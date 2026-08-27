#include "effects.h"

#include <algorithm>
#include <cmath>

namespace refrag {

namespace {

inline void ensure_size(std::vector<float> &v, std::size_t n) {
    if (v.size() < n) {
        v.assign(n, 0.0f);
    }
}

// effects._flanger_lfo
inline void flanger_lfo(int mode, double ph, float *out_l, float *out_r) {
    auto tri = [](double p) {
        double m = p - std::floor(p);
        return 4.0 * std::fabs(m - 0.5) - 1.0;
    };
    auto sine = [](double p) { return std::sin(kTwoPi * p); };
    bool use_sin = (mode == 0 || mode == 1 || mode == 2 || mode == 6);
    double l = use_sin ? sine(ph) : tri(ph);
    double r;
    if (mode == 0 || mode == 3) {
        r = l;
    } else if (mode == 1 || mode == 4) {
        r = use_sin ? sine(ph + 0.25) : tri(ph + 0.25);
    } else if (mode == 2 || mode == 5) {
        r = -l;
    } else {
        l = (l + 1.0) / 2.0;
        r = l;
    }
    *out_l = static_cast<float>(l);
    *out_r = static_cast<float>(r);
}

}  // namespace

// ---------------------------------------------------------------------------
// Distortion
// ---------------------------------------------------------------------------

class DistortionEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        int program = static_cast<int>(spec.p[0]);
        float pre = 0.05f + spec.p[1];
        float amount = spec.p[2];
        float post = spec.p[3];
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = distort_sample(l[i] * pre, program, amount) * post;
            r[i] = distort_sample(r[i] * pre, program, amount) * post;
        }
    }
};

// ---------------------------------------------------------------------------
// BitCrusher
// ---------------------------------------------------------------------------

class BitCrusherEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        int depth = std::max(1, static_cast<int>(std::lround(spec.p[0])));
        depth = std::min(depth, 24);
        double levels = std::pow(2.0, depth);
        double rate_hz = 20.0 * std::pow(2205.0, clampd(spec.p[1], 0.0, 1.0));
        double step = rate_hz / sample_rate_;
        double jit = spec.p[2];
        float wet = spec.p[3];
        float *chans[2] = {l, r};
        double ph = phase_;
        double prev_k = 0.0;
        float held[2] = {hold_[0], hold_[1]};
        for (std::size_t i = 0; i < n; ++i) {
            double s = step;
            if (jit > 0.0) {
                s = step * (1.0 + jit * rng().next_range(-0.9f, 0.9f));
            }
            ph += s;
            double k = std::floor(ph);
            if (i == 0 || k != prev_k) {
                held[0] = l[i];
                held[1] = r[i];
            }
            prev_k = k;
            for (int c = 0; c < 2; ++c) {
                float crushed = static_cast<float>(std::nearbyint(held[c] * levels) / levels);
                chans[c][i] = crushed * wet + chans[c][i] * (1.0f - wet);
                last_[c] = crushed;
            }
        }
        phase_ = std::fmod(ph, 1e9);
        hold_[0] = last_[0];
        hold_[1] = last_[1];
    }

  protected:
    void setup() override {
        phase_ = 0.0;
        hold_[0] = hold_[1] = 0.0f;
        last_[0] = last_[1] = 0.0f;
    }

  private:
    double phase_ = 0.0;
    float hold_[2] = {0.0f, 0.0f};
    float last_[2] = {0.0f, 0.0f};
};

// ---------------------------------------------------------------------------
// Compressor
// ---------------------------------------------------------------------------

class CompressorEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &ctx) override {
        int sc_idx = static_cast<int>(spec.p[4]);
        const float *key_l = l;
        const float *key_r = r;
        if (sc_idx > 0 && ctx.lines != nullptr && sc_idx - 1 < SidechainLines::kMax) {
            const float *cand_l = ctx.lines->l[sc_idx - 1];
            const float *cand_r = ctx.lines->r[sc_idx - 1];
            if (cand_l != nullptr && cand_r != nullptr) {
                key_l = cand_l;
                key_r = cand_r;
            }
        }
        ensure_size(level_, n);
        ensure_size(env_, n);
        for (std::size_t i = 0; i < n; ++i) {
            level_[i] = std::max(std::fabs(key_l[i]), std::fabs(key_r[i]));
        }
        float att = static_cast<float>(
            std::exp(-1.0 / (sample_rate_ * (0.0005 + spec.p[2] * spec.p[2] * 0.2))));
        float rel = static_cast<float>(
            std::exp(-1.0 / (sample_rate_ * (0.01 + spec.p[3] * spec.p[3] * 1.5))));
        slow_.process(level_.data(), env_.data(), n, rel);
        // Matches the Python reference: the fast follower starts from the state
        // the slow follower just left behind.
        OnePole fast;
        fast.set_state(slow_.state());
        for (std::size_t i = 0; i < n; ++i) {
            env_[i] = std::max(env_[i], fast.process_one(level_[i], att));
        }
        double th = 0.03 + spec.p[0] * 0.97;
        double ratio = 1.0 + spec.p[1] * 19.0;
        double exponent = 1.0 / ratio - 1.0;
        double min_gain = 1.0;
        for (std::size_t i = 0; i < n; ++i) {
            double over = std::max(env_[i] / th, 1.0);
            double gain = std::pow(over, exponent);
            min_gain = std::min(min_gain, gain);
            l[i] = static_cast<float>(l[i] * gain);
            r[i] = static_cast<float>(r[i] * gain);
        }
        gr_ = static_cast<float>(1.0 - min_gain);
    }

    float gain_reduction() const override { return gr_; }

  protected:
    void setup() override {
        slow_.reset(0.0f);
        gr_ = 0.0f;
    }

  private:
    OnePole slow_;
    float gr_ = 0.0f;
    std::vector<float> level_;
    std::vector<float> env_;
};

// ---------------------------------------------------------------------------
// Flanger / Chorus / StaticFlanger (fractional delay family)
// ---------------------------------------------------------------------------

class ModDelayEffect : public Effect {
  public:
    ModDelayEffect(double max_seconds, bool chorus) : max_seconds_(max_seconds), chorus_(chorus) {}

    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        ensure_size(dl_, n);
        ensure_size(dr_, n);
        ensure_size(wl_, n);
        ensure_size(wr_, n);
        ensure_size(src_l_, n);
        ensure_size(src_r_, n);
        float depth_knob = spec.p[0];
        double rate = chorus_ ? (0.05 + spec.p[1] * spec.p[1] * 4.0)
                              : (0.05 + spec.p[1] * spec.p[1] * 6.0);
        double base = chorus_ ? (0.005 + spec.p[2] * 0.03) * sample_rate_ : 0.0015 * sample_rate_;
        double depth = chorus_ ? depth_knob * 0.008 * sample_rate_
                               : depth_knob * 0.004 * sample_rate_;
        float feedback = chorus_ ? 0.0f : spec.p[2];
        float wet = spec.p[3];
        int mode = static_cast<int>(spec.p[4]);
        double last = ph_;
        for (std::size_t i = 0; i < n; ++i) {
            last = ph_ + static_cast<double>(i) * rate / sample_rate_;
            float lo, ro;
            flanger_lfo(mode, last, &lo, &ro);
            dl_[i] = static_cast<float>(base + depth * (lo + 1.0) / 2.0);
            dr_[i] = static_cast<float>(base + depth * (ro + 1.0) / 2.0);
        }
        ph_ = n ? std::fmod(last, 1.0) : ph_;
        std::copy(l, l + n, src_l_.begin());
        std::copy(r, r + n, src_r_.begin());
        line_.write_read(src_l_.data(), src_r_.data(), wl_.data(), wr_.data(), n, dl_.data(),
                         dr_.data(), feedback);
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = l[i] * (1.0f - wet) + wl_[i] * wet;
            r[i] = r[i] * (1.0f - wet) + wr_[i] * wet;
        }
    }
  protected:
    void setup() override {
        line_.init(max_seconds_, sample_rate_);
        ph_ = 0.0;
    }

  private:
    double max_seconds_;
    bool chorus_;
    double ph_ = 0.0;
    FracDelayLine line_;
    std::vector<float> dl_, dr_, wl_, wr_, src_l_, src_r_;
};

class StaticFlangerEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        ensure_size(dl_, n);
        ensure_size(dr_, n);
        ensure_size(wl_, n);
        ensure_size(wr_, n);
        ensure_size(src_l_, n);
        ensure_size(src_r_, n);
        double d = (0.0002 + std::fabs(spec.p[0]) * 0.008) * sample_rate_;
        float left = spec.p[0] >= 0.0f ? static_cast<float>(d) : 1.0f;
        float right = spec.p[0] >= 0.0f ? 1.0f : static_cast<float>(d);
        std::fill(dl_.begin(), dl_.begin() + n, left);
        std::fill(dr_.begin(), dr_.begin() + n, right);
        float feedback = spec.p[1];
        float wet = spec.p[2];
        std::copy(l, l + n, src_l_.begin());
        std::copy(r, r + n, src_r_.begin());
        line_.write_read(src_l_.data(), src_r_.data(), wl_.data(), wr_.data(), n, dl_.data(),
                         dr_.data(), feedback);
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = l[i] * (1.0f - wet) + wl_[i] * wet;
            r[i] = r[i] * (1.0f - wet) + wr_[i] * wet;
        }
    }
  protected:
    void setup() override { line_.init(0.05, sample_rate_); }

  private:
    FracDelayLine line_;
    std::vector<float> dl_, dr_, wl_, wr_, src_l_, src_r_;
};

// ---------------------------------------------------------------------------
// Phaser
// ---------------------------------------------------------------------------

class PhaserEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        if (n == 0) {
            return;
        }
        ensure_size(sweep_, n);
        ensure_size(dry_l_, n);
        ensure_size(dry_r_, n);
        double rate = 0.05 + spec.p[3] * spec.p[3] * 8.0;
        double lo = cutoff_hz(spec.p[0] * 0.7);
        double hi = cutoff_hz(spec.p[0] * 0.7 + (spec.p[1] - spec.p[0]) * 0.7 * spec.p[2] + 0.2);
        double last = ph_;
        for (std::size_t i = 0; i < n; ++i) {
            last = ph_ + static_cast<double>(i) * rate / sample_rate_;
            sweep_[i] = static_cast<float>(lo + (hi - lo) * (std::sin(kTwoPi * last) + 1.0) * 0.5);
        }
        ph_ = std::fmod(last, 1.0);
        std::copy(l, l + n, dry_l_.begin());
        std::copy(r, r + n, dry_r_.begin());
        l[0] += fb_[0] * spec.p[4];
        r[0] += fb_[1] * spec.p[4];
        const std::size_t chunk = 256;
        for (std::size_t i = 0; i < n; i += chunk) {
            std::size_t j = std::min(i + chunk, n);
            double f0 = sweep_[(i + j) / 2];
            BiquadCoeffs c = biquad_coeffs(FilterType::AllPass, f0, 0.7, sample_rate_);
            for (int s = 0; s < kStages; ++s) {
                stage_[s][0].set_coeffs(c);
                stage_[s][1].set_coeffs(c);
                stage_[s][0].process(l + i, l + i, j - i);
                stage_[s][1].process(r + i, r + i, j - i);
            }
        }
        fb_[0] = l[n - 1];
        fb_[1] = r[n - 1];
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = (dry_l_[i] + l[i]) * 0.5f;
            r[i] = (dry_r_[i] + r[i]) * 0.5f;
        }
    }
  protected:
    void setup() override {
        for (int s = 0; s < kStages; ++s) {
            stage_[s][0].reset();
            stage_[s][1].reset();
        }
        ph_ = 0.0;
        fb_[0] = fb_[1] = 0.0f;
    }

  private:
    static constexpr int kStages = 4;
    Biquad stage_[kStages][2];
    double ph_ = 0.0;
    float fb_[2] = {0.0f, 0.0f};
    std::vector<float> sweep_, dry_l_, dry_r_;
};

// ---------------------------------------------------------------------------
// Auto-Wah
// ---------------------------------------------------------------------------

class AutoWahEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        ensure_size(cut_, n);
        ensure_size(wet_l_, n);
        ensure_size(wet_r_, n);
        float coef = static_cast<float>(std::exp(
            -1.0 / (sample_rate_ * (0.002 + (1.0 - spec.p[0]) * (1.0 - spec.p[0]) * 0.3))));
        double base = cutoff_hz(spec.p[2]);
        double span = (cutoff_hz(1.0) - base) * 0.4;
        for (std::size_t i = 0; i < n; ++i) {
            float level = std::max(std::fabs(l[i]), std::fabs(r[i]));
            float env = follower_.process_one(level, coef);
            cut_[i] = static_cast<float>(base + spec.p[1] * clampd(env * 3.0, 0.0, 1.0) * span);
        }
        double q = res_to_q(spec.p[3] * 0.7);
        flt_[0].process_var(l, wet_l_.data(), n, FilterType::BandPass, cut_.data(), q,
                            sample_rate_);
        flt_[1].process_var(r, wet_r_.data(), n, FilterType::BandPass, cut_.data(), q,
                            sample_rate_);
        float wet = spec.p[4];
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = l[i] * (1.0f - wet) + wet_l_[i] * 2.0f * wet;
            r[i] = r[i] * (1.0f - wet) + wet_r_[i] * 2.0f * wet;
        }
    }

  protected:
    void setup() override {
        follower_.reset(0.0f);
        flt_[0].reset();
        flt_[1].reset();
    }

  private:
    OnePole follower_;
    TVFilter flt_[2];
    std::vector<float> cut_, wet_l_, wet_r_;
};

