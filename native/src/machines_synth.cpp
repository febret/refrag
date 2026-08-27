// Oscillator based machines: SubSynth, BassLine, PadSynth, 8BitSynth, Organ,
// FMSynth and KSSynth.
#include <algorithm>
#include <cmath>

#include "machine.h"

namespace refrag {

namespace {

inline void mix_centered(float *l, float *r, std::size_t i, float sample, float gain, float pan) {
    l[i] += sample * gain * (1.0f - pan) * 0.5f;
    r[i] += sample * gain * (1.0f + pan) * 0.5f;
}

// Mirrors dsp.adsr()'s "alive" flag: the voice ends once the release ramp has
// fully elapsed at the end of the rendered block.
inline bool voice_expired(const Voice &v, double release_frames) {
    if (v.released_at < 0) {
        return false;
    }
    double t_end = static_cast<double>(v.t - 1 - v.start_offset);
    double t_release = static_cast<double>(v.released_at - v.start_offset);
    return t_end >= t_release + std::max(1.0, release_frames);
}

// Shared 7-entry filter selector used by SubSynth (same table as PCMSynth).
inline bool filter_spec(int index, FilterType *type, bool *invert) {
    static const FilterType kTypes[7] = {FilterType::LowPass,  FilterType::LowPass,
                                         FilterType::HighPass, FilterType::BandPass,
                                         FilterType::LowPass,  FilterType::HighPass,
                                         FilterType::BandPass};
    if (index <= 0 || index > 6) {
        return false;
    }
    *type = kTypes[index];
    *invert = index >= 4;
    return true;
}

}  // namespace

// ---------------------------------------------------------------------------
// SubSynth: dual oscillator with cross modulation, resonant filter and 2 LFOs.
// ---------------------------------------------------------------------------

void MachineEngine::render_subsynth(float *l, float *r, std::size_t n) {
    const SubSynthParams &p = spec_.sub;
    fill_lfo(lfo1_, n, p.lfo1_wave, p.lfo1_rate, lfo1_phase_, 0.0);
    fill_lfo(lfo2_, n, 0, p.lfo2_rate, lfo2_phase_, 0.0);

    const double v_a = env_frames(p.vol_attack, sample_rate_);
    const double v_d = env_frames(p.vol_decay, sample_rate_);
    const double v_s = clampd(p.vol_sustain, 0.0, 1.0);
    const double v_r = env_frames(p.vol_release, sample_rate_);
    const double f_a = env_frames(p.flt_attack, sample_rate_);
    const double f_d = env_frames(p.flt_decay, sample_rate_);
    const double f_s = clampd(p.flt_sustain, 0.0, 1.0);
    const double f_r = env_frames(p.flt_release, sample_rate_);

    const int w1 = p.osc1_wave;
    const int w2 = p.osc2_wave - 1;  // -1 == Silence
    const double semi2 = p.osc2_octave * 12.0 + p.osc2_semis;
    const double cents2 = p.osc2_cents / 100.0;
    const bool unison = p.detune_mode == 1;
    const double q = res_to_q(p.flt_res);
    FilterType ftype = FilterType::LowPass;
    bool finvert = false;
    const bool use_filter = filter_spec(p.flt_type, &ftype, &finvert);
    const double bend_tc = std::max(1.0, sample_rate_ * 0.08);
    const std::size_t kCoeffHop = 32;

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, v_a, v_d, v_s, v_r, t_release);

            double lfo_semi1 = 0.0;
            double lfo_semi2 = 0.0;
            double cut_mod = 0.0;
            double vol_mod = 1.0;
            const float mods[2] = {lfo1_[i] * p.lfo1_depth, lfo2_[i] * p.lfo2_depth};
            const int targets[2] = {p.lfo1_target, p.lfo2_target};
            for (int k = 0; k < 2; ++k) {
                switch (targets[k]) {
                case 1:
                    lfo_semi1 += mods[k] * 2.0;
                    break;
                case 2:
                    lfo_semi2 += mods[k] * 2.0;
                    break;
                case 3:
                    lfo_semi1 += mods[k] * 2.0;
                    lfo_semi2 += mods[k] * 2.0;
                    break;
                case 4:
                    cut_mod += mods[k] * 0.45;
                    break;
                case 5:
                    vol_mod *= clampd(1.0 + mods[k] * 0.5, 0.0, 2.0);
                    break;
                case 6: {
                    double oct = 12.0 * std::round(mods[k]);
                    lfo_semi1 += oct;
                    lfo_semi2 += oct;
                    break;
                }
                default:
                    break;
                }
            }

