// Whole-room render graph: machines -> inserts -> strip -> sends -> master.
#pragma once

#include <array>
#include <memory>
#include <string>
#include <vector>

#include "effects.h"
#include "machine.h"
#include "mixer.h"
#include "samples.h"
#include "spec.h"
#include "thread_pool.h"

namespace refrag {

struct RoomSlotSpec {
    bool present = false;
    MachineSpec machine;
    std::array<EffectSpec, 2> effects{};
    MixerSpec mixer{};
};

struct RoomSpec {
    int sample_rate = 44100;
    int block_size = 512;
    std::vector<RoomSlotSpec> slots;
    MasterSpec master;
};

class RoomEngine {
  public:
    RoomEngine(int sample_rate, int block_size, int slot_count);

    int sample_rate() const { return sample_rate_; }
    int block_size() const { return block_size_; }
    int slot_count() const { return static_cast<int>(slots_.size()); }

    void register_sample(const std::string &name, std::vector<float> data, double source_rate);

    void sync(const RoomSpec &spec);

    void note_on(int slot, int note, float vel, int offset, int flags);
    void note_off(int slot, int note, int offset);
    void all_off(int slot);

    bool active() const;
    bool has_tail() const { return tail_blocks_ > 0; }

    // Renders the whole graph; out_l/out_r receive `frames` samples each.
    void render(float *out_l, float *out_r, std::size_t frames, double bpm);

    const std::vector<float> &slot_vu() const { return slot_vu_; }
    // Live voice count per slot; empty slots report 0.
    const std::vector<int> &slot_voice_counts() const;
    float master_vu_left() const { return master_vu_[0]; }
    float master_vu_right() const { return master_vu_[1]; }
    float limiter_gr() const { return lim_gr_; }

    // Vocoder band meters keyed by slot index.
    std::vector<std::pair<int, std::array<float, kVocoderBands>>> vocoder_vu() const;

  private:
    struct Slot {
        bool present = false;
        RoomSlotSpec spec;
        std::unique_ptr<MachineEngine> engine;
        MachineKind kind = MachineKind::SubSynth;
        std::array<std::unique_ptr<Effect>, 2> fx{};
        std::array<bool, 2> fx_present{{false, false}};
        std::array<EffectKind, 2> fx_kind{{EffectKind::Distortion, EffectKind::Distortion}};
        ChannelStrip strip;
        std::vector<float> dry_l, dry_r, wet_l, wet_r;
        bool rendered = false;
        // True when prev_l/prev_r hold audio from the previous block; drives
        // whether prev_outputs_ exposes this slot to vocoder lookups.
        bool prev_rendered = false;
        std::vector<float> prev_l, prev_r;
    };

    void reconfigure_audio();
    void ensure_buffers(std::size_t frames);
    // Re-points prev_outputs_ at the (possibly reallocated) per-slot previous
    // block buffers, keeping each slot's "has previous audio" state intact.
    void refresh_prev_pointers();

    int sample_rate_ = 44100;
    int block_size_ = 512;
    std::vector<Slot> slots_;
    MasterSpec master_{};
    MasterSection master_section_;
    SampleBank bank_;
    RenderThreadPool render_pool_;

    std::vector<float> mix_l_, mix_r_;
    std::vector<float> send_delay_l_, send_delay_r_;
    std::vector<float> send_reverb_l_, send_reverb_r_;
    std::vector<MachineAudio> outputs_, prev_outputs_;
    std::vector<float> slot_vu_;
    mutable std::vector<int> slot_voices_;
    float master_vu_[2] = {0.0f, 0.0f};
    float lim_gr_ = 0.0f;
    int tail_blocks_ = 0;
    std::size_t capacity_ = 0;
};

}  // namespace refrag
