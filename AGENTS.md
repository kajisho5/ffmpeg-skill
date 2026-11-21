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
- **A class that keeps coming back gets a guard, not another fix.** `docs/defect-guards.json`
  lists every class of `docs/defect-ledger.jsonl` with three or more entries and the test in
  `tests/test_guards.py` that runs every tool and fails wherever the class shows. A fix of a class
  whose guard is still `pending` does not pass `revert_proof.py`: write the guard in the same PR
  (or before it), and where the class can be seen while a tool runs, detect it in the common
  result writer and make the tool declare what it did (`runner.declare_time_map` is the pattern).
  The ledger line's `mechanism` names the guard, not only the tool that was fixed.
- **Before a push, ask the reviewer's questions yourself.**
  `.claude/skills/code-review/references/reviewer-findings.md` groups the 353 findings an outside
  reviewer made on earlier PRs into twenty questions (path guards against every input and output,
  a failed measurement reported as not measured, a claim as narrow as the code, the right stream,
  ...). A finding that fits none of them adds a question in the PR that answers it.
- **A defect changes a mechanism, not only a line (#632).** Every fix adds one line to
  `docs/defect-ledger.jsonl`: the defect's class, why the checks that exist let it through, and
  what was changed so the class cannot recur (a shared step, a type, generated text, a test that
  runs over every tool). Patching the reported place alone is allowed once per class, with the
  reason; the second defect of that class means the mechanism is wrong and is what gets rebuilt.
  `.github/scripts/revert_proof.py` and `test_every_defect_names_its_class_...` enforce it.
- **How usable the tools are is measured, not assumed.** `.claude/skills/first-try-probe/SKILL.md`
  has a fresh agent write calls blind from each tool's name, runs them (`tests/first_try.py`) and
  turns each miss into a line of `docs/stumbles.jsonl` that the tests replay. Run it after adding
  or renaming an option and before a tool moves from beta to stable.
- **Defects nobody has reported are looked for.** `.claude/skills/edge-probe/SKILL.md` gives every
  numeric option a zero, a negative and a huge value (`tests/edge_values.py`) and checks the few
  properties a tool should keep. Run it before a tool moves from beta to stable and after adding a
  numeric option.
