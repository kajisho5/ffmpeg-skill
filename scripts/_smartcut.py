"""cut.py --smart: a keyframe-aware cut that re-encodes only the partial GOPs at each cut point.

A segment [s, e) on a CFR, progressive H.264 source is split at its keyframes:

    head  [first frame at/after s, K1)        re-encoded (K1 = first keyframe at or after s)
    copy  [K1, K2)                            stream-copied, whole closed GOPs
    tail  [K2, first frame at/after e)        re-encoded (K2 = last keyframe at or before e)

A part that is empty (s on a keyframe, e on a keyframe or the end of the video) is left out; a
segment with no keyframe inside it is one re-encoded part. The re-encoded parts are encoded with
libx264 matched to the source stream (profile, level, pixel format, reorder depth, frame size,
SAR, colour tags) and every part is written as MPEG-TS, where each keyframe carries its own
parameter sets in-band, so the decoder switches between the encoder's SPS/PPS and the source's at
every join. The parts are joined with the concat demuxer (each part's exact length stated), and
the sound is cut from the source on the same frame grid and encoded once, in the same command.

The result is verified before it is moved into place, and any failure falls back to the full
re-encode with the reason stated:

    frames    the output's frame count and presentation times: one frame per frame duration from
              0, none missing, none repeated
    packets   every copied part's packets against the source's (MD5 of each packet with the
              parameter-set and delimiter NAL units removed, which the in-band switch adds)
    decode    framemd5 of each re-encoded part as written against the same frames decoded from
              the output, and of the first DECODE_CHECK_MAX_FRAMES frames of each copied
              part against the source's
    params    the re-encoded parts' stream parameters against the source's, and the output's
              time base against the source's

Nothing here decides where to cut; it only executes the cut it is given.
"""
import os
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from _common import STATE, aac_args, concat_list_line, ffmpeg_base, require_tool, run
from _common.runner import fail_if_classified

# the stream parameters a re-encoded part must share with the source (ffprobe -show_streams)
MATCH_FIELDS = ("codec_name", "profile", "level", "pix_fmt", "width", "height", "sample_aspect_ratio",
                "has_b_frames", "color_space", "color_range", "color_transfer", "color_primaries")
# what libx264 here can encode to match: 8-bit 4:2:0 (full range as yuvj420p)
SMART_PIX_FMTS = ("yuv420p", "yuvj420p")
SMART_PROFILES = {"Constrained Baseline": "baseline", "Baseline": "baseline", "Main": "main", "High": "high"}
SMART_EXTS = (".mp4", ".mov", ".m4v", ".mkv")
# the first frames of a copied part are decoded and compared against the source's; capped so a long part
# does not make the check cost a long decode
DECODE_CHECK_MAX_FRAMES = 300
# an input -ss lands this far after the keyframe it is asked for (ffprobe prints microseconds)
_SEEK_PAST = 1e-4
_DTS_MARGIN = 1e-4


class SmartFallback(Exception):
    """The smart cut cannot be made or did not verify: `reason` is the stated cause."""

    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.reason, self.code = reason, code


def stream_params(path: str) -> Optional[Dict[str, Any]]:
    """The first video stream's parameters (MATCH_FIELDS plus field_order, time_base, r_frame_rate)."""
    import json
    fields = ",".join(MATCH_FIELDS + ("field_order", "time_base", "r_frame_rate"))
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                f"stream={fields}", "-of", "json", path], quiet=True, check=False)
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
    except ValueError:
        return None
    return streams[0] if proc.returncode == 0 and streams else None


def _norm(field: str, value: Any) -> Any:
    if field == "profile":
        return SMART_PROFILES.get(str(value), value)
    if field == "sample_aspect_ratio" and value in (None, "0:1", "N/A"):
        return "1:1"
    return value


