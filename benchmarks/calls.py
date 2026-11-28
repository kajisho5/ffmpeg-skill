#!/usr/bin/env python3
"""Where the calls go: count each run's bash calls by kind, per task, from run.py's transcripts.

    python3 benchmarks/calls.py SKILL_TRANSCRIPTS [RAW_TRANSCRIPTS]

Each folder is a run.py `--out` (one `<task>-<run>/transcript.json` per run). With two folders,
the tasks are listed by how many more calls the first used than the second: the question #684
asks of the one model that uses more calls with the skill. A call is counted under the first kind
whose pattern it matches, so every call is counted once.
"""
import collections
import json
import re
import sys
from pathlib import Path

KINDS = [
    ("help", r"(^|\s)(--help|-h)(\s|$)"),
    ("read docs", r"\b(cat|head|tail|sed|less|grep|rg|find|ls)\b.*\b(SKILL\.md|references/|scripts/|\.py)\b"),
    ("dry run", r"--dry-run"),
    ("probe", r"\bprobe\.py\b"),
    ("check / verify / look", r"\b(check|verify|look)\.py\b"),
    ("skill tool", r"\b[a-z_]+\.py\b"),
    ("raw ffprobe", r"\bffprobe\b"),
    ("raw ffmpeg", r"\bffmpeg\b"),
    ("other shell", r""),
]


def kind_of(command):
    return next(name for name, pattern in KINDS if re.search(pattern, command))


def read(folder):
    """{task: [Counter of kinds, one per run]}"""
    out = collections.defaultdict(list)
    for path in sorted(Path(folder).glob("*/transcript.json")):
        task = path.parent.name.rsplit("-", 1)[0]
        counts = collections.Counter()
        for msg in json.loads(path.read_text(encoding="utf-8")):
            for call in msg.get("tool_calls") or []:
                try:
                    command = json.loads(call["function"].get("arguments") or "{}").get("command", "")
                except json.JSONDecodeError:
                    command = ""
                counts[kind_of(command)] += 1
        out[task].append(counts)
    return out


def mean_calls(runs):
    return sum(sum(c.values()) for c in runs) / len(runs) if runs else 0.0


def describe(runs):
    total = collections.Counter()
    for c in runs:
        total.update(c)
    return ", ".join(f"{k} {v / len(runs):.1f}" for k, v in total.most_common()) if runs else "-"


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    first = read(argv[1])
    second = read(argv[2]) if len(argv) == 3 else {}
    tasks = sorted(set(first) | set(second), key=lambda t: -(mean_calls(first.get(t, [])) - mean_calls(second.get(t, []))))
    for t in tasks:
        a, b = first.get(t, []), second.get(t, [])
        line = f"{t:14} {mean_calls(a):5.1f} calls  [{describe(a)}]"
        if second:
            line += f"   vs {mean_calls(b):5.1f}  [{describe(b)}]   {mean_calls(a) - mean_calls(b):+.1f}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
