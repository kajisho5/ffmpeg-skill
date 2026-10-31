# Shared flags, codecs and dry-run

The long form of SKILL.md's Quick start. `--help` on a script is still its full flag list;
`references/scripts.md` covers most flags per tool.

## Running the scripts

Scripts live in `scripts/` next to this file; run them with `python3 <skill-dir>/scripts/<name>.py`, and delivery templates in `templates/`. This file is enough to do a job: the table below routes the request, and `--help` on the script about to run is the cheapest full flag list. A reference file costs as much as this one; open one only for a question you have: `references/scripts.md` (most flags; `--help` lists all), `references/devices.md` (iPhone HDR, GoPro, DJI, screen recordings, Zoom), `references/gotchas.md` (the long form of the one-line rules at the end). MCP: `tools/list` shows only the core 12 by default; the other 30 (per this table) stay callable by name via `tools/call`, described by `contract --json`; set `FFMPEG_SKILL_MCP_FULL=1` for all 42.

## Shared flags

Shared flags (every script): `--dry-run`; `--json` (output path, its probe, the commands run); `--json-brief` (status/output/verified + a `summary`); `--fast` (preview quality); `--progress` (%/ETA); `--timeout SECONDS` (`kind: timeout`, default 1800; `0` for hour-long encodes); `--overwrite` (step 7); `--plan FILE` (a dry run `render.py FILE` runs later; refuses a changed input). Re-encoding tools also take `--hw` (Apple Silicon GPU, big files; `FFMPEG_SKILL_HW=1` = default, not export), `--codec h264|hevc|av1|prores` and `--quality N`: unset, SDR is x264 (`cut.py`: HEVC source stays HEVC, `--no-keep-hevc` x264), HDR is x265 Main10; `prores` needs `-o NAME.mov`, `h264` refuses HDR (`color.py --to-sdr` first).

## What `--dry-run` runs

Writing tools run nothing under `--dry-run`; the measuring tools (`probe`, `check`, `sync`, `multicam`, `scenes`, `cropdetect`, `report`, `silence`, `loudness`, `stabilize`; `overlay` for a multi-line `--text` on FFmpeg 8.0-8.1.0) may still run ffmpeg/ffprobe, skipping artifacts/side files (`--edl`, `--sheet`, a generated `.ass`); `verify` ignores the flag. Per tool: `contract --json` `dry_run`.
