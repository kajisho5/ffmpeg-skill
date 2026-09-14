"""drawtext: the option builders (textfile= route, boxborderw form per ffmpeg version), the
font-name escape and the shaping-library probe that decides drawtext vs libass per script.
Split out of _common.text in the refactor after 1.17.3; every body is byte-identical.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Dict, Optional
from _common.decision import escape_filter_path
from _common.runner import STATE, _DRAWTEXT_PENDING, _drawtext_tmpdir, ffmpeg_version


def drawtext_boxborderw(vertical: int, horizontal: int) -> str:
    """drawtext's per-side `boxborderw=top|right|bottom|left` (and the two-value `v|h` form)
    arrived in FFmpeg 6.1; 5.x and 6.0 reject the `|` with "Error setting option boxborderw"
    (found by the FFmpeg 5.1.1 CI job, #146). Older builds get the larger single value."""
    if ffmpeg_version() >= (6, 1):
        return f"{vertical}|{horizontal}"
    return str(max(vertical, horizontal))


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
