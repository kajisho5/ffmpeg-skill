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


def die(msg: str, code: int = 1, kind: str = "input", *, ctx: "Optional[Context]" = None,
        error_extra: "Optional[Dict[str, Any]]" = None, **extra: Any) -> "None":
    """Exit with a message. Under --json also print a machine-readable failure document
    (status: failed) on stdout so callers get the same shape as a success; exit codes are unchanged.

    `extra` fields are added to the failure document: a tool whose *result* failed (check.py's
    platform rows, render.py's check stage, batch.py's per-item results, verify.py's steps) keeps
    reporting that detail while the top-level status says failed. Before 1.4.3 those four printed
    `status: "completed"` next to a non-zero exit code, so a caller keying on the status alone
    read a failed delivery as a success.

    `error_extra` goes inside `error` (refuse() passes `reason` and `details` there); the
    collector's records (warn() and friends) are merged into the document as emit() merges them."""
    hint = extra.pop("hint", None)
    ctx = ctx or STATE  # 1.10: the optional per-request Context (2.0 makes it required); STATE is the default instance
    _set_current_ctx(ctx)  # the atexit hook has no argument: it reads the ctx emit()/die() last used
    ctx.plan = None  # a failed run plans nothing (the exit hook must not write a plan for it)
    STATE.plan = None  # the hook falls back to STATE when nothing passed a ctx; a failed run plans nothing there either
    sys.stderr.write(f"error: {msg}\n" + (f"hint: {hint}\n" if hint else ""))
    if kind == "ffmpeg" and "hw" not in extra and (ctx.hw or ctx.hw_stages or ctx.hw_env_ignored or ctx.hw_auto):
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
        for key, value in (error_extra or {}).items():
            if value is not None:
                doc["error"][key] = value
        doc.update(extra)
        _merge_collector(doc, ctx)
        print_json(doc)
    sys.exit(code)


def refuse(kind: str, reason: str, msg: str, *, hint: Optional[str] = None, code: int = 1,
           ctx: "Optional[Context]" = None, extra: "Optional[Dict[str, Any]]" = None, **details: Any) -> "None":
    """die() for a refusal a caller has to act on: `error.reason` is a stable snake_case code for
    *why* (output_exists, output_is_input, output_locked, plan_inputs_changed, ...), and
    `error.details` holds the facts the message is written from (paths, expected and actual
    values), so a caller never parses the prose. `extra` adds top-level keys as die()'s do."""
    die(msg, code=code, kind=kind, ctx=ctx, hint=hint, error_extra={"reason": reason, "details": json_safe(details)}, **(extra or {}))


