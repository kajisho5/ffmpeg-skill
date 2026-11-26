### Added

- `check.py --content` adds a `frame timing` row (#574): every frame's time, read from the packets,
  against the file's median step. A gap WARNs with how many frames are missing and where; a repeated
  time FAILs.
