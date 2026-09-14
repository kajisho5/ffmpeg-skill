"""Text people can see: font resolution per script, emoji clusters and their assets, drawtext
escaping and option building, and the per-character advance table the caption wrap measures with.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from _common.decision import escape_filter_path
from _common.emit import die, info
from _common.runner import STATE, _DRAWTEXT_PENDING, _drawtext_tmpdir, ffmpeg_version


def drawtext_boxborderw(vertical: int, horizontal: int) -> str:
    """drawtext's per-side `boxborderw=top|right|bottom|left` (and the two-value `v|h` form)
    arrived in FFmpeg 6.1; 5.x and 6.0 reject the `|` with "Error setting option boxborderw"
    (found by the FFmpeg 5.1.1 CI job, #146). Older builds get the larger single value."""
    if ffmpeg_version() >= (6, 1):
        return f"{vertical}|{horizontal}"
    return str(max(vertical, horizontal))


def default_font_file(font_name: str) -> Optional[str]:
    """Resolve `font_name` to a concrete on-disk font file, so a caller can tell drawtext
    `fontfile=<path>` instead of `font=<name>`, when possible.

    On some real Windows ffmpeg builds (winget's gyan.dev 9.x), drawtext's own fontconfig
    resolution crashes with an access violation whenever it has to resolve a font by family name
    -- with or without a valid fonts.conf on FONTCONFIG_FILE. `fontfile=` is the only form
    confirmed not to crash (#100), since it never touches fontconfig at all. `font_name` itself is
    ignored on Windows for that reason: a fixed, near-universally-present system font is used
    instead of trying to resolve the requested family (which would crash the same way).

    On Linux/macOS this is best-effort and uses the real requested family: `fc-match` reports the
    same file fontconfig would resolve `font_name` to anyway, so a caller gets the identical font,
    just already resolved to a path -- fontfile= skips a redundant fontconfig lookup and equally
    sidesteps the same class of crash if it exists on some build there too, but the fallback below
    (returning None) is exercised routinely there, not just on failure.

    Returns None when nothing could be resolved (fc-match missing/unavailable, or no well-known
    Windows font file present); the caller falls back to font=<font_name>, the prior behaviour.
    """
    if platform.system() == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        fonts = Path(windir) / "Fonts"
        # The requested family first: a file whose name starts with the family name with spaces
        # removed (Noto Sans CJK JP -> NotoSansCJKjp-Regular.otf, Meiryo -> meiryo.ttc), then the
        # common CJK system fonts when the request looks CJK (so Japanese text does not render as
        # boxes in Arial), and Arial only as the last resort.
        wanted = re.sub(r"[^a-z0-9]", "", (font_name or "").lower())
        try:
            files = sorted(fonts.iterdir()) if fonts.is_dir() else []
        except OSError:
            files = []
        if wanted:
            for f in files:
                stem = re.sub(r"[^a-z0-9]", "", f.stem.lower())
                if f.suffix.lower() in (".ttf", ".otf", ".ttc") and stem.startswith(wanted):
                    return str(f)
        if any(k in wanted for k in ("cjk", "gothic", "mincho", "meiryo", "yugoth", "msgothic", "malgun", "simhei", "simsun", "jp", "kr", "sc", "tc")):
            for name in ("NotoSansCJKjp-Regular.otf", "NotoSansCJK-Regular.ttc", "meiryo.ttc", "YuGothM.ttc", "msgothic.ttc", "malgun.ttf", "msyh.ttc"):
                if (fonts / name).exists():
                    return str(fonts / name)
        candidate = fonts / "arial.ttf"
        return str(candidate) if candidate.exists() else None
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "--format=%{file}\n", font_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    path = proc.stdout.splitlines()[0].strip() if proc.stdout.strip() else ""
    return path if path and os.path.exists(path) else None


# --------------------------------------------------------------------------- script detection
# 1.12: non-Latin caption/overlay text used to render as tofu (empty boxes) whenever the default
# family carried no glyphs for it -- silently, because fontconfig substitutes SOMETHING for every
# request and ffmpeg exits 0 either way. The tools now detect the script of the text they are about
# to draw and resolve a font file that actually covers it; nothing found is a failed job, not a
# warning (a video full of boxes is not a delivery).
SCRIPTS = ("ja", "zh", "ko", "ar", "he", "hi", "bn", "ta", "th", "lo", "ru", "el", "latin")


LANGUAGE_NAMES = {
    "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "he": "Hebrew",
    "hi": "Devanagari (Hindi/Marathi/Nepali)", "th": "Thai", "ru": "Cyrillic (Russian and others)",
    "el": "Greek", "latin": "Latin", "bn": "Bengali", "ta": "Tamil", "lo": "Lao",
}


# fontconfig's own :lang= codes for each script we detect (zh uses zh-cn, the Simplified subset
# every CJK font that claims zh carries; the rest are the plain two-letter codes).
FC_LANG = {"ja": "ja", "zh": "zh-cn", "ko": "ko", "ar": "ar", "he": "he", "hi": "hi", "th": "th", "ru": "ru", "el": "el",
           "bn": "bn", "ta": "ta", "lo": "lo"}


# Families tried in order, best first. The names are matched case-insensitively against the start
# of any family fontconfig reports for a file, so "Noto Sans CJK JP" also matches
# "Noto Sans CJK JP Black". Anything not listed still qualifies -- it just sorts after these.
PREFERRED_FAMILIES = {
    "ja": ["Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans JP", "Source Han Sans", "IPAPGothic", "IPAGothic", "IPA", "VL Gothic", "TakaoGothic", "WenQuanYi Zen Hei"],
    "zh": ["Noto Sans CJK SC", "Noto Serif CJK SC", "Noto Sans SC", "Source Han Sans", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Droid Sans Fallback"],
    "ko": ["Noto Sans CJK KR", "Noto Serif CJK KR", "Noto Sans KR", "Source Han Sans K", "NanumGothic", "Nanum Gothic", "Malgun Gothic", "WenQuanYi Zen Hei"],
    "ar": ["Noto Sans Arabic", "Noto Naskh Arabic", "Amiri", "Scheherazade", "DejaVu Sans", "FreeSans", "FreeSerif"],
    "he": ["Noto Sans Hebrew", "Noto Serif Hebrew", "DejaVu Sans", "FreeSans", "FreeSerif"],
    "hi": ["Noto Sans Devanagari", "Noto Serif Devanagari", "Lohit Devanagari", "Mangal", "Nirmala UI", "Samyak Devanagari", "FreeSans", "FreeSerif"],
    "th": ["Noto Sans Thai", "Noto Serif Thai", "Loma", "Garuda", "Waree", "Umpush", "Norasi", "Sarabun", "Leelawadee UI", "FreeSerif"],
    "bn": ["Noto Sans Bengali", "Noto Serif Bengali", "Lohit Bengali", "Mukti Narrow", "Vrinda", "Nirmala UI", "FreeSerif"],
    "ta": ["Noto Sans Tamil", "Noto Serif Tamil", "Lohit Tamil", "Latha", "Nirmala UI", "FreeSerif"],
    "lo": ["Noto Sans Lao", "Noto Serif Lao", "Phetsarath OT", "Souliyo Unicode", "Saysettha OT", "DokChampa", "Leelawadee UI"],
    "ru": ["Noto Sans", "DejaVu Sans", "Liberation Sans", "FreeSans", "FreeSerif"],
    "el": ["Noto Sans", "DejaVu Sans", "Liberation Sans", "FreeSans", "FreeSerif"],
}


# Windows has no fontconfig: the system fonts are looked up by file name instead, best first.
WINDOWS_FONTS = {
    "ko": [("malgun.ttf", "Malgun Gothic"), ("gulim.ttc", "Gulim"), ("batang.ttc", "Batang")],
    "zh": [("msyh.ttc", "Microsoft YaHei"), ("simhei.ttf", "SimHei"), ("simsun.ttc", "SimSun")],
    "ja": [("meiryo.ttc", "Meiryo"), ("YuGothM.ttc", "Yu Gothic Medium"), ("YuGothR.ttc", "Yu Gothic"), ("msgothic.ttc", "MS Gothic")],
    "ar": [("tahoma.ttf", "Tahoma"), ("arial.ttf", "Arial")],
    "he": [("tahoma.ttf", "Tahoma"), ("arial.ttf", "Arial")],
    "hi": [("mangal.ttf", "Mangal"), ("Nirmala.ttf", "Nirmala UI"), ("NirmalaB.ttf", "Nirmala UI")],
    "th": [("leelawui.ttf", "Leelawadee UI"), ("leelawad.ttf", "Leelawadee"), ("tahoma.ttf", "Tahoma")],
    "bn": [("Nirmala.ttf", "Nirmala UI"), ("vrinda.ttf", "Vrinda")],
    "ta": [("Nirmala.ttf", "Nirmala UI"), ("latha.ttf", "Latha")],
    "lo": [("leelawui.ttf", "Leelawadee UI"), ("DokChamp.ttf", "DokChampa")],
    "ru": [("arial.ttf", "Arial"), ("segoeui.ttf", "Segoe UI")],
    "el": [("arial.ttf", "Arial"), ("segoeui.ttf", "Segoe UI")],
}


_SCRIPT_RANGES = (
    ("ko", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7FF))),   # Hangul syllables + Jamo
    ("kana", ((0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9F))),  # hiragana/katakana
    ("han", ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2A6DF))),
    ("ar", ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    ("he", ((0x0590, 0x05FF), (0xFB1D, 0xFB4F))),
    ("hi", ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),
    ("bn", ((0x0980, 0x09FF),)),
    ("ta", ((0x0B80, 0x0BFF),)),
    ("th", ((0x0E00, 0x0E7F),)),
    ("lo", ((0x0E80, 0x0EFF),)),
    ("ru", ((0x0400, 0x04FF), (0x0500, 0x052F), (0x2DE0, 0x2DFF))),
    ("el", ((0x0370, 0x03FF), (0x1F00, 0x1FFF))),
)


