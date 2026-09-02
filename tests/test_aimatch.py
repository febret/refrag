"""Tests for the AI Match audio-to-pattern transcription."""

import io
import os
import tempfile
import unittest
from unittest import mock

import numpy as np
from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase

from server import aimatch, samples, state
from server.app import make_app

SR = 44100


def tone(midi, dur, sr=SR):
    f = 440 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(dur * sr)) / sr
    env = np.minimum(1, t * 200) * np.exp(-t * 1.5)
    x = np.zeros_like(t)
    for h, g in ((1, 1.0), (2, 0.4), (3, 0.2)):
        x += g * np.sin(2 * np.pi * f * h * t)
    return x * env * 0.3


def kick(sr=SR):
    t = np.arange(int(0.25 * sr)) / sr
    return np.sin(2 * np.pi * (55 + 40 * np.exp(-t * 30)) * t) * np.exp(-t * 12)


def hat(sr=SR):
    t = np.arange(int(0.06 * sr)) / sr
    rng = np.random.default_rng(1)
    return rng.standard_normal(len(t)) * np.exp(-t * 60) * 0.4


class PostProcessingTests(unittest.TestCase):
    """Model-free tests of the posteriorgram decoder and quantizer."""

    def test_single_note_decoded(self):
        n_frames = 250
        note_pg = np.zeros((n_frames, 88))
        onset_pg = np.zeros((n_frames, 88))
        f = 60 - aimatch.MIDI_OFFSET          # midi 60
        note_pg[10:100, f] = 0.8
        onset_pg[10, f] = 0.9
        events = aimatch.notes_from_posteriorgrams(note_pg, onset_pg)
        self.assertEqual(len(events), 1)
        start_s, end_s, midi, amp = events[0]
        self.assertEqual(midi, 60)
        self.assertAlmostEqual(start_s, 10 * 256 / 22050, delta=0.02)
        self.assertGreater(end_s, start_s + 0.5)
        self.assertAlmostEqual(amp, 0.8, delta=0.05)

    def test_melodia_trick_catches_onsetless_note(self):
        n_frames = 250
        note_pg = np.zeros((n_frames, 88))
        onset_pg = np.zeros((n_frames, 88))
        f = 72 - aimatch.MIDI_OFFSET
        note_pg[50:150, f] = 0.6              # slow swell: no onset spike
        note_pg[49, f] = 0.55                 # soften attack below onset thresh
        events = aimatch.notes_from_posteriorgrams(note_pg, onset_pg)
        self.assertTrue(any(e[2] == 72 for e in events))

    def test_short_blips_rejected(self):
        note_pg = np.zeros((250, 88))
        onset_pg = np.zeros((250, 88))
        f = 60 - aimatch.MIDI_OFFSET
        note_pg[10:14, f] = 0.9               # 4 frames < MIN_NOTE_LEN
        onset_pg[10, f] = 0.9
        self.assertEqual(aimatch.notes_from_posteriorgrams(note_pg, onset_pg),
                         [])

    def test_events_to_pattern_quantizes(self):
        # at 120 bpm: 0.5 s = 1 beat
        events = [(0.01, 0.52, 60, 0.8), (1.0, 1.49, 64, 0.4)]
        pat = aimatch.events_to_pattern(events, bpm=120)
        self.assertEqual(pat["length"], 1)
        self.assertEqual([n[:3] for n in pat["notes"]],
                         [[60, 0.0, 1.0], [64, 2.0, 1.0]])
        # louder event gets the higher velocity
        self.assertGreater(pat["notes"][0][3], pat["notes"][1][3])

    def test_measure_count_fits_clip(self):
        long_events = [(0.0, 0.5, 60, 1.0), (9.5, 10.0, 60, 1.0)]  # 20 beats
        pat = aimatch.events_to_pattern(long_events, bpm=120)
        self.assertEqual(pat["length"], 8)
        self.assertEqual(aimatch.events_to_pattern([], bpm=120),
                         {"length": 1, "notes": []})

    def test_duplicate_positions_merged(self):
        events = [(0.0, 0.5, 60, 0.3), (0.02, 0.5, 60, 0.9)]
        pat = aimatch.events_to_pattern(events, bpm=120)
        self.assertEqual(len(pat["notes"]), 1)


