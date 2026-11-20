#!/usr/bin/env python3
"""Turn a numbered image sequence into a video.

--pattern accepts either a printf-style numbered pattern (`frame_%04d.png`,
resolved relative to --dir) or a glob (`*.png`, matched and sorted
in natural name order) -- detected by whether the pattern contains a `%`. Either
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
import hashlib
import json
import os
import re
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from _common import STATE, add_common, apply_common, default_output, die, emit, ffmpeg_base, fingerprint, info, probe, refuse_output_is_input, require_tool, run, video_args, X264_PRESETS, concat_list_line, fmt_secs
from _common.emit import note, refuse, warn
from _common.probe import display_size, square_pixels_note
from _common.runner import register_plan_input
from _common.timeline import TimelineError, exact_rate

SEQUENCE_PLAN_ENV = "FFMPEG_SKILL_REPLAY_SEQUENCE_FRAMES"


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


def undecodable_frames(list_path: Path, frames: list, rate: Fraction) -> "list | None":
    """The frames of the list that do not decode to a picture, in order; None when the check could
    not be made (ffprobe failed). ffprobe decodes the same concat list the encode reads, so a frame
    is what the encode would get: frame i is decoded at the i-th start the list gives it. Only the
    first frame was probed, and a later one that was not an image (a text file named .png, a
    truncated PNG) was left out by the decoder while the fps filter repeated its neighbour: the run
    completed with that frame missing (#529)."""
    proc = run([require_tool("ffprobe"), "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-select_streams", "v:0", "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0"],
               quiet=True, check=False)
    if proc.returncode != 0:
        return None
    decoded = set()
    for line in proc.stdout.splitlines():
        try:
            decoded.add(round(float(line.strip().rstrip(",")) * rate))
        except ValueError:
            continue
    if not decoded:
        # the first frame was probed as an image, so it decodes: nothing read back is a check that
        # did not happen, not every frame missing
        return None
    return [f for i, f in enumerate(frames) if i not in decoded]


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


def argument_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="directory containing the frames")
    ap.add_argument("--pattern", required=True, help="printf pattern (frame_%%04d.png) or glob (*.png)")
    ap.add_argument("-o", "--output", help="output file (default: <dir>_sequence.mp4)")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate, the framerate (default 30)")
    ap.add_argument("--start-number", type=int, default=0, help="first frame index, for a printf pattern (default 0)")
    ap.add_argument("--width", type=int, help="output width in px; with --height also given, both are used directly")
    ap.add_argument("--height", type=int, help="output height in px; with --width also given, both are used directly")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    return ap


def frame_paths(directory: Path, pattern: str, start: int) -> "tuple[list[Path], int | None]":
    """Select the frames the encoder sees. The next printf index marks the first gap."""
    if "%" not in pattern:
        # Natural order, with a deterministic tie-break for names like frame2 and frame02.
        return sorted(directory.glob(pattern), key=lambda p: (natural_key(p.name), str(p))), None
    frames = []
    i = start
    while (directory / (pattern % i)).exists():
        frames.append(directory / (pattern % i))
        i += 1
    return frames, i


def frame_digest(records: list[dict]) -> str:
    """Bind exact frame fingerprints in order with a compact value for the replay child."""
    digest = hashlib.sha256()
    for frame in records:
        digest.update(json.dumps(frame, sort_keys=True).encode("ascii") + b"\n")
    return digest.hexdigest()


def replay_frame_digest(argv: list[str]) -> "str | None":
    """Check the current sequence without running a probe or an encode during replay's dry run."""
    try:
        args = argument_parser().parse_args(argv)
        frames, _ = frame_paths(Path(args.dir), args.pattern, args.start_number)
        paths = [f.resolve(strict=True) for f in frames]
        return frame_digest([fingerprint(str(f), complete=True) for f in paths])
    except (OSError, RuntimeError, TypeError, ValueError, SystemExit):
        return None


