---
name: building-python-mcp-servers
description: Builds robust Python MCP (Model Context Protocol) servers with FastMCP — tool design, error contracts, event-loop-safe blocking work, subprocess/CLI wrapping, single-file vs packaged distribution, global-state-free testing, and prompt-injection awareness. Use when writing an MCP server, exposing a tool or CLI to an LLM client, debugging tool registration/packaging, or testing MCP tools.
---

# Building Python MCP Servers

MCP servers expose tools to an LLM client (Claude Desktop, Claude Code, etc.).
The LLM is the caller, so the failure modes differ from a normal library: errors
must be machine-readable, every input is untrusted, and a green test suite often
proves nothing about whether the tools actually work. This skill encodes the
patterns that recur when these go wrong.

## Quick Start (FastMCP)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def read_config(path: str) -> dict:
    """Read a config file. `path` must be absolute."""
    p = Path(path)
    if not p.is_absolute():
        return {"error": "path must be absolute"}
    if not p.exists():
        return {"error": f"no such file: {path}"}
    return {"data": p.read_text()}

if __name__ == "__main__":
    mcp.run()
```

## Error Contract: return, don't raise — and stay consistent

An uncaught exception surfaces to the LLM as an opaque protocol error it can't
reason about. Return a structured result with a predictable shape instead, and
make callers check for it.

- **Pick one error shape and use it everywhere.** A dict with an `"error"` key is
  the common convention. Document that callers must check for it.
- **Batch tools must report skips, not swallow them.** The most common
  inconsistency: a single-item tool collects per-item errors, but a sibling
  "do this across a directory" tool silently `continue`s past files that fail to
  load. For automation that is invisible data loss. Every batch tool should
  return both results and a per-item `skipped`/`errors` list.

```python
@mcp.tool()
def validate_dir(path: str) -> dict:
    results, skipped = {}, []
    for f in Path(path).glob("*.md"):
        try:
            results[f.name] = _validate(f)
        except Exception as e:
            skipped.append({"file": f.name, "error": str(e)})  # never silently continue
    return {"results": results, "skipped": skipped}
