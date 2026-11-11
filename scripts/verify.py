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
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _common import STATE, add_common, apply_common, die, emit, guard_sidecar, info, probe

HERE = Path(__file__).resolve().parent
MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mxf", ".wav", ".m4a", ".mp3", ".flac", ".aac"}


def unique_stems(files: List[Path]) -> Dict[Path, str]:
    """Every file's outputs share one flat --out directory (stem = outdir / f.stem), so two files
    with the same basename from different folders -- entirely normal for real footage collected
    from multiple cameras/SD cards, e.g. two "clip.mp4"s in separate campaign folders -- used to
    resolve to the identical output prefix. Each file's own steps still ran correctly in isolation,
    but with --keep the second file's outputs silently overwrote the first file's on disk, and the
    report showed PASS for both without ever flagging the collision (same bug class already fixed
    in batch.py). Disambiguate every colliding stem with a stable per-collision index instead."""
    counts: Dict[str, int] = {}
    for f in files:
        counts[f.stem] = counts.get(f.stem, 0) + 1
    seen: Dict[str, int] = {}
    stems: Dict[Path, str] = {}
    for f in files:
        if counts[f.stem] > 1:
            seen[f.stem] = seen.get(f.stem, 0) + 1
            stems[f] = f"{f.stem}_{seen[f.stem]}"
        else:
            stems[f] = f.stem
    return stems


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


def _cell(message: str) -> str:
    """A failure message as one Markdown table cell: one line, no pipes, at most 200 characters."""
    return " / ".join(line.strip() for line in str(message).splitlines() if line.strip()).replace("|", "/")[:200]


def _probe_capturing(path: str) -> "Tuple[Optional[Dict[str, Any]], Dict[str, Any]]":
    """probe() in this process, with its failure kept: (the probe, {}) or (None, the failure's
    kind/reason/message). probe() dies on an unreadable file; its failure document is read back
    instead of a fixed string standing in for it (one JSON document per run: it is not printed)."""
    was_json, STATE.json = STATE.json, True
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return probe(path), {}
    except SystemExit as exc:
        try:
            doc = json.loads(out.getvalue())
        except ValueError:
            doc = {}
        e = doc.get("error") if isinstance(doc.get("error"), dict) else {}
        failure = {k: e[k] for k in ("kind", "reason", "message") if e.get(k)}
        failure.setdefault("message", (err.getvalue().strip().splitlines() or [f"probe exited {exc.code}"])[-1])
        return None, failure
    finally:
        STATE.json = was_json


