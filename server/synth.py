"""Native synthesis bindings plus sample-driven runtime wrappers."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field

import numpy as np

import refrag_engine as _native

from . import dsp, samples


_ALLOWED_BINOPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: None,
    ast.Mod: None,
    ast.LShift: np.left_shift,
    ast.RShift: np.right_shift,
    ast.BitAnd: np.bitwise_and,
    ast.BitOr: np.bitwise_or,
    ast.BitXor: np.bitwise_xor,
}

_PCM_FILTERS = {
    0: None,
    1: ("lp", False),
    2: ("hp", False),
    3: ("bp", False),
    4: ("lp", True),
    5: ("hp", True),
    6: ("bp", True),
}
_VOCODER_BANDS = (180.0, 300.0, 480.0, 760.0, 1200.0, 1900.0, 3000.0, 4800.0)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _sample_rate_ratio(sample_rate):
    return float(samples.SR) / float(sample_rate or samples.SR)


def _sample_buffer(name):
    return np.asarray(samples.get(str(name or "")), dtype=np.float32)


def _fetch_linear(buf, pos):
    if len(buf) == 0:
        return 0.0
    if len(buf) == 1:
        return float(buf[0])
    pos = float(np.clip(pos, 0.0, len(buf) - 1.0001))
    i0 = int(pos)
    frac = pos - i0
    i1 = min(i0 + 1, len(buf) - 1)
    return float(buf[i0] * (1.0 - frac) + buf[i1] * frac)


def _mix_centered(out, idx, sample, gain, pan):
    out[0, idx] += sample * gain * (1.0 - pan) * 0.5
    out[1, idx] += sample * gain * (1.0 + pan) * 0.5


def _env_frames(knob, sample_rate, max_s=4.0, min_s=0.001):
    return max(1.0, dsp.env_time(float(knob), max_s=max_s, min_s=min_s) * sample_rate)


def _adsr_block(t0, frames, start_offset, released_at, attack, decay, sustain, release):
    t = (t0 + np.arange(frames, dtype=np.float64)) - float(start_offset)
    t_release = None if released_at < 0 else (float(released_at) - float(start_offset))
    return dsp.adsr(t, attack, decay, sustain, release, t_release)


def _lfo_block(rate, phase, frames, sample_rate, wave=0):
    if frames <= 0:
        return np.zeros(0, dtype=np.float32), phase
    step = float(rate) / float(sample_rate)
    ph = phase + np.arange(frames, dtype=np.float64) * step
    vals = dsp.lfo_wave(int(wave), ph).astype(np.float32)
    return vals, phase + frames * step


def _region_bounds(buf_len, start_norm, end_norm):
    if buf_len <= 1:
        return 0, max(1, buf_len)
    start = int(_clamp(float(start_norm), 0.0, 1.0) * (buf_len - 1))
    end = int(_clamp(float(end_norm), 0.0, 1.0) * (buf_len - 1))
    if end <= start + 1:
        start = 0
        end = buf_len - 1
    return start, max(start + 1, min(buf_len - 1, end))


def compile_expr(text):
    """Compile a bytebeat expression into f(t_uint32_array) safely."""
    text = (text or "0").strip() or "0"
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None

    def ev(node, t):
        if isinstance(node, ast.Expression):
            return ev(node.body, t)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return np.int64(int(node.value))
        if isinstance(node, ast.Name) and node.id in ("t", "T"):
            return t
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.Invert)):
            val = ev(node.operand, t)
            return -val if isinstance(node.op, ast.USub) else ~val
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            a = ev(node.left, t)
            b = ev(node.right, t)
            op = type(node.op)
            if op is ast.Div:
                return np.where(b == 0, 0, a // np.where(b == 0, 1, b))
            if op is ast.Mod:
                return np.where(b == 0, 0, np.mod(a, np.where(b == 0, 1, b)))
            return _ALLOWED_BINOPS[op](a, b)
        return None

    if ev(tree, np.arange(1, dtype=np.int64)) is None:
        return None

    def fn(t):
        arr = np.asarray(t, dtype=np.int64)
        out = ev(tree, arr)
        if out is None:
            return np.zeros_like(arr)
        return np.asarray(out, dtype=np.int64)

    return fn


@dataclass
class VoiceState:
    note: int
    vel: float
    flags: int = 0
    t: int = 0
    released_at: int = -1
    dead: bool = False
    start_offset: int = 0
    serial: int = 0


@dataclass
class BeatBoxVoice(VoiceState):
    buffer: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=np.float32))
    rate: float = 1.0
    position: float = 0.0
    pan: float = 0.0
    gain: float = 1.0
    punch: float = 0.0
    play_end: float = 1.0
    stop_at: int = -1
    mute_group: int = 0


@dataclass
class PCMVoice(VoiceState):
    buffer: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=np.float32))
    base_rate: float = 1.0
    position: float = 0.0
    pan: float = 0.0
    gain: float = 1.0
    direction: int = 1
    region_start: int = 0
    loop_start: int = 0
    loop_end: int = 1
    release_end: int = 1
    loop_kind: str = ""
    intro_loop: bool = False


@dataclass
class VocoderVoice(VoiceState):
    phase: float = 0.0
    detune_phase_a: float = 0.0
    detune_phase_b: float = 0.0
    mod_slot: int = 0


@dataclass
class SampleStream:
    name: str
    buffer: np.ndarray
    position: float = 0.0
    rate: float = 1.0
    direction: int = 1
    pingpong: bool = False


class NativeEngineAdapter:
    def __init__(self, m, sample_rate=None):
        self.sample_rate = int(sample_rate or samples.SR)
        self._engine = _native.create_machine(m)

    def update(self, m, sample_rate=None):
        if sample_rate is not None:
            self.sample_rate = int(sample_rate)
        self._engine.update(m)

    def note_on(self, note, vel, offset=0, flags=0):
        self._engine.note_on(note, vel, offset, flags)

    def note_off(self, note, offset=0):
        self._engine.note_off(note, offset)

    def all_off(self):
        self._engine.all_off()

    def kill_all(self):
        self._engine.kill_all()

    def active(self):
        return self._engine.active()

    def render(self, n, ctx=None):
        return self._engine.render(n, ctx)

    @property
    def voices(self):
        return self._engine.voices

    @property
    def band_vu(self):
        return self._engine.band_vu


class _BasePythonEngine:
    def __init__(self, m, sample_rate=None):
        self.sample_rate = int(sample_rate or samples.SR)
        self.machine = None
        self.serial = 0
        self.voices = []
        self.band_vu = [0.0] * 8
        self.update(m, sample_rate=sample_rate)

    def update(self, m, sample_rate=None):
        self.machine = m
        if sample_rate is not None:
            self.sample_rate = int(sample_rate)

    def active(self):
        return any(not v.dead for v in self.voices)

    def note_off(self, note, offset=0):
        release_at = None
        for v in self.voices:
            if not v.dead and v.note == int(note) and v.released_at < 0:
                release_at = v.t + max(0, int(offset))
                v.released_at = release_at
        return release_at

    def all_off(self):
        for v in self.voices:
            if not v.dead and v.released_at < 0:
                v.released_at = v.t

    def kill_all(self):
        self.voices = []

    def _next_serial(self):
        self.serial += 1
        return self.serial

    def _compact(self):
        self.voices = [v for v in self.voices if not v.dead]

    def _trim_poly(self, poly):
        live = [v for v in self.voices if not v.dead]
        while len(live) >= poly:
            victim = min(live, key=lambda voice: voice.serial)
            victim.dead = True
            live.remove(victim)
        self._compact()


class BeatBoxEngine(_BasePythonEngine):
    def note_on(self, note, vel, offset=0, flags=0):
        channels = self.machine.get("channels") or []
        idx = int(note)
        if not 0 <= idx < len(channels):
            return
        ch = channels[idx]
        buf = _sample_buffer(ch.get("sample"))
        if len(buf) < 2:
            return
        params = ch.get("params") or {}
        mute_group = int(ch.get("mute_group", 0))
        cut_at = max(0, int(offset))
        if mute_group > 0:
            for voice in self.voices:
                if not voice.dead and voice.mute_group == mute_group:
                    voice.stop_at = voice.t + cut_at
        self._trim_poly(max(1, int(self.machine.get("poly", 8))))
        decay = _clamp(float(params.get("decay", 1.0)), 0.0, 1.0)
        tune = float(params.get("tune", 0.0))
        play_end = max(32, int((len(buf) - 1) * (0.12 + 0.88 * decay ** 0.8)))
        voice = BeatBoxVoice(
            note=idx,
            vel=float(vel),
            flags=int(flags),
            start_offset=max(0, int(offset)),
            serial=self._next_serial(),
            buffer=buf,
            rate=_sample_rate_ratio(self.sample_rate) * (2.0 ** (tune / 12.0)),
            pan=float(params.get("pan", 0.0)),
            gain=float(params.get("volume", 1.0)) * float(self.machine["params"].get("volume", 1.0)),
            punch=float(params.get("punch", 0.0)),
            play_end=float(min(len(buf) - 1, play_end)),
            mute_group=mute_group,
        )
        self.voices.append(voice)

    def render(self, n, ctx=None):
        out = np.zeros((2, n), dtype=np.float32)
        for voice in self.voices:
            if voice.dead:
                continue
            pos = voice.position
            for i in range(n):
                t = voice.t + i
                if t < voice.start_offset:
                    continue
                if pos >= voice.play_end or pos >= len(voice.buffer) - 1:
                    voice.dead = True
                    break
                sample = _fetch_linear(voice.buffer, pos)
                punch_env = math.exp(-(t - voice.start_offset) / max(1.0, self.sample_rate * 0.012))
                rate = voice.rate * (1.0 + voice.punch * 0.35 * punch_env)
                gain = voice.gain * voice.vel * (1.0 + voice.punch * 0.2 * punch_env)
                tail = 1.0
                remaining = voice.play_end - pos
                if remaining < 64:
                    tail *= max(0.0, remaining / 64.0)
                if voice.stop_at >= 0 and t >= voice.stop_at:
                    tail *= max(0.0, 1.0 - (t - voice.stop_at) / 64.0)
                    if tail <= 0.0:
                        voice.dead = True
                        break
                _mix_centered(out, i, sample, gain * tail, voice.pan)
                pos += rate
            voice.position = pos
            voice.t += n
        self._compact()
        return out


class PCMSynthEngine(_BasePythonEngine):
    def __init__(self, m, sample_rate=None):
        self.filter_l = dsp.TVFilter()
        self.filter_r = dsp.TVFilter()
        self.lfo_phase = 0.0
        super().__init__(m, sample_rate=sample_rate)

    def _matching_zones(self, note):
        zones = []
        for zone in self.machine.get("samples") or []:
            low = int(zone.get("low", 0))
            high = int(zone.get("high", 127))
            if low <= note <= high:
                zones.append(zone)
        return zones

    def note_on(self, note, vel, offset=0, flags=0):
        note = int(note)
        zones = self._matching_zones(note)
        if not zones:
            return
        poly = max(1, int(self.machine.get("poly", 8)))
        for zone in zones:
            self._trim_poly(poly)
            buf = _sample_buffer(zone.get("sample"))
            if len(buf) < 2:
                continue
            start, end = _region_bounds(len(buf), zone.get("start", 0.0), zone.get("end", 1.0))
            mode = int(zone.get("mode", 0))
            root = float(zone.get("root", 60))
            zone_tune = float(zone.get("tune", 0.0))
            octave = int(self.machine["params"].get("octave", 0))
            semis = int(self.machine["params"].get("semis", 0))
            cents = float(self.machine["params"].get("cents", 0.0))
            delta = (note - root) + octave * 12 + semis + (cents + zone_tune) / 100.0
            loop_kind = ""
            intro_loop = False
            release_end = end
            position = start
            if mode == 2:
                loop_kind = "fwd"
            elif mode == 3:
                loop_kind = "pingpong"
            elif mode == 4:
                loop_kind = "fwd"
                intro_loop = True
                release_end = len(buf) - 1
                position = 0
            elif mode == 5:
                loop_kind = "pingpong"
                intro_loop = True
                release_end = len(buf) - 1
                position = 0
            voice = PCMVoice(
                note=note,
                vel=float(vel),
                flags=int(flags),
                start_offset=max(0, int(offset)),
                serial=self._next_serial(),
                buffer=buf,
                base_rate=_sample_rate_ratio(self.sample_rate) * (2.0 ** (delta / 12.0)),
                position=float(position),
                pan=float(zone.get("pan", 0.0)),
                gain=float(zone.get("level", 1.0)) * float(self.machine["params"].get("volume", 1.0)),
                region_start=start,
                loop_start=start,
                loop_end=end,
                release_end=max(end, release_end),
                loop_kind=loop_kind,
                intro_loop=intro_loop,
            )
            self.voices.append(voice)

    def _advance_voice(self, voice, pos, direction, inc, released):
        inc = max(1e-6, float(inc))
        if voice.loop_kind and not released:
            lo = float(voice.loop_start)
            hi = float(max(voice.loop_start + 1, voice.loop_end))
            if voice.intro_loop and pos < lo:
                next_pos = pos + inc
                if next_pos < hi:
                    return next_pos, 1, False
                pos = max(lo, next_pos)
                direction = 1
            if voice.loop_kind == "fwd":
                next_pos = pos + inc
                while next_pos >= hi:
                    next_pos = lo + (next_pos - hi)
                return next_pos, 1, False
            next_pos = pos + inc * direction
            while next_pos >= hi or next_pos < lo:
                if next_pos >= hi:
                    over = next_pos - hi
                    next_pos = hi - over
                    direction = -1
                elif next_pos < lo:
                    over = lo - next_pos
                    next_pos = lo + over
                    direction = 1
            return next_pos, direction, False
        if voice.loop_kind == "pingpong" and direction < 0:
            direction = 1
        next_pos = pos + inc * direction
        return next_pos, direction, next_pos >= voice.release_end

    def render(self, n, ctx=None):
        out = np.zeros((2, n), dtype=np.float32)
        params = self.machine["params"]
        lfo_target = int(params.get("lfo_target", 0))
        lfo_vals, self.lfo_phase = _lfo_block(
            params.get("lfo_rate", 2.0),
            self.lfo_phase,
            n,
            self.sample_rate,
            params.get("lfo_wave", 0),
        )
        lfo_depth = float(params.get("lfo_depth", 0.0))
        pitch_ratio = np.ones(n, dtype=np.float32)
        cutoff_norm = np.full(n, float(params.get("flt_cutoff", 1.0)), dtype=np.float32)
        vol_mod = np.ones(n, dtype=np.float32)
        if lfo_target == 1:
            pitch_ratio = np.power(2.0, (lfo_vals * lfo_depth * 2.0) / 12.0).astype(np.float32)
        elif lfo_target == 2:
            cutoff_norm = np.clip(cutoff_norm + lfo_vals * lfo_depth * 0.45, 0.0, 1.0)
        elif lfo_target == 3:
            vol_mod = np.clip(1.0 + lfo_vals * lfo_depth * 0.5, 0.0, 2.0)
        attack = _env_frames(params.get("vol_attack", 0.0), self.sample_rate)
        decay = _env_frames(params.get("vol_decay", 0.0), self.sample_rate)
        sustain = float(params.get("vol_sustain", 1.0))
        release = _env_frames(params.get("vol_release", 0.05), self.sample_rate)
        for voice in self.voices:
            if voice.dead:
                continue
            env, alive = _adsr_block(
                voice.t, n, voice.start_offset, voice.released_at,
                attack, decay, sustain, release)
            pos = voice.position
            direction = voice.direction
            for i in range(n):
                t = voice.t + i
                if t < voice.start_offset:
                    continue
                if pos >= len(voice.buffer) - 1:
                    voice.dead = True
                    break
                gain = float(env[i]) * voice.gain * voice.vel * float(vol_mod[i])
                if gain <= 1e-5 and voice.released_at >= 0 and t >= voice.released_at:
                    pos, direction, ended = self._advance_voice(
                        voice, pos, direction, voice.base_rate, True)
                    if ended:
                        voice.dead = True
                        break
                    continue
                sample = _fetch_linear(voice.buffer, pos)
                _mix_centered(out, i, sample, gain, voice.pan)
                pos, direction, ended = self._advance_voice(
                    voice, pos, direction,
                    voice.base_rate * float(pitch_ratio[i]),
                    voice.released_at >= 0 and t >= voice.released_at,
                )
                if ended:
                    voice.dead = True
                    break
            voice.position = pos
            voice.direction = direction
            voice.t += n
            if not alive:
                voice.dead = True
        spec = _PCM_FILTERS.get(int(params.get("flt_type", 0)))
        if spec is not None:
            ftype, invert = spec
            hz = dsp.cutoff_hz(cutoff_norm)
            q = dsp.res_to_q(float(params.get("flt_res", 0.0)))
            filtered_l = self.filter_l.process(out[0], ftype, hz, q, sr=self.sample_rate)
            filtered_r = self.filter_r.process(out[1], ftype, hz, q, sr=self.sample_rate)
            if invert:
                out[0] = out[0] - filtered_l
                out[1] = out[1] - filtered_r
            else:
                out[0] = filtered_l
                out[1] = filtered_r
        self._compact()
        return out


class VocoderEngine(_BasePythonEngine):
    def __init__(self, m, sample_rate=None):
        self.mod_filters = [dsp.Biquad() for _ in _VOCODER_BANDS]
        self.car_filters = [dsp.Biquad() for _ in _VOCODER_BANDS]
        self.followers = [0.0 for _ in _VOCODER_BANDS]
        self.streams = {}
        self.current_mod_slot = 0
        super().__init__(m, sample_rate=sample_rate)

    def note_on(self, note, vel, offset=0, flags=0):
        slot = int(self.machine.get("mod_sel", 0))
        if 24 <= int(note) < 30:
            self.current_mod_slot = int(note) - 24
            return
        self.current_mod_slot = slot
        self._trim_poly(max(1, int(self.machine.get("poly", 8))))
        self.voices.append(VocoderVoice(
            note=int(note),
            vel=float(vel),
            flags=int(flags),
            start_offset=max(0, int(offset)),
            serial=self._next_serial(),
            mod_slot=slot,
        ))

    def _modulator_stream(self, slot):
        mods = self.machine.get("modulators") or []
        if not 0 <= slot < len(mods):
            return None
        mod = mods[slot]
        if mod.get("machine", -1) >= 0:
            return ("machine", int(mod["machine"]))
        name = str(mod.get("source") or "")
        if not name:
            return None
        stream = self.streams.get(slot)
        if stream is None or stream.name != name:
            buf = _sample_buffer(name)
            if len(buf) < 2:
                return None
            stream = SampleStream(
                name=name,
                buffer=buf,
                rate=_sample_rate_ratio(self.sample_rate),
            )
            self.streams[slot] = stream
        return ("sample", stream)

    def _render_stream(self, stream, frames):
        out = np.zeros(frames, dtype=np.float32)
        pos = stream.position
        direction = stream.direction
        end = max(1, len(stream.buffer) - 1)
        for i in range(frames):
            out[i] = _fetch_linear(stream.buffer, pos)
            if stream.pingpong:
                next_pos = pos + stream.rate * direction
                while next_pos >= end or next_pos < 0:
                    if next_pos >= end:
                        over = next_pos - end
                        next_pos = end - over
                        direction = -1
                    elif next_pos < 0:
                        next_pos = -next_pos
                        direction = 1
            else:
                next_pos = pos + stream.rate
                while next_pos >= end:
                    next_pos -= end
            pos = next_pos
        stream.position = pos
        stream.direction = direction
        return out

    def _modulator_block(self, frames, ctx):
        source = self._modulator_stream(self.current_mod_slot)
        if source is None:
            return np.zeros(frames, dtype=np.float32)
        stype, value = source
        if stype == "sample":
            return self._render_stream(value, frames)
        outputs = (ctx or {}).get("outputs") or {}
        prev = (ctx or {}).get("prev_outputs") or {}
        audio = outputs.get(value)
        if audio is None:
            audio = prev.get(value)
        if audio is None:
            return np.zeros(frames, dtype=np.float32)
        return np.asarray(audio, dtype=np.float32).mean(axis=0)

    def render(self, n, ctx=None):
        params = self.machine["params"]
        carrier = np.zeros(n, dtype=np.float32)
        attack = max(1.0, self.sample_rate * 0.005)
        decay = 1.0
        sustain = 1.0
        release = max(1.0, self.sample_rate * 0.08)
        wave = int(params.get("wave", 0))
        detune = float(params.get("unison", 0.0)) * 0.015
        sub_mix = float(params.get("sub", 0.0))
        noise_mix = float(params.get("noise", 0.0))
        rng = np.random.default_rng(12345)
        for voice in self.voices:
            if voice.dead:
                continue
            env, alive = _adsr_block(
                voice.t, n, voice.start_offset, voice.released_at,
                attack, decay, sustain, release)
            phase = voice.phase
            pha = voice.detune_phase_a
            phb = voice.detune_phase_b
            freq = dsp.note_freq(voice.note)
            for i in range(n):
                t = voice.t + i
                if t < voice.start_offset:
                    continue
                if env[i] <= 1e-5 and voice.released_at >= 0 and t >= voice.released_at:
                    continue
                phase += freq / self.sample_rate
                pha += freq * (1.0 - detune) / self.sample_rate
                phb += freq * (1.0 + detune) / self.sample_rate
                if wave == 0:
                    main = dsp.osc_wave(2, phase)
                    uni = 0.5 * (dsp.osc_wave(2, pha) + dsp.osc_wave(2, phb))
                else:
                    main = dsp.osc_wave(4, phase)
                    uni = 0.5 * (dsp.osc_wave(4, pha) + dsp.osc_wave(4, phb))
                sub = sub_mix * dsp.osc_wave(4, phase * 0.5)
                noise = noise_mix * float(rng.uniform(-1.0, 1.0))
                carrier[i] += (0.55 * main + 0.45 * uni + 0.4 * sub + 0.12 * noise) * float(env[i]) * voice.vel
            voice.phase = phase
            voice.detune_phase_a = pha
            voice.detune_phase_b = phb
            voice.t += n
            if not alive:
                voice.dead = True
        mod = self._modulator_block(n, ctx)
        out_mono = np.zeros(n, dtype=np.float32)
        slew = float(params.get("slew", 0.3))
        coef = _clamp(0.55 + slew * 0.42, 0.0, 0.995)
        dry = float(params.get("dry", 0.0))
        hf_bypass = float(params.get("hf_bypass", 0.0))
        for i, center in enumerate(_VOCODER_BANDS):
            self.mod_filters[i].set("bp", center, 1.2, sr=self.sample_rate)
            self.car_filters[i].set("bp", center, 1.2, sr=self.sample_rate)
            mod_band = self.mod_filters[i].process(mod)
            car_band = self.car_filters[i].process(carrier)
            env, state = dsp.onepole_smooth(np.abs(mod_band), coef, self.followers[i])
            self.followers[i] = state
            band_gain = float(params.get(f"band{i + 1}", 1.0))
            out_mono += car_band * env * band_gain
            self.band_vu[i] = float(np.clip(np.max(env) if len(env) else 0.0, 0.0, 1.0))
        if hf_bypass > 0:
            out_mono += mod * hf_bypass * 0.2
        if dry > 0:
            out_mono += mod * dry * 0.25
        out = np.vstack([out_mono, out_mono]).astype(np.float32)
        out *= float(params.get("volume", 1.0))
        self._compact()
        return out


def create_machine(m, sample_rate=None):
    mtype = m.get("type")
    if mtype == "beatbox":
        return BeatBoxEngine(m, sample_rate=sample_rate)
    if mtype == "pcmsynth":
        return PCMSynthEngine(m, sample_rate=sample_rate)
    if mtype == "vocoder":
        return VocoderEngine(m, sample_rate=sample_rate)
    return NativeEngineAdapter(m, sample_rate=sample_rate)


def render_block(output_buffer, param_matrix):
    return _native.render_block(output_buffer, param_matrix)


def initialize(thread_count=None):
    return _native.initialize(thread_count) if hasattr(_native, "initialize") else None
