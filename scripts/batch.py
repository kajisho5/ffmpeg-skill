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
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from _common import STATE, add_common, apply_common, child_args, die, emit, info, run_tool, MEDIA_EXT as _MEDIA_EXT
from _common.runner import HW_FORCED_ENV, add_hw_orchestrator_args, env_hw, stop_children
from _common.emit import absorb_stage_hw, audit, note, steps_encoder_report, warn

HERE = Path(__file__).resolve().parent
MEDIA_EXT = {e for e in _MEDIA_EXT if e not in (".png", ".jpg", ".jpeg", ".webp")}  # one list (_common); a batch walks media, not stills
# recipe steps name the script to run as plain, untrusted JSON -- run_step() joins it onto HERE
# with the `/` operator, which silently ignores the left side when the right side is itself an
# absolute path (Path("/scripts") / "/tmp/evil.py" == Path("/tmp/evil.py")), and does nothing to
# stop a "../" traversal either. Without this allowlist, a batch.json a caller didn't author
# themselves (from a template, a shared config, anywhere) could name any Python file on disk and
# have it executed with the caller's own privileges on every matching media file.
ALLOWED_STEP_SCRIPTS = {p.name for p in HERE.glob("*.py") if not p.name.startswith("_")}


def file_key(path: Path) -> str:
    st = path.stat()
    h = hashlib.sha1(usedforsecurity=False)  # a change detector, not a secret
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
        except (OSError, UnicodeDecodeError) as exc:
            # keyed on the recipe alone: an unreadable project cannot invalidate the cache by its
            # content, so say so (each item that needs it then fails on reading it)
            warn(f"recipe.project {recipe['project']} could not be read ({exc}); the cache key covers the recipe only",
                 "recipe_project_unreadable", path=str(recipe["project"]), error=str(exc))
    return hashlib.sha1((json.dumps(recipe, sort_keys=True) + "\0" + project_content).encode(), usedforsecurity=False).hexdigest()[:12]


def gpu_key() -> str:
    """The GPU setting the steps resolve, as a suffix for the item cache key: a VideoToolbox file is
    not the CPU's bytes, so a --hw output is never served to a --no-hw run or the other way round
    (render.py's cache_key folds the same two variables in). Read after apply_common(), which has
    exported --hw/--no-hw to the steps. '' when every step encodes on the CPU -- no flag and no
    $FFMPEG_SKILL_HW, or --no-hw -- so the keys of a cache written before --hw existed still hit."""
    if not env_hw():
        return ""
    # the variable alone leaves export.py's delivery presets on the CPU; --hw puts them on the GPU
    return ":hw" if os.environ.get(HW_FORCED_ENV) == "1" else ":hw-env"


JOBS_CAP = 8   # beyond this, concurrent encodes contend for the same cores and memory

_LOG = threading.local()
# set by batch.py's signal handler: a --jobs worker between two steps must not start the next one
_STOP = threading.Event()


def log(message: str) -> None:
    """info(), unless this thread is a --jobs worker -- then the line is buffered and flushed in
    file order when the item finishes, so a parallel run's log reads exactly like a serial one."""
    buf = getattr(_LOG, "buffer", None)
    if buf is None:
        info(message)
    else:
        buf.append(message)


class ItemError(Exception):
    """An item that cannot be processed, with the structured `error` its results row carries.
    process() raises it instead of die(): die() inside an item printed a second JSON document
    and left the row with error "1" (str(SystemExit))."""

    def __init__(self, error: Dict[str, Any]) -> None:
        super().__init__(error.get("message"))
        self.error = error


def step_error(index: Optional[int], tool: Optional[str], doc: Any) -> Dict[str, Any]:
    """A failed step's own failure, for its item's row: {step, tool, kind, message, code, reason,
    details, hint, exit_code} from the step's --json document (keys it did not report are left
    out; step and tool are always there)."""
    err = doc.get("error") if isinstance(doc, dict) and isinstance(doc.get("error"), dict) else {}
    out: Dict[str, Any] = {"step": index, "tool": tool}
    for k in ("kind", "message", "code", "reason", "details", "hint"):
        if err.get(k) is not None:
            out[k] = err[k]
    if isinstance(doc, dict) and doc.get("exit_code") is not None:
        out["exit_code"] = doc["exit_code"]
    return out


