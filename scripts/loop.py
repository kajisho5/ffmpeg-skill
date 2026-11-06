#!/usr/bin/env python3
"""Loop a clip a number of times, or to a target duration.

For a background loop, an ambient bed, or filling a fixed slot length with
a short clip. --times repeats the whole clip that many times back to back;
--duration instead loops (and, on the last repeat, trims) to hit an exact
target length. Audio loops along with the video when present. Without
--crossfade the loop point is not smoothed: a clip that doesn't already loop
cleanly shows a visible cut/pop at each repeat. --crossfade S makes the clip
loop first: its last S seconds fade into its first S (picture and sound), so
one repeat is S shorter than the clip and every seam continues the motion;
--times 1 then writes a single seamless loop file. Every run measures its
seam (the picture step and the sound level step where a repeat meets the
next) and reports it next to the steady frame-to-frame step, so a caller can
see whether the seam still jumps. --boomerang is the other way: it plays the clip
forward, then backward, so every repeat meets frames that match. Each
turnaround frame is shown once (frames 0..N-1, then N-2..1), so the motion
does not stall at either end. A boomerang is silent, because reversed sound
plays backwards; add a bed with audio.py. Like reverse.py, it holds the
decoded clip in memory.

Examples:
  python3 loop.py bg_loop.mp4 --times 3
  python3 loop.py texture.mp4 --duration 30
  python3 loop.py wave.mp4 --boomerang --times 4
  python3 loop.py smoke.mp4 --crossfade 1 --duration 60
"""
import argparse
import json
import math
import os
import sys
import tempfile

from _common import STATE, concat_list_line, add_common, aac_args, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, parse_time, probe, refuse_output_is_input, require_filter, require_tool, run, video_args, X264_PRESETS, time_arg, fmt_secs
from _common.emit import warn
from _common.decision import av_trim
from _common.probe import decode_gray_frames, decode_pcm_mono


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
        warn(f"--boomerang holds about {held / 1024 ** 3:.1f} GiB of decoded frames in memory "
             f"({frames} frames of {v['width']}x{v['height']}) -- cut the clip shorter first (cut.py) if RAM is tight",
             "memory_heavy", bytes=int(held))
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


def concat_first_frame(listfile: str) -> float:
    """Where the first frame sits on the clock ffmpeg reads a concat list on: the list's first video
    start minus its start_time. The concat demuxer counts an MP4's hidden AAC priming packet into its
    start (-0.021 s) where the MP4 demuxer does not, so ffmpeg moves both streams 21 ms later, and a
    frame-rate time base then rounded the picture's move to 33 ms (12 ms off). 0.0 when unmeasured."""
    proc = run([require_tool("ffprobe"), "-v", "error", "-f", "concat", "-safe", "0", "-i", listfile,
                "-select_streams", "v:0", "-show_entries", "stream=start_time:format=start_time", "-of", "json"],
               quiet=True, check=False)
    try:
        doc = json.loads(proc.stdout or "")
        return float(doc["streams"][0]["start_time"]) - float(doc["format"]["start_time"])
    except (ValueError, KeyError, IndexError, TypeError):
        return 0.0


def _frame_count(v, rate: float, src_dur: float) -> int:
    return int(v.get("nb_frames") or round((v.get("duration") or src_dur) * rate))


def _conformed_frames(v, rate: float, src_dur: float) -> int:
    """The frames the crossfade's graph sees: the picture after fps=RATE, which fills a gap in a
    variable-rate stream and drops crowded frames, so its count follows the stream's length, not
    the frames stored (299 stored frames over 10 s at 30 fps come out 300). The unit's trims and
    its length are counted in these, or a repeat is a frame or more off the length planned."""
    # the video stream's length, else Matroska's tag, else the container's (main() refuses a source
    # without one): never the stored frame count, which is what fps= does not keep
    d = v.get("duration") or v.get("tagged_duration") or src_dur
    return int(round(float(d) * rate))


