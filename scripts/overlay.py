#!/usr/bin/env python3
"""Composite a logo/image or a text title onto a video with position, timing,
opacity and fade in/out.

Positions: top-left, top, top-right, left, center, right, bottom-left, bottom,
bottom-right, or explicit "X,Y" pixels (negative counts from the far edge).

Examples:
  python3 overlay.py input.mp4 --image logo.png --position top-right --scale 200 --opacity 0.8
  python3 overlay.py input.mp4 --image lower_third.png --position bottom-left --start 2 --end 8 --fade 0.5
  python3 overlay.py input.mp4 --text "Episode 12" --position bottom --font-size 48 --start 1 --end 5 --fade 0.3
  python3 overlay.py input.mp4 --text "こんにちは" --font-file /path/NotoSansCJK-Bold.ttc --box
"""
import argparse
import sys
from typing import List, Optional

from _common import STATE, load_brand, video_args, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_drawtext, escape_filter_path, ffmpeg_base, info, parse_time, probe, run, x264_args

POS = {
    "top-left": ("{m}", "{m}"),
    "top": ("(W-w)/2", "{m}"),
    "top-right": ("W-w-{m}", "{m}"),
    "left": ("{m}", "(H-h)/2"),
    "center": ("(W-w)/2", "(H-h)/2"),
    "right": ("W-w-{m}", "(H-h)/2"),
    "bottom-left": ("{m}", "H-h-{m}"),
    "bottom": ("(W-w)/2", "H-h-{m}"),
    "bottom-right": ("W-w-{m}", "H-h-{m}"),
}


def position_exprs(pos: str, margin: int, text_mode: bool):
    if pos in POS:
        x, y = (e.format(m=margin) for e in POS[pos])
    else:
        try:
            xs, ys = pos.split(",")
            xv, yv = int(xs), int(ys)
        except ValueError:
            die(f"bad --position '{pos}'")
        x = f"W-w{xv}" if xv < 0 else str(xv)
        y = f"H-h{yv}" if yv < 0 else str(yv)
    if text_mode:
        # drawtext uses w/h for the text box but lower-case main dims differ: W/H -> w/h, w/h -> text_w/text_h
        x = x.replace("W", "main_w").replace("w", "text_w").replace("H", "main_h").replace("h", "text_h")
        y = y.replace("W", "main_w").replace("w", "text_w").replace("H", "main_h").replace("h", "text_h")
        x = x.replace("main_text_w", "main_w").replace("main_text_h", "main_h")
        y = y.replace("main_text_w", "main_w").replace("main_text_h", "main_h")
    return x, y


def enable_expr(start: Optional[float], end: Optional[float]) -> str:
    if start is None and end is None:
        return ""
    s = f"{start:.3f}" if start is not None else "0"
    if end is None:
        return f"gte(t,{s})"
    return f"between(t,{s},{end:.3f})"