class DrumTranscriptionTests(unittest.TestCase):
    def test_kicks_and_hats_classified(self):
        clip = np.zeros(2 * SR)
        for beat in (0.0, 1.0):               # 120 bpm: beats 0 and 2
            i = int(beat * SR)
            k = kick()
            clip[i:i + len(k)] += k
        for beat in (0.25, 0.75, 1.25, 1.75):
            i = int(beat * SR)
            h = hat()
            clip[i:i + len(h)] += h * 2
        pat = aimatch.drum_events_to_pattern(
            aimatch.transcribe_drums(clip, SR), bpm=120)
        kicks = sorted(n[1] for n in pat["notes"] if n[0] == aimatch.KICK)
        hats = sorted(n[1] for n in pat["notes"] if n[0] in (aimatch.CLHAT,
                                                             aimatch.OPHAT))
        self.assertEqual(kicks, [0.0, 2.0])
        self.assertEqual(hats, [0.5, 1.5, 2.5, 3.5])



@unittest.skipUnless(os.path.exists(aimatch.MODEL_PATH),
                     "Basic Pitch model not downloaded")
class ModelIntegrationTests(unittest.TestCase):
    """End-to-end transcription with the real model (if cached locally)."""

    def test_chord_pitches_recovered(self):
        clip = np.zeros(int(2.2 * SR))
        for m in (60, 64, 67):
            seg = tone(m, 1.0)
            clip[:len(seg)] += seg
        seg = tone(69, 1.0)
        clip[SR:SR + len(seg)] += seg
        pat = aimatch.match_pattern(clip, SR, bpm=120)
        keys = {n[0] for n in pat["notes"]}
        self.assertTrue({60, 64, 67, 69} <= keys, keys)
        self.assertEqual(pat["length"], 1)


class AiMatchApiTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = state.SESSION_DIR
        state.SESSION_DIR = self.tmp.name
        super().setUp()

    def tearDown(self):
        super().tearDown()
        state.SESSION_DIR = self._orig
        self.tmp.cleanup()

    @staticmethod
    def wav_bytes(duration_s=1.0):
        t = np.arange(int(SR * duration_s)) / SR
        buf = io.BytesIO()
        samples.write_wav(buf, np.sin(2 * np.pi * 440 * t) * 0.8)
        return buf.getvalue()

    def form(self):
        fd = FormData()
        fd.add_field("file", self.wav_bytes(), filename="clip.wav",
                     content_type="audio/wav")
        return fd

    async def test_match_overwrites_pattern(self):
        from server.app import rooms
        fake = {"length": 2, "notes": [[60, 0.0, 1.0, 0.8, 0],
                                       [64, 4.0, 1.0, 0.6, 0]]}
        with mock.patch.object(aimatch, "match_pattern", return_value=fake):
            room = rooms.get("aimatch-room")
            room.apply({"op": "add_machine", "slot": 0, "mtype": "subsynth"})
            resp = await self.client.post(
                "/api/aimatch?room=aimatch-room&slot=0", data=self.form())
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(body, {"notes": 2, "measures": 2})
            pat = room.machine(0)["patterns"]["A1"]
            self.assertEqual(pat["length"], 2)
            self.assertEqual(len(pat["notes"]), 2)



    async def test_silent_clip_reports_no_notes(self):
        from server.app import rooms
        room = rooms.get("aimatch-silent")
        room.apply({"op": "add_machine", "slot": 0, "mtype": "beatbox"})
        buf = io.BytesIO()
        samples.write_wav(buf, np.zeros(SR))
        fd = FormData()
        fd.add_field("file", buf.getvalue(), filename="silent.wav",
                     content_type="audio/wav")
        resp = await self.client.post(
            "/api/aimatch?room=aimatch-silent&slot=0", data=fd)
        self.assertEqual(resp.status, 422)


if __name__ == "__main__":
    unittest.main()
