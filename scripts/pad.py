#!/usr/bin/env python3
"""Add black video / silent audio at the start and/or end of a clip.

Distinct from fit.py --fit pad, which pads the FRAME (letterbox/pillarbox
bars around each existing frame to reach a target aspect ratio) -- this
tool pads the TIMELINE (extra seconds of solid colour and silence before
and/or after the clip's existing content). Common uses: a beat of black
before a title card starts, room for a fade-in, aligning a clip to a fixed
slot length.

Examples:
  python3 pad.py clip.mp4 --start 1.5                 # 1.5s of black+silence before the clip
  python3 pad.py clip.mp4 --end 2                      # 2s of black+silence after the clip
  python3 pad.py clip.mp4 --start 1 --end 1 --color 0x101010
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, validate_color, video_args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_pad.<ext>)")
    ap.add_argument("--start", type=float, default=0.0, help="seconds of padding to add before the clip (default 0)")
    ap.add_argument("--end", type=float, default=0.0, help="seconds of padding to add after the clip (default 0)")
    ap.add_argument("--color", default="black", help="padding colour (default black)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.start < 0 or args.end < 0:
        die(f"--start/--end must be >= 0, got start={args.start:g} end={args.end:g}")
    if args.start == 0 and args.end == 0:
        die("--start and/or --end must be > 0 (nothing to pad)")
    validate_color(args.color, "--color")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "pad")

    vf = f"tpad=start_duration={args.start:.3f}:stop_duration={args.end:.3f}:color={args.color}"
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
    if has_audio:
        af = f"adelay={int(args.start * 1000)}:all=1,apad=pad_dur={args.end:.3f}"
        cmd += ["-map", "0:a:0?", "-af", af]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, +{args.start:g}s start / +{args.end:g}s end)")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
