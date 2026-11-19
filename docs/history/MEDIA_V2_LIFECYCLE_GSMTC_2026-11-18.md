# Media V2 lifecycle and GSMTC continuation

18 November 2026. This offline continuation used the dirty checkout at
`E:\hi o\yasb`, branch `codex/sync-upstream`, HEAD
`c48acececa31006db98c21fca90b04e8b3cd233a`. The pinned Serpantinum target
remains `73b1cb79768641a52caf9f1d23a9a26f850f993e`. No live players, devices,
Windows settings, profiles, APO targets or Git index state were changed.

## Changed

- Added `closed` at `src/core/widgets/services/media/audio_device.py:105`. A
  persistent `MediaPopup` now rebinds the exact default service through
  `src/core/widgets/yasb/media_v2_popup.py:361` when it is reopened after
  shutdown. Injected test doubles remain unchanged.
- `EqualizerApoController._ensure_output_service` at
  `src/core/widgets/services/media/equalizer_apo.py:1333` reacquires a closed
  default output service at output reads and write boundaries.
  `EqualizerApoWriter.queue` drops closed default callbacks at line 958 before
  accepting a new request.
- `StereoTestService.shared()` at
  `src/core/widgets/services/media/stereo_test.py:90` now recreates a directly
  shut-down singleton.
  Its asynchronous application shutdown keeps the closed instance available
  until worker retirement completes. `MediaAudioPanel.toggle_test` at
  `src/core/widgets/yasb/media_v2_audio.py:227` drops a closed cached test
  service and reacquires the shared owner before a later Test action.
- Added regressions for direct singleton recreation, controller rebinding,
  popup rebinding, and Audio-panel test-service reacquisition.

The audit confirmed that normal application shutdown remains ordered. `main.py`
retires the stereo test, media backend, lyrics service and APO writer before
calling `app.quit`; the default output service then receives `aboutToQuit`.
The repaired paths cover a mid-process shutdown and reopen, where persistent
popup and panel owners previously retained closed QObjects.

## GSMTC alternative investigation

YASB currently uses `winrt.windows.media.control==3.2.1` through the Windows
GSMTC manager. The manager is the supported cross-process observer for sessions
that integrate with SMTC. It provides session enumeration, session-change
events, metadata, artwork, timeline, playback events and transport commands.
The current session and media-properties contracts expose no stable track or
media identifier beyond session and source-app identity.

`SystemMediaTransportControls` is an app-owned publishing and command surface
for the application's own `MediaPlayer`. `IAudioSessionManager2` and WASAPI
can complement GSMTC with process and endpoint session diagnostics, but they do
not provide track metadata, artwork, timeline or transport commands.
`IMFMediaSession` controls a Media Foundation pipeline owned by its caller.
MPRIS requires a per-player Windows bridge. UI Automation, window titles and
player-specific adapters are incomplete and brittle. GSMTC remains the only
supported general Windows source that preserves the Media V2 cross-player
contract. WASAPI is suitable as an optional companion diagnostic source.

Official references include the [GSMTC manager](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager),
[GSMTC session](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession),
[GSMTC media properties](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmediaproperties),
[SystemMediaTransportControls](https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/system-media-transport-controls),
[IAudioSessionManager2](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nn-audiopolicy-iaudiosessionmanager2),
[Core Audio interfaces](https://learn.microsoft.com/en-us/windows/win32/coreaudio/core-audio-interfaces), and
[IMFMediaSession](https://learn.microsoft.com/en-us/windows/win32/api/mfidl/nn-mfidl-imfmediasession).

## Verification

The focused media, lifecycle, popup, equalizer and section selection passed
214 tests. The full suite passed **2,751 tests and one expected AMD skip** in
166.75 seconds. It emitted 1,739 qasync deprecation warnings.

Strict Pyright 1.1.414 analyzed 502 files with zero diagnostics. Ruff check and
format check passed, with 509 files already formatted. Schema export registered
60 widgets and matched the current root schema bytes. The build exited 0 with
the existing cx_Freeze missing-module and duplicate quick-launch warnings.

The private frozen package matched 31 production modules plus the ordinary
entry, preserved 2,644 original ZIP entries and added only the two owned preview
dispatch entries. Ordinary and preview executable SHA-256 are both
`674b615696f03453ccb5b1b6f4ed45fcbfd5ebdd3dfa10462e6347e6f1915cc9`.
The source-bound synthetic preview used `native-profile-lifecycle`, exited 0,
and passed the popup, motion, Apply/discard, Lyrics, Audio, two fake Test
sinks, closed-timer, capture-reader and clean-shutdown checks. It recorded no
source actions and no presented-frame evidence.

The unchanged benchmark was run under labels
`final001-audio-lifecycle-20261118`, `final001-audio-lifecycle-20261118-r4`,
`final001-audio-lifecycle-clean-20261118` and
`final001-audio-lifecycle-clean2-20261118`.
The first clean run was started after the installed YASB process had exited and
measured settled two-view CPU at 12.9591% against the unchanged 12% cap. A
second clean run measured 15.8840%. Both comparators failed only that CPU
check. Earlier same-batch samples were 12.9420%, 14.4055% and 14.2889% while
the installed process was still present. The prior continuation receipt remains
a passing 11.3632% sample. The latest source manifest has 540 inputs and SHA-256
`e258d72b8416f9d7acd65de40f03f92de71f488a97dd6daf8e915f10acd4248d`.
The benchmark SHA remains
`f379e3db8011e299a1b8cc5c1f212e161471f7505740a16e074c22b76a2790a4`, and the
budget SHA remains
`83a16382417cf26956eaefc627a532453071816da0e301b875cc5bc455060657`.
The clean-run preflight confirmed no installed `C:\Program Files\YASB\yasb.exe`
process. The clean samples still vary materially, so they do not justify a
source-performance conclusion or a claim that the 12% cap is met.

The read-only attribution helper then measured the final hidden-popup sample at
8.3734% CPU with the same current source. A subsequent unchanged acceptance run
under `final001-audio-lifecycle-clean3-20261118` measured 9.1421% and the
comparator exited 0. Its source manifest, benchmark and budget hashes are
unchanged. The clean3 receipt passed every original budget, including zero
settled timers, readers and jobs, 15.4194 ms event-to-title-paint-start p95,
266,240 bytes private growth and zero handle or thread growth.

## Remaining evidence

The closed CPU cap now has a clean passing receipt, with short-sample variance
retained in the failed clean1 and clean2 records. The benchmark uses an
injected fake output and does not exercise the new closed-service branches, so
the result is evidence for the isolated raster budget rather than live output
behavior. Physical mixed-DPI and compositor
behavior, presented frames, ordinary production-main startup, full physical
input, live providers and live DSP remain outside this offline batch.
Duplicate metadata still needs a stronger platform track identifier before its
identity contract can change.
