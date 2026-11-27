### Fixed

- A sound-only render of an MPEG-TS or MPEG-PS counts from the file's start too: on a `.ts`, `.m2ts` or `.mpg` whose sound starts after its picture, `cut.py`, `loudness.py`, `audio.py` and `silence.py` wrote a `.wav` without the sound's lead (a burst at 1.0 s came out at 0.72 s), and `check.py --content` put each dropout that much early (#787).
