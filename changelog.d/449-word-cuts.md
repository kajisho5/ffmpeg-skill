### Added

- `cut.py --words FILE --word-segments 0-4,7-12`: cut on the words of a transcript, by index, joined with `--declick-ms`; `--margin`, `--margin-lead` and `--margin-tail` (no default), the cut on the source's frame grid, and `--onset-search SECONDS`, which moves a start to where the sound measurably rises (`measured: null` and the transcript time when it does not). The result's `word_segments` lists each range's words, transcript times, onset and the times cut (#449). `silence.py` already took `--margin-lead`, `--margin-tail` and the sentence flags.
