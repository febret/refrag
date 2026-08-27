"""AI Match: transcribe a short audio clip into pattern notes.

Pitched machines use Spotify's Basic Pitch neural network (the tiny
~230KB ``nmp.onnx`` model, Apache-2.0) executed through onnxruntime,
with the pre/post-processing reimplemented here in numpy/scipy (the
``basic-pitch`` package itself is not a dependency).  Beatbox machines
use a DSP onset detector plus a spectral-band classifier that maps hits
onto the 8 drum channels.

The model file is downloaded once into ``data/models/`` on first use.
The model is small enough that CPU inference takes milliseconds; if an
onnxruntime GPU build is installed its CUDA provider is used
automatically.
"""

import math
import os
import threading
import urllib.request

import numpy as np
import scipy.signal

from .state import DATA_DIR

try:
    import onnxruntime
except ImportError:                       # surfaced as a friendly error on use
    onnxruntime = None

MODEL_URL = ("https://raw.githubusercontent.com/spotify/basic-pitch/main/"
             "basic_pitch/saved_models/icassp_2022/nmp.onnx")
MODEL_DIR = os.path.join(DATA_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "nmp.onnx")
MODEL_MIN_BYTES = 100_000                 # sanity check on the download

# Basic Pitch constants (basic_pitch/constants.py)
BP_SR = 22050
FFT_HOP = 256
AUDIO_N_SAMPLES = BP_SR * 2 - FFT_HOP     # 43844 samples per model window
N_OVERLAP_FRAMES = 30
OVERLAP_LEN = N_OVERLAP_FRAMES * FFT_HOP  # 7680
HOP_SIZE = AUDIO_N_SAMPLES - OVERLAP_LEN  # 36164
ANNOT_FPS = BP_SR // FFT_HOP              # 86 output frames per second
ANNOT_N_FRAMES = ANNOT_FPS * 2            # 172 output frames per window
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87
MAGIC_ALIGNMENT_OFFSET = 0.0018

ONSET_THRESH = 0.5
FRAME_THRESH = 0.3
MIN_NOTE_LEN = 11                         # frames (~128 ms)
ENERGY_TOL = 11
MELODIA_MAX_NOTES = 400

MAX_CLIP_SECONDS = 30.0
GRID = 0.25                               # quantize to 1/16 notes (beats)
MEASURE_CHOICES = (1, 2, 4, 8)

_session = None
_session_lock = threading.Lock()


# -- model management ---------------------------------------------------------

def ensure_model():
    """Download and cache the Basic Pitch ONNX model; returns its path."""
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) >= MODEL_MIN_BYTES:
        return MODEL_PATH
    os.makedirs(MODEL_DIR, exist_ok=True)
    tmp = MODEL_PATH + ".tmp"
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=30) as resp, \
                open(tmp, "wb") as f:
            f.write(resp.read())
        if os.path.getsize(tmp) < MODEL_MIN_BYTES:
            raise OSError("model download truncated")
        os.replace(tmp, MODEL_PATH)
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("could not download the AI Match model "
                           f"({e}); check the server's internet access") from e
    return MODEL_PATH


def get_session():
    """Lazily create the shared onnxruntime session."""
    global _session
    if onnxruntime is None:
        raise RuntimeError("onnxruntime is not installed; "
                           "run: pip install -r requirements.txt")
    with _session_lock:
        if _session is None:
            path = ensure_model()
            avail = onnxruntime.get_available_providers()
            providers = [p for p in ("CUDAExecutionProvider",
                                     "CPUExecutionProvider") if p in avail]
            _session = onnxruntime.InferenceSession(path, providers=providers)
        return _session


# -- pitched transcription (Basic Pitch) --------------------------------------

