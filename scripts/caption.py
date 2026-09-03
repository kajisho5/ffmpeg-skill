#!/usr/bin/env python3
"""Burn SRT/ASS subtitles into a video, or generate an SRT from plain text.

Styling (font, size, colour, outline, position) applies to SRT input via
libass force_style. ASS files carry their own styles and are rendered as-is.

Text-to-SRT input format (one cue per line, blank lines ignored):
  0:00-0:03 Hello and welcome
  00:00:03.500 --> 00:00:06 Second line | with a manual line break
  Text without a time is auto-timed after the previous cue (--auto-seconds)

Examples:
  python3 caption.py input.mp4 --srt subs.srt
  python3 caption.py input.mp4 --text cues.txt --animate pop --karaoke        # word-by-word highlight, TikTok style
  python3 caption.py input.mp4 --srt subs.srt --font "Noto Sans CJK JP" --size 28 --position top
  python3 caption.py --text cues.txt --write-srt cues.srt          # only produce the SRT
  python3 caption.py input.mp4 --text cues.txt                     # generate + burn in one go
"""
import argparse
import os
import re
import sys
from typing import List, Tuple

from _common import aac_args, cfr_args, default_output, die, escape_filter_path, ffmpeg_base, fmt_srt_time, info, parse_time, probe, run, x264_args

ALIGN = {"bottom": 2, "top": 8, "center": 5, "bottom-left": 1, "bottom-right": 3, "top-left": 7, "top-right": 9}

TIME_RE = re.compile(
    r"^\s*(?P<a>[\d:.,]+)\s*(?:-->|-|–|to)\s*(?P<b>[\d:.,]+)\s+(?P<text>.+)$"
)


def parse_text_cues(path: str, auto_seconds: float, gap: float) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    cursor = 0.0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            m = TIME_RE.match(line)
            if m:
                try:
                    start, end = parse_time(m.group("a")), parse_time(m.group("b"))
                except ValueError:
                    start, end, text = cursor, cursor + auto_seconds, line.strip()
                else:
                    text = m.group("text").strip()
            else:
                start, end, text = cursor, cursor + auto_seconds, line.strip()
            if end <= start:
                die(f"cue '{line}': end must be after start")
            text = text.replace(" | ", "\n").replace("|", "\n")
            cues.append((start, end, text))
            cursor = end + gap
    if not cues:
        die(f"no cues found in {path}")
    return cues


def parse_srt(path: str) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    block: List[str] = []
    with open(path, encoding="utf-8-sig") as fh:
        content = fh.read().replace("\r\n", "\n") + "\n\n"
    for line in content.split("\n"):
        if line.strip():
            block.append(line)
            continue
        if block:
            times = next((b for b in block if "-->" in b), None)
            if times:
                a, b = times.split("-->")
                text = "\n".join(block[block.index(times) + 1:]).strip()
                cues.append((parse_time(a), parse_time(b), text))
            block = []
    if not cues:
        die(f"no cues found in {path}")
    return cues


