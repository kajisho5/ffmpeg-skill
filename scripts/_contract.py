#!/usr/bin/env python3
"""Machine-readable execution contract for ffmpeg-skill (internal module, not a tool).

    python3 scripts/_contract.py --json              # the contract, with detected capabilities
    python3 scripts/_contract.py --json --static     # same, without environment detection
    python3 scripts/_contract.py doctor [--json]     # which required capabilities this machine has
    ffmpeg-skill contract --json                     # the same through the npm entry point

The contract describes every public tool in scripts/ (one ToolSpec per script that does
not start with "_"): what it needs, what it takes, what it writes, how to verify the
result, and whether an agent can plan it with --dry-run. Input schemas are generated
from each script's argparse parser, so the CLI stays the single source of truth; the
per-tool facts that cannot be read from a parser (role, verification policy, required
ffmpeg components) live in TOOL_META below and are checked against the scripts by
tests/test_contract.py.

The contract has its own version (CONTRACT_VERSION) that only changes when the shape of
this document changes; the skill version comes from package.json.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL_ID = "ffmpeg-skill"
CONTRACT_VERSION = "1.0"

ROLES = {
    "analysis": "reads media and reports measurements; writes no media",
    "analysis_and_execution": "measures by default or with a flag, and can also write a transformed artifact",
    "execution": "writes a new media artifact from the input(s); the input is never modified",
    "verification": "checks or shows an artifact (probe numbers, compliance rows, contact sheets); writes no media",
}

# Facts that are not derivable from the argparse parsers. Capability names:
#   ffmpeg / ffprobe            the binaries on PATH
#   encoder:<name>              `ffmpeg -encoders`
#   filter:<name>               `ffmpeg -filters`
#   bsf:<name>                  `ffmpeg -bsfs`
#   external:whisper            a local whisper engine (whisper.cpp / faster-whisper / openai-whisper)
# "optional" entries name the flag or condition under which the capability is needed.
FF = ["ffmpeg", "ffprobe"]
X264 = "encoder:libx264"
X265 = "encoder:libx265"
AAC = "encoder:aac"
HDR_X265 = {"capability": X265, "when": "the source is HDR (kept as HEVC Main10)"}
AUDIO_OUT = [
    {"capability": "encoder:libmp3lame", "when": "output extension is .mp3"},
    {"capability": "encoder:libopus", "when": "output extension is .opus"},
    {"capability": "encoder:libvorbis", "when": "output extension is .ogg"},
    {"capability": "encoder:flac", "when": "output extension is .flac"},
]

TOOL_META: Dict[str, Dict[str, Any]] = {
    "probe": dict(role="analysis", inputs=["media (video or audio, any container ffprobe reads)"], outputs=["measurement JSON on stdout (no file)"],
                  required=["ffprobe"], optional=[{"capability": "ffmpeg", "when": "--analyze"}, {"capability": "filter:signalstats", "when": "--analyze"}],
                  video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=False, idempotency="bit_exact", deterministic=True),
    "cut": dict(role="execution", inputs=["video or audio asset"], outputs=["cut video/audio artifact (same container family, or audio extracted when -o has an audio extension)"],
                required=FF, optional=[{"capability": X264, "when": "re-encode: --accurate, VFR source, or a keyframe farther than --tolerance"}, HDR_X265, {"capability": AAC, "when": "re-encode of a video container"}] + AUDIO_OUT,
                video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "fit": dict(role="execution", inputs=["video asset"], outputs=["video artifact at the requested duration / aspect / fps"],
                required=FF + [X264, AAC], optional=[HDR_X265, {"capability": "filter:minterpolate", "when": "--smooth interpolate"}],
                video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "caption": dict(role="execution", inputs=["video asset", "SRT/ASS file or timed text (--text)"], outputs=["video artifact with burnt-in captions", "generated .srt / .ass sidecar"],
                    required=FF + [X264, AAC, "filter:subtitles"], optional=[{"capability": "filter:ass", "when": "--animate / --karaoke"}, HDR_X265, {"capability": "external:whisper", "when": "--transcribe"}],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "overlay": dict(role="execution", inputs=["video asset", "image (--image / --logo) or text (--text)"], outputs=["video artifact with the overlay composited"],
                    required=FF + [X264, AAC], optional=[{"capability": "filter:drawtext", "when": "--text"}, HDR_X265],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "graphics": dict(role="execution", inputs=["video asset"], outputs=["video artifact with the drawn template"],
                     required=FF + [X264, AAC, "filter:drawtext"], optional=[HDR_X265],
                     video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "sync": dict(role="analysis_and_execution", inputs=["reference recording (video or audio)", "second recording (video or audio)"], outputs=["offset / drift JSON on stdout", "aligned artifact with --replace-audio / --trim-second / --fix-drift -o"],
                 required=FF, optional=[{"capability": AAC, "when": "writing a video container"}] + AUDIO_OUT,
                 video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "multicam": dict(role="execution", inputs=["reference camera", "other cameras / recorders"], outputs=["switched multicam video artifact"],
                     required=FF + [X264, AAC], optional=[HDR_X265],
                     video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "audio": dict(role="execution", inputs=["video or audio asset", "music bed (--music) or replacement track (--replace)"], outputs=["artifact with the processed audio (video stream-copied, or dropped when -o has an audio extension)"],
                  required=FF + [AAC], optional=[{"capability": "filter:afftdn", "when": "--denoise / --voice"}, {"capability": "filter:sidechaincompress", "when": "--duck"},
                                                {"capability": "filter:acompressor", "when": "--compress / --voice"}, {"capability": "filter:alimiter", "when": "--limit"}, {"capability": "filter:agate", "when": "--gate"}] + AUDIO_OUT,
                  video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "loudness": dict(role="analysis_and_execution", inputs=["video or audio asset"], outputs=["loudness measurement JSON (--measure-only)", "normalised artifact (video stream-copied)"],
                     required=FF + ["filter:loudnorm", AAC], optional=AUDIO_OUT,
                     video_required=False, audio_only=True, visual=False, verify=["probe", "check"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "silence": dict(role="analysis_and_execution", inputs=["video or audio asset"], outputs=["silence list JSON (--list)", "artifact with silences removed", "EDL text (--edl)"],
                    required=FF + ["filter:silencedetect"], optional=[{"capability": X264, "when": "removing silences from a video"}, HDR_X265, {"capability": AAC, "when": "removing silences from a video"}] + AUDIO_OUT,
                    video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "join": dict(role="execution", inputs=["two or more video assets, or two or more audio-only assets"], outputs=["concatenated video artifact", "concatenated audio artifact (audio-only inputs, audio output extension)"],
                 required=FF + [X264, AAC, "filter:xfade", "filter:acrossfade"], optional=[HDR_X265] + AUDIO_OUT,
                 video_required=False, audio_only=True, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "color": dict(role="execution", inputs=["video asset", ".cube LUT (--lut)"], outputs=["video artifact with converted colour"],
                  required=FF, optional=[{"capability": X264, "when": "--to-sdr / --lut / --correct"}, {"capability": "filter:zscale", "when": "--to-sdr"}, {"capability": "filter:tonemap", "when": "--to-sdr"},
                                         {"capability": "filter:lut3d", "when": "--lut"}, {"capability": "bsf:filter_units", "when": "--strip-dovi"}, {"capability": X265, "when": "--lut on an HDR source"}, {"capability": AAC, "when": "re-encode"},
                                         {"capability": "filter:exposure", "when": "--correct"}, {"capability": "filter:eq", "when": "--correct"},
                                         {"capability": "filter:colorbalance", "when": "--correct"}, {"capability": "filter:colortemperature", "when": "--correct"}],
                  video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "export": dict(role="execution", inputs=["video asset"], outputs=["delivery artifact in the preset's format"],
                   required=FF, optional=[{"capability": X264, "when": "preset youtube / youtube4k / reels / x"}, {"capability": AAC, "when": "any preset except gif"},
                                          {"capability": X265, "when": "preset h265"}, {"capability": "encoder:prores_ks", "when": "preset prores"},
                                          {"capability": "filter:palettegen", "when": "preset gif"}, {"capability": "encoder:gif", "when": "preset gif"}],
                   video_required=True, audio_only=False, visual=False, verify=["probe", "check"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "check": dict(role="verification", inputs=["media artifact"], outputs=["compliance rows JSON on stdout (no file)"],
                  required=["ffprobe"], optional=[{"capability": "ffmpeg", "when": "loudness rows (default)"}, {"capability": "filter:loudnorm", "when": "loudness rows (default)"}],
                  video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=False, idempotency="bit_exact", deterministic=True),
    "scenes": dict(role="analysis", inputs=["video asset"], outputs=["scene / audio-peak / highlight JSON on stdout", "EDL text (--edl)", "per-scene contact sheet PNG (--sheet)"],
                   required=FF + ["filter:scdet"], optional=[{"capability": "filter:drawtext", "when": "--sheet"}, {"capability": "filter:tile", "when": "--sheet"}],
                   video_required=True, audio_only=False, visual=False, verify=[], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "look": dict(role="verification", inputs=["video artifact"], outputs=["PNG contact sheet / frames / side-by-side"],
                 required=FF + ["filter:tile"], optional=[{"capability": "filter:drawtext", "when": "timecode stamps (default; --no-timecode to skip)"}, {"capability": "filter:zscale", "when": "HDR source"}, {"capability": "filter:tonemap", "when": "HDR source"}],
                 video_required=True, audio_only=False, visual=False, verify=[], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "render": dict(role="execution", inputs=["project.json (clips, transitions, captions, overlays, audio, loudness, export, check)"], outputs=["final video artifact", "work directory of stage outputs (--keep / --work)"],
                   required=FF, optional=[{"capability": "delegated", "when": "each stage runs cut / join / fit / caption / overlay / audio / loudness / export / check with their capabilities"}],
                   video_required=True, audio_only=False, visual=True, verify=["probe", "check", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "batch": dict(role="execution", inputs=["folder of media", "batch.json recipe (steps or a render project)"], outputs=["one artifact per input file in the recipe's output_dir", "content-hash cache"],
                  required=FF, optional=[{"capability": "delegated", "when": "each recipe step runs the named script with its capabilities"}],
                  video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="cached", deterministic=True),
    "verify": dict(role="verification", inputs=["media files and/or folders"], outputs=["PASS/FAIL JSON per step", "Markdown report (--report)", "step outputs (--out / --keep)"],
                   required=FF, optional=[{"capability": "delegated", "when": "runs cut / fit / caption / export / loudness / color on each file"}],
                   video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=True, idempotency="environment_dependent", deterministic=False),
    "report": dict(role="verification", inputs=["deliverable (--after)", "source (--before)", "commands / notes text"], outputs=["single-file HTML delivery report"],
                   required=FF + ["filter:loudnorm"], optional=[{"capability": "delegated", "when": "runs look (sheets) and check (--platform)"}],
                   video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
}

# Dry-run behaviour a parser cannot express (measured in tests/test_contract.py with a fake ffmpeg
# on PATH). "analysis_only": ffmpeg still decodes/measures the input under --dry-run, but nothing
# is encoded and no file is written. Every other tool with the flag runs no ffmpeg at all.
DRY_RUN_ANALYSIS = {
    "sync": "audio is decoded to find the offset; the aligned output is not written",
    "multicam": "audio is decoded to align the cameras; the switched output is not written",
    "scenes": "scene and audio-peak measurement runs; --sheet and --edl are not written",
    "report": "probe, loudness and contact-sheet measurements run; the HTML is not written",
}
DRY_RUN_NOTES = {
    "probe": "read-only tool; --dry-run changes nothing (ffprobe still runs)",
    "check": "read-only tool; --dry-run skips the ffmpeg loudness measurement, so loudness rows are absent",
    "verify": "not supported: the flag is accepted but the steps run and outputs are written",
}

IDEMPOTENCY = {
    "bit_exact": "same inputs and flags give byte-identical output",
    "content_equivalent": "same inputs and flags give the same media content; bytes may differ between encoder builds",
    "cached": "re-runs skip inputs whose content hash and recipe are unchanged",
    "environment_dependent": "output includes timings or machine state and differs between runs",
}


# ----------------------------------------------------------------------------- parsers
class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


def _capture_parser(script: Path) -> argparse.ArgumentParser:
    """Import the script and run main() until parse_args() to get its live parser."""
    original = argparse.ArgumentParser.parse_args

    def fake_parse(self: argparse.ArgumentParser, *a: Any, **k: Any) -> Any:
        raise _Captured(self)

    argparse.ArgumentParser.parse_args = fake_parse  # type: ignore[assignment]
    sys_argv = sys.argv
    try:
        sys.argv = [str(script)]
        spec = importlib.util.spec_from_file_location("ffskill_tool_" + script.stem, script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.main()
    except _Captured as cap:
        return cap.parser
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[assignment]
        sys.argv = sys_argv
    raise RuntimeError(f"{script.name}: main() returned before parse_args()")


def _json_type(action: argparse.Action) -> Dict[str, Any]:
    if isinstance(action, argparse._StoreTrueAction):
        return {"type": "boolean"}
    if isinstance(action, argparse._AppendAction) or action.nargs in ("+", "*"):
        return {"type": "array", "items": {"type": "string"}}
    if action.type is int:
        return {"type": "integer"}
    if action.type is float:
        return {"type": "number"}
    return {"type": "string"}


def input_schema(parser: argparse.ArgumentParser) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []
    positional: List[str] = []
    common = {"dry_run", "json", "progress", "fast"}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        prop: Dict[str, Any] = _json_type(action)
        if action.help and action.help != argparse.SUPPRESS:
            prop["description"] = action.help % {"default": action.default} if "%(default)" in action.help else action.help
        if action.choices:
            prop["enum"] = list(action.choices)
        if action.default not in (None, False, argparse.SUPPRESS):
            prop["default"] = action.default
        if action.option_strings:
            prop["cli"] = list(action.option_strings)
            if action.required:
                required.append(action.dest)
        else:
            prop["cli"] = "positional"
            positional.append(action.dest)
            if action.nargs not in ("?", "*"):
                required.append(action.dest)
        if action.dest in common:
            prop["common"] = True
        props[action.dest] = prop
    groups = [g for g in getattr(parser, "_mutually_exclusive_groups", []) if g._group_actions]
    schema: Dict[str, Any] = {"type": "object", "properties": props, "required": required, "positional": positional, "additionalProperties": False}
    if groups:
        schema["mutually_exclusive"] = [[a.dest for a in g._group_actions] for g in groups]
        schema["one_of_required"] = [[a.dest for a in g._group_actions] for g in groups if g.required]
    return schema


def output_schema(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """What the tool prints on stdout with --json (keys observed in the implementation)."""
    if name == "probe":
        return {"type": "object", "description": "one probe document, or an array of them for several inputs",
                "properties": {"file": {"type": "string"}, "format": {"type": "string"}, "duration": {"type": "number"}, "size_bytes": {"type": "integer"},
                               "video": {"type": ["object", "null"]}, "audio": {"type": ["object", "null"]}}, "additionalProperties": True}
    base = {"status": {"enum": ["completed"]}, "output": {"type": ["string", "null"], "description": "path written, or null"},
            "dry_run": {"type": "boolean"}, "commands": {"type": "array", "items": {"type": "string"}, "description": "every ffmpeg command line planned or run"},
            "probe": {"type": "object", "description": "probe of the output when a file was written"}}
    extra: Dict[str, Any] = {}
    if name == "check":
        extra = {"platform": {"type": "string"}, "ok": {"type": "boolean"}, "failed": {"type": "integer"}, "warnings": {"type": "integer"},
                 "checks": {"type": "array", "items": {"type": "object", "properties": {"check": {"type": "string"}, "status": {"enum": ["PASS", "WARN", "FAIL"]}, "value": {}, "expected": {}, "fix": {"type": "string"}, "kind": {"enum": ["format", "judgement"]}}}}}
    elif name == "scenes":
        extra = {"file": {"type": "string"}, "duration": {"type": "number"}, "scene_count": {"type": "integer"}, "scenes": {"type": "array"}, "audio_peaks": {"type": "array"}}
    elif name == "silence":
        extra = {"silences": {"type": "array"}, "keep": {"type": "array"}, "input_duration": {"type": "number"}, "kept_duration": {"type": "number"}, "removed_seconds": {"type": "number"}}
    elif name == "sync":
        extra = {"reference": {"type": "string"}, "second": {"type": "string"}, "offset_seconds": {"type": "number"}, "confidence": {"type": "number"}, "meaning": {"type": "string"}, "drift": {"type": "object"}}
    elif name == "look":
        extra = {"outputs": {"type": "array", "items": {"type": "string"}}}
    elif name == "render":
        extra = {"stages": {"type": "array", "items": {"type": "string"}}, "check": {"type": ["object", "null"]}}
    elif name == "verify":
        extra = {"report": {"type": ["string", "null"]}, "files": {"type": "array"}, "failed": {"type": "integer"}, "total": {"type": "integer"}}
    elif name == "batch":
        extra = {"results": {"type": "array"}, "processed": {"type": "integer"}, "total": {"type": "integer"}}
    elif name == "report":
        extra = {"report": {"type": "string"}, "check": {"type": ["object", "null"]}}
    elif name == "loudness":
        extra = {"measured": {"type": "object", "description": "--measure-only prints the loudnorm measurement instead (input_i, input_tp, input_lra, input_thresh, target_offset)"}}
    elif name == "cut":
        extra = {"expected_duration": {"type": "number", "description": "seconds requested"},
                 "duration_error_ms": {"type": ["number", "null"], "description": "written minus requested, measured by ffprobe (null under --dry-run)"},
                 "precision": {"enum": ["packet", "sample", "codec_frame", "frame"],
                               "description": "packet: stream copy on a packet/keyframe boundary; sample: decoded audio trimmed to the sample, lossless output; codec_frame: sample-trimmed then framed by a lossy encoder (priming delay adds to the length); frame: re-encoded video"},
                 "reencoded": {"type": "boolean"}}
    elif name == "join":
        extra = {"mode": {"enum": ["video", "audio"]}, "clips": {"type": "integer"}, "transition": {"type": "string"}, "expected_duration": {"type": "number"},
                 "sample_rate": {"type": "integer", "description": "audio mode only"}, "channels": {"type": "integer", "description": "audio mode only"},
                 "video": {"type": "boolean", "description": "false in audio mode: the output has no video stream"}}
    elif name == "audio":
        extra = {"video": {"type": "boolean", "description": "true when the input's video stream was copied; false for an audio output extension (extraction)"},
                 "audio_stream": {"type": "integer", "description": "which input audio stream was processed (--audio-stream)"},
                 "dynamics": {"type": "array", "items": {"enum": ["agate", "acompressor", "alimiter"]}, "description": "typed dynamics filters applied, in graph order"}}
    props = dict(base)
    props.update(extra)
    required = ["status", "output", "dry_run", "commands"]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": True}


# ----------------------------------------------------------------------------- environment
def skill_version() -> str:
    for candidate in (ROOT / "package.json",):
        try:
            return str(json.loads(candidate.read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError):
            continue
    return "unknown"


def skill_description() -> str:
    try:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^description:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def public_tools() -> List[str]:
    return sorted(p.stem for p in HERE.glob("*.py") if not p.name.startswith("_"))


# `ffmpeg -filters` rows: FFmpeg <= 7 prints three flag characters (`..C acompressor A->A ...`),
# FFmpeg 8 prints two (`T. acompressor A->A ...`). The row is recognised by its io-spec token
# (`A->A`, `|->V`, `N->N`, ...) so the flag width does not matter; a legend line never carries `->`.
_FILTER_ROW = re.compile(r"^\s*(?:[A-Z.]{1,6}\s+)?([A-Za-z0-9_]+)\s+(\S*->\S*)(?:\s|$)")
# `ffmpeg -encoders` rows follow a ` ------` separator: flags (six characters today; any width of
# letters and dots is accepted) then the encoder name. A legend line has `=` where the name would be.
_ENCODER_ROW = re.compile(r"^\s*[A-Z.]{2,10}\s+([A-Za-z0-9_-]+)(?:\s|$)")
_LIST_SEPARATOR = re.compile(r"^\s*-{3,}\s*$")


def _parse_ff_list(flag: str, text: str) -> List[str]:
    """Names in the stdout of `ffmpeg <flag>`; empty when no row was recognised."""
    names: List[str] = []
    if flag == "-filters":
        for line in text.splitlines():
            m = _FILTER_ROW.match(line)
            if m:
                names.append(m.group(1))
    elif flag == "-encoders":
        lines = text.splitlines()
        sep = next((i for i, l in enumerate(lines) if _LIST_SEPARATOR.match(l)), None)
        rows = lines[sep + 1:] if sep is not None else lines
        for line in rows:
            m = _ENCODER_ROW.match(line)
            if m and m.group(1) != "=":
                names.append(m.group(1))
    elif flag == "-bsfs":
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 1 and not parts[0].endswith(":"):
                names.append(parts[0])
    return names


def _ff_listing(binary: str, flag: str) -> Dict[str, Any]:
    """`{"names": [...], "status": parsed | unparsed | failed | missing, "detail": str}` for `ffmpeg <flag>`.

    `parsed`: rows recognised. `unparsed`: ffmpeg ran but no row matched, so the capabilities it
    covers are unknown, not absent. `failed`: ffmpeg exited non-zero. `missing`: no binary on PATH.
    """
    exe = shutil.which(binary)
    if not exe:
        return {"names": [], "status": "missing", "detail": f"{binary} not on PATH"}
    try:
        proc = subprocess.run([exe, "-hide_banner", flag], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        return {"names": [], "status": "failed", "detail": f"{binary} {flag}: {e}"}
    if proc.returncode != 0:
        tail = " ".join(proc.stderr.strip().splitlines()[-2:])
        return {"names": [], "status": "failed", "detail": f"{binary} {flag} exited {proc.returncode}: {tail}"}
    names = _parse_ff_list(flag, proc.stdout)
    if not names:
        return {"names": [], "status": "unparsed", "detail": f"no row recognised in `{binary} {flag}` output ({len(proc.stdout.splitlines())} lines)"}
    return {"names": names, "status": "parsed", "detail": f"{len(names)} entries"}


def _ff_list(binary: str, flag: str) -> List[str]:
    """Names from `ffmpeg -encoders` / `-filters` / `-bsfs` (empty list when ffmpeg is missing or unparsed)."""
    return _ff_listing(binary, flag)["names"]


def _version_line(binary: str) -> Optional[str]:
    exe = shutil.which(binary)
    if not exe:
        return None
    proc = subprocess.run([exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    first = (proc.stdout or proc.stderr).splitlines()[:1]
    m = re.match(rf"{binary} version (\S+)", first[0]) if first else None
    return m.group(1) if m else (first[0] if first else "unknown")


def _whisper_available() -> bool:
    if shutil.which("whisper-cli") or shutil.which("whisper-cpp") or shutil.which("whisper"):
        return True
    return importlib.util.find_spec("faster_whisper") is not None or importlib.util.find_spec("whisper") is not None


def required_capabilities() -> Dict[str, List[str]]:
    req: set = set()
    opt: set = set()
    for meta in TOOL_META.values():
        req.update(meta["required"])
        opt.update(o["capability"] for o in meta["optional"] if o["capability"] != "delegated")
    opt -= req
    return {"required": sorted(req), "optional": sorted(opt)}


def doctor() -> Dict[str, Any]:
    """Detect which declared capabilities this machine has. No secrets, no environment variables.

    Three states per capability: available, missing, unknown. `unknown` means the ffmpeg listing
    that would prove it could not be read (unparsed output, ffmpeg failure); it is never folded into
    `missing` (a filter that exists is not reported absent) nor into `available` (a failed detection
    is not a pass). `ok` is true only when nothing required is missing or unknown.
    """
    listings = {
        "encoders": _ff_listing("ffmpeg", "-encoders"),
        "filters": _ff_listing("ffmpeg", "-filters"),
        "bsfs": _ff_listing("ffmpeg", "-bsfs"),
    }
    sets = {k: set(v["names"]) for k, v in listings.items()}
    state: Dict[str, str] = {}  # capability -> available | missing | unknown
    wanted = required_capabilities()

    def _from(kind: str, name: str) -> str:
        lst = listings[kind]
        if lst["status"] == "parsed":
            return "available" if name in sets[kind] else "missing"
        if lst["status"] == "missing":
            return "missing"  # no ffmpeg at all: nothing it provides is available
        return "unknown"

    for cap in wanted["required"] + wanted["optional"]:
        if cap == "ffmpeg":
            state[cap] = "available" if shutil.which("ffmpeg") else "missing"
        elif cap == "ffprobe":
            state[cap] = "available" if shutil.which("ffprobe") else "missing"
        elif cap.startswith("encoder:"):
            state[cap] = _from("encoders", cap[8:])
        elif cap.startswith("filter:"):
            state[cap] = _from("filters", cap[7:])
        elif cap.startswith("bsf:"):
            state[cap] = _from("bsfs", cap[4:])
        elif cap == "external:whisper":
            state[cap] = "available" if _whisper_available() else "missing"
        else:
            state[cap] = "missing"
    available = sorted(c for c, st in state.items() if st == "available")
    missing_required = sorted(c for c in wanted["required"] if state[c] == "missing")
    missing_optional = sorted(c for c in wanted["optional"] if state[c] == "missing")
    unknown = sorted(c for c, st in state.items() if st == "unknown")
    unknown_required = [c for c in unknown if c in wanted["required"]]
    errors = [f"{k}: {v['detail']}" for k, v in listings.items() if v["status"] in ("unparsed", "failed")]
    return {
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "ffmpeg": _version_line("ffmpeg"),
        "ffprobe": _version_line("ffprobe"),
        "available": available,
        "missing": missing_required,
        "missing_optional": missing_optional,
        "unknown": unknown,
        "detection": {k: {"status": v["status"], "count": len(v["names"]), "detail": v["detail"]} for k, v in listings.items()},
        "errors": errors,
        "ok": not missing_required and not unknown_required,
    }


# ----------------------------------------------------------------------------- contract
def tool_spec(name: str, version: str) -> Dict[str, Any]:
    if name not in TOOL_META:
        # a public script without metadata is drift: fail loudly instead of guessing its role or capabilities
        raise RuntimeError(f"scripts/{name}.py is public but has no TOOL_META entry in scripts/_contract.py; add one (or prefix the file with '_')")
    meta = TOOL_META[name]
    parser = _capture_parser(HERE / f"{name}.py")
    schema = input_schema(parser)
    # structured key -> CLI flag where key.replace("_", "-") is not the long option (MCP uses the same table)
    exceptions: Dict[str, str] = {}
    for dest, prop in schema["properties"].items():
        if prop["cli"] == "positional":
            continue
        longs = [f for f in prop["cli"] if f.startswith("--")]
        if dest == "output":
            exceptions[dest] = "-o"
        elif name == "loudness" and dest == "lufs":
            exceptions[dest] = "-I"
        elif "--" + dest.replace("_", "-") not in longs:
            exceptions[dest] = longs[0] if longs else prop["cli"][0]
    supports_dry_run = "dry_run" in schema["properties"] and name != "verify"
    return {
        "id": f"{SKILL_ID}/{name}",
        "name": name,
        "version": version,
        "description": (parser.description or "").strip().splitlines()[0] if parser.description else "",
        "executable": f"scripts/{name}.py",
        "role": meta["role"],
        "capabilities": {"required": list(meta["required"]), "optional": list(meta["optional"])},
        "inputs": list(meta["inputs"]),
        "outputs": list(meta["outputs"]),
        "input_schema": schema,
        "output_schema": output_schema(name, meta),
        "supports_dry_run": supports_dry_run,
        "dry_run": {"supported": supports_dry_run,
                    "ffmpeg_execution": "full" if not supports_dry_run else "analysis_only" if name in DRY_RUN_ANALYSIS else "none",
                    "semantics": "prints the ffmpeg command lines that would run; no output file is written",
                    **({"note": DRY_RUN_ANALYSIS.get(name) or DRY_RUN_NOTES[name]} if name in DRY_RUN_ANALYSIS or name in DRY_RUN_NOTES else {})},
        "supports_json": "json" in schema["properties"],
        "mutates_input": False,
        "produces_artifact": meta["produces_artifact"],
        "verification": {"required": bool(meta["verify"]), "tools": [f"{SKILL_ID}/{t}" for t in meta["verify"]]},
        "requires_visual_verification": meta["visual"],
        "audio_only": meta["audio_only"],
        "video_required": meta["video_required"],
        "deterministic_inputs": meta["deterministic"],
        "idempotency_hint": meta["idempotency"],
        "mcp": {"tool": name, "positional": schema["positional"], "argument_exceptions": exceptions},
    }


# ----------------------------------------------------------------------------- MCP derivation
# tools that print JSON without --json (probe) or whose primary output is a file path (look): the transport
# does not append --json for them (stated in invocation.structured.argument_mapping.json)
MCP_JSON_EXEMPT = ("look", "probe")
MCP_STRUCTURED_NOTE = ("Structured arguments: keys are the input_schema property names (argparse dests), positionals "
                       "are passed by name, output -> -o. Or argv: the raw CLI list (non-canonical; all other keys are then ignored). "
                       "Media paths must be absolute.")


def mcp_input_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a ToolSpec.input_schema into the JSON Schema an MCP tools/list entry carries.

    Deterministic and lossless where JSON Schema can express argparse semantics:
      - properties keep type / enum / default / description / items; the ffmpeg-skill-only keys
        (`cli`, `common`) are dropped, positionals get a "(positional N)" prefix in the description;
      - required fields, mutually exclusive groups (`not required [a, b]` per pair) and required
        groups (`anyOf required`) apply to the structured branch;
      - the raw-argv compatibility branch (`argv` present) lifts those constraints, which JSON Schema
        expresses as a top-level anyOf of the two branches.
    Not expressible and therefore documented rather than encoded: which keys the tool ignores when
    `argv` is given (all of them), and argparse's `%(default)s` help interpolation (already applied).
    """
    src = spec["input_schema"]
    props: Dict[str, Any] = {}
    positional = list(src.get("positional", []))
    for dest in sorted(src["properties"]):
        p = src["properties"][dest]
        out: Dict[str, Any] = {"type": p["type"]}
        if p["type"] == "array":
            out["items"] = dict(p.get("items", {"type": "string"}))
        desc = p.get("description", "")
        if dest in positional:
            desc = f"(positional {positional.index(dest) + 1}) {desc}".strip()
        if desc:
            out["description"] = desc
        for key in ("enum", "default"):
            if key in p:
                out[key] = p[key]
        props[dest] = out
    props["argv"] = {"type": "array", "items": {"type": "string"}, "description": "raw CLI arguments (non-canonical compatibility path; when present every other key is ignored)"}
    structured: Dict[str, Any] = {}
    if src.get("required"):
        structured["required"] = list(src["required"])
    all_of: List[Dict[str, Any]] = []
    for group in src.get("mutually_exclusive", []):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                all_of.append({"not": {"required": [a, b]}})
    if all_of:
        structured["allOf"] = all_of
    one_of = [[{"required": [d]} for d in group] for group in src.get("one_of_required", [])]
    if one_of:
        structured["anyOf"] = one_of[0] if len(one_of) == 1 else [{"allOf": [{"anyOf": g} for g in one_of]}]
    schema: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if structured:
        schema["anyOf"] = [{"required": ["argv"]}, structured]
    return schema


