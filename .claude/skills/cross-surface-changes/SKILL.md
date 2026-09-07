---
name: shipping-across-surfaces
description: Land a change everywhere the same fact is stated — enumerating the full surface inventory (landing copy, docs, machine-readable summaries, changelog badges repeated across every page, sitemap, README, descriptions embedded in code, and untyped frontend consumers of typed responses), generating a surface instead of restating it, drift tests where you cannot generate, never hand-maintaining a copy of a surface another codebase owns, shipping a paired PR when you change a format a different codebase decodes, and keeping overloaded product words apart. Use when adding or renaming a user-facing feature, editing product/marketing copy or docs, renaming a serialized response field, changing a serialization or share-link format, wiring one repo's output into another's checks, or reviewing a PR that touched only one place a fact appears.
---

# Shipping Across Surfaces

Most product facts are stated more than once. The feature exists in code, is
described on a landing page, summarized for agents, listed in a changelog,
repeated in a nav badge, restated in a README, and embedded again in the
description string of every tool or endpoint that exposes it. Each copy drifts
independently, and none of them are covered by tests.

The failure is never loud. Nothing goes red; the product simply describes itself
inaccurately in the four places you didn't edit, and the one place a reader
happened to look is the stale one.

## Enumerate the surface inventory once, in the repo

"I'll remember the other places" does not survive the second feature. Write the
list down — in `CONTRIBUTING.md`, a PR template, or the skill/guide the project
already keeps — and treat it as the definition of done for a user-facing change.
A realistic inventory for a product with a public site:

- Landing page: hero, section ledes, the feature cards, the free/paid list
- `<meta>` / OG / Twitter tags, and the structured data (`SoftwareApplication`
  description, `FAQPage` entries) — search engines read the copy you forgot
- Docs page, and any machine-readable summary for agents (`llms.txt`)
- Changelog entry **and** the version badge repeated in the nav of every page
- Sitemap, and the footer product column present on every page
- README, comparison pages, onboarding/skill files
- **The descriptions embedded in code** — every tool, command, or endpoint
  description, not just the primary one

That last bullet is the one that gets missed. A rename lands in the tool it was
named after and stays wrong in the three sibling tools that mention it in
passing. Grep for the old string across the whole tree, not just the docs
directory, before calling the change done.

All of these ship in the **same PR**. A follow-up "update docs" commit means the
interval between them shipped a product that contradicted itself.

## Prefer a generated surface to a restated one

The surfaces above are drudgery precisely because they're copies. Delete the copy
where you can:

- An API reference rendered from the live schema self-syncs and needs no hand
  edit when the API changes. That page is *free* forever.
- A version badge repeated across forty pages belongs in a template/partial or a
  build-time injection, not in forty files.
- A "supported features" list is better derived from the registry it describes
  than typed a second time.

Where generation isn't practical, make drift fail a test rather than a review.

```python
def test_readme_documents_every_registered_tool():
    registered = {t.name for t in get_registered_tools()}
    documented = parse_tool_names(README.read_text())
    assert documented == registered   # fails on add, remove, and rename
```

