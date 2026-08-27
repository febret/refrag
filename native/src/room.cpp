#include "room.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace refrag {

namespace {

inline void ensure_size(std::vector<float> &v, std::size_t n) {
    if (v.size() < n) {
        v.resize(n, 0.0f);
    }
}

}  // namespace

RoomEngine::RoomEngine(int sample_rate, int block_size, int slot_count)
    : render_pool_(slot_count) {
    if (sample_rate <= 0) {
        throw std::invalid_argument("sample_rate must be positive");
    }
    if (block_size <= 0) {
        throw std::invalid_argument("block_size must be positive");
    }
    if (slot_count <= 0) {
        throw std::invalid_argument("slot_count must be positive");
    }
    sample_rate_ = sample_rate;
    block_size_ = block_size;
    slots_.resize(static_cast<std::size_t>(slot_count));
    slot_vu_.assign(static_cast<std::size_t>(slot_count), 0.0f);
    outputs_.assign(static_cast<std::size_t>(slot_count), MachineAudio{});
    prev_outputs_.assign(static_cast<std::size_t>(slot_count), MachineAudio{});
    reconfigure_audio();
    ensure_buffers(static_cast<std::size_t>(block_size));
}

void RoomEngine::reconfigure_audio() {
    master_section_.configure(static_cast<double>(sample_rate_),
                              static_cast<std::size_t>(block_size_));
    master_section_.sync_effects(master_, 0x9E37u);
    for (auto &slot : slots_) {
        slot.strip.configure(static_cast<double>(sample_rate_),
                             static_cast<std::size_t>(block_size_));
        for (int i = 0; i < 2; ++i) {
            slot.fx[i].reset();
            slot.fx_present[i] = false;
        }
        if (slot.engine) {
            slot.engine->update(slot.spec.machine, static_cast<double>(sample_rate_));
        }
    }
}

void RoomEngine::refresh_prev_pointers() {
    if (prev_outputs_.size() != slots_.size()) {
        prev_outputs_.resize(slots_.size(), MachineAudio{});
    }
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        if (slot.prev_rendered && !slot.prev_l.empty() && !slot.prev_r.empty()) {
            prev_outputs_[i].l = slot.prev_l.data();
            prev_outputs_[i].r = slot.prev_r.data();
        } else {
            prev_outputs_[i] = MachineAudio{};
        }
    }
}

void RoomEngine::ensure_buffers(std::size_t frames) {
    if (frames <= capacity_) {
        return;
    }
    capacity_ = frames;
    ensure_size(mix_l_, frames);
    ensure_size(mix_r_, frames);
    ensure_size(send_delay_l_, frames);
    ensure_size(send_delay_r_, frames);
    ensure_size(send_reverb_l_, frames);
    ensure_size(send_reverb_r_, frames);
    for (auto &slot : slots_) {
        ensure_size(slot.dry_l, frames);
        ensure_size(slot.dry_r, frames);
        ensure_size(slot.wet_l, frames);
        ensure_size(slot.wet_r, frames);
        ensure_size(slot.prev_l, frames);
        ensure_size(slot.prev_r, frames);
    }
    // Growing the previous-block buffers reallocates them, so every cached
    // pointer handed to the vocoder's previous-block route is now stale.
    refresh_prev_pointers();
}

void RoomEngine::register_sample(const std::string &name, std::vector<float> data,
                                 double source_rate) {
    if (name.empty()) {
        throw std::invalid_argument("sample name must not be empty");
    }
    bank_.set(name, std::move(data), source_rate);
}

