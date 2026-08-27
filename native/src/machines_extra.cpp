// Vocoder and Modular machines.
#include <algorithm>
#include <cmath>

#include "machine.h"

namespace refrag {

namespace {

constexpr double kVocoderBandCenters[kVocoderBands] = {180.0,  300.0,  480.0,  760.0,
                                                       1200.0, 1900.0, 3000.0, 4800.0};

const MachineAudio *slot_audio(const RenderContext &ctx, int slot) {
    if (slot < 0 || slot >= ctx.slot_count) {
        return nullptr;
    }
    if (ctx.outputs != nullptr && ctx.outputs[slot].l != nullptr) {
        return &ctx.outputs[slot];
    }
    if (ctx.prev_outputs != nullptr && ctx.prev_outputs[slot].l != nullptr) {
        return &ctx.prev_outputs[slot];
    }
    return nullptr;
}

}  // namespace

// ---------------------------------------------------------------------------
// Vocoder: 8-band analysis of a sample or machine modulator
// ---------------------------------------------------------------------------

void MachineEngine::note_on_vocoder(int note, float vel, int offset, int flags) {
    if (note >= 24 && note < 30) {
        current_mod_slot_ = note - 24;
        return;
    }
    current_mod_slot_ = spec_.mod_sel;
    trim_poly(spec_.poly);
    Voice &v = push_voice(note, vel, offset, flags);
    v.mod_slot = spec_.mod_sel;
}

void MachineEngine::vocoder_modulator(std::size_t n, const RenderContext &ctx) {
    std::fill(mod_buf_.begin(), mod_buf_.begin() + n, 0.0f);
    int slot = current_mod_slot_;
    if (slot < 0 || slot >= static_cast<int>(spec_.modulators.size())) {
        return;
    }
    const VocoderModulator &mod = spec_.modulators[slot];
    if (mod.machine >= 0) {
        const MachineAudio *audio = slot_audio(ctx, mod.machine);
        if (audio == nullptr) {
            return;
        }
        for (std::size_t i = 0; i < n; ++i) {
            mod_buf_[i] = (audio->l[i] + audio->r[i]) * 0.5f;
        }
        return;
    }
    if (mod.source.empty() || bank_ == nullptr) {
        return;
    }
    if (streams_.size() <= static_cast<std::size_t>(slot)) {
        streams_.resize(static_cast<std::size_t>(slot) + 1);
    }
    SampleStream &stream = streams_[slot];
    if (!stream.sample || stream.name != mod.source) {
        SamplePtr buf = bank_->get(mod.source);
        if (!buf || buf->data.size() < 2) {
            return;
        }
        stream.name = mod.source;
        stream.sample = buf;
        stream.position = 0.0;
        stream.direction = 1;
        stream.pingpong = false;
        stream.rate = buf->source_rate / sample_rate_;
    }
    const std::vector<float> &buf = stream.sample->data;
    double end = std::max(1.0, static_cast<double>(buf.size()) - 1.0);
    double pos = stream.position;
    int direction = stream.direction;
    for (std::size_t i = 0; i < n; ++i) {
        mod_buf_[i] = fetch_linear(buf, pos);
        double next_pos;
        if (stream.pingpong) {
            next_pos = pos + stream.rate * direction;
            int guard = 0;
            while ((next_pos >= end || next_pos < 0.0) && guard++ < 64) {
                if (next_pos >= end) {
                    next_pos = end - (next_pos - end);
                    direction = -1;
                } else {
                    next_pos = -next_pos;
                    direction = 1;
                }
            }
        } else {
            next_pos = pos + stream.rate;
            int guard = 0;
            while (next_pos >= end && guard++ < 64) {
                next_pos -= end;
            }
        }
        pos = next_pos;
    }
    stream.position = pos;
    stream.direction = direction;
}

void MachineEngine::render_vocoder(float *l, float *r, std::size_t n, const RenderContext &ctx) {
    const VocoderParams &p = spec_.vocoder;
    std::fill(carrier_buf_.begin(), carrier_buf_.begin() + n, 0.0f);

    const double attack = std::max(1.0, sample_rate_ * 0.005);
    const double decay = 1.0;
    const double sustain = 1.0;
    const double release = std::max(1.0, sample_rate_ * 0.08);
    const int wave = p.wave == 0 ? 2 : 4;
    const double detune = p.unison * 0.015;
    const double sub_mix = p.sub;
    const double noise_mix = p.noise;

    // Deterministic noise, reseeded per block like the Python reference.
    Rng noise(12345);

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        double freq = note_freq(voice.note);
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, attack, decay, sustain, release, t_release);
            if (env <= 1e-5 && voice.released_at >= 0 && t >= voice.released_at) {
                continue;
            }
            voice.phase[0] += freq / sample_rate_;
            voice.phase[1] += freq * (1.0 - detune) / sample_rate_;
            voice.phase[2] += freq * (1.0 + detune) / sample_rate_;
            float main = osc_wave(wave, voice.phase[0]);
            float uni = 0.5f * (osc_wave(wave, voice.phase[1]) + osc_wave(wave, voice.phase[2]));
            float sub = static_cast<float>(sub_mix) * osc_wave(4, voice.phase[0] * 0.5);
            float noise_sample = static_cast<float>(noise_mix) * noise.next_bipolar();
            carrier_buf_[i] += (0.55f * main + 0.45f * uni + 0.4f * sub + 0.12f * noise_sample) *
                               static_cast<float>(env) * voice.vel;
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice.released_at >= 0) {
            double t_end = static_cast<double>(voice.t - 1 - voice.start_offset);
            if (t_end >= t_release + release) {
                voice.dead = true;
            }
        }
    }

    // An external carrier replaces the internal oscillator bank.
    if (p.carrier > 0) {
        const MachineAudio *audio = slot_audio(ctx, p.carrier - 1);
        if (audio != nullptr) {
            for (std::size_t i = 0; i < n; ++i) {
                carrier_buf_[i] = (audio->l[i] + audio->r[i]) * 0.5f;
            }
        } else {
            std::fill(carrier_buf_.begin(), carrier_buf_.begin() + n, 0.0f);
        }
    }

    vocoder_modulator(n, ctx);

    std::fill(lfo1_.begin(), lfo1_.begin() + n, 0.0f);
    float coef = static_cast<float>(clampd(0.55 + p.slew * 0.42, 0.0, 0.995));
    for (int b = 0; b < kVocoderBands; ++b) {
        mod_filters_[b].set(FilterType::BandPass, kVocoderBandCenters[b], 1.2, sample_rate_);
        car_filters_[b].set(FilterType::BandPass, kVocoderBandCenters[b], 1.2, sample_rate_);
        float band_gain = p.bands[b];
        float peak = 0.0f;
        for (std::size_t i = 0; i < n; ++i) {
            float mod_band = mod_filters_[b].process_one(mod_buf_[i]);
            float car_band = car_filters_[b].process_one(carrier_buf_[i]);
            float env = followers_[b].process_one(std::fabs(mod_band), coef);
            peak = std::max(peak, env);
            lfo1_[i] += car_band * env * band_gain;
        }
        band_vu_[b] = clampf(peak, 0.0f, 1.0f);
    }
    if (p.hf_bypass > 0.0f) {
        for (std::size_t i = 0; i < n; ++i) {
            lfo1_[i] += mod_buf_[i] * p.hf_bypass * 0.2f;
        }
    }
    if (p.dry > 0.0f) {
        for (std::size_t i = 0; i < n; ++i) {
            lfo1_[i] += mod_buf_[i] * p.dry * 0.25f;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        float value = lfo1_[i] * p.volume;
        l[i] = value;
        r[i] = value;
    }
}

