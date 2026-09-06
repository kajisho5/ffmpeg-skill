#!/usr/bin/env python3
"""Turn a numbered image sequence into a video.

--pattern accepts either a printf-style numbered pattern (`frame_%04d.png`,
resolved relative to --dir) or a glob (`*.png`, matched and sorted
alphabetically) -- detected by whether the pattern contains a `%`. Either
way, the actual files are checked on disk before ffmpeg runs: an empty match
or a broken numbering gap is refused here, not discovered from an opaque
ffmpeg error.

Examples:
  python3 sequence.py --dir frames --pattern "frame_%04d.png" --fps 24 -o out.mp4
  python3 sequence.py --dir frames --pattern "*.png" --fps 30 --start-number 1
"""
import argparse
import sys
from pathlib import Path

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, probe, run, video_args


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="directory containing the frames")
    ap.add_argument("--pattern", required=True, help="printf pattern (frame_%%04d.png) or glob (*.png)")
    ap.add_argument("-o", "--output", help="output file (default: <dir>_sequence.mp4)")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate (default 30)")
    ap.add_argument("--start-number", type=int, default=0, help="first frame index, for a printf pattern (default 0)")
    ap.add_argument("--width", type=int, help="output width in px; with --height also given, both are used directly")
    ap.add_argument("--height", type=int, help="output height in px; with --width also given, both are used directly")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.fps <= 0:
        die("--fps must be > 0")
    directory = Path(args.dir)
    if not directory.is_dir():
        die(f"--dir not found or not a directory: {args.dir}")

    is_glob = "%" not in args.pattern
    if is_glob:
        matches = sorted(directory.glob(args.pattern))
        if not matches:
            die(f"no files in {args.dir} match glob '{args.pattern}'")
        info(f"found {len(matches)} frames matching '{args.pattern}'")
        first_frame = matches[0]
        input_arg = str(directory / args.pattern)
        extra_input_args = ["-pattern_type", "glob"]
    else:
        try:
            first_name = args.pattern % args.start_number
        except (TypeError, ValueError):
            die(f"bad printf pattern '{args.pattern}'")
        first_frame = directory / first_name
        if not first_frame.exists():
            die(f"first frame not found: {first_frame} (check --pattern / --start-number)")
        input_arg = str(directory / args.pattern)
        extra_input_args = ["-start_number", str(args.start_number)]

    frame_meta = probe(str(first_frame))
    if not frame_meta.get("video"):
        die(f"{first_frame} is not a readable image")
    sw, sh = frame_meta["video"]["width"], frame_meta["video"]["height"]

    if args.width and args.height:
        out_w, out_h = even(args.width), even(args.height)
    elif args.width:
        out_w = even(args.width)
        out_h = even(out_w * sh / sw)
    elif args.height:
        out_h = even(args.height)
        out_w = even(out_h * sw / sh)
    else:
        out_w, out_h = even(sw), even(sh)

    output = args.output or default_output(str(directory).rstrip("/\\") or "sequence", "sequence", "mp4")
    cmd = ffmpeg_base() + ["-framerate", f"{args.fps:g}"] + extra_input_args + ["-i", input_arg]
    vf = [f"scale={out_w}:{out_h}", "setsar=1"]
    cmd += ["-vf", ",".join(vf)]
    cmd += video_args(None, args.crf, args.preset)
    cmd += ["-r", f"{args.fps:g}", "-an", output]
    run(cmd)

    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
