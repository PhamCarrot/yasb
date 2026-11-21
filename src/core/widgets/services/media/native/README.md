# Optional native media processor

This optional Windows x64 processor uses a resident control route through the
shared APO writer. The default `processor: graphic_eq` uses the static Equalizer
APO route. `processor: native` requires a prepared DLL path, hash and selected
profile binding.

Implemented: ten Q=1 peaking filters (32–16000 Hz), full-curve coefficient ramps
over 20 ms, mono averaging, channel swap, linear balance (inactive in mono),
full-state chunk validation and source/instance/revision/frame readback. The
audio callback uses fixed storage and lock-free triple buffers. The non-audio
control side computes coefficients and serializes callers. New commands coalesce
to the latest snapshot; accepted, applied and settled revisions remain distinct.

Supported proof: Windows x64, stereo float32, 44100/48000/88200/96000/176400/192000
Hz. Other rates bypass and report unsupported. Endpoint attestation and full
real-device parity remain open.
Unknown protocol fields are rejected rather than ignored.

The host must stop **and drain** processing before format changes/destruction,
and invoke only one audio callback at a time per instance. Suspending the instance
does not itself join a callback already in progress. Host lifecycle calls are not
permitted from its audio callback. Both replacing and legacy accumulating
entrypoints are tested; only the float replacing route is the intended APO path.

From the repository root with its developer environment and installed MSVC/SDK:

```powershell
python -m src.build_media_dsp
python -m pytest -q tests/widgets/test_media_native_dsp.py
```

The build reuses the repository's existing SDK/toolchain discovery, requires x64,
uses C++17/static CRT, treats compiler warnings as errors and emits a source hash,
DLL hash, build ID and third-party notices beside the DLL. Tests load the actual
DLL in a native host and process synthetic buffers without opening an audio device.
The build is optional and is not part of ordinary YASB startup or packaging yet.

## Streaming behavior

The streaming slice adds stereo-linked 10ms mean-square compression without
makeup. Balanced uses threshold−26dB/ratio2.8/knee20dB/attack14ms/release200ms;
Night uses−36/6/28/6/320. A linked lookahead limiter uses a nominal5ms window,
actual delay `floor(.005*rate)-1` frames (239 at48kHz),50msrelease and−1dBFS
sample ceiling with dynamics. Adaptive-only uses−0.1dBFS. These are sample-peak,
float32-representable bounds, not oversampled true-peak claims.

Adaptive EQ uses16384-point periodic-Hann stereo-power analysis with8192-frame
hop,27third-octave observations,17Q2half-octave filters, weighted/ridge/smooth
fitting with two residual refinements, four-second admitted warmup, asymmetric
correction and K-weighted makeup. Gain slew is0.25s with persistent32-frame phase;
makeup slews linear amplitude every sample. Enabling resets learning; disabling
fades neutral. It replaces manual-band processing while retaining the manual
curve for restoration. Bypass is immediate with zero delay and freezes histories.

Three intentional corrections to reference artifacts: analysis is causal at
absolute sample boundaries; slew does not depend on host block partitioning;
and negligible useful-band energy is rejected before admission, preventing DC
Hann leakage from steering filters. Low tones and DC-plus-valid-signal retain
admission. The pinned reference's relative gate remains: rejected observations
freeze the30smean/history, so a sustained >10dB drop can remain excluded until
reset/louder input. This limitation is explicit, not a new automatic mode.

Host-visible delay updates and IO-changed notifications occur only at safe
host-owned dispatch points, outside the mutex and as the last owner operation.
The resident worker never calls the host: a synchronous host destruction must be
able to join it. GET_CHUNK, suspend-to-stop and destroy do not deliver pending
notifications. A host that never dispatches after a resident latency change leaves
`host_latency_pending` set; real APO negotiation remains a deployment gate. Custom readback
reports actual callback latency, flags, bypass, learned gains and admission counts.
`settled_revision` covers the manual/stereo parameter ramp, not compressor-envelope
or adaptive convergence. Advancing callback frames do not establish audible output.
The real APO host's negotiation/channel mapping/restricted permissions remain open.

## Resident route and persistence

Protocol3 uses Parameters72, Bootstrap360, Status232 and PeerReport320 bytes.
The ordinary-user broker is a local message pipe with exclusive first instance,
remote rejection and owner checking. The controller owns the pipe. LocalSystem
and the Windows Audio service SID have client data and query rights.
The controller principal is trusted; this is not executable attestation or a
security boundary between programs running under the same SID. Kernel client PID,
exact source build, config/endpoint keys, random instance UUID, stream epoch,
connection nonce and sequence fence every exchange. Configured endpoint keys are
associations, not proof of physical Windows endpoint identity.

