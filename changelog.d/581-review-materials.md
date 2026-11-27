### Added

- `silence.py --audition DIR [--audition-seconds 2]` writes a small clip of each join as the cut sounds there
  and `DIR/index.json` (`cut_index`, `source_out`, `source_in`, `output_t`, `clip`, `join_at`, the measured
  `duration`), under `--list` too, so the joins are heard before anything is cut; the result's `audition` (#581).
- `fit.py --fit crop` reports the window it keeps as `crop` (in source pixels and in the scaled frame) in
  dry-run JSON, plans and results (#581).
