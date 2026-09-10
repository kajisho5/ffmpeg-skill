#!/usr/bin/env python3
"""Fit a video to a target duration and/or aspect ratio.

Duration: --duration N with --method speed (retime video+audio, pitch-preserving
via atempo chaining) or --method trim (keep the first N seconds, or a centred
window with --from-center). Aspect: --aspect 16:9|9:16|1:1|4:5|W:H with
--fit pad (letterbox/pillarbox with --pad-color, default black) or --fit crop.
--width and/or --height set the output size: give one and the other follows
the aspect (source aspect if --aspect is not also given); give both for an
exact frame. --rotate 90|180|270 (clockwise) and --flip h|v apply a new
rotation/mirror to the picture -- distinct from the rotation metadata a
source already carries (read automatically to compute the displayed size,
never altered by these flags unless asked). Both can be combined; rotate is
applied before flip.

Crop keeps the centre of the frame by default, which is a guess: going from
16:9 to 9:16 throws away most of the width, and whatever isn't in the middle
third (a person at the edge, a product held to one side) is cut off. Say what
to keep with --crop-x / --crop-y (0=left/top, 0.5=centre, 1=right/bottom, or
a decimal in between) rather than accepting the default silently when the
subject isn't centred; --fit pad never loses anything if you don't know yet.

Examples:
  python3 fit.py input.mp4 --duration 60                    # speed up/down to exactly 60s
  python3 fit.py input.mp4 --duration 30 --method trim
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --width 1080
  python3 fit.py input.mp4 --aspect 1:1 --fit crop --duration 15
  python3 fit.py input.mp4 --aspect 9:16 --fit crop --crop-x 1   # keep the right edge (e.g. product held stage-right)
  python3 fit.py input.mp4 --height 1080                         # width follows the source aspect
  python3 fit.py input.mp4 --width 1920 --height 1080            # exact frame, no aspect needed
  python3 fit.py input.mp4 --rotate 90                           # rotate 90 degrees clockwise
  python3 fit.py input.mp4 --flip h                              # mirror horizontally
"""
import argparse
import math
import sys
from fractions import Fraction
from typing import List

from _common import video_args, STATE, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, ffmpeg_base, info, parse_time, probe, run, run_keeping_subtitles, validate_color, x264_args

ASPECT_PRESETS = {"16:9": Fraction(16, 9), "9:16": Fraction(9, 16), "1:1": Fraction(1, 1), "4:5": Fraction(4, 5), "4:3": Fraction(4, 3), "21:9": Fraction(21, 9)}


def parse_aspect(value: str) -> Fraction:
    if value in ASPECT_PRESETS:
        return ASPECT_PRESETS[value]
    try:
        w, h = value.split(":")
        return Fraction(int(w), int(h))
    except (ValueError, ZeroDivisionError):
        die(f"bad aspect '{value}', use W:H like 16:9")
    return Fraction(1)  # unreachable


