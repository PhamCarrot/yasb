# Manual EQ Apply workflow

Completed locally on 16 November 2026 after MV-003. Main agent owned edits; helpers reviewed read-only. No Git writes, live APO edits, player commands or system changes.

Manual slider motion/release now edits only a local draft. No debounce timer or legacy autosave branch remains. Apply submits one whole-curve snapshot; presets remain immediate. Close/tab hide discards unsubmitted changes. Per-canonical-file draft leases prevent another view from overwriting/cancelling an editor's transaction. Commit authorization uses the current destination, and the writer retires only the captured token before notifying views, preserving a newer reentrant draft. Retarget uses committed intent while local edits stay unsubmitted.

The existing panel now exposes Apply/Saving/Saved/Retry states, with a read-only foreign-editor state and accurate visual-only behavior. Saved refers to successfully persisted config, not verified DSP activation. Config/guide/schema mark `write_debounce_ms` deprecated and ignored; the key remains readable. Existing selectors/layout remain intact. Schema changed only that field's description. Source edits: controller/writer, equalizer panel, popup close, scoped styles and validation model; no new backend/framework.

## Verification

Private environment `.git/sync-venv/Scripts/`; command/cwd/exit receipts under `.git/media-apply/`.

- RED manual-release test failed before the change: owner generation increased from1 to2 without Apply.
- Focused four-file suite: **57 passed**, exit0 (`focused-reviewed.log`), including eleven Apply tests for atomic commit/discard, leases, output/target change, failure/retry, presets, visual-only, actual panel button/tab hide and reentrant drafts.
- Full current rerun `python -m pytest -q`: exit0, **2261 passed,1 skipped**, 56.55s (`tests-rerun.log`). Initial run had the known unchanged adaptive-bar first-frame failure: 1failed/2260passed/1skip; rerun passed without edits. SDK MSVC14.44.35207 / SDK10.0.26100.0 x64; AMD DLL skip explicit.
- Ruff lint/format exit0 (479files); strict Pyright exit0 (474files,0errors/warnings). Schema export exit0 (60widgets/359definitions); semantic comparison allowed only the deprecated-field description. Root schema updated accordingly.
- Frozen build exit0; all five changed code modules match packaged bytecode. Existing duplicate-resource/optional-module warnings persist. No full frozen application run claimed.
- Offscreen qasync actual `open_at_parent`/real writer: slider-release writes0, Apply requests1/full curve persisted, close discards with no new request, Saved→Apply→Saved, actual writer joined. Popup625x568. Readable captures in `.git/media-apply/captures/`.
- Initial offscreen captures had missing font glyphs. Harness now registers installed Segoe/Cascadia/GoMono TTFs only within the process, records families/hashes, and leaves offscreen mode intact. Corrected captures were visually inspected. No font install/system/source fix was needed.
- Review-found destination-lease and post-notification cleanup issues were fixed and tested; final bounded reread found none. Test harness initially called an invented slider conversion helper; corrected to the existing slider SCALE, without weakening assertions. Whitespace/source hashes checked.

## Authorized native preview

The user explicitly resumed **native UI automation for the prepared isolated preview only**. This supersedes the earlier Escape pause for that scope; live players, APO files and system settings remain unauthorized.

Preview source `.git/media-preview/preview.py` smoke-tested then launched privately with existing Pythonw. Actual PID9004, returned window5048368/title `YASB Media Milestone Preview - isolated`, profile `.git/media-preview/profile-afb18bff`, synthetic backend/capture/output and owned registry/files. Inputs used Node REPL `@oai/sky` with returned identities and fresh screenshot/accessibility observations.

Observed: mouse open; band edit shows Apply while owned file remains Flat; Escape discards and returns focus to Open media player; Space reopens; explicit native Apply shows Saved and writes31Hz gain7 to owned file. Host closed via its observed Close button; window disappeared and clean-shutdown receipt verified. No live configuration changed. Native receipt: `.git/media-apply/native-checks.json`.

Native verification also reproduced **MV-006-ENTER**: Return on focused InfoButton did not open the popup, while Space did. Source sets activation mode for Return/Enter but delegates to a non-default QPushButton that does not click. Fix in the separate MV-006 batch. MV-005 work-area viewport remains next. The preview scope does not establish live DSP, real-player behavior, mixed physical DPI or complete parity.

Entry copies/source manifest499inputs, build hashes, source-bound runtime/capture/font/native receipts and `final-verification.json` are under `.git/media-apply/`. Earlier milestones remain preserved; continue the active queue without pushing.
