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
  "check": {"platform": "reels"},     ("content": true adds check.py --content's black/frozen/silence rows)
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
import hashlib
import re
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from export import PRESETS, PLATFORM_OF
from _platforms import PLATFORMS, caption_defaults, resolve as resolve_platform
from _common import STATE, add_common, aspect_ratio, brand_caption_style, load_brand, apply_common, child_args, die, emit, info, probe, require_tool, run, run_tool, place_output, refuse_output_is_input, _check_existing_output, _check_output_path, fingerprint, PLAN_VERSION, ffmpeg_version
import subprocess
from _contract import CONTRACT_VERSION
from batch import file_key


def _skill_version() -> str:
    """The shipped version, from package.json -- in the cache key so a stage whose implementation
    changed cannot serve back an artifact the old one wrote."""
    try:
        return str(json.loads((Path(__file__).resolve().parent.parent / "package.json")
                              .read_text(encoding="utf-8")).get("version") or "?")
    except (OSError, ValueError):
        return "?"


SKILL_VERSION = _skill_version()

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
                          "audiogram", "template", "snap"}),
    "clips[]": frozenset({"src", "in", "out", "speed", "snap"}),
    # 1.17: beat snapping, forwarded to cut.py for any clip that has in/out
    "snap": frozenset({"to", "tolerance", "min_confidence", "source"}),
    "frame": frozenset({"aspect", "width", "height", "fps", "fit"}),
    "transition": frozenset({"type", "duration"}),
    "silence": frozenset({"threshold", "min_silence", "margin"}),
    # 1.16: the picture an audio-only source gets before the rest of the chain can work on it
    "audiogram": frozenset({"image", "image_fit", "style", "position", "vis_height", "opacity",
                            "platform", "title", "color", "background", "width", "height", "fps"}),
    # 1.17.1: fit_size / min_size / fit_size_scope, so a project can state the fit policy the
    # templates now default to (eval 18 cs1 hit "unknown key 'fit_size'" and hand-ran the stages).
    "captions": frozenset({"text", "srt", "ass", "font", "size", "color", "position", "margin",
                           "animate", "highlight_color", "outline", "karaoke", "bold", "box",
                           "lang", "offset", "max_lines", "min_duration",
                           "fit_size", "min_size", "fit_size_scope"}),
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
    "check": frozenset({"platform", "content"}),
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


def brand_states_caption_size(path: Optional[str]) -> bool:
    """True only when a brand file actually names a caption size. `--brand` alone says nothing
    about type size -- brand_caption_style() applies no defaults -- so the presence of the flag
    must not switch caption.py's `--fit-size auto` off (review 17 finding 1)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        stated = load_brand(path).get("_stated") or {}
    except SystemExit:
        raise
    except Exception:
        return False
    # BRAND_DEFAULTS always supplies caption.size, so only what the FILE said can answer this
    # (the same reason brand_states_font() exists).
    return brand_caption_style(stated).get("size") is not None


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
        # 1.17.1: that size is the table's default, not a size anyone asked for, so it must not
        # switch off caption.py's `--fit-size auto` the way a stated --size does -- eval 18 saw a
        # long cue split across two consecutive cues instead of the type shrinking to fit. A
        # template that states "fit_size" wins, and so does a brand file that STATES a caption
        # size (that size is a statement about the look). A brand of colours or a font alone
        # states no size, so it must not stand the fitter down: review 17 finding 1.
        if not brand_states_caption_size(args.brand):
            tpl["captions"].setdefault("fit_size", "on")
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
    """Refuse an unrecognised key, naming the object, the key and the nearest valid one. A value
    that is not an object is require_object()'s to refuse, and only where the run reads it."""
    if not isinstance(obj, dict):
        return
    valid = OBJECT_KEYS[schema]
    for key in obj:
        if key in valid:
            continue
        near = NEAR_KEYS.get(schema, {}).get(str(key)) or next(iter(difflib.get_close_matches(str(key), sorted(valid), n=1, cutoff=0.6)), None)
        die(f"{label}: unknown key {key!r}" + (f" (did you mean {near!r}?)" if near
            else f" (valid keys: {', '.join(sorted(valid))})"))


