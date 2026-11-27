### Changed

- CI runs in two stages: the macOS and Windows test jobs start only after the Linux jobs pass on a pull request, so a change that breaks a test costs Linux minutes only; on `main` every job still runs (#680).
- `tests/run_parallel.py --first ITEM[,ITEM]` starts the test modules of the changed files first (a test module, a file, or `git:REV`); the map from each tool to its test modules is read from the tests. CI passes `git:HEAD^1` (#680).
- The "ffmpeg next" workflow runs the probe and the whole suite every week on the newest FFmpeg on the Windows feed, and opens or comments on one issue with the version and the failing tests' names when it fails (#680).
- A test command killed at the harness limit has its ffmpeg killed first, so the failure message carries the tool's own report with ffmpeg's stderr tail; on Windows the whole tree is ended before the pipes are read (#680).
