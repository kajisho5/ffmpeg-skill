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

from _common import STATE, add_common, apply_common, child_args, die, emit, info, run_tool, read_text_or_die, MEDIA_EXT as _MEDIA_EXT

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


JOBS_CAP = 8   # beyond this, concurrent encodes contend for the same cores and memory

_LOG = threading.local()


def log(message: str) -> None:
    """info(), unless this thread is a --jobs worker -- then the line is buffered and flushed in
    file order when the item finishes, so a parallel run's log reads exactly like a serial one."""
    buf = getattr(_LOG, "buffer", None)
    if buf is None:
        info(message)
    else:
        buf.append(message)


def run_step(argv: List[str], per_call: "Optional[float]" = None) -> bool:
    script = argv[0]
    if script not in ALLOWED_STEP_SCRIPTS:
        die(f"recipe step names a script that isn't one of this skill's own tools: {script!r} "
            f"(must be a bare filename like 'silence.py', found in scripts/)")
    cmd = [str(HERE / script)] + argv[1:] + child_args()
    log("  → " + " ".join(os.path.basename(c) if i < 1 else c for i, c in enumerate(cmd)))
    proc = run_tool(cmd, per_call=per_call)
    if proc.returncode != 0:
        log("    " + "\n    ".join(proc.stderr.strip().splitlines()[-4:]))
        return False
    for line in proc.stderr.splitlines():
        if line.startswith("warning:"):  # a step's deprecation notice is not swallowed by a success (review 9)
            log("    " + line)
    return True


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
            proj = json.loads(read_text_or_die(str(recipe["project"]), "recipe.project"))
        except ValueError as e:
            die(f"recipe.project: {recipe['project']} is not valid JSON: {e}")
        idx = int(recipe.get("clip_key", 0))
        proj.setdefault("clips", [{}])
        while len(proj["clips"]) <= idx:
            proj["clips"].append({})
        proj["clips"][idx]["src"] = str(src.resolve())
        proj["output"] = str(final.resolve())
        pj = work / f"{src.stem}_project.json"
        pj.write_text(json.dumps(proj, indent=2), encoding="utf-8")
        ok = run_step(["render.py", str(pj)], budget())
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
            if not run_step(argv, budget()):
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
    ap.add_argument("--jobs", default="1", metavar="N",
                    help="process N files at once, or 'auto' for min(cpu_count, 4). Capped at "
                         "min(N, cpu_count, 8): every item is already an ffmpeg that threads "
                         "across cores, so more than a few contend rather than go faster. "
                         "Default 1, which is 1.16's behaviour exactly.")
    ap.add_argument("--work", help="work directory for intermediates (default: <output_dir>/.work)")
    add_common(ap)
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
    if recipe.get("project") and not os.path.isabs(recipe["project"]):
        recipe["project"] = str((Path(args.recipe).resolve().parent / recipe["project"]))
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
        except ValueError:
            cache = {}
    rkey = recipe_key(recipe)
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
    interrupted = {"hit": False}

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
                cache[key] = r
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
        for i, src in enumerate(files):
            key = f"{file_key(src)}:{rkey}"
            hit = cache.get(key)
            if hit and Path(hit.get("output", "")).exists() and not args.force:
                info(f"skip (cached) {src.name}")
                slots[i] = {**hit, "cached": True}
                continue
            pending.append((i, src, key))

        def timed_out_row(src: Path) -> "Dict[str, Any]":
            timed_out["hit"] = True
            return {"file": str(src), "output": str(final_path(src, recipe, outdir)),
                    "ok": False, "seconds": 0.0, "skipped": "timeout"}

        def failed_row(src: Path, exc: BaseException) -> "Dict[str, Any]":
            """A worker that raised is a failed item, not a dead run. A die() inside a thread
            raises SystemExit through fut.result() and used to take the whole process down
            before the summary and the per-item table were printed -- so the one thing the user
            needed, which item failed and which succeeded, was the thing they did not get."""
            reason = str(exc) or exc.__class__.__name__
            return {"file": str(src), "output": str(final_path(src, recipe, outdir)),
                    "ok": False, "seconds": 0.0, "error": reason[:300]}

        if jobs == 1 or len(pending) < 2:
            for i, src, key in pending:
                if deadline is not None and time.monotonic() >= deadline:
                    slots[i] = timed_out_row(src)
                    continue
                info(f"=== {src.name}")
                try:
                    r = process(src, recipe, outdir, item_work(i, src), deadline)
                except KeyboardInterrupt:
                    interrupted["hit"] = True
                    break
                except BaseException as exc:            # noqa: BLE001 - reported, never swallowed
                    if isinstance(exc, SystemExit) and not exc.code:
                        raise
                    slots[i] = failed_row(src, exc)
                    continue
                slots[i] = r
                store(key, r)
            return [r for r in slots if r is not None]

        import concurrent.futures

        def work_one(i: int, src: Path, key: str) -> Dict[str, Any]:
            _LOG.buffer = [f"=== {src.name}"]
            try:
                r = process(src, recipe, outdir, item_work(i, src), deadline)
                store(key, r)
                return r
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
                # Spec 4.1: cancel what has not started, let the running children be killed by
                # the shared signal handling, and REPORT what completed -- exit 130 with the
                # partial table, never a traceback.
                interrupted["hit"] = True
                for fut in futures:
                    fut.cancel()
                for fut, (i, src) in futures.items():
                    if slots[i] is not None or not fut.done():
                        continue
                    try:
                        slots[i], lines[i] = fut.result()
                    except BaseException:               # noqa: BLE001
                        pass
                info("interrupted: reporting what had already finished")
        for i, src in enumerate(files):
            for line in lines.get(i, []):
                info(line)
        return [r for r in slots if r is not None]

        import concurrent.futures

        def work_one(i: int, src: Path, key: str) -> Dict[str, Any]:
            _LOG.buffer = [f"=== {src.name}"]
            try:
                r = process(src, recipe, outdir, item_work(i, src), deadline)
                store(key, r)
                return r
            finally:
                r_lines, _LOG.buffer = _LOG.buffer, None
                setattr(_LOG, "lines", r_lines)

        # Submitted in the existing sorted order and collected into a list indexed by submission
        # order, so the summary and the per-item table are identical to a serial run's whatever
        # order the encodes actually finish in.
        ordered: List[Optional[Dict[str, Any]]] = [None] * len(pending)
        lines: List[List[str]] = [[] for _ in pending]
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures: "Dict[Any, int]" = {}
            queue = list(enumerate(pending))
            in_flight: "set" = set()
            try:
                # The pool is topped up to `jobs` in flight and no further: submitting the whole
                # list up front would put every item past the deadline check before the first one
                # had finished, and the shared budget could then never stop anything.
                while queue or in_flight:
                    while queue and len(in_flight) < jobs:
                        slot, (i, src, key) = queue[0]
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                        queue.pop(0)
                        fut = pool.submit(_run_buffered, work_one, i, src, key)
                        futures[fut] = slot
                        in_flight.add(fut)
                    if not in_flight:
                        break
                    done_now, in_flight = concurrent.futures.wait(
                        in_flight, return_when=concurrent.futures.FIRST_COMPLETED)
                    in_flight = set(in_flight)
                    for fut in done_now:
                        ordered[futures[fut]], lines[futures[fut]] = fut.result()
                for slot, (i, src, key) in queue:
                    timed_out["hit"] = True
                    ordered[slot] = {"file": str(src),
                                     "output": str(final_path(src, recipe, outdir)),
                                     "ok": False, "seconds": 0.0, "skipped": "timeout"}
            except KeyboardInterrupt:
                for fut in futures:
                    fut.cancel()
                info("interrupted: finishing what had already started")
                raise
        for slot, (i, src, key) in enumerate(pending):
            for line in lines[slot]:
                info(line)
            if ordered[slot] is None:
                timed_out["hit"] = True
                ordered[slot] = {"file": str(src), "output": str(final_path(src, recipe, outdir)),
                                 "ok": False, "seconds": 0.0, "skipped": "timeout"}
            results.append(ordered[slot])
        return results

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
        except KeyboardInterrupt:
            info("watch stopped")
    done = sum(1 for r in results if r["ok"])
    info(f"{done}/{len(results)} processed, {sum(1 for r in results if r.get('cached'))} from cache")
    if not args.json:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['file']} -> {r['output']}" + (" (cached)" if r.get("cached") else ""))
    if interrupted["hit"]:
        # Ctrl-C on a batch that already produced files: the user needs the partial table, not a
        # traceback and not "nothing was written". Exit 130 with everything that completed.
        die(f"interrupted after {done} of {len(results)} item(s); the finished outputs are kept "
            "and the rest were not started",
            code=130, kind="interrupted", output=None, dry_run=STATE.dry_run, results=results,
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
    emit(None, results=results, processed=done, total=len(results),
         jobs=jobs, jobs_requested=requested, wall_seconds=round(time.time() - started, 1),
         item_seconds_total=round(sum(float(r.get("seconds") or 0) for r in results), 1),
         timed_out=timed_out["hit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
