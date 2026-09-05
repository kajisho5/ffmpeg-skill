# ffmpeg listing fixtures

Captured or constructed stdout of `ffmpeg -hide_banner -filters / -encoders / -bsfs`, used by
`tests/test_contract.py` to prove that capability detection (`doctor`) reads every layout FFmpeg
has printed. CI uploads each runner's listings and `doctor --json` as the `ffmpeg-listings-<os>`
artifact; copy a new layout from there into this directory and add it to the test table.

| File | Origin |
|---|---|
| `ffmpeg_filters_6.1.txt`, `ffmpeg_encoders_6.1.txt`, `ffmpeg_bsfs_6.1.txt` | **captured** from FFmpeg 6.1.1 (Ubuntu 24.04 apt; same output as the ubuntu-latest CI runner) |
| `ffmpeg_filters_9.0.1_windows.txt`, `ffmpeg_encoders_9.0.1_windows.txt`, `ffmpeg_bsfs_9.0.1_windows.txt` | **captured** from FFmpeg 9.0.1 (gyan.dev essentials build, windows-latest CI runner, CRLF line endings kept as captured) |
| `ffmpeg_filters_7.1_constructed.txt` | **constructed**: the 6.1 capture unchanged, kept under its own name so the version matrix names FFmpeg 7 explicitly (7.x prints the 6.x layout: three flag characters `T.. .S. ..C`) |
| `ffmpeg_filters_8.0_constructed.txt` | **constructed** from the 6.1 capture with two flag characters per row (`T. .S`) and no `..C = Command support` legend line. Not a capture of an FFmpeg 8 binary. |
| `ffmpeg_filters_garbage.txt` | not a listing at all: must yield `unknown`, never `missing` |

What the real FFmpeg 9.0.1 capture shows, and the constructed 8.0 file did not guess: the legend
still prints three-character keys (`T.. = Timeline support`, `.S. = Slice threading`) while the
rows carry two (` TS aap  AA->A`), and a ` ------` separator line follows the legend. The parser
keys on the io-spec token (`A->A`, `AA->A`, `|->V`, `N->N`) and ignores the flag column and the
legend, so both files parse; the real capture is the one that proves it. On the macos-latest
runner (Homebrew FFmpeg 8.1.2) `doctor --json` in the CI log parsed 481 filters and reported
`filter:drawtext` / `filter:subtitles` missing, which is true of that build (no libfreetype /
libass), not a parser failure.

"Constructed" files reproduce a row format with the 6.1 filter set; they are not captures of
that binary. Replace one with a capture when it is at hand and keep the name so the tests keep
working.
