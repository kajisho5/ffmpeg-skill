"""Process execution for ffmpeg-skill: locating the tools, running them under a wall-clock
ceiling, signal handling, output locking and staging, and the drawtext text-file spool.

Nothing here decides *what* to encode -- that is decision.py -- and nothing here formats a result
document -- that is emit.py. Imported through the `_common` facade by every script.
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
from typing import Any, Dict, List, Optional, Sequence, Tuple


INSTALL_HINTS = {
    "Darwin": ("  brew install ffmpeg-full; export PATH=\"$(brew --prefix ffmpeg-full)/bin:$PATH\""
               "   # keg-only, so installing it does not put it on PATH: keep the export in your shell profile;"
               " the plain ffmpeg formula lacks subtitles/drawtext/zscale"),
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
            out = subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
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


CODECS = ("h264", "hevc", "av1", "prores")


_ENCODERS: Optional[set] = None


class Context:
    """Per-process settings that the shared flags (--dry-run, --json, --progress, --fast) set once.

    Scripts read it as attributes (``STATE.dry_run``); the dict-style shims that once served
    older call sites are gone. Keeping it a single explicit object rather than module globals
    makes it obvious what run()/emit() depend on and lets tests reset it with ``STATE.reset()``.
    """

    __slots__ = ("dry_run", "json", "json_brief", "progress", "fast", "duration_hint", "commands", "timeout", "overwrite", "written", "preexisting", "plan", "plan_written", "plan_inputs", "codec",
                 "hw", "hw_source", "hw_notes", "hw_swaps", "hw_fallback", "hw_env_ignored", "hw_stages")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.dry_run = False      # print ffmpeg commands, run nothing (ffprobe still runs)
        self.json = False         # emit() prints a JSON document instead of the output path
        self.json_brief = False   # --json-brief: the same document trimmed to the fields a caller acts on
        self.progress = False     # run() streams percent / ETA to stderr for ffmpeg
        self.fast = False         # x264 preset forced to veryfast
        self.duration_hint: Optional[float] = None  # expected output length, for the progress percent
        self.commands: List[str] = []               # every ffmpeg command line, for --json and --dry-run
        self.timeout: float = _env_timeout()         # seconds per ffmpeg invocation, 0 = none
        self.overwrite = False                       # --overwrite: an existing output may be replaced
        self.written: set = set()                    # output paths this process has written itself
        self.preexisting: dict = {}                  # output path -> (size, mtime_ns) of a file that was there before we ran
        self.plan: Optional[str] = None              # --plan FILE: write the dry-run as a plan document (implies --dry-run)
        self.plan_written = False                    # write_plan() ran (emit or the exit hook), so the hook does not write twice
        self.plan_inputs: List[str] = []             # side inputs (srt/ass/lut/font files) a tool named through escape_filter_path
        self.codec: Optional[str] = None             # --codec: encoder for the re-encode (None = x264 for SDR, x265 for HDR)
        self.hw = False                              # --hw / $FFMPEG_SKILL_HW: VideoToolbox encoders where they apply
        self.hw_source: Optional[str] = None         # "flag" (--hw/--no-hw given) or "env" (FFMPEG_SKILL_HW), None = off by default
        self.hw_notes: List[str] = []                # why an encode stayed on (or fell back to) the CPU, for the result document
        self.hw_swaps: List[Tuple[List[str], List[str]]] = []  # (VideoToolbox args, the CPU args they replaced) for run()'s fallback
        self.hw_fallback = False                     # run() re-encoded a job VideoToolbox refused on the CPU (or a stage reported one)
        self.hw_env_ignored = False                  # $FFMPEG_SKILL_HW=1 was set but this tool's delivery preset does not take it (export.py)
        self.hw_stages: List[Dict[str, Any]] = []    # render.py: the `hw` facts each stage (a child process) reported


STATE = Context()


def add_common(ap: "argparse.ArgumentParser", codec: bool = True) -> None:
    """Add the flags every script shares. `codec=False` is for a tool that re-encodes but whose
    preset decides the encoder (export.py): it must not advertise --codec/--quality in its schema."""
    g = ap.add_argument_group("agent options")
    g.add_argument("--dry-run", action="store_true", help="print the ffmpeg commands that would run, run nothing")
    g.add_argument("--json", action="store_true", help="print a JSON result (output, probe, commands) on stdout instead of the path")
    g.add_argument("--json-brief", action="store_true",
                   help="like --json but trimmed: status, output, dry_run, verified, a compact summary of the output probe, this tool's own keys, and the command count instead of the command lines (failures print the full failure document, unchanged)")
    g.add_argument("--progress", action="store_true", help="show percent / ETA on stderr while ffmpeg encodes")
    g.add_argument("--fast", action="store_true", help="preview quality: x264 preset veryfast (overrides --preset) for quick iterations")
    if "--timeout" not in ap._option_string_actions:  # verify.py defines its own per-step --timeout; apply_common reads either
        g.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                       help=f"kill an ffmpeg run past this many seconds, kind=timeout (default {DEFAULT_TIMEOUT:.0f}; 0 = no limit)")
    g.add_argument("--overwrite", action="store_true",
                   help="allow replacing an existing output (refused without it)")
    g.add_argument("--plan", metavar="FILE",
                   help="write the dry run as a plan (inputs fingerprinted, commands, expected output, verify steps) that render.py FILE executes later; implies --dry-run")
    if codec and "crf" in ap._defaults:
        # A tool that re-encodes declares its CRF default with set_defaults(crf=N) before calling
        # this; --codec/--quality are its only encoder flags, resolved in video_args(). --crf was
        # the 1.x spelling of --quality (an alias from 1.8, deprecated in 1.10, removed in 2.0).
        g.add_argument("--codec", choices=CODECS, default=None,
                       help="video encoder for the re-encode: h264 (x264, the default for SDR), hevc (x265, the default for HDR), av1 (SVT-AV1 or libaom), prores (422 HQ, needs a .mov/.mkv output); HDR sources keep their colour on hevc/av1/prores")
        g.add_argument("--quality", type=int, default=ap._defaults["crf"], metavar="N",
                       help="encoder quality on the CRF scale (default %(default)s; lower = better; 18 visually lossless for x264/x265, up to 63 for av1); ignored by prores")
    if (codec and "crf" in ap._defaults) or not codec:
        _add_hw_flags(g, "encode on the GPU with Apple VideoToolbox (h264/hevc/prores; Apple Silicon only): several times faster, "
                         "larger files at the same quality; falls back to the CPU encoder, reported, where it cannot apply"
                         + ("" if codec else ". The only way to put a delivery preset on the GPU: $FFMPEG_SKILL_HW does not apply here"),
                      "encode on the CPU (x264/x265/SVT-AV1/prores_ks) even when $FFMPEG_SKILL_HW=1")
        ap.set_defaults(_hw_env=bool(codec))


def _add_hw_flags(g: Any, hw_help: str, no_hw_help: str) -> None:
    """--hw and --no-hw, each its own boolean (dests `hw` and `no_hw`). They are not one dest
    with store_true/store_false: the contract's input_schema keeps one property per dest and the
    MCP transport turns `true` into the flag, so a shared dest published --no-hw under the name
    `hw` and an MCP `hw: true` ran on the CPU. hw_flag() reads the pair back as True/False/None."""
    hw = g.add_mutually_exclusive_group()
    hw.add_argument("--hw", action="store_true", help=hw_help)
    hw.add_argument("--no-hw", action="store_true", help=no_hw_help)


def hw_flag(args: "argparse.Namespace") -> Optional[bool]:
    """--hw -> True, --no-hw -> False, neither (or a tool without the flags) -> None."""
    if getattr(args, "hw", False):
        return True
    if getattr(args, "no_hw", False):
        return False
    return None


def apply_common(args: "argparse.Namespace") -> None:
    STATE.plan = getattr(args, "plan", None) or None
    STATE.dry_run = bool(getattr(args, "dry_run", False)) or bool(STATE.plan)
    if STATE.plan:
        # tools that print their document instead of calling emit() (probe, and the analysis
        # tools without --json) still get their plan written, at exit, unless die() ran (review 6)
        import atexit
        atexit.register(_plan_at_exit)
    STATE.json_brief = bool(getattr(args, "json_brief", False))
    # --json-brief is a shorter --json, not a second output mode: it implies it, so a caller that
    # passes only --json-brief still gets a JSON document (and --json --json-brief is the brief one).
    STATE.json = bool(getattr(args, "json", False)) or STATE.json_brief
    STATE.progress = bool(getattr(args, "progress", False))
    STATE.fast = bool(getattr(args, "fast", False))
    STATE.overwrite = bool(getattr(args, "overwrite", False))
    if getattr(args, "timeout", None) is not None:
        STATE.timeout = max(0.0, float(args.timeout))
    if STATE.fast and getattr(args, "preset", None) in X264_PRESETS:
        args.preset = "veryfast"
    STATE.codec = getattr(args, "codec", None) or None
    STATE.hw_notes, STATE.hw_swaps, STATE.hw_fallback, STATE.hw_env_ignored, STATE.hw_stages = [], [], False, False, []
    flag = hw_flag(args)
    if flag is not None:
        STATE.hw, STATE.hw_source = bool(flag), "flag"
        if getattr(args, "_hw_orchestrator", False):
            # render.py / batch.py --hw|--no-hw: every stage they run inherits it as an explicit
            # choice -- export.py's delivery presets included, which $FFMPEG_SKILL_HW never reaches
            os.environ[HW_ENV] = "1" if flag else "0"
            os.environ[HW_FORCED_ENV] = "1"
    elif hasattr(args, "hw") and os.environ.get(HW_FORCED_ENV) == "1":
        STATE.hw, STATE.hw_source = env_hw(), "flag"
    elif hasattr(args, "hw") and getattr(args, "_hw_env", False) and env_hw():
        STATE.hw, STATE.hw_source = True, "env"
    else:
        STATE.hw, STATE.hw_source = False, None
        # export.py (a delivery preset decides the encoder): the machine default is not applied,
        # and the result says so rather than leaving a caller to wonder why the GPU was not used
        STATE.hw_env_ignored = (hasattr(args, "hw") and env_hw() and not getattr(args, "_hw_env", False)
                                and not getattr(args, "_hw_orchestrator", False))
    quality = getattr(args, "quality", None)
    if quality is not None:
        top = 63 if STATE.codec == "av1" else 51
        if not 0 <= int(quality) <= top:
            die(f"--quality must be between 0 and {top} for {STATE.codec or 'h264'} (CRF scale; 18 is visually lossless), got {quality}")
        args.crf = int(quality)  # every tool reads args.crf; --quality is the codec-neutral spelling of it
    if STATE.codec == "prores" and hasattr(args, "output"):
        out = getattr(args, "output", None)
        if not out:
            # every tool defaults its output to the source's extension (or .mp4): ProRes in an .mp4
            # fails inside ffmpeg with "codec not currently supported in container" (review 7)
            die("--codec prores needs an explicit -o NAME.mov (or .mkv): the default output name keeps the source's container, which cannot hold ProRes",
                hint="give -o NAME.mov")
        if os.path.splitext(str(out))[1].lower() not in (".mov", ".mkv"):
            die(f"--codec prores needs a .mov (or .mkv) output; {os.path.basename(str(out))} cannot hold ProRes",
                hint="give -o NAME.mov")
    crf = getattr(args, "crf", None)  # export.py's own --crf (its preset chooses the encoder)
    top = 63 if STATE.codec == "av1" else 51
    if crf is not None and not 0 <= int(crf) <= top:
        die(f"--crf must be between 0 and {top} ({'SVT-AV1' if STATE.codec == 'av1' else 'x264/x265'} scale; 18 is visually lossless), got {crf}")
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


def _fail(cmd: Sequence[str], returncode: int, stderr: str, ctx: "Optional[Context]" = None, retried: bool = False) -> None:
    # Partial-output cleanup already ran in the caller (_run_captured/_run_with_progress) for
    # every failed ffmpeg invocation, not just this check=True path -- see _cleanup_partial_output.
    # The process exit code is always 1 for an ffmpeg failure: ffmpeg's own code (1, 69, 218, 234,
    # a negative signal number...) varies by build and by the failing stage, and 124/127/130/143
    # are reserved for timeout, missing tool and interrupts. The raw code is kept in the JSON
    # document as `ffmpeg_returncode` for a caller that wants it. docs/design-decisions.md.
    #
    # `cmd` is the command that ran last: after run()'s GPU->CPU retry (`retried`), the CPU one.
    # Under --hw / $FFMPEG_SKILL_HW the message names its video encoder and the document carries
    # `encoder` and `hw`, because two encoders may have run and a caller must know whose stderr
    # this is.
    ctx = ctx or STATE
    tail = "\n".join(stderr.strip().splitlines()[-15:])
    what, extra = str(cmd[0]), {}
    enc = video_encoder_of(cmd) if ctx.hw else None
    if enc:
        on_gpu = enc.endswith("_videotoolbox")
        why = videotoolbox_failure(stderr) if on_gpu else None
        if not on_gpu and retried:
            what += f" (video encoder {enc}, the CPU retry after VideoToolbox refused the job)"
        elif on_gpu and why is None:
            what += f" (video encoder {enc}; not retried on the CPU: ffmpeg reported no VideoToolbox error)"
        else:
            what += f" (video encoder {enc})"
        report = hw_report(ctx, enc)
        if on_gpu:
            report["notes"].append(
                "the VideoToolbox encode failed and was not retried on the CPU: " +
                ("ffmpeg reported no encoder-open or compression-session error, so the cause is not the GPU (see the message)"
                 if why is None else f"VideoToolbox refused it ({why}) and no CPU encoder line was recorded to retry with"))
        extra = {"encoder": enc, "hw": report}
    die(f"command failed ({returncode}): {what}\n{tail}", code=1, kind="ffmpeg", ffmpeg_returncode=returncode, **extra)


def video_encoder_of(cmd: Sequence[str]) -> Optional[str]:
    """The video encoder an ffmpeg argv names last (-c:v / -vcodec / -codec:v), or None."""
    enc = None
    for i, a in enumerate(cmd[:-1]):
        if a in ("-c:v", "-vcodec", "-codec:v"):
            enc = str(cmd[i + 1])
    return enc


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
    a run never blocks on a y/N prompt) would replace it without a word. Since 2.0 it is refused
    (kind: input, before anything runs, dry runs included) unless --overwrite gives explicit
    consent; 1.x only warned, and FFMPEG_SKILL_NO_OVERWRITE=1 was the opt-in to this. Paths this
    process wrote itself (a two-pass tool, a copy-then-re-encode fallback) are never in question."""
    output = cmd[-1]
    if output in ("-",) or output.startswith("pipe:") or output.startswith("-"):
        return
    refuse_existing_outputs([output])


