#!/usr/bin/env python3
"""Pre-delivery compliance check: does this file meet the platform's spec?

Checks duration, frame size / aspect, fps, codec, pixel format, colour tags,
file size, integrated loudness and true peak against the chosen platform
and prints a PASS/WARN/FAIL table. Exit code 1 when anything FAILs.

Platforms: youtube, shorts, reels, tiktok, x, linkedin, broadcast (EBU R128), podcast, custom

Examples:
  python3 check.py final.mp4 --platform youtube
  python3 check.py reel.mp4 --platform reels --json
  python3 check.py spot.mov --platform broadcast
  python3 check.py clip.mp4 --platform custom --max-duration 30 --aspect 1:1 --lufs -16
"""
import argparse
import json
import re
import sys
from fractions import Fraction
from typing import Any, Dict, List

from _common import add_common, apply_common, die, emit, info, probe, require_tool, run

SPECS: Dict[str, Dict[str, Any]] = {
    "youtube":   {"max_duration": 12 * 3600, "aspects": ["16:9", "9:16", "1:1", "4:3"], "min_height": 720, "fps_max": 60, "codecs": ["h264", "hevc", "prores", "av1", "vp9"], "max_bytes": 256 * 1024 ** 3, "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
    "shorts":    {"max_duration": 180, "aspects": ["9:16", "1:1"], "min_height": 1080, "fps_max": 60, "codecs": ["h264", "hevc"], "max_bytes": 256 * 1024 ** 3, "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
    "reels":     {"max_duration": 90, "aspects": ["9:16", "4:5", "1:1"], "min_height": 1080, "fps_max": 60, "codecs": ["h264", "hevc"], "max_bytes": 4 * 1024 ** 3, "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": True},
    "tiktok":    {"max_duration": 600, "aspects": ["9:16", "1:1"], "min_height": 1080, "fps_max": 60, "codecs": ["h264", "hevc"], "max_bytes": 4 * 1024 ** 3, "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": True},
    "x":         {"max_duration": 140, "aspects": ["16:9", "1:1", "9:16"], "min_height": 720, "fps_max": 60, "codecs": ["h264"], "max_bytes": 512 * 1024 ** 2, "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True},
    "linkedin":  {"max_duration": 600, "aspects": ["16:9", "1:1", "9:16", "4:5"], "min_height": 720, "fps_max": 60, "codecs": ["h264"], "max_bytes": 5 * 1024 ** 3, "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True},
    "broadcast": {"max_duration": None, "aspects": ["16:9"], "min_height": 1080, "fps_max": 60, "codecs": ["prores", "dnxhd", "h264", "hevc", "mpeg2video"], "max_bytes": None, "lufs": -23, "lufs_tol": 1.0, "tp": -1.0, "sdr_only": False},
    "podcast":   {"max_duration": None, "aspects": None, "min_height": 0, "fps_max": None, "codecs": None, "max_bytes": None, "lufs": -16, "lufs_tol": 1.0, "tp": -1.0, "sdr_only": False},
    "custom":    {"max_duration": None, "aspects": None, "min_height": 0, "fps_max": None, "codecs": None, "max_bytes": None, "lufs": None, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
}


def measure_loudness(path: str) -> Dict[str, float]:
    ffmpeg = require_tool("ffmpeg")
    proc = run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"], quiet=True, check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        return {}
    d = json.loads(m.group(0))
    try:
        return {"lufs": float(d["input_i"]), "tp": float(d["input_tp"]), "lra": float(d["input_lra"])}
    except (KeyError, ValueError):
        return {}


def aspect_name(w: int, h: int) -> str:
    f = Fraction(w, h)
    for name, target in (("16:9", Fraction(16, 9)), ("9:16", Fraction(9, 16)), ("1:1", Fraction(1)), ("4:5", Fraction(4, 5)), ("4:3", Fraction(4, 3)), ("21:9", Fraction(21, 9))):
        if abs(float(f) - float(target)) < 0.02:
            return name
    return f"{f.numerator}:{f.denominator}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--platform", choices=sorted(SPECS), default="youtube")
    ap.add_argument("--max-duration", type=float, help="override max duration in seconds")
    ap.add_argument("--aspect", help="override allowed aspect (e.g. 9:16 or 16:9,1:1)")
    ap.add_argument("--lufs", type=float, help="override loudness target")
    ap.add_argument("--tp", type=float, help="override true-peak ceiling")
    ap.add_argument("--max-mb", type=float, help="override max file size in MB")
    ap.add_argument("--no-loudness", action="store_true", help="skip the loudness measurement (faster)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    spec = dict(SPECS[args.platform])
    if args.max_duration is not None:
        spec["max_duration"] = args.max_duration
    if args.aspect:
        spec["aspects"] = [a.strip() for a in args.aspect.split(",")]
    if args.lufs is not None:
        spec["lufs"] = args.lufs
    if args.tp is not None:
        spec["tp"] = args.tp
    if args.max_mb is not None:
        spec["max_bytes"] = int(args.max_mb * 1024 * 1024)

    meta = probe(args.input)
    v, a = meta.get("video") or {}, meta.get("audio") or {}
    rows: List[Dict[str, Any]] = []

    JUDGEMENT = {"duration", "aspect", "loudness", "fps", "resolution"}

    def row(name: str, status: str, value: Any, expect: Any, fix: str = "") -> None:
        # "format" rows are safe to fix mechanically; "judgement" rows change the content
        # (what is cut, what is cropped, how loud ambience gets) and need a decision
        rows.append({"check": name, "status": status, "value": value, "expected": expect, "fix": fix,
                     "kind": "judgement" if name in JUDGEMENT else "format"})

    dur = meta.get("duration") or 0.0
    if spec["max_duration"]:
        row("duration", "PASS" if dur <= spec["max_duration"] else "FAIL", f"{dur:.2f}s", f"<= {spec['max_duration']:g}s", "decide with the user: cut.py keeps quality but drops content; fit.py --duration speeds up (audio pitch-preserved, motion faster)")
    else:
        row("duration", "PASS", f"{dur:.2f}s", "any")

    if v:
        w, h = v["width"], v["height"]
        if v.get("rotation") in (90, -90, 270, -270):
            w, h = h, w
        asp = aspect_name(w, h)
        if spec["aspects"]:
            row("aspect", "PASS" if asp in spec["aspects"] else "FAIL", asp, "/".join(spec["aspects"]), f"fit.py --aspect {spec['aspects'][0]} --fit pad (keeps everything, adds bars) or crop (fills the frame, loses the edges: check the subject with look.py)")
        else:
            row("aspect", "PASS", asp, "any")
        short = min(w, h)
        if spec["min_height"]:
            row("resolution", "PASS" if short >= spec["min_height"] else "WARN", f"{w}x{h}", f"short side >= {spec['min_height']}", "upscaling will not add detail; re-export from the master")
        fps = v.get("fps") or 0
        if spec["fps_max"]:
            row("fps", "PASS" if fps <= spec["fps_max"] + 0.01 else "FAIL", f"{fps:g}", f"<= {spec['fps_max']}", "fit.py --fps 30 (drops half the frames of 60 fps motion; fine for talking heads, visible on sports/gaming)")
        row("vfr", "PASS" if not v.get("variable_frame_rate_suspected") else "WARN", "variable" if v.get("variable_frame_rate_suspected") else "constant", "constant", "fit.py --fps N (any re-encode conforms it)")
        if spec["codecs"]:
            row("video codec", "PASS" if v.get("codec") in spec["codecs"] else "FAIL", v.get("codec"), "/".join(spec["codecs"]), "export.py --preset " + args.platform.replace("shorts", "reels").replace("tiktok", "reels").replace("linkedin", "youtube"))
        pf = v.get("pix_fmt") or ""
        if args.platform in ("reels", "tiktok", "x", "linkedin"):
            row("pixel format", "PASS" if pf == "yuv420p" else "FAIL", pf, "yuv420p (8-bit 4:2:0)", "export.py preset re-encodes to yuv420p")
        if spec["sdr_only"] and v.get("hdr"):
            row("colour", "FAIL", v.get("hdr_format"), "SDR BT.709", "color.py --to-sdr")
        else:
            tags = (v.get("color_primaries"), v.get("color_transfer"))
            untagged = not tags[0] and not tags[1]
            if v.get("hdr") or tags == ("bt709", "bt709") or args.platform in ("podcast", "custom"):
                row("colour", "PASS", f"{tags[0]}/{tags[1]}" + (f" ({v.get('hdr_format')})" if v.get("hdr") else ""), "bt709/bt709 tagged (or HDR)")
            elif untagged and (v.get("bit_depth") or 8) == 8:
                # untagged 8-bit video is treated as BT.709 by every player and platform; nothing to fix
                row("colour", "PASS", "untagged (players assume bt709)", "bt709/bt709 tagged (or HDR)")
            else:
                row("colour", "WARN", f"{tags[0]}/{tags[1]}", "bt709/bt709 tagged (or HDR)", "color.py --retag bt709 when the picture really is 709; color.py --to-sdr when it is HDR")
    elif args.platform not in ("podcast", "custom"):
        row("video", "FAIL", "none", "video stream", "")

    size = meta.get("size_bytes") or 0
    if spec["max_bytes"]:
        row("file size", "PASS" if size <= spec["max_bytes"] else "FAIL", f"{size / 1024 / 1024:.1f} MB", f"<= {spec['max_bytes'] / 1024 / 1024:.0f} MB", "export.py --crf 24 or lower resolution")

    if a:
        row("audio", "PASS", f"{a.get('codec')} {a.get('channels')}ch {a.get('sample_rate')}Hz", "present")
        if a.get("sample_rate") and a["sample_rate"] not in (44100, 48000):
            row("sample rate", "WARN", a["sample_rate"], "44100 or 48000", "loudness.py --sample-rate 48000")
        if not args.no_loudness and spec["lufs"] is not None:
            lm = measure_loudness(args.input)
            if lm:
                diff = abs(lm["lufs"] - spec["lufs"])
                row("loudness", "PASS" if diff <= spec["lufs_tol"] else "FAIL", f"{lm['lufs']:.1f} LUFS", f"{spec['lufs']:g} ± {spec['lufs_tol']:g} LUFS", f"loudness.py -I {spec['lufs']:g} for speech or music; leave ambience/near-silence (<= -40 LUFS) alone and say so")
                row("true peak", "PASS" if lm["tp"] <= spec["tp"] + 0.05 else "FAIL", f"{lm['tp']:.1f} dBTP", f"<= {spec['tp']:g} dBTP", f"loudness.py --tp {spec['tp']:g}")
    elif args.platform in ("podcast",):
        row("audio", "FAIL", "none", "audio stream", "audio.py --replace")
    else:
        row("audio", "WARN", "none", "audio stream", "audio.py --replace (silent uploads are often rejected)")

    failed = [r for r in rows if r["status"] == "FAIL"]
    warned = [r for r in rows if r["status"] == "WARN"]
    if not args.json:
        width = max(len(r["check"]) for r in rows)
        print(f"{args.input} — {args.platform}")
        for r in rows:
            line = f"  {r['status']:4s} {r['check']:{width}s}  {r['value']}  (expected {r['expected']})"
            if r["status"] != "PASS" and r["kind"] == "judgement":
                line += "  [judgement]"
            if r["status"] != "PASS" and r["fix"]:
                line += f"  -> {r['fix']}"
            print(line)
        print(f"  {len(rows)} checks, {len(failed)} failed, {len(warned)} warnings")
    emit(None, platform=args.platform, checks=rows, failed=len(failed), warnings=len(warned), ok=not failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
