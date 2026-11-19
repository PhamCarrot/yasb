// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cmath>
#include <complex>

namespace yasb::dsp {
constexpr double pi = 3.14159265358979323846;
using Coefficients = std::array<double, 5>;
inline Coefficients peak_coefficients(double frequency, double gain, double q, double rate) noexcept {
    const double angle = 2 * pi * frequency / rate;
    const double alpha = std::sin(angle) / (2 * q);
    const double amplitude = std::pow(10, gain / 40);
    const double a0 = 1 + alpha / amplitude;
    return {(1 + alpha * amplitude) / a0, -2 * std::cos(angle) / a0, (1 - alpha * amplitude) / a0,
            -2 * std::cos(angle) / a0, (1 - alpha / amplitude) / a0};
}
inline double response_power(const Coefficients& c, std::complex<double> z) noexcept {
    const auto z2 = z * z;
    return std::norm(c[0] + c[1] * z + c[2] * z2) / std::norm(1.0 + c[3] * z + c[4] * z2);
}
inline double k_power(double frequency, double rate) noexcept {
    const auto z = std::polar(1.0, -2 * pi * frequency / rate);
    const double wh = 2 * pi * 38.13 / rate;
    const double ch = std::cos(wh), ah = std::sin(wh) / (2 * .5003), h0 = 1 + ah;
    const Coefficients highpass{(1 + ch) / (2 * h0), -(1 + ch) / h0, (1 + ch) / (2 * h0),
                               -2 * ch / h0, (1 - ah) / h0};
    const double ws = 2 * pi * 1681.97 / rate;
    const double cs = std::cos(ws), a = std::pow(10, 3.9998 / 40);
    const double beta = 2 * std::sqrt(a) * std::sin(ws) / (2 * .7072);
    const double s0 = a + 1 - (a - 1) * cs + beta;
    const Coefficients shelf{
        a * (a + 1 + (a - 1) * cs + beta) / s0, -2 * a * (a - 1 + (a + 1) * cs) / s0,
        a * (a + 1 + (a - 1) * cs - beta) / s0, 2 * (a - 1 - (a + 1) * cs) / s0,
        (a + 1 - (a - 1) * cs - beta) / s0};
    return response_power(highpass, z) * response_power(shelf, z);
}
}
