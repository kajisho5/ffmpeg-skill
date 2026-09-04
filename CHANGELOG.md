# Changelog

## 0.8.4 — three repeats, independent grading

The 24-prompt evaluation was run three times (72 agent runs, `evals/results/iteration-2-4.json`) and every run was graded by a separate model (`evals/results/iteration-2-4-independent-grades.json`): routing 72/72, honest 72/72, user's language 72/72, report format 71/72, visual check whenever the picture changed 24/24, mean quality 4.9 / 5. Script choices were identical across repeats; only defaults (crop vs pad, silence margin) varied.

- `overlay.py --fade` without `--start`/`--end` now fades in at 0 and out at the end of the video (it was silently ignored; found by an agent during the runs).
- `--dry-run` no longer prints "wrote <file>" for a file that was not written (central fix in `_common.info`).

## 0.8.3 — internals and triggering

- `_common.py`: the shared flag state is an explicit `Context` object (`STATE.dry_run` etc., dict-style access kept), `run()` is split into recording, dry-run, captured and progress paths with one failure handler. Behaviour unchanged: 54/54 tests and the sync benchmark give identical numbers before and after.
- `sync.py`: the 35 % minimum-overlap and the square-root overlap weight are named constants with the benchmark rationale (what 0.2 / 0.5 and exponents 0.25 / 1.0 did) written next to them.
- Trigger tests (`evals/trigger/`): 10 should-trigger and 10 should-not requests judged by an independent model against a catalog with four decoy skills. 20/20 on this description.

## 0.8.2 — second agent-run evaluation

24 prompts (12 English edits, 8 Japanese edits, 4 that must be declined) run by independent agents against the 0.8.1 skill (`evals/agent_prompts_24.json`, `evals/grade_runs_24.py`, `evals/results/iteration-2.json`). Routing 24/24, honest refusals 4/4, Japanese reports 9/9, visual check whenever the picture changed 8/8, mean 6.5 commands per job.

- `caption.py --text` now writes the generated SRT beside the output file, not beside the source.
- `probe.py` accepts the common flags (`--json`, `--field` etc.) like every other script.
- `audio.py`: `--music-fade-out` fades only the bed; `--fade-out` fades the whole mix (previously both were applied at once). `render.py` project audio gained `music_fade_out`.
- SKILL.md: how to find a CJK font before burning Japanese captions.
- Tests for all of the above; render test no longer depends on a clean output directory.

## 0.8.1 — skill craft

The skill file itself, measured. Six realistic prompts were run by independent agents with the old and the restructured SKILL.md (`evals/agent_prompts.json`, `evals/grade_runs.py`, results in `evals/results/`).

- SKILL.md rewritten for the agent, not as a catalogue: a description that says when to trigger; body 402 → 169 lines with workflow, what to ask vs assume, request→script map, report format and "looks right but is wrong" pitfalls; per-script CLI reference moved to `references/scripts.md`, real-device notes to `references/devices.md` (both installed and packaged).
- Results: routing 100 % for both versions; mean commands per job 9.0 → 7.7 (the Reels job went from 16 commands with a forced redo to a single `render.py` pass); report format followed 4/6 → 6/6.
- Found and fixed from the transcripts: `check.py` warned on untagged 8-bit H.264 and agents added a pointless retag (now PASS); `look.py --at` stamped 00:00:00.000 on every frame (now the requested time); the "fix FAILs" instruction made an agent boost -44 LUFS park ambience by 30 dB (check step reworded, pitfall added).

## 0.8.0 — validation release

