"""Optional direct audio output from the server to a local sound device.

Normally Refrag streams rendered audio to browsers over WebSockets, which adds
queueing and jitter-buffer latency.  When the server runs on the same machine
as the listener, setting ``REFRAG_AUDIO_OUT`` sends the engine's rendered
blocks straight to a local device instead, cutting that latency out.

``REFRAG_AUDIO_OUT`` is unset by default (feature off).  A value of ``0``
selects the system default output device; any other integer is a PortAudio
device index.  Run ``python -m server.audio_out`` to list available devices.

All rooms mix into a single shared sink, so several rooms playing at once are
summed together before hitting the device.
"""

import os
import sys
import threading

import numpy as np

try:
    import sounddevice
except Exception:                                   # pragma: no cover
    sounddevice = None

ENV_VAR = "REFRAG_AUDIO_OUT"
DEFAULT_DEVICE = 0
RING_BLOCKS = 4
# Frames to accumulate before the device starts consuming.  The render loop
# produces blocks at exactly real time, so without a small head start every
# scheduling jitter spike would surface as an underrun.
PRIME_BLOCKS = 2


class LocalAudioOutput:
    """Mixing sink that feeds a PortAudio output stream from render threads.

    Each room writes through its own :class:`RoomSink` cursor, so blocks that
    cover the same span of time are summed rather than concatenated.  The
    PortAudio callback drains the ring on its own thread; when it runs dry it
    emits silence and bumps :attr:`underruns`.
    """

    def __init__(self, device=DEFAULT_DEVICE, ring_blocks=RING_BLOCKS,
                 prime_blocks=PRIME_BLOCKS):
        self.device = device
        self.ring_blocks = max(2, int(ring_blocks))
        self.prime_blocks = max(0, int(prime_blocks))
        self.sample_rate = 0
        self.block_size = 0
        self.underruns = 0
        self.stream = None
        self._lock = threading.Lock()
        self._ring = None
        self._pos = 0            # absolute frame index of the read cursor
        self._end = 0            # absolute frame index one past the newest data
        self._primed = False
        self._prime_frames = 0

    # -- lifecycle ---------------------------------------------------------

    def open(self, sample_rate, block_size):
        """Start the output stream.  Returns True once running.

        Safe to call repeatedly; only the first call opens a stream.  Later
        calls with a different format are ignored (rooms are not resampled);
        use :meth:`matches` to detect that case.
        """
        with self._lock:
            if self.stream is not None:
                return True
            if sounddevice is None:
                raise RuntimeError(
                    "sounddevice is not installed; cannot use %s" % ENV_VAR)
            sample_rate = int(sample_rate)
            block_size = int(block_size)
            self._ring = np.zeros((self.ring_blocks * block_size, 2),
                                  dtype=np.float32)
            self._pos = 0
            self._end = 0
            self._primed = self.prime_blocks == 0
            self._prime_frames = min(self.prime_blocks,
                                     self.ring_blocks - 1) * block_size
            self.sample_rate = sample_rate
            self.block_size = block_size
            device = None if self.device == 0 else self.device
            self.stream = sounddevice.OutputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                channels=2,
                dtype="float32",
                callback=self._callback,
            )
            self.stream.start()
            return True

    def close(self):
        with self._lock:
            stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    @property
    def is_open(self):
        return self.stream is not None

    def matches(self, sample_rate, block_size):
        """True if the sink format matches (or the sink is not open yet)."""
        if self.stream is None:
            return True
        return (self.sample_rate == int(sample_rate)
                and self.block_size == int(block_size))

    def room_sink(self):
        """Create an independent write cursor for one room."""
        return RoomSink(self)

    # -- data flow ---------------------------------------------------------

    def submit(self, block, cursor=None):
        """Mix a ``(2, n)`` float block in at ``cursor`` (an absolute frame).

        Returns the next absolute write position.  ``cursor`` of ``None``, or
        one that has drifted outside the buffered window, resyncs to just
        ahead of the read cursor so latency stays bounded.
        """
        data = np.asarray(block, dtype=np.float32)
        if data.ndim != 2 or data.shape[0] != 2:
            raise ValueError("expected a (2, n) stereo block")
        n = data.shape[1]
        with self._lock:
            if self._ring is None:
                return self._pos
            if n == 0:
                return self._pos if cursor is None else cursor
            size = self._ring.shape[0]
            if n > size:
                data = data[:, -size:]
                n = size
            # A new or drifted room joins at the read cursor so it lines up
            # with audio other rooms have already queued for the same instant.
            latest = self._pos + size - n
            if cursor is None or cursor < self._pos or cursor > latest:
                cursor = min(self._pos, latest)
            self._clear_through(cursor + n)
            frames = data.T
            start = cursor % size
            end = start + n
            if end <= size:
                self._ring[start:end] += frames
            else:
                head = size - start
                self._ring[start:] += frames[:head]
                self._ring[:end - size] += frames[head:]
            self._end = max(self._end, cursor + n)
            if not self._primed and self._end - self._pos >= self._prime_frames:
                self._primed = True
            return cursor + n

    def _clear_through(self, target):
        """Zero ring slots between the newest written frame and ``target``.

        Slots are reused after wrapping, so stale audio must be erased before
        it is summed into.  Called with the lock held.
        """
        if target <= self._end:
            return
        size = self._ring.shape[0]
        first = max(self._end, target - size)
        count = target - first
        start = first % size
        end = start + count
        if end <= size:
            self._ring[start:end] = 0.0
        else:
            self._ring[start:] = 0.0
            self._ring[:end - size] = 0.0
        self._end = target

    def _pull(self, n):
        """Return ``n`` frames as ``(n, 2)``; pads with silence on underrun."""
        out = np.zeros((n, 2), dtype=np.float32)
        with self._lock:
            if self._ring is None:
                self.underruns += 1
                return out
            if not self._primed:
                # Still filling the head start; stay silent without counting
                # this as an underrun.
                return out
            avail = min(n, self._end - self._pos)
            if avail < n:
                self.underruns += 1
                # Refill the head start before resuming, so one late block does
                # not leave the buffer permanently on the edge of starving.
                self._primed = False
            if avail > 0:
                size = self._ring.shape[0]
                start = self._pos % size
                end = start + avail
                if end <= size:
                    out[:avail] = self._ring[start:end]
                    self._ring[start:end] = 0.0
                else:
                    head = size - start
                    out[:head] = self._ring[start:]
                    self._ring[start:] = 0.0
                    out[head:avail] = self._ring[:end - size]
                    self._ring[:end - size] = 0.0
            self._pos += max(avail, 0)
            if self._end < self._pos:
                self._end = self._pos
        np.clip(out, -1.0, 1.0, out=out)
        return out

    def _callback(self, outdata, frames, time_info, status):
        outdata[:] = self._pull(frames)


