# Script reference

Every script prints the same information with `--help`; this file exists so the agent can read several at once. All scripts accept `--dry-run`, `--json`, `--fast`, `--progress`, `-o OUT` -- but `--dry-run` only guarantees nothing is written for writing tools: `probe` (read-only, `--dry-run` changes nothing) and `check` (skips only the loudness-measurement pass) still run ffprobe/ffmpeg, `sync`/`multicam`/`scenes`/`report` still run ffmpeg/ffprobe to measure or analyse (they just don't write the final artifact), and `verify` accepts the flag but ignores it entirely. Exact per-tool semantics: `contract --json`'s `dry_run` field (or `docs/contract.md`).

## Contents
- probe.py — inspect
- cut.py — cut / join segments
- fit.py — target duration and/or aspect, rotate/flip
- crop.py — crop to an exact pixel rectangle
- insert.py — still image to a timed silent clip, with Ken Burns zoom/pan
- background.py — generate a solid-colour or gradient clip
- reverse.py — reverse playback
- stabilize.py — motion stabilisation (vidstab)
- sequence.py — numbered/globbed image sequence to video
- silence.py — remove dead air / jump cuts
- join.py — concatenate with transitions
- render.py — the whole edit in one project.json
- scenes.py — scene changes and highlight candidates
- check.py — pre-delivery compliance
- batch.py — same recipe over a folder, cached
- caption.py --transcribe — optional local speech-to-text
- MCP server — the toolkit for any MCP client
- graphics.py — motion-graphics templates
- brand.json — one file for fonts, colours, logo, margins
- report.py — HTML delivery report
- multicam.py — align several cameras and switch between them
- verify.py — real-footage verification kit
- look.py — see the result
- caption.py — subtitles (static, animated, karaoke)
- overlay.py — logo, image, title, video picture-in-picture, chroma key
- sync.py — offset detection, alignment, drift correction
- color.py — HDR to SDR, LUTs, colour tags, Dolby Vision
- audio.py — clean-up, music, ducking, layout
- loudness.py — EBU R128 normalisation
- export.py — delivery presets
- proxy.py — low-bitrate proxy for analysis/preview

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

### fit.py — target duration and/or aspect, rotate/flip
```
fit.py INPUT [--duration T --method speed|trim [--from-center] [--max-speed 4]]
             [--aspect 16:9|9:16|1:1|4:5|W:H --fit pad|crop [--width W] [--height H] [--pad-color black]]
             [--rotate 90|180|270] [--flip h|v] [--fps N] [-o OUT]
```
`speed` retimes video and audio together (pitch-preserving `atempo`); it
refuses factors beyond `--max-speed`. For slow motion add `--smooth blend`
(frame blending, fast) or `--smooth interpolate` (motion-compensated
`minterpolate`, fluid but roughly 10-20x slower than realtime). `trim` keeps
the head (or the middle with `--from-center`). `--width`/`--height` set the
output size: give one and the other follows the aspect (source aspect if
`--aspect` isn't also given); give both for an exact frame. `--rotate` applies
a new clockwise rotation (90/180/270 swap width/height for 90 and 270 — this
is separate from the rotation *metadata* fit.py already reads to size a
source correctly); `--flip h|v` mirrors the picture; both can combine, rotate
first. `--fps` forces a constant frame rate; VFR sources are conformed
automatically even without it.

### crop.py — crop to an exact pixel rectangle
```
crop.py INPUT --x X --y Y --width W --height H [-o OUT]
```
Crops to a literal `{x, y, width, height}` rectangle in source pixels —
distinct from `fit.py --fit crop`, which crops to an *aspect ratio* and picks
the rectangle for you. Use this when the rectangle is already known (a
face-detection box, a saved crop, a hand-picked region). The rectangle must
lie entirely inside the source frame (after accounting for display rotation);
`--width`/`--height` must be even (4:2:0 chroma) and are refused, never
rounded, if they aren't.

### insert.py — still image to a timed silent clip
```
insert.py IMAGE --duration T [--width W] [--height H] [--fps N]
                 [--zoom in|out [--zoom-amount 1.3]] [--pan left|right|up|down] [-o OUT]
```
Produces a silent, exact-duration clip from one image. `--width`/`--height`
resolve like `fit.py`'s (one given -> the other follows the image's aspect;
both given -> exact frame, scaled to fill and centre-cropped, never
distorted). `--zoom in|out` is a Ken Burns effect: a slow linear zoom across
the whole clip, ending (zoom in) or starting (zoom out) at `--zoom-amount`
(default 1.3). `--pan` drifts the visible window across the image while
zoomed — it needs `--zoom` (panning uses the extra image area a zoom exposes).

### background.py — generate a solid-colour or gradient clip
```
background.py -o OUT --duration T --width W --height H
              [--color C | --gradient C1:C2 [--angle DEG]]
```
No input file: ffmpeg's own `color`/`gradients` source filters generate the
clip directly. For a title-card background, a placeholder layer, or a base
for `overlay.py` to composite onto. `--width`/`--height` must be even.

### reverse.py — reverse playback
```
reverse.py INPUT [--no-audio] [-o OUT]
```
Reverses video (and audio, unless `--no-audio`) with ffmpeg's `reverse`/
`areverse` filters, which buffer the whole clip in memory — keep this to
clips it makes sense to reverse (seconds to a couple of minutes), not
something this tool limits for you.

### stabilize.py — motion stabilisation
```
stabilize.py INPUT [--shakiness 1-10] [--smoothing N] [--zoom 0-100] [-o OUT]
```
Two-pass `vidstabdetect`/`vidstabtransform`: pass 1 analyses camera motion to
a temporary transforms file (deleted after the run), pass 2 smooths and
re-renders. `--shakiness` (default 5) trades analysis time for how much
motion it looks for; `--smoothing` (default 15) is how many neighbouring
frames the camera path is averaged over; `--zoom` crops in slightly to hide
the black edges stabilizing can introduce. Needs an ffmpeg built with
`--enable-libvidstab`; `doctor` reports this tool `usable: no` when that's
missing (a plain Homebrew ffmpeg build, for example) rather than failing at
run time.

### sequence.py — numbered/globbed image sequence to video
```
sequence.py --dir DIR --pattern "frame_%04d.png"|"*.png" --fps N
            [--start-number N] [--width W] [--height H] [-o OUT]
```
Turns a numbered or glob-matched set of still images into a video. The match
is checked on disk before ffmpeg runs (an empty match or a missing first
frame is refused here, not discovered from an opaque ffmpeg error).

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
           [--mode burn|mux] [--audio-stream N] [--fps N]
           [--font NAME] [--fonts-dir DIR] [--size N] [--color RRGGBB] [--outline N] [--outline-color RRGGBB]
           [--bold] [--box] [--position bottom|top|center|top-left|...] [--margin N]
           [--animate none|fade|pop|slide] [--karaoke [--highlight-color RRGGBB]] [--write-ass OUT.ass] [-o OUT]
caption.py --text CUES.txt --write-srt OUT.srt        # generate the SRT only
```
Text cue format, one per line: `0:00-0:03 Hello`, `00:00:03.500 --> 00:00:06 Two | lines`,
or `00:00:03:15 --> 00:00:06:00 SMPTE non-drop-frame timecode` (`hh:mm:ss:ff`, frame count
converted with `--fps`, or the input video's own fps when `--input` is given and `--fps` is
not — a timecode-shaped cue with no fps available is refused rather than misread as plain text).
Lines without a time run for `--auto-seconds` (3 s) after the previous cue. `|` is a line break.
`--animate`/`--karaoke` generate a styled ASS (PlayRes = video size) from the
SRT/text cues: `pop` is the short-form "bouncy" entrance, `--karaoke` fills each
word from `--color` to `--highlight-color` evenly across the cue (word timing
is distributed, not transcribed). The ASS is kept next to the output so the
user can hand-tune timings and re-run with `--ass`.
`--mode burn` (default) renders subtitles into the picture and always
re-encodes both streams. `--mode mux` copies video and audio untouched and
adds the SRT as a separate, player-toggleable subtitle stream instead —
takes only a plain SRT (`--srt`/`--text`/`--transcribe`, not `--ass`, since
styling has no soft-subtitle equivalent) and no `--animate`/`--karaoke`. The
subtitle codec follows the output container: `mov_text` for `.mp4`/`.m4v`/`.mov`,
`srt` for `.mkv`, `webvtt` for `.webm`.
`--audio-stream N` (default 0, the first track) picks which audio stream of a
multi-track input (dubbed languages, M&E stems) is kept — applies to burn's
re-encoded audio, mux's stream-copied audio, `--transcribe`'s speech-to-text
source, and karaoke's energy-timing analysis alike, so all four agree on the
same track instead of each silently defaulting to whichever one ffmpeg's own
stream selection would have picked.

### overlay.py — logo, image, title, video picture-in-picture, chroma key
```
overlay.py INPUT --image PNG [--scale W | --scale-percent P] | --text "..." [--font-file F.ttf] [--font-size N] [--box]
                  | --video CLIP [--chromakey COLOR [--chromakey-similarity 0-1] [--chromakey-blend 0-1]]
           [--position top-right|bottom-left|center|X,Y] [--margin N] [--start T] [--end T] [--fade S] [--opacity 0-1] [-o OUT]
```
Alpha in PNGs is respected. Fades apply to the overlay only; the video keeps
playing. `--video` composites a second video as a picture-in-picture layer
(same position/scale/opacity/time-range knobs as `--image`); only the main
input's audio is kept, the PiP layer's own audio is dropped. `--chromakey`
(with `--video`) keys out that colour first for green-screen compositing.

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
color.py INPUT --correct [--exposure -3..3] [--contrast 0..2] [--saturation 0..2] [--gamma 0.1..10]
         [--temperature 2000..12000] [--tint -1..1] [--lift -1..1] [--gain -1..1]
         [--levels-in-black 0..255] [--levels-in-white 0..255] [--levels-out-black 0..255] [--levels-out-white 0..255]
         [--curves color_negative|cross_process|darker|increase_contrast|lighter|linear_contrast|medium_contrast|negative|strong_contrast|vintage] [-o OUT]
```
`--correct` is typed primary colour correction, no filter string ever accepted:
`--exposure`/`--contrast`/`--saturation`/`--gamma` (`exposure`/`eq` filters),
`--temperature`/`--tint`/`--lift`/`--gain` (`colortemperature`/`colorbalance`
filters — `--tint` sets midtones, `--lift` shadows, `--gain` highlights, a
classic three-way correction), `--levels-*` (`colorlevels`, 8-bit units
converted to the filter's own 0..1 range, only added to the chain when at
least one is given) and `--curves` (the `curves` filter's own built-in
presets, only added when given). Every flag is range-checked against this
script's own safe subset of what `ffmpeg -h filter=<name>` documents before
ffmpeg runs. `--json`'s `measurements` reports `analyze_levels()` (signalstats
luma/saturation) for input and output side by side.

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

### proxy.py — low-bitrate proxy for analysis/preview
```
proxy.py INPUT [--width W | --scale F] [--crf N] [--fps N] [--no-audio] [-o OUT]
```
Not a delivery preset: resizes to `--width` (default 640) or by `--scale`
factor, re-encodes at a proxy-grade `--crf` (default 30) with the fastest
x264/x265 preset, keeps the source's own dynamic range (HDR stays HDR;
run `color.py --to-sdr` first if SDR is wanted). Only executes the spec
given — does not decide which asset to proxy or what for.

