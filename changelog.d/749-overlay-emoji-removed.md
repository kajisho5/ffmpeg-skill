### Changed

- `overlay.py` no longer takes `--emoji-assets`, `--emoji-scale` or `--emoji-max`: they never had an effect there (it draws text with drawtext), were deprecated in 4.20.2, and are removed after one whole minor as the beta rule says. `caption.py` and `graphics.py` keep them (#749). The warning code `deprecated_option`, which only they recorded, leaves `contract --json`'s `diagnostic_codes`.
