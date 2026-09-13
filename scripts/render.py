#!/usr/bin/env python3
"""Declarative edits: describe the whole edit in one project.json and render it
in one command. Change a number, re-render. Non-destructive: sources are never
touched, intermediates live in a work directory.

Project format (all keys optional except clips):
{
  "output": "final.mp4",
  "frame": {"aspect": "9:16", "width": 1080, "fps": 30},
  "clips": [
    {"src": "a.mp4", "in": "0:05", "out": "0:20"},
    {"src": "b.mp4", "in": 3, "out": 12, "speed": 1.25},
    {"src": "c.mp4"}
  ],
  "transition": {"type": "fade", "duration": 0.5},
  "silence": {"threshold": -38, "min_silence": 0.8},
  "captions": {"text": "cues.txt", "srt": null, "animate": "pop", "karaoke": true, "font": "Noto Sans CJK JP", "size": 28, "position": "bottom"},
  "brand": "brand.json",
  "graphics": [
    {"template": "title", "title": "Episode 12", "subtitle": "The math of video", "start": 0, "end": 4},
    {"template": "lower-third", "name": "Ada Lovelace", "title": "Analyst", "start": 5, "end": 11}
  ],
  "overlays": [
    {"logo": true},
    {"text": "Episode 12", "position": "bottom", "start": 1, "end": 5, "fade": 0.3, "box": true}
  ],
  "audio": {"voice": "medium", "music": "bed.mp3", "music_volume": -16, "duck": true, "music_fade_out": 2,
            "effects": "sfx.wav", "stems": {"dialogue": 0, "music": -18, "effects": -22}},
  "loudness": {"lufs": -14, "tp": -1},
  "fit": {"duration": 60},
  "export": {"preset": "reels", "normalize": true},   (default for platform presets; false opts out)
  "check": {"platform": "reels"},
  "chapters": "chapters.txt"            (or [{"at": "0:00", "title": "Intro"}, ...])
}

Stages run in this order: clips (cut) → join → silence → fit → captions →
graphics → overlays → audio → loudness → export → chapters → check. Missing stages are
skipped. "brand" points caption/graphics/overlay at a brand.json (fonts,
colours, logo, safe margin); {"logo": true} in overlays places the brand logo.

"check" mirrors check.py's own exit code: a delivery-spec FAIL (or check.py
itself failing to run) exits 1, same as running check.py directly would --
the render is not silently reported as successful just because every stage
up to it completed. The output file is still written and `--json`'s
`check` field still carries the full row-by-row result either way.

Examples:
  python3 render.py --init project.json          # write a commented starter project
  python3 render.py project.json                 # render
  python3 render.py project.json --dry-run       # show every command without rendering
  python3 render.py project.json --fast          # preview quality
"""
import argparse
import difflib
import re
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from export import PRESETS, PLATFORM_OF
from _platforms import PLATFORMS, caption_defaults, resolve as resolve_platform
from _common import STATE, add_common, apply_common, child_args, die, emit, info, probe, run_tool, place_output, refuse_output_is_input, fingerprint, PLAN_VERSION

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE.parent / "templates"
# The placeholders a delivery template carries; a block whose placeholder has no value
# (no --logo, no --title, no cues) is dropped from the filled project rather than rendered empty.
PLACEHOLDERS = ("$INPUT", "$OUTPUT", "$CUES", "$SRT", "$LOGO", "$TITLE", "$BRAND", "$CHAPTERS", "$IMAGE")
# Intermediates follow the delivery's own media kind: an audio-only project (the podcast
# template) must not carry its stages through .mp4 containers.
AUDIO_EXT = frozenset({".wav", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".opus"})

TEMPLATE = {
    "output": "final.mp4",
    "frame": {"aspect": "16:9", "width": 1920, "fps": 30},
    "clips": [{"src": "REPLACE_ME.mp4", "in": "0:00", "out": "0:30"}],
    "transition": {"type": "fade", "duration": 0.5},
    "silence": None,
    "brand": None,
    "captions": None,
    "graphics": [],
    "overlays": [],
    "audio": None,
    "loudness": {"lufs": -14, "tp": -1},
    "fit": None,
    "export": {"preset": "youtube", "normalize": True},
    "chapters": None,
    "check": {"platform": "youtube"},
}


# Every key render.py reads, per object. Anything else is a refusal rather than a silent no-op:
# a clip "start"/"end" (the spelling titles, graphics and overlays use) rendered the whole clip
# untrimmed, and a mistyped stage name dropped the stage -- both reported as a success (review 9).
OBJECT_KEYS: Dict[str, frozenset] = {
    "project": frozenset({"output", "frame", "clips", "transition", "silence", "brand", "captions",
                          "graphics", "overlays", "audio", "loudness", "fit", "export", "check", "chapters",
                          "audiogram", "template"}),
    "clips[]": frozenset({"src", "in", "out", "speed"}),
    "frame": frozenset({"aspect", "width", "height", "fps", "fit"}),
    "transition": frozenset({"type", "duration"}),
    "silence": frozenset({"threshold", "min_silence", "margin"}),
    # 1.16: the picture an audio-only source gets before the rest of the chain can work on it
    "audiogram": frozenset({"image", "image_fit", "style", "position", "vis_height", "opacity",
                            "platform", "title", "color", "background", "width", "height", "fps"}),
    "captions": frozenset({"text", "srt", "ass", "font", "size", "color", "position", "margin",
                           "animate", "highlight_color", "outline", "karaoke", "bold", "box",
                           "lang", "offset", "max_lines", "min_duration"}),
    # the 1.14 social templates (sticker/hook/meme) take their own text and timing, so a
    # graphics[] entry can carry them too -- a template that only works from the CLI is not
    # "usable inside a render.py graphics[] entry" (review 12)
    "graphics[]": frozenset({"template", "name", "title", "subtitle", "start", "end", "position",
                             "from", "scale", "primary", "text_color", "lang",
                             "text", "top", "bottom", "duration", "margin", "platform"}),
    "overlays[]": frozenset({"logo", "image", "text", "position", "start", "end", "fade", "opacity",
                             "scale", "font_size", "font", "font_file", "margin", "box", "platform"}),
    "audio": frozenset({"music", "replace", "music_volume", "fade_in", "fade_out", "music_fade_out",
                        "gain", "duck_amount", "duck_threshold", "duck_attack", "duck_release",
                        "voice", "denoise", "duck", "music_loop", "stereo", "mono", "downmix",
                        "stereo_widen", "effects", "effects_volume", "stems"}),
    "audio.stems": frozenset({"dialogue", "music", "effects"}),
    "chapters[]": frozenset({"at", "title"}),
    "loudness": frozenset({"lufs", "tp"}),
    "fit": frozenset({"duration", "method", "aspect", "fit", "width", "height", "fps", "smooth"}),
    "export": frozenset({"preset", "fit", "crf", "normalize"}),
    "check": frozenset({"platform"}),
}
# Typos difflib cannot see: a clip is trimmed with in/out, not the start/end that time a title.
NEAR_KEYS: Dict[str, Dict[str, str]] = {"clips[]": {"start": "in", "end": "out", "from": "in", "to": "out"},
                                        "audio.stems": {"voice": "dialogue", "speech": "dialogue", "sfx": "effects", "bed": "music"},
                                        "chapters[]": {"start": "at", "time": "at", "name": "title"}}


