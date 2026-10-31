"""drawtext: the option builders (textfile= route, boxborderw form per ffmpeg version), the
font-name escape and the shaping-library probe that decides drawtext vs libass per script.
Split out of _common.text in the refactor after 1.17.3; every body is byte-identical.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional
from _common.decision import escape_filter_path
from _common.runner import STATE, _DRAWTEXT_PENDING, _drawtext_tmpdir, ffmpeg_exe, ffmpeg_release, require_tool


def _on_windows() -> bool:
    return os.name == "nt"


def _windows_short_path(path: str) -> "Optional[str]":
    """The 8.3 short form of an existing Windows path, or None (not Windows, the call failed, or
    the volume keeps no short names)."""
    if not _on_windows():
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    except (OSError, AttributeError, ValueError):
        return None
    return buf.value if 0 < n < len(buf) else None


def drawtext_fontfile(path: str) -> str:
    """`fontfile=<path>` for drawtext, with a path FreeType can open.

    drawtext hands the path to FreeType, which opens it with the C runtime's ANSI fopen on
    Windows: measured on the gyan.dev 9.0.2 build, a font under `compat dir ünïcode` fails to
    load (drawtext falls back to fontconfig and the job dies with "could not parse fontconfig
    pattern") while the same file under an ASCII directory loads, spaces and all. A non-ASCII
    path on Windows is therefore given in its 8.3 short form, or, where the volume keeps no
    short names, copied into this run's private drawtext directory under an ASCII name (recorded,
    `font_path_copied`). Elsewhere the path is passed as it is. The original file is what a plan
    binds, never the copy.
    """
    path = str(path)
    if not _on_windows() or path.isascii() or not os.path.isfile(path):
        # a missing file is left to ffmpeg's own error, as before: there is nothing to copy
        return f"fontfile={escape_filter_path(path)}"
    if os.path.isfile(path) and path not in STATE.plan_inputs:
        STATE.plan_inputs.append(path)
    short = _windows_short_path(path)
    if short and short.isascii():
        return f"fontfile={escape_filter_path(short, bind=False)}"
    import hashlib
    from _common.emit import record_fallback, warn
    tmpdir = _drawtext_tmpdir(create=not STATE.dry_run)
    if not tmpdir.isascii():
        tmpdir = _windows_short_path(tmpdir) or tmpdir
    st = os.stat(path)
    # the path plus size and mtime: a font replaced in place during the run gets a new copy
    key = f"{path}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")
    name = "font_" + hashlib.sha1(key, usedforsecurity=False).hexdigest()[:16] + os.path.splitext(path)[1].lower()
    copy = os.path.join(tmpdir, name)
    if not copy.isascii():
        warn(f"font: {path} is not an ASCII path and no ASCII copy could be placed; drawtext may "
             "not open it on Windows (move the font to a folder named in ASCII)", "font_path_not_ascii", font=path)
        return f"fontfile={escape_filter_path(path, bind=False)}"
    if not STATE.dry_run and not os.path.exists(copy):
        try:
            shutil.copyfile(path, copy)
        except OSError as e:
            warn(f"font: could not copy {path} to an ASCII path ({e}); drawtext may not open it on "
                 "Windows (move the font to a folder named in ASCII)", "font_path_not_ascii", font=path)
            return f"fontfile={escape_filter_path(path, bind=False)}"
    record_fallback(f"font: {path} is not an ASCII path, which drawtext cannot open on Windows; "
                    f"drawing with a copy at {copy}", "font_path_copied", font=path, file=copy)
    return f"fontfile={escape_filter_path(copy, bind=False)}"


def drawtext_boxborderw(vertical: int, horizontal: int) -> str:
    """drawtext's per-side `boxborderw` in its two-value `v|h` form (FFmpeg 6.1+, the floor since
    3.0.0; 2.x gave 5.x and 6.0 the larger single value, which they needed)."""
    return f"{vertical}|{horizontal}"


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
    exe = ffmpeg_exe("ffmpeg")[0]
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


# FFmpeg 8.0 rewrote drawtext's line splitter to hand harfbuzz `p - start` bytes after GET_UTF8 had
# already stepped past the line break, so every line but the last is shaped WITH its newline and
# the font's .notdef box is drawn at its end (and counted in text_w). 8.0.2 and 8.1.1 measure the
# length before the step; 8.0, 8.0.1 (Ubuntu 26.04) and 8.1 ship the bug.
NEWLINE_GLYPH_RELEASES = frozenset({(8, 0, 0), (8, 0, 1), (8, 1, 0)})


def drawtext_draws_newline_glyph() -> bool:
    """Whether this build's drawtext draws a box at each line break of a multi-line text (see
    NEWLINE_GLYPH_RELEASES). A git or vendor build without a release number is taken to be fixed:
    the fix is on master, and a guess the other way would reroute every multi-line title."""
    return ffmpeg_release() in NEWLINE_GLYPH_RELEASES


def is_multiline(text: "Optional[str]") -> bool:
    """`text` draws as more than one line (the normalisation drawtext_text_opts() applies)."""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return "\n" in cleaned


def drawtext_center_align() -> str:
    """`:text_align=C` for a centred drawtext, so each line of a multi-line label is centred on
    its own (FFmpeg 6.1+, the floor since 3.0.0)."""
    return ":text_align=C"


def drawtext_clean(text: "Optional[str]") -> str:
    """The text drawtext_text_opts() writes to its file: `\r\n` and `\r` become `\n`, a tab,
    vertical tab or form feed becomes a space, other control characters are stripped, and trailing
    newlines are dropped (drawtext ignores one trailing newline and draws a second as a blank
    line, which would centre the block half a line too high; a label that is only newlines stays
    as it is)."""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\x00-\x08\x0e-\x1f\x7f]", "", re.sub(r"[\t\x0b\x0c]", " ", cleaned))
    return cleaned.rstrip("\n") or cleaned


def drawtext_text_opts(text: str, tmpdir: "Optional[str]" = None) -> str:
    r"""`textfile=<path>:expansion=none` for drawtext -- the one route that is provably safe for
    every character on every build shape this repo uses.

    The filter-graph parser never sees the text at all: only the PATH is parsed, and
    escape_filter_path() already handles that. `expansion=none` switches off drawtext's own
    `%{...}` scanner, which is the reason `%` was unsafe (a bare `\%` logs "Stray %" on one build
    and fails the whole filter chain on another). With the scanner off, `'`, `%`, `:`, `,`, `[`,
    `]`, `;` and `\` all reach the picture verbatim -- 1.15 fixes `overlay.py --text "it's 100%
    done"` losing both characters. A newline is kept (`\r\n` and `\r` become `\n`): drawtext
    draws it as a line break, and graphics.py's wrap puts them there on purpose (stripping them
    ran a wrapped title off both edges of the frame); trailing newlines are dropped. A tab, vertical tab or form
    feed becomes a space, as the wrap measures it; other control characters are stripped (that
    dates from the inline-escape route, where they broke the graph parser).

    The file is UTF-8, mode 0600, in a private per-run directory (see _drawtext_tmpdir) that is
    removed when the process ends. It is *registered* here and written by run() only if the
    command about to run actually names it, so --dry-run and the ASS route write nothing; a
    printed plan therefore names a path that no longer exists once the run is over, which is the
    same promise every other temp file in this skill makes.
    """
    cleaned = drawtext_clean(text)
    import hashlib
    name = "t_" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16] + ".txt"
    if tmpdir is None:
        tmpdir = _drawtext_tmpdir(create=not STATE.dry_run)
    path = os.path.join(tmpdir, name)
    _DRAWTEXT_PENDING[path] = cleaned
    return f"textfile={escape_filter_path(path)}:expansion=none"


def drawtext_line_metrics(lines: "List[str]", font_opt: str, fontsize: int) -> "List[Optional[Dict[str, float]]]":
    """Each line's drawtext metrics as this ffmpeg measures it ALONE, on one line, where the
    8.0/8.0.1/8.1.0 newline bug cannot reach it: {w: text_w, top: top_a, bottom: bottom_d, lh},
    None for an empty line (drawtext measures it as no glyphs).

    The numbers come out of drawtext itself: its y expression print()s them (libavutil's eval
    function, logged at error level), one drawtext per line on a generated one-frame picture --
    no input is read and nothing is written but the line files, in a temporary directory that is
    removed afterwards. It runs under --dry-run too (run_analysis), so a plan places the lines
    where a run does. The y expression is evaluated at configuration and again per frame; the
    last value of each line wins."""
    import tempfile
    from _common.emit import die
    from _common.runner import flush_drawtext_textfiles, run_analysis
    out: "List[Optional[Dict[str, float]]]" = [None] * len(lines)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-skill-measure-") as td:
        chain = []
        for i, line in enumerate(lines):
            if line:
                chain.append(f"drawtext={drawtext_text_opts(line, tmpdir=td)}:{font_opt}:fontsize={fontsize}:x=0:"
                             f"y='print({-(1000 + i)},16)+print(text_w,16)+print(top_a,16)+print(bottom_d,16)+print(lh,16)'")
        if not chain:
            return out
        cmd = [require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
               "-i", "color=c=black:s=16x16:r=1", "-frames:v", "1", "-vf", ",".join(chain), "-f", "null", "-"]
        try:
            flush_drawtext_textfiles(cmd)
            proc = run_analysis(cmd, record=True)
        finally:
            for path in [p for p in _DRAWTEXT_PENDING if p.startswith(td)]:
                del _DRAWTEXT_PENDING[path]
    current, values = None, {}  # type: Optional[int], Dict[int, List[float]]
    # 8.x prefixes each value with "[Eval @ 0x...] ", 6.1 prints it bare
    for m in re.finditer(r"^(?:\[Eval @ [^\]]*\] )?(-?[0-9]+(?:\.[0-9]+)?|-?nan|-?inf)\s*$", proc.stderr, re.M):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if v <= -1000 and v == int(v):
            current = int(-v) - 1000
            values[current] = []
        elif current is not None:
            values[current].append(v)
    for i, line in enumerate(lines):
        got = values.get(i) if line else None
        if line and (not got or len(got) != 4):
            die("could not measure a line of --text with drawtext (no print() output from ffmpeg)", kind="ffmpeg")
        if got:
            out[i] = {"w": got[0], "top": got[1], "bottom": got[2], "lh": got[3]}
    return out
