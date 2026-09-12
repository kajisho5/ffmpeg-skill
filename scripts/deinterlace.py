#!/usr/bin/env python3
"""Deinterlace interlaced source footage (old broadcast masters, DV, some camcorders).

Wraps FFmpeg's yadif filter. --mode frame (default) keeps the original frame
rate, blending each pair of fields back into one frame; --mode field instead
emits one frame per field, doubling the frame rate (smoother motion, the
usual choice for footage that will be watched at full quality). --parity
tells yadif which field came first when the container doesn't say so
correctly; --only-interlaced skips frames the source itself doesn't mark as
interlaced, leaving already-progressive frames untouched.

This tool does not detect whether the source needs deinterlacing at all --
that's a probe.py/look.py judgement (visible combing on motion in a contact
sheet). Running yadif on already-progressive footage is a harmless no-op in
practice but still re-encodes the whole file, so don't run this by default.

Examples:
  python3 deinterlace.py old_tape.mov
  python3 deinterlace.py broadcast.mxf --mode field --parity tff
  python3 deinterlace.py mixed.mov --only-interlaced
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args, X264_PRESETS, fmt_secs

MODES = {"frame": 0, "field": 1}
PARITIES = {"auto": -1, "tff": 0, "bff": 1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_deint.<ext>)")
    ap.add_argument("--mode", choices=list(MODES), default="frame",
                     help="frame (default): one output frame per input frame; field: one output frame per field, doubling fps")
    ap.add_argument("--parity", choices=list(PARITIES), default="auto",
                     help="which field came first (default auto-detect from the stream)")
    ap.add_argument("--only-interlaced", action="store_true",
                     help="only deinterlace frames the source marks as interlaced; leave the rest untouched")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (default 0)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    output = args.output or default_output(args.input, "deint")

    vf = f"yadif=mode={MODES[args.mode]}:parity={PARITIES[args.parity]}:deint={1 if args.only_interlaced else 0}"
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", f"0:a:{args.audio_stream}?"]
    cmd += video_args(meta, args.crf, args.preset)
    if args.mode == "field":
        v = meta["video"]
        src_fps = v.get("fps") or 30.0
        cmd += ["-fps_mode", "cfr", "-r", f"{src_fps * 2:g}"]
    else:
        cmd += cfr_args(meta)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['fps']:g}fps, mode={args.mode})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
