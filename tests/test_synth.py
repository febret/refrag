"""Tests for the synthesis engine: machines, effects, engine, export."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from server import catalog, dsp, effects, state, synth
from server.engine import BLOCK, AudioEngine, render_song


def make_room(name="synth-test"):
    room = state.Room(name)
    room.doc = state.new_room_doc()
    return room


class MachineRenderTests(unittest.TestCase):
    """Every machine family must produce audible, finite output."""

    def render_machine(self, mtype, note=60, extra=None, blocks=4):
        m = state.new_machine(mtype)
        if extra:
            m.update(extra)
        eng = synth.create_machine(m)
        eng.note_on(note, 1.0)
        out = np.concatenate([eng.render(BLOCK, None) for _ in range(blocks)],
                             axis=1)
        self.assertTrue(np.all(np.isfinite(out)), mtype + " produced NaN/inf")
        return out

    def test_subsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("subsynth"))), 0.01)

    def test_pcmsynth(self):
        self.assertGreater(np.max(np.abs(self.render_machine("pcmsynth"))), 0.001)

    def test_bassline(self):
        self.assertGreater(np.max(np.abs(self.render_machine("bassline", 40))), 0.01)

    def test_beatbox(self):
        out = self.render_machine("beatbox", note=0, blocks=1)
        self.assertGreater(np.max(np.abs(out)), 0.01)

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

    def test_modular_patch(self):
        m = state.new_machine("modular")
        room = make_room()
        room.doc["machines"][0] = m
        for op in [
            {"op": "mod_place", "slot": 0, "bay": 0, "ctype": "oscillator"},
            {"op": "mod_place", "slot": 0, "bay": 2, "ctype": "envelope"},
            {"op": "mod_place", "slot": 0, "bay": 3, "ctype": "vca"},
            {"op": "mod_wire", "slot": 0, "src": "c0.out", "dst": "c3.in"},
            {"op": "mod_wire", "slot": 0, "src": "c2.out", "dst": "c3.mod"},
            {"op": "mod_wire", "slot": 0, "src": "c3.out", "dst": "panel.left_out"},
        ]:
            self.assertTrue(room.apply(op), op)
        eng = synth.create_machine(m)
        eng.note_on(57, 1.0)
        out = eng.render(BLOCK, None)
        self.assertGreater(np.max(np.abs(out)), 0.01)

    def test_vocoder_with_sample_modulator(self):
        m = state.new_machine("vocoder")
        m["modulators"][0]["source"] = "vox_vowels"
        eng = synth.create_machine(m)
        eng.note_on(48, 1.0)
        out = np.concatenate([eng.render(BLOCK, None) for _ in range(4)], axis=1)
        self.assertGreater(np.max(np.abs(out)), 0.001)

    def test_note_off_silences_voice(self):
        m = state.new_machine("subsynth")
        eng = synth.create_machine(m)
        eng.note_on(60, 1.0)
        eng.render(BLOCK, None)
        eng.note_off(60)
        for _ in range(40):
            out = eng.render(BLOCK, None)
        self.assertLess(np.max(np.abs(out)), 1e-3)

    def test_polyphony_limit(self):
        m = state.new_machine("subsynth")
        m["poly"] = 2
        eng = synth.create_machine(m)
        for n in (60, 64, 67, 71):
            eng.note_on(n, 1.0)
        live = [v for v in eng.voices if not v.dead]
        self.assertLessEqual(len(live), 2)


class ExpressionTests(unittest.TestCase):
    def test_valid_expression(self):
        fn = synth.compile_expr("t*(42&t>>10)")
        out = fn(np.arange(64, dtype=np.int64))
        self.assertEqual(out.shape, (64,))

    def test_invalid_expression_returns_none(self):
        self.assertIsNone(synth.compile_expr("__import__('os')"))
        self.assertIsNone(synth.compile_expr("t +"))

    def test_division_by_zero_safe(self):
        fn = synth.compile_expr("t/(t%2)")
        out = fn(np.arange(8, dtype=np.int64))
        self.assertTrue(np.all(np.isfinite(out.astype(float))))


class EffectTests(unittest.TestCase):
    def test_every_effect_processes(self):
        rng = np.random.default_rng(1)
        x = rng.uniform(-0.5, 0.5, (2, BLOCK))
        ctx = {"bpm": 120.0, "lines": {}}
        for etype in catalog.EFFECT_ORDER:
            fx = effects.create_effect(etype)
            params = catalog.default_params(catalog.EFFECTS[etype]["controls"])
            y = fx.process(x.copy(), params, ctx)
            self.assertEqual(y.shape, x.shape, etype)
            self.assertTrue(np.all(np.isfinite(y)), etype)
            # run a second block to exercise state
            y2 = fx.process(x.copy(), params, ctx)
            self.assertTrue(np.all(np.isfinite(y2)), etype)

    def test_unchanged_biquad_coefficients_are_reused(self):
        bq = dsp.Biquad()
        with mock.patch("server.dsp.biquad_coeffs",
                        wraps=dsp.biquad_coeffs) as coeffs:
            bq.set("lp", 1200.0, 0.7)
            bq.set("lp", 1200.0, 0.7)
            self.assertEqual(coeffs.call_count, 1)
            bq.set("lp", 1400.0, 0.7)
            self.assertEqual(coeffs.call_count, 2)

    def test_constant_tv_filter_matches_scalar_path(self):
        rng = np.random.default_rng(9)
        x = rng.uniform(-0.5, 0.5, BLOCK)
        scalar = dsp.TVFilter().process(x, "lp", 1500.0, 0.8)
        array = dsp.TVFilter().process(
            x, "lp", np.full(BLOCK, 1500.0), 0.8)
        np.testing.assert_array_equal(array, scalar)


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

    def test_looper_clear_queue_operation(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 1, "pattern": 0})
        self.assertTrue(room.apply({"op": "looper_clear_queue", "slot": 0}))
        self.assertNotIn("queued_bank", eng.status()["looper"]["0"])
        self.assertFalse(room.apply({"op": "looper_clear_queue", "slot": 0}))

    def test_looper_queue_can_repeat_live_pattern(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 0, "pattern": 0})
        room.apply({"op": "looper_pattern", "slot": 0,
                    "bank": 0, "pattern": 0})
        self.assertEqual(len(eng.status()["looper"]["0"]["queue"]), 2)
        eng._pattern_events(0, room.machine(0), 3.99, 4.1, room.doc)
        self.assertEqual(len(eng.status()["looper"]["0"]["queue"]), 1)
        eng._pattern_events(0, room.machine(0), 7.99, 8.1, room.doc)
        self.assertNotIn("queued_bank", eng.status()["looper"]["0"])

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

    def test_live_transpose_does_not_change_beatbox_mapping(self):
        room = state.Room("beatbox-looper")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "beatbox"})
        room.apply({"op": "add_note", "slot": 0, "note": 3,
                    "start": 0, "dur": 0.25})
        room.machine(0)["transpose"] = 12
        eng = AudioEngine(room)
        events = eng._pattern_events(0, room.machine(0), 0, 0.2, room.doc)
        self.assertTrue(any(event[1] == "on" and event[2] == 3
                            for event in events))

    def test_song_playback_produces_audio(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "song"})
        out = np.concatenate([eng.render_block() for _ in range(8)], axis=1)
        self.assertGreater(np.max(np.abs(out)), 0.01)

    def test_render_block_uses_configured_block_size(self):
        room = self._room_with_song()
        room.doc["audio"]["block_size"] = 512
        eng = AudioEngine(room)
        out = eng.render_block()
        self.assertEqual(out.shape[1], 512)

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

    def test_pattern_cache_handles_loop_boundary(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        m = room.machine(0)
        events = eng._pattern_events(0, m, 3.99, 4.1, room.doc)
        onsets = [event for event in events if event[1] == "on"]
        self.assertEqual(len(onsets), 1)
        self.assertAlmostEqual(onsets[0][0], 4.0)
        self.assertEqual(onsets[0][2], 60)

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
        self.assertTrue(any(v.note == 72 for v in eng.slots[0].engine.voices))

    def test_effect_tail_keeps_engine_active_after_voice_ends(self):
        room = self._room_with_song()
        eng = AudioEngine(room)
        eng.handle_note(0, 72, True, 1.0)
        eng.render_block()
        eng.handle_note(0, 72, False)
        for _ in range(100):
            eng.render_block()
            if not eng.slots[0].engine.active():
                break
        self.assertFalse(eng.slots[0].engine.active())
        self.assertGreater(eng._tail_blocks, 0)
        self.assertFalse(eng.is_idle())

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
                sum(len(slot.engine.voices) for slot in eng.slots
                    if slot.engine and hasattr(slot.engine, "voices")))
            max_offs = max(max_offs, sum(
                len(slot.active_offs) for slot in eng.slots))
        self.assertLessEqual(max_voices, room.machine(0)["poly"])
        self.assertLessEqual(max_offs, 2)

    def test_mute_silences_machine(self):
        room = self._room_with_song()
        room.apply({"op": "set_mixer", "slot": 0, "param": "mute", "value": 1})
        eng = AudioEngine(room)
        room.apply({"op": "transport", "playing": True, "mode": "pattern"})
        out = np.concatenate([eng.render_block() for _ in range(4)], axis=1)
        self.assertLess(np.max(np.abs(out)), 1e-6)

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
    def test_factory_samples_exist(self):
        from server import samples
        for name in ("kick", "snare", "piano", "vox_vowels"):
            x = samples.get(name)
            self.assertGreater(len(x), 100, name)
            self.assertTrue(np.all(np.isfinite(x)), name)

    def test_wav_roundtrip(self):
        import io
        from server import samples
        buf = io.BytesIO()
        samples.write_wav(buf, np.sin(np.linspace(0, 100, 4410)))
        x = samples.load_wav_bytes(buf.getvalue())
        self.assertGreater(len(x), 4000)

    def test_24bit_wav_decodes(self):
        import io
        import wave
        from server import samples
        sig = np.sin(np.linspace(0, 60, 4410))
        pcm = (sig * 8388607).astype(np.int32)
        raw = bytearray()
        for v in pcm:
            raw += int(v & 0xFFFFFF).to_bytes(3, "little")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(3)
            w.setframerate(44100)
            w.writeframes(bytes(raw))
        x = samples.load_wav_bytes(buf.getvalue())
        self.assertGreater(len(x), 4000)
        self.assertAlmostEqual(float(np.max(np.abs(x))), 1.0, places=2)

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

    def test_save_rejects_tiny_sample(self):
        import io
        import tempfile
        from server import samples
        buf = io.BytesIO()
        samples.write_wav(buf, np.zeros(4))
        with tempfile.TemporaryDirectory() as tmp:
            orig = samples.SAMPLE_DIR
            samples.SAMPLE_DIR = tmp
            try:
                with self.assertRaises(ValueError):
                    samples.save_user_sample("tiny", buf.getvalue())
            finally:
                samples.SAMPLE_DIR = orig


if __name__ == "__main__":
    unittest.main()