# --------------------------------------------------------------------------- emoji (1.15)
# Emoji are orthogonal to the writing system: "やった 🎉" is Japanese AND emoji. They are detected
# separately from detect_script() so a cue's font resolution is still decided by its letters.
EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),   # symbols & pictographs, supplemental, extended-A
    (0x1F000, 0x1F0FF),   # mahjong/domino/playing cards
    (0x2600, 0x27BF),     # misc symbols + dingbats
    (0x2B00, 0x2BFF),     # misc symbols and arrows
    (0xFE0F, 0xFE0F),     # VS16 (emoji presentation selector)
    (0x1F1E6, 0x1F1FF),   # regional indicators (flags)
    (0x20E3, 0x20E3),     # combining enclosing keycap
    (0x1F3FB, 0x1F3FF),   # skin-tone modifiers
)


# U+200D ZWJ is deliberately NOT in EMOJI_RANGES: it is ordinary Indic/Persian orthography
# (क्‍ष is ka + virama + ZWJ + ssa) and only becomes emoji glue *between two emoji bases*.
# Characters that never START a cluster: they bind to whatever stands before them.
_EMOJI_TAIL = frozenset({0x200D, 0xFE0F, 0x20E3} | set(range(0x1F3FB, 0x1F400)))


_EMOJI_REGIONAL = range(0x1F1E6, 0x1F200)


_ZWJ = 0x200D


_VS15 = 0xFE0E   # text-presentation selector: "draw this as a character, not as an emoji"


_VS16 = 0xFE0F


_KEYCAP = 0x20E3


_KEYCAP_BASES = frozenset("0123456789#*")


def _is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def _is_emoji_base(ch: str) -> bool:
    """Can this character START an emoji cluster? Pictographs and regional indicators can;
    the joiners and modifiers (ZWJ, VS16, keycap, skin tone) never can -- they only bind to an
    emoji base that already stands before them. Without this, a ZWJ or a VS16 sitting after an
    ordinary letter turned that letter into "an emoji" and the PNG route replaced it with a gap."""
    return ord(ch) not in _EMOJI_TAIL and _is_emoji_char(ch)


def emoji_clusters(text: str) -> "List[Tuple[int, str]]":
    """(index in `text`, cluster) for every emoji in it, ZWJ sequences, VS16, keycaps, flag pairs
    and skin-tone modifiers kept together -- 👩‍💻 is one cluster, not three, and 1️⃣ starts at the
    digit even though the digit is not itself an emoji character.

    A cluster can only START at an emoji base (a pictograph, a regional indicator) or at a keycap
    base (`0-9 # *`) that is actually followed by U+20E3. A ZWJ is glue *inside* a cluster, never
    a starter and never a tail on its own: `क्‍ष` (Hindi ka + virama + ZWJ + ssa) and `abc‍def`
    contain no emoji. A base explicitly marked with U+FE0E (VS15, text presentation) is likewise
    not an emoji -- the author asked for the character, not the picture.
    """
    out: "List[Tuple[int, str]]" = []
    i = 0
    n = len(text or "")
    while i < n:
        ch = text[i]
        start = i
        if _is_emoji_base(ch):
            j = i + 1
            if j < n and ord(text[j]) == _VS15:      # text presentation requested: not an emoji
                i = j + 1
                continue
        elif ch in _KEYCAP_BASES:
            j = i + 1
            if j < n and ord(text[j]) == _VS16:
                j += 1
            if not (j < n and ord(text[j]) == _KEYCAP):
                i += 1
                continue
            j += 1
        else:
            i += 1
            continue
        # extend: modifiers bind rightwards, a ZWJ only when a real emoji base follows it
        while j < n:
            cp = ord(text[j])
            if cp in (_VS16, _KEYCAP) or 0x1F3FB <= cp <= 0x1F3FF:
                j += 1
                continue
            if cp == _ZWJ and j + 1 < n and _is_emoji_base(text[j + 1]):
                j += 2
                continue
            if (j == start + 1 and ord(ch) in _EMOJI_REGIONAL and cp in _EMOJI_REGIONAL):
                j += 1
                continue
            break
        out.append((start, text[start:j]))
        i = j
    return out


def has_emoji(text: str) -> bool:
    return bool(emoji_clusters(text or ""))


def emoji_codepoint_name(cluster: str) -> str:
    """The asset filename stem for a cluster: lowercase hex code points joined by '-', the
    Twemoji/Noto convention (1f389, 1f469-200d-1f4bb, 1f1ef-1f1f5)."""
    return "-".join(f"{ord(c):x}" for c in cluster)


def _emoji_name_candidates(cluster: str) -> "List[str]":
    """Asset stems to try, most specific first: exact, without VS16, without skin tone, the ZWJ
    sequence reduced to its first code point, the bare base."""
    cps = [ord(c) for c in cluster]
    names = [emoji_codepoint_name(cluster)]

    def add(seq):
        name = "-".join(f"{c:x}" for c in seq)
        if name and name not in names:
            names.append(name)
    add([c for c in cps if c != 0xFE0F])
    add([c for c in cps if c != 0xFE0F and not (0x1F3FB <= c <= 0x1F3FF)])
    if 0x200D in cps:
        add([cps[0]])
    add([cps[0]])
    return names


def emoji_asset_for(cluster: str, assets_dir: "Optional[str]") -> "Optional[str]":
    """The PNG for `cluster` under `assets_dir`, or None when nothing matches."""
    if not assets_dir or not os.path.isdir(assets_dir):
        return None
    for name in _emoji_name_candidates(cluster):
        for ext in (".png", ".PNG"):
            candidate = os.path.join(assets_dir, name + ext)
            if os.path.isfile(candidate):
                return candidate
    return None


EMOJI_ASSET_HINT = (
    "point --emoji-assets at a directory of PNGs named by code point (1f389.png): "
    "twemoji/assets/72x72 (Twemoji, CC-BY 4.0) or noto-emoji/png/128 (Noto Emoji, OFL/Apache-2.0) "
    "are the two people already have. The skill has no network at runtime, so the assets must "
    "already exist on this machine -- nothing is ever downloaded")


_EMOJI_COLOR_FAMILIES = ("Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji")


_EMOJI_SUPPORT_CACHE: "Dict[Tuple[Optional[str], bool], Dict[str, Any]]" = {}


