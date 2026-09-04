#!/usr/bin/env python3
"""Contract evals, deterministic half: every expected answer in questions.json must be
derivable from the live contract. Run before a release and after any ToolSpec change.

    python3 evals/contract/check.py            # exits non-zero when the contract and the answers disagree
    python3 evals/contract/check.py --grade answers.json   # grade an agent's answers {"id": "answer", ...}

The agent half (README.md here) gives a model the contract JSON and questions.json and
records its answers; grade them with --grade.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
QUESTIONS = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))


def contract():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "_contract.py"), "--json", "--static"], stdout=subprocess.PIPE, text=True, check=True).stdout
    return json.loads(out)


def derive(doc):
    """Recompute every expected answer from the contract itself."""
    tools = {t["name"]: t for t in doc["tools"]}
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    return {
        "q1-tool-for-task": tools["silence"]["id"],
        "q2-required-capability": [c for c in tools["loudness"]["capabilities"]["required"] if c not in ("ffmpeg", "ffprobe", "encoder:aac")][0],
        "q3-visual-verification": yn(tools["caption"]["requires_visual_verification"]),
        "q4-no-visual-for-audio": yn(tools["loudness"]["requires_visual_verification"]),
        "q5-input-preserved": yn(tools["cut"]["mutates_input"]),
        "q6-dry-run": yn(tools["export"]["supports_dry_run"]),
        "q7-roles": f"probe={tools['probe']['role']}, cut={tools['cut']['role']}, check={tools['check']['role']}",
        "q8-no-shell-needed": "clip.mp4 --start 0:10 --end 0:20 -o out.mp4 --json",
        "q9-stable-ids": ", ".join(tools[n]["id"] for n in ("probe", "loudness", "export", "look")),
        "q10-verification-tools": ", ".join(tools["export"]["verification"]["tools"]),
    }


def norm(s):
    return re.sub(r"[\s`'\"]+", " ", str(s)).strip().lower().rstrip(".")


def main():
    doc = contract()
    derived = derive(doc)
    bad = [q["id"] for q in QUESTIONS if norm(derived[q["id"]]) != norm(q["expected"])]
    if bad:
        for b in bad:
            print(f"MISMATCH {b}: contract says {derived[b]!r}, questions.json expects {[q for q in QUESTIONS if q['id']==b][0]['expected']!r}")
        return 1
    print(f"contract evals: {len(QUESTIONS)} expected answers agree with the contract")
    if "--grade" in sys.argv:
        answers = json.loads(Path(sys.argv[sys.argv.index("--grade") + 1]).read_text(encoding="utf-8"))
        score = 0
        for q in QUESTIONS:
            got = norm(answers.get(q["id"], ""))
            ok = norm(q["expected"]) in got or got == norm(q["expected"])
            score += ok
            print(f"{'PASS' if ok else 'FAIL'} {q['id']}: {answers.get(q['id'], '')!r}")
        print(f"{score}/{len(QUESTIONS)}")
        return 0 if score == len(QUESTIONS) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
