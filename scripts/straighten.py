#!/usr/bin/env python3
"""Rotate a video by an arbitrary angle (horizon correction, not a 90/180/270 turn).

Distinct from fit.py --rotate, which only turns the picture in exact 90-degree
steps (swapping width/height, lossless in intent). This tool wraps FFmpeg's
rotate filter for a small corrective tilt -- "the horizon is 2 degrees off" --
which necessarily crops or pads the corners: rotating a rectangle by a
non-90-degree angle leaves triangular gaps at the corners. --fit crop scales
up just enough to fill the frame with no visible gap (losing a thin border
of the original picture); --fit pad keeps the full original picture inside
the rotated frame and fills the gaps with --fill-color.

This tool does not measure the tilt itself -- it has no way to find a
horizon line in a frame; that is a look.py/vision judgement call. Give the
degrees once you can see how far off it is.

Examples:
  python3 straighten.py tilted.mp4 --degrees -2.5
  python3 straighten.py handheld.mp4 --degrees 1.2 --fit pad --fill-color 0x101010
"""
import argparse
import math
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, validate_color, video_args, X264_PRESETS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_straighten.<ext>)")
    ap.add_argument("--degrees", type=float, required=True, help="rotation angle in degrees, -45..45, positive = clockwise")
    ap.add_argument("--fit", choices=["crop", "pad"], default="crop",
                     help="crop (default): scale up to fill the frame, no visible corner gap; pad: keep the full picture, fill the corner gaps with --fill-color")
    ap.add_argument("--fill-color", default="black", help="corner fill colour with --fit pad (default black)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (default 0)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be positive, got {args.fps:g}")

    if not -45 <= args.degrees <= 45:
        die(f"--degrees must be -45..45, got {args.degrees:g}")
    if args.degrees == 0:
        die("--degrees must be nonzero (nothing to straighten)")
    validate_color(args.fill_color, "--fill-color")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    output = args.output or default_output(args.input, "straighten")

    radians = math.radians(args.degrees)
    if args.fit == "pad":
        rotate = (f"rotate={radians:.8f}:fillcolor={args.fill_color}:"
                  f"ow=trunc(rotw({radians:.8f})/2)*2:oh=trunc(roth({radians:.8f})/2)*2")
    else:
        # Pre-scale the frame up by a safe, conservative factor (|cos|+|sin|, the exact growth
        # factor for a square, over-generous for a rectangle) so the rotated content fully
        # covers the original W:H window with no black corner, then rotate in place (canvas
        # stays at the scaled size) and crop back down to the original W:H, centred.
        s = abs(math.cos(radians)) + abs(math.sin(radians))
        # crop dimensions must round down to even (4:2:0 chroma); trunc(.../2)*2 floors to the
        # nearest even value instead of leaving an odd width/height that the encoder would refuse.
        rotate = f"scale=iw*{s:.8f}:ih*{s:.8f},rotate={radians:.8f},crop=trunc(iw/{s:.8f}/2)*2:trunc(ih/{s:.8f}/2)*2"

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", rotate, "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", f"0:a:{args.audio_stream}?"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, degrees={args.degrees:g}, fit={args.fit})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
