#!/usr/bin/env python3
"""Build a single-file HTML delivery report: what went in, what came out,
before/after contact sheets, loudness, compliance and the exact commands.
The agent hands this to the user instead of a wall of text.

Examples:
  python3 report.py --before raw.mov --after final.mp4 -o report.html
  python3 report.py --after final.mp4 --platform reels --title "Episode 12 — Reels cut" -o report.html
  python3 report.py --before raw.mov --after final.mp4 --commands commands.txt --notes notes.md
  python3 report.py --pack talk_pack.md -o pack.html          # the social pack table as HTML
"""
import argparse
import base64
import html
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from _common import STATE, add_common, apply_common, child_args, die, emit, info, probe, read_text_or_die, run_tool

HERE = Path(__file__).resolve().parent


def sheet_b64(path: str, tiles: str = "4x2", width: int = 1200) -> Optional[str]:
    with tempfile.TemporaryDirectory(prefix="ffskill_report_") as tmp:
        png = os.path.join(tmp, "sheet.png")
        proc = run_tool([str(HERE / "look.py"), path, "--tiles", tiles, "--width", str(width), "-o", png] + child_args())
        if proc.returncode != 0 or not os.path.exists(png):
            return None
        return base64.b64encode(Path(png).read_bytes()).decode("ascii")


def loudness(path: str) -> Dict[str, Any]:
    proc = run_tool([str(HERE / "loudness.py"), path, "--measure-only"] + child_args())
    try:
        d = json.loads(proc.stdout)
        return {"lufs": round(float(d["input_i"]), 1), "tp": round(float(d["input_tp"]), 1), "lra": round(float(d["input_lra"]), 1)}
    except (ValueError, KeyError):
        return {}


def check(path: str, platform: str) -> Optional[Dict[str, Any]]:
    proc = run_tool([str(HERE / "check.py"), path, "--platform", platform, "--json"] + child_args())
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or "checks" not in doc:
        # check.py could not run at all (missing ffmpeg, unreadable file): its failure document
        # has no rows to render. A failed *verification* still carries its rows and is shown.
        reason = ((doc or {}).get("error") or {}).get("message") or (proc.stderr.strip().splitlines() or ["?"])[-1]
        info(f"check.py could not run: {reason[:200]}")
        return None
    return doc


def fmt_dur(sec: Optional[float]) -> str:
    if sec is None:
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


PACK_CSS = """
    :root{--bg:#F4F6F8;--paper:#fff;--ink:#161B21;--ink2:#4B5661;--line:#D8DEE4;--ok:#2C8A5B;--bad:#B4362F}
    @media (prefers-color-scheme:dark){:root{--bg:#111518;--paper:#191E23;--ink:#E8ECEF;--ink2:#AEB6BE;--line:#2A3138;--ok:#5CC38C;--bad:#F07A73}}
    body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans JP",sans-serif}
    .wrap{max-width:900px;margin:0 auto;padding:32px 20px 60px}
    h1{font-size:24px;margin:0 0 16px}
    table{border-collapse:collapse;width:100%;font-size:14px;background:var(--paper);border:1px solid var(--line);border-radius:6px;overflow:hidden}
    th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}th{color:var(--ink2);font-weight:500}
    td.pass{color:var(--ok);font-weight:600}td.bad{color:var(--bad);font-weight:600}
    p.note{color:var(--ink2);font-size:13px}
    .foot{color:var(--ink2);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:10px}
"""


def pack_report(args) -> int:
    """render.py --template all writes <stem>_pack.md: one row per destination. This renders the
    same rows as HTML, so a pack can be handed over the way a single delivery report is -- no
    re-measurement, because the pack table is what the renders actually produced."""
    text = read_text_or_die(args.pack, "--pack")
    rows: List[List[str]] = []
    header: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if not header:
            header = cells
        else:
            rows.append(cells)
    if not rows:
        die(f"{args.pack}: no pack table found (expected the Markdown table render.py --template all writes)")
    title = args.title or f"Social pack — {Path(args.pack).stem.replace('_pack', '')}"
    output = args.output or str(Path(args.pack).with_suffix(".html"))
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = ""
    for r in rows:
        cells = ""
        for i, c in enumerate(r):
            cls = ""
            if header[i:i + 1] == ["check"]:
                cls = " class='pass'" if c.lower() == "pass" else " class='bad'"
            cells += f"<td{cls}>{html.escape(c)}</td>"
        body += f"<tr>{cells}</tr>"
    doc = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{html.escape(title)}</title><style>{PACK_CSS}</style></head><body><div class='wrap'>"
           f"<h1>{html.escape(title)}</h1><table><tr>{head}</tr>{body}</table>"
           f"<p class='note'>{len(rows)} destination(s) from one edit.</p>"
           "<p class='foot'>Generated by ffmpeg-skill · local FFmpeg, no cloud.</p></div></body></html>")
    if STATE.dry_run:
        info(f"wrote {output}")
    else:
        try:
            Path(output).write_text(doc, encoding="utf-8")
        except OSError as e:
            die(f"cannot write {output}: {e}", kind="output")
        info(f"wrote {output} ({os.path.getsize(output) / 1024:.0f} KB)")
    emit(None, report=output, pack=[dict(zip(header, r)) for r in rows], check=None,
         verification=([{"step": "exists", "ok": True}] if not STATE.dry_run else []))
    if not args.json:
        print(output)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", help="the deliverable (required unless --pack is given)")
    ap.add_argument("--pack", metavar="FILE", help="a social pack table written by render.py --template all (<stem>_pack.md): render it as HTML")
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

    if args.pack:
        return pack_report(args)
    if not args.after:
        die("--after is required (or --pack FILE for a social pack table)")
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
    commands = read_text_or_die(args.commands, "--commands").splitlines() if args.commands else []
    notes = read_text_or_die(args.notes, "--notes") if args.notes else ""
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
        try:
            Path(output).write_text(doc, encoding="utf-8")
        except OSError as e:
            die(f"cannot write {output}: {e}", kind="output")
        info(f"wrote {output} ({os.path.getsize(output) / 1024:.0f} KB)")
    emit(None, report=output, check=chk, verification=([{"step": "exists", "ok": True}] if not STATE.dry_run else []))
    if not args.json:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
