#!/usr/bin/env python3
"""Cut a clip or several segments out of a video and (optionally) join them.

Lossless stream copy (-c copy) is preferred. Cuts snap to keyframes in that
mode, so if frame accuracy matters pass --accurate to re-encode. Multiple
segments are cut individually and joined by stream copy when the parts match in their codec
parameters; otherwise every segment is re-cut from the source into one re-encode.

Audio: a stream copy lands on a packet boundary (about 21 ms for AAC, one
demuxer block for WAV); --accurate decodes and trims to the sample. The output
extension picks the codec: -o out.wav writes PCM (never an AAC packet inside a
WAV), -o out.m4a writes AAC; an audio extension on a video input drops the
picture (mp4 -> wav extraction). The result reports `precision`
(packet / sample / codec_frame / frame) and the measured duration error, plus
`mode` (copy / accurate / hybrid -- "hybrid" means a lossless cut silently
re-encoded because the keyframe snap exceeded --tolerance), `keyframe_snapped`
(a stream copy end to end), `start_snapped` (measured: a copied start moved past a frame),
`reencode_reason`, `requested_start`/`requested_end` (or `requested_segments` for --segments),
`requested_duration`, `output_duration` and `duration_delta_seconds` -- so a
caller never has to trust "it probably cut where I asked" on faith.

A single-segment .mp4/.mov copy shifts its timestamps to zero (-avoid_negative_ts
make_zero), so the picture starts at the keyframe; --edit-list keeps the MP4 edit
list instead, which hides the keyframe's pre-roll so the picture starts at --start.

A re-encode uses x264 for an SDR source and x265 Main10 for an HDR or BT.2020 one, as every
editing tool does; --keep-hevc re-encodes an SDR HEVC source as HEVC (x265 8-bit BT.709, or
VideoToolbox under --hw), so a trimmed phone clip keeps its codec. --codec overrides both.

A source whose nominal and average frame rates differ is taken for variable-frame-rate and
re-encoded, as --accurate (--vfr-guard average, the default); its sampled packet timing is
reported in `vfr_check`. --vfr-guard sampled re-encodes only when that sampled timing is
variable or too short to judge, and --vfr-guard off keeps the copy with a note.

Examples:
  python3 cut.py input.mp4 --start 00:00:10 --end 00:00:25
  python3 cut.py input.mp4 --segments 0:05-0:12,1:00-1:20 -o highlights.mp4
  python3 cut.py input.mp4 --start 3.5 --duration 10 --accurate
  python3 cut.py talk.wav --start 1.2345 --end 2.3456 --accurate -o part.wav   # sample-exact
  python3 cut.py talk.mp4 --start 1:00 --end 2:00 -o part.wav                   # audio extraction
"""
import argparse
import contextlib
import json
import os
import sys
import tempfile
import zlib
from typing import List, Tuple

from _common import (beat_grid, snap_points, decode_pcm_mono, rms_envelope, BEAT_MIN_CONFIDENCE)
from _common import require_tool
from _common import sibling_temp, source_codec_video_args, STATE, add_common, apply_common, audio_codec_for, emit, aac_args, cfr_args, default_output, die, ffmpeg_base, info, is_audio_output, time_arg, probe, run, X264_PRESETS, keyframes_near, MissingFpsError, concat_list_line, place_output, refuse_output_is_input, fmt_secs, measure_frame_timing, dry_run_input_pending

# outputs whose re-encode dropped a subtitle/data stream (reported as dropped_non_av_streams)
DROPPED_STREAMS: List[str] = []
# keyframe timestamps found next to a requested cut that the tolerance turned into a re-encode
# (reported so the caller can choose a lossless cut at one of them next time)
NEAREST_KEYFRAMES: list = []
# --keep-hevc: an SDR HEVC source re-encodes as HEVC instead of H.264 (set by main())
KEEP_HEVC = False


def _t(value: str, fps, flag: str = "--segments") -> float:
    """time_arg() with the input's fps (SMPTE hh:mm:ss:ff, or @fps): the one parser every tool uses (1.9)."""
    return time_arg(value, flag, fps)


def parse_segments(spec: str, fps=None) -> List[Tuple[float, float]]:
    segs = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "-" not in raw:
            die(f"segment '{raw}' must look like START-END (e.g. 0:05-0:12)")
        a, b = raw.rsplit("-", 1)
        start, end = _t(a, fps), _t(b, fps)
        if start < 0:
            die(f"segment '{raw}': start must be >= 0")
        if end <= start:
            die(f"segment '{raw}': end must be after start")
        segs.append((start, end))
    if not segs:
        die("no segments given")
    return segs


def encode_args(meta: dict, dst: str, crf: int, preset: str) -> List[str]:
    """Codec arguments for a re-encoded cut: video + AAC into a video container, otherwise the codec
    the audio extension names (PCM for .wav, FLAC, MP3, AAC...) with no video stream."""
    if is_audio_output(dst) or not meta.get("video"):
        return ["-vn"] + audio_codec_for(dst)
    return video_encode_args(meta, crf, preset) + aac_args()


def video_encode_args(meta: dict, crf: int, preset: str) -> List[str]:
    return source_codec_video_args(meta, crf, preset, keep_hevc=KEEP_HEVC) + cfr_args(meta)


def copy_args(meta: dict, dst: str) -> List[str]:
    """Stream-copy arguments: everything into a video container, audio only into an audio extension."""
    if is_audio_output(dst) and meta.get("video"):
        return ["-vn", "-c:a", "copy"]
    args = ["-c", "copy"]
    if os.path.splitext(dst)[1].lower() in (".mp4", ".mov", ".m4v"):
        args += ["-movflags", "+faststart"]
    return args


LOSSLESS_AUDIO = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "flac"}


def precision_of(meta: dict, dst: str, reencoded: bool) -> str:
    """How exact the cut is, measured on what was written:

    packet      stream copy; the cut lands on a packet (audio) or keyframe (video) boundary
    sample      decoded audio trimmed to the sample and written losslessly (PCM / FLAC)
    codec_frame decoded audio trimmed to the sample, then framed by a lossy encoder (AAC 1024,
                MP3 1152, Opus 960 samples) which also adds its priming delay to the reported length
    frame       re-encoded video: the picture is frame-exact, the audio underneath is sample-trimmed
    """
    if not reencoded:
        return "packet"
    if is_audio_output(dst) or not meta.get("video"):
        codec = audio_codec_for(dst)[1]
        return "sample" if codec in LOSSLESS_AUDIO else "codec_frame"
    return "frame"


# The order `precision` values rank in, least exact first. It is a conservative order for this
# tool's segments (all cut from one source into one container), not a universal scale.
PRECISION_ORDER = ("packet", "codec_frame", "frame", "sample")


def least_exact(precisions: List[str]) -> str:
    return min(precisions, key=PRECISION_ORDER.index)


def report_precision(meta: dict, dst: str, reencoded: bool, outcomes: List[dict]) -> dict:
    """The run's precision keys from its segments' outcomes.

    precision         main's formula, unchanged: precision_of() for the whole run, so `packet` only
                      when nothing re-encoded (the join included)
    keyframe_snapped  precision == "packet": the run is a stream copy end to end, which lands on
                      keyframes and packets. Kept with its 2.x meaning; whether a copied START
                      really moved is start_snapped
    start_snapped     measured: true when a copied segment's picture starts more than a frame from
                      its requested start; false when every start is where asked (an edit list, a
                      start on a keyframe, an audio-only copy's packet seek) or everything
                      re-encoded; null when a copied start was not measured (--dry-run)
    least_exact_precision  the least exact segment's precision; differs from `precision` only for
                      an audio-only --segments join of copied and re-encoded parts (a video join
                      re-cuts every segment when any part re-encodes)
    segment_precision each segment's, for --segments (null for one segment)"""
    precision = precision_of(meta, dst, reencoded)
    snaps = [o.get("start_snapped") for o in outcomes]
    if any(s is True for s in snaps):
        start_snapped = True
    elif any(s is None for s in snaps):
        start_snapped = None
    else:
        start_snapped = False
    return {"precision": precision, "keyframe_snapped": precision == "packet", "start_snapped": start_snapped,
            "least_exact_precision": least_exact([o["precision"] for o in outcomes]),
            "segment_precision": [o["precision"] for o in outcomes] if len(outcomes) > 1 else None}


def _outcome(meta: dict, dst: str, reencoded: bool, reasons: List[str], **copy) -> dict:
    """One segment's outcome. start_snapped defaults to false: a re-encode starts where asked, and
    an audio-only copy seeks on the output side, to the packet; a video copy passes the measured
    value (copy_presentation), a --dry-run copy None."""
    out = {"reencoded": reencoded, "reasons": reasons, "precision": precision_of(meta, dst, reencoded),
           "start_snapped": False, "edit_list": False, "stored_preroll_seconds": None}
    out.update(copy)
    return out


EDIT_LIST_EXTS = (".mp4", ".mov", ".m4v")


def _with_notes(outcome: dict, notes: List[str]) -> dict:
    """An outcome with the notes of the attempt that led to it put first."""
    outcome["notes"] = list(notes) + list(outcome.get("notes") or [])
    return outcome


_ORIGINS: dict = {}


def file_origin(src: str) -> float:
    """The file's format start_time: the zero that -ss and segment times count from. Stream
    start_times are absolute, so subtract this to put them on the cut's clock. One probe per source."""
    if src not in _ORIGINS:
        proc = run([require_tool("ffprobe"), "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", src],
                   quiet=True, check=False)
        try:
            _ORIGINS[src] = float((proc.stdout or "").strip() or 0.0)
        except ValueError:
            _ORIGINS[src] = 0.0
    return _ORIGINS[src]


def source_skew(src: str, meta: dict, t: float) -> float:
    """How far the source's audio starts after its video at `t` on the cut's clock: a cut from
    `t` that keeps both streams where they were starts them this far apart (0 once both run)."""
    v, a = meta.get("video") or {}, meta.get("audio") or {}
    if v.get("start_time") is None or a.get("start_time") is None:
        return 0.0
    origin = file_origin(src)
    return max(a["start_time"] - origin, t) - max(v["start_time"] - origin, t)


def video_end(src: str, meta: dict):
    """Where the video stream ends on the cut's clock (seconds from the file's start), or None when
    the stream's length is unknown."""
    v = meta.get("video") or {}
    if not v.get("duration"):
        return None
    return (v.get("start_time") or 0.0) + v["duration"] - file_origin(src)


_SEEK_SHIFTS: dict = {}
# ffmpeg's dts heuristic: before a demuxer that does not seek by presentation time, an input -ss
# seeks this much earlier when a stream has a decode delay (B-frames); fftools ffmpeg_demux.c
DTS_HEURISTIC = 3.0 / 23


