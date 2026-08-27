#include "machine.h"

#include <algorithm>
#include <cmath>

namespace refrag {

namespace {

inline void mix_centered(float *l, float *r, std::size_t i, float sample, float gain, float pan) {
    l[i] += sample * gain * (1.0f - pan) * 0.5f;
    r[i] += sample * gain * (1.0f + pan) * 0.5f;
}

bool modular_topology_equal(const MachineSpec &a, const MachineSpec &b) {
    if (a.components.size() != b.components.size() || a.wires.size() != b.wires.size()) {
        return false;
    }
    for (std::size_t i = 0; i < a.components.size(); ++i) {
        if (a.components[i].present != b.components[i].present ||
            a.components[i].kind != b.components[i].kind) {
            return false;
        }
    }
    for (std::size_t i = 0; i < a.wires.size(); ++i) {
        if (a.wires[i].src != b.wires[i].src || a.wires[i].dst != b.wires[i].dst ||
            a.wires[i].dst_input != b.wires[i].dst_input) {
            return false;
        }
    }
    return true;
}

}  // namespace

MachineEngine::MachineEngine(const MachineSpec &spec, double sample_rate, const SampleBank *bank,
                             std::uint64_t seed)
    : spec_(spec), sample_rate_(sample_rate > 0.0 ? sample_rate : kDefaultSampleRate),
      bank_(bank), rng_(seed * 2654435761u + 1u), noise_rng_(seed * 40503u + 7u) {
    expr_a_.compile(spec_.expr_a);
    expr_b_.compile(spec_.expr_b);
    modular_dirty_ = true;
    reset_runtime();
}

void MachineEngine::reset_runtime() {
    voices_.clear();
    band_vu_.fill(0.0f);
    lfo1_phase_ = 0.0;
    lfo2_phase_ = 0.0;
    leslie_phase_ = 0.0;
    dc_x_[0] = dc_x_[1] = 0.0f;
    dc_y_[0] = dc_y_[1] = 0.0f;
    current_mod_slot_ = spec_.mod_sel;
    streams_.assign(std::max<std::size_t>(spec_.modulators.size(), 6), SampleStream{});
    refresh_sample_rate_state();
}

void MachineEngine::refresh_sample_rate_state() {
    pcm_filter_[0].reset();
    pcm_filter_[1].reset();
    for (int i = 0; i < kVocoderBands; ++i) {
        mod_filters_[i].reset();
        car_filters_[i].reset();
        followers_[i].reset(0.0f);
    }
    for (auto &stream : streams_) {
        // Playback ratios are derived from the engine rate; force a refresh.
        stream.sample.reset();
        stream.name.clear();
        stream.position = 0.0;
        stream.direction = 1;
    }
    for (auto &node : mod_nodes_) {
        node.delay.clear();
        node.delay_idx = 0;
    }
    modular_dirty_ = true;
}

void MachineEngine::update(const MachineSpec &spec, double sample_rate) {
    double sr = sample_rate > 0.0 ? sample_rate : sample_rate_;
    bool kind_changed = spec.kind != spec_.kind;
    bool rate_changed = sr != sample_rate_;
    bool topology_changed = !modular_topology_equal(spec_, spec);
    bool expr_changed = spec.expr_a != expr_a_.source() || spec.expr_b != expr_b_.source();

    spec_ = spec;
    sample_rate_ = sr;
    if (expr_changed) {
        expr_a_.compile(spec_.expr_a);
        expr_b_.compile(spec_.expr_b);
    }
    if (streams_.size() < std::max<std::size_t>(spec_.modulators.size(), 6)) {
        streams_.resize(std::max<std::size_t>(spec_.modulators.size(), 6));
    }
    if (kind_changed) {
        modular_dirty_ = true;
        reset_runtime();
        return;
    }
    if (rate_changed) {
        refresh_sample_rate_state();
    }
    if (topology_changed) {
        modular_dirty_ = true;
    }
}

void MachineEngine::compact() {
    voices_.erase(std::remove_if(voices_.begin(), voices_.end(),
                                 [](const Voice &v) { return v.dead; }),
                  voices_.end());
}

void MachineEngine::trim_poly(int poly) {
    poly = std::max(1, std::min(poly, kMaxVoices));
    for (;;) {
        int live = 0;
        Voice *victim = nullptr;
        for (auto &v : voices_) {
            if (v.dead) {
                continue;
            }
            ++live;
            if (victim == nullptr || v.serial < victim->serial) {
                victim = &v;
            }
        }
        if (live < poly || victim == nullptr) {
            break;
        }
        victim->dead = true;
    }
    compact();
}

Voice &MachineEngine::push_voice(int note, float vel, int offset, int flags) {
    Voice v;
    v.note = note;
    v.vel = vel;
    v.flags = flags;
    v.start_offset = std::max(0, offset);
    v.serial = next_serial();
    voices_.push_back(std::move(v));
    return voices_.back();
}

void MachineEngine::note_on(int note, float vel, int offset, int flags) {
    switch (spec_.kind) {
    case MachineKind::BeatBox:
        note_on_beatbox(note, vel, offset, flags);
        return;
    case MachineKind::PCMSynth:
        note_on_pcmsynth(note, vel, offset, flags);
        return;
    case MachineKind::Vocoder:
        note_on_vocoder(note, vel, offset, flags);
        return;
    default:
        break;
    }

    double previous_note = static_cast<double>(note);
    bool had_voice = false;
    for (const auto &v : voices_) {
        if (!v.dead) {
            previous_note = v.note;
            had_voice = true;
        }
    }

    if (spec_.kind == MachineKind::BassLine || spec_.kind == MachineKind::Modular) {
        // Monophonic families: the newest note takes over the machine.
        for (auto &v : voices_) {
            v.dead = true;
        }
        compact();
    }

    trim_poly(spec_.poly);
    Voice &v = push_voice(note, vel, offset, flags);
    if (spec_.kind == MachineKind::BassLine) {
        bool slide = (flags & 2) != 0 || spec_.bass.legacy_glide != 0;
        v.note_from = (had_voice && slide) ? previous_note : static_cast<double>(note);
    }
    if (spec_.kind == MachineKind::KSSynth) {
        note_on_kssynth(v);
    }
}

void MachineEngine::note_off(int note, int offset) {
    for (auto &v : voices_) {
        if (!v.dead && v.note == note && v.released_at < 0) {
            v.released_at = v.t + std::max(0, offset);
        }
    }
}

void MachineEngine::all_off() {
    for (auto &v : voices_) {
        if (!v.dead && v.released_at < 0) {
            v.released_at = v.t;
        }
    }
}

bool MachineEngine::active() const {
    for (const auto &v : voices_) {
        if (!v.dead) {
            return true;
        }
    }
    return false;
}

int MachineEngine::live_voice_count() const {
    int count = 0;
    for (const auto &v : voices_) {
        if (!v.dead) {
            ++count;
        }
    }
    return count;
}

void MachineEngine::ensure_scratch(std::size_t n) {
    auto grow = [n](std::vector<float> &v) {
        if (v.size() < n) {
            v.assign(n, 0.0f);
        }
    };
    grow(lfo1_);
    grow(lfo2_);
    grow(cutoff_);
    grow(scratch_a_);
    grow(scratch_b_);
    grow(mod_buf_);
    grow(carrier_buf_);
}

void MachineEngine::fill_lfo(std::vector<float> &dst, std::size_t n, int wave, double rate,
                             double &phase, double phase_offset) {
    double step = rate / sample_rate_;
    for (std::size_t i = 0; i < n; ++i) {
        dst[i] = lfo_wave(wave, phase + static_cast<double>(i) * step + phase_offset);
    }
    phase += static_cast<double>(n) * step;
    if (phase > 1e9) {
        phase = std::fmod(phase, 1.0);
    }
}

void MachineEngine::render(float *l, float *r, std::size_t n, const RenderContext &ctx) {
    std::fill(l, l + n, 0.0f);
    std::fill(r, r + n, 0.0f);
    if (n == 0) {
        return;
    }
    ensure_scratch(n);
    switch (spec_.kind) {
    case MachineKind::SubSynth:
        render_subsynth(l, r, n);
        break;
    case MachineKind::PCMSynth:
        render_pcmsynth(l, r, n);
        break;
    case MachineKind::BassLine:
        render_bassline(l, r, n);
        break;
    case MachineKind::BeatBox:
        render_beatbox(l, r, n);
        break;
    case MachineKind::PadSynth:
        render_padsynth(l, r, n);
        break;
    case MachineKind::BitSynth:
        render_bitsynth(l, r, n);
        break;
    case MachineKind::Modular:
        render_modular(l, r, n);
        break;
    case MachineKind::Organ:
        render_organ(l, r, n);
        break;
    case MachineKind::Vocoder:
        render_vocoder(l, r, n, ctx);
        break;
    case MachineKind::FMSynth:
        render_fmsynth(l, r, n);
        break;
    case MachineKind::KSSynth:
        render_kssynth(l, r, n);
        break;
    }
    compact();
    for (std::size_t i = 0; i < n; ++i) {
        if (!std::isfinite(l[i])) {
            l[i] = 0.0f;
        }
        if (!std::isfinite(r[i])) {
            r[i] = 0.0f;
        }
    }
}

// ---------------------------------------------------------------------------
// BeatBox: one sampled channel per note, with mute groups
// ---------------------------------------------------------------------------

void MachineEngine::note_on_beatbox(int note, float vel, int offset, int flags) {
    if (note < 0 || note >= static_cast<int>(spec_.channels.size())) {
        return;
    }
    const BeatBoxChannel &ch = spec_.channels[note];
    SamplePtr buf = bank_ ? bank_->get(ch.sample) : nullptr;
    if (!buf || buf->data.size() < 2) {
        return;
    }
    int cut_at = std::max(0, offset);
    if (ch.mute_group > 0) {
        for (auto &v : voices_) {
            if (!v.dead && v.mute_group == ch.mute_group) {
                v.stop_at = v.t + cut_at;
            }
        }
    }
    trim_poly(spec_.poly);

    double decay = clampd(ch.decay, 0.0, 1.0);
    double len = static_cast<double>(buf->data.size());
    double play_end = std::max(32.0, std::floor((len - 1.0) * (0.12 + 0.88 * std::pow(decay, 0.8))));

    Voice &v = push_voice(note, vel, offset, flags);
    v.sample = buf;
    v.rate = (buf->source_rate / sample_rate_) * std::pow(2.0, ch.tune / 12.0);
    v.pan = ch.pan;
    v.gain = ch.volume * spec_.beat.volume;
    v.punch = ch.punch;
    v.play_end = std::min(len - 1.0, play_end);
    v.mute_group = ch.mute_group;
}

void MachineEngine::render_beatbox(float *l, float *r, std::size_t n) {
    double punch_tc = std::max(1.0, sample_rate_ * 0.012);
    for (auto &voice : voices_) {
        if (voice.dead || !voice.sample) {
            continue;
        }
        const std::vector<float> &buf = voice.sample->data;
        double limit = static_cast<double>(buf.size()) - 1.0;
        double pos = voice.position;
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            if (pos >= voice.play_end || pos >= limit) {
                voice.dead = true;
                break;
            }
            float sample = fetch_linear(buf, pos);
            double punch_env = std::exp(-static_cast<double>(t - voice.start_offset) / punch_tc);
            double rate = voice.rate * (1.0 + voice.punch * 0.35 * punch_env);
            float gain = static_cast<float>(voice.gain * voice.vel *
                                            (1.0 + voice.punch * 0.2 * punch_env));
            float tail = 1.0f;
            double remaining = voice.play_end - pos;
            if (remaining < 64.0) {
                tail *= static_cast<float>(std::max(0.0, remaining / 64.0));
            }
            if (voice.stop_at >= 0 && t >= voice.stop_at) {
                tail *= static_cast<float>(
                    std::max(0.0, 1.0 - static_cast<double>(t - voice.stop_at) / 64.0));
                if (tail <= 0.0f) {
                    voice.dead = true;
                    break;
                }
            }
            mix_centered(l, r, i, sample, gain * tail, voice.pan);
            pos += rate;
        }
        voice.position = pos;
        voice.t += static_cast<std::int64_t>(n);
    }
}

