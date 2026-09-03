#!/usr/bin/env python3
"""Export with delivery presets. Scales/pads to the preset's frame (keeping
the source aspect inside it), constrains duration where the platform does,
sets BT.709 tags, and picks sensible codecs/bitrates.

Presets:
  youtube   1920x1080 H.264 CRF 18 high profile, AAC 192k, 48 kHz, faststart
  youtube4k 3840x2160 H.264 CRF 18, AAC 192k
  reels     1080x1920 9:16 H.264 CRF 20, AAC 128k, max 90 s (also Shorts/TikTok)
  x         1280x720 H.264 CRF 22, AAC 128k, max 140 s (Twitter/X)
  prores    ProRes 422 HQ .mov, PCM 16-bit audio (editing master)
  h265      HEVC CRF 24 (libx265) with hvc1 tag for Apple compatibility
  gif       480px wide palette-optimised GIF at 12 fps (short previews)

Examples:
  python3 export.py final.mp4 --preset youtube
  python3 export.py final.mp4 --preset reels --fit crop
  python3 export.py final.mp4 --preset prores -o master.mov
  python3 export.py --list
"""
import argparse
import sys
from typing import Dict, List

from _common import STATE, add_common, apply_common, emit, cfr_args, default_output, die, ffmpeg_base, info, probe, run

PRESETS: Dict[str, Dict] = {
    "youtube": {"w": 1920, "h": 1080, "ext": "mp4", "video": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"], "audio": ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"], "max": None, "desc": "1080p H.264, AAC 192k"},
    "youtube4k": {"w": 3840, "h": 2160, "ext": "mp4", "video": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"], "audio": ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"], "max": None, "desc": "2160p H.264, AAC 192k"},
    "reels": {"w": 1080, "h": 1920, "ext": "mp4", "video": ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30"], "audio": ["-c:a", "aac", "-b:a", "128k", "-ar", "48000"], "max": 90.0, "desc": "9:16 1080x1920, 30fps, max 90s (Reels/Shorts/TikTok)"},
    "x": {"w": 1280, "h": 720, "ext": "mp4", "video": ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30"], "audio": ["-c:a", "aac", "-b:a", "128k", "-ar", "44100"], "max": 140.0, "desc": "720p H.264, max 140s (Twitter/X)"},
    "prores": {"w": None, "h": None, "ext": "mov", "video": ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"], "audio": ["-c:a", "pcm_s16le"], "max": None, "desc": "ProRes 422 HQ master, PCM audio, source resolution"},
    "h265": {"w": None, "h": None, "ext": "mp4", "video": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"], "audio": ["-c:a", "aac", "-b:a", "160k"], "max": None, "desc": "HEVC CRF 24, hvc1 tag, source resolution"},
    "gif": {"w": 480, "h": None, "ext": "gif", "video": [], "audio": [], "max": None, "desc": "480px palette GIF, 12fps"},
}

BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output", help="output file (default: <name>_<preset>.<ext>)")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="delivery preset")
    ap.add_argument("--fit", choices=["pad", "crop"], default="pad", help="how to reach the preset frame when aspect differs (default pad)")
    ap.add_argument("--pad-color", default="black")
    ap.add_argument("--no-scale", action="store_true", help="keep source resolution even for platform presets")
    ap.add_argument("--allow-long", action="store_true", help="do not trim to the platform's max duration")
    ap.add_argument("--crf", type=int, help="override CRF")
    ap.add_argument("--list", action="store_true", help="list presets and exit")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.list:
        for name, p in PRESETS.items():
            print(f"{name:10s} {p['desc']}")
        return 0
    if not args.input or not args.preset:
        die("input and --preset are required (or use --list)")

    p = PRESETS[args.preset]
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    if meta["video"].get("hdr") and args.preset != "prores":
        info("warning: source is HDR (%s). This preset outputs SDR BT.709 tags without tone mapping; run color.py --to-sdr first for correct colours." % meta["video"].get("hdr_format"))
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, args.preset, p["ext"])

    vf: List[str] = []
    if p["w"] and not args.no_scale:
        if p["h"]:
            if args.fit == "crop":
                vf += [f"scale={p['w']}:{p['h']}:force_original_aspect_ratio=increase", f"crop={p['w']}:{p['h']}"]
            else:
                vf += [f"scale={p['w']}:{p['h']}:force_original_aspect_ratio=decrease", f"pad={p['w']}:{p['h']}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}"]
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
        emit(output)
        return 0

    if vf:
        cmd += ["-vf", ",".join(vf)]
    video = list(p["video"])
    if args.crf is not None and "-crf" in video:
        video[video.index("-crf") + 1] = str(args.crf)
    if STATE["fast"] and "-preset" in video:
        video[video.index("-preset") + 1] = "veryfast"
    cmd += video
    if "-r" not in video:
        cmd += cfr_args(meta)
    if args.preset not in ("prores",):
        cmd += BT709
    if p["ext"] == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += (p["audio"] if has_audio else ["-an"])
    if p["max"] and not args.allow_long and (meta.get("duration") or 0) > p["max"]:
        info(f"trimming to the platform maximum of {p['max']:.0f}s (use --allow-long to keep full length)")
        cmd += ["-t", f"{p['max']:.3f}"]
    cmd.append(output)
    run(cmd)
    result = probe(output)
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {v['codec']})")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
