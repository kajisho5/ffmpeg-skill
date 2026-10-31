# Timestamp grammar

Timestamp flags (`--start`, `--end`, `--at`, `--from`, `--duration`, `--offset`, and the times in cue and chapter files) take seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` or SMPTE `hh:mm:ss:ff` with `@fps` (`00:01:02:15@29.97`) — paste an NLE cue sheet as-is; length flags (`--min-silence`, `--margin`, `--fade`) are plain seconds.