def _emoji_color_font() -> "Tuple[Optional[str], Optional[str], bool]":
    """(family, file, fontconfig_answered) for the first installed colour emoji family."""
    exe = shutil.which("fc-list")
    if not exe:
        return None, None, False
    for family in _EMOJI_COLOR_FAMILIES:
        try:
            proc = subprocess.run([exe, f":family={family}", "file"], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return None, None, False
        if proc.returncode != 0:
            return None, None, False
        for line in proc.stdout.splitlines():
            path = line.split(":", 1)[0].strip()
            if path and os.path.exists(path):
                return family, path, True
    return None, None, True


def _libass_color_probe() -> "Optional[bool]":
    """Does THIS ffmpeg render an emoji in colour through libass? Answered by a render, never by
    the font listing: Noto Color Emoji installs happily on builds whose freetype/libass has no
    colour-bitmap path at all, and those render a monochrome outline instead (measured). ~80 ms.
    None means the probe could not be run (no ffmpeg, a failure) -- unknown, not false."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        srt = os.path.join(td, "e.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:01,000\n\U0001F389\n")
        try:
            proc = subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "color=c=black:s=64x64:d=0.04",
                 "-vf", "subtitles=" + srt.replace("\\", "/"), "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            return None
    if proc.returncode != 0 or len(proc.stdout) < 64 * 64 * 3:
        return None
    data = proc.stdout
    for i in range(0, 64 * 64 * 3, 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        if max(r, g, b) - min(r, g, b) > 40:
            return True
    return False


def emoji_support(assets: "Optional[str]" = None, probe: bool = True) -> "Dict[str, Any]":
    """What this machine can actually do with emoji, cached per process.

    `mode` is `color` when a render probe proves libass draws colour, else `png` when an assets
    directory resolves, else `mono` when some installed face has a glyph at all, else `none`.
    An installed colour emoji font proves nothing on its own -- that is why `libass_color` comes
    from a render (see references/gotchas.md#emoji). `probe=False` (`contract --json --static`, and every
    static/JSON-only path) skips the render entirely and leaves `libass_color` unknown.
    """
    key = (assets or None, bool(probe))
    if key in _EMOJI_SUPPORT_CACHE:
        return dict(_EMOJI_SUPPORT_CACHE[key])
    family, file, fc_answered = _emoji_color_font()
    libass_color = _libass_color_probe() if probe else None
    assets_dir = assets if (assets and os.path.isdir(assets)) else None
    if libass_color:
        mode = "color"
    elif assets_dir:
        mode = "png"
    elif family:
        mode = "mono"
    elif not fc_answered:
        # No fontconfig to ask (a static ffmpeg build, a bare container): the PNG path needs none,
        # so the honest answer is png-or-none, never "none because fc-list is missing".
        mode = "none"
    else:
        mode = "none"
    if not fc_answered:
        detail = "no fontconfig on this machine; the PNG overlay path needs none"
    elif libass_color:
        detail = f"{family or 'an installed face'} renders in colour through libass on this ffmpeg"
    elif family and libass_color is False:
        detail = f"{family} installed but libass renders it monochrome on this build"
    elif family and libass_color is None:
        detail = f"{family} installed; the colour render probe was not run"
    elif assets_dir:
        detail = "no colour emoji family installed; using the PNG assets directory"
    else:
        detail = "no colour emoji family installed and no --emoji-assets directory"
    result = {"mode": mode, "color_font": family, "color_font_file": file,
              "libass_color": libass_color, "assets": assets_dir,
              "detail": detail, "fix": EMOJI_ASSET_HINT}
    _EMOJI_SUPPORT_CACHE[key] = result
    return dict(result)


def resolve_emoji_assets(flag: "Optional[str]" = None, project: "Optional[str]" = None,
                         brand: "Optional[dict]" = None) -> "Optional[str]":
    """--emoji-assets DIR, else the project key, else brand.json, else FFMPEG_SKILL_EMOJI_ASSETS.
    A directory that was named but does not exist is a failed job, never a silent downgrade."""
    brand = brand or {}
    styles = (brand.get("styles") or {}).get("caption") or {}
    for value, where in ((flag, "--emoji-assets"), (project, "the project's text.emoji_assets"),
                         (styles.get("emoji_assets"), "brand.json styles.caption.emoji_assets"),
                         (brand.get("emoji_assets"), "brand.json emoji_assets"),
                         (os.environ.get("FFMPEG_SKILL_EMOJI_ASSETS"), "FFMPEG_SKILL_EMOJI_ASSETS")):
        if not value:
            continue
        if not os.path.isdir(str(value)):
            die(f"{where}: {value} is not a readable directory -- {EMOJI_ASSET_HINT}", kind="input")
        return str(value)
    return None


# --------------------------------------------------------------------------- text measurement (1.12)
# Moved here in 1.15 so graphics.py's ASS route and the emoji placement share caption.py's table.
# Average advance width per character, in em (a fraction of the font size). Proportional Latin text
# averages a bit over half an em; CJK and Thai are drawn on a full-width grid; Arabic/Hebrew and
# Devanagari sit in between. These are deliberately averages, not per-glyph metrics: measuring the
# real advance needs a font parser (no stdlib one) and would still be wrong for libass's own
# shaping, while a cue wrapped from an average is right to within a character on every line.
# (Latin is measured per character from LATIN_EM below, not from this average.)
ADVANCE_EM = {"ja": 1.0, "zh": 1.0, "ko": 1.0, "th": 1.0, "hi": 0.7, "ar": 0.6, "he": 0.6,
              "ru": 0.55, "el": 0.55, "latin": 0.55}


# Scripts written without spaces: a line breaks between any two characters.
# Scripts a line may break inside a run of, one character at a time. Thai is deliberately NOT
# here since 1.16.1: it writes no space inside a phrase, and without a dictionary the wrapper
# cannot see where one word ends -- every character-level break it took in eval 17 landed inside
# a word. A Thai run is therefore one atom, broken only at the spaces (or the manual `|`) the
# writer put there; an over-long run stays long on its own line, the rule long Latin words
# already follow.
NO_SPACE_SCRIPTS = ("ja", "zh", "ko")
NO_BOUNDARY_SCRIPTS = ("th",)   # per-character breaking would chop words: keep the run whole


# Per-character Latin advances in em, read off DejaVu Sans (the default caption family, and close
# enough to any other proportional sans for a wrap) and rounded UP: a capital runs 0.56-0.99 em
# against the single 0.55 average that used to stand for all of Latin, so an all-caps caption --
# the style most burn-ins use -- overflowed the safe area and was silently re-wrapped by libass
# past --max-lines. Rounding up is the safe direction: libass re-wraps a too-long line, it never
# un-wraps a short one. Characters outside the table fall back by class (0.7 uppercase/digit,
# 0.57 lowercase and anything else Latin-ish).
LATIN_EM = {
    ' ': 0.32, '!': 0.41, '"': 0.46, '#': 0.84, '$': 0.64, '%': 0.96, '&': 0.78, "'": 0.28,
    '(': 0.4, ')': 0.4, '*': 0.5, '+': 0.84, ',': 0.32, '-': 0.37, '.': 0.32, '/': 0.34, '0': 0.64,
    '1': 0.64, '2': 0.64, '3': 0.64, '4': 0.64, '5': 0.64, '6': 0.64, '7': 0.64, '8': 0.64,
    '9': 0.64, ':': 0.34, ';': 0.34, '<': 0.84, '=': 0.84, '>': 0.84, '?': 0.54, '@': 1.0,
    'A': 0.69, 'B': 0.69, 'C': 0.7, 'D': 0.78, 'E': 0.64, 'F': 0.58, 'G': 0.78, 'H': 0.76,
    'I': 0.3, 'J': 0.3, 'K': 0.66, 'L': 0.56, 'M': 0.87, 'N': 0.75, 'O': 0.79, 'P': 0.61,
    'Q': 0.79, 'R': 0.7, 'S': 0.64, 'T': 0.62, 'U': 0.74, 'V': 0.69, 'W': 0.99, 'X': 0.69,
    'Y': 0.62, 'Z': 0.69, '[': 0.4, '\\': 0.34, ']': 0.4, '^': 0.84, '_': 0.5, '`': 0.5, 'a': 0.62,
    'b': 0.64, 'c': 0.55, 'd': 0.64, 'e': 0.62, 'f': 0.36, 'g': 0.64, 'h': 0.64, 'i': 0.28,
    'j': 0.28, 'k': 0.58, 'l': 0.28, 'm': 0.98, 'n': 0.64, 'o': 0.62, 'p': 0.64, 'q': 0.64,
    'r': 0.42, 's': 0.53, 't': 0.4, 'u': 0.64, 'v': 0.6, 'w': 0.82, 'x': 0.6, 'y': 0.6, 'z': 0.53,
    '{': 0.64, '|': 0.34, '}': 0.64, '~': 0.84
}


# Thai and Lao write some vowels BEFORE the consonant they belong to: the break must not land
# between them and the base that follows.
LEADING_VOWELS = set(range(0x0E40, 0x0E45)) | set(range(0x0EC0, 0x0EC5))


def _is_mark(ch: str) -> bool:
    """A character that hangs off the one before it: a combining mark (any script) or one of the
    Thai/Lao vowel signs and tone marks, which are Mn/Mc but carry no combining class."""
    return unicodedata.combining(ch) != 0 or unicodedata.category(ch) in ("Mn", "Mc")


def _char_em(ch: str) -> float:
    # CJK punctuation and the fullwidth forms (、。，！？　and U+FF01-FF60) are drawn on the same
    # full-width grid as the ideographs they sit between, even though they are not "Han" to a
    # script detector -- measuring them as Latin under-counts a wrapped CJK line by a character.
    cp = ord(ch)
    # A combining mark is drawn on top of (or under) its base and advances the pen by nothing:
    # charging it a full em wrapped Thai and Devanagari lines far shorter than they needed to be.
    if unicodedata.combining(ch) != 0 or unicodedata.category(ch) in ("Mn", "Cf"):
        # "Cf" catches ZWJ/ZWNJ: an Indic joiner is orthography, and it advances the pen by
        # nothing -- charging it a full em (it used to count as "emoji") shrank a Hindi line.
        return 0.0
    if 0x3000 <= cp <= 0x303F or 0xFF01 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6:
        return 1.0
    script = char_script(ch)
    if script == "emoji":
        # 1.15: an emoji is drawn (or reserved) at a full em box, not at Latin's 0.57 -- counting
        # it as Latin overflowed the safe area on an emoji-heavy line.
        return 1.0
    if script == "latin":
        if ch in LATIN_EM:
            return LATIN_EM[ch]
        if ch.isupper() or ch.isdigit():
            return 0.7
        return 0.57
    return ADVANCE_EM.get(script, 0.55)


def text_width_em(text: str, emoji_em: float = 1.0) -> float:
    """Width of `text` in em, from the per-script average advance table. `emoji_em` is what one
    emoji cluster costs (--emoji-scale), so a wrap counts the box that will actually be drawn."""
    total = 0.0
    spans = {i: len(c) for i, c in emoji_clusters(text)}
    i = 0
    while i < len(text):
        if i in spans:
            total += emoji_em
            i += spans[i]
            continue
        total += _char_em(text[i])
        i += 1
    return total


def emoji_filter_chain(plan, base_label, out_label, first_input=1):
    """(chains, inputs) that composite the planned PNGs on top of `base_label`.

    `inputs` is a list of argv fragments, each ending in the asset path, to be appended to the
    ffmpeg command in order (an overlay that fades needs `-loop 1` on its input so the still has
    a timeline the fade filter can move along; one that does not is a plain `-i`).
    """
    overlays = plan.get("overlays") or []
    if not overlays:
        return [], []
    # Group by everything that makes two uses of the same PNG a different STREAM: the fade is
    # expressed in the cue's own timeline, so two cues cannot share one faded input.
    def _key(o):
        fades = (round(float(o.get("fade_in") or 0.0), 3), round(float(o.get("fade_out") or 0.0), 3))
        window = (round(float(o["start"]), 3), round(float(o["end"]), 3)) if any(fades) else (None, None)
        return (o["asset"], o["box"]) + fades + window

    groups: "List[Tuple]" = []
    for o in overlays:
        if _key(o) not in groups:
            groups.append(_key(o))
    chains: List[str] = []
    inputs: "List[List[str]]" = []
    pads: "Dict[Tuple, List[str]]" = {}
    for k, key in enumerate(groups):
        asset, box, fin, fout, gstart, gend = key
        uses = [o for o in overlays if _key(o) == key]
        idx = first_input + k
        labels = [f"e{k}_{j}" for j in range(len(uses))]
        chain = f"[{idx}:v]format=rgba,scale={box}:{box}"
        if fin or fout:
            # -loop 1 gives the still an advancing timeline on the SAME clock as the main video,
            # so the fade times below are the cue's own seconds. The emoji then appears and
            # leaves with the text instead of popping in against a fading line.
            # -t bounds the loop at the cue's end: an unbounded looped still never EOFs and the
            # whole encode hangs (overlay keeps pulling from it after the main video is done).
            inputs.append(["-loop", "1", "-t", f"{gend:.3f}", "-i", asset])
            if fin:
                chain += f",fade=t=in:st={gstart:.3f}:d={fin:.3f}:alpha=1"
            if fout:
                chain += f",fade=t=out:st={max(gstart, gend - fout):.3f}:d={fout:.3f}:alpha=1"
        else:
            inputs.append(["-i", asset])
        if len(labels) > 1:
            chain += f",split={len(labels)}"
        chains.append(chain + "".join(f"[{l}]" for l in labels))
        pads[key] = labels
    cur = base_label
    remaining = {key: list(v) for key, v in pads.items()}
    for j, o in enumerate(overlays):
        label = remaining[_key(o)].pop(0)
        nxt = out_label if j == len(overlays) - 1 else f"eov{j}"
        x = o["x"]
        x = f"'{x}'" if isinstance(x, str) else x
        # No eof_action=pass here: a PNG input is a SINGLE frame at pts 0, and eof_action=pass
        # switches off overlay's default "hold the last frame of the secondary input", so the
        # asset would be composited on frame 0 only and vanish for the rest of the cue (that is
        # exactly what shipped first). eof_action=repeat (the default) holds the still for the
        # whole timeline; enable= is what confines it to the cue's window.
        chains.append(f"[{cur}][{label}]overlay=x={x}:y={o['y']}:"
                      f"enable='between(t,{o['start']:.3f},{o['end']:.3f})'[{nxt}]")
        cur = nxt
    return chains, inputs


# --------------------------------------------------------------------------- shaping (1.15)
# Scripts whose correct rendering needs harfbuzz-class reordering and re-clustering (Indic matras,
# Thai/Lao mark stacking). drawtext does NOT use harfbuzz even in an --enable-libharfbuzz build, so
# these come out wrong through drawtext on every build and must go through libass. Arabic and
# Hebrew are NOT here: drawtext's text_shaping uses fribidi, which does bidi and Arabic joining
# correctly -- they only join this set on a build compiled without fribidi.
SHAPING_SCRIPTS = frozenset({"hi", "bn", "ta", "te", "kn", "ml", "gu", "pa", "si", "th", "lo", "km", "my"})


BIDI_SCRIPTS = frozenset({"ar", "he"})


_SHAPING_BUILD_CACHE: "Dict[str, bool]" = {}


def drawtext_shaping() -> "Dict[str, bool]":
    """Which shaping libraries THIS ffmpeg was built with, from -buildconf (falling back to the
    `configuration:` line of -version). Cached per process."""
    if _SHAPING_BUILD_CACHE:
        return dict(_SHAPING_BUILD_CACHE)
    text = ""
    exe = shutil.which("ffmpeg")
    if exe:
        for flag in ("-buildconf", "-version"):
            try:
                proc = subprocess.run([exe, "-hide_banner", flag], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                break
            if proc.returncode == 0 and proc.stdout.strip():
                text = proc.stdout
                break
    _SHAPING_BUILD_CACHE.update({"fribidi": "--enable-libfribidi" in text,
                                 "harfbuzz": "--enable-libharfbuzz" in text})
    return dict(_SHAPING_BUILD_CACHE)


def needs_shaping(script: str) -> bool:
    """Whether drawtext would render `script` wrongly on this build."""
    if script in SHAPING_SCRIPTS:
        return True
    return script in BIDI_SCRIPTS and not drawtext_shaping()["fribidi"]


def font_family_of_file(path: str) -> "Optional[str]":
    """The family name of a font FILE -- what libass wants, given a --font-file. `fc-scan` reads
    the file directly; without fontconfig the file stem is the honest best guess."""
    if not path or not os.path.isfile(path):
        return None
    exe = shutil.which("fc-scan")
    if exe:
        try:
            proc = subprocess.run([exe, "--format", "%{family[0]}", path], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().splitlines()[0].strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    return Path(path).stem


def char_script(ch: str) -> str:
    """The script of one character: one of SCRIPTS, or "latin" for anything else (including
    digits, punctuation and spaces -- they are measured and wrapped like Latin)."""
    cp = ord(ch)
    # 1.15: an emoji cluster is not Latin. detect_script() skips "emoji" the way it skips "latin",
    # so font resolution still follows the letters around it.
    if _is_emoji_char(ch):
        return "emoji"
    for name, ranges in _SCRIPT_RANGES:
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return "ja" if name == "kana" else ("zh" if name == "han" else name)
    return "latin"


def detect_script(text: str, lang: "Optional[str]" = None) -> str:
    """Which script `text` is written in, as one of SCRIPTS.

    Hangul wins for Korean, any kana makes the whole string Japanese (Japanese mixes kana and
    Han), Han alone is Chinese. Mixed text is decided by character count: the non-Latin script
    with the most characters wins, ties going to whichever appeared first, and text with no
    non-Latin characters at all is "latin". `lang` (a --lang/--language hint, or brand.json's
    `lang`) only resolves the one ambiguity the characters genuinely cannot: Han with no kana
    is Chinese by default but Japanese (or Korean hanja) when the caller says so.
    """
    counts: "Dict[str, int]" = {}
    order: "List[str]" = []
    kana = 0
    for ch in text or "":
        s = char_script(ch)
        if s in ("latin", "emoji"):
            continue
        if ord(ch) in range(0x3040, 0x3100) or ord(ch) in range(0x31F0, 0x3200) or ord(ch) in range(0xFF66, 0xFFA0):
            kana += 1
        if s not in counts:
            order.append(s)
        counts[s] = counts.get(s, 0) + 1
    if kana:  # Japanese: the Han characters in the same string are Japanese too
        counts["ja"] = counts.pop("ja", 0) + counts.pop("zh", 0)
        order = [s for s in order if s != "zh"]
    if not counts:
        return "latin"
    best = max(counts, key=lambda s: (counts[s], -order.index(s)))
    hint = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    if not kana and best == "zh" and hint in ("ja", "zh", "ko"):
        return hint  # Han-only text: only the caller knows whether it is Chinese, Japanese or hanja
    return best


_SCRIPT_FONT_CACHE: "Dict[Tuple[str, Optional[str]], Optional[Tuple[str, str]]]" = {}


def _fc_list_fonts(fc_lang: str) -> "Optional[List[Tuple[str, List[str]]]]":
    """(file, families) for every font fontconfig says covers `fc_lang`.

    `[]` means fontconfig answered and nothing covers the language; `None` means it could not be
    asked at all (no `fc-list` on PATH, or it failed/timed out) -- the difference between
    "missing" and "unknown", which the caller must not collapse: unknown is not a refusal.
    """
    exe = shutil.which("fc-list")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, f":lang={fc_lang}", "file", "family"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    out = []
    for line in proc.stdout.splitlines():
        if ": " not in line:
            continue
        path, _, families = line.partition(": ")
        path = path.strip()
        if not path or not os.path.exists(path):
            continue
        names = [f.replace("\\-", "-").strip() for f in families.split(",") if f.strip()]
        out.append((path, names or [Path(path).stem]))
    return out


def _family_rank(families: "Sequence[str]", preferred: "Sequence[str]") -> int:
    for i, want in enumerate(preferred):
        w = want.lower()
        if any(f.lower().startswith(w) for f in families):
            return i
    return len(preferred)


def _script_font_entry(script: str, family_hint: "Optional[str]" = None) -> "Optional[Tuple[str, str]]":
    key = (script, family_hint)
    if key in _SCRIPT_FONT_CACHE:
        return _SCRIPT_FONT_CACHE[key]
    _SCRIPT_FONT_CACHE[key] = result = _script_font_uncached(script, family_hint)
    return result


FC_UNKNOWN = "unknown"  # sentinel: fontconfig could not be asked (absent or failing), not "no font"


def _script_font_uncached(script: str, family_hint: "Optional[str]" = None):
    """(file, family), None when nothing covers `script`, or FC_UNKNOWN when it cannot be asked."""
    if script not in FC_LANG:
        return None
    if platform.system() == "Windows":
        fonts = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        for name, family in WINDOWS_FONTS.get(script, []):
            if (fonts / name).exists():
                return str(fonts / name), family
        return None
    preferred = list(PREFERRED_FAMILIES.get(script, []))
    if family_hint:
        preferred.insert(0, family_hint)
    candidates = _fc_list_fonts(FC_LANG[script])
    if candidates is None:
        return FC_UNKNOWN
    if not candidates:
        return None
    scored = []
    for path, families in candidates:
        joined = " ".join(families).lower()
        stem = Path(path).stem.lower()
        # "Unifont Sample" is fontconfig's tofu-with-hex-digits fallback: it "covers" every script
        # by drawing the code point, which is exactly the unreadable result this feature exists to
        # avoid -- it is only ever chosen when nothing else covers the script at all. A *Mono* face
        # is legible but wrong for a caption band, so it sorts after every proportional one.
        last_resort = 1 if "unifont" in joined else 0
        mono = 1 if "mono" in joined else 0
        # regular weights before Bold/Italic/Oblique cuts, so a default caption is not bold by accident
        styled = 1 if any(k in stem for k in ("bold", "italic", "oblique", "light", "thin", "black")) else 0
        scored.append((last_resort, _family_rank(families, preferred), mono, styled, path, families[0]))
    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3], row[4]))
    best = scored[0]
    return best[4], best[5]


def font_for_script(script: str, family_hint: "Optional[str]" = None) -> "Optional[str]":
    """A font FILE path that covers `script`, or None when this machine has none.

    Linux/macOS ask fontconfig (`fc-list :lang=xx file family`) and rank what it reports by the
    PREFERRED_FAMILIES table; Windows has no fontconfig, so the known system files are probed by
    name. Cached per process: a caption job resolves the same script for every cue.
    """
    entry = _script_font_entry(script, family_hint)
    return entry[0] if entry and entry is not FC_UNKNOWN else None


def font_family_for_script(script: str, family_hint: "Optional[str]" = None) -> "Optional[str]":
    """The family NAME of font_for_script()'s file -- what libass wants in an ASS Fontname."""
    entry = _script_font_entry(script, family_hint)
    return entry[1] if entry and entry is not FC_UNKNOWN else None


def script_font_status(script: str) -> str:
    """"available" (a font file covers `script`), "missing" (fontconfig answered, none does) or
    "unknown" (there is no working fontconfig to ask). Only "missing" is a refusal."""
    entry = _script_font_entry(script)
    if entry is FC_UNKNOWN:
        return "unknown"
    return "available" if entry else "missing"


def font_covers_script(font_name: str, script: str) -> bool:
    """Whether the installed family `font_name` actually carries glyphs for `script`.

    `fc-match` cannot answer this: given a family that IS installed it returns that family
    whatever `:lang=` asks for (verified -- `fc-match "DejaVu Sans:lang=zh-cn"` answers
    "DejaVu Sans", which has no Han glyphs at all). `fc-list :lang=xx:family=<name>` does: it
    lists only files that satisfy BOTH, so an empty listing is the proof of no coverage. Unknown
    (no fontconfig at all) counts as covering: a warning nobody can verify is worse than none.
    """
    if script not in FC_LANG or not font_name:
        return True
    exe = shutil.which("fc-list")
    if not exe:
        return True
    try:
        proc = subprocess.run([exe, f":lang={FC_LANG[script]}:family={font_name}", "file"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


# Named flags differ per tool: overlay.py and graphics.py take a font FILE, caption.py takes a
# directory of faces plus the family name -- naming a flag the tool does not have is worse than
# naming none, so the hint says both (review 10).
FONT_FLAG_HINT = "pass a font file (--font-file on overlay.py/graphics.py, --fonts-dir with --font on caption.py)"


FONT_INSTALL_HINT = ("install fonts-noto-cjk / fonts-noto-core (apt), "
                     "brew install --cask font-noto-sans-cjk / font-noto-sans-arabic (mac), or "
                     + FONT_FLAG_HINT)


def fonts_dir_covers_script(fonts_dir: str, script: str) -> "Optional[bool]":
    """Does any font under `fonts_dir` cover `script`? None when it cannot be checked.

    `--fonts-dir` says "also look here", not "this exact face", so it must not switch the
    coverage guarantee off. fontconfig's `fc-scan` reads the files directly (no cache, no
    installed-font database), which is exactly the question: `%{lang}` lists the languages each
    face claims.
    """
    if script not in FC_LANG or not fonts_dir or not os.path.isdir(fonts_dir):
        return None
    exe = shutil.which("fc-scan")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "--format", "%{lang}\n", fonts_dir],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    want = FC_LANG[script].lower()
    for line in proc.stdout.splitlines():
        if want in [tag.strip().lower() for tag in line.split("|")]:
            return True
    return False


def script_font_for_text(text: str, *, lang: "Optional[str]" = None, font: "Optional[str]" = None,
                         font_explicit: bool = False, font_file: "Optional[str]" = None,
                         fonts_dir: "Optional[str]" = None
                         ) -> "Tuple[str, Optional[str], Optional[str]]":
    """(script, font file, family) to draw `text` with, resolving by script when nothing explicit
    was asked for.

    Returns (script, None, None) when the caller's own choice stands: Latin text, an explicit
    --font-file, an explicit --font (which is kept even when fontconfig says it does not cover
    the script -- with one info line saying so, because overriding a user's stated font silently
    is worse than a warning), or a --fonts-dir that does carry the script. Otherwise the resolved
    file is returned with ONE info line naming it.

    A script fontconfig says nothing covers is a failed job (tofu is not a delivery). A machine
    with no working fontconfig at all answers "unknown", not "missing": the job continues with
    the caller's font -- libass and drawtext still have their own font backends -- and one info
    line says the coverage could not be verified.
    """
    script = detect_script(text or "", lang)
    if script == "latin":
        return script, None, None
    if font_file:
        return script, None, None
    if font_explicit and font:
        if not font_covers_script(font, script):
            info(f"font: '{font}' does not cover {LANGUAGE_NAMES[script]} text on this machine; keeping it as asked "
                 f"(drop --font, or {FONT_FLAG_HINT}, to pick one by script automatically)")
        return script, None, None
    if fonts_dir:
        covered = fonts_dir_covers_script(fonts_dir, script)
        if covered:
            return script, None, None
        if covered is None:
            info(f"font: could not verify that {fonts_dir} covers {LANGUAGE_NAMES[script]} text "
                 "(no fc-scan on this machine); using it as given")
            return script, None, None
        info(f"font: no face in {fonts_dir} covers {LANGUAGE_NAMES[script]} text; "
             "picking one by script instead (the directory is still searched first)")
    entry = _script_font_entry(script)
    if entry is FC_UNKNOWN:
        info(f"font: could not verify that this machine can render {LANGUAGE_NAMES[script]} text "
             "(no working fontconfig); rendering with the font as given -- "
             "doctor --json .fonts.scripts reports what is known")
        return script, None, None
    if not entry:
        die(f"no installed font covers {LANGUAGE_NAMES[script]} text on this machine — {FONT_INSTALL_HINT}", kind="input")
    info(f"font: {entry[0]} (covers {script})")
    return script, entry[0], entry[1]


def escape_drawtext(text: str) -> str:
    """Escape a FONT NAME for a single-quoted drawtext option value (`font='<this>'`).

    Since 1.15 this is no longer the route for drawn TEXT -- use drawtext_text_opts(), which puts
    the text in a file and keeps `\'` and `%` verbatim. It remains the escape for the font-name
    fallback, where the value is a family name that never legitimately contains a quote or a
    percent sign.

    Every ffmpeg filter-graph special character (`\\ : % , [ ] ;`) needs a backslash escape
    regardless of the surrounding quotes -- the graph parser still splits on an unescaped `,`/`;`
    or ends an option list on an unescaped `:`/`[`/`]` even while "inside" a quoted value. The
    quote character itself has no reliable backslash escape at all: `\\'` and the POSIX shell
    close-insert-reopen trick both parse fine in a simple `-vf` chain but silently corrupt a
    `-filter_complex` chain that uses explicit `[label]` pads (confirmed by rendering the result:
    trailing option names leak into the picture as literal text). `%` has the same problem as far
    as drawtext's own expansion scanner is concerned. Both are therefore dropped here rather than
    escaped -- which is exactly why drawn text no longer comes through this function.
    """
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return (
        text.replace("'", "")
        .replace("%", "")
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def drawtext_text_opts(text: str, tmpdir: "Optional[str]" = None) -> str:
    """`textfile=<path>:expansion=none` for drawtext -- the one route that is provably safe for
    every character on every build shape this repo uses.

    The filter-graph parser never sees the text at all: only the PATH is parsed, and
    escape_filter_path() already handles that. `expansion=none` switches off drawtext's own
    `%{...}` scanner, which is the reason `%` was unsafe (a bare `\%` logs "Stray %" on one build
    and fails the whole filter chain on another). With the scanner off, `'`, `%`, `:`, `,`, `[`,
    `]`, `;` and `\` all reach the picture verbatim -- 1.15 fixes `overlay.py --text "it's 100%
    done"` losing both characters. Control characters are still stripped: a one-line burnt-in
    label has no use for them.

    The file is UTF-8, mode 0600, in a private per-run directory (see _drawtext_tmpdir) that is
    removed when the process ends. It is *registered* here and written by run() only if the
    command about to run actually names it, so --dry-run and the ASS route write nothing; a
    printed plan therefore names a path that no longer exists once the run is over, which is the
    same promise every other temp file in this skill makes.
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text or "")
    import hashlib
    name = "t_" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16] + ".txt"
    if tmpdir is None:
        tmpdir = _drawtext_tmpdir(create=not STATE.dry_run)
    path = os.path.join(tmpdir, name)
    _DRAWTEXT_PENDING[path] = cleaned
    return f"textfile={escape_filter_path(path)}:expansion=none"


# --------------------------------------------------------------- caption line breaking (1.16)
# Lifted out of caption.py in 1.16.0 so graphics.py can wrap the same way (caption.py keeps the
# names it exported, re-imported from here). The whole breaker is pure: a string in, a list of
# lines out, no subprocess and no probe, which is what makes the eval regression corpus cheap
# to lock down in unit tests.

# How much of the frame width a caption line may use. libass's own default SRT margins are 10 of a
# 384-wide script (2.6 % a side); 5 % a side is the safe area every platform check in this repo uses.
SAFE_WIDTH_FRACTION = 0.9
# ORPHAN_MIN_EM: one full-width CJK/Thai character plus a hair. A last line narrower than this is a
# single stranded character -- eval 14's th1 (a lone 'ล') and dl3 (a lone '行').
ORPHAN_MIN_EM = 1.1

WRAP_MODES = ("phrase", "measured")

# R3's Japanese preference table. These are *preferences* applied only among positions that
# already fit the line, so the table can never make a line too wide or change the line count.
#
# JA_PARTICLES is a "do not strand at the start of a line" table, which is the direction kinsoku
# practice actually goes: a particle is enclitic -- it attaches to the word BEFORE it and marks
# that word's role -- so a line beginning with は or が reads as a fragment torn off its phrase.
# A break AFTER a particle is therefore preferred (the particle stays with what it marks) and a
# break BEFORE one is forbidden. The list is the eight case/topic particles named in the 1.16.0
# task brief (は が を に で と の へ) plus も や から まで より, which a reader of Japanese would
# add for the same reason. It is a judgement call with no upstream source; treat it as tunable
# data, not as grammar.
JA_PARTICLES = "はがをにでとのへもや"              # a break AFTER one of these is preferred, BEFORE one forbidden
# The multi-character members of the same table. They are matched as whole strings against the
# text on each side of a candidate break -- putting them in the character string above turned
# か, ら, ま, で, よ and り into one-character particles of their own, which none of them is.
JA_PARTICLE_WORDS = ("から", "まで", "より")
JA_SENTENCE_END = "。、！？」』）"                  # a break AFTER one of these is preferred
# Characters that may never start a line: small kana, the prolonged sound mark, closing brackets
# and the Japanese punctuation that hangs on the end of the line before it.
JA_NO_LINE_START = "ぁぃぅぇぉっゃゅょァィゥェォッャュョーヽヾゝゞ、。！？）」』】〕》’”％"
JA_NO_LINE_END = "（「『【〔《‘“"                   # ... and the ones that may never end a line

# R4. Function words belong to the phrase that FOLLOWS them: an article or preposition begins the
# noun phrase it governs, so a break before one is the good break (the word opens the next line
# with its phrase) and a break after one is the bad break (it is stranded at the end of a line,
# away from what it governs). Both directions are scored, which is what makes the rule decide
# rather than merely veto. Frozen data, matched case-folded on the atom with its punctuation
# stripped; six languages because those are the Latin-script languages the eval corpus covers. A
# word in several sets means the same thing structurally in each, so the union is used when no
# --lang was given.
FUNCTION_WORDS = {
    "en": {"a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "by", "from", "and",
           "or", "as", "is", "it", "its", "this", "that", "into", "than", "but", "so"},
    "es": {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en", "con",
           "por", "para", "y", "o", "que", "su", "sus", "lo", "se", "es"},
    "pt": {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na",
           "nos", "nas", "com", "por", "para", "e", "que", "se", "ao", "aos"},
    "fr": {"le", "la", "les", "un", "une", "de", "du", "des", "à", "au", "aux", "en", "dans",
           "et", "ou", "que", "qui", "ce", "ces", "son", "sa", "ses", "par", "pour", "avec", "sur"},
    "de": {"der", "die", "das", "ein", "eine", "einen", "einem", "einer", "den", "dem", "des",
           "zu", "in", "im", "auf", "mit", "und", "oder", "von", "vom", "für", "aus", "an"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "di", "del", "della", "da",
           "in", "nel", "con", "per", "e", "che", "su", "al", "ai"},
}
_FUNCTION_WORDS_ANY = frozenset().union(*FUNCTION_WORDS.values())

# Penalty scores. Only the ordering matters; 1.0 means "never choose this if anything else fits".
PENALTY_FORBIDDEN = 1.0
PENALTY_OKURIGANA = 0.9       # between a kanji stem and the hiragana that inflects it
PENALTY_FUNCTION_WORD = 0.8   # R4: the line before the break ends in an article/preposition
PENALTY_IDEOGRAPHS = 0.6      # between two kanji: no evidence either way, mildly discouraged
PENALTY_NEUTRAL = 0.5         # between two content words, or two characters with nothing to say
PENALTY_FUNCTION_WORD_START = 0.2  # R4: the next line opens with the article/preposition it governs
PENALTY_PARTICLE = 0.2        # R3: after a particle, so the particle stays with the word it marks
PENALTY_SENTENCE_END = 0.0    # R3: after 。、！？ -- the one break a reader expects

_HYPHENS = ("-", "‐")    # ‑ (non-breaking hyphen) is deliberately NOT here


def _atoms(line: str) -> "List[Tuple[str, bool]]":
    """Break a line into the smallest pieces a wrap may separate -- one atom per CJK/Thai
    character, one per emoji cluster, one per whitespace-delimited word otherwise -- each with
    whether a space stood before it in the original. The flag is what puts the text back together
    exactly as written: "Hello 世界" keeps its space, "世界です" gains none."""
    out: "List[Tuple[str, bool]]" = []
    word = ""
    spaced = False        # a space stands before the atom being built
    pending = False       # a space stands before the NEXT atom
    attach_next = False   # a leading Thai/Lao vowel is waiting for its base consonant
    # An emoji cluster is one atom: a wrap must never land inside a ZWJ sequence, a flag pair or
    # between a base and its skin-tone modifier (the same rule combining marks already follow).
    clusters = {i: len(cl) for i, cl in emoji_clusters(line)}
    i = 0
    while i < len(line):
        ch = line[i]
        if i in clusters:
            cluster = line[i:i + clusters[i]]
            if word:
                out.append((word, spaced))
                word = ""
            out.append((cluster, pending))
            pending = False
            attach_next = False
            i += clusters[i]
            continue
        i += 1
        if char_script(ch) in NO_SPACE_SCRIPTS:
            if word:
                out.append((word, spaced))
                word = ""
            if out and not pending and _is_katakana_run(ch) and _is_katakana_run(out[-1][0][-1]):
                # a katakana word (タイミング, コンピューター) is one atom: eval 17 saw タイ|ミング
                out[-1] = (out[-1][0] + ch, out[-1][1])
            elif out and (attach_next or _is_mark(ch)):
                # never break between a base and the mark (or the leading vowel) that belongs to
                # it: the line would start with an orphaned tone mark or vowel sign
                out[-1] = (out[-1][0] + ch, out[-1][1])
            else:
                out.append((ch, pending))
                pending = False
            attach_next = ord(ch) in LEADING_VOWELS
        elif ch.isspace():
            if word:
                out.append((word, spaced))
                word = ""
            pending = True
        else:
            if not word:
                spaced, pending = pending, False
            word += ch
    if word:
        out.append((word, spaced))
    return out


def _split_hyphens(atoms: "List[Tuple[str, bool]]") -> "List[Tuple[str, bool]]":
    """R1's one addition to the atom list: a hyphenated token may break *after* its hyphen.

    "end-to-end" becomes `end-` / `to-` / `end`, each piece carrying the space flag of the token
    it came from for the first piece and False for the rest, so _join() puts it back with no space
    at all. A hyphen that is the first or last character of the token (`-5`, `well-`) is never a
    break point: the guard is that both sides must be non-empty."""
    out: "List[Tuple[str, bool]]" = []
    for atom, spaced in atoms:
        if len(atom) < 3 or not any(h in atom[1:-1] for h in _HYPHENS):
            out.append((atom, spaced))
            continue
        piece = ""
        first = True
        for i, ch in enumerate(atom):
            piece += ch
            if ch in _HYPHENS and 0 < i < len(atom) - 1:
                out.append((piece, spaced if first else False))
                piece = ""
                first = False
        if piece:
            out.append((piece, spaced if first else False))
    return out


def _join(left: str, atom: str, spaced: bool) -> str:
    """Put an atom back on a line, restoring the space that stood before it."""
    if not left:
        return atom
    return left + (" " if spaced else "") + atom


def _break_spaced(first: str, second: str) -> bool:
    """Did a space stand at the break between these two wrapped lines? Only spaced scripts put one
    there -- a CJK/Thai break sits between two characters that were written with nothing between
    them, and re-joining them with a space would insert a character the cue never had."""
    if not first or not second:
        return False
    return char_script(first[-1]) not in NO_SPACE_SCRIPTS and char_script(second[0]) not in NO_SPACE_SCRIPTS \
        and char_script(first[-1]) != "emoji" and char_script(second[0]) != "emoji"


def _is_kana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x30FF


def _is_katakana_run(ch: str) -> bool:
    """Katakana proper plus the prolonged-sound mark: the characters one loan word is made of."""
    cp = ord(ch)
    return (0x30A1 <= cp <= 0x30FA) or cp == 0x30FC or (0x31F0 <= cp <= 0x31FF) or (0xFF66 <= cp <= 0xFF9F)


def _is_hiragana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x309F


def _is_ideograph(ch: str) -> bool:
    cp = ord(ch)
    return 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF


def _is_weak_line(line: str) -> "bool":
    """A line no reader should be given on its own (R2).

    1.15 asked only "is the last line one atom narrower than ORPHAN_MIN_EM", which a full-width
    character passes: dl3 still showed a lone `2` and a stranded `行`. Three cases instead, any of
    which makes a line too thin to stand alone:
      - a single character narrower than ORPHAN_MIN_EM (1.15's rule, kept);
      - nothing but digits, punctuation and symbols, at most two characters ("2", "--");
      - a single kana, whatever its width -- a kana is a full em and passes the width test, but a
        line holding one is a syllable, not a word.
    """
    stripped = (line or "").strip()
    if not stripped:
        return True
    if len(stripped) == 1 and text_width_em(stripped) < ORPHAN_MIN_EM:
        return True
    if len(stripped) <= 2 and all(unicodedata.category(c)[0] in "NPS" for c in stripped):
        return True
    if len(stripped) == 1 and char_script(stripped) == "ja" and _is_kana(stripped):
        return True
    return False


def _function_words(lang: "Optional[str]") -> "frozenset":
    """R4's table for this language. An unknown or absent language gets the union of the six sets:
    a token that appears in several of them is the same kind of word in each, which is why the
    rule is a penalty and not a refusal."""
    key = (lang or "").strip().lower().split("-")[0]
    if key in FUNCTION_WORDS:
        return frozenset(FUNCTION_WORDS[key])
    return _FUNCTION_WORDS_ANY


def _bare_word(atom: str) -> str:
    return "".join(c for c in (atom or "") if c.isalpha() or c == "'").strip("'").lower()


def _particle_starts(text: str) -> bool:
    """Does `text` begin with a particle -- one character, or one of the two-character ones?"""
    if not text:
        return False
    return text[0] in JA_PARTICLES or text.startswith(JA_PARTICLE_WORDS)


def _particle_ends(text: str) -> bool:
    """Does `text` end with a particle? `から` counts, a bare `ら` does not."""
    if not text:
        return False
    return text[-1] in JA_PARTICLES or text.endswith(JA_PARTICLE_WORDS)


def break_penalty(prev_char: str, next_char: str, lang: "Optional[str]" = None,
                  before: str = "", after: str = "") -> float:
    """How bad a break between these two characters is, 0.0 (preferred) to 1.0 (forbidden).

    Only consulted among break positions that already fit `max_em`, so a preference can never
    widen a line or change the line count. Japanese gets the particle half of the table -- a break
    AFTER a particle is preferred and a break BEFORE one forbidden, because a particle attaches to
    the word before it; Chinese gets only the sentence-end and forbidden halves, because particles
    are Japanese grammar.

    `before`/`after` are the text on each side of the break when the caller has it, which is what
    lets the two-character particles (から/まで/より) be matched as words. Without them only the
    single-character table applies."""
    if not prev_char or not next_char:
        return PENALTY_NEUTRAL
    script = (lang or "").strip().lower().split("-")[0]
    if script not in ("ja", "zh"):
        # A kana on either side settles it: only Japanese has them, and char_script() reads a bare
        # Han character as Chinese, which used to switch the particle rules off for exactly the
        # break they exist to judge (`...が|決まる` -- kana before, kanji after).
        if _is_kana(prev_char) or _is_kana(next_char):
            script = "ja"
        else:
            script = char_script(next_char)
            if script not in ("ja", "zh"):
                script = char_script(prev_char)
    if next_char in JA_NO_LINE_START or prev_char in JA_NO_LINE_END or _is_mark(next_char):
        return PENALTY_FORBIDDEN
    if script not in ("ja", "zh"):
        return PENALTY_NEUTRAL
    if prev_char in JA_SENTENCE_END:
        return PENALTY_SENTENCE_END
    if script == "ja" and _particle_starts(after or next_char):
        # a particle may not open a line: it belongs to the word before it (kinsoku)
        return PENALTY_FORBIDDEN
    if script == "ja" and _particle_ends(before or prev_char):
        return PENALTY_PARTICLE
    if script == "ja" and _is_ideograph(prev_char) and _is_hiragana(next_char):
        # okurigana: 決|まる is inside a word even though neither half is a "word" on its own
        return PENALTY_OKURIGANA
    if _is_ideograph(prev_char) and _is_ideograph(next_char):
        return PENALTY_IDEOGRAPHS
    return PENALTY_NEUTRAL


def _cut_penalty(atoms: "Sequence[Tuple[str, bool]]", cut: int, lang: "Optional[str]") -> float:
    """The penalty of breaking `atoms` before index `cut`."""
    prev_atom = atoms[cut - 1][0]
    next_atom = atoms[cut][0]
    if not prev_atom or not next_atom:
        return PENALTY_NEUTRAL
    if atoms[cut][1]:
        # a space stood here: a spaced script, so R4 is the rule that applies, in both directions
        if all(not ch.isalnum() for ch in next_atom):
            return PENALTY_FORBIDDEN   # never strand punctuation at the start of a line
        words = _function_words(lang)
        if _bare_word(prev_atom) in words:
            return PENALTY_FUNCTION_WORD        # stranded at the end of a line, away from its noun
        if _bare_word(next_atom) in words:
            return PENALTY_FUNCTION_WORD_START  # opens the next line with the phrase it governs
        return PENALTY_NEUTRAL
    if prev_atom.endswith(_HYPHENS):
        return PENALTY_NEUTRAL         # R1: a hyphen is a legitimate break point
    # the text on each side, so a two-character particle (から/まで/より) is seen as one
    before = "".join(a for a, _sp in atoms[:cut])
    after = "".join(a for a, _sp in atoms[cut:])
    return break_penalty(prev_atom[-1], next_atom[0], lang, before=before, after=after)


def best_break(atoms: "Sequence[Tuple[str, bool]]", max_em: float,
               lang: "Optional[str]" = None) -> "Optional[int]":
    """The index to break `atoms` at so they become two lines, or None when none fits.

    Among every position whose two halves both fit `max_em`, the one minimising
    (penalty, widest line, |width difference|) wins: R1-R4 choose first, and 1.15's
    minimise-the-widest-line rule breaks the ties it used to decide alone."""
    best = None
    for cut in range(1, len(atoms)):
        a = b = ""
        for atom, sp in atoms[:cut]:
            a = _join(a, atom, sp)
        for atom, sp in atoms[cut:]:
            b = _join(b, atom, sp)
        wa, wb = text_width_em(a), text_width_em(b)
        if max(wa, wb) > max_em:
            continue
        if _is_weak_line(a) or _is_weak_line(b):
            continue
        key = (_cut_penalty(atoms, cut, lang), max(wa, wb), abs(wa - wb))
        if best is None or key < best[0]:
            best = (key, cut)
    return None if best is None else best[1]


def _fix_orphans(lines: "List[str]", max_em: float) -> "List[str]":
    """No last line that is a single stranded atom.

    Greedy wrapping leaves one character alone whenever the line before it filled exactly: eval 14
    produced a Thai cue ending in a lone `ล` and a Japanese one ending in a lone `行`. While the
    last line is one atom narrower than ORPHAN_MIN_EM, the last atom of the line above moves down
    onto it -- but only while the result still fits and the line above does not become an orphan
    itself, so a two-word cue is never made worse."""
    lines = list(lines)
    for _ in range(len(lines)):
        if len(lines) < 2:
            break
        tail = _atoms(lines[-1])
        if len(tail) != 1 or text_width_em(lines[-1]) >= ORPHAN_MIN_EM:
            break
        prev = _atoms(lines[-2])
        if len(prev) < 2:
            break
        moved, spaced = prev[-1]
        new_prev = ""
        for atom, sp in prev[:-1]:
            new_prev = _join(new_prev, atom, sp)
        new_last = _join(moved, tail[0][0], _break_spaced(lines[-2], lines[-1]))
        if text_width_em(new_last) > max_em or text_width_em(new_prev) < ORPHAN_MIN_EM:
            break
        lines[-2], lines[-1] = new_prev, new_last
    return lines


def _fix_weak_lines(lines: "List[str]", max_em: float) -> "List[str]":
    """R2, generalised: _fix_orphans run at *every* boundary, against _is_weak_line.

    1.15 only ever looked at the last line, so a stranded digit or kana in the middle of a
    three-line cue survived. Walking upward from the last line, while a line is weak the last atom
    of the line above moves down onto it -- with 1.15's two guards intact (the result must still
    fit, and the line above must not itself become weak), so the line count never changes."""
    lines = list(lines)
    for i in range(len(lines) - 1, 0, -1):
        for _ in range(len(lines)):
            if not _is_weak_line(lines[i]):
                break
            prev = _atoms(lines[i - 1])
            if len(prev) < 2:
                break
            moved, _spaced = prev[-1]
            new_prev = ""
            for atom, sp in prev[:-1]:
                new_prev = _join(new_prev, atom, sp)
            new_last = _join(moved, lines[i], _break_spaced(lines[i - 1], lines[i]))
            if text_width_em(new_last) > max_em or _is_weak_line(new_prev) \
                    or text_width_em(new_prev) < ORPHAN_MIN_EM:
                break
            lines[i - 1], lines[i] = new_prev, new_last
    return lines


def _rebalance(lines: "List[str]", max_em: float) -> "List[str]":
    """Move each break to the one that minimises the widest line of the pair, without changing the
    line count.

    Greedy wrapping fills line 1 to the brim and leaves line 2 short, which is what split eval 14's
    `"A third line the tool times for me"` mid-phrase. Only spaced scripts are rebalanced: a
    non-spaced script has no phrase structure in its atom list, so moving the break there only
    moves the ragged edge. A break is never placed before a punctuation-only atom."""
    if len(lines) < 2:
        return lines
    out = list(lines)
    for i in range(len(out) - 1):
        first, second = out[i], out[i + 1]
        tail_atoms = _atoms(second)
        if tail_atoms:
            tail_atoms[0] = (tail_atoms[0][0], _break_spaced(first, second))
        atoms = _atoms(first) + tail_atoms
        if not atoms or any(char_script(ch) in NO_SPACE_SCRIPTS for ch in first + second):
            continue
        best = None
        for cut in range(1, len(atoms)):
            if not atoms[cut][1]:
                continue  # only break where a space stood
            if all(not ch.isalnum() for ch in atoms[cut][0]):
                continue  # never strand punctuation at the start of a line
            a = b = ""
            for atom, sp in atoms[:cut]:
                a = _join(a, atom, sp)
            for atom, sp in atoms[cut:]:
                b = _join(b, atom, sp)
            wa, wb = text_width_em(a), text_width_em(b)
            if max(wa, wb) > max_em:
                continue
            key = (max(wa, wb), abs(wa - wb))
            if best is None or key < best[0]:
                best = (key, a, b)
        if best is not None:
            out[i], out[i + 1] = best[1], best[2]
    return out


def _rebalance_phrase(lines: "List[str]", max_em: float, lang: "Optional[str]") -> "Tuple[List[str], int]":
    """_rebalance with R1-R4 deciding, for every script rather than spaced ones only.

    Returns the new lines and how many breaks a phrase rule moved away from the position 1.15's
    widest-line rule alone would have chosen -- the `phrase_breaks` count in the result."""
    if len(lines) < 2:
        return list(lines), 0
    out = list(lines)
    moved = 0
    for i in range(len(out) - 1):
        first, second = out[i], out[i + 1]
        tail_atoms = _atoms(second)
        if tail_atoms:
            tail_atoms[0] = (tail_atoms[0][0], _break_spaced(first, second))
        atoms = _split_hyphens(_atoms(first) + tail_atoms)
        if len(atoms) < 2:
            continue
        cut = best_break(atoms, max_em, lang)
        if cut is None:
            continue
        a = b = ""
        for atom, sp in atoms[:cut]:
            a = _join(a, atom, sp)
        for atom, sp in atoms[cut:]:
            b = _join(b, atom, sp)
        if (a, b) != (first, second):
            moved += 1
        out[i], out[i + 1] = a, b
    return out, moved


def _greedy_chunks(raw: str, max_em: float) -> "List[str]":
    """The greedy fill on its own: the line count every mode must keep."""
    current = ""
    chunk: "List[str]" = []
    for atom, spaced in _atoms(raw):
        candidate = _join(current, atom, spaced)
        if current and text_width_em(candidate) > max_em:
            chunk.append(current)
            current = atom
        else:
            current = candidate
    if current:
        chunk.append(current)
    return chunk


def _balance(chunk: "List[str]", max_em: float, mode: str, lang: "Optional[str]") -> "List[str]":
    """The post-passes for one greedy chunk, in the mode's own order. Never changes the count:
    a pass that would is discarded, exactly as 1.15 did."""
    if len(chunk) < 2:
        return chunk
    if mode == "measured":
        fixed = _fix_orphans(chunk, max_em)
        rebalanced = _rebalance(fixed, max_em)
    else:
        fixed = _fix_weak_lines(_fix_orphans(chunk, max_em), max_em)
        rebalanced, _moved = _rebalance_phrase(fixed, max_em, lang)
        rebalanced = _fix_weak_lines(rebalanced, max_em)
    if len(rebalanced) == len(chunk):
        return rebalanced
    return fixed if len(fixed) == len(chunk) else chunk


def wrap_text(text: str, max_em: float, *, balance: bool = True, mode: str = "phrase",
              lang: "Optional[str]" = None) -> "List[str]":
    """Wrap `text` to lines no wider than `max_em` em, keeping the manual breaks it already has.

    An atom wider than the whole line (one very long word) is left alone on its line rather than
    cut mid-word: an over-long line is readable, a chopped word is not.

    `mode="phrase"` (the default since 1.16) then applies the four phrase rules -- never inside a
    word or across a hyphen's wrong side (R1), no line that is a lone digit, punctuation or kana
    (R2), Japanese/Chinese breaks preferred at sentence ends and after particles, never before one
    and never inside a word (R3), and an article or preposition kept with the phrase it governs by
    preferring the break before it and avoiding the break after it (R4). `mode="measured"` is
    1.15's behaviour exactly: no one-character orphan line, and a break chosen only to minimise the
    widest line. Neither mode ever changes the number of lines the greedy fill produced.
    """
    lines: "List[str]" = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        chunk = _greedy_chunks(raw, max_em)
        lines.extend(_balance(chunk, max_em, mode, lang) if balance else chunk)
    return lines or [text]
def wrap_variants(text: str, max_em: float, *, mode: str = "phrase",
                  lang: "Optional[str]" = None) -> "Tuple[List[str], List[str], List[str]]":
    """`(wrapped, greedy, measured)` for one cue from a single greedy fill.

    layout_cues needs all three -- `wrapped` is what is burnt in, `greedy` is what `rebalanced`
    counts against and `measured` what `phrase_breaks` counts against -- and used to call
    wrap_text() three times, re-running the atomiser and the greedy fill each time. The fill is
    the same for every mode, so it is done once here and only the post-passes are repeated.
    `measured` is the same list object as `wrapped` when that is already the mode.
    """
    wrapped: "List[str]" = []
    greedy: "List[str]" = []
    measured: "List[str]" = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        chunk = _greedy_chunks(raw, max_em)
        greedy.extend(chunk)
        wrapped.extend(_balance(list(chunk), max_em, mode, lang))
        measured.extend(chunk if mode == "measured" else _balance(list(chunk), max_em, "measured", None))
    if not greedy:
        greedy = [text]
    return (wrapped or [text], greedy, measured or [text])


# --- caption size that fits the cue (1.17) -------------------------------------------------
# The legibility floor: 4.5 % of the frame height, ass_units(0.045) = 13 against the 288-line
# ASS script grid. One floor for every destination -- 87 px of type on a 1920-tall frame, above
# the ~3.5 % where mobile legibility bottoms out and where the platforms' own caption UIs sit.
# Nothing per-platform is measured, so nothing per-platform is claimed. (The eval-17 cues happen
# to land exactly on it: 13 is the smallest size at which every one of them fits two lines.)
MIN_CAPTION_FRACTION = 0.045
ASS_SCRIPT_HEIGHT = 288  # caption.py's --size/--margin reference grid; mirrors _platforms


def line_em_for_size(size: float, play_w: "Optional[int]", play_h: "Optional[int]", *,
                     safe_fraction: float = SAFE_WIDTH_FRACTION,
                     script_height: int = ASS_SCRIPT_HEIGHT) -> "Optional[float]":
    """How many em fit on one caption line at `size`, or None without geometry.

    `size` is in ASS points against a `script_height`-line script (what libass's force_style
    uses), so the rendered pixel size is size * play_h / script_height. This is the one width
    formula: caption.py::max_line_em and fit_size() both call it.
    """
    if not play_w or not play_h or not size:
        return None
    size_px = size * play_h / float(script_height)
    if size_px <= 0:
        return None
    return (play_w * safe_fraction) / size_px


def fit_size(cues, *, size: int, min_size: "Optional[int]" = None, max_lines: int = 2,
             play_w: "Optional[int]" = None, play_h: "Optional[int]" = None,
             safe_fraction: float = SAFE_WIDTH_FRACTION, mode: str = "phrase",
             lang: "Optional[str]" = None, script_height: int = ASS_SCRIPT_HEIGHT,
             step: int = 1, scope: str = "file") -> "Dict[str, Any]":
    """The largest size in [min_size, size] at which every cue wraps to <= max_lines lines.

    Pure: strings and integers in, a dict out. No ffmpeg, no ffprobe, no I/O -- the caption size
    is a text-measurement decision, and measuring it must not need a subprocess.

    `cues` is an iterable of cue texts (or of (start, end, text) tuples, as caption.py holds
    them before layout). Returns
    {"size", "floor", "requested", "scope", "shrunk", "fits", "per_cue", "max_em", "steps"}.

    The search is a linear walk downwards, not a bisection, and deliberately so:
    len(wrap_text(t, max_em)) is NOT guaranteed monotone in max_em under the phrase rules -- a
    rebalance that is discarded at one width can be applied at the next -- and a non-monotone
    predicate breaks bisection. 24 -> 13 is at most twelve iterations of pure string work.

    `scope="cue"` returns one size per cue index in `per_cue`, with `size` the minimum of them;
    the caller writes a per-cue {\\fsN} override. The default is `scope="file"`: a caption track
    whose type size changes from cue to cue reads as a mistake, and one measured line width per
    file is what makes the wrap behaviour reproducible.
    """
    # `texts` stays parallel to `cues`: a blank cue becomes None rather than being dropped, so
    # per_cue[i] always refers to the caller's cue i. caption.py indexes layout by these keys.
    texts: "List[Optional[str]]" = []
    for cue in cues or []:
        if isinstance(cue, (tuple, list)):
            raw = cue[2] if len(cue) > 2 else cue[-1]
        else:
            raw = cue
        texts.append(raw if raw and str(raw).strip() else None)
    measurable = [t for t in texts if t is not None]
    requested = int(size)
    floor = int(min_size) if min_size is not None else ass_units_local(MIN_CAPTION_FRACTION,
                                                                      script_height)
    floor = max(1, min(floor, requested))
    step = max(1, int(step))
    result: "Dict[str, Any]" = {"size": requested, "floor": floor, "requested": requested,
                                "scope": scope, "shrunk": 0, "fits": True, "per_cue": {},
                                "max_em": None, "steps": 0}
    em_at = lambda sz: line_em_for_size(sz, play_w, play_h, safe_fraction=safe_fraction,
                                        script_height=script_height)
    base_em = em_at(requested)
    result["max_em"] = base_em
    if not measurable or base_em is None or max_lines < 1:
        # No geometry means no measurable width: leave the size exactly as asked.
        return result

    def lines_at(text: str, sz: int) -> int:
        em = em_at(sz)
        if em is None:
            return 1
        return len(wrap_text(text, em, mode=mode, lang=lang))

    over_at_requested = [t for t in measurable if lines_at(t, requested) > max_lines]
    result["shrunk"] = len(over_at_requested)

    def best_for(subset) -> "Tuple[int, bool]":
        """(largest size in [floor, requested] fitting every text in `subset`, did it fit)."""
        sz = requested
        while sz >= floor:
            result["steps"] += 1
            if all(lines_at(t, sz) <= max_lines for t in subset):
                return sz, True
            sz -= step
        return floor, all(lines_at(t, floor) <= max_lines for t in subset)

    if scope == "cue":
        per_cue = {}
        fits_all = True
        for i, t in enumerate(texts):
            if t is None:
                per_cue[i] = requested    # a blank cue draws nothing; it constrains nothing
                continue
            sz, ok = best_for([t])
            per_cue[i] = sz
            fits_all = fits_all and ok
        result["per_cue"] = per_cue
        sized = [v for i, v in per_cue.items() if texts[i] is not None]
        result["size"] = min(sized) if sized else requested
        result["fits"] = fits_all
    else:
        sz, ok = best_for(measurable)
        result["size"] = sz
        result["fits"] = ok
    result["max_em"] = em_at(result["size"])
    return result


def ass_units_local(fraction: float, script_height: int = ASS_SCRIPT_HEIGHT) -> int:
    """`fraction` of the frame height in ASS units. Mirrors _platforms.ass_units, kept here so
    _common.text stays importable without the scripts/ top level on sys.path."""
    return int(round(fraction * script_height))
