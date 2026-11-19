# Media V2 fresh architecture and compatibility review

18 November 2026. This review used the dirty checkout at `E:\hi o\yasb` on
branch `codex/sync-upstream` with HEAD
`c48acececa31006db98c21fca90b04e8b3cd233a`. The pinned upstream ancestor
`37928dfeacc579948c4b4bf12e169bcbf6006ff2` remained present. The 540-input
source manifest matched before implementation work and still matches the
current source. Its SHA-256 is
`b1a74c092a06f43814527e5fbdfbd8b411098c0ac5a2d4c14df1469b30c05d56`.

## Changed

- No production or test source change was justified by the review.
- Updated `docs/NEXT_SESSION_HANDOFF.md` and `docs/ACTIVE_MEDIA_BATCH.md` with
  the fresh findings and receipts.
- Added this history record. No Git index, refs, branches, worktrees, players,
  devices, Windows settings, live profiles or APO targets were changed.
- No comments were removed. The reviewed comments document ownership,
  cancellation, persistence, provenance or non-obvious rendering behavior.

## Findings and decisions

The current Media V2 entry point remains the existing YASB `WidgetBuilder`
contract. `MediaWidgetV2` keeps `validation_schema`, inherits the base callback
vocabulary and registers `toggle_media_menu`, `play_pause`, `previous`, `next`,
`automatic_selection` and `toggle_compact`. Its shared `MediaBackend` retains
source-generation invalidation, metadata revision gates and cancellable task
ownership. Popup suspension, artwork and background coalescing, DiscArt capture
leasing, Lyrics draining and the Equalizer APO single-worker queue matched
their current callers and focused tests.

No high-confidence repair was found. Two lower-priority contract risks remain
open for a future product decision. Track equivalence uses title, track number
and album where available, so duplicate tracks with identical metadata can
retain presentation until a new timeline event. The default audio-output
singleton remains closed after explicit shutdown, which matters only when a
process recreates that service after teardown. A compatibility coverage gap
also remains for direct assertions on popup output, device, source, timeline
and Lyrics action IDs. Current source creates those documented identities.

## Verification

All commands used the private `.git/sync-venv` environment and isolated
profiles where applicable.

| Check | Result |
| --- | --- |
| Focused Media V2, fidelity, backend, popup, seek and Apply tests | 92 passed, exit 0 |
| Additional backend, image-cache and Lyrics owner selection | 46 passed, exit 0 |
| Initial full `pytest -q` | 2744 passed, 1 expected AMD skip, 1 timing-sensitive Lyrics failure, exit 1 |
| Isolated failing Lyrics case | 1 passed, exit 0 |
| Full `pytest -q` repeat | 2745 passed, 1 expected AMD skip, 1738 warnings, 154.98 s, exit 0 |
| Strict Pyright 1.1.414 | 502 files, zero diagnostics, exit 0 |
| Ruff check | exit 0 |
| Ruff format check | 509 files already formatted, exit 0 |
| Schema export | 60 widgets, exported bytes equal root schema, exit 0 |
| Frozen build | exit 0 in 86.86 s with the existing cx_Freeze warnings |
| Frozen package proof | 30 module matches, ordinary entry match, 2644 original ZIP entries preserved, 60 schema widgets, exit 0 |
| Current unchanged-budget benchmark | All checks passed, comparison exit 0 |
| Current benchmark closed two-view CPU | 10.59% of one core against 12% |
| Current benchmark playing single-view event-loop p95 | 5.94 ms against 25 ms |
| Current synthetic frozen preview | 625×565 popup, motion cancellation, Apply/discard, Lyrics loopback and local import, Audio/Test retirement, zero capture readers and timers, no source actions, chooser unchanged, exit 0 |

The benchmark receipt is `.git/performance/final-review-20261118`, with
benchmark SHA-256
`f379e3db8011e299a1b8cc5c1f212e161471f7505740a16e074c22b76a2790a4` and
budget SHA-256
`83a16382417cf26956eaefc627a532453071816da0e301b875cc5bc455060657`.
Fresh build, package and native receipts are under
`.git/media-review-20261118`. The successful synthetic profile was
`native-profile-review2`, PID 32164. The first attempt stopped at the harness
run gate before an owned gate writer was attached and is retained as a failed
coordination attempt.

## Remaining concerns

Physical mixed-DPI and compositor behavior, presented frames, ordinary
production-main startup, full physical input, live providers and live DSP
remain unverified. The duplicate-metadata track identity and post-shutdown
audio singleton cases need a contract decision before changing their owners.

