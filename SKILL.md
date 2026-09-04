---
name: ffmpeg-skill
description: Professional video editing with local FFmpeg — MCP server, batch folders, declarative project rendering, brand kits, motion-graphics templates (lower-thirds, titles, countdowns), HTML delivery reports, scene detection and highlight picks, delivery compliance checks, cut, silence removal, transitions, multicam, captions (animated/karaoke timed to speech), fit to duration/aspect, audio sync with drift correction, HDR/HLG/Dolby Vision to SDR, LUTs, audio clean-up and ducking, loudness, overlays, platform exports, frame inspection and a real-footage verification kit; Python stdlib scripts, no cloud or API keys.
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
3. **Plan with `--dry-run --json`, then execute.** Every script accepts
   `--dry-run` (prints the ffmpeg commands, runs nothing) and `--json`
   (structured result: output path, probe of the output, commands run). Use
   them to confirm a plan before long encodes and to report exact facts.
   `--fast` gives a quick preview-quality render (x264 veryfast), `--progress`
   prints percent and ETA on stderr for long encodes.
4. **Chain operations in a sensible order.** Colour (HDR→SDR / LUT) → cut →
   join → silence → fit → caption/overlay → sync → audio → loudness → export.
   Do frame changes (fit/crop) before captions and overlays so text is sized
   for the final frame. Re-encode as few times as possible: keep intermediates
   at CRF 18 (the default) and only use `export.py` for the last step; for
   anything with more than two steps use `render.py` with a project.json.
5. **Check the deliverable.** Before reporting, run `check.py OUTPUT --platform X`
   for the destination the user named; fix FAILs, mention WARNs.
6. **Verify the output.** Run `probe.py` on each result and confirm duration,
   resolution, fps and audio match what was requested. Report those numbers to
   the user (e.g. "final.mp4: 59.98 s, 1080x1920, 30 fps, AAC stereo").
7. **Keep the user's originals.** Never overwrite the source file. Write new
   files next to the input or where the user asked.
8. **Look at the picture.** After captioning, overlaying, cropping or colour
   work run `look.py OUTPUT` (contact sheet) or `look.py OUTPUT --at T` and
   view the PNG: text inside the frame and not over faces, logos where asked,
   crops keeping the subject, colours not washed out. Fix and re-run before
   reporting. Numbers from probe are not enough.

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
| "cut out the pauses / dead air", "tighten it up", "jump cuts" | `silence.py input.mp4 [--threshold -40 --min-silence 0.8]` |
| "stitch these clips together", "add a crossfade between them" | `join.py a.mp4 b.mp4 c.mp4 --transition fade --duration 0.5` |
| "show me what it looks like", "check the captions are readable" | `look.py output.mp4` then view the PNG |
| "what would you run?", "don't render yet" | any script with `--dry-run` |
| "make a 60 s highlight from this hour", "find the good bits" | `scenes.py long.mp4 --highlights 6 --target 60 --edl picks.txt` → `cut.py --segments` |
| "is this OK to upload?", "check it meets the Reels spec" | `check.py final.mp4 --platform reels` |
| "set it up so I can tweak and re-render", "several changes to the same edit" | `render.py --init project.json`, edit, `render.py project.json` |
| "add a lower third with my name", "title card", "countdown intro", "progress bar" | `graphics.py input.mp4 --template lower-third --name "..." --title "..." --start 2 --end 8` |
| "use our brand fonts/colours/logo" | pass `--brand brand.json` to caption/overlay/graphics, or `"brand"` in project.json |
| "send me a summary of what you did" | `report.py --before raw.mov --after final.mp4 --platform youtube -o report.html` |
| "do this to every file in the folder", "process the whole shoot" | `batch.py FOLDER --recipe batch.json` (steps or a render project; cached) |
| "transcribe it and caption it" | `caption.py input.mp4 --transcribe --animate pop --karaoke` (needs a local whisper; otherwise `--text`) |
| "three cameras, cut between them" | `multicam.py camA.mp4 camB.mp4 camC.mp4 --switch "0-20:0,20-40:1,40-60:2"` |
| "it's an iPhone Dolby Vision clip and players show it wrong" | `color.py clip.mov --to-sdr` or `color.py clip.mov --strip-dovi` (keep HDR, drop the DV layer) |
| "does it look like Log / S-Log / flat footage?" | `probe.py clip.mp4 --analyze` (`looks_like_log`) then `color.py --lut` |
| "test the tool on my real files" | `verify.py ~/Footage --report verify.md` |
| "show me progress", "quick preview first" | any encoding script with `--progress` and/or `--fast` |
| "the colours look washed out / it's an iPhone HDR video" | `color.py input.mov --to-sdr` (probe shows `hdr: true`) |
| "apply this LUT", "convert the S-Log / V-Log footage" | `color.py input.mp4 --lut grade.cube [--lut-strength 0.7]` |
| "the colours are tagged wrong" | `color.py input.mp4 --retag bt709` (no re-encode) |
| "clean up the audio", "remove the hiss / room noise" | `audio.py input.mp4 --voice` (speech) or `--denoise` |
| "add background music under the talking" | `audio.py input.mp4 --music bed.mp3 --duck --fade-out 3` |
| "convert the 5.1 to stereo" | `audio.py input.mov --downmix` |
| "swap in the narration track" | `audio.py input.mp4 --replace narration.wav` |
| "the audio drifts out of sync over the hour" | `sync.py camera.mp4 recorder.wav --fix-drift --replace-audio` |
| "smooth slow motion", "half speed but fluid" | `fit.py input.mp4 --duration 2x --smooth interpolate` (slow) or `--smooth blend` |
| "TikTok-style captions with the words popping / highlighted" | `caption.py input.mp4 --text cues.txt --animate pop --karaoke` |
| "it's a phone video with variable frame rate" | nothing extra: every re-encoding script conforms VFR to constant fps automatically; `fit.py --fps 30` to pick the rate |

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
refuses factors beyond `--max-speed`. For slow motion add `--smooth blend`
(frame blending, fast) or `--smooth interpolate` (motion-compensated
`minterpolate`, fluid but roughly 10-20x slower than realtime). `trim` keeps
the head (or the middle with `--from-center`). `--fps` forces a constant frame
rate; VFR sources are conformed automatically even without it.

