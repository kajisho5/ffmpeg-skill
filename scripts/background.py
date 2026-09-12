#!/usr/bin/env python3
"""Generate a solid-colour or two-colour gradient background clip.

No input file: a silent, fixed-duration, exact-size clip generated entirely
by ffmpeg's own source filters (`color` for solid, `gradients` for a
two-colour gradient) -- for a title card background, a placeholder behind a
logo, or a base layer for overlay.py to composite onto.

Examples:
  python3 background.py --duration 3 --width 1920 --height 1080 --color 0x101010
  python3 background.py --duration 5 --width 1080 --height 1920 --gradient 0xff6a00:0x0057ff --angle 45
"""
import argparse
import math
import sys

from _common import add_common, apply_common, die, emit, ffmpeg_base, info, parse_time, probe, run, validate_color, video_args, X264_PRESETS, time_arg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", required=True, help="output file")
    ap.add_argument("--duration", required=True, help="clip duration (seconds or mm:ss)")
    ap.add_argument("--width", type=int, required=True, help="output width in px (must be even)")
    ap.add_argument("--height", type=int, required=True, help="output height in px (must be even)")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate (default 30)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--color", default="black", help="solid background colour, e.g. black, 0x101010 (default black)")
    src.add_argument("--gradient", help="two colours as C1:C2 for a linear gradient, e.g. 0xff6a00:0x0057ff")
    ap.add_argument("--angle", type=float, default=0.0, help="gradient angle in degrees (with --gradient, default 0 = left to right)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    target = time_arg(args.duration, "--duration", args.fps)
    if target <= 0:
        die("--duration must be > 0")
    if args.fps <= 0:
        die("--fps must be > 0")
    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")

    if args.gradient:
        try:
            c0, c1 = args.gradient.split(":")
        except ValueError:
            die(f"--gradient needs two colours as C1:C2, got '{args.gradient}'")
        validate_color(c0, "--gradient")
        validate_color(c1, "--gradient")
        rad = math.radians(args.angle)
        x1 = round(args.width * math.cos(rad))
        y1 = round(args.width * math.sin(rad))
        # gradients defaults to seed=-1 (a random seed picked fresh each run) and speed=0.01 (a
        # slow rotation applied every frame), so without pinning both, this "static" background
        # was neither reproducible between runs nor actually static across its own duration --
        # violating the bit_exact/deterministic contract _contract.py declares for this tool.
        # speed's own valid range bottoms out at 1e-05 (0 is refused), so that's the closest to
        # motionless the filter allows.
        src_filter = f"gradients=size={args.width}x{args.height}:rate={args.fps:g}:c0={c0}:c1={c1}:x0=0:y0=0:x1={x1}:y1={y1}:seed=0:speed=1e-05"
    else:
        validate_color(args.color, "--color")
        src_filter = f"color=c={args.color}:size={args.width}x{args.height}:rate={args.fps:g}"

    output = args.output
    cmd = ffmpeg_base() + ["-f", "lavfi", "-i", src_filter, "-t", f"{target:.3f}"]
    cmd += video_args(None, args.crf, args.preset)
    cmd += ["-an", output]
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
