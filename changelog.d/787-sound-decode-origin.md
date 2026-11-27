### Fixed

- A sound-only decode of an MPEG-TS or MPEG-PS counts from the file's start, as the picture does since #766: `decode_pcm_mono` (so `sync.py`, `scenes.py`, `multicam.py`), silencedetect times (`silence.py`'s cut levels, `metadata.py --auto-chapters`), `waveform.py`'s stills, `caption.py`'s karaoke energy split and the WAV an ASR engine transcribes all read the file's clock now (#787).
- `sync.py --replace-audio` counts the second file's sound from the file's start too, and `-copyts` no longer drags the reference's own start into the written picture: a `.ts` reference at 1.467 s kept its picture there beside a sound at 0, and a trimmed head was padded back (#787).
