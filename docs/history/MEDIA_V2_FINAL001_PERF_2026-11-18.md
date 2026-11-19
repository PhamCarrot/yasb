# FINAL-001 performance follow-up

18 November 2026. Checkout `E:\hi o\yasb`, branch `codex/sync-upstream`,
HEAD `c48acececa31006db98c21fca90b04e8b3cd233a`. All 540 inputs matched the
prior FINAL-001 manifest before editing. The original index SHA-256 was
`7339732f0873efa846fdb5d1a1290a2fdddd6681c2f2673b7b4a30e0f48c4138`.
The pinned upstream remains an ancestor.

## Changes and attribution

- `MediaText` reuses its DPR-sized scratch image and width-specific edge
  gradient. It caches the width measurement and a single shaped Qt line
  for the common steady, overflowing single-line case. Both copies are
  drawn at their original fractional offsets. The original rectangle
  layout handles crossfades, complex or decorated text, and clips that
  require it. Font and style changes invalidate cached layout, and hiding
  retires the scratch image and shaped line.
- `DiscArt` keeps ticking capture, analysis, and cover angle. It requests
  a repaint when the visible spectrum, glow, geometry, or rotating cover
  changes. The silent fallback has no angle-dependent pixels. The renderer
  reads its accent and logical scale once per paint.
- Tests cover shaped layout reuse, font invalidation, hide retirement and
  the disc's stationary fallback, rotating current and fading covers, and
  active synthetic spectrum. The current pixel check matched all 144
  pre-edit frames at DPR 1, 1.5 and 2 and exercised cached layout on 36
  frames. The fixture includes mixed scripts, wrap, fractional offsets,
  disabled text, narrow viewport and fades.

The alternating process-local marquee replay measured a median 15.78 ms
before and 10.29 ms after per 120 grabs, a 34.8% reduction in that replay.
An instrumented benchmark replay measured 72 disc paints from 43 ticks
before and 33 from 43 after. Those instrumented runs measured 95.99 ms
across 250 bar text paints before and 55.43 ms across 248 after. The disc
and paint-count comparison used the revision before the final wrap
robustness change. It is diagnostic evidence alongside the current-source
A/B and pixel comparisons.

## Acceptance method and iteration history

The benchmark and budgets kept SHA-256
`f379e3db8011e299a1b8cc5c1f212e161471f7505740a16e074c22b76a2790a4` and
`83a16382417cf26956eaefc627a532453071816da0e301b875cc5bc455060657`
respectively. All canonical runs used the existing offscreen benchmark
with synthetic capture, media, output and owned profiles.

The initial run reproduced the settled two-view CPU miss at 18.70%.
The scratch-only iteration remained above 12% at 13.64%. The first
layout variant's direction guard bypassed its cache on QImage painters,
which use automatic direction. The active-cache revision was verified
to take the optimized path. That revision included a repeat-draw cull
which was removed in the final revision to preserve custom glyph
overhang.

Earlier trials are retained in `.git/final-001-perf/` and
`.git/performance/final-001-perf-*/`, including the run that passed at
10.53% closed CPU and 7.16 ms playing p95 on the preceding revision.
Other runs showed CPU and jitter misses. The pre-confirmation system
snapshot recorded significant host activity across all 12 logical CPUs.
The final confirmation runner waits for three read-only host samples at
or below 30% total load, then invokes the unchanged benchmark and
comparator. Host settings, app priority and affinity stay as found.

Known predecessor's evidence and frozen runtime are in
[the first FINAL-001 record](MEDIA_V2_FINAL001_2026-11-18.md).

| Current-source quiet-start run | Settled two-view CPU (limit 12%) | Single-view playing p95 (limit 25 ms) | Comparator |
| --- | ---: | ---: | ---: |
| `final-001-perf-quiet-first` | 15.13% | 7.31 ms | exit 1 |
| `final-001-perf-quiet-repeat` | 12.22% | 4.58 ms | exit 1 |