def mismatches(want: Dict[str, Any], got: Dict[str, Any]) -> List[str]:
    """`field source/part` for every MATCH_FIELDS value the part does not share."""
    return [f"{f} {want.get(f)}/{got.get(f)}" for f in MATCH_FIELDS if _norm(f, want.get(f)) != _norm(f, got.get(f))]


def ineligible(params: Optional[Dict[str, Any]], meta: Dict[str, Any], ext: str) -> Optional[Tuple[str, str]]:
    """(reason, code) when the source or the output cannot take a smart cut, else None."""
    if params is None:
        return "the source's video stream parameters could not be read", "params_unreadable"
    if ext.lower() not in SMART_EXTS:
        return f"--smart writes {', '.join(SMART_EXTS)}; {ext} is not one", "container"
    if params.get("codec_name") != "h264":
        return (f"--smart matches the source with libx264, so it takes H.264; this source is "
                f"{params.get('codec_name')}", "codec")
    if params.get("pix_fmt") not in SMART_PIX_FMTS:
        return f"--smart encodes 8-bit 4:2:0; this source is {params.get('pix_fmt')}", "pix_fmt"
    if str(params.get("profile")) not in SMART_PROFILES:
        return f"H.264 profile {params.get('profile')} cannot be matched by libx264 here", "profile"
    if params.get("field_order") not in (None, "progressive", "unknown"):
        return f"the source is interlaced ({params.get('field_order')})", "interlaced"
    if int(params.get("has_b_frames") or 0) > 2:
        return f"a reorder depth of {params.get('has_b_frames')} frames cannot be matched", "reorder_depth"
    if not _rate(params):
        return "the source states no frame rate", "frame_rate"
    if (meta.get("video") or {}).get("bt2020_or_hdr"):
        return "an HDR or BT.2020 source is encoded on the 10-bit HEVC line, not matched", "hdr"
    return None


def _rate(params: Dict[str, Any]) -> Optional[Fraction]:
    try:
        q = Fraction(str(params.get("r_frame_rate") or ""))
    except (ValueError, ZeroDivisionError):
        return None
    return q if q > 0 else None


def x264_line(params: Dict[str, Any], crf: int, preset: str) -> List[str]:
    """libx264 arguments that reproduce the source stream's parameters (MATCH_FIELDS)."""
    level = int(params.get("level") or 0)
    depth = int(params.get("has_b_frames") or 0)
    # the reorder depth decides how far each part's decode times run ahead of its presentation
    # times; parts of different depth would collide in decode order at the join
    b = "bframes=0" if depth == 0 else ("bframes=3:b-pyramid=none" if depth == 1 else "bframes=3:b-pyramid=normal")
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-profile:v", SMART_PROFILES[str(params["profile"])], "-pix_fmt", params["pix_fmt"],
            "-x264-params", f"{b}:open-gop=0"]
    if level:
        args += ["-level:v", f"{level // 10}.{level % 10}"]
    for flag, field in (("-colorspace", "color_space"), ("-color_primaries", "color_primaries"),
                        ("-color_trc", "color_transfer"), ("-color_range", "color_range")):
        value = params.get(field)
        if value and value != "unknown":
            args += [flag, str(value)]
    return args


def frames_between(frames: List[float], lo: float, hi: Optional[float]) -> List[float]:
    return [p for p in frames if p >= lo - 1e-6 and (hi is None or p < hi - 1e-6)]