def seek_shift(src: str) -> float:
    """How much earlier than `-ss t` ffmpeg's input seek asks the demuxer for: DTS_HEURISTIC for a
    demuxer that does not seek by pts (Matroska, MPEG-TS...) when a stream has a decode delay, 0
    for MP4/MOV (AVFMT_SEEK_TO_PTS) or a source with no delay. One probe per source."""
    if src not in _SEEK_SHIFTS:
        proc = run([require_tool("ffprobe"), "-v", "error", "-show_entries", "format=format_name:stream=has_b_frames",
                    "-of", "json", src], quiet=True, check=False)
        try:
            doc = json.loads(proc.stdout or "") if proc.returncode == 0 else {}
            name = str((doc.get("format") or {}).get("format_name") or "")
            delay = any(int(st.get("has_b_frames") or 0) > 0 for st in doc.get("streams") or [])
        except (ValueError, TypeError, AttributeError):
            name, delay = "", False
        _SEEK_SHIFTS[src] = 0.0 if ("mov" in name.split(",") or not delay) else DTS_HEURISTIC
    return _SEEK_SHIFTS[src]


_LANDINGS: dict = {}


def seek_keyframe(src: str, t: float):
    """The keyframe a stream copy starting at `-ss t` begins from, as (pts, dts, first presented
    pts at or after t) in seconds on the cut's clock, or None when it cannot be read.

    Measured, not modelled: ffprobe -read_intervals seeks with the same avformat_seek_file call as
    ffmpeg's input -ss (to the file's start_time + t, less seek_shift()), and the copy starts at
    the first keyframe read after it, as ffmpeg drops the packets before it. A model ("the
    keyframe with the largest dts at or before t") was wrong both ways: the MP4 demuxer seeks
    over its raw decode times, ffprobe's dts plus the reorder delay, so on B-frame H.264 -ss 3.99
    landed on the keyframe at 2.0, not on the one at 4.0 (dts 3.933), while on a keyint-60 HEVC
    file -ss 9.9 began at the keyframe at 10.0 (dts 9.833). The read does not seek earlier than
    ffmpeg does: a seek before the file's start skips an edit-listed MP4's negative-pts keyframe.
    Cached on (src, t)."""
    key = (src, round(t, 6))
    if key in _LANDINGS:
        return _LANDINGS[key]
    origin = file_origin(src)
    target = origin + t - seek_shift(src)
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                "packet=pts_time,dts_time,flags", "-of", "json", "-read_intervals",
                f"{target:.6f}%{origin + t + 1.0:.6f}", src], quiet=True, check=False)
    try:
        packets = json.loads(proc.stdout or "")["packets"] if proc.returncode == 0 else []
    except (ValueError, KeyError, TypeError):
        packets = []
    landed, pts_all = None, []
    for p in packets if isinstance(packets, list) else []:
        try:
            pts = float(p["pts_time"]) - origin
        except (KeyError, TypeError, ValueError):
            continue
        if landed is None:
            if "K" not in str(p.get("flags", "")):
                continue   # ffmpeg's copy drops what comes before the first keyframe
            try:
                landed = (pts, float(p.get("dts_time", p["pts_time"])) - origin)
            except (TypeError, ValueError):
                landed = (pts, pts)
        pts_all.append(pts)
    if landed is None:
        _LANDINGS[key] = None
        return None
    # the first picture an edit list starting at t presents: the first frame at or after t
    later = [x for x in pts_all if x >= t - 1e-6]
    _LANDINGS[key] = (landed[0], landed[1], min(later) if later else None)
    return _LANDINGS[key]


def copy_presentation(t: float, key, edit_list: bool, fps) -> dict:
    """What a stream copy starting at `t` presents, from the keyframe it began at (seek_keyframe).
    With an MP4 edit list a keyframe at or before t is decoded but hidden (stored pre-roll) and the
    picture starts at t; a keyframe after t starts the picture late. Without one (Matroska, or a
    concat part cut with make_zero) the picture starts at the keyframe. start_snapped: the
    presented start is more than a frame from t (an unmeasured start counts as snapped)."""
    frame = 1.0 / fps if fps else 0.0
    if key is None:
        return {"start_snapped": True, "stored_preroll_seconds": None}
    k_pts, first = key[0], key[2]
    if first is None:
        # no packet at or after t in the probed window: where the picture starts is unmeasured
        return {"start_snapped": True, "stored_preroll_seconds": None}
    if edit_list and k_pts <= t + 1e-6:
        # hidden: the pictures decoded from the keyframe up to the first one presented
        return {"start_snapped": False, "stored_preroll_seconds": round(max(0.0, first - k_pts), 6)}
    return {"start_snapped": abs(k_pts - t) > frame + 1e-6, "stored_preroll_seconds": None}


def av_skew(out_meta: dict, edit_list_remedy: bool = False, expected: float = 0.0):
    """(seconds audio starts after video, warning note or None); None when either is missing.
    A lossless cut can start its streams apart -- Core Media HEVC once gave 3.7 s of sound with no
    picture from a run that exited 0 -- so a skew more than max(2 frames, 0.1 s) away from
    `expected` (the source's own skew at the cut's start: a track that starts late there, by
    design, is not a defect of the cut) is named. It is reported, not repaired:
    `edit_list_remedy` (a single MP4/MOV copy whose start snapped, cut without --edit-list)
    names --edit-list as the lossless way to start both streams at --start."""
    v, a = out_meta.get("video") or {}, out_meta.get("audio") or {}
    if v.get("start_time") is None or a.get("start_time") is None:
        return None, None
    skew = round(a["start_time"] - v["start_time"], 6)
    fps = v.get("fps") or 0
    limit = max(2.0 / fps if fps else 0.0, 0.1)
    if abs(skew - expected) <= limit:
        return skew, None
    first = "audio" if skew > 0 else "video"
    return skew, (f"the {'video' if first == 'audio' else 'audio'} starts {abs(skew):.3f}s before the {first}"
                  + (f" ({abs(expected):.3f}s in the source there)" if abs(expected) > 1e-3 else "")
                  + ": a stream copy began on packets the two streams do not share; re-run with --accurate "
                  "for a cut whose picture and sound start together"
                  + (", or with --edit-list to keep the lossless copy and hide the keyframe's pre-roll"
                     if edit_list_remedy else ""))


_PACKETS: dict = {}