def _resample(audio, sr, target):
    audio = np.asarray(audio, dtype=np.float32)
    if sr == target:
        return audio
    g = math.gcd(int(target), int(sr))
    return scipy.signal.resample_poly(audio, target // g, sr // g).astype(np.float32)


def _run_model(audio_22k):
    """Run the model over overlapping windows; returns (note_pg, onset_pg)."""
    orig_len = len(audio_22k)
    padded = np.concatenate([np.zeros(OVERLAP_LEN // 2, dtype=np.float32),
                             audio_22k])
    windows = []
    for i in range(0, len(padded), HOP_SIZE):
        w = padded[i:i + AUDIO_N_SAMPLES]
        if len(w) < AUDIO_N_SAMPLES:
            w = np.pad(w, (0, AUDIO_N_SAMPLES - len(w)))
        windows.append(w)
    x = np.stack(windows)[:, :, None].astype(np.float32)
    sess = get_session()
    # output tensors: :1 = note, :2 = onset (see basic_pitch/inference.py)
    note, onset = sess.run(["StatefulPartitionedCall:1",
                            "StatefulPartitionedCall:2"],
                           {sess.get_inputs()[0].name: x})
    return _unwrap(note, orig_len), _unwrap(onset, orig_len)


def _unwrap(output, orig_len):
    """(n_windows, 172, 88) -> (n_frames, 88), overlap frames removed."""
    n_olap = N_OVERLAP_FRAMES // 2
    output = output[:, n_olap:-n_olap, :]
    out = output.reshape(output.shape[0] * output.shape[1], output.shape[2])
    n_frames_per_window = ANNOT_N_FRAMES - N_OVERLAP_FRAMES
    return out[:int(orig_len / HOP_SIZE * n_frames_per_window)]


def _frames_to_time(n_frames):
    """Model output frame index -> seconds (basic_pitch.model_frames_to_time)."""
    times = np.arange(n_frames) * FFT_HOP / BP_SR
    window_numbers = np.floor(np.arange(n_frames) / ANNOT_N_FRAMES)
    window_offset = (FFT_HOP / BP_SR) * (
        ANNOT_N_FRAMES - AUDIO_N_SAMPLES / FFT_HOP) + MAGIC_ALIGNMENT_OFFSET
    return times - window_offset * window_numbers


def notes_from_posteriorgrams(note_pg, onset_pg,
                              onset_thresh=ONSET_THRESH,
                              frame_thresh=FRAME_THRESH,
                              min_note_len=MIN_NOTE_LEN):
    """Decode posteriorgrams into [(start_s, end_s, midi, amplitude)].

    Follows basic_pitch.note_creation.output_to_notes_polyphonic
    (onset-driven pass + "melodia trick" for onset-less sustained notes).
    """
    frames = np.array(note_pg, dtype=np.float64)
    onsets = np.array(onset_pg, dtype=np.float64)
    n_frames = frames.shape[0]
    if n_frames < 2:
        return []

    # infer additional onsets from sharp rises in the note posteriorgram
    diffs = []
    for n in (1, 2):
        appended = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(appended[n:, :] - appended[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:2, :] = 0
    if np.max(frame_diff) > 0:
        frame_diff = np.max(onsets) * frame_diff / np.max(frame_diff)
    onsets = np.maximum(onsets, frame_diff)

    peak_mat = np.zeros_like(onsets)
    peaks = scipy.signal.argrelmax(onsets, axis=0)
    peak_mat[peaks] = onsets[peaks]
    onset_idx = np.where(peak_mat >= onset_thresh)
    onset_t = onset_idx[0][::-1]          # backwards in time
    onset_f = onset_idx[1][::-1]

    remaining = frames.copy()
    events = []                           # (start_frame, end_frame, midi, amp)

    for t0, f in zip(onset_t, onset_f):
        if t0 >= n_frames - 1:
            continue
        i, k = t0 + 1, 0
        while i < n_frames - 1 and k < ENERGY_TOL:
            k = k + 1 if remaining[i, f] < frame_thresh else 0
            i += 1
        i -= k
        if i - t0 <= min_note_len:
            continue
        remaining[t0:i, f] = 0
        if f < MAX_FREQ_IDX:
            remaining[t0:i, f + 1] = 0
        if f > 0:
            remaining[t0:i, f - 1] = 0
        events.append((t0, i, f + MIDI_OFFSET, float(np.mean(frames[t0:i, f]))))

    # melodia trick: sweep up leftover energy into sustained notes
    for _ in range(MELODIA_MAX_NOTES):
        if np.max(remaining) <= frame_thresh:
            break
        i_mid, f = np.unravel_index(np.argmax(remaining), remaining.shape)
        remaining[i_mid, f] = 0
        i, k = i_mid + 1, 0
        while i < n_frames - 1 and k < ENERGY_TOL:
            k = k + 1 if remaining[i, f] < frame_thresh else 0
            remaining[i, f] = 0
            if f < MAX_FREQ_IDX:
                remaining[i, f + 1] = 0
            if f > 0:
                remaining[i, f - 1] = 0
            i += 1
        i_end = i - 1 - k
        i, k = i_mid - 1, 0
        while i > 0 and k < ENERGY_TOL:
            k = k + 1 if remaining[i, f] < frame_thresh else 0
            remaining[i, f] = 0
            if f < MAX_FREQ_IDX:
                remaining[i, f + 1] = 0
            if f > 0:
                remaining[i, f - 1] = 0
            i -= 1
        i_start = i + 1 + k
        if i_end - i_start <= min_note_len:
            continue
        events.append((i_start, i_end, f + MIDI_OFFSET,
                       float(np.mean(frames[i_start:i_end, f]))))

    times = _frames_to_time(n_frames)
    return [(float(times[t0]), float(times[min(t1, n_frames - 1)]), midi, amp)
            for t0, t1, midi, amp in events]


def transcribe(audio, sr):
    """Mono float audio -> [(start_s, end_s, midi, amplitude)]."""
    x = _resample(audio, sr, BP_SR)
    x = x[:int(MAX_CLIP_SECONDS * BP_SR)]
    if len(x) < FFT_HOP or float(np.max(np.abs(x))) < 1e-4:
        return []
    note_pg, onset_pg = _run_model(x)
    return notes_from_posteriorgrams(note_pg, onset_pg)


# -- drum transcription (beatbox) ---------------------------------------------

# beatbox channel indices (see state.DEFAULT_BEATBOX_KIT)
KICK, SNARE, CLHAT, OPHAT, CLAP, TOM_LO, TOM_HI, CRASH = range(8)


def transcribe_drums(audio, sr):
    """Mono float audio -> [(channel, time_s, amplitude)] drum hits."""
    x = _resample(audio, sr, BP_SR)
    x = x[:int(MAX_CLIP_SECONDS * BP_SR)]
    if len(x) < 2048 or float(np.max(np.abs(x))) < 1e-4:
        return []
    hop = 256
    f, t, Z = scipy.signal.stft(x, fs=BP_SR, nperseg=1024,
                                noverlap=1024 - hop, padded=False)
    mag = np.abs(Z)
    if mag.shape[1] < 4:
        return []
    # prepend a silent column so a hit at t=0 still registers as an attack,
    # and a leading zero so find_peaks can mark it as a peak
    flux = np.sum(np.clip(np.diff(mag, axis=1, prepend=0.0), 0, None), axis=0)
    flux = np.concatenate([[0.0], flux])
    if np.max(flux) <= 0:
        return []
    flux /= np.max(flux)
    min_gap = max(1, int(0.06 * BP_SR / hop))            # >= 60 ms apart
    height = max(0.08, float(np.mean(flux) + 0.5 * np.std(flux)))
    peaks, props = scipy.signal.find_peaks(flux, height=height,
                                           distance=min_gap)
    lo = f < 120
    lomid = (f >= 120) & (f < 400)
    mid = (f >= 400) & (f < 2500)
    hi = f >= 3500
    events = []
    for p, strength in zip(peaks, props["peak_heights"]):
        col = max(0, p - 1)               # flux is shifted by the leading zero
        a, b = col, min(col + max(1, int(0.05 * BP_SR / hop)), mag.shape[1])
        win = mag[:, a:b].mean(axis=1)
        total = float(np.sum(win)) + 1e-12
        e_lo = float(np.sum(win[lo])) / total
        e_lomid = float(np.sum(win[lomid])) / total
        e_mid = float(np.sum(win[mid])) / total
        e_hi = float(np.sum(win[hi])) / total
        # sustain of the high band ~90-150 ms after the hit vs at the hit
        c, d = min(col + int(0.09 * BP_SR / hop), mag.shape[1] - 1), \
            min(col + int(0.15 * BP_SR / hop), mag.shape[1])
        tail = mag[hi, c:d].mean() if d > c else 0.0
        head = float(win[hi].mean()) + 1e-12
        sustain = float(tail) / head
        if e_lo > 0.35:
            ch = KICK
        elif e_hi > 0.5:
            if sustain > 0.6 and strength > 0.6:
                ch = CRASH
            elif sustain > 0.35:
                ch = OPHAT
            else:
                ch = CLHAT
        elif e_mid > 0.45:
            ch = SNARE if e_hi > 0.12 else CLAP
        elif e_lomid > 0.4:
            ch = TOM_LO if e_lo > e_mid else TOM_HI
        else:
            ch = SNARE
        events.append((ch, float(t[col]), float(strength)))
    return events


# -- pattern building ----------------------------------------------------------

def _fit_measures(max_end_beats):
    for L in MEASURE_CHOICES:
        if max_end_beats <= L * 4 + 1e-6:
            return L
    return MEASURE_CHOICES[-1]


def _velocities(amps):
    top = max(amps) if amps else 1.0
    top = top if top > 1e-9 else 1.0
    return [round(min(1.0, max(0.2, 0.3 + 0.7 * a / top)), 3) for a in amps]


def events_to_pattern(events, bpm):
    """Pitched note events -> {"length": L, "notes": [...]} at the room bpm."""
    spb = 60.0 / float(bpm)
    quant = []
    for start_s, end_s, midi, amp in events:
        start = round(start_s / spb / GRID) * GRID
        dur = max(GRID, round((end_s - start_s) / spb / GRID) * GRID)
        quant.append((int(midi), start, dur, amp))
    if not quant:
        return {"length": 1, "notes": []}
    length = _fit_measures(max(s + d for _, s, d, _ in quant))
    span = length * 4
    vels = _velocities([q[3] for q in quant])
    best = {}
    for (midi, start, dur, _), vel in zip(quant, vels):
        if not 0 <= start < span:
            continue
        key = (midi, start)
        dur = min(dur, span - start)
        if key not in best or vel > best[key][3]:
            best[key] = [midi, start, dur, vel, 0]
    notes = sorted(best.values(), key=lambda n: (n[1], n[0]))
    return {"length": length, "notes": notes}


def drum_events_to_pattern(events, bpm):
    """Drum hits -> {"length": L, "notes": [...]} on the 16th-note grid."""
    spb = 60.0 / float(bpm)
    quant = []
    for ch, time_s, amp in events:
        start = round(time_s / spb / GRID) * GRID
        quant.append((int(ch), start, amp))
    if not quant:
        return {"length": 1, "notes": []}
    length = _fit_measures(max(s for _, s, _ in quant) + GRID)
    span = length * 4
    vels = _velocities([q[2] for q in quant])
    best = {}
    for (ch, start, _), vel in zip(quant, vels):
        if not 0 <= start < span:
            continue
        key = (ch, start)
        if key not in best or vel > best[key][3]:
            best[key] = [ch, start, GRID, vel, 0]
    notes = sorted(best.values(), key=lambda n: (n[1], n[0]))
    return {"length": length, "notes": notes}


def match_pattern(audio, sr, bpm, drum=False):
    """Full AI Match: audio -> pattern dict for the current machine."""
    if drum:
        return drum_events_to_pattern(transcribe_drums(audio, sr), bpm)
    return events_to_pattern(transcribe(audio, sr), bpm)