def template_names() -> List[str]:
    """Every templates/<name>.json that ships with the skill."""
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.json"))


def load_template(name: str) -> Dict[str, Any]:
    path = TEMPLATE_DIR / f"{name}.json"
    if not path.is_file():
        die(f"unknown template {name!r}", hint="templates: " + ", ".join(template_names()) + " (or 'all')")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read template {path}: {exc}")
    return {}


def fill_template(node: Any, values: Dict[str, Any]) -> "tuple":
    """Substitute the $PLACEHOLDERS a template carries; return (filled, complete).

    complete=False means a placeholder in this node had no value, and the caller drops the
    whole block: a template's overlay entry is `{"image": "$LOGO"}`, so a run without --logo
    must lose the overlay entirely rather than render an overlay of nothing."""
    if isinstance(node, str):
        if node in PLACEHOLDERS:
            value = values.get(node)
            return value, value is not None
        return node, True
    if isinstance(node, list):
        kept = []
        for item in node:
            filled, ok = fill_template(item, values)
            if ok:
                kept.append(filled)
        return kept, True
    if isinstance(node, dict):
        out: Dict[str, Any] = {}
        complete = True
        for key, value in node.items():
            filled, ok = fill_template(value, values)
            if not ok:
                complete = False
                continue
            out[key] = filled
        return out, complete
    return node, True


def template_project(name: str, args) -> Dict[str, Any]:
    """One template plus the run's arguments as a ready-to-render project."""
    tpl = load_template(name)
    dest = str((tpl.get("check") or {}).get("platform") or name)
    if args.srt and isinstance(tpl.get("captions"), dict) and "text" in tpl["captions"]:
        cap = {("srt" if k == "text" else k): ("$SRT" if k == "text" else v) for k, v in tpl["captions"].items()}
        tpl["captions"] = cap
    # The caption block's size and margin are the table's, not a literal restated in the JSON:
    # change a destination's safe zone in scripts/_platforms.py and every template follows.
    if isinstance(tpl.get("captions"), dict) and dest in PLATFORMS and PLATFORMS[dest].get("frame"):
        defaults = caption_defaults(dest)
        tpl["captions"]["size"] = defaults["size"]
        tpl["captions"]["margin"] = defaults["margin"]
        for key in ("position", "animate", "outline"):
            tpl["captions"].setdefault(key, defaults[key])
    output = args.output or str(template_output(args.input, name, dest))
    values = {
        "$INPUT": os.path.abspath(args.input),
        "$OUTPUT": os.path.abspath(output),
        "$CUES": os.path.abspath(args.cues) if args.cues else None,
        "$SRT": os.path.abspath(args.srt) if args.srt else None,
        "$LOGO": os.path.abspath(args.logo) if args.logo else None,
        "$BRAND": os.path.abspath(args.brand) if args.brand else None,
        "$CHAPTERS": os.path.abspath(args.chapters) if args.chapters else None,
        "$TITLE": args.title,
        "$IMAGE": os.path.abspath(args.image) if args.image else None,
    }
    for flag, path in (("--cues", args.cues), ("--srt", args.srt), ("--logo", args.logo),
                       ("--brand", args.brand), ("--chapters", args.chapters), ("--image", args.image)):
        if path and not os.path.isfile(path):
            die(f"{flag}: file not found: {path}")
    proj, _ = fill_template(tpl, values)
    if args.fit:
        proj.setdefault("frame", {})["fit"] = args.fit
    return proj


def template_ext(dest: str) -> str:
    """A destination with no frame delivers audio: the podcast template writes .m4a, not .mp4."""
    return ".mp4" if (PLATFORMS.get(dest) or {}).get("frame") else ".m4a"


def template_output(input_path: str, name: str, dest: str) -> Path:
    """Where a template writes when no -o was given: next to the input, named after it and the
    template. One rule for a single template and for a pack, so `--template tiktok` and
    `--template tiktok,x` put their files in the same place (review 12)."""
    stem = Path(input_path).with_suffix("").name
    return Path(input_path).resolve().parent / f"{stem}_{name}{template_ext(dest)}"


