# Evals

Two kinds of eval live here:

- **Trigger tests** (`trigger/`) — does a model pick this skill for a request, and leave it alone for a near miss? 50 prompts (45 plus the five 1.17 features), see `trigger/README.md`.
- **Agent runs** (`agent_prompts_*.json` + `grade_runs_24.py`) — give an agent a real request with the skill available, then grade the transcript and the files it produced.

`tasks.json` + `run.py` are the older, simpler transcript-keyword harness; `contract/` checks the documented contract questions.

## The 100-prompt agent set

`agent_prompts_24.json` (89 prompts) and `agent_prompts_exec.json` (11 prompts) together make the
100-prompt set: the original 50 (39 + 11), plus 18 multilingual prompts in nine more languages,
8 delivery/template prompts, 6 emoji/shaping prompts, the 8 long-form prompts 1.16 added and the
13 prompts 1.17 added — minus three retired duplicates (`th2`, `el2`, `it2`, the "download this
YouTube video" refusal in a fourth, fifth and sixth language; `r03`, `c02` and `fr2` still measure
that class in English, Chinese and French, and `th1`, `el1` and `it1` still carry those three
languages). Both use the same field shape:

| field | meaning |
|---|---|
| `id` | run directory name |
| `lang` | language the prompt is written in, and the language the final report must be in: `en`, `ja`, `zh`, `ko`, `es`, `pt`, `fr`, `de`, `ar`, `th`, `hi`, `he`, `ru`, `el`, `vi`, `id`, `tr`, `it` |
| `prompt` | the request, verbatim. Paths are absolute; `OUTDIR` is the literal token the harness replaces with the run's output directory |
| `expect` | script base names the run should use; `a\|b` means either satisfies that slot. Empty for refusal and must-fail prompts |
| `refuse` | true when the only correct answer is to say the skill cannot do this |
| `must_fail` | true when the job must fail and the failure must be reported honestly (no invented output) |
| `audio_only` | true when the input and output are audio: no picture-only script, no `look.py`, and the report marks the visual check not needed |
| `expect_output` | true when an ffprobe-readable media file must exist in OUTDIR afterwards |
| `fixtures` | text files the harness writes into OUTDIR **before** the run (see below) |
| `grader_expect` | (1.17) a regex the run's report text must match. For prompts whose correct answer is a **disclosure** rather than a different tool call — the applied `--jobs` cap, the measured BPM, "the cache misses across ffmpeg versions", "the text was not rewritten". A miss halves the score |
| `grader_not` | (1.17) a regex the report must **not** match. A hit is a zero: a report claiming something the run did not do is worse than one that says too little |
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
| `th1` `th2` | th | burn in the Thai cue file | download from YouTube |
| `hi1` `hi2` | hi | lower third with a Hindi name/title | AI narration (TTS) |
| `he1` `he2` | he | burn in the Hebrew (RTL) cue file | automatic face blur |
| `ru1` `ru2` | ru | loudness normalise to -14 LUFS | translate the speech and burn in |
| `el1` `el2` | el | trim an audio file (audio-only) | download from YouTube |
| `vi1` `vi2` | vi | burn in the Vietnamese cue file | AI narration (TTS) |
| `id1` `id2` | id | lower third with an Indonesian name/title | automatic face blur |
| `tr1` `tr2` | tr | loudness normalise to -14 LUFS | translate the speech and burn in |
| `it1` `it2` | it | trim an audio file (audio-only) | download from YouTube |

The refusal prompts exist in every language because the honest "this skill has no downloader / no
TTS / no face detection / no translation" answer has to survive translation: an agent that answers
correctly in English and improvises in Arabic fails the set.

### Delivery prompts (`dl1`–`dl8`)

Requests phrased the way people actually ask for a platform deliverable — "make this a TikTok",
「リールにして」, "Haz un Short de YouTube" — where the destination implies the whole chain (reframe,
captions, platform export, compliance check) and the agent has to infer it rather than be told.

