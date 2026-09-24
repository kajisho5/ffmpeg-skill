#!/usr/bin/env python3
"""Grade eval 25 runs (TTS segment joins, editor-timeline handoff) on the result documents.

    python3 evals/grade_runs_25.py RUN_DIR [PROMPTS_JSON] [--json]

RUN_DIR/<id>/ is what evals/run_agents_25.sh leaves: transcript.jsonl (claude -p stream-json)
or transcript.txt (any harness's plain log), plus .before/.after file listings. For every
prompt in PROMPTS_JSON (default evals/agent_prompts_25.json):

  expect         every slot ('a|b' = either) appears in a command the agent ran
  grader_expect  every regex matches a command the agent ran
  grader_not     no regex matches the transcript (commands, tool output, report) -- 'Traceback'
                 catches a crashed script; '--on-missing skip' in tt2 catches joining before asking
  result_expect  checked against the LAST --json result document the named tool printed, not the
                 command line: tool=<script stem> selects it, ok=true needs status completed,
                 skipped_names=<file> needs that file in skipped[], names=<file> needs it in
                 skipped[], pending[] or problems[]
  report_expect  substring of the final report
  must_not_write a file that must not appear in .after (a refused/handoff run renders nothing)
  record_only    routing is recorded, verdict 'recorded' instead of pass/fail

A missing run directory is MISSING, never a crash.
"""
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parent


def load_run(d: Path):
    """(commands, tool_outputs, final_report) from a run folder."""
    cmds, outs, final = [], [], ""
    jl = d / "transcript.jsonl"
    if jl.exists():
        for line in jl.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                final = ev.get("result") or final
            content = (ev.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmds.append((c.get("input") or {}).get("command", ""))
                elif c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                    outs.append(body or "")
                elif c.get("type") == "text" and ev.get("type") == "assistant":
                    final = c.get("text") or final
        return cmds, outs, final
    tx = d / "transcript.txt"
    if tx.exists():
        text = tx.read_text(encoding="utf-8", errors="replace")
        cmds = [m.group(1) for m in re.finditer(r"^\$ (.+)$", text, re.M)]
        rep = text.split("\n## Report\n", 1)
        return cmds, [rep[0]], rep[1] if len(rep) > 1 else ""
    return None


def result_docs(outs):
    """Every top-level JSON object printed in tool output (a script's --json document)."""
    docs = []
    dec = json.JSONDecoder()
    for o in outs:
        i = 0
        while True:
            j = o.find("{", i)
            if j < 0:
                break
            try:
                doc, end = dec.raw_decode(o, j)
            except ValueError:
                i = j + 1
                continue
            if isinstance(doc, dict) and "status" in doc:
                docs.append(doc)
            i = end
    return docs


def _names(doc, *keys):
    return [Path(str(x.get("path", x) if isinstance(x, dict) else x)).name
            for k in keys for x in (doc.get(k) or [])]


def grade(p, d: Path):
    run = load_run(d)
    if run is None:
        return {"id": p["id"], "verdict": "MISSING"}
    cmds, outs, final = run
    cmdtext = "\n".join(cmds)
    alltext = "\n".join([cmdtext, *outs, final])
    fails = []
    for slot in p.get("expect", []):
        if not any(alt in cmdtext for alt in slot.split("|")):
            fails.append("expect %r not in any command" % slot)
    for rx in p.get("grader_expect", []):
        if not re.search(rx, cmdtext):
            fails.append("grader_expect %r" % rx)
    for rx in p.get("grader_not", []):
        if re.search(re.escape(rx) if rx.startswith("--") else rx, alltext if rx == "Traceback" else cmdtext):
            fails.append("grader_not %r matched" % rx)
    re_exp = p.get("result_expect")
    doc = None
    if re_exp:
        tool = re_exp.get("tool")
        tool_outs = [o for c, o in zip(cmds, outs) if tool + ".py" in c and "--json" in c] if len(cmds) == len(outs) else outs
        docs = result_docs(tool_outs)
        doc = docs[-1] if docs else None
        if doc is None:
            fails.append("no %s --json result document" % tool)
        else:
            if re_exp.get("ok") and doc.get("status") != "completed":
                fails.append("result status %r" % doc.get("status"))
            if "skipped_names" in re_exp and re_exp["skipped_names"] not in _names(doc, "skipped"):
                fails.append("%s not in skipped[]" % re_exp["skipped_names"])
            if "names" in re_exp and re_exp["names"] not in _names(doc, "skipped", "pending", "problems"):
                fails.append("%s not in skipped/pending/problems" % re_exp["names"])
    if p.get("report_expect") and p["report_expect"] not in final:
        fails.append("report does not name %r" % p["report_expect"])
    after = d / ".after"
    if p.get("must_not_write") and after.exists() and p["must_not_write"] in after.read_text().split():
        fails.append("%s was written" % p["must_not_write"])
    verdict = "recorded" if p.get("record_only") else ("pass" if not fails else "fail")
    return {"id": p["id"], "verdict": verdict, "failures": fails,
            "commands": [c for c in cmds if ".py" in c],
            "result_status": doc.get("status") if doc else None}


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if not args:
        raise SystemExit(__doc__)
    root = Path(args[0])
    prompts = json.loads(Path(args[1] if len(args) > 1 else W / "agent_prompts_25.json").read_text(encoding="utf-8"))
    rows = [grade(p, root / p["id"]) for p in prompts]
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            print("%-4s %-8s %s" % (r["id"], r["verdict"], "; ".join(r.get("failures") or [])))
    return 0 if all(r["verdict"] in ("pass", "recorded") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
