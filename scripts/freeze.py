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

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_freeze.<ext>)")
    ap.add_argument("--at", type=float, help="timestamp to freeze, in seconds (default: the last frame)")
    ap.add_argument("--hold", type=float, required=True, help="how long the freeze lasts, in seconds")
    ap.add_argument("--mode", choices=["insert", "extend"], default="insert",
                     help="insert (default): hold pushes the rest of the clip later; extend: only valid at/after the clip's end, makes the last frame last longer with nothing pushed")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
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
    at = args.at if args.at is not None else dur
    if at < 0 or at > dur:
        die(f"--at {at:g} is outside the clip (0..{dur:.3f})")
    if args.mode == "extend" and at < dur - 0.01:
        die(f"--mode extend needs --at at or after the clip's end ({dur:.3f}), got {at:g}")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "freeze")

    if args.mode == "extend":
        # tpad's stop_duration clones the last frame for the given duration; no PTS surgery
        # needed since it only ever appends past the real end.
        vf = f"tpad=stop_mode=clone:stop_duration={args.hold:.3f}"
        cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
        if has_audio:
            cmd += ["-map", "0:a:0?", "-af", f"apad=pad_dur={args.hold:.3f}"]
    elif at == 0:
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
        # resuming the rest of the clip: split the timeline at `at`, freeze-frame the first
        # part's last frame for --hold seconds via tpad, concat with the remainder.
        n = max(1, round(args.hold * fps))
        # The video hold length is rounded to a whole number of frames (n / fps), but the audio
        # side used to pad by the raw --hold value -- up to half a frame duration off from what
        # the video actually holds for, a permanent A/V drift from this point on. Pad audio by
        # the same, frame-rounded duration the video actually gets.
        actual_hold = n / fps
        vf = (f"[0:v]split[a][b];[a]trim=end={at:.3f},setpts=PTS-STARTPTS[head];"
              f"[b]trim=start={at:.3f},setpts=PTS-STARTPTS[tail];"
              f"[head]tpad=stop_mode=clone:stop={n}[frozen];"
              f"[frozen][tail]concat=n=2:v=1:a=0[outv]")
        cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", vf, "-map", "[outv]"]
        if has_audio:
            af = (f"[0:a]asplit[aa][ab];[aa]atrim=end={at:.3f},asetpts=PTS-STARTPTS[ahead];"
                  f"[ab]atrim=start={at:.3f},asetpts=PTS-STARTPTS[atail];"
                  f"[ahead]apad=pad_dur={actual_hold:.6f}[afrozen];"
                  f"[afrozen][atail]concat=n=2:v=0:a=1[outa]")
            cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", f"{vf};{af}", "-map", "[outv]", "-map", "[outa]"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, froze {args.hold:g}s at {at:g}s, mode={args.mode})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
