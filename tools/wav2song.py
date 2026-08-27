"""wav2song: generate a refrag song (room session JSON) from a WAV loop.

Pipeline:
  1. Load the WAV and detect tempo + grid offset (onset-flux fit).
  2. Transcribe drums (onset classifier) and pitched material
     (Basic Pitch via server.aimatch) on band-split copies.
  3. Detect sustained spectral peaks and build padsynth drone stacks.
  4. Assemble a room doc: beatbox drums, subsynth bass/chords/highs,
     padsynth drones, with patterns and song blocks covering the clip.
  5. Simplify patterns musically: grid quantization, minimum durations,
     chord grouping, and loop detection into short repeating patterns.
  6. Auto-balance: render offline, compare per-band log-mel energy with
     the input, adjust layer gains, repeat --tune times.
  7. Write the session JSON (plus optional rendered WAV and score report).

Every internal knob can be overridden through a YAML configuration file
passed with --cfg; see doc/wav2song.md for the full schema.

Usage:
  python tools/wav2song.py input.wav [-o name] [--cfg cfg.yaml] [--bpm F]
         [--tune N] [--no-simplify] [--no-drums] [--no-bass] [--no-chords]
         [--no-drones] [--max-chord N] [--render out.wav] [--report]
         [--dump-cfg]
"""

import argparse
import copy
import json
import math
import os
import sys
import threading
import wave
from collections import defaultdict

import numpy as np
import scipy.signal
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import aimatch                                  # noqa: E402
from server.engine import render_song                       # noqa: E402
from server.state import SESSION_DIR, Room, new_machine, new_room_doc  # noqa: E402

SR = 44100

# ---------------------------------------------------------------------------
# configuration
#
# DEFAULTS is the single source of truth for every tunable knob.  A YAML file
# passed with --cfg is deep-merged over it; explicit CLI flags win over both.
# ---------------------------------------------------------------------------

