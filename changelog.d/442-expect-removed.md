### Added

- `check.py --expect-removed START-END` (with `--expect-changed` or `--expect-audio-changed`): a cut
  is checked against the reference with the declared spans taken out (#442, phase 3). Both
  `change_scope` and `audio_change_scope` gain `removed`; spans that do not match the cut FAIL.
- `check.py --expect-audio-changed` compares Matroska files too: they store no length per track,
  and the container's now stands for it (before, the row FAILed as not compared).
