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
- **A reported defect is swept before it is fixed.** One report names one tool and one input; the
  same thing usually happens elsewhere, and the reporter found it because nobody here looked. Name
  the defect's class without naming the tool, run `python3 tests/sweep.py INPUT --baseline PLAIN`
  and the path-parity checks in `.claude/skills/sibling-sweep/SKILL.md`, then fix the shared cause
  or file the siblings in one issue. The PR body says what was swept and what it showed.
- **Before a push, ask the reviewer's questions yourself.**
  `.claude/skills/code-review/references/reviewer-findings.md` groups the 353 findings an outside
  reviewer made on earlier PRs into twenty questions (path guards against every input and output,
  a failed measurement reported as not measured, a claim as narrow as the code, the right stream,
  ...). A finding that fits none of them adds a question in the PR that answers it.