def _packet_time(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _Packets(list):
    """video_packets' result: (pts, dts, keyframe) in decode order, plus `breaks`, the indices of
    packets after which a read window ended before the end of the file (what follows is a later
    window, not the next packet), and `spans`, each window's (lo, hi) with the range of packets
    read in it."""
    breaks: frozenset = frozenset()
    spans: tuple = ()


# video_packets reads [start - M, end + M] around each segment, M = max(PACKET_MARGIN, 2 x
# --tolerance), and widens M x4 up to PACKET_WIDENINGS times before reading the whole file
PACKET_MARGIN = 10.0
PACKET_WIDENINGS = 3


def packet_windows(segments, margin: float, total=None) -> tuple:
    """The merged read windows around `segments`, as (lo, hi) on the cut's clock: lo None from the
    file's start (never a seek: a seek to it skips an edit-listed MP4's negative-pts keyframe, as
    measure_frame_timing found), hi None to its end (`total`, the media duration)."""
    spans = sorted((s - margin, e + margin) for s, e in segments)
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return tuple((None if lo <= 0 else round(lo, 6), None if total and hi >= total else round(hi, 6))
                 for lo, hi in merged)


def _read_packets(src: str, windows: tuple):
    """The video packets of `src` in `windows` (packet_windows; ((None, None),) is the whole file),
    one ffprobe per window, or None when ffprobe fails. A window's seek lands on the keyframe
    before its start, so packets a previous window already read (dts not after its last) are
    dropped. Cached on (src, windows)."""
    key = (src, windows)
    if key in _PACKETS:
        return _PACKETS[key]
    origin = file_origin(src)
    packets, breaks, spans, last_dts = _Packets(), set(), [], None
    for lo, hi in windows:
        first, before = len(packets), last_dts
        cmd = [require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
               "packet=pts_time,dts_time,flags", "-of", "csv=p=0"]
        if lo is not None or hi is not None:
            cmd += ["-read_intervals", ("" if lo is None else f"{origin + lo:.6f}") + "%"
                    + ("" if hi is None else f"{origin + hi:.6f}")]
        proc = run(cmd + [src], quiet=True, check=False)
        if proc.returncode != 0:
            _PACKETS[key] = None
            return None
        for line in (proc.stdout or "").split():
            fields = line.split(",")
            if len(fields) < 3:
                continue
            pts, dts = _packet_time(fields[0]), _packet_time(fields[1])
            pts, dts = (None if pts is None else pts - origin), (None if dts is None else dts - origin)
            if before is not None and dts is not None and dts <= before + 1e-9:
                continue
            packets.append((pts, dts, "K" in fields[2]))
            if dts is not None:
                last_dts = dts
        if hi is not None and len(packets) > first:
            breaks.add(len(packets) - 1)
        spans.append((lo, hi, first, len(packets)))
    packets.breaks, packets.spans = frozenset(breaks), tuple(spans)
    _PACKETS[key] = packets or None
    return _PACKETS[key]


def _windows_cover(packets, segments) -> bool:
    """True when the packets read around each segment hold what the plan needs from them: the
    keyframe the copy lands on (the largest dts at or before the start; none at all only counts
    from the file's start), a whole GOP after it, and the first keyframe at or after the end
    with a whole GOP after that too (gop_is_open judges both) -- or the end of the file."""
    runs = [(lo, hi, packets[i0:i1]) for lo, hi, i0, i1 in packets.spans]
    for s, e in segments:
        run_ = next(((lo, hi, p) for lo, hi, p in runs if (lo is None or lo <= s) and (hi is None or hi >= e)), None)
        if run_ is None:
            return False
        lo, hi, part = run_
        keys = [(p[0], p[1]) for p in part if p[2] and p[0] is not None and p[1] is not None]
        landed = [k for k in keys if k[1] <= s + 1e-6]
        if not landed:
            if lo is None:
                continue
            return False
        k_dts = max(k[1] for k in landed)
        later = [k for k in keys if k[1] > k_dts + 1e-9]
        if not later:
            if hi is None:
                continue
            return False
        after = [k for k in later if k[0] >= e - 1e-6]
        if hi is None:
            continue
        if not after or not [k for k in after if k[1] > min(after)[1] + 1e-9]:
            return False
    return True


def video_packets(src: str, segments=None, tolerance: float = 0.5, total=None):
    """The video packets of `src` a --segments copy join is planned and checked against, in decode
    order, as (pts, dts, keyframe) on the cut's clock (a missing timestamp is None), or None
    when ffprobe cannot read them. Only windows around the segments are read (packet_windows),
    widened x4 up to PACKET_WIDENINGS times while one lacks what the plan needs (_windows_cover),
    and the whole file after that, so the cost follows the segments asked for, not the source's
    length; with no `segments`, the whole file."""
    if segments:
        margin = max(PACKET_MARGIN, 2 * tolerance)
        for _ in range(PACKET_WIDENINGS + 1):
            windows = packet_windows(segments, margin, total)
            if windows == ((None, None),):
                break
            packets = _read_packets(src, windows)
            if packets is None:
                return None
            if _windows_cover(packets, segments):
                return packets
            margin *= 4
    return _read_packets(src, ((None, None),))


def gop_is_open(packets, i: int) -> bool:
    """True when keyframe packets[i] starts an open GOP: a packet decoded after it, before the next
    keyframe, is presented before it (a leading picture, which needs the GOP before to decode). A
    missing timestamp there counts as open, and so does a GOP whose read window ended before its
    next keyframe (video_packets widens its windows so that the GOPs a plan judges are whole). A
    GOP the file ends in has been read to its last packet and is judged on those."""
    key = packets[i][0]
    breaks = getattr(packets, "breaks", ())
    if key is None or i in breaks:
        return True
    for j in range(i + 1, len(packets)):
        pts, dts, is_key = packets[j]
        if is_key:
            return False
        if pts is None or dts is None or pts < key - 1e-6 or j in breaks:
            return True
    return False


# a copied part stops before its end keyframe's packet by this much: -t compares decode
# timestamps, and ffprobe prints them rounded to the microsecond
_DTS_MARGIN = 1e-4


def reorders(packets) -> bool:
    """True when the source's frames reorder: some packet is presented before one decoded ahead of
    it (B-frames). A source that never reorders cuts exactly in decode order, so its --segments
    parts are cut as in every 2.x release (main()). Judged within each window video_packets read:
    the gap between two windows is not a reorder."""
    breaks = getattr(packets, "breaks", ())
    top = None
    for i, (pts, _dts, _key) in enumerate(packets):
        if pts is not None:
            if top is not None and pts < top - 1e-6:
                return True
            top = pts if top is None else max(top, pts)
        if i in breaks:
            top = None
    return False


def plan_part(packets, start: float, end: float, tolerance: float, vend, fps, snap_end: bool = True,
              landing=None) -> dict:
    """How the --segments part start-end is stream-copied for a concat-demuxer join.

    The copy begins at the keyframe `-ss start` lands on: `landing`, seek_keyframe()'s measurement,
    when it is one of `packets`' keyframes, otherwise the one with the largest dts at or before
    `start` (which the MP4 demuxer's seek over raw decode times does not always take: the join
    check is the backstop). The join presents from that keyframe: the concat demuxer does not apply the part's edit
    list start. The part ends at its end keyframe's DTS: an input -t stops in decode order, so
    ending at the keyframe's pts would carry that keyframe and the P-frame after it into the part.
    The end keyframe is the first one presented at or after `end` among those decoded after the
    landing (an earlier one would drop requested frames, and any decoded before the landing would
    give -t <= 0); one past `tolerance` re-encodes, reason "tolerance". With no keyframe after
    `end` (the end is in the video's last GOP) the end stays where asked and check_join judges
    the copy. A part that reaches the end of the video keeps -t end-start: nothing follows it to
    leak in. Without `snap_end` (a source whose frames do not reorder, or Matroska/MPEG-TS
    parts) the end is left where asked, as in every 2.x release; only the start is judged."""
    frame = 1.0 / fps if fps else 0.001
    keys = [(i, p[0], p[1]) for i, p in enumerate(packets) if p[2] and p[0] is not None and p[1] is not None]
    measured = ([k for k in keys if abs(k[1] - landing[0]) < 1e-5] if landing else [])
    landed = measured[:1] or [k for k in keys if k[2] <= start + 1e-6]
    if not landed and keys and (not getattr(packets, "spans", None) or packets.spans[0][0] is None):
        # a video stream that starts after `start` (its sound leads it): the seek lands on its
        # first keyframe, which the tolerance judges like any other
        landed = keys[:1]
    plan = {"reason": None, "start": start, "t": end - start, "start_index": None, "start_pts": None,
            "end_index": None, "end_pts": None, "end_bound": end}
    if not landed:
        plan["reason"] = "tolerance"
        return plan
    si, s_pts, s_dts = max(landed, key=lambda k: k[2])
    plan.update(start_index=si, start_pts=s_pts)
    within = (lambda off: True) if tolerance < 0 else (lambda off: off < tolerance)
    if not within(abs(s_pts - start)):
        plan["reason"] = "tolerance"
        return plan
    if vend is not None and end >= vend - frame / 2:
        plan["end_bound"] = None
        return plan
    if not snap_end:
        return plan
    after = [k for k in keys if k[2] > s_dts + 1e-9 and k[1] >= end - 1e-6]
    if not after:
        # the end is in the video's last GOP: no keyframe to snap it to, so the end stays where
        # asked and check_join judges the copy (a B-frame part cut mid-GOP in decode order usually
        # fails it, and the join is re-cut) -- not a tolerance miss, even under --tolerance -1
        return plan
    ei, e_pts, e_dts = min(after, key=lambda k: k[1])
    if not within(e_pts - end):
        plan["reason"] = "tolerance"
        return plan
    t = e_dts - start - _DTS_MARGIN
    if t < 0.001:
        # the start sits within a millisecond of the end keyframe's dts: no packet to copy
        plan["reason"] = "tolerance"
        return plan
    plan.update(t=t, end_index=ei, end_pts=e_pts, end_bound=e_pts)
    return plan


def hidden_preroll_start(packets, plans, edit_listed: bool):
    """The 1-based number of the first part after the first whose start is not on a keyframe
    presented at or before it, for edit-listed (.mp4/.mov) parts of a source whose frames reorder;
    None otherwise. Such a part stores the frames from its keyframe to its start as hidden
    pre-roll, which the concat demuxer crushes into sub-millisecond steps at the join (measured on
    every source shape tried), so the join is re-cut without trying the copy."""
    if not edit_listed:
        return None
    for i, plan in enumerate(plans):
        if i and not plan["reason"] and plan["start_pts"] is not None and plan["start_pts"] < plan["start"] - _DTS_MARGIN:
            return i + 1
    return None


def open_join_key(packets, plans):
    """The pts of the first keyframe a stream-copy join of the planned parts cannot cross, or None.
    An open END keyframe: its leading pictures belong to the part but decode after the keyframe,
    so a part cut in decode order loses them. An open START keyframe after the first part: the
    decoder drops leading pictures only at the start of a stream, so after a join they would decode
    against the previous part's frames. Parts that re-encode anyway are skipped."""
    for i, plan in enumerate(plans):
        if plan["reason"]:
            continue
        if i and gop_is_open(packets, plan["start_index"]):
            return plan["start_pts"]
        if plan["end_index"] is not None and gop_is_open(packets, plan["end_index"]):
            return plan["end_pts"]
    return None


def stream_packet_times(path: str, stream: str, entry: str, limit: int = None) -> list:
    """One timestamp field (pts_time, duration_time) of every packet of the first `stream` ("v" or
    "a") in `path`, or of its first `limit` packets; a missing value is None. [] when there is no
    such stream or ffprobe fails."""
    cmd = [require_tool("ffprobe"), "-v", "error", "-select_streams", f"{stream}:0", "-show_entries", f"packet={entry}",
           "-of", "csv=p=0"] + (["-read_intervals", f"%+#{limit}"] if limit else []) + [path]
    proc = run(cmd, quiet=True, check=False)
    if proc.returncode != 0:
        return []
    return [_packet_time(line.split(",")[0]) for line in (proc.stdout or "").split()]


def expected_packets(packets, ranges) -> int:
    """How many source video packets the join's parts present: those with lo <= pts < hi in each
    (lo, hi) range, hi None for a part that runs to the end of the video."""
    return sum(1 for lo, hi in ranges for pts, _, _ in packets
               if pts is not None and pts >= lo - 1e-6 and (hi is None or pts < hi - 1e-6))


def check_join(out_pts, counts, fps, cfr: bool, predicted=None) -> dict:
    """The joined file measured, not predicted: its video packet count against the source's
    (`counts`, one per part, from expected_packets), and with constant frame timing every
    presentation step. A step inside a part is a frame (more than half, less than one and a half).
    The step at a join is the one `predicted` from the parts (predicted_join_steps), within a
    millisecond: the frame before a join is shown for its frame plus the time the concat
    demuxer leaves between the parts' pictures, which is not a fixed bound -- 56.7 ms at 30 fps
    for an exact no-B-frame join, one audio frame or more past a frame for PCM -- and a bound
    loose enough for every source let a hole of one audio packet through. Without a prediction
    a join step is held to the interior bound."""
    expected = sum(counts)
    pts = sorted(p for p in out_pts if p is not None)
    ok = len(out_pts) == expected and len(pts) == len(out_pts)
    max_step = None
    if cfr and fps:
        frame = 1.0 / fps
        gaps = [b - a for a, b in zip(pts, pts[1:])]
        if gaps:
            max_step = round(max(gaps), 6)
            joins = {}
            if ok and predicted:
                at = 0
                for j, n in enumerate(counts[:-1]):
                    at += n
                    if 0 < at < len(pts) and j < len(predicted) and predicted[j] is not None:
                        joins[at - 1] = predicted[j]
            ok = ok and all(abs(g - joins[i]) <= JOIN_STEP_SLACK and g > frame / 2 if i in joins
                            else frame / 2 < g < 1.5 * frame for i, g in enumerate(gaps))
    return {"packets": len(out_pts), "expected_packets": expected, "max_step_seconds": max_step, "ok": ok}


def _adts_payload(data: str) -> bytes:
    """A packet's bytes from ffprobe's -show_data hex dump, without the ADTS header an MPEG-TS AAC
    packet carries (7 bytes, 9 with a CRC): what aac_adtstoasc leaves when the packet is copied
    into MP4, MOV or Matroska."""
    raw = bytearray()
    for line in str(data or "").strip().splitlines():
        _, _, rest = line.partition(":")
        raw += bytes.fromhex(rest.strip().split("  ")[0].replace(" ", ""))
    if len(raw) >= 7 and raw[0] == 0xFF and (raw[1] & 0xF6) == 0xF0:
        return bytes(raw[7 if raw[1] & 1 else 9:])
    return bytes(raw)


def audio_packet_hashes(path: str, lo=None, hi=None, stream: str = "a:0", strip_adts: bool = False) -> list:
    """(pts, CRC32) of the `stream` audio packets of `path`, on its own raw clock, from `lo` to `hi`
    (absolute seconds; None = the file's start or end: a read from the start never seeks). With
    `strip_adts` each packet is hashed without its ADTS header (_adts_payload; zlib's CRC32 is
    ffprobe's), so an MPEG-TS source's AAC matches the same packets copied out of it. [] when
    there is no such stream or ffprobe fails."""
    cmd = [require_tool("ffprobe"), "-v", "error", "-select_streams", stream]
    if strip_adts:
        cmd += ["-show_entries", "packet=pts_time,data", "-show_data", "-of", "json"]
    else:
        cmd += ["-show_entries", "packet=pts_time,data_hash", "-show_data_hash", "CRC32", "-of", "csv=p=0"]
    if lo is not None or hi is not None:
        cmd += ["-read_intervals", ("" if lo is None else f"{lo:.6f}") + "%" + ("" if hi is None else f"{hi:.6f}")]
    proc = run(cmd + [path], quiet=True, check=False)
    out = []
    if proc.returncode != 0:
        return out
    if strip_adts:
        try:
            packets = json.loads(proc.stdout or "").get("packets") or []
        except (ValueError, AttributeError):
            return out
        for p in packets:
            pts = _packet_time(p.get("pts_time")) if isinstance(p, dict) else None
            if pts is not None and p.get("data"):
                out.append((pts, "CRC32:%08x" % zlib.crc32(_adts_payload(p["data"]))))
        return out
    for line in (proc.stdout or "").split():
        fields = line.split(",")
        pts = _packet_time(fields[0])
        crc = next((f for f in fields[1:] if f.startswith("CRC32:")), None)
        if pts is not None and crc:
            out.append((pts, crc))
    return out


def copied_audio_streams(meta: dict, joined: str) -> List[str]:
    """The source audio streams (`a:N`) a join's sound may have been copied from: those with the
    codec, channel count and sample rate of the joined file's audio. FFmpeg's default selection
    copies the stream with the most channels, which need not be a:0 (a stereo AAC a:0 beside a
    6-channel PCM a:1 copied a:1), so the check must hash the stream that was copied."""
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                "stream=codec_name,channels,sample_rate", "-of", "json", joined], quiet=True, check=False)
    try:
        st = (json.loads(proc.stdout or "").get("streams") or [{}])[0] if proc.returncode == 0 else {}
        shape = (st.get("codec_name"), int(st.get("channels") or 0), int(st.get("sample_rate") or 0))
    except (ValueError, TypeError, AttributeError, IndexError):
        return ["a:0"]
    found = [f"a:{a['index']}" for a in meta.get("audio_streams") or []
             if (a.get("codec"), a.get("channels") or 0, a.get("sample_rate") or 0) == shape]
    return found or ["a:0"]


