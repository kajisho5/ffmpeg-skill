#!/usr/bin/env python3
"""Colour management: convert HDR (HDR10/PQ, HLG, BT.2020) to SDR BT.709 with
real tone mapping, apply a .cube LUT (Log footage, creative grades), fix wrong
colour tags without re-encoding, or apply typed primary colour correction
(exposure, contrast, saturation, gamma, white balance, three-way
lift/gain, levels, curves).

Examples:
  python3 color.py iphone_hdr.mov --to-sdr                       # PQ/HLG -> BT.709 SDR, hable tonemap
  python3 color.py iphone_hdr.mov --to-sdr --tonemap mobius --peak 1000
  python3 color.py slog3.mp4 --lut SLog3_to_Rec709.cube            # apply LUT (any Log -> 709 or a look)
  python3 color.py clip.mp4 --lut look.cube --lut-strength 0.6
  python3 color.py wrongly_tagged.mp4 --retag bt709                # metadata only, stream copy
  python3 color.py iphone_dv.mov --strip-dovi                       # drop Dolby Vision RPU, keep HLG base layer
  python3 color.py iphone_dv.mov --to-sdr                           # DV 8.4 = HLG base layer -> tone-mapped SDR
  python3 color.py flat.mp4 --correct --exposure 0.3 --contrast 1.1 --saturation 1.05 --temperature 5600 --tint -0.05
  python3 color.py flat.mp4 --correct --gamma 1.2 --lift 0.04 --gain -0.03   # three-way shadows/gamma/highlights
  python3 color.py flat.mp4 --correct --levels-in-black 16 --levels-in-white 235 --curves medium_contrast
"""
import argparse
import os
import sys
from typing import List

from _common import STATE, add_common, analyze_levels, apply_common, emit, aac_args, cfr_args, default_output, die, escape_filter_path, ffmpeg_base, info, probe, run, run_keeping_subtitles, x264_args, X264_PRESETS, fmt_secs

TONEMAPS = ["hable", "mobius", "reinhard", "bt2390", "clip", "linear", "gamma"]

# Typed primary correction: each flag is one option of one real, always-available libavfilter filter
# (never a caller-supplied filter string). Range is this script's own safe subset of what the filter
# documents (`ffmpeg -h filter=<name>`), not the filter's full technical range. default is each filter's
# own documented no-op value, so every stage in this dict is always emitted and the chain never depends
# on which flags were actually given (exposure/temperature/tint/gamma/lift/gain). `colorlevels` and
# `curves` (see LEVELS and CURVES_PRESETS below) are the exception: they only add a term to the chain
# when the caller actually asks for them, because "levels 0..255 in, 0..255 out" and "no curve" are
# already the identity operation without emitting a no-op filter term for it.
CORRECTION = {
    #      flag           default  lo      hi       unit
    "exposure":    (0.0,   -3.0,    3.0,   "stops"),   # exposure filter's own full range (linear-domain stops)
    "contrast":    (1.0,    0.0,    2.0,   "x"),       # eq filter; 0=flat grey, 1=unchanged, 2=double contrast
    "saturation":  (1.0,    0.0,    2.0,   "x"),       # eq filter; 0=grayscale, 1=unchanged, 2=double saturation
    "temperature": (6500.0, 2000.0, 12000.0, "K"),     # colortemperature filter; 6500=unchanged (its own default)
    "tint":        (0.0,   -1.0,    1.0,   "x"),       # mapped to colorbalance midtones, see correction_chain()
    "gamma":       (1.0,    0.1,   10.0,   "x"),       # eq filter's own gamma option; 1=unchanged (its own default)
    "lift":        (0.0,   -1.0,    1.0,   "x"),       # colorbalance shadows (rs=gs=bs); 0=unchanged
    "gain":        (0.0,   -1.0,    1.0,   "x"),       # colorbalance highlights (rh=gh=bh); 0=unchanged
}

# colorlevels takes fractional 0.0..1.0 input/output black/white points; this tool exposes the
# familiar 8-bit 0..255 unit instead and divides by 255.0 when building the filter (same convention
# as the rest of CORRECTION: a human-friendly CLI unit formatted into the filter's own native unit).
LEVELS = {
    #             flag             default  lo   hi
    "levels_in_black":  (0,     0, 255),
    "levels_in_white":  (255,   0, 255),
    "levels_out_black": (0,     0, 255),
    "levels_out_white": (255,   0, 255),
}

# curves filter's real built-in presets (`ffmpeg -h filter=curves`), excluding its own "none" (0):
# omitting --curves already gets that identity result without adding a filter term for it.
CURVES_PRESETS = ["color_negative", "cross_process", "darker", "increase_contrast", "lighter",
                   "linear_contrast", "medium_contrast", "negative", "strong_contrast", "vintage"]


