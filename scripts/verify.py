#!/usr/bin/env python3
"""Real-footage verification kit: run the whole toolchain against your own
files (phone HDR, GoPro, OBS screen captures, Log footage, Zoom recordings)
and get a pass/fail table. Synthetic test media never shows what a real
container does; this does.

Every file gets: probe, lossless cut, accurate cut, fit (9:16 pad), caption
burn, overlay text, loudness measurement, silence listing, export (x preset),
look (contact sheet), plus color --to-sdr when the file is HDR and
audio --downmix when it has more than 2 channels.

Examples:
  python3 verify.py ~/Footage/*.MOV ~/Footage/*.mp4
  python3 verify.py fixtures/ --quick --report verify.md
  python3 verify.py clip.mov --keep --out ./verify_out
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

from _common import add_common, apply_common, die, emit, info, probe

HERE = Path(__file__).resolve().parent
MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mxf", ".wav", ".m4a", ".mp3", ".flac", ".aac"}


def collect(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(x for x in pp.rglob("*") if x.suffix.lower() in MEDIA_EXT and x.is_file())
        elif pp.is_file():
            files.append(pp)
        else:
            die(f"not found: {p}")
    if not files:
        die("no media files found")
    return files


def step(name: str, argv: List[str], timeout: float) -> Dict:
    t0 = time.time()
    if argv[0] == "__check_hdr__":
        try:
            v = probe(argv[1]).get("video") or {}
            ok = bool(v.get("hdr")) and v.get("bit_depth", 8) >= 10
            err = "" if ok else f"re-encode lost HDR: {v.get('color_transfer')}/{v.get('pix_fmt')}"
        except SystemExit:
            ok, err = False, "output missing"
        return {"step": name, "ok": ok, "seconds": round(time.time() - t0, 1), "error": err}
    try:
        proc = subprocess.run([sys.executable, str(HERE / argv[0])] + argv[1:], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        ok = proc.returncode == 0
        err = "" if ok else (proc.stderr.strip().splitlines() or ["?"])[-1][:200]
    except subprocess.TimeoutExpired:
        ok, err = False, f"timeout after {timeout:.0f}s"
    return {"step": name, "ok": ok, "seconds": round(time.time() - t0, 1), "error": err}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="media files and/or folders")
    ap.add_argument("--out", help="directory for outputs (default: temp dir, deleted unless --keep)")
    ap.add_argument("--keep", action="store_true", help="keep the outputs")
    ap.add_argument("--quick", action="store_true", help="probe, copy cut, fit, caption, export only")
    ap.add_argument("--seconds", type=float, default=6.0, help="length of the test cut taken from each file (default 6)")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-step timeout in seconds")
    ap.add_argument("--report", help="write a Markdown report here")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    files = collect(args.paths)
    tmp = None
    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="ffskill_verify_")
        outdir = Path(tmp.name)

    results = []
    for f in files:
        info(f"=== {f}")
        entry: Dict = {"file": str(f), "steps": []}
        try:
            meta = probe(str(f))
        except SystemExit:
            entry["steps"].append({"step": "probe", "ok": False, "seconds": 0, "error": "ffprobe failed"})
            results.append(entry)
            continue
        entry["probe"] = {k: meta.get(k) for k in ("duration", "format")}
        entry["probe"]["video"] = {k: (meta.get("video") or {}).get(k) for k in ("codec", "width", "height", "fps", "pix_fmt", "hdr_format", "rotation", "variable_frame_rate_suspected")}
        entry["probe"]["audio"] = {k: (meta.get("audio") or {}).get(k) for k in ("codec", "channels", "sample_rate")}
        entry["steps"].append({"step": "probe", "ok": True, "seconds": 0, "error": ""})
        dur = meta.get("duration") or 0.0
        has_v, has_a = bool(meta.get("video")), bool(meta.get("audio"))
        stem = outdir / f.stem
        cut = f"{stem}_cut.mp4"
        seg_end = min(dur, args.seconds) if dur else args.seconds
        fast = ["--fast"]
        plan = []
        plan.append(("cut copy", ["cut.py", str(f), "--start", "0", "--end", f"{seg_end:.2f}", "-o", cut]))
        if has_v:
            plan.append(("cut accurate", ["cut.py", str(f), "--start", "0", "--end", f"{seg_end:.2f}", "--accurate", "-o", f"{stem}_acc.mp4"] + fast))
            plan.append(("fit 9:16", ["fit.py", cut, "--aspect", "9:16", "--width", "720", "-o", f"{stem}_fit.mp4"] + fast))
            cues = outdir / f"{f.stem}_cues.txt"
            cues.write_text("0:00-0:02 Verification caption\n0:02-0:04 Second | line\n", encoding="utf-8")
            plan.append(("caption", ["caption.py", cut, "--text", str(cues), "--animate", "pop", "--karaoke", "-o", f"{stem}_cap.mp4"] + fast))
            if not args.quick:
                plan.append(("overlay text", ["overlay.py", cut, "--text", "verify", "--position", "top-left", "-o", f"{stem}_ovl.mp4"] + fast))
                plan.append(("look sheet", ["look.py", cut, "-o", f"{stem}_sheet.png"]))
                if (meta.get("video") or {}).get("hdr"):
                    plan.append(("color to-sdr", ["color.py", f"{stem}_acc.mp4", "--to-sdr", "-o", f"{stem}_sdr.mp4"] + fast))
                    plan.append(("hdr preserved", ["__check_hdr__", f"{stem}_acc.mp4"]))
                plan.append(("probe analyze", ["probe.py", cut, "--analyze"]))
            plan.append(("export x", ["export.py", cut, "--preset", "x", "-o", f"{stem}_x.mp4"]))
        if has_a and not args.quick:
            plan.append(("loudness measure", ["loudness.py", str(f), "--measure-only"]))
            plan.append(("silence list", ["silence.py", cut, "--list"]))
            if (meta.get("audio") or {}).get("channels", 0) > 2:
                plan.append(("audio downmix", ["audio.py", cut, "--downmix", "-o", f"{stem}_st.mp4"]))
        for name, argv in plan:
            r = step(name, argv, args.timeout)
            entry["steps"].append(r)
            info(f"  {'PASS' if r['ok'] else 'FAIL'}  {name:16s} {r['seconds']:6.1f}s  {r['error']}")
        results.append(entry)

    total = sum(len(e["steps"]) for e in results)
    failed = sum(1 for e in results for s in e["steps"] if not s["ok"])
    lines = ["# ffmpeg-skill verification", "", f"{len(files)} files, {total} steps, {failed} failed", ""]
    for e in results:
        p = e.get("probe", {})
        v, a = p.get("video", {}), p.get("audio", {})
        lines.append(f"## {e['file']}")
        lines.append(f"{p.get('duration')}s, {v.get('codec')} {v.get('width')}x{v.get('height')} @ {v.get('fps')} {v.get('pix_fmt')}"
                     + (f" [{v.get('hdr_format')}]" if v.get("hdr_format") else "") + (" [VFR?]" if v.get("variable_frame_rate_suspected") else "")
                     + (f" rot {v.get('rotation')}" if v.get("rotation") else "") + f", audio {a.get('codec')} {a.get('channels')}ch")
        lines.append("")
        lines.append("| step | result | time | error |")
        lines.append("|---|---|---|---|")
        for s in e["steps"]:
            lines.append(f"| {s['step']} | {'PASS' if s['ok'] else 'FAIL'} | {s['seconds']}s | {s['error']} |")
        lines.append("")
    report = "\n".join(lines)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        info(f"wrote {args.report}")
    if args.json:
        emit(None, report=args.report, files=results, failed=failed, total=total)
    else:
        print(report)
    if tmp and not args.keep:
        tmp.cleanup()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
