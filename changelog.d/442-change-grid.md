### Added

- `check.py --change-grid 32|64|96` (with `--expect-changed`): the frame in finer tiles, 30 or 20 px
  at 1080p, each grid with its own floor (24, 32, 48), so a change smaller than a 60x60 tile is
  found; the row names the grid (`floor 32 on 64x36 tiles`) and `change_scope.tile` holds it. A
  grid whose tiles would be under 20 px is refused (#442).
- The change floor surveyed across libx264, libx265, libsvtav1, libaom-av1, libvpx-vp9 and ProRes
  at 1080p, 720p and 480p (`tests/change_floor_survey.py`, `docs/design-decisions.md`): the
  default of 24 stays. Hardware encoders were not measured.
