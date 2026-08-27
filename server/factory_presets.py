"""Factory starter presets for every Refrag machine.

Presets are installed as JSON files under data/presets/<machine>/ at server
startup.  Existing files are never overwritten, so users can tweak or replace
factory presets freely.  Each preset only lists the parameters that differ
from the machine defaults; Room.load_preset merges them over the defaults.
"""

import json
import os

from . import catalog
from .state import PRESET_DIR, _safe_name

# ---------------------------------------------------------------------------
# Preset tables: {machine_type: {preset_name: data}}
# data = {"params": {...}, plus optional extras (channels, samples, harm1/2,
#         expr_a/b, components, wires, modulators, poly)}
# ---------------------------------------------------------------------------

PRESETS = {
    # -- SubSynth ------------------------------------------------------------
    "subsynth": {
        "Fat Bass": {
            "params": {"osc1_wave": 2, "osc2_wave": 4, "osc_mix": 0.35,
                       "osc2_octave": -1, "detune_mode": 1, "osc2_cents": 8,
                       "flt_type": 1, "flt_cutoff": 0.42, "flt_res": 0.35,
                       "flt_decay": 0.35, "flt_sustain": 0.25,
                       "vol_decay": 0.4, "vol_sustain": 0.75,
                       "vol_release": 0.12}},
        "Warm Pad": {
            "params": {"osc1_wave": 2, "osc2_wave": 3, "osc_mix": 0.5,
                       "detune_mode": 1, "osc2_cents": 14, "flt_type": 1,
                       "flt_cutoff": 0.55, "flt_res": 0.15,
                       "lfo1_target": 4, "lfo1_rate": 0.4, "lfo1_depth": 0.25,
                       "vol_attack": 0.45, "vol_sustain": 0.9,
                       "vol_release": 0.55}},
        "Pluck Lead": {
            "params": {"osc1_wave": 4, "osc2_wave": 3, "osc_mix": 0.4,
                       "osc2_semis": 12, "flt_type": 1, "flt_cutoff": 0.5,
                       "flt_res": 0.45, "flt_decay": 0.28, "flt_sustain": 0.1,
                       "vol_decay": 0.45, "vol_sustain": 0.0,
                       "vol_release": 0.25}},
        "Glide Lead": {
            "params": {"osc1_wave": 2, "osc2_wave": 4, "osc_mix": 0.45,
                       "bend": 0.35, "detune_mode": 1, "osc2_cents": 10,
                       "flt_type": 1, "flt_cutoff": 0.7, "flt_res": 0.3,
                       "vol_attack": 0.05, "vol_sustain": 0.85,
                       "vol_release": 0.2}},
        "Hollow Keys": {
            "params": {"osc1_wave": 1, "osc2_wave": 7, "osc_mix": 0.5,
                       "osc2_octave": 1, "flt_type": 1, "flt_cutoff": 0.75,
                       "vol_decay": 0.55, "vol_sustain": 0.35,
                       "vol_release": 0.3}},
        "FM Bell": {
            "params": {"osc1_wave": 0, "osc2_wave": 1, "osc_mod": 0.45,
                       "mod_mode": 0, "osc2_octave": 2, "osc2_semis": 7,
                       "flt_type": 0, "vol_decay": 0.7, "vol_sustain": 0.0,
                       "vol_release": 0.6}},
        "Wobble Bass": {
            "params": {"osc1_wave": 2, "osc2_wave": 4, "osc_mix": 0.4,
                       "osc2_octave": -1, "flt_type": 1, "flt_cutoff": 0.45,
                       "flt_res": 0.55, "lfo1_target": 4, "lfo1_wave": 0,
                       "lfo1_rate": 4.0, "lfo1_depth": 0.6,
                       "vol_sustain": 0.9, "vol_release": 0.1}},
        "Airy Strings": {
            "params": {"osc1_wave": 2, "osc2_wave": 3, "osc_mix": 0.5,
                       "detune_mode": 1, "osc2_cents": 18, "flt_type": 1,
                       "flt_cutoff": 0.62, "lfo1_target": 3, "lfo1_wave": 0,
                       "lfo1_rate": 5.5, "lfo1_depth": 0.04,
                       "vol_attack": 0.35, "vol_sustain": 1.0,
                       "vol_release": 0.45}},
    },

    # -- PCMSynth ------------------------------------------------------------
    "pcmsynth": {
        "Grand Piano": {
            "params": {"vol_release": 0.15},
            "samples": [{"sample": "piano", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 60, "low": 0, "high": 127, "mode": 0,
                         "start": 0.0, "end": 1.0}]},
        "Soft E-Piano": {
            "params": {"flt_type": 1, "flt_cutoff": 0.75, "vol_release": 0.2},
            "samples": [{"sample": "epiano", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 60, "low": 0, "high": 127, "mode": 0,
                         "start": 0.0, "end": 1.0}]},
        "String Ensemble": {
            "params": {"vol_attack": 0.25, "vol_release": 0.4},
            "samples": [{"sample": "strings", "level": 1.0, "tune": 0,
                         "pan": 0.0, "root": 60, "low": 0, "high": 127,
                         "mode": 2, "start": 0.35, "end": 0.9}]},
        "Choir Aahs": {
            "params": {"vol_attack": 0.35, "vol_release": 0.5,
                       "flt_type": 1, "flt_cutoff": 0.7},
            "samples": [{"sample": "choir", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 60, "low": 0, "high": 127, "mode": 2,
                         "start": 0.3, "end": 0.9}]},
        "Finger Bass": {
            "params": {"flt_type": 1, "flt_cutoff": 0.55, "vol_release": 0.1},
            "samples": [{"sample": "bass", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 36, "low": 0, "high": 127, "mode": 0,
                         "start": 0.0, "end": 1.0}]},
        "Lead Flute": {
            "params": {"vol_attack": 0.12, "vol_release": 0.25,
                       "lfo_target": 1, "lfo_rate": 5.0, "lfo_depth": 0.02},
            "samples": [{"sample": "flute", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 72, "low": 0, "high": 127, "mode": 2,
                         "start": 0.35, "end": 0.9}]},
        "Piano + Strings": {
            "params": {"vol_release": 0.3},
            "samples": [{"sample": "piano", "level": 0.9, "tune": 0, "pan": -0.2,
                         "root": 60, "low": 0, "high": 63, "mode": 0,
                         "start": 0.0, "end": 1.0},
                        {"sample": "strings", "level": 0.8, "tune": 0,
                         "pan": 0.2, "root": 60, "low": 64, "high": 127,
                         "mode": 2, "start": 0.35, "end": 0.9}]},
        "Wobble Sample": {
            "params": {"flt_type": 1, "flt_cutoff": 0.5, "flt_res": 0.5,
                       "lfo_target": 2, "lfo_rate": 4.0, "lfo_depth": 0.5},
            "samples": [{"sample": "choir", "level": 1.0, "tune": 0, "pan": 0.0,
                         "root": 60, "low": 0, "high": 127, "mode": 2,
                         "start": 0.3, "end": 0.9}]},
    },

    # -- BassLine ------------------------------------------------------------
    "bassline": {
        "Classic Acid": {
            "params": {"wave": 0, "cutoff": 0.38, "res": 0.75, "env_mod": 0.7,
                       "decay": 0.32, "accent": 0.7}},
        "Square Squelch": {
            "params": {"wave": 1, "pulse_width": 0.35, "cutoff": 0.42,
                       "res": 0.8, "env_mod": 0.65, "decay": 0.25,
                       "accent": 0.6}},
        "Deep Sub": {
            "params": {"wave": 0, "tune": -12, "cutoff": 0.3, "res": 0.2,
                       "env_mod": 0.25, "decay": 0.5}},
        "Distorted 303": {
            "params": {"wave": 0, "cutoff": 0.4, "res": 0.7, "env_mod": 0.65,
                       "decay": 0.3, "accent": 0.8, "dist_program": 1,
                       "dist_pre": 1.8, "dist_amount": 0.55,
                       "dist_post": 0.8}},
        "Fuzz Lead": {
            "params": {"wave": 1, "pulse_width": 0.45, "tune": 12,
                       "cutoff": 0.6, "res": 0.5, "env_mod": 0.4,
                       "decay": 0.45, "dist_program": 4, "dist_pre": 1.4,
                       "dist_amount": 0.5, "dist_post": 0.7}},
        "Rubber Bass": {
            "params": {"wave": 0, "cutoff": 0.5, "res": 0.55, "env_mod": 0.5,
                       "decay": 0.2, "lfo_target": 1, "lfo_rate": 6.0,
                       "lfo_depth": 0.12}},
        "Slow Wobble": {
            "params": {"wave": 1, "pulse_width": 0.4, "cutoff": 0.35,
                       "res": 0.65, "env_mod": 0.3, "decay": 0.6,
                       "lfo_target": 1, "lfo_rate": 1.5, "lfo_depth": 0.45}},
    },

    # -- BeatBox -------------------------------------------------------------
    # channel order: [sample, tune, punch, decay, pan, volume, mute_group]
    "beatbox": {
        "Standard Kit": {"params": {}, "kit": [
            ("kick", 0, 0, 1, 0.0, 1.1, 0), ("snare", 0, 0, 1, 0.0, 0.95, 0),
            ("clhat", 0, 0, 1, -0.25, 0.75, 1), ("ophat", 0, 0, 1, 0.25, 0.7, 1),
            ("clap", 0, 0, 1, 0.1, 0.85, 0), ("tom_lo", 0, 0, 1, -0.35, 0.85, 0),
            ("tom_hi", 0, 0, 1, 0.35, 0.85, 0), ("crash", 0, 0, 1, 0.0, 0.7, 0)]},
        "Tight Electro": {"params": {}, "kit": [
            ("kick", 2, 0, 0.45, 0.0, 1.15, 0), ("snare", 3, 0.05, 0.4, 0.0, 0.9, 0),
            ("clhat", 4, 0, 0.3, -0.3, 0.7, 1), ("ophat", 2, 0, 0.5, 0.3, 0.6, 1),
            ("clap", 0, 0, 0.5, 0.0, 0.9, 0), ("tom_lo", 4, 0, 0.4, -0.4, 0.8, 0),
            ("tom_hi", 4, 0, 0.4, 0.4, 0.8, 0), ("crash", 0, 0, 0.6, 0.0, 0.55, 0)]},
        "Boomy Hip-Hop": {"params": {}, "kit": [
            ("kick", -3, 0, 1, 0.0, 1.2, 0), ("snare", -2, 0.1, 0.8, 0.0, 0.9, 0),
            ("clhat", -2, 0, 0.6, -0.2, 0.65, 1), ("ophat", -3, 0, 0.8, 0.2, 0.6, 1),
            ("clap", -1, 0.05, 0.9, 0.0, 0.8, 0), ("tom_lo", -4, 0, 0.9, -0.3, 0.85, 0),
            ("tom_hi", -2, 0, 0.9, 0.3, 0.85, 0), ("crash", -2, 0, 1, 0.0, 0.6, 0)]},
        "Soft Percussion": {"params": {}, "kit": [
            ("kick", 0, 0.25, 0.7, 0.0, 0.9, 0), ("snare", 2, 0.3, 0.6, 0.0, 0.7, 0),
            ("clhat", 0, 0.2, 0.5, -0.35, 0.55, 1), ("ophat", 0, 0.15, 0.7, 0.35, 0.5, 1),
            ("clap", 3, 0.3, 0.6, 0.15, 0.6, 0), ("tom_lo", 0, 0.2, 0.8, -0.45, 0.75, 0),
            ("tom_hi", 0, 0.2, 0.8, 0.45, 0.75, 0), ("crash", 0, 0.2, 1, 0.0, 0.5, 0)]},
        "Pitched Toms": {"params": {}, "kit": [
            ("kick", 0, 0, 1, 0.0, 1.05, 0), ("tom_lo", -5, 0, 1, -0.5, 0.9, 0),
            ("tom_lo", 0, 0, 1, -0.2, 0.9, 0), ("tom_hi", -2, 0, 1, 0.2, 0.9, 0),
            ("tom_hi", 3, 0, 1, 0.5, 0.9, 0), ("clhat", 0, 0, 0.6, -0.3, 0.6, 1),
            ("ophat", 0, 0, 0.8, 0.3, 0.55, 1), ("crash", 0, 0, 1, 0.0, 0.6, 0)]},
    },

    # -- PadSynth ------------------------------------------------------------
    "padsynth": {
        "Glass Choir": {
            "params": {"vol_attack": 0.45, "vol_release": 0.6, "morph": 0.3,
                       "lfo1_target": 3, "lfo1_rate": 0.3, "lfo1_depth": 0.15},
            "harm1": [1, 0, 0.5, 0, 0.32, 0, 0, 0.2, 0, 0, 0.12, 0, 0, 0, 0.08,
                      0, 0, 0, 0, 0, 0, 0, 0, 0],
            "harm2": [1, 0.6, 0.4, 0.32, 0.24, 0.2, 0.16, 0.12, 0.1, 0.08,
                      0.06, 0.05, 0.04, 0.04, 0.03, 0.03, 0.02, 0.02, 0.02,
                      0.01, 0.01, 0.01, 0.01, 0.01],
            "width1": 0.45, "width2": 0.3},
        "Dark Drone": {
            "params": {"vol_attack": 0.6, "vol_release": 0.7, "morph": 0.5,
                       "morph_env": 1, "morph_attack": 0.7,
                       "morph_sustain": 1.0},
            "harm1": [1, 0.8, 0.2, 0.1, 0.05, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      0, 0, 0, 0, 0, 0, 0, 0],
            "harm2": [0.3, 1, 0.1, 0.6, 0.05, 0.35, 0, 0.2, 0, 0.1, 0, 0.06,
                      0, 0.04, 0, 0.02, 0, 0, 0, 0, 0, 0, 0, 0],
            "width1": 0.6, "width2": 0.55},
        "Bell Wash": {
            "params": {"vol_attack": 0.15, "vol_decay": 0.6,
                       "vol_sustain": 0.5, "vol_release": 0.7},
            "harm1": [1, 0, 0, 0.7, 0, 0, 0.45, 0, 0, 0, 0.3, 0, 0, 0, 0, 0.2,
                      0, 0, 0, 0, 0, 0.1, 0, 0],
            "harm2": [1, 0, 0.4, 0, 0.25, 0, 0.15, 0, 0.1, 0, 0, 0, 0, 0, 0,
                      0, 0, 0, 0, 0, 0, 0, 0, 0],
            "width1": 0.2, "width2": 0.35},
        "Morphing Sweep": {
            "params": {"morph_env": 1, "morph": 1.0, "morph_attack": 0.55,
                       "morph_decay": 0.5, "morph_sustain": 0.3,
                       "morph_release": 0.5, "vol_attack": 0.3,
                       "vol_release": 0.5},
            "harm1": [1, 0.5, 0.33, 0.25, 0.2, 0.17, 0.14, 0.13, 0.11, 0.1,
                      0.09, 0.08, 0.08, 0.07, 0.07, 0.06, 0.06, 0.06, 0.05,
                      0.05, 0.05, 0.05, 0.04, 0.04],
            "harm2": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      0, 0, 0, 0, 0],
            "width1": 0.35, "width2": 0.5},
        "Shimmer Pad": {
            "params": {"vol_attack": 0.4, "vol_release": 0.65,
                       "lfo1_target": 1, "lfo1_rate": 5.0, "lfo1_depth": 0.03,
                       "lfo2_target": 3, "lfo2_rate": 0.25,
                       "lfo2_depth": 0.2, "morph": 0.4},
            "harm1": [1, 0, 0.4, 0, 0, 0.5, 0, 0, 0, 0.3, 0, 0, 0, 0, 0.2, 0,
                      0, 0, 0, 0.12, 0, 0, 0, 0.08],
            "harm2": [0.7, 1, 0.5, 0.7, 0.3, 0.5, 0.2, 0.35, 0.15, 0.25, 0.1,
                      0.18, 0.08, 0.12, 0.06, 0.09, 0.04, 0.06, 0.03, 0.04,
                      0.02, 0.03, 0.02, 0.02],
            "width1": 0.5, "width2": 0.4},
    },

    # -- 8BitSynth -----------------------------------------------------------
    "bitsynth": {
        "Classic Chip Lead": {
            "params": {"blend": 0.0},
            "expr_a": "t*(42&t>>10)", "expr_b": "(t>>4)|(t<<2)"},
        "Gritty Engine": {
            "params": {"blend": 0.3, "octave": -1},
            "expr_a": "t*(t>>9|t>>13)&16", "expr_b": "t*5&(t>>7)"},
        "Laser Sweep": {
            "params": {"blend": 0.0, "octave": 1},
            "expr_a": "t*(t>>5|t>>8)>>(t>>16)", "expr_b": "t*(t>>11&t>>8&123)"},
        "Buzz Bass": {
            "params": {"blend": 0.5, "octave": -2},
            "expr_a": "t*3&(t>>6)", "expr_b": "t*2&(t>>5)|t*3&(t*4>>10)"},
        "Static Rhythm": {
            "params": {"blend": 0.25},
            "expr_a": "t*(t^t+(t%255|t+t)>>10|t>>6)",
            "expr_b": "(t*9&t>>4)|(t*5&t>>7)"},
        "Alien Talk": {
            "params": {"blend": 0.6},
            "expr_a": "t*(t>>((t>>12)%12)&31)", "expr_b": "t%(t>>8|t<<3)"},
    },

    # -- Modular -------------------------------------------------------------
    "modular": {
        "Basic Mono Synth": {
            "params": {},
            "components": [
                {"type": "oscillator", "params": {"wave": 2, "octave": 0,
                                                  "semis": 0, "cents": 0,
                                                  "fm_amt": 0}},
                "occupied",
                {"type": "filter", "params": {"type": 0, "cutoff": 0.6,
                                              "reso": 0.3, "mod_amt": 0.4}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.02, "decay": 0.3,
                                                "sustain": 0.7,
                                                "release": 0.15}},
                {"type": "vca", "params": {"gain": 1.0}},
                None, None],
            "wires": [["panel.note_cv", "c0.note"], ["c0.out", "c2.in"],
                      ["c4.out", "c2.mod"], ["c2.out", "c5.in"],
                      ["c4.out", "c5.mod"], ["c5.out", "panel.left_out"]]},
        "Wobble Machine": {
            "params": {},
            "components": [
                {"type": "oscillator", "params": {"wave": 2, "octave": -1,
                                                  "semis": 0, "cents": 0,
                                                  "fm_amt": 0}},
                "occupied",
                {"type": "lfo", "params": {"wave": 0, "rate": 3.0,
                                           "depth": 0.4}},
                {"type": "filter", "params": {"type": 0, "cutoff": 0.35,
                                              "reso": 0.55, "mod_amt": 0.8}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.0, "decay": 0.3,
                                                "sustain": 0.8,
                                                "release": 0.1}},
                {"type": "vca", "params": {"gain": 0.6}},
                None],
            "wires": [["panel.note_cv", "c0.note"], ["c0.out", "c3.in"],
                      ["c2.out", "c3.mod"], ["c3.out", "c6.in"],
                      ["c5.out", "c6.mod"], ["c6.out", "panel.left_out"]]},
        "FM Growl": {
            "params": {},
            "components": [
                {"type": "oscillator", "params": {"wave": 0, "octave": -1,
                                                  "semis": 0, "cents": 0,
                                                  "fm_amt": 0}},
                "occupied",
                {"type": "oscillator", "params": {"wave": 0, "octave": 0,
                                                  "semis": 7, "cents": 0,
                                                  "fm_amt": 0.5}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.01, "decay": 0.4,
                                                "sustain": 0.6,
                                                "release": 0.2}},
                {"type": "vca", "params": {"gain": 1.0}},
                {"type": "shaper", "params": {"drive": 0.35, "mode": 0}},
                None],
            "wires": [["panel.note_cv", "c0.note"], ["panel.note_cv", "c2.note"],
                      ["c0.out", "c2.fm"], ["c2.out", "c5.in"],
                      ["c4.out", "c5.mod"], ["c5.out", "c6.in"],
                      ["c6.out", "panel.left_out"]]},
        "Noise Sweep FX": {
            "params": {},
            "components": [
                {"type": "noise", "params": {"color": 0.2}},
                {"type": "lfo", "params": {"wave": 1, "rate": 0.4,
                                           "depth": 0.5}},
                {"type": "filter", "params": {"type": 2, "cutoff": 0.4,
                                              "reso": 0.7, "mod_amt": 0.9}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.5, "decay": 0.5,
                                                "sustain": 0.8,
                                                "release": 0.6}},
                {"type": "vca", "params": {"gain": 0.9}},
                None, None],
            "wires": [["c0.out", "c2.in"], ["c1.out", "c2.mod"],
                      ["c2.out", "c5.in"], ["c4.out", "c5.mod"],
                      ["c5.out", "panel.left_out"]]},
        "Echo Keys": {
            "params": {},
            "components": [
                {"type": "oscillator", "params": {"wave": 1, "octave": 0,
                                                  "semis": 0, "cents": 0,
                                                  "fm_amt": 0}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.0, "decay": 0.45,
                                                "sustain": 0.0,
                                                "release": 0.2}},
                {"type": "vca", "params": {"gain": 1.0}},
                {"type": "moddelay", "params": {"time": 0.4, "feedback": 0.45,
                                                "wet": 0.5}},
                None, None, None],
            "wires": [["panel.note_cv", "c0.note"], ["c0.out", "c3.in"],
                      ["c2.out", "c3.mod"], ["c3.out", "c4.in"],
                      ["c4.out", "panel.left_out"]]},
        "Random Bleeps": {
            "params": {},
            "components": [
                {"type": "samplehold", "params": {"rate": 8.0}},
                {"type": "oscillator", "params": {"wave": 4, "octave": 0,
                                                  "semis": 0, "cents": 0,
                                                  "fm_amt": 0.6}},
                "occupied",
                {"type": "envelope", "params": {"attack": 0.0, "decay": 0.2,
                                                "sustain": 0.6,
                                                "release": 0.1}},
                {"type": "vca", "params": {"gain": 0.8}},
                None, None, None],
            "wires": [["panel.note_cv", "c1.note"], ["c0.out", "c1.fm"],
                      ["c1.out", "c4.in"], ["c3.out", "c4.mod"],
                      ["c4.out", "panel.left_out"]]},
    },

    # -- Organ ---------------------------------------------------------------
    "organ": {
        "Full Drawbars": {
            "params": {"bar16": 0.9, "bar5_13": 0.7, "bar8": 0.9, "bar4": 0.75,
                       "bar2_23": 0.6, "bar2": 0.55, "bar1_35": 0.4,
                       "bar1_13": 0.35, "bar1": 0.3, "leslie_speed": 0.45,
                       "leslie_depth": 0.55}},
        "Jazz Trio": {
            "params": {"bar16": 0.85, "bar5_13": 0.6, "bar8": 0.8, "bar4": 0.0,
                       "bar2_23": 0.0, "bar2": 0.0, "bar1_35": 0.0,
                       "bar1_13": 0.0, "bar1": 0.0, "perc_tone": 0.7,
                       "perc_decay": 0.35, "leslie_speed": 0.3,
                       "leslie_depth": 0.5}},
        "Gospel Shout": {
            "params": {"bar16": 0.9, "bar5_13": 0.8, "bar8": 0.9, "bar4": 0.85,
                       "bar2_23": 0.8, "bar2": 0.8, "bar1_35": 0.75,
                       "bar1_13": 0.75, "bar1": 0.85, "leslie_speed": 0.85,
                       "leslie_depth": 0.65, "drive": 0.3}},
        "Mellow Flutes": {
            "params": {"bar16": 0.7, "bar5_13": 0.0, "bar8": 0.85, "bar4": 0.5,
                       "bar2_23": 0.0, "bar2": 0.2, "bar1_35": 0.0,
                       "bar1_13": 0.0, "bar1": 0.0, "leslie_speed": 0.2,
                       "leslie_depth": 0.35}},
        "Rock Organ": {
            "params": {"bar16": 0.9, "bar5_13": 0.75, "bar8": 0.9, "bar4": 0.8,
                       "bar2_23": 0.5, "bar2": 0.4, "bar1_35": 0.0,
                       "bar1_13": 0.0, "bar1": 0.6, "leslie_speed": 0.6,
                       "leslie_depth": 0.5, "drive": 0.55}},
        "Percussive Comp": {
            "params": {"bar16": 0.8, "bar5_13": 0.4, "bar8": 0.7, "bar4": 0.3,
                       "bar2_23": 0.35, "bar2": 0.0, "bar1_35": 0.0,
                       "bar1_13": 0.0, "bar1": 0.0, "perc_tone": 0.35,
                       "perc_decay": 0.5, "leslie_speed": 0.4,
                       "leslie_depth": 0.45}},
    },

    # -- Vocoder -------------------------------------------------------------
    "vocoder": {
        "Robot Voice": {
            "params": {"wave": 1, "unison": 0.15, "sub": 0.25, "noise": 0.08,
                       "slew": 0.2, "hf_bypass": 0.15},
            "modulators": [{"source": "vox_robot", "machine": -1},
                           {"source": "vox_vowels", "machine": -1},
                           {"source": "vox_rhythm", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1}]},
        "Vowel Choir": {
            "params": {"wave": 0, "unison": 0.35, "sub": 0.4, "noise": 0.03,
                       "slew": 0.5, "hf_bypass": 0.1, "band1": 0.8,
                       "band8": 1.3},
            "modulators": [{"source": "vox_vowels", "machine": -1},
                           {"source": "vox_robot", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1}]},
        "Rhythmic Gate": {
            "params": {"wave": 0, "unison": 0.25, "sub": 0.35, "noise": 0.0,
                       "slew": 0.05, "hf_bypass": 0.0},
            "modulators": [{"source": "vox_rhythm", "machine": -1},
                           {"source": "vox_vowels", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1}]},
        "Whisper Bot": {
            "params": {"wave": 1, "unison": 0.1, "sub": 0.1, "noise": 0.4,
                       "slew": 0.35, "hf_bypass": 0.3, "dry": 0.08},
            "modulators": [{"source": "vox_vowels", "machine": -1},
                           {"source": "vox_robot", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1}]},
        "Deep Announcer": {
            "params": {"wave": 0, "unison": 0.2, "sub": 0.6, "noise": 0.05,
                       "slew": 0.3, "band1": 1.5, "band2": 1.3, "band7": 0.7,
                       "band8": 0.6},
            "modulators": [{"source": "vox_robot", "machine": -1},
                           {"source": "vox_vowels", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1},
                           {"source": "", "machine": -1}]},
    },

    # -- FMSynth -------------------------------------------------------------
    "fmsynth": {
        "DX Keys": {
            "params": {"algorithm": 3, "op1_level": 0.55, "op1_octave": 2,
                       "op1_decay": 0.4, "op1_sustain": 0.2,
                       "op2_level": 0.9, "op2_decay": 0.6, "op2_sustain": 0.4,
                       "op2_release": 0.25, "op3_level": 0.35, "op3_octave": 1,
                       "op3_decay": 0.5, "op3_sustain": 0.3,
                       "op3_release": 0.25}},
        "Glass Bell": {
            "params": {"algorithm": 0, "op1_level": 0.5, "op1_octave": 2,
                       "op1_semis": 5, "op1_decay": 0.5, "op1_sustain": 0.0,
                       "op2_level": 0.6, "op2_decay": 0.6, "op2_sustain": 0.0,
                       "op3_level": 0.9, "op3_decay": 0.75, "op3_sustain": 0.0,
                       "op3_release": 0.6}},
        "Growl Bass": {
            "params": {"algorithm": 1, "feedback": 0.45, "op1_level": 0.7,
                       "op1_octave": -1, "op1_decay": 0.35,
                       "op1_sustain": 0.4, "op2_level": 0.5, "op2_semis": 7,
                       "op2_decay": 0.3, "op2_sustain": 0.3,
                       "op3_level": 0.9, "op3_octave": -1, "op3_decay": 0.5,
                       "op3_sustain": 0.6, "op3_release": 0.15}},
        "Metallic Pluck": {
            "params": {"algorithm": 0, "op1_level": 0.8, "op1_octave": 3,
                       "op1_semis": 2, "op1_decay": 0.25, "op1_sustain": 0.0,
                       "op2_level": 0.55, "op2_decay": 0.35,
                       "op2_sustain": 0.0, "op3_level": 0.85,
                       "op3_decay": 0.45, "op3_sustain": 0.0,
                       "op3_release": 0.3}},
        "Soft Organ": {
            "params": {"algorithm": 4, "op1_level": 0.8, "op2_level": 0.5,
                       "op2_octave": 1, "op3_level": 0.35, "op3_octave": 2,
                       "op1_sustain": 1.0, "op2_sustain": 1.0,
                       "op3_sustain": 1.0, "op1_release": 0.15,
                       "op2_release": 0.15, "op3_release": 0.15}},
        "Tremolo Pad": {
            "params": {"algorithm": 4, "op1_level": 0.7, "op2_level": 0.6,
                       "op2_semis": 0, "op2_octave": 0,
                       "op3_level": 0.4, "op3_octave": 1, "op1_attack": 0.35,
                       "op2_attack": 0.4, "op3_attack": 0.45,
                       "op1_release": 0.5, "op2_release": 0.5,
                       "op3_release": 0.5, "lfo_ao": 1, "lfo_rate": 4.5,
                       "lfo_depth": 0.3}},
        "Sci-Fi Sweep": {
            "params": {"algorithm": 0, "feedback": 0.6, "op1_level": 0.9,
                       "op1_octave": -2, "op1_fixed": 1, "op1_attack": 0.5,
                       "op1_sustain": 1.0, "op2_level": 0.7, "op2_decay": 0.7,
                       "op2_sustain": 0.5, "op3_level": 0.8,
                       "op3_sustain": 0.8, "op3_release": 0.5,
                       "lfo_f3": 1, "lfo_rate": 0.4, "lfo_depth": 0.25}},
    },

    # -- KSSynth -------------------------------------------------------------
    "kssynth": {
        "Nylon Guitar": {
            "params": {"pre_filter": 0.45, "pre_track": 0.6, "decay": 0.45,
                       "u1_damping": 0.35, "u2_damping": 0.5, "u2_cents": 6,
                       "mix": 0.4}},
        "Bright Steel": {
            "params": {"pre_filter": 0.15, "decay": 0.55, "u1_damping": 0.15,
                       "u2_damping": 0.2, "u2_cents": -4, "mix": 0.45}},
        "Soft Harp": {
            "params": {"pre_filter": 0.65, "pre_vel": 0.4, "decay": 0.6,
                       "u1_damping": 0.45, "u1_invert": 1, "u2_damping": 0.55,
                       "u2_invert": 1, "mix": 0.5}},
        "Muted Pluck": {
            "params": {"pre_filter": 0.55, "decay": 0.2, "u1_damping": 0.6,
                       "u2_damping": 0.7, "mix": 0.35}},
        "12-String Shimmer": {
            "params": {"pre_filter": 0.3, "decay": 0.5, "u1_damping": 0.25,
                       "u2_octave": 1, "u2_damping": 0.3, "u2_cents": 8,
                       "mix": 0.4}},
        "Bass Pluck": {
            "params": {"pre_filter": 0.5, "pre_track": 0.7, "decay": 0.4,
                       "u1_octave": -1, "u1_damping": 0.4, "u2_octave": -1,
                       "u2_semis": 0, "u2_cents": 5, "u2_damping": 0.5,
                       "mix": 0.3}},
        "Koto Strike": {
            "params": {"pre_filter": 0.1, "pre_vel": 0.3, "decay": 0.3,
                       "u1_damping": 0.2, "u1_invert": 0, "u2_damping": 0.25,
                       "u2_semis": 12, "mix": 0.25, "invert_mix": 1}},
    },
}


