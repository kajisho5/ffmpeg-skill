### Fixed

- A SIGTERM or Ctrl-C that reached a tool while it was making or removing an output lock left the
  lock beside the output (`.NAME.ffskill-lock`): a `verify.py` step stopped by its `--timeout`
  could leave it in `--out`, which made a macOS CI run fail once. A signal that arrives then, or
  between a child's start and the moment the tool starts tracking it, is now handled once that
  step ends, so the lock is removed and the child (ffmpeg, a sibling script under `run_tool()`,
  a `verify.py` step, a `batch.py` step) is stopped with its partial output instead of running on
  (#465).