            double bend_semi = p.bend * 12.0 * std::exp(-local / bend_tc);
            double f1 = note_freq(voice.note + lfo_semi1 + bend_semi);
            double base2 = voice.note + semi2 + lfo_semi2 + bend_semi;

            float o2 = 0.0f;
            if (w2 >= 0) {
                if (unison) {
                    double fa = note_freq(base2 - cents2);
                    double fb = note_freq(base2 + cents2);
                    voice.phase[1] += fa / sample_rate_;
                    voice.phase[2] += fb / sample_rate_;
                    o2 = 0.5f * (osc_wave(w2, voice.phase[1] + p.osc2_phase, fa / sample_rate_,
                                          &noise_rng_) +
                                 osc_wave(w2, voice.phase[2] + p.osc2_phase, fb / sample_rate_,
                                          &noise_rng_));
                } else {
                    double f2 = note_freq(base2 + cents2);
                    voice.phase[1] += f2 / sample_rate_;
                    o2 = osc_wave(w2, voice.phase[1] + p.osc2_phase, f2 / sample_rate_,
                                  &noise_rng_);
                }
            }

            double inc1 = f1 / sample_rate_;
            if (p.mod_mode == 0 && p.osc_mod > 0.0f) {  // FM
                inc1 *= 1.0 + p.osc_mod * 4.0 * o2;
            }
            voice.phase[0] += inc1;
            double read_phase = voice.phase[0];
            if (p.mod_mode == 1) {  // PM
                read_phase += p.osc_mod * o2;
            }
            float o1 = osc_wave(w1, read_phase, std::fabs(inc1), &noise_rng_);
            if (p.mod_mode == 2) {  // AM
                o1 *= static_cast<float>(1.0 - p.osc_mod + p.osc_mod * (o2 * 0.5 + 0.5));
            }

            float s = o1 * (1.0f - p.osc_mix) + o2 * p.osc_mix;

            if (use_filter) {
                if (t == voice.start_offset || i % kCoeffHop == 0) {
                    double fenv = adsr(local, f_a, f_d, f_s, f_r, t_release);
                    double norm = clampd(p.flt_cutoff * fenv +
                                             p.flt_track * (voice.note - 60.0) / 48.0 + cut_mod,
                                         0.0, 1.0);
                    voice.filter.set(ftype, cutoff_hz(norm), q, sample_rate_);
                }
                float filtered = voice.filter.process_one(s);
                s = finvert ? s - filtered : filtered;
            }

            float gain = static_cast<float>(env * vol_mod) * voice.vel * p.volume;
            mix_centered(l, r, i, s, gain, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, v_r)) {
            voice.dead = true;
        }
    }
}

// ---------------------------------------------------------------------------
// BassLine: monophonic 303 style voice with slide, accent and distortion.
// ---------------------------------------------------------------------------