def _checked(args: argparse.Namespace, flag: str) -> float:
    _, lo, hi, unit = CORRECTION[flag]
    value = getattr(args, flag)
    if not (lo <= value <= hi):
        die(f"--{flag} {value:g} is outside {lo:g}..{hi:g} {unit} (the safe range this tool guarantees)")
    return value


def _checked_levels(args: argparse.Namespace, flag: str) -> int:
    _, lo, hi = LEVELS[flag]
    value = getattr(args, flag)
    if not (lo <= value <= hi):
        die(f"--{flag.replace('_', '-')} {value} is outside {lo}..{hi} (8-bit units, scaled to colorlevels' own 0..1 range)")
    return value


def correction_chain(args: argparse.Namespace) -> str:
    """Always-present filter stages, in a fixed order chosen so each stage sees a picture already
    corrected by the previous one: exposure (linear light level) -> white balance (temperature/tint/
    lift/gain, so contrast/saturation act on colour-balanced footage) -> contrast/saturation/gamma
    (the most creative-adjacent stage of the always-on chain). `tint` (-1 green .. +1 magenta) is not
    a single ffmpeg option: it is expressed as colorbalance's three midtone channels (gm=-tint,
    rm=bm=tint/2) so a positive tint shifts midtones toward magenta and a negative one toward green
    without changing overall midtone lightness, the same balanced-axis convention colour tools use
    for a one-dial tint control. `lift` and `gain` extend the same colorbalance call to the shadow
    (rs=gs=bs=lift) and highlight (rh=gh=bh=gain) channels, giving a classic three-way shadows/
    midtones/highlights correction in one filter invocation. `gamma` is folded into the same `eq`
    term contrast/saturation already use, as `eq`'s own `gamma` option. Two further stages are
    appended only when asked for, since their own identity value would otherwise add a no-op filter
    term to the chain: `colorlevels` (--levels-*, 8-bit units scaled to the filter's 0..1 range) and
    `curves` (--curves, one of the filter's own named presets)."""
    exposure = _checked(args, "exposure")
    contrast = _checked(args, "contrast")
    saturation = _checked(args, "saturation")
    temperature = _checked(args, "temperature")
    tint = _checked(args, "tint")
    gamma = _checked(args, "gamma")
    lift = _checked(args, "lift")
    gain = _checked(args, "gain")
    in_black = _checked_levels(args, "levels_in_black")
    in_white = _checked_levels(args, "levels_in_white")
    out_black = _checked_levels(args, "levels_out_black")
    out_white = _checked_levels(args, "levels_out_white")
    if in_black >= in_white:
        die(f"--levels-in-black {in_black} must be less than --levels-in-white {in_white}")
    if out_black >= out_white:
        die(f"--levels-out-black {out_black} must be less than --levels-out-white {out_white}")

    gm, rm, bm = -tint, tint / 2.0, tint / 2.0
    rgb = [
        f"exposure=exposure={exposure:g}",
        f"colortemperature=temperature={temperature:g}",
        f"colorbalance=rs={lift:g}:gs={lift:g}:bs={lift:g}:rm={rm:g}:gm={gm:g}:bm={bm:g}:rh={gain:g}:gh={gain:g}:bh={gain:g}",
    ]
    terms = [_rgb_stage(rgb), f"eq=contrast={contrast:g}:saturation={saturation:g}:gamma={gamma:g}"]
    rgb2 = []
    if (in_black, in_white, out_black, out_white) != (0, 255, 0, 255):
        rimin, rimax = in_black / 255.0, in_white / 255.0
        romin, romax = out_black / 255.0, out_white / 255.0
        rgb2.append(
            f"colorlevels=rimin={rimin:g}:gimin={rimin:g}:bimin={rimin:g}:"
            f"rimax={rimax:g}:gimax={rimax:g}:bimax={rimax:g}:"
            f"romin={romin:g}:gomin={romin:g}:bomin={romin:g}:"
            f"romax={romax:g}:gomax={romax:g}:bomax={romax:g}"
        )
    if args.curves:
        rgb2.append(f"curves=preset={args.curves}")
    if rgb2:
        terms.append(_rgb_stage(rgb2))
    return ",".join(terms)


