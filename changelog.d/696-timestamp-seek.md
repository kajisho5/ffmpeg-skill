### Fixed

- A frame grab or a seek into an MPEG-TS (`.ts`, `.m2ts`, `.mts`) or MPEG-PS (`.mpg`) file starts
  far enough before its time to decode from a keyframe: `look.py --at`, `--compare` and the contact
  sheet no longer fail with "not written" or show the next keyframe's picture, `cut.py --accurate`
  no longer loses the picture or starts on another frame, and the review page's stills and
  `cropdetect.py`'s readings are no longer missing (#696).
- `overlay.py --image --codec prores` on an 8-bit source leaves the main picture as it was: the
  still is made YUV in the source's matrix instead of the whole picture going through RGB (#696).