def plan_segment(packets: List[Tuple[Any, Any, bool]], s: float, e: float, vend: Optional[float],
                 gop_is_open) -> List[Dict[str, Any]]:
    """The parts of one segment, in order: {kind: reencode|copy, start, end (None: to the end of
    the video), frames}. Raises SmartFallback when a keyframe the copy would start or stop at
    opens its GOP or the packets around a cut were not read."""
    frames = sorted(p[0] for p in packets if p[0] is not None)
    keyidx = [i for i, p in enumerate(packets) if p[2] and p[0] is not None and p[1] is not None]
    seg = frames_between(frames, s, e)
    if not seg:
        raise SmartFallback(f"no frame of the source lies in {s:.3f}-{e:.3f}s", "no_frames")
    first, last = seg[0], seg[-1]
    to_end = vend is not None and e >= vend - 1e-6
    end_bound = None if to_end else next((p for p in frames if p >= e - 1e-6), None)
    if end_bound is None and not to_end:
        raise SmartFallback(f"the frames after {e:.3f}s were not read", "packets")
    k1 = next((i for i in keyidx if packets[i][0] >= first - 1e-6), None)
    if k1 is None or packets[k1][0] > last + 1e-6:
        return [{"kind": "reencode", "start": first, "end": end_bound, "frames": len(seg)}]
    if gop_is_open(packets, k1):
        raise SmartFallback(f"the keyframe at {packets[k1][0]:.3f}s opens its GOP (frames decoded after it are shown "
                            "before it), so a copy cannot start there", "open_gop")
    k1_pts = packets[k1][0]
    # where the copy stops: the last keyframe presented at or before the end bound, decoded after K1
    stops = [i for i in keyidx if packets[i][1] > packets[k1][1] + 1e-9
             and (end_bound is None or packets[i][0] <= end_bound + 1e-6)]
    k2 = stops[-1] if stops else None
    if k2 is not None and gop_is_open(packets, k2):
        raise SmartFallback(f"the keyframe at {packets[k2][0]:.3f}s opens its GOP, so the copy cannot stop there",
                            "open_gop")
    copy_end = packets[k2][0] if k2 is not None else None
    if copy_end is None and not to_end:
        # no keyframe after K1 inside the segment: the copy would run past the end in its last GOP
        return [{"kind": "reencode", "start": first, "end": end_bound, "frames": len(seg)}]
    parts: List[Dict[str, Any]] = []
    if first < k1_pts - 1e-6:
        parts.append({"kind": "reencode", "start": first, "end": k1_pts,
                      "frames": len(frames_between(frames, first, k1_pts))})
    parts.append({"kind": "copy", "start": k1_pts, "end": copy_end, "key_dts": packets[k1][1],
                  "end_dts": packets[k2][1] if k2 is not None else None})
    if copy_end is not None and (end_bound is None or copy_end < end_bound - 1e-6):
        tail = frames_between(frames, copy_end, end_bound)
        if tail:
            parts.append({"kind": "reencode", "start": copy_end, "end": end_bound, "frames": len(tail)})
    return parts


def _framehashes(cmd: List[str], code: str) -> List[Tuple[int, str]]:
    """(size, md5) per line of an ffmpeg -f framemd5 run (packets with -c copy, frames otherwise).
    A run that failed is no evidence, even when the hashes it printed match: a classified failure
    (a full disk) fails the run, any other is a fallback with `code`."""
    proc = run(cmd, quiet=True, check=False)
    fail_if_classified(proc)
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
        raise SmartFallback(f"the check could not hash {cmd[cmd.index('-i') + 1]}: "
                            f"{lines[-1] if lines else f'exit code {proc.returncode}'}", code)
    out = []
    for line in (proc.stdout or "").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 6:
            try:
                out.append((int(cols[4]), cols[5]))
            except ValueError:
                continue
    return out


_NORMALIZE = "h264_mp4toannexb,filter_units=remove_types=7|8|9"


def packet_hashes(path: str, seek: Optional[float] = None, t: Optional[float] = None) -> List[Tuple[int, str]]:
    """The first video stream's packets as (size, md5) with SPS, PPS and delimiters removed."""
    ff = require_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if seek is not None:
        cmd += ["-ss", f"{seek:.6f}"]
    cmd += ["-i", path]
    if t is not None:
        cmd += ["-t", f"{t:.6f}"]
    return _framehashes(cmd + ["-map", "0:v:0", "-c", "copy", "-bsf:v", _NORMALIZE, "-f", "framemd5", "-"], "packets")


