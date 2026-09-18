---
name: reviewing-ffmpeg-skill-changes
description: Review a change to the ffmpeg-skill repository for the failures its own contract makes possible — a claim in a result document that is true at one layer and false at the layer a caller reads, a new flag that reaches the code but not the contract/docs/demo surfaces, a "bug" that docs/design-decisions.md already decided with a pinning test, a fix with no regression test, a new runtime dependency or a raw ffmpeg shell call that breaks the scope boundary, a SKILL.md line added without one trimmed, a review that re-derives findings from a summary instead of the tree at the reviewed commit. Use when asked to review a PR or diff in this repository, when authoring code here and needing a pre-commit check, or when triaging an external review or audit report about this codebase.
---

# Reviewing ffmpeg-skill Changes

This repository has an unusual failure mode, and a review that misses it looks
thorough while catching nothing. The product is a **JSON result document** that an
agent reads instead of watching the video. A change can be correct at the FFmpeg
layer, correct at the Python layer, and still ship a lie at the layer that
matters: `status: "completed"` next to a non-zero exit, `verified: true` for
something the tool never measured, a cut described as lossless when the keyframe
snap moved it 1.24 s. The 0.9.1/0.10.0 "honesty fix" (`cut.py`'s `mode` /
`keyframe_snapped` / `duration_delta_seconds`, `check.py`'s `reason`, `render.py`'s
check-stage exit code) exists because three such claims shipped and were caught
after the fact. **Review the claim, not just the code.**

The second failure mode is re-reporting decisions. Three review rounds on
2026-09-12 re-reported entries in `docs/design-decisions.md`, which is why that
file exists.

## Establish the review base first

Read the tree at the commit under review, not a summary of it and not your own
working copy if it has moved.

```bash
git fetch origin && git log --oneline -1 origin/main
git diff --stat origin/main...HEAD          # what the branch actually changes
git show origin/main:docs/design-decisions.md | head -40
```

At least one earlier review reported committed media that is not in git and
colour flags that were already validated — both came from reading a summary
rather than the tree. Before reporting any finding, name the file and line you
read it at, and confirm the symbol still exists there.

## Check the claim at the layer the caller reads

For every writing tool touched, trace the success document it prints and ask
whether each field is something the tool *measured*.

| field | the review question |
| --- | --- |
| `status` | can this be `completed` while the exit code is non-zero? (`die()` must set `failed`) |
| `verified` | is it the conjunction of steps the tool actually ran, or an assumption? |
| `reencodes_*` | was a copy fallback taken and reported, or silently assumed not taken? |
| `dropped_non_av_streams` | did the timeline move (track must be dropped, `true`) or stay (kept, `false`)? |
| `keyframe_snapped`, `duration_delta_seconds` | for `cut`: is the measured divergence reported, not rounded away? |
| `mode` | does it name the path actually taken (`copy` vs re-encode)? |
| `error.kind` | `input` / `ffmpeg` / `output` / `missing_tool` / `timeout` / `verification` / `interrupted` — is it the one that happened? |
| `error.retryable` | must stay `false`; a `true` here invites a blind retry loop |

`--dry-run` claims matter too: `info()` rewrites `wrote X` to `[dry-run] would
write X`, and `analysis_only` tools (`probe`, `check`, `sync`, `multicam`,
`scenes`, `cropdetect`, `report`, `silence`, `loudness`, `stabilize`) do run
FFmpeg to measure. A change that makes a writing tool print a write claim under
dry-run is a defect.

See `references/result-honesty.md` for the code pointers and the exact test names
that pin each of these.

## Refuse to report what the repo already decided

Grep `docs/design-decisions.md` before writing any "this looks wrong" sentence.
Each entry names the rationale *and* the test that pins it. If the change under
review is about one of them, the report must say **which sentence there no longer
holds** — otherwise it is a re-report and will be closed as one.

Also grep before claiming a gap, because several checks are centralised:

```bash
grep -rn "validate_color(" scripts/     # colour flags are validated at tool level, not per call site
grep -rn "apply_common()" scripts/      # --crf range check happens once, here
grep -rn "time_arg(" scripts/           # the single time parser; a tool parsing time itself is the bug
```

