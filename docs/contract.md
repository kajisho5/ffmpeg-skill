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
| `skill.version` | the npm / package.json version (`1.20.0`) | any release |

A release that adds a tool or a flag keeps `contract_version`; a breaking change to the
ToolSpec shape bumps it. Consumers pin on `contract_version` and read `skill.version`
for provenance. Consumers should also pin `ffmpeg-skill` itself by npm version or git
tag, not by tracking `main` — see README, "Development", "Releasing".

The prose tool count in this file, README, `SKILL.md` and `package.json`'s description is
not generated (it reads naturally in a sentence), so `tests/test_contract.py`'s
`test_docs_tool_count_matches_the_real_tool_list` checks all five against the real count
from `scripts/` on every CI run instead — a stale count fails a test rather than drifting
silently. (`SKILL.md` was added to that check after its "the 28 scripts" sat stale through
twelve tool additions while the other three files were correct.)

## Stability guarantee (1.x)

1.0.0 was published on 2026-09-11 (by accident: see CHANGELOG.md's 1.0.0 entry; the number
is kept rather than burned). From 1.0.3 on, the number is treated as the promise it implies.
For the whole of 1.x:

| Surface | Promise |
|---|---|
| Tool ids (`ffmpeg-skill/<name>`) and script names | never removed or renamed |
| CLI arguments (`argparse` dests, flags, positionals) | never removed, renamed, or made newly required; new optional arguments may be added |
| `--json` output keys, and the keys of `contract --json` / `doctor --json` | never removed or given a different type; new keys may be added |
| Exit codes (0 success, 1 failure incl. ffmpeg failures, 2 unknown/undecidable in `doctor`, 124 timeout, 127 missing tool, 128+signal interrupted) | unchanged |
| `contract_version` (`1.0`) | unchanged; a ToolSpec shape change is a major |
| MCP `tools/list` names and `inputSchema` property names | derived from the above, so covered by the same promise |
| Behaviour of a tool for the same input and arguments | may change only to fix a defect or to track an FFmpeg change, and every such change gets a CHANGELOG line |

Not covered: the exact wording of `--help` text, descriptions, stderr messages, and the
`details`/`notes` free-text fields of JSON output; the internals under `scripts/_*.py`;
the evals harness; the development skills under `.claude/`.

The promise is enforced, not remembered: `tests/test_contract.py`'s
`test_mcp_tool_surface_matches_the_frozen_1x_snapshot` pins every tool's argument names and
which are required against `tests/fixtures/mcp_tools.json`. A removal, rename or newly
required argument fails CI; an addition fails until the snapshot is regenerated
(`UPDATE_MCP_SNAPSHOT=1 python3 tests/test_contract.py`), so the diff of the fixture shows a
reviewer exactly what grew.

## Deprecation policy

Something that has to go (an argument superseded by a better one, an output key that turned
out to be misleading) is retired in three steps, never in one:

1. **Deprecate** in a minor release: the old form keeps working unchanged, a one-line warning
   naming the replacement is printed to stderr when it is used, the CHANGELOG entry says
   "deprecated", and `--help` marks it `(deprecated: use ...)`.
2. **Keep** it for at least two further minor releases or 90 days, whichever is longer.
3. **Remove** it only in the next major (2.0.0), listed in that release's CHANGELOG under
   "Removed", together with the version that first deprecated it.

A defect fix that changes behaviour is not a deprecation: it ships in a patch with a
CHANGELOG line, and if the old behaviour was something a caller could reasonably have relied
on, the line says so.

## What 2.0 changes

`contract --json` carries a top-level `deprecated` list, next to `contract_version`: one entry per
thing 2.0.0 removes, `{"what", "since", "replacement", "removed_in", "where"}` with `where` naming
the surface (`cli`, `json`, `mcp`, `behaviour`). It is the machine-readable half of the policy
above, and this section is written from it. Nothing below changes behaviour in 1.x -- every old
spelling keeps working until 2.0.