Both benchmark commands exited 0 and captured all 48 reopen cycles. The
repeat also missed empty-closed CPU at 14.91%, before there was any active
marquee. Every other limit passed in those two runs. Settle left zero
popup timers, readers and worker jobs.

The independent closed-state breakdown measured 46.875 ms of process
CPU in the benchmark's resource snapshot at the start of its two-view
closed sample. The snapshots in the empty and paused closed samples each
took 78.125 ms of CPU. The canonical CPU measurement includes that work,
which can contribute roughly 2 to 4 percentage points in its two-second
window. Four three-second diagnostic windows with both marquees moving
measured 5.21% to 10.95% (median 9.65%). Alternating stationary-marquee
controls had a 4.18% median with both bars still visible. The resource
measurements and controls ended with exit 0. They show application work
and measurement overhead separately. The canonical results retain the
original accounting and thresholds.

The final-source canonical run after the test fixture annotation correction
passed the comparator (benchmark and comparison exit 0). It measured
**11.36%** settled two-view closed CPU against **12%**, and **7.57 ms**
single-view playing p95 against **25 ms**. Peak single-view p95 was
7.57 ms and peak two-view p95 was 26.06 ms against 50 ms. It recorded
one shared artwork decode and one background preparation, 8 shared
entries totaling 6,458,532 bytes, and 20.89 ms title paint-start p95.
There were 48 reopen cycles. From cycle 8 to 24 private memory grew
40,960 bytes, handles and threads grew by zero, and native thread IDs
were stable after cycle 8. Settled popup timers, capture readers and
worker jobs were zero. Result, complete limit comparison and its current
manifest are at `.git/performance/final-001-perf-final-source/`.

## Integrated verification

The final source manifest contains 540 inputs and has SHA-256
`b1a74c092a06f43814527e5fbdfbd8b411098c0ac5a2d4c14df1469b30c05d56`.
Only `media_v2_motion.py`, `media_v2_disc.py` and `test_media_fidelity.py`
changed relative to the prior manifest. The full source archive is
`.git/final-001-perf/verified-source.zip`.

- Focused Media V2 and fidelity pytest selection had 30 passes and exit 0.
- The first full pytest exited 1 on the existing Lyrics browse timer
  because the 20 ms timer had yet to fire at the 40 ms assertion.
  The isolated case passed in 0.81 s. The serial full repeat exited 0 with
  2,745 passes and one expected AMD DLL skip in 159.58 s. Lyrics code and
  assertions were preserved. The repeat recorded 1,748 qasync warnings.
- The first strict Pyright found two diagnostics on an untyped synthetic
  spectrum callback. The callback now has an explicit `str` parameter and
  `list[float]` result, with the same fixture values. The final strict
  run exited 0 with zero diagnostics across 502 files. Final Ruff check
  and format check both exited 0, with 509 files already formatted.
- Schema export exited 0 and matched all 60 widget registrations and
  schema bytes. The build from src exited 0 in 65.74 s. Package comparison
  exited 0 with 30 production module matches plus the ordinary entry and
  both guides. The isolated archive preserved 2,644 original entries and
  added exactly the two preview dispatch entries.

Exact commands, cwd, receipts and logs are under `.git/final-001-perf/`.

The owned x64 frozen Windows run used `native-profile-perf`, PID 34832,
HWND 10685746. Node Sky bound the executable path and HWND before the
automation gate. Widget and settings origins were inside the copied
archive, Qt originated in the package, and the process used System32 ICU.
The 625×565 popup passed the seek wave, pause mid-decay, interrupted
close/reopen, manual Apply/discard, one loopback Lyrics request and
owned import, and page-leave and close cancellation of two 614,400-byte
fake PCM sends. All popup timers, capture readers and surface workers
retired. The process exited 0 with an unchanged chooser stamp and no owned
windows in final Sky inventory. No media-source actions were recorded.
This run verifies automated packaged Windows Qt behavior. Full input,
compositor and presented frames and live provider/DSP evidence remain open.
