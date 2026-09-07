---
name: shipping-build-artifacts
description: Make the build step a real gate on what you actually distribute — build scripts that warn and exit 0 on a missing input, size checks with only an upper bound, hand-maintained file lists that drift from the entrypoints they must cover, committed bundles that go stale when only the source changes, GNU-only shell in release scripts that aborts on the other OS, and verification that runs against the source tree instead of the artifact. Use when writing or reviewing a build/package script, a `dist/` copy step, a release workflow that uploads a zip or installer, or a committed compiled asset.
---

# Shipping Build Artifacts

Lint, type-check, and tests run against the source tree. What users install is a
*different* set of bytes — assembled by a script that most gates never look at,
then uploaded by a workflow that trusts whatever the script left behind. Every
failure below ships a broken or stale artifact under fully green CI.

## A script that warns and exits 0 is not a gate

The shape is universal: a declared list of inputs, a copy loop, a friendly
warning when one is missing.

```js
for (const f of DIST_FILES) {
  if (!fs.existsSync(f)) {
    console.warn(`Warning: ${f} not found, skipping`);   // build "succeeds"
    continue;
  }
  fs.copyFileSync(f, path.join("dist", f));
}
```

Move one required file aside and the script prints a line nobody reads, exits 0,
and produces a `dist/` without it. Nothing downstream notices: the test job ran
against the source tree, and the release job zips `dist/` and attaches it to a
public release. The artifact is wholly non-functional — the entrypoint imports a
file that isn't there — and the failure is discovered by users.

```js
const missing = DIST_FILES.filter((f) => !fs.existsSync(f));
if (missing.length) {
  console.error(`Missing build inputs: ${missing.join(", ")}`);
  process.exit(1);
}
```

The rule: inside a build script, `warn` may only describe something the artifact
survives without. If you cannot say what still works when that file is absent, it
is an error and the process must exit non-zero.

## Bound the artifact size on *both* sides

A packaging check with only a ceiling — "fail if the zip exceeds 500 KB" — is a
cost guard, not a correctness one. A build that silently dropped half its files
is *smaller*, so it passes the only check that exists.

```js
assert(bytes < 500 * 1024, "package too large");
assert(bytes > 20 * 1024, "package suspiciously small — inputs likely missing");
assert(entries.length === DIST_FILES.length, "package entry count mismatch");
```

Better still, assert on contents rather than a proxy: list the archive's entries
and compare against the set the entrypoints require.

## Derive the file list, or check it against the entrypoints

`DIST_FILES` — like a build backend's `only-include`, or a hand-written
`package_data` — is a *second* copy of "what this app is made of." The first copy
is the manifest, the entry HTML, and the import graph. They drift in one
direction: someone adds `utils.js`, references it from the popup, and forgets the
copy list. The build stays green and the feature is dead in the packaged app.

Either derive the list (bundle from the real entrypoints), or add a check that
every path referenced by the manifest and by `<script src>` / `importScripts`
exists in `dist/` after the build. A hand-maintained allowlist with no such check
is a bug scheduled for a future commit.

The same rule covers any place dependency or asset metadata is restated by hand —
a standalone launcher script whose inline dependency header duplicates the
project manifest's `dependencies`, for instance. If duplication is unavoidable,
add a test that normalizes both lists and compares them, so drift fails in CI
instead of at a user's install.

## Committed build outputs go stale silently

When a compiled or minified bundle is committed and served directly, *the bundle
is the program* and its source is a comment until someone rebuilds. Editing only
the source ships nothing; the page keeps serving the previous bundle, and no test
or linter says a word.

- Rebuild in CI and `diff` against the committed output; fail on drift.
- Pin the builder to an exact version — the diff is only meaningful if the output
  is byte-deterministic.
- Confirm that determinism once across the environments people actually use
  (native toolchain vs. container image), so the check is runnable locally too.

```bash
npx -y esbuild@0.24.2 src/app.jsx --jsx=transform --minify --outfile=/tmp/app.js
diff /tmp/app.js web/app.js
```

Rebuild and commit the output in the **same commit** as the source change. A
"rebuild bundles" follow-up commit means every commit in between shipped code
that does not match its source.

## Release scripts run on an OS you didn't write them on

Build scripts are written on a developer machine and executed on the runner.
GNU-only tooling is the usual break, and `set -e` turns it into a total abort on
a line that merely reads a version number:

```bash
# Breaks under BSD grep (macOS): -P / lookbehind are GNU extensions.
VERSION=$(grep -Po '(?<=^version = ")[^"]+' pyproject.toml)
```

Read structured metadata with a parser instead of a regex, and prefer a runtime
you already depend on:

```bash
VERSION=$(python -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
VERSION=$(jq -r .version package.json)
```

Then pin it with a test: the version the build script extracts must equal the
version declared in the project manifest. Without that, the failure mode is a
release tagged `v1.4.0` whose artifact reports `1.3.2`, and nothing in the
pipeline disagrees.

## Verify the artifact, then publish — in that order, in that job

Attaching a file to a public release, pushing a tag, or uploading to a registry
are the least reversible steps in the project. The verification must sit between
the build and the upload, in the same job. A separate green "test" job proves
nothing about the artifact: it ran against the source tree.

Minimum ordering:

1. Build.
2. List every entry in the artifact and assert the entrypoints are present.
3. Install or load it **from a directory the source tree is not on the load path
   of**, and exercise one real symbol or command — not merely that a top-level
   name resolves.
4. Only then upload.

Step 3 is the one that gets skipped, and it is the only step that distinguishes
"the archive has files in it" from "the thing runs." Run it somewhere else on
disk, or it passes against the sources and proves nothing.

## Checklist

```
Build script:
- [ ] Missing declared input → non-zero exit, not a warning
- [ ] Size assertions have a floor as well as a ceiling
- [ ] File list is derived, or checked against manifest/entry-HTML references
- [ ] Duplicated dependency metadata has a drift test
- [ ] No GNU-only flags (grep -P, sed -i'' semantics) in scripts CI also runs
- [ ] Version extracted with a parser, and asserted equal to the declared version

Committed build outputs:
- [ ] CI rebuilds and diffs; drift fails
- [ ] Builder pinned to an exact version; output confirmed deterministic
- [ ] Output committed alongside the source change, not in a follow-up

Release:
- [ ] Artifact contents listed and asserted before upload
- [ ] Artifact installed/loaded from outside the repo and exercised
- [ ] Verification runs in the same job as the upload, before it
```

## Note for this repository (ffmpeg-skill)

`package.json`'s `"files"` list is the equivalent of `DIST_FILES` here — it must
list exactly what ships (`bin/`, `scripts/`, `mcp/`, `references/`, `SKILL.md`,
`README.md`, `LICENSE`), and `.claude/` (this file included) must NEVER appear
in it. `npm publish --dry-run` is the "list every entry and assert the
entrypoints are present" step (step 2 above) — run it before every publish, and
watch for stray `__pycache__`/`.pyc` files sneaking into the tarball from a
local test run (this actually happened once this session and was caught by
exactly this check). There is no separate "install from outside the repo and
exercise a symbol" step in this repo's release process today (`node
bin/install.js --dir /tmp/skills` from README's Development section is the
closest equivalent) — worth doing before a real publish, not just a dry-run.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
