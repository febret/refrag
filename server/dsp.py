"""Shared DSP primitives: oscillators, envelopes, filters, distortion."""

import numpy as np
from scipy import signal as sig

SR = 44100
TWO_PI = 2.0 * np.pi

# ---------------------------------------------------------------------------
# Oscillators (phase in cycles, i.e. wraps at 1.0)
# ---------------------------------------------------------------------------

_rng = np.random.default_rng(1234)


def note_freq(note):
    return 440.0 * 2.0 ** ((np.asarray(note, dtype=np.float64) - 69.0) / 12.0)


def osc_wave(index, phase):
    """Render one of the 9 shared waveforms. phase is in cycles."""
    ph = phase - np.floor(phase)
    if index == 0:      # Sine
        return np.sin(TWO_PI * ph)
    if index == 1:      # Triangle
        return 4.0 * np.abs(ph - 0.5) - 1.0
    if index in (2, 3):  # Saw / Saw HQ
        out = 2.0 * ph - 1.0
        if index == 3:
            out = polyblep_correct_saw(out, ph, phase)
        return out
    if index in (4, 5):  # Square / Square HQ
        return np.where(ph < 0.5, 1.0, -1.0)
    if index == 6:      # Pulse
        return np.where(ph < 0.25, 1.0, -1.0)
    if index == 7:      # Half Sine
        return np.maximum(np.sin(TWO_PI * ph), 0.0) * 2.0 - 1.0
    if index == 8:      # Noise
        return _rng.uniform(-1.0, 1.0, np.shape(ph))
    return np.zeros_like(ph)


def polyblep_correct_saw(out, ph, phase):
    """Cheap polyblep smoothing of saw discontinuities."""
    if np.ndim(phase) == 0 or len(np.atleast_1d(phase)) < 2:
        return out
    dt = np.empty_like(ph)
    dt[1:] = np.abs(np.diff(phase))
    dt[0] = dt[1] if len(dt) > 1 else 0.01
    dt = np.clip(dt, 1e-6, 0.5)
    t = ph / dt
    mask1 = ph < dt
    corr = np.zeros_like(ph)
    corr[mask1] = -(2 * t[mask1] - t[mask1] ** 2 - 1.0)
    t2 = (ph - 1.0) / dt
    mask2 = ph > 1.0 - dt
    corr[mask2] += -(t2[mask2] ** 2 + 2 * t2[mask2] + 1.0)
    return out + corr


def lfo_wave(index, phase, state=None):
    ph = phase - np.floor(phase)
    if index == 0:
        return np.sin(TWO_PI * ph)
    if index == 1:
        return 4.0 * np.abs(ph - 0.5) - 1.0
    if index == 2:
        return 2.0 * ph - 1.0
    if index == 3:
        return np.where(ph < 0.5, 1.0, -1.0)
    # Random: sample & hold per cycle
    cyc = np.floor(phase).astype(np.int64)
    rnd = np.sin(cyc * 12.9898 + 78.233) * 43758.5453
    return 2.0 * (rnd - np.floor(rnd)) - 1.0


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def env_time(knob, max_s=4.0, min_s=0.001):
    """Map a 0..1 knob to seconds with a musical curve."""
    return min_s + (max_s - min_s) * float(knob) ** 2.5


def adsr_level(t, A, D, S):
    """Scalar or array gated envelope level at voice-time t (samples)."""
    t = np.asarray(t, dtype=np.float64)
    A = max(A, 1.0)
    D = max(D, 1.0)
    lvl = np.where(t < A, t / A,
                   np.where(t < A + D, 1.0 - (1.0 - S) * (t - A) / D, S))
    return lvl


def adsr(t, A, D, S, R, t_release=None):
    """Vectorized ADSR. t in samples (array). Returns env plus 'alive' flag."""
    R = max(R, 1.0)
    if t_release is None:
        return adsr_level(t, A, D, S), True
    lr = float(adsr_level(np.float64(t_release), A, D, S))
    env_on = adsr_level(t, A, D, S)
    env_off = lr * np.maximum(0.0, 1.0 - (t - t_release) / R)
    env = np.where(t < t_release, env_on, env_off)
    alive = bool(t[-1] < t_release + R) if len(np.atleast_1d(t)) else False
    return env, alive


# ---------------------------------------------------------------------------
# Biquad filters with time-varying cutoff (chunked lfilter)
# ---------------------------------------------------------------------------

