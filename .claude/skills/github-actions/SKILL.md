---
name: running-github-actions-efficiently
description: Cut GitHub Actions minutes and wall-clock time without losing coverage — the OS billing multiplier (macOS 10x / Windows 2x / Linux 1x), trigger hygiene that stops push+pull_request double-firing, concurrency that cancels superseded runs, dependency caching keyed on lockfiles, matrix discipline, and auditing scheduled crons that bill 24/7. Use when CI is burning included minutes, when runs feel slow, when setting up a new repo's workflows, or when reviewing an existing workflow for waste.
---

# Running GitHub Actions Efficiently

Actions minutes on **private** repos bill against a monthly included quota; public
repos are free. So cost concentrates in private repos, and a handful of workflows
usually dominate the bill. This skill is the checklist for finding and fixing that
waste. Every fix below preserves what CI actually verifies — none of them trade
away coverage.

## First, know the one number that dominates everything

Minutes are billed **per job**, rounded up to the minute, times a **runner-OS
multiplier**:

| Runner | Multiplier |
|--------|-----------|
| Linux (`ubuntu-*`) | **1x** |
| Windows (`windows-*`) | **2x** |
| macOS (`macos-*`) | **10x** |

A one-minute macOS job costs the same as ten Linux minutes. This single fact
reorders every optimization: **a repo with a few macOS jobs can outspend a repo
with ten times as many Linux jobs.** Before anything else, find your macOS jobs
and ask of each: does this step genuinely need macOS?

- Xcode / Apple-platform builds and tests (`xcodebuild`): yes, macOS is required.
- Linters and formatters (even Swift ones like SwiftLint/SwiftFormat), pure
  unit tests with no Apple frameworks, packaging, doc builds: usually **no** —
  move them to `ubuntu-latest` and cut that job's cost ~10x.

Split the must-be-macOS work into its own job and push everything else to Linux.
If a single macOS job does both (e.g. runs SwiftLint *and* an Xcode build), split
it: a cheap Linux `lint` job plus the macOS `build` job. The tools only parse
source, so the Linux job just checks out and runs them — no toolchain build.

SwiftLint and SwiftFormat both ship self-contained prebuilt Linux binaries, so
"Swift means macOS" is a myth for the linting half of the pipeline:

```yaml
  lint:
    runs-on: ubuntu-latest        # 1x, not 10x
    steps:
      - uses: actions/checkout@v4
      - name: Install SwiftLint & SwiftFormat (Linux)
        run: |
          set -euxo pipefail
          curl -fsSL -o /tmp/sl.zip https://github.com/realm/SwiftLint/releases/download/0.65.0/swiftlint_linux_amd64.zip
          unzip -oq /tmp/sl.zip -d /tmp/sl
          sudo install -m0755 /tmp/sl/swiftlint-static /usr/local/bin/swiftlint
          curl -fsSL -o /tmp/sf.zip https://github.com/nicklockwood/SwiftFormat/releases/download/0.62.1/swiftformat_linux.zip
          unzip -oq /tmp/sf.zip -d /tmp/sf
          sudo install -m0755 /tmp/sf/swiftformat_linux /usr/local/bin/swiftformat
      - run: swiftlint lint
      - run: swiftformat . --lint
```

Use SwiftLint's **`swiftlint-static`** (not the dynamically linked `swiftlint`,
which needs a Swift runtime the bare runner lacks) and SwiftFormat's
`swiftformat_linux` — both are statically linked and run on plain `ubuntu-latest`.
Pin versions in the URL, `curl -f` to fail on a bad download, and reference the
exact binary names rather than a fragile `find`.

**What genuinely can't move.** A SwiftPM target only builds on Linux if its code
and its dependencies do. Two reliable signals it's macOS-pinned: the package
declares `platforms: [.macOS(...)]` only, or it depends on an Apple-focused
library (e.g. `SQLite.swift`, anything importing `AppKit`/`SwiftUI`/`CloudKit`).
Don't gamble a repo's only build job on a Linux move — if `swift build` there
depends on such a package, keep it on macOS. `grep -rE 'import (AppKit|SwiftUI|
Cocoa|CloudKit|CoreData)'` over the target's sources is a fast pre-check.

## Trigger hygiene: stop paying for the same commit twice

The most common silent waste is a workflow that runs **twice on every change**:

