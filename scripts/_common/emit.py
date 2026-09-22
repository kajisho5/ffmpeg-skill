"""Result documents: die(), info(), emit(), the brief and 2.0 shapes, and the plan file.

Every script ends in exactly one of these: emit() on success, die() on failure. Both print a
single JSON document when --json is on and record the Context the caller passed.
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence
from _common.runner import Context, ERROR_CODE, ERROR_RETRYABLE, STATE


def die(msg: str, code: int = 1, kind: str = "input", *, ctx: "Optional[Context]" = None, **extra: Any) -> "None":
    """Exit with a message. Under --json also print a machine-readable failure document
    (status: failed) on stdout so callers get the same shape as a success; exit codes are unchanged.

    `extra` fields are added to the failure document: a tool whose *result* failed (check.py's
    platform rows, render.py's check stage, batch.py's per-item results, verify.py's steps) keeps
    reporting that detail while the top-level status says failed. Before 1.4.3 those four printed
    `status: "completed"` next to a non-zero exit code, so a caller keying on the status alone
    read a failed delivery as a success."""
    hint = extra.pop("hint", None)
    ctx = ctx or STATE  # 1.10: the optional per-request Context (2.0 makes it required); STATE is the default instance
    _set_current_ctx(ctx)  # the atexit hook has no argument: it reads the ctx emit()/die() last used
    ctx.plan = None  # a failed run plans nothing (the exit hook must not write a plan for it)
    STATE.plan = None  # the hook falls back to STATE when nothing passed a ctx; a failed run plans nothing there either
    sys.stderr.write(f"error: {msg}\n" + (f"hint: {hint}\n" if hint else ""))
    if ctx.json:
        doc: Dict[str, Any] = {
            "status": "failed", "exit_code": code,
            "error": {
                "kind": kind, "message": msg,
                "code": ERROR_CODE.get(kind, "INTERNAL_ERROR"),
                "retryable": ERROR_RETRYABLE,
            },
            "commands": list(ctx.commands),
        }
        if hint:
            doc["error"]["hint"] = hint
        doc.update(extra)
        print_json(doc)
    sys.exit(code)


def info(msg: str, ctx: "Optional[Context]" = None) -> None:
    # under --dry-run nothing is written; do not let scripts claim otherwise
    ctx = ctx or STATE
    if msg.startswith("wrote ") and ctx.dry_run:
        msg = "[dry-run] would write " + msg[len("wrote "):]
    sys.stderr.write(f"{msg}\n")


# The atexit plan hook takes no arguments, so emit()/die() record the Context they were given
# here; nothing passed a ctx = it stays None and the hook falls back to STATE, as before (1.10).
_CURRENT_CTX: "Optional[Context]" = None


def _set_current_ctx(ctx: "Context") -> None:
    global _CURRENT_CTX
    _CURRENT_CTX = ctx


def emit(output: Optional[str], *, ctx: "Optional[Context]" = None, **extra: Any) -> None:
    """Final stdout line: the output path, or a JSON document with --json.

    `ctx` is the optional per-request Context added in 1.10 (2.0 makes it required, issue #189 B);
    omitted, every read falls back to the process-global STATE as before."""
    ctx = ctx or STATE
    _set_current_ctx(ctx)  # so the atexit hook writes (or skips) this ctx's plan, not STATE's
    meta: Dict[str, Any] = {}
    if output and not ctx.dry_run:
        meta = verify_output(output)  # dies (status: failed, kind: output) if the artifact is unusable
    if ctx.json:
        doc: Dict[str, Any] = {"status": "completed", "output": output, "dry_run": ctx.dry_run, "commands": list(ctx.commands)}
        if meta:
            doc["probe"] = meta
        # What this tool itself verified about its artifact (issue #189 C, "verify as part of the
        # contract"): the probe every writing tool runs, plus the measurements a tool adds
        # (`verification` extra: loudness after the write, a platform check). `verified` is true
        # only when the file was written, probed, and every self-check met its target; a dry run
        # verified nothing. Spec failures the tool cannot fix on its own (export's loudness gap)
        # keep status completed and say verified: false, so a caller keys on one field.
        steps: List[Dict[str, Any]] = ([{"step": "probe", "ok": True}] if meta else []) + list(extra.pop("verification", None) or [])
        if output and not ctx.dry_run and os.path.splitext(output)[1].lower() not in MEDIA_EXT:
            steps.insert(0, {"step": "exists", "ok": True})
        doc["verified"] = not ctx.dry_run and bool(steps) and all(s.get("ok") for s in steps)
        doc["verification"] = steps
        doc.update(extra)
        if ctx.plan:
            doc["plan"] = write_plan(ctx.plan, output, extra, ctx=ctx)
        print_json(_brief(doc, meta) if ctx.json_brief else doc)
    elif ctx.plan:
        print(write_plan(ctx.plan, output, extra, ctx=ctx))
    elif output:
        print(output)


# Keys the brief document replaces or drops: the full probe (summarised), the command lines
# (counted) and the per-step verification list (its verdict stays as `verified`).
_BRIEF_DROP = ("probe", "commands", "verification")


def _brief_summary(meta: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """The handful of output facts a caller reports or branches on, from the probe this tool
    already ran -- plus the measured loudness when the tool measured one. Keys whose value is
    unknown are left out rather than emitted as null."""
    video = (meta or {}).get("video") or {}
    audio = (meta or {}).get("audio") or {}
    summary: Dict[str, Any] = {}
    duration = (meta or {}).get("duration")
    if duration is not None:
        summary["duration_s"] = round(float(duration), 3)
    for key, value in (("width", video.get("width")), ("height", video.get("height")), ("fps", video.get("fps")),
                       ("vcodec", video.get("codec")), ("acodec", audio.get("codec")), ("channels", audio.get("channels"))):
        if value is not None:
            summary[key] = value
    lufs = None
    for source, key in ((extra.get("result"), "input_i"), (extra.get("measured"), "input_i")):
        if lufs is None and isinstance(source, dict):
            lufs = _to_float(source.get(key))
    for step in extra.get("verification") or []:
        if lufs is None and isinstance(step, dict):
            lufs = _to_float(step.get("lufs"))
    # a silent file measures -inf, which json.dumps writes as the non-standard -Infinity: the
    # brief document stays valid JSON by leaving the key out instead (the full document's own
    # `measured`/`result` still carries whatever the tool reported).
    if lufs is not None and math.isfinite(lufs):
        summary["lufs"] = round(lufs, 2)
    return summary


def _brief(doc: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """--json-brief: the same success document with the bulky parts replaced by what a caller
    acts on. Same keys, same meanings -- `commands` becomes the count of the command lines,
    `probe` becomes `summary` -- plus every tool-specific key the tool itself passed to emit().
    Failures are untouched: die() prints the full failure document either way."""
    brief: Dict[str, Any] = {"status": doc["status"], "output": doc["output"], "dry_run": doc["dry_run"],
                             "verified": doc.get("verified", False)}
    summary = _brief_summary(meta, doc)
    if summary:
        brief["summary"] = summary
    brief["commands"] = len(doc.get("commands") or [])
    for key, value in doc.items():
        if key not in brief and key not in _BRIEF_DROP:
            brief[key] = value
    # the emoji report is a full inventory in the long document; brief keeps the two fields a
    # caller branches on (did colour happen, and how many)
    if isinstance(brief.get("emoji"), dict):
        brief["emoji"] = {k: v for k, v in brief["emoji"].items() if k in ("mode", "count")}
    return brief


PLAN_VERSION = 1


_PLAN_STRIP = ("--plan", "--dry-run", "--json")


def _plan_at_exit() -> None:
    ctx = _CURRENT_CTX or STATE
    if ctx.plan and not ctx.plan_written:
        try:
            write_plan(ctx.plan, None, {}, ctx=ctx)
        except SystemExit:
            pass


def _plan_inputs(commands: Sequence[str], argv: Sequence[str] = (), ctx: "Optional[Context]" = None) -> List[str]:
    """Every existing file the plan depends on: the `-i` inputs of the planned commands, any
    existing file named in argv (a recipe, a project, an SRT, a LUT, a still), and the side
    inputs tools register through escape_filter_path() (review 6: only `-i` files were bound)."""
    import shlex
    seen: List[str] = []
    for a in list(argv) + list((ctx or STATE).plan_inputs):
        if a and not a.startswith("-") and os.path.isfile(a) and a not in seen:
            seen.append(a)
    for line in commands:
        try:
            toks = shlex.split(line.split("] ", 1)[1] if line.startswith("[dry-run] ") else line)
        except ValueError:
            continue
        for i, tok in enumerate(toks[:-1]):
            if tok == "-i" and os.path.isfile(toks[i + 1]) and toks[i + 1] not in seen:
                seen.append(toks[i + 1])
    return seen


def write_plan(path: str, output: Optional[str], extra: Dict[str, Any], ctx: "Optional[Context]" = None) -> str:
    """The dry run as an artifact: what will run, on which exact inputs, producing what, checked
    how. `render.py PLAN` executes it after re-fingerprinting the inputs (issue #189 C).

    `ctx` is the Context whose commands and inputs the plan describes (emit()/die() pass the one
    they were given); omitted, it is the process-global STATE as before."""
    import datetime
    ctx = ctx or STATE
    argv = [a for a in sys.argv[1:]]
    cleaned: List[str] = []
    skip = False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in _PLAN_STRIP:
            skip = a == "--plan"
            continue
        if a.startswith("--plan="):
            continue
        cleaned.append(a)
    tool = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    verify: List[Dict[str, Any]] = [{"tool": "probe"}] if output else []
    platform = None
    if "--platform" in cleaned:
        platform = cleaned[cleaned.index("--platform") + 1]
    elif tool == "export" and "--preset" in cleaned:
        platform = {"youtube": "youtube", "youtube4k": "youtube", "reels": "reels", "x": "x"}.get(cleaned[cleaned.index("--preset") + 1])
    if platform and output and tool != "check":
        verify.append({"tool": "check", "platform": platform})
    doc = {
        "plan_version": PLAN_VERSION,
        "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": tool,
        "argv": cleaned,
        "cwd": os.getcwd(),
        "inputs": [fingerprint(p) for p in _plan_inputs(ctx.commands, cleaned, ctx)],
        "commands": list(ctx.commands),
        "output": os.path.abspath(output) if output else None,
        "verify": verify,
        "notes": list(extra.get("notes") or []),
    }
    try:
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        die(f"cannot write plan {path}: {exc}", kind="output")
    ctx.plan_written = True
    info(f"plan written: {path} ({len(doc['commands'])} command(s), {len(doc['inputs'])} input(s)); run it with render.py {path}", ctx)
    return path


def print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# Deferred for the same reason as runner's import of this module: probe needs die() from here, and
# emit() needs verify_output() from there, but only ever at call time.
from _common.probe import MEDIA_EXT, _to_float, fingerprint, verify_output  # noqa: E402