def _rgb_stage(filters: list) -> str:
    """Wrap a run of RGB-only filters in explicit, matching YUV<->RGB conversions.

    exposure/colortemperature/colorbalance/colorlevels/curves take RGB, so libavfilter inserts a
    swscale conversion on each side. Left to itself, the way in honours the frame's colour tag
    (bt709 on any camera or export.py file) while the way back uses swscale's default matrix
    (bt601): on a bt709-tagged source an all-defaults --correct came out 26 dB PSNR from its
    input and ~8 % less saturated (#159). Untagged sources never showed it because both legs
    then fall back to bt601 and cancel. Pinning both legs to the same matrix restores the
    identity on every source (39 dB, the same as an untagged one always got); bt601 on both
    sides measured better than bt709 on both (34 dB) because swscale's 601 path round-trips
    8-bit 4:2:0 more exactly. The matrix here is only the working space of the conversion pair,
    never a tag: the output carries the encoder's BT.709 tags as before."""
    return ("scale=in_color_matrix=bt601,format=gbrpf32le," + ",".join(filters)
            + ",scale=out_color_matrix=bt601,format=yuv420p")


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
    mode.add_argument("--correct", action="store_true", help="typed primary colour correction: --exposure/--contrast/--saturation/--temperature/--tint/--gamma/--lift/--gain/--levels-*/--curves")
    ap.add_argument("--tonemap", choices=TONEMAPS, default="hable", help="tone-mapping curve (default hable)")
    ap.add_argument("--peak", type=float, default=1000.0, help="source peak brightness in nits used for PQ (default 1000)")
    ap.add_argument("--desat", type=float, default=0.0, help="tonemap desaturation strength (default 0)")
    ap.add_argument("--lut-strength", type=float, default=1.0, help="blend LUT result with the original, 0..1 (default 1)")
    ap.add_argument("--force", action="store_true", help="run --to-sdr even if the file is not tagged as HDR (treat as PQ)")
    ap.add_argument("--exposure", type=float, default=CORRECTION["exposure"][0], help="--correct: exposure in stops, -3..3 (default 0)")
    ap.add_argument("--contrast", type=float, default=CORRECTION["contrast"][0], help="--correct: contrast, 0..2, 1=unchanged (default 1)")
    ap.add_argument("--saturation", type=float, default=CORRECTION["saturation"][0], help="--correct: saturation, 0..2, 1=unchanged (default 1)")
    ap.add_argument("--temperature", type=float, default=CORRECTION["temperature"][0], help="--correct: white-balance temperature in Kelvin, 2000..12000, 6500=unchanged (default 6500)")
    ap.add_argument("--tint", type=float, default=CORRECTION["tint"][0], help="--correct: green(-1)/magenta(+1) tint, 0=unchanged (default 0)")
    ap.add_argument("--gamma", type=float, default=CORRECTION["gamma"][0], help="--correct: master gamma (eq filter's own gamma), 0.1..10, 1=unchanged (default 1)")
    ap.add_argument("--lift", type=float, default=CORRECTION["lift"][0], help="--correct: shadows lift (colorbalance rs/gs/bs), -1..1, 0=unchanged (default 0)")
    ap.add_argument("--gain", type=float, default=CORRECTION["gain"][0], help="--correct: highlights gain (colorbalance rh/gh/bh), -1..1, 0=unchanged (default 0)")
    ap.add_argument("--levels-in-black", type=int, default=LEVELS["levels_in_black"][0], help="--correct: colorlevels input black point, 0..255 (default 0, unchanged)")
    ap.add_argument("--levels-in-white", type=int, default=LEVELS["levels_in_white"][0], help="--correct: colorlevels input white point, 0..255 (default 255, unchanged)")
    ap.add_argument("--levels-out-black", type=int, default=LEVELS["levels_out_black"][0], help="--correct: colorlevels output black point, 0..255 (default 0, unchanged)")
    ap.add_argument("--levels-out-white", type=int, default=LEVELS["levels_out_white"][0], help="--correct: colorlevels output white point, 0..255 (default 255, unchanged)")
    ap.add_argument("--curves", choices=CURVES_PRESETS, default=None, help="--correct: curves filter built-in preset (default: none, no curves term added)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did. Only affects modes that re-encode "
                          "audio (--to-sdr, --lut, --correct, and --retag's re-encode fallback) -- --strip-dovi and "
                          "a successful --retag stream-copy all streams untouched, so the flag has nothing to select there.")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS)
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    v = meta["video"]
    has_audio = bool(meta.get("audio"))
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")

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
        r = probe(output, role="output")
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
        dropped_streams = False
        if proc.returncode != 0:
            # Some codecs cannot carry retagged colour info without a bitstream filter, so the
            # stream copy above fails and we fall back to re-encoding video+audio. The copy path
            # (-map 0 -c copy) keeps every stream -- extra audio tracks, subtitles, chapters,
            # attached pictures -- byte-for-byte; -c:s/-c:d copy here keeps that same guarantee
            # for subtitle/data streams even though video/audio must be re-encoded. Only if THAT
            # also fails (e.g. a subtitle codec genuinely incompatible with the target container)
            # do we drop to video+selected-audio-only, and even then we say so explicitly rather
            # than silently reporting "completed" with streams missing.
            info("stream copy could not rewrite tags, re-encoding video/audio (subtitles/data streams kept)")
            cmd = ffmpeg_base() + ["-i", args.input, "-map", "0:v:0", "-map", f"0:a:{args.audio_stream}?",
                                    "-map", "0:s?", "-map", "0:d?"] + x264_args(args.crf, args.preset, keep_bt709=False)
            cmd += ["-colorspace", tags[0], "-color_primaries", tags[1], "-color_trc", tags[2]]
            cmd += (aac_args() if has_audio else []) + ["-c:s", "copy", "-c:d", "copy"] + [output]
            proc2 = run(cmd, check=False)
            if proc2.returncode != 0:
                info("re-encode with subtitles/data streams kept also failed; dropping them")
                dropped_streams = True
                cmd = ffmpeg_base() + ["-i", args.input, "-map", "0:v:0", "-map", f"0:a:{args.audio_stream}?"] + x264_args(args.crf, args.preset, keep_bt709=False)
                cmd += ["-colorspace", tags[0], "-color_primaries", tags[1], "-color_trc", tags[2]] + (aac_args() if has_audio else []) + [output]
                run(cmd)
        info(f"wrote {output} (tags -> {args.retag})")
        emit(output, reencoded=proc.returncode != 0, dropped_non_av_streams=dropped_streams)
        return 0

    measurements = None
    if args.to_sdr:
        if not v.get("hdr") and not args.force:
            die(f"{args.input} is not tagged as HDR (transfer={v.get('color_transfer')}, primaries={v.get('color_primaries')}). Use --force to tone-map anyway.")
        vf = hdr_to_sdr_chain(meta, args.tonemap, args.peak, args.desat)
        output = args.output or default_output(args.input, "sdr")
        tag = "sdr"
    elif args.correct:
        if v.get("hdr") and not args.force:
            die(f"{args.input} is HDR ({v.get('hdr_format')}); --correct works on SDR pixels and would tag PQ/HLG data as BT.709 "
                f"without a tone map (sweep F10). Run --to-sdr first, or --force to grade the raw values anyway")
        vf = correction_chain(args)
        output = args.output or default_output(args.input, "correct")
        tag = "correct"
        # OBSERVED technical measurements (signalstats: luma / saturation distribution), never a
        # "looks better" judgement -- the same primitive probe.py --analyze uses for Log detection.
        measurements = None if STATE.dry_run else {"input": analyze_levels(args.input)}
    else:
        if v.get("hdr") and not args.force:
            die(f"{args.input} is HDR ({v.get('hdr_format')}); a LUT made for SDR applied to PQ/HLG pixels gives a wrong picture "
                f"tagged BT.709 (sweep F10). Run --to-sdr first (or chain it), or --force if the LUT expects HDR input")
        if not os.path.exists(args.lut):
            die(f"LUT not found: {args.lut}")
        if not (0.0 <= args.lut_strength <= 1.0):
            die(f"--lut-strength {args.lut_strength:g} is outside 0..1")
        lut = f"lut3d=file={escape_filter_path(args.lut)}:interp=tetrahedral"
        if args.lut_strength == 0.0:
            # 0 means "no LUT at all" -- without this branch, 0 (falling outside the open interval
            # below) landed in the same "apply the LUT at full strength" fallback as an out-of-range
            # value did before the guard above existed: the one strength value documented to mean
            # "don't grade it" instead silently graded it at 100%, the opposite of what was asked.
            vf = "format=yuv420p"
        elif args.lut_strength < 1.0:
            # blend graded and original
            vf = f"split[o][g];[g]{lut}[g2];[o][g2]blend=all_mode=normal:all_opacity={args.lut_strength:g},format=yuv420p"
        else:
            vf = f"{lut},format=yuv420p"
        output = args.output or default_output(args.input, "lut")
        tag = "lut"

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf, "-map", "0:v:0", "-map", f"0:a:{args.audio_stream}?"]
    cmd += x264_args(args.crf, args.preset) + cfr_args(meta) + (aac_args() if has_audio else [])
    dropped_streams = run_keeping_subtitles(cmd, output)
    r = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, {r['video']['width']}x{r['video']['height']}, "
         f"{r['video']['color_transfer']}/{r['video']['color_primaries']}, {tag})")
    extra = {"dropped_non_av_streams": dropped_streams}
    if measurements is not None:
        measurements["output"] = analyze_levels(output)
        extra["measurements"] = measurements
    emit(output, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