def run_step(argv: List[str], per_call: "Optional[float]" = None) -> "tuple[bool, Optional[dict]]":
    """Returns (ok, doc): doc is the step's own --json result document; a failed step that
    printed none that parses gets one in the failure shape (error.reason step_output_unparsed,
    the last stderr line as the message), so its row still says why. {in}/{out} are already resolved by the caller before argv reaches here, so forcing
    --json on every step (harmless: no step reads another step's stdout, only its output path)
    costs nothing and lets a caller like process() read back tool-specific fields, e.g. cut.py's
    `reencoded`, without adding a bespoke flag per field it might someday want."""
    script = argv[0]
    if script not in ALLOWED_STEP_SCRIPTS:
        # main() refuses such a recipe before any item runs; this stays as the last line of defence
        raise ItemError({"step": None, "tool": script, "kind": "input", "reason": "step_script_not_allowed",
                         "message": f"recipe step names a script that isn't one of this skill's own tools: {script!r} "
                                    "(must be a bare filename like 'silence.py', found in scripts/)"})
    if _STOP.is_set():
        return False, {"status": "failed", "exit_code": 130,
                       "error": {"kind": "interrupted", "message": f"interrupted before {script} started"}}
    cmd = [str(HERE / script)] + argv[1:] + child_args() + (["--json"] if "--json" not in argv[1:] else [])
    log("  → " + " ".join(os.path.basename(c) if i < 1 else c for i, c in enumerate(cmd)))
    proc = run_tool(cmd, per_call=per_call)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = None
    if proc.returncode != 0:
        log("    " + "\n    ".join(proc.stderr.strip().splitlines()[-4:]))
        if not isinstance(doc, dict):
            doc = {"status": "failed", "exit_code": proc.returncode,
                   "error": {"reason": "step_output_unparsed",
                             "message": (proc.stderr.strip().splitlines() or [f"{script} exited {proc.returncode} and printed nothing"])[-1][:300]}}
        return False, doc
    for line in proc.stderr.splitlines():
        if line.startswith("warning:"):  # a step's deprecation notice is not swallowed by a success (review 9)
            log("    " + line)
    return True, doc


def _run_buffered(fn, *a):
    """Run a worker and hand back (its result, the log lines it produced)."""
    r = fn(*a)
    return r, list(getattr(_LOG, "lines", None) or [])


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


