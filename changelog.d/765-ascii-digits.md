### Fixed

- `caption.py` keeps a cue whose text is only full-width or other non-ASCII digits before a timing
  line with no blank line above it; it was taken for the next cue's index and lost from every copy
  the tool wrote (#765). A timing line written in such digits, which FFmpeg's SRT reader cannot
  read, is refused as `kind: input` before any command, dry runs included, with a hint to write
  the times in ASCII digits. A `--color` alpha and a `.cube` LUT written in such digits are
  refused the same way instead of failing inside FFmpeg.
