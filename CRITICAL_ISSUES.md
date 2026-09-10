# Identified Issues for ffmpeg-skill

## Summary
Found 5 issues during code review, overlapping with #100 (Windows drawtext crash). All five are now addressed.

## Issues

### Issue 1: Python 3.14+ SyntaxWarning on invalid escape sequence — Fixed
- **File**: `_common.py:342`
- **Problem**: `" \t\\"'\\;|&<>()[]{}$*?"` contains invalid escape sequence `\;`
- **Severity**: Medium (will become error in Python 3.14+)
- **Fix**: dropped the stray backslash before `;` (it was already a plain, unescaped character everywhere else in that string)

### Issue 2: Windows Python documentation gap — Fixed
- **Location**: README examples
- **Problem**: Examples show `python3` but Windows Git Bash only recognizes `python`
- **Fix**: added a note next to the Quick Start script examples pointing Windows/Git Bash users at `python` instead; `bin/install.js` and `doctor`/`contract` already handled this, only the raw script-example block needed it spelled out

### Issue 3: FFmpeg capability detection incomplete for drawtext — Fixed
- **Problem**: `doctor` reported `missing required: none` but `drawtext` crashes at runtime on Windows
- **Fix**: `doctor` now actually renders one frame through `drawtext` (`_drawtext_probe()` in `scripts/_contract.py`) instead of trusting the `-filters` listing alone. A crash (killed by signal on POSIX, an access-violation-style exit on Windows) downgrades `filter:drawtext` from "listed" to `missing`, with the crash detail surfaced in `errors[]`; an ordinary nonzero exit (including every existing fixture-driven test's fake ffmpeg) leaves the listing-based result standing, since that proves nothing either way

### Issue 4: Font error messages lack context — Mitigated, not directly fixed
- **Problem**: Fontconfig errors don't indicate actual cause (missing fontfile, invalid fonts.conf)
- **Impact**: All drawtext tools (look.py, scenes.py, overlay.py, graphics.py)
- **What changed**: all four tools now resolve a concrete `--font-file` by default (`default_font_file()` in `_common.py`) and emit `fontfile=` instead of `font=` whenever one can be found — this is the root-cause fix for #100 (fontconfig's own resolution is what crashes; `fontfile=` skips it entirely), so in practice the fontconfig error path this issue describes should rarely be hit anymore. The underlying ffmpeg/fontconfig error text itself is unchanged when it does still occur.

### Issue 5: SKILL.md missing Windows drawtext limitations — Fixed
- **Location**: SKILL.md Gotchas section
- **Problem**: No mention of Windows-specific `drawtext` + fontconfig issues
- **Fix**: added a Gotchas entry describing the crash, the automatic `fontfile=` default that now covers it, and the `--font-file` / `doctor` escape hatches if it still happens

## Related
- Issue #100: "drawtext access-violates on Windows" — the root-cause fix (fontfile= by default across look/scenes/overlay/graphics, plus doctor's real drawtext probe) closes this.
