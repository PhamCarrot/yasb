// Offline host and signal fixtures; no audio devices or Windows audio APIs.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <thread>
#include <vector>
#include <string_view>
#include <memory>
#include <string>
#include <fstream>
#include <filesystem>
#include "../../src/core/widgets/services/media/native/transport.h"
#include "../../src/core/widgets/services/media/native/vendor/xaymar-vst2/vst.h"
#include "../../src/core/widgets/services/media/native/processor.h"

using namespace yasb::dsp;
void native_require(bool value, int line) { if (!value) throw std::runtime_error("Native DSP assertion failed at line " + std::to_string(line)); }
#define require(value) ::native_require((value), __LINE__)
std::atomic<unsigned> latency_notifications{0};
bool destroy_on_latency = false;
vst_effect* destroyed_effect = nullptr;
DWORD host_thread = GetCurrentThreadId();
intptr_t host(vst_effect* effect, VST_HOST_OPCODE opcode, int32_t, int64_t, void*, float) {
    if (opcode == VST_HOST_OPCODE_0D) {
        require(effect != nullptr && effect->delay >= 0 && effect->delay < 1024);
        require(GetCurrentThreadId() == host_thread);
        if (destroy_on_latency) {
            destroy_on_latency = false; destroyed_effect = effect;
            effect->control(effect, VST_EFFECT_OPCODE_DESTROY, 0, 0, nullptr, 0);
            latency_notifications.fetch_add(1); return 1;
        }
        Status status;
        require(effect->control(effect, VST_EFFECT_OPCODE_CUSTOM, status_opcode, sizeof(status), &status, 0) == 1);
        latency_notifications.fetch_add(1);
        return 1;
    }
    return opcode == VST_HOST_OPCODE_01 ? 2400 : 0;
}
struct Host {
    HMODULE library;
    vst_effect* effect;
    explicit Host(const wchar_t* path, float rate = 48000) {
        library = LoadLibraryW(path);
        require(library != nullptr);
        using Entry = vst_effect*(*)(vst_host_callback);
        Entry entry = nullptr;
        FARPROC address = GetProcAddress(library, "VSTPluginMain");
        static_assert(sizeof(address) == sizeof(entry));
        std::memcpy(&entry, &address, sizeof(entry));
        require(entry != nullptr && entry(nullptr) == nullptr);
        effect = entry(host);
        require(effect && effect->magic_number == 0x56737450 && effect->num_inputs == 2 && effect->num_outputs == 2);
        require(effect->num_params == 0 && (effect->flags & (16 | 32)) == (16 | 32));
        call(VST_EFFECT_OPCODE_CREATE);
        call(VST_EFFECT_OPCODE_SET_SAMPLE_RATE, 0, 0, nullptr, rate);
        call(VST_EFFECT_OPCODE_SET_BLOCK_SIZE, 0, 1024);
        call(VST_EFFECT_OPCODE_SUSPEND, 0, 1);
    }
    ~Host() { if (effect && effect != destroyed_effect) { call(VST_EFFECT_OPCODE_SUSPEND); call(VST_EFFECT_OPCODE_DESTROY); } FreeLibrary(library); }
    intptr_t call(VST_EFFECT_OPCODE opcode, int index = 0, intptr_t value = 0, void* pointer = nullptr, float option = 0) {
        return effect->control(effect, opcode, index, value, pointer, option);
    }
    bool set(Parameters& parameters) {
        return call(VST_EFFECT_OPCODE_18, 0, sizeof(parameters), &parameters) == 1;
    }
    Status status() {
        Status result;
        require(call(VST_EFFECT_OPCODE_CUSTOM, status_opcode, sizeof(result), &result) == 1);
        require(result.version == protocol && result.bytes == sizeof(Status) && result.instance && result.build);
        return result;
    }
    void render(const std::vector<float>& left, const std::vector<float>& right,
                std::vector<float>& out_left, std::vector<float>& out_right, unsigned block = 256) {
        for (unsigned offset = 0; offset < left.size(); offset += block) {
            const float* inputs[] = {left.data() + offset, right.data() + offset};
            float* outputs[] = {out_left.data() + offset, out_right.data() + offset};
            effect->process_float(effect, inputs, outputs, static_cast<int>(std::min(block, unsigned(left.size()) - offset)));
        }
    }
};

