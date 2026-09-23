# Deliberate behaviours (read before filing a bug)

This file lists behaviours that look like defects on a first read but are decisions, with the
reason and the test that pins each one. An audit, a review bot or a contributor that finds one
of these should report it only if the rationale no longer holds -- and then the report should
say which sentence below is wrong. Every entry names where the decision lives in code so it can
be checked against the tree, not against this note.

Three earlier review rounds (2026-09-12) re-reported several of these; that is why the file
exists. When a decision changes, edit the entry in the same PR.

## Time limits

- **`FFMPEG_SKILL_TIMEOUT=0` (or `--timeout 0`) means no limit anywhere**, including the outer
  ceiling on sibling-script runs and the MCP dispatch. 0 is the documented "off" value, chosen so
  a genuinely multi-hour job can opt out; the default (1800 s) is what protects an unattended
  agent. Code: `_common.child_limit()`, `_common._limit_for()`. Test: `test_timeout_kills_a_hung_ffmpeg_and_reports_kind_timeout` (the `--timeout 0` case).
- **The outer ceiling is 4x the per-call limit plus 60 s, not the per-call limit itself.** A tool
  runs several ffmpeg/ffprobe calls (two-pass loudness, copy-then-re-encode fallbacks), each under
  its own limit; the outer ceiling only exists to end a child hung for a non-ffmpeg reason. Code:
  `_common.child_limit()`. Test: `test_sibling_scripts_run_under_an_outer_ceiling`.

## Dry run

- **Measurement passes run under `--dry-run`; only writes are skipped.** `probe`, `check`, `sync`,
  `multicam`, `scenes`, `cropdetect`, `report`, `silence`, `loudness` and `stabilize` run
  ffmpeg/ffprobe to measure, because a plan built on a fake measurement is not a plan. The
  contract lists them as `analysis_only`; every other tool runs nothing. Code:
  `_contract.DRY_RUN_ANALYSIS`. Tests: `test_dry_run_never_runs_ffmpeg_and_writes_nothing`,
  `test_dry_run_plans_rest_on_real_measurements`.
- **When a measured input is an intermediate an earlier dry-run stage would have written**
  (render/batch plans), the measurement is skipped with a note rather than failing the plan.
  Code: `_common.dry_run_input_pending()`.
- **`verify` accepts `--dry-run` and ignores it.** Its job is to run the tools for real.
  Contract: `_contract.DRY_RUN_NOTES["verify"]`.

## Colour

- **A BT.2020-primaries stream is routed through the HDR (10-bit HEVC, tags preserved) path even
  when its transfer is SDR.** `probe` reports `hdr: true` with `hdr_format: "BT.2020 SDR"` for
  it. The alternative -- 8-bit BT.709 x264 -- would clip the wide gamut without a conversion.
  Changing the meaning of `hdr` is a 1.x contract change and waits for 2.0. Code:
  `_common.probe()` (`hdr = ...`), `_common.video_args()` docstring.
- **`escape_drawtext()` drops `'` and `%` from burnt-in text** instead of escaping them. Both
  characters have no reliable escape across the FFmpeg versions in CI; a missing apostrophe is a
  known limitation, a broken filter graph is not. Test: `test_drawtext_semicolon_and_quote_render_as_inert_literal_text`.
- **`grid.py` and `look.py` composite an HDR input into an 8-bit SDR picture without a tone map.** Both
  produce comparison/inspection artefacts, not deliverables; `grid.py` prints a note when an input is
  HDR and points to `color.py --to-sdr` for a graded conversion. `join.py` and `broll.py`, whose output
  is a deliverable, keep the HDR (10-bit HEVC) path. Test: `test_grid_composites_cols_rows_with_labels`.
- **`look.py -o` is used verbatim only for a single `--at` with an image extension**; several frames,
  or `-o` given as a stem, produce `<stem>_<t>s.png` names. Test: `test_hdr_source_stays_hdr_through_reencodes`.
- **`--correct` converts through bt601 on both legs** (not bt709), because on every tested
  FFmpeg the 709 round trip through 8-bit 4:2:0 loses ~5 dB more than 601. Code:
  `color.py _rgb_stage()`. Test: `test_color_correct_identity_holds_on_a_bt709_tagged_source`.

## Outputs and files

- **An existing output is refused without `--overwrite`, dry runs included** (2.0; 1.x warned,
  with `FFMPEG_SKILL_NO_OVERWRITE=1` as the opt-in). The refusal is `kind: input` before any
  ffmpeg runs, so a dry run predicts it. A path this same run wrote (two-pass tools,
  copy-then-re-encode fallbacks) is never someone else's file. Code:
  `_common._check_existing_output()`. Test:
  `test_existing_output_is_refused_without_overwrite_and_never_for_its_own_files`.
- **An existing output is written through a hidden sibling temp file and replaced only on
  success**, so a failed run never costs the caller the file that was there (FFmpeg 5.x truncates
  the output before a filter error). The temp name `.<stem>.ffskill-<pid><ext>` is expected in the
  output directory during a run. Code: `_common._stage_existing_output()`.
- **Subtitle/data tracks are kept where the picture's timeline is untouched and dropped where
  it is retimed; both cases report `dropped_non_av_streams`.** Tools that re-encode the picture
  or audio in place (`fit`, `color`, `graphics`, `overlay`, `audio`, `loudness`, `proxy`,
  `deinterlace`, `denoise`, `freeze --mode extend`) try `run_keeping_subtitles()` first and
  report `false` unless the container refused the track. Tools that move the timeline
  (`cut` re-encode, `pad --start`, `freeze --mode insert`, `fit --method speed`, `speedramp`,
  `broll`, `join`) do not copy a track whose cues would fire at the wrong time and report
  `true` when the source had one. Code: `_common.run_keeping_subtitles()` and each tool's `emit`.
