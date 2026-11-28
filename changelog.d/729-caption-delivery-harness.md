### Added

- `tests/caption_delivery.py`: caption delivery checked on a phone capture you supply (an argument or `$FFMPEG_SKILL_PHONE_CAPTURE`, only read) and on a 30000/1001 CFR control it generates: accurate cut, caption mux and copy export, each cue's delivered start within one frame of the request, the sample rate at every step, the CFR grid and the delivery's lengths, as a JSON and a Markdown report. The control's report is in `docs/caption-delivery/`; no phone footage is committed or downloaded (#729).
