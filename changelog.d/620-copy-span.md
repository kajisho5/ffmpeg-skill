### Added

- **A stream copy is verified against the span its keyframes allow, and says where it landed** (#620, the owner's decision of 2026-11-26 as a freeze exception).
  `cut.py` reports `snapped_segments` (`[[in, out], ...]`, read against `requested_start`/`requested_end`/`requested_segments`),
  holds the written length to the sum of those spans (the step `copy_span`: one frame plus the source's reorder depth per part,
  instead of `--tolerance`; a miss is `verified: false`), and adds the warning `copy_drift_large` when a copy's in or out
  sits more than 0.25 s from the request, naming `--accurate`. `docs/contract.md` states what a post-export mismatch does, tool by tool.
