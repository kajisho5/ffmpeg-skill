#!/usr/bin/env python3
"""Run calls an agent wrote blind, and say which the tools answered well.

The calls come from an agent that was shown only each tool's name and one line about it
(`--brief` prints that list). Its file is a JSON array of {"tool", "request", "argv"}, with
{clip} where an input video goes:

    python3 tests/first_try.py --brief > tools.txt             # what the blind agent may read
    python3 tests/first_try.py guesses.json                    # the counts, then each miss
    python3 tests/first_try.py guesses.json --json > rows.json # every row

Every call runs with --dry-run, so nothing is rendered. A row is one of:

    ran       exit 0. Read these too: a call can run and be wrong (`freeze.py --time 3` did).
    taught    a usage error that names one of the tool's own options for each unknown flag
    elsewhere it names only other tools that take the flag
    silent    an unknown flag and no pointer at all
    refused   any other refusal (a missing file, a value out of range): not about a name

Nothing here judges a row. `silent` and `elsewhere` are where a help string may lack the word
people reach for; a row that `ran` needs its plan read. .claude/skills/first-try-probe/SKILL.md
has the loop.
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_OUTPUT = {"check", "cropdetect", "probe", "scenes", "verify", "report"}  # tools that take no -o


def brief():
    doc = json.loads(subprocess.run([sys.executable, str(ROOT / "scripts" / "_contract.py"), "--json", "--static"],
                                    capture_output=True, text=True, check=True).stdout)
    return "\n".join(f"{t['name']}: {t['description'].split('. ')[0][:170]}" for t in doc["tools"])


def run(guess, clip, tmp, index):
    argv = [clip if a == "{clip}" else a for a in guess["argv"]]
    out = [] if guess["tool"] in NO_OUTPUT else ["-o", str(Path(tmp) / f"o{index}.mp4")]
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{guess['tool']}.py"), *argv, *out, "--dry-run"],
                          capture_output=True, text=True, timeout=180)
    text = proc.stdout + proc.stderr
    answer = text.rsplit("error:", 1)[-1].strip() if "error:" in text else ""
    unknown = re.findall(r"^(--[\w-]+) is not an option of this tool(.*)$", answer, re.M)
    own = lambda tail: "did you mean" in tail or "mention" in tail or "spelled in full" in tail
    if proc.returncode == 0:
        kind = "ran"
    elif not unknown:
        kind = "refused"
    elif all(own(tail) for _, tail in unknown):
        kind = "taught"
    elif all(own(tail) or "take" in tail for _, tail in unknown):
        kind = "elsewhere"
    else:
        kind = "silent"
    return dict(guess, kind=kind, answer=answer[:600])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("guesses", nargs="?", help="the blind agent's JSON file")
    ap.add_argument("--clip", default=str(ROOT / "demos" / "footage" / "veo_sea.mp4"), help="the video {clip} stands for")
    ap.add_argument("--brief", action="store_true", help="print each tool's name and one line about it, and stop")
    ap.add_argument("--json", action="store_true", help="print every row as JSON")
    args = ap.parse_args()
    if args.brief or not args.guesses:
        print(brief())
        return 0
    guesses = json.loads(Path(args.guesses).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        rows = [run(g, args.clip, tmp, i) for i, g in enumerate(guesses)]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    counts = collections.Counter(r["kind"] for r in rows)
    print(f"{len(rows)} calls: " + ", ".join(f"{counts[k]} {k}" for k in ("ran", "taught", "elsewhere", "silent", "refused")))
    for kind in ("silent", "elsewhere"):
        for r in (r for r in rows if r["kind"] == kind):
            print(f"{kind:9} {r['tool']} {' '.join(r['argv'])[:70]}  ({r['request'][:50]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