// ---------------------------------------------------------------------------
// PCMSynth: multisampled zones with loop modes
// ---------------------------------------------------------------------------

namespace {

void region_bounds(std::size_t buf_len, double start_norm, double end_norm, std::size_t *out_start,
                   std::size_t *out_end) {
    if (buf_len <= 1) {
        *out_start = 0;
        *out_end = std::max<std::size_t>(1, buf_len);
        return;
    }
    double span = static_cast<double>(buf_len - 1);
    std::size_t start = static_cast<std::size_t>(clampd(start_norm, 0.0, 1.0) * span);
    std::size_t end = static_cast<std::size_t>(clampd(end_norm, 0.0, 1.0) * span);
    if (end <= start + 1) {
        start = 0;
        end = buf_len - 1;
    }
    *out_start = start;
    *out_end = std::max(start + 1, std::min(buf_len - 1, end));
}

}  // namespace

void MachineEngine::note_on_pcmsynth(int note, float vel, int offset, int flags) {
    std::vector<const PcmZone *> zones;
    for (const auto &zone : spec_.zones) {
        if (zone.low <= note && note <= zone.high) {
            zones.push_back(&zone);
        }
    }
    if (zones.empty()) {
        return;
    }
    for (const PcmZone *zone : zones) {
        trim_poly(spec_.poly);
        SamplePtr buf = bank_ ? bank_->get(zone->sample) : nullptr;
        if (!buf || buf->data.size() < 2) {
            continue;
        }
        std::size_t start = 0;
        std::size_t end = 1;
        region_bounds(buf->data.size(), zone->start, zone->end, &start, &end);
        int mode = zone->mode;
        double delta = (note - static_cast<double>(zone->root)) + spec_.pcm.octave * 12.0 +
                       spec_.pcm.semis + (spec_.pcm.cents + zone->tune) / 100.0;
        PcmLoop loop_kind = PcmLoop::None;
        bool intro_loop = false;
        std::size_t release_end = end;
        double position = static_cast<double>(start);
        if (mode == 2) {
            loop_kind = PcmLoop::Forward;
        } else if (mode == 3) {
            loop_kind = PcmLoop::PingPong;
        } else if (mode == 4) {
            loop_kind = PcmLoop::Forward;
            intro_loop = true;
            release_end = buf->data.size() - 1;
            position = 0.0;
        } else if (mode == 5) {
            loop_kind = PcmLoop::PingPong;
            intro_loop = true;
            release_end = buf->data.size() - 1;
            position = 0.0;
        }
        Voice &v = push_voice(note, vel, offset, flags);
        v.sample = buf;
        v.rate = (buf->source_rate / sample_rate_) * std::pow(2.0, delta / 12.0);
        v.position = position;
        v.pan = zone->pan;
        v.gain = zone->level * spec_.pcm.volume;
        v.loop_start = start;
        v.loop_end = end;
        v.release_end = std::max(end, release_end);
        v.loop_kind = loop_kind;
        v.intro_loop = intro_loop;
    }
}