def frame_hashes(path: str, at: Optional[float], count: int) -> List[Tuple[int, str]]:
    """framemd5 of `count` decoded frames from `at` (seconds, an accurate seek; None from the start)."""
    ff = require_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if at is not None and at > 0:
        cmd += ["-ss", f"{at:.6f}"]
    return _framehashes(cmd + ["-i", path, "-map", "0:v:0", "-frames:v", str(count), "-flags:v", "+bitexact",
                               "-fflags", "+bitexact", "-f", "framemd5", "-"], "decode")


def output_pts(path: str) -> List[float]:
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                "-of", "csv=p=0", path], quiet=True, check=False)
    out = []
    for line in (proc.stdout or "").split():
        try:
            out.append(float(line.strip(",")))
        except ValueError:
            continue
    return sorted(out)


def _write(cmd: List[str], what: str) -> None:
    """Run one of the smart cut's ffmpeg writes. A failure the runner classifies (a full disk, a
    missing input) fails the run as it would anywhere; any other is a fallback with ffmpeg's reason
    (x264 refusing the matched profile at --quality 0, a copy the muxer rejects)."""
    proc = run(cmd, check=False)
    fail_if_classified(proc)
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
        why = next((ln for ln in lines if "rror" in ln), lines[-1] if lines else f"exit code {proc.returncode}")
        raise SmartFallback(f"ffmpeg could not write {what}: {why}", "encode")


def _count(n_frames: int, rate: Fraction) -> str:
    """A part's exact length for the concat list's `duration`, in seconds."""
    return f"{float(Fraction(n_frames) / rate):.9f}"


