import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "tools"))

import wav2song

from server import aimatch
from server.state import Room

CFG = wav2song.DEFAULTS


def make_room(doc):
    """Runtime-only Room preloaded with a doc (no data/sessions access)."""
    room = Room.__new__(Room)
    room.id = "wav2song-unittest"
    room.doc = None
    room.lock = threading.RLock()
    room.rev = 0
    room.dirty = False
    room._last_save = 0.0
    room.listeners = set()
    room.engine = None
    room.runtime_only = True
    room.load_doc(doc)
    return room


def synth_clip(path, bpm=100.0, measures=4):
    """Write a simple synthetic loop: kick/hat pattern + sine chords."""
    sr = wav2song.SR
    spb = 60.0 / bpm
    total = int(measures * 4 * spb * sr)
    t = np.arange(total) / sr
    x = np.zeros(total, dtype=np.float32)

    def add_hit(beat, freq, dur, gain):
        i0 = int(beat * spb * sr)
        n = min(int(dur * sr), total - i0)
        if n <= 0:
            return
        tt = np.arange(n) / sr
        env = np.exp(-tt / (dur / 4))
        if freq:
            x[i0:i0 + n] += gain * env * np.sin(
                2 * np.pi * freq * tt * np.exp(-tt * 6))
        else:
            rng = np.random.default_rng(int(beat * 16))
            x[i0:i0 + n] += gain * env * rng.normal(0, 0.4, n)

    for meas in range(measures):
        b = meas * 4
        for k in (0, 2):
            add_hit(b + k, 55, 0.25, 0.9)              # kick-ish thump
        for k in (0.5, 1.5, 2.5, 3.5):
            add_hit(b + k, 0, 0.05, 0.6)               # hat-ish noise
    # sustained chord (A minor-ish) throughout
    for freq in (220.0, 261.63, 329.63):
        x += 0.08 * np.sin(2 * np.pi * freq * t)
    x = np.clip(x, -1, 1)
    wav2song.save_wav(path, np.stack([x, x]))


