# Gotchas and things that look right but are wrong

The long form of SKILL.md's "Things that look right but are wrong" and "Gotchas"
bullets. SKILL.md keeps one line per item and points here with the anchors below;
nothing here is optional reading when the job touches that area — it is the
detail, not an aside.

## Colour, HDR and Log

### HDR and colour
SDR outputs are H.264 tagged BT.709 `yuv420p`. When `probe.py` reports
`hdr: true` (HDR10/PQ, HLG, Dolby Vision, BT.2020), every editing script keeps
the output HDR (HEVC Main10, source colour tags) so nothing is silently
flattened. Decide with the user: keep HDR (fine for YouTube/phones) or run
`color.py --to-sdr` first for SDR-only destinations, LUT work or H.264
deliverables. `hdr: true` counts BT.2020 primaries too, so it is also true for a
wide-gamut SDR file; `hdr_signal: true` is the narrower fact — a real PQ / HLG /
Dolby Vision transfer — and `hdr_format` names the in-between case
(`BT.2020 SDR`). `export.py` platform presets are SDR and warn on HDR input.
iPhone `.mov` files also carry timecode/metadata tracks; scripts map only the
first audio track, so extra tracks are dropped on re-encode. Keep ProRes masters
at source colour: `export.py --preset prores` does not retag.

Re-encoding an HDR (iPhone, HDR10) source through an SDR path flattens the
colours. The scripts keep HDR; if you hand-write ffmpeg (never do — see SKILL.md),
do not tag BT.709 on BT.2020 pixels.

### Log footage
S-Log, V-Log and C-Log look grey and low-contrast but are tagged SDR. Run
`probe.py --analyze`; `looks_like_log: true` means apply the manufacturer's
`.cube` with `color.py --lut` before anything else.

## Cutting

### Keyframe cuts
A lossless `cut.py` result may start up to one GOP (often 1–10 s) earlier than
requested; the script re-encodes automatically when the deviation exceeds 0.5 s.
If the user insists on lossless output, pass `--tolerance -1` and tell them the
cut lands on the nearest earlier keyframe. A `-c copy` cut on VFR or a
non-keyframe boundary produces a file that "works" but starts on a frozen or
wrong frame — respect the automatic re-encode rather than forcing the copy.

### Variable frame rate
`probe.py` sets `variable_frame_rate_suspected` when `r_frame_rate` and
`avg_frame_rate` disagree (phone and screen recordings). Every re-encoding
script then adds `-fps_mode cfr` at the source's average rate, and `cut.py`
switches itself to `--accurate` (copy-cuts on VFR are unreliable). Pick the rate
explicitly with `fit.py --fps 30|60` when the average is odd (e.g. 23.4 fps from
dropped frames).

## Audio

### Sync, multicam and drift
A sync or multicam alignment with `confidence` under 0.3, or an offset larger
than 60 % of the analysis window, is probably wrong: enlarge `--analyze-seconds`
or find a clap. `multicam.py` reports one `confidence` per camera — check all of
them, not just that the command succeeded, before trusting the cut.

`sync.py`/`multicam.py` align audio tracks to each other, never lip sync (mouth
movement vs. audio) — there is no face or mouth detection anywhere in this skill.
High confidence means the audio matched well, not that the picture looks right;
whether lip sync is correct needs a look at the video, not the reported offset.

Don't mix files with different frame rates or sample rates in one
`cut.py --segments` join without re-encoding (`--accurate`). After `sync.py`,
verify by running it again on the output: offset (and drift ppm with
`--fix-drift`) should be ~0. Recordings longer than ~10 minutes from separate
devices: always use `--fix-drift`.

### Loudness and ambience
"Normalised" audio can still clip: check true peak, not just LUFS (`check.py`
does both). And do not normalise ambience or near-silence to a speech target — a
clip measured at -40 LUFS or below is room tone, wind or nothing; raising it
25 dB raises the noise, not the content. Leave the level, say so, and offer music
or narration.

## Text and framing

### Captions, fonts and text order
Captions burned before a crop/resize land off-frame: frame changes first, then
text. Captions burned at an intermediate size and then upscaled by `export.py`
come out soft (a 1280x720 source fit to 9:16 is 406x720 until export scales it to
1080x1920) — fit to the delivery size first
(`fit.py --width 1080 --height 1920`), then caption, then export.

CJK and other non-Latin text: libass and drawtext need a font that has the
glyphs. Check with `fc-list | grep -i cjk`. Then either name it
(`caption.py --font "Noto Sans CJK JP"`) or point at the file
(`overlay.py --font-file /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`,
`caption.py --fonts-dir ./fonts --font "Noto Sans CJK JP"`). Without a matching
font you get boxes, not an error. Install: `apt install fonts-noto-cjk`,
`brew install --cask font-noto-sans-cjk`.