def list_templates() -> None:
    """The templates, the destination each delivers to, and the zones its UI covers."""
    print("%-15s %-11s %-5s %7s  %-10s %s" % ("template", "frame", "fit", "max", "loudness", "safe zones (fraction of the frame)"))
    for name in template_names():
        tpl = load_template(name)
        dest = str((tpl.get("check") or {}).get("platform") or name)
        plat = PLATFORMS.get(dest) or {}
        frame = plat.get("frame")
        spec = plat.get("spec") or {}
        safe = plat.get("safe") or {}
        dur = spec.get("max_duration")
        zones = ", ".join("%s %.2f" % (edge, safe.get(edge, 0)) for edge in ("top", "bottom", "left", "right") if safe.get(edge))
        size = "%dx%d" % (frame["w"], frame["h"]) if frame else "audio"
        fit = str((tpl.get("frame") or {}).get("fit") or "-")
        loud = ("%g LUFS" % spec["lufs"]) if spec.get("lufs") is not None else "-"
        print("%-15s %-11s %-5s %7s  %-10s %s" % (name, size, fit, ("%gs" % dur) if dur else "-", loud, zones or "none"))


# `--template all`: every destination a single edit is normally posted to. The podcast template
# is audio-only and youtube-shorts is an alias of shorts, so neither belongs in a video pack.
PACK_DEFAULT = ["tiktok", "reels", "shorts", "youtube", "x", "linkedin", "facebook"]


def expand_templates(value: str) -> List[str]:
    if value.strip() == "all":
        return list(PACK_DEFAULT)
    names = [n.strip() for n in value.split(",") if n.strip()]
    if not names:
        die("--template needs a name, a comma-separated list, or 'all'")
    known = template_names()
    seen: List[str] = []
    for name in names:
        # the spellings people write resolve to the destination they mean, the same way
        # check.py --platform and export.py --preset take them (scripts/_platforms.py)
        if name not in known:
            name = resolve_platform(name) or name
        if name not in known:
            die(f"unknown template {name!r}", hint="templates: " + ", ".join(known) + " (or 'all')")
        if name not in seen:
            seen.append(name)
    return seen


def render_pack(names: List[str], args) -> int:
    """The social pack: one edit delivered to every named destination, plus a table of what
    was written. Each destination is a full render (its own frame, captions, loudness, export
    and platform check), so the pack reports per-platform results rather than one verdict."""
    stem = Path(args.input).with_suffix("").name
    outdir = Path(args.output).parent if args.output else Path(args.input).resolve().parent
    dests = {name: str((load_template(name).get("check") or {}).get("platform") or name) for name in names}
    rows: List[Dict[str, Any]] = []
    outputs: List[str] = []
    failed: List[str] = []
    for name in names:
        # the destination decides the container: an audio-only destination in a pack must not be
        # handed a .mp4 name the single-template form would never have written (review 12)
        dest_out = str(outdir / (stem + "_" + name + template_ext(dests[name])))
        argv = [str(HERE / "render.py"), args.input, "--template", name, "-o", dest_out]
        for flag, value in (("--cues", args.cues), ("--srt", args.srt), ("--logo", args.logo),
                            ("--title", args.title), ("--brand", args.brand), ("--fit", args.fit),
                            ("--chapters", args.chapters), ("--image", args.image)):
            if value:
                argv += [flag, str(value)]
        info(f"→ pack: {name}")
        proc = run_tool(argv + child_args() + ["--json"])
        try:
            doc = json.loads(proc.stdout.strip() or "{}")
        except ValueError:
            doc = {}
        # the child ran with --json, so its planned commands come back in the document: the pack
        # is the one path that writes seven files, and --dry-run has to show all of them
        for line in proc.stderr.splitlines():
            if line.startswith("$ ") or line.startswith("[dry-run]"):
                STATE.commands.append(line[2:] if line.startswith("$ ") else line)
        STATE.commands.extend(str(c) for c in (doc.get("commands") or []))
        out = doc.get("output") or dest_out
        chk = doc.get("check") or {}
        ok = proc.returncode == 0 and doc.get("status") == "completed"
        probe_doc = doc.get("probe") or {}
        if STATE.dry_run:
            # A dry run encoded nothing and verified nothing. Reading a size off a file left over
            # from an earlier real run, or calling an unrun check "pass", reports a verification
            # result for a run that never happened (review 12).
            rows.append({"platform": name, "file": os.path.basename(out), "path": out,
                         "size_bytes": None, "duration": None, "check": "planned", "ok": bool(ok)})
            continue
        size = os.path.getsize(out) if os.path.exists(out) else 0
        rows.append({"platform": name, "file": os.path.basename(out), "path": out,
                     "size_bytes": size, "duration": probe_doc.get("duration"),
                     "check": ("pass" if chk.get("ok") else ("%d FAIL" % chk["failed"]) if chk.get("failed") else ("pass" if ok else "failed")),
                     "ok": bool(ok)})
        outputs.append(out)
        if not ok:
            failed.append(name)
    pack = str(outdir / f"{stem}_pack.md")
    lines = [f"# Social pack — {stem}", "",
             "| platform | file | size | duration | check |", "|---|---|---|---|---|"]
    for r in rows:
        dur = f"{r['duration']:.2f} s" if r.get("duration") else "-"
        mb = f"{r['size_bytes'] / 1024 / 1024:.1f} MB" if r.get("size_bytes") else "-"
        lines.append(f"| {r['platform']} | {r['file']} | {mb} | {dur} | {r['check']} |")
    lines += ["", f"{len(rows)} destinations from one edit ({os.path.basename(args.input)}).",
              "Rendered by ffmpeg-skill; `report.py --pack` turns this table into an HTML report."]
    if not STATE.dry_run:
        Path(pack).write_text("\n".join(lines) + "\n", encoding="utf-8")
    info(("[dry-run] would write " if STATE.dry_run else "wrote ") + pack)
    if failed:
        die(f"pack: {len(failed)} of {len(rows)} destinations failed: {', '.join(failed)}",
            kind="verification", output=pack, dry_run=STATE.dry_run, pack=rows, outputs=outputs)
    emit(pack, pack=rows, outputs=outputs, stages=["pack"],
         verification=[{"step": "check", "ok": r["ok"], "platform": r["platform"]} for r in rows])
    return 0


