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
<!-- contents:end -->

## Time limits

- **`FFMPEG_SKILL_TIMEOUT=0` (or `--timeout 0`) means no limit anywhere**, including the outer
  ceiling on sibling-script runs and the MCP dispatch. 0 is the documented "off" value, chosen so
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
  frame; see "a multi-line `overlay.py --text`" below). The contract lists them as
  `analysis_only`, except `probe`, which is `none` with the note that ffprobe still runs (it writes
  nothing either way); every other tool runs nothing. Code:
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
  Contract: `_contract.DRY_RUN_NOTES["verify"]`.

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
  bounded by `--timeout`). No other tool builds this structure: `join.py`, `multicam.py` and
  `broll.py` open different files without `-ss`; `speedramp.py`, `freeze.py` and `loop.py` split one
  input. Code: `cut._join_chunk()`. Test:
  `test_every_segment_input_of_an_accurate_join_keeps_the_graph_format` (the planned command, any
  FFmpeg) and `test_an_accurate_join_across_a_colour_tag_change_completes` (the run; it only fails
  where the deadlock reproduces).
- **`escape_drawtext()` drops `'` and `%` from burnt-in text** instead of escaping them. Both
  characters have no reliable escape across the FFmpeg versions in CI; a missing apostrophe is a
  known limitation, a broken filter graph is not. Test: `test_drawtext_semicolon_and_quote_render_as_inert_literal_text`.
- **`grid.py` and `look.py` composite an HDR input into an 8-bit SDR picture without a tone map.** Both
  produce comparison/inspection artefacts, not deliverables; `grid.py` prints a note when an input is
  HDR and points to `color.py --to-sdr` for a graded conversion. `join.py` and `broll.py`, whose output
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
  default black pads, white text and black/grey boxes plan what they did. Not converted: a GIF export
  (untagged, and palettegen reads the pad back with the BT.601 it was drawn in), a prores or HDR line,
  a caller's own `--ass` file (its colours and YCbCr header are the file's, as libass/FFmpeg read
  them), and the PNG contact sheets of `look.py`/`scenes.py` (RGB outputs, not tagged video). Code:
  `_common/color.py` (`is_neutral_color`, `rgb_island`), `_common/decision.py` (`drawn_chain`,
  `pad_filters`), and each drawing tool. Tests: `test_a_pad_fill_or_background_lands_in_the_bt709_its_output_is_tagged_with`,
  `test_drawn_text_and_boxes_land_in_the_bt709_their_output_is_tagged_with`,
  `test_a_picture_that_only_passes_through_keeps_its_pixels`, `test_drawn_colours_are_drawn_in_bt709`.
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

## Outputs and files

- **An existing output is refused without `--overwrite`, dry runs included** (2.0; 1.x warned,
  with `FFMPEG_SKILL_NO_OVERWRITE=1` as the opt-in). The refusal is `kind: input` before any
  ffmpeg runs, so a dry run predicts it. A path this same run wrote (two-pass tools,
  copy-then-re-encode fallbacks) is never someone else's file. Code:
  `_common._check_existing_output()`. Test:
  `test_existing_output_is_refused_without_overwrite_and_never_for_its_own_files`.
  Side files count as outputs (2.2.4): caption.py checks the video and every `.srt`/`.ass` it
  will write (`--text`/`--transcribe`/`--write-srt`, generated or `--write-ass` ASS,
  `_offset.ass`) together before speech recognition and the first write; an `_adjusted.srt` or
  emoji-forced ASS, known only once the cues are laid out, is checked where it is written, still
  before that write. Through 2.2.3 a hand-corrected transcript was replaced on a re-run. Code:
  `_common.refuse_existing_outputs()`. Test:
  `test_caption_sidecars_are_refused_like_the_video_without_overwrite`.
- **An existing output is written through a hidden sibling temp file and replaced only on
  success**, so a failed run never costs the caller the file that was there (FFmpeg 5.x truncates
  the output before a filter error). The temp name `.<stem>.ffskill-<pid><ext>` is expected in the
  output directory during a run. Code: `_common._stage_existing_output()`.