def execute(src: str, segments: List[Tuple[float, float]], dst: str, meta: Dict[str, Any], params: Dict[str, Any],
            packets, crf: int, preset: str, tmp: str, *, vend: Optional[float], gop_is_open, landing,
            origin, declick: float, seek_margin: float) -> Dict[str, Any]:
    """Write the smart cut of `segments` to `dst` and verify it (module docstring). Returns the
    `smart` document; raises SmartFallback with the reason when it cannot be made or does not verify.
    `landing(src, t)` is cut.seek_keyframe, `origin(path)` cut.file_origin."""
    rate = _rate(params)
    frame = float(1 / rate)
    half = frame / 2
    x264 = x264_line(params, crf, preset)
    plans = [plan_segment(packets, s, e, vend, gop_is_open) for s, e in segments]
    has_a = bool(meta.get("audio"))
    for si, ((s, _), segment_parts) in enumerate(zip(segments, plans)):
        # the sound is trimmed on the picture's grid from the segment's first frame; a picture that
        # starts later than a frame after the segment (video that starts after its audio) would
        # lose the sound before it, which the full re-encode keeps
        late = segment_parts[0]["start"] - s
        if has_a and late > frame + 1e-6:
            raise SmartFallback(f"the picture of segment {si + 1} starts {late:.3f}s after it does, and the sound "
                                "before it is kept only by a full re-encode", "av_offset")
    parts: List[Dict[str, Any]] = []
    for si, segment_parts in enumerate(plans):
        for part in segment_parts:
            part = dict(part, segment=si, path=os.path.join(tmp, f"part{len(parts):03d}.ts"))
            if part["kind"] == "reencode":
                m = min(seek_margin, part["start"])
                trim = f"trim=start={m - half:.6f}" + (f":end={m + part['frames'] * frame - half:.6f}")
                _write(ffmpeg_base() + ["-ss", f"{part['start'] - m:.6f}", "-i", src, "-map", "0:v:0", "-an", "-sn", "-dn",
                                        "-vf", f"{trim},setpts=PTS-STARTPTS", "-frames:v", str(part["frames"]),
                                        "-fps_mode", "passthrough"] + x264 + ["-f", "mpegts", part["path"]],
                       f"the re-encoded part from {part['start']:.3f}s")
            else:
                target = part["start"] + _SEEK_PAST
                landed = None if STATE.dry_run else landing(src, target)
                if not STATE.dry_run and (landed is None or abs(landed[0] - part["start"]) > 1e-4):
                    raise SmartFallback(f"a stream copy from the keyframe at {part['start']:.3f}s lands at "
                                        f"{'an unreadable place' if landed is None else f'{landed[0]:.3f}s'}", "seek")
                part["seek"] = target
                part["t"] = None if part["end_dts"] is None else part["end_dts"] - target - _DTS_MARGIN
                _write(ffmpeg_base() + ["-ss", f"{target:.6f}", "-i", src] + ([] if part["t"] is None else ["-t", f"{part['t']:.6f}"])
                       + ["-map", "0:v:0", "-an", "-sn", "-dn", "-c", "copy", "-f", "mpegts", part["path"]],
                       f"the copied part from {part['start']:.3f}s")
            if not STATE.dry_run:
                written = output_pts(part["path"])
                if part["kind"] == "copy":
                    expected = None if part["end"] is None else round((part["end"] - part["start"]) * rate)
                    if expected is not None and len(written) != expected:
                        raise SmartFallback(f"the copy from {part['start']:.3f}s holds {len(written)} frames where the "
                                            f"source has {expected}", "copy_count")
                    part["frames"] = len(written)
                elif len(written) != part["frames"]:
                    raise SmartFallback(f"the re-encode from {part['start']:.3f}s holds {len(written)} frames, not "
                                        f"{part['frames']}", "encode_count")
                if part["kind"] == "reencode":
                    got = stream_params(part["path"]) or {}
                    diff = mismatches(params, got)
                    if diff:
                        raise SmartFallback("the re-encoded part does not match the source: " + ", ".join(diff), "params_mismatch")
            parts.append(part)
    listfile = os.path.join(tmp, "smart.txt")
    with open(listfile, "w", encoding="utf-8") as fh:
        for part in parts:
            fh.write(concat_list_line(part["path"]) + "\n")
            if part.get("frames"):
                fh.write(f"duration {_count(part['frames'], rate)}\n")
    ext = os.path.splitext(dst)[1].lower()
    cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile]
    graph: List[str] = []
    if has_a:
        # the sound of each segment from the source, on the picture's frame grid, encoded once
        pads = ""
        for i, (s, e) in enumerate(segments):
            first = plans[i][0]["start"]
            last = plans[i][-1]
            end = last["end"] if last["end"] is not None else e
            m = min(seek_margin, s)
            cmd += ["-ss", f"{s - m:.6f}", "-t", f"{m + (end - s) + 1.0:.6f}", "-i", src]
            a, b = m + (first - s), m + (end - s)
            fade = min(declick, (b - a) / 2)
            fades = (f",afade=t=in:st=0:d={fade:.6f}" if fade > 0 and i > 0 else "")
            fades += (f",afade=t=out:st={b - a - fade:.6f}:d={fade:.6f}" if fade > 0 and i < len(segments) - 1 else "")
            # padded to its picture's length: sound that ends early (a track shorter than the
            # picture) must not pull the next segment's sound forward
            graph.append(f"[{i + 1}:a:0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-{a:.6f}/TB,"
                         f"aresample=async=1:first_pts=0,apad=whole_dur={b - a:.6f}{fades}[a{i}]")
            pads += f"[a{i}]"
        graph.append(f"{pads}concat=n={len(segments)}:v=0:a=1[a]")
        cmd += ["-filter_complex", ";".join(graph), "-map", "0:v:0", "-map", "[a]"] + aac_args()
    else:
        cmd += ["-map", "0:v:0"]
    cmd += ["-c:v", "copy", "-bsf:v", "filter_units=remove_types=9", "-sn", "-dn"]
    tb = str(params.get("time_base") or "")
    if ext in (".mp4", ".mov", ".m4v"):
        if tb.startswith("1/"):
            cmd += ["-video_track_timescale", tb[2:]]
        cmd += ["-tag:v", "avc1", "-movflags", "+faststart"]
    _write(cmd + [dst], "the joined parts")
    doc: Dict[str, Any] = {
        "applied": True,
        "parts": [{"segment": p["segment"] + 1, "kind": p["kind"], "start": round(p["start"], 6),
                   "end": None if p["end"] is None else round(p["end"], 6), "frames": p.get("frames")} for p in parts],
        "reencoded_frames": sum(p.get("frames") or 0 for p in parts if p["kind"] == "reencode"),
        "copied_frames": sum(p.get("frames") or 0 for p in parts if p["kind"] == "copy"),
        "matched": {f: params.get(f) for f in MATCH_FIELDS},
        "encoder": x264,
    }
    if STATE.dry_run:
        doc["checks"] = None
        return doc
    doc["checks"] = verify(src, dst, parts, params, rate, origin)
    doc["time_base"] = doc["checks"]["time_base"]
    return doc


