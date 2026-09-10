---
name: verifying-external-behavior
description: Confirms what a third-party library, remote API, build backend, or scraped document actually does before writing code that depends on it — throwaway probes that run in seconds, permissive clients that forward wrong arguments instead of rejecting them, per-endpoint docs that don't generalize, response shapes that make a "fast path" always-false, fakes that encode your assumption rather than the service's behavior, and dry-runs that skip the step that fails. Use when integrating a new dependency or endpoint, writing a tolerated-status or error branch, choosing a client argument name, testing against a fake, or reviewing code that asserts an upstream contract.
---

# Verifying External Behavior

Most integration bugs are not coding errors. They are a belief about someone
else's system — a status code, a parameter name, a response shape, a build
backend's scoping rule — that was never checked and turned out to be wrong. The
code is written correctly against a contract that does not exist.

The fix is not more care. It is a **probe**: a throwaway command that asks the
real system the exact question, before the code is written. Probes cost seconds.
The bugs they prevent are silent, ship green, and are found months later.

## Probe the exact call you are about to write

Not a similar call, not the documented example — the same endpoint form, the same
library version, the same argument spelling.

```bash
# A library's real defaults / return shapes, with no venv to create or clean up
uv run --no-project --with somelib python -c "import somelib; print(somelib.Thing())"

# The exact URL, including the collection-vs-item distinction
curl -s -o /dev/null -w '%{http_code}\n' https://api.example.com/v1/things
curl -s -o /dev/null -w '%{http_code}\n' https://api.example.com/v1/things/1

# What a build backend actually put in the artifact
uv build && unzip -l dist/*.whl

# A real service instead of a fake, for one minute
docker run --rm -p 6390:6379 redis:7-alpine
```

Two rules make probes worth the minute they cost:

- **Probe before you design around the answer.** A probe that confirms a
  parameter tweak "should" fix a discrepancy is worth more than the tweak.
- **Paste the probe command and its output into the PR, comment, or test.** A
  finding with no reproduction decays into folklore, and the next person re-derives
  it — or, worse, trusts it after it has gone stale.

## Permissive clients don't reject wrong arguments — they ignore them

This is the highest-severity class, because the failure returns *plausible data*.
Many HTTP client wrappers forward keyword arguments verbatim into the query
string without validating them against their own documented parameter list. The
remote service then drops the unknown parameter and applies its default — often
"the authenticated user". A misspelled selector (`owner=` for `owner_screen_name=`,
`id_=` for `id=`) does not raise; it silently returns *someone else's* records.

Never infer "the library would have rejected that" from the library's declared
parameter list. Read the bytes that leave the process:

```python
# Probe: intercept the transport and print the outbound request, then stop.
import requests

sent = {}
def spy(self, method, url, **kw):
    sent["url"], sent["params"] = url, kw.get("params")
    raise RuntimeError("probe: request intercepted")

requests.Session.request = spy
try:
    client.favorites(id_=12345)          # the call you were about to ship
except RuntimeError:
    pass
print(sent)      # {'url': '.../favorites/list.json', 'params': {'id_': 12345}}
```

If the parameter you passed is not in `params` under the name the service
documents, the call is wrong no matter how healthy the response looks.

Two corollaries:

- **Pass every selector by keyword.** Clients that bind positional arguments in a
  per-endpoint order will happily accept `get_thing(owner, slug)` and send `slug`
  as `owner_id`, while a neighbouring method with the same-looking signature is
  correct by luck.
- **Check that the parameter exists at all.** Some endpoints have no equivalent of
  the selector you want. "Forward it under the right name" is not a fix when the
  right name does not exist — the feature has to be built differently.

## Per-endpoint docs do not generalize across sibling endpoints

A status code documented for the single-item form frequently does not apply to
the collection form of the same resource. Verified live against a large public
REST API: `GET /repos/{repo}/issues` on a repository with issues disabled returns
**200 with an empty array**, while `GET /repos/{repo}/issues/1` returns **410
Gone**. Code written to "tolerate 410 when issues are disabled" therefore has a
branch that never fires, and the real path — an empty 200 — falls through to
whatever the generic handler does.

Probe the exact URL before writing a tolerated-status branch. If you keep a
defensive branch for a status you could not reproduce, label it as defensive and
name the path you *did* observe, so the next reader does not mistake it for
verified behaviour.

```python
# Observed: issues-disabled repos return 200 with []. The 410 branch is
# defensive — the item endpoint documents it, the list endpoint never sent it.
if resp.status_code == 410:
    return []
```

