# Media V2 planning handoff

Updated 16 November 2026. The planning audit is complete; implementation of this plan has not started. Read [the Media V2 plan](MEDIA_V2_PLAN.md) first. The prior sync record is preserved verbatim in [history](history/UPSTREAM_SYNC_2026-11-16.md); its next-action text is historical, not the current queue.

## Current source and constraints

Use `E:/hi o/yasb`, branch `codex/sync-upstream`, HEAD `c48acececa31006db98c21fca90b04e8b3cd233a`, including upstream `37928dfeacc579948c4b4bf12e169bcbf6006ff2`. Application source/tests/schema/guide hashes still match all 494 verified inputs from the sync. Only planning documentation and local evidence were added in this phase. No stage, commit, branch, push or PR was performed for planning.

One main agent owns each implementation batch. Helpers may do bounded read-only research/review only. Keep live YASB profiles, Windows settings, audio routes and application state intact. No installs, publication or live audio configuration edits are authorized. **Computer Use remains paused after physical Escape; do not resume native input without the user's instruction.**

## User decisions

Priority 1 is bugs, validity/architecture and YASB compatibility; priority 2 is measured optimization; priority 3 is Serpantinum media-menu functionality/appearance. Latest inspected upstream is the target, with the three supplied videos informing visual/motion details. Preserve existing configuration, callbacks, QSS identities and Windows-specific features.

The user chose **full functional parity**, including Windows DSP research, rather than a permanently visual-only approximation. The user then explicitly corrected the EQ choice: **do not use a legacy autosave mode**. Manual bands edit a draft only; Apply commits the curve; close/tab change discards it. Reference presets and explicit Audio actions remain immediate. Old input keys may be migrated/deprecated, but no legacy autosave execution path is to be retained.

## Planning results and evidence

- Recommendation: retain shared media backend/model/Windows source and upstream capture; repair concrete lifecycle/recovery faults, consolidate audio write ownership, then rework the existing popup composition for Equalizer/Audio/Lyrics. No blanket rewrite or rendering-framework change is justified now.
- Pinned Serpantinum: `73b1cb79768641a52caf9f1d23a9a26f850f993e`, local archive version 2.5.1 at `F:/MUSE.AI/SER SHELL/serpantinum-master`. 32 selected local owners/dependencies match pinned upstream bytes. Pinned DSP: `cf81973482c0f1cb7ef144b17afb3714d2c4f96d`, v0.4.0.
- Videos: three originals under `F:/MUSE.AI/SER SHELL`; 82 frames sampled every two seconds, plus full-resolution Audio/EQ/Lyrics-search stills. Manifests and images are local in `.git/media-plan-evidence/`. No native application automation was performed during planning.
- Current-session fault probes reproduced four open defects: MV-001 retry remains unready with one start call; MV-002 four hide/reopens yield four concurrent held background jobs; MV-003 A/B/A managers report applied while the managed file still contains B's curve; MV-004 setup retry remains cached-failed after the owned marker block is repaired. Receipt JSONs are under `.git/media-plan-evidence/`. These are defect-characterization probes, not successful fix verification.
- The first APO probe used an incomplete bare-Include fixture and failed before reaching the intended scenario. It was corrected to the production-required marker block and rerun against disposable data. No acceptance rule or production code was weakened.
- Geometry overflow and several identity/focus scenarios are source-supported risks requiring targeted reproduction. Previous 2198-test sync results are historical regression evidence; they do not establish complete media correctness, full DSP or visual/native parity.

## Exact next action

This request was for a plan, so stop before implementation. When the user asks to implement, take sole ownership and begin with **MV-001 only**: reproduce transient startup failure as a regression test, repair recovery through the shared backend/source owner, and verify late-event rejection and cleanup. Then update this handoff before a successor starts. MV-002 background lifetime follows; shared audio writer/state and the single Apply workflow follow that. The full dependency/acceptance sequence is in the plan.

Native input/focus, real-player/provider, DSP endpoint and presented-frame gates remain open. Work that can be verified offline may proceed when implementation is requested, but do not mark those native gates complete while automation is paused. Nothing should be pushed without explicit instruction.
