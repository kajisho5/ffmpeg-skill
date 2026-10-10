"""Result documents: die(), info(), emit(), the brief and 2.0 shapes, and the plan file.

Every script ends in exactly one of these: emit() on success, die() on failure. Both print a
single JSON document when --json is on and record the Context the caller passed.
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
    if kind == "ffmpeg" and "hw" not in extra and (ctx.hw or ctx.hw_stages or ctx.hw_env_ignored):
        # a tool's own ffmpeg failure (cut.py runs run(check=False) and dies itself; render.py
        # re-raises a stage's) carries `encoder` and `hw` as run()'s _fail() does: under --hw /
        # $FFMPEG_SKILL_HW two encoders may have run, and a caller must know whose failure it is
        enc = extra.get("encoder") or _video_encoders(ctx.commands)[0]
        if enc and "encoder" not in extra:
            extra["encoder"] = enc
        extra["hw"] = hw_report(ctx, enc)
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


ENV_HW_NOTE = ("VideoToolbox chosen by FFMPEG_SKILL_HW=1 (machine default; ~1.1-3.5x the bytes of x264/x265 "
               "at matched quality); rerun with --no-hw for a final deliverable")
ENV_NOT_FOR_DELIVERY_BASE = ("FFMPEG_SKILL_HW=1 is not applied to export.py's delivery presets (a delivered file is where "
                             "VideoToolbox's larger files cost most)")
ENV_NOT_FOR_DELIVERY_NOTE = ENV_NOT_FOR_DELIVERY_BASE + "; pass --hw to put this export on the GPU"


def env_not_for_delivery_note() -> str:
    """The note for an export the variable left on the CPU: the advice to pass --hw only on a
    machine that can take it (the same advice on a Linux box would send the caller to a flag that
    then reports the CPU encode)."""
    from _common import decision  # the same name the --hw decisions (and their tests) stand the platform in on
    return ENV_NOT_FOR_DELIVERY_NOTE if decision.hw_platform_reason() is None else ENV_NOT_FOR_DELIVERY_BASE


def _video_encoders(commands: Sequence[str]) -> "Tuple[Optional[str], Optional[str]]":
    """(the last video encoder the command lines name, or `copy` for a stream copy; that encoder's
    command line). A later copy (loudness.py after export's encode) keeps the encode before it."""
    import re as _re
    enc, line, copied = None, None, False
    for c in commands:
        for name in _re.findall(r"(?:^|\s)-(?:c:v|vcodec|codec:v)\s+(\S+)", c):
            if name == "copy":
                copied = True
            else:
                enc, line = name, c
        if _re.search(r"(?:^|\s)-(?:c|codec)\s+copy(?:\s|$)", c):
            copied = True
    if enc is None and copied:
        return "copy", None
    return enc, line


def hw_report(ctx: "Context", enc: Optional[str]) -> Dict[str, Any]:
    """The `hw` object for a run whose last video encoder was `enc` (None: this process recorded
    no encode -- batch.py, whose stages are child processes). `requested`: VideoToolbox was asked
    for this run's encodes (by --hw, by $FFMPEG_SKILL_HW where it applies, or for a stage);
    `source`: flag|env; `used`: the encoder that ran last is VideoToolbox; `fallback`: a job
    VideoToolbox refused was re-encoded on the CPU, here or in a stage; `notes`: why. Under
    --dry-run `used` is null and `fallback` false: nothing ran."""
    stages = list(ctx.hw_stages)
    requested = bool(ctx.hw) or any(st.get("requested") for st in stages)
    source = ctx.hw_source if ctx.hw else next((st.get("source") for st in stages if st.get("requested")), None)
    if not requested and ctx.hw_env_ignored:
        source = "env"
    # a stage that reported its source without asking (export.py under the variable: requested
    # false, source env) still names where the request came from
    source = source or next((st.get("source") for st in stages if st.get("source")), None)
    vt = enc is not None and enc.endswith("_videotoolbox")
    # `used` is what ran; a dry run ran nothing (the planned encoder is `encoder`), so null --
    # as waveform.py's `silent` is null when nothing was measured
    used = None if enc is None or ctx.dry_run else vt
    notes = list(ctx.hw_notes)
    if vt and source == "env" and not any(n.endswith(ENV_HW_NOTE) for n in notes):
        # the machine default, not this call, chose the GPU: say what it costs and how to opt out
        # (once: a stage that ran on it already said so)
        notes.append(ENV_HW_NOTE)
    if ctx.hw_env_ignored and enc not in (None, "copy"):
        notes.append(env_not_for_delivery_note())
    return {"requested": requested, "source": source, "used": used,
            "fallback": bool(ctx.hw_fallback) or any(st.get("fallback") for st in stages), "notes": notes}


def hw_quality_note(enc: Optional[str], line: Optional[str]) -> Optional[str]:
    """The `notes` line every VideoToolbox encode carries: its quality is not the CRF encode's."""
    import re as _re
    if not enc or not enc.endswith("_videotoolbox"):
        return None
    if enc == "prores_videotoolbox":
        return ("prores_videotoolbox is not prores_ks: the same 422 HQ profile from a different encoder, so size and detail "
                "differ from the CPU encode; `verified` covers the output's measured properties, not parity with the CPU "
                "encode; --no-hw for prores_ks")
    m = _re.search(r"(?:^|\s)-q:v\s+(\d+)", line or "")
    return (f"{enc}{' -q:v ' + m.group(1) if m else ''} is not CRF-equivalent: --quality (or the preset's CRF) is mapped "
            "to -q:v by an approximate SSIM fit (docs/design-decisions.md), so size and detail differ from the x264/x265 "
            "encode (~1.1-3.5x the bytes at matched SSIM); `verified` covers the output's measured properties, not quality "
            "parity with the CPU encode; --no-hw for the CRF encode")


def _encoder_report(ctx: "Context") -> Dict[str, Any]:
    """`encoder`: the last video encoder this run's ffmpeg commands name (after any GPU->CPU
    fallback, since run() rewrites the recorded command), `copy` for a stream copy; absent when no
    command encoded video. `hw` (hw_report): present whenever VideoToolbox was asked for (--hw or
    $FFMPEG_SKILL_HW, a stage's, or the variable a delivery preset does not take)."""
    enc, _line = _video_encoders(ctx.commands)
    out: Dict[str, Any] = {"encoder": enc} if enc else {}
    if ctx.hw or ctx.hw_stages or ctx.hw_env_ignored:
        out["hw"] = hw_report(ctx, enc)
    return out


def _hw_notes_for(ctx: "Context") -> List[str]:
    """Top-level `notes` lines for the GPU encodes this result stands on: this tool's last encode,
    and (render.py) every stage that ran on VideoToolbox."""
    enc, line = _video_encoders(ctx.commands)
    out: List[str] = []
    for note in [hw_quality_note(enc, line)] + [st.get("quality_note") for st in ctx.hw_stages]:
        if note and note not in out:
            out.append(note)
    return out


def absorb_stage_hw(stage: str, doc: Any, ctx: "Optional[Context]" = None) -> None:
    """render.py runs each stage as a child process: carry the stage's `hw` facts (fell back, and
    why; ran on VideoToolbox, with its quality note) into this result, which records only the
    command lines."""
    ctx = ctx or STATE
    hw = doc.get("hw") if isinstance(doc, dict) else None
    if not isinstance(hw, dict):
        return
    for n in hw.get("notes") or []:
        # once: this process may have said it already (waveform.py's own encode), or another stage
        if n not in ctx.hw_notes and not any(existing.endswith(": " + n) for existing in ctx.hw_notes):
            ctx.hw_notes.append(f"{stage}: {n}")
    enc, line = _video_encoders([str(c) for c in (doc.get("commands") or [])])
    quality = hw_quality_note(enc, line) if hw.get("used") else None
    ctx.hw_stages.append({"stage": stage, "requested": bool(hw.get("requested")), "source": hw.get("source"),
                          "used": hw.get("used"), "fallback": bool(hw.get("fallback")), "quality_note": quality})


def steps_encoder_report(steps: Sequence["Tuple[str, Any]"]) -> Dict[str, Any]:
    """batch.py's per-item `encoder`, `hw` and `notes`, from the --json documents of the steps
    (child processes) that made the item: the last encoder a step ran (a later stream copy keeps
    the encode before it), and their GPU facts as render.py's result carries its stages'."""
    ctx = Context()
    ctx.dry_run = STATE.dry_run
    enc: Optional[str] = None
    for name, doc in steps:
        step_enc = doc.get("encoder") if isinstance(doc, dict) else None
        if step_enc and (step_enc != "copy" or enc is None):
            enc = step_enc
        absorb_stage_hw(name, doc, ctx)
    out: Dict[str, Any] = {"encoder": enc} if enc else {}
    if ctx.hw_stages:
        out["hw"] = hw_report(ctx, enc)
        quality = [st["quality_note"] for st in ctx.hw_stages if st.get("quality_note")]
        if quality:
            out["notes"] = list(dict.fromkeys(quality))
    return out


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
        doc.update(_encoder_report(ctx))
        doc.update(extra)
        hw_notes = [n for n in _hw_notes_for(ctx) if n not in (doc.get("notes") or [])]
        if hw_notes:
            doc["notes"] = list(doc.get("notes") or []) + hw_notes
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


def json_safe(obj: Any) -> Any:
    """Replace non-finite floats with the strings loudness.py already reports ("-inf" / "inf")
    and NaN with null: json.dumps would otherwise write -Infinity / NaN, which no strict JSON
    parser accepts (a silent file measures -inf LUFS)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None if obj != obj else ("inf" if obj > 0 else "-inf")
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(json_safe(obj), indent=2, ensure_ascii=False, allow_nan=False) + "\n")


# Deferred for the same reason as runner's import of this module: probe needs die() from here, and
# emit() needs verify_output() from there, but only ever at call time.
from _common.probe import MEDIA_EXT, _to_float, fingerprint, verify_output  # noqa: E402