void RoomEngine::sync(const RoomSpec &spec) {
    bool audio_changed =
        spec.sample_rate != sample_rate_ || spec.block_size != block_size_;
    if (spec.sample_rate > 0) {
        sample_rate_ = spec.sample_rate;
    }
    if (spec.block_size > 0) {
        block_size_ = spec.block_size;
    }
    if (spec.slots.size() > slots_.size()) {
        std::size_t old = slots_.size();
        slots_.resize(spec.slots.size());
        slot_vu_.resize(spec.slots.size(), 0.0f);
        outputs_.resize(spec.slots.size(), MachineAudio{});
        prev_outputs_.resize(spec.slots.size(), MachineAudio{});
        for (std::size_t i = old; i < slots_.size(); ++i) {
            slots_[i].strip.configure(static_cast<double>(sample_rate_),
                                      static_cast<std::size_t>(block_size_));
        }
        std::size_t frames = capacity_;
        capacity_ = 0;
        ensure_buffers(std::max<std::size_t>(frames, static_cast<std::size_t>(block_size_)));
    }
    master_ = spec.master;
    if (audio_changed) {
        reconfigure_audio();
        std::size_t frames = capacity_;
        capacity_ = 0;
        ensure_buffers(std::max<std::size_t>(frames, static_cast<std::size_t>(block_size_)));
    }
    master_section_.sync_effects(master_, 0x9E37u);

    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        const RoomSlotSpec *incoming = i < spec.slots.size() ? &spec.slots[i] : nullptr;
        if (incoming == nullptr || !incoming->present) {
            slot.present = false;
            slot.engine.reset();
            for (int k = 0; k < 2; ++k) {
                slot.fx[k].reset();
                slot.fx_present[k] = false;
            }
            slot_vu_[i] = 0.0f;
            continue;
        }
        slot.spec = *incoming;
        slot.present = true;
        if (!slot.engine || slot.kind != incoming->machine.kind) {
            slot.engine = std::make_unique<MachineEngine>(
                incoming->machine, static_cast<double>(sample_rate_), &bank_,
                static_cast<std::uint64_t>(i) + 1u);
            slot.kind = incoming->machine.kind;
        } else {
            slot.engine->update(incoming->machine, static_cast<double>(sample_rate_));
        }
        for (int k = 0; k < 2; ++k) {
            const EffectSpec &st = incoming->effects[k];
            if (!st.present) {
                slot.fx[k].reset();
                slot.fx_present[k] = false;
                continue;
            }
            if (!slot.fx_present[k] || slot.fx_kind[k] != st.kind || !slot.fx[k]) {
                slot.fx[k] = create_effect(st.kind, static_cast<double>(sample_rate_),
                                           static_cast<std::uint64_t>(i * 7 + k + 3));
                slot.fx_kind[k] = st.kind;
                slot.fx_present[k] = true;
            }
        }
    }
}

void RoomEngine::note_on(int slot, int note, float vel, int offset, int flags) {
    if (slot < 0 || slot >= static_cast<int>(slots_.size())) {
        throw std::out_of_range("slot index out of range");
    }
    Slot &s = slots_[slot];
    if (!s.present || !s.engine) {
        return;
    }
    s.engine->note_on(note, vel, offset, flags);
}

void RoomEngine::note_off(int slot, int note, int offset) {
    if (slot < 0 || slot >= static_cast<int>(slots_.size())) {
        throw std::out_of_range("slot index out of range");
    }
    Slot &s = slots_[slot];
    if (!s.present || !s.engine) {
        return;
    }
    s.engine->note_off(note, offset);
}

void RoomEngine::all_off(int slot) {
    if (slot >= static_cast<int>(slots_.size())) {
        throw std::out_of_range("slot index out of range");
    }
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        if (slot >= 0 && static_cast<int>(i) != slot) {
            continue;
        }
        if (slots_[i].engine) {
            slots_[i].engine->all_off();
        }
    }
}

bool RoomEngine::active() const {
    if (tail_blocks_ > 0) {
        return true;
    }
    for (const auto &slot : slots_) {
        if (slot.present && slot.engine && slot.engine->active()) {
            return true;
        }
    }
    return false;
}

const std::vector<int> &RoomEngine::slot_voice_counts() const {
    slot_voices_.assign(slots_.size(), 0);
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        const Slot &slot = slots_[i];
        if (slot.present && slot.engine) {
            slot_voices_[i] = slot.engine->live_voice_count();
        }
    }
    return slot_voices_;
}