# check_join_audio: a run of AUDIO_RUN packets, from AUDIO_SKIP seconds into a part and starting
# within AUDIO_REACH of it, is looked for within AUDIO_SEARCH of where it belongs in the source; a
# part whose sound is more than AUDIO_SYNC_LIMIT off its picture fails the join
AUDIO_RUN, AUDIO_SKIP, AUDIO_REACH, AUDIO_SEARCH, AUDIO_SYNC_LIMIT = 8, 0.25, 2.0, 0.5, 0.005


def check_join_audio(src: str, joined: str, starts, counts, out_pts=None, streams=("a:0",),
                     strip_adts: bool = False) -> dict:
    """Each copied part's sound against its picture in the joined file, by matching audio packets
    with the source's (CRC32). A part's video moved by (its first frame in the join - its start
    keyframe in the source), and its sound by (an audio packet's time in the join - the same
    packet's time in the source); the two must agree within AUDIO_SYNC_LIMIT. The packet is the
    first of AUDIO_RUN consecutive ones, from AUDIO_SKIP into the part, whose run appears exactly
    once within AUDIO_SEARCH of where the video's move puts it. A part with no such run (digital
    silence, a periodic tone, a part too short) is unmeasured, not failed. `starts` are the
    parts' start keyframes (pts on the cut's clock), `counts` their video packets in the join,
    `out_pts` the join's video packet times when the caller has read them. `streams` are the
    source streams the sound may have come from (copied_audio_streams), tried in turn until one
    measures a part; `strip_adts` hashes the source's packets without their ADTS headers.
    Returns {audio_offset_ms: per part, sound minus picture (+ = sound late, null = unmeasured),
    audio_parts_checked, audio_ok}. A B-frame H.264 + PCM .mov join measured 0 / +16.0 / +53.3 ms
    and passed the video check; clean joins measure under 1 ms."""
    out_a = audio_packet_hashes(joined)
    if out_pts is None:
        out_pts = stream_packet_times(joined, "v", "pts_time")
    vpts = sorted(p for p in out_pts if p is not None)
    if not out_a or len(vpts) != sum(counts):
        return {"audio_offset_ms": None, "audio_parts_checked": 0, "audio_ok": True}
    origin = file_origin(src)
    offsets: list = []
    for stream in streams:
        offsets, first = [], 0
        for k, n in zip(starts, counts):
            v_out = vpts[first]
            nxt = vpts[first + n] if first + n < len(vpts) else float("inf")
            first += n
            vshift = v_out - (k + origin)
            lo = k + origin - 1.0
            src_a = audio_packet_hashes(src, None if lo <= origin else lo, k + origin + AUDIO_REACH + 2 * AUDIO_SEARCH,
                                        stream=stream, strip_adts=strip_adts)
            by_hash: dict = {}
            for j, (_, crc) in enumerate(src_a):
                by_hash.setdefault(crc, []).append(j)
            found = None
            for m, (p, crc) in enumerate(out_a):
                if p < v_out + AUDIO_SKIP:
                    continue
                if p > v_out + AUDIO_REACH or m + AUDIO_RUN > len(out_a) or out_a[m + AUDIO_RUN - 1][0] >= nxt:
                    break
                run_ = [h for _, h in out_a[m:m + AUDIO_RUN]]
                hits = [j for j in by_hash.get(crc, ()) if abs(src_a[j][0] - (p - vshift)) <= AUDIO_SEARCH
                        and [h for _, h in src_a[j:j + AUDIO_RUN]] == run_]
                if len(hits) == 1:
                    found = (p - src_a[hits[0]][0]) - vshift
                    break
            offsets.append(None if found is None else round(found * 1000, 2) + 0.0)
        if any(o is not None for o in offsets):
            break
    measured = [o for o in offsets if o is not None]
    return {"audio_offset_ms": offsets, "audio_parts_checked": len(measured),
            "audio_ok": all(abs(o) <= AUDIO_SYNC_LIMIT * 1000 for o in measured)}


def cut_one(src: str, start: float, end: float, dst: str, reencode: bool, crf: int, preset: str, tolerance: float = 0.5, meta: dict = None,
            _reasons: List[str] = None, edit_list_ok: bool = False, copy_t: float = None) -> dict:
    """Cut one segment. Returns its outcome: {reencoded, reasons, precision, start_snapped, ...}, where
    `reasons` lists why THIS segment re-encoded on its own (pcm_container / copy_failed / tolerance);
    the caller adds the reasons that forced every segment (requested, codec, vfr).

    `edit_list_ok` (--edit-list) keeps the edit list a single MP4/MOV copy writes instead of
    -avoid_negative_ts make_zero; off, the copy is cut and judged as in every 2.x release.

    `copy_t` is a --segments part planned by plan_part: copied for -t copy_t (to its end
    keyframe's dts), keeping the edit list an MP4/MOV copy writes, and not judged by its length
    here, since plan_part judged each of its ends."""
    reasons = list(_reasons or [])
    dur = end - start
    meta = meta or probe(src)
    audio_only = is_audio_output(dst) or not meta.get("video")
    if not reencode and audio_only and audio_codec_for(dst)[1].startswith("pcm") and not str((meta.get("audio") or {}).get("codec", "")).startswith("pcm"):
        info(f"{(meta.get('audio') or {}).get('codec')} packets cannot be copied into a PCM container; decoding to PCM")
        reencode = True
        reasons.append("pcm_container")
    edit_list = False
    notes: List[str] = []
    if reencode:
        if is_audio_output(dst) or not meta.get("video"):
            # -ss before -i seeks, then decoding discards samples up to the exact start
            # (accurate_seek); atrim bounds the decoded stream to the requested length at sample
            # resolution.
            cmd = ffmpeg_base() + ["-ss", f"{start:.6f}", "-i", src, "-t", f"{dur:.6f}"]
            cmd += ["-af", f"atrim=end={dur:.6f},asetpts=PTS-STARTPTS"]
        else:
            # Seek SEEK_MARGIN early, then drop the margin on the output side, which decodes and
            # discards it from both streams alike. An input seek straight to `start` can land (the
            # MP4 demuxer seeks over its raw decode times) on a keyframe whose picture comes after
            # `start` and lose the frames before it (-ss 9.9 on a B-frame HEVC file began at 10.0).
            m = min(SEEK_MARGIN, start)
            cmd = ffmpeg_base() + ["-ss", f"{start - m:.6f}", "-i", src, "-ss", f"{m:.6f}", "-t", f"{dur:.6f}"]
        # ffmpeg's default stream selection also picks one subtitle stream; a re-encode cannot
        # trim it (the cues kept their timestamps and the container grew to 2 s for a 1 s cut,
        # sweep F2), so the re-encode carries video/audio only and the result says so
        cmd += ["-sn", "-dn"]
        if meta.get("subtitle_streams") or meta.get("data_streams"):
            DROPPED_STREAMS.append(dst)
        cmd += encode_args(meta, dst, crf, preset) + ["-avoid_negative_ts", "make_zero", dst]
    elif audio_only:
        # output-side seek: an input seek on a video file lands on the previous video keyframe and on
        # FLAC/MP3 on a coarse index; reading from the start and dropping packets is exact to the packet
        cmd = ffmpeg_base() + ["-i", src, "-ss", f"{start:.6f}", "-t", f"{dur:.6f}"] + copy_args(meta, dst) + ["-avoid_negative_ts", "make_zero", dst]
    else:
        # With --edit-list a single MP4/MOV output keeps the edit list the plain copy writes: the
        # keyframe's pre-roll is stored but hidden, so the picture and the sound start at `start`.
        # make_zero (the default, as in every 2.x release) shifts the timestamps instead and shows
        # the pre-roll -- on Core Media HEVC, 3.7 s of sound with no picture from a run that exited
        # 0, which av_start_skew_seconds and a note report. A planned concat part keeps it: the concat
        # demuxer ignores where the edit list starts (it shows the pre-roll) but places the next
        # part by its length, which make_zero parts got wrong by the B-frame reorder delay.
        # Other concat parts (Matroska, MPEG-TS) keep make_zero.
        edit_list = (edit_list_ok or copy_t is not None) and os.path.splitext(dst)[1].lower() in EDIT_LIST_EXTS
        cmd = (ffmpeg_base() + ["-ss", f"{start:.6f}", "-i", src, "-t", f"{dur if copy_t is None else copy_t:.6f}"]
               + copy_args(meta, dst) + ([] if edit_list else ["-avoid_negative_ts", "make_zero"]) + [dst])
    proc = run(cmd, check=False)
    if proc.returncode != 0:
        if not reencode:
            info("stream copy failed, falling back to re-encode")
            return cut_one(src, start, end, dst, True, crf, preset, tolerance, meta, reasons + ["copy_failed"], edit_list_ok)
        die(f"ffmpeg failed:\n{proc.stderr.strip()}", kind="ffmpeg")
    if not reencode and tolerance >= 0 and not STATE.dry_run and copy_t is None:
        out_meta = probe(dst)
        got = out_meta.get("duration") or 0.0
        vdur, fps = (out_meta.get("video") or {}).get("duration"), (meta.get("video") or {}).get("fps")
        if edit_list and not audio_only and vdur and fps and abs(got - vdur) > 1.0 / fps:
            # the container's length counts the longer track; the tolerance is about the picture.
            # Only under --edit-list: the default judges the container, as every 2.x release did
            msg = f"the container is {got:.3f}s but its video {vdur:.3f}s; the cut was judged by the video"
            info(msg)
            notes.append(msg)
            got = vdur
        if abs(got - dur) >= tolerance and edit_list and (copy_presentation(start, seek_keyframe(src, start), True, fps)["stored_preroll_seconds"] is not None):
            # the edit list started the picture at `start`: only the END is off (it lands on a
            # packet boundary), and no other --start would change that
            info(f"the stream copy starts where asked but its end landed {got - dur:+.2f}s from the requested "
                 f"length (> {tolerance:.2f}s tolerance); re-encoding this segment for accuracy")
            return _with_notes(cut_one(src, start, end, dst, True, crf, preset, tolerance, meta, reasons + ["tolerance"], edit_list_ok), notes)
        if abs(got - dur) >= tolerance:  # a snap of exactly the tolerance is not "within" it (sweep F20)
            near = keyframes_near(src, start)
            alt = ""
            if near:
                closest = min(near, key=lambda k: abs(k - start))
                alt = (f"; for a lossless cut move --start to a keyframe (nearest: {closest:.3f}s"
                       + (f", others within 5 s: {', '.join(f'{k:.3f}' for k in near if k != closest)}" if len(near) > 1 else "") + ")")
                NEAREST_KEYFRAMES.extend(k for k in near if k not in NEAREST_KEYFRAMES)
            info(f"stream copy landed on a keyframe {abs(got - dur):.2f}s away from the requested cut "
                 f"(> {tolerance:.2f}s tolerance); re-encoding this segment for accuracy{alt}")
            return _with_notes(cut_one(src, start, end, dst, True, crf, preset, tolerance, meta, reasons + ["tolerance"], edit_list_ok), notes)
    if reencode or audio_only:
        return _outcome(meta, dst, reencode, reasons)
    if STATE.dry_run:
        # the planned copy: whether it keeps an edit list is known; where it lands is not
        return _outcome(meta, dst, False, reasons, edit_list=edit_list and edit_list_ok, start_snapped=None)
    fps = (meta.get("video") or {}).get("fps")
    # a concat part's edit list does not hide its pre-roll in the join, so it presents from the keyframe
    shown = edit_list and edit_list_ok
    key = seek_keyframe(src, start)
    return _outcome(meta, dst, False, reasons, edit_list=shown, notes=notes, landed_pts=key[0] if key else None,
                    **copy_presentation(start, key, shown, fps))