void MachineEngine::render_bassline(float *l, float *r, std::size_t n) {
    const BassLineParams &p = spec_.bass;
    fill_lfo(lfo1_, n, 0, p.lfo_rate, lfo1_phase_, p.lfo_phase);

    const double decay_frames = std::max(1.0, env_time(p.decay, 2.0, 0.03) * sample_rate_);
    const double attack_frames = std::max(1.0, sample_rate_ * 0.003);
    const double release_frames = std::max(1.0, sample_rate_ * 0.008);
    const double glide_frames = std::max(1.0, sample_rate_ * 0.06);
    const double q = res_to_q(p.res);
    const std::size_t kCoeffHop = 16;

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        bool accent = (voice.flags & 1) != 0;
        double accent_amt = accent ? clampd(p.accent, 0.0, 1.0) : 0.0;
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, attack_frames, 1.0, 1.0, release_frames, t_release);
            double glide = std::min(1.0, local / glide_frames);
            double pitch = voice.note_from + (voice.note - voice.note_from) * glide + p.tune;

            double lfo = lfo1_[i] * p.lfo_depth;
            double pw = clampd(p.pulse_width + (p.lfo_target == 0 ? lfo * 0.45 : 0.0), 0.01, 0.99);
            double f = note_freq(pitch);
            double inc = f / sample_rate_;
            voice.phase[0] += inc;
            double ph = voice.phase[0] - std::floor(voice.phase[0]);
            float s;
            if (p.wave == 0) {
                s = static_cast<float>(2.0 * ph - 1.0 + polyblep(ph, inc));
            } else {
                s = ph < pw ? 1.0f : -1.0f;
            }

            if (t == voice.start_offset || i % kCoeffHop == 0) {
                double fenv = std::exp(-local / decay_frames);
                double norm = clampd(p.cutoff +
                                         p.env_mod * fenv * (1.0 + accent_amt * 0.8) +
                                         (p.lfo_target == 1 ? lfo * 0.45 : 0.0),
                                     0.0, 1.0);
                voice.filter.set(FilterType::LowPass, cutoff_hz(norm),
                                 q * (1.0 + accent_amt * 0.4), sample_rate_);
            }
            s = voice.filter.process_one(s);

            double vol = env * (1.0 + accent_amt * 0.6);
            if (p.lfo_target == 2) {
                vol *= clampd(1.0 + lfo * 0.5, 0.0, 2.0);
            }
            mix_centered(l, r, i, s, static_cast<float>(vol) * voice.vel, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, release_frames)) {
            voice.dead = true;
        }
    }

    if (p.dist_program > 0) {
        // catalog order: Off, Overdrive, Saturate, Foldback, Fuzz
        static const int kProgramMap[5] = {-1, 0, 1, 3, 2};
        int program = kProgramMap[std::min(4, p.dist_program)];
        float pre = 0.05f + p.dist_pre;
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = distort_sample(l[i] * pre, program, p.dist_amount) * p.dist_post;
            r[i] = distort_sample(r[i] * pre, program, p.dist_amount) * p.dist_post;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        l[i] *= p.volume;
        r[i] *= p.volume;
    }
}

// ---------------------------------------------------------------------------
// PadSynth: additive engine morphing between two harmonic tables.
// ---------------------------------------------------------------------------

