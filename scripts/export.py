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
  h265      HEVC CRF 24 (libx265) with hvc1 tag for Apple compatibility
  gif       480px wide palette-optimised GIF at 12 fps (short previews)
  copy      stream copy, no re-encode: same codecs, container and colour
            tags as the source (a delivery target with nothing to change)

Examples:
  python3 export.py final.mp4 --preset youtube
  python3 export.py final.mp4 --preset reels --fit crop
  python3 export.py final.mp4 --preset reels --normalize   # meet the platform's loudness in the same call
  python3 export.py final.mp4 --preset prores -o master.mov
  python3 export.py final.mp4 --preset copy -o delivered.mp4
  python3 export.py --list
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

from _common import STATE, add_common, apply_common, bt709_tag_args, child_args, emit, cfr_args, default_output, die, encoder_args, ffmpeg_base, info, probe, run, run_tool, validate_color, pad_filters, add_pad_fill_args, fmt_secs
from check import SPECS as PLATFORMS, measure_loudness
from _platforms import ALIASES as _ALIASES, PLATFORMS as PLATFORM_TABLE, resolve as resolve_platform
# Frame and duration limit come from the one platform table (scripts/_platforms.py) rather than
# from a literal restated here: before 1.14 they were typed twice and the facebook preset had
# already drifted (no duration cap against the table's 14400 s).
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
    "prores": {"w": None, "h": None, "ext": "mov", "video": ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"], "audio": ["-c:a", "pcm_s16le"], "max": None, "desc": "ProRes 422 HQ master, PCM audio, source resolution"},
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
    ap.add_argument("--normalize", action="store_true", help="youtube/youtube4k/reels/x: when the written file misses the platform's loudness spec, run loudness.py on it (audio re-encoded, video copied) so one export delivers")
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
    if meta["video"].get("bt2020_or_hdr") and args.preset not in ("prores", "copy", "youtube-hdr"):
        notes.append("source is HDR (%s). This preset outputs SDR BT.709 tags without tone mapping; run color.py --to-sdr first for correct colours." % meta["video"].get("hdr_format"))
        info("warning: " + notes[-1])
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, args.preset, p["ext"])
    out_ext = Path(output).suffix.lstrip(".").lower()

    vf: List[str] = []
    if p["w"] and not args.no_scale:
        if p["h"]:
            if args.fit == "crop":
                vf += [f"scale={p['w']}:{p['h']}:force_original_aspect_ratio=increase", f"crop={p['w']}:{p['h']}"]
            else:
                vf.append(pad_filters(p["w"], p["h"], args.pad_fill, args.pad_color, args.pad_blur))
            vf.append("setsar=1")
        else:
            vf.append(f"scale={p['w']}:-2")
    cmd = ffmpeg_base() + ["-i", args.input]

    if args.preset == "gif":
        chain = ",".join(["fps=12"] + vf) if vf else "fps=12"
        fc = f"[0:v]{chain},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
        cmd += ["-filter_complex", fc, "-loop", "0", output]
        run(cmd)
        info(f"wrote {output}")
        emit(output, **({"notes": notes} if notes else {}))
        return 0

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
        while "-movflags" in video:
            i = video.index("-movflags")
            del video[i:i + 2]
    if args.crf is not None and "-crf" in video:
        video[video.index("-crf") + 1] = str(args.crf)
    if STATE.fast and "-preset" in video and not p.get("codec"):
        video[video.index("-preset") + 1] = "veryfast"
    cmd += video
    if args.preset != "copy":
        # a stream copy can't be frame-rate-conformed or retagged without decoding it — that would
        # no longer be a copy, and would silently mislabel colour the agent never actually looked at
        if "-r" not in video:
            cmd += cfr_args(meta)
        if args.preset not in ("prores",) and not p.get("codec"):
            cmd += bt709_tag_args(video[video.index("-c:v") + 1])
    if out_ext == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += (p["audio"] if has_audio else ["-an"])
    if p["max"] and not args.allow_long and (meta.get("duration") or 0) > p["max"]:
        info(f"trimming to the platform maximum of {p['max']:.0f}s (use --allow-long to keep full length)")
        cmd += ["-t", f"{p['max']:.3f}"]
    cmd.append(output)
    run(cmd)
    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {v['codec']})")
    extra: Dict[str, object] = {}
    platform = PLATFORM_OF.get(args.preset)
    if platform and has_audio and not STATE.dry_run:
        # Every eval run that exported for a platform then had to come back with loudness.py: the
        # preset scales and tags but does not touch levels, and only check.py said so. Measure the
        # written file here so the result names the gap and the caller plans one pass, not two.
        spec = PLATFORMS[platform]
        m = measure_loudness(output)
        if m:
            ok = abs(m["lufs"] - spec["lufs"]) <= spec["lufs_tol"] and m["tp"] <= spec["tp"]
            extra["loudness"] = {"lufs": m["lufs"], "tp": m["tp"], "target_lufs": spec["lufs"], "target_tp": spec["tp"], "ok": ok}
            extra["verification"] = [{"step": "loudness", "ok": ok, "platform": platform}]
            if not ok and args.normalize:
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
                    die(f"--normalize: loudness.py failed: {err.get('message') or proc.stderr.strip()[-300:]}",
                        kind=err.get("kind") or "ffmpeg", output=output, hint=err.get("hint"))
                os.replace(tmp, output)
                m = measure_loudness(output) or m
                ok = abs(m["lufs"] - spec["lufs"]) <= spec["lufs_tol"] and m["tp"] <= spec["tp"]
                extra["loudness"] = {"lufs": m["lufs"], "tp": m["tp"], "target_lufs": spec["lufs"], "target_tp": spec["tp"], "ok": ok, "normalized": True}
                extra["verification"] = [{"step": "loudness", "ok": ok, "platform": platform}]
                if not ok:
                    notes.append(f"loudness is still {m['lufs']:.1f} LUFS / {m['tp']:+.1f} dBTP after loudness.py (target {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP): {child.get('result', {}).get('note') or 'the encoder overshoots the ceiling'}")
                    info("warning: " + notes[-1])
            elif not ok:
                notes.append(f"loudness {m['lufs']:.1f} LUFS / {m['tp']:+.1f} dBTP is outside {platform}'s {spec['lufs']:g} LUFS / {spec['tp']:g} dBTP; "
                             f"run loudness.py -I {spec['lufs']:g} --tp {spec['tp']:g} on this file, or export with --normalize")
                info("warning: " + notes[-1])
    elif platform and has_audio and args.normalize:
        spec = PLATFORMS[platform]
        notes.append(f"[dry-run] --normalize: loudness.py -I {spec['lufs']:g} --tp {spec['tp']:g} would run on the written file if it misses {platform}'s spec")
    if notes:
        extra["notes"] = notes
    emit(output, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
