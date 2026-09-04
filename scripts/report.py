#!/usr/bin/env python3
"""Build a single-file HTML delivery report: what went in, what came out,
before/after contact sheets, loudness, compliance and the exact commands.
The agent hands this to the user instead of a wall of text.

Examples:
  python3 report.py --before raw.mov --after final.mp4 -o report.html
  python3 report.py --after final.mp4 --platform reels --title "Episode 12 — Reels cut" -o report.html
  python3 report.py --before raw.mov --after final.mp4 --commands commands.txt --notes notes.md
"""
import argparse
import base64
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from _common import STATE, add_common, apply_common, die, emit, info, probe

HERE = Path(__file__).resolve().parent


def sheet_b64(path: str, tiles: str = "4x2", width: int = 1200) -> Optional[str]:
    with tempfile.TemporaryDirectory(prefix="ffskill_report_") as tmp:
        png = os.path.join(tmp, "sheet.png")
        proc = subprocess.run([sys.executable, str(HERE / "look.py"), path, "--tiles", tiles, "--width", str(width), "-o", png],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0 or not os.path.exists(png):
            return None
        return base64.b64encode(Path(png).read_bytes()).decode("ascii")


def loudness(path: str) -> Dict[str, Any]:
    proc = subprocess.run([sys.executable, str(HERE / "loudness.py"), path, "--measure-only"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        d = json.loads(proc.stdout)
        return {"lufs": round(float(d["input_i"]), 1), "tp": round(float(d["input_tp"]), 1), "lra": round(float(d["input_lra"]), 1)}
    except (ValueError, KeyError):
        return {}


def check(path: str, platform: str) -> Optional[Dict[str, Any]]:
    proc = subprocess.run([sys.executable, str(HERE / "check.py"), path, "--platform", platform, "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def fmt_dur(sec: Optional[float]) -> str:
    if not sec:
        return "?"
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:05.2f}" if h else f"{m}:{s:05.2f}"


def media_rows(meta: Dict[str, Any], ld: Dict[str, Any]) -> List[List[str]]:
    v, a = meta.get("video") or {}, meta.get("audio") or {}
    rows = [
        ["Duration", fmt_dur(meta.get("duration"))],
        ["Size", f"{(meta.get('size_bytes') or 0) / 1024 / 1024:.1f} MB"],
        ["Video", f"{v.get('codec')} {v.get('width')}×{v.get('height')} @ {v.get('fps')} fps, {v.get('pix_fmt')}" if v else "none"],
        ["Colour", (f"{v.get('color_primaries')}/{v.get('color_transfer')}" + (f" — {v.get('hdr_format')}" if v.get("hdr") else " (SDR)")) if v else "—"],
        ["Frame rate", ("variable (suspected)" if v.get("variable_frame_rate_suspected") else "constant") if v else "—"],
        ["Audio", f"{a.get('codec')} {a.get('channels')} ch {a.get('sample_rate')} Hz" if a else "none"],
    ]
    if ld:
        rows.append(["Loudness", f"{ld['lufs']} LUFS, TP {ld['tp']} dBTP, LRA {ld['lra']} LU"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", required=True, help="the deliverable")
    ap.add_argument("--before", help="the source (optional)")
    ap.add_argument("-o", "--output", help="report path (default: <after>_report.html)")
    ap.add_argument("--title", help="report title")
    ap.add_argument("--platform", help="run check.py for this platform and include the table")
    ap.add_argument("--commands", help="text file with the commands that were run (one per line)")
    ap.add_argument("--notes", help="text/markdown file with notes to include verbatim")
    ap.add_argument("--no-sheets", action="store_true", help="skip contact sheets (faster, smaller)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    after = probe(args.after)
    before = probe(args.before) if args.before else None
    ld_after = loudness(args.after) if after.get("audio") else {}
    ld_before = loudness(args.before) if before and before.get("audio") else {}
    chk = check(args.after, args.platform) if args.platform else None
    sheets = {}
    if not args.no_sheets:
        if before and before.get("video"):
            sheets["before"] = sheet_b64(args.before)
        if after.get("video"):
            sheets["after"] = sheet_b64(args.after)
    commands = Path(args.commands).read_text(encoding="utf-8").splitlines() if args.commands else []
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes else ""
    title = args.title or f"Delivery report — {Path(args.after).name}"
    output = args.output or str(Path(args.after).with_name(Path(args.after).stem + "_report.html"))

    def table(rows: List[List[str]]) -> str:
        return "<table>" + "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows) + "</table>"

    parts: List[str] = []
    parts.append(f"<h1>{html.escape(title)}</h1>")
    parts.append(f"<p class='meta'>{html.escape(os.path.abspath(args.after))}</p>")
    cols = []
    if before:
        cols.append(f"<div class='col'><h2>Before</h2><p class='file'>{html.escape(Path(args.before).name)}</p>{table(media_rows(before, ld_before))}"
                    + (f"<img src='data:image/png;base64,{sheets['before']}' alt='before contact sheet'>" if sheets.get("before") else "") + "</div>")
    cols.append(f"<div class='col'><h2>After</h2><p class='file'>{html.escape(Path(args.after).name)}</p>{table(media_rows(after, ld_after))}"
                + (f"<img src='data:image/png;base64,{sheets['after']}' alt='after contact sheet'>" if sheets.get("after") else "") + "</div>")
    parts.append("<div class='cols'>" + "".join(cols) + "</div>")
    if chk:
        rows = "".join(
            f"<tr class='{r['status'].lower()}'><td class='st'>{r['status']}</td><td>{html.escape(r['check'])}</td><td>{html.escape(str(r['value']))}</td><td>{html.escape(str(r['expected']))}</td><td>{html.escape(r.get('fix') or '') if r['status'] != 'PASS' else ''}</td></tr>"
            for r in chk["checks"])
        verdict = "READY" if chk.get("ok") else f"{chk.get('failed')} FAIL"
        parts.append(f"<h2>Compliance — {html.escape(args.platform)} <span class='verdict {'ok' if chk.get('ok') else 'bad'}'>{verdict}</span></h2>"
                     f"<table class='checks'><tr><th></th><th>check</th><th>value</th><th>expected</th><th>fix</th></tr>{rows}</table>")
    if notes:
        parts.append("<h2>Notes</h2><pre class='notes'>" + html.escape(notes) + "</pre>")
    if commands:
        parts.append("<h2>Commands</h2><pre class='cmd'>" + html.escape("\n".join(commands)) + "</pre>")
    parts.append("<p class='foot'>Generated by ffmpeg-skill · local FFmpeg, no cloud.</p>")

    css = """
    :root{--bg:#F4F6F8;--paper:#fff;--ink:#161B21;--ink2:#4B5661;--line:#D8DEE4;--ok:#2C8A5B;--warn:#C48519;--bad:#B4362F;--accent:#1E6F8E}
    @media (prefers-color-scheme:dark){:root{--bg:#111518;--paper:#191E23;--ink:#E8ECEF;--ink2:#AEB6BE;--line:#2A3138;--ok:#5CC38C;--warn:#E3A63C;--bad:#F07A73;--accent:#5FB2D4}}
    body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans JP",sans-serif}
    .wrap{max-width:1100px;margin:0 auto;padding:32px 20px 60px}
    h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 10px}
    .meta{color:var(--ink2);font-size:13px;margin:0 0 20px;word-break:break-all}
    .cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
    .col{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
    .col h2{margin-top:0}.file{color:var(--ink2);font-size:13px;margin:0 0 8px}
    table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
    th{color:var(--ink2);font-weight:500;width:34%}
    img{max-width:100%;border-radius:4px;margin-top:12px;border:1px solid var(--line)}
    .checks{background:var(--paper);border:1px solid var(--line);border-radius:6px;overflow:hidden}.checks th{width:auto}
    .st{font-weight:700;font-family:ui-monospace,Menlo,monospace}tr.pass .st{color:var(--ok)}tr.warn .st{color:var(--warn)}tr.fail .st{color:var(--bad)}
    .verdict{font-size:13px;padding:2px 8px;border-radius:3px;margin-left:8px;vertical-align:middle}.verdict.ok{background:var(--ok);color:#fff}.verdict.bad{background:var(--bad);color:#fff}
    pre{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:12px 14px;overflow-x:auto;font-size:12.5px;line-height:1.5}
    .foot{color:var(--ink2);font-size:12px;margin-top:36px;border-top:1px solid var(--line);padding-top:10px}
    """
    doc = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{css}</style></head><body><div class='wrap'>{''.join(parts)}</div></body></html>"
    if STATE.dry_run:
        info(f"wrote {output}")  # printed as "[dry-run] would write"; nothing is written
    else:
        Path(output).write_text(doc, encoding="utf-8")
        info(f"wrote {output} ({os.path.getsize(output) / 1024:.0f} KB)")
    emit(None, report=output, check=chk)
    if not args.json:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