def _record(bucket: str, msg: str, code: str, ctx: "Optional[Context]", data: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    ctx = ctx or STATE
    entry: Dict[str, Any] = {"code": code, "message": msg}
    entry.update(data)
    # once per run: a decision taken for every encode of a job (an AV1 encoder fallback, a CRF
    # clamp) is one record, though its stderr line is printed each time it is taken
    if entry not in getattr(ctx, bucket):
        getattr(ctx, bucket).append(entry)
    sys.stderr.write(f"{prefix}{msg}\n")
    return entry


def warn(msg: str, code: str, *, ctx: "Optional[Context]" = None, **data: Any) -> Dict[str, Any]:
    """Say something went other than asked, on stderr AND in the document
    (`diagnostics.warnings`: {code, message, ...data}). Use it where a bare info("warning: ...")
    would leave the caller of --json nothing to read (a source test refuses that spelling).
    Every code is listed in the contract (`json_output.diagnostic_codes`)."""
    return _record("warnings", msg, code, ctx, data, "warning: ")


def record_fallback(msg: str, code: str, *, ctx: "Optional[Context]" = None, **data: Any) -> Dict[str, Any]:
    """The run took another route than the asked one and went on (`diagnostics.fallbacks`)."""
    return _record("fallbacks", msg, code, ctx, data, "")


def record_skip(msg: str, code: str, *, ctx: "Optional[Context]" = None, **data: Any) -> Dict[str, Any]:
    """A step that was asked for, or would normally run, did not (`diagnostics.skipped`)."""
    return _record("skipped", msg, code, ctx, data, "")


def note(msg: str, ctx: "Optional[Context]" = None) -> None:
    """A plain `notes` line that also goes to stderr."""
    ctx = ctx or STATE
    if msg not in ctx.notes:
        ctx.notes.append(msg)
    sys.stderr.write(f"{msg}\n")


def _merge_collector(doc: Dict[str, Any], ctx: "Context") -> None:
    """The collector into a result or failure document: ctx.notes join `notes` (once each), and
    the three record lists become `diagnostics`, present only when one of them is not empty
    (`warnings` and `skipped` are not top-level keys: check.py's `warnings` is a count and join.py's
    `skipped` its left-out inputs)."""
    extra_notes = [n for n in ctx.notes if n not in (doc.get("notes") or [])]
    if extra_notes:
        doc["notes"] = list(doc.get("notes") or []) + extra_notes
    diag = {k: list(getattr(ctx, k)) for k in ("warnings", "fallbacks", "skipped") if getattr(ctx, k)}
    if diag:
        merged = dict(doc.get("diagnostics") or {})
        for k, v in diag.items():
            merged[k] = list(merged.get(k) or []) + [e for e in v if e not in (merged.get(k) or [])]
        doc["diagnostics"] = merged


def audit(event: str, details: Dict[str, Any], *, default_path: Optional[str] = None, plan_sha256: Optional[str] = None,
          ctx: "Optional[Context]" = None) -> Dict[str, Any]:
    """Append one JSON line to the audit log: {ts, tool, event, pid, plan_sha256?, details}.
    The log is render.py's --audit-log FILE when given, else the event's own `default_path` (a
    plan's `<plan>.audit.jsonl`, a lock's hidden sibling); neither = nothing to write. Never under
    --dry-run (a dry run writes nothing). A write that fails is a recorded warning, never a
    failure of the run. Returns what happened, for the caller's `details.audit_log`."""
    import datetime
    ctx = ctx or STATE
    path = ctx.audit_log or default_path
    if not path:
        return {"path": None, "written": False, "reason": "no_audit_log"}
    if ctx.dry_run:
        return {"path": path, "written": False, "reason": "dry_run"}
    rec: Dict[str, Any] = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                           "tool": os.path.splitext(os.path.basename(sys.argv[0] or "?"))[0], "event": event, "pid": os.getpid()}
    if plan_sha256:
        rec["plan_sha256"] = plan_sha256
    rec["details"] = details
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(json_safe(rec), ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        warn(f"could not append the {event} record to the audit log {path} ({exc}); the run is unaffected",
             "audit_log_unwritable", ctx=ctx, path=path, event=event, error=str(exc))
        return {"path": path, "written": False, "reason": "unwritable", "error": str(exc)}
    return {"path": path, "written": True}


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
    if not requested and ctx.hw_auto:
        source = "auto"  # nobody asked: this build has no libx264/libx265, so VideoToolbox was the only encoder
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
    if ctx.hw_env_ignored and enc not in (None, "copy") and not vt:
        notes.append(env_not_for_delivery_note())
    return {"requested": requested, "source": source, "used": used,
            "fallback": bool(ctx.hw_fallback) or any(st.get("fallback") for st in stages), "notes": notes}


def hw_quality_note(enc: Optional[str], line: Optional[str], no_cpu_encoder: bool = False) -> Optional[str]:
    """The `notes` line every VideoToolbox encode carries: its quality is not the CRF encode's.
    `no_cpu_encoder`: the build has no libx264/libx265, so `--no-hw` is no remedy and is not offered."""
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
            "parity with the CPU encode" + ("" if no_cpu_encoder else "; --no-hw for the CRF encode"))


