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

INSTALL_HINTS = {
    "Darwin": "  brew install ffmpeg",
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


def die(msg: str, code: int = 1) -> "None":
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)


def info(msg: str) -> None:
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
        code=127,
    )
    return ""  # unreachable


def run(cmd: Sequence[str], *, quiet: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, echoing it to stderr unless quiet. Exits on failure when check=True."""
    if not quiet:
        info("$ " + " ".join(shell_quote(c) for c in cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        die(f"command failed ({proc.returncode}): {cmd[0]}\n{tail}", code=proc.returncode or 1)
    return proc


def shell_quote(s: str) -> str:
    if not s or any(ch in s for ch in " \t\"'\;|&<>()[]{}$*?"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def ffmpeg_base(overwrite: bool = True) -> List[str]:
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    cmd.append("-y" if overwrite else "-n")
    return cmd


def probe(path: str) -> Dict[str, Any]:
    """Return a compact, script-friendly description of a media file."""
    if not os.path.exists(path):
        die(f"input not found: {path}")
    ffprobe = require_tool("ffprobe")
    proc = run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        quiet=True,
        check=False,
    )
    if proc.returncode != 0:
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

    out: Dict[str, Any] = {
        "file": path,
        "format": fmt.get("format_name"),
        "duration": duration,
        "size_bytes": _to_int(fmt.get("size")),
        "bitrate": _to_int(fmt.get("bit_rate")),
        "video": None,
        "audio": None,
        "subtitle_streams": len(subs),
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
            "hdr_format": ("HDR10/PQ" if trc == "smpte2084" else "HLG" if trc == "arib-std-b67" else "BT.2020 SDR" if hdr else None),
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
    return out


def default_output(input_path: str, suffix: str, ext: Optional[str] = None) -> str:
    p = Path(input_path)
    new_ext = ext if ext else p.suffix.lstrip(".") or "mp4"
    return str(p.with_name(f"{p.stem}_{suffix}.{new_ext}"))


def parse_time(value: str) -> float:
    """Accept seconds ('12.5'), mm:ss ('1:30'), hh:mm:ss(.ms) ('00:01:30.250') or SRT '00:01:30,250'."""
    v = value.strip().replace(",", ".")
    if not v:
        raise ValueError("empty time")
    parts = v.split(":")
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


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter graph option value."""
    p = str(Path(path))
    p = p.replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
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
