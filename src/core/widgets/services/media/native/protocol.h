// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace yasb::dsp {
constexpr std::uint32_t magic = 0x59445350; // YDSP
constexpr std::uint32_t protocol = 3;
constexpr std::uint32_t mono = 1;
constexpr std::uint32_t swap = 2;
constexpr std::uint32_t adaptive = 4;
constexpr std::uint32_t bypass = 8;
constexpr std::int32_t status_opcode = 0x59445350;
constexpr std::array<double, 10> frequencies{32, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000};

// Fixed-width little-endian wire format for x64 Windows.
// No native pointers, bools, paths or implicit per-band commands cross this boundary.
struct Parameters {
    std::uint32_t magic_number = magic;
    std::uint32_t version = protocol;
    std::uint64_t revision = 0;
    std::array<float, 10> gains{};
    float balance = 0;
    std::uint32_t flags = 0;
    std::uint32_t dynamics = 0; // 0=off, 1=Balanced, 2=Night
    float preamp_db = 0;
};
static_assert(sizeof(Parameters) == 72);
static_assert(std::is_trivially_copyable_v<Parameters>);

struct Status {
    std::uint32_t version = protocol;
    std::uint32_t bytes = sizeof(Status);
    std::uint64_t build = 0;
    std::uint64_t instance = 0;
    std::uint64_t accepted_revision = 0;
    std::uint64_t applied_revision = 0;
    std::uint64_t settled_revision = 0; // Manual/stereo ramp only, not adaptive convergence/audibility.
    std::uint64_t processed_frames = 0;
    std::uint32_t sample_rate = 48000;
    std::uint32_t channels = 2;
    std::uint32_t latency_frames = 0;
    std::uint32_t processing = 0; // 0=suspended, 1=supported callback, 2=unsupported rate, 3=bypassed
    std::uint32_t flags = 0;
    std::uint32_t dynamics = 0;
    std::uint64_t adaptive_observations = 0;
    std::uint64_t adaptive_admitted = 0;
    float adaptive_makeup = 0;
    std::array<float, 17> adaptive_gains{};
    std::array<std::uint8_t, 16> instance_uuid{};
    std::uint64_t stream_epoch = 1;
    std::uint64_t accepted_fingerprint = 0;
    std::uint64_t applied_fingerprint = 0;
    std::uint32_t transport_state = 0; // 0=not configured, 1=connecting, 2=connected, 3=error
    std::uint32_t transport_error = 0;
    std::uint32_t process_id = 0;
    std::uint32_t host_latency_pending = 0; // Host-owned safe dispatcher entry still required.
    std::uint64_t callback_age_ms = UINT64_MAX; // Non-audio consumer tracks frame progress.
};
static_assert(sizeof(Status) == 232);

using Id = std::array<std::uint8_t, 16>;
using Key = std::array<std::uint8_t, 32>;
struct Bootstrap {
    std::uint32_t magic_number = magic;
    std::uint32_t version = protocol;
    std::uint32_t bytes = sizeof(Bootstrap);
    std::uint32_t reserved = 0;
    Id installation{};
    Key config{};
    Key endpoint{}; // Configured association, not independent endpoint attestation.
    std::array<char, 192> controller_sid{};
    Parameters initial{};
};
static_assert(sizeof(Bootstrap) == 360);

struct PeerReport {
    Key config{}, endpoint{};
    Status status{};
    std::uint64_t age_ms = 0;
    std::uint64_t confirmed_generation = 0;
    std::uint64_t connection_epoch = 0;
};
static_assert(sizeof(PeerReport) == 320);

inline std::uint64_t fingerprint(const Parameters& parameters) noexcept {
    // Value identity, not authentication. Header/revision do not affect settings.
    const auto* bytes = reinterpret_cast<const unsigned char*>(&parameters) + offsetof(Parameters, gains);
    std::uint64_t result = 14695981039346656037ULL;
    for (unsigned i = 0; i < 56; ++i) result = (result ^ bytes[i]) * 1099511628211ULL;
    return result;
}
}
