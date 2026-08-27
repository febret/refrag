#include "pydoc.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace refrag {

namespace {

py::object get_item(const py::handle &obj, const char *key) {
    if (!obj || obj.is_none()) {
        return py::none();
    }
    if (py::isinstance<py::dict>(obj)) {
        py::dict d = py::reinterpret_borrow<py::dict>(obj);
        if (d.contains(key)) {
            return d[key];
        }
        return py::none();
    }
    if (py::hasattr(obj, "get")) {
        return obj.attr("get")(key, py::none());
    }
    return py::none();
}

bool to_double(const py::handle &h, double *out) {
    if (!h || h.is_none()) {
        return false;
    }
    if (py::isinstance<py::bool_>(h)) {
        *out = h.cast<bool>() ? 1.0 : 0.0;
        return true;
    }
    if (py::isinstance<py::int_>(h) || py::isinstance<py::float_>(h)) {
        *out = h.cast<double>();
        return true;
    }
    try {
        *out = py::float_(py::reinterpret_borrow<py::object>(h)).cast<double>();
        return true;
    } catch (const py::error_already_set &) {
        PyErr_Clear();
        return false;
    }
}

// Reads a numeric control from a params mapping, falling back to `def`.
class Params {
  public:
    explicit Params(const py::handle &obj) : obj_(py::reinterpret_borrow<py::object>(obj)) {}

    float f(const char *key, float def) const {
        double v = def;
        py::object item = get_item(obj_, key);
        if (to_double(item, &v)) {
            return static_cast<float>(v);
        }
        return def;
    }

    int i(const char *key, int def) const {
        double v = def;
        py::object item = get_item(obj_, key);
        if (to_double(item, &v)) {
            return static_cast<int>(std::lround(v));
        }
        return def;
    }

    int flag(const char *key, int def) const { return i(key, def) != 0 ? 1 : 0; }

