#!/usr/bin/env python3
"""Run one input through every tool that takes a single media file, and print what each said.

A defect reported against one tool is usually a property of an input (an odd-sized frame, a
subtitle track, a start time that is not 0) or of a shared step, so the first question after
reproducing it is which other tools meet the same thing. This answers it in one command:

    python3 tests/sweep.py odd_629x1401.mov                 # every tool in the table
    python3 tests/sweep.py clip.mkv --only cut,crop,export  # some of them
    python3 tests/sweep.py clip.mp4 --json > sweep.json     # the rows as JSON
    python3 tests/sweep.py clip.mp4 --baseline plain.mp4    # only rows that differ from a plain clip's

A row is the tool's own result document reduced to: status, error kind, verified, warning and
fallback codes, source_carry.dropped, and the last line of an error message. Nothing here judges
a row: a refusal with a hint can be the decided behaviour (docs/design-decisions.md). Read the
rows that differ from the baseline, then decide.

The table holds one minimal invocation per tool. A tool that needs a second file or a project is
not in it (join, sync, multicam, broll, render, batch, sequence, grid, insert): sweep those by hand.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# tool -> (arguments after the input, output extension). {w} and {h} are an even size at or
# below the input's; {mid} is the middle of the clip in seconds and {dur} its length.
TABLE = {
    "audio": (["--voice", "light"], ".mp4"),
    "caption": (["--text", "{cues}"], ".mp4"),
    "color": (["--correct", "--contrast", "1.1"], ".mp4"),
    "crop": (["--x", "0", "--y", "0", "--width", "{w}", "--height", "{h}"], ".mp4"),
    "cut": (["--start", "0.2", "--end", "{mid}"], ".mp4"),
    "cut --accurate": (["--start", "0.2", "--end", "{mid}", "--accurate"], ".mp4"),
    "deinterlace": ([], ".mp4"),
    "denoise": ([], ".mp4"),
    "export": (["--preset", "youtube"], ".mp4"),
    "fit": (["--duration", "{mid}"], ".mp4"),
    "freeze": (["--at", "{mid}", "--hold", "0.5"], ".mp4"),
    "graphics": (["--template", "title", "--title", "Sweep", "--start", "0", "--end", "{mid}"], ".mp4"),
    "look": (["--at", "{mid}"], ".png"),
    "loop": (["--times", "2"], ".mp4"),
    "loudness": ([], ".mp4"),
    "metadata": (["--title", "sweep"], ".mp4"),
    "overlay": (["--image", "{still}"], ".mp4"),
    "pad": (["--end", "0.5"], ".mp4"),
    "proxy": ([], ".mp4"),
    "redact": (["--x", "0", "--y", "0", "--width", "{w}", "--height", "{h}"], ".mp4"),
    "reverse": ([], ".mp4"),
    "silence": ([], ".mp4"),
    "speedramp": (["--segment", "0-{dur}:2.0"], ".mp4"),
    "stabilize": ([], ".mp4"),
    "straighten": (["--degrees", "2"], ".mp4"),
}


# One tool on one short clip: generous, and a stalled child still ends so the sweep reaches the rest.
TIMEOUT_S = 600


def run_json(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, subprocess.CompletedProcess(cmd, -1, "", f"no result after {TIMEOUT_S} s (timed out)")
    start = proc.stdout.find("{")
    try:
        return json.loads(proc.stdout[start:]) if start >= 0 else None, proc
    except ValueError:
        return None, proc


def row_for(tool, source, facts, work):
    name = tool.split()[0]
    args, ext = TABLE[tool]
    args = [a.format(**facts) for a in args]
    out = os.path.join(work, f"sweep_{tool.replace(' ', '_').replace('-', '')}{ext}")
    doc, proc = run_json([sys.executable, str(SCRIPTS / f"{name}.py"), source, *args, "-o", out, "--overwrite", "--json"])
    if doc is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or [""]
        status = "timeout" if proc.returncode == -1 and "timed out" in tail[0] else "no-json"
        return {"tool": tool, "status": status, "exit": proc.returncode, "message": tail[0][:200]}
    err = doc.get("error") or {}
    diag = doc.get("diagnostics") or {}
    row = {"tool": tool, "status": doc.get("status"), "kind": err.get("kind"), "verified": doc.get("verified"),
           "warnings": sorted(w.get("code") for w in diag.get("warnings") or []),
           "fallbacks": sorted(w.get("code") for w in diag.get("fallbacks") or []),
           "dropped": (doc.get("source_carry") or {}).get("dropped") or []}
    if doc.get("dropped_non_av_streams"):
        row["dropped_non_av_streams"] = True
    if err.get("message"):
        row["message"] = err["message"].strip().splitlines()[-1][:200]
    return row


def facts_for(source, work):
    doc, proc = run_json([sys.executable, str(SCRIPTS / "probe.py"), source, "--json"])
    failed = isinstance(doc, dict) and (doc.get("status") == "failed" or doc.get("error"))
    if not doc or failed or proc.returncode != 0:
        why = ((doc or {}).get("error") or {}).get("message") if isinstance(doc, dict) else None
        sys.exit(f"probe.py could not read {source}: {(why or proc.stderr or '').strip()[-300:]}")
    meta = doc[0] if isinstance(doc, list) else (doc.get("files") or [doc])[0] if "files" in doc else doc
    if not isinstance(meta, dict) or not (meta.get("video") or meta.get("audio")):
        sys.exit(f"probe.py found no picture or sound in {source}")
    video = meta.get("video") or {}
    duration = float(meta.get("duration") or 2.0)
    w, h = int(video.get("width") or 320), int(video.get("height") or 240)
    cues = os.path.join(work, "sweep_cues.txt")
    Path(cues).write_text(f"0-{max(duration / 2, 0.5):.2f} Sweep\n", encoding="utf-8")
    still = os.path.join(work, "sweep_still.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=64x64", "-frames:v", "1", still], check=True)
    return {"w": max(2, (w // 2) // 2 * 2), "h": max(2, (h // 2) // 2 * 2), "mid": f"{max(duration / 2, 0.4):.2f}",
            "dur": f"{duration:.3f}",
            "cues": cues, "still": still}


def sweep(source, tools, work):
    facts = facts_for(source, work)
    return [row_for(t, source, facts, work) for t in tools]


def show(row):
    bits = [f"{row['tool']:<16}", f"{row.get('status') or '?':<10}"]
    if row.get("kind"):
        bits.append(f"kind={row['kind']}")
    if row.get("verified") is not None:
        bits.append(f"verified={row['verified']}")
    for key in ("warnings", "fallbacks", "dropped"):
        if row.get(key):
            bits.append(f"{key}={','.join(row[key])}")
    if row.get("dropped_non_av_streams"):
        bits.append("dropped_non_av_streams")
    if row.get("message"):
        bits.append("| " + row["message"])
    return " ".join(bits)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--only", help="comma-separated tool names from the table")
    ap.add_argument("--baseline", help="a plain clip: print only the rows that differ from its rows")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    ap.add_argument("--list", action="store_true", help="print the table's tools and exit")
    args = ap.parse_args()
    if args.list:
        print("\n".join(TABLE))
        return 0
    tools = list(TABLE)
    if args.only:
        wanted = [t.strip() for t in args.only.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in TABLE]
        if unknown:
            sys.exit(f"not in the table: {', '.join(unknown)} (see --list)")
        tools = wanted
    with tempfile.TemporaryDirectory(prefix="ffskill-sweep-") as work:
        rows = sweep(args.input, tools, work)
        if args.baseline:
            base = {r["tool"]: r for r in sweep(args.baseline, tools, work)}
            rows = [r for r in rows if {k: v for k, v in r.items() if k != "message"} !=
                    {k: v for k, v in base[r["tool"]].items() if k != "message"}]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print("\n".join(show(r) for r in rows) or "no row differs from the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
