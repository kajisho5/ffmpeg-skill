#!/usr/bin/env python3
"""Composite a logo/image or a text title onto a video with position, timing,
opacity and fade in/out.

Positions: top-left, top, top-right, left, center, right, bottom-left, bottom,
bottom-right, or explicit "X,Y" pixels (negative counts from the far edge).

--video composites a second VIDEO as a picture-in-picture layer (position,
scale, opacity, time-range -- same knobs as --image), instead of a still
image or text. --place SRC_START-SRC_END@AT (repeatable, with --video) shows only
that range of the layer, starting at AT on the main timeline: one pass lays
several pieces of a layer (say, graphics rendered back to back) at their own
times, and the main picture shows untouched everywhere else. Only the main input's audio is kept; the PiP layer's own
audio track, if any, is dropped -- mixing two audio tracks is a job for
audio.py, not this tool. --chromakey COLOR (with --video) turns that colour
transparent first (green-screen removal) before compositing.

Examples:
  python3 overlay.py input.mp4 --image logo.png --position top-right --scale 200 --opacity 0.8
  python3 overlay.py input.mp4 --image lower_third.png --position bottom-left --start 2 --end 8 --fade 0.5
  python3 overlay.py input.mp4 --text "Episode 12" --position bottom --font-size 48 --start 1 --end 5 --fade 0.3
  python3 overlay.py input.mp4 --text "こんにちは" --font-file /path/NotoSansCJK-Bold.ttc --box
  python3 overlay.py input.mp4 --video webcam.mp4 --position bottom-right --scale 480 --opacity 0.9
  python3 overlay.py bg.mp4 --video greenscreen.mp4 --chromakey 0x00ff00 --chromakey-similarity 0.15
  python3 overlay.py talk.mp4 --video cues.mov --position 0,0 --margin 0 --place 0-2.5@12 --place 2.5-6@40
"""
import argparse
import re
import sys
from typing import List, Optional

from _platforms import PLATFORMS, PLATFORM_CHOICES, safe_margins_px, resolve as resolve_platform
from _common import STATE, script_font_for_text, drawtext_clean, drawtext_line_metrics, drawtext_text_opts, drawtext_draws_newline_glyph, is_multiline, needs_shaping, LANGUAGE_NAMES, has_emoji, detect_script, emoji_clusters, load_brand, drawn_chain, label_chain, matrix_chain, rgb_chain_to_bt709, video_args, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_drawtext, ffmpeg_base, info, parse_time, probe, run, run_keeping_subtitles, validate_color, x264_args, X264_PRESETS, time_arg, fmt_secs
from _common.emit import warn
from _common.fonts import font_choice, record_font_choice
from _common import drawtext_fontfile  # noqa: E402

# Per-edge margins: a platform's UI does not cover the same fraction of every edge (TikTok's
# like column is 14 % of the width, its description block 22 % of the height), so a position
# names the edges it is measured from rather than one --margin for all four.
POS = {
    "top-left": ("{left}", "{top}"),
    "top": ("(W-w)/2", "{top}"),
    "top-right": ("W-w-{right}", "{top}"),
    "left": ("{left}", "(H-h)/2"),
    "center": ("(W-w)/2", "(H-h)/2"),
    "right": ("W-w-{right}", "(H-h)/2"),
    "bottom-left": ("{left}", "H-h-{bottom}"),
    "bottom": ("(W-w)/2", "H-h-{bottom}"),
    "bottom-right": ("W-w-{right}", "H-h-{bottom}"),
}


def position_exprs(pos: str, margin: int, text_mode: bool, margins: Optional[dict] = None):
    edges = margins or {}
    m = {edge: int(edges.get(edge, margin)) for edge in ("top", "bottom", "left", "right")}
    if pos in POS:
        x, y = (e.format(**m) for e in POS[pos])
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


def _num(v: float) -> str:
    """A measured pixel value as an expression literal (no exponent form)."""
    return f"{v:.6f}".rstrip("0").rstrip(".")