namespace {

// Advances one PCM voice cursor, honouring the zone's loop mode.
bool advance_pcm_voice(const Voice &voice, double &pos, int &direction, double inc, bool released) {
    inc = std::max(1e-6, inc);
    if (voice.loop_kind != PcmLoop::None && !released) {
        double lo = static_cast<double>(voice.loop_start);
        double hi = static_cast<double>(std::max(voice.loop_start + 1, voice.loop_end));
        if (voice.intro_loop && pos < lo) {
            double next_pos = pos + inc;
            if (next_pos < hi) {
                pos = next_pos;
                direction = 1;
                return false;
            }
            pos = std::max(lo, next_pos);
            direction = 1;
        }
        if (voice.loop_kind == PcmLoop::Forward) {
            double next_pos = pos + inc;
            int fwd_guard = 0;
            while (next_pos >= hi && fwd_guard++ < 64) {
                next_pos = lo + (next_pos - hi);
            }
            pos = next_pos;
            direction = 1;
            return false;
        }
        double next_pos = pos + inc * direction;
        int guard = 0;
        while ((next_pos >= hi || next_pos < lo) && guard++ < 64) {
            if (next_pos >= hi) {
                double over = next_pos - hi;
                next_pos = hi - over;
                direction = -1;
            } else if (next_pos < lo) {
                double over = lo - next_pos;
                next_pos = lo + over;
                direction = 1;
            }
        }
        pos = next_pos;
        return false;
    }
    if (voice.loop_kind == PcmLoop::PingPong && direction < 0) {
        direction = 1;
    }
    double next_pos = pos + inc * direction;
    pos = next_pos;
    return next_pos >= static_cast<double>(voice.release_end);
}

}  // namespace