## The response *shape* is part of the contract

List endpoints commonly embed a **summary** object — a handful of identity fields —
rather than the full entity. A "we already have the data" fast path written
against the full entity is then always false:

```python
# This check is intended to skip a per-item fetch. Against summary objects that
# carry only {login, id, avatar_url}, it is False for every item — so the
# "fallback" enrichment fetch is the common path, and the loop is N+1.
if all(k in user for k in ("name", "company", "location", "followers")):
    return user
return fetch_user(user["login"])       # runs every time
```

Before optimizing around a response, print one real element and compare its keys
to what your code reads. The same probe settles range and boundary assumptions
that otherwise get "handled" defensively forever: if a per-year query provably
returns exactly that year's days, the dedup pass guarding against adjacent-year
leakage is dead code, and saying so in the PR is more valuable than the code.

## A fake proves your code calls the fake

Fakes are written by the same person as the code, from the same beliefs, so they
agree with each other by construction. Stand the real thing up **once** and re-run
the same assertions against it — a container is a minute, and it is the only thing
that validates the semantics the fake asserts: TTL and expiry sentinels, whether a
client factory is awaitable, key eviction, ordering, which exception type a
failure raises.

Simulate the outage deterministically instead of mocking the error, so the code
takes the same path production would:

```python
# A dead port is a real, instant, deterministic connection failure.
client = redis.asyncio.from_url("redis://localhost:1")
```

The same reasoning applies to documents you parse. A hand-written fixture encodes
your reading of the markup; the live page may render the same tokens across
indented lines, so a regex requiring single spaces matches every fixture and never
matches production. Capture one real sample, commit it, and point the parser's
test at it. Prefer a machine-readable attribute (`data-date="2024-01-01"`) over a
human-readable string when the source offers both — it survives markup and locale
changes that a prose regex does not.

## Dry-runs skip the step that fails

Resolve-only and plan-only modes are not verification of anything the *real* run
does after resolution. A dependency resolver's `--dry-run` reports success for a
requirement whose presence makes the actual build hard-fail, because the dry run
never builds. A build script's `--check` may never invoke the platform-specific
tool that breaks.

Run the real operation once, on the platform that matters:

```bash
uv pip install --dry-run .    # resolves; does NOT build → misses build-time errors
uv build                      # actually builds → catches them
```

More generally: if a mode exists specifically to be cheap, ask which step it
bought that discount by skipping, and whether your bug lives there.

## Some verified behaviour is not yours to fix

A probe sometimes proves the upstream system is simply wrong, or surprising, for
your use case. Resist reaching for a configuration knob to make the number look
right — if the underlying model or endpoint produces that output across parameter
settings, tuning a parameter buries the finding instead of recording it. Write
down what was observed, at which version, with the command, and choose a different
approach.

Record findings with three things or they will not survive: **the command**, **the
observed output**, and **the date**. External behaviour changes; an undated claim
cannot be re-checked.

## Checklist

```
Before shipping code that depends on an external system:
- [ ] The exact call/endpoint/version was probed, not a similar one
- [ ] Outbound request parameters inspected — names match what the service documents
- [ ] Selectors passed by keyword, never positionally
- [ ] Collection and item forms probed separately for status-code branches
- [ ] One real response element printed and compared against the fields the code reads
- [ ] Fakes validated against the real service at least once
- [ ] Failure paths exercised against a real failure (dead port, revoked token), not a mock
- [ ] Verified with the real build/install, not a dry-run
- [ ] Every tolerated-status or defensive branch is either reproduced or labelled defensive
- [ ] Findings recorded with command, output, and date
```

## Note for this repository (ffmpeg-skill)

`ffmpeg`/`ffprobe` are exactly the "third-party system" this skill is about —
their real behavior across versions and flags is the whole reason `doctor`
exists, and this session repeatedly needed to probe ffmpeg directly rather
than reason about it from documentation. The clearest example: `cut.py`'s
copy-mode `-ss` (before `-i`) seeks to the nearest preceding keyframe, and it
was tempting to assume the output duration would still equal the requested
`-t` regardless of where the seek landed. Running the actual command against
a real fixture (`--start 1.13 --end 5.71 --tolerance 2.0`) showed a real
1.24s divergence between `requested_duration` and `output_duration` — the
kind of finding this skill says to record with the command, the output, and
the date, which is exactly how `test_cut_copy_keyframe_snap_reports_a_real_nonzero_delta`
in `tests/test_all.py` was derived, rather than calculated from first principles.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
