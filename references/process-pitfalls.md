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

## Git tag push and GitHub Release creation are not reachable from this environment

The git credentials available here can push to `refs/heads/*` (branches) but not
`refs/tags/*` — confirmed by a 403 straight from the git-receive-pack endpoint, not an
auth failure, meaning it's a deliberate scope restriction, not a bug to route around.
The GitHub MCP tool surface has no `create_release`/`create_tag` equivalent either
(`create_branch`, `create_pull_request`, `create_or_update_file` exist; nothing for
releases). A direct call to the GitHub REST API's `/releases` endpoint with a raw token
is also blocked by the outbound proxy itself (its own 403, pointing at Anthropic's docs,
not GitHub's).

Confirmed once (retried the tag push a second time "just in case" before accepting it).
Don't retry either path a second time — if `git push origin <tag>` 403s, or no
release-creation tool is found in one `ToolSearch` pass, say so once and hand the user
the two-minute browser-only path instead (open the repo's `/releases/new`, type the new
tag name in the tag field — GitHub creates it from the target branch on publish, no git
command needed).

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
