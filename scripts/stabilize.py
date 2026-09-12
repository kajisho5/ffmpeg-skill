#!/usr/bin/env python3
"""Stabilize shaky video (FFmpeg's vidstab, two-pass).

Pass 1 (vidstabdetect) analyses camera motion and writes the transforms to a
temporary file; pass 2 (vidstabtransform) smooths that motion and re-renders
the frames. The transforms file lives in a temp directory for the duration of
this run only -- it is not a caller-facing artifact.

--shakiness (1 = barely shaky, fast; 10 = very shaky, slow analysis) and
--smoothing (how many neighbouring frames to average the camera path over)
are the two knobs that matter most; --zoom crops in slightly to hide the
edges stabilizing can introduce (0 = keep the original framing and let edges
show). --crop chooses what happens to any edge vidstab reveals that --zoom
doesn't crop away: "keep" (default) stretches the border pixels, "black"
fills it in solid black instead. --tripod locks the frame fully still
against a single reference frame (e.g. a camera meant to be static but
nudged, or a shot you want dead-locked rather than merely smoothed) instead
of following the camera's intended motion.

Examples:
  python3 stabilize.py shaky.mp4
  python3 stabilize.py shaky.mp4 --shakiness 8 --smoothing 20 --zoom 5
  python3 stabilize.py locked-off.mp4 --tripod --crop black
"""
import argparse
import sys
import tempfile
from pathlib import Path

from _common import STATE, add_common, apply_common, aac_args, cfr_args, default_output, die, emit, escape_filter_path, ffmpeg_base, info, probe, require_tool, run, video_args, X264_PRESETS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_stab.<ext>)")
    ap.add_argument("--shakiness", type=int, default=5, help="1 (barely shaky) .. 10 (very shaky), default 5")
    ap.add_argument("--smoothing", type=int, default=15, help="frames of camera-path smoothing on each side, default 15")
    ap.add_argument("--zoom", type=float, default=0.0, help="percent to zoom in to hide stabilization edges, 0..100 (default 0)")
    ap.add_argument("--crop", choices=["keep", "black"], default="keep", help="edges --zoom doesn't crop away: keep (stretch border pixels, default) or black (fill solid black)")
    ap.add_argument("--tripod", action="store_true", help="lock the frame fully still against a single reference frame instead of smoothing the camera's motion")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if not 1 <= args.shakiness <= 10:
        die(f"--shakiness must be 1..10, got {args.shakiness}")
    if not 0 <= args.smoothing <= 1000:
        die(f"--smoothing must be 0..1000, got {args.smoothing}")
    if not 0 <= args.zoom <= 100:
        die(f"--zoom must be 0..100, got {args.zoom}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "stab")

    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-vidstab-") as tmp:
        trf = str(Path(tmp) / "transforms.trf")
        trf_arg = escape_filter_path(trf)

        if not STATE["dry_run"]:
            ffmpeg = require_tool("ffmpeg")
            detect_vf = f"vidstabdetect=shakiness={args.shakiness}:result={trf_arg}"
            if args.tripod:
                # A frame number, not a boolean: frame 1 is the standard reference for "lock to
                # this fixed frame" (mirrors vidstabtransform's own tripod=1 below).
                detect_vf += ":tripod=1"
            detect_cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", args.input,
                          "-vf", detect_vf, "-f", "null", "-"]
            proc = run(detect_cmd, check=False)
            if proc.returncode != 0:
                die(f"stabilization analysis (pass 1) failed:\n{proc.stderr.strip()[-1500:]}")

        crop_mode = {"keep": 0, "black": 1}[args.crop]
        transform_vf = f"vidstabtransform=input={trf_arg}:smoothing={args.smoothing}:crop={crop_mode}:zoom={args.zoom:g}:optzoom=1"
        if args.tripod:
            # Equivalent to relative=0:smoothing=0 -- overrides --smoothing, since averaging a
            # camera path makes no sense once every frame is locked to one fixed reference.
            transform_vf += ":tripod=1"
        cmd = ffmpeg_base() + ["-i", args.input, "-vf", transform_vf]
        cmd += video_args(meta, args.crf, args.preset)
        cmd += cfr_args(meta)
        if has_audio:
            cmd += aac_args()
        else:
            cmd += ["-an"]
        cmd.append(output)
        run(cmd)

    result = probe(output, role="output")
    info(f"wrote {output} ({result['duration']:.3f}s, {result['video']['width']}x{result['video']['height']})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
