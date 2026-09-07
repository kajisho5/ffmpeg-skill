---
name: reproducing-ci-locally
description: Run the CI gate on your machine so it agrees with the runner — deriving the exact command, paths, markers, and env from the workflow file instead of the Makefile, unblocking gate steps that short-circuit and hide the next failure, pinning the linter version CI resolves, building the interpreter/toolchain environment the runner builds, and confirming the run is green instead of explaining a red job away. Use when a check passes locally but fails in CI (or the reverse), when a lint/format job goes red on an untouched file, when setting up a local dev loop for an unfamiliar repo, or before pushing a branch you expect to merge.
---

# Reproducing CI Locally

A local check is only useful if it runs the same thing the runner runs. Most
"green locally, red in CI" failures are not bugs in the code — they are a
difference between two commands: different paths, different test markers,
different env, a different linter version, or a different interpreter.

The fix is mechanical: **derive the local command from the workflow file**, not
from the Makefile, not from habit, not from what the last repo used.

## Read the workflow before you run anything

The workflow is the contract. The Makefile is a convenience that drifts from it.

```bash
# What the gate actually is, in order
sed -n '/jobs:/,$p' .github/workflows/ci.yml

# Every command CI runs, across all workflows
grep -rn "run:" .github/workflows/
```

Copy out four things, verbatim:

1. **The commands and their order.**
2. **The paths each command is scoped to** (`ruff check app tests scripts` is not
   `ruff check .`).
3. **Test selection** — marker expressions, `-k` filters, which suites are excluded.
4. **The `env:` block**, and the runtime/toolchain versions in `setup-*` steps.

Each of those four is a distinct way to get a wrong answer locally.

**Paths.** If CI lints `app tests scripts` and you run `ruff check .`, you get
findings from directories CI never looks at — a red that isn't a merge blocker
and shouldn't be "fixed" in an unrelated PR. Run it the narrow way to reproduce
the gate; run it the wide way only when you're deliberately auditing.

**Markers.** A suite-wide `make test` that excludes one marker is not the CI
gate if CI excludes six. Live-credential integration tests deselected in CI will
run locally, hit a fake key, and fail in a way that looks like a regression:

```bash
# Wrong: local shorthand — pulls in suites CI never runs
pytest -m "not browser"

# Right: the full expression, copied from the workflow
pytest -m "not browser and not slow and not load and not integration"
```

**Env.** Config objects instantiated at import time (a settings singleton at
module scope, an engine built when the module loads) make *collection* fail
without the workflow's variables — a wall of "Field required" errors that looks
like a broken suite. Mirror the `env:` block, including the *shape* of values:
if CI passes a Postgres URL and the module builds a pooled engine, a local
SQLite URL raises on arguments that dialect rejects before a single test runs.

Keep those values in a gitignored `.env.ci` copied from the workflow's `env:`
block, so the local command is the workflow command plus one `set -a`:

```bash
set -a; . ./.env.ci; set +a
pytest -m "not browser and not slow and not load and not integration"
```

## A short-circuiting gate hides the next failure

Gate steps run in order and the job stops at the first red. So the CI log shows
you *one* failure even when three are waiting:

```yaml
- run: ruff check .          # fails here …
- run: ruff format --check . # … so this never runs, and you never see it
```

You fix the lint error, push, and get an immediate second red for formatting.
Same shape everywhere: `cargo fmt --all -- --check` before `cargo clippy
--all-targets -- -D warnings` before `cargo test` means a formatting failure
tells you nothing about whether clippy or the tests pass.

**Run every gate step locally, even after one fails.** Don't `&&`-chain them
while diagnosing — run them separately and collect the whole set:

```bash
ruff check app tests scripts;  echo "lint:   $?"
ruff format --check app tests; echo "format: $?"
pytest -m "not integration";   echo "tests:  $?"
```

The corollary: after a red job, never report "only X is broken." Everything
downstream of X is unmeasured until you run it.

## Pin what gates the build, and reproduce the version CI resolves

An unpinned gating tool means the gate changes without a commit. A range like
`ruff>=0.4.0` resolves to whatever shipped this morning, and a release that
*widens file coverage* — a formatter that starts formatting code blocks inside
Markdown, a linter that promotes a rule to default — turns every open PR red on
files nobody touched.

Two habits:

- **Pin the linter, formatter, and toolchain** in the manifest, and bump them in
  a dedicated PR where the reformat is the whole diff.
- **Reproduce with the version CI resolves**, not the one you happen to have:

```bash
uvx ruff@0.16.4 format --check .      # exactly what the runner would install

# Node: CI does `npm ci` then `npx prettier --check web` — that's the LOCKFILE's
# prettier. A bare `npx prettier` fetches the latest and flags files CI is fine
# with. Read the pinned version, then ask for it.
grep -m1 -A2 '"node_modules/prettier"' package-lock.json
npx -y prettier@3.8.3 --check web
```

Formatting a file CI never complained about is not a fix — it's an unrelated
diff caused by using a different tool than the gate.

## Build the environment the runner builds

Package managers will happily invent an environment for you, and the one they
invent is not CI's.

