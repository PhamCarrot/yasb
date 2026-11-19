# Media V2 ordinary startup and real-use check

19 November 2026, Asia/Bangkok. The current checkout remained on
`codex/sync-upstream` at `c48acececa31006db98c21fca90b04e8b3cd233a`.
The earlier [themed popup batch](MEDIA_V2_THEMED_POPUP_2026-11-19.md) records
the source-bound synthetic verification. This session used the actual
ordinary entry points and gathered separate Windows media evidence.

## Artifacts and profile

| Build | Artifact | SHA-256 of executable / library.zip |
| --- | --- | --- |
| Candidate 2.0.9, primary | `E:\hi o\yasb\src\dist\yasb.exe`, launched from `E:\hi o\yasb` | `674b615696f03453ccb5b1b6f4ed45fcbfd5ebdd3dfa10462e6347e6f1915cc9` / `2ab95bb852c00b6c2aaa3fce4dcef7859d47f5b29414b510967036d904d18923` |
| Installed fork 2.0.8, primary baseline | `C:\Program Files\YASB\yasb.exe`, launched from its install directory | `0ae6c52a45bfb0391a62110897239ba4224423e3b98f5eaa0053e93b76943d19` / `8e68209e533af7e3f0b8ac495d843f4deca05813eb573ecdbca239b147955f8a` |
| Fork `main` 2.0.8, secondary reconstruction | `.git/media-v2-real-use-20261119/fork-source/src/dist/yasb.exe`, launched from the isolated exported checkout | `7b3952db4c0495ccdf05143d85aa3482afe362654f856f168ed6bb5cdf9cba41` / `9783ea013986c60cb1f53fc25b8069440172a12d85c8c53b60b2e4f1585603d9` |

