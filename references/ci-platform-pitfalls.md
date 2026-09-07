# Platform-specific CI pitfalls

Behaviour differences between macOS/Linux/Windows CI runners and their ffmpeg
builds that are not bugs in this repo's code — they were each independently
diagnosed once, at real cost (full CI cycles, log-reading, re-fixture
attempts). Written down so the next person (or the next session) does not
re-diagnose them from scratch. Add to this file whenever a fix in this repo
exists only because a platform's real, observed behaviour forced it — not
for hypothetical differences.

## Windows

### `-pattern_type glob` is unsupported on the Chocolatey ffmpeg build

The Windows GitHub Actions runner's `choco install ffmpeg` build fails with
`Pattern type 'glob' was selected but globbing is not supported by this
libavformat build` — glob support depends on how libavformat was compiled,
and this build lacks it entirely. There is no flag or workaround within
`-pattern_type glob` itself.

Fix used in `sequence.py`: resolve the frame list in Python (`glob.glob` or
walking consecutive numbered filenames) and feed ffmpeg an explicit
**concat-demuxer list file** instead of relying on `-pattern_type glob`.
This works identically on all three OSes since it never depends on
libavformat's own globbing.

### The concat demuxer's "repeat last file" duration trick over-counts by one frame

The standard technique for giving the last file in a concat list a duration
(repeat its entry once with no explicit `duration` line, so ffmpeg holds it
until EOF) produced an extra frame's worth of output duration on some ffmpeg
builds — e.g. 1.2s of output for footage that should total 1.0s. Observed on
both macOS and Windows CI after switching `sequence.py` to the concat
demuxer (see above).

Fix: pass an explicit `-t <total_duration>` alongside the concat list so the
output is truncated to the intended length regardless of how the demuxer's
own end-marker behaves on a given build.

### A `#!/bin/sh` fake-ffmpeg PATH shim is not portable to Windows

Several tests fake ffmpeg's behaviour (e.g. "exits 0 but writes nothing") by
dropping a `#!/bin/sh` script named `ffmpeg` earlier on `PATH`. This has no
Windows equivalent — `cmd.exe`/PowerShell do not execute a shebang script
named `ffmpeg` the way a POSIX shell resolves `ffmpeg` on `PATH`, so the
fake binary is silently never picked up and the test either fails for the
wrong reason or exercises the real ffmpeg instead.

Fix: `@unittest.skipIf(platform.system() == "Windows", "reason echoing this
note")` on every test that depends on this shim technique, rather than
trying to make the shim itself cross-platform. Established first on
`test_dry_run_never_runs_ffmpeg_and_writes_nothing` and the
`DoctorDetectionTests` class; the same pattern was later needed for
`test_output_verification_failures_are_loud` when it was added by a
different change that didn't carry the context forward. When adding a new
shim-based test, search the test files for this skip pattern and mirror it
rather than rediscovering the failure on a Windows CI run.

### A real ffmpeg crash's OS-reported exit code does not match this repo's self-reported one, on Windows only

When ffmpeg genuinely crashes (e.g. parsing a corrupt `.cube` LUT, or being
told to write into a directory that does not exist), Windows reports the
subprocess's exit code as a large unsigned-32-bit value (`4294967295`,
`3199971767`, `4294967294`, ...) that does not exactly equal what this
repo's own `die()`-driven JSON `exit_code` field captured for the same
failure. Confirmed not a flake by re-running the identical commit's
identical job and getting byte-identical numbers both times; the mismatch
recurs on different failure sub-cases with different specific numbers each
time. This is inherent to how Windows reports a crashed child process's
exit status through Python's `subprocess` — not a bug in `verify_output()`
or `die()`.

Fix: tests that assert on `exit_code` for a `kind == "ffmpeg"` failure only
assert `!= 0` on Windows, and assert the exact expected value on
macOS/Linux. Do not chase exact-value parity on Windows for this class of
failure — it is not achievable without changing how the OS reports crashed
subprocesses, which is out of this repo's control.

## macOS

### `vidstabdetect`/`vidstabtransform` (libvidstab) behaves meaningfully differently across ffmpeg builds

A synthetic camera-shake test fixture that reliably gets *less* jittery
after `stabilize.py` on Linux CI can reliably get *more* jittery (a larger
measured frame-to-frame motion, not smaller) on macOS CI's ffmpeg build —
this was independently confirmed across three different fixture designs
(a single clean sine-wave jitter; a multi-frequency jitter including a fast
~9.1Hz component; a retuned multi-frequency jitter in a more realistic
1-2Hz hand-tremor range), all of which passed on Linux and all of which
failed differently on macOS. This points to a genuine behavioural
difference in libvidstab (or how it's built/linked) between the two
platforms' ffmpeg, not a fixable property of the test fixture — a fixture
cannot be tuned to satisfy two optical-flow implementations that disagree.

Fix: `test_stabilize_reduces_frame_to_frame_motion` only asserts the
quantitative "motion went down" claim on Linux
(`if platform.system() == "Linux":`); on every platform it still asserts
the tool ran, produced output, and the output has the expected duration —
so the test still catches a genuinely broken `stabilize.py`, just not a
libvidstab behavioural quirk that is outside this repo's control. Don't
spend another cycle retuning the fixture frequencies again — three attempts
already ruled that out.

## General

When a test needs to special-case a platform, prefer gating with
`platform.system()` (already imported for this purpose in
`tests/test_all.py` and `tests/test_contract.py`) over inventing a new
mechanism, and write the skip/relaxation reason as a full sentence
explaining the underlying platform behaviour — not just "flaky on
Windows" — so a future reader doesn't have to re-derive it from the CI log.
