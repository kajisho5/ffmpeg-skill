# Surfaces — everywhere a fact about this repo is stated

A change is shipped only when every surface that states the fact agrees. `feat`
PRs are held to the full list below; a `fix` is held to whatever surface its fact
appears on.

## The inventory

| surface | what it must say | checked by |
| --- | --- | --- |
| `scripts/*.py` + `scripts/_contract.py` | the behaviour and the tool/flag schema | the generator |
| `python3 scripts/_contract.py --json` | canonical tool names, flags, dry-run semantics, error kinds | `tests/test_contract.py` |
| `README.md` | tool table, contract table, gotchas | tested against the contract |
| `SKILL.md` | runtime guidance for the calling agent | tested against the contract; < 30,000 bytes |
| `references/scripts.md` | per-tool detail | docs consistency tests |
| `docs/contract.md` | the contract restated for humans | `tests/test_contract.py` |
| `CHANGELOG.md` | the entry for the change | `test_changelog_mentions_every_closed_issue_since_last_tag` |
| `demos/build.py` → `docs/demos.md` | a before/after demo per feature | a test asserts every `scripts/*.py` appears in some demo |
| `mcp/` | MCP tools derived from the contract | MCP derivation tests |
| `bin/install.js` `PAYLOAD`, `package.json` `files` | what ships in npm | `tests/release_check.sh` |

## Rules a review enforces

- **Never hand-duplicate a schema.** Extend the generator in `_contract.py`. A
  schema typed into a doc by hand is drift waiting to happen.
- **A `feat` adds a demo** to the table in `demos/build.py`, then regenerates the
  page with `python3 demos/build.py --docs`. A tool whose entire output is a
  table, JSON document or HTML file goes in `INSPECTION` in `demos/build.py`
  instead of a demo.
- **A `feat` PR** updates `README.md`, `SKILL.md`, `references/scripts.md`,
  `docs/contract.md` and `CHANGELOG.md`. A feature only `SKILL.md` knows about is
  half shipped — the README is read by people who never open `SKILL.md`.
- **`SKILL.md` under 30,000 bytes** is a test
  (`test_skill_md_stays_under_the_30kb_budget`). Adding a line means trimming one;
  the PR says which.
- **A release PR moves `docs/roadmap.md`'s "the released version today is …" line
  in the same PR as the version bump**, so the roadmap never describes a shipped
  version as planned.
- **Packaging exceptions:** `references/process-pitfalls.md` is a maintainer diary
  and is deliberately *not* in the npm package; `scripts.md`, `devices.md`,
  `ci-platform-pitfalls.md` and `docs/contract.md` are. Check `package.json`
  `files` and `bin/install.js` `PAYLOAD`, not this note.
- **Never quote the release bump's skip-CI marker in a PR body.** A squash merge
  copies it into the merge commit and skips every workflow
  (`references/process-pitfalls.md`).

## Drift check

To confirm a surface is generated rather than restated, change the value in
`_contract.py` and re-run the contract tests; a surface that does not follow is
hand-maintained and is itself a finding.

```bash
python3 scripts/_contract.py --json > /tmp/before.json
# make the change
python3 scripts/_contract.py --json > /tmp/after.json
diff /tmp/before.json /tmp/after.json
npm test
```

For a refactor that must be behaviour-free (the `_common`/`text.py` splits are the
precedent), dump `--json` and every script's `--help` before and after and diff
them empty.
