// Machine voices and the per-machine render engine.  Every one of the twelve
// families is rendered here; nothing in this file touches Python.
#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "dsp.h"
#include "expr.h"
#include "samples.h"
#include "spec.h"

namespace refrag {

inline constexpr int kMaxVoices = 64;
inline constexpr int kVocoderBands = 8;
inline constexpr int kPadHarmonics = 24;

// Stereo view of another slot's output, used by the vocoder for machine
// modulators / carriers.
struct MachineAudio {
    const float *l = nullptr;
    const float *r = nullptr;
};

struct RenderContext {
    const MachineAudio *outputs = nullptr;       // rendered earlier this block
    const MachineAudio *prev_outputs = nullptr;  // previous block
    int slot_count = 0;
    double bpm = 120.0;
};

enum class PcmLoop { None, Forward, PingPong };

struct Voice {
    int note = 0;
    float vel = 0.0f;
    int flags = 0;
    std::int64_t t = 0;
    std::int64_t released_at = -1;
    bool dead = false;
    int start_offset = 0;
    std::uint64_t serial = 0;

    // Generic oscillator phases (organ uses all nine).
    std::array<double, 12> phase{};
    double note_from = 0.0;   // bassline glide origin
    double glide_pos = 0.0;   // bassline glide progress
    double aux = 0.0;         // per-machine scratch accumulator

    // Sample playback (BeatBox / PCMSynth / Sampler).
    SamplePtr sample;
    double position = 0.0;
    double rate = 1.0;
    float pan = 0.0f;
    float gain = 1.0f;
    float punch = 0.0f;
    double play_end = 1.0;
    std::int64_t stop_at = -1;
    int mute_group = 0;
    int direction = 1;
    std::size_t loop_start = 0;
    std::size_t loop_end = 1;
    std::size_t release_end = 1;
    PcmLoop loop_kind = PcmLoop::None;
    bool intro_loop = false;

    // Sampler: config snapshotted at note-on (loop_start/loop_end hold the
    // crop bounds, `rate` the base pitch-only playback ratio).  The fixed
    // audible span can't be resolved until a RenderContext supplies BPM, so
    // it is cached lazily the first time the voice is rendered.
    SamplerEnvelope smp_vol_env{};
    SamplerEnvelope smp_tone_env{};
    SamplerEnvelope smp_dist_env{};
    SamplerEnvelope smp_pitch_env{};
    float smp_tone = 0.0f;
    float smp_bass = 0.0f;
    float smp_mid = 0.0f;
    float smp_high = 0.0f;
    float smp_dist = 0.0f;
    float smp_pitch = 0.0f;
    double smp_natural_frames = 0.0;  // cropped duration estimate at note-on
    double smp_pattern_beats = 4.0;   // pattern length in beats (measures*4)
    double smp_audible_frames = -1.0; // resolved lazily once BPM is known
    OnePole smp_tilt_lp;
    std::array<Biquad, 3> smp_eq;     // bass shelf, mid peak, high shelf

    // Vocoder carrier.
    int mod_slot = 0;

    // Per-voice filter (SubSynth).
    Biquad filter;

    // Karplus-Strong units.
    std::array<std::vector<float>, 2> ks_buf;
    std::array<std::size_t, 2> ks_idx{{0, 0}};
    std::array<float, 2> ks_lp{{0.0f, 0.0f}};
    std::array<float, 2> ks_feedback{{0.99f, 0.99f}};
    std::array<float, 2> ks_damp{{0.3f, 0.3f}};
    float ks_energy = 1.0f;

    // Additive pad partial phases (A/B detune pair).
    std::array<double, kPadHarmonics> pad_ph_a{};
    std::array<double, kPadHarmonics> pad_ph_b{};

    // FM operator feedback memory.
    std::array<float, 3> fm_fb{};
};

// Playback cursor for a vocoder sample modulator.
struct SampleStream {
    std::string name;
    SamplePtr sample;
    double position = 0.0;
    double rate = 1.0;
    int direction = 1;
    bool pingpong = false;
};

class MachineEngine {
  public:
    MachineEngine(const MachineSpec &spec, double sample_rate, const SampleBank *bank,
                  std::uint64_t seed);

    void update(const MachineSpec &spec, double sample_rate);

    MachineKind kind() const { return spec_.kind; }
    double sample_rate() const { return sample_rate_; }

