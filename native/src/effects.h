// The 16 insert effects.  Each instance owns its
// state and processes an in-place stereo block.
#pragma once

#include <memory>
#include <vector>

#include "dsp.h"
#include "spec.h"

namespace refrag {

// Sidechain taps: post-strip stereo lines of the first slots in the rack.
struct SidechainLines {
    static constexpr int kMax = 6;
    const float *l[kMax] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
    const float *r[kMax] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
};

struct EffectContext {
    double bpm = 120.0;
    const SidechainLines *lines = nullptr;
};

class Effect {
  public:
    virtual ~Effect() = default;

    void configure(EffectKind kind, double sample_rate, std::uint64_t seed) {
        kind_ = kind;
        sample_rate_ = sample_rate;
        rng_.reseed(seed);
        setup();
    }

    EffectKind kind() const { return kind_; }
    double sample_rate() const { return sample_rate_; }
    // Gain reduction for VU reporting (limiter / compressor).
    virtual float gain_reduction() const { return 0.0f; }

    virtual void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                         const EffectContext &ctx) = 0;

  protected:
    virtual void setup() {}

    Rng &rng() { return rng_; }

    double sample_rate_ = kDefaultSampleRate;
    EffectKind kind_ = EffectKind::Distortion;
    Rng rng_{1};
};

// Creates a configured effect; never returns null for a valid EffectKind.
std::unique_ptr<Effect> create_effect(EffectKind kind, double sample_rate, std::uint64_t seed);

// Freeverb-style reverb, exposed directly because the master bus reuses it.
class ReverbEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &ctx) override;

  protected:
    void setup() override;

  private:
    struct CombState {
        std::vector<float> buf;
        std::size_t i = 0;
        float lp = 0.0f;
    };
    struct AllpassState {
        std::vector<float> buf;
        std::size_t i = 0;
    };

    void comb(const float *x, float *out, std::size_t n, std::size_t length, float feedback,
              float damp, CombState &st);
    void allpass(const float *x, float *out, std::size_t n, std::size_t length, AllpassState &st);
    void ensure(std::size_t n);

    static constexpr std::size_t kCombs[8] = {1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617};
    static constexpr std::size_t kAllpass[4] = {556, 441, 341, 225};
    static constexpr std::size_t kSpread = 23;

    CombState comb_l_[8];
    CombState comb_r_[8];
    AllpassState ap_l_[4];
    AllpassState ap_r_[4];
    FracDelayLine predelay_;
    std::vector<float> pre_l_, pre_r_, mono_, wet_l_, wet_r_, tmp_, delay_buf_;
};

// Limiter, reused by the master bus.
class LimiterEffect final : public Effect {
  public:
    void process(float *l, float *r, std::size_t n, const EffectSpec &spec,
                 const EffectContext &ctx) override;
    float gain_reduction() const override { return gr_; }

  protected:
    void setup() override;

  private:
    double env_ = 1.0;
    float gr_ = 0.0f;
    std::vector<float> env_buf_;
};

}  // namespace refrag
