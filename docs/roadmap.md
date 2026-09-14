# Roadmap: 1.7.1 → 1.21.0 → 2.0

The 1.x contract is frozen (docs/contract.md, "Stability guarantee"). 1.8 → 1.10 pre-ship the
2.0 decisions (issue #189, docs/design-decisions.md "Decided for 2.0") behind opt-in flags or
parallel keys, plus the follow-ups the evals keep surfacing. 1.11 → 1.20 grow the skill on the
frozen contract, one theme per minor, each closed by an evals iteration on the theme's own
prompts and an audit pass, as 1.5 → 1.7 did. 2.0.0 then removes the old spelling and flips the
defaults; it adds no feature of its own. `resolve_version.py` turns `feat` PRs into a
minor and `fix` PRs into a patch, so each block below is one or two `feat` PRs plus fixes.

**Every heading carries one of three states**, so that "on the roadmap" is never mistaken for
"in the released package":

- **shipped + evaluated** — released, and closed by a named evals iteration whose results are in
  `evals/results/`.
- **shipped, eval pending** — released, but no evals iteration has graded it yet.
- **planned** — not released. Nothing below a *planned* heading exists in any published version;
  the feature lines are the intent, not a description of the code.

The released version today is **1.17.1**, shipped and evaluated: **eval 19**
(`evals/results/iteration-19.json`) re-ran the 18 prompts eval 18's follow-up named, three of them
three times over, and confirmed the patch — the size fitter fires on the `render.py --template`
path in 12/12 caption runs, and the beat, filler and `--jobs` prompts route on the first try. It
also root-caused a defect the two previous patches had been aiming at symptoms of: `caption.py`'s
generated-ASS path writes the platform's *vertical* safe margin into `MarginL` and `MarginR` too,
so libass lays every caption into a 240 px column and stacks one word per line (see the 1.17.1
section). **1.17.2 below is the patch — implemented, not tagged yet.** Everything after 1.17.2 is
planned.

| version | state | evidence |
|---|---|---|
| 1.8.0 | shipped + evaluated | eval 8 at 1.8.0 (`iteration-8.json`) |
| 1.9.0 | shipped + evaluated | eval 9 at 1.9.0 (`iteration-9.json`) |
| 1.10.0 | shipped + evaluated | eval 10 at 1.10.0 (`iteration-10.json`), corpus re-run 101/101 |
| 1.11.0 / 1.11.1 | shipped + evaluated | eval 11 at 1.11.0, eval 12 at 1.11.1 |
| 1.12.0 | shipped + evaluated | eval 13 at 1.12.0 (`iteration-13.json`) |
| 1.13.0 | shipped + evaluated | eval 14 at 1.13.0 (`iteration-14.json`) |
| 1.14.0 | shipped + evaluated | eval 15 at 1.14.0 (`iteration-15.json`) |
| 1.15.0 | shipped + evaluated | eval 16 at 1.15.0 (`iteration-16.json`) |
| refactor after 1.15.0 | shipped, eval pending | contract + MCP snapshots and every `--help` byte-identical; 323/323 cases |
| 1.16.0 | shipped + evaluated | eval 17 at 1.16.0 (`iteration-17.json`); contract and MCP snapshots additive only; tool count still 42 |
| 1.16.1 | shipped + evaluated | caption-break patch from eval 17: a Thai run and a katakana word are never broken inside, `caption.py` reports `overlong` lines; eval 18 graded the tree that carries it and reported no wrapping defect |
| 1.17.0 | shipped, evaluated (eval 18) | eval 18 at 1.17.0 (`iteration-18.json`); tool count still 42; contract and MCP snapshots additive only. Two findings: `render.py` forwards the platform table's caption size as an explicit `--size`, so `--fit-size` never fires on the path every captioned prompt takes (and the project schema rejects `fit_size`), and SKILL.md names none of the 1.17 features, so beats, filler and `--cache` were each used in one run at most. 1.17.1 is the patch |
| 1.17.1 | shipped, evaluated (eval 19) | eval 19 at 1.17.1 (`iteration-19.json`), 26 runs over the 18 prompts eval 18 named; tool count still 42, contract additive only. The patch holds: `--fit-size` fires on the template path 12/12 (24 → 16, `dl4` to the 13-unit floor, `split` 0, `text_unchanged` true), filler and beats route first try, the third label is gone, trigger 50/50. One finding, and it is older than the patch: `caption.py write_ass` writes the platform's vertical safe margin to `MarginL`/`MarginR` as well as `MarginV`, leaving a 240 px text column at `PlayResX` 1080, so the picture still stacks one word per line on the `--animate`/`--karaoke` path every template takes. Present since 1.14. 1.17.2 is the patch |
| 1.17.2 | implemented, not tagged yet | eval 19 headline: `caption.py` wrote the VERTICAL `--margin` into the ASS Style's `MarginL`/`MarginR` too, so TikTok geometry left a 240 px text column and libass stacked one word per line while the tool reported `split: 0`. The side margins are the destination's horizontal safe zone and the fitter measures the same column; the pinned `--fit-size off` ASS fixture was re-pinned (it carried the wrong margins). Tool count still 42, contract additive only |
| 1.18.0 → 1.21.0, 2.0.0 | planned | — |

## 1.8.0 — one-call delivery, quieter checks, encoder flags (shipped + evaluated, eval 8)

- **`check.py` judgement rows without a named platform.** Today `--platform` defaults to
  `youtube`, so a run that only wanted the format rows gets loudness / true-peak FAILs and the
  agent spends a paragraph explaining why it left them alone (eval 7: e07, e12, j02, j04). When
  `--platform` is not given explicitly, judgement rows report `WARN` (not `FAIL`, not counted in
  `failed`) and a `notes` line says the target was assumed. Named platforms are unchanged.
- **`render.py` `export.normalize`.** The project's export stage forwards `--normalize` so a
  project renders a platform-compliant file in one export (1.7.1 gave the flag to `export.py`).
- **`--codec h264|hevc|av1|prores` and `--quality N`** (2.0 B, pre-shipped): added by
  `add_common()` to every re-encoding tool, resolved once in `video_args()` (CRF for x264/x265,
  `-crf`/`-b:v` for av1, profile for ProRes; HDR / 10-bit branch stays in the same place).
  `--crf` / `--preset` keep working as aliases with no deprecation yet. Contract snapshot and
  MCP snapshot regenerated; `docs/contract.md` gains one paragraph.
- **Eval iteration 8 at 1.8.0** (3 repeats, independent grader): confirms the 1.7.1 language
  fix (r04 / f01), measures whether `--normalize` removed the second export, and whether
  `--codec` gets picked for "make it HEVC" / "ProRes master". Seventh audit pass on the tree.

## 1.9.0 — one time grammar, one HDR meaning (shipped + evaluated, eval 9)

- **`time_arg()` everywhere** (2.0 B): `broll.py`, `cut.py`, `freeze.py`, `render.py`,
  `sequence.py`, `verify.py` still call `parse_time()` or their own helpers; every time-taking
  flag goes through `time_arg()`, so seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` and four-part
  SMPTE behave the same in all 42 tools. Documented once in `references/scripts.md`.
- **`@fps` suffix**: `00:01:02:15@29.97` names the rate explicitly; without it a four-part value
  uses the source fps and a missing fps stays `kind: input`. Accepted by `time_arg()` only.
- **`hdr_signal`** (2.0 A, parallel key): `probe` adds `hdr_signal: true` only for PQ / HLG
  transfer; `hdr` keeps today's meaning (BT.2020 primaries count) until 2.0 renames it. The
  HDR-aware tools (`color`, `export`, `check`, `proxy`) read `hdr_signal` so BT.2020 SDR stops
  going down the HDR path, with `hdr_format: "BT.2020 SDR"` as the explanation.
- **Eval iteration 9**; pins in `docs/design-decisions.md` for the grammar and the HDR split.

## 1.10.0 — 2.0 readiness (shipped + evaluated, eval 10)

- **Deprecation notices** (done), per the three-step policy in `docs/contract.md`: `--help` text,
  CHANGELOG, and a `deprecated` list in `contract --json` for what 2.0 removes: the per-tool
  v1 success keys superseded by `result_v2`, `--crf` as an alias of `--quality`,
  `json` / `progress` in the MCP `inputSchema`, the current `hdr` meaning, the overwrite default.
  (`--preset` is *not* deprecated: it is the x264 speed preset, not a quality alias.)
- **`Context` threading** (done, 2.0 B, internal): `STATE` is the default `Context` instance and
  `run()` / `emit()` / `die()` / `info()` accept an optional `ctx=`; no tool changes behaviour. 2.0 makes
  the argument required, which is the signature change the major is for.
- **MCP lean schema, opt-in** (done): `FFMPEG_SKILL_MCP_LEAN=1` drops `json` / `progress` from
  `tools/list` (2.0 A3 pre-shipped; the default stays byte-identical to the CLI, as the
  contract promises).
- **`FFMPEG_SKILL_NO_OVERWRITE=1`** (done) documented in SKILL.md as the recommended agent setting;
  the test is `test_contract.py`'s `test_existing_output_warns_today_refuses_on_request_and_never_for_its_own_files`,
  so 2.0's default flip has been exercised.
- **Eval iteration 10** and an eighth audit pass; the real-device corpus re-run on the tree —
  all done: the eighth audit shipped as 1.9.1, eval 10 graded 108/108 at 1.10.0
  (`evals/results/iteration-10.json`) and the corpus re-ran 101/101 steps PASS.
  `docs/contract.md` "What 2.0 changes" section written from the `deprecated` list (done).

## 1.11.0 — token diet (shipped + evaluated, eval 11; the 1.11.1 follow-up by eval 12)

The PR was `feat:`, so the release bot cut a minor and the themes below moved up one.

The eval-10 follow-up: make a job cost the agent fewer tokens and fewer calls without changing
what any tool does. Nothing here is a behaviour change — `--json`, exit codes, contract fields
and the default MCP `tools/list` are unchanged except for additions.

- **Two-tier SKILL.md** (done): the always-loaded file keeps the workflow, the request→script
  table, the report format and one line per gotcha; the long "Things that look right but are
  wrong" / "Gotchas" prose and the audio-only recipes moved to `references/gotchas.md`, each
  line pointing at its anchor. 362 lines / 37.8 KB → 198 lines / 29.1 KB, no rule dropped.
- **Guidance that saves calls** (done): `doctor` only after a failure or when the user asks
  (1.11.1; the 1.11.0 wording "before the first job on a new machine" made fresh agents run it
  in 23 of 36 eval runs, 0 of 36 after the change), not per job; no separate `probe.py` before every edit (a writing
  tool's `--json` already carries the input and the output probe); `render.py` with a project.json
  for jobs of three or more steps; `look.py --tiles 3x2` (or `--at T`) for verification, the full
  4x3 sheet only when the job is about layout across the whole clip.
- **`--json-brief`** (done, additive): every tool gains a flag that prints the same success
  document trimmed to `status`, `output`, `dry_run`, `verified`, a compact `summary`
  (duration/width/height/fps/codecs/channels, `lufs` when measured), its own tool-specific keys
  and the command count instead of the command lines — about a third of `--json`'s bytes.
  `contract --json` reports it as `supports_json_brief`, mirroring `supports_json`.
- **Shorter `doctor` summary** (done): the plain-text output states counts and what is missing
  (1681 → 522 bytes on a healthy machine); `doctor --json` is unchanged and still carries every
  capability name, per-tool `usable` and the fix hints.
- **Eval iteration 11** measured tokens per run and kept only the changes that hold routing,
  honesty, language, report format and look behaviour at iteration-10 levels (done, 36/36 at
  1.11.0). It also showed the 1.11.0 wording sending agents to the reference files and to
  `doctor` on every job, which 1.11.1 reworded and eval 12 re-measured (36/36 at 1.11.1).

## 1.12.0 — captions people can read, in any script (shipped + evaluated, eval 13)

- **Fonts by script** (done): `caption.py`, `graphics.py` and `overlay.py --text` detect the
  writing system of the text (ja, zh, ko, ar, he, hi, th, ru, el) and resolve a font file that
  covers it from `fc-list :lang=xx` (Windows: the known system fonts), logging the one it chose.
  No font for the script is a failed job (`kind: input`) with per-OS install hints, never a
  silent page of boxes. `--lang` on caption/graphics and `"lang"` in brand.json break the
  Han-only Chinese/Japanese/Korean tie; an explicit font is always kept, with a warning when it
  does not cover the text.
- **`doctor` per language** (done): `fonts.scripts` reports available/missing/unknown plus the
  file per writing system; the plain-text `doctor` keeps it to one line.
- **Readable cues** (done): `caption.py` wraps by measured width (a per-character table for
  Latin, a per-script advance elsewhere, zero for combining marks, which stay with their base) so
  CJK, Thai and all-caps Latin lines stop overflowing the safe area; `--max-lines` (default 2)
  splits a cue that needs more, `--min-duration` (default 1.0) holds a flashed cue, `--offset
  TIME` shifts SRT, ASS and cue files in the skill's timestamp grammar. Word-level timings from a whisper JSON drive
  `--karaoke` when the transcript has them, instead of an even split.
- **brand.json caption styles** (done): `styles.caption.{font,size,colour,box,position}` gives
  every project the same look; `graphics.py` reads `font` and `colour` from the same block.
- The caption prompts (JA/EN, CJK wrap, karaoke, SRT offset) plus the per-language act/refuse
  prompts added for zh, ko, es, pt, fr, de and ar were graded by **eval 13** at 1.12.0 (done):
  50/50 on the grown set, every non-Latin caption and lower-third picking a covering font by
  itself (`evals/results/iteration-13.json`).

## 1.13.0 — the audio bed (shipped + evaluated, eval 14)

- `audio.py` (done): `--voice [light|medium|strong]` (bare `--voice` is `medium`, the chain it
  always produced), `--stereo-widen 0..1` (refused on a mono input, and on more than two
  channels unless `--downmix` folds them to stereo first), the sidechain ducking parameters exposed (`--duck-threshold`, `--duck-attack`,
  `--duck-release`, next to the existing `--duck-amount`), and `--effects FILE` /
  `--effects-volume`: a third bed that is deliberately never ducked. `--json` gains an `audio`
  block naming the duck settings the run used. `render.py` spells the levels as
  `audio.stems: {dialogue, music, effects}`, mapping to `--gain` / `--music-volume` /
  `--effects-volume`.
- `loudness.py` (done): `--lra N` documented and the measured input/output ranges reported in
  `--json` (`measured.input_lra`, `result.input_lra`, `targets`).
- `loudness.py --dialogue` was **not** shipped. It was built (silencedetect → aselect → a gated
  loudnorm measurement) and then measured against the whole-file measurement it was meant to
  correct: `loudnorm`'s EBU R128 integrated loudness already applies the −70 LUFS absolute and
  −10 LU relative gates, which drop the same blocks the speech gate dropped. On every fixture in
  the repo — including one that is half digital silence — the gated result moved by at most
  0.6 LU, inside `check.py`'s own ±1 LU tolerance, and cost a second full decode of the input.
  A flag that cannot change the delivered file by more than the tolerance it is checked against
  is not worth the pass; `references/gotchas.md#loudness-and-ambience` records it so it is not
  re-proposed.
- `check.py --platform podcast` (done) gains `chapters` (PASS with ≥ 1 marker, WARN `none`) and
  `channels` (PASS mono/stereo, WARN above — players downmix 5.1 unpredictably); both are
  informational and absent for other platforms.
- `audio.py --chapters` was **not** added: `metadata.py episode.mp4 --chapters chapters.txt`
  already writes them, losslessly, and a second spelling in a tool that re-encodes the audio
  would be the worse one. Instead `render.py` gained a `chapters` project key (a file path or
  an inline list of `{"at", "title"}`) that runs `metadata.py` on the delivered file as the
  last stage before `check`.
- The audio-only and mixed prompts were graded by **eval 14** at 1.13.0 (done): 76/76 on the
  set grown to 76 prompts (50 + 18 language + 8 delivery), `evals/results/iteration-14.json`.
  Eval 14 also found the two defects 1.14.0 and 1.15.0 answer: delivery runs paying a second
  encode because `export.py` ran without `--normalize`, and Devanagari through `graphics.py`
  (drawtext) coming out wrong-shaped.


## 1.14.0 — delivery templates (shipped + evaluated, eval 15)

Eval 14's delivery baseline: the destination is named ("make this a TikTok", 「リールにして」),
the chain behind it is always the same, and four of seven producing runs paid a second full
encode because `export.py` ran without `--normalize` first.

- `render.py --template tiktok|reels|shorts|youtube|linkedin|podcast`: one call for the whole
  chain a platform name implies (reframe, captions when cues are given, platform export,
  `check.py`), with `--normalize` on by default whenever a platform is named, so a delivery is
  one encode rather than two.
- **Blurred-background fit**: `fit.py --fit pad --pad-fill blur` as the template default for
  16:9 into 9:16, instead of two thirds black bars (the dl8 case).
- **Social pack**: `--template all` renders the same source to every vertical destination in one
  run, sharing the decode and the caption pass.
- **Sticker, hook and meme graphics** in `graphics.py`: the hook card (an opening caption on a solid or blurred plate), the
  top/bottom meme caption and the sticker-style label that short-form deliverables ask for,
  drawn from the same brand kit as the existing lower-thirds.
- `export.py` presets for shorts / tiktok / linkedin as named targets (today aliases of
  reels / youtube), `youtube-hdr` (HEVC Main10 HDR10 kept), `youtube-av1`; a preset carries its
  loudness spec so `--normalize` and `check.py` read one table.
- `look.py --best-frame` picks a thumbnail candidate by sharpness and exposure (measured, no
  content judgement) and writes it at the platform's thumbnail size; `report.py` embeds it.
- Eval 15 on the delivery prompts (`dl1`–`dl8`), three repeats, measuring the encode count per
  delivery rather than pass/fail alone.

## 1.15.0 — text people can see (shipped + evaluated, eval 16)

The defects eval 14 found in the text path. Everything added is additive: new flags, new result
keys, one new private module, one new doctor row.

- **Complex-script shaping for `graphics.py`.** The roadmap used to say "drawtext cannot shape";
  the measurement says something narrower. On a build with `--enable-libfribidi`, drawtext gets
  bidi and Arabic joining right — Arabic and Hebrew were already correct. What it cannot do on
  any build is **reorder and re-cluster** (Devanagari matras, Thai/Lao mark stacking), because it
  does not use harfbuzz even in an `--enable-libharfbuzz` build. `graphics.py --text-render auto`
  therefore renders those scripts through libass (a generated `<output>_gfx.ass`, private helper
  `scripts/_ass_overlay.py`) and reports `text_renderer: "ass"`; `--text-render drawtext` with
  such a script is a refusal naming the script, never a wrongly shaped frame. Latin, CJK and
  Arabic frames are pixel-identical to 1.14.0 (the drawtext command line changed: the label moved
  into `textfile=…:expansion=none`). `overlay.py --text` gets the refusal, and the route in 1.16.0.
- **Emoji in captions and titles.** Colour emoji through drawtext is not available at all (a
  CBDT/sbix face fails filter initialisation and writes no file), and an installed colour emoji
  font proves nothing — Noto Color Emoji is present on the dev box and libass still renders
  monochrome. So the colour route is a PNG overlay: `--emoji-assets DIR` (Twemoji/Noto PNGs named
  by code point), the ASS reserving the gap and the PNG composited on top. `doctor --json`
  `.fonts.emoji` answers what this machine can do, from a render probe. Nothing is downloaded.
- **`'` and `%` survive.** `overlay.py --text` and `graphics.py`'s labels dropped both; drawn text
  now goes to drawtext as `textfile=<path>:expansion=none`, so the graph parser never sees it.
  (`caption.py` went through libass and was already correct; there is now a regression lock.)
- **No one-character orphan lines**, and a balanced break for spaced scripts: the measured wrap
  never leaves a single character alone on a line (`th1`, `dl3`) and prefers the break that
  minimises the widest line (`dl1`).
- Eval 16 re-ran the caption and graphics prompts in every script the set covers, plus six new
  emoji/shaping prompts (`em1`–`em4`, `sh1`–`sh2`). Three of the four targets landed: Devanagari
  and Thai correctly shaped in 4/4 runs (hi1's garble is gone), emoji visible in colour in every
  run given PNG assets and reported monochrome in the one that was not, and the `Failed:` label
  rule on all three refuse-the-verb prompts. The one that did not: the caption breaker still
  splits phrases (`dl1` "A third line the tool / times for me", `dl4` a lone "subtítulos"); the
  one-character ban removed the `th1`/`dl3` orphans but not the cause. A phrase-aware breaker is
  the first item of 1.16.0.

## Refactor release after 1.15.0 — no behaviour change (shipped, eval pending)

A release of its own so that "nothing changed for a caller" is checkable in one diff: no flag,
no JSON key, no exit code, no contract field moves. The contract snapshot and the MCP snapshot
came out byte-identical, as did `--help` for all 42 tools.

- **`scripts/_common.py` is a package**: `runner` (process execution and timeouts),
  `probe` (ffprobe and the measured facts), `decision` (the copy-vs-re-encode and capability
  choices), `emit` (result documents, `die()`, `info()`), `color` (colour tags, HDR paths) and
  `text` (fonts, script detection, emoji, drawtext), which the plan did not name separately and
  which is the second-largest of the six.
  `scripts/_common/__init__.py` is a facade that re-exports all 184 names the single file
  defined, so every `from _common import ...` and every `_common.<name>` in every tool and test
  keeps working unchanged — including the ones tests rebind (`_common._FFMPEG_VERSION`), which
  the facade mirrors onto the module that defines them.
- **`tests/test_all.py` split by tool group** (analysis, editing, audio, picture, delivery,
  orchestration) with the shared fixtures in `tests/_fixtures.py`; `test_all.py` is now a
  `load_tests` aggregator over the six, so `npm test` runs the same 323 cases under the same
  names. The footage is built once per process, not once per group.
- No eval iteration of its own: the release is proved by the existing suite plus the two
  snapshots, and the next themed eval runs on top of it.

## 1.16.0 — long-form delivery (shipped + evaluated, eval 17)

- **Phrase-aware caption breaking** (eval 16 follow-up): `caption.py`/`graphics.py --wrap
  phrase|measured`, default `phrase`. Four rules over the break positions that already fit, so
  no line is widened and the line count never changes — never inside a word or on the wrong side
  of a hyphen; no lone digit, punctuation pair or single kana on its own line, at every boundary
  rather than only the last; Japanese/Chinese sentence ends preferred, a particle kept with the
  word before it (kinsoku: a line may not open with one), never a break inside a word; an article
  or preposition kept with the phrase it governs in six Latin-script languages. The
  `dl1`/`dl3`/`dl4`/`th1` cues are the regression lock, and each now breaks as one whole phrase
  per line. `--wrap measured` restores 1.15 exactly. The label lines (`Done:`/`Steps:`/`Check:`) are now stated in SKILL.md to carry the user's
  language (`dl4`, `id1`).
- **Audiogram**: `waveform.py --image` plus `templates/audiogram.json` and a `render.py`
  `audiogram` stage — an audio episode over a still or brand plate, with a title and captions.
  **No new tool** (`docs/design-decisions.md` records why), so the count stays 42, and a run with
  none of the new flags builds the same command line 1.15 did.
- **Auto chapters**: `metadata.py --auto-chapters` proposes markers from measured pauses and
  scene changes, with `--chapters-out`/`--description-out`. Every title is `Chapter N` and the
  result says `"titles": "placeholder"` — the skill proposes the timestamps, the caller names
  them.
- **Multi-language subtitle tracks**: `caption.py --mode mux --srt file:lang`, repeatable, with
  `--track-title` and `--default-track`; the result lists every stream under `tracks` and
  `check.py` gains an informational `subtitles` row.
- Eval 17 (`iteration-17.json`): audiogram 2/2, auto chapters 2/2 with `Chapter N` titles only,
  multi-language tracks correct, 16/16 delivery outputs pass their platform check, trigger 45/45,
  tokens flat. The caption breaker, though, **does not get to act** at the platform caption
  sizes: at TikTok/Shorts size a line holds about 6 em, a five-word cue cannot fit two lines,
  and `caption.py` splits it into two-line cues exactly as 1.15.1 did (byte-identical ASS on
  `cw1`, `dl1`, `dl4`). Thai still breaks inside words in both versions (no dictionary), and
  1.16.0's balancing moves that break towards the middle of the run; a katakana word gets split
  (`タイ|ミング`). The `dl3` orphans are gone. Follow-ups: 1.16.1 (shipped: a Thai run is one atom, broken only at a space
  or `|`; a katakana word is one atom; `caption.py` counts lines wider than the safe width as
  `overlong` and names the fix) and, in 1.17.0, a caption size that fits the cue before the
  cue is split.

## 1.17.0 — throughput (shipped + evaluated, eval 18)

- **Done. `caption.py --fit-size`**: the caption size is fitted to the cue *before* the cue is
  split. This is the rest of the eval-17 answer and belongs at the top of this section: the
  breaker was never the problem at a platform caption size, the size was. `auto` (the default)
  shrinks only a size the skill itself chose, `off` is 1.16.1 byte for byte, `--min-size` is the
  4.5 %-of-frame-height floor, `--fit-size-scope cue` is the opt-in per-cue form. The text is
  never rewritten to make it fit.
- **Done. `silence.py --filler`** removes filler words when word timings are available (whisper
  stays optional: no transcript, no filler removal, and the tool says so, with the install lines).
- **Done. Beat-synced cuts**: `scenes.py --beats` measures the grid, `cut.py --snap beats` and
  `render.py`'s project `"snap"` move in/out points onto it, and below `--min-confidence` the
  cut refuses rather than snapping to a grid nothing in the audio supports. The beat list, the
  tempo and the confidence are reported so the caller can see what it snapped to.
- **Done. `batch.py --jobs N`** runs independent items in parallel under one `--timeout` budget.
  `--watch` composes with it. (`--resume` was not built: the existing content-hash cache already
  skips items whose output is there, so a second flag for it would be a second spelling.)
- **Done. `render.py --cache DIR`** keys unchanged stages on the content hash of their inputs and
  arguments plus the ffmpeg, skill and contract versions, so changing the export preset re-runs
  export only; `--from STAGE` alongside the existing `--stop-after`. Opt-in: no default directory.
- Eval 18 (`iteration-18.json`), 100 prompts: language 100/100, report format 98/100, trigger
  50/50 including one new prompt per 1.17 feature, tokens flat (74.7k → 73.3k on the 87 prompts
  both iterations ran), Opus quality mean 3.71 against 4.17. `batch.py --jobs` is 2/2 with the
  cap reported, `render.py --cache` routed and then refused honestly when an ffmpeg upgrade
  invalidated every key, `cut.py --snap beats` and `scenes.py --beats` are correct where they
  were used. Two findings, and both are about reach rather than about the code:
  **the size fitter never runs on the path the captioned prompts actually take** — `render.py`
  fills the caption size from the platform table and forwards it as an explicit `--size 24`, so
  `caption.py` treats the size as user-stated and `--fit-size auto` declines to shrink it; the
  `cw1`/`dl1`/`dl3`/`dl4` splits are unchanged from eval 17, no `size_used` or `shrunk` key
  appears in any of those reports, and the project schema rejects the key outright (`unknown key
  fit_size`). The one run that called `caption.py --fit-size on` by hand got 24 → 16, `shrunk` 2,
  `split` 0 and three intact cues, at 102k tokens and 28 tool calls. And **SKILL.md names none of
  this**: zero occurrences of `filler`, `beat`, `BPM`, `--snap beats`, `--words`, `--jobs` or
  `--cache` in 29,992 bytes, so `--snap beats`, `scenes.py --beats`, `silence.py --filler` and
  `render.py --cache` were each used in exactly one run of the hundred, one agent wrote that the
  skill has no beat detection and cut at the literal timestamps, and two rebuilt filler removal
  by hand with `cut.py --segments` (leaving the output VFR). 1.17.1 is the patch.

## 1.17.1 — the eval-18 patch (shipped + evaluated, eval 19)

- **Done. The template path fits the caption size.** 1.17.0's fitter was unreachable from
  `render.py --template`: the template fills the caption size from the delivery table and
  forwarded it as an explicit `--size`, which is the signal `caption.py` reads as "a human chose
  this", so `--fit-size auto` stood down and the cue was split instead (eval 18 cw1/dl1/dl3/dl4).
  The filled project states `"fit_size": "on"`; a template's own `fit_size` and a `--brand`
  caption size still win, and `"fit_size": "off"` is 1.17.0 byte for byte.
- **Done. Project captions take `fit_size`, `min_size`, `fit_size_scope`** (eval 18 cs1 could not
  state the policy in a project and hand-ran the four stages), and `render.py` reports the caption
  stage's block as `caption`.
- **Done. SKILL.md routes the 1.17 features** — filler, beats, `--jobs auto`, `--cache` — after
  eval 18 found none of them in the routing table (bt2 even reported the skill has no beat
  detection). Paid for with duplicated wording, inside the 30,000-byte budget.
- **Done. One label for a partial result**: `Done:` with the shortfall in `Notes:`.
- **Done. `caption.py` reports `text_unchanged`** and says "caption text unchanged" in its summary
  when it burned the cues exactly as given.
- **Done. Eval fixtures** stage a batch recipe's `output_dir` absolute (eval 18 bp1/bp2).
- **Eval 19 (`iteration-19.json`) graded it**: 26 runs over cw1/cw2, dl1/dl3/dl4, cs1-3, bt1-3,
  fw1-3, bp1-2 and rc1-2, with cw1/dl1/dl4/cs1 repeated three times each, plus the trigger set.
  Every target above was met. `--fit-size` fires on the template path in 12/12 caption runs
  (cw1/dl1/cs1 24 → 16, dl4 to the 13-unit floor, `split` 0, `text_unchanged` true, identical per
  id across all three repeats, and the rendered media byte-identical between reps); no run met
  `unknown key fit_size`; `fw1`/`fw3` route to `silence.py --filler --words` on the first try where
  eval 18 rebuilt them by hand as `cut.py --segments`; `bt2` quotes its measured 0.184 confidence
  against the 0.5 threshold instead of asserting the skill has no beat detection; `bp1`/`bp2` use
  `--jobs` with the cap disclosed and no fixture rewrite; report format is 26/26 with no third
  label anywhere. Language 26/26, routing 23/26, honesty 24/26, trigger 50/50, Opus quality mean
  3.65 against 3.71, and tokens fell from 81.0k to 78.3k on the same 18 ids (cs1 alone −18%, now
  that the template reaches the fitter and no hand-built chain is needed).
- **And the finding that outlives the patch**: the picture is unchanged. `caption.py`'s
  `write_ass` computes one `margin = round(args.margin * scale)` and writes it into `MarginL`,
  `MarginR` *and* `MarginV`. `args.margin` is the platform's **vertical** safe margin in ASS units
  (tiktok 63, shorts 52), which scales to 420 px, so at `PlayResX` 1080 the text column is 240 px
  and libass wraps every word — "Hello world" renders as "Hello" over "world". The fitter budgets
  `play_w × 0.9`, which is why `split: 0` and `text_unchanged: true` are true of the ASS text and
  false of the frame, and why shrinking cannot rescue it (dl4 reaches the floor and still stacks).
  It is the generated-ASS path only (`--animate`/`--karaoke`, which every delivery template uses);
  the plain SRT path sets `MarginV` alone through `force_style` and is correctly typeset. Present
  since 1.14 introduced the platform margins, and it explains eval 17's and eval 18's "one word per
  line" as well — both of which were patched at symptoms of this line. 1.17.2 is the patch.

## 1.17.2 — the caption-margin patch (implemented, not tagged yet)

- **Done. The caption Style's side margins are the horizontal safe zone.** Since 1.14 `write_ass`
  wrote `--margin` — the *vertical* safe margin, 63 ASS units = 420 px at TikTok geometry — into
  `MarginL` and `MarginR` as well, leaving libass a 240 px column on a 1080-wide frame: "Hello
  world" was drawn as "Hello" over "world" while the fitter and the wrapper measured the
  horizontal safe width and reported no wrap at all (eval 19 headline; dl4's Spanish cues hit the
  13-unit floor and still stacked). `MarginL`/`MarginR` now come from `safe.left`/`safe.right`,
  or from the conventional 5 % border with no `--platform`, and `line_em_for_size`/`fit_size`
  use exactly `play_w - MarginL - MarginR`. The SRT `force_style` path is unchanged.
- The pinned `--fit-size off` fixture was re-pinned: it carried the wrong margins. A behaviour
  change to fix a defect, with the CHANGELOG line the stability paragraph of `docs/contract.md`
  asks for.

- **Regression tests on the ASS path** (`tests/test_picture.py`): the Style row's `MarginL` and
  `MarginR` equal the platform's safe zone at tiktok geometry, the generated ASS for "Hello world"
  at `--platform tiktok` contains no `\N`, and the rasterised frame carries exactly `\N + 1` text
  bands for the cw1 cues — the picture, not the fit stats.
- **Not in this patch, carried to the next docs/skill change**: the SKILL.md refusal line "never
  rewrite, shorten or paraphrase the user's caption text; offer `--max-lines` or a smaller size"
  (`cs3` took the forbidden path in evals 17, 18 and 19). Whether `silence.py --filler` should
  leave silences alone unless asked (eval 19 fw1/fw3) is a 1.18.0 decision, not a patch.
- **Eval 20** re-runs the caption set, three repeats each, and grades the caption prompts on the
  contact sheet rather than on the fit stats.

## 1.18.0 — measured analysis and multicam at scale (still no judgement) (planned)

- `scenes.py --shots` labels each shot static / pan / motion by measured optical flow;
  `--audio-peaks` and `--speech` (speech-vs-music energy ratio) as separate lists.
- `silence.py --speech-aware` keeps breaths shorter than `--min-silence` inside a sentence and
  cuts only between sentences (measured pauses), with the cut list as EDL. It composes with 1.17's
  `--filler`: one removal list, one graph — sentence-boundary pauses and timed filler words go
  through the same `keep_ranges()`.
- `cropdetect.py --motion-centre` reports the motion centroid per second for a 9:16 reframe
  that the calling agent decides on (the skill reports the number; it does not pick the subject).
- `sync.py` accepts 3+ sources (one reference, N seconds) and writes one offsets JSON;
  drift correction reports the measured ppm and where it resampled.
- `multicam.py --switch energy` cuts to the loudest camera's audio with a minimum shot length;
  `--edl` exports the cut list for an NLE; the timeline is a `render.py` project so it can be
  re-rendered with different minimum shot lengths.
- Eval 19 on analysis and multicam prompts, scored against hand-labelled ground truth; a
  real-device multicam corpus (phone + camera + lav).

## 1.19.0 — observability, portability, a smaller MCP surface (planned)

- `--trace FILE` (common flag): one JSON line per ffmpeg run with wall time, encode fps,
  speed, exit code, bytes written; `result_v2.metrics` carries the same for the whole tool.
- `report.py` before/after frame pairs at the same timestamps, loudness and true-peak
  graphs, and the plan/verify chain when a plan was executed.
- `verify.py --install` checks the install itself (ffmpeg build, encoders, fonts, whisper) and
  prints the fix per missing capability, using the contract's capability list.
- Windows: paths with spaces and non-ASCII fonts through every filter (fontconfig escaping
  audit), long-path support; the Windows CI job runs the full real-device corpus, which closes
  issue #143.
- ffmpeg 8 / 9: filter and encoder fixtures refreshed, `bt709_tag_args` and the colour
  negotiation path re-verified on each; a compatibility table in `references/devices.md`.
- `--hwaccel auto` (opt-in): videotoolbox / vaapi / nvenc for previews (`--fast`) only,
  never for the final encode unless `--hwaccel final` is given, with the encoder named in the
  result so a difference is traceable.
- **MCP: core 12 tools, the rest lazily.** A 42-tool `tools/list` costs a client's context on
  every session for tools most sessions never call. The default listing becomes the core 12
  (`probe`, `cut`, `join`, `fit`, `caption`, `audio`, `loudness`, `export`, `check`, `look`,
  `render`, `doctor`/`contract`); the other 30 stay reachable and are fetched through the
  contract on demand. The contract itself still describes all 42 — nothing is removed from the
  surface, only from the default listing.
- Eval 20 on the Windows and macOS runners; it also grades whether agents quote the metrics
  rather than re-probe.

## 1.20.0 — agent ergonomics (planned)

- SKILL.md rewritten from evals 8–20: **the request table regrouped by intent** (the clusters
  people actually ask in — shorten, reframe, caption, fix the audio, deliver, inspect — rather
  than by script name), the language and report rules moved to the top, the gotchas list pruned
  to the ones still hit.
- MCP: `tools/list` descriptions shortened to one line each (the schemas are unchanged), a
  `prompts` capability with the five workflows (reel, podcast, multicam, delivery check, HDR).
- `contract --json` gains `examples` per tool (the SKILL.md table rows, machine-readable).
- Eval 21: trigger set doubled, plus "second-turn" prompts where the agent must continue an edit
  from a previous result document.

## 1.21.0 — the 2.0 freeze (planned)

- Everything 2.0 removes is announced (`deprecated` in the contract, `--help`, CHANGELOG) for
  at least one minor; `docs/migrating-2.0.md` maps every old spelling to the new one.
- `contract_version` 1.1: `deprecated`, `examples`, `metrics` documented; the real-device
  corpus and every eval set re-run on the tree; ninth audit pass.
- No new options after 1.21.0 on 1.x: 1.21.x is fixes only while 2.0.0 is prepared.

## 2.0.0 (planned, after 1.21.x settles)

Manual `package.json` bump in one PR (the release workflow never picks a major). It removes
the deprecated spellings, promotes `result_v2` to the top level, makes `ctx` required, renames
`hdr`, flips the overwrite default, and drops `json` / `progress` from MCP. Nothing else.

## Not planned

- A feature that needs 2.0: features land in 1.x behind flags (1.4.0, 1.6.0, 1.7.0 did).
- A new tool where an option on an existing one fits: the 42-tool table is the contract's
  surface, and adding a tool is allowed but is the last resort (none is planned above).
