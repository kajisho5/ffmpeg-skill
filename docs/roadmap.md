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

The released version today is **2.1.0** — `render.py --export-timeline` hands the cut to an
editor as FCPXML, CMX 3600 EDL or OpenTimelineIO (clips, speed, dissolves, music bed, chapter
markers; everything else listed as `not_exported`), plus the eval-24 follow-up that stops
`export.py` calling a BT.2020 SDR source HDR. 2.0.0 made the five changes 1.10.0 announced
(docs/contract.md "What 2.0 changed"). Tool count still 42.

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
| 1.17.2 | shipped, evaluated (eval 20) | eval 20 at 1.17.2 (`iteration-20.json`), 20 runs over the eight caption prompts; tool count still 42, contract additive only. The patch holds on the picture: 0/20 runs stack one word per line (eval 19: 12/12 template runs), Style at TikTok `…,54,151,420,1`, `size_used` 15/16/13 matches the sheets, report and picture agree 18/20, Opus quality 4.25 (3.65). Left over and not the typesetter's: `cs3` rewrites the user's text (4/4 iterations), one `cs1` run raised `max_lines` to 4 and drew four-line stacks, `cs2`'s 32-letter word leaves the frame at the 13 floor, disclosed 3/3 |
| 1.17.3 | shipped, eval pending | two SKILL.md rules from eval 20, no code: the cue text is burned as written (never rewrite, shorten or paraphrase it, even when asked to "make it fit" — `cs3`, 4/4 iterations), and on a vertical delivery keep the template's `--max-lines` and let the size drop (rep3/cs1 raised it to 4 and drew four-line stacks). SKILL.md trimmed elsewhere to stay under 30,000 bytes; tool count still 42, contract unchanged |
| refactor after 1.17.3 | shipped, eval pending | `_common/text.py` (1,655 lines, 111 top-level definitions) split into `fonts.py`, `emoji.py`, `drawtext.py` and `wrap.py`, with `text.py` a re-export shim; contract + MCP snapshots and every `--help` byte-identical, no behaviour change; 596/596 tests |
| 1.18.0 | shipped, evaluated (eval 21) | `scenes.py --shots`/`--audio-peaks`/`--speech`, `cropdetect.py --motion-centre`, `silence.py --speech-aware` (composes with 1.17's `--filler` through one `keep_ranges()`), `sync.py` N≥1 sources (the `second` positional kept exactly, additive `more_sources`), `multicam.py --switch energy`/`--edl`/`--min-shot`; tool count still 42, contract and MCP snapshots additive only. 1109/1109 tests. Eval 21 at this version found every tool correct and none discoverable — SKILL.md named zero of the five flags. 1.18.1 is the fix |
| 1.18.1 | shipped, evaluated (eval 22) | routing rows for `scenes.py --shots`/`--audio-peaks`/`--speech`, `cropdetect.py --motion-centre`, `silence.py --speech-aware`, and an extended `multicam.py` row for `--switch energy` — no script changes. SKILL.md trimmed elsewhere (same style as 1.17.3) to stay under 30,000 bytes: 29,998. `CHANGELOG.md`'s caption side-margin write-up had also been left under the `1.17.1` heading instead of `1.17.2`, where that behaviour (#239) actually shipped; corrected, docs-only, no version bump |
| 1.18.2 | shipped, evaluated (eval 22) | README's tool table named none of the five 1.18.0 flags or `sync.py`'s additive extra-source positionals or `multicam.py --switch energy`; added the same one-liner facts already in SKILL.md since 1.18.1. No script changes |
| 1.18.3 | shipped, evaluated (eval 22) | MCP `tools/list` defaults to the core 12 (`render`, `look`, `caption`, `export`, `check`, `fit`, `cut`, `audio`, `loudness`, `graphics`, `silence`, `probe`, chosen from eval 17-20's `expect`-field frequency), opt-in to the full 42 via `FFMPEG_SKILL_MCP_FULL=1`; every tool stays callable by name through `tools/call` either way, `contract --json` still describes all 42. Tool count still 42, CLI/MCP argument names unchanged |
| 1.18.4 | shipped, eval pending | eval 20's `cs2` (a 32-letter Spanish word still clipping the frame at `--min-size`): `scripts/_common/wrap.py` slices an atom at the column edge (preferring an existing hyphen) only when it does not fit alone even at the floor; `caption.py`'s burn path reports the new `broken_inside_word` stats key. A fitting Thai phrase or katakana run (1.16.1) is provably unchanged — the slice branch is unreachable for an atom that already fits. No new CLI flag, no script added, tool count still 42 |
| 1.19.0 | shipped, eval pending | `multicam.py --write-project FILE` (eval 21's `mc2` gap): writes a `render.py` project whose `clips[]` reproduces multicam's own cut decision exactly (`src`/`in`/`out` per cut, offset-shifted to each camera's own timeline), for `--switch energy`, a manual `--switch` spec, or `--auto` alike; multicam's own combined render and `--edl`/`--offsets-only` unchanged. `feat:` release, hence the minor bump — not the start of the "1.19.0" theme further down this document, which is unrelated and still planned |
| 1.19.1 | shipped, eval pending | eval 19's `fw1`/`fw3`: `silence.py --filler` alone (no `--speech-aware`) jump-cut unrelated dead-air silence gaps too, ~5s unasked. Fixed: generic silence detection is skipped unless `--speech-aware` is also given, so `--filler` alone removes only the timed filler-word spans; `--speech-aware` alone and `--filler --speech-aware` combined are unchanged |
| 1.19.2 | shipped, docs-only | SKILL.md rows for 1.18.3's MCP core-12 (previously undocumented) and 1.18.4's overlong-word column-edge slice, plus this document's own roadmap truth-up. No script changes |
| 1.19.3 | shipped, eval pending | `graphics.py`'s `wrapped()` helper (used by the lower-third, title, sticker, hook and meme templates) turns on the same `slice_overlong` escape hatch `caption.py` turned on in 1.18.4, so a single unbreakable overlong atom drawn through a template no longer renders past the frame's safe width. `broken_inside_word` reported the same way as `caption.py`. A fitting Thai phrase or katakana run is unchanged, guarded by the same font-availability skip as `ShapingTests`. Tool count still 42, no new CLI flag for this change specifically -- `look.py --ink` is a separate, not-yet-versioned addition tracked in its own PR |
| 1.20.0 | shipped, eval pending | `look.py --ink` (#261): measures the count and fraction of non-background pixels in a PNG (a still frame, a burned caption/graphics overlay, or a `--compare` side-by-side image), pixel-scan only -- no new dependency. `feat:` release, hence the minor bump. Tool count still 42 |
| 1.21.0 | shipped, eval pending | `contract --json` gains `examples` per tool (#267): `scripts/_contract.py` parses SKILL.md's own "User says" / "Do" request table into `{tool_name: [{prompts, command}]}`, cached, so every one of the 42 tools has at least one machine-readable example that can't drift from the table a person reads. `feat:` release, hence the minor bump -- not the start of the "1.21.0: the 2.0 freeze" heading further down this document. Tool count still 42 |
| 1.22.0 | shipped, eval pending | `batch.py` reports `cut.py`'s stream-copy vs hybrid re-encode rate across a folder (#269): `run_step()` reads each step's own `--json` result document back (previously only used for its output path), and rolls `cut.py`'s per-call `reencoded` into one `cut_stream_copy` summary (`{calls, stream_copy, reencoded, stream_copy_rate}`). `feat:` release, hence the minor bump. Tool count still 42 |
| 1.23.0 | shipped, eval pending | MCP `tools/list` descriptions shortened to one line each (#271): `MCP_STRUCTURED_NOTE` used to be appended to every one of the 42 descriptions verbatim; it now goes once into `initialize`'s `instructions` field instead. Additive/no-op for `tools/call` and `inputSchema`; the frozen 1.x MCP snapshot doesn't track descriptions. `feat:` release, hence the minor bump. Tool count still 42 |
| 1.24.0 | shipped, eval pending | MCP `prompts` capability with five workflow recipes (#272): `reel`, `podcast`, `multicam`, `delivery_check`, `hdr`. `initialize` advertises `capabilities.prompts`; `prompts/list`/`prompts/get` fill a template built from facts SKILL.md's own request table already states -- recipes, not new tool calls, every command line named is one `tools/call` (or the CLI) can already run. `feat:` release, hence the minor bump. Tool count still 42 |
| 1.24.1 | shipped, evaluated (eval 23b) | `caption.py --karaoke-style word` (#276, #278): one ASS Dialogue event per word, active word scaled by `--karaoke-scale` (default 112%) and emboldened, past/upcoming words coloured -- not a colour-only sweep. `loudness.py`'s stream-copy branch gains `-movflags +faststart` (#277, #275), fixing a `render.py --template ... --normalize` delivery that lost faststart. Eval 23b's `kw1`/`ff1` prompts (`evals/results/iteration-23b.json`) confirm both for real: the generated ASS carries `\fscx112\fscy112` on the active word, and a loudness-normalised template-youtube delivery still has `moov` before `mdat`, with `check.py`'s loudness/true-peak rows PASS |
| 1.25.0 | shipped, evaluated (eval 23b) | `chore:` release bump; closes the remaining mp4 stream-copy paths over to `-movflags +faststart` (#279). No script API change, tool count still 42. Covered by eval 23b alongside 1.24.1 -- same faststart code path, no regression found |
| 2.0.0 | planned | — |

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

## 1.17.2 — the caption-margin patch (shipped + evaluated, eval 20)

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
- **Eval 20 (`iteration-20.json`) graded it**: 20 runs over cw1/dl1/dl3/dl4/cs1/cs2 x3 plus cs3
  and rc1, every contact sheet opened and the lines per cue counted. 0/20 runs stack one word per
  line (eval 19: every template run); `size_used` 15 on TikTok, 16 on Shorts, the 13 floor for the
  Spanish cues, and the sheets show those sizes on one or two balanced lines. Report and picture
  agree in 18/20; the two exceptions are agent choices — cs3 rewrote the cues again and one cs1 run
  raised `max_lines` to 4 to keep size 24, drawing four-line stacks it did not mention. rc1 with a
  real captions stage used `--cache`, found nothing to reuse and said so. Tokens on the shared ids
  91,085 → 86,993. Two SKILL.md lines follow (never rewrite the user's captions; keep the
  template's max-lines and let the size drop) as a docs change, and one 1.18.0 design item: a word
  wider than the column at the floor (`cs2`'s 32 letters) must break at the column edge instead of
  leaving the frame.

## 1.17.3 — two caption rules in SKILL.md (shipped, eval pending)

- **The words in a caption belong to the user.** A bullet in "what this skill does not decide":
  cue text is burned as written; too long for the frame means a smaller size, `--max-lines`, or
  the user's own edit, never a rewrite — even when the request asks for one (`cs3` rewrote in evals
  17, 18, 19 and 20; the prose elsewhere in the file never said it in those words).
- **Keep the template's `--max-lines` and let the size drop.** The caption routing row says so:
  raising `max_lines` to dodge a shrink stacks two words per line (eval 20 rep3/cs1).
- No script changes. SKILL.md lost one gotcha bullet (even dimensions and rotation tags, both
  automatic) and a few parentheticals to stay under the 30,000-byte budget. Eval 21 at 1.18.0
  re-runs cs1 and cs3 to check both lines land.

## 1.18.0 — measured analysis and multicam at scale (still no judgement) (shipped, evaluated, eval 21)

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
- Eval 21 on analysis and multicam prompts, scored against hand-labelled ground truth; a
  real-device multicam corpus (phone + camera + lav).

**Done, as written above**, with two implementation notes: `sync.py`'s `second` positional
argument was kept exactly as-is rather than renamed to a list (`_contract.py` introspects argparse
dests directly into the MCP `inputSchema`, so a rename would have broken the CLI/MCP stability
guarantee) — a new optional `more_sources` positional carries the extra cameras/recorders instead,
and a 1-source run keeps the original 2-source JSON shape with the same numbers additively
available under `sources`. A multicam `--switch energy` timeline needed no new `render.py` project
stage — it maps onto the existing `clips[]` array. The caption word-too-wide-for-the-frame item
from 1.17.2's eval (`cs2`, a break-at-the-column-edge escape for the 1.16.1 keep-the-run-whole
rule) is still unaddressed and is not part of this section — it stays an open design item for a
future release.

- **Eval 21 (`iteration-21.json`) graded it the day it shipped**: 12 synthetic prompts (no real
  cameras or footage available in this environment; the roadmap's real-device multicam corpus has
  not run — carried forward, same as issue #143), one per new flag plus a re-check of `cs1`/`cs3`.
  The tools measured correctly every time they were reached: both sync offsets (2.5 s and 1.18 s,
  both within 0.15 s), the shot label on a panning clip, the multicam switch point and its
  render-project mapping (verified by dry-running a hand-built project.json against multicam's own
  cuts), and both 1.17.2/1.17.3 rechecks. What was not reached: `scenes.py --audio-peaks` and
  `--speech`, `cropdetect.py --motion-centre` were each refused by an agent that read SKILL.md end
  to end and, correctly finding no routing row, declined to guess rather than fabricate a number —
  the honest failure mode, but a failure mode all the same. `silence.py --speech-aware` reached a
  correct result without the flag, by luck of one fixture's specific silence durations, which would
  not generalise. Grep confirmed the cause: SKILL.md named none of the five 1.18.0 flags anywhere.
  1.18.1 is the fix.

## 1.18.1 — SKILL.md routing for the five 1.18.0 flags (shipped, evaluated, eval 22)

- **Done.** Routing rows added for `scenes.py --shots`/`--audio-peaks`/`--speech`,
  `cropdetect.py --motion-centre`, `silence.py --speech-aware`, and the existing `multicam.py`
  row extended for `--switch energy`. No script changes; `tests.test_contract -k skill` and the
  orchestration SKILL.md size test pass. SKILL.md trimmed elsewhere (a parenthetical tightened
  here, a clause shortened there — the same style 1.17.3 used, not a change of meaning) to make
  room under the 30,000-byte budget: 29,998 bytes.
- **CHANGELOG.md attribution.** The caption side-margin write-up had been left under the
  `1.17.1` heading; it moved to `1.17.2`, where that behaviour (#239) actually shipped.
  Docs-only, no version bump.
- **Evaluated.** Eval 22 (`evals/results/iteration-22.json`) wrote eight new symptom-only
  prompts for the five 1.18.0 flags, naming no flag: 7/8 routed correctly on the first try
  (`scenes.py --shots`, `cropdetect.py --motion-centre`, `silence.py --speech-aware`, `sync.py`'s
  N-source form, `multicam.py --switch energy`, plus Japanese and Spanish variants of two of
  them), against eval 21's 4/9 at 1.18.0's own release. The eighth (`--filler` composed with
  `--speech-aware`) is a partial for a content reason, not a routing miss — see follow-ups.

## 1.18.2 — README routing for the five 1.18.0 flags (shipped, evaluated, eval 22)

- **Done.** SKILL.md already carried the routing rows from 1.18.1; README's own tool table named
  none of the same five flags, `sync.py`'s additive extra-source positionals, or `multicam.py
  --switch energy`. Added the identical one-liner facts to README, matching its existing style.
  No script changes.
- **Evaluated.** Covered by eval 22 alongside 1.18.1 — see above.

## 1.18.3 — MCP default tools/list is the core 12 (shipped, evaluated, eval 22)

- **Done.** `docs/design-decisions.md`'s P1-7 decision shipped: `mcp/server.py`'s `tools/list`
  now defaults to `scripts/_contract.py::MCP_CORE_TOOLS` — `render`, `look`, `caption`, `export`,
  `check`, `fit`, `cut`, `audio`, `loudness`, `graphics`, `silence`, `probe` — chosen from eval
  17-20's `expect`-field frequency, not taste. `FFMPEG_SKILL_MCP_FULL=1` opts back into all 42,
  unchanged from prior behaviour; every tool stays callable by name through `tools/call`
  regardless, and `contract --json` still documents all 42. Tool count still 42; no CLI/MCP
  argument renamed or removed.
- **Evaluated.** Eval 22 re-ran `cs1`/`cs3` (x3 each) on the tree carrying this change to confirm
  the caption-honesty fixes (1.17.2/1.17.3) still hold after it: they do, 6/6.

## 1.18.4 — the caption escape hatch (shipped, eval pending)

- **Done.** Eval 20's `cs2` finding (a single unbreakable 32-letter Spanish word still wider than
  the column at `--min-size`, clipping past both frame edges) is fixed. `scripts/_common/wrap.py`
  adds `_slice_atom`: when an atom lands alone on a line and is still too wide after every other
  mechanism (wrapping, the size shrink), it prefers cutting after the atom's own existing hyphen
  when that fits, otherwise hard-slices at the widest prefix that measures within the column. No
  dictionary, no linguistic awareness, no rewriting — the pieces concatenate back to the exact
  original characters. `caption.py`'s burn path (`layout_cues`) is the one call site that turns
  this on; it reports the new `broken_inside_word` stats key, separate from `overlong` (which now
  fires only in the residual case of a single character alone wider than the column). A fitting
  Thai phrase or katakana run (1.16.1) is provably unaffected: the slice branch is unreachable for
  an atom that already fits, proven by a test running both with the hatch enabled. No new CLI
  flag, no script added, tool count still 42.
- **Not yet evaluated.** A future eval should re-run `cs2` against real ground truth (an
  independent grader opening the produced stills, not a self-report) to confirm the word no
  longer clips in practice, not just in the unit tests.

## Cross-vendor eval runner (shipped, evals/docs/tests only, no version bump)

`evals/run.py` grades any transcript file against `evals/tasks.json` (the 29-prompt
routing/refusal set) or the fuller `agent_prompts_24.json`/`agent_prompts_exec.json` sets with
substrings and `re.search` only — no `claude` CLI, no LLM-judge call, no dependency on any
particular vendor's model anywhere in the grading path. `--prompts` selects the corpus, `--json`
gives machine-readable output, and an `expect` slot's `a|b` alternation plus the existing
`grader_expect`/`grader_not` regexes are graded the same way whether the transcript came from
Claude Code, Cursor, Codex, or another harness. `evals/README.md`'s "Running this from Cursor,
Codex, or another harness" section documents the walkthrough end to end — how to get the
prompts, run them in another harness, save a transcript, grade it, and how to read the result:
what regex-only grading can and can't tell you, and why a cross-vendor pass rate is not directly
comparable to this repo's own `evals/results/iteration-*.json` numbers (different agent, different
grader script, in places a different corpus subset — see that section's "Comparing results across
vendors"). This closes `docs/design-decisions.md`'s P1-8 ("at least one routing run on a
non-Claude model") on the tooling side; no cross-vendor number is published here yet because the
maintainer cannot run another vendor's model from this environment, which is stated rather than
worked around. `scripts/`, the contract, and MCP are unchanged — this is dev-tooling only, so it
carries no version bump and no CHANGELOG entry.

MCP's `tools/list` defaulting to the core 12 — the other roadmap item this same review pass
checked — was already shipped and documented: see the **1.18.3** row above and 1.19.2's SKILL.md
truth-up. No further action was needed there.

## 1.24.1 / 1.25.0 — karaoke-style word + the remaining faststart paths (shipped, evaluated, eval 23b)

- **Done.** `caption.py --karaoke-style word` (#276, #278): `sweep` (default) keeps today's `\kf`
  colour-fill, one Dialogue event per cue; `word` instead emits one Dialogue event per word, the
  active word scaled by `--karaoke-scale` (default 112%) and emboldened, past words in `--color`,
  upcoming words in `--upcoming-color`. `loudness.py`'s stream-copy branch gained
  `-movflags +faststart` (#277, #275), and 1.25.0 closes the same flag over the remaining
  mp4 stream-copy paths repo-wide (#279). No new CLI surface beyond `--karaoke-style`,
  `--highlight-color`/`--upcoming-color`/`--karaoke-scale`/`--karaoke-timing`; tool count still 42.
- **Evaluated (eval 23b, `evals/results/iteration-23b.json`), continuing eval 23 which closed
  partial at 1.19.3 (`iteration-23-partial.json`).** Two new real-execution prompts (`kw1`, `ff1`)
  were added to `evals/agent_prompts_24.json` and run for real (actual ffmpeg encodes) against the
  live scripts, graded with `evals/grade_runs_24.py` (the same regex grader Set A/B/C used, not a
  fabricated score): `kw1` asks for word-level karaoke where "the active word should get bigger,
  not just change colour" (the #276 reporter's own words) — routed to `caption.py --karaoke-style
  word`, and the generated ASS carries `\fscx112\fscy112` on the active word, confirming the size
  bump is real, not just a colour change. `ff1` is a template-delivery prompt through
  `render.py --template youtube` (fit → `loudness.py -I -14 --tp -1` → export → `check.py`):
  faststart holds through the loudness-normalize re-encode (`moov` before `mdat`, byte-checked)
  and `check.py`'s loudness/true-peak rows both PASS. Both pass; no regression found. Routing
  100%, report format 2/2, disclosure (`grader_expect`) 2/2, real execution 2/2 — all against the
  actual grader script, not restated by hand.
- **Not done.** The Opus-focused-grader qualitative pass and the 55-prompt trigger-judge routing
  pass (`evals/trigger/`) both need a model call independent of the one producing the run; this
  sandbox has no such access configured, the same blocker iteration-23-partial recorded for its
  routing pass. Not faked with this run's own self-report standing in for an independent judge —
  documented here as a still-open gap. Eval 23 (both `-partial` and this `-23b` addendum) stays
  open until an environment with that access runs Set B (whisper/TTS), Set D (the 55-prompt
  trigger judge), and an Opus/independent-model quality pass.

## 1.19.0 — observability, portability (planned)

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

## 2.0.0 — the announced breaks (shipped)

Manual `package.json` bump in one PR (the release workflow never picks a major). It removed
`--crf` (use `--quality`), refuses an existing output without `--overwrite`, narrowed `hdr` to a
real HDR signal (adding `bt2020_or_hdr` for the 1.x meaning), and dropped `json` / `progress`
from the MCP schema. Two planned items were not done, deliberately:

- **`result_v2` was withdrawn, not promoted.** It placed a key in `metrics` or `details` by its
  value, so the flat keys stay the one shape (docs/design-decisions.md).
- **`ctx` stays optional.** The MCP server still runs one subprocess per call; a required
  argument would break every call site for a risk nothing has yet.

The 1.21.0 "2.0 freeze" above did not happen as written either: 1.21-1.26 kept shipping
features, and the deprecation window's 90-day half was waived (docs/contract.md). Nothing else.

## Not planned

- A feature that needs 2.0: features land in 1.x behind flags (1.4.0, 1.6.0, 1.7.0 did).
- A new tool where an option on an existing one fits: the 42-tool table is the contract's
  surface, and adding a tool is allowed but is the last resort (none is planned above).
