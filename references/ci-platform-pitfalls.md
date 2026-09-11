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

## FFmpeg 5.x (the 5.1.1 static-build CI job)

Found the day the job was added (#146); 6.1+ behaves the same on all three OSes, so none of
these had ever shown up before.

- **`scdet=...:sc_pass=1` passes only frames whose score exceeds the threshold.** On 5.x every
  truly static frame (score exactly 0: a title card, colour bars) is dropped before the next
  filter and the frame numbers are re-counted without them. `scenes.py` used it with
  `threshold=0` expecting every frame through, so a 4 s smptebars scene made the cuts on both
  sides of it disappear from its neighbourhood test. 6.1+ passes every frame regardless.
  Dropped the option; scores are also indexed by frame number now, missing frames counting as 0.
- **`drawtext` `boxborderw=v|h` (and the four-value form) is 6.1+.** 5.x and 6.0 fail the whole
  filter with "Error setting option boxborderw to value 9|16". `_common.drawtext_boxborderw()`
  emits the larger single value on older builds (`_common.ffmpeg_version()` parses
  `ffmpeg -version` once; it is the only place the tools branch on a version string).
- **`showwaves` keeps emitting frames after the audio ends, `-shortest` notwithstanding.** A
  12 s source came out 14.08 s on 5.1.1. `waveform.py` now also passes `-t <source duration>`.
- **`-display_rotation` is 6.0+.** Only the test fixture builder used it (to make a rotated
  phone-style clip); on 5.x it writes the stream's `rotate` tag instead, which every probe here
  reads identically.
- **John Van Sickle's 7.0.2 static build has no `drawtext`** (built with freetype, yet the
  filter is absent), and BtbN no longer publishes 7.x; the 7.1 job therefore runs in a Debian
  trixie container (apt ffmpeg 7.1.5 with libass, freetype and zimg).

## FFmpeg 7.1+ (the debian-trixie container CI job)

- **Output `-colorspace bt709` is no longer just a tag: on an untagged source it converts.**
  7.1 added colourspace negotiation to libavfilter, and the CLI feeds the encoder's
  `-colorspace/-color_primaries/-color_trc` into the graph's output constraints. A source
  whose bitstream carries no colour tags (`color_space=unknown` -- test sources, screen
  recordings, many cameras) then *differs* from the requested BT.709, so ffmpeg auto-inserts
  a real matrix conversion (swscale guesses bt601 for "unknown"): every SDR re-encode through
  `x264_args()` shifted the picture, and a `--lut-strength 0` no-op grade came back ~24 dB
  PSNR from its source. 5.x/6.x wrote the same options as tags only (47 dB, no conversion).
  The 7.0.2 static build does *not* show it; 7.1.1 (conda-forge) reproduces it locally, so
  that is the build to use when the trixie job goes red on a colour test.
  Fix: `_common.bt709_tag_args()` writes the tags through the encoder's own VUI parameters
  (`-x264-params colorprim=...:transfer=...:colormatrix=...`, x265 likewise) from 7.1 on,
  which libavfilter never sees; older builds keep the output options, since those were the
  only way to get an mp4 `colr` atom there. A decoder-side `-colorspace bt709 ... -i` override
  was tried first and rejected: it also tags a `-c copy` output of an untagged source (export
  copy must stay a real copy), and it exposed a separate, pre-existing `--correct` bug (below).
  Verified on 5.1.1, 6.1.1, 7.1.1 and 8.1.2. 8.x has the same encode-time conversion; it
  went unnoticed there because 8.x's `psnr` filter *also* negotiates colourspace and undid it
  before measuring (40 dB for re-matrixed pixels), and it then flagged the fixed, byte-clean
  output as 26 dB instead. The tests' `_psnr` helper now pins identical colour tags on both
  inputs so every build reports the same number for the same two files.
- **The conda-forge 7.1.1 build deadlocks on `tpad` + `adelay`/`apad` (pad.py) and ignores
  SIGTERM.** Debian's 7.1.5 in CI does not. Run pad tests against CI, not that build, and note
  that the tools have no subprocess timeout to get an agent out of such a hang.
- **Not a 7.1 issue, found while chasing it: `color --correct` desaturates a bt709-*tagged*
  source by ~8 % at identity settings on 6.1 and 7.1 alike** (113.6 → 103.9 saturation_avg):
  the RGB stages (exposure/colortemperature/colorbalance) make swscale go yuv→rgb with the
  frame's bt709 matrix and back with its bt601 default. The identity test only ever used an
  untagged source, where both legs pick bt601 and cancel out. Tracked separately.
