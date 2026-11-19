# Media V2 correctness performance and Serpantinum parity plan

Updated 16 November 2026. This is the implementation plan for the disc media popup in `yasb.media_v2.MediaWidgetV2`. **MV-001 through MV-006 and manual Apply are implemented and locally verified.** DSP-001/002/003 scoped offline native/control proofs are complete; the PRES-001 presentation slice is complete and PERF-001 measurement/optimization is complete; LYR-001 lyric contracts/shared ownership are complete; LYR-002 presentation/import is complete; AUDIO-TEST-001 is active, followed by remaining parity gates. See [the handoff](NEXT_SESSION_HANDOFF.md) and batch evidence for [MV-001](history/MEDIA_V2_MV001_2026-11-16.md), [MV-002](history/MEDIA_V2_MV002_2026-11-16.md) and [MV-004](history/MEDIA_V2_MV004_2026-11-16.md).

**Recommendation:** keep the shared media model, backend, Windows transport and upstream capture service. Repair the reproduced recovery and lifetime faults. Consolidate audio processing ownership. Rework the popup's composition for the three reference tabs while retaining usable disc, artwork and control components. A wholesale widget/backend rewrite or framework change is not justified by the present evidence.

## Settled requirements

1. **First priority:** correctness, remaining bugs, maintainable ownership and compatibility with current upstream YASB. Decide repair versus replacement per owner, using reproductions.
2. **Second priority:** measured optimization after correctness is stable.
3. **Third priority:** full functionality and appearance of the latest Serpantinum full media popup, including Windows DSP research and the Equalizer, Audio and Lyrics tabs.
4. Latest inspected upstream Serpantinum is the target; the supplied videos provide visual and motion evidence.
5. Preserve existing Media V2 configuration, callbacks, QSS identities and Windows-specific features, except the explicitly changed EQ workflow below.
6. **No legacy autosave mode.** Manual EQ bands edit a draft. Apply commits the complete curve. Closing or leaving Equalizer discards the draft. Presets and explicit Audio controls follow the reference's immediate action behavior. Do not retain an automatic manual-band write path behind another option.
7. Full functional parity is the goal. Disabled controls, visual-only EQ or static substitutes for dynamic processing cannot be counted as completed DSP parity. Clear unavailable/error states remain necessary for unsupported or failing runtime environments.
8. Keep this work local. No push, publication, driver/plugin installation, live profile replacement, live audio configuration changes or Windows settings changes are authorized by this plan. Native UI automation is resumed only for the prepared isolated preview; no live players, APO configuration or Windows settings.

The target is the **full media popup**, not Serpantinum's entire shell, lock screen, desktop lyrics widget or separate 220×140 side popout. Existing YASB bar layouts remain supported.

## Baseline and evidence