# The most segments one fallback ffmpeg call opens: every segment is its own input (a file handle,
# a demuxer and a decoder each), and macOS shells default to 256 open files.
JOIN_CHUNK = 32
# how far before a segment the fallback seeks, so a start inside the B-frame reorder delay before a
# keyframe still decodes from the keyframe BEFORE it
SEEK_MARGIN = 1.0
# codecs whose configuration travels in the packets, so a part with no extradata is not missing any
IN_BAND_CONFIG = ("mp3", "mp2")
TS_EXTS = (".ts", ".m2ts", ".mts")
_SIG_FIELDS = {"video": ("codec_name", "profile", "pix_fmt", "width", "height", "r_frame_rate", "time_base",
                         "sample_aspect_ratio", "color_transfer", "color_primaries"),
               "audio": ("codec_name", "profile", "sample_rate", "channels", "time_base")}


_PARTS: dict = {}


def _part_probe(path: str):
    """ffprobe's streams and format of a cut part, with extradata hashes; None when it cannot be
    read. One probe per part serves join_signature and predicted_join_steps."""
    if path not in _PARTS:
        proc = run([require_tool("ffprobe"), "-v", "error", "-show_data_hash", "sha256", "-show_streams", "-show_format",
                    "-of", "json", path], quiet=True, check=False)
        try:
            doc = json.loads(proc.stdout or "") if proc.returncode == 0 else None
        except ValueError:
            doc = None
        _PARTS[path] = doc if isinstance(doc, dict) and isinstance(doc.get("streams"), list) else None
    return _PARTS[path]


def join_signature(path: str):
    """What a stream-copy join needs to be identical across parts: each stream's type, codec
    parameters, rotation and extradata hash. None when ffprobe cannot read the part."""
    doc = _part_probe(path)
    if doc is None:
        return None
    sig = []
    for st in doc["streams"]:
        kind = st.get("codec_type")
        entry = {"type": kind, "extradata_hash": st.get("extradata_hash")}
        entry.update({f: st.get(f) for f in _SIG_FIELDS.get(kind, ("codec_name",))})
        if kind == "video":
            entry["rotation"] = next((sd.get("rotation") for sd in st.get("side_data_list") or []
                                      if "rotation" in sd), None)
        sig.append(entry)
    return sig


# how far a measured join step may be from the predicted one: ffprobe prints the parts' times
# to the microsecond, and a time base coarser than that (Matroska's 1 ms) rounds each of them
JOIN_STEP_SLACK = 0.001


def predicted_join_steps(parts) -> list:
    """For each join of `parts`, the presentation step from the last frame of one part to the
    first of the next, as the concat demuxer places them: the next part starts where this one's
    container ends, so the step is (this part's container end - its last frame's pts) + (the next
    part's first frame's pts - its container start), read from the parts' own packets (Matroska
    stores no stream durations). None for a join whose parts' times are unknown. On an exact
    no-B-frame join (0-1.8,4-6 at 30 fps) that is 33.3 + 13.3 + 10.0 = 56.7 ms, what the joined
    file showed."""
    def times(path):
        doc = _part_probe(path)
        pts = [p for p in stream_packet_times(path, "v", "pts_time") if p is not None]
        try:
            fmt = (doc or {}).get("format") or {}
            c_start, c_dur = float(fmt["start_time"]), float(fmt["duration"])
        except (KeyError, TypeError, ValueError):
            return None
        return (c_start, c_start + c_dur, min(pts), max(pts)) if pts else None
    spans = [times(p) for p in parts]
    return [None if a is None or b is None else (a[1] - a[3]) + (b[2] - b[0]) for a, b in zip(spans, spans[1:])]


def signatures_match(sigs: list, ext: str) -> bool:
    """True when every part can be joined by stream copy: same streams in the same order with the
    same parameters. A missing extradata hash only matches another missing one where the codec (or
    an MPEG-TS output) carries its configuration in-band -- PCM has none at all."""
    if not sigs or any(sig is None for sig in sigs):
        return False
    first = sigs[0]
    for sig in sigs[1:]:
        if len(sig) != len(first):
            return False
        for a, b in zip(first, sig):
            if {k: v for k, v in a.items() if k != "extradata_hash"} != {k: v for k, v in b.items() if k != "extradata_hash"}:
                return False
            ha, hb = a.get("extradata_hash"), b.get("extradata_hash")
            if ha or hb:
                if ha != hb:
                    return False
            else:
                codec = str(a.get("codec_name") or "")
                if not (codec.startswith("pcm_") or codec in IN_BAND_CONFIG or ext in TS_EXTS):
                    return False
    return True


def _fraction_rate(text: str) -> float:
    """"30000/1001" or "30" as a number."""
    num, _, den = str(text).partition("/")
    return float(num) / float(den or 1)


def _grid_at_or_after(t: float, v0: float, rate: float) -> float:
    """The time of the first frame at or after `t` on a constant-rate grid starting at `v0`."""
    import math
    return v0 + math.ceil((t - v0) * rate - 1e-6) / rate


def _join_chunk(src: str, segments: List[Tuple[float, float]], dst: str, meta: dict, crf: int, preset: str,
                has_v: bool, intermediate: bool = False, vend=None, hold=frozenset(), first: int = 0) -> List[str]:
    """Re-cut `segments` from the source into one file through the concat filter, returning the codec
    arguments it encoded with. Each segment is
    its own seeked input, so both of its streams start at the segment's origin (0); neither is
    rebased on its own, which would drop a real A/V offset -- the audio is padded to the origin
    instead. Both streams are cut to the same length so the next segment starts where this ends.

    An `intermediate` chunk keeps its audio as PCM, so the chunks join with no encoder priming
    between them and the audio is encoded once, for the final file."""
    has_a = bool(meta.get("audio"))
    cmd = ffmpeg_base()
    graph, pads = [], ""
    video = meta.get("video") or {}
    rate_arg = video.get("r_frame_rate") if has_v else None
    try:
        rate = _fraction_rate(rate_arg) if rate_arg else (video.get("fps") or 0.0)
    except (ValueError, ZeroDivisionError):
        rate = video.get("fps") or 0.0
    v0 = (video.get("start_time") or 0.0) - file_origin(src) if has_v and rate else 0.0
    for i, (s, e) in enumerate(segments):
        d = e - s
        # Seek SEEK_MARGIN early and trim to the exact start. The MP4 demuxer seeks over its raw
        # decode times, so a start just before a keyframe (within the B-frame reorder delay) can
        # land on that keyframe and lose its leading frames -- measured: -ss 9.9 on a keyint-60
        # HEVC file began at 10.0 (seek_keyframe measures where a copy lands). Likewise an input -t stops reading at s+d in decode order and would drop
        # B-frames that display inside the segment, so it reads a second past the end.
        m = min(SEEK_MARGIN, s)
        cmd += ["-ss", f"{s - m:.6f}", "-t", f"{m + d + 1.0:.6f}", "-i", src]
        a, b, half = m, m + d, 0.0
        if has_v and rate:
            # Both streams are cut on the source's frame grid: from the first frame at or after the
            # start to the first at or after the end, which are the frames the segment holds. A
            # segment starting between frames otherwise placed its pictures half a frame off the
            # output's grid, and the constant-rate output duplicated one (65 frames for 64 on
            # FFmpeg 6.1). The video trim sits half a frame before each grid point, so no FFmpeg
            # version rounds a frame on the boundary in or out.
            a = m + (_grid_at_or_after(s, v0, rate) - s)
            b = m + (_grid_at_or_after(e, v0, rate) - s)
            half = 0.5 / rate
        # both streams shift by the same constant, so an offset between them (audio that starts
        # late) survives; the audio is then padded to the segment's origin
        if has_v:
            # a segment that runs past the video's end holds its last frame for the sound (main()
            # has already ended one that ran less than a frame past it at the video's end): the
            # concat filter starts the next segment after the longer stream, so a short picture
            # would leave a hole in the video there
            pad = f"tpad=stop_mode=clone:stop_duration={e - vend + 1.0:.6f}," if first + i in hold else ""
            graph.append(f"[{i}:v:0]{pad}trim=start={a - half:.6f}:end={b - half:.6f},setpts=PTS-{a:.6f}/TB[v{i}]")
            pads += f"[v{i}]"
        if has_a:
            graph.append(f"[{i}:a:0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-{a:.6f}/TB,"
                         f"aresample=async=1:first_pts=0[a{i}]")
            pads += f"[a{i}]"
    outs = ("[v]" if has_v else "") + ("[a]" if has_a else "")
    graph.append(f"{pads}concat=n={len(segments)}:v={int(has_v)}:a={int(has_a)}{outs}")
    cmd += ["-filter_complex", ";".join(graph)]
    for pad in ("[v]" if has_v else None, "[a]" if has_a else None):
        if pad:
            cmd += ["-map", pad]
    if intermediate:
        codec = (video_encode_args(meta, crf, preset) if has_v else ["-vn"]) + ["-c:a", "pcm_s24le"]
    else:
        codec = encode_args(meta, dst, crf, preset)
    # the source's rate, stated: FFmpeg 7.0 encoded the trimmed, concatenated pictures at 25 fps
    # and dropped frames to fit (98 frames for 117 at 30 fps)
    rate_out = ["-r", rate_arg] if has_v and rate_arg and rate and "-r" not in codec else []
    cmd += ["-sn", "-dn"] + codec + rate_out + [dst]
    run(cmd)
    return codec


