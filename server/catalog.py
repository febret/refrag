"""Catalog of every rack device Refrag exposes.

Each machine/effect declares its controls with type, range, default and the
options for selectors.  Both the synthesis engine and the web client are
driven from these tables so the two sides always agree.
"""

# ---------------------------------------------------------------------------
# Shared option lists
# ---------------------------------------------------------------------------

OSC_WAVEFORMS = ["Sine", "Triangle", "Saw", "Saw HQ", "Square", "Square HQ",
                 "Pulse", "Half Sine", "Noise"]
OSC2_WAVEFORMS = ["Silence"] + OSC_WAVEFORMS
LFO_WAVEFORMS = ["Sine", "Triangle", "Saw", "Square", "Random"]
FILTER_TYPES = ["Off", "LowPass", "HighPass", "BandPass",
                "Inv. LP", "Inv. HP", "Inv. BP"]
SUB_LFO1_TARGETS = ["None", "Osc 1", "Osc 2", "Osc 1+2", "Cutoff", "Volume", "Octave"]
SUB_LFO2_TARGETS = ["None", "Osc 1", "Osc 2", "Osc 1+2", "Cutoff", "Volume"]
PCM_LFO_TARGETS = ["None", "Pitch", "Cutoff", "Volume"]
PAD_LFO_TARGETS = ["None", "Pitch", "Morph", "Volume"]
BL_LFO_TARGETS = ["Pulse Width", "Cutoff", "Volume"]
DIST_PROGRAMS = ["Off", "Overdrive", "Saturate", "Foldback", "Fuzz"]
FX_DIST_PROGRAMS = ["Overdrive", "Saturate", "Fuzz", "Foldback"]
PCM_PLAY_MODES = ["Play Once", "Note On/Off", "Loop Fwd", "Loop FwdBack",
                  "Intro+Loop Fwd", "Intro+Loop FwdBack"]
FLANGER_MODES = ["Mono Sine", "Stereo Sine", "Inv. Sine", "Mono Tri",
                 "Stereo Tri", "Inv. Tri", "Uni Sine", "Uni Tri"]
DELAY_MODES = ["Mono", "PingPong LR", "PingPong RL", "Wide LR", "Wide RL"]
MULTIFILTER_TYPES = ["LowPass", "HighPass", "BandPass", "Notch",
                     "Peak", "Band Isolate", "LowShelf", "HighShelf"]
FM_ALGORITHMS = ["1>2>3", "1>3 2>3", "1>2 1>3", "1>2+3", "1+2+3"]
VOCODER_CARRIERS = ["Internal", "Machine 1", "Machine 2", "Machine 3", "Machine 4",
                    "Machine 5", "Machine 6", "Machine 7", "Machine 8", "Machine 9",
                    "Machine 10", "Machine 11", "Machine 12", "Machine 13", "Machine 14"]
SIDECHAIN_SOURCES = ["Self", "Line 1", "Line 2", "Line 3", "Line 4", "Line 5", "Line 6"]


def knob(label, lo, hi, default, curve="lin"):
    return {"type": "knob", "label": label, "min": lo, "max": hi,
            "default": default, "curve": curve}


def slider(label, lo, hi, default):
    return {"type": "slider", "label": label, "min": lo, "max": hi,
            "default": default}


def select(label, options, default=0):
    return {"type": "select", "label": label, "options": options,
            "default": default}


def toggle(label, default=0):
    return {"type": "toggle", "label": label, "default": default}


def cut_note_toggle(default=0):
    return toggle("Cut Note", default)


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

