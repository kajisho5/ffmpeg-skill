#!/usr/bin/env python3
"""Score an agent transcript against an eval prompt corpus, with regex-only grading.

Usage:
  python3 evals/run.py transcript.txt --task 5        # did the transcript for task 5 call the expected script(s)?
  python3 evals/run.py --list                          # print the prompts (paste them to the agent one by one)
  python3 evals/run.py results/                         # folder of <id>.txt transcripts -> pass rate
  python3 evals/run.py results/ --prompts evals/agent_prompts_24.json   # the 108-prompt set

A transcript "passes" when:
  - every expected script name (or `a|b` alternation slot) appears in it, and
  - if the prompt carries `grader_expect`, that regex also matches the transcript, and
  - if the prompt carries `grader_not`, that regex does NOT match the transcript.

Every check here is a substring or regex match against the transcript text -- there is no LLM
grading step and no dependency on any particular model or vendor. That makes this script usable
from any agent harness that can produce a transcript file: Claude Code, Cursor, Codex, or a
plain script that pipes an agent's tool-call log to a text file. See evals/README.md's
"Running this from Cursor, Codex, or another harness" section for the walkthrough, and be aware
of what regex-only grading can't catch (also documented there) -- it checks that the right
scripts were invoked and that a few disclosure phrases are present or absent; it does not judge
whether the output is actually good.

Pair with skill-creator's eval runner for automated, multi-run measurement.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PROMPTS = HERE / "tasks.json"


def load_tasks(prompts_path: Path) -> list:
    """Load an eval corpus and normalise it to a common shape.

    Two on-disk shapes are supported:
      - tasks.json:            {"tasks": [{"id": int, "request": str, "expect": [...]}, ...]}
      - agent_prompts*.json:   [{"id": str, "prompt": str, "expect": [...], ...}, ...]

    Both are normalised to a list of dicts with `id`, `request`, `expect`,
    `grader_expect` (optional regex, or None) and `grader_not` (optional regex, or None).
    `expect` entries may use `a|b` alternation (with or without a `.py` suffix on each side)
    to mean "either satisfies this slot".
    """
    raw = json.loads(prompts_path.read_text(encoding="utf-8"))
    items = raw["tasks"] if isinstance(raw, dict) and "tasks" in raw else raw
    tasks = []
    for t in items:
        tasks.append({
            "id": t["id"],
            "request": t.get("request") or t.get("prompt") or "",
            "expect": t.get("expect") or [],
            "grader_expect": t.get("grader_expect"),
            "grader_not": t.get("grader_not"),
            "refuse": bool(t.get("refuse")),
        })
    return tasks


def _slot_hit(slot: str, text: str) -> bool:
    """One `expect` entry, e.g. "fit.py|render.py" or "fit|render": true if any alternative
    (with or without a trailing ".py") appears in the transcript text."""
    for alt in slot.split("|"):
        alt = alt.strip()
        if not alt:
            continue
        if alt in text:
            return True
        stem = alt[:-3] if alt.endswith(".py") else alt
        if f"{stem}.py" in text:
            return True
    return False


def score(text: str, task: dict) -> tuple:
    """Regex/substring-only grading. Returns (passed, reasons) where reasons lists every check
    that failed: missing `expect` slots, a `grader_expect` pattern that never matched, or a
    `grader_not` pattern that matched when it must not have."""
    reasons = []
    missing = [e for e in task["expect"] if not _slot_hit(e, text)]
    if missing:
        reasons.append(f"missing: {', '.join(missing)}")
    ge = task.get("grader_expect")
    if ge and not re.search(ge, text):
        reasons.append(f"grader_expect not matched: {ge}")
    gn = task.get("grader_not")
    if gn and re.search(gn, text):
        reasons.append(f"grader_not matched (should not have): {gn}")
    return (not reasons, reasons)


def _find_transcript(folder: Path, task_id) -> Path:
    """Accept either a flat `<id>.txt`/`<id>.md` file in `folder`, or this repo's own
    `<id>/with_skill/outputs/run.md` iteration layout, whichever exists."""
    for name in (f"{task_id}.txt", f"{task_id}.md"):
        f = folder / name
        if f.exists():
            return f
    nested = folder / str(task_id) / "with_skill" / "outputs" / "run.md"
    if nested.exists():
        return nested
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="transcript file or folder of <id>.txt/<id>.md files")
    ap.add_argument("--task", help="task id for a single transcript (int for tasks.json, string for agent_prompts*.json)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS,
                     help="eval corpus JSON to grade against (default: evals/tasks.json)")
    ap.add_argument("--json", action="store_true", help="print machine-readable results instead of text")
    args = ap.parse_args()

    tasks = load_tasks(args.prompts)

    if args.list:
        for t in tasks:
            print(f"{t['id']}. {t['request']}    -> {', '.join(t['expect']) or '(refusal, no expected script)'}")
        return 0
    if not args.target:
        ap.error("give a transcript file/folder or --list")

    p = Path(args.target)
    results = []
    if p.is_dir():
        for t in tasks:
            f = _find_transcript(p, t["id"])
            if f is not None:
                ok, reasons = score(f.read_text(encoding="utf-8", errors="replace"), t)
                results.append((t, ok, reasons))
    else:
        if args.task is None:
            ap.error("--task ID is required for a single transcript")
        task_id = args.task
        t = next((x for x in tasks if str(x["id"]) == str(task_id)), None)
        if not t:
            ap.error(f"no task {task_id}")
        ok, reasons = score(p.read_text(encoding="utf-8", errors="replace"), t)
        results.append((t, ok, reasons))

    passed = sum(1 for _, ok, _ in results if ok)

    if args.json:
        out = {
            "prompts": str(args.prompts),
            "passed": passed,
            "total": len(results),
            "results": [
                {"id": t["id"], "request": t["request"], "passed": ok, "reasons": reasons}
                for t, ok, reasons in results
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        for t, ok, reasons in results:
            print(f"{'PASS' if ok else 'FAIL'} {str(t['id']):>4s} {t['request'][:60]:60s}" +
                  ("" if ok else "  " + "; ".join(reasons)))
        print(f"{passed}/{len(results)} passed  (grading: regex-only, {args.prompts.name})")

    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
