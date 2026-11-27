### Fixed

- `caption.py` ends a cue with the picture: the default `--min-duration` no longer lengthens a short last cue past the input's picture, and a cue whose own end is past it is held there too, so `--mode mux` no longer writes a container longer than its picture (a 3.13 s picture was muxed into 3.8 s) and a burn's adjusted SRT names no time past the last frame. Each held cue is named in a note (#776).
