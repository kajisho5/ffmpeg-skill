### Fixed

- A sound-only render of an MPEG-TS or MPEG-PS counts from the file's start too: on a `.ts`, `.m2ts` or `.mpg` whose sound starts after its picture, `cut.py`, `loudness.py`, `audio.py` and `silence.py` wrote a `.wav` without the sound's lead (a burst at 1.0 s came out at 0.72 s), and `check.py --content` put each dropout that much early (#787).
- `loop.py` on an MPEG-PS whose sound starts late keeps its first repeat whole: the concat demuxer gives such a file's video no start time, so the sound's lead was cut off the first repeat (15.72 s for 16 s, `verified: false`) (#787).
