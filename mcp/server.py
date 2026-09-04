#!/usr/bin/env python3
"""ffmpeg-skill as an MCP server (stdio, JSON-RPC 2.0) — standard library only.

Every public script in ../scripts becomes a tool. Tool names, order, inputSchema and the
structured-argument mapping all come from the contract (scripts/_contract.py); this file
is only the transport. Arguments are passed as a flat object (keys = argparse dests) or,
for CLI compatibility, as an argv list. Results are the script's --json output.

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

sys.path.insert(0, str(SCRIPTS))
import _contract  # noqa: E402  (the contract is the only source of tool names, schemas and argument mapping)

_SPECS: Dict[str, Dict[str, Any]] = {}


def specs() -> Dict[str, Dict[str, Any]]:
    """ToolSpecs from the contract, generated once per process (argparse -> ToolSpec -> here)."""
    if not _SPECS:
        for spec in _contract.build(detect=False)["tools"]:
            _SPECS[spec["name"]] = spec
    return _SPECS


class _Positional(dict):
    """Positional argument names per tool, read from the contract (kept as a mapping for compatibility)."""

    def __missing__(self, name: str) -> List[str]:
        return list(specs()[name]["mcp"]["positional"]) if name in specs() else ["input"]

    def get(self, name: str, default: Any = None) -> Any:  # type: ignore[override]
        return self[name] if name in specs() else default


POSITIONAL: Dict[str, List[str]] = _Positional()


def build_argv(name: str, args: Dict[str, Any]) -> List[str]:
    """Structured arguments -> argv, using the mapping the contract states (invocation.structured)."""
    if isinstance(args.get("argv"), list):
        argv = [str(a) for a in args["argv"]]
        if name not in _contract.MCP_JSON_EXEMPT and "--json" not in argv and "--help" not in argv:
            argv.append("--json")
        return argv
    spec = specs().get(name)
    exceptions = spec["mcp"]["argument_exceptions"] if spec else {}
    argv: List[str] = []
    args = dict(args)
    for key in POSITIONAL[name]:
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
        flag = exceptions.get(key, "--" + key.replace("_", "-"))
        if val is True:
            argv.append(flag)
        elif isinstance(val, list):
            for v in val:
                argv += [flag, str(v)]
        else:
            argv += [flag, str(val)]
    if name not in _contract.MCP_JSON_EXEMPT and "--json" not in argv and "--help" not in argv:
        argv.append("--json")
    return argv


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    script = SCRIPTS / f"{name}.py"
    if name not in specs() or not script.exists():
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
    """tools/list: one entry per ToolSpec, in the contract's order, inputSchema derived from ToolSpec.input_schema."""
    return [_contract.mcp_tool(spec) for spec in specs().values()]


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
            print(f"{t['name']:10s} {t['description'].split(' Structured arguments:')[0]}")
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
