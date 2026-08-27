#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <thread>
#include <utility>
#include <vector>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

namespace {

constexpr double kSR = 44100.0;
constexpr double kTwoPi = 6.28318530717958647692;
constexpr std::size_t kMaxBlock = 8192;
constexpr std::size_t kMaxVoices = 64;

enum class MachineKind {
    SubSynth,
    PCMSynth,
    BassLine,
    BeatBox,
    PadSynth,
    BitSynth,
    Modular,
    Organ,
    Vocoder,
    FMSynth,
    KSSynth,
    Unknown,
};

struct Voice {
    int note = 0;
    float vel = 0.0f;
    int flags = 0;
    int t = 0;
    int released_at = -1;
    bool dead = false;
    int start_offset = 0;
    std::uint64_t serial = 0;

    double phase1 = 0.0;
    double phase2 = 0.0;
    double phase3 = 0.0;
    double phase4 = 0.0;
    double note_from = 0.0;
    std::vector<float> ks_buf;
    std::size_t ks_idx = 0;
};

struct MachineParams {
    float volume = 1.0f;
    float pan = 0.0f;
    float attack = 0.01f;
    float decay = 0.12f;
    float sustain = 0.7f;
    float release = 0.18f;
    float detune = 0.01f;
    float mix = 0.5f;
    float drive = 0.0f;
    float cutoff = 0.5f;
    float resonance = 0.3f;
    float leslie_speed = 0.0f;
    float leslie_depth = 0.0f;
    float fm_index = 3.0f;
    float ks_decay = 0.4f;
    int carrier = 0;
    int mod_sel = 0;
    int algorithm = 0;
    float waveform = 0.0f;
};

template <typename T>
T read_num(const py::dict &d, const char *key, T def) {
    py::object v;
    if (d.contains(key)) {
        v = d[key];
    } else {
        v = py::none();
    }
    return v.is_none() ? def : v.cast<T>();
}

float clampf(float x, float lo, float hi) {
    return std::max(lo, std::min(hi, x));
}

double note_freq(double note) {
    return 440.0 * std::pow(2.0, (note - 69.0) / 12.0);
}

float wave_sample(int wave, double phase) {
    double ph = phase - std::floor(phase);
    switch (wave) {
    case 0: return std::sin(kTwoPi * ph);
    case 1: return static_cast<float>(4.0 * std::abs(ph - 0.5) - 1.0);
    case 2:
    case 3: return static_cast<float>(2.0 * ph - 1.0);
    case 4:
    case 5: return ph < 0.5 ? 1.0f : -1.0f;
    case 6: return ph < 0.25 ? 1.0f : -1.0f;
    case 7: return std::max(0.0f, static_cast<float>(std::sin(kTwoPi * ph))) * 2.0f - 1.0f;
    case 8: {
        double x = std::sin((ph + 1.0) * 1234.5678) * 43758.5453;
        return static_cast<float>((x - std::floor(x)) * 2.0 - 1.0);
    }
    default: return 0.0f;
    }
}

double adsr(double t, double a, double d, double s, double r, double released_at) {
    if (t < 0.0) return 0.0;
    if (released_at >= 0.0 && t >= released_at) {
        double x = (t - released_at) / std::max(1.0, r);
        return std::max(0.0, s * (1.0 - x));
    }
    if (a > 1.0 && t < a) return t / a;
    if (d > 1.0 && t < a + d) {
        double f = (t - a) / d;
        return 1.0 + (s - 1.0) * f;
    }
    return s;
}

void zero_stereo(float *out, std::size_t frames) {
    std::fill(out, out + frames * 2, 0.0f);
}

MachineKind kind_from_string(const std::string &s) {
    if (s == "subsynth") return MachineKind::SubSynth;
    if (s == "pcmsynth") return MachineKind::PCMSynth;
    if (s == "bassline") return MachineKind::BassLine;
    if (s == "beatbox") return MachineKind::BeatBox;
    if (s == "padsynth") return MachineKind::PadSynth;
    if (s == "bitsynth") return MachineKind::BitSynth;
    if (s == "modular") return MachineKind::Modular;
    if (s == "organ") return MachineKind::Organ;
    if (s == "vocoder") return MachineKind::Vocoder;
    if (s == "fmsynth") return MachineKind::FMSynth;
    if (s == "kssynth") return MachineKind::KSSynth;
    return MachineKind::Unknown;
}

MachineParams parse_params(const py::dict &m) {
    py::dict p = m["params"].cast<py::dict>();
    MachineParams out;
    out.volume = read_num<float>(p, "volume", 1.0f);
    out.pan = read_num<float>(p, "pan", 0.0f);
    out.attack = std::max(1.0f, read_num<float>(p, "vol_attack", read_num<float>(p, "attack", 0.01f)) * static_cast<float>(kSR));
    out.decay = std::max(1.0f, read_num<float>(p, "vol_decay", read_num<float>(p, "decay", 0.12f)) * static_cast<float>(kSR));
    out.sustain = clampf(read_num<float>(p, "vol_sustain", read_num<float>(p, "sustain", 0.7f)), 0.0f, 1.0f);
    out.release = std::max(1.0f, read_num<float>(p, "vol_release", read_num<float>(p, "release", 0.18f)) * static_cast<float>(kSR));
    out.detune = read_num<float>(p, "detune", 0.01f);
    out.mix = read_num<float>(p, "mix", 0.5f);
    out.drive = read_num<float>(p, "drive", read_num<float>(p, "dist_amount", 0.0f));
    out.cutoff = read_num<float>(p, "cutoff", read_num<float>(p, "flt_cutoff", 0.5f));
    out.resonance = read_num<float>(p, "res", read_num<float>(p, "flt_res", 0.3f));
    out.leslie_speed = read_num<float>(p, "leslie_speed", 0.0f);
    out.leslie_depth = read_num<float>(p, "leslie_depth", 0.0f);
    out.fm_index = read_num<float>(p, "fm_index", 3.0f);
    out.ks_decay = read_num<float>(p, "decay", 0.4f);
    out.carrier = m.contains("carrier") ? m["carrier"].cast<int>() : read_num<int>(p, "carrier", 0);
    out.mod_sel = m.contains("mod_sel") ? m["mod_sel"].cast<int>() : read_num<int>(p, "mod_sel", 0);
    out.algorithm = m.contains("algorithm") ? m["algorithm"].cast<int>() : read_num<int>(p, "algorithm", 0);
    out.waveform = read_num<float>(p, "wave", read_num<float>(p, "osc1_wave", 0.0f));
    return out;
}

struct ThreadPool {
    using JobFn = void (*)(void *, std::size_t, std::size_t, float *, std::size_t);

