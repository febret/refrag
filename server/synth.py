"""Native audio-engine bindings and render-asset synchronization."""

from __future__ import annotations

import numpy as np

import refrag_engine as _native

from . import samples


def _sample_names(machine):
    if not machine:
        return set()
    names = set()
    if machine.get("type") == "beatbox":
        entries = machine.get("channels") or []
    elif machine.get("type") == "pcmsynth":
        entries = machine.get("samples") or []
    elif machine.get("type") == "vocoder":
        entries = machine.get("modulators") or []
    elif machine.get("type") == "sampler":
        entries = [
            pat.get("sampler") or {}
            for pat in (machine.get("patterns") or {}).values()
            if isinstance(pat, dict)
        ]
    else:
        entries = []
    for entry in entries:
        name = str(entry.get("sample") or entry.get("source") or "")
        if name:
            names.add(name)
    return names


class NativeRoomEngine:
    """Owns a room's complete native machine/effect/mixer render graph."""

    def __init__(self, sample_rate, block_size, slot_count):
        self._registered_samples = {}
        self._engine = _native.create_room_engine(
            int(sample_rate), int(block_size), int(slot_count))

    def sync(self, doc):
        names = set()
        for machine in doc.get("machines") or []:
            names.update(_sample_names(machine))
        for name in names:
            source = samples.get(name)
            if self._registered_samples.get(name) is source:
                continue
            buffer = np.ascontiguousarray(source, dtype=np.float32)
            self._engine.register_sample(name, buffer, samples.SR)
            self._registered_samples[name] = source
        self._engine.sync(doc)

    def note_on(self, slot, note, vel, offset=0, flags=0):
        self._engine.note_on(slot, note, vel, offset, flags)

    def note_off(self, slot, note, offset=0):
        self._engine.note_off(slot, note, offset)

    def all_off(self, slot=-1):
        self._engine.all_off(slot)

    def active(self):
        return self._engine.active()

    def render(self, frames, bpm):
        return self._engine.render(frames, bpm)

    def status(self):
        return self._engine.status()
