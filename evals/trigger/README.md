# Trigger tests: should / should-not

`prompts.json` holds 12 requests the skill must trigger on (English and Japanese, some without a file extension or the word "edit") and 10 near-miss requests it must not (still images, installing ffmpeg, downloading from YouTube, writing a script, an editor shortcut, thumbnail design, CSV to JSON, a codec explainer, AI video generation, meeting transcription).

Method: show an independent model a skill catalog made of this skill's `description` plus four decoy skills that own the neighbouring territory (image-tools, web-research, copywriter, meeting-notes), give it the raw request, and ask which one skill it would load or `none`. A run is correct when ffmpeg-skill is chosen exactly for the should-trigger prompts.

Results: `results-<date>.json`. 2026-09-04: 22/22 (incl. two audio-only requests: WAV→MP3 conversion, silence removal on an M4A).
