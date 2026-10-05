#!/usr/bin/env python3
"""Loop a clip a number of times, or to a target duration.

For a background loop, an ambient bed, or filling a fixed slot length with
a short clip. --times repeats the whole clip that many times back to back;
--duration instead loops (and, on the last repeat, trims) to hit an exact
target length. Audio loops along with the video when present. This tool
does not smooth the loop point (no crossfade at the seam) -- a clip that
doesn't already loop cleanly will show a visible cut/pop at each repeat;
that's a judgement call about the source material, not something a --times
or --duration flag can fix. --boomerang is the exception: it plays the clip
forward, then backward, so every repeat meets frames that match. Each
turnaround frame is shown once (frames 0..N-1, then N-2..1), so the motion
does not stall at either end. A boomerang is silent, because reversed sound
plays backwards; add a bed with audio.py. Like reverse.py, it holds the
decoded clip in memory.

Examples:
  python3 loop.py bg_loop.mp4 --times 3
  python3 loop.py texture.mp4 --duration 30
  python3 loop.py wave.mp4 --boomerang --times 4
"""
import argparse
import math
import sys

from _common import add_common, aac_args, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, video_args, X264_PRESETS, time_arg, fmt_secs


# The loop filter's size is capped at 32767 frames, so one boomerang cycle (2N-2 frames) must fit.
LOOP_FILTER_MAX_FRAMES = 32767


def _boomerang_graph(meta, src_dur: float, times) -> str:
    """Frames 0..N-1, then N-2..1, repeated: `times` round trips, or forever for --duration (-t ends it).

    The backward half is the source minus frame 0, reversed, minus its first frame (N-1). The
    forward half already shows both ends, so each turnaround appears once. That is unlike the
    common split/reverse/concat recipe, which shows frame N-1 twice and, on every repeat, frame 0
    twice. Trimming by frame index this way needs no frame count."""
    v = meta["video"]
    frames = v.get("nb_frames") or round((v.get("duration") or src_dur) * (v.get("fps") or 30.0))
    if frames < 3:
        die(f"--boomerang needs a clip of at least 3 frames, got {frames}")
    cycle = 2 * frames - 2
    if cycle > LOOP_FILTER_MAX_FRAMES:
        die(f"--boomerang cycle is {cycle} frames; ffmpeg's loop filter holds at most {LOOP_FILTER_MAX_FRAMES} "
            f"-- cut the clip shorter first (cut.py)")
    # reverse holds the clip's decoded frames; split, trim and loop pass references to the same
    # frames, so the peak is about one clip (measured: the same max RSS as a plain reverse)
    bytes_per_frame = v["width"] * v["height"] * 1.5 * (2 if (v.get("bit_depth") or 8) > 8 else 1)
    held = bytes_per_frame * frames
    if held > 2 * 1024 ** 3:
        info(f"warning: --boomerang holds about {held / 1024 ** 3:.1f} GiB of decoded frames in memory "
             f"({frames} frames of {v['width']}x{v['height']}) -- cut the clip shorter first (cut.py) if RAM is tight")
    repeats = -1 if times is None else times - 1
    # Retimed by frame index at the source's nominal rate: a VFR source's reversed half carries
    # its gaps mirrored, and a CFR conform after the graph duplicated a frame against them (a
    # turnaround shown twice), so the output is made constant-rate here and passed through as is.
    # fps= after setpts drops or repeats nothing; it tells the encoder the rate, whose time base
    # otherwise follows the source's r_frame_rate and rounds the new timestamps unevenly.
    rate = _nominal_rate(v)
    return ("[0:v]split[f][r];[f]setpts=PTS-STARTPTS[fw];"
            "[r]trim=start_frame=1,reverse,trim=start_frame=1,setpts=PTS-STARTPTS[bw];"
            f"[fw][bw]concat=n=2:v=1:a=0,loop=loop={repeats}:size={LOOP_FILTER_MAX_FRAMES},"
            f"setpts=N/(({rate})*TB),fps={rate}[v]")


# Above this a "frame rate" is a time base (90000/1 from MPEG-TS, 1000/1 from Matroska), not a rate.
MAX_PLAUSIBLE_FPS = 240


def _fraction(text):
    try:
        num, _, den = (text or "").partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return value if 0 < value <= MAX_PLAUSIBLE_FPS else None


def _nominal_rate(v) -> str:
    """The source's frame rate as an exact fraction: r_frame_rate when it is within 1% of the
    average (an iPhone clip: 60/1 against 59.95 from a 1/600 time base), else the average; with
    neither usable, frames over the video's duration, else 30."""
    r, avg = v.get("r_frame_rate"), v.get("avg_frame_rate")
    r_val, avg_val = _fraction(r), _fraction(avg)
    if r_val and (not avg_val or abs(r_val - avg_val) <= 0.01 * avg_val):
        return r
    if avg_val:
        return avg
    counted = (v.get("nb_frames") or 0) / (v.get("duration") or float("inf"))
    return f"{counted:g}" if 0 < counted <= MAX_PLAUSIBLE_FPS else "30"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_loop.<ext>)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--times", type=int, help="repeat the whole clip this many times (2 = original + 1 repeat)")
    group.add_argument("--duration", help="loop (and trim the last repeat) to hit exactly this target duration (seconds or mm:ss)")
    ap.add_argument("--boomerang", action="store_true",
                    help="play forward then backward (--times counts round trips; 1 is allowed); drops audio")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    src_dur = meta.get("duration") or 0.0
    if src_dur <= 0:
        die("input has no measurable duration to loop")
    has_audio = bool(meta.get("audio")) and not args.boomerang
    notes = []
    output = args.output or default_output(args.input, "loop")

    if args.times is not None:
        if args.times < (1 if args.boomerang else 2):
            die(f"--times must be >= 1 with --boomerang, got {args.times}" if args.boomerang else
                f"--times must be >= 2 (1 is just the original clip), got {args.times}")
        target = None
        stream_loop = args.times - 1
    else:
        target = time_arg(args.duration, "--duration", meta["video"].get("fps") if meta.get("video") else None)
        if target <= src_dur:
            die(f"--duration ({target:g}s) must be longer than the source ({src_dur:.3f}s) -- use cut.py to trim instead")
        stream_loop = math.ceil(target / src_dur) - 1

    if args.boomerang:
        cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", _boomerang_graph(meta, src_dur, args.times), "-map", "[v]"]
        if meta.get("audio"):
            notes.append("audio dropped: a boomerang plays half its sound backwards -- add a bed with audio.py")
    else:
        # -stream_loop repeats the whole input read (video and audio together) at the demuxer level
        # -- exact and lossless-in-intent for a re-encode target, unlike a filter-graph loop that
        # would need separate video/audio filters kept in lockstep by hand.
        cmd = ffmpeg_base() + ["-stream_loop", str(stream_loop), "-i", args.input]
    if target is not None:
        cmd += ["-t", f"{target:.3f}"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += ["-fps_mode", "passthrough"] if args.boomerang else cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, source {src_dur:.3f}s "
         f"{'boomeranged' if args.boomerang else 'looped'})")
    for note in notes:
        info(note)
    emit(output, boomerang=args.boomerang, **({"notes": notes} if notes else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
