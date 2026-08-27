# AGENTS.md — Refrag

Guidance for AI coding agents working in this repository.

## Project Overview

Refrag is a collaborative, rack-based virtual DAW inspired by Caustic 3.1.
Audio is synthesized on the Python server and streamed to browsers in shared
rooms. Machine controls, patterns, transport, mixer state, effects, and
automation are synchronized over WebSockets and persisted as room snapshots.

## Tech Stack

- **Server**: Python 3.11+, `aiohttp` (web server + WebSockets), `numpy`/`scipy` (DSP)
- **Client**: Dependency-free vanilla HTML/CSS/JS (`web/`), with an AudioWorklet (`web/worklet.js`)
- **No frontend build step** — edit files in `web/` directly; no bundler, no npm.

## Commands

```sh
# Install dependencies
python -m pip install -r requirements.txt

# Run the server (serves web app on http://localhost:8000)
./start.sh          # or: start.bat on Windows
# Custom port: set REFRAG_PORT env var before launching

# Run tests
python -m unittest discover -s tests -v
```

There is no linter/formatter configured; match the existing code style.

## Repository Layout

```
server/
  app.py             # HTTP + WebSocket server, room API, transport clock, WAV export
  state.py           # Collaborative room state, JSON persistence to data/sessions/
  synth.py           # Audio rendering for all 11 machine families
  effects.py         # The 16 insert effects
  engine.py          # Sequencer, mixer, master chain
  catalog.py         # Control definitions for all rack devices
  samples.py         # Procedural generation of factory drum kit / instrument samples / vocoder loops
  factory_presets.py # Factory preset definitions (data/presets/)
web/
  index.html, style.css, worklet.js
  js/app.js, audio.js, editors.js, machines.js, mixer.js, util.js
data/
  presets/           # Factory presets as JSON, one dir per machine family
  sessions/          # Persisted room snapshots (runtime artifacts, don't hand-edit)
  samples/           # Generated sample data
tests/               # unittest-based test suite
doc/user-guide.md    # Full user manual
```

## Architecture Notes

- **State flow**: browser → WebSocket → `state.py` (room state) → `engine.py`/`synth.py` render → streamed audio back to all clients.
- **Single source of truth** for device controls is `server/catalog.py`. When adding a control, update the catalog first; the web UI reads control metadata from it.
- **Machine families** (11): bassline, beatbox, bitsynth, fmsynth, kssynth, modular, organ, padsynth, pcmsynth, subsynth, vocoder. Each has presets under `data/presets/<family>/`.
- **Effects** (16 insert effects) live in `server/effects.py`; each channel has two insert slots plus a master section.
- Room snapshots are written to `data/sessions/*.json` on change. Treat these as runtime data.

## Conventions

- Server code: standard library style, type hints where practical, no external frameworks beyond aiohttp/numpy/scipy.
- Client code: plain ES modules, no transpilation, no dependencies.
- Presets are JSON files with human-readable names (spaces allowed in filenames).
- Tests use `unittest` (not pytest). Add tests under `tests/test_*.py`.

## When Making Changes

1. **New machine control / parameter**: add to `server/catalog.py`, wire into the relevant renderer in `server/synth.py` (or `effects.py`), and ensure the client editor renders it (usually automatic via catalog).
2. **New effect**: implement in `server/effects.py`, register in the effect list/catalog, verify it appears in both insert slots and master chain.
3. **DSP changes**: keep rendering deterministic per tick; be mindful of real-time performance (numpy vectorized ops preferred over Python loops).
4. **Protocol changes** (WebSocket messages): update both `server/app.py` and `web/js/audio.js`/`app.js` together.
5. **Run the test suite** after changes: `python -m unittest discover -s tests -v`.
6. Do not commit changes to `data/sessions/` room files created during local testing.

## Testing Notes

- `tests/test_synth.py` covers machine rendering; `test_effects` behavior is exercised via engine/synth tests.
- `tests/test_state.py` covers persistence and room state.
- `tests/test_catalog.py` validates control definitions consistency.
- `tests/test_upload.py` and `tests/test_factory_presets.py` cover uploads and preset integrity (all presets must load cleanly).
