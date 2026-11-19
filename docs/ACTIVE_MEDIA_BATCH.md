# Active Media V2 checkpoint

## Source publication

The 2.0.9 source is on the fork's main branch at `a7d7c7a5`. The
[current handoff](NEXT_SESSION_HANDOFF.md) records packaging, public CI
and the remaining startup issue.

## Archived startup trace

Completed 19 November 2026. See the [handoff](NEXT_SESSION_HANDOFF.md) and
[startup trace record](history/YASB_STARTUP_TRACE_2026-11-19.md).

The new ordinary candidate first launch took 1.898 s before its first log and
5.523 s to message-ready. The trace localized newer stalls to several
startup phases, and the installed fork also showed a first-copy slowdown.
The historical 7.275 s has no identified wait owner. The source and shipped
packages matched their entry hashes after the trace. Final repeat medians
were close at 1.386 s versus 1.333 s to the visible bar. All 48 measured
launches exited 0. Keep the installed fork as the daily baseline.

The subsequent two-run primary-thread check also exited 0. Windows reported
13 single-node blocked samples during the slower copied launch. The
receipt leaves the wait object and owner unidentified. See the startup trace
record for the raw wait-chain, page-fault and module samples.

## Archived ordinary startup and real-use check

Completed 19 November 2026. See the [handoff](NEXT_SESSION_HANDOFF.md) and
[startup and real-use record](history/MEDIA_V2_REAL_USE_2026-11-19.md).

The primary comparison used the user's installed fork 2.0.8. Warm median
visible times were 1.682 s for the candidate and 1.601 s for the installed
build. The earliest candidate launch took 11.634 s to a visible bar, with
7.275 s before its first log. The ordinary launches compared fresh processes
with uncontrolled OS cache. Both builds emitted native COM diagnostics.

A native shortcut opened the ordinary popup while an owned Chrome GSMTC
session was playing. The separate packaged test passed 12 events against
the real session and the user's copied theme, including a 168 s seek and a
settled real track update. Owned processes exited and the live config and Git
integrity checks matched entry. Preserve the installed daily baseline while
the first-start stall and native COM diagnostics are open.

## Archived themed popup batch

Completed 19 November 2026 in the local `codex/sync-upstream` checkout.
Read the [handoff](NEXT_SESSION_HANDOFF.md) and
[themed popup record](history/MEDIA_V2_THEMED_POPUP_2026-11-19.md).

Preset drag and caption were fixed through the existing draft, writer and
header owners. The real-theme fixture aligns the Equalizer, Audio and Lyrics
sections against the pinned full-popup reference. Audio Test uses headphones,
active Stop uses a square and Reset uses a circular arrow. The record links
the complete phase captures, including the separately enabled seek thumb.

Current-source serial results were **2,789 passes and one expected AMD
skip**, Ruff and strict Pyright pass, 60-widget byte-identical schema,
verified build/package and a clean owned Windows preview. The unchanged
comparator passed on the first run at **6.865% settled two-view CPU against
12%**. The prior owner-repair numbers below are historical.

Mixed-DPI, physical input, presented frames, ordinary production startup,
real providers, live endpoints/APO/DSP and stable duplicate-track identity
remain separate evidence. See the handoff for the next authorized route.

## Archived owner repair batch

Completed 19 November 2026 in the local `codex/sync-upstream` checkout.
Read the [owner repair record](history/MEDIA_V2_OWNER_REPAIRS_2026-11-19.md).
Enabled APO now admits Apply against the current writer and draft lease.
The Media V2 Audio page exposes balance, mono, swap, Dynamic EQ and Reset.
The Media V2 Lyrics page uses online providers and no longer exposes local-file
import.
The backend remains the shared owner until cleanup completes.

Final current-source results were **2,779 passes and one expected AMD
skip**, Ruff and strict Pyright pass, 60-widget byte-identical schema,
frozen package proof and a clean owned Windows preview. The unchanged
performance repeat passed at **9.920% settled two-view CPU against 12%** after
the initial 13.714% miss and a separate diagnostic. The record links the
fresh source manifest, receipts, focus observations and failed attempts.

The local batch has reached its verification boundary. Mixed-DPI, physical
input, presented frames, ordinary production startup, real providers,
live endpoint/DSP and stable duplicate-track identity remain external evidence.

## Archived checkpoint notes