def write_srt(cues: List[Tuple[float, float, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (s, e, t) in enumerate(cues, 1):
            fh.write(f"{i}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{t}\n\n")


def write_ass(cues: List[Tuple[float, float, str]], path: str, args, play_w: int, play_h: int) -> None:
    """Write a styled ASS file with optional animation and word-by-word highlight."""
    def t(sec: float) -> str:
        cs = int(round(sec * 100))
        h, rem = divmod(cs, 360000)
        m, rem = divmod(rem, 6000)
        s_, cs = divmod(rem, 100)
        return f"{h}:{m:02d}:{s_:02d}.{cs:02d}"

    scale = play_h / 288.0  # our --size is relative to a 288-line script like force_style
    size = int(round(args.size * scale))
    margin = int(round(args.margin * scale))
    # karaoke: PrimaryColour is the "sung" colour, SecondaryColour the "not yet sung" one
    primary = ass_color(args.highlight_color if args.karaoke else args.color)
    secondary = ass_color(args.color)
    outline = ass_color(args.outline_color)
    back = ass_color(args.outline_color, 0x80)
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {play_w}", f"PlayResY: {play_h}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{args.font},{size},{primary},{secondary},{outline},{back},{-1 if args.bold else 0},0,0,0,100,100,0,0,{3 if args.box else 1},{args.outline * scale:.1f},{args.shadow * scale:.1f},{ALIGN[args.position]},{margin},{margin},{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = []
    for start, end, text in cues:
        text = text.replace("\n", "\\N")
        fx = ""
        if args.animate == "fade":
            fx = "{\\fad(200,200)}"
        elif args.animate == "pop":
            fx = "{\\fad(80,120)\\fscx60\\fscy60\\t(0,120,\\fscx110\\fscy110)\\t(120,200,\\fscx100\\fscy100)}"
        elif args.animate == "slide":
            fx = "{\\fad(150,150)\\move(%d,%d,%d,%d,0,250)}" % (play_w // 2, play_h - margin + int(30 * scale), play_w // 2, play_h - margin)
        body = text
        if args.karaoke:
            # split each line into words and give every word an equal share of the cue (\k is in centiseconds)
            dur_cs = max(1, int(round((end - start) * 100)))
            segments = body.split("\\N")
            words = [w for seg in segments for w in seg.split(" ") if w]
            per = max(1, dur_cs // max(1, len(words)))
            out_segments = []
            for seg in segments:
                ws = [w for w in seg.split(" ") if w]
                out_segments.append(" ".join(f"{{\\kf{per}}}{w}" for w in ws))
            body = "\\N".join(out_segments)
        lines.append(f"Dialogue: 0,{t(start)},{t(end)},Default,,0,0,0,,{fx}{body}")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write("\n".join(header + lines) + "\n")


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        die(f"colour must be RRGGBB hex, got '{hex_rgb}'")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="video to burn captions into (omit with --write-srt to only generate)")
    ap.add_argument("-o", "--output", help="output video (default: <name>_captioned.<ext>)")
    src = ap.add_argument_group("subtitle source")
    src.add_argument("--srt", help="SRT file to burn")
    src.add_argument("--ass", help="ASS file to burn (styles inside the file are used)")
    src.add_argument("--text", help="plain text cue file to convert into SRT (see format above)")
    src.add_argument("--write-srt", help="where to save the generated SRT (default: <text>.srt)")
    src.add_argument("--auto-seconds", type=float, default=3.0, help="duration for cues without timing (default 3)")
    src.add_argument("--gap", type=float, default=0.0, help="gap after auto-timed cues in seconds")
    sty = ap.add_argument_group("style (SRT only)")
    sty.add_argument("--font", default="DejaVu Sans", help="font family, e.g. 'Noto Sans CJK JP' for Japanese")
    sty.add_argument("--fonts-dir", help="directory with extra .ttf/.otf files")
    sty.add_argument("--size", type=int, default=24, help="font size in ASS points (relative to a 288p script height, scales automatically)")
    sty.add_argument("--color", default="FFFFFF", help="text colour RRGGBB (default FFFFFF)")
    sty.add_argument("--outline-color", default="000000", help="outline colour RRGGBB")
    sty.add_argument("--outline", type=float, default=2.0, help="outline width (default 2)")
    sty.add_argument("--shadow", type=float, default=0.0, help="shadow depth (default 0)")
    sty.add_argument("--bold", action="store_true")
    sty.add_argument("--position", choices=sorted(ALIGN), default="bottom", help="on-screen placement (default bottom)")
    sty.add_argument("--margin", type=int, default=30, help="vertical margin from the edge (default 30)")
    sty.add_argument("--box", action="store_true", help="draw an opaque box behind text instead of an outline")
    anim = ap.add_argument_group("animation (generates ASS; needs --text or --srt input)")
    anim.add_argument("--animate", choices=["none", "fade", "pop", "slide"], default="none", help="per-cue entrance animation")
    anim.add_argument("--karaoke", action="store_true", help="word-by-word highlight (fills from --color to --highlight-color across each cue)")
    anim.add_argument("--highlight-color", default="FFD200", help="karaoke fill colour RRGGBB (default FFD200)")
    anim.add_argument("--write-ass", help="where to save the generated ASS (default: next to the output)")
    enc = ap.add_argument_group("encoding")
    enc.add_argument("--crf", type=int, default=18)
    enc.add_argument("--preset", default="medium")
    args = ap.parse_args()

    if not (args.srt or args.ass or args.text):
        die("give one of --srt, --ass or --text")

    srt_path = args.srt
    if args.text:
        cues = parse_text_cues(args.text, args.auto_seconds, args.gap)
        srt_path = args.write_srt or os.path.splitext(args.text)[0] + ".srt"
        write_srt(cues, srt_path)
        info(f"wrote {srt_path} ({len(cues)} cues)")
        if not args.input:
            print(srt_path)
            return 0

    if not args.input:
        die("input video is required unless you only use --text/--write-srt")
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")

    output = args.output or default_output(args.input, "captioned")
    if (args.animate != "none" or args.karaoke) and not args.ass:
        cues_for_ass = cues if args.text else parse_srt(srt_path)
        ass_path = args.write_ass or os.path.splitext(output)[0] + ".ass"
        w, h = meta["video"]["width"], meta["video"]["height"]
        if meta["video"].get("rotation") in (90, -90, 270, -270):
            w, h = h, w
        write_ass(cues_for_ass, ass_path, args, w, h)
        info(f"wrote {ass_path} ({len(cues_for_ass)} cues, animate={args.animate}, karaoke={args.karaoke})")
        args.ass = ass_path

    if args.ass:
        if not os.path.exists(args.ass):
            die(f"ASS file not found: {args.ass}")
        vf = f"ass={escape_filter_path(args.ass)}"
        if args.fonts_dir:
            vf += f":fontsdir={escape_filter_path(args.fonts_dir)}"
    else:
        if not srt_path or not os.path.exists(srt_path):
            die(f"SRT file not found: {srt_path}")
        style = [
            f"FontName={args.font}",
            f"FontSize={args.size}",
            f"PrimaryColour={ass_color(args.color)}",
            f"OutlineColour={ass_color(args.outline_color)}",
            f"BackColour={ass_color(args.outline_color, 0x80)}",
            f"BorderStyle={3 if args.box else 1}",
            f"Outline={args.outline:g}",
            f"Shadow={args.shadow:g}",
            f"Bold={-1 if args.bold else 0}",
            f"Alignment={ALIGN[args.position]}",
            f"MarginV={args.margin}",
        ]
        force = ",".join(style).replace("\\", "\\\\").replace("'", "\\'")
        vf = f"subtitles={escape_filter_path(srt_path)}:force_style='{force}'"
        if args.fonts_dir:
            vf += f":fontsdir={escape_filter_path(args.fonts_dir)}"

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf] + x264_args(args.crf, args.preset) + cfr_args(meta)
    cmd += (aac_args() if meta.get("audio") else ["-an"]) + [output]
    run(cmd)
    result = probe(output)
    info(f"wrote {output} ({result.get('duration'):.3f}s)")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
