#!/usr/bin/env python3
"""Build a review page for a render project: the plan, the result, and fields to re-edit it.

    python3 scripts/_review.py project.json [--result render.json] [-o project.review] [--overwrite]
    npx ffmpeg-skill review project.json [--result render.json]

Standalone use only (#633): this is not one of the contract's tools and the MCP server does not
list it, so a caller that owns the review (Velisa) never reaches it. It writes a folder with an
index.html and the stills it shows; the page needs no network and runs nothing. "Save project"
in the page saves the edited project JSON; rendering it again is `render.py` as usual.

The page is an editor-style screen (sources with their probe facts, the work steps, a viewer that
plays the output, a timeline with clips, cues and the sound, the measured rows against what was
expected) in which every element has a number; pressing one adds a row to an instruction for an
agent, and each tool's own flags come from the contract. Its markup is `_review.html`; this file
measures and embeds one JSON document: each clip's stills at its in point, middle and out point,
ffprobe's facts about each source, the stages of `render.py --dry-run --json`, and (with --result,
the `render.py --json` document of a run) that document, stills and a waveform of the output. A
still that ffmpeg could not write is left out and says so; nothing is guessed.
"""
import argparse
import json
import os
import shlex
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common.runner import found_exe  # noqa: E402
from _common.decision import parse_time  # noqa: E402
from _common.asr import parse_srt  # noqa: E402
from _platforms import PLATFORMS  # noqa: E402


SOURCES: "set[str]" = set()  # every media path the project or the result names, resolved
BASE = Path.cwd()             # the project's folder, set in main(): a relative output is read from there
STILLS = "stills"             # the stills live in a folder of their own, which only this tool writes
STILLS_MARK = ".ffmpeg-skill-review-stills"
STILL_TIMEOUT = 120  # seconds for one still or one probe: a stalled read is a missing still, not a hang


def is_input(path) -> bool:  # by name and by file identity: a hard link to an input has another name
    return os.path.realpath(path) in SOURCES or (os.path.exists(path) and any(os.path.samefile(path, s) for s in SOURCES))