- **`caption.py` leaves its `.srt`/`.ass` sidecar next to the output by design**; it is a
  deliverable (the subtitle file), not an intermediate.
- **`examples/out/` and `tests/out/` are not tracked**; local demo output can be large. Nothing
  under them is in git (`.gitignore`).

## Arguments

- **A clip `speed` of 0 in a render project means "no speed change"**, the same as omitting the
  key; it is not a division by zero. A negative or non-finite speed is refused. Code:
  `render.py` (`if c.get("speed")`).
- **`--quality` (and `export.py`'s own `--crf`) is range-checked once in `apply_common()` for
  every tool**; a tool's own parser does not repeat the check. A re-encoding tool declares its
  default with `set_defaults(crf=N)`, which `add_common()` turns into `--quality`'s default; 2.0
  removed the `--crf` alias. Code: `_common.add_common()`, `_common.apply_common()`.
- **Colour flags are validated with `validate_color()` at the tool level**, including `overlay`,
  `grid`, `broll`, `join`, `fit`, `pad`, `waveform`, `straighten`, `background`, `export`. A
  review that reads one call site should grep for `validate_color(` before reporting a gap.

## Process and packaging

- **`references/process-pitfalls.md` is a maintainer diary and is not in the npm package**;
  `scripts.md`, `devices.md`, `ci-platform-pitfalls.md` and `docs/contract.md` are. Code:
  `package.json` `files`, `bin/install.js` `PAYLOAD`. Test: `tests/release_check.sh`.
- **`npm test` calls `python3`**; the Windows CI job gets it from `actions/setup-python`. A
  Windows machine with only `py` should run the test files directly.
- **The release bump commit carries the skip-CI marker in its message**; it is pushed by the
  release workflow with a PAT (the ruleset blocks the built-in token) and must not trigger a
  second run. Never quote that marker in a PR body: a squash merge copies it into the merge
  commit and skips every workflow (`references/process-pitfalls.md`).
- **An ffmpeg failure exits 1, whatever ffmpeg's own exit code was.** ffmpeg's code varies by
  build and by the failing stage (1, 69, 218, 234, a negative signal number), and 124/127/
  130/143 are reserved for timeout, missing tool and interrupts; passing the raw code through
  made the process exit code depend on the ffmpeg build. The raw code is in the JSON failure
  document as `ffmpeg_returncode`. Code: `_common._fail()`.
- **`verified` is what the tool measured itself, not a promise about the user's intent.**
  Every writing tool probes its artifact (that is `verify_output`); tools that measure more
  (`loudness.py` re-measures the file, `export.py` measures against the platform, `render.py`
  runs `check`) add those steps to `verification`, and `verified` is the conjunction. A spec
  miss the tool cannot fix (export's loudness) is `completed` + `verified: false`, not a
  failure: the file is usable, the next step is named in `notes`. Code: `_common.emit()`.
- **A plan is a dry run plus fingerprints, executed only by `render.py`.** `--plan FILE` is
  implemented once in `emit()` (every tool gets it, nothing per tool), inputs are found from the
  `-i` arguments of the planned commands, and the fingerprint is size + sha256 of the first and
  last 8 MiB rather than the whole file, so planning a multi-GB master stays instant while a
  re-export or re-trim is still caught. Execution re-runs the *tool* with the planned argv, not
  the recorded command lines: the tool's own guards, staging and verification stay in force.
  Code: `_common.write_plan()`, `render.execute_plan()`.
- **The flat success document is the 2.0 shape; `result_v2` was withdrawn, not promoted.**
  1.10.0 deprecated the top-level per-tool keys in favour of an opt-in `result_v2` block
  (issue #189). At 2.0 the block turned out to place a key by its value -- a number in `metrics`,
  the same key holding `null` in `details` -- so a caller had to know a value to know where to
  look it up, and promoting it would have rewritten every consumer of every tool's JSON for
  that. The flat keys, typed per tool in `output_schema`, stay; `--json-brief` answers the size
  concern. Test: `test_result_v2_preview_is_gone`.
- **`retryable` is always `false` in failure documents.** No failure kind is distinguishable
  today from a deterministic one that would fail identically on a blind retry, so the field never
  invites a retry loop. Code: `_common.ERROR_RETRYABLE`.

## Decided for 2.0 (issue #189 B), recorded in 1.x so the code moved toward them

- **Time grammar: seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` everywhere; four-part `hh:mm:ss:ff`
  is SMPTE at the source's frame rate, and a `@fps` suffix (e.g. `00:01:02:15@29.97`) names the
  rate explicitly.** The ambiguity today is only the four-part form (it needs an fps, and each
  tool found it its own way). 1.x: `time_arg()` is the single parser, every tool uses it, an
  unknown fps for a four-part value is `kind: input` naming `--fps`. 2.0: the `@fps` suffix is
  accepted by `time_arg()` and documented once in `references/scripts.md`; nothing else changes,
  so no CLI is removed. Rejected: "seconds only in single tools, composite input only in
  `render.py`" -- editors quote timecode, and refusing it moves the conversion onto the agent.
  Code: `_common.time_arg()`. 1.9.0 shipped it: `broll`, `cut` and `freeze` (the last three
  callers of the raw parser) go through `time_arg()`, and `@fps` is accepted everywhere, so 2.0
  has nothing left to change here.
- **Encoder abstraction: `--codec h264|hevc|av1|prores` and `--quality N` on every
  re-encoding tool, resolved in one place.** `video_args()` already centralises x264 + the
  HDR/10-bit branch; 2.0 adds the two flags to `add_common()` for tools that re-encode, keeps
  `--crf`/`--preset` as aliases for one major, and maps `--quality` to CRF / `-b:v` / ProRes
  profile per codec. Until then every tool keeps its `x264 medium / crf 18` default; the
  `export.py` presets are the only place a non-x264 codec is chosen. Rejected: a per-tool
  `--codec` added piecemeal in 1.x (the audits found HDR fragility wherever encoder choice was
  duplicated; one more duplication is the wrong direction). Code: `_common.video_args()`.
  1.8.0 shipped the two flags (`add_common()` adds them to every tool that declares `--crf`;
  `encoder_args()` resolves them; `--crf`/`--preset` unchanged); 1.10.0 deprecated `--crf`, and
  2.0 removed it (`--preset` stays: it is x264's speed/size trade, not an alias). Test:
  `test_crf_is_gone_and_quality_keeps_its_default`.
- **`hdr` is a real HDR signal (PQ / HLG / Dolby Vision) since 2.0; the tools route on
  `bt2020_or_hdr`.** 1.x's `hdr` also counted BT.2020 primaries on an SDR transfer; 1.9 added
  `hdr_signal` as the narrow parallel key, and 2.0 gave `hdr` its meaning (`hdr_signal` stays,
  equal to it). The editing tools still route every BT.2020-or-HDR source through the HEVC Main10
  path with its own tags -- a BT.2020 SDR source re-encoded as x264 with BT.709 tags would shift
  its colours -- so that condition got its own key, `bt2020_or_hdr`, and tool behaviour did not
  change. `hdr_format` says "BT.2020 SDR" for the in-between case. Code: `_common.probe()`. Test:
  `test_probe_hdr_is_the_signal_and_bt2020_sdr_keeps_the_10bit_route`.
- **Per-request Context: `STATE` stays process-global; `run()`/`emit()`/`die()` take an
  optional `Context`.** 2.0 did not make it required: the server still spawns one subprocess per
  call, so nothing shares the global, and a required argument would have broken every tool's
  call sites for a risk that does not exist yet. The plan, kept for when a server runs tools
  in-process: thread `ctx` through the three choke points (a signature change, hence a major);
  tools that only call those keep working with a one-line change. Rejected: thread-locals (hides
  the dependency the reviews keep asking about). Code: `_common.Context`.

## External review, 2026-09-14 (1.17.0)

An outside review of the repository at 1.17.0, alongside eval 18. What it raised, and what was
decided. Recorded here so none of it is re-proposed from scratch.

- **P0-1 — run eval 18 before any further feature work.** Accepted, and **done before this
  patch**: eval 18 ran on 1.17.0 (100 prompts, independent grading) and its findings are what
  1.17.1 fixes — the delivery templates never reached `--fit-size`, the project schema refused
  the fit keys, and SKILL.md routed none of the 1.17 features.
- **P0-2 — issue #234, `probe.py` reports `?s | no video | no audio` on a cp932 Windows box.**
  Accepted and **fixed in 1.17.1**: every child capture in `scripts/` passes
  `encoding="utf-8", errors="replace"` instead of decoding with the machine's code page, and a
  probe whose ffprobe printed nothing refuses (`kind: input`) rather than returning a document of
  nulls with exit 0. A source-level test keeps `text=True` without an encoding out of the tree.
- **P0-3 — the roadmap's "released version today" line lagged the bump.** Accepted; the checklist
  half landed in the eval-18 docs PR (`CONTRIBUTING.md`'s release checklist now says to move that
  line in the same PR as the version bump) but the line itself still read 1.16.0 against a
  `package.json` of 1.17.0 until review 17 caught it; **done in 1.17.1**.
- **P1-4 — `scripts/_common/text.py` is the next module too large to review in one pass.**
  Accepted, and deliberately **not mixed into 1.17.1**: it is a behaviour-free split, so it gets
  the same treatment `_common.py` got — its own no-change release after 1.17.1, with the contract
  snapshot, the MCP surface and every `--help` byte-identical.
  **Done in the refactor after 1.17.3.** `text.py` (1,655 lines, 111 top-level definitions) was
  cut along its own section comments into `fonts.py` (font tables, `char_script`/`detect_script`,
  the fontconfig lookups, `script_font_for_text`), `emoji.py` (clusters, assets, the support
  probe, `emoji_filter_chain`), `drawtext.py` (option building, escaping, the shaping probe) and
  `wrap.py` (the advance table, the caption wrapper, `fit_size`); the import graph is acyclic
  (emoji → emit; fonts → emoji; drawtext → runner, decision; wrap → fonts, emoji) and every body
  moved byte-identical, checked by AST source segment. `text.py` stays as a re-export shim that
  mirrors rebinding to the defining part, the way the `_common` facade does, and the facade's
  module list gained the four parts so a `mock.patch("_common.<name>")` still reaches the
  binding the code reads at call time. The release rule held: `contract --json` and every
  script's `--help` were dumped before and after and diffed empty, the contract and MCP
  snapshot tests pass, no behaviour change.
- **P1-5 — reports copy the English boilerplate lines into non-English answers.** Accepted:
  SKILL.md's failure example now shows the Japanese rendering of `Check:`/`Look:`'s filler lines,
  so the rule ("these are sentences, not labels") has an example next to it.
- **P1-6 — eval prompt `ml2` tested a refusal, not the mux.** Accepted: `ml2` now ships a German
  SRT and a video and expects `caption|render`.
- **P1-7 — the 42-tool MCP `tools/list` is paid for by every session.** Accepted, and **shipped**:
  `tools/list` defaults to the core 12 (`render`, `look`, `caption`, `export`, `check`, `fit`,
  `cut`, `audio`, `loudness`, `graphics`, `silence`, `probe`), chosen from eval iterations 17-20's
  `expect` frequency, not taste. `FFMPEG_SKILL_MCP_FULL=1` lists all 42; the other 30 stay
  reachable by name through `tools/call` either way, and the contract still describes all 42.
- **P1-8 — at least one routing run on a non-Claude model.** Accepted as an `evals/run.py` task,
  and **shipped**: `run.py` grades any transcript file against `tasks.json` or the fuller
  `agent_prompts_24.json`/`agent_prompts_exec.json` sets with substring and regex checks only
  (`--json` output, an `a|b` alternation in `expect`, and the `grader_expect`/`grader_not`
  regexes), no `claude` CLI or LLM-judge dependency anywhere in the path. `evals/README.md`'s
  "Running this from Cursor, Codex, or another harness" section documents the walkthrough. What
  is still true, and stated rather than fixed: the maintainer has not run another vendor's model
  from this environment, so no cross-vendor number is published here yet -- the harness is ready
  for whoever does.
- **P2-9 — issue #143 (real-device corpus) has no acceptance criteria.** Accepted as written in
  the issue: the corpus run is the criterion, one row per device family.
- **P2-10 — `--cache` has no failure-path tests.** Accepted and **closed in this patch**: the
  existing tests cover hit, miss, invalidation (stage args, ffmpeg build, skill and contract
  version, `--fast`, container) and the atomic cache write; what was missing — a failed stage
  must cache nothing and leave no work directory — is now a test.
- **P2-11 — no accuracy numbers for the beat grid and filler removal.** Accepted: those wait for
  eval-19 data rather than being asserted from the implementation.
- **P2-12 — reorganise SKILL.md's table by intent.** Accepted, and it **stays 1.20.0**: 1.17.1
  spends its byte budget on the missing routing rows, which is the same finding at a smaller
  scale.

## External review, 2026-09-13

An outside review of the repository at 1.13.0 (eval 14). What it raised, and what was decided.
Each item is recorded here so it is not re-proposed from scratch.

- **`scripts/_common.py` is too large to review in one pass.** Accepted, and **done** in the
  behaviour-free refactor release after 1.15.0, not folded into a feature minor: the module is a
  package of six -- `runner` (process execution and timeouts), `probe` (ffprobe and the measured
  facts), `decision` (the pure copy-vs-re-encode and capability choices), `emit` (result
  documents, `die()`, `info()`), `color` (colour tags and the HDR paths) and `text` (fonts,
  scripts, emoji, drawtext) -- and `scripts/_common/__init__.py` is a facade re-exporting all 184
  of their names, so every `from _common import ...` and every `_common.<name>` in the tools and
  tests keeps working and the diff is checkable as "no caller changed": the contract snapshot,
  the MCP tool surface and every `--help` came out byte-identical. `tests/test_all.py` split by
  tool group in the same release. Two things
  the review suggested alongside it were **rejected**: a `MediaInfo` dataclass in place of the
  probe dicts (the dicts are the `--json` payload and the contract's `output_schema`; a
  dataclass would add a conversion layer on the hot path and a second shape to keep in sync),
  and a different overwrite policy (writing to a temp path and renaming into place stays — it is
  what makes a killed or timed-out run leave no partial output, and 2.0's refusal default is
  built on it).
- **The evaluation is Claude-only.** True, and it is stated rather than fixed: the agent runs use
  a Sonnet agent, the independent grader is Opus, and the trigger judge is Sonnet. The maintainer
  cannot run other vendors' models from this environment, so a cross-vendor number would be
  invented, not measured. What is done instead, **shipped**: `evals/run.py` is a regex/substring-
  only grader runnable from Cursor, Codex, or any harness that can produce a transcript file —
  `--prompts` selects `tasks.json` (the 29-prompt routing/refusal set) or the fuller
  `agent_prompts_24.json`/`agent_prompts_exec.json` sets, and `evals/README.md` documents the
  walkthrough. Anyone with access to another model can run it there and publish the result,
  reported as its own number (see that section's "Comparing results across vendors") rather than
  a delta against this repo's own Claude-based iterations. The harness reads transcripts and
  files; nothing in it is Claude-specific by design.
- **`references/` is rarely read during evals.** Measured and expected. The reference files are
  the long-form detail, and SKILL.md's request→script table is what carries a job: iteration 11
  showed that pointing agents at the reference files cost tokens without changing outcomes, and
  1.11.1 reworded step 0 accordingly. The answer is not to make `references/` more attractive but
  to make the table better: the **intent-clustered request table is planned for 1.20.0**.
- **The MCP catalogue costs a client context on every session.** A 42-tool `tools/list` is paid
  for by every session, including the ones that call two tools. Decided and shipped in **1.18.3**:
  the default listing becomes the core 12, the other 30 are reachable lazily through `tools/call`
  or `FFMPEG_SKILL_MCP_FULL=1`. The contract still describes all 42 — the surface does not shrink,
  only the default listing.
- **The roadmap read as though planned work had shipped.** Fixed: `docs/roadmap.md` now marks
  every version shipped + evaluated (naming the iteration), shipped with eval pending, or
  planned, and the reconciliation is against `CHANGELOG.md` and `evals/results/`.
- **The README over-claimed platform coverage.** Issue #143 (the full real-device corpus on
  Windows, and an install reproduced by someone other than the maintainer) is still open. The
  README now says what is actually covered: the contract and test suite on Linux, macOS and
  Windows; the real-device media corpus on Linux and macOS; the Windows corpus open.

## 1.15.0 — text people can see

- **Colour emoji is a PNG overlay, not a font.** Two measurements, both on ffmpeg 6.1.1 with
  Noto Color Emoji installed. (1) `drawtext` cannot use a colour emoji font *at all*: at
  `fontsize=48` it fails filter initialisation with `Could not set font size to 48 pixels:
  invalid library handle` → `Error initializing filters`, and at the font's only strike
  (`fontsize=109`) with `Monocromatic (1bpp) fonts are not supported.` — no file is written
  either way. That is a hard failure, not a degraded render, so drawtext must never be handed an
  emoji font. (2) A colour emoji font being installed proves nothing about libass: the same
  machine logs `Glyph 0x1F389 not found, broken font? Trying all charmaps` through `subtitles=`
  and renders a monochrome outline from a fallback face. The only honest capability test is a
  render probe (`doctor --json .fonts.emoji.libass_color`), and the only build-independent colour
  path is a PNG composited over the text. Both error strings are quoted here so the font route is
  not re-proposed.
- **Emoji position comes from the same averaged em table the wrap uses**, not from parsing font
  metrics and not from shelling out to a shaping library (there is no stdlib font parser, and a
  dependency is out of scope). The consequence is stated rather than hidden: an emoji at the
  start or end of a line is exact, and one in the middle of a Latin line is off by the accumulated
  rounding of the characters before it — **measured at 17 px on a 24 px caption over a 1280-wide
  frame: 0.28 em, about 3 % of the line width**, which still lands the box inside the gap libass
  reserved rather than on a glyph. That measured number is the documented bound, not a tighter
  estimate. An RTL line is measured from its rendered end instead of its logical prefix: libass
  lays Arabic and Hebrew out right-to-left, so the logical prefix is the *right* part of the
  picture and measuring it from the left put the PNG on top of the text.
  The overlay is clamped to the frame and the test asserts it stays inside the safe area.
  The gap itself is exact: U+2588 FULL BLOCK was **measured**, not assumed, at 0.83 em (FreeSans),
  0.79 (WenQuanYi Zen Hei) and 0.66 (DejaVu Sans, IPAPGothic, Loma), and figure spaces at
  0.46–0.55 em, so neither reserves a whole em; an alpha-hidden zero-width space carrying
  `\fsp<px>` reserves exactly the requested pixels in all five faces, including inside a karaoke
  run.
- **`graphics.py`'s ASS route is chosen per text, not globally.** The renderer switches only when
  the text contains a script drawtext cannot shape, an emoji overlay needs a reserved gap, or the
  emoji would otherwise be drawn *by drawtext* — which loads exactly one font file and has no
  fallback chain, so `mode: mono` there is an empty box, not a glyph. libass does have a fallback
  chain, so `mono` means libass; a run pinned to `--text-render drawtext` strips the cluster and
  says so rather than reporting a mode it did not deliver.
  Latin, CJK and Arabic templates keep the drawtext route and render pixel-identically to
  1.14.0, so the demos, the golden frames and every existing test do not move (the filter
  string itself did change: the label moved from `text=` into `textfile=…:expansion=none`) —
  and the new route carries no risk for the 95 % of jobs that never needed it.


## 1.16.0 — long-form delivery

**The audiogram extends `waveform.py`; there is no `audiogram.py`.** `waveform.py` already owns
`showwaves`/`showspectrum`, `--width/--height/--fps/--color/--background`, `--split-channels`,
`--audio-stream`, the one encoder line and the FFmpeg-5.x `-t` cap (#146). An `audiogram.py`
would be that file plus a background image: a second spelling of one tool, which is exactly the
mistake recorded for `audio.py --chapters`. The 1.x guarantee forbids *removing* a tool, so an
`audiogram.py` would be permanent surface; `--image` is one additive argument. The composite job
(visualisation over a plate, a title, captions burnt in, platform size, `check.py`) is a chain,
and this repo already has one answer for a chain: a `render.py` template, as 1.14 established and
`templates/podcast.json` precedes. The tool count therefore stays 42, which is asserted in five
files by `test_docs_tool_count_matches_the_real_tool_list`. Do not re-propose it.

**The title and the captions on an audiogram are second processes.** `waveform.py --title` runs
`graphics.py --template sticker` and `--srt`/`--text` runs `caption.py` on the rendered file,
rather than adding drawtext or an ASS path here. One code path per job is worth two process
spawns; the alternative is a second subtitle renderer that drifts from the first.

**`--auto-chapters` lives in `metadata.py`, and the detectors moved into `_common`.**
`metadata.py` already owns the chapter format, the `-c copy` graph and the written-vs-asked-for
count assertion; `scenes.py --chapters-out` would put chapter writing in a tool that cannot write
chapters. No script in `scripts/` imports a sibling tool (only the `_`-prefixed modules are
shared), so `silence.detect` and `scenes.detect_scenes` moved into `_common/probe.py` byte-for-byte
and all three tools import them from there. The merge/keep/drop decision itself is
`propose_chapters()` in `_common/decision.py`: pure, subprocess-free, unit-testable.

**The skill proposes chapter timestamps; it never names them.** Every proposed title is
`Chapter N` and the result says `"titles": "placeholder"`. Naming a chapter needs knowing what is
said in it, which is content understanding — the boundary SKILL.md's "What this skill does and
does not decide" holds. A request to title them is a refusal with the placeholder list offered.

**Only the `--srt FILE:lang` suffix form.** The parallel-list alternative (`--srt a --srt b
--lang en,ja`) was specified and dropped: it can get out of order, and two spellings of one
argument is the thing the deprecation policy exists to avoid. A single `--srt` with no suffix
still honours `--language`, so nothing that worked before changed.

**The Japanese particle table is a preference, not grammar — and it is a "do not strand at the
start of a line" table.** `は が を に で と の へ も や から まで より` come from the task brief
plus the five a reader would add. A particle is enclitic: it attaches to the word *before* it and
marks that word's role, so kinsoku practice keeps the two together. The rule is therefore "prefer
the break after a particle, forbid the break before one", not the other way round. There is no
upstream source for the list and no precedent in this repo; it is tunable data, applied among
break positions that already fit, so it can never widen a line or change the line count.

**R4 scores both directions, which is what makes it decide.** An article or preposition opens the
noun phrase it governs, so the break *before* it is the good break (0.2) and the break *after* it
the bad one (0.8). Penalising only the bad direction leaves the greedy width rule to choose among
everything else, which is how the first cut of this release still split eval 16's `dl1` cue
mid-phrase. With both directions scored, `"A third line the tool times for me"` comes out as
`A third line / the tool times for me` — one whole phrase per line — and `dl4` is unchanged.

## 1.17.0 — throughput

**No new tool. The tool count stays 42.** Four candidates were considered and each landed as a
flag on the tool that already owns the vocabulary: a `beats.py` analyser → `scenes.py --beats`
(scenes already decodes the same PCM through `audio_envelope()`, and "where are the interesting
times" must not be split across two scripts); a `filler.py` → `silence.py --filler` (filler
removal *is* time-range removal — it reuses `keep_ranges()` and the identical `aselect`/`concat`
graph, and a second tool would give the agent two ways to spell "tighten the talking"); a job
runner → `batch.py --jobs` (batch already owns the item loop, the cache and the summary); a
`cache.py` → `render.py --cache` (the cache key is a stage's own arguments, and only render knows
them). Going to 43 is not a one-line change: it means `README.md` ×4, `SKILL.md` ×2 with single
digits of headroom, `package.json`, `.claude-plugin/plugin.json`, `docs/contract.md`,
`references/scripts.md|devices.md|gotchas.md|ci-platform-pitfalls.md`, `demos/CI.md`,
`tests/corpus/report.md`, `tests/fixtures/mcp_tools.json`, `TOOL_META` + the reencode table +
`provides`, and `test_docs_tool_count_matches_the_real_tool_list`. Do not re-propose any of the
four.

**The caption legibility floor is 4.5 % of the frame height, one number for every destination.**
`ass_units(0.045) = 13` against the 288-line ASS script grid — 87 px of type on a 1920-tall
frame. It was chosen as the smallest size that is still comfortably above the ~3.5 % where mobile
legibility studies and the platforms' own caption UIs bottom out, *not* fitted to the eval cues;
that every eval-17 cue happens to fit two lines at exactly 13 is stated in the code comment
rather than hidden. There is no per-platform floor table, because nothing per-platform has been
measured and a table of seven guesses reads as seven measurements. `_platforms.PLATFORMS[name]`
can gain a `min_size` the day one is measured; until then one honest number.

**One fitted size per file, not per cue.** A caption track whose type size changes from cue to
cue is the single most visible "this was machine-made" artefact, and it defeats the 1.12
readability work — one measured line width per file is also what makes the wrap regression lock
mean anything. `--fit-size-scope cue` exists for the one outlier cue that would otherwise shrink
a ten-minute file, and it is opt-in and named in the result.

**`--fit-size auto`, not `on` and not `off`.** With `off` as the default the feature would ship
dark: no agent passes a flag it has no reason to know about, and the defect eval 17 measured is
precisely that the *default* path produces four-line cues — eval 18 would measure 1.16.0 again.
With `on` as the default, a caller who deliberately set `--size 30` for a brand look would
silently get 21, which breaks "the same behaviour for the same input and arguments" for a real,
stated argument. `auto` changes only the path where the skill itself chose the number, and the
CHANGELOG carries the behaviour line the stability guarantee requires. A `brand.json` caption
size counts as stated for the same reason `--size` does: it is a decision about the look that
somebody wrote down.

**`like`, `tipo`, `cioè` and `なんか` are not ordinary filler words.** They are discourse markers:
grammatical in most sentences, so removing them cuts meaning rather than noise — a judgement
about content, which this skill does not make. The first three are out of the default lists and
reachable with `--filler-extra`, which says what adding one costs. `なんか` is *in* the `ja` list,
because it is the most common Japanese filler and leaving it out makes the flag useless for
Japanese; it is orthographically identical to the pronoun use, so every run that removes one
warns and `--filler-keep なんか` takes it back out. The asymmetry is deliberate: English has
usable fillers without `like`, Japanese does not have usable fillers without `なんか`.

**There is no heuristic filler fallback without word timings.** "Remove the 0.3 s blips that look
like an 'um'" would cut real speech — short words, breaths, the start of a sentence — and it
would do so silently, with no way for the caller to check. A filler word is removed only where a
speech engine measured a `start < end` pair for it; without timings the tool refuses and names
`--words` and `--transcribe`. This is the same rule as `--snap beats`: never act on a
measurement that was not made.

**The ffmpeg version is inside the render cache key.** A cached artifact is a file this skill did
not produce in *this* run, and the only honest way to reuse one is to be certain the same code
would have produced it. The ffmpeg build banner (the whole `ffprobe -version` first line, not `major.minor`: two 7.1.x
builds with different libx264 write different bytes), the skill version, the contract version and
the flags render forwards to its children are
therefore part of the key, so a different build simply *misses* rather than being asked to trust
a file it did not write — no "is this close enough" comparison, no staleness heuristic, and no
way for a filter default that changed between builds to leak into a delivery. The cache is also
opt-in with no default directory: a cache appearing on someone's disk unasked contradicts the
"a plan leaves nothing behind" posture the whole tool holds.

**`batch.py --jobs` is capped at `min(N, cpu_count, 8)`.** Every item is itself an ffmpeg process
that already threads across cores; beyond a few concurrent x264 encodes the jobs contend and
wall-clock stops improving while memory does not. A number above the cap is *clamped with a note*
rather than refused — refusing a number that is merely optimistic is unhelpful, and the result
reports both `jobs` and `jobs_requested` so a report claiming "64 jobs" is checkable. The
`--timeout` becomes the whole batch's budget rather than each item's, which is why the pool is
topped up to `jobs` in flight rather than submitted all at once: a deadline that every item has
already passed cannot stop anything. That shared budget is scoped so it cannot change 1.16: it
applies when a `--timeout` was actually stated, or when `--jobs > 1` asked for the batch to be
treated as one piece of work. The default sequential run with the default 1800 s keeps the old
per-item ceiling — otherwise a folder of forty files that used to finish would start exiting 124,
for a flag nobody passed.

**`--beats`, `--filler`, `--jobs` and `--cache` get no SKILL.md request row in 1.17.0.** The
existing rows already route ("cut out the pauses" → `silence.py`, "do this to every file in the
folder" → `batch.py`, "a 60 s highlight" → `scenes.py`), `references/scripts.md` carries the
flags, and SKILL.md has single digits of headroom under its 30,000-byte budget. Only the caption
size got a row, because that one is a *different answer to a request the table already claims to
route*. If eval 18 shows agents missing `--filler` or `--snap beats`, 1.18.0 buys the rows.

**`--shots`' flow measurement is scoped to stay dependency-free and fast: 48x27 grayscale frames
at 4 fps, a 4x4 grid of block matches, +/-3 px search.** A real optical-flow library was never on
the table — the zero-dependency rule stdlib+ffmpeg covers every other script, and a Lucas-Kanade
or dense-flow implementation in pure Python would be both slower and no more honest for what
`--shots` actually needs, which is three labels, not a per-pixel field. 48x27 keeps a whole shot's
decode at a few KB (a feature-length input never risks memory the way `--beats`' 22050 Hz PCM
does), and 4 fps is enough to see whether the frame is panning, static or churning without
sampling every frame ffmpeg decodes. The zero-shift tie-break in `_block_match` (see the code
comment) exists because a textureless block — sky, an out-of-focus background, `--shots`' own
`test_scenes_shots_static_clip_is_labelled_static` fixture — ties every candidate offset on SAD,
and without an explicit bias towards "no motion" the scan reported the search window's first
corner as the measured displacement: a still frame read as steady motion in one direction, every
time. `agreement` (how consistently the 16 blocks agree on direction) is what tells a pan from
motion-inside-a-static-frame: a camera move shifts the whole picture one way, a subject moving in
front of a still background does not, and the two look identical in `magnitude` alone.

**`--audio-peaks` writes a new `audio_peaks_db` key rather than changing `audio_peaks`.** The
unconditional `audio_peaks` list scenes.py has always reported (`[{time, rms}]`) is a different
measurement in a different unit, used to score `--highlights`; the stability guarantee's "no key
given a different type" means an explicit request for dBFS-unit peaks needed its own name, not a
unit change to a key a caller has been reading since 1.0.

**`--speech` reports a ratio, not a label.** A zero-crossing-rate proxy (this window's ZCR over
the file's own median) says nothing about whether a stretch *is* speech or music — it says speech
transients cross zero faster than sustained tones, which is true often enough to be a usable
number and not true often enough to be a classifier. Naming the key `speech_music_ratio` rather
than `is_speech` keeps the tool on its side of the "analysis tools report numbers, they never
decide what's interesting" line: the calling agent reads the number and decides what a high or
low ratio means for its own request, the same way it already reads `--rank-by audio`'s RMS
figures without this skill calling any of them "the best scene".

**`--speech-aware` composes with `--filler` by feeding the same `keep_ranges()`/`merge_spans()`
pipeline `--filler` already uses, not a second removal pass.** The composition risk was two
independent cut lists disagreeing — a breath kept by `--speech-aware` getting cut anyway because
`--filler` found a word inside it, or the reverse. `speech_aware_silences()` returns two lists
(sentence-boundary silences to remove, breaths to keep) instead of a single filtered list, so a
breath is simply never added to the removal side: it is not "removed then added back", which
would leave a seam. The one designed interaction is a filler word *inside* a kept breath: the
breath itself is not cut, but `merge_spans()` still unions the filler span into the removal list
the same way it has always merged a filler word sitting inside a plain silencedetect gap (the
1.17.0 regression fix), so a real disfluency is still removed even from air `--speech-aware`
would otherwise keep whole. `BREATH_FLOOR` (0.12 s) exists because plain `detect()` only sees
gaps at or above `--min-silence`; without a second, shorter silencedetect pass the breaths inside
a sentence are invisible to begin with, not merely unclassified.

**sync.py's N-source shape adds a new optional `more_sources` positional rather than renaming
`second` to a list.** The stability guarantee treats an argparse dest as a CLI surface: renaming
`second` to `sources` (even as a 1+ `nargs`) would have been a rename of a positional the contract
promises never to rename, and the MCP `inputSchema` derives its property names directly from
argparse dests (see `_contract.input_schema`), so the rename would have propagated into a removed
MCP property too. `second` therefore keeps meaning exactly what it always has — the one other
recording a 2-source call aligns — and `more_sources` (`nargs="*"`, default `[]`) is purely
additive: omitted, the CLI and its JSON are unchanged from 1.17. `args.sources = [second] +
more_sources` is built once, right after parsing, so the rest of `main()` (and `measure_one()`,
factored out of the single-pair drift code that used to live inline) never has to know which
positional a given source came from.

**Why `sources` carries the single-source measurement too, additively, instead of only appearing
at N>1.** A caller that standardises on reading `sources` for a multi-camera job should not also
need a special case for the 2-source call — `sources[0]` is always the same measurement as the
top-level `offset_seconds`/`confidence` when there is exactly one. The reverse (a flat `second`
key materialising when there are three sources) is not offered, because there is no single "the"
second source to put there once there are two or three, and inventing one would be worse than
leaving the key out.

**`multicam.py --switch energy`'s window and merge rule.** Loudness is measured every 0.25 s (four
times finer than the default `--min-shot`, so a real cut point is not missed by more than 0.25 s)
and picking the winner is a plain argmax over cameras with a video stream — the same "biggest
number wins" rule `scenes.py --rank-by audio` already uses, not a smarter voice-activity model,
because a second measurement method would be a second thing to keep honest and this one is easy to
audit from the `cuts` list alone. Folding a run shorter than `--min-shot` into its neighbour
(rather than, say, discarding it or holding the previous camera) was chosen because it never
invents a cut that was not there and never drops the fact that a switch was measured at that
instant — it only refuses to *act* on a switch too brief to be a readable shot. The direction of
the fold (into the next run, or the previous one if it is the last) is arbitrary in the sense that
either choice is defensible; it is documented here rather than left to be rediscovered from the
code, and pinned by `test_multicam_switch_energy_respects_min_shot`.

**The multicam timeline needed no new render.py project stage.** A `--switch` cut list is already
exactly what `clips[]` expresses: one clip per cut, `src` the camera's own file, `in`/`out` on
that camera's own timeline (the reference cut, shifted by the camera's measured offset). Inventing
a `"multicam"` stage type would have meant a second way to say "play this camera from A to B" that
`render.py` would have to keep in sync with `clips[]` forever; reusing `clips[]` means a switch
list can be re-rendered with a different `--min-shot` by re-running `multicam.py --switch energy`
and rewriting the same project's `clips` array, with every other stage (captions, audio, export,
check) working on the multicam edit exactly as it would on any other project. `--edl` writes the
plain `cut.py --segments` file (`START-END` per line) rather than a `render.py` project directly,
because the camera index a project's clips need is already sitting in the JSON `cuts` field
(`[[start, end, camera], ...]`) — turning that into `clips[]` is a few lines in the calling agent,
not a new file format this tool would have to maintain.

## 2.1.0 — handing the cut to an editor

- **`--export-timeline` is an option on `render.py`, not a 43rd tool.** The input is a
  project file and the translation is render.py's own reading of it (paths resolved the same
  way, the same validation); a separate tool would re-implement both. Code:
  `render.export_timeline()`, `_common/timeline.py`.
- **The timeline matches the project's numbers, not a render's.** A dissolve is centred on
  each cut and trimmed `trim_head`/`trim_tail` frames either side, so the total is the sum of the
  clip lengths minus one transition per join -- what `join.py`'s xfade renders by design. A real
  render can come out a few frames longer, because `join.py` offsets each crossfade by the
  part's *container* duration (audio priming included); that is render's drift, recorded as a
  follow-up, and copying it into the timeline would hand an editor a cut nobody asked for.
  Test: `test_build_centres_each_dissolve_and_keeps_the_rendered_length`.
- **What a timeline cannot carry is reported, never dropped.** Captions, graphics, overlays,
  the silence cut, fit, audio processing, loudness and the export preset go to
  `timeline.not_exported` and stderr. A caption track or a title in FCPXML would be a second
  implementation of `caption.py`/`graphics.py` whose output no one here can see.
  Test: `test_build_refuses_what_a_timeline_cannot_hold`.
- **OTIO's `source_range` is timeline length, with the speed in a `LinearTimeWarp`.** Core
  OTIO does not rescale a clip's duration by its effects; the first version stored the
  speed-scaled source length and the reference `opentimelineio` library (0.18) measured the
  track at 253 frames for a 225-frame cut. Test:
  `test_otio_track_lengths_add_up_without_counting_transitions`.
- **Verified here: structure and arithmetic; not verified here: an editor opening the file.**
  All three formats were read back by the reference OTIO library and its FCPXML / CMX 3600
  adapters at the right length, but none of Final Cut, Resolve or Premiere is available in this
  environment, and OTIO's own FCPXML adapter ignores dissolves, markers and retiming, so those
  parts of the FCPXML are checked only against Apple's schema by hand. The editor round trip is
  on #143's real-hands checklist.
