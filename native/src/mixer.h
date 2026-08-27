// Channel strip (EQ / width / pan) and the master bus: master EQ, delay,
// reverb sends, insert effects, limiter and output volume.
#pragma once

#include <memory>
#include <vector>

#include "dsp.h"
#include "effects.h"
#include "spec.h"

namespace refrag {

inline std::size_t width_buffer_len(double sample_rate, std::size_t block_size) {
    std::size_t by_rate = static_cast<std::size_t>(sample_rate * 0.02);
    return std::max(std::max<std::size_t>(2048, by_rate), block_size);
}

// Micro-delay on one channel used by the strip's width control.
class WidthDelay {
  public:
    void init(std::size_t length) {
        length_ = std::max<std::size_t>(1, length);
        buf_.assign(length_, 0.0f);
        w_ = 0;
    }

    void process(float *sig, std::size_t n, std::size_t delay) {
        if (n == 0 || length_ == 0) {
            return;
        }
        if (tmp_.size() < n) {
            tmp_.assign(n, 0.0f);
        }
        std::copy(sig, sig + n, tmp_.begin());
        for (std::size_t i = 0; i < n; ++i) {
            if (i < delay) {
                std::size_t back = delay - i;
                sig[i] = buf_[(w_ + length_ - (back % length_)) % length_];
            } else {
                sig[i] = tmp_[i - delay];
            }
        }
        for (std::size_t i = 0; i < n; ++i) {
            buf_[(w_ + i) % length_] = tmp_[i];
        }
        w_ = (w_ + n) % length_;
    }

  private:
    std::size_t length_ = 0;
    std::size_t w_ = 0;
    std::vector<float> buf_;
    std::vector<float> tmp_;
};

class ChannelStrip {
  public:
    void configure(double sample_rate, std::size_t block_size) {
        sample_rate_ = sample_rate;
        for (auto &bq : eq_) {
            bq.reset();
        }
        std::size_t len = width_buffer_len(sample_rate, block_size);
        width_[0].init(len);
        width_[1].init(len);
    }

    void process(float *l, float *r, std::size_t n, const MixerSpec &mx);

  private:
    double sample_rate_ = kDefaultSampleRate;
    Biquad eq_[6];
    WidthDelay width_[2];
};

// Global multi-tap delay with per-tap pan and looping (engine.MasterDelay).
class MasterDelay {
  public:
    void configure(double sample_rate);
    // Writes the wet taps into out_l/out_r (overwrites).
    void process(const float *in_l, const float *in_r, float *out_l, float *out_r, std::size_t n,
                 const MasterSpec &mp, double bpm);

  private:
    double sample_rate_ = kDefaultSampleRate;
    std::vector<float> buf_[2];
    std::vector<float> tap_l_, tap_r_;
    std::size_t w_ = 0;
    OnePole lp_[2];
};

class MasterSection {
  public:
    void configure(double sample_rate, std::size_t block_size);
    void sync_effects(const MasterSpec &spec, std::uint64_t seed_base);

    // mix/send buffers are modified in place; mix ends up holding the output.
    void process(float *mix_l, float *mix_r, float *send_delay_l, float *send_delay_r,
                 float *send_reverb_l, float *send_reverb_r, std::size_t n, const MasterSpec &mp,
                 double bpm);

    float limiter_gr() const { return lim_gr_; }

  private:
    void eq(float *l, float *r, std::size_t n, const MasterSpec &mp);

    double sample_rate_ = kDefaultSampleRate;
    std::size_t block_size_ = 512;
    MasterDelay delay_;
    std::unique_ptr<Effect> reverb_;
    std::unique_ptr<Effect> limiter_;
    std::unique_ptr<Effect> fx_[2];
    bool fx_present_[2] = {false, false};
    EffectKind fx_kind_[2] = {EffectKind::Distortion, EffectKind::Distortion};
    Biquad eq_[6];
    std::vector<float> wet_l_, wet_r_, dry_l_, dry_r_;
    float lim_gr_ = 0.0f;
};

}  // namespace refrag
