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

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, drawn_chain, emit, EVEN_SCALE, ffmpeg_base, info, probe, run_keeping_subtitles, validate_color, video_args, X264_PRESETS, time_arg, fmt_secs, run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_pad.<ext>)")
    ap.add_argument("--start", default="0", help="padding to add before the clip: seconds or mm:ss (default 0)")
    ap.add_argument("--end", default="0", help="padding to add after the clip: seconds or mm:ss (default 0)")
    ap.add_argument("--color", default="black", help="padding colour (default black)")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    args.start = time_arg(args.start, "--start")
    args.end = time_arg(args.end, "--end")
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

    tpad = f"tpad=start_duration={args.start:.3f}:stop_duration={args.end:.3f}:color="
    # a --color with chroma lands in the BT.709 the output is tagged with (tpad's own YUV is BT.601
    # before FFmpeg 7.1, and for an untagged picture after it); black is the same under every matrix
    vf = drawn_chain(tpad + args.color, meta, [args.color], tpad + "black")
    cmd = ffmpeg_base() + ["-i", args.input]
    if has_audio:
        # One -filter_complex, not a -vf and an -af: the ffmpeg scheduler of Ubuntu 26.04's 8.0.1 and
        # conda-forge's 7.1.1 (not Debian's 7.1.5 or 8.1) deadlocks with no CPU use when one demuxer feeds two simple
        # graphs and the audio one both delays its input and pads the tail. One graph reading both
        # streams runs on 5.1-8.1 alike. run() only adds an even scale to a -vf, so add it here.
        v = meta["video"]
        even = EVEN_SCALE + "," if (v.get("width") or 0) % 2 or (v.get("height") or 0) % 2 else ""
        af = f"adelay={int(args.start * 1000)}:all=1,apad=pad_dur={args.end:.3f}"
        cmd += ["-filter_complex", f"[0:v:0]{even}{vf}[v];[0:a:0]{af}[a]", "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", vf, "-map", "0:v:0"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    if args.start > 0:
        # a stream-copied subtitle track keeps its timestamps and would fire --start seconds early
        # (sweep F3); drop it and say so, as freeze --mode insert and fit --method speed do
        run(cmd + [output])
        dropped_streams = bool(meta.get("subtitle_streams") or meta.get("data_streams"))
    else:
        dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, +{args.start:g}s start / +{args.end:g}s end)")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