    struct Slot {
        std::atomic<bool> ready{false};
        std::atomic<bool> done{false};
        JobFn fn = nullptr;
        void *ctx = nullptr;
        std::size_t begin = 0;
        std::size_t end = 0;
        std::size_t frames = 0;
        alignas(64) std::array<float, kMaxBlock * 2> scratch{};
        std::thread thread;
    };

    std::vector<std::unique_ptr<Slot>> slots;
    std::atomic<bool> stopping{false};

    static void wait_for(std::atomic<bool> &flag, bool value) {
#if defined(__cpp_lib_atomic_wait) && __cpp_lib_atomic_wait >= 201907L
        flag.wait(value, std::memory_order_relaxed);
#else
        while (flag.load(std::memory_order_acquire) == value) {
            std::this_thread::yield();
        }
#endif
    }

    explicit ThreadPool(std::size_t count) {
        count = std::max<std::size_t>(1, count);
        slots.reserve(count);
        for (std::size_t i = 0; i < count; ++i) {
            auto slot = std::make_unique<Slot>();
            slot->thread = std::thread([this, i] { worker(i); });
            slots.emplace_back(std::move(slot));
        }
    }

    ~ThreadPool() {
        stopping.store(true, std::memory_order_release);
        for (auto &slot : slots) {
            slot->ready.store(true, std::memory_order_release);
#if defined(__cpp_lib_atomic_wait) && __cpp_lib_atomic_wait >= 201907L
            slot->ready.notify_one();
#endif
        }
        for (auto &slot : slots) {
            if (slot->thread.joinable()) {
                slot->thread.join();
            }
        }
    }

