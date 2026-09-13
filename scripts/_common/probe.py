"""ffprobe and the measured facts read back off a file: the probe document every script starts
from, the verification every script ends with, and the level/waveform measurements.

Reading only -- the choices made from these facts live in decision.py.
"""
from __future__ import annotations

import json
import math
import os
import re
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence
from _common.emit import die
from _common.runner import STATE, require_tool, run, run_analysis


def fingerprint(path: str) -> Dict[str, Any]:
    """Size plus a sha256 over the first and last 8 MiB: enough to notice a re-export, a re-trim
    or a swapped file, cheap enough for a multi-GB source (hashing a whole master would make
    planning slower than the edit)."""
    import hashlib
    st = os.stat(path)
    h = hashlib.sha256()
    chunk = 8 * 1024 * 1024
    with open(path, "rb") as f:
        h.update(f.read(chunk))
        if st.st_size > 2 * chunk:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))
        elif st.st_size > chunk:
            h.update(f.read())
    return {"path": os.path.abspath(path), "size": st.st_size, "sha256_head_tail": h.hexdigest()}


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
            # 1.9 (2.0 A1 pre-shipped as a parallel key): true only for a PQ / HLG transfer or Dolby
            # Vision, i.e. a genuinely HDR signal. `hdr` also counts BT.2020 primaries on an SDR
            # transfer ("BT.2020 SDR" in hdr_format) and keeps that meaning until 2.0 renames it.
            "hdr_signal": trc in ("smpte2084", "arib-std-b67") or bool(dovi),
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
