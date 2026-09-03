#include "spec.h"

#include <array>

namespace refrag {

namespace {

struct KindName {
    const char *name;
    MachineKind kind;
};

constexpr KindName kMachineNames[] = {
    {"subsynth", MachineKind::SubSynth}, {"pcmsynth", MachineKind::PCMSynth},
    {"sampler", MachineKind::Sampler},   {"bassline", MachineKind::BassLine},
    {"beatbox", MachineKind::BeatBox},   {"padsynth", MachineKind::PadSynth},
    {"bitsynth", MachineKind::BitSynth}, {"modular", MachineKind::Modular},
    {"organ", MachineKind::Organ},       {"vocoder", MachineKind::Vocoder},
    {"fmsynth", MachineKind::FMSynth},   {"kssynth", MachineKind::KSSynth},
};

struct ModName {
    const char *name;
    ModularKind kind;
};

constexpr ModName kModularNames[] = {
    {"oscillator", ModularKind::Oscillator}, {"lfo", ModularKind::Lfo},
    {"envelope", ModularKind::Envelope},     {"filter", ModularKind::Filter},
    {"vca", ModularKind::Vca},               {"mixer2", ModularKind::Mixer2},
    {"noise", ModularKind::Noise},           {"samplehold", ModularKind::SampleHold},
    {"moddelay", ModularKind::ModDelay},     {"shaper", ModularKind::Shaper},
    {"crossfade", ModularKind::Crossfade},   {"invert", ModularKind::Invert},
};

struct EffectName {
    const char *name;
    EffectKind kind;
};

constexpr EffectName kEffectNames[] = {
    {"distortion", EffectKind::Distortion},       {"bitcrusher", EffectKind::BitCrusher},
    {"compressor", EffectKind::Compressor},       {"flanger", EffectKind::Flanger},
    {"chorus", EffectKind::Chorus},               {"phaser", EffectKind::Phaser},
    {"autowah", EffectKind::AutoWah},             {"parametriceq", EffectKind::ParametricEQ},
    {"limiter", EffectKind::Limiter},             {"vinyl", EffectKind::Vinyl},
    {"combfilter", EffectKind::CombFilter},       {"cabinet", EffectKind::Cabinet},
    {"staticflanger", EffectKind::StaticFlanger}, {"delay", EffectKind::Delay},
    {"reverb", EffectKind::Reverb},               {"multifilter", EffectKind::MultiFilter},
};

// Control ids and defaults, ordered exactly as catalog.EFFECTS declares them.
const char *const kDistortionKeys[] = {"program", "pre", "amount", "post", nullptr};
const float kDistortionDefaults[] = {0.0f, 1.0f, 0.5f, 1.0f, 0.0f};
const char *const kBitCrusherKeys[] = {"depth", "rate", "jitter", "wet", nullptr};
const float kBitCrusherDefaults[] = {8.0f, 1.0f, 0.0f, 1.0f, 0.0f};
const char *const kCompressorKeys[] = {"threshold", "ratio", "attack", "release", "sidechain"};
const float kCompressorDefaults[] = {0.5f, 0.5f, 0.1f, 0.3f, 0.0f};
const char *const kFlangerKeys[] = {"depth", "rate", "feedback", "wet", "mode"};
const float kFlangerDefaults[] = {0.5f, 0.3f, 0.4f, 0.5f, 1.0f};
const char *const kChorusKeys[] = {"depth", "rate", "delay", "wet", "mode"};
const float kChorusDefaults[] = {0.3f, 0.3f, 0.3f, 0.5f, 1.0f};
const char *const kPhaserKeys[] = {"low", "high", "depth", "rate", "feedback"};
const float kPhaserDefaults[] = {0.2f, 0.8f, 0.5f, 0.3f, 0.4f};
const char *const kAutoWahKeys[] = {"speed", "depth", "cutoff", "resonance", "wet"};
const float kAutoWahDefaults[] = {0.4f, 0.7f, 0.3f, 0.6f, 1.0f};
const char *const kParametricEqKeys[] = {"freq", "gain", "bandwidth", nullptr, nullptr};
const float kParametricEqDefaults[] = {0.5f, 0.0f, 0.5f, 0.0f, 0.0f};
const char *const kLimiterKeys[] = {"pre", "attack", "release", "post", nullptr};
const float kLimiterDefaults[] = {1.0f, 0.1f, 0.3f, 1.0f, 0.0f};
const char *const kVinylKeys[] = {"dust", "scratch", "noise", "age", "wet"};
const float kVinylDefaults[] = {0.3f, 0.2f, 0.2f, 0.4f, 0.5f};
const char *const kCombFilterKeys[] = {"freq", "reso", "wet", nullptr, nullptr};
const float kCombFilterDefaults[] = {0.5f, 0.5f, 1.0f, 0.0f, 0.0f};
const char *const kCabinetKeys[] = {"width", "height", "damp", "tone", "wet"};
const float kCabinetDefaults[] = {0.5f, 0.5f, 0.5f, 0.5f, 0.7f};
const char *const kStaticFlangerKeys[] = {"delay", "feedback", "wet", "mode", nullptr};
const float kStaticFlangerDefaults[] = {0.0f, 0.5f, 0.5f, 0.0f, 0.0f};
const char *const kDelayKeys[] = {"time", "feedback", "wet", "mode", nullptr};
const float kDelayDefaults[] = {0.4f, 0.4f, 0.4f, 1.0f, 0.0f};
const char *const kReverbKeys[] = {"room", "damp", "delay", "width", "wet"};
const float kReverbDefaults[] = {0.6f, 0.4f, 0.0f, 1.0f, 0.35f};
const char *const kMultiFilterKeys[] = {"type", "freq", "reso", "gain", nullptr};
const float kMultiFilterDefaults[] = {0.0f, 0.5f, 0.3f, 0.0f, 0.0f};

// Modular component controls, ordered as catalog.MODULAR_COMPONENTS declares.
const char *const kOscillatorKeys[] = {"wave", "octave", "semis", "cents", "fm_amt", nullptr};
const float kOscillatorDefaults[] = {2.0f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModLfoKeys[] = {"wave", "rate", "depth", nullptr};
const float kModLfoDefaults[] = {0.0f, 2.0f, 1.0f, 0.0f, 0.0f};
const char *const kModEnvKeys[] = {"attack", "decay", "sustain", "release", nullptr};
const float kModEnvDefaults[] = {0.0f, 0.2f, 0.8f, 0.1f, 0.0f};
const char *const kModFilterKeys[] = {"type", "cutoff", "reso", "mod_amt", nullptr};
const float kModFilterDefaults[] = {0.0f, 0.7f, 0.2f, 0.0f, 0.0f};
const char *const kModVcaKeys[] = {"gain", nullptr};
const float kModVcaDefaults[] = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModMixer2Keys[] = {"level1", "level2", nullptr};
const float kModMixer2Defaults[] = {0.7f, 0.7f, 0.0f, 0.0f, 0.0f};
const char *const kModNoiseKeys[] = {"color", nullptr};
const float kModNoiseDefaults[] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModSampleHoldKeys[] = {"rate", nullptr};
const float kModSampleHoldDefaults[] = {4.0f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModDelayKeys[] = {"time", "feedback", "wet", nullptr};
const float kModDelayDefaults[] = {0.3f, 0.3f, 0.5f, 0.0f, 0.0f};
const char *const kModShaperKeys[] = {"drive", "mode", nullptr};
const float kModShaperDefaults[] = {0.3f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModCrossfadeKeys[] = {"mix", nullptr};
const float kModCrossfadeDefaults[] = {0.5f, 0.0f, 0.0f, 0.0f, 0.0f};
const char *const kModEmptyKeys[] = {nullptr};
const float kModEmptyDefaults[] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};

}  // namespace

bool machine_kind_from_string(const std::string &name, MachineKind *out) {
    for (const auto &entry : kMachineNames) {
        if (name == entry.name) {
            *out = entry.kind;
            return true;
        }
    }
    return false;
}

bool modular_kind_from_string(const std::string &name, ModularKind *out) {
    for (const auto &entry : kModularNames) {
        if (name == entry.name) {
            *out = entry.kind;
            return true;
        }
    }
    return false;
}

int modular_input_count(ModularKind kind) {
    switch (kind) {
    case ModularKind::Oscillator:
        return 2;  // note, fm
    case ModularKind::Lfo:
    case ModularKind::Envelope:
    case ModularKind::Noise:
        return 0;
    case ModularKind::Filter:
        return 2;  // in, mod
    case ModularKind::Vca:
        return 2;  // in, mod
    case ModularKind::Mixer2:
        return 2;  // in1, in2
    case ModularKind::SampleHold:
    case ModularKind::ModDelay:
    case ModularKind::Shaper:
    case ModularKind::Invert:
        return 1;
    case ModularKind::Crossfade:
        return 3;  // in1, in2, mod
    }
    return 0;
}

int modular_input_index(ModularKind kind, const std::string &jack) {
    switch (kind) {
    case ModularKind::Oscillator:
        if (jack == "note") return 0;
        if (jack == "fm") return 1;
        return -1;
    case ModularKind::Filter:
    case ModularKind::Vca:
        if (jack == "in") return 0;
        if (jack == "mod") return 1;
        return -1;
    case ModularKind::Mixer2:
        if (jack == "in1") return 0;
        if (jack == "in2") return 1;
        return -1;
    case ModularKind::SampleHold:
    case ModularKind::ModDelay:
    case ModularKind::Shaper:
    case ModularKind::Invert:
        return jack == "in" ? 0 : -1;
    case ModularKind::Crossfade:
        if (jack == "in1") return 0;
        if (jack == "in2") return 1;
        if (jack == "mod") return 2;
        return -1;
    case ModularKind::Lfo:
    case ModularKind::Envelope:
    case ModularKind::Noise:
        return -1;
    }
    return -1;
}

const char *const *modular_param_names(ModularKind kind) {
    switch (kind) {
    case ModularKind::Oscillator:
        return kOscillatorKeys;
    case ModularKind::Lfo:
        return kModLfoKeys;
    case ModularKind::Envelope:
        return kModEnvKeys;
    case ModularKind::Filter:
        return kModFilterKeys;
    case ModularKind::Vca:
        return kModVcaKeys;
    case ModularKind::Mixer2:
        return kModMixer2Keys;
    case ModularKind::Noise:
        return kModNoiseKeys;
    case ModularKind::SampleHold:
        return kModSampleHoldKeys;
    case ModularKind::ModDelay:
        return kModDelayKeys;
    case ModularKind::Shaper:
        return kModShaperKeys;
    case ModularKind::Crossfade:
        return kModCrossfadeKeys;
    case ModularKind::Invert:
        return kModEmptyKeys;
    }
    return kModEmptyKeys;
}

const float *modular_param_defaults(ModularKind kind) {
    switch (kind) {
    case ModularKind::Oscillator:
        return kOscillatorDefaults;
    case ModularKind::Lfo:
        return kModLfoDefaults;
    case ModularKind::Envelope:
        return kModEnvDefaults;
    case ModularKind::Filter:
        return kModFilterDefaults;
    case ModularKind::Vca:
        return kModVcaDefaults;
    case ModularKind::Mixer2:
        return kModMixer2Defaults;
    case ModularKind::Noise:
        return kModNoiseDefaults;
    case ModularKind::SampleHold:
        return kModSampleHoldDefaults;
    case ModularKind::ModDelay:
        return kModDelayDefaults;
    case ModularKind::Shaper:
        return kModShaperDefaults;
    case ModularKind::Crossfade:
        return kModCrossfadeDefaults;
    case ModularKind::Invert:
        return kModEmptyDefaults;
    }
    return kModEmptyDefaults;
}

bool effect_kind_from_string(const std::string &name, EffectKind *out) {
    for (const auto &entry : kEffectNames) {
        if (name == entry.name) {
            *out = entry.kind;
            return true;
        }
    }
    return false;
}

const char *const *effect_param_names(EffectKind kind) {
    switch (kind) {
    case EffectKind::Distortion:
        return kDistortionKeys;
    case EffectKind::BitCrusher:
        return kBitCrusherKeys;
    case EffectKind::Compressor:
        return kCompressorKeys;
    case EffectKind::Flanger:
        return kFlangerKeys;
    case EffectKind::Chorus:
        return kChorusKeys;
    case EffectKind::Phaser:
        return kPhaserKeys;
    case EffectKind::AutoWah:
        return kAutoWahKeys;
    case EffectKind::ParametricEQ:
        return kParametricEqKeys;
    case EffectKind::Limiter:
        return kLimiterKeys;
    case EffectKind::Vinyl:
        return kVinylKeys;
    case EffectKind::CombFilter:
        return kCombFilterKeys;
    case EffectKind::Cabinet:
        return kCabinetKeys;
    case EffectKind::StaticFlanger:
        return kStaticFlangerKeys;
    case EffectKind::Delay:
        return kDelayKeys;
    case EffectKind::Reverb:
        return kReverbKeys;
    case EffectKind::MultiFilter:
        return kMultiFilterKeys;
    }
    return kDistortionKeys;
}

const float *effect_param_defaults(EffectKind kind) {
    switch (kind) {
    case EffectKind::Distortion:
        return kDistortionDefaults;
    case EffectKind::BitCrusher:
        return kBitCrusherDefaults;
    case EffectKind::Compressor:
        return kCompressorDefaults;
    case EffectKind::Flanger:
        return kFlangerDefaults;
    case EffectKind::Chorus:
        return kChorusDefaults;
    case EffectKind::Phaser:
        return kPhaserDefaults;
    case EffectKind::AutoWah:
        return kAutoWahDefaults;
    case EffectKind::ParametricEQ:
        return kParametricEqDefaults;
    case EffectKind::Limiter:
        return kLimiterDefaults;
    case EffectKind::Vinyl:
        return kVinylDefaults;
    case EffectKind::CombFilter:
        return kCombFilterDefaults;
    case EffectKind::Cabinet:
        return kCabinetDefaults;
    case EffectKind::StaticFlanger:
        return kStaticFlangerDefaults;
    case EffectKind::Delay:
        return kDelayDefaults;
    case EffectKind::Reverb:
        return kReverbDefaults;
    case EffectKind::MultiFilter:
        return kMultiFilterDefaults;
    }
    return kDistortionDefaults;
}

}  // namespace refrag
