### Fixed

- **`silence.py` suggests a `--threshold` that finds the pauses, not one that removes the speech
  (#684).** When nothing sat below the threshold, the hint named the track's mean level + 6 dB; on a
  talk whose room sits above -35 dBFS that is above the speech (`--threshold -9` removed 18.8 s of a
  20 s talk). It names the peak of the quietest `--min-silence` stretch and the threshold 3 dB above
  it now, which on the same talk removes the four pauses and keeps the talk, and the `hint` is the
  third key of the result, after `status` and `wrote`. SKILL.md's "cut out the pauses" row says to
  run again with that threshold.
