### Fixed

- `overlay.py` no longer takes `--emoji-assets`, `--emoji-scale` or `--emoji-max` silently: it draws text with drawtext and never read them, so a value given there did nothing and nothing said so. Each now prints one warning and adds `deprecated_option` to the result's `diagnostics.warnings`. A guard test (tests/test_guards.py) reads every tool's parser and fails on an option nothing reads that `deprecated` does not list (#749).
