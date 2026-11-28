### Added

- A local, opt-in record of how the tools are used (#689). Off by default: `FFMPEG_SKILL_USAGE_LOG=1`
  (or an absolute file path) makes every tool run append one JSON line to
  `~/.local/state/ffmpeg-skill/usage.jsonl` (`$XDG_STATE_HOME`; `%LOCALAPPDATA%` on Windows) holding
  exactly the tool, the skill version, `completed` or `failed`, the failure's `error.kind` and
  `error.reason`, the names of the options given, the seconds the run took and the FFmpeg major
  version. Never an option's value, a path, a file name or text; nothing leaves the machine.
  `_contract.py doctor --usage` prints the counts as JSON. A log path that is not absolute, is outside
  `FFMPEG_SKILL_ROOTS`, is one of the run's files or cannot be written is a warning on stderr, never a
  failed run. PRIVACY.md says what is written, where, and how to delete it.