// ---------------------------------------------------------------------------
// Modular
// ---------------------------------------------------------------------------

void MachineEngine::modular_prepare() {
    if (modular_dirty_) {
        mod_nodes_.assign(spec_.components.size(), ModularNode{});
        mod_left_sources_.clear();
        mod_right_sources_.clear();
        mod_volume_sources_.clear();
        for (std::size_t i = 0; i < spec_.components.size(); ++i) {
            mod_nodes_[i].kind = spec_.components[i].kind;
            mod_nodes_[i].present = spec_.components[i].present;
        }
        for (const ModularWire &wire : spec_.wires) {
            bool src_ok = wire.src >= 0 ? (wire.src < static_cast<int>(mod_nodes_.size()) &&
                                           mod_nodes_[wire.src].present)
                                        : (wire.src == kPanelNoteCv || wire.src == kPanelVelocity ||
                                           wire.src == kPanelModWheel);
            if (!src_ok) {
                continue;
            }
            if (wire.dst == kPanelLeftOut) {
                if (wire.src >= 0) {
                    mod_left_sources_.push_back(wire.src);
                }
                continue;
            }
            if (wire.dst == kPanelRightOut) {
                if (wire.src >= 0) {
                    mod_right_sources_.push_back(wire.src);
                }
                continue;
            }
            if (wire.dst == kPanelVolumeMod) {
                if (wire.src >= 0) {
                    mod_volume_sources_.push_back(wire.src);
                }
                continue;
            }
            if (wire.dst < 0 || wire.dst >= static_cast<int>(mod_nodes_.size()) ||
                !mod_nodes_[wire.dst].present) {
                continue;
            }
            ModularNode &node = mod_nodes_[wire.dst];
            int input = wire.dst_input;
            if (input < 0 || input >= modular_input_count(node.kind) || input >= 3) {
                continue;
            }
            if (wire.src >= 0) {
                node.sources[input].push_back(wire.src);
            } else if (wire.src == kPanelNoteCv) {
                node.from_note[input] = true;
            } else if (wire.src == kPanelVelocity) {
                node.from_velocity[input] = true;
            } else if (wire.src == kPanelModWheel) {
                node.from_mod_wheel[input] = true;
            }
        }
        modular_dirty_ = false;
    }
    for (std::size_t i = 0; i < mod_nodes_.size() && i < spec_.components.size(); ++i) {
        mod_nodes_[i].params = spec_.components[i].params;
    }
}