The user confirmed that the installed copy is their fork build. A read-only
archive comparison matched 395 normalized startup and core bytecodes to the
fork's [September 19 commit](https://github.com/PhamCarrot/yasb/commit/b67033d391cc6ca94dcfa2faf736c6a2cf027e53).
The secondary build uses the fork's verified public
[`main` commit](https://github.com/PhamCarrot/yasb/commit/5c791bdb0604015e1257d91a45dc6530bd2a90c1).
That commit differs from the installed source in 13 packaged modules,
including bar startup and taskbar. The fork's release page listed zero
releases. The installed bundle has Python 3.14.7. Both other binaries have
3.14.10. All bundle Qt 6.10.2. [Artifact metadata](../../.git/media-v2-real-use-20261119/artifacts.json).

The fork reconstruction used its pinned direct packages and cx_Freeze 8.6.4
in an isolated virtual environment. For the moving CSS-engine `dev` ref, it
used the latest commit at the fork's published `main` timestamp,
[`0f389247`](https://github.com/Video-Nomad/qt-css-engine/commit/0f389247c30007e995bcf9e2565914f84a5831e3).
The source archive checkouts lacked SCM version metadata. The first dependency
build exited 1, and the retry supplied the version label to the CSS build
backend. `build.py build` exited 0 on the retry. The first frozen launch then
failed in `qasync` while importing `PyQt6.QtCore` with “The specified procedure
could not be found.” The owned Qt folder contained two non-Windows ICU DLLs.
Quarantining both outside the frozen folder let the reconstruction use Windows
ICU, as the candidate does. The executable and ZIP hashes were identical before
and after. [Dependencies](../../.git/media-v2-real-use-20261119/fork-dependencies-freeze.txt),
[first frozen receipt](../../.git/media-v2-real-use-20261119/launches/fork-main-1.json),
[error dialog](../../.git/media-v2-real-use-20261119/fork-import-diagnostic.txt),
[timed artifact](../../.git/media-v2-real-use-20261119/fork-timed-artifact.json).

The timing workloads used byte-identical copied `styles.css` and identical
derived YAML, retaining the live widget list and theme. Process-local
`YASB_CONFIG_HOME`, `LOCALAPPDATA`, `TEMP` and `TMP` point into the owned
profile. Update checks and work-area reservation are disabled. The owned
YAML suppresses the custom separator's startup command and clears the Power
Menu bindings. The configuration uses visual EQ with live APO disabled.
No unrelated player or YASB instance was closed. The original launchers,
registered autostart and installed bundle were read only.
[Profile receipt](../../.git/media-v2-real-use-20261119/profiles.json).

## Startup measurements

The first series compared the reconstructed fork. After the user identified
their installed artifact, a second series compared that physical install. In
each series the order was baseline, candidate, candidate, baseline, baseline,
candidate, candidate, baseline. Each launch used a fresh process. Each series
reused its own per-build profile from the second run onward. The candidate
had already launched four times before the primary installed comparison.
Binary building, hashing and package inspection occurred before the recorded
launches. No OS cache reset or reboot was performed.

Times are from just before `CreateProcess` to the first sample of the owned
`YasbBar` HWND visible and uncloaked, and then to a successful `WM_NULL`
round trip to that same bar. The polling interval was 12 ms plus overhead.
The second metric is message dispatch readiness. Exact compositor presentation,
first popup paint and whole-desktop responsiveness require separate timing.
The test used one 1920 × 1080 display at 96 DPI. The work area matched before,
during and after every launch. CPU is summed process user and kernel time.

| Series | Build | First bar / ready | Repeat median bar / ready | Repeat bar range |
| --- | --- | --- | --- | --- |
| Primary | Installed fork | 2.891 s / 2.941 s | 1.601 s / 1.631 s | 1.569–1.740 s |
| Primary | Previously launched candidate, new profile | 2.099 s / 2.140 s | 1.682 s / 1.759 s | 1.596–1.979 s |
| Secondary | Reconstructed fork | 3.147 s / 3.536 s | 1.744 s / 1.795 s | 1.527–1.746 s |
| Secondary | Earliest observed candidate | 11.634 s / 12.566 s | 1.913 s / 1.960 s | 1.616–2.037 s |

The primary repeat times overlap. Median time to the bar was 81 ms longer
in the candidate and message readiness was 128 ms longer. Median CPU to
message readiness was 1.578 s for the candidate and 1.938 s for the installed
fork. All 16 measured processes exited 0 through the pipe owned by their own
PID. The mutex and pipe were gone and no bar HWND survived after each stop.
[All raw samples and medians](../../.git/media-v2-real-use-20261119/timing-summary.json).

The earliest candidate launch spent approximately 7.275 s before its first
application log, 3.120 s from the CLI server log to the audio-service startup
marker, and 0.931 s between window visibility and message readiness. Its
subsequent ranges in that series were 0.600–1.078 s, 0.392–0.411 s and
0.037–0.047 s. Process CPU to readiness was 1.672 s on the earliest run and
1.594–1.625 s on repeats. The added delay was primarily elapsed time, with
host CPU busy at 40% on the first candidate launch versus 29–45% on its
repeats. The markers localize the delay without identifying the waiting
component. The earliest installed observed run from the later primary series
took 1.442 s to its first log and 0.692 s from CLI to audio-service marker.
[Earliest candidate log](../../.git/media-v2-real-use-20261119/launches-final/candidate-1-yasb.log),
[earliest installed log](../../.git/media-v2-real-use-20261119/launches-installed/installed-1-yasb.log).

Every timing log contains both native COM diagnostics. `0x8001010d` appears
while the event loop is running, and `0x8001010e` appears at GSMTC manager
release during shutdown. Exit codes stayed 0. The ordinary candidate real-use
run without a `WM_NULL` probe also logged `0x8001010d`. The shared behavior
belongs in readiness assessment despite the successful process exits.
[Primary candidate log](../../.git/media-v2-real-use-20261119/launches-installed/candidate-1-yasb.log),
[primary baseline log](../../.git/media-v2-real-use-20261119/launches-installed/installed-1-yasb.log),
[COM status definitions](https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-3).

## Real Windows media and the themed popup

An isolated installed Chrome 157.0.8103.80 app window played two generated
tracks with a quiet local signal. The independent WinRT witness saw Chrome's
genuine GSMTC session as current, the expected titles and the listed playback
and timeline states. The receipt keeps only the owned tracks and an unowned
session count. The real Chrome app and candidate were separate processes.
[Windows session events](../../.git/media-v2-real-use-20261119/real-gsmtc.jsonl),
[player callbacks](../../.git/media-v2-real-use-20261119/real-player-events.jsonl).

The ordinary candidate launched twice during this check and shut down via
its own CLI pipe. Sky omitted both the bar and popup from its target list.
The second owned profile added `Ctrl+Alt+Shift+F12` for the existing Media V2
`toggle_media_menu` callback. After that injected native key, Win32 observed
the candidate's owned 625 × 565 popup at `[8, 41, 633, 606]`, HWND `16256352`,
alongside bar HWND `35195986` in PID `38488`, while Chrome's track was active.
A later window enumeration showed only its bar. This establishes ordinary
startup and popup creation in real use. Sky's target boundary leaves the
ordinary popup's paint, selected tab, click and drag interactions unobserved.
The shortcut was registered in the owned profile for the process lifetime.
[Native shortcut receipt](../../.git/media-v2-real-use-20261119/ordinary-popup-sky.json),
[ordinary exit](../../.git/media-v2-real-use-20261119/real-candidate-shortcut.json).

A separate companion package preserved all 2,645 shipped archive entries
and the executable bytes. Its two private entry points hosted the packaged
widget in a test window with the same QSS and visual-only media config. It
used the production GSMTC adapter and the genuine Chrome session without a
mock backend. Actions inside the host used Qt events and widget callbacks.
It held the window open for deterministic assertions. Its images are Qt
widget captures. The ordinary executable stayed unchanged.
[Companion package proof](../../.git/media-v2-real-use-20261119/packaged-real-proof.json).

- The 625 × 565 popup showed the owned Chrome title, art, source and timeline
  with Equalizer selected by default. Bass fit within the header immediately.
  A Qt drag changed 31 Hz from +5 dB to +8 dB and preserved the other nine
  values. Explicit Apply committed the visual draft. Live APO was disabled,
  and the ordinary executable has no profile-specific APO path override.
  The disposable writer path remains covered by the preceding synthetic gate.
- Both wheel directions kept Equalizer selected. Separate tab clicks reached
  Audio and Lyrics. Audio showed the visual-only processing state and both
  glyph buttons. Lyrics reached the search UI with the owned synthetic track.
  No real lyric match or real endpoint DSP was exercised.
- Pause and resume reached Chrome through SMTC, and both were reflected by
  the popup backend. The initial HTTP fixture delivered a seek callback but
  finished at 0 s. On the rerun, the local media was buffered in seekable
  browser blobs. Chrome received and applied the 168 s target and both
  Windows and YASB reported 168 s. The attempt with the earlier fixture is
  kept, including its exit 1. [Initial seek failure](../../.git/media-v2-real-use-20261119/packaged-real-receipts-first-attempt/error.log).
- Next reached Chrome, updated YASB to the new real title and kept Equalizer.
  The early Qt frame deliberately retained the outgoing title during its
  authored 300 ms crossfade. A second capture waited for the text blend to
  reach 0.999 and visibly showed Orchard after Harbor. The same popup closed
  and reopened on its last selected Audio page with the new title. The
  backend reported closed after shutdown. The final companion process
  exited 0 with 12 passing steps and zero failures. Its synchronous Qt widget
  calls took 107.5 ms for initial open and 11.0 ms for reopen. Those calls
  exclude desktop presentation and native input latency.

[Equalizer](../../.git/media-v2-real-use-20261119/packaged-real-receipts/01-equalizer-real-track.png),
[immediate Bass caption](../../.git/media-v2-real-use-20261119/packaged-real-receipts/02-bass-immediate-qt.png),
[Audio](../../.git/media-v2-real-use-20261119/packaged-real-receipts/04-audio.png),
[Lyrics](../../.git/media-v2-real-use-20261119/packaged-real-receipts/05-lyrics.png),
[title transition](../../.git/media-v2-real-use-20261119/packaged-real-receipts/06-next-real-track-transition.png),
[settled title](../../.git/media-v2-real-use-20261119/packaged-real-receipts/07-next-real-track-settled.png),
[assertions](../../.git/media-v2-real-use-20261119/packaged-real-receipts/steps.json),
[exit](../../.git/media-v2-real-use-20261119/packaged-real-exit.json).

The owned Chrome process and both ordinary real-use candidate processes
exited 0. The final GSMTC inventory contained neither an owned nor unrelated
session. The desktop inventory contained no owned windows. Live profile
hashes, Git metadata and shipped artifacts were checked after shutdown.
[Final integrity](../../.git/media-v2-real-use-20261119/final-integrity.json).

## Readiness

The candidate is suitable for continued local evaluation. Keep the installed
copy as the daily default while the earliest observed startup stall and the
native GSMTC diagnostics remain unexplained. Warm launch times alone do not
show a persistent multi-second difference. A new paired cold-cache sample,
desktop and first-popup presentation timing, physical popup input, mixed-DPI,
signed or installed candidate deployment, live APO/DSP and a real lyrics hit
remain outside the completed evidence. A future startup investigation should
trace the interval before the first application log and the CLI-to-audio
service boundary on the original artifact. Keep this verification separate
from any future source changes.