    void note_on(int note, float vel, int offset, int flags);
    void note_off(int note, int offset);
    void all_off();
    bool active() const;
    // Number of voices that are still alive (dead voices are compacted away
    // after each render).
    int live_voice_count() const;

    // Writes (does not accumulate) `n` frames into the planar l/r buffers.
    void render(float *l, float *r, std::size_t n, const RenderContext &ctx);

    const std::array<float, kVocoderBands> &band_vu() const { return band_vu_; }

  private:
    void reset_runtime();
    void refresh_sample_rate_state();
    std::uint64_t next_serial() { return ++serial_; }
    void compact();
    void trim_poly(int poly);
    Voice &push_voice(int note, float vel, int offset, int flags);

    void render_subsynth(float *l, float *r, std::size_t n);
    void render_pcmsynth(float *l, float *r, std::size_t n);
    void render_sampler(float *l, float *r, std::size_t n, const RenderContext &ctx);
    void render_bassline(float *l, float *r, std::size_t n);
    void render_beatbox(float *l, float *r, std::size_t n);
    void render_padsynth(float *l, float *r, std::size_t n);
    void render_bitsynth(float *l, float *r, std::size_t n);
    void render_modular(float *l, float *r, std::size_t n);
    void render_organ(float *l, float *r, std::size_t n);
    void render_vocoder(float *l, float *r, std::size_t n, const RenderContext &ctx);
    void render_fmsynth(float *l, float *r, std::size_t n);
    void render_kssynth(float *l, float *r, std::size_t n);

    void note_on_beatbox(int note, float vel, int offset, int flags);
    void note_on_pcmsynth(int note, float vel, int offset, int flags);
    void note_on_sampler(int note, float vel, int offset, int flags);
    void note_on_vocoder(int note, float vel, int offset, int flags);
    void note_on_kssynth(Voice &v);

    void ensure_scratch(std::size_t n);
    void fill_lfo(std::vector<float> &dst, std::size_t n, int wave, double rate, double &phase,
                  double phase_offset);
    void vocoder_modulator(std::size_t n, const RenderContext &ctx);
    void modular_prepare();

    MachineSpec spec_{};
    double sample_rate_ = kDefaultSampleRate;
    const SampleBank *bank_ = nullptr;
    std::vector<Voice> voices_;
    std::uint64_t serial_ = 0;
    Rng rng_{1};
    Rng noise_rng_{2};
    std::array<float, kVocoderBands> band_vu_{};

    // Machine-level modulation state.
    double lfo1_phase_ = 0.0;
    double lfo2_phase_ = 0.0;
    double leslie_phase_ = 0.0;
    float dc_x_[2] = {0.0f, 0.0f};
    float dc_y_[2] = {0.0f, 0.0f};

    // Shared scratch buffers (reused between blocks).
    std::vector<float> lfo1_, lfo2_, cutoff_, scratch_a_, scratch_b_, mod_buf_, carrier_buf_;

    // PCMSynth machine filter.
    TVFilter pcm_filter_[2];

    // Vocoder state.
    std::array<Biquad, kVocoderBands> mod_filters_;
    std::array<Biquad, kVocoderBands> car_filters_;
    std::array<OnePole, kVocoderBands> followers_;
    std::vector<SampleStream> streams_;
    int current_mod_slot_ = 0;

    // BitSynth compiled expressions.
    ByteBeatExpr expr_a_;
    ByteBeatExpr expr_b_;

    // Modular runtime graph.
    struct ModularNode {
        ModularKind kind = ModularKind::Invert;
        bool present = false;
        std::array<float, 5> params{};
        std::array<std::vector<int>, 3> sources;  // component indices per input
        std::array<bool, 3> from_note{};          // input fed by panel.note_cv
        std::array<bool, 3> from_velocity{};
        std::array<bool, 3> from_mod_wheel{};
        double phase = 0.0;
        double sh_phase = 0.0;
        float sh_value = 0.0f;
        float svf_lp = 0.0f;
        float svf_bp = 0.0f;
        std::vector<float> delay;
        std::size_t delay_idx = 0;
        float out = 0.0f;
    };
    std::vector<ModularNode> mod_nodes_;
    std::vector<int> mod_left_sources_;
    std::vector<int> mod_right_sources_;
    std::vector<int> mod_volume_sources_;
    bool modular_dirty_ = true;
};

}  // namespace refrag
