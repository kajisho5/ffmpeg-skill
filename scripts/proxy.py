#!/usr/bin/env python3
"""Generate a small, low-bitrate proxy of a video: cheap for a machine to decode,
not meant for delivery. Intended for downstream AI analysis, preview or
editing-decision workflows that only need to look at (or feed a model) a
much smaller stand-in for the original.

Resizes to --width (default 640px, height follows the source aspect) or by
--scale factor, re-encodes at a proxy-grade --crf (default 30 - well above any
delivery preset's 18-24 in export.py, since a proxy trades visual quality for
size and speed), and always uses the fastest x264/x265 preset. Keeps the
source's own dynamic range (an HDR source proxies to HEVC10, same as every
other re-encoding tool here) rather than guessing whether SDR is wanted -
run color.py --to-sdr first if it is.

This tool only executes the spec it is given: it does not decide which asset
should be proxied, what resolution or bitrate is "right" for a given
downstream use, or what the proxy will be used for - those are the calling
agent's call.

Examples:
  python3 proxy.py input.mov                          # 640px wide, CRF 30, keeps audio
  python3 proxy.py input.mov --width 480 --no-audio    # smaller, video-only
  python3 proxy.py input.mov --scale 0.25 --fps 10     # quarter-size, 10fps (e.g. for a vision model)
"""
import argparse
import sys

from _common import add_common, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run, video_args, fmt_secs


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_proxy.<ext>)")
    ap.add_argument("--width", type=int, default=640, help="output width in px, height follows the source aspect (default 640)")
    ap.add_argument("--scale", type=float, help="scale factor applied to the source dimensions instead of --width (0 < scale <= 1)")
    ap.add_argument("--crf", type=int, default=30, help="proxy-grade CRF, higher = smaller/lower quality (default 30)")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate")
    ap.add_argument("--no-audio", action="store_true", help="drop audio entirely (default: keep it)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.scale is not None and not 0.0 < args.scale <= 1.0:
        die(f"--scale must be > 0 and <= 1, got {args.scale}")
    if args.width <= 0:
        die(f"--width must be > 0, got {args.width}")
    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be > 0, got {args.fps}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        sw = sh
    has_audio = bool(meta.get("audio")) and not args.no_audio

    out_w = even(sw * args.scale) if args.scale is not None else even(args.width)
    output = args.output or default_output(args.input, "proxy")

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", f"scale={out_w}:-2"]
    cmd += video_args(meta, args.crf, "veryfast")
    cmd += cfr_args(meta, args.fps)
    cmd += ["-c:a", "aac", "-b:a", "96k"] if has_audio else ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['codec']}, crf {args.crf})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
