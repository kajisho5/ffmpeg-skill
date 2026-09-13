"""Colour: the bt709 tagging arguments and the HDR-to-SDR conversion path, plus colour-token
validation for the tools that take a `--color`.
"""
from __future__ import annotations

import re
from typing import List, Tuple
from _common.emit import die
from _common.runner import ffmpeg_version


def bt709_tag_args(encoder: str = "libx264") -> List[str]:
    """Tag an SDR output as BT.709 without touching its pixels.

    Up to FFmpeg 7.0 the output options -colorspace/-color_primaries/-color_trc were tags only.
    7.1 added colourspace negotiation to libavfilter and feeds those options into the graph's
    output constraints, so on a source whose bitstream carries no colour tags (test sources,
    screen recordings, many cameras) the CLI now auto-inserts a *real* matrix conversion (its
    guess for "unknown" is bt601) into every SDR re-encode: a --lut-strength 0 no-op grade
    came back ~24 dB PSNR from its source on 7.1. From 7.1 on, the tags therefore go through
    the encoder's own VUI parameters instead, which libavfilter never sees; a source that is
    genuinely tagged bt601/bt2020 is left alone either way (it keeps its own tags on the old
    path, and the encoder VUI is a label, not a conversion, on the new one).
    """
    if ffmpeg_version() < (7, 1):
        return ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    if encoder == "libx265":
        return ["-x265-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]
    return ["-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]


def _sdr_bt709(encoder: str) -> "Tuple[str, List[str]]":
    """BT.709 SDR tags for `encoder` as (encoder-params string, extra output options): the two
    spellings bt709_tag_args() picks between, split so a caller that already builds an encoder
    params string can merge them (the option given twice keeps only the last)."""
    if ffmpeg_version() < (7, 1):
        return "", ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    if encoder == "libsvtav1":
        return "color-primaries=1:transfer-characteristics=1:matrix-coefficients=1", []
    if encoder == "libaom-av1":
        return "", []  # no VUI params option; an untagged 8-bit stream reads as BT.709 everywhere
    return "colorprim=bt709:transfer=bt709:colormatrix=bt709", []


def color_hex(value: str) -> str:
    """Normalise '#ffd200' / 'ffd200' / '0xFFD200' to 'FFD200'."""
    v = str(value).strip().lstrip("#")
    if v.lower().startswith("0x"):
        v = v[2:]
    if len(v) != 6:
        die(f"colour must be RRGGBB, got '{value}'")
    return v.upper()


_COLOR_TOKEN_RE = re.compile(r"^(0[xX][0-9A-Fa-f]{6,8}|#[0-9A-Fa-f]{6,8}|[A-Za-z][A-Za-z0-9]*)(@(?:0(?:\.\d+)?|1(?:\.0+)?|\.\d+))?$")  # alpha is 0..1; "red@2" used to reach ffmpeg


def validate_color(value: str, flag: str = "--color") -> str:
    """Refuse a colour argument that isn't a plain ffmpeg colour token (named colour, 0xRRGGBB[AA],
    #RRGGBB[AA], optionally with an @alpha suffix). Every caller that string-formats a colour flag
    straight into a filter graph (color=c=..., tpad=...:color=..., rotate=...:fillcolor=...) must
    validate it first -- ffmpeg filter options are comma/colon-delimited, so an unvalidated value
    containing those characters lets a caller splice in an entirely different filter (a real,
    demonstrated filter-graph injection: --color "black,drawtext=text=..." renders arbitrary burnt-in
    text), not just an odd colour. This is the same "no filter graph accepted from the caller"
    invariant every other typed flag in this codebase already holds to."""
    if not _COLOR_TOKEN_RE.match(value):
        die(f"{flag} must be a plain colour (a name, 0xRRGGBB[AA], or #RRGGBB[AA], optionally @alpha), got '{value}'")
    return value
