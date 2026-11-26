### Fixed

- An EDL, an SRT/ASS, a chapter or description list, a project or a report a tool writes itself is
  staged and put in place through the same replace-time check as an ffmpeg output: a file another
  process created or edited at that path, detected at the locked comparison, is refused
  (`output_exists`) instead of overwritten unless `--overwrite` consents; a target the check saw
  absent is installed with a link that fails if one appeared (where the filesystem has hard links
  and `--overwrite` did not consent); an existing target keeps its mode and its group (a writer
  that may not give the new file that group is refused with `output_group_not_settable` rather
  than replacing the file with one in another group); and a failed write or pair leaves the
  previous file whole (#696).