void MachineEngine::render_padsynth(float *l, float *r, std::size_t n) {
    const PadSynthParams &p = spec_.pad;
    fill_lfo(lfo1_, n, 0, p.lfo1_rate, lfo1_phase_, p.lfo1_phase);
    fill_lfo(lfo2_, n, 0, p.lfo2_rate, lfo2_phase_, p.lfo2_phase);

    const double v_a = env_frames(p.vol_attack, sample_rate_);
    const double v_d = env_frames(p.vol_decay, sample_rate_);
    const double v_s = clampd(p.vol_sustain, 0.0, 1.0);
    const double v_r = env_frames(p.vol_release, sample_rate_);
    const double m_a = env_frames(p.morph_attack, sample_rate_);
    const double m_d = env_frames(p.morph_decay, sample_rate_);
    const double m_s = clampd(p.morph_sustain, 0.0, 1.0);
    const double m_r = env_frames(p.morph_release, sample_rate_);
    const double nyquist = sample_rate_ * 0.48;

    // Modulation is evaluated at the block mid-point for the partial table and
    // per sample for pitch/volume.
    std::size_t mid = n / 2;
    double morph_lfo = 0.0;
    for (int k = 0; k < 2; ++k) {
        int target = k == 0 ? p.lfo1_target : p.lfo2_target;
        float value = k == 0 ? lfo1_[mid] * p.lfo1_depth : lfo2_[mid] * p.lfo2_depth;
        if (target == 2) {
            morph_lfo += value * 0.5;
        }
    }

    struct Partial {
        int index;
        float amp;
        double detune;
    };
    Partial partials[kPadHarmonics];

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        double local_mid = static_cast<double>(voice.t + static_cast<std::int64_t>(mid) -
                                               voice.start_offset);
        double morph = p.morph;
        if (p.morph_env) {
            morph *= adsr(std::max(0.0, local_mid), m_a, m_d, m_s, m_r, t_release);
        }
        morph = clampd(morph + morph_lfo, 0.0, 1.0);
        double width = spec_.width1 * (1.0 - morph) + spec_.width2 * morph;

        int count = 0;
        double total = 0.0;
        for (int k = 0; k < kPadHarmonics; ++k) {
            double a1 = k < static_cast<int>(spec_.harm1.size()) ? spec_.harm1[k] : 0.0;
            double a2 = k < static_cast<int>(spec_.harm2.size()) ? spec_.harm2[k] : 0.0;
            double amp = a1 * (1.0 - morph) * p.gain1 + a2 * morph * p.gain2;
            if (amp <= 1e-4) {
                continue;
            }
            partials[count].index = k;
            partials[count].amp = static_cast<float>(amp);
            partials[count].detune = width * 0.004 * (k + 1);
            total += amp;
            ++count;
        }
        float norm = static_cast<float>(1.0 / std::max(1.0, total));

        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, v_a, v_d, v_s, v_r, t_release);
            double pitch_semi = 0.0;
            double vol_mod = 1.0;
            const float mods[2] = {lfo1_[i] * p.lfo1_depth, lfo2_[i] * p.lfo2_depth};
            const int targets[2] = {p.lfo1_target, p.lfo2_target};
            for (int k = 0; k < 2; ++k) {
                if (targets[k] == 1) {
                    pitch_semi += mods[k] * 2.0;
                } else if (targets[k] == 3) {
                    vol_mod *= clampd(1.0 + mods[k] * 0.5, 0.0, 2.0);
                }
            }
            double f0 = note_freq(voice.note + pitch_semi);
            float s = 0.0f;
            for (int k = 0; k < count; ++k) {
                const Partial &partial = partials[k];
                double fk = f0 * (partial.index + 1);
                if (fk >= nyquist) {
                    break;
                }
                double det = partial.detune;
                voice.pad_ph_a[partial.index] += fk * (1.0 - det) / sample_rate_;
                voice.pad_ph_b[partial.index] += fk * (1.0 + det) / sample_rate_;
                double pa = voice.pad_ph_a[partial.index];
                double pb = voice.pad_ph_b[partial.index];
                s += partial.amp * 0.5f *
                     static_cast<float>(std::sin(kTwoPi * pa) + std::sin(kTwoPi * pb));
            }
            float gain = static_cast<float>(env * vol_mod) * voice.vel * p.volume * norm;
            mix_centered(l, r, i, s, gain, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, v_r)) {
            voice.dead = true;
        }
    }
}

// ---------------------------------------------------------------------------
// 8BitSynth: dual bytebeat generator.
// ---------------------------------------------------------------------------

void MachineEngine::render_bitsynth(float *l, float *r, std::size_t n) {
    const BitSynthParams &p = spec_.bit;
    const double base_freq = note_freq(60.0);
    const double bytebeat_rate = 8000.0 / sample_rate_;
    const double attack_frames = std::max(1.0, sample_rate_ * 0.002);
    const double release_frames = std::max(1.0, sample_rate_ * 0.01);
    const float blend = clampf(p.blend, 0.0f, 1.0f);
    const bool need_a = blend < 1.0f && expr_a_.valid();
    const bool need_b = blend > 0.0f && expr_b_.valid();

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double pitch = voice.note + p.octave * 12.0 + p.semis + p.cents / 100.0;
        double step = note_freq(pitch) / base_freq * bytebeat_rate;
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, attack_frames, 1.0, 1.0, release_frames, t_release);
            std::int64_t ti = static_cast<std::int64_t>(voice.aux);
            float sample = 0.0f;
            if (need_a) {
                float a = static_cast<float>((expr_a_.eval(ti) & 255) / 127.5 - 1.0);
                sample += a * (1.0f - blend);
            }
            if (need_b) {
                float b = static_cast<float>((expr_b_.eval(ti) & 255) / 127.5 - 1.0);
                sample += b * blend;
            }
            voice.aux += step;
            mix_centered(l, r, i, sample, static_cast<float>(env) * voice.vel * p.volume, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, release_frames)) {
            voice.dead = true;
        }
    }

    // DC blocker: bytebeat output carries a heavy offset.
    for (std::size_t i = 0; i < n; ++i) {
        float xl = l[i];
        float xr = r[i];
        float yl = xl - dc_x_[0] + 0.995f * dc_y_[0];
        float yr = xr - dc_x_[1] + 0.995f * dc_y_[1];
        dc_x_[0] = xl;
        dc_x_[1] = xr;
        dc_y_[0] = yl;
        dc_y_[1] = yr;
        l[i] = yl;
        r[i] = yr;
    }
}