def require_object(obj: Any, label: str) -> None:
    """Refuse a value that is not an object where the run reads it with .get(): "export": "reels"
    in a render, a string frame, a clip written as a bare path. 2.2.1 died there with a traceback
    and nothing on stdout under --json. null, false and {} still ask for nothing."""
    if obj and not isinstance(obj, dict):
        die(f"{label}: must be an object {{...}}, got {type(obj).__name__} {obj!r:.60}")


# the stage that first reads each section; --stop-after before it means the run never reads it
READ_AT = {"transition": "join", "silence": "silence", "fit": "fit", "captions": "captions",
           "graphics": "graphics", "overlays": "overlays", "loudness": "loudness", "export": "export",
           "check": "check"}
_READ_ORDER = ["clips", "join", "silence", "fit", "captions", "graphics", "overlays", "audio", "loudness", "export", "check"]


def _reaches(stage: str, stop_after: Optional[str]) -> bool:
    return not stop_after or _READ_ORDER.index(stage) <= _READ_ORDER.index(stop_after)


def validate_project(proj: Dict[str, Any], timeline: bool = False, stop_after: Optional[str] = None) -> None:
    """Every project error the run would hit, before the first ffmpeg call. A value that is not
    an object is refused only where this run reads it (require_object()): a full render reads
    every stage's section, a transition only between two or more clips and a clip's snap only
    on a clip it cuts; --export-timeline (`timeline`) reads the clips, frame, audio and a
    transition between clips, and only names the other sections in not_exported. 2.2.1 rendered
    a single clip with "transition": "none" and exported "captions": "subs.srt", reading neither,
    and a patch release does not refuse them."""
    check_keys(proj, "project", "project")
    clips = proj.get("clips")
    # the join (or the timeline's dissolves) reads the transition; an audiogram render joins nothing
    several = isinstance(clips, list) and len(clips) > 1 and (timeline or not proj.get("audiogram"))
    read = {"frame", "audio"} | ({"transition"} if several else set())
    if not timeline:
        read |= {"silence", "audiogram", "captions", "loudness", "fit", "export", "check", "snap"}
        # --stop-after ends the run before later stages read their sections: 2.2.1 completed a
        # `--stop-after fit` preview of a project with "captions": "subs.srt", never reading it
        read = {n for n in read if n not in READ_AT or _reaches(READ_AT[n], stop_after)}
    for name in ("frame", "transition", "silence", "audiogram", "captions", "audio", "loudness", "fit", "export", "check", "snap"):
        if name in read:
            require_object(proj.get(name), name)
        check_keys(proj.get(name), name, name)
    check_keys((proj.get("audio") or {}).get("stems"), "audio.stems", "audio.stems")
    if isinstance(proj.get("chapters"), list):
        # Every other project error is raised here, before the first ffmpeg call; a chapter typo
        # found inside the last stage costs a whole render and leaves an unchaptered file behind.
        for i, item in enumerate(proj["chapters"]):
            if isinstance(item, dict):
                check_keys(item, "chapters[]", f"chapters[{i}]")
            if not isinstance(item, dict) or item.get("at") is None or not str(item.get("title") or "").strip():
                die(f'chapters[{i}]: needs {{"at": TIME, "title": STR}}')
    for name in ("clips", "graphics", "overlays"):
        items = proj.get(name)
        if name == "clips" or (not timeline and _reaches(READ_AT[name], stop_after)):  # the export reads only the clips
            if items and not isinstance(items, list):
                die(f"{name}: must be a list of objects [{{...}}], got {type(items).__name__} {items!r:.60}")
            for i, item in enumerate(items or []):
                if not isinstance(item, dict):
                    die(f"{name}[{i}]: must be an object {{...}}, got {type(item).__name__} {item!r:.60}")
        for i, item in enumerate(items if isinstance(items, list) else []):
            check_keys(item, f"{name}[]", f"{name}[{i}]")
            if name != "clips":
                continue
            # every clip stage starts from rel(c["src"]): without one it was a KeyError traceback
            if not item.get("src"):
                die(f"clips[{i}]: no src")
            if item.get("snap") is not None:
                # the render reads a clip's snap only on a clip it cuts (in/out), the export never
                if not timeline and (item.get("in") is not None or item.get("out") is not None):
                    require_object(item["snap"], f"clips[{i}].snap")
                check_keys(item["snap"], "snap", f"clips[{i}].snap")