void MachineEngine::render_pcmsynth(float *l, float *r, std::size_t n) {
    const PCMSynthParams &p = spec_.pcm;
    fill_lfo(lfo1_, n, p.lfo_wave, p.lfo_rate, lfo1_phase_, 0.0);
    bool pitch_mod = p.lfo_target == 1;
    bool cutoff_mod = p.lfo_target == 2;
    bool vol_mod = p.lfo_target == 3;
    for (std::size_t i = 0; i < n; ++i) {
        float lv = lfo1_[i];
        scratch_a_[i] = pitch_mod
                            ? static_cast<float>(std::pow(2.0, (lv * p.lfo_depth * 2.0) / 12.0))
                            : 1.0f;
        cutoff_[i] = cutoff_mod
                         ? clampf(p.flt_cutoff + lv * p.lfo_depth * 0.45f, 0.0f, 1.0f)
                         : p.flt_cutoff;
        scratch_b_[i] = vol_mod ? clampf(1.0f + lv * p.lfo_depth * 0.5f, 0.0f, 2.0f) : 1.0f;
    }

    double attack = env_frames(p.vol_attack, sample_rate_);
    double decay = env_frames(p.vol_decay, sample_rate_);
    double sustain = p.vol_sustain;
    double release = env_frames(p.vol_release, sample_rate_);

    for (auto &voice : voices_) {
        if (voice.dead || !voice.sample) {
            continue;
        }
        const std::vector<float> &buf = voice.sample->data;
        double limit = static_cast<double>(buf.size()) - 1.0;
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        double pos = voice.position;
        int direction = voice.direction;
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            if (pos >= limit) {
                voice.dead = true;
                break;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, attack, decay, sustain, release, t_release);
            float gain = static_cast<float>(env) * voice.gain * voice.vel * scratch_b_[i];
            bool released = voice.released_at >= 0 && t >= voice.released_at;
            if (gain <= 1e-5f && released) {
                if (advance_pcm_voice(voice, pos, direction, voice.rate, true)) {
                    voice.dead = true;
                    break;
                }
                continue;
            }
            mix_centered(l, r, i, fetch_linear(buf, pos), gain, voice.pan);
            if (advance_pcm_voice(voice, pos, direction, voice.rate * scratch_a_[i], released)) {
                voice.dead = true;
                break;
            }
        }
        voice.position = pos;
        voice.direction = direction;
        voice.t += static_cast<std::int64_t>(n);
        if (t_release >= 0.0) {
            double t_end = static_cast<double>(voice.t - 1 - voice.start_offset);
            if (!(t_end < t_release + std::max(1.0, release))) {
                voice.dead = true;
            }
        }
    }

    int flt = p.flt_type;
    if (flt > 0 && flt <= 6) {
        static const FilterType kTypes[7] = {FilterType::LowPass,  FilterType::LowPass,
                                             FilterType::HighPass, FilterType::BandPass,
                                             FilterType::LowPass,  FilterType::HighPass,
                                             FilterType::BandPass};
        bool invert = flt >= 4;
        FilterType type = kTypes[flt];
        for (std::size_t i = 0; i < n; ++i) {
            cutoff_[i] = static_cast<float>(cutoff_hz(cutoff_[i]));
        }
        double q = res_to_q(p.flt_res);
        pcm_filter_[0].process_var(l, scratch_a_.data(), n, type, cutoff_.data(), q, sample_rate_);
        pcm_filter_[1].process_var(r, scratch_b_.data(), n, type, cutoff_.data(), q, sample_rate_);
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = invert ? l[i] - scratch_a_[i] : scratch_a_[i];
            r[i] = invert ? r[i] - scratch_b_[i] : scratch_b_[i];
        }
    }
}

}  // namespace refrag
