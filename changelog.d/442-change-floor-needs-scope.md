### Changed

- `check.py --change-floor` without `--expect-changed` is refused, as `--change-grid` is: neither is
  used without it (before, the floor was taken and ignored) (#442).
