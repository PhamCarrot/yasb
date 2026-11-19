// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#pragma once
#include "biquad.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>

namespace yasb::dsp {
constexpr unsigned analysis_size = 16384, analysis_hop = 8192, analysis_bands = 27, adaptive_filters = 17, fit_points = 54;
inline double band_frequency(unsigned band) noexcept { return 1000 * std::exp2((double(band) - 14) / 3); }
inline double adaptive_frequency(unsigned band) noexcept { return 1000 * std::exp2((double(band) - 8) / 2); }
inline double correction_weight(double frequency) noexcept {
    if (frequency <= 50 || frequency >= 16000) return 0;
    if (frequency < 100) return .5 - .5 * std::cos(pi * std::log2(frequency / 50));
    if (frequency <= 10000) return 1;
    return .5 + .5 * std::cos(pi * std::log(frequency / 10000) / std::log(1.6));
}
inline double bass_preference(double frequency) noexcept {
    if (frequency <= 80) return 1;
    if (frequency >= 250) return 0;
    return .5 + .5 * std::cos(pi * std::log(frequency / 80) / std::log(250.0 / 80));
}
inline double shaped_correction(double deviation) noexcept {
    const double raw = -.5 * deviation * deviation * deviation / (deviation * deviation + 6.25);
    const double bound = raw < 0 ? 6 : 3;
    return bound * std::tanh(raw / bound);
}
struct Observation {
    std::array<double, analysis_bands> power{};
    double total = 0;
};

class Spectrum {
    std::array<float, analysis_size> left_{}, right_{}, window_{};
    std::array<std::complex<double>, analysis_size> fft_{};
    std::array<std::complex<double>, analysis_size / 2> twiddles_{};
    std::array<unsigned short, analysis_size> reverse_{};
    std::array<unsigned, analysis_bands> lower_{}, upper_{};
    std::array<double, analysis_bands> bandwidth_{};
    unsigned cursor_ = 0;
    std::uint64_t frames_ = 0;
    double normalization_ = 0;
    void channel(const std::array<float, analysis_size>& input, Observation& observation) noexcept {
        for (unsigned i = 0; i < analysis_size; ++i) fft_[reverse_[i]] = double(input[(cursor_ + i) % analysis_size]) * window_[i];
        for (unsigned length = 2; length <= analysis_size; length *= 2) {
            const unsigned half = length / 2, stride = analysis_size / length;
            for (unsigned start = 0; start < analysis_size; start += length) {
                for (unsigned j = 0; j < half; ++j) {
                    const auto a = fft_[start + j], b = fft_[start + j + half] * twiddles_[j * stride];
                    fft_[start + j] = a + b; fft_[start + j + half] = a - b;
                }
            }
        }
        for (unsigned bin = 1; bin < analysis_size / 2; ++bin) observation.total += std::norm(fft_[bin]) * normalization_;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            double power = 0;
            for (unsigned bin = lower_[band]; bin <= upper_[band]; ++bin) power += std::norm(fft_[bin]);
            observation.power[band] += power * normalization_ * bandwidth_[band] / (upper_[band] - lower_[band] + 1);
        }
    }
public:
    // Called by the suspended host on the control side, not from the audio callback.
    void configure(double rate) noexcept {
        double sum = 0;
        for (unsigned i = 0; i < analysis_size; ++i) {
            window_[i] = static_cast<float>(.5 - .5 * std::cos(2 * pi * i / analysis_size));
            sum += double(window_[i]) * window_[i];
            unsigned source = i, reversed = 0;
            for (unsigned bit = 0; bit < 14; ++bit) { reversed = reversed * 2 + (source & 1); source >>= 1; }
            reverse_[i] = static_cast<unsigned short>(reversed);
            if (i < analysis_size / 2) twiddles_[i] = std::polar(1.0, -2 * pi * i / analysis_size);
        }
        normalization_ = 1 / (analysis_size * sum); // Stereo channel means, positive spectrum doubled below.
        const double bin_width = rate / analysis_size;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            const double centre = band_frequency(band), low = centre / std::exp2(1.0 / 6), high = centre * std::exp2(1.0 / 6);
            unsigned lower = static_cast<unsigned>(std::ceil(low / bin_width));
            unsigned upper = static_cast<unsigned>(std::floor(high / bin_width));
            if (lower > upper) lower = upper = static_cast<unsigned>(std::round(centre / bin_width));
            lower_[band] = std::clamp(lower, 1u, analysis_size / 2 - 1);
            upper_[band] = std::clamp(upper, lower_[band], analysis_size / 2 - 1);
            bandwidth_[band] = (high - low) / bin_width;
        }
        reset();
    }
    void reset() noexcept { left_.fill(0); right_.fill(0); cursor_ = 0; frames_ = 0; }
    bool push(double left, double right) noexcept {
        constexpr double limit = 1e20; // Avoid float overflow before FFT/power analysis.
        left_[cursor_] = static_cast<float>(std::clamp(left, -limit, limit));
        right_[cursor_] = static_cast<float>(std::clamp(right, -limit, limit));
        cursor_ = (cursor_ + 1) % analysis_size;
        ++frames_;
        return frames_ >= analysis_size && (frames_ - analysis_size) % analysis_hop == 0;
    }
    Observation analyze() noexcept {
        Observation result;
        channel(left_, result); channel(right_, result);
        // Each channel contributes half of the two-sided power: factors cancel.
        return result;
    }
};

