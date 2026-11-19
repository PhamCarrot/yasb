# FINAL-001 continuation checklist

This checklist records the agreed FINAL-001 scope and acceptance criteria.
Read the [current handoff](NEXT_SESSION_HANDOFF.md) and
[FINAL-001 record](history/MEDIA_V2_FINAL001_2026-11-18.md) for completed work,
current receipts and remaining evidence. Only one main agent may edit the
checkout. Helpers may do bounded read-only research and review.

## Scope and authorization

Work in `E:\hi o\yasb`. Preserve the dirty checkout and all custom widgets.
Keep Git read-only: no stage, commit, branch, worktree, push or PR. No global
installs, live player commands, actual audio playback/device opening, live APO
configuration changes or Windows settings changes. Native automation is resumed
only for the owned isolated preview. No legacy autosave mode.

The target remains pinned Serpantinum `73b1cb79768641a52caf9f1d23a9a26f850f993e`.
Use numeric/behavioral contracts and independently written MIT implementation.
Do not copy or translate AGPL code, shaders or assets. Reference videos have
older labels/data/themes and unknown desktop scaling; they do not establish
pixel or presented-frame equality.

## 1. Complete targeted compatibility assertions

The read-only review identified these gaps; its findings are not test results.
Check current implementation before adding assertions.

- Config migration: `src/core/validation/widgets/yasb/media_v2.py` normalizes
  `bar_scrolling`, popup `scrolling`, `placement`, `edge_offset`, `bar_offset`,
  `widget_offset`, `direction: auto`, background `native_blur` and `mode: qss`,
  and retired `preset_effect: blur_slide`. Assert canonical fields win, the
  caller's input is unchanged, deprecated keys disappear from model_dump and
  invalid boolean strings fail. Include `native_blur: "perhaps"` rejection.
- Manual Apply: extend `tests/widgets/test_equalizer_apply.py` with accepted
  deprecated `write_debounce_ms` values 50 and 500. Wait beyond 500 ms and assert
  writer generation and actual bytes do not change before explicit Apply.
  Do not add an autosave execution path.
- Callback vocabulary: preserve `toggle_media_menu`, `play_pause`, `previous`,
  `next`, `automatic_selection`, `toggle_compact`, plus base callbacks. Validate
  config strings/keybindings without global hooks or executing commands.
- Documented QSS identities: assert IDs/classes on existing references for
  bar/popup, transport, progress track/fill/handle, EQ bands, presets and header
  controls after reparenting. IDs intentionally repeat between bar and popup;
  do not require global uniqueness. New band wrappers can affect undocumented
  direct-child selectors; documented descendant/ID selectors remain the target.

Suggested legacy input:

```yaml
bar_scrolling: {enabled: false, speed: 55, delay: 200}
popup:
  scrolling: {speed: 65, delay: 300}
  placement: screen
  direction: auto
  edge_offset: 9
  bar_offset: 61
  background: {mode: qss, native_blur: "false"}
  equalizer: {preset_effect: blur_slide}
```

Expected normalized values: bar scrolling false/55/200, popup scrolling65/300,
direction down, offsets9/61, blur false, background color, effect none. Recheck
these against current validators rather than treating this note as an oracle.

## 2. Final fidelity review

Retain the stable MVV finding IDs in the FID records. FID-002 is an independent
raster adaptation; shader shadow/hover-colour interpolation and the shared
cover overshoot differ in small details. Compare the current captures and
pinned contracts before deciding whether to refine those differences. Do not
claim pixel-perfect motion from source timing constants or Qt grabs. Keep the
intentional Windows Tab/Ctrl+Tab accessibility behavior. The lower page235 and
band155 heights are preferences, not fixed acceptance sizes; canonical default
allocation is227/152 at scale1, with all controls reachable.

## 3. Frozen UI proof

The existing source preview prepends `root/src`; it is not frozen UI evidence.
Current builds already include QtMultimedia.pyd, Qt6Multimedia.dll, Windows and
FFmpeg multimedia plugins and five FFmpeg dependencies through cx_Freeze's Qt
hook. Verify against the pinned private venv again after the final build.

A researched private harness route preserves production package entries:

1. Copy the current dist into an owned `.git/final-001/frozen-preview` directory.
2. Copy its yasb.exe as yasb_preview.exe.
3. Add `__init__yasb_preview.pyc`, byte-identical to `__init__yasb.pyc`, and an
   isolated `__main__yasb_preview.pyc` shim to the private library.zip. Preserve
   every original ZIP entry byte; add each new entry exactly once.
4. Use pinned Python 3.14/optimization1 and a valid 16-byte pyc header. The actual
   entry naming is `__main__yasb.pyc`, not `yasb__main__.pyc`.
5. Use explicit owned evidence/repo paths: frozen __file__ is inside library.zip.
6. Put fixture-only helpers in the private harness. Do not import entire test
   modules or prepend the venv/root/src: pytest and QtTest are not packaged, and
   PyQt6's extend_path could silently load external binaries.
7. Before input, assert core/widget/settings origins use the copied archive and
   PyQt6 native modules use copied lib/PyQt6. Inject fake media/output/capture,
   lyric transport and Test sink before constructing any widget. Never reach a
   real device, player, external lyric provider or live APO target.
8. Inventory with Node REPL @oai/sky and bind the actual executable/profile/window.
   This proves packaged widget runtime under an isolated entry, not ordinary
   production-main startup or real endpoint processing.

The mechanism was researched read-only against freeze_core/initscripts startup
and cx_Freeze executable dispatch. The architecture4 package proof and frozen
synthetic receipt now verify the copied package and isolated entry. Ordinary
production-main startup, real providers, physical input and endpoint processing
remain separate external gates.

## 4. Reapply unchanged performance budgets

After competing builds/tests finish, run the owned raster benchmark:

```powershell
& '.git/sync-venv/Scripts/python.exe' '.git/performance/benchmark.py' final-001
```

Keep `.git/performance/budgets.json` unchanged. Compare the result explicitly;
the benchmark records metrics but does not enforce budgets itself.

| Metric | Existing budget |
|---|---:|
| Identical two-view artwork | 1 decode + 1 background prepare |
| Shared cache | at most 8 entries  / 32 MiB including accounting |
| Settled closed popup | 0 timers/readers/actual jobs |
| CPU, percent of one core | closed12 / paused45 / playing70 / two-view100 |
| Event-loop delay p95 | single25ms / two-view50ms |
| Event-to-title-paint start p95 | 50ms |
| Warm growth | at most 8MiB /4 handles /1 thread |

The script records 48 cycles and native thread identities. Its own hash set only
covers media_v2*.py; attach the full current source manifest including services.
It never selects Lyrics/Audio/Test, so add separate bounded activity/drain
observations for those owners. Paint-start timings are not presented frames.
Do not claim a CPU/FPS improvement without an attributable measurement.

## 5. Stable integrated gates and receipts

Use the private environment and `.git/<batch>/run_check.py` to isolate profiles
and record exact cwd/command/exit/time. Do not overwrite prior batch evidence.
The runner sets QT_QPA_PLATFORM=offscreen; native Windows preview is separate.
Use PowerShell `login:false` in the execution tool: the user's normal shell
profile produced an unrelated oh-my-posh disk-access error on18November.
Do not modify that profile or system settings.

Run Ruff check/format-check, strict Pyright, full pytest, schema export in a
private output directory and frozen build from src. A zero-test selection is
not a pass. Expected AMD atiadlxx.dll absence remains explicit. Run full tests
without competing builds/types to avoid the known timing-sensitive bar oracle.
Compare schema bytes/widget count, both bundled guides and packaged production
code objects against source, and retain a source hash manifest/archive.

## 6. External gates and concrete deployment preparation

Full parity remains conditional on real endpoint association/host permissions,
audible processing, actual provider availability, physical mixed-DPI/native
compositor observations and presented-frame evidence. Offline IPC frames or
saved configuration alone do not prove an endpoint processes sound.

Prepare an exact optional DSP artifact/build identity, read-only discovery,
proposed file changes, backup/restore paths and rollback procedure before
requesting additional live authorization. Do all independent work first. Do not
activate an endpoint, register/install/restart anything or alter live profiles
without explicit user authorization. Record bootstrap behavior while YASB is
absent and retain the optional processor's provenance/notices.

## Finish

Update the current handoff and a new batch record with source identity, exact
checks, native/visual/performance evidence and remaining gaps. Preserve older
records separately. No push. Do not mark an unavailable external gate complete.
