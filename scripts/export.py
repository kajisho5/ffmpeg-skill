#!/usr/bin/env python3
"""Export with delivery presets. Scales/pads to the preset's frame (keeping
the source aspect inside it), constrains duration where the platform does,
sets BT.709 tags, and picks sensible codecs/bitrates.

Presets:
  youtube   1920x1080 H.264 CRF 18 high profile, AAC 192k, 48 kHz, faststart
  youtube4k 3840x2160 H.264 CRF 18, AAC 192k
  reels     1080x1920 9:16 H.264 CRF 20, AAC 128k, max 90 s (Instagram Reels)
  tiktok    1080x1920 9:16 H.264 CRF 20, AAC 128k, max 600 s
  shorts    1080x1920 9:16 H.264 CRF 20, AAC 128k, max 180 s (YouTube Shorts)
  linkedin  1080x1080 1:1 H.264 CRF 20, AAC 128k, max 600 s
  facebook  1920x1080 16:9 H.264 CRF 21, AAC 128k
  youtube-hdr HEVC Main10 keeping the source's HDR10/HLG tags (refuses an SDR source)
  youtube-av1 1080p AV1 (libsvtav1, libaom fallback); missing_tool when neither is built
  x         1280x720 H.264 CRF 22, AAC 128k, max 140 s (Twitter/X)
  prores    ProRes 422 HQ .mov, PCM 16-bit audio (editing master)
  dnxhr-lb / dnxhr-sq / dnxhr-hq   DNxHR 8-bit 4:2:2 .mov, PCM 16-bit audio
  dnxhr-hqx DNxHR HQX 10-bit 4:2:2;  dnxhr-444  DNxHR 444 10-bit 4:4:4
            (editing masters at the source's size and rate, like prores)
  key-fill  fill + key pair (<out>, <out stem>_key.mov) from an alpha source
  prores4444 / prores4444xq / qtrle / vp9-alpha / hap-alpha
            masters that keep the source's alpha (refused without one);
            --alpha-mode straight|premultiplied; alpha read back after
  h265      HEVC CRF 24 (libx265) with hvc1 tag for Apple compatibility
  gif       480px wide palette-optimised GIF at 12 fps (short previews)
  copy      stream copy, no re-encode: same codecs, container and colour
            tags as the source (a delivery target with nothing to change)

Examples:
  python3 export.py final.mp4 --preset youtube
  python3 export.py final.mp4 --preset reels --fit crop
  python3 export.py final.mp4 --preset reels --normalize   # meet the platform's loudness in the same call
  python3 export.py final.mp4 --preset prores -o master.mov
  python3 export.py final.mp4 --preset dnxhr-hq -o master.mov
  python3 export.py final.mp4 --preset copy -o delivered.mp4
  python3 export.py --list
"""
import argparse
import json
import math
import re
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

from _common.runner import child_exit_code, fail_if_classified, kept_clause, mark_delivered
from _common import STATE, run_analysis, add_common, apply_common, bt709_label_filter, bt709_matrix_args, bt709_tag_args, child_args, emit, cfr_args, default_output, die, encoder_args, ffmpeg_base, info, probe, require_tool, run, run_tool, validate_color, pad_filters, add_pad_fill_args, fmt_secs
from _common.decision import hw_preset_video, restate_last_swap
from _common.emit import note, record_fallback, record_skip, warn
from _common.probe import square_pixels, square_pixels_note
from _common.runner import ffmpeg_encoders, guard_sidecar, remember_written, run_analysis as _run_analysis, subtitle_codec_for
from _common.emit import file_identity
from check import SPECS as PLATFORMS, measure_loudness
from _platforms import ALIASES as _ALIASES, PLATFORMS as PLATFORM_TABLE, TP_TOLERANCE_DB, resolve as resolve_platform
# Frame and duration limit come from the one platform table (scripts/_platforms.py) rather than
# from a literal restated here: before 1.14 they were typed twice and the facebook preset had
# already drifted (no duration cap against the table's 14400 s).

def _loudness_step(ok: bool, platform: str, spec: dict, m: dict) -> dict:
    """export's loudness verification step: the platform's targets, what was measured, the
    difference and the tolerance each was held to (docs/contract.md, 2.18 keys)."""
    expected = {"lufs": spec["lufs"], "tp_max": spec["tp"]}
    measured = {"lufs": m["lufs"], "tp": m["tp"]}
    delta = {"lufs": round(m["lufs"] - spec["lufs"], 2) if math.isfinite(m["lufs"]) else None,
             "tp": round(m["tp"] - spec["tp"], 2) if math.isfinite(m["tp"]) else None}
    return {"step": "loudness", "ok": ok, "platform": platform, "property": "loudness",
            "expected": expected, "measured": measured, "delta": delta,
            "tolerance": {"lufs": spec["lufs_tol"], "tp": TP_TOLERANCE_DB}, "provenance": "specification"}

def _from_table(dest: str, **over) -> Dict:
    """A preset's w/h/max read from PLATFORMS[dest], with the encoder settings given here.

    `over` is for the two presets that are deliberately not the destination's own frame or cap:
    `youtube4k` delivers to YouTube at 2160p, and neither youtube preset trims at YouTube's
    12-hour limit (check.py reports it; export.py has never cut a long upload and does not start).
    """
    frame = PLATFORM_TABLE[dest]["frame"] or {}
    spec = PLATFORM_TABLE[dest]["spec"]
    max_duration = spec.get("max_duration")
    out = {"w": frame.get("w"), "h": frame.get("h"),
           "max": float(max_duration) if max_duration is not None else None}
    out.update(over)
    return out


_H264_HIGH = ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"]
_AAC_192 = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
_AAC_128 = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000"]


def _social(crf: str = "20") -> List[str]:
    return ["-c:v", "libx264", "-preset", "medium", "-crf", crf, "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30"]


