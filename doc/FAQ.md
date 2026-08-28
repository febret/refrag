# Refrag FAQ


## What is Refrag?
Refrag is a collaborative, rack-based sound generator, sequencer and looper 
inspired by Caustic 3.1.
Audio is synthesized on the Python server and streamed to browser clients in 
shared rooms. Machine controls, patterns, transport, mixer state, effects, and 
automation are synchronized over WebSockets and persisted as room snapshots.


## What is Caustic?
Caustic is an awesome and sadly abandoned Eurorack-style music studio for Android.


## What are the main components of the project?
Refrag has four conceptual layers that work together:

- Room and session logic: the shared state model for machines, patterns, transport, automation, and mixer configuration. This is the “live DAW state” that users edit and that gets persisted between sessions.
- Audio synthesis engine: the part that turns the room state into sound. This includes voice generation, machine-specific DSP behavior, synth parameter mapping, and the timing of notes and automation.
- Effect and mixer pipeline: the signal path between machines, channels, inserts, sends, and the master bus. This is where dynamics, filtering, spatial treatment, and final output shaping happen.
- Client/server integration: the browser UI and transport layer that let users edit the room, while the server stays authoritative on state and audio generation. The browser is mostly an interface; the server owns the actual room model and render loop.

The project is organized around those layers, with the server and native engine handling the audio and state logic, and the browser client providing control and visualization. The result is a collaborative room-based synth environment rather than a single monolithic app or a plain DSP library.


## Why does Refrag have a custom native engine instead of using a third-party DSP library?

Refrag is a machine/effect engine, not a DSP chain. Each machine has custom voice state, modulation behavior, note semantics, and parameter mapping. Effects are part of the room routing/mixer graph, and the engine also coordinates transport, automation, sidechains, snapshots, and low-latency render work.

A generic DSP library can provide good oscillators, filters, envelopes, and delays, but it does not replace the architecture that makes Refrag behave like a rack-based DAW. The project’s custom native code is where exact room semantics and performance tuning live.

The engine is intentionally designed to be visible and fully tunable rather than hidden behind a generic DSP abstraction.
This project is also a personal experiment in AI-driven low-latency, multicore C++ optimization.
