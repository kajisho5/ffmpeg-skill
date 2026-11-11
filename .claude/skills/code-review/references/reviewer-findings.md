# What an outside reviewer kept finding

353 inline findings from the automated reviewer on PRs #92 to #435, read as classes rather than
as a list. Each class below was reported on several unrelated PRs, which means the author's own
review did not ask the question. Ask every one of them before a push; a class that does not apply
takes a second to dismiss, and one that does was going to come back as a review round.

The counts are approximate (a finding can sit in two classes). PR numbers are examples to read,
not the full list. To rebuild the list: the review comments of this repository, author
`coderabbitai[bot]`, top-level comments only.

## The questions

1. **Does the path check cover every file this run reads and every file it writes?** (about 45:
   #376, #382, #413, #416, #428, #430.) The largest class. For each side file (`--timemap`,
   `--edl`, `--plan`, a report, an ASS sidecar, a second media output): compare it with *every*
   input (each `--srt`, `--brand`, `--font-file`, each clip of a project, each expanded batch
   item), with every other output including the *default* output path, and by file identity
   (hard links, symlinks), not by string. Guard on every run that would write the file, a dry
   run included (a dry run refuses an existing output just as the real run would), and on no run
   that would not (a mode that skips the file skips its guard). Validate before the first write.
   A side file that only records the result (a time map, an EDL, a report) is written after the
   media render succeeded; one the render reads (a generated ASS) has to exist before it, and one
   a mode produces with no render (an SRT alone) has no render to wait for. Stage it beside the
   target and replace, and require `--overwrite` to replace an existing one.
2. **Is a measurement that failed reported as "not measured"?** (about 30: #372, #376, #380, #383,
   #385, #386, #431, #432, #433, #434.) A failed ffprobe, a decode that returned nothing, an
   unknown frame rate or an unreadable decoder list must not come out as PASS, as an empty list,
   as `null` levels or as "none found". It is a WARN row, a note, or a refusal.
3. **Is the claim in the prose as narrow as the code?** (about 35: #98, #110, #345, #362, #383,
   #387, #399, #407, #433.) Every sentence added to CHANGELOG, README, `references/` and
   `docs/contract.md` that says "every", "always", "never", "all tools" or names a guarantee: find
   the code path it is false on (another mode, several inputs, a missing stream) and qualify it.
4. **Is this the right stream?** (about 20: #313, #352, #353, #360, #385, #412, #430, #434.) A
   cover picture is a video stream. The container duration is not the video's or the audio's. The
   first audio track is not the selected one. A still overlay is not a second video source. Use
   the playable video (`V:0`, non-attached), the stream's own duration, the selected track.
5. **Does the result say what was done, not what was planned?** (about 20: #355, #364, #380, #416,
   #427, #428, #434.) A field such as a preset, `declick_ms`, kept ranges, a language, fades or a
   drop reason is taken from what the run finally did (after snapping, fallbacks, a skipped
   stage), preferably from the output probe, and is absent when the thing did not happen.
6. **What does each numeric flag do with `nan`, `inf`, a negative, zero and an empty string?**
   (about 15: #343, #364, #372, #385, #387, #416, #427, #430, #434.) Also a count that sizes an
   allocation or a concat list. Since 3.3.0 `nan` and `inf` are refused for every `type=float`
   flag and every time string in one place each (`finite_float`, `parse_time`), and a contract
   walk tests it; what is left to ask is a number parsed any other way, and the range.
7. **Is a flag that this mode ignores refused?** (about 10: #385, #386, #399, #430.) Including
   when the caller passes the default value explicitly, and including zero.
8. **Does the dry run agree with the real run?** (about 12: #383, #385, #389, #428, #430, #431,
   #433.) It runs the same validation and refusals, skips measurements of inputs an earlier step
   has not written yet, and skips probes of files that only a real run creates.
9. **Is everything bounded?** (about 15: #303, #375, #376, #382, #386, #416, #433, #435.) A decode
   or a child's stderr held in memory, a subprocess with no timeout, a tail decode with no window,
   a FIFO or non-regular input read to its end.
10. **Is time handled per frame?** (about 25: #258, #372, #375, #376, #383, #385, #387, #416,
    #434.) Timestamps from frame PTS, not index divided by the average rate. Tolerances of one
    video frame or one AAC frame, compared unrounded. Both sides of a comparison on the same
    origin. Whether a window's edge is inclusive. Rounding that accumulates across ranges.
11. **Did the feature reach every surface?** (about 25: #260, #311, #353, #371, #373, #376, #380,
    #385, #430, #432.) A `feature` PR adds a before/after demo. A new constant, reason, language or
    flag is added to the table in `references/scripts.md` and to the contract description. Counts
    in SKILL.md and README still add up. `references/surfaces.md` has the inventory.
12. **Does each test fail for the reason its name gives?** (about 25: #97, #304, #315, #342, #344,
    #368, #383, #412, #427, #430, #434.) It checks the wiring or the documented bound, not a
    proxy. Expected values are computed per item. There is a test that forces the failure path.
    It skips where the platform cannot run it (Windows, no ffprobe, no `drawtext`) and keeps its
    fixtures inside `OUT`.
13. **With several inputs, is each one's own fact used?** (about 10: #412, #413, #416.) A hint, a
    timecode, a duration or a guard built from the first input is wrong for the second.
14. **Is the capability checked before the path that needs it, and declared?** (about 10: #387,
    #399, #433.) A filter, decoder or encoder is probed before the sidecar is written or the
    encode starts, with the caller's own fonts and assets, and the contract lists it.
15. **Does one refused item take its siblings with it?** (about 6: #371, #380.) One subtitle track
    that cannot be converted, one rejected phrase: the others are still handled.
16. **What is left behind when the run fails half way?** (about 8: #413, #428, #430.) A partial
    second output or a sidecar this run created is removed; one the caller asked to keep is
    reported.
17. **Does module state or a hint outlive its use?** (about 5: #385, #416.) State collected for
    one run is cleared at the start of `main()`; a hint is attached only to the refusal it explains.
18. **Is caller text escaped where it is quoted back?** (about 5: #101, #405.) File names and flag
    values in notes, hints and reproduced commands.
19. **Is the generator fixed, not its output?** (about 6: #363, #391, #430.) `docs/demos.md`, the
    site pages and `skills/ffmpeg-skill/SKILL.md` are generated; a wrong sentence there is a bug
    in the script that writes it.
20. **Does automation stop when it cannot know?** (about 4: #365, #435.) A workflow step whose
    lookup failed stops instead of taking a default, and a job has only the permissions it uses.

## How to use it

- Before a push: read the diff once per question that can apply. Questions 1, 2, 3 and 5 apply to
  almost every tool change.
- A question that finds something is a defect class: sweep it
  (`.claude/skills/sibling-sweep/SKILL.md`) before fixing the one place.
- A finding the reviewer raises that fits no question above is new: add the question here in the
  PR that answers the finding, with the PR number.
- Not every finding is right. Check it against the tree and `docs/design-decisions.md` first; a
  request to split a batched PR, or for docstring coverage, is declined with a reason.