    std::size_t count() const { return slots.size(); }

    float *scratch(std::size_t index) { return slots[index]->scratch.data(); }

    void submit(std::size_t index, JobFn fn, void *ctx, std::size_t begin, std::size_t end, std::size_t frames) {
        auto &slot = *slots[index];
        slot.fn = fn;
        slot.ctx = ctx;
        slot.begin = begin;
        slot.end = end;
        slot.frames = frames;
        slot.done.store(false, std::memory_order_release);
        slot.ready.store(true, std::memory_order_release);
#if defined(__cpp_lib_atomic_wait) && __cpp_lib_atomic_wait >= 201907L
        slot.ready.notify_one();
#endif
    }

    void wait(std::size_t index) {
        wait_for(slots[index]->done, false);
    }

    void worker(std::size_t index) {
        auto &slot = *slots[index];
        for (;;) {
            wait_for(slot.ready, false);
            if (stopping.load(std::memory_order_acquire)) {
                break;
            }
            auto fn = slot.fn;
            if (fn != nullptr) {
                fn(slot.ctx, slot.begin, slot.end, slot.scratch.data(), slot.frames);
            }
            slot.ready.store(false, std::memory_order_release);
            slot.done.store(true, std::memory_order_release);
#if defined(__cpp_lib_atomic_wait) && __cpp_lib_atomic_wait >= 201907L
            slot.done.notify_one();
#endif
        }
    }
};

ThreadPool &pool() {
    static ThreadPool instance(std::max<unsigned>(1, std::thread::hardware_concurrency() ? std::thread::hardware_concurrency() - 1 : 1));
    return instance;
}

struct RowRenderContext {
    const float *rows = nullptr;
    std::size_t row_stride = 0;
    std::size_t col_count = 0;
    bool planar = false;
};

class MachineEngine;

struct MachineRenderContext {
    MachineEngine *engine = nullptr;
    MachineParams params;
    std::array<Voice *, kMaxVoices> active{};
    std::size_t active_count = 0;
};

void render_rows(void *ctx_ptr, std::size_t begin, std::size_t end, float *out, std::size_t frames) {
    auto *ctx = static_cast<RowRenderContext *>(ctx_ptr);
    zero_stereo(out, frames);
    for (std::size_t row = begin; row < end; ++row) {
        const float *r = ctx->rows + row * ctx->row_stride;
        double note = r[0];
        double vel = r[1];
        int wave = static_cast<int>(r[2]);
        float pan = clampf(r[3], -1.0f, 1.0f);
        double attack = std::max(1.0, r[4] * kSR);
        double decay = std::max(1.0, r[5] * kSR);
        double sustain = clampf(r[6], 0.0f, 1.0f);
        double release = std::max(1.0, r[7] * kSR);
        double phase = r[8];
        double freq = note_freq(note);
        for (std::size_t i = 0; i < frames; ++i) {
            double env = adsr(static_cast<double>(i), attack, decay, sustain, release, -1.0);
            phase += freq / kSR;
            float s = wave_sample(wave, phase) * static_cast<float>(env * vel);
            if (ctx->planar) {
                out[i] += s * (1.0f - pan) * 0.5f;
                out[frames + i] += s * (1.0f + pan) * 0.5f;
            } else {
                out[i * 2] += s * (1.0f - pan) * 0.5f;
                out[i * 2 + 1] += s * (1.0f + pan) * 0.5f;
            }
        }
    }
}

class MachineEngine : public std::enable_shared_from_this<MachineEngine> {
  public:
    explicit MachineEngine(py::dict m) { update(std::move(m)); }

    void update(py::dict m) {
        machine_ = std::move(m);
        kind_ = kind_from_string(std::string(py::str(machine_["type"])));
        params_ = parse_params(machine_);
        poly_ = machine_.contains("poly") ? machine_["poly"].cast<int>() : 8;
        poly_ = std::max(1, std::min<int>(poly_, static_cast<int>(kMaxVoices)));
    }

