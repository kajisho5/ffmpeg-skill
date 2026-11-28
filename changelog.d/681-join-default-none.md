### Changed

- **`join.py` joins end to end by default (#681).** The default transition was a 0.5 s `fade`, so
  "join these" wrote a file 0.5 s shorter per boundary than the clips together, with the two clips
  blended across each cut. The default is now `--transition none`: the join is the clips' summed
  length, and `expected_duration` says so. This changes what an existing call without
  `--transition` writes. **To keep the old output, pass `--transition fade`** (with `--duration`
  for another length; 0.5 s is still its default). `--duration` with no transition is now refused
  (`kind: input`, the hint names `--transition fade`): with no `--transition` it was the length of
  the default crossfade, and with `--transition none` it was ignored. `render.py` projects are unchanged: a project's
  `transition` is still a 0.5 s fade unless it says otherwise, and render.py passes it to join.py
  by name.