def process(src: Path, recipe: Dict[str, Any], outdir: Path, work: Path,
            deadline: "Optional[float]" = None) -> Dict[str, Any]:
    final = final_path(src, recipe, outdir)
    t0 = time.time()

    def budget() -> "Optional[float]":
        """What is left of the BATCH's time limit -- not a fresh one per item. A --timeout is a
        promise about the whole run, so a queue of 40 files cannot quietly take 40 timeouts."""
        if deadline is None:
            return None
        return max(1.0, deadline - time.monotonic())
    if recipe.get("project"):
        try:
            proj = json.loads(Path(str(recipe["project"])).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ItemError({"step": None, "tool": "render.py", "kind": "input", "reason": "recipe_project_unreadable",
                             "message": f"recipe.project: {recipe['project']} could not be read as JSON: {e}"})
        if not isinstance(proj, dict):
            raise ItemError({"step": None, "tool": "render.py", "kind": "input", "reason": "recipe_project_unreadable",
                             "message": f"recipe.project: {recipe['project']} is not a JSON object"})
        idx = int(recipe.get("clip_key", 0))
        proj.setdefault("clips", [{}])
        while len(proj["clips"]) <= idx:
            proj["clips"].append({})
        proj["clips"][idx]["src"] = str(src.resolve())
        proj["output"] = str(final.resolve())
        pj = work / f"{src.stem}_project.json"
        pj.write_text(json.dumps(proj, indent=2), encoding="utf-8")
        ok, _doc = run_step(["render.py", str(pj)], budget())
        step_docs = [("render", _doc)]
        failure = None if ok else step_error(0, "render.py", _doc)
        cut_reencoded: List[bool] = []
        cut_reasons: List[str] = []
    else:
        steps = recipe.get("steps") or []
        if not steps:
            raise ItemError({"step": None, "tool": None, "kind": "input", "reason": "recipe_has_no_steps",
                             "message": "recipe needs steps or project"})
        cur = str(src)
        ok = True
        failure = None
        cut_reencoded = []
        step_docs = []
        cut_reasons = []
        for i, step in enumerate(steps):
            last = i == len(steps) - 1
            out = str(final) if last else str(work / f"{src.stem}_step{i}.{'mp4' if src.suffix.lower() not in ('.wav', '.mp3', '.m4a', '.flac') else src.suffix.lstrip('.')}")
            argv = [str(a).replace("{in}", cur).replace("{out}", out) for a in step]
            step_ok, doc = run_step(argv, budget())
            step_docs.append((Path(str(argv[0])).stem if argv else "step", doc))
            # only cut.py's own doc carries `reencoded` -- true if ANY range this call cut (or its
            # --segments join) re-encoded, for the reasons in its `reencode_reason` (distinct per
            # call, so cut_reencode_reasons lists each reason once per cut.py call that named it).
            # Per cut.py call, not per --segments range.
            if step_ok and argv and argv[0] == "cut.py" and isinstance(doc, dict) and "reencoded" in doc:
                cut_reencoded.append(bool(doc["reencoded"]))
                cut_reasons.extend(r for r in (doc.get("reencode_reason") or []) if isinstance(r, str))
            if not step_ok:
                ok = False
                failure = step_error(i, str(argv[0]) if argv else None, doc)
                break
            cur = out
    result: Dict[str, Any] = {"file": str(src), "output": str(final), "ok": ok, "seconds": round(time.time() - t0, 1)}
    if failure:
        result["error"] = failure
    # `ok` is "every step completed" (design-decisions: a spec miss a tool cannot fix is completed +
    # verified false, not a failure); `verified` is whether every step also verified what it wrote,
    # and `unverified` names the steps that did not and which of their checks failed
    unverified = []
    for idx, (name, doc) in enumerate(step_docs):
        if ok and isinstance(doc, dict) and doc.get("verified") is not True:
            unverified.append({"step": idx, "tool": name,
                               "failed": [str(v.get("step")) + (f" ({v['stage']})" if v.get("stage") else "")
                                          for v in doc.get("verification") or [] if isinstance(v, dict) and not v.get("ok")]})
    result["verified"] = bool(ok and not STATE.dry_run and step_docs and not unverified)
    if unverified and not STATE.dry_run:
        result["unverified"] = unverified
    diag: Dict[str, List[Any]] = {}
    for name, doc in step_docs:
        for bucket, entries in ((doc or {}).get("diagnostics") or {}).items() if isinstance(doc, dict) else []:
            diag.setdefault(bucket, []).extend(dict(e, step=name) for e in entries if isinstance(e, dict))
    if diag:
        result["diagnostics"] = diag
    if cut_reencoded:
        result["cut_reencoded"] = cut_reencoded
        result["cut_reencode_reasons"] = cut_reasons
    # the encoder each item really ran and its GPU facts (--hw / FFMPEG_SKILL_HW: on VideoToolbox,
    # fell back and why): this process encodes nothing itself, so its top-level hw.used is null
    result.update(steps_encoder_report(step_docs))
    return result


def output_identity(path: str) -> "Optional[Dict[str, int]]":
    """What a cache entry remembers of the output it served: size and mtime_ns (a stat, no read)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def cached_output_changed(hit: Dict[str, Any]) -> "Optional[Dict[str, Any]]":
    """None when the entry's output is still the file this batch wrote; else why it is not served:
    output_missing, output_changed (size or mtime differ: something replaced or edited it) or
    entry_unverifiable (an entry written by 2.10.11 or earlier recorded no identity, so nothing can say
    the file is the one it describes)."""
    out = str(hit.get("output") or "")
    now = output_identity(out) if out else None
    if now is None:
        return {"reason": "output_missing", "output": out, "message": "the output is gone"}
    expected = hit.get("output_identity")
    if not isinstance(expected, dict):
        return {"reason": "entry_unverifiable", "output": out,
                "message": "the cache entry predates output identities, so the file cannot be checked"}
    if expected != now:
        return {"reason": "output_changed", "output": out, "expected": expected, "actual": now,
                "message": "the output changed since the batch wrote it"}
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--recipe", required=True, help="batch.json")
    ap.add_argument("--force", action="store_true", help="ignore the cache and redo everything")
    ap.add_argument("--watch", type=float, help="keep polling the folder every N seconds")
    ap.add_argument("--jobs", default="1", metavar="N",
                    help="process N files at once, or 'auto' for min(cpu_count, 4). Capped at "
                         "min(N, cpu_count, 8): every item is already an ffmpeg that threads "
                         "across cores, so more than a few contend rather than go faster. "
                         "Default 1, which is 1.16's behaviour exactly.")
    ap.add_argument("--work", help="work directory for intermediates (default: <output_dir>/.work)")
    add_common(ap)
    add_hw_orchestrator_args(ap)
    args = ap.parse_args()
    apply_common(args)

    started = time.time()
    folder = Path(args.folder).resolve()  # relative 'bdir' used to become bdir/bdir/out once joined with the default outdir
    if not folder.is_dir():
        die(f"not a folder: {folder}")
    try:
        recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read recipe: {exc}")
    if not isinstance(recipe, dict):
        die("cannot read recipe: not a JSON object")
    if recipe.get("project") and not os.path.isabs(recipe["project"]):
        recipe["project"] = str((Path(args.recipe).resolve().parent / recipe["project"]))
    # a recipe error is the same for every item: refuse it once, before any item runs, rather than
    # failing each item with it
    if not recipe.get("project"):
        if not recipe.get("steps"):
            die("recipe needs steps or project")
        for st in recipe["steps"]:
            name = st[0] if isinstance(st, list) and st else st
            if not isinstance(name, str) or name not in ALLOWED_STEP_SCRIPTS:
                die(f"recipe step names a script that isn't one of this skill's own tools: {name!r} "
                    f"(must be a bare filename like 'silence.py', found in scripts/)")
    outdir = Path(recipe.get("output_dir") or (folder / "out"))
    if not outdir.is_absolute():
        outdir = folder / outdir
    work = Path(args.work) if args.work else outdir / ".work"
    # the children refuse an output whose directory does not exist, under --dry-run too, so the
    # directories are created for the plan as well -- and removed again afterwards when a dry
    # run created them and left them empty (a plan leaves nothing behind, sweep F15)
    created = [d for d in (outdir, work) if not d.exists()]
    outdir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    if STATE.dry_run and created:
        import atexit

        def _remove_empty_dirs() -> None:
            for d in sorted(created, key=lambda p: len(str(p)), reverse=True):
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except OSError:
                    pass
        atexit.register(_remove_empty_dirs)
    cache_path = outdir / ".ffskill_cache.json"
    cache: Dict[str, Any] = {}
    if cache_path.exists() and not args.force:
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as exc:
            # every entry is lost: each item runs again, and the next store rewrites the file
            size = cache_path.stat().st_size if cache_path.exists() else None
            warn(f"the batch cache {cache_path} could not be read ({exc}); starting with an empty cache, so every item runs again",
                 "batch_cache_reset", path=str(cache_path), size=size, error=str(exc))
            audit("batch_cache_reset", {"path": str(cache_path), "size": size, "error": str(exc)},
                  default_path=str(outdir / ".ffskill-audit.jsonl"))
            cache = {}
    rkey = recipe_key(recipe) + gpu_key()
    glob = recipe.get("glob") or "*"

    # --jobs: every item is itself an ffmpeg that already threads across cores, so beyond a few
    # concurrent encodes the jobs contend and wall-clock stops improving while memory does not.
    # A number above the cap is clamped with a note, not refused: an optimistic number is not an
    # error, and refusing one helps nobody.
    cpus = os.cpu_count() or 1
    requested = min(cpus, 4) if str(args.jobs).lower() == "auto" else None
    if requested is None:
        try:
            requested = int(args.jobs)
        except ValueError:
            die(f"--jobs {args.jobs!r}: a whole number, or 'auto'", kind="input")
        if requested < 1:
            die("--jobs must be at least 1", kind="input")
    jobs = max(1, min(requested, cpus, JOBS_CAP))
    if jobs != requested:
        info(f"--jobs {requested} capped to {jobs} (min of the request, {cpus} CPU(s) and the "
             f"{JOBS_CAP}-job ceiling): each item is already a multi-threaded encode")
    # One budget for the whole batch, not one per item -- but only where that cannot change what
    # 1.16 did. A stated --timeout is a statement about this run, and asking for --jobs > 1 is
    # asking for the batch to be treated as one piece of work; the default sequential path with
    # the default timeout keeps 1.16's behaviour exactly, where each item got its own ceiling and
    # a long folder was never cut off part-way.
    shared_budget = bool(args.timeout) or jobs > 1
    deadline = time.monotonic() + STATE.timeout if (shared_budget and STATE.timeout) else None
    cache_lock = threading.Lock()
    timed_out = {"hit": False}
    interrupted: Dict[str, Any] = {"hit": False, "signal": None}
    _STOP.clear()
    # Ctrl-C (and SIGTERM where it is delivered) stops the running steps and reports the table:
    # the shared handler would exit with "nothing was written" and no rows, and inside an item it
    # surfaced as that item's failure while the batch went on (spec 4.1)
    import signal as _signal

    def _interrupt(signum: int, frame: Any) -> None:
        interrupted["signal"] = signum
        _STOP.set()
        stop_children()
        raise KeyboardInterrupt
    if threading.current_thread() is threading.main_thread():
        for sig in (getattr(_signal, "SIGINT", None), getattr(_signal, "SIGTERM", None)):
            if sig is not None:
                try:
                    _signal.signal(sig, _interrupt)
                except (ValueError, OSError):
                    pass

    def one_pass() -> List[Dict[str, Any]]:
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
        def item_work(i: int, src: Path) -> Path:
            """Where this item's intermediates go. Parallel items must not share one work dir:
            the step file names are stem-derived, so two globs holding the same stem would write
            over each other. Serial runs keep the flat layout 1.16 used, byte for byte."""
            if jobs == 1:
                return work
            sub = work / f"{i}-{src.stem}"
            sub.mkdir(parents=True, exist_ok=True)
            return sub

        def store(key: str, r: Dict[str, Any]) -> None:
            if not (r["ok"] and not STATE.dry_run):
                return
            # The read-modify-write of the in-memory dict needs the lock even though the file
            # write is already atomic: two finishers could otherwise serialise from two different
            # snapshots and lose an entry.
            with cache_lock:
                # this run just rewrote r["output"]: an entry under another key (another recipe,
                # the other GPU setting) that names the same file now describes bytes that are gone
                for stale in [k for k, v in cache.items() if k != key and isinstance(v, dict) and v.get("output") == r["output"]]:
                    del cache[stale]
                # the output as this run left it: a later hit is served only while it is unchanged
                cache[key] = dict(r, output_identity=output_identity(r["output"]))
                # write_text isn't atomic -- a process killed mid-write (or a --watch loop racing
                # a concurrent manual run) could leave a truncated file that json.loads() above
                # then silently treats as "no cache" (a ValueError -> {}), discarding every prior
                # entry. Write to a sibling temp file and rename into place: same-directory
                # renames are atomic on POSIX and os.replace() is atomic on Windows too, so a
                # reader only ever sees the old complete file or the new complete file.
                tmp = cache_path.parent / f"{cache_path.name}.tmp{os.getpid()}.{threading.get_ident()}"
                tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
                os.replace(tmp, cache_path)

        # ONE list, indexed by each file's position in the sorted `files`. A cached hit goes
        # into its own slot rather than being appended ahead of the items that still have to run:
        # appending in two passes reordered the per-item table whenever the cache was partially
        # warm, which happens at --jobs 1 too and contradicts the order this tool promises.
        slots: "List[Optional[Dict[str, Any]]]" = [None] * len(files)
        pending: List[tuple] = []
        cache_miss: Dict[int, Dict[str, Any]] = {}
        for i, src in enumerate(files):
            key = f"{file_key(src)}:{rkey}"
            hit = cache.get(key)
            if isinstance(hit, dict) and not args.force:
                why = cached_output_changed(hit)
                if why is None:
                    info(f"skip (cached) {src.name}")
                    slots[i] = {**{k: v for k, v in hit.items() if k != "output_identity"}, "cached": True}
                    continue
                cache_miss[i] = why
                facts = {k: v for k, v in why.items() if k not in ("reason", "message")}
                msg = f"{src.name}: the cached output {hit.get('output')} is not served ({why['message']}); the item runs again"
                if why["reason"] == "output_changed":
                    warn(msg, "batch_cache_output_changed", file=str(src), **facts)
                elif why["reason"] == "entry_unverifiable":
                    warn(msg, "batch_cache_entry_unverifiable", file=str(src), **facts)
            pending.append((i, src, key))

        def timed_out_row(src: Path) -> "Dict[str, Any]":
            timed_out["hit"] = True
            return {"file": str(src), "output": str(final_path(src, recipe, outdir)),
                    "ok": False, "seconds": 0.0, "skipped": "timeout"}

        def failed_row(src: Path, exc: BaseException) -> "Dict[str, Any]":
            """A worker that raised is a failed item, not a dead run. A die() inside a thread
            raises SystemExit through fut.result() and used to take the whole process down
            before the summary and the per-item table were printed -- so the one thing the user
            needed, which item failed and which succeeded, was the thing they did not get.
            `error` is structured: an ItemError's own, else what the exception says (its class
            in `exception`), never str(SystemExit) -- which was the exit code, "1"."""
            if isinstance(exc, ItemError):
                error = dict(exc.error)
            elif isinstance(exc, SystemExit):
                error = {"step": None, "tool": None, "exception": "SystemExit", "exit_code": exc.code,
                         "message": f"the item stopped with exit code {exc.code}; its message is on stderr"}
            else:
                error = {"step": None, "tool": None, "exception": exc.__class__.__name__,
                         "message": (str(exc) or exc.__class__.__name__)[:300]}
            log(f"    failed: {error['message']}")
            return {"file": str(src), "output": str(final_path(src, recipe, outdir)),
                    "ok": False, "verified": False, "seconds": 0.0, "error": error}

        def interrupted_row(src: Path, started: bool, r: "Optional[Dict[str, Any]]" = None) -> "Dict[str, Any]":
            """An item the interrupt reached: `interrupted: true` when it was running (its steps
            were stopped), `skipped: "interrupted"` when it had not started."""
            row = dict(r) if r else {"file": str(src), "output": str(final_path(src, recipe, outdir)), "seconds": 0.0}
            row.update(ok=False, verified=False)
            if started:
                row["interrupted"] = True
                row.setdefault("error", {"step": None, "tool": None, "kind": "interrupted",
                                         "message": "interrupted while this item was running; its running step was stopped"})
            else:
                row["skipped"] = "interrupted"
            return row

        def with_miss(i: int, r: Dict[str, Any]) -> Dict[str, Any]:
            if i in cache_miss:
                r["cache_miss"] = {k: v for k, v in cache_miss[i].items() if k != "message"}
            return r

        if jobs == 1 or len(pending) < 2:
            for n, (i, src, key) in enumerate(pending):
                if deadline is not None and time.monotonic() >= deadline:
                    slots[i] = timed_out_row(src)
                    continue
                info(f"=== {src.name}")
                try:
                    r = process(src, recipe, outdir, item_work(i, src), deadline)
                except KeyboardInterrupt:
                    interrupted["hit"] = True
                    # the running item, then every one not started: each keeps its row
                    slots[i] = interrupted_row(src, True)
                    for j, later, _k in pending[n + 1:]:
                        slots[j] = interrupted_row(later, False)
                    break
                except BaseException as exc:            # noqa: BLE001 - reported, never swallowed
                    if isinstance(exc, SystemExit) and not exc.code:
                        raise
                    slots[i] = with_miss(i, failed_row(src, exc))
                    continue
                slots[i] = with_miss(i, r)
                store(key, r)
            return [r for r in slots if r is not None]

        import concurrent.futures

        def work_one(i: int, src: Path, key: str) -> Dict[str, Any]:
            _LOG.buffer = [f"=== {src.name}"]
            try:
                r = process(src, recipe, outdir, item_work(i, src), deadline)
                if not interrupted["hit"]:   # a step the interrupt stopped is no result to keep
                    store(key, r)
                return with_miss(i, r)
            finally:
                r_lines, _LOG.buffer = _LOG.buffer, None
                setattr(_LOG, "lines", r_lines)

        # Submitted in the existing sorted order and written straight into each item's own slot,
        # so the summary and the per-item table are identical to a serial run's whatever order
        # the encodes actually finish in.
        lines: "Dict[int, List[str]]" = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures: "Dict[Any, tuple]" = {}
            queue = list(pending)
            in_flight: "set" = set()
            try:
                # The pool is topped up to `jobs` in flight and no further: submitting the whole
                # list up front would put every item past the deadline check before the first one
                # had finished, and the shared budget could then never stop anything.
                while queue or in_flight:
                    while queue and len(in_flight) < jobs:
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                        i, src, key = queue.pop(0)
                        fut = pool.submit(_run_buffered, work_one, i, src, key)
                        futures[fut] = (i, src)
                        in_flight.add(fut)
                    if not in_flight:
                        break
                    done_now, in_flight = concurrent.futures.wait(
                        in_flight, return_when=concurrent.futures.FIRST_COMPLETED)
                    in_flight = set(in_flight)
                    for fut in done_now:
                        i, src = futures[fut]
                        try:
                            slots[i], lines[i] = fut.result()
                        except BaseException as exc:    # noqa: BLE001 - reported, never swallowed
                            slots[i] = failed_row(src, exc)
                            lines[i] = [f"=== {src.name}", f"    failed: {exc}"]
                for i, src, key in queue:
                    slots[i] = timed_out_row(src)
            except KeyboardInterrupt:
                # Spec 4.1: cancel what has not started, stop the running steps (the handler
                # already did), and REPORT every item -- exit 130 with the table, never a
                # traceback. The pool's exit waits for the stopped items; they are read below.
                interrupted["hit"] = True
                for fut in futures:
                    fut.cancel()
                info("interrupted: reporting what had already finished")
        if interrupted["hit"]:
            for fut, (i, src) in futures.items():
                if slots[i] is not None:
                    continue
                if fut.cancelled():
                    slots[i] = interrupted_row(src, False)
                    continue
                try:
                    r, lines[i] = fut.result()
                except BaseException:                   # noqa: BLE001 - its row says it was interrupted
                    r = None
                # finished in time: kept as it is; stopped by the interrupt: said so
                slots[i] = r if (r and r.get("ok")) else interrupted_row(src, True, r)
            for i, src, _key in queue:
                if slots[i] is None:
                    slots[i] = interrupted_row(src, False)
        for i, src in enumerate(files):
            for line in lines.get(i, []):
                info(line)
        return [r for r in slots if r is not None]

    results = one_pass()
    if args.watch:
        info(f"watching {folder} every {args.watch:g}s (Ctrl-C to stop)")
        # the shared SIGINT handler (install_signal_handlers) exits 130 with "nothing was written",
        # which is wrong for a watch that already processed files: while idle between passes,
        # let Ctrl-C be a plain KeyboardInterrupt so the summary below prints (review 5)
        import signal
        try:
            while True:
                previous = signal.signal(signal.SIGINT, signal.default_int_handler)
                try:
                    time.sleep(args.watch)
                finally:
                    signal.signal(signal.SIGINT, previous)
                results = one_pass()
                if interrupted["hit"]:
                    break  # the pass reported its rows; a watch interrupted mid-pass stops here
        except KeyboardInterrupt:
            info("watch stopped")
    # the items' GPU facts (asked for, fell back and why) reach the top-level `hw`, as render.py's
    # stages' do; `used` stays null there, because this process encoded nothing itself
    for r in results:
        absorb_stage_hw(Path(r["file"]).name, r)
    done = sum(1 for r in results if r["ok"])
    info(f"{done}/{len(results)} processed, {sum(1 for r in results if r.get('cached'))} from cache")
    if not args.json:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['file']} -> {r['output']}" + (" (cached)" if r.get("cached") else ""))
    if interrupted["hit"]:
        # Ctrl-C on a batch that already produced files: the user needs the partial table, not a
        # traceback and not "nothing was written". Exit 130 (143 for SIGTERM) with every item:
        # finished, interrupted while running, or not started.
        stopped = sum(1 for r in results if r.get("interrupted"))
        not_started = sum(1 for r in results if r.get("skipped") == "interrupted")
        die(f"interrupted after {done} of {len(results)} item(s): {stopped} stopped while running and "
            f"{not_started} not started; the finished outputs are kept",
            code=128 + int(interrupted["signal"] or 2), kind="interrupted", output=None, dry_run=STATE.dry_run, results=results,
            processed=done, total=len(results), jobs=jobs, jobs_requested=requested,
            timed_out=timed_out["hit"])
    if timed_out["hit"]:
        skipped = [r["file"] for r in results if r.get("skipped") == "timeout"]
        die(f"the batch's {STATE.timeout:.0f} s budget ran out with {len(skipped)} item(s) not "
            f"started: {', '.join(os.path.basename(f) for f in skipped[:5])}"
            + (" ..." if len(skipped) > 5 else "")
            + ". --timeout is the whole run's limit, not each item's; raise it or split the folder.",
            code=124, kind="timeout", output=None, dry_run=STATE.dry_run, results=results,
            processed=done, total=len(results), jobs=jobs, jobs_requested=requested,
            timed_out=True)
    if done != len(results):
        failed_files = [r["file"] for r in results if not r["ok"]]
        die(f"{len(results) - done} of {len(results)} items failed: {', '.join(failed_files[:5])}" + (" ..." if len(failed_files) > 5 else ""),
            kind="verification", output=None, dry_run=STATE.dry_run, results=results, processed=done, total=len(results))
    # cut.py's own `reencoded`, rolled up across every cut.py step this batch ran: how much of the
    # folder landed on the fast lossless path (mode "copy") vs re-encoded on at least one range.
    # Keyframe placement, VFR sources, --accurate/--codec in the recipe and --segments joins all
    # cause it, so the summary counts cut.py's own `reencode_reason` values rather than guessing
    # one cause. Per cut.py call, not per --segments range.
    all_cuts = [r for res in results for r in (res.get("cut_reencoded") or [])]
    cut_summary = None
    # how many cut.py calls named each reason, beside cut_stream_copy (whose shape is 2.x's,
    # unchanged); null when no cut.py step ran
    reasons: Optional[Dict[str, int]] = None
    if all_cuts:
        copied = sum(1 for r in all_cuts if not r)
        cut_summary = {"calls": len(all_cuts), "stream_copy": copied, "reencoded": len(all_cuts) - copied,
                        "stream_copy_rate": round(copied / len(all_cuts), 3)}
        reasons = {}
        for res in results:
            if "cut_reencode_reasons" not in res:
                # a row from a cache an earlier 2.x batch wrote: it says which calls re-encoded,
                # not why, so they count as "unknown" rather than leaving {} ("none re-encoded")
                unknown = sum(1 for r in res.get("cut_reencoded") or [] if r)
                if unknown:
                    reasons["unknown"] = reasons.get("unknown", 0) + unknown
            for r in res.get("cut_reencode_reasons") or []:
                reasons[r] = reasons.get(r, 0) + 1
        why = (" (reencode_reason: " + ", ".join(f"{k} x{v}" for k, v in reasons.items()) + ")") if reasons else ""
        info(f"cut.py: {copied}/{len(all_cuts)} call(s) stayed fully lossless stream-copy "
             f"({cut_summary['stream_copy_rate']:.0%}), {len(all_cuts) - copied} re-encoded a range or its --segments join{why}")
    unverified = [os.path.basename(r["file"]) for r in results if r.get("ok") and not r.get("verified")]
    if unverified and not STATE.dry_run:
        note(f"{len(unverified)} item(s) completed but did not verify everything they wrote (see each row's unverified): "
             + ", ".join(unverified[:5]) + (" ..." if len(unverified) > 5 else ""))
    emit(None, verification=[{"step": "item", "file": r["file"], "ok": bool(r.get("verified"))} for r in results]
         if not STATE.dry_run else [],
         results=results, processed=done, total=len(results),
         jobs=jobs, jobs_requested=requested, wall_seconds=round(time.time() - started, 1),
         item_seconds_total=round(sum(float(r.get("seconds") or 0) for r in results), 1),
         timed_out=timed_out["hit"], cut_stream_copy=cut_summary, cut_reencode_reasons=reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
