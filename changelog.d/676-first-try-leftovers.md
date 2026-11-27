### Fixed

- A usage error's `try:` line is printed only when the tool's own parser takes the corrected command: 10 of the taught first-try mistakes were answered with a command that failed its own usage check (`caption.py --soft` given as `--mode`, `--size 1920x1080` as `--width`, `color.py --grade` as `--source-alpha-mode`), and `color.py --correct --brightness 0.1` with `--peak 0.1`, which ran (#676).

### Added

- `speedramp.py --speed FACTOR [--start TIME] [--end TIME]`: one span at that speed and the rest at 1x, the same command as the three `--segment` pieces it stands for (#676). A `--speed` that is not one factor is refused with the `--segment` form.
- `color.py` and `batch.py` answer more first-try names: `--grade` (`--correct`), `--brightness` (`--exposure`, `--gamma`), `batch.py --config` (`--recipe`), `--parallel`/`--workers` (`--jobs`), `--no-cache` (`--force`); recorded in `docs/stumbles.jsonl` (#676).
