# Media V2 writer admission, Stereo Test and backend drain

## Entry and scope

- Checkout E:\hi o\yasb, branch `codex/sync-upstream`, HEAD
  `c48acececa31006db98c21fca90b04e8b3cd233a`. The entry staged diff was
  empty. Index SHA-256
  `7339732f0873efa846fdb5d1a1290a2fdddd6681c2f2673b7b4a30e0f48c4138`.
- Rehashed all 540 architecture5 inputs before edits. All matched manifest
  SHA-256 `1e30c95ae8283d832c96d1cba70ad1039a9994d69a2422533edafd1a4c1b1533`.
  Entry Git status, staged diff and reconciliation are in the batch evidence
  directory `.git/media-v2-owner-repairs-20261119/`.
- One implementation owner made the repairs. Read-only helpers traced the
  lifecycle faults, researched the gates and reviewed the repairs. The pinned
  reference is Serpantinum `73b1cb79768641a52caf9f1d23a9a26f850f993e`.
  Verification uses the private environment, fake endpoints, owned files and
  the copied frozen package.

## Repairs and focused checks

1. Enabled APO needs an accepting writer. A draft lease binds to its writer
   and canonical target, and queue admission checks the token held on that
   target. The Apply button offers **Reconnect** when persistence is
   unavailable. Reconnection only binds the writer. An established,
   unchanged persisted base permits the next explicit Apply to claim a fresh
   lease and commit. **Review** loads the current curve and discards the old
   draft when its base changed or is unknown. A native target with no known
   base requires explicit restoration before it can be edited. A synchronous
   edit after a commit notification creates a separate draft.
2. Stereo Test binds through one QObject-owned output subscription at
   construction and replacement. Delivery checks the sender against the
   current valid owner. After PCM preparation it verifies the current output
   and captured endpoint before creating a sink.
3. Backend shared shutdown retires synchronously and publishes one
   owner-held drain task. Concurrent callers join through a shield, and the
   owner slot clears after that task drains the cancelled source work. The
   retained legacy adapter and direct close paths retain their existing guards.

| Check | Exact outcome |
| --- | --- |
| `eq-red` | Exit 1, 2 failures. Invalid Apply returned success with the writer absent. A stale +3 dB draft obtained success against the replacement after +6 dB was saved. |
| `eq-focused-final` | Exit 0, 82 passed in 18.47 s. Real button Apply/Reconnect/Review, unchanged and unknown bases, draft/discard bytes, native restore and failed-write retry, foreign lease, destination and adaptive guards. |
| `stereo-red` | Exit 1, 4 failures covering closed and deleted owners. The closed replacement had zero resets. A queued retired-owner signal prevented the deleted-wrapper control from reaching playing. Both held preparations created stale sinks. |
| `stereo-focused-final` | Exit 0, 28 passed in 2.09 s with fake sinks. One playing reset, zero wrong-endpoint sink creations, one connected receiver across repeated starts and zero after shutdown or QObject deletion. |
| `backend-red-controlled` | Exit 1, 1 passed and 1 failed. The cancelled case observed `(second.done(), shared_instance(), interrupted) == (True, None, 1)` before release. |
| `backend-focused-final` | Exit 0, 41 passed in 1.12 s. Both waiter cases acknowledge cleanup after release. Each has one fake start and close, zero replacement constructors and zero final tracked tasks. |

The earlier `backend-red` attempt also failed its control because it expected a
successful startup await after deliberately cancelling the startup task.
The corrected test expects `CancelledError` from startup and still requires
the source's cleanup acknowledgement. The first strict Pyright attempt
`types` exited 1 on possibly unbound test variable `startup`. Its creation
now precedes the cleanup block.

## Serial integrated gates

The batch directory holds the full commands, working directories, UTC start
and end timestamps, exits, stdout and stderr. The runner isolated
`YASB_CONFIG_HOME`, `LOCALAPPDATA`, `APPDATA`, `TEMP` and `TMP`. It used the
private `.git/sync-venv` tools. The frozen launcher used the actual Windows Qt
platform and its own fresh profile.

| Receipt | Command and result |
| --- | --- |
| `final-lint` | `ruff check .`, exit 0. |
| `final-format` | `ruff format --check .`, exit 0, 509 formatted files. |
| `final-types` | `pyright --pythonpath <private-python> --outputjson`, exit 0, 502 files and zero diagnostics in strict mode. |
| `full-pytest` | `python -m pytest -q -rs`, exit 0, **2,779 passed and 1 skipped** in 143.46 s. The AMD `atiadlxx.dll` skip was expected. MSVC 14.44.35207 and Windows SDK 10.0.26100.0 ran the x64 tests. |
| `schema` | Fresh export in the batch's `schema-export` directory, exit 0, 60 widgets. Export, root and packaged schema bytes matched. |
| `build` | `python build.py build` in `src`, exit 0 in 48.73 s. Duplicate resource ZIP entry and optional/platform dependency diagnostics are in the logs. |
| `package-verification-final` | Exit 0. 31 packaged modules, including all four touched production modules, and ordinary main match compiled source. Both bundled guides match. All 2,645 original ZIP entries preserve their bytes and order, and the two owned entries are unique. The copied Qt Multimedia module, DLL, plugins and five FFmpeg libraries match. System ICU loaded from System32. |

The fresh manifest has 540 inputs, including all current tracked and untracked
source/test inputs and the six root inputs. Eight files differ from
architecture5, with no added or removed manifest paths. Manifest SHA-256
`370197d86848e42dc7a17dc3101e38b7e1898c4aec0fdbd19f101adb2389a00d`.
The source archive `verified-source.zip` SHA-256 is
`27377a7447bb394793370adecc3f03d2c0e96dfed79e1bd2c53e84ab30032e6f`.
Final `package-proof.json` SHA-256 is
`150eb5629e3f0215be2861872ef532460b265bbee64a213bb8434b2cd7cbde73`.

