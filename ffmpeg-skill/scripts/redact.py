#!/usr/bin/env python3
"""Blur, pixelate, or interpolate away an exact pixel rectangle for the whole clip.

{x, y, width, height} are literal pixel offsets and dimensions in the SOURCE
frame, the same convention as crop.py -- this tool needs the rectangle
already known (a saved detection box, a hand-picked region); it does not
locate faces, plates, logos or burned-in text itself. The rest of the frame
is untouched.

--mode blur (default) applies a strong box blur inside the rectangle;
--mode pixelate mosaics it into large blocks -- the more recognisable,
unmistakably-redacted look often wanted for compliance/legal footage.
--mode delogo fills the rectangle from the picture around it (ffmpeg's
delogo filter): a fixed logo or burned-in line, not inpainting, and not a
region that moves. delogo reads a 1 px ring outside the box, so the box
cannot touch the frame edge, and it only interpolates 8-bit YUV (an HDR or
10-bit source is refused; color.py --to-sdr first).
The region stays one mode for the whole clip; for a region that only needs
covering part of the timeline, cut the clip into segments first (cut.py)
and redact only the relevant one.

Examples:
  python3 redact.py interview.mp4 --x 820 --y 140 --width 240 --height 240
  python3 redact.py dashcam.mp4 --x 0 --y 900 --width 400 --height 120 --mode pixelate --block-size 16
  python3 redact.py branded.mp4 --x 40 --y 20 --width 180 --height 60 --mode delogo
"""
import argparse
import sys

from _common import add_common, overlay_format, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args, X264_PRESETS, fmt_secs
from _common.emit import note
from _common.probe import display_size, square_pixels, square_pixels_note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_redact.<ext>)")
    ap.add_argument("--x", type=int, required=True, help="left edge of the rectangle, in source pixels")
    ap.add_argument("--y", type=int, required=True, help="top edge of the rectangle, in source pixels")
    ap.add_argument("--width", type=int, required=True, help="rectangle width in px (must be even)")
    ap.add_argument("--height", type=int, required=True, help="rectangle height in px (must be even)")
    ap.add_argument("--mode", choices=["blur", "pixelate", "delogo"], default="blur",
                     help="blur (default), pixelate, or delogo (interpolate a fixed rectangle away; not inpainting, and not a moving region)")
    ap.add_argument("--blur-strength", type=int, default=20, help="box-blur radius in px, --mode blur only (default 20)")
    ap.add_argument("--block-size", type=int, default=12, help="mosaic block size in px, --mode pixelate only (default 12)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (default 0)")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
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
    # the rectangle is in the displayed frame: rotation applied, and a non-square-pixel source
    # squared at its display aspect first (#411), the frame look.py and cropdetect.py show
    sw, sh = display_size(meta["video"])
    square = square_pixels(meta["video"])
    if square:
        note(square_pixels_note(meta["video"]))
    if args.x + args.width > sw or args.y + args.height > sh:
        die(f"redaction rectangle ({args.x},{args.y},{args.width}x{args.height}) exceeds the source frame ({sw}x{sh})")
    if args.mode == "delogo":
        # delogo's band is fixed at 1 px (the option was removed; 5.1 through current all
        # expand the box by that ring and refuse it when the ring leaves the frame).
        vinfo = meta["video"]
        if vinfo.get("bt2020_or_hdr") or (vinfo.get("bit_depth") or 8) > 8:
            die(f"--mode delogo interpolates 8-bit YUV only (this source is {vinfo.get('pix_fmt') or 'not 8-bit'}); "
                "color.py --to-sdr first")
        if args.x < 1 or args.y < 1 or args.x + args.width >= sw or args.y + args.height >= sh:
            die(f"--mode delogo needs a 1 px ring of picture around the rectangle "
                f"({args.x},{args.y},{args.width}x{args.height} in {sw}x{sh}); "
                "a logo on the frame edge is out of range")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")

    output = args.output or default_output(args.input, "redact")
    if args.mode == "delogo":
        cmd = ffmpeg_base() + ["-i", args.input, "-vf",
                               (square + "," if square else "") + f"delogo=x={args.x}:y={args.y}:w={args.width}:h={args.height}",
                               "-map", "0:v:0"]
    else:
        # exact=1: crop rounds an odd x/y down to the chroma grid of a 4:2:0 frame otherwise, and
        # overlay always does, so an odd rectangle was taken from and put back one pixel up and
        # left (its last column and row left as they were, one outside it changed: A170). The
        # patch is taken exactly, given a transparent first column/row where x/y is odd, and put
        # at the even position before it: the luma inside the rectangle is replaced, the luma
        # outside is not (the chroma pair on an odd edge is shared, so it is half mixed)
        crop = f"crop={args.width}:{args.height}:{args.x}:{args.y}:exact=1"
        ox, oy = args.x % 2, args.y % 2
        if args.mode == "blur":
            # boxblur refuses a radius above half the plane: the chroma planes of 4:2:0 are half-size,
            # so they get their own (halved) radius; a 30 px region with the default 20 used to fail
            radius = max(1, min(args.blur_strength, min(args.width, args.height) // 2 - 1))
            # at least 1 wherever the chroma plane can hold it: radius // 2 alone was 0 at
            # --blur-strength 1, which left colour-only detail readable (review of #521). (FFmpeg
            # 7.1 refuses a chroma radius of 1 on a 2 px chroma plane, a 4 px wide region; 6.1
            # took it.) 0 is only a plane too small to blur: the luma still is
            chroma = max(0, min(max(1, radius // 2), (min(args.width, args.height) // 2 - 1) // 2))
            region = f"{crop},boxblur={radius}:{radius}:{chroma}:{radius}"
        else:
            region = f"{crop},scale={max(1, args.width // args.block_size)}:{max(1, args.height // args.block_size)}:flags=neighbor,scale={args.width}:{args.height}:flags=neighbor"
        if ox or oy:
            deep = overlay_format(meta)
            region += (f",format=yuva444p{'10le' if deep else ''},"
                       f"pad={args.width + 2 * ox}:{args.height + 2 * oy}:{ox}:{oy}:color=black@0")
        fc = (f"[0:v]{square + ',' if square else ''}split=2[base][region];[region]{region}[patched];"
              f"[base][patched]overlay={args.x - ox}:{args.y - oy}{overlay_format(meta)}[out]")
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
