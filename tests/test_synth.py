"""Tests for the synthesis engine: machines, effects, engine, export."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from server import catalog, state, synth
from server.engine import BLOCK, AudioEngine, render_song


def make_room(name="synth-test"):
    room = state.Room(name)
    room.doc = state.new_room_doc()
    return room


def slot_voices(graph, slot=0):
    """Live voice count for one slot of a native room graph."""
    return graph.status()["slot_voice_counts"][slot]


class MachineGraph:
    """A persistent one-slot native room graph for single-machine tests.

    The mixer strip and master section stay at neutral settings so a rendered
    block is the machine's own output.
    """

    def __init__(self, machine, sample_rate=44100, block_size=BLOCK):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.doc = state.new_room_doc()
        self.doc["machines"] = [machine]
        self.doc["audio"] = {"sample_rate": self.sample_rate,
                             "block_size": self.block_size}
        self.doc["master"]["params"].update({"volume": 1.0, "lim_bypass": 0})
        self.graph = synth.NativeRoomEngine(
            self.sample_rate, self.block_size, 1)
        self.sync()

    def sync(self):
        self.graph.sync(self.doc)

    def note_on(self, note, vel=1.0, offset=0, flags=0):
        self.graph.note_on(0, note, vel, offset, flags)

    def note_off(self, note, offset=0):
        self.graph.note_off(0, note, offset)

    def render(self, frames=None):
        frames = self.block_size if frames is None else frames
        return self.graph.render(frames, self.doc["bpm"])

    def voice_count(self):
        return slot_voices(self.graph)

    def band_vu(self):
        return self.graph.status().get("vocoder_vu", {}).get("0", [])


class MachineRenderTests(unittest.TestCase):
    """Every machine family must produce audible, finite output."""

    def render_machine(self, mtype, note=60, extra=None, blocks=4):
        m = state.new_machine(mtype)
        if extra:
            m.update(extra)
        graph = MachineGraph(m)
        graph.note_on(note, 1.0)
        out = np.concatenate([graph.render() for _ in range(blocks)], axis=1)
        self.assertTrue(np.all(np.isfinite(out)), mtype + " produced NaN/inf")
        return out

    def test_subsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("subsynth"))), 0.01)

    def test_pcmsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("pcmsynth"))), 0.001)

    def test_sampler(self):
        m = state.new_machine("sampler")
        m["patterns"]["A1"] = state.new_pattern("sampler")
        m["patterns"]["A1"]["sampler"]["sample"] = "kick"
        graph = MachineGraph(m)
        graph.note_on(0, 1.0)
        out = graph.render()
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertGreater(np.max(np.abs(out)), 0.001)

    def test_bassline(self):
        self.assertGreater(np.max(np.abs(self.render_machine("bassline", 40))), 0.01)

    def test_beatbox(self):
        out = self.render_machine("beatbox", note=0, blocks=1)
        self.assertGreater(np.max(np.abs(out)), 0.01)

    def test_beatbox_uses_assigned_sample_buffer(self):
        m = state.new_machine("beatbox")
        m["channels"][0]["sample"] = "impulse"
        m["channels"][0]["params"].update({
            "tune": 0,
            "punch": 0.0,
            "decay": 1.0,
            "pan": 0.0,
            "volume": 1.0,
        })
        impulse = np.concatenate([[1.0], np.zeros(255, dtype=np.float32)]).astype(np.float32)
        orig_get = synth.samples.get
        with mock.patch("server.synth.samples.get",
                        side_effect=lambda name: impulse if name == "impulse"
                        else orig_get(name)):
            graph = MachineGraph(m, block_size=16)
            graph.note_on(0, 1.0)
            out = graph.render(16)
        self.assertGreater(out[0, 0], 0.45)
        self.assertAlmostEqual(float(out[0, 0]), float(out[1, 0]), places=6)

    def test_sampler_referenced_samples_are_registered(self):
        m = state.new_machine("sampler")
        m["patterns"]["A1"] = state.new_pattern("sampler")
        m["patterns"]["A1"]["sampler"]["sample"] = "kick"
        self.assertEqual(synth._sample_names(m), {"kick"})

    def test_padsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("padsynth"))), 0.01)

    def test_bitsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("bitsynth"))), 0.01)

    def test_organ(self):
        self.assertGreater(np.max(np.abs(self.render_machine("organ"))), 0.01)

    def test_fmsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("fmsynth"))), 0.01)

    def test_kssynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("kssynth"))), 0.005)


    def test_vocoder_with_sample_modulator(self):
        m = state.new_machine("vocoder")
        m["modulators"][0]["source"] = "vox_vowels"
        graph = MachineGraph(m)
        graph.note_on(48, 1.0)
        out = np.concatenate([graph.render() for _ in range(4)], axis=1)
        self.assertGreater(np.max(np.abs(out)), 0.001)






    def test_pcmsynth_selects_zone_by_note_range(self):
        m = state.new_machine("pcmsynth")
        m["samples"] = [
            {"sample": "low", "level": 1.0, "tune": 0, "pan": 0.0,
             "root": 60, "low": 0, "high": 63, "mode": 0,
             "start": 0.0, "end": 1.0},
            {"sample": "high", "level": 1.0, "tune": 0, "pan": 0.0,
             "root": 72, "low": 64, "high": 127, "mode": 0,
             "start": 0.0, "end": 1.0},
        ]
        sample_map = {
            "low": np.ones(512, dtype=np.float32),
            "high": -np.ones(512, dtype=np.float32),
        }
        orig_get = synth.samples.get
        with mock.patch("server.synth.samples.get",
                        side_effect=lambda name: sample_map.get(
                            name, orig_get(name))):
            # A fresh graph per zone keeps each note on its own clean engine.
            low = MachineGraph(m, block_size=16)
            low.note_on(48, 1.0)
            out_low = low.render(16)
            high = MachineGraph(m, block_size=16)
            high.note_on(84, 1.0)
            out_high = high.render(16)
        self.assertGreater(float(np.mean(out_low)), 0.05)
        self.assertLess(float(np.mean(out_high)), -0.05)


class EffectTests(unittest.TestCase):
    """All 16 insert effects must process cleanly wherever they can be placed."""

    def _effect_slot(self, etype):
        return {
            "type": etype,
            "bypass": 0,
            "params": catalog.default_params(catalog.EFFECTS[etype]["controls"]),
        }



    def test_master_insert_effect_audibly_alters_the_mix(self):
        def render_with_master_effect(etype):
            room = make_room("master-alter")
            room.doc["machines"][0] = state.new_machine("subsynth")
            if etype:
                room.apply({
                    "op": "set_effect", "target": "master", "index": 0,
                    "etype": etype,
                })
            engine = AudioEngine(room)
            engine.handle_note(0, 60, True, 1.0)
            return engine.render_block()

        plain = render_with_master_effect(None)
        distorted = render_with_master_effect("distortion")
        self.assertTrue(np.all(np.isfinite(distorted)))
        self.assertFalse(np.allclose(plain, distorted))


class MixerAndMasterTests(unittest.TestCase):
    """Per-channel mute/solo/pan/volume/sends and the master bus (inserts,
    limiter, meters) all live in the native room graph now; exercise them
    through AudioEngine/room ops rather than asserting exact sample values."""

    def _single_machine_room(self, name="mixer-test", mtype="subsynth"):
        room = make_room(name)
        room.doc["machines"][0] = state.new_machine(mtype)
        return room

    def test_pan_hard_left_silences_right_channel(self):
        room = self._single_machine_room()
        room.apply({"op": "set_mixer", "slot": 0, "param": "pan", "value": -1.0})
        eng = AudioEngine(room)
        eng.handle_note(0, 60, True, 1.0)
        out = eng.render_block()
        self.assertGreater(np.max(np.abs(out[0])), 0.01)
        self.assertLess(np.max(np.abs(out[1])), 1e-4)


    def test_mixer_volume_scales_peak_amplitude(self):
        def peak_at(volume):
            room = self._single_machine_room()
            room.apply({"op": "set_mixer", "slot": 0, "param": "volume",
                        "value": volume})
            eng = AudioEngine(room)
            eng.handle_note(0, 60, True, 1.0)
            return float(np.max(np.abs(eng.render_block())))

        loud = peak_at(1.0)
        quiet = peak_at(0.1)
        self.assertGreater(loud, 0.01)
        self.assertLess(quiet, loud * 0.3)

    def test_solo_silences_unsoloed_machines_same_as_muting_them(self):
        def render(mute_slot0, solo_slot1):
            room = make_room("solo-test")
            room.doc["machines"][0] = state.new_machine("subsynth")
            room.doc["machines"][1] = state.new_machine("subsynth")
            if mute_slot0:
                room.apply({"op": "set_mixer", "slot": 0, "param": "mute",
                            "value": 1})
            if solo_slot1:
                room.apply({"op": "set_mixer", "slot": 1, "param": "solo",
                            "value": 1})
            eng = AudioEngine(room)
            eng.handle_note(0, 60, True, 1.0)
            eng.handle_note(1, 67, True, 1.0)
            return eng.render_block()

        muted = render(mute_slot0=True, solo_slot1=False)
        soloed = render(mute_slot0=False, solo_slot1=True)
        self.assertGreater(np.max(np.abs(soloed)), 0.01)
        np.testing.assert_allclose(muted, soloed, atol=1e-6)

    def test_send_reverb_amount_changes_master_mix(self):
        def render_with_send(amount):
            room = self._single_machine_room()
            room.apply({"op": "set_mixer", "slot": 0, "param": "send_reverb",
                        "value": amount})
            eng = AudioEngine(room)
            eng.handle_note(0, 60, True, 1.0)
            eng.render_block()
            return eng.render_block()

        dry = render_with_send(0.0)
        wet = render_with_send(1.0)
        self.assertTrue(np.all(np.isfinite(wet)))
        self.assertFalse(np.allclose(dry, wet))



    def test_disabling_master_limiter_stops_reporting_gain_reduction(self):
        room = self._single_machine_room()
        room.apply({"op": "set_master", "param": "lim_pre", "value": 4.0})
        room.apply({"op": "set_master", "param": "lim_bypass", "value": 0})
        eng = AudioEngine(room)
        eng.handle_note(0, 60, True, 1.0)
        for _ in range(8):
            eng.render_block()
        self.assertEqual(eng.status()["lim_gr"], 0.0)

    def test_master_volume_scales_final_output(self):
        def peak_at(volume):
            room = self._single_machine_room()
            room.apply({"op": "set_master", "param": "volume", "value": volume})
            eng = AudioEngine(room)
            eng.handle_note(0, 60, True, 1.0)
            return float(np.max(np.abs(eng.render_block())))

        loud = peak_at(1.2)
        quiet = peak_at(0.1)
        self.assertGreater(loud, 0.01)
        self.assertLess(quiet, loud * 0.3)




class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = state.SESSION_DIR
        state.SESSION_DIR = self.tmp.name

    def tearDown(self):
        state.SESSION_DIR = self._orig
        self.tmp.cleanup()

    def _room_with_song(self):
        room = state.Room("engine-test")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
        room.apply({"op": "add_note", "slot": 0, "note": 60, "start": 0,
                    "dur": 1, "vel": 1})
        room.apply({"op": "add_note", "slot": 0, "note": 64, "start": 2,
                    "dur": 1, "vel": 1})
        room.apply({"op": "song_add", "machine": 0, "bank": 0, "pattern": 0,
                    "start": 0, "length": 2})
        return room

    def test_pattern_playback_produces_audio(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        out = np.concatenate([eng.render_block() for _ in range(8)], axis=1)
        self.assertGreater(np.max(np.abs(out)), 0.01)
        self.assertGreater(eng.position(), 0)

    def test_sampler_pattern_compiles_to_one_full_span_trigger(self):
        room = state.Room("sampler-events")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "sampler"})
        room.apply({
            "op": "set_sampler_param", "slot": 0, "key": "B3",
            "param": "sample", "value": "kick",
        })
        room.apply({
            "op": "set_pattern_length", "slot": 0, "key": "B3", "length": 2,
        })
        room.apply({"op": "select_pattern", "slot": 0, "bank": 1, "pattern": 2})
        eng = AudioEngine(room)
        events = eng._pattern_events(0, room.machine(0), 0.0, 0.2, room.doc)
        self.assertEqual(events, [
            (0.0, "on", 18, 1.0, 0),
            (8.0, "off", 18, 0, 0),
        ])
        self.assertNotIn("transpose_step", eng.status()["looper"]["0"])

    def test_sampler_random_looper_uses_assigned_samples(self):
        room = state.Room("sampler-random")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "sampler"})
        room.apply({
            "op": "set_sampler_param", "slot": 0, "key": "C7",
            "param": "sample", "value": "kick",
        })
        room.apply({"op": "looper_set_bank", "slot": 0, "bank": 2})
        eng = AudioEngine(room)
        self.assertEqual(eng._random_pattern_for_slot(room.machine(0)), (2, 6))

    def test_sampler_song_block_uses_pattern_slot_trigger(self):
        room = state.Room("sampler-song")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "sampler"})
        room.apply({
            "op": "set_sampler_param", "slot": 0, "key": "D16",
            "param": "sample", "value": "kick",
        })
        room.apply({
            "op": "song_add", "machine": 0, "bank": 3, "pattern": 15,
            "start": 2, "length": 1,
        })
        room.doc["transport"]["mode"] = "song"
        eng = AudioEngine(room)
        events = eng._pattern_events(0, room.machine(0), 8.0, 8.2, room.doc)
        self.assertTrue(any(
            event[1] == "on" and event[2] == 63 and event[0] == 8.0
            for event in events))

    def test_looper_queues_and_launches_at_pattern_boundary(self):
        room = self._room_with_song()
        room.apply({"op": "add_note", "slot": 0, "key": "B1",
                    "note": 67, "start": 0, "dur": 1})
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        rev_before_queue = room.rev
        self.assertTrue(room.apply({
            "op": "looper_pattern", "slot": 0, "bank": 1, "pattern": 0,
        }))
        self.assertEqual(room.rev, rev_before_queue)
        self.assertEqual(
            (room.machine(0)["bank"], room.machine(0)["pattern"]), (0, 0))
        queued = eng.status()["looper"]["0"]
        self.assertEqual((queued["queued_bank"], queued["queued_pattern"]), (1, 0))
        self.assertEqual(queued["queue"], [{"bank": 1, "pattern": 0}])

        events = eng._pattern_events(
            0, room.machine(0), 3.99, 4.1, room.doc)
        onsets = [event for event in events if event[1] == "on"]
        self.assertTrue(any(
            event[2] == 67 and abs(event[0] - 4.0) < 1e-9
            for event in onsets))
        self.assertEqual(
            (room.machine(0)["bank"], room.machine(0)["pattern"]), (1, 0))
        self.assertNotIn("queued_bank", eng.status()["looper"]["0"])

    def test_looper_queue_appends_and_keeps_duplicates(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 1, "pattern": 0})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 2, "pattern": 3})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 2, "pattern": 3})
        queued = eng.status()["looper"]["0"]
        self.assertEqual(queued["queue"], [
            {"bank": 1, "pattern": 0},
            {"bank": 2, "pattern": 3},
            {"bank": 2, "pattern": 3},
        ])



    def test_looper_random_mode_uses_non_empty_patterns_in_browsed_bank(self):
        room = self._room_with_song()
        room.apply({"op": "add_note", "slot": 0, "key": "B3",
                    "note": 72, "start": 0, "dur": 1, "vel": 1})
        room.apply({"op": "looper_set_bank", "slot": 0, "bank": 1})
        room.apply({"op": "looper_set_mode", "slot": 0, "mode": "random"})
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        eng._pattern_events(0, room.machine(0), 3.99, 4.1, room.doc)
        live = eng.status()["looper"]["0"]
        self.assertEqual(live["mode"], "random")
        self.assertEqual(live["looper_bank"], 1)
        self.assertEqual(live["bank"], 1)
        self.assertEqual(live["pattern"], 2)

    def test_looper_stop_clears_queue(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 1, "pattern": 0})
        room.apply({"op": "transport", "playing": False})
        self.assertNotIn("queued_bank", eng.status()["looper"]["0"])

    def test_looper_from_song_mode_launches_immediately(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "song"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 3, "pattern": 5})
        self.assertEqual(room.doc["transport"]["mode"], "pattern")
        self.assertEqual(
            (room.machine(0)["bank"], room.machine(0)["pattern"]), (3, 5))
        live = eng.status()["looper"]["0"]
        self.assertEqual((live["bank"], live["pattern"]), (3, 5))
        self.assertNotIn("queued_bank", live)

    def test_looper_pattern_lengths_are_independent(self):
        room = self._room_with_song()
        room.apply({"op": "add_machine", "slot": 1, "mtype": "subsynth"})
        room.apply({"op": "set_pattern_length", "slot": 1,
                    "key": "A1", "length": 2})
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 1, "pattern": 0})
        room.apply({"op": "looper_pattern", "slot": 1,
                    "bank": 1, "pattern": 0})
        eng._pattern_events(0, room.machine(0), 3.99, 4.1, room.doc)
        self.assertEqual(room.machine(0)["bank"], 1)
        self.assertEqual(room.machine(1)["bank"], 0)
        self.assertEqual(eng.status()["looper"]["1"]["queued_bank"], 1)

    def test_live_transpose_changes_melodic_events_and_clamps_notes(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "set_transpose", "slot": 0, "value": 12})
        events = eng._pattern_events(0, room.machine(0), 0, 0.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 72
                            for event in events))
        room.machine(0)["patterns"]["A1"]["notes"][0][0] = 127
        room.mark_changed()
        events = eng._pattern_events(0, room.machine(0), 0, 0.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 127
                            for event in events))

    def test_transpose_sequencer_advances_per_pattern_boundary(self):
        room = self._room_with_song()
        room.apply({"op": "set_transpose_step", "slot": 0, "step": 0,
                    "transpose": 0, "loops": 1})
        room.apply({"op": "set_transpose_step", "slot": 0, "step": 1,
                    "transpose": 12, "loops": 2})
        room.apply({"op": "set_transpose_step", "slot": 0, "step": 2,
                    "transpose": -12, "loops": 1})
        room.apply({"op": "set_transpose_step", "slot": 0, "step": 3,
                    "transpose": 7, "loops": 1})
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})

        first = eng._pattern_events(0, room.machine(0), 0.0, 0.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 60 for event in first))
        self.assertEqual(eng.status()["looper"]["0"]["transpose_step"], 0)

        eng._pattern_events(0, room.machine(0), 3.99, 4.1, room.doc)
        second = eng._pattern_events(0, room.machine(0), 4.0, 4.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 72 for event in second))
        self.assertEqual(eng.status()["looper"]["0"]["transpose_step"], 1)

        eng._pattern_events(0, room.machine(0), 7.99, 8.1, room.doc)
        self.assertEqual(eng.status()["looper"]["0"]["transpose_step"], 1)
        eng._pattern_events(0, room.machine(0), 11.99, 12.1, room.doc)
        third = eng._pattern_events(0, room.machine(0), 12.0, 12.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 48 for event in third))
        self.assertEqual(eng.status()["looper"]["0"]["transpose_step"], 2)


    def test_song_playback_produces_audio(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "song"})
        out = np.concatenate([eng.render_block() for _ in range(8)], axis=1)
        self.assertGreater(np.max(np.abs(out)), 0.01)


    def test_audio_engine_honors_non_default_sample_rate_and_block_size(self):
        room = self._room_with_song()
        room.doc["audio"]["sample_rate"] = 22050
        room.doc["audio"]["block_size"] = 512
        eng = AudioEngine(room)
        self.assertEqual(eng.sample_rate, 22050)
        self.assertEqual(eng.block_size, 512)
        self.assertEqual(eng.status()["audio"],
                         {"sample_rate": 22050, "block_size": 512})
        native = eng.graph.status()
        self.assertEqual(native["sample_rate"], 22050)
        self.assertEqual(native["block_size"], 512)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        out = eng.render_block()
        self.assertEqual(out.shape, (2, 512))
        self.assertTrue(np.all(np.isfinite(out)))

    def test_render_block_calls_native_room_graph_once(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        with mock.patch.object(
                eng.graph, "render", wraps=eng.graph.render) as native_render:
            out = eng.render_block()
        self.assertEqual(out.shape, (2, BLOCK))
        native_render.assert_called_once_with(BLOCK, room.doc["bpm"])

    def test_runtime_audio_config_changes_apply_on_next_block(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        self.assertEqual(eng.render_block().shape[1], 2048)
        room.apply({"op": "set_audio_config", "prop": "block_size", "value": 1024})
        self.assertEqual(eng.render_block().shape[1], 1024)

    def test_loop_wraps(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "song",
                    "loop": [0, 1]})
        for _ in range(200):
            eng.render_block()
        self.assertLess(eng.position(), 4.5)

    def test_pattern_event_cache_invalidates_after_edit(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        m = room.machine(0)
        before = eng._pattern_events(0, m, 0.0, 0.2, room.doc)
        self.assertTrue(any(event[2] == 60 for event in before))

        self.assertTrue(room.apply({
            "op": "update_note", "slot": 0, "index": 0, "note": 67,
        }))
        after = eng._pattern_events(0, m, 0.0, 0.2, room.doc)
        self.assertTrue(any(event[2] == 67 for event in after))
        self.assertFalse(any(event[2] == 60 for event in after))


    def test_song_event_cache_invalidates_after_edit(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.doc["transport"]["mode"] = "song"
        m = room.machine(0)
        before = eng._pattern_events(0, m, 0.0, 0.2, room.doc)
        self.assertTrue(any(event[2] == 60 for event in before))

        self.assertTrue(room.apply({
            "op": "update_note", "slot": 0, "index": 0, "note": 67,
        }))
        after = eng._pattern_events(0, m, 0.0, 0.2, room.doc)
        self.assertTrue(any(event[2] == 67 for event in after))
        self.assertFalse(any(event[2] == 60 for event in after))

    def test_live_note_waits_for_render_lock(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        finished = threading.Event()

        room.lock.acquire()
        worker = threading.Thread(
            target=lambda: (
                eng.handle_note(0, 72, True, 1.0),
                finished.set(),
            ))
        worker.start()
        try:
            time.sleep(0.02)
            self.assertFalse(finished.is_set())
        finally:
            room.lock.release()
            worker.join(timeout=1)
        self.assertTrue(finished.is_set())
        self.assertGreater(slot_voices(eng.graph), 0)

    def test_effect_tail_keeps_engine_active_after_voice_ends(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        eng.handle_note(0, 72, True, 1.0)
        eng.render_block()
        eng.handle_note(0, 72, False)
        for _ in range(100):
            eng.render_block()
            if slot_voices(eng.graph) == 0:
                break
        self.assertEqual(slot_voices(eng.graph), 0)
        self.assertGreater(eng._tail_blocks, 0)
        self.assertFalse(eng.is_idle())


    def test_is_idle_false_while_transport_is_playing(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        eng.render_block()
        self.assertFalse(eng.is_idle())

    def test_is_idle_becomes_true_once_tail_decays(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        eng.handle_note(0, 72, True, 1.0)
        eng.render_block()
        eng.handle_note(0, 72, False)
        for _ in range(400):
            if eng.is_idle():
                break
            eng.render_block()
        self.assertTrue(eng.is_idle())

    def test_sustained_pattern_runtime_state_stays_bounded(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        max_voices = 0
        max_offs = 0
        for _ in range(600):
            eng.render_block()
            max_voices = max(
                max_voices,
                sum(eng.graph.status().get("slot_voice_counts", [])))
            max_offs = max(max_offs, sum(
                len(slot.active_offs) for slot in eng.slots))
        self.assertLessEqual(max_voices, room.machine(0)["poly"])
        self.assertLessEqual(max_offs, 2)


    def test_reassigned_beatbox_sample_takes_effect_through_full_engine(self):
        room = make_room("sample-swap")
        room.doc["machines"][0] = state.new_machine("beatbox")
        first = np.ones(512, dtype=np.float32)
        second = -np.ones(512, dtype=np.float32) * 0.5
        sample_map = {"one": first, "two": second}
        orig_get = synth.samples.get
        with mock.patch("server.synth.samples.get",
                        side_effect=lambda name: sample_map.get(
                            name, orig_get(name))):
            room.doc["machines"][0]["channels"][0]["sample"] = "one"
            eng = AudioEngine(room)
            eng.handle_note(0, 0, True, 1.0)
            out_before = eng.render_block()

            room.apply({"op": "set_channel_param", "slot": 0, "channel": 0,
                        "param": "sample", "value": "two"})
            eng.handle_note(0, 0, True, 1.0)
            out_after = eng.render_block()

        self.assertTrue(np.all(np.isfinite(out_before)))
        self.assertTrue(np.all(np.isfinite(out_after)))
        self.assertFalse(np.allclose(out_before, out_after))

    def test_live_note_recording(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "record": True,
                    "mode": "pattern"})
        eng.render_block()
        eng.handle_note(0, 72, True, 1.0)
        eng.render_block()
        eng.handle_note(0, 72, False)
        pat = room.doc["machines"][0]["patterns"]["A1"]
        self.assertTrue(any(n[0] == 72 for n in pat["notes"]))

    def test_automation_record_and_playback(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "record": True,
                    "mode": "pattern"})
        eng.render_block()
        room.apply({"op": "set_param", "slot": 0, "param": "flt_cutoff",
                    "value": 0.25})
        key = "0:A1:flt_cutoff"
        self.assertIn(key, room.doc["automation"]["pattern"])
        room.apply({"op": "transport", "record": False})
        eng.render_block()
        self.assertIn((0, "flt_cutoff"),
                      {k: v for k, v in eng.auto_values.items()})

    def test_automation_does_not_deepcopy_room_document(self):
        room = self._room_with_song()
        room.doc["automation"]["song"]["0:mixer.volume"] = {
            "keys": [[0.0, 0.5], [4.0, 1.0]],
        }
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "song"})
        with mock.patch("server.engine.copy.deepcopy",
                        side_effect=AssertionError("deepcopy in render path")):
            out = eng.render_block()
        self.assertEqual(out.shape, (2, BLOCK))

    def test_export_song(self):
        room = self._room_with_song()
        audio = render_song(room)
        self.assertEqual(audio.shape[0], 2)
        # 2 measures at 120bpm = 4s + 2s tail
        self.assertGreater(audio.shape[1], 5 * 44100)
        self.assertGreater(np.max(np.abs(audio)), 0.01)
        self.assertFalse(room.doc["transport"]["playing"])

    def test_export_song_uses_configured_sample_rate(self):
        room = self._room_with_song()
        room.doc["audio"]["sample_rate"] = 22050
        audio = render_song(room)
        self.assertGreater(audio.shape[1], 5 * 22050)


class SampleTests(unittest.TestCase):
    def test_replaced_sample_is_registered_again(self):
        doc = state.new_room_doc()
        machine = state.new_machine("beatbox")
        for channel in machine["channels"]:
            channel["sample"] = ""
        machine["channels"][0]["sample"] = "replaceable"
        doc["machines"][0] = machine
        first = np.ones(64, dtype=np.float32)
        second = -np.ones(64, dtype=np.float32)
        native = mock.Mock()
        with mock.patch.object(
                synth._native, "create_room_engine", return_value=native):
            graph = synth.NativeRoomEngine(44100, BLOCK, len(doc["machines"]))
            with mock.patch(
                    "server.synth.samples.get", return_value=first):
                graph.sync(doc)
            with mock.patch(
                    "server.synth.samples.get", return_value=second):
                graph.sync(doc)
        self.assertEqual(native.register_sample.call_count, 2)
        np.testing.assert_array_equal(
            native.register_sample.call_args.args[1], second)


    def test_wav_roundtrip(self):
        import io
        from server import samples
        buf = io.BytesIO()
        samples.write_wav(buf, np.sin(np.linspace(0, 100, 4410)))
        x = samples.load_wav_bytes(buf.getvalue())
        self.assertGreater(len(x), 4000)


    def test_user_sample_never_shadows_factory(self):
        import io
        import tempfile
        from server import samples
        buf = io.BytesIO()
        samples.write_wav(buf, np.sin(np.linspace(0, 100, 4410)))
        with tempfile.TemporaryDirectory() as tmp:
            orig = samples.SAMPLE_DIR
            samples.SAMPLE_DIR = tmp
            try:
                name = samples.save_user_sample("kick", buf.getvalue())
                self.assertNotIn(name, samples.FACTORY)
                self.assertTrue(name.startswith("kick"))
            finally:
                samples.SAMPLE_DIR = orig



if __name__ == "__main__":
    unittest.main()
