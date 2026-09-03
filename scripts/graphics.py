#!/usr/bin/env python3
"""Motion-graphics templates rendered with drawbox/drawtext expressions —
no After Effects, no image assets, brand colours from brand.json.

Templates:
  lower-third   name + title bar sliding in from the left (--name, --title)
  title         centred title card with optional subtitle, fade in/out (--title, --subtitle)
  chapter       small chip in a corner (--title), e.g. "Part 2 — Setup"
  progress      thin progress bar along the bottom that fills over the clip (or --start/--end)
  countdown     big numbers counting down from --from to 0 (--start/--end define the window)
  bug           persistent text bug (--title) in a corner, e.g. "@handle" or "LIVE"

Examples:
  python3 graphics.py talk.mp4 --template lower-third --name "Ada Lovelace" --title "Analyst" --start 2 --end 8
  python3 graphics.py talk.mp4 --template title --title "Episode 12" --subtitle "The math of video" --start 0 --end 4
  python3 graphics.py talk.mp4 --template progress --brand brand.json
  python3 graphics.py intro.mp4 --template countdown --from 5 --start 1 --end 6
  python3 graphics.py clip.mp4 --template chapter --title "Part 2 — Setup" --position top-left --start 0 --end 5
"""
import argparse
import sys
from typing import List, Optional

from _common import aac_args, add_common, apply_common, cfr_args, color_hex, default_output, die, emit, escape_drawtext, escape_filter_path, ffmpeg_base, info, load_brand, parse_time, probe, run, video_args

TEMPLATES = ["lower-third", "title", "chapter", "progress", "countdown", "bug"]


def ff_color(hex_rgb: str, alpha: float = 1.0) -> str:
    return f"0x{color_hex(hex_rgb)}@{alpha:g}"


