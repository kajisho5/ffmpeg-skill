#!/usr/bin/env python3
"""Shared helpers for ffmpeg-skill scripts.

Standard library only. Locates ffmpeg/ffprobe on PATH, runs them with clear
error reporting, and provides a compact media probe used by every script.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


# `kind` (below) has been the only machine-readable failure axis since 0.1: a flat, 4-value
# vocabulary (input / missing_tool / ffmpeg / output) set at the ~7 call sites that ever pass one
# explicitly, defaulting to "input" everywhere else. `ERROR_CODE` is an additive, purely
# informational refinement layered on top for agents that want a stable enum to switch on instead
# of pattern-matching `kind` strings -- it is a static 1:1 relabelling of the exact same 4 buckets,
# not a new taxonomy. It intentionally does NOT introduce categories this codebase cannot actually
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
}

# None of the four kinds above are retryable in practice: an "input"/"missing_tool" failure is
# always deterministic (the same bad path or absent binary fails identically every time), and a
# "ffmpeg"/"output" failure -- while it COULD in principle be caused by a transient environment
# condition (full disk, OOM) rather than a bad command -- is never distinguishable from a
# deterministic content-cause failure without exit-code/stderr sniffing this codebase does not do.
# Reporting retryable=True for a code we can't actually back up would invite an agent into a blind
# retry loop against a command that will fail the same way every time; false-for-everything is the
# honest answer until real sniffing exists to justify anything else.
ERROR_RETRYABLE = False


def die(msg: str, code: int = 1, kind: str = "input") -> "None":
    """Exit with a message. Under --json also print a machine-readable failure document
    (status: failed) on stdout so callers get the same shape as a success; exit codes are unchanged."""
    sys.stderr.write(f"error: {msg}\n")
    if STATE.json:
        print_json({
            "status": "failed", "exit_code": code,
            "error": {
                "kind": kind, "message": msg,
                "code": ERROR_CODE.get(kind, "INTERNAL_ERROR"),
                "retryable": ERROR_RETRYABLE,
            },
            "commands": list(STATE.commands),
        })
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

    Scripts read it as attributes (``STATE.dry_run``) or, for older call sites, like a dict
    (``STATE["dry_run"]``). Keeping it a single explicit object rather than module globals makes
    it obvious what run()/emit() depend on and lets tests reset it with ``STATE.reset()``.
    """

    __slots__ = ("dry_run", "json", "progress", "fast", "duration_hint", "commands")
    _KEYS = ("dry_run", "json", "progress", "fast", "duration_hint", "commands")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.dry_run = False      # print ffmpeg commands, run nothing (ffprobe still runs)
        self.json = False         # emit() prints a JSON document instead of the output path
        self.progress = False     # run() streams percent / ETA to stderr for ffmpeg
        self.fast = False         # x264 preset forced to veryfast
        self.duration_hint: Optional[float] = None  # expected output length, for the progress percent
        self.commands: List[str] = []               # every ffmpeg command line, for --json and --dry-run

    # mapping-style access kept for backwards compatibility
    def __getitem__(self, key: str) -> Any:
        if key not in self._KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._KEYS:
            raise KeyError(key)
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default) if key in self._KEYS else default


STATE = Context()


def add_common(ap: "argparse.ArgumentParser") -> None:
    """Add the flags every script shares."""
    g = ap.add_argument_group("agent options")
    g.add_argument("--dry-run", action="store_true", help="print the ffmpeg commands that would run, run nothing")
    g.add_argument("--json", action="store_true", help="print a JSON result (output, probe, commands) on stdout instead of the path")
    g.add_argument("--progress", action="store_true", help="show percent / ETA on stderr while ffmpeg encodes")
    g.add_argument("--fast", action="store_true", help="preview quality: x264 preset veryfast (overrides --preset) for quick iterations")


def apply_common(args: "argparse.Namespace") -> None:
    STATE.dry_run = bool(getattr(args, "dry_run", False))
    STATE.json = bool(getattr(args, "json", False))
    STATE.progress = bool(getattr(args, "progress", False))
    STATE.fast = bool(getattr(args, "fast", False))
    if STATE.fast and getattr(args, "preset", None) in X264_PRESETS:
        args.preset = "veryfast"


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
    output = cmd[-1]
    if output in ("-", "pipe:0", "pipe:1") or output.startswith("pipe:") or output.startswith("-"):
        return
    try:
        if os.path.exists(output):
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