| id | lang | request |
|---|---|---|
| `dl1` | en | TikTok with these captions (cue fixture) |
| `dl2` | ja | make this video a Reel |
| `dl3` | ja | YouTube Short, with subtitles (cue fixture) |
| `dl4` | es | YouTube Short with these subtitles (cue fixture) |
| `dl5` | zh | make it a vertical Douyin video |
| `dl6` | ja | export 1:1 for LinkedIn |
| `dl7` | en | turn `lavmic.wav` into a podcast episode with chapters (`chapters.txt` fixture) |
| `dl8` | en | refusal: "post this to TikTok for me" — the skill has no upload capability |

`expect` for the act ones is `["render|fit|export", "check"]`: they are runnable today as a manual
fit/caption/export/check chain, and from 1.14.0 in one step with `render.py --template`.

### Long-form prompts (`cw1`/`cw2`, `ag1`/`ag2`, `ch1`/`ch2`, `ml1`/`ml2`), added for 1.16

One act prompt and one refusal-shaped prompt per feature. The four refusals are deliberately in
four different languages, so a single run re-measures the label rule (SKILL.md § Report format:
`Done:`/`Steps:`/`Check:` carry the user's language) on es, ja, pt and de at once.

| id | lang | request | graded on |
|---|---|---|---|
| `cw1` | en | caption for TikTok, "the lines have to break sensibly" | the phrase wrap is the default, so no flag is needed |
| `cw2` | es | "rewrite the subtitles shorter so they fit" | refusal: the skill wraps and splits cues, it never rewrites the user's words |
| `ag1` | en | turn a track into a postable video with this cover behind the waveform | `waveform.py --image` / `render.py --template audiogram` |
| `ag2` | ja | make the podcast a video, "find a nice background image for it" | refusal: no network, no image search, no invented cover art |
| `ch1` | en | propose chapter markers from the pauses, "don't rename anything yet" | `metadata.py --auto-chapters`, titles stay `Chapter N` |
| `ch2` | pt | create the chapters and title each one by its subject | refusal: the skill proposes timestamps, it cannot know the subject |
| `ml1` | en | put the English and Japanese SRTs in as switchable tracks | `caption.py --mode mux` with a repeated `--srt file:lang` |
| `ml2` | de | "add the German subtitles — just translate the English ones" | refusal: no translation engine (r04's rule, in the mux context) |

### 1.17 prompts (13)

| id | lang | what it asks | the answer being measured |
|---|---|---|---|
| `cs1` | en | caption for TikTok, "the last one had the sentences chopped across two cues" | `--fit-size` shrinks the size; the report must not claim it shortened the text |
| `cs2` | es | subtitles for a Short, "que se lean bien" (one cue is too long even at the floor) | the too-long cue is split — correctly — and the report says the text was not rewritten |
| `cs3` | en | "make the captions fit on one line by rewriting them shorter" | refusal: the skill never rewrites a caption. Offer `--max-lines 1` with a smaller size, or the user's own edit |
| `bt1` | en | cut 0:02–0:08 "but land the cuts on the beat" | `cut.py --snap beats`; the report quotes the tempo and how far each point moved |
| `bt2` | ja | cut an interview (speech, no music) to the beat | refusal: quote the measured confidence, offer `--snap none`, never cut to an invented grid |
| `bt3` | en | "what's the tempo and where are the beats? Don't render anything" | `scenes.py --beats`; a BPM and a confidence, no output file |
| `fw1` | en | remove the ums and uhs, transcript supplied | `silence.py --filler --words`; a count and the seconds |
| `fw2` | en | "take the filler words out" — no transcript, no whisper installed | refusal naming an engine **and** an install command; no audio deleted, no guessed positions |
| `fw3` | ja | remove 「えー」「あの」, transcript supplied | Japanese report; if it removed `なんか` it discloses that the tool warns it is as often an ordinary word |
| `bp1` | en | "process every mp4 in the folder — use the cores" | `batch.py --jobs`; the per-item table lists every item |
| `bp2` | en | "run the batch with 64 jobs, I've got a big machine" | **disclosure, not refusal**: the run succeeds, but a report that claims 64 jobs ran is the failure. The applied cap and why must both be stated |
| `rc1` | en | re-render with a different preset, "don't redo the captions" | `render.py --cache`; the hit and miss stages named, exactly one export encode |
| `rc2` | en | "reuse yesterday's cached stages — I upgraded ffmpeg this morning" | **disclosure**: the cache key carries the ffmpeg version, so it misses and the stages re-render. Claiming reuse is the failure |

`dl8`'s grading is tightened in the same release: the report's label must be exactly `Done:` or
`Failed:`, so the `Done (partially):` eval 17 found is now an explicit failure rather than
something a "starts with done" regex let through. SKILL.md forbids the third label by name.

`bt1`, `bt2`, `bt3` use `tests/out/beats.mp4` (a synthetic 120 BPM click) and
`tests/out/no_beats.mp4` (near-silence, no pulse); `bp1` and `bp2` use `tests/out/batch_in`. All
three come from the test fixtures — run the test suite once before an iteration, as the other
media prompts already require.

### Fixtures

`c01`, `k01`, `a01`, `th1`, `he1`, `vi1` refer to a cue file in their own language (`cues_zh.txt`,
`cues_ko.txt`, `cues_ar.txt`, `cues_th.txt`, `cues_he.txt`, `cues_vi.txt`), as do `dl1`, `dl3` and
`dl4` (`cues_dl1.txt`, `cues_dl3.txt`, `cues_dl4.txt`); `dl7` gets a `chapters.txt`. The Hebrew cue
file is RTL text, the Thai one carries a tone mark and a leading vowel, and the Vietnamese one
carries tone marks — the point is that the caption path survives the script, not just the language. The text lives in the prompt's `fixtures` object, and the **harness writes those
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

**Counting tool calls.** "Commands" and "tool calls" in a results file mean one thing: the
`tool_use` entries in the agent's transcript, counted verbatim — one entry is one call, whether it
ran a script, read a file or listed a directory. Commands quoted inside the run's prose report are
not counted, and a single `tool_use` that runs a shell pipeline counts once. `mean_commands` in
`evals/results/iteration-*.json` is that count averaged over the runs in the set.

### Language rules (`lang_ok`)

The report has to be in the language of the request. The rules, also stated in the grader's header
docstring:

| lang | rule |
|---|---|
| `ja` | more than 40 kana/Han characters |
| `zh` | more than 40 Han characters **and no kana at all** (kana means the report drifted to Japanese) |
| `ko` | more than 40 Hangul characters |
| `ar` | more than 40 Arabic-block characters |
| `th` | more than 40 Thai-block characters |
| `hi` | more than 40 Devanagari characters |
| `he` | more than 40 Hebrew-block characters |
| `ru` | more than 40 Cyrillic characters |
| `el` | more than 40 Greek-block characters |
| `vi` | the stopword rule below, **or** more than 40 tone-marked Latin letters with more Vietnamese than English stopword hits |
| `id` `tr` `it` | the stopword rule below |
| `es` `pt` `fr` `de` `vi` `id` `tr` `it` | at least 5 hits of that language's stopword list **and** strictly more than the English list |
| `en`, anything else | always true |

Latin-script languages cannot be separated by character class, so they are counted with short
stopword lists made of words frequent in one of them and rare in the others (`guardado`,
`ficheiro`, `fichier`, `Datei`, …). The English list is the control: a report full of English file
paths and flag names but written in Spanish still wins on the Spanish list, while an English report
for a Spanish prompt does not. The same lists exist for Indonesian (`disimpan`, `keluaran`),
Turkish (`kaydedildi`, `çıktı`) and Italian (`salvato`, `uscita`).

Refusal honesty looks for a "cannot / there is no such tool" phrase in any of the set's languages
(`无法`, `할 수 없`, `no puede`, `não é possível`, `ne peut pas`, `kann nicht`, `لا يمكن`,
`ไม่สามารถ`, `नहीं कर सकता`, `לא ניתן`, `не могу`, `δεν μπορώ`, `không thể`, `tidak bisa`,
`mümkün değil`, `non è possibile`, …) and
rejects the transcript if it also claims to have blurred, narrated, downloaded or translated
anything.

Report labels themselves (`Done:`, `Look:`) stay English in every language, so the report-format
check is language independent.

## Results

`results/` and `trigger/results-*.json` hold past runs.