def biquad_coeffs(ftype, f0, q, sr=SR, gain_db=0.0):
    f0 = float(np.clip(f0, 20.0, sr * 0.49))
    q = float(max(q, 0.05))
    w0 = TWO_PI * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)
    if ftype == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif ftype == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif ftype == "bp":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif ftype == "notch":
        b = [1, -2 * cw, 1]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif ftype == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif ftype == "lowshelf":
        sqA = np.sqrt(A)
        b = [A * ((A + 1) - (A - 1) * cw + 2 * sqA * alpha),
             2 * A * ((A - 1) - (A + 1) * cw),
             A * ((A + 1) - (A - 1) * cw - 2 * sqA * alpha)]
        a = [(A + 1) + (A - 1) * cw + 2 * sqA * alpha,
             -2 * ((A - 1) + (A + 1) * cw),
             (A + 1) + (A - 1) * cw - 2 * sqA * alpha]
    elif ftype == "highshelf":
        sqA = np.sqrt(A)
        b = [A * ((A + 1) + (A - 1) * cw + 2 * sqA * alpha),
             -2 * A * ((A - 1) + (A + 1) * cw),
             A * ((A + 1) + (A - 1) * cw - 2 * sqA * alpha)]
        a = [(A + 1) - (A - 1) * cw + 2 * sqA * alpha,
             2 * ((A - 1) - (A + 1) * cw),
             (A + 1) - (A - 1) * cw - 2 * sqA * alpha]
    elif ftype == "allpass":
        b = [1 - alpha, -2 * cw, 1 + alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        return np.array([1.0, 0, 0]), np.array([1.0, 0, 0])
    b = np.asarray(b, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    return b / a[0], a / a[0]


class Biquad:
    """Stateful biquad (mono)."""

    def __init__(self):
        self.zi = np.zeros(2)
        self.b = np.array([1.0, 0, 0])
        self.a = np.array([1.0, 0, 0])
        self._params = None

    def set(self, ftype, f0, q, sr=SR, gain_db=0.0):
        params = (ftype, float(f0), float(q), float(sr), float(gain_db))
        if params == self._params:
            return
        self.b, self.a = biquad_coeffs(ftype, f0, q, sr, gain_db)
        self._params = params

    def process(self, x):
        y, self.zi = sig.lfilter(self.b, self.a, x, zi=self.zi)
        return y


class TVFilter:
    """Time-varying resonant filter processed in chunks."""

    def __init__(self, chunk=128):
        self.zi = np.zeros(2)
        self.chunk = chunk

    def process(self, x, ftype, cutoff_hz, q, sr=SR):
        """cutoff_hz can be scalar or array (per-sample)."""
        n = len(x)
        if np.isscalar(cutoff_hz) or np.ndim(cutoff_hz) == 0:
            b, a = biquad_coeffs(ftype, float(cutoff_hz), q, sr)
            y, self.zi = sig.lfilter(b, a, x, zi=self.zi)
            return y
        if n and np.all(cutoff_hz == cutoff_hz[0]):
            b, a = biquad_coeffs(ftype, float(cutoff_hz[0]), q, sr)
            y, self.zi = sig.lfilter(b, a, x, zi=self.zi)
            return y
        out = np.empty_like(x)
        for i in range(0, n, self.chunk):
            j = min(i + self.chunk, n)
            b, a = biquad_coeffs(ftype, float(cutoff_hz[(i + j) // 2]), q, sr)
            out[i:j], self.zi = sig.lfilter(b, a, x[i:j], zi=self.zi)
        return out


def onepole_smooth(x, coef, state):
    """One-pole lowpass smoother (for envelope followers). Returns (y, state)."""
    b = np.array([1.0 - coef])
    a = np.array([1.0, -coef])
    y, zf = sig.lfilter(b, a, x, zi=np.array([state * coef]))
    return y, float(y[-1]) if len(y) else state


def cutoff_hz(norm):
    """Map 0..1 to 20Hz..18kHz exponentially."""
    return 20.0 * (900.0 ** np.clip(norm, 0.0, 1.0))


def res_to_q(res):
    return 0.55 + float(np.clip(res, 0, 1)) ** 1.6 * 14.0


# ---------------------------------------------------------------------------
# Distortion programs (shared by BassLine + Distortion effect)
# ---------------------------------------------------------------------------

def distort(x, program, amount):
    """program: 0 overdrive, 1 saturate, 2 fuzz, 3 foldback."""
    amt = float(np.clip(amount, 0.0, 1.0))
    drive = 1.0 + amt * 15.0
    if program == 0:      # overdrive: tanh tube-ish
        return np.tanh(x * drive) / np.tanh(drive) if drive > 0 else x
    if program == 1:      # saturate: soft-knee
        return x / (1.0 + amt * np.abs(x) * 4.0)
    if program == 2:      # fuzz: hard clip
        th = max(1.0 - amt * 0.95, 0.05)
        return np.clip(x, -th, th) / th
    if program == 3:      # foldback
        th = max(1.0 - amt * 0.9, 0.1)
        y = np.abs(np.mod(x - th, 4.0 * th))
        return np.abs(y - 2.0 * th) - th
    return x


def declick_ramp(n, samples=64):
    r = np.ones(n)
    m = min(samples, n)
    r[:m] = np.linspace(0.0, 1.0, m)
    return r
