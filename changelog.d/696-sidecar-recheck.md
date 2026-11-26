### Fixed

- An EDL, an SRT/ASS, a chapter or description list, a project or a report a tool writes itself is
  staged and put in place through the same replace-time check as an ffmpeg output: a file another
  process created or edited at that path, detected at the locked comparison, is refused
  (`output_exists`) instead of overwritten unless `--overwrite` consents; a target the check saw
  absent is never replaced when one appeared: the link install fails, and a filesystem without
  hard links creates the name exclusively and copies the staged file into it (`--overwrite` is
  the consent to replace that path); an existing target keeps the mode, group and access ACL it
  had when the staged file took them (a writer that may not give the new file that group or copy
  that ACL is refused with `output_group_not_settable` or `output_acl_not_preserved` rather than
  replacing the file with one in another group or whose named users' permissions changed); and a
  failed write or pair leaves the previous file whole (#696).
