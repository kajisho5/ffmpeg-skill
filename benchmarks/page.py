#!/usr/bin/env python3
"""Build docs/benchmark.md from the committed results files, and check a results file's shape.

    python3 benchmarks/page.py --write    # regenerate docs/benchmark.md
    python3 benchmarks/page.py --check    # exit 1 when docs/benchmark.md is not what the results give

The page is never edited by hand: .github/scripts/build_pages.py renders it from
benchmarks/results/*.json for the Pages site, and tests/test_benchmarks.py fails when the
committed copy differs. A results file is one model (or one published group of models), one arm,
one release; `validate()` is the schema, and run.py calls it before it writes.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = HERE / "results"
PAGE = ROOT / "docs" / "benchmark.md"
SCHEMA = 1
SERIES = "common-24"  # benchmarks/tasks.py TASK_SET
REPO = "https://github.com/kajisho5/ffmpeg-skill/"

REQUIRED = {"schema": int, "date": str, "release": str, "arm": str, "models": list, "task_set": str, "tasks": int,
            "runs_per_task": int, "requests": int, "call_limit": int, "correct": (int, type(None)),
            "calls_per_request": (int, float, type(None)), "cost_usd": (int, float, type(None)), "source": str, "note": str}
OPTIONAL = {"label": str, "correct_per_run": list, "calls_per_request_range": list, "ffmpeg": str, "tasks_sha256": str,
            "runs": list, "per_task": dict}
RUN_ROW = {"task": str, "run": int, "ok": bool, "detail": str, "calls": int, "cost_usd": (int, float, type(None)),
           "stopped": str, "claimed": str}
TASK_SETS = {
    "scratch-24": "The 24 ordinary requests of the 2026-11-21 benchmark (cut, resize, 9:16, mute, fade, join, captions, "
                  "loudness, a Reel, cut out the pauses, ...), run from a scratch folder. That task file is not in the repository, "
                  "so these rows are the published record and are not re-run as they stand",
    "named-cuts-9": "Nine requests that name an editor's cut (cutaway, reaction cut, insert, smash cut, cross-cutting, montage, "
                    "establishing shot, J-cut, L-cut), the baseline in #675, same scratch harness",
    "common-24": "[benchmarks/tasks.py](../benchmarks/tasks.py): 24 ordinary requests, each output measured; "
                 "the series this repository runs. Its requests are not the scratch-24 ones, so compare its rows with each other",
}


class Invalid(ValueError):
    pass


def validate(doc, name="results"):
    """Raise Invalid naming the first field that is missing, of the wrong type, or inconsistent."""
    def need(cond, why):
        if not cond:
            raise Invalid(f"{name}: {why}")
    need(isinstance(doc, dict), "is not an object")
    for key, kind in REQUIRED.items():
        need(key in doc, f"has no `{key}`")
        need(isinstance(doc[key], kind) and not isinstance(doc[key], bool), f"`{key}` is {type(doc[key]).__name__}")
    for key in doc:
        need(key in REQUIRED or key in OPTIONAL, f"`{key}` is not a field of schema {SCHEMA}")
        if key in OPTIONAL:
            need(isinstance(doc[key], OPTIONAL[key]), f"`{key}` is {type(doc[key]).__name__}")
    need(doc["schema"] == SCHEMA, f"schema is {doc['schema']}, this page reads {SCHEMA}")
    need(re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["date"]), "`date` is not YYYY-MM-DD")
    need(re.fullmatch(r"\d+\.\d+\.\d+", doc["release"]), "`release` is not a version")
    need(doc["arm"] in ("skill", "raw"), "`arm` is neither skill nor raw")
    need(doc["models"] and all(isinstance(m, str) and m for m in doc["models"]), "`models` is empty")
    need(min(doc["tasks"], doc["runs_per_task"], doc["call_limit"]) > 0, "a count is not positive")
    need(0 < doc["requests"] <= doc["tasks"] * doc["runs_per_task"] * len(doc["models"]), "`requests` is more than tasks x runs x models")
    need(doc["correct"] is None or 0 <= doc["correct"] <= doc["requests"], "`correct` is outside 0..requests")
    need(doc["calls_per_request"] is None or 0 <= doc["calls_per_request"] <= doc["call_limit"], "`calls_per_request` is outside 0..call_limit")
    need(doc["correct"] is not None or doc["calls_per_request"] is not None, "neither `correct` nor `calls_per_request` is recorded")
    if doc["source"] == "benchmarks/run.py":  # a run made here carries every run it counts
        rows = doc.get("runs")
        need(isinstance(rows, list) and len(rows) == doc["requests"], "a run.py result lists every run in `runs`")
        for row in rows:
            for key, kind in RUN_ROW.items():
                need(key in row and isinstance(row[key], kind), f"a run row has no `{key}` of type {kind}")
        need(doc["correct"] == sum(r["ok"] for r in rows), "`correct` is not the count of runs that are ok")
    else:  # a published figure names where it was published
        need(doc["source"].startswith(REPO), "`source` is neither benchmarks/run.py nor a link into this repository")
        need("runs" not in doc, "a published figure has no `runs`; they were not kept")
    return doc


def load(results=RESULTS):
    docs = []
    for path in sorted(Path(results).glob("*.json")):
        docs.append((path.name, validate(json.loads(path.read_text(encoding="utf-8")), path.name)))
    return docs


def version_key(doc):
    return (doc["date"], tuple(int(x) for x in doc["release"].split(".")))


def number(x):
    """7.0 as 7.0 (the published figure), 7.833 as 7.83."""
    return f"{x:.1f}" if round(x, 1) == x else f"{x:.2f}"


def cells(doc):
    correct = "not measured" if doc["correct"] is None else f"{doc['correct']} of {doc['requests']}"
    if doc.get("correct_per_run") and len(doc["correct_per_run"]) > 1:
        correct += f" ({min(doc['correct_per_run'])}-{max(doc['correct_per_run'])} per pass)"
    calls = "not measured" if doc["calls_per_request"] is None else number(doc["calls_per_request"])
    if doc.get("calls_per_request_range"):
        calls += " ({}-{})".format(*map(number, doc["calls_per_request_range"]))
    cost = "not recorded" if doc["cost_usd"] is None else f"${doc['cost_usd']:.2f}"
    source = doc["source"]
    link = f"[{'#' + source.rsplit('/', 1)[-1].split('#')[0]}]({source})" if source.startswith(REPO) else "run.py"
    arm = "with the skill" if doc["arm"] == "skill" else "without (ffmpeg only)"
    release = doc.get("label") or doc["release"]
    return [", ".join(doc["models"]), arm, release, doc["date"], correct, calls, cost, str(doc["runs_per_task"]), link]


HEAD = ["Models", "Arm", "Release", "Date", "Correct", "Tool calls per request", "Cost", "Runs per task", "Source"]


def table(rows):
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in cells(d)) + " |" for d in rows]
    return "\n".join(lines)


def render(results=RESULTS):
    docs = [d for _, d in load(results)]
    sets = sorted({d["task_set"] for d in docs}, key=lambda s: (s not in TASK_SETS, list(TASK_SETS).index(s) if s in TASK_SETS else 0, s))
    sets_note = [] if any(s.startswith(SERIES) for s in sets) else [
        f"No run of [benchmarks/tasks.py](../benchmarks/tasks.py) (`{SERIES}`, the series this repository runs) is recorded yet. "
        "The rows below are the figures published before it existed, each with its source."]
    out = [
        "# Benchmark: the same requests with and without the skill",
        "",
        "<!-- generated by benchmarks/page.py from benchmarks/results/*.json; do not edit -->",
        "",
        "Each request is given to a model in an agent loop with one tool (`bash`) and a limit of 20 calls. "
        "With the skill, SKILL.md is in the system prompt and the tools are on disk; without it, the model has "
        "ffmpeg and ffprobe. Every output file is measured (length, frame, streams, loudness, a frame's brightness, "
        "the pitch of the sound); what the model says it did is recorded and never graded. The models are reached "
        "through an API, not run on local hardware.",
        "",
        "Read a difference of one or two correct answers as noise when a cell ran once (`Runs per task` 1). "
        "A figure the source did not state is `not measured`, never a zero.",
        "",
        "## Latest result per model and arm",
    ]
    out += ["", *sets_note] if sets_note else []
    for s in sets:
        group = [d for d in docs if d["task_set"] == s]
        latest = {}
        for d in group:
            key = (tuple(d["models"]), d["arm"])
            if key not in latest or version_key(d) >= version_key(latest[key]):
                latest[key] = d
        rows = sorted(latest.values(), key=lambda d: (len(d["models"]) == 1, d["models"], d["arm"] != "skill"))
        out += ["", f"### {s}", "", TASK_SETS.get(s, f"A subset of {s.split(':')[0]}: {s.split(':', 1)[-1]}") + ".", "", table(rows)]
    out += ["", "## Every recorded result", ""]
    for s in sets:
        group = sorted((d for d in docs if d["task_set"] == s), key=lambda d: (version_key(d), -len(d["models"]), d["arm"] != "skill", d["models"]))
        out += [f"### {s}", "", table(group), ""]
        notes = [f"- {', '.join(d['models'])}, {d['arm']}, {d.get('label') or d['release']}: {d['note']}"
                 + ("".join(f" Per request: {', '.join(f'{k} {v}' for k, v in d['per_task'].items())}.") if d.get("per_task") else "")
                 for d in group if d["note"] or d.get("per_task")]
        if notes:
            out += ["Notes:", "", *notes, ""]
    out += [
        "## Running it",
        "",
        "One command per model and arm; the endpoint and key come from the environment and are never written to a file:",
        "",
        "```",
        "export BENCH_API_URL=https://<provider>/v1/chat/completions BENCH_API_KEY=...",
        "python3 benchmarks/run.py MODEL --arm skill --runs 3",
        "python3 benchmarks/run.py MODEL --arm raw --runs 3",
        "python3 benchmarks/page.py --write",
        "```",
        "",
        "`--dry-run` prints the tasks and the request each would send, with no endpoint and no network. "
        "`--only cut,mute` runs part of the set; `--budget 5` stops starting runs after five dollars. "
        "Each run's transcript is kept under `--out`. The model's commands run in bash, so a run needs Linux or macOS (WSL on Windows); `--dry-run` works anywhere. After a release, the `benchmark` workflow "
        "(Actions, run by hand) does the same on a runner and attaches the results file; committing it updates this page. "
        "The checkers are tested with a known-good and a known-bad output for every task (`tests/test_benchmarks.py`).",
        "",
    ]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render()
    if args.write:
        PAGE.write_text(text, encoding="utf-8")
        print(f"wrote {PAGE.relative_to(ROOT)}")
        return 0
    if PAGE.read_text(encoding="utf-8") != text:
        print(f"{PAGE.relative_to(ROOT)} is not what benchmarks/results gives: run python3 benchmarks/page.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
