# Security Policy

## Reporting a vulnerability

Please report security issues privately using GitHub's [Report a vulnerability](https://github.com/kajisho5/ffmpeg-skill/security/advisories/new)
flow (Security tab → Advisories → "Report a vulnerability") rather than a public issue or PR.
That opens a private advisory only maintainers can see until a fix is ready.

Include, where you can:
- The affected file/tool (e.g. `scripts/batch.py`) and version
- A minimal reproduction (input that triggers it, and what happens)
- The impact you'd expect (e.g. arbitrary file write, path traversal, injection into an ffmpeg
  filter graph)

This project has had real findings fixed this way before -- e.g. `batch.py` recipe steps that
could resolve outside `scripts/` via an absolute path or `../` traversal (fixed in #124). That
kind of report is exactly what this process is for.

## Supported versions

Only the latest published version (see [CHANGELOG.md](CHANGELOG.md) / the latest npm release) is
supported. There's no LTS branch -- please upgrade before reporting if you're on an older one.

## What you install and what it touches

- **What is installed.** `npx ffmpeg-skill` copies the skill into your agent's skills directory:
  `SKILL.md`, the references, the templates, executable Python scripts (`scripts/`, standard
  library only) and `mcp/server.py`, an MCP server that talks over stdio. `npx ffmpeg-skill setup`
  also runs `brew`, `winget` or `apt-get` to install FFmpeg when `ffmpeg` does not run
  (`--no-ffmpeg` skips that).
- **What a tool reads and writes.** The input files you name and the outputs you name; the side
  files it is asked for or says it writes (a `--plan`, `caption.py`'s `.srt`/`.ass` beside its
  output, `verify.py --out`); temporary files in the system temp directory, and a hidden
  `.<name>.ffskill-<pid>` file beside an output it replaces. It starts `ffmpeg` and `ffprobe`,
  and a few local helpers (fontconfig's `fc-match`/`fc-scan` for fonts, a speech-to-text engine for
  `--transcribe`), never through a shell.
- **What it refuses.** An input or output that FFmpeg would open as a URL (`http:`, `tcp:`,
  `file:`, `subfile,`, ...); a playlist (HLS, DASH, IMF, ffconcat, by name or by content); a pipe
  or a device as input; an output that is one of the inputs; an existing output without
  `--overwrite`. Every input of every `ffmpeg` and `ffprobe` command carries
  `-protocol_whitelist file`, so a file a demuxer finds named inside another file is opened as a
  local file or not at all.
- **Network.** The scripts and the MCP server open no network connection themselves: no module
  in `scripts/` or `mcp/` imports `socket`, `urllib`, `http.client` or an HTTP library, and FFmpeg
  is kept to local files as above. What does use the network is not the skill's code: three of the
  speech engines `--transcribe` can run (parakeet-mlx, faster-whisper, openai-whisper) download
  their model weights the first time they run (faster-whisper runs inside the tool's own process),
  and `npx` and `setup` download the package and FFmpeg.
- **Running it scoped.**
  - `FFMPEG_SKILL_ROOTS`: directories separated by `:` (`;` on Windows), each absolute. When it
    is set, every input and output must resolve, symlinks followed, under one of them; anything
    else is refused before FFmpeg runs, dry runs included (`kind: input`,
    `error.reason: path_outside_roots`). The system temp directory stays allowed (the tools keep
    their intermediates there), and so does reading the skill's own `templates/`. A font named for a
    caption or a title (`--font-file`, `--fonts-dir`) is not checked. Recommended in the `env` of
    an MCP client's server entry (README, [MCP](README.md#mcp)).
  - `FFMPEG_SKILL_READ_ONLY=1` refuses `--plan`, the one file `probe`, `check` and `cropdetect`
    can write, so those three write nothing; the MCP server sets it for them. It does not stop the
    other tools writing their outputs.
  - A container gives the strongest bound: mount only the folder with the media, and run without
    a network (`docker run --network none -v "$PWD:/work" ...`), with any speech model installed
    beforehand.
