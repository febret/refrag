"""Tests for the native Refrag engine (`refrag_engine`).

The persistent ``RoomEngine`` returned by ``create_room_engine`` is the only
supported render interface, so every case below drives a whole room graph.

Run with:
    python -m unittest discover -s native/tests -v

``refrag_engine`` resolves to the installed extension whenever the project has
been installed, because ``pip install -e .`` registers an import hook that wins
over ``sys.path``; rebuild and reinstall before running to exercise native
changes.  The ``native/build`` entries below are only used as a fallback when
nothing is installed.
"""

import os
import random
import sys
import unittest

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _candidate in (
    os.path.join(_ROOT, "native", "build", "Release"),
    os.path.join(_ROOT, "native", "build"),
):
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)
        break
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import refrag_engine  # noqa: E402

from server import catalog, samples, state  # noqa: E402

SR = 44100
BLOCK = 512
MACHINES = catalog.MACHINE_ORDER


def register_factory_samples(engine):
    for name in samples.factory_names():
        engine.register_sample(name, np.asarray(samples.get(name), dtype=np.float32), samples.SR)


def make_doc(machines=None, master=None, sample_rate=SR, block_size=BLOCK, slots=4):
    doc = state.new_room_doc()
    doc["audio"] = {"sample_rate": sample_rate, "block_size": block_size}
    doc["machines"] = [None] * slots
    for idx, machine in enumerate(machines or []):
        doc["machines"][idx] = machine
    if master:
        doc["master"]["params"].update(master)
    return doc


def new_room(doc, slots=None):
    audio = doc["audio"]
    engine = refrag_engine.create_room_engine(
        audio["sample_rate"], audio["block_size"], slots or len(doc["machines"]))
    register_factory_samples(engine)
    engine.sync(doc)
    return engine


def peak(block):
    return float(np.max(np.abs(block))) if block.size else 0.0


def zero_crossings(signal):
    return int(np.sum(np.abs(np.diff(np.signbit(signal).astype(np.int8)))))


def bitsynth_block(expr_a, expr_b=None, blend=None, frames=BLOCK, blocks=1):
    """Renders a BitSynth room block whose expressions are under test.

    The native bytebeat parser is the only expression implementation left, so
    these helpers exercise compilation, evaluation and rejection through the
    room graph.  ``blocks`` renders repeatedly and returns the last block,
    which lets a caller skip the machine's DC-blocker settling transient.
    """
    machine = state.new_machine("bitsynth")
    machine["expr_a"] = expr_a
    if expr_b is not None:
        machine["expr_b"] = expr_b
    if blend is not None:
        machine["params"]["blend"] = blend
    engine = new_room(make_doc([machine]))
    engine.note_on(0, 60, 1.0)
    out = None
    for _ in range(blocks):
        out = engine.render(frames, 120.0)
    return out


