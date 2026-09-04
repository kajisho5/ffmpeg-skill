#!/usr/bin/env python3
"""ffmpeg-skill as an MCP server (stdio, JSON-RPC 2.0) — standard library only.

Every script in ../scripts becomes a tool; arguments are passed as an argv list
or as a flat object of flags. Results are the script's --json output.

Run:
  python3 mcp/server.py                         # stdio transport
Claude Desktop / Claude Code config example:
  {"mcpServers": {"ffmpeg-skill": {"command": "python3", "args": ["/path/to/ffmpeg-skill/mcp/server.py"]}}}
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
PROTOCOL_VERSION = "2024-11-05"

TOOLS: Dict[str, str] = {
    "probe": "Inspect a media file: duration, fps/VFR, resolution, codecs, HDR, rotation, audio. Args: inputs (list), analyze (bool), compact (bool).",
    "cut": "Cut a range or several segments, lossless when possible. Args: input, start, end, duration, segments, accurate, output.",
    "fit": "Fit to a duration (speed/trim) and/or aspect (pad/crop). Args: input, duration, method, aspect, fit, width, fps, smooth, output.",
    "caption": "Burn SRT/ASS or timed text; animated/karaoke styles; brand. Args: input, srt, ass, text, animate, karaoke, font, size, position, brand, output.",
    "overlay": "Composite a logo/image/text with timing and fade. Args: input, image, text, logo, position, start, end, fade, opacity, scale, brand, output.",
    "graphics": "Motion-graphics templates: lower-third, title, chapter, progress, countdown, bug. Args: input, template, name, title, subtitle, start, end, brand, output.",
    "sync": "Detect offset between two recordings by audio, optional drift fix. Args: reference, second, fix_drift, replace_audio, trim_second, output.",
    "multicam": "Align N cameras/recorders and switch between them. Args: inputs (list), switch, auto, audio, fix_drift, output.",
    "audio": "Denoise/voice chain, music bed with ducking, fades, downmix, replace. Args: input, voice, denoise, music, duck, music_volume, fade_in, fade_out, downmix, replace, output.",
    "loudness": "Two-pass EBU R128 normalisation. Args: input, lufs, tp, measure_only, output.",
    "silence": "Remove dead air / list silences. Args: input, threshold, min_silence, margin, list, edl, output.",
    "join": "Concatenate clips with transitions, normalising size/fps/audio. Args: inputs (list), transition, duration, width, height, fps, output.",
    "color": "HDR→SDR tone mapping, LUTs, retag, strip Dolby Vision. Args: input, to_sdr, lut, retag, strip_dovi, tonemap, output.",
    "export": "Platform presets: youtube, youtube4k, reels, x, prores, h265, gif. Args: input, preset, fit, output.",
    "check": "Pre-delivery compliance per platform. Args: input, platform, no_loudness.",
    "scenes": "Scene changes, audio peaks, highlight proposals. Args: input, highlights, target, edl, sheet.",
    "look": "Contact sheet / frames / before-after PNG for visual checks. Args: input, at (list), tiles, compare, output.",
    "render": "Render a whole edit from project.json. Args: project, fast, stop_after, init.",
    "batch": "Apply a step recipe or render project to every file in a folder (content-hash cached). Args: folder, recipe, force, watch, work.",
    "verify": "Run the toolchain on real files and report PASS/FAIL. Args: paths (list), quick, report.",
    "report": "HTML delivery report. Args: after, before, platform, commands, notes, title, output.",
}
POSITIONAL = {"probe": ["inputs"], "sync": ["reference", "second"], "multicam": ["inputs"], "join": ["inputs"], "verify": ["paths"], "render": ["project"], "batch": ["folder"]}


def build_argv(name: str, args: Dict[str, Any]) -> List[str]:
    if isinstance(args.get("argv"), list):
        argv = [str(a) for a in args["argv"]]
        if name not in ("look", "probe") and "--json" not in argv and "--help" not in argv:
            argv.append("--json")
        return argv
    argv: List[str] = []
    args = dict(args)
    pos = POSITIONAL.get(name, ["input"])
    for key in pos:
        val = args.pop(key, None)
        if val is None:
            continue
        if isinstance(val, list):
            argv += [str(v) for v in val]
        else:
            argv.append(str(val))
    for key, val in args.items():
        if val is None or val is False:
            continue
        flag = "--" + key.replace("_", "-")
        if key == "output":
            flag = "-o"
        if key == "lufs" and name == "loudness":
            flag = "-I"
        if val is True:
            argv.append(flag)
        elif isinstance(val, list):
            for v in val:
                argv += [flag, str(v)]
        else:
            argv += [flag, str(val)]
    if name not in ("look", "probe") and "--json" not in argv and "--help" not in argv:
        argv.append("--json")
    return argv


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    script = SCRIPTS / f"{name}.py"
    if not script.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"unknown tool {name}"}]}
    argv = build_argv(name, args or {})
    proc = subprocess.run([sys.executable, str(script)] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout = proc.stdout.strip()
    text = stdout
    structured = None
    try:
        structured = json.loads(stdout) if stdout.startswith("{") or stdout.startswith("[") else None
    except ValueError:
        structured = None
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()
        tail = "\n".join(err[-12:])
        return {"isError": True, "content": [{"type": "text", "text": f"{name} failed (exit {proc.returncode})\n{tail}"}]}
    if structured is None:
        text = stdout or "\n".join(proc.stderr.strip().splitlines()[-5:])
    result: Dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if structured is not None:
        result["structuredContent"] = structured if isinstance(structured, dict) else {"result": structured}
    return result


def tool_list() -> List[Dict[str, Any]]:
    out = []
    for name, desc in TOOLS.items():
        out.append({
            "name": name,
            "description": desc + " Pass either named args (flags without dashes, underscores for hyphens) or argv (raw CLI list). Media paths must be absolute.",
            "inputSchema": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}, "description": "raw CLI arguments"}}, "additionalProperties": True},
        })
    return out


def handle(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": "ffmpeg-skill", "version": version()}}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        return call_tool(params.get("name", ""), params.get("arguments") or {})
    if method == "ping":
        return {}
    raise KeyError(method)


def version() -> str:
    try:
        return json.loads((HERE.parent / "package.json").read_text())["version"]
    except Exception:
        return "0"


def main() -> int:
    if "--list" in sys.argv:
        for t in tool_list():
            print(f"{t['name']:10s} {t['description'].split(' Pass either')[0]}")
        return 0
    if "--call" in sys.argv:  # debugging helper: --call NAME '{"input": "..."}'
        i = sys.argv.index("--call")
        name = sys.argv[i + 1]
        args = json.loads(sys.argv[i + 2]) if len(sys.argv) > i + 2 else {}
        print(json.dumps(call_tool(name, args), indent=2))
        return 0
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if "id" not in req:  # notification
            continue
        try:
            result = handle(req)
            resp = {"jsonrpc": "2.0", "id": req["id"], "result": result}
        except KeyError as exc:
            resp = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": f"method not found: {exc}"}}
        except Exception as exc:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": str(exc)}}
        stdout.write((json.dumps(resp) + "\n").encode("utf-8"))
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
