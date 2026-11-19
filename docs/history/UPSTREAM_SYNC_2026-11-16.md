# YASB upstream sync - locally verified

Updated 16 November 2026. The requested local sync is complete. **Nothing has been pushed. Computer Use is paused after the user pressed physical Escape.** No further native UI input is authorized until the user resumes it.

## Source and ownership

Use `E:/hi o/yasb`, branch `codex/sync-upstream`. The local merge preserves fork parent `5c791bdb0604015e1257d91a45dc6530bd2a90c1` and includes upstream `37928dfeacc579948c4b4bf12e169bcbf6006ff2`. A fresh `git ls-remote upstream refs/heads/main` matched that upstream tip after verification. `main` and `codex/backup-before-sync` retain the original fork. The resulting local merge commit ID and ancestry are recorded in `.git/sync-investigation/final-verification.json`; read the actual Git state before further work.

One main implementation agent owned all source/Git changes; helpers performed bounded read-only review. No remote publication, live YASB profile edits, real playback commands, Equalizer APO writes, service restarts, or Windows settings changes were performed. Keep these constraints unless the user explicitly changes them.

## Decisions and resulting behavior

- Restored all upstream documentation/tooling, including 44 silently retained deletions, and upstream DPI/bar fixes.
- Retained Media V2, its components, shared MediaBackend/Windows source/model, optional APO support and both custom guides. Kept async shutdown drain and build inclusions.
- Kept one media owner: the legacy WindowsMedia adapter delegates to MediaBackend; Media V2 and the visualizer label share it. Replaced the deleted singleton import with upstream-style lifetime-aware local Qt singleton.
- Kept coherent upstream loopback/capture-source/idle lifecycle; reapplied custom title/artist formatting, scrolling and independent visualizer opacity. Media Lite keeps the artwork-background QSS class while retaining upstream icon/AUMID imports, DPI handling and popup clipping.
- Kept upstream dependencies and strict Ruff/Pyright/test policy, including no pywin32. The old unused numpy/pyaudiowpatch pins were not reintroduced.
- Added explicit types and Qt override signatures needed by upstream strict checking. Qt properties use the existing upstream getter/setter binding pattern. No blanket type exclusions or weakened tests. Narrow Pillow/comtypes missing-stub annotations follow upstream conventions.
- Regenerated schema from models: 60 registered widgets and 359 definitions, retaining Media V2 and custom label options alongside upstream capture source.

## Verification in this implementation session

Private environment: `.git/sync-venv` using Python 3.14.10, Qt 6.10.2, Ruff 0.17.1 and Pyright 1.1.414. Logs, exact commands, profiles and source hashes are local in `.git/sync-investigation/`. Verified source manifest: `verified-source-sha256.json`, SHA-256 `ef85c241594d054a175369c4316c5c84073e8553e122fd551955072d9dfdc565` (494 source/test/schema/guide inputs). Check it before reusing build evidence.

Final checks:

- `.git/sync-venv/Scripts/ruff.exe check .`: exit 0, all checks passed (`ruff-lint.log`).
- `.git/sync-venv/Scripts/ruff.exe format --check .`: exit 0, 474 files already formatted (`ruff-format.log`).
- `.git/sync-venv/Scripts/pyright.exe --pythonpath <private Python> --outputjson`: exit 0, 469 files, **0 errors / 0 warnings** (`pyright-pass5.json`). Earlier failed runs (3473, 451, 105, 51 errors) are diagnostic history, not passes.
- Private Python `-m pytest -q`: exit 0, **2198 passed, 1 skipped in 51.90 s** (`tests-final.log`). Includes 14 focused custom checks: shared selection, command targeting, unknown-repeat compatibility, late session removal, shutdown, labels, idle/disc leases and all four popup artwork layouts. Windows SDK checks used MSVC 14.44.35207 / SDK 10.0.26100.0 / x64. The sole skip is `atiadlxx.dll` unavailable on this machine.
- Private Python `src/core/validation/export_schema.py` under owned profile: exit 0, no import failures; schema contracts checked (`schema-export.log`).
- From `src`, private Python `build.py build`: exit 0 (`build.log`). Build folder: `src/dist`. Custom modules/validation are in `lib/library.zip`; both guides and schema byte-match source. `yasb.exe` SHA-256: `674b615696f03453ccb5b1b6f4ed45fcbfd5ebdd3dfa10462e6347e6f1915cc9`. No MSI was installed.
- Real, read-only GSMTC backend probe: exit 0, manager ready, **0 active sessions**, no errors, 0 commands; close drained all tasks and timer (`native-media-readonly.json`). This does not establish real-player playback behavior.
- Custom delta `git diff --check upstream/main` and unstaged whitespace check: exit 0. The raw pre-final staging index check exited 2 for 359 inherited upstream documentation/line-ending warnings across 45 paths (`whitespace-index.log`); upstream docs were preserved rather than reformatted outside scope.
- Independent read-only review found no concrete behavior loss in the 31 Qt properties, equalizer collaboration-state renames, typed closure captures, label integration or Windows source/task ownership.

## Native/visual evidence and remaining limits

The owned synthetic preview used the actual private interpreter/profile and current source. Node REPL `@oai/sky` inventoried and bound the exact returned window and executable; the main preview rendered Media V2, timeline and visualizer label. The user then physically Escape-stopped Computer Use. No further Computer Use calls were made. Native popup input was not completed reliably, so do not claim native popup/control parity. The preview's own receipt records closed=true, one source close and zero capture readers; it was already absent at process cleanup inspection. All three recorded preview playback actions went only to the synthetic source.

The four popup layouts rendered in the automated offscreen Qt tests. Real-player controls, real WASAPI/device switching, mixed-DPI interaction, optional APO configuration writes and ARM64 remain unverified. The frozen build emitted upstream-style optional-module/API-set and duplicate-resource warnings; build success is not a complete frozen-UI runtime claim. Preserve live profiles and the Computer Use pause.

## Next action

No implementation queue remains for this request. Let the user review the local sync branch/build. Do not push, publish, install, replace the live YASB setup or resume native automation without their instruction. For an explicitly requested future native check, use `.git/sync-investigation/preview.py` with the owned profile and bind fresh returned window identities; do not reuse old handles or coordinates.
