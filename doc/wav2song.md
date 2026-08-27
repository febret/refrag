# wav2song — WAV loop to refrag song

`tools/wav2song.py` analyzes a WAV music loop and generates a refrag song: a
room session JSON with machines, presets, patterns, mixer settings and a song
arrangement that approximates the input. The result is written to
`data/sessions/` and can be opened in the web UI by loading the room with the
session's name.

```sh
python tools/wav2song.py myloop.wav -o myloop --report
# then open http://localhost:8000 and join room "myloop"
```

The first pitched-transcription run downloads the small Basic Pitch ONNX
model (~230 KB) into `data/models/`.

## How it works

1. **Tempo detection** — an onset-flux autocorrelation proposes tempo
   candidates (metrical octaves are folded into a useful range); each is
   refined by fitting the onsets to a 16th-note grid. The best-scoring
   tempo + grid offset wins.
2. **Transcription** — drums are detected with a DSP onset classifier and
   mapped to the 8 beatbox channels; pitched material is transcribed with
   Basic Pitch on band-split copies of the signal (bass / chords / highs).
3. **Drone detection** — spectral peaks of the *median* spectrum over time
   (robust against transients) become sustained pad chords, split across up
   to two padsynth machines to respect their 8-voice polyphony.
4. **Song assembly** — a beatbox, a subsynth bass, subsynth chord/high
   layers and the padsynth drones are configured, and patterns + song
   blocks are laid out to cover the clip.
5. **Musical simplification** — note starts are quantized to the grid,
   durations get sensible minimums, repeated fragments merge into sustained
   notes, simultaneous notes group into chords, and repeating content
   collapses into short (1/2/4-measure) looping patterns.
6. **Auto-balance** — the song is rendered offline and compared with the
   input on a 64-band log-mel spectrogram; per-layer gains are nudged
   toward the input's band energies for a few iterations, keeping the
   best-scoring result.

## CLI options

| Option | Description |
|---|---|
| `input` | Input `.wav` file (16/24-bit PCM or 8-bit; any rate/channels). Clips longer than 30 s are analyzed on the first 30 s. |
| `-o`, `--output NAME` | Session name, or an explicit `.json` path. Default: the input file stem, written to `data/sessions/`. |
| `--cfg YAML` | Extended configuration file; see below. |
| `--dump-cfg` | Print the effective configuration as YAML and exit (works with `--cfg` to inspect merged values). |
| `--bpm F` | Fix the tempo instead of detecting it. |
| `--tune N` | Auto-balance iterations (default 2; `0` disables). |
| `--no-simplify` | Keep raw transcription timing; skips quantization, chords and loop building. |
| `--no-drums` / `--no-bass` / `--no-chords` / `--no-drones` | Drop a layer. `--no-chords` also drops the highs layer. |
| `--max-chord N` | Maximum simultaneous notes per chord (default 5). |
| `--render WAV` | Also write the rendered song audio. |
| `--report` | Print the final similarity score (0..1, log-mel cosine). |
| `--quiet` | Suppress progress output. |

Precedence: built-in defaults < `--cfg` file < explicit CLI flags.

## Configuration file (`--cfg`)

The YAML file is deep-merged over the defaults, so only the keys you want to
change need to be present. Unknown keys are rejected with an error (typos
fail loudly). Run `python tools/wav2song.py --dump-cfg` to see all defaults
in valid YAML — that output is a good starting template.

Example:

```yaml
tempo:
  bpm: 95.5              # skip detection
simplify:
  max_chord: 4
layers:
  highs:
    enabled: false
  bass:
    params:              # any subsynth catalog param
      flt_cutoff: 0.3
      volume: 0.9
  drones:
    group_size: 5
tune:
  rounds: 3
```

### `tempo` — tempo & grid detection

| Key | Default | Description |
|---|---|---|
| `bpm` | `null` | Fixed tempo; `null` = autodetect. |
| `candidates` | `5` | Autocorrelation tempo candidates to evaluate. |
| `min_bpm` / `max_bpm` | `60 / 200` | Candidate search range. |
| `fold_low` / `fold_high` | `70 / 190` | Candidates are octave-folded (×2 / ÷2) into this range. |
| `fit_range` | `3.0` | ± BPM refined around each candidate. |
| `fit_step` | `0.02` | BPM resolution of the grid fit. |
| `offset_steps` | `20` | Grid-offset positions tested per 16th note. |

### `grid` — note grid & velocities

| Key | Default | Description |
|---|---|---|
| `step` | `0.25` | Base grid in beats (0.25 = 16th notes). |
| `vel_levels` | `[0.4, 0.6, 0.8, 1.0]` | Quantized velocity levels. |
| `vel_floor` | `0.5` | Transcription amplitude → velocity mapping floor. |

