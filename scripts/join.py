#!/usr/bin/env python3
"""Join clips with transitions, normalising resolution, frame rate and audio
layout so mismatched sources (phone + camera + screen recording) cut together.

Transitions (xfade): fade, dissolve, wipeleft, wiperight, wipeup, wipedown,
slideleft, slideright, circleopen, fadeblack, fadewhite, smoothleft, none.

Examples:
  python3 join.py a.mp4 b.mp4 c.mp4 -o final.mp4                      # 0.5 s crossfade, size/fps from the first clip
  python3 join.py *.mp4 --transition fadeblack --duration 1 -o reel.mp4
  python3 join.py a.mov b.mp4 --transition none --width 1920 --height 1080 --fps 30
"""
import argparse
import sys
from typing import List

from _common import STATE, video_args, aac_args, add_common, apply_common, default_output, die, emit, ffmpeg_base, info, probe, run, x264_args

TRANSITIONS = ["fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
               "circleopen", "circleclose", "fadeblack", "fadewhite", "smoothleft", "smoothright", "radial", "none"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="two or more clips in order")
    ap.add_argument("-o", "--output", help="output file (default: <first>_joined.mp4)")
    ap.add_argument("--transition", choices=TRANSITIONS, default="fade", help="transition between clips (default fade)")
    ap.add_argument("--duration", type=float, default=0.5, help="transition length in seconds (default 0.5)")
    ap.add_argument("--width", type=int, help="output width (default: first clip)")
    ap.add_argument("--height", type=int, help="output height (default: first clip)")
    ap.add_argument("--fps", type=float, help="output frame rate (default: first clip)")
    ap.add_argument("--fit", choices=["pad", "crop"], default="pad", help="how clips of another aspect reach the frame (default pad)")
    ap.add_argument("--pad-color", default="black")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if len(args.inputs) < 2:
        die("give at least two clips")
    metas = [probe(p) for p in args.inputs]
    for p, m in zip(args.inputs, metas):
        if not m.get("video"):
            die(f"{p} has no video stream")
    first = metas[0]["video"]
    fw, fh = first["width"], first["height"]
    if first.get("rotation") in (90, -90, 270, -270):
        fw, fh = fh, fw
    if args.width and args.height:
        w, h = args.width, args.height
    elif args.width:
        w, h = args.width, int(round(args.width * fh / fw))
    elif args.height:
        w, h = int(round(args.height * fw / fh)), args.height
    else:
        w, h = fw, fh
    fps = args.fps or first.get("fps") or 30.0
    fps = round(fps) if abs(fps - round(fps)) < 0.02 else fps
    w, h = w - (w % 2), h - (h % 2)
    durs = [m.get("duration") or 0.0 for m in metas]
    d = args.duration if args.transition != "none" else 0.0
    for p, dur in zip(args.inputs, durs):
        if d and dur <= d * 2 and not STATE["dry_run"]:
            die(f"{p} is only {dur:.2f}s, too short for a {d:.2f}s transition; shorten --duration")

    cmd = ffmpeg_base()
    extra_inputs: List[str] = []
    parts: List[str] = []
    n = len(args.inputs)
    for i, (p, m) in enumerate(zip(args.inputs, metas)):
        cmd += ["-i", p]
    # silent audio for clips without an audio track
    audio_src: List[str] = []
    for i, m in enumerate(metas):
        if m.get("audio"):
            audio_src.append(f"{i}:a:0")
        else:
            idx = n + len(extra_inputs)
            extra_inputs += ["-f", "lavfi", "-t", f"{durs[i]:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_src.append(f"{idx}:a:0")
    cmd += extra_inputs

    if args.fit == "crop":
        geo = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        geo = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}"
    pixfmt = "yuv420p10le" if (metas[0].get("video") or {}).get("hdr") else "yuv420p"
    for i in range(n):
        parts.append(f"[{i}:v]{geo},setsar=1,fps={fps:g},format={pixfmt},settb=AVTB[v{i}]")
        parts.append(f"[{audio_src[i]}]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")

    if args.transition == "none":
        chain = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{chain}concat=n={n}:v=1:a=1[vout][aout]")
    else:
        vprev, aprev = "v0", "a0"
        offset = 0.0
        for i in range(1, n):
            offset += durs[i - 1] - d
            vout = f"vx{i}" if i < n - 1 else "vout"
            aout = f"ax{i}" if i < n - 1 else "aout"
            parts.append(f"[{vprev}][v{i}]xfade=transition={args.transition}:duration={d:g}:offset={offset:.3f}[{vout}]")
            parts.append(f"[{aprev}][a{i}]acrossfade=d={d:g}:c1=tri:c2=tri[{aout}]")
            vprev, aprev = vout, aout

    output = args.output or default_output(args.inputs[0], "joined", "mp4")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]"]
    cmd += video_args(metas[0], args.crf, args.preset) + aac_args() + [output]
    run(cmd)
    expected = sum(durs) - d * (n - 1)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, expected ~{expected:.3f}s, {w}x{h} @ {fps:g}fps, {n} clips, {args.transition})")
    emit(output, clips=n, transition=args.transition, expected_duration=round(expected, 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
