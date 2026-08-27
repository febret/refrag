// Plain-old-data description of a rack machine, decoded from the room document
// so that the render path never touches Python objects.
#pragma once

#include <array>
#include <string>
#include <vector>

namespace refrag {

enum class MachineKind {
    SubSynth,
    PCMSynth,
    BassLine,
    BeatBox,
    PadSynth,
    BitSynth,
    Modular,
    Organ,
    Vocoder,
    FMSynth,
    KSSynth,
};

// Returns false when the name is not one of the eleven machine families.
bool machine_kind_from_string(const std::string &name, MachineKind *out);

// --- per family parameter blocks -------------------------------------------

struct SubSynthParams {
    int osc1_wave = 2;
    float osc_mix = 0.5f;
    float osc_mod = 0.0f;
    int mod_mode = 0;  // 0 FM, 1 PM, 2 AM
    float bend = 0.0f;
    int osc2_wave = 0;  // 0 = Silence, else index-1 into the shared waveforms
    float osc2_phase = 0.0f;
    int osc2_octave = 0;
    int osc2_semis = 0;
    float osc2_cents = 0.0f;
    int detune_mode = 0;  // 0 cents, 1 unison
    int flt_type = 1;
    float flt_cutoff = 1.0f;
    float flt_res = 0.0f;
    float flt_track = 0.0f;
    float flt_attack = 0.0f;
    float flt_decay = 0.0f;
    float flt_sustain = 1.0f;
    float flt_release = 0.0f;
    int lfo1_target = 0;
    int lfo1_wave = 0;
    float lfo1_rate = 2.0f;
    float lfo1_depth = 0.0f;
    int lfo2_target = 0;
    float lfo2_rate = 2.0f;
    float lfo2_depth = 0.0f;
    float vol_attack = 0.0f;
    float vol_decay = 0.0f;
    float vol_sustain = 1.0f;
    float vol_release = 0.05f;
    float volume = 1.0f;
};

struct PCMSynthParams {
    int flt_type = 0;
    float flt_cutoff = 1.0f;
    float flt_res = 0.0f;
    int lfo_target = 0;
    int lfo_wave = 0;
    float lfo_rate = 2.0f;
    float lfo_depth = 0.0f;
    int octave = 0;
    int semis = 0;
    float cents = 0.0f;
    float vol_attack = 0.0f;
    float vol_decay = 0.0f;
    float vol_sustain = 1.0f;
    float vol_release = 0.05f;
    float volume = 1.0f;
};

struct PcmZone {
    std::string sample;
    float level = 1.0f;
    float tune = 0.0f;
    float pan = 0.0f;
    int root = 60;
    int low = 0;
    int high = 127;
    int mode = 0;
    float start = 0.0f;
    float end = 1.0f;
};

struct BassLineParams {
    int wave = 0;  // 0 saw, 1 square
    float pulse_width = 0.5f;
    int tune = 0;
    float cutoff = 0.6f;
    float res = 0.6f;
    float env_mod = 0.5f;
    float decay = 0.3f;
    float accent = 0.5f;
    int lfo_target = 1;  // 0 pulse width, 1 cutoff, 2 volume
    float lfo_rate = 2.0f;
    float lfo_depth = 0.0f;
    float lfo_phase = 0.0f;
    int dist_program = 0;  // 0 off, 1 overdrive, 2 saturate, 3 foldback, 4 fuzz
    float dist_pre = 1.0f;
    float dist_amount = 0.5f;
    float dist_post = 1.0f;
    int legacy_glide = 0;
    float volume = 1.0f;
};

struct BeatBoxChannel {
    std::string sample;
    float tune = 0.0f;
    float punch = 0.0f;
    float decay = 1.0f;
    float pan = 0.0f;
    float volume = 1.0f;
    int mute = 0;
    int solo = 0;
    int mute_group = 0;
};

struct BeatBoxParams {
    float volume = 1.0f;
};

struct PadSynthParams {
    int lfo1_target = 0;  // 0 none, 1 pitch, 2 morph, 3 volume
    float lfo1_rate = 2.0f;
    float lfo1_depth = 0.0f;
    float lfo1_phase = 0.0f;
    int lfo2_target = 0;
    float lfo2_rate = 2.0f;
    float lfo2_depth = 0.0f;
    float lfo2_phase = 0.0f;
    float morph = 0.0f;
    int morph_env = 0;
    float morph_attack = 0.2f;
    float morph_decay = 0.2f;
    float morph_sustain = 1.0f;
    float morph_release = 0.2f;
    float gain1 = 1.0f;
    float gain2 = 1.0f;
    float vol_attack = 0.3f;
    float vol_decay = 0.3f;
    float vol_sustain = 1.0f;
    float vol_release = 0.4f;
    float volume = 1.0f;
};

struct BitSynthParams {
    float blend = 0.0f;
    int octave = 0;
    int semis = 0;
    float cents = 0.0f;
    float volume = 1.0f;
};

struct OrganParams {
    std::array<float, 9> bars{{0.8f, 0.0f, 0.8f, 0.4f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}};
    float perc_tone = 0.5f;
    float perc_decay = 0.0f;
    float leslie_speed = 0.4f;
    float leslie_depth = 0.5f;
    float drive = 0.0f;
    float volume = 1.0f;
};

struct VocoderParams {
    std::array<float, 8> bands{{1, 1, 1, 1, 1, 1, 1, 1}};
    int carrier = 0;
    int send_notes = 0;
    int wave = 0;
    float unison = 0.2f;
    float sub = 0.3f;
    float noise = 0.05f;
    float slew = 0.3f;
    float hf_bypass = 0.0f;
    float dry = 0.0f;
    float volume = 1.0f;
};

struct VocoderModulator {
    std::string source;
    int machine = -1;
};

struct FMOperator {
    float level = 1.0f;
    int level_vel = 0;
    int octave = 0;
    int semis = 0;
    int fixed = 0;
    float attack = 0.0f;
    float decay = 0.3f;
    float sustain = 0.7f;
    float release = 0.1f;
};

struct FMSynthParams {
    int algorithm = 4;
    float feedback = 0.0f;
    int feedback_vel = 0;
    int volume_vel = 0;
    int lfo_a1 = 0, lfo_a2 = 0, lfo_a3 = 0, lfo_ao = 0;
    int lfo_f1 = 0, lfo_f2 = 0, lfo_f3 = 0;
    float lfo_rate = 2.0f;
    float lfo_depth = 0.0f;
    std::array<FMOperator, 3> ops{};
    float volume = 1.0f;
};

struct KSUnit {
    int follow = 1;
    int octave = 0;
    int semis = 0;
    float cents = 0.0f;
    float damping = 0.3f;
    float damp_track = 0.5f;
    float damp_vel = 0.0f;
    int invert = 0;
};

struct KSSynthParams {
    float pre_filter = 0.3f;
    float pre_track = 0.5f;
    float pre_vel = 0.0f;
    float decay = 0.5f;
    std::array<KSUnit, 2> units{};
    float mix = 0.5f;
    int invert_mix = 0;
    float volume = 1.0f;
};

// --- modular ---------------------------------------------------------------

enum class ModularKind {
    Oscillator,
    Lfo,
    Envelope,
    Filter,
    Vca,
    Mixer2,
    Noise,
    SampleHold,
    ModDelay,
    Shaper,
    Crossfade,
    Invert,
};

bool modular_kind_from_string(const std::string &name, ModularKind *out);
int modular_input_count(ModularKind kind);
// Index of a named input jack, or -1 when the component has no such input.
int modular_input_index(ModularKind kind, const std::string &jack);
// Ordered control ids for a component (nullptr terminated), matching catalog.py.
const char *const *modular_param_names(ModularKind kind);
const float *modular_param_defaults(ModularKind kind);

struct ModularComponent {
    ModularKind kind = ModularKind::Invert;
    bool present = false;
    std::array<float, 5> params{};
};

// Jack endpoints: component index >= 0, or one of the panel pseudo-jacks.
enum PanelJack {
    kPanelNoteCv = -1,
    kPanelVelocity = -2,
    kPanelModWheel = -3,
    kPanelVolumeMod = -4,
    kPanelLeftOut = -5,
    kPanelRightOut = -6,
};

struct ModularWire {
    int src = 0;       // component index, or a PanelJack value
    int dst = 0;       // component index, or a PanelJack value
    int dst_input = 0; // input index on the destination component
};

struct ModularParams {
    float volume = 1.0f;
    float out_gain = 1.0f;
};

// --- machine ---------------------------------------------------------------

struct MachineSpec {
    MachineKind kind = MachineKind::SubSynth;
    int poly = 8;
    int cut_note = 0;
    bool mute = false;
    bool solo = false;

