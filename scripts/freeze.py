#!/usr/bin/env python3
"""Freeze on one frame for a number of seconds -- an end-card hold, a comedic beat, a pause.

--at is the timestamp to freeze (default: the last frame). --hold is how
long the freeze lasts. --mode insert (default) inserts the hold into the
clip at --at, pushing everything after it later by --hold seconds; --mode
extend only works with --at at (or past) the end of the clip and simply
makes the last frame last --hold seconds longer, without touching anything
earlier. Audio is silent during the held frame in --mode insert (there is
no source audio for a frozen moment that didn't exist before); --mode
extend has no audio to extend either, since it only makes sense at the
clip's end.

Examples:
  python3 freeze.py interview.mp4 --hold 2                        # hold the last frame 2s longer
  python3 freeze.py sketch.mp4 --at 12.5 --hold 1.5                # 1.5s freeze inserted at 12.5s
  python3 freeze.py outro.mp4 --hold 3 --mode extend                # extend only the very end by 3s
"""
import argparse
import sys

from _common.decision import av_trim, frame_durations, frame_rate, grid_at_or_after, stream_starts
from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args, X264_PRESETS, MissingFpsError, time_arg, fmt_secs, run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_freeze.<ext>)")
    ap.add_argument("--at", help="timestamp to freeze: seconds, mm:ss, hh:mm:ss.ms or SMPTE hh:mm:ss:ff (default: the last frame)")
    ap.add_argument("--hold", type=float, required=True, help="how long the freeze lasts, in seconds")
    ap.add_argument("--mode", choices=["insert", "extend"], default="insert",
                     help="insert (default): hold pushes the rest of the clip later; extend: only valid at/after the clip's end, makes the last frame last longer with nothing pushed")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.hold <= 0:
        die(f"--hold must be > 0, got {args.hold:g}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = meta.get("duration") or 0.0
    fps = meta["video"].get("fps") or 30.0
    if args.at is not None:
        at = time_arg(args.at, "--at", (meta.get("video") or {}).get("fps"))
    else:
        at = dur
    if at < 0 or at > dur:
        die(f"--at {at:g} is outside the clip (0..{dur:.3f})")
    if args.mode == "extend" and at < dur - 0.01:
        die(f"--mode extend needs --at at or after the clip's end ({dur:.3f}), got {at:g}")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "freeze")

    # Both streams are cut at the same frame time and shifted by the same constants (#409): the
    # head runs from the first frame, the tail from the first frame at or after --at. Rebasing each
    # stream to its own start moved a sound that starts 0.3 s late 0.279 s early, and a picture that
    # starts 0.1 s late 0.1 s early (147 frames for 150).
    v0 = stream_starts(meta)[0]
    rate = frame_rate(meta) or fps
    cut_at = grid_at_or_after(at, v0, rate)
    # no frame at or after --at (no --at holds at the clip's end): the insert tail would be empty
    # and the hold lost, so hold the last frame as --mode extend does (#416 review)
    vend = v0 + (meta["video"].get("duration") or dur - v0)
    if args.mode == "extend" or cut_at >= vend - 0.5 / rate:
        # tpad's stop_duration clones the last frame for the given duration; no PTS surgery
        # needed since it only ever appends past the real end.
        vf = f"tpad=stop_mode=clone:stop_duration={args.hold:.3f}"
        cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
        if has_audio:
            cmd += ["-map", "0:a:0?", "-af", f"apad=pad_dur={args.hold:.3f}"]
    elif at == 0 or cut_at <= v0 + 1e-6:
        # A freeze at the very start has no preceding "head" segment to hold on to (the
        # split/trim/concat approach below needs a non-empty head, which trim=end=0 can't give
        # it -- ffmpeg fails filtering an empty stream). Symmetric to --mode extend at the other
        # end: tpad's start_duration clones the *first* frame backwards instead.
        vf = f"tpad=start_mode=clone:start_duration={args.hold:.3f}"
        cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
        if has_audio:
            cmd += ["-map", "0:a:0?", "-af", f"adelay={int(args.hold * 1000)}:all=1"]
    else:
        # freeze N frames at `at` by holding on that one source frame for --hold seconds, then
        # resuming the rest of the clip: split the timeline at `at` and hold the remainder's
        # FIRST frame -- the frame shown at `at` -- for --hold seconds (a segment of its own, below).
        # Through 3.1.3 the head's last frame was held, the frame before `at`: at a cut, the last
        # frame of the previous shot (#411).
        n = max(1, round(args.hold * fps))
        # The video hold length is rounded to a whole number of frames (n / fps), but the audio
        # side used to pad by the raw --hold value -- up to half a frame duration off from what
        # the video actually holds for, a permanent A/V drift from this point on. Pad audio by
        # the same, frame-rounded duration the video actually gets.
        actual_hold = n / fps
        head_v, head_a = av_trim(v0, cut_at, rate)
        tail_v, tail_a = av_trim(cut_at, None, rate)
        # The hold is its own segment: the frame at cut_at, cut on the input's clock and cloned to
        # n frames there (tpad's stop clone), then shifted like the tail. From FFmpeg 7.0 setpts
        # leaves its output's frame rate unknown and its frames' durations 0, so the earlier tpad
        # start clone after av_trim's setpts stamped every clone 0 and the hold was dropped (a 3 s
        # freeze came out 1.97 s on 7.1). Cloning before setpts and concatenating the hold before
        # the tail reads the same on every version; the tail's first frame then shows n + 1 times,
        # as tpad's start clone showed it.
        # The held frame is the first frame at or after the cut, whatever its time: on a variable
        # frame rate a nominal one-frame window around cut_at can hold no frame (frames at 0.033
        # and 0.100, --at 0.06), and the hold was lost (#416 review). A second trim keeps that one
        # frame; on a constant rate it is the frame at cut_at, as before.
        half = 0.5 / rate
        hold_v = (f"trim=start={cut_at - half:.6f},trim=end_frame=1,"
                  f"tpad=stop_mode=clone:stop={n - 1},setpts=PTS-STARTPTS")
        vf = (f"[0:v]split=3[a][b][c];[a]{head_v}[head];"
              f"[b]{hold_v}[hold];[c]{tail_v}[tail];"
              f"[head][hold][tail]concat=n=3:v=1:a=0,{frame_durations(meta, rate)}[outv]")
        cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", vf, "-map", "[outv]"]
        if has_audio:
            af = (f"[0:a]asplit[aa][ab];[aa]{head_a}[ahead];"
                  f"[ab]{tail_a}[atail];"
                  f"[ahead]apad=pad_dur={actual_hold:.6f}[afrozen];"
                  f"[afrozen][atail]concat=n=2:v=0:a=1[outa]")
            cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", f"{vf};{af}", "-map", "[outv]", "-map", "[outa]"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    if args.mode == "insert":
        # the picture gains `hold` seconds at `at`; a stream-copied subtitle track would keep its
        # old timestamps and every cue after the freeze would fire early (same reasoning as
        # fit.py --method speed). Drop it rather than ship captions that lie.
        run(cmd + [output])
        dropped_streams = bool(meta.get("subtitle_streams") or meta.get("data_streams"))
    else:
        dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, froze {args.hold:g}s at {at:g}s, mode={args.mode})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
