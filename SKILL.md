---
name: ffmpeg-skill
description: Professional video editing with local FFmpeg — cut, caption, fit to duration/aspect, sync multicam audio, normalise loudness, overlay logos and export platform presets, all from Python stdlib scripts with no cloud or API keys.
---

# ffmpeg-skill

You are editing video for the user with FFmpeg through the scripts in `scripts/`.
Everything runs locally. Nothing is uploaded, no keys are needed, and the only
requirements are `ffmpeg`/`ffprobe` on PATH and Python 3.9+.

Run scripts with `python3 <skill-dir>/scripts/<name>.py ...`. Every script has
`--help`, exits non-zero on failure with the reason on stderr, prints the output
path on stdout, and defaults the output name to `<input>_<operation>.<ext>`.

## Workflow (always follow this order)

1. **Probe first.** Run `probe.py` on every input before touching it. Read the
   duration, fps, resolution, codecs, audio channels and the
   `variable_frame_rate_suspected` flag. Plan the edit from real numbers, never
   from assumptions about the file.
2. **Prefer lossless.** If the request can be satisfied without re-encoding
   (plain cuts on keyframes, remuxing, audio-only changes), do not re-encode.
   `cut.py` and `loudness.py` stream-copy video by default; only pass
   `--accurate` to `cut.py` when the user needs frame-exact cuts.
3. **Chain operations in a sensible order.** Cut → fit → caption/overlay →
   sync/loudness → export. Do the destructive/aspect changes before burning
   text so captions are sized for the final frame. Re-encode as few times as
   possible: if several re-encoding steps are needed, keep intermediates at
   CRF 18 (the default) and only use `export.py` for the last step.
4. **Verify the output.** Run `probe.py` on each result and confirm duration,
   resolution, fps and audio match what was requested. Report those numbers to
   the user (e.g. "final.mp4: 59.98 s, 1080x1920, 30 fps, AAC stereo").
5. **Keep the user's originals.** Never overwrite the source file. Write new
   files next to the input or where the user asked.

## Request → script

| User says | Do |
|-----------|----|
| "what's in this file", "how long is it", "is it 4K" | `probe.py input.mp4` |
| "cut from 1:20 to 2:05", "trim the first 10 seconds" | `cut.py input.mp4 --start 1:20 --end 2:05` |
| "keep only these parts", "remove the middle" | `cut.py input.mp4 --segments 0-1:00,1:30-2:00` |
| "make it exactly 60 seconds", "fit it in 30s" | `fit.py input.mp4 --duration 60` (speed) or `--method trim` |
| "make it vertical / for TikTok / 9:16", "square for Instagram" | `fit.py input.mp4 --aspect 9:16 --fit pad` (or `--fit crop`) |
| "add subtitles from this SRT", "burn in captions" | `caption.py input.mp4 --srt subs.srt` |
| "caption it with these lines" (plain text with times) | `caption.py input.mp4 --text cues.txt` |
| "put our logo top-right", "add a watermark" | `overlay.py input.mp4 --image logo.png --position top-right --scale 200` |
| "add a title for the first 4 seconds" | `overlay.py input.mp4 --text "Title" --position top --start 0 --end 4 --fade 0.4` |
| "sync the lav mic to the camera", "line up the two cameras" | `sync.py camera.mp4 mic.wav --replace-audio` / `sync.py camA.mp4 camB.mp4 --trim-second` |
| "fix the audio levels", "normalise to -14 LUFS" | `loudness.py input.mp4` (`-I -16 --tp -1.5` for podcasts, `-I -23` for broadcast) |
| "export for YouTube / Reels / X", "give me a ProRes master", "make it HEVC" | `export.py input.mp4 --preset youtube|reels|x|prores|h265` |
| "make a GIF preview" | `export.py input.mp4 --preset gif` |

## Scripts

### probe.py — inspect
```
probe.py INPUT... [--compact] [--field duration|video.fps|...]
```
JSON with `duration`, `video{codec,width,height,fps,pix_fmt,color_space,rotation,variable_frame_rate_suspected}`,
`audio{codec,channels,sample_rate}`. `--compact` gives one line per file.

### cut.py — cut / join segments
```
cut.py INPUT [--start T] [--end T | --duration T] [--segments A-B,C-D,...] [--accurate] [-o OUT]
```
Times accept `12.5`, `1:30`, `00:01:30.250`. Default is `-c copy` (snaps to
keyframes, instant, lossless); if the snapped result deviates more than
`--tolerance` (0.5 s) from the request, that segment is re-encoded automatically
(x264 CRF 18). `--accurate` always re-encodes; `--tolerance -1` never does.
Multiple segments are concatenated in the order given. stderr reports whether
the result was "lossless stream copy" or "re-encoded".

### fit.py — target duration and/or aspect
```
fit.py INPUT [--duration T --method speed|trim [--from-center] [--max-speed 4]]
             [--aspect 16:9|9:16|1:1|4:5|W:H --fit pad|crop [--width W] [--pad-color black]]
             [--fps N] [-o OUT]
```
`speed` retimes video and audio together (pitch-preserving `atempo`); it
refuses factors beyond `--max-speed`. `trim` keeps the head (or the middle with
`--from-center`). `--fps` forces constant frame rate — use it on VFR sources.

