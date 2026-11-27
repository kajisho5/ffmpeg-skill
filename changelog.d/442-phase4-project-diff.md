### Added

- `render.py NEW.json --compare-project OLD.json` (#442, phase 4): the expected change comes from
  the difference between the two projects, not from what the agent says it did. A changed caption
  cue, overlay or graphic is its own span, `audio`/`loudness` the whole sound, `brand`/`template`
  the whole picture, `export` both, and a later `in` on the first clip or an earlier `out` on the
  last a removed span; after the render, `check.py --compare` runs against OLD's output with those
  `--expect-changed`/`--expect-audio-changed`/`--expect-removed` values, and a FAIL fails the render.
  The result's `compare_project` holds the derived values, the differences they came from and
  check.py's document. A difference no span states (a clip added or removed, a transition, silence,
  fit, frame, audiogram or snap change) is refused before the first stage
  (`project_diff_not_derivable`).
