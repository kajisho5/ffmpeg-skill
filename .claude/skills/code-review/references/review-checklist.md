# Review Checklist — runnable

Copy this into the review. Every box is a command or a named read, not a feeling.

## 0. Base

```bash
git fetch origin
git log --oneline -1 origin/main
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- scripts/ docs/contract.md SKILL.md README.md
```

- [ ] Findings are stated against file:line at the reviewed commit
- [ ] `docs/design-decisions.md` grepped for each candidate finding; any match
      cites the sentence that no longer holds

## 1. Result-document honesty

- [ ] `status` cannot be `completed` on a non-zero exit (`die()` sets `failed`)
- [ ] `verified` is a conjunction of steps that ran; nothing flipped to `true`
      without a measurement
- [ ] `dropped_non_av_streams` matches timeline-move vs in-place (see
      `result-honesty.md`)
- [ ] `cut` still reports `mode` / `keyframe_snapped` / `duration_delta_seconds`
- [ ] `error.kind` is the kind that actually occurred; `retryable` stays `false`
- [ ] `info()` still rewrites `wrote X` under `--dry-run`; no write claim in a
      dry-run document
- [ ] `analysis_only` tools still measure under `--dry-run`

```bash
grep -rn "emit(\|die(" scripts/*.py | wc -l      # every script ends in one of the two
python3 scripts/<changed-tool>.py --json --dry-run ... # read the document it prints
```

## 2. Surfaces

```bash
python3 scripts/_contract.py --json > /tmp/before.json   # before the change
python3 scripts/_contract.py --json > /tmp/after.json    # after
diff /tmp/before.json /tmp/after.json
wc -c SKILL.md                                            # must be < 30000
```

- [ ] New flag/tool is in the contract, and `README.md` / `SKILL.md` /
      `references/scripts.md` / `docs/contract.md` agree
- [ ] `CHANGELOG.md` has the entry
- [ ] `feat`: a demo in `demos/build.py` (or an `INSPECTION` row), `docs/demos.md`
      regenerated with `python3 demos/build.py --docs`
- [ ] `SKILL.md` stayed under 30,000 bytes; the PR names the line it trimmed
- [ ] Release PR moved `docs/roadmap.md`'s "released version today" line

## 3. Scope and rules

- [ ] No new runtime dependency; stdlib + Python 3.9+ only
- [ ] No raw `ffmpeg`/`ffprobe` shell call outside `scripts/*.py`
- [ ] No mutation of an input file
- [ ] No AI/LLM content judgement, no cloud, no API keys
- [ ] Colour flags go through `validate_color(`; `--crf` range check stays in
      `apply_common()`; time parsing goes through `time_arg()`
- [ ] A 1.x change does not change the meaning of an existing field — parallel key
      (`result_v2`, `hdr_signal`) instead
- [ ] A fix ships a regression test that would have caught the original bug

## 4. The gate

```bash
npm test
npm run release-check
python3 scripts/_contract.py doctor
```

- [ ] Both test files pass, read after the run — not predicted
- [ ] Any red check is its own statement: what is red, what makes it red, whether
      it was fixed, and whether it is pre-existing (run it on the base commit)
- [ ] Cross-OS / cross-FFmpeg risk stated for changes touching ffmpeg invocation,
      path handling, or child-process decoding (CI covers FFmpeg 5.1–9.x on
      Linux/macOS/Windows)
- [ ] No skip-CI marker quoted in the PR body

## 5. The write-up

- [ ] Findings ordered by cost: false claim → missing surface/test → style
- [ ] Each finding has file:line, the concrete failure, and the smallest fix
- [ ] Unverified items are labelled unverified, not implied passing
- [ ] Deep security audit deferred to a dedicated pass if warranted
