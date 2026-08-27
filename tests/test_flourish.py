"""Tests for the Flourish pattern-expansion tool."""

import tempfile
import unittest

from server import flourish, state
from server.engine import AudioEngine


class FlourishGenerateTests(unittest.TestCase):
    def setUp(self):
        self.pat = {"length": 2, "notes": [
            [60, 0.0, 1.0, 0.9, 0],
            [64, 2.0, 1.0, 0.8, 0],
            [67, 4.0, 2.0, 0.8, 1],
        ]}

    def test_deterministic_per_seed(self):
        for themes in ([], ["major"], ["minor", "fast"],
                       ["jazzy", "arp", "octaves"], ["mellow", "syncopated"]):
            a = flourish.generate(self.pat, themes, 42)
            b = flourish.generate(self.pat, themes, 42)
            self.assertEqual(a, b)

    def test_reroll_changes_output(self):
        a = flourish.generate(self.pat, ["major", "fast"], 1)
        b = flourish.generate(self.pat, ["major", "fast"], 2)
        self.assertNotEqual(a, b)

    def test_notes_flagged_and_in_bounds(self):
        span = self.pat["length"] * 4
        for themes in (["fast"], ["mellow"], ["syncopated", "octaves"]):
            for n in flourish.generate(self.pat, themes, 7):
                self.assertTrue(n[4] & flourish.FLAG)
                self.assertGreaterEqual(n[1], 0)
                self.assertLess(n[1], span)
                self.assertLessEqual(n[1] + n[2], span + 1e-9)
                self.assertTrue(0 <= n[0] <= 127)
                self.assertTrue(0.05 <= n[3] <= 1.0)

    def test_original_notes_untouched(self):
        before = [list(n) for n in self.pat["notes"]]
        flourish.generate(self.pat, ["major", "fast", "arp"], 3)
        self.assertEqual(self.pat["notes"], before)

    def test_generates_something_for_every_theme(self):
        for theme in flourish.THEMES:
            added = flourish.generate(self.pat, [theme], 5)
            self.assertGreater(len(added), 0, theme)

    def test_empty_pattern_gets_anchors(self):
        added = flourish.generate({"length": 1, "notes": []}, ["major"], 1)
        self.assertGreater(len(added), 0)

    def test_drum_mode_stays_on_channels(self):
        pat = {"length": 1, "notes": [[0, 0.0, 0.25, 1.0, 0],
                                      [1, 1.0, 0.25, 1.0, 0]]}
        for themes in (["fast"], ["mellow"], ["minor", "syncopated"],
                       list(flourish.THEMES)):
            added = flourish.generate(pat, themes, 9, drum=True)
            self.assertGreater(len(added), 0)
            for n in added:
                self.assertTrue(0 <= n[0] < 8)
                self.assertTrue(n[4] & flourish.FLAG)
                self.assertLess(n[1], 4)

    def test_no_duplicate_positions(self):
        added = flourish.generate(self.pat, ["fast", "syncopated"], 11)
        existing = {(n[0], round(n[1] * 8)) for n in self.pat["notes"]}
        seen = set()
        for n in added:
            key = (n[0], round(n[1] * 8))
            self.assertNotIn(key, existing)
            self.assertNotIn(key, seen)
            seen.add(key)


class FlourishOpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = state.SESSION_DIR
        state.SESSION_DIR = self.tmp.name
        self.room = state.Room("flourish-room")
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "add_note", "slot": 0, "note": 60,
                         "start": 0.0, "dur": 1.0, "vel": 0.9})

    def tearDown(self):
        state.SESSION_DIR = self._orig
        self.tmp.cleanup()

    def pat(self):
        return self.room.get_pattern(self.room.machine(0))

    def fl_notes(self):
        return [n for n in self.pat()["notes"] if n[4] & flourish.FLAG]

    def test_flourish_generates_and_stores_meta(self):
        self.assertTrue(self.room.apply({"op": "flourish", "slot": 0,
                                         "themes": ["major"], "seed": 5}))
        self.assertGreater(len(self.fl_notes()), 0)
        meta = self.pat()["flourish"]
        self.assertEqual(meta, {"on": 1, "themes": ["major"], "seed": 5})

    def test_reroll_replaces_flourish_keeps_base(self):
        self.room.apply({"op": "flourish", "slot": 0,
                         "themes": ["major", "fast"], "seed": 5})
        first = [list(n) for n in self.fl_notes()]
        self.room.apply({"op": "flourish", "slot": 0,
                         "themes": ["major", "fast"], "seed": 6})
        self.assertNotEqual([list(n) for n in self.fl_notes()], first)
        self.assertIn([60, 0.0, 1.0, 0.9, 0],
                      [list(n) for n in self.pat()["notes"]])

    def test_unknown_themes_filtered(self):
        self.assertTrue(self.room.apply({"op": "flourish", "slot": 0,
                                         "themes": ["major", "bogus"],
                                         "seed": 1}))
        self.assertEqual(self.pat()["flourish"]["themes"], ["major"])

    def test_toggle(self):
        self.assertFalse(self.room.apply({"op": "flourish_toggle", "slot": 0,
                                          "on": 0}))   # nothing generated yet
        self.room.apply({"op": "flourish", "slot": 0, "themes": [], "seed": 1})
        self.assertTrue(self.room.apply({"op": "flourish_toggle", "slot": 0,
                                         "on": 0}))
        self.assertEqual(self.pat()["flourish"]["on"], 0)
        self.assertTrue(self.room.apply({"op": "flourish_toggle", "slot": 0,
                                         "on": 1}))
        self.assertEqual(self.pat()["flourish"]["on"], 1)

    def test_commit_turns_note_normal(self):
        self.room.apply({"op": "flourish", "slot": 0, "themes": ["major"],
                         "seed": 5})
        notes = self.pat()["notes"]
        idx = next(i for i, n in enumerate(notes) if n[4] & flourish.FLAG)
        self.assertTrue(self.room.apply({"op": "flourish_commit", "slot": 0,
                                         "index": idx}))
        self.assertFalse(notes[idx][4] & flourish.FLAG)
        # committing a normal note is rejected
        self.assertFalse(self.room.apply({"op": "flourish_commit", "slot": 0,
                                          "index": idx}))

    def test_clear_removes_flourish_only(self):
        self.room.apply({"op": "flourish", "slot": 0, "themes": ["fast"],
                         "seed": 5})
        self.assertTrue(self.room.apply({"op": "flourish_clear", "slot": 0}))
        self.assertEqual(self.fl_notes(), [])
        self.assertEqual(len(self.pat()["notes"]), 1)
        self.assertNotIn("flourish", self.pat())

    def test_set_pattern_notes(self):
        self.assertTrue(self.room.apply({
            "op": "set_pattern_notes", "slot": 0, "length": 2,
            "notes": [[60, 0.0, 1.0, 0.8], [64, 4.0, 2.0, 0.7, 0],
                      [99, 99.0, 1, 1]]}))   # out-of-range note dropped
        pat = self.pat()
        self.assertEqual(pat["length"], 2)
        self.assertEqual(len(pat["notes"]), 2)
        self.assertFalse(self.room.apply({"op": "set_pattern_notes",
                                          "slot": 0, "length": 3,
                                          "notes": []}))


class FlourishEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = state.SESSION_DIR
        state.SESSION_DIR = self.tmp.name
        self.room = state.Room("flourish-engine-room")
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.engine = AudioEngine(self.room)
        m = self.room.machine(0)
        m["patterns"]["A1"] = {
            "length": 1,
            "notes": [[60, 0.0, 1.0, 0.9, 0],       # normal
                      [64, 1.0, 1.0, 0.7, 4],       # flourish
                      [67, 2.0, 1.0, 0.7, 4 | 1]],  # flourish + accent
            "flourish": {"on": 1, "themes": [], "seed": 0},
        }

    def tearDown(self):
        state.SESSION_DIR = self._orig
        self.tmp.cleanup()

    def events(self):
        m = self.room.machine(0)
        evs = self.engine._pattern_events(0, m, 0.0, 4.0, self.room.doc)
        return sorted(e for e in evs if e[1] == "on")

    def test_flourish_notes_play_when_on(self):
        ons = self.events()
        self.assertEqual([e[2] for e in ons], [60, 64, 67])
        # bit 4 is stripped before reaching the synth; accent survives
        self.assertEqual([e[4] for e in ons], [0, 0, 1])

    def test_flourish_notes_skipped_when_off(self):
        pat = self.room.machine(0)["patterns"]["A1"]
        pat["flourish"]["on"] = 0
        ons = self.events()
        self.assertEqual([e[2] for e in ons], [60])

    def test_patterns_without_meta_play_everything(self):
        pat = self.room.machine(0)["patterns"]["A1"]
        del pat["flourish"]
        self.assertEqual([e[2] for e in self.events()], [60, 64, 67])


if __name__ == "__main__":
    unittest.main()
