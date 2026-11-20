---
name: probing-first-try-use
description: Find the places where an agent that has not read the docs gets an ffmpeg-skill tool wrong on the first try — having a fresh agent write calls blind from each tool's name and one line about it, running them with tests/first_try.py, reading the calls that ran as carefully as the ones that failed, teaching each miss through a help string or the shared hint, and recording it in docs/stumbles.jsonl so a test replays it. Use when asked how usable the tools are, before promoting a tool from beta to stable, after adding or renaming options, at the weekly measurement, or when a user reports that an agent "kept guessing the wrong flag".
---

# Probing First-Try Use

The tests call every tool the way its author spells it. An agent does not: it reads one line
about a tool and types what an experienced FFmpeg user would type. The first round of this probe
(2026-11-20) ran 126 such calls. 27 ran. One of those ran and was wrong: `freeze.py --time 3
--hold 1` was read as `--timeout 3`, froze the last frame and said nothing.

You cannot write the calls yourself. Once you have read `--help` you know the names, and a guess
that knows the answer measures nothing.

## The loop

1. **Make the brief.** `python3 tests/first_try.py --brief > tools.txt` prints each tool's name
   and the first sentence of its description. That file is all the blind agent may see.

2. **Have a fresh agent write the calls.** Start an agent with no context of this repository.
   Tell it, in these words or close to them: it must not open the source, `--help`, the README or
   any other file; it may read only `tools.txt`; for every tool it invents three realistic
   requests and writes the argument list it would type first, with `{clip}` where an input video
   goes, as a JSON array of `{"tool", "request", "argv"}`. Ask for honest guesses, not odd ones.
   Three per tool is enough to see the pattern; a different agent or model on the next round
   guesses differently, which is the point.

3. **Run them.** `python3 tests/first_try.py guesses.json` runs every call with `--dry-run` and
   prints the counts and the misses. `--json` gives every row with the tool's answer.

4. **Read the rows that ran first.** A wrong call that exits 0 is the worst outcome, and no count
   shows it. For each, read the dry run's plan against the request: did the flag mean what the
   agent meant? Look for an option name argparse completed to another option, a value taken in
   another unit (`--scale 0.15` where the tool wants pixels), and a default that did the work
   instead of the flag.

5. **Sort the misses.**

   | Row | What it means | What to do |
   |---|---|---|
   | `silent` | an unknown flag and no pointer | if the tool has an option for it, put the word the agent used into that option's help; `runner._teach` finds it |
   | `elsewhere` | only other tools were named | the same, unless the tool truly has no such option |
   | `taught` | an own option was named | check it is the right one; a wrong pointer is worse than none |
   | `refused` | a missing file, a value out of range | usually the probe's own doing (the clip is 8 s long); skip unless the message has no way out |

   A flag for something the tool does not do (`reverse.py --start`) has no pointer to give. Leave
   it; do not add the feature here.

6. **Teach without adding a name.** Under the feature freeze nothing may be added to the
   contract, and shipped code may not grow (`.github/code-budget.json`). A help string costs
   neither: write the option's help so that it uses the word people reach for. Change
   `runner._teach` only when a whole class of guess is missed, and remove what a loose rule gets
   wrong: a spelling match that suggested `--duration` for `--ratio` was worse than silence.

7. **Record each one.** Add a line to `docs/stumbles.jsonl`: `seen`, `tool`, `argv`, `class`,
   `got`, `right`, `must_say`, `status`. `taught` lines are replayed by `StumbleLedgerTests`,
   which reads only what follows `error:` (the usage block lists every option, so a name found
   there proves nothing). A stumble that cannot be answered yet (a result that is wrong and says
   nothing) goes in as `open` with an empty `must_say`.

8. **Run the probe again and report both counts**: calls that ran, and unknown-flag calls that
   were pointed at an own option, before and after.

## What a round should not do

- Do not count a round as progress because `ran` went up. A help string that makes a wrong call
  succeed is a regression.
- Do not rename an option to match a guess. The decided names are in
  `docs/design-decisions.md` ("one name per meaning"); a rename waits for the freeze to lift and
  keeps the old name as a deprecated alias.
- Do not feed the guesses back to the agent that wrote them, and do not reuse one round's guesses
  as the next round's measurement: they are in the ledger now, and the tests replay them.
- Do not paste the blind agent's file into a PR without reading every `argv`: it is model output,
  and it becomes a test.

## Reference

- `tests/first_try.py`: the runner (`--brief`, `--json`, `--clip`).
- `docs/stumbles.jsonl`: the ledger. `tests/test_contract.py::StumbleLedgerTests`: the replay.
- `scripts/_common/runner.py`: `_teach` (the hint) and `apply_common` (a shortened shared option
  is refused).
- `.claude/skills/sibling-sweep/SKILL.md`: when a row turns out to be a defect, sweep it before
  fixing it.
