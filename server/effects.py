"""The 16 insert effects. Each effect is a stateful stereo processor.

process(x, params, ctx) takes a (2, n) float64 block and returns the same
shape. ctx provides bpm and sidechain inputs for the compressor.
"""

import numpy as np
from scipy import signal as sig

from .dsp import (Biquad, TVFilter, biquad_coeffs, cutoff_hz, distort,
                  onepole_smooth, res_to_q)


class Effect:
    def __init__(self, sample_rate=44100):
        self.sample_rate = int(sample_rate)
        self.setup()

    def setup(self):
        pass

    def process(self, x, p, ctx):
        return x


class FracDelayLine:
    """Stereo circular delay line with modulated tap reads."""

    def __init__(self, max_s=2.0, sample_rate=44100):
        self.sample_rate = int(sample_rate)
        self.n = int(max_s * self.sample_rate)
        self.buf = np.zeros((2, self.n))
        self.w = 0

    def write_read(self, x, delay_samples, feedback=0.0):
        """Per-block write with feedback and (2,n) or (n,) delay arrays."""
        _, n = x.shape
        out = np.empty_like(x)
        positions = self.w + np.arange(n)
        idx = positions % self.n
        delay_ndim = np.ndim(delay_samples)
        for c in range(2):
            delay = delay_samples[c] if delay_ndim == 2 else delay_samples
            read_pos = (positions - delay) % self.n
            floor_pos = np.floor(read_pos)
            i0 = floor_pos.astype(np.int64) % self.n
            i1 = (i0 + 1) % self.n
            frac = read_pos - floor_pos
            delayed = self.buf[c, i0] * (1 - frac) + self.buf[c, i1] * frac
            out[c] = delayed
            self.buf[c, idx] = x[c] + delayed * feedback
        self.w = (self.w + n) % self.n
        return out


def _flanger_lfo(mode, ph):
    """Returns (lfoL, lfoR) in -1..1 (or 0..1 for unipolar modes)."""
    tri = lambda p: 4 * np.abs((p % 1) - 0.5) - 1
    sin = lambda p: np.sin(2 * np.pi * p)
    wave = sin if mode in (0, 1, 2, 6) else tri
    l = wave(ph)
    if mode in (0, 3):          # mono
        r = l
    elif mode in (1, 4):        # stereo (quadrature)
        r = wave(ph + 0.25)
    elif mode in (2, 5):        # inverted
        r = -l
    else:                        # unipolar
        l = (l + 1) / 2
        r = l
        return l, r
    return l, r


class Distortion(Effect):
    def process(self, x, p, ctx):
        y = x * (0.05 + p["pre"])
        y = distort(y, int(p["program"]), p["amount"])
        return y * p["post"]


class BitCrusher(Effect):
    def setup(self):
        self.hold = np.zeros(2)
        self.phase = 0.0

    def process(self, x, p, ctx):
        n = x.shape[1]
        depth = max(1, int(round(p["depth"])))
        levels = 2 ** depth
        rate_hz = 20.0 * (2205.0 ** np.clip(p["rate"], 0, 1))  # 20Hz..44.1k
        step = rate_hz / self.sample_rate
        jit = p["jitter"]
        if jit > 0:
            steps = step * (1 + jit * np.random.default_rng().uniform(-0.9, 0.9, n))
        else:
            steps = np.full(n, step)
        ph = self.phase + np.cumsum(steps)
        self.phase = float(ph[-1] % 1e9)
        keep = np.floor(ph).astype(np.int64)
        # sample & hold: only update output when integer part advances
        change = np.empty(n, dtype=bool)
        change[0] = True
        change[1:] = keep[1:] != keep[:-1]
        idxs = np.where(change)[0]
        y = np.empty_like(x)
        for c in range(2):
            held = np.maximum.accumulate(np.where(change, np.arange(n), -1))
            src = x[c, np.clip(held, 0, n - 1)]
            src[held < 0] = self.hold[c]
            y[c] = np.round(src * levels) / levels
            self.hold[c] = y[c, -1]
        return y * p["wet"] + x * (1 - p["wet"])