// ---------------------------------------------------------------------------
// Parametric EQ
// ---------------------------------------------------------------------------

class ParametricEqEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        double f0 = cutoff_hz(spec.p[0]);
        double gain_db = spec.p[1] * 18.0;
        double q = 0.3 + (1.0 - spec.p[2]) * 6.0;
        bq_[0].set(FilterType::Peak, f0, q, sample_rate_, gain_db);
        bq_[1].set(FilterType::Peak, f0, q, sample_rate_, gain_db);
        bq_[0].process_inplace(l, n);
        bq_[1].process_inplace(r, n);
    }

  protected:
    void setup() override {
        bq_[0].reset();
        bq_[1].reset();
    }

  private:
    Biquad bq_[2];
};

// ---------------------------------------------------------------------------
// Limiter
// ---------------------------------------------------------------------------

void LimiterEffect::setup() {
    env_ = 1.0;
    gr_ = 0.0f;
}

void LimiterEffect::process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                            const EffectContext &) {
    if (n == 0) {
        return;
    }
    ensure_size(env_buf_, n);
    float pre = 0.05f + spec.p[0];
    for (std::size_t i = 0; i < n; ++i) {
        l[i] *= pre;
        r[i] *= pre;
    }
    double att = std::exp(-1.0 / (sample_rate_ * (0.0002 + spec.p[1] * spec.p[1] * 0.05)));
    double rel = std::exp(-1.0 / (sample_rate_ * (0.01 + spec.p[2] * spec.p[2] * 1.0)));
    const std::size_t hop = 16;
    double e = env_;
    double min_env = 1.0;
    for (std::size_t i = 0; i < n; i += hop) {
        std::size_t j = std::min(i + hop, n);
        double tgt = 1.0;
        for (std::size_t k = i; k < j; ++k) {
            double level = std::max(std::max(std::fabs(l[k]), std::fabs(r[k])), 1e-9f);
            tgt = std::min(tgt, std::min(1.0 / level, 1.0));
        }
        double coef = tgt < e ? att : rel;
        e = tgt + (e - tgt) * std::pow(coef, static_cast<double>(j - i));
        for (std::size_t k = i; k < j; ++k) {
            env_buf_[k] = static_cast<float>(e);
        }
        min_env = std::min(min_env, e);
    }
    env_ = e;
    gr_ = static_cast<float>(1.0 - min_env);
    float post = spec.p[3];
    for (std::size_t i = 0; i < n; ++i) {
        l[i] = l[i] * env_buf_[i] * post;
        r[i] = r[i] * env_buf_[i] * post;
    }
}

// ---------------------------------------------------------------------------
// Vinyl
// ---------------------------------------------------------------------------

class VinylEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        ensure_size(gen_, n);
        ensure_size(aged_l_, n);
        ensure_size(aged_r_, n);
        std::fill(gen_.begin(), gen_.begin() + n, 0.0f);
        double q = 0.4 + spec.p[3] * 1.2;
        bq_[0].set(FilterType::BandPass, 1800.0, q, sample_rate_);
        bq_[1].set(FilterType::BandPass, 1800.0, q, sample_rate_);
        bq_[0].process(l, aged_l_.data(), n);
        bq_[1].process(r, aged_r_.data(), n);
        float age = spec.p[3];
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = l[i] * (1.0f - age) + aged_l_[i] * 2.2f * age;
            r[i] = r[i] * (1.0f - age) + aged_r_[i] * 2.2f * age;
        }
        float dust = spec.p[0];
        if (dust > 0.0f) {
            float p = dust * dust * 0.002f;
            for (std::size_t i = 0; i < n; ++i) {
                if (rng().next_unit() < p) {
                    gen_[i] += rng().next_bipolar() * 0.8f;
                }
            }
        }
        float scratch = spec.p[1];
        if (scratch > 0.0f) {
            float p = scratch * scratch * 0.0004f;
            for (std::size_t i = 0; i < n; ++i) {
                if (rng().next_unit() < p) {
                    float amp = rng().next_range(0.5f, 1.0f);
                    // np.convolve(imp, hanning(64), mode="same")
                    for (int k = 0; k < 64; ++k) {
                        long target = static_cast<long>(i) + k - 31;
                        if (target < 0 || target >= static_cast<long>(n)) {
                            continue;
                        }
                        gen_[static_cast<std::size_t>(target)] += amp * hann_[k];
                    }
                }
            }
        }
        float noise = spec.p[2];
        if (noise > 0.0f) {
            for (std::size_t i = 0; i < n; ++i) {
                float sm = lp_.process_one(rng().next_bipolar(), 0.995f);
                gen_[i] += sm * noise * 3.0f;
            }
        }
        float wet = spec.p[4] * 0.5f;
        for (std::size_t i = 0; i < n; ++i) {
            l[i] += gen_[i] * wet;
            r[i] += gen_[i] * wet;
        }
    }
  protected:
    void setup() override {
        bq_[0].reset();
        bq_[1].reset();
        lp_.reset(0.0f);
        for (int i = 0; i < 64; ++i) {
            hann_[i] = static_cast<float>(0.5 - 0.5 * std::cos(kTwoPi * i / 63.0));
        }
    }

  private:
    Biquad bq_[2];
    OnePole lp_;
    float hann_[64] = {};
    std::vector<float> gen_, aged_l_, aged_r_;
};

// ---------------------------------------------------------------------------
// Comb filter
// ---------------------------------------------------------------------------

class CombFilterEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        double f0 = 40.0 * std::pow(100.0, clampd(spec.p[0], 0.0, 1.0));
        std::size_t len = std::max<std::size_t>(2, static_cast<std::size_t>(sample_rate_ / f0));
        if (buf_[0].size() != len) {
            buf_[0].assign(len, 0.0f);
            buf_[1].assign(len, 0.0f);
            idx_ = 0;
        }
        float reso = spec.p[1];
        float wet = spec.p[2];
        float wet_gain = wet * (1.0f - reso * 0.5f);
        float *chans[2] = {l, r};
        for (std::size_t i = 0; i < n; ++i) {
            std::size_t idx = (idx_ + i) % len;
            for (int c = 0; c < 2; ++c) {
                float y = chans[c][i] + buf_[c][idx];
                buf_[c][idx] = reso * y;
                chans[c][i] = chans[c][i] * (1.0f - wet) + y * wet_gain;
            }
        }
        idx_ = (idx_ + n) % len;
    }
  protected:
    void setup() override {
        buf_[0].clear();
        buf_[1].clear();
        idx_ = 0;
    }

  private:
    std::vector<float> buf_[2];
    std::size_t idx_ = 0;
};

// ---------------------------------------------------------------------------
// Cabinet
// ---------------------------------------------------------------------------

class CabinetEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        ensure_size(dry_l_, n);
        ensure_size(dry_r_, n);
        ensure_size(wet_l_, n);
        ensure_size(wet_r_, n);
        std::copy(l, l + n, dry_l_.begin());
        std::copy(r, r + n, dry_r_.begin());
        std::copy(l, l + n, wet_l_.begin());
        std::copy(r, r + n, wet_r_.begin());
        double w = 0.0006 + spec.p[0] * 0.004;
        double h = 0.0008 + spec.p[1] * 0.006;
        double damp = 0.2 + spec.p[2] * 0.7;
        struct Tap {
            std::size_t d;
            float g;
        };
        Tap taps[3] = {
            {static_cast<std::size_t>(w * sample_rate_),
             static_cast<float>(0.7 * (1.0 - damp * 0.5))},
            {static_cast<std::size_t>(h * sample_rate_),
             static_cast<float>(0.5 * (1.0 - damp * 0.5))},
            {static_cast<std::size_t>((w + h) * sample_rate_),
             static_cast<float>(0.35 * (1.0 - damp))},
        };
        for (const Tap &tap : taps) {
            if (tap.d == 0 || tap.d >= n) {
                continue;
            }
            for (std::size_t i = tap.d; i < n; ++i) {
                wet_l_[i] += tap.g * dry_l_[i - tap.d];
                wet_r_[i] += tap.g * dry_r_[i - tap.d];
            }
        }
        double tone_f = 800.0 + spec.p[3] * 5000.0;
        bq_[0].set(FilterType::LowPass, tone_f, 0.7, sample_rate_);
        bq_[1].set(FilterType::LowPass, tone_f, 0.7, sample_rate_);
        bq_[0].process_inplace(wet_l_.data(), n);
        bq_[1].process_inplace(wet_r_.data(), n);
        float wet = spec.p[4];
        for (std::size_t i = 0; i < n; ++i) {
            l[i] = dry_l_[i] * (1.0f - wet) + wet_l_[i] * 0.5f * wet;
            r[i] = dry_r_[i] * (1.0f - wet) + wet_r_[i] * 0.5f * wet;
        }
    }
  protected:
    void setup() override {
        bq_[0].reset();
        bq_[1].reset();
    }

  private:
    Biquad bq_[2];
    std::vector<float> dry_l_, dry_r_, wet_l_, wet_r_;
};

