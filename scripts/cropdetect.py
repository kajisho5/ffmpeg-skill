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
from typing import Dict, List, Optional, Tuple

from _common import add_common, apply_common, die, emit, info, print_json, probe, require_tool, run_analysis, decode_gray_frames
from _common.emit import note, warn
from _common.probe import PROBED_VIDEO, display_size, square_pixels, square_pixels_note

MOTION_CENTRE_FPS = 2.0
MOTION_CENTRE_W, MOTION_CENTRE_H = 64, 36

CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def round_rect(rect: Tuple[int, int, int, int], round_to: int, full: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """One measured rectangle (w, h, x, y) as it is reported: the whole frame when the picture
    reaches every edge (cropdetect's own round=2 reading of an odd side is one pixel short of it),
    else rounded down to a multiple of `round_to` and re-centred the way cropdetect's round option
    does it. Rounding inside the filter made a bar-free 1920x1080 read 1920x1072 at the default 16
    (#403): 1080 is not a multiple of 16, and the rounded size was then compared with the source's."""
    w, h, x, y = rect
    fw, fh = full
    if fw and fh and x == 0 and y == 0 and w >= fw - fw % 2 and h >= fh - fh % 2:
        return fw, fh, 0, 0
    # the filter's own reading of its round option: 1 is 16, an odd value is doubled
    round_to = 16 if round_to <= 1 else round_to * 2 if round_to % 2 else round_to
    shrink_w, shrink_h = w % round_to, h % round_to
    return w - shrink_w, h - shrink_h, x + ((shrink_w // 2 + 1) & ~1), y + ((shrink_h // 2 + 1) & ~1)


def detect(path: str, seconds: float, samples: int, limit: float, round_to: int, duration: float,
           failed: "Optional[List[Dict]]" = None, square: str = "", full: Tuple[int, int] = (0, 0)) -> List[Tuple[int, int, int, int]]:
    """Crop rectangles from `samples` windows spread over the file. A window ffmpeg cannot decode
    is skipped, and appended to `failed` as {start, seconds, error} when the caller passes a list,
    so the result can say how many of the readings it stands on. `square` is the source's
    square_pixels() scale, run first so the rectangle is in the frame crop.py crops (#411).
    `full` is that frame's size: the filter measures at round=2 and round_rect() rounds each
    reading, so a picture that fills the frame is reported as the frame."""
    ffmpeg = require_tool("ffmpeg")
    per_window = max(0.5, seconds / max(1, samples))
    rects: List[Tuple[int, int, int, int]] = []
    failures: List[List[str]] = []
    for i in range(samples):
        start = 0.0 if duration <= 0 else (duration - per_window) * i / max(1, samples - 1) if samples > 1 else 0.0
        start = max(0.0, start)
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-i", path, "-t", f"{per_window:.3f}",
               "-map", f"0:{PROBED_VIDEO}", "-vf", (square + "," if square else "") + f"cropdetect=limit={limit:g}:round=2:reset=1", "-f", "null", "-"]
        proc = run_analysis(cmd, check=False)
        if proc.returncode != 0:
            # One window ffmpeg cannot decode (a damaged stretch) is skipped; the other windows
            # still measure. Only when every window fails is there nothing to report.
            failures.append(proc.stderr.strip().splitlines()[-1:] or ["?"])
            if failed is not None:
                failed.append({"start": round(start, 3), "seconds": round(per_window, 3), "error": failures[-1][0][:300]})
            continue
        for m in CROP_RE.finditer(proc.stderr):
            rects.append(round_rect((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))), round_to, full))
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
    ap.add_argument("--round", type=int, default=16, dest="round_to", help="a detected crop's width/height are rounded down to a multiple of this (default 16); a picture that reaches every edge is reported as the whole frame, unrounded")
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
    # cropdetect and the grey decode both see the frame after ffmpeg applies rotation, so the
    # rectangle and the motion points are in that frame. Reporting the stored size made a
    # 176x320 crop look taller than a 320x180 source. A non-square-pixel source is measured
    # squared at its display aspect, the frame crop.py then crops (#411).
    sw, sh = display_size(meta["video"])
    if square_pixels_note(meta["video"]):
        note(square_pixels_note(meta["video"]))
    duration = meta.get("duration") or 0.0

    failed: List[Dict] = []
    # A164: cropdetect reads a limit below 1 as a fraction of the top code and 1 or more as the
    # code itself, so --limit 1, the top of the documented 0..1 range, was read as code 1 (nearly
    # nothing is black) where 0.999 reads as nearly everything. The top of the range is written
    # as the top code of the source's bit depth (255 for 8 bits, 1023 for 10).
    limit = args.limit if args.limit < 1 else float((1 << int(meta["video"].get("bit_depth") or 8)) - 1)
    rects = detect(args.input, args.seconds, args.samples, limit, args.round_to, duration, failed,
                   square_pixels(meta["video"]), (sw, sh))
    # windows_failed: a window ffmpeg could not decode was skipped without a word, so a
    # crop measured on one window of five read as well-founded as one measured on all five
    result: Dict = {"file": args.input, "source_width": sw, "source_height": sh,
                    "windows": args.samples, "windows_failed": len(failed)}
    if failed:
        warn(f"cropdetect could not decode {len(failed)} of {args.samples} sampled windows; the crop rests on the other "
             f"{args.samples - len(failed)}: {failed[-1]['error']}", "cropdetect_windows_failed",
             failed=len(failed), windows=args.samples, starts=[f["start"] for f in failed])
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