def _encoder_report(ctx: "Context") -> Dict[str, Any]:
    """`encoder`: the last video encoder this run's ffmpeg commands name (after any GPU->CPU
    fallback, since run() rewrites the recorded command), `copy` for a stream copy; absent when no
    command encoded video. `hw` (hw_report): present whenever VideoToolbox was asked for (--hw or
    $FFMPEG_SKILL_HW, a stage's, or the variable a delivery preset does not take)."""
    enc, _line = _video_encoders(ctx.commands)
    out: Dict[str, Any] = {"encoder": enc} if enc else {}
    if ctx.hw or ctx.hw_stages or ctx.hw_env_ignored or ctx.hw_auto:
        out["hw"] = hw_report(ctx, enc)
    return out


def _hw_notes_for(ctx: "Context") -> List[str]:
    """Top-level `notes` lines for the GPU encodes this result stands on: this tool's last encode,
    and (render.py) every stage that ran on VideoToolbox."""
    enc, line = _video_encoders(ctx.commands)
    out: List[str] = []
    cpu = {"h264_videotoolbox": "libx264", "hevc_videotoolbox": "libx265"}.get(enc or "")
    for note in [hw_quality_note(enc, line, cpu in ctx.hw_auto)] + [st.get("quality_note") for st in ctx.hw_stages]:
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
    quality = hw_quality_note(enc, line, hw.get("source") == "auto") if hw.get("used") else None
    ctx.hw_stages.append({"stage": stage, "requested": bool(hw.get("requested")), "source": hw.get("source"),
                          "used": hw.get("used"), "fallback": bool(hw.get("fallback")), "quality_note": quality})


def _stage_hw_notes(doc: Dict[str, Any]) -> List[str]:
    """The notes lines a stage's document carries only because of its GPU encode (its `hw.notes`
    and the VideoToolbox quality line): absorb_stage_hw() already reports those, once."""
    hw = doc.get("hw") if isinstance(doc.get("hw"), dict) else {}
    out = [str(n) for n in hw.get("notes") or []]
    enc, line = _video_encoders([str(c) for c in (doc.get("commands") or [])])
    for no_cpu in (False, True):
        q = hw_quality_note(enc, line, no_cpu)
        if q:
            out.append(q)
    return out


# A stage's own artifact checks: a stage that completed passed them (verify_output() fails the
# stage otherwise), and its artifact is an intermediate, so carrying them would only lengthen the list.
_STAGE_ARTIFACT_STEPS = ("probe", "exists")


def absorb_stage(stage: str, doc: Any, ctx: "Optional[Context]" = None) -> Dict[str, Any]:
    """A child tool's --json document into this result: its `hw` facts (absorb_stage_hw), its
    `diagnostics` records and its `notes` (each tagged with the stage it came from), and -- for a
    stage that completed in a real run -- its verification steps beyond the artifact probe, tagged
    with `stage`, which emit() adds to this result's own: the parent's `verified` is then the
    conjunction of every stage's (a stage that said `verified: false` without a failing step adds
    one `{step: verified, stage, ok: false}`). Returns the fields a re-raise of the stage's failure
    carries in its own `error`: the child's `reason` and `details`."""
    ctx = ctx or STATE
    absorb_stage_hw(stage, doc, ctx)
    if not isinstance(doc, dict):
        return {}
    for bucket in ("warnings", "fallbacks", "skipped"):
        for entry in (doc.get("diagnostics") or {}).get(bucket) or []:
            if isinstance(entry, dict):
                tagged = dict(entry, stage=entry.get("stage") or stage)
                if tagged not in getattr(ctx, bucket):
                    getattr(ctx, bucket).append(tagged)
    hw_only = _stage_hw_notes(doc)
    for n in doc.get("notes") or []:
        if not isinstance(n, str) or n in hw_only or n.endswith(ENV_HW_NOTE) or any(n.endswith(": " + h) for h in hw_only):
            continue
        # a nested stage's note (render.py inside a pack) already names its stage
        tagged_note = n if n.startswith(f"{stage}: ") else f"{stage}: {n}"
        if tagged_note not in ctx.notes:
            ctx.notes.append(tagged_note)
    if doc.get("status") == "completed" and not doc.get("dry_run") and not ctx.dry_run:
        carried = [dict(s, stage=s.get("stage") or stage) for s in doc.get("verification") or []
                   if isinstance(s, dict) and (s.get("step") not in _STAGE_ARTIFACT_STEPS or not s.get("ok"))]
        if doc.get("verified") is False and all(s.get("ok") for s in carried):
            carried.append({"step": "verified", "stage": stage, "ok": False})
        for s in carried:
            if s not in ctx.stage_verification:
                ctx.stage_verification.append(s)
    err = doc.get("error") if isinstance(doc.get("error"), dict) else {}
    return {k: err[k] for k in ("reason", "details") if err.get(k) is not None}


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