- **A fresh clone or worktree has no virtualenv.** `uv run <tool>` silently
  creates a bare one *without* your dev extras, then fails with `Failed to
  spawn: ruff` — which reads like a missing dependency rather than a missing
  environment.
- **`uv run` re-syncs from the lockfile** against your *host* interpreter. On a
  Python newer than CI's matrix, a pinned dependency with no wheel for that
  version gets built from source and fails on a compiler error that has nothing
  to do with your change.
- **Extras differ.** If CI installs `[dev,web]` and `make install` installs
  `[dev]`, the full suite errors at collection locally on an import CI has.

Build it explicitly, at CI's interpreter version, with CI's extras:

```bash
uv venv .venv --python 3.12 --seed
uv pip install --python "$PWD/.venv/bin/python" -e ".[dev,web]"
.venv/bin/python -m ruff check app tests scripts
.venv/bin/python -m pytest -m "not integration"
```

Driving the tools as `.venv/bin/python -m <tool>` sidesteps the re-sync entirely.
If you prefer `uv run`, pass `--no-sync`. And prefix with `env -u VIRTUAL_ENV`
when a shell profile exports one — otherwise the run is silently redirected into
an unrelated environment and its results mean nothing.

## Fix divergence in shared config, not in the workflow

When you find a difference, ask where the fix belongs. A flag added to the
workflow YAML fixes CI and leaves every local run diverging — so the next person
hits the same confusion.

Prefer the file both sides read:

- Test-runner flags → `addopts` in `pyproject.toml`, not the workflow's `run:`.
  (Import-mode is the classic one: a source directory on `sys.path` shadowing an
  installed compiled package is a *config* problem, and pinning
  `--import-mode=importlib` in `addopts` fixes local and CI together.)
- Marker definitions, coverage thresholds, lint rules and target version → the
  project manifest.
- Keep `requires-python` and the linter's `target-version` in sync; a mismatch
  means the linter applies rules for a runtime you don't support.

The workflow should read as `make lint` / `make test` plus the environment. When
it contains flags the local target doesn't, that's the divergence.

## Know which checks are actually gates

Not every command in the repo is a merge blocker, and treating them as equal
wastes PRs.

```bash
# Which jobs are required is a repo setting, not a file — check it
gh api repos/OWNER/REPO/branches/main/protection --jq '.required_status_checks.contexts'
```

If CI runs the linter but not the type checker, then a pre-existing type error in
an untouched module is not blocking your PR — don't fold a speculative fix for it
into an unrelated change, and don't claim CI verifies types. The inverse matters
too: a helper target like `make quality-check` that runs *more* than CI will show
you reds that no one is gating on.

## Finish by confirming the run, not by explaining it

"Passes locally" is a prediction. Wait for the real result:

```bash
gh pr checks --watch
gh run view --log-failed        # the failing step's output, not the summary
```

When a job is red, fix it in the same PR if the fix is feasible. If you believe
it's pre-existing, **prove it**: check out the base commit and run the same
command there. An unverified "pre-existing / out of scope" is how a base branch
becomes permanently red.

Two traps in the log itself:

- A step gated on an event (`if: github.event.action == 'opened'`) is skipped
  when you re-run by pushing a commit. Green-on-rerun can mean *not run*.
- A permissions failure at the last step (an HTTP 403 posting a comment) shows
  every build/test step green with a red X on the job — read which step failed
  before concluding the code is broken.

## Checklist

```
Before running anything:
- [ ] Read .github/workflows/*.yml — commands, order, paths, markers, env, versions
- [ ] Local command uses CI's paths (not `.`) and CI's full marker expression
- [ ] Workflow env: block mirrored, including value shape (DB URL dialect, etc.)

Environment:
- [ ] venv created explicitly at CI's runtime version, with CI's extras
- [ ] Tools driven from that venv (`.venv/bin/python -m …` or `--no-sync`)
- [ ] `env -u VIRTUAL_ENV` when a shell profile exports one
- [ ] Gating linter/formatter/toolchain pinned; local run uses the pinned version

Running:
- [ ] Every gate step run separately — a first failure hides the rest
- [ ] Formatter check run even when the linter passed (they are different tools)

Fixing:
- [ ] Divergence fixed in shared config (manifest/addopts), not only in the workflow
- [ ] Checked which jobs are actually required before treating a red as blocking
- [ ] Waited for the real run; any red either fixed here or proven on the base commit
```

## Note for this repository (ffmpeg-skill)

This repo's gate is `.github/workflows/ci.yml`: install ffmpeg per-OS (apt /
`brew install ffmpeg-full` / `choco install ffmpeg`), then `python
tests/test_all.py` and `python tests/test_contract.py` (unittest, not pytest —
there is no marker expression to copy, but there IS an OS-conditional: a
handful of `test_contract.py` tests are `skipIf`'d on Windows because they
depend on a POSIX shell shim, not on CI's own `if:` gating). Read the actual
workflow file before assuming a local `npm test` run matches — `npm test` runs
both files with no OS-conditional skip logic layered on top, so on a
non-Windows machine it is already a faithful local reproduction; the gap only
shows up when debugging a Windows-specific CI failure, where the fix is to
read what `skipIf` actually excludes before assuming a fix applies everywhere.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
