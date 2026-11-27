#!/usr/bin/env python3
"""Run the with/without-skill benchmark (#677) against one model and write one results file.

    python3 benchmarks/run.py MODEL --arm skill|raw --runs N [--only cut,mute] [--dry-run]

MODEL is the model id the endpoint takes. The endpoint is any OpenAI-compatible chat-completions
URL with tool calls; it is read from the environment and never written anywhere:

    BENCH_API_URL     e.g. https://<provider>/v1/chat/completions
    BENCH_API_KEY     sent as `Authorization: Bearer ...`
    BENCH_PRICE_IN / BENCH_PRICE_OUT   optional, dollars per million prompt / completion tokens,
                      for a cost when the response's `usage` carries none

Each run is an agent loop with one tool (`bash`) and a limit of --limit calls (20), in a fresh
folder holding the task's inputs (made with ffmpeg, benchmarks/tasks.py). The `skill` arm puts
SKILL.md in the system prompt and the files `npm` ships under ./ffmpeg-skill; the `raw` arm has
ffmpeg and ffprobe only. The output is graded by measurement (benchmarks/tasks.py), never by
what the model says. --user NAME runs every command as that user (`runuser`, needs root).

Writes benchmarks/results/<date>_<release>_<model>_<arm>.json (validated, see
benchmarks/page.py) and, under --out, transcript.json per run. Regenerate the page with
`python3 benchmarks/page.py --write`.

--dry-run needs no endpoint and no network: it prints each task, the ffmpeg commands that make
its inputs, and the request body the first call would send.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import page  # noqa: E402
import tasks  # noqa: E402

BASH_TOOL = {"type": "function", "function": {
    "name": "bash", "description": "Run one bash command in the working folder; returns its exit code and output.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}
COMMON = ("You are in a folder that holds the files the request names. Do the request with the bash tool. "
          "When it is done, or cannot be done, answer in a few sentences: what you wrote and what you measured.")


def release():
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def shipped_files():
    """The files `npm pack` ships (package.json `files`), the copy a user installs."""
    out = []
    for entry in json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["files"]:
        out += [p for p in ROOT.glob(entry) if p.is_file()] + [p for d in ROOT.glob(entry) if d.is_dir() for p in d.rglob("*") if p.is_file()]
    return sorted({p for p in out if "__pycache__" not in p.parts})


def system_prompt(arm):
    if arm == "raw":
        return COMMON + " ffmpeg and ffprobe are installed."
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    return (COMMON + " The ffmpeg-skill tools are installed in ./ffmpeg-skill (scripts in ./ffmpeg-skill/scripts); "
            "ffmpeg and ffprobe are installed too. The skill's SKILL.md follows.\n\n" + skill)


def request_body(model, messages):
    return {"model": model, "messages": messages, "tools": [BASH_TOOL], "max_tokens": 4096}


def post(url, key, body, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == 2:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                raise RuntimeError(f"no answer from the endpoint: {e}") from None
        time.sleep(5 * (attempt + 1))


def run_command(command, workdir, user, timeout=600):
    argv = ["bash", "-c", command]
    if user:
        argv = ["runuser", "-u", user, "--", *argv]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workdir), "LANG": "C.UTF-8", "TMPDIR": str(workdir)}
    try:
        proc = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        text, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        text, code = f"(stopped after {timeout} s)", 124
    return f"exit code {code}\n" + (text if len(text) <= 6000 else "...(cut)...\n" + text[-6000:])


def cost_of(usage):
    if not usage:
        return None
    if isinstance(usage.get("cost"), (int, float)):
        return float(usage["cost"])
    pin, pout = os.environ.get("BENCH_PRICE_IN"), os.environ.get("BENCH_PRICE_OUT")
    if pin and pout:
        return (usage.get("prompt_tokens", 0) * float(pin) + usage.get("completion_tokens", 0) * float(pout)) / 1e6
    return None


def agent_run(task, arm, model, url, key, limit, user, keep):
    """One request, start to finish: (row for the results file, transcript)."""
    workdir = Path(tempfile.mkdtemp(prefix=f"bench-{task['id']}-"))
    try:
        tasks.make_fixtures(task["inputs"], workdir)
        if arm == "skill":
            for f in shipped_files():
                dest = workdir / "ffmpeg-skill" / f.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
        if user:
            subprocess.run(["chown", "-R", user, str(workdir)], check=True)
        messages = [{"role": "system", "content": system_prompt(arm)}, {"role": "user", "content": task["request"]}]
        calls, cost, stopped, claimed = 0, 0.0, "answered", ""
        costed = True
        for _ in range(limit * 3):  # a model that answers with neither text nor a call still ends
            try:
                answer = post(url, key, request_body(model, messages))
            except RuntimeError as e:
                stopped, claimed = "error", str(e)
                break
            c = cost_of(answer.get("usage"))
            costed = costed and c is not None
            cost += c or 0.0
            msg = (answer.get("choices") or [{}])[0].get("message") or {}
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
            if not msg.get("tool_calls"):
                claimed = msg.get("content") or ""
                break
            for call in msg["tool_calls"]:
                calls += 1
                if calls > limit:
                    stopped = "call_limit"
                    break
                try:
                    command = json.loads(call["function"].get("arguments") or "{}").get("command", "")
                except json.JSONDecodeError:
                    command = ""
                result = run_command(command, workdir, user) if command else "no command given"
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
            if stopped == "call_limit":
                calls = limit
                break
        ok, detail = tasks.grade(task, workdir)
        row = {"task": task["id"], "ok": ok, "detail": detail, "calls": calls, "cost_usd": round(cost, 5) if costed else None,
               "stopped": stopped, "claimed": claimed[:600]}
        return row, messages
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def summarize(model, arm, rows, runs, limit, selected):
    by_run = [[r for r in rows if r["run"] == i] for i in range(runs)]
    correct = [sum(r["ok"] for r in rs) for rs in by_run if rs]
    calls = [statistics.mean(r["calls"] for r in rs) for rs in by_run if rs]
    costs = [r["cost_usd"] for r in rows]
    ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    return {
        "schema": page.SCHEMA, "date": datetime.date.today().isoformat(), "release": release(), "arm": arm,
        "models": [model], "task_set": tasks.TASK_SET if len(selected) == len(tasks.TASKS) else tasks.TASK_SET + ":" + ",".join(t["id"] for t in selected),
        "tasks": len(selected), "runs_per_task": runs, "requests": len(rows), "call_limit": limit,
        "correct": sum(r["ok"] for r in rows), "correct_per_run": correct,
        "calls_per_request": round(statistics.mean(r["calls"] for r in rows), 2) if rows else None,
        "calls_per_request_range": [round(min(calls), 2), round(max(calls), 2)] if calls else None,
        "cost_usd": round(sum(costs), 4) if rows and None not in costs else None,
        "ffmpeg": ffmpeg, "tasks_sha256": hashlib.sha256((HERE / "tasks.py").read_bytes()).hexdigest()[:16],
        "source": "benchmarks/run.py", "note": "", "runs": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", help="the model id the endpoint takes")
    ap.add_argument("--arm", choices=("skill", "raw"), required=True)
    ap.add_argument("--runs", type=int, default=3, help="runs per task (3: a difference of one answer is not a change)")
    ap.add_argument("--only", default="", help="comma-separated task ids (default: all 24)")
    ap.add_argument("--limit", type=int, default=20, help="tool calls per run")
    ap.add_argument("--budget", type=float, default=None, help="stop starting runs once this many dollars are spent")
    ap.add_argument("--user", default=None, help="run the model's commands as this unprivileged user (needs root)")
    ap.add_argument("--out", default=None, help="folder for transcripts (default: a new temp folder)")
    ap.add_argument("--results", default=str(HERE / "results"), help="folder the results file is written to")
    ap.add_argument("--keep", action="store_true", help="keep each run's working folder")
    ap.add_argument("--dry-run", action="store_true", help="print the tasks and the requests; call nothing")
    args = ap.parse_args(argv)
    ids = [i for i in args.only.split(",") if i]
    unknown = [i for i in ids if i not in tasks.BY_ID]
    if unknown:
        ap.error(f"unknown task id(s): {', '.join(unknown)}; the ids are {', '.join(tasks.BY_ID)}")
    if args.runs < 1 or args.limit < 1:
        ap.error("--runs and --limit take a positive number")
    selected = [tasks.BY_ID[i] for i in ids] if ids else tasks.TASKS
    if args.dry_run:
        url = os.environ.get("BENCH_API_URL") or "(BENCH_API_URL)"
        for t in selected:
            body = request_body(args.model, [{"role": "system", "content": system_prompt(args.arm)}, {"role": "user", "content": t["request"]}])
            sys_text = body["messages"][0]["content"]
            body["messages"][0]["content"] = sys_text[:160] + f"... ({len(sys_text)} characters{', SKILL.md included' if args.arm == 'skill' else ''})" if len(sys_text) > 200 else sys_text
            print(json.dumps({"task": t["id"], "request": t["request"], "output": t["output"],
                              "inputs": [f"write {n}" if n in tasks.TEXT_FIXTURES else shlex.join(tasks.fixture_command(n, "WORK")) for n in t["inputs"]],
                              "post": url, "body": body, "runs": args.runs, "call_limit": args.limit}, ensure_ascii=False))
        print(f"{len(selected)} task(s) x {args.runs} run(s), arm {args.arm}: {len(selected) * args.runs} requests would be sent", file=sys.stderr)
        return 0
    url, key = os.environ.get("BENCH_API_URL"), os.environ.get("BENCH_API_KEY")
    if not url or not key:
        print("run.py: set BENCH_API_URL and BENCH_API_KEY (or use --dry-run)", file=sys.stderr)
        return 2
    out = Path(args.out or tempfile.mkdtemp(prefix="bench-transcripts-"))
    rows, spent = [], 0.0
    for run in range(args.runs):
        for t in selected:
            if args.budget is not None and spent >= args.budget:
                print(f"run.py: stopped at the budget (${spent:.2f} of ${args.budget:.2f})", file=sys.stderr)
                break
            row, transcript = agent_run(t, args.arm, args.model, url, key, args.limit, args.user, args.keep)
            row["run"] = run
            rows.append(row)
            spent += row["cost_usd"] or 0.0
            (out / f"{t['id']}-{run}").mkdir(parents=True, exist_ok=True)
            (out / f"{t['id']}-{run}" / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{t['id']:14} run {run}: {'ok  ' if row['ok'] else 'FAIL'} {row['calls']:2} calls  {row['detail']}", file=sys.stderr)
    if not rows or all(r["stopped"] == "error" for r in rows):
        # an endpoint that never answered measured nothing: no results file, not 0 of N correct
        print("run.py: no run got an answer from the endpoint" + (f" ({rows[0]['claimed']})" if rows else "") + "; nothing written", file=sys.stderr)
        return 1
    doc = summarize(args.model, args.arm, rows, args.runs, args.limit, selected)
    if args.budget is not None and spent >= args.budget:
        doc["note"] = f"stopped at the budget of ${args.budget:.2f}: {len(rows)} of {len(selected) * args.runs} requests ran"
    page.validate(doc)
    slug = re.sub(r"[^a-z0-9.]+", "-", args.model.lower()).strip("-")
    dest = Path(args.results) / f"{doc['date']}_{doc['release']}_{slug}_{args.arm}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{doc['correct']} of {doc['requests']} correct, {doc['calls_per_request']} calls per request; wrote {dest}; transcripts in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
