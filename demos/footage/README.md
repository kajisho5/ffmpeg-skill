# Demo footage

`ai_talk.mp4` is AI-generated video (a person at a laptop who does not exist), 6 s, 640×430,
supplied by the maintainer for the demos. The `reframe_talk` demo uses it. It is not part of the
npm package.

`ai_talk_en.mp4` is AI-generated too (a man outdoors who does not exist), 15 s, 854×480, English
speech with two hesitations. `ai_talk_en.words.json` holds its word timings as faster-whisper
(base, primed with the filler list the way `silence.py --filler --transcribe` primes it) wrote
them, so the `filler_en` and `pauses_en` demos, which both read this clip, build without a
speech engine.

These two clips are the only footage in `demos/build.py` that is not synthetic: three demos
(`reframe_talk`, `filler_en`, `pauses_en`) use them, and every other demo is generated from
FFmpeg's own test sources.

## Showcase clips (AI-generated with Google Veo)

`veo_rain.mp4`, `veo_basketball.mp4`, `veo_greenscreen.mp4`, `veo_talk_en.mp4`, `veo_talk_ja.mp4`,
`veo_pause_en.mp4`, `veo_sea.mp4`, `veo_hands.mp4` and `veo_hall.mp4` are AI-generated video made
with Google Veo and supplied by the maintainer. The people and places in them do not exist. Each is
7.85 s, 1920×1080, 24 fps, HEVC, with sound; they are re-encoded copies (`export.py --preset h265`)
of the generated files, to keep the repository small. `demos/showcase.py` edits them
([docs/showcase.md](../../docs/showcase.md)); the reel it builds says the footage is AI-generated on
its first and last card. `veo_talk_en.srt` and `veo_talk_ja.srt` hold the talks' cues as
`caption.py --transcribe` wrote them, corrected against what is said. `slide_en_*.png` and
`slide_ja_*.png` are the slides of the conference demo, made for it.

`real_city.mp4`, `real_sea.mp4` and `real_fireworks.mp4` are not generated: the maintainer shot
them on a phone (a city at night, handheld; a coast at night; fireworks at 60 fps, scaled from 4K to
1080p). They are re-encoded copies without the camera's metadata.