class Compressor(Effect):
    def setup(self):
        self.env = 0.0
        self.gr = 0.0   # for VU

    def process(self, x, p, ctx):
        sc_idx = int(p["sidechain"])
        key = x
        if sc_idx > 0 and ctx is not None:
            key = ctx.get("lines", {}).get(sc_idx - 1, x)
        level = np.max(np.abs(key), axis=0)
        att = np.exp(-1.0 / (self.sample_rate * (0.0005 + p["attack"] ** 2 * 0.2)))
        rel = np.exp(-1.0 / (self.sample_rate * (0.01 + p["release"] ** 2 * 1.5)))
        env, self.env = onepole_smooth(level, rel, self.env)
        env_fast, _ = onepole_smooth(level, att, self.env)
        env = np.maximum(env, env_fast)
        th = 0.03 + p["threshold"] * 0.97
        ratio = 1.0 + p["ratio"] * 19.0
        over = np.maximum(env / th, 1.0)
        gain = over ** (1.0 / ratio - 1.0)
        self.gr = float(1.0 - np.min(gain))
        return x * gain


class Flanger(Effect):
    def setup(self):
        self.dl = FracDelayLine(0.06, sample_rate=self.sample_rate)
        self.ph = 0.0

    def process(self, x, p, ctx):
        n = x.shape[1]
        rate = 0.05 + p["rate"] ** 2 * 6.0
        ph = self.ph + np.arange(n) * rate / self.sample_rate
        self.ph = float(ph[-1] % 1.0)
        l, r = _flanger_lfo(int(p["mode"]), ph)
        base = 0.0015 * self.sample_rate
        depth = p["depth"] * 0.004 * self.sample_rate
        dl_ = np.stack([base + depth * (l + 1) / 2, base + depth * (r + 1) / 2])
        wet = self.dl.write_read(x, dl_, p["feedback"])
        return x * (1 - p["wet"]) + wet * p["wet"]


class Chorus(Effect):
    def setup(self):
        self.dl = FracDelayLine(0.12, sample_rate=self.sample_rate)
        self.ph = 0.0

    def process(self, x, p, ctx):
        n = x.shape[1]
        rate = 0.05 + p["rate"] ** 2 * 4.0
        ph = self.ph + np.arange(n) * rate / self.sample_rate
        self.ph = float(ph[-1] % 1.0)
        l, r = _flanger_lfo(int(p["mode"]), ph)
        base = (0.005 + p["delay"] * 0.03) * self.sample_rate
        depth = p["depth"] * 0.008 * self.sample_rate
        dl_ = np.stack([base + depth * (l + 1) / 2, base + depth * (r + 1) / 2])
        wet = self.dl.write_read(x, dl_, 0.0)
        return x * (1 - p["wet"]) + wet * p["wet"]


