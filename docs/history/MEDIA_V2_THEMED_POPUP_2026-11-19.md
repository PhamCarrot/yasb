# Media V2 themed popup refinements

## Source and reference

Entry checkout E:\hi o\yasb, branch `codex/sync-upstream`, HEAD
`c48acececa31006db98c21fca90b04e8b3cd233a`. The staged diff was empty.
All 540 inputs matched the preceding owner-repair manifest
`370197d86848e42dc7a17dc3101e38b7e1898c4aec0fdbd19f101adb2389a00d`.
Current receipts and captures are in `.git/media-v2-themed-popup-20261119/`.
One implementation owner made all source changes.

Reference Serpantinum 2.5.1, pinned at
`73b1cb79768641a52caf9f1d23a9a26f850f993e`. A read-only check matched all
32 manifest-selected local source files and the source archive's pin. The
implementation uses independently written Qt rendering. No reference assets
are packaged.

The [reference provenance](../../.git/media-v2-themed-popup-20261119/reference/provenance.json)
identifies the exact source movie, timestamps and crop. V3 gives the same
full popup and art across Equalizer at 0.63 s, an Audio transition at 1.08 s,
settled Audio at 1.45 s, Lyrics searching at 2.13 s and loaded Lyrics at 2.53 s.
The [pinned loaded-Lyrics still](../../.git/media-v2-themed-popup-20261119/reference/loaded-pinned-still.png)
comes from `docs/assets/previews/preview_2.png`, SHA-256
`51d67db1c36a5c782b780cecf0eb268d367d87d983f640605b7180ab2ef830cf`. Its
two-tab header predates the three-tab layout in the source and V3 frames.
Reference seek hover/drag, exact pause-decay timing and lightning bounds
come from the pinned behavior contracts.

The theme fixture contains 49 relevant processed rules plus validated popup
options. It uses the real stylesheet precedence, profile font choices and
synthetic cover, metadata and lyrics. It excludes unrelated widgets, commands,
paths and content. The owned graphic writer uses disposable files. The
enabled Audio comparison uses an injected fixture with local state.

## Changes and targeted evidence

- A band edit bases its curve on the current complete controller draft or
  preset. A mouse-release snap can act only on the edit's original lease.
  The panel retires a held gesture if a synchronous observer supersedes its
  draft. The explicit Apply path owns persistence.
- Preset selection notifies the caption owner independently of write status.
  The header lays the measured caption out synchronously. A retarget during
  page entry preserves the current extent and remaining duration. Unrelated
  notifications leave an in-flight header transition alone.
- **MVV-001/007/008.** Disabling implicit Qt palette fill exposes the album
  on Equalizer, Audio and Lyrics. Lower control defaults live below explicit
  bar QSS, scoped to each configured scale and radius. Lightning uses an
  input-transparent bounded paint region on the rounded album surface.
  The four corner pixels expose the contrasting backplate during both
  border charge and settlement.
- **MVV-005/008.** The seek wave has a smooth short-fraction envelope,
  two-layer motion and a rounded thumb with a soft shadow and hover/drag
  easing. The circular paint clip preserves the user's chosen color even
  with a 999 px QSS radius. The actual theme config hides the thumb, so
  comparison captures include a separately labelled owned thumb-on variant.
- **MVV-007.** Audio uses the reference balance scale and center-to-handle
  fill, staggered cards, separate toggle title and knob, and a 150 ms
  balance dim that retains the balance value in Mono. Dynamic explains the
  native-processing requirement through its accessible description. Fake
  enabled Audio and Stereo Test exercise the existing control owners. Test,
  active Stop and Reset use portable headphones, square and circular-arrow
  glyphs on the same accessible buttons.
- **MVV-003/007.** The tab strip consumes wheel ticks while click and
  keyboard navigation keep their normal behavior. Four synthetic playback
  updates alone kept Equalizer. A metadata change while hidden did the same.
  Explicit Lyrics selection acquired demand and retained the last page
  across close/reopen while draining demand during the hidden period.
- **MVV-007.** Lyrics uses a centered search/status composition and the
  local-file action. The timed list keeps virtual rows and stable hit
  rectangles. Current, nearby and distant lines have distinct scale and
  opacity. Word intervals retain UTF-16 ranges. The 650 ms line/follow
  behaviors preserve browsing and return, and a loaded outgoing page fades
  after retiring input and network demand.