// ---------------------------------------------------------------------------
// Organ: nine drawbars, percussion and a Leslie rotor.
// ---------------------------------------------------------------------------

void MachineEngine::render_organ(float *l, float *r, std::size_t n) {
    const OrganParams &p = spec_.organ;
    static const double kRatios[9] = {0.5, 1.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0};

    double total = 0.0;
    for (int k = 0; k < 9; ++k) {
        total += p.bars[k];
    }
    const float norm = static_cast<float>(1.0 / std::max(1.0, total * 0.55));
    const double attack_frames = std::max(1.0, sample_rate_ * 0.004);
    const double release_frames = std::max(1.0, sample_rate_ * 0.012);
    const double perc_frames =
        std::max(1.0, (0.08 + clampd(p.perc_decay, 0.0, 1.0) * 1.2) * sample_rate_);
    const bool perc_on = p.perc_decay > 0.0f;
    const double leslie_rate = 0.6 + clampd(p.leslie_speed, 0.0, 1.0) * 6.4;
    const double leslie_step = leslie_rate / sample_rate_;
    const double depth = clampd(p.leslie_depth, 0.0, 1.0);
    const double nyquist = sample_rate_ * 0.48;

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        double f0 = note_freq(voice.note);
        double lph = leslie_phase_;
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                lph += leslie_step;
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double env = adsr(local, attack_frames, 1.0, 1.0, release_frames, t_release);
            double vib = 1.0 + depth * 0.0025 * std::sin(kTwoPi * lph);
            float s = 0.0f;
            for (int k = 0; k < 9; ++k) {
                float level = p.bars[k];
                if (level <= 1e-4f) {
                    continue;
                }
                double fk = f0 * kRatios[k] * vib;
                if (fk >= nyquist) {
                    continue;
                }
                voice.phase[k] += fk / sample_rate_;
                s += level * static_cast<float>(std::sin(kTwoPi * voice.phase[k]));
            }
            if (perc_on) {
                double perc_ratio = 2.0 + clampd(p.perc_tone, 0.0, 1.0);
                double fp = f0 * perc_ratio * vib;
                if (fp < nyquist) {
                    voice.phase[9] += fp / sample_rate_;
                    double perc_env = std::exp(-local / perc_frames);
                    s += static_cast<float>(0.8 * perc_env * std::sin(kTwoPi * voice.phase[9]));
                }
            }
            s *= norm;
            if (p.drive > 0.0f) {
                double d = 1.0 + p.drive * 6.0;
                s = static_cast<float>(std::tanh(s * d) / std::tanh(d));
            }
            double trem = 1.0 + depth * 0.35 * std::sin(kTwoPi * lph);
            double rot = depth * 0.8 * std::sin(kTwoPi * lph + kTwoPi * 0.25);
            float gain = static_cast<float>(env * trem) * voice.vel * p.volume;
            mix_centered(l, r, i, s, gain, static_cast<float>(rot));
            lph += leslie_step;
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, release_frames)) {
            voice.dead = true;
        }
    }
    leslie_phase_ += static_cast<double>(n) * leslie_step;
    if (leslie_phase_ > 1e9) {
        leslie_phase_ = std::fmod(leslie_phase_, 1.0);
    }
}

// ---------------------------------------------------------------------------
// FMSynth: three operators with five routing algorithms.
// ---------------------------------------------------------------------------