    void note_on(int note, float vel, int offset = 0, int flags = 0) {
        if (kind_ == MachineKind::BassLine) {
            for (auto &v : voices_) {
                v.dead = true;
            }
            compact();
        }
        Voice v;
        v.note = note;
        v.vel = vel;
        v.flags = flags;
        v.start_offset = std::max(0, offset);
        v.serial = ++serial_;
        v.note_from = voices_.empty() ? note : voices_.back().note;
        if (kind_ == MachineKind::KSSynth) {
            init_ks(v, note, vel);
        }
        if (voices_.size() >= static_cast<std::size_t>(poly_)) {
            auto it = std::min_element(voices_.begin(), voices_.end(), [](const Voice &a, const Voice &b) { return a.serial < b.serial; });
            if (it != voices_.end()) {
                it->dead = true;
            }
            compact();
        }
        voices_.push_back(std::move(v));
    }

    void note_off(int note, int offset = 0) {
        for (auto &v : voices_) {
            if (!v.dead && v.note == note && v.released_at < 0) {
                v.released_at = v.t + std::max(0, offset);
            }
        }
    }

    void all_off() {
        for (auto &v : voices_) {
            if (v.released_at < 0) {
                v.released_at = v.t;
            }
        }
    }

    void kill_all() { voices_.clear(); }

    bool active() const {
        return std::any_of(voices_.begin(), voices_.end(), [](const Voice &v) { return !v.dead; });
    }

    py::array_t<float> render(std::size_t frames, py::object) {
        py::array_t<float> raw(2 * frames);
        render_into(raw.mutable_data(), frames);
        py::array_t<float> out(std::vector<py::ssize_t>{2, static_cast<py::ssize_t>(frames)});
        float *dst = out.mutable_data();
        const float *src = raw.data();
        for (std::size_t i = 0; i < frames; ++i) {
            dst[i] = src[i * 2];
            dst[frames + i] = src[i * 2 + 1];
        }
        return out;
    }

    void render_into(float *out, std::size_t frames) {
        std::size_t cursor = 0;
        while (cursor < frames) {
            std::size_t chunk = std::min<std::size_t>(kMaxBlock, frames - cursor);
            zero_stereo(out + cursor * 2, chunk);
            render_chunk(out + cursor * 2, chunk);
            cursor += chunk;
        }
    }

    py::list voices_snapshot() const {
        py::list out;
        for (const auto &v : voices_) {
            out.append(v);
        }
        return out;
    }

    py::list band_vu_snapshot() const {
        py::list out;
        for (float v : band_vu_) {
            out.append(v);
        }
        return out;
    }

  private:
    py::dict machine_;
    MachineParams params_;
    MachineKind kind_ = MachineKind::Unknown;
    int poly_ = 8;
    std::uint64_t serial_ = 0;
    std::vector<Voice> voices_;
    std::array<float, 8> band_vu_{};

    void compact() {
        voices_.erase(std::remove_if(voices_.begin(), voices_.end(), [](const Voice &v) { return v.dead; }), voices_.end());
    }

    void init_ks(Voice &v, int note, float vel) {
        double freq = std::max(20.0, note_freq(note));
        std::size_t len = std::max<std::size_t>(4, static_cast<std::size_t>(kSR / freq));
        v.ks_buf.resize(len);
        for (std::size_t i = 0; i < len; ++i) {
            double seed = std::sin((i + 1) * 12.9898 + note * 78.233);
            v.ks_buf[i] = static_cast<float>((seed - std::floor(seed)) * 2.0 - 1.0) * vel;
        }
    }

    static float envelope_of(const Voice &v, const MachineParams &p, double t) {
        double rel = v.released_at >= 0 ? static_cast<double>(v.released_at - v.start_offset) : -1.0;
        return static_cast<float>(adsr(t, p.attack, p.decay, p.sustain, p.release, rel));
    }

    static void mix_sample(float *out, std::size_t i, float s, float gain, float pan) {
        out[i * 2] += s * gain * (1.0f - pan) * 0.5f;
        out[i * 2 + 1] += s * gain * (1.0f + pan) * 0.5f;
    }

