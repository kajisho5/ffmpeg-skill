### Fixed

- A 0 that `export.py --duration`, `--pad-blur`, `caption.py --font-size` and `--emoji-scale` (also in `graphics.py`) cannot take is refused as outside the option's range, instead of being read as the whole clip, radius 1, the default size or scale 1.0 (#749).