def refuse_existing_outputs(paths: Sequence[str]) -> None:
    """_check_existing_output() for every file a run will write, named together, before the
    first of them is written. A tool whose outputs are not all ffmpeg's last argument (caption.py's
    .srt/.ass sidecars) calls this up front so a hand-edited sidecar is refused like the video
    is, and a dry run predicts the same refusal."""
    existing: List[str] = []
    for output in paths:
        if not output:
            continue
        try:
            exists = os.path.isfile(output)
            real = os.path.realpath(output)
        except OSError:
            continue
        if not exists or real in STATE.written:
            continue
        try:
            st = os.stat(output)
            STATE.preexisting[real] = (st.st_size, st.st_mtime_ns)
        except OSError:
            pass
        if output not in existing:
            existing.append(output)
    if not existing or STATE.overwrite:
        return
    if len(existing) == 1:
        die(f"refusing to overwrite existing output {existing[0]!r}: pass --overwrite to replace it, or choose another -o path",
            kind="input", hint="pass --overwrite, or choose another -o path")
    die("refusing to overwrite existing outputs " + ", ".join(repr(p) for p in existing)
        + ": pass --overwrite to replace them, or choose another -o path",
        kind="input", hint="pass --overwrite, or choose another -o path")


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


HW_ENV = "FFMPEG_SKILL_HW"
# set only by render.py/batch.py --hw/--no-hw for the stages they run: "the outer command chose
# explicitly", so a child resolves $FFMPEG_SKILL_HW as a flag (export.py included), not a default
HW_FORCED_ENV = "_FFMPEG_SKILL_HW_EXPLICIT"


