# Script reference

Every script prints the same information with `--help`; this file exists so the agent can read several at once. All scripts accept `--dry-run`, `--json`, `--json-brief` (since 1.11.0: the same JSON result trimmed to `status`, `output`, `dry_run`, `verified`, a compact `summary` of the output probe -- duration_s, width, height, fps, vcodec, acodec, channels, and lufs when measured -- the tool's own keys, and the count of commands instead of the command lines; it implies `--json`, leaves `--json`'s own output untouched, and failures print the usual full failure document), `--fast`, `--progress`, `--timeout SECONDS`, `--overwrite`, `--plan FILE` (the dry run written as a plan document that `render.py FILE` executes later; see render.py), `-o OUT`; every editing tool that re-encodes (not `export.py`, whose preset decides the codec) also takes `--codec h264|hevc|av1|prores` (the encoder for the re-encode; default x264 for SDR, x265 Main10 for HDR, unchanged) and `--quality N` (CRF scale, overrides `--crf`; up to 63 for av1; ignored by prores). `--crf` is deprecated since 1.10.0 (it warns on stderr and is removed in 2.0): use `--quality`, except on `export.py`, whose `--crf` is not an alias and stays. With `FFMPEG_SKILL_NO_OVERWRITE=1` in the environment, any tool refuses (`kind: input`) to replace an existing output unless `--overwrite` is given. `--codec hevc` on SDR writes 8-bit BT.709 HEVC (`hvc1`), `av1` uses SVT-AV1 (libaom fallback), `prores` is 422 HQ and needs an explicit `-o NAME.mov` (or `.mkv`), `h264` refuses an HDR source (`kind: input`, run `color.py --to-sdr` first). `export.py` keeps choosing the codec from its preset and has neither flag; a `render.py` project cannot choose a codec either -- but `--dry-run` only guarantees nothing is written for writing tools: `probe` (read-only, `--dry-run` changes nothing) still runs ffprobe, `check`/`sync`/`multicam`/`scenes`/`cropdetect`/`report`/`silence`/`loudness`/`stabilize` still run their ffmpeg/ffprobe measurements (a dry-run plan rests on real numbers; they just don't write the final artifact), and `verify` accepts the flag but ignores it entirely. Exact per-tool semantics: `contract --json`'s `dry_run` field (or `docs/contract.md`).

## Time grammar (every time-taking flag, 1.9)

One parser, `time_arg()`, behind every `--start`, `--end`, `--at`, `--from`,
`--duration`, `--segments`, cue file and project field: seconds (`12.5`),
`mm:ss(.fff)` (`1:30`), `hh:mm:ss(.fff)` (`00:01:30.250`; a comma also works,
as in SRT). A four-part `hh:mm:ss:ff` is SMPTE non-drop-frame timecode at the
source's frame rate; append `@fps` (`00:01:02:15@29.97`) to name the rate
yourself, which is the only way for a tool with no input file (`caption.py
--text` without a video, and `--fps` there). A four-part value with no fps
anywhere is `kind: input` naming the flag. Nothing else about times differs
between tools.

## Contents
- probe.py — inspect
- cut.py — cut / join segments
- fit.py — target duration and/or aspect, rotate/flip
- crop.py — crop to an exact pixel rectangle
- insert.py — still image to a timed silent clip, with Ken Burns zoom/pan
- broll.py — cut away to a B-roll clip for a window and come back
- metadata.py — chapter markers and title/artist/comment tags, streams copied
- background.py — generate a solid-colour or gradient clip
- reverse.py — reverse playback
- stabilize.py — motion stabilisation (vidstab)
- sequence.py — numbered/globbed image sequence to video
- silence.py — remove dead air / jump cuts
- join.py — concatenate with transitions
- render.py — the whole edit in one project.json
- delivery templates — one command per destination (`--template`)
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
JSON with `duration`, `video{codec,width,height,fps,pix_fmt,color_space,rotation,variable_frame_rate_suspected,hdr,hdr_signal,hdr_format}`
(`hdr_signal` is true only for a PQ / HLG transfer or Dolby Vision; `hdr` also counts
BT.2020 primaries on an SDR transfer, which `hdr_format` names "BT.2020 SDR" -- 2.0 renames),
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
the result was "lossless stream copy" or "re-encoded"; when the snap forced a
re-encode, the result's `lossless_alternative` names the nearest keyframe
`--start` that would stream-copy instead, so the trade can be offered.

### fit.py — target duration and/or aspect, rotate/flip
```
fit.py INPUT [--duration T --method speed|trim [--from-center] [--max-speed 4]]
             [--aspect 16:9|9:16|1:1|4:5|W:H --fit pad|crop|blur [--width W] [--height H] [--pad-color black] [--pad-fill color|blur [--pad-blur 20]]]
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
`--pad-fill blur` fills the letterbox/pillarbox bars with a blurred, scaled-to-cover copy
of the frame (the look every phone editor gives landscape footage posted as a Short/Reel)
instead of the solid `--pad-color`; `--pad-blur` is the blur radius. `export.py --fit pad`
takes the same two flags. `--fit blur` (1.14) is the same fill named in one word and with the
background dimmed (`eq brightness=-0.15`) so the picture in front reads as the subject: the
whole frame is kept (nothing cropped), the borders are a blurred copy of it rather than black.
A delivery template asks for it as `"frame": {"aspect": "9:16", "fit": "blur"}`, or
`render.py --template tiktok clip.mp4 --fit blur`. The dimming is applied to SDR sources only:
an `eq` on PQ/HLG code values is not the −15 % perceptual dim it is on SDR, so an HDR source
keeps a blurred but undimmed background (and is never silently tone-mapped); `info` says so.

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

### cropdetect.py — measure black bars, report the crop rectangle
```
cropdetect.py INPUT [--seconds N] [--samples N] [--limit F] [--round N]
```
Measurement only -- writes no file. Samples `--samples` windows spread
across the file (default 5, totalling `--seconds` 10s of footage) and
reports the crop rectangle FFmpeg's `cropdetect` filter found most often, as
`{x, y, width, height}` ready to hand to `crop.py`. Distinct from
`fit.py --fit crop`, which crops to a target aspect ratio it computes
itself with no black-bar measurement involved. A rectangle that matches the
full source frame means no bars were found. Does not decide whether
removing detected bars is wanted -- genuine letterboxed content (a
scope-ratio film in a 16:9 frame) "detects" the same way as accidental
bars; look at the frame before cropping it away.

### deinterlace.py — deinterlace interlaced footage
```
deinterlace.py INPUT [--mode frame|field] [--parity auto|tff|bff] [--only-interlaced] [-o OUT]
```
Wraps FFmpeg's `yadif` filter. `--mode frame` (default) keeps the source
frame rate; `--mode field` emits one frame per field, doubling the output
frame rate. `--parity` overrides field order when the container gets it
wrong; `--only-interlaced` skips frames the source doesn't itself mark
interlaced. Does not detect whether the source needs deinterlacing --
that's a `look.py` judgement call (visible combing on motion).

### denoise.py — reduce video noise/grain
```
denoise.py INPUT [--strength low|medium|high] [--luma-spatial F] [--chroma-spatial F]
                  [--luma-temporal F] [--chroma-temporal F] [-o OUT]
```
Wraps FFmpeg's `hqdn3d` filter. `--strength` picks a tested preset scaling
all four of hqdn3d's spatial/temporal luma/chroma parameters together; the
four `--luma-*`/`--chroma-*` flags override any of them individually.
Heavier denoising trades fine detail for a cleaner but softer image -- for
audio noise reduction use `audio.py --denoise` instead, this tool only
touches the picture.

### redact.py — blur or pixelate an exact rectangle
```
redact.py INPUT --x X --y Y --width W --height H [--mode blur|pixelate]
                 [--blur-strength N] [--block-size N] [-o OUT]
```
Same rectangle convention as `crop.py` -- the rectangle must already be
known (a saved detection box, a hand-picked region); this tool does not
locate faces or plates itself. `--mode blur` (default) box-blurs the
rectangle; `--mode pixelate` mosaics it into `--block-size`-px blocks, the
more unmistakably-redacted look often wanted for compliance footage. The
rest of the frame, and the whole clip's timeline, are untouched -- to
redact only part of the timeline, `cut.py` the clip into segments first.

### sphere.py — flat viewport extraction from 360/spherical video
```
sphere.py INPUT [--input-projection equirect|fisheye|dfisheye|c3x2|c6x1|barrel|cylindrical|hequirect]
                 [--yaw D] [--pitch D] [--roll D] [--h-fov D] [--v-fov D]
                 [--width W] [--height H] [--interp METHOD] [--stereo mono|sbs|tb]
                 [--audio-stream N] [-o OUT]
```
Wraps FFmpeg's `v360` filter to bake out an ordinary flat clip pointed at a
fixed direction — the same "look this way" operation a VR headset or a 360
player's viewport does. `--yaw`/`--pitch`/`--roll` aim the camera (each
-180..180, default 0); `--h-fov`/`--v-fov` set how wide the view is (each
1..170, default 90/60). `--input-projection` must match the source's own
projection (default `equirect`, the most common capture/export format) —
this tool cannot detect it from the pixels, so a wrong value produces a
distorted or garbled output, not an error. There is no subject detection or
tracking here: only the typed aim you give it. For a shot that follows a
moving subject, call this once per keyframe viewpoint from outside this
tool. `--width`/`--height` must be even (4:2:0 chroma); default 1920x1080.

### straighten.py — rotate by an arbitrary angle (horizon correction)
```
straighten.py INPUT --degrees D [--fit crop|pad] [--fill-color C] [-o OUT]
```
Distinct from `fit.py --rotate`, which only turns the picture in exact
90-degree steps -- this wraps FFmpeg's `rotate` filter for a small
corrective tilt (`--degrees`, -45..45). Rotating by a non-90-degree angle
leaves triangular gaps at the corners: `--fit crop` (default) scales up
just enough to fill the frame with no visible gap, losing a thin border of
the original picture; `--fit pad` keeps the full original picture and fills
the gaps with `--fill-color`. Does not measure the tilt itself -- give the
degrees once you can see how far off it is (a `look.py` judgement call).

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
Turns a numbered or glob-matched set of still images into a video. Glob
matches are ordered naturally (`img2` before `img10`). The match
is checked on disk before ffmpeg runs (an empty match or a missing first
frame is refused here, not discovered from an opaque ffmpeg error).

### waveform.py — audio waveform/spectrum visualization video
```
waveform.py INPUT [--style waveform|spectrum] [--width W] [--height H] [--fps N]
                   [--color C] [--background C] [--waveform-mode M] [--split-channels]
                   [--image PATH] [--image-fit cover|contain|blur]
                   [--position bottom|centre|top|strip] [--vis-height FRAC] [--opacity 0..1]
                   [--platform NAME] [--srt FILE | --text FILE] [--title TEXT] [--brand brand.json]
                   [-o OUT]
```
Renders the input's audio as a video: `--style waveform` (default, FFmpeg's
`showwaves`) draws amplitude over time; `--style spectrum` (`showspectrum`)
draws a frequency-over-time heatmap instead, reading more out of dense
mixes at the cost of being less immediately readable. The output always
carries the audio it visualizes. For an audio-only input (no video stream
needed) or any file with an audio track worth visualizing.

**Audiogram (1.16).** `--image PATH` puts a local still behind the
visualisation, which is what turns a podcast episode into something postable.
`--image-fit cover` (default) scales to cover and centre-crops; `contain` pads
with `--background`; `blur` uses fit.py's blurred-pad plate. `--position`
places the band (`strip`, the default, is a band of `--vis-height` -- a
fraction of the frame, default 0.35 -- along the bottom, the podcast
convention); `--opacity` fades the visualisation over the plate. `--platform`
takes the frame size and fps from the delivery table and refuses a destination
with no frame (`podcast`) -- the still is fed at that rate, so the plate cannot
quietly decide the output's frame rate, and the run verifies the rate it
announced along with the frame size and the duration. `--image` must be a file
ffmpeg can actually decode: one that is not is refused (`kind: input`) before
any encode starts. `--title` draws one label through graphics.py's
sticker template and `--srt`/`--text` burns captions by running caption.py
afterwards -- both as second processes, so neither of those code paths is
re-implemented here. `--image` must be a readable local file: a URL is refused
(`kind: input`), nothing is fetched, and the skill never invents cover art --
give an image or a colour. Without any of these flags the command line is
byte-identical to 1.15's. Every run's result carries an `audiogram` object (style,
background, image, position, vis_height, platform, captions, title, stages,
verified). `render.py --template audiogram` is the one-call form; it is
deliberately not part of `--template all`.

### freeze.py — hold a frame for N seconds
```
freeze.py INPUT --hold T [--at T] [--mode insert|extend] [-o OUT]
```
`--at` (default: the last frame) is the timestamp to freeze; `--hold` is
how long the freeze lasts. `--mode insert` (default) inserts the hold at
`--at`, pushing everything after it later by `--hold` seconds. `--mode
extend` only works with `--at` at (or past) the clip's end and just makes
the last frame last `--hold` seconds longer, with nothing pushed. Audio is
silent during the held frame in `--mode insert` (there is no source audio
for a frozen moment that didn't exist before). `--mode insert` drops a
subtitle/data track rather than copy it with timestamps that no longer match
the pushed picture (`dropped_non_av_streams: true` in the result), as
`fit.py --method speed` does; `--mode extend` keeps it.

### pad.py — add black/silent padding at the start/end
```
pad.py INPUT [--start T] [--end T] [--color C] [-o OUT]
```
Distinct from `fit.py --fit pad`, which pads the *frame* (letterbox/
pillarbox bars around each existing frame) -- this pads the *timeline*:
extra seconds of solid colour and silence before and/or after the clip's
existing content (seconds or `mm:ss`). At least one of `--start`/`--end` must be > 0.

### speedramp.py — step through different speeds across a clip
```
speedramp.py INPUT --segment START-END:FACTOR [--segment ...] [-o OUT]
```
Distinct from `fit.py --duration --method speed`, which applies one
constant factor to the whole clip -- this takes a list of `--segment`
pieces (repeatable) covering the clip start to end with no gaps or
overlaps, each played at its own constant speed (pitch-preserving audio,
matching `fit.py`), then concatenates them: "speed up, then slow way down
for the punch, then speed back up," built from a few constant segments
rather than a continuous curve. `START`/`END` take seconds or `mm:ss`;
`FACTOR` is 0.05..20 (2.0 = twice as fast,
0.5 = half speed). Picking exactly where a ramp should ease in or out is a
judgement call for the calling agent, made concrete here as the segment
boundaries it supplies.
A subtitle/data track in the source is not carried into the retimed/concatenated
output; the result says so with `dropped_non_av_streams: true`.

### loop.py — repeat a clip
```
loop.py INPUT --times N | --duration T [-o OUT]
```
`--times` repeats the whole clip that many times back to back (2 =
original + 1 repeat). `--duration` instead loops (and trims the last
repeat) to hit an exact target length. For a background loop, an ambient
bed, or filling a fixed slot length with a short clip. Does not smooth the
loop point (no crossfade at the seam) -- a clip that doesn't already loop
cleanly will show a visible cut/pop at each repeat, which is a property of
the source material this tool cannot fix.

### broll.py — cut away to a B-roll clip and come back
```
broll.py A.mp4 --insert B.mp4 --at T [--duration D | --end T2] [--from T3]
               [--insert ... --at ...] [--audio a|b|mix] [--pad-color black] [-o OUT]
```
A plays as it is; during each window B's picture is shown instead (scaled and
padded to A's frame, A's fps), and A resumes at its own time when the window
ends -- a cutaway, not a splice, so the output is exactly as long as A. One
`--insert`/`--at` pair per cutaway (`--duration`, `--end`, `--from` are per
cutaway too, or given once for all; defaults 4 s and 0); windows may not
overlap or run past A's end, and B must have enough material from `--from`.
`--audio a` (default) keeps A's audio untouched and stream-copied; `b` replaces
it inside each window with B's; `mix` plays both. The output's length is
verified against A's.
A subtitle/data track in the source is not carried into the retimed/concatenated
output; the result says so with `dropped_non_av_streams: true`.

### metadata.py — chapter markers and container tags, streams copied
```
metadata.py INPUT [--chapters chapters.txt | --clear-chapters | --auto-chapters]
                  [--min-chapter S] [--max-chapters N] [--from silence|scenes|both]
                  [--silence-threshold dB] [--silence-min S] [--scene-threshold N]
                  [--chapters-out FILE] [--description-out FILE]
                  [--title T] [--artist A] [--album A] [--comment C] [--date D] [--genre G] [-o OUT]
```
`chapters.txt` holds one chapter per line, `TIME TITLE` (cut.py's time syntax:
seconds, mm:ss, hh:mm:ss.ms); each chapter ends where the next starts and the
last runs to the end of the file. Starts must ascend and lie inside the file.
Every stream is `-c copy` (bit for bit; `probe` reports the result under
`chapters` and `tags`), so this is instant and lossless. Chapter markers need a
container that can hold them (.mp4/.m4v/.m4a/.mov, .mkv/.mka/.webm); `.wav`,
`.gif`, `.mp3` and `.flac` outputs are refused for `--chapters` rather than
silently dropping them. Tags alone are written to any container that has them.
`--clear-chapters` removes existing markers; an empty tag value (`--comment ""`)
clears that tag.

**Proposed chapters (1.16).** `--auto-chapters` measures the file's own
structure instead of reading a file: silencedetect for the pauses (`--from
silence`), scdet for the scene cuts (`--from scenes`), both by default. A
chapter starts where speech resumes; a scene cut within 1 s of one is the same
event and merges to `silence+scene` evidence, which `--max-chapters` never
drops before a single-evidence marker. `--min-chapter` (default 60, a
long-form default) is the shortest chapter, and nothing is proposed within it
of the end of the file. **Two detectors mean two full decodes of the input**
(`notes` says so); `--from silence` is the cheap path. Every title is
`Chapter N` and the result says `"titles": "placeholder"`: the skill proposes
where a chapter starts, it cannot know what is in one -- naming them is the
caller's job, and asking this skill to do it is a refusal.
`--chapters-out FILE` writes the proposal in this tool's own `--chapters`
format, so the titles can be edited and fed straight back;
`--description-out FILE` writes the YouTube block (`00:00 Chapter 1` per
line, rounded down to the second). The output is still `-c copy`. An input
with no video degrades to `--from silence` with a note; an explicit `--from
scenes` on it is refused, as is `--from silence` on an input with no audio.
The result gains `auto_chapters` (source, min_chapter, proposed, kept,
titles, chapters with their evidence, description_block, files).

### grid.py — composite clips into a grid
```
grid.py CLIP1 CLIP2 [...] --cols N --rows N [--cell-width W] [--cell-height H]
                          [--label auto|none] [--font NAME] [--audio-from I]
                          [--pad] [-o OUT]
```
Letterboxes every clip into a common `--cell-width`x`--cell-height` cell (no
stretching) and tiles them `--cols`x`--rows`, filled left-to-right,
top-to-bottom -- the input count must equal cols*rows exactly. `--label auto`
(default) burns each clip's filename (extension stripped) into its cell's
bottom-right corner; `--label none` skips it. No audio unless `--audio-from`
picks one input's track by index -- mixing every clip's audio together is
rarely useful for a comparison grid, so this tool never does that silently.
Runs only as long as the shortest clip by default; `--pad` instead holds
each shorter clip's last frame (with silence) out to the longest.

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
Normalises every clip to one frame size, fps, `yuv420p`, 48 kHz and one
channel layout (the widest clip's -- a 5.1 clip keeps 5.1 -- or `--channels`;
silent track generated for clips without audio), then chains `xfade` +
`acrossfade`. Output length = sum of clips − transition × (n−1). Clips must be
longer than 2 × the transition. Use `--transition none` for a plain cut.
A subtitle/data track in the source is not carried into the retimed/concatenated
output; the result says so with `dropped_non_av_streams: true`.

### render.py — the whole edit in one project.json
```
render.py --init project.json                # starter file
render.py project.json [--fast] [--dry-run] [--stop-after STAGE] [--work DIR --keep]
render.py plan.json                          # execute a plan written by <tool> --plan plan.json
```
A plan is a single tool's dry run as an artifact: `cut.py in.mp4 --start 2 --end 8
--plan cut.json` writes `{plan_version, tool, argv, inputs (path, size, sha256 of
head+tail), commands, output, verify}` and runs nothing. `render.py cut.json`
re-fingerprints the inputs (refusing, `kind: input`, if any changed since the
plan), runs the tool with the planned argv, then the verify steps (probe; `check`
for a `--platform` or a platform export preset), and reports `plan`, `tool`,
`tool_result` and `check`. Show the plan to the user, get the yes, execute:
one round trip instead of re-deriving the command.
`"export": {"preset": "reels", "normalize": true}` forwards `export.py --normalize`
so the rendered file meets the platform's loudness without a separate pass. Since
1.9.0 it is on by default when the preset is a platform (`youtube|youtube4k|reels|x`)
and the project has no `loudness` stage; `"normalize": false` opts out.

`"audio": {"stems": {"dialogue": -2, "music": -18, "effects": -24}}` names one
level per element of the mix: `dialogue` is the main track's gain, `music` the
bed's level, `effects` the level of the third file `"audio": {"effects":
"sfx.wav"}` adds (never ducked). Each maps to the flag of the same meaning
(`--gain`, `--music-volume`, `--effects-volume`); an explicit flag next to a
stem wins, and a stems level with no file to apply it to (`effects` without
`"effects"`, `music` without `"music"`) is refused, `kind: input`.
`"audio": {"voice": "light"|"medium"|"strong"}` picks the voice strength
(`true` is `medium`).

`"chapters"` is a chapters file path, or an inline list of `{"at": TIME,
"title": STR}`; it runs `metadata.py` on the delivered file as the last stage
before `check`, so the markers are in the file that ships (streams copied). The
entries and the file path are validated before the first stage runs, and the
stage plans its `metadata.py` command under `--dry-run`/`--plan` like every
other stage, so the plan lists `chapters` and the run does the same work.

Stages: clips (cut, optional speed) → join (transition) → silence → fit →
captions → graphics → overlays → audio → loudness → export → chapters → check. Keys mirror the
CLI flags of each script (see the docstring); a key `render.py` does not read -- at
the top level or in any stage/clip object -- is refused (`kind: input`) naming the
key and the nearest valid one, never silently ignored. Use it whenever an edit has
more than two steps or the user is likely to ask for changes: edit the JSON,
re-render, and the result is reproducible. `--dry-run --json` prints the
complete command plan for review.

### Delivery templates — one command per destination (1.14)
```
render.py --template tiktok INPUT [--cues cues.txt | --srt subs.srt] [--logo logo.png] [--title "..."]
          [--brand brand.json] [--chapters chapters.txt] [--image cover.png] [--fit crop|pad|blur] [-o OUT]
render.py --template all INPUT ...        # or a comma list: one delivery per destination + <stem>_pack.md
render.py --list-templates                # the table below, from the running install
render.py --template tiktok INPUT --write-project project.json    # fill it, edit it, render it later
```
A template is a `render.py` project shipped in `templates/<name>.json` with `$INPUT`, `$OUTPUT`,
`$CUES`/`$SRT`, `$LOGO`, `$TITLE`, `$BRAND`, `$CHAPTERS` and `$IMAGE` placeholders. Filling it substitutes
what the run was given and **drops any block whose placeholder has no value** — no `--logo` means
no overlay stage at all, not an overlay of nothing. The filled project then renders through the
normal stages, so `--dry-run --json`, `--stop-after` and the work directory behave as always. An
unknown name is refused (`kind: input`) with the list. Output defaults to
`<input>_<template>.mp4` **next to the input** (`.m4a` for an audio-only destination such as
`podcast`) — the same rule for one template and for a pack, whose `-o` names the directory.
Alias spellings are accepted everywhere one name is: `youtube-shorts`/`yt-shorts` = `shorts`,
`yt` = `youtube`, `instagram`/`ig` = `reels`, `twitter` = `x`, `fb` = `facebook`
(`check.py --platform`, `export.py --preset`, `caption.py`/`graphics.py`/`overlay.py
--platform`, `look.py --safe`, `render.py --template`).

Under `--dry-run` a pack prints every child's planned commands and its table reads `planned`
with no size or duration: nothing was encoded, so nothing is reported as verified. `--chapters`
reaches a pack's audio destination like it does the single-template form.

Each template's frame, duration limit, loudness target and safe zones come from the one delivery
table (`scripts/_platforms.py`). Safe zones are the fraction of the frame the app's own UI covers;
the template places captions, graphics **and the `--logo` overlay** clear of them, and
`caption.py --platform`, `graphics.py --platform` and `overlay.py --platform` apply them to a
hand-built step:

| template | frame | max duration | loudness | safe top | safe bottom | safe left | safe right |
|---|---|---|---|---|---|---|---|
| `tiktok` | 1080x1920 (9:16) | 600 s | -14 LUFS / -1 dBTP | 0.10 | 0.22 | 0.05 | 0.14 |
| `reels` | 1080x1920 (9:16) | 90 s | -14 LUFS / -1 dBTP | 0.08 | 0.20 | 0.05 | 0.12 |
| `shorts` | 1080x1920 (9:16) | 180 s | -14 LUFS / -1 dBTP | 0.06 | 0.18 | 0.05 | 0.12 |
| `youtube-shorts` | 1080x1920 (9:16) | 180 s | -14 LUFS / -1 dBTP | 0.06 | 0.18 | 0.05 | 0.12 |
| `youtube` | 1920x1080 (16:9) | 43200 s | -14 LUFS / -1 dBTP | 0.05 | 0.05 | 0.05 | 0.05 |
| `x` | 1280x720 (16:9) | 140 s | -14 LUFS / -1 dBTP | 0.05 | 0.05 | 0.05 | 0.05 |
| `linkedin` | 1080x1080 (1:1) | 600 s | -14 LUFS / -1 dBTP | 0.05 | 0.05 | 0.05 | 0.05 |
| `facebook` | 1920x1080 (16:9) | 14400 s | -14 LUFS / -1 dBTP | 0.05 | 0.05 | 0.05 | 0.05 |
| `podcast` | audio only | — | -16 LUFS / -1 dBTP | 0.00 | 0.00 | 0.00 | 0.00 |
| `audiogram` | 1920x1080 (16:9), or `--platform` / `--image` | 43200 s | -14 LUFS / -1 dBTP | 0.05 | 0.05 | 0.05 | 0.05 |

`podcast` is audio: silence trim, −16 LUFS / −1 dBTP, chapter markers when `--chapters` is given,
and `check.py --platform podcast`. `--template all` renders `tiktok, reels, shorts, youtube, x,
linkedin, facebook` (not the audio template, not the `youtube-shorts` alias) into
`<stem>_<platform>.mp4`, runs each platform's check and writes `<stem>_pack.md` with one row per
destination; `report.py --pack <stem>_pack.md` renders that table as a single HTML page. A pack
whose destinations did not all pass exits non-zero with the per-destination rows in `pack`.

`audiogram` (1.16) is the one-call form of the podcast-to-video job: an `audiogram` stage runs
**first** (it makes the picture the rest of the chain works on, through `waveform.py --image`),
then captions, loudness, export and check. It needs `--image` (a local file) or a `background`
colour in the project — this skill fetches nothing and invents no cover art — and it is
deliberately **not** part of `--template all`, whose destinations all assume a source that
already has a picture.

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
check.py INPUT --platform youtube|shorts|reels|tiktok|x|linkedin|facebook|broadcast|podcast|custom [--no-loudness] [--json]
         [--max-duration S] [--aspect 9:16] [--lufs -14] [--tp -1] [--max-mb N]
```
PASS/WARN/FAIL per check with the script that fixes it. Run it as the final
step before reporting a deliverable; fix FAILs, mention WARNs. Without
`--platform` the youtube spec is assumed and the judgement rows (duration,
aspect, fps, resolution, loudness, true peak) come back as WARN with a `notes`
line, not FAIL: name the platform when the file is a delivery for it.
`--platform podcast` adds two informational rows: `channels` (PASS for mono or
stereo, WARN above — podcast players downmix 5.1 unpredictably) and `chapters`
(PASS when the container carries at least one marker, WARN `none` otherwise —
write them with `metadata.py --chapters`). Neither can FAIL a delivery, and
neither appears for another platform. Since 1.14 the per-platform numbers (duration, aspects,
minimum height, fps, codecs, size, LUFS, true peak, SDR-only) come from the one delivery table
in `scripts/_platforms.py`, which `export.py` and the `render.py` templates read too -- so the
loudness a preset normalises to and the loudness this tool checks are the same value by
construction, not by two lists agreeing.

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
graphics.py INPUT --template lower-third|title|chapter|progress|countdown|bug|sticker|hook|meme
            [--name] [--title] [--subtitle] [--text] [--top] [--bottom] [--duration 3]
            [--from N] [--start S] [--end E] [--position CORNER] [--margin PX] [--platform NAME]
            [--brand brand.json] [--primary RRGGBB] [--scale 1.0] [--lang XX]
            [--wrap phrase|measured] [--text-render auto|ass|drawtext] [--write-ass OUT.ass]
            [--emoji auto|color|png|mono|none] [--emoji-assets DIR] [--emoji-scale 1.0] [--emoji-max 60] [-o OUT]
```
Since 1.16 a label too wide for the frame is broken into lines by the same phrase-aware wrap
caption.py uses (`--wrap phrase|measured`; see caption.py above) instead of running off the edge —
the hook card, the meme lines and the sticker chip. A label that already fits is untouched.

Drawn with drawbox/drawtext/overlay — no PNG assets needed. Sizes scale with
the frame's short side; colours, font and safe margin come from `--brand`.
Lower-third slides in over 0.4 s and out over 0.3 s; title/chapter/bug fade.
Non-Latin `--name`/`--title`/`--subtitle` text picks a font file by script the
same way `caption.py` does (`--lang XX` disambiguates Han-only text; no font for
the script fails the job). Arabic and Hebrew are already correct through drawtext
on a build with `--enable-libfribidi` (bidi + joining). What drawtext cannot do on
any build is reorder and re-cluster — Devanagari matras, Thai/Lao mark stacking —
because it does not use harfbuzz. Since 1.15 `--text-render auto` (the default)
therefore routes those scripts through libass: the template's geometry is written
as a generated `<output>_gfx.ass` (`--write-ass PATH` names it) and burned with
`ass=`, reported as `text_renderer: "ass"` with `script` and `ass` in the JSON.
Latin/CJK/Arabic frames are pixel-identical to 1.14 (the drawtext command
line is not: since 1.15 every drawn label is passed as `textfile=<tmp>:expansion=none`
rather than `text=`, so a `--dry-run` compared against 1.14 differs by design). `--text-render ass` forces the
route; `--text-render drawtext` with a shaping script is refused by name rather
than rendering a wrong frame. See `references/gotchas.md#fonts-by-script`.
`--emoji*` works as on `caption.py` below; a template whose text is *only* emoji
and that this machine can draw none of is `kind: input`, because that frame would
be blank. `--emoji none` strips the clusters from the drawn text, and a job whose
emoji would fall to `mode: mono` is routed through libass (which has a font
fallback chain) instead of drawtext (which does not, and would draw an empty box).

Every drawn label goes to drawtext as `textfile=<path>:expansion=none`. The file
is UTF-8, mode 0600, in a private per-run temp directory created with
`tempfile.mkdtemp()`, written only when the command that names it actually runs
(so `--dry-run` and the ASS route write nothing) and removed when the process
ends. A plan printed by `--dry-run` therefore names a path that does not exist.

All three are usable from a `render.py` project too: a `graphics[]` entry takes `text`, `top`,
`bottom`, `duration`, `margin` and `platform` alongside the older keys.
1.14 adds three social templates: `sticker` (`--text`, a filled chip that pops in at
`--position`), `hook` (`--title --duration 3`, the full-width opening card with a thin progress
bar along the top that empties as the card's time runs out) and `meme` (`--top` / `--bottom`,
upper-case white with a heavy black outline). `--platform NAME` takes each edge's margin from
that destination's safe zone (see "Delivery templates" above), so a sticker stays off TikTok's
like column; `--margin PX` sets all four edges and wins over `--platform`.

### brand.json — one file for fonts, colours, logo, margins
```json
{"font": "Noto Sans CJK JP", "font_file": "fonts/NotoSansCJK-Bold.ttc",
 "colors": {"primary": "FF6A00", "text": "FFFFFF", "outline": "000000", "background": "0B1D2A"},
 "logo": "logo.png", "logo_position": "top-right", "logo_scale": 160, "logo_opacity": 0.9,
 "safe_margin": 48, "lang": "ja",
 "styles": {"caption": {"font": "Noto Sans CJK JP", "size": 28, "colour": "FFFFFF", "box": false, "position": "bottom"}},
 "caption": {"size": 28, "position": "bottom", "animate": "pop", "karaoke": true, "bold": true}}
```
`caption.py --brand`, `overlay.py --brand --logo`, `graphics.py --brand`, and
`"brand": "brand.json"` in a render project. Explicit flags still win.
`styles.caption` (1.12) is the one caption look every project shares —
`{font, size, colour, box, position}`, British or American spelling of colour —
read by `caption.py` and, for `font` and `colour`, by `graphics.py`; it wins
over the older top-level `caption` block where both set the same key, and that
block still carries the burn-in-only defaults (`animate`, `karaoke`, `bold`,
`outline`). `"lang"` is the script hint `--lang` would give. When a
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
look.py INPUT --safe tiktok [--at 3]                              # shade what the app's UI covers
```
Outputs PNG. View it with the Read tool (or any image viewer) and judge the
frame like an editor would. Use `--compare` to show before/after to the user. `--safe NAME` (1.14) shades the zones that
destination's own UI covers -- TikTok's description block and like column, the Reels/Shorts
chrome -- on the sheet or the frame, so "is the caption readable" can be answered about the app
rather than about the file.

### caption.py — subtitles (static, animated, karaoke)
```
caption.py INPUT --srt FILE[:LANG] | --ass FILE | --text CUES.txt [--write-srt OUT.srt]
           [--mode burn|mux] [--srt FILE:LANG ...] [--track-title T ...] [--default-track LANG]
           [--audio-stream N] [--fps N] [--lang XX] [--offset TIME]
           [--max-lines N] [--min-duration S] [--wrap phrase|measured]
           [--font NAME] [--fonts-dir DIR] [--size N] [--color RRGGBB] [--outline N] [--outline-color RRGGBB]
           [--bold] [--box] [--position bottom|top|center|top-left|...] [--margin N]
           [--animate none|fade|pop|slide] [--karaoke [--highlight-color RRGGBB]] [--write-ass OUT.ass]
           [--emoji auto|color|png|mono|none] [--emoji-assets DIR] [--emoji-scale 1.0] [--emoji-max 60] [-o OUT]
caption.py --text CUES.txt --write-srt OUT.srt        # generate the SRT only
```
Text cue format, one per line: `0:00-0:03 Hello`, `00:00:03.500 --> 00:00:06 Two | lines`,
or `00:00:03:15 --> 00:00:06:00 SMPTE non-drop-frame timecode` (`hh:mm:ss:ff`, frame count
converted with `--fps`, or the input video's own fps when `--input` is given and `--fps` is
not — a timecode-shaped cue with no fps available is refused rather than misread as plain text).
Lines without a time run for `--auto-seconds` (3 s) after the previous cue. `|` is a line break.
`--animate`/`--karaoke` generate a styled ASS (PlayRes = video size) from the
SRT/text cues: `pop` is the short-form "bouncy" entrance, `--karaoke` fills each
word from `--color` to `--highlight-color` across the cue; `--karaoke-timing
energy` (default) follows the speech loudness in the audio, `even` splits the
cue equally (word timing is derived, not transcribed). The ASS is kept next to the
user can hand-tune timings and re-run with `--ass`.
Emoji (1.15): `--emoji-assets DIR` is a directory of PNGs named by code point
(`1f389.png`, `1f1ef-1f1f5.png`, `1f469-200d-1f4bb.png` — the Twemoji/Noto
convention), also read from `brand.json` `styles.caption.emoji_assets` and
`FFMPEG_SKILL_EMOJI_ASSETS`. With one, the cue text keeps its place in the ASS
with an invisible placeholder reserving the emoji's box and each PNG is
composited on top (`--emoji-scale` sizes the box, `--emoji-max` caps the count).
Without one the run still succeeds and says `emoji: {"mode": "mono"}` plus a
warning; `--emoji none` strips them; `--emoji color` insists on a colour-capable
libass and refuses otherwise. Nothing is ever downloaded. What this machine can
do: `doctor --json` → `.fonts.emoji`. Details: `references/gotchas.md#emoji`.

Readable by default (1.12, rebalanced in 1.15): every cue is wrapped to the safe area (90 % of the
frame width) at the chosen `--size`, measured per script — CJK and Thai count a
full em per character, Latin per character from a table read off DejaVu Sans (so
an all-caps line measures as wide as it draws), Cyrillic/Greek about 0.55,
Arabic/Hebrew 0.6, Devanagari 0.7, and a combining mark nothing at all —
breaking between characters for CJK/Thai and at spaces otherwise, but never
between a character and the combining marks that belong to it (Thai tone marks
and vowel signs, Devanagari matras, Arabic and Hebrew points). A cue that would need more than `--max-lines` (default 2) is split
into consecutive cues sharing its time; a cue shorter than `--min-duration`
(default 1.0 s) is held longer, never past the next cue's start; `--offset
TIME` shifts every cue (seconds, `mm:ss`, `hh:mm:ss.ms` or `hh:mm:ss:ff`, a
leading `-` for earlier) for `--text`, `--srt` and `--ass`. One `cues:` info line reports what changed. A file you passed in is
never edited: the adjusted copy is written next to the output
(`<out>_adjusted.srt`, `<out>_offset.ass`) and burned instead — under `--dry-run`
/`--plan` the planned command names that same copy and the plan says where it
comes from, but nothing is written until the real run. `--min-duration` and
`--offset` also work with `--write-srt` alone; `--max-lines` does not, because
wrapping needs the input video's real frame size.

Phrase-aware breaking (1.16), `--wrap phrase` (default) — four rules over the
break positions that already fit, so a line is never widened and the line count
never changes: **R1** never inside a word, and a hyphenated token may break only
after its hyphen (never after a non-breaking `‑`, nor a leading/trailing
one); **R2** no line that is a lone digit, one or two punctuation characters, or
a single kana, checked at every boundary rather than only the last; **R3** for
Japanese and Chinese, a break is preferred after `。、！？」』）` and (Japanese
only) after a particle — a particle attaches to the word before it, so kinsoku
forbids opening a line with one — discouraged between a kanji stem and its
okurigana, and forbidden before a small kana, `ー` or a closing bracket; **R4**
for en/es/pt/fr/de/it, an article or preposition is kept with the phrase it
governs: the break before it is preferred and the break after it penalised (a
frozen table, matched case-folded; `--lang`, else the script detector, picks the
set, and with no language the union of the six is used). `--wrap measured` is 1.15's
width-only wrap exactly, kept so an older split can be reproduced. The result's
`caption` object carries the layout counts plus `wrap` and `phrase_breaks`.
graphics.py takes the same flag for the labels that can hold more than one line
(the hook card, the meme lines, the sticker chip). The breaker never rewrites,
shortens or translates the text: a cue that cannot fit `--max-lines` is split
into consecutive cues, as it always was.

Several languages in one file (1.16): `--srt` is repeatable and each file may
carry a `:lang` suffix — `--mode mux --srt en.srt:en --srt ja.srt:ja --srt
es.srt:es -o ep.mkv` writes one deliverable with three language-tagged,
toggleable streams and copies the video and audio bit for bit. The suffix splits
on the last colon, and only when the tail is a BCP-47-shaped code *and* the whole
token is not itself a file on disk, so `C:\subs\en.srt` and a file named
`a:b.srt` are never mangled; a single `--srt` with no suffix still takes
`--language`. `--track-title` names a track (repeated in `--srt` order;
otherwise a frozen display-name table, and a code the table does not know gets
the code itself — never a guessed or translated name), `--default-track LANG`
marks one for auto-selection. Every other new track is explicitly marked *not*
default, because ffmpeg otherwise flags the first one itself -- so with no
`--default-track` a Matroska file really does leave every track off. Two tracks with the same code, a
code that is not BCP-47-shaped, a `--default-track` no track carries, and more
than one `--srt` with `--mode burn` are all refused. **Container note:** `.mp4`
and `.mov` accept several `mov_text` tracks but many players show only the
first, and MPEG-4 stores an ISO-639-2 code — a two-letter one is silently
dropped, so this tool converts it (`en` → `eng`); Matroska keeps the code you
give. Past two tracks in an MPEG-4 container the result carries a note
recommending `.mkv`. Two further MPEG-4 limits are reported rather than papered
over: it has no per-track title the muxer writes back (so `tracks[].title` is
`null` there, with a note) and it always enables its first subtitle track
whatever disposition is asked for (so that track is reported `default: true`,
again with a note). `.mkv` has neither limit. The result gains `tracks` and `subtitle_tracks`; check.py
prints an informational `subtitles` row (WARN for an untagged stream, never
counted in `failed`). The skill never translates and never generates a second
language.

Fonts by script (1.12): with no `--font` and no font named in your brand file, the
script of the cue text (Japanese, Chinese, Korean, Arabic, Hebrew, Devanagari,
Thai, Cyrillic, Greek) picks a font file that covers it, logged as `font: <file>
(covers ko)`. Han-only text is read as Chinese unless `--lang ja|ko` (or
brand.json `"lang"`) says otherwise; `--language` is the same flag, and still
tags the subtitle stream under `--mode mux` and sets `--transcribe`'s language.
No font for the script fails the job (`kind: input`) instead of rendering boxes
— but only when fontconfig answered: with no working `fc-list` the coverage is
`unknown`, and the job runs with the font as given behind one info line. An
explicit font is always kept, with an info line when it does not cover the text;
`--fonts-dir` is searched first and checked with `fc-scan`, and a directory that
does not cover the script gets one line and a font resolved by script anyway. `doctor --json` `fonts.scripts` lists what this machine can render. See
`references/gotchas.md#fonts-by-script` (RTL: use captions, not drawtext).

`--karaoke` uses real per-word timings when the transcript has them (a whisper
`<stem>.json` or `<stem>.words.json` next to the SRT, `{"segments": [{"words":
[{"word", "start", "end"}]}]}`); otherwise `--karaoke-timing` decides.

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
                  [--emoji auto|mono|none] [--emoji-assets DIR]
                  | --video CLIP [--chromakey COLOR [--chromakey-similarity 0-1] [--chromakey-blend 0-1]]
           [--position top-right|bottom-left|center|X,Y] [--margin N] [--platform NAME] [--start T] [--end T] [--fade S] [--opacity 0-1] [-o OUT]
```
`--platform NAME` (1.14) takes each edge's margin from that destination's safe zone
(`scripts/_platforms.py`), so a template's top-left logo clears TikTok's status bar instead of
sitting 24 px into it; an explicit `--margin` (or a brand `safe_margin`) wins.
Alpha in PNGs is respected. Fades apply to the overlay only; the video keeps
playing. `--video` composites a second video as a picture-in-picture layer
(same position/scale/opacity/time-range knobs as `--image`); only the main
input's audio is kept, the PiP layer's own audio is dropped. `--chromakey`
(with `--video`) keys out that colour first for green-screen compositing.

`--fade S` fades the overlay in at `--start` (or 0); the fade-out happens
only at `--end`, so a logo with no `--end` stays to the last frame.

Since 1.15 the drawn text goes to drawtext in a **file** (`textfile=`,
`expansion=none`), so `'` and `%` survive verbatim — `--text "it's 100% done"`
used to lose both. `overlay.py` still draws through drawtext, which cannot shape
Devanagari/Thai-class scripts and cannot load a colour emoji font: a shaping
script is refused by name pointing at `caption.py`/`graphics.py`, and
`--emoji png|color` is refused the same way (`--emoji mono`, the default here,
draws whatever glyph the text font has; `--emoji none` strips them).

### sync.py — offset detection, alignment, drift correction
```
sync.py REFERENCE SECOND [--json] [--max-offset 30] [--analyze-seconds 120] [--fix-drift [--drift-window 60]]
        [--replace-audio | --trim-second] [-o OUT]
```
Cross-correlates loudness envelopes: coarse FFT search (20 ms), then a direct
1 ms refinement (pure Python, a 2-minute window takes ~1-3 s). Positive offset
= the second recording started later. `--replace-audio` writes the reference
video with the second file's audio aligned (video stream copied); the output
keeps the reference's full length -- a shorter or head-trimmed second file is
padded with silence, never allowed to cut the picture.
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
audio.py INPUT [--voice [light|medium|strong] | --denoise [--denoise-strength 25]] [--gain dB]
         [--music FILE [--music-volume -14] [--duck [--duck-amount 12] [--duck-threshold -26.02]
          [--duck-attack 20] [--duck-release 400]] [--music-loop]]
         [--effects FILE [--effects-volume -14]] [--stereo-widen 0..1]
         [--fade-in S] [--fade-out S] [--stereo | --mono | --downmix] [--replace FILE] [-o OUT]
```
`--voice` takes a strength; a bare `--voice` is `medium`, the chain it has always
produced. The exact filter chains:

| level | chain |
| --- | --- |
| `light` | `highpass=f=80,acompressor=threshold=-18dB:ratio=2:attack=5:release=80:makeup=1` |
| `medium` | `highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2` |
| `strong` | the `medium` chain, then `deesser=i=0.6,acompressor=threshold=-24dB:ratio=4:attack=5:release=120:makeup=3,alimiter=limit=0.891251:level=disabled` |

`light` for a good room (rumble and level only, noise floor and sibilance left
alone), `medium` for a normal talking head, `strong` for phone/laptop audio.
`strong` is the only level with a limiter, so it is the only one whose peaks
stop at −1 dBFS: `medium` (the default, and the chain a bare `--voice` gets) can
clip a hot source, since its make-up gain has nothing above it — normalise
afterwards with `loudness.py`, or use `strong`, which measures quieter and safer.
`--duck` uses a sidechain compressor keyed by the speech so music dips under
dialogue and swells in pauses:
`sidechaincompress=threshold=0.05:ratio=<amount/3, min 2>:attack=20:release=400:makeup=1`
by default. `--duck-threshold DB` (default −26.02 dBFS, i.e. the 0.05 linear),
`--duck-attack MS` (20) and `--duck-release MS` (400) move each one; a lower
threshold ducks on quieter speech, a shorter release brings the bed back faster.
`--json`'s `audio` block reports the settings the run actually used.
`--effects FILE` mixes a third track (sound effects, atmos) at
`--effects-volume` and is never ducked — effects are cut to the picture.
`--stereo-widen 0..1` widens the stereo image (`extrastereo=m=1+2*amount`) and
needs a real stereo source: it scales the side signal (L−R), so a mono track
duplicated to two channels has nothing to scale. A 1-channel input is refused
(`kind: input`) — `--stereo` duplicates it but does not widen it — and more than
two channels are refused unless `--downmix` is given too, in which case the
widening runs on the stereo fold-down. `--downmix` uses the
ITU centre/LFE weights for 5.1/7.1 → stereo. `--mono` averages a stereo pair,
leaves a 1-channel input untouched and downmixes >2 channels through
swresample. Video is always stream-copied, and so is a subtitle/data track
when the container can hold it (`dropped_non_av_streams` says when it could not).
Run `loudness.py` after this for final levels.

### loudness.py — EBU R128 normalisation
```
loudness.py INPUT [-I -14] [--tp -1] [--lra 11] [--measure-only] [-o OUT]
```
`--lra N` is the loudness-range target in LU (default 11): lower it to squeeze a
wide-dynamic mix into a phone speaker, raise it to leave a film mix alone.
`--json` reports the measured range on both sides — `measured.input_lra` for the
input, `result.input_lra` for the written file, with `targets` echoing the
requested lufs / tp / lra.

Two-pass `loudnorm`: measure, then apply with measured values (linear mode when
the true-peak ceiling allows). Video and any subtitle/data track are
stream-copied (`dropped_non_av_streams` reports a track the container refused); audio becomes AAC in
video containers or the codec matching the extension (.wav → PCM, .flac, .mp3).
The written file is measured again: a lossy encoder can push peaks past the
ceiling loudnorm held (ffmpeg's AAC at 192k turned one transient from -2.4 to
+3.7 dBFS). When it does, the tool re-encodes -- first at 256k then 320k if you
did not pass `--audio-bitrate`, then with the loudnorm ceiling lowered by the
overshoot -- until the file itself meets `--tp`. `result` reports
`tp_ceiling_used`, `audio_bitrate_used`, `encodes`, and a `note` when the
integrated loudness ended more than 1 LU from the target because of it.

### export.py — delivery presets
```
export.py INPUT --preset youtube|youtube4k|reels|tiktok|shorts|linkedin|facebook|x|youtube-hdr|youtube-av1|prores|h265|gif|copy
                [--fit pad|crop] [--no-scale] [--allow-long] [--crf N] [--normalize] [-o OUT]
export.py --list
```
Scales into the preset frame (pad by default), tags BT.709, sets `+faststart`,
trims to platform maximums (Reels 90 s, X 140 s) unless `--allow-long`. It
does not touch levels: for youtube / youtube4k / reels / x the written file is
measured and the result's `loudness` (and a `notes` line) says when it is
outside the platform's LUFS / true-peak spec, naming the `loudness.py` call
that fixes it -- or pass `--normalize`, which runs that call on the written
file itself (audio re-encoded, video copied; `loudness.normalized: true`) so a
platform export is one command instead of export, loudness, export again.

Since 1.14 each social destination is its own preset rather than an alias: `tiktok`
(1080x1920, max 600 s), `shorts` (1080x1920, max 180 s), `reels` (1080x1920, max 90 s),
`linkedin` (1080x1080), `facebook` (1920x1080), each with its platform's loudness spec from the
same table `check.py` reads, so `--normalize` and the check agree. `youtube-hdr` writes HEVC
Main10 keeping the source's own HDR10/HLG tags and refuses an SDR source (`kind: input`, hinting
at `--preset youtube`) rather than labelling SDR as HDR; `youtube-av1` encodes AV1 with
SVT-AV1 (libaom fallback) and refuses with `kind: missing_tool` on an ffmpeg built with
neither.

### proxy.py — low-bitrate proxy for analysis/preview
```
proxy.py INPUT [--width W | --scale F] [--crf N] [--fps N] [--no-audio] [-o OUT]
```
Not a delivery preset: resizes to `--width` (default 640) or by `--scale`
factor, re-encodes at a proxy-grade `--crf` (default 30) with the fastest
x264/x265 preset, keeps the source's own dynamic range (HDR stays HDR;
run `color.py --to-sdr` first if SDR is wanted) and keeps a subtitle/data
track when the container can hold it (`dropped_non_av_streams`). Only executes the spec
given — does not decide which asset to proxy or what for.

