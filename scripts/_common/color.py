"""Colour: the bt709 tagging arguments and the HDR-to-SDR conversion path, plus colour-token
validation for the tools that take a `--color`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
    the encoder's own VUI parameters instead, which libavfilter never sees.

    These tags are a label on every FFmpeg version: they never convert the pixels. A source
    whose matrix is not BT.709 (a BT.601 `smpte170m`/`bt470bg` file) gets its pixels converted
    separately, by bt709_matrix_filter() in the filter graph; through 2.10.0 nothing did, and
    such a source came out labelled BT.709 over BT.601 pixels (measured on 6.1: 48.5 dB YUV
    PSNR against the source, i.e. untouched, tagged bt709/bt709/bt709).
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


# The SDR matrices (ffprobe's names) whose pixels an output tagged BT.709 has to convert:
# BT.601 (`smpte170m` 525-line, `bt470bg` 625-line: the same coefficients) and the two rare
# pre-BT.709 ones the colorspace filter also reads. bt2020nc/c sources take the HDR/BT.2020 path.
NON_BT709_MATRICES = ("smpte170m", "bt470bg", "fcc", "smpte240m")

# RGB pictures (ffprobe's pix_fmt names: PNG rgb24/rgba/pal8/rgb48be, qtrle, gbrp...). Their
# conversion to YUV is wherever the graph first needs YUV, and FFmpeg's default for it is BT.601
# (5.1, 6.1, 7.0; 7.1+ follows the link's tag, unspecified = BT.601). Gray has no matrix.
_RGB_PIX_FMT_RE = re.compile(r"^(?:rgb|bgr|argb|abgr|0rgb|0bgr|gbr|x2rgb|x2bgr|pal8)")


def rgb_to_bt709_filter(pix_fmt: str = "yuv444p") -> str:
    """An RGB picture converted to BT.709 limited-range YUV right here, in `pix_fmt`, so no later
    conversion (an auto-inserted one, with FFmpeg's BT.601 default) decides the matrix. 4:4:4 by
    default: the tool's own scaling and the encoder's 4:2:0 come after, as they did on the RGB."""
    return f"scale=out_color_matrix=bt709:out_range=tv,format={pix_fmt}"


def is_rgb(meta: Optional[Dict[str, Any]]) -> bool:
    """True when the probed picture is RGB (a PNG/still, a qtrle/png-in-mov clip, an image sequence)."""
    return bool(_RGB_PIX_FMT_RE.match(str(((meta or {}).get("video") or {}).get("pix_fmt") or "")))


_MATRIX_FILTER_RE = re.compile(r"^(?:colorspace=ispace=(?:%s):iprimaries=bt709:itrc=bt709:space=bt709:primaries=bt709:trc=bt709|(?:format=rgb24,)?%s)$"
                               % ("|".join(NON_BT709_MATRICES), re.escape(rgb_to_bt709_filter())))
_INPUT_VIDEO_REF = re.compile(r"\[(\d+):v(?::0)?\]")


def bt709_matrix_filter(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """The filter that turns the probed source's pixels into BT.709 ones before an output is
    tagged BT.709, or None when nothing needs converting: an SDR source tagged with a non-BT.709
    matrix (NON_BT709_MATRICES) only. An untagged or BT.709 source, an HDR/BT.2020 one (it keeps
    its own tags, or color.py --to-sdr converts it) and a missing probe get None, so their
    commands are what they were.

    The matrix is converted and nothing else: primaries and transfer are passed through
    (iprimaries/itrc = the output's), so the picture a player that decodes with the source's
    matrix showed is the picture the BT.709 output shows. The `colorspace` filter is in every
    FFmpeg build (no zscale needed) and takes explicit input properties, so the conversion does
    not depend on how a build reads or negotiates the frames' own tags. The range is left as it is.

    An RGB source (is_rgb: a PNG/still, an image sequence, a qtrle clip) has no matrix of its own
    but gets one where the graph first needs YUV, and FFmpeg's default there is BT.601: through
    2.10.1 such a source came out labelled BT.709 over BT.601-encoded pixels (pure red decoded as
    (255,24,0), pure green as (0,216,0), on 5.1.1 to 8.1). It is converted to BT.709 YUV here
    (rgb_to_bt709_filter). A JPEG (yuvj, tagged bt470bg) is a BT.601 source like any other."""
    v = (meta or {}).get("video") or {}
    matrix = v.get("color_space")
    if v.get("bt2020_or_hdr"):
        return None
    if is_rgb(meta):
        # a palette is turned into YUV with fixed BT.601 coefficients whatever out_color_matrix
        # says (5.1.1, 6.1): expand it to RGB first
        return ("format=rgb24," if v.get("pix_fmt") == "pal8" else "") + rgb_to_bt709_filter()
    if matrix not in NON_BT709_MATRICES:
        return None
    return f"colorspace=ispace={matrix}:iprimaries=bt709:itrc=bt709:space=bt709:primaries=bt709:trc=bt709"


def bt709_label_filter(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """For an UNTAGGED SDR YUV picture that meets a converted (BT.709-tagged) one in a filter that
    mixes pictures (overlay, xstack): its BT.709 label, tags only (setparams), or None for any
    other picture (tagged, RGB, HDR, no probe).

    FFmpeg 7.1+ negotiates one colourspace for all of a mixing filter's inputs and converts the
    others to it, taking "unknown" as BT.601: the untagged main under a converted logo, or an
    untagged grid cell beside a converted one, was shifted (7.08 mean / 25 max RGB on 7.1.1 and
    8.1.3), or the converted picture converted back. Labelled as what the output says it is, the
    inputs agree and nothing is converted; on 5.1-7.0 the label changes nothing. The pixels are not
    touched, as for the untagged source of a one-input re-encode (bt709_tag_args)."""
    v = (meta or {}).get("video") or {}
    if (not v.get("pix_fmt") or v.get("bt2020_or_hdr") or is_rgb(meta)
            or (v.get("color_space") or "unknown") not in ("unknown", "unspecified")):
        return None
    return "setparams=colorspace=bt709" + ("" if v.get("color_range") == "pc" else ":range=tv")


# FFmpeg's named colours that are greys (libavutil/parseutils.c's table): R = G = B.
_GREY_NAMES = frozenset(("black", "white", "gray", "grey", "silver", "darkgray", "darkgrey", "dimgray", "dimgrey",
                         "gainsboro", "lightgray", "lightgrey", "whitesmoke"))


def _yuv8(rgb: Sequence[int], kr: float, kb: float) -> "Tuple[int, int, int]":
    """8-bit limited-range YUV of an RGB colour under the matrix (kr, kb), rounded as FFmpeg's
    drawing code rounds it (ff_draw_color)."""
    r, g, b = (c / 255 for c in rgb)
    y = kr * r + (1 - kr - kb) * g + kb * b
    return (int(16 + 219 * y + 0.5), int(128 + 224 * (b - y) / (2 * (1 - kb)) + 0.5),
            int(128 + 224 * (r - y) / (2 * (1 - kr)) + 0.5))


def is_neutral_color(value: Any) -> bool:
    """True for a colour whose 8-bit YUV is the same under BT.601 and BT.709, however translucent: a
    grey (R = G = B; black and white included), or one so near grey that both round to the same
    bytes (graphics.py's default background 101418). Only another colour lands differently, so only
    it needs drawn_chain(). A name counts only if it is one of FFmpeg's greys; anything else
    (`red`, `random`) is not neutral."""
    v = str(value or "").strip().split("@")[0].lower()
    if v in _GREY_NAMES:
        return True
    v = v[1:] if v.startswith("#") else v[2:] if v.startswith("0x") else v
    if re.fullmatch(r"[0-9a-f]{6}(?:[0-9a-f]{2})?", v):
        rgb = (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
        return _yuv8(rgb, 0.299, 0.114) == _yuv8(rgb, 0.2126, 0.0722)
    return False


def is_full_range(meta: Optional[Dict[str, Any]]) -> bool:
    """True when the probed YUV picture is full range: a `yuvj` format, or any other YUV format
    tagged `pc` (VP9 and AV1 full range decode as plain `yuv420p` tagged pc, 10-bit full range as
    `yuv420p10le` tagged pc). An RGB picture is not: bt709_matrix_filter() makes it limited YUV."""
    v = (meta or {}).get("video") or {}
    if is_rgb(meta) or not v.get("pix_fmt"):
        return False
    return str(v["pix_fmt"]).startswith("yuvj") or v.get("color_range") == "pc"


def limited_range_filter(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """The filter that takes a full-range SDR YUV picture (is_full_range) to limited range, or None
    for any other picture (limited, RGB, HDR/BT.2020, no probe).

    A tool that puts several pictures in one frame or one stream (concat, xfade, xstack, overlay)
    passes their samples through as they are, so a full-range clip beside a limited one was shown
    with the other's range: C03028 came out C9251B (#410). The input range is left to `scale`,
    which reads it from each frame (FFmpeg 6.1 already converts a full-range non-`yuvj` frame to
    limited at any resize, so a stated `in_range=pc` would convert some frames twice); only the
    output range is stated. A `yuvj` format is full range by name, so it is also given its limited
    name (`format=`), or swscale would write full range under the limited tag."""
    v = (meta or {}).get("video") or {}
    if v.get("bt2020_or_hdr") or not is_full_range(meta):
        return None
    pf = str(v["pix_fmt"])
    return "scale=out_range=tv" + (f",format=yuv{pf[4:]}" if pf.startswith("yuvj") else "")


def as_limited(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """`meta` as it reads after limited_range_filter(): the same probe with a limited-range format and
    tag, for the code that plans what is drawn on the converted picture (drawn_stream_format)."""
    if not limited_range_filter(meta):
        return meta
    v = dict((meta or {}).get("video") or {})
    pf = str(v["pix_fmt"])
    v.update(pix_fmt="yuv" + pf[4:] if pf.startswith("yuvj") else pf, color_range="tv")
    return {**(meta or {}), "video": v}


def drawn_stream_format(meta: Optional[Dict[str, Any]]) -> "Tuple[str, bool]":
    """(pix_fmt, full range) of the picture a tool draws on, for rgb_island(): the probed source's own
    8-bit planar YUV format (an RGB source has become yuv444p, BT.709 limited, through
    bt709_matrix_filter), or yuv420p for anything else (the format the encoder line takes it to)."""
    v = (meta or {}).get("video") or {}
    if is_rgb(meta):
        return "yuv444p", False
    pf = str(v.get("pix_fmt") or "yuv420p")
    full = is_full_range(meta)
    if pf not in ("yuv420p", "yuv422p", "yuv444p", "yuvj420p", "yuvj422p", "yuvj444p"):
        pf = "yuv420p"
    return pf, full


def rgb_island(colour_chain: str, neutral_chain: str = "null", pix_fmt: str = "yuv420p", full: bool = False,
               tag: str = "d") -> str:
    """`colour_chain` (filters that draw a colour: drawtext, pad, tpad, rotate's fill, libass) run on
    an RGB copy of the picture, as one simple filtergraph (one input, one output; `tag` keeps its
    labels unique in a bigger graph). For FFmpeg < 7.1, whose drawing filters turn every colour into
    YUV with BT.601 whatever the picture is tagged (`ff_draw_init`), and drawbox on every version:
    in RGB a colour is written as it is, and the copy goes back to YUV with BT.709.

    Only the pixels the drawing touched come from that copy. The same round trip without the colour
    (`neutral_chain`: `null`, or the same pad/tpad/rotate with a black fill, which is the same under
    every matrix) is compared with it plane by plane, and maskedmerge takes the drawn copy where
    the two differ and the untouched picture (`neutral_chain` on the YUV itself) everywhere else:
    the RGB round trip is not lossless, so a picture that only passes through keeps its pixels."""
    rng = "pc" if full else "tv"
    to_rgb = f"scale=in_color_matrix=bt709:in_range={rng},format=rgb24"
    to_yuv = f"scale=out_color_matrix=bt709:out_range={rng},format={pix_fmt}"
    keep = "'255*gt(val,0)'"
    t = f"_{tag}"
    return (f"split=3[{t}p][{t}c][{t}n];[{t}p]format={pix_fmt},{neutral_chain}[{t}p1];"
            f"[{t}c]{to_rgb},{colour_chain},{to_yuv},split[{t}c1][{t}c2];"
            f"[{t}n]{to_rgb},{neutral_chain},{to_yuv}[{t}n1];"
            f"[{t}c1][{t}n1]blend=all_mode=difference,lut=c0={keep}:c1={keep}:c2={keep}[{t}m];"
            f"[{t}p1][{t}c2][{t}m]maskedmerge")


def bt709_matrix_args(meta: Optional[Dict[str, Any]]) -> List[str]:
    """["-vf", bt709_matrix_filter(meta)] for an encoder line that tags its output BT.709, or [].

    It rides on the encoder line (decision.video_args() and friends) so every tool that
    re-encodes through that line converts without building it into its own graph. That -vf is
    valid as it stands for a command with no other filter; run() folds it into the tool's own
    -vf or -filter_complex (fold_bt709_matrix()) before the command is recorded or run."""
    f = bt709_matrix_filter(meta)
    return ["-vf", f] if f else []


def fold_bt709_matrix(cmd: Sequence[str]) -> List[str]:
    """`cmd` with the conversion bt709_matrix_args() appended to its encoder line moved into the
    tool's own filter graph, where it runs first, on the decoded source:

    - no other filter: unchanged (the -vf is the graph);
    - a -vf: the conversion is prepended to that chain;
    - a -filter_complex: every `[N:v]` / `[N:v:0]` reference to an input that reads the same file
      as input 0 (the file the encoder line was built for; cut.py's segment join opens it once
      per segment) reads that input through the conversion instead. Other inputs are untouched.

    A -filter_complex with no such reference is refused rather than run with two graphs (ffmpeg
    would refuse it anyway, less clearly). Every other command is returned as it is."""
    out: List[str] = []
    conv, at = None, -1
    i = 0
    while i < len(cmd):
        if cmd[i] == "-vf" and i + 1 < len(cmd) and _MATRIX_FILTER_RE.match(str(cmd[i + 1])):
            conv, at = conv or str(cmd[i + 1]), (at if at >= 0 else len(out))
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    if conv is None:
        return list(cmd)
    graph_at = next((k for k, a in enumerate(out[:-1]) if a in ("-filter_complex", "-lavfi")), None)
    if graph_at is not None:
        inputs = [out[k + 1] for k in range(len(out) - 1) if out[k] == "-i"]
        source = {n for n, p in enumerate(inputs) if p == inputs[0]} if inputs else set()
        refs: Dict[int, List[str]] = {}  # input index -> [its first reference, the labels standing in for it]

        def through(m: "re.Match[str]") -> str:
            n = int(m.group(1))
            if n not in source:
                return m.group(0)
            label = f"[bt709src{sum(len(v) - 1 for v in refs.values())}]"
            refs.setdefault(n, [m.group(0)]).append(label)
            return label

        graph = _INPUT_VIDEO_REF.sub(through, str(out[graph_at + 1]))
        if not refs:
            die("internal: a BT.709 matrix conversion was requested for a -filter_complex that never reads "
                "input 0's video as [0:v]", kind="ffmpeg")
        # one conversion per input, split when the graph reads that input more than once
        # (speedramp.py trims [0:v] once per segment)
        chains = [f"{ref}{conv}" + (f",split={len(labels)}" if len(labels) > 1 else "") + "".join(labels)
                  for ref, *labels in refs.values()]
        out[graph_at + 1] = ";".join(chains + [graph])
        return out
    vf_at = next((k for k, a in enumerate(out[:-1]) if a == "-vf"), None)
    if vf_at is not None:
        out[vf_at + 1] = f"{conv},{out[vf_at + 1]}"
        return out
    return out[:at] + ["-vf", conv] + out[at:]


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