    static void render_subsynth(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph1 = v.phase1;
        double ph2 = v.phase2;
        double f1 = note_freq(v.note);
        double f2 = note_freq(v.note + 12.0 * p.detune);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            if (env <= 0.0f) continue;
            ph1 += f1 / kSR;
            ph2 += f2 / kSR;
            float s = 0.6f * wave_sample(static_cast<int>(p.waveform) % 4, ph1) + 0.4f * wave_sample(0, ph2);
            s = static_cast<float>(std::tanh(s * (1.0f + p.drive * 3.0f)));
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph1;
        v.phase2 = ph2;
        v.t += static_cast<int>(frames);
    }

    static void render_bassline(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph = v.phase1;
        double start = v.note_from;
        double note = v.note;
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            double glide = std::min(1.0, lt / (0.06 * kSR));
            double pitch = start + (note - start) * glide;
            ph += note_freq(pitch) / kSR;
            float env = static_cast<float>(std::exp(-lt / (0.35 * kSR + 1.0)));
            float s = static_cast<float>(std::tanh(wave_sample(2, ph) * (1.0f + p.drive * 4.0f)));
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph;
        v.t += static_cast<int>(frames);
    }

    static void render_pad(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph1 = v.phase1;
        double ph2 = v.phase2;
        double f = note_freq(v.note);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            ph1 += f * (1.0 - p.detune * 0.5) / kSR;
            ph2 += f * (1.0 + p.detune * 0.5) / kSR;
            float s = 0.5f * wave_sample(0, ph1) + 0.5f * wave_sample(1, ph2);
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph1;
        v.phase2 = ph2;
        v.t += static_cast<int>(frames);
    }

    static void render_bit(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph = v.phase1;
        double f = note_freq(v.note);
        float crush = 4.0f + p.drive * 24.0f;
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            ph += f / kSR;
            float s = wave_sample(2, ph);
            s = std::round(s * crush) / crush;
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph;
        v.t += static_cast<int>(frames);
    }

    static void render_organ(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        static constexpr std::array<double, 6> ratios = {0.5, 1.0, 1.5, 2.0, 3.0, 4.0};
        static constexpr std::array<float, 6> levels = {0.8f, 0.7f, 0.45f, 0.4f, 0.25f, 0.2f};
        std::array<double, 6> phase = {v.phase1, v.phase2, v.phase3, v.phase4, v.phase1 + 0.1, v.phase2 + 0.1};
        double f = note_freq(v.note);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            float s = 0.0f;
            for (std::size_t h = 0; h < ratios.size(); ++h) {
                phase[h] += f * ratios[h] / kSR;
                s += levels[h] * wave_sample(0, phase[h]);
            }
            float trem = 1.0f - p.leslie_depth * 0.2f;
            mix_sample(out, i, s * trem, env * v.vel, 0.0f);
        }
        v.phase1 = phase[0];
        v.phase2 = phase[1];
        v.phase3 = phase[2];
        v.phase4 = phase[3];
        v.t += static_cast<int>(frames);
    }

    static void render_fm(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph1 = v.phase1, ph2 = v.phase2, ph3 = v.phase3;
        double f = note_freq(v.note);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            ph1 += f / kSR;
            ph2 += f * 2.0 / kSR;
            ph3 += f * 3.0 / kSR;
            float m = wave_sample(0, ph1) * p.fm_index;
            float s = wave_sample(0, ph2 + m);
            s = wave_sample(0, ph3 + s * 0.6f);
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph1;
        v.phase2 = ph2;
        v.phase3 = ph3;
        v.t += static_cast<int>(frames);
    }

    static void render_pcm(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph = v.phase1;
        double f = note_freq(v.note);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            ph += f / kSR;
            float s = 0.7f * wave_sample(0, ph) + 0.3f * wave_sample(8, ph * 4.0);
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph;
        v.t += static_cast<int>(frames);
    }

