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
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


# One sentinel character stands in drawn text where an emoji was, so the placeholder is inserted
# AFTER the brace-stripping that keeps caller-supplied text from injecting override commands.
EMOJI_SENTINEL = "\ue000"


def emoji_placeholder(box_px: float) -> str:
    r"""The ASS override that reserves exactly `box_px` of advance and draws nothing.

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
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
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


# --- SRT markup -------------------------------------------------------------------------------
# The tags ffmpeg's own SRT reader turns into styling (libavcodec/htmlsubtitles.c): <i> <b> <u>
# <s>, <font color=...>, and a `{\anN}` position block. caption.py's plain --srt route hands the
# file to ffmpeg, which draws `<i>Hello</i>` in italics; the routes where caption.py writes its own
# ASS (--animate, --karaoke, an emoji-forced ASS, the tiktok/reels/shorts templates) escaped the
# same cue and drew the tags as text, and the wrapper measured them as width. Only these tags are
# markup here: an unknown `<tag>` and every other `{\...}` block stay text, escaped as before
# (a caption still cannot open \pos or \t from its cue text).
_SRT_TAG_RE = re.compile(
    r"<\s*(/?)\s*(i|b|u|s)\s*>"                       # 1, 2: simple style tags
    r"|<\s*font\b([^<>]*)>"                           # 3: <font ...attributes>
    r"|<\s*/\s*font\s*>"                              # closing font
    r"|\{\\an([1-9])\}",                              # 4: position block
    re.IGNORECASE)
_FONT_COLOR_RE = re.compile(r"""\bcolor\s*=\s*["']?\s*([#\w]+)""", re.IGNORECASE)
_NAMED_COLORS = {
    "white": "ffffff", "black": "000000", "red": "ff0000", "lime": "00ff00", "green": "008000",
    "blue": "0000ff", "yellow": "ffff00", "cyan": "00ffff", "aqua": "00ffff",
    "magenta": "ff00ff", "fuchsia": "ff00ff", "silver": "c0c0c0", "gray": "808080",
    "grey": "808080", "maroon": "800000", "olive": "808000", "navy": "000080",
    "purple": "800080", "teal": "008080", "orange": "ffa500"}


def srt_markup_tokens(text: str) -> "List[Tuple[bool, str]]":
    """`text` cut into (is_markup, piece) runs, in order; the pieces concatenate back to `text`."""
    out: "List[Tuple[bool, str]]" = []
    pos = 0
    for m in _SRT_TAG_RE.finditer(text or ""):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text or ""):
        out.append((False, text[pos:]))
    return out


def strip_srt_markup(text: str) -> str:
    """The words a viewer reads: `text` with the SRT markup tags removed."""
    return "".join(piece for markup, piece in srt_markup_tokens(text) if not markup)


def srt_alignment(text: str) -> "Optional[int]":
    """The `{\\anN}` a cue asks for, or None."""
    for markup, piece in srt_markup_tokens(text):
        m = _SRT_TAG_RE.fullmatch(piece) if markup else None
        if m and m.group(4):
            return int(m.group(4))
    return None


def _font_colour(attrs: str) -> "Optional[str]":
    m = _FONT_COLOR_RE.search(attrs or "")
    if not m:
        return None
    value = m.group(1).lower()
    value = _NAMED_COLORS.get(value, value)
    if value.startswith("0x"):
        value = value[2:]
    value = value.lstrip("#")
    if re.fullmatch(r"[0-9a-f]{6}", value):
        return "&H%s%s%s&" % (value[4:6].upper(), value[2:4].upper(), value[0:2].upper())
    return None   # ffmpeg ignores a colour it cannot read (#f00 included); so does this


def _markup_to_ass(tag: str, colours: "List[str]", colour: bool = True) -> str:
    m = _SRT_TAG_RE.fullmatch(tag)
    if not m:
        return ""
    if not colour and not m.group(2) and not m.group(4):
        return ""   # a <font> tag where the caller owns the colours (karaoke): dropped
    if m.group(2):
        return "{\\%s%d}" % (m.group(2).lower(), 0 if m.group(1) else 1)
    if m.group(4):
        return "{\\an%s}" % m.group(4)
    if m.group(0).lstrip("< \t").lower().startswith("/"):
        if colours:
            colours.pop()
        return "{\\c%s}" % colours[-1] if colours else "{\\c}"
    colour = _font_colour(m.group(3))
    colours.append(colour or (colours[-1] if colours else ""))
    return "{\\c%s}" % colour if colour else ""


def ass_escape_markup(text: str, colour: bool = True) -> str:
    """ass_escape() for cue text that may carry SRT markup: the tags ffmpeg's SRT reader styles
    become the same ASS overrides it writes for them (`<i>` -> `{\\i1}`, `<font color="#ffff00">`
    -> `{\\c&H00FFFF&}`, `{\\an8}` kept), and everything else is escaped exactly as ass_escape()
    escapes it. `colour=False` drops the <font> tags instead: karaoke's highlight IS the primary
    colour, and a cue colour would replace it."""
    out: "List[str]" = []
    colours: "List[str]" = []
    for markup, piece in srt_markup_tokens(text):
        if markup:
            out.append(_markup_to_ass(piece, colours, colour))
            continue
        escaped = ass_escape(piece)
        if escaped.endswith("\\") and not escaped.endswith("\\​"):
            escaped += "​"   # a trailing backslash must not run into the override after it
        out.append(escaped)
    return "".join(out)


