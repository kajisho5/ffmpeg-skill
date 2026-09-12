#!/usr/bin/env python3
"""Shared helpers for ffmpeg-skill scripts.

Standard library only. Locates ffmpeg/ffprobe on PATH, runs them with clear
error reporting, and provides a compact media probe used by every script.
"""
from __future__ import annotations

import json
import os
import platform
import argparse
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Every script prints paths, help text and reports that may contain non-ASCII (Japanese examples,
# arrows). On Windows the console streams default to a legacy code page and raise
# UnicodeEncodeError; make them UTF-8 with replacement so a --help never crashes on encoding.
for _stream in (sys.stdout, sys.stderr):
    try:
        if getattr(_stream, "encoding", "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

INSTALL_HINTS = {
    "Darwin": "  brew install ffmpeg-full   (the plain ffmpeg formula lacks subtitles/drawtext/zscale)",
    "Linux": (
        "  Debian/Ubuntu: sudo apt install ffmpeg\n"
        "  Fedora:        sudo dnf install ffmpeg\n"
        "  Arch:          sudo pacman -S ffmpeg"
    ),
    "Windows": (
        "  winget install Gyan.FFmpeg\n"
        "  or: choco install ffmpeg\n"
        "  or download a build from https://ffmpeg.org/download.html and add it to PATH"
    ),
}


# `kind` (below) is the machine-readable failure axis: input / missing_tool / ffmpeg / output
# since 0.1, plus timeout (1.3), verification (1.4.3) and interrupted (1.4.10). `ERROR_CODE` is an
# additive, purely informational refinement layered on top for agents that want a stable enum to
# switch on instead of pattern-matching `kind` strings -- a static 1:1 relabelling of the same
# buckets, not a new taxonomy. It intentionally does NOT introduce categories this codebase cannot actually
# distinguish today (e.g. a separate ffprobe-vs-ffmpeg code, or an environment-vs-content-cause
# split of ffmpeg failures): every ffmpeg subprocess failure is currently one undifferentiated
# bucket regardless of whether ffmpeg rejected a bad filter argument or died from a full disk,
# and every "kind": "input" failure covers both a missing file and a bad flag value alike. Adding
# codes for distinctions the code can't actually make would be guessing, not reporting -- if a
# future call site can genuinely tell capability-missing apart from bad-argument (see doctor()'s
# available/missing/unknown states, which already model this for detection but aren't wired into
# any die() call), split ERROR_CODE then, with evidence, not speculatively now.
ERROR_CODE = {
    "input": "INPUT_INVALID",
    "missing_tool": "DEPENDENCY_MISSING",
    "ffmpeg": "FFMPEG_EXECUTION_FAILED",
    "output": "OUTPUT_INVALID",
    "timeout": "TIMEOUT",
    "verification": "VERIFICATION_FAILED",
    "interrupted": "INTERRUPTED",
}

# Wall-clock ceiling for one ffmpeg/ffprobe invocation, in seconds. A hung ffmpeg (a build
# that deadlocks on a filter combination, a stalled network mount, an input that never ends)
# used to hang the calling agent with it, with no error document and no way out short of
# killing the process by hand. The ceiling is generous on purpose: it exists to turn a hang
# into a reported failure, not to police slow encodes. --timeout and FFMPEG_SKILL_TIMEOUT
# override it; 0 disables it.
DEFAULT_TIMEOUT = 1800.0
PROBE_TIMEOUT = 120.0


def _env_timeout() -> float:
    try:
        return max(0.0, float(os.environ.get("FFMPEG_SKILL_TIMEOUT", DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT

# None of the four kinds above are retryable in practice: an "input"/"missing_tool" failure is
# always deterministic (the same bad path or absent binary fails identically every time), and a
# "ffmpeg"/"output" failure -- while it COULD in principle be caused by a transient environment
# condition (full disk, OOM) rather than a bad command -- is never distinguishable from a
# deterministic content-cause failure without exit-code/stderr sniffing this codebase does not do.
# Reporting retryable=True for a code we can't actually back up would invite an agent into a blind
# retry loop against a command that will fail the same way every time; false-for-everything is the
# honest answer until real sniffing exists to justify anything else.
ERROR_RETRYABLE = False


_FFMPEG_VERSION: "Optional[Tuple[int, int]]" = None


def ffmpeg_version() -> "Tuple[int, int]":
    """(major, minor) of the FFmpeg build on PATH, parsed once from `ffprobe -version`; (0, 0)
    when it cannot be read. ffprobe rather than ffmpeg because --dry-run promises never to run
    ffmpeg (docs/contract.md: ffmpeg_execution "none") while ffprobe always may, and the two
    ship from the same build. Used only to pick between two spellings of an option where FFmpeg
    changed behaviour between releases (the tools otherwise never branch on the version: doctor's
    capability listing is the source of truth for what a build can do)."""
    global _FFMPEG_VERSION
    if _FFMPEG_VERSION is None:
        _FFMPEG_VERSION = (0, 0)
        try:
            out = subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 timeout=PROBE_TIMEOUT).stdout
            m = re.search(r"ffprobe version\s+n?(\d+)\.(\d+)", out)
            if m:
                _FFMPEG_VERSION = (int(m.group(1)), int(m.group(2)))
            else:
                # git / vendor builds print "N-115000-g..." or a date, never major.minor; the
                # libavutil major is still there and maps one-to-one onto the FFmpeg major
                # (56=4, 57=5, 58=6, 59=7, 60=8). Without this every version branch took the
                # oldest spelling on such builds: on 7.1 that skipped bt709_tag_args()'s
                # workaround and an untagged source got a real matrix conversion.
                m = re.search(r"^libavutil\s+(\d+)\.", out, re.M)
                if m:
                    major = int(m.group(1)) - 52
                    if major >= 4:
                        _FFMPEG_VERSION = (major, 0)
        except (OSError, subprocess.TimeoutExpired):
            # (0, 0) = unknown: every version branch then takes the older, universally accepted
            # spelling, the same "unknown is not missing" stance doctor takes.
            pass
    return _FFMPEG_VERSION


def drawtext_boxborderw(vertical: int, horizontal: int) -> str:
    """drawtext's per-side `boxborderw=top|right|bottom|left` (and the two-value `v|h` form)
    arrived in FFmpeg 6.1; 5.x and 6.0 reject the `|` with "Error setting option boxborderw"
    (found by the FFmpeg 5.1.1 CI job, #146). Older builds get the larger single value."""
    if ffmpeg_version() >= (6, 1):
        return f"{vertical}|{horizontal}"
    return str(max(vertical, horizontal))


def pad_filters(out_w: int, out_h: int, fill: str, color: str, blur: int) -> str:
    """The letterbox/pillarbox step shared by fit.py and export.py, as one -vf segment.

    fill="color": scale to fit, then pad with a solid colour (the historical behaviour).
    fill="blur": the bars are a blurred, scaled-to-cover copy of the same frame -- what every
    phone editor's "make it vertical" does with landscape footage (#139). Built as a small
    graph inside the -vf chain: split, one branch scaled to cover and cropped to the frame
    then boxblur'ed, the other scaled to fit, overlaid centred. Only `filter:boxblur` is
    needed beyond the usual scale/pad set, and that is already required by redact.py."""
    if fill == "blur":
        # boxblur rejects a radius larger than half the smaller dimension ("radius 20, must be
        # <= 8" on a 16 px target); clamp instead of failing an otherwise valid request
        radius = max(1, min(int(blur), max(1, min(out_w, out_h) // 2 - 1)))
        return (f"split[__fitfg][__fitbg];"
                f"[__fitbg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur={radius}:2[__fitbgb];"
                f"[__fitfg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[__fitfgs];"
                f"[__fitbgb][__fitfgs]overlay=(W-w)/2:(H-h)/2:format=auto")
    return f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color={color}"


def add_pad_fill_args(parser: "argparse.ArgumentParser") -> None:
    parser.add_argument("--pad-fill", choices=["color", "blur"], default="color",
                        help="what fills the letterbox/pillarbox bars under --fit pad: a solid --pad-color (default) or a blurred, scaled-up copy of the frame")
    parser.add_argument("--pad-blur", type=int, default=20, help="blur radius in pixels for --pad-fill blur (default 20)")


def die(msg: str, code: int = 1, kind: str = "input", **extra: Any) -> "None":
    """Exit with a message. Under --json also print a machine-readable failure document
    (status: failed) on stdout so callers get the same shape as a success; exit codes are unchanged.

    `extra` fields are added to the failure document: a tool whose *result* failed (check.py's
    platform rows, render.py's check stage, batch.py's per-item results, verify.py's steps) keeps
    reporting that detail while the top-level status says failed. Before 1.4.3 those four printed
    `status: "completed"` next to a non-zero exit code, so a caller keying on the status alone
    read a failed delivery as a success."""
    hint = extra.pop("hint", None)
    sys.stderr.write(f"error: {msg}\n" + (f"hint: {hint}\n" if hint else ""))
    if STATE.json:
        doc: Dict[str, Any] = {
            "status": "failed", "exit_code": code,
            "error": {
                "kind": kind, "message": msg,
                "code": ERROR_CODE.get(kind, "INTERNAL_ERROR"),
                "retryable": ERROR_RETRYABLE,
            },
            "commands": list(STATE.commands),
        }
        if hint:
            doc["error"]["hint"] = hint
        doc.update(extra)
        print_json(doc)
    sys.exit(code)


def info(msg: str) -> None:
    # under --dry-run nothing is written; do not let scripts claim otherwise
    if msg.startswith("wrote ") and STATE.dry_run:
        msg = "[dry-run] would write " + msg[len("wrote "):]
    sys.stderr.write(f"{msg}\n")


def require_tool(name: str) -> str:
    """Return the absolute path of ffmpeg/ffprobe or exit with install steps."""
    path = shutil.which(name)
    if path:
        return path
    system = platform.system()
    hint = INSTALL_HINTS.get(system, "  See https://ffmpeg.org/download.html")
    die(
        f"'{name}' was not found on PATH.\n"
        f"Install FFmpeg (which includes ffprobe) for {system}:\n{hint}",
        code=127, kind="missing_tool",
    )
    return ""  # unreachable


X264_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo")


class Context:
    """Per-process settings that the shared flags (--dry-run, --json, --progress, --fast) set once.

    Scripts read it as attributes (``STATE.dry_run``); the dict-style shims that once served
    older call sites are gone. Keeping it a single explicit object rather than module globals
    makes it obvious what run()/emit() depend on and lets tests reset it with ``STATE.reset()``.
    """

    __slots__ = ("dry_run", "json", "progress", "fast", "duration_hint", "commands", "timeout", "overwrite", "written", "preexisting")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.dry_run = False      # print ffmpeg commands, run nothing (ffprobe still runs)
        self.json = False         # emit() prints a JSON document instead of the output path
        self.progress = False     # run() streams percent / ETA to stderr for ffmpeg
        self.fast = False         # x264 preset forced to veryfast
        self.duration_hint: Optional[float] = None  # expected output length, for the progress percent
        self.commands: List[str] = []               # every ffmpeg command line, for --json and --dry-run
        self.timeout: float = _env_timeout()         # seconds per ffmpeg invocation, 0 = none
        self.overwrite = False                       # --overwrite: an existing output may be replaced
        self.written: set = set()                    # output paths this process has written itself
        self.preexisting: dict = {}                  # output path -> (size, mtime_ns) of a file that was there before we ran



STATE = Context()


def add_common(ap: "argparse.ArgumentParser") -> None:
    """Add the flags every script shares."""
    g = ap.add_argument_group("agent options")
    g.add_argument("--dry-run", action="store_true", help="print the ffmpeg commands that would run, run nothing")
    g.add_argument("--json", action="store_true", help="print a JSON result (output, probe, commands) on stdout instead of the path")
    g.add_argument("--progress", action="store_true", help="show percent / ETA on stderr while ffmpeg encodes")
    g.add_argument("--fast", action="store_true", help="preview quality: x264 preset veryfast (overrides --preset) for quick iterations")
    if "--timeout" not in ap._option_string_actions:  # verify.py defines its own per-step --timeout; apply_common reads either
        g.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                       help=f"kill an ffmpeg run past this many seconds, kind=timeout (default {DEFAULT_TIMEOUT:.0f}; 0 = no limit)")
    g.add_argument("--overwrite", action="store_true",
                   help="allow replacing an existing output (warned today, refused from 2.0)")


def apply_common(args: "argparse.Namespace") -> None:
    STATE.dry_run = bool(getattr(args, "dry_run", False))
    STATE.json = bool(getattr(args, "json", False))
    STATE.progress = bool(getattr(args, "progress", False))
    STATE.fast = bool(getattr(args, "fast", False))
    STATE.overwrite = bool(getattr(args, "overwrite", False))
    if getattr(args, "timeout", None) is not None:
        STATE.timeout = max(0.0, float(args.timeout))
    if STATE.fast and getattr(args, "preset", None) in X264_PRESETS:
        args.preset = "veryfast"
    crf = getattr(args, "crf", None)
    if crf is not None and not 0 <= int(crf) <= 51:
        die(f"--crf must be between 0 and 51 (x264/x265 scale; 18 is visually lossless, 23 the encoder default), got {crf}")
    install_signal_handlers()


# The child processes this tool is waiting on right now (an ffmpeg, or a sibling script under
# run_tool), with the command whose partial output would need removing. A signal handler
# reads it; the runners keep it current. Before 1.4.9 a SIGTERM to the tool (a cancelled MCP
# call, a supervisor's stop, a closed terminal) killed only the Python parent: ffmpeg carried on
# as an orphan, finished a file nobody verified, and the caller got no JSON at all; SIGINT was a
# KeyboardInterrupt traceback with the partial left on disk.
_CHILDREN: List[Tuple[subprocess.Popen, Sequence[str]]] = []
_SIGNALS_INSTALLED = False


def _on_signal(signum: int, frame: Any) -> None:
    import signal as _signal
    name = {getattr(_signal, "SIGINT", None): "SIGINT", getattr(_signal, "SIGTERM", None): "SIGTERM"}.get(signum, str(signum))
    for proc, cmd in list(_CHILDREN):
        try:
            proc.terminate()  # ffmpeg exits promptly on SIGTERM; a sibling script runs this same handler
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        except OSError:
            pass
        if cmd:
            _cleanup_partial_output(cmd)
    _CHILDREN.clear()
    die(f"interrupted by {name}: the running command was stopped and its partial output removed; nothing was written",
        code=128 + signum, kind="interrupted")


def install_signal_handlers() -> None:
    """SIGINT/SIGTERM stop the child, remove its partial output and exit with a failure document
    (kind: interrupted, exit 130/143). Main thread only; on Windows SIGTERM is never delivered,
    SIGINT (Ctrl-C) is."""
    global _SIGNALS_INSTALLED
    if _SIGNALS_INSTALLED:
        return
    import signal as _signal
    import threading
    if threading.current_thread() is not threading.main_thread():
        return
    for sig in (getattr(_signal, "SIGINT", None), getattr(_signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            _signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass
    _SIGNALS_INSTALLED = True


def _watch(proc: subprocess.Popen, cmd: Sequence[str]) -> None:
    _CHILDREN.append((proc, cmd))


def _unwatch(proc: subprocess.Popen) -> None:
    _CHILDREN[:] = [(p, c) for p, c in _CHILDREN if p is not proc]


def emit(output: Optional[str], **extra: Any) -> None:
    """Final stdout line: the output path, or a JSON document with --json."""
    meta: Dict[str, Any] = {}
    if output and not STATE.dry_run:
        meta = verify_output(output)  # dies (status: failed, kind: output) if the artifact is unusable
    if STATE.json:
        doc: Dict[str, Any] = {"status": "completed", "output": output, "dry_run": STATE.dry_run, "commands": list(STATE.commands)}
        if meta:
            doc["probe"] = meta
        doc.update(extra)
        print_json(doc)
    elif output:
        print(output)


def _cmdline(cmd: Sequence[str]) -> str:
    return " ".join(shell_quote(c) for c in cmd)


def _is_ffmpeg(cmd: Sequence[str]) -> bool:
    return os.path.basename(cmd[0]).startswith("ffmpeg")


def _cleanup_partial_output(cmd: Sequence[str]) -> None:
    """A failed ffmpeg command can still have opened its output container (muxer header
    written) before erroring out mid-stream -- unlike a failure that happens before ffmpeg ever
    touches the output path (a bad filter argument, a missing input), which never creates the
    file at all. Both are reported the same way (status: failed), but only the first case used
    to leave a stray, usually-0-byte file behind: verify_output()'s cleanup only runs on the
    success path, so a failed run() call never routed through it. Remove whatever ffmpeg managed
    to write so a caller scanning the output directory after a failure never mistakes a partial
    artifact for a real (if unverified) one."""
    # run() also executes ffprobe, whose last argument is an INPUT. Never
    # interpret a read-only tool's failure as permission to remove that file.
    if not _is_ffmpeg(cmd):
        return
    output = cmd[-1]
    if output in ("-", "pipe:0", "pipe:1") or output.startswith("pipe:") or output.startswith("-"):
        return
    try:
        if not os.path.exists(output):
            return
        # A file that was already there before this command ran is someone's deliverable, not
        # our partial. If ffmpeg died before opening it (bad filter argument, unreadable input:
        # the common case) it is byte-for-byte what it was, so leave it alone. Only when ffmpeg
        # did open and truncate it (size or mtime changed) is what remains a partial of ours,
        # and the original is already gone either way; then removing it is still right.
        before = STATE.preexisting.get(os.path.realpath(output))
        if before is not None:
            st = os.stat(output)
            if (st.st_size, st.st_mtime_ns) == before:
                return
        os.remove(output)
    except OSError:
        pass


def _fail(cmd: Sequence[str], returncode: int, stderr: str) -> None:
    # Partial-output cleanup already ran in the caller (_run_captured/_run_with_progress) for
    # every failed ffmpeg invocation, not just this check=True path -- see _cleanup_partial_output.
    tail = "\n".join(stderr.strip().splitlines()[-15:])
    die(f"command failed ({returncode}): {cmd[0]}\n{tail}", code=returncode or 1, kind="ffmpeg")


def _check_no_overwrite_input(cmd: Sequence[str]) -> None:
    """Refuse an ffmpeg command whose output path resolves to the same file as one of its
    inputs. ffmpeg's own "Output same as Input" guard only catches byte-identical path
    strings; a relative/absolute pair, a leading "./", a redundant ".." segment, or a symlink
    all resolve to the same file but pass that check, so "-o ./same.mp4" on an input opened as
    "same.mp4" would otherwise silently let ffmpeg's -y clobber the source mid-encode. Every
    write-side script routes through this one run() choke point rather than each computing its
    own output path defensively, so the guard lives here once instead of at 25+ call sites."""
    output = cmd[-1]
    if output in ("-", "pipe:0", "pipe:1") or output.startswith("pipe:") or output.startswith("-"):
        return
    try:
        out_real = os.path.realpath(output)
    except OSError:
        return
    for i, a in enumerate(cmd):
        if a == "-i" and i + 1 < len(cmd):
            inp = cmd[i + 1]
            try:
                if os.path.realpath(inp) == out_real:
                    die(f"refusing to run: output {output!r} is the same file as input {inp!r} "
                        f"(would overwrite it while ffmpeg is still reading it) -- choose a different --output/-o path",
                        kind="input")
            except OSError:
                continue


def refuse_output_is_input(output: str, *inputs: str) -> None:
    """Tool-level twin of the run() guard, for tools whose final ffmpeg command does not name
    the user's input at all. `cut.py --segments` cuts each part into a temp dir and then concats
    a list file: the last command's only `-i` is that list, so `-o` equal to the input sailed
    through _check_no_overwrite_input() and replaced the source with the join (fourth audit,
    P0). Call it once the output path is known, before any part of the input is consumed."""
    try:
        out_real = os.path.realpath(output)
    except OSError:
        return
    for inp in inputs:
        try:
            same = os.path.realpath(inp) == out_real
        except OSError:
            continue
        if same:
            die(f"refusing to run: output {output!r} is the same file as input {inp!r} "
                f"(the result would replace the source) -- choose a different --output/-o path", kind="input")


def _check_output_path(cmd: Sequence[str]) -> None:
    """An output whose directory does not exist, or that names a directory, is a caller mistake:
    say so as `kind: input` before ffmpeg runs, instead of the muxer's "No such file or directory"
    as `kind: ffmpeg` (which reads as an encoder failure) or an `OUTPUT_INVALID` after the fact."""
    output = cmd[-1]
    if output == "-" or output.startswith("pipe:") or output.startswith("-"):
        return
    if os.path.isdir(output):
        die(f"output {output!r} is a directory; pass a file path (e.g. {os.path.join(output, 'result.mp4')!r})")
    parent = os.path.dirname(os.path.abspath(output))
    if not os.path.isdir(parent):
        die(f"output directory {parent!r} does not exist; create it first (this tool never creates directories)")
    if not os.access(parent, os.W_OK):
        die(f"output directory {parent!r} is not writable")


EVEN_SCALE = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _pid_dead(pid: int) -> bool:
    """True only when the process is known not to exist. POSIX: signal 0. Windows: OpenProcess
    fails with ERROR_INVALID_PARAMETER (87) for a pid that is not in use; any other outcome
    (a handle, or access denied) means it is live. Unknown is treated as live."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            k32.CloseHandle(handle)
            return False
        return k32.GetLastError() == 87
    except Exception:
        return False


class _OutputLock:
    """Two runs writing the same output at once used to both report `completed` while one of
    them described the other's file (sweep F1). A lock file next to the output, created with
    O_EXCL and holding the writer's pid, makes the second run refuse as `kind: input`. A lock
    whose pid is dead (POSIX) or older than an hour is stale and taken over."""
    def __init__(self, output: str) -> None:
        self.path: Optional[str] = None
        self.fd: Optional[int] = None
        if output == "-" or output.startswith("pipe:") or output.startswith("-"):
            return
        d, base = os.path.split(os.path.abspath(output))
        self.path = os.path.join(d, f".{base}.ffskill-lock")

    def __enter__(self) -> "_OutputLock":
        if not self.path:
            return self
        for attempt in (0, 1):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                if attempt == 0 and self._stale():
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                die(f"another run is writing {os.path.basename(self.path)[1:-len('.ffskill-lock')]!r} right now "
                    f"(lock {self.path}); wait for it or choose a different --output/-o path")
            except OSError:
                return self  # unlockable location (read-only dir surfaces elsewhere): proceed without a lock
        return self

    def _stale(self) -> bool:
        try:
            pid = int(open(self.path).read().strip() or "0")
            if pid > 0 and _pid_dead(pid):
                return True
            import time
            return time.time() - os.path.getmtime(self.path) > 3600
        except (OSError, ValueError):
            return True

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        if self.path:
            try:
                os.remove(self.path)
            except OSError:
                pass


def _odd_dimension_retry(cmd: List[str], stderr: str) -> Optional[List[str]]:
    """An odd-sized source (641x359 screen captures, some 4:4:4 masters) fails every yuv420p
    encode with "width/height not divisible by 2" (sweep F8, 15 tools). Return the same command
    with an even-dimension scale prepended to its -vf chain (or a new -vf when the command had
    none); None when the failure is something else or the graph is a -filter_complex the
    caller has to fix itself."""
    if "not divisible by 2" not in stderr or EVEN_SCALE in cmd or any(EVEN_SCALE in a for a in cmd):
        return None
    if "-filter_complex" in cmd:
        return None
    new = list(cmd)
    if "-vf" in new:
        i = new.index("-vf") + 1
        new[i] = EVEN_SCALE + "," + new[i]
        return new
    if "-c:v" in new and new[new.index("-c:v") + 1] == "copy":
        return None
    return new[:-1] + ["-vf", EVEN_SCALE, new[-1]]


def _check_existing_output(cmd: Sequence[str]) -> None:
    """An output path that already exists is someone's file: a previous result, a source the
    agent mis-named, a deliverable from another run. ffmpeg's -y (which every command carries so
    a run never blocks on a y/N prompt) would replace it without a word. Until 2.0 this only
    warns, per docs/contract.md's deprecation policy; FFMPEG_SKILL_NO_OVERWRITE=1 opts into the
    2.0 behaviour (refuse) today, and --overwrite is the explicit consent either way. Paths this
    process wrote itself (a two-pass tool, a copy-then-re-encode fallback) are never in question."""
    output = cmd[-1]
    if output in ("-",) or output.startswith("pipe:") or output.startswith("-"):
        return
    try:
        exists = os.path.isfile(output)
        real = os.path.realpath(output)
    except OSError:
        return
    if not exists or real in STATE.written:
        return
    try:
        st = os.stat(output)
        STATE.preexisting[real] = (st.st_size, st.st_mtime_ns)
    except OSError:
        pass
    if STATE.overwrite:
        return
    if os.environ.get("FFMPEG_SKILL_NO_OVERWRITE", "") not in ("", "0"):
        die(f"refusing to overwrite existing output {output!r}: pass --overwrite to replace it, or choose another -o path", kind="input")
    info(f"warning: {output} already exists and will be overwritten (pass --overwrite to confirm; "
         f"from 2.0 an existing output is refused without it, FFMPEG_SKILL_NO_OVERWRITE=1 enables that now)")


def _remember_output(cmd: Sequence[str]) -> None:
    output = cmd[-1]
    if output == "-" or output.startswith("pipe:") or output.startswith("-"):
        return
    try:
        STATE.written.add(os.path.realpath(output))
    except OSError:
        pass


def _timed_out(cmd: Sequence[str], seconds: float) -> "None":
    _cleanup_partial_output(cmd)
    die(f"{os.path.basename(cmd[0])} exceeded the {seconds:.0f} s time limit and was killed; nothing was written. "
        f"Raise --timeout (or FFMPEG_SKILL_TIMEOUT) if the job is genuinely that long, or check the input for a stall",
        code=124, kind="timeout")


def _stage_existing_output(cmd: Sequence[str]) -> Tuple[List[str], Optional[str], Optional[str]]:
    """When the output path already holds someone's file, run ffmpeg against a hidden sibling
    temp path and move it over the original only on success.

    ffmpeg's -y truncates the output the moment it opens it, and *when* it opens it depends on
    the version: 6.1+ initialises the filter graph first (a bad LUT fails before the file is
    touched), 5.x opens the output during option parsing, before any filter runs, so the same
    bad LUT leaves a 0-byte file where the deliverable was. No amount of post-failure cleanup
    can undo that; the only way to keep an existing file safe across a failed run is for ffmpeg
    never to write to it. Same directory, same extension (the muxer is chosen by it), hidden
    name, so nothing else changes for the encoder. Returns (command to execute, final path,
    temp path); (cmd, None, None) when no staging is needed."""
    output = cmd[-1]
    if output == "-" or output.startswith("pipe:") or output.startswith("-"):
        return list(cmd), None, None
    try:
        if not os.path.isfile(output) or os.path.realpath(output) in STATE.written:
            return list(cmd), None, None
    except OSError:
        return list(cmd), None, None
    d, base = os.path.split(output)
    stem, ext = os.path.splitext(base)
    tmp = os.path.join(d, f".{stem}.ffskill-{os.getpid()}{ext}")
    return list(cmd[:-1]) + [tmp], output, tmp


def run(cmd: Sequence[str], *, quiet: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, echoing it to stderr unless quiet. Exits on failure when check=True.

    ffmpeg invocations are recorded in STATE.commands (for --json), skipped under --dry-run
    (a fake successful CompletedProcess is returned so scripts can keep planning), and run
    with a progress readout under --progress. ffprobe and other tools always run. An output
    path that already exists is written through a temp file and replaced only on success
    (see _stage_existing_output), so a failed run never costs the caller the file that was there.
    """
    is_ffmpeg = _is_ffmpeg(cmd)
    if is_ffmpeg:
        _check_no_overwrite_input(cmd)
        _check_output_path(cmd)
        _check_existing_output(cmd)
        STATE.commands.append(_cmdline(cmd))
    if not quiet:
        info(("[dry-run] $ " if STATE.dry_run and is_ffmpeg else "$ ") + _cmdline(cmd))
    if STATE.dry_run and is_ffmpeg:
        return subprocess.CompletedProcess(list(cmd), 0, "", "")
    with _OutputLock(cmd[-1] if is_ffmpeg else "-"):
        exec_cmd, final, tmp = _stage_existing_output(cmd) if is_ffmpeg else (list(cmd), None, None)
        proc = _execute(exec_cmd)
        if proc.returncode != 0 and is_ffmpeg:
            retry = _odd_dimension_retry(exec_cmd, proc.stderr or "")
            if retry is not None:
                info("source has odd dimensions; scaling to even before encoding (yuv420p needs it)")
                STATE.commands[-1] = _cmdline(retry[:-1] + [cmd[-1]])
                proc = _execute(retry)
            elif "not divisible by 2" in (proc.stderr or ""):
                die("the source has odd dimensions (width or height not divisible by 2) and this tool's filter graph "
                    "cannot pad them itself; make them even first, e.g. fit.py --width/--height, then retry",
                    kind="input")
        if proc.returncode != 0 and check:
            _fail(exec_cmd, proc.returncode, proc.stderr or "")
        if final and tmp:
            if proc.returncode == 0:
                try:
                    os.replace(tmp, final)
                except OSError as e:
                    _cleanup_partial_output(exec_cmd)
                    die(f"could not replace {final} with the new output: {e}", kind="output")
                _remember_output(cmd)
            else:
                _cleanup_partial_output(exec_cmd)
    return proc


def _execute(exec_cmd: List[str]) -> subprocess.CompletedProcess:
    """One attempt, never exiting on failure (run() decides after its retries)."""
    if STATE.progress and _is_ffmpeg(exec_cmd) and exec_cmd[-1] != "-":
        return _run_with_progress(exec_cmd, False)
    return _run_captured(exec_cmd, False)


def run_analysis(cmd: Sequence[str], *, check: bool = True, text: bool = True, record: bool = False) -> subprocess.CompletedProcess:
    """Run an ffmpeg *measurement* (scene scores, crop rectangles, decoded PCM, signal stats,
    silence detection, loudness, stabilisation pass 1): output to `-f null`, a pipe or a temp
    file, no deliverable written. These are not run() calls -- they run under --dry-run too,
    since a plan built on a fake measurement is not a plan (silence.py used to report "0
    silences" and loudness.py a made-up -20 LUFS under --dry-run) -- but they get the same
    wall-clock limit as any other ffmpeg invocation and, with check=True, the same `kind: ffmpeg`
    failure instead of an exit-0 "0 scenes found" over a file ffmpeg could not read. record=True
    lists the command in the --json `commands` like run() does."""
    if record:
        STATE.commands.append(_cmdline(cmd))
    limit = _limit_for(cmd)
    try:
        proc = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, timeout=limit)
    except subprocess.TimeoutExpired:
        _timed_out(cmd, limit or 0)
    if check and proc.returncode != 0:
        err = proc.stderr if text else proc.stderr.decode(errors="replace")
        _fail(cmd, proc.returncode, err)
    return proc


def dry_run_input_pending(path: str) -> bool:
    """True when a measurement cannot run because its input does not exist yet under --dry-run:
    in a render.py/batch.py plan each stage's input is the previous stage's output, which a dry
    run never wrote. The measurement is then skipped (with a note) rather than failing the plan;
    on a real file the measurement runs even under --dry-run."""
    if STATE.dry_run and not os.path.exists(path):
        info(f"[dry-run] {path} does not exist yet (an earlier dry-run stage would write it); measurement skipped")
        return True
    return False


def child_limit(per_call: Optional[float] = None) -> Optional[float]:
    """Wall-clock ceiling for running one sibling script as a subprocess (render/batch/report
    stages, the MCP server's dispatch). A tool runs a handful of ffmpeg/ffprobe calls, each
    under its own --timeout, so the outer ceiling is a multiple of that plus a margin: it never
    fires first on a healthy run, and it is the only thing that ends a child hung for a reason
    that is not ffmpeg (a stuck import, a wedged pipe). None when the per-call limit is 0."""
    limit = STATE.timeout if per_call is None else per_call
    return (limit * 4 + 60) if limit else None


def run_tool(argv: Sequence[str], *, per_call: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run a sibling script (`argv[0]` is the script path) under child_limit(). On overrun the
    child is killed and a CompletedProcess is returned whose stdout is this skill's own failure
    document (kind timeout, exit 124), so callers that parse the child's --json see a timeout
    exactly as they would from the child itself."""
    limit = child_limit(per_call)
    child = subprocess.Popen([sys.executable] + list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _watch(child, [])  # a sibling script removes its own partial output; there is none of ours to clean
    try:
        out, err = child.communicate(timeout=limit)
        _unwatch(child)
        return subprocess.CompletedProcess(child.args, child.returncode, out, err)
    except subprocess.TimeoutExpired as e:
        child.kill()
        child.communicate()
        _unwatch(child)
        name = os.path.basename(str(argv[0]))
        msg = f"{name} did not finish within {limit:.0f} s (4x the per-ffmpeg --timeout plus 60 s) and was killed"
        doc = {"status": "failed", "exit_code": 124,
               "error": {"kind": "timeout", "message": msg, "code": ERROR_CODE["timeout"], "retryable": ERROR_RETRYABLE},
               "commands": []}
        partial = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return subprocess.CompletedProcess(list(argv), 124, json.dumps(doc), partial + f"\nerror: {msg}\n")


def decode_pcm_mono(path: str, sample_rate: int, seconds: Optional[float] = None, start: float = 0.0,
                    *, check: bool = True) -> List[float]:
    """Decode (part of) a file's audio to mono float samples in [-1, 1) at `sample_rate` via a
    single ffmpeg pass under --timeout. Shared by scenes.py (audio envelope for cut scoring) and
    sync.py (cross-correlation); an undecodable input is kind ffmpeg when check=True, else []."""
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    proc = run_analysis(cmd, check=False, text=False)
    if proc.returncode != 0 or not proc.stdout:
        if check:
            die(f"could not decode audio from {path}:\n{proc.stderr.decode(errors='replace').strip()}", kind="ffmpeg")
        return []
    n = len(proc.stdout) // 2
    import struct
    return [v / 32768.0 for v in struct.unpack(f"<{n}h", proc.stdout[: n * 2])]


def rms_envelope(samples: Sequence[float], step: int, *, full_blocks_only: bool = False, remove_mean: bool = False) -> List[float]:
    """RMS per block of `step` samples. full_blocks_only drops a short tail block (sync.py: every
    block must be the same length for the correlation); remove_mean subtracts the envelope's mean
    (sync.py: so silence does not correlate). scenes.py keeps the tail and the absolute level."""
    import math
    step = max(1, int(step))
    n = len(samples)
    stop = n - step + 1 if full_blocks_only else n
    env: List[float] = []
    for i in range(0, max(0, stop), step):
        block = samples[i:i + step]
        env.append(math.sqrt(sum(x * x for x in block) / len(block)))
    if remove_mean and env:
        mean = sum(env) / len(env)
        env = [e - mean for e in env]
    return env


def child_args() -> List[str]:
    """The shared flags a tool that runs sibling scripts (render.py, batch.py) forwards to them,
    so one `--timeout`/`--overwrite`/`--fast`/`--dry-run` on the outer command governs every
    stage. Before 1.4.3 only --fast and --dry-run were forwarded; a --timeout given to render.py
    stopped at render.py."""
    args: List[str] = []
    if STATE.fast:
        args.append("--fast")
    if STATE.dry_run:
        args.append("--dry-run")
    if STATE.overwrite:
        args.append("--overwrite")
    args += ["--timeout", f"{STATE.timeout:g}"]
    return args


def run_keeping_subtitles(cmd: List[str], output: str) -> bool:
    """Run an ffmpeg command that already maps its video/audio, trying first to also
    stream-copy any subtitle/data streams the source has (`-map 0:s?`/`0:d?` are no-ops when
    there are none). A source whose subtitle codec cannot be copied into the target container
    (e.g. a container change) makes that first attempt fail; retry the same command without the
    extra maps rather than let a tool that never touched subtitles start hard-failing because of
    them. `cmd` is the full argv *without* the output path. Returns True only when the
    retry-without-subtitles path was actually needed (i.e. subtitle/data streams were dropped)."""
    if run(cmd + ["-map", "0:s?", "-map", "0:d?", "-c:s", "copy", "-c:d", "copy", output], check=False).returncode == 0:
        return False
    run(cmd + [output])
    return True


def _limit_for(cmd: Sequence[str]) -> Optional[float]:
    """The wall-clock ceiling for this command: ffprobe (and other read-only probes) get a fixed
    short one, ffmpeg the configured one; None means unlimited."""
    if not _is_ffmpeg(cmd):
        return PROBE_TIMEOUT if STATE.timeout else None
    return STATE.timeout or None


def _run_captured(cmd: List[str], check: bool) -> subprocess.CompletedProcess:
    """Plain run with stdout/stderr captured."""
    limit = _limit_for(cmd)
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _watch(child, cmd)
    try:
        out, err = child.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        _unwatch(child)
        _timed_out(cmd, limit or 0)
    finally:
        _unwatch(child)
    proc = subprocess.CompletedProcess(list(cmd), child.returncode, out, err)
    if proc.returncode == 0 and _is_ffmpeg(cmd):
        _remember_output(cmd)
    if proc.returncode != 0:
        # Cleanup happens for every failed ffmpeg invocation, not just the check=True/_fail()
        # path: a handful of scripts (cut.py, loudness.py, silence.py, sync.py) call run() with
        # check=False so they can compose their own die() message from proc.stderr, but the
        # partial-output risk is identical either way -- and for a script that retries into the
        # same output path after a check=False failure (e.g. color.py's --retag copy-then-
        # reencode fallback), removing the stale partial first is strictly safer than leaving it
        # for -y to overwrite.
        _cleanup_partial_output(cmd)
        if check:
            _fail(cmd, proc.returncode, proc.stderr)
    return proc


def _progress_line(done: float, total: float, elapsed: float) -> str:
    if total > 0:
        pct = min(99.9, done / total * 100)
        eta = (elapsed / pct * (100 - pct)) if pct > 0.5 else 0
        return f"\r  {pct:5.1f}%  {done:7.1f}s / {total:.1f}s  ETA {eta:4.0f}s"
    return f"\r  {done:7.1f}s encoded"


def _run_with_progress(cmd: List[str], check: bool) -> subprocess.CompletedProcess:
    """Run ffmpeg with -progress on a pipe and print percent/ETA to stderr.

    The time limit is checked on a clock, not per progress line: a deadlocked ffmpeg (the very
    case --timeout exists for) prints nothing, so a loop that only looked at the deadline when a
    line arrived waited on it forever. Reader threads drain both pipes; the main loop wakes at
    least twice a second to compare the clock against the limit."""
    import queue
    import threading
    import time
    total = STATE.duration_hint or 0.0
    full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    t0 = time.time()
    limit = _limit_for(cmd)
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _watch(proc, cmd)
    assert proc.stdout is not None and proc.stderr is not None
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    err_chunks: List[str] = []

    def pump_out() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            lines.put(line)
        lines.put(None)

    def pump_err() -> None:
        err_chunks.append(proc.stderr.read())  # type: ignore[union-attr]

    threading.Thread(target=pump_out, daemon=True).start()
    err_thread = threading.Thread(target=pump_err, daemon=True)
    err_thread.start()
    last = ""

    def clear_line() -> None:
        if last:
            sys.stderr.write("\r" + " " * len(last) + "\r")

    def timed_out() -> None:
        proc.kill()
        proc.wait()
        clear_line()
        _timed_out(cmd, limit or 0)

    while True:
        remaining = (limit - (time.time() - t0)) if limit else None
        if remaining is not None and remaining <= 0:
            timed_out()
        try:
            line = lines.get(timeout=min(0.5, remaining) if remaining is not None else 0.5)
        except queue.Empty:
            continue
        if line is None:
            break
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                done = int(line.split("=")[1]) / 1_000_000
            except ValueError:
                continue
            msg = _progress_line(done, total, time.time() - t0)
            if msg != last:
                sys.stderr.write(msg)
                sys.stderr.flush()
                last = msg
    try:
        proc.wait(timeout=(max(5.0, limit - (time.time() - t0)) if limit else None))
    except subprocess.TimeoutExpired:
        timed_out()
    _unwatch(proc)
    err_thread.join()
    err = "".join(err_chunks)
    clear_line()
    if proc.returncode == 0:
        _remember_output(cmd)
    if proc.returncode != 0:
        _cleanup_partial_output(cmd)
        if check:
            _fail(cmd, proc.returncode, err)
    return subprocess.CompletedProcess(full, proc.returncode, "", err)


def shell_quote(s: str) -> str:
    if not s or any(ch in s for ch in " \t\n\r\\\"';|&<>()[]{}$*?"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def ffmpeg_base(overwrite: bool = True) -> List[str]:
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    cmd.append("-y" if overwrite else "-n")
    return cmd


MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts", ".mts", ".m2ts", ".mxf", ".3gp", ".wmv", ".gif",
             ".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".aif", ".aiff", ".caf", ".wma", ".png", ".jpg", ".jpeg", ".webp"}


def _output_failed(path: str, why: str) -> "None":
    """An ffmpeg run reported success but the artifact is not usable: say so, and do not leave a
    0-byte file behind that a later step could mistake for a result."""
    try:
        if os.path.exists(path) and os.path.getsize(path) == 0:
            os.remove(path)
            why += " (empty file removed)"
    except OSError:
        pass
    die(f"output verification failed: {path}: {why}", kind="output")


def verify_output(path: str) -> Dict[str, Any]:
    """The success criterion for every writing tool: the file exists, is not empty and ffprobe
    can read at least one stream from it. Non-media artifacts (srt, edl, html, md) only need to
    exist and be non-empty. Returns the probe (empty dict for non-media)."""
    if not os.path.exists(path):
        _output_failed(path, "not written")
    if os.path.getsize(path) == 0:
        _output_failed(path, "0 bytes")
    if os.path.splitext(path)[1].lower() not in MEDIA_EXT:
        return {}
    meta = probe(path, role="output")
    if not meta.get("video") and not meta.get("audio"):
        _output_failed(path, "no video or audio stream")
    return meta


def probe(path: str, role: str = "input") -> Dict[str, Any]:
    """Return a compact, script-friendly description of a media file.

    role="output" marks a file this tool just wrote: a read failure is then reported as an
    output-verification failure (kind "output") instead of an input problem."""
    if not os.path.exists(path):
        if role == "output" and not STATE.dry_run:
            _output_failed(path, "not written")
        if STATE.dry_run:
            # width/height/fps are honestly 0/0/0.0 -- "not measured", matching duration/size_bytes
            # below -- because this is a dry run: the file doesn't exist yet, so there is nothing to
            # probe. Earlier this stub used plausible-looking placeholders (1920x1080x30.0) instead,
            # which some tools' dry-run summary line echoed verbatim as if it were a real computed
            # preview (#77). That was reverted once, because a couple of call sites divided by these
            # values for aspect-ratio math and crashed on a real 0 (join.py, fit.py); those call
            # sites are now guarded to treat 0 as "unknown" and fall back sanely instead of dividing
            # by it, so the stub can finally report the honest, unknown value.
            return {"file": path, "dry_run": True, "format": None, "duration": 0.0, "size_bytes": 0, "bitrate": None,
                    "video": {"codec": None, "width": 0, "height": 0, "fps": 0.0, "pix_fmt": None, "hdr": False,
                              "color_transfer": None, "color_primaries": None, "rotation": 0, "variable_frame_rate_suspected": False},
                    "audio": {"codec": None, "channels": 0, "sample_rate": 0}, "subtitle_streams": 0, "data_streams": 0}
        die(f"input not found: {path}")
    ffprobe = require_tool("ffprobe")
    proc = run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
        quiet=True,
        check=False,
    )
    if proc.returncode != 0:
        if role == "output":
            _output_failed(path, f"ffprobe cannot read it:\n{proc.stderr.strip()}")
        die(f"ffprobe failed on {path}:\n{proc.stderr.strip()}")
    try:
        raw = json.loads(proc.stdout or "{}")
    except ValueError as e:
        if role == "output":
            _output_failed(path, f"ffprobe printed unreadable JSON: {e}")
        die(f"ffprobe printed unreadable JSON for {path}: {e}", kind="ffmpeg")
    fmt = raw.get("format", {})
    streams = raw.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    data_stream_count = sum(1 for s in streams if s.get("codec_type") in ("data", "attachment"))

    duration = _to_float(fmt.get("duration"))
    if duration is None and video:
        duration = _to_float(video.get("duration"))
    if duration is None and audio:
        duration = _to_float(audio.get("duration"))
    if duration and STATE.duration_hint is None:
        STATE.duration_hint = duration

    out: Dict[str, Any] = {
        "file": path,
        "format": fmt.get("format_name"),
        "duration": duration,
        "size_bytes": _to_int(fmt.get("size")),
        "bitrate": _to_int(fmt.get("bit_rate")),
        "video": None,
        "audio": None,
        "subtitle_streams": len(subs),
        "data_streams": data_stream_count,
        # container-level chapter markers and the common tags, so metadata.py's result is
        # verifiable the same way every other tool's is (additive keys, 1.x-safe)
        "chapters": [{
            "index": n,
            "start": _to_float(ch.get("start_time")),
            "end": _to_float(ch.get("end_time")),
            "title": (ch.get("tags") or {}).get("title"),
        } for n, ch in enumerate(raw.get("chapters") or [])],
        "tags": {k.lower(): v for k, v in (fmt.get("tags") or {}).items() if k.lower() in ("title", "artist", "album", "comment", "date", "genre")},
        # every subtitle stream in file order: index n here is `-map 0:s:n`
        "subtitle_stream_details": [{
            "index": n,
            "codec": s.get("codec_name"),
            "language": (s.get("tags") or {}).get("language"),
            "title": (s.get("tags") or {}).get("title"),
        } for n, s in enumerate(subs)],
    }
    if video:
        r_rate = _fraction(video.get("r_frame_rate"))
        avg_rate = _fraction(video.get("avg_frame_rate"))
        fps = float(avg_rate) if avg_rate else (float(r_rate) if r_rate else None)
        vfr = bool(r_rate and avg_rate and abs(float(r_rate) - float(avg_rate)) > 0.01)
        w, h = _to_int(video.get("width")), _to_int(video.get("height"))
        rotation = 0
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(round(float(sd["rotation"])))
        if "rotate" in (video.get("tags") or {}):
            try:
                rotation = int(video["tags"]["rotate"])
            except ValueError:
                pass
        pix = video.get("pix_fmt") or ""
        trc = video.get("color_transfer") or ""
        prim = video.get("color_primaries") or ""
        hdr = trc in ("smpte2084", "arib-std-b67") or prim == "bt2020"
        dovi = None
        for sd in video.get("side_data_list", []) or []:
            if "dv_profile" in sd or "DOVI" in str(sd.get("side_data_type", "")):
                dovi = {"profile": sd.get("dv_profile"), "level": sd.get("dv_level"), "bl_compatibility_id": sd.get("dv_bl_signal_compatibility_id")}
        if dovi:  # a Dolby Vision stream is HDR even when its base layer tags are missing
            hdr = True
        out["video"] = {
            "codec": video.get("codec_name"),
            "profile": video.get("profile"),
            "width": w,
            "height": h,
            "display_aspect": video.get("display_aspect_ratio") or _aspect_string(w, h),
            "fps": round(fps, 3) if fps else None,
            "r_frame_rate": video.get("r_frame_rate"),
            "avg_frame_rate": video.get("avg_frame_rate"),
            "variable_frame_rate_suspected": vfr,
            "pix_fmt": video.get("pix_fmt"),
            "bit_depth": _bit_depth(pix),
            "hdr": hdr,
            "hdr_format": (("Dolby Vision %s" % (("profile %s" % dovi["profile"]) if dovi and dovi.get("profile") is not None else "")).strip() if dovi else
                           "HDR10/PQ" if trc == "smpte2084" else "HLG" if trc == "arib-std-b67" else "BT.2020 SDR" if hdr else None),
            "dolby_vision": dovi,
            "color_space": video.get("color_space"),
            "color_primaries": video.get("color_primaries"),
            "color_transfer": video.get("color_transfer"),
            "color_range": video.get("color_range"),
            "rotation": rotation,
            "nb_frames": _to_int(video.get("nb_frames")),
            "bitrate": _to_int(video.get("bit_rate")),
        }
    if audio:
        out["audio"] = {
            "codec": audio.get("codec_name"),
            "channels": _to_int(audio.get("channels")),
            "channel_layout": audio.get("channel_layout"),
            "sample_rate": _to_int(audio.get("sample_rate")),
            "bitrate": _to_int(audio.get("bit_rate")),
        }
        # every audio stream in file order: index n here is `-map 0:a:n` (audio.py --audio-stream n)
        out["audio_streams"] = [{
            "index": n,
            "codec": a.get("codec_name"),
            "channels": _to_int(a.get("channels")),
            "channel_layout": a.get("channel_layout"),
            "sample_rate": _to_int(a.get("sample_rate")),
            "language": (a.get("tags") or {}).get("language"),
            "title": (a.get("tags") or {}).get("title"),
        } for n, a in enumerate(s for s in streams if s.get("codec_type") == "audio")]
    return out


def default_output(input_path: str, suffix: str, ext: Optional[str] = None) -> str:
    p = Path(input_path)
    new_ext = ext if ext else p.suffix.lstrip(".") or "mp4"
    return str(p.with_name(f"{p.stem}_{suffix}.{new_ext}"))


class MissingFpsError(ValueError):
    """parse_time() saw an hh:mm:ss:ff SMPTE timecode but no fps was given to convert it -- distinct
    from a plain ValueError so a caller that falls back to treating unparseable text as a literal
    line (e.g. caption.py's free-text cue format) can still fail loudly on this one, instead of
    silently swallowing a mistyped/missing --fps as an auto-timed line of digits."""


def concat_list_line(path: str) -> str:
    """One `file '...'` line for the concat demuxer. The demuxer reads backslash as an escape
    inside the quoted form, so a Windows path (C:\\Users\\...\\part000.mp4) must be written
    with forward slashes -- ffmpeg opens either spelling on Windows -- and a single quote in the
    name is closed, escaped and reopened. Shared by cut.py (multi-segment) and sequence.py."""
    escaped = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"


def _bit_depth(pix_fmt: Optional[str]) -> int:
    """Bits per component from a pixel format name. `"10" in pix` used to read yuv410p (4:1:0
    chroma) as 10-bit; the depth is the number that ends the name (before an le/be suffix):
    yuv420p10le -> 10, gbrp12be -> 12, gray16le -> 16, yuv410p / yuv420p / rgb24 -> 8."""
    m = re.search(r"(\d{1,2})(?:le|be)?$", pix_fmt or "")
    if not m:
        return 8
    n = int(m.group(1))
    if n in (24, 32):      # packed 8-bit rgb24/bgr32/rgb0 etc.
        return 8
    if n in (48, 64):      # packed 16-bit rgb48/rgba64
        return 16
    return n if 8 <= n <= 16 else 8


def fmt_secs(value: Optional[float]) -> str:
    """`12.345s`, or `?s` when the probe had no duration (MPEG-TS without a duration tag, a
    stream whose container and streams all omit it). Every writing tool prints the duration
    of what it wrote; formatting None with :.3f used to raise TypeError after a successful
    encode, in 25+ scripts."""
    return "?s" if value is None else f"{value:.3f}s"


def place_output(src: str, dst: str) -> None:
    """Deliver an already-rendered file to `dst` under the same rules as an ffmpeg output:
    the path is checked, an existing file is only replaced through a sibling temp so a
    failed copy never costs the caller what was there, and the result is remembered as ours.
    render.py's final `copyfile()` used to bypass all three."""
    import shutil
    cmd = ["ffmpeg", dst]
    _check_output_path(cmd)
    _check_existing_output(cmd)
    d, base = os.path.split(dst)
    stem, ext = os.path.splitext(base)
    tmp = os.path.join(d, f".{stem}.ffskill-{os.getpid()}{ext}")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        die(f"could not place {dst}: {e}", kind="output")
    _remember_output(cmd)


def parse_time(value: str, fps: Optional[float] = None) -> float:
    """Accept seconds ('12.5'), mm:ss ('1:30'), hh:mm:ss(.ms) ('00:01:30.250'), SRT '00:01:30,250',
    or -- when `fps` is given -- SMPTE non-drop-frame timecode 'hh:mm:ss:ff' ('00:01:30:15')."""
    v = value.strip().replace(",", ".")
    if not v:
        raise ValueError("empty time")
    parts = v.split(":")
    if len(parts) == 4:
        if fps is None or fps <= 0:
            raise MissingFpsError(f"'{value}' looks like an hh:mm:ss:ff SMPTE timecode, but no fps was given to convert its frame count to seconds")
        h, m, s, f = parts
        if "." in f:
            raise ValueError(f"bad SMPTE timecode: {value}")
        frame, whole_fps = int(f), int(round(fps))
        if not (0 <= frame < whole_fps):
            raise ValueError(f"bad SMPTE timecode '{value}': frame {frame} is out of range for {fps:g} fps (0-{whole_fps - 1})")
        # Non-drop-frame: the timecode counts whole_fps frames per timecode-second, so the real
        # time is the total frame count over the true rate (at 29.97 an hour of timecode is
        # 3596.4 s of video). This is exactly what fmt_smpte_time() inverts; before, the two
        # disagreed by ~0.1 % on the fractional NTSC rates and drifted apart over long files.
        total_frames = (int(h) * 3600 + int(m) * 60 + int(s)) * whole_fps + frame
        return total_frames / fps
    if len(parts) > 3:
        raise ValueError(f"bad time: {value}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def time_arg(value: str, flag: str, fps: Optional[float] = None) -> float:
    """parse_time() for a command-line flag: SMPTE hh:mm:ss:ff resolves with the input's fps when
    the caller has one, and every parse failure is a `kind: input` refusal naming the flag (so
    `--json` callers get a failure document, never a traceback)."""
    try:
        return parse_time(value, fps)
    except MissingFpsError as e:
        die(f"{flag} {value!r}: {e}")
    except ValueError as e:
        die(f"{flag} {value!r}: {e} (use seconds, mm:ss, hh:mm:ss.ms or, with a known fps, hh:mm:ss:ff)")
    return 0.0  # unreachable


def fmt_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_smpte_time(seconds: float, fps: float) -> str:
    """SMPTE non-drop-frame timecode 'hh:mm:ss:ff' for a real fps (not the fractional NTSC rates
    -- 29.97/59.94 need drop-frame counting to stay wall-clock accurate, which this does not do)."""
    if seconds < 0:
        seconds = 0.0
    whole_fps = int(round(fps))
    total_frames = int(round(seconds * fps))
    frame = total_frames % whole_fps
    secs_total = total_frames // whole_fps
    h, rem = divmod(secs_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{frame:02d}"


def escape_filter_path(path: str) -> str:
    """Escape a file path for use as a filter option value (subtitles=, ass=, lut3d=file=, fontfile=, fontsdir=).

    A filter option value is parsed twice: the graph parser splits filters on `,` / `;` and options
    on `:`, then the filter's own option parser splits key=value pairs on `:` again. A character that
    must survive both passes needs two levels of escaping, so a Windows drive letter `D:/x.srt` is
    written `D\\\\:/x.srt`; with a single backslash the second pass still splits at the colon and
    ffmpeg reads `/x.srt` as the next option (`Unable to parse "original_size" option value`).
    Backslashes are turned into forward slashes first (ffmpeg accepts them on Windows), so a backslash
    never has to be escaped itself; `,`, `;`, `[` and `]` are graph-level characters and survive with
    one backslash. `'` is special: the graph parser also treats a quote as the start of a quoted
    token, so a single `\\'` is consumed by the first pass and "Ryo's Mac/cues.srt" reaches the
    filter as "Ryos Mac/cues.srt" (Unable to open ...). Three backslashes survive both passes
    (measured on 6.1 and 7.1 with subtitles=, ass= and lut3d=file=).
    """
    p = str(Path(path))
    p = p.replace("\\", "/")
    p = p.replace(":", "\\\\:")
    p = p.replace("'", "\\\\\\'")
    for ch in (",", ";", "[", "]"):
        p = p.replace(ch, "\\" + ch)
    return p


def default_font_file(font_name: str) -> Optional[str]:
    """Resolve `font_name` to a concrete on-disk font file, so a caller can tell drawtext
    `fontfile=<path>` instead of `font=<name>`, when possible.

    On some real Windows ffmpeg builds (winget's gyan.dev 9.x), drawtext's own fontconfig
    resolution crashes with an access violation whenever it has to resolve a font by family name
    -- with or without a valid fonts.conf on FONTCONFIG_FILE. `fontfile=` is the only form
    confirmed not to crash (#100), since it never touches fontconfig at all. `font_name` itself is
    ignored on Windows for that reason: a fixed, near-universally-present system font is used
    instead of trying to resolve the requested family (which would crash the same way).

    On Linux/macOS this is best-effort and uses the real requested family: `fc-match` reports the
    same file fontconfig would resolve `font_name` to anyway, so a caller gets the identical font,
    just already resolved to a path -- fontfile= skips a redundant fontconfig lookup and equally
    sidesteps the same class of crash if it exists on some build there too, but the fallback below
    (returning None) is exercised routinely there, not just on failure.

    Returns None when nothing could be resolved (fc-match missing/unavailable, or no well-known
    Windows font file present); the caller falls back to font=<font_name>, the prior behaviour.
    """
    if platform.system() == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        fonts = Path(windir) / "Fonts"
        # The requested family first: a file whose name starts with the family name with spaces
        # removed (Noto Sans CJK JP -> NotoSansCJKjp-Regular.otf, Meiryo -> meiryo.ttc), then the
        # common CJK system fonts when the request looks CJK (so Japanese text does not render as
        # boxes in Arial), and Arial only as the last resort.
        wanted = re.sub(r"[^a-z0-9]", "", (font_name or "").lower())
        try:
            files = sorted(fonts.iterdir()) if fonts.is_dir() else []
        except OSError:
            files = []
        if wanted:
            for f in files:
                stem = re.sub(r"[^a-z0-9]", "", f.stem.lower())
                if f.suffix.lower() in (".ttf", ".otf", ".ttc") and stem.startswith(wanted):
                    return str(f)
        if any(k in wanted for k in ("cjk", "gothic", "mincho", "meiryo", "yugoth", "msgothic", "malgun", "simhei", "simsun", "jp", "kr", "sc", "tc")):
            for name in ("NotoSansCJKjp-Regular.otf", "NotoSansCJK-Regular.ttc", "meiryo.ttc", "YuGothM.ttc", "msgothic.ttc", "malgun.ttf", "msyh.ttc"):
                if (fonts / name).exists():
                    return str(fonts / name)
        candidate = fonts / "arial.ttf"
        return str(candidate) if candidate.exists() else None
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "--format=%{file}\n", font_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    path = proc.stdout.splitlines()[0].strip() if proc.stdout.strip() else ""
    return path if path and os.path.exists(path) else None


def escape_drawtext(text: str) -> str:
    """Escape `text` for use as a single-quoted drawtext option value (`text='<this>'`).

    Every ffmpeg filter-graph special character (`\\ : % , [ ] ;`) needs a backslash
    escape regardless of the surrounding quotes -- the graph parser still splits on an
    unescaped `,`/`;` or ends an option list on an unescaped `:`/`[`/`]` even while
    "inside" a quoted value. The quote character itself has no reliable backslash
    escape at all: `\\'` and the POSIX shell `'\\''` close-insert-reopen trick both
    parse fine in a simple `-vf` chain, but silently corrupt a `-filter_complex` chain
    that uses explicit `[label]` pads -- confirmed by rendering the result: the text
    value doesn't end where the quote closes it, and trailing option names/values
    (fontfile=..., fontsize=...) leak into the rendered picture as literal text
    instead of being parsed as options. A quote is therefore dropped outright rather
    than escaped -- losing one apostrophe from a label is a fine trade for "the
    filter graph parses the way the code intends, on every call shape this codebase
    uses it in".

    `%` has the same problem the quote character did: `\%` is not a real escape as
    far as drawtext's own text-expansion scanner (on by default, `expansion=normal`,
    for `%{pts}`/`%{localtime}`/etc.) is concerned -- a bare backslash-escaped `%`
    always logs "Stray % near ..." (confirmed with the minimal case
    `text='100\%done'`), which is merely noisy on one ffmpeg
    build (the warning is printed, the file still gets written) but a hard filtering
    failure that writes no output at all on another. Every caller of this function
    only ever wants a literal label, never `%{...}` expansion, so `%` is dropped
    outright rather than chasing a per-build-safe escape (`expansion=none` on the
    filter would also fix it, but needs touching every drawtext= call site instead
    of the one shared helper). Control characters (newline, tab, ...) are dropped
    for the same reason: none are meaningful in a one-line burnt-in label, and
    unlike the graph-special characters above, ffmpeg's own text-expansion scanner
    -- not just the graph parser -- is involved in whether they're actually safe."""
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return (
        text.replace("'", "")
        .replace("%", "")
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def cfr_args(meta: Optional[Dict[str, Any]], fps: Optional[float] = None) -> List[str]:
    """Force a constant frame rate on output when the source looks VFR (or fps is given).

    VFR sources (phone/screen recordings) drift against audio after cuts and joins,
    so every re-encoding script passes this to conform them automatically.
    """
    v = (meta or {}).get("video") or {}
    if fps is None and not v.get("variable_frame_rate_suspected"):
        return []
    rate = fps or v.get("fps") or 30.0
    rate = round(rate) if abs(rate - round(rate)) < 0.02 else rate
    return ["-fps_mode", "cfr", "-r", f"{rate:g}"]


def bt709_tag_args(encoder: str = "libx264") -> List[str]:
    """Tag an SDR output as BT.709 without touching its pixels.

    Up to FFmpeg 7.0 the output options -colorspace/-color_primaries/-color_trc were tags only.
    7.1 added colourspace negotiation to libavfilter and feeds those options into the graph's
    output constraints, so on a source whose bitstream carries no colour tags (test sources,
    screen recordings, many cameras) the CLI now auto-inserts a *real* matrix conversion (its
    guess for "unknown" is bt601) into every SDR re-encode: a --lut-strength 0 no-op grade
    came back ~24 dB PSNR from its source on 7.1. From 7.1 on, the tags therefore go through
    the encoder's own VUI parameters instead, which libavfilter never sees; a source that is
    genuinely tagged bt601/bt2020 is left alone either way (it keeps its own tags on the old
    path, and the encoder VUI is a label, not a conversion, on the new one).
    """
    if ffmpeg_version() < (7, 1):
        return ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    if encoder == "libx265":
        return ["-x265-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]
    return ["-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]


def x264_args(crf: int = 18, preset: str = "medium", keep_bt709: bool = True) -> List[str]:
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if keep_bt709:
        args += bt709_tag_args("libx264")
    return args


def video_args(meta: Optional[Dict[str, Any]], crf: int = 18, preset: str = "medium") -> List[str]:
    """Encoder args that preserve what the source is.

    SDR sources -> H.264 8-bit tagged BT.709 (x264_args). HDR sources (HDR10/PQ, HLG,
    Dolby Vision base layer, BT.2020) -> HEVC Main10 with the source's own colour tags,
    so cutting/captioning/fitting an iPhone HDR clip stays HDR instead of becoming a
    washed-out file mislabelled as BT.709. Use color.py --to-sdr when SDR is wanted.
    """
    v = (meta or {}).get("video") or {}
    if not v.get("hdr"):
        return x264_args(crf, preset)
    cs = v.get("color_space") or "bt2020nc"
    prim = v.get("color_primaries") or "bt2020"
    trc = v.get("color_transfer") or "arib-std-b67"
    x265 = f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}:range=limited:hdr10-opt=1" if trc == "smpte2084" else f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}"
    return ["-c:v", "libx265", "-preset", preset, "-crf", str(crf + 2), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
            "-x265-params", x265, "-colorspace", cs, "-color_primaries", prim, "-color_trc", trc, "-movflags", "+faststart"]


def aac_args(bitrate: str = "192k") -> List[str]:
    return ["-c:a", "aac", "-b:a", bitrate]


AUDIO_CODECS = {
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
    ".m4a": ["-c:a", "aac", "-b:a", "256k"],
    ".aac": ["-c:a", "aac", "-b:a", "256k"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


def audio_codec_for(output_path: str, default_bitrate: str = "192k") -> List[str]:
    """Pick an audio codec that the output container can actually hold."""
    ext = os.path.splitext(output_path)[1].lower()
    return list(AUDIO_CODECS.get(ext, ["-c:a", "aac", "-b:a", default_bitrate]))


def is_audio_output(output_path: str) -> bool:
    """True when the output extension is an audio-only container (.wav, .flac, .mp3, .m4a, .aac, .ogg, .opus).

    Such a file cannot hold a video stream and, for .wav, cannot hold compressed audio: scripts use
    this to drop the picture (-vn) and to pick the codec from the extension instead of AAC.
    """
    return os.path.splitext(output_path)[1].lower() in AUDIO_CODECS


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


def read_text_or_die(path: str, flag: str) -> str:
    """Read a caller-supplied UTF-8 text file (a cue list, chapters, notes) or fail as kind input
    with the flag named, instead of a FileNotFoundError / UnicodeDecodeError traceback."""
    if os.path.isdir(path):
        # checked first: Windows raises PermissionError, not IsADirectoryError, for a directory
        die(f"{flag}: {path} is a directory, not a text file")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        die(f"{flag}: {path} does not exist")
    except IsADirectoryError:
        die(f"{flag}: {path} is a directory, not a text file")
    except UnicodeDecodeError as e:
        die(f"{flag}: {path} is not UTF-8 text ({e.reason} at byte {e.start}); save it as UTF-8")
    except OSError as e:
        die(f"{flag}: cannot read {path}: {e.strerror}")
    return ""  # unreachable


def keyframes_near(path: str, t: float, window: float = 5.0) -> List[float]:
    """Video keyframe timestamps within +-window seconds of t, ascending. Read with
    -read_intervals so a long file is not scanned end to end; empty when ffprobe cannot say."""
    ffprobe = require_tool("ffprobe")
    lo = max(0.0, t - window)
    proc = run([ffprobe, "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                "-read_intervals", f"{lo:.3f}%{t + window:.3f}", "-show_entries", "frame=pts_time",
                "-of", "csv=p=0", path], quiet=True, check=False)
    if proc.returncode != 0:
        return []
    out: List[float] = []
    for line in proc.stdout.splitlines():
        try:
            out.append(round(float(line.strip().rstrip(",")), 3))
        except ValueError:
            continue
    return sorted(set(out))


def measured_level_dbfs(path: str, seconds: float = 120.0) -> Optional[Dict[str, float]]:
    """Mean and peak level of the first `seconds` of audio (volumedetect), in dBFS; None if unmeasurable.
    Cheap enough to run once as a hint when a threshold-based tool found nothing."""
    ffmpeg = require_tool("ffmpeg")
    proc = run_analysis([ffmpeg, "-hide_banner", "-nostdin", "-t", f"{seconds:.0f}", "-i", path, "-vn",
                         "-af", "volumedetect", "-f", "null", "-"], check=False)
    m_mean = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", proc.stderr)
    m_max = re.search(r"max_volume:\s*(-?[0-9.]+) dB", proc.stderr)
    if not (m_mean and m_max):
        return None
    return {"mean_dbfs": float(m_mean.group(1)), "peak_dbfs": float(m_max.group(1))}


def analyze_levels(path: str, seconds: float = 20.0) -> Dict[str, Any]:
    """Sample luma/saturation statistics (signalstats) and guess whether the picture is Log-encoded.

    Log gammas (S-Log3, V-Log, C-Log, HLG-looking flat profiles) put black around 90-95/255 and
    white below ~235 with low saturation: the image looks grey and flat but is tagged as plain SDR.
    """
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-t", f"{seconds:.1f}", "-i", path, "-an",
           "-vf", "fps=2,signalstats,metadata=print:file=-", "-f", "null", "-"]
    proc = run_analysis(cmd, check=False)
    vals: Dict[str, List[float]] = {}
    for line in proc.stdout.splitlines():
        if "lavfi.signalstats." in line and "=" in line:
            key, val = line.split("lavfi.signalstats.", 1)[1].split("=", 1)
            try:
                vals.setdefault(key, []).append(float(val))
            except ValueError:
                pass
    if not vals.get("YAVG"):
        return {"error": "no frames analysed"}
    def mean(k: str) -> float:
        v = vals.get(k) or [0.0]
        return sum(v) / len(v)
    ymin, ymax, yavg, sat = min(vals.get("YMIN") or [0]), max(vals.get("YMAX") or [255]), mean("YAVG"), mean("SATAVG")
    # signalstats reports in the source bit depth; normalise everything to an 8-bit scale
    scale = 1.0
    if ymax > 255 or yavg > 255:
        scale = 1 / 4.0 if ymax <= 1023 else (1 / 16.0 if ymax <= 4095 else 1 / 256.0)  # 10 / 12 / 16-bit
    ymin, ymax, yavg, sat = ymin * scale, ymax * scale, yavg * scale, sat * scale
    # 5th/95th percentile of per-frame lows/highs is more robust than the absolute min/max
    lows = sorted(x * scale for x in (vals.get("YLOW") or vals.get("YMIN") or [0]))
    highs = sorted(x * scale for x in (vals.get("YHIGH") or vals.get("YMAX") or [255]))
    p_low = lows[len(lows) // 20]
    p_high = highs[-1 - len(highs) // 20]
    looks_log = p_low >= 64 and p_high <= 235 and sat < 40
    return {
        "scale": "8-bit equivalent",
        "y_min": round(ymin, 1), "y_max": round(ymax, 1), "y_avg": round(yavg, 1), "y_low_p5": round(p_low, 1), "y_high_p95": round(p_high, 1),
        "saturation_avg": round(sat, 1),
        "looks_like_log": looks_log,
        "note": ("flat, low-contrast, desaturated picture tagged as SDR: probably a Log profile (S-Log/V-Log/C-Log). "
                 "Apply the camera's conversion LUT with color.py --lut" if looks_log else "contrast and saturation look like normal display-referred SDR"),
    }


BRAND_DEFAULTS: Dict[str, Any] = {
    "font": "DejaVu Sans",
    "font_file": None,
    "colors": {"primary": "FFD200", "text": "FFFFFF", "outline": "000000", "background": "101418", "accent": "1E6F8E"},
    "logo": None,
    "logo_position": "top-right",
    "logo_scale": 160,
    "logo_opacity": 0.9,
    "safe_margin": 48,
    "caption": {"size": 26, "position": "bottom", "animate": "pop", "karaoke": False, "bold": True, "outline": 2},
    "loudness": {"lufs": -14, "tp": -1},
}


def load_brand(path: Optional[str]) -> Dict[str, Any]:
    """Load brand.json (fonts, colours, logo, safe margins, caption defaults); missing keys fall back to defaults."""
    import copy
    brand = copy.deepcopy(BRAND_DEFAULTS)
    if not path:
        return brand
    if not os.path.exists(path):
        die(f"brand file not found: {path}")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        die(f"brand file is not valid JSON: {exc}")
    base = Path(path).resolve().parent
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(brand.get(k), dict):
            brand[k].update(v)
        else:
            brand[k] = v
    for key in ("logo", "font_file"):
        if brand.get(key) and not os.path.isabs(brand[key]):
            brand[key] = str(base / brand[key])
    brand["_path"] = str(path)
    return brand


def color_hex(value: str) -> str:
    """Normalise '#ffd200' / 'ffd200' / '0xFFD200' to 'FFD200'."""
    v = str(value).strip().lstrip("#")
    if v.lower().startswith("0x"):
        v = v[2:]
    if len(v) != 6:
        die(f"colour must be RRGGBB, got '{value}'")
    return v.upper()


_COLOR_TOKEN_RE = re.compile(r"^(0[xX][0-9A-Fa-f]{6,8}|#[0-9A-Fa-f]{6,8}|[A-Za-z][A-Za-z0-9]*)(@(?:0(?:\.\d+)?|1(?:\.0+)?|\.\d+))?$")  # alpha is 0..1; "red@2" used to reach ffmpeg


def validate_color(value: str, flag: str = "--color") -> str:
    """Refuse a colour argument that isn't a plain ffmpeg colour token (named colour, 0xRRGGBB[AA],
    #RRGGBB[AA], optionally with an @alpha suffix). Every caller that string-formats a colour flag
    straight into a filter graph (color=c=..., tpad=...:color=..., rotate=...:fillcolor=...) must
    validate it first -- ffmpeg filter options are comma/colon-delimited, so an unvalidated value
    containing those characters lets a caller splice in an entirely different filter (a real,
    demonstrated filter-graph injection: --color "black,drawtext=text=..." renders arbitrary burnt-in
    text), not just an odd colour. This is the same "no filter graph accepted from the caller"
    invariant every other typed flag in this codebase already holds to."""
    if not _COLOR_TOKEN_RE.match(value):
        die(f"{flag} must be a plain colour (a name, 0xRRGGBB[AA], or #RRGGBB[AA], optionally @alpha), got '{value}'")
    return value


def print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fraction(v: Optional[str]) -> Optional[Fraction]:
    if not v or v in ("0/0", "0"):
        return None
    try:
        f = Fraction(v)
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _aspect_string(w: Optional[int], h: Optional[int]) -> Optional[str]:
    if not w or not h:
        return None
    f = Fraction(w, h)
    return f"{f.numerator}:{f.denominator}"
