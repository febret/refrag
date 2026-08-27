"""Procedurally generated factory samples plus user WAV loading.

Refrag ships without binary assets: the default BeatBox kit, PCMSynth
instruments and Vocoder modulator loops are synthesized at startup.
Users can also upload WAV files which get stored under data/samples.
"""

import io
import os
import struct
import wave

import numpy as np

from .dsp import SR
from .state import SAMPLE_DIR

_rng = np.random.default_rng(42)
_cache = {}


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _expdecay(dur, rate):
    return np.exp(-_t(dur) * rate)


def _norm(x):
    peak = np.max(np.abs(x)) or 1.0
    return (x / peak * 0.92).astype(np.float32)


# ---------------------------------------------------------------------------
# Drum kit
# ---------------------------------------------------------------------------

def _kick():
    t = _t(0.45)
    freq = 42 + 240 * np.exp(-t * 33)
    ph = np.cumsum(freq) / SR
    body = np.sin(2 * np.pi * ph) * np.exp(-t * 7)
    click = _rng.uniform(-1, 1, len(t)) * np.exp(-t * 220) * 0.6
    return _norm(body + click)


def _snare():
    t = _t(0.3)
    tone = (np.sin(2 * np.pi * 185 * t) + 0.6 * np.sin(2 * np.pi * 330 * t)) * np.exp(-t * 22)
    noise = _rng.uniform(-1, 1, len(t)) * np.exp(-t * 14)
    return _norm(tone * 0.5 + noise * 0.8)


def _hat(open_):
    dur = 0.6 if open_ else 0.09
    t = _t(dur)
    n = _rng.uniform(-1, 1, len(t))
    # metallic: sum of square partials
    metal = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in
                (3211, 4189, 5333, 6427, 7523)) / 5
    x = (0.6 * n + 0.6 * metal) * np.exp(-t * (5 if open_ else 60))
    # highpass-ish: subtract smoothed version
    kernel = np.ones(24) / 24
    x = x - np.convolve(x, kernel, mode="same")
    return _norm(x)


def _clap():
    t = _t(0.35)
    n = _rng.uniform(-1, 1, len(t))
    env = np.zeros(len(t))
    for k, at in enumerate((0.0, 0.012, 0.024, 0.036)):
        idx = int(at * SR)
        seg = np.exp(-(np.arange(len(t) - idx)) / SR * (90 if k < 3 else 9))
        env[idx:] = np.maximum(env[idx:], seg)
    x = n * env
    kernel = np.ones(16) / 16
    x = x - 0.7 * np.convolve(x, kernel, mode="same")
    return _norm(x)


def _tom(freq):
    t = _t(0.5)
    f = freq * (1 + 0.6 * np.exp(-t * 18))
    ph = np.cumsum(f) / SR
    x = np.sin(2 * np.pi * ph) * np.exp(-t * 9)
    x += _rng.uniform(-1, 1, len(t)) * np.exp(-t * 60) * 0.25
    return _norm(x)


def _crash():
    t = _t(1.8)
    n = _rng.uniform(-1, 1, len(t))
    metal = sum(np.sign(np.sin(2 * np.pi * f * t + 0.7 * k)) for k, f in
                enumerate((2011, 3033, 4907, 6101, 8117))) / 5
    x = (n * 0.7 + metal * 0.5) * np.exp(-t * 2.2)
    kernel = np.ones(20) / 20
    x = x - 0.6 * np.convolve(x, kernel, mode="same")
    return _norm(x)


# ---------------------------------------------------------------------------
# Instruments for the PCMSynth
# ---------------------------------------------------------------------------

def _piano():
    """Struck-string-ish tone at C4."""
    f0 = 261.63
    t = _t(2.5)
    x = np.zeros(len(t))
    for k in range(1, 9):
        amp = 1.0 / k ** 1.3
        det = 1 + 0.0004 * k * k
        x += amp * np.sin(2 * np.pi * f0 * k * det * t) * np.exp(-t * (2.5 + k * 1.4))
    x *= (1 - np.exp(-t * 900))
    return _norm(x)


def _epiano():
    f0 = 261.63
    t = _t(2.2)
    x = np.sin(2 * np.pi * f0 * t + 2.2 * np.sin(2 * np.pi * f0 * 14 * t) *
               np.exp(-t * 9)) * np.exp(-t * 2.4)
    x += 0.3 * np.sin(2 * np.pi * f0 * 4 * t) * np.exp(-t * 6)
    return _norm(x)


def _strings():
    f0 = 261.63
    t = _t(2.0)
    x = np.zeros(len(t))
    for det in (-0.4, -0.13, 0.13, 0.4):
        ph = f0 * 2 ** (det / 100) * t + 0.003 * np.sin(2 * np.pi * 5.2 * t + det * 9)
        x += (2 * (ph - np.floor(ph)) - 1)
    kernel = np.ones(10) / 10
    x = np.convolve(x, kernel, mode="same")
    env = np.minimum(t * 4, 1.0)
    return _norm(x * env)


def _choir():
    f0 = 261.63
    t = _t(2.0)
    x = np.zeros(len(t))
    for det in (-0.3, 0.0, 0.3):
        ph = f0 * 2 ** (det / 100) * t
        saw = 2 * (ph - np.floor(ph)) - 1
        x += saw
    # crude formants (ah): resonate at 800 & 1150
    out = np.zeros(len(t))
    for fc, g in ((800, 1.0), (1150, 0.7), (2900, 0.25)):
        w = 2 * np.pi * fc / SR
        r = 0.995
        a = [1, -2 * r * np.cos(w), r * r]
        from scipy.signal import lfilter
        out += g * lfilter([1 - r], a, x)
    env = np.minimum(t * 3, 1.0)
    return _norm(out * env)