```

> Type footgun: YAML auto-parses an unquoted ISO date (`date: 2025-06-15`) into a
> `datetime.date`, **not** a `str` or `datetime.datetime`. A validator that
> handles only `str`/`datetime` will false-positive on native YAML dates. When
> validating parsed values, enumerate every type the parser can actually produce.

## Wrapping a subprocess / CLI

A huge share of MCP servers shell out to another tool. Three failures recur:

**1. Don't discard stdout on a non-zero exit.** Many CLIs exit non-zero *by
design* (a linter/mutation-tester reporting findings) and write their real
output to **stdout** with an empty stderr. A wrapper that returns
`f"Error: {result.stderr}"` whenever `returncode != 0` reports a successful run
to the LLM as an empty `"Error: "`.

```python
def run_tool(args: list[str]) -> dict:
    r = subprocess.run(args, capture_output=True, text=True)
    return {                       # hand BOTH streams to the model; let it judge
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
```

**2. Pin to the version you actually wrap, and verify subcommands exist.** A
server written against a tool's 2.x CLI while the project pins 3.x will call
subcommands and flags that no longer exist — every wrapped tool breaks at
runtime. Check the *installed* version's `--help`, not your memory of it.

**3. Parse args safely.** Splitting an extra-args string with `str.split()`
breaks quoted, space-containing arguments — use `shlex.split()`. Never
interpolate a client-supplied string into a shell command; pass an argv list to
`subprocess.run` (no `shell=True`). When a tool accepts a target/path, remember
the LLM (or content it read) chose it — validate it.

## No module-level global state (it makes the server untestable)

Parsing CLI args at import time and stashing them in module globals
(`WORKING_DIR`, `MAKEFILE_PATH`, caches…) forces every test to
`del sys.modules["server"]` and re-import under a patched `sys.argv` just to
reset state — brittle and easy to get wrong. Keep configuration in an object or
pass it through; construct tools from a factory.

```python
def build_server(config: Config) -> FastMCP:
    mcp = FastMCP("my-server")

    @mcp.tool()
    def do_thing(x: str) -> dict:
        return {"result": _work(x, config)}   # config captured, not global

    return mcp
```

This also avoids **double registration**: a module-level "create all tools" loop
*plus* the same loop inside `main()` registers every tool twice when the file is
run directly (`uv run server.py`, as Claude Desktop does) versus via a console
entry point. Register in exactly one place.

## Keep blocking work off the protocol event loop

Do not assume a framework moves synchronous tool functions to a worker thread.
Some FastMCP runtimes invoke them inline on the protocol event loop. A SQLite
query, filesystem walk, dependency traversal, or synchronous HTTP call that takes
five seconds can therefore block pings and every unrelated request for the same
five seconds.

Make the tool async and move only the blocking boundary to a thread:

```python
import asyncio

@mcp.tool()
async def find_dependents(item_id: int) -> dict:
    rows = await asyncio.to_thread(repository.find_dependents, item_id)
    return {"items": [row.to_dict() for row in rows]}
```

Keep connection ownership in mind. Do not create a SQLite connection on the
event-loop thread and hand that connection to the worker. Open and close it
inside `repository.find_dependents`, or use a pool/driver whose concurrency
contract explicitly permits the handoff. A thread wrapper around a shared,
thread-affine connection merely trades event-loop starvation for intermittent
database errors.

Test responsiveness, not just the slow tool's result. Start a deliberately
blocked repository call, invoke a lightweight tool (or protocol ping) before
releasing it, and require the lightweight request to finish first:

```python
slow = asyncio.create_task(call_tool("find_dependents", {"item_id": 42}))
await entered_worker.wait()

healthy = await asyncio.wait_for(call_tool("health", {}), timeout=0.2)
assert healthy == {"ok": True}

release_worker.set()
await slow
```

A timing assertion on the slow call alone cannot detect event-loop starvation;
the regression is that independent protocol traffic stops making progress.

## Sampling is an optional client capability — contain failures in the tool

`ctx.sample(...)` is not guaranteed to work just because the tool itself was
called successfully. The connected client may not support sampling, or its
sampling handler may raise while processing the request. Those are different
failure modes at the framework layer, but they are the same tool-level outcome:
the requested analysis could not be produced.

Catch the exception around the sampling boundary **inside the tool** and convert
it to the server's normal error shape. Do not rely on the framework's outer
exception wrapper; by then the caller receives an opaque protocol/tool error
instead of your documented contract.

```python
async def sample_or_error(ctx: Context, prompt: str) -> dict:
    try:
        response = await ctx.sample(prompt)
    except Exception as exc:
        return {"error": f"sampling failed: {exc}"}
    return {"result": response.text or ""}
```

Keep the `try` block narrow so unrelated programming errors are not mislabeled as
sampling failures. Test both boundaries explicitly: a client with no sampling
support, and a configured sampling handler that raises. Also test an empty
sampling response if the tool promises an empty-string or other fallback.

## Distribution: single-file vs packaged

MCP servers are often launched as a single file (`uv run server.py`), so two
packaging traps are easy to ship without noticing:

- **Module/package name collision.** Having both a top-level `server.py` *and* a
  `server/` package directory means `import server` resolves to the package
  (shadowing the module), so a console entry point like `server:main` finds no
  `main` and fails. Only running the file directly works. Pick one name.
- **Over-narrow build includes.** A build config like
  `only-include = ["server.py"]` produces a wheel containing just that file —
  `import server.analyzers` raises `ModuleNotFoundError` for anyone who
  `pip install`s it, even though `uv run server.py` works locally. If you ship a
  package, include the package and its data files.

For a PEP 723 single-file server, pin explicit versions in the inline
`# /// script` header **and** keep them in sync with `pyproject.toml`; a
transitive-only dependency (imported but never declared) breaks the moment the
intermediary drops it.

## Testing: prove the tools actually work

Mocking the subprocess/transport layer and asserting that argv contains certain
tokens locks in commands that may not exist in the wrapped tool — the suite stays
green while every tool is broken at runtime. A passing CI here does **not** mean
the server works.

- Keep at least one **integration test that invokes the real wrapped tool** (or
  a real sample file) end to end.
- A bare `import server` smoke test is meaningless under a name collision (it can
  import an empty package). Assert a tool *runs and returns expected output*.
- Test the error contract: malformed input returns your `"error"` shape, batch
  tools populate `skipped`.

## Treat all tool I/O as untrusted (prompt injection)

Tool inputs, file contents, and especially **other tools' descriptions** can be
attacker-influenced and flow into the model's context. A server that feeds such
text back into a second LLM call is itself a prompt-injection surface — its
output is advisory, not authoritative. Don't grant a tool more filesystem/network
reach than it needs, validate paths, and never let tool output be treated as a
trusted instruction.

## MCP Server Checklist

```
Contract:
- [ ] One consistent error shape; documented that callers check it
- [ ] Batch tools return a per-item skipped/errors list (never silent continue)
- [ ] Inputs validated (absolute paths, allowed types) before use
- [ ] Sampling failures (unsupported client and handler exception) normalized inside the tool

Subprocess:
- [ ] Both stdout and stderr returned; non-zero exit not assumed to be failure
- [ ] Pinned to the wrapped tool's actual version; subcommands verified
- [ ] shlex.split for arg strings; argv list (no shell=True)

Structure:
- [ ] No module-level CLI parsing / global state
- [ ] Tools registered in exactly one place
- [ ] Blocking database/filesystem/network work moved off the protocol event loop
- [ ] Concurrency test proves a lightweight request completes while a slow tool is blocked

Distribution & tests:
- [ ] No server.py / server/ name collision; build includes the whole package
- [ ] PEP 723 header deps pinned and synced with pyproject
- [ ] An integration test exercises a real tool (not just mocked argv)
```

## Note for this repository (ffmpeg-skill)

`mcp/server.py` here is a hand-rolled stdio JSON-RPC server, NOT FastMCP — the
`@mcp.tool()` decorator examples above don't apply directly. But most of the
*principles* transfer almost exactly, because this server's entire job is
wrapping 22 subprocess-based CLI tools:

- The subprocess-wrapping section (stdout/stderr handling, argv-list-only, no
  `shell=True`) matches `mcp/server.py`'s actual design: `execution.shell:
  false` and `arbitrary_executables: false` are load-bearing guarantees in
  `contract --json`, not just documentation.
- "No module-level global state" and "tools registered in exactly one place"
  are already true by construction here: `tools/list` is derived from
  `scripts/_contract.py` at call time, not from a hand-written table (see
  `tests/test_contract.py`'s `test_mcp_tools_match_contract` and
  `test_mcp_schema_drift_follows_the_scripts`).
- "Testing: prove the tools actually work" is already the norm —
  `test_mcp_tool_call_round_trip` and the contract tests build real JSON-RPC
  requests and check real tool output, not mocked argv.
- The event-loop/blocking-work section does not apply: this server is
  synchronous stdio, not an async framework moving work onto a shared loop.
- The prompt-injection section is worth taking seriously as-is: any tool
  whose input includes a caller-supplied path (nearly all of them) should be
  read with the same wariness this section describes.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
