# Contract evals

Can an agent understand ffmpeg-skill from `contract --json` alone, without reading
`SKILL.md`, the scripts or a shell command?

`questions.json` holds ten questions with the field of the contract that answers each
and the expected answer: picking the right tool id, naming a required capability,
deciding whether a visual check is needed, whether the input is preserved, whether
`--dry-run` is available, telling analysis / execution / verification apart, building an
argv from the input schema and mapping, and the stability of tool ids.

- `check.py` (deterministic, run in `release-check`): recomputes every expected answer
  from the live contract, so the questions can never drift from the ToolSpecs.
- Agent run: give a model the contract (`python3 scripts/_contract.py --json --static`)
  and `questions.json`, ask for `{"<id>": "<answer>"}`, and grade with
  `python3 evals/contract/check.py --grade answers.json`.

Results: `../results/contract-<date>.json`.
