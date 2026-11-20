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

## Showcase clips (AI-generated with Grok Imagine)

`grok_rain.mp4`, `grok_basketball.mp4`, `grok_greenscreen.mp4` and `grok_talk.mp4` are AI-generated
video made with Grok Imagine and supplied by the maintainer: a rainy street at night, a basketball
shot, a presenter on a green screen and a conference talk in English. The people and places do not
exist. Each is 15 s, 736×400, 24 fps, with sound. `demos/showcase.py` edits them
([docs/showcase.md](../../docs/showcase.md)); the reel it builds says the footage is AI-generated on
its first and last card. `grok_talk_short.srt` holds the talk's cues as `caption.py --transcribe`
(faster-whisper, small) wrote them for the tightened clip, so the build needs no speech engine.
They are not part of the npm package.
