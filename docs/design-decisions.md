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

- **An existing output is warned about, not refused, until 2.0** (`--overwrite` is the explicit
  consent; `FFMPEG_SKILL_NO_OVERWRITE=1` opts into the 2.0 refusal today). Per the 1.x
  deprecation policy in `docs/contract.md`. Code: `_common._check_existing_output()`.
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
- **`--crf` is range-checked once in `apply_common()` for every tool**; a tool's own parser does
  not repeat the check. Code: `_common.apply_common()`.
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
- **The 2.0 success-document shape ships in 1.x as an opt-in parallel key.** `result_v2`
  (`FFMPEG_SKILL_RESULT_V2=1`) is built once in `emit()` from what every tool already passes,
  so no tool changes its own keys and 2.0 becomes "promote `result_v2` to the top level". Per
  issue #189's plan: parallel keys first, deprecation notices second, 2.0 removes the old.
  Code: `_common._result_v2()`.
- **`retryable` is always `false` in failure documents.** No failure kind is distinguishable
  today from a deterministic one that would fail identically on a blind retry, so the field never
  invites a retry loop. Code: `_common.ERROR_RETRYABLE`.