### caption.py — subtitles
```
caption.py INPUT --srt FILE | --ass FILE | --text CUES.txt [--write-srt OUT.srt]
           [--font NAME] [--fonts-dir DIR] [--size N] [--color RRGGBB] [--outline N] [--outline-color RRGGBB]
           [--bold] [--box] [--position bottom|top|center|top-left|...] [--margin N] [-o OUT]
caption.py --text CUES.txt --write-srt OUT.srt        # generate the SRT only
```
Text cue format, one per line: `0:00-0:03 Hello`, `00:00:03.500 --> 00:00:06 Two | lines`.
Lines without a time run for `--auto-seconds` (3 s) after the previous cue. `|` is a line break.

### overlay.py — logo, image, title
```
overlay.py INPUT --image PNG [--scale W | --scale-percent P] | --text "..." [--font-file F.ttf] [--font-size N] [--box]
           [--position top-right|bottom-left|center|X,Y] [--margin N] [--start T] [--end T] [--fade S] [--opacity 0-1] [-o OUT]
```
Alpha in PNGs is respected. Fades apply to the overlay only; the video keeps playing.

### sync.py — offset detection and alignment
```
sync.py REFERENCE SECOND [--json] [--max-offset 30] [--analyze-seconds 120]
        [--replace-audio | --trim-second] [-o OUT]
```
Cross-correlates loudness envelopes (pure Python FFT, ~5 ms resolution).
Positive offset = the second recording started later. `--replace-audio` writes
the reference video with the second file's audio aligned (video stream copied).
`--trim-second` writes the second file shifted to the reference timeline.
Check `confidence` (0–1); below ~0.3 the match is doubtful — try a longer
`--analyze-seconds` or a window that contains a clear event (clap).

### loudness.py — EBU R128 normalisation
```
loudness.py INPUT [-I -14] [--tp -1] [--lra 11] [--measure-only] [-o OUT]
```
Two-pass `loudnorm`: measure, then apply with measured values (linear mode when
the true-peak ceiling allows). Video is stream-copied; audio becomes AAC in
video containers or the codec matching the extension (.wav → PCM, .flac, .mp3).

### export.py — delivery presets
```
export.py INPUT --preset youtube|youtube4k|reels|x|prores|h265|gif [--fit pad|crop] [--no-scale] [--allow-long] [--crf N] [-o OUT]
export.py --list
```
Scales into the preset frame (pad by default), tags BT.709, sets `+faststart`,
trims to platform maximums (Reels 90 s, X 140 s) unless `--allow-long`.

## Gotchas

- **Variable frame rate (phone/screen recordings).** `probe.py` sets
  `variable_frame_rate_suspected` when `r_frame_rate` and `avg_frame_rate`
  disagree. VFR causes audio drift and bad concat joins. Fix it early with
  `fit.py --fps 30` (or 60) before cutting with `--accurate`, captioning or
  syncing; add `--accurate` to `cut.py` because copy-cuts on VFR are unreliable.
- **Audio drift / sync.** Don't mix files with different frame rates or sample
  rates in one `cut.py --segments` join without re-encoding (`--accurate`).
  After `sync.py`, verify by running it again on the output: the offset should
  be ~0. If dialogue drifts over a long recording, the clocks differ; align the
  start with `sync.py`, then fix drift with `fit.py --duration` on the audio-only
  track to match the reference length.
- **Colour.** All H.264/H.265 outputs are tagged BT.709 (`-colorspace`,
  `-color_primaries`, `-color_trc`) and `yuv420p`. If `probe.py` shows a
  BT.2020/HDR source (`color_transfer` smpte2084 or arib-std-b67), tell the
  user the output will be tagged as SDR BT.709 without tone mapping, and add
  `-vf zscale=t=linear:npl=100,tonemap=hable,zscale=p=bt709:t=bt709:m=bt709`
  manually with ffmpeg if they need a proper SDR conversion.
- **CJK and other non-Latin text.** libass and drawtext need a font that has
  the glyphs. Check with `fc-list | grep -i cjk`. Then either name it
  (`caption.py --font "Noto Sans CJK JP"`) or point at the file
  (`overlay.py --font-file /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`,
  `caption.py --fonts-dir ./fonts --font "Noto Sans CJK JP"`). Without a
  matching font you get boxes, not an error. Install: `apt install fonts-noto-cjk`,
  `brew install --cask font-noto-sans-cjk`.
- **Keyframe cuts.** A lossless `cut.py` result may start up to one GOP (often
  1–10 s) earlier than requested; the script re-encodes automatically when the
  deviation exceeds 0.5 s. If the user insists on lossless output, pass
  `--tolerance -1` and tell them the cut lands on the nearest earlier keyframe.
- **Rotation metadata.** Phone footage often has a `rotation` tag; `probe.py`
  reports it and `fit.py` accounts for it when computing the output frame.
- **Odd dimensions.** `yuv420p` needs even width/height; `fit.py` and
  `export.py` round to even values automatically.
- **Speed.** Re-encodes use x264 `medium`. For long files add `--preset veryfast`
  to intermediates and keep the default for the final export.
