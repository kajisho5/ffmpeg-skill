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

from _common.probe import PROBED_VIDEO, probed_maps
from _common.color import is_rgb
from _common.decision import line_matrix_filter
from _common.emit import note
from _common.runner import ffmpeg_failure_extra, require_filter
from _common import add_common, apply_common, aac_args, cfr_args, with_cfr, default_output, die, emit, escape_filter_path, ffmpeg_base, info, probe, require_tool, run_keeping_subtitles, video_args, X264_PRESETS, run_analysis, dry_run_input_pending, fmt_secs, record_fallback, EVEN_SCALE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_stab.<ext>)")
    ap.add_argument("--shakiness", type=int, default=5, help="the amount of shake to correct, the strength: 1 (barely shaky) .. 10 (very shaky), default 5")
    ap.add_argument("--smoothing", type=int, default=15, help="frames of camera-path smoothing on each side, default 15")
    ap.add_argument("--zoom", type=float, default=0.0, help="percent to zoom in to hide stabilization edges, 0..100 (default 0)")
    ap.add_argument("--crop", choices=["keep", "black"], default="keep", help="edges --zoom doesn't crop away: keep (stretch border pixels, default) or black (fill solid black)")
    ap.add_argument("--tripod", action="store_true", help="lock the frame fully still against a single reference frame instead of smoothing the camera's motion")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
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
    # pass 1 is a measurement that runs under --dry-run too: refused here, with the reason a run
    # that met "No such filter" gets, instead of as an unclassified pass-1 failure (#402)
    for name in ("vidstabdetect", "vidstabtransform"):
        require_filter(name, "stabilizing (vid.stab)")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "stab")

    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-vidstab-") as tmp:
        trf = str(Path(tmp) / "transforms.trf")
        trf_arg = escape_filter_path(trf)

        ffmpeg = require_tool("ffmpeg")
        # vid.stab asserts on an odd frame (ffmpeg aborts in pass 1, #438), so both passes see an
        # even one. Recorded like the runner's own odd-size retry: the output is a pixel narrower
        # or shorter than the source.
        v = meta["video"]
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        if int(v.get("rotation") or 0) % 180 == 90:
            w, h = h, w
        even = f"{EVEN_SCALE}," if (w % 2 or h % 2) else ""
        if even:
            record_fallback("source has odd dimensions; scaling to even before stabilizing (vid.stab needs it)",
                            "odd_dimensions_scaled_even", output=output, scale=EVEN_SCALE)
        # vid.stab aborts on an RGB picture (FFmpeg 6.1.1 with libvidstab 1.1: rgb24, bgr24, rgba
        # and gbrp all fail the assertion `fi->planes==1`), so pass 1 failed as kind ffmpeg on a
        # PNG still or an RGB .mov (#531), and yuv444p of the same frames runs. Both passes see YUV
        # 4:4:4: the conversion the encoder line folds into pass 2 for an RGB source
        # (line_matrix_filter: to BT.709 on the SDR line, with the matrix the line tags on a
        # BT.2020 / HDR one, #544), or, for an SDR source on a line that keeps the source's tags
        # and converts no matrix (--codec prores), FFmpeg's own conversion to yuv444p, as that
        # line's encoder has.
        to_yuv, to_yuv_pass2 = "", ""
        if is_rgb(meta):
            conv = line_matrix_filter(meta)
            to_yuv = (conv or "format=yuv444p") + ","
            to_yuv_pass2 = "" if conv else to_yuv  # the encoder line's conversion is folded in by run() (fold_bt709_matrix)
            note(f"the source is RGB ({v.get('pix_fmt')}), which vid.stab does not take: both passes stabilize a YUV 4:4:4 "
                 "copy of it, and the output's pixel format is the encoder line's (probe.video.pix_fmt)")
        detect_vf = f"{to_yuv}{even}vidstabdetect=shakiness={args.shakiness}:result={trf_arg}"
        if args.tripod:
            # A frame number, not a boolean: frame 1 is the standard reference for "lock to
            # this fixed frame" (mirrors vidstabtransform's own tripod=1 below).
            detect_vf += ":tripod=1"
        # both passes read the picture probe() describes (its size chose the even scale above)
        detect_cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", args.input,
                      "-map", f"0:{PROBED_VIDEO}", "-vf", detect_vf, "-f", "null", "-"]
        # Pass 1 is a measurement into a temp file (the transforms), so it runs under --dry-run
        # as well; only pass 2, the write, is skipped there.
        if not dry_run_input_pending(args.input):
            proc = run_analysis(detect_cmd, check=False, record=True)
            if proc.returncode != 0:
                die(f"stabilization analysis (pass 1) failed:\n{proc.stderr.strip()[-1500:]}", kind="ffmpeg", **ffmpeg_failure_extra(proc.stderr))

        crop_mode = {"keep": 0, "black": 1}[args.crop]
        # optzoom=0: the zoom is --zoom and nothing else. vidstab's default (optzoom=1) adds its own
        # "optimal" zoom on top, so --zoom 0 did not keep the original framing and --crop black
        # rarely had an edge to fill (through 3.8.8, audit A156)
        transform_vf = f"{to_yuv_pass2}{even}vidstabtransform=input={trf_arg}:smoothing={args.smoothing}:crop={crop_mode}:zoom={args.zoom:g}:optzoom=0"
        if args.tripod:
            # Equivalent to relative=0:smoothing=0 -- overrides --smoothing, since averaging a
            # camera path makes no sense once every frame is locked to one fixed reference.
            transform_vf += ":tripod=1"
        cmd = ffmpeg_base() + ["-i", args.input] + probed_maps(meta) + ["-vf", with_cfr(transform_vf, meta)]
        cmd += video_args(meta, args.crf, args.preset)
        cmd += cfr_args(meta)
        if has_audio:
            cmd += aac_args()
        else:
            cmd += ["-an"]
        # the frames keep their times, so the subtitle/data tracks are copied as fit.py and color.py
        # copy them, and dropped (said) only where the container refuses them (#520)
        dropped_streams = run_keeping_subtitles(cmd, output)

    result = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {result['video']['width']}x{result['video']['height']})")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
