"""Tests for the factory starter presets."""

import os
import tempfile
import unittest

import numpy as np

from server import catalog, factory_presets, state, synth
from server.engine import BLOCK


class FactoryPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._orig_preset = state.PRESET_DIR
        cls._orig_session = state.SESSION_DIR
        state.PRESET_DIR = os.path.join(cls.tmp.name, "presets")
        state.SESSION_DIR = os.path.join(cls.tmp.name, "sessions")
        # factory_presets captured PRESET_DIR at import; patch module attr
        factory_presets.PRESET_DIR = state.PRESET_DIR
        cls.written = factory_presets.install()

    @classmethod
    def tearDownClass(cls):
        state.PRESET_DIR = cls._orig_preset
        state.SESSION_DIR = cls._orig_session
        cls.tmp.cleanup()

    def test_every_machine_has_five_to_ten_presets(self):
        for mtype in catalog.MACHINE_ORDER:
            presets = factory_presets.PRESETS.get(mtype, {})
            self.assertGreaterEqual(len(presets), 5, mtype)
            self.assertLessEqual(len(presets), 10, mtype)

    def test_install_writes_files_once(self):
        total = sum(len(p) for p in factory_presets.PRESETS.values())
        self.assertEqual(self.written, total)
        # second run must not overwrite anything
        self.assertEqual(factory_presets.install(), 0)

    def test_preset_params_are_valid_controls(self):
        for mtype, presets in factory_presets.PRESETS.items():
            controls = catalog.MACHINES[mtype]["controls"]
            for name, data in presets.items():
                for pid, val in data.get("params", {}).items():
                    self.assertIn(pid, controls, f"{mtype}/{name}: {pid}")
                    spec = controls[pid]
                    if spec["type"] in ("knob", "slider"):
                        self.assertGreaterEqual(val, spec["min"],
                                                f"{mtype}/{name}: {pid}")
                        self.assertLessEqual(val, spec["max"],
                                             f"{mtype}/{name}: {pid}")
                    elif spec["type"] == "select":
                        self.assertTrue(0 <= val < len(spec["options"]),
                                        f"{mtype}/{name}: {pid}")

    def test_every_preset_loads_and_renders(self):
        room = state.Room("preset-test")
        room.doc = state.new_room_doc()
        for mtype, presets in factory_presets.PRESETS.items():
            room.apply({"op": "add_machine", "slot": 0, "mtype": mtype})
            for name in presets:
                self.assertTrue(room.load_preset(0, name),
                                f"load failed: {mtype}/{name}")
                m = room.doc["machines"][0]
                self.assertEqual(m["preset"], state._safe_name(name))
                eng = synth.create_machine(m)
                note = 0 if mtype == "beatbox" else 48
                eng.note_on(note, 1.0)
                out = np.concatenate(
                    [eng.render(BLOCK, None) for _ in range(3)], axis=1)
                self.assertTrue(np.all(np.isfinite(out)),
                                f"{mtype}/{name} produced NaN/inf")
                self.assertGreater(np.max(np.abs(out)), 1e-4,
                                   f"{mtype}/{name} is silent")

    def test_modular_preset_wires_reference_placed_components(self):
        for name, data in factory_presets.PRESETS["modular"].items():
            comps = data["components"]
            valid_jacks = {"panel.note_cv", "panel.velocity",
                           "panel.mod_wheel", "panel.left_out",
                           "panel.right_out", "panel.volume_mod"}
            for i, c in enumerate(comps):
                if isinstance(c, dict):
                    spec = catalog.MODULAR_COMPONENTS[c["type"]]
                    for j in spec["inputs"] + spec["outputs"]:
                        valid_jacks.add(f"c{i}.{j}")
                    # occupied markers must follow multi-bay components
                    for k in range(1, spec["size"]):
                        self.assertEqual(comps[i + k], "occupied",
                                         f"{name}: bay {i + k}")
            for src, dst in data["wires"]:
                self.assertIn(src, valid_jacks, f"{name}: {src}")
                self.assertIn(dst, valid_jacks, f"{name}: {dst}")

    def test_beatbox_kits_have_eight_channels(self):
        for name, data in factory_presets.PRESETS["beatbox"].items():
            self.assertEqual(len(data["kit"]), 8, name)

    def test_padsynth_harmonics_have_correct_length(self):
        n = catalog.MACHINES["padsynth"]["harmonics"]
        for name, data in factory_presets.PRESETS["padsynth"].items():
            self.assertEqual(len(data["harm1"]), n, name)
            self.assertEqual(len(data["harm2"]), n, name)

    def test_bitsynth_expressions_compile(self):
        for name, data in factory_presets.PRESETS["bitsynth"].items():
            self.assertIsNotNone(synth.compile_expr(data["expr_a"]),
                                 f"{name}: expr_a")
            self.assertIsNotNone(synth.compile_expr(data["expr_b"]),
                                 f"{name}: expr_b")


if __name__ == "__main__":
    unittest.main()
