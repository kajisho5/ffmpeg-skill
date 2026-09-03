# Changelog

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
