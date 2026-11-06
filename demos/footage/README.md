# Demo footage

`ai_talk.mp4` is AI-generated video (a person at a laptop who does not exist), 6 s, 640×430,
supplied by the maintainer for the demos. It is the only non-synthetic source in `demos/build.py`
(the `reframe_talk` demo) and is not part of the npm package.

`ai_talk_en.mp4` is AI-generated too (a man outdoors who does not exist), 15 s, 854×480, English
speech with two hesitations. `ai_talk_en.words.json` holds its word timings as faster-whisper
(base, primed with the filler list the way `silence.py --filler --transcribe` primes it) wrote
them, so the `filler_en` demo builds without a speech engine.
