# Process pitfalls

Mistakes made (or nearly made) while developing this repo that were not about FFmpeg
or a platform's behaviour — about the *process* of making a change safely. Written down
for the same reason `references/ci-platform-pitfalls.md` exists: a mistake that isn't
recorded gets repeated the next time a session starts fresh with no memory of it.

**This file is a living record.** Whenever a change here is made (or nearly made, then
caught before landing) because an existing guardrail — a pinned test, an environment
constraint, a platform's real behaviour under repeated attempts — wasn't checked first,
add an entry below. Don't wait to be asked.

## Before narrowing a `required`/`optional` capability list, grep for the pinned test that checks it

`scripts/_contract.py`'s `TOOL_META[...]["required"]` drives `doctor`'s per-tool `usable`
answer (`_tool_usability()` in `_contract.py` only reads `required`, never `optional`).
Moving a capability from `required` to `optional` — even when it's honestly true that a
new flag makes it conditional — silently changes what `doctor` reports as `usable: no`
on a machine missing that capability, for the tool's *default* invocation too.

`tests/test_contract.py`'s `DoctorDetectionTests` pins specific `usable` outcomes against
real captured `ffmpeg -filters`/`-encoders` fixtures (e.g. a plain Homebrew macOS build
correctly reporting `caption.usable: "no"` because it lacks `filter:subtitles`). A change
to `required` that isn't checked against these first can pass a quick unit test and still
break this fixture-based guarantee.

Caught twice while adding capability metadata for new flags (`caption.py --mode mux` in
#51, `doctor`'s `gpu_encoders` in #52) — in both cases the fix was to grep
`tests/test_contract.py` for `usable` and `_doctor(` *before* editing `TOOL_META`, not
after a test failure revealed it. Do that grep first, every time `required`/`optional`
changes.

## Git tag push and GitHub Release creation are not reachable from this environment — so they are not done from it

The git credentials available here can push to `refs/heads/*` (branches) but not
`refs/tags/*` — confirmed by a 403 straight from the git-receive-pack endpoint, not an
auth failure, meaning it's a deliberate scope restriction, not a bug to route around.
The GitHub MCP tool surface has no `create_release`/`create_tag` equivalent either, and a
direct call to the GitHub REST API's `/releases` endpoint with a raw token is blocked by
the outbound proxy itself.

Confirmed once (retried the tag push a second time "just in case" before accepting it).
Don't retry either path a second time. Since 0.16.11 this is moot for releases:
`.github/workflows/release.yml` creates the tag, the GitHub Release and the npm publish
from GitHub Actions on every push to `main` (README, "Development" → "Releasing"), so a
session never needs to push a tag at all — merging the PR is the release. The one thing
still worth knowing: that workflow's own `git push origin HEAD:main` (the automatic
version-bump commit) and its tag run under the built-in `GITHUB_TOKEN`, which by design
triggers no further workflow runs, so a red `tests` run for that bump commit is not
"missing" — it is never scheduled; the PR run before the merge is the one that counted.

## A throwaway probe must be pointed at a copy in a directory you have just verified with `pwd`, never at "the repo, probably"

While validating the auto-bump script for `release.yml`, a scratch run was meant to
execute against a temporary copy of the repo. It ran with the real checkout as its
working directory instead — a `cd` into the scratch path happened in a shell whose
working directory was reset between commands — and its `git add -A && git commit`,
`git tag v0.16.12` and two empty commits landed on the real branch and moved the real
local `v0.16.12` tag. Nothing was pushed, and `git reflog` plus a `git fetch --force` of
the tag from `origin` restored everything, but it was only noticed because `git status`
showed files the session had not edited.

Rule: a probe that runs `git commit`, `git tag`, `rm -rf`, or writes into the tree goes
in a directory created *and* verified in the same command (`cd "$DIR" && pwd && ...`),
not one assumed from an earlier `cd`; prefer a fixture built from a few `printf` lines
over a copy of the whole checkout (the copy carries the real `.git`, so a mistake there
is a mistake in the real history); and run `git status` on the real repo before
committing anything afterwards. `.claude/skills/destructive-operations/SKILL.md` says the
same thing for the tools themselves — it applies to the person testing them too.

## A quantitative test failing three different ways across fixture redesigns means the platform, not the fixture, is the problem

`test_stabilize_reduces_frame_to_frame_motion` (macOS CI, `stabilize.py`) failed with
three independently redesigned shake fixtures in a row — each time the instinct was "the
fixture's frequencies must be wrong," each time the retuned fixture failed a *different*
way on the next CI run. The actual cause (libvidstab behaving differently across the
Linux and macOS ffmpeg builds) was diagnosable from the first failure: a synthetic
fixture that reliably improves under one implementation and reliably gets worse under
another is evidence the implementations disagree, not that the fixture is miscalibrated.

