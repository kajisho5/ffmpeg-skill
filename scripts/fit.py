#!/usr/bin/env python3
"""Fit a video to a target duration and/or aspect ratio.

Duration: --duration N with --method speed (retime video+audio, pitch-preserving
via atempo chaining) or --method trim (keep the first N seconds, or a centred
window with --from-center). Aspect: --aspect 16:9|9:16|1:1|4:5|W:H with
--fit pad (letterbox/pillarbox with --pad-color, default black) or --fit crop
(centre crop). --width sets the output width; height follows the aspect.

Examples:
  python3 fit.py input.mp4 --duration 60                    # speed up/down to exactly 60s
  python3 fit.py input.mp4 --duration 30 --method trim
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --width 1080
  python3 fit.py input.mp4 --aspect 1:1 --fit crop --duration 15
"""
import argparse
import math
import sys
from fractions import Fraction
from typing import List

from _common import video_args, STATE, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, ffmpeg_base, info, parse_time, probe, run, x264_args

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
    a.add_argument("--width", type=int, help="output width in px (default: keep source width or the width implied by the aspect)")
    a.add_argument("--pad-color", default="black", help="pad colour, e.g. black, white, 0x101010 (default black)")
    e = ap.add_argument_group("encoding")
    e.add_argument("--crf", type=int, default=18)
    e.add_argument("--preset", default="medium")
    e.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if not args.duration and not args.aspect and not args.width and not args.fps:
        die("nothing to do: give --duration, --aspect, --width and/or --fps")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    src_dur = meta["duration"] or 0.0
    sw, sh = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        sw, sh = sh, sw
    has_audio = bool(meta.get("audio"))

    vf: List[str] = []
    af: List[str] = []
    pre_input: List[str] = []
    post: List[str] = []
    factor = 1.0

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
    if args.aspect or args.width:
        src_ratio = Fraction(sw, sh)
        ratio = parse_aspect(args.aspect) if args.aspect else src_ratio
        if args.width:
            out_w = even(args.width)
        else:
            out_w = even(sw if ratio <= src_ratio else sh * ratio)
        out_h = even(out_w / ratio)
        if args.fit == "crop":
            vf.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase")
            vf.append(f"crop={out_w}:{out_h}")
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
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps) if not args.fps else []
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd += post + [output]
    run(cmd)

    result = probe(output)
    msg = f"wrote {output} ({result['duration']:.3f}s, {result['video']['width']}x{result['video']['height']})"
    if abs(factor - 1.0) > 1e-4:
        msg += f", speed {factor:.3f}x"
    info(msg)
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
