// Copyright (c) YASB contributors. SPDX-License-Identifier: MIT
// Local, bounded, non-audio control. No Windows service or network listener.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <aclapi.h>
#include <bcrypt.h>
#include <sddl.h>
#include <algorithm>
#include <atomic>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include "transport.h"
#include "processor.h"

namespace yasb::dsp {
namespace {
constexpr unsigned max_peers = 16, max_frame = 1024;
constexpr DWORD client_access = FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES |
    FILE_WRITE_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
struct WinFailure { DWORD code; };
void checked(bool value) { if (!value) throw WinFailure{GetLastError()}; }
class Handle {
    HANDLE value_ = INVALID_HANDLE_VALUE;
public:
    Handle() = default;
    explicit Handle(HANDLE value) : value_(value) {}
    ~Handle() { reset(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value_(other.value_) { other.value_ = INVALID_HANDLE_VALUE; }
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) { reset(other.value_); other.value_ = INVALID_HANDLE_VALUE; }
        return *this;
    }
    void reset(HANDLE value = INVALID_HANDLE_VALUE) noexcept {
        if (value_ && value_ != INVALID_HANDLE_VALUE) CloseHandle(value_);
        value_ = value;
    }
    HANDLE get() const noexcept { return value_; }
    bool valid() const noexcept { return value_ && value_ != INVALID_HANDLE_VALUE; }
};
struct LocalMemory {
    void* value = nullptr;
    ~LocalMemory() { if (value) LocalFree(value); }
};
template<class T> bool nonzero(const T& value) noexcept {
    return std::any_of(value.begin(), value.end(), [](auto byte) { return byte != 0; });
}
bool random_bytes(void* bytes, unsigned size) noexcept {
    return BCryptGenRandom(nullptr, static_cast<PUCHAR>(bytes), size, BCRYPT_USE_SYSTEM_PREFERRED_RNG) >= 0;
}
std::string current_sid() {
    HANDLE raw = nullptr;
    checked(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw) != FALSE);
    Handle token(raw);
    alignas(TOKEN_USER) std::array<unsigned char, 256> buffer{};
    DWORD bytes = 0;
    checked(GetTokenInformation(token.get(), TokenUser, buffer.data(), static_cast<DWORD>(buffer.size()), &bytes) != FALSE);
    char* text = nullptr;
    checked(ConvertSidToStringSidA(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid, &text) != FALSE);
    LocalMemory memory{text};
    return text;
}
std::wstring pipe_name(const Id& installation) {
    std::wstring result = L"\\\\.\\pipe\\YASB.MediaDSP.v3.";
    constexpr wchar_t hex[] = L"0123456789abcdef";
    for (auto value : installation) { result += hex[value >> 4]; result += hex[value & 15]; }
    return result;
}
bool verified_owner(HANDLE pipe, const Bootstrap& bootstrap) noexcept {
    PSID expected = nullptr;
    if (!ConvertStringSidToSidA(bootstrap.controller_sid.data(), &expected)) return false;
    LocalMemory expected_memory{expected};
    PSID owner = nullptr; PSECURITY_DESCRIPTOR descriptor = nullptr;
    const DWORD result = GetSecurityInfo(pipe, SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION,
        &owner, nullptr, nullptr, nullptr, &descriptor);
    LocalMemory descriptor_memory{descriptor};
    if (result != ERROR_SUCCESS) { SetLastError(result); return false; }
    if (!owner || !EqualSid(owner, expected)) { SetLastError(ERROR_ACCESS_DENIED); return false; }
    return true;
}

enum class Op : std::uint32_t { hello = 1, hello_ack, set, query, status };
struct Header {
    std::uint32_t magic_number = magic, version = protocol, bytes = sizeof(Header);
    Op op = Op::hello;
    std::uint64_t sequence = 0;
    Key config{}, endpoint{};
    Id instance{};
    std::uint64_t stream_epoch = 0, connection_epoch = 0;
};
static_assert(sizeof(Header) == 120);
struct Packet {
    Header header{};
    std::array<unsigned char, max_frame - sizeof(Header)> payload{};
};
static_assert(sizeof(Packet) == max_frame);
enum class Io { idle, complete, closed };
Io read_packet(HANDLE pipe, Packet& packet) noexcept {
    DWORD bytes = 0;
    if (!ReadFile(pipe, &packet, sizeof(packet), &bytes, nullptr)) {
        return GetLastError() == ERROR_NO_DATA ? Io::idle : Io::closed;
    }
    const auto& h = packet.header;
    if (bytes < sizeof(Header) || bytes != h.bytes || bytes > max_frame || h.magic_number != magic || h.version != protocol)
        { SetLastError(ERROR_INVALID_DATA); return Io::closed; }
    return Io::complete;
}
Io write_packet(HANDLE pipe, const Packet& packet) noexcept {
    DWORD bytes = 0;
    if (!WriteFile(pipe, &packet, packet.header.bytes, &bytes, nullptr)) return Io::closed;
    if (bytes == 0) return Io::idle; // Message was NOT sent; retain exact packet/deadline.
    if (bytes == packet.header.bytes) return Io::complete;
    SetLastError(ERROR_INVALID_DATA); return Io::closed;
}
template<class T> void put(Packet& packet, const T& value) noexcept {
    static_assert(sizeof(T) <= max_frame - sizeof(Header));
    std::memcpy(packet.payload.data(), &value, sizeof(value));
    packet.header.bytes = sizeof(Header) + sizeof(T);
}
template<class T> bool get(const Packet& packet, T& value) noexcept {
    if (packet.header.bytes != sizeof(Header) + sizeof(T)) return false;
    std::memcpy(&value, packet.payload.data(), sizeof(value));
    return true;
}
Packet message(Op op, const Bootstrap& binding, const Status& status, std::uint64_t sequence, std::uint64_t epoch) noexcept {
    Packet result;
    result.header.op = op; result.header.sequence = sequence;
    result.header.config = binding.config; result.header.endpoint = binding.endpoint;
    result.header.instance = status.instance_uuid; result.header.stream_epoch = status.stream_epoch;
    result.header.connection_epoch = epoch;
    return result;
}
bool matches(const Header& a, const Header& b) noexcept {
    return a.config == b.config && a.endpoint == b.endpoint && a.instance == b.instance &&
        a.stream_epoch == b.stream_epoch && a.connection_epoch == b.connection_epoch;
}
bool valid_status(const Status& status, const Header& header) noexcept {
    if (status.version != protocol || status.bytes != sizeof(Status) || status.build != YASB_DSP_BUILD_ID ||
        status.instance_uuid != header.instance || status.stream_epoch != header.stream_epoch ||
        !nonzero(status.instance_uuid) || !status.stream_epoch || !status.process_id || status.host_latency_pending > 1 ||
        status.channels != 2 || status.processing > 3 || (status.flags & ~(mono | swap | adaptive | bypass)) ||
        status.dynamics > 2 || status.applied_revision > status.accepted_revision ||
        status.settled_revision > status.applied_revision || !std::isfinite(status.adaptive_makeup)) return false;
    for (float gain : status.adaptive_gains) if (!std::isfinite(gain)) return false;
    return status.processing == 2 ? status.sample_rate == 0 : supported_rate(status.sample_rate);
}

struct Desired {
    bool used = false;
    Bootstrap binding{};
    Parameters parameters{};
    std::uint64_t generation = 0;
};
struct Peer {
    Handle pipe;
    unsigned phase = 0; // listening, awaiting hello, active
    Header identity{};
    Status status{};
    Packet pending{};
    bool has_pending = false, in_flight = false;
    std::uint64_t next_sequence = 1, sent_sequence = 0, busy_fingerprint = 0;
    ULONGLONG deadline = 0, last_seen = 0;
};
struct SharedPeer {
    bool active = false;
    PeerReport report{};
    ULONGLONG last_seen = 0;
    std::uint64_t busy_fingerprint = 0;
};

class Broker {
    Bootstrap bootstrap_;
    std::wstring name_;
    LocalMemory security_;
    Handle stop_{CreateEventW(nullptr, TRUE, FALSE, nullptr)}, wake_{CreateEventW(nullptr, FALSE, FALSE, nullptr)};
    std::array<Peer, max_peers> peers_{};
    std::array<Desired, max_peers> desired_{};
    std::array<SharedPeer, max_peers> reports_{};
    std::mutex mutex_;
    std::thread thread_;
    std::atomic<bool> closing_{false};
#ifdef YASB_DSP_TEST_HOOKS
    std::atomic<bool> hold_dispatch_{false}, dispatch_held_{false};
#endif
    void reset(Peer& peer, unsigned index) noexcept {
        DisconnectNamedPipe(peer.pipe.get());
        Handle pipe = std::move(peer.pipe); peer = Peer{}; peer.pipe = std::move(pipe);
        std::lock_guard<std::mutex> lock(mutex_); reports_[index] = SharedPeer{};
    }
    Desired desired_locked(const Header& identity) {
        for (const auto& value : desired_) if (value.used && value.binding.config == identity.config && value.binding.endpoint == identity.endpoint) return value;
        return Desired{};
    }
    static SharedPeer snapshot(const Peer& peer) {
        SharedPeer value;
        value.active = peer.phase == 2;
        value.last_seen = peer.last_seen;
        value.busy_fingerprint = peer.busy_fingerprint;
        value.report.config = peer.identity.config; value.report.endpoint = peer.identity.endpoint;
        value.report.status = peer.status; value.report.connection_epoch = peer.identity.connection_epoch;
        return value;
    }
    void publish_report(unsigned index, const Peer& peer) {
        std::lock_guard<std::mutex> lock(mutex_); reports_[index] = snapshot(peer);
    }
    void run() noexcept {
        HANDLE events[] = {stop_.get(), wake_.get()};
        while (WaitForMultipleObjects(2, events, FALSE, 20) != WAIT_OBJECT_0) {
            for (unsigned index = 0; index < max_peers && !closing_.load(); ++index) {
                auto& peer = peers_[index];
                const auto now = GetTickCount64();
                if (peer.phase == 0) {
                    const BOOL connected = ConnectNamedPipe(peer.pipe.get(), nullptr);
                    const DWORD error = connected ? ERROR_PIPE_LISTENING : GetLastError();
                    if (error == ERROR_PIPE_CONNECTED) { peer.phase = 1; peer.deadline = now + 2000; }
                    else if (error != ERROR_PIPE_LISTENING) reset(peer, index);
                    continue;
                }
                if (peer.deadline && now >= peer.deadline) { reset(peer, index); continue; }
                Packet incoming;
                const auto read = read_packet(peer.pipe.get(), incoming);
                if (read == Io::closed) { reset(peer, index); continue; }
                if (read == Io::complete) {
                    Status status;
                    if (!get(incoming, status) || !valid_status(status, incoming.header)) { reset(peer, index); continue; }
                    if (peer.phase == 1) {
                        ULONG process = 0;
                        if (incoming.header.op != Op::hello || incoming.header.sequence || !incoming.header.connection_epoch ||
                            !GetNamedPipeClientProcessId(peer.pipe.get(), &process) || process != status.process_id) {
                            reset(peer, index); continue;
                        }
                        peer.identity = incoming.header; peer.status = status; peer.last_seen = now;
                        peer.pending.header = peer.identity; peer.pending.header.op = Op::hello_ack;
                        peer.pending.header.bytes = sizeof(Header); peer.has_pending = true;
                    } else {
                        if (!peer.in_flight || incoming.header.op != Op::status || incoming.header.sequence != peer.sent_sequence ||
                            !matches(incoming.header, peer.identity)) { reset(peer, index); continue; }
                        peer.status = status; peer.last_seen = now; peer.in_flight = false; peer.busy_fingerprint = 0;
                        peer.deadline = 0;
                    }
                }
                if (peer.phase == 2 && !peer.in_flight && !peer.has_pending) {
                    bool exhausted = false;
                    {
                        // Reserve the packet AND publish the latest status/busy fence
                        // atomically with intent publication/readback. No pipe I/O here.
                        std::lock_guard<std::mutex> lock(mutex_);
                        const Desired desired = desired_locked(peer.identity);
                        const auto wanted = desired.used ? fingerprint(desired.parameters) : 0;
                        peer.pending.header = peer.identity; peer.pending.header.sequence = peer.next_sequence;
                        peer.pending.header.op = Op::query; peer.pending.header.bytes = sizeof(Header);
                        if (desired.used && peer.status.accepted_fingerprint != wanted) {
                            exhausted = peer.status.accepted_revision == UINT64_MAX;
                            if (!exhausted) {
                                Parameters parameters = desired.parameters; parameters.revision = peer.status.accepted_revision + 1;
                                peer.pending.header.op = Op::set; put(peer.pending, parameters); peer.busy_fingerprint = wanted;
                            }
                        }
                        peer.has_pending = !exhausted; peer.deadline = now + 2000;
                        reports_[index] = snapshot(peer);
                    }
                    if (exhausted) { reset(peer, index); continue; }
                }
#ifdef YASB_DSP_TEST_HOOKS
                // Deterministic race fixture: reservation is visible before the
                // worker can send or reach its normal end-of-iteration publication.
                if (peer.has_pending && peer.pending.header.op == Op::set && hold_dispatch_.load()) {
                    dispatch_held_.store(true); continue;
                }
                dispatch_held_.store(false);
#endif
                if (peer.has_pending) {
                    const auto written = write_packet(peer.pipe.get(), peer.pending);
                    if (written == Io::closed) { reset(peer, index); continue; }
                    if (written == Io::complete) {
                        peer.has_pending = false;
                        if (peer.phase == 1) { peer.phase = 2; peer.deadline = 0; }
                        else { peer.in_flight = true; peer.sent_sequence = peer.next_sequence++; }
                    }
                }
                publish_report(index, peer);
            }
        }
        for (unsigned index = 0; index < max_peers; ++index) reset(peers_[index], index);
    }
public:
    explicit Broker(const Bootstrap& bootstrap) : bootstrap_(bootstrap), name_(pipe_name(bootstrap.installation)) {
        checked(stop_.valid() && wake_.valid());
        if (current_sid() != bootstrap.controller_sid.data()) throw WinFailure{ERROR_ACCESS_DENIED};
        constexpr auto audio_service_sid = "S-1-5-80-2676549577-1911656217-2625096541-4178041876-1366760775";
        const auto controller = current_sid();
        std::string sddl = "O:" + controller + "D:P(A;;GA;;;" + controller +
            ")(A;;0x00120183;;;SY)(A;;0x00120183;;;" + audio_service_sid + ")";
        PSECURITY_DESCRIPTOR descriptor = nullptr;
        checked(ConvertStringSecurityDescriptorToSecurityDescriptorA(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr) != FALSE);
        security_.value = descriptor;
        SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
        for (unsigned i = 0; i < max_peers; ++i) {
            peers_[i].pipe.reset(CreateNamedPipeW(name_.c_str(), PIPE_ACCESS_DUPLEX | (i == 0 ? FILE_FLAG_FIRST_PIPE_INSTANCE : 0),
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
                max_peers, max_frame * 2, max_frame * 2, 0, &attributes));
            checked(peers_[i].pipe.valid());
        }
        thread_ = std::thread([this] { run(); });
    }
    ~Broker() {
        closing_.store(true); SetEvent(stop_.get());
        if (thread_.joinable()) thread_.join(); // No state/control mutex held.
    }
    bool publish(const Bootstrap& binding, const Parameters& parameters, std::uint64_t generation) {
        if (closing_.load() || !generation || binding.installation != bootstrap_.installation || binding.controller_sid != bootstrap_.controller_sid) return false;
        Prepared checked_parameters;
        if (!prepare(parameters, 48000, checked_parameters)) return false;
        std::lock_guard<std::mutex> lock(mutex_);
        Desired* destination = nullptr;
        for (auto& value : desired_) if (value.used && value.binding.config == binding.config) { destination = &value; break; }
        if (!destination) for (auto& value : desired_) if (!value.used) { destination = &value; break; }
        if (!destination || (destination->used && generation <= destination->generation)) return false;
        *destination = Desired{true, binding, parameters, generation}; SetEvent(wake_.get()); return true;
    }
#ifdef YASB_DSP_TEST_HOOKS
    void test_hold(bool value) noexcept { hold_dispatch_.store(value); SetEvent(wake_.get()); }
    bool test_held() const noexcept { return dispatch_held_.load(); }
#endif
    unsigned reports(PeerReport* output, unsigned capacity) {
        unsigned count = 0;
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& value : reports_) {
            if (!value.active || count >= capacity) continue;
            PeerReport report = value.report; report.age_ms = GetTickCount64() - value.last_seen;
            for (const auto& desired : desired_) {
                if (!desired.used || desired.binding.config != report.config || desired.binding.endpoint != report.endpoint) continue;
                const auto wanted = fingerprint(desired.parameters);
                if (report.status.accepted_fingerprint == wanted && report.status.applied_fingerprint == wanted &&
                    report.status.settled_revision == report.status.accepted_revision &&
                    (!value.busy_fingerprint || value.busy_fingerprint == wanted)) report.confirmed_generation = desired.generation;
            }
            output[count++] = report;
        }
        return count;
    }
};
}

