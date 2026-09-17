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

from _common import add_common, apply_common, die, emit, info, print_json, probe, require_tool, run_analysis, decode_gray_frames, frame_flow

MOTION_CENTRE_FPS = 2.0
MOTION_CENTRE_W, MOTION_CENTRE_H = 64, 36

CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect(path: str, seconds: float, samples: int, limit: float, round_to: int, duration: float) -> List[Tuple[int, int, int, int]]:
    ffmpeg = require_tool("ffmpeg")
    per_window = max(0.5, seconds / max(1, samples))
    rects: List[Tuple[int, int, int, int]] = []
    failures: List[List[str]] = []
    for i in range(samples):
        start = 0.0 if duration <= 0 else (duration - per_window) * i / max(1, samples - 1) if samples > 1 else 0.0
        start = max(0.0, start)
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-i", path, "-t", f"{per_window:.3f}",
               "-vf", f"cropdetect=limit={limit:g}:round={round_to}:reset=1", "-f", "null", "-"]
        proc = run_analysis(cmd, check=False)
        if proc.returncode != 0:
            # One window ffmpeg cannot decode (a damaged stretch) is skipped; the other windows
            # still measure. Only when every window fails is there nothing to report.
            failures.append(proc.stderr.strip().splitlines()[-1:] or ["?"])
            continue
        for m in CROP_RE.finditer(proc.stderr):
            rects.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))))
    if failures and len(failures) == samples:
        die(f"cropdetect could not decode any of the {samples} sampled windows: {failures[-1][0][:300]}", kind="ffmpeg")
    return rects


def motion_centre(path: str, seconds: float, samples: int, duration: float, sw: int, sh: int) -> List[Dict]:
    """Per-second motion centroid: {time, x, y, x_frac, y_frac} -- a report-only measurement,
    the same sampled-window approach as detect() above. x/y are pixel coordinates in the SOURCE
    frame (consistent with the --round crop rectangle this tool already reports in source
    pixels); x_frac/y_frac are the same position as a 0..1 fraction of source_width/height, for a
    caller that wants to reframe without first knowing the source size. This never picks a
    subject -- it reports where in the frame the measured pixel motion was concentrated, which is
    not the same thing as where the interesting subject is (a moving background behind a still
    speaker centres the motion on the background)."""
    per_window = max(0.5, seconds / max(1, samples))
    cell = 8  # NxN diff grid at decode resolution
    cw, ch = MOTION_CENTRE_W / cell, MOTION_CENTRE_H / cell
    out: List[Dict] = []
    for i in range(samples):
        start = 0.0 if duration <= 0 else (duration - per_window) * i / max(1, samples - 1) if samples > 1 else 0.0
        start = max(0.0, start)
        frames = decode_gray_frames(path, MOTION_CENTRE_FPS, MOTION_CENTRE_W, MOTION_CENTRE_H,
                                     start=start, seconds=per_window, check=False)
        for k in range(len(frames) - 1):
            prev, cur = frames[k], frames[k + 1]
            wsum = wx = wy = 0.0
            for gy in range(cell):
                for gx in range(cell):
                    x0, x1 = int(gx * cw), int((gx + 1) * cw)
                    y0, y1 = int(gy * ch), int((gy + 1) * ch)
                    diff = 0
                    for y in range(y0, y1):
                        row = y * MOTION_CENTRE_W
                        for x in range(x0, x1):
                            diff += abs(prev[row + x] - cur[row + x])
                    cx = (gx + 0.5) / cell
                    cy = (gy + 0.5) / cell
                    wsum += diff
                    wx += diff * cx
                    wy += diff * cy
            t = start + (k + 1) / MOTION_CENTRE_FPS
            if wsum <= 0:
                out.append({"time": round(t, 2), "x": None, "y": None, "x_frac": None, "y_frac": None, "motion": 0.0})
                continue
            xf, yf = wx / wsum, wy / wsum
            out.append({"time": round(t, 2), "x": round(xf * sw), "y": round(yf * sh),
                        "x_frac": round(xf, 3), "y_frac": round(yf, 3), "motion": round(wsum / (MOTION_CENTRE_W * MOTION_CENTRE_H), 2)})
    out.sort(key=lambda r: r["time"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--seconds", type=float, default=10.0, help="total seconds of footage to sample across the file (default 10)")
    ap.add_argument("--samples", type=int, default=5, help="number of windows spread across the file (default 5)")
    ap.add_argument("--limit", type=float, default=0.0941176, help="black-pixel threshold, 0..1 (default ~0.094, cropdetect's own default)")
    ap.add_argument("--round", type=int, default=16, dest="round_to", help="the reported width/height are rounded to a multiple of this (default 16)")
    ap.add_argument("--motion-centre", action="store_true",
                    help="report the motion centroid per second, sampled the same way as the crop "
                         "detection above (report only -- this tool never picks a reframe, it hands "
                         "the calling agent numbers to reframe with)")
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

    if args.motion_centre:
        centre = motion_centre(args.input, args.seconds, args.samples, duration, sw, sh)
        result["motion_centre"] = centre
        info(f"--motion-centre: {len(centre)} measured points")

    if args.json:
        emit(None, **result)
    else:
        print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