def join_from_source(src: str, segments: List[Tuple[float, float]], dst: str, meta: dict, crf: int, preset: str, tmp: str) -> None:
    """The join fallback: every segment re-cut from the source and encoded once. The parts are not
    reused -- a copied part carries keyframe pre-roll and an audio tail the concat filter would
    turn into a gap, and a re-encode keeps nothing lossless anyway."""
    if meta.get("subtitle_streams") or meta.get("data_streams"):
        DROPPED_STREAMS.append(dst)
    has_v = bool(meta.get("video")) and not is_audio_output(dst)
    vend = video_end(src, meta) if has_v else None
    # the segments whose picture ends before their sound; the last one is left as the source had it,
    # since no join follows it
    # (by position: a repeat of a held segment in last place is still the last one)
    hold = frozenset(k for k, (_, e) in enumerate(segments[:-1]) if vend is not None and e > vend + 1e-6)
    if len(segments) <= JOIN_CHUNK:
        _join_chunk(src, segments, dst, meta, crf, preset, has_v, vend=vend, hold=hold)
        return
    ext = os.path.splitext(dst)[1] or ".mp4"
    # Matroska chunks with PCM audio: no edit lists and no AAC priming to carry into the join (MP4
    # chunks measured the video 23 ms late against the audio after a copy concat)
    # the chunks' codec tag (hvc1), which a stream copy out of Matroska does not carry into an MP4
    # (it writes hev1, which Apple players refuse)
    tag: List[str] = []

    def encode_chunks() -> List[str]:
        out = []
        for k in range(0, len(segments), JOIN_CHUNK):
            chunk = os.path.join(tmp, f"chunk{k // JOIN_CHUNK:03d}.mkv")
            args = _join_chunk(src, segments[k:k + JOIN_CHUNK], chunk, meta, crf, preset, has_v, intermediate=True,
                               vend=vend, hold=hold, first=k) or []
            if "-tag:v" in args:
                tag[:] = args[args.index("-tag:v"):args.index("-tag:v") + 2]
            out.append(chunk)
        return out

    chunks = encode_chunks()
    if not STATE.dry_run and STATE.hw and not signatures_match([join_signature(c) for c in chunks], ".mkv"):
        # VideoToolbox refused some chunk and run() re-encoded that one on the CPU, so the chunks
        # no longer match: encode them all on the CPU rather than refuse a join that can be made
        info("the GPU refused part of this join and the chunks came out mixed; re-encoding every chunk on the CPU")
        STATE.hw_notes.append("the --segments join fell back to the CPU for every chunk after VideoToolbox refused one")
        # off for these encodes only: the result still reports that the GPU was asked for
        STATE.hw = False
        try:
            chunks = encode_chunks()
        finally:
            STATE.hw = True
    if not STATE.dry_run and not signatures_match([join_signature(c) for c in chunks], ".mkv"):
        die("the re-encoded chunks of this join came out with different stream parameters, so they "
            f"cannot be joined safely; cut at most {JOIN_CHUNK} segments per run and join the results "
            "with join.py", kind="ffmpeg")
    listfile = os.path.join(tmp, "chunks.txt")
    with open(listfile, "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(concat_list_line(c) + "\n")
    audio = [] if not meta.get("audio") else (aac_args() if has_v else audio_codec_for(dst))
    run(ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile]
        + (["-c:v", "copy"] + (tag if ext in (".mp4", ".mov", ".m4v") else []) if has_v else ["-vn"]) + audio
        + (["-movflags", "+faststart"] if ext in (".mp4", ".mov", ".m4v") and has_v else []) + [dst])


BEAT_RATE = 22050  # the decode rate the onset pass uses, matching scenes.py --beats


