"""Fonts and scripts: the per-script font tables, script detection, fontconfig lookups
(fc-match / fc-list / fc-scan) and the font-for-this-text resolution the drawing tools use.
Split out of _common.text in the refactor after 1.17.3; every body is byte-identical.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from _common.emit import die, info, record_fallback, warn
from _common.emoji import _is_emoji_char


def default_font_file(font_name: str) -> Optional[str]:
    """Resolve `font_name` to a concrete on-disk font file, so a caller can tell drawtext
    `fontfile=<path>` instead of `font=<name>`, when possible (resolve_font()'s `file`).

    On some real Windows ffmpeg builds (winget's gyan.dev 9.x), drawtext's own fontconfig
    resolution crashes with an access violation whenever it has to resolve a font by family name
    -- with or without a valid fonts.conf on FONTCONFIG_FILE. `fontfile=` is the only form
    confirmed not to crash (#100), since it never touches fontconfig at all. On Windows the
    requested family is looked for by file name in the Fonts folder; a family that is not there
    falls back to a CJK system font (for a CJK-looking request) or Arial, a near-universally-present
    system font, instead of trying to resolve the requested family (which would crash the same way).

    On Linux/macOS this is best-effort and uses the real requested family: `fc-match` reports the
    same file fontconfig would resolve `font_name` to anyway, so a caller gets the identical font,
    just already resolved to a path -- fontfile= skips a redundant fontconfig lookup and equally
    sidesteps the same class of crash if it exists on some build there too, but the fallback below
    (returning None) is exercised routinely there, not just on failure.

    Returns None when nothing could be resolved (fc-match missing/unavailable, or no well-known
    Windows font file present); the caller falls back to font=<font_name>, the prior behaviour.
    """
    return resolve_font(font_name)["file"]


# generic fontconfig aliases: resolving one to a concrete family is what they are for, not a substitution
_GENERIC_FAMILIES = {"sans", "sansserif", "serif", "mono", "monospace", "cursive", "fantasy", "systemui", "emoji"}


def _family_key(name: "Optional[str]") -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def resolve_font(font_name: str) -> "Dict[str, object]":
    """default_font_file() with what it found: {file, family, substituted, via}. `substituted` is
    True when the file is not the requested family -- a Windows machine without it (a CJK system
    font or Arial instead), or fc-match answering with another family (fontconfig always answers
    something). `via` is windows_fonts or fc-match; file and family are None when nothing resolved."""
    none: "Dict[str, object]" = {"file": None, "family": None, "substituted": False, "via": None}
    if platform.system() == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        fonts = Path(windir) / "Fonts"
        # The requested family first: a file whose name starts with the family name with spaces
        # removed (Noto Sans CJK JP -> NotoSansCJKjp-Regular.otf, Meiryo -> meiryo.ttc), then the
        # common CJK system fonts when the request looks CJK (so Japanese text does not render as
        # boxes in Arial), and Arial only as the last resort.
        wanted = _family_key(font_name)
        try:
            files = sorted(fonts.iterdir()) if fonts.is_dir() else []
        except OSError:
            files = []
        if wanted:
            for f in files:
                stem = _family_key(f.stem)
                if f.suffix.lower() in (".ttf", ".otf", ".ttc") and stem.startswith(wanted):
                    return {"file": str(f), "family": font_name, "substituted": False, "via": "windows_fonts"}
        if any(k in wanted for k in ("cjk", "gothic", "mincho", "meiryo", "yugoth", "msgothic", "malgun", "simhei", "simsun", "jp", "kr", "sc", "tc")):
            for name in ("NotoSansCJKjp-Regular.otf", "NotoSansCJK-Regular.ttc", "meiryo.ttc", "YuGothM.ttc", "msgothic.ttc", "malgun.ttf", "msyh.ttc"):
                if (fonts / name).exists():
                    return {"file": str(fonts / name), "family": Path(name).stem, "substituted": bool(wanted), "via": "windows_fonts"}
        candidate = fonts / "arial.ttf"
        if candidate.exists():
            return {"file": str(candidate), "family": "Arial",
                    "substituted": bool(wanted) and wanted != "arial" and wanted not in _GENERIC_FAMILIES, "via": "windows_fonts"}
        return none
    exe = shutil.which("fc-match")
    if not exe:
        return none
    try:
        proc = subprocess.run([exe, "--format=%{file}\n%{family}\n", font_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return none
    if proc.returncode != 0:
        return none
    lines = proc.stdout.splitlines()
    path = lines[0].strip() if lines else ""
    if not (path and os.path.exists(path)):
        return none
    # fontconfig lists a face's family names comma-separated (localised names included); the
    # request is met when one of them is the requested family, or the request names a style of it
    families = [f.strip() for f in (lines[1] if len(lines) > 1 else "").split(",") if f.strip()]
    wanted = _family_key(font_name)
    met = (not wanted or wanted in _GENERIC_FAMILIES or not families
           or any(_family_key(f) and (wanted.startswith(_family_key(f)) or _family_key(f).startswith(wanted)) for f in families))
    return {"file": path, "family": families[0] if families else None, "substituted": not met, "via": "fc-match"}


def font_choice(asked: "Optional[str]", *, font_file: "Optional[str]" = None, script_file: "Optional[str]" = None,
                script_family: "Optional[str]" = None, renderer: str = "drawtext") -> "Dict[str, object]":
    """The font a text-drawing tool draws with, as its result's `font_used`: {asked, file, family,
    how, substituted}. `how`: font_file (the caller's own file), script (a font picked to cover the
    text's script, 1.12), resolved (the asked family resolved to a file: fc-match, or the Windows
    Fonts folder), by_name (no file resolved; ffmpeg/libass look the family up themselves, so the
    file is not known here). For libass (`renderer="libass"`) a resolved file is the one fontconfig
    picks for the family, which is what libass loads through fontconfig; on Windows libass is
    given the family by name, so nothing is resolved for it."""
    if font_file:
        return {"asked": font_file, "file": font_file, "family": None, "how": "font_file", "substituted": False}
    if script_file:
        return {"asked": asked, "file": script_file, "family": script_family, "how": "script", "substituted": False}
    if renderer == "libass" and platform.system() == "Windows":
        return {"asked": asked, "file": None, "family": asked, "how": "by_name", "substituted": False}
    found = resolve_font(asked or "")
    if not found["file"]:
        return {"asked": asked, "file": None, "family": asked, "how": "by_name", "substituted": False}
    return {"asked": asked, "file": found["file"], "family": found["family"], "how": "resolved",
            "substituted": bool(found["substituted"]), "via": found["via"]}


def record_font_choice(choice: "Dict[str, object]") -> "Dict[str, object]":
    """Record a substituted font (`diagnostics.fallbacks`, `font_substituted`) and return `choice`
    for the result's `font_used`: fontconfig answers every request with some font, and drawtext and
    libass draw with it and exit 0, so without this the only trace was the picture."""
    if choice.get("substituted"):
        record_fallback(f"font: '{choice['asked']}' is not installed here; drawing with {choice.get('family') or '?'} "
                        f"({choice['file']}) instead", "font_substituted",
                        asked=choice["asked"], file=choice["file"], family=choice.get("family"), via=choice.get("via"))
    return choice


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
    "zh-hant": "Traditional Chinese",
}


# fontconfig's own :lang= codes for each script we detect (zh uses zh-cn, the Simplified subset
# every CJK font that claims zh carries; the rest are the plain two-letter codes).
FC_LANG = {"ja": "ja", "zh": "zh-cn", "ko": "ko", "ar": "ar", "he": "he", "hi": "hi", "th": "th", "ru": "ru", "el": "el",
           "bn": "bn", "ta": "ta", "lo": "lo", "zh-hant": "zh-tw"}


# Families tried in order, best first. The names are matched case-insensitively against the start
# of any family fontconfig reports for a file, so "Noto Sans CJK JP" also matches
# "Noto Sans CJK JP Black". Anything not listed still qualifies -- it just sorts after these.
PREFERRED_FAMILIES = {
    "ja": ["Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans JP", "Source Han Sans", "IPAPGothic", "IPAGothic", "IPA", "VL Gothic", "TakaoGothic", "WenQuanYi Zen Hei"],
    "zh": ["Noto Sans CJK SC", "Noto Serif CJK SC", "Noto Sans SC", "Source Han Sans", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Droid Sans Fallback"],
    "zh-hant": ["Noto Sans CJK TC", "Noto Serif CJK TC", "Noto Sans CJK HK", "Noto Sans TC", "Noto Sans HK", "Source Han Sans TW",
                "Source Han Sans HC", "AR PL UMing TW", "AR PL UKai TW", "PingFang TC", "WenQuanYi Zen Hei", "Droid Sans Fallback"],
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
    "zh-hant": [("msjh.ttc", "Microsoft JhengHei"), ("mingliu.ttc", "MingLiU")],
    "ja": [("meiryo.ttc", "Meiryo"), ("YuGothM.ttc", "Yu Gothic Medium"), ("YuGothR.ttc", "Yu Gothic"), ("msgothic.ttc", "MS Gothic")],
    "ar": [("tahoma.ttf", "Tahoma"), ("arial.ttf", "Arial")],
    "he": [("tahoma.ttf", "Tahoma"), ("arial.ttf", "Arial")],
    # Windows 11 ships Nirmala UI as the collection Nirmala.ttc; there is no Nirmala.ttf (#339).
    # The .ttf names stay first so a machine that still has them (older Windows, a copied font)
    # keeps that file. Mangal, when present, stays the Devanagari face it always was.
    "hi": [("mangal.ttf", "Mangal"), ("Nirmala.ttf", "Nirmala UI"), ("Nirmala.ttc", "Nirmala UI"), ("NirmalaB.ttf", "Nirmala UI")],
    "th": [("leelawui.ttf", "Leelawadee UI"), ("leelawad.ttf", "Leelawadee"), ("tahoma.ttf", "Tahoma")],
    "bn": [("Nirmala.ttf", "Nirmala UI"), ("Nirmala.ttc", "Nirmala UI"), ("vrinda.ttf", "Vrinda")],
    "ta": [("Nirmala.ttf", "Nirmala UI"), ("Nirmala.ttc", "Nirmala UI"), ("latha.ttf", "Latha")],
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


# 2.19: Han-only text is Chinese, and Chinese is written in two standard forms whose glyphs differ
# (骨, 直, 角 are drawn differently in Taipei and Beijing). A Simplified face draws a Taiwanese
# caption in the wrong form, so a --lang naming Traditional Chinese resolves a Traditional face.
# The script stays "zh" for wrapping; only the font lookup changes.
HANT_TAGS = ("zh-tw", "zh-hk", "zh-mo", "zh-hant", "yue")


def font_key(script: str, lang: "Optional[str]" = None) -> str:
    """The font-table key for `script` under the caller's `lang`: "zh-hant" for Chinese text the
    caller says is Traditional (zh-TW, zh-HK, zh-MO, zh-Hant-*, yue), else `script` itself."""
    tag = (lang or "").strip().lower().replace("_", "-")
    if script == "zh" and any(tag == t or tag.startswith(t + "-") for t in HANT_TAGS):
        return "zh-hant"
    return script


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


def _is_last_resort(entry: "Tuple[str, str]") -> bool:
    """Unifont, fontconfig's code-point-box face: it covers every script and renders none."""
    return "unifont" in " ".join(str(x) for x in entry).lower()


def script_font_for_text(text: str, *, lang: "Optional[str]" = None, font: "Optional[str]" = None,
                         font_explicit: bool = False, font_file: "Optional[str]" = None,
                         fonts_dir: "Optional[str]" = None
                         ) -> "Tuple[str, Optional[str], Optional[str]]":
    """(script, font file, family) to draw `text` with, resolving by script when nothing explicit
    was asked for.

    Returns (script, None, None) when the caller's own choice stands: Latin text, an explicit
    --font-file, an explicit --font (which is kept even when fontconfig says it does not cover
    the script -- with one recorded warning saying so, `font_lacks_script`, because overriding a
    user's stated font silently is worse than a warning), or a --fonts-dir that does carry the script. Otherwise the resolved
    file is returned with ONE info line naming it.

    A script fontconfig says nothing covers is a failed job (tofu is not a delivery). A machine
    with no working fontconfig at all answers "unknown", not "missing": the job continues with
    the caller's font -- libass and drawtext still have their own font backends -- and one recorded
    warning (`font_coverage_unverified`) says the coverage could not be verified.
    """
    script = detect_script(text or "", lang)
    if script == "latin":
        return script, None, None
    if font_file:
        return script, None, None
    key = font_key(script, lang)
    if font_explicit and font:
        if not font_covers_script(font, key):
            warn(f"font: '{font}' does not cover {LANGUAGE_NAMES[key]} text on this machine; keeping it as asked "
                 f"(drop --font, or {FONT_FLAG_HINT}, to pick one by script automatically)", "font_lacks_script",
                 font=font, script=script)
        return script, None, None
    if fonts_dir:
        covered = fonts_dir_covers_script(fonts_dir, key)
        if covered:
            return script, None, None
        if covered is None:
            warn(f"font: could not verify that {fonts_dir} covers {LANGUAGE_NAMES[key]} text "
                 "(no fc-scan on this machine); using it as given", "font_coverage_unverified", fonts_dir=fonts_dir, script=script)
            return script, None, None
        record_fallback(f"font: no face in {fonts_dir} covers {LANGUAGE_NAMES[key]} text; "
                        "picking one by script instead (the directory is still searched first)", "fonts_dir_lacks_script",
                        fonts_dir=fonts_dir, script=script)
    entry = _script_font_entry(key)
    if key != script and (not entry or (entry is not FC_UNKNOWN and _is_last_resort(entry))):
        # no Traditional face (Unifont's code-point boxes are none): the Simplified one still
        # has the characters, in the other form
        simplified = _script_font_entry(script)
        if simplified and simplified is not FC_UNKNOWN and (not entry or not _is_last_resort(simplified)):
            entry = simplified
            record_fallback(f"font: no {LANGUAGE_NAMES[key]} face is installed; drawing with {entry[0]}, a "
                            "Simplified Chinese face whose glyph forms differ in places "
                            "(install fonts-noto-cjk or a TC font)", "font_variant_missing", lang=lang, file=entry[0])
            key = script
    if entry is FC_UNKNOWN:
        warn(f"font: could not verify that this machine can render {LANGUAGE_NAMES[key]} text "
             "(no working fontconfig); rendering with the font as given -- "
             "doctor --json .fonts.scripts reports what is known", "font_coverage_unverified", script=script)
        return script, None, None
    if not entry:
        die(f"no installed font covers {LANGUAGE_NAMES[key]} text on this machine — {FONT_INSTALL_HINT}", kind="input")
    info(f"font: {entry[0]} (covers {key})")
    return script, entry[0], entry[1]
