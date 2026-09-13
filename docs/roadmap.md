# Roadmap: 1.7.1 → 1.21.0 → 2.0

The 1.x contract is frozen (docs/contract.md, "Stability guarantee"). 1.8 → 1.10 pre-ship the
2.0 decisions (issue #189, docs/design-decisions.md "Decided for 2.0") behind opt-in flags or
parallel keys, plus the follow-ups the evals keep surfacing. 1.11 → 1.20 grow the skill on the
frozen contract, one theme per minor, each closed by an evals iteration on the theme's own
prompts and an audit pass, as 1.5 → 1.7 did. 2.0.0 then removes the old spelling and flips the
defaults; it adds no feature of its own. `resolve_version.py` turns `feat` PRs into a
minor and `fix` PRs into a patch, so each block below is one or two `feat` PRs plus fixes.

## 1.8.0 — one-call delivery, quieter checks, encoder flags

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

## 1.9.0 — one time grammar, one HDR meaning

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

## 1.10.0 — 2.0 readiness

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
- **Eval iteration 10** and an eighth audit pass; the real-device corpus (92 verification
  steps) re-run on the tree — eighth audit shipped as 1.9.1; eval 10 and corpus re-run pending.
  `docs/contract.md` "What 2.0 changes" section written from the `deprecated` list (done).

## 1.11.0 — token diet (shipped; the PR was `feat:`, so the release bot cut a minor, and the themes below move up one)

The eval-10 follow-up: make a job cost the agent fewer tokens and fewer calls without changing
what any tool does. Nothing here is a behaviour change — `--json`, exit codes, contract fields
and the default MCP `tools/list` are unchanged except for additions.

- **Two-tier SKILL.md** (done): the always-loaded file keeps the workflow, the request→script
  table, the report format and one line per gotcha; the long "Things that look right but are
  wrong" / "Gotchas" prose and the audio-only recipes moved to `references/gotchas.md`, each
  line pointing at its anchor. 362 lines / 37.8 KB → 198 lines / 29.1 KB, no rule dropped.
- **Guidance that saves calls** (done): `doctor` only on a new machine or after a
  `kind: missing_tool` failure, not per job; no separate `probe.py` before every edit (a writing
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
- **Eval iteration 11** measures tokens per run and keeps only the changes that hold routing,
  honesty, language, report format and look behaviour at iteration-10 levels (pending).

## 1.12.0 — captions people can read

- `caption.py` wraps by measured text width (fontconfig metrics, not character count) so
  CJK and long Latin lines stop overflowing the safe area; `--max-lines` and `--min-duration`
  per cue; `--offset SECONDS` shifts an SRT/cues file; word-level timings from whisper's own
  word output drive `--karaoke` instead of even splitting.
- `brand.json` caption styles (`styles.caption.{font,size,colour,box,position}`) so one brand
  file gives every project the same look; `graphics.py` reads the same block.
- Eval 11: the 8 caption prompts (JA/EN, CJK wrap, karaoke, SRT offset) run 3 times.

## 1.13.0 — the audio bed

- `audio.py`: `--voice` strength levels (`light|medium|strong`), `--stereo-widen`, stem
  levels for dialogue / music / effects in a `render.py` project (`audio.stems`), sidechain
  ducking parameters exposed (`--duck-threshold`, `--duck-release`).
- `loudness.py --lra N` targets loudness range, `--dialogue` gates the measurement on speech
  (ffmpeg `speechnorm` / `silencedetect` energy) so ambience-heavy edits are not over-boosted.
- `check.py --platform podcast` gains chapters and mono/stereo rows; `audio.py --chapters
  chapters.txt` writes MP4/M4A chapter markers.
- Eval 12 on audio-only and mixed prompts.

## 1.14.0 — sync and multicam at scale

- `sync.py` accepts 3+ sources (one reference, N seconds) and writes one offsets JSON;
  drift correction reports the measured ppm and where it resampled.
- `multicam.py --switch energy` cuts to the loudest camera's audio with a minimum shot length;
  `--edl` exports the cut list for an NLE; the timeline is a `render.py` project so it can be
  re-rendered with different minimum shot lengths.
- Eval 13 on multicam / sync prompts; a real-device multicam corpus (phone + camera + lav).

## 1.15.0 — delivery, one preset per destination

- `export.py` presets for shorts / tiktok / linkedin as named targets (today aliases of
  reels / youtube), `youtube-hdr` (HEVC Main10 HDR10 kept), `youtube-av1`; a preset carries its
  loudness spec so `--normalize` and `check.py` read one table.
- `look.py --best-frame` picks a thumbnail candidate by sharpness and exposure (measured, no
  content judgement) and writes it at the platform's thumbnail size; `report.py` embeds it.
- Chapter markers in the delivery file from a `chapters` block in the project.
- Eval 14 on delivery prompts, all presets checked by `check.py` on the corpus.

## 1.16.0 — throughput

- `batch.py --jobs N` runs independent items in parallel under one `--timeout` budget;
  resumable (`--resume` skips items whose output verified); `--watch` folders.
- `render.py` caches unchanged stages by content hash of inputs and stage arguments, so
  changing the export preset re-runs export only; `--stop-after` and `--from STAGE`.
- `proxy.py` round trip: edit on proxies, `render.py --conform` re-renders from originals.
- Eval 15 measures wall-clock and encode counts on the 36-prompt set (the number, not just
  pass/fail).

## 1.17.0 — measured analysis (still no judgement)

- `scenes.py --shots` labels each shot static / pan / motion by measured optical flow;
  `--audio-peaks` and `--speech` (speech-vs-music energy ratio) as separate lists.
- `silence.py --speech-aware` keeps breaths shorter than `--min-silence` inside a sentence and
  cuts only between sentences (measured pauses), with the cut list as EDL.
- `cropdetect.py --motion-centre` reports the motion centroid per second for a 9:16 reframe
  that the calling agent decides on (the skill reports the number; it does not pick the subject).
- Eval 16 on analysis prompts, scored against hand-labelled ground truth.

## 1.18.0 — observability

- `--trace FILE` (common flag): one JSON line per ffmpeg run with wall time, encode fps,
  speed, exit code, bytes written; `result_v2.metrics` carries the same for the whole tool.
- `report.py` before/after frame pairs at the same timestamps, loudness and true-peak
  graphs, and the plan/verify chain when a plan was executed.
- `verify.py --install` checks the install itself (ffmpeg build, encoders, fonts, whisper) and
  prints the fix per missing capability, using the contract's capability list.
- Eval 17 grades whether agents quote the metrics rather than re-probe.

## 1.19.0 — portability

- Windows: paths with spaces and non-ASCII fonts through every filter (fontconfig escaping
  audit), long-path support; the Windows CI job runs the full corpus.
- ffmpeg 8 / 9: filter and encoder fixtures refreshed, `bt709_tag_args` and the colour
  negotiation path re-verified on each; a compatibility table in `references/devices.md`.
- `--hwaccel auto` (opt-in): videotoolbox / vaapi / nvenc for previews (`--fast`) only,
  never for the final encode unless `--hwaccel final` is given, with the encoder named in the
  result so a difference is traceable.
- Eval 18 on the Windows and macOS runners.

## 1.20.0 — agent ergonomics

- SKILL.md rewritten from evals 8–18: the request table regrouped by intent, the language and
  report rules moved to the top, the gotchas list pruned to the ones still hit.
- MCP: `tools/list` descriptions shortened to one line each (the schemas are unchanged), a
  `prompts` capability with the five workflows (reel, podcast, multicam, delivery check, HDR).
- `contract --json` gains `examples` per tool (the SKILL.md table rows, machine-readable).
- Eval 19: trigger set doubled (44 prompts), plus 20 "second-turn" prompts where the agent
  must continue an edit from a previous result document.

## 1.21.0 — the 2.0 freeze

- Everything 2.0 removes is announced (`deprecated` in the contract, `--help`, CHANGELOG) for
  at least one minor; `docs/migrating-2.0.md` maps every old spelling to the new one.
- `contract_version` 1.1: `deprecated`, `examples`, `metrics` documented; the real-device
  corpus and all 19 eval sets re-run on the tree; ninth audit pass.
- No new options after 1.21.0 on 1.x: 1.21.x is fixes only while 2.0.0 is prepared.

## 2.0.0 (after 1.21.x settles)

Manual `package.json` bump in one PR (the release workflow never picks a major). It removes
the deprecated spellings, promotes `result_v2` to the top level, makes `ctx` required, renames
`hdr`, flips the overwrite default, and drops `json` / `progress` from MCP. Nothing else.

## Not planned

- A feature that needs 2.0: features land in 1.x behind flags (1.4.0, 1.6.0, 1.7.0 did).
- A new tool where an option on an existing one fits: the 42-tool table is the contract's
  surface, and adding a tool is allowed but is the last resort (none is planned above).
