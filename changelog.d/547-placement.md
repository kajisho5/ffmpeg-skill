### Added

- **`caption.py`, `overlay.py` and `graphics.py` report where what they drew landed: `placement`** (#547).
`{measured, x, y, width, height, frame_width, frame_height, touches_edge, samples}`, measured by rendering the run's own
filter graph over a black and a white frame of the written size; a caption is the union of its cues (sampled at each
cue's middle), a graphics template the union of four instants of its span. `touches_edge` names the frame edges the
box reaches, so a caption that runs off the frame says so. A measured box removes `rendered_placement` from
`unverified` (`legibility` stays); `render.py` keeps it.
