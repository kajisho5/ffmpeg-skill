---
name: concurrent-branches
description: Resolve conflicts and merges when several branches are open against one repo at the same time — the hotspot files every change must touch (registry manifests, a single version field, shared tool config, one aggregated test module, tracked build output), union-vs-recompute-vs-rebuild as three different correct resolutions, generated artifacts that must never be merged, non-deterministic serialization that makes every branch conflict, renumbered identifiers that git cannot show you, and why a clean auto-merge is not a passing test. Use when rebasing or merging a long-lived branch, resolving conflict markers, reviewing a merge commit, deciding what a repo should commit vs generate, or setting up a repo that will take parallel contributions.
---

# Merging Concurrent Branches

When several branches are open against the same repo at once, the conflicts do
not land in the code you were thinking about. They land in a small, predictable
set of **hotspot** files that nearly every change has to touch — a registry
manifest, a version field, shared tool config, one aggregated test module, a
tracked build output.

Each hotspot has exactly one correct resolution, and they are not the same rule.
"Take ours" / "take theirs" is right for almost none of them. Worse, getting one
wrong is silent: the dropped entry, the collided version, the stale bundle all
merge green and are found later by someone who cannot reproduce them.

## Find the hotspots before you need to resolve them

Files touched by nearly every commit are the files your branch will conflict on.

```bash
# the 15 files most commits touch — your hotspot list
git log --format= --name-only -n 200 | sort | uniq -c | sort -rn | head -15
```

Write the resolution rule for each one into the contributing docs. Under
conflict pressure, with a stale branch and a red CI run, nobody re-derives
"the version field is recomputed, not merged" correctly.

## Additive registries: union both sides, never choose one

A manifest that lists every component — plugin entries, module paths, exported
names, a feature list. Two branches each append an entry, and the conflict spans
both additions:

```jsonc
<<<<<<< HEAD
    "./components/exporter",
    "./components/importer"        // theirs, already merged to main
=======
    "./components/exporter",
    "./components/validator"       // yours
>>>>>>> feature/validator
```

Both sides are correct and neither is a substitute for the other. Resolve by
keeping **every** entry from both sides. Taking a side deletes a component that
is still fully present in the tree — the code compiles, the tests pass, and the
component is simply never registered or installed.

Nothing catches that unless you check the registry against the filesystem:

```bash
# every registered path exists
jq -r '.plugins[].components[]' manifest.json | while read -r p; do
  [ -e "${p#./}" ] || echo "registered but missing: $p"
done
# every component on disk is registered
for d in components/*/; do
  grep -q "\"./${d%/}\"" manifest.json || echo "present but unregistered: $d"
done
```

Run it as a repo test, not as a merge-day ritual. It is the only thing standing
between a mis-resolved conflict and a component that quietly does not ship.

## Single-value counters: recompute from the integration branch

A version field, a sequence number, a "latest migration" pointer. Both branches
bumped `2.17.0` to `2.18.0`; both are wrong now, because a third branch already
merged and main is at `2.18.0` too.

Union is meaningless here and picking a side reintroduces a collision. The rule
is **recompute from the current integration branch**, not from either side of
the conflict — every change that merged since you branched consumed one
increment:

```bash
git fetch origin main
git show origin/main:manifest.json | jq -r '.metadata.version'   # -> 2.18.0
# your branch takes 2.19.0, regardless of what your branch said before
```

Do this as the *last* step before pushing, not during the merge. If another
branch lands while you resolve, you redo only one line.

## Generated artifacts: rebuild, never merge

A committed minified bundle, a built PDF, a compiled schema, a checked-in
snapshot. Git will happily produce a merge for the text ones and force a
binary choice for the rest — and **every** such result is wrong, because a
derived file's only correct content is whatever the merged sources generate.

Resolve the sources, then regenerate:

```bash
git checkout --merge -- src/ ui/app.jsx   # resolve the real inputs first
make build                                 # regenerate the artifact
git add dist/bundle.js docs/handbook.pdf
```

Two things make this reviewable rather than a leap of faith:

- **Pin the generator version.** If the bundler or typesetter is pinned, its
  output is byte-identical anywhere, and a reviewer can regenerate and `diff` to
  confirm the artifact matches the source. Unpinned, the artifact diff is a mix
  of your change and a tool upgrade, and nobody can tell them apart.
- **Verify only the expected regions moved.** A rebuilt document reflows: a
  one-paragraph edit typically spreads across two or three consecutive pages.
  Raster-diff or `diff` the rebuilt artifact against one built from the base
  commit in the same environment, and say in the PR which regions changed and
  why. Anything else that moved is your merge, not your edit.

## Non-deterministic serialization turns every branch into a conflict

If a tracked file is written by iterating a map, set, or dict whose order is not
stable, the whole file is rewritten on every run. Then every branch conflicts on
every line, diffs are unreviewable, and real conflicts hide inside the churn.