## Owned frozen Windows preview

`native-profile-owners3` passed and exited 0 with empty stdout and stderr.
Process inventory and Sky bound PID 18340, host HWND 16779790 and the exact
copied executable and profile. The popup HWND was 46207140. Runtime module
origins resolve inside the copied archive or the bundled PyQt6 directory.
The 625×565 popup showed the playing wave, pause decay, and animated close,
reversal, and reopen. The managed APO bytes stayed stable during edit and
discard, and changed after Apply. Lyrics made one loopback request and loaded
an owned LRC. Fake Test started two 614,400-byte clips and reset twice. At
settlement there were zero popup timers and capture readers, and after shared
shutdown zero backend tasks and one fake source close. The chooser timestamp
and value hash matched before and after. Final process exit and Sky inventories
showed zero owned windows.

The interactive trace ran with normal auto-close. Sky captured the verified
host and the popup as a related 625×565 window. Raw Qt events and per-action
foreground, receiver HWND, section and focus are in `native-input-events.jsonl`
and `sky-*.json`. Only the injected actions below are attributed.

| Action | Observed result |
| --- | --- |
| Native mouse on the host opener | Qt delivered the press to the host button, then the popup opened and focused `media-play`. |
| Native mouse on the captured Equalizer tab | Qt delivered the press to the popup HWND and changed Audio to Equalizer with tab focus. |
| Ctrl+Tab and Tab | Ctrl+Tab moved Equalizer to Audio with tab focus. Tab moved focus to the Audio page within the same popup HWND. |
| Escape and Return | Escape dismissed the popup and restored `media-info` host focus. Return from that control reopened the popup with `media-play` focus. |
| Native mouse on the host outside the popup | Normal auto-close hid the popup and restored host focus. |

The first mouse attempt hit Sky's stale-input guard. Refreshing the target
capture enabled the recorded retry. One screen reported 1.0 device pixel
ratio and 96 DPI. Sky provided Windows window captures and injected input.
The five Qt grabs record widget rendering. PresentMon was absent from PATH,
and presented-frame and physical-input evidence remains open.

The first frozen attempt `owners1` exited 1 after a check receipt overwrote
the package metadata filename. Separate receipt names and re-verification
resolved it. `owners2` passed its automated assertions and drained cleanly
but exited 1 when Windows denied replacing a live telemetry file during a
read. The final disposable harness skips a temporarily locked telemetry
sample and its copied package passed. Both failed exit receipts and the
initial preview copy are preserved.

## Unchanged performance gate

All three labels are under `.git/performance/`. The same 540-input manifest is
attached to the first run, diagnostic and repeat. Benchmark SHA-256
`f379e3db8011e299a1b8cc5c1f212e161471f7505740a16e074c22b76a2790a4`,
comparator SHA-256
`870d26c606c855c34c3bef23d73294a8de50515e78e1a7604f340950318929cc`,
and budgets SHA-256
`83a16382417cf26956eaefc627a532453071816da0e301b875cc5bc455060657`
match the entry versions.

| Label | Result |
| --- | --- |
| `final001-owner-repairs-20261119` | Benchmark exit 0, 42.90 s. Comparator exit 1. Settled two-view CPU was 13.714% against 12%, the sole failed budget. |
| `final001-owner-repairs-closed-cpu-20261119` | Diagnostic exit 0, 67.81 s. Its instrumented settled sample was 6.104%. Extra samples were 9.56% with both bars visible, 4.64% with the monitor disabled, 6.20% with one bar visible and 5.68% with both hidden. The visible bars recorded title paints while owner timers and readers were settled. This run did not reproduce the first miss or isolate its cause. |
| `final001-owner-repairs-repeat1-20261119` | Original benchmark exit 0, 41.26 s. Unchanged comparator exit 0 with all budgets passing. Settled two-view CPU was **9.920% against 12%**. |

In the passing repeat, settled two-view event-loop p95 was 1.11 ms, playing
single-view p95 was 3.31 ms, and title-paint-start p95 was 17.50 ms from 24
samples. Shared decode and background prepare were 1 each. Cache usage was 8
entries and 6,458,532 bytes. Settled popup timers, capture readers and actual
jobs were 0/0/0. Reopen cycle 8-to-24 growth was 57,344 private bytes, zero
handles and zero threads. Cycle 8-to-48 growth was 110,592 private bytes,
with the same native thread identities. The architecture5 figures of 16.870%
and 9.911% are archived observations from its earlier source manifest.

The final source identity check rehashed all 540 inputs, matched all three
performance manifests and confirmed the original branch, HEAD and index hash
with an empty staged diff. `git diff --check` exited 0. See
`final-source-identity.json` and `final-diff-check.json` in the batch directory.

## Remaining evidence and next action

The local repair batch is complete. The fake startup probe established the
shared-drain bug and its repair. The historical COM `0x8001010e` error and
native resource survival were outside the reproduced failure. Production-main
startup, real providers and live endpoint/DSP remain outside this batch.
Physical input, mixed-DPI and compositor timing also remain open. Stable
duplicate-track identity still requires a provider identifier.

For a separately authorized native-evidence session, start from the linked
handoff and rehash the source. Bind a fresh owned preview, then measure popup
geometry and focus on two active displays with different scale factors and
collect presented-frame timings with an available capture tool. Treat any
production-main or live provider run as a separately scoped action.
