# Privacy

ffmpeg-skill is a set of command-line tools that run on your own machine. This page says what
they do with data, as of the version it ships with.

- **No collection.** The tools send no telemetry, analytics or usage data, and the project runs
  no server that could receive any. There is no account and nothing to sign in to.
- **Your media stays local.** Video, audio, subtitles and project files are read from and written
  to the paths you give. Nothing is uploaded.
- **No network use by the tools themselves**, and no API key is read. One exception:
  transcription (`caption.py --transcribe`, `silence.py --filler --transcribe`) runs a speech
  engine you installed yourself (whisper.cpp, faster-whisper, openai-whisper or parakeet). On its
  first run such an engine may download its model from its own provider, and a Hugging Face
  client uses a token you are logged in with. What those engines and providers do is covered by
  their own policies.
- **Installing** from npm, GitHub or a plugin directory is a download from that service, under
  that service's policy.
- **Environment variables** the tools read are configuration only: the `FFMPEG_SKILL_*` switches,
  `PARAKEET_MODEL` and `PARAKEET_CPP_MODEL` for a speech model, and `PATH`, `PATHEXT` and `WINDIR`
  to find programs and fonts.

Questions: open an issue at https://github.com/kajisho5/ffmpeg-skill/issues.