    static void render_beatbox(const MachineParams &, Voice &v, float *out, std::size_t frames) {
        double ph = v.phase1;
        double f = 70.0 + (v.note % 8) * 30.0;
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = static_cast<float>(std::exp(-lt / (0.08 * kSR + 1.0)));
            ph += f / kSR;
            float s = 0.8f * wave_sample(0, ph) + 0.2f * wave_sample(8, ph * 7.0);
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph;
        v.t += static_cast<int>(frames);
        if (v.t > static_cast<int>(kSR * 0.5)) {
            v.dead = true;
        }
    }

    static void render_vocoder(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        double ph = v.phase1;
        double f = note_freq(v.note);
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            ph += f / kSR;
            float carrier = wave_sample(0, ph);
            float mod = std::abs(wave_sample(8, ph * 5.0));
            float s = carrier * (0.45f + 0.55f * mod);
            mix_sample(out, i, s, env * v.vel, 0.0f);
        }
        v.phase1 = ph;
        v.t += static_cast<int>(frames);
    }

    static void render_ks(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        if (v.ks_buf.empty()) {
            std::size_t len = std::max<std::size_t>(4, static_cast<std::size_t>(kSR / std::max(20.0, note_freq(v.note))));
            v.ks_buf.resize(len);
            for (std::size_t i = 0; i < len; ++i) {
                double seed = std::sin((i + 1) * 12.9898 + v.note * 78.233);
                v.ks_buf[i] = static_cast<float>((seed - std::floor(seed)) * 2.0 - 1.0) * v.vel;
            }
        }
        for (std::size_t i = 0; i < frames; ++i) {
            int t = v.t + static_cast<int>(i);
            if (t < v.start_offset) continue;
            double lt = t - v.start_offset;
            float env = envelope_of(v, p, lt);
            std::size_t idx = v.ks_idx;
            std::size_t next = (idx + 1) % v.ks_buf.size();
            float y = 0.996f * 0.5f * (v.ks_buf[idx] + v.ks_buf[next]);
            v.ks_buf[idx] = y;
            v.ks_idx = next;
            mix_sample(out, i, y, env * v.vel, 0.0f);
        }
        v.t += static_cast<int>(frames);
        if (v.released_at >= 0 && v.t > v.released_at + static_cast<int>((0.1f + p.ks_decay) * kSR)) {
            v.dead = true;
        }
    }

    void render_voice(const MachineParams &p, Voice &v, float *out, std::size_t frames) {
        switch (kind_) {
        case MachineKind::SubSynth:
        case MachineKind::Modular:
            render_subsynth(p, v, out, frames);
            break;
        case MachineKind::PCMSynth:
            render_pcm(p, v, out, frames);
            break;
        case MachineKind::BassLine:
            render_bassline(p, v, out, frames);
            break;
        case MachineKind::BeatBox:
            render_beatbox(p, v, out, frames);
            break;
        case MachineKind::PadSynth:
            render_pad(p, v, out, frames);
            break;
        case MachineKind::BitSynth:
            render_bit(p, v, out, frames);
            break;
        case MachineKind::Organ:
            render_organ(p, v, out, frames);
            break;
        case MachineKind::Vocoder:
            render_vocoder(p, v, out, frames);
            break;
        case MachineKind::FMSynth:
            render_fm(p, v, out, frames);
            break;
        case MachineKind::KSSynth:
            render_ks(p, v, out, frames);
            break;
        default:
            render_pcm(p, v, out, frames);
            break;
        }
        if (v.released_at >= 0 && v.t > v.released_at + static_cast<int>(p.release * 1.5f)) {
            v.dead = true;
        }
    }

    static void voice_job(void *ctx_ptr, std::size_t begin, std::size_t end, float *scratch, std::size_t frames) {
        auto *ctx = static_cast<MachineRenderContext *>(ctx_ptr);
        zero_stereo(scratch, frames);
        for (std::size_t i = begin; i < end; ++i) {
            ctx->engine->render_voice(ctx->params, *ctx->active[i], scratch, frames);
        }
    }

    void render_chunk(float *out, std::size_t frames) {
        std::array<Voice *, kMaxVoices> active{};
        std::size_t active_count = 0;
        for (auto &v : voices_) {
            if (!v.dead) {
                active[active_count++] = &v;
            }
        }
        if (active_count == 0) {
            return;
        }

        MachineRenderContext ctx;
        ctx.engine = this;
        ctx.params = params_;
        for (std::size_t i = 0; i < active_count; ++i) {
            ctx.active[i] = active[i];
        }
        ctx.active_count = active_count;

        voice_job(&ctx, 0, active_count, out, frames);

        compact();
        float peak = 0.0f;
        for (std::size_t i = 0; i < frames * 2; ++i) {
            peak = std::max(peak, std::abs(out[i]));
        }
        band_vu_.fill(clampf(peak, 0.0f, 1.0f));
    }
};