def _seamless_unit_cmd(meta, src: str, unit: str, rate: str, frames: int, fade_frames: int, has_audio: bool) -> list:
    """One repeat that loops on itself: the clip's last `fade_frames` fade into its first ones.

    The tail (frames N-F..N-1) is laid over the head (frames 0..F-1) with xfade, so the repeat
    starts on frame N-F, the frame the clip's own frame N-F-1 leads into: the repeat's end runs
    straight on into its start. Frames F..N-F-1 follow unchanged; the repeat is N-F frames. The
    sound does the same on the picture's clock (padded with silence to the picture's length
    first, so a short or late sound cannot shorten the fade). Written lossless
    (FFV1 + FLAC) to a temporary file the concat list then repeats, so the repeats cost one
    lossy encode, as without --crossfade."""
    fps = _fraction(rate) or 30.0
    fade = fade_frames / fps
    cut = (frames - fade_frames) / fps
    length = frames / fps
    # each branch re-states its rate after setpts: FFmpeg 7.x's setpts marks the frame rate
    # unknown (1/0) and xfade refuses anything but a constant one (6.1 kept it)
    graph = (f"[0:v:0]setpts=PTS-STARTPTS,fps={rate},split[vt][vb];"
             f"[vt]trim=start_frame={frames - fade_frames}:end_frame={frames},setpts=PTS-STARTPTS,fps={rate}[t];"
             f"[vb]trim=end_frame={frames - fade_frames},setpts=PTS-STARTPTS,fps={rate}[b];"
             f"[t][b]xfade=transition=fade:duration={fade:.6f}:offset=0[v]")
    maps = ["-map", "[v]"]
    if has_audio:
        # acrossfade writes nothing when its first input is exactly the fade long (FFmpeg 6.1 and
        # 7.1, measured), so the fade is built by hand: tail faded out + head faded in, summed
        graph += (f";[0:a:0]aresample=async=1:first_pts=0,apad,atrim=end={length:.6f},asplit=3[at][ah][ab];"
                  f"[at]atrim=start={cut:.6f},asetpts=PTS-STARTPTS,afade=t=out:d={fade:.6f}:curve=tri[ta];"
                  f"[ah]atrim=end={fade:.6f},asetpts=PTS-STARTPTS,afade=t=in:d={fade:.6f}:curve=tri[ha];"
                  f"[ta][ha]amix=inputs=2:normalize=0:duration=longest[xa];"
                  f"[ab]atrim=start={fade:.6f}:end={cut:.6f},asetpts=PTS-STARTPTS[ba];"
                  f"[xa][ba]concat=n=2:v=0:a=1[a]")
        maps += ["-map", "[a]", "-c:a", "flac"]
    else:
        maps += ["-an"]
    return ffmpeg_base() + ["-i", src, "-filter_complex", graph] + maps + ["-c:v", "ffv1", "-fps_mode", "passthrough", unit]


# Frames are compared at this size: enough to see a cut or a jump, a few KB per frame.
SEAM_W, SEAM_H = 64, 36


