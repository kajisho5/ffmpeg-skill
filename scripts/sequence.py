#!/usr/bin/env python3
"""Turn a numbered image sequence into a video.

--pattern accepts either a printf-style numbered pattern (`frame_%04d.png`,
resolved relative to --dir) or a glob (`*.png`, matched and sorted
alphabetically) -- detected by whether the pattern contains a `%`. Either
way, the actual frame list is resolved and checked on disk before ffmpeg
runs (an empty match or a missing first frame is refused here, not
discovered from an opaque ffmpeg error), then fed to ffmpeg as an explicit
concat list -- not `-pattern_type glob`, which several real ffmpeg builds
(the Windows Chocolatey package, for one) compile without.

Examples:
  python3 sequence.py --dir frames --pattern "frame_%04d.png" --fps 24 -o out.mp4
  python3 sequence.py --dir frames --pattern "*.png" --fps 30 --start-number 1
"""
import argparse
import sys
import tempfile
from pathlib import Path

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, probe, run, video_args


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def _concat_list_line(path: Path) -> str:
    # concat demuxer file paths: backslash and single-quote need escaping inside the quoted form.
    escaped = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"


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
        frames = sorted(directory.glob(args.pattern))
        if not frames:
            die(f"no files in {args.dir} match glob '{args.pattern}'")
        info(f"found {len(frames)} frames matching '{args.pattern}'")
    else:
        try:
            args.pattern % args.start_number
        except (TypeError, ValueError):
            die(f"bad printf pattern '{args.pattern}'")
        frames = []
        i = args.start_number
        while (directory / (args.pattern % i)).exists():
            frames.append(directory / (args.pattern % i))
            i += 1
        if not frames:
            die(f"first frame not found: {directory / (args.pattern % args.start_number)} (check --pattern / --start-number)")
        info(f"found {len(frames)} consecutive frames from index {args.start_number}")

    frame_meta = probe(str(frames[0]))
    if not frame_meta.get("video"):
        die(f"{frames[0]} is not a readable image")
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
    frame_duration = 1.0 / args.fps

    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-sequence-") as tmp:
        list_path = Path(tmp) / "frames.txt"
        lines = []
        for f in frames:
            lines.append(_concat_list_line(f.resolve()))
            lines.append(f"duration {frame_duration:.6f}")
        lines.append(_concat_list_line(frames[-1].resolve()))  # concat demuxer: last entry's duration is ignored, so repeat it
        list_path.write_text("\n".join(lines), encoding="utf-8")

        cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", str(list_path)]
        vf = [f"scale={out_w}:{out_h}", "setsar=1", f"fps={args.fps:g}"]
        cmd += ["-vf", ",".join(vf)]
        cmd += video_args(None, args.crf, args.preset)
        # The concat demuxer's trailing repeated-last-file trick (needed so the last real file's
        # duration line takes effect) has been observed to produce an extra frame's worth of
        # duration on some ffmpeg builds -- force the exact intended length rather than trust it.
        total_duration = len(frames) * frame_duration
        cmd += ["-t", f"{total_duration:.6f}", "-an", output]
        run(cmd)

    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