```yaml
on:
  push:            # ← no branch filter: fires on EVERY push to EVERY branch
  pull_request:    # ← also fires for the PR built from those same commits
```

When you push a feature branch that has an open PR, the `push` event and the
`pull_request` event both fire a full run of the same commit. On a 10x macOS
runner that doubles the most expensive thing you have.

**Fix — scope `push` to the branches you actually gate on:**

```yaml
on:
  push:
    branches: [main]   # only post-merge commits to main
  pull_request:        # all pre-merge validation happens here
```

Now branch work is validated once (by the PR) and `main` is validated once
(post-merge). No commit is ever built twice for the same reason.

Add **path filters** so unrelated changes don't spin a runner at all:

```yaml
on:
  pull_request:
    paths-ignore: ['**.md', 'docs/**', '.github/ISSUE_TEMPLATE/**']
```

(Note: a required status check gated on `paths` can block PRs that legitimately
change nothing in-scope — prefer `paths-ignore` for docs, or make the check
non-required, rather than `paths` on a required job.)

## Concurrency: kill superseded runs automatically

Without a `concurrency` block, pushing three commits in quick succession starts
three full runs and lets all three finish. You only care about the last one.

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

This cancels any in-progress run on the same ref when a newer one starts. It is
the single highest-leverage line for anyone who pushes iteratively or force-pushes
during review. Put it at the top level of every workflow.

One caveat: don't set `cancel-in-progress: true` on workflows that must run to
completion once started — deploys, releases, anything that writes external state.
Scope those with a distinct group and leave cancellation off (or queue them).

## Cache dependencies — keyed on the lockfile

Re-downloading and re-resolving dependencies on every run is pure waste. Cache the
dependency directory, keyed on the **lockfile** so the cache invalidates exactly
when dependencies change, with a `restore-keys` fallback for partial hits.

Most `setup-*` actions have caching built in — prefer it over hand-rolled
`actions/cache` where it exists:

```yaml
# Python (uv)
- uses: astral-sh/setup-uv@v6
  with:
    enable-cache: true
    cache-dependency-glob: "uv.lock"

# Python (pip)
- uses: actions/setup-python@v5
  with: { python-version: '3.12', cache: 'pip' }

# Node
- uses: actions/setup-node@v4
  with: { node-version: '20', cache: 'npm' }

# Go
- uses: actions/setup-go@v5
  with: { go-version: '1.22', cache: true }   # caches modules + build cache
```

For ecosystems without built-in caching, use `actions/cache` directly:

```yaml
# Rust (cargo registry + build)
- uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/registry
      ~/.cargo/git
      target
    key: ${{ runner.os }}-cargo-${{ hashFiles('Cargo.lock') }}
    restore-keys: ${{ runner.os }}-cargo-

# SwiftPM (build + package repository cache)
- uses: actions/cache@v4
  with:
    path: |
      .build
      ~/Library/Caches/org.swift.swiftpm
    key: ${{ runner.os }}-spm-${{ hashFiles('Package.resolved') }}
    restore-keys: ${{ runner.os }}-spm-

# Docker layers (buildx / build-push-action)
- uses: docker/build-push-action@v6
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

Cache the **dependency graph** (downloaded/resolved packages), not fragile
machine-specific build state. Caching compiler-derived artifacts with absolute
paths (e.g. all of Xcode's `DerivedData`) can produce flaky or wrong builds — the
dependency cache is the safe, high-ROI target.

Two speed wins on macOS runners specifically:

```yaml
# Skip the multi-minute `brew update` when you just need a couple of tools
- run: brew install swiftlint swiftformat
  env:
    HOMEBREW_NO_AUTO_UPDATE: "1"
    HOMEBREW_NO_INSTALL_CLEANUP: "1"
```

## Matrix discipline

A matrix multiplies job count: `os: [ubuntu, macos, windows] × python: [3.10, 3.11,
3.12, 3.13]` is **12 jobs per run**, and the macOS/Windows cells carry the 10x/2x
multipliers. Test broadly, but deliberately:

- Run the **full matrix** on `main` / nightly, and a **minimal matrix** (one OS,
  min+max version) on PRs. `if: github.event_name == 'push'` gates the expensive
  cells.
- `fail-fast: true` (the default) stops the whole matrix on the first failure —
  keep it unless you specifically need every cell's result.
- Test the versions you actually support. Dropping an EOL runtime is free minutes.
- Prefer Linux cells; add macOS/Windows cells only for genuinely OS-specific code.

## Scheduled workflows bill around the clock

A `schedule:` cron runs whether or not anyone touched the repo — so it bills
continuously, forever, and is the easiest thing to forget. Audit every one:

```yaml
on:
  schedule:
    - cron: '*/15 * * * *'   # every 15 min = ~2,880 runs/month. Almost never worth it on Actions.
