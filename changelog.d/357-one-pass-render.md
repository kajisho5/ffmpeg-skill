### Changed

- `render.py` encodes a project of one uncut clip whose stages are fit, captions and loudness before a
  platform export (a `--template` render with `--cues`) once instead of once per stage: fit, caption and
  loudness plan their own filters, the captions against the frame fit plans and the loudness on the
  source, and the export reads the source through them. One lossy generation instead of three, and on a
  30 s 1080p reels render 56 % of the time with the machine loaded (31 % in two runs on a quieter machine). The result's `render_path` says `fused` or `staged`
  and `render_path_reason` why a project was staged; `--staged` keeps one file per stage (#357).