void MachineEngine::render_modular(float *l, float *r, std::size_t n) {
    modular_prepare();
    if (mod_nodes_.empty()) {
        return;
    }

    Voice *voice = nullptr;
    for (auto &v : voices_) {
        if (!v.dead && (voice == nullptr || v.serial > voice->serial)) {
            voice = &v;
        }
    }
    if (voice == nullptr) {
        return;
    }

    bool has_envelope = false;
    double max_release = std::max(1.0, sample_rate_ * 0.02);
    for (const auto &node : mod_nodes_) {
        if (node.present && node.kind == ModularKind::Envelope) {
            has_envelope = true;
            max_release = std::max(max_release, env_frames(node.params[3], sample_rate_));
        }
    }

    const double note_cv = (voice->note - 60.0) / 12.0;
    const float velocity = voice->vel;
    double t_release =
        voice->released_at < 0
            ? -1.0
            : static_cast<double>(voice->released_at) - static_cast<double>(voice->start_offset);
    const double gate_tc = std::max(1.0, sample_rate_ * 0.01);
    const float gain = spec_.modular.out_gain * spec_.modular.volume;

    for (std::size_t i = 0; i < n; ++i) {
        std::int64_t t = voice->t + static_cast<std::int64_t>(i);
        if (t < voice->start_offset) {
            continue;
        }
        double local = static_cast<double>(t - voice->start_offset);

        for (std::size_t idx = 0; idx < mod_nodes_.size(); ++idx) {
            ModularNode &node = mod_nodes_[idx];
            if (!node.present) {
                continue;
            }
            float in[3] = {0.0f, 0.0f, 0.0f};
            bool wired[3] = {false, false, false};
            for (int k = 0; k < 3; ++k) {
                for (int src : node.sources[k]) {
                    in[k] += mod_nodes_[src].out;
                    wired[k] = true;
                }
                if (node.from_note[k]) {
                    in[k] += static_cast<float>(note_cv);
                    wired[k] = true;
                }
                if (node.from_velocity[k]) {
                    in[k] += velocity;
                    wired[k] = true;
                }
                if (node.from_mod_wheel[k]) {
                    wired[k] = true;
                }
            }

            switch (node.kind) {
            case ModularKind::Oscillator: {
                double base = wired[0] ? 60.0 + in[0] * 12.0 : static_cast<double>(voice->note);
                double pitch = base + node.params[1] * 12.0 + node.params[2] +
                               node.params[3] / 100.0;
                double freq = note_freq(pitch) * (1.0 + node.params[4] * 4.0 * in[1]);
                double inc = freq / sample_rate_;
                node.phase += inc;
                node.out = osc_wave(static_cast<int>(node.params[0]), node.phase, std::fabs(inc),
                                    &noise_rng_);
                break;
            }
            case ModularKind::Lfo: {
                node.phase += node.params[1] / sample_rate_;
                node.out = lfo_wave(static_cast<int>(node.params[0]), node.phase) * node.params[2];
                break;
            }
            case ModularKind::Envelope: {
                double a = env_frames(node.params[0], sample_rate_);
                double d = env_frames(node.params[1], sample_rate_);
                double s = clampd(node.params[2], 0.0, 1.0);
                double rel = env_frames(node.params[3], sample_rate_);
                node.out = static_cast<float>(adsr(local, a, d, s, rel, t_release));
                break;
            }
            case ModularKind::Filter: {
                double norm = clampd(node.params[1] + node.params[3] * in[1], 0.0, 1.0);
                double fc = cutoff_hz(norm);
                double f = clampd(2.0 * std::sin(kTwoPi * fc / (2.0 * sample_rate_)), 0.0, 0.99);
                double damp = clampd(1.0 - node.params[2] * 0.97, 0.03, 1.0);
                float hp = in[0] - node.svf_lp - static_cast<float>(damp) * node.svf_bp;
                node.svf_bp += static_cast<float>(f) * hp;
                node.svf_bp = clampf(node.svf_bp, -8.0f, 8.0f);
                node.svf_lp += static_cast<float>(f) * node.svf_bp;
                node.svf_lp = clampf(node.svf_lp, -8.0f, 8.0f);
                int type = static_cast<int>(node.params[0]);
                node.out = type == 0 ? node.svf_lp : (type == 1 ? hp : node.svf_bp);
                break;
            }
            case ModularKind::Vca:
                node.out = in[0] * node.params[0] * (wired[1] ? in[1] : 1.0f);
                break;
            case ModularKind::Mixer2:
                node.out = in[0] * node.params[0] + in[1] * node.params[1];
                break;
            case ModularKind::Noise: {
                float white = noise_rng_.next_bipolar();
                float color = clampf(node.params[0], 0.0f, 0.99f);
                node.sh_value = (1.0f - color) * white + color * node.sh_value;
                node.out = color > 0.0f ? node.sh_value * (1.0f + color * 2.0f) : white;
                break;
            }
            case ModularKind::SampleHold: {
                double prev = node.sh_phase;
                node.sh_phase += node.params[0] / sample_rate_;
                if (std::floor(node.sh_phase) != std::floor(prev)) {
                    node.sh_value = wired[0] ? in[0] : noise_rng_.next_bipolar();
                }
                node.out = node.sh_value;
                break;
            }
            case ModularKind::ModDelay: {
                std::size_t cap =
                    std::max<std::size_t>(4, static_cast<std::size_t>(sample_rate_ * 1.0));
                if (node.delay.size() != cap) {
                    node.delay.assign(cap, 0.0f);
                    node.delay_idx = 0;
                }
                double d = (0.005 + clampd(node.params[0], 0.0, 1.0) * 0.995) * sample_rate_;
                std::size_t dd =
                    static_cast<std::size_t>(clampd(d, 1.0, static_cast<double>(cap) - 1.0));
                std::size_t read = (node.delay_idx + cap - dd) % cap;
                float delayed = node.delay[read];
                node.delay[node.delay_idx] = in[0] + delayed * node.params[1];
                node.delay_idx = (node.delay_idx + 1) % cap;
                node.out = in[0] * (1.0f - node.params[2]) + delayed * node.params[2];
                break;
            }
            case ModularKind::Shaper: {
                int mode = static_cast<int>(node.params[1]);
                float drive = node.params[0];
                if (mode == 1) {
                    node.out = clampf(in[0] * (1.0f + drive * 8.0f), -1.0f, 1.0f);
                } else if (mode == 2) {
                    node.out = distort_sample(in[0] * (1.0f + drive * 2.0f), 3, drive);
                } else {
                    double k = 1.0 + drive * 8.0;
                    node.out = static_cast<float>(std::tanh(in[0] * k) / std::tanh(k));
                }
                break;
            }
            case ModularKind::Crossfade: {
                float m = clampf(node.params[0] + (wired[2] ? in[2] * 0.5f : 0.0f), 0.0f, 1.0f);
                node.out = in[0] * (1.0f - m) + in[1] * m;
                break;
            }
            case ModularKind::Invert:
                node.out = -in[0];
                break;
            }
            if (!std::isfinite(node.out)) {
                node.out = 0.0f;
            }
        }

        float left = 0.0f;
        for (int src : mod_left_sources_) {
            left += mod_nodes_[src].out;
        }
        float right = 0.0f;
        if (mod_right_sources_.empty()) {
            right = left;
        } else {
            for (int src : mod_right_sources_) {
                right += mod_nodes_[src].out;
            }
        }
        float vol_mod = 1.0f;
        if (!mod_volume_sources_.empty()) {
            float sum = 0.0f;
            for (int src : mod_volume_sources_) {
                sum += mod_nodes_[src].out;
            }
            vol_mod = clampf(sum, 0.0f, 2.0f);
        }
        float gate = 1.0f;
        if (!has_envelope && voice->released_at >= 0 && t >= voice->released_at) {
            gate = static_cast<float>(
                std::exp(-static_cast<double>(t - voice->released_at) / gate_tc));
        }
        float g = gain * vol_mod * gate * 0.5f;
        l[i] = left * g;
        r[i] = right * g;
    }

    voice->t += static_cast<std::int64_t>(n);
    if (voice->released_at >= 0) {
        double since = static_cast<double>(voice->t - voice->released_at);
        if (since >= max_release + gate_tc * 8.0) {
            voice->dead = true;
        }
    }
    for (auto &v : voices_) {
        if (&v != voice && !v.dead) {
            v.dead = true;
        }
    }
}

}  // namespace refrag