### silence.py — remove dead air / jump cuts
```
silence.py INPUT [--threshold -35] [--min-silence 0.6] [--margin 0.15] [--min-keep 0.2] [--list] [--edl keep.txt] [-o OUT]
```
Runs `silencedetect`, keeps `--margin` seconds of air around speech, drops
gaps shorter than `--min-silence`, and re-encodes once with `select`/`aselect`
(frame accurate). `--list` prints silences, kept ranges and seconds removed
without rendering; `--edl` saves the kept ranges in `cut.py --segments` format
so the user can edit the list by hand. Quiet rooms need `--threshold -40`
to `-45`; noisy ones `-30`. Always tell the user how many seconds were removed.

### join.py — concatenate with transitions
```
join.py CLIP1 CLIP2 [...] [--transition fade|dissolve|wipeleft|slideleft|fadeblack|fadewhite|circleopen|none]
        [--duration 0.5] [--width W --height H] [--fps N] [--fit pad|crop] [-o OUT]
```
Normalises every clip to one frame size, fps, `yuv420p` and 48 kHz stereo
(silent track generated for clips without audio), then chains `xfade` +
`acrossfade`. Output length = sum of clips − transition × (n−1). Clips must be
longer than 2 × the transition. Use `--transition none` for a plain cut.

### render.py — the whole edit in one project.json
```
render.py --init project.json                # starter file
render.py project.json [--fast] [--dry-run] [--stop-after STAGE] [--work DIR --keep]
```
Stages: clips (cut, optional speed) → join (transition) → silence → fit →
captions → graphics → overlays → audio → loudness → export → check. Keys mirror the
CLI flags of each script (see the docstring). Use it whenever an edit has
more than two steps or the user is likely to ask for changes: edit the JSON,
re-render, and the result is reproducible. `--dry-run --json` prints the
complete command plan for review.

