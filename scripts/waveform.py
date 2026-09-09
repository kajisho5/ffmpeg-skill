#!/usr/bin/env python3
"""Render an audio track as a waveform or spectrum visualization video.

Wraps FFmpeg's showwaves (--style waveform, the default) or showspectrum
(--style spectrum) source filter over the input's audio -- for a podcast
episode, a music release, or any clip that has no picture worth showing.
The rendered clip always carries the same audio it visualizes; the video is
generated fresh, there is no source picture involved.

--style waveform draws the amplitude over time; --style spectrum draws a
frequency-over-time heatmap instead, which reads more information out of
dense mixes at the cost of being less immediately readable to a general
audience. Both accept --width/--height and --color; waveform additionally
takes --waveform-mode (how each sample is drawn) and --split-channels
(stereo drawn as two separate lanes instead of summed to one).

Examples:
  python3 waveform.py podcast.wav -o waveform.mp4
  python3 waveform.py track.wav --style spectrum --width 1920 --height 1080 -o spectrum.mp4
  python3 waveform.py interview.mp4 --split-channels --color cyan|magenta
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, default_output, die, emit, ffmpeg_base, info, probe, run, validate_color

WAVEFORM_MODES = ["point", "line", "p2p", "cline"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_waveform.<ext>)")
    ap.add_argument("--style", choices=["waveform", "spectrum"], default="waveform", help="waveform (default) or spectrum visualization")
    ap.add_argument("--width", type=int, default=1920, help="output width in px, must be even (default 1920)")
    ap.add_argument("--height", type=int, default=1080, help="output height in px, must be even (default 1080)")
    ap.add_argument("--fps", type=float, default=25.0, help="output frame rate (default 25)")
    ap.add_argument("--color", default="lime", help="channel colour(s), pipe-separated per channel, e.g. 'lime' or 'cyan|magenta' (default lime)")
    ap.add_argument("--background", default="black", help="background colour (default black)")
    ap.add_argument("--waveform-mode", choices=WAVEFORM_MODES, default="line", help="--style waveform only: how each sample is drawn (default line)")
    ap.add_argument("--split-channels", action="store_true", help="draw each channel in its own lane instead of summing to one")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to render, 0-based in file order (default 0)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")
    for token in args.color.split("|"):
        validate_color(token, "--color")
    validate_color(args.background, "--background")
    if args.fps <= 0:
        die(f"--fps must be > 0, got {args.fps:g}")

    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    output = args.output or default_output(args.input, "waveform")

    if args.style == "waveform":
        vf = (f"showwaves=s={args.width}x{args.height}:mode={args.waveform_mode}:rate={args.fps:g}:"
              f"split_channels={1 if args.split_channels else 0}:colors={args.color}")
    else:
        vf = f"showspectrum=s={args.width}x{args.height}:mode={'separate' if args.split_channels else 'combined'}:fps={args.fps:g}"
    # showwaves/showspectrum paint the visualization on a transparent-black canvas; composite
    # it over an explicit solid background instead of assuming that canvas already matches
    # --background.
    vf = f"color=c={args.background}:s={args.width}x{args.height}:r={args.fps:g}[bg];[0:a:{args.audio_stream}]{vf}[vis];[bg][vis]overlay=format=auto"

    cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", vf, "-map", f"0:a:{args.audio_stream}"]
    cmd += ["-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    cmd += aac_args()
    cmd += ["-shortest", output]
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {args.style})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
