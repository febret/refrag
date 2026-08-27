"""The room audio engine: transport clock, sequencing, mixing, mastering.

One AudioEngine exists per room.  render_block() produces the next stereo
block and is called either by the real-time streaming loop in app.py or in
a tight loop for offline WAV export.
"""

import copy
from bisect import bisect_left
import random

import numpy as np

from . import catalog, effects, synth
from .dsp import Biquad, cutoff_hz, onepole_smooth
from .state import (AUDIO_DEFAULT_BLOCK_SIZE, AUDIO_DEFAULT_SAMPLE_RATE, BANKS,
                    BEATS_PER_MEASURE)

BLOCK = AUDIO_DEFAULT_BLOCK_SIZE
SR = AUDIO_DEFAULT_SAMPLE_RATE


def shuffle_offset(beat, mode, amount):
    """Delay offbeat 8ths (march) or 16ths (swing) by up to half a division."""
    if amount <= 0:
        return 0.0
    div = 0.5 if mode == 0 else 0.25
    idx = round(beat / div)
    if abs(beat - idx * div) > 1e-6:
        return 0.0
    return div * amount * 0.5 if idx % 2 == 1 else 0.0


def _width_buffer_len(sample_rate, block_size):
    return max(2048, int(sample_rate * 0.02), int(block_size))


def _resize_tail_buffer(buf, target_len):
    if target_len == buf.shape[1]:
        return buf
    out = np.zeros((2, target_len))
    copy_len = min(target_len, buf.shape[1])
    if copy_len:
        out[:, -copy_len:] = buf[:, -copy_len:]
    return out


class MachineSlot:
    def __init__(self, sample_rate, block_size):
        self.engine = None
        self.mtype = None
        self.fx = [None, None]        # (etype, effect instance)
        self.eq = [Biquad() for _ in range(6)]   # 3 bands x stereo
        self.width_buf = np.zeros((2, _width_buffer_len(sample_rate, block_size)))
        self.vu = 0.0
        self.active_offs = []         # [(beat_off, note), ...] pending note-offs
        self.machine_ref = None
        self.active_pattern = None    # (bank, pattern)
        self.pattern_origin = 0.0
        self.queued_patterns = []
        self.transpose_step = 0
        self.transpose_loops = 0