### scenes.py — scene changes and highlight candidates
```
scenes.py INPUT [--threshold 10] [--min-scene 1] [--highlights N [--target SECONDS] [--max-scene 15]] [--edl picks.txt] [--sheet scenes.png] [--json]
```
Lists scenes with audio energy, the loudest moments, and (with
`--highlights`) proposes N ranges that add up to `--target` seconds, biased to
the loudest window of each scene. Review the sheet + JSON, adjust the EDL, then
`cut.py --segments`. Cut detection is a one-frame spike test (benchmark on
hard cuts between real single takes: precision 0.95, recall 1.00 at the default
threshold; raise `--threshold` to 12 for 0.98 precision at 0.94 recall).
Dissolves and very slow fades are not cuts and will be missed. Highlights are
a proposal engine, not a judgement of content: tell the user what it picked
and why (energy, scene length).

### check.py — pre-delivery compliance
```
check.py INPUT --platform youtube|shorts|reels|tiktok|x|linkedin|broadcast|podcast|custom [--no-loudness] [--json]
         [--max-duration S] [--aspect 9:16] [--lufs -14] [--tp -1] [--max-mb N]
```
PASS/WARN/FAIL per check with the script that fixes it. Run it as the final
step before reporting a deliverable; fix FAILs, mention WARNs.

### batch.py — same recipe over a folder, cached
```
batch.py FOLDER --recipe batch.json [--force] [--watch SECONDS] [--json]
```
`batch.json` holds either `steps` (a list of script argv with `{in}`/`{out}`
placeholders, chained) or `project` (a render project applied per file).
Outputs land in `output_dir` with `suffix`; a content-hash cache skips files
already done with the same recipe. Use `--dry-run` to preview the plan.

### caption.py --transcribe — optional local speech-to-text
If `whisper-cli` (whisper.cpp), `faster-whisper` or `whisper` is installed,
`caption.py input.mp4 --transcribe [--language ja] [--model base]` writes the
SRT from the audio and burns it (combine with `--animate pop --karaoke`).
Nothing is downloaded and nothing is required: without an engine it prints
install hints and the user can supply `--text` cues instead. Always tell the
user which engine was used, and treat the transcript as a draft to review.

### MCP server — the toolkit for any MCP client
`python3 mcp/server.py` speaks MCP over stdio; each script is a tool taking
named args (flags without dashes, underscores for hyphens) or `argv`. Config
for Claude Desktop / Claude Code:
`{"mcpServers": {"ffmpeg-skill": {"command": "python3", "args": ["~/.claude/skills/ffmpeg-skill/mcp/server.py"]}}}`.
Inside this skill, call the scripts directly; the server is for other hosts.

### graphics.py — motion-graphics templates
```
graphics.py INPUT --template lower-third|title|chapter|progress|countdown|bug [--name] [--title] [--subtitle]
            [--from N] [--start S] [--end E] [--position CORNER] [--brand brand.json] [--primary RRGGBB] [--scale 1.0] [-o OUT]
```
Drawn with drawbox/drawtext/overlay — no PNG assets needed. Sizes scale with
the frame's short side; colours, font and safe margin come from `--brand`.
Lower-third slides in over 0.4 s and out over 0.3 s; title/chapter/bug fade.

### brand.json — one file for fonts, colours, logo, margins
```json
{"font": "Noto Sans CJK JP", "font_file": "fonts/NotoSansCJK-Bold.ttc",
 "colors": {"primary": "FF6A00", "text": "FFFFFF", "outline": "000000", "background": "0B1D2A"},
 "logo": "logo.png", "logo_position": "top-right", "logo_scale": 160, "logo_opacity": 0.9,
 "safe_margin": 48, "caption": {"size": 28, "position": "bottom", "animate": "pop", "karaoke": true, "bold": true}}
```
`caption.py --brand`, `overlay.py --brand --logo`, `graphics.py --brand`, and
`"brand": "brand.json"` in a render project. Explicit flags still win. When a
user mentions brand guidelines, colours, "our font" or a logo, ask for or
write a brand.json once and reuse it across every output.

### report.py — HTML delivery report
```
report.py --after FINAL [--before SOURCE] [--platform youtube] [--commands cmds.txt] [--notes notes.md] [--title T] [--no-sheets] [-o report.html]
```
One self-contained HTML: before/after facts and contact sheets, loudness,
compliance table with fixes, commands. Produce it for any multi-step job and
hand the path to the user together with the numbers.