MACHINES = {
    "subsynth": {
        "name": "SubSynth",
        "poly": 8,
        "controls": {
            "osc1_wave": select("Waveform", OSC_WAVEFORMS, 2),
            "osc_mix": knob("Mix", 0, 1, 0.5),
            "osc_mod": knob("Mod", 0, 1, 0.0),
            "mod_mode": select("Mod Mode", ["FM", "PM", "AM"], 0),
            "bend": knob("Amount", 0, 1, 0.0),
            "osc2_wave": select("Waveform", OSC2_WAVEFORMS, 0),
            "osc2_phase": knob("Phase", -0.5, 0.5, 0.0),
            "osc2_octave": knob("Octave", -4, 4, 0, "int"),
            "osc2_semis": knob("Semis", -12, 12, 0, "int"),
            "osc2_cents": knob("Cents", -50, 50, 0, "int"),
            "detune_mode": select("Detune", ["Cents", "Unison"], 0),
            "flt_type": select("Filter", FILTER_TYPES, 1),
            "flt_cutoff": slider("Cutoff", 0, 1, 1.0),
            "flt_res": slider("Res", 0, 1, 0.0),
            "flt_track": knob("Track", 0, 1, 0.0),
            "flt_attack": knob("Attack", 0, 1, 0.0),
            "flt_decay": knob("Decay", 0, 1, 0.0),
            "flt_sustain": knob("Sustain", 0, 1, 1.0),
            "flt_release": knob("Release", 0, 1, 0.0),
            "lfo1_target": select("Target", SUB_LFO1_TARGETS, 0),
            "lfo1_wave": select("Wave", LFO_WAVEFORMS, 0),
            "lfo1_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo1_depth": knob("Depth", 0, 1, 0.0),
            "lfo2_target": select("Target", SUB_LFO2_TARGETS, 0),
            "lfo2_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo2_depth": knob("Depth", 0, 1, 0.0),
            "vol_attack": knob("Attack", 0, 1, 0.0),
            "vol_decay": knob("Decay", 0, 1, 0.0),
            "vol_sustain": knob("Sustain", 0, 1, 1.0),
            "vol_release": knob("Release", 0, 1, 0.05),
            "cut_note": cut_note_toggle(0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "pcmsynth": {
        "name": "PCMSynth",
        "poly": 8,
        "controls": {
            "flt_type": select("Filter", FILTER_TYPES, 0),
            "flt_cutoff": slider("Cutoff", 0, 1, 1.0),
            "flt_res": slider("Res", 0, 1, 0.0),
            "flt_attack": knob("Attack", 0, 1, 0.0),
            "flt_decay": knob("Decay", 0, 1, 0.0),
            "flt_sustain": knob("Sustain", 0, 1, 1.0),
            "flt_release": knob("Release", 0, 1, 0.0),
            "lfo_target": select("Target", PCM_LFO_TARGETS, 0),
            "lfo_wave": select("Wave", LFO_WAVEFORMS, 0),
            "lfo_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo_depth": knob("Depth", 0, 1, 0.0),
            "octave": knob("Octave", -3, 3, 0, "int"),
            "semis": knob("Semis", -12, 12, 0, "int"),
            "cents": knob("Cents", -50, 50, 0, "int"),
            "vol_attack": knob("Attack", 0, 1, 0.0),
            "vol_decay": knob("Decay", 0, 1, 0.0),
            "vol_sustain": knob("Sustain", 0, 1, 1.0),
            "vol_release": knob("Release", 0, 1, 0.05),
            "cut_note": cut_note_toggle(0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
        # Per-sample slot settings live in machine["samples"], not controls.
    },

    "sampler": {
        "name": "Sampler",
        "poly": 1,
        "controls": {
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "bassline": {
        "name": "BassLine",
        "poly": 1,
        "controls": {
            "wave": select("Waveform", ["Saw", "Square"], 0),
            "pulse_width": knob("Pulse W.", 0.01, 0.5, 0.5),
            "tune": knob("Tune", -12, 12, 0, "int"),
            "cutoff": knob("Cutoff", 0, 1, 0.6),
            "res": knob("Res", 0, 1, 0.6),
            "env_mod": knob("Env Mod", 0, 1, 0.5),
            "decay": knob("Decay", 0, 1, 0.3),
            "accent": knob("Accent", 0, 1, 0.5),
            "lfo_target": select("Target", BL_LFO_TARGETS, 1),
            "lfo_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo_depth": knob("Depth", 0, 1, 0.0),
            "lfo_phase": knob("Phase", 0, 1, 0.0),
            "dist_program": select("Program", DIST_PROGRAMS, 0),
            "dist_pre": knob("Pre", 0, 4, 1.0),
            "dist_amount": knob("Amount", 0, 1, 0.5),
            "dist_post": knob("Post", 0, 2, 1.0),
            "legacy_glide": toggle("Legacy", 0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "beatbox": {
        "name": "BeatBox",
        "poly": 8,
        "controls": {
            "volume": knob("Volume", 0, 2, 1.0),
        },
        # 8 channels each with sample/tune/punch/decay/pan/volume/mute/solo
        # kept in machine["channels"].
        "channel_controls": {
            "tune": knob("Tune", -12, 12, 0),
            "punch": knob("Punch", 0, 1, 0.0),
            "decay": knob("Decay", 0, 1, 1.0),
            "pan": knob("Pan", -1, 1, 0.0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "padsynth": {
        "name": "PadSynth",
        "poly": 8,
        "controls": {
            "lfo1_target": select("Target", PAD_LFO_TARGETS, 0),
            "lfo1_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo1_depth": knob("Depth", 0, 1, 0.0),
            "lfo1_phase": knob("Phase", 0, 1, 0.0),
            "lfo2_target": select("Target", PAD_LFO_TARGETS, 0),
            "lfo2_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo2_depth": knob("Depth", 0, 1, 0.0),
            "lfo2_phase": knob("Phase", 0, 1, 0.0),
            "morph": knob("Morph", 0, 1, 0.0),
            "morph_env": toggle("Env", 0),
            "morph_attack": knob("Attack", 0, 1, 0.2),
            "morph_decay": knob("Decay", 0, 1, 0.2),
            "morph_sustain": knob("Sustain", 0, 1, 1.0),
            "morph_release": knob("Release", 0, 1, 0.2),
            "gain1": knob("Gain 1", 0, 2, 1.0),
            "gain2": knob("Gain 2", 0, 2, 1.0),
            "vol_attack": knob("Attack", 0, 1, 0.3),
            "vol_decay": knob("Decay", 0, 1, 0.3),
            "vol_sustain": knob("Sustain", 0, 1, 1.0),
            "vol_release": knob("Release", 0, 1, 0.4),
            "cut_note": cut_note_toggle(0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
        "harmonics": 24,   # editable bars per table (+1 width bar)
    },

    "bitsynth": {
        "name": "8BitSynth",
        "poly": 4,
        "controls": {
            "blend": knob("A-B Blend", 0, 1, 0.0),
            "octave": knob("Octave", -4, 4, 0, "int"),
            "semis": knob("Semis", -12, 12, 0, "int"),
            "cents": knob("Cents", -50, 50, 0, "int"),
            "volume": knob("Volume", 0, 2, 1.0),
        },
        "expression_default": "t*(42&t>>10)",
    },

    "modular": {
        "name": "Modular",
        "poly": 1,
        "controls": {
            "volume": knob("Volume", 0, 2, 1.0),
            "out_gain": knob("Gain", 0, 2, 1.0),
        },
        "bays": 8,
    },

    "organ": {
        "name": "Organ",
        "poly": 8,
        "controls": {
            "bar16": slider("16", 0, 1, 0.8),
            "bar5_13": slider("5 1/3", 0, 1, 0.0),
            "bar8": slider("8", 0, 1, 0.8),
            "bar4": slider("4", 0, 1, 0.4),
            "bar2_23": slider("2 2/3", 0, 1, 0.0),
            "bar2": slider("2", 0, 1, 0.0),
            "bar1_35": slider("1 3/5", 0, 1, 0.0),
            "bar1_13": slider("1 1/3", 0, 1, 0.0),
            "bar1": slider("1", 0, 1, 0.0),
            "perc_tone": knob("Tone", 0, 1, 0.5),
            "perc_decay": knob("Decay", 0, 1, 0.0),
            "leslie_speed": knob("Speed", 0, 1, 0.4),
            "leslie_depth": knob("Depth", 0, 1, 0.5),
            "drive": knob("Drive", 0, 1, 0.0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "vocoder": {
        "name": "Vocoder",
        "poly": 6,
        "controls": {
            "band1": slider("B1", 0, 2, 1.0),
            "band2": slider("B2", 0, 2, 1.0),
            "band3": slider("B3", 0, 2, 1.0),
            "band4": slider("B4", 0, 2, 1.0),
            "band5": slider("B5", 0, 2, 1.0),
            "band6": slider("B6", 0, 2, 1.0),
            "band7": slider("B7", 0, 2, 1.0),
            "band8": slider("B8", 0, 2, 1.0),
            "carrier": select("Carrier", VOCODER_CARRIERS, 0),
            "send_notes": toggle("Send Notes", 0),
            "wave": select("Waveform", ["Saw", "Square"], 0),
            "unison": knob("Unison", 0, 1, 0.2),
            "sub": knob("Sub", 0, 1, 0.3),
            "noise": knob("Noise", 0, 1, 0.05),
            "slew": knob("Slew", 0, 1, 0.3),
            "hf_bypass": knob("HF Byp.", 0, 1, 0.0),
            "dry": knob("Dry", 0, 1, 0.0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
        "modulators": 6,
    },

    "fmsynth": {
        "name": "FMSynth",
        "poly": 6,
        "controls": {
            "algorithm": select("Algorithm", FM_ALGORITHMS, 4),
            "feedback": knob("Feedback", 0, 1, 0.0),
            "feedback_vel": toggle("Vel", 0),
            "volume_vel": toggle("Vel", 0),
            "lfo_a1": toggle("A1", 0), "lfo_a2": toggle("A2", 0),
            "lfo_a3": toggle("A3", 0), "lfo_ao": toggle("AO", 0),
            "lfo_f1": toggle("F1", 0), "lfo_f2": toggle("F2", 0),
            "lfo_f3": toggle("F3", 0),
            "lfo_rate": knob("Rate", 0.05, 12, 2.0),
            "lfo_depth": knob("Depth", 0, 1, 0.0),
            # Per-operator controls x3
            "op1_level": knob("Level", 0, 1, 1.0),
            "op1_level_vel": toggle("Vel", 0),
            "op1_octave": knob("Octave", -4, 4, 0, "int"),
            "op1_semis": knob("Semis", -12, 12, 0, "int"),
            "op1_fixed": toggle("Fixed", 0),
            "op1_attack": knob("Attack", 0, 1, 0.0),
            "op1_decay": knob("Decay", 0, 1, 0.3),
            "op1_sustain": knob("Sustain", 0, 1, 0.7),
            "op1_release": knob("Release", 0, 1, 0.1),
            "op2_level": knob("Level", 0, 1, 0.6),
            "op2_level_vel": toggle("Vel", 0),
            "op2_octave": knob("Octave", -4, 4, 0, "int"),
            "op2_semis": knob("Semis", -12, 12, 0, "int"),
            "op2_fixed": toggle("Fixed", 0),
            "op2_attack": knob("Attack", 0, 1, 0.0),
            "op2_decay": knob("Decay", 0, 1, 0.3),
            "op2_sustain": knob("Sustain", 0, 1, 0.7),
            "op2_release": knob("Release", 0, 1, 0.1),
            "op3_level": knob("Level", 0, 1, 0.6),
            "op3_level_vel": toggle("Vel", 0),
            "op3_octave": knob("Octave", -4, 4, 0, "int"),
            "op3_semis": knob("Semis", -12, 12, 0, "int"),
            "op3_fixed": toggle("Fixed", 0),
            "op3_attack": knob("Attack", 0, 1, 0.0),
            "op3_decay": knob("Decay", 0, 1, 0.3),
            "op3_sustain": knob("Sustain", 0, 1, 0.7),
            "op3_release": knob("Release", 0, 1, 0.1),
            "cut_note": cut_note_toggle(0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },

    "kssynth": {
        "name": "KSSynth",
        "poly": 8,
        "controls": {
            "pre_filter": knob("Pre Filter", 0, 1, 0.3),
            "pre_track": knob("Track", 0, 1, 0.5),
            "pre_vel": knob("Velocity", 0, 1, 0.0),
            "decay": knob("Decay", 0, 1, 0.5),
            # Unit 1
            "u1_follow": toggle("Kbd", 1),
            "u1_octave": knob("Octave", -2, 2, 0, "int"),
            "u1_semis": knob("Semis", -12, 12, 0, "int"),
            "u1_cents": knob("Cents", -50, 50, 0, "int"),
            "u1_damping": knob("Damping", 0, 1, 0.3),
            "u1_damp_track": knob("Track", 0, 1, 0.5),
            "u1_damp_vel": knob("Velocity", 0, 1, 0.0),
            "u1_invert": toggle("Invert", 0),
            # Unit 2
            "u2_follow": toggle("Kbd", 1),
            "u2_octave": knob("Octave", -2, 2, 0, "int"),
            "u2_semis": knob("Semis", -12, 12, 0, "int"),
            "u2_cents": knob("Cents", -50, 50, 0, "int"),
            "u2_damping": knob("Damping", 0, 1, 0.3),
            "u2_damp_track": knob("Track", 0, 1, 0.5),
            "u2_damp_vel": knob("Velocity", 0, 1, 0.0),
            "u2_invert": toggle("Invert", 0),
            "mix": knob("Mix", 0, 1, 0.5),
            "invert_mix": toggle("Inv Mix", 0),
            "volume": knob("Volume", 0, 2, 1.0),
        },
    },
}

MACHINE_ORDER = ["subsynth", "pcmsynth", "sampler", "bassline", "beatbox",
                 "padsynth", "bitsynth", "modular", "organ", "vocoder",
                 "fmsynth", "kssynth"]

# ---------------------------------------------------------------------------
# Insert effects (16)
# ---------------------------------------------------------------------------

EFFECTS = {
    "distortion": {
        "name": "Distortion",
        "controls": {
            "program": select("Program", FX_DIST_PROGRAMS, 0),
            "pre": knob("Pre", 0, 4, 1.0),
            "amount": knob("Amount", 0, 1, 0.5),
            "post": knob("Post", 0, 2, 1.0),
        },
    },
    "bitcrusher": {
        "name": "BitCrusher",
        "controls": {
            "depth": knob("Depth", 1, 16, 8, "int"),
            "rate": knob("Rate", 0, 1, 1.0),
            "jitter": knob("Jitter", 0, 1, 0.0),
            "wet": knob("Wet", 0, 1, 1.0),
        },
    },
    "compressor": {
        "name": "Compressor",
        "controls": {
            "threshold": knob("Threshold", 0, 1, 0.5),
            "ratio": knob("Ratio", 0, 1, 0.5),
            "attack": knob("Attack", 0, 1, 0.1),
            "release": knob("Release", 0, 1, 0.3),
            "sidechain": select("SideChain", SIDECHAIN_SOURCES, 0),
        },
    },
    "flanger": {
        "name": "Flanger",
        "controls": {
            "depth": knob("Depth", 0, 1, 0.5),
            "rate": knob("Rate", 0, 1, 0.3),
            "feedback": knob("Feedback", 0, 0.95, 0.4),
            "wet": knob("Wet", 0, 1, 0.5),
            "mode": select("Mode", FLANGER_MODES, 1),
        },
    },
    "chorus": {
        "name": "Chorus",
        "controls": {
            "depth": knob("Depth", 0, 1, 0.3),
            "rate": knob("Rate", 0, 1, 0.3),
            "delay": knob("Delay", 0, 1, 0.3),
            "wet": knob("Wet", 0, 1, 0.5),
            "mode": select("Mode", FLANGER_MODES, 1),
        },
    },
    "phaser": {
        "name": "Phaser",
        "controls": {
            "low": knob("Low", 0, 1, 0.2),
            "high": knob("High", 0, 1, 0.8),
            "depth": knob("Depth", 0, 1, 0.5),
            "rate": knob("Rate", 0, 1, 0.3),
            "feedback": knob("Feedback", 0, 0.95, 0.4),
        },
    },
    "autowah": {
        "name": "Auto-Wah",
        "controls": {
            "speed": knob("Speed", 0, 1, 0.4),
            "depth": knob("Depth", 0, 1, 0.7),
            "cutoff": knob("Cutoff", 0, 1, 0.3),
            "resonance": knob("Reso", 0, 1, 0.6),
            "wet": knob("Wet", 0, 1, 1.0),
        },
    },
    "parametriceq": {
        "name": "Param EQ",
        "controls": {
            "freq": knob("Freq", 0, 1, 0.5),
            "gain": knob("Gain", -1, 1, 0.0),
            "bandwidth": knob("Width", 0, 1, 0.5),
        },
    },
    "limiter": {
        "name": "Limiter",
        "controls": {
            "pre": knob("Pre", 0, 4, 1.0),
            "attack": knob("Attack", 0, 1, 0.1),
            "release": knob("Release", 0, 1, 0.3),
            "post": knob("Post", 0, 2, 1.0),
        },
    },
    "vinyl": {
        "name": "Vinyl Sim",
        "controls": {
            "dust": knob("Dust", 0, 1, 0.3),
            "scratch": knob("Scratch", 0, 1, 0.2),
            "noise": knob("Noise", 0, 1, 0.2),
            "age": knob("Age", 0, 1, 0.4),
            "wet": knob("Wet", 0, 1, 0.5),
        },
    },
    "combfilter": {
        "name": "Comb Filter",
        "controls": {
            "freq": knob("Freq", 0, 1, 0.5),
            "reso": knob("Reso", 0, 0.95, 0.5),
            "wet": knob("Wet", 0, 1, 1.0),
        },
    },
    "cabinet": {
        "name": "Cabinet Sim",
        "controls": {
            "width": knob("Width", 0, 1, 0.5),
            "height": knob("Height", 0, 1, 0.5),
            "damp": knob("Damp", 0, 1, 0.5),
            "tone": knob("Tone", 0, 1, 0.5),
            "wet": knob("Wet", 0, 1, 0.7),
        },
    },
    "staticflanger": {
        "name": "St. Flanger",
        "controls": {
            "delay": knob("Delay", -1, 1, 0.0),
            "feedback": knob("Feedback", 0, 0.95, 0.5),
            "wet": knob("Wet", 0, 1, 0.5),
            "mode": select("Mode", FLANGER_MODES, 0),
        },
    },
    "delay": {
        "name": "Delay",
        "controls": {
            "time": knob("Time", 0, 1, 0.4),
            "feedback": knob("Feedback", 0, 0.95, 0.4),
            "wet": knob("Wet", 0, 1, 0.4),
            "mode": select("Mode", DELAY_MODES, 1),
        },
    },
    "reverb": {
        "name": "Reverb",
        "controls": {
            "room": knob("Room", 0, 1, 0.6),
            "damp": knob("Damp", 0, 1, 0.4),
            "delay": knob("Delay", 0, 1, 0.0),
            "width": knob("Width", 0, 1, 1.0),
            "wet": knob("Wet", 0, 1, 0.35),
        },
    },
    "multifilter": {
        "name": "MultiFilter",
        "controls": {
            "type": select("Type", MULTIFILTER_TYPES, 0),
            "freq": knob("Freq", 0, 1, 0.5),
            "reso": knob("Reso", 0, 1, 0.3),
            "gain": knob("Gain", -1, 1, 0.0),
        },
    },
}

EFFECT_ORDER = ["distortion", "bitcrusher", "compressor", "flanger", "chorus",
                "phaser", "autowah", "parametriceq", "limiter", "vinyl",
                "combfilter", "cabinet", "staticflanger", "delay", "reverb",
                "multifilter"]

# ---------------------------------------------------------------------------
# Mixer strip / master section
# ---------------------------------------------------------------------------

MIXER_STRIP = {
    "eq_bass": knob("Bass", -1, 1, 0.0),
    "eq_mid": knob("Mid", -1, 1, 0.0),
    "eq_high": knob("High", -1, 1, 0.0),
    "send_delay": knob("Delay", 0, 1, 0.0),
    "send_reverb": knob("Reverb", 0, 1, 0.0),
    "pan": knob("Pan", -1, 1, 0.0),
    "width": knob("Width", -1, 1, 0.0),
    "volume": knob("Volume", 0, 1.5, 1.0),
}

MASTER = {
    "dly_loop": toggle("Loop", 0),
    "dly_sync": toggle("Sync", 1),
    "dly_first_tap": toggle("1st Tap", 0),
    "dly_steps": select("Steps", ["1", "2", "3", "4", "5"], 1),
    "dly_time": knob("Time", 0, 1, 0.4),
    "dly_feedback": knob("F.Back", 0, 0.95, 0.4),
    "dly_damping": knob("Damping", 0, 1, 0.3),
    "dly_wet": knob("Wet", 0, 1, 1.0),
    "dly_pan1": knob("Pan", -1, 1, -0.4),
    "dly_pan2": knob("Pan", -1, 1, 0.4),
    "dly_bypass": toggle("On", 1),
    "rev_predelay": knob("Pre Delay", 0, 1, 0.1),
    "rev_room": knob("Room Size", 0, 1, 0.6),
    "rev_damping": knob("HF Damping", 0, 1, 0.4),
    "rev_diffuse": knob("Diffuse", 0, 1, 0.5),
    "rev_dither": toggle("Dither", 0),
    "rev_early": knob("Early Refl.", 0, 1, 0.3),
    "rev_er_decay": knob("E.R. Decay", 0, 1, 0.5),
    "rev_stereo_delay": knob("St. Delay", 0, 1, 0.3),
    "rev_stereo_spread": knob("St. Spread", 0, 1, 0.7),
    "rev_wet": knob("Wet", 0, 1, 1.0),
    "rev_bypass": toggle("On", 1),
    "eq_bass": knob("Bass", -1, 1, 0.0),
    "eq_bass_freq": knob("Freq", 0, 1, 0.3),
    "eq_mid": knob("Mid", -1, 1, 0.0),
    "eq_mid_freq": knob("Freq", 0, 1, 0.6),
    "eq_high": knob("High", -1, 1, 0.0),
    "eq_bypass": toggle("On", 0),
    "lim_pre": knob("Pre", 0, 4, 1.0),
    "lim_attack": knob("Attack", 0, 1, 0.1),
    "lim_release": knob("Release", 0, 1, 0.3),
    "lim_post": knob("Post", 0, 2, 1.0),
    "lim_bypass": toggle("On", 1),
    "volume": knob("Volume", 0, 1.5, 0.8),
}

# Modular synth component catalog -------------------------------------------

MODULAR_COMPONENTS = {
    "oscillator": {
        "name": "Oscillator", "size": 2,
        "controls": {
            "wave": select("Wave", OSC_WAVEFORMS, 2),
            "octave": knob("Octave", -4, 4, 0, "int"),
            "semis": knob("Semis", -12, 12, 0, "int"),
            "cents": knob("Cents", -50, 50, 0, "int"),
            "fm_amt": knob("FM Amt", 0, 1, 0.0),
        },
        "inputs": ["note", "fm"], "outputs": ["out"],
    },
    "lfo": {
        "name": "LFO", "size": 1,
        "controls": {
            "wave": select("Wave", LFO_WAVEFORMS, 0),
            "rate": knob("Rate", 0.05, 20, 2.0),
            "depth": knob("Depth", 0, 1, 1.0),
        },
        "inputs": [], "outputs": ["out"],
    },
    "envelope": {
        "name": "ADSR Env", "size": 1,
        "controls": {
            "attack": knob("Attack", 0, 1, 0.0),
            "decay": knob("Decay", 0, 1, 0.2),
            "sustain": knob("Sustain", 0, 1, 0.8),
            "release": knob("Release", 0, 1, 0.1),
        },
        "inputs": [], "outputs": ["out"],
    },
    "filter": {
        "name": "SVF Filter", "size": 2,
        "controls": {
            "type": select("Type", ["LowPass", "HighPass", "BandPass"], 0),
            "cutoff": knob("Cutoff", 0, 1, 0.7),
            "reso": knob("Reso", 0, 1, 0.2),
            "mod_amt": knob("Mod Amt", 0, 1, 0.0),
        },
        "inputs": ["in", "mod"], "outputs": ["out"],
    },
    "vca": {
        "name": "VCA", "size": 1,
        "controls": {
            "gain": knob("Gain", 0, 2, 1.0),
        },
        "inputs": ["in", "mod"], "outputs": ["out"],
    },
    "mixer2": {
        "name": "Mixer 2:1", "size": 1,
        "controls": {
            "level1": knob("Lvl 1", 0, 1, 0.7),
            "level2": knob("Lvl 2", 0, 1, 0.7),
        },
        "inputs": ["in1", "in2"], "outputs": ["out"],
    },
    "noise": {
        "name": "Noise", "size": 1,
        "controls": {
            "color": knob("Color", 0, 1, 0.0),
        },
        "inputs": [], "outputs": ["out"],
    },
    "samplehold": {
        "name": "Samp/Hold", "size": 1,
        "controls": {
            "rate": knob("Rate", 0.1, 30, 4.0),
        },
        "inputs": ["in"], "outputs": ["out"],
    },
    "moddelay": {
        "name": "Delay", "size": 1,
        "controls": {
            "time": knob("Time", 0, 1, 0.3),
            "feedback": knob("F.Back", 0, 0.95, 0.3),
            "wet": knob("Wet", 0, 1, 0.5),
        },
        "inputs": ["in"], "outputs": ["out"],
    },
    "shaper": {
        "name": "Waveshaper", "size": 1,
        "controls": {
            "drive": knob("Drive", 0, 1, 0.3),
            "mode": select("Mode", ["Soft", "Hard", "Fold"], 0),
        },
        "inputs": ["in"], "outputs": ["out"],
    },
    "crossfade": {
        "name": "Crossfader", "size": 1,
        "controls": {
            "mix": knob("Mix", 0, 1, 0.5),
        },
        "inputs": ["in1", "in2", "mod"], "outputs": ["out"],
    },
    "invert": {
        "name": "Inverter", "size": 1,
        "controls": {},
        "inputs": ["in"], "outputs": ["out"],
    },
}


def default_params(controls):
    return {cid: spec["default"] for cid, spec in controls.items()}


def catalog_json():
    """Serializable catalog for the web client."""
    return {
        "machines": MACHINES,
        "machineOrder": MACHINE_ORDER,
        "effects": EFFECTS,
        "effectOrder": EFFECT_ORDER,
        "mixerStrip": MIXER_STRIP,
        "master": MASTER,
        "modularComponents": MODULAR_COMPONENTS,
    }
