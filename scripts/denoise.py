#!/usr/bin/env python3
"""Reduce video noise/grain with FFmpeg's hqdn3d filter.

For audio noise reduction use audio.py --denoise instead -- this tool only
touches the picture. --strength picks a tested preset (low/medium/high,
scaling hqdn3d's four spatial/temporal luma/chroma parameters together);
--luma-spatial/--chroma-spatial/--luma-temporal/--chroma-temporal override
any of the four individually when a preset isn't precise enough. Heavier
denoising trades away fine detail (skin texture, foliage, film grain) for a
cleaner-looking but softer image -- there is no setting that removes noise
"for free"; --strength high is a real quality trade-off, not just "better".

Examples:
  python3 denoise.py noisy_lowlight.mp4
  python3 denoise.py grainy_scan.mov --strength high
  python3 denoise.py source.mp4 --luma-spatial 6 --chroma-spatial 4 --luma-temporal 8 --chroma-temporal 6
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args

# hqdn3d's own AVOptions default to 0 (off); these tested presets are the light/medium/heavy
# starting points its own documentation and common usage recommend (spatial then temporal,
# luma then chroma -- chroma tends to tolerate more smoothing before looking soft).
STRENGTH_PRESETS = {
    "low": (2.0, 1.5, 3.0, 2.25),
    "medium": (4.0, 3.0, 6.0, 4.5),
    "high": (8.0, 6.0, 10.0, 7.5),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_denoise.<ext>)")
    ap.add_argument("--strength", choices=list(STRENGTH_PRESETS), default="medium",
                     help="preset denoising amount (default medium); overridden per-parameter by the flags below")
    ap.add_argument("--luma-spatial", type=float, help="spatial luma denoising strength (default from --strength)")
    ap.add_argument("--chroma-spatial", type=float, help="spatial chroma denoising strength (default from --strength)")
    ap.add_argument("--luma-temporal", type=float, help="temporal luma denoising strength (default from --strength)")
    ap.add_argument("--chroma-temporal", type=float, help="temporal chroma denoising strength (default from --strength)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (default 0)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    ls, cs, lt, ct = STRENGTH_PRESETS[args.strength]
    ls = args.luma_spatial if args.luma_spatial is not None else ls
    cs = args.chroma_spatial if args.chroma_spatial is not None else cs
    lt = args.luma_temporal if args.luma_temporal is not None else lt
    ct = args.chroma_temporal if args.chroma_temporal is not None else ct
    for name, val in (("--luma-spatial", ls), ("--chroma-spatial", cs), ("--luma-temporal", lt), ("--chroma-temporal", ct)):
        if val < 0:
            die(f"{name} must be >= 0, got {val:g}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    output = args.output or default_output(args.input, "denoise")

    vf = f"hqdn3d={ls:g}:{cs:g}:{lt:g}:{ct:g}"
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", f"0:a:{args.audio_stream}?"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps)
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, strength={args.strength})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