| What 2.0 removes | Since | Replacement | To be ready today |
|---|---|---|---|
| The per-tool v1 success keys next to `result_v2` (`output`, `probe`, `commands`, `verified`, `verification` and each tool's own keys at the top level) | 1.20.0 | `result_v2`, promoted to the top level in 2.0 | Run with `FFMPEG_SKILL_RESULT_V2=1` and read `result_v2` (`metrics`, `notes`, `details`) instead of the top-level keys |
| `--crf` as an alias of `--quality` on every re-encoding tool that takes `--quality` (`export.py` keeps `--crf`: its preset chooses the encoder) | 1.20.0 | `--quality N` (the same CRF scale, codec-neutral) | Pass `--quality`; `--crf` warns on stderr and is marked in `--help` |
| `json` and `progress` in the MCP `inputSchema` | 1.20.0 | nothing: the transport sets them itself | Stop sending them from an MCP client; run the server with `FFMPEG_SKILL_MCP_LEAN=1` to see the 2.0 schema |
| `hdr` meaning "BT.2020 primaries *or* a PQ/HLG transfer" in `probe` | 1.20.0 | `hdr_signal` (true only for PQ / HLG / Dolby Vision); in 2.0 `hdr` takes that meaning | Key on `hdr_signal` for "is this a real HDR signal" and on `hdr_format` for the `BT.2020 SDR` case |
| Overwriting an existing output with only a warning | 1.20.0 | `--overwrite` as explicit consent (refused without it from 2.0) | Set `FFMPEG_SKILL_NO_OVERWRITE=1` (the recommended agent setting) and pass `--overwrite` where a replacement is intended |

## Skill

```json
{
  "contract_version": "1.0",
  "deprecated": [{"what": "...", "since": "1.20.0", "replacement": "...", "removed_in": "2.0.0", "where": "cli | json | mcp | behaviour"}],
  "skill": {"id": "ffmpeg-skill", "version": "1.20.0", "execution_mode": "local", "kind": "execution",
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
| `examples[]` | `{prompts[], command}` (1.20.0): SKILL.md's own "User says" / "Do" table rows for this tool, machine-readable — `prompts` is the row's phrasing(s), `command` the row's `Do` text with the markdown backticks stripped. Every tool has at least one; parsed from SKILL.md at read time, so it never drifts from the table a person reads |
| `role` | `analysis`, `analysis_and_execution`, `execution` or `verification` (see below) |
| `capabilities.required` | ffmpeg components the tool always needs |
| `capabilities.optional[]` | `{capability, when}`: needed only for that flag or input |
| `inputs`, `outputs` | asset kinds consumed and artifact kinds produced, in words |
| `input_schema` | generated from argparse: `properties` keyed by dest with `type`, `cli`, `enum`, `default`, `description`; `required`; `positional` (order); `mutually_exclusive` |
| `output_schema` | what `--json` prints on stdout |
| `supports_dry_run`, `dry_run` | whether `--dry-run` plans without running ffmpeg or writing files |
| `supports_json` | whether `--json` exists |
| `supports_json_brief` | whether `--json-brief` exists (1.20.0): the same success document with `probe` replaced by a compact `summary` (`duration_s`, `width`, `height`, `fps`, `vcodec`, `acodec`, `channels`, and `lufs` when the tool measured one), `commands` replaced by the number of commands run, and the per-step `verification` list dropped (its verdict stays in `verified`). Tool-specific keys are unchanged, `--json`'s own output is unchanged, and a failure prints the same failure document either way |
| `mutates_input` | always `false`: no tool overwrites its input |
| `produces_artifact` | writes a file (media, PNG, HTML, EDL) |
| `verification` | `{required, tools}`: which tools to run on the output afterwards |
| `requires_visual_verification` | the picture changed; run `ffmpeg-skill/look` and inspect the PNG |
| `reencodes_video`, `reencodes_audio` | `"always"` / `"never"` / `"conditional"`, meaning *when that stream is present in the input* — not whether the tool touches the file at all. `"conditional"` tools (`cut`, `export`, `render`, `batch`, `verify`, `caption`, `color`) carry a `reencode_note` explaining what it depends on — for `caption`, `--mode burn` (default) always re-encodes both streams, `--mode mux` copies both untouched; for `color`, `--strip-dovi` and `--retag` are a stream copy of both (retag only re-encodes if the copy attempt fails), while `--to-sdr` / `--lut` / `--correct` always re-encode both. Several visual tools (`fit`, `overlay`, `graphics`, `join`, `multicam`, `silence`) are `"always"` on audio too: this codebase never mixes `-c:v` re-encode with `-c:a copy` in one call, so a caller cannot assume the original audio codec survives just because only the picture changed |
| `audio_only` | accepts an audio-only input (WAV, MP3, M4A, FLAC, OGG, Opus) |
| `video_required` | refuses an input without a video stream ("input has no video stream") |
| | `join` has `audio_only: true` and `video_required: false` since 0.9.1: audio-only inputs are joined as audio (no `look` needed then); mixing audio and video inputs is refused |
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
it would run, reports `dry_run: true`, and never reports an output probe. The
exceptions are stated per tool in the contract's `dry_run` field: `probe` and `check` are
read-only (ffprobe still runs); `sync`, `multicam`, `scenes`, `cropdetect`, `report`, `silence`,
`loudness` and `stabilize` still run their ffmpeg/ffprobe measurements (the analysis is the
tool's job; only the artifact is skipped, including side files such as `--edl`, `--sheet` or a
generated `.ass`), and `verify` does not support dry-run (its steps run). `SKILL.md` and
`references/scripts.md` repeat the same list; the contract is the authority.

`--codec h264|hevc|av1|prores` and `--quality N` (1.8) are on every tool whose schema has
`crf` (the ones that re-encode), marked `common`. They are resolved in one place
(`_common.encoder_args()`): hevc keeps an HDR source Main10 with its tags and writes 8-bit
BT.709 for SDR; av1 is SVT-AV1 with libaom as the fallback; prores is 422 HQ and needs a
`.mov`/`.mkv` output; h264 refuses an HDR source (`kind: input`). `--quality` is the CRF scale
and overrides `--crf`. Without `--codec` the encoder is what it always was (x264 for SDR, x265
Main10 for HDR), so the flags add no behaviour to a caller that does not pass them. The
encoder each value needs is listed under the tool's optional capabilities (`--codec hevc` and
so on). `export.py` refuses `--codec`: its presets decide the codec.

`--plan FILE` (1.6) is a dry run that also writes a plan document: `{"plan_version": 1,
"tool", "argv", "cwd", "inputs": [{"path", "size", "sha256_head_tail"}], "commands",
"output", "verify": [{"tool": "probe"}, {"tool": "check", "platform"}], "notes"}`. It
implies `--dry-run`, so the same execution rules apply; `inputs` covers the `-i` files of the
planned commands, every existing file named in argv (a recipe, a still, an SRT) and the
subtitle/LUT/font files a filter reads. Tools that print their document without `--json`
(`probe`, the analysis tools) still write the plan at exit; `verify.py` and `render.py`
refuse `--plan` (their steps run for real; a project file is already a plan). `render.py FILE` executes a plan:
it refuses (`kind: input`) when an input's size or head/tail hash differs from the plan,
runs the tool with the planned `argv`, then the verify steps, and reports `plan`, `tool`,
`tool_result` and `check`. `plan_version` is bumped when the document's shape changes.

### Repeatability

No tool keeps state or uses randomness. `deterministic_inputs` is `false` only for
`verify`, whose output includes timings. `idempotency_hint` says what "same inputs"
gives you:

| Hint | Tools |
|---|---|
| `bit_exact` | probe, check, scenes, look |
| `content_equivalent` (same media, bytes may differ between encoder builds) | every encoding tool, cut, sync, report |
| `cached` | batch (content-hash cache, re-runs skip unchanged inputs); render **when `--cache DIR` is given** — the hint stays `content_equivalent` because that is what render is without the flag, and the cache is opt-in |
| `environment_dependent` | verify |

## `provides`

`provides` lists these 42 tools by a cross-repository Capability id, for
`kajisho5/AI-video-production-OS`'s `CapabilityContract.provides`
(`docs/SPEC.md` there), matching the ids already assigned to this Skill in
that project's own `docs/CAPABILITY_MATRIX.md` section 9 ("ffmpeg-skill's
21 raw tools ... are Capabilities in their own right, independent of the
higher-level Skills that delegate to them"): `[{"id": "ffmpeg-skill.<tool>",
"lifecycle": "EXPERIMENTAL", "tool_id": "ffmpeg-skill/<tool>"}, ...]`, one
entry per tool, sorted by id. The Capability id uses a dot
(`ffmpeg-skill.cut`) - the `<domain>.<verb>` shape every other Skill's
Capability ids use elsewhere in that project (`video.trim`, `audio.gain`,
...), with `ffmpeg-skill` as the domain - while `tool_id` carries this
contract's own slash-shaped `id` (`ffmpeg-skill/cut`) unchanged. It is
purely additive: derived from `public_tools()`, saying nothing `tools[]`
doesn't already say, only indexed by Capability id instead of tool name.

## `capability_map`

`provides` re-indexes each tool by an id shaped like the tool name
(`ffmpeg-skill.cut`); it doesn't tell a caller that "I need to trim a
video" resolves to `cut`. `capability_map` is the small, hand-authored
table that closes that gap: `[{"capability": "<domain>.<verb>", "tool_id":
"ffmpeg-skill/<tool>", "params": {...}}, ...]`. A planner that only knows
an abstract goal (`video.trim`, `audio.loudness`, `subtitle.burn`,
`media.stream.inspect`, `media.frames.extract`, `media.proxy`) looks it up here to find
the tool, then builds and runs that tool's own call from its
`input_schema` exactly as it would have if it already knew the tool name -
`capability_map` never executes anything itself, and this skill never
picks a capability on the caller's behalf.

Some entries also fix one or more `params` where the capability names a
*specific* behaviour narrower than the whole tool: `video.reframe` maps
to `fit` with `params: {"fit": "crop"}`, because `fit.py` also does
duration-fit and letterbox padding, and only the crop mode is a
"reframe". A caller resolving `video.reframe` should treat those params
as fixed inputs to that tool's own schema, not as optional defaults.

This list is deliberately short and will stay short: a capability is only
added when resolving it is a mechanical, no-judgment lookup. There is no
`video.highlight` entry, for instance, because `scenes.py --highlights`
ranks candidates by a measured proxy (audio energy or duration), never by
understood content - offering it as a blindly-delegable capability would
misrepresent what it does (see SKILL.md, "What this skill does and does
not decide"). `media.proxy` (a low-bitrate, fast-decode proxy for
downstream analysis/preview, distinct from `export.py`'s delivery
presets) resolves to `proxy` - itself a mechanical resize + re-encode
with no opinion on which asset should be proxied or what for.

## Delivery table and templates (1.14)

`scripts/_platforms.py` is the one table every delivery tool reads. Per destination
(`tiktok`, `reels`, `shorts`, `youtube`, `youtube-hdr`, `youtube-av1`, `x`, `linkedin`,
`facebook`, `podcast`, plus the `broadcast` / `custom` compliance targets):

| field | meaning |
|---|---|
| `frame` | `{w, h, aspect}` the destination is delivered at, or `null` for an audio-only one |
| `fps` | the frame rate a delivery is conformed to (`null`: leave the source's alone) |
| `spec` | `check.py`'s row values: `max_duration`, `aspects`, `min_height`, `fps_max`, `codecs`, `max_bytes`, `lufs`, `lufs_tol`, `tp`, `sdr_only` |
| `safe` | the fraction of the frame the app's own UI covers, per edge (`top`, `bottom`, `left`, `right`) |
| `caption` | caption defaults a template uses: `size` (fraction of frame height), `position`, `box`, `outline`, `animate` |
| `preset` | the `export.py` preset that writes this destination |
| `check` | the `check.py` platform a delivery is verified against |

It is an internal module (leading underscore), not a tool: the public tool count is unchanged.
`check.py`'s `SPECS`, `export.py`'s `PRESETS` (each platform preset's frame and duration cap)
and `export.py`'s `PLATFORM_OF` are all built from it, so the loudness `export.py --normalize`
targets, the frame it writes, the cap it trims at and the spec `check.py` enforces are one
value. Two presets deliberately differ from their destination's row and say so in the code:
`youtube4k` delivers to YouTube at 2160p, and no `youtube*` preset trims at YouTube's 12-hour
limit (`check.py` reports it instead). `_platforms.resolve()` is the one alias map -- 
`youtube-shorts`/`yt-shorts` = `shorts`, `yt` = `youtube`, `instagram`/`ig` = `reels`,
`twitter` = `x`, `fb` = `facebook` -- and `check.py --platform`, `export.py --preset`,
`caption.py`/`graphics.py`/`overlay.py --platform`, `look.py --safe` and
`render.py --template` all accept those spellings.

New in the same release, all additive: `export.py --preset tiktok|shorts|linkedin|facebook`
(real presets, not aliases of `reels`/`youtube`), `--preset youtube-hdr` (HEVC Main10 keeping
the source's HDR tags; `kind: input` on an SDR source) and `--preset youtube-av1`
(`kind: missing_tool` when the build has neither SVT-AV1 nor libaom); `caption.py --platform`
and `graphics.py --platform` / `--margin` and `overlay.py --platform` (margins from the safe
zone, an explicit `--margin`/`--position` wins); `look.py --safe NAME`; `fit.py --fit blur`; `report.py --pack`;
`graphics.py --template sticker|hook|meme`; and `render.py --template NAME INPUT`
(`--cues/--srt/--logo/--title/--brand/--chapters/--fit/-o/--write-project/--list-templates`),
which fills a `templates/<name>.json` project shipped with the skill. `--template all` or a
comma-separated list renders every named destination and writes a `<stem>_pack.md` table.
A project may now carry `"template"` (the name it was filled from) and `"frame": {"fit": ...}`.

## Capabilities

Names: `ffmpeg`, `ffprobe`, `encoder:<name>`, `filter:<name>`, `bsf:<name>`,
`external:whisper`. `capabilities.required` is the union of every tool's required list;
`optional` the union of the conditional ones. With detection (the default)
`available`, `missing` and `missing_optional` are added from `doctor`, which reads
`ffmpeg -encoders / -filters / -bsfs` and looks for a local whisper. Pass `--static`
to omit detection. Nothing from the environment other than those lists and the
ffmpeg/ffprobe/python versions is printed; no environment variables, no paths.

`external:whisper` is **optional** for two tools since 1.17: `caption.py`
(`--transcribe`) and `silence.py` (`--filler --transcribe`). Neither requires
it — both take a transcript the caller already has (`--srt`/`--words`), and
both refuse with the same three install lines when asked to make one with no
engine present. Whisper is never a dependency of this skill.

`doctor` has three states per capability. `available` and `missing` come from a listing
that was read; `unknown` means the listing that would prove the capability could not be
read (`ffmpeg -filters` in a layout the parser does not recognise, or ffmpeg exiting
non-zero), and it is never folded into `missing`, so an installed filter is not reported
absent, nor into `available`, so a failed detection is not a pass. `detection` gives the
status (`parsed`, `unparsed`, `failed`, `missing`), row count and detail of each listing;
`errors` lists the unreadable ones. The filter parser recognises the FFmpeg 6/7 layout
(three flag characters, `..C acompressor A->A`) and the FFmpeg 8 layout (two, `T.
acompressor A->A`) by the io-spec token, so the flag width does not matter; fixtures for
both live in `tests/fixtures/`.

`ffmpeg-skill doctor` exits 0 when every required capability is available, 1 when one is
missing, 2 when none is missing but a required one is unknown. `ok` is true only for 0.
The keys of 0.9.0 (`available`, `missing`, `missing_optional`, `ok`) are unchanged.

`doctor`'s `tools` field folds that same per-capability `state` into a per-tool answer:
`{"<tool>": {"usable": "yes"|"no"|"unknown", "missing": [...], "fix": "...", "unknown": [...]}}`.
`missing`/`unknown` list only that tool's own required capabilities that are in that state
(`missing` is absent when there is none, same for `unknown`); `fix` is a one-line, plain-language
remedy for each missing capability, joined with "; " when there is more than one. This exists so
a caller does not have to cross-reference `available`/`missing` against each tool's own required
capabilities by hand to answer "can I run `caption.py` on this machine right now" -- `doctor`
passing overall does not mean every tool is usable (a plain Homebrew `ffmpeg` on macOS is `ok`
for tools that don't need `subtitles`/`drawtext`/`zscale`, but `caption.usable` is `"no"`).

`doctor`'s `gpu_encoders` field reports GPU-backed encoders (`nvenc`, `videotoolbox`, `qsv`,
`vaapi`, `amf`) present in this ffmpeg *build*, read from `-encoders` alone — `{"status":
"parsed"|"unparsed"|"failed"|"missing", "present": [...]}`. It proves the build shipped the
capability, not that the GPU/driver on this machine will accept a job (that needs a real
encode, which this introspection never runs). No tool declares or requires a GPU encoder, so
`gpu_encoders` never affects `ok` or any tool's `usable` — it exists purely so a caller can ask
the same honest yes/no/unknown question about GPU support that filter/encoder detection already
answers for everything else, without a tool here needing to use one.

`doctor`'s `fonts` field reports whether the default drawtext font (`caption.py`'s
`--animate`/`--karaoke`, `graphics.py`'s templates — `BRAND_DEFAULTS["font"]`, `"DejaVu Sans"`)
is actually installed — `{"default_font": "...", "status": "available"|"missing"|"unknown",
"detail": "..."}`. drawtext's `font=` is a fontconfig name lookup, and fontconfig silently
substitutes the closest match for *any* name, known or not — a missing font never fails the
encode, so drawtext's own exit code cannot detect it. `fc-match` is queried instead: `available`
when it resolves the name to itself, `missing` when it substitutes a different family, `unknown`
when `fc-match` itself is not on PATH or fails. Like `gpu_encoders`, this is purely informational
and never affects `ok` or any tool's `usable` — a substituted font is not a broken tool, just a
typeface the caller didn't ask for.

Since 1.12 the same field also carries `scripts`: one entry per writing system the tools detect,
`{"ja": {"status": "available"|"missing"|"unknown", "file": "/path/to/font.ttc"|null}, "zh": ...,
"ko": ..., "ar": ..., "he": ..., "hi": ..., "bn": ..., "ta": ..., "th": ..., "lo": ..., "ru": ...,
"el": ...}` (`bn`, `ta` and `lo` were added in 1.15). It answers "which
languages can this machine actually render", which no filter or encoder capability asks:
`available` means `fc-list :lang=<code>` (Linux/macOS) or a known system font file (Windows) covers
the script, `missing` means fontconfig knows none, `unknown` means there is no working fontconfig to
ask (no `fc-list` on PATH, or it failed). `caption.py`, `graphics.py` and `overlay.py --text` resolve
a font by script automatically and fail with `kind: input` rather than render boxes **only for
`missing`**: `unknown` is not `missing` here any more than anywhere else in this document — the job
runs with the font as given and one info line says the coverage could not be verified. So a
`missing` script here is a job that will not run until a font is installed — but, like the default
font, it never affects `ok` or any tool's
`usable` (the tool works, this machine just has no glyphs for that language). The plain-text
`doctor` summarises the whole map on one `fonts:` line, which also carries the default font's
`detail` in brackets when its status is not `available` and that detail is short enough to keep the
line to one screen width; a longer explanation, and the per-script files, are `--json` only.
`--lang`/`--language` (caption, graphics) is the hint that says whether Han-only text is Chinese,
Japanese or Korean.

Since 1.15 `fonts` also carries `emoji`: `{"mode": "color"|"png"|"mono"|"none", "color_font": "Noto
Color Emoji"|null, "color_font_file": "..."|null, "libass_color": true|false|null, "assets":
"/path"|null, "detail": "...", "fix": "..."}`. `libass_color` comes from a **render probe** — one
64x64 frame with an emoji cue through `subtitles=`, chroma-tested — because an installed colour
emoji family proves nothing: Noto Color Emoji installs cleanly on builds whose libass still draws a
monochrome outline. `null` means the probe was not run: `contract --json --static` (and every other
static/JSON-only path) skips it, exactly as it skips the rest of the environment detection. `mode`
is `color` when the probe says colour, else `png` when an emoji assets directory resolves, else
`mono` when some installed face has a glyph, else `none`. Informational like the rest of `fonts`:
it never moves `ok` or any tool's `usable`.

`caption.py`, `graphics.py` and `overlay.py` gained `--emoji auto|color|png|mono|none`,
`--emoji-assets DIR`, `--emoji-scale FLOAT` and `--emoji-max N` in 1.15; `graphics.py` also gained
`--text-render auto|ass|drawtext` and `--write-ass PATH`. New success keys: `emoji`
(`{"mode", "count", "clusters", "assets", "missing", "overlays"}`) on `caption.py` and
`graphics.py`, and `text_renderer` (`"ass"`|`"drawtext"`), `script` and `ass` (the generated file,
when one was written) on `graphics.py`. `--json-brief` carries `emoji.mode` and `emoji.count` only.
All additive: `contract_version` stays 1.0.

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

Per-tool keys added in 1.13: `audio` (`audio.py`) reports the mix it built — the
`--voice` level, `stereo_widen`, whether an `--effects` bed was mixed, and with
`--music` the `music_volume` plus a `duck` object naming the threshold (dB and
linear), ratio, attack and release actually used, or `null` when `--duck` was not
given. `loudness.py` reports `measured` (the input's loudnorm measurement,
including `input_lra`) and `targets` (the requested lufs / tp / lra).
`check.py --platform podcast` adds two informational rows to `checks`,
`channels` and `chapters`.

Per-tool keys added in 1.16, all additive (no 1.15 key is removed, renamed or
given a different type):

| key | tool | what it holds |
|---|---|---|
| `caption` | `caption.py` | the cue-layout counts the run only printed before (`shifted`, `wrapped`, `rebalanced`, `split`, `extended`, `dropped`) plus `wrap` (`"phrase"` or `"measured"`) and `phrase_breaks`, the number of cues a phrase rule broke somewhere the 1.15 width rule would not. `broken_inside_word` (1.20.0) counts atoms hard-sliced at the live column's edge because they did not fit alone even at the size floor — never a rewrite, the sliced pieces are the exact original characters. `overlong` is now residual: it fires only when even a single character is wider than the column |
| `tracks`, `subtitle_tracks` | `caption.py --mode mux` | one entry per subtitle stream in the output — `{index, file, language, title, codec, default, cues, kept_from_input}`; a stream the input already carried has `file: null` and `kept_from_input: true`. `subtitle_tracks` is the total. Every field describes the file as written, not as asked for: an MPEG-4 output reports `title: null` (the muxer stores none) and `default: true` on its first track (the muxer always enables it), each with a `notes` line |
| `auto_chapters` | `metadata.py --auto-chapters` | `{source, min_chapter, max_chapters, proposed, kept, titles, chapters, description_block, files}`. `titles` is always `"placeholder"`: the machine-readable form of "the skill did not name these". Each chapter carries its `evidence` (`start`, `silence`, `scene`, or `silence+scene` with the span, its length and the cut time) |
| `audiogram` | `waveform.py` (every run) | `{style, background, image, position, vis_height, platform, captions, title, stages, verified}`. `background` is `"image"` or `"color"`; `verified` is true when the render probes at the asked-for frame size, frame rate and within 0.05 s of the source audio, and is `false` under `--dry-run`, where nothing was rendered to verify |

Per-tool keys added in 1.17, all additive:

| key | tool | what it holds |
|---|---|---|
| `fit_size`, `size_requested`, `size_used`, `size_floor`, `size_pct_height`, `shrunk`, `fit_scope`, `fit_exhausted` | `caption.py` | siblings inside the same `caption` block: which mode fitted the size (`auto`/`on`/`off`), the size asked for and the size used in ASS units, the floor (13 = 4.5 % of the frame height), that size as a percentage of the frame, how many cues the shrink rescued, `file` or `cue` scope, whether the floor was reached with cues still split, and `size_source` (`input`, or `platform-frame` when a plan was written before the input existed). `size_used` is `null` when there was no geometry to fit against at all |
| `beats`, `beat_grid` | `scenes.py --beats` | the measured beat times, and `{supported_beats, tempo_bpm, interval, confidence, phase, onsets, supported, unsupported, method, step_s, range_bpm, usable}`. `supported_beats` is the subset of the regular grid that a measured onset marks — the only list a tool that moves a cut may snap to. `usable` is `confidence >= --min-confidence`; a low confidence is reported, not refused — `scenes.py` measures, it does not act |
| `snap` | `cut.py --snap beats`, `render.py` | `{mode, tolerance, confidence, tempo_bpm, grid, grid_points, moved, snapped, unchanged, source}`. `grid` is `"supported"`: points are moved only onto grid points a measured onset marks, never onto the regular grid's continuation through a silent passage. `moved` has exactly one row per in/out point given (`from`, `to`, `delta`, `snapped`, `beat_index`) — a point is never added or dropped, and `to` is always either a measured beat or the caller's own value |
| `filler`, `removed_seconds_total` | `silence.py --filler` | `{lang, source, engine, words, removed, removed_count, removed_seconds, removed_words, word_timings, list, warnings}`. The existing `removed_seconds` is unchanged in name and meaning — the seconds of *silence* removed, which is what it has always held — and `removed_seconds_total` is the additive sibling covering silence plus filler |
| `jobs`, `jobs_requested`, `wall_seconds`, `item_seconds_total`, `timed_out` | `batch.py` | the parallelism actually applied and the number asked for, the batch's wall clock, the sum of the per-item times (so the speed-up can be quoted), and whether the shared timeout budget ran out. A timed-out item carries `"skipped": "timeout"` in its result row |
| `cache` | `render.py --cache` | `{dir, ffmpeg, hits, misses, saved_seconds, entries}`, plus `would_hit` under `--dry-run`. The ffmpeg build banner, the skill version, the contract version, the forwarded flags (`--fast`, `--codec`, …) and the output's extension are all part of every key, so a cache is never reused across any of them — a `--fast` draft is never served to a run that did not ask for one |

Per-tool keys added in 1.20.0, all additive:

| key | tool | what it holds |
|---|---|---|
| `caption` | `render.py` | the caption stage's own block, forwarded verbatim from `caption.py` (the cue-layout counts plus the fit-size keys above), so a template run can be read for `split` and `size_used` without re-running the stage. `null` when the project has no captions stage — and also when the captions stage came from the `--cache` (a cache hit carries no stage document, so a second `render.py … --cache DIR` run reports `caption: null` while `stages_done` still lists `captions`). `caption.py --mode mux` writes no `caption` block at all |
| `text_unchanged` | `caption.py` | a sibling inside the `caption` block, **burn mode only** (`--mode mux` never touches the text and omits the key): `true` when the drawn text equals the cues that were handed in — nothing transcribed, no cue dropped, no cue **split** across two consecutive cues and no glyph stripped (`--emoji none`). Wrapping, line breaks and timing do not count: the words are the same. This tool never rewrites, shortens or translates a cue, so the key is a statement of what happened, not a judgement of the text |


Per-tool keys added in 1.20.0, all additive:

| key | tool | what it holds |
|---|---|---|
| `shots` | `scenes.py --shots` | `[{start, end, label, flow_magnitude}]` per detected scene, `label` one of `static`/`pan`/`motion` from a lightweight block-matching optical-flow proxy (frames decoded at 4 fps, 48x27, no external dependency). A shot too short to sample two frames is `static` with `flow_magnitude: 0` |
| `audio_peaks_db` | `scenes.py --audio-peaks` | `[{time, level}]`, measured dBFS loudness peaks. A **new** key: the pre-existing `audio_peaks` (always reported, unrelated unitless RMS figures used for `--highlights` scoring) keeps its 1.0 meaning unchanged |
| `speech` | `scenes.py --speech` | `[{time, speech_music_ratio}]`, a per-second zero-crossing-rate ratio against the file's own median — a measured proxy, not a speech/music classification |
| `motion_centre` | `cropdetect.py --motion-centre` | `[{time, x, y, x_frac, y_frac, motion}]` per second, sampled over the same windows as the crop-bar detection. `x`/`y` are source pixels, `x_frac`/`y_frac` a 0..1 fraction of `source_width`/`source_height`; a window with no measured motion reports `x`/`y`/`x_frac`/`y_frac: null`. Report only — this tool never picks a reframe |
| `speech_aware`, `speech_aware.breaths` | `silence.py --speech-aware` | `{min_silence, floor, breaths_kept, breaths_kept_seconds, breaths}`. `breaths` are the sub-`--min-silence` gaps kept because they sit inside a sentence; the removal list (`silences`, `keep`, `removed_seconds`) already reflects the speech-aware classification. Composes with `--filler` through the same `keep_ranges()`/`merge_spans()` pipeline, so `--speech-aware --filler` produces one removal list |
| `sources` | `sync.py` | `[{path, offset_s, confidence, drift_ppm}]`, one entry per SOURCE. Present for every run, including the original single-SOURCE shape (where it mirrors the top-level `second`/`offset_seconds`/`confidence` additively). With 2+ SOURCEs it is the *only* per-source shape: there is no top-level `second`/`offset_seconds` because there is no single pair to put there |
| `switch_mode`, `min_shot` | `multicam.py --switch energy` | `"energy"` and the `--min-shot` value used (default 1.5s), alongside the existing `cuts` (`[[start, end, camera], ...]`) which already carries the camera index for `--edl`'s companion cut list |

`check.py` also gains an informational `subtitles` row on **every** platform:
`PASS` when every soft subtitle stream carries a language tag, `WARN` when one
does not (or when there are none). Like `channels` and `chapters` it is never
counted in `failed` — no platform refuses a delivery over it.

The MCP `audio` tool publishes `voice` as `{"type": "string", "enum": ["light",
"medium", "strong"]}`. A client that still sends the 1.12 boolean `{"voice":
true}` keeps working: `true` emits the bare `--voice`, which is `medium` — the
chain the flag has always produced. Send the string when you can; the boolean
is accepted at runtime and means `medium`.

Success (`exit 0`): one document matching `output_schema`, always with
`status: "completed"`, `output`, `dry_run`, `commands`, and `probe` of the output when a
file was written. `probe` prints its measurement document directly.

Every writing tool also reports what it verified itself (1.7): `verification` lists the
steps (`{"step": "probe", "ok": true}`; `loudness` with the measured and target values for
`loudness.py` and the platform presets of `export.py`; `check` with the platform for
`render.py`), and `verified` is `true` only when the artifact was written, probed and every
listed step met its target. A `--dry-run` document has `verified: false` and an empty list.
`export.py` whose written file misses the platform's loudness spec stays `completed` (the
file is valid) with `verified: false` and the fix in `notes`, so a caller keys on one field.

With `FFMPEG_SKILL_RESULT_V2=1` in the environment, every writing tool's success document
also carries `result_v2`: a preview of the one shape 2.0 will use for every tool
(issue #189). `{"schema": 2, "output", "probe", "commands", "metrics", "notes", "dropped":
{"non_av_streams"}, "verified", "verification", "details"}` -- `metrics` holds the numbers a caller keys on (loudness's
measurement dicts flattened, plus any numeric top-level key such as `expected_duration` or
`offset_seconds`), `notes` the free text, `details` the tool's remaining keys unchanged. The
1.x keys are not moved; the environment variable only adds the key, and its absence is the
default until 2.0.

Success is decided by `verify_output` in `_common` (`scripts/_common/probe.py`), not by the
ffmpeg exit code alone:
the file must exist, be non-empty and give ffprobe at least one stream. A tool that ran
ffmpeg successfully but has no usable artifact fails with `kind: output` (a 0-byte file is
removed so a later step cannot mistake it for a result).

Failure (non-zero exit; 127 when ffmpeg/ffprobe is missing): the message on stderr as
before, and, when `--json` was given, on stdout:

```json
{"status": "failed", "exit_code": 1,
 "error": {"kind": "input | ffmpeg | output | missing_tool | timeout | verification | interrupted", "message": "...",
           "code": "INPUT_INVALID | DEPENDENCY_MISSING | FFMPEG_EXECUTION_FAILED | OUTPUT_INVALID | TIMEOUT | VERIFICATION_FAILED | INTERNAL_ERROR",
           "retryable": false},
 "commands": ["ffmpeg ..."]}
```

`message` carries the script's own reason (missing input, ffprobe failure, the last
stderr lines of ffmpeg, the verification that failed); an optional `error.hint` names the
flag change that would make a retry meaningful (never a diagnosis of the media); `commands` lists what was planned
or run so the caller can retry or report without re-deriving the command; `kind: ffmpeg`
failures add `ffmpeg_returncode` (ffmpeg's own exit code; the process exits 1). `code` is a
purely additive, statically-mapped relabelling of `kind` (never a new distinction `kind`
doesn't already make) for a caller that wants a stable enum instead of matching `kind`
strings. `retryable` is currently always `false`: none of the kinds are distinguishable
today from a deterministic failure that would fail identically on a blind retry, so nothing
here claims otherwise until real exit-code/stderr sniffing exists to back that up.

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

`FFMPEG_SKILL_MCP_LEAN=1` (anything but "" or `0`) in the server's environment removes `json` and
`progress` from every `inputSchema` (from `properties`, and from `required` if a tool ever made
them required). They are transport flags `mcp/server.py` sets itself -- it appends `--json` for
every tool but `look` and `probe` -- rather than arguments a caller chooses, and 2.0 drops them
for good (see "What 2.0 changes"). The flag is opt-in and changes nothing else: without it
`tools/list` carries the tool names, argument names and `required` lists the frozen 1.x snapshot
pins -- descriptions may change between releases (the `--crf` deprecation mark did) -- so a lean
client and a default client see the same tools with the same names.

### Default `tools/list` surface: core 12, opt-in for all 42

By default `tools/list` returns only the core dozen in `_contract.MCP_CORE_TOOLS` (`render`,
`look`, `caption`, `export`, `check`, `fit`, `cut`, `audio`, `loudness`, `graphics`, `silence`,
`probe`) rather than all 42, so a session doesn't pay context for 30 schemas it is unlikely to ever call
directly -- the set is the tools eval iterations 17-20's ground-truth `expect` lists actually name
most often across the corpus in `evals/agent_prompts*.json`. Every tool -- including the other 30
-- is still callable by name through `tools/call` regardless of what `tools/list` advertised; the
contract (`ffmpeg-skill contract --json`) still describes all 42 unconditionally. Set
`FFMPEG_SKILL_MCP_FULL=1` (anything but "" or `0`) in the server's environment to make `tools/list`
return all 42, as every version before 1.20.0 did.

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

- `scripts/_platforms.py`: the delivery table (destinations, specs, safe zones) read by check/export/render/caption/graphics/look
- `templates/*.json`: the shipped delivery templates `render.py --template NAME` fills
- `scripts/_contract.py`: the generator (`--json`, `--static`, `doctor`)
- `bin/install.js`: `ffmpeg-skill contract` and `ffmpeg-skill doctor`
- `tests/test_contract.py`: schema, consistency (scripts = MCP = installer), MCP inputSchema derived from the contract (equality, determinism, drift, round trips), dry-run, JSON shapes, verification policy, real-media run
- `evals/contract/`: questions an agent must answer from the contract alone, with the expected answers checked against the live contract
- `tests/release_check.sh`: runs the contract from the packed and installed copies before a release
