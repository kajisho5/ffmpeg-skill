# ffmpeg-skill

**Give your coding agent a video editor.** Local FFmpeg, Python standard library, nothing else.

![before / after demo](assets/demo.gif)

```bash
npx ffmpeg-skill
```

`ffmpeg-skill` is an [Agent Skill](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills) for Claude Code, Cursor, Codex and any other agent that reads `SKILL.md`. It teaches the agent a fixed editing workflow (probe → edit losslessly where possible → verify) and ships eight small CLI scripts that do the actual work with `ffmpeg`/`ffprobe`. Think of it as the fully local FFmpeg counterpart to cloud video-agent tools such as browser-use/video-use.

**No API keys. No cloud. No dependencies.** If `ffmpeg` and `python3` are on your PATH, it works — offline, on any footage you'd rather not upload.

## Features

- **Probe first, verify last** — the skill forces the agent to read real duration/fps/resolution before editing and to check the result after, so you get "final.mp4: 59.98 s, 1080×1920, 30 fps" instead of guesses.
- **Lossless when possible** — cuts and joins use stream copy by default; re-encoding only happens when it must (frame-accurate cuts, filters, format changes).
- **Cut & join** segments with `mm:ss` / `hh:mm:ss.ms` times.
- **Captions** — burn SRT/ASS with font, size, colour, outline and position control; generate SRT from a plain timed-text file; animated (fade/pop/slide) and word-by-word karaoke highlight styles for short-form video.
- **Fit** to an exact duration (pitch-preserving speed change or trim) and to 16:9 / 9:16 / 1:1 / 4:5 by padding or cropping; motion-interpolated or blended slow motion.
- **Real-world footage handling** — variable-frame-rate phone clips are conformed to constant fps automatically, rotation metadata is honoured, 10-bit HEVC and 5.1 sources are handled.
- **Multicam / external-audio sync** — offset detection by cross-correlation implemented in pure Python (no numpy), 1 ms resolution, plus clock-drift correction for long takes.
- **Colour management** — real HDR10/HLG → SDR BT.709 tone mapping, 3D LUT (.cube) for Log footage and looks, and metadata-only retagging.
- **Audio post** — voice clean-up chain (highpass, de-esser, FFT denoise, compressor), background music with sidechain ducking, fades, 5.1 → stereo downmix, track replacement.
- **Loudness** — two-pass EBU R128 normalisation to −14 LUFS (or any target) with true-peak ceiling.
- **Overlays** — logos, watermarks and titles with position, time range, opacity and fades.
- **Export presets** — YouTube, Instagram Reels/Shorts/TikTok, X, ProRes 422 HQ master, H.265, GIF — all tagged BT.709.
- **Agent-friendly CLI** — every script has `--help`, prints the output path on stdout, exits non-zero with a reason on stderr, and names outputs `<input>_<operation>.<ext>` by default.

## Install

```bash
# Claude Code (default) → ~/.claude/skills/ffmpeg-skill
npx ffmpeg-skill

# Cursor → ~/.cursor/skills/ffmpeg-skill
npx ffmpeg-skill --cursor

# Codex → ~/.codex/skills/ffmpeg-skill
npx ffmpeg-skill --codex

# everything, or a project-local copy, or a custom directory
npx ffmpeg-skill --all
npx ffmpeg-skill --project
npx ffmpeg-skill --dir ./my-skills
```

Or without Node: clone this repo and copy `SKILL.md` and `scripts/` into your agent's skills directory.

You also need FFmpeg:

| OS | Command |
|----|---------|
| macOS | `brew install ffmpeg` |
| Ubuntu / Debian | `sudo apt install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` |

## Usage

Once installed, just talk to your agent. Five things you can say to Claude Code:

1. **"Take `interview.mp4`, keep 0:45–3:10 and 5:00–6:30, and make it exactly 60 seconds for Reels."**
   → `probe.py` → `cut.py --segments 0:45-3:10,5:00-6:30` → `fit.py --duration 60 --aspect 9:16 --fit crop` → `export.py --preset reels` → `probe.py` to confirm 60.0 s at 1080×1920.
2. **"Burn these captions in TikTok style, words popping in with a yellow highlight, in Japanese."**
   → `caption.py --text cues.txt --font "Noto Sans CJK JP" --animate pop --karaoke --highlight-color FFD200`.
3. **"The lav mic recording is out of sync with the camera and drifts over the hour — fix it, clean up the hiss and normalise to −14 LUFS."**
   → `sync.py camera.mp4 lav.wav --fix-drift --replace-audio` → `audio.py --voice` → `loudness.py` → report the detected offset, drift ppm and final LUFS.
4. **"Put our logo in the top-right corner for the whole video at 80% opacity, and a title card for the first 4 seconds."**
   → `overlay.py --image logo.png --position top-right --scale 220 --opacity 0.8` → `overlay.py --text "…" --start 0 --end 4 --fade 0.4`.
5. **"This iPhone HDR clip looks washed out on YouTube — fix it and give me a ProRes master too."**
   → `probe.py` (shows `hdr: true`) → `color.py --to-sdr` → `export.py --preset youtube` and `export.py --preset prores`.

The scripts also work on their own:

```bash
python3 ~/.claude/skills/ffmpeg-skill/scripts/probe.py input.mp4 --compact
python3 ~/.claude/skills/ffmpeg-skill/scripts/fit.py input.mp4 --duration 60 --aspect 9:16
```

More examples: [examples/README.md](examples/README.md). To see everything run end-to-end on generated footage: `bash examples/make_demo.sh`.

## Scripts

| Script | What it does |
|--------|--------------|
| `probe.py` | Duration, fps (+ VFR detection), resolution, codecs, bit depth, HDR format, colour space, rotation, audio channels as JSON |
| `cut.py` | In/out or multi-segment cuts, lossless `-c copy` first, re-encode fallback, `--accurate` for frame-exact |
| `caption.py` | Burn SRT/ASS (font, size, colour, outline, position); build SRT from timed plain text; animated + karaoke ASS |
| `fit.py` | Fit to a duration (speed or trim, smooth slow-mo) and/or aspect ratio (pad or crop), force constant fps |
| `sync.py` | Detect offset between two recordings by audio cross-correlation (1 ms), correct clock drift; output aligned video/audio |
| `color.py` | HDR10/HLG → SDR BT.709 tone mapping, 3D LUT application, colour-tag rewriting |
| `audio.py` | Denoise / voice chain, music bed with auto-ducking, fades, downmix, replace track |
| `loudness.py` | Two-pass EBU R128 `loudnorm` to −14 LUFS / −1 dBTP (or custom), video stream-copied |
| `overlay.py` | Composite image/logo or drawtext title with position, time range, opacity, fade |
| `export.py` | Presets: `youtube`, `youtube4k`, `reels`, `x`, `prores`, `h265`, `gif` |

All scripts: Python 3.9+, standard library only, `--help`, non-zero exit + stderr message on failure.

## Requirements

- FFmpeg 5.0+ with `libx264`, `libx265`, `libass`, `prores_ks` and `libzimg` (for `color.py --to-sdr`); the default builds from Homebrew, apt and gyan.dev include all of them
- Python 3.9+
- Node 16+ only for the `npx` installer

## Development

```bash
bash examples/make_demo.sh      # generates footage, runs every script, rebuilds assets/demo.gif
python3 tests/test_all.py       # end-to-end tests incl. VFR, rotated, 5.1, 10-bit HDR10 and drifting sources (needs ffmpeg)
node bin/install.js --dir /tmp/skills   # try the installer without touching ~/.claude
```

## License

[MIT](LICENSE)