_LAST_DOC: Dict[str, Any] = {}   # the JSON document the most recent sh() child printed


def _refuse_uncached_earlier_stage(stage: str) -> None:
    """--from STAGE promises the earlier stages come from the cache. When one does not, say so
    rather than quietly re-encoding the thing the caller asked to skip."""
    target = CACHE.get("from")
    if not target or stage not in STAGE_ORDER or target not in STAGE_ORDER:
        return
    if STAGE_ORDER.index(stage) < STAGE_ORDER.index(target):
        die(f"--from {target}: the {stage} stage is not in {CACHE['dir']} for this project and "
            "these inputs, so there is nothing to start from. Render once without --from to fill "
            "the cache (note that a different ffmpeg build or skill version never reuses one).",
            kind="input")


def sh(script: str, *argv: Any, extra: List[str] = None, stage: str = None) -> str:
    """Run a sibling script, forwarding --fast / --dry-run, returning its printed output path.

    With --cache and a named `stage`, an identical stage that ran before is served from the
    cache instead of re-encoded. `stages_done` is unchanged either way: a cached stage is still
    a stage that happened.
    """
    full = [str(a) for a in argv] + (extra or [])
    dest = full[full.index("-o") + 1] if "-o" in full[:-1] else None
    key = None
    if stage and CACHE.get("dir") and dest:
        inputs = [a for a in full if os.path.exists(a) and a != dest]
        # The destination is where this stage's answer goes, not part of the question: hashing it
        # would make a second run with the first run's output already on disk miss every time.
        key_args = ["<out>" if a == dest else a for a in full]
        key = cache_key(stage, script, key_args, inputs, dest)
        if cache_lookup(stage, key, dest):
            CACHE["hits"].append(stage)
            info(f"→ {script} {stage}: served from --cache")
            # No child ran, so there is no document: say so rather than leaving the PREVIOUS
            # child's document standing, which a caller reading _LAST_DOC would misattribute.
            _LAST_DOC.clear()
            _LAST_DOC["cached"] = True
            return dest
        CACHE["misses"].append(stage)
        _refuse_uncached_earlier_stage(stage)
    elif stage and CACHE.get("dir"):
        CACHE["misses"].append(stage)
    started = time.time()
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
    _LAST_DOC.clear()
    _LAST_DOC.update(doc if isinstance(doc, dict) else {})
    out_path = str(doc.get("output") or "")
    if key:
        cache_store(stage, key, out_path or (dest or ""), time.time() - started)
    return out_path


# ------------------------------------------------------------------ the stage cache (1.17)
#
# Opt-in only: --cache DIR. There is no default directory -- a cache that appears on someone's
# disk without being asked for is a surprise, and this tool's posture is that a plan leaves
# nothing behind.

STAGE_ORDER = ("clips", "audiogram", "join", "silence", "fit", "captions", "graphics",
               "overlays", "audio", "loudness", "export", "chapters")

def _fresh_cache() -> "Dict[str, Any]":
    return {"dir": None, "ffmpeg": None, "hits": [], "misses": [], "saved_seconds": 0.0,
            "entries": 0, "would_hit": [], "from": None}


# Module-level so sh() can reach it without threading a parameter through every stage. main()
# resets it on entry, so two renders in one process (a test session, an embedding caller) do not
# inherit each other's hit/miss lists.
CACHE: Dict[str, Any] = _fresh_cache()