class Adaptive {
    struct Filter {
        Coefficients coefficients{1, 0, 0, 0, 0};
        std::array<double, 2> z1{}, z2{};
        double process(double value, unsigned channel) noexcept {
            const auto& c = coefficients;
            const double result = c[0] * value + z1[channel];
            z1[channel] = c[1] * value - c[3] * result + z2[channel];
            z2[channel] = c[2] * value - c[4] * result;
            if (std::abs(z1[channel]) < 1e-30) z1[channel] = 0;
            if (std::abs(z2[channel]) < 1e-30) z2[channel] = 0;
            return result;
        }
    };
    using Curve = std::array<double, adaptive_filters>;
    Spectrum spectrum_;
    std::array<Filter, adaptive_filters> filters_{};
    Curve current_{}, target_{};
    std::array<double, analysis_bands> slow_{}, fast_{}, weight_{}, k_weight_{}, desired_{};
    std::array<double, fit_points> grid_frequency_{}, grid_weight_{};
    std::array<std::complex<double>, fit_points> grid_z_{};
    std::array<std::array<double, adaptive_filters>, fit_points> basis_{};
    std::array<std::array<double, adaptive_filters>, adaptive_filters> cholesky_{};
    double rate_ = 48000, mean_ = 0, target_makeup_ = 0, makeup_linear_ = 1, target_makeup_linear_ = 1;
    double slow_alpha_ = 0, fast_alpha_ = 0, mean_alpha_ = 0, slew_ = 0, makeup_slew_ = 0, weight_sum_ = 0;
    std::uint64_t observed_ = 0, admitted_ = 0;
    unsigned phase_ = 0;
    bool enabled_ = false, active_ = false;
    Curve solve(const Curve& rhs) const noexcept {
        Curve result = rhs;
        for (unsigned i = 0; i < adaptive_filters; ++i) {
            for (unsigned j = 0; j < i; ++j) result[i] -= cholesky_[i][j] * result[j];
            result[i] /= cholesky_[i][i];
        }
        for (int i = adaptive_filters - 1; i >= 0; --i) {
            for (unsigned j = i + 1; j < adaptive_filters; ++j) result[i] -= cholesky_[j][i] * result[j];
            result[i] /= cholesky_[i][i];
        }
        return result;
    }
    Curve project(const std::array<double, fit_points>& values) const noexcept {
        Curve rhs{};
        for (unsigned point = 0; point < fit_points; ++point) for (unsigned band = 0; band < adaptive_filters; ++band) {
            rhs[band] += basis_[point][band] * grid_weight_[point] * values[point];
        }
        return solve(rhs);
    }
    double interpolate(double frequency) const noexcept {
        const double position = std::clamp(3 * std::log2(frequency / 1000) + 14, 0.0, double(analysis_bands - 1));
        const unsigned lower = static_cast<unsigned>(position), upper = std::min(lower + 1, analysis_bands - 1);
        return desired_[lower] + (position - lower) * (desired_[upper] - desired_[lower]);
    }
    void fit() noexcept {
        std::array<double, fit_points> values{};
        for (unsigned point = 0; point < fit_points; ++point) values[point] = interpolate(grid_frequency_[point]);
        Curve gains = project(values);
        for (unsigned iteration = 0; iteration < 2; ++iteration) {
            std::array<Coefficients, adaptive_filters> filters;
            for (unsigned band = 0; band < adaptive_filters; ++band) filters[band] = peak_coefficients(adaptive_frequency(band), gains[band], 2, rate_);
            std::array<double, fit_points> residual = values;
            for (unsigned point = 0; point < fit_points; ++point) for (const auto& filter : filters) {
                residual[point] -= 10 * std::log10(response_power(filter, grid_z_[point]));
            }
            const Curve step = project(residual);
            for (unsigned band = 0; band < adaptive_filters; ++band) gains[band] = std::clamp(gains[band] + step[band], -8.0, 4.0);
        }
        target_ = gains;
    }
    void learn(const Observation& observation) noexcept {
        ++observed_;
        double useful = 0;
        for (double value : observation.power) useful += value;
        // Deliberate DC-leak rejection before history/admission. This leaves low
        // valid tones/noise eligible while preventing Hann bin1 from steering EQ.
        if (observation.total < 1e-7 || useful < std::max(1e-20, observation.total * 1e-10) ||
            (mean_ > 0 && observation.total < mean_ * .1)) return;
        ++admitted_;
        mean_ = admitted_ == 1 ? observation.total : mean_ + mean_alpha_ * (observation.total - mean_);
        const double slow_alpha = std::max(1.0 / admitted_, slow_alpha_), fast_alpha = std::max(1.0 / admitted_, fast_alpha_);
        std::array<double, analysis_bands> difference{}, effective{}, shape{};
        double centre = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            slow_[band] += slow_alpha * (observation.power[band] - slow_[band]);
            fast_[band] += fast_alpha * (observation.power[band] - fast_[band]);
            difference[band] = 10 * std::log10((fast_[band] + 1e-20) / (slow_[band] + 1e-20));
            centre += weight_[band] * difference[band];
        }
        centre /= weight_sum_;
        double variance = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) variance += weight_[band] * std::pow(difference[band] - centre, 2);
        const double blend = std::clamp((std::sqrt(variance / weight_sum_) - 3) / 5, 0.0, 1.0);
        double intercept = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            effective[band] = slow_[band] + blend * (fast_[band] - slow_[band]);
            slow_[band] += .3 * blend * (fast_[band] - slow_[band]);
            shape[band] = 10 * std::log10(effective[band] + 1e-20) + 2.5 * (double(band) - 14) / 3;
            intercept += weight_[band] * shape[band];
        }
        intercept /= weight_sum_;
        const double warm = std::min(1.0, double(admitted_) * analysis_hop / (4 * rate_));
        for (unsigned band = 0; band < analysis_bands; ++band) {
            const double smooth = .25 * shape[band ? band - 1 : 0] + .5 * shape[band] + .25 * shape[std::min(band + 1, analysis_bands - 1)];
            desired_[band] = (shaped_correction(smooth - intercept) * weight_[band] + bass_preference(band_frequency(band))) * warm;
        }
        fit();
        std::array<Coefficients, adaptive_filters> filters;
        for (unsigned band = 0; band < adaptive_filters; ++band) filters[band] = peak_coefficients(adaptive_frequency(band), target_[band], 2, rate_);
        double original = 0, corrected = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            const double power = effective[band] * k_weight_[band];
            original += power;
            const auto z = std::polar(1.0, -2 * pi * band_frequency(band) / rate_);
            double response = 1;
            for (const auto& filter : filters) response *= response_power(filter, z);
            corrected += power * response;
        }
        target_makeup_ = std::clamp(10 * std::log10((original + 1e-20) / (corrected + 1e-20)), -6.0, 3.0);
        target_makeup_linear_ = std::pow(10, target_makeup_ / 20);
    }