# The properties each writing tool does NOT measure about its output, by tool name: the unverified
# range U that every --json result reports (docs/contract.md "unverified"). A property listed here
# is one a caller might assume was checked; naming it is the difference between "verified" meaning
# "the listed properties were measured" and "everything is fine". Kept beside emit() so a tool
# cannot report verified without this list travelling with it.
UNVERIFIED: Dict[str, List[str]] = {
    "cut": ["picture_content"],
    "join": ["picture_content", "transition_look"],
    "fit": ["subject_framing"],
    "crop": ["subject_framing"],
    "caption": ["rendered_placement", "legibility"],
    "overlay": ["rendered_placement"],
    "graphics": ["rendered_placement"],
    "color": ["grade_look"],
    "export": ["picture_content"],
    "render": ["picture_content", "rendered_placement"],
    "silence": ["removed_span_content"],
    "audio": ["mix_balance"],
    "loudness": ["perceived_loudness"],
    "sync": ["lip_sync"],
    "multicam": ["lip_sync", "shot_choice"],
}


# a picture and its sound may differ in length by this much more than they did in the input
STREAM_LENGTH_TOLERANCE = 0.25
# how many seconds at each end of every kept stream the decode check decodes
DECODE_WINDOW_SECONDS = 1.0
# how much earlier than its window the tail decode starts reading (a seek past the last keyframe)
DECODE_SEEK_MARGIN_SECONDS = 10.0


def _expected_count(want: Any) -> int:
    """`expect_streams` values: a count, or True/False for "at least one" / "none"."""
    return int(want) if not isinstance(want, bool) else (1 if want else 0)


def stream_inventory_step(meta: Dict[str, Any], expect: Dict[str, Any]) -> Dict[str, Any]:
    """The output's stream composition checked against what the operation should have produced
    (#367: a cut of an MPEG-TS source lost its whole video stream and still said verified: true,
    because the only properties measured were duration and start skew). `expect` comes from the
    input's own probe and the tool's arguments (provenance "input_premeasurement"): a stream the
    input had and the operation was not told to drop must still be there. A value is a count
    (the cut, join and export writers map one stream of each kind) or a bool for "at least one";
    fewer streams than that is `missing`."""
    counts = meta.get("stream_counts") or {k: int(bool(meta.get(k))) for k in expect}
    want = {k: _expected_count(v) for k, v in expect.items()}
    got = {k: int(counts.get(k) or 0) if meta.get(k) else 0 for k in expect}
    missing = [k for k in expect if got[k] < want[k]]
    step: Dict[str, Any] = {"step": "streams", "property": "stream_inventory",
                            "expected": {k: want[k] > 0 for k in expect}, "measured": {k: got[k] > 0 for k in expect},
                            "expected_count": want, "measured_count": got,
                            "provenance": "input_premeasurement", "ok": not missing}
    if missing:
        step["missing"] = missing
    return step


