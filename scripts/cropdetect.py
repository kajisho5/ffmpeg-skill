#!/usr/bin/env python3
"""Measure black letterbox/pillarbox bars and report the crop rectangle that removes them.

Wraps FFmpeg's cropdetect filter: it samples frames, finds the largest
non-black rectangle common to (recent) frames, and reports it. This is a
measurement only -- it writes no file. Feed the reported {x, y, width,
height} to crop.py to actually remove the bars:

  python3 cropdetect.py input.mp4
  python3 crop.py input.mp4 --x 0 --y 140 --width 1920 --height 800

Distinct from fit.py --fit crop, which crops to a *target aspect ratio* it
computes itself (no black-bar detection involved) -- this tool instead
measures bars that are already baked into the source picture and tells you
where they are; it does not decide whether removing them is wanted (a
source with genuine letterboxed content, e.g. a scope-ratio film in a 16:9
frame, will "detect" that letterboxing as bars to strip, which is correct
for restoring the original frame but wrong if the letterboxing is part of
the intended presentation -- look at the frame before cropping it away).

--seconds controls how much of the file is sampled (default 10s, spread
across the file by --samples windows so a single black scene near the start
doesn't skew the result). Detected values fluctuate slightly frame to frame
even on a static border; the reported rectangle is the most common one seen.

Examples:
  python3 cropdetect.py input.mp4
  python3 cropdetect.py input.mp4 --seconds 30 --limit 0.15
"""
import argparse
import re
import sys
from collections import Counter
from typing import Dict, List, Tuple

from _common import add_common, apply_common, die, emit, info, print_json, probe, require_tool, run_analysis

CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect(path: str, seconds: float, samples: int, limit: float, round_to: int, duration: float) -> List[Tuple[int, int, int, int]]:
    ffmpeg = require_tool("ffmpeg")
    per_window = max(0.5, seconds / max(1, samples))
    rects: List[Tuple[int, int, int, int]] = []
    for i in range(samples):
        start = 0.0 if duration <= 0 else (duration - per_window) * i / max(1, samples - 1) if samples > 1 else 0.0
        start = max(0.0, start)
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-i", path, "-t", f"{per_window:.3f}",
               "-vf", f"cropdetect=limit={limit:g}:round={round_to}:reset=1", "-f", "null", "-"]
        proc = run_analysis(cmd)
        for m in CROP_RE.finditer(proc.stderr):
            rects.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))))
    return rects


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--seconds", type=float, default=10.0, help="total seconds of footage to sample across the file (default 10)")
    ap.add_argument("--samples", type=int, default=5, help="number of windows spread across the file (default 5)")
    ap.add_argument("--limit", type=float, default=0.0941176, help="black-pixel threshold, 0..1 (default ~0.094, cropdetect's own default)")
    ap.add_argument("--round", type=int, default=16, dest="round_to", help="the reported width/height are rounded to a multiple of this (default 16)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.seconds <= 0:
        die(f"--seconds must be > 0, got {args.seconds:g}")
    if args.samples <= 0:
        die(f"--samples must be > 0, got {args.samples}")
    if not 0 <= args.limit <= 1:
        die(f"--limit must be 0..1, got {args.limit:g}")
    if args.round_to <= 0:
        die(f"--round must be > 0, got {args.round_to}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    duration = meta.get("duration") or 0.0

    rects = detect(args.input, args.seconds, args.samples, args.limit, args.round_to, duration)
    result: Dict = {"file": args.input, "source_width": sw, "source_height": sh}
    if not rects:
        result["crop"] = None
        info("no crop bars detected (cropdetect produced no readings -- try --limit higher, or the source may already be full-frame)")
    else:
        w, h, x, y = Counter(rects).most_common(1)[0][0]
        result["crop"] = {"width": w, "height": h, "x": x, "y": y}
        result["confidence"] = round(Counter(rects).most_common(1)[0][1] / len(rects), 3)
        if (w, h) == (sw, sh):
            info(f"no bars detected: full {sw}x{sh} frame is already content")
        else:
            info(f"detected crop={w}:{h}:{x}:{y} (source {sw}x{sh}, confidence {result['confidence']:.0%}) -- "
                 f"crop.py {args.input} --x {x} --y {y} --width {w} --height {h}")

    if args.json:
        emit(None, **result)
    else:
        print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
