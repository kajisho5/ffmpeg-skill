# Contributing to ffmpeg-skill

Thanks for considering a contribution. This project has one job: execute explicit,
agent-given FFmpeg operations deterministically, safely, and verifiably. Read
`SKILL.md`'s "What this skill does and does not decide" before proposing anything —
it defines the boundary this project holds deliberately (no content understanding, no
creative judgement, no AI/LLM integration, no cloud dependency).

## Before you start

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

- **Read `docs/contract.md` and `scripts/_contract.py` first.** The capability
  contract (`contract --json`) is the single source of truth for tool schemas,
  verification policy, and capability detection — every surface (MCP, installer,
  docs, tests) is generated from or checked against it. Don't hand-duplicate a
  schema; extend the generator.
- **Small, hardening-focused changes are the easiest to land.** Bug fixes,
  cross-platform correctness, test coverage for an edge case, and documentation
  drift fixes are always welcome. New tools or features are a much higher bar —
  see "Scope" below.
- **A bug fix sweeps for siblings first.** Before fixing a reported defect, name its class and
  check which other tools meet the same thing: `python3 tests/sweep.py INPUT --baseline PLAIN`
  runs one input through the 31 single-input tools (`cut` twice, plain and `--accurate`) and prints
  the rows that differ from a plain clip's; the tools that need a second file or a project are
  named in its docstring and are swept by hand. The full procedure is `.claude/skills/sibling-sweep/SKILL.md`; the PR template's
  "Siblings" section records what was swept.
- **Every change needs a reproduction.** If you're fixing a bug, show the failing
  case before your fix and the passing case after — either as a new test or a
  documented manual repro in the PR description.

## Scope

This project intentionally does **not**:
- add AI/LLM-based scene understanding, highlight detection, or content judgement
- fall back to raw `ffmpeg`/`ffprobe` shell invocations outside `scripts/*.py`
- depend on cloud services or require API keys
- mutate input files
- make creative or compositional decisions on the calling agent's behalf

