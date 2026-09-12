#!/usr/bin/env python3
"""Loop a clip a number of times, or to a target duration.

For a background loop, an ambient bed, or filling a fixed slot length with
a short clip. --times repeats the whole clip that many times back to back;
--duration instead loops (and, on the last repeat, trims) to hit an exact
target length. Audio loops along with the video when present. This tool
does not smooth the loop point (no crossfade at the seam) -- a clip that
doesn't already loop cleanly will show a visible cut/pop at each repeat;
that's a judgement call about the source material, not something a --times
or --duration flag can fix.

Examples:
  python3 loop.py bg_loop.mp4 --times 3
  python3 loop.py texture.mp4 --duration 30
"""
import argparse
import math
import sys

from _common import add_common, aac_args, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, video_args, X264_PRESETS, time_arg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_loop.<ext>)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--times", type=int, help="repeat the whole clip this many times (2 = original + 1 repeat)")
    group.add_argument("--duration", help="loop (and trim the last repeat) to hit exactly this target duration (seconds or mm:ss)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
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
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "loop")

    if args.times is not None:
        if args.times < 2:
            die(f"--times must be >= 2 (1 is just the original clip), got {args.times}")
        target = None
        stream_loop = args.times - 1
    else:
        target = time_arg(args.duration, "--duration", meta["video"].get("fps") if meta.get("video") else None)
        if target <= src_dur:
            die(f"--duration ({target:g}s) must be longer than the source ({src_dur:.3f}s) -- use cut.py to trim instead")
        stream_loop = math.ceil(target / src_dur) - 1

    # -stream_loop repeats the whole input read (video and audio together) at the demuxer level
    # -- exact and lossless-in-intent for a re-encode target, unlike a filter-graph loop that
    # would need separate video/audio filters kept in lockstep by hand.
    cmd = ffmpeg_base() + ["-stream_loop", str(stream_loop), "-i", args.input]
    if target is not None:
        cmd += ["-t", f"{target:.3f}"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, source {src_dur:.3f}s looped)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