Windows drawtext crashes on some real builds (#100): the drawtext tools resolve a
concrete `--font-file` by default, which avoids it; if one still crashes, pass
`--font-file` explicitly. Details: `references/ci-platform-pitfalls.md`.

### Reframing, fps and duration
`--fit crop` to reach 9:16 from 16:9 throws away 70 % of the width: a wide shot
loses people at the edges. Check the sheet; pad (bars), `--crop-x`/`--crop-y`
toward the subject, or a reframe is often the honest answer — a silent centre
crop is a guess, not a decision.

Conforming 60 fps to 30 halves the motion samples: fine for a talking head,
visibly choppy for sports, gaming, drone pans. Keep 60 when the platform allows.

"Make it 60 seconds" on a 3-minute talk by speed change is unwatchable (3×); by
trim it drops two thirds of the words. Ask which, or propose a highlight cut with
`scenes.py`.

### Dimensions and rotation
`yuv420p` needs even width/height; `fit.py` and `export.py` round to even values
automatically. Phone footage often carries a `rotation` tag; `probe.py` reports
it and `fit.py` accounts for it when computing the output frame.

## Planning

### Highlights
`scenes.py --highlights` defaults to the loudest scenes (`--rank-by audio`): a
quiet but important moment (a confession, a punchline landing in silence) is
skipped, and pure crowd noise or a mic bump can outrank it. `--rank-by duration`
picks the longest unbroken scenes instead. Neither is "the best parts" — check
the contact sheet (`--sheet`) before treating the picks as final.

### Chaining and speed
Anything chained by hand through three re-encodes should be one `render.py`
project instead, so the plan is one file and the user can change one number.
Re-encodes use x264 `medium`; for long files add `--preset veryfast` to
intermediates and keep the default for the final export.

## Audio-only files

Audio files are a first-class input, not a special case. `probe.py`, `cut.py`,
`silence.py`, `loudness.py`, `audio.py`, `sync.py` and `check.py --platform
podcast` all accept WAV, FLAC, MP3, M4A/AAC, OGG and Opus (any container ffmpeg
can read) and write the codec that fits the output extension, so the same
commands work with `talk.wav` in place of `talk.mp4`. What changes:

- The output extension picks the format: `-o out.mp3` converts, `-o out.wav`
  keeps PCM, `-o out.m4a` writes AAC. `audio.py in.wav -o out.mp3` with no
  other flag is a plain conversion.
- `cut.py` stream-copies audio too, so trims land on a packet boundary
  (`precision: packet`, a few ms; the JSON reports `duration_error_ms`). Pass
  `--accurate` for a sample-exact trim: `precision: sample` when the output is
  PCM or FLAC, `codec_frame` when a lossy codec (AAC, MP3, Opus) frames it
  again. A `.wav` output is always PCM, never AAC packets inside a WAV.
- `join.py` joins audio-only clips as audio (`acrossfade` or a butt join) at
  one sample rate and channel layout; the output must have an audio extension.
  Video and audio clips cannot be mixed in one join.
- An audio extension on a video input (`audio.py talk.mp4 -o talk.wav`,
  `cut.py talk.mp4 --start 1:00 --end 2:00 -o part.wav`) extracts the audio; the
  output has no video stream. `audio.py --audio-stream N` picks a track when
  `probe` lists several under `audio_streams`.
- `Look: not needed` in the report; `Check:` still applies for loudness
  (`check.py file.wav --platform podcast` measures LUFS and true peak).
- Scripts that need a picture (`fit`, `caption`, `overlay`, `graphics`,
  `color`, `export`, `scenes`, `look`) refuse an audio file with
  "input has no video stream". Say so instead of forcing a video wrapper.

### Audio-only recipes

| User says (audio file) | Do |
|-----------|----|
| "normalise this WAV to -14 LUFS", "podcast levels" | `loudness.py talk.wav -I -14 --tp -1 -o talk_norm.wav` (`-I -16 --tp -1.5` podcast) |
| "remove the silence from this recording" | `silence.py talk.wav -o talk_tight.wav` |
| "clean up the noise in this M4A" | `audio.py talk.m4a --voice -o talk_clean.m4a` (speech) or `--denoise` |
| "convert this WAV to MP3" | `audio.py talk.wav -o talk.mp3` |
| "trim this audio from 00:30 to 02:00" | `cut.py talk.wav --start 0:30 --end 2:00 -o talk_cut.wav` (`--accurate` for sample-exact) |
| "join these recordings", "intro + episode + outro" | `join.py intro.wav episode.m4a outro.wav -o full.flac` (`--transition none` for a butt join) |
| "extract the audio from the video" | `audio.py talk.mp4 -o talk.wav` (`--voice -o talk.m4a` to clean it on the way) |
| "compress / limit / gate the voice" | `audio.py talk.wav --compress --comp-threshold -20 --comp-ratio 4 --limit --limit-ceiling -1 -o talk_dyn.wav` |
| "is this loud enough for Apple Podcasts?" | `check.py talk.m4a --platform podcast` |
