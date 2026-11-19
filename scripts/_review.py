#!/usr/bin/env python3
"""Build a review page for a render project: the plan, the result, and fields to re-edit it.

    python3 scripts/_review.py project.json [--result render.json] [-o project.review]
    npx ffmpeg-skill review project.json [--result render.json]

Standalone use only (#633): this is not one of the contract's tools and the MCP server does not
list it, so a caller that owns the review (Velisa) never reaches it. It writes a folder with an
index.html and the stills it shows; the page needs no network and runs nothing. "Save project"
in the page writes the edited project JSON; rendering it again is `render.py` as usual.

Plan: each clip's stills at its in point, middle and out point, the frame, captions, loudness and
export settings, and the stages of `render.py --dry-run --json`. Result (with --result, the
`render.py --json` document of a run): status, verified, the output's measured duration, size,
frame rate and sound, every verification step that failed, the check rows, and stills of the
output. A still that ffmpeg could not write is left out and says so; nothing is guessed.
"""
import argparse
import html
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common.runner import found_exe  # noqa: E402
from _common.decision import parse_time  # noqa: E402


def still(src: str, at: float, out: Path) -> bool:
    """One 320 px wide JPEG of `src` at `at` seconds; False when ffmpeg could not write it."""
    proc = subprocess.run([found_exe("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(at, 0):.3f}", "-i", src, "-frames:v", "1",
                           "-vf", "scale=320:-2", "-q:v", "4", str(out)], capture_output=True)
    return proc.returncode == 0 and out.is_file() and out.stat().st_size > 0


def length(src: str) -> "float | None":
    proc = subprocess.run([found_exe("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                          capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def seconds(value, fps: float = 30.0) -> "float | None":
    if value is None:
        return None
    try:
        return float(parse_time(str(value), fps))
    except (ValueError, TypeError):
        return None


def figure(folder: Path, name: str, src: str, at: "float | None", label: str) -> str:
    if at is None or not still(src, at, folder / name):
        return f'<figure class="miss"><div>no still</div><figcaption>{html.escape(label)}</figcaption></figure>'
    return f'<figure><img src="{name}" alt=""><figcaption>{html.escape(label)}</figcaption></figure>'


def plan_section(project: dict, base: Path, folder: Path) -> str:
    rows = []
    for i, clip in enumerate(project.get("clips") or []):
        src = str(clip.get("src", ""))
        path = src if os.path.isabs(src) else str(base / src)
        total = length(path)
        start = seconds(clip.get("in")) or 0.0
        end = seconds(clip.get("out"))
        end = end if end is not None else total
        figs = "" if end is None else "".join(figure(folder, f"clip{i}_{k}.jpg", path, t, lab) for k, (t, lab) in enumerate(
            ((start, f"in {start:.2f} s"), ((start + end) / 2, "middle"), (max(end - 0.05, start), f"out {end:.2f} s"))))
        rows.append(f'''<div class="clip" data-i="{i}"><h3>Clip {i + 1} <span>{html.escape(src)}</span></h3><div class="row">{figs}</div>
<div class="fields"><label>in <input data-k="in" value="{html.escape(str(clip.get("in", "")))}"></label>
<label>out <input data-k="out" value="{html.escape(str(clip.get("out", "")))}"></label>
<label>speed <input data-k="speed" value="{html.escape(str(clip.get("speed", "")))}"></label></div></div>''')
    frame = project.get("frame") or {}
    caps = project.get("captions") or {}
    loud = project.get("loudness") or {}
    text = caps.get("text") if isinstance(caps.get("text"), str) and not str(caps.get("text")).startswith("$") else ""
    settings = f'''<div class="fields wide"><label>aspect <input id="aspect" value="{html.escape(str(frame.get("aspect", "")))}"></label>
<label>fit <select id="fit">{"".join(f'<option{" selected" if frame.get("fit") == o else ""}>{o}</option>' for o in ("", "pad", "crop", "blur"))}</select></label>
<label>loudness LUFS <input id="lufs" value="{html.escape(str(loud.get("lufs", "")))}"></label>
<label>export preset <input id="preset" value="{html.escape(str((project.get("export") or {}).get("preset", "")))}"></label></div>
<label class="block">captions text <textarea id="captions">{html.escape(text)}</textarea></label>'''
    return "".join(rows) + settings


def result_section(result: dict, folder: Path) -> str:
    probe = result.get("probe") or {}
    video, audio = probe.get("video") or {}, probe.get("audio") or {}
    facts = [("status", result.get("status")), ("verified", result.get("verified")),
             ("duration", f'{probe["duration"]:.3f} s' if probe.get("duration") is not None else None),
             ("size", f'{video.get("width")}×{video.get("height")}' if video.get("width") else None),
             ("frame rate", f'{video.get("fps"):g} fps' if video.get("fps") else None),
             ("sound", f'{audio.get("codec")} {audio.get("channels")} ch' if audio else "none")]
    out = "".join(f'<div class="fact"><b>{html.escape(k)}</b><span>{html.escape("not measured" if v is None else str(v))}</span></div>'
                  for k, v in facts)
    failed = [s for s in result.get("verification") or [] if s.get("ok") is False]
    steps = "".join(f'<li>{html.escape(str(s.get("stage", "")))} {html.escape(str(s.get("step")))}: expected '
                    f'{html.escape(json.dumps(s.get("expected")))}, measured {html.escape(json.dumps(s.get("measured")))}</li>' for s in failed)
    check = result.get("check") or {}
    rows = "".join(f'<li class="{html.escape(str(r.get("verdict", "")).lower())}">{html.escape(str(r.get("verdict")))} '
                   f'{html.escape(str(r.get("name") or r.get("check")))}: {html.escape(str(r.get("detail") or r.get("measured") or ""))}</li>'
                   for r in check.get("checks") or [])
    sheet = ""
    path, dur = result.get("output"), probe.get("duration")
    if path and dur and os.path.isfile(path):
        sheet = "".join(figure(folder, f"out_{k}.jpg", path, dur * (k + 0.5) / 6, f"{dur * (k + 0.5) / 6:.1f} s") for k in range(6))
    return (f'<div class="facts">{out}</div>' + (f'<h3>Failed steps</h3><ul>{steps}</ul>' if steps else "")
            + (f'<h3>Check</h3><ul class="check">{rows}</ul>' if rows else "") + (f'<div class="row">{sheet}</div>' if sheet else ""))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review: {title}</title><style>
:root{{--bg:#f6f5f1;--fg:#16171a;--mut:#5d6069;--line:#dcd9d0;--ok:#0f8a46;--bad:#c2341f;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111215;--fg:#eceef2;--mut:#9aa0aa;--line:#2b2e35;--ok:#2fd27c;--bad:#ff7a66;--card:#1a1c21}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}} main{{max-width:1100px;margin:auto;padding:24px 16px 80px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{margin:36px 0 12px;font-size:19px}} h3{{font-size:15px;margin:18px 0 8px}} h3 span{{color:var(--mut);font-weight:400}}
.clip,.facts,.cmd{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}}
.row{{display:flex;gap:10px;overflow-x:auto}} figure{{margin:0;flex:none}} img{{width:200px;border-radius:8px;display:block}}
figure.miss div{{width:200px;height:112px;border:1px dashed var(--line);border-radius:8px;display:grid;place-items:center;color:var(--mut)}}
figcaption{{color:var(--mut);font-size:12px}} .fields{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}} label{{color:var(--mut);font-size:13px}}
input,select,textarea{{display:block;font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;width:9em}}
textarea{{width:100%;min-height:90px}} .block{{display:block;margin-top:12px}} .facts{{display:flex;gap:18px;flex-wrap:wrap}}
.fact b{{display:block;color:var(--mut);font-size:12px;font-weight:600}} .check .fail{{color:var(--bad)}} .check .pass{{color:var(--ok)}}
button{{font:inherit;background:var(--fg);color:var(--bg);border:0;border-radius:10px;padding:10px 16px;cursor:pointer}}
code{{display:block;white-space:pre-wrap;word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px}}
</style></head><body><main><h1>{title}</h1><p style="color:var(--mut)">ffmpeg-skill review page. It runs nothing: save the project and render it again.</p>
<h2>Plan</h2><p style="color:var(--mut)">stages: {stages}</p>{plan}
<h2>Result</h2>{result}
<h2>Re-edit</h2><div class="cmd"><button id="save">Save project</button><code id="run"></code><code id="ask"></code></div>
<script id="project" type="application/json">{project_json}</script><script>
const P=JSON.parse(document.getElementById('project').textContent);const name={name};
function edited(){{const p=JSON.parse(JSON.stringify(P));
document.querySelectorAll('.clip').forEach(c=>{{const i=+c.dataset.i;c.querySelectorAll('input').forEach(f=>{{const k=f.dataset.k,v=f.value.trim();
if(v===''){{delete p.clips[i][k];}}else{{p.clips[i][k]=(k==='speed'||/^\\d+(\\.\\d+)?$/.test(v))?Number(v):v;}}}})}});
const set=(o,k,v,num)=>{{if(v===''){{if(p[o])delete p[o][k];}}else{{p[o]=p[o]||{{}};p[o][k]=num?Number(v):v;}}}};
set('frame','aspect',document.getElementById('aspect').value.trim());set('frame','fit',document.getElementById('fit').value);
set('loudness','lufs',document.getElementById('lufs').value.trim(),true);set('export','preset',document.getElementById('preset').value.trim());
const t=document.getElementById('captions').value;if(t.trim()){{p.captions=p.captions||{{}};p.captions.text=t;}}return p;}}
function show(){{document.getElementById('run').textContent='python3 scripts/render.py '+name+' --overwrite --json';
document.getElementById('ask').textContent='Render '+name+' again with the project I saved, then report it.';}}
document.getElementById('save').onclick=()=>{{const b=new Blob([JSON.stringify(edited(),null,2)+'\\n'],{{type:'application/json'}});
const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click();show();}};show();
</script></main></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="the render.py project JSON")
    ap.add_argument("--result", help="the render.py --json document of a run of this project")
    ap.add_argument("-o", "--output", help="the folder to write (default: <project>.review next to the project)")
    a = ap.parse_args(argv)
    proj_path = Path(a.project).resolve()
    try:
        project = json.loads(proj_path.read_text(encoding="utf-8"))
        result = json.loads(Path(a.result).read_text(encoding="utf-8")) if a.result else None
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    folder = Path(a.output).resolve() if a.output else proj_path.with_suffix(".review")
    folder.mkdir(parents=True, exist_ok=True)
    # a dry run writes nothing, so --overwrite only keeps an output from an earlier run from refusing it
    dry = subprocess.run([sys.executable, str(HERE / "render.py"), str(proj_path), "--dry-run", "--overwrite", "--json"],
                         capture_output=True, text=True, cwd=str(proj_path.parent))
    try:
        doc = json.loads(dry.stdout)
        stages = (" → ".join(doc.get("stages") or []) if doc.get("status") == "completed"
                  else "the dry run failed: " + str((doc.get("error") or {}).get("message", "no message")))
    except ValueError:
        stages = "the dry run did not complete: " + (dry.stderr.strip().splitlines() or ["no message"])[-1]
    page = PAGE.format(title=html.escape(proj_path.name), stages=html.escape(stages),
                       plan=plan_section(project, proj_path.parent, folder),
                       result=result_section(result, folder) if result else '<p style="color:var(--mut)">Not rendered yet: '
                       'give --result with a render.py --json document to see what was measured.</p>',
                       project_json=json.dumps(project).replace("</", "<\\/"), name=json.dumps(proj_path.name))
    (folder / "index.html").write_text(page, encoding="utf-8")
    print(folder / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
