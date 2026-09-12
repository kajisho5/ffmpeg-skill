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
npm test                    # tests/test_all.py + tests/test_contract.py
npm run release-check       # packaging + installer + MCP + doctor + full suite
python3 scripts/_contract.py doctor   # what this machine can actually run
```

Python 3.9+ standard library only — no new runtime dependencies. Every script
must keep working with nothing beyond `ffmpeg`/`ffprobe` on `PATH`.

## Tests

- `tests/test_contract.py` — contract ↔ implementation ↔ MCP ↔ installer ↔ docs
  consistency, JSON/error-shape correctness, dry-run guarantees, capability
  detection.
- `tests/test_all.py` — real-media conformance across codecs, containers, VFR,
  HDR, multi-track audio, and every tool's actual ffmpeg invocation.

Add a test alongside any behavioral change. A fix without a regression test that
would have caught the original bug isn't done yet.

## Pull requests

- Keep PRs focused — one fix or one small feature per PR.
- Run `npm test` locally before opening; CI runs on Linux, macOS, and Windows, and
  all three must pass.
- Explain *why*, not just *what*, in the PR description — the reasoning is what
  future maintainers (human or agent) need most.

## Reporting issues

Read [docs/design-decisions.md](docs/design-decisions.md) first: it lists behaviours that look like
bugs but are decisions, with the reason and the test that pins each one. If your report is about
one of them, say which sentence there no longer holds.

Bug reports should include: the exact command run, the actual vs. expected
output/behavior, and `python3 scripts/_contract.py doctor --json` if the issue
might be capability-related. See existing issues for the level of detail that's
useful here — a concrete reproduction beats a description of a hunch.
