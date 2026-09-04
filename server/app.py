"""Refrag web server: static app, room API, WebSocket sync + audio streaming."""

import asyncio
from collections import deque
import io
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse

import numpy as np
from aiohttp import WSMsgType, web

from . import aimatch, audio_out, catalog, factory_presets, samples
from .engine import AudioEngine, render_song
from .state import (AUDIO_DEFAULT_BLOCK_SIZE, AUDIO_DEFAULT_SAMPLE_RATE,
                    RoomManager, SESSION_DIR)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
TLS_DIR = os.path.join(ROOT, "data", "tls")
DEFAULT_SSL_CERT = os.path.join(TLS_DIR, "refrag-cert.pem")
DEFAULT_SSL_KEY = os.path.join(TLS_DIR, "refrag-key.pem")

rooms = RoomManager()

# Optional direct-to-device audio sink, shared by every room (see audio_out).
LOCAL_AUDIO = None


class ClientSender:
    """Single WebSocket writer with a bounded queue for disposable audio."""

    def __init__(self, session, ws, max_audio_blocks=4):
        self.session = session
        self.ws = ws
        self.max_audio_blocks = max_audio_blocks
        self.messages = deque()
        self.audio_blocks = 0
        self.ready = asyncio.Event()
        self.task = asyncio.get_running_loop().create_task(self.run())

    def enqueue_audio(self, data):
        if self.audio_blocks >= self.max_audio_blocks:
            for i, (kind, _) in enumerate(self.messages):
                if kind == "audio":
                    del self.messages[i]
                    self.audio_blocks -= 1
                    self.session.audio_drops += 1
                    break
        self.messages.append(("audio", data))
        self.audio_blocks += 1
        self.ready.set()

    def enqueue_text(self, data, coalesce=False):
        if coalesce:
            for i, (kind, _) in enumerate(self.messages):
                if kind == "status":
                    self.messages[i] = ("status", data)
                    return
            kind = "status"
        else:
            kind = "text"
        self.messages.append((kind, data))
        self.ready.set()

    async def run(self):
        try:
            while True:
                if not self.messages:
                    self.ready.clear()
                    await self.ready.wait()
                    continue
                kind, data = self.messages.popleft()
                if kind == "audio":
                    self.audio_blocks -= 1
                    await self.ws.send_bytes(data)
                else:
                    await self.ws.send_str(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.session.sender_failed(self.ws)

    async def close(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass


class RoomSession:
    """Runtime for one room: sockets + streaming loop."""

    def __init__(self, room):
        self.room = room
        self.sockets = set()
        self.senders = {}
        self.engine = AudioEngine(room)
        self.engine.on_state_change = self.schedule_broadcast
        self.task = None
        self._broadcast_flag = False
        self.render_ms = 0.0
        self.render_peak_ms = 0.0
        self.deadline_late_ms = 0.0
        self.overruns = 0
        self.scheduler_resets = 0
        self.audio_drops = 0
        self._local_audio_warned = False
        self._local_sink = None

    def _submit_local_audio(self, blk):
        """Mix a rendered block into the shared local output device, if any."""
        if LOCAL_AUDIO is None:
            return
        sample_rate, block_size = self._audio_settings()
        try:
            if not LOCAL_AUDIO.is_open:
                LOCAL_AUDIO.open(sample_rate, block_size)
            elif not LOCAL_AUDIO.matches(sample_rate, block_size):
                if not self._local_audio_warned:
                    self._local_audio_warned = True
                    print("[audio-out] room %s runs at %d Hz / %d frames but "
                          "the output device is open at %d Hz / %d frames; "
                          "this room is not sent to the local device."
                          % (self.room.id, sample_rate, block_size,
                             LOCAL_AUDIO.sample_rate, LOCAL_AUDIO.block_size),
                          file=sys.stderr)
                return
            if self._local_sink is None:
                self._local_sink = LOCAL_AUDIO.room_sink()
            self._local_sink.submit(blk)
        except Exception as exc:
            if not self._local_audio_warned:
                self._local_audio_warned = True
                print("[audio-out] local playback failed: %s" % exc,
                      file=sys.stderr)

    def _audio_settings(self):
        audio = self.room.doc.get("audio") or {}
        sr = int(audio.get("sample_rate", AUDIO_DEFAULT_SAMPLE_RATE))
        block = int(audio.get("block_size", AUDIO_DEFAULT_BLOCK_SIZE))
        return sr, block

    def add_socket(self, ws):
        self.sockets.add(ws)
        self.senders[ws] = ClientSender(self, ws)

    async def remove_socket(self, ws):
        self.sockets.discard(ws)
        sender = self.senders.pop(ws, None)
        if sender is not None:
            await sender.close()

    def sender_failed(self, ws):
        self.sockets.discard(ws)
        self.senders.pop(ws, None)
        loop = asyncio.get_running_loop()
        loop.create_task(ws.close())
        loop.create_task(self.broadcast(
            {"type": "users", "count": len(self.sockets)}))

    async def send(self, ws, obj):
        sender = self.senders.get(ws)
        if sender is not None:
            sender.enqueue_text(json.dumps(obj))

    def schedule_broadcast(self):
        self._broadcast_flag = True

    async def run(self):
        """Real-time render/stream loop."""
        next_t = time.monotonic()
        status_t = 0.0
        idle_silence = 0
        while True:
            try:
                if not self.sockets and LOCAL_AUDIO is None:
                    await asyncio.sleep(0.25)
                    next_t = time.monotonic()
                    continue
                if self.engine.is_idle():
                    idle_silence += 1
                else:
                    idle_silence = 0
                # ~0.5s of silence: stop streaming.  With a local device open
                # we keep rendering so its ring buffer never starves.
                if idle_silence > 12 and LOCAL_AUDIO is None:
                    await asyncio.sleep(0.05)
                    next_t = time.monotonic()
                    now = time.monotonic()
                    if now - status_t > 0.5:
                        status_t = now
                        await self.send_status()
                    if self._broadcast_flag:
                        self._broadcast_flag = False
                        await self.broadcast_doc()
                    self.room.maybe_save()
                    continue

                render_start = time.perf_counter()
                blk = await asyncio.get_running_loop().run_in_executor(
                    None, self.engine.render_block)
                elapsed_ms = (time.perf_counter() - render_start) * 1000.0
                self.render_ms = (elapsed_ms if self.render_ms == 0 else
                                  self.render_ms * 0.9 + elapsed_ms * 0.1)
                self.render_peak_ms = max(self.render_peak_ms, elapsed_ms)
                n = blk.shape[1]
                self._submit_local_audio(blk)
                pcm = np.empty(n * 2, dtype="<i2")
                pcm[0::2] = np.clip(blk[0] * 32000, -32768, 32767).astype("<i2")
                pcm[1::2] = np.clip(blk[1] * 32000, -32768, 32767).astype("<i2")
                data = pcm.tobytes()
                for sender in list(self.senders.values()):
                    sender.enqueue_audio(data)

                now = time.monotonic()
                if now - status_t > 0.12:
                    status_t = now
                    await self.send_status()
                if self._broadcast_flag:
                    self._broadcast_flag = False
                    await self.broadcast_doc()
                self.room.maybe_save()

                block_s = n / max(1.0, float(self.engine.sample_rate))
                next_t += block_s
                delay = next_t - time.monotonic()
                self.deadline_late_ms = max(0.0, -delay * 1000.0)
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    self.overruns += 1
                    if delay < -block_s:
                        next_t = time.monotonic()
                        self.scheduler_resets += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                import traceback
                traceback.print_exc()
                await asyncio.sleep(0.5)

    async def send_status(self):
        sample_rate, block_size = self._audio_settings()
        perf = {
            "render_ms": round(self.render_ms, 2),
            "render_peak_ms": round(self.render_peak_ms, 2),
            "deadline_late_ms": round(self.deadline_late_ms, 2),
            "overruns": self.overruns,
            "render_drops": self.overruns,
            "scheduler_resets": self.scheduler_resets,
            "audio_drops": self.audio_drops,
        }
        if LOCAL_AUDIO is not None:
            perf["audio_out_underruns"] = LOCAL_AUDIO.underruns
        msg = json.dumps({
            "type": "status",
            **self.engine.status(),
            "audio": {"sample_rate": sample_rate, "block_size": block_size},
            "perf": perf,
        })
        for sender in list(self.senders.values()):
            sender.enqueue_text(msg, coalesce=True)
        self.render_peak_ms = self.render_ms

    async def broadcast_doc(self, exclude=None):
        msg = json.dumps({"type": "doc", "rev": self.room.rev,
                          "doc": self.room.doc})
        for ws, sender in list(self.senders.items()):
            if ws is exclude:
                continue
            sender.enqueue_text(msg)

    async def broadcast(self, obj, exclude=None):
        msg = json.dumps(obj)
        for ws, sender in list(self.senders.items()):
            if ws is exclude:
                continue
            sender.enqueue_text(msg)


sessions = {}


def get_session(room_id):
    room = rooms.get(room_id)
    sess = sessions.get(room.id)
    if sess is None:
        sess = RoomSession(room)
        sessions[room.id] = sess
        sess.task = asyncio.get_event_loop().create_task(sess.run())
    return sess


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def index(request):
    return web.FileResponse(os.path.join(WEB_DIR, "index.html"))


async def catalog_handler(request):
    return web.json_response(catalog.catalog_json())


async def samples_handler(request):
    return web.json_response({"factory": samples.factory_names(),
                              "user": samples.user_names()})


async def sample_waveform_handler(request):
    name = request.query.get("name", "")
    try:
        points = int(request.query.get("points", 1024))
        summary = samples.waveform_summary(name, points)
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid waveform request"}, status=400)
    except KeyError:
        return web.json_response({"error": "sample not found"}, status=404)
    return web.json_response(summary)


async def normalize_sampler_handler(request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError
        slot = int(body["slot"])
        key = str(body["key"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return web.json_response({"error": "invalid normalization request"}, status=400)
    sess = get_session(str(body.get("room") or "default"))
    room = sess.room
    with room.lock:
        machine = room.machine(slot)
        pattern = room.get_pattern(machine, key) if machine is not None else None
        settings = pattern.get("sampler") if isinstance(pattern, dict) else None
        if machine is None or machine.get("type") != "sampler" or not settings:
            return web.json_response({"error": "sampler pattern not found"}, status=404)
        name = settings.get("sample", "")
        start = settings.get("start", 0.0)
        end = settings.get("end", 1.0)
        try:
            peak = samples.sample_peak(name, start, end)
        except KeyError:
            return web.json_response({"error": "sample not found"}, status=404)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if peak <= 1e-9:
            return web.json_response({"error": "cannot normalize a silent sample"},
                                     status=422)
        gain = min(16.0, 0.95 / peak)
        changed = room.apply({
            "op": "set_sampler_param",
            "slot": slot,
            "key": key,
            "param": "gain",
            "value": gain,
        })
    if not changed:
        return web.json_response({"error": "sampler pattern changed"}, status=409)
    sess.engine.wake()
    await sess.broadcast_doc()
    return web.json_response({"gain": gain, "peak": peak})


async def upload_sample(request):
    """Accept a WAV upload (multipart fields: optional 'name', 'file')."""
    reader = await request.multipart()
    name = None
    data = None
    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name == "name":
            name = await field.text()
        else:
            if name is None and field.filename:
                fname = urllib.parse.unquote(field.filename)
                name = os.path.splitext(os.path.basename(fname))[0]
            data = await field.read()
    name = "".join(ch for ch in (name or "sample")
                   if ch.isalnum() or ch in "_- ")[:40].strip() or "sample"
    if not data:
        return web.json_response({"error": "no file received"}, status=400)
    try:
        name = samples.save_user_sample(name, data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"name": name})


async def presets_handler(request):
    room = rooms.get(request.query.get("room", "default"))
    mtype = request.match_info["mtype"]
    return web.json_response({"presets": room.list_presets(mtype)})


async def export_handler(request):
    room = rooms.get(request.query.get("room", "default"))
    loop_only = request.query.get("loop") == "1"
    loop = asyncio.get_event_loop()
    audio = await loop.run_in_executor(None, render_song, room, loop_only)
    buf = io.BytesIO()
    samples.write_wav(buf, audio)
    data = buf.getvalue()
    name = room.doc.get("name", "song") + ".wav"
    return web.Response(body=data, content_type="audio/wav",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{name}"'})


async def songs_handler(request):
    return web.json_response({"songs": rooms.list()})


async def load_song_handler(request):
    room_id = request.query.get("room", "default")
    song = request.query.get("song") or request.query.get("name")
    if not song:
        return web.json_response({"error": "song is required"}, status=400)
    room = rooms.get(room_id)
    if not room.load_snapshot(song):
        return web.json_response({"error": "song not found"}, status=404)
    return web.json_response({"ok": True, "song": song, "room": room.id})


async def aimatch_handler(request):
    """AI Match: transcribe an uploaded WAV into the current pattern.

    Multipart field 'file' (16-bit mono/stereo WAV); query: room, slot.
    Overwrites the machine's current pattern (notes + measure count).
    """
    room_id = request.query.get("room", "default")
    try:
        slot = int(request.query.get("slot", "-1"))
    except ValueError:
        slot = -1
    sess = get_session(room_id)
    room = sess.room
    m = room.machine(slot)
    if m is None:
        return web.json_response({"error": "no machine in that slot"}, status=400)
    if m.get("type") == "sampler":
        return web.json_response(
            {"error": "AI Match requires a note or drum pattern editor"},
            status=400)

    reader = await request.multipart()
    data = None
    while True:
        field = await reader.next()
        if field is None:
            break
        data = await field.read()
    if not data:
        return web.json_response({"error": "no audio received"}, status=400)
    try:
        audio = samples.load_wav_bytes(data)
    except Exception as e:
        return web.json_response({"error": f"bad WAV: {e}"}, status=400)

    bpm = room.doc["bpm"]
    drum = m["type"] == "beatbox"
    loop = asyncio.get_event_loop()
    try:
        pat = await loop.run_in_executor(
            None, aimatch.match_pattern, audio, samples.SR, bpm, drum)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=503)

    if not pat["notes"]:
        return web.json_response({"error": "no notes detected in the clip"},
                                 status=422)
    room.apply({"op": "set_pattern_notes", "slot": slot,
                "length": pat["length"], "notes": pat["notes"]})
    sess.engine.wake()
    await sess.broadcast_doc()
    return web.json_response({"notes": len(pat["notes"]),
                              "measures": pat["length"]})


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024, heartbeat=30)
    await ws.prepare(request)
    room_id = request.query.get("room", "default")
    sess = get_session(room_id)
    room = sess.room

    sr, block = sess._audio_settings()
    await ws.send_str(json.dumps({"type": "hello", "room": room.id,
                                  "sr": sr, "block": block,
                                  "users": len(sess.sockets) + 1}))
    await ws.send_str(json.dumps({"type": "doc", "rev": room.rev,
                                  "doc": room.doc}))
    sess.add_socket(ws)
    await sess.broadcast({"type": "users", "count": len(sess.sockets)})

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                op = json.loads(msg.data)
            except ValueError:
                continue
            kind = op.get("op")
            if kind == "note":
                sess.engine.handle_note(int(op["slot"]), int(op["note"]),
                                        bool(op["on"]), float(op.get("vel", 1)),
                                        int(op.get("flags", 0)))
                await sess.broadcast({"type": "note", "slot": op["slot"],
                                      "note": op["note"], "on": op["on"]},
                                     exclude=ws)
            elif kind == "save_preset":
                if room.save_preset(int(op["slot"]), op["name"]):
                    await sess.broadcast_doc()
            elif kind == "load_preset":
                if room.load_preset(int(op["slot"]), op["name"]):
                    await sess.broadcast_doc()
            elif kind == "save_room":
                room.save(force=True)
                await sess.send(ws, {"type": "saved"})
            elif kind == "load_room":
                song = str(op.get("name") or op.get("song") or "")
                if not song:
                    await sess.send(ws, {"type": "error", "message": "No song selected"})
                    continue
                if room.load_snapshot(song):
                    sess.engine.wake()
                    await sess.broadcast_doc()
                    await sess.send(ws, {"type": "loaded", "song": song})
                else:
                    await sess.send(ws, {"type": "error", "message": f"Song not found: {song}"})
            elif kind:
                changed = room.apply(op)
                if changed:
                    sess.engine.wake()
                    if room.runtime_only:
                        await sess.send_status()
                    elif op.get("op") in ("set_param", "set_mixer", "set_master",
                                        "set_effect_param", "mod_param",
                                        "set_channel_param", "set_harmonic",
                                        "set_sample_param", "set_sampler_param"):
                        # lightweight echo for continuous controls
                        await sess.broadcast({"type": "opecho", "req": op},
                                             exclude=ws)
                    else:
                        await sess.broadcast_doc()
    finally:
        await sess.remove_socket(ws)
        await sess.broadcast({"type": "users", "count": len(sess.sockets)})
        room.save(force=True)
    return ws


def make_app():
    # generous upload limit so phone voice memos / recordings fit
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/api/catalog", catalog_handler)
    app.router.add_get("/api/samples", samples_handler)
    app.router.add_get("/api/samples/waveform", sample_waveform_handler)
    app.router.add_get("/api/songs", songs_handler)
    app.router.add_get("/api/rooms", songs_handler)
    app.router.add_get("/api/load", load_song_handler)
    app.router.add_post("/api/samples", upload_sample)
    app.router.add_post("/api/sampler/normalize", normalize_sampler_handler)
    app.router.add_post("/api/aimatch", aimatch_handler)
    app.router.add_get("/api/presets/{mtype}", presets_handler)
    app.router.add_get("/api/export", export_handler)
    app.router.add_get("/refrag-cert.pem", tls_certificate_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/web/", WEB_DIR)
    app.on_startup.append(_start_local_audio_room)
    app.on_shutdown.append(_close_local_audio)
    return app


def init_local_audio():
    """Enable direct device output when REFRAG_AUDIO_OUT is set."""
    global LOCAL_AUDIO
    LOCAL_AUDIO = audio_out.configure_from_env()
    return LOCAL_AUDIO


async def _start_local_audio_room(app):
    """Bring up the default room so local playback works with no browser."""
    if LOCAL_AUDIO is not None:
        get_session("default")


async def _close_local_audio(app):
    global LOCAL_AUDIO
    sink, LOCAL_AUDIO = LOCAL_AUDIO, None
    if sink is not None:
        sink.close()


def _certificate_paths():
    cert = os.environ.get("REFRAG_SSL_CERT")
    key = os.environ.get("REFRAG_SSL_KEY")
    if bool(cert) != bool(key):
        raise RuntimeError(
            "REFRAG_SSL_CERT and REFRAG_SSL_KEY must both be set")
    return (cert, key) if cert else (DEFAULT_SSL_CERT, DEFAULT_SSL_KEY)


def ensure_self_signed_certificate(cert_path, key_path):
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return
    os.makedirs(os.path.dirname(cert_path), exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "server.tls", cert_path, key_path],
        cwd=ROOT,
        check=True)


def ssl_context_from_env():
    cert, key = _certificate_paths()
    if not os.environ.get("REFRAG_SSL_CERT"):
        ensure_self_signed_certificate(cert, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


async def tls_certificate_handler(request):
    cert, key = _certificate_paths()
    if not os.environ.get("REFRAG_SSL_CERT"):
        ensure_self_signed_certificate(cert, key)
    return web.FileResponse(
        cert,
        headers={"Content-Disposition":
                 'attachment; filename="refrag-cert.pem"'})


def main():
    port = int(os.environ.get("REFRAG_PORT", "8000"))
    os.makedirs(SESSION_DIR, exist_ok=True)
    factory_presets.install()
    init_local_audio()
    app = make_app()
    ssl_context = ssl_context_from_env()
    cert, _ = _certificate_paths()
    print(f"Refrag listening on https://localhost:{port}")
    if not os.environ.get("REFRAG_SSL_CERT"):
        print(f"Using self-signed certificate: {cert}")
    web.run_app(app, port=port, print=None, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