def add_hw_orchestrator_args(ap: "argparse.ArgumentParser") -> None:
    """--hw / --no-hw on a tool that runs other tools (render.py, batch.py) and encodes nothing itself."""
    _add_hw_flags(ap, "run every stage's encode on Apple VideoToolbox, the final delivery export included (Apple Silicon; "
                      "falls back to the CPU, reported, where it cannot apply). Without it, $FFMPEG_SKILL_HW=1 still "
                      "puts the intermediate stages on the GPU and leaves the delivery export on the CPU",
                  "every stage on the CPU encoders, whatever $FFMPEG_SKILL_HW says")
    ap.set_defaults(_hw_orchestrator=True)


def env_hw() -> bool:
    """$FFMPEG_SKILL_HW asks for VideoToolbox by default (1/true/yes/on); anything else is off."""
    return os.environ.get(HW_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def hw_platform_reason() -> Optional[str]:
    """None when this machine can take a VideoToolbox constant-quality encode, else why not.
    `-q:v` on VideoToolbox is Apple-Silicon-only in FFmpeg: an Intel Mac lists the encoders but
    rejects the quality setting, so the machine check is macOS AND Apple Silicon hardware."""
    if platform.system() != "Darwin":
        return "VideoToolbox is macOS-only"
    if not apple_silicon():
        return "VideoToolbox constant-quality encoding needs Apple Silicon"
    return None


_APPLE_SILICON: Optional[bool] = None


def apple_silicon() -> bool:
    """Whether this Mac's hardware is Apple Silicon -- not this interpreter's architecture: an
    x86_64 Python under Rosetta reports platform.machine() "x86_64" on an M-series Mac, where
    `sysctl -n hw.optional.arm64` still reads 1 (an Intel Mac has no such key). What decides -q:v
    is the ffmpeg binary's own build; an x86_64 ffmpeg there refuses it, and run() re-encodes that
    job on the CPU with ffmpeg's line in the note. Read once."""
    global _APPLE_SILICON
    if _APPLE_SILICON is None:
        _APPLE_SILICON = platform.machine() == "arm64"
        if not _APPLE_SILICON and platform.system() == "Darwin":
            try:
                out = subprocess.run([shutil.which("sysctl") or "/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                     errors="replace", timeout=10).stdout
                _APPLE_SILICON = out.strip() == "1"
            except (OSError, subprocess.SubprocessError):
                _APPLE_SILICON = False
    return _APPLE_SILICON


# What FFmpeg prints when a VideoToolbox encoder cannot take a job, read from the sources of 5.1,
# 6.0, 6.1, 7.0, 7.1, 8.0 and master (fftools/ffmpeg*.c, libavcodec/videotoolboxenc.c):
#  - the CLI's encoder-open failure, "Error while opening encoder", on every version. From 6.0 the
#    line carries the output stream's log context, which names the encoder ("[vost#0:0/
#    h264_videotoolbox @ 0x...]", from 8.0 followed by "[enc:h264_videotoolbox @ 0x...]"). 5.1
#    prints "Error initializing output stream 0:0 -- Error while opening encoder for output stream
#    #0:0 ...", which names no encoder, so there it counts only beside an error line the
#    VideoToolbox encoder logged in its own context;
#  - the encoder's own session failures, logged in its codec context ("[h264_videotoolbox @
#    0x...]"): "cannot create compression session", "cannot prepare encoder", "cannot encode
#    frame", "Error encoding frame". Each of them fails the encode. Matched without case and
#    without the "Error: " prefix, which master drops ("Cannot create compression session").
# Deliberately not counted, so the job is not run twice and the GPU is not blamed:
#  - "Could not open encoder before EOF" (7.0+). It names the encoder, but it follows a filter
#    graph that failed before the first frame -- a missing font, a bad filter argument -- so the
#    encoder never got as far as opening;
#  - the encoder's ERROR-level lines that do not fail the encode ("Error setting profile/level
#    property ... Output will be encoded using a supported profile/level combination", the
#    frames_before/frames_after/entropy/realtime/pixel-aspect properties), which a job that fails
#    for another reason (a full disk: "Error submitting a packet to the muxer") can still carry.
_VT_ENCODER_RE = re.compile(r"(?:h264|hevc|prores)_videotoolbox")
_VT_OWN_CONTEXT_RE = re.compile(r"\[(?:h264|hevc|prores)_videotoolbox @ [^\]]*\]")
_VT_SESSION_RE = re.compile(r"create compression session|prepare encoder|encode frame|encoding frame", re.I)
# the encoder's own ERROR-level lines that do not fail the encode (listed above)
_VT_NONFATAL_RE = re.compile(r"profile/level|entropy|frames_before|frames_after|realtime|pixel aspect|aspect ratio", re.I)
_STREAM_CONTEXT_RE = re.compile(r"\[[a-z]ost#\d+:\d+")
_ENCODER_OPEN_FAILED = "Error while opening encoder"


def videotoolbox_failure(stderr: str) -> Optional[str]:
    """The stderr line that shows a VideoToolbox encoder refused the job (could not open, or its
    compression session failed), with the log contexts' pointers dropped; None when the failure
    is something else. Only such a failure is retried on the CPU (see the notes above)."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    own = [ln for ln in lines if _VT_OWN_CONTEXT_RE.search(ln)]
    # the lines that can explain a refusal: not the non-fatal property errors, which a job that
    # failed elsewhere (5.1: an audio encoder that could not open) still carries
    fatal = [ln for ln in own if not _VT_NONFATAL_RE.search(ln)]
    found = next((ln for ln in own if _VT_SESSION_RE.search(ln)), None)
    if found is None:
        for ln in lines:
            if _ENCODER_OPEN_FAILED not in ln:
                continue
            if _VT_ENCODER_RE.search(ln):            # 6.0+: the line names the encoder that failed to open
                found = fatal[-1] if fatal else ln
                break
            if fatal and not _STREAM_CONTEXT_RE.search(ln):  # 5.1: no encoder named; the encoder's own error line is
                found = fatal[-1]
                break
    return re.sub(r" @ 0x[0-9a-fA-F]+", "", found)[:200] if found else None


def _hw_fallback(cmd: List[str], ctx: "Context") -> Optional[List[str]]:
    """`cmd` with every VideoToolbox encoder line this process built swapped back to the CPU line
    it replaced, or None when it has none -- for run() when the GPU refused an encode."""
    out, changed = list(cmd), False
    for vt, cpu in ctx.hw_swaps:
        n = len(vt)
        for i in range(len(out) - n + 1):
            if out[i:i + n] == vt:
                out[i:i + n] = cpu
                changed = True
                break
    return out if changed else None


def run(cmd: Sequence[str], *, quiet: bool = False, check: bool = True, ctx: "Optional[Context]" = None) -> subprocess.CompletedProcess:
    """Run a command, echoing it to stderr unless quiet. Exits on failure when check=True.

    ffmpeg invocations are recorded in STATE.commands (for --json), skipped under --dry-run
    (a fake successful CompletedProcess is returned so scripts can keep planning), and run
    with a progress readout under --progress. ffprobe and other tools always run. An output
    path that already exists is written through a temp file and replaced only on success
    (see _stage_existing_output), so a failed run never costs the caller the file that was there.

    `ctx` is the optional per-request Context added in 1.10 (2.0 makes it required, issue #189 B);
    omitted, the commands and flags are read from the process-global STATE as before.
    """
    ctx = ctx or STATE
    is_ffmpeg = _is_ffmpeg(cmd)
    if is_ffmpeg:
        _check_no_overwrite_input(cmd)
        _check_output_path(cmd)
        _check_existing_output(cmd)
        ctx.commands.append(_cmdline(cmd))
    if not quiet:
        info(("[dry-run] $ " if ctx.dry_run and is_ffmpeg else "$ ") + _cmdline(cmd), ctx=ctx)
    if ctx.dry_run and is_ffmpeg:
        return subprocess.CompletedProcess(list(cmd), 0, "", "")
    if is_ffmpeg:
        flush_drawtext_textfiles(cmd)
    with _OutputLock(cmd[-1] if is_ffmpeg else "-"):
        exec_cmd, final, tmp = _stage_existing_output(cmd) if is_ffmpeg else (list(cmd), None, None)
        def even_retry(proc: subprocess.CompletedProcess, ran: List[str]) -> "Tuple[subprocess.CompletedProcess, List[str]]":
            """An attempt that failed on odd dimensions, run again with an even scale: after the
            first attempt, and after a GPU->CPU retry (VideoToolbox may refuse an odd-sized job
            for another reason before x264 ever reports the size)."""
            if proc.returncode == 0 or not is_ffmpeg:
                return proc, ran
            retry = _odd_dimension_retry(ran, proc.stderr or "")
            if retry is not None:
                info("source has odd dimensions; scaling to even before encoding (yuv420p needs it)")
                ctx.commands[-1] = _cmdline(retry[:-1] + [cmd[-1]])
                return _execute(retry), retry
            if "not divisible by 2" in (proc.stderr or ""):
                die("the source has odd dimensions (width or height not divisible by 2) and this tool's filter graph "
                    "cannot pad them itself; make them even first, e.g. fit.py --width/--height, then retry",
                    kind="input")
            return proc, ran

        # `tried` is the last command run: the CPU fallback swaps its encoder line in
        proc, tried = even_retry(_execute(exec_cmd), exec_cmd)
        retried = False
        if proc.returncode != 0 and is_ffmpeg and ctx.hw_swaps:
            cpu_cmd = _hw_fallback(tried, ctx)
            if cpu_cmd is not None:
                # Only a failure VideoToolbox itself reported is retried on the CPU: a bad filter
                # graph, a missing font or a full disk would fail the same way twice and be
                # reported as the GPU's fault (videotoolbox_failure() has the strings and why).
                # A failure that is not one stays a failure of this command: with check=True,
                # _fail() names it; with check=False the caller's own retry decides (a success
                # after that must not carry a note about it).
                why = videotoolbox_failure(proc.stderr or "")
                if why is not None:
                    reason = f"VideoToolbox refused the encode: {why}"
                    info(reason + "; retrying on the CPU encoder")
                    ctx.hw_notes.append(reason + "; re-encoded on the CPU")
                    ctx.hw_fallback = True
                    ctx.commands[-1] = _cmdline(cpu_cmd[:-1] + [cmd[-1]])
                    if not quiet:
                        # echoed like the first attempt, so a caller that reads the "$ " lines
                        # (render.py's stages) records the command that really ran
                        info("$ " + ctx.commands[-1], ctx=ctx)
                    proc, tried = even_retry(_execute(cpu_cmd), cpu_cmd)
                    retried = True
        if proc.returncode != 0 and check:
            _fail(tried, proc.returncode, proc.stderr or "", ctx=ctx, retried=retried)
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
        # #234: decode as UTF-8, never as the machine's locale code page -- ffmpeg echoes the
        # input filename on stderr, and loudness/check parse the loudnorm JSON out of it. The
        # encoding kwargs are rejected with text=False, so they are only passed for text mode.
        text_kw = {"encoding": "utf-8", "errors": "replace"} if text else {}
        proc = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, **text_kw, timeout=limit)
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
    child = subprocess.Popen([sys.executable] + list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
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
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
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
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
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


def place_output(src: str, dst: str, move: bool = False) -> None:
    """Deliver an already-rendered file to `dst` under the same rules as an ffmpeg output:
    the path is checked, the output's lock is held (as run() holds it for an ffmpeg write), an
    existing file is only replaced through a sibling temp so a failed copy never costs the
    caller what was there, and the result is remembered as ours. render.py's final
    `copyfile()` used to bypass all of them.

    `move`: `src` is a temp file the caller wrote next to `dst` (sibling_temp), renamed into place
    with os.replace() under the lock instead of copied -- a checked `cut.py --segments` join was
    copied whole, about 2 s for 240 MB. A rename that fails (another filesystem) falls back to
    the copy."""
    import shutil
    cmd = ["ffmpeg", dst]
    _check_output_path(cmd)
    _check_existing_output(cmd)
    d, base = os.path.split(dst)
    stem, ext = os.path.splitext(base)
    tmp = os.path.join(d, f".{stem}.ffskill-{os.getpid()}{ext}")
    with _OutputLock(dst):
        if move:
            try:
                os.replace(src, dst)
                _remember_output(cmd)
                return
            except OSError:
                pass
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


def sibling_temp(dst: str, tag: str) -> str:
    """A hidden path next to `dst`, with its extension (the muxer is chosen by it), for a file
    place_output(..., move=True) renames into place: same directory, so the rename never
    crosses a filesystem."""
    d, base = os.path.split(dst)
    stem, ext = os.path.splitext(base)
    return os.path.join(d, f".{stem}.ffskill-{tag}-{os.getpid()}{ext}")


_DRAWTEXT_TMPDIR: "Optional[str]" = None


_DRAWTEXT_PENDING: "Dict[str, str]" = {}


def _drawtext_tmpdir(create: bool = True) -> str:
    """The private, per-run directory drawn-text files live in.

    tempfile.mkdtemp() creates it 0700 under a name nobody can guess, which is the whole point:
    the 1.15.0 shape (a fixed, world-writable `/tmp/ffmpeg-skill-text` entered with
    makedirs(exist_ok=True) and content-addressed filenames) let any other user on the machine
    pre-create the directory or plant a symlink at a predictable name, and handed the second
    user of a shared box a PermissionError out of filter construction instead of a `kind: input`
    refusal. The directory is removed when the process ends, whether it succeeded or failed.
    """
    global _DRAWTEXT_TMPDIR
    import tempfile
    if _DRAWTEXT_TMPDIR and os.path.isdir(_DRAWTEXT_TMPDIR):
        return _DRAWTEXT_TMPDIR
    if not create:
        # --dry-run names the path it WOULD use and creates nothing (a dry run writes nothing).
        return os.path.join(tempfile.gettempdir(), "ffmpeg-skill-text-%d" % os.getpid())
    import atexit
    _DRAWTEXT_TMPDIR = tempfile.mkdtemp(prefix="ffmpeg-skill-text-")
    atexit.register(shutil.rmtree, _DRAWTEXT_TMPDIR, True)
    return _DRAWTEXT_TMPDIR


def flush_drawtext_textfiles(cmd: "Sequence[str]") -> "List[str]":
    """Write the drawn-text files this command actually names, and return their paths.

    The text is registered when the filter STRING is built, but a filter string is not a run:
    graphics.py builds the drawtext graph even on a job that is finally rendered through libass,
    and every tool builds one under --dry-run. Writing here -- from run(), past the dry-run
    return, against the command that is about to be executed -- is what keeps both of those from
    leaving a file behind.
    """
    if not _DRAWTEXT_PENDING:
        return []
    joined = " ".join(str(a) for a in cmd)
    written = []
    for path, body in list(_DRAWTEXT_PENDING.items()):
        # match on the unique file name, not the full path: inside a filter string the path is
        # escaped (a Windows drive colon becomes `C\\:`, and the separators are forward slashes),
        # so the registered spelling never appears verbatim in the command
        if os.path.basename(path) not in joined or os.path.exists(path):
            continue
        # O_NOFOLLOW exists on POSIX only; the directory is private (mkdtemp, 0700) so the
        # symlink guard is belt and braces there and unavailable on Windows
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        written.append(path)
    return written


def ffmpeg_encoders() -> set:
    """Names from `ffmpeg -encoders` -- the build that will run the encode -- read once; empty when
    it cannot be read. Used to pick an AV1 encoder, to refuse --codec av1 / prores before ffmpeg
    would, and to see whether --hw's VideoToolbox encoders are built in.

    Under --dry-run only, the list comes from `ffprobe -encoders` instead: a dry run promises
    never to run ffmpeg (docs/contract.md: ffmpeg_execution "none") while ffprobe always may, as in
    ffmpeg_version(). That is the one case for ffprobe. On a mixed install (a Homebrew ffprobe next
    to a static ffmpeg) its list is another build's, so a real run never uses it: the AV1/ProRes
    refusals and the VideoToolbox check must describe the binary that encodes, and a plan that
    read ffprobe's list is re-decided against ffmpeg's when it runs."""
    global _ENCODERS
    if _ENCODERS is None:
        _ENCODERS = set()
        tool = "ffprobe" if STATE.dry_run else "ffmpeg"
        try:
            out = subprocess.run([shutil.which(tool) or tool, "-hide_banner", "-encoders"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT).stdout
            _ENCODERS = set(re.findall(r"^\s*[VAS][.\w]{5}\s+(\S+)", out, re.M))
        except (OSError, subprocess.SubprocessError):
            pass
    return _ENCODERS


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


# Deferred to the foot of the module on purpose. runner is the first module the package loads and
# emit needs runner's Context/STATE/ERROR_CODE, so the two form a cycle that has to be cut
# somewhere: by the time this line runs every name emit reads from runner above is defined, and
# every name runner reads from emit is only ever read inside a function body, never at import.
from _common.emit import _plan_at_exit, die, hw_report, info  # noqa: E402
