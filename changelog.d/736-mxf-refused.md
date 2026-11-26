### Fixed

- An `.mxf` output of a re-encode (`cut.py --accurate`/`--smart`, fit, color, audio, export and the rest) is refused
  before ffmpeg runs, as `.webm` is, with `kind: input`, `reason: output_container_codecs` and a hint to `.mov` or `.mkv`. It
  failed after the encode started with "Codec 'aac' is not supported by the bitstream filter 'pcm_rechunk'" (#736).
