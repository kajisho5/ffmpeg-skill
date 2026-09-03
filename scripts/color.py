#!/usr/bin/env python3
"""Colour management: convert HDR (HDR10/PQ, HLG, BT.2020) to SDR BT.709 with
real tone mapping, apply a .cube LUT (Log footage, creative grades), or fix
wrong colour tags without re-encoding.

Examples:
  python3 color.py iphone_hdr.mov --to-sdr                       # PQ/HLG -> BT.709 SDR, hable tonemap
  python3 color.py iphone_hdr.mov --to-sdr --tonemap mobius --peak 1000
  python3 color.py slog3.mp4 --lut SLog3_to_Rec709.cube            # apply LUT (any Log -> 709 or a look)
  python3 color.py clip.mp4 --lut look.cube --lut-strength 0.6
  python3 color.py wrongly_tagged.mp4 --retag bt709                # metadata only, stream copy
  python3 color.py iphone_dv.mov --strip-dovi                       # drop Dolby Vision RPU, keep HLG base layer
  python3 color.py iphone_dv.mov --to-sdr                           # DV 8.4 = HLG base layer -> tone-mapped SDR
"""
import argparse
import os
import sys
from typing import List

from _common import add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_filter_path, ffmpeg_base, info, probe, run, x264_args

TONEMAPS = ["hable", "mobius", "reinhard", "bt2390", "clip", "linear", "gamma"]


def hdr_to_sdr_chain(meta: dict, tonemap: str, peak: float, desat: float) -> str:
    v = meta["video"]
    trc = v.get("color_transfer") or "smpte2084"
    prim = v.get("color_primaries") or "bt2020"
    space = v.get("color_space") or "bt2020nc"
    # zscale needs explicit input tags when the file lacks them
    chain: List[str] = [
        f"zscale=tin={trc}:pin={prim}:min={space}:rin={v.get('color_range') or 'tv'}:t=linear:npl={peak:g}",
        "format=gbrpf32le",
        "zscale=p=bt709",
        f"tonemap=tonemap={tonemap}:desat={desat:g}" + (":peak=%g" % (peak / 100.0) if tonemap in ("bt2390",) else ""),
        "zscale=t=bt709:m=bt709:r=tv",
        "format=yuv420p",
    ]
    return ",".join(chain)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_sdr / _lut / _retag)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--to-sdr", action="store_true", help="tone-map HDR (PQ/HLG/BT.2020) to SDR BT.709")
    mode.add_argument("--lut", help=".cube LUT to apply (3D)")
    mode.add_argument("--retag", choices=["bt709", "bt2020-pq", "bt2020-hlg", "bt601"], help="rewrite colour tags only (no re-encode)")
    mode.add_argument("--strip-dovi", action="store_true", help="remove the Dolby Vision RPU (profile 8.4 iPhone clips) so players use the plain HLG/HDR10 base layer; stream copy")
    ap.add_argument("--tonemap", choices=TONEMAPS, default="hable", help="tone-mapping curve (default hable)")
    ap.add_argument("--peak", type=float, default=1000.0, help="source peak brightness in nits used for PQ (default 1000)")
    ap.add_argument("--desat", type=float, default=0.0, help="tonemap desaturation strength (default 0)")
    ap.add_argument("--lut-strength", type=float, default=1.0, help="blend LUT result with the original, 0..1 (default 1)")
    ap.add_argument("--force", action="store_true", help="run --to-sdr even if the file is not tagged as HDR (treat as PQ)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    v = meta["video"]
    has_audio = bool(meta.get("audio"))

    if args.strip_dovi:
        output = args.output or default_output(args.input, "nodv")
        if v.get("codec") != "hevc":
            die("--strip-dovi only applies to HEVC (Dolby Vision) streams")
        if not v.get("dolby_vision"):
            info("note: no Dolby Vision metadata detected; removing unregistered SEI anyway")
        cmd = ffmpeg_base() + ["-i", args.input, "-map", "0", "-c", "copy", "-bsf:v", "filter_units=remove_types=62", "-tag:v", "hvc1"]
        if os.path.splitext(output)[1].lower() in (".mp4", ".mov", ".m4v"):
            cmd += ["-movflags", "+faststart"]
        cmd.append(output)
        run(cmd)
        r = probe(output)
        info(f"wrote {output} (dolby_vision={r['video'].get('dolby_vision')})")
        emit(output)
        return 0

    if args.retag:
        tags = {
            "bt709": ["bt709", "bt709", "bt709"],
            "bt2020-pq": ["bt2020nc", "bt2020", "smpte2084"],
            "bt2020-hlg": ["bt2020nc", "bt2020", "arib-std-b67"],
            "bt601": ["smpte170m", "smpte170m", "smpte170m"],
        }[args.retag]
        output = args.output or default_output(args.input, "retag")
        ext = os.path.splitext(output)[1].lower()
        cmd = ffmpeg_base() + ["-i", args.input, "-map", "0", "-c", "copy",
               "-colorspace", tags[0], "-color_primaries", tags[1], "-color_trc", tags[2]]
        if ext in (".mp4", ".mov", ".m4v"):
            cmd += ["-movflags", "+faststart"]
        cmd.append(output)
        proc = run(cmd, check=False)
        if proc.returncode != 0:
            # some codecs cannot carry retagged colour info without a bitstream filter; fall back to re-encode
            info("stream copy could not rewrite tags, re-encoding")
            cmd = ffmpeg_base() + ["-i", args.input, "-map", "0:v:0", "-map", "0:a:0?"] + x264_args(args.crf, args.preset, keep_bt709=False)
            cmd += ["-colorspace", tags[0], "-color_primaries", tags[1], "-color_trc", tags[2]] + (aac_args() if has_audio else []) + [output]
            run(cmd)
        info(f"wrote {output} (tags -> {args.retag})")
        emit(output)
        return 0

    if args.to_sdr:
        if not v.get("hdr") and not args.force:
            die(f"{args.input} is not tagged as HDR (transfer={v.get('color_transfer')}, primaries={v.get('color_primaries')}). Use --force to tone-map anyway.")
        vf = hdr_to_sdr_chain(meta, args.tonemap, args.peak, args.desat)
        output = args.output or default_output(args.input, "sdr")
        tag = "sdr"
    else:
        if not os.path.exists(args.lut):
            die(f"LUT not found: {args.lut}")
        lut = f"lut3d=file={escape_filter_path(args.lut)}:interp=tetrahedral"
        if 0 < args.lut_strength < 1:
            # blend graded and original
            vf = f"split[o][g];[g]{lut}[g2];[o][g2]blend=all_mode=normal:all_opacity={args.lut_strength:g},format=yuv420p"
        else:
            vf = f"{lut},format=yuv420p"
        output = args.output or default_output(args.input, "lut")
        tag = "lut"

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0", "-map", "0:a:0?"]
    cmd += x264_args(args.crf, args.preset) + cfr_args(meta) + (aac_args() if has_audio else []) + [output]
    run(cmd)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, {r['video']['width']}x{r['video']['height']}, "
         f"{r['video']['color_transfer']}/{r['video']['color_primaries']}, {tag})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
