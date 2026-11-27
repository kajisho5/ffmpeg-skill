### Added

- `FFMPEG_SKILL_ENCODE` holds a project's house encoder settings (`codec=h264,quality=18,preset=medium,hw=0`): a call that leaves out `--codec`, `--quality`, an x264 `--preset` or `--hw`/`--no-hw` takes them (`export.py`'s delivery presets keep their own codec and CRF), and with `locked` a call that gives one with another value, or `--fast` where a preset is pinned, is refused before ffmpeg runs (`kind: input`, `error.reason: encode_policy`), dry runs included. Unset, nothing changes (#576).
- A result whose run encoded video records the settings its last video encode ran with, `encode: {codec, crf, preset, hw, policy}`, beside `encoder` (on `batch.py`'s rows too), and a `--fast` result says `preview: true` (#576).