def atempo_chain(factor: float) -> str:
    """atempo accepts 0.5..100 per instance; chain for extreme factors."""
    parts: List[str] = []
    remaining = factor
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 100.0:
        parts.append("atempo=100.0")
        remaining /= 100.0
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_fit.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    d = ap.add_argument_group("duration")
    d.add_argument("--duration", help="target duration (seconds or mm:ss)")
    d.add_argument("--method", choices=["speed", "trim"], default="speed", help="how to reach the duration (default speed)")
    d.add_argument("--from-center", action="store_true", help="with --method trim, keep the middle instead of the start")
    d.add_argument("--max-speed", type=float, default=4.0, help="refuse speed factors above this (default 4x)")
    d.add_argument("--smooth", choices=["none", "blend", "interpolate"], default="none",
                   help="slow-motion quality: blend (frame blending) or interpolate (motion-compensated, slow but fluid). default none = duplicate frames")
    a = ap.add_argument_group("aspect")
    a.add_argument("--aspect", help="target aspect ratio, e.g. 16:9, 9:16, 1:1, 4:5")
    a.add_argument("--fit", choices=["pad", "crop"], default="pad", help="pad (letterbox) or crop to reach the aspect (default pad)")
    a.add_argument("--width", type=int, help="output width in px (default: keep source width or the width implied by the aspect); with --height also given, both are used directly")
    a.add_argument("--height", type=int, help="output height in px (default: keep source height or the height implied by the aspect); with --width also given, both are used directly")
    a.add_argument("--pad-color", default="black", help="pad colour, e.g. black, white, 0x101010 (default black)")
    a.add_argument("--crop-x", type=float, default=0.5, help="with --fit crop, horizontal anchor 0=left, 0.5=centre (default), 1=right")
    a.add_argument("--crop-y", type=float, default=0.5, help="with --fit crop, vertical anchor 0=top, 0.5=centre (default), 1=bottom")
    r = ap.add_argument_group("rotate / flip")
    r.add_argument("--rotate", type=int, choices=[90, 180, 270], help="rotate the picture clockwise by this many degrees")
    r.add_argument("--flip", choices=["h", "v"], help="mirror the picture horizontally (h) or vertically (v)")
    e = ap.add_argument_group("encoding")
    e.add_argument("--crf", type=int, default=18)
    e.add_argument("--preset", default="medium")
    e.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be positive, got {args.fps:g}")
    if not args.duration and not args.aspect and not args.width and not args.height and not args.fps and not args.rotate and not args.flip:
        die("nothing to do: give --duration, --aspect, --width/--height, --rotate/--flip and/or --fps")
    if not 0.0 <= args.crop_x <= 1.0:
        die(f"--crop-x must be 0..1, got {args.crop_x}")
    if not 0.0 <= args.crop_y <= 1.0:
        die(f"--crop-y must be 0..1, got {args.crop_y}")
    validate_color(args.pad_color, "--pad-color")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    src_dur = meta["duration"] or 0.0
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        sw, sh = sh, sw
    if args.rotate in (90, 270):
        sw, sh = sh, sw
    has_audio = bool(meta.get("audio"))

    vf: List[str] = []
    af: List[str] = []
    pre_input: List[str] = []
    post: List[str] = []
    factor = 1.0

    # ---- rotate / flip
    if args.rotate == 90:
        vf.append("transpose=1")
    elif args.rotate == 270:
        vf.append("transpose=2")
    elif args.rotate == 180:
        vf.append("transpose=2,transpose=2")
    if args.flip == "h":
        vf.append("hflip")
    elif args.flip == "v":
        vf.append("vflip")

    # ---- duration
    if args.duration:
        target = parse_time(args.duration)
        if target <= 0:
            die("target duration must be > 0")
        if args.method == "speed":
            if src_dur <= 0 and STATE["dry_run"]:
                src_dur = target  # planning against an intermediate that does not exist yet
            factor = src_dur / target  # >1 = speed up
            if factor > args.max_speed or factor < 1 / args.max_speed:
                die(f"required speed factor {factor:.2f}x exceeds --max-speed {args.max_speed}x; use --method trim or raise the limit")
            if abs(factor - 1.0) > 1e-4:
                vf.append(f"setpts={1/factor:.8f}*PTS")
                src_fps = meta["video"].get("fps") or 30.0
                if factor < 1.0 and args.smooth == "interpolate":
                    vf.append(f"minterpolate=fps={src_fps:g}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
                elif factor < 1.0 and args.smooth == "blend":
                    vf.append(f"fps={src_fps:g}")
                    vf.append("tblend=all_mode=average")
                if has_audio:
                    af.append(atempo_chain(factor))
            post += ["-t", f"{target:.3f}"]
            STATE["duration_hint"] = target
        else:
            if target < src_dur:
                start = (src_dur - target) / 2 if args.from_center else 0.0
                pre_input += ["-ss", f"{start:.3f}"]
                post += ["-t", f"{target:.3f}"]
            else:
                info(f"source ({src_dur:.2f}s) is already shorter than {target:.2f}s; trim does nothing")

    # ---- aspect / size
    if args.aspect or args.width or args.height:
        src_ratio = Fraction(sw, sh) if sh else None
        ratio = parse_aspect(args.aspect) if args.aspect else src_ratio
        if args.width and args.height:
            out_w, out_h = even(args.width), even(args.height)
        elif args.width:
            out_w = even(args.width)
            out_h = even(out_w / ratio) if ratio else args.width
        elif args.height:
            out_h = even(args.height)
            out_w = even(out_h * ratio) if ratio else args.height
        elif ratio and src_ratio:
            # No explicit --width/--height: size the canvas to the new aspect without exceeding
            # the source's own resolution in either dimension. A narrower/taller target than the
            # source (e.g. 9:16 from a 16:9 source) must be bounded by the source's HEIGHT, not
            # its width -- bounding by width there multiplies the height by src_ratio/ratio (a
            # 1920x1080 source asked for 9:16 used to come out 1920x3414, a ~3.16x upscale in
            # both fit=pad and fit=crop, entirely unrequested).
            if ratio <= src_ratio:
                out_h = even(sh)
                out_w = even(out_h * ratio)
            else:
                out_w = even(sw)
                out_h = even(out_w / ratio)
        else:
            out_w, out_h = even(sw), even(sh)
        if args.fit == "crop":
            vf.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase")
            vf.append(f"crop={out_w}:{out_h}:(in_w-out_w)*{args.crop_x:g}:(in_h-out_h)*{args.crop_y:g}")
        else:
            vf.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease")
            vf.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}")
        vf.append("setsar=1")

    if args.fps:
        vf.append(f"fps={args.fps:g}")
    elif meta["video"].get("variable_frame_rate_suspected"):
        info("source looks variable-frame-rate; conforming to constant fps automatically")

    output = args.output or default_output(args.input, "fit")
    cmd = ffmpeg_base() + pre_input + ["-i", args.input]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", f"0:a:{args.audio_stream}"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps) if not args.fps else []
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd += post
    if abs(factor - 1.0) > 1e-4:
        # A subtitle/data stream stream-copied by run_keeping_subtitles keeps the source's
        # original timestamps; --method speed retimes video (setpts) and audio (atempo) but has
        # no equivalent way to retime a copied subtitle track, so it would desync from the
        # now-faster/slower picture. Drop them here rather than ship a captions track that lies
        # about when a line is spoken.
        run(cmd + [output])
        dropped_streams = bool(meta.get("subtitle_streams") or meta.get("data_streams"))
    else:
        dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    msg = f"wrote {output} ({result['duration']:.3f}s, {result['video']['width']}x{result['video']['height']})"
    if abs(factor - 1.0) > 1e-4:
        msg += f", speed {factor:.3f}x"
    info(msg)
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
