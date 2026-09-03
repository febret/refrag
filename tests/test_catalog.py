"""Tests for the device catalog."""

import unittest

from server import catalog


class CatalogTests(unittest.TestCase):
    def test_all_twelve_machines_present(self):
        expected = {"subsynth", "pcmsynth", "bassline", "beatbox", "padsynth",
                    "bitsynth", "modular", "organ", "vocoder", "fmsynth",
                    "kssynth", "sampler"}
        self.assertEqual(set(catalog.MACHINES.keys()), expected)
        self.assertEqual(set(catalog.MACHINE_ORDER), expected)

    def test_all_sixteen_effects_present(self):
        self.assertEqual(len(catalog.EFFECTS), 16)
        self.assertEqual(set(catalog.EFFECT_ORDER), set(catalog.EFFECTS.keys()))

    def test_control_specs_are_valid(self):
        for mid, spec in catalog.MACHINES.items():
            for cid, c in spec["controls"].items():
                self.assertIn(c["type"], ("knob", "slider", "select", "toggle"),
                              f"{mid}.{cid}")
                if c["type"] in ("knob", "slider"):
                    self.assertLessEqual(c["min"], c["default"], f"{mid}.{cid}")
                    self.assertLessEqual(c["default"], c["max"], f"{mid}.{cid}")
                if c["type"] == "select":
                    self.assertTrue(0 <= c["default"] < len(c["options"]))


    def test_catalog_json_serializable(self):
        import json
        json.dumps(catalog.catalog_json())


if __name__ == "__main__":
    unittest.main()
