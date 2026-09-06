#!/usr/bin/env python3
"""Crop a video to an exact pixel rectangle.

{x, y, width, height} are literal pixel offsets and dimensions in the SOURCE
frame, not aspect-ratio-relative -- for cropping to a target aspect ratio
(e.g. 16:9 -> 9:16) use fit.py --fit crop instead, which computes the
rectangle for you and lets you steer it with --crop-x/--crop-y. This tool is
for when the caller already knows the exact rectangle (a face-detection box,
a saved crop from a previous edit, a hand-picked region).

The rectangle must lie entirely inside the source frame after accounting for
any display rotation, and --width/--height must be even (required for 4:2:0
chroma subsampling, the pixel format every encoder here uses) -- given values
are validated and refused, never silently rounded, since a caller-specified
rectangle should do exactly what was asked or fail loudly.

Examples:
  python3 crop.py input.mp4 --x 100 --y 0 --width 1080 --height 1920
  python3 crop.py input.mp4 --x 0 --y 140 --width 1920 --height 800 -o cropped.mp4
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run, video_args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_crop.<ext>)")
    ap.add_argument("--x", type=int, required=True, help="left edge of the crop rectangle, in source pixels")
    ap.add_argument("--y", type=int, required=True, help="top edge of the crop rectangle, in source pixels")
    ap.add_argument("--width", type=int, required=True, help="crop width in px (must be even)")
    ap.add_argument("--height", type=int, required=True, help="crop height in px (must be even)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.x < 0 or args.y < 0:
        die(f"--x/--y must be >= 0, got x={args.x} y={args.y}")
    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        sw, sh = sh, sw
    if args.x + args.width > sw or args.y + args.height > sh:
        die(f"crop rectangle ({args.x},{args.y},{args.width}x{args.height}) exceeds the source frame ({sw}x{sh})")
    has_audio = bool(meta.get("audio"))

    output = args.output or default_output(args.input, "crop")
    vf = [f"crop={args.width}:{args.height}:{args.x}:{args.y}", "setsar=1"]
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", ",".join(vf)]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
