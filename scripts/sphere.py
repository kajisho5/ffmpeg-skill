#!/usr/bin/env python3
"""Extract a flat (rectilinear) viewport from a 360/spherical video.

This wraps FFmpeg's v360 filter for the one job it is most often needed for:
turning an equirectangular (or other spherical-projection) source into an
ordinary flat video pointed at a chosen direction -- the same "look this way"
operation a VR headset or a 360 video player's viewport does, baked into a
real file. --yaw/--pitch/--roll aim the camera; --h-fov/--v-fov set how wide
the view is.

This tool does not decide WHERE to point the camera -- there is no subject
detection or tracking here, only the typed rotation/FOV you give it (see this
skill's design principles: it measures and transforms, it does not judge
"what's interesting" in a frame). For a shot that follows a moving subject,
call this once per keyframe viewpoint (or render a short segment per angle)
from outside this tool.

Nor does it detect whether an input actually IS a 360/spherical video --
probe.py's frame dimensions don't distinguish a 2:1 equirectangular capture
from an ordinary flat clip that happens to be that aspect ratio. Point
--input-projection at what the source actually is; wrong information here
produces a distorted or garbled output, not an error (a real limit of what a
frame's own pixels can prove about how they were projected -- ffmpeg's own
v360 filter has the same limit).

Examples:
  python3 sphere.py insta360.mp4 --yaw 0 --pitch 0 -o front.mp4
  python3 sphere.py insta360.mp4 --yaw 90 --h-fov 100 --v-fov 70 -o right_wide.mp4
  python3 sphere.py gopro_max.mp4 --input-projection fisheye --yaw -45 --pitch 10 -o angle.mp4
"""
import argparse
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_output, die, emit, ffmpeg_base, info, probe, run_keeping_subtitles, video_args

# v360's own AVOption names for the input projections real 360 cameras/exports actually
# produce (ffmpeg -h filter=v360 documents 24 total; this is the subset a caller is likely
# to have on hand, not the full list -- narrower, typed choices over an open string).
INPUT_PROJECTIONS = ["equirect", "fisheye", "dfisheye", "c3x2", "c6x1", "barrel", "cylindrical", "hequirect"]
INTERP_METHODS = ["nearest", "linear", "cubic", "lanczos", "spline16", "gaussian", "mitchell"]
STEREO_MODES = {"mono": "2d", "sbs": "sbs", "tb": "tb"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_view.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track")
    ap.add_argument("--input-projection", choices=INPUT_PROJECTIONS, default="equirect",
                     help="the source's own 360 projection (default equirect, the most common capture/export format)")
    ap.add_argument("--stereo", choices=list(STEREO_MODES), default="mono",
                     help="input stereo packing: mono (default), sbs (side-by-side), tb (top-bottom) -- always flattened to a mono output")
    aim = ap.add_argument_group("camera aim")
    aim.add_argument("--yaw", type=float, default=0.0, help="left/right rotation in degrees, -180..180 (default 0, straight ahead)")
    aim.add_argument("--pitch", type=float, default=0.0, help="up/down rotation in degrees, -180..180 (default 0, level)")
    aim.add_argument("--roll", type=float, default=0.0, help="tilt/roll rotation in degrees, -180..180 (default 0)")
    fov = ap.add_argument_group("field of view")
    fov.add_argument("--h-fov", type=float, default=90.0, help="output horizontal field of view in degrees, 1..170 (default 90)")
    fov.add_argument("--v-fov", type=float, default=60.0, help="output vertical field of view in degrees, 1..170 (default 60)")
    out = ap.add_argument_group("output frame")
    out.add_argument("--width", type=int, default=1920, help="output width in px, must be even (default 1920)")
    out.add_argument("--height", type=int, default=1080, help="output height in px, must be even (default 1080)")
    out.add_argument("--interp", choices=INTERP_METHODS, default="lanczos", help="resampling method (default lanczos)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    ap.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if not -180 <= args.yaw <= 180:
        die(f"--yaw must be -180..180, got {args.yaw}")
    if not -180 <= args.pitch <= 180:
        die(f"--pitch must be -180..180, got {args.pitch}")
    if not -180 <= args.roll <= 180:
        die(f"--roll must be -180..180, got {args.roll}")
    if not 1 <= args.h_fov <= 170:
        die(f"--h-fov must be 1..170, got {args.h_fov}")
    if not 1 <= args.v_fov <= 170:
        die(f"--v-fov must be 1..170, got {args.v_fov}")
    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    output = args.output or default_output(args.input, "view")

    v360 = (f"v360=input={args.input_projection}:output=rectilinear:"
            f"in_stereo={STEREO_MODES[args.stereo]}:out_stereo=2d:"
            f"yaw={args.yaw:g}:pitch={args.pitch:g}:roll={args.roll:g}:"
            f"h_fov={args.h_fov:g}:v_fov={args.v_fov:g}:"
            f"w={args.width}:h={args.height}:interp={args.interp}")
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", v360, "-map", "0:v:0"]
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
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, yaw={args.yaw:g} pitch={args.pitch:g})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
