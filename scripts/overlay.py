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

from _common import aac_args, default_output, die, escape_drawtext, escape_filter_path, ffmpeg_base, info, parse_time, probe, run, x264_args

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
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="PNG/JPG (alpha respected) to composite")
    src.add_argument("--text", help="text to draw (drawtext)")
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
    args = ap.parse_args()

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
        if args.fade > 0 and (start is not None or end is not None):
            s = start if start is not None else 0.0
            chain.append(f"fade=t=in:st={s:.3f}:d={args.fade:g}:alpha=1")
            if end is not None:
                chain.append(f"fade=t=out:st={end - args.fade:.3f}:d={args.fade:g}:alpha=1")
        x, y = position_exprs(args.position, args.margin, text_mode=False)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        # -loop 1 turns the still into a timed stream so fade/enable expressions see real timestamps
        cmd = ffmpeg_base() + ["-i", args.input, "-loop", "1", "-i", args.image]
        fc = f"[1:v]{','.join(chain)},setpts=PTS-STARTPTS[ov];[0:v][ov]{ov}[out]"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", "0:a?", "-shortest"]
    else:
        x, y = position_exprs(args.position, args.margin, text_mode=True)
        opts = [f"text='{escape_drawtext(args.text)}'", f"fontsize={args.font_size}", f"x={x}", f"y={y}",
                f"borderw={args.border}", f"bordercolor={args.border_color}"]
        if args.font_file:
            opts.append(f"fontfile={escape_filter_path(args.font_file)}")
        else:
            opts.append(f"font='{args.font}'")
        alpha = alpha_expr(args.opacity, start, end, args.fade)
        opts.append(f"fontcolor={args.font_color}")
        if alpha != "1":
            opts.append(f"alpha='{alpha}'")
        if args.box:
            opts += ["box=1", f"boxcolor={args.box_color}", "boxborderw=12"]
        if enable:
            opts.append(f"enable='{enable}'")
        cmd += ["-vf", "drawtext=" + ":".join(opts)]

    cmd += x264_args(args.crf, args.preset)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    cmd.append(output)
    run(cmd)
    result = probe(output)
    info(f"wrote {output} ({result['duration']:.3f}s)")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
