### Added

- `render.py --preview`: the whole project laid out at its own frame (every stage at the `--fast` preset), then
  made small by `proxy.py` (the short side 540, never enlarged) as `<output>_preview.mp4`; the output itself is
  not written, the check stage is not run, and the result says `preview: true` (#581). It refuses
  `--compare-project`, which checks a full-size delivered render.
- `cut.py --audition DIR [--audition-seconds 2]`: a small clip of each join and `DIR/index.json`, cut from the
  written cut, so a stream copy is heard at the keyframes it joined on; `audition.path` names the cut's mode (#581).
- `render.py` results and dry runs list `clips`: each clip's `speed_factor` and, for a one-clip project, the fit
  stage's `crop` or `placed`; the fit stage's `timing` too (#581).
- `fit.py --fit pad` and `--fit blur` report where the picture lands in the frame as `placed` in dry-run JSON,
  plans and results (#581).
