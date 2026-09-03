"""HTTP tests for the sample upload endpoint (phone upload path)."""

import io
import os
import tempfile
import unittest

import numpy as np
from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase

from server import samples, state
from server.app import make_app, rooms


def wav_bytes(duration_s=0.2, freq=440.0):
    t = np.arange(int(44100 * duration_s)) / 44100.0
    buf = io.BytesIO()
    samples.write_wav(buf, np.sin(2 * np.pi * freq * t) * 0.8)
    return buf.getvalue()


class UploadApiTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = samples.SAMPLE_DIR
        samples.SAMPLE_DIR = self.tmp.name
        super().setUp()

    def tearDown(self):
        super().tearDown()
        samples.SAMPLE_DIR = self._orig
        self.tmp.cleanup()

    async def test_upload_with_name_field(self):
        fd = FormData()
        fd.add_field("name", "My Phone Riff")
        fd.add_field("file", wav_bytes(), filename="ignored.wav",
                     content_type="audio/wav")
        resp = await self.client.post("/api/samples", data=fd)
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["name"], "My Phone Riff")
        # listed by the samples API
        resp = await self.client.get("/api/samples")
        lib = await resp.json()
        self.assertIn("My Phone Riff", lib["user"])
        # loadable by the synth engine
        x = samples.get("My Phone Riff")
        self.assertGreater(len(x), 1000)




    async def test_factory_collision_renamed(self):
        fd = FormData()
        fd.add_field("name", "kick")
        fd.add_field("file", wav_bytes(), filename="kick.wav",
                     content_type="audio/wav")
        resp = await self.client.post("/api/samples", data=fd)
        body = await resp.json()
        self.assertNotEqual(body["name"], "kick")

    async def test_waveform_summary_is_bounded(self):
        resp = await self.client.get(
            "/api/samples/waveform", params={"name": "kick", "points": "80"})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["name"], "kick")
        self.assertEqual(len(body["min"]), 80)
        self.assertEqual(len(body["max"]), 80)
        self.assertGreater(body["duration"], 0)
        self.assertGreater(body["peak"], 0)

    async def test_waveform_rejects_missing_sample(self):
        resp = await self.client.get(
            "/api/samples/waveform", params={"name": "definitely missing"})
        self.assertEqual(resp.status, 404)

    async def test_sampler_normalize_uses_cropped_peak(self):
        shaped = io.BytesIO()
        samples.write_wav(
            shaped,
            np.concatenate([
                np.full(2048, 0.1, dtype=np.float32),
                np.full(2048, 0.8, dtype=np.float32),
            ]))
        name = samples.save_user_sample("normalize shape", shaped.getvalue())
        room = rooms.get("normalize-sampler-test")
        room.doc = state.new_room_doc()
        room.apply({"op": "add_machine", "slot": 0, "mtype": "sampler"})
        room.apply({
            "op": "set_sampler_param", "slot": 0, "key": "A1",
            "param": "sample", "value": name,
        })
        room.apply({
            "op": "set_sampler_param", "slot": 0, "key": "A1",
            "param": "end", "value": 0.49,
        })
        resp = await self.client.post("/api/sampler/normalize", json={
            "room": room.id, "slot": 0, "key": "A1",
        })
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertAlmostEqual(body["peak"], 0.1, places=3)
        self.assertGreater(body["gain"], 9.0)
        self.assertAlmostEqual(
            room.machine(0)["patterns"]["A1"]["sampler"]["gain"],
            body["gain"])


if __name__ == "__main__":
    unittest.main()
