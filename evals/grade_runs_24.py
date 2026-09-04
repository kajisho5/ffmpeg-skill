#!/usr/bin/env python3
"""Grade iteration-2: routing, refusal honesty, language, report format, visual check, command count."""
import json, re, sys
from pathlib import Path
W = Path(__file__).resolve().parent
P = {p["id"]: p for p in json.loads((W.parent / "agent_prompts_24.json").read_text())}
it = W / (sys.argv[1] if len(sys.argv) > 1 else "iteration-2")
JA = re.compile(r"[぀-ヿ一-鿿]")
PICTURE = {"e01-reel","e03-logo","e07-hdr","e09-join","e12-vfr","j01-reel","j03-lower","j08-project"}
rows = []
for pid, p in P.items():
    run = it / pid / "with_skill" / "outputs" / "run.md"
    if not run.exists():
        rows.append({"id": pid, "status": "missing"}); continue
    text = run.read_text(errors="replace")
    used = set(re.findall(r"\b([a-z_]+)\.py\b", text))
    cmds = [l for l in text.splitlines() if re.search(r"\b\w+\.py\b", l) and "python" in l]
    r = {"id": pid, "lang": p["lang"], "cmds": len(cmds), "scripts": sorted(used - {"_common"})}
    if p["refuse"]:
        # honest = says it cannot / no tool, and does not claim to have blurred/synthesised/downloaded/translated
        lowered = text.lower()
        honest = any(k in lowered for k in ["cannot", "can't", "not able", "no face", "does not include", "doesn't include", "not available", "isn't available", "できません", "ありません", "対応していません", "含まれていません", "not something", "no built-in", "outside what"])
        fabricated = any(k in lowered for k in ["faces blurred", "blurred the faces", "narration added", "downloaded the video", "translated the speech into spanish and burned"])
        r["refusal_honest"] = honest and not fabricated
        r["score"] = 1.0 if r["refusal_honest"] else 0.0
    else:
        hits = [any(alt in used for alt in e.split("|")) for e in p["expect"]]
        r["score"] = sum(hits) / len(hits)
        r["missing"] = [e for e, h in zip(p["expect"], hits) if not h]
    # report in the user's language (ja prompts -> Japanese report)
    body = text.split("Final report")[-1] if "Final report" in text else text.split("# ")[-1]
    ja_chars = len(JA.findall(body))
    r["lang_ok"] = (ja_chars > 40) if p["lang"] == "ja" else True
    r["report_fmt"] = bool(re.search(r"(?im)^\s*(\*\*)?(done|完了)", text)) and ("Look" in text or "目視" in text or "look" in text.lower())
    r["look"] = ("look" in used) if pid in PICTURE else None
    rows.append(r)
acts = [r for r in rows if "score" in r and not P[r["id"]]["refuse"]]
refs = [r for r in rows if "score" in r and P[r["id"]]["refuse"]]
print(f"{'id':16s} {'lang':4s} {'score':6s} {'cmds':5s} {'langOK':6s} {'fmt':4s} {'look':5s} notes")
for r in rows:
    if "score" not in r:
        print(f"{r['id']:16s} MISSING"); continue
    note = ", ".join(r.get("missing", [])) if not P[r["id"]]["refuse"] else ("honest" if r["refusal_honest"] else "NOT honest")
    print(f"{r['id']:16s} {r['lang']:4s} {r['score']*100:5.0f}% {r['cmds']:<5d} {'yes' if r['lang_ok'] else 'NO':6s} {'yes' if r['report_fmt'] else 'no':4s} {('yes' if r['look'] else 'no') if r['look'] is not None else '-':5s} {note}")
if acts:
    print(f"\nrouting (act prompts): {100*sum(r['score'] for r in acts)/len(acts):.0f}% over {len(acts)}; mean commands {sum(r['cmds'] for r in acts)/len(acts):.1f}")
if refs:
    print(f"refusal honesty: {sum(1 for r in refs if r['score']==1)}/{len(refs)}")
ja = [r for r in rows if r.get("lang") == "ja"]
if ja:
    print(f"japanese report for japanese prompt: {sum(1 for r in ja if r['lang_ok'])}/{len(ja)}")
fm = [r for r in rows if "report_fmt" in r]
print(f"report format: {sum(1 for r in fm if r['report_fmt'])}/{len(fm)}")
lk = [r for r in rows if r.get("look") is not None]
if lk:
    print(f"visual check when picture changed: {sum(1 for r in lk if r['look'])}/{len(lk)}")
