#!/usr/bin/env python3
"""Grade iteration runs: expected scripts present in run.md, command count, report shape."""
import json, re, sys
from pathlib import Path
W = Path(__file__).resolve().parent
prompts = {p["id"]: p for p in json.loads((W / "prompts.json").read_text())}
it = W / sys.argv[1] if len(sys.argv) > 1 else W / "iteration-1"
rows = []
for d in sorted(it.iterdir()):
    if not d.is_dir() or d.name not in prompts:
        continue
    for variant in ("with_skill", "old_skill"):
        run = d / variant / "outputs" / "run.md"
        if not run.exists():
            rows.append((d.name, variant, None, 0, [], 0, False, False))
            continue
        text = run.read_text(errors="replace")
        cmds = [l for l in text.splitlines() if re.search(r"\b\w+\.py\b", l) and ("python" in l or l.strip().startswith("$"))]
        used = set(re.findall(r"\b([a-z_]+)\.py\b", text))
        exp = prompts[d.name]["expect"]
        hits = [any(alt.replace(".py", "") in used for alt in e.split("|")) for e in exp]
        report_ok = bool(re.search(r"(?im)^\s*(\*\*)?done", text)) and ("LUFS" in text or "fps" in text)
        look_ok = "look" in used
        rows.append((d.name, variant, sum(hits) / len(exp), len(cmds), [e for e, h in zip(exp, hits) if not h], len(used), report_ok, look_ok))
print(f"{'eval':22s} {'variant':10s} {'routing':8s} {'cmds':5s} {'scripts':7s} {'report':6s} {'look':4s} missing")
for name, variant, score, ncmd, missing, nscripts, rep, look in rows:
    print(f"{name:22s} {variant:10s} {('%.0f%%' % (100*score)) if score is not None else 'n/a':8s} {ncmd:<5d} {nscripts:<7d} {'yes' if rep else 'no':6s} {'yes' if look else 'no':4s} {', '.join(missing)}")
for variant in ("with_skill", "old_skill"):
    sc = [r[2] for r in rows if r[1] == variant and r[2] is not None]
    cm = [r[3] for r in rows if r[1] == variant and r[2] is not None]
    if sc:
        print(f"{variant}: routing {100*sum(sc)/len(sc):.0f}%, mean commands {sum(cm)/len(cm):.1f}, report format {sum(1 for r in rows if r[1]==variant and r[6])}/{len(sc)}, visual check {sum(1 for r in rows if r[1]==variant and r[7])}/{len(sc)}")
