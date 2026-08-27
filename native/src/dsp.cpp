#include "dsp.h"

namespace refrag {

BiquadCoeffs biquad_coeffs(FilterType type, double f0, double q, double sample_rate,
                           double gain_db) {
    double sr = sample_rate > 0.0 ? sample_rate : kDefaultSampleRate;
    f0 = clampd(f0, 20.0, sr * 0.49);
    q = std::max(q, 0.05);
    double w0 = kTwoPi * f0 / sr;
    double cw = std::cos(w0);
    double sw = std::sin(w0);
    double alpha = sw / (2.0 * q);
    double A = std::pow(10.0, gain_db / 40.0);
    double b[3] = {1.0, 0.0, 0.0};
    double a[3] = {1.0, 0.0, 0.0};

    switch (type) {
    case FilterType::LowPass:
        b[0] = (1.0 - cw) / 2.0;
        b[1] = 1.0 - cw;
        b[2] = (1.0 - cw) / 2.0;
        a[0] = 1.0 + alpha;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha;
        break;
    case FilterType::HighPass:
        b[0] = (1.0 + cw) / 2.0;
        b[1] = -(1.0 + cw);
        b[2] = (1.0 + cw) / 2.0;
        a[0] = 1.0 + alpha;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha;
        break;
    case FilterType::BandPass:
        b[0] = alpha;
        b[1] = 0.0;
        b[2] = -alpha;
        a[0] = 1.0 + alpha;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha;
        break;
    case FilterType::Notch:
        b[0] = 1.0;
        b[1] = -2.0 * cw;
        b[2] = 1.0;
        a[0] = 1.0 + alpha;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha;
        break;
    case FilterType::Peak:
        b[0] = 1.0 + alpha * A;
        b[1] = -2.0 * cw;
        b[2] = 1.0 - alpha * A;
        a[0] = 1.0 + alpha / A;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha / A;
        break;
    case FilterType::LowShelf: {
        double sqA = std::sqrt(A);
        b[0] = A * ((A + 1.0) - (A - 1.0) * cw + 2.0 * sqA * alpha);
        b[1] = 2.0 * A * ((A - 1.0) - (A + 1.0) * cw);
        b[2] = A * ((A + 1.0) - (A - 1.0) * cw - 2.0 * sqA * alpha);
        a[0] = (A + 1.0) + (A - 1.0) * cw + 2.0 * sqA * alpha;
        a[1] = -2.0 * ((A - 1.0) + (A + 1.0) * cw);
        a[2] = (A + 1.0) + (A - 1.0) * cw - 2.0 * sqA * alpha;
        break;
    }
    case FilterType::HighShelf: {
        double sqA = std::sqrt(A);
        b[0] = A * ((A + 1.0) + (A - 1.0) * cw + 2.0 * sqA * alpha);
        b[1] = -2.0 * A * ((A - 1.0) + (A + 1.0) * cw);
        b[2] = A * ((A + 1.0) + (A - 1.0) * cw - 2.0 * sqA * alpha);
        a[0] = (A + 1.0) - (A - 1.0) * cw + 2.0 * sqA * alpha;
        a[1] = 2.0 * ((A - 1.0) - (A + 1.0) * cw);
        a[2] = (A + 1.0) - (A - 1.0) * cw - 2.0 * sqA * alpha;
        break;
    }
    case FilterType::AllPass:
        b[0] = 1.0 - alpha;
        b[1] = -2.0 * cw;
        b[2] = 1.0 + alpha;
        a[0] = 1.0 + alpha;
        a[1] = -2.0 * cw;
        a[2] = 1.0 - alpha;
        break;
    case FilterType::Bypass:
    default:
        return BiquadCoeffs{1.0, 0.0, 0.0, 0.0, 0.0};
    }

    BiquadCoeffs c;
    double inv = a[0] != 0.0 ? 1.0 / a[0] : 1.0;
    c.b0 = b[0] * inv;
    c.b1 = b[1] * inv;
    c.b2 = b[2] * inv;
    c.a1 = a[1] * inv;
    c.a2 = a[2] * inv;
    return c;
}

}  // namespace refrag
