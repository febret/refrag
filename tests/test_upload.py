"""HTTP tests for the sample upload endpoint (phone upload path)."""

import io
import os
import tempfile
import unittest

import numpy as np
from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase

from server import samples, state
from server.app import make_app


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


if __name__ == "__main__":
    unittest.main()
