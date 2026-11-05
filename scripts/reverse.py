#!/usr/bin/env python3
"""Reverse a video (and its audio, unless dropped).

Uses ffmpeg's `reverse` (video) and `areverse` (audio) filters, which decode
and buffer the whole clip in memory -- long inputs cost real time and RAM,
which is why there is no length limit baked in here: it is the caller's job
to keep this to clips it makes sense to reverse (a few seconds to a couple of
minutes), not a workaround this tool applies for you.

Examples:
  python3 reverse.py input.mp4
  python3 reverse.py input.mp4 --no-audio -o backwards.mp4
"""
import argparse
import math
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run, video_args, X264_PRESETS, fmt_secs
from _common.emit import warn
from _common.decision import av_clip_length, av_trim, frame_durations, frame_rate, stream_starts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_reverse.<ext>)")
    ap.add_argument("--no-audio", action="store_true", help="drop audio instead of reversing it")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio")) and not args.no_audio

    output = args.output or default_output(args.input, "reverse")
    if (meta.get("duration") or 0) > 60:
        warn(f"reverse buffers every decoded frame in memory; {meta['duration']:.0f}s of "
             f"{meta['video']['width']}x{meta['video']['height']} can exhaust RAM -- cut the part to reverse first (cut.py)",
             "memory_heavy", duration=meta["duration"])
    cmd = ffmpeg_base() + ["-i", args.input]
    if has_audio:
        # Both streams are reversed about one end (#409); each reversed about its own end put a sound
        # 0.6 s longer than its picture 0.396 s off. As in a join, both start at the first frame (the
        # sound shifted by the same constant, padded when it starts late) and end together, on the
        # first frame time at or after the clip's one length (av_clip_length: the picture's, or the
        # sound's when it runs more than a frame past it). The last frame is held and the sound
        # padded with silence to that end; the end is a frame time because a copied cut's stated
        # video length can run past its last frame (7.517 s for frames ending at 7.5). One graph for
        # both streams, as pad.py's padding needs. areverse keeps its input's timestamps in order,
        # so the reversed sound is retimed by its samples. The hold (tpad) runs before av_trim's
        # setpts: from FFmpeg 7.0 setpts leaves its output's frame rate unknown and its frames'
        # durations 0, so a tpad after it clones nothing (the picture stayed 0.6 s short on 7.1);
        # the closing fps gives the frames their durations back (frame_durations).
        rate = frame_rate(meta) or meta["video"].get("fps") or 30.0
        length = av_clip_length(meta, rate)
        vlen = meta["video"].get("duration") or length
        end = math.ceil(length * rate - 1e-6) / rate
        vtrim, atrim = av_trim(stream_starts(meta)[0], None)
        cmd += ["-filter_complex",
                f"[0:v:0]tpad=stop_mode=clone:stop_duration={max(0.0, end - vlen) + 2 / rate:.6f},{vtrim},"
                f"trim=end={end - 0.5 / rate:.6f},reverse,{frame_durations(meta, rate)}[v];"
                f"[0:a:0]{atrim},apad=whole_dur={end:.6f},atrim=end={end:.6f},areverse,asetpts=N/SR/TB[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", "reverse"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {result['video']['width']}x{result['video']['height']})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
