# Refrag Sound Engine Architecture

The Refrag audio system uses a native C++ core compiled as a Python extension 
module named `refrag_engine`.

The Python server selects machines, maintains room state, schedules notes, and 
pushes block data to the browser. The native engine handles the hot path for
audio synthesis and mixing.

## High-Level Data Flow

The main flow is:
1. The server creates or updates machine objects for each rack slot.
2. The transport loop requests audio blocks for the room see (`AudioEngine / synth.py`).
3. The Python side prepares a float NumPy output buffer and param matrix.
4. The native engine renders directly into those arrays.
5. Audio is mixed and sent to connected browser clients.

## Python Server Integration

The server-side integration remains centered on the existing `server/synth.py` and `server/engine.py` modules.

### Server responsibilities

- maintain room state and machine definitions
- decide which instruments are active for the current block
- convert room data into a renderable parameter matrix
- call the native rendering entry point
- aggregate audio for the full room

### Native module responsibilities

- create machine instances from Python dict metadata
- maintain voice state and per-machine parameters
- render one block of samples into a provided buffer
- expose audio data in a format the Python layer already understands

The key API is:

```python
import refrag_engine

refrag_engine.render_block(output_buffer, param_matrix)
```

and machine objects are created through:

```python
engine = refrag_engine.create_machine(machine_dict)
```

This lets the Python server keep using normal dictionaries and NumPy arrays while the native layer handles the density-critical sample work.

## Component Relationship Diagram

```text
+-----------------------+
| server/engine.py      |
| - render_block()      |
| - handle_note()       |
| - schedule automation |
+----------+------------+
           |
           v
+----------+------------+
| server/synth.py        |
| - create_machine()     |
| - machine metadata     |
| - native bridge        |
+----------+------------+
           |
           v
+----------+------------+
| pybind11 C++ module    |
| refrag_engine          |
| - MachineEngine        |
| - render_block()       |
+----------+------------+
           |
           v
+----------+------------+
| Native DSP Core        |
| - voice state          |
| - oscillator graphs    |
| - envelopes            |
| - filter/mix stages    |
+-----------------------+
```

## Native Engine Structure

The native code creates a `MachineEngine` object for each runtime machine instance. Each machine owns:

- a machine type (subsynth, bassline, padsynth, etc.)
- a parameter block
- a tracked set of active voices
- phase state for oscillators and modulation
- release/decay logic for note tails

The render call path is intentionally narrow:

```text
render_block(output_buffer, param_matrix)
        |
        v
validate NumPy arrays
        |
        v
iterate rows / instrument entries
        |
        v
fill stereo output directly
        |
        v
return to Python server
```

This is the path used to avoid layer-by-layer copying between Python and C++.

## Zero-Copy Conventions

The render path writes directly into the preallocated NumPy memory owned by the Python caller.

- the output buffer is passed into the native routine as `py::array_t<float, py::array::c_style | py::array::forcecast>`
- the native layer reads `output_buffer.mutable_data()`
- samples are written directly to those memory addresses
- no extra heap allocations or temporary arrays are created in the hot render path

This keeps the host/device memory boundary narrow and avoids churn that would otherwise hurt real-time performance.

## Worker Model and Thread Coordination

The engine is designed around a fixed thread pool initialized once per process. Each worker thread lives for the application lifetime and waits on lightweight atomic signaling rather than mutex-based blocking.

Core parts of the design:

- fixed worker count based on hardware concurrency
- dedicated task slots per worker
- atomic-ready / atomic-done flags
- spin-wait / atomic polling for the render loop
- no standard mutex locking in the per-block render path

```text
+----------------------------+
| Main Python / server thread |
| render_block() request      |
+-------------+--------------+
              |
              v
+-------------+--------------+
| Native render dispatcher    |
| split work across workers   |
| arm atomic task slots       |
+-------------+--------------+
              |
              v
+-----------------------------+
| Worker threads              |
| - fetch assigned voices     |
| - render per machine state  |
| - write scratch channel     |
| - signal completion         |
+--------------+--------------+
               |
               v
+--------------+---------------+
| Main thread                  |
| aggregate scratch buffers    |
| write final stereo mix       |
+------------------------------+
```

The design intentionally favors deterministic real-time execution over flexible task scheduling. The goal is to keep the audio callback path static, small, and safe for live performance.

## Synthesis Core and Voice Model

The native engine uses a compact value-based voice model. Each voice contains its own incremental oscillator phase, envelope state, start offset, and note lifecycle markers.

This keeps the internal DSP graph compact and cache-friendly:

- each voice is a small object
- its state is passed by value in the local render work
- phase and filter state remain independent between voices and threads
- synthesis kernels operate on fixed, preallocated state rather than dynamically resized containers

For example, the engine tracks:

- note frequency / pitch
- amplitude envelope
- pan and output gain
- per-voice sample generation state
- release tail state for note-off processing

## Parameter Flow

The parameter matrix is read at render time, so parameter changes do not require recompiling synthesis graphs.

Each block reads values such as:

- frequency / note data
- cutoff / resonance
- volume / gain
- wave shape and algorithm selections
- modulator values and detune controls

This means runtime edits can flow from the room state into the DSP without rebuilding static graphs.

## Why This Fits Refrag

Refrag is a collaborative rack-based DAW with multiple simultaneous instruments, automation, and transport-driven block generation. The new engine fits that model because it keeps the server-side orchestration logic intact while moving the heavy audio work into a compact and predictable native code path.

The main benefits are:

- faster low-level synthesis than Python loops
- lower per-block overhead in the audio path
- better fit for multi-machine live performance
- consistent interaction with NumPy-based Python data structures
- maintainability through a narrower boundary between orchestration and DSP

## Summary

The new sound engine is a hybrid architecture:

- the Python server still owns room state, scheduling, and UI integration
- the native C++ module owns the hot render loop and voice synthesis
- pybind11 bridges Python and C++ without losing the direct NumPy memory model
- the fixed worker pool and atomic signaling keep the render path low-latency and allocation-free

This gives Refrag a more efficient, more scalable synthesis core without sacrificing the existing collaborative server architecture.