Compare against the *live* registry, not a second hand-written list — a test that
compares two hand-maintained lists only proves you updated both copies of the
same mistake. The same rule covers duplicated dependency metadata and committed
build outputs; see **build-artifacts** (also in this repo's `.claude/skills/`).

## A response model is only half the contract

A typed backend and an untyped frontend can disagree without either side
failing. Renaming a Pydantic field updates serialization and keeps every Python
test green, while a Jinja template's inline JavaScript still reads the old name
inside a template literal. The browser then renders `undefined`: valid
JavaScript, no exception, no backend failure.

Treat every serialized field rename as a producer-and-consumer change:

```bash
# Search the whole tree, not just Python call sites. Templates and committed
# JavaScript bundles are consumers too.
rg 'old_field|new_field' .
```

Then pin the boundary with a test that uses the real serialized response and the
real consumer. A browser test is ideal when available. A cheaper contract test
can still make the hidden dependency explicit:

```python
def test_dashboard_consumes_the_audit_response_contract():
    payload = AuditResponse.example().model_dump()
    template = Path("templates/dashboard.html").read_text()

    for field in ("summary", "recommendations"):
        assert field in payload
        assert f"result.{field}" in template
```

This test is deliberately narrow: it does not claim to execute JavaScript. It
makes a field rename fail in the same change that alters the response model,
instead of relying on someone to notice `undefined` in a rendered page. Prefer
generating a typed client or shared schema when the frontend architecture allows
it; otherwise keep this boundary test beside the producer's contract tests.

## Don't hand-maintain a copy of a surface you don't own

The tempting shortcut when validating against another system — another service's
tool names, another team's enum, a partner API's status codes — is to paste the
current values into a constant and check against it.

```python
# Anti-pattern: a private snapshot of someone else's public surface.
KNOWN_TOOLS = {"search", "create", "archive"}   # correct until they ship
```

It is stale the moment the owner ships, and the staleness surfaces as *your*
validator rejecting valid input. Worse, nothing in your repo can detect it: you
have no reference to compare against.

Truth flows **outward from whoever owns it**. The owning codebase publishes a
generated, versioned artifact — a committed `tools.json` carrying the source
version and commit — and the consumer reads that file. Ask "who owns this fact,
and which direction is it moving?" before writing the check. A design where your
repo reaches into theirs to scrape the truth is the wrong direction and will
break on access, auth, or refactor; a design where they publish and you consume
is stable.

Checks that need **no** external truth are fine to land standalone: a denylist of
known-bad legacy patterns, a structural schema check, a "this field is required"
assertion. Those describe your own expectations, not their surface.

## A format change needs its consumer's PR in the same breath

When one codebase encodes and a different one decodes — a share-link payload, an
export file, a cache key, a webhook body — the format is a contract between two
repos, and half a contract is an outage.

- Open the paired PR in the consumer repo at the same time, proactively. Don't
  land the producer side and file an issue for the other end.
- Version the payload so an old decoder can *detect* a new format instead of
  misparsing it into plausible garbage.
- Where the two are on different release cadences (an app store review vs. a
  static site deploy), ship the decoder first and the encoder second.

If the counterpart repo is private and this one is public, refer to it by what it
does — "the site that serves the share links" — never by slug, path, or URL.
Naming the public product a piece of content is *about* is expected; leaking the
name of a private repository is not. That distinction is worth a CI check in any
public repo that has a private counterpart.

## Keep overloaded words apart

Products accumulate words that name two different things. One system may have a
per-feed, unsigned POST configured on a resource *and* an account-wide, signed,
retried event stream with a delivery log — and call both a "webhook." Once copy
uses the bare word, every sentence about either becomes ambiguous and support
questions stop being answerable.

Write the two definitions down with a canonical label for each, put them
somewhere new copy is written against, and never let the bare overloaded word
stand alone in user-facing text. This applies to nav labels and tool descriptions
as much as to prose — the label is the surface most people read.

## Make factual claims traceable

Copy that asserts things about behavior ("processes N per second", "caps
withdrawals per settlement") drifts from the code faster than any other surface,
because nothing recompiles when it becomes false.

Keep a claim ledger with stable identifiers, cite the identifier inline from the
copy, and record provenance in the ledger rather than repeating it in the prose.
Two rules make it survive:

- **Append, never renumber.** A new claim continues the numbering; reusing or
  renumbering an identifier silently repoints every existing citation.
- **When two ledgers cover the same fact, cite the more rigorously derived one** —
  a measured benchmark row over a read-the-source row — so the weaker claim can't
  outlive its replacement.

A repo-level check that every factual sentence carries a citation turns this from
a habit into a gate.

## Checklist

```
Before calling a user-facing change done:
- [ ] Surface inventory exists in the repo and was walked, not recalled
- [ ] Old strings grepped for across the whole tree, including code descriptions
- [ ] Serialized field renames grepped through templates and frontend code
- [ ] Untyped response consumers covered by a boundary contract test
- [ ] Every sibling tool/endpoint description mentioning the feature updated
- [ ] Changelog entry added and the repeated version badge bumped everywhere
- [ ] All surfaces in ONE PR, not a docs follow-up

Reducing the surface count:
- [ ] Anything renderable from a live schema/registry is generated, not typed
- [ ] Repeated fragments live in a template/partial, not N files
- [ ] Unavoidable duplication has a drift test against the live source

Across repo boundaries:
- [ ] No hand-maintained snapshot of a surface another codebase owns
- [ ] Truth flows outward from the owner as a versioned, generated artifact
- [ ] Format changes ship a paired consumer PR; payload is versioned
- [ ] Decoder deploys before encoder when cadences differ
- [ ] Public content names no private repo slug, path, or URL

Wording:
- [ ] Overloaded product terms have written definitions and canonical labels
- [ ] Factual claims cite a stable ledger identifier; identifiers are append-only
```

## Note for this repository (ffmpeg-skill)

The "22 tools" count (and the per-category tool tables) in README.md and
SKILL.md is exactly this kind of restated surface — it drifted to "21" more
than once this session when a tool was added and only the code was updated.
`tests/test_contract.py`'s `test_mcp_tools_match_contract` and
`test_mcp_schema_drift_follows_the_scripts` are the "generated surface" /
"drift test" answer for the MCP tool list specifically (MCP's `tools/list` is
derived from the contract, never hand-written) — the same rigor doesn't yet
exist for the README/SKILL.md tool-count prose, which is still grepped and
hand-edited. `docs/contract.md`'s `capability_map`/`provides` sections are the
other real example: they explicitly promise "says nothing tools[] doesn't
already say," i.e. they are declared to be a re-index, not a second source of
truth — exactly the "truth flows outward from whoever owns it" principle.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
