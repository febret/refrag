#include "mixer.h"

#include <algorithm>
#include <cmath>

namespace refrag {

namespace {

inline void ensure_size(std::vector<float> &v, std::size_t n) {
    if (v.size() < n) {
        v.assign(n, 0.0f);
    }
}

}  // namespace

// ---------------------------------------------------------------------------
// Channel strip
// ---------------------------------------------------------------------------

void ChannelStrip::process(float *l, float *r, std::size_t n, const MixerSpec &mx) {
    struct Band {
        FilterType type;
        double f0;
        float gain;
    };
    const Band bands[3] = {
        {FilterType::LowShelf, 250.0, mx.eq_bass},
        {FilterType::Peak, 1200.0, mx.eq_mid},
        {FilterType::HighShelf, 5000.0, mx.eq_high},
    };
    float *chans[2] = {l, r};
    for (int bi = 0; bi < 3; ++bi) {
        if (std::fabs(bands[bi].gain) < 0.01f) {
            continue;
        }
        for (int c = 0; c < 2; ++c) {
            Biquad &bq = eq_[bi * 2 + c];
            bq.set(bands[bi].type, bands[bi].f0, 0.7, sample_rate_, bands[bi].gain * 12.0);
            bq.process_inplace(chans[c], n);
        }
    }

    float w = mx.width;
    if (std::fabs(w) > 0.02f) {
        std::size_t d = static_cast<std::size_t>(std::fabs(w) * 0.008 * sample_rate_);
        if (d > 0) {
            int ch = w < 0.0f ? 0 : 1;
            width_[ch].process(chans[ch], n, d);
        }
    }

    float pan = mx.pan;
    if (std::fabs(pan) > 0.01f) {
        float gl = static_cast<float>(std::sqrt(0.5 * (1.0 - pan)) * 1.414);
        float gr = static_cast<float>(std::sqrt(0.5 * (1.0 + pan)) * 1.414);
        for (std::size_t i = 0; i < n; ++i) {
            l[i] *= gl;
            r[i] *= gr;
        }
    }
}

// ---------------------------------------------------------------------------
// Master delay
// ---------------------------------------------------------------------------

void MasterDelay::configure(double sample_rate) {
    sample_rate_ = sample_rate;
    std::size_t cap = std::max<std::size_t>(64, static_cast<std::size_t>(sample_rate * 4.0));
    buf_[0].assign(cap, 0.0f);
    buf_[1].assign(cap, 0.0f);
    w_ = 0;
    lp_[0].reset(0.0f);
    lp_[1].reset(0.0f);
}

void MasterDelay::process(const float *in_l, const float *in_r, float *out_l, float *out_r,
                          std::size_t n, const MasterSpec &mp, double bpm) {
    std::size_t cap = buf_[0].size();
    if (cap == 0 || n == 0) {
        std::fill(out_l, out_l + n, 0.0f);
        std::fill(out_r, out_r + n, 0.0f);
        return;
    }
    int steps = mp.dly_steps + 1;
    steps = std::max(1, std::min(steps, 8));
    double d;
    if (mp.dly_sync) {
        static const double kOpts[6] = {0.25, 0.5, 0.75, 1.0, 1.5, 2.0};
        int idx = static_cast<int>(std::lround(mp.dly_time * 5.0));
        idx = std::max(0, std::min(5, idx));
        d = kOpts[idx] * 60.0 / (bpm > 0.0 ? bpm : 120.0) * sample_rate_;
    } else {
        d = (0.02 + mp.dly_time * 1.2) * sample_rate_;
    }
    std::size_t D = static_cast<std::size_t>(
        clampd(d, 64.0, static_cast<double>(cap / static_cast<std::size_t>(steps + 1))));
    if (D == 0) {
        D = 1;
    }
    float fb = mp.dly_feedback;
    float damp = mp.dly_damping;

    ensure_size(tap_l_, n);
    ensure_size(tap_r_, n);
    std::fill(out_l, out_l + n, 0.0f);
    std::fill(out_r, out_r + n, 0.0f);
    std::fill(tap_l_.begin(), tap_l_.begin() + n, 0.0f);
    std::fill(tap_r_.begin(), tap_r_.begin() + n, 0.0f);

    const float pans[2] = {mp.dly_pan1, mp.dly_pan2};
    for (int tap = 0; tap < steps; ++tap) {
        std::size_t back = (D * static_cast<std::size_t>(tap + 1)) % cap;
        float g = static_cast<float>(std::pow(static_cast<double>(fb), tap));
        float pan = pans[tap % 2];
        float gl = static_cast<float>(std::sqrt(0.5 * (1.0 - pan)) * 1.414);
        float gr = static_cast<float>(std::sqrt(0.5 * (1.0 + pan)) * 1.414);
        bool last = tap == steps - 1;
        for (std::size_t i = 0; i < n; ++i) {
            std::size_t idx = (w_ + i) % cap;
            std::size_t rd = (idx + cap - back) % cap;
            float tl = buf_[0][rd];
            float tr = buf_[1][rd];
            out_l[i] += tl * g * gl;
            out_r[i] += tr * g * gr;
            if (last) {
                tap_l_[i] = tl * g;
                tap_r_[i] = tr * g;
            }
        }
    }
    if (damp > 0.0f) {
        float coef = damp * 0.9f;
        lp_[0].process(out_l, out_l, n, coef);
        lp_[1].process(out_r, out_r, n, coef);
    }
    for (std::size_t i = 0; i < n; ++i) {
        std::size_t idx = (w_ + i) % cap;
        float wl = in_l[i];
        float wr = in_r[i];
        if (mp.dly_first_tap) {
            wl *= fb;
            wr *= fb;
        }
        if (mp.dly_loop) {
            wl += tap_l_[i] * fb;
            wr += tap_r_[i] * fb;
        }
        buf_[0][idx] = wl;
        buf_[1][idx] = wr;
    }
    w_ = (w_ + n) % cap;
}

// ---------------------------------------------------------------------------
// Master section
// ---------------------------------------------------------------------------

void MasterSection::configure(double sample_rate, std::size_t block_size) {
    sample_rate_ = sample_rate;
    block_size_ = block_size;
    delay_.configure(sample_rate);
    reverb_ = create_effect(EffectKind::Reverb, sample_rate, 0x51F3A1);
    limiter_ = create_effect(EffectKind::Limiter, sample_rate, 0x51F3A2);
    for (int i = 0; i < 2; ++i) {
        fx_[i].reset();
        fx_present_[i] = false;
    }
    for (auto &bq : eq_) {
        bq.reset();
    }
    lim_gr_ = 0.0f;
}

void MasterSection::sync_effects(const MasterSpec &spec, std::uint64_t seed_base) {
    for (int i = 0; i < 2; ++i) {
        const EffectSpec &st = spec.effects[i];
        if (!st.present) {
            fx_[i].reset();
            fx_present_[i] = false;
            continue;
        }
        if (!fx_present_[i] || fx_kind_[i] != st.kind || !fx_[i]) {
            fx_[i] = create_effect(st.kind, sample_rate_, seed_base + 97u * (i + 1));
            fx_kind_[i] = st.kind;
            fx_present_[i] = true;
        }
    }
}

void MasterSection::eq(float *l, float *r, std::size_t n, const MasterSpec &mp) {
    double bass_f = 60.0 + mp.eq_bass_freq * 440.0;
    double mid_f = 500.0 + mp.eq_mid_freq * 4500.0;
    struct Band {
        FilterType type;
        double f0;
        float gain;
    };
    const Band bands[3] = {
        {FilterType::LowShelf, bass_f, mp.eq_bass},
        {FilterType::Peak, std::sqrt(bass_f * mid_f), mp.eq_mid},
        {FilterType::HighShelf, mid_f, mp.eq_high},
    };
    float *chans[2] = {l, r};
    for (int bi = 0; bi < 3; ++bi) {
        if (std::fabs(bands[bi].gain) < 0.01f) {
            continue;
        }
        for (int c = 0; c < 2; ++c) {
            Biquad &bq = eq_[bi * 2 + c];
            bq.set(bands[bi].type, bands[bi].f0, 0.7, sample_rate_, bands[bi].gain * 12.0);
            bq.process_inplace(chans[c], n);
        }
    }
}

void MasterSection::process(float *mix_l, float *mix_r, float *send_delay_l, float *send_delay_r,
                            float *send_reverb_l, float *send_reverb_r, std::size_t n,
                            const MasterSpec &mp, double bpm) {
    if (n == 0) {
        return;
    }
    ensure_size(wet_l_, n);
    ensure_size(wet_r_, n);
    ensure_size(dry_l_, n);
    ensure_size(dry_r_, n);

    if (mp.dly_bypass) {
        delay_.process(send_delay_l, send_delay_r, wet_l_.data(), wet_r_.data(), n, mp, bpm);
        for (std::size_t i = 0; i < n; ++i) {
            mix_l[i] += wet_l_[i] * mp.dly_wet;
            mix_r[i] += wet_r_[i] * mp.dly_wet;
        }
    }

    if (mp.rev_bypass) {
        std::copy(send_reverb_l, send_reverb_l + n, dry_l_.begin());
        std::copy(send_reverb_r, send_reverb_r + n, dry_r_.begin());
        std::copy(send_reverb_l, send_reverb_l + n, wet_l_.begin());
        std::copy(send_reverb_r, send_reverb_r + n, wet_r_.begin());
        EffectSpec rp;
        rp.present = true;
        rp.kind = EffectKind::Reverb;
        rp.p[0] = mp.rev_room;
        rp.p[1] = mp.rev_damping;
        rp.p[2] = mp.rev_predelay;
        rp.p[3] = mp.rev_stereo_spread;
        rp.p[4] = 1.0f;
        EffectContext ctx;
        ctx.bpm = bpm;
        reverb_->process(wet_l_.data(), wet_r_.data(), n, rp, ctx);
        for (std::size_t i = 0; i < n; ++i) {
            mix_l[i] += (wet_l_[i] - dry_l_[i] * 0.6f) * mp.rev_wet;
            mix_r[i] += (wet_r_[i] - dry_r_[i] * 0.6f) * mp.rev_wet;
        }
    }

    EffectContext ctx;
    ctx.bpm = bpm;
    for (int i = 0; i < 2; ++i) {
        const EffectSpec &st = mp.effects[i];
        if (st.present && !st.bypass && fx_present_[i] && fx_[i]) {
            fx_[i]->process(mix_l, mix_r, n, st, ctx);
        }
    }

    if (mp.eq_bypass) {
        eq(mix_l, mix_r, n, mp);
    }

    if (mp.lim_bypass) {
        EffectSpec lp;
        lp.present = true;
        lp.kind = EffectKind::Limiter;
        lp.p[0] = mp.lim_pre;
        lp.p[1] = mp.lim_attack;
        lp.p[2] = mp.lim_release;
        lp.p[3] = mp.lim_post;
        limiter_->process(mix_l, mix_r, n, lp, ctx);
        lim_gr_ = limiter_->gain_reduction();
    }

    for (std::size_t i = 0; i < n; ++i) {
        mix_l[i] *= mp.volume;
        mix_r[i] *= mp.volume;
    }
}

}  // namespace refrag
