#!/usr/bin/env python3
"""Give every numeric option of every tool a zero, a negative and a huge value, and list what ran.

A value at the edge of an option's range is where a tool most often does something nobody decided:
0 that means "off" on one option and "no limit" on another, a negative length, a size no frame has.
The tests give each option the values its author had in mind. This gives it the others:

    python3 tests/edge_values.py                       # every tool in tests/sweep.py's table
    python3 tests/edge_values.py --only fit,overlay    # some of them
    python3 tests/edge_values.py --json > rows.json    # every row, refused ones included

Each call is the tool's minimal invocation from tests/sweep.py plus one option at one edge value,
run with --dry-run, so nothing is rendered. A refusal is the good answer and is not printed. A
row that HUNG gave no answer in 45 s: the value was taken and the tool is working on it. A row
that RAN is printed too: the tool took the value. That is not yet a defect -- 0 is a real setting
on many options -- so read each one: does the help say what the value means, and does the plan
do that? .claude/skills/edge-probe/SKILL.md has the loop and what counts as a finding.

The options come from the contract (`_contract.py --json --static`): type integer or number,
without the ones every tool shares. A tool that is not in sweep.py's table (it needs a second
file or a project) is probed by hand.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EDGES = ("0", "-1", "1000000000")
HUNG_S = 45  # a dry run answers in a second or two; past this the value was taken and is being worked on
SHARED = {"timeout", "quality", "crf"}


def options():
    doc = json.loads(subprocess.run([sys.executable, str(ROOT / "scripts" / "_contract.py"), "--json", "--static"],
                                    capture_output=True, text=True, check=True).stdout)
    return {t["name"]: {spec["cli"][0]: spec.get("description", "") for name, spec in t["input_schema"]["properties"].items()
                        if spec.get("type") in ("integer", "number") and name not in SHARED and spec.get("cli")}
            for t in doc["tools"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clip", default=str(ROOT / "demos" / "footage" / "veo_sea.mp4"))
    ap.add_argument("--only", help="comma-separated tool names")
    ap.add_argument("--json", action="store_true", help="print every row as JSON")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    by_tool, rows = options(), []
    with tempfile.TemporaryDirectory() as work:
        facts = sweep.facts_for(args.clip, work)
        for entry, (base, ext) in sweep.TABLE.items():
            tool = entry.split()[0]
            if " " in entry or (only and tool not in only):
                continue
            base = [a.format(**facts) for a in base]
            out = ["-o", str(Path(work) / f"edge{ext}")] if ext else []
            for flag, text in by_tool.get(tool, {}).items():
                for value in EDGES:
                    cmd = [sys.executable, str(ROOT / "scripts" / f"{tool}.py"), args.clip, *base, f"{flag}={value}", *out, "--dry-run", "--overwrite"]
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=HUNG_S)
                        how, last = ("ran" if proc.returncode == 0 else "refused"), (proc.stderr.strip().splitlines() or [""])[-1]
                    except subprocess.TimeoutExpired:
                        how, last = "hung", f"no answer after {HUNG_S} s"
                    rows.append({"tool": tool, "flag": flag, "value": value, "how": how, "help": text, "said": last[:300]})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    count = lambda how: sum(1 for r in rows if r["how"] == how)
    print(f"{len(rows)} calls on {len({r['tool'] for r in rows})} tools: {count('refused')} refused, {count('ran')} ran, {count('hung')} hung")
    for r in sorted((r for r in rows if r["how"] != "refused"), key=lambda r: r["how"]):
        print(f"{r['how'].upper():5} {r['tool']} {r['flag']}={r['value']}  | {r['help'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