Measured instead of assumed. New `tests/corpus.py` pulls public real-device videos (GoPro HERO 4K 10-bit, DJI 4K60 no-audio, two iPhones incl. Dolby Vision 4K60, two Android screen recordings incl. 18 fps VFR and 120 fps, an HDR10 PQ test pattern, a 24p clip, and Blender's Tears of Steel) and runs `verify.py` over them; `tests/bench_*.py` score algorithms against known ground truth.

- `sync.py`: normalised cross-correlation over the overlap (prefix-sum energies) with a runner-up-aware confidence. Lags with under 35 % overlap are ignored and scores carry a sqrt(overlap) weight so partial coincidental matches cannot beat the true alignment. Benchmark on real dialogue/music (±30 s offsets, gain, noise, EQ): 120 s windows 40/40 within 10 ms (max 1.1 ms); 60 s stress windows went from 86 % to 95 %, with 4 of the 5 remaining misses flagged by confidence < 0.3.
- `scenes.py`: cuts are now one-frame spikes (score above threshold and > 3× the neighbouring median), not any frame over a threshold; motion, flashes and pans stop registering. `--ratio` added. Benchmark on 53 hard cuts between single-take corpus clips: precision 0.95, recall 1.00 (F1 0.97) at the default threshold 8; 0.98 / 0.94 at 12.
- `loudness.py`: silent input is reported (`"silent": true`) instead of crashing; normalisation refuses with a clear message.
- `verify.py`: tone-maps the HDR-preserved cut instead of the whole file (a 10-minute 4K HDR source timed out).
- Corpus results: 90/92 verify steps pass on first run; both failures fixed above. Silence benchmark: 0 missed gaps, ≤1 ms leftover silence over 20 cases.
- SKILL.md: sync guidance now cites the benchmark and the 4× window rule.

## 0.7.0

- `mcp/server.py` (new): the whole toolkit as an MCP server over stdio (JSON-RPC 2.0, standard library only). Every script is a tool; named args or raw argv; results as structured JSON. Installed alongside scripts by `npx ffmpeg-skill`.
- `batch.py` (new): apply a step recipe or a render project to every file in a folder, content-hash cache so re-runs only touch changed files, `--watch` polling.
- `caption.py --transcribe`: optional local speech-to-text bridge (whisper.cpp `whisper-cli`, faster-whisper, or openai-whisper if present). Never required; a clear install hint otherwise.
- Tests: 49 end-to-end cases.

## 0.6.0

- `graphics.py` (new): motion-graphics templates with no image assets — lower-third (slide in/out), title card, chapter chip, progress bar, countdown, corner bug — coloured from brand.json.
- `brand.json` support: fonts, colours, logo (position/scale/opacity), safe margin, caption defaults. `caption.py --brand`, `overlay.py --brand --logo`, `graphics.py --brand`, and a `"brand"` key in `render.py` projects (plus a `graphics` stage and `{"logo": true}` overlays).
- `report.py` (new): single-file HTML delivery report with before/after contact sheets, media facts, loudness, compliance table and the commands run.
- Tests: 46 end-to-end cases.

## 0.5.0

- `render.py` (new): declarative edits from one `project.json` (clips → join → silence → fit → captions → overlays → audio → loudness → export → check). `--init` writes a starter, `--dry-run` prints every command, `--stop-after` for iterating.
- `scenes.py` (new): scene changes (scdet) and audio peaks, highlight proposals sized to a target duration, `--edl` for `cut.py --segments`, per-scene contact sheet.
- `check.py` (new): pre-delivery compliance for youtube / shorts / reels / tiktok / x / linkedin / broadcast / podcast / custom: duration, aspect, resolution, fps, VFR, codec, pixel format, colour/HDR, file size, loudness, true peak, with the fix command per failure.
- `evals/`: 24 natural-language routing tasks with expected scripts, plus a transcript scorer.
- `.github/workflows/ci.yml`: 3-OS matrix, manual trigger only until the Actions quota resets.
- `join.py`: `--width` alone keeps the first clip's aspect; `--fast` no longer breaks `export.py` presets.

## 0.4.1

Fixes found by running `verify.py` on a real iPhone clip (Dolby Vision 8.4 / HLG, 10-bit HEVC, 60 fps VFR, portrait rotation, extra metadata tracks):

- HDR sources now stay HDR through every re-encode (`cut`, `fit`, `caption`, `overlay`, `silence`, `join`, `multicam`, `sync`): HEVC Main10 with the source's HLG/PQ tags instead of an 8-bit H.264 file mislabelled BT.709. Use `color.py --to-sdr` when you want SDR.
- Audio mapping uses the first audio stream only (`0:a:0?`); iPhone `.mov` files carry timecode/metadata tracks that broke `-map 0:a?`.
- `probe.py --analyze` normalises 10-/12-bit levels to an 8-bit scale before the Log heuristic.
- `look.py` tone-maps HDR frames for display so the agent judges representative colours.
- `verify.py` runs `color --to-sdr` on the original file and adds an "hdr preserved" check on the accurate cut.

## 0.4.0

- `verify.py` (new): real-footage verification kit — runs the toolchain over the user's own files and reports PASS/FAIL per step, Markdown and JSON.
- `multicam.py` (new): align N cameras/recorders by audio (drift correction optional), switch between them from a time list or automatically, pick the audio source.
- `probe.py`: Dolby Vision detection (`dolby_vision`, `hdr_format`), `--analyze` samples picture levels and flags Log-looking footage.
- `color.py`: `--strip-dovi` removes the Dolby Vision RPU losslessly; HLG and DV 8.4 sources verified through `--to-sdr`.
- `caption.py`: karaoke word timing now follows speech energy in the audio (`--karaoke-timing energy|even`).
- `--progress` (percent / ETA) and `--fast` (preview preset) on every script.
- Tests: 38 end-to-end cases.

## 0.3.0

- `look.py` (new): contact sheet with timecodes, single-frame extraction, side-by-side before/after PNGs — the agent can inspect its own output.
- `silence.py` (new): silence detection and frame-accurate removal with margins, `--list` and `--edl` cut-list export compatible with `cut.py --segments`.
- `join.py` (new): xfade/acrossfade transitions between clips with automatic normalisation of size, fps, pixel format and audio layout (silent track synthesised when missing).
- `--dry-run` and `--json` on every script: print the ffmpeg commands without running, or emit a structured result (output, probe, commands).
- SKILL.md workflow now includes plan (`--dry-run`) and visual verification (`look.py`) steps.

## 0.2.0

- `color.py` (new): HDR10/HLG → SDR BT.709 tone mapping (zscale + tonemap), 3D `.cube` LUTs with strength blending, metadata-only colour retagging.
- `audio.py` (new): voice clean-up chain, FFT denoise, music bed with sidechain ducking, fades, 5.1 → stereo downmix, mono/stereo layout, track replacement.
- `sync.py`: coarse-to-fine search (20 ms FFT → 1 ms direct) and `--fix-drift` clock-drift measurement and correction by resampling; roughly 5x faster on the default window.
- `caption.py`: `--animate fade|pop|slide` and `--karaoke` word-by-word highlight, generated as a styled ASS sized to the video; SRT input can be animated too.
- `fit.py`: `--smooth blend|interpolate` for slow motion.
- VFR sources are conformed to constant frame rate automatically by every re-encoding script; `cut.py` switches to accurate mode on VFR.
- `probe.py`: `hdr`, `hdr_format`, `bit_depth` fields.
- `export.py`: warns when an HDR source is exported without tone mapping.
- Tests now cover VFR, rotated, 5.1, 10-bit HDR10 HEVC and drifting sources.

## 0.1.0

- Initial release: probe, cut, caption, fit, sync, loudness, overlay, export; npx installer; demo and tests.
