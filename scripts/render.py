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
  "audio": {"voice": true, "music": "bed.mp3", "music_volume": -16, "duck": true, "music_fade_out": 2},
  "loudness": {"lufs": -14, "tp": -1},
  "fit": {"duration": 60},
  "export": {"preset": "reels"},
  "check": {"platform": "reels"}
}

Stages run in this order: clips (cut) → join → silence → fit → captions →
graphics → overlays → audio → loudness → export → check. Missing stages are
skipped. "brand" points caption/graphics/overlay at a brand.json (fonts,
colours, logo, safe margin); {"logo": true} in overlays places the brand logo.

Examples:
  python3 render.py --init project.json          # write a commented starter project
  python3 render.py project.json                 # render
  python3 render.py project.json --dry-run       # show every command without rendering
  python3 render.py project.json --fast          # preview quality
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from _common import STATE, add_common, apply_common, die, emit, info, probe

HERE = Path(__file__).resolve().parent

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
    "export": {"preset": "youtube"},
    "check": {"platform": "youtube"},
}


def sh(script: str, *argv: Any, extra: List[str] = None) -> str:
    """Run a sibling script, forwarding --fast / --dry-run, returning its printed output path."""
    cmd = [sys.executable, str(HERE / script)] + [str(a) for a in argv] + (extra or [])
    if STATE["fast"]:
        cmd.append("--fast")
    if STATE["dry_run"]:
        cmd.append("--dry-run")
    info("→ " + " ".join(os.path.basename(c) if i < 2 else c for i, c in enumerate(cmd)))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stderr.splitlines():
        if line.startswith("$ ") or line.startswith("[dry-run]"):
            STATE["commands"].append(line[2:] if line.startswith("$ ") else line)
        elif line.strip():
            info("    " + line)
    if proc.returncode != 0:
        die(f"{script} failed")
    out = proc.stdout.strip().splitlines()
    return out[-1] if out else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="project.json")
    ap.add_argument("--init", metavar="FILE", help="write a starter project file and exit")
    ap.add_argument("--work", help="work directory for intermediates (default: <output>_work)")
    ap.add_argument("--keep", action="store_true", help="keep intermediates (default: kept only when --work is given)")
    ap.add_argument("--stop-after", choices=["clips", "join", "silence", "fit", "captions", "graphics", "overlays", "audio", "loudness", "export"], help="stop after this stage (for iterating)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.init:
        Path(args.init).write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
        info(f"wrote {args.init}; edit clips/src and run: render.py {args.init}")
        print(args.init)
        return 0
    if not args.project:
        die("give a project.json (or --init FILE)")
    try:
        proj: Dict[str, Any] = json.loads(Path(args.project).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read project: {exc}")
    base = Path(args.project).resolve().parent

    def rel(p: Any) -> str:
        p = str(p)
        return p if os.path.isabs(p) else str(base / p)

    clips = proj.get("clips") or []
    if not clips:
        die("project.clips is empty")
    output = rel(proj.get("output") or "final.mp4")
    work = Path(args.work) if args.work else Path(str(Path(output).with_suffix("")) + "_work")
    work.mkdir(parents=True, exist_ok=True)
    frame = proj.get("frame") or {}
    trans = proj.get("transition") or {}
    brand_args: List[str] = ["--brand", rel(proj["brand"])] if proj.get("brand") else []
    stages_done: List[str] = []

    # ---- clips
    parts: List[str] = []
    for i, c in enumerate(clips):
        src = rel(c["src"])
        if not STATE["dry_run"]:
            probe(src)
        needs_cut = c.get("in") is not None or c.get("out") is not None
        part = str(work / f"clip{i:02d}.mp4")
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
            dur = (probe(part).get("duration") or 0.0) if not STATE["dry_run"] else 10.0
            fitted = str(work / f"clip{i:02d}_speed.mp4")
            sh("fit.py", part, "--duration", f"{dur / spd:.3f}", "-o", fitted)
            part = fitted
        parts.append(part)
    stages_done.append("clips")
    current = parts[0]
    if args.stop_after == "clips":
        emit(current, stages=stages_done)
        return 0

    # ---- join
    if len(parts) > 1:
        current = str(work / "joined.mp4")
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
        nxt = str(work / "tight.mp4")
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
    if frame.get("width") and len(parts) == 1:
        fit.setdefault("width", frame["width"])
    if frame.get("fps") and len(parts) == 1:
        fit.setdefault("fps", frame["fps"])
    if fit:
        nxt = str(work / "fit.mp4")
        argv = [current, "-o", nxt]
        for k, flag in (("duration", "--duration"), ("method", "--method"), ("aspect", "--aspect"), ("fit", "--fit"), ("width", "--width"), ("fps", "--fps"), ("smooth", "--smooth")):
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
        nxt = str(work / "captioned.mp4")
        argv = [current, "-o", nxt]
        if cap.get("text"):
            argv += ["--text", rel(cap["text"])]
        elif cap.get("srt"):
            argv += ["--srt", rel(cap["srt"])]
        elif cap.get("ass"):
            argv += ["--ass", rel(cap["ass"])]
        else:
            die("captions needs text, srt or ass")
        for k, flag in (("font", "--font"), ("size", "--size"), ("color", "--color"), ("position", "--position"), ("margin", "--margin"), ("animate", "--animate"), ("highlight_color", "--highlight-color"), ("outline", "--outline")):
            if cap.get(k) is not None:
                argv += [flag, str(cap[k])]
        for k, flag in (("karaoke", "--karaoke"), ("bold", "--bold"), ("box", "--box")):
            if cap.get(k):
                argv.append(flag)
        sh("caption.py", *(argv + brand_args))
        current = nxt
        stages_done.append("captions")
    if args.stop_after == "captions":
        emit(current, stages=stages_done)
        return 0

    # ---- graphics
    for i, g in enumerate(proj.get("graphics") or []):
        nxt = str(work / f"graphics{i:02d}.mp4")
        if not g.get("template"):
            die(f"graphics[{i}] needs a template")
        argv = [current, "-o", nxt, "--template", g["template"]]
        for k, flag in (("name", "--name"), ("title", "--title"), ("subtitle", "--subtitle"), ("start", "--start"), ("end", "--end"), ("position", "--position"), ("from", "--from"), ("scale", "--scale"), ("primary", "--primary"), ("text_color", "--text-color")):
            if g.get(k) is not None:
                argv += [flag, str(g[k])]
        sh("graphics.py", *(argv + brand_args))
        current = nxt
        if "graphics" not in stages_done:
            stages_done.append("graphics")
    if args.stop_after == "graphics":
        emit(current, stages=stages_done)
        return 0

    # ---- overlays
    for i, ov in enumerate(proj.get("overlays") or []):
        nxt = str(work / f"overlay{i:02d}.mp4")
        argv = [current, "-o", nxt]
        if ov.get("logo"):
            argv.append("--logo")
        elif ov.get("image"):
            argv += ["--image", rel(ov["image"])]
        elif ov.get("text"):
            argv += ["--text", ov["text"]]
        else:
            die(f"overlays[{i}] needs image or text")
        for k, flag in (("position", "--position"), ("start", "--start"), ("end", "--end"), ("fade", "--fade"), ("opacity", "--opacity"), ("scale", "--scale"), ("font_size", "--font-size"), ("font", "--font"), ("font_file", "--font-file"), ("margin", "--margin")):
            if ov.get(k) is not None:
                argv += [flag, str(ov[k])]
        if ov.get("box"):
            argv.append("--box")
        sh("overlay.py", *(argv + brand_args))
        current = nxt
        if "overlays" not in stages_done:
            stages_done.append("overlays")
    if args.stop_after == "overlays":
        emit(current, stages=stages_done)
        return 0

    # ---- audio
    au = proj.get("audio")
    if au:
        nxt = str(work / "audio.mp4")
        argv = [current, "-o", nxt]
        for k, flag in (("music", "--music"), ("replace", "--replace")):
            if au.get(k):
                argv += [flag, rel(au[k])]
        for k, flag in (("music_volume", "--music-volume"), ("fade_in", "--fade-in"), ("fade_out", "--fade-out"), ("music_fade_out", "--music-fade-out"), ("gain", "--gain"), ("duck_amount", "--duck-amount")):
            if au.get(k) is not None:
                argv += [flag, str(au[k])]
        for k, flag in (("voice", "--voice"), ("denoise", "--denoise"), ("duck", "--duck"), ("music_loop", "--music-loop"), ("stereo", "--stereo"), ("mono", "--mono"), ("downmix", "--downmix")):
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
        nxt = str(work / "loudnorm.mp4")
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
        sh("export.py", *argv)
        stages_done.append("export")
    else:
        if not STATE["dry_run"]:
            import shutil
            shutil.copyfile(current, output)
        info(f"copied final stage to {output}")
    current = output

    # ---- check
    ck = proj.get("check")
    check_result = None
    if ck and ck.get("platform") and not STATE["dry_run"]:
        proc = subprocess.run([sys.executable, str(HERE / "check.py"), output, "--platform", ck["platform"], "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            check_result = json.loads(proc.stdout)
        except ValueError:
            check_result = {"error": proc.stderr.strip()[-300:]}
        if check_result.get("failed"):
            info(f"check: {check_result['failed']} FAIL — " + "; ".join(f"{r['check']}={r['value']} ({r['fix']})" for r in check_result["checks"] if r["status"] == "FAIL"))
        else:
            info(f"check: OK for {ck['platform']}")
        stages_done.append("check")

    if not args.keep and not args.work and not STATE["dry_run"]:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    info(f"rendered {output} via {' → '.join(stages_done)}")
    emit(output, stages=stages_done, check=check_result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
