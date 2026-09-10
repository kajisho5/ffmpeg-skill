#!/usr/bin/env python3
"""Apply the same recipe to every file in a folder, with a content-hash cache
so re-runs only process what changed. A recipe is a list of script steps;
{in} and {out} are substituted, and the output of one step feeds the next.

Recipe (batch.json):
{
  "glob": "*.mp4",
  "output_dir": "out",
  "suffix": "_final",
  "steps": [
    ["silence.py", "{in}", "--threshold", "-38", "-o", "{out}"],
    ["loudness.py", "{in}", "-o", "{out}"],
    ["export.py", "{in}", "--preset", "youtube", "-o", "{out}"]
  ]
}
or use a render project for every file:  {"project": "project.json", "clip_key": 0}

Examples:
  python3 batch.py ~/Footage --recipe batch.json
  python3 batch.py ~/Footage --recipe batch.json --dry-run
  python3 batch.py ~/Footage --recipe batch.json --force        # ignore the cache
  python3 batch.py ~/Footage --recipe batch.json --watch 30     # poll the folder every 30 s
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from _common import STATE, add_common, apply_common, die, emit, info

HERE = Path(__file__).resolve().parent
MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mxf", ".wav", ".m4a", ".mp3", ".flac"}
# recipe steps name the script to run as plain, untrusted JSON -- run_step() joins it onto HERE
# with the `/` operator, which silently ignores the left side when the right side is itself an
# absolute path (Path("/scripts") / "/tmp/evil.py" == Path("/tmp/evil.py")), and does nothing to
# stop a "../" traversal either. Without this allowlist, a batch.json a caller didn't author
# themselves (from a template, a shared config, anywhere) could name any Python file on disk and
# have it executed with the caller's own privileges on every matching media file.
ALLOWED_STEP_SCRIPTS = {p.name for p in HERE.glob("*.py") if not p.name.startswith("_")}


def file_key(path: Path) -> str:
    st = path.stat()
    h = hashlib.sha1()
    h.update(f"{path.name}|{st.st_size}|{int(st.st_mtime)}".encode())
    with open(path, "rb") as fh:  # first and last MB: cheap and good enough to detect changes
        h.update(fh.read(1 << 20))
        if st.st_size > 2 << 20:
            fh.seek(-(1 << 20), os.SEEK_END)
            h.update(fh.read(1 << 20))
    return h.hexdigest()


def recipe_key(recipe: Dict[str, Any]) -> str:
    # A "project" recipe is just {"project": "<path>", "clip_key": N} -- the actual settings
    # (export preset, captions, everything) live in the file at that path, not in this dict.
    # Hashing only `recipe` meant editing project.json's content (without touching batch.json
    # itself) left the key, and so every cache hit, unchanged: a preset swapped from "copy" to
    # "x" (a real re-encode) still served the old cached output. Fold the referenced file's own
    # content into the key so a content change invalidates the cache like any other edit would.
    project_content = ""
    if recipe.get("project"):
        try:
            project_content = Path(recipe["project"]).read_text(encoding="utf-8")
        except OSError:
            pass
    return hashlib.sha1((json.dumps(recipe, sort_keys=True) + "\0" + project_content).encode()).hexdigest()[:12]


def run_step(argv: List[str]) -> bool:
    script = argv[0]
    if script not in ALLOWED_STEP_SCRIPTS:
        die(f"recipe step names a script that isn't one of this skill's own tools: {script!r} "
            f"(must be a bare filename like 'silence.py', found in scripts/)")
    cmd = [sys.executable, str(HERE / script)] + argv[1:]
    if STATE["fast"]:
        cmd.append("--fast")
    if STATE["dry_run"]:
        cmd.append("--dry-run")
    info("  → " + " ".join(os.path.basename(c) if i < 2 else c for i, c in enumerate(cmd)))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        info("    " + "\n    ".join(proc.stderr.strip().splitlines()[-4:]))
        return False
    return True


def final_path(src: Path, recipe: Dict[str, Any], outdir: Path) -> Path:
    suffix = recipe.get("suffix", "_out")
    # By default final_ext falls back to each source's OWN extension, so files that only differ
    # by extension don't collide -- but a recipe that fixes "ext" (e.g. converting a folder of
    # mixed .mp4/.mov masters to one format) makes every source with the same stem land on the
    # same final path, e.g. clip.mp4 and clip.mov both -> clip_out.mp4. process() has no collision
    # detection of its own; see one_pass()'s pre-flight check, which uses this same computation
    # to catch that before any file is actually processed (and the earlier one silently clobbered).
    final_ext = recipe.get("ext") or src.suffix.lstrip(".") or "mp4"
    return outdir / f"{src.stem}{suffix}.{final_ext}"


def process(src: Path, recipe: Dict[str, Any], outdir: Path, work: Path) -> Dict[str, Any]:
    final = final_path(src, recipe, outdir)
    t0 = time.time()
    if recipe.get("project"):
        proj = json.loads(Path(recipe["project"]).read_text(encoding="utf-8"))
        idx = int(recipe.get("clip_key", 0))
        proj.setdefault("clips", [{}])
        while len(proj["clips"]) <= idx:
            proj["clips"].append({})
        proj["clips"][idx]["src"] = str(src.resolve())
        proj["output"] = str(final.resolve())
        pj = work / f"{src.stem}_project.json"
        pj.write_text(json.dumps(proj, indent=2), encoding="utf-8")
        ok = run_step(["render.py", str(pj)])
    else:
        steps = recipe.get("steps") or []
        if not steps:
            die("recipe needs steps or project")
        cur = str(src)
        ok = True
        for i, step in enumerate(steps):
            last = i == len(steps) - 1
            out = str(final) if last else str(work / f"{src.stem}_step{i}.{'mp4' if src.suffix.lower() not in ('.wav', '.mp3', '.m4a', '.flac') else src.suffix.lstrip('.')}")
            argv = [str(a).replace("{in}", cur).replace("{out}", out) for a in step]
            if not run_step(argv):
                ok = False
                break
            cur = out
    return {"file": str(src), "output": str(final), "ok": ok, "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--recipe", required=True, help="batch.json")
    ap.add_argument("--force", action="store_true", help="ignore the cache and redo everything")
    ap.add_argument("--watch", type=float, help="keep polling the folder every N seconds")
    ap.add_argument("--work", help="work directory for intermediates (default: <output_dir>/.work)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    folder = Path(args.folder)
    if not folder.is_dir():
        die(f"not a folder: {folder}")
    try:
        recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read recipe: {exc}")
    if recipe.get("project") and not os.path.isabs(recipe["project"]):
        recipe["project"] = str((Path(args.recipe).resolve().parent / recipe["project"]))
    outdir = Path(recipe.get("output_dir") or (folder / "out"))
    if not outdir.is_absolute():
        outdir = folder / outdir
    work = Path(args.work) if args.work else outdir / ".work"
    outdir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    cache_path = outdir / ".ffskill_cache.json"
    cache: Dict[str, Any] = {}
    if cache_path.exists() and not args.force:
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    rkey = recipe_key(recipe)
    glob = recipe.get("glob") or "*"

    def one_pass() -> List[Dict[str, Any]]:
        results = []
        files = sorted(p for p in folder.glob(glob) if p.is_file() and p.suffix.lower() in MEDIA_EXT and outdir not in p.parents)
        # Two different sources can compute the same final path (most often a fixed recipe "ext"
        # collapsing e.g. clip.mp4 and clip.mov to the same clip_out.mp4) -- catch that before
        # processing anything, rather than letting the later one silently overwrite the earlier
        # one's finished output with the cache still recording both as "ok".
        by_final: Dict[Path, List[Path]] = {}
        for src in files:
            by_final.setdefault(final_path(src, recipe, outdir), []).append(src)
        collisions = {dst: srcs for dst, srcs in by_final.items() if len(srcs) > 1}
        if collisions:
            detail = "; ".join(f"{dst.name} <- {', '.join(s.name for s in srcs)}" for dst, srcs in collisions.items())
            die(f"{len(collisions)} output filename collision(s) in this batch -- rename the sources, "
                f"or add a distinguishing \"suffix\"/\"ext\" per run, or split into separate globs: {detail}")
        for src in files:
            key = f"{file_key(src)}:{rkey}"
            hit = cache.get(key)
            if hit and Path(hit.get("output", "")).exists() and not args.force:
                info(f"skip (cached) {src.name}")
                results.append({**hit, "cached": True})
                continue
            info(f"=== {src.name}")
            r = process(src, recipe, outdir, work)
            results.append(r)
            if r["ok"] and not STATE["dry_run"]:
                cache[key] = r
                # write_text isn't atomic -- a process killed mid-write (or a --watch loop racing
                # a concurrent manual run) could leave a truncated file that json.loads() above
                # then silently treats as "no cache" (a ValueError -> {}), discarding every prior
                # entry. Write to a sibling temp file and rename into place: same-directory
                # renames are atomic on POSIX and os.replace() is atomic on Windows too, so a
                # reader only ever sees the old complete file or the new complete file.
                tmp = cache_path.parent / f"{cache_path.name}.tmp{os.getpid()}"
                tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
                os.replace(tmp, cache_path)
        return results

    results = one_pass()
    if args.watch:
        info(f"watching {folder} every {args.watch:g}s (Ctrl-C to stop)")
        try:
            while True:
                time.sleep(args.watch)
                results = one_pass()
        except KeyboardInterrupt:
            pass
    done = sum(1 for r in results if r["ok"])
    info(f"{done}/{len(results)} processed, {sum(1 for r in results if r.get('cached'))} from cache")
    emit(None, results=results, processed=done, total=len(results))
    if not args.json:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['file']} -> {r['output']}" + (" (cached)" if r.get("cached") else ""))
    return 0 if done == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