  private:
    py::object obj_;
};

std::string as_string(const py::handle &h, const char *what) {
    if (!h || h.is_none()) {
        return std::string();
    }
    if (py::isinstance<py::str>(h)) {
        return h.cast<std::string>();
    }
    throw std::invalid_argument(std::string(what) + " must be a string");
}

std::vector<float> float_list(const py::handle &h) {
    std::vector<float> out;
    if (!h || h.is_none()) {
        return out;
    }
    for (const py::handle &item : py::reinterpret_borrow<py::object>(h)) {
        double v = 0.0;
        to_double(item, &v);
        out.push_back(static_cast<float>(v));
    }
    return out;
}

int parse_jack(const std::string &jack, std::string *sub) {
    auto dot = jack.find('.');
    std::string head = dot == std::string::npos ? jack : jack.substr(0, dot);
    *sub = dot == std::string::npos ? std::string() : jack.substr(dot + 1);
    if (head == "panel") {
        if (*sub == "note_cv") return kPanelNoteCv;
        if (*sub == "velocity") return kPanelVelocity;
        if (*sub == "mod_wheel") return kPanelModWheel;
        if (*sub == "volume_mod") return kPanelVolumeMod;
        if (*sub == "left_out") return kPanelLeftOut;
        if (*sub == "right_out") return kPanelRightOut;
        return -100;
    }
    if (head.size() > 1 && head[0] == 'c') {
        try {
            return std::stoi(head.substr(1));
        } catch (const std::exception &) {
            return -100;
        }
    }
    return -100;
}

void parse_subsynth(const Params &p, SubSynthParams *out) {
    out->osc1_wave = p.i("osc1_wave", 2);
    out->osc_mix = p.f("osc_mix", 0.5f);
    out->osc_mod = p.f("osc_mod", 0.0f);
    out->mod_mode = p.i("mod_mode", 0);
    out->bend = p.f("bend", 0.0f);
    out->osc2_wave = p.i("osc2_wave", 0);
    out->osc2_phase = p.f("osc2_phase", 0.0f);
    out->osc2_octave = p.i("osc2_octave", 0);
    out->osc2_semis = p.i("osc2_semis", 0);
    out->osc2_cents = p.f("osc2_cents", 0.0f);
    out->detune_mode = p.i("detune_mode", 0);
    out->flt_type = p.i("flt_type", 1);
    out->flt_cutoff = p.f("flt_cutoff", 1.0f);
    out->flt_res = p.f("flt_res", 0.0f);
    out->flt_track = p.f("flt_track", 0.0f);
    out->flt_attack = p.f("flt_attack", 0.0f);
    out->flt_decay = p.f("flt_decay", 0.0f);
    out->flt_sustain = p.f("flt_sustain", 1.0f);
    out->flt_release = p.f("flt_release", 0.0f);
    out->lfo1_target = p.i("lfo1_target", 0);
    out->lfo1_wave = p.i("lfo1_wave", 0);
    out->lfo1_rate = p.f("lfo1_rate", 2.0f);
    out->lfo1_depth = p.f("lfo1_depth", 0.0f);
    out->lfo2_target = p.i("lfo2_target", 0);
    out->lfo2_rate = p.f("lfo2_rate", 2.0f);
    out->lfo2_depth = p.f("lfo2_depth", 0.0f);
    out->vol_attack = p.f("vol_attack", 0.0f);
    out->vol_decay = p.f("vol_decay", 0.0f);
    out->vol_sustain = p.f("vol_sustain", 1.0f);
    out->vol_release = p.f("vol_release", 0.05f);
    out->volume = p.f("volume", 1.0f);
}

void parse_pcm(const Params &p, PCMSynthParams *out) {
    out->flt_type = p.i("flt_type", 0);
    out->flt_cutoff = p.f("flt_cutoff", 1.0f);
    out->flt_res = p.f("flt_res", 0.0f);
    out->lfo_target = p.i("lfo_target", 0);
    out->lfo_wave = p.i("lfo_wave", 0);
    out->lfo_rate = p.f("lfo_rate", 2.0f);
    out->lfo_depth = p.f("lfo_depth", 0.0f);
    out->octave = p.i("octave", 0);
    out->semis = p.i("semis", 0);
    out->cents = p.f("cents", 0.0f);
    out->vol_attack = p.f("vol_attack", 0.0f);
    out->vol_decay = p.f("vol_decay", 0.0f);
    out->vol_sustain = p.f("vol_sustain", 1.0f);
    out->vol_release = p.f("vol_release", 0.05f);
    out->volume = p.f("volume", 1.0f);
}

void parse_bassline(const Params &p, BassLineParams *out) {
    out->wave = p.i("wave", 0);
    out->pulse_width = p.f("pulse_width", 0.5f);
    out->tune = p.i("tune", 0);
    out->cutoff = p.f("cutoff", 0.6f);
    out->res = p.f("res", 0.6f);
    out->env_mod = p.f("env_mod", 0.5f);
    out->decay = p.f("decay", 0.3f);
    out->accent = p.f("accent", 0.5f);
    out->lfo_target = p.i("lfo_target", 1);
    out->lfo_rate = p.f("lfo_rate", 2.0f);
    out->lfo_depth = p.f("lfo_depth", 0.0f);
    out->lfo_phase = p.f("lfo_phase", 0.0f);
    out->dist_program = p.i("dist_program", 0);
    out->dist_pre = p.f("dist_pre", 1.0f);
    out->dist_amount = p.f("dist_amount", 0.5f);
    out->dist_post = p.f("dist_post", 1.0f);
    out->legacy_glide = p.flag("legacy_glide", 0);
    out->volume = p.f("volume", 1.0f);
}

void parse_pad(const Params &p, PadSynthParams *out) {
    out->lfo1_target = p.i("lfo1_target", 0);
    out->lfo1_rate = p.f("lfo1_rate", 2.0f);
    out->lfo1_depth = p.f("lfo1_depth", 0.0f);
    out->lfo1_phase = p.f("lfo1_phase", 0.0f);
    out->lfo2_target = p.i("lfo2_target", 0);
    out->lfo2_rate = p.f("lfo2_rate", 2.0f);
    out->lfo2_depth = p.f("lfo2_depth", 0.0f);
    out->lfo2_phase = p.f("lfo2_phase", 0.0f);
    out->morph = p.f("morph", 0.0f);
    out->morph_env = p.flag("morph_env", 0);
    out->morph_attack = p.f("morph_attack", 0.2f);
    out->morph_decay = p.f("morph_decay", 0.2f);
    out->morph_sustain = p.f("morph_sustain", 1.0f);
    out->morph_release = p.f("morph_release", 0.2f);
    out->gain1 = p.f("gain1", 1.0f);
    out->gain2 = p.f("gain2", 1.0f);
    out->vol_attack = p.f("vol_attack", 0.3f);
    out->vol_decay = p.f("vol_decay", 0.3f);
    out->vol_sustain = p.f("vol_sustain", 1.0f);
    out->vol_release = p.f("vol_release", 0.4f);
    out->volume = p.f("volume", 1.0f);
}

void parse_organ(const Params &p, OrganParams *out) {
    static const char *kBars[9] = {"bar16", "bar5_13", "bar8",    "bar4",  "bar2_23",
                                   "bar2",  "bar1_35", "bar1_13", "bar1"};
    static const float kBarDefaults[9] = {0.8f, 0.0f, 0.8f, 0.4f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    for (int i = 0; i < 9; ++i) {
        out->bars[i] = p.f(kBars[i], kBarDefaults[i]);
    }
    out->perc_tone = p.f("perc_tone", 0.5f);
    out->perc_decay = p.f("perc_decay", 0.0f);
    out->leslie_speed = p.f("leslie_speed", 0.4f);
    out->leslie_depth = p.f("leslie_depth", 0.5f);
    out->drive = p.f("drive", 0.0f);
    out->volume = p.f("volume", 1.0f);
}

void parse_vocoder(const Params &p, VocoderParams *out) {
    static const char *kBands[8] = {"band1", "band2", "band3", "band4",
                                    "band5", "band6", "band7", "band8"};
    for (int i = 0; i < 8; ++i) {
        out->bands[i] = p.f(kBands[i], 1.0f);
    }
    out->carrier = p.i("carrier", 0);
    out->send_notes = p.flag("send_notes", 0);
    out->wave = p.i("wave", 0);
    out->unison = p.f("unison", 0.2f);
    out->sub = p.f("sub", 0.3f);
    out->noise = p.f("noise", 0.05f);
    out->slew = p.f("slew", 0.3f);
    out->hf_bypass = p.f("hf_bypass", 0.0f);
    out->dry = p.f("dry", 0.0f);
    out->volume = p.f("volume", 1.0f);
}

void parse_fm(const Params &p, FMSynthParams *out) {
    out->algorithm = p.i("algorithm", 4);
    out->feedback = p.f("feedback", 0.0f);
    out->feedback_vel = p.flag("feedback_vel", 0);
    out->volume_vel = p.flag("volume_vel", 0);
    out->lfo_a1 = p.flag("lfo_a1", 0);
    out->lfo_a2 = p.flag("lfo_a2", 0);
    out->lfo_a3 = p.flag("lfo_a3", 0);
    out->lfo_ao = p.flag("lfo_ao", 0);
    out->lfo_f1 = p.flag("lfo_f1", 0);
    out->lfo_f2 = p.flag("lfo_f2", 0);
    out->lfo_f3 = p.flag("lfo_f3", 0);
    out->lfo_rate = p.f("lfo_rate", 2.0f);
    out->lfo_depth = p.f("lfo_depth", 0.0f);
    static const char *kPrefix[3] = {"op1_", "op2_", "op3_"};
    static const float kLevelDefaults[3] = {1.0f, 0.6f, 0.6f};
    for (int k = 0; k < 3; ++k) {
        auto key = [&](const char *suffix) {
            static thread_local std::string buffer;
            buffer = std::string(kPrefix[k]) + suffix;
            return buffer.c_str();
        };
        out->ops[k].level = p.f(key("level"), kLevelDefaults[k]);
        out->ops[k].level_vel = p.flag(key("level_vel"), 0);
        out->ops[k].octave = p.i(key("octave"), 0);
        out->ops[k].semis = p.i(key("semis"), 0);
        out->ops[k].fixed = p.flag(key("fixed"), 0);
        out->ops[k].attack = p.f(key("attack"), 0.0f);
        out->ops[k].decay = p.f(key("decay"), 0.3f);
        out->ops[k].sustain = p.f(key("sustain"), 0.7f);
        out->ops[k].release = p.f(key("release"), 0.1f);
    }
    out->volume = p.f("volume", 1.0f);
}

void parse_ks(const Params &p, KSSynthParams *out) {
    out->pre_filter = p.f("pre_filter", 0.3f);
    out->pre_track = p.f("pre_track", 0.5f);
    out->pre_vel = p.f("pre_vel", 0.0f);
    out->decay = p.f("decay", 0.5f);
    static const char *kPrefix[2] = {"u1_", "u2_"};
    for (int k = 0; k < 2; ++k) {
        auto key = [&](const char *suffix) {
            static thread_local std::string buffer;
            buffer = std::string(kPrefix[k]) + suffix;
            return buffer.c_str();
        };
        out->units[k].follow = p.flag(key("follow"), 1);
        out->units[k].octave = p.i(key("octave"), 0);
        out->units[k].semis = p.i(key("semis"), 0);
        out->units[k].cents = p.f(key("cents"), 0.0f);
        out->units[k].damping = p.f(key("damping"), 0.3f);
        out->units[k].damp_track = p.f(key("damp_track"), 0.5f);
        out->units[k].damp_vel = p.f(key("damp_vel"), 0.0f);
        out->units[k].invert = p.flag(key("invert"), 0);
    }
    out->mix = p.f("mix", 0.5f);
    out->invert_mix = p.flag("invert_mix", 0);
    out->volume = p.f("volume", 1.0f);
}

void parse_beatbox_channels(const py::handle &obj, MachineSpec *spec) {
    spec->channels.clear();
    if (!obj || obj.is_none()) {
        return;
    }
    for (const py::handle &item : py::reinterpret_borrow<py::object>(obj)) {
        BeatBoxChannel ch;
        if (item.is_none()) {
            spec->channels.push_back(ch);
            continue;
        }
        ch.sample = as_string(get_item(item, "sample"), "beatbox channel sample");
        Params p(get_item(item, "params"));
        ch.tune = p.f("tune", 0.0f);
        ch.punch = p.f("punch", 0.0f);
        ch.decay = p.f("decay", 1.0f);
        ch.pan = p.f("pan", 0.0f);
        ch.volume = p.f("volume", 1.0f);
        Params top(item);
        ch.mute = top.flag("mute", 0);
        ch.solo = top.flag("solo", 0);
        ch.mute_group = top.i("mute_group", 0);
        spec->channels.push_back(ch);
    }
}

void parse_pcm_zones(const py::handle &obj, MachineSpec *spec) {
    spec->zones.clear();
    if (!obj || obj.is_none()) {
        return;
    }
    for (const py::handle &item : py::reinterpret_borrow<py::object>(obj)) {
        if (item.is_none()) {
            continue;
        }
        PcmZone zone;
        Params p(item);
        zone.sample = as_string(get_item(item, "sample"), "pcmsynth zone sample");
        zone.level = p.f("level", 1.0f);
        zone.tune = p.f("tune", 0.0f);
        zone.pan = p.f("pan", 0.0f);
        zone.root = p.i("root", 60);
        zone.low = p.i("low", 0);
        zone.high = p.i("high", 127);
        zone.mode = p.i("mode", 0);
        zone.start = p.f("start", 0.0f);
        zone.end = p.f("end", 1.0f);
        spec->zones.push_back(zone);
    }
}

void parse_modulators(const py::handle &obj, MachineSpec *spec) {
    spec->modulators.clear();
    if (!obj || obj.is_none()) {
        return;
    }
    for (const py::handle &item : py::reinterpret_borrow<py::object>(obj)) {
        VocoderModulator mod;
        if (!item.is_none()) {
            mod.source = as_string(get_item(item, "source"), "vocoder modulator source");
            Params p(item);
            mod.machine = p.i("machine", -1);
        }
        spec->modulators.push_back(mod);
    }
}

void parse_modular(const py::handle &components, const py::handle &wires, MachineSpec *spec) {
    spec->components.clear();
    spec->wires.clear();
    if (components && !components.is_none()) {
        for (const py::handle &item : py::reinterpret_borrow<py::object>(components)) {
            ModularComponent comp;
            if (item.is_none() || py::isinstance<py::str>(item)) {
                // None (empty bay) or the "occupied" continuation marker.
                spec->components.push_back(comp);
                continue;
            }
            std::string type = as_string(get_item(item, "type"), "modular component type");
            ModularKind kind;
            if (!modular_kind_from_string(type, &kind)) {
                throw std::invalid_argument("unknown modular component type: " + type);
            }
            comp.kind = kind;
            comp.present = true;
            Params p(get_item(item, "params"));
            const char *const *names = modular_param_names(kind);
            const float *defaults = modular_param_defaults(kind);
            for (int i = 0; i < 5 && names[i] != nullptr; ++i) {
                comp.params[i] = p.f(names[i], defaults[i]);
            }
            spec->components.push_back(comp);
        }
    }
    if (wires && !wires.is_none()) {
        for (const py::handle &item : py::reinterpret_borrow<py::object>(wires)) {
            py::list pair = py::reinterpret_borrow<py::list>(
                py::reinterpret_steal<py::object>(PySequence_List(item.ptr())));
            if (pair.size() < 2) {
                continue;
            }
            std::string src_sub;
            std::string dst_sub;
            int src = parse_jack(pair[0].cast<std::string>(), &src_sub);
            int dst = parse_jack(pair[1].cast<std::string>(), &dst_sub);
            if (src == -100 || dst == -100) {
                continue;
            }
            ModularWire wire;
            wire.src = src;
            wire.dst = dst;
            wire.dst_input = 0;
            if (dst >= 0) {
                if (dst >= static_cast<int>(spec->components.size()) ||
                    !spec->components[dst].present) {
                    continue;
                }
                int index = modular_input_index(spec->components[dst].kind, dst_sub);
                if (index < 0) {
                    continue;
                }
                wire.dst_input = index;
            }
            spec->wires.push_back(wire);
        }
    }
}

MachineSpec parse_machine(const py::handle &obj) {
    if (!obj || obj.is_none()) {
        throw std::invalid_argument("machine must be a mapping");
    }
    MachineSpec spec;
    std::string type = as_string(get_item(obj, "type"), "machine type");
    if (!machine_kind_from_string(type, &spec.kind)) {
        throw std::invalid_argument("unknown machine type: " + type);
    }
    Params top(obj);
    spec.poly = std::max(1, std::min(kMaxVoices, top.i("poly", 8)));
    spec.mute = top.flag("mute", 0) != 0;
    spec.solo = top.flag("solo", 0) != 0;
    spec.mod_sel = top.i("mod_sel", 0);
    spec.width1 = top.f("width1", 0.3f);
    spec.width2 = top.f("width2", 0.3f);

    Params params(get_item(obj, "params"));
    int cut_note_default =
        (spec.kind == MachineKind::BassLine || spec.kind == MachineKind::Modular) ? 1 : 0;
    spec.cut_note = params.flag("cut_note", cut_note_default);
    switch (spec.kind) {
    case MachineKind::SubSynth:
        parse_subsynth(params, &spec.sub);
        break;
    case MachineKind::PCMSynth:
        parse_pcm(params, &spec.pcm);
        parse_pcm_zones(get_item(obj, "samples"), &spec);
        break;
    case MachineKind::BassLine:
        parse_bassline(params, &spec.bass);
        break;
    case MachineKind::BeatBox:
        spec.beat.volume = params.f("volume", 1.0f);
        parse_beatbox_channels(get_item(obj, "channels"), &spec);
        break;
    case MachineKind::PadSynth:
        parse_pad(params, &spec.pad);
        spec.harm1 = float_list(get_item(obj, "harm1"));
        spec.harm2 = float_list(get_item(obj, "harm2"));
        break;
    case MachineKind::BitSynth:
        spec.bit.blend = params.f("blend", 0.0f);
        spec.bit.octave = params.i("octave", 0);
        spec.bit.semis = params.i("semis", 0);
        spec.bit.cents = params.f("cents", 0.0f);
        spec.bit.volume = params.f("volume", 1.0f);
        spec.expr_a = as_string(get_item(obj, "expr_a"), "expr_a");
        spec.expr_b = as_string(get_item(obj, "expr_b"), "expr_b");
        break;
    case MachineKind::Modular:
        spec.modular.volume = params.f("volume", 1.0f);
        spec.modular.out_gain = params.f("out_gain", 1.0f);
        parse_modular(get_item(obj, "components"), get_item(obj, "wires"), &spec);
        break;
    case MachineKind::Organ:
        parse_organ(params, &spec.organ);
        break;
    case MachineKind::Vocoder:
        parse_vocoder(params, &spec.vocoder);
        parse_modulators(get_item(obj, "modulators"), &spec);
        break;
    case MachineKind::FMSynth:
        parse_fm(params, &spec.fm);
        break;
    case MachineKind::KSSynth:
        parse_ks(params, &spec.ks);
        break;
    }
    return spec;
}

EffectSpec parse_effect(const py::handle &obj) {
    EffectSpec spec;
    if (!obj || obj.is_none()) {
        return spec;
    }
    std::string type = as_string(get_item(obj, "type"), "effect type");
    if (type.empty()) {
        return spec;
    }
    if (!effect_kind_from_string(type, &spec.kind)) {
        throw std::invalid_argument("unknown effect type: " + type);
    }
    spec.present = true;
    Params top(obj);
    spec.bypass = top.flag("bypass", 0) != 0;
    Params params(get_item(obj, "params"));
    const char *const *names = effect_param_names(spec.kind);
    const float *defaults = effect_param_defaults(spec.kind);
    for (int i = 0; i < kMaxEffectParams && names[i] != nullptr; ++i) {
        spec.p[i] = params.f(names[i], defaults[i]);
    }
    return spec;
}

MixerSpec parse_mixer(const py::handle &obj) {
    MixerSpec mx;
    Params p(obj);
    mx.eq_bass = p.f("eq_bass", 0.0f);
    mx.eq_mid = p.f("eq_mid", 0.0f);
    mx.eq_high = p.f("eq_high", 0.0f);
    mx.send_delay = p.f("send_delay", 0.0f);
    mx.send_reverb = p.f("send_reverb", 0.0f);
    mx.pan = p.f("pan", 0.0f);
    mx.width = p.f("width", 0.0f);
    mx.volume = p.f("volume", 1.0f);
    return mx;
}

MasterSpec parse_master(const py::handle &obj) {
    MasterSpec ms;
    if (!obj || obj.is_none()) {
        return ms;
    }
    Params p(get_item(obj, "params"));
    ms.dly_loop = p.flag("dly_loop", 0);
    ms.dly_sync = p.flag("dly_sync", 1);
    ms.dly_first_tap = p.flag("dly_first_tap", 0);
    ms.dly_steps = std::max(0, std::min(7, p.i("dly_steps", 1)));
    ms.dly_time = p.f("dly_time", 0.4f);
    ms.dly_feedback = p.f("dly_feedback", 0.4f);
    ms.dly_damping = p.f("dly_damping", 0.3f);
    ms.dly_wet = p.f("dly_wet", 1.0f);
    ms.dly_pan1 = p.f("dly_pan1", -0.4f);
    ms.dly_pan2 = p.f("dly_pan2", 0.4f);
    ms.dly_bypass = p.flag("dly_bypass", 1);
    ms.rev_predelay = p.f("rev_predelay", 0.1f);
    ms.rev_room = p.f("rev_room", 0.6f);
    ms.rev_damping = p.f("rev_damping", 0.4f);
    ms.rev_diffuse = p.f("rev_diffuse", 0.5f);
    ms.rev_dither = p.flag("rev_dither", 0);
    ms.rev_early = p.f("rev_early", 0.3f);
    ms.rev_er_decay = p.f("rev_er_decay", 0.5f);
    ms.rev_stereo_delay = p.f("rev_stereo_delay", 0.3f);
    ms.rev_stereo_spread = p.f("rev_stereo_spread", 0.7f);
    ms.rev_wet = p.f("rev_wet", 1.0f);
    ms.rev_bypass = p.flag("rev_bypass", 1);
    ms.eq_bass = p.f("eq_bass", 0.0f);
    ms.eq_bass_freq = p.f("eq_bass_freq", 0.3f);
    ms.eq_mid = p.f("eq_mid", 0.0f);
    ms.eq_mid_freq = p.f("eq_mid_freq", 0.6f);
    ms.eq_high = p.f("eq_high", 0.0f);
    ms.eq_bypass = p.flag("eq_bypass", 0);
    ms.lim_pre = p.f("lim_pre", 1.0f);
    ms.lim_attack = p.f("lim_attack", 0.1f);
    ms.lim_release = p.f("lim_release", 0.3f);
    ms.lim_post = p.f("lim_post", 1.0f);
    ms.lim_bypass = p.flag("lim_bypass", 1);
    ms.volume = p.f("volume", 0.8f);

    py::object fx = get_item(obj, "effects");
    if (fx && !fx.is_none()) {
        int index = 0;
        for (const py::handle &item : fx) {
            if (index >= 2) {
                break;
            }
            ms.effects[index] = parse_effect(item);
            ++index;
        }
    }
    return ms;
}

}  // namespace

RoomSpec parse_room(const py::handle &doc, int fallback_sample_rate, int fallback_block_size) {
    if (!doc || doc.is_none()) {
        throw std::invalid_argument("room document must be a mapping");
    }
    RoomSpec spec;
    spec.sample_rate = fallback_sample_rate;
    spec.block_size = fallback_block_size;
    py::object audio = get_item(doc, "audio");
    if (audio && !audio.is_none()) {
        Params p(audio);
        spec.sample_rate = p.i("sample_rate", fallback_sample_rate);
        spec.block_size = p.i("block_size", fallback_block_size);
    }
    if (spec.sample_rate <= 0 || spec.block_size <= 0) {
        throw std::invalid_argument("audio sample_rate and block_size must be positive");
    }

    py::object machines = get_item(doc, "machines");
    if (!machines || machines.is_none()) {
        throw std::invalid_argument("room document is missing 'machines'");
    }
    int index = 0;
    for (const py::handle &item : machines) {
        RoomSlotSpec slot;
        if (!item.is_none()) {
            try {
                slot.machine = parse_machine(item);
            } catch (const std::exception &err) {
                throw std::invalid_argument("machine slot " + std::to_string(index) + ": " +
                                            err.what());
            }
            slot.present = true;
            py::object fx = get_item(item, "effects");
            if (fx && !fx.is_none()) {
                int k = 0;
                for (const py::handle &entry : fx) {
                    if (k >= 2) {
                        break;
                    }
                    try {
                        slot.effects[k] = parse_effect(entry);
                    } catch (const std::exception &err) {
                        throw std::invalid_argument("machine slot " + std::to_string(index) +
                                                    " effect " + std::to_string(k) + ": " +
                                                    err.what());
                    }
                    ++k;
                }
            }
            slot.mixer = parse_mixer(get_item(item, "mixer"));
        }
        spec.slots.push_back(std::move(slot));
        ++index;
    }
    spec.master = parse_master(get_item(doc, "master"));
    return spec;
}

std::vector<float> parse_sample_array(const py::handle &array) {
    py::array_t<float, py::array::c_style | py::array::forcecast> arr =
        py::cast<py::array_t<float, py::array::c_style | py::array::forcecast>>(
            py::reinterpret_borrow<py::object>(array));
    if (arr.ndim() != 1) {
        throw std::invalid_argument("sample data must be a 1-D mono array");
    }
    std::vector<float> out(static_cast<std::size_t>(arr.shape(0)));
    const float *src = arr.data();
    for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = std::isfinite(src[i]) ? src[i] : 0.0f;
    }
    return out;
}

}  // namespace refrag
