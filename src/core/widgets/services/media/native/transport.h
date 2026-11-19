// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#pragma once
#include "protocol.h"
#include <memory>

namespace yasb::dsp {
bool random_identity(Id& id) noexcept;
bool valid_bootstrap(const Bootstrap& bootstrap) noexcept;
bool same_binding(const Bootstrap& left, const Bootstrap& right) noexcept;

struct ClientHooks {
    void* owner = nullptr;
    void (*status)(void*, Status&) = nullptr;
    bool (*submit)(void*, const Parameters&, std::uint64_t expected_epoch) = nullptr;
    void (*connection)(void*, std::uint32_t state, std::uint32_t error) = nullptr;
};
class ResidentClient {
    struct Impl;
    std::unique_ptr<Impl> impl_;
public:
    ResidentClient(const Bootstrap& bootstrap, ClientHooks hooks);
    ~ResidentClient();
    void stop() noexcept;
    std::uint32_t state() const noexcept;
    std::uint32_t error() const noexcept;
};
}

// C ABI bridge: opaque lifetime owner, bounded byte buffers, no Python callbacks.
#ifdef YASB_DSP_EXPORTS
#define YASB_DSP_API __declspec(dllexport)
#else
#define YASB_DSP_API
#endif
extern "C" {
YASB_DSP_API int YasbMediaProtocolInfo(void* output, unsigned bytes);
YASB_DSP_API int YasbMediaBootstrapInit(yasb::dsp::Bootstrap* output, unsigned bytes);
YASB_DSP_API void* YasbMediaBrokerCreate(const yasb::dsp::Bootstrap* bootstrap, unsigned bytes);
YASB_DSP_API int YasbMediaBrokerPublish(void* broker, const yasb::dsp::Bootstrap* binding,
    unsigned bytes, const yasb::dsp::Parameters* parameters, std::uint64_t generation);
YASB_DSP_API unsigned YasbMediaBrokerReports(void* broker, yasb::dsp::PeerReport* output, unsigned capacity);
YASB_DSP_API void YasbMediaBrokerDestroy(void* broker);
}