std::vector<std::pair<int, std::array<float, kVocoderBands>>> RoomEngine::vocoder_vu() const {
    std::vector<std::pair<int, std::array<float, kVocoderBands>>> out;
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        const Slot &slot = slots_[i];
        if (slot.present && slot.engine && slot.engine->kind() == MachineKind::Vocoder) {
            out.emplace_back(static_cast<int>(i), slot.engine->band_vu());
        }
    }
    return out;
}

void RoomEngine::render(float *out_l, float *out_r, std::size_t frames, double bpm) {
    ensure_buffers(frames);
    if (frames == 0) {
        return;
    }
    std::fill(mix_l_.begin(), mix_l_.begin() + frames, 0.0f);
    std::fill(mix_r_.begin(), mix_r_.begin() + frames, 0.0f);
    std::fill(send_delay_l_.begin(), send_delay_l_.begin() + frames, 0.0f);
    std::fill(send_delay_r_.begin(), send_delay_r_.begin() + frames, 0.0f);
    std::fill(send_reverb_l_.begin(), send_reverb_l_.begin() + frames, 0.0f);
    std::fill(send_reverb_r_.begin(), send_reverb_r_.begin() + frames, 0.0f);

    bool any_solo = false;
    for (const auto &slot : slots_) {
        if (slot.present && slot.spec.machine.solo) {
            any_solo = true;
            break;
        }
    }

    for (auto &audio : outputs_) {
        audio = MachineAudio{};
    }
    RenderContext ctx;
    ctx.outputs = outputs_.data();
    ctx.prev_outputs = prev_outputs_.data();
    ctx.slot_count = static_cast<int>(slots_.size());
    ctx.bpm = bpm;

    // Machine synthesis is the largest independent part of a room block. Render
    // every non-vocoder slot through the persistent pool; each task owns one
    // MachineEngine and one pair of dry buffers.
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        slot.rendered = false;
        if (!slot.present || !slot.engine) {
            slot_vu_[i] = 0.0f;
            continue;
        }
        if (slot.kind != MachineKind::Vocoder) {
            outputs_[i].l = slot.dry_l.data();
            outputs_[i].r = slot.dry_r.data();
        }
    }
    render_pool_.parallel_for(slots_.size(), [this, frames, &ctx](std::size_t i) {
        Slot &slot = slots_[i];
        if (!slot.present || !slot.engine || slot.kind == MachineKind::Vocoder) {
            return;
        }
        slot.engine->render(slot.dry_l.data(), slot.dry_r.data(), frames, ctx);
        slot.rendered = true;
    });

    // Vocoders can consume earlier slots from the current block. Render them in
    // rack order and hide later outputs so their previous-block fallback keeps
    // the same deterministic semantics as the original serial graph.
    std::vector<MachineAudio> visible_outputs(outputs_.size());
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        if (!slot.present || !slot.engine || slot.kind != MachineKind::Vocoder) {
            continue;
        }
        std::copy(outputs_.begin(), outputs_.end(), visible_outputs.begin());
        for (std::size_t later = i; later < visible_outputs.size(); ++later) {
            visible_outputs[later] = MachineAudio{};
        }
        RenderContext vocoder_ctx = ctx;
        vocoder_ctx.outputs = visible_outputs.data();
        slot.engine->render(
            slot.dry_l.data(), slot.dry_r.data(), frames, vocoder_ctx);
        outputs_[i].l = slot.dry_l.data();
        outputs_[i].r = slot.dry_r.data();
        slot.rendered = true;
    }

    SidechainLines lines;
    EffectContext fx_ctx;
    fx_ctx.bpm = bpm;
    fx_ctx.lines = &lines;

    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        if (!slot.rendered) {
            continue;
        }

        std::copy(slot.dry_l.begin(), slot.dry_l.begin() + frames, slot.wet_l.begin());
        std::copy(slot.dry_r.begin(), slot.dry_r.begin() + frames, slot.wet_r.begin());

        for (int k = 0; k < 2; ++k) {
            const EffectSpec &st = slot.spec.effects[k];
            if (st.present && !st.bypass && slot.fx_present[k] && slot.fx[k]) {
                slot.fx[k]->process(slot.wet_l.data(), slot.wet_r.data(), frames, st, fx_ctx);
            }
        }

        const MixerSpec &mx = slot.spec.mixer;
        slot.strip.process(slot.wet_l.data(), slot.wet_r.data(), frames, mx);

        if (i < SidechainLines::kMax) {
            lines.l[i] = slot.wet_l.data();
            lines.r[i] = slot.wet_r.data();
        }

        float vu = 0.0f;
        for (std::size_t f = 0; f < frames; ++f) {
            vu = std::max(vu, std::max(std::fabs(slot.wet_l[f]), std::fabs(slot.wet_r[f])));
        }
        slot_vu_[i] = std::isfinite(vu) ? vu : 0.0f;

        bool muted = slot.spec.machine.mute || (any_solo && !slot.spec.machine.solo);
        if (muted) {
            continue;
        }
        float vol = mx.volume;
        for (std::size_t f = 0; f < frames; ++f) {
            float sl = slot.wet_l[f] * vol;
            float sr = slot.wet_r[f] * vol;
            mix_l_[f] += sl;
            mix_r_[f] += sr;
            if (mx.send_delay > 0.0f) {
                send_delay_l_[f] += sl * mx.send_delay;
                send_delay_r_[f] += sr * mx.send_delay;
            }
            if (mx.send_reverb > 0.0f) {
                send_reverb_l_[f] += sl * mx.send_reverb;
                send_reverb_r_[f] += sr * mx.send_reverb;
            }
        }
    }

    // Keep this block's dry outputs available to the next one.
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        Slot &slot = slots_[i];
        slot.prev_rendered = slot.rendered;
        if (slot.rendered) {
            std::copy(slot.dry_l.begin(), slot.dry_l.begin() + frames, slot.prev_l.begin());
            std::copy(slot.dry_r.begin(), slot.dry_r.begin() + frames, slot.prev_r.begin());
        }
    }
    refresh_prev_pointers();

    float peak = 0.0f;
    for (std::size_t f = 0; f < frames; ++f) {
        peak = std::max(peak, std::fabs(mix_l_[f]));
        peak = std::max(peak, std::fabs(mix_r_[f]));
        peak = std::max(peak, std::fabs(send_delay_l_[f]));
        peak = std::max(peak, std::fabs(send_delay_r_[f]));
        peak = std::max(peak, std::fabs(send_reverb_l_[f]));
        peak = std::max(peak, std::fabs(send_reverb_r_[f]));
    }
    if (peak > 1e-6f) {
        tail_blocks_ = static_cast<int>(8.0 * sample_rate_ / std::max(1, block_size_));
    } else if (tail_blocks_ > 0) {
        --tail_blocks_;
    }

    master_section_.process(mix_l_.data(), mix_r_.data(), send_delay_l_.data(),
                            send_delay_r_.data(), send_reverb_l_.data(), send_reverb_r_.data(),
                            frames, master_, bpm);
    if (master_.lim_bypass) {
        lim_gr_ = master_section_.limiter_gr();
    }

    float vu_l = 0.0f;
    float vu_r = 0.0f;
    for (std::size_t f = 0; f < frames; ++f) {
        float sl = mix_l_[f];
        float sr = mix_r_[f];
        if (!std::isfinite(sl)) {
            sl = 0.0f;
        }
        if (!std::isfinite(sr)) {
            sr = 0.0f;
        }
        vu_l = std::max(vu_l, std::fabs(sl));
        vu_r = std::max(vu_r, std::fabs(sr));
        out_l[f] = clampf(sl, -1.5f, 1.5f);
        out_r[f] = clampf(sr, -1.5f, 1.5f);
    }
    master_vu_[0] = vu_l;
    master_vu_[1] = vu_r;
}

}  // namespace refrag
