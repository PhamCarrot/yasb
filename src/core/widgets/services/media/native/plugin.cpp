// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstddef>
#include <cstring>
#include <mutex>
#include <new>
#include "vendor/xaymar-vst2/vst.h"
#include "processor.h"
#include "transport.h"

#ifndef YASB_DSP_BUILD_ID
#error Build with build_media_dsp.py to bind readback to the source.
#endif
static_assert(sizeof(void*) == 8, "The media processor requires 64-bit Windows");
static_assert(offsetof(vst_effect, process_float) == 120);
static_assert(sizeof(vst_effect) == 192);

namespace {
using namespace yasb::dsp;
std::atomic<std::uint32_t> next_instance{1};
struct Plugin {
    vst_effect effect{};
    std::mutex control_mutex;
    Parameters saved{}, exported{};
    Bootstrap binding{}, exported_binding{};
    bool configured = false, client_started = false, latency_pending = false;
    std::unique_ptr<ResidentClient> client;
    Latest<Prepared> commands;
    Latest<Status> reports;
    Status audio_status{}, last_report{};
    Processor processor;
    std::atomic<std::uint64_t> accepted{0};
    std::atomic<bool> running{false};
    std::atomic<bool> closing{false};
    std::atomic<std::uint32_t> transport_state{0}, transport_error{0};
    std::uint64_t stream_epoch = 1, progress_epoch = 0, progress_frames = 0;
    ULONGLONG progress_tick = 0;
    double rate = 48000;
    bool rate_supported = true;
    vst_host_callback host_callback;
    explicit Plugin(vst_host_callback callback) : host_callback(callback) {
        processor.reset();
        audio_status.build = YASB_DSP_BUILD_ID;
        audio_status.instance = (std::uint64_t(GetCurrentProcessId()) << 32) | next_instance.fetch_add(1);
        if (!random_identity(audio_status.instance_uuid)) throw std::bad_alloc();
        audio_status.process_id = GetCurrentProcessId();
        last_report = audio_status;
    }
};
Plugin& owner(vst_effect* effect) noexcept { return *static_cast<Plugin*>(effect->effect_internal); }

bool submit_locked(Plugin& plugin, const Parameters& parameters) {
    Prepared prepared;
    if (plugin.closing.load() || parameters.revision <= plugin.accepted.load() || !prepare(parameters, plugin.rate, prepared)) return false;
    plugin.commands.publish(prepared); plugin.saved = parameters;
    plugin.accepted.store(parameters.revision, std::memory_order_release);
    return true;
}
std::int32_t wanted_delay(const Plugin& plugin) noexcept {
    const auto& saved = plugin.saved;
    return plugin.rate_supported && !(saved.flags & bypass) && (saved.dynamics || (saved.flags & adaptive))
        ? static_cast<std::int32_t>(dynamics_tuning(saved.dynamics, plugin.rate).window - 1) : 0;
}
bool delay_locked(Plugin& plugin) noexcept {
    const auto delay = wanted_delay(plugin);
    const bool changed = plugin.effect.delay != delay;
    plugin.latency_pending = false;
    plugin.effect.delay = delay;
    return changed;
}
Status status_locked(Plugin& plugin) {
    plugin.reports.take(plugin.last_report);
    auto& result = plugin.last_report;
    result.accepted_revision = plugin.accepted.load(std::memory_order_acquire);
    result.accepted_fingerprint = result.accepted_revision ? fingerprint(plugin.saved) : 0;
    result.processing = plugin.rate_supported ? (plugin.running.load() ? ((result.flags & bypass) ? 3 : 1) : 0) : 2;
    result.transport_state = plugin.transport_state.load(); result.transport_error = plugin.transport_error.load();
    result.host_latency_pending = plugin.latency_pending ? 1 : 0;
    const auto now = GetTickCount64(); // Control/report consumer only, never process_block.
    if (result.stream_epoch != plugin.progress_epoch) {
        plugin.progress_epoch = result.stream_epoch; plugin.progress_frames = 0; plugin.progress_tick = 0;
    }
    if (result.processed_frames > plugin.progress_frames) {
        plugin.progress_frames = result.processed_frames; plugin.progress_tick = now;
    }
    result.callback_age_ms = plugin.progress_tick ? now - plugin.progress_tick : UINT64_MAX;
    return result;
}
void read_client_status(void* context, Status& status) {
    auto& plugin = *static_cast<Plugin*>(context);
    std::lock_guard<std::mutex> lock(plugin.control_mutex); status = status_locked(plugin);
}
bool client_submit(void* context, const Parameters& parameters, std::uint64_t epoch) {
    auto& plugin = *static_cast<Plugin*>(context);
    std::lock_guard<std::mutex> lock(plugin.control_mutex);
    if (epoch != plugin.stream_epoch || !submit_locked(plugin, parameters)) return false;
    // A host callback may synchronously destroy the effect. Never invoke one
    // from this worker (destroy must join it), or write host-owned effect fields.
    plugin.latency_pending = wanted_delay(plugin) != plugin.effect.delay;
    return true;
}
void client_connection(void* context, std::uint32_t state, std::uint32_t error) {
    auto& plugin = *static_cast<Plugin*>(context);
    plugin.transport_error.store(error); plugin.transport_state.store(state);
}

void process_block(vst_effect* effect, const float* const* inputs, float** outputs, std::int32_t frames, bool accumulate) {
    auto& plugin = owner(effect);
    if (frames <= 0 || !inputs || !outputs || !inputs[0] || !inputs[1] || !outputs[0] || !outputs[1]) return;
    if (!plugin.running.load(std::memory_order_acquire) || !plugin.rate_supported) {
        for (int i = 0; i < frames; ++i) {
            const float left = inputs[0][i], right = inputs[1][i];
            outputs[0][i] = left + (accumulate ? outputs[0][i] : 0);
            outputs[1][i] = right + (accumulate ? outputs[1][i] : 0);
        }
        return;
    }
    Prepared update;
    if (plugin.commands.take(update)) plugin.processor.accept(update);
    plugin.processor.process(inputs, outputs, frames, accumulate);
    auto& status = plugin.audio_status;
    status.applied_revision = plugin.processor.applied_revision();
    status.settled_revision = plugin.processor.settled_revision();
    status.processed_frames += frames;
    status.latency_frames = plugin.processor.latency();
    status.flags = plugin.processor.flags();
    status.dynamics = plugin.processor.dynamics_mode();
    status.applied_fingerprint = plugin.processor.applied_fingerprint();
    const auto& adaptive_state = plugin.processor.adaptive_state();
    status.adaptive_observations = adaptive_state.observed();
    status.adaptive_admitted = adaptive_state.admitted();
    status.adaptive_makeup = static_cast<float>(adaptive_state.makeup());
    for (unsigned band = 0; band < adaptive_filters; ++band) status.adaptive_gains[band] = static_cast<float>(adaptive_state.gains()[band]);
    plugin.reports.publish(status);
}

void VST_FUNCTION_INTERFACE process(vst_effect* effect, const float* const* inputs, float** outputs, std::int32_t frames) {
    process_block(effect, inputs, outputs, frames, false);
}
void VST_FUNCTION_INTERFACE accumulate(vst_effect* effect, const float* const* inputs, float** outputs, std::int32_t frames) {
    process_block(effect, inputs, outputs, frames, true);
}

void VST_FUNCTION_INTERFACE set_parameter(vst_effect*, std::uint32_t, float) {}
float VST_FUNCTION_INTERFACE get_parameter(vst_effect*, std::uint32_t) { return 0; }

intptr_t locked_control(vst_effect* effect, VST_EFFECT_OPCODE opcode, std::int32_t index,
                                       intptr_t value, void* pointer, float option) {
    auto& plugin = owner(effect);
    switch (opcode) {
    case VST_EFFECT_OPCODE_CREATE: return 0;
    case VST_EFFECT_OPCODE_SET_SAMPLE_RATE: {
        if (plugin.running.load()) return 0; // Host must suspend before reconfiguration.
        plugin.rate = option;
        plugin.rate_supported = supported_rate(option);
        plugin.processor.reset(plugin.rate_supported ? option : 48000);
        plugin.audio_status.stream_epoch = ++plugin.stream_epoch;
        plugin.audio_status.processed_frames = 0;
        plugin.audio_status.applied_fingerprint = 0;
        Prepared prepared;
        if (prepare(plugin.saved, option, prepared)) plugin.commands.publish(prepared);
        plugin.audio_status.sample_rate = plugin.rate_supported ? static_cast<std::uint32_t>(option) : 0;
        plugin.audio_status.applied_revision = plugin.audio_status.settled_revision = 0;
        plugin.audio_status.flags = plugin.audio_status.dynamics = plugin.audio_status.latency_frames = 0;
        plugin.audio_status.adaptive_observations = plugin.audio_status.adaptive_admitted = 0;
        plugin.audio_status.adaptive_makeup = 0;
        plugin.audio_status.adaptive_gains.fill(0);
        plugin.last_report = plugin.audio_status;
        // Retire the audio report before host configuration changes are exposed.
        plugin.reports.take(plugin.last_report);
        plugin.last_report = plugin.audio_status;
        return 0;
    }
    case VST_EFFECT_OPCODE_SUSPEND:
        plugin.running.store(value != 0, std::memory_order_release);
        return 0;
    case VST_EFFECT_OPCODE_17:
        if (!pointer) return 0;
        if (plugin.configured) {
            plugin.exported_binding = plugin.binding; plugin.exported_binding.initial = plugin.saved;
            *static_cast<void**>(pointer) = &plugin.exported_binding; return sizeof(Bootstrap);
        }
        plugin.exported = plugin.saved;
        *static_cast<void**>(pointer) = &plugin.exported;
        return sizeof(Parameters);
    case VST_EFFECT_OPCODE_18: {
        if (!pointer) return 0;
        if (value == sizeof(Bootstrap)) {
            Bootstrap binding;
            std::memcpy(&binding, pointer, sizeof(binding));
            if (!valid_bootstrap(binding) || (plugin.configured && !same_binding(plugin.binding, binding)) || !submit_locked(plugin, binding.initial)) return 0;
            plugin.binding = binding; plugin.configured = true; return 1;
        }
        if (value != sizeof(Parameters)) return 0;
        Parameters parameters;
        std::memcpy(&parameters, pointer, sizeof(parameters));
        return submit_locked(plugin, parameters) ? 1 : 0;
    }
    case VST_EFFECT_OPCODE_CUSTOM:
        if (index != status_opcode || value != sizeof(Status) || !pointer) return 0;
        {
            const Status status = status_locked(plugin);
            std::memcpy(pointer, &status, sizeof(Status));
        }
        return 1;
    case VST_EFFECT_OPCODE_EFFECT_CATEGORY: return 1;
    case VST_EFFECT_OPCODE_EFFECT_NAME:
        if (pointer) strcpy_s(static_cast<char*>(pointer), VST_EFFECT_BUFFER_SIZE, "YASB Media Processor");
        return 1;
    case VST_EFFECT_OPCODE_VENDOR_NAME:
        if (pointer) strcpy_s(static_cast<char*>(pointer), VST_VENDOR_BUFFER_SIZE, "YASB contributors");
        return 1;
    case VST_EFFECT_OPCODE_PRODUCT_NAME:
        if (pointer) strcpy_s(static_cast<char*>(pointer), VST_PRODUCT_BUFFER_SIZE, "YASB Media Processor");
        return 1;
    case VST_EFFECT_OPCODE_VENDOR_VERSION: return 1;
    case VST_EFFECT_OPCODE_VST_VERSION: return 2400;
    default: return 0;
    }
}

intptr_t VST_FUNCTION_INTERFACE control(vst_effect* effect, VST_EFFECT_OPCODE opcode, std::int32_t index,
                                       intptr_t value, void* pointer, float option) {
    auto& plugin = owner(effect);
    if (opcode == VST_EFFECT_OPCODE_DESTROY) {
        plugin.closing.store(true);
        if (plugin.client) plugin.client->stop(); // Join before freeing; no control mutex held.
        delete &plugin; return 0;
    }
    intptr_t result;
    bool latency_changed;
    bool start_client = false;
    vst_host_callback callback = nullptr;
    Bootstrap binding;
    {
        std::lock_guard<std::mutex> lock(plugin.control_mutex); // Never called from process().
        result = locked_control(effect, opcode, index, value, pointer, option);
        // Do not notify on borrowed chunk results, teardown/suspend or arbitrary
        // dispatch. A reentrant host destroy must leave no dangling result data.
        const bool may_notify = (opcode == VST_EFFECT_OPCODE_CUSTOM && index == status_opcode && result == 1) || (opcode == VST_EFFECT_OPCODE_18 && result == 1) ||
            opcode == VST_EFFECT_OPCODE_SET_SAMPLE_RATE || (opcode == VST_EFFECT_OPCODE_SUSPEND && value != 0);
        latency_changed = may_notify && delay_locked(plugin);
        callback = plugin.host_callback;
        if (plugin.configured && !plugin.client_started) {
            plugin.client_started = true; start_client = true; binding = plugin.binding;
        }
    }
    if (start_client) {
        try { plugin.client = std::make_unique<ResidentClient>(binding, ClientHooks{&plugin, read_client_status, client_submit, client_connection}); }
        catch (...) { plugin.transport_error.store(ERROR_NOT_ENOUGH_MEMORY); plugin.transport_state.store(3); }
    }
    // Reentrant host queries are safe: no plugin/control lock is held here.
    if (latency_changed) callback(effect, VST_HOST_OPCODE_0D, 0, 0, nullptr, 0);
    // No owner/effect access: the callback above may have destroyed them.
    return result;
}
}

extern "C" __declspec(dllexport) VST_ENTRYPOINT {
    if (!callback || !callback(nullptr, VST_HOST_OPCODE_01, 0, 0, nullptr, 0)) return nullptr;
    try {
        auto* plugin = new Plugin(callback);
        auto& effect = plugin->effect;
        effect.magic_number = 0x56737450;
        effect.control = control;
        effect.process = accumulate;
        effect.process_float = process;
        effect.set_parameter = set_parameter;
        effect.get_parameter = get_parameter;
        effect.num_programs = 1;
        effect.num_inputs = effect.num_outputs = 2;
        effect.flags = 16 | 32; // Float replacing and full-state program chunks.
        effect._unknown_float_00 = 1;
        effect.effect_internal = plugin;
        effect.unique_id = 0x59445350;
        effect.version = 1;
        return &effect;
    } catch (...) {
        return nullptr;
    }
}