- **Subtitle/data tracks are kept where the picture's timeline is untouched and dropped where
  it is retimed; both cases report `dropped_non_av_streams`.** Tools that re-encode the picture
  or audio in place (`fit`, `color`, `graphics`, `overlay`, `audio`, `loudness`, `proxy`,
  `deinterlace`, `denoise`, `freeze --mode extend`) try `run_keeping_subtitles()` first and
  report `false` unless the container refused the track. `export` does the same with its own
  ladder (`_run_keeping_non_av()`): a text track is converted to the container's own (mov_text in
  .mp4/.mov, SubRip in .mkv) rather than refused, a data stream the container refuses (a camera's
  timecode in .mp4) is retried away alone so the subtitles survive it, a platform trim cuts the
  track with the picture, and `non_av_streams` lists every stream kept or dropped. Test:
  `test_export_keeps_the_subtitle_track_for_every_preset_whose_container_holds_one`. Tools that move the timeline
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
Since 2.2.4 they are launched as `render.py` launches its stages: `run_tool()` with
`child_args()` and `--json`, so `--overwrite`, `--timeout`, `--fast` and `--dry-run` reach
them, and a failed stage is re-raised with the child's own kind, exit code and hint (a private
launcher had forwarded only `--dry-run` and called every failure `kind: ffmpeg`). The `_vis` /
`_titled` intermediates are removed on the failure path too, and a missing `--srt`/`--text`
is refused before the visualisation is encoded. Under `--dry-run` only, `--title` passes
graphics.py an explicit `--end` (the source's duration) because the `_vis` file it would probe
was never written; a real run's commands are unchanged. Tests:
`test_waveform_srt_and_title_rerun_with_overwrite`, `test_waveform_title_dry_run_completes`,
`test_waveform_missing_srt_is_input_before_any_encode`.

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
  refuses nothing it took in 2.2.1. When the project's own `fit.aspect` replaces it, the render
  never gives fit.py the frame's aspect and completes, so the export sizes the sequence
  without it. `frame_from_preset()` keeps 2.2.1's looser match (`16/9`, `1.78:1`) for the
  preset size: it drops nothing a 2.2.1 render was sized by.
  A render of several clips gives fit.py the frame's side when the frame gives an aspect and
  one side, and the project's `fit` object gives no width, height or other aspect. Before,
  join.py sized the join at the first clip's aspect and fit.py fitted the aspect inside it
  (`{aspect 9:16, width 1080}` over 16:9 clips rendered 342x608). Every other multi-clip
  project renders as 2.2.1 rendered it: a frame with both sides is already the join's size,
  and a `fit` object with its own size or aspect is fitted inside the joined picture
  (`fit {aspect 4:5}` under `{aspect 9:16, width 72}` over 16:9 clips renders 32x40 against a
  72x128 sequence, where one clip renders 72x90). Filling the frame's sides in there too
  overrode the `fit` object (`fit {width 540}` under a 1080x1920 crop frame rendered 540x1920,
  half the picture cut away). Which of `frame` and `fit` wins is deferred to a minor release.
  Three render gaps remain, all from join.py sizing the join before fit.py reframes it. (1)
  With several clips, one side and no aspect, join.py rounds an odd side down where fit.py
  rounds up (`{width 100}` over 4:3 renders 100x74, the sequence is 100x76). (2) join.py pads
  every clip into the joined frame before fit.py crops: the frame's own W x H when it gives
  both sides (as every template frame does after `frame_from_preset()`), else the first clip's
  aspect. So a multi-clip `frame.fit: crop` render keeps bars on every clip of another aspect
  than that frame, even when all the clips share one aspect, while the timeline states
  `fill`, the project's choice (the timeline follows the project, not the render's drift).
  Passing `frame.fit` to join.py would change rendered output and waits for a minor release.
  (3) The `fit`-object case above.
  Tests: `test_sequence_frame_is_the_frame_the_render_delivers`,
  `test_a_multi_clip_render_delivers_the_sequence_size`,
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
  confidently wrong one. Only when no Whisper engine is installed, or every one failed, does
  Parakeet run on English assumed, and then the result's top-level `notes` says the transcript is
  wrong if the speech is not English -- `transcription.routing` alone was too quiet for a caller
  that reads `verified`. "Goes first" means a Whisper engine that detects the language: whisper.cpp
  is passed `-l auto` when nothing named the language (its own default is `-l en`, which decoded
  every unnamed language as English, in 2.5.1 too), else the named or detected one, and an
  English-only Whisper model (`base.en`, `ggml-*.en.bin`, quantised too: `ggml-base.en-q5_1.bin`) does
  not count as one for routing. Known gap: with whisper.cpp as the only engine and such a model, undetected
  speech is decoded as English and the run adds no note.
  A named `--engine parakeet-*` runs as asked, with no note, and so does a Parakeet model named
  with `--model` or `PARAKEET_MODEL`: a multilingual (v3) one assumes nothing and gets no note; an
  English-only one named with `--model` gets the note, pointing at a v3 model rather than at a
  Whisper engine, which cannot load it. Measured on 8 min of LibriSpeech
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
  `test_cut_precision_keeps_its_formula_and_least_exact_precision_is_beside_it`,
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
  `test_an_mp4_copy_shifts_to_zero_unless_the_edit_list_is_asked_for` (the default),
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
  `test_an_mp4_copy_shifts_to_zero_unless_the_edit_list_is_asked_for`,
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
  `test_a_reencoded_cut_of_an_sdr_hevc_source_is_h264_unless_keep_hevc_is_asked_for` (the default
  pin), `test_a_reencoded_cut_of_an_sdr_hevc_source_stays_hevc`,
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
  `test_a_short_constant_clip_copies_by_default`,
  `test_a_suspected_but_constant_source_reencodes_by_default_and_says_sampled_would_copy`,
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
  `least_exact_precision`'s (the least exact segment).

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
  `--accurate` still uses `make_zero`: `asetpts` already starts the samples at 0, and the
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
- **`silence.py` selects the sound with two `ametadata` filters, not `aselect`.** 8.0 and 8.0.1's
  `aselect` passes every frame. The first `ametadata` tags a frame when the same `between()`
  expression (as a timeline `enable`, so the same per-frame `t`) is true and the second keeps the
  tagged frames, which is what `aselect` keeps. `asplit` + an `atrim` per range + `concat` was
  tried and works, but costs about 81 command bytes per range against 56: at `--max-cuts 400` on
  an hour-long file that is past Windows' 32767-character command line. `asegment`'s timestamp
  mode compares pts with a sample count and is right only for a stream that starts at 0. Code:
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
  3.9 job stay until 3.0. Tests: `test_python_3_9_is_deprecated_on_every_surface`,
  `test_doctor_prints_the_python_3_9_warning_on_stderr_only`, `test_installer_warns_once_on_python_3_9`.

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
  release number and gets no line, the same rule as the security advisory. Tests:
  `test_ffmpeg_5_is_deprecated_on_every_surface`, `test_doctor_prints_the_ffmpeg_5_warning_on_stderr_only`.

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
  that fix. Code: `export.py`. Test: `test_export_measures_the_length_its_preset_promises`.
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
  `--dry-run`. Its output times are the sums of the kept ranges, the same arithmetic the render
  uses. Test: `test_silence_writes_a_map_from_source_to_output_times`.

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
