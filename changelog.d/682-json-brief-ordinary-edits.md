### Changed

- SKILL.md asks for `--json-brief` on an ordinary edit (`--json` for the probe or the command lines): over eight
  ordinary edits the brief document is 0.29 of `--json`'s bytes. The brief document keeps a verification step
  that did not pass, so `verified: false` carries its reason (#682).