bool random_identity(Id& id) noexcept { return random_bytes(id.data(), static_cast<unsigned>(id.size())) && nonzero(id); }
bool valid_bootstrap(const Bootstrap& bootstrap) noexcept {
    if (bootstrap.magic_number != magic || bootstrap.version != protocol || bootstrap.bytes != sizeof(Bootstrap) || bootstrap.reserved ||
        !nonzero(bootstrap.installation) || !nonzero(bootstrap.config) || !nonzero(bootstrap.endpoint) ||
        std::find(bootstrap.controller_sid.begin(), bootstrap.controller_sid.end(), '\0') == bootstrap.controller_sid.end()) return false;
    PSID sid = nullptr;
    if (!ConvertStringSidToSidA(bootstrap.controller_sid.data(), &sid)) return false;
    LocalMemory memory{sid};
    Prepared prepared;
    return IsValidSid(sid) && bootstrap.initial.revision && prepare(bootstrap.initial, 48000, prepared);
}
bool same_binding(const Bootstrap& left, const Bootstrap& right) noexcept {
    return left.installation == right.installation && left.config == right.config && left.endpoint == right.endpoint && left.controller_sid == right.controller_sid;
}

struct ResidentClient::Impl {
    Bootstrap bootstrap;
    ClientHooks hooks;
    std::wstring name;
    Handle stop_event{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    std::thread thread;
    std::atomic<std::uint32_t> state{1}, error{0};
    Impl(const Bootstrap& binding, ClientHooks callbacks) : bootstrap(binding), hooks(callbacks), name(pipe_name(binding.installation)) {
        checked(stop_event.valid()); thread = std::thread([this] { run(); });
    }
    ~Impl() { stop(); }
    void stop() noexcept { SetEvent(stop_event.get()); if (thread.joinable()) thread.join(); }
    bool stopped(DWORD delay = 0) noexcept { return WaitForSingleObject(stop_event.get(), delay) == WAIT_OBJECT_0; }
    void set_connection(std::uint32_t value, std::uint32_t code) noexcept {
        state.store(value); error.store(code);
        if (hooks.connection) hooks.connection(hooks.owner, value, code);
    }
    void run() noexcept {
        while (!stopped()) {
            set_connection(1, error.load());
            Handle pipe(CreateFileW(name.c_str(), client_access, 0, nullptr, OPEN_EXISTING,
                SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr));
            DWORD mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
            if (!pipe.valid() || !SetNamedPipeHandleState(pipe.get(), &mode, nullptr, nullptr) || !verified_owner(pipe.get(), bootstrap)) {
                set_connection(1, GetLastError()); if (stopped(250)) break; continue;
            }
            Status status; hooks.status(hooks.owner, status);
            Id nonce; if (!random_identity(nonce)) { error.store(ERROR_GEN_FAILURE); if (stopped(250)) break; continue; }
            std::uint64_t connection = 0; std::memcpy(&connection, nonce.data(), sizeof(connection)); if (!connection) connection = 1;
            Packet pending = message(Op::hello, bootstrap, status, 0, connection); put(pending, status);
            const Header identity = pending.header;
            bool has_pending = true, handshake = false;
            std::uint64_t last_sequence = 0;
            ULONGLONG deadline = GetTickCount64() + 2000;
            while (!stopped()) {
                const auto now = GetTickCount64();
                if (now >= deadline) { error.store(ERROR_TIMEOUT); break; }
                hooks.status(hooks.owner, status);
                if (status.stream_epoch != identity.stream_epoch) { error.store(ERROR_RETRY); break; }
                if (has_pending) {
                    const auto written = write_packet(pipe.get(), pending);
                    if (written == Io::closed) { error.store(GetLastError()); break; }
                    if (written == Io::complete) has_pending = false;
                } else {
                    Packet incoming;
                    const auto read = read_packet(pipe.get(), incoming);
                    if (read == Io::closed) { error.store(GetLastError()); break; }
                    if (read == Io::complete) {
                        if (!matches(incoming.header, identity)) { error.store(ERROR_INVALID_DATA); break; }
                        if (!handshake) {
                            if (incoming.header.op != Op::hello_ack || incoming.header.sequence || incoming.header.bytes != sizeof(Header)) { error.store(ERROR_INVALID_DATA); break; }
                            handshake = true; set_connection(2, 0); deadline = now + 3000;
                        } else {
                            if (incoming.header.sequence <= last_sequence) { error.store(ERROR_INVALID_DATA); break; }
                            if (incoming.header.op == Op::set) {
                                Parameters parameters;
                                if (!get(incoming, parameters) || !hooks.submit(hooks.owner, parameters, identity.stream_epoch)) { error.store(ERROR_INVALID_DATA); break; }
                            } else if (incoming.header.op != Op::query || incoming.header.bytes != sizeof(Header)) { error.store(ERROR_INVALID_DATA); break; }
                            hooks.status(hooks.owner, status);
                            if (status.stream_epoch != identity.stream_epoch) { error.store(ERROR_RETRY); break; }
                            pending = message(Op::status, bootstrap, status, incoming.header.sequence, connection); put(pending, status);
                            last_sequence = incoming.header.sequence; has_pending = true; deadline = now + 3000;
                        }
                    }
                }
                if (stopped(10)) break;
            }
            set_connection(1, error.load()); if (stopped(100)) break;
        }
        set_connection(0, 0);
    }
};
ResidentClient::ResidentClient(const Bootstrap& bootstrap, ClientHooks hooks) : impl_(std::make_unique<Impl>(bootstrap, hooks)) {}
ResidentClient::~ResidentClient() = default;
void ResidentClient::stop() noexcept { impl_->stop(); }
std::uint32_t ResidentClient::state() const noexcept { return impl_->state.load(); }
std::uint32_t ResidentClient::error() const noexcept { return impl_->error.load(); }
}

