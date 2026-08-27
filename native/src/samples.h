// Registered mono sample buffers shared by BeatBox, PCMSynth and the Vocoder.
#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace refrag {

struct Sample {
    std::vector<float> data;
    double source_rate = 44100.0;
};

using SamplePtr = std::shared_ptr<const Sample>;

class SampleBank {
  public:
    void set(const std::string &name, std::vector<float> data, double source_rate) {
        auto sample = std::make_shared<Sample>();
        sample->data = std::move(data);
        sample->source_rate = source_rate > 0.0 ? source_rate : 44100.0;
        samples_[name] = std::move(sample);
    }

    SamplePtr get(const std::string &name) const {
        if (name.empty()) {
            return nullptr;
        }
        auto it = samples_.find(name);
        return it == samples_.end() ? nullptr : it->second;
    }

  private:
    std::unordered_map<std::string, SamplePtr> samples_;
};

// Linear interpolation used by every sample-playing machine.
inline float fetch_linear(const std::vector<float> &buf, double pos) {
    const std::size_t n = buf.size();
    if (n == 0) {
        return 0.0f;
    }
    if (n == 1) {
        return buf[0];
    }
    double limit = static_cast<double>(n) - 1.0001;
    if (pos < 0.0) {
        pos = 0.0;
    } else if (pos > limit) {
        pos = limit;
    }
    std::size_t i0 = static_cast<std::size_t>(pos);
    double frac = pos - static_cast<double>(i0);
    std::size_t i1 = i0 + 1 < n ? i0 + 1 : n - 1;
    return static_cast<float>(buf[i0] * (1.0 - frac) + buf[i1] * frac);
}

}  // namespace refrag
