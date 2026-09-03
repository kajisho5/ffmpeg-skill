# Changelog

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
