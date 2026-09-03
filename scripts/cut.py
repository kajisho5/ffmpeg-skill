#!/usr/bin/env python3
"""Cut a clip or several segments out of a video and (optionally) join them.

Lossless stream copy (-c copy) is preferred. Cuts snap to keyframes in that
mode, so if frame accuracy matters pass --accurate to re-encode. Multiple
segments are cut individually and concatenated with the concat demuxer.

Examples:
  python3 cut.py input.mp4 --start 00:00:10 --end 00:00:25
  python3 cut.py input.mp4 --segments 0:05-0:12,1:00-1:20 -o highlights.mp4
  python3 cut.py input.mp4 --start 3.5 --duration 10 --accurate
"""
import argparse
import os
import sys
import tempfile
from typing import List, Tuple

from _common import video_args, STATE, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, ffmpeg_base, info, parse_time, probe, run, x264_args


def parse_segments(spec: str) -> List[Tuple[float, float]]:
    segs = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "-" not in raw:
            die(f"segment '{raw}' must look like START-END (e.g. 0:05-0:12)")
        a, b = raw.rsplit("-", 1)
        start, end = parse_time(a), parse_time(b)
        if end <= start:
            die(f"segment '{raw}': end must be after start")
        segs.append((start, end))
    if not segs:
        die("no segments given")
    return segs


def cut_one(src: str, start: float, end: float, dst: str, reencode: bool, crf: int, preset: str, tolerance: float = 0.5, meta: dict = None) -> bool:
    """Cut one segment. Returns True if the result was re-encoded."""
    dur = end - start
    meta = meta or probe(src)
    if reencode:
        cmd = ffmpeg_base() + ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]
        cmd += video_args(meta, crf, preset) + cfr_args(meta) + aac_args() + ["-avoid_negative_ts", "make_zero", dst]
    else:
        cmd = ffmpeg_base() + ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero", dst]
    proc = run(cmd, check=False)
    if proc.returncode != 0:
        if not reencode:
            info("stream copy failed, falling back to re-encode")
            return cut_one(src, start, end, dst, True, crf, preset, tolerance, meta)
        die(f"ffmpeg failed:\n{proc.stderr.strip()}")
    if not reencode and tolerance >= 0 and not STATE["dry_run"]:
        got = probe(dst).get("duration") or 0.0
        if abs(got - dur) > tolerance:
            info(f"stream copy landed on a keyframe {abs(got - dur):.2f}s away from the requested cut "
                 f"(> {tolerance:.2f}s tolerance); re-encoding this segment for accuracy")
            return cut_one(src, start, end, dst, True, crf, preset, tolerance, meta)
    return reencode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_cut.<ext>)")
    g = ap.add_argument_group("range (single segment)")
    g.add_argument("--start", default="0", help="start time (seconds, mm:ss or hh:mm:ss.ms). default 0")
    g.add_argument("--end", help="end time")
    g.add_argument("--duration", help="duration instead of --end")
    ap.add_argument("--segments", help="comma separated START-END list, e.g. '0:05-0:12,1:00-1:20' (joined in order)")
    ap.add_argument("--accurate", action="store_true", help="always re-encode for frame-accurate cuts (default: lossless -c copy, re-encoding only when the keyframe snap exceeds --tolerance)")
    ap.add_argument("--tolerance", type=float, default=0.5, help="max seconds a lossless cut may deviate before re-encoding kicks in (default 0.5, -1 = never)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF when re-encoding (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset when re-encoding")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    total = meta.get("duration") or 0.0
    if meta.get("video", {}) and meta["video"].get("variable_frame_rate_suspected") and not args.accurate:
        info("source looks variable-frame-rate; lossless cuts on VFR are unreliable, switching to --accurate")
        args.accurate = True

    if args.segments:
        segments = parse_segments(args.segments)
    else:
        start = parse_time(args.start)
        if args.end and args.duration:
            die("use --end or --duration, not both")
        if args.end:
            end = parse_time(args.end)
        elif args.duration:
            end = start + parse_time(args.duration)
        else:
            end = total
        if end <= start:
            die("end must be after start")
        segments = [(start, end)]

    for s, e in segments:
        if total and s >= total:
            die(f"segment start {s:.3f}s is beyond the media duration {total:.3f}s")
    segments = [(s, min(e, total) if total else e) for s, e in segments]

    output = args.output or default_output(args.input, "cut")
    ext = os.path.splitext(output)[1] or ".mp4"

    reencoded = False
    if len(segments) == 1:
        reencoded = cut_one(args.input, segments[0][0], segments[0][1], output, args.accurate, args.crf, args.preset, args.tolerance, meta)
    else:
        with tempfile.TemporaryDirectory(prefix="ffskill_cut_") as tmp:
            parts = []
            for i, (s, e) in enumerate(segments):
                part = os.path.join(tmp, f"part{i:03d}{ext}")
                reencoded |= cut_one(args.input, s, e, part, args.accurate, args.crf, args.preset, args.tolerance, meta)
                parts.append(part)
            listfile = os.path.join(tmp, "list.txt")
            with open(listfile, "w", encoding="utf-8") as fh:
                for p in parts:
                    fh.write("file '" + p.replace("'", "'\\''") + "'\n")
            cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", output]
            proc = run(cmd, check=False)
            if proc.returncode != 0:
                info("concat with stream copy failed, re-encoding the join")
                cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile] + video_args(meta, args.crf, args.preset) + cfr_args(meta) + aac_args() + [output]
                run(cmd)

    result = probe(output)
    expected = sum(e - s for s, e in segments)
    info(f"wrote {output} ({result.get('duration'):.3f}s, expected ~{expected:.3f}s, "
         + ("re-encoded" if reencoded else "lossless stream copy") + ")")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
