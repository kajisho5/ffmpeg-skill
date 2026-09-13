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
  sticker       rounded filled chip of --text that pops in at --position (the social sticker)
  hook          full-width opening title card (--title) for --duration seconds with a thin
                progress bar along the top -- the TikTok/Shorts opener
  meme          white upper-case --top / --bottom lines with a heavy black outline

Examples:
  python3 graphics.py talk.mp4 --template lower-third --name "Ada Lovelace" --title "Analyst" --start 2 --end 8
  python3 graphics.py talk.mp4 --template title --title "Episode 12" --subtitle "The math of video" --start 0 --end 4
  python3 graphics.py talk.mp4 --template progress --brand brand.json
  python3 graphics.py intro.mp4 --template countdown --from 5 --start 1 --end 6
  python3 graphics.py talk.mp4 --template lower-third --name "김민준" --title "감독" --lang ko
  python3 graphics.py clip.mp4 --template chapter --title "Part 2 — Setup" --position top-left --start 0 --end 5
  python3 graphics.py reel.mp4 --template sticker --text "NEW" --position top-right --platform tiktok
  python3 graphics.py reel.mp4 --template hook --title "How I cut this in one command" --duration 3
  python3 graphics.py clip.mp4 --template meme --top "when the render" --bottom "finally finishes"