class AudioEngine:
    def __init__(self, room):
        self.room = room
        room.engine = self
        self.sample_rate = AUDIO_DEFAULT_SAMPLE_RATE
        self.block_size = AUDIO_DEFAULT_BLOCK_SIZE
        self._sync_audio_config(room.doc, force=True)
        self.slots = [
            MachineSlot(self.sample_rate, self.block_size)
            for _ in range(len(room.doc["machines"]))
        ]
        self.master_fx = [None, None]
        self.master_delay = MasterDelay(self.sample_rate)
        self.master_reverb = effects.Reverb(sample_rate=self.sample_rate)
        self.master_eq = [Biquad() for _ in range(6)]
        self.master_lim = effects.Limiter(sample_rate=self.sample_rate)
        self.pos = float(room.doc["transport"].get("pos", 0.0))
        self.prev_outputs = {}
        self.master_vu = (0.0, 0.0)
        self.lim_gr = 0.0
        self.auto_values = {}     # (slot,param)->value currently applied
        self.live_recorded = {}   # (slot,note)->onset beat for live rec
        self._idle_blocks = 0
        self._tail_blocks = 0
        self._sequence_rev = None
        self._pattern_event_cache = {}
        self._song_event_cache = None

    def _sync_audio_config(self, doc, force=False):
        audio = doc.get("audio") or {}
        sr = int(audio.get("sample_rate", AUDIO_DEFAULT_SAMPLE_RATE))
        block = int(audio.get("block_size", AUDIO_DEFAULT_BLOCK_SIZE))
        if (not force and sr == self.sample_rate and block == self.block_size):
            return False
        self.sample_rate = sr
        self.block_size = block
        return True

    def _refresh_audio_runtime_state(self):
        self.master_delay = MasterDelay(self.sample_rate)
        self.master_reverb = effects.Reverb(sample_rate=self.sample_rate)
        self.master_lim = effects.Limiter(sample_rate=self.sample_rate)
        self.master_fx = [None, None]
        for s in self.slots:
            s.fx = [None, None]
            s.width_buf = _resize_tail_buffer(
                s.width_buf, _width_buffer_len(self.sample_rate, self.block_size))

    # -- external control ---------------------------------------------------

    def position(self):
        return self.pos

    def seek(self, beats):
        self.pos = float(beats)
        self._reset_pattern_runtime(self.pos)

    def wake(self):
        self._idle_blocks = 0

    def _reset_pattern_runtime(self, origin=None, clear_queues=True):
        origin = self.pos if origin is None else float(origin)
        for idx, s in enumerate(self.slots):
            m = self.room.machine(idx)
            s.machine_ref = m
            s.active_pattern = (
                (m["bank"], m["pattern"]) if m is not None else None)
            s.pattern_origin = origin
            if clear_queues:
                s.queued_patterns = []
            s.transpose_step = 0
            s.transpose_loops = 0
            s.active_offs = []
            if s.engine:
                s.engine.all_off()

    def transport_updated(self, was_playing, old_mode):
        t = self.room.doc["transport"]
        if not t["playing"] or t["mode"] == "song":
            self._reset_pattern_runtime(self.pos)
        elif (not was_playing or
              (old_mode != "pattern" and t["mode"] == "pattern")):
            self._reset_pattern_runtime(self.pos)

    def request_pattern(self, slot_idx, bank, pattern):
        with self.room.lock:
            m = self.room.machine(slot_idx)
            if m is None:
                return False
            t = self.room.doc["transport"]
            requested = (bank, pattern)
            if t["mode"] != "pattern":
                t["mode"] = "pattern"
                self._reset_pattern_runtime(self.pos)
                m["bank"], m["pattern"] = requested
                s = self.slots[slot_idx]
                s.active_pattern = requested
                s.pattern_origin = self.pos
                return "document"
            s = self.slots[slot_idx]
            self._sync_pattern_slot(slot_idx, m, self.pos)
            if not t["playing"]:
                changed = requested != s.active_pattern or bool(s.queued_patterns)
                m["bank"], m["pattern"] = requested
                s.active_pattern = requested
                s.pattern_origin = self.pos
                s.queued_patterns = []
                return "document" if changed else False
            s.queued_patterns.append(requested)
            if self.on_state_change:
                self.on_state_change()
            return "runtime"

    def clear_pattern_queue(self, slot_idx):
        s = self.slots[slot_idx]
        if not s.queued_patterns:
            return False
        s.queued_patterns = []
        if self.on_state_change:
            self.on_state_change()
        return True

    def set_looper_mode(self, slot_idx, mode):
        if mode == "random":
            self.clear_pattern_queue(slot_idx)

    def handle_note(self, slot, note, on, vel=1.0, flags=0):
        """Live note from a client (preview keyboard)."""
        with self.room.lock:
            doc = self.room.doc
            m = self.room.machine(slot)
            if m is None:
                return
            eng = self._engine_for(slot)
            if eng is None:
                return
            t = doc["transport"]
            if on:
                eng.note_on(int(note), float(vel), 0, int(flags))
                self._idle_blocks = 0
                if t["record"] and t["playing"] and t["mode"] == "pattern":
                    self.live_recorded[(slot, int(note))] = self.pos
            else:
                eng.note_off(int(note))
                key = (slot, int(note))
                if key in self.live_recorded:
                    onset = self.live_recorded.pop(key)
                    if t["record"] and t["playing"] and t["mode"] == "pattern":
                        self._record_note(
                            slot, int(note), onset, self.pos, vel)

    def _record_note(self, slot, note, onset, end, vel):
        m = self.room.machine(slot)
        if m is None:
            return
        pat = self.room.get_pattern(m, create=True)
        span = pat["length"] * BEATS_PER_MEASURE
        q = 0.25
        start = round((onset % span) / q) * q
        if start >= span:
            start = 0.0
        dur = max(q, min(end - onset, span - start))
        self.room.apply({"op": "add_note", "slot": slot, "note": note,
                         "start": start, "dur": dur, "vel": vel})
        if self.on_state_change:
            self.on_state_change()

    on_state_change = None    # set by app.py to broadcast live-recorded notes

    # -- engine management ----------------------------------------------------

    def _engine_for(self, slot_idx):
        m = self.room.machine(slot_idx)
        s = self.slots[slot_idx]
        if m is None:
            s.engine = None
            s.mtype = None
            s.machine_ref = None
            s.active_pattern = None
            s.queued_patterns = []
            s.transpose_step = 0
            s.transpose_loops = 0
            return None
        if s.engine is None or s.mtype != m["type"]:
            s.engine = synth.create_machine(m, sample_rate=self.sample_rate)
            s.mtype = m["type"]
        else:
            s.engine.update(m, sample_rate=self.sample_rate)
        return s.engine

    def _fx_chain(self, holder, fx_states):
        """Sync effect instances with state list [{type,params,bypass},...]."""
        for i in range(2):
            st = fx_states[i] if fx_states else None
            cur = holder[i]
            if st is None:
                holder[i] = None
            elif cur is None or cur[0] != st["type"]:
                holder[i] = (st["type"], effects.create_effect(
                    st["type"], sample_rate=self.sample_rate))
        return holder

    # -- sequencing -----------------------------------------------------------

    def _sync_pattern_slot(self, slot_idx, m, origin):
        s = self.slots[slot_idx]
        selected = (m["bank"], m["pattern"])
        if s.machine_ref is not m:
            initial_sync = s.machine_ref is None and s.active_pattern is None
            s.machine_ref = m
            s.active_pattern = selected
            s.pattern_origin = 0.0 if initial_sync else origin
            s.queued_patterns = []
            s.transpose_step = 0
            s.transpose_loops = 0
            s.active_offs = []
        elif s.active_pattern is None:
            s.active_pattern = selected
            s.pattern_origin = 0.0
        elif s.active_pattern != selected:
            s.active_pattern = selected
            s.pattern_origin = origin
            s.queued_patterns = []
            s.transpose_step = 0
            s.transpose_loops = 0
            s.active_offs = []
            if s.engine:
                s.engine.all_off()

    @staticmethod
    def _normalize_looper_mode(m):
        mode = m.get("looper_mode", "queue")
        return mode if mode in ("queue", "random") else "queue"

    @staticmethod
    def _normalize_looper_bank(m):
        return max(0, min(len(BANKS) - 1, int(m.get("looper_bank", m.get("bank", 0)))))

    @staticmethod
    def _transpose_steps_for_machine(m):
        legacy = max(-24, min(24, int(m.get("transpose", 0))))
        raw = m.get("transpose_steps")
        if not isinstance(raw, list) or len(raw) != 4:
            return [{"transpose": legacy, "loops": 1} for _ in range(4)]
        out = []
        for item in raw[:4]:
            if not isinstance(item, dict):
                item = {}
            out.append({
                "transpose": max(-24, min(24, int(item.get("transpose", legacy)))),
                "loops": max(1, min(4, int(item.get("loops", 1)))),
            })
        while len(out) < 4:
            out.append({"transpose": legacy, "loops": 1})
        return out

    def _current_transpose(self, slot_idx, m):
        if m["type"] == "beatbox":
            return 0
        steps = self._transpose_steps_for_machine(m)
        idx = self.slots[slot_idx].transpose_step % len(steps)
        return steps[idx]["transpose"]

    def _advance_transpose_step(self, slot_idx, m):
        if m["type"] == "beatbox":
            return
        steps = self._transpose_steps_for_machine(m)
        if not steps:
            return
        s = self.slots[slot_idx]
        idx = s.transpose_step % len(steps)
        loops = max(1, min(4, int(steps[idx].get("loops", 1))))
        s.transpose_loops += 1
        if s.transpose_loops >= loops:
            s.transpose_loops = 0
            s.transpose_step = (idx + 1) % len(steps)

    def _random_pattern_for_slot(self, m):
        bank = self._normalize_looper_bank(m)
        candidates = []
        for pattern in range(16):
            pat = m["patterns"].get(BANKS[bank] + str(pattern + 1))
            if pat and pat.get("notes"):
                candidates.append((bank, pattern))
        if not candidates:
            return None
        return random.choice(candidates)

    def _commit_queued_pattern(self, slot_idx, m, boundary):
        s = self.slots[slot_idx]
        next_pattern = None
        if s.queued_patterns:
            next_pattern = s.queued_patterns.pop(0)
        elif self._normalize_looper_mode(m) == "random":
            next_pattern = self._random_pattern_for_slot(m)
        if next_pattern is None:
            return
        bank, pattern = next_pattern
        s.active_pattern = (bank, pattern)
        s.pattern_origin = boundary
        changed = (m["bank"], m["pattern"]) != (bank, pattern)
        m["bank"], m["pattern"] = bank, pattern
        if changed:
            self.room.mark_changed()
            self._sequence_rev = self.room.rev
        if self.on_state_change:
            self.on_state_change()

    def _sync_sequence_cache(self):
        if self._sequence_rev == self.room.rev:
            return
        self._sequence_rev = self.room.rev
        self._pattern_event_cache.clear()
        self._song_event_cache = None

    def _compiled_pattern(self, slot_idx, patkey, pat, doc):
        cache_key = (slot_idx, patkey)
        cached = self._pattern_event_cache.get(cache_key)
        if cached is not None:
            return cached

        events = []
        shuffle = doc["shuffle"]
        smode = doc["shuffle_mode"]
        flourish_on = pat.get("flourish", {}).get("on", 1)
        for note in pat["notes"]:
            key, start, dur, vel = note[0], note[1], note[2], note[3]
            flags = note[4] if len(note) > 4 else 0
            if flags & 4:
                if not flourish_on:
                    continue
                flags &= ~4
            start = start + shuffle_offset(start, smode, shuffle)
            events.append((start, key, dur, vel, flags))
        events.sort()
        compiled = ([event[0] for event in events], events)
        self._pattern_event_cache[cache_key] = compiled
        return compiled

    @staticmethod
    def _select_events(compiled, lo, hi):
        starts, events = compiled
        first = bisect_left(starts, lo)
        last = bisect_left(starts, hi, first)
        return events[first:last]

    def _build_song_event_cache(self, doc):
        by_machine = [[] for _ in self.slots]
        for blk in doc["song"]:
            slot_idx = blk["machine"]
            if not 0 <= slot_idx < len(self.slots):
                continue
            m = self.room.machine(slot_idx)
            if m is None:
                continue
            patkey = BANKS[blk["bank"]] + str(blk["pattern"] + 1)
            pat = m["patterns"].get(patkey)
            if not pat:
                continue
            span = pat["length"] * BEATS_PER_MEASURE
            block_beats = blk["length"] * BEATS_PER_MEASURE
            if span <= 0 or block_beats <= 0:
                continue
            block_start = blk["start"] * BEATS_PER_MEASURE
            _, pattern_events = self._compiled_pattern(
                slot_idx, patkey, pat, doc)
            for start, key, dur, vel, flags in pattern_events:
                occurrence = start
                while occurrence < block_beats:
                    if occurrence >= 0:
                        by_machine[slot_idx].append(
                            (block_start + occurrence, key, dur, vel, flags))
                    occurrence += span

        compiled = []
        for events in by_machine:
            events.sort()
            compiled.append(([event[0] for event in events], events))
        self._song_event_cache = compiled

    def _pattern_events(self, slot_idx, m, b0, b1, doc):
        """Collect note on/off events for the machine in beat range [b0,b1)."""
        self._sync_sequence_cache()
        events = []
        mode = doc["transport"]["mode"]

        def emit(compiled, lo, hi, offset, transpose):
            for start, key, dur, vel, flags in self._select_events(
                    compiled, lo, hi):
                abs_on = offset + start
                key = max(0, min(127, key + transpose))
                events.append((abs_on, "on", key, vel, flags))
                events.append((abs_on + dur, "off", key, 0, 0))

        if mode == "pattern":
            self._sync_pattern_slot(slot_idx, m, b0)
            s = self.slots[slot_idx]
            cursor = b0
            while cursor < b1 - 1e-12:
                bank, pattern = s.active_pattern
                patkey = BANKS[bank] + str(pattern + 1)
                pat = m["patterns"].get(patkey)
                span = ((pat["length"] if pat else 1) *
                        BEATS_PER_MEASURE)
                if span <= 0:
                    break
                cycle = max(0, int(np.floor(
                    (cursor - s.pattern_origin) / span + 1e-12)))
                cycle_start = s.pattern_origin + cycle * span
                local_start = max(0.0, cursor - cycle_start)
                boundary = cycle_start + span
                segment_end = min(b1, boundary)
                if pat:
                    compiled = self._compiled_pattern(
                        slot_idx, patkey, pat, doc)
                    transpose = self._current_transpose(slot_idx, m)
                    emit(compiled, local_start,
                         local_start + segment_end - cursor, cycle_start,
                         transpose)
                cursor = segment_end
                if cursor >= boundary - 1e-12:
                    self._commit_queued_pattern(slot_idx, m, boundary)
                    self._advance_transpose_step(slot_idx, m)
                if segment_end >= b1 - 1e-12:
                    break
        else:
            if self._song_event_cache is None:
                self._build_song_event_cache(doc)
            emit(self._song_event_cache[slot_idx], b0, b1, 0, self._current_transpose(slot_idx, m))
        return events

    def _apply_events(self, slot_idx, eng, events, b0, spb):
        """spb = samples per beat."""
        s = self.slots[slot_idx]
        block_size = self.block_size
        # scheduled offs from previous blocks
        due = [e for e in s.active_offs if e[0] < b0 + block_size / spb]
        s.active_offs = [e for e in s.active_offs if e[0] >= b0 + block_size / spb]
        for off_t, key in due:
            off = int(max(0, (off_t - b0) * spb))
            eng.note_off(key, min(off, block_size - 1))
        for t, kind, key, vel, flags in sorted(events):
            off = int(max(0, (t - b0) * spb))
            if kind == "on":
                if off < block_size:
                    eng.note_on(key, vel, off, flags)
            else:
                if off < block_size:
                    eng.note_off(key, off)
                else:
                    s.active_offs.append((t, key))

    # -- automation -----------------------------------------------------------

    def _apply_automation(self, doc):
        applied = {}
        t = doc["transport"]
        if not t["playing"]:
            self.auto_values = {}
            return applied
        # song automation
        if t["mode"] == "song":
            for key, entry in doc["automation"]["song"].items():
                slot_s, param = key.split(":", 1)
                keys = entry.get("keys", [])
                if not keys:
                    continue
                val = self._interp_keys(keys, self.pos)
                applied[(int(slot_s), param)] = val
        else:
            for key, entry in doc["automation"]["pattern"].items():
                slot_s, patkey, param = key.split(":", 2)
                slot = int(slot_s)
                m = self.room.machine(slot)
                if m is None:
                    continue
                if BANKS[m["bank"]] + str(m["pattern"] + 1) != patkey:
                    continue
                pat = m["patterns"].get(patkey)
                if not pat:
                    continue
                span = pat["length"] * BEATS_PER_MEASURE
                bars = entry.get("bars", [])
                if not bars or span <= 0:
                    continue
                origin = self.slots[slot].pattern_origin
                idx = int(((self.pos - origin) % span) * 8) % len(bars)
                val = bars[idx]
                if val is None:
                    # find previous set bar
                    for back in range(1, len(bars)):
                        v2 = bars[(idx - back) % len(bars)]
                        if v2 is not None:
                            val = v2
                            break
                if val is None:
                    continue
                prev = self.auto_values.get((slot, param))
                smooth = entry.get("smooth", 0.5)
                if prev is not None and smooth > 0 and isinstance(val, (int, float)):
                    val = prev + (val - prev) * (1 - smooth * 0.85)
                applied[(slot, param)] = val
        self.auto_values = applied
        return applied

    @staticmethod
    def _interp_keys(keys, pos):
        if pos <= keys[0][0]:
            return keys[0][1]
        if pos >= keys[-1][0]:
            return keys[-1][1]
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            if a[0] <= pos <= b[0]:
                if b[0] - a[0] < 1e-9 or not isinstance(a[1], (int, float)):
                    return a[1]
                f = (pos - a[0]) / (b[0] - a[0])
                return a[1] + (b[1] - a[1]) * f
        return keys[-1][1]

    # -- main render ----------------------------------------------------------

    def render_block(self):
        room = self.room
        with room.lock:
            if self._sync_audio_config(room.doc):
                self._refresh_audio_runtime_state()
            return self._render_block_locked(room.doc)

    def _render_block_locked(self, doc):
        n = self.block_size
        t = doc["transport"]
        bpm = doc["bpm"]
        spb = self.sample_rate * 60.0 / bpm
        b0 = self.pos
        b1 = b0 + n / spb

        auto = self._apply_automation(doc)

        machines = doc["machines"]
        any_solo = any(m and m["solo"] for m in machines)
        mix = np.zeros((2, n))
        send_delay = np.zeros((2, n))
        send_reverb = np.zeros((2, n))
        outputs = {}
        lines = {}

        for idx, m in enumerate(machines):
            s = self.slots[idx]
            if m is None:
                s.vu = 0.0
                continue
            eng = self._engine_for(idx)
            if eng is None:
                continue
            if t["playing"]:
                events = self._pattern_events(idx, m, b0, b1, doc)
                self._apply_events(idx, eng, events, b0, spb)

            # machine-level automation overrides
            slot_auto = {p: v for (sl, p), v in auto.items() if sl == idx
                         and not p.startswith("mixer.")}
            if slot_auto:
                for pkey, val in slot_auto.items():
                    if pkey in m["params"]:
                        m["params"][pkey] = val

            if not eng.active() and not (t["playing"]):
                dry = np.zeros((2, n))
            else:
                ctx = {"outputs": outputs, "prev_outputs": self.prev_outputs,
                       "bpm": bpm, "lines": lines}
                dry = eng.render(n, ctx)
            outputs[idx] = dry

            # insert effects
            self._fx_chain(s.fx, m["effects"])
            wet = dry
            for i in range(2):
                st = m["effects"][i]
                if st and s.fx[i] and not st.get("bypass"):
                    ctx = {"bpm": bpm, "lines": lines}
                    wet = s.fx[i][1].process(wet, st["params"], ctx)

            # mixer strip
            mx = dict(m["mixer"])
            for (sl, pkey), val in auto.items():
                if sl == idx and pkey.startswith("mixer."):
                    mx[pkey[6:]] = val
            wet = self._strip(s, wet, mx)
            lines[idx] = wet
            s.vu = float(np.max(np.abs(wet))) if wet.size else 0.0

            muted = m["mute"] or (any_solo and not m["solo"])
            if not muted:
                vol = mx["volume"]
                sig = wet * vol
                mix += sig
                if mx["send_delay"] > 0:
                    send_delay += sig * mx["send_delay"]
                if mx["send_reverb"] > 0:
                    send_reverb += sig * mx["send_reverb"]

        self.prev_outputs = outputs

        if (np.max(np.abs(mix)) > 1e-6 or
                np.max(np.abs(send_delay)) > 1e-6 or
                np.max(np.abs(send_reverb)) > 1e-6):
            self._tail_blocks = int(8 * self.sample_rate / self.block_size)
        elif self._tail_blocks > 0:
            self._tail_blocks -= 1

        # master section
        mp = dict(doc["master"]["params"])
        for (sl, pkey), val in auto.items():
            if sl == -1 and pkey in mp:
                mp[pkey] = val

        if mp["dly_bypass"]:
            mix = mix + self.master_delay.process(send_delay, mp, bpm) * mp["dly_wet"]
        if mp["rev_bypass"]:
            rp = {"room": mp["rev_room"], "damp": mp["rev_damping"],
                  "delay": mp["rev_predelay"], "width": mp["rev_stereo_spread"],
                  "wet": 1.0}
            rev = self.master_reverb.process(send_reverb, rp, None) - send_reverb * 0.6
            mix = mix + rev * mp["rev_wet"]

        self._fx_chain(self.master_fx, doc["master"]["effects"])
        for i in range(2):
            st = doc["master"]["effects"][i]
            if st and self.master_fx[i] and not st.get("bypass"):
                mix = self.master_fx[i][1].process(mix, st["params"], {"bpm": bpm})

        if mp["eq_bypass"]:
            mix = self._master_eq(mix, mp)
        if mp["lim_bypass"]:
            lp = {"pre": mp["lim_pre"], "attack": mp["lim_attack"],
                  "release": mp["lim_release"], "post": mp["lim_post"]}
            mix = self.master_lim.process(mix, lp, None)
            self.lim_gr = self.master_lim.gr

        mix *= mp["volume"]
        self.master_vu = (float(np.max(np.abs(mix[0]))) if mix.size else 0.0,
                          float(np.max(np.abs(mix[1]))) if mix.size else 0.0)

        # advance transport
        if t["playing"]:
            newpos = b1
            loop = t.get("loop")
            if t["mode"] == "song" and loop:
                loop_start = loop[0] * BEATS_PER_MEASURE
                loop_end = loop[1] * BEATS_PER_MEASURE
                if newpos >= loop_end and loop_end > loop_start:
                    newpos = loop_start + (newpos - loop_end)
                    for s in self.slots:
                        if s.engine:
                            s.engine.all_off()
                        s.active_offs = []
            elif t["mode"] == "pattern":
                pass   # patterns loop naturally by modulo
            self.pos = newpos
            t["pos"] = self.pos

        np.clip(mix, -1.5, 1.5, out=mix)
        return mix

    def _strip(self, s, x, mx):
        out = x
        # 3-band EQ (low shelf 250, peak 1200, high shelf 5000)
        bands = (("lowshelf", 250.0, mx["eq_bass"]),
                 ("peak", 1200.0, mx["eq_mid"]),
                 ("highshelf", 5000.0, mx["eq_high"]))
        for bi, (kind, f0, gain) in enumerate(bands):
            if abs(gain) < 0.01:
                continue
            for c in range(2):
                bq = s.eq[bi * 2 + c]
                bq.set(kind, f0, 0.7, sr=self.sample_rate, gain_db=gain * 12.0)
                out = out.copy() if out is x else out
                out[c] = bq.process(out[c])
        # width: micro-delay one channel
        w = mx["width"]
        if abs(w) > 0.02:
            d = int(abs(w) * 0.008 * self.sample_rate)
            if d > 0:
                ch = 0 if w < 0 else 1
                buf = s.width_buf[ch]
                sig = out[ch]
                out = out.copy() if out is x else out
                if d >= len(sig):
                    out[ch] = buf[-d:-d + len(sig)]
                else:
                    out[ch, :d] = buf[-d:]
                    out[ch, d:] = sig[:-d]
                if len(sig) >= len(buf):
                    buf[:] = sig[-len(buf):]
                else:
                    buf[:-len(sig)] = buf[len(sig):]
                    buf[-len(sig):] = sig
        # pan
        pan = mx["pan"]
        if abs(pan) > 0.01:
            gl = np.sqrt(0.5 * (1 - pan)) * 1.414
            gr = np.sqrt(0.5 * (1 + pan)) * 1.414
            out = out.copy() if out is x else out
            out[0] *= gl
            out[1] *= gr
        return out

    def _master_eq(self, x, mp):
        bass_f = 60 + mp["eq_bass_freq"] * 440       # 60..500
        mid_f = 500 + mp["eq_mid_freq"] * 4500       # 500..5000
        bands = (("lowshelf", bass_f, mp["eq_bass"]),
                 ("peak", np.sqrt(bass_f * mid_f), mp["eq_mid"]),
                 ("highshelf", mid_f, mp["eq_high"]))
        out = x
        for bi, (kind, f0, gain) in enumerate(bands):
            if abs(gain) < 0.01:
                continue
            for c in range(2):
                bq = self.master_eq[bi * 2 + c]
                bq.set(kind, f0, 0.7, sr=self.sample_rate, gain_db=gain * 12.0)
                out[c] = bq.process(out[c])
        return out

    # -- vu/status ------------------------------------------------------------

    def status(self):
        doc = self.room.doc
        vus = [round(s.vu, 3) for s in self.slots]
        auto = {f"{sl}:{p}": (round(v, 4) if isinstance(v, float) else v)
                for (sl, p), v in self.auto_values.items()}
        looper = {}
        for idx, m in enumerate(doc["machines"]):
            if m is None:
                continue
            s = self.slots[idx]
            active = s.active_pattern or (m["bank"], m["pattern"])
            patkey = BANKS[active[0]] + str(active[1] + 1)
            pat = m["patterns"].get(patkey)
            span = (pat["length"] if pat else 1) * BEATS_PER_MEASURE
            progress = 0.0
            if (doc["transport"]["playing"] and
                    doc["transport"]["mode"] == "pattern" and span > 0):
                progress = ((self.pos - s.pattern_origin) % span) / span
            entry = {
                "bank": active[0],
                "pattern": active[1],
                "progress": round(progress, 4),
                "mode": self._normalize_looper_mode(m),
                "looper_bank": self._normalize_looper_bank(m),
            }
            if s.queued_patterns:
                entry["queue"] = [
                    {"bank": bank, "pattern": pattern}
                    for bank, pattern in s.queued_patterns
                ]
                entry["queued_bank"] = s.queued_patterns[0][0]
                entry["queued_pattern"] = s.queued_patterns[0][1]
            if m["type"] != "beatbox":
                entry["transpose_step"] = s.transpose_step
            looper[str(idx)] = entry
        st = {"pos": round(self.pos, 4), "vu": vus,
              "master_vu": [round(self.master_vu[0], 3),
                            round(self.master_vu[1], 3)],
              "lim_gr": round(self.lim_gr, 3),
              "audio": {"sample_rate": self.sample_rate,
                        "block_size": self.block_size},
              "auto": auto, "looper": looper}
        for idx, m in enumerate(doc["machines"]):
            if m and m["type"] == "vocoder" and self.slots[idx].engine:
                st.setdefault("vocoder_vu", {})[str(idx)] = [
                    round(float(v), 3) for v in self.slots[idx].engine.band_vu]
        return st

    def is_idle(self):
        doc = self.room.doc
        if doc["transport"]["playing"]:
            return False
        return (self._tail_blocks <= 0 and
                not any(s.engine and s.engine.active() for s in self.slots))