class RoomEngineTests(unittest.TestCase):

    def test_render_shape_and_silence(self):
        engine = new_room(make_doc())
        out = engine.render(BLOCK, 120.0)
        self.assertEqual(out.shape, (2, BLOCK))
        self.assertEqual(out.dtype, np.float32)
        self.assertEqual(peak(out), 0.0)
        self.assertFalse(engine.active())

    def test_note_produces_audio_and_vu(self):
        doc = make_doc([state.new_machine("subsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertGreater(peak(out), 0.01)
        status = engine.status()
        self.assertEqual(len(status["slot_vu"]), len(doc["machines"]))
        self.assertGreater(status["slot_vu"][0], 0.01)
        self.assertEqual(len(status["slot_voice_counts"]), len(doc["machines"]))
        self.assertEqual(status["slot_voice_counts"][0], 1)
        self.assertEqual(status["slot_voice_counts"][1], 0)
        self.assertEqual(len(status["master_vu"]), 2)
        self.assertGreater(max(status["master_vu"]), 0.01)
        self.assertIn("lim_gr", status)
        self.assertIn("has_tail", status)
        self.assertTrue(status["has_tail"])

    def test_slot_voice_counts_track_polyphony(self):
        machine = state.new_machine("padsynth")
        machine["poly"] = 3
        doc = make_doc([machine, state.new_machine("subsynth")])
        engine = new_room(doc)
        self.assertEqual(engine.status()["slot_voice_counts"], [0] * len(doc["machines"]))

        for note in (60, 64, 67, 71, 74):
            engine.note_on(0, note, 1.0)
        counts = engine.status()["slot_voice_counts"]
        self.assertEqual(counts[0], 3)
        self.assertEqual(counts[1], 0)

        engine.note_on(1, 60, 1.0)
        self.assertEqual(engine.status()["slot_voice_counts"][1], 1)

        engine.all_off(0)
        for _ in range(60):
            engine.render(BLOCK, 120.0)
        counts = engine.status()["slot_voice_counts"]
        self.assertEqual(counts[0], 0)
        self.assertEqual(counts[1], 1)

        engine.all_off(1)
        for _ in range(60):
            engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][1], 0)

    def test_slot_voice_counts_reset_when_machine_removed(self):
        doc = make_doc([state.new_machine("padsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)
        doc["machines"][0] = None
        engine.sync(doc)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 0)

    def test_slot_voice_counts_stay_bounded_under_note_spam(self):
        machines = [state.new_machine(mtype) for mtype in MACHINES]
        for machine in machines:
            if machine["type"] == "vocoder":
                machine["modulators"][0]["source"] = "vox_vowels"
        doc = make_doc(machines, slots=len(machines))
        engine = new_room(doc)
        limits = [machine["poly"] for machine in machines]
        for _ in range(8):
            for slot, machine in enumerate(machines):
                for note in range(24, 96, 3):
                    engine.note_on(slot, 0 if machine["type"] == "beatbox" else note, 1.0)
            engine.render(BLOCK, 120.0)
            counts = engine.status()["slot_voice_counts"]
            for slot, machine in enumerate(machines):
                self.assertLessEqual(counts[slot], limits[slot],
                                     f"{machine['type']} exceeded poly limit")

    def test_note_offsets_are_honoured(self):
        doc = make_doc([state.new_machine("subsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0, 256)
        out = engine.render(BLOCK, 120.0)
        self.assertLess(peak(out[:, :250]), 1e-6)
        self.assertGreater(peak(out[:, 256:]), 0.001)

    def test_all_off_releases_one_slot_then_the_rack(self):
        doc = make_doc([state.new_machine("padsynth"), state.new_machine("padsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 64, 1.0)
        engine.render(64, 120.0)
        engine.all_off(0)
        for _ in range(60):
            engine.render(BLOCK, 120.0)
        counts = engine.status()["slot_voice_counts"]
        self.assertEqual(counts[0], 0)
        self.assertEqual(counts[1], 1)
        engine.all_off()
        for _ in range(60):
            engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][1], 0)

    def test_note_off_releases_the_voice(self):
        doc = make_doc([state.new_machine("subsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)
        engine.note_off(0, 60)
        for _ in range(20):
            out = engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 0)
        self.assertLess(peak(out), 1e-3)

    def test_same_pitch_note_off_preserves_newer_held_voice(self):
        machine = state.new_machine("subsynth")
        machine["params"]["vol_release"] = 0.3
        engine = new_room(make_doc([machine]))
        engine.note_on(0, 60, 1.0)
        engine.render(BLOCK, 120.0)
        engine.note_on(0, 60, 1.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 2)
        engine.note_off(0, 60)
        for _ in range(40):
            out = engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)
        self.assertGreater(peak(out), 1e-3)
        engine.note_off(0, 60)
        for _ in range(40):
            out = engine.render(BLOCK, 120.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 0)
        self.assertLess(peak(out), 1e-3)

    def test_cut_note_retrigger_replaces_same_pitch_voice(self):
        machine = state.new_machine("subsynth")
        machine["params"].update({"vol_release": 0.3, "cut_note": 1})
        engine = new_room(make_doc([machine]))
        engine.note_on(0, 60, 1.0)
        engine.render(BLOCK, 120.0)
        engine.note_on(0, 60, 1.0)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)

    def test_sample_rate_changes_playback_pitch(self):
        low = new_room(make_doc([state.new_machine("subsynth")], sample_rate=22050))
        high = new_room(make_doc([state.new_machine("subsynth")], sample_rate=44100))
        self.assertEqual(low.sample_rate, 22050)
        self.assertEqual(high.sample_rate, 44100)
        low.note_on(0, 69, 1.0)
        high.note_on(0, 69, 1.0)
        self.assertGreater(zero_crossings(low.render(2048, 120.0)[0]),
                           zero_crossings(high.render(2048, 120.0)[0]))

    def test_mute_and_solo(self):
        left = state.new_machine("subsynth")
        right = state.new_machine("subsynth")
        doc = make_doc([left, right])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 67, 1.0)
        both = peak(engine.render(BLOCK, 120.0))

        left["mute"] = 1
        engine.sync(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 67, 1.0)
        muted = engine.render(BLOCK, 120.0)
        self.assertGreater(both, 0.0)
        self.assertGreater(peak(muted), 0.0)
        self.assertGreater(engine.status()["slot_vu"][0], 0.0)

        left["mute"] = 0
        right["solo"] = 1
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        solo = engine.render(BLOCK, 120.0)
        self.assertGreater(engine.status()["slot_vu"][0], 0.0)
        self.assertLess(peak(solo), 1e-6)

    def test_mixer_volume_and_pan(self):
        machine = state.new_machine("subsynth")
        machine["mixer"]["pan"] = -1.0
        doc = make_doc([machine])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertGreater(peak(out[0]), peak(out[1]) + 0.01)

        machine["mixer"]["volume"] = 0.0
        engine.sync(doc)
        engine.note_on(0, 60, 1.0)
        self.assertLess(peak(engine.render(BLOCK, 120.0)), 1e-6)

    def test_sends_feed_master_delay(self):
        machine = state.new_machine("subsynth")
        machine["mixer"]["send_delay"] = 1.0
        doc = make_doc([machine], master={"dly_bypass": 1, "dly_wet": 1.0, "dly_time": 0.0,
                                          "dly_sync": 1, "rev_bypass": 0, "lim_bypass": 0,
                                          "volume": 1.0})
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_off(0, 60, 32)
        blocks = [engine.render(BLOCK, 120.0) for _ in range(24)]
        # A quarter-beat echo at 120 BPM lands around block 10.
        tail = np.concatenate(blocks[6:], axis=1)
        self.assertGreater(peak(tail), 1e-3)

    def test_master_reverb_tail(self):
        machine = state.new_machine("subsynth")
        machine["mixer"]["send_reverb"] = 1.0
        doc = make_doc([machine], master={"rev_bypass": 1, "rev_wet": 1.0, "dly_bypass": 0,
                                          "lim_bypass": 0})
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_off(0, 60, 8)
        blocks = [engine.render(BLOCK, 120.0) for _ in range(12)]
        self.assertGreater(peak(np.concatenate(blocks[4:], axis=1)), 1e-5)

    def test_master_limiter_reports_gain_reduction(self):
        machine = state.new_machine("subsynth")
        machine["params"]["volume"] = 2.0
        doc = make_doc([machine], master={"lim_bypass": 1, "lim_pre": 4.0, "volume": 1.5})
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertLessEqual(peak(out), 1.5 + 1e-4)
        self.assertGreater(engine.status()["lim_gr"], 0.0)

    def test_output_is_clipped_and_finite(self):
        doc = make_doc([state.new_machine("subsynth") for _ in range(4)], slots=4)
        for machine in doc["machines"]:
            machine["params"]["volume"] = 2.0
            machine["mixer"]["volume"] = 1.5
        doc["master"]["params"].update({"volume": 1.5, "lim_bypass": 0})
        engine = new_room(doc)
        for slot in range(4):
            engine.note_on(slot, 48 + slot * 5, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertLessEqual(peak(out), 1.5 + 1e-6)

    def test_tail_flag_decays_to_idle(self):
        doc = make_doc([state.new_machine("subsynth")],
                       master={"dly_bypass": 0, "rev_bypass": 0, "lim_bypass": 0})
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.render(BLOCK, 120.0)
        engine.all_off()
        self.assertTrue(engine.active())
        blocks = int(9 * SR / BLOCK)
        for _ in range(blocks):
            engine.render(BLOCK, 120.0)
        self.assertFalse(engine.active())
        self.assertFalse(engine.status()["has_tail"])

    def test_every_effect_runs_in_both_insert_slots(self):
        for etype in catalog.EFFECT_ORDER:
            with self.subTest(effect=etype):
                machine = state.new_machine("subsynth")
                params = catalog.default_params(catalog.EFFECTS[etype]["controls"])
                machine["effects"][0] = {"type": etype, "params": dict(params), "bypass": 0}
                machine["effects"][1] = {"type": etype, "params": dict(params), "bypass": 0}
                doc = make_doc([machine])
                engine = new_room(doc)
                engine.note_on(0, 60, 1.0)
                first = engine.render(BLOCK, 120.0)
                second = engine.render(BLOCK, 120.0)
                self.assertTrue(np.all(np.isfinite(first)), etype)
                self.assertTrue(np.all(np.isfinite(second)), etype)

    def test_master_effects_run(self):
        for etype in catalog.EFFECT_ORDER:
            with self.subTest(effect=etype):
                doc = make_doc([state.new_machine("subsynth")])
                params = catalog.default_params(catalog.EFFECTS[etype]["controls"])
                doc["master"]["effects"][0] = {
                    "type": etype, "params": dict(params), "bypass": 0}
                engine = new_room(doc)
                engine.note_on(0, 60, 1.0)
                out = engine.render(BLOCK, 120.0)
                self.assertTrue(np.all(np.isfinite(out)), etype)

    def test_effect_bypass_is_respected(self):
        machine = state.new_machine("subsynth")
        params = catalog.default_params(catalog.EFFECTS["distortion"]["controls"])
        params.update({"program": 2, "pre": 4.0, "amount": 1.0, "post": 2.0})
        machine["effects"][0] = {"type": "distortion", "params": params, "bypass": 1}
        doc = make_doc([machine])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        bypassed = engine.render(BLOCK, 120.0)

        machine["effects"][0]["bypass"] = 0
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        active = engine.render(BLOCK, 120.0)
        self.assertGreater(peak(active), peak(bypassed))


    def test_vocoder_reads_previous_slot_output(self):
        carrier = state.new_machine("subsynth")
        vocoder = state.new_machine("vocoder")
        vocoder["modulators"][0]["machine"] = 0
        doc = make_doc([carrier, vocoder])
        engine = new_room(doc)
        engine.note_on(0, 48, 1.0)
        engine.note_on(1, 60, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertTrue(np.all(np.isfinite(out)))
        status = engine.status()
        self.assertIn("1", status["vocoder_vu"])
        self.assertEqual(len(status["vocoder_vu"]["1"]), 8)
        self.assertGreater(max(status["vocoder_vu"]["1"]), 0.0)

    def test_vocoder_reads_later_slot_from_previous_block(self):
        vocoder = state.new_machine("vocoder")
        vocoder["modulators"][0]["machine"] = 1
        carrier = state.new_machine("subsynth")
        doc = make_doc([vocoder, carrier])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 48, 1.0)
        engine.render(BLOCK, 120.0)
        engine.render(BLOCK, 120.0)
        self.assertGreater(max(engine.status()["vocoder_vu"]["0"]), 0.0)

    def test_vocoder_previous_output_survives_buffer_growth(self):
        """A direct render that grows the buffers must not leave stale pointers.

        Slot 0 vocodes slot 1, i.e. a later slot, so it falls back to slot 1's
        previous-block audio.  Growing ``frames`` reallocates those buffers.
        """
        vocoder = state.new_machine("vocoder")
        vocoder["modulators"][0]["machine"] = 1
        carrier = state.new_machine("subsynth")
        engine = new_room(make_doc([vocoder, carrier], block_size=256))
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 48, 1.0)
        engine.render(64, 120.0)
        for frames in (8192, 8192, 32768):
            out = engine.render(frames, 120.0)
            self.assertEqual(out.shape, (2, frames))
            self.assertTrue(np.all(np.isfinite(out)))
            status = engine.status()
            bands = status["vocoder_vu"]["0"]
            self.assertEqual(len(bands), 8)
            self.assertTrue(all(np.isfinite(b) for b in bands))
            self.assertTrue(all(np.isfinite(v) for v in status["slot_vu"]))
        self.assertGreater(max(engine.status()["vocoder_vu"]["0"]), 0.0)

    def test_vocoder_previous_output_survives_sync_block_growth(self):
        """Growing block_size through sync() reallocates the same buffers."""
        vocoder = state.new_machine("vocoder")
        vocoder["modulators"][0]["machine"] = 1
        carrier = state.new_machine("subsynth")
        doc = make_doc([vocoder, carrier], block_size=256)
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 48, 1.0)
        engine.render(256, 120.0)
        doc["audio"] = {"sample_rate": SR, "block_size": 4096}
        engine.sync(doc)
        self.assertEqual(engine.block_size, 4096)
        out = engine.render(4096, 120.0)
        self.assertEqual(out.shape, (2, 4096))
        self.assertTrue(np.all(np.isfinite(out)))
        bands = engine.status()["vocoder_vu"]["0"]
        self.assertEqual(len(bands), 8)
        self.assertTrue(all(np.isfinite(b) for b in bands))

    def test_vocoder_previous_output_survives_slot_count_growth(self):
        """Adding slots re-runs buffer allocation; pointers must stay valid."""
        vocoder = state.new_machine("vocoder")
        vocoder["modulators"][0]["machine"] = 1
        carrier = state.new_machine("subsynth")
        doc = make_doc([vocoder, carrier], block_size=256, slots=2)
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.note_on(1, 48, 1.0)
        engine.render(64, 120.0)
        doc["machines"].extend([None] * 6)
        doc["audio"] = {"sample_rate": SR, "block_size": 2048}
        engine.sync(doc)
        out = engine.render(2048, 120.0)
        self.assertEqual(out.shape, (2, 2048))
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertTrue(all(np.isfinite(b) for b in engine.status()["vocoder_vu"]["0"]))

    def test_sync_preserves_voices_for_same_machine_type(self):
        machine = state.new_machine("padsynth")
        doc = make_doc([machine])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.render(64, 120.0)
        machine["params"]["volume"] = 0.5
        engine.sync(doc)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)

    def test_sync_replaces_machine_on_type_change(self):
        doc = make_doc([state.new_machine("padsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.render(64, 120.0)
        doc["machines"][0] = state.new_machine("organ")
        engine.sync(doc)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 0)
        engine.note_on(0, 60, 1.0)
        self.assertGreater(peak(engine.render(BLOCK, 120.0)), 0.001)

    def test_sync_handles_removed_machine(self):
        doc = make_doc([state.new_machine("subsynth")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        engine.render(64, 120.0)
        doc["machines"][0] = None
        engine.sync(doc)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 0)
        self.assertEqual(engine.status()["slot_vu"][0], 0.0)
        engine.note_on(0, 60, 1.0)  # must not raise
        self.assertEqual(peak(engine.render(BLOCK, 120.0)), 0.0)



    def test_sample_registration_round_trip(self):
        machine = state.new_machine("beatbox")
        machine["channels"][0]["sample"] = "click"
        doc = make_doc([machine])
        engine = new_room(doc)
        click = np.zeros(256, dtype=np.float32)
        click[0] = 1.0
        engine.register_sample("click", click, samples.SR)
        engine.note_on(0, 0, 1.0)
        self.assertGreater(peak(engine.render(64, 120.0)), 0.1)
        # Re-registering the same name replaces the buffer used by new notes.
        engine.render(BLOCK, 120.0)
        engine.register_sample("click", np.zeros(256, dtype=np.float32), samples.SR)
        engine.note_on(0, 0, 1.0)
        self.assertEqual(peak(engine.render(64, 120.0)), 0.0)


    def test_pcmsynth_loop_mode_keeps_playing(self):
        machine = state.new_machine("pcmsynth")
        machine["samples"] = [
            {"sample": "loop", "level": 1.0, "tune": 0, "pan": 0.0, "root": 60,
             "low": 0, "high": 127, "mode": 2, "start": 0.0, "end": 1.0},
        ]
        engine = new_room(make_doc([machine]))
        loop = np.sin(np.linspace(0.0, 2.0 * np.pi, 256, endpoint=False)).astype(np.float32)
        engine.register_sample("loop", loop, samples.SR)
        engine.note_on(0, 60, 1.0)
        blocks = [engine.render(BLOCK, 120.0) for _ in range(4)]
        # The zone is only 256 frames long, so audio in the last block proves
        # the loop wrapped instead of running out.
        self.assertGreater(peak(blocks[-1]), 0.05)
        self.assertEqual(engine.status()["slot_voice_counts"][0], 1)

    def test_vocoder_sample_modulator_updates_band_vu(self):
        machine = state.new_machine("vocoder")
        machine["modulators"][0]["source"] = "formant"
        engine = new_room(make_doc([machine]))
        formant = np.sin(np.linspace(0, np.pi * 12, 4096)).astype(np.float32)
        engine.register_sample("formant", formant, samples.SR)
        engine.note_on(0, 48, 1.0)
        engine.render(BLOCK, 120.0)
        bands = engine.status()["vocoder_vu"]["0"]
        self.assertEqual(len(bands), 8)
        self.assertTrue(any(float(v) > 0.001 for v in bands))


    def test_modular_patch(self):
        machine = state.new_machine("modular")
        room = state.Room("native-modular-test")
        room.runtime_only = True
        room.doc = state.new_room_doc()
        room.doc["machines"][0] = machine
        for op in (
            {"op": "mod_place", "slot": 0, "bay": 0, "ctype": "oscillator"},
            {"op": "mod_place", "slot": 0, "bay": 2, "ctype": "envelope"},
            {"op": "mod_place", "slot": 0, "bay": 3, "ctype": "vca"},
            {"op": "mod_wire", "slot": 0, "src": "c0.out", "dst": "c3.in"},
            {"op": "mod_wire", "slot": 0, "src": "c2.out", "dst": "c3.mod"},
            {"op": "mod_wire", "slot": 0, "src": "c3.out", "dst": "panel.left_out"},
        ):
            self.assertTrue(room.apply(op), op)
        engine = new_room(make_doc([machine]))
        engine.note_on(0, 57, 1.0)
        out = engine.render(BLOCK, 120.0)
        self.assertGreater(peak(out), 0.01)
        self.assertTrue(np.all(np.isfinite(out)))

    def test_bitsynth_expression_drives_output(self):
        out = bitsynth_block("t*(42&t>>10)")
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertGreater(peak(out), 0.01)

    def test_bitsynth_operator_grammar_is_accepted(self):
        for expr in ("t*(42&t>>10)", "(t>>4)|(t<<2)", "t*3&(t>>6)^t%255",
                     "~t*2+t/3-t%5", "T*(T>>5|T>>8)", "-t*(t>>7&3)",
                     "t * ( 42 & t >> 10 )"):
            with self.subTest(expr=expr):
                out = bitsynth_block(expr)
                self.assertTrue(np.all(np.isfinite(out)), expr)
                self.assertGreater(peak(out), 0.001, expr)

    def test_bitsynth_expression_values_drive_amplitude(self):
        # Once the DC blocker has settled the steady-state level follows the
        # value range of the expression, so `&` and `*` must really be applied.
        quiet = bitsynth_block("t&1", blocks=8)
        loud = bitsynth_block("(t&1)*255", blocks=8)
        self.assertGreater(peak(loud), 0.2)
        self.assertLess(peak(quiet), peak(loud) * 0.2)

    def test_bitsynth_second_expression_is_compiled(self):
        # blend fully favours expr_b, so only a parsed expr_b can make sound.
        self.assertGreater(peak(bitsynth_block("t +", expr_b="t*(42&t>>10)", blend=1.0)), 0.01)
        self.assertLess(peak(bitsynth_block("t*(42&t>>10)", expr_b="t +", blend=1.0)), 1e-6)

    def test_bitsynth_recompiles_expression_on_sync(self):
        machine = state.new_machine("bitsynth")
        machine["expr_a"] = "t*(42&t>>10)"
        doc = make_doc([machine])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        self.assertGreater(peak(engine.render(BLOCK, 120.0)), 0.01)

        machine["expr_a"] = "t +"  # an invalid edit silences the machine
        engine.sync(doc)
        for _ in range(12):
            after = engine.render(BLOCK, 120.0)
        self.assertLess(peak(after), 1e-6)

        machine["expr_a"] = "t*(t>>9|t>>13)&16"  # a valid edit brings it back
        engine.sync(doc)
        engine.note_on(0, 60, 1.0)
        self.assertGreater(peak(engine.render(BLOCK, 120.0)), 0.01)

    def test_bitsynth_invalid_expression_is_silent(self):
        for expr in ("t +", "__import__('os')", "x*2", "(t*2", "t 2", "t**2", "t/", "&t",
                     "t & & 2", "   "):
            with self.subTest(expr=expr):
                out = bitsynth_block(expr, expr_b=expr, blend=0.5)
                self.assertTrue(np.all(np.isfinite(out)), expr)
                self.assertLess(peak(out), 1e-6, expr)






    def test_variable_block_sizes(self):
        doc = make_doc([state.new_machine("organ")])
        engine = new_room(doc)
        engine.note_on(0, 60, 1.0)
        for frames in (1, 7, 64, 1024, 4096):
            out = engine.render(frames, 120.0)
            self.assertEqual(out.shape, (2, frames))
            self.assertTrue(np.all(np.isfinite(out)))

    def test_sample_rate_change_via_sync(self):
        doc = make_doc([state.new_machine("subsynth")])
        engine = new_room(doc)
        self.assertEqual(engine.sample_rate, SR)
        doc["audio"] = {"sample_rate": 48000, "block_size": 1024}
        engine.sync(doc)
        self.assertEqual(engine.sample_rate, 48000)
        self.assertEqual(engine.block_size, 1024)
        engine.note_on(0, 60, 1.0)
        out = engine.render(1024, 120.0)
        self.assertEqual(out.shape, (2, 1024))
        self.assertGreater(peak(out), 0.001)


    def test_bpm_changes_master_delay_time(self):
        machine = state.new_machine("subsynth")
        machine["mixer"]["send_delay"] = 1.0
        doc = make_doc([machine], master={"dly_bypass": 1, "dly_sync": 1, "dly_time": 0.0,
                                          "dly_wet": 1.0, "rev_bypass": 0, "lim_bypass": 0})

        def first_echo_block(bpm):
            engine = new_room(doc)
            engine.note_on(0, 60, 1.0)
            engine.note_off(0, 60, 32)
            for index in range(40):
                block = engine.render(BLOCK, bpm)
                if index > 2 and peak(block) > 0.05:
                    return index
            return None

        slow = first_echo_block(60.0)
        fast = first_echo_block(240.0)
        self.assertIsNotNone(slow)
        self.assertIsNotNone(fast)
        self.assertGreater(slow, fast)

    def test_room_render_is_deterministic(self):
        doc = make_doc([state.new_machine("kssynth")])
        a = new_room(doc)
        b = new_room(doc)
        a.note_on(0, 60, 1.0)
        b.note_on(0, 60, 1.0)
        np.testing.assert_array_equal(a.render(BLOCK, 120.0), b.render(BLOCK, 120.0))

    def test_full_rack_of_every_machine(self):
        machines = [state.new_machine(mtype) for mtype in MACHINES]
        for machine in machines:
            if machine["type"] == "vocoder":
                machine["modulators"][0]["source"] = "vox_vowels"
        doc = make_doc(machines, slots=len(machines))
        engine = new_room(doc)
        for slot, machine in enumerate(machines):
            engine.note_on(slot, 0 if machine["type"] == "beatbox" else 60, 1.0)
        out = np.concatenate([engine.render(BLOCK, 120.0) for _ in range(4)], axis=1)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertGreater(peak(out), 0.01)


class FuzzTests(unittest.TestCase):
    """Randomized graphs must stay finite, bounded and crash free."""

    @staticmethod
    def _random_params(controls, rng):
        out = {}
        for cid, spec in controls.items():
            if spec["type"] == "select":
                out[cid] = rng.randrange(len(spec["options"]))
            elif spec["type"] == "toggle":
                out[cid] = rng.randrange(2)
            else:
                value = rng.uniform(spec["min"], spec["max"])
                out[cid] = round(value) if spec.get("curve") == "int" else value
        return out



if __name__ == "__main__":
    unittest.main()
