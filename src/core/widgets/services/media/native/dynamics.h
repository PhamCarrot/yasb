// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
// Independently implemented streaming mathematics; no external DSP source used.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace yasb::dsp {
struct DynamicsTuning {
    double threshold = -26, ratio = 2.8, knee = 20;
    double detector = 0, attack = 0, release = 0, limiter_release = 0;
    unsigned window = 240;
};
inline DynamicsTuning dynamics_tuning(unsigned mode, double rate) noexcept {
    DynamicsTuning value;
    const bool night = mode == 2;
    if (night) { value.threshold = -36; value.ratio = 6; value.knee = 28; }
    value.detector = -std::expm1(-1 / (.010 * rate));
    value.attack = -std::expm1(-1 / ((night ? .006 : .014) * rate));
    value.release = -std::expm1(-1 / ((night ? .320 : .200) * rate));
    value.limiter_release = -std::expm1(-1 / (.050 * rate));
    value.window = std::max(2u, static_cast<unsigned>(std::floor(.005 * rate)));
    return value;
}

class Compressor {
    DynamicsTuning tuning_{};
    double power_ = 0, attenuation_ = 0;
public:
    void configure(const DynamicsTuning& tuning) noexcept { tuning_ = tuning; }
    void reset() noexcept { power_ = attenuation_ = 0; }
    void process(double& left, double& right) noexcept {
        const auto& t = tuning_;
        const double power = (left * left + right * right) * .5;
        power_ += t.detector * (power - power_);
        const double over = 10 * std::log10(power_ + 1e-12) - t.threshold;
        const double slope = 1 - 1 / t.ratio;
        double desired = 0;
        if (over >= t.knee * .5) desired = slope * over;
        else if (over > -t.knee * .5) desired = slope * (over + t.knee * .5) * (over + t.knee * .5) / (2 * t.knee);
        attenuation_ += (desired > attenuation_ ? t.attack : t.release) * (desired - attenuation_);
        const double gain = std::pow(10, -attenuation_ / 20);
        left *= gain;
        right *= gain;
    }
};

class Limiter {
    static constexpr unsigned capacity = 1024; // 192kHz *5ms=960; no runtime allocation.
    std::array<double, capacity> audio_left_{}, audio_right_{}, gain_history_{};
    std::array<double, capacity> requirements_{};
    std::array<std::uint64_t, capacity> positions_{};
    unsigned window_ = 0, cursor_ = 0, head_ = 0, count_ = 0;
    std::uint64_t frame_ = 0;
    double hold_ = 1, sum_ = 0, release_ = 0;
public:
    void configure(const DynamicsTuning& tuning) noexcept {
        release_ = tuning.limiter_release;
        if (window_ == tuning.window) return;
        window_ = std::min(capacity, tuning.window);
        reset();
    }
    void reset() noexcept {
        audio_left_.fill(0); audio_right_.fill(0); gain_history_.fill(1);
        cursor_ = head_ = count_ = 0; frame_ = 0;
        hold_ = 1; sum_ = window_;
    }
    unsigned latency() const noexcept { return window_ ? window_ - 1 : 0; }
    void process(double& left, double& right, double ceiling) noexcept {
        const double peak = std::max(std::abs(left), std::abs(right));
        const double required = peak > ceiling ? ceiling / peak : 1;
        // Retain each sample's gain requirement, including its original ceiling.
        // Changing modes must not reinterpret samples already in the delay line.
        while (count_ && frame_ >= window_ && positions_[head_] <= frame_ - window_) {
            head_ = (head_ + 1) % capacity; --count_;
        }
        while (count_ && requirements_[(head_ + count_ - 1) % capacity] >= required) --count_;
        const unsigned tail = (head_ + count_) % capacity;
        requirements_[tail] = required; positions_[tail] = frame_; ++count_;
        const double wanted = requirements_[head_];
        hold_ = std::min(wanted, hold_ + release_ * (1 - hold_));
        sum_ += hold_ - gain_history_[cursor_];
        gain_history_[cursor_] = hold_;
        audio_left_[cursor_] = left; audio_right_[cursor_] = right;
        const unsigned delayed = (cursor_ + 1) % window_;
        const double gain = std::clamp(sum_ / window_, 0.0, 1.0);
        left = std::clamp(audio_left_[delayed] * gain, -ceiling, ceiling);
        right = std::clamp(audio_right_[delayed] * gain, -ceiling, ceiling);
        cursor_ = delayed;
        ++frame_;
    }
};
}
