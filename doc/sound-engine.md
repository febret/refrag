# Refrag Sound Engine Architecture

Refrag renders audio in the native C++ `refrag_engine` extension. Each Python
`AudioEngine` owns one persistent native room graph. Python manages
collaboration, transport, sequencing, automation, asset loading, and streaming;
C++ owns every operation that produces or transforms a rendered sample.

## Render flow

For each block, the server:

1. Reads room state while holding the room lock.
2. Resolves transport events and automation values.
3. Registers newly referenced sample assets with the native sample bank.
4. Synchronizes machine, effect, mixer, routing, and master configuration.
5. Submits note-on and note-off events with offsets within the block.
6. Calls the native room graph once and receives the final planar stereo block.
7. Uses native meter/status values and advances the Python transport clock.

The real-time streaming loop and offline WAV export use this same path. Export
does not have a separate Python DSP implementation.

```text
room state / clients
        |
        v
+----------------------------+
| Python AudioEngine         |
| transport and sequencing   |
| automation and note events |
| sample asset registration  |
+-------------+--------------+
              |
              | graph state + timestamped events
              v
+-------------+--------------+
| Native RoomEngine          |
| machine voices             |
| insert effects             |
| mixer strips and routing   |
| sends and master chain     |
+-------------+--------------+
              |
              | final stereo float block + meters
              v
 streaming PCM / WAV export
```

## Native graph ownership

The room graph persists for the lifetime of an audio configuration and owns:

- all 11 machine implementations and their voices;
- the native sample bank and sample-playback cursors;
- two insert-effect instances per rack slot;
- channel EQ, width history, pan, volume, mute/solo, and send levels;
- dry-output, processed-line, previous-block, delay-send, and reverb-send buses;
- master delay, reverb, inserts, EQ, limiter, volume, and clipping;
- effect and send tails, VU meters, limiter gain reduction, and Vocoder bands.

Compatible state survives graph synchronization. Replacing a machine or effect
resets only the corresponding native runtime object. Changing sample rate or
block size creates a new graph because delay lines, filters, and time constants
depend on those values.

## Samples

WAV decoding, uploads, and procedural factory-sample creation remain Python
asset utilities. Before a referenced BeatBox, PCMSynth, or Vocoder sample can
render, Python passes a contiguous mono float buffer and its source sample rate
to the native sample bank. C++ retains render-safe storage and performs all
playback, interpolation, pitch conversion, looping, envelopes, and filtering.

Sample arrays never cross the Python boundary once per block. Registration only
occurs when a graph first references an asset.

## Routing order

The native graph preserves rack ordering and state from block to block:

1. machine dry outputs are rendered;
2. a Vocoder can read an available machine output, with previous-block data
   retained for ordering-dependent routes;
3. each slot's two inserts process in order;
4. the mixer strip applies EQ, stereo width, and pan;
5. processed lines are available to compressor sidechains;
6. audible channels feed the main, delay-send, and reverb-send buses;
7. master sends, inserts, EQ, limiter, volume, and clipping produce the result.

Stateful processors continue receiving blocks after notes end so delay, reverb,
filter, and dynamics tails decay correctly. Native active/tail state determines
when an idle room can stop rendering.

## Python/native boundary

The extension exposes a persistent room engine with operations for:

- graph synchronization;
- sample registration;
- slot-addressed note events and all-off/kill operations;
- one-call final block rendering;
- active/tail queries and meter snapshots.

The boundary validates dictionary fields and NumPy sample buffers before native
DSP begins. The render routine does not access Python objects while processing
samples and releases the GIL for the native hot path.

Each room graph creates a persistent native worker pool, capped by both the
configured render-thread count and the rack size. Independent non-Vocoder
machines render in parallel; Vocoders then render in rack order so current- and
previous-block modulator routing remains deterministic. Insert chains,
sidechains, mixing, sends, and mastering retain their required serial order.
Workers are created with the graph and reused for every block--no threads are
created in the hot path. Each graph selects its worker count from available
hardware concurrency and caps it to useful rack work.

`refrag_engine.create_room_engine(...)` is the only supported Python render
entry point. Machines, effects, samples, routing, and master processing are
configured through that persistent graph; standalone machine/effect renderers
and single-shot block helpers are intentionally not exposed.

Python may continue using NumPy/SciPy for non-render tasks such as sample asset
creation, AI-assisted analysis, test fixture generation, and final float-to-PCM
encoding. Machine synthesis, effects, channel processing, sends, mixing, and
mastering must not have Python fallbacks.

## Audio configuration and determinism

Sample rate and block size are native engine instance properties. Oscillator
increments, envelopes, filters, delay lengths, sample-rate conversion, and
effect timing derive from the configured rate rather than a fixed 44.1 kHz
constant.

Each stateful processor owns its own deterministic state. Noise-based machines
and effects use per-instance native generators so tests and offline rendering
are reproducible. Cross-slot dependencies are processed in a defined order;
parallel work is limited to independent operations that cannot change routing
or state order.

## Development requirements

The native extension must be rebuilt and reinstalled after any change under
`native/` so that tests never run against a stale binary:

```sh
python -m pip install .
```

Changes to render behavior should include graph-level tests for the relevant
machine or effect and for state continuity across blocks. The complete test
suite is:

```sh
python -m unittest discover -s tests -v
python native/tests/test_native_engine.py
```

Factory presets, non-default sample rates and block sizes, live and scheduled
notes, routing, tails, meters, streaming, and offline export are all expected to
exercise the native graph. A structural regression test ensures Python makes
one native room render call per output block and performs no intermediate
machine/effect/mixer NumPy processing.