The first `presets-red` run exited 1 with three failures. Both drag variants
copied +3.22 dB into an untouched Bass band whose intended value was +7 dB.
The caption slot remained 76 px while Classic needed 133 px with the test
font and held writer. The real-theme capture exposed a second cause.
The first Classic frame had the correct 49 px width at x558 in a 583 px
header, and later settled at x534. The held-layout test failed before
activation was added. The original 250-test focused refinement suite
passed after the themed geometry fix.

The additional `successor-release-red` run reproduced a synchronous
Apply-and-replace while the mouse was held. The later explicit Apply
persisted (3,8,8,8,8,8,8,8,8,8). `successor-release-green` exited 0 with
one pass and verified all ten +8 dB values in the managed bytes.

The Audio and Stereo Test glyph selection passed 43 tests after the final
visual follow-up. It observes distinct rendered glyphs, the unchanged Test
button extent, its two accessible names and fake audio sink cleanup.

## Full-popup comparison

The baseline and final images use the same scoped theme, font registration
and synthetic track. The pinned examples use a different track, album,
palette and font. Review geometry, visible states and transitions across the
full popup. The table links representative frames from each run.

| Area | Serpantinum V3 | YASB before | Final owned frozen preview |
| --- | --- | --- | --- |
| Equalizer | [settled](../../.git/media-v2-themed-popup-20261119/reference/v3-eq.png) | [settled](../../.git/media-v2-themed-popup-20261119/baseline-fonts/eq.png) | [settled](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-equalizer-settled.png), [first-frame Classic](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-classic-first-frame.png), [lightning overflow](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-lightning-overflow.png) |
| Audio | [transition](../../.git/media-v2-themed-popup-20261119/reference/v3-audio-morph.png), [settled](../../.git/media-v2-themed-popup-20261119/reference/v3-audio.png) | [Graphic EQ](../../.git/media-v2-themed-popup-20261119/baseline-fonts/audio-graphic.png) | [transition](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-audio-transition.png), [centered](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-audio-centered-fake.png), [Stop active](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-audio-test-active.png), [Graphic EQ](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-audio-graphic.png) |
| Lyrics | [searching](../../.git/media-v2-themed-popup-20261119/reference/v3-lyrics-search.png), [loaded](../../.git/media-v2-themed-popup-20261119/reference/v3-lyrics-loaded.png) | [searching](../../.git/media-v2-themed-popup-20261119/baseline-fonts/lyrics-search.png), [loaded](../../.git/media-v2-themed-popup-20261119/baseline-fonts/lyrics-loaded.png) | [searching](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-lyrics-search.png), [active word](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-lyrics-active-word.png), [line transition](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-lyrics-line-transition.png), [return](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-lyrics-return.png) |
| Seek and border | [source and movie provenance](../../.git/media-v2-themed-popup-20261119/reference/provenance.json) | [halfway while playing](../../.git/media-v2-themed-popup-20261119/baseline-fonts/wave-play-half.png) | [configured](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-wave-half-configured.png), [thumb variant](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-wave-half-thumb.png), [hover](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-wave-half-hover.png), [drag](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-wave-half-drag.png), [pause decay](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-wave-pause-decay.png), [border charge](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/themed-border-charge.png) |

The final Qt captures show the whole 625 × 565 popup. The lower surface now
shows the artwork wash in all three sections. The Audio controls keep the
Windows processing status and theme's selected-button colors. In the active
Stop capture, the selected foreground has lower contrast than the normal
Test foreground. The Lyrics capture shows a distinct line and within-line
highlight. Exact color, device rendering and compositor timing depend on the
host theme and display. The thumb-enabled preview differs from the configured
preview by the isolated thumb setting. Both are included above.

## Final serial gates

The [540-input manifest](../../.git/media-v2-themed-popup-20261119/verified-source-sha256.json)
has SHA-256 `0f5fc30df5a7144d65d6ca6a22b761e2abdafc3a0176347f53bc8e5b7b140c2e`.
Eighteen input hashes differ from the owner-repair manifest. The
[source archive](../../.git/media-v2-themed-popup-20261119/verified-source.zip)
has SHA-256 `467e7cc86e789a3ac41782561a5c5c914085eb05a7476b6750c9dc2c42f9e39c`.

- Ruff check and format check exited 0. The format check counted 509 files.
  Strict Pyright exited 0 with 502 source files and zero diagnostics.
  [Lint](../../.git/media-v2-themed-popup-20261119/glyph-final-lint.log),
  [format](../../.git/media-v2-themed-popup-20261119/glyph-final-format.log),
  [types](../../.git/media-v2-themed-popup-20261119/glyph-final-types.log).