def check_keys(obj: Any, schema: str, label: str) -> None:
    """Refuse an unrecognised key, naming the object, the key and the nearest valid one."""
    if not isinstance(obj, dict):
        return
    valid = OBJECT_KEYS[schema]
    for key in obj:
        if key in valid:
            continue
        near = NEAR_KEYS.get(schema, {}).get(str(key)) or next(iter(difflib.get_close_matches(str(key), sorted(valid), n=1, cutoff=0.6)), None)
        die(f"{label}: unknown key {key!r}" + (f" (did you mean {near!r}?)" if near
            else f" (valid keys: {', '.join(sorted(valid))})"))


def validate_project(proj: Dict[str, Any]) -> None:
    check_keys(proj, "project", "project")
    for name in ("frame", "transition", "silence", "audiogram", "captions", "audio", "loudness", "fit", "export", "check"):
        check_keys(proj.get(name), name, name)
    check_keys((proj.get("audio") or {}).get("stems"), "audio.stems", "audio.stems")
    if isinstance(proj.get("chapters"), list):
        # Every other project error is raised here, before the first ffmpeg call; a chapter typo
        # found inside the last stage costs a whole render and leaves an unchaptered file behind.
        for i, item in enumerate(proj["chapters"]):
            check_keys(item, "chapters[]", f"chapters[{i}]")
            if not isinstance(item, dict) or item.get("at") is None or not str(item.get("title") or "").strip():
                die(f'chapters[{i}]: needs {{"at": TIME, "title": STR}}')
    for name in ("clips", "graphics", "overlays"):
        items = proj.get(name)
        if isinstance(items, list):
            for i, item in enumerate(items):
                check_keys(item, f"{name}[]", f"{name}[{i}]")


def sh(script: str, *argv: Any, extra: List[str] = None) -> str:
    """Run a sibling script, forwarding --fast / --dry-run, returning its printed output path."""
    cmd = [str(HERE / script)] + [str(a) for a in argv] + (extra or []) + child_args() + ["--json"]
    info("→ " + " ".join(os.path.basename(c) if i < 1 else c for i, c in enumerate(cmd[:-1])))
    proc = run_tool(cmd)
    for line in proc.stderr.splitlines():
        if line.startswith("$ ") or line.startswith("[dry-run]"):
            STATE.commands.append(line[2:] if line.startswith("$ ") else line)
        elif line.strip():
            info("    " + line)
    try:
        doc = json.loads(proc.stdout.strip() or "{}")
    except ValueError:
        doc = {}
    if proc.returncode != 0:
        # Re-raise the stage's own failure: its kind, exit code and hint are what the caller
        # needs (a timeout inside audio.py is a timeout, not an "input" error of render.py).
        err = doc.get("error") or {}
        extra_fields = {"hint": err["hint"]} if err.get("hint") else {}
        die(f"{script} failed: {err.get('message') or (proc.stderr.strip().splitlines() or ['?'])[-1][:300]}",
            code=int(doc.get("exit_code") or 1), kind=err.get("kind") or "input", stage=script, **extra_fields)
    return str(doc.get("output") or "")


def execute_plan(plan: Dict[str, Any], path: str) -> int:
    """Run a plan written by `<tool> --plan FILE`: refuse if any fingerprinted input changed since
    the plan was made (the plan's commands would then describe a different edit), run the tool
    with the planned argv, then the plan's verify steps. --dry-run prints the planned commands."""
    if plan.get("plan_version") != PLAN_VERSION:
        die(f"{path}: plan_version {plan.get('plan_version')!r} is not {PLAN_VERSION}")
    tool = str(plan.get("tool") or "")
    script = HERE / f"{tool}.py"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tool) or not script.exists() or tool == "render":
        die(f"{path}: unknown tool {tool!r}")
    changed = []
    for inp in plan.get("inputs") or []:
        p = inp.get("path")
        if not p or not os.path.isfile(p):
            changed.append(f"{p}: missing")
            continue
        now = fingerprint(p)
        if now["size"] != inp.get("size") or now["sha256_head_tail"] != inp.get("sha256_head_tail"):
            changed.append(f"{p}: content changed since the plan was made")
    if changed:
        die("plan inputs differ from what was planned; re-run the tool with --plan to make a new plan:\n  " + "\n  ".join(changed),
            hint="plans are bound to the exact input files they were made from")
    if plan.get("cwd"):
        if not os.path.isdir(plan["cwd"]):
            die(f"plan cwd {plan['cwd']} no longer exists; relative paths in the plan would resolve elsewhere -- re-plan")
        os.chdir(plan["cwd"])
    if not isinstance(plan.get("argv"), list):
        die(f"{path}: argv must be a list")
    argv = [str(a) for a in plan["argv"]]
    if STATE.dry_run:
        for c in plan.get("commands") or []:
            STATE.commands.append(c)
            info("[dry-run] " + c)
        emit(plan.get("output"), plan=path, tool=tool, stages=[tool], check=None)
        return 0
    info(f"executing plan {path}: {tool} " + " ".join(argv))
    proc = run_tool([str(script)] + argv + child_args() + ["--json"])
    for line in proc.stderr.splitlines():
        if line.startswith("$ "):
            STATE.commands.append(line[2:])
        elif line.strip():
            info("    " + line)
    try:
        doc = json.loads(proc.stdout.strip() or "{}")
    except ValueError:
        doc = {}
    if proc.returncode != 0 or doc.get("status") != "completed":
        err = doc.get("error") or {}
        die(f"{tool} failed while executing the plan: {err.get('message') or proc.stderr.strip()[-300:]}",
            kind=err.get("kind", "ffmpeg"), plan=path, tool=tool)
    output = doc.get("output") or plan.get("output")
    check_result = None
    exit_code = 0
    for step in plan.get("verify") or []:
        if step.get("tool") == "check" and step.get("platform") and output:
            cp = run_tool([str(HERE / "check.py"), output, "--platform", step["platform"], "--json"] + child_args())
            try:
                check_result = json.loads(cp.stdout)
            except ValueError:
                check_result = {"error": cp.stderr.strip()[-300:]}
            if check_result.get("failed") or check_result.get("status") == "failed" or check_result.get("error"):
                exit_code = 1
    # a failed platform check is reported the way the direct path reports it: the tool completed,
    # verified is false, the rows say what to fix (review 6: a plan must not fail harder than the
    # same command run by hand)
    if exit_code:
        failed_rows = [r["check"] for r in (check_result or {}).get("checks", []) if r.get("status") == "FAIL"]
        info(f"plan done: {output}, but the {check_result.get('platform')} check failed" + (f": {', '.join(failed_rows)}" if failed_rows else ""))
    else:
        info(f"plan done: {output}")
    emit(output, plan=path, tool=tool, stages=[tool] + (["check"] if check_result else []), check=check_result, tool_result=doc,
         verification=([{"step": "check", "ok": not exit_code, "platform": check_result.get("platform")}] if check_result else [])
         + [s for s in (doc.get("verification") or []) if s.get("step") != "probe"])
    return 0