def main() -> int:
    args = argument_parser().parse_args()
    apply_common(args)

    if args.fps <= 0:
        die("--fps must be > 0")
    for flag, value in (("--width", args.width), ("--height", args.height)):
        # A109: 0 read as "not given" and a negative size reached ffmpeg (kind ffmpeg)
        if value is not None and value < 1:
            die(f"{flag} must be a positive number of pixels, got {value}")
    try:
        rate = exact_rate(args.fps)  # 29.97 is 30000/1001, as every other tool reads it
    except TimelineError as exc:
        die(f"--fps: {exc}")
    directory = Path(args.dir)
    expected = os.environ.get(SEQUENCE_PLAN_ENV)
    if not directory.is_dir():
        if expected:
            refuse("input", "plan_inputs_changed", f"the planned frame directory is unavailable: {args.dir}")
        die(f"--dir not found or not a directory: {args.dir}")
    try:
        frames, next_index = frame_paths(directory, args.pattern, args.start_number)
        resolved = [f.resolve(strict=True) for f in frames]
        for frame in resolved:
            if not frame.is_file():
                reason = "plan_inputs_changed" if expected else "media_path_not_a_file"
                refuse("input", reason, f"{str(frame)!r} is not a regular image file", path=str(frame))
        records = [fingerprint(str(f), complete=True) for f in resolved] if STATE.plan or expected else []
        digest = frame_digest(records) if STATE.plan or expected else None
    except (OSError, RuntimeError) as exc:
        if expected:
            refuse("input", "plan_inputs_changed", f"could not read the planned sequence: {exc}")
        die(f"could not read the frame sequence: {exc}")
    except (TypeError, ValueError):
        die(f"bad frame pattern '{args.pattern}'")
    if expected and digest != expected:
        refuse("input", "plan_inputs_changed",
               "the ordered sequence frames differ from what was planned; make a new plan",
               expected_frame_digest=expected, actual_frame_digest=digest)
    if next_index is None:
        if not frames:
            die(f"no files in {args.dir} match glob '{args.pattern}'")
        info(f"found {len(frames)} frames matching '{args.pattern}'")
    else:
        if not frames:
            die(f"first frame not found: {directory / (args.pattern % args.start_number)} (check --pattern / --start-number)")
        info(f"found {len(frames)} consecutive frames from index {args.start_number}")
        # 2.2.1: frames past a gap in the numbering (one render or export step that failed) used
        # to be dropped silently, giving a shorter video; name the gap and what was left out
        later = _frames_after(directory, args.pattern, next_index)
        if later:
            warn(f"frame {args.pattern % next_index} is missing; {len(later)} later frame(s) "
                 f"(from {later[0].name}) are NOT in the sequence -- fill the gap or rename them", "sequence_gap",
                 missing=args.pattern % next_index, frames_left_out=len(later), first_left_out=later[0].name)

    # For --dir . or .., use the resolved name so the default is next to the frame folder.
    named = directory if directory.name not in ("", ".", "..") else directory.resolve()
    output = args.output or default_output(str(named).rstrip("/\\") or "sequence", "sequence", "mp4")
    # Keep both the chosen entry names and their targets safe, including hard links.
    sources = list(map(str, frames + resolved))
    refuse_output_is_input(output, *sources)
    if STATE.plan:
        refuse_output_is_input(STATE.plan, *sources)
        for frame in resolved:
            register_plan_input(frame)
        STATE.measured_plan_inputs.update((record["path"], record) for record in records)
        STATE.sequence_frames_sha256 = digest

    frame_meta = probe(str(resolved[0]))
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

    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-sequence-") as tmp:
        list_path = Path(tmp) / "frames.txt"
        if STATE.plan:
            STATE.plan_generated_inputs.add(str(list_path))
        list_path.write_text(concat_list(resolved, rate), encoding="utf-8")
        # every frame decodes, or the run is refused before the encode (a dry run too: ffprobe runs
        # under --dry-run, as every probe does), naming the frames that do not
        bad = undecodable_frames(list_path, frames, rate)
        if bad is None:
            note("the frames could not be checked before the encode (ffprobe failed on the frame list); "
                 "a frame that does not decode would be left out of the video")
        elif bad:
            names = ", ".join(f.name for f in bad[:5]) + (f" and {len(bad) - 5} more" if len(bad) > 5 else "")
            refuse("input", "still_unreadable",
                   f"{len(bad)} of {len(frames)} frames do not decode as an image ({names}); they would be "
                   "missing from the video. Replace or remove them",
                   path=str(bad[0]), frames=[str(f) for f in bad], frames_unreadable=len(bad), frames_total=len(frames))

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
