### Fixed

- An `.flv` output of an H.264/HEVC encode, or of a stream copy of B-frame video from another
  container, is refused before ffmpeg runs (`kind: input`, reason `output_container_codecs`), dry
  runs included (#762). With B-frames a seek to the file's start fails, so `ffmpeg -ss 0` decoded no
  picture from it, while 23 of the 26 single-input tools said `verified: true`. Name a `.mp4`,
  `.mov` or `.mkv` output; a copy of an FLV into FLV is still written.
- A NUT, FLV or MPEG-TS (`.ts`, `.m2ts`, `.mts`) stream's length is read from where its last
  packets end (#762). NUT and FLV state none, so `loudness.py` said "the output reports no
  duration" for a good NUT and `loop.py` read 6.061 s for 6.0. MPEG-TS states the sound's from a
  timestamp several AAC frames before its end, so a stream copy `cut.py` into `.ts` read 1.259 s of
  sound for 1.536 s and said `verified: false`.