"""
import argparse
import sys
from typing import List, Optional

from _platforms import PLATFORMS, PLATFORM_CHOICES, safe_margins_px, resolve as resolve_platform
from _common import aac_args, add_common, brand_caption_style, script_font_for_text, apply_common, cfr_args, color_hex, default_font_file, default_output, die, emit, escape_drawtext, escape_filter_path, ffmpeg_base, info, load_brand, parse_time, probe, run, run_keeping_subtitles, video_args, drawtext_boxborderw, X264_PRESETS, time_arg, fmt_secs

TEMPLATES = ["lower-third", "title", "chapter", "progress", "countdown", "bug", "sticker", "hook", "meme"]


def ff_color(hex_rgb: str, alpha: float = 1.0) -> str:
    return f"0x{color_hex(hex_rgb)}@{alpha:g}"


def font_opts(brand: dict, font: Optional[str], font_file: Optional[str], script_file: Optional[str] = None) -> str:
    if font_file or brand.get("font_file"):
        return f"fontfile={escape_filter_path(font_file or brand['font_file'])}"
    if script_file:  # a font picked by the script of the text itself (1.12)
        return f"fontfile={escape_filter_path(script_file)}"
    resolved = default_font_file(font or brand.get("font", "DejaVu Sans"))
    if resolved:
        return f"fontfile={escape_filter_path(resolved)}"
    return f"font='{escape_drawtext(font or brand.get('font', 'DejaVu Sans'))}'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_gfx.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    ap.add_argument("--template", choices=TEMPLATES, required=True)
    ap.add_argument("--brand", help="brand.json for colours, font, safe margin")
    ap.add_argument("--name", help="lower-third: name line")
    ap.add_argument("--title", help="title / chapter / bug / hook text, or lower-third second line")
    ap.add_argument("--text", help="sticker: the chip's text")
    ap.add_argument("--top", help="meme: upper line")
    ap.add_argument("--bottom", help="meme: lower line")
    ap.add_argument("--duration", type=float, default=3.0, help="hook: seconds the opening card stays up (default 3)")
    ap.add_argument("--subtitle", help="title: smaller second line")
    ap.add_argument("--from", dest="count_from", type=int, default=5, help="countdown start number (default 5)")
    ap.add_argument("--start", help="show from (default 0)")
    ap.add_argument("--end", help="hide after (default end of clip)")
    ap.add_argument("--position", choices=["top-left", "top-right", "bottom-left", "bottom-right"], default=None, help="corner for chapter/bug/sticker (default bottom-left / top-right / top-right)")
    ap.add_argument("--margin", type=int, default=None, help="distance from the frame edge in px (default: brand safe_margin, or the --platform safe zone)")
    ap.add_argument("--platform", choices=PLATFORM_CHOICES, default=None,
                    help="keep the graphic out of this destination's UI: margins become the platform's safe zone "
                         "(TikTok's description bar and like column, the Reels/Shorts chrome). An explicit --margin wins")
    ap.add_argument("--primary", help="override brand primary colour RRGGBB")
    ap.add_argument("--text-color", help="override text colour RRGGBB")
    ap.add_argument("--font")
    ap.add_argument("--font-file")
    ap.add_argument("--lang", help="language code of the text (e.g. ja, zh, ko): the hint that says whether Han-only "
                                   "text is Chinese, Japanese or Korean when a font is picked by script")
    ap.add_argument("--scale", type=float, default=1.0, help="size multiplier (default 1)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS)
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    args.platform = resolve_platform(args.platform)
    if args.platform and not PLATFORMS[args.platform].get("frame"):
        info(f"--platform {args.platform}: this destination has no frame and no app chrome; margins unchanged")
        args.platform = None
    brand = load_brand(args.brand)
    primary = color_hex(args.primary or brand["colors"]["primary"])
    text_c = color_hex(args.text_color or brand["colors"]["text"])
    bg = color_hex(brand["colors"].get("background", "101418"))
    margin = int(brand.get("safe_margin", 48))
    style = brand_caption_style(brand)  # styles.caption is shared with caption.py
    if args.brand and style.get("font") and not args.font:
        args.font = style["font"]
    if args.brand and style.get("color") and not args.text_color:
        text_c = color_hex(style["color"])
    args.lang = args.lang or (brand.get("lang") if args.brand else None)
    # a font that covers the text before drawtext renders boxes instead of glyphs (1.12)
    _script, script_file, _family = script_font_for_text(
        " ".join(t for t in (args.name, args.title, args.subtitle, args.text, args.top, args.bottom) if t),
        lang=args.lang, font=args.font, font_explicit=bool(args.font), font_file=args.font_file or brand.get("font_file"))
    fo = font_opts(brand, args.font, args.font_file, script_file)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    W, H = meta["video"]["width"], meta["video"]["height"]
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        W, H = H, W
    dur = meta.get("duration") or 0.0
    # Per-edge margins. Without --margin/--platform every edge is the brand safe margin, exactly
    # as before; --margin sets all four; --platform takes each edge from the destination's safe
    # zone (scripts/_platforms.py), which is what keeps a sticker off TikTok's like column.
    m_top = m_bottom = m_left = m_right = margin
    if args.margin is not None:
        if args.margin < 0:
            die(f"--margin must be >= 0, got {args.margin}")
        m_top = m_bottom = m_left = m_right = margin = args.margin
    elif args.platform:
        px = safe_margins_px(args.platform, W, H)
        m_top, m_bottom, m_left, m_right = px["top"], px["bottom"], px["left"], px["right"]
        margin = m_left
        info(f"--platform {args.platform}: safe margins top {m_top} / bottom {m_bottom} / left {m_left} / right {m_right} px")
    fps = meta["video"].get("fps")
    s = time_arg(args.start, "--start", fps) if args.start else 0.0
    e = time_arg(args.end, "--end", fps) if args.end else dur
    if e <= s:
        die("--end must be after --start")
    en = f"enable='between(t,{s:.3f},{e:.3f})'"
    base = min(W, H) * args.scale  # scale everything from the short side
    filters: List[str] = []
    fade_a = f"if(lt(t,{s:.3f}+0.3),(t-{s:.3f})/0.3,if(gt(t,{e:.3f}-0.3),({e:.3f}-t)/0.3,1))"

    extra_inputs: List[str] = []
    fc: List[str] = []  # filter_complex chains (used by templates that need animated boxes)
    if 0 < min(W, H) < 64:  # 0x0 is a dry-run probe of an intermediate that does not exist yet
        die(f"the frame is {W}x{H}; the templates are sized from it and need at least 64 px on the short side")
    if args.template == "lower-third":
        if not args.name:
            die("lower-third needs --name")
        h1 = int(base * 0.055)
        h2 = int(base * 0.038)
        pad = int(base * 0.02)
        bar_h = h1 + (h2 + pad if args.title else 0) + pad * 2
        bar_w = int(base * 0.62)
        y0 = H - m_bottom - bar_h
        # slide in from the left over 0.4 s, slide out over 0.3 s (overlay evaluates x per frame)
        x_expr = f"if(lt(t,{s:.3f}+0.4),-{bar_w}+({bar_w}+{m_left})*((t-{s:.3f})/0.4),if(gt(t,{e:.3f}-0.3),{m_left}-({bar_w}+{m_left})*(1-({e:.3f}-t)/0.3),{m_left}))"
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
        xe = f"{m_left}" if "left" in pos else f"w-text_w-{m_right}"
        ye = f"{m_top}" if "top" in pos else f"h-text_h-{m_bottom}"
        box_color = ff_color(primary if args.template == "chapter" else bg, 0.9 if args.template == "chapter" else 0.7)
        txt_color = ff_color(bg if args.template == "chapter" else text_c)
        filters.append(f"drawtext=text='{escape_drawtext(args.title)}':{fo}:fontsize={fs}:fontcolor={txt_color}:x={xe}:y={ye}:box=1:boxcolor={box_color}:boxborderw={drawtext_boxborderw(pady, padx)}:alpha='{fade_a}':{en}")

    elif args.template == "progress":
        h = max(3, int(base * 0.008))
        fps = meta['video'].get('fps') or 30
        fc.append(f"color=c=0x{primary}:s={W}x{h}:r={fps:g},format=rgba[pb]")
        fc.append(f"[0:v]drawbox=x=0:y=ih-{h}:w=iw:h={h}:color={ff_color(bg, 0.5)}:t=fill:{en}[v1]")
        fc.append(f"[v1][pb]overlay=x='-w+w*min(1,max(0,(t-{s:.3f})/{e - s:.3f}))':y={H - h}:{en}:eof_action=pass[vout]")

    elif args.template == "sticker":
        # A social sticker: a filled chip of text that pops in. drawtext's box gives the chip
        # (its corners are square -- drawtext has no rounded box), and the pop is the two things
        # drawtext *can* animate per frame: alpha and position, so the chip fades up while
        # rising the last few pixels into place over 0.25 s.
        if not args.text:
            die("sticker needs --text")
        pos = args.position or "top-right"
        fs = int(base * 0.05)
        padx, pady = int(fs * 0.7), int(fs * 0.45)
        rise = int(fs * 0.5)
        pop = f"min(1,(t-{s:.3f})/0.25)"
        xe = f"{m_left}" if "left" in pos else f"w-text_w-{m_right}"
        ye = (f"{m_top}+{rise}*(1-{pop})" if "top" in pos else f"h-text_h-{m_bottom}-{rise}*(1-{pop})")
        alpha = f"min({pop},{fade_a})"
        filters.append(f"drawtext=text='{escape_drawtext(args.text)}':{fo}:fontsize={fs}:fontcolor={ff_color(bg)}:"
                       f"x={xe}:y='{ye}':box=1:boxcolor={ff_color(primary, 0.95)}:boxborderw={drawtext_boxborderw(pady, padx)}:"
                       f"alpha='{alpha}':{en}")

    elif args.template == "hook":
        # The opener: a full-width card over the first --duration seconds with a thin bar along
        # the top that empties as the card's time runs out, so the viewer sees how long it lasts.
        if not args.title:
            die("hook needs --title")
        if args.duration <= 0:
            die(f"--duration must be > 0, got {args.duration:g}")
        he = min(e, s + args.duration)
        hen = f"enable='between(t,{s:.3f},{he:.3f})'"
        h1 = int(base * 0.085)
        bar_h = max(3, int(base * 0.01))
        band_h = int(base * 0.30)
        y0 = (H - band_h) // 2
        filters.append(f"drawbox=x=0:y={y0}:w=iw:h={band_h}:color={ff_color(bg, 0.78)}:t=fill:{hen}")
        filters.append(f"drawtext=text='{escape_drawtext(args.title)}':{fo}:fontsize={h1}:fontcolor={ff_color(text_c)}:"
                       f"x=(w-text_w)/2:y=(h-text_h)/2:{hen}")
        filters.append(f"drawbox=x=0:y=0:w='iw*max(0,1-(t-{s:.3f})/{max(0.001, he - s):.3f})':h={bar_h}:"
                       f"color={ff_color(primary)}:t=fill:{hen}")

    elif args.template == "meme":
        # The classic layout: heavy white upper-case lines with a black outline, top and bottom,
        # sized so a short line fills the frame's width without wrapping (drawtext never wraps).
        if not (args.top or args.bottom):
            die("meme needs --top and/or --bottom")
        fs = int(base * 0.09)
        bw = max(2, int(fs / 12))
        white, black = ff_color("FFFFFF"), ff_color("000000")
        for text, y in ((args.top, f"{m_top}"), (args.bottom, f"h-text_h-{m_bottom}")):
            if not text:
                continue
            filters.append(f"drawtext=text='{escape_drawtext(text.upper())}':{fo}:fontsize={fs}:fontcolor={white}:"
                           f"borderw={bw}:bordercolor={black}:x=(w-text_w)/2:y={y}:{en}")

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
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", f"0:a:{args.audio_stream}?"]
    else:
        cmd += ["-vf", ",".join(filters), "-map", "0:v:0", "-map", f"0:a:{args.audio_stream}?"]
    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)
    r = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, {args.template})")
    emit(output, template=args.template, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