def _expand_beatbox_kit(kit):
    """Turn compact kit rows into full channel dicts."""
    chans = []
    for sample, tune, punch, decay, pan, volume, group in kit:
        chans.append({"sample": sample,
                      "params": {"tune": tune, "punch": punch, "decay": decay,
                                 "pan": pan, "volume": volume},
                      "mute": 0, "solo": 0, "mute_group": group})
    return chans


def preset_file_data(mtype, data):
    """Build the on-disk preset JSON for one preset table entry."""
    out = {"type": mtype, "params": dict(data.get("params", {}))}
    if mtype == "beatbox" and "kit" in data:
        out["channels"] = _expand_beatbox_kit(data["kit"])
    for extra in ("samples", "harm1", "harm2", "width1", "width2",
                  "expr_a", "expr_b", "components", "wires", "modulators",
                  "poly"):
        if extra in data:
            out[extra] = data[extra]
    return out


def install(force=False):
    """Write factory presets to disk. Never overwrites unless force=True."""
    written = 0
    for mtype, presets in PRESETS.items():
        d = os.path.join(PRESET_DIR, _safe_name(mtype))
        os.makedirs(d, exist_ok=True)
        for name, data in presets.items():
            path = os.path.join(d, _safe_name(name) + ".json")
            if os.path.exists(path) and not force:
                continue
            with open(path, "w", encoding="utf-8") as f:
                json.dump(preset_file_data(mtype, data), f, indent=1)
            written += 1
    return written