void resident_case(Host& plugin, const wchar_t* path, double seconds, bool change_rate, bool stop_render = false, bool stoppable = false) {
    Bootstrap binding;
    std::ifstream input(std::filesystem::path(path), std::ios::binary);
    require(bool(input.read(reinterpret_cast<char*>(&binding), sizeof(binding))) && input.peek() == EOF);
    require(plugin.call(VST_EFFECT_OPCODE_18, 0, sizeof(binding), &binding) == 1);
    const auto start = GetTickCount64();
    std::vector<float> left(960, .01f), right(960, -.02f), out_left(960), out_right(960);
    bool changed = false;
    while (GetTickCount64() - start < static_cast<ULONGLONG>(seconds * 1000)) {
        if (stoppable && std::filesystem::exists(std::filesystem::path(std::wstring(path) + L".stop"))) break;
        if (!stop_render || GetTickCount64() - start < 500) plugin.render(left, right, out_left, out_right);
        if (change_rate && !changed && GetTickCount64() - start >= 500) {
            plugin.call(VST_EFFECT_OPCODE_SUSPEND);
            plugin.call(VST_EFFECT_OPCODE_SET_SAMPLE_RATE, 0, 0, nullptr, 96000);
            plugin.call(VST_EFFECT_OPCODE_SUSPEND, 0, 1); changed = true;
        }
        plugin.status(); // Host-owned dispatch can negotiate deferred latency.
        Sleep(20);
    }
    auto status = plugin.status();
    std::printf("{\"pid\":%u,\"accepted\":%llu,\"applied\":%llu,\"fingerprint\":%llu,\"frames\":%llu,\"epoch\":%llu,\"transport\":%u}\n",
        status.process_id, status.accepted_revision, status.applied_revision, status.applied_fingerprint,
        status.processed_frames, status.stream_epoch, status.transport_state);
}

void resident_destroy_case(Host& plugin, const wchar_t* path) {
    Bootstrap binding;
    std::ifstream input(std::filesystem::path(path), std::ios::binary);
    require(bool(input.read(reinterpret_cast<char*>(&binding), sizeof(binding))) && input.peek() == EOF);
    require(plugin.call(VST_EFFECT_OPCODE_18, 0, sizeof(binding), &binding) == 1);
    std::vector<float> left(960, .01f), right(960, -.02f), out_left(960), out_right(960);
    bool pending = false;
    const auto start = GetTickCount64();
    // No host dispatch while the resident worker changes latency. GET_CHUNK
    // must keep its borrowed result alive and leave notification pending.
    while (GetTickCount64() - start < 4000) {
        plugin.render(left, right, out_left, out_right);
        void* data = nullptr;
        const auto bytes = plugin.call(VST_EFFECT_OPCODE_17, 0, 0, &data);
        require(bytes == sizeof(Bootstrap) && data && latency_notifications.load() == 0);
        Bootstrap saved; std::memcpy(&saved, data, sizeof(saved));
        if (saved.initial.dynamics) { pending = true; break; }
        Sleep(20);
    }
    require(pending);
    plugin.call(VST_EFFECT_OPCODE_SUSPEND); // Quiesce audio, but do not notify.
    require(latency_notifications.load() == 0);
    destroy_on_latency = true;
    const auto before = GetTickCount64();
    const auto status = plugin.status(); // Callback synchronously DESTROYs.
    require(status.host_latency_pending == 1 && destroyed_effect == plugin.effect);
    require(latency_notifications.load() == 1 && GetTickCount64() - before < 1000);
    plugin.effect = nullptr;
    std::printf("{\"destroyed_on_host_thread\":true,\"notifications\":1,\"borrowed_chunk_survived\":true}\n");
}

void preamp_case(Host& plugin, float db, bool bypassed) {
    Parameters parameters; parameters.revision = 1; parameters.preamp_db = db; parameters.flags = bypassed ? bypass : 0;
    require(plugin.set(parameters));
    std::vector<float> left(4096, .25f), right(4096, -.75f), out_left(4096), out_right(4096);
    plugin.render(left, right, out_left, out_right);
    require(plugin.status().settled_revision == 1);
    std::printf("{\"left\":%.12g,\"right\":%.12g}\n", out_left.back(), out_right.back());
}