class Phaser(Effect):
    STAGES = 4

    def setup(self):
        self.zi = [np.zeros((2, 2)) for _ in range(self.STAGES)]
        self.ph = 0.0
        self.fb = np.zeros(2)

    def process(self, x, p, ctx):
        n = x.shape[1]
        rate = 0.05 + p["rate"] ** 2 * 8.0
        ph = self.ph + np.arange(n) * rate / self.sample_rate
        self.ph = float(ph[-1] % 1.0)
        lo = cutoff_hz(p["low"] * 0.7)
        hi = cutoff_hz(p["low"] * 0.7 + (p["high"] - p["low"]) * 0.7 * p["depth"] + 0.2)
        sweep = lo + (hi - lo) * (np.sin(2 * np.pi * ph) + 1) / 2
        y = x.copy()
        y[:, 0] += self.fb * p["feedback"]
        chunk = 256
        out = np.empty_like(y)
        for i in range(0, n, chunk):
            j = min(i + chunk, n)
            f0 = float(sweep[(i + j) // 2])
            b, a = biquad_coeffs("allpass", f0, 0.7)
            seg = y[:, i:j]
            for s in range(self.STAGES):
                res = np.empty_like(seg)
                for c in range(2):
                    res[c], self.zi[s][c] = sig.lfilter(b, a, seg[c], zi=self.zi[s][c])
                seg = res
            out[:, i:j] = seg
        self.fb = out[:, -1].copy()
        return (x + out) * 0.5


class AutoWah(Effect):
    def setup(self):
        self.env = 0.0
        self.flt = [TVFilter(), TVFilter()]

    def process(self, x, p, ctx):
        level = np.max(np.abs(x), axis=0)
        speed = np.exp(
            -1.0 / (self.sample_rate * (0.002 + (1 - p["speed"]) ** 2 * 0.3)))
        env, self.env = onepole_smooth(level, speed, self.env)
        base = cutoff_hz(p["cutoff"])
        f = base + p["depth"] * np.clip(env * 3, 0, 1) * (cutoff_hz(1.0) - base) * 0.4
        q = res_to_q(p["resonance"] * 0.7)
        wet = np.stack([self.flt[c].process(x[c], "bp", f, q) for c in range(2)])
        return x * (1 - p["wet"]) + wet * 2.0 * p["wet"]


class ParametricEQ(Effect):
    def setup(self):
        self.bq = [Biquad(), Biquad()]

    def process(self, x, p, ctx):
        f0 = cutoff_hz(p["freq"])
        gain_db = p["gain"] * 18.0
        q = 0.3 + (1 - p["bandwidth"]) * 6.0
        for bq in self.bq:
            bq.set("peak", f0, q, sr=self.sample_rate, gain_db=gain_db)
        return np.stack([self.bq[c].process(x[c]) for c in range(2)])


class Limiter(Effect):
    def setup(self):
        self.env = 1.0
        self.gr = 0.0

    def process(self, x, p, ctx):
        y = x * (0.05 + p["pre"])
        level = np.maximum(np.max(np.abs(y), axis=0), 1e-9)
        att = np.exp(-1.0 / (self.sample_rate * (0.0002 + p["attack"] ** 2 * 0.05)))
        rel = np.exp(-1.0 / (self.sample_rate * (0.01 + p["release"] ** 2 * 1.0)))
        target = np.minimum(1.0 / level, 1.0)
        env = np.empty_like(target)
        e = self.env
        # coarse block-wise smoothing (16-sample hops keep it cheap)
        hop = 16
        for i in range(0, len(target), hop):
            j = min(i + hop, len(target))
            tgt = float(np.min(target[i:j]))
            coef = att if tgt < e else rel
            e = tgt + (e - tgt) * coef ** (j - i)
            env[i:j] = e
        self.env = float(e)
        self.gr = float(1.0 - np.min(env))
        return y * env * p["post"]


class Vinyl(Effect):
    def setup(self):
        self.bq = [Biquad(), Biquad()]
        self.rng = np.random.default_rng(7)
        self.lp = 0.0

    def process(self, x, p, ctx):
        n = x.shape[1]
        # aged bandpass on the source
        f0 = 1800.0
        q = 0.4 + p["age"] * 1.2
        aged = np.empty_like(x)
        for c in range(2):
            self.bq[c].set("bp", f0, q, sr=self.sample_rate)
            aged[c] = self.bq[c].process(x[c]) * 2.2
        y = x * (1 - p["age"]) + aged * p["age"]
        gen = np.zeros(n)
        if p["dust"] > 0:
            mask = self.rng.random(n) < (p["dust"] ** 2 * 0.002)
            gen += mask * self.rng.uniform(-1, 1, n) * 0.8
        if p["scratch"] > 0:
            mask = self.rng.random(n) < (p["scratch"] ** 2 * 0.0004)
            imp = mask * self.rng.uniform(0.5, 1, n)
            gen += np.convolve(imp, np.hanning(64), mode="same")
        if p["noise"] > 0:
            w = self.rng.uniform(-1, 1, n)
            sm, self.lp = onepole_smooth(w, 0.995, self.lp)
            gen += sm * p["noise"] * 3.0
        return y + np.stack([gen, gen]) * p["wet"] * 0.5


class CombFilter(Effect):
    def setup(self):
        self.buf = None

    def process(self, x, p, ctx):
        f0 = 40.0 * (100.0 ** p["freq"])   # 40..4000 Hz
        L = max(2, int(self.sample_rate / f0))
        wet = np.empty_like(x)
        b = np.zeros(L + 1); b[0] = 1.0
        a = np.zeros(L + 1); a[0] = 1.0; a[L] = -p["reso"]
        if self.buf is None or self.buf.shape != (2, L):
            self.buf = np.zeros((2, L))
        for c in range(2):
            zi = self.buf[c]
            wet[c], self.buf[c] = sig.lfilter(b, a, x[c], zi=zi)
        return x * (1 - p["wet"]) + wet * p["wet"] * (1 - p["reso"] * 0.5)


class Cabinet(Effect):
    def setup(self):
        self.state = {}
        self.bq = [Biquad(), Biquad()]

    def process(self, x, p, ctx):
        # a couple of short reflections sized by cabinet dimensions
        w = 0.0006 + p["width"] * 0.004
        h = 0.0008 + p["height"] * 0.006
        damp = 0.2 + p["damp"] * 0.7
        taps = [(int(w * self.sample_rate), 0.7 * (1 - damp * 0.5)),
                (int(h * self.sample_rate), 0.5 * (1 - damp * 0.5)),
                (int((w + h) * self.sample_rate), 0.35 * (1 - damp))]
        n = x.shape[1]
        wet = x.copy()
        for d, g in taps:
            if d < n:
                wet[:, d:] += g * x[:, :-d]
        tone_f = 800 + p["tone"] * 5000
        for c in range(2):
            self.bq[c].set("lp", tone_f, 0.7, sr=self.sample_rate)
            wet[c] = self.bq[c].process(wet[c])
        return x * (1 - p["wet"]) + wet * 0.5 * p["wet"]


class StaticFlanger(Effect):
    def setup(self):
        self.dl = FracDelayLine(0.05, sample_rate=self.sample_rate)

    def process(self, x, p, ctx):
        d = (0.0002 + np.abs(p["delay"]) * 0.008) * self.sample_rate
        if p["delay"] >= 0:
            dl_ = np.stack([np.full(x.shape[1], d), np.full(x.shape[1], 1.0)])
        else:
            dl_ = np.stack([np.full(x.shape[1], 1.0), np.full(x.shape[1], d)])
        wet = self.dl.write_read(x, dl_, p["feedback"])
        return x * (1 - p["wet"]) + wet * p["wet"]


class Delay(Effect):
    def setup(self):
        self.buf = np.zeros((2, 2 * self.sample_rate))
        self.w = 0

    def process(self, x, p, ctx):
        bpm = ctx.get("bpm", 120.0) if ctx else 120.0
        # sync to 16ths..1 bar
        steps = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
        beats = steps[int(p["time"] * (len(steps) - 1))]
        D = int(np.clip(
            beats * 60.0 / bpm * self.sample_rate, 32, self.buf.shape[1] - 1))
        n = x.shape[1]
        mode = int(p["mode"])
        y = x.copy()
        buf, w = self.buf, self.w
        fb = p["feedback"]
        outwet = np.zeros_like(x)
        idx = (w + np.arange(n)) % buf.shape[1]
        rd = (idx - D) % buf.shape[1]
        tapL = buf[0, rd]
        tapR = buf[1, rd]
        if mode == 0:      # mono
            m = (x[0] + x[1]) * 0.5
            buf[0, idx] = m + tapL * fb
            buf[1, idx] = buf[0, idx]
            outwet[0] = tapL; outwet[1] = tapL
        elif mode in (1, 2):   # ping-pong
            m = (x[0] + x[1]) * 0.5
            first, second = (0, 1) if mode == 1 else (1, 0)
            buf[first, idx] = m + tapR * fb if mode == 1 else m + tapL * fb
            if mode == 1:
                buf[0, idx] = m + tapR * fb
                buf[1, idx] = tapL
                outwet[0] = tapL; outwet[1] = tapR
            else:
                buf[1, idx] = m + tapL * fb
                buf[0, idx] = tapR
                outwet[0] = tapL; outwet[1] = tapR
        else:               # wide stereo
            buf[0, idx] = x[0] + tapL * fb
            buf[1, idx] = x[1] + tapR * fb
            if mode == 3:
                outwet[0] = tapL; outwet[1] = tapR
            else:
                outwet[0] = tapR; outwet[1] = tapL
        self.w = (w + n) % buf.shape[1]
        return x + outwet * p["wet"]


class Reverb(Effect):
    """Freeverb-style Schroeder reverb."""

    COMBS = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
    ALLPASS = [556, 441, 341, 225]
    SPREAD = 23

    def setup(self):
        self.comb_zi = {}
        self.ap_zi = {}
        self.predelay = FracDelayLine(0.25, sample_rate=self.sample_rate)

    def _comb(self, x, L, feedback, damp, key):
        st = self.comb_zi.get(key)
        if st is None or len(st["buf"]) != L:
            st = {"buf": np.zeros(L), "i": 0, "lp": 0.0}
            self.comb_zi[key] = st
        buf, i, lp = st["buf"], st["i"], st["lp"]
        n = len(x)
        out = np.empty(n)
        # process in L-sized hops so we can vectorize within each hop
        pos = 0
        while pos < n:
            m = min(L - i, n - pos, L)
            seg = buf[i:i + m]
            out[pos:pos + m] = seg
            # damped feedback (single-pole applied per hop, cheap approximation)
            lp = lp * damp + np.mean(seg) * (1 - damp) if m else lp
            buf[i:i + m] = x[pos:pos + m] + seg * feedback * (1 - damp) + lp * feedback * damp
            i = (i + m) % L
            pos += m
        st["i"], st["lp"] = i, lp
        return out

    def _allpass(self, x, L, key):
        st = self.ap_zi.get(key)
        if st is None or len(st["buf"]) != L:
            st = {"buf": np.zeros(L), "i": 0}
            self.ap_zi[key] = st
        buf, i = st["buf"], st["i"]
        n = len(x)
        out = np.empty(n)
        g = 0.5
        pos = 0
        while pos < n:
            m = min(L - i, n - pos)
            seg = buf[i:i + m]
            xin = x[pos:pos + m]
            out[pos:pos + m] = seg - g * xin
            buf[i:i + m] = xin + g * seg
            i = (i + m) % L
            pos += m
        st["i"] = i
        return out

    def process(self, x, p, ctx):
        room = 0.7 + p["room"] * 0.28
        damp = p["damp"] * 0.6
        pd = max(1.0, p["delay"] * 0.2 * self.sample_rate)
        src = self.predelay.write_read(x, pd, 0.0)
        mono = (src[0] + src[1]) * 0.5
        wetL = np.zeros_like(mono)
        wetR = np.zeros_like(mono)
        for k, L in enumerate(self.COMBS):
            wetL += self._comb(mono, L, room, damp, ("L", k))
            wetR += self._comb(mono, L + self.SPREAD, room, damp, ("R", k))
        for k, L in enumerate(self.ALLPASS):
            wetL = self._allpass(wetL, L, ("L", k))
            wetR = self._allpass(wetR, L + self.SPREAD, ("R", k))
        wetL *= 0.06
        wetR *= 0.06
        width = p["width"]
        mid = (wetL + wetR) * 0.5
        sideL = wetL * width + mid * (1 - width)
        sideR = wetR * width + mid * (1 - width)
        wet = np.stack([sideL, sideR])
        return x * (1 - p["wet"] * 0.4) + wet * p["wet"]


class MultiFilter(Effect):
    TYPES = ["lp", "hp", "bp", "notch", "peak", "bandiso", "lowshelf", "highshelf"]

    def setup(self):
        self.bq = [Biquad(), Biquad()]
        self.bq2 = [Biquad(), Biquad()]

    def process(self, x, p, ctx):
        ftype = self.TYPES[int(p["type"])]
        f0 = cutoff_hz(p["freq"])
        gain_db = p["gain"] * 18.0
        out = np.empty_like(x)
        if ftype == "bandiso":
            q = 0.4 + (1 - p["reso"]) * 4
            for c in range(2):
                self.bq[c].set("bp", f0, q, sr=self.sample_rate)
                out[c] = self.bq[c].process(x[c]) * (1 + p["reso"] * 2)
            return out * 10 ** (gain_db / 20.0)
        q = res_to_q(p["reso"] * 0.6)
        for c in range(2):
            self.bq[c].set(ftype if ftype in ("lp", "hp", "bp", "notch",
                                              "peak", "lowshelf", "highshelf")
                           else "lp", f0, q, sr=self.sample_rate,
                           gain_db=gain_db)
            out[c] = self.bq[c].process(x[c])
        if ftype in ("lp", "hp", "bp", "notch"):
            out *= 10 ** (gain_db / 20.0)
        return out


EFFECT_CLASSES = {
    "distortion": Distortion, "bitcrusher": BitCrusher, "compressor": Compressor,
    "flanger": Flanger, "chorus": Chorus, "phaser": Phaser, "autowah": AutoWah,
    "parametriceq": ParametricEQ, "limiter": Limiter, "vinyl": Vinyl,
    "combfilter": CombFilter, "cabinet": Cabinet, "staticflanger": StaticFlanger,
    "delay": Delay, "reverb": Reverb, "multifilter": MultiFilter,
}


def create_effect(etype, sample_rate=44100):
    cls = EFFECT_CLASSES.get(etype)
    return cls(sample_rate=sample_rate) if cls else None
