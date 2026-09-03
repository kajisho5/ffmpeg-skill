#!/usr/bin/env python3
"""Score an agent transcript against evals/tasks.json.

Usage:
  python3 evals/run.py transcript.txt --task 5        # did the transcript for task 5 call the expected script(s)?
  python3 evals/run.py --list                         # print the prompts (paste them to the agent one by one)
  python3 evals/run.py results/                       # folder of <id>.txt transcripts -> pass rate

A transcript "passes" when every expected script name (or flag) appears in it.
Pair with skill-creator's eval runner for automated, multi-run measurement.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))["tasks"]


def score(text: str, task: dict) -> tuple:
    missing = [e for e in task["expect"] if e not in text]
    return (not missing, missing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="transcript file or folder of <id>.txt files")
    ap.add_argument("--task", type=int, help="task id for a single transcript")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for t in TASKS:
            print(f"{t['id']:2d}. {t['request']}    -> {', '.join(t['expect'])}")
        return 0
    if not args.target:
        ap.error("give a transcript file/folder or --list")
    p = Path(args.target)
    results = []
    if p.is_dir():
        for t in TASKS:
            f = p / f"{t['id']}.txt"
            if f.exists():
                ok, missing = score(f.read_text(encoding="utf-8", errors="replace"), t)
                results.append((t, ok, missing))
    else:
        if not args.task:
            ap.error("--task ID is required for a single transcript")
        t = next((x for x in TASKS if x["id"] == args.task), None)
        if not t:
            ap.error(f"no task {args.task}")
        ok, missing = score(p.read_text(encoding="utf-8", errors="replace"), t)
        results.append((t, ok, missing))
    passed = sum(1 for _, ok, _ in results if ok)
    for t, ok, missing in results:
        print(f"{'PASS' if ok else 'FAIL'} {t['id']:2d} {t['request'][:60]:60s}" + ("" if ok else f"  missing: {', '.join(missing)}"))
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
