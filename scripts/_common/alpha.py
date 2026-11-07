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
from typing import Any, Dict, List, Optional

from _common.runner import STATE, ffmpeg_encoders, require_tool, run, run_analysis

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


def vp9_decoder_args(codec: Optional[str]) -> List[str]:
    """The input option that decodes a VP9 stream with libvpx-vp9: FFmpeg's native vp9 decoder
    drops the alpha layer (a WebM's yuva420p comes out yuv420p, fully opaque). [] for any other
    codec, or when this build has no libvpx (its encoder list stands in for the decoder's)."""
    return ["-c:v", "libvpx-vp9"] if codec == "vp9" and "libvpx-vp9" in ffmpeg_encoders() else []


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
    return bool(ALPHA_PIX.match(v.get("pix_fmt") or "")) or (v.get("codec") == "vp9" and vp9_alpha_tagged(path))


def frame_means(cmd_head: List[str], path: str, chain: str) -> "Dict[str, object] | None":
    """Every decoded frame of `path` through `chain` to a 64x36 grey copy: {mean (over every frame),
    min (the lowest frame's mean), frames, per_frame (each frame's mean, in decode order)}. None
    when no frame decodes."""
    w, h = _MEASURE_W, _MEASURE_H
    cmd = cmd_head + ["-i", path, "-map", "0:v:0", "-vf", f"{chain},scale={w}:{h}:flags=area,format=gray",
                      "-f", "rawvideo", "-"]
    proc = run_analysis(cmd, check=False, text=False)
    data = proc.stdout or b""
    size = w * h
    if proc.returncode != 0 or len(data) < size:
        return None
    frames = [sum(data[i:i + size]) / size for i in range(0, len(data) - size + 1, size)]
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


def uses_alpha(st) -> bool:
    """True when a measured clip has a frame that is not fully opaque (its alpha is used)."""
    return st is not None and st["min"] < OPAQUE


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


def finish_chain(codec: str, mode: Optional[str]) -> str:
    """The end of a filter chain that hands an alpha picture to the line: premultiplied colour
    when asked, then the line's own pixel format (so no later conversion can drop the plane)."""
    return ("premultiply=inplace=1," if mode == "premultiplied" else "") + f"format={ALPHA_CODECS[codec]['pix_fmt']}"


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
    line = written_line(output_meta, output)
    written = alpha_stats(output, line["codec"])
    step: Dict[str, Any] = {"step": "alpha", "property": "alpha_mean", "tolerance": ALPHA_TOLERANCE,
                            "expected": None if source is None else round(source["mean"], 2),
                            "measured": None if written is None else round(written["mean"], 2),
                            "frames": {"expected": rounded(source), "measured": rounded(written)},
                            "written": line, "provenance": provenance}
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
    the source's alpha passes."""
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
        step.update(reason="alpha_dropped", attribution="artifact",
                    hint="pass --keep-alpha to write an alpha line, or --drop-alpha when an opaque output is wanted")
    return step


def source_alpha(args, meta: Dict[str, Any], path: str) -> "Dict[str, object] | None":
    """The source's alpha measured once, before the run, when it can matter: the source stores an
    alpha plane and this is not a dry run. Refuses --keep-alpha on a source without one (nothing to
    keep). Returns None when there is nothing to measure."""
    from _common.emit import die
    plane = has_alpha_plane(meta, path)
    if getattr(args, "keep_alpha", False) and not plane:
        die(f"--keep-alpha keeps the source's alpha channel and {path} has none "
            f"({((meta or {}).get('video') or {}).get('pix_fmt')}, fully opaque)", kind="input",
            hint="background.py --transparent makes a transparent canvas to draw on; drop --keep-alpha for an opaque output")
    if not plane or STATE.dry_run:
        return None
    return alpha_stats(path, ((meta or {}).get("video") or {}).get("codec"))


def decoder_args_for(meta: Dict[str, Any], path: str) -> List[str]:
    """The input options a source with alpha needs to arrive with it: libvpx-vp9 for a VP9 stream
    tagged with an alpha layer (the native decoder drops it). [] for anything else."""
    v = (meta or {}).get("video") or {}
    return vp9_decoder_args("vp9") if v.get("codec") == "vp9" and vp9_alpha_tagged(path) else []


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