def stream_length(meta: Dict[str, Any], kind: str) -> Optional[float]:
    """One stream's own length: its duration, else the DURATION tag Matroska/WebM keep. A value
    that is not a finite number is no length (a NaN compares false and would pass every check)."""
    s = meta.get(kind) or {}
    for v in (s.get("duration"), s.get("tagged_duration")):
        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
            return float(v)
    return None


def stream_end(meta: Dict[str, Any], kind: str) -> Optional[float]:
    """Where one stream ends on the file's timeline: its start plus its own length."""
    length = stream_length(meta, kind)
    return None if length is None else ((meta.get(kind) or {}).get("start_time") or 0.0) + length


def file_origin(meta: Dict[str, Any]) -> float:
    """Where the file's timeline starts: the container's start time, else its earliest stream's.
    A -ss, a cut's --start and a window are counted from here, while stream starts and ends are
    on the file's own timestamps."""
    if isinstance(meta.get("start_time"), (int, float)):
        return float(meta["start_time"])
    starts = [(meta.get(k) or {}).get("start_time") for k in ("video", "audio")]
    return min([s for s in starts if isinstance(s, (int, float))] or [0.0])


def stream_lengths_step(meta: Dict[str, Any], references: Sequence[Dict[str, Any]],
                        tolerance: float = STREAM_LENGTH_TOLERANCE,
                        windows: Optional[Sequence[Tuple[float, float]]] = None) -> Dict[str, Any]:
    """Where the picture and the sound of the output end, against each other, allowing the gap
    the inputs already had. A filename with a space was reported to have lost 40 s of sound with
    no error: the container's length is the longest stream's, so a duration check passes while
    one stream stops early. `short` names a stream that ends more than `tolerance` (plus the
    inputs' own shortfall, summed over the inputs) before the other one. Ends, not lengths: a
    stream that only starts late is the start-skew check's (cut.py reports it in a note). A length
    that cannot be read is not a pass (`not_measured`). `windows` (cut.py's requested ranges, on
    the input's own timeline) count only the gap the input has inside them: a source whose video
    runs 5 s past its sound allows nothing to a cut from its middle."""
    kinds = ("video", "audio")
    lengths = {k: stream_length(meta, k) for k in kinds}
    step: Dict[str, Any] = {"step": "stream_lengths", "property": "stream_end", "measured": lengths,
                            "tolerance": tolerance, "provenance": "input_premeasurement"}
    unknown = [k for k in kinds if lengths[k] is None]
    if unknown:
        return dict(step, ok=False, reason="not_measured: no length for the %s stream" % " and ".join(unknown))
    allowed: Dict[str, float] = {k: 0.0 for k in kinds}
    unread_input = False
    for ref in references:
        if not all(ref.get(k) for k in kinds):
            continue  # an input with one stream (join's silent clip) brings no gap of its own
        ref_ends = {k: stream_end(ref, k) for k in kinds}
        if None in ref_ends.values():
            unread_input = True  # its gap is unknown, not zero
            continue
        rel = {k: ref_ends[k] - file_origin(ref) for k in kinds}  # the clock cut's ranges are on
        for s, e in (windows or [(0.0, max(rel.values()))]):
            inside = {k: max(s, min(e, rel[k])) for k in kinds}
            top = max(inside.values())
            for k in kinds:
                allowed[k] += top - inside[k]
    ends = {k: stream_end(meta, k) for k in kinds}
    last = max(ends.values())
    raw = {k: last - ends[k] for k in kinds}
    short = [k for k in kinds if raw[k] > allowed[k] + tolerance]
    step.update(ends={k: round(v, 3) for k, v in ends.items()}, shortfall={k: round(v, 3) for k, v in raw.items()},
                input_shortfall={k: round(v, 3) for k, v in allowed.items()}, ok=not short)
    if short and unread_input:
        # a gap the output has may be one an input already had: neither a pass nor a "short"
        step["input_shortfall"] = None
        step["reason"] = ("not_measured: an input's stream length cannot be read, so whether the %s gap "
                          "was already in the input is unknown" % " and ".join(short))
    elif short:
        step["short"] = short
    return step