class MasterDelay:
    """Global multi-tap delay with per-tap pan and looping."""

    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.buf = np.zeros((2, sample_rate * 4))
        self.w = 0
        self.lp = np.zeros(2)

    def process(self, x, mp, bpm):
        n = x.shape[1]
        steps = int(mp["dly_steps"]) + 1
        if mp["dly_sync"]:
            opts = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
            beats = opts[int(round(mp["dly_time"] * (len(opts) - 1)))]
            D = beats * 60.0 / bpm * self.sample_rate
        else:
            D = (0.02 + mp["dly_time"] * 1.2) * self.sample_rate
        D = int(np.clip(D, 64, self.buf.shape[1] // (steps + 1)))
        fb = mp["dly_feedback"]
        damp = mp["dly_damping"]
        idx = (self.w + np.arange(n)) % self.buf.shape[1]
        out = np.zeros_like(x)
        pans = [mp["dly_pan1"], mp["dly_pan2"]]
        write = x.copy()
        if mp["dly_first_tap"]:
            write *= fb
        acc = np.zeros_like(x)
        for tap in range(steps):
            rd = (idx - D * (tap + 1)) % self.buf.shape[1]
            tapL = self.buf[0, rd]
            tapR = self.buf[1, rd]
            g = fb ** tap
            pan = pans[tap % 2]
            gl = np.sqrt(0.5 * (1 - pan)) * 1.414
            gr = np.sqrt(0.5 * (1 + pan)) * 1.414
            out[0] += tapL * g * gl
            out[1] += tapR * g * gr
            if tap == steps - 1:
                acc[0] = tapL * g
                acc[1] = tapR * g
        if damp > 0:
            coef = damp * 0.9
            for c in range(2):
                out[c], self.lp[c] = onepole_smooth(out[c], coef, self.lp[c])
        loop_in = acc * fb if mp["dly_loop"] else 0
        self.buf[0, idx] = write[0] + (loop_in[0] if mp["dly_loop"] else 0)
        self.buf[1, idx] = write[1] + (loop_in[1] if mp["dly_loop"] else 0)
        self.w = (self.w + n) % self.buf.shape[1]
        return out


# ---------------------------------------------------------------------------
# Offline song export
# ---------------------------------------------------------------------------

def render_song(room, loop_only=False):
    """Render the room's song to a stereo float array (offline)."""
    doc = room.doc
    audio = doc.get("audio") or {}
    sample_rate = int(audio.get("sample_rate", AUDIO_DEFAULT_SAMPLE_RATE))
    block_size = int(audio.get("block_size", AUDIO_DEFAULT_BLOCK_SIZE))
    engine = AudioEngine.__new__(AudioEngine)
    engine.room = room
    engine.sample_rate = sample_rate
    engine.block_size = block_size
    engine.slots = [MachineSlot(sample_rate, block_size)
                    for _ in range(len(doc["machines"]))]
    engine.master_fx = [None, None]
    engine.master_delay = MasterDelay(sample_rate)
    engine.master_reverb = effects.Reverb(sample_rate=sample_rate)
    engine.master_eq = [Biquad() for _ in range(6)]
    engine.master_lim = effects.Limiter(sample_rate=sample_rate)
    engine.prev_outputs = {}
    engine.master_vu = (0.0, 0.0)
    engine.lim_gr = 0.0
    engine.auto_values = {}
    engine.live_recorded = {}
    engine.on_state_change = None
    engine._idle_blocks = 0
    engine._tail_blocks = 0
    engine._sequence_rev = None
    engine._pattern_event_cache = {}
    engine._song_event_cache = None

    with room.lock:
        saved_transport = copy.deepcopy(doc["transport"])
        loop = doc["transport"].get("loop")
        if loop_only and loop and loop[1] > loop[0]:
            start_beat = loop[0] * BEATS_PER_MEASURE
            end_beat = loop[1] * BEATS_PER_MEASURE
            tail = 0.0
        else:
            start_beat = 0.0
            end_beat = 0.0
            for blk in doc["song"]:
                end_beat = max(end_beat, (blk["start"] + blk["length"])
                               * BEATS_PER_MEASURE)
            if end_beat == 0:
                end_beat = 8 * BEATS_PER_MEASURE
            tail = 2.0    # seconds of decay after last note
        doc["transport"]["playing"] = True
        doc["transport"]["mode"] = "song"
        doc["transport"]["loop"] = None
        engine.pos = start_beat
        spb = sample_rate * 60.0 / doc["bpm"]
        total = int((end_beat - start_beat) * spb + tail * sample_rate)
        chunks = []
        try:
            done = 0
            while done < total:
                blk = engine._render_block_locked(doc)
                chunks.append(blk)
                done += blk.shape[1]
        finally:
            doc["transport"].update(saved_transport)
            room.engine = getattr(room, "engine", None)
    out = np.concatenate(chunks, axis=1)[:, :total]
    return out
