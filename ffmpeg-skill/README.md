# ffmpeg-skill (plugin tree)

Local FFmpeg video and audio editing for coding agents. This directory is the installable plugin:
the skill (`SKILL.md`, also at `skills/ffmpeg-skill/SKILL.md`), its tools (`scripts/`), their
references and templates, the machine-readable contract (`docs/contract.md`,
`python3 scripts/_contract.py --json`) and the MCP server (`mcp/server.py`).

It is built from the npm package by every release and published to the `plugin` branch. The full
README, the changelog and the tests are in the repository: https://github.com/kajisho5/ffmpeg-skill

Needs FFmpeg 6.1 or later and Python 3.10 or later. The tools themselves open no network
connection and read no API key. The one exception is transcription (`caption.py --transcribe`,
`silence.py --filler --transcribe`), which runs a speech engine you installed yourself
(whisper.cpp, faster-whisper, openai-whisper or parakeet): on its first run such an engine may
download its model, and a Hugging Face client uses a token you are logged in with.