// ---------------------------------------------------------------------------
// Tempo-synced delay
// ---------------------------------------------------------------------------

class DelayEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &ctx) override {
        static const double kSteps[8] = {0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0};
        int step_idx = static_cast<int>(spec.p[0] * 7.0);
        step_idx = std::max(0, std::min(7, step_idx));
        double bpm = ctx.bpm > 0.0 ? ctx.bpm : 120.0;
        std::size_t cap = buf_[0].size();
        double d = kSteps[step_idx] * 60.0 / bpm * sample_rate_;
        std::size_t D = static_cast<std::size_t>(
            clampd(d, 32.0, static_cast<double>(cap) - 1.0));
        int mode = static_cast<int>(spec.p[3]);
        float fb = spec.p[1];
        float wet = spec.p[2];
        ensure_size(tap_l_, n);
        ensure_size(tap_r_, n);
        for (std::size_t i = 0; i < n; ++i) {
            std::size_t idx = (w_ + i) % cap;
            std::size_t rd = (idx + cap - (D % cap)) % cap;
            tap_l_[i] = buf_[0][rd];
            tap_r_[i] = buf_[1][rd];
        }
        for (std::size_t i = 0; i < n; ++i) {
            std::size_t idx = (w_ + i) % cap;
            float tl = tap_l_[i];
            float tr = tap_r_[i];
            float out_l = 0.0f;
            float out_r = 0.0f;
            if (mode == 0) {
                float m = (l[i] + r[i]) * 0.5f;
                buf_[0][idx] = m + tl * fb;
                buf_[1][idx] = buf_[0][idx];
                out_l = tl;
                out_r = tl;
            } else if (mode == 1) {
                float m = (l[i] + r[i]) * 0.5f;
                buf_[0][idx] = m + tr * fb;
                buf_[1][idx] = tl;
                out_l = tl;
                out_r = tr;
            } else if (mode == 2) {
                float m = (l[i] + r[i]) * 0.5f;
                buf_[1][idx] = m + tl * fb;
                buf_[0][idx] = tr;
                out_l = tl;
                out_r = tr;
            } else {
                buf_[0][idx] = l[i] + tl * fb;
                buf_[1][idx] = r[i] + tr * fb;
                if (mode == 3) {
                    out_l = tl;
                    out_r = tr;
                } else {
                    out_l = tr;
                    out_r = tl;
                }
            }
            l[i] += out_l * wet;
            r[i] += out_r * wet;
        }
        w_ = (w_ + n) % cap;
    }
  protected:
    void setup() override {
        std::size_t cap = std::max<std::size_t>(64, static_cast<std::size_t>(2.0 * sample_rate_));
        buf_[0].assign(cap, 0.0f);
        buf_[1].assign(cap, 0.0f);
        w_ = 0;
    }

  private:
    std::vector<float> buf_[2];
    std::vector<float> tap_l_, tap_r_;
    std::size_t w_ = 0;
};

// ---------------------------------------------------------------------------
// Reverb
// ---------------------------------------------------------------------------

void ReverbEffect::setup() {
    for (int k = 0; k < 8; ++k) {
        comb_l_[k].buf.assign(kCombs[k], 0.0f);
        comb_l_[k].i = 0;
        comb_l_[k].lp = 0.0f;
        comb_r_[k].buf.assign(kCombs[k] + kSpread, 0.0f);
        comb_r_[k].i = 0;
        comb_r_[k].lp = 0.0f;
    }
    for (int k = 0; k < 4; ++k) {
        ap_l_[k].buf.assign(kAllpass[k], 0.0f);
        ap_l_[k].i = 0;
        ap_r_[k].buf.assign(kAllpass[k] + kSpread, 0.0f);
        ap_r_[k].i = 0;
    }
    predelay_.init(0.25, sample_rate_);
}