def run(cmd: Sequence[str], *, quiet: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, echoing it to stderr unless quiet. Exits on failure when check=True.

    ffmpeg invocations are recorded in STATE.commands (for --json), skipped under --dry-run
    (a fake successful CompletedProcess is returned so scripts can keep planning), and run
    with a progress readout under --progress. ffprobe and other tools always run.
    """
    is_ffmpeg = _is_ffmpeg(cmd)
    if is_ffmpeg:
        _check_no_overwrite_input(cmd)
        STATE.commands.append(_cmdline(cmd))
    if not quiet:
        info(("[dry-run] $ " if STATE.dry_run and is_ffmpeg else "$ ") + _cmdline(cmd))
    if STATE.dry_run and is_ffmpeg:
        return subprocess.CompletedProcess(list(cmd), 0, "", "")
    if STATE.progress and is_ffmpeg and cmd[-1] != "-":
        return _run_with_progress(list(cmd), check)
    return _run_captured(list(cmd), check)


def run_keeping_subtitles(cmd: List[str], output: str) -> "tuple[subprocess.CompletedProcess, bool]":
    """Run an ffmpeg command that already maps its video/audio, trying first to also
    stream-copy any subtitle/data streams the source has (`-map 0:s?`/`0:d?` are no-ops when
    there are none). A source whose subtitle codec cannot be copied into the target container
    (e.g. a container change) makes that first attempt fail; retry the same command without the
    extra maps rather than let a tool that never touched subtitles start hard-failing because of
    them. `cmd` is the full argv *without* the output path. Returns (proc, dropped) -- dropped is
    True only when the retry-without-subtitles path was actually needed."""
    proc = run(cmd + ["-map", "0:s?", "-map", "0:d?", "-c:s", "copy", "-c:d", "copy", output], check=False)
    if proc.returncode == 0:
        return proc, False
    return run(cmd + [output]), True


def _run_captured(cmd: List[str], check: bool) -> subprocess.CompletedProcess:
    """Plain run with stdout/stderr captured."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    """Run ffmpeg with -progress on a pipe and print percent/ETA to stderr."""
    import time
    total = STATE.duration_hint or 0.0
    full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    t0 = time.time()
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last = ""
    assert proc.stdout is not None
    for line in proc.stdout:
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
    _, err = proc.communicate()
    if last:
        sys.stderr.write("\r" + " " * len(last) + "\r")
    if proc.returncode != 0:
        _cleanup_partial_output(cmd)
        if check:
            _fail(cmd, proc.returncode, err)
    return subprocess.CompletedProcess(full, proc.returncode, "", err)


def shell_quote(s: str) -> str:
    if not s or any(ch in s for ch in " \t\"'\;|&<>()[]{}$*?"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def ffmpeg_base(overwrite: bool = True) -> List[str]:
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    cmd.append("-y" if overwrite else "-n")
    return cmd


MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts", ".mts", ".gif", ".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".png", ".jpg", ".jpeg"}


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
        if role == "output" and not STATE["dry_run"]:
            _output_failed(path, "not written")
        if STATE["dry_run"]:
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
                    "audio": {"codec": None, "channels": 0, "sample_rate": 0}, "subtitle_streams": 0}
        die(f"input not found: {path}")
    ffprobe = require_tool("ffprobe")
    proc = run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        quiet=True,
        check=False,
    )
    if proc.returncode != 0:
        if role == "output":
            _output_failed(path, f"ffprobe cannot read it:\n{proc.stderr.strip()}")
        die(f"ffprobe failed on {path}:\n{proc.stderr.strip()}")
    raw = json.loads(proc.stdout or "{}")
    fmt = raw.get("format", {})
    streams = raw.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    duration = _to_float(fmt.get("duration"))
    if duration is None and video:
        duration = _to_float(video.get("duration"))
    if duration is None and audio:
        duration = _to_float(audio.get("duration"))
    if duration and STATE.get("duration_hint") is None:
        STATE["duration_hint"] = duration

    out: Dict[str, Any] = {
        "file": path,
        "format": fmt.get("format_name"),
        "duration": duration,
        "size_bytes": _to_int(fmt.get("size")),
        "bitrate": _to_int(fmt.get("bit_rate")),
        "video": None,
        "audio": None,
        "subtitle_streams": len(subs),
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
            "bit_depth": 10 if "10" in pix else (12 if "12" in pix else 8),
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
        return int(h) * 3600 + int(m) * 60 + int(s) + frame / fps
    if len(parts) > 3:
        raise ValueError(f"bad time: {value}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


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
    never has to be escaped itself; `'`, `,`, `;`, `[` and `]` are graph-level characters.
    """
    p = str(Path(path))
    p = p.replace("\\", "/")
    p = p.replace(":", "\\\\:")
    for ch in ("'", ",", ";", "[", "]"):
        p = p.replace(ch, "\\" + ch)
    return p


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\\\\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
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


def x264_args(crf: int = 18, preset: str = "medium", keep_bt709: bool = True) -> List[str]:
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if keep_bt709:
        args += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
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


def analyze_levels(path: str, seconds: float = 20.0) -> Dict[str, Any]:
    """Sample luma/saturation statistics (signalstats) and guess whether the picture is Log-encoded.

    Log gammas (S-Log3, V-Log, C-Log, HLG-looking flat profiles) put black around 90-95/255 and
    white below ~235 with low saturation: the image looks grey and flat but is tagged as plain SDR.
    """
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-t", f"{seconds:.1f}", "-i", path, "-an",
           "-vf", "fps=2,signalstats,metadata=print:file=-", "-f", "null", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        scale = 1 / 4.0 if ymax <= 1023 else 1 / 16.0
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