def reinsert_srt_markup(marked: str, lines: "Sequence[str]") -> "List[str]":
    """Put `marked`'s markup back into `lines`, a wrap of strip_srt_markup(marked).

    A wrap keeps every visible character in order and only turns whitespace into a break (or puts a
    break between two characters), so each tag is anchored to a character: a closing tag right
    after the visible character before it, any other tag right before the visible character after
    it. Lines that do not hold the stripped text in order come back unchanged (markup dropped):
    tags would otherwise land in the wrong word.

    A tag pair that encloses no visible character (`A<font color=red> </font>B`) has no character
    to anchor to, and the rule above would put its closing tag after A and its opening tag before
    B, colouring B. In a gap between two visible characters that holds such a pair, the tags keep
    their source order instead: those before the pair's closing tag go right after the character
    before the gap, the rest right before the character after it (both at the start of the next
    line when the gap's whitespace became the break)."""
    tokens = srt_markup_tokens(marked)
    if not any(markup for markup, _p in tokens):
        return list(lines)
    # (line, column) of every non-space character of the wrapped lines, in reading order
    slots = [(li, ci) for li, line in enumerate(lines) for ci, ch in enumerate(line) if not ch.isspace()]
    if not slots:
        return list(lines)
    split_at = _empty_pair_splits(tokens)
    inserts: "Dict[Tuple[int, int], List[str]]" = {}
    seen = 0   # non-space visible characters passed so far
    for index, (markup, piece) in enumerate(tokens):
        if not markup:
            for ch in piece:
                if ch.isspace():
                    continue
                if seen >= len(slots) or lines[slots[seen][0]][slots[seen][1]] != ch:
                    return list(lines)
                seen += 1
            continue
        after_prev = (slots[seen - 1][0], slots[seen - 1][1] + 1) if seen else None
        before_next = slots[seen] if seen < len(slots) else None
        split = split_at.get(seen)
        if split is not None:
            # this gap holds a pair that encloses no visible character: keep the source order
            if after_prev is None or before_next is None:
                key = after_prev or before_next
            elif after_prev[0] != before_next[0]:
                key = before_next
            else:
                key = after_prev if index < split else before_next
        elif piece.lstrip("< \t").startswith("/") and after_prev or before_next is None:
            key = after_prev
        else:
            key = before_next
        inserts.setdefault(key, []).append(piece)
    if seen != len(slots):
        return list(lines)
    out = []
    for li, line in enumerate(lines):
        cols = sorted(ci for (l2, ci) in inserts if l2 == li)
        built, last = "", 0
        for ci in cols:
            built += line[last:ci] + "".join(inserts[(li, ci)])
            last = ci
        out.append(built + line[last:])
    return out


def _empty_pair_splits(tokens: "Sequence[Tuple[bool, str]]") -> "Dict[int, int]":
    """For each gap between visible characters (keyed by the number of non-space characters
    before it) that holds a tag pair enclosing none, the token index of the first such pair's
    closing tag."""
    splits: "Dict[int, int]" = {}
    seen = 0
    open_here: "List[str]" = []   # names of the tags opened in the current gap
    for index, (markup, piece) in enumerate(tokens):
        if not markup:
            if piece.strip():
                seen += sum(1 for ch in piece if not ch.isspace())
                open_here = []
            continue
        m = _SRT_TAG_RE.fullmatch(piece)
        if not m or m.group(4):
            continue
        name = (m.group(2) or "font").lower()
        if piece.lstrip("< \t").startswith("/"):
            if name in open_here:
                splits.setdefault(seen, index)
                del open_here[len(open_here) - 1 - open_here[::-1].index(name)]
        else:
            open_here.append(name)
    return splits


def carry_srt_markup(chunks: "Sequence[str]") -> "List[str]":
    """Consecutive cues cut from one marked cue, each made to stand alone: a tag still open at the
    end of a piece is closed there and opened again at the start of the next, and the cue's
    `{\\anN}` is repeated on every piece -- the second half of an italic, top-placed cue stays
    italic and at the top."""
    out: "List[str]" = []
    carried: "List[str]" = []
    # the cue's position, wherever in it the {\anN} stands: an earlier piece takes it too
    align = next((a for a in (srt_alignment(c) for c in chunks) if a is not None), None)
    for chunk in chunks:
        lead = "".join(carried)
        if align is not None and srt_alignment(chunk) is None:
            lead = "{\\an%d}" % align + lead
        opened: "List[str]" = list(carried)
        for markup, piece in srt_markup_tokens(chunk):
            if not markup:
                continue
            m = _SRT_TAG_RE.fullmatch(piece)
            if not m or m.group(4):
                continue
            closing = piece.lstrip("< \t").startswith("/")
            name = (m.group(2) or "font").lower()
            if closing:
                for k in range(len(opened) - 1, -1, -1):
                    if _tag_name(opened[k]) == name:
                        del opened[k]
                        break
            else:
                opened.append(piece)
        tail = "".join("</%s>" % _tag_name(t) for t in reversed(opened))
        out.append(lead + chunk + tail)
        carried = opened
    return out


def _tag_name(tag: str) -> str:
    m = _SRT_TAG_RE.fullmatch(tag)
    return ((m.group(2) if m else None) or "font").lower()


def text_overlay_ass(elements: Sequence[Dict[str, Any]], *, play_w: int, play_h: int,
                     path: str, fonts_dir: Optional[str] = None) -> str:
    """Write `elements` as an ASS file at `path` and return the path."""
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {play_w}", f"PlayResY: {play_h}",
        # YCbCr Matrix: None -- the colours are RGB, to be put in the video's own matrix: FFmpeg 8.x's
        # ass filter reads an absent header as BT.601 whatever the picture is tagged (drawn_chain)
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: None", "",
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
