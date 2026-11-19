// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#pragma once

#include "protocol.h"
#include "dynamics.h"
#include "adaptive.h"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <limits>

namespace yasb::dsp {
// Single producer/single consumer, latest-only, fixed storage. A retired slot
// cannot be reused by the producer until the consumer has exchanged it away.
// External callers serialize producers/readers; the audio side never locks.
template<class T> class Latest {
    static_assert(std::is_trivially_copyable_v<T>);
    std::array<T, 3> slots_{};
    std::atomic<unsigned> middle_{1};
    unsigned back_ = 2;
    unsigned front_ = 0;
public:
    void publish(const T& value) noexcept {
        slots_[back_] = value;
        back_ = middle_.exchange(back_ | 4, std::memory_order_acq_rel) & 3;
    }
    bool take(T& value) noexcept {
        if (!(middle_.load(std::memory_order_acquire) & 4)) return false;
        front_ = middle_.exchange(front_, std::memory_order_acq_rel) & 3;
        value = slots_[front_];
        return true;
    }
};
static_assert(std::atomic<unsigned>::is_always_lock_free);

struct Prepared {
    Parameters parameters{};
    std::array<Coefficients, 10> filters{};
    std::array<double, 4> matrix{1, 0, 0, 1};
    unsigned ramp_frames = 960;
    DynamicsTuning dynamics{};
    double preamp_gain = 1;
};

inline bool supported_rate(double rate) noexcept {
    return rate == 44100 || rate == 48000 || rate == 88200 || rate == 96000 || rate == 176400 || rate == 192000;
}

// Independent implementation of the peaking-EQ mathematics in the W3C Audio
// EQ Cookbook. Coefficient construction happens on the non-audio control side.
inline bool prepare(const Parameters& parameters, double rate, Prepared& result) noexcept {
    if (!supported_rate(rate) || parameters.magic_number != magic || parameters.version != protocol ||
        !std::isfinite(parameters.preamp_db) || parameters.preamp_db < -24 || parameters.preamp_db > 12 ||
        parameters.dynamics > 2 || (parameters.flags & ~(mono | swap | adaptive | bypass)) ||
        !std::isfinite(parameters.balance) || std::abs(parameters.balance) > 1) return false;
    for (float gain : parameters.gains) {
        if (!std::isfinite(gain) || std::abs(gain) > 12) return false;
    }
    Prepared next;
    next.parameters = parameters;
    next.ramp_frames = static_cast<unsigned>(std::round(rate * .020));
    next.dynamics = dynamics_tuning(parameters.dynamics, rate);
    next.preamp_gain = std::pow(10, parameters.preamp_db / 20);
    for (unsigned band = 0; band < frequencies.size(); ++band) {
        next.filters[band] = peak_coefficients(frequencies[band], parameters.flags & adaptive ? 0 : parameters.gains[band], 1, rate);
    }
    if (parameters.flags & mono) {
        next.matrix = {.5, .5, .5, .5}; // Balance is inactive in mono.
    } else {
        const double left = 1 - std::max(0.0f, parameters.balance);
        const double right = 1 + std::min(0.0f, parameters.balance);
        next.matrix = parameters.flags & swap ? std::array<double, 4>{0, left, right, 0}
                                             : std::array<double, 4>{left, 0, 0, right};
    }
    result = next;
    return true;
}

class Processor {
    struct Filter {
        Coefficients coefficients{1, 0, 0, 0, 0};
        Coefficients step{};
        std::array<double, 2> z1{}, z2{};
        double sample(double input, unsigned channel) noexcept {
            const auto& c = coefficients;
            const double output = c[0] * input + z1[channel];
            z1[channel] = c[1] * input - c[3] * output + z2[channel];
            z2[channel] = c[2] * input - c[4] * output;
            if (std::abs(z1[channel]) < 1e-30) z1[channel] = 0;
            if (std::abs(z2[channel]) < 1e-30) z2[channel] = 0;
            return output;
        }
    };
    std::array<Filter, 10> filters_{};
    std::array<double, 4> matrix_{1, 0, 0, 1}, matrix_step_{};
    Prepared target_{};
    unsigned remaining_ = 0;
    std::uint64_t applied_ = 0, settled_ = 0;
    Compressor compressor_;
    Limiter limiter_;
    Adaptive adaptive_;
    double preamp_gain_ = 1, preamp_step_ = 0;
public:
    void reset(double rate = 48000) noexcept {
        // Reset in place: the FFT storage must never create a large stack temporary.
        for (auto& filter : filters_) filter = Filter{};
        matrix_ = {1, 0, 0, 1}; matrix_step_.fill(0); target_ = Prepared{};
        remaining_ = 0; applied_ = settled_ = 0;
        preamp_gain_ = 1; preamp_step_ = 0;
        compressor_.reset(); limiter_.configure(dynamics_tuning(0, rate)); limiter_.reset();
        adaptive_.configure(rate);
    }
    void accept(const Prepared& prepared) noexcept {
        target_ = prepared;
        remaining_ = std::max(1u, prepared.ramp_frames);
        for (unsigned band = 0; band < filters_.size(); ++band) {
            for (unsigned c = 0; c < 5; ++c) {
                filters_[band].step[c] = (prepared.filters[band][c] - filters_[band].coefficients[c]) / remaining_;
            }
        }
        for (unsigned c = 0; c < 4; ++c) matrix_step_[c] = (prepared.matrix[c] - matrix_[c]) / remaining_;
        preamp_step_ = (prepared.preamp_gain - preamp_gain_) / remaining_;
        applied_ = prepared.parameters.revision;
        compressor_.configure(prepared.dynamics);
        limiter_.configure(prepared.dynamics);
        adaptive_.enable((prepared.parameters.flags & adaptive) != 0);
        if (prepared.parameters.flags & bypass) settled_ = applied_;
    }
    std::uint64_t applied_revision() const noexcept { return applied_; }
    std::uint64_t settled_revision() const noexcept { return settled_; }
    unsigned flags() const noexcept { return target_.parameters.flags; }
    unsigned dynamics_mode() const noexcept { return target_.parameters.dynamics; }
    unsigned latency() const noexcept { return (dynamics_mode() || (flags() & adaptive)) && !(flags() & bypass) ? limiter_.latency() : 0; }
    const Adaptive& adaptive_state() const noexcept { return adaptive_; }
    std::uint64_t applied_fingerprint() const noexcept { return applied_ ? fingerprint(target_.parameters) : 0; }
    void process(const float* const* input, float** output, int frames, bool accumulate = false) noexcept {
        constexpr double limit = std::numeric_limits<float>::max();
        for (int frame = 0; frame < frames; ++frame) {
            if (flags() & bypass) {
                const float left = input[0][frame], right = input[1][frame];
                output[0][frame] = left + (accumulate ? output[0][frame] : 0);
                output[1][frame] = right + (accumulate ? output[1][frame] : 0);
                continue; // Explicit bypass is immediate and freezes DSP history.
            }
            if (remaining_) {
                for (auto& filter : filters_) for (unsigned c = 0; c < 5; ++c) filter.coefficients[c] += filter.step[c];
                for (unsigned c = 0; c < 4; ++c) matrix_[c] += matrix_step_[c];
                preamp_gain_ += preamp_step_;
                if (!--remaining_) {
                    for (unsigned band = 0; band < filters_.size(); ++band) filters_[band].coefficients = target_.filters[band];
                    matrix_ = target_.matrix;
                    preamp_gain_ = target_.preamp_gain;
                    settled_ = applied_;
                }
            }
            double left = std::isfinite(input[0][frame]) ? input[0][frame] : 0;
            double right = std::isfinite(input[1][frame]) ? input[1][frame] : 0;
            left *= preamp_gain_; right *= preamp_gain_;
            for (auto& filter : filters_) {
                left = filter.sample(left, 0);
                right = filter.sample(right, 1);
            }
            adaptive_.process(left, right);
            double l = matrix_[0] * left + matrix_[1] * right;
            double r = matrix_[2] * left + matrix_[3] * right;
            if (dynamics_mode()) {
                compressor_.process(l, r);
                limiter_.process(l, r, .8912509381337456); // -1dBFS sample peak.
            } else if (flags() & adaptive) {
                limiter_.process(l, r, .9885530946569389); // -0.1dBFS safety sample peak.
            }
            const double out_left = l + (accumulate ? output[0][frame] : 0);
            const double out_right = r + (accumulate ? output[1][frame] : 0);
            output[0][frame] = std::isfinite(out_left) ? static_cast<float>(std::clamp(out_left, -limit, limit)) : 0;
            output[1][frame] = std::isfinite(out_right) ? static_cast<float>(std::clamp(out_right, -limit, limit)) : 0;
        }
    }
};
}
