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
import re
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, probe, run, video_args, X264_PRESETS, concat_list_line, fmt_secs
from _common.emit import note, warn
from _common.probe import display_size, square_pixels_note
from _common.timeline import TimelineError, exact_rate


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def _concat_list_line(path: Path) -> str:
    return concat_list_line(str(path))


def frame_durations(count: int, rate: Fraction) -> list:
    """The concat-list duration of each of `count` frames at `rate`, in whole microseconds: frame
    i lasts round(start(i+1)) - round(start(i)) with start(i) = i/rate, each position rounded
    once, so the demuxer's running sum is frame i's exact start to within half a microsecond at
    every frame (#474: 1/30 written 0.033333 fell 3.3e-7 s behind per frame, half a frame after
    about 50,000 frames)."""
    def at(i: int) -> int:
        return round(i * 1_000_000 / rate)
    return [at(i + 1) - at(i) for i in range(count)]


def concat_list(frames: list, rate: Fraction) -> str:
    """The concat-demuxer list for `frames` (paths) shown one frame each at `rate`."""
    lines = []
    framerate = f"option framerate {rate.numerator}/{rate.denominator}"
    for f, us in zip(frames, frame_durations(len(frames), rate)):
        lines.append(_concat_list_line(f))
        lines.append(framerate)
        lines.append(f"duration {us // 1_000_000}.{us % 1_000_000:06d}")
    lines.append(_concat_list_line(frames[-1]))  # concat demuxer: last entry's duration is ignored, so repeat it
    lines.append(framerate)
    return "\n".join(lines)


def natural_key(name: str) -> list:
    """img2 < img10: digit runs compare as numbers, the rest case-insensitively."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _frames_after(directory: Path, pattern: str, index: int) -> list:
    """Files in `directory` that match printf `pattern` with a number above `index`."""
    m = re.search(r"%0?(\d*)d", pattern)
    if not m:
        return []
    rx = re.compile("^" + re.escape(pattern[:m.start()]) + r"(\d+)" + re.escape(pattern[m.end():]) + "$")
    found = []
    for f in directory.iterdir():
        hit = rx.match(f.name)
        if hit and int(hit.group(1)) > index:
            found.append((int(hit.group(1)), f))
    return [f for _n, f in sorted(found)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="directory containing the frames")
    ap.add_argument("--pattern", required=True, help="printf pattern (frame_%%04d.png) or glob (*.png)")
    ap.add_argument("-o", "--output", help="output file (default: <dir>_sequence.mp4)")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate (default 30)")
    ap.add_argument("--start-number", type=int, default=0, help="first frame index, for a printf pattern (default 0)")
    ap.add_argument("--width", type=int, help="output width in px; with --height also given, both are used directly")
    ap.add_argument("--height", type=int, help="output height in px; with --width also given, both are used directly")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.fps <= 0:
        die("--fps must be > 0")
    try:
        rate = exact_rate(args.fps)  # 29.97 is 30000/1001, as every other tool reads it
    except TimelineError as exc:
        die(f"--fps: {exc}")
    directory = Path(args.dir)
    if not directory.is_dir():
        die(f"--dir not found or not a directory: {args.dir}")

    is_glob = "%" not in args.pattern
    if is_glob:
        # natural order: img2 before img10 (a lexical sort put every img1x before img2 and the
        # frames came out shuffled); a printf pattern never had this problem
        frames = sorted(directory.glob(args.pattern), key=lambda p: natural_key(p.name))
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
        # 2.2.1: frames past a gap in the numbering (one render or export step that failed) used
        # to be dropped silently, giving a shorter video; name the gap and what was left out
        later = _frames_after(directory, args.pattern, i)
        if later:
            warn(f"frame {args.pattern % i} is missing; {len(later)} later frame(s) "
                 f"(from {later[0].name}) are NOT in the sequence -- fill the gap or rename them", "sequence_gap",
                 missing=args.pattern % i, frames_left_out=len(later), first_left_out=later[0].name)

    frame_meta = probe(str(frames[0]))
    if not frame_meta.get("video"):
        die(f"{frames[0]} is not a readable image")
    # the displayed frame: an EXIF rotation applied, non-square pixels squared (#411)
    sw, sh = display_size(frame_meta["video"])
    if square_pixels_note(frame_meta["video"], "the first frame"):
        note(square_pixels_note(frame_meta["video"], "the first frame"))

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
    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-sequence-") as tmp:
        list_path = Path(tmp) / "frames.txt"
        list_path.write_text(concat_list([f.resolve() for f in frames], rate), encoding="utf-8")

        cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", str(list_path)]
        vf = [f"scale={out_w}:{out_h}", "setsar=1", f"fps={rate.numerator}/{rate.denominator}"]
        cmd += ["-vf", ",".join(vf)]
        # RGB (PNG) frames are converted to the BT.709 the line is tagged with (the first frame's probe)
        cmd += video_args(None, args.crf, args.preset, source=frame_meta)
        # The concat demuxer's trailing repeated-last-file trick (needed so the last real file's
        # duration line takes effect) has been observed to produce an extra frame's worth of
        # duration on some ffmpeg builds -- force the exact intended length rather than trust it.
        total_us = sum(frame_durations(len(frames), rate))
        cmd += ["-t", f"{total_us // 1_000_000}.{total_us % 1_000_000:06d}", "-an", output]
        run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['fps']:g}fps)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
