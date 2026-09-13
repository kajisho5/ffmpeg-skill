#!/usr/bin/env python3
"""Render a set of positioned text elements as an ASS file, so libass draws them instead of
drawtext.

Private helper (leading underscore): not a tool, no TOOL_META entry, no contract or MCP surface.

Why it exists (1.15): drawtext cannot SHAPE. On a build with fribidi it gets bidi and Arabic
joining right, but it never reorders or re-clusters -- Devanagari matras come out in logical
order and Thai/Lao marks stack wrongly -- because drawtext does not use harfbuzz even in an
--enable-libharfbuzz build. libass does. `graphics.py` keeps computing exactly the geometry it
computed before; only the renderer changes, and only for text that needs it.

Each element is a dict:

    {"text", "x", "y", "size", "color", "font", "bold", "outline", "outline_color",
     "shadow", "align", "start", "end", "fade", "move", "scale_t", "box", "box_color"}

`align` is the ASS numpad alignment of (x, y) -- 7 is top-left, 5 centre, 2 bottom-centre -- so
a centred title needs no text-width measurement at all. `move` is (x1, y1, x2, y2, t1, t2) in
milliseconds relative to the line's own start; `fade` is (in_ms, out_ms); `scale_t` is
(t1_ms, t2_ms, percent) for a pop.
"""
from typing import Any, Dict, List, Optional, Sequence


# One sentinel character stands in drawn text where an emoji was, so the placeholder is inserted
# AFTER the brace-stripping that keeps caller-supplied text from injecting override commands.
EMOJI_SENTINEL = "\ue000"


def emoji_placeholder(box_px: float) -> str:
    """The ASS override that reserves exactly `box_px` of advance and draws nothing.

    Measured, not assumed (1.15 spec, open question 2). U+2588 FULL BLOCK is NOT 1.0 em: its
    advance measured 0.83 em in FreeSans, 0.79 in WenQuanYi Zen Hei and 0.66 in DejaVu Sans,
    IPAPGothic and Loma, so a block reserves the wrong gap in every face this repo resolves.
    The spec's fallback, alpha-hidden figure spaces (U+2007), measured 0.46-0.55 em and only
    quantises the gap to half an em. What IS exact in all five faces is that same alpha-hidden
    whitespace carried by `\fsp` (letter spacing, in script pixels) on a zero-width space: the
    next glyph starts exactly `box_px` later, with no font dependence at all (verified by render,
    including inside a karaoke run, where the placeholder is its own zero-duration \kf segment).
    `\r` restores the style for the rest of the line.
    """
    return "{\\alpha&HFF&\\fsp%.1f}\u200b{\\r}" % box_px


def ass_time(sec: float) -> str:
    cs = int(round(max(0.0, sec) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = str(hex_rgb).lstrip("#")
    if len(h) != 6:
        raise ValueError(f"colour must be RRGGBB hex, got '{hex_rgb}'")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_field(name: str) -> str:
    """A font name or style name for a comma-delimited ASS field: no escape mechanism exists, so
    the delimiters are dropped (the same call caption.py's ass_font_name() makes)."""
    out = "".join(ch for ch in str(name or "") if ord(ch) >= 0x20 and ch not in ",:\\'")
    return out or "Sans"


# After a literal backslash, these characters would start an ASS sequence libass acts on
# (\N, \n, \h) or an override block (\{ is an escape, so \\{ is ambiguous). A zero-width space
# between the two breaks the sequence without changing what the reader sees.
_ASS_AFTER_BACKSLASH = frozenset("Nnh{}")


def ass_escape(text: str) -> str:
    """Element text for a Dialogue, with every character the user typed still in it.

    `{` and `}` would open and close an override block -- real style and animation commands
    (\\pos, \\t, \\fscx), so caller-supplied text containing them could reposition, rescale or
    recolour itself and everything after it. libass has escapes for exactly this (`\\{`, `\\}`),
    so 1.15.0 escapes them instead of deleting them: `A {b} c \\ d` now reaches the picture
    verbatim through the ASS route, the way it already did through drawtext. A literal backslash
    needs no escape of its own in libass (`\\\\` renders as TWO backslashes, it is not an escape);
    only a backslash immediately before one of _ASS_AFTER_BACKSLASH is ambiguous, and a
    zero-width space parts them.
    """
    s = str(text or "")
    out = []
    for i, ch in enumerate(s):
        if ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\n":
            out.append("\\N")
        elif ch == "\\":
            out.append("\\\u200b" if (i + 1 < len(s) and s[i + 1] in _ASS_AFTER_BACKSLASH) else "\\")
        else:
            out.append(ch)
    return "".join(out)


def ass_text(text: str) -> str:
    """Back-compatible name for ass_escape()."""
    return ass_escape(text)


def text_overlay_ass(elements: Sequence[Dict[str, Any]], *, play_w: int, play_h: int,
                     path: str, fonts_dir: Optional[str] = None) -> str:
    """Write `elements` as an ASS file at `path` and return the path."""
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {play_w}", f"PlayResY: {play_h}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    events: List[str] = []
    for i, el in enumerate(elements):
        name = f"E{i}"
        colour = ass_color(el.get("color", "FFFFFF"))
        outline_colour = ass_color(el.get("outline_color", "000000"))
        box = bool(el.get("box"))
        back = ass_color(el.get("box_color", el.get("outline_color", "000000")),
                         int(el.get("box_alpha", 0)))
        header.append(
            f"Style: {name},{ass_field(el.get('font') or 'Sans')},{int(round(el['size']))},"
            f"{colour},{colour},{outline_colour},{back},{-1 if el.get('bold') else 0},0,0,0,"
            f"100,100,0,0,{3 if box else 1},{float(el.get('outline', 0)):.1f},"
            f"{float(el.get('shadow', 0)):.1f},{int(el.get('align', 7))},0,0,0,1")
        tags = [f"\\an{int(el.get('align', 7))}"]
        move = el.get("move")
        if move:
            x1, y1, x2, y2, t1, t2 = move
            tags.append(f"\\move({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f},{t1:.0f},{t2:.0f})")
        else:
            tags.append(f"\\pos({el['x']:.0f},{el['y']:.0f})")
        fade = el.get("fade")
        if fade:
            tags.append(f"\\fad({fade[0]:.0f},{fade[1]:.0f})")
        scale_t = el.get("scale_t")
        if scale_t:
            t1, t2, pct = scale_t
            tags.append(f"\\fscx{pct:.0f}\\fscy{pct:.0f}\\t({t1:.0f},{t2:.0f},\\fscx100\\fscy100)")
        events.append(
            f"Dialogue: 0,{ass_time(el['start'])},{ass_time(el['end'])},{name},,0,0,0,,"
            "{" + "".join(tags) + "}" + ass_text(el["text"]).replace(
                EMOJI_SENTINEL, emoji_placeholder(el.get("box_px") or el["size"])))
    body = "\n".join(header + ["", "[Events]",
                               "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
                               "MarginV, Effect, Text"] + events) + "\n"
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(body)
    return path