def shot(out: Path, *args: str) -> bool:
    """One picture written by ffmpeg to `out`; False when ffmpeg could not write it. An earlier
    run's picture is removed first, so a seek that writes nothing is a missing still, not an old
    picture; a name that is a source of this project is never written (review of #636)."""
    if is_input(out):
        return False
    out.unlink(missing_ok=True)
    try:
        proc = subprocess.run([found_exe("ffmpeg"), "-v", "error", "-y", *args, str(out)], capture_output=True, timeout=STILL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out.is_file() and out.stat().st_size > 0


def still(folder: Path, name: str, src: str, at: "float | None") -> "str | None":
    """A 320 px wide JPEG of `src` at `at` seconds, as the name the page loads, or None."""
    ok = at is not None and shot(folder / STILLS / name, "-ss", f"{max(at, 0):.3f}", "-i", src, "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4")
    return f"{STILLS}/{name}" if ok else None


def write_new(path: Path, text: str) -> None:
    """Write `path` as a new file: into a temporary file created beside it, then renamed over it.
    Writing in place followed a symlink or a hard link at that name into whatever it pointed to (a
    project input), and truncated it; a rename replaces the name only. The temporary file is
    created exclusively, so a link already standing at a guessable name is never written through
    either (review of #636)."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o644)  # mkstemp makes it owner-only; a page and its marker are ordinary files
    os.replace(tmp, path)


def facts(src: str) -> dict:
    """ffprobe's own words about `src` (format duration, each stream's codec, size, rate), or {}."""
    try:
        proc = subprocess.run([found_exe("ffprobe"), "-v", "error", "-show_entries",
                               "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate", "-of", "json", src],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=STILL_TIMEOUT)
        doc = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def length(doc: dict) -> "tuple[float | None, float]":
    """The source's duration (None when unknown) and its frame rate (30 when unknown), which a
    frame-based time such as 00:00:05:45 is read at."""
    try:
        duration = float((doc.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    try:
        video = [s for s in doc.get("streams") or [] if s.get("codec_type") == "video"]
        num, den = ((video or [{}])[0].get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    return duration, fps or 30.0


def seconds(value, fps: float = 30.0) -> "float | None":
    try:  # a null bound reads as "None", which is not a time
        return float(parse_time(str(value), fps))
    except (ValueError, TypeError):
        return None


def clips_and_sources(project: dict, folder: Path) -> "tuple[list, list]":
    """Each clip with its bounds in seconds and its three stills, and each distinct source file
    with what ffprobe says about it."""
    sources, clips, seen = [], [], {}
    for i, clip in enumerate(project.get("clips") or []):
        src = str(clip.get("src", ""))
        path = src if os.path.isabs(src) else str(BASE / src)
        if path not in seen:
            seen[path] = len(sources)
            sources.append({"path": src, "probe": facts(path)})
        total, fps = length(sources[seen[path]]["probe"])
        start = seconds(clip.get("in"), fps) or 0.0
        end = seconds(clip.get("out"), fps)
        end = end if end is not None else total
        at = [] if end is None else [start, (start + end) / 2, max(end - 0.05, start)]
        clips.append({"s": seen[path], "a": start, "b": end, "stills": [still(folder, f"clip{i}_{k}.jpg", path, t) for k, t in enumerate(at)]})
    return clips, sources


def output_media(result: dict, folder: Path) -> dict:
    """The rendered file as the page plays it, six stills of it and a picture of its sound.
    Read where the safety check read it (the project's folder), never against the caller's cwd."""
    path, dur = result.get("output"), (result.get("probe") or {}).get("duration")
    path = str((BASE / path).resolve()) if path else None
    if not (path and os.path.isfile(path)):
        return {"video": None, "stills": [], "wave": None}
    wave = (result.get("probe") or {}).get("audio") and shot(folder / STILLS / "wave.png", "-i", path, "-filter_complex",
                                                             "showwavespic=s=2400x96:colors=0xa3a9b4:scale=sqrt", "-frames:v", "1")
    return {"video": Path(path).as_uri(), "wave": f"{STILLS}/wave.png" if wave else None,
            "stills": [{"t": dur * (k + 0.5) / 6, "file": still(folder, f"out_{k}.jpg", path, dur * (k + 0.5) / 6)} for k in range(6)] if dur else []}


def cues(project: dict, result: "dict | None") -> "tuple[str | None, list]":
    """The cue file the captions came from (the run's delivered .srt, else the project's own) and
    its cues; a file that cannot be read is no cues, which the page shows as no caption track."""
    caps = project.get("captions") if isinstance(project.get("captions"), dict) else {}
    name = (result or {}).get("caption_srt") or next((v for v in (caps.get("srt"), caps.get("text")) if isinstance(v, str)
                                                      and v.lower().endswith((".srt", ".vtt"))), None)
    try:
        return name, [list(c) for c in parse_srt(str(BASE / name))] if name else []
    except (SystemExit, OSError, ValueError):
        return name, []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="the render.py project JSON")
    ap.add_argument("--result", help="the render.py --json document of a run of this project")
    ap.add_argument("-o", "--output", help="the folder to write (default: <project>.review next to the project)")
    ap.add_argument("--overwrite", action="store_true", help="replace a review page already in that folder")
    a = ap.parse_args(argv)
    proj_path = Path(a.project).resolve()
    try:
        project = json.loads(proj_path.read_text(encoding="utf-8"))
        result = json.loads(Path(a.result).read_text(encoding="utf-8")) if a.result else None
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    global BASE
    BASE = proj_path.parent
    folder = Path(a.output).resolve() if a.output else proj_path.with_suffix(".review")
    if folder == proj_path:  # a project named x.review: its folder cannot be the project itself
        folder = proj_path.with_name(proj_path.name + "-review")
    if (folder / "index.html").exists() and not a.overwrite:
        print(f"error: {folder / 'index.html'} exists; pass --overwrite to replace it", file=sys.stderr)
        return 1
    if folder.exists() and not folder.is_dir():
        print(f"error: {folder} exists and is not a folder", file=sys.stderr)
        return 1
    if folder.is_dir() and not (folder / "index.html").exists() and any(folder.iterdir()):
        # a folder of other files (a media folder given as -o) is not a review folder: its files
        # could share a still's name (review of #636)
        print(f"error: {folder} holds other files and no review page; give an empty or new folder", file=sys.stderr)
        return 1
    # every string in the project that names a file (a clip, an overlay, a cue file, music) and
    # the result's output: none of them may be in the stills folder (review of #636)
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, (dict, list)):
            for v in (value.values() if isinstance(value, dict) else value):
                yield from strings(v)
    for text in list(strings(project)) + ([str(result["output"])] if result and result.get("output") else []):
        try:
            candidate = Path(text) if os.path.isabs(text) else proj_path.parent / text
            if candidate.exists():
                SOURCES.add(os.path.realpath(candidate))
        except (OSError, ValueError):
            continue  # literal text (an overlay line, a title) that cannot be a file name
    # the two documents this run reads are inputs too
    SOURCES.update(os.path.realpath(p) for p in [proj_path] + ([a.result] if a.result else []))
    # nothing is written over an input: not the page, not a still (checked before any write)
    if is_input(folder / "index.html"):
        print(f"error: {folder / 'index.html'} is an input of this run; give another -o", file=sys.stderr)
        return 1
    stills = folder / STILLS
    if os.path.lexists(stills):
        # only a stills folder this tool made is cleared; anything else in its place is someone's
        mark = stills / STILLS_MARK
        if not (stills.is_dir() and not stills.is_symlink() and mark.is_file() and not mark.is_symlink()):
            print(f"error: {stills} exists and was not made by the review page; move it or give another -o", file=sys.stderr)
            return 1
        inside = [p for p in SOURCES if Path(p).is_relative_to(stills.resolve())]
        if inside:
            print(f"error: the project uses {inside[0]}, which is in {stills}; give another -o", file=sys.stderr)
            return 1
        # only this tool's stills are removed, one by one: never the folder, never another file in it
        for entry in stills.iterdir():
            if (re.fullmatch(r"(clip\d+_\d|out_\d)\.jpg|wave\.png", entry.name) and entry.is_file() and not entry.is_symlink()
                    and not is_input(entry)):
                entry.unlink()
    stills.mkdir(parents=True, exist_ok=True)
    write_new(stills / STILLS_MARK, "made by scripts/_review.py; cleared on each run\n")
    # a dry run writes nothing, so --overwrite only keeps an output from an earlier run from refusing it
    dry = subprocess.run([sys.executable, str(HERE / "render.py"), str(proj_path), "--dry-run", "--overwrite", "--json"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(proj_path.parent))
    try:
        doc = json.loads(dry.stdout)
        stages, note = ((doc.get("stages") or [], "") if doc.get("status") == "completed"
                        else ([], "the dry run failed: " + str((doc.get("error") or {}).get("message", "no message"))))
    except ValueError:
        stages, note = [], "the dry run did not complete: " + (dry.stderr.strip().splitlines() or ["no message"])[-1]
    contract = subprocess.run([sys.executable, str(HERE / "_contract.py"), "--json", "--static"], capture_output=True, text=True, encoding="utf-8")
    clips, sources = clips_and_sources(project, folder)
    cue_file, cue_list = cues(project, result)
    data = {"name": proj_path.name, "project_path": str(proj_path), "project": project, "result": result, "stages": stages, "stages_note": note,
            "clips": clips, "sources": sources, "cue_file": cue_file, "cues": cue_list, "out": output_media(result or {}, folder),
            "safe": {k: v["safe"] for k, v in PLATFORMS.items() if v.get("safe")},
            "tools": {t["name"]: {"d": t["description"], "p": t["input_schema"]["properties"]} for t in json.loads(contract.stdout)["tools"]},
            # runnable from anywhere: this copy's render.py, both paths quoted for a shell
            "run": f"python3 {shlex.quote(str(HERE / 'render.py'))} {shlex.quote(str(proj_path))} --overwrite --json"}
    # the page is the template with this one document in it, as a script's own value (the page never
    # reads its data back out of the DOM); no "<" of the data reaches the HTML parser
    page = (HERE / "_review.html").read_text(encoding="utf-8").replace("/*DATA*/", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"), 1)
    write_new(folder / "index.html", page)
    print(folder / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
