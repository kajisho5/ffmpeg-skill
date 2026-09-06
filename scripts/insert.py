#!/usr/bin/env python3
"""Turn a still image into a silent, timed video clip.

Produces a fixed-duration, constant-frame-rate video from one image -- for
example a title card, an end slate, or a placeholder to slot into join.py
alongside real footage. The output has no audio track: pair it with audio.py
or export.py's own audio handling if the surrounding edit needs sound under
the still.

--width/--height set the output frame size the same way fit.py does: give
one and the other follows the image's own aspect; give both for an exact
frame (the image is scaled to fill it, centre-cropping any excess -- never
distorted). Omit both to keep the image's native size (evened for 4:2:0).

Examples:
  python3 insert.py title.png --duration 3
  python3 insert.py slate.jpg --duration 5 --width 1920 --height 1080 --fps 30 -o slate.mp4
"""
import argparse
import sys

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, video_args


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="still image (PNG/JPG/...)")
    ap.add_argument("-o", "--output", help="output file (default: <name>_insert.mp4)")
    ap.add_argument("--duration", required=True, help="clip duration (seconds or mm:ss)")
    ap.add_argument("--width", type=int, help="output width in px; with --height also given, both are used directly")
    ap.add_argument("--height", type=int, help="output height in px; with --width also given, both are used directly")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate (default 30)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    target = parse_time(args.duration)
    if target <= 0:
        die("--duration must be > 0")
    if args.fps <= 0:
        die("--fps must be > 0")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no image/video stream")
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    ratio = sw / sh

    if args.width and args.height:
        out_w, out_h = even(args.width), even(args.height)
    elif args.width:
        out_w = even(args.width)
        out_h = even(out_w / ratio)
    elif args.height:
        out_h = even(args.height)
        out_w = even(out_h * ratio)
    else:
        out_w, out_h = even(sw), even(sh)

    vf = [
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase",
        f"crop={out_w}:{out_h}",
        "setsar=1",
        f"fps={args.fps:g}",
    ]

    output = args.output or default_output(args.input, "insert", "mp4")
    cmd = ffmpeg_base() + ["-loop", "1", "-i", args.input, "-t", f"{target:.3f}", "-vf", ",".join(vf)]
    cmd += video_args(None, args.crf, args.preset)
    cmd += ["-an", output]
    run(cmd)

    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
