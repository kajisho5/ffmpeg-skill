---
name: probing-edge-values
description: Find the option values an ffmpeg-skill tool accepts without anyone having decided what they mean — zero, a negative number, a value far past any real frame or clip — by running tests/edge_values.py over every numeric option in the contract, then reading each call that ran or hung against the option's help, and checking the few properties a tool should keep (doing it twice changes nothing more, an inverse returns the source's shape, the output is what probe.py says). Use when looking for defects nobody has reported, before a tool moves from beta to stable, after adding a numeric option, or when a report says a tool "hung", "wrote a strange file" or "accepted nonsense".
---

# Probing Edge Values

The tests give each option the values its author had in mind. Most defects nobody has reported
sit just outside them: a 0 that one option reads as "off" and another as "no limit", a negative
length, a count of a billion. The first round (2026-11-20) made 558 such calls. The tools refused
344. One hung (`cropdetect.py --samples 1000000000`), and of the 213 that ran in a dry run, a
second, real run showed `graphics.py --from 1000000000` hanging too, and `caption.py --size -1`
and `overlay.py --font-size 1000000000` writing a file.

`.claude/skills/first-try-probe/SKILL.md` asks whether an agent can find the right option. This
asks what the tool does once it has one and the value is wrong.

## The loop

1. **Run it.** `python3 tests/edge_values.py` gives every integer and number option of every
   tool in `tests/sweep.py`'s table the values 0, -1 and 1000000000, one at a time, on the tool's
   minimal call, with `--dry-run`. It prints the calls that ran and the ones that hung; `--json`
   gives all of them with the option's help and the tool's last line. A refusal is the good
   answer.

2. **Drop what is decided.** Most rows that ran are fine, and you can tell from the help: 0 is
   the documented default (`--crop-x=0` is the left edge), -1 is inside the range (`--exposure`
   is -3..3), the option does nothing without another flag (`--lut-strength` without `--lut`).
   Before calling anything else a defect, read `docs/design-decisions.md`: a value that looks
   wrong can be a decision with a test.

3. **Run what is left for real**, without `--dry-run`, on a short clip, under `timeout 40`. A dry
   run does not reach the checks ffmpeg makes. Sort the result:

   | What happened | Class | What it needs |
   |---|---|---|
   | no answer in 40 s | unbounded | a refusal with the largest value that makes sense |
   | a file was written and the value is outside the help's range | numeric | a refusal that names the range |
   | ffmpeg failed with its own message (out of memory, out of range) | a refusal without a way out | the tool's own refusal, before ffmpeg runs |
   | the tool refused and named the range | (fine) | nothing |
   | 0 or a negative ran and the help does not say what it means | claim | the help says it, or the value is refused |

4. **Check the few properties that cost nothing to check.** No library is needed; each is two or
   three calls and `probe.py`:
   - *Again changes nothing more.* `loudness.py` on its own output, `fit.py` to the size it
     already has, `export.py --preset copy` twice: the second result has the first's facts.
   - *An inverse returns the shape.* `reverse.py` twice, `straighten.py` by +N then -N,
     `speedramp.py` by 2 then 0.5: duration, frame count and stream layout come back.
   - *The result is what the tool said.* `probe.py` on the output agrees with the result
     document's duration, size and streams.
   - *One more input changes one thing.* `join.py` of N+1 clips is longer than of N by the last
     clip (less the transition), and nothing else differs.
   A property that fails is a finding with its reproduction already written.

5. **Sweep before fixing.** A value that hangs one tool usually hangs the others that take a
   count or a length. Name the class without the tool, run `tests/sweep.py` and the checks in
   `.claude/skills/sibling-sweep/SKILL.md`, and fix the shared step or file the siblings in one
   issue.

6. **Fix with a refusal, and count the lines.** Shipped code may not grow
   (`.github/code-budget.json`), so prefer one bound in a shared place (`finite_float` in
   `runner.py` is the model: one registered type covers every tool) over a check per tool. Since
   #645 a range is one of them: `apply_common` refuses a number outside the `a..b` its option's
   help states, a negative the help does not name, and anything past a million. So most findings
   are fixed by writing the range in the help, with no new check. Each
   fix adds a line to `docs/defect-ledger.jsonl` and a test that gives the edge value and reads
   the refusal.

## What a round should not do

- Do not report a row because it ran. 213 ran in the first round; a handful were defects.
- Do not add a bound the help does not state. Decide the range, write it in the help, then
  refuse outside it, in that order.
- Do not run the real calls without a timeout, or on a long clip: a value that is taken can fill
  the disk before it fails.
- Do not widen the edge values to floats, strings and paths in the same round. Path and name
  handling has its own audit (#558) and its own checks in `code-review`.

## Reference

- `tests/edge_values.py`: the runner (`--only`, `--json`, `--clip`). It reads the options from
  `scripts/_contract.py --json --static` and the minimal calls from `tests/sweep.py`.
- `docs/defect-ledger.jsonl`: classes `unbounded`, `numeric`, `claim`.
- The method follows two published skills, Trail of Bits' `sharp-edges` (probe what zero, empty
  and negative mean; an easy wrong call is the design's fault) and `property-based-testing` (the
  properties in step 4), both CC BY-SA 4.0 at github.com/trailofbits/skills. No text is taken from
  them, and no dependency: this repository's tests use the standard library only.