def mcp_tool(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The MCP tools/list entry for a ToolSpec: name, description and the derived inputSchema."""
    return {"name": spec["name"], "description": f"{spec['description']} {MCP_STRUCTURED_NOTE}".strip(), "inputSchema": mcp_input_schema(spec)}


def mcp_tools(detect: bool = False) -> List[Dict[str, Any]]:
    return [mcp_tool(spec) for spec in build(detect=detect)["tools"]]


def build(detect: bool = True) -> Dict[str, Any]:
    version = skill_version()
    tools = [tool_spec(n, version) for n in public_tools()]
    wanted = required_capabilities()
    caps: Dict[str, Any] = {"required": wanted["required"], "optional": wanted["optional"], "naming": "ffmpeg | ffprobe | encoder:<name> | filter:<name> | bsf:<name> | external:whisper"}
    if detect:
        d = doctor()
        caps.update({"available": d["available"], "missing": d["missing"], "missing_optional": d["missing_optional"],
                     "unknown": d["unknown"], "detection": d["detection"], "detected_by": "doctor"})
    return {
        "contract_version": CONTRACT_VERSION,
        "skill": {
            "id": SKILL_ID,
            "version": version,
            "description": skill_description(),
            "execution_mode": "local",
            "kind": "execution",
            "entrypoints": {
                "cli": "python3 scripts/<tool>.py [args] [--json] [--dry-run]",
                "mcp": "python3 mcp/server.py (stdio JSON-RPC; tools/list == this tool list)",
                "contract": "python3 scripts/_contract.py --json  |  ffmpeg-skill contract --json",
                "doctor": "python3 scripts/_contract.py doctor --json  |  ffmpeg-skill doctor --json",
            },
            "not_provided": ["AI reasoning", "decisions", "production plans", "project IR", "approvals", "network access", "transcription engine"],
        },
        "requirements": {"python": ">=3.9 (standard library only)", "ffmpeg": ">=5.0", "ffprobe": ">=5.0", "node": ">=16 (npx installer only)"},
        "execution": {
            "shell": False,
            "arbitrary_executables": False,
            "subprocess": "argv list only: [python3, scripts/<tool>.py, ...] and [ffmpeg|ffprobe, ...] resolved from PATH",
            "network": False,
            "input_mutation": False,
        },
        "invocation": {
            "structured": {
                "canonical": True,
                "transports": ["cli", "mcp"],
                "argument_mapping": {
                    "positional": "listed in input_schema.positional, in order; array values expand to several arguments",
                    "options": "key -> --key with '_' replaced by '-'; booleans are flags; arrays repeat the flag; input_schema.properties[key].cli lists the accepted spellings",
                    "exceptions": "per tool in mcp.argument_exceptions (key -> flag), e.g. output -> -o, loudness.lufs -> -I, graphics.count_from -> --from",
                    "json": "--json is appended for every tool except look and probe (probe prints JSON by default)",
                },
            },
            "raw_argv": {"canonical": False, "transports": ["mcp"], "note": "MCP tools also accept {\"argv\": [...]} for CLI compatibility; it is still bound to the named script, never a shell"},
        },
        "roles": ROLES,
        "idempotency_hints": IDEMPOTENCY,
        "verification_policy": {
            "probe_first": "run ffmpeg-skill/probe on every input before planning",
            "verify_last": "run the tools named in each ToolSpec.verification after it wrote an artifact",
            "visual": "when requires_visual_verification is true, run ffmpeg-skill/look on the output and inspect the PNG",
            "audio_only": "audio-only inputs and audio-only tools never need ffmpeg-skill/look",
            "check_rows": "ffmpeg-skill/check rows carry kind=format (fix) or kind=judgement (decide with the user)",
        },
        "json_output": {
            "success": {"status": "completed", "exit_code": 0, "stdout": "one JSON document (output_schema)"},
            "failure": {"status": "failed", "exit_code": "non-zero (127 when ffmpeg/ffprobe is missing)", "stdout": "{\"status\": \"failed\", \"error\": {\"kind\": ..., \"message\": ...}} when --json was given", "stderr": "human-readable message"},
            "error_kinds": {"input": "missing or unsuitable input, bad arguments", "ffmpeg": "ffmpeg/ffprobe returned an error", "missing_tool": "ffmpeg or ffprobe not on PATH"},
        },
        "capabilities": caps,
        "tools": tools,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["contract", "doctor"], default="contract")
    ap.add_argument("--json", action="store_true", help="JSON on stdout (the contract is always JSON)")
    ap.add_argument("--static", action="store_true", help="omit environment detection (available / missing capabilities)")
    args = ap.parse_args()
    if args.command == "doctor":
        d = doctor()
        if args.json:
            print(json.dumps(d, indent=2, sort_keys=True))
        else:
            print(f"python {d['python']}; ffmpeg {d['ffmpeg'] or 'MISSING'}; ffprobe {d['ffprobe'] or 'MISSING'}")
            print(f"available: {', '.join(d['available'])}")
            print(f"missing required: {', '.join(d['missing']) or 'none'}")
            print(f"missing optional: {', '.join(d['missing_optional']) or 'none'}")
            if d["unknown"]:
                print(f"unknown (detection failed, not proven missing): {', '.join(d['unknown'])}")
            for err in d["errors"]:
                print(f"detection error: {err}", file=sys.stderr)
        if d["ok"]:
            return 0
        # 1: something required is missing; 2: nothing proven missing but a required capability is unknown
        return 1 if d["missing"] else 2
    print(json.dumps(build(detect=not args.static), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
