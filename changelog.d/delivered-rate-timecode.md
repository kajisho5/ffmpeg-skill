### Fixed

- Deinterlace field mode and export presets that force a frame rate now count
  start timecode at the delivered rate (#470). A 25 fps source labelled
  `01:00:00:12` is written as `01:00:00:24` at 50 fps or `01:00:00:14`
  at 30 fps. An export that preserves the source rate keeps the original label.
