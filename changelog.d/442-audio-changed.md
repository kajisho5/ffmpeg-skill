### Added

- `check.py --expect-audio-changed SPAN|none` (with `--compare`): the sound's side of `--expect-changed` (#442, phase 2).
An `audio_change_scope` row and document say which 0.1 s windows of the two decoded tracks differ, graded against the
declared spans; an untouched AAC re-encode of the same sound at 64 kbps or more is not a change.