def per_line_drawtext(lines: List[str], x: str, y: str, font_opt: str, args: argparse.Namespace,
                      box: List[str], timing: List[str]) -> str:
    """The drawtext chain for a multi-line --text on a release whose drawtext draws a box at each
    line break (drawtext_draws_newline_glyph): one drawtext per line, each line alone, placed
    where one multi-line drawtext puts it on a fixed release.

    That block's layout is drawtext's own (measure_text/draw_text): text_w is the widest line,
    text_h = lh*(lines-1) + the first line's top_a + the last line's bottom_d, the lines are
    left-aligned at x, and line i's baseline is y + top_a + i*lh. Each line is measured alone
    (drawtext_line_metrics), so the box the bug adds is in no number; x and y keep the caller's
    position expressions with text_w/text_h replaced by the block's values, and each line is
    drawn with y_align=baseline at its own baseline. The outlines of every line are drawn before
    any line's text, as one drawtext draws them, so a descender's outline never covers the next
    line's glyphs; the --box is drawn once, by the first line, at the block's size (boxw/boxh).
    Bit-identical to one multi-line drawtext on 8.1.3 for every named position, with and without
    --box; a font whose glyph boxes are not whole pixels (no hinting) can sit one row lower, since
    drawtext reports top_a rounded up."""
    m = drawtext_line_metrics(lines, font_opt, args.font_size)
    seen = [d for d in m if d]
    lh = seen[0]["lh"]
    width = max(d["w"] for d in seen)
    # an empty first/last line has no glyphs: drawtext's -32000/64 start values, as it measures them
    top = m[0]["top"] if m[0] else -500.0
    bottom = m[-1]["bottom"] if m[-1] else -500.0
    height = lh * (len(lines) - 1) + top + bottom

    def block(expr: str) -> str:
        return re.sub(r"\btext_h\b", _num(height), re.sub(r"\btext_w\b", _num(width), expr))

    bx, by = block(x), block(y)
    passes = ([[f"borderw={args.border}", f"bordercolor={args.border_color}", "fontcolor=black@0"],
               ["fontcolor=" + args.font_color]] if args.border else [["fontcolor=" + args.font_color]])
    filters = []
    for n, paint in enumerate(passes):
        for i, line in enumerate(lines):
            if not line:
                continue
            opts = [drawtext_text_opts(line), f"fontsize={args.font_size}", f"x={bx}", f"y={by}+{_num(top + i * lh)}",
                    "y_align=baseline", font_opt] + paint + timing[:1]
            if box and n == 0 and not filters:
                opts += box + [f"boxw={_num(width)}", f"boxh={_num(height)}"]
            filters.append("drawtext=" + ":".join(opts + timing[1:]))
    return ",".join(filters)


# one time inside --place: seconds, mm:ss, hh:mm:ss.ms or hh:mm:ss:ff with an optional @fps
# suffix (the time grammar's own); times are never negative, so '-' only separates the range
_PLACE_TIME = r"[^@\-]+(?:@[0-9.]+)?"


