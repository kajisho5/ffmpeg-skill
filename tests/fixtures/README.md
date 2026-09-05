# ffmpeg listing fixtures

Captured or constructed stdout of `ffmpeg -hide_banner -filters / -encoders / -bsfs`, used by
`tests/test_contract.py` to prove that capability detection (`doctor`) reads every layout FFmpeg
has printed.

| File | Origin |
|---|---|
| `ffmpeg_filters_6.1.txt`, `ffmpeg_encoders_6.1.txt`, `ffmpeg_bsfs_6.1.txt` | captured from FFmpeg 6.1.1 (Ubuntu 24.04) |
| `ffmpeg_filters_7.1_constructed.txt` | constructed: FFmpeg 7.x prints the 6.x layout (three flag characters `T.. .S. ..C`) |
| `ffmpeg_filters_8.0_constructed.txt` | constructed from the 6.1 capture in the FFmpeg 8 layout: two flag characters (`T. .S`), the `..C = Command support` column removed |
| `ffmpeg_filters_garbage.txt` | not a listing at all: must yield `unknown`, never `missing` |

"Constructed" files reproduce the row format of that version (`fftools/opt_common.c`, `show_filters`)
with the 6.1 filter set; they are not captures of that binary. Replace them with a capture when one
is available and keep the name so the tests keep working.