    SubSynthParams sub{};
    PCMSynthParams pcm{};
    BassLineParams bass{};
    BeatBoxParams beat{};
    PadSynthParams pad{};
    BitSynthParams bit{};
    OrganParams organ{};
    VocoderParams vocoder{};
    FMSynthParams fm{};
    KSSynthParams ks{};
    ModularParams modular{};

    std::vector<BeatBoxChannel> channels;
    std::vector<PcmZone> zones;
    std::vector<VocoderModulator> modulators;
    int mod_sel = 0;

    std::vector<float> harm1;
    std::vector<float> harm2;
    float width1 = 0.3f;
    float width2 = 0.3f;

    std::string expr_a;
    std::string expr_b;

    std::vector<ModularComponent> components;
    std::vector<ModularWire> wires;
};

// --- effects ---------------------------------------------------------------

enum class EffectKind {
    Distortion,
    BitCrusher,
    Compressor,
    Flanger,
    Chorus,
    Phaser,
    AutoWah,
    ParametricEQ,
    Limiter,
    Vinyl,
    CombFilter,
    Cabinet,
    StaticFlanger,
    Delay,
    Reverb,
    MultiFilter,
};

inline constexpr int kEffectKindCount = 16;
inline constexpr int kMaxEffectParams = 5;

bool effect_kind_from_string(const std::string &name, EffectKind *out);
// Ordered control ids for a family (nullptr terminated), matching catalog.py.
const char *const *effect_param_names(EffectKind kind);
const float *effect_param_defaults(EffectKind kind);

struct EffectSpec {
    bool present = false;
    bool bypass = false;
    EffectKind kind = EffectKind::Distortion;
    std::array<float, kMaxEffectParams> p{};
};

// --- mixer / master --------------------------------------------------------

struct MixerSpec {
    float eq_bass = 0.0f;
    float eq_mid = 0.0f;
    float eq_high = 0.0f;
    float send_delay = 0.0f;
    float send_reverb = 0.0f;
    float pan = 0.0f;
    float width = 0.0f;
    float volume = 1.0f;
};

struct MasterSpec {
    int dly_loop = 0;
    int dly_sync = 1;
    int dly_first_tap = 0;
    int dly_steps = 1;
    float dly_time = 0.4f;
    float dly_feedback = 0.4f;
    float dly_damping = 0.3f;
    float dly_wet = 1.0f;
    float dly_pan1 = -0.4f;
    float dly_pan2 = 0.4f;
    int dly_bypass = 1;
    float rev_predelay = 0.1f;
    float rev_room = 0.6f;
    float rev_damping = 0.4f;
    float rev_diffuse = 0.5f;
    int rev_dither = 0;
    float rev_early = 0.3f;
    float rev_er_decay = 0.5f;
    float rev_stereo_delay = 0.3f;
    float rev_stereo_spread = 0.7f;
    float rev_wet = 1.0f;
    int rev_bypass = 1;
    float eq_bass = 0.0f;
    float eq_bass_freq = 0.3f;
    float eq_mid = 0.0f;
    float eq_mid_freq = 0.6f;
    float eq_high = 0.0f;
    int eq_bypass = 0;
    float lim_pre = 1.0f;
    float lim_attack = 0.1f;
    float lim_release = 0.3f;
    float lim_post = 1.0f;
    int lim_bypass = 1;
    float volume = 0.8f;
    std::array<EffectSpec, 2> effects{};
};

}  // namespace refrag
