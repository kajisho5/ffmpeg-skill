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
  python3 caption.py input.mp4 --srt subs.srt --font "Noto Sans CJK JP" --size 28 --position top
  python3 caption.py --text cues.txt --write-srt cues.srt          # only produce the SRT
  python3 caption.py input.mp4 --text cues.txt                     # generate + burn in one go
"""
import argparse
import os
import re
import sys
from typing import List, Tuple

from _common import aac_args, default_output, die, escape_filter_path, ffmpeg_base, fmt_srt_time, info, parse_time, probe, run, x264_args

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


def write_srt(cues: List[Tuple[float, float, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (s, e, t) in enumerate(cues, 1):
            fh.write(f"{i}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{t}\n\n")


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
    probe(args.input)

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

    output = args.output or default_output(args.input, "captioned")
    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf] + x264_args(args.crf, args.preset) + aac_args() + [output]
    run(cmd)
    result = probe(output)
    info(f"wrote {output} ({result.get('duration'):.3f}s)")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