### `simplify` — musical simplification

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master switch (CLI: `--no-simplify`). |
| `max_chord` | `5` | Max simultaneous notes per chord. |
| `pitched_grid` | `0.5` | Quantization grid for chord-type layers (beats). |
| `min_dur` | `{bass: 0.5, chord: 1.0}` | Minimum note durations (beats) per layer mode. |
| `loop_lengths` | `[4, 8, 16]` | Candidate loop lengths in beats, tried smallest first. |
| `loop_coverage` | `0.6` | Fraction of notes a loop must explain to be accepted. |
| `loop_precision` | `0.4` | Fraction of predicted loop hits that must exist in the source. |
| `loop_min_instances` | `0.6` | Fraction of loop instances a note must appear in to enter the consensus. |
| `chunk_measures` | `4` | Fallback pattern size (measures) when no loop fits. |
| `raw_chunk_measures` | `8` | Pattern size when simplification is disabled. |

### `layers.drums`

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | CLI: `--no-drums`. |
| `snare_offbeat_to_hat` | `true` | Reclassify snare hits away from beats 2/4 as closed hats. |
| `offbeat_tolerance` | `0.3` | Distance (beats) from 2/4 before reclassifying. |
| `kit` | `[kick, snare, clhat, ophat, clap, tom_lo, tom_hi, crash]` | Sample per beatbox channel. |
| `channel_volumes` | `[1.3, 0.9, …]` | Per-channel volume. |
| `channel_punch` | `[0.3, 0, …]` | Per-channel punch. |
| `params` / `mixer` | `{}` / `{eq_high: 0.2}` | Beatbox machine param / mixer-strip overrides. |

### `layers.bass`, `layers.chords`, `layers.highs`

| Key | Default (bass) | Description |
|---|---|---|
| `enabled` | `true` | CLI: `--no-bass`; `--no-chords` disables chords **and** highs. |
| `band` | `[0, 260]` | Band-pass (Hz) applied before transcription; `null` = full bandwidth. |
| `note_range` | `[24, 59]` | Accepted MIDI note range. |
| `dur_scale` | `1.0` | Multiplier on transcribed note durations. |
| `params` | subsynth patch | Any subsynth catalog param (waveforms, filter, envelopes, `volume`, …). |
| `mixer` | `{eq_bass: 0.2}` | Mixer-strip overrides (`volume`, `pan`, `eq_*`, sends, …). |

Chords default to `band: [200, 2200]`, `note_range: [48, 127]`,
`dur_scale: 1.2`; highs to `band: null`, `note_range: [76, 127]`.

### `layers.drones` — sustained pad detection

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | CLI: `--no-drones`. |
| `max_notes` | `12` | Spectral peaks kept for the stack. |
| `freq_range` | `[80, 4000]` | Peak search range (Hz). |
| `prominence_db` | `6.0` | Peak prominence threshold. |
| `vel_db_range` | `24.0` | Peaks this many dB below the top map to the minimum velocity. |
| `group_size` | `6` | Notes per padsynth machine (8-voice polyphony headroom). |
| `max_machines` | `2` | Maximum drone machines. |
| `note_beats` | `4.0` | Length of each repeated drone chord (beats). |
| `harmonics` | 24 values | Padsynth harmonic table. |
| `width` | `0.35` | Padsynth harmonic width. |
| `params` / `mixer` | pad patch / `{}` | Padsynth param / mixer overrides. |

### `tune` — auto-balance

| Key | Default | Description |
|---|---|---|
| `rounds` | `2` | Iterations (CLI: `--tune N`; `0` disables). The best-scoring iteration is kept. |
| `max_gain_db` | `6.0` | Per-iteration gain change clamp. |
| `volume_min` / `volume_max` | `0.05 / 2.0` | Machine volume clamps. |
| `kick_band_hz` | `120.0` | Mel bands below this drive the kick-channel gain. |
| `register_low_ratio` / `register_high_ratio` | `0.5 / 6.0` | How far below/above a machine's note range its "register" extends when attributing band energy. |

### `score` — similarity metric

| Key | Default | Description |
|---|---|---|
| `n_mels` | `64` | Mel bands. |
| `fmin` / `fmax` | `30 / 16000` | Mel range (Hz). |
| `nperseg` / `hop` | `2048 / 1024` | STFT window / hop (samples at 44.1 kHz). |

The score is the mean per-frame cosine similarity between log-mel
spectrogram frames of the input and the rendered song (1.0 = identical,
uncorrelated noise scores ≈ 0.3).

## Tips

- If the drum layer sounds too busy, raise `layers.drums.offbeat_tolerance`
  or disable `snare_offbeat_to_hat`.
- For material without a sustained pad, `--no-drones` avoids smearing
  percussive content into chords.
- `--tune 3`–`4` can help difficult mixes; each round renders the whole
  song, so it costs time.
- `--render out.wav --report` gives a quick way to listen to and grade the
  result without starting the server.