def decode_step(path: str, meta: Dict[str, Any], kinds: Sequence[str], window: float = DECODE_WINDOW_SECONDS) -> Dict[str, Any]:
    """Decode the first `window` seconds of every kept stream and the last `window` before that
    stream's own end, and count the frames. A stream ffprobe lists from the container header can
    still hold nothing a decoder accepts; the inventory and length checks read the header, this
    one reads the payload. The tail read starts DECODE_SEEK_MARGIN_SECONDS earlier, so a seek that
    lands past the last keyframe (MPEG-TS seeks by timestamp, not to a keyframe) still decodes,
    but only frames in the last `window` count, and the read stops a second past the end. A
    stream whose own end cannot be read is not decoded at its end: its tail is `not_measured`,
    not undecodable (the container's end is the longest stream's, not this one's)."""
    from _common.runner import require_tool, run_analysis
    ffmpeg = require_tool("ffmpeg")
    frames: Dict[str, Dict[str, int]] = {}
    unmeasured: List[str] = []
    for kind in kinds:
        # 0:V is the motion picture only: an attached cover picture would be 0:v:0
        sel = ["-map", "0:%s:0" % ("V" if kind == "video" else "a"), "-f", "framecrc", "-"]
        base = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error"]
        origin = file_origin(meta)
        # the head is the stream's own first window: sound that starts 2 s in has none in the file's
        head_from = max(0.0, ((meta.get(kind) or {}).get("start_time") or origin) - origin)
        head = run_analysis(base + ["-ss", "%.3f" % head_from, "-i", path, "-t", "%g" % window] + sel, check=False)
        frames[kind] = {"head": _framecrc_frames(head) if head.returncode == 0 else 0}
        # the stream's own end only: the container's is the longest stream's, and a shorter stream
        # read there would decode nothing and be called undecodable when it is only unmeasured
        end = stream_end(meta, kind)
        if end is None:
            frames[kind]["tail"] = 0
            unmeasured.append(kind)
            continue
        tail_from = max(0.0, end - origin - window - DECODE_SEEK_MARGIN_SECONDS)  # -ss counts from the origin
        # -copyts keeps the file's own timestamps, the timeline `end` is measured on
        def tail_frames(start: float) -> int:
            proc = run_analysis(base + ["-copyts", "-ss", "%.3f" % start, "-t", "%g" % (end - origin - start + 1.0), "-i", path]
                                + sel, check=False)
            return _framecrc_frames(proc, since=end - window) if proc.returncode == 0 else 0
        frames[kind]["tail"] = tail_frames(tail_from)
        if not frames[kind]["tail"] and tail_from > 0:
            # a GOP longer than the margin (long-GOP MPEG-TS) has no keyframe after tail_from: read
            # from the start before calling it undecodable (only a failing stream pays for this)
            frames[kind]["tail"] = tail_frames(0.0)
    bad = [k for k in kinds if not all(frames[k].values())]
    step: Dict[str, Any] = {"step": "decode", "property": "decodable", "frames": frames, "window": window,
                            "provenance": "measurement", "ok": not bad}
    if bad:
        step["undecodable"] = [k for k in bad if k not in unmeasured]
    if unmeasured:
        step["reason"] = "not_measured: no end time for the %s stream" % " and ".join(unmeasured)
    return step