def step(name: str, argv: List[str], timeout: float) -> Dict:
    """Run one step and keep what its tool said: `ok` (it completed), and on a failure the tool's
    own `kind`, `reason` and `message` (its --json failure document), `error` being that message
    for the table. A completed step also carries the tool's `verified`."""
    t0 = time.time()
    if argv[0] == "__check_hdr__":
        meta, failure = _probe_capturing(argv[1])
        if meta is None:
            return dict({"step": name, "ok": False, "seconds": round(time.time() - t0, 1), "error": _cell(failure.get("message", ""))}, **failure)
        v = meta.get("video") or {}
        ok = bool(v.get("bt2020_or_hdr")) and v.get("bit_depth", 8) >= 10
        r: Dict[str, Any] = {"step": name, "ok": ok, "seconds": round(time.time() - t0, 1),
                             "error": "" if ok else f"re-encode lost HDR: {v.get('color_transfer')}/{v.get('pix_fmt')}"}
        if not ok:
            r.update(kind="verification", reason="hdr_lost", message=r["error"])
        return r
    try:
        proc = subprocess.run([sys.executable, str(HERE / argv[0])] + argv[1:] + ["--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout or None)
    except subprocess.TimeoutExpired:
        msg = f"timeout after {timeout:.0f}s"
        return {"step": name, "ok": False, "seconds": round(time.time() - t0, 1), "error": msg,
                "kind": "timeout", "reason": "step_timeout", "message": msg}
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = None
    doc = doc if isinstance(doc, dict) else {}
    ok = proc.returncode == 0
    r = {"step": name, "ok": ok, "seconds": round(time.time() - t0, 1), "error": ""}
    if ok:
        if "verified" in doc:
            r["verified"] = doc["verified"]
        return r
    e = doc.get("error") if isinstance(doc.get("error"), dict) else {}
    r["message"] = str(e.get("message") or (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1])
    r["error"] = _cell(r["message"])
    for k in ("kind", "reason", "details"):
        if e.get(k) is not None:
            r[k] = e[k]
    if not e:
        r["reason"] = "step_output_unparsed"
    r["exit_code"] = proc.returncode
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="media files and/or folders")
    ap.add_argument("--out", help="directory for outputs (default: temp dir, deleted unless --keep)")
    ap.add_argument("--keep", action="store_true", help="keep the outputs")
    ap.add_argument("--quick", action="store_true", help="probe, copy cut, fit, caption, export only")
    ap.add_argument("--seconds", type=float, default=6.0, help="length of the test cut taken from each file (default 6)")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-step timeout in seconds (default 600; 0 = no limit, as everywhere else)")
    ap.add_argument("--report", help="write a Markdown report here")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    if STATE.plan:
        die("verify.py does not support --plan: its steps run for real (it ignores --dry-run too)")

    files = collect(args.paths)
    tmp = None
    if args.out:
        # made first, so a --report inside a new --out folder passes the guard below (#413 review)
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
    if args.report:
        # a file this run writes itself (#408): not one of the media it verifies (a folder's
        # files included), nor an existing file without --overwrite
        guard_sidecar(args.report, *args.paths, *map(str, files))
    if not args.out:
        tmp = tempfile.TemporaryDirectory(prefix="ffskill_verify_")
        outdir = Path(tmp.name)

    stem_for = unique_stems(files)
    results = []
    for f in files:
        info(f"=== {f}")
        entry: Dict = {"file": str(f), "steps": [], "skipped": []}
        meta, failure = _probe_capturing(str(f))
        if meta is None:
            entry["steps"].append(dict({"step": "probe", "ok": False, "seconds": 0, "error": _cell(failure.get("message", ""))}, **failure))
            entry["skipped"].append({"step": "*", "reason": "input_unreadable", "message": "no other step runs on a file probe cannot read"})
            results.append(entry)
            continue
        entry["probe"] = {k: meta.get(k) for k in ("duration", "format")}
        entry["probe"]["video"] = {k: (meta.get("video") or {}).get(k) for k in ("codec", "width", "height", "fps", "pix_fmt", "hdr_format", "rotation", "variable_frame_rate_suspected")}
        entry["probe"]["audio"] = {k: (meta.get("audio") or {}).get(k) for k in ("codec", "channels", "sample_rate")}
        entry["steps"].append({"step": "probe", "ok": True, "seconds": 0, "error": ""})
        dur = meta.get("duration") or 0.0
        has_v, has_a = bool(meta.get("video")), bool(meta.get("audio"))
        stem = outdir / stem_for[f]
        cut = f"{stem}_cut.mp4"
        seg_end = min(dur, args.seconds) if dur else args.seconds
        fast = ["--fast"]
        plan = []
        skipped: List[Dict[str, str]] = entry["skipped"]

        def skip(step_name: str, reason: str, message: str) -> None:
            skipped.append({"step": step_name, "reason": reason, "message": message})
        plan.append(("cut copy", ["cut.py", str(f), "--start", "0", "--end", f"{seg_end:.2f}", "-o", cut]))
        if has_v:
            plan.append(("cut accurate", ["cut.py", str(f), "--start", "0", "--end", f"{seg_end:.2f}", "--accurate", "-o", f"{stem}_acc.mp4"] + fast))
            plan.append(("fit 9:16", ["fit.py", cut, "--aspect", "9:16", "--width", "720", "-o", f"{stem}_fit.mp4"] + fast))
            cues = outdir / f"{stem_for[f]}_cues.txt"
            cues.write_text("0:00-0:02 Verification caption\n0:02-0:04 Second | line\n", encoding="utf-8")
            plan.append(("caption", ["caption.py", cut, "--text", str(cues), "--animate", "pop", "--karaoke", "-o", f"{stem}_cap.mp4"] + fast))
            if not args.quick:
                plan.append(("overlay text", ["overlay.py", cut, "--text", "verify", "--position", "top-left", "-o", f"{stem}_ovl.mp4"] + fast))
                plan.append(("look sheet", ["look.py", cut, "-o", f"{stem}_sheet.png"]))
                if (meta.get("video") or {}).get("bt2020_or_hdr"):
                    plan.append(("color to-sdr", ["color.py", f"{stem}_acc.mp4", "--to-sdr", "-o", f"{stem}_sdr.mp4"] + fast))
                    plan.append(("hdr preserved", ["__check_hdr__", f"{stem}_acc.mp4"]))
                plan.append(("probe analyze", ["probe.py", cut, "--analyze"]))
            else:
                for n in ("overlay text", "look sheet", "color to-sdr", "hdr preserved", "probe analyze"):
                    skip(n, "quick", "--quick runs probe, copy cut, fit, caption and export only")
            if not args.quick and not (meta.get("video") or {}).get("bt2020_or_hdr"):
                for n in ("color to-sdr", "hdr preserved"):
                    skip(n, "not_hdr", "the file is not HDR")
            plan.append(("export x", ["export.py", cut, "--preset", "x", "-o", f"{stem}_x.mp4"]))
        else:
            for n in ("cut accurate", "fit 9:16", "caption", "overlay text", "look sheet", "color to-sdr", "hdr preserved",
                      "probe analyze", "export x"):
                skip(n, "no_video", "the file has no video stream")
        if has_a and not args.quick:
            plan.append(("loudness measure", ["loudness.py", str(f), "--measure-only"]))
            plan.append(("silence list", ["silence.py", cut, "--list"]))
            if (meta.get("audio") or {}).get("channels", 0) > 2:
                plan.append(("audio downmix", ["audio.py", cut, "--downmix", "-o", f"{stem}_st.mp4"]))
            else:
                skip("audio downmix", "not_multichannel", "the audio has 2 channels or fewer")
        elif not has_a:
            for n in ("loudness measure", "silence list", "audio downmix"):
                skip(n, "no_audio", "the file has no audio stream")
        else:
            for n in ("loudness measure", "silence list", "audio downmix"):
                skip(n, "quick", "--quick runs probe, copy cut, fit, caption and export only")
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
        for s in e.get("skipped") or []:
            lines.append(f"| {s['step']} | SKIP | - | {s['message']} |")
        lines.append("")
    report = "\n".join(lines)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        info(f"wrote {args.report}")
    if not args.json:
        print(report)
    if tmp and not args.keep:
        tmp.cleanup()
    if failed:
        die(f"{failed} of {total} verification steps failed", kind="verification", output=None, dry_run=STATE.dry_run,
            report=args.report, files=results, failed=failed, total=total)
    if args.json:
        emit(None, report=args.report, files=results, failed=failed, total=total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