// Deliberately hostile/stalled local clients against the owned test broker.
// This duplicate wire header is an independent external-peer fixture.
struct RawHeader {
    std::uint32_t magic_number = magic, version = protocol, bytes = sizeof(RawHeader), op = 1;
    std::uint64_t sequence = 0;
    Key config{}, endpoint{}; Id instance{};
    std::uint64_t stream_epoch = 0, connection_epoch = 7;
};
static_assert(sizeof(RawHeader) == 120);
void raw_peer_case(Host& plugin, const wchar_t* path, std::wstring_view mode) {
    Bootstrap binding;
    std::ifstream input(std::filesystem::path(path), std::ios::binary);
    require(bool(input.read(reinterpret_cast<char*>(&binding), sizeof(binding))));
    std::wstring name = L"\\\\.\\pipe\\YASB.MediaDSP.v3.";
    constexpr wchar_t hex[] = L"0123456789abcdef";
    for (auto value : binding.installation) { name += hex[value >> 4]; name += hex[value & 15]; }
    std::vector<HANDLE> pipes;
    const unsigned count = mode == L"raw-stall" ? 16 : 1;
    for (unsigned i = 0; i < count; ++i) {
        HANDLE pipe = INVALID_HANDLE_VALUE;
        const auto start = GetTickCount64();
        while (pipe == INVALID_HANDLE_VALUE && GetTickCount64() - start < 1500) {
            pipe = CreateFileW(name.c_str(), FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES |
                FILE_WRITE_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE, 0, nullptr, OPEN_EXISTING,
                SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
            if (pipe == INVALID_HANDLE_VALUE) Sleep(10);
        }
        require(pipe != INVALID_HANDLE_VALUE); pipes.push_back(pipe);
        DWORD pipe_mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
        require(SetNamedPipeHandleState(pipe, &pipe_mode, nullptr, nullptr) != FALSE);
    }
    std::ofstream(std::filesystem::path(std::wstring(path) + L".ready")) << "ready";
    if (mode == L"raw-stall") Sleep(2700);
    else {
        std::array<unsigned char, 2048> bytes{};
        RawHeader header; const Status status = plugin.status();
        header.config = binding.config; header.endpoint = binding.endpoint;
        header.instance = status.instance_uuid; header.stream_epoch = status.stream_epoch;
        header.bytes = sizeof(header) + sizeof(status);
        std::memcpy(bytes.data(), &header, sizeof(header));
        std::memcpy(bytes.data() + sizeof(header), &status, sizeof(status));
        DWORD sent = 0;
        const DWORD length = mode == L"raw-truncated" ? 4 : mode == L"raw-oversized" ? 1025 : header.bytes;
        require(WriteFile(pipes[0], bytes.data(), length, &sent, nullptr) && sent == length);
        if (mode == L"raw-replay" || mode == L"raw-epoch" || mode == L"raw-response-stall") {
            // Receive hello ACK and first query, bounded independently of broker.
            for (unsigned packet = 0; packet < 2; ++packet) {
                DWORD received = 0; const auto start = GetTickCount64();
                while (!ReadFile(pipes[0], bytes.data(), static_cast<DWORD>(bytes.size()), &received, nullptr)) {
                    require(GetLastError() == ERROR_NO_DATA && GetTickCount64() - start < 1500); Sleep(5);
                }
                require(received >= sizeof(RawHeader));
            }
            std::memcpy(&header, bytes.data(), sizeof(header));
            if (mode == L"raw-response-stall") Sleep(2300);
            else {
                if (mode == L"raw-replay") header.sequence = 0;
                else ++header.connection_epoch;
                header.op = 5; header.bytes = sizeof(header) + sizeof(status);
                std::memcpy(bytes.data(), &header, sizeof(header));
                std::memcpy(bytes.data() + sizeof(header), &status, sizeof(status));
                require(WriteFile(pipes[0], bytes.data(), header.bytes, &sent, nullptr) && sent == header.bytes);
            }
        }
        bool closed = false; const auto start = GetTickCount64();
        while (!closed && GetTickCount64() - start < 1500) {
            DWORD received = 0;
            if (!ReadFile(pipes[0], bytes.data(), static_cast<DWORD>(bytes.size()), &received, nullptr)) {
                const auto error = GetLastError();
                closed = error == ERROR_BROKEN_PIPE || error == ERROR_PIPE_NOT_CONNECTED;
                require(closed || error == ERROR_NO_DATA);
            }
            if (!closed) Sleep(5);
        }
        require(closed);
    }
    for (auto pipe : pipes) CloseHandle(pipe);
    std::printf("{\"closed\":true,\"count\":%u}\n", count);
}

void protocol_case(Host& plugin) {
    Parameters parameters;
    require(!plugin.set(parameters));
    parameters.revision = 1;
    require(plugin.set(parameters));
    require(plugin.status().accepted_revision == 1 && plugin.status().applied_revision == 0);
    for (int invalid = 0; invalid < 8; ++invalid) {
        Parameters bad = parameters;
        bad.revision = 2;
        switch (invalid) {
        case 0: bad.gains[4] = std::numeric_limits<float>::quiet_NaN(); break;
        case 1: bad.gains[4] = 13; break;
        case 2: bad.balance = std::numeric_limits<float>::infinity(); break;
        case 3: bad.balance = -1.01f; break;
        case 4: bad.version++; break;
        case 5: bad.magic_number++; break;
        case 6: bad.flags = 16; break;
        case 7: bad.preamp_db = std::numeric_limits<float>::quiet_NaN(); break;
        }
        require(!plugin.set(bad));
        require(plugin.status().accepted_revision == 1);
    }
    require(!plugin.call(VST_EFFECT_OPCODE_18, 0, sizeof(parameters) - 1, &parameters));
    require(!plugin.call(VST_EFFECT_OPCODE_18, 0, sizeof(parameters), nullptr));
    parameters.revision = 2; parameters.gains[0] = 6; require(plugin.set(parameters));
    parameters.revision = 3; parameters.gains[0] = -6; require(plugin.set(parameters));
    Parameters stale = parameters; stale.revision = 2; require(!plugin.set(stale));
    void* chunk = nullptr;
    require(plugin.call(VST_EFFECT_OPCODE_17, 0, 0, &chunk) == sizeof(Parameters));
    require(chunk && std::memcmp(chunk, &parameters, sizeof(parameters)) == 0);
    std::vector<float> in(2048, .01f), out_left(2048), out_right(2048);
    plugin.effect->process_float(plugin.effect, nullptr, nullptr, 0);
    require(plugin.status().applied_revision == 0);
    plugin.render(in, in, out_left, out_right, 31);
    auto status = plugin.status();
    require(status.accepted_revision == 3 && status.applied_revision == 3 && status.settled_revision == 3);
    require(status.processed_frames == 2048);
    require(plugin.call(VST_EFFECT_OPCODE_VST_VERSION) == 2400);
    std::printf("{\"accepted\":3,\"applied\":3,\"settled\":3,\"frames\":2048,\"build\":\"%llx\"}\n", status.build);
}

void eq_case(Host& plugin, float rate, unsigned band, double frequency, float gain) {
    Parameters parameters; parameters.revision = 1; parameters.gains.at(band) = gain;
    require(plugin.set(parameters));
    const unsigned frames = static_cast<unsigned>(rate * 2);
    std::vector<float> in_left(frames), in_right(frames), out_left(frames), out_right(frames);
    constexpr double test_pi = 3.14159265358979323846;
    for (unsigned i = 0; i < frames; ++i) in_left[i] = static_cast<float>(.01 * std::sin(2 * test_pi * frequency * i / rate));
    plugin.render(in_left, in_right, out_left, out_right);
    double input_power = 0, output_power = 0;
    for (unsigned i = frames / 2; i < frames; ++i) {
        input_power += double(in_left[i]) * in_left[i];
        output_power += double(out_left[i]) * out_left[i];
        require(out_right[i] == 0 && std::isfinite(out_left[i]));
    }
    auto status = plugin.status();
    require(status.applied_revision == 1 && status.settled_revision == 1 && status.processed_frames == frames);
    std::printf("{\"ratio\":%.12g,\"frames\":%u,\"rate\":%u}\n", std::sqrt(output_power / input_power), frames, status.sample_rate);
}

void matrix_case(Host& plugin, unsigned flags, float balance) {
    Parameters parameters; parameters.revision = 1; parameters.flags = flags; parameters.balance = balance;
    require(plugin.set(parameters));
    std::vector<float> left(4096, .25f), right(4096, -.75f), out_left(4096), out_right(4096);
    plugin.render(left, right, out_left, out_right, 63);
    std::printf("{\"left\":%.12g,\"right\":%.12g}\n", out_left.back(), out_right.back());
}

void lifecycle_case(Host& plugin) {
    Parameters parameters; parameters.revision = 1; parameters.balance = 1;
    require(plugin.set(parameters));
    // Reconfiguration while running is rejected, preserving the active format.
    plugin.call(VST_EFFECT_OPCODE_SET_SAMPLE_RATE, 0, 0, nullptr, 96000);
    require(plugin.status().sample_rate == 48000);
    plugin.call(VST_EFFECT_OPCODE_SUSPEND);
    plugin.call(VST_EFFECT_OPCODE_SET_SAMPLE_RATE, 0, 0, nullptr, 32000);
    plugin.call(VST_EFFECT_OPCODE_SUSPEND, 0, 1);
    require(plugin.status().processing == 2 && plugin.status().sample_rate == 0);
    std::vector<float> left(64, .25f), right(64, -.75f), out_left(64), out_right(64);
    plugin.render(left, right, out_left, out_right);
    require(out_left == left && out_right == right && plugin.status().processed_frames == 0);
    plugin.call(VST_EFFECT_OPCODE_SUSPEND);
    plugin.call(VST_EFFECT_OPCODE_SET_SAMPLE_RATE, 0, 0, nullptr, 96000);
    plugin.call(VST_EFFECT_OPCODE_SUSPEND, 0, 1);
    require(plugin.status().processing == 1 && plugin.status().applied_revision == 0);
    plugin.render(left, right, out_left, out_right);
    require(plugin.status().applied_revision == 1 && plugin.status().sample_rate == 96000);
    std::printf("{\"unsupported_bypasses\":true,\"recovered_rate\":96000}\n");
}

void mailbox_case() {
    struct Message { std::uint64_t revision = 0; std::array<std::uint64_t, 32> check{}; };
    Latest<Message> latest;
    std::atomic<bool> done{false};
    constexpr std::uint64_t count = 250000;
    std::thread writer([&] {
        for (std::uint64_t revision = 1; revision <= count; ++revision) {
            Message message; message.revision = revision; message.check.fill(revision ^ 0x123456789abcdef0);
            latest.publish(message);
        }
        done.store(true, std::memory_order_release);
    });
    Message message; std::uint64_t previous = 0;
    while (!done.load(std::memory_order_acquire) || previous < count) {
        if (!latest.take(message)) { std::this_thread::yield(); continue; }
        require(message.revision > previous);
        for (auto check : message.check) require(check == (message.revision ^ 0x123456789abcdef0));
        previous = message.revision;
    }
    writer.join();
    std::printf("{\"latest\":%llu,\"bounded_slots\":3}\n", previous);
}

void concurrent_case(Host& plugin) {
    std::atomic<bool> done{false};
    std::thread writer([&] {
        for (std::uint64_t revision = 1; revision <= 10000; ++revision) {
            Parameters parameters; parameters.revision = revision;
            parameters.gains.fill(revision % 2 ? 12.f : -12.f);
            require(plugin.set(parameters));
        }
        done.store(true, std::memory_order_release);
    });
    std::vector<float> left(256, .01f), right(256, -.02f), out_left(256), out_right(256);
    do {
        plugin.render(left, right, out_left, out_right);
        auto status = plugin.status();
        require(status.applied_revision <= status.accepted_revision && status.settled_revision <= status.applied_revision);
        for (float value : out_left) require(std::isfinite(value));
        for (float value : out_right) require(std::isfinite(value));
    } while (!done.load(std::memory_order_acquire));
    writer.join();
    for (int i = 0; i < 8; ++i) plugin.render(left, right, out_left, out_right);
    auto status = plugin.status();
    require(status.accepted_revision == 10000 && status.applied_revision == 10000 && status.settled_revision == 10000);
    std::printf("{\"latest_revision\":10000,\"frames\":%llu}\n", status.processed_frames);
}

void finite_in_place_case(Host& plugin) {
    Parameters parameters; parameters.revision = 1; parameters.gains.fill(12);
    require(plugin.set(parameters));
    // A FLT_MAX impulse needs >2 seconds to decay through the lowest boosted
    // pole. Keep the same absolute tail bound and allow four seconds of signal.
    std::vector<float> left(192000, 0), right(192000, 0);
    left[0] = .01f; right[0] = -.02f;
    left[3000] = std::numeric_limits<float>::quiet_NaN();
    right[3000] = std::numeric_limits<float>::infinity();
    left[6000] = std::numeric_limits<float>::max();
    plugin.render(left, right, left, right, 127);
    for (float value : left) require(std::isfinite(value));
    for (float value : right) require(std::isfinite(value));
    require(std::abs(left.back()) < 1e-10 && std::abs(right.back()) < 1e-10);
    std::printf("{\"in_place\":true,\"finite_after_invalid_input\":true}\n");
}

void accumulating_case(Host& plugin) {
    std::vector<float> left(64, .25f), right(64, -.75f), out_left(64, 1), out_right(64, -1);
    const float* inputs[] = {left.data(), right.data()};
    float* outputs[] = {out_left.data(), out_right.data()};
    plugin.effect->process(plugin.effect, inputs, outputs, 64);
    require(out_left.back() == 1.25f && out_right.back() == -1.75f);
    std::printf("{\"legacy_accumulates\":true}\n");
}

void compressor_case(float rate, unsigned mode, double amplitude) {
    Compressor compressor;
    compressor.configure(dynamics_tuning(mode, rate));
    double first = 0, last = 0;
    for (unsigned frame = 0; frame < static_cast<unsigned>(rate * 4); ++frame) {
        double left = amplitude, right = amplitude;
        compressor.process(left, right);
        if (!frame) first = left;
        last = left;
        require(left == right && std::isfinite(left));
    }
    std::printf("{\"first\":%.12g,\"settled\":%.12g}\n", first, last);
}

void limiter_case(float rate) {
    Limiter limiter;
    limiter.configure(dynamics_tuning(1, rate));
    constexpr double ceiling = .8912509381337456;
    int first = -1;
    double first_left = 0, first_right = 0;
    for (unsigned frame = 0; frame < unsigned(rate / 2); ++frame) {
        double left = frame == 0 ? 2 : 0, right = frame == 0 ? 1 : 0;
        limiter.process(left, right, ceiling);
        require(std::abs(left) <= ceiling && std::abs(right) <= ceiling);
        if (first < 0 && left != 0) { first = frame; first_left = left; first_right = right; }
    }
    require(first == static_cast<int>(limiter.latency()));
    std::printf("{\"delay\":%d,\"left\":%.12g,\"right\":%.12g}\n", first, first_left, first_right);
}

void dynamics_case(Host& plugin, unsigned mode, unsigned block, double amplitude = .5) {
    Parameters parameters; parameters.revision = 1; parameters.dynamics = mode;
    require(plugin.set(parameters));
    constexpr unsigned frames = 96000;
    std::vector<float> input(frames), out_left(frames), out_right(frames);
    constexpr double test_pi = 3.14159265358979323846;
    for (unsigned i = 0; i < frames; ++i) input[i] = static_cast<float>(amplitude * std::sin(2 * test_pi * 1000 * i / 48000));
    plugin.render(input, input, out_left, out_right, block);
    double in_power = 0, out_power = 0;
    for (unsigned i = frames - 24000; i < frames; ++i) {
        in_power += double(input[i]) * input[i]; out_power += double(out_left[i]) * out_left[i];
        require(out_left[i] == out_right[i] && std::abs(out_left[i]) <= .89125094);
    }
    auto status = plugin.status();
    require(status.dynamics == mode && status.latency_frames == (mode ? 239u : 0u));
    require(plugin.effect->delay == (mode ? 239 : 0));
    require(latency_notifications.load() == (mode ? 1u : 0u));
    std::printf("{\"attenuation_db\":%.12g,\"latency\":%u}\n", 10 * std::log10(out_power / in_power), status.latency_frames);
}

void bypass_case(Host& plugin) {
    Parameters parameters; parameters.revision = 1; parameters.dynamics = 2; parameters.flags = bypass;
    parameters.gains.fill(12); parameters.balance = 1;
    require(plugin.set(parameters));
    std::vector<float> left(1234, .25f), right(1234, -.75f), out_left(1234), out_right(1234);
    plugin.render(left, right, out_left, out_right, 17);
    require(out_left == left && out_right == right);
    auto status = plugin.status();
    require(status.latency_frames == 0 && status.flags == bypass && status.settled_revision == 1 && status.processing == 3);
    parameters.revision = 2; parameters.flags = 0;
    require(plugin.set(parameters));
    plugin.render(left, right, out_left, out_right, 17);
    // No limiter history advanced while bypassed: first239samples remain empty.
    for (unsigned frame = 0; frame < 239; ++frame) require(out_left[frame] == 0 && out_right[frame] == 0);
    require(plugin.status().latency_frames == 239);
    std::printf("{\"bypass_immediate\":true,\"history_frozen\":true}\n");
}

void limiter_ceiling_switch_case(bool lowering) {
    Limiter limiter; limiter.configure(dynamics_tuning(1, 48000));
    const double before = lowering ? .9885530946569389 : .8912509381337456;
    const double after = lowering ? .8912509381337456 : .9885530946569389;
    double left = 0, right = 0;
    for (unsigned frame = 0; frame <= 239; ++frame) {
        left = frame ? 0 : 2; right = frame ? 0 : 1;
        limiter.process(left, right, frame ? after : before);
    }
    std::printf("{\"left\":%.12g,\"right\":%.12g}\n", left, right);
}

void spectrum_case(unsigned mode) {
    auto spectrum = std::make_unique<Spectrum>(); spectrum->configure(48000);
    Observation observation; unsigned count = 0;
    for (unsigned frame = 0; frame < analysis_size + analysis_hop; ++frame) {
        const double left = mode == 3 ? .1 : .1 * std::sin(6.283185307179586 * 128 * frame / analysis_size);
        const double right = mode == 1 ? 0 : mode == 2 ? -left : left;
        if (spectrum->push(left, right)) { observation = spectrum->analyze(); ++count; }
    }
    double useful = 0; for (double power : observation.power) useful += power;
    std::printf("{\"total\":%.12g,\"useful\":%.12g,\"observations\":%u}\n", observation.total, useful, count);
}

void adaptive_scalars_case() {
    std::printf("{\"weights\":[%.12g,%.12g,%.12g,%.12g,%.12g,%.12g],\"bass\":[%.12g,%.12g,%.12g],\"correction\":[",
        correction_weight(50), correction_weight(100), correction_weight(10000), correction_weight(16000),
        correction_weight(std::sqrt(50.0 * 100)), correction_weight(std::sqrt(10000.0 * 16000)),
        bass_preference(80), bass_preference(std::sqrt(80.0 * 250)), bass_preference(250));
    const std::array<double, 6> deviations{2.5, 5, 10, -2.5, -5, -10};
    for (unsigned i = 0; i < deviations.size(); ++i) std::printf("%s%.12g", i ? "," : "", shaped_correction(deviations[i]));
    std::printf("]}\n");
}

std::vector<float> material(unsigned frames, double rate = 48000) {
    std::vector<float> result(frames);
    std::array<double, analysis_bands> amplitude{}, angle{};
    for (unsigned band = 0; band < analysis_bands; ++band) {
        const double frequency = 1000 * std::exp2((double(band) - 14) / 3);
        const double coloration = frequency < 250 ? 12 : frequency > 4000 ? -6 : 0;
        amplitude[band] = .001 * std::pow(10, (coloration - 2.5 * std::log2(frequency / 1000)) / 20);
        angle[band] = 6.283185307179586 * frequency / rate;
    }
    for (unsigned frame = 0; frame < frames; ++frame) {
        double value = 0;
        for (unsigned band = 0; band < analysis_bands; ++band) value += amplitude[band] * std::sin(angle[band] * frame + .37 * band);
        result[frame] = static_cast<float>(value);
    }
    return result;
}

void print_powers(const char* name, const Observation& observation) {
    std::printf("\"%s\":[", name);
    for (unsigned band = 0; band < analysis_bands; ++band) std::printf("%s%.12g", band ? "," : "", observation.power[band]);
    std::printf("]");
}

void adaptive_learning_case(std::wstring_view mode) {
    auto engine = std::make_unique<Adaptive>(); engine->configure(48000); engine->enable(true);
    auto input_spectrum = std::make_unique<Spectrum>(); input_spectrum->configure(48000);
    auto output_spectrum = std::make_unique<Spectrum>(); output_spectrum->configure(48000);
    Observation input_observation, output_observation;
    constexpr unsigned frames = 576000;
    const auto colored = mode == L"colored" || mode == L"reset" ? material(frames) : std::vector<float>();
    for (unsigned frame = 0; frame < frames; ++frame) {
        double value = 0;
        if (!colored.empty()) value = colored[frame];
        else if (mode == L"dc") value = .1;
        else if (mode == L"low") value = .001 * std::sin(6.283185307179586 * 39.3725328092 * frame / 48000);
        else if (mode == L"quiet") value = .0001 * std::sin(6.283185307179586 * 1000 * frame / 48000);
        else if (mode == L"dc-tone") value = .1 + .001 * std::sin(6.283185307179586 * 1000 * frame / 48000);
        double left = value, right = -value;
        if (input_spectrum->push(left, right)) input_observation = input_spectrum->analyze();
        engine->process(left, right);
        require(std::isfinite(left) && std::isfinite(right));
        if (output_spectrum->push(left, right)) output_observation = output_spectrum->analyze();
    }
    const auto admitted = engine->admitted(), observed = engine->observed();
    for (double gain : engine->gains()) require(gain >= -8 && gain <= 4);
    require(engine->makeup() >= -6 && engine->makeup() <= 3);
    if (mode == L"reset") {
        engine->enable(false);
        for (unsigned frame = 0; frame < 480000; ++frame) { double left = 0, right = 0; engine->process(left, right); }
        for (double gain : engine->gains()) require(gain == 0);
        require(engine->makeup() == 0 && engine->admitted() == admitted);
        engine->enable(true);
        require(engine->admitted() == 0 && engine->observed() == 0);
        std::printf("{\"decayed_neutral\":true,\"reenable_resets\":true}\n"); return;
    }
    std::printf("{\"admitted\":%llu,\"observations\":%llu,\"makeup\":%.12g,", admitted, observed, engine->makeup());
    print_powers("input", input_observation); std::printf(","); print_powers("output", output_observation); std::printf("}\n");
}

void adaptive_partition_case(Host& plugin, unsigned block, float manual_gain, float rate = 48000) {
    Parameters parameters; parameters.revision = 1; parameters.flags = adaptive; parameters.gains.fill(manual_gain);
    require(plugin.set(parameters));
    const unsigned frames = static_cast<unsigned>(8 * rate);
    const auto input = material(frames, rate);
    std::vector<float> left(frames), right(frames);
    plugin.render(input, input, left, right, block);
    std::uint64_t hash = 14695981039346656037ULL;
    for (unsigned frame = 0; frame < frames; ++frame) {
        require(std::isfinite(left[frame]) && std::abs(left[frame]) <= static_cast<float>(.9885530946569389) && left[frame] == right[frame]);
        std::uint32_t bits = 0; std::memcpy(&bits, &left[frame], sizeof(bits));
        hash = (hash ^ bits) * 1099511628211ULL;
    }
    auto status = plugin.status();
    require(status.latency_frames == static_cast<unsigned>(std::floor(.005 * rate)) - 1 && status.flags == adaptive && status.adaptive_admitted > 0);
    std::printf("{\"hash\":\"%llx\",\"observed\":%llu,\"admitted\":%llu,\"makeup\":%.9g}\n",
        hash, status.adaptive_observations, status.adaptive_admitted, status.adaptive_makeup);
}

void adaptive_safety_case(Host& plugin) {
    Parameters parameters; parameters.revision = 1; parameters.flags = adaptive;
    require(plugin.set(parameters));
    std::vector<float> left(48000, 2), right(48000, 1), out_left(48000), out_right(48000);
    plugin.render(left, right, out_left, out_right);
    // The wire samples are float32. Compare against the representable threshold,
    // not a rounded decimal double that lies below that float (0.9885531068...).
    constexpr float safety_ceiling = .9885530946569389f;
    for (unsigned frame = 0; frame < 48000; ++frame) {
        require(std::abs(out_left[frame]) <= safety_ceiling && std::abs(out_right[frame]) <= safety_ceiling);
        if (frame < 239) require(out_left[frame] == 0 && out_right[frame] == 0);
    }
    require(plugin.status().adaptive_observations > 0 && plugin.status().adaptive_admitted == 0);
    std::printf("{\"left\":%.12g,\"right\":%.12g,\"delay\":239}\n", out_left[239], out_right[239]);
}

int wmain(int argc, wchar_t** argv) {
    try {
        require(argc >= 3);
        const auto mode = std::wstring_view(argv[2]);
        if (mode == L"mailbox") { mailbox_case(); return 0; }
        const float rate = mode == L"eq" || mode == L"adaptive-rate" ? std::wcstof(argv[3], nullptr) : 48000.f;
        Host plugin(argv[1], rate);
        if (mode == L"protocol") protocol_case(plugin);
        else if (mode == L"eq") eq_case(plugin, rate, std::wcstoul(argv[4], nullptr, 10), std::wcstod(argv[5], nullptr), std::wcstof(argv[6], nullptr));
        else if (mode.substr(0, 4) == L"raw-") raw_peer_case(plugin, argv[3], mode);
        else if (mode == L"resident-destroy") resident_destroy_case(plugin, argv[3]);
        else if (mode == L"preamp") preamp_case(plugin, std::wcstof(argv[3], nullptr), std::wcstoul(argv[4], nullptr, 10) != 0);
        else if (mode == L"matrix") matrix_case(plugin, std::wcstoul(argv[3], nullptr, 10), std::wcstof(argv[4], nullptr));
        else if (mode == L"lifecycle") lifecycle_case(plugin);
        else if (mode == L"concurrent") concurrent_case(plugin);
        else if (mode == L"finite-in-place") finite_in_place_case(plugin);
        else if (mode == L"accumulating") accumulating_case(plugin);
        else if (mode == L"compressor") compressor_case(std::wcstof(argv[3], nullptr), std::wcstoul(argv[4], nullptr, 10), std::wcstod(argv[5], nullptr));
        else if (mode == L"limiter") limiter_case(std::wcstof(argv[3], nullptr));
        else if (mode == L"dynamics") dynamics_case(plugin, std::wcstoul(argv[3], nullptr, 10), std::wcstoul(argv[4], nullptr, 10));
        else if (mode == L"quiet-night") dynamics_case(plugin, 2, 256, .002);
        else if (mode == L"bypass") bypass_case(plugin);
        else if (mode == L"spectrum") spectrum_case(std::wcstoul(argv[3], nullptr, 10));
        else if (mode == L"adaptive-scalars") adaptive_scalars_case();
        else if (mode == L"adaptive-learning") adaptive_learning_case(argv[3]);
        else if (mode == L"adaptive-partition") adaptive_partition_case(plugin, std::wcstoul(argv[3], nullptr, 10), std::wcstof(argv[4], nullptr));
        else if (mode == L"limiter-switch") limiter_ceiling_switch_case(std::wcstoul(argv[3], nullptr, 10) != 0);
        else if (mode == L"adaptive-rate") adaptive_partition_case(plugin, 256, 0, rate);
        else if (mode == L"adaptive-safety") adaptive_safety_case(plugin);
        else if (mode == L"resident" || mode == L"resident-rate" || mode == L"resident-stop" || mode == L"resident-preview") resident_case(plugin, argv[3], std::wcstod(argv[4], nullptr), mode == L"resident-rate", mode == L"resident-stop", mode == L"resident-preview");
        else throw std::runtime_error("Unknown fixture");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
