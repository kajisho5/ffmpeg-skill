# Security Policy

## Reporting a vulnerability

Please report security issues privately using GitHub's [Report a vulnerability](../../security/advisories/new)
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
