### Fixed

- An EDL, an SRT/ASS, a chapter or description list, a project or a report a tool writes itself is
  written through `write_sidecar()`: an existing target is written in place under its output lock,
  after the same replace-time comparison as an ffmpeg output, so its inode, mode, group, access
  ACL, hard links and any symlink stay as `open()` left them and a file another process put there
  after the check is refused (`output_exists`) instead of overwritten unless `--overwrite`
  consents; a target the check saw absent is staged beside it and installed with `os.link()`, so
  a file that appeared in the gap is never replaced (a filesystem without hard links creates the
  name exclusively and copies the staged file into it; `--overwrite` is the consent to replace
  that path); and a failed write or pair leaves the previous file whole (#696, #743 review).