DEFAULTS = {
    "tempo": {
        "bpm": None,              # fixed tempo; null = autodetect
        "candidates": 5,          # autocorrelation candidates to try
        "min_bpm": 60.0,
        "max_bpm": 200.0,
        "fold_low": 70.0,         # fold octave multiples into this range
        "fold_high": 190.0,
        "fit_range": 3.0,         # +/- BPM refined around each candidate
        "fit_step": 0.02,         # BPM resolution of the grid fit
        "offset_steps": 20,       # grid-offset resolutions per 16th
    },
    "grid": {
        "step": 0.25,             # base grid in beats (0.25 = 16th notes)
        "vel_levels": [0.4, 0.6, 0.8, 1.0],
        "vel_floor": 0.5,         # transcription amp -> velocity mapping
    },
    "simplify": {
        "enabled": True,
        "max_chord": 5,           # max simultaneous notes per chord
        "pitched_grid": 0.5,      # grid for chord-type layers (beats)
        "min_dur": {"bass": 0.5, "chord": 1.0},
        "loop_lengths": [4.0, 8.0, 16.0],   # candidate loops (beats)
        "loop_coverage": 0.6,     # notes a loop must explain
        "loop_precision": 0.4,    # predicted hits that must be real
        "loop_min_instances": 0.6,  # fraction of instances a note needs
        "chunk_measures": 4,      # fallback pattern size (measures)
        "raw_chunk_measures": 8,  # pattern size when simplify is off
    },
    "layers": {
        "drums": {
            "enabled": True,
            "snare_offbeat_to_hat": True,
            "offbeat_tolerance": 0.3,      # beats away from 2/4
            "kit": ["kick", "snare", "clhat", "ophat", "clap",
                    "tom_lo", "tom_hi", "crash"],
            "channel_volumes": [1.3, 0.9, 0.9, 0.8, 0.8, 0.8, 0.8, 0.6],
            "channel_punch": [0.3, 0, 0, 0, 0, 0, 0, 0],
            "params": {},                  # beatbox machine param overrides
            "mixer": {"eq_high": 0.2},
        },
        "bass": {
            "enabled": True,
            "band": [0, 260],              # analysis band-pass (Hz)
            "note_range": [24, 59],        # accepted MIDI notes
            "dur_scale": 1.0,
            "params": {"osc1_wave": 2, "osc2_wave": 1, "osc2_octave": -1,
                       "osc_mix": 0.55, "flt_type": 1, "flt_cutoff": 0.35,
                       "flt_res": 0.1, "vol_release": 0.08, "volume": 1.1},
            "mixer": {"eq_bass": 0.2},
        },
        "chords": {
            "enabled": True,
            "band": [200, 2200],
            "note_range": [48, 127],
            "dur_scale": 1.2,
            "params": {"osc1_wave": 2, "osc2_wave": 3, "osc2_cents": 8,
                       "osc_mix": 0.5, "flt_type": 1, "flt_cutoff": 0.7,
                       "flt_res": 0.05, "vol_attack": 0.02,
                       "vol_release": 0.15, "volume": 0.9},
            "mixer": {"eq_high": 0.2},
        },
        "highs": {
            "enabled": True,
            "band": None,                  # null = full-bandwidth analysis
            "note_range": [76, 127],
            "dur_scale": 1.2,
            "params": {"osc1_wave": 2, "osc2_wave": 3, "osc2_cents": 12,
                       "osc_mix": 0.5, "flt_type": 0, "vol_attack": 0.02,
                       "vol_release": 0.25, "volume": 0.9},
            "mixer": {"eq_high": 0.2},
        },
        "drones": {
            "enabled": True,
            "max_notes": 12,               # spectral peaks to keep
            "freq_range": [80, 4000],      # peak search range (Hz)
            "prominence_db": 6.0,          # peak prominence threshold
            "vel_db_range": 24.0,          # dB below top peak -> velocity 0.4
            "group_size": 6,               # notes per padsynth machine
            "max_machines": 2,
            "note_beats": 4.0,             # length of each drone chord
            "harmonics": [1.0, 0.6, 0.4, 0.3, 0.22, 0.16, 0.12, 0.09,
                          0.07, 0.05, 0.04, 0.03, 0.025, 0.02, 0.015,
                          0.012, 0.01, 0.008, 0.006, 0.005, 0.004,
                          0.003, 0.002, 0.002],
            "width": 0.35,
            "params": {"vol_attack": 0.05, "vol_decay": 0.2,
                       "vol_sustain": 1.0, "vol_release": 0.3,
                       "gain1": 1.2, "volume": 1.2},
            "mixer": {},
        },
    },
    "tune": {
        "rounds": 2,              # auto-balance iterations (0 = off)
        "max_gain_db": 6.0,       # per-iteration gain change clamp
        "volume_min": 0.05,
        "volume_max": 2.0,
        "kick_band_hz": 120.0,    # sub band driving the kick channel
        "register_low_ratio": 0.5,   # widen machine register downward
        "register_high_ratio": 6.0,  # ... and upward (harmonics)
    },
    "score": {
        "n_mels": 64,
        "fmin": 30.0,
        "fmax": 16000.0,
        "nperseg": 2048,
        "hop": 1024,
    },
}


