---
name: writing-defect-reports
description: Establish a finding before you publish it, and correct it after — headlines that overstate what actually reproduces at the layer a user sees, reporting code that no entry point can reach or that is already dead, filing a caveat the project's own records already answered, re-verifying your prior notes against the tree instead of against the note, choosing the narrowest injection point that reproduces a failure without breaking the run first, capturing probe output a harness swallows, and withdrawing a published claim in the thread where you published it. Use when filing an issue, writing the body of a PR or code review that asserts a defect, triaging someone else's report, or deciding whether a suspicious observation is reportable at all.
---

# Writing Defect Reports

A report is a claim, and it is read by people who will not re-derive it. The cost
of an overstated one is not embarrassment — it is a maintainer spending an
afternoon on a premise that does not hold, or a "fix" landing for a failure mode
that never occurred. The techniques for *finding* a defect live in
**verifying-external-behavior** (also in this repo's `.claude/skills/`). This
skill is about the step between finding one and publishing it.

The rule underneath all of it: **publish the claim you actually measured, at the
layer you measured it.**

## The anomaly is real; the headline may not be

The common failure is not a fabricated bug. It is a genuine internal oddity
promoted one layer too far.

You notice that a helper returns a degenerate value for a small sample, trace it
into a scoring path, and write the report as *"short inputs are wrongly flagged."*
Then you run real short inputs through the public entry point and the flag never
sets — a downstream threshold absorbs the degenerate value, and the only visible
effect is noise in a secondary per-feature list. The internal oddity is worth
fixing; the headline was false, and a reviewer who tests it will say so.

**Before writing the title, run the reproduction at the outermost layer the title
names.** Then choose one of three honest framings:

| what you measured                          | how to file it                              |
| ------------------------------------------ | ------------------------------------------- |
| reproduces end to end                      | file it as the user-visible symptom         |
| reproduces internally, absorbed downstream | file the internal defect, state the absorption |
| does not reproduce at all                  | do not file; record the probe and move on   |

The second row is a good report, not a weak one. "This helper returns a value it
should not; today a threshold happens to mask it, so there is no user-visible
symptom yet" tells a maintainer exactly how to prioritize. Silently keeping the
dramatic title because the underlying issue is real is what burns credibility.

## Check the code is reachable before calling it broken

Three shapes look like defects and are not — or are, but not the one you were
about to describe:

**A branch that cannot execute.** An early return guarding a lookup that already
returns the same value on the missing case; a condition a preceding gate already
implies. This is dead code, and "dead code" is the accurate report. Filing it as a
correctness bug, or naming a test as though it exercises that branch, misleads
everyone downstream — confirm liveness by deleting the line and watching the
suite, not by reading it.

**A guard whose pattern only matches your fixture.** A validity check written
against a hand-typed sample can be structurally unable to fire against the real
input: a single-line pattern against a generator that wraps its output across
indented lines, an exact-string check against a source that varies whitespace.
Verify the guard against a captured real input, not the fixture. The consequence
matters for the fix, too: replacing synthetic fixtures with real captures deletes
that guard's only coverage, so the fix and the fixture change belong in one
change, not two.

**A file nothing invokes.** Repos accumulate scripts that reference paths the
repo does not contain and toolchains it does not depend on. Before reporting one
as broken, find the caller — the task runner, the workflow, the entry point. If
there is none, the report is "this is dead, delete it," which is cheap and
uncontroversial, rather than "the build is broken," which is wrong.

## Search the project's own records before filing a caveat

The most avoidable report is the one the project already answered. Two measured
figures that look inconsistent are usually inconsistent *definitions*, and the
definition is usually written down: a claim ledger row, a docstring, a design
note, a closed issue.

Grep for the term before writing "these two numbers do not appear to compute the
same quantity." If a record pins the definition, cite it — the caveat you were
about to publish reads as an open question the project already closed, and a
maintainer has to re-close it.

The same discipline applies to numbers you are *quoting*. Figures in an older
issue may not reproduce, because a dependency the value depends on is unpinned
and the installed version has changed. Re-measure before restating, and record it
with the command, output, and date — see **verifying-external-behavior** for why
an undated measurement cannot be re-checked, and **cross-surface-changes** for
choosing between two records that cover the same fact.

**Quote the protocol next to the figure**, not only in whatever artifact produced
it: the split, the warmup, the seed, the version. Two documents quoting the same
metric under different protocols read as a regression to anyone comparing them,
and the reader has no way to tell that they are not comparable.

## Your earlier note is a claim, not evidence

Working notes, scratch findings, and a prior comment on the same issue are
secondary sources — including your own. They were true about a tree that has
since moved, or they were wrong when written.

When a note and the code disagree, the code settles it. Re-derive from the
integration branch directly rather than from a checkout that may be behind:

```bash
git show origin/main:path/to/file.py | grep -n 'the_symbol'
```

If two notes contradict each other, do not average them and do not pick the more
recent — re-check the tree and then correct the wrong note in place, saying that
it was wrong. A knowledge base that records both readings without resolving them
is worse than one that records neither, because the next reader will pick one at
random.

## Pick the narrowest injection point that reproduces the failure

To exercise a failure path by hand you need to break something. Break the
smallest possible thing, or the run dies before reaching the path you care about.

The classic miss is a blanket hook or a global monkeypatch:

```bash
# Too broad — rejects EVERY commit, including the unrelated bookkeeping commit
# the process makes first. The run fails earlier than the path under test, and
# you have reproduced a different bug.
echo 'exit 1' > .git/hooks/pre-commit

# Narrow — fails exactly the operation whose failure you want to observe.
cat > .git/hooks/commit-msg <<'EOF'
grep -q 'sync from source-b' "$1" && exit 1
exit 0
EOF
```

The same rule holds elsewhere: fail one HTTP host rather than the network; make
one file unreadable rather than the directory; raise from one call rather than
patching the module. **After the run, confirm it failed where you intended** —
otherwise you have measured your instrumentation.

**Check where your probe's output actually goes.** Test harnesses commonly
replace the global logger or console object at setup, and verbosity flags do not
undo that. If a probe prints nothing, append to a file outside the harness's
reach and read it afterwards, rather than concluding the code path did not run.

## Report the checks that model a real regression

When you back a report with mutation evidence, include only mutations that (a)
plausibly model how an implementation would actually regress and (b) demonstrably
turn a named test red. A mutation that nothing catches is worth reporting as a
coverage gap; a mutation nobody would ever write is noise that makes the rest of
the report look padded.

State which test each mutation trips, and which assertion inside it — a guard
often turns out to be load-bearing at a different layer than the report assumed,
and the assertion name is what reveals it.

## A red gate is not an aside

Whether a red check is pre-existing is answered by running it on the base commit
— see **reproducing-ci-locally** (also in this repo's `.claude/skills/`). What
belongs here is where that answer goes in the write-up. A red check is never a
parenthetical under a "done" claim: give it its own statement naming what is red,
what makes it red, and whether you fixed it. And **confirm green after the run
finishes** rather than writing "should be green" — a prediction stated as an
outcome is the same defect as an overstated headline, one artifact over.

## Withdraw published claims where you published them

A wrong claim that has been read does not become unwritten when you stop
repeating it. If a caveat, a number, or a framing you published turns out to be
wrong or already-answered:

- Say so in the same thread, naming what was wrong and what is true instead.
- Do not quietly delete it and re-file a corrected version elsewhere; readers who
  saw the first one are never routed to the second.
- Keep it to the correction. A retraction is one or two sentences — what you
  claimed, what is actually the case, what changes as a result.

The same applies to a claim you inherited. If you repeat someone else's figure and
it fails to reproduce, correcting it is part of your report, not a separate errand.

## Checklist

```
Before publishing a defect report:
- [ ] Reproduction run at the outermost layer the title names; title matches
      what reproduced there, not what you found internally
- [ ] Absorbed-downstream findings filed as internal defects, with the absorption
      stated — not promoted to a user-visible symptom
- [ ] The code is reachable: an entry point calls it, and the branch is live
      (checked by deletion, not by reading)
- [ ] Guards verified against a captured real input, not the fixture that was
      written alongside them
- [ ] Project records (ledger, docstrings, design notes, closed issues) searched
      for a definition that already resolves the discrepancy
- [ ] Every quoted number re-measured, with version, command, and date; protocol
      stated next to the figure
- [ ] Prior notes re-verified against the integration branch, and any wrong note
      corrected in place
- [ ] Failure injected at the narrowest point; run confirmed to have failed where
      intended
- [ ] Mutation evidence limited to plausible regressions, each attributed to a
      named test and assertion
- [ ] No red check described as pre-existing under a "done" claim; green
      confirmed after the run finished, not predicted
- [ ] Any earlier wrong claim withdrawn in the thread where it was published
```

## Note for this repository (ffmpeg-skill)

This is the same discipline behind this repo's 0.9.1/0.10.0 "honesty fix"
pattern: `cut.py`'s `mode`/`keyframe_snapped`/`duration_delta_seconds` fields,
`check.py`'s `reason` field, and `render.py`'s check-stage exit code were all
added because a prior report ("the cut is lossless," "the check passed," "the
render succeeded") was true at one layer and silently false at the layer a
caller actually reads results from — exactly the "genuine internal oddity
promoted one layer too far" pattern this skill describes, just discovered
after shipping rather than before. When investigating a new claim about this
codebase, reproduce it with real media via `tests/test_all.py`'s fixtures
before reporting it, the same way `test_cut_copy_keyframe_snap_reports_a_real_nonzero_delta`
measured an actual 1.24s divergence rather than assuming one.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