def _content_hash(path: str) -> str:
    """The same cheap content fingerprint batch.py caches on: name, size, mtime, first and last
    MB. Reused rather than reinvented so one file has one identity across the skill."""
    try:
        return file_key(Path(path))
    except (OSError, ValueError):
        return "missing"


def ffmpeg_banner() -> str:
    """The whole `ffprobe -version` first line, not just major.minor.

    Two 7.1.x builds with different libx264 produce different bytes from the same command, and
    the cache exists to hand back bytes. major.minor cannot tell them apart, so the banner --
    which carries the build string and the configuration's version suffix -- is what goes in the
    key. Unreadable falls back to the parsed pair, which still separates the major releases.
    """
    try:
        out = subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=20).stdout
        first = (out or "").strip().splitlines()
        if first:
            return first[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ".".join(str(n) for n in ffmpeg_version())


def cache_key(stage: str, script: str, argv: "Sequence[Any]", inputs: "Sequence[str]",
              dest: "Optional[str]" = None) -> str:
    """sha1 of a canonical description of exactly what this stage is about to do.

    The ffmpeg build banner and the skill version are IN the key, deliberately: a different build
    simply misses rather than being asked to trust an artifact it did not write, and a stage whose
    implementation changed must not serve an old one back.

    `child_args()` is in the key too, and that is not a detail. render.py appends it to every
    stage command AFTER the arguments the stage itself built, and it carries `--fast` -- which
    rewrites the child's preset to veryfast. Without it in the key, `render --cache C --fast`
    stored a draft and the next `render --cache C` served that draft back as the delivery, with
    `cache.hits` presenting it as a legitimate reuse.

    The output's extension is in the key as well (#15): the artifact is stored as `<key><ext>`
    while the sidecar is `<key>.json`, so two runs differing only in container would otherwise
    share one sidecar and invalidate each other on every run.
    """
    payload = {
        "stage": stage, "tool": script,
        "args": [_content_hash(str(a)) if os.path.exists(str(a)) else str(a) for a in argv],
        "inputs": [{"hash": _content_hash(p)} for p in inputs],
        "child": [a for a in child_args() if a != "--dry-run"],
        "codec": STATE.codec, "ext": Path(dest).suffix if dest else None,
        "ffmpeg": CACHE.get("ffmpeg"), "skill": SKILL_VERSION, "contract": CONTRACT_VERSION,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cache_lookup(stage: str, key: str, dest: str) -> bool:
    """Put the cached artifact for `key` at `dest` and return True, or return False on any
    mismatch -- silently, because a miss is not an error, it is just work to do."""
    cdir = CACHE.get("dir")
    if not cdir:
        return False
    side = Path(cdir) / f"{key}.json"
    art = Path(cdir) / f"{key}{Path(dest).suffix or '.bin'}"
    if not (side.exists() and art.exists()):
        return False
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if int(meta.get("size") or -1) != art.stat().st_size:
        return False
    if STATE.dry_run:
        CACHE["would_hit"].append(stage)
        return True
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        if Path(dest).exists():
            Path(dest).unlink()
        os.link(art, dest)          # a hardlink where the filesystem allows it ...
    except OSError:
        shutil.copy2(art, dest)     # ... and a copy where it does not. Never a move: the cache
    CACHE["saved_seconds"] += float(meta.get("seconds") or 0.0)
    return True


def cache_store(stage: str, key: str, produced: str, seconds: float) -> None:
    """Keep `produced` for the next run. Never under --dry-run: a plan writes nothing."""
    cdir = CACHE.get("dir")
    if not cdir or STATE.dry_run or not produced or not os.path.exists(produced):
        return
    art = Path(cdir) / f"{key}{Path(produced).suffix or '.bin'}"
    try:
        shutil.copy2(produced, art)
        Path(cdir, f"{key}.json").write_text(json.dumps({
            "stage": stage, "ffmpeg": CACHE.get("ffmpeg"), "skill": SKILL_VERSION,
            "created": time.time(), "size": art.stat().st_size, "seconds": round(seconds, 2),
            "artifact": art.name}, indent=2), encoding="utf-8")
        CACHE["entries"] += 1
    except OSError as exc:
        info(f"cache: could not store the {stage} artifact ({exc}); the run is unaffected")


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
    soft. A preset that names a delivery frame of the same aspect is that frame.
    The match is 2.2.1's, looser than aspect_ratio(): `16/9` and `1.78:1` still take a 16:9
    preset's size. A render that hands such a frame.aspect to fit.py fails there, as in 2.2.1;
    one whose own fit.aspect replaces it, or that stops before fit, is sized by this match, and
    a patch release does not change a render 2.2.1 completed."""
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


def export_timeline(proj: Dict[str, Any], rel, dest: str) -> int:
    """--export-timeline: the project's cut as an editor timeline, nothing rendered (_common.timeline)."""
    from _common import timeline as tlmod
    fmt = tlmod.FORMATS.get(Path(dest).suffix.lower())
    if not fmt:
        die(f"--export-timeline {dest}: unknown timeline format", kind="input",
            hint="name the file .fcpxml, .edl or .otio")
    paths = [rel(c["src"]) for c in proj.get("clips") or [] if c.get("src")]
    if (proj.get("audio") or {}).get("music"):
        paths.append(rel(proj["audio"]["music"]))
    probes: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        if not os.path.exists(path):
            die(f"timeline source not found: {path}")
        probes[path] = probe(path)  # a timeline needs real durations and rates, dry run or not
    # the sequence frame is the one the render would deliver: an aspect-only frame takes its size
    # from the export preset exactly as the render's own frame does. An export that is not an
    # object names no preset here: 2.2.1's export never read it, and validate_project() refuses
    # it only in the render, which reads it.
    frame = dict(proj.get("frame") or {})
    export = proj.get("export")
    frame_from_preset(frame, export if isinstance(export, dict) else {})
    fit = proj.get("fit")
    if isinstance(fit, dict) and fit.get("aspect") and frame.get("aspect") and aspect_ratio(frame["aspect"]) is None:
        # the render hands fit.py the fit object's own aspect, never this one (only the preset
        # match above reads it), and completes: the sequence is the frame's size without it
        del frame["aspect"]
    try:
        tl = tlmod.build(dict(proj, frame=frame), probes, rel)
    except tlmod.TimelineError as exc:
        die(f"--export-timeline: {exc}", kind="input")
    text = tlmod.WRITERS[fmt](tl)
    report = tlmod.summary(tl, fmt)
    _check_output_path(["ffmpeg", dest])
    _check_existing_output(["ffmpeg", dest])
    verification: List[Dict[str, Any]] = []
    if not STATE.dry_run:
        try:
            Path(dest).write_text(text, encoding="utf-8")
        except OSError as exc:
            die(f"cannot write {dest}: {exc}", kind="output")
        verification.append({"step": "parse", "ok": tlmod.parses(dest, fmt)})
    for line in report["not_exported"]:
        info(f"not exported: {line}")
    info(("[dry-run] would write " if STATE.dry_run else "wrote ") +
         f"{dest} ({fmt}, {report['clips']} clips, {report['duration']}s at {report['rate']} fps)")
    emit(dest, timeline=report, verification=verification)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="project.json, or a plan.json written by <tool> --plan")
    ap.add_argument("--init", metavar="FILE", help="write a starter project file and exit")
    ap.add_argument("--work", help="work directory for intermediates (default: <output>_work)")
    ap.add_argument("--keep", action="store_true", help="keep intermediates (default: kept only when --work is given)")
    ap.add_argument("--cache", metavar="DIR",
                    help="reuse the artifacts of identical stages from a previous run. Opt-in: "
                         "there is no default directory. The ffmpeg version and the skill version "
                         "are part of every key, so a cache never crosses either.")
    ap.add_argument("--from", dest="from_stage", metavar="STAGE",
                    choices=list(STAGE_ORDER),
                    help="start at this stage, taking every earlier one from --cache; refuses if "
                         "one of them is not there")
    ap.add_argument("--export-timeline", metavar="FILE",
                    help="write the project's cut as an editor timeline instead of rendering it: .fcpxml (Final Cut, "
                         "Resolve), .edl (CMX 3600: Premiere, Resolve, Avid) or .otio (OpenTimelineIO); clips, speed, "
                         "transitions, the music bed and chapter markers carry over, everything else is listed as not exported")
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
    validate_project(proj, timeline=bool(args.export_timeline), stop_after=args.stop_after)
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

    if args.export_timeline:
        return export_timeline(proj, rel, args.export_timeline)

    clips = proj.get("clips") or []
    if not clips:
        die("project.clips is empty")
    output = rel(proj.get("output") or "final.mp4")
    # the final stage is a copy from the work dir, so run()'s own guard never sees the sources (review 5)
    refuse_output_is_input(output, *[rel(c.get("src")) for c in clips if c.get("src")])
    # 2.0 refuses an existing output without --overwrite; the final place_output() would, but
    # only after every stage had run -- say so before the first one instead
    _check_existing_output(["ffmpeg", output])
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
    # what the caption stage reported (wrapped/split counts and the fit-size keys), so a caller
    # reading render.py's JSON can see whether the type was shrunk to fit or a cue was split.
    caption_report: Optional[Dict[str, Any]] = None

    CACHE.clear()
    CACHE.update(_fresh_cache())
    if args.cache:
        cdir = Path(args.cache)
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            probe_file = cdir / ".writable"
            probe_file.write_text("", encoding="utf-8")
            probe_file.unlink()
        except OSError as exc:
            die(f"--cache {args.cache}: not a writable directory ({exc})", kind="output")
        CACHE["dir"] = str(cdir)
        CACHE["ffmpeg"] = ffmpeg_banner()
        CACHE["entries"] = len(list(cdir.glob("*.json")))
    CACHE["from"] = args.from_stage
    if args.from_stage and not args.cache:
        die(f"--from {args.from_stage} needs --cache DIR with a previous run's stages: without a "
            "cache there is no earlier artifact to start from, so every stage would run anyway.",
            kind="input")

    # A project may ask for its clip boundaries to land on the music's beat. The measurement and
    # the refusal both live in cut.py -- render forwards the request and reports what came back,
    # so a project that does not name "snap" builds the command line 1.16 built.
    snap_spec = proj.get("snap") or {}
    snap_reports: List[Dict[str, Any]] = []
    if snap_spec and str(snap_spec.get("to") or "") not in ("", "none", "beats"):
        die(f'snap.to: only "beats" (or "none") is a beat grid this skill can measure, got '
            f'{snap_spec.get("to")!r}', kind="input")

    # ---- clips
    # 2.2.1: every clip source is checked before the first one is cut, and every problem is named
    # in one refusal -- before, clip 7's missing file surfaced after clips 0-6 had been cut, and
    # only the first of several missing sources was reported per run.
    problems: List[Dict[str, Any]] = []
    for i, c in enumerate(clips):
        src = rel(c["src"])
        if not os.path.exists(src):  # under --dry-run too: a plan for a missing file is no plan
            problems.append({"index": i, "path": src, "reason": "missing"})
        elif os.path.isdir(src):
            problems.append({"index": i, "path": src, "reason": "a directory, not a file"})
        elif os.path.getsize(src) == 0:
            problems.append({"index": i, "path": src, "reason": "empty (0 bytes)"})
        elif not STATE.dry_run:
            # 2.2.4: readable, too -- one ffprobe per source, nothing decoded, the same test
            # join.py's preflight makes. Before, a real run probed the sources one by one and
            # stopped at the first unreadable file; the dry run already named every one via join.
            proc = run([require_tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0", src], quiet=True, check=False)
            kinds = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
            if proc.returncode != 0 or not kinds & {"audio", "video"}:
                first = ((proc.stderr or "").strip().splitlines() or ["no audio or video stream"])[-1]
                problems.append({"index": i, "path": src, "reason": f"unreadable: {first}"})
    if problems:
        die(f"{len(problems)} of {len(clips)} clip sources unusable: "
            + "; ".join(f"clip {p['index']}: {p['reason']}: {p['path']}" for p in problems),
            kind="input", problems=problems,
            hint="fix or remove these clips in the project; nothing was cut")

    parts: List[str] = []
    for i, c in enumerate(clips):
        src = rel(c["src"])
        needs_cut = c.get("in") is not None or c.get("out") is not None
        part = str(work / f"clip{i:02d}{mid}")
        if needs_cut:
            argv: List[Any] = [src, "-o", part, "--accurate"]
            if c.get("in") is not None:
                argv += ["--start", c["in"]]
            if c.get("out") is not None:
                argv += ["--end", c["out"]]
            clip_snap = dict(snap_spec)
            clip_snap.update(c.get("snap") or {})
            if str(clip_snap.get("to") or "none") == "beats":
                argv += ["--snap", "beats"]
                if clip_snap.get("tolerance") is not None:
                    argv += ["--snap-tolerance", str(clip_snap["tolerance"])]
                if clip_snap.get("min_confidence") is not None:
                    argv += ["--min-confidence", str(clip_snap["min_confidence"])]
                if clip_snap.get("source"):
                    argv += ["--snap-source", rel(clip_snap["source"])]
            sh("cut.py", *argv, stage="clips")
            if _LAST_DOC.get("snap"):
                snap_reports.append({"clip": i, **_LAST_DOC["snap"]})
            elif _LAST_DOC.get("cached") and str(clip_snap.get("to") or "none") == "beats":
                # The cut is the one the cache holds, so it WAS snapped -- the moves are simply
                # not re-measured. Saying `snap: null` here would report the opposite.
                snap_reports.append({"clip": i, "mode": "beats", "source": "cache",
                                     "note": "this clip came from --cache; it was snapped when "
                                             "it was first rendered and the moves are in that "
                                             "run's result"})
        else:
            part = src
        if c.get("speed"):
            spd = float(c["speed"])
            if not (spd > 0) or spd != spd or spd == float("inf"):
                die(f"clip {i}: speed must be a positive number, got {c['speed']!r}")
            if abs(spd - 1.0) > 1e-6:  # speed 1.0 used to cost a full re-encode for nothing
                dur = (probe(part).get("duration") or 0.0) if not STATE.dry_run else 10.0
                fitted = str(work / f"clip{i:02d}_speed{mid}")
                sh("fit.py", part, "--duration", f"{dur / spd:.3f}", "-o", fitted, stage="clips")
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
        sh("waveform.py", *argv, stage="audiogram")
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
        sh("join.py", *argv, stage="join")
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
        sh("silence.py", *argv, stage="silence")
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
    # Several clips were joined by join.py: into frame.width x frame.height when the frame gives
    # both, else at the FIRST clip's aspect. A frame of an aspect and ONE side then reached fit.py
    # as the aspect alone, which fit.py bounds by the joined picture: {aspect 9:16, width 1080}
    # over two 16:9 clips rendered 342x608, where one clip (and --export-timeline's sequence) is
    # 1080x1920. Only that case gets the frame's side. A frame with both sides is already the
    # join's size, and a project fit object with its own width, height or another aspect renders
    # as 2.2.1 rendered it: filling the frame's sides in there overrode the fit object's aspect
    # (fit {width 540} under a 1080x1920 frame came out 540x1920).
    own = proj.get("fit") or {}
    one_side = bool(frame.get("width")) != bool(frame.get("height"))
    sized = len(parts) == 1 or bool(frame.get("aspect") and one_side and not own.get("width") and not own.get("height")
                                    and own.get("aspect") in (None, frame.get("aspect")))
    if frame.get("width") and sized:
        fit.setdefault("width", frame["width"])
    if frame.get("height") and sized:
        fit.setdefault("height", frame["height"])
    if frame.get("fps") and len(parts) == 1:
        fit.setdefault("fps", frame["fps"])
    if fit:
        nxt = str(work / f"fit{mid}")
        argv = [current, "-o", nxt]
        for k, flag in (("duration", "--duration"), ("method", "--method"), ("aspect", "--aspect"), ("fit", "--fit"), ("width", "--width"), ("height", "--height"), ("fps", "--fps"), ("smooth", "--smooth")):
            if fit.get(k) is not None:
                argv += [flag, str(fit[k])]
        sh("fit.py", *argv, stage="fit")
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
        for k, flag in (("font", "--font"), ("size", "--size"), ("color", "--color"), ("position", "--position"), ("margin", "--margin"), ("animate", "--animate"), ("highlight_color", "--highlight-color"), ("outline", "--outline"), ("lang", "--lang"), ("offset", "--offset"), ("max_lines", "--max-lines"), ("min_duration", "--min-duration"),
                        ("fit_size", "--fit-size"), ("min_size", "--min-size"), ("fit_size_scope", "--fit-size-scope")):
            if cap.get(k) is not None:
                argv += [flag, str(cap[k])]
        for k, flag in (("karaoke", "--karaoke"), ("bold", "--bold"), ("box", "--box")):
            if cap.get(k):
                argv.append(flag)
        sh("caption.py", *(argv + brand_args + platform_args), stage="captions")
        if isinstance(_LAST_DOC.get("caption"), dict):
            caption_report = dict(_LAST_DOC["caption"])
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
        sh("graphics.py", *(argv + brand_args + ([] if g.get("platform") else platform_args)), stage="graphics")
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
        sh("overlay.py", *(argv + brand_args + ([] if ov.get("platform") else platform_args)), stage="overlays")
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
        sh("audio.py", *argv, stage="audio")
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
        sh("loudness.py", *argv, stage="loudness")
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
        sh("export.py", *argv, stage="export")
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
        sh("metadata.py", output, "--chapters", chapter_file, "-o", tagged, stage="chapters")
        if not STATE.dry_run:
            place_output(tagged, output)
        stages_done.append("chapters")

    # ---- check
    ck = proj.get("check")
    check_result = None
    exit_code = 0
    if ck and ck.get("platform") and not STATE.dry_run:
        proc = run_tool([str(HERE / "check.py"), output, "--platform", ck["platform"], "--json"]
                        + (["--content"] if ck.get("content") is True else []) + child_args())
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
        shutil.rmtree(work, ignore_errors=True)
    if exit_code:
        # The deliverable is written and verified, but it does not meet the requested platform
        # spec (or the check itself could not run): a failed delivery, reported as one.
        failed_rows = [r["check"] for r in (check_result or {}).get("checks", []) if r.get("status") == "FAIL"]
        die(f"rendered {output} but the {ck['platform']} check failed" + (f": {', '.join(failed_rows)}" if failed_rows else ""),
            kind="verification", output=output, dry_run=STATE.dry_run, stages=stages_done, check=check_result,
            probe=probe(output, role="output"))
    info(f"rendered {output} via {' → '.join(stages_done)}")
    cache_report = None
    if args.cache:
        cache_report = {"dir": CACHE["dir"], "ffmpeg": CACHE["ffmpeg"],
                        "hits": CACHE["hits"], "misses": CACHE["misses"],
                        "saved_seconds": round(CACHE["saved_seconds"], 1),
                        "entries": CACHE["entries"]}
        if STATE.dry_run:
            cache_report["would_hit"] = CACHE["would_hit"]
        info(f"cache: {len(CACHE['hits'])} hit(s) ({', '.join(CACHE['hits']) or '-'}), "
             f"{len(CACHE['misses'])} miss(es) ({', '.join(CACHE['misses']) or '-'})")
    # One entry per snapped clip, `clip` naming which. A single-clip project keeps the shape a
    # caller reads today by also carrying the first entry's keys at the top level.
    snap_report: Optional[Dict[str, Any]] = None
    if snap_reports:
        snap_report = dict(snap_reports[0])
        snap_report["clips"] = snap_reports
    emit(output, stages=stages_done, check=check_result, snap=snap_report, cache=cache_report,
         caption=caption_report,
         verification=[{"step": "check", "ok": True, "platform": ck["platform"]}] if check_result else [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