If a quantitative assertion fails on one platform, survives a redesign, and fails again
on the *same* platform in a different way: stop redesigning the fixture. Either restrict
the strict assertion to the platform where it's provably correct (keeping a weaker,
platform-general check — output exists, has the right duration — everywhere), or escalate
before spending a third CI cycle on it.

## A fix merged after CHANGELOG.md's current-version section was drafted can silently miss it

`CHANGELOG.md`'s `## 0.12.0` section was written once, covering everything merged up to
that point. Two fixes that closed real issues after that point (#62's `--audio-stream`
extension via PR #72, #77's dry-run-dims fix via PR #88) landed with no further nudge to
go back and add a bullet — #62's fix actually got a bullet (its content is genuinely
described) but the `Closes #62` link was left off, and #77 was missed outright until a
direct question ("shouldn't this bump the version?") prompted a manual check. Neither was
caught by CI, because nothing checked CHANGELOG.md against what had actually been closed.

Caught by hand both times, then closed properly with `tests/test_contract.py`'s
`test_changelog_mentions_every_closed_issue_since_last_tag`, which walks `git log` back to
the latest release tag, extracts every `Closes #N.` from a commit body, and fails if that
issue number doesn't appear anywhere in `CHANGELOG.md`. This needs real history (`ci.yml`'s
`actions/checkout` step now passes `fetch-depth: 0` for exactly this reason — the default
shallow clone leaves no tag reachable to diff against, which would make the test silently
skip itself in CI, not fail). If this test ever needs to skip a genuinely changelog-less
closed issue (a pure process note, a duplicate, a revert of an unreleased change), name the
exemption in the test itself with a reason — don't just widen the regex or drop the check.

## Automation that can publish must not take its "major" cue from text it did not write

On 2026-09-11, three routine Dependabot merges (`actions/upload-artifact` 4→7,
`actions/setup-node` 4→7, `dependabot/fetch-metadata` 2→3) were published to npm as
**1.0.0, 1.0.1 and 1.0.2**. The release pipeline (`release.yml`, since #129) resolves the next
version from PR labels; an autolabeler rule added the same day applied `major` to any PR whose
*body* contained the literal breaking-change marker. Dependabot PR bodies quote the upstream
project's release notes verbatim, and upload-artifact's v5.0.0 notes contain exactly that
phrase — about *their* Node runtime, nothing to do with this package. One label, three
accidental majors, in nine minutes, with every job green.

Two things made it worse than one bad rule: every chore merge released at all (so the first
accident was followed by two more before anyone looked), and nothing in the pipeline treated
"the major number changed" as different from any other bump.

Fixes (this commit): no autolabeler rule produces `major` any more; `chore`/`ci`/`docs`/
`dependencies` PRs are excluded from version resolution so they release nothing; `release.yml`
refuses to auto-bump across a major boundary regardless of labels; and the release job is
serialised (`concurrency`) so back-to-back merges cannot race on the bump push.

The general rule: a pipeline that publishes must never derive an irreversible decision (a
major bump, a publish, a tag) from text it did not author — PR bodies, commit messages and
release notes are quotations as often as they are statements. Match on labels a person
applied, or on files changed, and make the irreversible step refuse anything surprising rather
than assume the surprise was intended. And after wiring any such automation, watch the first
few real runs' *results* (npm, tags) rather than their exit codes: the three runs here were
"success" by every check the job had.

## An action input that does not exist is a warning, not an error -- and "excluded from the notes" is not "no release"

The fix for the accidental majors above (#145) still released **1.0.4** for its own,
workflow-only merge. Two assumptions in `release.yml` were wrong and nothing checked either:

- `release-drafter/release-drafter@v6` was called with `dry-run: true` to "compute the next
  version read-only". That action has no `dry-run` input. GitHub Actions logs
  `Unexpected input(s) 'dry-run'` as a *warning* and runs the step anyway -- so every release
  run had been rewriting the draft release live, and the "read-only" in the comment was fiction.
- `exclude-labels` in `release-drafter.yml` was expected to make a chore-only merge resolve to
  the same version as the last tag. It only removes those PRs from the draft *notes*; the
  version resolver still applies `default: patch` and reports last+patch. The workflow's "same
  version → no-op" guard therefore never fired.

Both were visible in the first run's log and in the action's documented inputs, and both were
missed because the PR's test plan verified the YAML *parsed* and the config *contained* the
intended keys -- not that the action *did* what the comment claimed. Fixed by taking the
decision away from the action: `.github/scripts/resolve_version.py` reads the merged PRs'
labels through `gh api`, returns nothing when nothing is releasable, refuses `major`, and has
a unit test in `tests/test_contract.py` with fake label data for each rule.

The general rule, twice over now: when wiring a third-party action, read its `action.yml`
inputs (or `Unexpected input(s)` in the first log) before trusting a parameter, and treat
any step whose output decides an irreversible action as something to unit-test with fixed
inputs, not something to confirm by reading its YAML. And watch the first real run's
*effect* (tags, npm), which is how both incidents were actually noticed.