### multicam.py — align several cameras and switch between them
```
multicam.py REF CAM2 [CAM3 ...] [--switch "START-END:CAM,..."] | [--auto N] [--audio IDX] [--fix-drift]
            [--offsets-only] [--width W --height H --fps N] [-o OUT]
```
All inputs are aligned to the first one by audio (same engine as `sync.py`,
`--fix-drift` for long takes). `--switch` names which camera is on screen for
each range of the reference timeline (gaps fall back to camera 0), `--auto N`
simply alternates every N seconds. Audio comes from the reference unless
`--audio` picks another input, e.g. an external recorder that has no video.
`--offsets-only` reports offsets and confidence without rendering.

### verify.py — real-footage verification kit
```
verify.py FILES_OR_FOLDERS [--quick] [--report verify.md] [--out DIR --keep] [--seconds 6] [--json]
```
Runs the toolchain on the user's own files (phone HDR, GoPro, OBS, Log, Zoom)
and prints a PASS/FAIL table per step (probe, copy cut, accurate cut, fit,
caption, overlay, look, export, loudness, silence, plus `color --to-sdr` for
HDR and `audio --downmix` for >2 channels). Exit code 1 if anything fails.
Run this first when a user hands over footage from a device you have not
seen before, and fix or report what fails.

### look.py — see the result
```
look.py INPUT [--tiles 4x3] [--width 1280] [-o sheet.png]         # contact sheet with timecodes
look.py INPUT --at 2.5 [--at 7] [-o basename]                     # single frames -> basename_2.500s.png
look.py BEFORE --compare AFTER --at 4 [-o cmp.png]                # side-by-side frame
```
Outputs PNG. View it with the Read tool (or any image viewer) and judge the
frame like an editor would. Use `--compare` to show before/after to the user.

### caption.py — subtitles (static, animated, karaoke)
```
caption.py INPUT --srt FILE | --ass FILE | --text CUES.txt [--write-srt OUT.srt]
           [--font NAME] [--fonts-dir DIR] [--size N] [--color RRGGBB] [--outline N] [--outline-color RRGGBB]
           [--bold] [--box] [--position bottom|top|center|top-left|...] [--margin N]
           [--animate none|fade|pop|slide] [--karaoke [--highlight-color RRGGBB]] [--write-ass OUT.ass] [-o OUT]
caption.py --text CUES.txt --write-srt OUT.srt        # generate the SRT only
```
Text cue format, one per line: `0:00-0:03 Hello`, `00:00:03.500 --> 00:00:06 Two | lines`.
Lines without a time run for `--auto-seconds` (3 s) after the previous cue. `|` is a line break.
`--animate`/`--karaoke` generate a styled ASS (PlayRes = video size) from the
SRT/text cues: `pop` is the short-form "bouncy" entrance, `--karaoke` fills each
word from `--color` to `--highlight-color` evenly across the cue (word timing
is distributed, not transcribed). The ASS is kept next to the output so the
user can hand-tune timings and re-run with `--ass`.

### overlay.py — logo, image, title
```
overlay.py INPUT --image PNG [--scale W | --scale-percent P] | --text "..." [--font-file F.ttf] [--font-size N] [--box]
           [--position top-right|bottom-left|center|X,Y] [--margin N] [--start T] [--end T] [--fade S] [--opacity 0-1] [-o OUT]
```
Alpha in PNGs is respected. Fades apply to the overlay only; the video keeps playing.

### sync.py — offset detection, alignment, drift correction
```
sync.py REFERENCE SECOND [--json] [--max-offset 30] [--analyze-seconds 120] [--fix-drift [--drift-window 60]]
        [--replace-audio | --trim-second] [-o OUT]
```
Cross-correlates loudness envelopes: coarse FFT search (20 ms), then a direct
1 ms refinement (pure Python, a 2-minute window takes ~1-3 s). Positive offset
= the second recording started later. `--replace-audio` writes the reference
video with the second file's audio aligned (video stream copied).
`--trim-second` writes the second file shifted to the reference timeline.
`--fix-drift` measures the offset again near the end of the overlap, reports
the clock difference in ppm, and resamples the second file so a 60-minute
take stays in sync (typical consumer devices drift 20-500 ppm = up to 1.8 s/h).
Use it whenever the recording is longer than ~10 minutes. Check `confidence`
(0–1, normalised correlation with a runner-up penalty); below 0.3 the match is
doubtful. Benchmark on real dialogue/music (±30 s offsets, gain, noise, EQ):
with the default 120 s window 40/40 within 10 ms (max 1.1 ms); with a 60 s
window 95 %, misses flagged below 0.3. Keep `--analyze-seconds` at least 4×
`--max-offset` (default 120 s vs 30 s): lags with under 35 % overlap are
ignored, so an offset larger than ~60 % of the window cannot be found.