```

- **Uptime / health checks** do not belong on Actions — a `*/5` or `*/15` cron is
  a runaway meter. Use a purpose-built external monitor (many have free tiers).
- **Daily rebuilds of static content that hasn't changed** (e.g. redeploying a
  site on a timer) are wasted runs — deploy on push instead, and keep a
  `workflow_dispatch:` for manual rebuilds.
- **DST/timezone hacks** that register two crons and gate one out still pay the
  runner spin-up (checkout + toolchain setup) for the run that no-ops. Gate
  *before* the setup steps, or compute the schedule so only one fires.
- Genuinely periodic jobs (a real nightly build) are fine — just right-size the
  frequency to how often the input actually changes.

Find them all across a repo:

```bash
grep -rl "schedule:" .github/workflows/
```

## Failures and long runs still bill

- A job that fails at minute 9 of 10 bills all 9. Order steps cheap-to-expensive
  and lint/typecheck **before** the long build, so bad commits die fast.
- Add a `timeout-minutes:` to every job so a hung step can't burn the max 6-hour
  runner allotment.
- Flaky tests that auto-retry the whole workflow multiply cost — fix the flake
  rather than papering over it with reruns.

## Measure before and after

Don't guess which workflow is expensive — measure:

- **Repo/org billing:** Settings → Billing → this month's Actions minutes, and
  the per-repo breakdown.
- **Per-run breakdown (API):** `/repos/{owner}/{repo}/actions/runs/{id}/timing`
  returns billable milliseconds split by OS multiplier.
- **What runs most (API):** `/repos/{owner}/{repo}/actions/runs?created=>=YYYY-MM-DD`
  — count runs per workflow and note the triggering `event`. A workflow with far
  more runs than you have merges is double-firing or over-scheduled.

Fix the top one or two offenders first; the distribution is almost always
long-tailed.

## Checklist

```
Audit:
- [ ] Identified every macOS/Windows job (10x/2x) — each justified, or moved to Linux
- [ ] Listed every schedule: cron and confirmed each is worth running 24/7
- [ ] Compared runs-per-workflow to merge frequency (excess = double-fire/over-schedule)

Triggers:
- [ ] push scoped to gated branches (e.g. [main]); pull_request handles pre-merge
- [ ] No workflow builds the same commit on both push and pull_request
- [ ] paths-ignore excludes docs/markdown-only changes

Concurrency:
- [ ] concurrency + cancel-in-progress on CI workflows
- [ ] Deploy/release workflows use a distinct group and do NOT cancel mid-run

Caching & speed:
- [ ] Dependencies cached, keyed on the lockfile, with restore-keys
- [ ] setup-* built-in caching used where available
- [ ] Cheap checks (lint/typecheck) run before the long build; jobs have timeout-minutes
- [ ] macOS brew steps skip auto-update (HOMEBREW_NO_AUTO_UPDATE)

Matrix:
- [ ] Full matrix on main/nightly; reduced matrix on PRs
- [ ] Only supported runtime versions; only necessary OSes
```

## Note for this repository (ffmpeg-skill)

`.github/workflows/ci.yml` already gets the trigger-hygiene rule right —
`push: branches: [main]` plus an unscoped `pull_request:` means no commit is
built twice for the same reason. It has no Python dependency install step to
cache (stdlib only, nothing to resolve), so the caching section mostly doesn't
apply here.

Two things this skill's checklist would flag as genuinely missing, verified by
reading the file directly (not assumed): **no `concurrency:` block** — pushing
several commits to an open PR in quick succession runs the full 3-OS matrix
every time with nothing cancelling the superseded ones, and macOS is the 10x
runner in that matrix — and **no `timeout-minutes:`** on the job, so a hung
`ffmpeg`/`choco`/`brew` step would run to the platform's multi-hour default
before failing instead of failing fast. Neither has been added as part of
adding this skill; they're noted here as a real, verified finding for whoever
next touches the workflow file to decide on.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
