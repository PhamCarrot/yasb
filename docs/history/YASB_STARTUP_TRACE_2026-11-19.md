# YASB ordinary startup trace

19 November 2026, Asia/Bangkok. This follow-up investigates the slow ordinary
startup from the [real-use comparison](MEDIA_V2_REAL_USE_2026-11-19.md).
The baseline is the user's installed fork 2.0.8 at
`C:\Program Files\YASB\yasb.exe`, from the [published fork commit](https://github.com/PhamCarrot/yasb/commit/b67033d391cc6ca94dcfa2faf736c6a2cf027e53).
The candidate is the ordinary 2.0.9 executable at `E:\hi o\yasb\src\dist\yasb.exe`.
Each headline launch used its own executable directory as its working directory.
The earlier comparison launched the candidate from the checkout root.

Both builds used new owned profiles containing the same previously reviewed
YAML and byte-identical theme QSS. Those copies suppress the separator's
startup command, live APO, work-area reservation, updater and unrelated
global hotkeys. Config, application data and temporary directories were
redirected per process. No cache flush, reboot or security change occurred.
The tests used one 1920 × 1080 display at 96 DPI. All measured exits used the
PID-verified CLI pipe and checked for bar, mutex and pipe cleanup.

## Reproduction and measurement

The historical console file was created at `08:12:22.9557195Z`, immediately
before launching the executable. The app log file was created at
`08:12:30.2306864Z`, giving an independent **7.27497 s** boundary. The old
wall-clock launch timestamp preceded preflight, but the file interval rules
out preflight accounting as the explanation. The old process returned from
spawn in 63 ms and used 1.672 s of CPU by the 12.566 s message-ready mark.
A 22-second existing-event query of Application, Code Integrity, Defender
and AppLocker yielded no matching events. This narrow query cannot exclude
an OS wait or attribute it to a particular component.
[Historical evidence](../../.git/yasb-prelog-startup-20261119/historical-evidence.json),
[historical candidate receipt](../../.git/media-v2-real-use-20261119/launches-final/candidate-1.json).

The new launcher brackets the monotonic spawn reference with UTC reads and
captures the Win32 process creation timestamp. It polls for an owned visible,
uncloaked `YasbBar` and then a successful `WM_NULL` round trip. Process CPU
and I/O counters are sampled approximately every 35 ms during startup.
Unchanged counters can bound an interval without accounted work. They cannot
identify the wait owner, prove that a read is blocked or measure compositor
presentation. Cross-process phase timestamps use Python's shared Windows
performance counter. [Process I/O](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getprocessiocounters),
[Python clock](https://docs.python.org/3.14/library/time.html#time.perf_counter),
[launcher](../../.git/yasb-prelog-startup-20261119/trace_launch.py).

The first new ordinary candidate took **1.898 s to log, 4.885 s to show and
5.523 s to answer**. The corresponding installed first observation was
0.599 s, 1.929 s and 1.975 s. Candidate repeat medians were 0.602 s, 1.614 s
and 1.656 s. At 51.2–1,104.0 ms in the slow candidate, consecutive samples
showed unchanged process CPU and I/O totals. CPU at the first log-file
observation was 609 ms, and CPU at readiness was 1.672 s. The later CLI-to-audio
service interval was 1.839 s and accounts for a separate part of this run.
[Ordinary before summary](../../.git/yasb-prelog-startup-20261119/ordinary-before/summary.json),
[slow run](../../.git/yasb-prelog-startup-20261119/ordinary-before/candidate-1/receipt.json),
[slow run accounting](../../.git/yasb-prelog-startup-20261119/ordinary-before/candidate-1/cpu-io.json).

## Diagnostic controls

The package copies retained the ordinary executable bytes and verified the
untouched archive entries against the shipped ZIP. Diagnostic markers were
buffered in memory and written on exit. The archive replacement for the
early `__startup__` script never emitted a marker. The first observed boundary
was entry to the frozen per-executable initializer, which includes preceding
native loading, interpreter setup and earlier freezer initialization in one
upper bound. The next markers bracketed bytecode resolution, application
entry, eager imports, logger, QApplication, profile/QSS and bar assembly.
Warm plain and marked launches from the same copy reached readiness around
1.55–1.56 s. The first plain launch from that location took 3.71 s.
[Marker proof](../../.git/yasb-prelog-startup-20261119/instrumentation-proof.json),
[plain and marked control](../../.git/yasb-prelog-startup-20261119/bootstrap-control/summary.json).

Two first launches from new copied paths logged at 2.436 s and 2.018 s.
Repeating the same paths logged at 0.567 s and 0.548 s. On the first runs,
the earliest observed freezer marker was 187–207 ms from spawn. The qasync
import took 639–918 ms, including only 47–94 ms of process CPU. The bar
manager import took 828–850 ms, including 328–375 ms of CPU. Logger
initialization took about 1 ms. Additional time occurred in bar assembly.
These phases contain multiple dependencies and waits. Copying creates a new
path and reads the original bytes, so it gives no controlled cold-cache state.
[Fresh-path trials](../../.git/yasb-prelog-startup-20261119/fresh-path-traces/summary.json),
[phase and accounting detail](../../.git/yasb-prelog-startup-20261119/phase-and-accounting-summary.json).

The same unmodified candidate was also launched from the checkout root and
from `src\dist` in alternating order. The slower first root launch had a
392 ms accounting plateau, and the other root launch was faster than both
dist runs. The sample does not isolate a stable working-directory effect.
[Working-directory control](../../.git/yasb-prelog-startup-20261119/cwd-control/summary.json).

The next trace resolved the qasync stage into Qt's extended-module imports.
On the first marked launch from that new path, `QtCore`, `QtGui` and
`QtWidgets` took **239.1 ms, 223.5 ms and 199.9 ms**, respectively. The three
intervals accumulated only 15.6 ms of sampled process CPU, with Windows CPU
accounting quantized in these observations. The markers bracket complete
imports, including native binding loads and initializers. They do not isolate
the exact DLL, file filter, scheduler state or driver.
[Qt import sub-markers](../../.git/yasb-prelog-startup-20261119/single-archive-ab/eager-1/phases.json),
[shared archive proof](../../.git/yasb-prelog-startup-20261119/single-archive-ab/proof.json).

The wizard experiment initially used two rewrites of the same copy. Across
those runs its own eager import took 9.45–10.50 ms. Much of the apparent
whole-launch difference had accrued in the bar manager before reaching the
wizard import. A second A/B shared a single archive, executable, profile,
working directory and QSS, changing only the diagnostic environment switch
for the wizard import. The control did not reproduce a multi-second wizard
cost. In the shared-archive experiment, the faster eager repeat reached
readiness in 1.518 s, inside the deferred repeat range of 1.478–1.629 s.
[First wizard A/B](../../.git/yasb-prelog-startup-20261119/welcome-ab/summary.json),
[same-archive wizard A/B](../../.git/yasb-prelog-startup-20261119/single-archive-ab/summary.json).

The installed build provided a separate location control. Its executable
and ZIP were copied byte-for-byte. In order, the copy's first pre-log and
ready times were **2.570 s and 4.339 s**. The installed path logged and
answered in 0.646 s and 1.577 s, then 0.547 s and 1.428 s. Returning to the
copy gave 0.548 s and 1.529 s. The installed code can therefore show the
same first-copy pattern, although path, ordering and cache conditioning are
entangled in this experiment.
[Installed location control](../../.git/yasb-prelog-startup-20261119/installed-location-control/summary.json).

No product code path was shown to cause the historical 7.275 s. The newer
evidence localizes excess wall time to multiple startup phases, including
before measurable process execution and during required imports. The shared
archive and installed location controls gave no evidence that deferring the
wizard, moving the logger or changing the candidate working directory would
remove the stall. The test did not use elevated or system-wide trace capture.
The source and shipped distribution stayed intact. The first private ZIP
repack attempt exited 1 when mutable `ZipInfo` objects were shared between
read and write archives. The retry copied the metadata before writing and
verified every retained entry. [Diagnostic source](../../.git/yasb-prelog-startup-20261119/trace_copy.py).

## Final ordinary comparison

The final series reversed which build launched first. The order was
candidate, installed, installed, candidate, candidate, installed, installed,
candidate. Each row summarizes four fresh processes. The repeat median and
range use the last three processes for that build within its series. The
prior ordinary launches, copied-path trials and hash reads had already
conditioned the machine before the final series. Treat first-in-series times
as observed under those conditions.

| Series | Build | First log | First visible / ready | Repeat log median | Repeat visible median (range) | Repeat ready median (range) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Before | Candidate 2.0.9 | 1.898 s | 4.885 / 5.523 s | 0.602 s | 1.614 s (1.546–1.654) | 1.656 s (1.589–1.683) |
| Before | Installed 2.0.8 | 0.599 s | 1.929 / 1.975 s | 0.497 s | 1.416 s (1.400–1.445) | 1.471 s (1.424–1.489) |
| Final | Candidate 2.0.9 | 0.626 s | 1.543 / 1.615 s | 0.529 s | 1.386 s (1.355–1.463) | 1.425 s (1.397–1.504) |
| Final | Installed 2.0.8 | 0.514 s | 1.412 / 1.434 s | 0.459 s | 1.333 s (1.320–1.343) | 1.369 s (1.353–1.408) |

The final candidate repeats were about 53 ms slower to the bar and 56 ms
slower to message readiness than installed. The same ordinary candidate
also produced the slower first launch in the before series. Both ordinary
series and the controls exited 0 on all 48 measured launches. The ordinary
launch logs continue to contain the previously recorded COM diagnostics.
[Final timings](../../.git/yasb-prelog-startup-20261119/ordinary-final/summary.json),
[before timings](../../.git/yasb-prelog-startup-20261119/ordinary-before/summary.json).

The installed build remains the daily baseline. The candidate can continue
in evaluation with close repeat startup times. Confidence about the slow
first-launch case still requires a trace captured during that condition with
enough detail to identify the wait owner. True cold-cache behavior and
desktop presentation timing remain outside these measurements. The audit
matched all 540 source inputs, 16 live profile files, both shipped executable
and archive identities, and the Git index. It found zero owned processes
after shutdown and `git diff --check` exited 0.
[Integrity receipt](../../.git/yasb-prelog-startup-20261119/final-integrity.json).

## Bounded primary-thread wait follow-up

Two additional diagnostic launches used the candidate's shipped executable,
first at its ordinary `src\dist` location and then in a new directory. The
entire candidate distribution matched the copy across 250 file hashes.
The sampler took the primary TID from the native process-creation return,
verified its owner and used a duplicate of the owned thread and process
handles. It queried that TID with Wait Chain Traversal flags `0` and sampled
page faults, primary-thread CPU cycles and a short list of module names by
the owned PID. It used the shared Windows monotonic clock and wrote the
receipts after shutdown. Both sampler threads joined. No system-wide trace
or elevated permissions were used. [Sampler](../../.git/yasb-prelog-startup-20261119/startup_wait_sampler.py),
[wait-chain API](https://learn.microsoft.com/en-us/windows/win32/api/wct/nf-wct-getthreadwaitchain),
[copy proof](../../.git/yasb-prelog-startup-20261119/startup-waits/copy-byte-proof.json).

| Diagnostic launch | First log | First visible / ready | Primary-thread samples |
| --- | ---: | ---: | --- |
| Ordinary candidate | 1.192 s | 3.379 / 3.488 s | 10 single-node running statuses |
| Byte-identical new location | 2.457 s | 4.400 / 4.687 s | 13 single-node running and 13 single-node blocked statuses |

The first actual snapshot followed spawn by 242 ms on the ordinary launch
and 43 ms on the copy. One early module enumeration on the copy returned
`ERROR_NO_MORE_FILES` before the first successful module sample. In the
copy, `QtCore.pyd` was first sampled at about 636 ms and `Qt6Core.dll` at
824 ms. The primary cycle counter stayed at the same value for the samples
from about 635 through 822 ms, while the process page-fault count rose from
8,081 to 8,446. The same primary thread also had a flat cycle counter and
flat process fault counts across blocked samples at about 1.570 and 1.663 s.
These are sampled boundaries. Module presence does not mark completion of
its initialization, and the fault count does not distinguish disk faults
from faults that were resolved in memory.
[Ordinary wait samples](../../.git/yasb-prelog-startup-20261119/startup-waits/ordinary-1/wait-samples.json),
[copied wait samples](../../.git/yasb-prelog-startup-20261119/startup-waits/new-location-1/wait-samples.json).

All 36 wait queries succeeded. Every chain ended at the owned primary
thread. There was no wait object, downstream owner or cycle in any sample.
This establishes sampled blocked intervals during the slower copied launch
without identifying what released them. Both diagnostic processes exited 0.
The previous order-balanced series remains the ordinary comparison. The
source manifest, original executables and archives, live profile and Git
index matched after this follow-up. The bounded attribution check is
complete. [Diagnostic summary](../../.git/yasb-prelog-startup-20261119/startup-waits/summary.json),
[follow-up integrity](../../.git/yasb-prelog-startup-20261119/startup-waits/integrity.json).
