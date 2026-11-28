### Fixed

- An `.avi`, `.wmv` or `.asf` output of an H.264/HEVC encode, or of a stream copy of B-frame video
  from another container, is refused before ffmpeg runs (`kind: input`, reason
  `output_container_codecs`), dry runs included (#754). These containers store no presentation time
  for B-frames, so a reader that seeks, `ffmpeg -ss 0` included, could decode no picture from the
  file: `cut`, `cut --accurate`, `export`, `loop` and `loudness` completed with `verified: false`,
  and the other tools said `verified: true` for the same video. Name a `.mp4`, `.mov` or `.mkv` output.
  An `.mpg`/`.mpeg` output of an AAC encode is refused the same way: MPEG-PS takes no AAC, and every
  re-encoding tool failed in the muxer after the encode started.
  The `.mxf` refusal's reason now says what a read-back shows: MXF stores B-frame H.264 without its
  reorder, so a read-back loses a frame (it said the muxer rejected the dts).