extern "C" int YasbMediaProtocolInfo(void* output, unsigned bytes) {
    using namespace yasb::dsp;
    struct Info { std::uint32_t version, parameters, bootstrap, status, report, reserved; std::uint64_t build; };
    static_assert(sizeof(Info) == 32);
    if (!output || bytes != sizeof(Info)) { SetLastError(ERROR_INVALID_PARAMETER); return 0; }
    const Info info{protocol, sizeof(Parameters), sizeof(Bootstrap), sizeof(Status), sizeof(PeerReport), 0, YASB_DSP_BUILD_ID};
    std::memcpy(output, &info, sizeof(info)); return 1;
}
extern "C" int YasbMediaBootstrapInit(yasb::dsp::Bootstrap* output, unsigned bytes) {
    using namespace yasb::dsp;
    if (!output || bytes != sizeof(Bootstrap)) { SetLastError(ERROR_INVALID_PARAMETER); return 0; }
    try {
        Bootstrap bootstrap;
        checked(random_identity(bootstrap.installation) && random_bytes(bootstrap.config.data(), 32) && random_bytes(bootstrap.endpoint.data(), 32));
        const auto sid = current_sid();
        if (sid.size() >= bootstrap.controller_sid.size()) throw WinFailure{ERROR_INSUFFICIENT_BUFFER};
        std::memcpy(bootstrap.controller_sid.data(), sid.c_str(), sid.size() + 1);
        bootstrap.initial.revision = 1; *output = bootstrap; return 1;
    } catch (const WinFailure& error) { SetLastError(error.code); } catch (...) { SetLastError(ERROR_NOT_ENOUGH_MEMORY); }
    return 0;
}
extern "C" void* YasbMediaBrokerCreate(const yasb::dsp::Bootstrap* bootstrap, unsigned bytes) {
    using namespace yasb::dsp;
    if (!bootstrap || bytes != sizeof(Bootstrap) || !valid_bootstrap(*bootstrap)) { SetLastError(ERROR_INVALID_PARAMETER); return nullptr; }
    try { return new Broker(*bootstrap); }
    catch (const WinFailure& error) { SetLastError(error.code); } catch (...) { SetLastError(ERROR_NOT_ENOUGH_MEMORY); }
    return nullptr;
}
extern "C" int YasbMediaBrokerPublish(void* broker, const yasb::dsp::Bootstrap* binding, unsigned bytes,
    const yasb::dsp::Parameters* parameters, std::uint64_t generation) {
    using namespace yasb::dsp;
    if (!broker || !binding || !parameters || bytes != sizeof(Bootstrap) || !valid_bootstrap(*binding)) { SetLastError(ERROR_INVALID_PARAMETER); return 0; }
    if (!static_cast<Broker*>(broker)->publish(*binding, *parameters, generation)) { SetLastError(ERROR_INVALID_STATE); return 0; }
    SetLastError(ERROR_SUCCESS); return 1;
}
extern "C" unsigned YasbMediaBrokerReports(void* broker, yasb::dsp::PeerReport* output, unsigned capacity) {
    if (!broker || !output || !capacity || capacity > 16) { SetLastError(ERROR_INVALID_PARAMETER); return 0; }
    const auto count = static_cast<yasb::dsp::Broker*>(broker)->reports(output, capacity);
    SetLastError(ERROR_SUCCESS); return count;
}
extern "C" void YasbMediaBrokerDestroy(void* broker) { delete static_cast<yasb::dsp::Broker*>(broker); }

#ifdef YASB_DSP_TEST_HOOKS
extern "C" __declspec(dllexport) void YasbMediaBrokerTestHold(void* broker, int hold) {
    static_cast<yasb::dsp::Broker*>(broker)->test_hold(hold != 0);
}
extern "C" __declspec(dllexport) int YasbMediaBrokerTestHeld(void* broker) {
    return static_cast<yasb::dsp::Broker*>(broker)->test_held() ? 1 : 0;
}
#endif