def parse_placements(specs: List[str], main_fps: Optional[float], layer_fps: Optional[float]) -> List[tuple]:
    """--place SRC_START-SRC_END@AT -> [(src_start, src_end, at)], refusing empty, negative or
    overlapping placements (two pieces on screen at once would stack in an order nobody asked for).
    SRC_START/SRC_END are positions in the layer, so an hh:mm:ss:ff timecode there counts the
    layer's frames; AT is a position on the main timeline and counts the main video's."""
    out = []
    for spec in specs:
        m = re.fullmatch(rf"\s*({_PLACE_TIME})-({_PLACE_TIME})@({_PLACE_TIME})\s*", spec)
        if not m:
            die(f"--place {spec!r}: use SRC_START-SRC_END@AT, e.g. 0-2.5@12 (times are not negative)")
        a = time_arg(m.group(1), "--place", layer_fps)
        b = time_arg(m.group(2), "--place", layer_fps)
        at = time_arg(m.group(3), "--place", main_fps)
        if b <= a:
            die(f"--place {spec!r}: the layer range ends before it starts")
        out.append((a, b, at))
    spans = sorted((at, at + (b - a)) for a, b, at in out)
    for (s1, e1), (s2, _e2) in zip(spans, spans[1:]):
        if s2 < e1 - 1e-6:
            die(f"--place: pieces overlap on the main timeline ({s1:g}-{e1:g} s and from {s2:g} s)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_overlay.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--image", help="PNG/JPG (alpha respected) to composite")
    src.add_argument("--text", help="text to draw (drawtext)")
    src.add_argument("--logo", action="store_true", help="composite the brand logo from --brand (position/scale/opacity from brand.json)")
    src.add_argument("--video", help="a second video to composite as a picture-in-picture layer")
    ap.add_argument("--place", action="append", default=[], metavar="SRC_START-SRC_END@AT",
                    help="with --video, repeatable: show this range of the layer starting at AT on the main "
                         "timeline (e.g. 0-2.5@12); the layer is hidden outside its placed ranges. Times in "
                         "seconds or HH:MM:SS. Not with --start/--end/--fade")
    ck = ap.add_argument_group("chroma key (with --video)")
    ck.add_argument("--chromakey", help="colour to key out (green-screen removal), e.g. 0x00ff00 or green")
    ck.add_argument("--chromakey-similarity", type=float, default=0.15, help="how close a pixel must be to --chromakey to become transparent, 0..1 (default 0.15)")
    ck.add_argument("--chromakey-blend", type=float, default=0.05, help="soften the key edge, 0..1 (default 0.05)")
    ap.add_argument("--brand", help="brand.json (logo, font, colours, safe margin)")
    ap.add_argument("--position", default="top-right", help="named position or X,Y (default top-right)")
    ap.add_argument("--margin", type=int, default=24, help="margin from the edges in px (default 24)")
    ap.add_argument("--platform", choices=PLATFORM_CHOICES, default=None,
                    help="keep the overlay out of this destination's UI: each edge's margin becomes that "
                         "platform's safe zone (scripts/_platforms.py), so a top-left logo clears TikTok's "
                         "status bar and a right-hand one clears the like column. An explicit --margin wins")
    ap.add_argument("--start", help="show from this time (default: whole video)")
    ap.add_argument("--end", help="hide after this time")
    ap.add_argument("--fade", type=float, default=0.0, help="fade-in duration in seconds (at --start or 0); the fade-out happens only at --end")
    ap.add_argument("--opacity", type=float, default=1.0, help="0..1 (default 1)")
    img = ap.add_argument_group("image options")
    img.add_argument("--scale", type=int, help="width in px for an image, logo or video layer (keeps aspect); text size is --font-size")
    img.add_argument("--scale-percent", type=float,
                     help="width as a %% of the displayed frame for an image, logo or video layer (keeps aspect); "
                          "a 90 or 270 degree rotation uses the stored height; text size is --font-size")
    txt = ap.add_argument_group("text options")
    txt.add_argument("--font", default="DejaVu Sans", help="fontconfig font name")
    txt.add_argument("--font-file", help="explicit .ttf/.otf/.ttc path (use this for CJK fonts)")
    txt.add_argument("--font-size", type=int, default=42)
    txt.add_argument("--font-color", default="white")
    txt.add_argument("--border", type=int, default=2, help="text outline width (default 2)")
    txt.add_argument("--border-color", default="black")
    txt.add_argument("--box", action="store_true", help="draw a translucent box behind the text")
    emo = ap.add_argument_group("emoji (1.15)")
    emo.add_argument("--emoji", choices=["auto", "color", "png", "mono", "none"], default="auto",
                     help="how emoji in --text are drawn. overlay.py draws through drawtext, which cannot load "
                          "a colour emoji font at all, so only 'mono'/'none' render here -- 'png'/'color' name "
                          "caption.py/graphics.py instead")
    emo.add_argument("--emoji-assets", metavar="DIR", help="directory of emoji PNGs named by code point "
                                                           "(used by caption.py/graphics.py; overlay.py has no PNG route)")
    emo.add_argument("--emoji-scale", type=float, default=1.0, help="emoji box as a multiple of the font size")
    emo.add_argument("--emoji-max", type=int, default=60, help="most emoji overlays one run may build")
    txt.add_argument("--box-color", default="black@0.5")
    enc = ap.add_argument_group("encoding")
    enc.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    enc.add_argument("--preset", default="medium", choices=X264_PRESETS)
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
    if args.text is not None and not args.text.strip():
        die("--text is blank -- give the words to draw", kind="input")
    if not (args.image or args.text or args.video):
        die("give --image, --text, --logo or --video")
    # --scale is a layer width. On a text draw it used to be accepted and ignored (fontsize stayed
    # at --font-size), so a project that asked for 200 px text completed with the 42 px default.
    if args.text and not (args.image or args.video) and (args.scale is not None or args.scale_percent is not None):
        die("--scale and --scale-percent size an image, logo or video layer; text size is --font-size", kind="input")
    if args.brand:
        if args.margin == ap.get_default("margin"):
            args.margin = int(brand.get("safe_margin", args.margin))
        if args.font == ap.get_default("font"):
            args.font = brand.get("font", args.font)
        if not args.font_file and brand.get("font_file"):
            args.font_file = brand["font_file"]
    if args.text:
        # 1.15: drawtext never reorders or re-clusters (no harfbuzz), so Devanagari matras and
        # Thai/Lao mark stacking come out wrong on EVERY build. A wrong frame is not a delivery:
        # refuse and name the two tools that render the script correctly through libass.
        _sc = detect_script(args.text, getattr(args, "lang", None))
        if needs_shaping(_sc):
            die(f"{LANGUAGE_NAMES.get(_sc, _sc)} text cannot be shaped by drawtext on any ffmpeg build "
                "(the marks are reordered by harfbuzz, which drawtext does not use): draw it with "
                "caption.py (--text cues, burned through libass) or graphics.py (--template with "
                "--text-render ass) instead", kind="input")
        if has_emoji(args.text):
            if args.emoji in ("png", "color"):
                die(f"--emoji {args.emoji}: overlay.py draws text with drawtext, which cannot load a colour "
                    "emoji font and cannot place a PNG inside a line -- use caption.py (--emoji-assets) for "
                    "cues or graphics.py (--template) for a title card", kind="input")
            if args.emoji == "none":
                for _i, _cl in list(reversed(emoji_clusters(args.text))):
                    args.text = args.text[:_i] + args.text[_i + len(_cl):]
                warn("emoji: stripped from the drawn text (--emoji none)", "emoji_stripped", mode="none")
            else:
                warn("emoji are drawn by the text font here (monochrome at best); "
                     "caption.py/graphics.py composite colour PNGs with --emoji-assets", "emoji_monochrome")
    script_file = script_family = None
    if args.text and not args.font_file:
        # 1.12: non-Latin overlay text picks a font by script, so a title in Japanese, Korean,
        # Arabic ... draws glyphs instead of boxes. drawtext does not shape or reorder RTL text --
        # see references/gotchas.md#fonts-by-script.
        _script, script_file, script_family = script_font_for_text(
            args.text, font=args.font, font_explicit=args.font != ap.get_default("font"), font_file=args.font_file)
    # the font drawtext gets, reported as `font_used` and recorded when it is not the one asked for
    font_used = font_choice(args.font, font_file=args.font_file, script_file=script_file, script_family=script_family)
    args.font_file = font_used["file"]
    if args.text:
        record_font_choice(font_used)
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    vw = meta["video"]["width"] or 0
    vh = meta["video"].get("height") or 0
    # ffmpeg applies display rotation before the filter graph, so the frame this overlay is
    # composited on is the displayed one. A 320x180 phone file tagged 90 degrees is 180 wide here.
    if meta["video"].get("rotation") in (90, -90, 270, -270):
        vw, vh = vh, vw
    # --platform: the edges this destination's own UI covers, in pixels of this frame. An
    # explicit --margin (or a brand safe_margin, applied above) is the more specific statement
    # and wins; without either, the historical 24 px default is unchanged.
    safe_margins = None
    args.platform = resolve_platform(args.platform)
    if args.platform and args.margin == ap.get_default("margin") and PLATFORMS[args.platform].get("frame"):
        # a dry run has no real frame to measure (the probe is stubbed rather than guessed), so
        # fall back to the destination's own delivery frame -- which is what the fitted
        # intermediate this stage runs on will be anyway
        frame = PLATFORMS[args.platform]["frame"]
        pw, ph = vw or frame["w"], vh or frame["h"]
        safe_margins = safe_margins_px(args.platform, pw, ph)
        info(f"--platform {args.platform}: safe margins top {safe_margins['top']} / bottom {safe_margins['bottom']} / "
             f"left {safe_margins['left']} / right {safe_margins['right']} px (clear of the app's own UI)")
    fps = meta["video"].get("fps")
    start = time_arg(args.start, "--start", fps) if args.start else None
    end = time_arg(args.end, "--end", fps) if args.end else None
    if start is not None and end is not None and end <= start:
        die("--end must be after --start")
    if not 0 <= args.opacity <= 1:
        die("--opacity must be within 0..1")
    if args.chromakey and not args.video:
        die("--chromakey needs --video")
    if args.chromakey:
        validate_color(args.chromakey, "--chromakey")
    validate_color(args.font_color, "--font-color")
    validate_color(args.border_color, "--border-color")
    validate_color(args.box_color, "--box-color")
    if not 0 < args.chromakey_similarity <= 1:
        die("--chromakey-similarity must be within (0, 1]")
    if not 0 <= args.chromakey_blend <= 1:
        die("--chromakey-blend must be within 0..1")
    if args.place and not args.video:
        die("--place needs --video")
    if args.place and (args.start or args.end or args.fade):
        die("--place sets when each piece shows: drop --start / --end / --fade")

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
            # no --start: fade in at 0. The fade-out only exists when --end names a moment the
            # overlay leaves; without --end it stays to the last frame ("fade in at the start" is
            # the common ask, and a matching fade-out at the very end surprised every eval run)
            s = start if start is not None else 0.0
            chain.append(f"fade=t=in:st={s:.3f}:d={args.fade:g}:alpha=1")
            if end is not None and end > args.fade:
                chain.append(f"fade=t=out:st={end - args.fade:.3f}:d={args.fade:g}:alpha=1")
        x, y = position_exprs(args.position, args.margin, text_mode=False, margins=safe_margins)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        # -loop 1 turns the still into a timed stream so fade/enable expressions see real timestamps
        cmd = ffmpeg_base() + ["-i", args.input, "-loop", "1", "-i", args.image]
        # the RGBA still is converted to the BT.709 the output is tagged with (overlay's own
        # RGB-to-YUV step used BT.601), and an untagged main is labelled BT.709 (tags only) so
        # 7.1+'s negotiation does not convert one picture to the other's "unknown" matrix
        base = label_chain(meta, meta) if rgb_chain_to_bt709(meta) else ""
        fc = (f"[1:v]{','.join(chain)},setpts=PTS-STARTPTS{rgb_chain_to_bt709(meta)}[ov];"
              + (f"[0:v]{base}null[base];[base]" if base else "[0:v]") + f"[ov]{ov}[out]")
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", f"0:a:{args.audio_stream}?"]
        if meta.get("duration"):
            # An explicit -t is exact and, unlike -shortest, only bounds the *main* input's
            # streams -- a preserved subtitle/data stream that ends earlier (run_keeping_subtitles)
            # must not be allowed to cut the whole output short via -shortest's "stop at whichever
            # mapped stream finishes first" semantics.
            cmd += ["-t", f"{meta['duration']:.3f}"]
        else:
            # No known duration to bound by -t (e.g. probe found no video duration): -shortest is
            # the only thing stopping the looped still from running forever. FFmpeg 7+'s
            # shortest_buf_duration slack (up to 10s) is an accepted imprecision here since there is
            # no better bound available.
            cmd += ["-shortest"]
    elif args.video:
        pip_meta = probe(args.video)
        if not pip_meta.get("video"):
            die(f"--video {args.video} has no video stream")
        layer_fps = pip_meta["video"].get("fps")
        placements = parse_placements(args.place, fps, layer_fps) if args.place else []
        # bounds from the video streams (a longer audio track would let a range run past the last
        # picture); the container duration only when a stream has none
        layer_dur = pip_meta["video"].get("duration") or pip_meta.get("duration")
        main_dur = meta["video"].get("duration") or meta.get("duration")
        # half a layer frame of slack absorbs a hand-typed end that rounds the last frame's end
        # (2.033 for 61 frames at 30 fps); anything longer asks for pictures the layer does not have
        slack = 0.5 / layer_fps if layer_fps else 0.02
        for a, b, at in placements:
            if layer_dur and a >= layer_dur:
                # the slack below is for an end rounded past the last frame; a start there selects
                # no picture at all and the "placed" piece would silently never show
                die(f"--place {a:g}-{b:g}@{at:g}: starts at or after the layer's end ({layer_dur:.3f} s)")
            if layer_dur and b > layer_dur + slack:
                die(f"--place {a:g}-{b:g}@{at:g}: the layer is only {layer_dur:.3f} s long")
            if main_dur and at >= main_dur:
                die(f"--place {a:g}-{b:g}@{at:g}: starts after the main video ends ({main_dur:.3f} s)")
        chain = []
        if args.scale_percent:
            chain.append(f"scale={int(vw * args.scale_percent / 100)}:-2")
        elif args.scale:
            chain.append(f"scale={args.scale}:-2")
        chain.append("format=yuva420p")
        if args.chromakey:
            chain.append(f"chromakey={args.chromakey}:{args.chromakey_similarity:g}:{args.chromakey_blend:g}")
        if args.opacity < 1:
            chain.append(f"colorchannelmixer=aa={args.opacity:g}")
        x, y = position_exprs(args.position, args.margin, text_mode=False, margins=safe_margins)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        cmd = ffmpeg_base() + ["-i", args.input, "-i", args.video]
        # both pictures converted by their own colour tags to the BT.709 the output is tagged with;
        # beside a converted one an untagged one gets its BT.709 label, tags only, so 7.1+'s
        # overlay does not convert one to the other's "unknown" (BT.601) matrix
        base, pip = matrix_chain(meta, meta), matrix_chain(pip_meta, meta)
        if base or pip:
            base, pip = base or label_chain(meta, meta), pip or label_chain(pip_meta, meta)
        if placements:
            # each placed piece: its range of the layer, re-timed to start at AT; eof_action=pass shows
            # the main picture untouched once a piece ends (the default would freeze its last frame)
            pieces = len(placements)
            # trim selects by timestamp: start the layer's at 0 so SRC_START/SRC_END count from its
            # first picture even when its video stream starts later than the file (audio first)
            fc = f"[1:v]setpts=PTS-STARTPTS,{pip}{','.join(chain)},split={pieces}" + "".join(f"[p{i}]" for i in range(pieces)) + ";"
            for i, (a, b, at) in enumerate(placements):
                fc += f"[p{i}]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS+{at:.6f}/TB[q{i}];"
            prev = f"[0:v]{base}null[m]" if base else None
            if prev:
                fc += prev + ";"
            cur = "[m]" if base else "[0:v]"
            for i in range(pieces):
                nxt = "[out]" if i == pieces - 1 else f"[m{i}]"
                fc += f"{cur}[q{i}]{ov}:eof_action=pass{nxt}" + ("" if i == pieces - 1 else ";")
                cur = nxt
        else:
            fc = (f"[1:v]{pip}{','.join(chain)}[ov];"
                  + (f"[0:v]{base}null[base];[base]" if base else "[0:v]") + f"[ov]{ov}[out]")
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", f"0:a:{args.audio_stream}?"]
        if meta.get("duration"):
            # See the --image branch above: -t (exact, bounds only the main input) instead of
            # -shortest (would also stop at a preserved subtitle/data stream that ends earlier).
            cmd += ["-t", f"{meta['duration']:.3f}"]
        else:
            cmd += ["-shortest"]
    else:
        x, y = position_exprs(args.position, args.margin, text_mode=True, margins=safe_margins)
        # 1.15: the text goes in a FILE with expansion off, so `'` and `%` survive verbatim
        # (they used to be dropped by escape_drawtext) and no character can reach the graph parser.
        font_opt = (drawtext_fontfile(args.font_file) if args.font_file
                    else f"font='{escape_drawtext(args.font)}'")
        alpha = alpha_expr(args.opacity, start if start is not None else (0.0 if args.fade > 0 else None), end, args.fade)
        timing = ([f"alpha='{alpha}'"] if alpha != "1" else []) + ([f"enable='{enable}'"] if enable else [])
        box = ["box=1", f"boxcolor={args.box_color}", "boxborderw=12"] if args.box else []
        if is_multiline(args.text) and drawtext_draws_newline_glyph():
            # this release's drawtext draws the font's missing-glyph box at every line break and
            # counts it in text_w: one drawtext per line, placed where one block would put it
            drawing = per_line_drawtext(drawtext_clean(args.text).split("\n"), x, y, font_opt, args, box, timing)
        else:
            opts = [drawtext_text_opts(args.text), f"fontsize={args.font_size}", f"x={x}", f"y={y}",
                    f"borderw={args.border}", f"bordercolor={args.border_color}", font_opt,
                    f"fontcolor={args.font_color}"] + timing[:1] + box + timing[1:]
            drawing = "drawtext=" + ":".join(opts)
        # a font/border/box colour with chroma lands in the BT.709 the output is tagged with
        colours = [args.font_color] + ([args.border_color] if args.border else []) + ([args.box_color] if args.box else [])
        cmd += ["-vf", drawn_chain(drawing, meta, colours), "-map", "0:v:0"]
        if meta.get("audio"):
            cmd += ["-map", f"0:a:{args.audio_stream}"]

    cmd += video_args(meta, args.crf, args.preset, convert_matrix=not args.video) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)
    if not STATE.dry_run:
        result = probe(output, role="output")
        info(f"wrote {output} ({fmt_secs(result['duration'])})")
    emit(output, dropped_non_av_streams=dropped_streams, **({"font_used": font_used} if args.text else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