public:
    void configure(double rate) noexcept {
        rate_ = rate; spectrum_.configure(rate);
        const double hop_seconds = analysis_hop / rate;
        slow_alpha_ = -std::expm1(-hop_seconds / 8);
        fast_alpha_ = -std::expm1(-hop_seconds / 1.5);
        mean_alpha_ = -std::expm1(-hop_seconds / 30);
        slew_ = -std::expm1(-32 / (.25 * rate));
        makeup_slew_ = -std::expm1(-1 / (.25 * rate));
        weight_sum_ = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) {
            weight_[band] = correction_weight(band_frequency(band)); weight_sum_ += weight_[band];
            k_weight_[band] = k_power(band_frequency(band), rate);
        }
        for (unsigned point = 0; point < fit_points; ++point) {
            const double frequency = 40 * std::exp2(double(point) / 6);
            grid_frequency_[point] = frequency; grid_weight_[point] = std::max(.1, correction_weight(frequency));
            grid_z_[point] = std::polar(1.0, -2 * pi * frequency / rate);
            for (unsigned band = 0; band < adaptive_filters; ++band) basis_[point][band] = 10 * std::log10(response_power(peak_coefficients(adaptive_frequency(band), 1, 2, rate), grid_z_[point]));
        }
        for (unsigned i = 0; i < adaptive_filters; ++i) for (unsigned j = 0; j <= i; ++j) {
            double value = 0;
            for (unsigned point = 0; point < fit_points; ++point) value += basis_[point][i] * grid_weight_[point] * basis_[point][j];
            if (i == j) value += .02 + .1 * ((i == 0 || i + 1 == adaptive_filters) ? 1 : 2);
            else if (i == j + 1) value -= .1;
            for (unsigned k = 0; k < j; ++k) value -= cholesky_[i][k] * cholesky_[j][k];
            cholesky_[i][j] = i == j ? std::sqrt(std::max(value, 1e-12)) : value / cholesky_[j][j];
        }
        for (auto& filter : filters_) filter = Filter{};
        current_.fill(0); target_.fill(0); target_makeup_ = 0; makeup_linear_ = target_makeup_linear_ = 1;
        phase_ = 0; enabled_ = active_ = false;
        reset_analysis();
    }
    void reset_analysis() noexcept {
        spectrum_.reset(); slow_.fill(0); fast_.fill(0); desired_.fill(0);
        mean_ = 0; admitted_ = observed_ = 0;
    }
    void enable(bool enabled) noexcept {
        if (enabled == enabled_) return;
        enabled_ = enabled;
        target_.fill(0); target_makeup_ = 0;
        target_makeup_linear_ = 1;
        if (enabled) { active_ = true; reset_analysis(); }
    }
    void process(double& left, double& right) noexcept {
        if (!active_) return;
        const double raw_left = left, raw_right = right;
        if (phase_ == 0) {
            for (unsigned band = 0; band < adaptive_filters; ++band) {
                current_[band] += slew_ * (target_[band] - current_[band]);
                filters_[band].coefficients = peak_coefficients(adaptive_frequency(band), current_[band], 2, rate_);
            }
            if (!enabled_) {
                double remaining = std::abs(makeup_linear_ - 1);
                for (double gain : current_) remaining = std::max(remaining, std::abs(gain));
                if (remaining < 1e-8) {
                    current_.fill(0); makeup_linear_ = 1; active_ = false;
                    for (auto& filter : filters_) filter = Filter{};
                    return;
                }
            }
        }
        phase_ = (phase_ + 1) % 32;
        for (auto& filter : filters_) { left = filter.process(left, 0); right = filter.process(right, 1); }
        makeup_linear_ += makeup_slew_ * (target_makeup_linear_ - makeup_linear_);
        left *= makeup_linear_; right *= makeup_linear_;
        // Analyze only samples that have actually reached this causal boundary.
        if (enabled_ && spectrum_.push(raw_left, raw_right)) learn(spectrum_.analyze());
    }
    std::uint64_t observed() const noexcept { return observed_; }
    std::uint64_t admitted() const noexcept { return admitted_; }
    const Curve& gains() const noexcept { return current_; }
    double makeup() const noexcept { return 20 * std::log10(makeup_linear_); }
};
}