## Score the change against the repository's rules

A change that is correct in isolation can still be unshippable here. Verify each
applicable rule against the tree:

- **Contract first.** `python3 scripts/_contract.py --json` is the source of truth
  for tool names, flags, dry-run semantics and error kinds. `README.md` and
  `SKILL.md` restate it and are tested against it. A new flag that exists only in
  a script is half shipped; extend the generator, never hand-duplicate a schema.
- **Every surface, or it is not shipped.** A `feat` updates `README.md` (tool
  table, contract table, gotchas), `SKILL.md`, `references/scripts.md`,
  `docs/contract.md` and `CHANGELOG.md`. See `references/surfaces.md`.
- **`SKILL.md` stays under 30,000 bytes** — enforced by
  `test_skill_md_stays_under_the_30kb_budget`, not a convention. Adding a line
  means trimming one, and the PR should say which.
- **A demo, or the feature is invisible.** Every script under `scripts/` must
  appear in some demo's command line (a test asserts it); a `feat` adds a
  before/after entry to `demos/build.py` and regenerates `docs/demos.md` with
  `python3 demos/build.py --docs`. Tools whose whole output is a table/JSON/HTML
  go in `INSPECTION` instead.
- **A regression test, or the fix is not done.** `CONTRIBUTING.md` is explicit: a
  fix without a test that would have caught the original bug is not finished.
- **Stdlib-only, Python 3.9+.** No new runtime dependency; every script must work
  with nothing but `ffmpeg`/`ffprobe` on `PATH`.
- **Scope boundary.** No AI/LLM content judgement, no cloud or API keys, no raw
  `ffmpeg`/`ffprobe` shell invocation outside `scripts/*.py`, no mutation of input
  files, no creative decisions on the caller's behalf.
- **1.x discipline.** Contract-shape changes wait for 2.0 and ship as parallel
  keys (`result_v2`, `hdr_signal`). A PR that changes the meaning of an existing
  field in a patch release is a finding.

## Run the gate, then read it honestly

```bash
npm test                              # tests/test_all.py + tests/test_contract.py
npm run release-check                 # packaging + installer + MCP + doctor + full suite
python3 scripts/_contract.py doctor   # what this machine can actually run
```

CI is a three-OS matrix (Linux/macOS/Windows) across FFmpeg 5.1, 6.1, 7.1 and
8.x/9.x. A change that passes locally on one FFmpeg major is not verified. Report
a red check as its own statement — never a parenthetical under a "done" claim —
and confirm green after the run finishes rather than predicting it. See
**reproducing-ci-locally** in this repo's `.claude/skills/`.

Two traps specific to reviewing here:

- **Never quote the release bump's skip-CI marker in a PR body.** A squash merge
  copies it into the merge commit and skips every workflow.
- **`references/process-pitfalls.md` is a maintainer diary** and is not in the npm
  package; the other reference files are. Packaging claims belong against
  `package.json` `files` and `bin/install.js` `PAYLOAD`.

## Write the review

Order findings by what they cost: a false claim in a result document first, then a
missing surface or test, then style. For each, give file and line at the reviewed
commit, the concrete failure it causes, and the smallest fix. State plainly which
checks you ran and what you did not verify — an unrun check reported as passing is
the same defect as an overstated result document, one artifact over. Defer deep
security audits to a dedicated security pass; this skill reviews quality, scope
and claim-honesty.

## Additional Resources

### Reference Files

- **`references/result-honesty.md`** — the JSON contract, the fields that carry
  claims, and the test that pins each one.
- **`references/surfaces.md`** — the full surface inventory a change must touch,
  and how to check for drift.
- **`references/review-checklist.md`** — the runnable pre-commit and pre-merge
  checklist with exact commands.

### Note for this repository (ffmpeg-skill)

This skill is repo-local and intentionally duplicates none of
**writing-defect-reports**, **verifying-external-behavior** or
**reproducing-ci-locally** (all in `.claude/skills/`); it points at them instead.
Its distinguishing subject is the review of a *claim* — the `emit()`/`die()`
document — which is where this codebase's shipped defects have actually come from.