def verify(src: str, dst: str, parts: List[Dict[str, Any]], params: Dict[str, Any], rate: Fraction, origin) -> Dict[str, Any]:
    """The checks in the module docstring; raises SmartFallback on the first that fails."""
    frame = float(1 / rate)
    half = frame / 2
    pts = output_pts(dst)
    expected = sum(p["frames"] for p in parts)
    if len(pts) != expected:
        raise SmartFallback(f"the output holds {len(pts)} frames where the parts hold {expected}", "frames")
    worst = max((abs(t - pts[0] - i * frame) for i, t in enumerate(pts)), default=0.0)
    if worst >= half:
        at = next(i for i, t in enumerate(pts) if abs(t - pts[0] - i * frame) >= half)
        raise SmartFallback(f"frame {at} of the output is presented at {pts[at] - pts[0]:.6f}s, off the "
                            f"{frame:.6f}s grid (a gap or a repeated frame at a join)", "frames")
    out_packets = packet_hashes(dst)
    if len(out_packets) != expected:
        raise SmartFallback(f"the output holds {len(out_packets)} video packets where the parts hold {expected}", "packets")
    dst_origin = origin(dst)
    offset, copied, decoded = 0, 0, 0
    for p in parts:
        n = p["frames"]
        at_out = pts[offset] - dst_origin - half
        if p["kind"] == "copy":
            source = packet_hashes(src, p["seek"], p["t"])
            if source != out_packets[offset:offset + n]:
                bad = next((i for i, (x, y) in enumerate(zip(source, out_packets[offset:offset + n])) if x != y),
                           min(len(source), n))
                raise SmartFallback(f"copied packet {bad} of the part from {p['start']:.3f}s differs from the source's",
                                    "packets")
            copied += n
            g = min(n, DECODE_CHECK_MAX_FRAMES)
            want = frame_hashes(src, p["start"] - half, g)
        else:
            g = n
            want = frame_hashes(p["path"], None, g)
        got = frame_hashes(dst, at_out, g)
        # a short list on both sides (a frame that did not decode) is not a match of g frames
        if len(want) != g or want != got:
            raise SmartFallback(f"the frames decoded from the output's {p['kind']} part at {pts[offset] - pts[0]:.3f}s "
                                f"differ from the {'source' if p['kind'] == 'copy' else 'encoded part'}", "decode")
        decoded += g
        offset += n
    out_params = stream_params(dst) or {}
    if out_params.get("time_base") != params.get("time_base"):
        raise SmartFallback(f"the output's time base is {out_params.get('time_base')}, the source's "
                            f"{params.get('time_base')}", "time_base")
    diff = mismatches(params, out_params)
    if diff:
        raise SmartFallback("the output's stream does not match the source: " + ", ".join(diff), "params_mismatch")
    return {"frames": expected, "grid_worst_seconds": round(worst, 6), "copied_packets_equal": copied,
            "frames_decoded_equal": decoded, "time_base": out_params.get("time_base")}
