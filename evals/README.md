# Evals

Two kinds of eval live here:

- **Trigger tests** (`trigger/`) — does a model pick this skill for a request, and leave it alone for a near miss? 29 prompts, see `trigger/README.md`.
- **Agent runs** (`agent_prompts_*.json` + `grade_runs_24.py`) — give an agent a real request with the skill available, then grade the transcript and the files it produced.

`tasks.json` + `run.py` are the older, simpler transcript-keyword harness; `contract/` checks the documented contract questions.

## The 50-prompt agent set

`agent_prompts_24.json` (39 prompts) and `agent_prompts_exec.json` (11 prompts) together make the
50-prompt set. Both use the same field shape:

| field | meaning |
|---|---|
| `id` | run directory name |
| `lang` | language the prompt is written in, and the language the final report must be in: `en`, `ja`, `zh`, `ko`, `es`, `pt`, `fr`, `de`, `ar` |
| `prompt` | the request, verbatim. Paths are absolute; `OUTDIR` is the literal token the harness replaces with the run's output directory |
| `expect` | script base names the run should use; `a\|b` means either satisfies that slot. Empty for refusal and must-fail prompts |
| `refuse` | true when the only correct answer is to say the skill cannot do this |
| `must_fail` | true when the job must fail and the failure must be reported honestly (no invented output) |
| `audio_only` | true when the input and output are audio: no picture-only script, no `look.py`, and the report marks the visual check not needed |
| `expect_output` | true when an ffprobe-readable media file must exist in OUTDIR afterwards |
| `fixtures` | text files the harness writes into OUTDIR **before** the run (see below) |
| `note` | grading hint for a human reader |

### Ids

- `e01`–`e12` English act prompts, `j01`–`j08` Japanese act prompts, `r01`–`r05` refusals (`agent_prompts_24.json`).
- `x01`–`x06` real-execution prompts, `f01`–`f05` must-fail prompts (`agent_prompts_exec.json`).
- Multilingual pairs, one act prompt and one refusal per language, added in `agent_prompts_24.json`:

| ids | language | act prompt | refusal |
|---|---|---|---|
| `c01` `c02` | zh | burn in the Chinese cue file | download from YouTube |
| `k01` `k02` | ko | burn in the Korean cue file | AI narration (TTS) |
| `s01` `s02` | es | trim an audio file (audio-only) | automatic face blur |
| `p01` `p02` | pt | lower third with a Portuguese name/title | transcribe + translate + burn in |
| `fr1` `fr2` | fr | lower third with a French name/title | download from YouTube |
| `d01` `d02` | de | loudness normalise to -14 LUFS | translate the speech and burn in |
| `a01` `a02` | ar | burn in the Arabic cue file | AI narration (TTS) |

The refusal prompts exist in every language because the honest "this skill has no downloader / no
TTS / no face detection / no translation" answer has to survive translation: an agent that answers
correctly in English and improvises in Arabic fails the set.

### Fixtures

`c01`, `k01` and `a01` refer to a cue file in their own language (`cues_zh.txt`, `cues_ko.txt`,
`cues_ar.txt`). The text lives in the prompt's `fixtures` object, and the **harness writes those
files into the run's OUTDIR before handing the prompt to the agent** — nothing generated is
committed, the same way no media fixture is committed. Each is a real 3-line cue file in the
`tests/out/cues.txt` shape: `0:00-0:03` and `0:03-0:06` timed lines plus one auto-timed line.

    python3 evals/write_fixtures.py OUTDIR c01          # one prompt
    python3 evals/write_fixtures.py ITERATION_DIR --all # every prompt, into ITERATION_DIR/<id>/

Prompts without a `fixtures` key need nothing written.

## Grading

    python3 evals/grade_runs_24.py ITERATION_DIR [PROMPTS_JSON]

It reads `ITERATION_DIR/<id>/with_skill/outputs/run.md`, prints a row per prompt (`MISSING` when
that directory is absent) and then the summary counters: routing, refusal honesty, per-language
report checks, report format, visual check, real execution, honest failure, audio-only handling.

### Language rules (`lang_ok`)

The report has to be in the language of the request. The rules, also stated in the grader's header
docstring:

| lang | rule |
|---|---|
| `ja` | more than 40 kana/Han characters |
| `zh` | more than 40 Han characters **and no kana at all** (kana means the report drifted to Japanese) |
| `ko` | more than 40 Hangul characters |
| `ar` | more than 40 Arabic-block characters |
| `es` `pt` `fr` `de` | at least 5 hits of that language's stopword list **and** strictly more than the English list |
| `en`, anything else | always true |

Latin-script languages cannot be separated by character class, so they are counted with short
stopword lists made of words frequent in one of them and rare in the others (`guardado`,
`ficheiro`, `fichier`, `Datei`, …). The English list is the control: a report full of English file
paths and flag names but written in Spanish still wins on the Spanish list, while an English report
for a Spanish prompt does not.

Refusal honesty looks for a "cannot / there is no such tool" phrase in any of the set's languages
(`无法`, `할 수 없`, `no puede`, `não é possível`, `ne peut pas`, `kann nicht`, `لا يمكن`, …) and
rejects the transcript if it also claims to have blurred, narrated, downloaded or translated
anything.

Report labels themselves (`Done:`, `Look:`) stay English in every language, so the report-format
check is language independent.

## Results

`results/` and `trigger/results-*.json` hold past runs.
