### Added

- `fit.py --zoom in|out` makes a timed push-in or pull-out on a video clip: `--zoom-amount` (default 1.3), `--zoom-start` and `--zoom-duration` in output seconds, toward `--crop-x`/`--crop-y` (centre by default), the start zoom before the move and the end zoom held after it. Each frame is scaled and cropped back, so the zoom keeps every frame and its timestamp; the result's `zoom` reports the move and `zoom.check` compares the output's frame count, timestamps, duration and rate with the source's, or says it did not measure them (#647).
