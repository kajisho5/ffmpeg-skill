"""Emoji: cluster detection (ZWJ sequences, keycaps, flags, skin tones), the PNG asset lookup,
the per-machine support probe and the overlay filter chain that composites the assets.
Split out of _common.text in the refactor after 1.17.3; every body is byte-identical.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Tuple, Optional
from _common.emit import die


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
