### Added

- Every input of every `ffmpeg` and `ffprobe` command a tool runs carries `-protocol_whitelist file`, a second guard behind the URL and playlist refusals: a file a demuxer finds named inside another file is opened as a local file or not at all (#572).
- `FFMPEG_SKILL_ROOTS`: optional directories (`os.pathsep`-separated, absolute) that every input and output must resolve under, symlinks followed, else `kind: input`, `error.reason: path_outside_roots`, dry runs included; the system temp directory stays allowed. Unset, nothing changes. README's MCP example sets it (#572).
- SECURITY.md says what the package installs, what a tool reads, writes and refuses, what uses the network (only third-party speech engines fetching their models, and `npx`/`setup`), and how to run it scoped (#572).