### color.py — HDR to SDR, LUTs, colour tags, Dolby Vision
```
color.py INPUT --to-sdr [--tonemap hable|mobius|reinhard|bt2390] [--peak 1000] [--desat 0] [-o OUT]
color.py INPUT --lut grade.cube [--lut-strength 0..1] [-o OUT]
color.py INPUT --retag bt709|bt2020-pq|bt2020-hlg|bt601 [-o OUT]      # metadata only, stream copy
color.py INPUT --strip-dovi [-o OUT]                                 # drop the Dolby Vision RPU, keep the HLG/HDR10 base layer (stream copy)
```
iPhone "HDR" video is Dolby Vision profile 8.4 on an HLG base layer:
`probe.py` reports `hdr_format: Dolby Vision profile 8` and `--to-sdr`
tone-maps it from the HLG base layer. When the user wants to keep HDR but
players mis-render the DV layer, `--strip-dovi` removes it losslessly.
`--to-sdr` does a real conversion: linearise (zscale, PQ or HLG), tone-map
(default `hable`, `mobius` keeps more highlight detail, `bt2390` is the
broadcast standard), then BT.709 gamma + matrix. Refuses when probe says the
input is not HDR unless `--force`. `--lut` applies a 3D .cube with
tetrahedral interpolation (Log→709 conversions, creative looks); blend with
`--lut-strength`. Everything else in the skill assumes SDR BT.709, so run this
first on HDR or Log sources.

### audio.py — clean-up, music, ducking, layout
```
audio.py INPUT [--voice | --denoise [--denoise-strength 25]] [--gain dB]
         [--music FILE [--music-volume -14] [--duck [--duck-amount 12]] [--music-loop]]
         [--fade-in S] [--fade-out S] [--stereo | --mono | --downmix] [--replace FILE] [-o OUT]
```
`--voice` = highpass 80 Hz → de-esser → FFT denoise → gentle compressor, the
standard talking-head chain. `--duck` uses a sidechain compressor keyed by the
speech so music dips under dialogue and swells in pauses. `--downmix` uses the
ITU centre/LFE weights for 5.1/7.1 → stereo. Video is always stream-copied.
Run `loudness.py` after this for final levels.

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
  disagree. Every re-encoding script then adds `-fps_mode cfr` at the source's
  average rate, and `cut.py` switches itself to `--accurate` (copy-cuts on VFR
  are unreliable). Pick the rate explicitly with `fit.py --fps 30|60` when the
  average is odd (e.g. 23.4 fps from dropped frames).
- **Audio drift / sync.** Don't mix files with different frame rates or sample
  rates in one `cut.py --segments` join without re-encoding (`--accurate`).
  After `sync.py`, verify by running it again on the output: offset (and drift
  ppm with `--fix-drift`) should be ~0. Recordings longer than ~10 minutes from
  separate devices: always use `--fix-drift`.
- **Colour.** SDR outputs are H.264 tagged BT.709 `yuv420p`. When `probe.py`
  reports `hdr: true` (HDR10/PQ, HLG, Dolby Vision, BT.2020), every editing
  script keeps the output HDR (HEVC Main10, source colour tags) so nothing is
  silently flattened. Decide with the user: keep HDR (fine for YouTube/phones)
  or run `color.py --to-sdr` first for SDR-only destinations, LUT work or
  H.264 deliverables. `export.py` platform presets are SDR and warn on HDR
  input. iPhone `.mov` files also carry timecode/metadata tracks; scripts map
  only the first audio track, so extra tracks are dropped on re-encode.
  For Log footage (S-Log, V-Log, C-Log: looks grey and low-contrast but is
  tagged SDR) run `probe.py --analyze`; `looks_like_log: true` means apply the
  manufacturer's `.cube` with `color.py --lut` before anything else. Keep
  ProRes masters at source colour: `export.py --preset prores` does not retag.
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
