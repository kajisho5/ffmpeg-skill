#!/usr/bin/env python3
"""Crop a video to an exact pixel rectangle (an alias of fit.py --rect since 4.19).

{x, y, width, height} are literal pixel offsets and dimensions in the SOURCE
frame, not aspect-ratio-relative -- for cropping to a target aspect ratio
(e.g. 16:9 -> 9:16) use fit.py --fit crop instead, which computes the
rectangle for you and lets you steer it with --crop-x/--crop-y. This tool is
for when the caller already knows the exact rectangle (a face-detection box,
a saved crop from a previous edit, a hand-picked region). It runs the code
fit.py --rect W:H:X:Y runs and writes the same file; new commands use that.

--width/--height without --x/--y (or with --center) is a centred box. The
rectangle must lie entirely inside the source frame after accounting for
any display rotation, and --width/--height must be even (required for 4:2:0
chroma subsampling, the pixel format every encoder here uses) -- given values
are validated and refused, never silently rounded, since a caller-specified
rectangle should do exactly what was asked or fail loudly. An odd --x/--y is
taken as given (the crop starts on that pixel), not moved to the chroma grid.

Examples:
  python3 crop.py input.mp4 --x 100 --y 0 --width 1080 --height 1920
  python3 crop.py input.mp4 --x 0 --y 140 --width 1920 --height 800 -o cropped.mp4
  python3 crop.py input.mp4 --width 1080 --height 1080          # centred
"""
import argparse
import re
import sys

from _common import add_common, apply_common, die, X264_PRESETS
from fit import crop_rect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_crop.<ext>)")
    ap.add_argument("--rect", metavar="W:H:X:Y", help="the box in one value, fit.py --rect's order (W:H alone: centred), instead of the four options below")
    ap.add_argument("--x", type=int, help="left edge of the crop rectangle, in source pixels (with --y; both left out: centred)")
    ap.add_argument("--y", type=int, help="top edge of the crop rectangle, in source pixels")
    ap.add_argument("--width", type=int, help="crop width in px (must be even); a size WxH is --width W --height H")
    ap.add_argument("--height", type=int, help="crop height in px (must be even)")
    ap.add_argument("--center", action="store_true", help="centre the box (what leaving --x/--y out does)")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    if args.rect is not None:
        if not re.fullmatch(r"\d+:\d+(:\d+:\d+)?", args.rect) or any(v is not None for v in (args.x, args.y, args.width, args.height)):
            die(f"give the box as --rect W:H:X:Y or W:H (centred), or as --width --height [--x --y], got {args.rect!r}")
        args.width, args.height, *xy = (int(n) for n in args.rect.split(":"))
        args.x, args.y = xy or (None, None)
    if args.width is None or args.height is None or (args.x is None) != (args.y is None) or (args.center and args.x is not None):
        die("give the box as --width W --height H, with --x X --y Y for its corner or neither (centred), or as --rect W:H:X:Y")
    return crop_rect(args, args.width, args.height, args.x, args.y, "crop")


if __name__ == "__main__":
    sys.exit(main())
