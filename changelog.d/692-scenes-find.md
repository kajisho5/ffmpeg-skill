### Added

- `scenes.py --find "TEXT" --words words.json [--nth N]` says when a word or phrase is said, from the words file `cut.py --words` reads: `find.matches` holds each time's `text`, `start`, `end` (the words' own times), `confidence` and `words` (the indices `cut.py --word-segments` takes). Case, punctuation and full/half width are set aside; not said is `completed` with no match and a note; a word without timing refuses the file (#692).
