# Deliberate behaviours (read before filing a bug)

This file lists behaviours that look like defects on a first read but are decisions, with the
reason and the test that pins each one. An audit, a review bot or a contributor that finds one
of these should report it only if the rationale no longer holds -- and then the report should
say which sentence below is wrong. Every entry names where the decision lives in code so it can
be checked against the tree, not against this note.

Three earlier review rounds (2026-09-12) re-reported several of these; that is why the file
exists. When a decision changes, edit the entry in the same PR.

<!-- contents:start -->
**By topic:**

- [Time limits](#time-limits)
- [Dry run](#dry-run)
- [Colour](#colour)
- [Outputs and files](#outputs-and-files)
- [Arguments](#arguments)
- [Process and packaging](#process-and-packaging)

**By release, review or plan** (in the order they were added):

- [Decided for 2.0 (issue #189 B), recorded in 1.x so the code moved toward them](#decided-for-20-issue-189-b-recorded-in-1x-so-the-code-moved-toward-them)
- [3.0.0 — the floors rise, and the cut defaults decided for 3.0 apply](#300--the-floors-rise-and-the-cut-defaults-decided-for-30-apply)
- [External review, 2026-09-14 (1.17.0)](#external-review-2026-09-14-1170)
- [External review, 2026-09-13](#external-review-2026-09-13)
- [1.15.0 — text people can see](#1150--text-people-can-see)
- [1.16.0 — long-form delivery](#1160--long-form-delivery)
- [1.17.0 — throughput](#1170--throughput)
- [2.1.0 — handing the cut to an editor](#210--handing-the-cut-to-an-editor)
- [2.3.0 — captions that can be seen](#230--captions-that-can-be-seen)
- [2.2.4 — the first bad input, named](#224--the-first-bad-input-named)
- [2.2.6 — silence is reported, not verified](#226--silence-is-reported-not-verified)
- [2.3.0 — short, repeated and silent inputs](#230--short-repeated-and-silent-inputs)
- [2.4.1 — a plain join keeps its picture](#241--a-plain-join-keeps-its-picture)
- [2.6.0 — the GPU](#260--the-gpu)
- [2.7.0 — a second speech engine](#270--a-second-speech-engine)
- [2.8.0 — cuts that say what they did](#280--cuts-that-say-what-they-did)
- [2.10.7 — geometry uses the displayed frame](#2107--geometry-uses-the-displayed-frame)
- [2.10.5 — an accurate cut starts its picture at 0](#2105--an-accurate-cut-starts-its-picture-at-0)
- [2.10.5 — a fixed logo comes off with redact.py --mode delogo](#2105--a-fixed-logo-comes-off-with-redactpy---mode-delogo)
- [2.10.0 — a video layer in a project](#2100--a-video-layer-in-a-project)
- [2.10.9 — FFmpeg 8.0.1 (Ubuntu 26.04)](#2109--ffmpeg-801-ubuntu-2604)
- [2.10.9 — doctor's FFmpeg advisory and the Python 3.9 deprecation](#2109--doctors-ffmpeg-advisory-and-the-python-39-deprecation)
- [2.11.0–2.12.0 — nothing happens silently](#21102120--nothing-happens-silently)
- [2.14.0 — the FFmpeg 5.x deprecation](#2140--the-ffmpeg-5x-deprecation)
- [2.15.0 — render.py's intermediate stages encode with veryfast](#2150--renderpys-intermediate-stages-encode-with-veryfast)
- [2.16.0 — intermediates at superfast, not ultrafast](#2160--intermediates-at-superfast-not-ultrafast)
- [2.17.0 — check.py --content's dropouts row](#2170--checkpy---contents-dropouts-row)
- [2.17.2 — cut.py fades the sound at every --segments join it re-encodes](#2172--cutpy-fades-the-sound-at-every---segments-join-it-re-encodes)
- [2.17.4 — a non-ASCII font path on Windows](#2174--a-non-ascii-font-path-on-windows)
- [2.18 — results carry the VDC paper's co-reported items](#218--results-carry-the-vdc-papers-co-reported-items)
- [2.19.0 — filler words in Korean, Chinese, Russian, Dutch, Polish and Turkish](#2190--filler-words-in-korean-chinese-russian-dutch-polish-and-turkish)
- [2.20 — a length or a silence is checked against a yardstick the tool did not make](#220--a-length-or-a-silence-is-checked-against-a-yardstick-the-tool-did-not-make)
- [2.21.1 — a stream that ends early or decodes nothing fails the check](#2211--a-stream-that-ends-early-or-decodes-nothing-fails-the-check)
- [2.22 — silence.py says where it cut, and where to listen](#222--silencepy-says-where-it-cut-and-where-to-listen)
- [2.23 — check.py --content's flashes and first-frame rows](#223--checkpy---contents-flashes-and-first-frame-rows)
- [2.24 — join.py --copy and cut.py --remove](#224--joinpy---copy-and-cutpy---remove)
- [2.24 — output identity and check.py --compare](#224--output-identity-and-checkpy---compare)
- [2.24 — export.py --max-mb](#224--exportpy---max-mb)
- [2.24 — export.py --repair](#224--exportpy---repair)
- [3.1.5 — both streams on one clock (#409)](#315--both-streams-on-one-clock-409)
- [3.1.5 — square pixels, and the geometry audit (#411)](#315--square-pixels-and-the-geometry-audit-411)
- [3.1.7 — the same mechanisms, where the earlier fixes did not reach (#414)](#317--the-same-mechanisms-where-the-earlier-fixes-did-not-reach-414)
- [3.1.8 — earlier fixes, where they had not reached (#415)](#318--earlier-fixes-where-they-had-not-reached-415)
- [After 3.1.8 — delivery masters (#417–#423, review of #430)](#after-318--delivery-masters-417423-review-of-430)
- [After 3.2.1 — broadcast legal levels, measured](#after-321--broadcast-legal-levels-measured)
- [After 3.2.2 — the alpha path beyond export (#433)](#after-322--the-alpha-path-beyond-export-433)
- [After 3.2.1 — a smart cut that re-encodes only the partial GOPs](#after-321--a-smart-cut-that-re-encodes-only-the-partial-gops)
- [After 3.2.3 — what the output lost from its source is said (#401)](#after-323--what-the-output-lost-from-its-source-is-said-401)
- [After 3.2.3 — two reports from outside (#436, #437)](#after-323--two-reports-from-outside-436-437)
- [After 3.2.3 — what a plugin install copies, and what it leaves out](#after-323--what-a-plugin-install-copies-and-what-it-leaves-out)
- [After 3.3.0 — a declared change scope for `check.py --compare` (#439)](#after-330--a-declared-change-scope-for-checkpy---compare-439)
- [After 3.3.0 — non-finite numbers are refused in one place](#after-330--non-finite-numbers-are-refused-in-one-place)
- [After 3.4.3 — the MCP Registry entry is published by the release, not by hand](#after-343--the-mcp-registry-entry-is-published-by-the-release-not-by-hand)
- [After 3.6.0 — a fold-down, a tone map and an overlay keep the source's levels and depth](#after-360--a-fold-down-a-tone-map-and-an-overlay-keep-the-sources-levels-and-depth)
- [After 3.6.0 — MCP annotations and argument values (audit A9, A10)](#after-360--mcp-annotations-and-argument-values-audit-a9-a10)
- [After 3.6.3 — a tagged version npm never got is finished by dispatch, on its tag (#448)](#after-363--a-tagged-version-npm-never-got-is-finished-by-dispatch-on-its-tag-448)
- [After 3.7.0 — a platform's upload limits are guidance (#485)](#after-370--a-platforms-upload-limits-are-guidance-485)
- [After 3.8.0 — a length that is not stated, and sound trimmed to the sample (#491, #493)](#after-380--a-length-that-is-not-stated-and-sound-trimmed-to-the-sample-491-493)
- [After 3.8.1 — a length or a silence between two milliseconds (the siblings of #493)](#after-381--a-length-or-a-silence-between-two-milliseconds-the-siblings-of-493)
- [After 3.8.3 — the millisecond in fit.py, broll.py and sync.py, and where it changes nothing (follow-ups of #470)](#after-383--the-millisecond-in-fitpy-brollpy-and-syncpy-and-where-it-changes-nothing-follow-ups-of-470)
- [After 3.8.5 — a flag value the tool cannot honour is refused (audit group: out of range, contradictory, ignored)](#after-385--a-flag-value-the-tool-cannot-honour-is-refused-audit-group-out-of-range-contradictory-ignored)
- [After 3.8.6 — the contract says what a dry run decodes, and a pending input has no length (#466)](#after-386--the-contract-says-what-a-dry-run-decodes-and-a-pending-input-has-no-length-466)
- [After 3.8.7 — render.py, batch.py and sequence.py, the audit's remaining findings (#458)](#after-387--renderpy-batchpy-and-sequencepy-the-audits-remaining-findings-458)
- [After 3.8.8 — four old grouped issues, item by item (#402, #403, #404, #429)](#after-388--four-old-grouped-issues-item-by-item-402-403-404-429)
- [After 3.8.9 — captions and text drawing (audit #457, #505)](#after-389--captions-and-text-drawing-audit-457-505)
- [After 3.8.10 — compositing, time and edge inputs (#460, #461)](#after-3810--compositing-time-and-edge-inputs-460-461)
- [After 3.8.11 — a window, a start or a length on the frame or the sample it names (#470's open items)](#after-3811--a-window-a-start-or-a-length-on-the-frame-or-the-sample-it-names-470s-open-items)
- [After 3.8.12 — audit #462: where cut.py, the smart cut and silence.py cut](#after-3812--audit-462-where-cutpy-the-smart-cut-and-silencepy-cut)
- [After 3.8.12 — issue #459: audio, sync, multicam, scenes and waveform](#after-3812--issue-459-audio-sync-multicam-scenes-and-waveform)
- [After 3.8.13 — frame size, colour tags, delivery limits and verify's outputs (#463, #464)](#after-3813--frame-size-colour-tags-delivery-limits-and-verifys-outputs-463-464)
- [After 3.8.13 — tests, CI, distribution and the site (#467)](#after-3813--tests-ci-distribution-and-the-site-467)
- [After 3.8.14 — odd positions, the CFR conform and the timeline's aspect (#512, #506)](#after-3814--odd-positions-the-cfr-conform-and-the-timelines-aspect-512-506)
- [After 3.8.16 — shared code and the MCP server (#465)](#after-3816--shared-code-and-the-mcp-server-465)
- [After 3.8.17 — leftovers of the old grouped issues (#510)](#after-3817--leftovers-of-the-old-grouped-issues-510)
- [After 3.8.18 — side inputs as outputs, the blurred pad's chroma and sequence's frames (#522, #527, #529)](#after-3818--side-inputs-as-outputs-the-blurred-pads-chroma-and-sequences-frames-522-527-529)
- [After 3.8.19 — a brand colour that starts with a digit (#535)](#after-3819--a-brand-colour-that-starts-with-a-digit-535)
- [After 3.8.20 — the decided items of #510](#after-3820--the-decided-items-of-510)
- [After 3.8.21 — variable-frame-rate sources in reverse, speedramp and freeze, and the timeline of several clips (#523, #526)](#after-3821--variable-frame-rate-sources-in-reverse-speedramp-and-freeze-and-the-timeline-of-several-clips-523-526)
- [After 3.8.22 — streams kept: a late-starting sound, audio-only extensions and subtitle tracks (#515, #517, #520)](#after-3822--streams-kept-a-late-starting-sound-audio-only-extensions-and-subtitle-tracks-515-517-520)
- [After 3.8.23 — a still where a clip is expected, RGB input to stabilize, and where fit puts the picture (#531, #519)](#after-3823--a-still-where-a-clip-is-expected-rgb-input-to-stabilize-and-where-fit-puts-the-picture-531-519)
- [After 3.9.0 — caches read in a dry run and stored after the inputs changed (#540)](#after-390--caches-read-in-a-dry-run-and-stored-after-the-inputs-changed-540)
- [After 3.9.1 — a variable-frame-rate cut lays its grid from its start; a hold or pad at the start keeps its last frame (#538)](#after-391--a-variable-frame-rate-cut-lays-its-grid-from-its-start-a-hold-or-pad-at-the-start-keeps-its-last-frame-538)
- [After 3.9.2 — audio-only output extensions, and a still given to export or join (#517, #531)](#after-392--audio-only-output-extensions-and-a-still-given-to-export-or-join-517-531)
- [After 3.9.3 — the timeline of several clips takes its size from fit (#526)](#after-393--the-timeline-of-several-clips-takes-its-size-from-fit-526)
- [After 3.10.0 — a refused stream costs only itself, and an output is what its name says (#539)](#after-3100--a-refused-stream-costs-only-itself-and-an-output-is-what-its-name-says-539)
- [After 3.10.1 — an HDR or BT.2020 RGB source is made YUV with the matrix its line tags (#544)](#after-3101--an-hdr-or-bt2020-rgb-source-is-made-yuv-with-the-matrix-its-line-tags-544)
- [After 3.14.1 — `npx ffmpeg-skill setup`, one command for a new machine](#after-3141--npx-ffmpeg-skill-setup-one-command-for-a-new-machine)
- [After 3.13.2 — file names and unusable inputs (#558)](#after-3132--file-names-and-unusable-inputs-558)
- [4.0.0 — a review page for standalone use (#633)](#400--a-review-page-for-standalone-use-633)
- [After 4.1.0 — one name per meaning, and a guessed name is answered](#after-410--one-name-per-meaning-and-a-guessed-name-is-answered)
- [After 4.1.2 — a number outside what its option takes is refused in one place (#645)](#after-412--a-number-outside-what-its-option-takes-is-refused-in-one-place-645)
<!-- contents:end -->

## Time limits

- **`FFMPEG_SKILL_TIMEOUT=0` (or `--timeout 0`) means no limit on any encode or tool run**, including
  the outer ceiling on sibling-script runs and the MCP dispatch, and ffprobe calls through `run()`;
  the short read-only queries outside `run()` (the version, stream-list and encoder/filter-list
  reads) keep their 120 s ceiling, since a hang there is a stall, not a long job. 0 is the documented "off" value, chosen so
  a genuinely multi-hour job can opt out; the default (1800 s) is what protects an unattended
  agent. Code: `_common.child_limit()`, `_common._limit_for()`, `mcp/server.py` `timeout_from_call()`
  (a raw `argv` list's `--timeout` sets the same ceiling as the structured `timeout` key). Test:
  `test_timeout_kills_a_hung_ffmpeg_and_reports_kind_timeout` (the `--timeout 0` case) and
  `test_mcp_argv_timeout_zero_clears_the_outer_ceiling`.
- **The outer ceiling is 4x the per-call limit plus 60 s, not the per-call limit itself.** A tool
  runs several ffmpeg/ffprobe calls (two-pass loudness, copy-then-re-encode fallbacks), each under
  its own limit; the outer ceiling only exists to end a child hung for a non-ffmpeg reason. Code:
  `_common.child_limit()`. Test: `test_sibling_scripts_run_under_an_outer_ceiling`.

## Dry run

- **Measurement passes run under `--dry-run`; only writes are skipped.** `probe`, `check`, `sync`,
  `multicam`, `scenes`, `cropdetect`, `report`, `silence`, `loudness` and `stabilize` run
  ffmpeg/ffprobe to measure, because a plan built on a fake measurement is not a plan. So does
  `overlay` for a multi-line `--text` on FFmpeg 8.0, 8.0.1 and 8.1.0 (one drawtext on a generated
  frame; see "a multi-line `overlay.py --text`" below), `metadata --auto-chapters`, `cut --snap
  beats`, and `render`/`batch`, whose stages run as their own dry runs (audit A236/A193: the
  contract said `none` for these four; a test now derives the list from what each dry run
  decodes, `test_every_tool_that_decodes_under_dry_run_is_in_dry_run_analysis`). The contract lists them as
  `analysis_only`, `probe` included since "After 3.8.11" below (it was `none` with the note that
  ffprobe still runs, while `--analyze` decodes with ffmpeg); every other tool runs nothing. Code:
  `_contract.DRY_RUN_ANALYSIS`. Tests: `test_dry_run_never_runs_ffmpeg_and_writes_nothing`,
  `test_dry_run_plans_rest_on_real_measurements`.
- **When a measured input is an intermediate an earlier dry-run stage would have written**
  (render/batch plans), the measurement is skipped rather than failing the plan, and the skip is
  recorded: a `diagnostics.skipped` entry (`measurement_input_pending`, once per path) beside the
  stderr line, which until the "nothing happens silently" work was the only "note" there was.
  Code: `_common.dry_run_input_pending()`. Test:
  `test_a_measurement_skipped_for_a_pending_input_reaches_the_document`.
- **`join.py --dry-run` plans on an input that does not exist yet, whatever `--on-missing`
  says.** The file is taken for an earlier step's output (render's cut clips, a TTS line): it
  stays in the planned command and is named under `pending` and in `notes`, never under
  `skipped`, which in a dry run as in a real run holds only what the join left out. A real run
  decides on the file as it then is: refused under `fail`, skipped under `skip` -- and refused
  under `skip` too when skipping leaves fewer than two inputs, which the note then says. Its
  probe is the dry-run stub, whose video stream means nothing, so its extension stands in: an
  audio extension -- any this skill reads (`_common.AUDIO_MEDIA_EXT`: `.wav`, `.m4a`, `.aiff`,
  `.caf`, ...), not only the ones it writes -- is taken for a file with no picture, any other
  for one with a picture, and the measured and pending inputs meet the rules a real run applies
  (all without a picture: an audio join; a mix: refused, naming a measured picture before a
  pending one). The guess can be wrong -- an `.mp4` holding only audio is refused as a mix a
  real run would have joined as audio, and batch.py names every intermediate of a `.ogg`,
  `.opus`, `.aac`, `.aif`/`.aiff`, `.caf` or `.wma` source `.mp4`, so a dry run of a batch join
  step over those sources is refused where the real batch completes (batch.py keeps the
  source's extension only for `.wav`, `.mp3`, `.m4a` and `.flac`; widening that changes the
  container a real run writes, and waits for a minor release) -- but a plan that completes and
  a real run that then refuses the mix, after the earlier steps ran, is the worse error. A
  join's audio rate and layout come from the inputs that exist, and `expected_duration` is null
  while any input is pending: the stub's 0 s would count the clip as nothing. The video join's
  planned frame and rate still come from the first input and its xfade offsets from every
  input's length: a pending first input's frame and rate, and the offsets after a pending
  input, are the stub's unmeasured 0x0 / 0 s, and the plan's `notes` say they are placeholders
  rather than borrowing another clip's (#77 made the stub honest instead of plausible). Code:
  `join.preflight()`, `join.main()`, `join.unpending_length()`.
  Tests: `test_join_dry_run_plans_on_pending_segments`,
  `test_render_dry_run_joins_a_trimmed_and_an_untrimmed_audio_clip`.
- **`join.py --on-silent` defaults to `warn`, not `fail`, at a -50 dBFS peak.** Deliberate
  silence exists: a beat of room tone between lines, a music bed's silent intro, a clip whose
  camera audio is to be replaced later. Refusing those by default would break joins that worked
  in 2.2.5, so the default only names the input (`silent`, `notes`, stderr) and a pipeline that
  knows every segment must speak -- TTS lines -- opts into `fail` or `skip`. The measure is the
  whole-file peak, not the mean or loudness: a failed TTS file is digital silence (volumedetect
  reports -91 dBFS) and any real speech peaks far above -50 dBFS even when quiet, while a noisy
  room-tone take can still peak above it and is then (correctly) not called silent; a mean or
  LUFS gate would flag quiet but real narration. An input with no audio stream is never silent
  (the join adds silence for it on purpose), and an unmeasurable level is left to the join.
  Code: `join.find_silent()`, `join.main()`. Test: `test_join_on_silent_names_a_silent_segment`.
- **`verify` accepts `--dry-run` and ignores it.** Its job is to run the tools for real.
  Contract: `_contract.DRY_RUN_NOTES["verify"]`. Since the flag is ignored, the document says
  `dry_run: false` and a `notes` line says the flag was ignored (audit A240: it said `dry_run: true`
  over outputs it had written). Test: `test_verify_ignores_dry_run_and_says_so`.

## Colour

- **A BT.2020-primaries stream is routed through the HDR (10-bit HEVC, tags preserved) path even
  when its transfer is SDR.** `probe` reports it as `hdr: false`, `bt2020_or_hdr: true`,
  `hdr_format: "BT.2020 SDR"` (see "`hdr` is a real HDR signal" below); the editing tools route
  on `bt2020_or_hdr`. The alternative -- 8-bit BT.709 x264 -- would clip the wide gamut without a
  conversion. Code: `_common.probe()`, `_common.video_args()` docstring.
- **`color.py --to-sdr` converts such a stream's gamut without a tone map.** It is already SDR:
  linearised with its own transfer, mapped to BT.709 primaries and re-encoded with the BT.709
  transfer, white and grey stay where they were. The tone map is kept for PQ, HLG, Dolby Vision
  and `--force` on an untagged file; through 2.2.2 it ran on BT.2020 SDR too and darkened white
  from Y 235 to 151. The result says which path ran (`sdr_path`, `notes`). Code:
  `color.is_bt2020_sdr()`. Test: `test_to_sdr_bt2020_sdr_converts_gamut_without_tonemap`.
- **`cut.py --segments --accurate` reads every segment with `-reinit_filter 0`, so a colour-tag change
  inside the source is a label, not a conversion.** The re-cut feeds one `-ss -t -i src` input per
  segment into one concat graph. By default FFmpeg rebuilds the graph at an input's buffer source when
  its frames change colour tags; on 8.1.2 that rebuild at a *later* input deadlocked at 0% CPU (an
  in-band SPS going from untagged to bt470bg/tv, #316), so a 36-segment job sat until `--timeout`.
  With the option the graph keeps the format it was configured with and the retagged frames pass as
  decoded. That is acceptable because no colour conversion in a cut follows the frames' own tags: an
  SDR output is tagged BT.709 explicitly and tag-only (`bt709_tag_args`), and the one conversion a cut
  can carry (a source whose *probed* matrix is BT.601, `bt709_matrix_filter`) takes the source's
  matrix as an explicit input property, so every segment of one source goes through the same one. An
  untagged source (#316's starts untagged) is relabelled, as before, so the BT.601-tagged later
  segment is no different from an untagged one. The rebuild would have converted the retagged side toward the graph's first (unknown)
  tag (the issue's debug log: `csp:bt470bg -> csp:unknown`), not toward BT.709, so it was no closer to
  the output's label. A BT.2020/HDR source
  still takes the HDR path chosen from the first video stream's probe. The cost: a source whose
  frame *size* or pixel format changes mid-stream is no longer refused by concat's own "parameters do
  not match" error; on 6.1 the first-format graph then crashes or stalls the encoder (the stall is
  bounded by `--timeout`). `silence.py` renders through the same `_join_chunk` (#409), so it has
  the flag too. No other tool builds this structure: `join.py`, `multicam.py` and `broll.py` open
  different files without `-ss`; `speedramp.py` and `freeze.py` split one input, and `loop.py`
  reads one concat list. Code: `cut._join_chunk()`. Test:
  `test_every_segment_input_of_an_accurate_join_keeps_the_graph_format` (the planned command, any
  FFmpeg) and `test_an_accurate_join_across_a_colour_tag_change_completes` (the run; it only fails
  where the deadlock reproduces).
- **`escape_drawtext()` drops `'` and `%` from burnt-in text** instead of escaping them. Both
  characters have no reliable escape across the FFmpeg versions in CI; a missing apostrophe is a
  known limitation, a broken filter graph is not. Test: `test_drawtext_semicolon_and_quote_render_as_inert_literal_text`.
- **`grid.py` composites an HDR input into an 8-bit SDR picture without a tone map.** It produces
  a comparison/inspection artefact, not a deliverable; it prints a note when an input is HDR and
  points to `color.py --to-sdr` for a graded conversion. (`look.py` shows an HDR frame through
  `--to-sdr`'s own tone map: "After 3.6.0" below.) `join.py` and `broll.py`, whose output
  is a deliverable, keep the HDR (10-bit HEVC) path. Test: `test_grid_composites_cols_rows_with_labels`.
- **`look.py -o` is used verbatim only for a single `--at` with an image extension**; several frames,
  or `-o` given as a stem, produce `<stem>_<t>s.png` names. Test: `test_hdr_source_stays_hdr_through_reencodes`.
- **`check.py`'s colour row WARNs on a BT.601 matrix and names `export.py`, not `--retag`.** The
  matrix is a tag (#325): a file tagged only `smpte170m`/`bt470bg` is BT.601, not "untagged". Every
  re-encode here converts it to the BT.709 it tags (the entry below; through 2.10.0 nothing did, and
  this fix said to re-export from the master); `color.py --retag bt709` is a stream copy that only
  relabels it, which shifts the colours of BT.601 pixels, so the fix says that too. Untagged 8-bit
  video, or a BT.709 matrix alone, still passes: players assume BT.709. Code: `check.py`, the colour
  row. Test: `test_check_colour_row_reads_the_matrix_tag`.
- **A source with a BT.601 matrix is converted to BT.709 when it is re-encoded; an untagged one is
  not.** Every SDR line but prores is tagged BT.709, and the tags are labels (`bt709_tag_args`), so
  a `smpte170m`/`bt470bg` (or `fcc`/`smpte240m`) source used to come out labelled BT.709 over
  BT.601 pixels: 48.5 dB YUV PSNR against its source on 6.1, every tag-honouring player showing
  shifted colours. `bt709_matrix_filter()` now converts it with the `colorspace` filter (in every
  FFmpeg build, explicit input properties, so no build's tag negotiation decides it). Untagged
  stays a relabel on purpose: players take untagged SDR as BT.709, and converting it is exactly the
  7.1 auto-conversion `bt709_tag_args` avoids. Only the **matrix** is converted; primaries and
  transfer pass through: the matrix is what every decoder applies, SMPTE-C/EBU primaries are
  shown as BT.709 by every player that does not colour-manage, a full conversion moved testsrc2 to
  22.5 dB RGB PSNR from what such a player shows, and a `bt470bg` (gamma 2.8) transfer tag on SD
  material is usually a label, not the camera's curve. The range is left as it is. The filter
  rides on the encoder line as a `-vf` (`video_args()`, `x264_args(source=...)`, export's preset
  line) and `run()` folds it into the
  tool's own graph as its first step (`fold_bt709_matrix()`), so the tools that re-encode one
  source needed no edit of their own; `join`, `multicam`, `broll` and `overlay --video` convert each
  input by its own tags in its own chain (`matrix_chain()`), since one source's tags say nothing
  about another's. Not converted: a stream copy, a prores master, an HDR/BT.2020 source.
  Measured on 5.1.1, 6.1 and a 7.1 development snapshot that predates 7.1's colour
  negotiation (CI runs 8.x): 42.2 dB RGB PSNR between the source decoded
  as BT.601 and the output decoded as BT.709 (24.8 dB for the old relabel), untagged and BT.709
  sources unchanged. Code: `_common/color.py`. Tests:
  `test_a_bt601_source_is_converted_to_the_bt709_it_is_tagged_with`,
  `test_an_untagged_or_bt709_source_is_not_converted`,
  `test_every_reencoding_tool_plans_the_bt601_conversion`,
  `test_fold_bt709_matrix_into_the_tools_graph`.
- **An RGB picture is converted to BT.709 YUV by an explicit `scale`, where it enters; an untagged
  picture that meets a converted one is labelled, not converted.** An RGB picture (PNG/JPEG still,
  logo, emoji PNG, PNG sequence, qtrle clip) has no matrix of its own: FFmpeg gives it one wherever
  the graph first needs YUV, and its default there is BT.601 (5.1.1, 6.1; 7.1+ follows the link's
  tag, "unknown" = BT.601), so through 2.10.1 every such output was BT.601 under a BT.709 tag: pure
  red decoded (255,24,0), green (0,216,0), mean ΔRGB 8.8 / max 38.9, on 5.1.1, 6.1, 7.1.1 and 8.1.3.
  `scale=out_color_matrix=bt709:out_range=tv,format=…` pins the conversion, so no build's default or
  negotiation decides it: a source gets it as the encoder line's `-vf` (`bt709_matrix_filter()`,
  folded like the BT.601 one, `format=yuv444p` so the tool's own scaling still sees full chroma), a
  still a tool made RGBA (`overlay --image`, emoji, `waveform --image`'s composite) at the end of its
  own chain (`rgb_chain_to_bt709()`, `yuva420p` for overlay). Converting the logo there, not letting
  the overlay filter do it, matters for the video too: with an RGBA input `overlay=format=auto`
  composites in RGB, so the whole main picture went to RGB and came back BT.601 (9.04 mean / 40.6
  max on a BT.709 main with 5.1.1/6.1, 7.93 / 37.4 untagged on every build); with a `yuva420p` logo
  it composites in YUV and the main's pixels are not touched. A palette PNG is expanded to RGB first:
  swscale converts a palette with fixed BT.601 whatever `out_color_matrix` says (9.1 → 0.9 mean on
  5.1.1/6.1). A JPEG probes as `yuvj420p`/`bt470bg` and is a BT.601 source like any other.
  `grid.py` converts each cell by its own tags (`matrix_chain()`): it is an inspection sheet, but one
  whose cells are compared with each other, and on 7.1+ `xstack` converted the cells to one
  another's matrix, so a BT.601 cell first took the BT.709 cell with it. FFmpeg 7.1+ negotiates one
  colourspace for all inputs of a mixing filter and converts the rest to it, taking "unknown" as
  BT.601: with a converted logo the *untagged main* shifted (7.08 mean / 25 max on 7.1.1 and 8.1.3,
  already 7.93 / 37.4 before this fix on 8.1), or the converted picture was converted back. So where
  a converted picture meets an untagged one, the untagged one is labelled BT.709 (`setparams`, tags
  only; `label_chain()`), which is what the output's tag says it is: no conversion is left to
  negotiate, and on 5.1/6.1 the label changes nothing. It is applied only there (a still over the
  video, a grid with a converted cell, and since 2.10.3 a `join`/`multicam`/`broll`/`overlay --video`
  with a converted clip, where an untagged clip beside a BT.601 one was shifted on 7.1+: 7.08 mean /
  25.0 max with the BT.601 clip first, 9.12 / 40.1 with it second, on 7.1.1 and 8.1.3), so a
  one-input re-encode of an untagged source, and a grid or join of untagged/BT.709 clips, keep their
  commands. Known on FFmpeg 7.0.x only (not in CI): its `colorspace` filter does not declare the
  converted link, so a BT.601 clip *first* in `grid`/`join` still takes the others with it; the fix
  would change #332's conversion filter for every tool, so it is left. Code: `_common/color.py`,
  `_common/decision.py`. Tests:
  `test_an_rgb_or_jpeg_source_is_converted_to_the_bt709_it_is_tagged_with`,
  `test_a_still_composited_over_the_video_is_converted_to_bt709`,
  `test_grid_converts_each_cell_by_its_own_tags`,
  `test_mixing_tools_label_an_untagged_clip_beside_a_converted_one`,
  `test_an_rgb_source_or_a_still_is_converted_to_the_bt709_it_is_tagged_with`,
  `test_still_and_rgb_tools_plan_the_bt709_conversion`. These tests' "untagged" clips were tagged
  bt709 when the fixtures were made by FFmpeg 7.1+ (the scale that drew them labels its output, and
  x264 wrote that label): they are relabelled unknown before the encode since 2.10.3, so 7.1+ CI runs
  the untagged case too.
- **A colour the skill draws is drawn in the BT.709 its output is tagged with: on FFmpeg 7.1+ by
  labelling an untagged picture, before 7.1 by drawing on an RGB copy and keeping every pixel the
  drawing did not touch.** A pad, `tpad`, `rotate` fill, `drawtext` font/box/border colour or libass
  colour is turned into YUV by the drawing filter itself (`ff_draw`): with BT.601 on 5.1-7.0 whatever
  the picture is tagged, with the link's colourspace from 7.1 on, "unknown" read as BT.601; `drawbox`
  uses BT.601 on every version, the `color`/`gradients` sources and an RGBA layer went through the
  encoder line's BT.601 default. Through 2.10.2 every drawn colour was BT.601 under the BT.709 tag
  (pure red (255,24,0), pure green (0,216,0): 8.80 mean / 38.9 max ΔRGB on 5.1.1, 6.1, 7.1.1 and
  8.1.3; on 7.1+ only a BT.709-tagged or converted source's pads were right). `drawn_chain()` picks
  the cheapest way that is exact on each build. 7.1+: the untagged picture is labelled BT.709
  (`label_chain()`, tags only) and the filters follow the label; generated ASS says `YCbCr Matrix:
  None`, because 8.x's `ass`/`subtitles` read an absent header as BT.601 whatever the link says
  (FFmpeg's own SRT header already says None). Before 7.1 nothing makes `ff_draw` use another matrix,
  so the drawing runs on an RGB copy (`rgb_island()`: in RGB a colour is written as it is, converted
  back with BT.709), and maskedmerge takes the drawn copy only where it differs from the same round
  trip without the colour: the RGB round trip is not lossless, so the untouched pixels come from the
  YUV picture itself (bit-identical, `--quality 0`). The alternatives: a numeric pre-compensation of
  the colour (the RGB that BT.601 maths turns into the BT.709 YUV) is out of gamut for saturated
  colours -- pure red needs G = -27, and clamped it is as wrong as before (22.6 max), 15% of the RGB
  cube cannot be reached; drawing everything in an RGB copy without the mask changes the whole
  picture; the island on every build costs four scales per frame where 7.1+ needs none, and on 8.x
  an RGB link with a non-None ASS header is drawn in limited range. Boxes, bars and backgrounds are
  colour sources made in RGB and converted (`rgb_chain_to_bt709()`, as #333's logos): a `graphics.py`
  template with a box of chroma draws all its boxes as overlaid colour layers, in their order and
  under its text, which also ends drawbox's 4:2:0 quirk of blending chroma four times over (a 0.55
  box was ~0.96 opaque in colour; the layer blends at the stated alpha; a box starting on an odd row
  or column, which overlay cannot place in 4:2:0, gets a transparent first row/column, so it covers
  the drawbox's pixels); `background.py`'s `color`/`gradients` and `waveform.py`'s plate and RGBA waves are
  converted where they are made. Only a colour whose 8-bit YUV differs between the two matrices
  (`is_neutral_color()`: not a grey, not graphics.py's near-black 101418) changes a command, so the
  default black pads, white text and black/grey boxes plan what they did -- except, before 7.1, on a
  full-range picture in a plain format (next entry), where greys were drawn in the wrong range too.
  Not converted: a GIF export (its pad, if a GIF preset ever had one, would be drawn and read back
  with the same BT.601), a prores or HDR line,
  a caller's own `--ass` file (its colours and YCbCr header are the file's, as libass/FFmpeg read
  them), and the drawn marks on the PNG contact sheets of `look.py`/`scenes.py` (RGB outputs, not
  tagged video; since #410 their picture is read as BT.709, so `look.py --safe`'s red shading, drawn
  by drawbox in BT.601, is a few codes off on an untagged source). Code:
  `_common/color.py` (`is_neutral_color`, `rgb_island`), `_common/decision.py` (`drawn_chain`,
  `pad_filters`), and each drawing tool. Tests: `test_a_pad_fill_or_background_lands_in_the_bt709_its_output_is_tagged_with`,
  `test_drawn_text_and_boxes_land_in_the_bt709_their_output_is_tagged_with`,
  `test_a_picture_that_only_passes_through_keeps_its_pixels`, `test_drawn_colours_are_drawn_in_bt709`.
- **Where pictures are mixed, or drawn on before FFmpeg 7.1, a full-range picture is taken to limited
  range first (#410).** Full range comes as a `yuvj` format (H.264/HEVC/JPEG), which every `scale`
  and `format=yuv420p` here converts by name, or as a plain format tagged `pc` (VP9 and AV1 full
  range, any 10-bit full range), which passes through untouched. concat, xfade, xstack and overlay
  mix samples, not colours, so such a clip beside a limited one in `join`, `multicam`, `grid`, `broll`
  or `overlay --video` was shown in the other's range (C03028 came out C9251B on 6.1), and so were the
  limited-range RGB layers #333 converts (graphics.py's boxes and bars, emoji, `overlay --image`)
  over a full-range main (30B050 came out 37A757). Each such picture's chain now ends with
  `scale=out_range=tv` (`range_chain()`, `layer_base_chain()`; a `yuvj` one also gets its plain format
  name), so every picture the filter mixes is limited and the output is limited, tagged so. The input
  range is left to `scale`, which reads it from each frame: 6.1's scale already turns a full-range
  plain-format frame limited at any resize, so a stated `in_range=pc` would convert some frames twice.
  Before 7.1 `ff_draw` also takes the range from the pixel format alone, so black was drawn 101010 and
  white EBEBEB on such a picture, and `rgb_island()` read a picture 6.1 had already made limited (or a
  10-bit one, drawn on as 8-bit) as full range, oversaturating a colour; `drawn_chain()` takes it to
  limited range there and draws in limited range, greys included. 7.1+ draws in the link's range and
  its drawing commands are unchanged. A one-input re-encode with no drawing keeps the range it had
  ("The range is left as it is" above still holds for the matrix conversion). Not done for an HDR or
  prores line, as `matrix_chain()`. Code: `_common/color.py` (`is_full_range`,
  `limited_range_filter`, `as_limited`), `_common/decision.py` (`range_chain`, `layer_base_chain`,
  `drawn_chain`). Tests: `test_mixing_tools_take_a_full_range_clip_to_limited_range`,
  `test_a_colour_drawn_on_a_full_range_picture_lands_in_its_range`,
  `test_converted_layers_on_a_full_range_main_land_in_its_range`, `test_audit_g_colour_plans`,
  `test_drawn_colours_are_drawn_in_bt709`.
- **An untagged SDR source is labelled BT.709 where a tool turns it into RGB for a picture file
  (#410).** `look.py`'s frames, compare images and contact sheet, `scenes.py --sheet` and
  `export.py --preset gif` let FFmpeg convert to RGB, and that conversion reads "unknown" as BT.601
  (C03028 came out B31F28) while every encoder line here takes untagged SDR as BT.709. The frames are
  labelled first (`bt709_label_filter()`, tags only), as #333's mixing filters do; a tagged source is
  read by its own tag, an HDR one is tone-mapped as before. Test:
  `test_rgb_views_of_an_untagged_source_read_it_as_bt709`.
- **`color.py --retag` rewrites the colour description the stream itself carries, and checks it.**
  H.264, HEVC, MPEG-2, AV1 and VP9 keep it in the bitstream (VUI, sequence header, frame header).
  Decoders, ffprobe included, read that before the container's `colr`/Colour. Through 2.10.10 the
  stream copy set only the container's tags (`-colorspace`/`-color_primaries`/`-color_trc`), so a
  source that carried tags in the stream kept them and the run said `completed` (6.1 and 8.0.1
  alike). The copy now also runs the codec's `*_metadata` bitstream filter (`-bsf:v:0`, in every
  FFmpeg from 5.0 and in each captured `tests/fixtures/ffmpeg_bsfs_*`). That filter rewrites
  headers only, so the copy stays lossless. The range flag is written as the probed range, because
  `h264_metadata` sets limited when the VUI had no signal type. A missing filter is a re-encode,
  not a refusal. Every run probes its output twice: ffprobe's stream tags and the first decoded
  frame's. From 8.1, ffprobe's stream tags follow the container's `colr` while the H.264 decoder
  still outputs the VUI's, so the stream tags alone passed a container-only copy there. A frame
  tag may be unspecified (8.1's ProRes decoder leaves frames untagged), but not different. Other
  tags after the copy mean a re-encode, said in
  `reencoded` and `notes`; other tags after the re-encode mean `kind: verification`. ProRes has no
  filter that writes every target (its transfer field has no BT.601), and ffprobe reads its
  container tag, so ProRes is a container retag. Code: `color.retag()`, `color.retag_bsf()`.
  Tests: `test_color_retag_rewrites_the_tags_the_stream_itself_carries`,
  `test_color_retag_fallback_keeps_extra_audio_and_subtitles_when_it_can`.
- **`--retag`'s re-encode puts the tags on the frames (`setparams`), not in output options.** From
  FFmpeg 7.1 `-colorspace` feeds the graph's colourspace negotiation and the encoder takes the
  frames' tags. A bt709 source retagged bt601 came out with a converted matrix and bt709
  primaries/transfer on 8.0.1 and 8.1.3, its pixels changed. setparams labels the frames, which
  every version's encoder writes: identical pixels and the requested tags on 6.1.1, 7.0.2, 8.0.1
  and 8.1.3. The same rule as `bt709_tag_args()`: on 7.1+ a tag is never an output option on a
  frame that does not already carry it. The other users of those options (`_cpu_encoder_args`,
  `_x265_hdr_default`, `_vt_args`) pass an HDR source's own probed tags, which its frames carry,
  so they convert nothing; one whose probe lacks a tag gets a default there, and that path is
  unchanged here. Code: `color.retag()`. Test:
  `test_color_retag_reencode_fallback_labels_the_frames`.
- **`--correct` converts through bt601 on both legs** (not bt709), because on every tested
  FFmpeg the 709 round trip through 8-bit 4:2:0 loses ~5 dB more than 601. Code:
  `color.py _rgb_stage()`. Test: `test_color_correct_identity_holds_on_a_bt709_tagged_source`.
  This is a YUV picture's working space: the pair cancels because the picture comes in as YUV (an
  RGB source too on the H.264 line, which converts it to BT.709 first). An RGB source (neither HDR nor BT.2020) on an alpha
  line (`--keep-alpha`) meets no matrix on the way in (and the way in names none: with
  `scale=in_color_matrix` on RGB frames, FFmpeg 7.1 wrote BT.601 samples whatever the way out
  asked for), so the way out decides what the file holds:
  bt709 on a line that stores YUV, which is then tagged BT.709 (#496, see "the alpha path beyond
  export"), bt601 on one that stores RGB, where FFmpeg converts back with that default. Code:
  `color.py working_matrix()`. Test: `test_an_alpha_line_shows_the_colour_of_its_source`.
  `--temperature` at its default 6500 adds no term: `colortemperature=temperature=6500` is not an
  identity (it tinted grey 808080 to 7E7E7B, #410). Test: `test_color_correct_defaults_leave_grey_grey`.
- **`--lut` converts through BT.709 on both legs, in float RGB** (#410). A LUT maps the RGB the picture
  really shows, so its legs are the picture's own matrix (BT.709, or BT.601/RGB already converted to
  it on the encoder line), not --correct's working space. Left to libavfilter they disagreed (in by
  the frame's tag, out by swscale's BT.601 default) and an identity LUT shifted every colour (2FAE4E
  to 249A4B); with `gbrpf32le` an identity LUT returns what `--lut-strength 0` does on 6.1, 8- and
  10-bit, limited and full range. A blend (`--lut-strength` below 1) is made in that RGB too. Code:
  `color.py lut_legs()`. Test: `test_color_lut_identity_returns_the_picture`. An RGB source on an
  alpha line takes `working_matrix()`'s legs, as `--correct` does: its qtrle/PNG line got BT.709
  legs and FFmpeg's BT.601 conversion back, and an identity LUT wrote 30C050 as 3CD753 (#496).

## Outputs and files

- **An existing output is refused without `--overwrite`, dry runs included** (2.0; 1.x warned,
  with `FFMPEG_SKILL_NO_OVERWRITE=1` as the opt-in). The refusal is `kind: input` before any
  ffmpeg runs, so a dry run predicts it. A path this same run wrote (two-pass tools,
  copy-then-re-encode fallbacks), or a child tool of this run wrote (render.py's stages, 3.1.6), is
  never someone else's file. Code:
  `_common._check_existing_output()`. Test:
  `test_existing_output_is_refused_without_overwrite_and_never_for_its_own_files`.
  Side files count as outputs (2.2.4): caption.py checks the video and every `.srt`/`.ass` it
  will write (`--text`/`--transcribe`/`--write-srt`, generated or `--write-ass` ASS,
  `_offset.ass`) together before speech recognition and the first write; an `_adjusted.srt` or
  emoji-forced ASS, known only once the cues are laid out, is checked where it is written, still
  before that write. Through 2.2.3 a hand-corrected transcript was replaced on a re-run. Code:
  `_common.refuse_existing_outputs()`. Test:
  `test_caption_sidecars_are_refused_like_the_video_without_overwrite`.
- **The output check is made again where the file is replaced** (#470). The check above runs
  before the encode and decides whether an existing target may be replaced (`--overwrite`, this
  run's own file, `batch.py`'s own delivery); the replace runs after it. The check records each
  target's identity (size, mtime, inode, device: `owned_identity()`, none when absent), a write of
  this run records the identity it left, and under the output lock the write already holds, just
  before the replace, `refuse_changed_output()` compares it again: a different file at the path, or
  one at a path that was absent, was put there by another process during the run and is refused
  (`kind: input`, `reason: output_exists`, `details.outputs[].changed_during_run`), the new
  output's temp removed and nothing replaced -- as `batch.py`'s `deliver()` already did. `run()`
  compares before staging and before its `os.replace`, `place_output()` before its rename and
  before the copy's rename, and a file a tool replaces itself goes through `replace_checked()`
  (export.py's fill and `--normalize`, silence.py's `--timemap`). The check is keyed by the path
  as named (its directory resolved, its last component not), so a symlink created at a target
  that was absent is a new file there, not a different path with no check. Files that belong
  together go through `replace_checked_together()`: export.py stages the key as well as the fill
  (its placeholder counted as this run's own, so run()'s check does not refuse it) and puts both
  in place only when both targets passed, moving an earlier file aside and putting it back if the
  second replace fails, so a refused or failed pair never leaves a new file beside an old one. The
  check also records the directory the path resolved to, and is found by the name as well as the
  resolved place (the name first, so a place another checked path also reaches does not stand in
  for it; a write through another spelling of the same path updates every record of that place):
  a directory link switched during the run is refused, not looked up as a place never checked. A process that ignores the lock file can still write the target between the last
  comparison and the replace. Every temp is removed on any way out short of the replace, a held lock included.
  `--overwrite` still replaces
  whatever is at the path, changed or not: it is consent to replace that path, not one file
  (`deliver()` reads it the same way); a path no check recorded is not compared. What remains:
  `run()` stages only an existing target, so a target absent at the check is opened by ffmpeg
  itself, and a file created at that name after the lock's comparison and before ffmpeg opens it
  is truncated by `-y` (staging every output would rename segment and pattern outputs ffmpeg names
  itself); files written with a plain `open()` after their check (EDLs, SRTs, chapter lists) are
  not compared. Code: `runner.refuse_changed_output()`, `replace_checked()`, `run()`,
  `place_output()`. Tests: `OutputChangedDuringRunTests` in `tests/test_contract.py`
  (`test_a_target_replaced_during_the_encode_is_refused_and_an_unchanged_one_replaced`,
  `test_a_target_created_after_the_check_is_refused_unless_overwrite`,
  `test_overwrite_still_replaces_a_target_swapped_during_the_encode`,
  `test_place_output_refuses_a_target_put_there_after_its_check`,
  `test_a_side_file_a_tool_replaces_itself_is_rechecked`, `test_a_link_created_at_an_absent_target_is_refused`,
  `test_files_committed_together_are_both_kept_back_when_one_is_refused`, `test_a_refused_lock_removes_the_staged_file`,
  `test_a_pair_whose_second_replace_fails_leaves_what_was_there`,
  `test_a_directory_link_switched_during_the_run_is_refused`; `test_export_key_fill_without_overwrite_writes_both`
  in `tests/test_delivery.py`).
- **An existing output is written through a hidden sibling temp file and replaced only on
  success**, so a failed run never costs the caller the file that was there (FFmpeg 5.x truncates
  the output before a filter error). The temp name `.<stem>.ffskill-<pid><ext>` is expected in the
  output directory during a run; it is created exclusively (`O_EXCL`), so an entry already at that
  name, a planted symlink included, is never written through, and the next free
  `.<stem>.ffskill-<pid>-<n><ext>` is used instead. A copy the tool makes itself (`place_output`,
  `batch.py`'s cross-filesystem delivery) writes the descriptor that created the temp
  (`copy_to_sibling()`); ffmpeg opens its temp by name, so a process that may delete entries in
  the output directory could still swap the file between the create and that open, which a
  sticky shared directory (`/tmp`) and a directory only the caller can write both rule out. A private
  subdirectory for those temps would not close it either (whoever can rename entries in the output
  directory can swap the subdirectory for a link, and ffmpeg cannot open relative to a directory
  descriptor), so this residual case is accepted (#456). A lock's default audit log beside the output
  is opened without following a symlink; a log named with `--audit-log` is opened as named. Code:
  `_common._stage_existing_output()`, `runner.reserve_sibling()`, `emit.audit()`. Test:
  `test_hidden_temp_names_are_never_written_through_a_planted_link`.
- **A file ffmpeg would read as a playlist is refused whatever it is called.** HLS and ffconcat
  are told by name or their first bytes; a DASH manifest and an IMF composition playlist by name
  or by the strings ffmpeg's own probes look for (`<MPD` with `dash:profile`, `<CompositionPlaylist`
  with `ContentTitle>`), anywhere before the first NUL byte, because ffmpeg probes the whole probe
  buffer: a manifest saved as `clip.mp4` made every tool follow its BaseURL to another local file
  or over HTTP, and FFmpeg 6.1's `-protocol_whitelist file` did not stop the HTTP request. A media
  file has a NUL byte within its first bytes, so the scan stops there. `subfile,<options>:<url>`
  is refused as a URL like any other protocol prefix. A path with a line break is refused where it
  would be written into a concat list (`media_path_has_line_break`): the format has no escape for
  one. Code: `runner._refuse_playlist()`, `runner.looks_like_url()`, `decision.concat_list_line()`.
  Tests: `test_a_playlist_input_and_an_option_shaped_output_are_refused`,
  `test_a_url_never_reaches_ffmpeg_as_an_input_or_an_output`,
  `test_a_path_with_a_line_break_never_reaches_a_concat_list`.
- **Subtitle/data tracks are kept where the picture's timeline is untouched and dropped where
  it is retimed; both cases report `dropped_non_av_streams`.** Tools that re-encode the picture
  or audio in place (`fit`, `color`, `crop`, `stabilize`, `graphics`, `overlay`, `audio`, `loudness`, `proxy`,
  `deinterlace`, `denoise`, `redact`, `sphere`, `straighten`, `freeze` holding the last frame) try
  `run_keeping_subtitles()` first, a text track converted to the container's own format as
  `export` converts it (since #520), and report `false` unless the container refused a stream (since #539 a refused data stream is retried away alone and does not cost the track beside it: "After 3.10.0"). `export` does the same with its own
  ladder (`_run_keeping_non_av()`): a text track is converted to the container's own (mov_text in
  .mp4/.mov, SubRip in .mkv) rather than refused, a data stream the container refuses (a camera's
  timecode in .mp4) is retried away alone so the subtitles survive it, a platform trim cuts the
  track with the picture, and `non_av_streams` lists every stream kept or dropped. Test:
  `test_export_keeps_the_subtitle_track_for_every_preset_whose_container_holds_one`. Tools that move the timeline
  (`cut` re-encode, `pad --start`, `freeze` inside the clip or at its start, `fit --method speed`, `speedramp`,
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
  `package.json` `files`, `bin/install.js` `PAYLOAD`. Test: `tests/release_check.sh` (the packed
  tarball and the install made from it must not contain the file; that script needs npm) and
  `test_npm_package_omits_the_maintainer_diary` (pins the `files` allow-list, which is what CI
  runs — Windows cannot spawn `npm`, and the debian-trixie job has nodejs without npm).
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

## 3.0.0 — the floors rise, and the cut defaults decided for 3.0 apply

- **Python 3.10 and FFmpeg 6.1 are the floors (`requirements.python` `>=3.10 (standard library
  only)`, `requirements.ffmpeg`/`ffprobe` `>=6.1`).** The two 2.x deprecations (Python 3.9 in
  2.10.9, FFmpeg 5.x in 2.14.0, both below) moved from `contract --json`'s `deprecated` to
  `removed`, so `deprecated` is empty again. CI's Python floor is 3.10 (plus 3.13), and the 5.1.1
  static job is gone: CI runs 6.1 (Ubuntu 24.04 apt), 7.1 (Debian trixie), 8.x (macOS Homebrew),
  9.x (Windows gyan.dev) and 8.0.1 (Ubuntu 26.04 apt). The 90-day half of the deprecation
  window was waived in writing (`docs/contract.md`, "Deprecation policy"). Code:
  `_contract.REMOVED`, `_contract.MIN_PYTHON`/`MIN_FFMPEG`, `bin/install.js`'s `PYTHON_PROBE`.
  Test: `test_3_0_removed_python_3_9_and_ffmpeg_5_on_every_surface`.
- **An FFmpeg older than 6.1 is refused, not warned about.** 2.x kept the 5.x and 6.0 code paths
  (drawtext's single-value `boxborderw`, among others) and printed a warning; 3.0.0 deleted those
  paths, so an old build would no longer fail cleanly here -- it would fail later in some other,
  worse way (a filter option it rejects halfway through a render). Every tool's first
  `ffmpeg`/`ffprobe` lookup therefore refuses a version it can read as older than 6.1, with
  `kind: missing_tool` (exit 127), `error.reason: ffmpeg_unsupported` and `details: {version,
  required}`; `doctor` lists the line in `unsupported` and reports `ok: false`, and the `npx`
  installer prints the same line. A git or vendor build whose version is not a release number
  (`N-12345-g…`) is **not** refused: its age cannot be read, the same rule as the security
  advisory, and refusing it would lock out exactly the newest builds. Code:
  `runner.require_tool()`, `_contract.ffmpeg_unsupported()`, `_contract.doctor()`. Tests:
  `test_every_tool_refuses_an_ffmpeg_older_than_6_1`,
  `test_doctor_reports_an_unsupported_python_or_ffmpeg_and_fails`.
- **A Python older than 3.10 is not refused by the tools themselves, only reported.** The
  installer skips such an interpreter (and warns when it finds none), and `doctor` lists it in
  `unsupported` with `ok: false`; the scripts do not check their own interpreter version.
  Code: `bin/install.js` `findPython()`/`warnMissingPython()`, `_contract.python_unsupported()`.
- **The "Decided for 3.0" defaults now apply (2.8.0 section below).** `cut.py` keeps the edit list
  on a single `.mp4`/`.mov` stream copy (`--no-edit-list` restores `-avoid_negative_ts make_zero`);
  an SDR HEVC source's re-encode stays HEVC, x265 8-bit BT.709 (`--no-keep-hevc` restores x264);
  `--vfr-guard` defaults to `sampled` (`--vfr-guard average` restores 2.x). `--edit-list` and
  `--keep-hevc` are still accepted, so a 2.x command line runs unchanged. `precision` is the least
  exact segment's (equal to `least_exact_precision`, which stays) and `keyframe_snapped` equals
  `start_snapped`; `contract_version` is `2.0`. Code: `cut.main()` (the `--no-` flags and
  `KEEP_HEVC`), `cut.report_precision()`. Tests: the cut-copy tests in `tests/test_cut_copy.py`
  that pin a default `.mp4` copy keeping its edit list, an SDR HEVC re-encode staying HEVC
  (`test_sdr_hevc_is_encoded_as_hevc_8bit_bt709`, `test_a_reencoded_cut_of_an_sdr_hevc_source_stays_hevc`)
  and the sampled VFR guard by default, and the precision tests in `tests/test_editing.py` that pin
  `precision` as the least exact segment's and `keyframe_snapped` as `start_snapped`.

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
  Since the SKILL.md restructure after 3.1.1 the full Japanese five-line example lives in
  `references/report.md`; SKILL.md keeps the rule with its Japanese `Check:`/`Look:` lines.
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
  every version up to 2.0.0 shipped + evaluated (naming the iteration), shipped with eval pending, or
  planned, and the reconciliation is against `CHANGELOG.md` and `evals/results/`. It has no entry
  for a release after 2.0.0; `CHANGELOG.md` is the record of those.
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
  uses whole-event bidirectional layout (`Encoding -1`) for generated styles with RTL text.
  The logical prefix of an Arabic or Hebrew line is the *right* part of the
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
- **SRT markup on `caption.py`'s own ASS route is the set ffmpeg's SRT reader styles, minus
  free override blocks.** `<i> <b> <u> <s>`, `<font color>` and a `{\anN}` become the overrides
  ffmpeg writes for them, so `--animate`/`--karaoke` draw what the plain `--srt` route draws. Any
  other `{\...}` block stays escaped text there, although ffmpeg's SRT route would apply it: cue
  text (an SRT, `--text`, a transcript) must not be able to `\pos`, `\t` or `\fscx` itself, which
  1.15 decided and this keeps. An unknown `<tag>` stays text too (ffmpeg removes it), so a
  caption that says `press <Enter>` is not shortened. Under `--karaoke`, `<font color>` is
  dropped: the highlight is the primary colour, and the cue's colour would replace it. Tests:
  `test_srt_markup_becomes_ass_overrides_not_text`,
  `test_caption_ass_dialogue_text_cannot_forge_override_blocks`.


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
Since 2.2.4 they are launched as `render.py` launches its stages: `run_tool()` with
`child_args()` and `--json`, so `--overwrite`, `--timeout`, `--fast` and `--dry-run` reach
them, and a failed stage is re-raised with the child's own kind, exit code and hint (a private
launcher had forwarded only `--dry-run` and called every failure `kind: ffmpeg`). The `vis` /
`titled` intermediates are hidden, pid-named siblings of the output (`sibling_temp`, #408) and are
removed on the failure path too: through 3.1.3 they were `<out>_vis` / `<out>_titled`, and the
removal took whatever file had that name, the input or a file of the caller's included. A missing `--srt`/`--text`
is refused before the visualisation is encoded. Under `--dry-run` only, `--title` passes
graphics.py an explicit `--end` (the source's duration) because the `_vis` file it would probe
was never written; a real run's commands are unchanged. Tests:
`test_waveform_srt_and_title_rerun_with_overwrite`, `test_waveform_title_dry_run_completes`,
`test_waveform_missing_srt_is_input_before_any_encode`, `test_waveform_never_removes_a_file_it_did_not_write`.

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
usable fillers without `like`, Japanese does not have usable fillers without `なんか`. For the
same reason Chinese `啊` is out of the `zh` list: it is a sentence-final particle far more often
than a hesitation, so cutting it changes sentences; `--filler-extra 啊` adds it for a speaker who
uses it as one.

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
  clip lengths minus one transition per join -- what `join.py`'s xfade renders by design. Since
  the Unreleased fix after 2.2.2, `join.py` offsets each crossfade by the part's video-stream
  length (its audio's only when the sound runs more than a frame past the picture), no longer
  the *container* duration with its audio priming, so a render matches this total to the frame.
  Tests: `test_build_centres_each_dissolve_and_keeps_the_rendered_length`,
  `test_join_dissolve_of_short_parts_keeps_the_frame_count`,
  `test_join_transition_keeps_each_clips_sound_with_its_picture`.
- **What a timeline cannot carry is reported, never dropped.** Captions, graphics, overlays,
  the silence cut, fit, audio processing, loudness and the export preset go to
  `timeline.not_exported` and stderr. A caption track or a title in FCPXML would be a second
  implementation of `caption.py`/`graphics.py` whose output no one here can see.
  Test: `test_build_refuses_what_a_timeline_cannot_hold`.
- **The sequence is the project's frame, sized by fit.py's own rule, and the render delivers
  that size.** The project's `frame` goes through `frame_from_preset()` (an aspect-only frame
  takes the export preset's size when the preset has that aspect) and then `frame_size()`, the
  function fit.py sizes its output with: one side and an aspect give the other, so
  `{aspect 16:9, width 1920}` is 1920x1080 over any source (2.1.0-2.2.1 took the height from
  the source: 1920x2160 over 4K). The aspect is read with `aspect_ratio()`, which fit.py now
  reads `--aspect` with too: two sides split at `:`, each read with `int()` as fit.py read them
  in 2.2.1 (`+16:9` and `1_6:9` parse, `0:9` is a zero ratio that sizes as no aspect). So the
  export refuses `16/9` where the render hands it to fit.py, which refuses it too, and fit.py
  refuses nothing it took in 2.2.1. The sequence takes the project's `fit` object first and the
  frame only where it has none, as the render's fit stage does: for one clip since #506 (in the
  "After 3.8.14" section below), for any number of clips since #526 ("After 3.9.3", the last
  section), so a frame aspect fit.py would refuse is no longer read where `fit.aspect` replaces
  it. `frame_from_preset()` keeps 2.2.1's looser match (`16/9`, `1.78:1`) for the
  preset size: it drops nothing a 2.2.1 render was sized by.
  A render of several clips gave fit.py the frame's side only when the frame gave an aspect and
  one side and the `fit` object no width, height or other aspect (before that, `{aspect 9:16,
  width 1080}` over 16:9 clips rendered 342x608); every other `fit` object was fitted inside the
  joined picture. Since #526 it gets the frame's sides by the one-clip rule, and a frame of one
  side gives join.py the other side fit.py would compute, so a project renders the size its
  sequence states whatever its number of clips. One render gap remains, in the picture and not
  its size: join.py pads every clip into the joined frame before fit.py crops, the frame's own W x H when it gives
  both sides (as every template frame does after `frame_from_preset()`), else the first clip's
  aspect. So a multi-clip `frame.fit: crop` render keeps bars on every clip of another aspect
  than that frame, even when all the clips share one aspect, while the timeline states
  `fill`, the project's choice (the timeline follows the project, not the render's drift).
  Passing `frame.fit` to join.py would change rendered output and is not part of #526.
  Tests: `test_sequence_frame_is_the_frame_the_render_delivers`,
  `test_a_multi_clip_render_delivers_the_sequence_size`,
  `test_a_sequence_of_several_clips_takes_the_fit_objects_frame`,
  `test_the_export_and_fit_py_read_one_aspect_grammar`,
  `test_render_frame_aspect_takes_the_export_presets_size`.
- **A clip of another aspect is a reframe FCPXML states and EDL and OTIO cannot.** FCPXML's
  `adjust-conform` is written on each such clip, `fill` for `frame.fit: crop` and `fit` for pad
  (the DTD reads a missing one as fit, so leaving it out exported every crop as a fit). blur
  has no conform: the clip is fitted, and the blurred background is named in `not_exported`.
  EDL and OTIO have no field for a conform, so there the reframe is named in `not_exported`
  with the project's `frame.fit`, and the editor's default decides. Each FCPXML video asset
  carries its own source's format (size and frame rate) and the sequence the frame's: with one
  format for both, a 320x180 asset under a 9:16 frame claimed to be 1080x1920.
  Test: `test_fcpxml_describes_each_source_and_states_the_conform`.
- **Times are read the way render.py's own stages read them.** `clips[].in`/`out` take
  `parse_time()`'s grammar at the source's fps, as cut.py reads them. `frame.fps` does not stand
  in: cut.py has no other fps to use, so a clip with no picture needs `@fps` on an
  `hh:mm:ss:ff` time in both paths. A chapter's `at` takes no fps, as metadata.py reads it, so
  `hh:mm:ss:ff` there needs its `@fps` in both paths too. Neither path accepts a time the
  other refuses. A time that does not parse is `kind: input` (2.1.0-2.2.1 called `float()`,
  and `--init`'s own `"in": "0:00"` was a traceback).
  Tests: `test_times_are_read_with_the_render_grammar`,
  `test_a_bad_time_is_an_input_failure_not_a_traceback`.
- **A value that is not an object is refused only where the run reads it.**
  `validate_project()` refuses it as `kind: input`, naming the key, before the first stage.
  In both paths that covers a string `frame`, a clip written as a bare path, a clip with no
  `src`, a string `audio` and a string `transition` between two or more clips. In the render
  it also covers every stage section (`"export": "reels"`, `"captions": "subs.srt"`) and the
  `snap` of a clip it cuts, up to the `--stop-after` stage: a section read only after it
  (`"captions": "subs.srt"` under `--stop-after fit`, a string `transition` under
  `--stop-after clips`) is not refused, as 2.2.1 completed those previews. A full run of each
  of these died in 2.2.1 with a traceback and nothing on stdout under `--json`. A value
  the run never reads is left as 2.2.1 left it. That is a single
  clip's `transition` (a batch.py project recipe that carries join.py's `--transition none`),
  an uncut clip's `snap`, and, in `--export-timeline`, every section it only lists in
  `not_exported`. Those projects rendered or exported in 2.2.1, and a patch release does not
  refuse them. So for these shapes the export can accept a project the render refuses, as in
  2.2.1. Refusing them in both paths is deferred to a minor release. Code:
  `render.validate_project()`, `render.require_object()`.
  Test: `test_a_bad_time_is_an_input_failure_not_a_traceback`.
- **OTIO's `source_range` is timeline length, with the speed in a `LinearTimeWarp`.** Core
  OTIO does not rescale a clip's duration by its effects; the first version stored the
  speed-scaled source length and the reference `opentimelineio` library (0.18) measured the
  track at 253 frames for a 225-frame cut. Test:
  `test_otio_track_lengths_add_up_without_counting_transitions`.
- **Verified here: structure and arithmetic; not verified here: an editor opening the file.**
  All three formats were read back by the reference OTIO library and its FCPXML / CMX 3600
  adapters at the right length, but none of Final Cut, Resolve or Premiere is available in this
  environment, and OTIO's own FCPXML adapter ignores dissolves, markers and retiming, so those
  parts of the FCPXML are checked against Apple's FCPXML 1.10 DTD with `xmllint --dtdvalid`, by
  hand: the DTD ships inside Final Cut, not in this repository, so no test reads it. 2.1.0 made
  the same claim and its files did not validate: the music bed came after the chapter markers
  inside the first clip, where the DTD's `asset-clip` holds `timeMap`, then the `adjust-*`
  elements (`adjust-conform`), then anchored items (the connected music clip), then markers.
  That order is pinned by `test_fcpxml_spine_matches_the_cut` and
  `test_fcpxml_keeps_the_dtd_child_order_on_a_retimed_first_clip`. OTIO's FCPXML adapter
  reads each clip's offset at its asset's frame rate and compares the frame counts across
  rates, so a project mixing source rates reads back there with gaps the file does not have
  (the file's offsets are rational seconds). The editor round trip is on #143's real-hands
  checklist.


## 2.3.0 — captions that can be seen

- **A burn that draws nothing is a refusal, not a warning.** `caption.py` counts the non-blank
  cues overlapping `[0, duration]`; none (a cue file timed for a longer cut, all-blank text, an
  `--ass` without `Dialogue` lines) is `kind: input`, because the output would be the input
  re-encoded and `verified: true` would be false at the layer a caller reads. Some cues outside
  is only a warning with `cues_outside`: trimming a clip out of a longer transcript is normal.
  With no probed duration every non-blank cue counts as drawn. `--mode mux` is not checked; a
  soft track draws nothing by itself. Tests: `test_caption_refuses_cues_that_are_never_visible`,
  `test_caption_reports_cues_burned_and_outside`, `test_waveform_srt_outside_the_render_is_refused_as_input`.
- **Whitespace-only text flags are missing, not text.** `graphics.py` maps a blank
  `--title`/`--name`/`--subtitle`/`--text`/`--top`/`--bottom` to unset before the template's own
  "needs --title" check; non-blank text is drawn exactly as given (not stripped). `overlay.py
  --text "  "` is refused. Test: `test_graphics_and_overlay_refuse_blank_text`.

## 2.2.4 — the first bad input, named

- **Every bad extra input is refused together, before ffmpeg runs.** The same rule 2.2.0/2.2.1
  gave `join.py` and `render.py`: `audio.py` checks every `--replace` / `--music` / `--effects`
  file (missing, empty, unreadable, or no audio stream) and names all of them in one
  `kind: input` refusal with `problems: [{flag, path, reason}]`, under `--dry-run` too (a file
  that does not exist yet stays pending, as in join.py). `render.py`'s real run now adds the
  ffprobe readability check to its clip-source preflight, so every unreadable source is named at
  once, as its dry run already did through join; the dry run itself is unchanged. `sync.py` and
  `multicam.py` name the file that is too short to analyse. No success path's command line
  changed. Tests: `test_audio_beds_without_audio_are_refused_together`,
  `test_render_real_run_names_every_unreadable_clip_source`, `test_sync_too_short_names_the_file`,
  `test_multicam_too_short_names_the_file`.


## 2.2.6 — silence is reported, not verified

- **A silent track warns by default, and refuses only on request.** `audio.py` measures the
  whole-file peak of each `--music` / `--replace` / `--effects` file and, under `--duck`, the
  voice. Default `--on-silent warn` still mixes it (a deliberately silent placeholder bed is a
  real use, and join.py's `--on-silent` takes the same default and -50 dBFS peak threshold) but
  names it under `silent` and in a note; `--on-silent fail` makes it one more `problems` entry in
  the 2.2.4 refusal. Peak rather than mean: a sparse effects track with a quiet mean is not
  silent. Tests: `test_audio_silent_beds_warn_by_default_and_fail_on_request`,
  `test_audio_duck_under_a_silent_voice_is_reported`.
- **Non-finite numbers are strings, not `-Infinity`.** `print_json` maps -inf/inf to `"-inf"` /
  `"inf"` and NaN to `null` and serialises with `allow_nan=False`: a JSON-valid document beats a
  numeric type for a value that has no JSON number, and `"-inf"` is what `loudness.py` already
  reported. A silent export's note says the audio is silent; loudness.py cannot fix that, so it
  is neither recommended nor run by `--normalize`. Test:
  `test_audio_every_tool_json_on_silent_input_parses_strictly`.
- **`check.py --content` is opt-in, and its thresholds are loose.** The black / frozen /
  silence rows cost a full decode of the file (one pass, blackdetect + freezedetect +
  silencedetect), where the default rows cost an ffprobe and one audio pass; and a black
  intro, a held title card or a silent B-roll montage are real edits, so they would be noise on
  every delivery. Thresholds: `black` WARN above 10% of the duration, FAIL at >= 95% (all
  black, allowing blackdetect's last-frame shortfall); `frozen` WARN when the longest frozen
  span exceeds max(3 s, 30% of the duration) -- a 3 s title hold is normal, a stuck third of a
  short is not -- FAIL at >= 95% (the whole video frozen); `silence` WARN above 50% below
  -50 dB, FAIL at >= 95%. Only FAIL means "almost certainly a broken render". The default row
  set is byte-identical without the flag. Tests: `test_check_content_rows`,
  `test_check_default_rows_unchanged_without_content`.
- **`check.py`'s `audio` row flags a silent track even without `--content`: FAIL under a loudness target, WARN with none (a muted screen recording is legitimate).** A present
  stream at or below -50 dBFS peak (2.2.6's threshold) is the empty-TTS / muted-export case
  that "present" used to pass; it costs nothing when the loudness pass ran (its true peak is
  read) and one volumedetect pass when loudness is skipped. Test:
  `test_check_audio_row_fails_on_silent_track`.

## 2.3.0 — short, repeated and silent inputs

- **A short or repeated join input warns; it never refuses.** A clip under 2 frames (audio-only:
  0.05 s) is almost always a failed earlier step, but a repeated clip (an intro used twice, a
  loop) is a real edit, and the frame count cannot tell a deliberate one-frame flash from a bug.
  Both are named under `short_segments` / `duplicates` and in notes; `verified` and the ffmpeg
  command are unchanged. Test: `test_join_warns_on_short_segments_and_duplicates`.
- **A silent waveform input warns by default, like audio.py.** `waveform.py --on-silent`
  takes audio.py's default (`warn`) and -50 dBFS peak threshold; `verified` stays about the
  render (size, rate, duration) so the top-level and `audiogram.verified` never disagree, and
  `silent` is the key a caller reads. `--dry-run` measures nothing and says `null`. Test:
  `test_waveform_silent_input_warns_or_fails`.
- **"Found no speech" is not "no engine".** An engine that ran and returned no cue is refused
  as `kind: input`, `reason: "no_speech"`, naming the engine and the caller's input rather than
  the engine's deleted temporary SRT. Tests: `AsrNoSpeechTests`.

## 2.4.1 — a plain join keeps its picture

- **A plain `join.py` cut gives each clip one length, as a crossfade does.** The concat filter
  starts the next clip after the *longer* stream of this one, so the picture of a clip whose sound
  runs past it -- a music bed padded to the container, or only an AAC tail -- got a hole (measured:
  0.3 s, and one frame from a 20 ms tail). `clip_length` decides the length for both paths: the
  sound's when it runs more than a frame past the picture (the last frame is held; narration is never
  cut), the picture's otherwise (the tail is trimmed). Tests:
  `test_join_none_holds_a_picture_shorter_than_its_sound`,
  `test_join_none_trims_a_sound_tail_under_a_frame`.
- **That length is a whole number of frames of the join's rate, and its sound the samples those
  frames last** (#455, #468). The rate is an exact fraction (the first clip's `r_frame_rate`, so
  30000/1001 and not 29.97, or `--fps` through `timeline.exact_rate`); the picture's length is
  rounded to the nearest frame, a sound past it rounded *up* to the frame that covers it (narration
  is still never cut), and the transition to the nearest whole frame (at least one). The graph cuts
  with `trim=end_frame` and `apad=whole_len`/`atrim=end_sample`, sample counts taken from the
  running frame total so the sound never drifts more than a sample from the picture, and
  `acrossfade=ns` overlaps exactly the frames xfade does. Each xfade offset is its frame's time
  rounded *down* to the microsecond, because xfade starts on the first frame at or after it: a
  length or offset written to the millisecond and rounded up put the next clip or the fade one
  frame late (one-frame holes from about 8 s for 60 five-frame clips; 138 frames where 137 were
  due). The picture chain keeps the fps filter's time base (one frame) instead of `settb=AVTB`, so
  every timestamp downstream is a frame number and a microsecond offset rescales to its frame on
  any FFmpeg. `clip_frames`, `transition_frames` and `frame_rate` report what was used. Code:
  `join.output_rate()`, `join.clip_frames()`, `join.frame_time()`. Tests:
  `test_join_clip_lengths_are_whole_frames_and_samples`, `test_join_transition_starts_on_its_frame`.

## 2.6.0 — the GPU

- **`--hw` is opt-in, and a delivery preset needs it explicitly.** Measured first on an M4 Max
  (FFmpeg 9.0, three 1080p SDR clips) and re-measured with `tests/bench_vt.py` on an M3 (FFmpeg
  9.0.2, SSIM against x264/x265 `medium` at CRF 18/23/28, iPhone footage included): VideoToolbox
  is 2–7× faster but needs 1.1–2.9× the bytes for the same SSIM on SDR and 1.9–3.5× on HDR. A draft or an
  intermediate is the place for speed; a file that is uploaded is the place for bytes. So
  `FFMPEG_SKILL_HW=1` changes every re-encoding tool's default but not `export.py`'s delivery
  presets, and `render.py --hw` is the one switch that puts a whole project, export included, on
  the GPU. It is never switched on by anything else (not `--fast`, not a detected GPU), with one
  exception: a build that has no libx264/libx265 to choose instead (next entry). An
  `export.py` run under the variable says in `hw` (`requested: false`, `source: env`, a note) that
  the preset stayed on the CPU and that `--hw` moves it. Code: `_common.runner.apply_common`,
  `add_hw_orchestrator_args`. Tests: `HwResolutionTests`, `test_export_preset_needs_an_explicit_hw`
  (a dry run with VideoToolbox stood in, so it runs on every CI runner),
  `test_the_env_default_reaches_the_other_re_encoding_tools`.
- **A build without libx264 or libx265 encodes on VideoToolbox without `--hw`, delivery presets
  included (#314).** The reasons above are about a choice: speed against bytes. An LGPL ffmpeg (a
  desktop app ships one) has `h264_videotoolbox`/`hevc_videotoolbox` and neither x264 nor x265, so
  the CPU line is not a slower option, it fails ("Unknown encoder 'libx264'"), and "a file that is
  uploaded is the place for bytes" and "never switched on by anything else" have nothing to protect.
  So when the encoder list (`ffmpeg -encoders`) was read and lacks the CPU encoder the line would
  name (libx264 for H.264, libx265 for HEVC, each on its own), the matching VideoToolbox encoder is
  in it, and this machine passes `hw_platform_reason()` (Apple Silicon, the check `--hw` uses), every
  re-encoding tool and every fixed `export.py` preset (`reels`, `youtube`, `h265`, ...) takes the
  VideoToolbox line, built exactly as under `--hw`. The result says `hw: {requested: false, source:
  "auto", used, ...}` with a note naming the encoder that was missing and the one that ran, and the
  usual `notes` line that the quality is not CRF-equivalent (without the `--no-hw` advice: it has no
  CPU encoder to go back to). What does not change: a build that has the CPU encoder takes exactly
  the line it did (the platform is asked before the encoder list, so Linux and Windows read no list
  for this, and the Mac reads it once per process); `FFMPEG_SKILL_HW=1` still does not move the
  presets (the request to make it cover them was declined: with libx264 in the build the preset
  stays where the first entry puts it, and without it the build decides, so the variable has nothing
  left to add); an explicit `--no-hw` (or `render.py`/`batch.py --no-hw`) is the caller's choice of
  the CPU and is not overridden, ffmpeg then refuses it as before; `FFMPEG_SKILL_HW=0` is no flag
  and does not stop it; AV1 and ProRes are out of scope (their own missing-encoder refusals stand).
  An unreadable encoder list (empty) proves nothing is missing, so here it moves no encode onto
  VideoToolbox. (Through 2.10.11 this sentence said it "changes nothing", which held only for this
  function: the same empty set made `--codec av1`/`prores` refuse with "this build has neither" and
  `--hw`'s note say "this ffmpeg build has no h264_videotoolbox". The read failure is now kept and
  named -- see "nothing happens silently", the encoder list.) No CPU line is
  recorded for it, so a job VideoToolbox refuses is a plain `kind: ffmpeg` failure naming
  `h264_videotoolbox`, not a retry that could not run. `doctor` agrees: a missing
  `encoder:libx264`/`libx265` whose VideoToolbox encoder is in the build, on a machine that passes the
  same check, is listed under the additive `covered_by` and in neither `available` nor `missing`, so
  `ok` and each tool's `usable` stand for what will run; the contract's `required`/`optional`
  capability lists are unchanged. Code: `_common.decision._vt_in_place_of`, `_maybe_hw`,
  `hw_preset_video`; `_contract._covered_by_videotoolbox`. Tests: `NoCpuEncoderTests`,
  `test_a_build_without_libx264_is_usable_where_videotoolbox_takes_its_place`,
  `test_libx264_stays_required_without_videotoolbox_or_off_apple_silicon`.
- **CRF maps to VideoToolbox `-q:v` on the safe side, with a separate HDR curve.**
  `vt_quality` takes, at each CRF, the highest `-q:v` whose SSIM matched the CPU encode across
  `tests/bench_vt.py`'s clips (synthetic CG, fractal and grain, iPhone 17 Pro SDR and HLG at 30
  and 60 fps), so a GPU encode never measures below the CPU one; the other clips pay in bytes.
  HDR has its own curve (63 − 1.6 per CRF step against SDR H.264's 75 − 2.2 and HEVC's 78 − 2.0).
  Its CPU line is x265 Main10 at CRF+2, and the Main10 VideoToolbox line needs ~11–15 less
  `-q:v` for that SSIM. On the first fit's SDR curve, HLG phone footage came out at 6–8× x265's
  bytes at a higher SSIM (0.998 against 0.989). The split is on `bt2020_or_hdr`, a probe fact,
  and only the HEVC line takes it: an export preset's H.264 line on an HDR source replaces x264
  at the same CRF. The HDR clips' matches spread by 6.6 at CRF 18 and ~10 at 23/28, 60 fps
  lowest. One curve set by the 30 fps clip covers them, and the 60 fps clips pay 2.6–3.5× x265's
  bytes; a content class or a bitrate ceiling was not worth that. Three rows match within 0.3
  `-q:v`, inside VideoToolbox's run-to-run noise, so "never below" means within noise. SSIM is the
  metric the first fit used: x264/x265 psy tuning lowers their SSIM at equal visual quality, so a
  matched `-q:v` leans low. Frames are paired by index (`settb=1/1000,setpts=N`), because
  `setpts=N/FRAME_RATE/TB` rounds in a 1/1000 or 1/600 time base and pairs two frames in three
  with a neighbour. Tests: `test_quality_mapping_is_monotonic_and_bounded`,
  `test_the_curves_keep_the_measured_values`, `test_an_hdr_source_gets_the_hdr_quality_curve`,
  `test_an_h264_line_on_an_hdr_source_keeps_the_h264_curve`.
- **`--quality` on the GPU is an approximation of the CRF encode, said so, and `verified` does not
  change meaning.** `-q:v` is not a CRF: VideoToolbox has no rate-distortion model that x264/x265's
  CRF promises a quality from, and the curves above are a fit at three CRFs on a handful of clips,
  pinned to the measured values, not derived. A content type the bench did not hold can land above
  or below the CPU encode's quality, and the bytes differ by 1.1–3.5×. So every VideoToolbox
  encode adds a top-level `notes` line naming the encoder and its `-q:v`, saying it is not
  CRF-equivalent and that `--no-hw` gives the CRF encode. `verified` stays what it is for every
  tool, the output's measured properties (written, probed, the tool's own measured steps: loudness,
  duration, a platform check); none of them reads the encoder line or assumes x264/CRF, so a GPU
  file verifies exactly as the same file from the CPU would. Tests:
  `test_a_gpu_encode_notes_that_its_quality_is_not_crf_equivalent`,
  `test_verified_is_the_measured_output_whatever_the_encoder`,
  `test_the_curves_keep_the_measured_values`.
- **VideoToolbox BT.709 tags go through a bitstream filter.** The ≥7.1 reason `bt709_tag_args`
  uses encoder VUI parameters holds for VideoToolbox too, and it has no `-x264-params`; the
  `-colorspace` output options put a real matrix conversion on an untagged source (24 dB PSNR,
  tag-neutral). `h264_metadata`/`hevc_metadata` write the VUI after encoding (49.9 dB). Test:
  `test_hw_encode_reports_itself_and_keeps_an_untagged_source_unconverted`.
- **A job VideoToolbox refuses is re-encoded on the CPU, and the result says so; no other failure
  is retried.** VideoToolbox has hard limits (H.264 stops at 4096 wide) that listing the encoder
  cannot reveal. `run()` swaps the recorded VideoToolbox arguments back to the CPU line they
  replaced and retries once; `hw.used: false`, `hw.fallback: true` and `hw.notes` (with the line
  ffmpeg printed) report it, and `encoder` names what really ran. It retries only when stderr shows
  VideoToolbox's own failure, read from the FFmpeg 5.1–8.0 and master sources: "Error while opening
  encoder" on a line naming a `*_videotoolbox` encoder (6.0+ log contexts `[vost#N:M/<encoder>]`,
  8.0+ `[enc:<encoder>]`; 5.1's line names no encoder, so there it counts beside an error the
  encoder logged in its own `[<encoder> @ …]` context), or the encoder's compression-session
  failures in that context ("create compression session", "prepare encoder", "encode frame",
  "encoding frame", matched without case because master drops the "Error: " prefix). A bad filter
  graph, a missing font (7.0+ then prints "Could not open encoder before EOF", which names the
  encoder but means it never got a frame) or a full disk is the same failure on the CPU: retrying
  ran the job twice and reported the GPU as its cause. Those fail once, and the failure document
  names the encoder of the command that ran, says it was not retried, and carries `encoder`/`hw`;
  when the CPU retry fails too, the message and stderr are the CPU command's, and the note says
  the retry failed too instead of claiming a re-encode. `hw.fallback` is true only when the CPU
  retry succeeded (it means "re-encoded on the CPU"); a retry that times out keeps the neutral
  "retrying on the CPU encoder" line. The note is one line per refusal, the latest outcome
  (`_set_refusal_note`), so a job of many encodes names it once. Code:
  `_common.runner.videotoolbox_failure`, `run`, `_fail`. Tests: `VideoToolboxFailureTests`,
  `test_a_videotoolbox_open_failure_is_re_encoded_on_the_cpu_and_reported`,
  `test_a_failure_that_is_not_videotoolbox_s_is_not_retried_and_names_the_command_that_ran`,
  `test_when_the_cpu_retry_fails_too_the_error_is_the_cpu_command_s`,
  `test_a_failed_cpu_retry_does_not_claim_a_re_encode_and_a_repeat_refusal_is_noted_once`,
  `test_a_cpu_retry_that_times_out_leaves_no_claim_that_it_re_encoded` (fake ffmpeg, every CI runner);
  `test_a_job_videotoolbox_refuses_falls_back_to_the_cpu_and_says_so` (real hardware, confirmed on an
  Apple M3 with FFmpeg 9.0.2: 54 tests OK, 0 skipped).
  The CPU retry gets the odd-dimension retry a CPU-only run gets
  (`test_an_odd_sized_job_videotoolbox_refused_gets_the_even_scale_on_the_cpu`), and on 5.1 the
  encoder's non-fatal property lines do not count as its refusal beside another stream's open
  failure (`NOT_VT`, the 5.1 audio-encoder case).
- **The encoder list is `ffmpeg -encoders`; `ffprobe -encoders` only under `--dry-run`.** The
  AV1/ProRes refusals and the VideoToolbox check must describe the binary that encodes, and on a
  mixed install (a Homebrew ffprobe next to a static ffmpeg) ffprobe's list is another build's. A
  dry run promises never to run ffmpeg, so it reads ffprobe's, as `ffmpeg_version()` always does;
  the real run re-decides against ffmpeg's. Code: `_common.runner.ffmpeg_encoders`. Tests:
  `EncoderListTests`, `test_hw_dry_run_runs_no_ffmpeg`.
- **HDR10 side data survives VideoToolbox** (mastering display, content light level), measured
  on FFmpeg 9.0 — no note is raised for it. Test: `test_hw_hdr10_side_data_survives`.
- **HDR10 static metadata is passed to libx265 and SVT-AV1 explicitly, and measured on every
  output** (#401). FFmpeg before 7.0 does not hand the decoded frames' mastering-display and
  content-light side data to either encoder, so a 6.1 re-encode wrote PQ video without them.
  `probe()` reads them (stream, else the first frame) into `video.hdr10_static`, the HEVC/AV1 HDR
  lines restate them as `master-display`/`max-cll` and `mastering-display`/`content-light`, and
  `emit()` warns `hdr10_metadata_dropped` when a PQ output still lacks what a PQ source had
  (prores_ks and libaom have no such option). Code: `_common.decision.hdr10_x265_params`,
  `_common.emit._report_dropped_hdr10_metadata`. Tests: `Hdr10StaticMetadataTests`.
- **An `export.py` preset on the GPU writes the preset's format, and its CPU fallback is the
  preset's own line.** A fixed h264/h265 preset is 8-bit with BT.709 tags whatever the source (on
  an HDR source it says so in a note, as without `--hw`), so its VideoToolbox line is built as for
  an SDR source, on the SDR curve, rather than as the Main10 HDR line the re-encoding tools use;
  otherwise `--hw` changed the delivered format and a GPU→CPU fallback changed it back. The CPU
  line recorded for that fallback carries the BT.709 tags only where `export.py` adds them (not
  `prores`, a master that keeps the source's). Code: `_common.decision.hw_preset_video`. Tests:
  `test_an_h265_preset_on_an_hdr_source_stays_the_preset_s_8_bit_bt709_format`,
  `test_the_prores_preset_s_cpu_fallback_keeps_the_source_s_tags`.
- **`--hw` and `--no-hw` are two booleans, not one dest.** The contract's `input_schema` keeps one
  property per argparse dest, and the MCP transport turns `true` into the property's flag, so a
  store_true/store_false pair on one dest published only `--no-hw`, under the name `hw`. Each flag
  has its own dest (`hw`, `no_hw`, mutually exclusive), `hw_flag()` reads the pair back, and the
  generator refuses any parser whose actions share a dest. Tests:
  `test_every_flag_of_every_parser_is_published_once_under_its_own_name`.
- **Under `--dry-run`, `hw.used` is null; `encoder` is the planned encoder.** `used` says what ran,
  and a dry run ran nothing (the same rule as `waveform.py`'s `silent`). `encoder` keeps naming the
  encoder of the planned command, as `commands` lists planned commands, and the
  `FFMPEG_SKILL_HW` note still says what the GPU will cost. Test:
  `test_a_dry_run_reports_the_planned_encoder_and_no_used`.
- **A tool that runs other tools passes the GPU choice on and reports its stages.** `render.py`
  and `batch.py` export `--hw`/`--no-hw` to their stages; `waveform.py` passes its explicit flag to
  the caption/title stage, which writes its deliverable, and folds that stage's commands and `hw`
  into its own result. `render.py` (stages and an executed plan) and `batch.py` (items, into its
  top-level `hw`, `used` null) carry what their children reported, a failed stage's `encoder` and
  `hw` included. `batch.py`'s item cache, like `render.py --cache`, keys on the GPU setting (the
  suffix is empty when every step is on the CPU, so older caches still hit), and an entry whose
  output a later run rewrote is dropped. Tests: `test_batch_never_serves_a_cached_item_across_the_gpu_setting`,
  `test_batch_s_top_level_hw_carries_its_items`, `test_a_hw_plan_executed_by_render_reports_hw`,
  `test_render_s_failed_stage_keeps_its_encoder_and_the_earlier_stages_fallback`,
  `test_waveform_passes_its_gpu_choice_to_the_stage_that_writes_the_file`,
  `test_waveform_s_no_hw_overrides_the_variable_for_its_stage_too`.
- **Apple Silicon is the hardware, not the interpreter.** An x86_64 Python under Rosetta reports
  `platform.machine()` as `x86_64` on an M-series Mac; `sysctl -n hw.optional.arm64` still reads 1
  there. Whether `-q:v` works is the ffmpeg binary's build, and an x86_64 ffmpeg that refuses it is
  re-encoded on the CPU by the fallback above, with ffmpeg's line in the note. Code:
  `_common.runner.apple_silicon`; `doctor`'s `hw.platform_ok` uses the same check. Test:
  `test_hw_runs_on_apple_silicon_hardware_under_a_rosetta_python`.

## 2.7.0 — a second speech engine

- **`auto` picks Parakeet only for English.** The default Parakeet model (tdt-0.6b-v2) is
  English-only and transcribes other speech as English-shaped nonsense. A named `--language`
  decides; without one whisper.cpp's detector (the smallest multilingual ggml model, a second
  or less) decides. When neither can name the language, a Whisper engine that can run goes first
  (Parakeet only if every Whisper engine fails): a fast English transcript is not worth a
  confidently wrong one. When no Whisper engine is installed, or every one failed, the
  English-only model is not run at all (4.0.0): the call is refused before anything is transcribed
  or written (`reason: english_only`, or `engine_failed` when a Whisper engine ran and failed), and
  the refusal names the flag that names the language. Until 3.x it ran on English assumed and a
  top-level `notes` line said so; a note is read after Japanese has been burned in as English
  words, and a caller that reads `verified` never read it. The price: English speech on a machine
  with only Parakeet needs `--language en`. "Goes first" means a Whisper engine that detects the language: whisper.cpp
  is passed `-l auto` when nothing named the language (its own default is `-l en`, which decoded
  every unnamed language as English, in 2.5.1 too), else the named or detected one, and an
  English-only Whisper model (`base.en`, `ggml-*.en.bin`, quantised too: `ggml-base.en-q5_1.bin`) does
  not count as one for routing. Known gap: with whisper.cpp as the only engine and such a model, undetected
  speech is decoded as English.
  A named `--engine parakeet-*` runs as asked: naming the engine is naming what it does. A
  multilingual (v3) Parakeet model named with `--model` or `PARAKEET_MODEL` assumes nothing and
  runs under `auto`; an English-only one named with `--model` is not run on speech nobody named.
  Tests: `test_no_language_and_only_an_english_only_parakeet_is_refused_before_it_runs`,
  `test_an_english_only_parakeet_is_not_the_last_resort_when_every_whisper_engine_fails`. Measured on 8 min of LibriSpeech
  (contributor's figures, Apple Silicon): parakeet-mlx v2 2.8% WER at ~120× real time, whisper
  large-v3-turbo 2.4% at ~39×. Tests: `ParakeetRoutingTests`, `ParakeetEngineTests`,
  `UndetectedLanguageTests`, `WhisperLanguageTests`, `AutoRoutingFallbackTests`.
- **A Whisper engine that failed is a failure, not silence.** Undetected speech goes to Whisper
  first, so a Whisper failure has to read as one for Parakeet to be tried after it. A
  faster-whisper whose model would not load (an offline first run) raised inside its worker
  thread, the exception was swallowed and the run was refused as "found no speech"; it now logs
  "found but failed" and the next engine is tried, as a failed whisper.cpp always was. An engine
  that ran and returned no segment is still `no_speech` (`AsrNoSpeechTests`). For word timings,
  undetected speech gives every Whisper engine its turn before Parakeet, as captions do; with no
  Parakeet waiting, the first Whisper engine that ran and failed is still the one silence.py's
  "no word-level timings" refusal names, as in 2.5.1. Tests: `WhisperFailureTests`,
  `AutoRoutingFallbackTests`.
- **"No engine found" means none was found.** Its install lines are for a machine with no engine;
  2.5.1 also gave it when an installed whisper.cpp failed, and auto would have given it after
  passing over an installed Parakeet engine for French. When engines were found and none
  transcribed, the refusal names each and why (`kind: input`, `reason` `engine_failed` or
  `english_only`, `engines[].detail` with the engine's own error line). A named `--engine` is `kind: missing_tool`
  only when it is not installed; an installed one that failed is `kind: input`, `engine_failed`.
  The line comes from stderr, or for parakeet-mlx from its stdout, where it prints its errors.
  Test: `EngineRefusalTests`.
- **The transcribe call returns what it used; nothing is left in module state.**
  `transcribe_result()` / `transcribe_words_result()` return a `Transcription` (cues, words,
  engine, the `transcription` facts, notes), so two transcriptions in one process never read each
  other's engine or words. `transcribe()` and `transcribe_words()` keep their old return shapes
  for existing callers. Test: `TranscriptionStateTests`.
- **The skill's code downloads nothing; an engine may fetch its model once.** parakeet-mlx's
  default `mlx-community/parakeet-tdt-0.6b-v2` comes from Hugging Face on first use, as
  faster-whisper's does, and openai-whisper's from OpenAI. The audio never leaves the machine and
  inference is local, so "no cloud" stays true. `execution.network: false` is about the skill's
  own code: parakeet-mlx and openai-whisper fetch in their own child processes, but faster-whisper
  is a library the skill runs in its own process, so its first-run fetch is made from that process
  (`HF_HUB_OFFLINE=1` keeps it on the cached copy afterwards). Loading it with `local_files_only`
  by default would break the first run 2.5.1 users rely on. The install hint, docs/contract.md and
  references/scripts.md say so, and the contract's `execution.model_downloads` names
  each engine's source and process, so `network: false` cannot be read as "a first
  `--transcribe` is network-free". Tests: `InstallHintTests`,
  `test_the_network_claim_matches_where_each_engine_runs`.
- **whisper.cpp transcribes with `-mc 0`, by default.** Whisper conditions each window on the text
  before it, and once a hallucinated line is in that context it can repeat it for the rest of the
  file: in the contributor's benchmark (#318, six English sets of ~10 min, whisper.cpp 1.9.5)
  large-v3-turbo repeated one sentence ~300 times on two sets, and on common_voice lost about the
  last 7 minutes of speech. `-mc 0` (`--max-context 0`, previous-text tokens kept: none) removed both
  loops and lowered every model's word-weighted WER: base 19.87 -> 18.33, small 17.07 -> 15.42,
  large-v3-turbo 69.12 -> 12.52. It is a decoding change, not a free one: gigaspeech is worse for all
  three models (13.16 -> 14.11 for large-v3-turbo) and some single cells are (small on
  common_voice 16.44 -> 19.28, large-v3-turbo on ami 25.72 -> 27.55). It is the default rather than
  an opt-in because a loop that silently loses minutes of speech is a defect, which the 2.x promise
  ("behaviour may change to fix a defect, with a CHANGELOG line") allows, and because the net is
  better for every model measured; an opt-in would leave the loss with everyone who does not know to ask.
  It is given to the two whisper.cpp commands that write a transcript (the SRT of `caption.py
  --transcribe` and the `--output-json-full` word timings of `silence.py --filler --transcribe`) and
  not to language detection (`-dl`: it reads the first 30 s and writes no transcript), nor to any other
  engine: faster-whisper, openai-whisper and Parakeet are not whisper.cpp and were not measured. No
  repetition detector was added: the flag removes the cause, a detector would be a second decoder to
  maintain. Every whisper.cpp binary name the skill runs (`whisper-cli`, `whisper-cpp`, `main`) is
  documented to take `-mc` (the flag is years old); a build that rejected it would write no file, so
  the run reads as "whisper.cpp found but failed" with the build's last output line and the next
  engine is tried (`engine_failed` when whisper.cpp was named). Reverse this if a measurement on other material shows `-mc 0` costing more than the
  loops it prevents. Test: `WhisperContextTests`.
- **`FFMPEG_SKILL_ASR_MODEL` names a model for the engine that can load it; `--model` goes where it
  is told.** The variable is this machine's default `--model` for `caption.py --transcribe` and
  `silence.py --filler --transcribe` (#328). An explicit `--model` is one call's choice and goes to
  whichever engine runs, as it did in 2.8.6. The variable applies to every call, including the
  ones auto sends to Whisper for another language, so a Parakeet model there (an
  `mlx-community/parakeet-*` repo or a `.gguf`) is offered to the Parakeet engines only and the
  Whisper engines keep `base`; passed through as `--model` is, it would make every non-English
  transcription on that machine fail on a model no Whisper engine loads. A Whisper name reaches the
  Parakeet engines too, which pass over it for their own model, so it changes neither routing nor
  Parakeet's model. The variable is not refused for a Parakeet name (`PARAKEET_MODEL` /
  `PARAKEET_CPP_MODEL` remain the Parakeet engines' own setting, and `--model` beats them, so the
  variable does too). `doctor` reports it no more than `FFMPEG_SKILL_ASR_ENGINE`: it prints no
  environment values, and the result's `transcription.model` names the model that ran. Tests:
  `ModelDefaultTests`, `test_the_machine_model_reaches_caption_and_silence`.

## 2.8.0 — cuts that say what they did

- **`precision`, `keyframe_snapped` and `requested_*` keep their 2.x meanings; what is measured
  per segment gets new keys.** No 2.x key changes meaning. `precision` stays `precision_of()` for
  the whole run and `keyframe_snapped` stays `precision == "packet"` (a stream copy end to end):
  `demos/build.py`'s `demo_cut_accurate` and `docs/demos.md` read it that way. What #306 measured
  goes beside them. `start_snapped` is true when a copied picture starts more than a frame from
  its requested start (the keyframe the copy's seek lands on, measured: see the entry on where a
  copy begins) or when that start could not be measured (no packet at or after it in the probed
  window): an unknown start is never claimed exact, and the copy is not re-encoded for it, because
  2.x copied without measuring at all. Test: `test_an_unmeasured_start_is_never_reported_as_exact`.
  It is `null` under
  `--dry-run`, because a planned copy has not landed anywhere yet. `least_exact_precision` is the
  least exact segment's precision, and `segment_precision` lists them all. The two precisions
  differ only for an audio-only join of copied and re-encoded parts, because a video join re-cuts
  every segment when one part re-encodes. `requested_segments`/`requested_duration` and
  `expected_duration` stay the request clamped to the media's duration. A segment that ends with
  the video (less than a frame of sound trimmed) shows in `duration_delta_seconds` and a note,
  not in a changed request. Tests (main's, restored verbatim):
  `test_cut_json_reports_requested_vs_actual_and_mode`,
  `test_cut_copy_keyframe_snap_reports_a_real_nonzero_delta`, `test_eval6_followups`; new:
  `test_cut_precision_is_the_least_exact_segments_and_keyframe_snapped_is_start_snapped` (renamed in 3.0.0),
  `test_cut_start_snapped_is_measured_and_null_under_dry_run`,
  `test_a_sound_tail_under_a_frame_ends_the_segment_with_its_picture`.
- **A join that re-encoded is not reported as a copy (defect fix, on by default).** When the
  concat demuxer's stream copy failed, 2.x re-encoded the join and still reported `mode: copy`,
  `reencoded: false` and `precision: packet`. The join now counts toward `reencoded`, so such a
  run reports `hybrid` and `concat_fallback`. `reencode_reason` lists every cause, and `--codec`
  is named even when `--accurate` already forced the re-encode. Tests:
  `test_a_failed_concat_copy_is_reported_as_the_reencode_it_became`,
  `test_cut_json_says_why_it_reencoded_and_how_exact_each_segment_is`.
- **`batch.py`'s `cut_stream_copy` keeps its shape; the reasons are a sibling key.** Callers
  compare that object whole: main's test does, with `assertEqual`. Each row gains
  `cut_reencode_reasons` (each reason once per `cut.py` call that named it), and the top level
  gains `cut_reencode_reasons` counts. They are `{}` when no call re-encoded and `null` when no
  `cut.py` step ran. A row served from a cache an earlier 2.x batch wrote has `cut_reencoded`
  but no reasons; its re-encoded calls count as `unknown`, so the counts never read "none
  re-encoded" beside `cut_stream_copy.reencoded: 1`. Tests: `test_batch_reports_cuts_stream_copy_vs_hybrid_rate_across_the_folder`
  (main's, verbatim), `test_batch_counts_cut_reencode_reasons_beside_the_stream_copy_rate`.

- **A `--segments` join copies only identical parts, and otherwise re-cuts from the source.**
  The concat demuxer takes the first part's parameters for every part, so a copied HEVC segment
  next to a re-encoded H.264 one decoded with errors from a run that exited 0. The copy join now
  needs matching per-stream signatures (codec parameters, rotation, colour tags, extradata hash;
  a hash missing on both sides only counts for PCM/MP3/MP2 or an MPEG-TS output). No sum of the
  parts' durations predicts the join (each carries its own start offset, which the concat
  demuxer drops: it missed by 0.03–1.3 s across five ordinary sources), so the result is
  measured instead (next entry). The fallback does not join the parts at all: a copied part carries keyframe
  pre-roll and an audio tail, and the concat filter starts each segment where its longest stream
  ended, which left a 0.1 s hole even after a `PTS-STARTPTS` rebase. Re-cutting every segment
  from the source (per-segment input seek, `trim`/`atrim`, concat filter) measured 120/120
  frames with no gap. Code: `cut.signatures_match`, `cut.join_from_source`. Tests:
  `tests/test_cut_copy.py`.
- **A copy join of B-frame video snaps both ends of every part to keyframes, and verifies by
  demuxing.** Measured on lavfi fixtures, frame by frame with `framemd5`, then on real iPhone
  footage. An input `-t` stops in decode order, so a part ended at a keyframe's pts carried that
  keyframe and the P-frame after it; `make_zero` parts started at the reorder delay. Of five
  designs only one was exact: `.mp4`/`.m4v`/`.mov` parts that keep their edit list (the concat demuxer
  ignores where it starts, so the pre-roll is shown, but places the next part by its length) and
  end at the end keyframe's **dts**. Each end is judged against `--tolerance` on its own. **Open
  GOPs** cannot be cut this way: the frames just before a keyframe decode after it, so they are
  lost (144/150 in every design). An open end keyframe, or an open start keyframe after the first
  part, re-cuts the join. iPhone "High Efficiency" HEVC is open at every keyframe, so its joins
  re-encode. Smart rendering (copy the interior, re-encode the joins) was deferred. The check is
  the backstop for what the design does not model: Matroska parts (still the old cut), unusual GOP
  shapes. Only copied parts are copy-joined; parts encoded one by one leave an AAC frame's hole at
  every join. Code: `cut.plan_part`, `cut.gop_is_open`, `cut.check_join`. Tests:
  `CopyJoinPlanTests`, `CutJoinTests` in `tests/test_cut_copy.py`.
- **A source whose frames do not reorder cuts its parts as 2.5.1 did.** #306's keyframe plan was
  written for B-frames, and on H.264 with no B-frames (`-g 60`, AAC; iPhone "Most Compatible") it
  regressed joins 2.5.1 copied frame-exactly: `0-1.0,4-6` re-encoded (`tolerance`,
  `concat_fallback`) where 2.5.1 copied 90 frames; `0-1.8,4-6` gave 120 frames (end moved
  +0.2 s) for 2.5.1's 114; `0-2.4,4-6` gave 120 (end moved −0.4 s: requested frames dropped under
  `mode: copy`) for 132; and `0.3-2,4.4-6`, which 2.5.1 copied as 120 frames, failed the check
  and re-encoded. Without reordering a cut in decode order is already exact, so
  `cut.reorders(packets)` (a packet presented before one decoded ahead of it) decides: when
  nothing reorders, each part is cut as in every 2.x release (`make_zero`, `-t end-start`, no end
  snap, judged against `--tolerance` by its length) and the join is still checked. All four came
  out bit-identical to 2.5.1's outputs. Tests:
  `test_a_source_without_bframes_cuts_its_parts_as_2x_did`,
  `test_a_60fps_source_without_bframes_stays_an_exact_copy`,
  `test_reorders_is_true_only_when_a_frame_is_presented_before_one_decoded_ahead`.
- **An end snaps to the keyframe at or after it, never earlier.** #306 took the keyframe nearest
  the requested end, so `0-2.4` ended at 2.0 and dropped requested frames under `mode: copy`. A
  start snap only ever adds material, and so does an end snap now: the part runs to the first
  keyframe at or after the end, and if that one is past `--tolerance` the join is re-cut. An end in
  the video's last GOP has no keyframe after it; it stays where asked and the join check judges it
  (#306's rule, not a tolerance miss, even under `--tolerance -1`). Tests:
  `test_an_end_snaps_to_the_keyframe_after_it_never_before`,
  `test_an_end_snaps_to_the_first_keyframe_at_or_after_it`,
  `test_a_segment_in_the_last_gop_is_not_a_tolerance_reencode`.
- **A later B-frame segment that starts between keyframes is re-cut without trying the copy.**
  Its edit-listed part stores the frames from the keyframe to the start as hidden pre-roll, and the
  concat demuxer crushes them into steps of about 0.07 ms at the join, so the copy failed its check
  on every source shape tried (`0.3-2,4.4-6`, `0-2,4.1-6`, `0-2,4.4-12` on H.264, `0-2,4.2-6` on
  closed-GOP HEVC). Only edit-listed parts hide pre-roll; the first part's is not at a join. It
  holds under `--tolerance -1` too, so `--tolerance -1` is "never for a keyframe snap", not "never":
  README, `references/gotchas.md`, `references/scripts.md` and `cut.py --help` say so, and advise a
  keyframe start or an `.mkv` output. Code: `cut.hidden_preroll_start`. Tests:
  `test_a_later_start_between_bframe_keyframes_is_recut_without_a_copy`,
  `test_only_a_later_edit_listed_part_starting_between_keyframes_hides_pre_roll`.
- **The step at a join is the one its parts predict, within 1 ms.** #306 allowed a frame plus
  `max(frame/2, one audio frame)` at every step. That rejected exact joins (no-B `0-1.8,4-6` steps
  56.7 ms at the join, past its 54.7 ms bound) and let through a hole of up to one audio packet,
  which grows without limit with large PCM packets. The concat demuxer places each part where the
  previous part's container ends, so the step is (that container's end − its last picture) + (the
  next part's first picture − its container start), read from each part's format and video
  packets (Matroska stores no stream durations): 33.3 + 13.3 + 10.0 = 56.7 ms there, what the
  joined file showed, and within 1 ms on every MP4, MOV, Matroska and MPEG-TS join measured.
  Steps inside a part stay within (frame/2, 1.5 × frame). Code: `cut.predicted_join_steps`,
  `cut.check_join`. Tests: `test_each_join_step_is_held_to_the_step_its_parts_predict`,
  `test_a_join_step_is_predicted_from_the_parts_containers_and_pictures`,
  `test_a_no_bframe_join_one_frame_plus_its_gap_long_passes_the_check`.
- **A copy join's sound is checked against its picture, part by part.** Matching audio packet
  hashes to the source on keyframe-aligned `0-2,4-6,8-10` copy joins, each part's sound minus
  picture shift measured 0.3 ms (B-frame H.264, AAC; closed-GOP HEVC), 0–0.64 ms (no-B H.264),
  0 (audio 0.379 s late; audio leading by 0.2 s), and 0 / +16.0 / +53.3 ms for B-frame H.264 with
  `pcm_s16le` in a `.mov`, which #306 passed as `ok: true` with 180/180 frames. `check_join_audio`
  reads `a:0` packets with `-show_data_hash CRC32` for the join and for source windows around each
  part's start keyframe; for each part, the first run of 8 packets from 0.25 s into it that
  appears exactly once in the source within ±0.5 s of where the video's shift puts it gives the
  audio shift. More than 5 ms from the video's shift fails the check and re-cuts the join. A part
  with no unique run (digital silence, a periodic tone, a part too short) is unmeasured
  (`null`), not failed, so silence makes the check blind there. The source stream hashed is the
  one the join copied: FFmpeg's default selection copies the audio stream with the most channels,
  not always `a:0` (a 6-channel PCM `a:1` beside a stereo AAC `a:0` was copied, every part went
  unmeasured, and a join 16 and 53 ms off passed), so the check hashes the source streams with
  the joined audio's codec, channels and sample rate, in turn, until one measures a part. An
  MPEG-TS source's AAC carries an ADTS header that the copy into MP4/MOV/Matroska strips, so no
  hash matched; its packets are hashed without it (from `-show_data`; zlib's CRC32 is ffprobe's).
  `ok` is the conjunction, and `join_check` carries only its documented keys. Cost: about 0.5 s
  on a 3-minute join. Code: `cut.check_join_audio`, `cut.copied_audio_streams`,
  `cut.audio_packet_hashes`. Tests: `test_the_audio_check_hashes_the_stream_the_join_copied`,
  `test_the_audio_check_measures_aac_out_of_mpeg_ts`,
  `test_an_adts_header_is_left_out_of_the_hashed_payload`,
  `test_a_matroska_join_is_checked_and_recut_when_it_is_wrong` (the key set),
  `test_a_join_whose_sound_drifts_off_its_picture_fails_the_check_and_is_recut`,
  `test_a_clean_join_passes_the_audio_check_part_by_part`,
  `test_the_audio_check_measures_each_parts_sound_against_its_picture`,
  `test_a_part_whose_packets_repeat_is_unmeasured_not_failed`.
- **The join reads the source's packets only around the segments.** #306 read every video packet
  of the source for each `--segments` run, so the cost followed the source's length: on a
  25-minute 720p30 H.264 source (`-g 60 -bf 3`, AAC, 954 MB, 45,000 video packets, 4 vCPU,
  FFmpeg 6.1) the whole read took 2.9 s with the page cache dropped and 1.1 s warm. Now one ffprobe
  per merged window `[start − M, end + M]`, M = max(10 s, 2 × `--tolerance`), absolute times; for
  `60-120,600-660,1200-1260` the three windows read 7,200 packets in 0.5 s cold or warm; the
  whole join took 4.9–5.1 s against 5.2–5.7 s (it now also checks the audio), and its `--dry-run`
  0.7 s against 1.4 s. A window that lacks the landing keyframe, a whole GOP after it, or the first
  keyframe at or after the end with a whole GOP after that is widened ×4, up to three times, and
  then the whole file is read. The window at the file's start does not seek (a seek there skips an
  edit-listed MP4's negative-pts keyframe, as `measure_frame_timing` found); packets a later
  window's seek reads again are dropped; `gop_is_open` and `reorders` do not take a window's end
  for the file's end or the next packet; the cache key is (source, windows). Code:
  `cut.video_packets`, `cut.packet_windows`, `cut._windows_cover`. Tests:
  `test_the_packets_read_around_segments_plan_as_the_whole_file_does`,
  `test_packets_are_read_in_windows_widened_until_the_plan_has_its_gops`,
  `test_a_gop_longer_than_every_window_reads_the_whole_file`,
  `test_the_first_window_never_seeks_and_windows_merge`,
  `test_a_gop_cut_off_by_a_read_window_is_not_judged_closed`,
  `test_reorders_is_judged_within_each_read_window`.
- **A checked join is written beside the output and renamed into place.** #306 wrote it in the
  temp directory and copied it (about 2 s for a 240 MB join). It is now a hidden sibling of the
  output (`.<name>.ffskill-join-<pid>.<ext>`), renamed with `os.replace` under the output's lock
  by `place_output(..., move=True)` (a rename that fails falls back to the copy), and removed
  whatever happens. A failed check still never costs an `--overwrite` target. Code:
  `runner.place_output`, `runner.sibling_temp`. Tests:
  `test_a_checked_join_is_renamed_into_place_under_the_outputs_lock`,
  `test_a_checked_join_is_placed_under_the_outputs_lock`,
  `test_a_checked_join_is_renamed_into_place_not_copied`.
- **The re-cut cuts on the source's frame grid and states its frame rate.** Each segment runs, for
  both streams, from the first frame at or after its start to the first at or after its end (the
  frames it holds); the video trim sits half a frame before those points, so no FFmpeg version
  rounds a boundary frame in or out. A start between frames placed the segment's pictures half a
  frame off the output's grid, and FFmpeg 6.1's constant-rate output duplicated one (65 frames for
  64). `-r` is the source's `r_frame_rate`: FFmpeg 7.0 encoded the trimmed, concatenated pictures
  at 25 fps and dropped frames (98 for 117). Both streams still shift by one constant. Tests:
  `test_a_short_segment_across_a_bframe_keyframe_never_cuts_a_negative_length`,
  `test_the_recut_cuts_on_the_frame_grid_and_states_the_sources_rate`,
  `test_mismatched_parts_are_recut_from_the_source_with_exact_boundaries` (on 7.0).
- **Both streams of a segment shift by one constant.** A per-stream `PTS-STARTPTS` moved an
  audio track that starts 0.379 s after its video 0.379 s early. The re-cut shifts video and
  audio by the same seek margin and pads the audio to the segment origin
  (`aresample=async=1:first_pts=0`). Test: `test_a_delayed_audio_track_keeps_its_offset_through_the_fallback`.
- **The re-cut seeks a second early.** The MP4 demuxer seeks over its raw decode times, so on a keyint-60
  HEVC file with 4 B-frames `-ss 9.9` began at the keyframe at 10.0 and lost three frames; an
  input `-t` likewise stops reading before late-stored B-frames. Test:
  `test_more_segments_than_one_call_takes_are_joined_in_chunks` (it crosses that boundary).
- **At most 32 segments per ffmpeg call, chunked through Matroska with PCM audio.** Each segment
  is its own input (a file handle, demuxer and decoder), and macOS shells default to 256 open
  files. MP4/AAC chunks copy-joined put the video 23 ms behind the audio (encoder priming per
  chunk); PCM chunks carry none, and the audio is encoded once for the final file.
- **A video cut or segment shorter than one frame is refused (defect fix, on by default).** There
  is no picture to cut: on 2.5.1 `--start 1 --end 1.01` on 30 fps video wrote one whole frame
  (44 ms longer than asked) and `--segments 1-1.01,3-4` wrote 31 frames, both reported
  `completed`. A copy lands on a whole GOP and a re-encode on one frame or none, so neither is what
  was asked; the refusal (`kind: input`, before ffmpeg runs) follows 2.x's refusals of a caption
  burn that draws nothing and of blank graphics text. A cut to an audio output is not refused: sound has no frame.
  Code: `cut.main()`. Tests: `test_a_segment_shorter_than_a_frame_is_refused`,
  `test_a_single_cut_shorter_than_a_frame_is_refused_but_not_to_audio`.
- **A single MP4/MOV copy keeps its edit list only with `--edit-list`; its report comes from the
  source's packets.** `make_zero` shows the keyframe's pre-roll. The plain copy writes an edit
  list that hides it, and its first presented frame was bit-identical to the source frame at or
  after `--start`. #306 made that the default. It is opt-in in 2.x because the default decides
  what a caller gets, measured against main: `nob.mp4 --start 1.13 --end 5.71 --tolerance 2`
  copied 172 frames (+1.153 s) and now 138 with the pre-roll hidden; `hevc_sdr --start 1.1 --end 4
  --tolerance 0.3` re-encoded (`hybrid`) and now copies; a 25-minute source `--start 601 --end 661`
  wrote 74.7 s and now 1.95 s. A player or tool that ignores edit lists also shows the stored
  pre-roll, so an edit-listed copy is not what every 2.x caller expects. So the default stays
  `-avoid_negative_ts make_zero` and is judged by the container's length, as in every 2.x
  release; `edit_list` is `false` and `stored_preroll_seconds` `null`. Two rules apply only under
  `--edit-list`: the copy is judged by its video (the container also counts a longer track), and
  a copy that starts where asked but ends past `--tolerance` re-encodes without offering another
  `--start`. What a copy stored is read from the source, not the output: `stored_preroll_seconds`
  is the first presented frame minus the presentation time of the keyframe the copy's seek lands
  on (measured: next entry), and a keyframe presented *after* the start (10.0, asked for 9.9 on
  the HEVC fixture) is a snap. Comparing the output's durations with and without the edit list
  was tried and does not work: a B-frame composition offset makes them differ even on a keyframe
  start. Code: `cut.seek_keyframe`, `cut.copy_presentation`. Tests:
  `test_an_mp4_copy_keeps_its_edit_list_by_default_and_shifts_to_zero_under_no_edit_list` (renamed in 3.0.0, when the edit list became the default),
  `test_an_mp4_copy_starts_its_picture_at_the_requested_time`,
  `test_an_edit_listed_source_cut_again_starts_where_asked`,
  `test_judging_a_copy_by_its_video_is_noted_even_when_it_then_reencodes`; main's
  `test_cut_json_reports_requested_vs_actual_and_mode` and `test_eval6_followups`, verbatim.
- **Where a stream copy begins is measured with the seek ffmpeg makes, not modelled.** #306
  predicted the landing as the keyframe with the largest ffprobe dts at or before the start. The
  MP4 demuxer seeks over its raw decode times, which are ffprobe's dts plus the reorder delay, so
  on B-frame H.264 (FFmpeg 6.1.1 and 7.0.2) `-ss 3.99` landed on the keyframe at 2.0, not on the
  one at 4.0 (dts 3.933), and only `-ss 4.0` reached 4.0; on the HEVC fixture `-ss 9.85` landed on
  8.0 and `-ss 9.9` on 10.0. The model got the second right and the first wrong: a single copy
  from 3.97 reported `start_snapped: false` with its picture 1.97 s early, its `--edit-list`
  variant reported no stored pre-roll, and a join from 3.95 failed its check (180 packets for 120)
  and was re-encoded after the copy was tried. `seek_keyframe` now runs `ffprobe -read_intervals`
  from the file's start_time + t, the same `avformat_seek_file` call as ffmpeg's input `-ss`, and
  takes the first keyframe it reads (ffmpeg's copy drops what comes before it). For a demuxer
  without `AVFMT_SEEK_TO_PTS` (Matroska, MPEG-TS) ffmpeg seeks 3/23 s earlier when a stream has
  a decode delay (`fftools` `ffmpeg_demux.c`), and so does the probe (`cut.seek_shift`): on a
  B-frame `.mkv` `-ss 4.05` lands on 2.0 and `-ss 4.2` on 4.0, as the probe says. A `--segments`
  plan starts each part at its measured landing, so a later start in the reorder delay is
  planned (a tolerance re-cut, or the hidden pre-roll re-cut) instead of failing its check. One
  ffprobe per segment start; the read never seeks earlier than ffmpeg does (a seek before the
  file's start skipped an edit-listed MP4's negative-pts keyframe). Code: `cut.seek_keyframe`,
  `cut.seek_shift`, `cut.plan_part`. Tests:
  `test_a_start_inside_the_reorder_delay_lands_where_ffmpeg_seeks`,
  `test_a_later_start_inside_the_reorder_delay_is_planned_not_tried`,
  `test_an_edit_listed_source_cut_again_starts_where_asked`.
- **A `--segments` tolerance re-cut names the nearest keyframes, as in 2.x.** 2.5.1 cut every part
  and the part that missed `--tolerance` filled `nearest_keyframes`. #306 judges every start in
  `plan_part` before any part is cut and re-cuts without `cut_one`, so the key was `null` for
  those runs (67 harness cases). The re-cut branch now lists `keyframes_near` each such segment's
  start, the same values 2.5.1 gave. `lossless_alternative` stays single-segment, as in 2.x.
  Test: `test_a_segments_tolerance_reencode_names_the_nearest_keyframes`.
- **Microsecond `-ss`/`-t` and the `--accurate` seek margin are defect fixes, on by default.**
  Both change what the default writes, and both only make it what was asked. `-ss` rounded to the
  millisecond missed a keyframe at 61/30 = 2.0333 s: `--start 00:00:02:01@30` seeked to 2.033,
  snapped back to the keyframe at 0 and re-encoded; it now copies from that keyframe. A video
  `--accurate` cut seeks a second early and drops the margin on the output side, because a seek
  straight to a start a few frames before a keyframe could land (the MP4 demuxer seeks over its raw
  decode times) on that keyframe and
  lost those frames. Tests: `test_a_millisecond_off_keyframe_start_is_seeked_to_the_microsecond`,
  `test_accurate_keeps_the_frames_before_a_keyframe`.
- **An A/V start skew on the default path is reported, not repaired.** Without `--edit-list` a
  copy keeps main's `make_zero` behaviour, including the Core Media HEVC case (3.7 s of sound
  with no picture) and the B-frame reorder delay (0.12 s on the HEVC fixture). Re-copying with
  the edit list when the skew is large was considered and rejected for 2.x: it would change the
  default output's timestamps, the thing `--edit-list` is opt-in to avoid. `av_start_skew_seconds`
  is always reported. On a stream copy only, a `notes` line names `--accurate` (and `--edit-list`
  for a single `.mp4`/`.mov` copy whose start snapped) when the skew is more than max(2 frames,
  0.1 s) away from the source's own skew where the copy's picture starts: at the keyframe the copy
  began from, or at `--start` under `--edit-list`. A track that starts late by design (the 0.355 s
  late-audio fixture cut from 0, or from 0.3, which snaps back to the same keyframe and writes the
  same copy) is what was asked for, not a copy that began on packets the streams do not share. A
  re-encode gets no note: it starts both streams where the source has them (the re-cut pads the
  audio to each segment's origin), and the note told `--accurate` runs to re-run with
  `--accurate`. Code: `cut.av_skew`, `cut.source_skew`. Tests:
  `test_an_mp4_copy_keeps_its_edit_list_by_default_and_shifts_to_zero_under_no_edit_list`,
  `test_a_source_whose_audio_starts_late_is_not_reported_as_a_skewed_cut`,
  `test_a_snapped_copy_is_compared_with_the_source_where_it_landed`,
  `test_a_reencode_never_carries_the_copy_skew_note`,
  `test_av_skew_names_the_edit_list_only_where_it_would_help`.
- **A re-encoded cut keeps an SDR HEVC source HEVC only with `--keep-hevc`.** A cut is a trim, so
  a re-encoded segment could come out in the codec of the source and of any copied segment beside
  it; x264 for every SDR source turns an iPhone clip into H.264. #306 made HEVC the default, which
  changed what an existing call writes (`hevc_sdr --start 2 --end 4 --accurate` gave h264 on 2.5.1
  and hevc with #306), so within 2.x it is opt-in: `source_codec_video_args(..., keep_hevc)` calls
  `encoder_args("hevc")` (x265 8-bit BT.709, VideoToolbox under `--hw` with the CPU line recorded
  for the fallback) only when the flag is set, the source is HEVC and not `bt2020_or_hdr`;
  everything else takes `video_args`, the line every editing tool uses. An HDR, HLG or BT.2020-SDR
  source gets the same Main10 line either way, and `--codec` always wins. The contract's `cut`
  capabilities keep 2.5.1's x264 and HDR x265 entries, the x265 one extended by "with
  `--keep-hevc` on an HEVC source". Tests:
  `test_a_reencoded_cut_of_an_sdr_hevc_source_stays_hevc_unless_no_keep_hevc` (the default
  pin, inverted in 3.0.0), `test_a_reencoded_cut_of_an_sdr_hevc_source_stays_hevc`,
  `test_codec_h264_still_overrides_the_source_codec`, `SourceCodecArgsTests` (including
  `test_cut_passes_keep_hevc_to_the_encoder_and_composes_with_hw`).
- **A chunked join restates `hvc1`, by default.** A `--segments` re-cut of more than 32 segments
  encodes Matroska chunks and copies them into the output; out of Matroska into MP4 that copy
  writes `hev1`, which Apple players refuse. 2.5.1 had no chunks (its re-encodes wrote `hvc1`
  directly), so this is a defect in #306's chunking, not in a release; it is fixed by default
  because every HDR source's re-cut is HEVC Main10 with no flag, and a chunked join of it would
  otherwise be the first 2.x output tagged `hev1`: `_join_chunk` returns its codec arguments and
  the final copy into `.mp4`/`.mov`/`.m4v` repeats their `-tag:v`. Tests:
  `test_a_chunked_hdr_join_keeps_the_hvc1_tag_by_default` (HLG, no flag),
  `test_more_segments_than_one_call_takes_are_joined_in_chunks` (`--keep-hevc`).
- **The VFR guard stays the average check by default; the sampled measurement is `--vfr-guard
  sampled`.** `r_frame_rate` against `avg_frame_rate` is a whole-file average: a phone clip at
  29.98 against a nominal 30 trips it, and one long last frame does too. #306 replaced it with
  `measure_frame_timing`, which reads packet timestamps (no decoding) in up to five 6 s windows
  and requires every interval within a tick (1 ms at least, half a frame at most) of its window's
  median; the half-frame cap is there because a 1/fps time base makes one tick a whole frame.
  As the default that changed what existing calls write in both directions: a 0.5 s
  constant-rate clip that 2.5.1 copied re-encoded (`vfr_inconclusive`, 11 intervals where 20 are
  needed), and the suspected-but-constant `vfr_false_positive.mp4` that 2.5.1 re-encoded copied.
  So within 2.x the guard is a choice. `average` (default) is 2.5.1's guard: the suspected source
  re-encodes as `--accurate`, reason `vfr`, and stderr still says "variable-frame-rate"; only
  then is the timing sampled, and reported in `vfr_check` with `guard`, plus a `notes` line naming
  `--vfr-guard sampled` when the sample is constant. A source the average check passes is not
  sampled, so the default costs what it did, and a copy join of it checks its steps as constant
  timing. `sampled` is #306's guard (re-encode on `vfr` or `inconclusive`), and `off` is #306's
  unreleased `--vfr-copy` (which never shipped and is gone): for an eligible copy cut it samples the
  timing but keeps the stream copy. VFR confined to the unsampled
  stretches is missed by `sampled`; that was accepted because a copy is lossless and `--accurate`
  is always available. The reads are shaped by how `-read_intervals` behaves: it resolves a
  seek, and a relative end, against the keyframe it lands on, so windows name an absolute end and
  keep only frames from their own start, and the first window does not seek (a seek to 0 on an
  edit-listed MP4 skipped its negative-pts keyframe). Code: `cut.main()` (the guard),
  `_common/probe.py` `classify_frame_timing`, `measure_frame_timing`. Tests:
  `test_vfr_is_conformed_to_cfr_on_cut_and_fit` (2.5.1's, verbatim),
  `test_a_short_constant_clip_copies_under_average` (`--vfr-guard average` since 3.0.0),
  `test_a_suspected_but_constant_source_reencodes_under_average_and_says_sampled_would_copy`,
  `test_the_default_guard_is_sampled`,
  `FrameTimingTests`, `VfrGuardTests` (`--vfr-guard sampled` / `off`).
- **A segment past the video's end is held or trimmed, like a join.py clip; `--accurate` joins in one
  encode.** Both concat routes start the next segment after the longer stream of this one, so a
  segment whose sound outruns its picture opened a hole (0.355 s; and one AAC frame at every
  `--accurate` join, because each part was encoded on its own). `clip_length`'s rule decides: under a
  frame past the video's end, the segment ends with the video; more, its last frame is held for the
  sound, which only the re-cut can do. The last segment keeps the source's tail. The video's end is
  on the cut's clock: stream start + duration − the file's start_time. Its test source starts both
  streams at 10 s with PCM audio: a copied AAC track's priming started the file 21 ms before its
  video on FFmpeg 6.1 and not on later versions, which changed the frame count. Tests:
  `test_a_segment_past_the_video_end_holds_its_last_frame_in_a_copy_join` and siblings,
  `test_an_accurate_join_has_no_hole_at_its_joins`.
- **Decided for 3.0: the defaults #306 measured better, and the meanings it wanted.** 2.x keeps
  every key's meaning and every default's behaviour, so these wait for the next major, where
  each is a documented breaking change: `--edit-list` becomes the default for a single
  `.mp4`/`.mov` copy; `--keep-hevc` becomes the default, so a re-encoded cut of an SDR HEVC
  source stays HEVC; `--vfr-guard sampled` becomes the default, so a stream copy is refused on
  measured frame timing rather than on the whole-file average; `keyframe_snapped` takes
  `start_snapped`'s meaning (the presented start moved) and `precision` takes
  `least_exact_precision`'s (the least exact segment). 3.0.0 applied all five (see "3.0.0 — the floors rise" above).

## 2.10.7 — geometry uses the displayed frame

- **A 90° or 270° rotation is applied before a tool measures or places a rectangle.** ffmpeg
  autorotates on decode, so the filter graph sees the picture the player shows, not the stored
  width and height. `probe.py` still reports the stored size plus `rotation` (that pair is what
  a stream copy keeps). `cropdetect.py`'s `source_width`/`source_height`, its crop rectangle and
  its motion points are the displayed frame, which is the frame `crop.py` checks. `broll.py`
  scales the cutaway to that frame. `overlay.py --scale-percent` and `--platform` margins, and
  `look.py --safe`'s aspect note, use it too. Tools that already swapped (`fit`, `crop`,
  `redact`, `caption`, `graphics`, `join`, `multicam`, `proxy`) are unchanged. Code:
  `cropdetect.main()`, `broll.main()`, `overlay.main()`, `look.main()`. Tests:
  `test_cropdetect_reports_the_displayed_frame_of_a_rotated_source`,
  `test_broll_sizes_the_cutaway_to_the_displayed_frame`,
  `test_overlay_scale_percent_uses_the_displayed_width`,
  `test_overlay_platform_margins_use_the_displayed_frame`,
  `test_look_safe_compares_the_displayed_aspect_of_a_rotated_source`.

## 2.10.5 — an accurate cut starts its picture at 0

- **`cut.py --accurate` on a video does not pass `-avoid_negative_ts make_zero`.** The
  flag shifts every stream so the earliest timestamp is 0. On a re-encode that timestamp
  is the AAC encoder's priming (1024 samples, 21.3 ms at 48 kHz) or, with B-frames, a
  negative video decode time further back, so the picture started after 0 and the sound
  at 0 (#336). `fit.py --fps` then snapped the gap and changed the frame count. Dropping
  the flag leaves the first frame at 0 when `--start` lands on a frame. A start between
  frames begins on the next source frame. On FFmpeg 6.1 that frame's timestamp is 0; on
  7.1, the Homebrew build and the Windows build it keeps about one frame (0.033 s), the
  grid the decoder already had. Moving the picture alone to erase that frame would leave
  the sound a frame ahead. An MP4/MOV edit list still hides the priming, so the sound
  presents with the picture; a Matroska file keeps the priming packet at a negative time
  and the picture at 0. A source whose audio starts late keeps that offset. Audio-only
  `--accurate` still uses `make_zero`: the sound is padded from 0 (`aresample=async=1:first_pts=0`,
  since #462 A46; `asetpts=PTS-STARTPTS` before it dropped a late sound's offset), and the
  flag is what folds the priming into the length `precision: codec_frame` reports. A stream
  copy is unchanged
  (`make_zero` by default, `--edit-list` to hide the keyframe's pre-roll). Code:
  `cut.cut_one()`. Test: `test_an_accurate_reencode_starts_the_picture_at_zero`.

## 2.10.5 — a fixed logo comes off with redact.py --mode delogo

- **`--mode delogo` is a mode of `redact.py`, not a 43rd script.** The operation is the one
  redact already has: a caller-supplied rectangle, applied to the whole clip, with no search
  for the region. A new tool would restate that and move the count the 1.16 and 1.17 entries
  above keep at 42. Blur and pixelate obscure the box; delogo fills it from the surrounding
  pixels (ffmpeg's `delogo`). It is a border blend. Inpainting, a logo that moves, and
  burned-in text whose position changes are out of scope, same as a face the caller did not
  box. Code: `redact.main()`. Tests: `test_delogo_interpolates_a_fixed_rectangle_and_refuses_the_frame_edge`,
  `test_delogo_refuses_a_10_bit_source`.
- **The box must leave a 1 px ring, because `delogo` expands it by a band that is no longer a
  flag.** On 5.1 through current the filter sets `band = 1`, grows the rectangle by that ring
  and refuses the frame when the ring leaves it (`x < 1`, `y < 1`, or `x + width` / `y + height`
  flush with the far edge). Passing `band` is an error on 6.1 ("Option not found"), so the tool
  does not expose it. An HDR or 10-bit source is refused up front: the filter's pixel formats
  are 8-bit YUV, and letting ffmpeg insert a scale would flatten the picture without saying so.
  Code: `redact.main()`. Tests: the two named above.

## 2.10.0 — a video layer in a project

- **`overlays[]` refuses `video` beside another layer kind, and only that combination.** A video
  layer is a fourth kind next to `logo`/`image`/`text`, as `overlay.py`'s `--logo`/`--image`/
  `--text`/`--video` are one mutually exclusive choice. An entry with a logo, an image and text
  together still draws the first of them (logo, then image, then text), as every release before
  #326 did: refusing those too would refuse projects 2.8.6 rendered. Making every combination a
  refusal is a separate change. Code: `render.check_overlay()`. Test:
  `test_render_video_overlay_refusals_and_dry_run_plan`.
- **`chromakey_similarity`/`chromakey_blend` without `chromakey` are refused in a project, though
  `overlay.py` accepts the flags alone.** The tool ignores them silently there; a project key that
  does nothing is what review 9 made a refusal (`OBJECT_KEYS`). A `chromakey*` key without
  `video` is refused as `overlay.py --chromakey` without `--video` is. Code:
  `render.check_overlay()`. Test: `test_render_video_overlay_refusals_and_dry_run_plan`.
- **A missing layer file is refused before the first stage, under `--dry-run` too.** No earlier
  stage writes an overlay video (it is the caller's file, like a clip source), so it is not a
  pending intermediate and a plan for it is no plan. A missing `image` is unchanged: a dry run
  still plans it and a real run fails in the overlays stage. Code: `render.main()`. Test:
  `test_render_video_overlay_refusals_and_dry_run_plan`.

## 2.10.9 — FFmpeg 8.0.1 (Ubuntu 26.04)

- **`pad.py` builds one `-filter_complex` for a clip with sound, not a `-vf` and an `-af`.** On
  8.0.1 and conda-forge's 7.1.1 (not Debian's 7.1.5 or 8.1.3), one demuxer feeding two simple
  graphs deadlocks when the audio one both delays and pads (`adelay` + `apad`); one graph reading
  both streams runs on 5.1.1, 6.1.1, 7.0.2, 8.0.1 and 8.1.3. A command
  compared with 2.10.8's differs by design. Code: `pad.main()`. Test:
  `test_pad_with_sound_is_one_filter_graph`.
- **`silence.py` never selects the sound with `aselect`.** 8.0 and 8.0.1's `aselect` passes every
  frame. Through 3.1.3 the tool tagged the kept frames with one `ametadata` and kept them with a
  second, in one graph; `asplit` + an `atrim` per range + `concat` was rejected because at
  `--max-cuts 400` its command passed Windows' 32767-character line. That one-graph render was
  replaced for #409 (below): the kept ranges now go through `cut.py`'s `--segments --accurate`
  re-cut, which trims each range from its own seeked input and runs at most 32 ranges per ffmpeg
  call, so neither `aselect` nor the long command comes back. `asegment`'s timestamp mode compares
  pts with a sample count and is right only for a stream that starts at 0. Code:
  `silence.main()`. Test: `test_silence_removal_cuts_the_sound_with_the_picture`.
- **On 8.0, 8.0.1 and 8.1.0, a multi-line `graphics.py` label goes through libass under
  `--text-render auto`**, decided after the template has wrapped its labels (so `main()` runs
  once more with the route forced). The releases are named, not probed: `--dry-run` may not start
  ffmpeg, and a git build without a release number is taken to be fixed. Code:
  `drawtext_draws_newline_glyph()`. Test:
  `test_multi_line_text_avoids_drawtext_on_releases_that_draw_the_line_break`.
- **On those releases a multi-line `overlay.py --text` is drawn one line per drawtext, at positions
  measured by a drawtext run, including under `--dry-run`.** overlay has no libass route, and
  libass would set the block differently (its lines are justified by the alignment, drawtext's are
  left-aligned in the block; its line spacing is its own). Through PR #346 overlay only warned in
  `notes`. Splitting the lines needs the block's numbers, and no multi-line drawtext on those
  releases has clean ones: every line but the last carries the box in its width. No filter can
  hand one drawtext's metrics to another either. So `drawtext_line_metrics()` measures each line
  alone: drawtext's own `print()` expression logs `text_w`, `top_a`, `bottom_d` and `lh` on a
  generated one-frame picture. The block is then rebuilt the way drawtext lays one out:
  `text_w` = the widest line, `text_h` = lh*(n-1) + the first line's top_a + the last line's
  bottom_d, lines left-aligned at x, baseline i at y + top_a + i*lh. Each line is drawn at its
  baseline (`y_align=baseline`) with the caller's x/y expressions, `text_w`/`text_h` replaced by
  those numbers. The outlines of all lines go first and the text second, as one drawtext draws
  them; otherwise a descender's outline covers the next line. `--box` is drawn once, by the first
  line, at the block's size (`boxw`/`boxh`). The result is bit-identical to one multi-line drawtext
  on 8.1.3 and 6.1.1 at every position tested, with and without `--box`. The 8.0.1 output is
  bit-identical to 8.1.3's single drawtext with DejaVu Sans. The cost of measuring is one small
  ffmpeg run, also under `--dry-run`, because a plan with guessed positions would not be the
  run's plan. Not exact: a font whose glyph boxes are not whole pixels (unhinted, e.g. FreeSerif
  Bold Italic) sits one row lower, because drawtext reports `top_a` rounded up. A fixed release
  plans the single drawtext it always did, byte for byte. Code: `overlay.per_line_drawtext()`,
  `_common.drawtext_line_metrics()`. Tests: `test_overlay_per_line_route_draws_what_one_multi_line_drawtext_draws`,
  `test_overlay_multi_line_text_draws_no_box_at_the_line_break`,
  `test_multi_line_text_avoids_drawtext_on_releases_that_draw_the_line_break`.

## 2.10.9 — doctor's FFmpeg advisory and the Python 3.9 deprecation

- **The FFmpeg CVE advisory is a warning, never a failure, and never says "vulnerable".** `doctor`
  sees only the upstream number in `ffmpeg -version`, and distributions backport fixes under it
  (Ubuntu `8.0.1-3ubuntu2`, Debian `+deb13u1`), so the line says the build is older than the first
  upstream release with the fix and that a distro may have backported it. It names an update command.
  `ok`, each tool's `usable` and the exit code stay what the capabilities say: an advisory that
  failed doctor would fail every patched distro build. Code: `_contract.ffmpeg_security()`.
  Tests: `test_ffmpeg_security_compares_with_the_fix_on_the_version_s_branch`,
  `test_doctor_advisory_is_a_warning_never_a_failure`.
- **A version on a branch with no fixed release is compared with the oldest release that has the
  fix.** security.html lists CVE-2026-8461's fix under 9.0, 8.1.2 and 8.0.3 and under no 7.x or 6.x
  release. Read literally, "older than the fix on its branch" would leave 6.1 and 7.1 (Ubuntu 24.04,
  Debian 13) silent. The line for them says no release on their branch is listed with the fix,
  which is what the page shows; it does not claim the old branch has the bug. A version that is not
  a release number (`N-12345-g…`, a dated git build) is `unknown` and gets no line.
- **The table is hand-maintained and offline.** It is the list on ffmpeg.org/security.html on the
  date in `FFMPEG_ADVISORIES_CHECKED`, and only CVEs that page lists go in. Fetching it at run
  time would break `execution.network: false`, and a stale table only means a missed warning, not
  a false one. Test: `test_ffmpeg_advisory_table_is_dated_sourced_and_documented`.
- **The Python 3.9 deprecation is on stderr only; the FFmpeg advisory is in the document too.**
  Every deprecation warning has been a stderr line (`--crf` in 1.10), and the machine-readable
  form is `contract --json`'s `deprecated`. The FFmpeg advisory is about the machine, which is what
  `doctor --json` describes, so it has a key (`ffmpeg_security.warnings`). The 3.9 floor and CI's
  3.9 job stay until 3.0. 3.0.0 removed the support and these tests; the refusal is pinned by
  `test_3_0_removed_python_3_9_and_ffmpeg_5_on_every_surface` and
  `test_doctor_reports_an_unsupported_python_or_ffmpeg_and_fails`.

## 2.11.0–2.12.0 — nothing happens silently

The principle: every refusal, rejection, skip, fallback or swallowed error leaves a structured
record a caller can read -- fields in the `--json` document, not only prose in `error.message` --
plus its stderr line. The entries below are the infrastructure and the first decisions taken
under it; the rest of the silent paths are converted onto the same infrastructure in later PRs.

- **A refusal is `refuse(kind, reason, message, **details)`: `error.reason` is a stable code and
  `error.details` the facts.** `kind` keeps its meaning (the failure class, mapped 1:1 to `code`);
  `reason` says *why* within it, from a closed list the contract publishes
  (`json_output.error_reasons`), and `details` carries the values the message is written from
  (paths, expected and actual). Both are absent on a failure that is not a refusal, the way `hint`
  is, so the failure example in `docs/contract.md` keeps its four keys. `reason` lives inside
  `error` because the top-level `reason` is already taken by `caption.py`'s `no_speech` refusal.
  Code: `_common.emit.refuse()`, the runner's output guards. Tests:
  `test_refusals_at_the_runner_choke_points_carry_a_reason_and_details`,
  `test_every_refusal_reason_is_in_the_contract_and_the_runner_guards_use_refuse` (a source
  check: every `refuse()` reason literal is in the contract and the guards never `die()` in prose).
- **The collector's records are under `diagnostics`, not top-level `warnings`/`skipped`.**
  `check.py`'s `warnings` is a count and `join.py`'s `skipped` its left-out inputs, so top-level
  keys of those names would mean two things. `diagnostics: {warnings, fallbacks, skipped}` holds
  `{code, message, ...facts}` entries recorded by `warn()`/`record_fallback()`/`record_skip()`
  (each also prints its line), merged by `emit()` and `die()` as `hw_notes` becomes `hw.notes`,
  present only when an entry exists. `render.py` takes a stage's entries with `absorb_stage()`,
  adding `stage`. Code: `_common.emit._merge_collector()`, `absorb_stage()`. Test:
  `test_a_stale_lock_taken_over_is_recorded_in_the_document_and_the_audit_log`.
- **The audit log is appended only where an event names a place, and never fails the run.**
  JSON lines `{ts, tool, event, pid, plan_sha256, details}`. A refused plan goes to
  `<plan>.audit.jsonl` (the plan is what the reader will look at); a lock event to the hidden
  `.<output>.ffskill-audit.jsonl` beside the lock it concerns; `render.py --audit-log FILE`
  replaces both. An event with neither (an output-is-input refusal without `--audit-log`) is in
  the document only: a log appearing next to arbitrary outputs unasked would contradict "a plan
  leaves nothing behind". A failed write is a `diagnostics.warnings` entry
  (`audit_log_unwritable`), and the refusal's `details.audit_log` says `{path, written}`. Nothing
  is appended under `--dry-run`, even for a refusal the dry run predicts: a dry run writes
  nothing, and `details.audit_log` then says `reason: "dry_run"`. Code: `_common.emit.audit()`,
  `render._reject_plan()`. Tests: `test_a_refused_plan_says_what_changed_and_leaves_an_audit_record`,
  `test_a_failed_audit_write_is_a_warning_not_a_failure`.
- **A refused plan lists every input, not only the bad ones.** `details.inputs` is
  `[{path, status: unchanged|changed|missing, expected, actual}]` so a caller sees the whole
  binding at once; `actual` is the string `"missing"` for a file that is gone. The message keeps
  the per-file prose and the word "changed". Inputs that did not exist when the plan was made are
  recorded in the plan as `unbound_inputs` (additive: `plan_version` stays 1) and reported on
  execution as a warning, not refused: a plan over an earlier step's output is the use case
  `join.py`'s pending inputs exist for. Code: `render.execute_plan()`, `_common.emit._plan_unbound_inputs()`.
  Test: `test_a_plan_names_the_inputs_it_could_not_bind_and_render_reports_them`.
- **A live holder's output lock is taken over only after its own time limit.** Through 2.10 a lock
  older than an hour was taken over even while its pid ran, so a legitimate encode longer than an
  hour (an `--timeout 0` master, a slow AV1 pass) lost its lock to a second writer: the F1 bug the
  lock exists for. A live pid is not proof of a live writer (a pid can be reused), so the takeover
  is kept, but bounded by the holder's own deadline: `child_limit()` from the lock's creation
  (4x `--timeout` + 60 s, which covers every retry `run()` makes under one lock); with
  `--timeout 0`, never. The writer stores the deadline as the lock's mtime minus an hour, so the
  rule every version applies ("older than an hour") means "past the deadline" in both directions
  and the lock file still holds only the pid. A dead pid's lock is taken over at once, as before.
  The cost: a pid reused by an unrelated long-lived process blocks the output until the
  deadline (about two hours by default, forever under `--timeout 0`); the refusal names the pid
  and the lock file to delete. A takeover is a `stale_lock_taken_over` fallback plus a
  `lock_takeover` audit line; running without a lock where none can be created is an
  `output_unlocked` warning plus an audit line. Code: `_common.runner._OutputLock`. Tests:
  `test_a_live_holder_keeps_its_lock_past_an_hour_while_inside_its_own_limit`,
  `test_with_no_time_limit_a_live_holders_lock_is_never_taken_over`,
  `test_a_lock_an_older_version_wrote_is_taken_over_after_an_hour_as_before`,
  `test_running_without_a_lock_is_a_recorded_warning`.

### Part 2: a degraded or partial result is never reported as the asked-for one

- **A stage's verdict is the parent's.** `absorb_stage()` now also carries a stage's `notes`
  (prefixed with its tool: `export: loudness ... is outside x's ...`) and, for a stage that
  completed in a real run, its verification steps tagged with `stage`; `emit()` adds them to the
  parent's own, so `render.py`'s `verified` is the conjunction of every stage's. Through 2.10 an
  export that missed its loudness (`completed`, `verified: false`) made a render that said
  `verified: true`. Carried: every step except a passing `probe`/`exists` of the stage's
  intermediate (a completed stage passed them by definition, and they would only lengthen the
  list); a stage that said `verified: false` without a failing step adds `{step: verified, stage,
  ok: false}`. The same carry applies to an executed plan (its tool's steps used to be copied by
  hand, untagged) and to a pack's renders. The entry "`verified` is what the tool measured itself"
  above still holds: render's stages *are* what it ran. Code: `_common.emit.absorb_stage()`,
  `emit()`. Test: `test_render_verified_is_every_stages_and_carries_their_notes`.
- **A cache hit replays what the stage verified.** A `render.py --cache` sidecar keeps the stage's
  `verified`, `verification`, `notes` and `diagnostics`; a hit feeds them through
  `absorb_stage()` as a live stage would, so a cached unverified export stays unverified.
  `references/scripts.md` said "Any mismatch is a silent miss" (and `cache_lookup()` returned
  False "silently, because a miss is not an error"); a miss is still not an error, but every
  miss is now in `cache.miss_reasons` (`not_cached`, `sidecar_missing`, `artifact_missing`,
  `sidecar_corrupt`, `artifact_truncated`, `no_output_path`); the two that mean something damaged
  a file this tool wrote are also a `cache_entry_damaged` warning and an audit line in the cache
  directory's `.ffskill-audit.jsonl` (the cache directory is the place the event names). A store
  that fails is a `cache_store_failed` warning, an input that cannot be fingerprinted a
  `cache_input_unreadable` warning (it keys as `"missing"`), and an unreadable ffprobe banner a
  `cache_ffmpeg_banner_unreadable` fallback: the sentence "Unreadable falls back to the parsed
  pair" in "The ffmpeg version is inside the render cache key" still describes the key, and the
  fallback is now said. Code: `render.cache_lookup()`, `cache_store()`. Tests:
  `test_render_cache_says_why_a_stage_missed_and_replays_what_a_hit_verified`,
  `test_render_cache_store_failure_banner_fallback_and_unreadable_input_are_recorded`.
- **`"check": {"content": true}` without a platform runs.** A plan's check step already honoured
  `content` alone (`render.execute_plan()`), and `check.py --content` without `--platform` is a
  valid call (youtube assumed, judgement rows WARN), so the project stage now follows the same rule
  rather than refusing a key the schema accepts; a failure is reported as a platform check's is
  (`kind: verification`, "the content check failed"). A check stage the run does not perform is
  recorded: `check_dry_run` under `--dry-run` (a plan's check steps too), `check_nothing_to_check`
  for a stage with neither key. check.py output that does not parse is a failure document
  (`status: failed`, `error.reason: check_output_unparsed`, `exit_code`, `stderr_tail`) where a
  bare string stood. Code: `render.run_check()`, `render.main()`. Tests:
  `test_render_runs_a_content_only_check_and_records_a_dry_run_skip`,
  `test_check_output_that_does_not_parse_is_a_structured_failure`.
- **`export.py` says what it cut and what it could not measure.** A trim to the platform maximum
  is `trimmed: {from, to}` and a `notes` line (it is the preset's promise, so not a warning). A
  loudness measurement that did not parse is `loudness: {lufs: null, tp: null, ok: null,
  measured: false, reason: not_measured, target_*}`, a failing `{step: loudness, ok: false,
  reason: not_measured}` and a `loudness_not_measured` warning -- check.py's WARN row for the same
  case is the model; leaving the block out read as "nothing to check" and kept `verified: true`.
  After `--normalize` a re-measurement that fails is the same record: the earlier measurement no
  longer describes the file, and reusing it (2.10) reported the old level as the new one. A
  platform preset on a source without audio records a `loudness_no_audio` skip. Code:
  `export._loudness_unmeasured()`. Tests: `test_export_says_it_trimmed_to_the_platform_maximum`,
  `test_export_an_unmeasured_loudness_is_a_failing_step_not_an_absence`.
- **`multicam.py`'s `cuts` name the camera on screen.** A range whose camera has not started plays
  camera 0 (unchanged); `cuts` now says 0 for it, as `--write-project` already did, and a
  `camera_not_started` fallback names the camera asked for. Code: `multicam.main()`. Test:
  `test_multicam_names_the_camera_it_rendered_not_the_one_asked_for`.
- **`report.py` accounts for every section.** Each section it tries to build -- loudness of each
  file with audio, the `--platform` compliance table, each contact sheet -- is a verification step;
  one that could not be built is `ok: false` with the child's `reason`/`kind`/`message` and a
  `report_section_missing` warning, so `verified` is false and `check: null` no longer sits beside
  `verified: true`. The compliance step's `ok` means "the table is in the report"; what the table
  says about the file is `passed`. Under `--dry-run` a contact sheet is a `report_section_dry_run`
  skip (look.py draws nothing in a dry run). `--no-sheets` is the caller's request and is not
  recorded. Test: `test_report_records_a_section_it_could_not_build`.
- **`batch.py`: `ok` stays "every step completed"; `verified` is new beside it.** The entry
  "`verified` is what the tool measured itself" decides that a spec miss is `completed` +
  `verified: false`, not a failure, so a step that completed unverified is not counted as failed;
  the row says `verified: false` and `unverified: [{step, tool, failed}]`, the batch's own
  `verification` has one `item` step per row (its `verified` was always false before: it had no
  steps), and a note names the items. A failed row's `error` is the failing step's own
  `{step, tool, kind, message, code, reason, details, hint, exit_code}`; the old string `error`
  (only ever a worker's exception text, or `"1"` -- `str(SystemExit)`) is replaced by that object,
  with `exception` for a worker that raised. A recipe error that is the same for every item (a step
  script outside `scripts/`, no steps) is refused once before any item runs. Code:
  `batch.process()`, `step_error()`. Tests:
  `test_batch_a_failed_item_says_which_step_failed_and_why`,
  `test_batch_counts_a_completed_but_unverified_step_as_ok_and_says_it_is_unverified`,
  `test_batch_a_worker_that_raised_names_its_error_not_its_exit_code`.
- **An interrupted batch reports every item.** The shared signal handler exited with "nothing was
  written" and, inside an item, surfaced as that item's failure while the batch went on. batch.py
  installs its own SIGINT/SIGTERM handler: it stops the running steps (`stop_children()`, the
  shared handler's first half) and raises KeyboardInterrupt, and the table then has one row per
  input -- finished, `interrupted: true` (stopped while running), or `skipped: "interrupted"` (not
  started) -- so `total` is the folder's count; exit 130 (143 for SIGTERM), `kind: interrupted`. A
  `--watch` loop stops after an interrupted pass. Test:
  `test_batch_interrupted_reports_every_item_and_the_right_total`.
- **A batch cache hit is served only while its output is the file the batch wrote.** An entry now
  keeps the output's `{size, mtime_ns}` (a stat, no read: a multi-GB delivery is not re-hashed per
  run); a hit whose output changed is a miss (`cache_miss.reason: output_changed`, a
  `batch_cache_output_changed` warning). An entry written by 2.10.11 or earlier has no identity and is not
  served either (`entry_unverifiable`): one re-run per item is the cost of not serving a replaced
  file as "cached ok". The GPU entry's "older caches still hit" is about the key and still holds; it
  is this identity check that re-runs them once. A cache file that does not parse is a
  `batch_cache_reset` warning plus an audit line in the output folder's `.ffskill-audit.jsonl`,
  and an unreadable `recipe.project` (its content is in the key) a `recipe_project_unreadable`
  warning. Code: `batch.cached_output_changed()`, `recipe_key()`. Tests:
  `test_batch_serves_a_cached_output_only_while_it_is_unchanged_and_records_a_reset_cache`,
  `test_batch_recipe_key_records_an_unreadable_project`.
- **`batch.py --watch` processes a source only once it has settled, and replaces only its own
  earlier output.** A pass took every file that existed, so a file still being copied into the
  folder was delivered as the fraction already written (`ok`, and `verified` for an MKV or TS,
  whose checks compare with the input as read), and once the copy finished every later pass met
  that output as someone else's and refused it (`output_exists`). A source is processed once it
  has the same size and mtime as at the previous poll, or, first seen, was last modified at least
  one interval ago; until then its row is `skipped: "settling"` (`ok: false`, not cached), and a
  watch stopped there fails with that row, since the file was not processed. One poll interval is
  the whole rule: a writer that pauses longer than the interval is read early, and the pass after
  its next write processes the file again. A file an earlier pass of the same watch delivered --
  the final output and every side file a step wrote, such as caption.py's `.srt` beside the
  video -- still with the size, mtime and inode it had then, is this run's own file under the
  overwrite rule above and is replaced without `--overwrite`; one replaced or edited since, or
  left by an earlier run, is refused as before (`output_exists`); so is one another item of the
  same run delivered (two items naming one fixed side file). The permission is per item and per
  path, and is checked where the write happens, not when the item starts: batch.py never hands a step a
  global `--overwrite` for it (that let `caption.py --text` replace a hand-corrected sidecar
  because the video was batch's own), it gives each step a snapshot of the files it delivered
  (`runner.OWNED_ENV`, internal to batch.py), and the step's own output check
  (`refuse_existing_outputs()`) passes an existing target only while it is still that file and
  reports back each path it was allowed to write, with the identity each had when it was written
  (`runner.report_committed()`, called where a write lands); `deliver()` compares the final path's
  identity again under the output lock and records the one it leaves. An SRT edited while the same
  item's video was still encoding no longer matches what was written and is refused next pass. A file another process puts there between that check and the
  write itself is refused there too: the step compares the identity its check recorded under the
  output lock before it replaces (see "The output check is made again where the file is
  replaced"). A side file a step
  writes without that check, or one of an item that failed, is not recorded, so the next pass
  refuses it. A plain batch (no `--watch`) has no previous poll and processes what is there.
  Code: `batch.settle_poll()`, `is_own_output()`, `deliver()`, `owned_config()`,
  `runner.owned_replaceable()`. Tests:
  `test_batch_watch_waits_for_a_source_to_settle_and_replaces_only_its_own_output`,
  `test_batch_watch_rechecks_its_own_output_where_it_replaces_it`,
  `test_batch_watch_step_refuses_its_own_output_replaced_before_its_check`,
  `test_batch_watch_replaces_its_own_side_files_but_not_an_edited_one`,
  `test_batch_watch_does_not_adopt_a_side_file_edited_while_the_step_ran`,
  `test_batch_item_never_replaces_a_side_file_another_item_delivered`,
  `test_a_step_replaces_only_the_files_batch_delivered_unchanged`,
  `test_batch_watch_reports_a_source_still_settling_when_it_stops`.
- **`verify.py` keeps each tool's own failure.** Steps run with `--json`; a failed step keeps the
  tool's `kind`, `reason`, `message`, `details` and `exit_code` (`step_timeout`,
  `step_output_unparsed` where the tool printed none), and the probe of an unreadable file keeps
  probe's own message instead of "ffprobe failed". `error` stays the one-line table cell. A step
  that does not apply is listed under the file's `skipped` (`quick`, `no_video`, `no_audio`,
  `not_hdr`, `not_multichannel`, `input_unreadable`) and as a SKIP row in the report; `total` and
  `failed` count only steps that ran, as before. Test:
  `test_verify_keeps_the_tools_own_failure_and_lists_the_steps_it_skipped`.

Part 3 converts the remaining fallbacks, skips and stderr-only warnings onto that infrastructure.
What was decided there:

- **A record is kept once per run; its stderr line is printed each time.** `_record()` does not
  append an entry identical to one already there, so a decision taken for every encode of a job
  (the libaom fallback, a CRF clamp, an odd-dimension retry) is one record. Code:
  `_common.emit._record()`. Test: `test_the_libaom_fallback_and_a_clamped_crf_are_recorded`.
- **Every code is a contract enum, and no tool prints a `warning:` line with `info()`.**
  `json_output.diagnostic_codes` lists each code with its bucket (warnings / fallbacks / skipped)
  and meaning; a source test reads every `warn()`/`record_fallback()`/`record_skip()` call against
  it in both directions, and another refuses `info("warning ...")` (or `print`/`stderr.write`) under
  `scripts/`, with no exception: part 2 converted `export.py`'s four (`colour_not_converted`,
  `output_audio_silent`, `loudness_outside_spec` twice) and `multicam.py`'s low-confidence line
  (`sync_low_confidence`, as `sync.py` records it), and the allowance the test held for them is gone. Code: `_contract.DIAGNOSTIC_CODES`. Tests:
  `test_every_diagnostic_code_is_in_the_contract_under_its_bucket`,
  `test_no_stderr_only_warning_is_left_in_the_sources`.
- **Which bucket.** A fallback is another route the run took and went on with, whose result
  differs from the asked one: an odd-sized frame scaled to even (`odd_dimensions_scaled_even`; the
  output is a row or column smaller), subtitle/data streams dropped on a retry
  (`non_av_streams_dropped`, with the first attempt's last stderr lines; `dropped_non_av_streams`
  stays the boolean it was), libaom for a missing SVT-AV1 (`av1_encoder_libaom`), a substituted
  font (`font_substituted`). A skip is a step that would normally run and did not: a dry-run
  measurement of a pending input, a `--fix-drift` correction (`drift_correction_skipped`). The rest
  are warnings, including `render.py`'s two defaults (`frame_from_export_preset`,
  `normalize_on_by_default`): they are choices made for the caller, and the stderr wording is
  kept (tests read `frame: 1920x1080 from the youtube export preset`). Tests:
  `test_an_odd_sized_source_scaled_to_even_is_a_recorded_fallback`,
  `test_run_keeping_subtitles_records_the_first_attempts_error`,
  `test_stderr_only_warnings_reach_the_document`.
- **An encoder list that could not be read is named, not taken for a missing encoder.**
  `ffmpeg_encoders()`/`ffmpeg_bsfs()` still return an empty set (every caller's membership test
  keeps working), but keep why (`ffmpeg_list_error()`: did not run, timed out, exited non-zero,
  listed nothing) and record it once (`ffmpeg_list_unreadable`). `--codec av1`/`prores` then refuse
  under their own reason, `kind: ffmpeg`, `error.reason: encoder_list_unreadable` -- not
  `missing_tool`, which a build that was never read cannot be said to be -- while a list that was
  read and lacks the encoder is `missing_tool`/`encoder_missing` as before. They still refuse
  rather than guess an encoder: the encode would run on the binary that could not even list its
  encoders. `--hw`'s CPU note says the VideoToolbox encoder "could not be confirmed". Code:
  `_common.runner._read_ff_list()`, `_common.decision._refuse_missing_encoder()`, `_vt_args()`.
  Test: `test_an_unreadable_encoder_list_is_named_not_taken_for_a_missing_encoder`.
- **The CRF clamp is reported where it bites, which is the HEVC HDR line.** It asks x265 for
  CRF+2, so `--quality 50`/`51` is encoded at 51 (`crf_clamped`, with requested, asked and used);
  the AV1 cap at 63 is checked the same way but `apply_common()` already refuses a higher
  `--quality`. Code: `_common.decision._clamped_crf()`.
- **`FFMPEG_SKILL_TIMEOUT` keeps its meaning and gains a record.** Not a number (or NaN): the
  default 1800 s, as before; negative: 0, i.e. no limit, as before (`max(0, value)`); each is a
  `timeout_env_invalid` warning, recorded only when no `--timeout` overrides the variable. Blank
  is unset. Changing a negative value to the default was considered and left: it would change what
  a running deployment's setting does in a patch. Code: `_common.runner._read_env_timeout()`.
  Test: `test_an_invalid_ffmpeg_skill_timeout_is_a_recorded_warning`.
- **`font_used` says which font file drew the text, as far as this process can know it.**
  `how` is `font_file`, `script`, `resolved` (fc-match, or the Windows Fonts folder), `by_name` (no
  file: ffmpeg or libass resolve the name themselves, so the file is not claimed), `fonts_dir` or
  `ass_styles` (`caption.py`). A resolved file is a substitute when none of the families
  fontconfig lists for it is the asked one, compared without case, spaces or punctuation and as a
  prefix either way ("DejaVu Sans Bold" is DejaVu Sans); a generic alias (`sans-serif`, `mono`,
  ...) is never a substitute. On Windows a family that is not in the Fonts folder is a substitute
  (Arial, or a CJK system font for a CJK-looking request). For libass on Windows nothing is
  resolved (`by_name`): libass may find the family itself, and claiming Arial there would be the
  same unverified guess this work removes. The script-coverage lines in `script_font_for_text()`
  became records too (`font_lacks_script`, `font_coverage_unverified`, `fonts_dir_lacks_script`).
  Code: `_common.fonts.resolve_font()`, `font_choice()`, `record_font_choice()`. Test:
  `test_the_font_drawn_with_is_reported_and_a_substitute_recorded`.
- **Counted skips get a field as well as a record.** `cropdetect.py` `windows`/`windows_failed`;
  `sync.py --fix-drift` `drift_skipped_reason` (`too_short` / `low_confidence` / null, also in each
  `sources` entry); `caption.py --ass` `caption.ass_shifted`/`ass_unshifted` (with `--offset`) and
  `ass_malformed`; `silence.py --filler` `filler.matched_untimed` and `matched_too_long`. The
  filler reader used to drop an untimed word before `filler_spans()` saw it, so it now hands them
  over to be counted; `word_timings` still counts only timed words. `sync.py` printed the
  single-source low-confidence warning twice (once per source, once overall); it is one
  `sync_low_confidence` record. Tests: `test_cropdetect_counts_the_windows_it_could_not_decode`,
  `test_a_skipped_drift_correction_says_why`, `test_caption_counts_ass_lines_it_could_not_shift_or_read`,
  `test_filler_words_with_no_timing_are_counted`.
- **A timeline that does not read back keeps its reason in a warning, not in the step.** The
  `parse` verification step stays `{step, ok}` (`render.py` is not touched here);
  `timeline.parses()` records `timeline_parse_failed` with the exception or what was read instead.
  A JSON value that is not an object is now a reason, not an `AttributeError`. Code:
  `_common.timeline.parses()`, `parse_error()`. Test: `test_a_timeline_that_does_not_parse_keeps_the_reason`.
- **The MCP server answers a line that is not JSON with `-32700`, id null.** A JSON value that is
  not an object and a notification still get no response (`test_mcp_server_survives_a_non_object_json_line`
  pins that): JSON-RPC answers an invalid request with `-32600`, but a scalar on stdin is no request
  this server can name, and replying to one was not asked for. Code: `mcp/server.py` `main()`. Test:
  `test_mcp_server_error_paths_raw_argv_and_call_helper`.

## 2.14.0 — the FFmpeg 5.x deprecation

- **FFmpeg 5.x is deprecated, not dropped.** The 5.x branches date from 2022. Debian 12 still
  ships 5.1, so raising `requirements.ffmpeg` is a break and waits for 3.0, which requires 6.1
  (Ubuntu 24.04's). Until then 5.0 keeps working, CI keeps its 5.1.1 job, and the version-specific
  workarounds stay. It follows the Python 3.9 route above: an entry in `contract --json`'s
  `deprecated`, and one stderr line from `doctor` and the `npx` installer when `ffmpeg -version`
  reads 5.x, never a key in `doctor --json` and never a failure. A git snapshot's version is not a
  release number and gets no line, the same rule as the security advisory. 3.0.0 removed
  the support and these tests; the refusal is pinned by `test_3_0_removed_python_3_9_and_ffmpeg_5_on_every_surface`
  and `test_every_tool_refuses_an_ffmpeg_older_than_6_1`.

## 2.15.0 — render.py's intermediate stages encode with veryfast

- **Only a stage whose output an encoding export re-encodes gets the faster preset.** (x265 on
  the HDR path takes the same `--preset` and the same reasoning.) What a
  caller keeps is export.py's encode, at its own preset; an x264 stage before it at `medium`
  spent about twice the time for detail the export re-encodes anyway. Measured on a 30 s 1080p
  reels render: 51.8 s → 41.7 s on FFmpeg 8.0.1, SSIM 0.997 between the two deliveries. Without
  an export stage, with `--stop-after` before it, or with a `copy` export, a stage's output is
  what the caller keeps, so it stays at the stage's own default. `--fast` (veryfast everywhere)
  and a stage's own `--preset` still win, and `--intermediate-preset medium` turns it off. The
  preset is part of each stage's arguments, so a `--cache` entry made at `medium` is not reused
  for a `veryfast` run. Code: `render.sh()`, `INTERMEDIATE`. Test:
  `test_render_intermediate_stages_use_veryfast_only_before_an_encoding_export`.

## 2.16.0 — intermediates at superfast, not ultrafast

- **`superfast` is the default intermediate preset; `ultrafast` is not.** Measured on a 30 s
  1080p reels render, with SSIM against a lossless reference of the same frame and captions:
  veryfast 33 s / 0.9863, superfast 30 s / 0.9868, ultrafast 26 s / 0.9814 (FFmpeg 8.0.1; on 6.1
  veryfast and superfast took the same time). superfast loses nothing the export keeps.
  ultrafast's last 4 s cost a visible step in quality, which the export cannot win back.
  Test: `test_render_intermediate_stages_use_veryfast_only_before_an_encoding_export` (its name
  is from 2.15; it asserts the current default).

## 2.17.0 — check.py --content's dropouts row

- **A dropout is a short gap of digital silence with sound on both sides, and it only WARNs.**
  The silence row measures a share of the running time, so 0.2 s of lost audio at a join (3%
  of a 6 s clip) passed. The new row counts gaps at or below -80 dBFS lasting 20 ms to 1 s,
  more than 50 ms from either end. -80 dB, far below the silence row's -50 dB, keeps a
  recording's own pauses (room tone at around -60 dB) out. A gap still open at the end is a
  tail, and one at the very start is a lead-in. The pass pads the audio with 2 s of zeros
  first, because audio that ends before the video would otherwise close its silent tail at
  its own EOF, inside the container's duration, and count as a dropout. A noise gate does make such gaps on purpose,
  which is why the row never FAILs and its fix says so. It costs one audio-only decode, because
  a second silencedetect in the main pass logs under the same name as the silence row's, and
  their lines could not be told apart. Code: `_common.probe._detect_dropouts()`. Test:
  `test_check_content_dropouts_row`.

## 2.17.2 — cut.py fades the sound at every --segments join it re-encodes

- **A re-encoded `--segments` join fades the sound 20 ms on each side, by default.** Two cuts
  butted together leave a step in the waveform wherever the sound was not at zero on both sides,
  and a step plays as a click. Measured on a 440 Hz tone, the step at the join was 14x the tone's
  own largest sample-to-sample change. 20 ms is too short to hear as a dip and long enough to
  remove the step. Only the sides that meet another segment are faded: the file's own start and
  end stay as cut. A stream-copy join copies the sound and cannot fade it without re-encoding the
  sound, which would make a lossless join lossy, so it is left as it was. The result's
  `declick_ms` reports the fade (null when no join was re-encoded), and `--no-declick` restores
  the butt join. `silence.py` is not changed: it cuts inside silence, where the sound is already
  near zero on both sides. Code: `cut._join_chunk()`, `DECLICK_S`. Test:
  `test_cut_segments_join_is_faded_so_it_does_not_click`.

## 2.17.4 — a non-ASCII font path on Windows

- **drawtext gets an ASCII font path on Windows, by short name or by copy.** FreeType opens
  `fontfile=` with the C runtime's ANSI `fopen`, so on Windows a font under a folder with a
  non-ASCII name does not load. On PR #365's runner (gyan.dev 9.0.2) the same font failed under
  `compat dir ünïcode` and loaded under an ASCII folder, with or without a space in the name and
  whatever the working directory. The 8.3 short form names the same file and is used when the
  drive keeps short names. Otherwise the font is copied into the run's private drawtext folder
  under a hashed ASCII name, recorded as `font_path_copied`, and removed with that folder when the
  run ends. A plan binds the user's font, not the copy. libass (`subtitles=`, `ass=`, `fontsdir=`)
  opens its files through FFmpeg and is not affected. Code: `drawtext.drawtext_fontfile()`.
  Tests: `WindowsFontPathTests`, `test_filter_paths_with_drive_colon_spaces_and_unicode`.

## 2.18 — results carry the VDC paper's co-reported items

- **A missing stream is a failed check, not a note.** The paper's seeded-defect run found that
  `cut.py` measured duration and start skew but not the output's stream composition, so an MPEG-TS
  cut that lost its whole video said `verified: true` (#367). The expected composition comes from
  the input's own probe and the tool's arguments (provenance `input_premeasurement`): a stream the
  input had and the operation was not told to drop must be there. `cut.py`, `join.py` and
  `export.py` check it through `emit(expect_streams=...)`. A missing stream fails the step rather
  than adding a warning, because the paper's three escapes all happened under a `verified: true`
  that the consumer believed. Code: `emit.stream_inventory_step()`. Test:
  `test_a_cut_that_loses_its_video_is_not_verified`, which seeds the defect and runs an unseeded
  control.
- **A failed step says its cause is unresolved.** A failed check asserts that one of the
  artifact, the reference, the measuring instrument or the expected value's provenance is wrong.
  No tool knows which yet, so every `ok: false` step carries `attribution: unresolved` unless the
  tool sets one. Re-running on an unresolved failure can destroy the evidence, so a caller should
  not.
- **`unverified` is a fixed list per tool, beside `emit()`.** The properties a tool does not
  measure are a property of the tool, not of the run, so they are a table (`UNVERIFIED`) that
  `emit()` attaches and the contract republishes as `unverified_properties`. A table outside
  `emit()` could drift from what the results say. The list names what a caller might assume was
  checked (caption placement, lip sync, the look of a grade), not everything in the world.
- **One true-peak tolerance, 0.1 dB.** The three tools used 0.1, 0.05 and 0.0 dB, so "verified"
  meant a different scale in each, and export could fail a file check passed. 0.1 dB is
  `loudness.py`'s existing margin: two loudnorm passes on the same encode differ by about that
  much. A tighter rule would fail files on measurement noise and send `loudness.py` round its
  re-encode loop for nothing. Code: `_platforms.TP_TOLERANCE_DB`. Test:
  `test_one_true_peak_tolerance_is_applied_and_reported`.

## 2.19.0 — filler words in Korean, Chinese, Russian, Dutch, Polish and Turkish

- **The new lists hold disfluencies only.** `ko` is 음/어/에/흠 and their doubled forms; `zh` is
  嗯/呃/唔 and their doubled forms; `ru`, `nl`, `pl` and `tr` are the hesitation sounds of each
  language. Words that are fillers as often as they are content stay out of the defaults and are
  named as discourse markers for `--filler-extra`, the same line `like` and `tipo` already sit
  behind: 그/저/뭐/이제 (저 is also "I"), 那个/这个/就是, ну/типа, şey/yani. `额` is a common
  filler spelling in Chinese chat, but it is also an ordinary character (金额, 额外), so it is in
  neither list. The lists are seeds with no measured accuracy, like the 1.17 ones (P2-11). Code:
  `FILLER_WORDS`, `FILLER_DISCOURSE_MARKERS`. Test:
  `test_every_new_language_list_holds_disfluencies_only`.
- **A filler may span several engine tokens, and in an unspaced script it needs a word boundary
  on each side.** Whisper splits Chinese, Japanese and Thai into tokens, not words: its own
  vocabulary turns えーと into えー + と and 金额 into 金 + 额. Before 2.19 only a single token
  could match, so the `ja` list's えーと and えっと never matched and えー was cut with と left
  behind. Now a run of up to `FILLER_MAX_TOKENS` tokens that joins to a listed word is that word,
  and the longest run wins. Matching runs of tokens can also join the middle of a real word
  (あの + 人 is "that person"), so in those scripts a run is cut only when punctuation, a pause of
  `FILLER_BOUNDARY_GAP` (0.1 s), the transcript's edge or a spaced-script word sits on each side.
  A filler spoken straight into the next word with no pause is kept: a missed "um" costs less than
  a cut word. Spaced languages keep the old whole-word rule, and a two-word marker such as
  `you know` now matches too; `--help` offered it, but it could never match one engine word. Code:
  `filler_spans()`, `_unspaced_script()`. Tests:
  `test_a_filler_split_across_whisper_tokens_is_one_word`,
  `test_an_unspaced_filler_needs_a_word_boundary_on_each_side`,
  `test_a_two_word_discourse_marker_added_with_filler_extra_matches`.
- **whisper.cpp tokens in an unspaced script are not glued.** whisper.cpp marks a word start with a
  leading space, so in Japanese or Chinese every token "continued" the one before and a whole
  segment became one word, which no filler could match. Between two whole characters of such a
  script the tokens now stay apart, as openai-whisper and faster-whisper split them. A token that
  is part of a character (U+FFFD) is still glued. Code: `_words_from_whisper_cpp_json()`. Test:
  `test_whisper_cpp_json_becomes_word_timings`.
- **Traditional Chinese is a font choice, not a script.** Simplified and Traditional Chinese share
  most code points but draw some differently, so the characters cannot tell them apart; only the
  caller's `--lang` can. `zh-TW`, `zh-HK`, `zh-MO`, `zh-Hant` and `yue` look the font up under
  `zh-hant` while the script stays `zh`, so line breaking and `doctor`'s `fonts.scripts` are
  unchanged. A machine with no Traditional face draws with the Simplified one and records
  `font_variant_missing` rather than refusing: the characters are there, in the other form, and a
  caption in a slightly different glyph form is a delivery where a refusal is not. Code:
  `fonts.font_key()`, `HANT_TAGS`. Test: `TraditionalChineseFontTests`.

## 2.20 — a length or a silence is checked against a yardstick the tool did not make

- **export.py holds the written length to the preset's maximum, as check.py does.** The paper's
  baseline experiment shipped a 90.10 s Reels file under `verified: true` while `check.py` failed it.
  The step measures the container's duration with no tolerance, because that is the number and the
  rule `check.py` applies. Any other margin would bring back two verdicts on one file. The source of
  the extra 0.1 s, `loudness.py` lengthening the sound, is fixed too, but the step does not depend on
  that fix. Code: `export.py`. Test: `test_export_measures_the_length_its_preset_promises`. Since #485
  `check.py` reports the table's length limit as guidance (WARN), so the two no longer give the same
  severity: the export step verifies the trim `export.py` itself made, with the same number and no
  tolerance, and stays a failing step.
- **loudness.py trims the sound to the input's length.** loudnorm's last block and the AAC encoder
  made the output run 0.015 s long on 6 s and 0.1 s on 90 s. A levels pass should change no timing,
  so `atrim=duration=` keeps the input's audio length, counted from the first sample. `end=` is a
  timestamp, and it cut the tail off sound that starts late. atrim follows loudnorm directly: an
  `aresample` between the two fails channel-layout negotiation on FFmpeg 5.1. A `duration` step
  allows one AAC frame of difference, at least 0.03 s. Test:
  `test_a_levels_pass_keeps_the_input_length_and_says_so`.
- **join.py reports the clips' total beside the joined length, and does not fail on the
  difference.** The expected length comes from the transition the join applied (provenance
  `input_premeasurement`), so on its own it cannot show that a fade took time out of the material:
  15 s of clips played as 14 s. The shortening is what a fade does, so it is not a failure. It is
  reported (`inputs_duration`, `transition_shortening`, a note) so the caller can hold it against
  the user's own expectation. Test: `test_join_reports_the_clips_total_next_to_the_joined_length`.
- **silence.py labels each removed span `digital` or `below_threshold`, and removes both as
  before.** Quiet sound under `--threshold` is what the user asked to remove, so the cut is
  unchanged. Reporting room tone and digital silence as the same "silence" hid that the cut took
  audible material, so each span is labelled. A span is digital when at least 99% of it sits at or
  below -90 dBFS, measured by one more silencedetect pass. That is near the 16-bit dither floor and
  far below any speech. Test: `test_silence_says_which_removed_spans_were_digital_silence`.

## 2.21.1 — a stream that ends early or decodes nothing fails the check

- **The streams check counts streams, compares where they end, and decodes both ends.** 2.18's
  `streams` step only asked whether a video and an audio stream were there. A report on X described
  a filename with a space that lost 40 s of sound with no error, and the container's length could
  not show that, because it is the longest stream's. `stream_lengths` compares where the picture and
  the sound end. It allows the gap the inputs already had (summed over join's clips) plus 0.25 s, so
  a source whose sound is shorter by design is not a failure. It compares ends, not lengths: a
  stream that only starts late is the start skew that cut.py reports in a note and does not fail
  (2.8.0, above). `decode` decodes the first and last second of every kept stream. A header can list a
  stream whose payload no decoder accepts, and only reading the payload shows that. The tail read
  starts 10 s earlier, because an MPEG-TS seek can land past the last keyframe. A length that cannot
  be read fails the step, as in 2.20. Code: `emit.stream_lengths_step()`, `emit.decode_step()`.
  Test: `test_a_damaged_ts_cut_names_the_stream_that_broke`, which writes three damaged files over
  a real cut's output (video removed, sound cut to 0.8 s, payload zeroed) and runs an undamaged
  control.
- **A TS stream copy that wrote no video is redone as a re-encode, not only reported.** The
  defect behind #367 is not random: the TS demuxer does not seek back to a keyframe as the MP4 one
  does, so a copy whose window holds no video keyframe writes no video packets, and ffmpeg exits
  0. The tool can tell which streams are missing and has a correct route, so it re-encodes that
  segment (`reencode_reason: stream_lost`), as it already does when a copy fails or lands past
  `--tolerance`. Test: the control in `test_a_damaged_ts_cut_names_the_stream_that_broke`, whose
  TS source has one keyframe at 0.
- **A printed command is quoted for a shell by an allow-list.** ffmpeg always receives an argv
  list (no shell, pinned by `test_every_tool_help_and_no_shell_paths`). The printed `commands`,
  though, are meant to be pasted and run again, and a deny-list of characters missed the backtick,
  a leading `#` and `~`, and `!`. Any argument outside `[A-Za-z0-9_@%+=:,./-]` is single-quoted now.
  Test: `test_printed_commands_run_unchanged_in_a_posix_shell`, which runs the quoted line in `sh`.

## 2.22 — silence.py says where it cut, and where to listen

- **A cut near sound is a warning, not a failed check.** `cut_points` measures the RMS 50 ms
  either side of every cut on the source, and `cut_warnings` lists those within 10 dB of
  `--threshold` (`CUT_SOUND_MARGIN_DB`). Room tone sits well below the threshold; a breath or a
  word's weak tail sits just under it. A level is not a judgement of speech: a quiet word and a
  loud breath can read the same, and a cut the user asked for at -25 dB is still what they asked
  for. So `verified` is unchanged, the warning says where to listen, and `removed_span_content`
  stays in `unverified`. Filler-word cuts sit in sound by design and are measured but not
  flagged. Code: `silence.cut_levels()`. Test:
  `test_silence_reports_the_level_at_every_cut_and_warns_near_speech`, where the default
  threshold cuts in digital silence (no warning) and -25 dB cuts into a -29 dB tail (a warning).
  The level is the loudest channel, not a mono mix (antiphase stereo would read as silence);
  `filler` is set per edge, so a filler merged into a silence leaves the silence's other edge
  checked; a decode that fails gives `cut_points: null` and `cut_levels_unmeasured`, never a
  silent reading. The `--timemap` file is checked up front (path, existing file) and written
  only after the cut: a map beside a refused or failed encode would describe media never made.
  Test: `test_silence_time_map_and_cut_levels_hold_at_the_edges`.
- **No second padding flag; `--margin` goes from 0.15 s to 0.2 s.** A request asked for
  100-300 ms of padding around cuts, with a safe default. `--margin` is that setting already, and
  `--speech-aware` keeps breaths inside a sentence. A `--padding` alias would be a second name for
  one setting in the contract and every surface that lists flags, so the docs point at `--margin`.
  The default moves to 0.2 s, still inside the asked range: weak word endings were the complaint,
  and 50 ms more air per side costs a little tightness, which `--margin 0.15` gives back. A
  template that sets its own margin (`templates/podcast.json`, 0.15) keeps it. Test: the default
  check in `test_silence_reports_the_level_at_every_cut_and_warns_near_speech`.
- **`--timemap` is an artifact, like `--edl`.** It is written beside the cut and not under
  `--dry-run`. Its output times are the sums of the ranges the render holds: with a picture, each
  kept range with its bounds moved to the nearest frame time (the bounds the re-cut is given,
  #409), with sound alone the kept range as asked. Tests:
  `test_silence_writes_a_map_from_source_to_output_times`,
  `test_silence_keeps_sync_and_its_time_map_over_many_ranges`.

## 2.23 — check.py --content's flashes and first-frame rows

- **A flash is one frame unlike both neighbours that match each other, and it only WARNs.** The
  rule is a step of at least 12/255 mean luma into the frame and out of it (on 64x36 grey
  frames, where moving footage stays at a few units and a cut moves tens), with the frames on
  either side within a quarter of the smaller step of each other. The return test is what
  separates a flash from fast motion: a whip pan steps as far on every frame, but its frames
  never come back, and with the test switched off it reported 58 flashes in 6 s. A hard cut steps once,
  and a cut away and back holds more than one frame; neither is a flash. A camera flash in the
  footage or a deliberate strobe is real, which is why the row never FAILs and its fix says
  so. Code: `_common.probe.detect_flashes()`. Test:
  `test_check_content_flashes_and_first_frame_rows`.
- **The flash pass reduces each frame to three numbers inside ffmpeg.** `tblend` gives
  |f[n] - f[n-1]|; two `tmix` branches with weights -1 0 1 and 1 0 -1 give the two clipped
  halves of f[n] - f[n-2], whose sum is its absolute value; each is averaged to one 16-bit
  pixel. Piping the frames themselves through Python would cost memory in proportion to the
  running time; this costs 6 bytes a frame. It is a separate video-only pass, because its
  output is raw data on stdout while the main pass is parsed from stderr. Raw frames carry no
  timestamps, so a flash is found by frame index; its time is that frame's own presentation
  time, read from the stream's packet timestamps (sorted, the hidden pre-roll before the
  stream's start dropped; no decode), measured from the container start as `look.py --at`
  seeks, so a timestamp gap before the flash is counted. Without timestamps it is index /
  average rate plus the video's lead, marked `~`, and `frame N` without a rate either. A video
  that decodes no frame, or a flash pass that fails, is "could not measure", not 0 flashes.
  Attached pictures (cover art) are skipped (`V`, not `v`), as probe skips them.
- **`first frame` and `flashes` are `kind: judgement`.** Neither has a mechanical fix: a fade
  from black or a strobe can be the edit. A first frame that does not decode is a WARN
  ("could not measure"), not a missing row.
- **A flat first frame WARNs; a dark one does not by itself.** Flat means a luma spread under
  4/255 at 64x36: a black lead-in, a solid colour. Darkness alone is not the test, because a
  dark shot is still a picture. A fade from black is often the edit, so the row is a WARN whose
  fix starts with "a fade from black is a choice", for the destinations where autoplay or the
  preview shows frame 0. Code: `_common.probe.first_frame_stats()`. Same test.
## 2.24 — join.py --copy and cut.py --remove

- **`--copy` is opt-in, and a mismatch is refused rather than re-encoded.** A join that
  re-encoded by default and copied when it could would change what an existing call does, which
  the stability promise allows only for a defect; and a caller who asked for a copy and got a
  re-encode would learn it only from `mode`. So `--copy` either copies or refuses, naming each
  clip that differs and how. The comparison is cut.py's `--segments` one
  (`_common.probe.stream_signature()` / `signatures_match()`, moved there so both use it), on
  the first video and the first audio stream, which are the streams the join maps. Test:
  `test_join_copy_joins_matching_clips_and_refuses_a_mismatch`.
- **What a matching signature does not catch is checked too.** An MP4 edit list that
  hides pre-roll frames (packets flagged discard in the first 300): the concat demuxer ignores
  edit lists, so a copy join would show them. Picture and sound that end more than 50 ms apart
  at either end of a clip (each stream's start, and its start plus its length): the demuxer starts the next clip where this one's container ends, so the shorter
  stream leaves a held frame or a hole in the sound there. And the result itself: its video
  packet count against the clips' total, and its video length against their summed length
  (within 50 ms per clip plus a frame), measured on a file beside the output that is renamed
  into place only when both hold. Same test.
- **Clips must lay out their streams alike.** The concat demuxer maps each clip's packets by
  stream index into the first clip's layout, so a cover picture stored between the video and the
  sound in one clip would put that clip's sound on another stream. A different stream count or
  order is refused before the signatures are compared. Same test.
- **`cut.py --remove` is `--segments` written the other way.** It builds the keep list and
  hands it to the same code, so a removal is cut, joined, declicked and verified exactly as the
  equivalent `--segments` would be. Overlaps merge and the ranges are clamped to the file; a
  leftover shorter than one frame (10 ms without a frame rate) is not a piece anyone asked to
  keep, and to a video output neither is one that holds less than one frame of the picture (#462
  A51, below). A range may start before 0 (it is clamped like the end). `--snap beats` is refused with
  it: a snapped edge of what is kept could move into a range the caller asked to drop, and the
  flag's promise is that those ranges are gone. Test: `test_cut_remove_keeps_the_rest`.

## 2.24 — output identity and check.py --compare

- **An output is identified by size and modification time, not a hash.** The point is to tell
  the file a run wrote from whatever sits at the path later (an older file a failed `--overwrite`
  run left, a file another run replaced). Size plus `mtime_ns` changes on any rewrite and costs
  one `stat`; a sha256 of an hour-long master costs seconds and proves nothing more for that
  purpose. Code: `_common.emit.file_identity()`. Test:
  `test_check_expect_identity_ties_the_check_to_one_write`.
- **`--expect-identity` is a FAIL, not a WARN.** The row exists for the case where the file is
  not the one the caller believes it is checking; passing the other rows on that file would be
  the false success the flag is there to stop. Without the flag check.py grades the path as
  before and only reports `input_identity`. Same test.
- **`--compare` pairs frames in decode order and reports, it does not align.** SSIM and PSNR are
  ffmpeg's own filters in one pass. Those filters pair by timestamp, so both pictures are re-timed
  to their frame index first (`setpts=N`): a shifted or irregular timestamp cannot meet the wrong
  reference frame. A dropped or added frame shifts every later pair, so a different frame count
  (from `nb_frames`, or counted from the packets when a container does not state it) is named in
  `notes` rather than hidden. Frames of another size are not compared at all (WARN, "not compared"): scaling one of
  them first would measure the scaler. The WARN line is a mean SSIM of 0.98, where differences
  start to be visible on ordinary footage; the worst frame and its time say where to look
  (`look.py --compare`), the time read as the flashes row reads it (that frame's presentation
  time, `~` index / rate without one). Cover art is not the picture compared (`V`, not `v`). Code: `_common.probe.compare_pictures()`. Test:
  `test_check_compare_measures_against_a_reference`.

## 2.24 — export.py --max-mb

- **A size limit is a two-pass x264 encode at a computed bitrate, then measured.** The budget is
  97% of MB MiB (the rest is the container's overhead), less the preset's own audio bitrate, over
  the running time the export keeps (the preset's maximum when it trims). One pass at that bitrate
  misses on content whose complexity changes; two passes are what x264 offers for a size. The
  size is still measured, because x264's rate control is a target, not a bound: an overshoot is a
  `file_size` verification failure and a `size_over_limit` warning, not a silent pass. Test:
  `test_export_max_mb_fits_the_size`.
- **What it cannot do honestly is refused.** Another encoder (the HEVC, AV1, ProRes, GIF and copy
  presets; VideoToolbox under `--hw`, which has no two-pass mode), `--crf` (a quality, not a
  size), a source with no duration, and a budget that leaves under 100 kb/s for the picture. A
  size that small makes an unwatchable file the user did not ask for, so the refusal says the
  bitrate it would have been. Same test.

## 2.24 — export.py --repair

- **Repair is a flag on the copy preset, not a tool.** It is a remux with three input flags
  (`-fflags +genpts+discardcorrupt -err_detect ignore_err`) and `-avoid_negative_ts make_zero`:
  the copy preset with different demuxing, so a new tool would add a name without adding a job.
  A re-encoding preset already decodes past damage, so `--repair` with one is refused as
  meaningless. Test: `test_export_repair_counts_damage_before_and_after`.
- **It is measured by what a decoder says, before and after.** One full decode of each file at
  `-v warning`, lines about timestamps counted apart from the rest. The verification step is
  judged on timestamp warnings only, the part a remux rewrites, and fails when the output has more
  than the input. Decode errors are reported before and after but not compared: they are log
  lines, and the same damaged frame logs a different number of them demuxed from TS than from MP4
  (one run of this test logged 51 before and 53 after on a remux that dropped nothing it should
  have kept). Errors that remain are named (`repair_incomplete`) with the way out (a re-encoding
  preset). On a TS file with 40 bytes of video payload overwritten (never a TS header or table, so
  every ffmpeg version still opens it): 99 decode-error lines before, 100 after, no timestamp
  warnings either side. Same test.

## 3.1.5 — both streams on one clock (#409)

ffmpeg shifts every stream of an input by one constant, so a filter graph sees a sound that starts
0.3 s after its picture at 0.3. Every item below had rebased a stream to its own first sample
(`PTS-STARTPTS`), or cut each stream on its own grid, and lost that offset while reporting
`verified: true`. Each now does what `cut.py --segments --accurate` does ("Both streams of a segment
shift by one constant", above): both streams cut on the same bounds, shifted by the same constant,
and a late sound padded with silence (`aresample=async=1:first_pts=0`), through the helpers in
`_common/decision.py` (`stream_starts`, `frame_rate`, `grid_at_or_after`, `av_trim`,
`av_clip_length`). Each was measured with a one-frame flash and a 40 ms beep at the same instant.

- **`silence.py` renders through `cut.py`'s re-cut, without its declick fade.** The one-pass
  select/ametadata graph rounded every kept range twice, the picture to whole frames and the sound
  to whole AAC frames, so the errors added up: 150 ms over 21 ranges of a 61 s source, and the
  `--timemap` with them; its `asetpts=N/SR` moved a late sound 280 ms early. `cut.join_from_source`
  is exact on both and handles the late sound, the 32-input limit and the chunking, so the tool
  calls it rather than a second copy. Each kept bound first moves to the nearest frame time (a
  measured bound sits microseconds off a frame, and the re-cut's "first frame at or after" would
  then drop that frame), so a range holds whole frames between its bounds; the old `between()` kept
  both boundary frames, one frame more per range (7.1 s where 7.0 s was kept). The joins sit in the `--margin` the tool keeps, so `DECLICK_S` is 0 for it, as 2.17.2
  decided. `keep`, `kept_duration`, `removed_seconds` and `--edl` report those rendered ranges too,
  an EDL frame time written down to the millisecond so `cut.py --segments` re-cuts the same frame
  (#416 review). Code: `silence.main()`, `silence.rendered_ranges()`. Tests:
  `test_silence_keeps_sync_and_its_time_map_over_many_ranges`,
  `test_silence_keeps_a_late_sound_where_it_was`, `test_silence_reports_and_exports_the_ranges_it_renders`.
- **`decode_pcm_mono` pads a sound that starts late, so its samples are on the file's clock.**
  `sync.py` measured a track 0.3 s late at +2.279 s for +2.000 s, `--replace-audio` placed it 270 ms
  late, and `multicam.py --audio` rebased the chosen camera's sound to its first sample. The decode
  now ends in `aresample=async=1:first_pts=0` for every caller (scenes.py's envelopes and cut.py's
  beat grid included, which were off the same way); `sync.py`'s writes and `multicam.py`'s audio
  chain place the sound on its own file's clock before they delay it. Code:
  `_common/probe.py` `decode_pcm_mono`, `sync.main()`, `multicam.main()`. Test:
  `test_a_late_sound_is_measured_and_placed_on_its_files_clock`.
- **`freeze.py` and `speedramp.py` cut on frame times and shift both streams together.** The head
  starts at the first frame and every boundary is the first frame at or after the asked time; sound
  before the first frame is dropped, as in a join. `freeze` was off by +279 ms (late sound) and
  -100 ms (late picture); `speedramp` by +570 ms at 0.5x, the factor scaling the offset. Code:
  `freeze.main()`, `speedramp.main()`. Tests: `test_freeze_keeps_a_late_sound_and_a_late_picture_in_sync`,
  `test_speedramp_keeps_a_late_sound_in_sync`.
- **`join.py` and `broll.py --audio b|mix` shift the sound by the picture's start.** #338 started
  each clip's picture at 0, and the sound was rebased on its own, so a sound 0.3 s late joined
  279 ms early; `broll` did the same with B's sound. A clip's length (`clip_length`, now
  `av_clip_length`) counts where its sound ends from the first frame, so a late sound that runs past
  the picture is not cut. Code: `join.clip_length()`, `join.main()`, `broll.main()`. Tests:
  `test_join_keeps_a_late_sound_where_it_was`, `test_broll_b_audio_keeps_a_late_sound_in_sync`.
- **`reverse.py` reverses both streams about one end, a frame time.** Each stream was reversed about
  its own end: a sound 0.6 s longer than its picture came out 396 ms off. Both now start at the
  first frame and end at the first frame time at or after the clip's length, the last frame held
  and the sound padded. The end is a frame time because a stream copy's stated video length can
  run past its last frame (7.517 s for frames that end at 7.5), which would leave the picture's end
  a fraction of a frame from the sound's; such a clip gains one held frame. The reversed sound is
  retimed by its samples (`asetpts=N/SR/TB`). Code: `reverse.main()`. Test:
  `test_reverse_turns_both_streams_about_one_end`.
- **`loop.py` repeats through the concat demuxer, not `-stream_loop`.** `-stream_loop` takes a
  repeat's length from its streams' spans, leaving out the last video frame when there is sound, so
  with a late sound each repeat lost a frame and the sound slid (795 of 810 frames, 43-51 ms). A
  concat list naming the file once per repeat places each repeat at the file's duration. The concat
  demuxer counts an MP4's hidden AAC priming into its start (-21 ms) where the MP4 demuxer does not,
  and a frame-rate time base rounded the picture's 21 ms move to 33 ms, so the first frame's place
  on the list's clock is measured (`concat_first_frame`, one ffprobe) and both streams shift by it;
  `min_hard_comp=0.001` fills a late sound's gap at every repeat, however short. Code:
  `loop.main()`. Test: `test_loop_keeps_a_late_sound_in_sync_on_every_repeat`.

## 3.1.5 — square pixels, and the geometry audit (#411)

- **A tool that sizes, crops, places or draws on the picture works on square pixels at the
  display aspect; a tool that only re-encodes keeps the stored size and its SAR.** DV, HDV and
  XDCAM 1440x1080, and DVD store non-square pixels (`sample_aspect_ratio`, which `probe.py` now
  reports). Every scaling tool used to fit the stored size as if its pixels were square and then
  `setsar=1`, so the picture came out squashed, and caption / overlay / graphics drew glyphs the
  player then stretched 1.78x. Of the two consistent answers (normalise, or carry the SAR through
  every graph), normalising is the one a filter graph can keep: `overlay`, `xstack`, `hstack`,
  `concat`, `drawtext` and libass all place in stored pixels, so carrying the SAR would mean
  correcting every coordinate and every font size in every tool. So the picture is scaled to
  square pixels first, keeping its height (1440x1080 at 4:3 is 1920x1080; 720x480 at 8:9 is
  640x480; the width rounds to even), and every size, rectangle and margin is in that frame --
  the frame `look.py` shows and `cropdetect.py` measures, so `crop.py --x/--y/--width/--height`
  and `redact.py` rectangles mean what a reader of the sheet sees. A tool that does not touch
  geometry (`cut`, `color`, `denoise`, `pad`, `freeze`, `export --no-scale`, a stream copy) keeps
  the stored size: the encoder writes the SAR through and the player shows it right. The scale is
  said once in `notes` ("stores non-square pixels (SAR 16:9): its 360x360 picture was scaled to
  640x360 square pixels"). Code: `_common.probe.display_size()`, `square_pixels()`,
  `square_pixels_note()`, used by fit, export, crop, join, broll, multicam, insert, sequence,
  grid, look, scenes --sheet, caption, overlay, graphics, redact, proxy, cropdetect, straighten,
  waveform --image and render's timeline frame. Tests: `GeometryAuditTests` (test_editing.py),
  `GeometryAuditPictureTests.test_text_tools_draw_on_square_pixels`,
  `test_grid_squares_a_non_square_pixel_cell`, `GeometryAuditAnalysisTests.test_look_shows_a_non_square_pixel_source_at_its_display_aspect`,
  `GeometryAuditDeliveryTests`.
- **An EXIF-rotated still is sized as ffmpeg shows it, upright.** FFmpeg 6.1 already reads the
  JPEG Orientation tag into the decoded frame's display matrix and autorotates on decode, but
  `-show_streams` has no rotation for it, so `insert.py` cropped a landscape window out of a
  portrait photo. `probe()` reads the first decoded frame's rotation for a still (an image2 or
  `*_pipe` demuxer: one extra ffprobe of one frame) and reports it as `rotation`, so every tool's
  existing rotation handling applies; the picture itself is left to ffmpeg's autorotate, exactly
  as for a phone video (2.10.7). Code: `_common.probe._still_rotation()`. Test:
  `test_insert_turns_an_exif_rotated_still_upright`.
- **`overlay.py --text` wraps a line wider than the frame, and says so.** drawtext never wraps;
  graphics.py and caption.py break text with the shared phrase wrapper, and overlay now does too,
  between the side margins (an explicit `x,y` position counts from x) at `--font-size`, with
  `slice_overlong`. Text that fits is unchanged; a wrapped run says "wrapped to N lines" in
  `notes`, since the width is the averaged advance table's estimate. graphics.py's `title`,
  `lower-third`, `chapter` and `bug` now go through its `wrapped()` as `sticker`, `hook` and `meme`
  already did, and the lower-third bar widens (up to the margins) to the widest wrapped line.
  Tests: `test_overlay_text_wraps_to_the_frame`, `test_graphics_title_wraps_a_long_title_and_subtitle`,
  `test_graphics_lower_third_wraps_inside_the_margins_and_widens_its_bar`,
  `test_graphics_chapter_chip_wraps_between_the_margins`.
- **A grid label is drawn with a font that covers its own script, and a label wider than its
  cell is shortened from the end with an ellipsis.** The label is right-aligned, so a long one
  used to lose its start off the cell's left edge; the start is the part that tells takes apart.
  `font_used` is the first label's choice; labels that needed different fonts are named in a
  note. Thai is drawn by drawtext here (a filename label on a comparison artefact, not a
  delivery), so its marks are not shaped. Tests: `test_grid_keeps_the_start_of_a_long_label`,
  `test_grid_label_font_covers_its_script`.
- **`freeze.py --at T` holds the frame shown at T** (the first frame whose time is at or after
  T), not the frame before it, so a freeze on a cut holds the new shot. The held frame is a segment
  of its own, cloned (`tpad`) before its `setpts`, as `reverse.py`'s held last frame is: from FFmpeg
  7.0 `setpts` leaves the frame rate unknown and frame durations 0, so a clone after it lands on
  one timestamp and is dropped. The held frame is taken as the first frame after the cut's
  half-frame tolerance (`trim=end_frame=1`), not a one-frame window, so a variable-frame-rate gap
  at the cut still yields one; with no frame at or after T (no `--at`: the clip's end) `--mode
  insert` holds the last frame as `--mode extend` does. Tests:
  `test_freeze_at_holds_the_frame_shown_at_that_time`, `test_freeze_without_at_holds_the_last_frame`,
  `test_freeze_holds_a_frame_on_a_variable_frame_rate_gap`.
- **hh:mm:ss:ff still counts from the file's first frame, not from a start timecode** (the time
  grammar above is unchanged). When a four-part time reads past the end of a source that carries
  a start timecode, the refusal's `hint` says so and names the frame from the file's start that
  the source timecode is. A time in another input than the first (a B-roll's `--from`, an
  overlay layer's `--place` range) is judged against that input's own timecode and length
  (`time_arg(..., source=meta)`). Code: `_common.decision._remember_smpte_hint()`, `emit.die()`.
  Tests: `test_a_smpte_time_past_the_end_of_a_timecoded_source_names_its_start_timecode`,
  `test_the_smpte_hint_names_the_timecode_of_the_input_the_time_is_in`.
- **look.py's contact sheet reads its stamps off the file's own timestamps** (`-copyts
  -start_at_zero`), not pts plus the seek: an input `-ss` resets an MPEG-TS's timestamps
  differently from an MP4's, and the sheet of a TS was stamped one seek late. `scenes.py --sheet`
  picks each scene's first frame by its time, not by start x average fps as a frame number,
  which named another frame on a variable-frame-rate source. `look.py --compare` letterboxes both
  pictures into boxes as tall as the taller one instead of stretching the first to the second's
  size. Tests: `test_contact_sheet_stamps_count_from_the_file_start_on_mpeg_ts`,
  `test_scenes_sheet_picks_each_scene_start_by_time_on_vfr`, `test_compare_keeps_each_pictures_aspect`.
- **broll.py scales an odd-sized A-roll to even up front** (`odd_dimensions_scaled_even`, the
  runner's code): the runner's even-scale retry reaches a `-vf` only, and broll's
  `filter_complex` failed unclassified. Test:
  `test_broll_scales_an_odd_sized_a_roll_to_even_and_records_it`.
- **Wrapping measures width; height is said, not fitted** (#416 review). `overlay.py --text` and
  `graphics.py --template title` wrap to the width and do not shrink the font to the height: a
  block that comes out taller than the frame, or text placed too near an edge to wrap at all, is
  drawn as asked and named in `notes` (the size is the caller's choice; the estimate is the
  averaged advance table's). Tests: `test_overlay_text_says_when_it_still_does_not_fit`,
  `test_graphics_title_says_when_the_wrapped_block_is_taller_than_the_frame`.
- **`straighten.py --fit crop` scales by |cos| + max(W/H, H/W) |sin|** of the displayed frame: the
  window turned back by the angle must fit the scaled frame on both axes; |cos| + |sin| is a
  square's factor and left two corners black on 16:9 (#416 review). The output is the displayed
  frame's own size (to even), with square pixels: the scale is rounded up to even so it still
  covers the window, where `trunc(iw/s/2)*2` after `scale=iw*s` lost 2 px on each axis (audit
  A235). Tests: `test_straighten_crop_fit_covers_all_four_corners_of_a_wide_frame`,
  `test_straighten_crop_writes_the_source_size_with_square_pixels`.
- **`loop.py` has no repeat cap** (#416 review): the concat list costs one ~100-byte line per
  repeat against an output that costs a whole clip per repeat, so any count whose list strains
  memory asks for an encode that fills the disk first; `-stream_loop` had no cap either.

## 3.1.7 — the same mechanisms, where the earlier fixes did not reach (#414)

- **`silence.py --margin` is kept around silences only, not around filler spans.** A filler cut is
  the word plus `--filler-pad`; taking 0.2 s off each side as well turned every word narrower than
  2 x `--margin` inside out (overlapping keep ranges, kept longer than the input, the word still
  there and reported as removed). The margin is applied to each silence before the merge
  (`inside_margin`), and a silence too narrow to hold two margins removes nothing. Code:
  `silence.inside_margin()`, `silence.keep_ranges()`. Tests:
  `test_filler_margin_does_not_swallow_a_short_filler`,
  `test_a_silence_narrower_than_two_margins_removes_nothing`.
- **A transcript is on the file's clock.** The speech engine's 16 kHz WAV (and `--karaoke`'s
  word-energy decode) pads a sound that starts late (`aresample=async=1:first_pts=0`), as
  `decode_pcm_mono` does since #409, so cue and word times count from the file's start. A Whisper
  transcript with no text is `no_speech` for `--filler` as for `caption.py`; one with text and no
  word timings is still a build without them. Code: `asr.engine_wav()`,
  `asr._whisper_heard_nothing()`. Tests: `FakeWhisperCppTests`,
  `test_word_timings_from_silence_are_no_speech_not_a_build_without_them`.
- **An exported timeline counts source positions from each source's start timecode, at its own
  rate.** Project times still count from the file's first frame (the time grammar is unchanged);
  the export adds the source's start timecode, so a conform finds the frames: EDL source
  timecodes are the clip's own frames from its timecode (drop-frame labels, `;`, where the source's
  timecode is drop-frame; the record side stays `FCM: NON-DROP FRAME`), the FCPXML asset `start`
  is that timecode and OTIO's `available_range` starts there. An `out` past a source's end ends
  at it, with a note, because the render's `cut.py` clamps it; an `in` at or past the end is
  refused as `cut.py` refuses it. A chapter `metadata.py` would refuse (at or past the end, or not
  after the one before) is refused, which is what "Neither path accepts a time the other refuses"
  already said. A music bed's own timecode is not read (an audio file rarely carries one). A
  start timecode the source's rate cannot have (frame 29 at 25 fps, a frame drop-frame counting
  skips) is read as none, as `probe()` skips a malformed tag, and the EDL `M2` speed is in the
  clip's own frames per second, the rate its source labels count in. Code: `timeline.build()`,
  `timeline.start_tc_frames()`, `timeline._tc_label()`. Tests:
  `test_the_source_start_timecode_is_carried_into_every_format`,
  `test_a_start_timecode_that_does_not_exist_at_the_source_rate_is_not_read`,
  `test_edl_source_timecodes_are_at_each_clips_own_rate`,
  `test_a_clip_out_past_the_media_end_ends_at_the_media_end`,
  `test_a_chapter_metadata_py_refuses_is_refused_not_dropped`.
- **caption.py rewrites a caller's SRT only when ffmpeg would read it differently.** ffmpeg's SRT
  demuxer requires hours and reads the milliseconds field as an integer (`,5` is 5 ms), where
  `parse_srt()` accepts `mm:ss,ms` and reads `,5` as 500 ms. A file whose every timing line is
  `hh:mm:ss[,.]mmm` reads the same to both and is still given to ffmpeg as it is (no side file for
  a BOM, CRLF or a period separator); any other goes as the `_adjusted.srt` copy the tool writes
  (an extra `--mode mux` track as `_trackN.srt`). Always writing the copy would add a side file to
  every run for files both readers agree on. Code: `caption.srt_timings_shared_grammar()`. Test:
  `test_caption_hands_ffmpeg_the_cues_it_read`.
- **`--mode mux` keeps every existing subtitle track, converted where the container needs it.**
  The rule is export.py's (#380), now `_common.runner.subtitle_codec_for()`, plus WebVTT for
  `.webm`; an EIA-608 track converts as text does (kept as it is in `.mov`, which holds c608). A track no conversion fits (a bitmap track in MPEG-4 or WebM) and a WebM mux of a
  picture or sound WebM cannot hold are refused up front as `kind: input`; a mux never drops a
  track the caller did not ask to drop. Test:
  `test_caption_mux_converts_an_existing_track_for_the_container`.
- **An explicit `--font` on Windows is looked up in the family table first**
  (`WINDOWS_FONTS` and `WINDOWS_LATIN_FONTS`), then by file-name prefix: Windows installs most
  families under file names that do not start with the family's name. Code:
  `fonts.windows_family_files()`. Test: `WindowsFamilyResolutionTests`.

## 3.1.8 — earlier fixes, where they had not reached (#415)

- **A file a child tool of this run wrote is this run's own.** render.py's export stage is a child
  process, so the delivery it wrote was not in render's `STATE.written`, and the chapters stage's
  `place_output()` over it was refused as `output_exists`, after a dry run that said completed (the
  test helper adds `--overwrite` to every render.py call, which hid it). render.py now records each
  stage's output (`remember_written()`), as run() records its own ffmpeg outputs. Code:
  `render.sh()`, `_common.runner.remember_written()`. Test:
  `Issue415Tests.test_render_export_then_chapters_delivers_on_a_fresh_path_without_overwrite`.
- **metadata.py writes an MPEG-4 file faststart.** #279 left the stream copy without `+faststart`
  on the reasoning that adding it would move the moov atom. That does not hold: a stream copy into
  the MPEG-4 family writes the index after the media unless told otherwise, so the copy moved the
  index of a faststart input (render's export, then its chapters stage) to the end. Now every MP4
  write is faststart. Code: `metadata.main()`. Test: `Issue415Tests.test_metadata_writes_a_faststart_mp4`.
- **A `.webm` source's default output name is `.mp4`.** The re-encoding tools write x264/x265/AV1
  video and AAC sound, which WebM does not take, so `clip_loudnorm.webm` failed in the muxer after a
  dry run that said completed. Of the two consistent answers (an `.mp4` default, or VP9/Opus encodes
  for a WebM target), the default name is one line in `default_output()` and changes no encoder. A
  caller who names `-o x.webm` got the muxer's refusal, which came only after the encode had
  started, as `kind: ffmpeg` with "Nothing was written into output file", and a dry run said
  completed (#488: every re-encoding tool, swept). Since #488 such a command is refused before
  anything runs, dry runs included (`kind: input`, reason `output_container_codecs`, the encoders
  named in `details`), by the one check every ffmpeg command passes (`runner._check_container_codecs`);
  the encoders are still not switched to VP9/Opus for a WebM name. A stream copy is still left to
  the muxer, since what it copies is not in the command. metadata.py and `export.py --preset
  copy`, stream copies, keep the source's extension. Code: `_common.decision.default_output()`, `NO_DEFAULT_ENCODE_EXT`. Tests:
  `Issue415Tests.test_a_webm_source_gets_an_mp4_default_output_that_the_run_writes`,
  `test_a_webm_output_of_an_h264_encode_is_refused_before_ffmpeg_runs`.
- **`waveform.py --title/--srt/--text --dry-run` says its text sizes are placeholders.** The title
  and captions are drawn by graphics.py and caption.py on the visualisation render, which a dry run
  does not write, so their planned font size and motion offset are 0 (the real run's are measured
  from the WxH render). A note says so; a plan does not invent the numbers. Code: `waveform.main()`.
  Test: `Issue415Tests.test_waveform_title_dry_run_says_its_planned_sizes_are_placeholders`.
- **batch.py: an item's intermediates live in a directory of its own and go with it.** The step
  files were `<work>/<stem>_step<i>.<ext>` and never removed, so `clip.mp4` and `clip.mov` in one
  serial batch refused each other's, and any later run that processed an item again was refused on
  the file an earlier run left. Each item now gets a new directory under the work directory
  (`<index>-<random>`, holding `step<i>.<ext>`; serial and `--jobs` alike; 1.17's flat serial layout is gone),
  removed with its contents when the item ends however it ends. Code: `batch.main()`
  `item_work()`/`run_item()`. Tests: `Issue415Tests.test_batch_items_own_their_intermediates`,
  `Issue415Tests.test_batch_a_stem_near_the_name_limit_still_runs` (no stem in either name, so a
  stem whose input and output names fit in 255 bytes fits here too).
- **batch.py: a step without `{out}` passes its input on, and the last file written is
  delivered.** A recipe ending in `check.py` marked the item `ok` with an output nothing wrote; its
  cache entry then missed (`output_missing`) on every run. A step that names no `{out}` writes
  nothing, so the next step reads what it read, and when the last step writes nothing the last
  written file is moved to the item's output (under the same `--overwrite` rule). A recipe in which
  no step names `{out}` (a QC pass: `check.py` or `probe.py` over a folder) is a legitimate batch
  that writes nothing: its rows carry `written: false` (`output` stays the final-path string: a
  `--json` key never changes type within a major), a note says so, `ok` follows the steps' exit
  codes, its cache entries claim no file (so a rerun is served, not missed as `output_missing`),
  and the final-name collision check does not apply. The delivered intermediate keeps its own
  extension (`.mp4` for a video source) unless the recipe sets `ext`: a `.webm` source's `fit.py`
  step writes MP4, which named `clip_out.webm` would be mislabelled. The move into place holds the
  output lock every tool's write holds, and a move across filesystems copies beside the final path
  and renames, so a failed copy never truncates the file it replaces. A `--dry-run` refuses an
  existing final path there as the real run would, and `check.py --dry-run` on a file an earlier
  dry-run step would write grades nothing (`checks: []`, a note) instead of dividing by its 0 height. Code: `batch.step_writes()`,
  `batch.writes_nothing()`, `batch.deliver()`, `batch.cached_output_changed()`. Tests:
  `Issue415Tests.test_batch_delivers_the_last_written_file_when_the_last_step_writes_none`,
  `Issue415Tests.test_batch_a_recipe_that_writes_nothing_reports_no_output`,
  `Issue415Tests.test_batch_a_delivered_intermediate_keeps_its_container_extension`,
  `Issue415Tests.test_batch_delivery_holds_the_output_lock`,
  `Issue415Tests.test_batch_delivery_across_filesystems_never_truncates_the_output`,
  `Issue415Tests.test_batch_dry_run_refuses_an_existing_output_a_read_only_last_step_would_deliver_to`.
- **batch.py's final-name collision check ignores case.** `Clip_out.mp4` and `clip_out.mp4` are
  one file on macOS's and Windows' default filesystems; the check refuses them on every platform,
  so a recipe that works on Linux does not overwrite an item on a Mac. Test:
  `Issue415Tests.test_batch_final_names_that_differ_only_in_case_collide`.
- **No fallback retries after a classified ffmpeg failure.** #389 stopped
  `run_keeping_subtitles()` from encoding again after a full disk, a missing encoder or filter or an
  unreadable input; export's own subtitle/data ladder, `color.py --retag`'s copy-then-re-encode
  (and its keep-then-drop re-encode), `cut.py`'s copy-then-re-encode and copy-concat-then-re-cut and
  `sync.py`'s copy paths still did, blaming the subtitles or the copy. They now stop with the first
  attempt's error (`fail_if_classified()`). Code: `_common.runner.fail_if_classified()`. Test:
  `Issue415Tests.test_a_classified_failure_is_not_retried_by_a_copy_or_stream_fallback`.
- **A stop after the deliverable is written says the file is kept, and keeps the child's exit
  code.** export.py `--normalize` and render.py's chapters and check stages run on a delivery
  already on disk; a timeout or Ctrl-C there said "nothing was written" while the file stayed (and
  a retry was refused as `output_exists`). The message now names the file, says it is kept without
  the step that was stopped, and the document carries it as `output`; the file is kept rather than
  removed because with `--overwrite` it has already replaced the caller's. export.py's
  `--normalize` failure exits with the loudness child's code (124, 130/143), as render.py and
  waveform.py already did. export.py counts its file delivered as soon as it is written, so a stop
  in the reads after the write (the output probe, the loudness measurement) says the same. render.py
  passes a stopped child's code on from an executed plan and from a pack destination too (the pack
  is then `kind: timeout`, not `verification`), and an export stage stopped in `--normalize` hands
  the delivery it kept to render's `output`. A child killed by a signal (returncode -9) is passed
  on as 128 + the signal (137), not as a wrapped 247 (`child_exit_code()`). Code: `_common.runner.mark_delivered()`, `kept_clause()`,
  `export.main()`, `render.sh()`/`main()`/`execute_plan()`/`render_pack()`. Tests:
  `Issue415Tests.test_export_normalize_timeout_keeps_its_exit_code_and_says_the_export_is_kept`,
  `Issue415Tests.test_export_a_stopped_read_after_the_write_says_the_export_is_kept`,
  `Issue415Tests.test_render_passes_a_stopped_childs_exit_code_and_kept_output_on`,
  `Issue415Tests.test_a_child_killed_by_a_signal_passes_on_128_plus_the_signal`,
  `Issue415Tests.test_a_stopped_run_names_the_deliverable_it_keeps`.
- **An ffprobe call is limited to `min(120 s, --timeout)`.** `_limit_for()` gave every probe through
  `run()` a fixed 120 s whatever `--timeout` said (the encoder-list read already took the lower
  one), and the version reads 120 s too; with `--timeout 2` a hung ffprobe held the tool for two
  minutes. `--timeout 0` leaves the probes through `run()` unlimited, as before; the version,
  stream-list and encoder/filter-list reads outside it keep 120 s (`_probe_limit()`). A probe that reaches
  its own 120 s ceiling no longer advises raising `--timeout`, which cannot raise it. Code:
  `_common.runner._limit_for()`, `_probe_limit()`, `_timed_out()`. Test:
  `Issue415Tests.test_ffprobe_through_run_is_bounded_by_a_lower_timeout`.

## After 3.1.8 — delivery masters (#417–#423, review of #430)

- **The alpha presets stay on the CPU under `--hw`.** VideoToolbox's ProRes line is 422 HQ: moved
  there, `prores4444`/`prores4444xq` wrote an opaque file and the `codec` step was skipped as "a
  VideoToolbox line". They keep `prores_ks` and a note says `--hw` did not move them; `key-fill`
  (one ffmpeg run writing both files) does the same. Code: `export.main()`, `export._key_fill()`.
  Test: `HwEverywhereTests.test_export_alpha_presets_stay_on_prores_ks_under_hw_and_a_dry_run_decodes_nothing`.
- **Alpha is compared over every frame, not the first.** A graphic that opens fully opaque read 255
  in the source and in a file that lost its alpha, so the check passed either way. The source and
  the written file are each decoded once to a 64x36 copy and compared frame by frame, each within
  2 of 255 (an aggregate let a loss in a few frames through: one of 200 frames turned opaque moves
  the mean by ~1). Where the frame counts differ (a variable-rate source conformed to a constant
  rate), indices do not pair, so the mean and the most transparent frame are compared and
  `comparison.paired` is false. A dry run decodes nothing: it decides from the pixel format and a VP9
  stream's `alpha_mode` tag. A VP9 source is decoded with libvpx-vp9 (the native decoder drops the
  alpha layer). Code: `export.alpha_stats()`, `vp9_decoder_args()`, `vp9_alpha_tagged()`. Tests:
  `test_export_alpha_review_430`, the test above.
- **`key-fill` writes the picture and the sound only, and reports the rest.** A fill and a key go to
  a switcher's keyer as a pair; a subtitle or data track has no place there, so the source's are
  listed in `non_av_streams.dropped` with `reason: key_fill` (as a GIF's are) rather than mapped.
  Both files are guarded as outputs (the fill is not ffmpeg's last argument, which `run()` guards)
  and the fill is written through a temp file, moved into place only after the encode succeeds
  (a failed encode leaves no partial fill, new or replaced). Code: `export._key_fill()`. Tests:
  `test_export_key_fill_review_430`, `test_export_key_fill_failure_removes_only_a_fill_it_created`.
- **A `--plan` path may not be any file a planned command writes**, not only `output`: `loudness.py
  --versions` has no single output, and a plan over a version file was refused as an existing output
  when it was executed. Code: `_common.emit.write_plan()`, `_planned_outputs()`. Test:
  `test_loudness_versions_writes_one_measured_file_per_target`.

## After 3.2.1 — broadcast legal levels, measured

- **The out-of-range share is counted, not estimated from a histogram.** `check.py --levels` sends
  each plane through `lutyuv` as a mask (an out-of-range code becomes the depth's top code, every
  other code 0) and reads the mask's mean with `signalstats`: that mean over the top code is the
  plane's out-of-range share in that frame, exact to the sample. signalstats' own BRNG is reported
  beside it (`brng_pct`) but does not decide the row: its limits are fixed at the nominal range, it
  counts pixels with any component out (luma and chroma cannot be told apart), and it cannot take
  EBU R 103's wider tolerance. The mask's value is a literal, not lutyuv's `maxval` (235 for limited-
  range luma, 240 for chroma), which would scale every share down. Code: `_common.probe.measure_signal_range()`.
  Test: `test_check_levels_counts_out_of_range_samples_exactly`.
- **Each standard is stated in percent of the nominal swing; the codes follow from the bit depth.**
  `bt709` is 0..100 % luma and the nominal chroma swing (16-235 / 16-240 at 8 bits, 64-940 / 64-960
  at 10). `ebu-r103` is the R 103 tolerance, luma -1 %..103 % (14-241 at 8 bits, 56-966 at 10), and
  chroma as far as an RGB triple inside R 103's -5 %..105 % can reach (|C| <= 0.55 of the span, 5-251).
  A limit between two codes rounds inward. This counts Y'CbCr codes: an RGB gamut error made of
  legal Y'CbCr codes is not counted, and the reference says so. Code: `_common.probe.LEGAL_RANGES`,
  `legal_limits()`. Test: `test_check_levels_scales_the_limits_with_the_bit_depth`.
- **The row judges the worst frame, not the clip average.** One frame with a clipped sky is a QC
  failure even in an hour that is otherwise legal, so the row FAILs when any frame has more than
  `--levels-tolerance` (1 %) of its luma or of its chroma samples out; the allowance is room for a
  filter's overshoot at a sharp edge. The clip share, the per-window shares and the worst frame's
  time are all in `levels`. It is a `format` row (the fix is mechanical: `color.py --legalize`), so
  it FAILs without a named platform too: the caller asked for it. Code: `check.levels_row()`.
- **An RGB or grey picture is not measured, and a full-range file is measured with a note.** Neither
  has the limited-range Y'CbCr codes a broadcast file carries; converting one here would measure the
  conversion. Test: `test_check_levels_is_opt_in_and_skips_a_picture_with_no_luma`.
- **The limits follow the depth of the planes, and a partial measurement is no measurement.** The
  depth comes from ffmpeg's pixel-format table (`component_depth()`), not from the format's name:
  `nv12` is 8-bit (its 12 is bits per pixel), and read as 12-bit every legal sample counted out. A
  run that exits non-zero, or whose two passes counted different frames, returns nothing and the
  row says `could not measure`: the frames read before a failure are not the file. Tests:
  `test_check_levels_reads_the_depth_of_the_planes_not_of_the_name`,
  `test_check_levels_is_not_measured_when_the_decode_fails_part_way` (#432 review).
- **`color.py --legalize` clamps after the 4:2:0 conversion, and measures instead of promising.** The
  clamp is the last filter before the encoder, on the 8-bit 4:2:0 picture it encodes: a clamp
  ahead of the subsampling lets the chroma filter's overshoot put samples back out. A lossy encoder
  can still move a decoded sample a code or more past a hard-clamped edge (the test pattern at CRF
  18 kept 4 % of one frame's luma out), so the written file is measured with the same counter: the
  `legal_levels` step holds it to the same 1 % per frame and `legalize_residual` reports any
  residue. Encoded losslessly (`--quality 0`) the residue is zero. `--codec` other than h264 is
  refused because the encoder line would convert the clamped picture again (10-bit, 4:2:2), and
  `--retag` / `--strip-dovi` because they copy the stream. A full-range source (tagged `pc`, or
  yuvj420p) is scaled to limited range (`scale=out_range=tv`) ahead of the 4:2:0 conversion, so its
  blacks and whites move into the limits instead of being cut at them; a limited-range source's
  chain is unchanged (#432 review; test
  `test_color_legalize_converts_a_full_range_picture_before_the_clamp`). Code: `color.legal_clamp()`,
  `color.legalize_report()`. Test:
  `test_color_legalize_clamps_after_the_420_conversion_and_measures_the_file`.
- **`--legalize` with `--keep-alpha` is refused; with `--drop-alpha` it runs.** The clamp and its
  measurement are defined on the 8-bit 4:2:0 picture the H.264 line encodes. An alpha line grades
  at 4:4:4 and every `--alpha-codec` converts the clamped picture again (ProRes 4444 to 10-bit,
  qtrle/PNG to RGB, VP9 to yuva420p), which is the reason `--codec` other than h264 is refused, so
  the combination is refused the same way (`kind: input`, before ffmpeg runs). An alpha master is an
  editing master, not the broadcast delivery: legalize the opaque delivery (`--drop-alpha`), or
  measure the master with `check.py --levels`. Code: `color.main()`. Test:
  `test_color_legalize_with_an_alpha_line_is_refused_and_runs_on_the_opaque_line` (#432 with #433).

## After 3.2.2 — the alpha path beyond export (#433)

Context: `export.py`'s alpha presets kept and checked an alpha channel, but every tool that grades
or composites wrote opaque H.264 and still said `verified: true` on a ProRes 4444 source whose alpha
it had dropped, and nothing could make a transparent canvas to draw one graphic on. Decisions:

- **An alpha line is asked for, never inferred.** `--keep-alpha` (`color.py --correct/--lut`,
  `graphics.py`, `overlay.py`) and `background.py --transparent` write ProRes 4444 by default
  (`--alpha-codec qtrle|png|vp9`); without the flag the tools write the same H.264 line as before.
  Switching an alpha source to ProRes on its own would change the codec, container and size of an
  existing call's output, which is not an additive change. A container that cannot hold the line
  (`.mp4` for ProRes, `.mov` for VP9) is refused before anything runs. Code: `_common/alpha.py`
  `check_alpha_args()`. Test: `test_color_on_an_alpha_source_without_keep_alpha_is_not_verified`.
- **A lost alpha fails verification instead of passing.** The one change to a call without the new
  flags: on a source that stores an alpha plane and uses it (a frame below opaque), a re-encode that
  writes no alpha adds an `alpha` step with `ok: false` (`reason: alpha_dropped`, `attribution:
  artifact`) and an `alpha_dropped` warning, so `verified` is false. The run still completes and
  writes its file; `--drop-alpha` records that an opaque output was wanted and adds no failing step.
  An opaque source is not decoded for this and reports exactly as before (the check needs the pixel
  format, or a VP9 stream's `alpha_mode` tag, to show an alpha plane first). Code: `alpha.report()`,
  `alpha.lost_step()`. Test: as above.
- **The alpha line keeps the source's colour tags, as `--codec prores` does.** An alpha master is an
  editing master: it converts no matrix and draws no BT.709 label, so `decision.keeps_source_tags()`
  is true for both. A grade's RGB legs (and an RGB layer's conversion) leave the frames untagged
  (6.1) or relabelled (7.1+), so the source's tags are put back on the frames with `setparams` at
  the end of the chain and named on the stream; with the frames already carrying them, 7.1+'s
  output-option negotiation has nothing to convert. Code: `decision.keeps_source_tags()`,
  `alpha.finish_chain()`, `alpha.tag_args()`. Test:
  `test_color_keep_alpha_grades_a_prores_4444_clip_and_keeps_its_alpha`.
- **An RGB source that is neither HDR nor BT.2020 is converted to BT.709 on a YUV alpha line and tagged so (#496).** "It converts
  no matrix" above holds for a YUV source, which has one to keep. An SDR RGB source (qtrle, PNG in
  `.mov`/`.mkv`; one that probes HDR or BT.2020 is not converted to BT.709: FFmpeg's own conversion makes its YUV, as before) has none, and ProRes 4444 and VP9 store YUV, so one conversion is made whatever
  the tool does. Left to FFmpeg it was BT.601, with no tag on 6.1: a 1280x720 master read as
  BT.709 showed 30C050 as 26AB4D, from `color.py --correct`, `graphics.py` and `overlay.py` alike
  (`--lut` wrote BT.709 samples with no tag). The conversion is now BT.709, RGB layers are
  converted to match, and the line is tagged BT.709 (matrix always; primaries and transfer the
  source's own when it has them), as the H.264 line treats an RGB source. `color.py` makes it in
  the grade's own way out of RGB, not in a conversion in front of it, so the grade of an RGB source
  is the same on every `--alpha-codec`. A qtrle/PNG line keeps the RGB (through the 4:4:4 YUV the
  tools work in, both ways with one matrix). An untagged YUV source is unchanged on every line: its
  samples are kept, and an RGB line reads them as FFmpeg's default, BT.601. Code:
  `alpha.rgb_to_bt709_line()`, `alpha.source_format()`, `color.py working_matrix()`. Test:
  `test_an_alpha_line_shows_the_colour_of_its_source`.
- **A conversion the alpha line makes names its matrix where FFmpeg 6.1 would not read the tag
  (#496's siblings).** Three more places took BT.601 on a BT.709-tagged source. `color.py` to a
  qtrle/PNG line: FFmpeg puts the conversion to RGB in front of `alphamerge`, ahead of
  `finish_chain()`'s label, so the graded YUV is labelled at the end of the colour branch too
  (`alpha.matrix_label()`; 30C050 came out 3CD753). `--alpha-mode premultiplied` on a ProRes
  4444/VP9 line: the way to RGB and back around `premultiply` name the line's matrix (opaque
  30C050 came out 3CD753 from `color.py`, 25AC4E from `overlay.py`). An RGB `overlay.py --video`
  layer with `--keep-alpha`: `matrix_chain()` converts nothing on an alpha line, so the layer
  became YUV by the default (pure red read FF1800); on a BT.709 line it is converted to BT.709,
  as an `--image` layer already was. With `--chromakey` the layer is keyed as BT.601 YUV first
  (the filter computes its key in BT.601 whatever the frames say) and converted after the key. Test: as above.
- **An RGB source's `gbr` colour space is not carried over (#454).** It says the stored samples are
  RGB, which is the pixel format's to say: the PNG line tags itself `gbr`, and on a YUV line
  (ProRes 4444, VP9) the label would call YUV samples RGB. So the output of a PNG-in-`.mov` source is
  tagged like that of an untagged qtrle source of the same pixels, and graded the same. Every probed
  tag passed back to FFmpeg goes through `_common/color.carried_tag()`, because the output options
  parse an older table than the one ffprobe prints: `-colorspace` refuses `gbr`, `-color_trc`
  refuses `bt470m`/`bt470bg` (it says `gamma22`/`gamma28`); setparams takes ffprobe's names. Tests:
  `test_color_keep_alpha_grades_an_rgb_source_tagged_gbr`,
  `test_every_probed_colour_tag_is_spelled_the_way_its_destination_takes_it`.
- **`color.py` never grades the alpha.** The alpha is split off the source and merged back
  (`alphamerge`) after the grade, which runs at 4:4:4 (8-bit: the grade filters' own depth). The
  merge is onto that 8-bit picture, so the alpha is written with 8 bits of precision whatever the
  output line stores: an 8-bit alpha (qtrle, PNG) comes back unchanged, while a 10- or 12-bit one
  (ProRes 4444) loses its low bits (#463 A155, measured on FFmpeg 6.1.1: a ProRes 4444 source of
  alpha 513 of 1023, decoded `yuva444p12le`, was written as 514 to 519 of 1023, two 8-bit steps
  dithered). The written alpha is compared with the source's frame by frame (tolerance 2 of 255),
  exactly as export's alpha presets are. Code: `color.main()`. Test: as above.
- **Compositing is checked against a floor, not an equality.** A layer drawn on the picture adds
  coverage, so the written alpha cannot equal the source's: `graphics.py`/`overlay.py` pass when the
  stream stores an alpha plane, no frame's alpha is below the source's, and the output did not turn
  opaque in every frame the source was transparent in (what a dropped alpha reads as). A layer that
  covers the whole frame for the whole clip fails `opaque_everywhere`: there is no alpha left to
  keep, and the step says so rather than guessing that was intended. Boxes are composited as layers
  (`overlay` blends the alpha; `drawbox` leaves it as it was), libass gets `alpha=1`. Code:
  `alpha.kept_step()`. Test: `test_graphics_and_overlay_render_on_a_transparent_canvas`.
- **An `overlay.py --video` layer with alpha keeps it**, with or without `--keep-alpha`: a VP9 layer
  is decoded with libvpx-vp9 (FFmpeg's own VP9 decoder drops the alpha layer), and an RGB layer
  (qtrle, PNG in .mov) is converted to BT.709 YUV in `yuva444p`, not `yuv444p`. Both covered the
  picture as an opaque rectangle. This changes the picture of an existing call, and only where the
  old one was wrong. Code: `overlay.main()`, `alpha.decoder_args_for()`. Test:
  `test_overlay_keeps_a_video_layers_alpha`.
- **What cannot be read is not taken as opaque.** A source that stores an alpha plane (or a
  palette, which can hold transparency the pixel format does not show) and whose alpha cannot be
  measured counts as using it, so an output without alpha fails; a VP9 source or layer with alpha
  on a build with no libvpx-vp9 decoder is refused (`decoder_missing`, read from `ffmpeg -decoders`,
  not the encoder list) rather than composited opaque. A decoder list that cannot be read is
  unknown, not missing, as for filters: libvpx-vp9 is still asked for and ffmpeg says whether it
  exists. `export.py`'s alpha presets take the same guard before they measure the source: with
  only FFmpeg's own decoder a VP9 alpha source and its written line both read opaque, and the step
  passed with the transparency gone. `doctor` reports `decoder:libvpx-vp9` from the same list
  (`test_doctor_resolves_the_declared_decoder_capability`). The measurement is read frame by frame from
  the pipe (an hour at 30 fps was ~250 MB held at once). A planned input a dry run cannot probe yet
  is not refused as opaque (its window is given: a clip of unknown length has no end to default
  `--end` to). `color.py --retag`'s fallback re-encode gets the same `alpha` step. Code:
  `alpha.source_alpha()`, `alpha.frame_means()`. Test:
  `test_alpha_checks_do_not_pass_what_they_could_not_read`.
- **On a BT.709-tagged alpha line, RGB layers are converted to BT.709.** The line keeps the source's
  tags, and FFmpeg 6.1 turns an RGB logo or box into YUV with BT.601, so saturated colours shifted
  under the kept tag. The YUV line of an RGB source that is neither HDR nor BT.2020 is BT.709 as well (#496) and converts its layers the
  same way. Drawn text colours (drawtext, libass) are not converted on an alpha line.
  Code: `decision.rgb_chain_to_bt709()`. Test: `test_graphics_and_overlay_render_on_a_transparent_canvas`.
- **`--alpha-mode` describes the written colour, as in `export.py`.** Sources are taken as straight;
  `premultiplied` multiplies the written colour by the alpha at the end of the graph.

## After 3.2.1 — a smart cut that re-encodes only the partial GOPs

- **Only H.264 that libx264 here can reproduce is cut smart; everything else falls back, saying why.**
  A re-encoded part and the copied GOPs are decoded as one stream, so the part has to have the
  source's parameters: profile (Baseline/Main/High), level, 8-bit 4:2:0, frame size, SAR, colour tags.
  It also has to have the source's reorder depth (`has_b_frames`). Each part's decode times run
  ahead of its presentation times by that depth, so parts of different depth would collide in
  decode order at a join. The x264 line sets `bframes`/`b-pyramid` to give the same depth, and
  every part is probed against the source. HEVC, 10-bit, 4:2:2/4:4:4, interlaced, variable-rate
  and HDR sources are not matched. Neither is an open GOP at a copy boundary, whose leading frames
  decode after the keyframe. These are re-encoded in full, as `--accurate` would, with `smart.reason`
  and a `reason_code`; they are not refused, because the caller asked for a cut. Code:
  `_smartcut.ineligible()`, `x264_line()`, `plan_segment()`.
- **The parts travel as MPEG-TS, so the parameter sets switch in-band.** An MP4 or Matroska part
  carries one SPS/PPS out of band, and a concat of the encoder's part and the source's packets would
  decode one of them with the other's. In MPEG-TS every keyframe carries its own, and the output
  keeps them in-band. The delimiter NAL units the TS muxer adds are removed again (`filter_units`). The
  output's MP4 time scale is set to the source's time base (`-video_track_timescale`); a Matroska
  output has Matroska's own 1/1000 and is checked against that (#462 A45, below).
- **Verified against the source, not trusted.** Each check below would catch a different way the
  join can go wrong:
  - a frame dropped or repeated at a join (the count and the frame grid);
  - a copy that started or stopped on the wrong packet (packet MD5s against the source's, with
    SPS/PPS/AUD removed on both sides);
  - a decoder that used the wrong parameter set after a join (framemd5 of each re-encoded part as
    written, and of the first 300 frames of each copied part from the source, against the output).
    The cap (`DECODE_CHECK_MAX_FRAMES`) is there because a wrong parameter set shows from the first
    frame after the join, and a long copied part (several GOPs, or one 10-second GOP) would
    otherwise cost a decode of its own.
    Both sides must hold all the frames asked for; two equally short lists are not a match.

  A failed check is a fallback, never a warning on a written file: the smart result is written
  beside the output and moved into place only once it passes.
- **The sound is cut from the source and encoded once.** A packet copy of AAC lands on 21 ms
  packet boundaries and carries encoder priming into every join. The sound is trimmed on the
  picture's frame grid, as the `--accurate` re-cut does, and encoded in the same command that joins
  the picture. The saving is in the video, which is where the time and the quality go. Each
  segment's sound is padded to its picture's length, so a track that ends early cannot pull the
  next segment's sound forward. A segment whose picture starts more than a frame after it (video
  that starts after its sound) falls back (`av_offset`): trimming the sound on the picture's grid
  would drop the sound before the picture, which the full re-encode keeps.
- **`--fps` stays a number in this change.** `join.py --fps 30000/1001` needs `--fps` to take a
  rational, but the MCP schema publishes `--fps` as `number`, and a rational needs it to become a
  string or a union, which the contract's type set does not allow. That is a contract decision for
  its own change; a float `--fps` is unchanged.

Tests: `SmartCutTests` in `tests/test_cut_copy.py`.

## After 3.2.3 — what the output lost from its source is said (#401)

- **`source_carry` is a report in `emit()`, not a per-tool fix and not a check.** #401 listed a
  dozen tools that drop a subtitle track, chapters, a cover picture, `creation_time`, a language
  tag or surround channels and still say `verified: true` with no note. Fixing each drop is
  per-tool work with its own decisions (a retimed cut cannot copy cues as they are). The shared
  part is that the loss must be *said*, so `emit()` compares the first input's items with the
  written file's, whichever tool, encoder or FFmpeg version dropped them. It does not touch
  `verified`: several drops are deliberate and documented (the entry "Subtitle/data tracks are
  kept where the picture's timeline is untouched and dropped where it is retimed"), and a check
  that fails on a decision would train callers to ignore it.
- **Content raises a warning; tags are only listed.** A lost subtitle track, chapter list, cover
  picture or surround layout records `source_items_dropped`. `creation_time`, the audio language
  and the start timecode are listed under `dropped` without a warning: every camera file carries a
  `creation_time` and FFmpeg drops it on any write that does not ask for `-map_metadata`, so the
  warning would fire on every real run and stop being read.
- **Not said twice.** Where the tool already reports the subtitle loss (`dropped_non_av_streams:
  true`, the `non_av_streams_dropped` fallback), `subtitles` is under `dropped` but adds no warning.
- **Absent for a source with none of the items**, so every result document for a plain source is
  what it was. Stereo and mono are not an item: `audio_channels` is compared for a surround
  source only.
- **Not compared:** two or more inputs with a picture or sound (which one's items the output
  should carry is the tool's choice; a tool's own output read back as an input, as `cut.py` does,
  is not a second source), a still or GIF output, a dry run, and an item bound to a stream the
  output does not have (a sound-only extract has no subtitle track or timecode to lose).
- **A chapter list kept but not retimed counts as kept.** The comparison is a count; whether the
  chapters still point at the right moments is a later, per-tool measurement.
- **A start timecode is compared by its value, and moves with the start of the picture.** FFmpeg
  copies the video stream's `timecode` tag and the MOV/MP4 muxer rebuilds a tmcd track from it, so
  a cut from 1 s was stamped with the source's 01:00:00:00 on frame 30 and listed as kept. A tool
  that starts the output on a later frame writes that frame's label (drop-frame where the source
  is): a single-range `cut` (its first frame at or after `--start` for a re-encode or an
  edit-listed copy, the keyframe for a copy that shows its pre-roll), `fit --method trim`,
  `sync --trim-second` (a padded head counts back before the source's start) and so a
  `render.py` clip with an `in`. A join of several ranges writes none: a timecode counts on from
  its first frame, so after the first join every label would name the wrong source frame, and a
  conform by timecode would land there. A stream copy out of MXF writes none either: its demuxer
  lands a seek on another keyframe than `cut.seek_keyframe` reads. `source_carry` then lists the
  timecode as dropped (an MXF, which always writes one, reads 00:00:00:00). The label is read at
  the source's rate and written at the rate the output is delivered at (`fit --fps`, a VFR source
  conformed): 01:00:00:12 at 25 fps is 01:00:00:24 at 50, and a fit that changes the rate writes
  it even without a trim, leaving the source's tmcd track behind. A start before a picture that
  starts after the file's origin is that picture's first frame; only a padded head counts back.
  Code: `_common.timeline.output_timecode_args()`, `cut.first_frame_from()`. Tests:
  `test_a_tool_that_moves_the_start_moves_the_start_timecode`,
  `test_the_start_timecode_is_counted_at_the_rate_fit_delivers`,
  `test_a_cut_before_a_late_picture_keeps_the_start_timecode_of_its_first_frame`.
  Code: `_common.emit.source_carry()`, `_common.probe.carry_inventory()`. Test:
  `test_source_carry_says_what_the_output_lost_from_its_source`.

## After 3.2.3 — two reports from outside (#436, #437)

- **A `force_style` Alignment is the legacy SSA number, a Style line's is the numpad one.**
  `caption.py` keeps two tables: `ALIGN` for the ASS file it writes (`--text`, `--transcribe`,
  karaoke) and `FORCE_STYLE_ALIGN` for the SRT burn. They agree on the bottom row only, which is
  why the default placement hid the bug. Measured on libass 0.17.1 (FFmpeg 6.1.1) and reported on
  FFmpeg 9.0.2. Code: `caption.FORCE_STYLE_ALIGN`. Test:
  `UserReportTests.test_caption_srt_position_lands_where_it_says` (the text's bounding box on the
  burned frame, for all seven positions).
- **An odd-sized BT.601 source is padded to even for its matrix conversion and cropped back to
  its own size, not cropped or scaled.** The `colorspace` filter refuses an odd frame, and it has
  to come first in the graph (it converts the source's own pixels). Padding by one row or column
  and cropping it off again after the conversion loses and resamples nothing (a 4:2:0 frame's
  chroma planes are the same size either way), so a caller's own rectangle (`crop.py --x 1
  --width 628` on a 629-wide source) still addresses the pixels it measured; a first version
  cropped the edge off and shifted such a rectangle. The odd axis is read after the rotation swap
  FFmpeg applies before the graph. `_MATRIX_FILTER_RE` accepts the wrapped form, so the code that
  folds the conversion into a tool's own `-vf` still finds it (without that the command carried
  two `-vf` and the second replaced the tool's graph). Code:
  `_common.color.bt709_matrix_filter()`. Test: `UserReportTests.test_insert_takes_an_odd_sized_jpeg`.

## After 3.2.3 — what a plugin install copies, and what it leaves out

- **The plugin tree is a branch built from the npm tarball, not the repository root.** A plugin
  host copies whatever the marketplace entry points at; at `./` that is every tracked file (28 MB:
  tests, evals, the site, brand files, docs images) for a skill that reads 2.6 MB. Each release
  commits the npm tarball's contents, plus `.claude-plugin/plugin.json` and
  `skills/ffmpeg-skill/SKILL.md`, to the `plugin` branch (`.github/scripts/publish_plugin_branch.sh`,
  run by release.yml before the npm publish). An npm plugin source was measured and rejected:
  Claude Code 2.1.322 and Codex 0.167 both shell out to `npm` for it ("npm exited with an error",
  "npm pack failed" without one), and the plugin route has never needed Node. A git source with
  `ref` installed with git alone in both, but not alike: from the 3.3.0 branch (tree at the root,
  a `url` source) Claude Code cached 2.6 MB and Codex kept the whole clone with every branch's
  history (39 MB, more than the repository's files). So since 3.4.0 the branch holds the tree
  under `ffmpeg-skill/`, for a `git-subdir` source: both hosts then copy that directory alone and
  keep no `.git` (2.6 MB each, measured). The two plugin files stay out of the npm package itself
  because `npx ffmpeg-skill` copies the package into an agent's skills folder, where a second
  `SKILL.md` under `skills/` would be the same skill twice. The marketplace entry moved from `./`
  to that directory after 3.4.0 had published the layout, and after both hosts installed from the
  real branch through it (3.4.0, 2.7 MB each, no `.git`). The marketplace itself is still this
  repository, so `marketplace add` checks it out: 50 MB in Claude Code and 66 MB in Codex, or
  1.1 MB and 2.2 MB with `--sparse .claude-plugin`, which the README's commands use. The one-line
  `/plugin install ... --marketplace` form was not measured. The cost of the move is a floor: by
  Claude Code's changelog a `git-subdir` source exists from 2.1.69, and installs correctly on git
  older than 2.39 only from 2.1.288. Neither older combination was run here; the README names
  both and points older installs at `npx ffmpeg-skill`.
  Test: `test_plugin_branch_tree_is_the_runtime_set`.
- **The plugin tree is the npm tarball minus `bin/`, plus the manifest, the `skills/` copy and
  the icon.** `bin/install.js` is the `npx ffmpeg-skill` installer: it copies the package into a
  skills folder and shells out to `python3` and `ffmpeg -version`. A plugin host does the
  installing, and the Claude plugin directory's checks read the file as an install-time risk
  (three findings on the 3.4.0 branch, plus a notice that `bin/` will later be accepted only from
  verified organisations). So the tree leaves it out and removes `bin` from its `package.json`,
  which the contract still reads for the version. `.claude-plugin/icon.png` is `assets/icon.png`;
  the directory takes the icon once, at the first submission, so it has to be on the branch before
  that. Same test.
- **The plugin does not register the MCP server.** `mcp/server.py` rides along in the plugin tree,
  but no `.mcp.json` or `mcpServers` entry starts it. In a host that runs a plugin (Claude Code,
  Codex, Gemini CLI) the agent has a shell, and the skill reaches all 42 tools through it; the MCP
  server exposes 12 tools whose definitions are 68 KB (about 17,000 tokens) and would be loaded
  into every session of a host that does not defer tool definitions, for a second route to the
  same scripts. The server is for clients without a shell, which do not install plugins: they get
  it from the MCP Registry entry (`server.json`) or the one-line config in the README
  (`npx -y ffmpeg-skill mcp`). Report this as a defect only with a host that runs plugins, has no
  shell, and cannot add an MCP server by its own config.

## After 3.3.0 — a declared change scope for `check.py --compare` (#439)

- **`--expect-changed` takes the scope from the caller and only measures.** The tool does not
  decide what an edit was meant to touch, and it does not align frames: pairs are by decode order,
  as `--compare` has paired them since 2.24. A declared span is closed at both ends and widened to
  whole frames (`between(t,3,5)` draws on the frame at 5.000 s). With a rectangle, the tiles it
  does not touch are still held to "unchanged" in those frames. Code: `check.change_scope()`,
  `_common.probe.change_tiles()`. Tests:
  `test_check_expect_changed_fails_on_a_change_outside_the_declaration`,
  `test_change_scope_is_closed_at_both_ends_and_holds_the_rest_of_a_rectangle_frame`.
- **Rectangles and reported places are in the displayed picture.** Both files go through
  `square_pixels()` before they are subtracted, so the grid covers `display_size()`: rotation
  applied and non-square pixels squared (1440x1080 at 4:3 is 1920x1080). A first version used the
  stored width, which refused a rectangle that fits the picture a viewer sees and picked the wrong
  tiles for one that passed.
- **"Not compared" is FAIL here, where `similarity` says WARN.** Another frame size, another frame
  count, a frame count or frame times that cannot be read, or a pass that failed: the flag exists to
  stop a false "nothing else changed", and a check that did not run would be one. The same
  reasoning as `--expect-identity`. An edit that changes the length therefore fails as not
  compared; declaring a removed span is a later phase, never detection.
- **Tiles, not SSIM.** In the issue's measurements a 200x60 box on 1920x1080 (0.6 % of the frame) leaves every frame's SSIM
  above `COMPARE_SSIM_WARN` on a clean source, and on a noisy one the edited and unedited frames'
  SSIM ranges overlap. The difference of the two pictures as 8-bit RGB, area-scaled to 32x18, with
  a tile's value the largest of its channels, separates them: 72 or more inside the edit against
  16 or less outside, in every case below.
- **The floor is 24, from footage, not 16.** The issue proposed 16 from synthetic pictures and
  asked for it to be set from real ones. The same box, 3 s to 5 s, FFmpeg 6.1.1, libx264:

  | source | settings | edited frames (min-max) | everything else (max) |
  |---|---|---|---|
  | iPhone 4K60 HEVC, scaled to 1080p30 | crf 20 veryfast | 72-128 | 9 |
  | same | crf 23 medium | 73-128 | 11 |
  | same | crf 28 medium | 73-128 | 16 |
  | Android screen recording 720x1600 | crf 20, 23, 28 | 107-109 | 3, 3, 4 |

  "Everything else" is not zero because later frames of a GOP are predicted from the changed ones
  and the rate control looks ahead; it grows with the quantiser and reached 16 at crf 28. A floor
  of 16 would sit on that value; 24 leaves a margin and is a third of the smallest edit measured.
  Two encodes with the same settings and no edit gave 0 everywhere. The row prints the floor and
  the largest tile that stayed under it (`quiet_peak`), so a run close to the floor shows. Two
  sources and one encoder are not a survey: `--change-floor` exists for footage this did not cover.
- **Files that are not encoded alike are a WARN and a note, not a higher floor.** A different
  preset alone moved the largest tile of every frame to 11 on a noisy source (and the mean SSIM to
  0.87) in the issue's measurements: the comparison then measures the encoder. The row compares codec, pixel format and frame
  rate and says so; it cannot see a different CRF or preset, which the docs state.
- **A changed frame is kept as a bit mask of its tiles.** Two unrelated files differ in every tile
  of every frame; as lists of tuples an hour of that is tens of millions of objects, as masks about
  10 MB. The pass streams 1728 bytes a frame and a frame under the floor costs one `max()`.
- **Limits, stated in `references/scripts.md`.** A change much smaller than a tile is diluted (a
  full-contrast change needs about a tenth of a tile); a faint shift over the whole picture stays
  under the floor in every tile, and `similarity` is the row for that; picture only. Measured on
  FFmpeg 6.1.1 locally; the test runs on every FFmpeg in CI.

## After 3.3.0 — non-finite numbers are refused in one place

- **`add_common()` registers `finite_float` for every `type=float`; `parse_time()` refuses a
  non-finite time.** An outside reviewer reported a `nan` or `inf` accepted by one flag at a time on
  nine PRs, and each was fixed where it was found. Run as a class (`nan` and `inf` on every float
  flag of the 25 single-input tools, 232 runs), all 232 were accepted at parse time: argparse's
  `float` reads them. A per-flag check cannot keep up with new flags; argparse looks a `type=` up
  in a per-parser registry at parse time, so one `ap.register("type", float, finite_float)` covers
  the flags a tool added before and after the call. With `--json` the refusal is a failure document
  (`kind: input`), as it was for the flags that checked themselves (`export.py --max-mb nan`);
  without it, argparse's usage error (exit 2), like any other value argparse cannot read. Times are `str` flags read by `parse_time()`, so
  that is the second place, and its refusal is `kind: input` through `time_arg()`. A number inside
  another string was probed in one place only: `speedramp.py --segment 0-1:FACTOR` is range-checked
  by its own parser, which a `nan` already failed; the others were not swept. Code: `_common.runner.finite_float`, `_common.decision.parse_time`. Test:
  `test_no_numeric_flag_of_any_tool_takes_nan_or_inf`, which walks the contract, so a new tool or
  flag is covered without being listed.

## After 3.4.3 — the MCP Registry entry is published by the release, not by hand

- **`release.yml` publishes `server.json` to the MCP Registry after the npm publish.** The entry
  names the npm package, so it can exist only once npm has the version, and the registry refuses
  a version it already lists. The steps therefore ask both registries on every run and publish
  when npm has the version and the registry does not: they do not depend on "was a tag created
  in this run", which is what lets a re-run finish a failed publish. The re-run checks out the tip of `main`, so
  it lists the version that is current then; a failed version that `main` has since moved past is
  not listed, and the registry's newest entry is the one clients read. The registry is asked for
  the exact name and version (`/v0/servers/{name}/versions/{version}`: 200 or 404), not through
  its paginated list, where a version on a later page would read as absent. A registry that
  cannot be asked, or any other status, stops the step, as does any `npm view` failure; neither is
  read as "not listed".
  A version npm answers E404 for also fails the step: by then it is tagged, so it is a release
  that never reached npm, which a re-run would otherwise pass over in silence. Authentication is
  GitHub's OIDC token for this repository, which the registry accepts for a name under
  `io.github.kajisho5/`, so no secret is stored. `mcp-publisher` is a pinned release whose
  Sigstore bundle is verified before the binary runs, as the registry's GitHub Actions guide
  says to; `releases/latest` is not used. The three steps may fail without stopping the job and
  a last step turns it red, the same shape as the plugin branch: a missing registry entry must
  not undo a release. The first run was the merge of the PR that added the steps (#445): it listed 3.4.3, a
  version released before they existed. Test: `test_mcp_registry_manifest_tracks_the_package_version`.

## After 3.6.0 — a fold-down, a tone map and an overlay keep the source's levels and depth

- **`audio.py --downmix` is quieter than its input, by design.** It folds 5.1/7.1 with the
  ITU-R BS.775 weights (centre and every surround at 0.707, LFE dropped) and pan's `<` scales
  each side so its gains sum to 1 over the channels the input has: a front channel alone comes out
  7.7 dB lower on 5.1, 9.9 dB on 7.1, and in-phase channels at full level cannot clip. Through
  3.6.0 pan's `=` summed 2.7× per side (3.2× on 7.1) with the LFE at 0.5, so a loud 5.1 clipped
  (flat factor 20+) while the run said verified. A limiter instead of the scale would change the
  programme's dynamics, and the loudness is `loudness.py`'s job. `--stereo`/`--mono` on more than
  two channels already went through swresample, which normalises the same way (measured on 6.1:
  s16, f32 and AAC sources fold in-phase -6 dBFS channels to -6 dBFS). Code:
  `audio.DOWNMIX_PAN`. Tests: `DownmixLevelTests`.
- **`--to-sdr` linearises at 100 nits per unit and gives `tonemap` the source peak; `--peak` is a
  PQ setting.** FFmpeg's `tonemap` reads linear 1.0 as 100 nits (SDR white) and takes `peak` in
  those units, so the zscale before it uses `npl=100` and the filter gets `peak=--peak/100`: a PQ
  pixel at `--peak` nits and HLG at 100 % land on Y 235. Through 3.6.0 the zscale used
  `npl=--peak`, so a 1000-nit pixel arrived as 1.0 (100 nits to the filter): nothing reached white
  (PQ 1000 nits and HLG 100 % at Y 151, HLG reference white at 91), and raising `--peak` to a
  brighter master's darkened everything. zimg decodes HLG for a 1000-nit display, so an HLG
  picture always peaks at 1000 nits there and `--peak` is not applied to it. `look.py` shows an HDR
  source through the same chain at `--to-sdr`'s defaults (hable, 1000 nits), and a BT.2020 SDR one
  through the gamut conversion only, so the sheet shows what the conversion would give; with
  `--compare`, each picture by its own tags (a BT.709 SDR one gets none). Code:
  `_common/color.py` (`hdr_to_sdr_chain`), `look.display_conversion`. Test:
  `test_to_sdr_takes_the_source_peak_to_sdr_white`,
  `test_look_shows_an_hdr_sheet_at_the_to_sdr_levels`,
  `test_look_compare_converts_each_input_by_its_own_tags`.
- **An overlay onto a picture deeper than 8 bits, on a line that keeps more than 8 bits, runs at
  10 bits.** overlay's default format is 8-bit `yuv420`, `format=auto` picks an 8-bit one as soon
  as a layer is 8-bit, and `drawbox` is 8-bit only on 6.1: through 3.6.0 a cutaway, a redaction,
  a graphics layer or box, an emoji and a PiP took a 10-bit HDR or ProRes picture to 8 bits before
  the 10-bit encoder, and `overlay --image`'s RGBA logo took it through 8-bit RGB (Y 402 / Cb 602
  / Cr 422 came out 400 / 603 / 423, through RGB 399 / 608 / 418). `overlay_format()` names
  `yuv420p10` (`yuv422p10`/`yuv444p10` for those sources) for such a picture, an 8-bit layer is
  widened to meet it (bit depth only, no matrix), and graphics.py draws its boxes as layers there.
  Not changed: an 8-bit main, an SDR H.264 line (its output is 8-bit; a 10-bit SDR source is
  reduced at the encoder as before), the alpha line (its tool picks the format), and the colour of
  an RGB layer on an HDR line, which is still FFmpeg's own conversion ("Not converted ... an HDR
  line" above). `overlay --video --opacity` scales the layer's alpha with `lut` in YUV: the RGB-only
  `colorchannelmixer` it used made FFmpeg composite the whole main picture in RGB, which came back
  BT.601 under the BT.709 tag (#333's defect, on the video path; C03028 read 188/42/35 at opacity 1
  and 199/55/32 at 0.999). Code: `_common/decision.py` (`overlay_format`), `broll`, `redact`,
  `graphics`, `overlay`, `caption`'s emoji. Tests: `test_an_overlay_onto_a_10_bit_main_keeps_its_low_bits`,
  `test_a_pip_with_opacity_leaves_the_main_picture_alone`.

## After 3.6.0 — MCP annotations and argument values (audit A9, A10)

- **Over MCP, `probe`, `check` and `cropdetect` refuse `plan`; the property stays listed.** They
  are annotated `readOnlyHint`, and a client may run a read-only tool without asking; `--plan FILE`
  was the one file they could still write, and with `--overwrite` it replaced any existing file.
  The CLI keeps both flags (every tool gets `--plan`, above). The MCP schema keeps both names,
  because the 3.x promise removes no `inputSchema` property (`mcp_tools.json` pins it), and says in
  their descriptions that `plan` is refused and `overwrite` has no effect
  (`_contract.MCP_READ_ONLY_REFUSED`). The server runs these three with
  `FFMPEG_SKILL_READ_ONLY=1`, which refuses `--plan` after argparse (`read_only_plan_refused`),
  so a raw `argv` cannot write one under any spelling either. Every other tool is
  `destructiveHint: true`: its `overwrite` replaces an existing file, which MCP does not count as
  additive. Code: `_contract.mcp_annotations()`, `_common.apply_common()`. Tests:
  `test_mcp_annotations_match_what_the_schema_lets_a_call_write`,
  `test_mcp_read_only_tools_write_no_plan_in_any_spelling`.
- **A value that starts with `-` is passed as `--flag=value`; others keep `--flag value`.**
  argparse reads a separate token that starts with `-` as an option, so `{"text": "-50%"}` was
  refused and an overlay in a project could not start with a minus. Only those values change
  form, so a call without one records the same argv as before (a plan's `argv`, a `--cache` key);
  a render stage with a negative number (`loudness.lufs`, `audio.gain`) gets a new cache key once.
  Positionals that start with `-` follow `--`, after every option. The joined form needs a long
  flag, so `output` and `loudness.lufs` use `--output` / `--lufs` there. A raw `argv` is passed
  as given: its caller chose the tokens. Code: `_common.option_args()`, `mcp/server.build_argv()`,
  render.py's stage commands. Tests: `test_mcp_value_starting_with_a_dash_is_a_value_for_every_tool`,
  `test_dash_leading_text_over_mcp_and_in_a_render_project`.

## After 3.6.3 — a tagged version npm never got is finished by dispatch, on its tag (#448)

- **`release.yml`'s `recover` job refuses a run whose commit is not the tag's.** It is dispatched
  with `--ref vX.Y.Z` and checks out `refs/tags/vX.Y.Z`; dispatched on `main` it publishes only
  while `main`'s tip is still the tagged commit. npm's provenance attestation names the run's
  commit (`GITHUB_SHA`) as the package's source, so a package built from the tag in a run on
  another commit would carry an attestation for a commit it was not built from. The cost is that
  a tag cut before the job existed (every tag up to v3.6.3) has no dispatch trigger at its own
  commit and cannot be recovered by CI. The job lives in `release.yml`, not a workflow file of its
  own, so it shares the `release` concurrency group and the workflow filename an npm trusted
  publisher would name; the publish authenticates as the `release` job's does (`NPM_TOKEN`, with
  `--provenance`).
- **A recovered version below one npm has is published as `backport`; the plugin branch takes it
  only when the branch's tip is older, and the MCP Registry only when it goes out as `latest`.**
  `latest` is what `npx ffmpeg-skill` installs, so it never moves back; the plugin branch only
  moves forward and hosts read its tip; the registry's newest entry is the one clients read. A second dispatch stops at "npm already has
  it", so a plugin branch or registry step that failed during a recovery is finished by hand, as
  the job's last steps say. Code: `.github/scripts/recover_release.py`. Test:
  `test_release_recovery_publishes_only_a_tagged_version_npm_lacks`.

## After 3.7.0 — a platform's upload limits are guidance (#485)

- **`check.py --platform` WARNs, never FAILs, on a length or file size over the platform table's
  limit, and marks those rows `basis: guidance`.** How long and how large an upload may be changes
  often, differs by account, and is owned by whoever uploads (publish-skill reads each platform's
  current documentation); `scripts/_platforms.py`'s numbers are the table's as of
  `UPLOAD_LIMITS_AS_OF` and are known to differ from the platforms' (X 140 s / 512 MiB against
  1200 s / 8 GB, Reels 90 s against 900 s). A FAIL made `check.py` exit 1 on a file its platform
  takes. The row stays, with the measured value and the table's limit, and its `reason` says the
  limit is the table's as of that date and that the uploader checks the current one; it is not
  counted in `failed`. A length or size that could not be measured against a table limit is WARN
  `could not measure` (3.6.7 made the length a FAIL): still never a PASS. The encoding rows (codec,
  aspect, resolution, fps, pixel format, colour, loudness, true peak) are what this tool writes and
  measures, and stay requirements. `basis` is a second field rather than a third `kind`: `kind` says
  what a fix costs (`duration` stays `judgement`, cutting loses content), `basis` says whose limit
  it is, and one row is both. Code: `check.main()` (`guidance`), `_platforms.upload_limit_note()`.
  Test: `test_check_a_platforms_length_and_size_limits_are_guidance`.
- **A limit the caller states is the caller's requirement and still FAILs.** `--max-duration` and
  `--max-mb`, on any platform including `custom`, are `basis: requirement`: the caller asked for
  that number, as with `--levels`. Without a named platform the `duration` row is WARN as every
  judgement row is (1.8.0); that rule is unchanged. Same test.
- **`export.py` still trims to the table's maximum, and its `duration` step still fails when the
  written file is over it.** The trim is the preset's documented behaviour with `--allow-long` as
  the way out, and the step verifies that trim, not the platform's rule; changing what a preset
  cuts is a larger decision than the label on a check row. The `notes` line now says the limit is
  the table's as of its date. The numbers themselves are not edited here (#464 A116, Reels 90 s):
  the uploader's table is the current one, and a second copy kept current here would drift again.

## After 3.8.0 — a length that is not stated, and sound trimmed to the sample (#491, #493)

- **A tool that computes with the input's length refuses an input that states none.** A Matroska
  written to a pipe has no duration in its container or its streams, and `probe()` reports
  `duration: null`. `meta.get("duration") or 0.0` read that as a clip 0 s long: `reverse.py`,
  `grid.py` and `broll.py` ended in a traceback, `fit.py` refused a "speed factor 0.00x",
  `freeze.py` and `speedramp.py` quoted a clip of `0..0.000`, `join.py` joined the clip as 0.04 s
  with `verified: true`, and `fit.py --method trim`, `scenes.py` and `metadata.py --auto-chapters`
  completed on a length of 0. `input_length()` is where these tools read the length now: `null`
  is refused as `kind: input`, the message says the length could not be read and the hint names
  the remux (`export.py --preset copy`), which writes a container that states it. The tool does
  not measure the length itself: that is a full read of the file per tool, and the remux does it
  once for every later step. A dry run's pending input (the probe stub), a stated 0 and a still
  picture (an image demuxer states no length) pass as before; `fit.py --dry-run` does not refuse
  either, because `render.py` plans a clip's speed stage on the source in place of a cut that
  does not exist yet (A97). A tool that only uses the length when a flag needs it refuses only then: `fit.py`
  without `--duration`, `graphics.py` with `--end`, `look.py --at`, `metadata.py` without
  chapters, `export.py` without `--max-mb` and `reverse.py --no-audio` run on the file as it is;
  `cut.py` treats an unknown total as no upper bound, and `loudness.py` and `check.py` report the
  length as not measured (2.20, A113). Code: `emit.input_length()`, `decision.av_clip_length()`.
  Test: `test_an_unread_length_is_refused_by_every_tool_that_computes_with_it`.
- **grid.py, broll.py and multicam.py end their sound to the sample, with audio.py's conform.**
  They ended it with `atrim=duration={:.3f}` / `atrim=0:{:.3f}` and the output's `-t {:.3f}`, as
  `audio.py` did before #478: a length of 59244 samples at 48 kHz was written as 59232.
  `decision.conform_to_length(length, rate)` is the one filter now (`aformat` pinning the rate,
  `apad=whole_len=N,atrim=end_sample=N`, then `atrim=end=length + half a sample` so sound that
  starts late still ends with the picture), and `audio.py` emits the same string it did. The
  sound is padded with silence as well as trimmed, so in `grid.py` every `--audio-from` track
  goes through it (the longer clip's sound was cut by `-t` alone), and a `broll.py` mix or a
  `multicam.py` track that ends early is as long as the picture. The output's `-t` sits half a
  sample past the last one (`conform_output_t`): at `{:.3f}` it would cut the sound back, and a
  frame is far longer than the difference. A dry run's pending input has no rate or length to
  count in and keeps the old filter. The count is of the track's samples: an MP4 edit list is in
  1/1000 s, so the stream's *stated* duration stays a whole millisecond, and the test reads the
  packets with the edit list ignored. Code: `decision.conform_filter()`,
  `decision.conform_to_length()`, `decision.conform_output_t()`. Test:
  `test_grid_broll_and_multicam_end_their_sound_to_the_sample`.

## After 3.8.1 — a length or a silence between two milliseconds (the siblings of #493)

- **A tool whose output ends on `-t` writes the millisecond unless it names another sample
  count.** `overlay.py --image/--video`, `waveform.py`, `loop.py --duration` and `sync.py
  --replace-audio` have no filter that ends the sound: the output's `-t` does, and it was
  `{:.3f}`. 59244 samples at 48 kHz (1.23425 s) were written as 59232. `length_output_t(length,
  rate)` keeps the millisecond text when it cuts nothing off the track at that rate and writes
  the length to the microsecond when it does; FFmpeg takes `-t` in microseconds and rounds it to
  the nearest sample. Where the sound runs on past the length (`sync.py`'s endless `apad`,
  `loop.py`'s next repeat) a millisecond that rounds up is too long as well (59280 for a
  reference of 59261), so there the microsecond is written whenever the two counts differ
  (`runs_on=True`); in `overlay.py` and `waveform.py` a `-t` past the end of the sound cuts
  nothing and stays. The rate is the kept track's (`--audio-stream`), in `sync.py` the second
  file's. No sound, or a dry run's pending input, has no rate: the millisecond stays.
- **That `-t` has no half sample of slack.** `conform_output_t()` adds one beside
  `conform_to_length()`, whose tools end their picture in the graph. Here the same `-t` ends the
  picture, and with the slack a layer's frame that starts exactly at the main input's end (31
  NTSC frames under a longer layer on the same grid) came through on a 1/60000 and a 1/90000
  time base: 32 frames for 31 (FFmpeg 6.1.1; on 1/30000 the slack rounds away). At the
  microsecond the frame stays out. What does change: a frame that starts in the last half
  millisecond before the stated end, which a `-t` rounded down left out and one rounded up always
  let in, is written. `overlay.py --video` over a main input whose sound outlasts its last frame
  by 8 microseconds writes the layer's next frame, as it already did when the sound outlasted it
  by a millisecond.
- **A silence that is not a whole millisecond is counted in samples.** `pad.py --start/--end`
  and `freeze.py --hold` (at the clip's end and at its first frame) wrote `adelay=<ms>` and
  `apad=pad_dur={:.3f}`: 0.23425 s of silence was 11232 samples for 11244. `silence_filter(rate,
  lead, tail)` writes `aformat=sample_rates=R,adelay=NS:all=1,apad=pad_len=N` when an amount is
  between two milliseconds (the `aformat` pins the rate the count is in, as in
  `conform_filter()`; a part of 0 is left out), and the old text when both are whole
  milliseconds, so those commands are the ones they were. One exception, a defect of its own: the
  millisecond was `int(seconds * 1000)`, which cuts 1.001 to 1000 (741 of the whole-millisecond
  values up to 100 s), and is `round()` now. `freeze.py --at T` in the middle of a clip already
  pads by the held frames' length to the microsecond and is unchanged. After 3.8.11 the silence
  *ahead* of a clip (`pad.py --start`, `freeze.py --at 0`) is the length of the frames `tpad` puts
  ahead of its picture, not the amount asked ("After 3.8.11").
- **The picture's `tpad` keeps its millisecond.** `tpad=start_duration/stop_duration={:.3f}`
  becomes a whole number of frames, so the text only matters when the amount is within half a
  millisecond of a half-frame boundary (`--end 0.0504` at 29.97 fps: 1 frame from "0.050", 2
  from the amount), where both counts are half a frame from what was asked. Not changed.
  Code: `decision.length_output_t()`, `decision.silence_filter()`. Test:
  `test_a_length_or_a_silence_between_two_milliseconds_is_written_to_the_sample`.

## After 3.8.3 — the millisecond in fit.py, broll.py and sync.py, and where it changes nothing (follow-ups of #470)

- **`fit.py --method trim` ends its sound on the output's `-t`, written to the sample.** It was
  `-t {:.3f}`: `--duration 1.23425` on a 48 kHz source that runs on wrote 59232 samples for 59244,
  `--duration 1.2346` wrote 59280 for 59261, and `--duration 1.2343` at 44.1 kHz 54419 for 54433.
  It is `length_output_t(target, rate, runs_on=True)` now, the rate the kept track's
  (`--audio-stream`). `--method speed` takes the same text only when the change is too small to
  retime (a factor within 1e-4 of 1, where no `atempo` is added and the source's sound runs on:
  3 s to `--duration 2.9999` wrote 144000 for 143995). Not covered: a retimed track keeps
  `-t {:.3f}`. Its sound ended 13 to 62 ms before the target in every case measured (58368
  samples for a target of 59244, 3 s to 1.23425 s; FFmpeg 6.1.1), so the millisecond cuts nothing
  there; that shortfall is `atempo`'s and is not addressed here, and `render.py` hands a speed
  stage's length to `fit.py` as `{:.3f}` on that path. A whole millisecond, a source without
  sound and a dry run's pending input write the command they did. After 3.8.11 a retimed track is
  conformed to the target's samples ("After 3.8.11").
- **The same `-t` bounds fit.py's picture.** With sound, a trim to 37 frames of a 30000/1001
  source (`--duration 1.2345666`) wrote 38 under `-t 1.235` and writes 37 under `-t 1.234567`.
  Without sound there is no rate, the millisecond stays, and that trim still writes 38 frames:
  seen, measured and not changed here (counted in frames after 3.8.11).
- **`broll.py` delays a cutaway's sound by `--at` to the sample.** It was
  `adelay={int(at * 1000)}|...`: `--at 1.001` started the sound at sample 48000 for 48048
  (`int(1.001 * 1000)` is 1000), `--at 1.2346` at 59232 for 59261 and `--at 1.23425` at 59232
  for 59244.
  An `--at` between two milliseconds is `silence_filter(MIX_RATE, lead=at)` now (`adelay=NS:all=1`
  at the mix's 48 kHz); a whole millisecond keeps `adelay=MS|MS`, rounded. The mix's rate is fixed
  and `--at` is the caller's, so a plan for a pending A-roll writes the delay the run will.
  Not covered: the cutaway's picture keeps its millisecond text (`trim=start={:.3f}:
  duration={:.3f}`, `setpts=PTS-STARTPTS+{:.3f}/TB`, the overlay's
  `enable='between(t,{:.3f},{:.3f})'`). At 30000/1001 with `--at 1.2345666 --from 1.2345666
  --duration 1.0343666` (frames 37, 37 and 31) the cutaway is on output frames 38-67 showing its
  frames 39-68, for 37-67 showing 37-67: a frame time whose millisecond rounds up is past the
  frame. That is a choice of frames, cured by bounds half a frame early as in `av_trim()`, and
  it changes the whole-millisecond commands too; it is left for its own change. The
  `--audio b` gate (`volume=0:enable='between(t,...)'`) is not limited by its text either way:
  FFmpeg evaluates it once per audio frame, and a window of samples 48000-95999 was muted over
  48128-96255. Both are changed after 3.8.11, and the sound's delay with them ("After 3.8.11").
- **`sync.py --replace-audio` delays the second file by the offset it measured, to the sample.**
  At the default `--fine-ms 1` and without `--fix-drift` the offset is a whole millisecond (8
  samples of the 8 kHz the measurement is made at) and the command is the one it was.
  `--fix-drift` adds the measured drift's share to the offset, which is then kept to a tenth of a
  millisecond (0.234 s can become 0.2339 s): that offset is written in samples as well, where it
  was `adelay=234`. With `--fine-ms 0.25` an offset of
  0.2343 s was written as `adelay=234` (the sound started at sample 11232, 11246 now, 11244 in
  the fixture), and one of 0.2345 s as 234 as well (`int(round(234.5))`; 11232, 11256 now, 11261
  in the fixture). Not covered: `--trim-second` still delays by the millisecond, because its
  `-af` reaches every audio track the second file has and the `aformat` that pins the rate of
  the count would resample a track at another rate; and `multicam.py`'s `adelay`, whose offsets
  are whole milliseconds (its step is fixed at 1 ms) except under `--fix-drift`, which was not
  measured and is not changed. After 3.8.11 `--trim-second` delays to the sample: the reason given
  here does not hold, its command writes one audio track ("After 3.8.11").
- **Where the millisecond changes nothing (measured, left as it was).** `join.py`'s
  `anullsrc -t {:.3f}` for a part without sound is padded and trimmed to that part's sample
  count like every other part (`apad=whole_len=N,atrim=end_sample=N`), and silence padded with
  silence is the same silence: two 37-frame parts at 30000/1001 came out as 94494 samples for 59
  frames (the default transition) under `-t 1.235`, and a 31-frame part ahead of a 37-frame one
  as 84885 samples for 53 frames under `-t 1.034`. `insert.py` and `background.py` have no
  sound, and their `-t` is applied in the 1/fps time base of the picture they generate, where
  FFmpeg rounds it to the nearest frame:
  at 30 fps 1.01 s is 30 frames and 1.02 s is 31, two frames (0.066667 s, written "0.067") are
  2, and 37 frames at 29.97 ("1.235") are 37. The text only decides within half a millisecond of
  a half-frame boundary (1.0166 s at 30 fps: 31 frames from "1.017", 30.498 asked), the case the
  3.8.1 section leaves to `tpad`. `grid.py`'s `trim=duration={:.3f}` and
  `tpad=stop_duration={:.3f}` sit behind its `fps` filter in the same time base (37 frames for
  1.234567 s at 29.97 and at 30 fps, 31 for 1.034367 s). `export.py`'s `-t` is a platform maximum
  from the table, whole seconds. `broll.py`'s own `-t {:.3f}` with `--audio a` ends a
  stream-copied track, whose packets are kept whole (59244 of 59244 samples of PCM).
  All of it on FFmpeg 6.1.1, the only one measured. Test:
  `test_a_length_or_a_silence_between_two_milliseconds_is_written_to_the_sample`.

## After 3.8.5 — a flag value the tool cannot honour is refused (audit group: out of range, contradictory, ignored)

- **`--timeout` is 0 (no limit) or a number of seconds a run can wait for; anything else is
  refused.** A negative `--timeout` used to be read as 0, which silently removed the limit, and a
  value whose wait did not fit `poll()`'s C int of milliseconds (2147483 s; `1e8` and `1e300`
  both did not) raised OverflowError once the child was running. The flag is a request, so it is
  refused (`kind: input`); `FFMPEG_SKILL_TIMEOUT` is ambient, so a negative or too-long value
  there keeps being read as 0 with the `timeout_env_invalid` warning. The bound is `MAX_TIMEOUT`,
  500000 s (about 5.8 days), so that the outer ceiling of 4x plus 60 s a sibling run or an MCP
  dispatch gets stays inside that wait; a job longer than that passes 0. Measured on Linux with
  Python 3.11 only. `child_limit()` gives no ceiling for a
  per-call value outside it (the MCP `timeout` key): the child refuses that `--timeout` itself.
  Code: `_common.runner.MAX_TIMEOUT`, `apply_common()`, `_read_env_timeout()`, `child_limit()`.
  Test: `test_a_timeout_no_run_can_wait_for_is_never_an_overflow`.
- **A numeric flag's range is checked in the tool that owns the flag, with `die()` in prose.**
  There is no shared range table: the bound is the filter's or the layout's, and the message
  names it (`-I/--lufs must be -70..-5 LUFS (loudnorm's range), got 5`). Values that still mean
  something are kept: `fit.py --aspect 0:9` is "no aspect" (decided under 2.1.0, above),
  `graphics.py --from 0` counts down from 0, `silence.py --min-silence 0` and `caption.py --gap 0`
  run. Not range-checked here, and left as found: `silence.py --threshold` and `scenes.py
  --threshold/--ratio/--min-scene` with any sign, `overlay.py --margin` below 0, `sync.py
  --step-ms/--fine-ms` of 0 or less, `metadata.py --scene-threshold` outside 0..100.
  Test: `test_a_number_outside_its_range_is_refused_before_ffmpeg_runs`.
- **A parameter of a switch that is off is refused by comparing it with its default.** This is
  the rule `audio.py --duck-*` already had, extended to `--music-*`, `--effects-volume`,
  `--denoise-strength`, `scenes.py --max-scene` and `waveform.py --color/--waveform-mode`. A
  caller who passes the default value explicitly is not refused; argparse cannot tell the two
  apart without a sentinel default, and the value asked for is then the value used.
- **`audio.py --voice` and `--denoise` combine.** The synopsis listed them as alternatives and
  the code let `--voice` win. `light` gets the denoise after its highpass; `medium` and `strong`
  run their own stage at `--denoise-strength`. `--voice medium --denoise` at the default strength
  writes the chain `--voice medium` writes. Code: `audio.voice_chain()`. Test:
  `test_voice_with_denoise_denoises_at_the_strength_asked`.
- **`overlay.py --video --fade` is refused, not implemented.** The image layer's fade is
  `fade=alpha=1` on an RGBA still; the video layer is composited in YUV with its own conversion
  rules (#333, #496), and a fade there is a feature with its own colour tests, not a fix. The same
  holds for a `render.py` overlay entry with `video` and `fade`.
- **A template pack refuses the flags of one render and forwards `--audit-log`.** `--stop-after`,
  `--cache`, `--from`, `--work`, `--keep` and `--export-timeline` name one render's stages, work
  folder or timeline; a pack is several full renders, and sharing them was never built.
- **In a multi-track `--mode mux`, `--offset` is every track's and `--min-duration` is the first
  track's.** An offset corrects the sync of the file, so it shifts each added `--srt`;
  `--min-duration` lengthens the first track's cues only, so the others keep their own lengths and
  the result says so in a note. (As written for 3.8.6 this said wrapping and `--max-lines` were
  computed for the first track at the burn-in size; after 3.8.7 no muxed track is wrapped or split,
  see the next section.) Test: `test_offset_shifts_every_track_of_a_multi_track_mux`.
- **`cropdetect.py --limit 1` is written as the top pixel code of the source's bit depth**, since
  FFmpeg reads a limit of 1 or more as a code. Test: `test_cropdetect_limit_1_is_the_top_of_its_range`.
- **A `batch.py` recipe's unknown key is refused**, as `render.py` refuses a project's
  (`check_keys()`): a recipe has no comment key. Test:
  `test_a_project_or_recipe_value_no_stage_reads_as_written_is_refused`.

## After 3.8.6 — the contract says what a dry run decodes, and a pending input has no length (#466)

- **`probe` is `analysis_only` under `--dry-run`.** It was `none`, with the note that ffprobe
  still runs, because it writes nothing either way; but `none` is the promise that no ffmpeg runs,
  and `--analyze` decodes the first 20 s of each video input with ffmpeg to sample picture levels,
  under `--dry-run` too (audit A193). The levels are measured, not skipped: a dry run of a
  read-only tool that measures is the measurement, as for `check`. Without `--analyze` only
  ffprobe runs, and the fake-ffmpeg test still checks that. Code: `_contract.DRY_RUN_ANALYSIS`.
  Tests: `test_every_tool_that_decodes_under_dry_run_is_in_dry_run_analysis` (a `probe
  --analyze` case, and no exemption for `probe`), `test_dry_run_never_runs_ffmpeg_and_writes_nothing`.
- **`graphics.py --dry-run` on an input an earlier step writes plans to a stated placeholder
  end.** With no `--end`, a graphic ends at the clip's end, and a pending input's probe stub says
  0 s, so the plan refused "--end must be after --start" where `overlay.py` (whose default end is
  open, `gte(t,start)`) plans the same input (audit A202). Its templates animate towards the end
  (fades, the lower third's slide-out, the progress bar, the countdown's steps), so the plan needs
  a number: `--start` plus `PENDING_PLACEHOLDER_SECONDS` (10 s), with a `notes` line saying the
  length is unknown and a real run ends the graphic at the clip's end. An `--end` the caller gives
  is used as given. Not changed here: the same 0 s stub still makes `silence`, `crop`, `freeze`,
  `loop`, `redact`, `speedramp` and `multicam` refuse a dry run on a pending input (swept on
  FFmpeg 6.1.1 and left for a fix of their own). Code: `graphics.main()`. Test:
  `test_graphics_dry_run_plans_on_an_input_an_earlier_step_writes`.

## After 3.8.7 — render.py, batch.py and sequence.py, the audit's remaining findings (#458)

- **A cache key reads a file's modification time in nanoseconds, not its every byte.**
  `batch.file_key()` (render.py's `--cache` uses it too) is the name, size, mtime and first and
  last MiB. The mtime was whole seconds, so a same-size rewrite of the middle within one second
  kept the key and the old output was served as cached (A277). It is `st_mtime_ns` now, the
  identity "An output is identified by size and modification time" already settled on (2.24).
  Still not seen: a rewrite whose mtime is set back (`touch -r`, a copy that keeps it) and a
  filesystem that stores whole seconds (FAT two). A full hash would read every source on every run
  and `--watch` pass; `--force` is the answer for those. Every key written before changes once, so
  the first run after the change runs every item and stage again. A project recipe's key also
  covers every file the project names (render.py's `project_input_files()`, the clip each item
  replaces left out: A80), read on every pass of `--watch` (A81). The chapters file an inline
  chapters list writes is keyed by its content (`render.CONTENT_KEYED`), since a new run writes it
  anew (A100); the chapters stage then hits when the delivery under it came from the cache (a
  hardlink keeps the artifact's mtime) and misses when it was copied without an export stage.
  Code: `batch.file_key()`, `recipe_key()`, `project_files_key()`, `render._content_hash()`.
  Test: `Issue458Tests.test_a_cache_key_changes_with_every_file_the_output_depends_on`.
- **render.py's work directory belongs to one run; an explicit `--work` replaces only render's own
  unchanged stage files.** The default directory is `mkdtemp()` beside the output
  (`<output>_work_<pid>_<random>`): named by the PID alone and reused with `exist_ok`, a later run
  that drew the same PID adopted and then deleted an earlier run's kept preview (A77). With
  `--work DIR`, the stage files a render wrote are recorded with their identity (size, mtime_ns,
  inode, device) in `DIR/.ffskill-render-stages.json`; a later render with the same `--work`
  passes `--overwrite` to the stage whose output is one of them and still that file, so a re-run
  is not refused on its own intermediates (A98). That is the overwrite rule's "a path this same
  run wrote" extended to an earlier render of the same directory; a file edited, replaced or not
  written by render there is refused as before, and nothing in `DIR` is ever deleted. A stage's
  sidecar (caption.py's `.ass`) is replaced with it under that `--overwrite`. A `--dry-run` writes
  its chapters list to a temporary directory and removes a `--work` it had to create, `--keep` or
  not (A99). Code: `render.own_stage_files()`, `_earlier_own_stage_file()`. Test:
  `Issue458Tests.test_the_work_directory_belongs_to_one_run`.
- **An output is named for the container that is written into it.** batch.py names a `.webm`
  source's output `.mp4` unless the recipe sets `ext`, the #415 `default_output()` rule: every WebM
  item of a re-encoding recipe was refused `output_container_codecs` (A83). A recipe whose last
  step keeps WebM (a stream copy, `export.py --preset vp9-alpha`) sets `"ext": "webm"`. render.py
  without an export stage copies the last stage's file, so an output named for another container
  than that file's (`.webm`, `.mkv` for an MP4 intermediate) is refused, `kind: input`: before the
  first stage when the last file is certainly an intermediate, at the copy when it may be the
  source itself (one uncut clip); the MP4 family (`.mp4`, `.mov`, `.m4v`, `.m4a`, `.3gp`) counts as
  one container (A84). It is not converted: an export stage is the conversion. `sequence.py --dir .`
  (or `..`) names its default output after the folder's resolved name, beside it (A108).
  Code: `batch.final_path()`, `render.refuse_copied_container()`. Test:
  `Issue458Tests.test_an_output_is_named_for_the_container_it_holds`.
- **Caller text is made to fit the file it is written into, or refused where the change would be
  silent.** A chapter title in an inline `chapters` list that holds a line feed, carriage return or
  NUL is refused (`kind: input`): metadata.py's chapters file is one `TIME TITLE` per line, read as
  text (a CR ends a line), and FFmpeg ends a title at NUL, so `"Intro\n0:01 Evil"` was two
  chapters, verified (A260); metadata.py refuses a NUL in a `--chapters` file too. Other control
  characters and U+2028 reach the chapter as they are, as metadata.py keeps them. In an EDL, every
  name (the title, clip names, SOURCE FILE, LOC titles) has each line break and control character
  replaced by a space, since CMX 3600 has no escape (A261); FCPXML replaces the characters XML 1.0
  cannot hold. In the pack table a file name is one line with `|` escaped as `\|` (GFM), which
  `report.py --pack` reads back (A263). A JSON file with a lone UTF-16 surrogate escape is refused
  where it is read (`parse_json()`: every project, recipe, brand, plan and transcript), since no
  file, argument or stdout can encode it (A264). Code: `render.validate_project()`,
  `timeline._edl_text()`, `timeline._xml_text()`, `render.md_cell()`, `report.md_cells()`,
  `runner.parse_json()`. Test: `Issue458Tests.test_caller_text_cannot_add_lines_to_a_file_render_writes`.
- **An EDL refuses what CMX 3600 cannot number, and its source timecode wraps at 24 h.** More than
  999 events (the three-digit field: A265), or a record that would run past 24:00:00:00 from its
  01:00:00:00 start, is a `kind: input` refusal naming `.fcpxml`/`.otio`. A source timecode wraps
  at midnight as the media's own does (`_tc_label()`, the day `output_timecode_args()` counts):
  23:59:59:00 plus 2 s is 00:00:01:00, not 24:00:01:00 (A266). Code: `timeline.to_edl()`. Test:
  `Issue458Tests.test_an_edl_refuses_what_cmx_3600_cannot_number`.
- **`batch.py`'s glob matches without regard to case, on every platform.** `"*.mp4"` found
  `GOPR0001.MP4` on macOS and Windows and nothing on Linux, where the batch completed with
  `total: 0` and no note (A82). Each letter outside a `[...]` class is matched in either case
  (`caseless_glob()`; `pathlib`'s `case_sensitive=` needs 3.12); a class keeps its letters, and
  two sources that then reach one output name are refused by the case-folded collision check that
  already existed. A glob that matches nothing is a note. Test:
  `Issue458Tests.test_render_and_batch_do_what_their_flags_say`.
- **The rest, in the same test.** `--stop-after export` stops after the delivery (the chapters and
  check stages do not run, and a `check` it never reads is not read: A87). An executed plan reports
  its output as an absolute path (A96). `--export-timeline` probes each file once (A267).
  `--list-templates` and `--init` print a JSON document under `--json` (A102). The audiogram
  template takes `$BRAND` and draws `$TITLE` as the youtube template does, a lower third from 1 s
  to 6 s; `$TITLE` is not put inside the audiogram block, since a block whose placeholder has no
  value is dropped whole (A90). A pack writes into the directory of `-o`, which the reference now
  says (A86), and the reference lists the ten presets that turn `normalize` on and no `--codec`
  (A103); `examples/brand.json` lost a `loudness` block no tool reads (A107).

## After 3.8.8 — four old grouped issues, item by item (#402, #403, #404, #429)

- **A command that names an encoder or a filter the build lacks is refused in `run()`, not tool
  by tool.** #402 listed some twenty tools; the cause they share is that nothing looked at the
  command before ffmpeg did, so the dry run completed. `_check_build_components()` reads each
  ffmpeg command `run()` is given, as built: `-c:v`/`-c:a`/`-c:s` values after the last `-i` (one
  before an input picks a decoder), each only for a stream kind the output keeps (ffmpeg opens an
  encoder per output stream, after selection: `-an`/`-vn`/`-sn` drops the kind, and `_an_input_has()`
  finds an input file without it, so `cut.py --accurate`'s `-c:a aac` on a video-only source needs
  no AAC; a `-filter_complex` graph, a lavfi or unreadable input counts as carrying it, and explicit `-map`s
  are not read), and the filter names of `-vf`, `-af`, `-filter:v`, `-filter:a`,
  `-filter_complex` and `-lavfi` (`graph_filter_names()`: split at `,` and `;` outside quotes and
  escapes, labels dropped). It is `kind: ffmpeg` with `reason: encoder_missing` /
  `filter_missing` and `details: {name}`, what the failed run already carried, so a caller keyed
  on those sees the same refusal earlier; `--codec av1`/`prores` keep their own `missing_tool`
  refusal, which is decided before a command exists. Left out on purpose: a `*_videotoolbox`
  encoder (`--hw` has its own platform check and CPU retry), `copy`, a lavfi input and a
  `-filter_complex_script`, every `run_analysis()` measurement (`loudness.measure()`'s loudnorm
  pass among them, which still fails in ffmpeg on a build without the filter; several callers take a failed
  reading as "no reading": cropdetect's windows, `probe.py --analyze`; the others now carry the
  cause through `ffmpeg_failure_extra()`), and any list that could not be read (an empty list
  proves nothing; the read for this check is quiet and records no `ffmpeg_list_unreadable`).
  `stabilize.py` asks for its two filters with `require_filter()` because its first pass is a
  measurement. Not done: `render.py` still finds a missing drawtext at the stage that needs it,
  after the earlier stages ran (its `--dry-run` finds it); `look.py` has no fallback for an HDR
  source without zscale, so `report.py` has no HDR sheet there; `caption.py --mode mux` is still
  listed as needing the subtitles filter and libx264, because `required` describes the default
  mode and moving them would make doctor call a build usable on which the default fails. Tests:
  `BuildComponentPreflightTests`.
- **`audio_tracks_dropped` stays unreported under `--dry-run` outside `cut.py`.** It is the
  comparison of the first input with the written file ("Not compared: ... a dry run", above);
  `cut.py` reports its own from the plan.
- **Under `--dry-run`, `probe(role="output")` is the stub whether or not a file is at the path.**
  With `--overwrite` and an earlier run's file there, a dry run read that file as its result. `cut.py`'s `output_duration` is `null` in a dry run, as the contract said. Not done:
  `cut.py --dry-run` still plans `mode: copy` for a copy the real run re-encodes when it lands
  past `--tolerance`; where a copy lands is only known by making it. Tests: `DryRunOutputTests`.
- **`cropdetect.py` measures at `round=2` and rounds a detected crop itself** (`round_rect()`,
  the filter's own arithmetic, `--round 1` read as 16 and an odd value doubled as the filter
  reads them), so a picture that reaches every edge is the frame, unrounded.
  Test: `test_cropdetect_reports_a_bar_free_frame_as_the_frame_whatever_round_is`.
- **`probe.py --analyze` makes no Log guess about an HDR stream**: `looks_like_log: null`,
  `reason: not_measured: ...`; the numbers stay. Test:
  `test_probe_analyze_does_not_call_an_hdr_stream_sdr`.
- **A verification step with no expected value carries no `provenance`.** The field says where an
  expected value came from; the `decode` step (does every stream decode) and export's
  `key_fill_pair` (the two written files against each other) have none, and wrote `measurement`
  and `output_measurement`, values the schema's enum does not have. Dropping the field, not adding
  a value, keeps the enum's meaning. Test: `test_every_provenance_a_tool_writes_is_one_the_schema_lists`.
- **`--emoji mono` on a build whose libass draws colour reports `mode: color` on the libass
  route.** `mono` and `color` build the same text, so nothing makes the glyph monochrome there; the
  result says what is drawn and warns (`emoji_mono_drawn_in_colour`). `graphics.py` sends `color`
  through libass as it sent `mono`; with `--text-render drawtext` nothing draws them, so the mode is
  `none`, they are stripped with `emoji_not_drawn`, and no colour warning is given. Tests:
  `EmojiClaimTests`.
- **`caption.py --text` refuses a file that starts as WebVTT, ASS or JSON**, naming `--srt` for
  WebVTT and `--ass` for ASS/SSA. The JSON refused is an object, or a non-empty array whose first
  element is an object or an array; an array of plain values (`["hello"]`) is cue text, as is a
  first line in brackets that is not JSON (`[Music]`). `metadata.py --chapters` drops one
  separator (`-`, a dash, `|`, `:`) followed by a space from the start of a title. `join.py
  --list` refuses concat directives rather than applying them (the argument-free `stream` too; a
  line that names a file that is there is a path): a trim is `cut.py`'s job, and a
  list that trims would otherwise join untrimmed files. `color.py --lut` checks a `.cube` for
  what lut3d needs (`LUT_3D_SIZE`, size^3 rows starting with three numbers) and leaves the other
  LUT formats to ffmpeg. `--image` (overlay, waveform) takes what the image demuxers read; a
  video or a GIF (one frame or many) is refused, as `-loop 1` always refused it, and `waveform.py` reads the plate under `--dry-run` too. `silence.py --words`
  warns about timings past the input rather than refusing: a transcript longer than a trimmed
  input is a caller's choice. Tests: `WrongFormatFileTests`, `WordsFileTests`.
- **Seen, verified and left for their own change** (the first four are fixed in the #510 section
  below): `broll.py --insert` with a still shows it for
  one frame (the input has no `-loop 1`); `--font-file` given a file that is not a font draws a
  fontconfig fallback with `font_used.substituted: false` (FFmpeg 6.1.1); unknown keys in a
  `--brand` file are ignored; `report.py --pack` takes any Markdown with a table;
  `independent_measurement` is in the provenance enum and no step writes it; and the four items of #429 (a step that writes without `{out}`, caption sidecars in
  a batch, placeholder side inputs in the cache key, Ctrl-C during a render stage), each of
  which changes the contract.

## After 3.8.9 — captions and text drawing (audit #457, #505)

- **A muxed subtitle track is neither wrapped nor split, and `--max-lines`/`--wrap` are refused
  with `--mode mux`** (A55). A soft track is drawn by the player at a size this run does not know;
  wrapping it at the burn-in size (24 of 288 lines) turned one cue on a 360x640 video into three
  consecutive cues of two words each. `--offset` and `--min-duration` still apply. A layout flag is
  recognised by its default (`--max-lines 2` and `--wrap phrase` given explicitly are accepted), as
  the 3.8.5 section's flags are. Code: `caption.main()` (`lay_out`). Test:
  `test_a_soft_subtitle_is_not_wrapped_at_the_burn_in_size`.
- **Word timings move with `--offset`** (#505). `--offset` exists because a transcript runs early or
  late against the sound, and the word timings come from the same transcript, so they are shifted
  by the same amount, for an `--srt` sidecar and for `--transcribe`. Word timings that are absolute
  to the media and must not move are not supported; a caller who has them passes no `--offset`.
  Code: `caption.shift_words()`. Test: `test_caption_karaoke_keeps_source_word_timings_after_srt_layout`.
- **The karaoke highlight waits for the first word** (A59). With real word timings the silence
  between the cue's start and its first word is an empty `\k` syllable (`sweep`) or an event with
  no active word (`word`); the energy and even splits have no lead and share the cue from its
  start, as before. Code: `caption.word_durations_from_timings()`. Test:
  `test_karaoke_waits_for_the_first_word_and_moves_with_offset`.
- **Under `--karaoke-style word`, `--animate` is one envelope spread over the word events** (A57).
  Each event gets the part of the cue's fade that falls inside it, as a `\fade` started at the
  alpha the event before ended on; a pop and a slide are carried on from where they are at the
  event's start (`\fscx` at the interpolated scale, `\move` from the interpolated point, `\pos`
  once the slide is over). A whole-cue event keeps the exact override it had, so `sweep`, a
  one-word cue and a run without karaoke write the ASS they wrote. The issue's simpler proposal
  (`\fad(in,0)` on the first event, `\fad(0,out)` on the last) left a step in the alpha when the
  first word is shorter than the fade-in, which this does not. Code: `caption.animate_fx()`. Test:
  `test_word_karaoke_takes_one_envelope_across_its_word_events`.
- **`--animate slide` ends on the line's own anchor** (A56): `--position`, a cue's `{\anN}` and the
  Style's MarginL/MarginR/MarginV, which is where libass draws the line without the slide; it
  rises 30 script lines into place for every position, as it did at the bottom. The bottom-centre
  slide with symmetric margins writes the `\move` it wrote. Code: `caption.line_anchor()`. Test:
  `test_animate_slide_ends_where_the_line_is_drawn_without_it`.
- **An SRT burn whose cue text holds `{...}` goes through the generated ASS** (A68). ffmpeg's SRT
  reader removes `{\...}` blocks itself and passes `{curly}` on to libass, where it is an override
  block and nothing of it is drawn; the generated-ASS route draws the braces and their text, so
  that route is taken, as an emoji overlay takes it, and a note says so. A cue with only `{\...}`
  blocks or a MicroDVD `{y:i}` code stays on the SRT route (ffmpeg removes those as markup, which
  `text_unchanged` does not count), and on the generated-ASS route a `{\...}` block in the same cue
  is drawn as text, as the 1.15.0 entry decided. Code: `caption.SRT_HIDDEN_BRACES_RE`. Test:
  `test_an_srt_burn_draws_the_text_in_braces`.
- **The kinsoku joins are phrase mode's** (A54). The first fill joins a no-line-start character
  (now including the fullwidth `，；：．`) to the atom before it and a no-line-end one to the atom
  after it, so the greedy fill can no longer open a line with `、` or `，` where no later pass
  reconsidered the break, and the orphan and weak-line passes move such a mark down only with the
  character it closes. A break after `，；：` is preferred as one after `、` is (it also settles the
  case where the other break would open a line with a particle). `--wrap measured` keeps 1.15's
  fill, so an older split still reproduces, and `phrase_breaks` still counts against it. Where no
  allowed break fits, a forbidden one is still taken: a bracketed run wider than the line, a line
  of about 3 em, two such characters in a row (`。ょ`). Measured on random kana and Han strings at
  4 to 12 em, not on a corpus. Code: `_common.wrap._kinsoku_atoms()`. Test:
  `test_no_line_opens_with_punctuation_that_may_not_start_one`.
- **`font_used.file` under `--bold` is the face `fc-match FAMILY:bold` names** (A70): what libass
  asks fontconfig for, the bold face where the family has one and the regular face (emboldened by
  libass) where it does not. Not measured from libass itself, and not on Windows, where nothing is
  resolved for libass. `graphics.py --template meme` draws its lines bold on the ASS route and
  reports the regular face; that is left for its own change. Code: `_common.fonts.font_choice()`.
  Test: `test_font_used_names_the_bold_face_libass_draws`.
- **In a burn, `--language` is a hint and is not checked as a track tag** (A71). It picks the
  script's font and the wrap's rules, both of which read `ja_JP` as `ja` (the wrap split on `-`
  only until now); a value neither knows changes nothing, as an absent one does. Only `--mode mux`
  writes it into the file, so only there is it refused when it is not a language code, under its
  own name, for an `--srt` track and a `--text`/`--transcribe` one alike. Code: `caption.main()`
  (`tagged_by_language`). Test: `test_language_is_a_track_tag_only_where_there_is_a_track`.
- **The emoji placeholder restores what it changed, not the Style** (A69): the four alphas (the box
  colour's at the Style's own value) and a letter spacing of 0. `{\r}` also dropped the pop, a
  per-cue `\fs` and a cue's `<i>`/`<b>`/colour for the text after an emoji. Code:
  `_ass_overlay.emoji_placeholder()`. Test: `test_the_emoji_placeholder_keeps_the_lines_own_animation`.
## After 3.8.10 — compositing, time and edge inputs (#460, #461)

- **A printed command that names a file the tool removed is a record, not a rerunnable line.**
  A concat list, an ffmetadata file, a drawtext text file, a two-pass log or a render stage's
  intermediate is written for the run and removed when the tool exits, so the line in `commands`
  that names it cannot be pasted and run again (audit A238). Keeping those files would leave a
  temporary directory behind every run; the README and the contract's `commands` description say
  which lines are records instead. Code: the tools' temp directories (`tempfile.mkdtemp`). Test:
  `test_printed_commands_say_which_name_a_removed_temp_file`.
- **A rectangle at an odd `--x`/`--y` is exact in luma; the chroma pair on its odd edge is
  shared.** `redact.py` takes its patch with `crop=...:exact=1`, gives it a transparent first
  column/row where x/y is odd and puts it at the even position before it (`overlay` places a 4:2:0
  input on the chroma grid), so no luma sample outside the rectangle changes and every one inside
  it is redacted (audit A170). A 4:2:0 chroma sample on that edge covers a pixel inside and one
  outside, and is half mixed: there is no exact answer at that resolution. `crop.py` cuts with
  `exact=1`, so the rectangle written is the one asked for. `overlay.py --position X,Y` and
  `fit.py`'s computed crop offset still landed on the even position before an odd one (10,12 for
  11,13, measured on 6.1.1); both are exact since #512 (the "After 3.8.11" section). Code: `redact.main()`, `crop.main()`.
  Test: `test_an_odd_rectangle_is_taken_and_redacted_where_it_was_asked`.
- **A hold of the last frame keeps the subtitle track.** `freeze.py` with no `--at` (or an `--at`
  at the clip's end) appends frames past the end and moves no cue, so it keeps the track as
  `--mode extend` does; a hold inside the clip or at its start still drops it (its cues would fire
  early) and says so (audit A180). Code: `freeze.main()`. Test:
  `test_freeze_of_the_last_frame_keeps_the_subtitle_track`.
- **Matroska attachments travel only into Matroska, and a second picture is reported, not
  kept.** A subtitle track's fonts are attachments, which no `-map 0:s?`/`0:d?` selects; a tool
  that keeps the subtitles into `.mkv`/`.mka`/`.mks` now maps `0:t?` as well. MP4, MOV and WebM
  hold none, so there `source_carry` lists `attachments` dropped with the warning (audit A256). A
  second playable video stream is left out by every tool that writes one picture (they write the
  one `probe()` describes, `V:0`); `source_carry` lists `video_streams` dropped (audit A258).
  Neither is a refusal: the output is what was asked for, minus what the container or the tool
  cannot carry, said. An MP4/MOV chapter text track (read by FFmpeg as a data stream with the tag
  `text`) is never copied: the muxer writes one from the chapters it is given, and the copy was a
  stray data track with the old titles (audit A173). Code: `runner.carried_stream_maps()`,
  `emit.source_carry()`. Tests: `test_attachments_and_a_second_picture_are_kept_or_reported`,
  `test_a_chapter_track_is_not_copied_as_a_data_stream`.
- **`render.py` compares its output with a project's one source only.** Its stages run as their
  own tools, so it probes the source itself before it reports: a project whose clips are all one
  file, with no music, replacement or effects track, no video layer and no audiogram, gets
  `source_carry`; any other mixes sources, and is not compared, as for any tool with two (audit
  A255). The start timecode counts as kept when every stage that compared it kept it (a cut from
  1 s writes the label of the frame it starts on, not the source's), as dropped when one dropped
  it; a stage served from `--cache` replays the verdict its entry recorded. Code: `render.emit()`,
  `render.project_source()`. Test: `test_a_one_source_render_says_what_its_output_lost`.
- **`background.py --gradient` runs corner to corner at every angle.** C1 is on the corner the
  direction starts from, C2 on the opposite one; the `gradients` source is drawn on a square as
  wide as the frame's diagonal and the frame cropped from its middle, since `gradients` takes its
  two points only inside its own frame (a point below -1 is refused, one past the edge replaced by
  a seeded random one). Every angle outside 0-90 failed as `kind: ffmpeg` (audit A169), and inside
  it the far point lay past the frame, so the picture of `--angle 0`/`90` changes too. Code:
  `background.gradient_source()`. Test: `test_background_gradient_runs_corner_to_corner_at_any_angle`.
- **`memory_heavy` is keyed on the decoded frames held, about 2 GiB.** `reverse.py` and
  `loop.py --boomerang` hold every decoded frame; the estimate is width x height x the chroma
  planes (4:2:0 1.5, 4:2:2 2, 4:4:4 3, plus an alpha plane) x 2 bytes above 8 bits x the frames.
  reverse.py warned on a length above 60 s, so 30 s of 4K60 (about 21 GiB) went unwarned and 61 s
  of 320x180 was warned (audit A174). It is an estimate for a warning, not a limit: nothing is
  refused. Code: `decision.held_frames_bytes()`. Test:
  `test_reverse_warns_from_what_it_holds_not_from_the_length`.
## After 3.8.11 — a window, a start or a length on the frame or the sample it names (#470's open items)

- **A window on the picture is bounded half a frame from the frames it selects.** `overlay.py
  --start/--end`, `graphics.py`'s windows and `broll.py`'s cutaway wrote `between(t,{:.3f},{:.3f})`.
  At 30000/1001 frame 37 starts at 1.2345667 s, which `{:.3f}` writes as 1.235, past it, and `t`
  is a double that is not always the number the text reads as (the frame at 1.4 s of a 25 fps MP4
  is not `<= 1.400`). `window_expr(start, end, meta)` writes the bounds half a frame before the
  first frame at or after `start` and half a frame after the last frame at or before `end`, on the
  grid `grid_at_or_after()` counts on (`half_open` for an end that is the next window's start:
  the countdown's digits). A window of frames 37-67 (`--start 1.2345666 --end 2.2356666`) is on
  37-67; the text drawn by `drawtext` was on 38-67 and 31-59 for 31-60. With no grid (a dry run's
  pending input, a picture probe() suspects of a variable rate) the millisecond text stays. The
  bounds change for a window in whole milliseconds as well (`between(t,1.980000,8.020000)` for
  `--start 2 --end 8` at 25 fps): written at the frame's own time the text was the one that could
  go either way.
- **An overlay's window is in the layer's position, not in `enable`.** overlay's `enable` is
  evaluated on each frame either input hands over, the layer's next frame included, so a still
  looped at 25 fps or a 25 fps `--video` over a 30000/1001 picture was drawn on frames 36, 38-65
  and 67 for 37-67 (FFmpeg 6.1.1). `windowed_overlay_x(x, window)` writes `x='if(WINDOW,X,-w)'`,
  evaluated once per output frame with the main picture's `t`: the layer is off the picture
  outside the window. `overlay.py --image/--video` and every `graphics.py` layer (`overlay`
  boxes, the lower-third bar, the progress bar) are written this way; `drawtext` and `drawbox`
  see the main picture's frames only and keep `enable`. A fade's `alpha` keeps its millisecond:
  a fade-in is at 0 on its first frame either way. Not changed: `_common/emoji.py`'s PNG windows
  follow the cue of the line libass draws (`caption.py`, `graphics.py`'s ASS route), whose times
  are libass's own; bounding the PNG alone would split it from its line. Not measured.
- **`broll.py`'s cutaway is whole frames of the A-roll, and its sound starts with them.** The
  window is the A-roll's frames from its first at or after `--at` to the last before `--at` plus
  the length; B is cut from its first frame at or after `--from`, half a frame of its own early,
  for that many frames, and put on the A-roll's exact rate (`fps=30000/1001`, not `fps=29.97`).
  `--at 1.2345666 --from 1.2345666 --duration 1.0343666` at 30000/1001 was on frames 38-67
  showing B's 39-68 and is on 37-67 showing 37-67. B's last frame is held (`eof_action=repeat`)
  and the position takes it off: with `eof_action=pass` the last frame depended on where B's end
  fell against the window, and a window between two frames gained or lost one (`--at 0.5
  --duration 0.5` at 25 fps was 13 frames, 12 now, the frames that start in [0.5, 1.0)). This
  replaces the 3.8.3 entry's "delays a cutaway's sound by `--at`": the picture never started at
  an `--at` between two frames, the next frame did, and the sound ran ahead of it (`--at 1.001`
  at 25 fps: sound from 1.001 s, picture from 1.04 s). The sound is delayed by the window's first
  frame now (`adelay=1040|1040`), as both streams of a clip shift by one constant (#409); an
  `--at` on a frame writes the delay it did. A cutaway in which no frame of the A-roll starts
  (`--at 1.01 --duration 0.02` at 25 fps) is refused as `kind: input`: it would show nothing.
  Without a grid for the A-roll: the old text.
- **`broll.py --audio b` mutes the A-roll per sample.** `volume=0:enable='between(t,...)'` is
  evaluated once per audio frame: a window of samples 48000-95999 was muted over 48128-96255
  (1024-sample frames). `aeval='val(ch)*not(between(t,LO,HI))'` is evaluated per sample on the
  A-roll's clock, the bounds half a sample outside the window's first and last sample, and B's
  layer is padded or cut to the same count, so the A-roll is muted exactly where B sounds.
- **`fit.py --method trim` without sound counts frames.** It kept `-t {:.3f}`: 37 frames of a
  30000/1001 source were written as 38 under `-t 1.235`, and `--duration 1.0014` as 30 for 31
  under `-t 1.001`. `picture_output_t()` keeps the millisecond when it keeps the same frames as
  the target and writes half a frame before the first frame left out when it does not (`-t
  1.217883`). Not from the centre (the output's clock starts at the seek, between two frames) and
  not with `--fps`: the millisecond stays there. `--method speed` without sound is a sibling not
  changed: its retimed picture is regridded by the output's own frame-rate handling, which reads
  the graph's frame rate, and FFmpeg 7.0 changed what a `setpts` leaves of it
  (`frame_durations`); 6.1.1 writes 38 frames for a 37-frame target (3 s to 1.2345666 s at
  30000/1001), and 7.1 and 8 were not measured.
- **An SMPTE time at an NTSC rate is counted at the exact rate.** `parse_time()` divided the
  frame count by `fps` as probe() reports it, 29.97: `00:00:01:07` was 1.2345679 s, 1.2
  microseconds past frame 37, and a start read from it was the frame after. `ntsc_rate()` reads
  23.976, 29.97, 47.952, 59.94 and 119.88 (probe()'s three decimals, or an `@29.97` suffix) as
  N * 1000 / 1001, as `timeline.exact_rate()` does; every other rate is used as it is. Every tool
  that takes a time through `time_arg()` reads it so.
- **`fit.py --method speed` leaves a retimed track at the length `atempo` gives it.** Its output
  is laid down in windows placed by the content and comes out short or long (3 s of bursts to
  1.23425 s: 58368 samples for 59244; to 2.0 s: 95360 for 96000; a sine: 59232 for 59244;
  FFmpeg 6.1.1). Following the `atempo` chain with `conform_to_length(target, rate)` in `-af`,
  as `audio.py` does in its graph, ended the track on the sample on 6.1.1, 7.1 and 9.0.2 and
  never ended on FFmpeg 8.0.1 (`atempo=...,aformat,apad=whole_len=N,atrim=end_sample=N,atrim=end=T`
  with `-t`: every such run in CI was killed at the 1800 s limit, #514). It is not shipped; the
  3.8.3 behaviour stays and the item stays open on #470.
- **`sync.py --trim-second` delays to the sample.** The 3.8.3 entry kept `adelay=<ms>` because
  "its `-af` reaches every audio track the second file has". That sentence is wrong: the command
  maps the default selection, or with several streams the probed picture and sound
  (`default_selection_maps`), so one track is written, the one `sec_sr` is the rate of (a second
  file with a 48 kHz and a 44.1 kHz track: one 48 kHz track written, before and after). With
  `--fine-ms 0.25` an offset of 0.2343 s started the sound at sample 11232; it is
  `aformat=sample_rates=48000,adelay=11246S:all=1` now (`silence_filter`). At the default
  `--fine-ms 1` without `--fix-drift` the command is the one it was. Not changed: the picture's
  `tpad=start_duration={:.4f}` is whole frames; the sound is placed on the offset measured
  against the reference, and moving it to the frame would undo that alignment.
- **A silence ahead of a clip is as long as the frames put ahead of its picture.** `pad.py
  --start` and `freeze.py --at 0 --mode insert` delayed the sound by the amount asked, which the
  3.8.1 entry counted in samples, while `tpad` puts whole frames ahead of the picture: `--start
  0.23425` at 25 fps is 6 frames (0.240 s) of picture and was 0.23425 s of silence, the clip's
  sound 5.75 ms ahead of its picture; `--start 0.05` at 30 fps was 2 frames and 0.050 s.
  `tpad_length(seconds, meta)` is the length tpad makes of the `{:.3f}` text it is given (the
  nearest frame count, a half rounding up), and the sound is delayed by it: 11520 samples for
  the 0.23425 s, `adelay=240:all=1`, and `--start 1.001` is 25 frames and `adelay=1000:all=1`.
  `pad.py` says so in a note when the two differ. The silence after a clip (`--end`, `freeze.py`'s
  hold at the end) moves nothing and is the amount asked, counted as the 3.8.1 entry says. No
  rate (a dry run's pending input) or a variable one: the amount asked.
- **`loop.py` fills the gap a long sound leaves at each repeat on the clip's rate.** A repeat is
  as long as the file, so where the sound outlasts the picture the next repeat starts after a
  gap, and what stood in it was left to the output's frame-rate handling: FFmpeg 6.1.1 repeated
  the last frame and showed the next repeat's first frame twice, from 1.20 s where its sound
  starts at 1.23425 s (a 1 s 25 fps clip with 1.23425 s of sound); FFmpeg 7.1 and 8 held the
  last frame (50 packets for 6.1's 56; seen in CI). The graph now ends on `fps=<clip's rate>`
  when the file outlasts the picture by more than half a frame: the last frame is repeated in the
  graph and each later repeat's frames sit on the grid once (its first on 1.24 s). `fps` rounds
  to the nearest tick, so a repeat's first frame is within half a frame of its sound on either
  side (1.20 s for sound at 1.21 s); rounding up would never be early and could be a whole frame
  late, and half a frame is the bound the other time tools hold. The number of
  frames is then the graph's, not the FFmpeg version's default; that is measured on 6.1.1 only,
  and 7.1 and 8 are expected, not seen, to write the same 56. A clip whose repeats meet, a
  `--crossfade` repeat and a variable-rate source (conformed by `-fps_mode cfr -r`) write the
  command they did.
  All of it measured on FFmpeg 6.1.1 only. Code: `decision.window_expr()`,
  `decision.windowed_overlay_x()`, `decision.ntsc_rate()`, `decision.tpad_length()`,
  `fit.picture_output_t()`. Tests: `test_a_window_or_a_length_on_a_frame_time_keeps_that_frame`,
  `test_a_start_a_gate_or_a_retimed_length_is_written_to_the_sample`,
  `test_a_loop_whose_sound_outlasts_its_picture_repeats_the_last_frame_on_the_grid`.
## After 3.8.12 — audit #462: where cut.py, the smart cut and silence.py cut

Eleven items of the 2026-11 audit of `cut.py`, `_smartcut.py` and `silence.py` that were still real
on 3.8.5 (A50 and A52 are fixed in their own change). Each was reproduced on FFmpeg 6.1.1 first.

- **A silence with no speech on one side keeps no margin on that side (A40).** A silence that starts
  where the sound starts is removed from the file's start, and one that runs to where the sound ends
  is removed to the file's end. `--margin` is air kept beside speech. At the file's edges it kept a
  piece of dead air of its own (`keep [0, 0.2]` before the first word) with a jump cut after it.
  FFmpeg 6.1 closes a silence that runs to the end at the file's end (`silence_end: 7.50933` for a
  7.5 s file), so the `inf` end the code tested for never came. "Where the sound starts and ends" is
  the audio stream's start and its start plus its own length, within `SOUND_EDGE` (50 ms):
  silencedetect closes a silence at its last decoded block, and an AAC stream's stated start sits a
  priming frame off its samples; a sound shorter than that before a leading silence (or after a
  trailing one) is no word to keep air beside. Code: `silence.inside_margin()`, `silence.sound_span()`. Test:
  `test_silence_keeps_no_margin_where_there_is_no_speech`.
- **An EDL is written once the cut it describes exists (A41).** This is the `--timemap` rule
  ("written only after the cut", 2.22). It now holds for `silence.py --edl`, `scenes.py --highlights
  --edl` (after its `--sheet`) and `multicam.py --edl`/`--write-project` (after the render). Before,
  a refused run (an existing `-o`, `-o` the input, nothing kept, an existing `--sheet`) left an EDL
  of media never made, and the corrected retry was refused for that EDL. `--list` writes it as
  before. The path checks still run up front (`guard_sidecar`), so a dry run predicts them. Test:
  `test_silence_writes_its_cut_lists_only_once_the_media_exists`.
- **The level at each cut is read on the file's clock (A42).** `cut_levels()` decoded the sound to
  PCM from its first sample and read each window at `t x rate`. A sound 0.5 s late was read 0.5 s
  after every cut, giving -24 dB at a cut in digital silence. The decode ends in
  `aresample=async=1:first_pts=0`, as `decode_pcm_mono` does ("both streams on one clock", above).
  It was the one PCM decode indexed by time that did not; the others (`decode_pcm_mono`,
  `caption.py`'s level read) already pad. Test: `test_silence_measures_each_cut_on_the_files_clock`.
- **A kept bound never lies before the file's start (A43).** `rendered_ranges()` moves each bound
  to the nearest frame time, on the grid that runs from the picture's first frame. With a picture
  that starts 0.29 s after its sound, the nearest grid point to 0 was -0.011. A bound that rounds
  below 0 now takes the first grid point at or after 0 (0.022), which is where `cut.py`'s re-cut
  starts that range anyway (`grid_at_or_after`). So `keep`, `--edl` and `--timemap` agree with the
  render, and `cut.py --segments` takes the EDL. Test:
  `test_silence_never_keeps_a_range_before_the_files_start`.
- **`--list` and `--filler-list` take the picture from the `-o` they are given (A48).** A list
  writes no media, and the picture test read that media path as none, so with an audio `-o` it
  reported frame-snapped ranges (1.2, 1.833) that the audio run cuts at 1.213 and 1.817. Test:
  `test_silence_list_for_an_audio_output_reports_the_ranges_the_audio_run_cuts`.
- **`--max-cuts` counts removal ranges, refuses only a render, and gives a reason that holds
  (A49).** The help says removal ranges, and the check counted keep
  ranges. One pause (two kept pieces) was refused at `--max-cuts 1`. It also refused `--list`,
  which is how a caller sees what the limit is about. Its reason was the one-graph filter's size,
  which the chunked re-cut (#409) no longer has. The flag stays, with its default of 400, as a
  guard against an edit chopped by a `--threshold` that catches speech. The count is
  `time_map()["removed"]` (a lead-in and a tail count as cuts too), checked before the render and
  under `--dry-run`. Test: `test_silence_max_cuts_counts_the_removal_ranges_and_never_refuses_a_list`.
- **The time map's documentation says what #409 made it (A47).** `docs/contract.md` and
  `references/scripts.md` still said the map advanced by millisecond-rounded bounds and drifted over
  many cuts. Since #409 it is the sum of the rendered ranges' exact lengths (2.22's `--timemap`
  entry, above). Documentation only.
- **`--smart` copies the last GOP of a cut that runs to the end of the video (A44).** The copy
  stopped at the last keyframe and re-encoded the GOP after it as a tail (30 frames of a cut from
  1.5 s of a 4 s source). The module docstring says that part is left out, and a GOP that ends with
  the video is whole. Code: `_smartcut.plan_segment()`. Test:
  `test_smart_cut_to_the_end_copies_the_last_gop`.
- **A Matroska smart cut is checked against Matroska's time base (A45).** A `.mkv` output always
  reads 1/1000 (the muxer's millisecond timestamps), and the check compared it with an MP4 source's
  1/15360. Every such cut fell back, and only after it had been built and verified. The frame-grid,
  packet and decode checks are what show a join gone wrong. The time base check is there to see
  the MP4 time scale `execute()` sets. Code: `_smartcut.expected_time_base()`. Test:
  `test_smart_cut_into_matroska_from_an_mp4_source`.
- **A single-range audio extraction pads a late sound from 0 (A46).** `cut.py --start 0 --end 2 -o
  part.wav` of a source whose sound starts 0.355 s after its picture wrote 1.645 s with the sound
  moved earlier. `--segments ... --accurate` already kept the offset. The re-encode of one range to
  an audio output ends in `aresample=async=1:first_pts=0` instead of `asetpts=PTS-STARTPTS`.
  Not covered: a stream copy of the sound (`-o part.m4a` without `--accurate`) still starts at its
  first packet (`make_zero`). A copy cannot add silence, and leaving the timestamp in place
  (measured without `make_zero`) did not give a decoder a leading gap either. Since #515 the
  result says so (the "After 3.8.20" section). Test:
  `test_an_audio_extraction_keeps_a_late_sounds_offset`.
- **`--remove` does not keep a leftover with no picture (A51).** `--remove 1-6` of a 6 s picture
  with 6.3 s of sound left 6.0-6.3, which was then refused as "segment 6.000-6.300s is shorter than
  one frame", a segment the caller never gave. A cut keeps a picture in every segment, so a
  leftover that holds less than one frame of the picture (sound before its first frame or after its
  last) is left out to a video output, and a note names it. A removal that leaves only such
  sound is refused (`kind: input`) with the way out (an audio `-o`). To an audio output the sound is
  kept, as before. `silence.py` is not changed by this: its last range past the picture is a
  range of the render, which ends the picture there as the source does. Code:
  `cut.keep_ranges_after_removing()`. Test: `test_remove_drops_a_leftover_with_no_picture_and_says_so`.
## After 3.8.12 — issue #459: audio, sync, multicam, scenes and waveform

- **`audio.py --duck-amount` is the depth in dB, made with a gate, not a compressor.** A
  compressor's gain reduction is how far its key rises over the threshold times `1 - 1/ratio`, so
  no ratio gives a stated depth: the ratio `max(2, amount/3)` used through 3.8.8 ducked 0 and 3
  the same 9.7 dB on the test's speech and 60 by 18. The bed is now split: one copy goes through
  `sidechaingate` keyed by the speech (`ratio=9000:range=0:knee=1`: all of the bed above the threshold,
  none below; agate's default soft knee of 2.82843 opened it only about 2 dB over the threshold,
  so a key 1.5 dB over it left the bed unducked), that copy is scaled by `-(1 - 10^(-amount/20))` and added to the other, which
  leaves `10^(-amount/20)` of the bed under speech and all of it in the pauses (measured: 3, 12
  and 30 dB asked, 3.0, 12.0 and 30.1 written). The key gets `dcshift=shift=0.000001` (-120 dBFS):
  agate's detector starts at zero and leaves the gate open while the key is exact zeros, so a
  voice track that begins with digital silence ducked the bed until its first word. The
  threshold, attack and release keep their meaning (the gate opens at the threshold over
  `--duck-attack` and closes over `--duck-release`); the result's `duck.ratio` is the gate's 9000,
  and `amount_db` is the depth. The default command line moved: the "unchanged to the byte" the
  1.13 test pinned was a compressor string, and it now pins the gate's. Code: `audio.duck_graph()`.
  Test: `test_duck_amount_is_the_depth_in_db`, `test_audio_duck_parameters_reach_the_sidechain_filter`,
  `test_a_key_just_over_the_duck_threshold_ducks_the_bed`.
- **A limiter runs on what is delivered.** With `--music` or `--effects`, `--limit` and `--voice
  strong`'s `alimiter` move from the main track to the mix, ahead of the fades and the conform; a
  limiter on the voice let the beds added after it pass the ceiling (`--limit-ceiling -6` wrote 0
  dBFS). The ducking key is the voice before that limiter, which only lowers peaks above the
  ceiling. Without a bed the chain is the one it was. What is limited is the mix before it is
  encoded: a lossy encoder after the limiter can peak over the ceiling in the written file (the
  test writes PCM), and `loudness.py` is the tool that measures and holds a written file's peak. Code: `audio.py` (`post_limit`). Test:
  `test_a_limiter_is_the_ceiling_of_the_mix_it_delivers`.
- **A dynamics knee is 0..18.06 dB.** The filters take a linear knee of 1..8 (default 2.82843); the
  flag converts dB to linear and accepted 1..8 *dB* (linear 1.12..2.51), so nothing from 2.51 up to
  ffmpeg's own default could be asked for. The range is widened to the filter's, in dB, rounded
  down to 18.06 so the linear value stays inside 8; a value that ran before still writes the same
  knee. The help's defaults are ffmpeg's, converted (threshold -18.06, range -24.26, knee 9.03).
  Test: `test_dynamics_help_gives_the_filters_own_defaults_in_the_flags_unit`.
- **`--bitrate` (`loudness.py --audio-bitrate`) given for an audio output replaces that
  extension's own setting; `.wav`/`.flac` refuse it.** `.mp3`'s `-q:a 0` becomes `-b:a`, CBR at
  the rate asked; libopus and libvorbis keep their VBR around it. Not given, every extension keeps
  the setting it had. `loudness.py`'s unpinned `.m4a`/`.aac` starts at the 256k it was always
  written at and reports it (`audio_bitrate_used` said 192k), so its overshoot retry is 320k
  only; a pinned rate is reported for `.mp3`/`.ogg`/`.opus` too, which had no
  `audio_bitrate_used`. Code: `decision.audio_codec_for()`. Test: `test_bitrate_reaches_the_codec_of_an_audio_output`.
- **A filter graph over 100,000 characters (8,000 on Windows) reaches ffmpeg in a file.** Linux
  refuses one argument over 128 KiB and Windows a command line over 32,767 characters; a graph
  built per item (`scenes.py --sheet`'s select, ~50 characters a scene) crossed it between 2,400 and
  3,000 scenes and raised OSError with no JSON. `run()` and `run_analysis()` write the graph to a temp
  file and pass `-/filter_complex`, `-/filter:v` ... on FFmpeg 7.0 and later and
  `-filter_complex_script`, `-filter_script:v` ... before it, removing the file afterwards; the
  command a run records and prints keeps the graph inline. Only the 6.1 spelling was run here.
  Code: `runner.long_filters_in_files()`. Test: `test_scenes_sheet_of_thousands_of_scenes_is_written`.
- **`scenes.py --sheet` has no expression that grows with the scene count.** One `select` summing a
  term a scene reached FFmpeg in the file above and 7.1 and later refused it at 3,000 scenes
  (ENOMEM from the expression parser; 6.1 took 30,000, flat or nested). The scenes are dealt
  round-robin to `split` branches of at most 64 terms (`SHEET_SELECT_TERMS`), each summed as a
  balanced tree (6 nested levels), and `interleave` merges the branches' thumbnails in time order;
  dealt round-robin, the branches stay level and interleave holds about one thumbnail a branch.
  Only 6.1 was run here: that 7.1+ takes 64-term expressions is unverified until CI. Code:
  `scenes.sheet_graph()`. Test: `test_scenes_sheet_select_expressions_do_not_grow_with_the_scene_count`.
- **`decode_pcm_mono()` returns an `array('f')`.** Four bytes a sample instead of a Python
  float's ~32, and every value is the double the list held (an s16 sample over 32768 is exact in
  a float32). It is still the whole decode in memory, now about 0.3 GB an hour at scenes.py's
  22.05 kHz (twice that while the decode is converted); streaming the envelope instead is a
  larger change and was not made. Test: `test_decoded_pcm_takes_a_few_bytes_a_sample`.
- **`sync.py`'s confidence penalises the best other peak.** The runner-up is the highest local
  maximum more than five steps from the winner; the running "previous best" it was took the
  winner's own neighbour, so an exact match read 0.59 and a tie 0.50. A file against itself or a
  shifted copy now reads above 0.95 on the test's bursts; a tie stays at most 0.5 (the formula,
  `min(1, 0.5 + margin)`, is unchanged). The benchmark sentences in references/scripts.md and
  README ("misses flagged below 0.3", "4 of 5 misses flagged") were measured with the old
  runner-up and could not be re-run here (no corpus); both now say so. Test:
  `test_sync_confidence_tells_an_exact_match_from_a_tie`.
- **`multicam.py --switch` ranges that overlap are refused** (`kind: input`) rather than merged or
  resolved by order: which camera a caller meant for the overlap is theirs to say. Ranges that
  touch run. **`--fix-drift` retimes the picture** with `setpts=(PTS-STARTPTS)/ratio`, as
  `sync.py --trim-second` does; `--write-project`'s clip of a retimed camera carries the ratio as
  `speed`, the per-clip rate render.py plays a clip at (fit to its length / speed), so the
  project's clips last what the direct render's do; a camera that is not retimed (camera 0, a
  fallback to it, a ratio of 1) carries no `speed`, as render.py skips 1. Tests: `test_multicam_switch_ranges_that_overlap_are_refused`,
  `test_multicam_fix_drift_retimes_the_picture_with_the_sound`.
- **A `scenes.py --highlights` range lies inside its scene.** Its window starts at the scene's
  start or on the 0.5 s grid after it and ends by the scene's end, and is written to the
  hundredth rounded inward (3.333 is 3.34, not 3.33). A grid point before the cut was a candidate
  and opened up to 0.5 s early. Test: `test_scenes_highlight_never_opens_before_its_scene`.
- **The beat grid's refit is held on a `--beat-range` bound, not discarded.** A fit a hair past the
  bound (90 BPM under 60-90) kept the step-rounded interval (89.76 BPM, 80 ms off by 30 s); the
  tempo still cannot leave the range, and a fit more than an eighth of the interval away is
  still discarded. Shared by `cut.py --snap beats`. Code: `decision._refine_grid()`. Test:
  `test_scenes_beats_keep_their_refit_on_a_range_bound`.
- **`waveform.py` of an audio input writes `<name>_waveform.mp4` by default**, and `-o` with an
  audio extension is refused (`kind: input`): the output always has a picture. Other tools keep an
  audio input's extension, which is right for them (cut, silence, loudness, audio write sound),
  except where a `.wma` input's would be encoded into, refused since #517 ("After 3.9.2"): name `-o`;
  the tools that always write a picture refuse an audio-only input. Test:
  `test_waveform_of_an_audio_input_is_a_video_by_default`.
## After 3.8.13 — frame size, colour tags, delivery limits and verify's outputs (#463, #464)

- **A BT.2020 source with no transfer tag is re-encoded as `bt2020-10`, not HLG** (A153).
  `probe()` reads BT.2020 primaries without a transfer tag as `hdr: false`, "BT.2020 SDR"; the
  10-bit line filled the missing tag with `arib-std-b67`, so the output read back as HLG, an HDR
  signal the source never was. Leaving the tag out would also be honest, but the x265 VUI needs a
  value and every other tag on the line is written; `bt2020-10` is the SDR curve BT.2020 defines
  (the same function as BT.709's) and reads back as what probe called the source. An HDR signal
  with no transfer tag (Dolby Vision whose base layer is untagged) keeps the HLG default it had.
  Code: `_common.decision.source_transfer()`. Test:
  `PictureTests.test_an_untagged_transfer_is_not_written_as_another_signal`.
- **`color.py --to-sdr --force` labels a frame missing a colour tag with what the chain assumes**
  (A161's sibling): on FFmpeg 6.1 zscale's `pin` does not reach a frame whose own primaries are
  unspecified ("no path between colorspaces"), so a file with no tags failed as `kind: ffmpeg`.
  A `setparams` with the chain's assumptions (PQ, BT.2020) comes first when a tag is missing; a
  fully tagged source's chain is unchanged. The note names the transfer and primaries the chain
  read. Code: `_common.color.hdr_to_sdr_chain()`. Test:
  `PictureTests.test_to_sdr_force_on_a_non_hdr_file_says_what_it_read_it_as`.
- **A pixel offset the caller gives is not moved by a filter's chroma rounding** (A157): fixed
  for `crop.py` and `redact.py` in 3.8.11 ("After 3.8.10", A170: `crop=...:exact=1`, and the
  redaction patch padded by a transparent column/row so the luma of exactly the asked rectangle
  is replaced). A layer `overlay.py --position x,y` places at an odd x or y still lands one pixel
  up or left on 4:2:0 (FFmpeg 6.1.1's overlay at 1,1 draws at 0,0): #512.
- **A media output with no file extension is refused before ffmpeg** (the sweep of A159): every
  tool that writes media gave it to ffmpeg, which failed as `kind: ffmpeg` after the run had
  started, and the dry run completed. `run()` refuses it as `kind: input`,
  `output_extension_missing`, unless the command names a format with `-f` after its last input.
  An unknown extension (`out.xyz`) is still left to the muxer: telling which of FFmpeg's 200-odd
  muxers a build has would cost a process per run. (Changed by #558, "After 3.13.2 — file names": it is
  refused, and the build is asked only for an extension outside the common ones.) Side files are not checked, and `look.py` takes
  an `-o` without an image extension as a stem in every mode (`<stem>_sheet.png`,
  `<stem>_vs_<other>_<i>_<t>s.png`, `<stem>_<t>s.png`), as the decision above already said for
  `--at`. Code: `runner._check_output_extension()`. Tests:
  `ContractTests.test_a_media_output_with_no_extension_is_refused_before_ffmpeg`,
  `AnalysisTests.test_look_takes_an_o_without_an_image_extension_as_a_stem_in_every_mode`.
- **A proxy is never wider than its source, and never under 2 px** (A162). A proxy exists to be
  smaller; the default `--width 640` upscaled a smaller source, and an explicit `--width` above the
  source width is capped too, with a `notes` line, rather than refused: the caller's intent ("at
  most this wide") is met. Test: `DeliveryTests.test_proxy_is_never_wider_than_its_source`.
- **`sphere.py`'s vertical field of view follows from the others unless given** (A163):
  `2 atan(tan(h/2) H/W)`, which keeps the pixels square. A pair the caller gives is drawn as
  given (a squeezed view can be what is wanted) with a `notes` line saying how far from square it
  is, past 0.5 %. Test: `EditingTests.test_sphere_default_view_has_square_pixels`.
- **`stabilize.py --zoom` is the only zoom** (A156): vidstab's `optzoom` is 0. Its default (1)
  adds an "optimal" static zoom on top of `--zoom`, which made `--zoom 0` ("keep the original
  framing") and `--crop black` mean nothing. The default output changes: it keeps the framing and
  shows (stretched, or black with `--crop black`) the edges stabilizing reveals; `--zoom N` crops
  them away. Test: `PictureTests.test_stabilize_zoom_zero_keeps_the_framing_and_shows_the_edges`.
- **A platform preset that keeps the source's frame rate conforms one above the platform's
  `fps_max`** (A115) to the source rate over the smallest whole divisor within it (120 to 60,
  119.88 to 59.94, 100 to 50), so each output frame is a source frame and motion keeps its
  cadence. Today that is the youtube family; the other platform presets already write 30 fps.
  Test: `DeliveryTests.test_a_platform_preset_writes_what_its_platform_check_passes`.
- **`export.py --max-mb --normalize` re-encodes the sound at the preset's bitrate** (A112), the
  one the size budget subtracted. loudness.py's own true-peak bitrate raise is off there: a file
  over the size the caller set is the larger miss, and a true peak still over the ceiling is
  reported as before. Without `--max-mb` nothing changes. Test:
  `DeliveryTests.test_export_max_mb_with_normalize_stays_under_the_limit`.
- **`probe.py --field` prints a string as itself and any other value present as JSON** (A123); a
  missing field is an empty line, as it always was (kept for callers that test for one). With
  `--json` or `--json-brief` every line is JSON: a string is quoted and a missing field is `null`.
  A string stays bare without them so `$(probe.py f --field video.codec)` keeps working. Tests:
  `AnalysisTests.test_probe_field_prints_json_not_python`,
  `AnalysisTests.test_json_brief_alone_prints_the_json_document`.
- **`verify.py` forwards `--overwrite` and `--fast` to its steps, and `--keep` alone keeps the
  outputs in a folder it names** (A119, A120); stems never collide, compared case-folded (A121).
  `--hw` is not forwarded: verify.py has no such flag. Without `--overwrite` a rerun into the same
  `--out` still fails each step on its existing output (every tool refuses to replace one). A name
  it generates that is another input (`clip.mp4`'s `clip_cut.mp4` beside it in a folder verified
  into itself, a link or another case of the name included) refuses the whole run before anything
  is written, `--overwrite` or not: each step checks its output against its own input only. Tests:
  `AnalysisTests.test_verify_stems_never_collide_and_its_outputs_are_where_it_says`,
  `AnalysisTests.test_verify_never_writes_a_name_that_is_another_input`.
- **`straighten.py --fit crop` writes the displayed frame's own size** (A154): fixed in 3.8.11
  ("After 3.8.10", A235). `EditingTests.test_straighten_crop_fit_writes_the_source_frame_size`
  pins it at every angle tried.
- **`fit.py --method trim` from 0 does not seek** (A158), so its subtitle and data tracks are
  kept as for any tool that leaves the timeline alone ("Subtitle/data tracks are kept where the
  picture's timeline is untouched", above). A cue that runs past the trim is kept whole, as
  export's platform trim keeps it, so the container can be longer than the picture by the rest
  of that cue. Test: `EditingTests.test_fit_trim_from_the_start_keeps_the_subtitle_track`.

## After 3.8.13 — tests, CI, distribution and the site (#467)

- **Decoded audio is still the whole file, at 4 bytes a sample** (A217). `decode_pcm_mono()` returns
  an `array('f')` instead of a list of Python floats: about 8 bytes a sample at the peak (the
  decoder's s16 bytes, a 16-bit copy, the floats) against about 72 to 81, so an hour at 8 kHz
  peaks at about 230 MB, not 2.3 GB, and an hour of `scenes.py --beats` at 22.05 kHz at about
  640 MB; 4 bytes a sample are held after the decode. It is not
  streamed: `scenes.py`'s speech ratio and onset refinement, `loop.py`'s seam and `sync.py`'s
  correlation read the samples themselves, not only an envelope, and a streamed envelope for some
  callers would be a second decode path with its own clock. Every value is the float the list
  held (a 16-bit sample divided by 32768 is exact in a float32). Code: `_common/probe.py`
  `decode_pcm_mono()`. Test: `test_decoded_pcm_is_four_bytes_a_sample_and_the_same_values`.
- **`contract --json --tool NAME` narrows `tools` and nothing else** (A220). The other keys stay
  whole, `provides` and `capability_map` included (a few KB together; they map ids to tools across
  the skill), so a consumer reads the same document shape with or without the flag and the 3.x
  promise that no key of `contract --json` is removed holds for it. One tool is about 55 to 85 KB
  against about 950 KB. An unknown name is refused with the list; `doctor` refuses the flag, since
  `doctor --json .tools` is already one short entry per tool. Code: `_contract.main()`. Test:
  `test_contract_tool_selects_entries_and_refuses_an_unknown_name`.
- **The lint for unused imports is a test, not a CI step** (A224). `tests/test_contract.py` walks
  the shipped modules (`scripts/`, `scripts/_common/`, `mcp/server.py`) with `ast`, so it runs in
  every job that runs the contract tests, on every OS, and needs no linter: a pip-installed one in
  CI would be the first third-party tool the gate depends on, and its version would move the
  result. `_common/__init__.py` and `_common/text.py` are left out: they import names for their
  callers. A `noqa` comment on the import line exempts it. Unused variables and dead functions are
  not checked (A224's two of each were removed by hand). Test:
  `test_the_runtime_imports_nothing_it_does_not_use`.
- **Bytecode is kept out of the npm package by `files`, not by `.npmignore`** (A222). With `files`
  set, npm 10 packs everything under a listed directory whatever `.npmignore` says, so the negated
  entries `!**/__pycache__/**`, `!**/*.pyc` and `!**/*.pyo` end `files` and `release_check.sh`
  fails a tarball with a `.pyc` in it. `.npmignore` stays, saying why it is not enough. Test:
  `test_npm_package_leaves_out_python_bytecode`.
- **A demo whose second command uses a measured value runs that value and stops when the gallery
  prints another** (A243, A244). `docs/demos.md` is written by replaying the builders with nothing
  run, so it can print only a constant (`CROPDETECT_GALLERY_RECT`, `SCENES_GALLERY_SEGMENTS` in
  `demos/build.py`). A real build reads the measurement (cropdetect's `crop`, the `--edl` ranges),
  and nothing measured or a value other than the constant is a `BuildError`, so the command under
  a picture is the one that made it. A different FFmpeg that measures the synthetic fixtures
  differently fails the build until the constant and the page are updated; that is the intent.
  Test: `test_a_demo_runs_the_measured_value_and_the_gallery_prints_it`.
- **The agent eval installs the shipped skill and watches the checkout; it does not sandbox the
  agent** (A271, A274). `evals/run_agents_25.sh` installs each run's skill with `bin/install.js
  --dir` (the set `npx ffmpeg-skill` installs: no evals, answer keys or tests) instead of linking the
  checkout, and compares the checkout's state before and after every run (`git status
  --porcelain`, the tracked files' diff against `HEAD` and the untracked files' hashes): a run
  that changed it is named in `RUN_DIR/<id>/.tree_changed` and the script exits 1. A `RUN_DIR`
  inside the checkout that git does not ignore is refused before anything is staged, rather than
  left out of the comparison: leaving out a folder that holds tracked files would hide edits to
  them. The state carries `HEAD` and the index as well (a run that commits its edit leaves the
  status clean; one that only restages leaves the status line and the diff against `HEAD`), an
  untracked link is hashed as its target's name without being followed,
  and a snapshot git cannot take stops the script with exit 3 before the agent starts: two failed
  snapshots are not an unchanged checkout. The agent still
  runs as the caller, with the caller's HOME and environment and `bypassPermissions`: `claude -p`
  reads its sign-in from HOME, and a headless run cannot answer a permission prompt. Run it in a
  container or a throwaway account when that matters. Tests:
  `test_the_agent_eval_installs_the_shipped_skill_and_watches_the_checkout`,
  `test_the_agent_eval_sees_a_second_edit_and_refuses_a_run_dir_it_would_see`.

## After 3.8.14 — odd positions, the CFR conform and the timeline's aspect (#512, #506)

- **A VFR source is conformed by the `fps` filter, in the picture's graph; the encoder line keeps
  `-fps_mode cfr -r` as well, and then moves no frame.** The encoder line's conform alone let a
  frame fall up to about two frames behind its slot before it dropped one: on a 30 fps clip with
  two runs of six frames dropped (27 fps on average) every tool through `cfr_args` wrote flashes
  18 and 56 ms after their beeps and a picture 74 ms longer than the source's. The filter takes
  the nearest frame for every slot; on that clip each of those tools wrote every flash 18-19 ms
  after its beep (within half a 27 fps frame) and a 4.000 s picture (FFmpeg 6.1.1). It is the last
  filter of a plain `-vf` chain, and the first of a `-vf` that is a graph of its own
  (drawn_chain()'s split/maskedmerge for a colour with chroma, `pad_filters()`'s blur pad in
  `fit.py --fit blur`/`--pad-fill blur` and `export.py`; `chain_with_rate()` places a rate that is
  not cfr_args()'s the same way) and of a `-filter_complex` graph
  that composites onto the main picture without moving it in time (`overlay`, `redact`, `broll`,
  `graphics`, `caption`'s emoji route, `color --keep-alpha`): FFmpeg 6.1's overlay and maskedmerge
  end their output at the last frame's start, so an fps filter after them lost the last frame
  (3.963 s of 4; `export.py --preset reels --pad-fill blur`, whose `-r 30` was appended after the
  blur pad, wrote 119 frames of a 4 s 30 fps picture). `fit.py` conforms after any retiming and
  ahead of the frame's own filters. `pad.py` conforms right after `tpad`, inside its drawn chain: in front of it the
  padding was rounded to the 27 fps grid on top of the frames' own rounding (37 ms late). After 3.9.0 it conforms ahead of `tpad`, the padding counted in the delivered
  rate's frames and the sound delayed by them (#538, in that section).
  `cfr_at_input()` raises when such a graph does not read the main picture exactly once, so no
  graph goes unconformed without a word. A graph that moves frames in time closes on the delivered
  rate (`speedramp.py`, `freeze.py` inside the clip) or takes the filter after its concat (`cut.py
  --segments`). `speedramp.py` gives each segment the frames between its retimed ends on the
  whole output's grid (its picture shifted by under half a frame onto that grid, padded by two
  clones and cut to the count; its sound padded or cut to its own sample count) and joins the
  two streams by separate concats: each segment's own length rounded to the grid drifted (eight
  0.5 s segments at 1x of the 27 fps clip held 14 frames each and put the last flash at 3.630 s
  for 3.5), and one concat over both started each segment after the longer of its two streams.
  The joined picture's timestamps are rebuilt from its running frame count
  (`setpts=N*den/(num*TB)` and a closing `fps` on the delivered rate): FFmpeg 6.1.1's video-only
  concat ends a segment at its last frame's timestamp, so a one-frame segment had no length, and
  three in a row put the rest of the picture a frame early (0.267 s for 0.3). A segment that falls
  wholly inside a VFR source's gap holds no source frame and still comes out empty. The rate is cfr_args()'s own, so a 29.97 average is still written as `29.97`. A
  rate the caller names (`--fps`), an `export.py` social preset's `-r 30`, a youtube preset's
  divided rate for a source above the platform's limit (120 to 60: `_platform_rate_args`, after
  3.8.11) and `fit.py --method speed`'s retimed picture (the picture only: its `atempo` track keeps
  its own length, see "After 3.8.11"; with `--fps` the retimed picture goes to that rate at once,
  where `fps=30` then `fps=60` kept 60 of a 2x speed-up's 120 pictures) go through the same filter (a 1.11x speed-up of a constant 30 fps clip
  showed each flash 50 ms late; the 30 fps social presets measured no shift on that VFR clip
  before or after). `grid.py` already conformed each cell with `fps=`, and `join.py` measured
  18-19 ms before the change; both are unchanged. Not changed, each with its own cause:
  `speedramp.py` puts its sound 21 ms early (atempo; a segment at 1.0 on a constant-rate clip, 40
  ms after a 0.5x segment), so its test measures the picture alone; and a `freeze.py --at` inside
  a VFR gap writes the picture after the hold early (56 ms at `--at 0.15`, 93 ms at `--at 2.2` on
  that clip). `reverse.py` is not changed either: `reverse` hands its frames the forward
  timestamps in order, so a reversed VFR picture keeps its gaps where they were in forward time
  and showed each flash 0.19 s late on that clip (its closing rate is already the delivered one,
  A234). Conforming before the `reverse` filter puts it within half a frame but can drop the
  source's last frame before the reversal (one that falls past the delivered grid's last slot),
  which `test_reverse_of_a_variable_rate_clip_opens_on_its_last_frame` pins; that is left for a
  decision (#512). After 3.8.20 all three are changed (#523, in that section). Code: `decision.cfr_filter()`, `with_cfr()`, `cfr_at_input()`,
  `graph_with_cfr()`, `chain_with_rate()`, `speedramp.main()`. Tests:
  `test_a_variable_rate_conform_keeps_each_picture_within_half_a_frame`,
  `test_a_speed_change_puts_each_picture_within_half_a_frame`,
  `test_speedramp_segments_hold_the_frames_between_their_retimed_ends`,
  `test_a_one_frame_speedramp_segment_keeps_its_length`,
  `test_a_speed_change_to_a_named_rate_keeps_every_picture`,
  `test_a_rate_conform_ahead_of_a_composite_pad_keeps_the_last_frame`.
- **A VFR hold is counted at the rate its frames are cloned at.** `freeze.py` counted `--hold` in
  frames of the average rate and `tpad` cloned them at the nominal one, so 1 s held 27 frames
  spaced 1/30 s (0.9 s) while the sound was padded by 1 s. The count, and the sound's pad, are now
  in frames of the nominal rate. After 3.8.20 a hold inside the clip clones frames of the
  delivered rate, the picture being conformed as it is decoded, and is counted in those (#523).
  Code: `freeze.main()`. Test: the `freeze` case of
  `test_a_variable_rate_conform_keeps_each_picture_within_half_a_frame`.
- **An `overlay.py` layer lands at its position in luma; the chroma sample on an odd edge is
  shared.** `overlay` places a layer on a 4:2:0 picture on the chroma grid, so an odd x or y was
  taken down to the even one before it (`--position 11,13` drew at 10,12; a right-aligned,
  bottom-aligned or centred layer whose position came out odd moved the same way). The position is
  computed from the main picture's and the layer's sizes (its integer part, as overlay takes it);
  where it is odd the layer gets a transparent column or row on that side (in RGBA for an
  `--image`, at 4:4:4 for a `--video` layer) and is overlaid at the even position before it. A
  4:2:0 chroma sample on that edge covers a pixel inside the layer and one outside, so it is half
  mixed: there is no exact answer at that resolution, as for `redact.py` (A170). A dry run whose
  input or layer does not exist yet has no sizes and plans the expressions as before. `--text`
  (drawtext) was already exact. The layer's own size is computed for the position as `scale`
  computes it (`-1`/`-2`, rounded half away from zero); the pad is written in `iw`/`ih`, so the
  layer is never resized by it. An `--image` that stores non-square pixels is made square at its
  display aspect first, as a `--video` layer is (square_pixels(), #411): the position was computed
  from its displayed size while overlay received the stored one, so a 100x100 PNG at SAR 2:1 sat
  at x=120 of a 320 px main, 100 px wide, for `top-right --margin 0`. Code: `overlay.on_grid()`.
  Tests: `test_an_overlay_lands_where_its_position_says_in_luma`,
  `test_an_image_layer_with_non_square_pixels_is_placed_at_its_displayed_size`.
- **`fit.py --fit crop` keeps its crop offset even by widening the scaled frame, not with
  `crop=exact=1`.** `crop` floored the computed offset `(in_w-out_w)*crop_x` to the chroma grid,
  so over an odd margin `--crop-x 1` kept one column of the margin and lost the source's last
  column, and a centred crop sat a pixel left of / above the centre. The scaled frame is now the
  size `force_original_aspect_ratio=increase` gives, with the margin on each axis rounded up to a
  multiple of 4 (at most 3 px more on the cropped axis, a scale off the source's aspect by under a
  pixel), and the offset is computed in the tool, to even: `--crop-x/-y` 0, 0.5 and 1 land on the
  edge or the centre exactly, any other anchor on the even offset nearest it, with a `notes` line
  naming the axis, the offset asked and the one applied (`--crop-x 0.25` over a 36 px margin: 10
  px, not 9). This is
  `straighten.py --fit crop`'s rule (A235). `exact=1` keeps the scale but puts the chroma half a
  sample off the luma on an odd offset. A dry run whose input does not exist yet plans the old
  expressions. Code: `fit.main()`. Test:
  `test_fit_crop_anchor_lands_on_the_edge_or_the_centre_it_names`.
- **A one-clip `--export-timeline` sequence takes the `fit` object first, by the render's rule.**
  The render's fit stage gives fit.py the `fit` object's aspect, mode, width, height and fps and
  the frame's only where the object has none (`setdefault`), so the export does the same before it
  sizes the sequence: frame 16:9 with `fit` 1:1 rendered a square and exported 16:9, and a frame
  aspect `16/9` replaced by `fit.aspect` exported the source's size (#506). A `fit.aspect` or
  `fit.fit` fit.py would refuse is refused under its own name. Several clips are unchanged: their
  join is sized from the frame before fit.py reframes it, and the three render gaps listed under
  "The sequence is the project's frame" (one side and no aspect, padding before a crop, a `fit`
  object over the join) are still open there (after 3.9.1 the first and the third are closed,
  #526). Code: `render.export_timeline()`. Test:
  `test_a_one_clip_sequence_takes_the_fit_objects_frame`.

## After 3.8.16 — shared code and the MCP server (#465)

- **A file with an image name that ffmpeg cannot decode as one is refused by `probe()`** (A184).
  ffprobe lists a text file named `.png` as a png stream of 0x0 through the image demuxer; that was
  reported as a measured picture (`probe.py` exit 0) and divided by in `check.py` and `insert.py`.
  `probe()` now refuses a still (read by `image2` or an `*_pipe` demuxer) whose stream has no frame
  size, `kind: input`, `reason: still_unreadable`, for every tool that probes the file, which is
  every input of every tool except `sequence.py`'s frames after the first (it probes the first
  only; since 3.8.18's follow-up every frame is decoded once before the encode, and a later one
  that does not decode is refused there, with the same reason: "After 3.8.18" below). A stream with no size in a video container is not refused there: such a file can
  still carry a readable track, and the tool that reads it decides. Code: `_common.probe.probe()`.
  Test: `test_a_file_named_as_an_image_that_is_not_one_is_refused`.
- **A sibling script past its outer ceiling is sent SIGTERM and killed only if it has not exited
  15 s later** (A183, `STOP_GRACE`). Its own SIGTERM handler stops its ffmpeg (up to 5 s each),
  removes the partial output and releases the output lock; the SIGKILL that `run_tool()` sent left
  both. The document is still `kind: timeout`, exit 124, and says "stopped" or "killed".
  `verify.py`'s per-step `--timeout` stops its step the same way; `subprocess.run()`'s SIGKILL left
  each timed-out step's partial output and output lock in `--out`. A SIGTERM or Ctrl-C to
  `verify.py` itself stops the step it is running the same way (`stop_children()`); through the
  review of #530 the step was not tracked and ran on, writing, after `verify.py` had exited.
  **On Windows** no SIGTERM handler can run (`terminate()` is TerminateProcess on the tool's own
  Python), so the tool and every process it started, its ffmpeg included, are killed at once with
  `%SystemRoot%\System32\taskkill.exe /T /F` (`terminate_tree()`), and the call returns once
  taskkill has. Nothing of the tool's own cleanup runs: its output lock stays, naming a process
  that no longer runs, which the next run to that output takes over (`stale_lock_taken_over`), and
  its partial output stays under the final name, which the next run refuses as `output_exists`
  unless `--overwrite` is given. Without taskkill, or when it fails or takes more than 30 s, only
  the tool is killed and its ffmpeg can run on. This branch runs on the Windows CI job only; here
  the choice of branch is tested with the kill call replaced. Code: `_common.runner._stop_child()`,
  `terminate_tree()`. Tests: `test_a_child_past_its_ceiling_is_stopped_and_cleans_up`,
  `test_a_sigterm_to_verify_stops_its_running_step`,
  `test_stopping_a_tool_picks_the_tree_kill_on_windows_only`,
  `test_on_windows_a_stopped_tool_takes_its_ffmpeg_with_it`.
- **A colour name is checked against ffmpeg's own table** (A189). `validate_color()` took any word,
  and an unknown one (`grey`; ffmpeg has `gray` and `lightgrey`) failed inside ffmpeg as kind
  ffmpeg after a dry run that completed. The table is the `ffmpeg -colors` list (the same in 6.1
  through 8), plus `random` and `bikeshed`; a word that is not a name passes only as six or eight
  bare hex digits, which is how ffmpeg reads it (whatever the first digit is: "After 3.8.19"). The test compares the table with the installed
  ffmpeg's list, so a later FFmpeg that adds a name fails it rather than refusing the name. Code:
  `_common.color.FFMPEG_COLOR_NAMES`. Test: `test_an_unknown_colour_name_is_refused_before_ffmpeg`.
- **`run()` and `run_analysis()` add `-pattern_type none` to every still input with a `%` in its
  name** (A7), the #408 guard, which only the tools that called `still_input_args()` had: the emoji
  overlay PNGs, `grid.py`'s and `broll.py`'s stills and `join.py`'s reached image2, which read
  `st%d.png` as a sequence and opened `st1.png`. An input that sets its own `-pattern_type` or `-f`
  is left alone (no tool here reads an image sequence through a pattern; `sequence.py` writes a
  concat list). The ffprobe stream checks inside `run()` and the frame readers of `_common.alpha` and
  `_common.probe`, which start their own process, add it too. Code: `_common.runner.guard_input_formats()`. Test:
  `test_a_percent_in_a_still_path_never_opens_another_file`.
- **Read RIFF/WAVE inputs as WAV (#518).** FFmpeg 9.0.2 can misidentify ordinary
  PCM audio as MPEG-TS. The same input-format helper now uses the file header
  for probes, edits and measurements. Explicit input formats take precedence.
  Since #558 the guard is `-f image2 -pattern_type none` ("After 3.13.2 — file names"): the option alone failed
  for a name that is not a pattern.
- **Two paths are one file when they resolve alike or when the file is the same (device and
  inode)** (A5). `run()`'s output-is-input guard compared resolved strings, so a hard link to the
  input and, on a case-insensitive volume, the input's name in another case were written over.
  With a hard link the staged `--overwrite` would have left the source's data in place, but the
  name the caller gave is still the input, as `refuse_output_is_input()` already treated it. The
  same comparison now serves the side-file guards, `silence.py --timemap` and `--plan`.
  `caption.py` refuses an `-o` that is its input (by name or as another name for it) before it
  writes the SRT or the ASS; it used to write the sidecar beside the source first (review of
  #530). Not measured here: a case-insensitive volume (the CI runners on macOS and Windows have one). Code:
  `_common.runner.same_file()`. Tests: `test_a_second_name_for_the_input_is_refused`,
  `test_caption_refuses_the_input_as_output_before_writing_a_sidecar`.
- **A stale output lock is taken over inside a section the operating system holds** (A186). Two
  runs that both found the same stale lock used to both remove "it": the second removal took the
  first run's new lock, and both wrote the output. A run that judges the lock stale now takes the
  section first: `<lock>.takeover`, locked through the OS (`flock` on POSIX, `msvcrt.locking` on
  Windows). Inside it the run judges the lock again, removes it only if it is still stale, and
  creates its own lock before it leaves; a lock found gone there is not removed, and its own
  create decides. A run that cannot get the section within 2 s (`SECTION_WAIT`) is refused as
  `output_locked`, `why: takeover_in_progress`. A run also removes its own lock at its end inside
  the section, and on POSIX only while the file at that name is still its own; when a takeover of
  its lock is under way it leaves the lock to that run. The section belongs to the run while it
  lives and is released by the kernel when the run closes it or ends, killed included, so a run
  paused inside it for any length of time still keeps every other run out, and nothing is left
  for another run to judge or recover. Through the review of #530 the section was a file whose
  existence was the lock, recovered by others once it was older than 60 s: a run paused past that
  lost it without knowing, a contender took the lock over, and the paused run then removed the
  contender's fresh lock, so both held one; three rounds each closed one window of that and left
  another. The section's file means nothing by itself: its name is removed when the section is
  left. On POSIX that happens while the lock is still held, and a run that had opened the old file
  finds, once it has the lock, that the name is another file or none, and starts again. On
  Windows a file another run has open cannot be removed, so the holder closes it first and a
  failed removal leaves the empty file for the next run to use. Where the filesystem gives no OS
  file lock (some network filesystems), no weaker scheme stands in: a stale lock is not taken over
  (`why: takeover_unavailable`, and the refusal says to delete the lock by hand), while a run that
  finds no lock is unaffected. The lock itself appears with its holder's pid and deadline already
  in it: they are written to a file of the run's own, which is hard-linked to the lock's name
  (atomic, and refused when the name exists, as O_EXCL is). A lock created empty and written after
  read as `unreadable`, which is stale, to a run that looked in between; where no hard link can be
  made (FAT, some network shares) it still is. On Windows a process that has exited is dead even
  while a handle to it is open (its exit code is read): the Windows CI judged such a child alive
  and refused its stale lock as held. Not measured here: the Windows branch (`msvcrt.locking`,
  the removal of an open file) runs on the Windows CI job only, and a filesystem without `flock`.
  Code: `_common.runner._TakeoverSection`, `_OutputLock._take_over()`, `__exit__()`, `_create()`,
  `_pid_dead()`. Tests: `test_two_runs_taking_over_one_stale_lock_do_not_both_hold_it`,
  `test_a_run_paused_in_a_takeover_keeps_every_other_run_out`,
  `test_a_run_that_opened_the_section_before_its_name_went_starts_again`,
  `test_a_killed_holder_releases_the_takeover_section`,
  `test_without_an_os_file_lock_a_stale_lock_is_left_for_a_person`,
  `test_an_output_lock_is_never_seen_without_its_pid`,
  `test_a_finished_process_is_dead_while_its_handle_is_open`.
- **`batch.py` removes the directories it created when no item started** (A187): a refusal before
  the first item (`--jobs`, an output collision, a final path that is an input) and a glob that
  matches nothing leave no empty `out/` and `out/.work`, as a dry run already did. Once an item has
  started they stay, as before. `verify.py` makes a new `--out` folder before its `--report` guard
  (so a report inside it passes) and removes it again, with the parents it made, when that guard
  refuses the run; once a step has run the folder stays. Code: `batch.main()` (`item_started`),
  `verify.main()` (`started`). Test:
  `test_a_refused_batch_leaves_no_directories`.
- **A plan does not record `--json-brief`, and executing a plan drops it** (A181): `render.py`
  runs the planned tool with `--json` and reads the full document, whose `commands` the brief one
  replaces with a count. A plan written by 3.8.11 or earlier with the flag runs. Code:
  `_common.emit.is_output_shape_flag()`. Test: `test_a_plan_made_with_json_brief_executes`.
- **`render.py` still reads a stage's commands from its stderr, and joins a command whose quoted
  argument holds a line break** (A4). render's `commands` have always been read from there, the
  `[dry-run]` lines included, so the stderr stays the source and a `$` line whose quote is still
  open at its end takes the next line. Code: `_common.emit.stderr_records()`. Test:
  `test_a_command_with_a_line_break_in_an_argument_stays_one_command`.
- **A failed MCP call carries its failure document in `content` too** (A22): as the last text
  block, after the `<tool> failed (exit N)` lines. The server negotiates protocol 2024-11-05, which
  has no `structuredContent`; a client of that revision read only stderr lines. `structuredContent`
  stays. Code: `mcp/server.call_tool()`. Test: `test_mcp_failure_document_reaches_a_2024_11_05_client`.
- **The MCP server runs `tools/call` on one worker thread, in order** (A24). The loop that reads
  requests answers `ping`, `tools/list` and the prompts while a tool runs, and
  `notifications/cancelled` stops the call it names: its tool gets SIGTERM (stops its ffmpeg,
  removes the partial output) and no response is sent for it, as the protocol asks; a queued call
  that is cancelled never starts. Only a JSON-RPC 2.0 notification (`"jsonrpc": "2.0"`, no `id`)
  cancels; any other is ignored. Calls still run one at a time and answer in the order they came,
  and the next call starts only once a cancelled one's stop is done: on POSIX that is when its
  tool has exited, its handler having stopped its ffmpeg; on Windows its whole process tree is
  killed (see A183 above) and the worker waits for taskkill, up to 35 s. So a client sees no new
  interleaving between tool results and no two encodes at once, except on Windows when taskkill is
  missing or fails, where the cancelled tool's ffmpeg can run on beside the next call. The tool
  specs are built once, before the worker starts and under a lock: building them swaps argparse's
  `parse_args` and `sys.argv` process-wide, and a `tools/call` and a `tools/list` on a fresh server
  built them at once and ran a tool's `main()` for real (SystemExit). Every response, the -32700
  parse error included, is written under one lock. Code: `mcp/server.py` (`_call_worker`,
  `cancel`, `specs`, `_write`). Tests: `test_mcp_answers_a_ping_and_cancels_a_call_while_a_tool_runs`,
  `test_mcp_starts_the_next_call_only_once_a_cancelled_one_is_stopped`,
  `test_mcp_cancels_only_on_a_json_rpc_2_notification`,
  `test_mcp_tool_specs_are_built_once_when_first_used_from_two_threads`,
  `test_mcp_parse_error_goes_through_the_one_writer`.
- **The `hdr` prompt's `strip_dovi` picks the recipe** (A23): `true`, `1` or `yes` gives the
  `color.py --strip-dovi` message, `false`, `0`, `no` or nothing the `--to-sdr` one, and any other
  value is a JSON-RPC error naming it. Code: `_contract.mcp_prompt_get()` (`flags`). Test:
  `test_mcp_hdr_prompt_strip_dovi_changes_the_recipe`.
- **Cutting a word wider than the line takes time linear in its length** (A11). `_slice_atom()`
  measured every prefix of the remaining word for each piece, so a 4 KB hyphenated cue ran for
  minutes inside `caption.py`, where `--timeout` (a limit on each ffmpeg call) does not reach. It
  cuts the same pieces (compared on 20000 random strings of Latin, kana, Thai, combining marks,
  ZWJ emoji and flags) and measures only up to the first prefix that is too wide. Code:
  `_common.wrap._slice_atom()`. Test: `test_slicing_a_long_hyphenated_word_measures_linearly`.

## After 3.8.17 — leftovers of the old grouped issues (#510)

- **A still picture given where a clip is taken is shown for as long as the clip would be.** Read
  with a plain `-i`, an image demuxer gives one frame: `broll.py --insert logo.png --from 0.5` showed
  none of it (the trim starts past its one frame; with `--from 0` it was one frame through 3.8.11,
  and 3.8.12's `eof_action=repeat` holds it), and `grid.py CLIP logo.png` counted the cell as
  0 s long, so the grid was 0 s and the run ended in a traceback on the empty file. The still is opened with
  `-loop 1` and a `-t` that bounds it (the grid's length; for a cutaway, two of the loop's frames
  past the end of the trim, which starts at B's first frame at or after `--from` on the loop's own
  25 fps: `--from` plus the length cut off the one frame of `--from 0.041 --duration 0.033`), and
  a grid cell that is a still takes no part in choosing the grid's length; a grid of stills
  only is refused (`kind: input`), naming `insert.py`, which makes a clip of a still. A still has
  no material to run out of, so broll.py's check of B's length past `--from` skips it (image2
  gives a TGA a duration of one frame, and that was refused), and a grid whose first cell is a
  still is named `.mp4`, not after the still's extension. Still means
  what `probe._is_still()` means: one picture read by an image demuxer, so a GIF is a clip here
  as it is to `--image` (a one-frame GIF is still one frame). Code: `probe.is_still_input()`,
  `probe.still_loop_args()`, `overlay.main()`. The other way round, a still as `overlay.py`'s main picture under a
  looped `--image` is one picture out: with no duration to bound by `-t`, the overlay filter
  takes `shortest=1` (`-shortest` alone never ended it, and the run went on to its timeout).
  Test: `StillAsClipTests`. Seen and not changed here: `cut.py`, `join.py` and a render clip read a still as one frame
  (`cut.py STILL --start 0 --end 2` writes 0.04 s with `verified: true`, as it clamps any `--end`
  past an input; `join.py --transition none` joins one frame; a render clip with `in`/`out` on a
  still is cut to one frame and then refused by the join's transition). What a still means
  there (refused, naming `insert.py`, or held for the window asked) is a decision of its own:
  for `cut.py` it is refused since #531 ("After 3.8.23"), and for `join.py` since the decision
  recorded in "After 3.9.2".
- **A font file the caller names is refused when it is not there or not a font**, from
  `--font-file` (`overlay.py`, `graphics.py`) and from a brand file's `font_file` (those two and
  `caption.py` when it burns, which hands libass its folder; `--mode mux` draws nothing). On FFmpeg 6.1.1 drawtext that cannot load its
  `fontfile=` asks fontconfig for a default face and exits 0 (a missing file did the same), and
  libass finds no face in the folder and does the same: the run completed with
  `font_used.substituted: false`. The file is read by its first bytes (TrueType, OpenType/CFF,
  collection, WOFF/WOFF2, Type 1, BDF, PCF), not its extension; a `.dfont` and a gzipped PCF pass
  by name, unread. A brand `font_file` is checked only where text is drawn with it, so
  `overlay.py --image --brand`, `graphics.py --template progress` (a bar, no text) and
  `caption.py` with no input video (it writes the SRT only) do not read it. Code: `fonts.require_font_file()`. Test:
  `test_a_font_file_that_is_not_a_font_is_refused`.
- **A brand file key no tool reads is refused** (`kind: input`, with the nearest known key), in
  every block: the top level, `colors`, `caption`, `styles` and `styles.caption` (the last two take
  the same keys, since `brand_caption_style()` merges them). render.py has refused an unknown
  project key since review 9 for the same reason: a misspelt `"safe_margn"` drew the default.
  `colors.accent` is accepted: `BRAND_DEFAULTS` and `examples/brand.json` carry it as a palette
  entry, though no tool draws with it. `loudness` is read by no tool (A107) but the example
  carried it until 3.8.8, so it is not refused: it gets a note. Code: `decision.BRAND_KEYS`,
  `check_brand_keys()`. Test: `test_a_brand_key_no_tool_reads_is_refused`.
- **`report.py --pack` takes the table `render.py --template all` writes, and nothing else.** The
  first table's header must be that table's five columns in its order, the line under it its
  five-column delimiter row, and every later line of the table is a row that must have five
  cells (a row of empty cells, `| | |`, is a row, not a second delimiter); a later table in the
  file ends the pack instead of joining it. Any Markdown with a
  table was rendered and reported `verified: true` (the step only says the HTML was written).
  Code: `report.PACK_HEADER`, `pack_report()`. Test: `test_report_pack_takes_only_the_pack_table`.
- **A silent output's loudness step is pinned by a test.** `loudness.py` has reported it not ok
  with `reason: not_measured: ...` and no `lufs` since 3.6.7. No real input reaches it (a silent
  or too-short input is refused before the encode), so the test replaces only the output's
  measurement, in a child process. Test: `SilentOutputLoudnessTests`.
- **Left for a product decision then:** the render filter check, look.py's HDR path, the cut
  dry run and the four #429 items. All seven were decided after 3.8.20 (below).

## After 3.8.18 — side inputs as outputs, the blurred pad's chroma and sequence's frames (#522, #527, #529)

- **An output named like a file the run reads but does not hand to ffmpeg as `-i` is refused**
  (#522), `kind: input`, `reason: output_is_input`, before anything is written and in a dry run
  too. `run()`'s guard compares the output with the command's `-i` inputs only, and
  `sync.py REF SECOND --trim-second` writes from SECOND alone: REF named `SECOND_synced.mp4` (the
  default output name) or given as `-o` was replaced with `--overwrite`. The sweep of that class
  (each side-file flag given again as `-o`, with `--overwrite`) found the same in
  `cut.py --snap-source`, `metadata.py --chapters`, `graphics.py` and `overlay.py` `--brand` and
  `--font-file` (a brand file's `font_file` too), `silence.py --words` and `--filler-words`, and
  `join.py --list`; each tool now compares its output with those files once it is known
  (`refuse_output_is_input()`, the tool-level twin of the guard). Already refused, and not changed:
  `caption.py`'s cue, SRT, ASS and brand files, `audio.py --music`, `--effects` and `--replace`,
  `waveform.py --srt`/`--text`, `render.py --template`'s side files, `sync.py --replace-audio`.
  A LUT (`color.py --lut`) is not replaced: ffmpeg picks no muxer for a LUT's extension (`.cube`,
  `.3dl`, `.dat`, `.m3d`, `.csp`) and `lut3d` does not read a LUT named like media, so both fail
  as `kind: ffmpeg` with the LUT unchanged. Not measured here: another case of the name on a
  case-insensitive volume when the output does not exist yet (`same_file()` compares resolved
  names until both files exist). Test: `test_an_output_named_like_a_file_the_run_reads_is_refused`.
- **A side file is never written over a file a brand file names** (review of #534). The side-file
  guards compared a side output with the brand file but not with its `font_file` and `logo`:
  `graphics.py --write-ass`, `caption.py --write-srt` and `--write-ass`, and
  `render.py --template --write-project` with `--overwrite` replaced the brand's font (or logo)
  with the text they write. graphics.py now guards with the font it draws with, caption.py with
  the brand's font_file and logo, and render.py's `--write-project` with every file the project
  reads (`project_input_files()`, which already followed the brand to them). `load_brand()`
  adds the font_file and logo to the files a `--plan` binds, so a plan is not written over them
  either; caption.py hands libass the font's folder, so its plan named no font. The sweep (each
  side output named like each side input, brand-named files included, with `--overwrite`) found
  every other guard holding: graphics and overlay `--plan`, cut, metadata, join, silence and sync
  `--plan`, silence `--edl` and `--timemap`. Seen and not changed here (fixed by #535, "After
  3.8.19"): `waveform.py --brand` failed on every brand file, the default one included, because
  the brand background `101418` is a bare hex colour starting with a digit, which
  `validate_color()` refused although "After 3.8.16" says six bare hex digits pass. Test: `test_a_side_file_never_replaces_a_brand_files_font_or_logo`.
- **`verify.py` never replaces a cue file without `--overwrite`, and the caption step fails on it
  instead of the run being refused** (#522). Through 3.8.18 the `<stem>_cues.txt` it writes in
  `--out` was replaced unasked. Without `--overwrite` an existing one is left as it is and the
  caption step is a failure `kind: input`, `reason: output_exists`, with the other steps run: a
  rerun into the same `--out` already fails each step on its own existing output ("After 3.8.13"),
  and the cue file belongs to the caption step. A link or a folder at the name is never written
  through, `--overwrite` or not (a folder was a traceback). A `--report` that names a file the
  steps write (`OUT/clip_cut.mp4`, the cue file, a caption sidecar) is refused before any step
  runs, `reason: output_path_taken`; it replaced that step's output once the steps had read it.
  Test: `test_verify_leaves_an_existing_cue_file_and_keeps_its_report_off_its_own_names`.
- **A blur's chroma radius is evaluated by boxblur on the chroma planes' own size** (#527).
  `pad_filters()` (`fit.py --fit blur`, `--pad-fill blur`, `waveform.py --image-fit blur`;
  `export.py --pad-fill blur` too, though its presets' frames are 720 px or more and never meet
  it) clamped the radius to the luma plane and gave chroma the same one: a 160x120 source to 9:16
  (a 68x120 frame, 34x60 chroma) failed inside ffmpeg. `redact.py` had its own chroma bound,
  written for 4:2:0, and a 4:1:1 or 4:1:0 source (DV) failed a 30x30 region. Both now hand
  boxblur an expression on `cw`/`ch`: the radius asked for (the luma one for a pad, half of it, at
  least 1, for redact), or the largest the plane holds, `floor((min(cw, ch) - 1) / 2)`, or 0. On
  a frame large enough nothing changes: the pad's chroma radius is still the luma one, and
  redact's output on 4:2:0 and 4:4:4 is the same pictures (compared frame by frame on odd and even
  regions). Not verified here: FFmpeg 7.1, which refuses a radius 6.1 took; the bound is the one
  redact.py's 4:2:0 numbers already passed there. Code: `_common.decision.boxblur_chroma_radius()`.
  Test: `test_a_blur_holds_every_plane_on_a_small_or_subsampled_frame`.
- **`fit.py --smooth interpolate` makes its frames at `--fps` when given** (#527): made at the
  source's rate and then put on `--fps 60` by the fps filter, every other frame of a 2x slow
  motion was a repeat (117 distinct pictures of 240; 232 now). `--smooth blend` is not changed:
  blending two neighbours makes one new picture per gap whatever the rate (119 distinct pictures
  of 240 with the blend at 30 or at 60). A VFR source whose speed change puts the picture on the
  grid now says "source looks variable-frame-rate" as one conformed by the fps filter does.
  Test: `test_fit_interpolates_slow_motion_at_the_rate_it_delivers`.
- **`sequence.py` decodes every frame once before the encode and refuses one that does not
  decode** (#529), `kind: input`, `reason: still_unreadable`, naming the frames (`frames`,
  `frames_unreadable`, `frames_total`). Only the first frame was probed, and a later text file
  named `.png` or a truncated PNG was dropped by the decoder while the fps filter showed the frame
  before it: the run completed with a picture missing. The check is one ffprobe over the concat
  list the encode reads, so it costs one more decode of every frame, and it runs under `--dry-run`
  too (ffprobe, not ffmpeg: the contract's dry-run note says so). When ffprobe fails or reads
  nothing back, the frames are not called bad: a note says they could not be checked and the
  encode runs as before; the contract's dry-run note and the reason's text say so too. Code:
  `sequence.undecodable_frames()`. Tests: `test_sequence_refuses_a_frame_that_does_not_decode`,
  `test_sequence_frame_check_that_cannot_be_made_calls_no_frame_bad`.
- **Checked and not changed:** `speedramp.py` with a sound whose sample rate reads 0 skips the
  per-segment sample count, but no run reaches a written file: a Matroska file patched to rate 0
  probes as 0 and its sound does not decode (FFmpeg 6.1.1: "Value inf for parameter
  'time_base'"), so the run fails in ffmpeg. `verify.py`'s caption step stopped at its
  `--timeout` leaves the `.srt` and `.ass` it had written: they are deliverables, not partial
  files ("Outputs and files": caption.py leaves its sidecar by design); removing them on a failed
  burn would be a decision of its own. The colour-name table is compared with the installed
  ffmpeg's `-colors` by `test_an_unknown_colour_name_is_refused_before_ffmpeg` on every CI job, so
  on 6.1, 7.1, 8.x and 9.x (all fifteen test jobs of #530 passed).

## After 3.8.19 — a brand colour that starts with a digit (#535)

- **Six or eight hex digits are a colour whatever the first digit is, bare or after `0x` or `#`,
  and seven are refused** (#535). `validate_color()` took a bare word only when it started with a
  letter, so `0B1D2A` (the example brand's background) and `101418` (the default one) were
  refused by every flag it checks, while `FF6A00` passed. FFmpeg 6.1.1 reads them all:
  `color=c=0B1D2A`, drawtext `fontcolor=0B1D2A` and `drawbox=c=0B1D2A` draw that colour (to
  within the YUV round trip's one step), as they do `0B1D2AFF` and `0B1D2A@0.5`, and the same
  commands with `0B1D2` or with seven digits fail ("Invalid 0xRRGGBB[AA] color string"), with or
  without `0x` or `#`. The prefixed forms took six
  to eight digits, so seven passed the check and failed inside ffmpeg as kind `ffmpeg` after a dry
  run that had completed; they now take six or eight, as the bare form does. The check is still
  the filter-graph guard: what passes is a name (a word that starts with a letter and is in
  ffmpeg's table), six or eight hex digits, optionally `@` and an alpha from 0 to 1, and nothing
  else (`0B1D2A,drawtext=...`, `0B1D2A:x=1`, `0B1D2AZ` are refused, `kind: input`). The refusal
  says the digits may be bare. The test asks the installed ffmpeg first, so a version that reads
  these otherwise fails it on that CI job; only 6.1.1 was run here. Code:
  `_common.color._COLOR_TOKEN_RE`, `validate_color()`. Test:
  `test_six_or_eight_hex_digits_pass_whatever_the_first_digit`, which also runs a dry run of every
  flag `validate_color()` checks (the table is compared with the calls in `scripts/`).
- **`waveform.py` reads a brand colour as the other brand tools do** (#535): through
  `color_hex()`, as `caption.py` and `graphics.py` read theirs (`overlay.py` reads no brand
  colour), so `#0B1D2A`, `0x0B1D2A` and `0B1D2A` in a brand file give the same `--color` or
  `--background`. Before, the brand's value was copied as written, and `waveform.py --brand`
  failed on `examples/brand.json`, on a brand that leaves its colours to the defaults, and in
  `render.py`'s audiogram stage with a brand. A brand colour that is a name or eight digits is now
  refused there, `kind: input`, as `graphics.py` and `caption.py` already refused it; `--color`
  and `--background` given on the command line still take any colour `validate_color()` takes.
  The sweep ran every tool that takes `--brand` (waveform, caption, graphics, overlay,
  `render.py --template` and a `render.py` project with an audiogram) with `examples/brand.json`
  and with a brand whose every colour starts with a digit, dry run and real run: only waveform
  and the audiogram project failed before, all complete now, and waveform's picture is the brand
  background. Test: `test_every_brand_tool_runs_with_the_example_brand`.
## After 3.8.20 — the decided items of #510

- **A real `render.py` run checks every stage's filters and encoders before the first stage, by
  running its own dry run.** A stage finds a filter or an encoder the build lacks when it runs
  (`_check_build_components()` reads the command that stage builds), so a real render cut and fit
  the footage and then failed at the graphics stage of a build without drawtext, while its
  `--dry-run`, which runs every stage's own dry run, was refused before anything encoded. The
  project is known before the first stage, but what each stage needs is decided inside the stage
  (graphics' text route, an HDR source's tone map, a preset's encoder), so the check is not a
  second list of filters per stage kept in render.py: the real run runs the same command line with
  `--dry-run`, and when that is refused with `filter_missing` or `encoder_missing`, the real run is
  refused with the same kind, message, `reason`, `details`, hint and `stage`, its `commands`
  empty. Any other outcome of the dry run (a refusal for another reason, a timeout) is left to the
  real run, which decides on the files as they then are: a dry run plans on stubs for pending
  intermediates and is refused in cases a real run completes (the `.ogg` batch join under "Dry run"
  above). The cost is one dry run, measured at about 1 s for a template render of a 60 s clip on
  FFmpeg 6.1.1, against 59-78 s for the render; a project whose dry run measures (a silence stage,
  a `--snap beats` clip) measures twice. A filter a stage chooses on a measurement of an
  intermediate the dry run does not have yet (it is pending) is still found at that stage. A pack
  (`--template all`) is a render per destination, and each checks itself; the pack renders the
  other destinations as before. `waveform.py` with `--title`, `--srt` or `--text` is the same
  shape (it encoded the visualisation, then its title stage was refused) and does the same. Code:
  `runner.refuse_missing_components_first()`, `render.main()`, `waveform.main()`. Test:
  `MissingComponentFirstTests`. Siblings seen and not changed: a `batch.py` recipe of steps runs
  every item's earlier steps before the step that needs the filter, item after item (a `project`
  recipe is a render and checks itself); a batch dry run per item, or of the whole folder, before
  the first real step is a cost per item, and whether one item's missing filter refuses the batch
  or only that item is a decision of its own. `export.py --normalize` runs `loudness.py` after the
  encode, but loudnorm is part of every build. `report.py` records a contact sheet that could not
  be drawn and goes on ("`report.py` accounts for every section" above).
- **`look.py` on an HDR source without zscale is refused, dry and real (`filter_missing`).** Its
  tone map is `hdr_to_sdr_chain()`, the one `color.py --to-sdr` uses, and on a build without
  zscale the only other filters that read PQ or HLG are GPU ones (libplacebo, `tonemap_opencl`,
  `tonemap_vaapi`), which need a device this skill does not set up and cannot count on;
  `colorspace` has no PQ or HLG transfer. A sheet drawn from the HDR frames as they are would show
  colours the source does not have, so the refusal stands, and `report.py` records it for its
  contact sheet. Code: `look.py` (the tone-map chain), `_common/color.py`. Test:
  `test_an_hdr_contact_sheet_without_zscale_is_refused`.
- **`cut.py --dry-run` does not read packets for a single segment, and says what a real run may
  still change.** Where a single stream copy lands is measured from the written file
  (`cut_one()` judges its length against `--tolerance`); reading the packets in the dry run would
  make every plan as slow as a cut's own measurement, and the plan would still not know a copy that
  fails or loses a stream. So a plan of `mode: copy` names in `possible_reencode_reason` the
  `reencode_reason` values a real run may add, which turn it into `hybrid`: `tolerance` when a
  copied part, video or audio-only, is judged by its written length (an audio-only copy was left
  out until the review of #537; not under `--tolerance -1`, and not for a
  `--segments` part whose end is snapped to a keyframe: the `--segments` dry run reads the packets
  and judges those parts as a real run does), `copy_failed` and `stream_lost` on every copy, and
  `concat_fallback` on a `--segments` copy join; a plan of `mode: smart` names `smart_fallback`,
  since its checks run on the written cut (`smart.checks` is null). A `notes` line says the same in
  words. It is `[]` in a real run and for a plan that already re-encodes. `batch.py --dry-run`
  counts the plans in `cut_stream_copy` and its summary line says they are planned stream copies a
  real run may still re-encode, not that they stayed lossless. Code: `cut.possible_reencode_reason()`,
  `cut.possible_reencode_note()`, `batch.main()`. Tests:
  `test_a_planned_copy_says_a_real_run_may_re_encode_it`,
  `test_smart_cut_copies_the_whole_gops_and_reencodes_only_the_ends`,
  `test_batch_reports_cuts_stream_copy_vs_hybrid_rate_across_the_folder`. Sibling seen and not
  changed: `color.py --retag --dry-run` reports `reencoded: false`, and a real run re-encodes when
  the copy fails or ffprobe still reads the old tags on the written file; its plan names no such
  possibility.
- **A batch step that writes without naming `{out}` stops the batch (#429 item 1).** Every step
  runs with `--json`, and its document's `output` is the file it wrote (or, under `--dry-run`,
  would write): null for a step that only reads (`check.py`, `probe.py`, `cropdetect.py`,
  `scenes.py`, `verify.py`), a path for every writing tool with no `-o` (its default output beside
  its input). A step that names neither `{out}` nor an `-o` of its own and reports one is refused
  (`kind: input`, `reason: step_writes_without_out`, `details.file`) and no later item starts
  (`skipped: "recipe_refused"`): its file is not what the next step reads (that is still this step's
  input) nor what is delivered, and the next pass took `<stem>_meta.mp4` beside the source for a new
  item. The tool's own document is the rule, not a list of which tools write under which flags
  (`loudness.py --measure-only` writes nothing; `loudness.py` does). A dry run finds it with nothing
  written; a real run has written that one file (items in flight under `--jobs` one each) and the
  refusal names it; it is left where the tool put it. A step that names `-o` itself
  (`look.py {in} -o {in}.png`, a contact sheet beside each source) placed its file on purpose and is
  not refused. Code: `batch.wrote_without_out()`, `names_output()`, `process()`, `main()`. Test:
  `test_a_batch_step_that_writes_without_out_stops_the_batch`.
- **`render.py` delivers its captions stage's SRT; `batch.py` names a side file it loses (#429
  item 2).** A `captions.text` cue file is turned into an SRT by `caption.py`, beside the stage's
  intermediate in the work directory, and was removed with it. It is now `<output>.srt`
  (`caption_srt`), guarded as a side file of the output before the first stage (an existing one
  refused without `--overwrite`, never an input or the output) and placed under the output's lock
  (`place_output()`). Nothing after the captions stage re-times the picture except the export's
  trim to a platform's maximum, so the SRT is not delivered (`caption_srt_not_delivered`, reason
  `timeline_changed`) when the export reports `trimmed` or the delivery is more than 0.25 s shorter
  than the captioned stage; nor when the stage came from `--cache`, which keeps the video only
  (reason `cached`). Captions from `srt` or `ass` are the caller's own files and are not copied. In a
  batch a later step may re-time anything, so a side file a step before the last writes beside its
  intermediate is not delivered: a `batch_side_file_not_delivered` skip names it, and only the last
  step's side files land beside the output, as before. Code: `render.deliver_caption_srt()`,
  `batch.work_files()`. Tests: `test_a_render_delivers_its_captions_srt_beside_the_output`,
  `test_a_batch_records_a_side_file_lost_with_an_intermediate`.
- **A side input built from `{in}` is keyed per item (#429 item 3).** `side_inputs_key()` keys the
  literal paths a recipe names; a path built from a placeholder was skipped, so an edited
  `{in}.png` served the old output. The first step's `{in}` is the item's source, so its derived
  path is resolved and keyed by content per item (`item_side_inputs_key()`; a recipe with none keeps
  its old key, so existing caches still hit). A later step's `{in}` is an intermediate that does not
  exist before the item runs and cannot be keyed: such an item is never served from the cache nor
  stored (`cache_miss: {reason: side_input_unresolved, step, argument}`). A rerun after the edit
  re-encodes and, as for an edited source, replaces the earlier output only with `--overwrite`
  ("left by an earlier run, is refused as before", above). The sweep found the same class in
  `render.py --cache`: a stage's key hashed the `--brand` file's bytes, not the logo and font file
  it names, so a font replaced under its name was served; those are keyed now
  (`render._brand_files_key()`, only for a stage with `--brand`). Test:
  `test_a_side_input_built_from_in_is_in_the_batch_cache_key`.
- **An interrupted render or batch says what it kept (#429 item 4).** A render stage that writes
  outside the work directory (the export writes the delivery itself) has its destination's
  identity (size, mtime_ns, inode) recorded before it starts (`runner.watch_destination()`); after a
  stop, a file there that is not that file is this run's and is reported kept, unverified, by the
  #415 rule ("kept, without the step that was stopped", `output`), while the caller's own file,
  untouched or restored by the stage's cleanup, is not claimed. Recording the destination as written
  up front would have claimed that file. Ctrl-C during export's `--normalize` loudness pass said
  "nothing was written" with the export's encode at the output. The work directory, removed at exit
  unless `--keep`/`--work`, is in `STATE.temp_dirs`, and its stage files are no longer listed as
  "still on disk". A batch row stopped in its last step carries `kept` for such a file at the
  final path. The output lock and its `.takeover` file left beside a stopped child came from a
  second signal: a Ctrl-C reaches every process of the group and the parent then sends SIGTERM, and
  the handler raised again from inside the lock's `__exit__`; a second signal during the stop is now
  ignored (`runner._on_signal()`), and the parent's SIGKILL after `STOP_GRACE` still ends a cleanup
  that hangs. A process killed outright (SIGKILL, a power cut) still leaves its lock; the next run
  takes it over as stale (its pid is dead). Code: `runner.watch_destination()`,
  `kept_deliverables()`, `written_on_disk()`, `_on_signal()`, `render.sh()`, `batch.process()`.
  Tests: `test_an_interrupted_stage_reports_the_file_it_wrote_and_not_the_work_directory`,
  `test_a_second_signal_during_the_stop_does_not_leave_the_lock`,
  `test_ctrl_c_during_the_export_s_loudness_pass_reports_the_kept_delivery`. Seen and not changed:
  `verify.py` runs its steps for real into its own `--out` directory (its stop was not tried here);
  `multicam.py` and `sequence.py` run one ffmpeg command, whose partial output run() removes.
- **The review of #537: four more places the same decisions reach.**
  - *The flags a parent adds go before a `--`.* The up-front check ran
    `render.py ARGV --dry-run --json`; with the input after `--` the two flags were positionals, the
    child was refused (exit 2, no document) and the check was skipped with only an info line, so
    the stages ran up to the one that lacks the filter. `runner.with_flags()` puts added flags
    before the first `--`; batch's steps (a recipe step with `--` was refused: `unrecognized
    arguments: --dry-run --timeout 1800 --json`), `render.py`'s executed plan and the MCP server's
    raw `argv` use it too. Tests: `test_a_real_run_is_refused_before_its_first_stage_as_its_dry_run_is`
    (the `--` case), `test_a_step_with_a_double_dash_still_gets_the_shared_flags`.
  - *A `FILE:SUFFIX` side input is keyed by FILE.* `caption.py --srt FILE:LANG` reads FILE
    (`split_srt_lang()`); batch's keys (literal and `{in}`-built) hashed the whole token, which is
    no file, so an edited subtitle file kept its key. `batch.side_input_file()` takes the token when
    it is a file, else the part before the last colon when that is one. No other tool takes a
    file with a suffix (multicam's `--cuts` and speedramp's spans are times). Test:
    `test_a_file_lang_side_input_is_keyed_by_its_file`.
  - *An entry stored before the `{out}` check is not served for a recipe that needs it.* A row of
    `["metadata.py", "{in}"]` cached as `written: false` was served, so the recipe never met
    `step_writes_without_out`. An entry now records `output_checked`; for a recipe with a step that
    names no `{out}` an entry without it is a `cache_miss` (`entry_predates_output_check`), runs once
    and is stored again. A QC recipe (`check.py` over a folder) measures again once after the
    upgrade; a recipe whose steps all name `{out}` keeps its entries. Test:
    `test_a_cache_entry_from_before_the_output_check_is_not_served`.
  - *Interrupted reports.* A `project` recipe item is a render that writes the final path, and is
    watched as a last step is (`kept`); batch's own handler ignores a second signal as
    `runner._on_signal()` does (the exit code was the SIGTERM's for a Ctrl-C, and the stop ran
    again); render watches the delivery even when `--work` is the folder that holds it (it was
    taken for an intermediate). verify.py and multicam.py use the runner's handler, and the MCP
    server sets none. Tests: `test_ctrl_c_during_the_export_s_loudness_pass_reports_the_kept_delivery`
    (the project subtest), `test_a_second_signal_to_batch_keeps_the_first_signal_s_report`,
    `test_an_interrupted_stage_reports_the_file_it_wrote_and_not_the_work_directory` (the `--work`
    case).
  - *An audio-only copy names `tolerance` in its plan.* It is judged by its written length like a
    video copy but returned before the dry run recorded that (`cut.cut_one()`); a `--segments`
    audio join's parts go the same way. Test: `test_a_planned_copy_says_a_real_run_may_re_encode_it`.
- **The second review of #537.**
  - *A batch step's brand assets are keyed.* A step's `--brand` file, literal or built from `{in}`,
    was keyed by its own bytes; its `logo` and `font_file` (resolved against the brand file's folder,
    as `load_brand()` does) are keyed now too, through `decision.brand_asset_files()`, which
    `render.py`'s stage key also uses. A project recipe's key already had them
    (`project_input_files()`), and a `--plan` fingerprints them. Test: `test_brand_assets_are_in_the_batch_key`.
  - *The key is made again before an item is stored.* It was made when the pass looked the item up;
    a side input edited while the item waited or ran was stored under that key, and putting the old
    file back (a copy that keeps its mtime) served an output made from the edited one. `store()`
    makes the key again from the files as they are and stores nothing when it differs
    (`batch_cache_inputs_changed`); the next run makes the item again. Test:
    `test_an_item_whose_side_input_changed_while_it_ran_is_not_cached`.
  - *A side delivery is never the stopped run's `output`.* `render.py` marks the SRT it delivers as
    a side delivery (`mark_delivered(side=True)`), so a stop in the chapters or check stage reports
    the video as `output`; the message still names both. Test:
    `test_a_stop_after_the_srt_is_delivered_names_the_video_as_the_output`.
  - *The rows carry what the summary names.* `batch.py --dry-run` rows carry
    `cut_possible_reencode_reason`, per `cut.py` call. The contract's `possible_reencode_reason`
    says the dry run does not write or measure the output cut; a `--segments` dry run does read the
    source's packets.


## After 3.8.21 — variable-frame-rate sources in reverse, speedramp and freeze, and the timeline of several clips (#523, #526)

Measured on `make_vfr_flash_beep()`'s clip (30 fps with two runs of six frames dropped, from 0.1 s
and from 2.1 s, so 27 fps on average; a two-frame flash and a 40 ms beep every second from
0.5 s) and on `make_flash_beep()`'s constant 30 fps one, FFmpeg 6.1.1 only. The 18-19 ms by which
every flash of the VFR clip follows its beep is the 27 fps grid's own (the flash at 0.5 s lands on
the slot at 0.519 s, "After 3.8.14").

- **A VFR picture is conformed before `reverse`, each slot taking the last frame that starts
  before the slot ends** (#523). `reverse` hands its frames the forward timestamps in order, so a
  reversed VFR picture kept its gaps where they were in forward time: every flash came 0.19 s
  after the reversed beep, and 0.23 s late with `--no-audio` (whose picture ran 4.074 s). With
  `fps=R:round=down` ahead of the reversal the reversed picture is the conformed forward one
  mirrored, and the flashes land on the 27 fps slot at or after where they belong (a flash that
  ends at s + 2/30 starts at 4 - s - 2/30 reversed: 0.444 s for 0.433), 14-16 ms before the
  reversed beep (which starts 0.04 s before the end of the source's, so the fixture itself puts
  them 27 ms apart), in a 4.000 s picture, with and without sound. The nearest frame to each slot,
  the forward conform's rule, is not used: the last slot's nearest frame can be the one before a
  real last frame that starts after the slot's middle (1.983 s on a 1/60 grid against a slot at
  1.951 s), and the reversal then opened on it, which
  `test_reverse_of_a_variable_rate_clip_opens_on_its_last_frame` pins (the reason this was left
  open in "After 3.8.14"). A `settb=AVTB` follows the conform: its output's time base is one frame,
  and the trim after it rescales its half-frame bound to that base (see freeze.py below). The
  constant-rate path is unchanged. Code: `reverse.main()`. Tests:
  `test_a_reversed_variable_rate_picture_keeps_its_sound`,
  `test_reverse_of_a_variable_rate_clip_opens_on_its_last_frame`.
- **Every `atempo` chain is led by a window and a half of silence and cut by a window after;
  a 1x `speedramp.py` segment is not retimed** (#523, #541 review). `atempo` lays its first
  window down without retiming it and sets everything after it about half a window early, the
  window being the power of two at or above sample_rate / 24 (1024 samples at 44.1 and 48 kHz,
  256 at 8 kHz, 2048 at 96 kHz; measured at each): `speedramp.py`'s beeps came 21.3 ms early at
  1x and 40 ms at 0.5x on a constant-rate clip, `fit.py --method speed`'s 17-25 ms (1.11x,
  0.91x), `audio.py --tempo`'s 10-31 ms (1.5, 0.8, 3) and 89-123 ms at 0.3 (two stages), and a
  1x track ended 21 ms short. That is the cause the 3.8.16 entry gave as "atempo" and left.
  `atempo_chain_with_lead()` puts half a window of silence per stage ahead of the first one
  (each stage's half window of its own input is the earlier stages' tempo product times that
  many of the chain's input) and a whole window more, then cuts that window off the output at
  the chain's tempo and moves its timestamps back by it, so a track that starts after 0 keeps its
  start. The extra window is the review's finding: with the half window alone the chain's first
  window, which atempo fades in, lay over the input's first 21 ms, and a 10 ms tone there came out
  7 dB down at 1x and was gone at 1.5x and 2x (`speedramp.py`, `fit.py --method speed` 2x and
  `audio.py --tempo 1.5`); it now keeps its -1.9 dBFS peak at every factor tried (1, 1.5, 2, 0.5,
  0.3), a slowed tone spread over the windows its new length takes. Through a single stage
  (0.5x to 3x) the beeps' mean onset is within 5 ms of where the retiming puts them in every case
  above and a single beep within half a 30 fps frame (12.6 ms at 0.91x; atempo places its
  windows by the content). Through a chain below 0.5x the claim is narrower: a 40 ms beep slowed
  to 0.3x is laid down as several grains, the first of which can sit anywhere in a window that
  holds the beep's start, so its onset is within one window (2048 samples, 43 ms at 48 kHz) of
  its place, no closer: -34 to +26 ms (0.3x on FFmpeg 6.1.1: 0, -24, -34, -14 ms; 0.25x: +26,
  -27, -8, -7; macOS's 9.0.2 at 0.3x: -1, -23, -34, +7, its third beep read as four onsets),
  where the systematic shift was 70-155 ms early. The test takes, for each beep, the first onset
  from 0.25 s before its place to a window after the stretched beep ends, and says "not
  measured" when there is none; a failure prints the onsets, the chain and `ffmpeg -version`.
  The other CI versions (7.1, 8.0.1, Windows' 9.0.2) passed the earlier nearest-onset form. Each
  beep is held to the bound of the segment it is in: the two 3x beeps after `speedramp.py`'s
  0.25x segment are held to half a frame (7 and 8 ms early on 6.1.1), not to the chain's window,
  and the 5 ms mean is read only where all four beeps go through one stage. A 1x `speedramp.py` segment is cut and not retimed, so its
  sound is the source's to the sample; `fit.py --method speed` within 1e-4 of 1x and `audio.py
  --tempo 1` already added no `atempo`. One lead for the chain, not one per stage: an `adelay`
  between two stages made FFmpeg 6.1.1 fail a graph that joins the result with `concat`
  ("Invalid data found when processing input", `speedramp.py --segment 0-2:0.25 --segment
  2-4:3`). `speedramp.py` measures its sound on the VFR clip within half a frame now (its row in
  `test_a_variable_rate_conform_keeps_each_picture_within_half_a_frame` checks the sound too),
  and `test_speedramp_segments_hold_the_frames_between_their_retimed_ends` holds the picture to
  its slot and the sound to its place (within 4 ms) separately: their difference adds the grid's
  18.5 ms to any sound offset. `fit.py --method speed` still ends a retimed track on the
  millisecond `-t` ("After 3.8.11"): 3 s to 1.23425 s still writes 59392 AAC samples. A rate that
  is not known (a dry run's pending input) leaves the chain as it was. The window rule is
  af_atempo's own; it was measured on 6.1.1 only, and the CI jobs on 7.1, 8 and 9 run the tests.
  Code: `decision.atempo_lead()`, `atempo_chain_with_lead()`, `fit.atempo_chain()`,
  `speedramp.main()`, `audio.main()`. Tests: `test_a_tempo_change_keeps_each_sound_where_it_belongs`,
  `test_a_tempo_change_keeps_an_attack_at_its_start`.
- **`freeze.py` conforms a VFR picture as it is decoded when it holds a frame inside the clip,
  and works on the delivered grid** (#523). On the source's own frames the head segment ended at
  its last frame's nominal duration, so with `--at` inside a gap the hold, and everything after
  it, started the rest of the gap early against the sound, which is cut at `--at`: 56 ms at
  `--at 0.15`, 93 ms at `--at 2.2`, with the picture 4.926 and 4.889 s long for 5. With
  `cfr_at_input()` every frame time (the cut, the hold's frame, the hold's count) is on the 27 fps
  grid, the flashes after the hold land within half a frame of their beeps, and the picture holds
  every slot (135 frames). The conformed picture's time base is one frame (1/27 s) and `trim`
  rescales its bound to it, so a half-frame bound written to the microsecond (3.907407 for --at
  3.9) became frame 105 itself: that frame was cut from the head and held in place of frame 106,
  two frames short. A `settb=AVTB` after the conform keeps the bounds between the frames. The
  grid is laid from the picture's start (`setpts` to 0 ahead of the `fps` filter, the picture's
  trims counted from there): the filter lays it from the clock's 0, and every time above is
  counted from the start, so a picture that starts 50 ms after its sound came out a frame early
  after the hold (flash minus beep 68 ms before it, 31 ms after; on 3.8.20 `--at 2.2` moved it
  73 ms). The joined picture's timestamps are then rebuilt from its frame count (`setpts=N*...`
  ahead of the closing `fps`, as `speedramp.py` does): FFmpeg 6.1.1's video `concat` gives a
  one-frame segment no length, so a hold of one frame (`--hold 0.04` at 30 fps, `--hold 0.05` on
  the 27 fps clip, on constant-rate sources too and on 3.8.20) lost its frame and the rest of the
  picture ran a frame before its sound (33 ms on the 30 fps clip; #541 review). The picture is not
  moved back after the conform: a `setpts` there left its frames no
  duration and no rate from FFmpeg 7.0, and the hold's `tpad` after it cloned nothing (109 frames
  for 135 on 7.1, in CI; 6.1.1, 8.0.1 and 9.0.2 wrote 135). A hold at the start or
  the end of the clip already ran through `with_cfr()` and is unchanged. (After 3.9.0 a hold at the start is conformed first,
  #538.) Code: `freeze.main()`,
  `decision.cfr_at_input()` (its `origin`). Tests: the `freeze-gap` rows of
  `test_a_variable_rate_conform_keeps_each_picture_within_half_a_frame`,
  `test_a_variable_rate_freeze_keeps_every_frame_of_its_grid`.
- **Swept for the class "a tool that moves time on a VFR source puts its picture more than half a
  frame from its sound"**, and for "a sound retimed by atempo is early". `python3 tests/sweep.py
  VFR --baseline CFR` (the two fixtures above) printed no row that differs, before and after the
  change: the defects are in the output, not in what a tool says, so each tool that moves time
  was also run and measured on both clips (flash against beep, and the picture's length). Within
  half a 27 fps frame and not changed: `join.py` (`--transition none` and `fade`), `broll.py`,
  `silence.py`, `loop.py --times` and `--crossfade`, `pad.py`, `fit.py --method trim`, `cut.py
  --segments` across a gap, and `freeze.py` at the start or the end. Left, each with its own
  cause: `cut.py --start` on a VFR source puts its picture up to a frame after its sound (24 ms at
  `--start 0.45`, 33 ms at 0.2, plain or `--accurate`): the conform's grid is the source clock's,
  and the output-side seek then lands between two of its slots, which the encoder line's rate
  rounds again. `freeze.py --at 0` on the VFR clip writes 134 frames for 135 (the picture ends 37 ms
  before its sound; the same on 3.8.20, cause not looked into). Both fixed after 3.9.0 (#538). `loop.py --boomerang` retimes
  its frames by index and has no sound (decided, its docstring). `insert.py` takes a still. The
  atempo class reaches `speedramp.py`, `fit.py --method speed` (and `render.py`'s speed stage,
  which runs it) and `audio.py --tempo`; all three are changed.
- **Which of `frame` and `fit` sizes a sequence of several clips was not decided here** (#526;
  decided after 3.9.1 for (a), the `fit` object, in that section: the numbers below are 3.9.1's).
  It reproduces as the issue says, and the render itself is not one rule either: over two 160x120
  clips joined without a transition, frame 16:9 with `fit` 1:1 renders 120x120 and exports a 160x90 sequence; frame
  `{aspect 16:9, width 320}` with `fit {aspect 4:5, fit crop}` renders 192x240 and exports
  320x180, where one clip renders and exports 320x400; frame 1:1 with `fit {width 200}` renders
  200x200 and exports 120x120; frame `{width 320, height 180}` with `fit` 1:1 renders 180x180
  and exports 320x180. The two defensible rules: (a) the `fit` object wins, as it
  does for one clip: the sequence is the `fit` object's frame with the frame's values where it
  has none, and the render sizes the join so (join.py would size it from that frame, or fit.py
  get the frame's sides by `setdefault` as the one-clip stage does), which changes the size of
  every such multi-clip render; (b) the frame wins: the sequence stays the frame's, and the
  render would have to stop fitting the `fit` object's aspect inside the joined picture, which
  makes a `fit` object over several clips mean nothing it can be seen to do. The project does not
  decide between them: both are a reading of the same two objects. Recommended: (a), one rule for
  any number of clips, in a minor release because it changes rendered sizes, with the test the
  issue names (the rendered file's size against the exported sequence's) over one and several
  clips and the three render gaps under "The sequence is the project's frame" closed with it. No
  code changes here.

## After 3.8.22 — streams kept: a late-starting sound, audio-only extensions and subtitle tracks (#515, #517, #520)

- **A copied audio extraction that leaves out a late sound's lead is kept as a copy and says so**
  (#515). `cut.py --start 0 --end 2 -o x.m4a` of a source whose sound starts 0.254 s after the
  file's origin wrote 1.765 s that start with the sound: a stream copy begins at the first packet
  and cannot add silence, so the extraction is that much early against the picture. The result
  said only that it was 0.235 s short (`duration_delta_seconds`), which reads as an end that
  landed on a packet. It is not re-encoded: a copy's start that is off by less than `--tolerance`
  is kept and reported (a keyframe snap is, `start_snapped`), and a copy that comes out
  `--tolerance` or more short is re-encoded by the length check, which pads the sound from the
  start (A46). The check judges the written length, not the lead: the copy is short by up to a
  packet less than the lead (0.351 s for a lead of 0.355 s, 0.235 s for 0.254 s), so a
  `--tolerance` between the two keeps the copy and its warning (#542 review). What changed is that the run says it: an `audio_lead_dropped` warning
  (`{seconds, segments: [{index, seconds}]}`, the total and each `--segments` part it happened
  in) and a `notes` line naming `--accurate`, which keeps the lead. A dry run reports it too, from
  the source's stream starts, whatever `--tolerance` is: it cannot know the written length, so
  for a lead of `--tolerance` or more its note says a run re-encodes and pads instead when the
  copy comes out `--tolerance` or more short (`length_unjudged`). It left the warning out
  there, where a run with `--tolerance 0.353` kept the copy and gave it. It is reported from one frame of the source's picture (an offset
  under a frame cannot be seen against it), and for the part a re-cut replaced not at all. Not
  changed, and not decided here: whether the copy should instead re-encode whenever it would drop
  a lead (a lossy re-encode of AAC that `--accurate` already offers). Code: `cut.copied_lead()`,
  `cut.cut_one()`, `cut.main()`. Test: `test_a_copied_audio_extraction_says_it_left_out_a_late_sounds_lead`.
- **A picture edit that keeps the timeline keeps the subtitle track, converted where the container
  needs it** (#520). `crop.py` and `stabilize.py` left subtitles to FFmpeg's default stream
  selection, which in FFmpeg 6.1 picks no subtitle stream for an MP4 output (it has no default MP4
  subtitle encoder), so an MP4's mov_text track was dropped where `fit.py` and `color.py` kept it.
  Both now map the picture and sound `probe()` describes and run through
  `run_keeping_subtitles()`, as the entry "Subtitle/data tracks are kept where the picture's
  timeline is untouched and dropped where it is retimed" says. That helper copied every track,
  so a container change (mov_text into `.mkv`, SubRip into `.mp4`) failed the copy and the retry
  dropped the track; it now converts a text track to the container's own format
  (`subtitle_codec_for()`, export.py's rule and the one a crop of several tracks already used), so
  a track that crosses a container keeps its cues in every tool that uses the helper, unless
  another stream fails the same attempt (below). Crop's
  default selection had written a Matroska output's track as ASS (from mov_text or SubRip); it is
  SubRip now, as in `fit` and `export`, and a SubRip track into MP4, which it dropped, is mov_text. A track no conversion fits (a bitmap track in MPEG-4) or a data
  stream the container refuses (a tmcd track into Matroska, and on FFmpeg 6.1.1 a copied tmcd track
  into MP4 as well: "Could not find tag for codec none") still fails the first attempt, and the
  retry drops every subtitle and data stream, with `non_av_streams_dropped` saying why; so an MP4
  with a start timecode and a mov_text track still loses the track in `crop` as in `color`;
  `export.py`'s own ladder keeps the subtitles past a refused data stream, the helper does not.
  The sweep (`tests/sweep.py` with an MP4 holding one mov_text track against a plain clip) left,
  after the fix, `caption` (a burn), `waveform`, the copy `cut`, `loop`, `reverse` and `silence`
  dropping the track with the `source_items_dropped` warning, and `cut --accurate`, `fit
  --duration`, `freeze` inside the clip and `speedramp` with `dropped_non_av_streams: true`. The
  last four and the copy cut, `loop`, `reverse` and `silence` move the timeline (decided). A burn
  and a waveform keep it, so they fall under the rule too; they are left for a decision of their
  own (#520): a burn may be of the very cues the track holds. Code: `crop.main()`,
  `stabilize.main()`, `runner.run_keeping_subtitles()`, `runner.subtitle_codec_args()`. Tests:
  `test_a_picture_edit_that_keeps_the_timeline_keeps_the_subtitle_track`,
  `test_run_keeping_subtitles_records_the_first_attempts_error`.
- **An overlay's fade-out is cut to the layer's window** (#517). `overlay.py --fade N` with
  `--end E` where `E <= N` left the image layer's fade-out out (it was written only when `E > N`),
  so the layer faded in and vanished at full strength; with a window shorter than `N` the fade-out
  started before the layer was shown. The fade-out is now `min(N, E - start)` and starts that long
  before `E`, for an image and a text layer alike, as `audio.py` caps its fade-outs and `cut.py`
  its declick fades. The fade-in keeps its asked length; where the two overlap, the layer peaks
  below full strength, as before for text. Code: `overlay.fade_out_length()`, `overlay.alpha_expr()`.
  Test: `test_overlay_fade_out_longer_than_its_window_is_cut_to_it`.

## After 3.8.23 — a still where a clip is expected, RGB input to stabilize, and where fit puts the picture (#531, #519)

- **A still picture given where a clip with a length is needed is refused, `kind: input`,
  naming the still and `insert.py`** (#531). `input_length()` lets a still through as 0 s on
  purpose (grid.py and broll.py show one for as long as the clip beside it, "After 3.8.17"), and
  a tool that then computed with that 0 failed in a way that blamed something else: `cut.py`
  wrote 0.04 s with `verified: true` from `--start 0` and wrote nothing past the one frame
  (`kind: output`, "no video or audio stream"); `fit.py --duration` refused "0.00x" with
  `--method speed` and wrote one frame as verified with `--method trim`; `freeze.py --at` past 0,
  `speedramp.py` and `loop.py` were refused with a length of 0.000 or "no measurable duration";
  `metadata.py --chapters` failed inside ffmpeg (a chapter ending before it starts). The cut is the
  decision #510 left open for `cut.py`; `fit.py --method trim` is the same keep-the-first-N-seconds
  and is refused with it, and `metadata.py` is the sibling the sweep found (the same 0 s reaching
  ffmpeg). What a still has is kept: `freeze.py --at 0` still holds its one frame and
  `look.py --at 0` still shows it. Still means `probe._is_still()`: one picture read by an image
  demuxer (PNG, JPEG and TGA tested; a GIF is a clip). A render clip with `in`/`out` on a still
  now meets cut.py's refusal instead of the join's transition refusal. `verify.py STILL` now fails
  its cut steps and the steps built on the cut, where every step passed on a 0.04 s cut before.
  Code: `_common.emit.refuse_still()`, its callers in `cut.py`, `fit.py`, `freeze.py`,
  `speedramp.py`, `loop.py`, `metadata.py`. Test: `test_a_still_where_a_length_is_needed_is_refused_as_an_input`.
- **`look.py --at` past the picture it is taken from is refused, on either side of `--compare`**
  (#531). A still has one picture at 0, and `--at 1.5` on one wrote nothing (`kind: output`), where a
  clip with a time past its end got "--at T is beyond the duration" (`kind: input`); that is the
  refusal a still now gets, saying `--at 0` shows it. `--compare` checked neither picture's length,
  and a clip past its own end there was `kind: output` too. A still is read without `-ss`: image2
  given `-ss 0.000` dropped a TGA's only frame (image2 gives a TGA a length of one frame), so
  `look.py white.tga --at 0` wrote nothing. Code: `look._refuse_past_end()`, `look._seek()`.
  Test: the same one.
- **Decided after 3.9.2 as (a), refused** ("After 3.9.2"); recorded here as it was left. Not
  changed then: `export.py STILL` writes a 0.04 s file with
  `verified: true`, and `join.py --transition none` with a still joins one frame (a transition is
  refused, `kind: input`, by the clip's length). The options: (a) refuse, `kind: input`, naming
  `insert.py STILL --duration T`, as cut.py now does; (b) hold the still for a stated time (a
  `--still-duration` flag, or the join's transition length, or a default such as 3 s, said in a
  note), which is what a caller who joins a title card means. Recommended: (a) for `export.py`
  (a delivery of one frame is never meant, and insert.py already sizes and times a still) and (a)
  for `join.py` too, until (b) has a flag: holding for a time nobody stated is the decision this
  skill leaves to its caller. The same class, also not changed and recorded for the same decision:
  `fit.py STILL --aspect` (no `--duration`), `stabilize.py STILL`, `reverse.py STILL` and
  `scenes.py STILL` write or read one frame and complete; `graphics.py STILL` with no `--end` is
  refused as "--end must be after --start", and `look.py STILL` (a contact sheet) as "without a
  known duration", both `kind: input` but not naming the still.
- **`stabilize.py` takes an RGB source** (#531). vid.stab aborts on an RGB picture: FFmpeg 6.1.1
  with libvidstab 1.1 fails the assertion `fi->planes==1` on rgb24, bgr24, rgba and gbrp alike,
  and runs on yuv444p of the same frames, so a PNG still, a qtrle or RGB `.mov` and a gbrp file
  failed in pass 1 (`kind: ffmpeg`), while a JPEG still (YUV) ran. Both passes now see YUV 4:4:4:
  the BT.709 conversion every other re-encode of an RGB source makes (`bt709_matrix_filter()`; pass
  2 already had it, folded in by run(), pass 1 had none), or FFmpeg's own conversion to yuv444p
  on a line that keeps the source's tags and converts no matrix (`--codec prores`), and for an
  RGB source that probes HDR or BT.2020, which no line converts (below). Converting is
  what the other tools do with RGB input, so it is not refused. A note says the source was RGB;
  the output's pixel format is the encoder line's (yuv420p for H.264, yuv422p10le for ProRes),
  read back in `probe.video.pix_fmt`. Not verified on another libvidstab: one that took RGB would
  still get the YUV copy. Code: `stabilize.main()`. Test: `test_stabilize_takes_an_rgb_source`.
- **`caption.py --fonts-dir DIR --font NAME` names a face of DIR only where libass's pick is
  certain** (#531). libass looks NAME up among the faces in DIR and, with none of that name, asks
  fontconfig as it does without a fonts dir; the result said `how: fonts_dir`,
  `substituted: false` whatever DIR held, an empty folder or a text file named `.ttf` included.
  DIR's own files are now read with `fc-scan` and their name tables. Without a face of that name
  the font is reported as a run without `--fonts-dir` reports it (fontconfig's answer,
  `substituted: true` and a `font_substituted` fallback only when it is another family; an
  installed family is its own file, and on Windows the family is given to libass by name, both
  `substituted: false`; `fonts_dir` still named), and a note says the folder had no such face.
  "That name" is libass 0.17's match, each part checked by drawing on 0.17.1 with fontconfig given
  no fonts, so a face not matched drew nothing: the family is the Microsoft-platform name ID 1 only
  (`Inter` is not a family of `Inter-Black.otf`, whose ID 1 is `Inter Black`; fontconfig also lists
  ID 16), or FreeType's family name when there is no such record (DejaVu Sans with only its
  Macintosh records drew); the full name matches a TrueType outline and the PostScript name a CFF
  or Type 1 one, not the other way (`LiberationMono-Bold` and `Inter Display SemiBold Italic` drew
  nothing); only the folder's own files, not a subfolder and not a dot-file (fc-scan given the
  folder recurses, so it is given the files).
  Which face of the family libass then takes is not repeated here: libass scores the folder's faces
  and the installed ones together (a folder holding only DejaVuSans-Bold.ttf, with DejaVu Sans
  installed, drew the installed regular face for a regular burn; libass's debug log names it), and
  its weight and slant scoring differs between versions. So a `file` is named only for a face in
  exactly the asked style, upright at weight 400 or, with `--bold` (ASS Bold -1, which libass asks
  as 700), 700, or for a face asked by its full or PostScript name: libass scores either 0, the
  best there is, and an installed face that ties is the same family and style, so the face drawn
  may be that installed copy. A folder that holds the family only in other styles reports
  `how: fonts_dir`, `file: null`, `family` as asked and `substituted: false` (libass draws a face of
  that family either way), with a note that libass picks among those and the installed faces;
  `file: null` with a note is what an unreadable folder already reported. An earlier commit of this
  change ranked the faces by distance from the asked weight; a review reported that libass 0.17.4
  takes an italic 700 over an upright 600 for a bold request, where that ranking took the upright
  (not reproduced here: no such pair of one family is installed), and the ranking was dropped
  rather than chased. `font_used`
  names one face: libass draws a glyph that face lacks from another (its log: "Glyph 0x2605 not
  found, selecting one more font"), which is not recorded; drawtext draws its missing-glyph box
  from the same face.
  It is reported, not refused: an installed family found by fontconfig is drawn as asked, and
  `--font NAME` without `--fonts-dir` is not refused either. This differs from the font *file*
  check of 3.8.18 ("After 3.8.17"), which refuses a file the caller names that is not a font: here
  the caller named a family, and only the folder lacked it. Checked by drawing: the burn with the
  missing family and the burn naming the family reported are the same picture. When fc-scan
  cannot read the folder (no fontconfig), the family is reported as asked with a note that it was
  not checked. Code: `fonts.fonts_dir_face()`, `fonts._sfnt_names()`, `caption.main()`. Tests:
  `test_a_fonts_dir_without_the_asked_face_reports_the_substitution`,
  `test_a_fonts_dir_face_is_matched_as_libass_matches_it`.
- **`fit.py` reports where the picture sits in the frame it wrote, measured** (#519). After
  `--aspect`, `--width` or `--height` the result has `picture`: `{measured, x, y, width, height,
  frame_width, frame_height, frame_share, scale, cropped}`. The issue proposed computing it from
  the geometry the tool gave ffmpeg, but for a pad or a blur that geometry is ffmpeg's: the scale
  rounds the fitted size (`force_original_aspect_ratio`), pad rounds its offset and the picture's
  rows to the chroma grid of the format it runs in (a 203-row picture is 202 rows in a 4:2:0 pad,
  203 in a 4:2:2 or RGB one), and overlay rounds only the offset (the blur keeps 203). So ffmpeg
  measures it: the frame's own filters (the blur graph with its background drawn black,
  `pad_filters(blank=True)`) run on a white and a black frame of the source's displayed size and
  pixel format, after the conversion the encoder line adds and ending in the written file's pixel
  format, and the picture is the rectangle where the two differ. No frame of the source is
  decoded, and the frame size is the written file's. The narrowest reading of the issue: `scale`
  is the picture's width over the source's displayed width (for a crop, the width scaled to
  before the crop); `cropped` is in source pixels, rounded, each axis at its own scale (the
  scaled frame's margin is widened to a multiple of 4, so a 360x640 source cut to 360x202 is
  scaled to 360x642 and its 220 cut rows a side are 219 source rows); the note is given when
  `scale` is below 1 and no size was asked. A measurement that gives no frame of the written size
  is `{measured: false, reason}` and a note, never a rectangle. Only `fit.py` reports `picture`.
  The issue's sweep, not done here: `crop.py` (the caller gives the rectangle, so where the
  picture sits is known) and `pad.py` (it pads in time, before and after the clip; the picture
  fills its frame) have nothing to measure; `render.py`'s frame stage runs fit.py and does not
  pass its result on, and `export.py`'s presets that reframe (`--fit pad` with any `--pad-fill`,
  `--fit crop`) build the same `pad_filters()` frame but are not measured: both report no
  `picture` in that release. #548 extends the measurement to those export presets and carries each
  fit and export report in the render result. The original fit behavior was tested against
  the written file on a white source (black or red bars, the darkened blur, a 4:2:2 ProRes line, an
  RGB source, three crop anchors, a portrait source's rows cut) on 6.1.1 only. Code: `fit.measure_picture()`. Tests:
  `test_fit_reports_the_picture_rectangle_it_wrote`,
  `test_a_picture_measurement_that_fails_is_reported_as_not_measured`. The two frames are
  compared byte for byte, so they are rendered with `-filter_threads 1`: on FFmpeg 8.0.1 (CI, once
  in three runs of the red-pad case) the white frame's render differed from the black frame's in
  rows 128-217 of the 360x640 frame, one slice of rows above the picture, and `picture` said 293
  rows for the 203 the file held. The cause was not isolated (it did not recur locally on 6.1.1);
  one thread removes the slices. Test: `test_the_picture_measurement_runs_its_filters_on_one_thread`.
- **Seen and not changed** (the RGB sweep, `rgb24.mov` (qtrle, PCM) against the same clip in
  H.264): `audio.py`, `loudness.py` and `metadata.py` to `.mp4` stream-copy the qtrle picture,
  which MP4 cannot hold, and fail inside ffmpeg (`kind: ffmpeg`); to `.mov` they complete. That is
  a stream copy into a container that cannot hold the codec, not RGB (a gbrp H.264 `.mov` gave no
  differing row), and is a class of its own.
- **Seen and not changed: an RGB source that probes HDR or BT.2020 is written with BT.601 YUV
  under BT.2020 tags, or not at all** (found from a review of `stabilize.py`'s RGB path; the class
  is the HDR encoder line, not stabilize). `bt709_matrix_filter()` converts no HDR/BT.2020 source
  and the HDR line tags the source's own matrix, so FFmpeg's default RGB-to-YUV conversion
  (BT.601) makes the YUV. "One that probes HDR or BT.2020 is not converted to BT.709: FFmpeg's own
  conversion makes its YUV, as before" (#496, above) holds for not converting to BT.709, but says
  nothing of the matrix that conversion uses, which is not the one tagged. Measured on 6.1.1 with
  a gbrp10le FFV1 source of C03028 tagged bt2020/smpte2084 and no matrix: `stabilize.py`, `fit.py
  --fps 30`, `denoise.py` and `crop.py` alike write HEVC tagged bt2020nc that decodes, by its tag,
  as 196/52/35, and as 192/47/39 (the source) with BT.601. The same source tagged `gbr` (FFmpeg's
  own tag for RGB) fails every re-encoding tool of `tests/sweep.py` (`kind: ffmpeg`: the line
  passes `-colorspace gbr`, which no encoder option parses). The fix belongs to the HDR line of
  every tool (name the BT.2020 matrix in the conversion and tag `bt2020nc` for an RGB picture),
  with `fold_bt709_matrix()` and the alpha line's #496 rule to change with it; not done in a
  stabilize change, where a matrix of its own would be a second convention.
## After 3.9.0 — caches read in a dry run and stored after the inputs changed (#540)

- **A batch dry run serves a cache hit as the real run does, and its summary says those cuts apart.**
  A dry run without `--force` served an entry a real run had stored: its row (`cached: true`)
  carries that run's measured `cut_reencoded` and no `cut_possible_reencode_reason`, and the
  summary line counted those calls as planned re-encodes and pointed at the field the row lacks.
  Planning the item instead was tried and not kept: its last step meets the output the earlier run
  delivered and is refused `output_exists` without `--overwrite`. Which earlier deliveries a run may
  replace is known per process, so a real `--force` run is refused the same way. The real run serves
  the entry and never meets that refusal, so a planned row would show a failure the real run does
  not have. The dry run therefore reports what the real run does. The line counts the planned calls
  (`cut_possible_reencode_reason` on those rows) apart from the calls of rows a real run serves from
  the cache, as the run that stored them measured them. `cut_stream_copy` counts both, as a real
  run's does. Such a row's `verified` is the stored run's, not false: the contract's "false under
  --dry-run" now names that exception, and the contract's dry-run line for batch says that a served
  item runs no step. `render.py --dry-run` with `--cache` already did the same: a stage it would
  serve is listed in `cache.would_hit` and is not run, and `cache_lookup()` returns before it
  replays the stored result, so nothing a real run measured is shown as planned. Code:
  `batch.main()` (the summary). Test: `test_a_batch_dry_run_says_a_cached_row_s_cuts_apart_from_its_plans`.
- **A render stage is stored only under the key its inputs still have.** `sh()` made the stage's key
  before the child ran and stored the artifact under it after. A `--brand` logo or font, or any
  input file, changed in between was drawn and stored under the old file's key, and putting the old
  file back (a copy that keeps its mtime) served the new one. The key is now made again when the
  stage ends, from the same arguments, hashing the same files it hashed before the stage, so a file
  the stage itself writes beside its output does not count. When it differs, nothing is stored and a
  `cache_inputs_changed` skip names the stage; the next run makes it again. The check is the key
  at the stage's two ends: an input changed and put back before the stage ends, with the same
  fingerprint, is not seen (the child may have read the changed file). This is the rule
  `batch.py`'s `store()` follows since #537. Code: `render.sh()`, `cache_key(files=)`. Test:
  `test_a_render_stage_whose_brand_logo_changed_while_it_ran_is_not_cached` (a hook in
  `run_tool()` rewrites the logo before the real `overlay.py` child starts).
- **The sweep.** The caches that persist between runs are `batch.py`'s item cache and
  `render.py --cache`; both are now read in a dry run as the real run reads them, and both store
  under a key made after the work. Seen and not changed: `verify.py` and `proxy.py` keep no cache.
  The ASR model files under `~/.cache` are downloads, not stored results. The rest are memos that
  live for one process and store no artifact: `cut.py`'s keyframe landings and packet reads (keyed
  by path), the ffprobe banner, the owned-files snapshot, and the font and emoji lookups. A file
  replaced while one process runs is outside what they claim.


## After 3.9.1 — a variable-frame-rate cut lays its grid from its start; a hold or pad at the start keeps its last frame (#538)

Measured on `make_vfr_flash_beep()`'s clip (30 fps with two runs of six frames dropped, 27 fps on
average; flashes and beeps every second from 0.5 s) and `make_flash_beep()`'s constant 30 fps one,
FFmpeg 6.1.1 only; 7.1, 8.0.1 and 9.0.2 run the tests in CI. The two items "After 3.8.21" left
with their own cause.

- **A conform followed by an output-side seek lays its grid from the seek** (#538). `cut.py`'s
  re-encode (plain and `--accurate`, which a VFR source takes either way) seeks a margin of up to
  a second early and drops it with an output `-ss`, and `fit.py --method trim --from-center` does
  the same. The `fps` filter ahead of that seek laid its grid from the first decoded frame on a
  time base of one frame, so the seek landed between two slots and `-fps_mode cfr -r` rounded the
  picture again: every flash of the VFR clip came 24 ms after its beep at `cut.py --start 0.45`,
  33 ms at `--start 0.2`, and 24 ms (37 ms at `--duration 3`) through `fit.py --method trim
  --from-center`, against 18-19 ms for the uncut clip. `cfr_filter(meta, seek=m)` moves the
  picture so the seek is its 0, conforms it with `start_time=0` (a frame takes the slot its
  time rounds to and is shown until the next frame's slot; the last frame before the seek fills
  the slots up to the first one after it, the earlier ones are dropped), and moves it back on a
  microsecond time base, so the seek lands on a slot and slot k is the source's time start +
  k/27. That is the `fps` filter's rounding of timestamps, not a search for the nearest frame:
  cut at 2.2, inside a gap, slots 0-2 show the frame of 2.067 although 2.3 is nearer slot 2
  (measured with numbered frames, #549 review). From the cut: -13 ms at `--start 0.45` and `--from-center` 3.1, -4 ms at
  `--start 0.2`; `--start 1.45` and `2.2` (a whole second's margin, and a start inside a gap)
  measured -13 and -4 ms before and after. The frame counts are unchanged (96, 103, 69, 49, 84).
  The setpts after the conform leaves its frames no duration from FFmpeg 7.0; the encoder line's
  `-fps_mode cfr`, which cfr_args() always gives with this filter, sets each to one frame (by
  reading FFmpeg's sync code, not run here: CI runs it). A seek of 0 (a cut from the start, `fit.py
  --method trim` from the start) keeps the plain filter. Not changed: `fit.py --method trim
  --from-center --fps R` on a VFR source (24 ms at `--fps 27`, -8 at 24): its rate filter is the
  caller's and the encoder line carries no `-r`, so a setpts after it would leave FFmpeg 7+
  writing a rate it no longer knows; a constant-rate source's cut is not conformed and starts on
  the first frame at or after `--start` (17 ms on the 30 fps clip, decided in `cut_one()`).
  `cut.py --segments` conforms after its concat, from 0, and was already within half a frame.
  Code: `decision.cfr_filter()`, `cut.cut_one()`, `fit.main()`. Test:
  `test_a_variable_rate_cut_lays_its_grid_from_its_start`.
- **A VFR picture is conformed before a hold or a pad at its start, and the hold or padding is
  whole frames of the delivered rate** (#538). `tpad`'s start pad passes its input's end on
  without the pad, and an `fps` filter after it ended the picture at its last frame's start:
  `freeze.py --at 0 --hold 1` and `pad.py --start 1` wrote 134
  frames of the VFR clip's 135, the picture 37 ms short of its sound; a 30 fps clip through
  `tpad,fps=30` writes 149 of 150 the same way, but a constant-rate source is not conformed. A
  stop pad ends on its own clones and was not affected (`pad.py --end`, a hold at the end). The
  conform now comes first, `tpad` clones or pads `round(T * R)` frames of the delivered rate R
  (at least one for a hold), and the sound waits as long as they last (`n / R`, in samples), as a
  hold inside the clip does ("After 3.8.21"): 135 frames for `--hold 1` and `--start 1`, 122 for
  0.5 (14 frames, 0.519 s), 109 for `--hold 0.05`, every flash 18-19 ms after its beep. This
  changes one sentence "After 3.8.14": "`pad.py` conforms right after `tpad` ...: in front of it
  the padding was rounded to the 27 fps grid on top of the frames' own rounding (37 ms late)". The
  37 ms was against a sound delayed by `--start` itself; delayed by the padding's own frames the
  sound moves with the picture, and flash minus beep is the grid's 18-19 ms (it was 0 ms at
  `--start 0.5`, by the rounding, with the last frame lost). The conform is now ahead of the drawn
  chain, so a maskedmerge never meets it (#512's reason for keeping it inside). `--start 0.5` thus
  pads 0.519 s on the 27 fps output, as a constant-rate source pads whole frames of its own rate
  (`tpad_length`), with the same `notes` line. Code: `freeze.main()`, `pad.main()`. Tests:
  `test_a_variable_rate_hold_or_pad_at_the_start_keeps_every_frame`, the `pad` and `pad-colour`
  rows of `test_a_variable_rate_conform_keeps_each_picture_within_half_a_frame`.
- **Swept for the classes "a conform followed by an output-side seek" and "a conform after a
  filter that passes its input's end on early".** `python3 tests/sweep.py VFR --baseline CFR`
  printed no differing row, before and after (the defects are in the output, not in what a tool
  says). Every output-side `-ss` in `scripts/` was read: `cut.py` and `fit.py` are the two after
  a conform; `sync.py --trim-second` does not conform a VFR second file; `_smartcut.py` does not
  run on a VFR source (reason `vfr`). `tpad`'s start pad is used by `freeze.py`, `pad.py` and
  `sync.py`, which has no conform. Measured on both clips: `pad.py --end` and `--start --end`,
  `freeze.py` at the end, and `fit.py --method trim` from the start were already right.

## After 3.9.2 — audio-only output extensions, and a still given to export or join (#517, #531)

- **`.aif`, `.aiff` and `.caf` outputs are written as that container, in 16-bit PCM; a `.wma`
  output is written only as a stream copy of WMA sound, and refused, `kind: input`, where the run
  would encode into it** (#517, item 1). The audio extensions the skill reads
  (`AUDIO_MEDIA_EXT`) were wider than the ones it had a codec for (`AUDIO_CODECS`), and an
  extension with no codec was taken for a video container: `cut.py` (from a video, and
  `--accurate` from any source), `audio.py`, `silence.py` and `loudness.py`, from a video or an
  audio source, given `-o x.aiff` (or `.aif`, `.caf`) mapped the picture or encoded AAC and
  failed in the muxer (`kind: ffmpeg`, "Nothing was written"), after a dry run had completed with that plan; an audio
  `join.py` refused it as "cannot fill a video container"; `render.py`'s audio-only delivery (the
  podcast template) refused it as a copied `.mp4`. A stream copy of PCM (`cut.py` of a `.wav`,
  `metadata.py`) already wrote it. `-o x.wma` completed, verified, in every tool of the sweep that
  writes media but `waveform.py` and an audio `join.py` (both refused it), with the tools' H.264
  and AAC (or the copied stream) in an ASF file. The three are now in
  `AUDIO_CODECS`, so `is_audio_output()`, `audio_codec_for()` and every tool that reads them agree,
  a dry run included: `-c:a pcm_s16be`, the AIFF and CAF muxers' own default and the same 16-bit
  PCM as `.wav` (big-endian, plain AIFF's byte order), lossless, so `--bitrate` / `--audio-bitrate` is
  refused for them as for `.wav` and `.flac` (`LOSSLESS_AUDIO_EXT`). A stream copy keeps the
  source's PCM (a `.wav`'s `pcm_s16le` is copied as it is: ffprobe reads `pcm_s16le` in the
  `aiff` or `caf` file); a
  copy of a source that is not PCM is re-encoded, as for `.wav` (`cut.cut_one()`). `render.py`'s
  audio list is `AUDIO_CODECS` now, not a copy of it. `.wma` is what is left of the read set
  (`decision.UNWRITTEN_AUDIO_EXT`, the read set less the written one). The skill has no WMA
  encoder line, and the ASF muxer writes anything under the name, so a run that would encode into
  `.wma` is refused with reason `output_extension_unsupported` by
  `runner.refuse_unwritten_output()`, whose hint names the extensions `AUDIO_CODECS` writes; `run()`
  calls it for every ffmpeg command it records or runs, beside the missing-extension rule
  (`output_extension_missing`, A159), so before the command that would write the file runs, a dry
  run included, and it is the same refusal whether the name came from `-o` or from a `.wma` input's
  default (`talk_loudnorm.wma`). What it lets through is the result that was right before: a
  command that encodes nothing (every audio codec option `copy`, no filter) from inputs whose sound
  is WMA as ffprobe names it (`runner.WMA_CODECS`: wmav1, wmav2, wmapro, wmalossless, wmavoice) and
  that hold no picture or drop it (`-vn`), the parts of a copy join (`-f concat`) read from its
  list (in a dry run, parts not yet written named `.wma` count, as each part's own command was
  checked). So `cut.py` without `--accurate` (`--segments` included) and `metadata.py` still write
  the source's WMA into ASF, a review of the first version of this change having found that
  refusing every `.wma` broke them. Only wmav1 and wmav2 were run (FFmpeg 6.1.1 encodes those two;
  wmapro, wmalossless and wmavoice have decoders only, so no fixture was made and those three are
  allowed by name, not by a run). `cut.py`'s copy is judged by its written length and re-encoded
  when it lands `--tolerance` or more off (or wrote no stream, or failed): into `.wma` that
  re-encode is refused with the same reason, the copy this run wrote is removed so no file is left
  under the name (a copy that failed wrote none: `run()` replaces an existing path only on success, so the
  file `--overwrite` named is the caller's earlier one and is left), and a note says `--tolerance -1` keeps the copy as it lands; a dry run cannot
  know the length and says so in its notes (`cut.cut_one()`). `loudness.py` and `silence.py` always
  encode, so they call the refusal before their measuring pass, beside their other output guards;
  `join.py` (an audio join encodes) and `render.py` call it before their own extension rules, which
  would name `.wma` a video container or a copied `.mp4`. `render.py` refuses where it would write the
  file: a run that reaches the delivery (not a `--stop-after` preview) of more than a single uncut clip,
  and at the delivery when any stage after `clips` made the file; a single uncut WMA clip no stage
  touches is the source itself and is copied as it was, as before #517. `waveform.py` keeps its own refusal of every audio-only extension
  (it writes a picture). Checked on FFmpeg 6.1.1 only, by probing the written file: format `aiff`
  or `caf`, one audio stream, `pcm_s16be` (`pcm_s16le` for the copy), its length within one sample
  of the same tool's `.wav`; for `.wma`, format `asf`, the source's WMA codec and the same packet
  count as ffmpeg's own copy of the window. Not changed: a tool that writes a picture given an audio-only
  extension, `.wav` included, still fails in the muxer (`kind: ffmpeg`), as before (the sweep:
  every picture tool of `tests/sweep.py`, and `join.py` of video clips); that is a class of its
  own. Code: `decision.AUDIO_CODECS`, `decision.UNWRITTEN_AUDIO_EXT`,
  `runner.refuse_unwritten_output()`, `runner._copies_wma_only()`, `cut.cut_one()`,
  `join.join_audio()`, `render.AUDIO_EXT`, `loudness.main()`, `silence.main()`. Tests:
  `test_aif_aiff_and_caf_outputs_are_written_as_that_container`,
  `test_a_wma_output_is_refused_before_ffmpeg_runs`,
  `test_a_failed_wma_copy_leaves_the_file_it_was_to_replace`,
  `test_a_render_refuses_wma_only_where_it_would_write_one`,
  `test_a_stream_copy_of_wma_sound_into_wma_is_kept`.
- **A still given to `export.py` or `join.py` is refused, `kind: input`, naming the still and
  `insert.py`** (#531, the two items "After 3.8.23" left for a decision). Option (a) of that entry:
  a delivery of one frame and a join of one frame are never meant, `insert.py STILL --duration T`
  makes the clip, and holding a still for a time nobody stated is the decision this skill leaves to
  its caller. Before, on FFmpeg 6.1.1: the `export.py` presets tried (`youtube`, `reels`, `h265`,
  `prores` and `--preset copy`) wrote one frame (0.04 s, 0.033 s for `reels`) with
  `verified: true`, `--preset gif` failed in its muxer (`kind: ffmpeg`), and the alpha presets
  refused an opaque still for its lack of alpha (`prores4444` wrote an RGBA PNG as one frame,
  verified);
  `join.py --transition none` joined one frame, verified; a transition was refused as "0.04s, too
  short for a 0.48s transition" in a real run and planned in a dry run; `--copy` was refused as a
  stream-layout mismatch; a still beside audio-only inputs was refused as a picture among sounds.
  None of these was a still working on purpose (no entry or test kept one), so every preset and
  every `--transition`, `--copy` included, now meets the same refusal through
  `_common.emit.refuse_still()`, a dry run included, wherever the still stands in the join; a
  dry run's pending input is not a still. Siblings through these two: a `render.py` project whose
  clip is a still with an `export` stage wrote one frame, verified, and is refused by the export
  stage; two clips, one a still, were refused by the join's transition rule and planned in a dry
  run, and are refused by the join now, a dry run included. The rest of the class recorded "After
  3.8.23" (`fit.py STILL --aspect`, `stabilize.py`, `reverse.py`, `scenes.py`, `graphics.py`
  without `--end`, `look.py`'s contact sheet) is not changed here. Code: `export.main()`,
  `join.main()`. Test: `test_a_still_given_to_export_or_join_is_refused` (and a clip `insert.py`
  made of the still is exported and joined).
## After 3.9.3 — the timeline of several clips takes its size from fit (#526)

- **The `fit` object wins over the frame for any number of clips, in the render and in
  `--export-timeline`** (#526, option (a) of "After 3.8.21"). The render's fit stage gives fit.py
  the `fit` object's aspect, mode, width and height and the frame's only where the object has
  none (`setdefault`), as it always did for one clip; the export writes the sequence from the
  same merge (`frame.update()` with the object's aspect, fit, width, height and fps) whatever the
  number of clips. Before, a multi-clip render gave fit.py the frame's sides in one case only
  (an aspect and one side, and no size or other aspect in the object) and otherwise fitted the
  object inside the joined picture, while the export sized the sequence from the frame alone.
  Over two 160x120 clips joined without a transition, on FFmpeg 6.1.1 (rendered with
  `--stop-after fit`, exported as FCPXML):

  | frame | fit | 3.9.1 render / sequence | now, both (= one clip, before and now) |
  |---|---|---|---|
  | 16:9 | 1:1 | 120x120 / 160x90 | 120x120 |
  | 16:9, width 320 | 4:5, crop | 192x240 / 320x180 | 320x400 |
  | 1:1 | width 200 | 200x200 / 120x120 | 200x200 |
  | 320x180 | 1:1 | 180x180 / 320x180 | 320x180 |
  | 16:9 at 25 fps | fps 24 | 24 fps / 25 fps | 24 fps |
  | width 100 | none | 100x74 / 100x76 | 100x76 |

  Why (a): one rule for one clip and for several, the rule #506 already gave a one-clip project,
  and a `fit` object over several clips keeps doing something that can be seen. Option (b), the
  frame wins, would have kept every multi-clip render's size only by making the `fit` object's
  aspect and sides mean nothing there. What the merge implies is the one-clip rule's, now for
  several clips too: a frame with both sides keeps them under a `fit` object that gives only an
  aspect (fit.py's `frame_size()` uses two given sides as they are), so frame 320x180 with `fit`
  1:1 is 320x180 with the picture fitted to it, not a square; and a `fit` object with one side
  takes the frame's other side (`fit {width 36}` under a 72x128 crop frame is 36x128, the
  picture cut to that). The rate is the object's too: the render's fit.py already took
  `fit.fps`, and the multi-clip sequence stated the frame's. No `notes` line says the object
  won: the one-clip render has never written one, and both are the documented rule.
  The frame's rate is not handed to fit.py for several clips (join.py already conformed them to
  it), and a multi-clip project with no fit stage of its own (no `fit` object, `frame.aspect` or
  `frame.fit`) still gets none: join.py delivers the frame's sides and rate.
- **A frame of one side gives join.py both sides, the other one by fit.py's rule.** join.py
  takes a lone `--width` to the first clip's aspect and rounds both sides down to even, fit.py
  and the sequence round them up (`frame_size()`): `{width 100}` over 4:3 clips rendered 100x74
  against a 100x76 sequence, `{height 75}` over a 128x72 first clip 132x74 against 136x76, and
  `{width 101}` over it 100x56 against 102x58. render.py now computes the other side with `frame_size()` from the first clip's
  displayed size (`display_size()`, as join.py and the export read it) and passes both. A side
  that is not a whole number goes to join.py as written, which refuses it as before. With this
  and the entry above, the gaps (1) and (3) of "The sequence is the project's frame" are closed;
  (2), join.py's padding before a crop, remained until #552. An effective crop
  now fits each source inside the delivery canvas with join.py's crop mode, using
  the same size as the exported sequence.
- **Two combinations the first version left apart (review of #553).** A frame of one side whose
  side the `fit` object gives too: the join is sized from the object's value (the object giving no
  other side), since fit.py derives the other side from the joined canvas and the export from the
  clip (`{width 100}` with `fit {width 200}` rendered 200x152 against 200x150). A key the `fit` object
  gives as `null` is dropped before the frame's values are merged in, as the export already read it
  (frame 320x180 with `fit {aspect 1:1, width null}` rendered 180x180 against 320x180, for one clip
  too). Both are rows of `test_a_sequence_of_several_clips_takes_the_fit_objects_frame`.
  A third: with `frame.fps` and a different `fit.fps` the clips were joined at the frame's rate and
  conformed again by fit.py, each clip rounded twice, where the sequence rounds each once at the
  delivered rate (two 0.7 s clips, frame 25 fps, fit 24 fps: 35 frames against 34; two 8-frame clips: 13
  against 12). join.py now gets the `fit` object's rate where it gives one, the frame's otherwise
  (`test_several_clips_are_joined_at_the_rate_the_fit_object_delivers`). Measured on FFmpeg 6.1.1.
  Filed as #552: (2) above.
- **Which projects render differently.** Only projects of two or more clips (an audiogram
  project joins nothing and is not one). (i) With a fit stage (a `fit` object, `frame.aspect` or
  `frame.fit`) and a frame width or height, fit.py now gets the frame's sides, except where it
  already did (an aspect and one side in the frame, no size or other aspect in the object). The
  delivered size changes where the object's aspect or sides were fitted inside the join (the
  table above); where the join already had the size fit.py now asks for (a `fit` object of only
  `duration` under a frame of both sides), the size is the same and the fit stage's command
  line, and so its `--cache` key, differ. (ii) With a frame of exactly one whole-number side,
  join.py gets both sides: the size changes where that side is odd or the first clip's aspect
  makes the other one odd, and the join's command line changes in every such project. Their exports change where a
  `fit` object exists (its aspect, mode, sides or rate now size the sequence), and a
  `fit.aspect` or `fit.fit` fit.py refuses is now refused by the export, as for one clip. A
  multi-clip frame of both sides and `frame.fit` with no aspect and no `fit` object failed in
  fit.py ("nothing to do") and now renders at the frame's size. One-clip projects are unchanged:
  `test_a_sequence_of_several_clips_takes_the_fit_objects_frame` pins their sizes and rates at
  3.9.1's (that test, run against 3.9.1's render.py, fails only its two-clip rows).
  Swept: every place that sizes a render or a sequence from `frame` or `fit` -- render.py's join
  and fit stages, `export_timeline()` for `.fcpxml`, `.edl` and `.otio` (one `timeline.build()`
  for all three; FCPXML states the size, EDL and OTIO only in the reframe note), and `batch.py`
  with a project recipe (it runs render.py, so it renders what render.py does: 120x120 for the
  first row above, before and after). `tests/sweep.py` over a 4:3 clip against a 16:9 one
  printed no differing row (the single-file tools do not read a project). `multicam.py
  --write-project` writes no frame or fit, and a delivery template is one clip. Measured on
  FFmpeg 6.1.1 only. Code: `render.main()` (the join and fit stages), `render.export_timeline()`.
  Tests: `test_a_sequence_of_several_clips_takes_the_fit_objects_frame`,
  `test_a_multi_clip_render_delivers_the_sequence_size`,
  `test_a_one_clip_sequence_takes_the_fit_objects_frame`.

## After 3.10.0 — a refused stream costs only itself, and an output is what its name says (#539)

The leftovers of #515, #517 and #520, each reproduced on FFmpeg 6.1.1 (Linux) with lavfi fixtures
before it was changed. Five classes are changed, two are left for a decision.

- **A data stream the container refuses is retried away alone; the subtitles beside it stay**
  (item 5). `run_keeping_subtitles()` retried without every subtitle and data stream when any of
  them failed the first attempt, so an MP4 with a mov_text track and a start timecode (tmcd) lost
  the track in every tool that uses the helper: written to Matroska, which takes no data stream,
  and on FFmpeg 6.1.1 to MP4 too (a copied tmcd track is refused there). The helper has
  `export.py`'s rungs now (subtitles and data, the subtitles alone, neither), and a rung is tried
  only when the source holds what it drops, so a source with one kind of stream is still encoded
  twice at most. Each retry is a `non_av_streams_dropped` fallback with `dropped`, the stream
  types it leaves out, as `export.py` records it. `dropped_non_av_streams` is read back after the
  data-only rung: false when the written file holds as many data streams as the source (the
  MOV/MP4 muxer writes a timecode track of its own from the picture's timecode tag), true into
  Matroska. Not changed: a source with a data stream and no subtitle still reports `true` after
  its retry, whatever the muxer wrote, as before. Not changed either: `color.py --retag`'s
  re-encode, which has its own two-step copy of the same streams (`-c:s copy`, no conversion,
  both dropped together). Routing it through the helper kept a mov_text track into `.mkv` and
  then reported `dropped_non_av_streams: false` beside a second audio track the re-encode leaves
  out, which `test_color_retag_fallback_keeps_extra_audio_and_subtitles_when_it_can` pins as
  `true`; what that field should say there is a decision. Seen in the sweep and not changed: a tool whose picture goes through
  `-filter_complex` (`graphics`, `overlay`, `pad`, `redact`) writes no timecode tag, so its MP4
  holds no timecode track; `source_carry` lists the timecode as dropped. Code:
  `runner.run_keeping_subtitles()`, `runner._non_av_kinds()`. Test:
  `test_a_refused_data_stream_does_not_cost_the_subtitles_beside_it`; unchanged and still passing:
  `test_run_keeping_subtitles_records_the_first_attempts_error`.
- **`metadata.py` refuses, before ffmpeg runs, a stream the output's container does not take as a
  copy** (item 6). It copies every stream (`-map 0 -c copy`), so nothing can be converted, and a
  SubRip MKV written to `.mp4` failed in the muxer (`kind: ffmpeg`) after a dry run that said
  completed. The same happened for a mov_text MP4 to `.mkv`, a timecode track to Matroska or
  WebM and an attachment outside Matroska. Each is `kind: input` now, a dry run included, naming
  the stream, with a hint: keep the source's container, or change it first with
  `export.py --preset copy`, which converts a text track. Only what MPEG-4, Matroska and WebM
  are known to refuse is judged (each case run against ffmpeg's own copy on 6.1.1); another
  container is left to its muxer. The sweep found the same failure in the source's own container:
  FFmpeg 6.1.1's MP4 muxer refuses a copied tmcd track ("Could not find tag for codec none"), so
  `metadata.py` failed for every MP4 with a start timecode. The copy is tried as it is, and when
  it is refused the track alone is left out and the muxer writes it again from the picture's
  timecode tag (a `non_av_streams_dropped` fallback; the label read back is the source's). An
  FFmpeg that takes the copy is not affected; none was run. Not changed: `color.py --retag`'s
  stream copy of such an MP4 still fails and re-encodes (`reencoded: true`, with a note). Code:
  `metadata.refuse_uncopyable_streams()`, `metadata.non_av_streams()`, `metadata.main()`. Test:
  `test_metadata_refuses_a_stream_the_output_container_does_not_take_as_a_copy`.
- **A picture is not written into an audio-only extension** (item 3). The tools that always write
  a picture took `-o x.m4a` and completed, verified, with H.264 in a file named for sound, and
  failed in the muxer for `-o x.wav` (`kind: ffmpeg`) after a dry run that said completed;
  "After 3.9.2" left this as a class of its own. One check in `run()`, beside the WebM rule,
  refuses it for every ffmpeg command (`kind: input`, reason `output_extension_audio_only`), dry
  runs included: an output extension in `AUDIO_MEDIA_EXT`, a video encoder named for it (`-c:v`
  other than `copy`), no `-vn`, and an input that can give a picture. The sweep (every
  media-writing tool of `tests/sweep.py` with `.m4a` and `.wav`, a run and a dry run each, and
  `join`, `insert`, `background` by hand): every picture tool is refused, and `audio`, `cut`,
  `loudness` and `silence` still write the sound. `metadata.py` copies, so it has the same
  refusal by its own rule when the source has a picture (a cover picture beside its sound is
  still copied). `waveform.py` keeps its older refusal. Not changed, because a stream copy is not
  judged from the command: `sync.py --replace-audio -o x.m4a` copies the picture into the `.m4a`
  (`-o x.wav` is refused in a run, where the copy fails and the re-encode is checked, but planned
  in a dry run), and `join.py --copy` was not run. Code:
  `runner._check_picture_into_audio_extension()`, `metadata.main()`. Test:
  `test_a_picture_written_into_an_audio_only_extension_is_refused_before_ffmpeg_runs`.
- **A sound-only output of `audio.py` or `loudness.py` holds a late sound's lead as silence**
  (item 1). A source whose sound starts 0.476 s after its picture came out with the sound at 0
  in `.wav` and `.flac` (no start time) and in `.m4a` only as an edit a decoder does not pad, so
  the extraction was that much early and that much shorter. Both tools re-encode, so #409's
  rule applies ("a late sound padded with silence", as `cut.py --accurate` and `silence.py`
  already do; the copy `cut.py` keeps its `audio_lead_dropped` warning, a decision of "After
  3.8.22"). `audio.py` pads first in the main track's chain, so every later stage and `--tempo`
  work on the file's clock from 0 (`--replace` reads the replacement's own lead);
  `loudness.py` pads after the trim that counts from the first sample, and its `duration` step
  expects the sound's length plus the lead. A lead of half a millisecond or less is not padded
  (`sync.py`'s bound), a source without a picture has none, and beside a copied picture the
  container holds the start and nothing changes. Seen and not changed, with a plain source too:
  `loudness.py -o x.mp3` reports `verified: false` (the MP3 is 38 ms longer than the one AAC
  frame the step allows) and `-o x.opus` of a 44.1 kHz source fails in libopus (`kind: ffmpeg`).
  Not run: an audio `join.py` and `render.py`'s audio-only delivery of such a source. Code:
  `decision.late_sound_lead()`, `decision.PAD_SOUND_FROM_ZERO`, `audio.main()`,
  `loudness._normalize()`. Test: `test_a_sound_only_output_keeps_a_late_sounds_lead_as_silence`.
- **`graphics.py`'s fades and the lower third's slide fit a window shorter than they are**
  (item 2). The 0.3 s fade in and out (drawtext's alpha, and `\fad(300,300)` on the ASS route;
  250 ms for the sticker there) was fixed: a window under 0.3 s never reached its fade-out, so
  the text vanished part way up, and one between 0.3 and 0.6 s jumped down in brightness where
  the fade-out took over (measured per frame on both routes). Each fade is `min(0.3, window / 2)`
  now, the cap the emoji overlay already had. The lower third had the same shape in position
  (0.4 s in, 0.3 s out: in a shorter window the bar jumped back where the slide-out took over,
  measured on drawtext; the ASS route's three timed lines were reasoned about, not measured); the
  two share a short window 4:3. A window of 0.6 s (0.7 s for the lower third) or
  more writes the expressions it always did. Not changed: the sticker's 0.25 s rise, which a
  window shorter than it only cuts short. Code: `graphics.main()` (`fade_s`, `in_s`, `out_s`).
  Test: `test_graphics_fades_and_slides_fit_a_window_shorter_than_they_are`.
- **Left for a decision: `caption.py`'s burn and `waveform.py` drop the source's subtitle track**
  (item 4). Reproduced; nothing changed. The timeline is kept, so the rule above would keep the
  track, but a burn may be of the very cues the track holds, and then keeping it shows them twice.
- **Matroska audio uses `.mka`** (item 7). Before this decision, a cut to `.mka` planned
  to keep picture. FFmpeg's default stream selection kept only sound, so `stream_lost` triggered
  a re-encode that explicitly mapped picture into the `.mka`. The audio extension table now
  treats `.mka` as sound-only. Every re-encoded `.mka` cut uses FLAC. Copy mode can retry
  after a recoverable muxing error, a missing stream, or a missed length tolerance. A terminal
  failure such as a full disk stops the run. Use `.mkv` to keep the picture.
- **What the review of #554 found in the five changes above, each measured on FFmpeg 6.1.1 first.**
  `waveform.py`'s older refusal of an audio extension had no `reason` while README named
  `output_extension_audio_only` for every picture tool; it gives that reason now, from its own
  place ahead of its measuring passes. The `dropped_non_av_streams` text in the contract said
  "false when the muxer writes the timecode track itself" without the condition stated above (a
  source with both a subtitle and a data stream); it says it now. `audio.py --audio-stream N`
  read the first track's start for the lead: a second track 0.476 s late beside a first at 0 was
  written 2.53 s long with the sound at 0, and is 3.0 s with the sound at 0.49 s now
  (`audio.main_track_lead()` reads the selected track's start; `loudness.py` has no
  `--audio-stream`). `metadata.py`'s preflight left `.m4a` out of the MPEG-4 family, so sound with
  a SubRip track written to `.m4a` still failed in ffmpeg after a dry run that completed; and its
  timecode retry into `.m4v` completed without the timecode (the ipod muxer writes no tmcd track
  unless asked; `source_carry` listed it as dropped), so that retry passes `-write_tmcd 1` and the
  label read back is the source's. In `graphics.py`, the lower third's two slides met at an
  instant the ASS route writes in centiseconds (0.61 for 0.614286 in a 0.5 to 0.7 s window), so
  the text's slide-out led the bar's: no frame differed at 25 or 30 fps, one did at 60 fps (the
  text 11 px ahead of the bar at 640 px wide, 2 px between the routes after); the instant is
  rounded to a centisecond for both routes when the slides fill the window. A window they fill
  exactly had a rest line of no length whose emoji PNG, which has no fade, showed for the one
  frame at that instant (saturation of the bar's corner 30.7 on that frame against 4.8 and 2.1
  beside it; 6.6 after); the line is not written. The sticker's 0.25 s pop was cut on the ASS
  route only, so in a 0.2 s window drawtext peaked at 1.18 against 2.10 (full strength 2.10); the
  pop is `min(0.25, fade)` on both, and its ASS `\move` with it. Tests: the five above, extended.
- **The padded lead is cut into frames of 4096 samples (`asetnsamples=n=4096:p=0`).** From #554's
  CI log, not measured locally: on FFmpeg 9.0.2 `loudness.py -o x.flac` of a late sound failed
  in the FLAC encoder ("invalid block size: 111305"), the pad having handed it the lead and the
  sound as one frame; 6.1.1 splits the frames itself. The split is part of
  `decision.PAD_SOUND_FROM_ZERO`, so `audio.py` and `loudness.py` both have it, for every codec
  (the lengths and onsets measured on 6.1.1 are the same with it, `.wav`, `.flac`, `.m4a`,
  `.mp3`, `.ogg` and `.opus`). Whether it clears the failure on 9 is reasoned from the encoder's
  message. Not changed, and likely to meet the same on FFmpeg 9 where a filter upstream emits one
  large frame: the same pad without the split in `cut.py --accurate` to `.flac` (`cut.cut_one()`)
  and in the re-cut `silence.py` and `cut.py --segments` use (`cut.join_from_source()`). The same
  CI run had two data streams in the fixture of
  `test_a_refused_data_stream_does_not_cost_the_subtitles_beside_it`; the new tests no longer
  assert how many data tracks a muxer writes.
- **The fade's alpha is held in 0..1.** From #554's CI on FFmpeg 9.0.2 (macOS), not reproduced
  here: the drawtext chip in a 0.5 to 0.95 s window was 6.94 on the frame at `--start` where
  every other frame was under 1, in that one window only; the same subtest passes on 6.1.1, 7.1
  and 8. Evaluated by hand, the expression is exactly 0 on that frame and on a frame at `--end`,
  and negative on a frame the window selects a hair before `--start` (1.234567 s for
  `--start 1.235` at 30000/1001: -0.0014). FFmpeg 6.1.1 draws nothing for 0 or a negative alpha
  (measured: the frame is black for -0.05 and 0), so the cause on 9 is not established. The
  expression is `max(0,min(1,...))` now, which removes the negative case by construction; on
  6.1.1 every frame of the three windows measures as before. It does not change the frame at
  `--start` itself, whose alpha was 0 already, so it may not clear the CI failure. Leaving that
  frame out of the drawtext's `enable` would, if a zero alpha is what FFmpeg 9 draws wrongly, but
  `test_a_window_or_a_length_on_a_frame_time_keeps_that_frame` pins the `enable` text of this
  drawtext, so it was not done; that needs an FFmpeg 9 run and a decision. The test is not
  loosened: one rise and one fall, which a first frame brighter than the next fails. Code:
  `graphics.main()` (`fade_a`).
## After 3.10.1 — an HDR or BT.2020 RGB source is made YUV with the matrix its line tags (#544)

- **The class: an RGB source is converted to YUV with FFmpeg's default matrix under a tag that
  names another.** SDR RGB sources are converted to BT.709 explicitly
  (`bt709_matrix_filter()`, after 2.10.1), and measured again here they are right (C03028/30C050/2030C0/808080
  in gbrp FFV1, tagged BT.709 or not, through `fit.py` and `crop.py`: C13028/30C150/1F30C0/808080
  read by the bt709 tag). An RGB source that probes HDR or BT.2020 was left out of that
  ("FFmpeg's own conversion makes its YUV, as before", #496; recorded as seen and not changed in
  "After 3.8.23"), and the 10-bit line that keeps such a source's colour tagged
  `v.color_space or "bt2020nc"`. Two things followed, both measured on FFmpeg 6.1.1 with a
  160x120-per-patch gbrp10le FFV1 source of those four colours, BT.2020 primaries, PQ transfer:
  - matrix tag `gbr` (what FFmpeg 6.1.1 writes into the FFV1 `.mkv` of an RGB filter graph
    without being asked, and what PNG-in-MOV, qtrle, utvideo and libx264rgb copies of that file
    probe as: the usual case; the untagged one needs `-colorspace unknown` to make): the line passed
    `-colorspace gbr`, which no encoder option parses, and every re-encode failed inside ffmpeg
    (`kind: ffmpeg`, "Nothing was written"): 21 rows of `tests/sweep.py` against a YUV PQ
    baseline (`caption`, `crop`, `cut`, `cut --accurate`, `deinterlace`, `denoise`, `fit`,
    `freeze`, `graphics`, `loop`, `overlay`, `pad`, `proxy`, `redact`, `reverse`, `silence`,
    `speedramp`, `sphere`, `stabilize`, `straighten`, and `verify` through them), plus
    `export.py --preset youtube-hdr`, `join.py`, `multicam.py`, `broll.py` and
    `overlay.py --video` by hand;
  - no matrix tag: the same tools completed and wrote BT.601 YUV tagged bt2020nc. Read by the
    tag the patches were C53525/2BB14D/1F3BC8/808080 (up to 15 of 255 off; read as BT.601 they
    were the source's), in every one of those tools: the sweep printed no differing row for
    any of them (its rows are what a tool said), so each output was decoded and compared with the same tool's output from a YUV PQ
    copy of the picture.
  An RGB file tagged `bt2020nc` (a mislabelled one, made with `-colorspace bt2020nc`) was
  right before: FFmpeg 6.1's scaler converts by the frame's own tag.
- **Decided: the line names the matrix it tags.** `color.hdr_line_matrix()` is the matrix tag
  of the 10-bit line: a YUV source's own, or bt2020nc without one, exactly as before; for an RGB
  source, its tag when that names a matrix swscale can make (bt2020nc, bt709, the BT.601 names,
  fcc, smpte240m: the frames FFmpeg 6.1 already converted by that tag), else bt2020nc.
  `color.hdr_rgb_matrix_filter()` is the conversion
  (`scale=out_color_matrix=bt2020:out_range=tv,format=yuv444p10le`: the matrix only, limited
  range, 4:4:4 at the line's 10 bits, as `rgb_to_bt709_filter()` is 4:4:4 at 8), and it rides on
  the encoder line the way the BT.709 one does: `video_args()` ends with it, `run()` folds it
  in front of the tool's own graph (`fold_bt709_matrix()` recognises it), `matrix_chain()`
  gives it to each RGB clip of a join, a multicam, a cutaway or a PiP on an HDR line (the
  matrix is the line's, so an RGB clip beside a YUV bt2020nc one gets that), `export.py` adds
  it to its `youtube-hdr` and `youtube-av1` lines, and `stabilize.py` and `fit.py`'s picture
  measurement take it from `decision.line_matrix_filter()` instead of each asking
  `bt709_matrix_filter()`. `--codec prores` on such a source gets it too: that line writes the
  same three tags. Primaries and transfer are not touched. `bt709_matrix_filter()` still
  returns nothing for an HDR or BT.2020 source (its test pins that), so no BT.709-tagged line
  changed.
- **Measured after, FFmpeg 6.1.1.** Both variants, read by the output's bt2020nc tag:
  C03028/30C050/2030C0/808080 from `crop`, `fit --fps 30`, `denoise`, `stabilize`,
  `export --preset youtube-hdr`, `join` (two RGB clips; an RGB and a YUV one, with and without a
  fade), `multicam`, `broll` (RGB over RGB, RGB over YUV), `overlay --video` (RGB layer, RGB
  main), `crop --codec hevc|av1|prores` and `export --preset youtube-av1` (its blue 2130C1). Every picture-writing row of
  the sweep table against the YUV PQ copy: at most 3 of 255 apart (`sphere` 3, `stabilize` and
  `proxy` 2, the rest 0 or 1), except `caption` (9, on the edge of the drawn text, where a
  4:4:4 picture under libass differs from a 4:2:0 one; the patches are equal) and `export`
  (below). HLG and BT.2020 SDR (`bt2020-10`) sources the same through `crop`. The bt2020nc-tagged
  RGB file: the same four colours before and after. `tests/sweep.py` of either variant against
  the YUV PQ copy now prints three rows, the stream copies below. FFmpeg 7, 8 and 9 were not run locally:
  from 7.1 swscale and libavfilter negotiate the matrix from the frames' tags, which this
  conversion sets where 6.1 only writes the pixels, and the SDR counterpart of the same shape
  (`scale=out_color_matrix=bt709`) is what CI already runs there; that this one behaves the same
  is reasoned, not measured.
- **Seen and not changed** (each is its own decision, none is the 10-bit line):
  - an 8-bit BT.709 line given an HDR or BT.2020 RGB source: `export.py`'s fixed presets (which
    warn `colour_not_converted` and convert nothing, by decision) and `grid.py` (an SDR line
    whatever its cells are). The RGB is made YUV by FFmpeg's default there, BT.601 under the
    bt709 tag: `export --preset youtube` reads CC3D25/26AC4D/1C37C6/808080 where the same
    preset on the YUV PQ copy reads C63828 for the red (BT.2020 samples under the bt709 tag,
    the decided part). Converting it is `bt709_matrix_filter()` returning a filter for an HDR
    RGB source, which
    `test_an_rgb_source_or_a_still_is_converted_to_the_bt709_it_is_tagged_with` pins as None;
    proposed, not done.
  - an SDR RGB clip on an HDR line (`join.py HDR.mkv SDR_RGB.mkv`): still FFmpeg's conversion
    (C53525 by the bt2020nc tag). Its primaries and transfer are not the line's either; a matrix
    alone would not make it right.
  - an alpha line (`--keep-alpha`, `--transparent`) and `export.py --preset prores` of such a
    source write no matrix tag at all (and here no primaries or transfer either: ProRes 4444 of
    the PQ fixture probes unknown/unknown/unknown, its YUV BT.601). Nothing disagrees with a tag
    there, so it is not this class; that the HDR tags are lost is. #496's sentence for the alpha
    line ("an HDR or BT.2020 one is not converted to BT.709: FFmpeg's own conversion makes its
    YUV") still describes it.
  - an RGB layer (a logo, an emoji, a box) on an HDR line: "Not converted ... an HDR line"
    ("After 3.6.0"), unchanged.
  - `audio.py`, `loudness.py` and `metadata.py` to `.mp4` stream-copy FFV1, which MP4 cannot
    hold (`kind: ffmpeg`): the stream-copy class recorded in "After 3.8.23".
  - `color.py --to-sdr` reads RGB and YUV PQ alike (D90000/00E300/0000FA/9A9A9A from both).
- Code: `_common/color.py` (`hdr_line_matrix`, `hdr_rgb_matrix_filter`, `hdr_rgb_matrix_args`,
  `_MATRIX_FILTER_RE`), `_common/decision.py` (`video_args`, `matrix_chain`,
  `line_matrix_filter`, the three places the tag was built), `export.py`, `stabilize.py`,
  `fit.py`. Tests: `test_an_hdr_or_bt2020_rgb_source_keeps_its_colours_on_the_hdr_line`
  (tests/test_picture.py: five variants of the fixture, each asserted before the tool; the
  colours of four patches read by the output's tag, tolerance 7 of 255 on the largest
  error over the four patches, where the wrong matrix puts the green patch 15 and the blue 11 off and
  the lossy 10-bit round trip is at most 2 on FFmpeg 6.1.1 and at most 5 on 7.1 (CI: every patch a
  little dark there, the grey 128 read 126, a level and not a matrix; not run down, since 7.1 cannot
  be run locally); run against 3.10.0's scripts it
  fails 13 of its 15 rows, the two bt2020nc-tagged ones passing as they should),
  `test_an_hdr_line_names_the_matrix_it_tags_for_an_rgb_source` (tests/test_contract.py: the
  helpers, every `--codec` line, the fold).

## After 3.14.1 — `npx ffmpeg-skill setup`, one command for a new machine

- **`setup` installs FFmpeg only through brew, winget or apt-get, and only when `ffmpeg` does not
  run.** Those are the three commands the README already gave by hand. On any other system (dnf,
  pacman, a machine without Homebrew) it installs the skill, says FFmpeg is still missing and
  exits with doctor's non-zero status: a package name guessed for a manager nobody here has run
  is worse than the manual line. `--no-ffmpeg` never runs a package manager.
- **It does not edit a shell profile.** Homebrew's `ffmpeg-full` is keg-only; `setup` puts its
  `bin` on PATH for its own process (so its doctor run sees the build) and prints the `export`
  line. After winget, the terminal that ran it has the old PATH, so `setup` says to open a new one
  and exits non-zero; that is a correct report of this terminal, not a failed install.
- **It does not register the MCP server**, for the reason under "The plugin does not register the
  MCP server": the agents it installs for have a shell. It installs neither Node nor Python.
- **It takes no target flags.** The targets are the agents whose home directories exist
  (`~/.claude`, `~/.cursor`, `~/.codex` or `~/.agents`), Claude Code when none does; choosing them
  is what the plain installer's flags are for, and `setup --all` is refused before a file is
  copied.
- Code: `bin/install.js` (`detectAgents`, `ffmpegInstallPlan`, `setupFfmpeg`). Test:
  `test_setup_installs_for_the_agents_found_and_only_runs_a_named_package_manager`
  (tests/test_contract.py). The three install commands are tested against a stand-in for the
  package manager; none has been run by this test on a machine without FFmpeg.

## After 3.13.2 — file names and unusable inputs (#558)

Seven items of the basics audit of 3.10.0, each reproduced on FFmpeg 6.1.1 (Linux, Python 3.11)
before it was changed. Nothing here was run on FFmpeg 7.1, 8 or 9, on macOS or on Windows; what
is said about them is reasoned and marked so.

- **A still with a `%` in its name is opened with `-f image2 -pattern_type none`.** The A7 entry
  above put `-pattern_type none` alone in front of every image name with a `%`. FFmpeg chooses
  image2 by itself only for a name it reads as a pattern (`logo%d.png`); `a%20b.png` and `50%.png`
  are opened by `png_pipe` (`jpeg_pipe`, ...), which has no such option, and every tool given one
  failed as `kind: ffmpeg` ("Option pattern_type not found": `overlay --image`, `insert`,
  `broll --insert`, `probe`). Naming the demuxer makes both cases one: measured for `a%20b`,
  `50%`, `p%d` and `q%03d` as `.png` and `.jpg` (the decoded pixel is the file's own, not the
  numbered neighbour's), and the decode of a `%`-named file is byte-identical with and without the
  two options for the 20 of the 21 extensions in `_IMAGE2_EXT` this build writes (`.xpm` it
  cannot write). Forced, image2 takes the codec from the extension, as it already did for a `%d`
  name: a JPEG named `x%20y.png` does not open (it did not before either). That `image2` accepts
  `pattern_type none` on 7.1 to 9 is reasoned from the A7 guard having passed CI there for `%d`
  names, which image2 was already reading. Code: `runner.still_input_args()`. Test:
  `BasicsAudit558Tests.test_a_percent_in_a_still_name_is_that_file_pattern_or_not`; the exact
  argument list `test_a_percent_in_a_still_path_never_opens_another_file` pins moved with it.
- **A relative path with a colon in its first segment is written `./...` inside a filter.**
  `escape_filter_path()` went through `Path()`, which drops a leading `./`, so
  `caption.py --srt ./a:b.srt` reached the subtitles filter as `a\\:b.srt`; the filter opens its
  file through libavformat, which read `a` as a protocol ("Protocol not found"). `d:e/c.srt` failed
  the same way, and so does `metadata=print:file=` given such a name directly. `lut3d`, drawtext's
  `fontfile`/`textfile` and `ssim`'s `stats_file` open with `fopen` and worked before; `./name` is
  the same file to them. An absolute path is unchanged. On Windows the path is judged as a Windows
  path (`PureWindowsPath`): `C:/x`, `C:\x` and the drive-relative `C:x` keep their form, because
  the drive's colon is escaped and is not a scheme; that branch is tested with `_on_windows()`
  patched, not on Windows. The callers are `caption.py` (subtitles, ass, fontsdir), `graphics.py`
  (ass, fontsdir), `color.py` (lut3d), `stabilize.py` (its own temp path), `_common.drawtext`
  (fontfile, textfile), `_contract.py`'s drawtext check, `_common.emoji` and `_common.probe`
  (temp paths). Test:
  `PictureTests.test_a_relative_path_with_a_colon_inside_a_filter_is_opened_as_a_file`.
- **An output extension the build maps to no muxer is refused before ffmpeg**
  (`output_extension_unknown`, `kind: input`, dry runs included). This changes the sentence in
  "the sweep of A159" above, "An unknown extension (`out.xyz`) is still left to the muxer: telling
  which of FFmpeg's 200-odd muxers a build has would cost a process per run": the cost falls only
  on a run whose extension is outside `runner._COMMON_OUTPUT_EXT` (the extensions the skill names
  and a few every build has), and is paid once per process. For any other extension the build is
  asked: the names from `ffmpeg -muxers` and each one's "Common extensions:" line from
  `ffmpeg -h muxer=NAME` (about 190 short processes, 8 at a time: 1.9 s wall on 4 cores here).
  FFmpeg chooses the muxer by the extension alone, without case, so that list decides; `.mka` is
  in the common set because the Matroska audio muxer shares the name `matroska` and `-h muxer=`
  never lists it. When the build cannot be asked, or one muxer cannot be read, nothing is
  refused and the command runs as before; a `-f` after the last input exempts the output, as it
  does for a missing extension. A static table was not used: it would refuse an extension a
  later FFmpeg adds. Measured on 6.1.1: the 26 tools of `tests/sweep.py` that take `-o`, and
  `join`, `multicam`, `broll`, `grid`, `insert`, `background` and `waveform` by hand, failed as
  `kind: ffmpeg` with a completed dry run and refuse now in both (`render.py --template` refuses
  through its export stage; a project with no export stage has its own rule for the extension). That the two
  listings have the same shape on 7.1 to 9 is not verified; if they do not, the answer is "cannot
  be asked" and the old behaviour. Code: `runner._refuse_unknown_extension()`. Test:
  `BasicsAudit558Tests.test_an_output_extension_no_muxer_has_is_refused_before_ffmpeg`.
- **An input that cannot be media says which it is.** `probe()` refuses a directory
  (`input_is_directory`), an empty file (`input_empty`) and a file ffprobe cannot read
  (`input_not_media`) with a hint each, where it used to pass on ffprobe's lines ("moov atom not
  found" behind a `[mov,mp4,... @ 0x...]` prefix whose address differs on every run). The
  not-media message still opens with "ffprobe failed on PATH", which `verify.py`'s report rows and
  two existing tests match, and keeps ffprobe's own words without the prefix. A file cut short
  and a text file named `.mp4` get the same reason: ffprobe says the same of both. An output this
  run wrote is not judged here (`role="output"` is unchanged), and an ffmpeg failure's stderr
  (`kind: ffmpeg`) still carries the prefixes. Code: `probe._refuse_unusable_input()`,
  `probe._refuse_not_media()`. Test: `test_an_input_that_cannot_be_media_says_which_it_is`.
- **A file the user may not reach is "permission denied", not "not found"**
  (`input_permission_denied`). `os.path.exists()` is false for EACCES as for ENOENT.
  `runner.path_denied()` tells them apart (`os.stat` raising `PermissionError`, or a file that is
  there and not readable), for a real run and a dry run: a dry run used to take such an input for
  an earlier stage's output that was not written yet. A path that is not there stays "input not
  found" with no reason, as before. The same word is used where a tool names a missing file
  itself: `join.py`'s, `audio.py`'s and `render.py`'s problem lists (`reason: "permission
  denied"` beside `"missing"`), `verify.py` (which raised a traceback from `Path.is_dir()`), and
  the SRT, ASS, LUT, chapters, brand, `--image` and layer files. Not changed: side files checked
  with `os.path.isfile()` by tools not listed here. On Windows a directory's mode does not stop a
  search, so only the mocked half of the test runs there. Test:
  `test_a_file_the_user_may_not_reach_is_not_reported_as_missing`.
- **`_contract.py` ends quietly when its reader has gone.** `contract --json | head -40`, README's
  quick start, closed the pipe on a document of about 990 KB; `print()` raised `BrokenPipeError`
  (a traceback, exit 1). It exits 0 with nothing on stderr. The tools write their document with
  `sys.stdout.write()`, which on Python 3.11 here returned normally for a 5 MB document into a
  closed pipe, so they are not changed; other Python versions were not measured. How Windows
  reports a closed pipe to the writer is not verified, and the test is skipped there. Test:
  `test_the_contract_into_a_pipe_that_closes_ends_quietly`.
- **An input name starting with a dash is read as a file.** ffprobe takes its input as a bare
  argument, so `-report` and `-dash.mp4` (given after `--`) were read as options: "You have to
  specify one input file", and for `-report` an `ffprobe-*.log` written into the working
  directory. `runner.guard_input_names()` writes such a name `./name` where the command is built:
  each `-i` value of an ffmpeg command, and the last argument of an ffprobe command when a file
  of that name exists (which tells it from an option such as `-version`). `run()`,
  `run_analysis()`, the frame readers of `_common.alpha` and `_common.probe` and the stream
  checks inside `runner` all pass through it; documents and messages keep the name as given.
  Three places passed such a name on by themselves and are changed too: `default_output()`
  (`./-dash.mp4` gave the default output `-dash_fit.mp4`, which the output guard then refused),
  `verify.py` (its `Path` dropped the `./` before the name reached a step's parser) and
  `report.py` (`--after=-x.mp4`). An explicit output starting with a dash is still refused with
  the `./NAME` hint (`output_looks_like_option`), as decided. Not changed: `verify.py` also drops
  the `./` of a name with a colon (`./co:lon.mp4` is then refused as a URL with the hint to write
  `./`), and a `--font-file` starting with a dash is drawn but its family is not read by
  `fc-scan`. `./name` with a forward slash is a file to ffmpeg on Windows as well (reasoned, not
  run). Test: `test_an_input_name_starting_with_a_dash_is_read_as_a_file`.

## 4.0.0 — a review page for standalone use (#633)

- **It is not one of the tools.** `scripts/_review.py` and `npx ffmpeg-skill review` are the only
  ways in; `contract --json` does not list it and the MCP server does not expose it. A caller that
  owns the review (Velisa) reaches the skill through the contract or the MCP server, so it never
  sees the page and needs no switch to turn it off. Nothing on the machine is searched for
  Velisa: a check for another product's files would break when that product moves them.
- **The page runs nothing.** Re-editing means editing the render project: the page saves the
  edited JSON and shows the `render.py` command and a sentence to give the agent. A page that ran
  ffmpeg would need a local server, and the run would bypass the agent that reports the result.
- **It is one screen built from one document.** `_review.py` measures (ffprobe per source, three
  stills per clip, six stills and a waveform of the output, the dry run's stages) and embeds one
  JSON document with the project, the run's result as given, and each tool's flags from
  `_contract.py --json --static`; `scripts/_review.html` holds the markup, styles and script and
  derives everything it shows from that document. The page measures nothing and recomputes
  nothing: a row is green only where the run's own `ok` is true or `check.py` said PASS.
- **An instruction, not an edit.** Only a clip's in, out and speed change the saved project. A
  tool flag, a caption's text, a marker or a range becomes a line of the instruction with the
  element's number: the agent that runs the tools is the one that knows how a flag maps onto the
  project, and it reports the result.
- **The caption shown after a caption setting is changed is labelled a likeness** and is drawn
  under the picture, not over it: the picture already carries the burned captions of the last run.
- **A file the browser cannot play falls back to the six stills**, and the page says so. No proxy
  is encoded: that would be a second render nobody asked for.
- **A still that ffmpeg could not write says "no still"**, and a measurement the run did not make
  says "not measured": the page shows what was measured, never a placeholder that looks like data.
- **The plan's dry run passes `--overwrite`**: it writes nothing, and without the flag an output
  left by the run being reviewed refused it, so the page said the plan had no stages.
- Code: `scripts/_review.py`, `scripts/_review.html`, `bin/install.js` (`review`). Test:
  `test_the_review_page_shows_the_plan_and_the_result_and_saves_an_edited_project`
  (tests/test_orchestration.py) checks the embedded document and every write guard. The page's own
  script (selection, the instruction, clip edits, playback, the four languages) was checked in
  Chromium at 1440x900 and 1920x1080 with `.claude/skills/review-page-ui/SKILL.md`; CI has no
  browser, so a change to `_review.html` is checked that way before it is pushed.

## After 4.1.0 — one name per meaning, and a guessed name is answered

Decided on 2026-11-20 after an agent building the showcase got about a dozen calls wrong on the
first try. A survey of the 372 tool-specific options showed why: the same thing has several names
(an angle is `--angle`, `--rotate` and `--degrees`), and one name means several things (`--scale`
is pixels on `overlay.py` and a factor on `proxy.py`).

- **The decided names.** An angle is `--angle`. A strength is `--strength`. A text size is
  `--font-size`. A language is `--lang`. A length of time is `--duration`. The shortest pause is
  `--min-silence`. A colour is `--color`, or `--WHAT-color` when a tool has several (`--pad-color`
  for what fills a frame). A size in pixels is `--width`/`--height`; `--scale` is a factor. The
  stream of one input is `--audio-stream`; which input's sound is `--audio`. `--position` takes the
  nine names of `overlay.py` or `X,Y` on every tool.
- **A name two tools share has one type and one list of choices.** A shorter list on one tool is a
  defect to remove, not a variant.
- **Nothing is renamed during the freeze.** The tools that hold an older name keep it
  (`OLDER_NAMES`), and the names that already mean two things are listed (`SAME_NAME_TWO_MEANINGS`).
  Both lists may only shrink: a new option that takes an older name, or a shared name that splits,
  fails `test_option_names_do_not_grow_apart`. When the freeze lifts, a tool takes the decided name
  and keeps the older one as a deprecated alias for a major; a stable tool never loses a name.
- **Until then the answer teaches.** A usage error names, for each `--flag` the tool lacks, the
  options that share a word with it or are a near spelling, the options whose help uses the word,
  and the tools that take a flag of that name (`runner._teach`). A help-text match is reported as
  "mentions", never as "did you mean": a loose match that suggested `--duration` for `--ratio` was
  removed for that reason. Where the meant option's help did not use the other tools' word, the help
  now does (`fit.py --rotate`, `cropdetect.py --seconds`, `grid.py --background`,
  `stabilize.py --shakiness`).
- **A stumble is one line.** `docs/stumbles.jsonl` holds each first-try mistake. A `taught` line is
  replayed by `StumbleLedgerTests`, which reads only what follows `error:` (the usage block lists
  every option, so a name found there teaches nothing). An `open` line is a result that is wrong and
  says nothing; answering it adds a warning to the result, which waits for the freeze.
- **A shortened name of a shared option is refused; a tool's own is kept.** argparse takes any
  unambiguous start of an option name. `freeze.py --time 3` ran as `--timeout 3`. The options every
  tool shares (`runner.SHARED`) are spelled in full, because a guess that lands on one of them
  changes how the run behaves and not what it makes. A tool's own options keep the shortening:
  callers use it (`caption.py --lang`), and removing it everywhere is a break for a major.
- **The ledger is fed by blind guesses.** An agent shown only each tool's name and one line about
  it writes the calls it would try; they are run, and the ones answered with the right option
  become taught lines. The first round was 126 calls: 27 ran.
- Code: `scripts/_common/runner.py` (`_teach`, `add_common`, `apply_common`). Tests: `StumbleLedgerTests`
  (tests/test_contract.py).

## After 4.1.2 — a number outside what its option takes is refused in one place (#645)

- **The help is the range.** A numeric option whose help states `a..b` takes that range and nothing
  else; `apply_common` reads it from the help, so the text an agent reads and the check cannot
  disagree. A help that mentions two numbers some other way writes them as "-40 to -45".
- **A negative needs a help that names one.** `-N`, dB, degrees or stops in the help means a
  negative is a real setting (`audio --gain -3`, `cut --tolerance -1`, `straighten --degrees -2`).
  Elsewhere a negative length, size or count is refused. This looks strict for an option nobody
  thought about; that is the point: say what the negative means in the help and it is taken.
- **Nothing is past a million**, except `audio --length-samples` (an hour at 48 kHz is 172,800,000).
  A million seconds is eleven days and no frame is a million pixels wide. An option that needs a
  tighter ceiling states its range.
- **A value equal to the default is not checked**, so a default outside its own stated range would
  hide; the test reads every stated range against its default instead.
- Zero is not decided here. On most options it is a real setting; the ones where it is not keep
  their own check.
- Code: `scripts/_common/runner.py` (`apply_common`). Test:
  `test_a_number_outside_what_its_option_takes_is_refused_on_every_tool` (tests/test_contract.py).