void render_block_impl(py::array_t<float, py::array::c_style | py::array::forcecast> output_buffer, py::array_t<float> param_matrix) {
    auto out = output_buffer.request();
    auto params = param_matrix.request();
    if (params.ndim != 2) {
        throw std::runtime_error("param_matrix must be 2D");
    }
    if (out.ndim != 2 && out.ndim != 1) {
        throw std::runtime_error("output_buffer must be 1D interleaved or 2D stereo");
    }
    std::size_t frames = 0;
    float *out_ptr = static_cast<float *>(out.ptr);
    if (out.ndim == 2) {
        if (out.shape[0] != 2) {
            throw std::runtime_error("output_buffer must have shape (2, n)");
        }
        frames = static_cast<std::size_t>(out.shape[1]);
    } else {
        if (out.shape[0] % 2 != 0) {
            throw std::runtime_error("interleaved output must have an even length");
        }
        frames = static_cast<std::size_t>(out.shape[0] / 2);
    }
    zero_stereo(out_ptr, frames);
    if (params.shape[1] < 9) {
        throw std::runtime_error("param_matrix needs at least 9 columns");
    }
    std::size_t rows = static_cast<std::size_t>(params.shape[0]);
    if (rows == 0) {
        return;
    }

    RowRenderContext ctx;
    ctx.rows = static_cast<const float *>(params.ptr);
    ctx.row_stride = static_cast<std::size_t>(params.shape[1]);
    ctx.col_count = static_cast<std::size_t>(params.shape[1]);
    ctx.planar = (out.ndim == 2);

    render_rows(&ctx, 0, rows, out_ptr, frames);
}

}  // namespace

PYBIND11_MODULE(refrag_engine, m) {
    m.doc() = "Refrag native audio engine";

    py::class_<Voice>(m, "Voice")
        .def(py::init<>())
        .def_readwrite("note", &Voice::note)
        .def_readwrite("vel", &Voice::vel)
        .def_readwrite("flags", &Voice::flags)
        .def_readwrite("t", &Voice::t)
        .def_readwrite("released_at", &Voice::released_at)
        .def_readwrite("dead", &Voice::dead)
        .def_readwrite("start_offset", &Voice::start_offset)
        .def_readwrite("serial", &Voice::serial);

    py::class_<MachineEngine, std::shared_ptr<MachineEngine>>(m, "MachineEngine")
        .def("update", &MachineEngine::update)
        .def("note_on", &MachineEngine::note_on, py::arg("note"), py::arg("vel"), py::arg("offset") = 0, py::arg("flags") = 0)
        .def("note_off", &MachineEngine::note_off, py::arg("note"), py::arg("offset") = 0)
        .def("all_off", &MachineEngine::all_off)
        .def("kill_all", &MachineEngine::kill_all)
        .def("active", &MachineEngine::active)
        .def("render", &MachineEngine::render, py::arg("n"), py::arg("ctx") = py::none())
        .def_property_readonly("voices", &MachineEngine::voices_snapshot)
        .def_property_readonly("band_vu", &MachineEngine::band_vu_snapshot);

    m.def("create_machine", [](py::dict m) { return std::make_shared<MachineEngine>(std::move(m)); });
    m.def("render_block", &render_block_impl, py::arg("output_buffer"), py::arg("param_matrix"));
    m.def("initialize", [](py::object) {});
}
