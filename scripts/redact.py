#!/usr/bin/env python3
"""Blur or pixelate an exact pixel rectangle for the whole clip (privacy redaction, license plates, faces).

{x, y, width, height} are literal pixel offsets and dimensions in the SOURCE
frame, the same convention as crop.py -- this tool needs the rectangle
already known (a saved detection box, a hand-picked region); it does not
locate faces or plates itself. The rest of the frame is untouched.

--mode blur (default) applies a strong box blur inside the rectangle;
--mode pixelate mosaics it into large blocks -- the more recognisable,
unmistakably-redacted look often wanted for compliance/legal footage.
The region stays --mode blur/pixelate for the whole clip; for a region that
only needs covering part of the timeline, cut the clip into segments first
(cut.py) and redact only the relevant one.

Examples:
  python3 redact.py interview.mp4 --x 820 --y 140 --width 240 --height 240
  python3 redact.py dashcam.mp4 --x 0 --y 900 --width 400 --height 120 --mode pixelate --block-size 16
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args, X264_PRESETS, fmt_secs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_redact.<ext>)")
    ap.add_argument("--x", type=int, required=True, help="left edge of the rectangle, in source pixels")
    ap.add_argument("--y", type=int, required=True, help="top edge of the rectangle, in source pixels")
    ap.add_argument("--width", type=int, required=True, help="rectangle width in px (must be even)")
    ap.add_argument("--height", type=int, required=True, help="rectangle height in px (must be even)")
    ap.add_argument("--mode", choices=["blur", "pixelate"], default="blur", help="blur (default) or pixelate the rectangle")
    ap.add_argument("--blur-strength", type=int, default=20, help="box-blur radius in px, --mode blur only (default 20)")
    ap.add_argument("--block-size", type=int, default=12, help="mosaic block size in px, --mode pixelate only (default 12)")
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

    if args.x < 0 or args.y < 0:
        die(f"--x/--y must be >= 0, got x={args.x} y={args.y}")
    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")
    if args.blur_strength <= 0:
        die(f"--blur-strength must be > 0, got {args.blur_strength}")
    if args.block_size <= 1:
        die(f"--block-size must be > 1, got {args.block_size}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        sw, sh = sh, sw
    if args.x + args.width > sw or args.y + args.height > sh:
        die(f"redaction rectangle ({args.x},{args.y},{args.width}x{args.height}) exceeds the source frame ({sw}x{sh})")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")

    output = args.output or default_output(args.input, "redact")
    crop = f"crop={args.width}:{args.height}:{args.x}:{args.y}"
    if args.mode == "blur":
        region = f"{crop},boxblur={args.blur_strength}:{args.blur_strength}"
    else:
        region = f"{crop},scale={max(1, args.width // args.block_size)}:{max(1, args.height // args.block_size)}:flags=neighbor,scale={args.width}:{args.height}:flags=neighbor"
    fc = f"[0:v]split=2[base][region];[region]{region}[patched];[base][patched]overlay={args.x}:{args.y}[out]"
    cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", fc, "-map", "[out]"]
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
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {args.mode} at x={args.x} y={args.y} {args.width}x{args.height})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
