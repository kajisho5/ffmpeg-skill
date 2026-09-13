# Trigger tests: should / should-not

`prompts.json` holds 16 requests the skill must trigger on (English, Japanese, Chinese, Korean, Spanish and Arabic, some without a file extension or the word "edit") and 13 near-miss requests it must not (still images, installing ffmpeg — in English, Japanese and French, downloading from YouTube, writing a script in Japanese and Portuguese, an editor shortcut, thumbnail design, CSV to JSON, a codec explainer, AI video generation in English and German, meeting transcription).

Method: show an independent model a skill catalog made of this skill's `description` plus four decoy skills that own the neighbouring territory (image-tools, web-research, copywriter, meeting-notes), give it the raw request, and ask which one skill it would load or `none`. A run is correct when ffmpeg-skill is chosen exactly for the should-trigger prompts.

The non-English prompts are there because the skill description is English: a request in Chinese, Korean, Spanish, Portuguese, French, German or Arabic must route the same way an English one does, and a near-miss in those languages must still miss.

Results: `results-<date>.json`. 2026-09-04: 22/22 on the then 22-prompt set (incl. two audio-only requests: WAV→MP3 conversion, silence removal on an M4A). The set is now 29 prompts (22 + 7 multilingual: t13 zh, t14 ko, t15 es, t16 ar should-trigger; n11 pt, n12 fr, n13 de should-not).