def frame_from_preset(frame: Dict[str, Any], export: Dict[str, Any]) -> None:
    """Fill frame.width/height from the export preset when the project gave only an aspect.
    Eval 7 (j08 twice, e01 by hand): "frame": {"aspect": "9:16"} with a reels export fitted a
    1280x720 source to 406x720, captions were burned at that size, and export.py upscaled them
    soft. A preset that names a delivery frame of the same aspect is that frame."""
    if not frame.get("aspect") or frame.get("width") or frame.get("height"):
        return
    preset = PRESETS.get(str(export.get("preset") or ""), {})
    if not (preset.get("w") and preset.get("h")):
        return
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*", str(frame["aspect"]))
    if not m or float(m.group(2)) == 0:
        return
    if abs(float(m.group(1)) / float(m.group(2)) - preset["w"] / preset["h"]) > 0.01:
        return
    frame["width"], frame["height"] = preset["w"], preset["h"]
    info(f"frame: {preset['w']}x{preset['h']} from the {export['preset']} export preset (captions and overlays are sized for delivery)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="project.json, or a plan.json written by <tool> --plan")
    ap.add_argument("--init", metavar="FILE", help="write a starter project file and exit")
    ap.add_argument("--work", help="work directory for intermediates (default: <output>_work)")
    ap.add_argument("--keep", action="store_true", help="keep intermediates (default: kept only when --work is given)")
    ap.add_argument("--stop-after", choices=["clips", "join", "silence", "fit", "captions", "graphics", "overlays", "audio", "loudness", "export"], help="stop after this stage (for iterating)")
    tpl = ap.add_argument_group("delivery templates (one command per destination)")
    tpl.add_argument("--template", metavar="NAME", help="render INPUT with a shipped template: " + ", ".join(template_names())
                                                        + ", a comma-separated list, or 'all' (the social pack)")
    tpl.add_argument("--list-templates", action="store_true", help="print the templates with their frames, limits and safe zones, and exit")
    tpl.add_argument("--cues", help="cue file for the template's captions (caption.py --text format)")
    tpl.add_argument("--srt", help="SRT file for the template's captions instead of --cues")
    tpl.add_argument("--logo", help="logo image the template overlays")
    tpl.add_argument("--title", help="title text for the template's opening card / lower third")
    tpl.add_argument("--brand", help="brand.json the template's captions, graphics and overlays use")
    tpl.add_argument("--chapters", help="chapter file (podcast template)")
    tpl.add_argument("--image", help="still image behind the visualisation (audiogram template); a local file, nothing is fetched")
    tpl.add_argument("--fit", choices=["crop", "pad", "blur"], help="override how the template reaches its aspect")
    tpl.add_argument("-o", "--output", help="output file (default: next to the input, <input>_<template>.mp4, "
                                            "or .m4a for an audio-only destination); for a list of templates "
                                            "or 'all' its directory is where the pack is written")
    tpl.add_argument("--write-project", metavar="FILE", help="write the filled project.json for editing and stop (no render)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.list_templates:
        list_templates()
        return 0
    if args.init:
        Path(args.init).write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
        info(f"wrote {args.init}; edit clips/src and run: render.py {args.init}")
        print(args.init)
        return 0
    if not args.project:
        die("give a project.json (or --init FILE, or --template NAME INPUT)")
    if STATE.plan:
        die("render.py has no --plan: the project file is the plan (use --dry-run to preview it)")
    if args.template:
        # `render.py --template tiktok talk.mp4 ...`: the positional is the footage, not a project.
        args.input = args.project
        if not os.path.isfile(args.input):
            die(f"input not found: {args.input}")
        names = expand_templates(args.template)
        if len(names) > 1:
            if args.write_project:
                die("--write-project writes one project; name a single template")
            return render_pack(names, args)
        proj: Dict[str, Any] = template_project(names[0], args)
        base = Path.cwd()
    else:
        for flag, value in (("--cues", args.cues), ("--srt", args.srt), ("--logo", args.logo),
                            ("--title", args.title), ("--brand", args.brand), ("--chapters", args.chapters),
                            ("--image", args.image), ("--fit", args.fit), ("--write-project", args.write_project)):
            if value:
                die(f"{flag} belongs to --template NAME INPUT; a project.json states it in the project itself")
        try:
            proj = json.loads(Path(args.project).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            die(f"cannot read project: {exc}")
        if not isinstance(proj, dict):
            die(f"{args.project}: not a project or plan object (top level is {type(proj).__name__})")
        if "plan_version" in proj:
            return execute_plan(proj, os.path.abspath(args.project))
        base = Path(args.project).resolve().parent
    validate_project(proj)
    if args.write_project:
        # Only the filled project: the point is to edit it before rendering, so nothing runs.
        try:
            Path(args.write_project).write_text(json.dumps(proj, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            die(f"cannot write {args.write_project}: {exc}", kind="output")
        info(f"wrote {args.write_project}; edit it and run: render.py {args.write_project}")
        emit(args.write_project, template=args.template, stages=[], check=None)
        return 0

    def rel(p: Any) -> str:
        p = str(p)
        return p if os.path.isabs(p) else str(base / p)

    if isinstance(proj.get("chapters"), str) and not os.path.exists(rel(proj["chapters"])):
        die(f"chapters file not found: {rel(proj['chapters'])}")

    clips = proj.get("clips") or []
    if not clips:
        die("project.clips is empty")
    output = rel(proj.get("output") or "final.mp4")
    # the final stage is a copy from the work dir, so run()'s own guard never sees the sources (review 5)
    refuse_output_is_input(output, *[rel(c.get("src")) for c in clips if c.get("src")])
    # The default work dir name comes only from the output path, with no PID or timestamp --
    # two concurrent render.py runs targeting the same output (a batch.py "project" recipe
    # processing several files in parallel, or simply running render.py twice by mistake) shared
    # the same work directory and clobbered each other's same-named intermediates (clip00.mp4,
    # fit.mp4, ...) mid-run. An explicit --work is left as given (the caller asked for that exact,
    # shared path, e.g. to inspect intermediates across runs); only the auto-derived default is
    # made unique per process, since it's the one that's also auto-deleted at the end.
    work = Path(args.work) if args.work else Path(f"{Path(output).with_suffix('')}_work_{os.getpid()}")
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die(f"cannot create the work directory {work}: {e}")
    if not args.keep and not args.work:
        # a failed or dry run used to leave <output>_work_<pid>/ behind (sweep F15): the
        # auto-named directory is ours alone, so remove it on every exit path
        import atexit
        import shutil
        atexit.register(lambda: shutil.rmtree(work, ignore_errors=True))
    # Intermediates keep the delivery's media kind: a .mp4 project is unchanged (every stage file
    # is still clipNN.mp4 / fit.mp4 / loudnorm.mp4), while an audio-only delivery (the podcast
    # template) carries its stages through the audio container instead of a video one.
    mid = Path(output).suffix.lower() if Path(output).suffix.lower() in AUDIO_EXT else ".mp4"
    frame = dict(proj.get("frame") or {})
    trans = proj.get("transition") or {}
    frame_from_preset(frame, proj.get("export") or {})
    brand_args: List[str] = ["--brand", rel(proj["brand"])] if proj.get("brand") else []
    # A project written from a delivery template names its destination, so the caption and
    # graphics stages are told which zones that app's UI covers; the template's own explicit
    # margin/size still win inside those tools. A hand-written project (no "template" key) is
    # unchanged -- it never gets a --platform it did not ask for.
    dest = str(((proj.get("check") or {}).get("platform") or "")) if proj.get("template") else ""
    platform_args: List[str] = ["--platform", dest] if dest in PLATFORMS and PLATFORMS[dest].get("frame") else []
    stages_done: List[str] = []

    # ---- clips
    parts: List[str] = []
    for i, c in enumerate(clips):
        src = rel(c["src"])
        if not os.path.exists(src):
            die(f"clip {i}: source not found: {src}")  # under --dry-run too: a plan for a missing file is no plan
        if not STATE.dry_run:
            probe(src)
        needs_cut = c.get("in") is not None or c.get("out") is not None
        part = str(work / f"clip{i:02d}{mid}")
        if needs_cut:
            argv: List[Any] = [src, "-o", part, "--accurate"]
            if c.get("in") is not None:
                argv += ["--start", c["in"]]
            if c.get("out") is not None:
                argv += ["--end", c["out"]]
            sh("cut.py", *argv)
        else:
            part = src
        if c.get("speed"):
            spd = float(c["speed"])
            if not (spd > 0) or spd != spd or spd == float("inf"):
                die(f"clip {i}: speed must be a positive number, got {c['speed']!r}")
            if abs(spd - 1.0) > 1e-6:  # speed 1.0 used to cost a full re-encode for nothing
                dur = (probe(part).get("duration") or 0.0) if not STATE.dry_run else 10.0
                fitted = str(work / f"clip{i:02d}_speed{mid}")
                sh("fit.py", part, "--duration", f"{dur / spd:.3f}", "-o", fitted)
                part = fitted
        parts.append(part)
    stages_done.append("clips")
    current = parts[0]

    # ---- audiogram: the picture an audio-only source needs before anything else can work on it
    ag = proj.get("audiogram")
    if ag:
        if not ag.get("image") and not ag.get("background"):
            die('audiogram: give an "image" (a local file) or a "background" colour -- this skill '
                "never fetches a picture and never invents cover art", kind="input")
        nxt = str(work / f"audiogram{mid}")
        argv = [current, "-o", nxt]
        for key, flag in (("image", "--image"), ("image_fit", "--image-fit"), ("style", "--style"),
                          ("position", "--position"), ("vis_height", "--vis-height"),
                          ("opacity", "--opacity"), ("platform", "--platform"), ("title", "--title"),
                          ("color", "--color"), ("background", "--background"),
                          ("width", "--width"), ("height", "--height"), ("fps", "--fps")):
            if ag.get(key) is not None:
                argv += [flag, str(ag[key])]
        argv += brand_args
        sh("waveform.py", *argv)
        current = nxt
        parts = [current]
        stages_done.append("audiogram")

    if args.stop_after == "clips":
        emit(current, stages=stages_done)
        return 0

    # ---- join
    if len(parts) > 1:
        current = str(work / f"joined{mid}")
        argv = list(parts) + ["-o", current, "--transition", trans.get("type", "fade"), "--duration", str(trans.get("duration", 0.5))]
        if frame.get("width"):
            argv += ["--width", str(frame["width"])]
        if frame.get("height"):
            argv += ["--height", str(frame["height"])]
        if frame.get("fps"):
            argv += ["--fps", str(frame["fps"])]
        sh("join.py", *argv)
        stages_done.append("join")
    if args.stop_after == "join":
        emit(current, stages=stages_done)
        return 0

    # ---- silence
    sil = proj.get("silence")
    if sil:
        nxt = str(work / f"tight{mid}")
        argv = [current, "-o", nxt]
        for k, flag in (("threshold", "--threshold"), ("min_silence", "--min-silence"), ("margin", "--margin")):
            if sil.get(k) is not None:
                argv += [flag, str(sil[k])]
        sh("silence.py", *argv)
        current = nxt
        stages_done.append("silence")
    if args.stop_after == "silence":
        emit(current, stages=stages_done)
        return 0

    # ---- fit (duration and/or frame)
    fit = dict(proj.get("fit") or {})
    if frame.get("aspect"):
        fit.setdefault("aspect", frame["aspect"])
    if frame.get("fit"):
        fit.setdefault("fit", frame["fit"])
    if frame.get("width") and len(parts) == 1:
        fit.setdefault("width", frame["width"])
    if frame.get("height") and len(parts) == 1:
        fit.setdefault("height", frame["height"])
    if frame.get("fps") and len(parts) == 1:
        fit.setdefault("fps", frame["fps"])
    if fit:
        nxt = str(work / f"fit{mid}")
        argv = [current, "-o", nxt]
        for k, flag in (("duration", "--duration"), ("method", "--method"), ("aspect", "--aspect"), ("fit", "--fit"), ("width", "--width"), ("height", "--height"), ("fps", "--fps"), ("smooth", "--smooth")):
            if fit.get(k) is not None:
                argv += [flag, str(fit[k])]
        sh("fit.py", *argv)
        current = nxt
        stages_done.append("fit")
    if args.stop_after == "fit":
        emit(current, stages=stages_done)
        return 0

    # ---- captions
    cap = proj.get("captions")
    if cap:
        nxt = str(work / f"captioned{mid}")
        argv = [current, "-o", nxt]
        if cap.get("text"):
            argv += ["--text", rel(cap["text"])]
        elif cap.get("srt"):
            argv += ["--srt", rel(cap["srt"])]
        elif cap.get("ass"):
            argv += ["--ass", rel(cap["ass"])]
        else:
            die("captions needs text, srt or ass")
        for k, flag in (("font", "--font"), ("size", "--size"), ("color", "--color"), ("position", "--position"), ("margin", "--margin"), ("animate", "--animate"), ("highlight_color", "--highlight-color"), ("outline", "--outline"), ("lang", "--lang"), ("offset", "--offset"), ("max_lines", "--max-lines"), ("min_duration", "--min-duration")):
            if cap.get(k) is not None:
                argv += [flag, str(cap[k])]
        for k, flag in (("karaoke", "--karaoke"), ("bold", "--bold"), ("box", "--box")):
            if cap.get(k):
                argv.append(flag)
        sh("caption.py", *(argv + brand_args + platform_args))
        current = nxt
        stages_done.append("captions")
    if args.stop_after == "captions":
        emit(current, stages=stages_done)
        return 0

    # ---- graphics
    for i, g in enumerate(proj.get("graphics") or []):
        nxt = str(work / f"graphics{i:02d}{mid}")
        if not g.get("template"):
            die(f"graphics[{i}] needs a template")
        argv = [current, "-o", nxt, "--template", g["template"]]
        for k, flag in (("name", "--name"), ("title", "--title"), ("subtitle", "--subtitle"), ("start", "--start"), ("end", "--end"), ("position", "--position"), ("from", "--from"), ("scale", "--scale"), ("primary", "--primary"), ("text_color", "--text-color"), ("lang", "--lang"),
                        ("text", "--text"), ("top", "--top"), ("bottom", "--bottom"), ("duration", "--duration"), ("margin", "--margin"), ("platform", "--platform")):
            if g.get(k) is not None:
                argv += [flag, str(g[k])]
        # the entry's own "platform" is the more specific statement than the template's destination
        sh("graphics.py", *(argv + brand_args + ([] if g.get("platform") else platform_args)))
        current = nxt
        if "graphics" not in stages_done:
            stages_done.append("graphics")
    if args.stop_after == "graphics":
        emit(current, stages=stages_done)
        return 0

    # ---- overlays
    for i, ov in enumerate(proj.get("overlays") or []):
        nxt = str(work / f"overlay{i:02d}{mid}")
        argv = [current, "-o", nxt]
        if ov.get("logo"):
            argv.append("--logo")
        elif ov.get("image"):
            argv += ["--image", rel(ov["image"])]
        elif ov.get("text"):
            argv += ["--text", ov["text"]]
        else:
            die(f"overlays[{i}] needs image or text")
        for k, flag in (("position", "--position"), ("start", "--start"), ("end", "--end"), ("fade", "--fade"), ("opacity", "--opacity"), ("scale", "--scale"), ("font_size", "--font-size"), ("font", "--font"), ("font_file", "--font-file"), ("margin", "--margin"), ("platform", "--platform")):
            if ov.get(k) is not None:
                argv += [flag, str(ov[k])]
        if ov.get("box"):
            argv.append("--box")
        # review 12: the overlay stage was the one stage that never heard which destination this
        # is, so a template's top-left logo landed 24 px in -- under TikTok's own status bar.
        sh("overlay.py", *(argv + brand_args + ([] if ov.get("platform") else platform_args)))
        current = nxt
        if "overlays" not in stages_done:
            stages_done.append("overlays")
    if args.stop_after == "overlays":
        emit(current, stages=stages_done)
        return 0

    # ---- audio
    au = dict(proj.get("audio") or {})
    if au:
        # "stems": one level per element of the mix, the way a mixing desk names them. Each maps
        # to the flag that already exists (dialogue = the main track's gain, music = the bed's
        # level, effects = the third file's level), so a stems block is a vocabulary, not a
        # second code path -- and an explicit flag next to it wins, since it is the more specific
        # statement of the same thing.
        stems = au.pop("stems", None) or {}
        if stems.get("effects") is not None and not au.get("effects"):
            die('audio.stems.effects sets the level of "audio": {"effects": "sfx.wav"}, which this project does not have')
        if stems.get("music") is not None and not au.get("music"):
            die('audio.stems.music sets the level of "audio": {"music": "bed.mp3"}, which this project does not have')
        for stem, key in (("dialogue", "gain"), ("music", "music_volume"), ("effects", "effects_volume")):
            if stems.get(stem) is not None:
                au.setdefault(key, stems[stem])
        nxt = str(work / f"audio{mid}")
        argv = [current, "-o", nxt]
        for k, flag in (("music", "--music"), ("replace", "--replace"), ("effects", "--effects")):
            if au.get(k):
                argv += [flag, rel(au[k])]
        for k, flag in (("music_volume", "--music-volume"), ("effects_volume", "--effects-volume"), ("fade_in", "--fade-in"), ("fade_out", "--fade-out"), ("music_fade_out", "--music-fade-out"), ("gain", "--gain"), ("duck_amount", "--duck-amount"), ("duck_threshold", "--duck-threshold"), ("duck_attack", "--duck-attack"), ("duck_release", "--duck-release"), ("stereo_widen", "--stereo-widen")):
            if au.get(k) is not None:
                argv += [flag, str(au[k])]
        # "voice": true is the medium chain; "voice": "light"|"medium"|"strong" names one
        if au.get("voice") is not None and au.get("voice") is not False:
            argv += ["--voice"] + ([] if au["voice"] is True else [str(au["voice"])])
        for k, flag in (("denoise", "--denoise"), ("duck", "--duck"), ("music_loop", "--music-loop"), ("stereo", "--stereo"), ("mono", "--mono"), ("downmix", "--downmix")):
            if au.get(k):
                argv.append(flag)
        sh("audio.py", *argv)
        current = nxt
        stages_done.append("audio")
    if args.stop_after == "audio":
        emit(current, stages=stages_done)
        return 0

    # ---- loudness
    ld = proj.get("loudness")
    if ld:
        nxt = str(work / f"loudnorm{mid}")
        argv = [current, "-o", nxt]
        if ld.get("lufs") is not None:
            argv += ["-I", str(ld["lufs"])]
        if ld.get("tp") is not None:
            argv += ["--tp", str(ld["tp"])]
        sh("loudness.py", *argv)
        current = nxt
        stages_done.append("loudness")
    if args.stop_after == "loudness":
        emit(current, stages=stages_done)
        return 0

    # ---- export
    ex = proj.get("export")
    if ex and ex.get("preset"):
        argv = [current, "--preset", ex["preset"], "-o", output]
        if ex.get("fit"):
            argv += ["--fit", ex["fit"]]
        if ex.get("crf") is not None:
            argv += ["--crf", str(ex["crf"])]
        normalize = ex.get("normalize")
        if normalize is None and ex["preset"] in PLATFORM_OF and not proj.get("loudness"):
            # eval 8: a reels project without the key rendered fully, failed the loudness check and
            # was rendered again; a platform preset with no loudness stage of its own gets the
            # one-export behaviour by default ("normalize": false opts out)
            normalize = True
            info(f"export: --normalize on by default for the {ex['preset']} preset (set \"normalize\": false to skip)")
        if normalize:
            argv += ["--normalize"]  # one export that meets the platform's loudness (export.py --normalize)
        sh("export.py", *argv)
        stages_done.append("export")
    else:
        if not STATE.dry_run:
            place_output(current, output)
        info(("[dry-run] would copy" if STATE.dry_run else "copied") + f" final stage to {output}")
    current = output

    # ---- chapters (metadata.py on the delivered file: streams copied, markers written)
    ch = proj.get("chapters")
    if ch:
        # Planned exactly like the audio stage: the metadata.py command names the export's output,
        # which a dry run has not written either. The plan is the run, so --dry-run shows the
        # command and lists the stage (the child's own --dry-run prints rather than writes).
        if isinstance(ch, list):
            chapter_file = str(work / "chapters.txt")
            lines = [f"{entry['at']} {entry['title']}" for entry in ch]
            Path(chapter_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            chapter_file = rel(ch)
        tagged = str(work / ("chapters" + Path(output).suffix))
        sh("metadata.py", output, "--chapters", chapter_file, "-o", tagged)
        if not STATE.dry_run:
            place_output(tagged, output)
        stages_done.append("chapters")

    # ---- check
    ck = proj.get("check")
    check_result = None
    exit_code = 0
    if ck and ck.get("platform") and not STATE.dry_run:
        proc = run_tool([str(HERE / "check.py"), output, "--platform", ck["platform"], "--json"] + child_args())
        try:
            check_result = json.loads(proc.stdout)
        except ValueError:
            check_result = {"error": proc.stderr.strip()[-300:]}
        if check_result.get("failed"):
            info(f"check: {check_result['failed']} FAIL — " + "; ".join(f"{r['check']}={r['value']} ({r['fix']})" for r in check_result["checks"] if r["status"] == "FAIL"))
            exit_code = 1
        elif check_result.get("error") or check_result.get("status") == "failed":
            info(f"check: could not run check.py — {check_result.get('error')}")
            exit_code = 1
        else:
            info(f"check: OK for {ck['platform']}")
        stages_done.append("check")

    if not args.keep and not args.work:
        # Also clean up on --dry-run: a dry run still creates this directory (and some steps,
        # e.g. caption.py's .ass sidecar, write into it even under --dry-run), and now that the
        # default name carries this process's PID, nothing else will ever reuse -- and so
        # implicitly clean up -- a leftover dry-run directory the way a same-named real run used
        # to before the PID suffix was added.
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    if exit_code:
        # The deliverable is written and verified, but it does not meet the requested platform
        # spec (or the check itself could not run): a failed delivery, reported as one.
        failed_rows = [r["check"] for r in (check_result or {}).get("checks", []) if r.get("status") == "FAIL"]
        die(f"rendered {output} but the {ck['platform']} check failed" + (f": {', '.join(failed_rows)}" if failed_rows else ""),
            kind="verification", output=output, dry_run=STATE.dry_run, stages=stages_done, check=check_result,
            probe=probe(output, role="output"))
    info(f"rendered {output} via {' → '.join(stages_done)}")
    emit(output, stages=stages_done, check=check_result,
         verification=[{"step": "check", "ok": True, "platform": ck["platform"]}] if check_result else [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