def font_opts(brand: dict, font: Optional[str], font_file: Optional[str]) -> str:
    if font_file or brand.get("font_file"):
        return f"fontfile={escape_filter_path(font_file or brand['font_file'])}"
    return f"font='{font or brand.get('font', 'DejaVu Sans')}'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_gfx.<ext>)")
    ap.add_argument("--template", choices=TEMPLATES, required=True)
    ap.add_argument("--brand", help="brand.json for colours, font, safe margin")
    ap.add_argument("--name", help="lower-third: name line")
    ap.add_argument("--title", help="title / chapter / bug text, or lower-third second line")
    ap.add_argument("--subtitle", help="title: smaller second line")
    ap.add_argument("--from", dest="count_from", type=int, default=5, help="countdown start number (default 5)")
    ap.add_argument("--start", help="show from (default 0)")
    ap.add_argument("--end", help="hide after (default end of clip)")
    ap.add_argument("--position", choices=["top-left", "top-right", "bottom-left", "bottom-right"], default=None, help="corner for chapter/bug (default bottom-left / top-right)")
    ap.add_argument("--primary", help="override brand primary colour RRGGBB")
    ap.add_argument("--text-color", help="override text colour RRGGBB")
    ap.add_argument("--font")
    ap.add_argument("--font-file")
    ap.add_argument("--scale", type=float, default=1.0, help="size multiplier (default 1)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    brand = load_brand(args.brand)
    primary = color_hex(args.primary or brand["colors"]["primary"])
    text_c = color_hex(args.text_color or brand["colors"]["text"])
    bg = color_hex(brand["colors"].get("background", "101418"))
    margin = int(brand.get("safe_margin", 48))
    fo = font_opts(brand, args.font, args.font_file)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    W, H = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        W, H = H, W
    dur = meta.get("duration") or 0.0
    s = parse_time(args.start) if args.start else 0.0
    e = parse_time(args.end) if args.end else dur
    if e <= s:
        die("--end must be after --start")
    en = f"enable='between(t,{s:.3f},{e:.3f})'"
    base = min(W, H) * args.scale  # scale everything from the short side
    filters: List[str] = []
    fade_a = f"if(lt(t,{s:.3f}+0.3),(t-{s:.3f})/0.3,if(gt(t,{e:.3f}-0.3),({e:.3f}-t)/0.3,1))"

    extra_inputs: List[str] = []
    fc: List[str] = []  # filter_complex chains (used by templates that need animated boxes)
    if args.template == "lower-third":
        if not args.name:
            die("lower-third needs --name")
        h1 = int(base * 0.055)
        h2 = int(base * 0.038)
        pad = int(base * 0.02)
        bar_h = h1 + (h2 + pad if args.title else 0) + pad * 2
        bar_w = int(base * 0.62)
        y0 = H - margin - bar_h
        # slide in from the left over 0.4 s, slide out over 0.3 s (overlay evaluates x per frame)
        x_expr = f"if(lt(t,{s:.3f}+0.4),-{bar_w}+({bar_w}+{margin})*((t-{s:.3f})/0.4),if(gt(t,{e:.3f}-0.3),{margin}-({bar_w}+{margin})*(1-({e:.3f}-t)/0.3),{margin}))"
        fc.append(f"color=c=0x{bg}@0.85:s={bar_w}x{bar_h}:r={meta['video'].get('fps') or 30:g},format=rgba[bar]")
        fc.append(f"color=c=0x{primary}:s={int(base * 0.012)}x{bar_h}:r={meta['video'].get('fps') or 30:g},format=rgba[acc]")
        fc.append(f"[0:v][bar]overlay=x='{x_expr}':y={y0}:{en}:eof_action=pass[v1]")
        fc.append(f"[v1][acc]overlay=x='{x_expr}':y={y0}:{en}:eof_action=pass[v2]")
        tx = f"({x_expr})+{int(base * 0.035)}"
        chain = f"drawtext=text='{escape_drawtext(args.name)}':{fo}:fontsize={h1}:fontcolor={ff_color(text_c)}:x='{tx}':y={y0 + pad}:{en}"
        if args.title:
            chain += f",drawtext=text='{escape_drawtext(args.title)}':{fo}:fontsize={h2}:fontcolor={ff_color(primary)}:x='{tx}':y={y0 + pad + h1 + pad // 2}:{en}"
        fc.append(f"[v2]{chain}[vout]")

    elif args.template == "title":
        if not args.title:
            die("title needs --title")
        h1 = int(base * 0.11)
        h2 = int(base * 0.045)
        filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={ff_color(bg, 0.55)}:t=fill:{en}")
        filters.append(f"drawtext=text='{escape_drawtext(args.title)}':{fo}:fontsize={h1}:fontcolor={ff_color(text_c)}:x=(w-text_w)/2:y=(h-text_h)/2-{h2 if args.subtitle else 0}:alpha='{fade_a}':{en}")
        filters.append(f"drawbox=x=(iw-{int(base * 0.12)})/2:y=(ih)/2+{h1 // 2 + (0 if args.subtitle else 0)}:w={int(base * 0.12)}:h={max(2, int(base * 0.006))}:color={ff_color(primary)}:t=fill:{en}")
        if args.subtitle:
            filters.append(f"drawtext=text='{escape_drawtext(args.subtitle)}':{fo}:fontsize={h2}:fontcolor={ff_color(primary)}:x=(w-text_w)/2:y=(h-text_h)/2+{h1 // 2 + int(base * 0.03)}:alpha='{fade_a}':{en}")

    elif args.template in ("chapter", "bug"):
        if not args.title:
            die(f"{args.template} needs --title")
        pos = args.position or ("bottom-left" if args.template == "chapter" else "top-right")
        fs = int(base * (0.04 if args.template == "chapter" else 0.032))
        padx, pady = int(fs * 0.6), int(fs * 0.35)
        xe = f"{margin}" if "left" in pos else f"w-text_w-{margin}"
        ye = f"{margin}" if "top" in pos else f"h-text_h-{margin}"
        box_color = ff_color(primary if args.template == "chapter" else bg, 0.9 if args.template == "chapter" else 0.7)
        txt_color = ff_color(bg if args.template == "chapter" else text_c)
        filters.append(f"drawtext=text='{escape_drawtext(args.title)}':{fo}:fontsize={fs}:fontcolor={txt_color}:x={xe}:y={ye}:box=1:boxcolor={box_color}:boxborderw={pady}|{padx}:alpha='{fade_a}':{en}")

    elif args.template == "progress":
        h = max(3, int(base * 0.008))
        fps = meta['video'].get('fps') or 30
        fc.append(f"color=c=0x{primary}:s={W}x{h}:r={fps:g},format=rgba[pb]")
        fc.append(f"[0:v]drawbox=x=0:y=ih-{h}:w=iw:h={h}:color={ff_color(bg, 0.5)}:t=fill:{en}[v1]")
        fc.append(f"[v1][pb]overlay=x='-w+w*min(1,max(0,(t-{s:.3f})/{e - s:.3f}))':y={H - h}:{en}:eof_action=pass[vout]")

    elif args.template == "countdown":
        n = args.count_from
        seg = (e - s) / (n + 1)
        fs = int(base * 0.32)
        for k in range(n, -1, -1):
            ks = s + (n - k) * seg
            ke = ks + seg
            pulse = f"1-0.15*min(1,(t-{ks:.3f})/{seg * 0.5:.3f})"
            filters.append(f"drawtext=text='{k}':{fo}:fontsize={fs}:fontcolor={ff_color(primary)}:borderw={max(2, fs // 40)}:bordercolor={ff_color(bg)}:x=(w-text_w)/2:y=(h-text_h)/2:alpha='{pulse}':enable='between(t,{ks:.3f},{ke:.3f})'")

    output = args.output or default_output(args.input, "gfx")
    cmd = ffmpeg_base() + ["-i", args.input]
    if fc:
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "0:a:0?"]
    else:
        cmd += ["-vf", ",".join(filters), "-map", "0:v:0", "-map", "0:a:0?"]
    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    cmd.append(output)
    run(cmd)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, {args.template})")
    emit(output, template=args.template)
    return 0


if __name__ == "__main__":
    sys.exit(main())