Updated 19 November 2026 after the architecture4 offline continuation. Read the [handoff](NEXT_SESSION_HANDOFF.md) and
[FINAL-001 performance follow-up](history/MEDIA_V2_FINAL001_PERF_2026-11-18.md).

The fresh current-source run passed all unchanged isolated raster budgets.
Settled two-view CPU was 10.59% against 12%, and single-view playing
event-loop p95 was 5.94 ms against 25 ms. Full pytest repeat passed with 2,745
tests and the expected AMD skip after one timing-sensitive Lyrics failure on
the first current-session run. Strict Pyright, Ruff, schema and frozen build
checks passed. The current-source frozen synthetic preview passed and closed
with its chooser stamp preserved. The local FINAL-001 milestone remains
complete. Findings and exact receipts are in
[MEDIA_V2_REVIEW_2026-11-18](history/MEDIA_V2_REVIEW_2026-11-18.md).

Preserve the dirty checkout at E:\hi o\yasb, manual Apply, marquee behavior
and the pinned reference. The earlier [FINAL-001 record](history/MEDIA_V2_FINAL001_2026-11-18.md)
contains compatibility and the first frozen native run. The
[optional DSP trial](MEDIA_V2_OPTIONAL_DSP_TRIAL.md) awaits separate live
authorization. Physical input and presentation parity, actual providers,
and live device processing remain external evidence.

Git is read-only. Preview actions are limited to owned synthetic data.
The original source manifest and receipts are under .git/final-001-perf. Fresh
review receipts are under .git/media-review-20261118 and
.git/performance/final-review-20261118. All prior preview process and window
identities are stale.

## FINAL-001 compatibility and lifecycle continuation

The continuation record is
[MEDIA_V2_FINAL001_COMPAT_2026-11-18](history/MEDIA_V2_FINAL001_COMPAT_2026-11-18.md).
It added direct QSS identity assertions for the bar, popup shell, transport,
progress, EQ, presets, Audio and Lyrics controls after reparenting. It also
added a duplicate-metadata regression and fixed later recreation of a closed
`DefaultAudioOutputService` singleton. The duplicate-track behavior remains a
documented GSMTC identity limitation because the current model has no stable
platform track ID.

The focused selection passed 178 tests. The first full run encountered the
known timing-sensitive adaptive-bar oracle after 2,746 passes and one expected
AMD skip. The exact case passed in isolation. The serial full rerun passed
2,747 tests and one expected AMD skip in 159.65 seconds. Pyright, Ruff, schema,
frozen package proof and the source-bound synthetic preview passed.

The continuation benchmark passed every unchanged budget. Settled two-view CPU
was 11.36% against 12%, playing single-view event-loop p95 was 7.87 ms against
25 ms, event-to-title-paint-start p95 was 20.13 ms against 50 ms, and private
memory growth from cycle 8 to 24 was 65,536 bytes with zero handle or thread
growth. Receipts are under
`.git/media-final001-compat-20261118/` and
`.git/performance/final001-compat-20261118/`.

The current 540-input continuation manifest is
`79baed25858af5065147072c050aaad95cf779ea14237e15ff5a3d4998bd5f35`. The
Git index SHA remains
`7339732f0873efa846fdb5d1a1290a2fdddd6681c2f2673b7b4a30e0f48c4138`.
Live players, DSP, devices, profiles and Windows state remain untouched.

## FINAL-001 audio lifecycle and GSMTC continuation

The continuation record is
[MEDIA_V2_LIFECYCLE_GSMTC_2026-11-18](history/MEDIA_V2_LIFECYCLE_GSMTC_2026-11-18.md).
The audit covered persistent popup and equalizer references to the default
output service, the shared stereo-test service and APO writer callbacks. Closed
default services are now reacquired at later popup, controller and writer use
points. The Audio panel reacquires a closed stereo-test singleton before a
later Test action. Direct regressions cover each repaired path.

GSMTC remains the only supported general Windows source that preserves
cross-player session enumeration, metadata, artwork, timeline, events and
transport commands. SystemMediaTransportControls and MediaPlayer are
app-owned. WASAPI can complement GSMTC with process and endpoint diagnostics,
but it has no media metadata or transport contract. No stable track identifier
is exposed by the current GSMTC model.