def alpha_expr(opacity: float, start: Optional[float], end: Optional[float], fade: float) -> str:
    """Time-varying alpha with linear fade in/out inside [start, end]."""
    if fade <= 0 or (start is None and end is None):
        return f"{opacity:g}"
    s = start if start is not None else 0.0
    parts = [f"{opacity:g}"]
    fin = f"min(1,(t-{s:.3f})/{fade:g})"
    parts.append(fin)
    if end is not None:
        parts.append(f"min(1,({end:.3f}-t)/{fade:g})")
    return "max(0," + "*".join(parts) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_overlay.<ext>)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--image", help="PNG/JPG (alpha respected) to composite")
    src.add_argument("--text", help="text to draw (drawtext)")
    src.add_argument("--logo", action="store_true", help="composite the brand logo from --brand (position/scale/opacity from brand.json)")
    ap.add_argument("--brand", help="brand.json (logo, font, colours, safe margin)")
    ap.add_argument("--position", default="top-right", help="named position or X,Y (default top-right)")
    ap.add_argument("--margin", type=int, default=24, help="margin from the edges in px (default 24)")
    ap.add_argument("--start", help="show from this time (default: whole video)")
    ap.add_argument("--end", help="hide after this time")
    ap.add_argument("--fade", type=float, default=0.0, help="fade in/out duration in seconds")
    ap.add_argument("--opacity", type=float, default=1.0, help="0..1 (default 1)")
    img = ap.add_argument_group("image options")
    img.add_argument("--scale", type=int, help="scale the image to this width in px (keeps aspect)")
    img.add_argument("--scale-percent", type=float, help="scale the image to this %% of the video width")
    txt = ap.add_argument_group("text options")
    txt.add_argument("--font", default="DejaVu Sans", help="fontconfig font name")
    txt.add_argument("--font-file", help="explicit .ttf/.otf/.ttc path (use this for CJK fonts)")
    txt.add_argument("--font-size", type=int, default=42)
    txt.add_argument("--font-color", default="white")
    txt.add_argument("--border", type=int, default=2, help="text outline width (default 2)")
    txt.add_argument("--border-color", default="black")
    txt.add_argument("--box", action="store_true", help="draw a translucent box behind the text")
    txt.add_argument("--box-color", default="black@0.5")
    enc = ap.add_argument_group("encoding")
    enc.add_argument("--crf", type=int, default=18)
    enc.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    brand = load_brand(args.brand)
    if args.logo:
        if not brand.get("logo"):
            die("--logo needs a brand.json with a 'logo' entry")
        args.image = brand["logo"]
        if args.position == ap.get_default("position"):
            args.position = brand.get("logo_position", "top-right")
        if not args.scale and not args.scale_percent:
            args.scale = int(brand.get("logo_scale", 160))
        if args.opacity == 1.0:
            args.opacity = float(brand.get("logo_opacity", 1.0))
    if not (args.image or args.text):
        die("give --image, --text or --logo")
    if args.brand:
        if args.margin == ap.get_default("margin"):
            args.margin = int(brand.get("safe_margin", args.margin))
        if args.font == ap.get_default("font"):
            args.font = brand.get("font", args.font)
        if not args.font_file and brand.get("font_file"):
            args.font_file = brand["font_file"]
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    vw = meta["video"]["width"]
    start = parse_time(args.start) if args.start else None
    end = parse_time(args.end) if args.end else None
    if start is not None and end is not None and end <= start:
        die("--end must be after --start")
    if not 0 <= args.opacity <= 1:
        die("--opacity must be within 0..1")

    output = args.output or default_output(args.input, "overlay")
    enable = enable_expr(start, end)
    cmd = ffmpeg_base() + ["-i", args.input]

    if args.image:
        probe(args.image)
        chain: List[str] = ["format=rgba"]
        if args.scale_percent:
            chain.append(f"scale={int(vw * args.scale_percent / 100)}:-1")
        elif args.scale:
            chain.append(f"scale={args.scale}:-1")
        if args.opacity < 1:
            chain.append(f"colorchannelmixer=aa={args.opacity:g}")
        if args.fade > 0:
            # no --start/--end: fade in at 0 and out at the end of the video
            s = start if start is not None else 0.0
            e = end if end is not None else (meta.get("duration") or 0.0)
            chain.append(f"fade=t=in:st={s:.3f}:d={args.fade:g}:alpha=1")
            if e > args.fade:
                chain.append(f"fade=t=out:st={e - args.fade:.3f}:d={args.fade:g}:alpha=1")
        x, y = position_exprs(args.position, args.margin, text_mode=False)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        # -loop 1 turns the still into a timed stream so fade/enable expressions see real timestamps
        cmd = ffmpeg_base() + ["-i", args.input, "-loop", "1", "-i", args.image]
        fc = f"[1:v]{','.join(chain)},setpts=PTS-STARTPTS[ov];[0:v][ov]{ov}[out]"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", "0:a:0?", "-shortest"]
    else:
        x, y = position_exprs(args.position, args.margin, text_mode=True)
        opts = [f"text='{escape_drawtext(args.text)}'", f"fontsize={args.font_size}", f"x={x}", f"y={y}",
                f"borderw={args.border}", f"bordercolor={args.border_color}"]
        if args.font_file:
            opts.append(f"fontfile={escape_filter_path(args.font_file)}")
        else:
            opts.append(f"font='{args.font}'")
        alpha = alpha_expr(args.opacity, start if start is not None else (0.0 if args.fade > 0 else None),
                           end if end is not None else ((meta.get("duration") or None) if args.fade > 0 else None), args.fade)
        opts.append(f"fontcolor={args.font_color}")
        if alpha != "1":
            opts.append(f"alpha='{alpha}'")
        if args.box:
            opts += ["box=1", f"boxcolor={args.box_color}", "boxborderw=12"]
        if enable:
            opts.append(f"enable='{enable}'")
        cmd += ["-vf", "drawtext=" + ":".join(opts)]

    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    cmd.append(output)
    run(cmd)
    if not STATE.dry_run:
        result = probe(output)
        info(f"wrote {output} ({result['duration']:.3f}s)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
