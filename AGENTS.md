# For agents working on this repository

- Runtime use of the skill is documented in `SKILL.md`; this file is for agents that review,
  audit or change the repository itself.
- **Before reporting a defect, read `docs/design-decisions.md`.** It lists behaviours that look
  like bugs but are decisions, each with its rationale and the test that pins it. Report one of
  them only if the rationale no longer holds, and say which sentence is wrong.
- Verify a finding against the tree at the commit you are reviewing, not against a summary: at
  least one earlier review reported committed media that is not in git and colour flags that were
  already validated.
- The contract (`python3 scripts/_contract.py --json`, `docs/contract.md`) is the authority on
  tool names, flags, dry-run semantics and error kinds; README and SKILL.md restate it and are
  tested against it.
- Development rules (scope, tests, PR expectations) are in `CONTRIBUTING.md`.