The focused lifecycle selection passed 214 tests. The serial full suite passed
2,751 tests and one expected AMD skip in 166.75 seconds. Strict Pyright, Ruff,
schema export, build, package proof and the source-bound synthetic preview
passed. After the installed YASB process exited, the first clean benchmark
measured settled two-view CPU at 12.96% and the second measured 15.88%, both
against the unchanged 12% cap. Both comparators failed only that CPU check.
The clean benchmark uses an injected fake output and does not exercise the new
closed-service branches, so the CPU result is not attributed to the lifecycle
changes. The attribution helper measured 8.37% in the final hidden-popup
sample. The subsequent clean3 benchmark measured 9.14% settled two-view CPU
and its comparator exited 0. The prior continuation receipt remains the
passing 11.36% reference.

Receipts are under `.git/media-final001-audio-lifecycle-20261118/`,
`.git/performance/final001-audio-lifecycle-clean-20261118/` and
`.git/performance/final001-audio-lifecycle-clean2-20261118/`,
`.git/performance/final001-audio-lifecycle-clean3-20261118/` and
`.git/performance/final001-audio-cpu-diagnostic-20261118/`. The current 540-input
manifest SHA-256 is
`e258d72b8416f9d7acd65de40f03f92de71f488a97dd6daf8e915f10acd4248d`.

Remaining work is external evidence for physical mixed-DPI, compositor and
presented frames, production-main startup, physical input, real providers and
live DSP. Duplicate-track identity also awaits a stable platform or provider
identifier. The optional DSP deployment proposal and rollback preparation are
complete for separate authorization.

The detailed dependency graph, runtime flow, popup state machine, shutdown
order and architecture risks are in
[MEDIA_V2_ARCHITECTURE_2026-11-18](history/MEDIA_V2_ARCHITECTURE_2026-11-18.md).
This continuation also fixed closed Lyrics and APO writer singleton reuse with
drain-aware shared guards and regression tests.

The final architecture continuation passed 2,754 tests and one expected AMD
skip, refreshed the package and frozen preview, and passed the unchanged
benchmark at 7.61% settled two-view CPU against 12%. Its 540-input manifest is
`0a321ed283abb1d88a60460c60ca9d6a91271a708d9a132bc7f37ae2b95cadb3`.

The architecture3 continuation on 19 November 2026 added cancellation-safe
drain tasks for Lyrics, APO writer and stereo Test shared owners. The first full
suite sample hit the known timing-sensitive section oracle after 2,755 passes.
The serial rerun passed 2,756 tests and one expected AMD skip. The final
unchanged benchmark passed at 9.10% settled two-view CPU against 12%, with
1.03 ms event-loop p95, 15.02 ms title-paint p95, zero settled timers/readers/
jobs and zero handle/thread growth. The final manifest is
`e761115f4aac2d349feeb8d08dd1c3637b76510fc316c38a5f2ae6c09b55449b`.

## Architecture4 offline continuation

The current offline source includes deleted-QObject guards for the default
output, MediaBackend and APO writer singletons, plus the locked event-loop
snapshot in `WindowsMediaSource._post`. Dynamic QSS assertions now cover popup
state, player-selection mode, transport shape and the Lyrics picker ID.
The architecture4 source manifest, rebuilt package proof and passing synthetic
frozen receipt are under `.git/media-v2-architecture4-20261119/`.

The final full suite passed 2,761 tests and one expected AMD skip. The unchanged
benchmark comparator passed under
`.git/performance/final001-architecture4-repeat2-20261119/` with 11.462%
settled two-view CPU against the unchanged 12% cap. Live provider, physical
presentation, input, endpoint and DSP evidence remain external gates.
Receipts are under `.git/media-v2-architecture3-20261119/` and
`.git/performance/final001-architecture3-20261119/`.

## Architecture5 retained-owner continuation

Closed and deleted writer, backend, output and adapter owners now rebind through
their existing shared factories. The backend shared drain is guarded during
`aclose_shared()`, and queued legacy refreshes cannot create a fresh native
backend after shutdown. Architecture5 receipts are under
`.git/media-v2-architecture5-20261119/` and
`.git/performance/final001-architecture5-repeat1-20261119/`.

The final full suite passed 2,766 tests and one expected AMD skip. The unchanged
benchmark passed with 9.911% settled two-view CPU against the 12% cap. Live
provider, physical presentation, input, endpoint and DSP evidence remain
external gates.