- Full pytest exited 0 with 2,789 passed and one expected skip because
  `atiadlxx.dll` could not load. Pytest recorded 130.83 s and 1,871 warnings.
  The x64 SDK checks used MSVC 14.44.35207 and SDK 10.0.26100.0.
  [Pytest output](../../.git/media-v2-themed-popup-20261119/glyph-final-pytest.log).
- The fresh 60-widget schema matched both root and ordinary package bytes,
  SHA-256 `a5cf6463f5ab65bbaaa063ca3f71f8edf83b28ed2aaefe15cb0fd99162bcaf38`.
  `python build.py build` from `src` exited 0. The package gate verified 31
  Media V2 modules, the ordinary main, both guides and the Qt Multimedia
  plugins and dependencies. The separate preview archive preserved 2,645
  ordinary entries and added two private entry points. The archived build
  output records duplicate ZIP resource, optional dependency and API-set
  warnings. [Schema](../../.git/media-v2-themed-popup-20261119/glyph-final-schema.log),
  [build](../../.git/media-v2-themed-popup-20261119/glyph-final-build.json),
  [package proof](../../.git/media-v2-themed-popup-20261119/package-proof.json).
- Final themed Qt comparison exited 0. The [caption trace](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/caption-trace.json)
  records `Classic` at x534 with width 49 px, `Pop` at x556 with width 27 px
  and `Bass` at x550 with width 33 px, all within the 583 px header before
  first paint. [Source comparison receipt](../../.git/media-v2-themed-popup-20261119/glyph-final-comparison.json).

## Owned Windows preview and performance

The first frozen preview exited 1 after an oracle waited for the completed
album-art task reference to disappear. The task had completed and remained
retained. The harness now verifies that the reference is absent or completed,
with zero active work. `themed2` and the final `themed3` passed that check.
[First exit](../../.git/media-v2-themed-popup-20261119/native-profile-themed1-exit.json),
[final resource state](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/settled-resources.json).

The final Windows preview reported 24 themed captures, two wheel events
delivered through Qt with Equalizer retained, and zero source actions. It
verified real bytes through a disposable APO writer, one loopback Lyrics
request with one owned LRC import, and two fake Stereo Test starts with
614,400 PCM bytes each and two resets. Shutdown drained the workers, Lyrics
reply, audio poll, popup timers and capture readers. The chooser stamp
matched, the process exited 0 and the final Sky inventory was empty.
[Automated evidence](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/automated.json),
[close](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/closed.json),
[exit](../../.git/media-v2-themed-popup-20261119/native-profile-themed3-exit.json),
[inventory](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/sky-final-inventory.json).

Sky observed a real Return key on the bound host reopen the final popup on
Audio and focus Play. `themed2` observed native mouse tab navigation. On the
final build the popup lost focus before the secondary mouse action, so that
action was withheld. The wheel regression evidence is from the Windows Qt
events. The preview used one 96-DPI display at 100%. WGC and widget grabs
recorded visible states. Presented-frame timing and mixed-DPI behavior
remain open. [Final keyboard](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/sky-keyboard-open.json),
[mouse boundary](../../.git/media-v2-themed-popup-20261119/native-profile-themed3/sky-popup-lost-focus.json).

The unchanged benchmark and comparator both exited 0 on the first run.
All 45 comparator checks passed. Settled two-view CPU was **6.865% against
12%** of one core, single-view playing p95 event-loop delay was **5.468 ms
against 25 ms**, title paint-start p95 was **14.588 ms against 50 ms**, and
final capture readers were zero. The recorded benchmark manifest matches
the 540-input final manifest above. [Raw result](../../.git/performance/final001-themed-popup-20261119/result.json),
[comparison](../../.git/performance/final001-themed-popup-20261119/comparison.json).

Final integrity rehashed all 540 workspace and archived inputs against the
same manifest. Live `config.yaml` and `styles.css` matched the read-only
fixture source hashes. `git diff --check` exited 0, the staged diff was
empty and HEAD, branch and index matched entry. [Integrity receipt](../../.git/media-v2-themed-popup-20261119/final-integrity.json),
[Git receipt](../../.git/media-v2-themed-popup-20261119/final-git-integrity.json).

The next separately authorized evidence step is a fresh owned preview on
two displays with different scales and presented-frame capture. Physical
input, production-main startup, real providers, endpoints, APO and DSP,
and stable duplicate-track identity remain outside this local gate.
