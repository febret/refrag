"""Tests for room state operations."""

import os
import tempfile
import unittest

from server import state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = state.SESSION_DIR
        state.SESSION_DIR = self.tmp.name
        self.room = state.Room("test-room")

    def tearDown(self):
        state.SESSION_DIR = self._orig
        self.tmp.cleanup()

    def test_add_and_remove_machine(self):
        self.assertTrue(self.room.apply({"op": "add_machine", "slot": 0,
                                         "mtype": "subsynth"}))
        self.assertEqual(self.room.doc["machines"][0]["type"], "subsynth")
        self.assertTrue(self.room.apply({"op": "remove_machine", "slot": 0}))
        self.assertIsNone(self.room.doc["machines"][0])


    def test_set_param(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "bassline"})
        self.assertTrue(self.room.apply({"op": "set_param", "slot": 0,
                                         "param": "cutoff", "value": 0.9}))
        self.assertEqual(self.room.doc["machines"][0]["params"]["cutoff"], 0.9)
        self.assertFalse(self.room.apply({"op": "set_param", "slot": 0,
                                          "param": "nope", "value": 1}))

    def test_live_transpose_defaults_clamps_and_skips_beatbox(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        m = self.room.machine(0)
        self.assertEqual(m["transpose"], 0)
        self.assertEqual(len(m["transpose_steps"]), 4)
        self.assertTrue(self.room.apply({
            "op": "set_transpose", "slot": 0, "value": 99,
        }))
        self.assertEqual(m["transpose"], 24)
        self.assertTrue(all(step["transpose"] == 24 for step in m["transpose_steps"]))
        self.room.apply({"op": "add_machine", "slot": 1, "mtype": "beatbox"})
        self.assertFalse(self.room.apply({
            "op": "set_transpose", "slot": 1, "value": 12,
        }))


    def test_saved_song_can_be_loaded_from_disk(self):
        self.room.apply({"op": "set_song_prop", "prop": "name", "value": "Saved Song"})
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "set_param", "slot": 0, "param": "flt_cutoff", "value": 0.5})
        self.room.save(force=True)

        manager = state.RoomManager()
        self.assertIn("test-room", manager.list())

        loaded = state.Room("other-room")
        self.assertTrue(loaded.load_snapshot("test-room"))
        self.assertEqual(loaded.doc["name"], "Saved Song")
        self.assertEqual(loaded.machine(0)["params"]["flt_cutoff"], 0.5)

    def test_looper_selects_immediately_without_engine(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.doc["transport"]["mode"] = "song"
        self.assertTrue(self.room.apply({
            "op": "looper_pattern", "slot": 0, "bank": 2, "pattern": 7,
        }))
        m = self.room.machine(0)
        self.assertEqual((m["bank"], m["pattern"]), (2, 7))
        self.assertEqual(self.room.doc["transport"]["mode"], "pattern")
        self.assertFalse(self.room.apply({
            "op": "looper_pattern", "slot": 0, "bank": 4, "pattern": 0,
        }))

    def test_looper_mode_and_bank_ops(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        m = self.room.machine(0)
        self.assertEqual(m["looper_mode"], "queue")
        self.assertTrue(self.room.apply({
            "op": "looper_set_mode", "slot": 0, "mode": "random",
        }))
        self.assertEqual(m["looper_mode"], "random")
        self.assertTrue(self.room.apply({
            "op": "looper_set_bank", "slot": 0, "bank": 3,
        }))
        self.assertEqual(m["looper_bank"], 3)

    def test_set_transpose_step_updates_single_step(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        m = self.room.machine(0)
        self.assertTrue(self.room.apply({
            "op": "set_transpose_step", "slot": 0, "step": 2,
            "transpose": -7, "loops": 4,
        }))
        self.assertEqual(m["transpose_steps"][2]["transpose"], -7)
        self.assertEqual(m["transpose_steps"][2]["loops"], 4)
        self.assertFalse(self.room.apply({
            "op": "set_transpose_step", "slot": 0, "step": 2,
            "transpose": -7, "loops": 4,
        }))

    def test_notes_roundtrip(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        m = self.room.doc["machines"][0]
        self.assertTrue(self.room.apply({"op": "add_note", "slot": 0,
                                         "note": 60, "start": 0, "dur": 1,
                                         "vel": 0.8}))
        pat = m["patterns"]["A1"]
        self.assertEqual(len(pat["notes"]), 1)
        self.assertTrue(self.room.apply({"op": "update_note", "slot": 0,
                                         "index": 0, "note": 62}))
        self.assertEqual(pat["notes"][0][0], 62)
        self.assertTrue(self.room.apply({"op": "remove_note", "slot": 0,
                                         "index": 0}))
        self.assertEqual(pat["notes"], [])


    def test_pattern_length_trims_notes(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "set_pattern_length", "slot": 0, "length": 2})
        self.room.apply({"op": "add_note", "slot": 0, "note": 60,
                         "start": 6, "dur": 1})
        self.room.apply({"op": "set_pattern_length", "slot": 0, "length": 1})
        self.assertEqual(self.room.doc["machines"][0]["patterns"]["A1"]["notes"], [])

    def test_song_blocks(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.assertTrue(self.room.apply({"op": "song_add", "machine": 0,
                                         "bank": 0, "pattern": 0, "start": 4,
                                         "length": 2}))
        blk = self.room.doc["song"][0]
        self.assertTrue(self.room.apply({"op": "song_update", "id": blk["id"],
                                         "start": 8}))
        self.assertEqual(self.room.doc["song"][0]["start"], 8)
        self.assertTrue(self.room.apply({"op": "song_remove", "id": blk["id"]}))
        self.assertEqual(self.room.doc["song"], [])

    def test_remove_machine_drops_song_blocks(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "song_add", "machine": 0, "bank": 0,
                         "pattern": 0, "start": 0, "length": 1})
        self.room.apply({"op": "remove_machine", "slot": 0})
        self.assertEqual(self.room.doc["song"], [])

    def test_effects(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.assertTrue(self.room.apply({"op": "set_effect", "slot": 0,
                                         "index": 0, "etype": "delay"}))
        fx = self.room.doc["machines"][0]["effects"][0]
        self.assertEqual(fx["type"], "delay")
        self.assertTrue(self.room.apply({"op": "set_effect_param", "slot": 0,
                                         "index": 0, "param": "wet",
                                         "value": 0.7}))
        self.assertEqual(fx["params"]["wet"], 0.7)
        self.assertTrue(self.room.apply({"op": "set_effect", "slot": 0,
                                         "index": 0, "etype": None}))
        self.assertIsNone(self.room.doc["machines"][0]["effects"][0])


    def test_modular_ops(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "modular"})
        self.assertTrue(self.room.apply({"op": "mod_place", "slot": 0,
                                         "bay": 0, "ctype": "oscillator"}))
        m = self.room.doc["machines"][0]
        self.assertEqual(m["components"][0]["type"], "oscillator")
        self.assertEqual(m["components"][1], "occupied")   # 2-bay component
        # cannot place on occupied bay
        self.assertFalse(self.room.apply({"op": "mod_place", "slot": 0,
                                          "bay": 1, "ctype": "lfo"}))
        self.assertTrue(self.room.apply({"op": "mod_wire", "slot": 0,
                                         "src": "c0.out",
                                         "dst": "panel.left_out"}))
        self.assertTrue(self.room.apply({"op": "mod_remove", "slot": 0, "bay": 0}))
        self.assertIsNone(m["components"][0])
        self.assertEqual(m["wires"], [])

    def test_copy_pattern(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "add_note", "slot": 0, "note": 60, "start": 0,
                         "dur": 1})
        self.assertTrue(self.room.apply({"op": "copy_pattern", "slot": 0,
                                         "src": "A1", "dst": "B3"}))
        m = self.room.doc["machines"][0]
        self.assertEqual(len(m["patterns"]["B3"]["notes"]), 1)


    def test_audio_config_defaults_and_updates(self):
        self.assertEqual(self.room.doc["audio"]["sample_rate"], 44100)
        self.assertEqual(self.room.doc["audio"]["block_size"], 2048)
        self.assertTrue(self.room.apply({
            "op": "set_audio_config", "prop": "sample_rate", "value": 48000,
        }))
        self.assertTrue(self.room.apply({
            "op": "set_audio_config", "prop": "block_size", "value": 1024,
        }))
        self.assertEqual(self.room.doc["audio"]["sample_rate"], 48000)
        self.assertEqual(self.room.doc["audio"]["block_size"], 1024)
        self.assertFalse(self.room.apply({
            "op": "set_audio_config", "prop": "sample_rate", "value": 12345,
        }))

    def test_audio_config_persists_and_normalizes_legacy_snapshot(self):
        self.room.doc["audio"] = {"sample_rate": 96000, "block_size": 4096}
        self.room.save(force=True)
        room2 = state.Room("test-room")
        self.assertEqual(room2.doc["audio"]["sample_rate"], 96000)
        self.assertEqual(room2.doc["audio"]["block_size"], 4096)

        # Simulate an old snapshot without audio settings.
        del room2.doc["audio"]
        room2.save(force=True)
        room3 = state.Room("test-room")
        self.assertEqual(room3.doc["audio"]["sample_rate"], 44100)
        self.assertEqual(room3.doc["audio"]["block_size"], 2048)

    def test_replace_machine_keeps_patterns(self):
        self.room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        self.room.apply({"op": "add_note", "slot": 0, "note": 60, "start": 0,
                         "dur": 1})
        self.room.apply({"op": "replace_machine", "slot": 0, "mtype": "fmsynth"})
        m = self.room.doc["machines"][0]
        self.assertEqual(m["type"], "fmsynth")
        self.assertEqual(len(m["patterns"]["A1"]["notes"]), 1)
        self.assertEqual(m["transpose"], 0)
        self.assertEqual(len(m["transpose_steps"]), 4)


if __name__ == "__main__":
    unittest.main()