| Input | Pinned identity |
|---|---|
| YASB fork | `E:/hi o/yasb`, `codex/sync-upstream`, commit `c48acececa31006db98c21fca90b04e8b3cd233a` |
| Included YASB upstream | `37928dfeacc579948c4b4bf12e169bcbf6006ff2` |
| Local Serpantinum archive | `F:/MUSE.AI/SER SHELL/serpantinum-master`, version file 2.5.1; no Git metadata |
| Serpantinum target | [`73b1cb79768641a52caf9f1d23a9a26f850f993e`](https://github.com/ilyamiro/serpantinum/tree/73b1cb79768641a52caf9f1d23a9a26f850f993e), inspected master on 16 November 2026 |
| Reference DSP | [`serpantinum-audio` 0.4.0, `cf81973482c0f1cb7ef144b17afb3714d2c4f96d`](https://github.com/ilyamiro/serpantinum-audio/tree/cf81973482c0f1cb7ef144b17afb3714d2c4f96d) |

32 inspected local reference owners/dependencies match the pinned upstream bytes, including media components, audio services, configuration, window registry and main window lifecycle. This establishes the inspected scope, not the original archive's whole-repository commit.

Local evidence is under `.git/media-plan-evidence/`: reference source hashes, video hashes/metadata, frame manifests and the four fault-probe JSON receipts. The reference videos were sampled every two seconds: 82 frames in total, plus full-resolution stills for the three menu sections. This is reference inspection, not measured animation smoothness or a live reference run.

| Video | File in `F:/MUSE.AI/SER SHELL` | Relevant observed state |
|---|---|---|
| V1 | `kituhay_Global settings preset are now available! #archlinux #techto.mp4` | 00:02: Audio tab, balance, mono/swap, dynamic-range choices, Test and Reset |
| V2 | `kituhay_Hell yeah! v2.5.1 is out. #techtok #desktop #ui #hyprland #l.mp4` | 00:00: Equalizer tab, ten bands, presets, Dynamic and Saved controls |
| V3 | `kituhay_join rserpantinum subreddit guys! #linux #hyprland #desktop.mp4` | 00:02: Lyrics tab and searching state; 1920×1080 source |

The desktop lyric card in V2 is a separate surface; it is not evidence of the full popup's loaded-lyrics layout. Loaded lyrics, error states and interrupted transitions still need reference comparisons. Video display scaling is not recorded, so source logical dimensions are authoritative until capture conditions can be matched.

The previous sync's 2,198 passing tests and one AMD DLL skip are preserved in [the sync record](history/UPSTREAM_SYNC_2026-11-16.md). MV-001 adds 14 backend cases, MV-002 six background cases, and MV-004 nineteen setup-recovery cases. The final current suite passed **2,237 tests with one AMD DLL skip**, with clean strict typing and a successful frozen build. MV-001's initial intermittent adaptive-bar failure did not recur in the following session's full runs. The existing 14-case custom-widget suite's layout checks save a non-null image and check text/width; they do not compare reference pixels, motion, clipping, focus or presented frames. These results do not establish full media/DSP/UI parity.

## Findings to fix before visual redesign

Severity: S1 serious functional failure; S2 normal correctness/resource issue. Completion is identified per row; all other findings remain open. Original fault-probe exit 0 means the defect was reproduced, not fixed.

| ID | Severity and evidence | Failure and owning source | Required corrected behavior |
|---|---|---|---|
| MV-001 | S1, fixed locally | Original failure: a fail-once source stayed at one start call after refresh/start; ready stayed false while the error was cleared. See [batch evidence](history/MEDIA_V2_MV001_2026-11-16.md). | Explicit retry replaces the failed source in the same shared backend. Fourteen regression cases and an offscreen qasync probe with a real second Windows manager request verify recovery, one startup, retired-work rejection and cleanup. Real-player controls remain unverified. |
| MV-002 | S2, fixed locally | Background ownership now survives hide/reopen. Six real-thread regression cases and an offscreen qasync probe verify the fix; see [evidence](history/MEDIA_V2_MV002_2026-11-16.md). | Peak actual work stays at one per surface; requests coalesce, hidden/stale results do not publish, cache restoration and destruction remain safe. |
| MV-003 | S1, fixed locally | Canonical file state, serialized actual-byte writes, immutable intent/persisted snapshots and application-owned scheduling now replace popup-local writers. See [evidence](history/MEDIA_V2_MV003_2026-11-16.md). | One authoritative writer and applied state per canonical configuration target; serialize writes, invalidate cached assumptions and keep all views consistent. |
| MV-004 | S2, fixed locally | Installation/parent readiness is revalidated per apply; see [evidence](history/MEDIA_V2_MV004_2026-11-16.md). | Nineteen recovery/preservation cases and offscreen controller execution verify repaired setup, external damage, target changes and transient failures without restarting. Shared managed-payload ownership remains MV-003. |
| MV-005 | S2, fixed locally | Work-area bounded viewport, preserved scale, clamped animation/resize and automatic focused-control scrolling. See [evidence](history/MEDIA_V2_MV005_2026-11-16.md). |101geometry cases, offscreen DPI1/1.5/2 and owned native scale1/2 checks pass. Physical mixed-monitor proof remains open. |
| MV-006 | Fixed locally | Validated captured seek revisions, Return/keypad Enter, stable session-menu highlight and owned-menu lifetime. See [evidence](history/MEDIA_V2_MV006_2026-11-16.md). |36new regression cases, focused165/full2398passed; qasync and scoped native checks. Presentation policies preserved. |

Receipts: `startup-retry-probe.json`, `background-reopen-probe.json`, `apo-multiple-owner-probe.json`, `apo-setup-retry-probe.json`. The first APO experiment used an incomplete bare-Include fixture and could not reach the write scenario. It was corrected to the production-required BEGIN/END marker block and rerun; no production acceptance rule was changed.

### Keep repair or replace

| Owner | Decision and boundary |
|---|---|
| Immutable media snapshots and `MediaBackend` | Keep. Repair startup recovery and prove identity/action/event contracts. The backend remains the single media selection owner. |
| `WindowsMediaSource` and legacy adapter | Keep. Native references/subscriptions belong to the source; legacy widgets continue through the shared adapter. No second GSMTC manager. |
| Upstream WASAPI capture | Keep upstream ownership. Disc demand is a reader lease, not another capture implementation. |
| Bounded artwork decode/cache | Keep its existing GUI/worker separation and coalescing; expand stale-result and teardown coverage. |
| `MediaSurface` background work | Repair the existing lifetime owner, using the widget decoder's coalescing principle. Do not introduce a generic worker framework. |
| APO/controller state | Consolidate write and state ownership. Reuse pure configuration/validation functions; replace competing per-popup writers. |
| Popup composition | Rework the existing popup for a bounded viewport, common header and three lower pages. Keep the widget type, QSS IDs, callbacks and compatible layout options. Do not create a permanent parallel Media V3 widget. |
| Disc, text, transport, border and motion components | Reuse first. Replace an individual component only if a concrete correctness, fidelity or measured performance requirement cannot be met cleanly. |

A full backend rewrite requires evidence that its event/identity/lifetime model cannot represent the agreed behavior. A UI framework change requires a representative Windows prototype proving the current approach cannot meet the visual or measured budget. File age, line count, missing annotations and general distrust of old patches are not those proofs.

## Implementation sequence

### Phase 0 establish the contracts

Create regression cases from MV-001–005 and a state matrix covering empty/loading/error, unknown timeline, duplicate application sessions, progressive metadata, source changes, paused/playing, rejected controls, seek during track/session change, close/reopen and shutdown. Keep native provider objects out of widget state. Bind every result to source/build, profile and test data.

Record compatibility inputs from both guides and representative existing configurations: custom layouts/scales, callbacks/keybindings, QSS selectors, visual-only and APO settings, disc options, visualizer labels and upstream capture-source settings. Obsolete debounce/autosave-related keys may remain readable with a deprecation/migration message; they must not select or retain an autosave execution path.

**Exit:** precise corrected assertions and a pinned feature/capture matrix. Each unavailable native observation is listed explicitly; passing fake-source tests does not close it.

### Phase 1 repair correctness through existing owners

1. **MV-001 completed locally:** backend startup retry with source replacement and generation/lifetime tests. Recovery stays in the shared backend; widgets do not create replacement sources and no continuous polling was added.
2. **MV-002 completed locally:** background ownership across hide/reopen and teardown, verified with actual running jobs rather than only asyncio task references.
3. **MV-003 completed locally:** one app-owned scheduler and authoritative state per canonical managed file. Popup-local animations remain presentation-only. Views share saved/applied state; an edit transaction has one clear owner so another popup cannot overwrite or cancel it accidentally.
4. **MV-004 completed locally:** revalidate installation/parent setup after failure or external change, preserving recoverable atomic writes and owned fixtures. Taken before MV-003 as groundwork for canonical target ownership; the managed-payload/shared-state part remains MV-003.
5. **MV-005 completed locally:** bound popup geometry to available work area, including taskbar exclusions. Test left/right/top/hidden artwork, EQ on/off and scales 0.75/1/2; existing configurations remain usable.
6. **MV-006 completed locally:** resolve proven identity/input failures. Add direct native-source fault tests, out-of-order metadata completion, removed sessions, captured command targets, one-second seek guard, nested menu Escape/outside-click and interrupted transition cases.

**Exit:** reproduced S1/S2 failures are fixed with regression evidence; no duplicate owners, stale publication or unbounded work. Native gates outside the isolated preview scope remain open.

### Phase 2 settle the DSP and presentation architecture

**Incremental batches:**[DSP-001](history/MEDIA_V2_DSP001_2026-11-16.md) is complete locally (52native cases/full2450passed):optional tenQ1EQ/stereo DLL, actual ABI host, bounded snapshots and truthful readback. [DSP-002 streaming proof](history/MEDIA_V2_DSP002_2026-11-16.md) is complete locally (86native cases/full2484passed); [DSP-003 resident integration](history/MEDIA_V2_DSP003_2026-11-17.md) is complete offline (full2556passed/1skip):bounded broker/fenced readback/preamp, selected-profile state and same canonical writer/draft ownership; defaultGraphicEQ unchanged. Real host latency/permissions/channel/endpoint deployment and bootstrap-while-YASB-absent limits remain explicit. This does not close Phase2 or activate an endpoint. [PRES-001](history/MEDIA_V2_PRES001_2026-11-17.md) proves the common presentation slice locally (full2571passed/1skip plus scopednativeAudio/draft/focus). Next measure baseline/optimize, deliver full Equalizer/Audio/Lyrics and reference parity in the phase order below.

Run a bounded DSP feasibility spike before committing to a transport or a broad rewrite. The current loopback service captures audio for analysis; processing its buffers does not change arbitrary applications' rendered output. [Microsoft loopback documentation](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording) and [APO architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/audio-processing-object-architecture) establish the distinction.

Evaluate the smallest credible route first: existing Equalizer APO endpoint integration plus a native processor hosted by a supported plugin interface. If it cannot meet the requirements, compare a custom APO or deliberate virtual-endpoint route as a separate deployment design. Do not assume a VST/native host works on every device, OS or CPU architecture. Do not install or register anything during an offline spike.

The deliverable must settle supported Windows/architecture/device/sample-rate scope, processing route, control/readback protocol, state persistence, native deployment/rollback, coexistence with other effects and failure behavior. DSP work must stay out of Python's GUI thread and out of real-time filesystem/locking paths. Use atomic validated parameter snapshots and keep command acceptance, persistence, backend activation and measured processing distinct.

Static EQ/stereo configuration is a plausible extension; a verified streaming processor is still needed for compression, limiting and adaptive EQ. The current `GraphicEQ` plus automatic preamp is not the reference's ten Q=1 peaking filters. Reference DSP runs at 48 kHz stereo float32; prove other supported rates explicitly. [Pinned DSP chain](https://github.com/ilyamiro/serpantinum-audio/blob/cf81973482c0f1cb7ef144b17afb3714d2c4f96d/src/dsp/chain.h).

Keep the media snapshot backend separate from global output processing. The effects target a supported output route, not whichever player happens to be selected in the menu. Capture-source choice and output processing are different responsibilities.

The reference shell is AGPL-3.0-or-later and its audio engine declares AGPL-3.0-only; YASB is MIT. Plan the Python/Qt appearance and behavior adaptation independently. Any direct code/asset reuse needs an explicit compatible provenance/licensing decision rather than silently changing the project's license.

For presentation, prove one slice: common disc/header/seek controls, bounded lower viewport and one tab transition. Compare a local refactor against replacing that composition owner. Keep the smaller option that passes the same behavior, compatibility and fidelity checks. No framework port is selected by this plan.

**Exit:** documented owner map, working offline DSP/control proof and one presentation slice. If a full DSP route is not feasible, return that architecture decision; do not quietly reduce the accepted goal to visual-only controls.

### Phase 3 measure and optimize

[PERF-001](history/MEDIA_V2_PERF001_2026-11-17.md) is locally complete: duplicate2viewimagework2+2→1+1; boundedmetadata-awarecache, predeclaredbudgets,48cyclewarmresourceplateau, full2581passed/1skip. NoCPU/FPSgainclaim; presentedframesunavailable. Reapplybudgetsafterfeatures.

Profile a correctness-stable baseline in empty, closed, paused-open, playing-open, track-churn and multiple-view cases. Include repeated hide/reopen, source/device changes, artwork errors and large artwork. Record hardware, display scale, capture conditions and source identity.

Measure CPU, memory, threads/handles, active timers, actual decoder jobs, queue/cache sizes, capture reader counts, event-loop delay, event-to-paint latency and presented frames where available. Use p50/p95 and resource plateaus across repeated cycles. Set and record numeric budgets from that baseline and the chosen display refresh rate before claiming an optimization.

Optimize only attributable costs. Candidates are duplicate background work, repeated blur/palette decode, per-view cache duplication, unnecessary repaints and layered graphics effects. Share a cache or scheduler only when measured duplication justifies it. Hidden popup work must stop or settle; other visible widgets' legitimate capture demand must remain intact. Paused playback stops disc rotation/reactive activity after decay, but reference-intended subtle background/border motion is not removed merely to improve a number.

**Exit:** bounded jobs/caches/resources, no accumulating reader leases, stable settled resources after repeated cycles, and before/after evidence for each optimization. Timer callbacks or a video file's nominal FPS do not establish presented-frame performance. Reapply these budgets after the new feature work.

### Phase 4 deliver full functional parity

Implement the three sections in the existing popup and route their operations through the agreed shared owners.

**Equalizer:** ten manual bands, eight presets, draft/Apply/Saved state, discard on close/tab change, atomic full-curve commit, immediate explicit preset actions, dynamic-EQ mutual exclusion and error recovery. Manual slider release must not publish audio settings. The reference `set_band` only updates a draft; `apply` sends it to DSP. [Pinned dispatch](https://github.com/ilyamiro/serpantinum/blob/73b1cb79768641a52caf9f1d23a9a26f850f993e/src/quickshell/media/equalizer.sh#L208-L288).

**Audio:** real balance, mono, channel swap, Off/Balanced/Night dynamics, Reset, dynamic EQ and a cancellable 3.2-second stereo Test. Balance is inactive in mono. Test sound occurs only from an explicit user action, never startup or an unattended validation run. Do not label an unconfirmed setting Saved/active because a command was queued.

**Lyrics:** [LYR-001](history/MEDIA_V2_LYR001_2026-11-17.md) contracts/shared request ownership completed locally (full2664passed/1skip); LYR-002 presentation/import and AUDIO-TEST-001 explicit stereo Test are complete locally; FID-001 and FID-002 are complete locally; FINAL-001 is next in the successor chat. Deliver local-file import, online lookup providers, line/word synchronization, loading/empty/error states, follow-current-line, wheel/drag browsing, four-second return to follow and click-to-seek bound to the captured track/session. Fetch/subscribe only for an interested visible view; cancel stale lookups and keep caches bounded. Use fixture lyrics and mocked network responses before live lookup. The desktop lyric card is a separate surface and is not added here.

**Exit:** every accepted feature has an operating Windows implementation on the documented supported route, with fake/offline tests plus authorized real-device/native evidence. Unsupported runtime conditions show accurate states; they do not count as completed feature parity. Preserve existing non-conflicting options, including optional visual-only mode, without claiming it processes audio.

### Phase 5 match appearance and motion

[FID-001](history/MEDIA_V2_FID001_2026-11-17.md) and [FID-002](history/MEDIA_V2_FID002_2026-11-18.md) are locally complete. Exact reference/compositor/presented-frame observations remain qualified by their finding ledgers. Continue the [FINAL-001 checklist](MEDIA_V2_FINAL_CHECKLIST.md) in the next chat.

Match the pinned reference before introducing aesthetic changes. Compare equivalent data, logical dimensions, scale, theme, fonts and interaction states. Keep a finding ledger with stable IDs, severity, capture/timecode and intentional/deferred/accidental/unresolved status.

| Target | Reference contract and comparison |
|---|---|
| Canonical full popup | 625×565 at scale 1; 18 outer margins; 224×224 cover; 16 cover/control gap; separator 2 with 16 vertical margins; lower section prefers 235 and negotiates within the canonical shell. Existing alternative layouts get compatibility/geometry tests, not a fabricated reference screenshot. |
| Header | Scrolling title, elided artist, informational output pill; player dropdown for 2+ players and informational Via pill otherwise. Do not turn the output pill into an unrequested device switcher. |
| Transport | Wavy seekbar, elapsed/total time, Previous/Play-Pause/Next. Preserve unrelated compatible YASB capabilities without adding controls to the reference layout arbitrarily. |
| Disc and reactive spectrum | 60 radial bars, 25 seconds per rotation, pause/decay, bass/kick scale/bounce/tilt/glow. Check the current 24-band-to-60 resampling against the reference's 60-band stream with deterministic audio; do not replace upstream capture to alter presentation. |
| Artwork/background | 650 ms cover crossfade, 800 ms blurred-background crossfade, clipping/crop/fallbacks and theme overlays. No stale cover on session/track change. |
| Border | 1,200 ms charge, five-second colour rotation; compare the reference's glass/material variant separately. |
| Intro | Stagger delays 70/150/230/310/370/430/550 ms with reference easing and 660–860 ms durations. Verify interruption/reversal, not only a successful first open. |
| Tabs | Equalizer/Audio/Lyrics, Tab/Shift+Tab behavior, 400 ms translation and 250 ms fade; header morphs to section actions. |
| EQ | UI labels 31 Hz–16 kHz, ±12 dB in 1 dB steps, two rows of four presets. Processing uses the pinned backend's 32 Hz first peaking filter rather than assuming the UI label defines the algorithm. Dynamic EQ dims manual controls to 30% and blocks editing. |
| Lyrics | Match loading, loaded/synced, browsing, local-file and failure states; the available V3 still establishes searching only. |

Use a representative canonical slice early, then expand. Source timings are specified targets, not measurements from the two-second video samples. Do not declare pixel, motion or focus parity from source inspection or the prior saved-image tests alone.

**Exit:** paired captures and interaction evidence cover important states; no accidental serious mismatch remains. Platform/material differences are explicit. A missing native/reference observation remains unresolved rather than being hidden by a passing unit test.

### Phase 6 retain upstream compatibility and close the batch

Keep contract checks for legacy media consumers, current capture API/source/idle behavior, popup shell behavior, widget registration/schema and packaged custom modules/guides. Preserve the one-media-owner rule and stable configuration/callback/QSS identities. Do not merge or rewrite all upstream files for a popup change.

For a stable batch, run the repository's Ruff formatter/linter, strict Pyright, full pytest suite, schema export and frozen build using a private environment. Keep SDK skips explicit and do not add skips to conceal new failures. Required native/resource/visual checks are additional gates. Record the exact source, executable, profile, commands, results, captures, benchmarks and open issues in the handoff.

On future YASB or Serpantinum updates, pin the new revision, compare the owned contracts and reference matrix, then run affected checks. Updating the reference ledger is not automatic permission to change functionality, install anything or push.

## DSP acceptance details

The feasibility and implementation tests must cover the pinned functional algorithms, not merely their control labels:

- Ten Q=1 peaking filters and preset coefficients; impulse/frequency-response fixtures, gain limits and parameter smoothing.
- Mono averaging, swap ordering and linear balance using channel-isolated fixtures; finite outputs and correct reset/bypass behavior.
- Balanced compressor: −26 dB, ratio 2.8, knee 20 dB, attack 14 ms, release 200 ms. Night: −36 dB, ratio 6, knee 28, attack 6 ms, release 320 ms.
- Limiter: five-millisecond lookahead, 50 ms release; reference thresholds −1 dBFS with dynamics and −0.1 dBFS with dynamic EQ only.
- Dynamic EQ: adaptive analysis/filter chain, convergence/gating, transition from manual settings and measured response to controlled material. Static attenuation is not a substitute.
- Atomic invalid-command rejection, persistence failure, disconnect/reconnect, stale acknowledgements, device changes, multiple views, backend restart and coexistence with existing effects.
- Authorized endpoint tests only after the offline route is proven, with backup/rollback for any live audio configuration. Shared-mode/exclusive/RAW limitations and architecture/device support must be stated accurately.

Primary references: [control parser](https://github.com/ilyamiro/serpantinum-audio/blob/cf81973482c0f1cb7ef144b17afb3714d2c4f96d/src/control.h), [DSP sources](https://github.com/ilyamiro/serpantinum-audio/tree/cf81973482c0f1cb7ef144b17afb3714d2c4f96d/src/dsp), [Equalizer APO configuration](https://sourceforge.net/p/equalizerapo/wiki/Configuration%20reference/), [Microsoft APO implementation](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/implementing-audio-processing-objects).

## Native verification and immediate next action

Native UI checks are resumed for the prepared isolated preview only. Offline/offscreen evidence cannot close live-provider or presented-frame criteria. Within the authorized scope, launch an owned isolated preview, inventory through Node REPL `@oai/sky`, bind the actual executable/profile/window, then verify open/close, rapid reversal, nested player menu, keyboard traversal, Escape/outside click, focus return, monitor/DPI changes and supported work areas. Use fresh returned identities and observations for every input route.

**Current implementation status:** MV-001–006 and manual Apply are complete locally; source changes are uncommitted and nothing was pushed. Continue offline DSP proof, measured optimization, full functional/UI parity and compatibility gates. The user requests continuing all remaining milestones in this chat. Each batch has one main owner, its own corrected assertions and relevant runtime evidence. Proceed in the priority order above. Do not start a full rewrite, copy the Linux shell or claim full parity from the already completed upstream sync.
