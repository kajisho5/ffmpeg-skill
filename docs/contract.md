# ffmpeg-skill execution contract

`ffmpeg-skill contract --json` (or `python3 scripts/_contract.py --json`) prints a
machine-readable description of this skill: which tools exist, what each one needs,
takes and writes, how its result is verified, and what an agent may assume about
dry-run, input preservation and repeatability. It is the interface a planning agent
consumes instead of reading `SKILL.md`, which stays written for a coding agent that
follows the workflow by hand.

The contract is derived from the code that runs, not maintained beside it:

- the tool list is every script in `scripts/` that does not start with `_`;
- every `input_schema` is generated from the script's own `argparse` parser at the
  moment the contract is printed, so a new flag appears in the contract with no other edit;
- the facts a parser cannot express (role, required ffmpeg components, verification
  policy, visual-check policy) live in one table in `scripts/_contract.py` and are
  checked against the scripts, the MCP server and the installer by `tests/test_contract.py`.

## Versions

| Field | Meaning | Changes when |
|---|---|---|
| `contract_version` | shape of this document (`1.0`) | a key is renamed, removed or changes meaning |
| `skill.version` | the npm / package.json version (`0.9.0`) | any release |

A release that adds a tool or a flag keeps `contract_version`; a breaking change to the
ToolSpec shape bumps it. Consumers pin on `contract_version` and read `skill.version`
for provenance.

## Skill

```json
{
  "contract_version": "1.0",
  "skill": {"id": "ffmpeg-skill", "version": "0.9.0", "execution_mode": "local", "kind": "execution",
            "entrypoints": {"cli": "...", "mcp": "...", "contract": "...", "doctor": "..."},
            "not_provided": ["AI reasoning", "decisions", "production plans", "project IR", "approvals", "network access", "transcription engine"]},
  "requirements": {"python": ">=3.9 (standard library only)", "ffmpeg": ">=5.0", "ffprobe": ">=5.0"},
  "execution": {"shell": false, "arbitrary_executables": false, "network": false, "input_mutation": false}
}
```

ffmpeg-skill is an execution skill. It measures, transforms and verifies media with
local FFmpeg. It does not reason, plan, decide, or hold a project model; those belong
to the agent that calls it.

## ToolSpec

One entry per tool under `tools`, sorted by id. Tool ids are stable:
`ffmpeg-skill/<script name>` (`ffmpeg-skill/cut`, `ffmpeg-skill/loudness`, …).

| Field | Meaning |
|---|---|
| `id`, `name`, `version`, `executable` | `ffmpeg-skill/cut`, `cut`, skill version, `scripts/cut.py` |
| `role` | `analysis`, `analysis_and_execution`, `execution` or `verification` (see below) |
| `capabilities.required` | ffmpeg components the tool always needs |
| `capabilities.optional[]` | `{capability, when}`: needed only for that flag or input |
| `inputs`, `outputs` | asset kinds consumed and artifact kinds produced, in words |
| `input_schema` | generated from argparse: `properties` keyed by dest with `type`, `cli`, `enum`, `default`, `description`; `required`; `positional` (order); `mutually_exclusive` |
| `output_schema` | what `--json` prints on stdout |
| `supports_dry_run`, `dry_run` | whether `--dry-run` plans without running ffmpeg or writing files |
| `supports_json` | whether `--json` exists |
| `mutates_input` | always `false`: no tool overwrites its input |
| `produces_artifact` | writes a file (media, PNG, HTML, EDL) |
| `verification` | `{required, tools}`: which tools to run on the output afterwards |
| `requires_visual_verification` | the picture changed; run `ffmpeg-skill/look` and inspect the PNG |
| `audio_only` | accepts an audio-only input (WAV, MP3, M4A, FLAC, OGG, Opus) |
| `video_required` | refuses an input without a video stream ("input has no video stream") |
| `deterministic_inputs`, `idempotency_hint` | see Repeatability |
| `mcp` | the MCP tool name and its positional arguments |

### Roles

| Role | Tools |
|---|---|
| `analysis` (measures, writes no media) | probe, scenes |
| `analysis_and_execution` (measures by default or with a flag, can also write) | silence (`--list`), loudness (`--measure-only`), sync (offset JSON without `-o`) |
| `execution` (writes a new artifact) | cut, fit, caption, overlay, graphics, multicam, audio, join, color, export, render, batch |
| `verification` (checks or shows an artifact) | check, look, verify, report |

### Verification policy

The workflow in `SKILL.md` is "probe first, verify last". The contract states it per tool:

| Tool | After it wrote an artifact, run |
|---|---|
| cut, silence, audio, sync, batch | probe |
| loudness | probe, check |
| export | probe, check |
| fit, caption, overlay, graphics, color, join, multicam | probe, look |
| render | probe, check, look |
| probe, check, look, scenes, verify, report | nothing (they are the verification) |

`requires_visual_verification` is `true` exactly for the tools that change the picture
(fit, caption, overlay, graphics, color, join, multicam, render). Audio-only tools and
audio-only inputs never need `look`; the report line is `Look: not needed`. `check`
rows carry `kind: format` (fix it) or `kind: judgement` (decide with the user).

### Dry run

`supports_dry_run` is measured, not declared: `tests/test_contract.py` runs every tool
with `--dry-run` behind a fake `ffmpeg` that records any call, and asserts that no
call happened and no file appeared. Under `--dry-run` a tool prints the command lines
it would run, reports `dry_run: true`, and never reports an output probe. Two
exceptions are stated in the contract: `probe` and `check` are read-only (ffprobe
still runs), and `verify` does not support dry-run (its steps run).

### Repeatability