def _bass():
    f0 = 65.41
    t = _t(1.6)
    ph = f0 * t
    x = (2 * (ph - np.floor(ph)) - 1) * np.exp(-t * 3)
    x = np.tanh(x * 2.2)
    return _norm(x)


def _flute():
    f0 = 523.25
    t = _t(2.0)
    vib = 0.004 * np.sin(2 * np.pi * 5 * t) * np.minimum(t * 2, 1)
    x = np.sin(2 * np.pi * f0 * (t + vib)) + 0.2 * np.sin(2 * np.pi * 2 * f0 * t)
    x += 0.05 * _rng.uniform(-1, 1, len(t))
    env = np.minimum(t * 8, 1.0)
    return _norm(x * env)


# ---------------------------------------------------------------------------
# Vocoder modulator loops
# ---------------------------------------------------------------------------

def _vowels():
    """A loop cycling through vowel formant pairs (robot-speech-like)."""
    from scipy.signal import lfilter
    formants = [(730, 1090), (270, 2290), (300, 870), (530, 1840), (640, 1190)]
    seg = int(0.28 * SR)
    total = np.zeros(seg * len(formants))
    t = np.arange(seg) / SR
    src_ph = np.cumsum(np.full(seg, 110.0)) / SR
    src = ((src_ph % 1) < 0.12).astype(np.float64) * 2 - 1   # pulse train
    for i, (f1, f2) in enumerate(formants):
        y = np.zeros(seg)
        for fc, g in ((f1, 1.0), (f2, 0.8)):
            w = 2 * np.pi * fc / SR
            r = 0.992
            y += g * lfilter([1 - r], [1, -2 * r * np.cos(w), r * r], src)
        env = np.minimum(t * 30, 1.0) * np.minimum((seg / SR - t) * 30, 1.0)
        total[i * seg:(i + 1) * seg] = y * env
    return _norm(total)


def _rhythm():
    beat = int(0.125 * SR)
    total = np.zeros(beat * 16)
    for i in range(16):
        if i % 4 == 0:
            burst = _rng.uniform(-1, 1, beat) * np.exp(-np.arange(beat) / SR * 30)
        elif i % 2 == 0:
            burst = _rng.uniform(-1, 1, beat // 2) * np.exp(-np.arange(beat // 2) / SR * 60)
            burst = np.concatenate([burst, np.zeros(beat - len(burst))])
        else:
            burst = np.zeros(beat)
        total[i * beat:(i + 1) * beat] = burst
    return _norm(total)


def _robot():
    t = _t(2.0)
    x = np.sign(np.sin(2 * np.pi * 95 * t))
    gate = (np.sin(2 * np.pi * 3.1 * t) > -0.4).astype(np.float64)
    return _norm(x * gate)


FACTORY = {
    "kick": _kick, "snare": _snare, "clhat": lambda: _hat(False),
    "ophat": lambda: _hat(True), "clap": _clap,
    "tom_lo": lambda: _tom(105), "tom_hi": lambda: _tom(170),
    "crash": _crash,
    "piano": _piano, "epiano": _epiano, "strings": _strings,
    "choir": _choir, "bass": _bass, "flute": _flute,
    "vox_vowels": _vowels, "vox_rhythm": _rhythm, "vox_robot": _robot,
}


def factory_names():
    return sorted(FACTORY.keys())


def user_names():
    if not os.path.isdir(SAMPLE_DIR):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(SAMPLE_DIR)
                  if f.lower().endswith(".wav"))


def all_names():
    return factory_names() + [n for n in user_names() if n not in FACTORY]


def load_wav_bytes(data):
    """Parse a WAV file into mono float32 at SR."""
    with wave.open(io.BytesIO(data), "rb") as w:
        nch = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 1:
        x = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    elif width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8)
        raw = raw[:len(raw) - len(raw) % 3].reshape(-1, 3).astype(np.int32)
        v = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        x = v.astype(np.float32) / 8388608.0
    elif width == 4:
        x = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError("unsupported WAV bit depth")
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    if rate != SR and len(x) > 1:
        idx = np.linspace(0, len(x) - 1, int(len(x) * SR / rate))
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return x


def save_user_sample(name, data):
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    x = load_wav_bytes(data)          # validate + normalize format
    if len(x) < 32:
        raise ValueError("sample too short")
    # factory names shadow user files in get(); avoid the collision
    while name in FACTORY:
        name = name + "_u"
    path = os.path.join(SAMPLE_DIR, name + ".wav")
    write_wav(path, x)
    _cache.pop(name, None)
    return name


def get(name):
    """Return mono float32 sample data by name."""
    if name in _cache:
        return _cache[name]
    if name in FACTORY:
        x = FACTORY[name]()
    else:
        path = os.path.join(SAMPLE_DIR, name + ".wav")
        try:
            with open(path, "rb") as f:
                x = load_wav_bytes(f.read())
        except OSError:
            x = np.zeros(64, dtype=np.float32)
    _cache[name] = x
    return x


def write_wav(path_or_buf, mono_or_stereo):
    """Write float array (mono (n,) or stereo (2,n)) as 16-bit WAV."""
    x = np.asarray(mono_or_stereo)
    if x.ndim == 1:
        frames = x[:, None]
    else:
        frames = x.T
    pcm = np.clip(frames * 32767.0, -32768, 32767).astype("<i2")
    if isinstance(path_or_buf, (str, os.PathLike)):
        f = wave.open(str(path_or_buf), "wb")
    else:
        f = wave.open(path_or_buf, "wb")
    try:
        f.setnchannels(frames.shape[1])
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())
    finally:
        f.close()