class TestAnalysis(unittest.TestCase):
    """Pure-DSP pieces that do not need the Basic Pitch model."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wav2song_test_")
        cls.clip = os.path.join(cls.tmp, "clip.wav")
        synth_clip(cls.clip)
        cls.audio = wav2song.load_wav(cls.clip)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_load_wav(self):
        self.assertGreater(len(self.audio), wav2song.SR)
        self.assertLessEqual(float(np.max(np.abs(self.audio))), 1.0)

    def test_bpm_detection(self):
        bpm, offset = wav2song.detect_tempo(self.audio, CFG)
        # accept metrical multiples of the true 100 BPM
        ratio = bpm / 100.0
        nearest = min((0.5, 1.0, 2.0), key=lambda r: abs(ratio - r))
        self.assertLess(abs(ratio - nearest) / nearest, 0.03)

    def test_drone_stack_detects_sustained_chord(self):
        stack = wav2song.detect_drone_stack(self.audio,
                                            CFG["layers"]["drones"])
        midis = [m for m, _ in stack]
        self.assertTrue(any(m in midis for m in (57, 60, 64)),
                        "expected A3/C4/E4 in %r" % midis)

    def test_simplify_notes_grid_and_chords(self):
        notes = [[60, 0.013, 0.11, 0.7], [64, 0.02, 0.4, 0.9],
                 [60, 0.55, 0.2, 0.5], [67, 0.021, 0.3, 0.8]]
        cfg = wav2song.deep_merge(CFG, {"simplify": {"max_chord": 2}})
        out = wav2song.simplify_notes(notes, "chord", cfg)
        for key, start, dur, vel in out:
            self.assertAlmostEqual(start % 0.5, 0.0)
            self.assertGreaterEqual(dur, 1.0)
            self.assertIn(vel, tuple(CFG["grid"]["vel_levels"]))
        starts = [n[1] for n in out]
        self.assertLessEqual(starts.count(0.0), 2)     # chord cap applies

    def test_find_loop(self):
        notes = []
        for i in range(4):                             # 4 identical measures
            notes.extend([[0, i * 4.0, 0.25, 1.0], [2, i * 4.0 + 2, 0.25, 0.8]])
        loop_beats, loop = wav2song.find_loop(notes, 16.0, CFG)
        self.assertEqual(loop_beats, 4.0)
        self.assertEqual(len(loop), 2)

    def test_drum_layer_builds_doc(self):
        builder = wav2song.SongBuilder(100.0, 0.0, 9.6, CFG)
        notes = []
        for meas in range(4):
            for beat in (0, 1, 2, 3):
                notes.append([0, meas * 4.0 + beat, 0.25, 1.0])
        builder.add_layer(wav2song.drums_machine(CFG["layers"]["drums"]),
                          notes, "drum")
        doc = builder.finish("test")
        room = make_room(json.loads(json.dumps(doc)))  # round-trips as JSON
        self.assertEqual(room.doc["machines"][0]["type"], "beatbox")


@unittest.skipUnless(os.path.exists(aimatch.MODEL_PATH),
                     "Basic Pitch model not downloaded")
class TestPipeline(unittest.TestCase):
    """Full CLI pipeline on a synthetic clip (no auto-balance)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wav2song_pipe_")
        cls.clip = os.path.join(cls.tmp, "clip.wav")
        synth_clip(cls.clip)
        cls.out = os.path.join(cls.tmp, "song.json")
        wav2song.main([cls.clip, "-o", cls.out, "--tune", "0", "--quiet"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        with open(self.out, "r", encoding="utf-8") as f:
            self.doc = json.load(f)

    def test_session_loads_and_renders(self):
        room = make_room(self.doc)
        rendered = wav2song.render_doc(room.doc)
        self.assertGreater(float(np.max(np.abs(rendered))), 1e-4)

    def test_has_machines_and_blocks(self):
        machines = [m for m in self.doc["machines"] if m]
        self.assertGreaterEqual(len(machines), 2)
        self.assertTrue(self.doc["song"])
        slots = {b["machine"] for b in self.doc["song"]}
        self.assertEqual(slots, set(range(len(machines))))

    def test_notes_are_grid_aligned(self):
        grid = CFG["grid"]["step"]
        for m in self.doc["machines"]:
            if not m:
                continue
            for pat in m["patterns"].values():
                for key, start, dur, vel, flags in pat["notes"]:
                    frac = (start / grid) % 1.0
                    self.assertLess(min(frac, 1 - frac), 1e-6,
                                    "off-grid note in %s" % m["name"])
                    self.assertGreaterEqual(dur, grid - 1e-9)


class TestConfig(unittest.TestCase):
    def test_deep_merge_nested(self):
        cfg = wav2song.deep_merge(
            CFG, {"tempo": {"bpm": 120.0},
                  "layers": {"bass": {"params": {"volume": 0.5}}}})
        self.assertEqual(cfg["tempo"]["bpm"], 120.0)
        self.assertEqual(cfg["layers"]["bass"]["params"]["volume"], 0.5)
        # untouched keys stay at defaults; DEFAULTS is not mutated
        self.assertEqual(cfg["tune"]["rounds"], CFG["tune"]["rounds"])
        self.assertIsNone(CFG["tempo"]["bpm"])

    def test_validate_rejects_unknown_keys(self):
        with self.assertRaises(KeyError):
            wav2song.validate_cfg({"tempoo": {}})
        with self.assertRaises(KeyError):
            wav2song.validate_cfg({"layers": {"drums": {"bogus": 1}}})

    def test_load_cfg_yaml(self):
        tmp = tempfile.mkdtemp(prefix="wav2song_cfg_")
        try:
            path = os.path.join(tmp, "cfg.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("tempo:\n  bpm: 95.5\n"
                        "simplify:\n  max_chord: 3\n"
                        "layers:\n  drones:\n    enabled: false\n")
            cfg = wav2song.load_cfg(path)
            self.assertEqual(cfg["tempo"]["bpm"], 95.5)
            self.assertEqual(cfg["simplify"]["max_chord"], 3)
            self.assertFalse(cfg["layers"]["drones"]["enabled"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_overrides_cfg(self):
        tmp = tempfile.mkdtemp(prefix="wav2song_cfg_")
        try:
            path = os.path.join(tmp, "cfg.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("tune:\n  rounds: 7\n")
            args = wav2song.parse_args(
                ["in.wav", "--cfg", path, "--tune", "1", "--no-drums"])
            cfg = wav2song.effective_cfg(args)
            self.assertEqual(cfg["tune"]["rounds"], 1)
            self.assertFalse(cfg["layers"]["drums"]["enabled"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