PRESETS: Dict[str, Dict] = {
    "youtube": dict(_from_table("youtube", max=None), ext="mp4", video=_H264_HIGH, audio=_AAC_192, desc="1080p H.264, AAC 192k"),
    "youtube4k": dict(_from_table("youtube", w=3840, h=2160, max=None), ext="mp4", video=_H264_HIGH, audio=_AAC_192, desc="2160p H.264, AAC 192k"),
    "reels": dict(_from_table("reels"), ext="mp4", video=_social(), audio=_AAC_128, desc="9:16 1080x1920, 30fps, max 90s (Instagram Reels)"),
    "x": dict(_from_table("x"), ext="mp4", video=_social("22"), audio=["-c:a", "aac", "-b:a", "128k", "-ar", "44100"], desc="720p H.264, max 140s (Twitter/X)"),
    "prores": {"w": None, "h": None, "ext": "mov", "video": ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"], "audio": ["-c:a", "pcm_s16le"], "max": None, "intermediate": True,
               "expect": {"codec": "prores", "profile": "HQ", "pix_fmt": "yuv422p10le"}, "desc": "ProRes 422 HQ master, PCM audio, source resolution"},
    # DNxHR (the dnxhd encoder's resolution-independent profiles): editing masters like prores, at
    # the source's size and rate; the written profile and pixel format are checked after the write
    **{f"dnxhr-{name}": {"w": None, "h": None, "ext": "mov",
                         "video": ["-c:v", "dnxhd", "-profile:v", f"dnxhr_{name}", "-pix_fmt", pix],
                         "audio": ["-c:a", "pcm_s16le"], "max": None, "intermediate": True,
                         "expect": {"codec": "dnxhd", "profile": f"DNXHR {name.upper()}", "pix_fmt": pix},
                         "desc": f"DNxHR {name.upper()} master ({desc}), PCM audio, source resolution"}
       for name, pix, desc in (("lb", "yuv422p", "8-bit 4:2:2, low bandwidth"), ("sq", "yuv422p", "8-bit 4:2:2, standard"),
                               ("hq", "yuv422p", "8-bit 4:2:2, high quality"), ("hqx", "yuv422p10le", "10-bit 4:2:2"),
                               ("444", "yuv444p10le", "10-bit 4:4:4"))},
    # Alpha masters (#417): editing masters that keep the source's alpha channel; the alpha is read
    # back from a written frame and compared with the source's. A source without alpha is refused.
    "prores4444": {"w": None, "h": None, "ext": "mov", "alpha": True, "intermediate": True,
                   "video": ["-c:v", "prores_ks", "-profile:v", "4", "-vendor", "apl0", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16"],
                   "audio": ["-c:a", "pcm_s16le"], "max": None, "expect": {"codec": "prores", "profile": "4444"},
                   "desc": "ProRes 4444 with alpha (16-bit alpha), PCM audio, source resolution"},
    "prores4444xq": {"w": None, "h": None, "ext": "mov", "alpha": True, "intermediate": True,
                     "video": ["-c:v", "prores_ks", "-profile:v", "5", "-vendor", "apl0", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16"],
                     "audio": ["-c:a", "pcm_s16le"], "max": None, "expect": {"codec": "prores", "profile": "XQ"},
                     "desc": "ProRes 4444 XQ with alpha (16-bit alpha), PCM audio, source resolution"},
    "qtrle": {"w": None, "h": None, "ext": "mov", "alpha": True, "intermediate": True,
              "video": ["-c:v", "qtrle", "-pix_fmt", "argb"], "audio": ["-c:a", "pcm_s16le"], "max": None,
              "expect": {"codec": "qtrle", "pix_fmt": "argb"}, "desc": "QuickTime Animation (lossless RGB + alpha), PCM audio"},
    "vp9-alpha": {"w": None, "h": None, "ext": "webm", "alpha": True, "intermediate": True,
                  "video": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "20", "-b:v", "0", "-row-mt", "1"],
                  "audio": ["-c:a", "libopus", "-b:a", "128k"], "max": None, "expect": {"codec": "vp9"},
                  "desc": "WebM VP9 with alpha (CRF 20), Opus audio, source resolution"},
    "hap-alpha": {"w": None, "h": None, "ext": "mov", "alpha": True, "intermediate": True,
                  "video": ["-c:v", "hap", "-format", "hap_alpha"], "audio": ["-c:a", "pcm_s16le"], "max": None,
                  "expect": {"codec": "hap"}, "desc": "HAP Alpha (needs an ffmpeg built with snappy; size a multiple of 4), PCM audio"},
    # Key and fill for a switcher's downstream keyer (#418): two ProRes 422 HQ files from one alpha
    # source, the fill (colour) and the key (the alpha as a luma matte), frame for frame.
    "key-fill": {"w": None, "h": None, "ext": "mov", "alpha": True, "intermediate": True, "keyfill": True,
                 "video": ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"],
                 "audio": ["-c:a", "pcm_s16le"], "max": None,
                 "desc": "fill + key pair (<out> and <out stem>_key.mov), ProRes 422 HQ, frame for frame, for a switcher's keyer"},
    "h265": {"w": None, "h": None, "ext": "mp4", "video": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"], "audio": ["-c:a", "aac", "-b:a", "160k"], "max": None, "desc": "HEVC CRF 24, hvc1 tag, source resolution"},
    "gif": {"w": 480, "h": None, "ext": "gif", "video": [], "audio": [], "max": None, "desc": "480px palette GIF, 12fps"},
    "copy": {"w": None, "h": None, "ext": None, "video": ["-c:v", "copy"], "audio": ["-c:a", "copy"], "max": None, "desc": "stream copy, no re-encode (source codecs/container/colour tags unchanged)"},
    # 1.14: the destinations that used to be aliases of reels/youtube are their own presets, each
    # sized and length-limited from the one platform table (scripts/_platforms.py) rather than from
    # a comment. `reels` keeps its historical settings byte-for-byte so existing calls are unchanged.
    "tiktok": dict(_from_table("tiktok"), ext="mp4", video=_social(), audio=_AAC_128, desc="9:16 1080x1920, 30fps, max 600s (TikTok)"),
    "shorts": dict(_from_table("shorts"), ext="mp4", video=_social(), audio=_AAC_128, desc="9:16 1080x1920, 30fps, max 180s (YouTube Shorts)"),
    "linkedin": dict(_from_table("linkedin"), ext="mp4", video=_social(), audio=_AAC_128, desc="1:1 1080x1080, 30fps, max 600s (LinkedIn)"),
    "facebook": dict(_from_table("facebook"), ext="mp4", video=_social("21"), audio=_AAC_128, desc="16:9 1920x1080, 30fps, max 14400s (Facebook feed)"),
    # HDR and AV1 deliveries: the encoder line comes from encoder_args() so the source's own
    # HDR tags survive (hevc) and the AV1 encoder is chosen/refused in one place.
    "youtube-hdr": {"w": None, "h": None, "ext": "mp4", "codec": "hevc", "video": [], "audio": _AAC_192, "max": None, "hdr_only": True, "desc": "HEVC Main10, source HDR10/HLG tags kept, AAC 192k (refuses an SDR source)"},
    "youtube-av1": dict(_from_table("youtube", max=None), ext="mp4", codec="av1", video=[], audio=_AAC_192, desc="1080p AV1 (libsvtav1, libaom fallback), AAC 192k"),
}



# which check.py platform a preset targets (its loudness spec is measured after the write)
HERE = Path(__file__).resolve().parent
# broadcast's "preset" is prores, an editing master rather than a delivery: nothing is measured
# against a loudness spec after writing it, exactly as before 1.14.
_NOT_A_DELIVERY = frozenset({"broadcast"})
# Derived from the same table: a destination whose "preset" is this one is the compliance target
# its loudness is measured against (youtube4k and the two youtube variants deliver to youtube).
PLATFORM_OF: Dict[str, str] = {PLATFORM_TABLE[n]["preset"]: PLATFORM_TABLE[n]["check"]
                               for n in sorted(PLATFORM_TABLE)
                               if PLATFORM_TABLE[n].get("preset") in PRESETS and PLATFORM_TABLE[n]["frame"]
                               and n not in _NOT_A_DELIVERY}
PLATFORM_OF["youtube4k"] = PLATFORM_TABLE["youtube"]["check"]
# Aliases people write for a destination ('youtube-shorts', 'ig', 'twitter') name the same preset.
PRESET_CHOICES: List[str] = sorted(set(PRESETS) | {a for a in _ALIASES if resolve_platform(a) in PRESETS})


# The alpha helpers (#417) live in _common.alpha since color.py, graphics.py, overlay.py and
# background.py write alpha lines too; the names this module has always had stay bound here.
from _common.alpha import (ALPHA_PIX as _ALPHA_PIX, ALPHA_TOLERANCE, OPAQUE, alpha_stats,  # noqa: E402
                           alpha_compare as _alpha_compare, frame_means as _frame_means, rounded as _rounded,
                           decoder_args_for, vp9_alpha_tagged)


def key_path(fill: str) -> str:
    stem, _ = os.path.splitext(fill)
    return f"{stem}_key.mov"


def _key_fill(args, p: Dict, meta: Dict, output: str, cmd: List[str], vf: List[str], has_audio: bool,
              source_alpha, notes: List[str], subs: List[Dict], data: List[Dict]) -> int:
    """--preset key-fill: one decode split into the fill (the colour, straight or premultiplied)
    and the key (alphaextract: alpha 255 is video white, 0 black), both ProRes 422 HQ in one ffmpeg
    run so they hold the same frames; the source's start timecode is written on both. Checked
    after: the same frame count, size, rate and length, the key's mean level against the source's
    alpha, and both files hashed (output_identity, key.identity)."""
    key = key_path(output)
    # both files are this run's outputs, but ffmpeg's last argument (which run() guards and stages)
    # is only the key: the fill is checked here the same way -- not the input under another
    # spelling, not someone's file without --overwrite -- and written through a hidden temp file
    guard_sidecar(output, args.input, siblings=[key])
    guard_sidecar(key, args.input, siblings=[output])
    if STATE.hw and "-c:v" in p["video"]:
        note(f"--hw: --preset {args.preset} stays on {p['video'][p['video'].index('-c:v') + 1]}: one ffmpeg run writes "
             "the fill and the key as a pair, and VideoToolbox's ProRes encoder is not used for it")
    fill_chain = ",".join(vf + (["premultiply=inplace=1"] if args.alpha_mode == "premultiplied" else []) + ["format=yuv422p10le"])
    key_chain = ",".join(vf + ["alphaextract", "format=yuv422p10le"])
    tc = ((meta.get("timecode") or {}).get("value"))
    tc_args = ["-timecode", tc] if tc else []
    cmd = cmd + ["-filter_complex", f"[0:v:0]split[f][k];[f]{fill_chain}[fill];[k]{key_chain}[key]"]
    cmd += ["-map", "[fill]"] + (["-map", "0:a:0"] if has_audio else []) + p["video"] + tc_args + cfr_args(meta)
    # the fill is always written to a hidden sibling and moved into place only after the encode
    # succeeds: run() stages and cleans up only ffmpeg's last output (the key), so a failed encode
    # left a partial new fill (the retry was refused as output_exists) or truncated an existing one
    fill_tmp = None
    if not STATE.dry_run:
        d, base = os.path.split(output)
        stem, ext = os.path.splitext(base)
        fill_tmp = os.path.join(d, f".{stem}.ffskill-fill-{os.getpid()}{ext}")
    cmd += (p["audio"] if has_audio else ["-an"]) + [fill_tmp or output]
    cmd += ["-map", "[key]"] + p["video"] + tc_args + cfr_args(meta) + ["-an", key]
    try:
        run(cmd)
        if fill_tmp:
            os.replace(fill_tmp, output)
    finally:
        if fill_tmp:
            # the command is recorded with the path the caller asked for, not the temp name
            STATE.commands[:] = [c.replace(fill_tmp, output) for c in STATE.commands]
            if os.path.exists(fill_tmp):
                os.remove(fill_tmp)
    remember_written(output, key)
    extra: Dict[str, object] = {"alpha_mode": args.alpha_mode or "straight", "key": {"output": key}}
    # a fill and a key for a switcher carry the picture and the sound; the source's subtitle and
    # data streams are not written, and the document says so (as for a GIF)
    non_av = _non_av_report(subs, [], data, ["subtitle", "data"], output, "key_fill")
    extra["non_av_streams"] = non_av
    extra["dropped_non_av_streams"] = bool(non_av["dropped"])
    if non_av["dropped"]:
        notes.append(f"a key/fill pair holds the picture and the sound only: the source's {len(non_av['dropped'])} "
                     "subtitle/data stream(s) were not written; non_av_streams lists them")
    if STATE.dry_run:
        emit(output, **extra, **({"notes": notes} if notes else {}))
        return 0
    fill_m, key_m = probe(output, role="output"), probe(key, role="output")
    fv, kv = fill_m["video"], key_m["video"]
    pair = {k: [fv.get(k), kv.get(k)] for k in ("width", "height", "nb_frames", "r_frame_rate")}
    # the video streams' lengths: the fill's container also counts its sound, which may run longer
    # than the picture, and the key has none
    pair["duration"] = [round(v.get("duration") or v.get("tagged_duration") or 0, 3) for v in (fv, kv)]
    same = all(a == b and a not in (None, 0) for a, b in pair.values())
    steps = [{"step": "key_fill_pair", "property": "frames_size_rate_length", "ok": same, "measured": pair,
              "provenance": "output_measurement"}]
    key_level = _luma_stats(key)
    level = _alpha_compare(key_level, source_alpha)
    steps.append({"step": "key_level", "property": "key_mean_vs_source_alpha", "ok": level["ok"], "comparison": level,
                  "expected": None if source_alpha is None else round(source_alpha["mean"], 2),
                  "measured": None if key_level is None else round(key_level["mean"], 2), "tolerance": ALPHA_TOLERANCE,
                  "frames": {"expected": _rounded(source_alpha), "measured": _rounded(key_level)},
                  "provenance": "input_premeasurement"})
    extra["key"] = {"output": key, "identity": file_identity(key), "sha256": _sha256(key), "timecode": tc}
    extra["fill_sha256"] = _sha256(output)
    info(f"wrote {output} (fill) and {key} (key), {fv['width']}x{fv['height']}, {fv.get('nb_frames')} frames each")
    emit(output, verification=steps, expect_streams={"video": 1, "audio": 1 if has_audio else 0}, **extra,
         **({"notes": notes} if notes else {}))
    return 0


def _sha256(path: str) -> str:
    """The whole file's SHA-256: a key/fill pair is handed to a playout system as two files that
    must stay a pair, and the hashes let it check that neither was replaced."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _luma_stats(path: str) -> "Dict[str, float] | None":
    """The level (0-255) of every frame of a file, on a 64x36 grey copy: {mean, min, frames}."""
    return _frame_means([require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"], path, "format=gray")


def _loudness_unmeasured(extra: Dict[str, object], notes: List[str], platform: str, spec: Dict, normalized: bool = False) -> None:
    """The written file's loudness could not be read (ffmpeg's loudnorm JSON did not parse): the
    platform's loudness was not verified, and the document says so -- a `loudness` block with null
    values and a reason, a failing `loudness` verification step, a warning -- rather than leaving
    the block out, which read as "nothing to check". check.py reports the same case as a WARN row."""
    reason = "not_measured"
    extra["loudness"] = {"lufs": None, "tp": None, "target_lufs": spec["lufs"], "target_tp": spec["tp"], "ok": None,
                         "measured": False, "reason": reason, **({"normalized": True} if normalized else {})}
    extra["verification"] = [{"step": "loudness", "ok": False, "platform": platform, "reason": reason}]
    msg = (f"the written file's loudness could not be measured{' after --normalize' if normalized else ''} "
           f"(ffmpeg's loudnorm output did not parse), so {platform}'s {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP was not "
           "verified; run check.py on the file")
    notes.append(msg)
    warn(msg, "loudness_not_measured", platform=platform, normalized=normalized)


# Text subtitle codecs ffmpeg can convert to the container's own text track: mov_text is the one
# text track MP4/MOV hold, Matroska holds SubRip/ASS/WebVTT as they are but not mov_text.
# the -c:s for one source subtitle stream (#380), shared with caption.py --mode mux (#414): copy
# when the output container holds it as it is, else the container's own text format (a bitmap
# track is tried as a copy; a container that refuses it is the fallback below)
_subtitle_codec = subtitle_codec_for


def _data_streams(path: str) -> List[Dict[str, object]]:
    """The data streams of a file ({index, codec}), without its attachments (probe()'s
    data_streams counts both, and -map 0:d maps only the data streams)."""
    proc = run([require_tool("ffprobe"), "-v", "error", "-select_streams", "d", "-show_entries",
                "stream=codec_name,codec_tag_string", "-of", "json", path], quiet=True)
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
    except ValueError:
        # an unread list would map nothing and report nothing dropped
        die(f"ffprobe's data-stream list for {path} did not parse", kind="ffmpeg")
    return [{"index": n, "codec": s.get("codec_name") or s.get("codec_tag_string")} for n, s in enumerate(streams)]


def _run_keeping_non_av(cmd: List[str], output: str, sub_codecs: List[str], data: int) -> List[str]:
    """run_keeping_subtitles() for export: the subtitle streams go in the codec the container takes
    (_subtitle_codec), and a refused data stream does not cost the subtitles. The rungs are
    subtitles + data, subtitles alone, neither; each retry is a `non_av_streams_dropped` fallback
    with the attempt's error. `cmd` already maps the picture and the sound and has no output.
    Returns the stream types dropped ([] when everything mapped was written)."""
    sub_args: List[str] = ["-map", "0:s"] if sub_codecs else []
    for n, codec in enumerate(sub_codecs):
        sub_args += [f"-c:s:{n}", codec]
    data_args = ["-map", "0:d", "-c:d", "copy"] if data else []
    rungs = [(sub_args + data_args, [])]
    if sub_codecs and data:
        rungs.append((sub_args, ["data"]))
    rungs.append(([], (["subtitle"] if sub_codecs else []) + (["data"] if data else [])))
    for n, (extra, dropped) in enumerate(rungs):
        if n == len(rungs) - 1:
            run(cmd + extra + [output])
            return dropped
        attempt = run(cmd + extra + [output], check=False)
        if attempt.returncode == 0:
            return dropped
        # a full disk or a missing encoder fails every rung the same way: that error, not a
        # fallback that blames the subtitles and encodes again (#415, #389's rule)
        fail_if_classified(attempt)
        error = " | ".join([ln.strip() for ln in (attempt.stderr or "").splitlines() if ln.strip()][-3:])[-500:]
        going = rungs[n + 1][1]
        record_fallback(f"{os.path.basename(output)} could not hold the source's {' and '.join(t for t in ('subtitle', 'data') if t in going)} "
                        f"stream(s) ({error or 'ffmpeg exit ' + str(attempt.returncode)}); encoding again without them",
                        "non_av_streams_dropped", output=output, returncode=attempt.returncode, error=error, dropped=going)
    return []  # not reached: the last rung either returns or exits


def _written_data_codec(n: int, sources: List[Dict], written: List[Dict]) -> bool:
    """True when the written file holds a data track for source data stream `n`: tracks are
    matched by codec, never by position, so with k source streams of one codec and j tracks of it
    written, the first min(j, k) of those sources count as kept (a muxer's own timecode track is
    not credited to an unrelated stream, and two copied streams of one codec are both kept)."""
    codec = sources[n].get("codec")
    if not codec:
        return False
    rank = sum(1 for s in sources[:n] if s.get("codec") == codec)
    return rank < sum(1 for w in written if w.get("codec") == codec)


def _non_av_report(subs: List[Dict], sub_codecs: List[str], data: List[Dict], dropped: List[str],
                   output: str, reason: str) -> Dict[str, List[Dict]]:
    """`non_av_streams`: each source subtitle/data stream as kept (with the codec it was written in)
    or dropped (with why), read back from the written file; under --dry-run, as planned."""
    kept: List[Dict] = []
    gone: List[Dict] = []
    written_subs: List[Dict] = []
    written_data: List[Dict] = []
    if not STATE.dry_run and (subs or data):
        written_subs = probe(output, role="output").get("subtitle_stream_details") or []
        written_data = _data_streams(output)
    for kind, streams, written in (("subtitle", subs, written_subs), ("data", data, written_data)):
        for n, s in enumerate(streams):
            row = {"type": kind, "index": n, "codec": s.get("codec")}
            if kind == "subtitle":
                row["language"] = s.get("language")
            if STATE.dry_run and kind not in dropped:
                planned = sub_codecs[n] if kind == "subtitle" else "copy"
                kept.append(dict(row, output_codec=s.get("codec") if planned == "copy" else planned))
            elif kind == "subtitle" and n < len(written):
                kept.append(dict(row, output_codec=written[n].get("codec")))
            elif kind == "data" and _written_data_codec(n, streams, written):
                # read back, not assumed, and matched by codec: an MP4/MOV muxer writes a
                # timecode (tmcd) track of its own from the source's timecode tag even when the
                # copied one was refused
                kept.append(dict(row, output_codec=s.get("codec")))
            else:
                gone.append(dict(row, reason=reason if kind in dropped else "not_in_output"))
    return {"kept": kept, "dropped": gone}


# --repair (2.24): regenerate missing timestamps, drop packets flagged corrupt, keep demuxing past errors
REPAIR_INPUT_ARGS = ["-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err"]
_TIMESTAMP_WARNING = re.compile(r"(?i)\b(dts|pts)\b|timestamp")


def media_damage(path: str) -> Dict[str, int]:
    """One full decode of `path` at -v warning: lines about timestamps (non-monotonic DTS, invalid
    PTS) and every other error line, counted. What --repair is measured by, before and after."""
    # repeat+: every occurrence on its own line, not "Last message repeated N times", which hid
    # N timestamp warnings and was itself counted as a decode error
    proc = run_analysis([require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "repeat+warning", "-i", path, "-f", "null", "-"],
                        check=False, record=True)
    lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
    # "Packet corrupt (stream = 0, dts = ...)" names a dts but is damage, not a timestamp problem
    stamps = sum(1 for ln in lines if _TIMESTAMP_WARNING.search(ln) and "corrupt" not in ln.lower())
    return {"timestamp_warnings": stamps, "decode_errors": len(lines) - stamps}


MIB = 1024 * 1024
SIZE_HEADROOM = 0.97        # of the byte budget given to the streams; the rest is container overhead
SIZE_MIN_VIDEO_KBPS = 100   # below this the picture is not worth delivering; refused instead
SIZE_MAX_VIDEO_KBPS = 400_000  # 400 Mb/s: above any delivery line, and libx264 refuses far larger values


def size_video_args(args, video: List[str], p: Dict, meta: Dict, has_audio: bool) -> List[str]:
    """--max-mb: the preset's x264 line with its CRF replaced by the bitrate that fits the size,
    for a two-pass encode. Refused where that cannot be done honestly: another codec, --crf, --hw,
    a source with no duration, or a size too small for a watchable picture."""
    if args.crf is not None:
        die("--max-mb sets the bitrate from the size, --crf sets a quality: give one of them")
    if "-c:v" not in video or video[video.index("-c:v") + 1] != "libx264" or "-crf" not in video:
        die(f"--max-mb runs a two-pass x264 encode; --preset {args.preset} does not encode with x264"
            + (" (--hw puts it on VideoToolbox, which has no two-pass mode)" if STATE.hw else ""))
    if not math.isfinite(args.max_mb) or args.max_mb <= 0:
        die(f"--max-mb must be a positive number of MiB, got {args.max_mb:g}")
    dur = float(meta.get("duration") or 0.0)
    if p["max"] and not args.allow_long:
        dur = min(dur, float(p["max"]))
    if dur <= 0:
        die("--max-mb needs the source's duration, which it does not report")
    audio_kbps = 0.0
    if has_audio and "-b:a" in p["audio"]:
        audio_kbps = float(p["audio"][p["audio"].index("-b:a") + 1].rstrip("k"))
    video_kbps = args.max_mb * MIB * 8 * SIZE_HEADROOM / dur / 1000 - audio_kbps
    if video_kbps > SIZE_MAX_VIDEO_KBPS:
        die(f"--max-mb {args.max_mb:g} allows {video_kbps / 1000:.0f} Mb/s over {dur:.1f}s, beyond any delivery bitrate; "
            "a limit that large constrains nothing", hint="drop --max-mb (the preset's quality setting applies)")
    if video_kbps < SIZE_MIN_VIDEO_KBPS:
        die(f"--max-mb {args.max_mb:g} leaves {max(video_kbps, 0):.0f} kb/s for the picture over {dur:.1f}s "
            f"(after {audio_kbps:.0f} kb/s of audio); under {SIZE_MIN_VIDEO_KBPS} kb/s it is not watchable",
            hint="raise --max-mb, or cut the video shorter first")
    out = list(video)
    i = out.index("-crf")
    out[i:i + 2] = ["-b:v", f"{video_kbps:.0f}k"]
    info(f"--max-mb {args.max_mb:g}: {video_kbps:.0f} kb/s video + {audio_kbps:.0f} kb/s audio over {dur:.1f}s, two-pass")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output", help="output file (default: <name>_<preset>.<ext>)")
    ap.add_argument("--preset", choices=PRESET_CHOICES, help="delivery preset (aliases: " + ", ".join(a for a in _ALIASES if resolve_platform(a) in PRESETS) + ")")
    ap.add_argument("--fit", choices=["pad", "crop"], default="pad", help="how to reach the preset frame when aspect differs (default pad)")
    ap.add_argument("--pad-color", default="black")
    add_pad_fill_args(ap)
    ap.add_argument("--no-scale", action="store_true", help="keep source resolution even for platform presets")
    ap.add_argument("--allow-long", action="store_true", help="do not trim to the platform's max duration")
    ap.add_argument("--crf", type=int, help="override CRF")
    ap.add_argument("--repair", action="store_true",
                    help="--preset copy only: remux a damaged file -- timestamps regenerated, corrupt packets dropped, "
                         "negative timestamps shifted to zero -- and count the decode errors and timestamp warnings "
                         "before and after; the input is never touched")
    ap.add_argument("--max-mb", type=float, metavar="MB",
                    help="fit the file under MB megabytes (MiB): a two-pass x264 encode at the video bitrate the "
                         "running time leaves after the audio, measured afterwards (H.264 presets; not with --crf or --hw)")
    ap.add_argument("--normalize", action="store_true", help="youtube/youtube4k/reels/x: when the written file misses the platform's loudness spec, run loudness.py on it (audio re-encoded, video copied) so one export delivers")
    ap.add_argument("--alpha-mode", choices=["straight", "premultiplied"],
                    help="alpha presets (prores4444, prores4444xq, qtrle, vp9-alpha, hap-alpha): write the colour straight "
                         "(default, as decoded) or premultiplied by the alpha; written to the result as alpha_mode")
    ap.add_argument("--list", action="store_true", help="list presets and exit")
    add_common(ap, codec=False)  # the preset decides the codec; --codec would only be refused
    args = ap.parse_args()
    apply_common(args)
    if args.preset and args.preset not in PRESETS:
        args.preset = resolve_platform(args.preset)

    if args.list:
        for name, p in PRESETS.items():
            print(f"{name:10s} {p['desc']}")
        return 0
    if not args.input or not args.preset:
        die("input and --preset are required (or use --list)")
    validate_color(args.pad_color, "--pad-color")
    if args.normalize and args.preset not in PLATFORM_OF:
        die(f"--normalize applies to the platform presets ({', '.join(sorted(PLATFORM_OF))}); --preset {args.preset} has no loudness spec to meet",
            hint="drop --normalize, or run loudness.py with your own target")

    p = PRESETS[args.preset]
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    notes: List[str] = []
    if p.get("hdr_only") and not meta["video"].get("bt2020_or_hdr"):
        # The point of this preset is that the delivery stays HDR. Running it on an SDR source
        # would write a 10-bit HEVC file labelled with SDR tags and call it an HDR delivery.
        die(f"--preset {args.preset} delivers HDR and this source is SDR ({meta['video'].get('codec')}, "
            f"{meta['video'].get('color_transfer') or 'untagged'})",
            hint="use --preset youtube for an SDR delivery; there is no way to invent HDR range from an SDR master")
    if meta["video"].get("bt2020_or_hdr") and not p.get("intermediate") and args.preset not in ("copy", "youtube-hdr"):
        # 2.0: `hdr` is a real PQ/HLG/DV signal; bt2020_or_hdr also covers BT.2020 SDR, which is
        # not HDR but still needs converting before BT.709 tags describe it (eval 24 h1)
        kind = "HDR" if meta["video"].get("hdr") else "wide-gamut SDR, not HDR"
        notes.append("source is %s (%s). This preset outputs SDR BT.709 tags without converting it; run color.py --to-sdr first for correct colours." % (kind, meta["video"].get("hdr_format")))
        warn(notes[-1], "colour_not_converted", preset=args.preset, hdr_format=meta["video"].get("hdr_format"))
    has_audio = bool(meta.get("audio"))
    source_alpha = None
    if p.get("alpha"):
        encoder = p["video"][p["video"].index("-c:v") + 1]
        encoders = ffmpeg_encoders()
        if encoders and encoder not in encoders:
            die(f"--preset {args.preset} needs the {encoder} encoder and this ffmpeg build has none"
                + (" (HAP needs an ffmpeg built with snappy)" if encoder == "hap" else ""),
                kind="missing_tool", error_extra={"reason": "encoder_missing", "details": {"name": encoder}},
                hint="python3 scripts/_contract.py doctor lists the encoders this build has")
        if encoder == "hap" and (meta["video"]["width"] % 4 or meta["video"]["height"] % 4):
            die(f"--preset hap-alpha needs a width and height that are multiples of 4 (HAP's texture blocks); "
                f"this source is {meta['video']['width']}x{meta['video']['height']}",
                hint="crop or pad it first (crop.py, pad.py)")
        # a pixel format with an alpha plane, or a VP9 stream stored with one (probed as yuv420p);
        # a dry run decides on these metadata reads alone and decodes nothing
        has_alpha_plane = bool(_ALPHA_PIX.match(meta["video"].get("pix_fmt") or "")) or vp9_alpha_tagged(args.input)
        # a VP9 source stored with alpha on a build whose decoder list was read without libvpx-vp9
        # is refused (decoder_missing) before it is measured: FFmpeg's own VP9 decoder reads it
        # opaque, so the source and the written line both measured 255 and the alpha step passed
        # with the transparency gone (#433 review). An unreadable list keeps the decoder named.
        dec_args = decoder_args_for(meta, args.input)
        if not STATE.dry_run:
            source_alpha = alpha_stats(args.input, meta["video"].get("codec"))
        if not has_alpha_plane and (STATE.dry_run or source_alpha is None or source_alpha["min"] >= OPAQUE):
            die(f"--preset {args.preset} keeps an alpha channel and this source has none "
                f"({meta['video'].get('pix_fmt')}, fully opaque): use prores or dnxhr-* for an opaque master")
    elif args.alpha_mode:
        die("--alpha-mode applies only to the alpha presets (prores4444, prores4444xq, qtrle, vp9-alpha, hap-alpha)")
    # copy keeps the source's container, so its default name keeps the source's extension (as
    # metadata.py's does): default_output()'s .webm -> .mp4 is for the re-encoding presets
    output = args.output or default_output(args.input, args.preset, p["ext"] or Path(args.input).suffix.lstrip(".") or None)
    out_ext = Path(output).suffix.lstrip(".").lower()

    vf: List[str] = []
    # A GIF is RGB: an untagged SDR source is labelled BT.709 (tags only) for palettegen's conversion,
    # which read "unknown" as BT.601 (C03028 came out B31F28, #410); a tagged one is read by its tag
    gif_label = bt709_label_filter(meta) if args.preset == "gif" else None
    if p["w"] and not args.no_scale:
        if p["h"]:
            if args.fit == "crop":
                vf += [f"scale={p['w']}:{p['h']}:force_original_aspect_ratio=increase", f"crop={p['w']}:{p['h']}"]
            else:
                # a --pad-color with chroma is drawn in the BT.709 the line is tagged with; a GIF is
                # not tagged, and palettegen reads the pad back with the same BT.601 it was drawn in
                vf.append(pad_filters(p["w"], p["h"], args.pad_fill, args.pad_color, args.pad_blur,
                                      meta=None if args.preset == "gif" else meta))
            vf.append("setsar=1")
        else:
            vf.append(f"scale={p['w']}:-2")
        # sized in square pixels: a non-square-pixel master is squared at its display aspect
        # first, or the preset's frame would squash it (#411)
        if square_pixels(meta["video"]):
            vf.insert(0, square_pixels(meta["video"]))
            note(square_pixels_note(meta["video"]))
    if args.repair and args.preset != "copy":
        die("--repair is a remux: use it with --preset copy (a re-encoding preset already rebuilds every frame)")
    if args.max_mb is not None and args.preset == "gif":
        # the GIF branch below returns before the size is ever applied or measured
        die("--max-mb runs a two-pass x264 encode; --preset gif does not encode with x264 (shorten or shrink the GIF instead)")
    if args.max_mb is not None and p.get("keyfill"):
        # the key/fill branch below writes ProRes and returns before the size is applied or measured
        die("--max-mb runs a two-pass x264 encode; --preset key-fill writes ProRes (a fill and a key), which has no size target")
    # an alpha source in VP9 is decoded with libvpx-vp9, or its alpha never reaches the encoder
    # (decoder_args_for, above: [] for anything that is not VP9 stored with alpha)
    dec_args = dec_args if p.get("alpha") else []
    cmd = ffmpeg_base() + (REPAIR_INPUT_ARGS if args.repair else []) + dec_args + ["-i", args.input]
    # Subtitle and data streams (a soft-subtitle track muxed upstream, a camera's timecode) are
    # kept where the container can hold them: ffmpeg's default stream selection takes one video
    # and one audio stream only, and through 2.22.1 every preset dropped the rest without a word.
    # Mapping them means mapping the picture and the sound too, the same streams probe() describes.
    subs = meta.get("subtitle_stream_details") or []
    data = _data_streams(args.input) if meta.get("data_streams") else []
    sub_codecs = [_subtitle_codec(s.get("codec") or "", out_ext) for s in subs]
    if args.preset != "gif" and not p.get("keyfill") and (subs or data):
        cmd += ["-map", "0:V:0"] + (["-map", "0:a:0"] if has_audio else [])

    if args.preset == "gif":
        chain = ",".join(([gif_label] if gif_label else []) + ["fps=12"] + vf)
        fc = f"[0:v]{chain},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
        cmd += ["-filter_complex", fc, "-loop", "0", output]
        run(cmd)
        info(f"wrote {output}")
        non_av = _non_av_report(subs, [], data, ["subtitle", "data"], output, "gif")
        if non_av["dropped"]:
            notes.append(f"a GIF holds no subtitle or data stream: the source's {len(non_av['dropped'])} were not written")
        emit(output, non_av_streams=non_av, dropped_non_av_streams=bool(non_av["dropped"]), **({"notes": notes} if notes else {}))
        return 0

    if p.get("keyfill"):
        return _key_fill(args, p, meta, output, cmd, vf, has_audio, source_alpha, notes, subs, data)
    if p.get("alpha") and args.alpha_mode == "premultiplied":
        vf.append("premultiply=inplace=1")
    if vf:
        cmd += ["-vf", ",".join(vf)]
    video = list(p["video"])
    if p.get("codec"):
        # encoder_args() is the one place that turns a codec name into encoder options: it keeps
        # the source's HDR tags for hevc and refuses (kind: missing_tool) when no AV1 encoder is
        # built, which is exactly what these two presets promise.
        video = encoder_args(p["codec"], args.crf if args.crf is not None else (20 if p["codec"] == "hevc" else 32),
                             "veryfast" if STATE.fast else "medium", meta)
        # encoder_args() already applied --fast (its own preset scale per encoder: SVT-AV1 counts
        # 1..12, not x264's names) and appends +faststart, which this tool adds again for mp4
        as_built = list(video)
        while "-movflags" in video:
            i = video.index("-movflags")
            del video[i:i + 2]
        restate_last_swap(as_built, video)
    if args.crf is not None and "-crf" in video:
        video[video.index("-crf") + 1] = str(args.crf)
    if STATE.fast and "-preset" in video and not p.get("codec"):
        video[video.index("-preset") + 1] = "veryfast"
    # a fixed preset's line is tagged BT.709 (prores and dnxhr, editing masters, keep the source's tags)
    tag_bt709 = not p.get("intermediate") and not p.get("codec")
    if p.get("alpha") and STATE.hw and video and video[video.index("-c:v") + 1] == "prores_ks":
        # VideoToolbox's ProRes line is 422 HQ: under --hw a 4444 alpha master would come out
        # opaque, so these presets stay on prores_ks and say so
        note(f"--hw: --preset {args.preset} stays on prores_ks: VideoToolbox's ProRes encoder writes 422 HQ, "
             "without the alpha this preset keeps")
    elif not p.get("codec") and video:
        # --hw (never $FFMPEG_SKILL_HW here) puts a fixed preset on VideoToolbox: the same codec,
        # its CRF mapped to -q:v, the preset's frame rate kept; tags come with the VT line itself.
        # A build without libx264/libx265 has no other encoder, so it goes there without --hw too
        # (hw_preset_video returns the line untouched in every other case)
        video = hw_preset_video(video, meta, bt709=tag_bt709)
    if args.max_mb is not None:
        video = size_video_args(args, video, p, meta, has_audio)
    cmd += video
    if args.preset != "copy":
        # a stream copy can't be frame-rate-conformed or retagged without decoding it — that would
        # no longer be a copy, and would silently mislabel colour the agent never actually looked at
        if "-r" not in video:
            cmd += cfr_args(meta)
        if tag_bt709 and not video[video.index("-c:v") + 1].endswith("_videotoolbox"):
            cmd += bt709_tag_args(video[video.index("-c:v") + 1])
        if not p.get("intermediate"):
            # every line but an editing master's (prores, dnxhr) says BT.709 (the fixed presets' tags above, an
            # SDR hevc/av1 line's own): a BT.601 source's pixels are converted to match, in front
            # of the -vf above (run() folds the two); an untagged, BT.709 or HDR source adds nothing
            cmd += bt709_matrix_args(meta)
    if out_ext == "mp4":
        cmd += ["-movflags", "+faststart"]
    if args.repair:
        cmd += ["-avoid_negative_ts", "make_zero"]
    cmd += (p["audio"] if has_audio else ["-an"])
    trimmed = None
    if p["max"] and not args.allow_long and (meta.get("duration") or 0) > p["max"]:
        # the preset's promise (the platform's maximum), but the caller loses the tail: say how much
        # in the document (`trimmed`, `notes`), not only on stderr. -t is an output option, so a
        # kept subtitle track is cut at the same point (a cue after it is not written)
        trimmed = {"from": round(float(meta["duration"]), 3), "to": round(float(p["max"]), 3)}
        note(f"trimmed from {trimmed['from']:.3f}s to the {args.preset} maximum of {p['max']:.0f}s "
             "(use --allow-long to keep full length)")
        cmd += ["-t", f"{p['max']:.3f}"]
    damage_before = media_damage(args.input) if args.repair and not STATE.dry_run else None
    with tempfile.TemporaryDirectory(prefix="ffskill_2pass_") as passdir:
        if args.max_mb is not None:
            # pass 1 only writes x264's statistics; pass 2 encodes against them
            log = os.path.join(passdir, "x264")
            run(cmd + ["-pass", "1", "-passlogfile", log, "-an", "-sn", "-dn", "-f", "null", "-"])
            cmd += ["-pass", "2", "-passlogfile", log]
        dropped = _run_keeping_non_av(cmd, output, sub_codecs, len(data)) if (subs or data) else []
        if not (subs or data):
            run(cmd + [output])
    if not STATE.dry_run:
        # the export is on disk: a stop in the reads and the --normalize pass that follow keeps it,
        # and says so (#415)
        mark_delivered(output)
    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['codec']})")
    extra: Dict[str, object] = {"trimmed": trimmed} if trimmed else {}
    encoder = video[video.index("-c:v") + 1] if "-c:v" in video else None
    if p.get("expect") and not STATE.dry_run and encoder == p["video"][p["video"].index("-c:v") + 1]:
        # an editing master is asked for by codec, profile and pixel format: read all three back
        # (a VideoToolbox prores line under --hw writes its own pixel format, so it is not compared)
        measured = {k: v.get(k) for k in p["expect"]}
        extra.setdefault("verification", []).append(
            {"step": "codec", "property": "codec_profile_pix_fmt", "ok": measured == p["expect"],
             "expected": dict(p["expect"]), "measured": measured, "provenance": "specification"})
    if p.get("alpha"):
        extra["alpha_mode"] = args.alpha_mode or "straight"
        if not STATE.dry_run:
            # the alpha survived when every written frame's alpha matches the source frame's (an
            # encoder, decoder or muxer that drops it reads fully opaque); premultiplying changes
            # colour, not alpha
            written_alpha = alpha_stats(output, v.get("codec"))
            cmp = _alpha_compare(written_alpha, source_alpha)
            extra.setdefault("verification", []).append(
                {"step": "alpha", "property": "alpha_mean", "ok": cmp["ok"], "comparison": cmp,
                 "expected": None if source_alpha is None else round(source_alpha["mean"], 2),
                 "measured": None if written_alpha is None else round(written_alpha["mean"], 2), "tolerance": ALPHA_TOLERANCE,
                 "frames": {"expected": _rounded(source_alpha), "measured": _rounded(written_alpha)},
                 "provenance": "input_premeasurement"})
    platform = PLATFORM_OF.get(args.preset)
    if platform and has_audio and not STATE.dry_run:
        # Every eval run that exported for a platform then had to come back with loudness.py: the
        # preset scales and tags but does not touch levels, and only check.py said so. Measure the
        # written file here so the result names the gap and the caller plans one pass, not two.
        spec = PLATFORMS[platform]
        m = measure_loudness(output)
        if not m:
            _loudness_unmeasured(extra, notes, platform, spec)
        if m:
            ok = abs(m["lufs"] - spec["lufs"]) <= spec["lufs_tol"] and m["tp"] <= spec["tp"] + TP_TOLERANCE_DB
            extra["loudness"] = {"lufs": m["lufs"], "tp": m["tp"], "target_lufs": spec["lufs"], "target_tp": spec["tp"], "ok": ok}
            extra["verification"] = [_loudness_step(ok, platform, spec, m)]
            if not math.isfinite(m["lufs"]):
                # a silent output measures -inf LUFS: no gain reaches the target, so recommending
                # (or running, under --normalize) loudness.py only returns "nothing to normalise"
                extra["loudness"]["silent"] = True
                notes.append(f"output audio is silent (integrated loudness -inf, {platform} expects {spec['lufs']:g} LUFS); "
                             "check the source's audio or give the export a real track (audio.py --replace)")
                warn(notes[-1], "output_audio_silent", platform=platform)
            elif not ok and args.normalize:
                # Eval 7: every platform job ran export -> loudness.py -> export again (two video
                # encodes). The levels pass only re-encodes audio, so do it here on the written
                # file and the caller gets one export that meets the spec.
                info(f"loudness {m['lufs']:.1f} LUFS / {m['tp']:+.1f} dBTP is outside {platform}'s spec; normalising to {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP")
                # a private name: <stem>_loudnorm.<ext> is loudness.py's own default output, so a
                # real file of that name next to the export was overwritten and renamed away (review 7)
                tmp = str(Path(output).with_name(f".{Path(output).stem}.normalize-{os.getpid()}{Path(output).suffix}"))
                proc = run_tool([str(HERE / "loudness.py"), output, "-I", f"{spec['lufs']:g}", "--tp", f"{spec['tp']:g}", "-o", tmp, "--json"] + child_args())
                try:
                    child = json.loads(proc.stdout)
                except ValueError:
                    child = {}
                STATE.commands.extend(child.get("commands") or [])  # the encode that changed the audio belongs in this run's log
                if proc.returncode != 0 or child.get("status") != "completed":
                    err = child.get("error") or {}
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    # the child's "nothing was written" is about its own temp file; this run's export is
                    # on disk, and the child's exit code (124 timeout, 130/143 interrupted) is the
                    # run's, as render.py and waveform.py pass a stage's on (#415)
                    why = (err.get("message") or proc.stderr.strip()[-300:]).replace("; nothing was written", "")
                    die(f"--normalize: loudness.py failed: {why} ({kept_clause()})",
                        code=child_exit_code(child, proc.returncode) if proc.returncode else 1,
                        kind=err.get("kind") or "ffmpeg", output=output, hint=err.get("hint"))
                os.replace(tmp, output)
                m = measure_loudness(output)
                if not m:
                    # the file changed: the measurement before --normalize no longer describes it
                    _loudness_unmeasured(extra, notes, platform, spec, normalized=True)
                    ok = True  # nothing more to say about a level that was not measured
                else:
                    ok = abs(m["lufs"] - spec["lufs"]) <= spec["lufs_tol"] and m["tp"] <= spec["tp"] + TP_TOLERANCE_DB
                    extra["loudness"] = {"lufs": m["lufs"], "tp": m["tp"], "target_lufs": spec["lufs"], "target_tp": spec["tp"], "ok": ok, "normalized": True}
                    extra["verification"] = [_loudness_step(ok, platform, spec, m)]
                if not ok:
                    notes.append(f"loudness is still {m['lufs']:.1f} LUFS / {m['tp']:+.1f} dBTP after loudness.py (target {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP): {child.get('result', {}).get('note') or 'the encoder overshoots the ceiling'}")
                    warn(notes[-1], "loudness_outside_spec", platform=platform, lufs=m["lufs"], tp=m["tp"], normalized=True)
            elif not ok:
                notes.append(f"loudness {m['lufs']:.1f} LUFS / {m['tp']:+.1f} dBTP is outside {platform}'s {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP; "
                             f"run loudness.py -I {spec['lufs']:g} --tp {spec['tp']:g} on this file, or export with --normalize")
                warn(notes[-1], "loudness_outside_spec", platform=platform, lufs=m["lufs"], tp=m["tp"], normalized=False)
    elif platform and not has_audio and not STATE.dry_run:
        record_skip(f"no loudness check against {platform}'s spec: the source has no audio, so the export has none",
                    "loudness_no_audio", platform=platform)
    elif platform and has_audio and args.normalize:
        spec = PLATFORMS[platform]
        notes.append(f"[dry-run] --normalize: loudness.py -I {spec['lufs']:g} --tp {spec['tp']:g} would run on the written file if it misses {platform}'s spec")
    if p["max"] and not args.allow_long and not STATE.dry_run:
        # the preset's length promise, measured the way check.py measures it (the container's
        # duration, no tolerance): before 2.20 nothing re-read the length, and a --normalize pass
        # that left the sound 0.1 s long shipped a 90.10 s Reels file as verified
        written = probe(output, role="output").get("duration")
        if written is not None:
            step = {"step": "duration", "property": "duration", "ok": written <= p["max"],
                    "expected": {"max": p["max"]}, "measured": round(written, 3),
                    "delta": round(written - p["max"], 3), "tolerance": 0.0, "provenance": "specification"}
        else:
            # the preset promised a length; one that could not be read is not one that held
            step = {"step": "duration", "property": "duration", "ok": False, "expected": {"max": p["max"]},
                    "reason": "not_measured: the written file reports no duration"}
        extra.setdefault("verification", []).append(step)
    if damage_before is not None:
        after = media_damage(output)
        extra["repair"] = {"before": damage_before, "after": after}
        # judged on timestamp warnings, the part a remux rewrites: decode errors are counted in log
        # lines, and the same damaged frame logs a different number of them demuxed from another
        # container, so their before/after is reported, not compared
        stamps = after["timestamp_warnings"]
        extra.setdefault("verification", []).append(
            {"step": "repair", "property": "timestamp_warnings", "ok": stamps <= damage_before["timestamp_warnings"],
             "expected": {"max": damage_before["timestamp_warnings"]}, "measured": stamps,
             "provenance": "input_premeasurement"})
        if after["decode_errors"]:
            notes.append(f"--repair: {after['decode_errors']} decode error(s) remain: a remux drops corrupt packets and "
                         "rewrites timestamps but cannot rebuild a damaged frame; a re-encoding preset decodes past them")
            warn(notes[-1], "repair_incomplete", **after)
    if args.max_mb is not None and not STATE.dry_run:
        limit = int(args.max_mb * MIB)
        size = os.path.getsize(output)
        extra.setdefault("verification", []).append(
            {"step": "file_size", "property": "size_bytes", "ok": size <= limit, "expected": {"max": limit},
             "measured": size, "delta": size - limit, "tolerance": 0, "provenance": "user_specified"})
        if size > limit:
            notes.append(f"--max-mb {args.max_mb:g}: the file is {size / MIB:.2f} MiB, over the limit; the encoder overshot "
                         f"its target bitrate on this content: export again with a lower --max-mb")
            warn(notes[-1], "size_over_limit", size=size, limit=limit)
    # read back after --normalize, which rewrote the file
    non_av = _non_av_report(subs, sub_codecs, data, dropped, output, "write_failed")
    if non_av["dropped"]:
        notes.append(f"{len(non_av['dropped'])} subtitle/data stream(s) of the source are not in {os.path.basename(output)} "
                     f"({', '.join(sorted({d['type'] + ': ' + d['reason'] for d in non_av['dropped']}))}); non_av_streams lists them")
    extra["non_av_streams"] = non_av
    extra["dropped_non_av_streams"] = bool(non_av["dropped"])
    if notes:
        extra["notes"] = notes
    # the delivery keeps the source's picture and, except as a GIF, its sound
    extra["expect_streams"] = {"video": int(bool(meta.get("video"))), "audio": int(bool(has_audio and args.preset != "gif"))}
    extra["stream_reference"] = [meta]
    if trimmed:  # only the kept 0..max of the source can have handed its gap to the output
        extra["stream_windows"] = [(0.0, float(p["max"]))]
    emit(output, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
