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

The released version today is **1.15.0**, shipped and evaluated: **eval 16**
(`evals/results/iteration-16.json`) graded it on the 82-prompt set, the 76 plus the six
emoji/shaping prompts. Everything after 1.15.0 is planned.

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
| 1.16.0 → 1.21.0, 2.0.0 | planned | — |

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

## Refactor release after 1.15.0 — no behaviour change (planned)

A release of its own so that "nothing changed for a caller" is checkable in one diff: no flag,
no JSON key, no exit code, no contract field moves. The contract snapshot and the MCP snapshot
must come out byte-identical.

- **`scripts/_common.py` becomes a package**: `runner` (process execution and timeouts),
  `probe` (ffprobe and the measured facts), `decision` (the copy-vs-re-encode and capability
  choices), `emit` (result documents, `die()`, `info()`) and `color` (colour tags, HDR paths).
  `scripts/_common/__init__.py` is a facade that re-exports today's names, so every
  `from _common import ...` in every tool and test keeps working unchanged.
- **`tests/test_all.py` splits by tool group** (analysis, editing, audio, picture, delivery,
  orchestration) with the shared fixtures in one place; `npm test` still runs the same set.
- No eval iteration of its own: the release is proved by the existing suite plus the two
  snapshots, and the next themed eval runs on top of it.

## 1.16.0 — long-form delivery (planned)

- **Phrase-aware caption breaking** (eval 16 follow-up): the wrap never splits inside a word or
  between a determiner and its noun, and balances lines by measured width; the `dl1`/`dl3`/`dl4`
  cues become the regression lock. The label lines (`Done:`/`Steps:`/`Check:`) are stated in
  SKILL.md to be part of the user's-language report (`dl4`, `id1`).
- **Audiogram**: a `waveform.py` / `render.py` template that turns an audio episode into a
  shareable video (waveform or spectrum over a still or brand background, captions burned in).
- **Auto chapters**: chapter markers proposed from measured structure (silence spans and scene
  changes), written by `metadata.py` — the skill proposes the timestamps, the caller names them.
- **Multi-language subtitle tracks**: `caption.py --mode mux` takes more than one subtitle file
  and tags each stream with its language, so one deliverable carries several tracks.
- Eval 17 on long-form and podcast prompts.

## 1.17.0 — throughput (planned)

- `silence.py --filler` removes filler words when a transcript is available (whisper stays
  optional: no transcript, no filler removal, and the tool says so).
- **Beat-synced cuts**: measured onsets from the music bed as a cut grid `cut.py`/`render.py`
  can snap to; the beat list is reported so the caller can see what it snapped to.
- `batch.py --jobs N` runs independent items in parallel under one `--timeout` budget;
  resumable (`--resume` skips items whose output verified); `--watch` folders.
- `render.py` caches unchanged stages by content hash of inputs and stage arguments, so
  changing the export preset re-runs export only; `--stop-after` and `--from STAGE`.
- Eval 18 measures wall-clock and encode counts on the delivery and batch prompts (the number,
  not just pass/fail).

## 1.18.0 — measured analysis and multicam at scale (still no judgement) (planned)

- `scenes.py --shots` labels each shot static / pan / motion by measured optical flow;
  `--audio-peaks` and `--speech` (speech-vs-music energy ratio) as separate lists.
- `silence.py --speech-aware` keeps breaths shorter than `--min-silence` inside a sentence and
  cuts only between sentences (measured pauses), with the cut list as EDL.
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
