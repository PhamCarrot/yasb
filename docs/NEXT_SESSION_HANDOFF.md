# Media V2 implementation handoff

Updated 20 November 2026.

## Current checkout

- Repository `E:\hi o\yasb`, branch `codex/sync-upstream`, HEAD `c48acececa31006db98c21fca90b04e8b3cd233a`.
- The worktree remains dirty from earlier Media V2 and related source batches. Preserve those edits and do not reset or clean the checkout.
- This batch updated the Media V2 wave painting, paused visualizer scheduling, lyrics focus styling, Equalizer action presentation, lyric provider set, related tests and documentation. Git remains read-only in the checkout.
- No live YASB process, profile, player, device, endpoint, Equalizer APO state or Windows setting was changed.

The latest public Media V2 source publication is [a7d7c7a5](https://github.com/PhamCarrot/yasb/commit/a7d7c7a573feca5db8ca13e8b52c081ede0d2778). The current checkout contains later local source work, so the documentation below describes the checkout rather than a new publication.

## Current Media V2 contract

- The popup lower section contains Equalizer, Audio and Lyrics tabs when `popup.show_equalizer` is enabled. Local lyric-file import and the Audio Test action are not part of the current Media V2 contract.
- `popup.lyrics.provider_order` accepts LRCLIB, NetEase, Better Lyrics and Musixmatch in any unique order. Lookup follows that order after disabled Musixmatch is filtered. Musixmatch needs an enabled route and an API key.
- Equalizer band edits remain drafts until **Apply**. Presets apply immediately. `write_debounce_ms` remains accepted for compatibility and has no effect.
- The current UI fixes keep short progress-wave fills visible while clipping the styled frame to the authoritative progress fill. The paused visualizer no longer runs its ambient orbit timer. The clean Equalizer header hides its action box until a draft or recovery action needs it. Lyrics no longer draw a focus rectangle around the active line. Lower-section layout keeps the EQ band row, two-row preset box and tab strip reachable. The Lyrics scrollbar uses `media-lyrics-scrollbar`, and the Equalizer effect overlay resynchronizes after Lyrics-to-Equalizer navigation and resize.
- The guide documents the native processor fields, profile and endpoint binding, persistence versus processing status, and the x64-only optional DSP build. The ordinary package does not install or activate that DLL.

## Packaging and ARM64 CI

- From `src`, the ordinary package commands remain `python build.py build` and `python build.py bdist_msi`. The MSI is written under `src/dist/out/` with an `x64` or `aarch64` suffix.
- `src/build.py` detects x64 or ARM64 and selects the matching tray-hook and Everything DLL. The frozen package includes `schema.json`, `MEDIA_V2_GUIDE.md` and `MEDIA_VISUALIZER_LABEL_GUIDE.md`.
- The optional native Media V2 DSP is built from the repository root with `python -m src.build_media_dsp`. It requires x64 Windows and writes to `build/media-dsp/` with its receipt and vendor notices.
- `.github/workflows/tests.yaml` runs pytest on `windows-latest` x64 and `windows-11-arm` ARM64. The PR workflow has x64 and ARM64 package jobs. Release workflows use `x64` and `aarch64` artifact and MSI naming. These workflow paths do not provide local ARM64 runtime or presented-frame evidence for this checkout.

## Current-batch verification

The checks below were run against the current checkout after the source changes.

- The complete media and Equalizer widget set exited 0 with **552 passed, 1,298 warnings in 106.95 s**. The warnings are existing `qasync` deprecations.
- `python -m compileall -q src tests` exited 0.
- `python build.py build` and `python build.py bdist_msi` exited 0. The MSI is `src/dist/out/yasb-2.0.9-x64.msi`.
- The final UI benchmark exited 0. Common event-loop p95 improved from **3.19 ms to 1.39 ms** for paused-open and from **11.40 ms to 6.82 ms** for the two-window paused large-art case. The final playing-open p95 was **6.01 ms**. Large-art decode and background calls remained one each, with zero final readers.
- Ruff was unavailable in the project environment, so no Ruff result is claimed for this batch.

## Remaining evidence gaps

Production-main startup, physical popup input, compositor-presented frames, mixed-DPI displays, live lyric-provider responses, real endpoint and APO/DSP processing, stable duplicate-track identity and local ARM64 runtime behavior still need separately authorized evidence. Synthetic Preview and CI matrix results do not close those gaps.

## Preserved history

Detailed source and runtime records remain in the history directory. The most relevant records are [themed popup refinements](history/MEDIA_V2_THEMED_POPUP_2026-11-19.md), [owner repairs](history/MEDIA_V2_OWNER_REPAIRS_2026-11-19.md), [ordinary startup and real use](history/MEDIA_V2_REAL_USE_2026-11-19.md), [startup trace](history/YASB_STARTUP_TRACE_2026-11-19.md) and [architecture review](history/MEDIA_V2_ARCHITECTURE_2026-11-18.md). Older records retain their original observations and should not be read as the current public contract.

## Next action

The requested remote replacement still needs a deliberate review of the target branch and an explicit force-replace confirmation before any Git write. Until then, keep Git, live YASB state and native endpoint state read-only. Before a future source or release batch, reread this handoff, inspect the dirty checkout, and rerun source-bound verification against the current source identity.
