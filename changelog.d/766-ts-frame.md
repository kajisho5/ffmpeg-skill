### Fixed

- `look.py --at T` shows the frame `cut.py --start T` starts on, on an MPEG-TS or MPEG-PS file whose
  sound starts before its picture: a time read on the picture alone counted from the picture's
  first frame, not the file's start. The same held for `look.py --compare` and the contact sheet,
  the review page's stills, the times `scenes.py` gives its cuts (and `metadata.py --auto-chapters
  --from scenes`), and the windows of `cropdetect.py`, fit's crop check and `scenes.py --shots`.
  `check.py --levels` gives its worst frame's time from the file's start on every container; a
  picture that starts late was counted from its own first frame (#766).
