---
name: sweeping-defect-siblings
description: Turn one reported defect in ffmpeg-skill into the full list of places the same thing happens — naming the defect's class (an input property, a shared step, a convention that differs between two code paths, an FFmpeg-version behaviour), sweeping every tool with tests/sweep.py and a path-parity probe, separating decided refusals from real siblings, and landing the fix with one regression test per class rather than per report. Use whenever an issue or PR comment reports a bug in this repository, before writing the fix, and again when triaging an external review or audit.
---

# Sweeping Defect Siblings

A report from outside names one tool and one input. It is almost never the only
place the defect lives, and the reporter found it because nobody inside thought
to look. #437 named `insert.py` and an odd-sized JPEG; the same odd frame also
broke `caption.py` and crashed `stabilize.py` on a video, which nobody had
reported. #436 named `--position top`; the documented example in `--help` used
that exact flag and had never worked.

So a fix for the reported line is half the job. The other half is the sweep, and
it happens **before** the fix is written, because the siblings decide where the
fix belongs (one shared helper, or one tool).

## The loop

1. **Reproduce the report as written**, on the local FFmpeg. If it does not
   reproduce, check the fixture before the tool: FFmpeg sources round sizes,
   drop tags and pick pixel formats on their own (the `color` source turns
   629x1400 into 628x1400 for 4:2:0). Build the input another way and assert its
   properties with `probe.py` first.

2. **Name the class.** Write one sentence that does not mention the reported
   tool. The usual classes here:

   | Class | The sentence looks like | Sweep with |
   |---|---|---|
   | Input property | "a frame with an odd width reaches a filter that refuses it" | `tests/sweep.py INPUT --baseline PLAIN` |
   | Shared step | "the BT.601 conversion is first in every graph" | grep the helper's callers, then the sweep |
   | Two paths, one meaning | "`--srt` and `--text` reach libass by different routes" | run both paths with every value of the flag and compare the measurement |
   | Convention mismatch | "a number means something else to the library" | grep every place that number family is written |
   | Version behaviour | "from 7.1 the encoder takes tags from frames" | the CI job logs for 6.1 / 7.1 / 8 / 9, and the fixtures that set the same thing |
   | Result claim | "`verified: true` with something missing" | the sweep's `verified`, `warnings` and `dropped` columns |

3. **Sweep.** `python3 tests/sweep.py INPUT --baseline PLAIN` prints only the
   tools whose result differs from a plain clip's. Vary the property, not only
   the tool: if the report is an odd JPEG, also try an odd PNG, an odd video,
   an odd size in each of width and height. For a flag, run every choice of the
   flag, not the one reported.

4. **Sort the rows.** For each differing row, read `docs/design-decisions.md`:
   - a refusal with `kind: input` and a hint that names the way out is usually
     a decision: leave it, and say in the PR that it was seen;
   - `kind: ffmpeg`, an assertion, "Nothing was written", or a completed run
     whose output is wrong is a sibling.

5. **Decide where the fix goes.** Two or more siblings through one helper: fix
   the helper. Siblings with separate causes: fix the reported one here and
   file the others in **one** issue titled by the class, with the sweep rows
   pasted in.

6. **Pin the class, not the report.** The regression test iterates the
   property (all seven positions, both odd axes, both paths), and asserts the
   fixture before the tool.

7. **Say what was swept** in the PR body under "Siblings": the class sentence,
   the command, the rows that differed, and which were fixed, filed or decided.
   "None found" needs the command that found none.

## What a sweep is not

- Not a reason to widen the PR without limit: siblings with their own cause go
  to an issue.
- Not a judgement: `tests/sweep.py` prints what each tool said. A row is a
  question for design-decisions, not a bug by itself.
- Not complete: the table covers tools that take one media file. Sweep
  `join`, `sync`, `multicam`, `broll`, `render`, `batch`, `sequence`, `grid`
  and `insert` by hand when the class can reach them.
