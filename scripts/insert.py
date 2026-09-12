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

--zoom in|out applies a Ken Burns effect: a slow, linear zoom across the
clip's duration (--zoom-amount sets the end/start zoom factor, default 1.3 =
30% zoomed in by the end). --pan left|right|up|down drifts the visible
window across the image while zoomed (ignored, with a warning, if --zoom is
not also given -- panning needs the extra image area a zoom exposes).

Examples:
  python3 insert.py title.png --duration 3
  python3 insert.py slate.jpg --duration 5 --width 1920 --height 1080 --fps 30 -o slate.mp4
  python3 insert.py photo.jpg --duration 6 --zoom in --pan right --width 1920 --height 1080
"""
import argparse
import math
import sys

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, video_args, X264_PRESETS, time_arg, fmt_secs


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
    ap.add_argument("--zoom", choices=["in", "out"], help="Ken Burns: slow linear zoom in or out across the clip")
    ap.add_argument("--zoom-amount", type=float, default=1.3, help="end (zoom in) or start (zoom out) zoom factor, > 1.0 (default 1.3)")
    ap.add_argument("--pan", choices=["left", "right", "up", "down"], help="drift the visible window this direction while zoomed (needs --zoom)")
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
    if args.zoom_amount <= 1.0:
        die(f"--zoom-amount must be > 1.0, got {args.zoom_amount}")
    if args.pan and not args.zoom:
        die("--pan needs --zoom in|out")

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

    if args.zoom:
        frames = max(1, round(target * args.fps))
        amount = args.zoom_amount
        if args.zoom == "in":
            zexpr = f"if(eq(on,0),1,min(zoom+{(amount - 1) / frames:.8f},{amount:g}))"
        else:
            zexpr = f"if(eq(on,0),{amount:g},max(zoom-{(amount - 1) / frames:.8f},1))"
        pan_x = {
            "left": f"(iw-iw/zoom)*(1-on/{frames})",
            "right": f"(iw-iw/zoom)*on/{frames}",
        }.get(args.pan, "iw/2-(iw/zoom/2)")
        pan_y = {
            "up": f"(ih-ih/zoom)*(1-on/{frames})",
            "down": f"(ih-ih/zoom)*on/{frames}",
        }.get(args.pan, "ih/2-(ih/zoom/2)")
        # zoompan samples from the still at its native resolution; scale it up first so the
        # zoomed-in crop still has real pixels to draw from instead of upscaling blur.
        upscale = max(2, math.ceil(amount * 2))
        vf = [
            f"scale={out_w * upscale}:{out_h * upscale}:force_original_aspect_ratio=increase",
            f"crop={out_w * upscale}:{out_h * upscale}",
            f"zoompan=z='{zexpr}':x='{pan_x}':y='{pan_y}':d={frames}:s={out_w}x{out_h}:fps={args.fps:g}",
            "setsar=1",
        ]
    else:
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

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