Sort before writing:

```python
# BAD — map iteration order; the file is rewritten differently every time
records = [to_record(k, v) for k, v in index.items()]

# GOOD — a stable key. ISO-8601 dates sort chronologically as plain strings,
# so no date parsing is needed to get a deterministic, reviewable file.
records = sorted((to_record(k, v) for k, v in index.items()), key=lambda r: r["date"])
```

This applies to *any* code path that rebuilds a committed file from an unordered
collection, including the ones added later. Once one path forgets, the file is
churny again.

## Shared tool config: take the base file, re-apply your delta

`pyproject.toml`, `package.json`, lint config, a CI workflow — files where your
branch added three lines and four other branches added their own. Reconciling
hunks by hand is where dev-dependency pins and tool sections get silently
dropped.

Take the integration branch's copy wholesale — it already carries everything
that landed while you were away — then re-add only the lines your branch
introduced:

```bash
git checkout origin/main -- pyproject.toml
# re-add just your delta, then confirm nothing else moved
git diff origin/main -- pyproject.toml
```

That last `git diff` should show your addition and nothing else. If it shows a
pin reverting or a tool section disappearing, you took a side by accident.

## Aggregated test modules: keep both suites, then check for shadowing

Two branches append cases to the same test file. Union them — but a union can
produce two tests with the same name, and in Python and JavaScript the later
definition simply replaces the earlier one. The file looks longer, the suite
count looks plausible, and one branch's case never runs.

```bash
grep -oE '^\s*(def test_[A-Za-z0-9_]+|it\(.[^,]*|test\(.[^,]*)' tests/test_thing.py \
  | sort | uniq -d
```

The same shape bites production code: two branches independently add the same
module-level helper, the resolution keeps both, and the second shadows the
first.

## Append; never renumber a shared identifier

Repos that carry stable identifiers cited from elsewhere — claim IDs in a source
ledger, migration numbers, fixture keys, snapshot names — break in a way conflict
markers cannot show you. Renumbering `C7`-`C12` to make room is a clean,
conflict-free edit that invalidates every citation of those IDs in files your
merge never touched.

Add new identifiers by continuing the numbering past the highest one that exists
anywhere, and never reuse or renumber one. If two branches both claimed `C17`,
renumber **yours** and fix your own references; do not renumber the side that
already merged.

## A clean auto-merge is not verification

Two branches editing far-apart regions of one large file merge cleanly and can
still be semantically wrong: one side's change depends on a helper the other
removed, or both added equivalent logic under different names, or one side's
edit now sits inside a branch the other made unreachable.

After any non-trivial merge, confirm both sides survived — grep the merged tree
for a distinctive string from each:

```bash
git grep -n "computes the retry budget"     # a phrase only their change added
git grep -n "REDACTION_PLACEHOLDER"         # a symbol only yours added
```

Present and consistent, not just present. Then read the two regions together.

## Match the repo's integration style, and re-run the real gate

```bash
git log --graph --oneline -20    # merge commits, or a linear rebased history?
```

Follow whichever the history already uses. Then run the repo's actual CI
commands locally before pushing: **a resolved merge is code that has never
existed anywhere before**, and neither branch's CI run covered it. A green check
on your branch and a green check on main say nothing about their union. See
**reproducing-ci-locally** for deriving the commands the runner actually uses.

## Checklist

- [ ] Hotspot files identified from `git log --name-only` before branching
- [ ] Registry/manifest conflicts resolved by union; every entry from both sides kept
- [ ] Registry checked against the filesystem in both directions, in CI
- [ ] Version/counter fields recomputed from `origin/main`, not taken from either side
- [ ] Generated artifacts rebuilt from merged sources, never text- or binary-merged
- [ ] Generator version pinned so a reviewer can regenerate and diff
- [ ] Files serialized from maps/sets sorted by a stable key
- [ ] Shared tool config taken from base, delta re-applied, `git diff` shows only your lines
- [ ] Merged test modules checked for duplicate test names
- [ ] New shared identifiers appended; none reused or renumbered
- [ ] A distinctive string from each side found in the merged tree
- [ ] Repo's real CI gate run locally on the merged result before pushing

## Note for this repository (ffmpeg-skill)

This is exactly the pattern seen across the PR #28-#37 merge cascade for the
0.10.0 release: `CHANGELOG.md` was the hotspot file nearly every PR touched,
and the correct resolution every time was "union both sides, never choose
one" (keep every bullet, verify no leftover conflict markers). `package.json`'s
`version` field is the single-value-counter case: it should be recomputed
once, after all merges land, not carried through each individual merge.

## Learn More

- **reproducing-ci-locally** (also added to this repo's `.claude/skills/`) —
  running the runner's real commands on the merged tree

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
