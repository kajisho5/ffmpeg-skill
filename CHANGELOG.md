# Changelog

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