def deep_merge(base, override):
    """Recursively merge override into a copy of base."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if (key in out and isinstance(out[key], dict)
                and isinstance(value, dict)):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def validate_cfg(cfg, defaults=None, path=""):
    """Reject unknown keys so typos in a cfg file fail loudly."""
    defaults = DEFAULTS if defaults is None else defaults
    for key, value in cfg.items():
        if key not in defaults:
            raise KeyError("unknown cfg key: %s%s" % (path, key))
        if (isinstance(defaults[key], dict) and isinstance(value, dict)
                and key not in ("params", "mixer", "min_dur")):
            validate_cfg(value, defaults[key], path + key + ".")


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("cfg root must be a mapping")
    validate_cfg(data)
    return deep_merge(DEFAULTS, data)


# ---------------------------------------------------------------------------
# audio io + analysis
# ---------------------------------------------------------------------------

def load_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError("unsupported sample width: %d bytes" % width)
    x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        x = scipy.signal.resample_poly(x, SR, sr).astype(np.float32)
    return x


def save_wav(path, stereo):
    pcm = (np.clip(stereo, -1, 1).T * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def onset_envelope(x, hop=512):
    f, t, S = scipy.signal.spectrogram(x, SR, nperseg=2048, noverlap=2048 - hop)
    L = np.log1p(S * 1000)
    flux = np.maximum(0, np.diff(L, axis=1, prepend=0)).sum(axis=0)
    return t, flux / (flux.max() or 1.0)


def detect_bpm_candidates(x, tc):
    """Tempo candidates from onset-flux autocorrelation."""
    t, flux = onset_envelope(x)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    hop_s = t[1] - t[0] if len(t) > 1 else 512 / SR
    lags = np.arange(1, len(ac))
    bpms = 60.0 / (lags * hop_s)
    mask = (bpms >= tc["min_bpm"]) & (bpms <= tc["max_bpm"])
    if not mask.any():
        return [120.0]
    order = np.argsort(ac[lags[mask]])[::-1]
    cands = []

    def push(bpm):
        # fold metrical multiples into the useful range
        while bpm < tc["fold_low"]:
            bpm *= 2
        while bpm > tc["fold_high"]:
            bpm /= 2
        if all(abs(bpm - c) > 2.0 for c in cands):
            cands.append(bpm)

    for i in order[:tc["candidates"] * 2]:
        bpm = float(bpms[mask][i])
        push(bpm)
        push(bpm * 2)
        if len(cands) >= tc["candidates"]:
            break
    return cands[:tc["candidates"]] or [120.0]


def fit_grid(x, bpm_hint, tc):
    """Refine (bpm, offset_seconds, score) maximizing onset energy on the grid."""
    t, flux = onset_envelope(x)
    best = (-1.0, bpm_hint, 0.0)
    off_step = 1.0 / tc["offset_steps"]
    for bpm in np.arange(bpm_hint - tc["fit_range"],
                         bpm_hint + tc["fit_range"] + 1e-9, tc["fit_step"]):
        if bpm <= 0:
            continue
        step = 60.0 / bpm / 4.0
        ph = (t / step) % 1.0
        for off_frac in np.arange(0, 1.0, off_step):
            d = np.minimum(np.abs(ph - off_frac), 1 - np.abs(ph - off_frac))
            score = float(np.sum(flux * np.maximum(0, 1 - d * 8)))
            if score > best[0]:
                best = (score, float(bpm), float(off_frac * step))
    return best[1], best[2], best[0]


def detect_tempo(x, cfg):
    """Best (bpm, offset) across autocorrelation candidates + grid fit."""
    tc = cfg["tempo"]
    if tc["bpm"]:
        bpm, offset, _ = fit_grid(x, float(tc["bpm"]), tc)
        return bpm, offset
    best = (-1.0, 120.0, 0.0)
    for cand in detect_bpm_candidates(x, tc):
        bpm, offset, score = fit_grid(x, cand, tc)
        if score > best[0]:
            best = (score, bpm, offset)
    return best[1], best[2]


def bandpass(x, lo, hi):
    ny = SR / 2.0
    if lo <= 20:
        b, a = scipy.signal.butter(4, hi / ny, "low")
    elif hi >= ny - 100:
        b, a = scipy.signal.butter(4, lo / ny, "high")
    else:
        b, a = scipy.signal.butter(4, [lo / ny, hi / ny], "band")
    return scipy.signal.filtfilt(b, a, x).astype(np.float32)


def detect_drone_stack(x, dc):
    """Sustained spectral peaks -> [(midi, velocity)] sorted by pitch.

    Uses the median magnitude over time so transient content is ignored.
    """
    f, t, S = scipy.signal.spectrogram(x, SR, nperseg=8192,
                                       noverlap=8192 - 2048, mode="psd")
    med = np.median(S, axis=1)
    L = 10 * np.log10(med + 1e-12)
    peaks, props = scipy.signal.find_peaks(L, prominence=dc["prominence_db"])
    lo, hi = dc["freq_range"]
    sel = [(f[i], L[i]) for i in peaks if lo <= f[i] <= hi]
    if not sel:
        return []
    sel.sort(key=lambda p: -p[1])
    top_db = sel[0][1]
    stack = {}
    for freq, db in sel[:dc["max_notes"]]:
        midi = int(round(69 + 12 * math.log2(freq / 440.0)))
        vel = max(0.4, min(1.0, 1.0 + (db - top_db) / dc["vel_db_range"]))
        if midi not in stack or vel > stack[midi]:
            stack[midi] = round(vel, 2)
    return sorted(stack.items())


# ---------------------------------------------------------------------------
# machine construction
# ---------------------------------------------------------------------------

def make_machine(mtype, name, params=None, mixer=None, **extra):
    m = new_machine(mtype, name)
    for k, v in (params or {}).items():
        if k not in m["params"]:
            raise KeyError("%s: unknown param %r" % (mtype, k))
        m["params"][k] = v
    for k, v in (mixer or {}).items():
        if k not in m["mixer"]:
            raise KeyError("mixer: unknown param %r" % k)
        m["mixer"][k] = v
    for k, v in extra.items():
        m[k] = v
    return m


def drums_machine(lc):
    m = make_machine("beatbox", "DRUMS", params=lc["params"], mixer=lc["mixer"])
    for i, ch in enumerate(m["channels"]):
        if i < len(lc["kit"]):
            ch["sample"] = lc["kit"][i]
        if i < len(lc["channel_volumes"]):
            ch["params"]["volume"] = lc["channel_volumes"][i]
        if i < len(lc["channel_punch"]):
            ch["params"]["punch"] = lc["channel_punch"][i]
    return m


def synth_machine(name, lc):
    return make_machine("subsynth", name, params=lc["params"],
                        mixer=lc["mixer"])


def drone_machine(name, dc):
    return make_machine("padsynth", name, params=dc["params"],
                        mixer=dc["mixer"], harm1=list(dc["harmonics"]),
                        width1=dc["width"])


# ---------------------------------------------------------------------------
# musical simplification (quantize / merge / chords / loops)
# ---------------------------------------------------------------------------

def _q(x, step):
    return round(round(x / step) * step, 4)


def _qvel(v, levels):
    return min(levels, key=lambda level: abs(level - v))


def simplify_notes(notes, mode, cfg):
    """notes: [key, start, dur, vel] absolute beats. mode: drum|bass|chord|drone."""
    sc = cfg["simplify"]
    base_grid = cfg["grid"]["step"]
    levels = cfg["grid"]["vel_levels"]
    drum = mode == "drum"
    grid = base_grid if mode in ("drum", "bass") else sc["pitched_grid"]
    mindur = base_grid if drum else sc["min_dur"].get(mode, 1.0)
    cleaned = {}
    for key, start, dur, vel in notes:
        s = _q(start, grid)
        d = base_grid if drum else max(mindur, _q(dur, 0.5))
        v = _qvel(vel, levels)
        k = (key, s)
        if k not in cleaned or v > cleaned[k][3]:
            cleaned[k] = [key, s, d, v]
    notes = sorted(cleaned.values(), key=lambda n: (n[1], n[0]))
    if mode in ("drum", "drone"):
        return notes
    # merge successive same-pitch notes separated by small gaps
    by_key = defaultdict(list)
    for n in notes:
        by_key[n[0]].append(n)
    merged = []
    for key, seq in by_key.items():
        cur = seq[0]
        for n in seq[1:]:
            if n[1] <= cur[1] + cur[2] + grid:
                cur[2] = _q(max(cur[1] + cur[2], n[1] + n[2]) - cur[1], 0.5)
                cur[3] = max(cur[3], n[3])
            else:
                merged.append(cur)
                cur = n
        merged.append(cur)
    notes = sorted(merged, key=lambda n: (n[1], n[0]))
    # chord grouping: same start -> shared duration, capped voice count
    by_start = defaultdict(list)
    for n in notes:
        by_start[n[1]].append(n)
    out = []
    for start in sorted(by_start):
        group = by_start[start]
        group.sort(key=lambda n: -n[3])
        group = group[:sc["max_chord"]]
        d = max(n[2] for n in group)
        for n in group:
            n[2] = d
        out.extend(sorted(group, key=lambda n: n[0]))
    return out


def find_loop(notes, total_beats, cfg):
    """Smallest configured loop whose consensus explains most notes."""
    if not notes:
        return None, None
    sc = cfg["simplify"]
    grid = cfg["grid"]["step"]
    for L in sc["loop_lengths"]:
        L = float(L)
        instances = int(total_beats // L)
        if instances < 2:
            continue
        seen = defaultdict(list)
        in_range = 0
        for key, start, dur, vel in notes:
            if start >= instances * L:
                continue
            in_range += 1
            seen[(key, _q(start % L, grid))].append((int(start // L), dur, vel))
        if not in_range:
            continue
        need = max(2, int(math.ceil(instances * sc["loop_min_instances"])))
        consensus = {}
        for (key, folded), occs in seen.items():
            if len({i for i, _, _ in occs}) >= need:
                durs = sorted(d for _, d, _ in occs)
                vels = sorted(v for _, _, v in occs)
                consensus[(key, folded)] = (durs[len(durs) // 2],
                                            vels[len(vels) // 2])
        if not consensus:
            continue
        covered = sum(1 for key, start, dur, vel in notes
                      if start < instances * L
                      and (key, _q(start % L, grid)) in consensus)
        coverage = covered / in_range
        precision = covered / max(len(consensus) * instances, 1)
        if coverage >= sc["loop_coverage"] and precision >= sc["loop_precision"]:
            loop = [[key, folded, min(dur, L - folded), vel, 0]
                    for (key, folded), (dur, vel) in
                    sorted(consensus.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
            return L, loop
    return None, None


def chunk_notes(notes, total_measures, measures_per_pat):
    """Split absolute notes into patterns; sustains carry across borders."""
    span = measures_per_pat * 4
    chunks = defaultdict(list)
    for key, start, dur, vel in notes:
        remaining = dur
        pos = start
        while remaining > 1e-9:
            ci = int(pos // span)
            local = round(pos - ci * span, 4)
            seg = min(remaining, span - local)
            chunks[ci].append([key, local, round(seg, 4), vel, 0])
            pos += seg
            remaining -= seg
    n_chunks = int(math.ceil(total_measures / float(measures_per_pat)))
    return n_chunks, chunks


# ---------------------------------------------------------------------------
# song assembly
# ---------------------------------------------------------------------------

class SongBuilder:
    def __init__(self, bpm, offset, duration, cfg):
        self.cfg = cfg
        self.bpm = bpm
        self.offset = offset
        self.spb = 60.0 / bpm
        self.total_beats = max(4.0, (duration - offset) / self.spb)
        self.total_measures = int(math.ceil(self.total_beats / 4.0))
        self.simplify = cfg["simplify"]["enabled"]
        self.doc = new_room_doc()
        self.doc["bpm"] = round(bpm, 2)
        self.machines = []
        self.song = []
        self._next_block = 1
        self.modes = []                # per-machine simplification mode

    def beats(self, t):
        return (t - self.offset) / self.spb

    def add_layer(self, machine, notes, mode):
        """notes: [key, start_beats, dur_beats, vel] absolute."""
        notes = [[int(k), float(s), float(d), float(v)]
                 for k, s, d, v in notes if 0 <= s < self.total_beats]
        if not notes:
            return
        if self.simplify:
            notes = simplify_notes(notes, mode, self.cfg)
        else:
            notes = sorted(([k, round(s, 4), round(d, 4), round(v, 3)]
                            for k, s, d, v in notes), key=lambda n: (n[1], n[0]))
        slot = len(self.machines)
        self.machines.append(machine)
        self.modes.append(mode)
        loop_beats, loop = (find_loop(notes, self.total_beats, self.cfg)
                            if self.simplify else (None, None))
        if loop_beats is not None:
            machine["patterns"]["A1"] = {"length": int(loop_beats // 4),
                                         "notes": loop}
            self._block(slot, 0, 0, self.total_measures)
        else:
            mpp = (self.cfg["simplify"]["chunk_measures"] if self.simplify
                   else self.cfg["simplify"]["raw_chunk_measures"])
            n_chunks, chunks = chunk_notes(notes, self.total_measures, mpp)
            for ci in range(n_chunks):
                machine["patterns"]["A%d" % (ci + 1)] = {
                    "length": mpp,
                    "notes": sorted(chunks.get(ci, []),
                                    key=lambda n: (n[1], n[0]))}
                start = ci * mpp
                length = min(mpp, self.total_measures - start)
                if length > 0:
                    self._block(slot, ci, start, length)

    def _block(self, slot, pattern, start, length):
        self.song.append({"id": self._next_block, "machine": slot,
                          "bank": 0, "pattern": pattern,
                          "start": start, "length": length})
        self._next_block += 1

    def finish(self, name):
        self.doc["name"] = name
        machines = list(self.machines)
        while len(machines) < 14:
            machines.append(None)
        self.doc["machines"] = machines[:14]
        self.doc["song"] = self.song
        return self.doc


def build_song(x, cfg, log):
    duration = len(x) / SR
    if duration > aimatch.MAX_CLIP_SECONDS:
        log("clip is %.1fs; analyzing the first %.0fs"
            % (duration, aimatch.MAX_CLIP_SECONDS))
        x = x[:int(aimatch.MAX_CLIP_SECONDS * SR)]
        duration = len(x) / SR

    bpm, offset = detect_tempo(x, cfg)
    log("tempo: %.2f BPM (grid offset %.3fs)" % (bpm, offset))

    builder = SongBuilder(bpm, offset, duration, cfg)
    layers = cfg["layers"]
    vel_floor = cfg["grid"]["vel_floor"]

    if layers["drums"]["enabled"]:
        lc = layers["drums"]
        events = aimatch.transcribe_drums(x, SR)
        fixed = []
        for ch, t, a in events:
            # snare hits away from beats 2/4 are usually hats in a dense mix
            if ch == 1 and lc["snare_offbeat_to_hat"]:
                pos = builder.beats(t) % 4.0
                if min(abs(pos - 1.0), abs(pos - 3.0)) > lc["offbeat_tolerance"]:
                    ch = 2
            fixed.append((ch, t, a))
        amps = [a for _, _, a in fixed]
        top = max(amps) if amps else 1.0
        notes = [[ch, builder.beats(t), cfg["grid"]["step"],
                  vel_floor + (1 - vel_floor) * a / top]
                 for ch, t, a in fixed]
        builder.add_layer(drums_machine(lc), notes, "drum")
        log("drums: %d hits" % len(notes))

    def pitched_notes(events, lc):
        lo, hi = lc["note_range"]
        evs = [(s, e, m, a) for s, e, m, a in events if lo <= m <= hi]
        amps = [a for _, _, _, a in evs]
        top = max(amps) if amps else 1.0
        return [[m, builder.beats(s),
                 max(0.1, (e - s) / builder.spb * lc["dur_scale"]),
                 vel_floor + (1 - vel_floor) * a / top]
                for s, e, m, a in evs]

    def transcribe_band(band):
        if band:
            return aimatch.transcribe(bandpass(x, band[0], band[1]), SR)
        return aimatch.transcribe(x, SR)

    for name, mode in (("bass", "bass"), ("chords", "chord"),
                       ("highs", "chord")):
        lc = layers[name]
        if not lc["enabled"]:
            continue
        notes = pitched_notes(transcribe_band(lc["band"]), lc)
        builder.add_layer(synth_machine(name.upper(), lc), notes, mode)
        log("%s: %d notes" % (name, len(notes)))

    dc = layers["drones"]
    if dc["enabled"]:
        stack = detect_drone_stack(x, dc)
        if stack:
            log("drone stack: %s" % " ".join(str(m) for m, _ in stack))
            gs = dc["group_size"]
            groups = [stack[i:i + gs] for i in range(0, len(stack), gs)]
            for gi, group in enumerate(groups[:dc["max_machines"]]):
                notes = []
                beat = 0.0
                while beat < builder.total_beats:
                    for midi, vel in group:
                        notes.append([midi, beat, dc["note_beats"], vel])
                    beat += dc["note_beats"]
                builder.add_layer(drone_machine("DRONE%d" % (gi + 1), dc),
                                  notes, "drone")

    return builder


# ---------------------------------------------------------------------------
# scoring + auto-balance
# ---------------------------------------------------------------------------

def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def mel_filterbank(sc):
    mels = np.linspace(_hz_to_mel(sc["fmin"]), _hz_to_mel(sc["fmax"]),
                       sc["n_mels"] + 2)
    freqs = _mel_to_hz(mels)
    bins = np.fft.rfftfreq(sc["nperseg"], 1.0 / SR)
    fb = np.zeros((sc["n_mels"], len(bins)))
    for i in range(sc["n_mels"]):
        lo, ctr, hi = freqs[i], freqs[i + 1], freqs[i + 2]
        up = (bins - lo) / max(ctr - lo, 1e-9)
        down = (hi - bins) / max(hi - ctr, 1e-9)
        fb[i] = np.maximum(0.0, np.minimum(up, down))
    fb *= (2.0 / (freqs[2:] - freqs[:-2]))[:, None]
    return fb, freqs[1:-1]


def logmel(x, sc, fb):
    rms = np.sqrt(np.mean(x ** 2))
    x = x / max(rms, 1e-9)
    f, t, S = scipy.signal.spectrogram(
        x, SR, nperseg=sc["nperseg"],
        noverlap=sc["nperseg"] - sc["hop"], mode="psd")
    return np.maximum(10.0 * np.log10(fb @ S + 1e-12) + 60.0, 0.0)


def similarity(a, b, cfg, fb=None):
    """Mean per-frame cosine similarity between log-mel spectrogram frames."""
    sc = cfg["score"]
    if fb is None:
        fb, _ = mel_filterbank(sc)
    n = min(len(a), len(b))
    A, B = logmel(a[:n], sc, fb), logmel(b[:n], sc, fb)
    nf = min(A.shape[1], B.shape[1])
    A, B = A[:, :nf], B[:, :nf]
    na = np.linalg.norm(A, axis=0)
    nb = np.linalg.norm(B, axis=0)
    floor = 1e-3 * max(na.max(), nb.max())
    sims = np.where((na < floor) & (nb < floor), 1.0,
                    (A * B).sum(axis=0) / np.maximum(na * nb, 1e-12))
    return float(np.mean(sims)), A, B


def render_doc(doc):
    """Render a room doc offline without touching data/sessions."""
    room = Room.__new__(Room)
    room.id = "wav2song-tmp"
    room.doc = new_room_doc()
    room.lock = threading.RLock()
    room.rev = 0
    room.dirty = False
    room._last_save = 0.0
    room.listeners = set()
    room.engine = None
    room.runtime_only = True
    room.load_doc(doc)
    return render_song(room)


def machine_register(m, mode, tc):
    """Approximate frequency range a machine occupies, from its notes."""
    if mode == "drum":
        return 30.0, 12000.0
    keys = [n[0] for p in m["patterns"].values() for n in p["notes"]]
    if not keys:
        return 30.0, 12000.0
    lo = 440.0 * 2 ** ((min(keys) - 69) / 12.0) * tc["register_low_ratio"]
    hi = 440.0 * 2 ** ((max(keys) - 69) / 12.0) * tc["register_high_ratio"]
    return lo, hi


def _gain_snapshot(builder):
    snap = []
    for m in builder.machines:
        snap.append((m["params"].get("volume", 1.0),
                     m["channels"][0]["params"]["volume"]
                     if m["type"] == "beatbox" else None))
    return snap


def _restore_gains(builder, snap):
    for m, (vol, kick) in zip(builder.machines, snap):
        m["params"]["volume"] = vol
        if kick is not None:
            m["channels"][0]["params"]["volume"] = kick


def auto_balance(builder, orig, cfg, log):
    """Iteratively match the render's per-band energy to the original.

    Keeps the best-scoring gain settings across iterations.
    """
    tc = cfg["tune"]
    rounds = tc["rounds"]
    fb, centers = mel_filterbank(cfg["score"])
    doc = builder.finish(builder.doc.get("name") or "wav2song")
    best_score, best_snap = -1.0, None
    for it in range(rounds + 1):                  # final pass scores only
        rendered = render_doc(doc)
        mono = np.asarray(rendered).mean(axis=0)
        score, A, B = similarity(orig, mono, cfg, fb)
        if score > best_score:
            best_score, best_snap = score, _gain_snapshot(builder)
        if it == rounds:
            break
        diff = B.mean(axis=1) - A.mean(axis=1)     # + = render too loud
        log("tune %d/%d: similarity %.4f" % (it + 1, rounds, score))
        clamp = tc["max_gain_db"]
        for slot, m in enumerate(builder.machines):
            mode = builder.modes[slot]
            lo, hi = machine_register(m, mode, tc)
            sel = (centers >= lo) & (centers <= hi)
            if not sel.any():
                continue
            band_diff = float(np.mean(diff[sel]))
            gain = 10.0 ** (np.clip(-band_diff, -clamp, clamp) / 20.0)
            vol = m["params"].get("volume", 1.0) * gain
            m["params"]["volume"] = float(
                np.clip(vol, tc["volume_min"], tc["volume_max"]))
            if mode == "drum":
                # kick carries the sub band; adjust it from the lowest bands
                sub = float(np.mean(diff[centers < tc["kick_band_hz"]]))
                kick = m["channels"][0]["params"]
                kgain = 10.0 ** (np.clip(-sub, -clamp, clamp) / 20.0)
                kick["volume"] = float(np.clip(
                    kick["volume"] * kgain, tc["volume_min"], tc["volume_max"]))
    if best_snap is not None:
        _restore_gains(builder, best_snap)
        log("best tune: similarity %.4f" % best_score)
    return doc


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="wav2song",
        description="Generate a refrag song (session JSON) from a WAV loop. "
                    "See doc/wav2song.md for the full documentation.")
    ap.add_argument("input", nargs="?", help="input .wav file")
    ap.add_argument("-o", "--output", default=None,
                    help="session name or output .json path "
                         "(default: input file stem, written to data/sessions/)")
    ap.add_argument("--cfg", default=None, metavar="YAML",
                    help="extended configuration file (see doc/wav2song.md)")
    ap.add_argument("--dump-cfg", action="store_true",
                    help="print the effective configuration as YAML and exit")
    ap.add_argument("--bpm", type=float, default=None,
                    help="override tempo detection")
    ap.add_argument("--tune", type=int, default=None, metavar="N",
                    help="auto-balance iterations (default 2, 0 disables)")
    ap.add_argument("--no-simplify", action="store_true",
                    help="keep raw transcription timing (no grid/loops)")
    ap.add_argument("--no-drums", action="store_true", help="skip drum layer")
    ap.add_argument("--no-bass", action="store_true", help="skip bass layer")
    ap.add_argument("--no-chords", action="store_true",
                    help="skip chord + high layers")
    ap.add_argument("--no-drones", action="store_true",
                    help="skip sustained drone detection")
    ap.add_argument("--max-chord", type=int, default=None, metavar="N",
                    help="max simultaneous notes per chord (default 5)")
    ap.add_argument("--render", default=None, metavar="WAV",
                    help="also write the rendered song audio")
    ap.add_argument("--report", action="store_true",
                    help="print the final similarity score")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress progress output")
    return ap.parse_args(argv)


def effective_cfg(args):
    """defaults < --cfg file < explicit CLI flags."""
    cfg = load_cfg(args.cfg) if args.cfg else copy.deepcopy(DEFAULTS)
    if args.bpm is not None:
        cfg["tempo"]["bpm"] = args.bpm
    if args.tune is not None:
        cfg["tune"]["rounds"] = args.tune
    if args.no_simplify:
        cfg["simplify"]["enabled"] = False
    if args.max_chord is not None:
        cfg["simplify"]["max_chord"] = args.max_chord
    if args.no_drums:
        cfg["layers"]["drums"]["enabled"] = False
    if args.no_bass:
        cfg["layers"]["bass"]["enabled"] = False
    if args.no_chords:
        cfg["layers"]["chords"]["enabled"] = False
        cfg["layers"]["highs"]["enabled"] = False
    if args.no_drones:
        cfg["layers"]["drones"]["enabled"] = False
    return cfg


def output_path(args):
    out = args.output
    if out and (out.endswith(".json") or os.sep in out or "/" in out):
        return out, os.path.splitext(os.path.basename(out))[0]
    name = out or os.path.splitext(os.path.basename(args.input))[0]
    return os.path.join(SESSION_DIR, name + ".json"), name


def main(argv=None):
    args = parse_args(argv)
    cfg = effective_cfg(args)
    if args.dump_cfg:
        print(yaml.safe_dump(cfg, sort_keys=False))
        return None
    if not args.input:
        raise SystemExit("wav2song: an input .wav file is required")
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a))

    x = load_wav(args.input)
    builder = build_song(x, cfg, log)

    path, name = output_path(args)
    builder.doc["name"] = name
    if cfg["tune"]["rounds"] > 0:
        doc = auto_balance(builder, x, cfg, log)
    else:
        doc = builder.finish(name)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    log("wrote %s (%d machines, %d measures)"
        % (path, len([m for m in doc["machines"] if m]),
           builder.total_measures))

    if args.render or args.report:
        rendered = render_doc(doc)
        if args.render:
            save_wav(args.render, rendered)
            log("rendered %s" % args.render)
        if args.report:
            score, _, _ = similarity(x, np.asarray(rendered).mean(axis=0), cfg)
            print("similarity: %.4f" % score)
    return path


if __name__ == "__main__":
    main()