void ReverbEffect::ensure(std::size_t n) {
    ensure_size(pre_l_, n);
    ensure_size(pre_r_, n);
    ensure_size(mono_, n);
    ensure_size(wet_l_, n);
    ensure_size(wet_r_, n);
    ensure_size(tmp_, n);
    ensure_size(delay_buf_, n);
}

void ReverbEffect::comb(const float *x, float *out, std::size_t n, std::size_t length,
                        float feedback, float damp, CombState &st) {
    if (st.buf.size() != length) {
        st.buf.assign(length, 0.0f);
        st.i = 0;
        st.lp = 0.0f;
    }
    std::size_t pos = 0;
    while (pos < n) {
        std::size_t m = std::min(std::min(length - st.i, n - pos), length);
        if (m == 0) {
            break;
        }
        double sum = 0.0;
        for (std::size_t k = 0; k < m; ++k) {
            float seg = st.buf[st.i + k];
            out[pos + k] = seg;
            sum += seg;
        }
        st.lp = static_cast<float>(st.lp * damp + (sum / static_cast<double>(m)) * (1.0 - damp));
        for (std::size_t k = 0; k < m; ++k) {
            float seg = out[pos + k];
            st.buf[st.i + k] = x[pos + k] + seg * feedback * (1.0f - damp) + st.lp * feedback * damp;
        }
        st.i = (st.i + m) % length;
        pos += m;
    }
}

void ReverbEffect::allpass(const float *x, float *out, std::size_t n, std::size_t length,
                           AllpassState &st) {
    if (st.buf.size() != length) {
        st.buf.assign(length, 0.0f);
        st.i = 0;
    }
    const float g = 0.5f;
    std::size_t pos = 0;
    while (pos < n) {
        std::size_t m = std::min(length - st.i, n - pos);
        if (m == 0) {
            break;
        }
        for (std::size_t k = 0; k < m; ++k) {
            float seg = st.buf[st.i + k];
            float xin = x[pos + k];
            out[pos + k] = seg - g * xin;
            st.buf[st.i + k] = xin + g * seg;
        }
        st.i = (st.i + m) % length;
        pos += m;
    }
}

void ReverbEffect::process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                           const EffectContext &) {
    if (n == 0) {
        return;
    }
    ensure(n);
    float room = 0.7f + spec.p[0] * 0.28f;
    float damp = spec.p[1] * 0.6f;
    float pd = static_cast<float>(std::max(1.0, spec.p[2] * 0.2 * sample_rate_));
    std::fill(delay_buf_.begin(), delay_buf_.begin() + n, pd);
    predelay_.write_read(l, r, pre_l_.data(), pre_r_.data(), n, delay_buf_.data(),
                         delay_buf_.data(), 0.0f);
    for (std::size_t i = 0; i < n; ++i) {
        mono_[i] = (pre_l_[i] + pre_r_[i]) * 0.5f;
        wet_l_[i] = 0.0f;
        wet_r_[i] = 0.0f;
    }
    for (int k = 0; k < 8; ++k) {
        comb(mono_.data(), tmp_.data(), n, kCombs[k], room, damp, comb_l_[k]);
        for (std::size_t i = 0; i < n; ++i) {
            wet_l_[i] += tmp_[i];
        }
        comb(mono_.data(), tmp_.data(), n, kCombs[k] + kSpread, room, damp, comb_r_[k]);
        for (std::size_t i = 0; i < n; ++i) {
            wet_r_[i] += tmp_[i];
        }
    }
    for (int k = 0; k < 4; ++k) {
        allpass(wet_l_.data(), tmp_.data(), n, kAllpass[k], ap_l_[k]);
        std::copy(tmp_.begin(), tmp_.begin() + n, wet_l_.begin());
        allpass(wet_r_.data(), tmp_.data(), n, kAllpass[k] + kSpread, ap_r_[k]);
        std::copy(tmp_.begin(), tmp_.begin() + n, wet_r_.begin());
    }
    float width = spec.p[3];
    float wet = spec.p[4];
    for (std::size_t i = 0; i < n; ++i) {
        float wl = wet_l_[i] * 0.06f;
        float wr = wet_r_[i] * 0.06f;
        float mid = (wl + wr) * 0.5f;
        float sl = wl * width + mid * (1.0f - width);
        float sr = wr * width + mid * (1.0f - width);
        l[i] = l[i] * (1.0f - wet * 0.4f) + sl * wet;
        r[i] = r[i] * (1.0f - wet * 0.4f) + sr * wet;
    }
}