At most16 peers/config slots,1KiB frames and one pending/in-flight packet per peer.
NOWAIT I/O and2–3second deadlines bound stalled/malformed peers. Stop events wake
and join workers outside plugin/control locks; there are no Python callbacks from
the DLL. Real-time processing performs no pipe, file, allocation or blocking lock.
Command reservation publishes latest status and its busy fence atomically before
I/O, so A→B→A cannot reuse a superseded cached completion.

The selected YASB profile stores atomic committed whole EQ+Audio state and keeps a
recoverable first record backup. The canonical APO file remains the sole owner key
across profiles/processors. Native setup keeps the previous managed leaf as
`yasb-media-v2-eq.txt.yasb-native-backup`; parent backup semantics are unchanged.
The native leaf contains only the stereo plugin chain, with preamp inside DSP,
never a second GraphicEQ/host Preamp. Ordinary settings update the profile record
and resident snapshot; the watched leaf changes only on setup, retarget, repair
or explicit rollback to the static route. Startup restores saved manual/Audio
state before accepting edits. Failed restoration remains blocked and Apply retries
restoration. Audio patches never consume an EQ draft; Apply keeps latest Audio.

A stable Bootstrap carries initial settings. If the host reloads while YASB is
absent, it starts those settings until YASB reconnects and reconciles its selected
profile record. No claim of latest-state restoration while YASB is absent is made.
Missing/incompatible artifacts or disconnected instances stay unavailable; there
is no silent GraphicEQ fallback. DLL upgrades require a reviewed binding migration
rather than overwriting an incompatible record.

File persistence, command acceptance, applied/manual-ramp-settled state and audio
callback progress are separate. Frame progress is observed by the non-audio
consumer, including a callback-age field, and fenced by instance/stream/connection;
a fresh pipe response alone never establishes ongoing audio processing. Historical
routes retire their broker threads/handles when their canonical intent moves.
Normal packaging still excludes the optional DLL; deployment/channel mapping,
restricted host-token permissions and real audible processing need separate proof.

## Provenance

The processor and protocol are independently implemented MIT code. Peaking-filter
mathematics follows the [W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/).
No Serpantinum AGPL engine source or assets are included or translated here.

The interoperability header and all accompanying notices are preserved verbatim
from [DPF revision4238e1c7f0351bbe488d79f0899c540543ac7583](https://github.com/DISTRHO/DPF/tree/4238e1c7f0351bbe488d79f0899c540543ac7583/distrho/src/xaymar-vst2),
retrieved16November2026. Bundled LICENSE has BSD3 conditions; the header retains
its BSD2 wording and upstream README. Binary builds carry all three documents.

| File | SHA256 |
|---|---|
| `vendor/xaymar-vst2/vst.h` | `dae7b8056ffc9cdd487d376e22a5e20861a854aae36d0b64bfea9eb0fb1c903e` |
| `vendor/xaymar-vst2/LICENSE` | `d7e0e8225d97d6c46a5048daef5f471cbda3ce3e8cc44d2da8ef6a833aed4bc5` |
| `vendor/xaymar-vst2/README.md` | `8d67a90a80c63419982eb9bea2b78f93f11df7aac372ac8ae066519949da481d` |

The target loader is pinned Equalizer APO
[`bbfcc3e5024cbb9d61ba75fc88d78605cc4c9687`](https://sourceforge.net/p/equalizerapo/code/ci/bbfcc3e5024cbb9d61ba75fc88d78605cc4c9687/tree/helpers/VSTPluginInstance.cpp).
Interoperability in the offline host does not establish compatibility with a
restricted real `audiodg` process, endpoint routing or installed host activation.

Streaming mathematical/behavioral target is pinned [Serpantinum audio cf81973482c0f1cb7ef144b17afb3714d2c4f96d](https://github.com/ilyamiro/serpantinum-audio/tree/cf81973482c0f1cb7ef144b17afb3714d2c4f96d).
The implementation is independent MIT code from the stated contracts, not a
translation or inclusion of the AGPL source. Offline numeric fixtures distinguish
compressor detection/knee, limiter delay/history, FFT stereo energy, fitting,
loudness, gating and block causality. Phase-level deployment/functional parity
remains subject to the project plan's additional gates.
