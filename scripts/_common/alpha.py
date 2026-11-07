"""The alpha channel: reading it, keeping it through a re-encode, and checking it was kept.

export.py's alpha presets (#417) measured the alpha of a written master against its source's; the
helpers moved here so the tools that composite or grade (color.py, graphics.py, overlay.py) and
background.py's transparent canvas can do the same:

- `--keep-alpha` (color, graphics, overlay) writes the picture with its alpha plane, in one of the
  ALPHA_CODECS lines (`--alpha-codec`, ProRes 4444 by default); background.py's `--transparent`
  writes a fully transparent canvas in the same lines. `--alpha-mode straight|premultiplied` says
  how the colour is stored, as export.py's does.
- An alpha line keeps the source's colour tags and converts no matrix, as `--codec prores` does
  (`keeps_source_tags()` in decision.py): an alpha master is an editing master.
- Every completed run on a source whose alpha is really used (a frame below OPAQUE) gets an
  `alpha` verification step. Without `--keep-alpha` the output's picture has no alpha and that step
  fails (the output reported `verified: true` with the alpha gone before this module existed);
  `--drop-alpha` says the flattening is wanted, and a note records it instead.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from typing import Any, Dict, List, Optional

from _common import runner as _runner
from _common.runner import STATE, ffmpeg_encoders, require_tool, run

# A pixel format that carries an alpha plane (yuva*, rgba, argb, gbrap, ya8/ya16, ...).
ALPHA_PIX = re.compile(r"^(yuva|gbrap|ya\d|rgba|bgra|argb|abgr|rgba64|bgra64)")

ALPHA_TOLERANCE = 2.0  # of 255, per frame (or on the mean and the most transparent frame, below)
OPAQUE = 254.5         # a frame whose mean alpha is at least this is fully opaque

_MEASURE_W, _MEASURE_H = 64, 36  # the measuring copy: small enough to read every frame, large enough for exact edges

# The lines --keep-alpha / --transparent write. `pix_fmt` is what the encoder is asked for and is
# read back (the `alpha` step's `codec` field); `ext` are the containers that hold it.
ALPHA_CODECS: Dict[str, Dict[str, Any]] = {
    "prores4444": {"video": ["-c:v", "prores_ks", "-profile:v", "4", "-vendor", "apl0", "-pix_fmt", "yuva444p10le",
                             "-alpha_bits", "16"],
                   "encoder": "prores_ks", "pix_fmt": "yuva444p10le", "ext": (".mov", ".mkv"),
                   "audio": ["-c:a", "pcm_s16le"], "desc": "ProRes 4444 with 16-bit alpha"},
    "qtrle": {"video": ["-c:v", "qtrle", "-pix_fmt", "argb"], "encoder": "qtrle", "pix_fmt": "argb", "ext": (".mov",),
              "audio": ["-c:a", "pcm_s16le"], "desc": "QuickTime Animation, lossless RGB + alpha"},
    "png": {"video": ["-c:v", "png", "-pix_fmt", "rgba"], "encoder": "png", "pix_fmt": "rgba", "ext": (".mov", ".mkv"),
            "audio": ["-c:a", "pcm_s16le"], "desc": "PNG frames in a .mov/.mkv, lossless RGB + alpha"},
    "vp9": {"video": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "20", "-b:v", "0", "-row-mt", "1"],
            "encoder": "libvpx-vp9", "pix_fmt": "yuva420p", "ext": (".webm", ".mkv"),
            "audio": ["-c:a", "libopus", "-b:a", "128k"], "desc": "VP9 with an alpha layer (CRF 20)"},
}
ALPHA_CODEC_DEFAULT = "prores4444"
ALPHA_MODES = ("straight", "premultiplied")


_DECODERS: "Optional[set]" = None


def ffmpeg_decoders() -> set:
    """Names from `ffmpeg -decoders`, read once (empty when the list cannot be read), as
    runner.ffmpeg_encoders() reads the encoders: the libvpx VP9 decoder is a build option of its
    own, so the encoder list does not say whether it is there."""
    global _DECODERS
    if _DECODERS is None:
        _DECODERS = _runner._read_ff_list("-decoders", r"^\s*[VAS][.\w]{5}\s+(\S+)")
    return _DECODERS


def libvpx_vp9_decoder() -> bool:
    """True when the build lists libvpx-vp9 among its decoders, or when the list could not be read
    (unknown is not "missing": the explicit decoder is kept and ffmpeg itself says if it is absent).
    False only when the list was read and does not have it."""
    decoders = ffmpeg_decoders()
    return not decoders or "libvpx-vp9" in decoders


def vp9_decoder_args(codec: Optional[str]) -> List[str]:
    """The input option that decodes a VP9 stream with libvpx-vp9: FFmpeg's native vp9 decoder
    drops the alpha layer (a WebM's yuva420p comes out yuv420p, fully opaque). [] for any other
    codec, or when this build has no libvpx-vp9 decoder (decoder_args_for() refuses that case
    where the alpha matters)."""
    return ["-c:v", "libvpx-vp9"] if codec == "vp9" and libvpx_vp9_decoder() else []


def vp9_alpha_tagged(path: str) -> bool:
    """True when the first video stream is VP9 stored with an alpha layer (Matroska/WebM's
    ALPHA_MODE=1 stream tag): ffprobe reports such a stream as yuv420p, so the pixel format alone
    does not show the alpha. A metadata read, so a dry run can decide without decoding."""
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_name:stream_tags", "-of", "json", path], quiet=True)
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
    except ValueError:
        return False
    s = streams[0] if streams else {}
    return s.get("codec_name") == "vp9" and any(k.lower() == "alpha_mode" and str(v).strip() == "1"
                                                for k, v in (s.get("tags") or {}).items())


def has_alpha_plane(meta: Dict[str, Any], path: str) -> bool:
    """True when the first video stream of `path` (probed as `meta`) stores an alpha plane: a pixel
    format with one, or a VP9 stream tagged with an alpha layer. Metadata only; whether the alpha
    is used (any pixel below opaque) takes alpha_stats()."""
    v = (meta or {}).get("video") or {}
    # a palette (pal8: an indexed PNG/GIF) can carry transparency in the palette itself (tRNS),
    # which the pixel format does not show; it is measured like an alpha plane
    return (bool(ALPHA_PIX.match(v.get("pix_fmt") or "")) or v.get("pix_fmt") == "pal8"
            or (v.get("codec") == "vp9" and vp9_alpha_tagged(path)))


def frame_means(cmd_head: List[str], path: str, chain: str) -> "Dict[str, object] | None":
    """Every decoded frame of `path` through `chain` to a 64x36 grey copy: {mean (over every frame),
    min (the lowest frame's mean), frames, per_frame (each frame's mean, in decode order)}. None
    when no frame decodes."""
    w, h = _MEASURE_W, _MEASURE_H
    cmd = cmd_head + ["-i", path, "-map", "0:v:0", "-vf", f"{chain},scale={w}:{h}:flags=area,format=gray",
                      "-f", "rawvideo", "-"]
    # Read frame by frame as ffmpeg writes them, not the whole pipe at once: the raw copy is 2304
    # bytes a frame (~250 MB for an hour at 30 fps), the per-frame means a float each. The same
    # wall-clock limit as run_analysis(), which this replaces here.
    _runner._refuse_url_media(cmd)
    limit = _runner._limit_for(cmd)
    size = w * h
    frames: List[float] = []
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_runner.child_kwargs())
    _runner._watch(child, cmd)
    expired = threading.Event()

    def _expire() -> None:
        expired.set()
        child.kill()

    timer = threading.Timer(limit, _expire) if limit else None
    if timer:
        timer.daemon = True
        timer.start()
    try:
        pending = b""
        while True:
            chunk = child.stdout.read(size * 64)
            if not chunk:
                break
            pending += chunk
            whole = len(pending) - len(pending) % size
            for i in range(0, whole, size):
                frames.append(sum(pending[i:i + size]) / size)
            pending = pending[whole:]
        child.wait()
    finally:
        if timer:
            timer.cancel()
        _runner._unwatch(child)
        child.stdout.close()
    if expired.is_set():
        _runner._timed_out(cmd, limit or 0)
    if child.returncode != 0 or not frames:
        return None
    return {"mean": sum(frames) / len(frames), "min": min(frames), "frames": len(frames), "per_frame": frames}


def alpha_stats(path: str, codec: Optional[str] = None) -> "Dict[str, object] | None":
    """The alpha (0-255) of every decoded frame, on a 64x36 copy: {mean, min, frames, per_frame}.
    255.0 is fully opaque, and a picture with no alpha plane reads 255 too (format=rgba fills it).
    Every frame, not the first: a clip that opens fully opaque and turns transparent later would
    read as opaque from its first frame, in the source and in a written file that lost its alpha.
    A VP9 file is decoded with libvpx-vp9 (vp9_decoder_args). None when no frame decodes."""
    head = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"] + vp9_decoder_args(codec)
    return frame_means(head, path, "format=rgba,alphaextract")


def alpha_compare(written, source) -> Dict[str, object]:
    """The written file's alpha against the source's. With the same number of frames, frame by
    frame (frame i against frame i, each within ALPHA_TOLERANCE): an aggregate let a loss confined
    to a few frames through (one of 200 frames turned opaque moves the mean by ~1). With a
    different count (a variable-rate source conformed to a constant rate repeats or drops frames,
    so indices no longer pair), the mean and the most transparent frame, and `paired: false`
    says so. {ok, paired, worst_delta, worst_frame}."""
    if written is None or source is None:
        return {"ok": False, "paired": None, "worst_delta": None, "worst_frame": None}
    w, s = written.get("per_frame") or [], source.get("per_frame") or []
    if w and len(w) == len(s):
        deltas = [abs(a - b) for a, b in zip(w, s)]
        worst = max(range(len(deltas)), key=deltas.__getitem__)
        return {"ok": deltas[worst] <= ALPHA_TOLERANCE, "paired": True, "worst_delta": round(deltas[worst], 2),
                "worst_frame": worst}
    delta = max(abs(written["mean"] - source["mean"]), abs(written["min"] - source["min"]))
    return {"ok": delta <= ALPHA_TOLERANCE, "paired": False, "worst_delta": round(delta, 2), "worst_frame": None}


def rounded(st) -> "Dict[str, float] | None":
    return None if st is None else {"mean": round(st["mean"], 2), "min": round(st["min"], 2), "frames": st["frames"]}


# source_alpha()'s answer for a source that stores an alpha plane whose alpha could not be read:
# not "opaque" (that would let an output that dropped it pass), so every check on it fails
UNMEASURED: Dict[str, Any] = {"unmeasured": True}


def _measured(st):
    return None if st is None or st.get("unmeasured") else st


def uses_alpha(st) -> bool:
    """True when a measured clip has a frame that is not fully opaque (its alpha is used), or when
    a clip that stores an alpha plane could not be measured (UNMEASURED)."""
    return st is not None and (bool(st.get("unmeasured")) or st["min"] < OPAQUE)


# --- the flags -----------------------------------------------------------------------------------

def add_alpha_args(ap, transparent: bool = False) -> None:
    """--keep-alpha / --drop-alpha (or background.py's --transparent), --alpha-codec, --alpha-mode."""
    g = ap.add_argument_group("alpha")
    if transparent:
        g.add_argument("--transparent", action="store_true",
                       help="write a fully transparent canvas (alpha 0 in every pixel) in an alpha line (--alpha-codec), "
                            "a base layer for graphics.py / overlay.py --keep-alpha; --color/--gradient do not apply")
    else:
        g.add_argument("--keep-alpha", action="store_true",
                       help="keep the source's alpha: write the output in an alpha line (--alpha-codec, default "
                            "prores4444; needs a .mov/.mkv, or .webm for vp9) with the source's colour tags kept, and "
                            "check the alpha after (the `alpha` verification step). Refused on a source without an alpha plane")
        g.add_argument("--drop-alpha", action="store_true",
                       help="the source has alpha and an opaque output is wanted: the alpha is dropped on purpose and a note "
                            "says so. Without it (or --keep-alpha) an output that loses a used alpha fails the `alpha` step")
    g.add_argument("--alpha-codec", choices=sorted(ALPHA_CODECS), default=None,
                   help="the alpha line: prores4444 (default; ProRes 4444, 16-bit alpha), qtrle (QuickTime Animation, "
                        ".mov), png (PNG frames, .mov/.mkv), vp9 (VP9 with alpha, .webm/.mkv)")
    g.add_argument("--alpha-mode", choices=list(ALPHA_MODES), default=None,
                   help="how the colour is written beside the alpha: straight (default, as composited) or premultiplied "
                        "by the alpha; reported as alpha_mode")


def alpha_requested(args) -> bool:
    return bool(getattr(args, "keep_alpha", False) or getattr(args, "transparent", False))


def check_alpha_args(args, output: Optional[str]) -> Optional[str]:
    """Validates the alpha flags against each other and the output name; returns the alpha codec
    (None when no alpha line was asked for). Sets STATE.alpha_line so the colour helpers keep the
    source's tags (decision.keeps_source_tags)."""
    from _common.emit import die  # emit imports runner; imported here to keep this module light
    flag = "--transparent" if hasattr(args, "transparent") else "--keep-alpha"
    if not alpha_requested(args):
        if args.alpha_codec or args.alpha_mode:
            die(f"--alpha-codec and --alpha-mode apply with {flag}", kind="input")
        return None
    if getattr(args, "drop_alpha", False):
        die("--keep-alpha and --drop-alpha ask for opposite things: give one", kind="input")
    if STATE.codec:
        die(f"{flag} writes its own alpha line (--alpha-codec); --codec {STATE.codec} cannot carry an alpha channel",
            kind="input", hint=f"drop --codec, or drop {flag}")
    codec = args.alpha_codec or ALPHA_CODEC_DEFAULT
    line = ALPHA_CODECS[codec]
    if output is not None:
        ext = os.path.splitext(output)[1].lower()
        if ext not in line["ext"]:
            die(f"{flag} --alpha-codec {codec} needs a {' or '.join(line['ext'])} output; {output} cannot hold it",
                kind="input", hint=f"pass -o NAME{line['ext'][0]}")
    encoders = ffmpeg_encoders()
    if encoders and line["encoder"] not in encoders:
        die(f"--alpha-codec {codec} needs the {line['encoder']} encoder and this ffmpeg build has none",
            kind="missing_tool", error_extra={"reason": "encoder_missing", "details": {"name": line["encoder"]}},
            hint="python3 scripts/_contract.py doctor lists the encoders this build has; --alpha-codec prores4444 or png "
                 "need only FFmpeg's own encoders")
    STATE.alpha_line = codec
    return codec


def default_ext(codec: str) -> str:
    return ALPHA_CODECS[codec]["ext"][0].lstrip(".")


def video_line(codec: str) -> List[str]:
    return list(ALPHA_CODECS[codec]["video"])


def audio_line(codec: str) -> List[str]:
    return list(ALPHA_CODECS[codec]["audio"])


_TAG_KEYS = (("colorspace", "color_space", "-colorspace"), ("color_primaries", "color_primaries", "-color_primaries"),
             ("color_trc", "color_transfer", "-color_trc"))


def _source_tags(meta: Optional[Dict[str, Any]]) -> List[tuple]:
    v = (meta or {}).get("video") or {}
    return [(param, v.get(key), flag) for param, key, flag in _TAG_KEYS
            if v.get(key) and v.get(key) not in ("unknown", "reserved", "unspecified")]


def finish_chain(codec: str, mode: Optional[str], meta: Optional[Dict[str, Any]] = None) -> str:
    """The end of a filter chain that hands an alpha picture to the line: premultiplied colour
    when asked, the source's colour tags put back on the frames (`setparams`: a grade's RGB legs
    and an RGB layer's conversion relabel them, BT.601 or unknown), then the line's own pixel
    format (so no later conversion can drop the plane)."""
    tags = _source_tags(meta)
    label = ("setparams=" + ":".join(f"{p}={val}" for p, val, _ in tags) + ",") if tags else ""
    # premultiplied colour is colour x alpha in RGB: multiplied there (a YUV premultiply scales the
    # limited-range offsets too), after the tags are back so both conversions use the same matrix
    return (label + ("format=gbrap,premultiply=inplace=1," if mode == "premultiplied" else "")
            + f"format={ALPHA_CODECS[codec]['pix_fmt']}")


def tag_args(meta: Optional[Dict[str, Any]]) -> List[str]:
    """The source's colour tags as output options, so the written stream says what the frames do
    (an alpha line keeps the source's tags, as --codec prores does)."""
    out: List[str] = []
    for _p, val, flag in _source_tags(meta):
        out += [flag, val]
    return out


def written_line(output_meta: Dict[str, Any], output: str) -> Dict[str, Any]:
    """What the written stream is: {codec, pix_fmt, alpha_plane} (alpha_plane: the stream stores one)."""
    v = (output_meta or {}).get("video") or {}
    return {"codec": v.get("codec"), "pix_fmt": v.get("pix_fmt"), "alpha_plane": has_alpha_plane(output_meta, output)}


def kept_step(output: str, output_meta: Dict[str, Any], source: "Dict[str, object] | None", *,
              composite: bool, provenance: str = "input_premeasurement") -> Dict[str, Any]:
    """The `alpha` verification step of a --keep-alpha / --transparent run.

    `composite` False (color.py, background.py --transparent against an all-zero source): the
    alpha is not touched by the operation, so the written alpha must equal the source's frame by
    frame (alpha_compare). `composite` True (graphics.py, overlay.py): layers drawn over the
    picture add coverage, so the written alpha may only be at or above the source's in every
    frame, and must not have gone opaque in every frame the source was transparent in (what an
    alpha dropped on the way reads as). In both, the written stream must store an alpha plane."""
    unmeasured = bool(source and source.get("unmeasured"))
    source = _measured(source)
    line = written_line(output_meta, output)
    written = alpha_stats(output, line["codec"])
    step: Dict[str, Any] = {"step": "alpha", "property": "alpha_mean", "tolerance": ALPHA_TOLERANCE,
                            "expected": None if source is None else round(source["mean"], 2),
                            "measured": None if written is None else round(written["mean"], 2),
                            "frames": {"expected": rounded(source), "measured": rounded(written)},
                            "written": line, "provenance": provenance}
    if unmeasured:
        step["reason"] = "source_alpha_unmeasured"
    if not composite:
        cmp = alpha_compare(written, source)
        step.update(comparison=cmp, ok=bool(cmp["ok"] and line["alpha_plane"]))
        return step
    step["property"] = "alpha_at_least_source"
    if written is None or source is None:
        step.update(ok=False, comparison={"ok": False, "paired": None, "worst_delta": None, "worst_frame": None})
        return step
    w, s = written["per_frame"], source["per_frame"]
    paired = len(w) == len(s)
    if paired:
        deficits = [b - a for a, b in zip(w, s)]
        worst = max(range(len(deficits)), key=deficits.__getitem__)
        below = deficits[worst] > ALPHA_TOLERANCE
        opaque_where_transparent = all(a >= OPAQUE for a, b in zip(w, s) if b < OPAQUE) and any(b < OPAQUE for b in s)
        cmp = {"paired": True, "worst_delta": round(max(deficits[worst], 0.0), 2), "worst_frame": worst}
    else:
        below = written["min"] < source["min"] - ALPHA_TOLERANCE
        opaque_where_transparent = written["min"] >= OPAQUE and source["min"] < OPAQUE
        cmp = {"paired": False, "worst_delta": round(max(source["min"] - written["min"], 0.0), 2), "worst_frame": None}
    ok = line["alpha_plane"] and not below and not opaque_where_transparent
    cmp["ok"] = ok
    if opaque_where_transparent:
        step["reason"] = "opaque_everywhere"
    elif below:
        step["reason"] = "alpha_below_source"
    elif not line["alpha_plane"]:
        step["reason"] = "no_alpha_plane"
    step.update(comparison=cmp, ok=ok)
    return step


def lost_step(output: str, output_meta: Dict[str, Any], source: "Dict[str, object] | None") -> Dict[str, Any]:
    """The `alpha` step of a run without --keep-alpha on a source whose alpha is used: the output
    stores no alpha plane (every re-encoding line but the alpha ones is opaque), so it fails, with
    the reason and the flag that keeps it. Measured, not assumed: a written file that does carry
    the source's alpha passes. A source whose alpha could not be measured (UNMEASURED) fails
    with reason source_alpha_unmeasured: nothing shows the output kept what it had."""
    unmeasured = bool(source and source.get("unmeasured"))
    source = _measured(source)
    line = written_line(output_meta, output)
    written = alpha_stats(output, line["codec"]) if line["alpha_plane"] else None
    cmp = alpha_compare(written, source) if written is not None else {"ok": False, "paired": None,
                                                                         "worst_delta": None, "worst_frame": None}
    step: Dict[str, Any] = {"step": "alpha", "property": "alpha_mean", "ok": bool(cmp["ok"]), "comparison": cmp,
                            "tolerance": ALPHA_TOLERANCE,
                            "expected": None if source is None else round(source["mean"], 2),
                            "measured": round(written["mean"], 2) if written is not None else 255.0,
                            "frames": {"expected": rounded(source), "measured": rounded(written)},
                            "written": line, "provenance": "input_premeasurement"}
    if not step["ok"]:
        step.update(reason="source_alpha_unmeasured" if unmeasured and line["alpha_plane"] else "alpha_dropped",
                    attribution="artifact",
                    hint="pass --keep-alpha to write an alpha line, or --drop-alpha when an opaque output is wanted")
    return step


def source_alpha(args, meta: Dict[str, Any], path: str) -> "Dict[str, object] | None":
    """The source's alpha measured once, before the run, when it can matter: the source stores an
    alpha plane and this is not a dry run. Refuses --keep-alpha on a source without one (nothing to
    keep). Returns None when there is nothing to measure."""
    from _common.emit import die
    if STATE.dry_run and _runner.dry_run_input_pending(path):
        # a planned input an earlier step will write (a --transparent canvas in a recipe): there is
        # nothing to probe yet, so the alpha checks wait for the real run
        return None
    plane = has_alpha_plane(meta, path)
    codec = ((meta or {}).get("video") or {}).get("codec")
    if plane and codec == "vp9" and not libvpx_vp9_decoder():
        _no_vp9_decoder(path)
    if getattr(args, "keep_alpha", False) and not plane:
        die(f"--keep-alpha keeps the source's alpha channel and {path} has none "
            f"({((meta or {}).get('video') or {}).get('pix_fmt')}, fully opaque)", kind="input",
            hint="background.py --transparent makes a transparent canvas to draw on; drop --keep-alpha for an opaque output")
    if not plane or STATE.dry_run:
        return None
    return alpha_stats(path, codec) or UNMEASURED


def decoder_args_for(meta: Dict[str, Any], path: str) -> List[str]:
    """The input options a source with alpha needs to arrive with it: libvpx-vp9 for a VP9 stream
    tagged with an alpha layer (the native decoder drops it). [] for anything else."""
    v = (meta or {}).get("video") or {}
    if v.get("codec") != "vp9" or not vp9_alpha_tagged(path):
        return []
    if not libvpx_vp9_decoder():
        # FFmpeg's own decoder would read it without the alpha, and a layer would cover what is
        # under it: refused, not composited wrong
        _no_vp9_decoder(path)
    return ["-c:v", "libvpx-vp9"]


def _no_vp9_decoder(path: str) -> None:
    from _common.emit import die
    die(f"{path} is VP9 with an alpha layer, and this ffmpeg build has no libvpx-vp9 decoder to read it "
        "(FFmpeg's own VP9 decoder drops the alpha)", kind="missing_tool",
        error_extra={"reason": "decoder_missing", "details": {"name": "libvpx-vp9"}},
        hint="use an ffmpeg built with libvpx, or a ProRes 4444 / qtrle / PNG source")


def report(args, codec: Optional[str], src: "Dict[str, object] | None", output: Optional[str],
           extra: Dict[str, Any], composite: bool, provenance: str = "input_premeasurement") -> None:
    """Adds the alpha fields and the `alpha` step to a result's `extra` (after the write)."""
    from _common.emit import note, warn
    from _common.probe import probe
    if codec:
        extra["alpha_mode"] = args.alpha_mode or "straight"
        extra["alpha_codec"] = codec
        if output and not STATE.dry_run:
            extra.setdefault("verification", []).append(kept_step(output, probe(output, role="output"), src,
                                                                  composite=composite, provenance=provenance))
        return
    if not uses_alpha(src) or not output or STATE.dry_run:
        return
    if getattr(args, "drop_alpha", False):
        note("the source's alpha channel was dropped (--drop-alpha): the output is opaque")
        extra["alpha_dropped"] = True
        return
    step = lost_step(output, probe(output, role="output"), src)
    extra.setdefault("verification", []).append(step)
    if not step["ok"]:
        extra["alpha_dropped"] = True
        warn("the source has an alpha channel and this output does not keep it: pass --keep-alpha to keep it, "
             "or --drop-alpha when an opaque output is wanted", "alpha_dropped")
