"""Tests for bounded real-time audio delivery."""

import asyncio
import unittest

from server.app import ClientSender


class FakeSession:
    def __init__(self):
        self.audio_drops = 0
        self.failed = []

    def sender_failed(self, ws):
        self.failed.append(ws)


class BlockingWebSocket:
    def __init__(self):
        self.gate = asyncio.Event()
        self.bytes = []
        self.text = []

    async def send_bytes(self, data):
        self.bytes.append(data)
        await self.gate.wait()

    async def send_str(self, data):
        self.text.append(data)


class ClientSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_client_drops_oldest_audio_only(self):
        session = FakeSession()
        ws = BlockingWebSocket()
        sender = ClientSender(session, ws, max_audio_blocks=2)
        sender.enqueue_audio(b"first")
        await asyncio.sleep(0)

        sender.enqueue_text("status")
        sender.enqueue_audio(b"old")
        sender.enqueue_audio(b"newer")
        sender.enqueue_audio(b"newest")
        self.assertEqual(session.audio_drops, 1)

        ws.gate.set()
        for _ in range(10):
            if len(ws.bytes) == 3 and ws.text == ["status"]:
                break
            await asyncio.sleep(0)
        await sender.close()

        self.assertEqual(ws.bytes, [b"first", b"newer", b"newest"])
        self.assertEqual(ws.text, ["status"])
        self.assertEqual(session.failed, [])

    async def test_close_cancels_blocked_sender(self):
        sender = ClientSender(FakeSession(), BlockingWebSocket())
        sender.enqueue_audio(b"block")
        await asyncio.sleep(0)
        await sender.close()
        self.assertTrue(sender.task.cancelled())

    async def test_status_messages_are_coalesced_while_blocked(self):
        ws = BlockingWebSocket()
        sender = ClientSender(FakeSession(), ws)
        sender.enqueue_audio(b"block")
        await asyncio.sleep(0)
        sender.enqueue_text("old status", coalesce=True)
        sender.enqueue_text("new status", coalesce=True)
        self.assertEqual(list(sender.messages), [("status", "new status")])
        await sender.close()


if __name__ == "__main__":
    unittest.main()