class RoomSink:
    """Per-room write cursor into a shared :class:`LocalAudioOutput`."""

    def __init__(self, output):
        self.output = output
        self.cursor = None

    def submit(self, block):
        self.cursor = self.output.submit(block, self.cursor)


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def parse_device(value):
    """Parse a ``REFRAG_AUDIO_OUT`` value into a device index or None."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            "%s must be an integer device index (0 = default device), got %r"
            % (ENV_VAR, value))


def configure_from_env(env=None):
    """Build a :class:`LocalAudioOutput` from ``REFRAG_AUDIO_OUT``.

    Returns ``None`` when the variable is unset, malformed, or when
    ``sounddevice`` is unavailable, so the server always keeps starting.
    """
    env = os.environ if env is None else env
    try:
        device = parse_device(env.get(ENV_VAR))
    except ValueError as exc:
        print("[audio-out] %s" % exc, file=sys.stderr)
        return None
    if device is None:
        return None
    if sounddevice is None:
        print("[audio-out] %s is set but the 'sounddevice' package is not "
              "installed; local playback disabled." % ENV_VAR, file=sys.stderr)
        return None
    print("[audio-out] local playback enabled on device %s"
          % ("default" if device == 0 else device))
    return LocalAudioOutput(device=device)


def list_devices():
    """Return a list of ``(index, name, max_output_channels)`` tuples."""
    if sounddevice is None:
        return []
    out = []
    for i, dev in enumerate(sounddevice.query_devices()):
        if dev.get("max_output_channels", 0) > 0:
            out.append((i, dev.get("name", "?"), dev["max_output_channels"]))
    return out


def _main():
    if sounddevice is None:
        print("sounddevice is not installed; run: pip install sounddevice")
        return 1
    print("Output devices (use the index as %s):" % ENV_VAR)
    print("  0\t<system default>")
    for index, name, channels in list_devices():
        if index == 0:
            continue
        print("  %d\t%s (%d ch)" % (index, name, channels))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
