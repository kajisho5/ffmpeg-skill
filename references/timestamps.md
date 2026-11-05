# Timestamp grammar

Timestamp flags (`--start`, `--end`, `--at`, `broll.py --from`, `--duration`, `--offset`, and the times in cue and chapter files) take seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` or SMPTE `hh:mm:ss:ff` with `@fps` (`00:01:02:15@29.97`) — an NLE cue sheet pastes as-is when its timecode is non-drop-frame (a `;` drop-frame timecode is refused in a flag and in a `--text` cue file); length flags (`--min-silence`, `--margin`, `--fade`) are plain seconds. `render.py --from` takes a stage name, not a time.
