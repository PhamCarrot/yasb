# FINAL-001 compatibility and lifecycle continuation

18 November 2026. This offline continuation used the dirty checkout at
`E:\hi o\yasb`, branch `codex/sync-upstream`, HEAD `c48acececa31006db98c21fca90b04e8b3cd233a`.
The pinned Serpantinum target remains
`73b1cb79768641a52caf9f1d23a9a26f850f993e`. No Git index, refs, live players,
devices, Windows settings, profiles or APO targets were changed.

## Changed

- Added direct QSS identity assertions for the Media V2 bar and popup shell,
  viewport, border, main/details/output/timeline rows, artwork, title and
  artist labels, source and selector controls, player menu ownership,
  elapsed/duration labels, separator, presets container, transport controls,
  EQ bands and reparented Audio and Lyrics header controls.
- Added a backend regression test documenting duplicate metadata behavior. A
  refresh with the same title, album and track number but a changed artist
  preserves the timeline until an explicit timeline event arrives while the
  seek revision advances. GSMTC metadata has no stable track identifier, so no
  heuristic identity change was introduced.
- Fixed `DefaultAudioOutputService.instance()` to replace a closed singleton
  before returning it to a later owner. The focused test replaces construction
  and shutdown with device-free doubles and verifies a fresh instance.

## Verification

The focused compatibility, popup, backend, sections and Apply selection passed
178 tests in 13.76 seconds. The first full suite run reached 2,746 passed and
one expected AMD skip, then hit the known timing-sensitive adaptive-bar oracle.
That exact case passed alone. The serial full rerun passed **2,747 tests and one
expected AMD skip** in 159.65 seconds, exit 0. It emitted 1,714 qasync
deprecation warnings.

Strict Pyright 1.1.414 analyzed 502 files with zero diagnostics. Ruff check and
format check passed, with 509 files already formatted. Schema export registered
60 widgets and its private output matched the current root schema bytes.

The current frozen build exited 0. Private package proof matched 31 production
modules plus the ordinary entry, preserved 2,644 original ZIP entries and added
only the two owned preview dispatch entries. QtMultimedia, both multimedia
plugins and the five FFmpeg dependencies were present, and no incompatible
bundled ICU was present.

The source-bound frozen synthetic preview used profile `native-profile-compat`
and exited 0. It passed the 625x565 popup, wave and pause-decay cancellation,
close/reopen, manual Apply/discard, loopback Lyrics and local import, Audio/Test
retirement, zero closed timers and capture readers, no media source actions,
unchanged chooser state and clean shutdown.

The unchanged benchmark and comparator passed every budget. The benchmark and
private receipts are under `.git/performance/final001-compat-20261118/`.

| Metric | Result | Budget |
|---|---:|---:|
| Settled two-view closed CPU | 11.36% | 12% |
| Single-view playing event-loop p95 | 7.87 ms | 25 ms |
| Identical artwork work | 1 decode / 1 background prepare | 1 / 1 |
| Shared cache | 8 entries / 6,458,532 bytes | 8 / 33,554,432 |
| Settled timers/readers/jobs | 0 / 0 / 0 | 0 / 0 / 0 |
| Event-to-title-paint-start p95 | 20.13 ms | 50 ms |
| Cycle 8 to 24 private growth | 65,536 bytes | 8 MiB |
| Cycle 8 to 24 handles / threads | 0 / 0 | 4 / 1 |

The current 540-input source manifest is
`.git/media-final001-compat-20261118/verified-source-sha256.json` with SHA-256
`79baed25858af5065147072c050aaad95cf779ea14237e15ff5a3d4998bd5f35`.
Compared with the fresh review manifest, only
`src/core/widgets/services/media/audio_device.py`,
`tests/widgets/test_media_backend.py`,
`tests/widgets/test_media_fidelity.py` and
`tests/widgets/test_media_v2.py` changed. The Git index SHA remains
`7339732f0873efa846fdb5d1a1290a2fdddd6681c2f2673b7b4a30e0f48c4138`.

## Remaining evidence

Duplicate metadata remains a documented product-contract limitation because
GSMTC does not expose a stable track ID in the current model. A stronger signal
such as a platform track identifier would be needed before changing the owner.
Existing controllers that retain an audio service after explicitly shutting it
down must not continue using that closed QObject. Later `instance()` calls now
receive a fresh service.

Physical mixed-DPI and compositor behavior, presented frames, ordinary
production-main startup, full physical input, live providers and live DSP
remain outside this offline batch.
