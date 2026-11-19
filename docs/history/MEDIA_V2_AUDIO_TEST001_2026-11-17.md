# AUDIO-TEST-001 - Explicit cancellable stereo Test

Completed locally17November2026. Main owns all changes. No Git writes/push, real device enumeration/playback, player controls or live APO changes.

## Changed and decisions

One application-owned StereoTestService prepares one immutable614400-byte/153600-frame/48kHzstereoInt16 clip on one retained worker. Independent sine generator: left660Hz.75s, silence.18s,right880Hz.75s,silence.18s,both770Hz1s,tail.34s; peak9000/15mslinear fades. No AGPL generator reuse. Lazy real sink factory is reached only by explicit visible Audio Test. It matches the captured endpoint UTF8 QtIMMDeviceID case-insensitively, requires exact format and fails closed; no default fallback/volume/EQ/player mutation.

One intent generation/token, sink/QBuffer and3.2stimer. Install before potentially synchronous callbacks; retire identity before reset; reset before bufferclose. Stop/restart retains actual preparation until completion. Supersession/outputchange/stale signals cannot stop or publish into a successor. Shutdown retires playback/drains actual work before global task cancellation. UI cancels before outgoing fade, on close/hide/Reset/destruction. Stop stays enabled even without native DSP. Audio Reset preserves adaptive/bypass and resets balance/mono/swap/dynamics. Default tests block real sink reach and fail if attempted; adapters are exercised only with fake Qt devices/sinks.

## Verification

Exact commands/cwd/exits in `.git/audio-test/final-verification.json`. Full2725passed/1expectedAMDskip121.94s(exit0); focused28passed1.63s. Pyright501files/zero diagnostics; Ruff check exit0/508formatted. Schema60unchanged. Frozenbuildexit0/26.94s;25packaged modules structurally match current source, QtMultimedia.pyd/Qt6Multimedia.dll/Windows+FFmpegplugins included.539-input manifest/nine-filearchive. Known packaging warnings and qasync deprecations retained.

Tests exercise held actual preparation acrossStop/restart/drain, PCM channels/frequency/fades, one-owner/tokens/outputchanges, synchronousEOF/start/error/reset callbacks, stale timers, buffer-open/generator/length/sink failures and retry, QBufferreset-before-close, no EQ/draft/player writes, native-unavailable Stop, tab/close/Reset/destruction. Initial failures were readiness assumptions (Stop also means Preparing) and querying an already Qt-deleted QBuffer; explicit Playing readiness, QObject validity plus reset-before-close event ordering corrected the oracle without relaxing contracts. Type-only errors were corrected, not suppressed. Independent bounded source review found no actionable defect.

Native source-bound synthetic preview profile0fe9063a/PID22960/window6884198:30sourcehashes matched; keyboardCtrlTab/CtrlShiftTab/Tab/Space activated Test, observedplaying/Stop despite unavailableDSP; three3.2sdeadline completions retiredthreefakesinks, no sourceactions. Escape restored Open media playerfocus; host exited cleanly/inventoryempty; existing chooserstamp identical. One mouse routing rejection over Codex was not sent through; keyboard route used instead. Native Stop-before-deadline was not established (tool roundtrips exceeded clip duration); actualqasync UI runtime tests cover immediateStop and cancellation. No audible or realendpoint proof. Receipt/nativecaptures/events retained. All previewsclosed; old identitiesstale.

## Next

FID-001 geometry/header/Audio composition, FID-002 wavy seek/motion, FINAL-001 compatibility/frozen UI/performance. Real DSP deployment remains separately authorized after concrete backup/rollback is prepared. No legacyautosave.
