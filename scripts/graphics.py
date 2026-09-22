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
import os
import re
import sys
from typing import List, Optional

from _platforms import PLATFORMS, PLATFORM_CHOICES, safe_margins_px, resolve as resolve_platform
from _common import (aac_args, add_common, brand_caption_style, script_font_for_text, apply_common, cfr_args,
                     color_hex, default_font_file, default_output, die, emit, escape_drawtext, escape_filter_path,
                     ffmpeg_base, info, load_brand, parse_time, probe, run, run_keeping_subtitles, video_args,
                     drawtext_boxborderw, X264_PRESETS, time_arg, fmt_secs, STATE, drawtext_text_opts,
                     LANGUAGE_NAMES, needs_shaping, detect_script, BIDI_SCRIPTS, font_family_of_file, font_family_for_script, has_emoji,
                     emoji_clusters, emoji_codepoint_name, char_script, emoji_filter_chain, emoji_asset_for, emoji_support, resolve_emoji_assets,
                     EMOJI_ASSET_HINT, text_width_em, drawtext_shaping, wrap_text, WRAP_MODES,
                     SAFE_WIDTH_FRACTION)
from _ass_overlay import text_overlay_ass, EMOJI_SENTINEL

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
    ap.add_argument("--wrap", choices=list(WRAP_MODES), default="phrase",
                    help="how a label too wide for the frame is broken into lines: 'phrase' (default, 1.16) never "
                         "breaks inside a word or a hyphen's wrong side, never leaves a lone digit, kana or "
                         "punctuation on its own line, prefers Japanese sentence ends and particles, and never ends "
                         "a line on an article or preposition; 'measured' is 1.15's width-only wrap. A label that "
                         "already fits one line is untouched either way")
    ap.add_argument("--text-render", choices=["auto", "ass", "drawtext"], default="auto",
                    help="which renderer draws the template's text: 'auto' (default) uses libass for "
                         "scripts drawtext cannot shape (Devanagari, Bengali, Tamil, Thai, Lao ...) and for "
                         "emoji overlays, and drawtext for everything else -- Latin/CJK/Arabic frames are "
                         "pixel-identical to 1.14 (the drawtext command itself changed: the label is "
                         "passed as textfile=, not text=); 'ass' always uses libass; 'drawtext' forces the old renderer and is "
                         "refused for a script it cannot shape")
    ap.add_argument("--write-ass", metavar="PATH",
                    help="where to save the generated ASS when the libass route is used (default: <output stem>_gfx.ass)")
    emo = ap.add_argument_group("emoji (1.15)")
    emo.add_argument("--emoji", choices=["auto", "color", "png", "mono", "none"], default="auto",
                     help="how emoji in the template text are drawn (see caption.py --emoji)")
    emo.add_argument("--emoji-assets", metavar="DIR",
                     help="directory of emoji PNGs named by code point (1f389.png); nothing is ever downloaded")
    emo.add_argument("--emoji-scale", type=float, default=1.0,
                     help="emoji box as a multiple of the line's font size (default 1.0)")
    emo.add_argument("--emoji-max", type=int, default=60, help="most emoji overlays one run may build (default 60)")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
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

    # --- which renderer draws the text (1.15) --------------------------------------------------
    # drawtext does bidi and Arabic joining on a fribidi build, but it never reorders or
    # re-clusters (no harfbuzz), so Indic matras and Thai/Lao mark stacking come out wrong on
    # every build. Those scripts -- and any run that has to reserve a gap for an emoji PNG -- go
    # through libass instead; everything else keeps the exact drawtext graph 1.14 produced.
    all_text = " ".join(t for t in (args.name, args.title, args.subtitle, args.text, args.top, args.bottom) if t)
    shaping = needs_shaping(_script)
    emoji_assets = resolve_emoji_assets(args.emoji_assets, None, brand if args.brand else None)
    emoji_mode = None
    emoji_overlays: List[dict] = []
    if has_emoji(all_text):
        support = emoji_support(emoji_assets, probe=True)
        emoji_mode = support["mode"] if args.emoji == "auto" else args.emoji
        if args.emoji == "color" and not support["libass_color"]:
            die("--emoji color: this ffmpeg renders emoji monochrome through libass "
                f"({support['detail']}) -- pass --emoji-assets DIR for colour, or --emoji mono", kind="input")
        if args.emoji == "png" and not emoji_assets:
            die("--emoji png: no emoji assets directory resolved -- " + EMOJI_ASSET_HINT, kind="input")
    if args.text_render == "drawtext" and shaping:
        die(f"{LANGUAGE_NAMES.get(_script, _script)} text cannot be shaped by drawtext on any ffmpeg "
            "build (the marks are reordered by harfbuzz, which drawtext does not use): drop "
            "--text-render drawtext to render it through libass, or draw it with caption.py",
            kind="input")
    route = "ass" if (args.text_render == "ass" or
                      (args.text_render == "auto" and (shaping or emoji_mode == "png"))) else "drawtext"
    # drawtext loads exactly ONE font file and has no fallback chain, so "whatever glyph the text
    # font has" for an emoji is an empty box on DejaVu Sans and on every script font: reporting
    # mode "mono" from the drawtext route is a claim the frame does not keep. libass DOES have a
    # fallback chain, so an auto run routes there instead; a run that pinned --text-render
    # drawtext degrades to "none" (strip) and says so rather than drawing tofu.
    if emoji_mode == "mono" and route == "drawtext":
        if args.text_render == "auto":
            route = "ass"
        else:
            emoji_mode = "none"
            info("emoji: --text-render drawtext has no font fallback chain, so the cluster would "
                 "be drawn as an empty box -- stripped from the text instead "
                 "(--text-render auto renders it monochrome through libass)")
    if emoji_mode == "mono":
        info("warning: emoji rendered monochrome (no colour path on this ffmpeg; "
             "--emoji-assets DIR for colour). " + support["detail"])
    if emoji_mode == "none":
        if not "".join(ch for ch in all_text if char_script(ch) != "emoji").strip():
            die("the template's text is nothing but emoji and this machine can draw none of them "
                "(no glyph, no --emoji-assets DIR): that frame would be blank, which is not a "
                "delivery -- " + EMOJI_ASSET_HINT, kind="input")

        def _strip_emoji(text):
            if not text:
                return text
            for _i, cl in emoji_clusters(text):
                text = text.replace(cl, "")
            return re.sub(r"[ \t]{2,}", " ", text).strip()

        for _attr in ("name", "title", "subtitle", "text", "top", "bottom"):
            setattr(args, _attr, _strip_emoji(getattr(args, _attr, None)))
        all_text = " ".join(t for t in (args.name, args.title, args.subtitle, args.text,
                                        args.top, args.bottom) if t)
        info("emoji: stripped from the drawn text (--emoji none)")
    elements: List[dict] = []

    def ass_font_family() -> "Optional[str]":
        explicit = args.font_file or brand.get("font_file")
        if explicit:
            return font_family_of_file(explicit) or args.font or brand.get("font")
        if script_file:
            return font_family_of_file(script_file) or font_family_for_script(_script)
        return args.font or brand.get("font", "DejaVu Sans")

    def ass_fonts_dir() -> "Optional[str]":
        explicit = args.font_file or brand.get("font_file")
        if explicit:
            return os.path.dirname(os.path.abspath(explicit))
        if script_file:
            return os.path.dirname(os.path.abspath(script_file))
        return None

    def chip_frac(left, right, pad):
        """The fraction of the frame a boxed label may use: the span between the margins, less
        drawtext's own box padding on each side."""
        usable = W - left - right - 2 * pad
        return max(0.1, min(SAFE_WIDTH_FRACTION, usable / float(W))) if W else SAFE_WIDTH_FRACTION

    sliced_atoms: List[int] = []

    def wrapped(text, size_px, frac=SAFE_WIDTH_FRACTION):
        """A label broken to the frame's safe width (1.16).

        drawtext and libass both render a literal newline as a line break, and every template
        below already passes its label through one of them -- so wrapping is a matter of putting
        the breaks in, at the same measured width and by the same four phrase rules caption.py
        uses. A label that already fits comes back unchanged, which is why this is additive: the
        only text it touches is text that used to run off the edge of the frame.

        `slice_overlong=True` matches caption.py's burn path (1.18.4): a single atom that is
        still wider than the column even alone -- a long hashtag/URL/name with no break point --
        is hard-sliced at the column's edge (preferring an existing hyphen) rather than left to
        render past the frame. An atom that already fits is never touched, so a fitting Thai
        phrase or katakana run comes through exactly as before.
        """
        text = str(text or "")
        if not text or not size_px:
            return text
        max_em = (W * frac) / float(size_px)
        if max_em <= 0:
            return text
        out = []
        for para in text.split("\n"):
            out.extend(wrap_text(para, max_em, mode=args.wrap, lang=args.lang,
                                  slice_overlong=True, sliced=sliced_atoms) if para.strip() else [para])
        return "\n".join(out)

    def add_text(text, drawtext, *, target=None, **el):
        """One line of template text: a drawtext filter on the old route, an ASS element on the
        new one. The geometry is computed identically either way."""
        if route != "ass":
            (filters if target is None else target).append(drawtext)
            return
        el["text"] = text
        elements.append(el)

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
        tx_pad = int(base * 0.035)
        tx = f"({x_expr})+{tx_pad}"
        x_rest, x_off = m_left + tx_pad, -bar_w + tx_pad
        draws = []
        for text, fs, colour, ty in ((args.name, h1, text_c, y0 + pad),
                                     (args.title, h2, primary, y0 + pad + h1 + pad // 2)):
            if not text:
                continue
            draws.append(f"drawtext={drawtext_text_opts(text)}:{fo}:fontsize={fs}:"
                         f"fontcolor={ff_color(colour)}:x='{tx}':y={ty}:{en}")
            if route == "ass":
                # the same three phases the bar itself slides through, as \move Dialogues
                elements.append(dict(text=text, size=fs, color=colour, font=ass_font_family(),
                                     align=7, x=x_rest, y=ty, outline=max(1.0, fs / 16.0),
                                     outline_color="000000", start=s, end=min(e, s + 0.4),
                                     move=(x_off, ty, x_rest, ty, 0, 400), x_expr=tx))
                elements.append(dict(text=text, size=fs, color=colour, font=ass_font_family(),
                                     align=7, x=x_rest, y=ty, outline=max(1.0, fs / 16.0),
                                     outline_color="000000", start=min(e, s + 0.4), end=max(s, e - 0.3),
                                     x_expr=tx))
                elements.append(dict(text=text, size=fs, color=colour, font=ass_font_family(),
                                     align=7, x=x_rest, y=ty, outline=max(1.0, fs / 16.0),
                                     outline_color="000000", start=max(s, e - 0.3), end=e,
                                     move=(x_rest, ty, x_off, ty, 0, 300), x_expr=tx))
        fc.append(f"[v2]{','.join(draws)}[vout]" if route != "ass" else "[v2]null[vout]")

    elif args.template == "title":
        if not args.title:
            die("title needs --title")
        h1 = int(base * 0.11)
        h2 = int(base * 0.045)
        filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={ff_color(bg, 0.55)}:t=fill:{en}")
        add_text(args.title,
                 f"drawtext={drawtext_text_opts(args.title)}:{fo}:fontsize={h1}:fontcolor={ff_color(text_c)}:x=(w-text_w)/2:y=(h-text_h)/2-{h2 if args.subtitle else 0}:alpha='{fade_a}':{en}",
                 size=h1, color=text_c, font=ass_font_family(), align=5, x=W / 2,
                 y=H / 2 - (h2 if args.subtitle else 0), outline=max(1.0, h1 / 20.0),
                 outline_color="000000", start=s, end=e, fade=(300, 300))
        filters.append(f"drawbox=x=(iw-{int(base * 0.12)})/2:y=(ih)/2+{h1 // 2 + (0 if args.subtitle else 0)}:w={int(base * 0.12)}:h={max(2, int(base * 0.006))}:color={ff_color(primary)}:t=fill:{en}")
        if args.subtitle:
            add_text(args.subtitle,
                     f"drawtext={drawtext_text_opts(args.subtitle)}:{fo}:fontsize={h2}:fontcolor={ff_color(primary)}:x=(w-text_w)/2:y=(h-text_h)/2+{h1 // 2 + int(base * 0.03)}:alpha='{fade_a}':{en}",
                     size=h2, color=primary, font=ass_font_family(), align=5, x=W / 2,
                     y=H / 2 + h1 // 2 + int(base * 0.03), outline=max(1.0, h2 / 20.0),
                     outline_color="000000", start=s, end=e, fade=(300, 300))

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
        box_hex = primary if args.template == "chapter" else bg
        txt_hex = bg if args.template == "chapter" else text_c
        align = (7 if "left" in pos else 9) if "top" in pos else (1 if "left" in pos else 3)
        add_text(args.title,
                 f"drawtext={drawtext_text_opts(args.title)}:{fo}:fontsize={fs}:fontcolor={txt_color}:x={xe}:y={ye}:box=1:boxcolor={box_color}:boxborderw={drawtext_boxborderw(pady, padx)}:alpha='{fade_a}':{en}",
                 size=fs, color=txt_hex, font=ass_font_family(), align=align,
                 x=(m_left if "left" in pos else W - m_right),
                 y=(m_top if "top" in pos else H - m_bottom),
                 box=True, box_color=box_hex, box_alpha=(0x19 if args.template == "chapter" else 0x4C),
                 outline=float(pady), outline_color=box_hex, start=s, end=e, fade=(300, 300))

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
        align = (7 if "left" in pos else 9) if "top" in pos else (1 if "left" in pos else 3)
        y_rest = m_top if "top" in pos else H - m_bottom
        y_start = y_rest + rise if "top" in pos else y_rest + rise
        # the chip is a box between the two side margins, not the whole frame: wrapping to the
        # frame width let a long --text run off the plate even though it "fitted"
        sticker_text = wrapped(args.text, fs, chip_frac(m_left, m_right, padx))
        add_text(sticker_text,
                 f"drawtext={drawtext_text_opts(sticker_text)}:{fo}:fontsize={fs}:fontcolor={ff_color(bg)}:"
                 f"x={xe}:y='{ye}':box=1:boxcolor={ff_color(primary, 0.95)}:boxborderw={drawtext_boxborderw(pady, padx)}:"
                 f"alpha='{alpha}':{en}",
                 size=fs, color=bg, font=ass_font_family(), align=align,
                 x=(m_left if "left" in pos else W - m_right), y=y_rest,
                 box=True, box_color=primary, box_alpha=0x0D, outline=float(pady),
                 outline_color=primary, start=s, end=e, fade=(250, 250),
                 move=(m_left if "left" in pos else W - m_right, y_start,
                       m_left if "left" in pos else W - m_right, y_rest, 0, 250))

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
        hook_title = wrapped(args.title, h1)
        add_text(hook_title,
                 f"drawtext={drawtext_text_opts(hook_title)}:{fo}:fontsize={h1}:fontcolor={ff_color(text_c)}:"
                 f"x=(w-text_w)/2:y=(h-text_h)/2:{hen}",
                 size=h1, color=text_c, font=ass_font_family(), align=5, x=W / 2, y=H / 2,
                 outline=max(1.0, h1 / 20.0), outline_color="000000", start=s, end=he)
        filters.append(f"drawbox=x=0:y=0:w='iw*max(0,1-(t-{s:.3f})/{max(0.001, he - s):.3f})':h={bar_h}:"
                       f"color={ff_color(primary)}:t=fill:{hen}")

    elif args.template == "meme":
        # The classic layout: heavy white upper-case lines with a black outline, top and bottom,
        # sized so a short line fills the frame's width; a longer one is broken by the same
        # phrase-aware wrap caption.py uses (1.16 -- drawtext itself still never wraps).
        if not (args.top or args.bottom):
            die("meme needs --top and/or --bottom")
        fs = int(base * 0.09)
        bw = max(2, int(fs / 12))
        white, black = ff_color("FFFFFF"), ff_color("000000")
        for text, y in ((args.top, f"{m_top}"), (args.bottom, f"h-text_h-{m_bottom}")):
            if not text:
                continue
            meme_line = wrapped(text.upper(), fs)
            add_text(meme_line,
                     f"drawtext={drawtext_text_opts(meme_line)}:{fo}:fontsize={fs}:fontcolor={white}:"
                     f"borderw={bw}:bordercolor={black}:x=(w-text_w)/2:y={y}:{en}",
                     size=fs, color="FFFFFF", font=ass_font_family(), bold=True,
                     align=(8 if y == f"{m_top}" else 2), x=W / 2,
                     y=(m_top if y == f"{m_top}" else H - m_bottom),
                     outline=float(bw), outline_color="000000", start=s, end=e)

    elif args.template == "countdown":
        n = args.count_from
        seg = (e - s) / (n + 1)
        fs = int(base * 0.32)
        for k in range(n, -1, -1):
            ks = s + (n - k) * seg
            ke = ks + seg
            pulse = f"1-0.15*min(1,(t-{ks:.3f})/{seg * 0.5:.3f})"
            add_text(str(k),
                     f"drawtext=text='{k}':{fo}:fontsize={fs}:fontcolor={ff_color(primary)}:borderw={max(2, fs // 40)}:bordercolor={ff_color(bg)}:x=(w-text_w)/2:y=(h-text_h)/2:alpha='{pulse}':enable='between(t,{ks:.3f},{ke:.3f})'",
                     size=fs, color=primary, font=ass_font_family(), align=5, x=W / 2, y=H / 2,
                     outline=float(max(2, fs // 40)), outline_color=bg, start=ks, end=ke,
                     scale_t=(0, seg * 500, 115))

    output = args.output or default_output(args.input, "gfx")
    ass_path = None
    emoji_result = None
    if route == "ass":
        scale_em = float(args.emoji_scale or 1.0)
        missing: List[str] = []
        seen: List[str] = []
        for el in elements:
            el["box_px"] = int(round(el["size"] * scale_em))
            line = el["text"]
            clusters = emoji_clusters(line)
            if not clusters or emoji_mode not in ("png",):
                continue
            line_w = text_width_em(line, scale_em) * el["size"]
            align = int(el.get("align", 7))
            left = el["x"] if align in (7, 4, 1) else (
                el["x"] - line_w / 2.0 if align in (8, 5, 2) else el["x"] - line_w)
            line_h = el["size"] * 1.2
            y_top = el["y"] if align in (7, 8, 9) else (
                el["y"] - line_h / 2.0 if align in (4, 5, 6) else el["y"] - line_h)
            # An RTL line is rendered right-to-left: measure the suffix, not the logical prefix.
            rtl = detect_script(line) in BIDI_SCRIPTS
            rebuilt, cursor = "", 0
            for idx, cluster in clusters:
                name = emoji_codepoint_name(cluster)
                if name not in seen:
                    seen.append(name)
                asset = emoji_asset_for(cluster, emoji_assets)
                if not asset:
                    if name not in missing:
                        missing.append(name)
                    rebuilt += line[cursor:idx + len(cluster)]
                    cursor = idx + len(cluster)
                    continue
                if rtl:
                    prefix_px = line_w - text_width_em(line[:idx] + cluster, scale_em) * el["size"]
                else:
                    prefix_px = text_width_em(line[:idx], scale_em) * el["size"]
                if el.get("x_expr"):
                    # the lower-third slides: the emoji rides the same expression the bar does
                    x = f"({el['x_expr']})+{prefix_px:.0f}"
                else:
                    x = int(round(max(0.0, min(left + prefix_px, W - el["box_px"]))))
                emoji_overlays.append({"asset": asset, "cluster": name, "x": x,
                                       "y": int(round(max(0.0, min(y_top + (line_h - el["box_px"]) / 2.0,
                                                                   H - el["box_px"])))),
                                       "start": round(el["start"], 3), "end": round(el["end"], 3),
                                       "box": el["box_px"],
                                       # every template fades its text in and out over 0.3 s
                                       # (fade_a above); the PNG rides the same envelope.
                                       "fade_in": round(min(0.3, max(0.0, (el["end"] - el["start"]) / 2.0)), 3),
                                       "fade_out": round(min(0.3, max(0.0, (el["end"] - el["start"]) / 2.0)), 3)})
                rebuilt += line[cursor:idx] + EMOJI_SENTINEL
                cursor = idx + len(cluster)
            el["text"] = rebuilt + line[cursor:]
        # `or 60` would swallow --emoji-max 0, the one value meaning "none at all".
        _max = 60 if args.emoji_max is None else int(args.emoji_max)
        if len(emoji_overlays) > _max:
            die(f"{len(emoji_overlays)} emoji overlays would be built for this job "
                f"(limit {_max}, --emoji-max raises it); ffmpeg's filter graph and the "
                "per-frame cost both grow linearly -- split the job, or use --emoji none", kind="input")
        if missing:
            info("warning: no PNG in the assets directory for " + ", ".join(missing))
        if emoji_mode:
            emoji_result = {"mode": emoji_mode, "count": len(emoji_clusters(all_text)),
                            "clusters": sorted(seen) or sorted({emoji_codepoint_name(cl) for _i, cl in emoji_clusters(all_text)}),
                            "assets": emoji_assets, "missing": missing,
                            "overlays": len(emoji_overlays)}
        ass_path = args.write_ass or os.path.splitext(output)[0] + "_gfx.ass"
        if STATE.dry_run:
            info(f"[dry-run] would write {ass_path} ({len(elements)} text elements)")
        else:
            text_overlay_ass(elements, play_w=W, play_h=H, path=ass_path, fonts_dir=ass_fonts_dir())
            info(f"wrote {ass_path} ({len(elements)} text elements, rendered through libass)")
    elif emoji_mode:
        emoji_result = {"mode": emoji_mode, "count": len(emoji_clusters(all_text)),
                        "clusters": sorted({emoji_codepoint_name(cl) for _i, cl in emoji_clusters(all_text)}),
                        "assets": emoji_assets, "missing": [], "overlays": 0}

    cmd = ffmpeg_base() + ["-i", args.input]
    if route == "ass" or emoji_overlays:
        chains = list(fc) if fc else [f"[0:v]{','.join(filters) if filters else 'null'}[vout]"]
        last = "vout"
        if route == "ass":
            vf = f"ass={escape_filter_path(ass_path)}"
            fdir = ass_fonts_dir()
            if fdir:
                vf += f":fontsdir={escape_filter_path(fdir)}"
            chains.append(f"[{last}]{vf}[vtxt]")
            last = "vtxt"
        eo, emoji_inputs = emoji_filter_chain({"overlays": emoji_overlays}, last, "vfinal", first_input=1)
        for spec in emoji_inputs:
            cmd += spec
            asset = spec[-1]
            if asset not in STATE.plan_inputs:
                STATE.plan_inputs.append(asset)
        if eo:
            chains += eo
            last = "vfinal"
        cmd += ["-filter_complex", ";".join(chains), "-map", f"[{last}]",
                "-map", f"0:a:{args.audio_stream}?"]
    elif fc:
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", f"0:a:{args.audio_stream}?"]
    else:
        cmd += ["-vf", ",".join(filters), "-map", "0:v:0", "-map", f"0:a:{args.audio_stream}?"]
    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)
    r = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, {args.template})")
    extra = {"template": args.template, "dropped_non_av_streams": dropped_streams,
             "text_renderer": route, "script": _script}
    if ass_path:
        extra["ass"] = ass_path
    if emoji_result:
        extra["emoji"] = emoji_result
    if sliced_atoms:
        extra["broken_inside_word"] = len(sliced_atoms)
    emit(output, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