def _grid_from_source(path: str, min_confidence: float) -> "dict":
    """The beat grid of `path`: a scenes.py --json document if that is what it is, otherwise a
    media file to measure. Reading a document is how a caller avoids a second decode."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict) and doc.get("beat_grid"):
        grid = dict(doc["beat_grid"])
        grid["beats"] = doc.get("beats") or []
        # A scenes.py document carries the supported subset since 1.17; one written by an older
        # build does not, and a grid whose supported points are unknown is not one this tool may
        # move a cut onto -- an unknown subset is not an empty one, but it is not a measurement
        # either, so it is refused rather than silently treated as "all of them".
        grid["supported_beats"] = doc.get("beat_grid", {}).get("supported_beats")
        if grid["supported_beats"] is None:
            grid["supported_beats"] = doc.get("supported_beats")
        try:
            tempo = grid.get("tempo_bpm")
            grid["tempo_bpm"] = float(tempo) if tempo is not None else None
            grid["confidence"] = float(grid.get("confidence") or 0.0)
        except (TypeError, ValueError):
            die(f"--snap-source {path}: beat_grid.tempo_bpm and .confidence must be numbers "
                "(regenerate it with `scenes.py MUSIC --beats --json`)", kind="input")
        if grid["beats"] and grid["tempo_bpm"] is None:
            die(f"--snap-source {path}: this document lists beats but no tempo_bpm, so no grid "
                "was actually measured in it. Regenerate it with "
                "`scenes.py MUSIC --beats --json`.", kind="input")
        grid["usable"] = grid["confidence"] >= min_confidence
        return grid
    if isinstance(doc, dict):
        die(f"--snap-source {path}: this JSON has no beat_grid -- produce one with "
            "`scenes.py MUSIC --beats --json`", kind="input")
    samples = decode_pcm_mono(path, BEAT_RATE, check=False)
    env = rms_envelope(samples, max(1, int(round(BEAT_RATE * 0.01))))
    return beat_grid(env, 0.01, min_confidence=min_confidence)


def snap_segments(args, segments, meta, total):
    """Move every in/out point to the nearest measured beat. Returns (result dict, segments).

    A cut point may move to a measured, onset-supported grid point and may not appear from one:
    the number of segments is unchanged, and nothing is ever proposed. The keyframe/tolerance
    decision downstream then runs on the snapped values, which is the right order -- whether a cut
    can be lossless depends on where it actually lands.
    """
    source = args.snap_source or args.input
    if not args.snap_source and not meta.get("audio"):
        die("--snap beats needs audio to measure a beat in; this file has none. Cut without it "
            "(--snap none), or pass --snap-source with the music bed.", kind="input")
    # Compare the PARSED segments against the whole file, not the raw --start string: "0:00",
    # "0.0" and "00:00:00" are all a zero start that a string comparison lets through, and the
    # run would then snap the implicit end point and silently shorten a whole-file copy.
    whole_file = (len(segments) == 1 and abs(segments[0][0]) < 1e-6
                  and (not total or abs(segments[0][1] - total) < 1e-6))
    if whole_file:
        die("--snap beats has no in or out point to move: this run copies the whole file. Give "
            "--start/--end (or --segments), or drop --snap.", kind="input")
    # A floor of zero would make the confidence check vacuous -- a grid measured from noise scores
    # above 0.0 and would pass -- and the whole point of the flag is that a cut only moves onto a
    # pulse somebody can hear. The number is a floor on belief, so it must be a positive one.
    if args.min_confidence <= 0:
        die("--min-confidence must be greater than 0: at 0 every grid is 'reliable', including "
            "one measured from noise, which is exactly what --snap beats must not cut to. Use "
            "--snap none if you do not want the points moved at all.", kind="input")
    grid = _grid_from_source(source, args.min_confidence)
    confidence = float(grid.get("confidence") or 0.0)
    tempo = grid.get("tempo_bpm")
    if confidence < args.min_confidence or not grid.get("beats"):
        die(f"no reliable beat grid in this audio (confidence {confidence:.2f}, needs "
            f"{args.min_confidence:.2f}): cutting to invented beats would move your in/out points "
            "to times nothing in the audio supports. Re-run with --snap none, or pass "
            "--snap-source from a music bed.", kind="input")
    # THE grid a cut may move onto is the onset-supported subset, never the full regular grid.
    # beat_grid() reports a regular grid over the whole duration by design -- a grid has to be
    # regular -- so it runs on through a passage with no music in it. Snapping to one of those
    # points moves a cut to a time nothing in the audio marks, which is the fabrication this
    # release forbids and which this tool's own refusal text promises it does not do.
    supported = grid.get("supported_beats")
    if supported is None:
        die(f"--snap-source {source}: this document does not say which grid points a measured "
            "onset supports, so there is no way to tell a beat from a gap in it. Regenerate it "
            "with `scenes.py MUSIC --beats --json`.", kind="input")
    if not supported:
        die(f"no measured onset supports any point of this beat grid (confidence "
            f"{confidence:.2f}): the grid is regular but nothing in the audio marks it, so every "
            "move would be to an invented time. Re-run with --snap none, or pass --snap-source "
            "from a music bed.", kind="input")
    points = [t for seg in segments for t in seg]
    moved = snap_points(points, supported, args.snap_tolerance)
    out_segments = []
    for i in range(0, len(moved), 2):
        s, e = moved[i]["to"], moved[i + 1]["to"]
        if e <= s:   # a snap that would collapse the segment is not applied to it
            s, e = moved[i]["from"], moved[i + 1]["from"]
            moved[i].update({"to": s, "delta": 0.0, "snapped": False, "beat_index": None})
            moved[i + 1].update({"to": e, "delta": 0.0, "snapped": False, "beat_index": None})
        out_segments.append((s, e))
    snapped = sum(1 for m in moved if m["snapped"])
    for m in moved:
        if m["snapped"]:
            info(f"--snap beats: {m['from']:.3f}s -> {m['to']:.3f}s ({m['delta'] * 1000:+.0f} ms)")
    info(f"--snap beats: {tempo:.1f} BPM, confidence {confidence:.2f}; {snapped} of {len(moved)} "
         f"point(s) moved, within {args.snap_tolerance:.3f}s, onto {len(supported)} of "
         f"{len(grid['beats'])} grid point(s) a measured onset supports")
    return ({"mode": "beats", "tolerance": args.snap_tolerance, "confidence": confidence,
             "tempo_bpm": tempo, "grid": "supported", "grid_points": len(supported),
             "moved": [dict(m) for m in moved], "snapped": snapped,
             "unchanged": len(moved) - snapped,
             "source": "measured" if not args.snap_source else args.snap_source},
            out_segments)


@contextlib.contextmanager
def _join_workspace():
    """A --segments copy join's workspace: a temp directory for its parts, and a list of the files
    it writes beside the output (the checked join, renamed into place when it passes), removed
    whatever happens."""
    temps: List[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="ffskill_cut_") as tmp:
            yield tmp, temps
    finally:
        for path in temps:
            try:
                os.remove(path)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_cut.<ext>)")
    g = ap.add_argument_group("range (single segment)")
    g.add_argument("--start", default="0", help="start time (seconds, mm:ss or hh:mm:ss.ms). default 0")
    g.add_argument("--end", help="end time")
    g.add_argument("--duration", help="duration instead of --end")
    ap.add_argument("--segments", help="comma separated START-END list, e.g. '0:05-0:12,1:00-1:20' (joined in order)")
    ap.add_argument("--accurate", action="store_true", help="always re-encode for frame-accurate (video) / sample-accurate (audio) cuts (default: lossless -c copy, re-encoding only when the keyframe snap exceeds --tolerance)")
    ap.add_argument("--edit-list", action="store_true", help="a single-segment .mp4/.mov stream copy keeps the MP4 edit list that hides the keyframe's pre-roll, so the picture starts at --start (default: -avoid_negative_ts make_zero, the picture starts at the keyframe); a player that ignores edit lists shows the pre-roll")
    ap.add_argument("--keep-hevc", action="store_true", help="a re-encode of an SDR HEVC source stays HEVC (x265 8-bit BT.709; VideoToolbox under --hw) instead of x264 (default: x264 for SDR, x265 Main10 for HDR); --codec overrides it")
    ap.add_argument("--vfr-guard", choices=["average", "sampled", "off"], default="average",
                    help="what keeps a variable-frame-rate source from a stream copy (default average: a nominal rate "
                         "that differs from the average re-encodes, as --accurate, and the sampled frame timing is "
                         "reported; sampled: re-encode only when sampled packet timestamps are variable or too few "
                         "to judge; off: measure and keep the copy, with a note)")
    ap.add_argument("--tolerance", type=float, default=0.5, help="max seconds a lossless cut may deviate before re-encoding kicks in (default 0.5, -1 = never for a "
                         "keyframe snap; a --segments join is still re-cut for open GOPs, a later B-frame .mp4/.mov "
                         "segment starting between keyframes, or a failed join check)")
    snap = ap.add_argument_group("beat snapping")
    snap.add_argument("--snap", choices=["none", "beats"], default="none",
                      help="move each in/out point to the nearest measured beat (default none)")
    snap.add_argument("--snap-tolerance", type=float, default=0.12,
                      help="most seconds a point may move with --snap beats (default 0.12, about a "
                           "quarter of a beat at 120 BPM)")
    snap.add_argument("--snap-source", metavar="FILE",
                      help="take the beat grid from this scenes.py --beats --json document (or from "
                           "this media file) instead of measuring the input again")
    snap.add_argument("--min-confidence", type=float, default=BEAT_MIN_CONFIDENCE,
                      help=f"refuse to snap below this measured beat confidence (default {BEAT_MIN_CONFIDENCE})")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset when re-encoding")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    global KEEP_HEVC
    KEEP_HEVC = args.keep_hevc

    meta = probe(args.input)
    total = meta.get("duration") or 0.0
    # why every segment re-encodes, if one of these forces it; `requested` is read before the
    # guards below overwrite args.accurate, so a forced re-encode is never reported as asked for
    forced: List[str] = ["requested"] if args.accurate else []
    if STATE.codec:
        # "cut this and make it HEVC": a stream copy keeps the source codec, so the request is a
        # re-encode -- and a cause of it even when --accurate or the VFR guard already forced one
        if not args.accurate:
            info(f"--codec {STATE.codec} asks for a re-encode; the lossless copy path keeps the source codec, switching to --accurate")
        args.accurate = True
        forced.append("codec")

    fps = (meta.get("video") or {}).get("fps")
    if args.segments:
        segments = parse_segments(args.segments, fps)
    else:
        start = _t(args.start, fps, "--start")
        if start < 0:
            die(f"--start must not be negative, got {args.start!r}")
        if args.end and args.duration:
            die("use --end or --duration, not both")
        if args.end:
            end = _t(args.end, fps, "--end")
            if end < 0:
                die(f"--end must not be negative, got {args.end!r}")
        elif args.duration:
            end = start + _t(args.duration, fps, "--duration")
        else:
            end = total
        if end <= start:
            die("end must be after start")
        segments = [(start, end)]

    snap_result = None
    if args.snap == "beats":
        snap_result, segments = snap_segments(args, segments, meta, total)

    for s, e in segments:
        if total and s >= total:
            die(f"segment start {s:.3f}s is beyond the media duration {total:.3f}s")
    segments = [(s, min(e, total) if total else e) for s, e in segments]
    # what was asked for, clamped to the media duration as in every 2.x release: requested_* and
    # expected_duration report this, and a segment the join below ends with the video (less than a
    # frame of sound trimmed) shows that trim in duration_delta_seconds and a note instead
    requested = list(segments)
    video = meta.get("video") or {}
    if video.get("fps") and not is_audio_output(args.output or ""):
        # a video segment shorter than one frame has no picture to cut: a copy lands on a whole
        # GOP and a re-encode on one frame or none, so the result would not be what was asked
        frame = 1.0 / video["fps"]
        # where the video ends on the cut's clock (video_end), not the stream's length: video that
        # starts after the container does (MPEG-TS) ends later than its length says. A pending
        # --dry-run input has nothing to probe, so it falls back to the media duration.
        vend = (None if dry_run_input_pending(args.input) else video_end(args.input, meta)) or total
        for s, e in segments:
            if (min(e, vend) if vend else e) - s < frame - 1e-6:
                die(f"segment {s:.3f}-{e:.3f}s is shorter than one frame ({frame:.4f}s at {video['fps']:g} fps)"
                    + (" inside the video stream" if vend and e > vend else "")
                    + "; give every segment at least one frame", kind="input")

    output = args.output or default_output(args.input, "cut")
    refuse_output_is_input(output, args.input)
    ext = os.path.splitext(output)[1] or ".mp4"

    # A segment that runs past the end of the video, with a join after it: whatever joins it (the
    # concat demuxer or the concat filter) starts the next segment after its LONGER stream, so the
    # sound with no picture left a hole in the video (0.355 s for 0.3 s of sound, reported as a
    # clean copy). clip_length's rule, as join.py uses it: less than a frame past -> end the
    # segment with its picture; more -> hold the last frame for the sound, which only a re-cut
    # can do. The last segment is left as the source had it: nothing is placed after it.
    join_notes: List[str] = []
    hold_needed = False
    vend = (video_end(args.input, meta) if len(segments) > 1 and video.get("fps") and not is_audio_output(output)
            and not dry_run_input_pending(args.input) else None)
    if vend is not None:
        frame = 1.0 / video["fps"]
        for i, (s, e) in enumerate(segments[:-1]):
            if e <= vend + 1e-6:
                continue
            if e - vend <= frame + 1e-6:
                segments[i] = (s, vend)
                join_notes.append(f"segment {i + 1} ends with the video at {vend:.3f}s: the {(e - vend) * 1000:.0f} ms of "
                                  "sound after its last frame is trimmed")
            else:
                hold_needed = True
                join_notes.append(f"segment {i + 1} runs {e - vend:.3f}s past the end of the video; its last frame is held "
                                  "for the sound, which a stream-copy join cannot do, so every segment was re-cut")
    for n in join_notes:
        info(n)

    # the VFR guard: a stream copy of variable-frame-rate video cuts unreliably. --vfr-guard average
    # (the default, as in every 2.x release) trusts probe's nominal-vs-average rate check and
    # re-encodes on it; the sampled packet timing is then measured only to report whether that
    # check was right. sampled re-encodes on the sampled timing instead (an iPhone's 30 vs 29.98
    # fps is not taken for VFR), and off measures and keeps the copy.
    vfr_check = None
    vfr_notes: List[str] = []
    could_copy = (bool(video) and not args.accurate and not hold_needed and not is_audio_output(output)
                  and not dry_run_input_pending(args.input))

    def sample_timing() -> dict:
        return {"heuristic": True, **measure_frame_timing(args.input, total, video.get("start_time") or 0.0),
                "method": "sampled", "guard": args.vfr_guard}

    if args.vfr_guard == "average":
        if video.get("variable_frame_rate_suspected") and not args.accurate:
            info("source looks variable-frame-rate; lossless cuts on VFR are unreliable, switching to --accurate")
            if could_copy:
                vfr_check = sample_timing()
                if vfr_check["measured"] == "sampled_cfr":
                    vfr_notes.append("the nominal and average frame rates differ, so the source was taken for VFR and "
                                     "re-encoded, but its sampled frame timing is constant: --vfr-guard sampled keeps "
                                     "the lossless copy")
                    info(vfr_notes[-1])
            args.accurate = True
            forced.append("vfr")
    elif could_copy:
        vfr_check = sample_timing()
        measured = vfr_check["measured"]
        what = ("the sampled frame timing is variable" if measured == "vfr"
                else "the frame timing could not be measured")
        if measured != "sampled_cfr" and args.vfr_guard == "off":
            vfr_notes.append(f"{what}; --vfr-guard off skipped the re-encode that forces, so a stream copy of this "
                             "source may land off its frames")
            info(vfr_notes[-1])
        elif measured != "sampled_cfr":
            info(f"{what}; lossless cuts on VFR are unreliable, switching to --accurate (--vfr-guard off keeps the copy)")
            args.accurate = True
            forced.append("vfr" if measured == "vfr" else "vfr_inconclusive")

    outcomes: List[dict] = []
    join_reencoded = False
    join_check = None
    if len(segments) == 1:
        outcomes.append(cut_one(args.input, segments[0][0], segments[0][1], output, args.accurate, args.crf, args.preset, args.tolerance, meta,
                                edit_list_ok=args.edit_list))
    elif hold_needed or args.accurate:
        # Straight to one encode through the concat filter. A held frame needs the re-cut (no part
        # can carry it into a copy join); and when every part re-encodes anyway, encoding each on
        # its own and copy-joining them left a hole of one AAC frame at every join (each part's
        # audio runs an encoder frame past its picture, and the concat demuxer places the next
        # part after it: measured 23 ms per join).
        with tempfile.TemporaryDirectory(prefix="ffskill_cut_") as tmp:
            join_from_source(args.input, segments, output, meta, args.crf, args.preset, tmp)
        join_reencoded = hold_needed   # only the hold is a fallback; --accurate asked for this
        outcomes = [_outcome(meta, output, True, []) for _ in segments]
    else:
        with _join_workspace() as (tmp, temps):
            # A video join is planned from the source's own packets and measured against them once
            # written (check_join). A source whose frames do not reorder (no B-frames) cuts its
            # parts as every 2.x release did (make_zero, -t end-start, each part judged against
            # --tolerance by its length): in decode order that is already exact. One whose frames
            # reorder keeps .mp4/.mov parts' edit lists and cuts each from its start keyframe to
            # its end keyframe's dts (plan_part). An audio-only join keeps the plain cut.
            join_video = bool(video) and not is_audio_output(output) and not dry_run_input_pending(args.input)
            # where each part's -ss lands, measured (seek_keyframe); the packets read around the
            # segments reach back to it
            landings = [seek_keyframe(args.input, s) for s, _ in segments] if join_video else None
            packets = (video_packets(args.input, [(min(s, k[0]) if k else s, e) for (s, e), k in zip(segments, landings)],
                                     args.tolerance, total) if join_video else None)
            snap_end = bool(packets) and reorders(packets) and ext.lower() in EDIT_LIST_EXTS
            plans = ([plan_part(packets, s, e, args.tolerance, video_end(args.input, meta), fps, snap_end, k)
                      for (s, e), k in zip(segments, landings)] if packets else None)
            open_key = open_join_key(packets, plans) if plans else None
            preroll = hidden_preroll_start(packets, plans, snap_end) if plans else None
            recut = None  # why the parts are not joined by stream copy, when that is known before cutting them
            if join_video and not packets:
                recut = ("the source's video packets could not be read, so a stream-copy join could not be checked; "
                         "every segment was re-cut from the source")
            elif open_key is not None:
                recut = (f"the source uses open GOPs: frames before the keyframe at {open_key:.3f}s decode after it, so a "
                         "stream-copy join would drop them; every segment was re-cut from the source")
            elif preroll is not None and not any(p["reason"] for p in plans):
                recut = (f"segment {preroll} starts between keyframes of a source whose frames reorder: its copy would "
                         "hide the frames before its start, which a stream-copy join cannot do; every segment was re-cut "
                         "from the source")
            compatible = False
            if recut:
                info(recut)
                join_notes.append(recut)
            elif plans and any(p["reason"] for p in plans):
                # a segment with no keyframe near its start or end re-encodes, and only copied parts are
                # joined by copy (parts encoded one by one leave an AAC frame's hole at every join), so
                # every segment is re-cut into one encode, without encoding the parts first
                late = [str(i + 1) for i, p in enumerate(plans) if p["reason"]]
                # the keyframes near each such segment's start, as a part judged on its own named them
                # in every 2.x release, so the caller can move the cut instead
                for (s, _), p in zip(segments, plans):
                    if p["reason"]:
                        NEAREST_KEYFRAMES.extend(k for k in keyframes_near(args.input, s) if k not in NEAREST_KEYFRAMES)
                info(f"segment{'s' if len(late) > 1 else ''} {', '.join(late)} {'have' if len(late) > 1 else 'has'} no keyframe "
                     f"within {args.tolerance:.2f}s of {'their' if len(late) > 1 else 'its'} start or end to copy from; "
                     "re-cutting every segment from the source into one re-encode")
                recut = "tolerance"
            if recut:
                outcomes = [_outcome(meta, output, True, ["tolerance"] if plans and plans[i]["reason"] else [])
                            for i in range(len(segments))]
            else:
                parts = []
                for i, (s, e) in enumerate(segments):
                    part = os.path.join(tmp, f"part{i:03d}{ext}")
                    plan = plans[i] if plans else None
                    outcomes.append(cut_one(args.input, s, e, part, False, args.crf, args.preset, args.tolerance, meta,
                                            edit_list_ok=False, copy_t=plan["t"] if plan and snap_end else None))
                    parts.append(part)
                # a stream-copy join is only safe between identical copied parts: the concat demuxer
                # takes the first part's parameters for all of them, and a mismatch (a copied HEVC part
                # next to a re-encoded one, or H.264 next to HEVC) decodes with errors from a run that
                # exited 0; video parts that all re-encoded match, but leave an AAC frame's hole at each
                # join (audio decoded to PCM has no encoder priming, so those parts still join)
                compatible = (not (join_video and any(o["reencoded"] for o in outcomes))
                              and (STATE.dry_run or signatures_match([join_signature(p) for p in parts], ext)))
                if compatible:
                    listfile = os.path.join(tmp, "list.txt")
                    with open(listfile, "w", encoding="utf-8") as fh:
                        for p in parts:
                            fh.write(concat_list_line(p) + "\n")
                    # a join that is checked is written to a hidden file beside the output and renamed
                    # into place only once it passes (copying it out of the temp directory cost about 2 s
                    # for 240 MB): a failed check re-cuts, and a re-cut that then failed must not cost
                    # the caller the file --overwrite would have replaced
                    checked = bool(plans) and not STATE.dry_run
                    joined = sibling_temp(output, "join") if checked else output
                    if checked:
                        temps.append(joined)
                    cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy"]
                    if ext in (".mp4", ".mov", ".m4v"):
                        cmd += ["-movflags", "+faststart"]
                    cmd += [joined]
                    proc = run(cmd, check=False)
                    if proc.returncode != 0:
                        info("concat with stream copy failed; re-cutting every segment from the source into one re-encode")
                        compatible = False
                    elif checked:
                        # measured, not predicted: the joined file against the source packets its parts hold
                        # constant frame timing: measured by the sampled guards, and under the default
                        # average guard a copy is only reached when probe's rate check found it constant
                        cfr = (vfr_check.get("measured") == "sampled_cfr" if vfr_check
                               else args.vfr_guard == "average")
                        counts = [expected_packets(packets, [(p["start_pts"], p["end_bound"])]) for p in plans]
                        out_pts = stream_packet_times(joined, "v", "pts_time")
                        join_check = check_join(out_pts, counts, fps, cfr, predicted_join_steps(parts))
                        # the sound of each part against its picture (only once the pictures are right: the
                        # parts are located in the join by their packet counts)
                        video_ok = join_check["ok"]
                        audio = (check_join_audio(args.input, joined, [p["start_pts"] for p in plans], counts, out_pts,
                                                  copied_audio_streams(meta, joined),
                                                  strip_adts=("mpegts" in str(meta.get("format") or "").split(",")
                                                              and ext.lower() not in TS_EXTS))
                                 if video_ok and meta.get("audio") else
                                 {"audio_offset_ms": None, "audio_parts_checked": 0, "audio_ok": True})
                        audio_ok = audio.pop("audio_ok")
                        join_check["ok"] = video_ok and audio_ok
                        join_check.update(audio)
                        if not join_check["ok"]:
                            step = join_check["max_step_seconds"]
                            if video_ok:
                                off = max((o for o in join_check["audio_offset_ms"] if o is not None), key=abs)
                                why = (f"segment {join_check['audio_offset_ms'].index(off) + 1}'s sound is {abs(off):.1f} ms "
                                       f"{'late' if off > 0 else 'early'} against its picture")
                            else:
                                why = (f"{join_check['packets']} video packets where the segments hold "
                                       f"{join_check['expected_packets']} in the source"
                                       + (f", largest step {step:.3f}s" if step is not None else ""))
                            msg = f"the stream-copy join was checked and failed: {why}; every segment was re-cut from the source"
                            info(msg)
                            join_notes.append(msg)
                            compatible = False
                        else:
                            place_output(joined, output, move=True)
                else:
                    info("the cut parts cannot be joined by stream copy (a segment re-encoded, or the parts differ in "
                         "codec parameters); re-cutting every segment from the source into one re-encode")
            if not compatible:
                join_from_source(args.input, segments, output, meta, args.crf, args.preset, tmp)
                join_reencoded = True
                # every segment was re-cut and re-encoded: none of them keeps its copy precision
                outcomes = [_outcome(meta, output, True, o["reasons"]) for o in outcomes]

    result = probe(output, role="output")
    expected = sum(e - s for s, e in requested)
    # the join counts: a copy join that fell back to a re-encode is not a stream copy (2.x reported
    # it as mode copy, precision packet)
    reencoded = join_reencoded or any(o["reencoded"] for o in outcomes)
    report = report_precision(meta, output, reencoded, outcomes)
    precision = report["precision"]
    reencode_reason: List[str] = []
    if reencoded:
        for r in forced + [r for o in outcomes for r in o["reasons"]] + (["concat_fallback"] if join_reencoded else []):
            if r not in reencode_reason:
                reencode_reason.append(r)
    got = result.get("duration")
    error_ms = round((got - expected) * 1000, 3) if got is not None and not STATE.dry_run else None
    # mode: "copy" (nothing re-encoded at any stage, the join included), "accurate" (--accurate was
    # asked for or forced), "hybrid" (asked for lossless but a segment or the join re-encoded anyway;
    # reencode_reason says why)
    mode = "copy" if not reencoded else ("accurate" if args.accurate else "hybrid")
    notes: List[str] = vfr_notes + join_notes + [n for o in outcomes for n in o.get("notes") or []]
    single = outcomes[0] if len(outcomes) == 1 else {}
    stored = single.get("stored_preroll_seconds")
    if single.get("edit_list") and stored:
        notes.append(f"{stored:.3f}s of pre-roll is stored, hidden by the MP4 edit list; a player or "
                     "tool that ignores edit lists will show it")
    # where each copied part's end moved to its keyframe; only for a join that is those parts
    end_snaps = None
    if join_check and join_check["ok"] and not join_reencoded:
        end_snaps = [None if o["reencoded"] or p["end_pts"] is None else round(p["end_pts"] - e, 3) + 0.0
                     for o, p, (_, e) in zip(outcomes, plans, segments)]
    # a single MP4/MOV copy without --edit-list shows the pre-roll the edit list would hide
    remedy = (len(outcomes) == 1 and not reencoded and not single.get("edit_list") and single.get("start_snapped")
              and ext.lower() in EDIT_LIST_EXTS and not is_audio_output(output))
    # the source's own skew where the output's picture starts: at the keyframe the first copy
    # landed on, or at the start when an edit list hides the pre-roll (or a re-encode starts there)
    first = outcomes[0] if outcomes else {}
    at = (first["landed_pts"] if not reencoded and not first.get("edit_list") and first.get("landed_pts") is not None
          else segments[0][0])
    skew, skew_note = ((None, None) if STATE.dry_run
                       else av_skew(result, bool(remedy), source_skew(args.input, meta, at)))
    if reencoded:
        # a re-encode starts both streams where the source had them at the start (the re-cut pads the
        # audio to each segment's origin): the skew is reported, but no copy began on unshared packets
        skew_note = None
    if skew_note:
        info(skew_note)
        notes.append(skew_note)
    info(f"wrote {output} ({fmt_secs(got)}, expected ~{expected:.3f}s, "
         + ("re-encoded" if reencoded else "lossless stream copy") + f", {precision} precision)")
    emit(output, expected_duration=round(expected, 6), duration_error_ms=error_ms, precision=precision, reencoded=reencoded,
         dropped_non_av_streams=bool(DROPPED_STREAMS),
         requested_start=round(requested[0][0], 6) if len(requested) == 1 else None,
         requested_end=round(requested[0][1], 6) if len(requested) == 1 else None,
         requested_segments=[[round(s, 6), round(e, 6)] for s, e in requested] if len(requested) > 1 else None,
         requested_duration=round(expected, 6), output_duration=round(got, 6) if got is not None else None,
         duration_delta_seconds=round(error_ms / 1000, 6) if error_ms is not None else None,
         mode=mode, keyframe_snapped=report["keyframe_snapped"], start_snapped=report["start_snapped"],
         reencode_reason=reencode_reason, least_exact_precision=report["least_exact_precision"],
         segment_precision=report["segment_precision"],
         edit_list=bool(single.get("edit_list")), stored_preroll_seconds=stored, av_start_skew_seconds=skew,
         join_check=join_check, segment_end_snap_seconds=end_snaps,
         notes=notes, **({"vfr_check": vfr_check} if vfr_check else {}),
         nearest_keyframes=sorted(NEAREST_KEYFRAMES) if NEAREST_KEYFRAMES else None,
         # the trade the caller can offer instead of a re-encode (eval e02: "without losing quality")
         lossless_alternative=(f"--start {min(NEAREST_KEYFRAMES, key=lambda k: abs(k - segments[0][0])):.3f} lands on a keyframe: "
                               f"stream copy with no re-encode, {abs(min(NEAREST_KEYFRAMES, key=lambda k: abs(k - segments[0][0])) - segments[0][0]):.2f}s off the requested start")
         if mode == "hybrid" and NEAREST_KEYFRAMES and len(segments) == 1 else None,
         snap=snap_result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