void MachineEngine::render_fmsynth(float *l, float *r, std::size_t n) {
    const FMSynthParams &p = spec_.fm;
    fill_lfo(lfo1_, n, 0, p.lfo_rate, lfo1_phase_, 0.0);

    struct OpState {
        double a, d, s, rel;
        double freq_offset;
        bool fixed;
        float level;
        bool level_vel;
    };
    OpState ops[3];
    double max_release = 1.0;
    for (int k = 0; k < 3; ++k) {
        const FMOperator &op = p.ops[k];
        ops[k].a = env_frames(op.attack, sample_rate_);
        ops[k].d = env_frames(op.decay, sample_rate_);
        ops[k].s = clampd(op.sustain, 0.0, 1.0);
        ops[k].rel = env_frames(op.release, sample_rate_);
        ops[k].freq_offset = op.octave * 12.0 + op.semis;
        ops[k].fixed = op.fixed != 0;
        ops[k].level = op.level;
        ops[k].level_vel = op.level_vel != 0;
        max_release = std::max(max_release, ops[k].rel);
    }
    const int algorithm = std::max(0, std::min(4, p.algorithm));
    const bool amp_lfo[3] = {p.lfo_a1 != 0, p.lfo_a2 != 0, p.lfo_a3 != 0};
    const bool freq_lfo[3] = {p.lfo_f1 != 0, p.lfo_f2 != 0, p.lfo_f3 != 0};

    for (auto &voice : voices_) {
        if (voice.dead) {
            continue;
        }
        double t_release =
            voice.released_at < 0
                ? -1.0
                : static_cast<double>(voice.released_at) - static_cast<double>(voice.start_offset);
        float vel_gain = p.volume_vel ? voice.vel : 1.0f;
        float feedback = p.feedback * (p.feedback_vel ? voice.vel : 1.0f);
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            double local = static_cast<double>(t - voice.start_offset);
            double lfo = lfo1_[i] * p.lfo_depth;

            float out[3] = {0.0f, 0.0f, 0.0f};
            float env[3];
            for (int k = 0; k < 3; ++k) {
                env[k] = static_cast<float>(
                    adsr(local, ops[k].a, ops[k].d, ops[k].s, ops[k].rel, t_release));
                double base = ops[k].fixed ? 60.0 + ops[k].freq_offset
                                           : voice.note + ops[k].freq_offset;
                if (freq_lfo[k]) {
                    base += lfo * 2.0;
                }
                double f = note_freq(base);
                voice.phase[k] += f / sample_rate_;
            }

            auto op_out = [&](int k, double phase_mod) {
                float amp = ops[k].level * env[k];
                if (ops[k].level_vel) {
                    amp *= voice.vel;
                }
                if (amp_lfo[k]) {
                    amp *= static_cast<float>(clampd(1.0 + lfo * 0.5, 0.0, 2.0));
                }
                return amp * static_cast<float>(std::sin(kTwoPi * (voice.phase[k] + phase_mod)));
            };

            out[0] = op_out(0, feedback * voice.fm_fb[0]);
            voice.fm_fb[0] = out[0];

            float sample = 0.0f;
            switch (algorithm) {
            case 0:  // 1>2>3
                out[1] = op_out(1, out[0] * 2.0);
                out[2] = op_out(2, out[1] * 2.0);
                sample = out[2];
                break;
            case 1:  // 1>3 2>3
                out[1] = op_out(1, 0.0);
                out[2] = op_out(2, (out[0] + out[1]) * 2.0);
                sample = out[2];
                break;
            case 2:  // 1>2 1>3
                out[1] = op_out(1, out[0] * 2.0);
                out[2] = op_out(2, out[0] * 2.0);
                sample = (out[1] + out[2]) * 0.5f;
                break;
            case 3:  // 1>2+3
                out[1] = op_out(1, out[0] * 2.0);
                out[2] = op_out(2, 0.0);
                sample = (out[1] + out[2]) * 0.5f;
                break;
            default:  // 1+2+3
                out[1] = op_out(1, 0.0);
                out[2] = op_out(2, 0.0);
                sample = (out[0] + out[1] + out[2]) / 3.0f;
                break;
            }
            if (p.lfo_ao) {
                sample *= static_cast<float>(clampd(1.0 + lfo * 0.5, 0.0, 2.0));
            }
            mix_centered(l, r, i, sample, vel_gain * p.volume, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        if (voice_expired(voice, max_release)) {
            voice.dead = true;
        }
    }
}

// ---------------------------------------------------------------------------
// KSSynth: two Karplus-Strong strings.
// ---------------------------------------------------------------------------

void MachineEngine::note_on_kssynth(Voice &v) {
    const KSSynthParams &p = spec_.ks;
    double vel = clampd(v.vel, 0.0, 1.0);
    double track = (v.note - 60.0) / 48.0;
    double pre = clampd(p.pre_filter + p.pre_track * track + p.pre_vel * vel, 0.0, 0.999);
    for (int u = 0; u < 2; ++u) {
        const KSUnit &unit = p.units[u];
        double pitch = (unit.follow ? static_cast<double>(v.note) : 60.0) + unit.octave * 12.0 +
                       unit.semis + unit.cents / 100.0;
        double f = std::max(20.0, note_freq(pitch));
        std::size_t len = std::max<std::size_t>(2, static_cast<std::size_t>(sample_rate_ / f));
        v.ks_buf[u].assign(len, 0.0f);
        float lp = 0.0f;
        double sum = 0.0;
        for (std::size_t i = 0; i < len; ++i) {
            lp = static_cast<float>((1.0 - pre) * rng_.next_bipolar() + pre * lp);
            v.ks_buf[u][i] = lp * static_cast<float>(vel);
            sum += v.ks_buf[u][i];
        }
        // The delay loop has unity gain at DC, so the excitation must be
        // zero-mean or the string rings with a constant offset.
        float mean = static_cast<float>(sum / static_cast<double>(len));
        for (std::size_t i = 0; i < len; ++i) {
            v.ks_buf[u][i] -= mean;
        }
        v.ks_idx[u] = 0;
        v.ks_lp[u] = 0.0f;
        v.ks_damp[u] = static_cast<float>(
            clampd(unit.damping + unit.damp_track * track + unit.damp_vel * vel, 0.0, 0.95));
        double decay_seconds = 0.05 + std::pow(clampd(p.decay, 0.0, 1.0), 2.0) * 6.0;
        v.ks_feedback[u] = static_cast<float>(
            clampd(std::exp(-static_cast<double>(len) / (decay_seconds * sample_rate_)), 0.0,
                   0.9999));
    }
    v.ks_energy = 1.0f;
}

void MachineEngine::render_kssynth(float *l, float *r, std::size_t n) {
    const KSSynthParams &p = spec_.ks;
    const double release_frames = std::max(1.0, sample_rate_ * (0.02 + p.decay * 0.35));
    const float mix = clampf(p.mix, 0.0f, 1.0f);
    const float unit_gain[2] = {1.0f - mix, mix * (p.invert_mix ? -1.0f : 1.0f)};

    for (auto &voice : voices_) {
        if (voice.dead || voice.ks_buf[0].empty()) {
            continue;
        }
        float peak = 0.0f;
        for (std::size_t i = 0; i < n; ++i) {
            std::int64_t t = voice.t + static_cast<std::int64_t>(i);
            if (t < voice.start_offset) {
                continue;
            }
            float s = 0.0f;
            for (int u = 0; u < 2; ++u) {
                std::vector<float> &buf = voice.ks_buf[u];
                if (buf.empty() || unit_gain[u] == 0.0f) {
                    continue;
                }
                std::size_t idx = voice.ks_idx[u];
                float raw = buf[idx];
                float damp = voice.ks_damp[u];
                voice.ks_lp[u] = (1.0f - damp) * raw + damp * voice.ks_lp[u];
                float y = voice.ks_feedback[u] * voice.ks_lp[u];
                buf[idx] = p.units[u].invert ? -y : y;
                voice.ks_idx[u] = (idx + 1) % buf.size();
                s += unit_gain[u] * y;
            }
            double gain = 1.0;
            if (voice.released_at >= 0 && t >= voice.released_at) {
                gain = std::exp(-static_cast<double>(t - voice.released_at) / release_frames);
            }
            float value = s * static_cast<float>(gain);
            peak = std::max(peak, std::fabs(value));
            mix_centered(l, r, i, value, p.volume, 0.0f);
        }
        voice.t += static_cast<std::int64_t>(n);
        voice.ks_energy = peak;
        if (voice.t > voice.start_offset && peak < 1e-5f) {
            voice.dead = true;
        }
        if (voice.released_at >= 0 &&
            static_cast<double>(voice.t - voice.released_at) > release_frames * 12.0) {
            voice.dead = true;
        }
    }
}

}  // namespace refrag