def _framecrc_frames(proc: Any, since: Optional[float] = None) -> int:
    """Frames in ffmpeg's framecrc output; with `since`, only those still on screen at that time
    (pts plus duration: a last frame held for 2 s starts before the window and still counts). Rows
    are `stream, dts, pts, duration, size, crc`, timestamps in the `#tb N: num/den` time base."""
    tb: Dict[str, float] = {}
    n = 0
    for line in (proc.stdout or "").splitlines():
        if line.startswith("#tb "):
            idx, frac = line[4:].split(":", 1)
            num, den = frac.strip().split("/")
            tb[idx.strip()] = float(num) / float(den)
        elif line and not line.startswith("#"):
            cols = [c.strip() for c in line.split(",")]
            if since is None:
                n += 1
            elif len(cols) > 3 and cols[0] in tb and (float(cols[2]) + float(cols[3])) * tb[cols[0]] >= since - 1e-3:
                n += 1
    return n


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
        expect_streams = extra.pop("expect_streams", None)
        stream_reference = extra.pop("stream_reference", None)
        stream_windows = extra.pop("stream_windows", None)
        steps: List[Dict[str, Any]] = ([{"step": "probe", "ok": True}] if meta else []) + list(extra.pop("verification", None) or [])
        if meta and expect_streams:
            steps.append(stream_inventory_step(meta, expect_streams))
            kept = [k for k in ("video", "audio") if _expected_count(expect_streams.get(k, 0))]
            if stream_reference is not None and len(kept) == 2:
                steps.append(stream_lengths_step(meta, stream_reference, windows=stream_windows))
            present = [k for k in kept if meta.get(k)]
            if present:
                steps.append(decode_step(output, meta, present))
        # a tool that ran others (render.py) verified what its stages verified too (absorb_stage())
        steps += [s for s in ctx.stage_verification if s not in steps]
        if output and not ctx.dry_run and os.path.splitext(output)[1].lower() not in MEDIA_EXT:
            steps.insert(0, {"step": "exists", "ok": True})
        doc["verified"] = not ctx.dry_run and bool(steps) and all(s.get("ok") for s in steps)
        # a failed check asserts that something in artifact, reference, instrument or the expected
        # value's provenance is wrong; until a tool knows which, it says it does not know
        steps = [dict(s, attribution=s.get("attribution") or "unresolved") if s.get("ok") is False else s for s in steps]
        doc["verification"] = steps
        tool = os.path.splitext(os.path.basename(sys.argv[0] or ""))[0]
        if output and not ctx.dry_run and tool in UNVERIFIED and "unverified" not in extra:
            doc["unverified"] = list(UNVERIFIED[tool])
        doc.update(_encoder_report(ctx))
        doc.update(extra)
        hw_notes = [n for n in _hw_notes_for(ctx) if n not in (doc.get("notes") or [])]
        if hw_notes:
            doc["notes"] = list(doc.get("notes") or []) + hw_notes
        _merge_collector(doc, ctx)
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


def _plan_unbound_inputs(commands: Sequence[str], ctx: "Optional[Context]" = None) -> List[str]:
    """The inputs _plan_inputs() could not fingerprint because they did not exist when the plan
    was made: a planned command's `-i` file (or a side input registered through
    escape_filter_path) that is not on disk and is not written by an earlier planned command (the
    tool's own intermediates are bound by the command that makes them). render.py reports them on
    execution: nothing checks that their content is what the plan was made for."""
    import shlex
    produced: List[str] = []
    out: List[str] = []

    def consider(p: str) -> None:
        if (not p or p == "-" or p.startswith("pipe:") or os.path.exists(p)
                or os.path.abspath(p) in produced or os.path.abspath(p) in out):
            return
        out.append(os.path.abspath(p))
    for p in (ctx or STATE).plan_inputs:
        consider(p)
    for line in commands:
        try:
            toks = shlex.split(line.split("] ", 1)[1] if line.startswith("[dry-run] ") else line)
        except ValueError:
            continue
        fmt = None  # an input's -f (lavfi's "inputs" are filter graphs, not files)
        for i, tok in enumerate(toks[:-1]):
            if tok == "-f":
                fmt = toks[i + 1]
            elif tok == "-i":
                if fmt != "lavfi":
                    consider(toks[i + 1])
                fmt = None
        if toks:
            produced.append(os.path.abspath(toks[-1]))
    return out


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
        # inputs that did not exist yet, so carry no fingerprint (render.py reports them on execution)
        "unbound_inputs": _plan_unbound_inputs(ctx.commands, ctx),
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