// ---------------------------------------------------------------------------
// MultiFilter
// ---------------------------------------------------------------------------

class MultiFilterEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &) override {
        int type = static_cast<int>(spec.p[0]);
        type = std::max(0, std::min(7, type));
        double f0 = cutoff_hz(spec.p[1]);
        double gain_db = spec.p[3] * 18.0;
        float lin_gain = static_cast<float>(std::pow(10.0, gain_db / 20.0));
        if (type == 5) {  // Band Isolate
            double q = 0.4 + (1.0 - spec.p[2]) * 4.0;
            float boost = 1.0f + spec.p[2] * 2.0f;
            bq_[0].set(FilterType::BandPass, f0, q, sample_rate_);
            bq_[1].set(FilterType::BandPass, f0, q, sample_rate_);
            for (std::size_t i = 0; i < n; ++i) {
                l[i] = bq_[0].process_one(l[i]) * boost * lin_gain;
                r[i] = bq_[1].process_one(r[i]) * boost * lin_gain;
            }
            return;
        }
        static const FilterType kTypes[8] = {
            FilterType::LowPass,  FilterType::HighPass, FilterType::BandPass,
            FilterType::Notch,    FilterType::Peak,     FilterType::BandPass,
            FilterType::LowShelf, FilterType::HighShelf};
        double q = res_to_q(spec.p[2] * 0.6);
        bq_[0].set(kTypes[type], f0, q, sample_rate_, gain_db);
        bq_[1].set(kTypes[type], f0, q, sample_rate_, gain_db);
        bool scale = type <= 3;
        for (std::size_t i = 0; i < n; ++i) {
            float yl = bq_[0].process_one(l[i]);
            float yr = bq_[1].process_one(r[i]);
            l[i] = scale ? yl * lin_gain : yl;
            r[i] = scale ? yr * lin_gain : yr;
        }
    }

  protected:
    void setup() override {
        bq_[0].reset();
        bq_[1].reset();
    }

  private:
    Biquad bq_[2];
};

// ---------------------------------------------------------------------------

std::unique_ptr<Effect> create_effect(EffectKind kind, double sample_rate, std::uint64_t seed) {
    std::unique_ptr<Effect> fx;
    switch (kind) {
    case EffectKind::Distortion:
        fx = std::make_unique<DistortionEffect>();
        break;
    case EffectKind::BitCrusher:
        fx = std::make_unique<BitCrusherEffect>();
        break;
    case EffectKind::Compressor:
        fx = std::make_unique<CompressorEffect>();
        break;
    case EffectKind::Flanger:
        fx = std::make_unique<ModDelayEffect>(0.06, false);
        break;
    case EffectKind::Chorus:
        fx = std::make_unique<ModDelayEffect>(0.12, true);
        break;
    case EffectKind::Phaser:
        fx = std::make_unique<PhaserEffect>();
        break;
    case EffectKind::AutoWah:
        fx = std::make_unique<AutoWahEffect>();
        break;
    case EffectKind::ParametricEQ:
        fx = std::make_unique<ParametricEqEffect>();
        break;
    case EffectKind::Limiter:
        fx = std::make_unique<LimiterEffect>();
        break;
    case EffectKind::Vinyl:
        fx = std::make_unique<VinylEffect>();
        break;
    case EffectKind::CombFilter:
        fx = std::make_unique<CombFilterEffect>();
        break;
    case EffectKind::Cabinet:
        fx = std::make_unique<CabinetEffect>();
        break;
    case EffectKind::StaticFlanger:
        fx = std::make_unique<StaticFlangerEffect>();
        break;
    case EffectKind::Delay:
        fx = std::make_unique<DelayEffect>();
        break;
    case EffectKind::Reverb:
        fx = std::make_unique<ReverbEffect>();
        break;
    case EffectKind::MultiFilter:
        fx = std::make_unique<MultiFilterEffect>();
        break;
    }
    fx->configure(kind, sample_rate, seed);
    return fx;
}

}  // namespace refrag