If your idea needs one of these, it likely belongs in a different, complementary
skill (see `README.md`'s "Standalone, and in an ecosystem" section) rather than
this one. Open an issue to discuss before writing code for anything larger than a
bug fix — it saves everyone a wasted PR.

## Development

```bash
git clone https://github.com/kajisho5/ffmpeg-skill
cd ffmpeg-skill
npm run test:fast           # tests/test_contract.py only: contract, docs, dry runs (~3-4 min)
npm test                    # everything: real encodes (test_all.py's modules, run in parallel by tests/run_parallel.py; about 21 min on 4 cores, 35 serially) + contract
python3 tests/run_parallel.py --part 1/3   # one of CI's three machines' share (test_contract included); about a third of the time
npm run release-check       # packaging + installer + MCP + doctor + full suite
python3 scripts/_contract.py doctor   # what this machine can actually run
```

Python 3.10+ standard library only — no new runtime dependencies. 3.10 is the floor CI runs
(3.0.0 removed 3.9), so code must keep working on it, and on FFmpeg 6.1, the oldest FFmpeg CI
runs. Every script must keep working with nothing beyond `ffmpeg`/`ffprobe` on `PATH`.

## Tests

- `tests/test_contract.py` — contract ↔ implementation ↔ MCP ↔ installer ↔ docs
  consistency, JSON/error-shape correctness, dry-run guarantees, capability
  detection.
- `tests/test_all.py` — real-media conformance across codecs, containers, VFR,
  HDR, multi-track audio, and every tool's actual ffmpeg invocation.
  It only imports nine group modules (`test_analysis`, `test_editing`, `test_audio`,
  `test_picture`, `test_delivery`, `test_orchestration`, `test_accel`, `test_asr`,
  `test_cut_copy`); while working on one tool, run its group alone, e.g.
  `python3 tests/test_editing.py`, or one case with
  `python3 tests/test_editing.py EditingTests.test_silence_removal`.

Add a test alongside any behavioral change. A fix without a regression test that
would have caught the original bug isn't done yet.

## Pull requests

- Keep PRs focused — one fix or one small feature per PR.
- Run `npm test` locally before opening; CI runs on Linux, macOS, and Windows, and
  all three must pass.
- Explain *why*, not just *what*, in the PR description — the reasoning is what
  future maintainers (human or agent) need most.
- A `feat` PR updates every place the feature is stated: `README.md` (the tool
  table, the contract table, gotchas), `SKILL.md`, `references/scripts.md`,
  `docs/contract.md` and `CHANGELOG.md`. The README is read by people who never
  open SKILL.md, so a feature that only SKILL.md knows about is half shipped.
- `SKILL.md` must stay under **30,000 bytes** — it is loaded into every session.
  Since 1.15 this is a test
  (`tests/test_contract.py::test_skill_md_stays_under_the_30kb_budget`), not a
  convention: adding a line there means trimming one, and the PR says which.
- A `feat` PR adds at least one before/after demo to `demos/build.py` and
  `docs/demos.md` (the page is generated: add the demo to the table in
  `demos/build.py`, then run `python3 demos/build.py --docs`). A feature nobody
  can see working is hard to review and harder to trust; the demo also runs the
  new tool end to end, so a broken flag fails the build instead of the reader.
  Every script under `scripts/` must appear in some demo's command line — a test
  asserts it. The only exception is a tool whose entire output is a table, a JSON
  document or an HTML file: add it to `INSPECTION` in `demos/build.py` instead and
  it gets a command and a sentence in the gallery's Inspection section.
- A release PR moves `docs/roadmap.md`'s "the released version today is ..." line in the **same
  PR as the version bump**, so the roadmap never describes a version that is already out as
  planned. A label-driven release (release.yml's auto-bump) moves only the version number and
  keeps the hand-written prose, marked with the version it describes
  (`.github/scripts/bump_roadmap_md.py`); the next hand-written release PR replaces the sentence.
  The same bump moves both `version` fields in `server.json` (`.github/scripts/bump_server_json.py`).
- Every release also commits the installable plugin tree to the `plugin` branch
  (`.github/scripts/publish_plugin_branch.sh`): the npm tarball's contents plus the plugin
  manifest and `skills/`, under `ffmpeg-skill/` on that branch (a `git-subdir` marketplace source names
  that directory). Never commit to that branch by hand and never force-push it; hosts
  fast-forward it. `bash .github/scripts/publish_plugin_branch.sh --tree-only DIR` builds the
  tree locally without touching git.
- A release whose npm publish failed keeps its tag, and a re-run skips the publish. Finish it by
  dispatching `release.yml` on the tag: `gh workflow run release.yml --ref vX.Y.Z -f version=X.Y.Z`.
  Its `recover` job refuses a version npm already has, a missing tag and a run on any other commit,
  publishes with provenance (`latest` only when the version is above every stable one on npm, else `backport`), and
  then publishes the plugin branch only when its tip is an older version and the MCP Registry
  entry only for a `latest` version: a backport fills in neither. A tag from before the job
  existed (up to v3.6.3) cannot be recovered this way. Do not
  publish by hand: a local publish has no provenance and, without `--tag`, moves `latest`. README's "Releasing" and
  the job's comments say why it is built this way.

## Publishing the MCP listing

The MCP Registry entry is published by CI: since 3.5.0 `release.yml` publishes `server.json` after
the npm publish of every release, signed in through GitHub's OIDC token (no stored secret), and a
re-run fills in a version the registry does not list yet. Step 1 below is the manual fallback for
when that step fails; steps 2 to 4 are manual and nothing in CI does them.

The registry checks the **already published** npm package. `mcpName` in `package.json` has to
equal `server.json`'s `name` (`io.github.kajisho5/ffmpeg-skill`) at that exact version, so publish
npm first (the release workflow does) and only then the registry. Clients run
`npx -y ffmpeg-skill mcp`, which is `python3 mcp/server.py` on stdio.

1. Only when the workflow's "Publish to the MCP Registry" step failed and a re-run does not fix
   it: install [`mcp-publisher`](https://modelcontextprotocol.io/registry/quickstart) and run
   `mcp-publisher login github` as **kajisho5** (GitHub auth only allows the `io.github.kajisho5/`
   namespace). `mcp-publisher validate`, then `mcp-publisher publish`.
2. Smithery: nothing to run. Its API, CLI and SDKs stopped working on 2026-10-31
   (smithery.ai/future); the site remains a curated directory and documents no way to submit a
   server, so this repository ships no `smithery.yaml` and no `.mcpb` bundle.
3. Glama: submit the GitHub repo, then claim it. `glama.json` lists maintainer `kajisho5`.
   Claiming again is what picks up a change to that file.
4. Scorecard uploads SARIF to code scanning. That upload needs code scanning enabled on the
   repository. The badge in the README fills in after a scan with `publish_results` has run.

## Reporting issues

Read [docs/design-decisions.md](docs/design-decisions.md) first: it lists behaviours that look like
bugs but are decisions, with the reason and the test that pins each one. If your report is about
one of them, say which sentence there no longer holds.

Bug reports should include: the exact command run, the actual vs. expected
output/behavior, and `python3 scripts/_contract.py doctor --json` if the issue
might be capability-related. See existing issues for the level of detail that's
useful here — a concrete reproduction beats a description of a hunch.