def _mean_step(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _rms_db(block) -> "float | None":
    if not block:
        return None
    rms = math.sqrt(sum(x * x for x in block) / len(block))
    return 20 * math.log10(rms) if rms > 1e-6 else -120.0


def _measure_seam(output: str, unit: float, out_dur: float, fps: float, has_audio: bool) -> dict:
    """The first seam of the written file, where repeat 1 meets repeat 2 (or, for a single repeat,
    the file's last frame against its first, as a player looping it would show them).

    video_step: the mean absolute luma difference (0-255, on a 64x36 grey copy) across the seam;
    video_typical_step: the median of the same difference between the neighbouring frames, so a
    caller can tell a seam that jumps (step far above typical) from a clip that is busy anyway.
    audio_level_step_db: the RMS level 20 ms after the seam minus 20 ms before it."""
    half = min(0.5, unit / 2)
    if out_dur - unit > 1.5 / fps:
        frames = decode_gray_frames(output, fps, SEAM_W, SEAM_H, start=unit - half, seconds=2 * half, check=False)
        at = round(half * fps)
        pair = (frames[at - 1], frames[at]) if 0 < at < len(frames) else None
        where = "between_repeats"
    else:
        head = decode_gray_frames(output, fps, SEAM_W, SEAM_H, seconds=half, check=False)
        tail = decode_gray_frames(output, fps, SEAM_W, SEAM_H, start=max(0.0, out_dur - half), check=False)
        frames = tail + head
        at = len(tail)
        pair = (tail[-1], head[0]) if tail and head else None
        where = "end_to_start"
    seam = {"at": where, "time": round(unit, 3) if where == "between_repeats" else None}
    if pair:
        steps = [_mean_step(frames[i - 1], frames[i]) for i in range(1, len(frames)) if i != at]
        seam["video_step"] = round(_mean_step(*pair), 2)
        seam["video_typical_step"] = round(sorted(steps)[len(steps) // 2], 2) if steps else None
    else:
        seam["video_step"] = seam["video_typical_step"] = None
    if has_audio:
        rate, win = 48000, 0.02
        if where == "between_repeats":
            pcm = decode_pcm_mono(output, rate, seconds=2 * win, start=unit - win, check=False)
            before, after = pcm[: int(rate * win)], pcm[int(rate * win):]
        else:
            after = decode_pcm_mono(output, rate, seconds=win, check=False)
            before = decode_pcm_mono(output, rate, start=max(0.0, out_dur - win), check=False)
        b, a = _rms_db(before), _rms_db(after)
        seam["audio_level_step_db"] = round(a - b, 1) if a is not None and b is not None else None
    return seam


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_loop.<ext>)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--times", type=int, help="repeat the whole clip this many times (2 = original + 1 repeat)")
    group.add_argument("--duration", help="loop (and trim the last repeat) to hit exactly this target duration (seconds or mm:ss)")
    ap.add_argument("--boomerang", action="store_true",
                    help="play forward then backward (--times counts round trips; 1 is allowed); drops audio")
    ap.add_argument("--crossfade", metavar="S",
                    help="fade the clip's last S seconds into its first S (picture and sound) so every seam is smooth; "
                         "one repeat is then S shorter than the clip, and --times 1 writes one seamless loop")
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
    # the concat list is the only -i, so run() never sees the source next to -o (#416 review)
    refuse_output_is_input(output, args.input)

    v = meta["video"]
    rate = _nominal_rate(v)
    fps = _fraction(rate) or 30.0
    unit = src_dur  # the length one repeat adds
    fade_frames = 0
    if args.crossfade is not None:
        if args.boomerang:
            die("--crossfade and --boomerang cannot be combined: a boomerang's turnarounds already meet matching frames")
        frames = _conformed_frames(v, fps, src_dur)
        require_filter("xfade", "--crossfade")
        fade = time_arg(args.crossfade, "--crossfade", v.get("fps"))
        if not math.isfinite(fade):
            die(f"--crossfade must be a finite number of seconds, got {args.crossfade!r}")
        fade_frames = round(fade * fps)
        if fade_frames < 1:
            die(f"--crossfade {args.crossfade!r} is shorter than one frame ({1 / fps:.3f}s at {fps:g} fps)")
        if 2 * fade_frames > frames:
            die(f"--crossfade ({fade_frames / fps:.3f}s) must be at most half the clip ({frames / fps:.3f}s): "
                f"the fade lays the clip's end over its start, and the two must not overlap")
        unit = (frames - fade_frames) / fps

    if args.times is not None:
        least = 1 if (args.boomerang or fade_frames) else 2
        if args.times < least:
            die(f"--times must be >= 1, got {args.times}" if least == 1 else
                f"--times must be >= 2 (1 is just the original clip; with --crossfade, 1 writes one seamless loop), got {args.times}")
        target = None
        stream_loop = args.times - 1
    else:
        target = time_arg(args.duration, "--duration", v.get("fps"))
        if target <= unit:
            die(f"--duration ({target:g}s) must be longer than one repeat ({unit:.3f}s) -- use cut.py to trim instead")
        stream_loop = math.ceil(target / unit) - 1

    if args.boomerang:
        cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", _boomerang_graph(meta, src_dur, args.times), "-map", "[v]"]
        if meta.get("audio"):
            notes.append("audio dropped: a boomerang plays half its sound backwards -- add a bed with audio.py")
    else:
        # The concat demuxer reads the clip once per repeat and starts each repeat at the previous
        # one's start plus the file's duration (#409): both streams keep their offset from the
        # file's start in every repeat. -stream_loop took the repeat's length from its streams'
        # spans without the last video frame, so a sound that starts 0.3 s late shortened every
        # repeat by a frame and slid against the picture (346 frames for 360, 68 ms off).
        # Both streams start at the first frame, shifted by one constant (av_trim), and the gap a
        # late sound leaves at each repeat's start is filled with silence, at any length.
        workdir = tempfile.TemporaryDirectory(prefix="ffskill_loop_")
        listfile = os.path.join(workdir.name, "loop.txt")
        repeat = os.path.abspath(args.input)
        if fade_frames:
            repeat = os.path.join(workdir.name, "unit.mkv")
            run(_seamless_unit_cmd(meta, args.input, repeat, rate, _conformed_frames(v, fps, src_dur), fade_frames, has_audio))
        with open(listfile, "w", encoding="utf-8") as fh:
            fh.write((concat_list_line(repeat) + "\n") * (stream_loop + 1))
        vtrim, atrim = av_trim(concat_first_frame(listfile), None, fill_gaps=True)
        cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile]
        if has_audio:
            cmd += ["-filter_complex", f"[0:v:0]{vtrim}[v];[0:a:0]{atrim}[a]",
                    "-map", "[v]", "-map", "[a]"]
        else:
            cmd += ["-map", "0:v:0", "-vf", vtrim]
    if target is not None:
        cmd += ["-t", f"{target:.3f}"]
    cmd += video_args(meta, args.crf, args.preset)
    # a crossfade's repeat is already constant at `rate` (its graph's fps=): the loop keeps that rate,
    # not a variable-rate source's average, which re-timed every repeat by a frame or two
    cmd += ["-fps_mode", "passthrough"] if args.boomerang else cfr_args(meta, fps if fade_frames and v.get("variable_frame_rate_suspected") else None)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    try:
        run(cmd)
    finally:
        if not args.boomerang:
            workdir.cleanup()

    extra = {"boomerang": args.boomerang}
    if fade_frames:
        extra["crossfade"] = round(fade_frames / fps, 6)
    requested = target if target is not None else (
        args.times * (2 * _frame_count(v, fps, src_dur) - 2) / fps if args.boomerang else args.times * unit)
    if STATE.dry_run:
        emit(output, expected_duration=round(requested, 3), **extra, **({"notes": notes} if notes else {}))
        return 0
    result = probe(output, role="output")
    rv = result["video"]
    out_dur = result.get("duration") or 0.0
    # the length asked for (repeats x one repeat, or --duration), against the file: within a frame
    # and a half, the slack the last repeat's trim and the encoder's final frame leave
    tolerance = 1.5 / fps
    verification = [{"step": "duration", "requested": round(requested, 3), "measured": round(out_dur, 3),
                     "tolerance": round(tolerance, 3), "ok": abs(out_dur - requested) <= tolerance}]
    if not args.boomerang:
        extra["seam"] = _measure_seam(output, unit, out_dur, fps, has_audio)
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {rv['width']}x{rv['height']}, source {src_dur:.3f}s "
         f"{'boomeranged' if args.boomerang else 'looped'})")
    for note in notes:
        info(note)
    # the streams the run must have written: a crossfade unit whose sound came out empty once left
    # a silent loop that still said verified: true
    emit(output, expected_duration=round(requested, 3), verification=verification,
         expect_streams={"video": 1, "audio": 1 if has_audio else 0}, **extra,
         **({"notes": notes} if notes else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