No tool keeps state or uses randomness. `deterministic_inputs` is `false` only for
`verify`, whose output includes timings. `idempotency_hint` says what "same inputs"
gives you:

| Hint | Tools |
|---|---|
| `bit_exact` | probe, check, scenes, look |
| `content_equivalent` (same media, bytes may differ between encoder builds) | every encoding tool, cut, sync, report |
| `cached` | batch (content-hash cache, re-runs skip unchanged inputs) |
| `environment_dependent` | verify |

## Capabilities

Names: `ffmpeg`, `ffprobe`, `encoder:<name>`, `filter:<name>`, `bsf:<name>`,
`external:whisper`. `capabilities.required` is the union of every tool's required list;
`optional` the union of the conditional ones. With detection (the default)
`available`, `missing` and `missing_optional` are added from `doctor`, which reads
`ffmpeg -encoders / -filters / -bsfs` and looks for a local whisper. Pass `--static`
to omit detection. Nothing from the environment other than those lists and the
ffmpeg/ffprobe/python versions is printed; no environment variables, no paths.

`ffmpeg-skill doctor` exits non-zero when a required capability is missing.

## Invocation

Structured arguments are the canonical way to call a tool, on the CLI or through MCP.
The mapping is stated in `invocation.structured.argument_mapping`: positionals in
`input_schema.positional` order, `key` → `--key` with `_` → `-`, booleans as bare flags,
arrays repeated, `output` → `-o`, `loudness.lufs` → `-I`. `--json` is appended for every
tool except `probe` (JSON by default) and `look`.

The MCP server also accepts `{"argv": [...]}` for CLI compatibility. That path is
marked `canonical: false`: it is still bound to the named script and never reaches a
shell, but an agent ecosystem should use the structured form. No tool, CLI or MCP,
runs a shell, evaluates strings, or executes anything other than the named script,
`ffmpeg` and `ffprobe`.

## JSON output

Success (`exit 0`): one document matching `output_schema`, always with
`status: "completed"`, `output`, `dry_run`, `commands`, and `probe` of the output when a
file was written. `probe` prints its measurement document directly.

Failure (non-zero exit; 127 when ffmpeg/ffprobe is missing): the message on stderr as
before, and, when `--json` was given, on stdout:

```json
{"status": "failed", "error": {"kind": "input | ffmpeg | missing_tool", "message": "..."}}
```

## MCP relationship

`mcp/server.py` is a transport. It holds no tool table and no schema of its own:

```
argparse parser  →  ToolSpec.input_schema  →  contract  →  MCP tools/list inputSchema
```

At start-up the server builds the ToolSpecs (`_contract.build(detect=False)`) and
derives each `tools/list` entry with `_contract.mcp_tool`: the name is the ToolSpec
name, the order is the contract's sorted order, and `inputSchema` is
`_contract.mcp_input_schema(ToolSpec)`. `tools/call` maps structured arguments to
argv with the ToolSpec's `mcp.positional` and `mcp.argument_exceptions`. A new
public script, a removed one, or a changed parser therefore changes the MCP surface
with no edit to `mcp/`; `tests/test_contract.py` proves this by copying the skill,
adding, removing and editing scripts, and reading `tools/list` again.

### Translation, and what JSON Schema cannot say

| ToolSpec.input_schema | MCP inputSchema |
|---|---|
| `properties.<dest>.type / enum / default / description / items` | copied as is |
| `properties.<dest>.cli`, `.common` | dropped (ffmpeg-skill-only keys) |
| `positional` | same properties, passed by name; description gets a `(positional N)` prefix |
| `required` | `required` of the structured branch |
| `mutually_exclusive` groups | `allOf: [{not: {required: [a, b]}} …]` for every pair |
| `one_of_required` groups | `anyOf: [{required: [a]}, …]` |
| raw `argv` compatibility | an `argv` array property; top-level `anyOf: [{required: [argv]}, <structured branch>]` |
| `additionalProperties: false` | kept |

Two things are documented rather than encoded, because JSON Schema has no way to
express them: when `argv` is present every other key is ignored (stated in the `argv`
description), and MCP has no notion of positional order, so positionals are named
properties whose order is only informative. `%(default)s` help interpolation is
already applied when the ToolSpec is built.

The `tools/list` document is deterministic (byte-identical across processes and
identical to the translation of `contract --json`), which the tests check.

## Consuming the contract from an agent

A planning agent (for example video-production-agent's SkillRegistry) can:

1. run `ffmpeg-skill contract --json` once and register the skill by `skill.id` and the
   tools by `id`;
2. resolve `capabilities.required` against `capabilities.available` before planning;
3. pick a tool by `role`, `inputs`/`outputs`, `video_required` and `audio_only`;
4. build the call from `input_schema` and the argument mapping, plan with `--dry-run`;
5. run, parse `output_schema`, then run `verification.tools`, adding `look` when
   `requires_visual_verification` is true.

The measurement documents (`probe`, `check`, `scenes`, `sync`) are ffmpeg-skill's own
shapes, not another system's Observation model; convert them in the agent's adapter.
ffmpeg-skill contains no agent-specific code.

## Where things live

- `scripts/_contract.py`: the generator (`--json`, `--static`, `doctor`)
- `bin/install.js`: `ffmpeg-skill contract` and `ffmpeg-skill doctor`
- `tests/test_contract.py`: schema, consistency (scripts = MCP = installer), MCP inputSchema derived from the contract (equality, determinism, drift, round trips), dry-run, JSON shapes, verification policy, real-media run
- `evals/contract/`: questions an agent must answer from the contract alone, with the expected answers checked against the live contract
- `tests/release_check.sh`: runs the contract from the packed and installed copies before a release
