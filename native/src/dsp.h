// Core DSP primitives shared by every native machine, effect and mixer stage.
// Filter state handling follows scipy `lfilter` conventions so coefficients
// stay interchangeable with the offline analysis tooling.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>

namespace refrag {

inline constexpr double kTwoPi = 6.283185307179586476925286766559;
inline constexpr double kDefaultSampleRate = 44100.0;

inline float clampf(float x, float lo, float hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

inline double clampd(double x, double lo, double hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

inline double note_freq(double note) {
    return 440.0 * std::pow(2.0, (note - 69.0) / 12.0);
}

// ---------------------------------------------------------------------------
// Deterministic per-instance RNG (xorshift64*, seeded explicitly).
// ---------------------------------------------------------------------------

class Rng {
  public:
    explicit Rng(std::uint64_t seed = 0x9E3779B97F4A7C15ull) { reseed(seed); }

    void reseed(std::uint64_t seed) {
        state_ = seed ? seed : 0x9E3779B97F4A7C15ull;
        for (int i = 0; i < 4; ++i) {
            next_u64();
        }
    }

    std::uint64_t next_u64() {
        std::uint64_t x = state_;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        state_ = x;
        return x;
    }

    // Uniform in [0,1).
    float next_unit() {
        return static_cast<float>((next_u64() >> 40) * (1.0 / 16777216.0));
    }

    // Uniform in [-1,1).
    float next_bipolar() { return next_unit() * 2.0f - 1.0f; }

    float next_range(float lo, float hi) { return lo + (hi - lo) * next_unit(); }

  private:
    std::uint64_t state_ = 0x9E3779B97F4A7C15ull;
};

// ---------------------------------------------------------------------------
// Oscillators (phase in cycles, wraps at 1.0)
// ---------------------------------------------------------------------------

// polyBLEP correction for a naive saw; `dt` is the per-sample phase increment.
inline double polyblep(double ph, double dt) {
    if (dt <= 0.0) {
        return 0.0;
    }
    if (ph < dt) {
        double t = ph / dt;
        return -(2.0 * t - t * t - 1.0);
    }
    if (ph > 1.0 - dt) {
        double t = (ph - 1.0) / dt;
        return -(t * t + 2.0 * t + 1.0);
    }
    return 0.0;
}

// Waveforms 0..8 -> Sine, Triangle, Saw, Saw HQ, Square, Square HQ, Pulse,
// Half Sine, Noise.  `dt` enables band limiting for the HQ variants, `rng`
// provides the noise source.
inline float osc_wave(int wave, double phase, double dt = 0.0, Rng *rng = nullptr) {
    double ph = phase - std::floor(phase);
    switch (wave) {
    case 0:
        return static_cast<float>(std::sin(kTwoPi * ph));
    case 1:
        return static_cast<float>(4.0 * std::fabs(ph - 0.5) - 1.0);
    case 2:
        return static_cast<float>(2.0 * ph - 1.0);
    case 3:
        return static_cast<float>(2.0 * ph - 1.0 + polyblep(ph, dt));
    case 4:
        return ph < 0.5 ? 1.0f : -1.0f;
    case 5: {
        double v = ph < 0.5 ? 1.0 : -1.0;
        if (dt > 0.0) {
            double p2 = ph + 0.5;
            p2 -= std::floor(p2);
            v += polyblep(ph, dt);
            v -= polyblep(p2, dt);
        }
        return static_cast<float>(v);
    }
    case 6:
        return ph < 0.25 ? 1.0f : -1.0f;
    case 7:
        return static_cast<float>(std::max(0.0, std::sin(kTwoPi * ph)) * 2.0 - 1.0);
    case 8:
        return rng ? rng->next_bipolar() : 0.0f;
    default:
        return 0.0f;
    }
}

// LFO shapes 0..4 -> Sine, Triangle, Saw, Square, Random (sample & hold).
inline float lfo_wave(int wave, double phase) {
    double ph = phase - std::floor(phase);
    switch (wave) {
    case 0:
        return static_cast<float>(std::sin(kTwoPi * ph));
    case 1:
        return static_cast<float>(4.0 * std::fabs(ph - 0.5) - 1.0);
    case 2:
        return static_cast<float>(2.0 * ph - 1.0);
    case 3:
        return ph < 0.5 ? 1.0f : -1.0f;
    default: {
        double cyc = std::floor(phase);
        double rnd = std::sin(cyc * 12.9898 + 78.233) * 43758.5453;
        return static_cast<float>(2.0 * (rnd - std::floor(rnd)) - 1.0);
    }
    }
}

// ---------------------------------------------------------------------------
// Envelopes
// ---------------------------------------------------------------------------

inline double env_time(double knob, double max_s = 4.0, double min_s = 0.001) {
    knob = clampd(knob, 0.0, 1.0);
    return min_s + (max_s - min_s) * std::pow(knob, 2.5);
}

inline double env_frames(double knob, double sample_rate, double max_s = 4.0,
                         double min_s = 0.001) {
    return std::max(1.0, env_time(knob, max_s, min_s) * sample_rate);
}

inline double adsr_level(double t, double a, double d, double s) {
    a = std::max(a, 1.0);
    d = std::max(d, 1.0);
    if (t < a) {
        return t / a;
    }
    if (t < a + d) {
        return 1.0 - (1.0 - s) * (t - a) / d;
    }
    return s;
}

// Gated ADSR matching dsp.adsr().  `t_release` < 0 means "still held".
inline double adsr(double t, double a, double d, double s, double r, double t_release) {
    r = std::max(r, 1.0);
    if (t_release < 0.0 || t < t_release) {
        return adsr_level(t, a, d, s);
    }
    double lr = adsr_level(t_release, a, d, s);
    return lr * std::max(0.0, 1.0 - (t - t_release) / r);
}

// ---------------------------------------------------------------------------
// Biquad filters
// ---------------------------------------------------------------------------

enum class FilterType {
    LowPass,
    HighPass,
    BandPass,
    Notch,
    Peak,
    LowShelf,
    HighShelf,
    AllPass,
    Bypass,
};

struct BiquadCoeffs {
    double b0 = 1.0, b1 = 0.0, b2 = 0.0, a1 = 0.0, a2 = 0.0;
};

BiquadCoeffs biquad_coeffs(FilterType type, double f0, double q, double sample_rate,
                           double gain_db = 0.0);

// Stateful mono biquad using the scipy transposed-direct-form-II state layout.
class Biquad {
  public:
    void reset() {
        z0_ = 0.0;
        z1_ = 0.0;
    }

    void set(FilterType type, double f0, double q, double sample_rate, double gain_db = 0.0) {
        if (has_params_ && type == type_ && f0 == f0_ && q == q_ && sample_rate == sr_ &&
            gain_db == gain_db_) {
            return;
        }
        c_ = biquad_coeffs(type, f0, q, sample_rate, gain_db);
        type_ = type;
        f0_ = f0;
        q_ = q;
        sr_ = sample_rate;
        gain_db_ = gain_db;
        has_params_ = true;
    }

    void set_coeffs(const BiquadCoeffs &c) {
        c_ = c;
        has_params_ = false;
    }

    inline float process_one(float x) {
        double xn = static_cast<double>(x);
        double y = c_.b0 * xn + z0_;
        z0_ = c_.b1 * xn - c_.a1 * y + z1_;
        z1_ = c_.b2 * xn - c_.a2 * y;
        return static_cast<float>(y);
    }

    void process(const float *src, float *dst, std::size_t n) {
        for (std::size_t i = 0; i < n; ++i) {
            dst[i] = process_one(src[i]);
        }
    }

    void process_inplace(float *buf, std::size_t n) { process(buf, buf, n); }

  private:
    BiquadCoeffs c_{};
    double z0_ = 0.0;
    double z1_ = 0.0;
    bool has_params_ = false;
    FilterType type_ = FilterType::Bypass;
    double f0_ = 0.0, q_ = 0.0, sr_ = 0.0, gain_db_ = 0.0;
};

// Time-varying filter: coefficients refreshed per chunk from the chunk
// mid-point cutoff, mirroring dsp.TVFilter.
class TVFilter {
  public:
    void reset() { bq_.reset(); }

    void process_const(const float *src, float *dst, std::size_t n, FilterType type,
                       double cutoff, double q, double sample_rate) {
        bq_.set(type, cutoff, q, sample_rate);
        bq_.process(src, dst, n);
    }

    void process_var(const float *src, float *dst, std::size_t n, FilterType type,
                     const float *cutoff, double q, double sample_rate,
                     std::size_t chunk = 128) {
        if (n == 0) {
            return;
        }
        bool constant = true;
        for (std::size_t i = 1; i < n; ++i) {
            if (cutoff[i] != cutoff[0]) {
                constant = false;
                break;
            }
        }
        if (constant) {
            process_const(src, dst, n, type, cutoff[0], q, sample_rate);
            return;
        }
        for (std::size_t i = 0; i < n; i += chunk) {
            std::size_t j = std::min(i + chunk, n);
            bq_.set(type, cutoff[(i + j) / 2], q, sample_rate);
            bq_.process(src + i, dst + i, j - i);
        }
    }

  private:
    Biquad bq_;
};

// One-pole smoother matching dsp.onepole_smooth (b=[1-coef], a=[1,-coef]).
class OnePole {
  public:
    void reset(float value = 0.0f) { state_ = value; }
    float state() const { return state_; }
    void set_state(float v) { state_ = v; }

    inline float process_one(float x, float coef) {
        state_ = (1.0f - coef) * x + coef * state_;
        return state_;
    }

    void process(const float *src, float *dst, std::size_t n, float coef) {
        for (std::size_t i = 0; i < n; ++i) {
            dst[i] = process_one(src[i], coef);
        }
    }

  private:
    float state_ = 0.0f;
};

// ---------------------------------------------------------------------------
// Shared mappings and shapers
// ---------------------------------------------------------------------------

inline double cutoff_hz(double norm) { return 20.0 * std::pow(900.0, clampd(norm, 0.0, 1.0)); }

inline double res_to_q(double res) {
    return 0.55 + std::pow(clampd(res, 0.0, 1.0), 1.6) * 14.0;
}

// program: 0 overdrive, 1 saturate, 2 fuzz, 3 foldback (dsp.distort).
inline float distort_sample(float x, int program, float amount) {
    float amt = clampf(amount, 0.0f, 1.0f);
    double drive = 1.0 + amt * 15.0;
    switch (program) {
    case 0: {
        double td = std::tanh(drive);
        return td > 0.0 ? static_cast<float>(std::tanh(x * drive) / td) : x;
    }
    case 1:
        return static_cast<float>(x / (1.0 + amt * std::fabs(x) * 4.0));
    case 2: {
        double th = std::max(1.0 - amt * 0.95, 0.05);
        return static_cast<float>(clampd(x, -th, th) / th);
    }
    case 3: {
        double th = std::max(1.0 - amt * 0.9, 0.1);
        double m = std::fmod(static_cast<double>(x) - th, 4.0 * th);
        if (m < 0.0) {
            m += 4.0 * th;
        }
        return static_cast<float>(std::fabs(std::fabs(m) - 2.0 * th) - th);
    }
    default:
        return x;
    }
}

// ---------------------------------------------------------------------------
// Delay lines
// ---------------------------------------------------------------------------

// Stereo circular delay line with fractional taps (effects.FracDelayLine).
class FracDelayLine {
  public:
    void init(double max_seconds, double sample_rate) {
        n_ = std::max<std::size_t>(4, static_cast<std::size_t>(max_seconds * sample_rate));
        buf_[0].assign(n_, 0.0f);
        buf_[1].assign(n_, 0.0f);
        w_ = 0;
    }

    std::size_t size() const { return n_; }

    // `delay_l`/`delay_r` hold per-sample delays; writes x + delayed*feedback.
    // Reads for a block are resolved against the pre-block buffer contents (the
    // vectorized semantics of the Python reference), so the feedback path never
    // sees samples written earlier in the same block.
    void write_read(const float *in_l, const float *in_r, float *out_l, float *out_r,
                    std::size_t frames, const float *delay_l, const float *delay_r,
                    float feedback) {
        if (n_ == 0) {
            return;
        }
        const float *in[2] = {in_l, in_r};
        float *out[2] = {out_l, out_r};
        const float *delays[2] = {delay_l, delay_r};
        double nn = static_cast<double>(n_);
        for (int c = 0; c < 2; ++c) {
            float *buf = buf_[c].data();
            for (std::size_t i = 0; i < frames; ++i) {
                double pos = static_cast<double>(w_ + i);
                double read_pos = std::fmod(pos - static_cast<double>(delays[c][i]), nn);
                if (read_pos < 0.0) {
                    read_pos += nn;
                }
                double fl = std::floor(read_pos);
                std::size_t i0 = static_cast<std::size_t>(fl) % n_;
                std::size_t i1 = (i0 + 1) % n_;
                float frac = static_cast<float>(read_pos - fl);
                out[c][i] = buf[i0] * (1.0f - frac) + buf[i1] * frac;
            }
            for (std::size_t i = 0; i < frames; ++i) {
                buf[(w_ + i) % n_] = in[c][i] + out[c][i] * feedback;
            }
        }
        w_ = (w_ + frames) % n_;
    }

  private:
    std::size_t n_ = 0;
    std::size_t w_ = 0;
    std::array<std::vector<float>, 2> buf_{};
};

}  // namespace refrag
