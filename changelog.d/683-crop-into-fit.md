### Changed

- `crop.py` is folded into `fit.py` (#683): `fit.py --rect W:H:X:Y` cuts an exact pixel box with no scaling (`--rect W:H` is centred) and writes the file `crop.py` writes. `crop.py` stays as an alias (`alias_of: fit` in the contract): every command, its MCP name and its arguments keep working, and it leaves the tool count (now 41), SKILL.md's table and `tools/list`. `crop.py` also takes `--rect W:H:X:Y`, and `--width W --height H` without `--x/--y` (or with `--center`) is a centred box (#676). `cropdetect.py` now hands its rectangle on as `fit.py --rect`.
