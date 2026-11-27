### Fixed

- A sound-only decode of an MPEG-TS or MPEG-PS counts from the file's start, as the picture does since #766: `decode_pcm_mono` (so `sync.py`, `scenes.py`, `multicam.py`), silencedetect times (`silence.py`'s cut levels, `metadata.py --auto-chapters`), `waveform.py`'s stills, `caption.py`'s karaoke energy split and the WAV an ASR engine transcribes all read the file's clock now (#787).
