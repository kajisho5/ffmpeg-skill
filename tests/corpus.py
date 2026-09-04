#!/usr/bin/env python3
"""Real-world corpus: download public sample videos from many devices/codecs
and run verify.py on them. Files are cached in tests/corpus/ (git-ignored).

Each entry records where it came from, why it is in the corpus, and what
probe.py is expected to say about it, so a regression is a diff, not a vibe.

Usage:
  python3 tests/corpus.py --list
  python3 tests/corpus.py --fetch                # download everything (size-capped)
  python3 tests/corpus.py --fetch --only gopro,android_screen
  python3 tests/corpus.py --verify               # verify.py on what is downloaded -> tests/corpus/report.md
  python3 tests/corpus.py --expect               # compare probe output with the expectations in the manifest
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "tests" / "corpus"
UA = {"User-Agent": "ffmpeg-skill-corpus/0.1 (+https://github.com/kajisho5/ffmpeg-skill)"}

MANIFEST = [
    {"id": "gopro_hero", "url": "https://archive.org/download/grizzly-bear-selfie/GX010743.MP4", "file": "gopro_GX010743.MP4",
     "source": "archive.org grizzly-bear-selfie (user upload)", "why": "GoPro HERO native file: GPMF metadata track, 4:2:0 HEVC/H.264, high bitrate, extra data streams", "max_mb": 260,
     "expect": {"video.codec": ["hevc", "h264"], "audio.channels": 2}},
    {"id": "dji_drone", "url": "https://archive.org/download/dji-0230/DJI_0038.MOV", "file": "dji_DJI_0038.MOV",
     "source": "archive.org dji-0230 (user upload)", "why": "DJI drone .MOV: 4K, D-Log/normal profile, possibly no audio", "max_mb": 200,
     "expect": {"video.codec": ["hevc", "h264"]}},
    {"id": "iphone_mov", "url": "https://archive.org/download/jupiter-canyon/IMG_3179.MOV", "file": "iphone_IMG_3179.MOV",
     "source": "archive.org jupiter-canyon (user upload)", "why": "iPhone .MOV from another device/generation than the local sample", "max_mb": 80,
     "expect": {"video.codec": ["hevc", "h264"]}},
    {"id": "android_screen", "url": "https://archive.org/download/screen-recording-20231223-021623/Screen_Recording_20231223_021623.mp4", "file": "android_screen_1.mp4",
     "source": "archive.org screen-recording-20231223-021623", "why": "Android screen recording: VFR, odd resolution, possibly mono/no audio", "max_mb": 20,
     "expect": {}},
    {"id": "android_screen2", "url": "https://archive.org/download/screen-recording-20260303-174357-2/Screen_Recording_20260303_174357(2).mp4", "file": "android_screen_2.mp4",
     "source": "archive.org screen-recording-20260303-174357-2", "why": "second Android screen recording", "max_mb": 20, "expect": {}},
    {"id": "hdr10_pattern", "url": "https://archive.org/download/mehanik-hdr10-test-patterns/02.%20White%20%26%20Color%20clipping/02.%20White%20240-1000nits-MaxCLL-1000-MDL-1000.mp4", "file": "hdr10_white_clipping.mp4",
     "source": "archive.org mehanik-hdr10-test-patterns", "why": "HDR10 (PQ, BT.2020) with MaxCLL/MDL metadata: tone-map and tag handling", "max_mb": 60,
     "expect": {"video.hdr": True, "video.color_transfer": "smpte2084"}},
    {"id": "iphone13_4k60", "url": "https://img.photographyblog.com/reviews/apple_iphone_13_pro/sample_images/4K60p.mov", "file": "iphone13pro_4K60p.mov",
     "source": "photographyblog.com iPhone 13 Pro review samples", "why": "iPhone 13 Pro 4K60 .mov (Dolby Vision HLG expected), large frame + high fps", "max_mb": 400,
     "expect": {"video.codec": "hevc", "video.hdr": True}},
    {"id": "blender_tos_720", "url": "https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov", "file": "tears_of_steel_720p.mov",
     "source": "Blender Foundation, Tears of Steel (CC-BY 3.0)", "why": "clean H.264 .mov with real dialogue, music and scene cuts for scenes/silence/loudness", "max_mb": 400,
     "expect": {"video.codec": "h264", "audio.channels": 2}},
    {"id": "vp9_hdr", "url": "https://storage.googleapis.com/media.webmproject.org/devsite/vp9/hdr-encoding/strobe_scientist.mkv", "file": "vp9_hdr_strobe_scientist.mkv",
     "source": "webmproject.org VP9 HDR encoding guide", "why": "VP9 10-bit HDR in Matroska: non-HEVC HDR path", "max_mb": 200,
     "expect": {"video.codec": "vp9", "video.hdr": True}},
    {"id": "rtings_24p", "url": "https://www.rtings.com/images/test-materials/2015/305_24p.mp4", "file": "rtings_305_24p.mp4",
     "source": "rtings.com test materials", "why": "24p judder test clip: fps handling", "max_mb": 100, "expect": {"video.fps": 24.0}},
]


def fetch(entry: dict, force: bool = False) -> Path:
    """Download with a size cap, resume (HTTP Range) and a final length check, so a dropped
    connection never leaves a truncated file that looks complete."""
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / entry["file"]
    cap = entry["max_mb"] * 1024 * 1024
    head = urllib.request.urlopen(urllib.request.Request(entry["url"], headers=UA, method="HEAD"), timeout=60)
    total = int(head.headers.get("Content-Length") or 0)
    if total and total > cap:
        raise RuntimeError(f"{entry['id']}: {total / 1e6:.0f} MB exceeds cap {entry['max_mb']} MB")
    if out.exists() and not force and (not total or out.stat().st_size == total):
        return out
    tmp = out.with_suffix(out.suffix + ".part")
    if force and tmp.exists():
        tmp.unlink()
    for attempt in range(5):
        have = tmp.stat().st_size if tmp.exists() else 0
        if total and have >= total:
            break
        headers = dict(UA)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(entry["url"], headers=headers), timeout=60) as resp:
                mode = "ab" if have and resp.status == 206 else "wb"
                if mode == "wb":
                    have = 0
                with open(tmp, mode) as fh:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
                        have += len(chunk)
                        if have > cap:
                            raise RuntimeError(f"{entry['id']}: exceeded cap while downloading")
        except (OSError, urllib.error.URLError) as exc:  # noqa: PERF203
            if attempt == 4:
                raise RuntimeError(f"{entry['id']}: download failed after retries: {exc}")
            continue
        if not total:
            break
    size = tmp.stat().st_size if tmp.exists() else 0
    if total and size != total:
        raise RuntimeError(f"{entry['id']}: got {size} of {total} bytes")
    tmp.rename(out)
    return out


def probe(path: Path) -> dict:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "probe.py"), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return json.loads(proc.stdout) if proc.returncode == 0 else {"error": proc.stderr.strip()[-200:]}


def dig(d: dict, dotted: str):
    cur = d
    for k in dotted.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="comma separated ids")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--expect", action="store_true")
    ap.add_argument("--quick", action="store_true", help="verify --quick")
    args = ap.parse_args()
    entries = [e for e in MANIFEST if not args.only or e["id"] in args.only.split(",")]
    if args.list or not (args.fetch or args.verify or args.expect):
        for e in entries:
            have = (DEST / e["file"]).exists()
            print(f"{'have' if have else '    '} {e['id']:16s} {e['why'][:70]}\n      {e['source']}")
        return 0
    rc = 0
    if args.fetch:
        for e in entries:
            try:
                p = fetch(e, args.force)
                print(f"ok   {e['id']:16s} {p.stat().st_size / 1e6:6.1f} MB  {p.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {e['id']:16s} {exc}")
                rc = 1
    if args.expect:
        for e in entries:
            p = DEST / e["file"]
            if not p.exists():
                continue
            m = probe(p)
            v = m.get("video") or {}
            a = m.get("audio") or {}
            line = f"{e['id']:16s} {v.get('codec')} {v.get('width')}x{v.get('height')} @{v.get('fps')} {v.get('pix_fmt')} {v.get('hdr_format') or 'SDR'}{' VFR?' if v.get('variable_frame_rate_suspected') else ''} rot={v.get('rotation')} | audio {a.get('codec')} {a.get('channels')}ch | {m.get('duration')}s"
            bad = []
            for key, want in e.get("expect", {}).items():
                got = dig(m, key)
                ok = got in want if isinstance(want, list) else (abs(got - want) < 0.05 if isinstance(want, float) and isinstance(got, (int, float)) else got == want)
                if not ok:
                    bad.append(f"{key}: expected {want}, got {got}")
            print(("ok   " if not bad else "DIFF ") + line + (("\n      " + "; ".join(bad)) if bad else ""))
            rc |= 1 if bad else 0
    if args.verify:
        files = [str(DEST / e["file"]) for e in entries if (DEST / e["file"]).exists()]
        if not files:
            print("nothing downloaded; run --fetch first")
            return 1
        cmd = [sys.executable, str(ROOT / "scripts" / "verify.py")] + files + ["--report", str(DEST / "report.md"), "--out", str(DEST / "out"), "--keep"]
        if args.quick:
            cmd.append("--quick")
        proc = subprocess.run(cmd)
        rc |= proc.returncode
        print(f"report: {DEST / 'report.md'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
