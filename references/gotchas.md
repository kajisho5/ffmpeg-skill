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

Do not add a speech gate in front of the measurement either: `loudnorm`'s EBU
R128 integrated loudness already applies the −70 LUFS absolute and −10 LU
relative gates, which drop the same quiet blocks a `silencedetect` pass would.
A speech-span gate was measured against the whole-file measurement on every
fixture in the repo, including one that is half digital silence, and moved the
result by at most 0.6 LU — inside `check.py`'s own ±1 LU tolerance — for the
cost of a second full decode. That is why `loudness.py` has no speech-gate flag.

## Text and framing

### Captions, fonts and text order
Captions burned before a crop/resize land off-frame: frame changes first, then
text. Captions burned at an intermediate size and then upscaled by `export.py`
come out soft (a 1280x720 source fit to 9:16 is 406x720 until export scales it to
1080x1920) — fit to the delivery size first
(`fit.py --width 1080 --height 1920`), then caption, then export.

Cue length and timing are handled for you since 1.12: `caption.py` wraps every
cue to the safe area by measured width at the chosen `--size`, splits a cue past
`--max-lines` (default 2) into consecutive cues, holds a cue shorter than
`--min-duration` (default 1.0 s) — never past the next cue — and shifts
everything by `--offset SECONDS`. It reports what it changed on one `cues:` line
and writes the adjusted copy next to the output, never over the file you passed
in. Wrapping needs the input video (the line width comes from its real frame
size); with `--write-srt` alone only the timing flags apply.

Windows drawtext crashes on some real builds (#100): the drawtext tools resolve a
concrete `--font-file` by default, which avoids it; if one still crashes, pass
`--font-file` explicitly. Details: `references/ci-platform-pitfalls.md`.

### Fonts by script
libass and drawtext draw an empty box per character they have no glyph for, and
ffmpeg still exits 0 — a video full of tofu is the classic "it worked" failure.
Since 1.12 `caption.py`, `graphics.py` and `overlay.py --text` detect the script
of the text they are about to draw (Japanese, Chinese, Korean, Arabic, Hebrew,
Devanagari, Bengali, Tamil, Thai, Lao, Cyrillic, Greek) and resolve a font file that covers it,
printing one line — `font: /usr/share/fonts/.../wqy-zenhei.ttc (covers ko)`.
**No font for the script is a failed job** (`kind: input`), not a warning.

- What this machine can render: `python3 scripts/_contract.py doctor --json`,
  field `fonts.scripts` (`available` / `missing` / `unknown` per language, with
  the file it would use). The plain-text `doctor` says the same in one line.
- What fontconfig has: `fc-list ":lang=ja" file family` (`ja`, `zh-cn`, `ko`,
  `ar`, `he`, `hi`, `th`, `ru`, `el`).
- Install: `apt install fonts-noto-cjk fonts-noto-core`, or
  `brew install --cask font-noto-sans-cjk font-noto-sans-arabic`, or point at a
  file with `--font-file` (`overlay.py`, `graphics.py`) / `--fonts-dir`
  (`caption.py`).
- Han characters alone (no kana, no hangul) are read as Chinese. Japanese or
  Korean hanja text with no kana needs `--lang ja` / `--lang ko`
  (`caption.py --language` is the same flag), or `"lang"` in brand.json.
- An explicit `--font`, an explicit `--font-file`, or a font your brand file
  itself names is always kept, even when fontconfig says it does not cover the script: you get one info
  line saying so, not a silent substitution. A brand file that never names a
  font is not a choice — the script still picks one.
- `--fonts-dir` (`caption.py`) adds faces to the search, it does not switch the
  check off: if nothing in the directory covers the script, one line says so and
  a covering font is resolved as usual.
- **No fontconfig is `unknown`, not `missing`.** With no `fc-list` on PATH (or
  one that fails) coverage cannot be verified: the job runs with the font as
  given behind one info line, because libass and drawtext have font backends of
  their own. Only fontconfig answering "nothing covers this" fails the job.
- **RTL:** libass shapes and reorders Arabic and Hebrew correctly, so
  `caption.py` — which renders every subtitle through libass, `subtitles=` and
  `ass=` alike — is right for them by construction. `drawtext` (`overlay.py
  --text`, `graphics.py`) depends on the build: `ffmpeg -version` showing
  `--enable-libfribidi` (and `--enable-libharfbuzz`) shapes and reorders RTL
  correctly too; a build without them draws logical order with unjoined
  letterforms. Nothing in the tools checks this, so on an unknown machine a
  caption is the safe place for Arabic/Hebrew.

**Shaping is a second problem, and it is not the same one.** A font that covers
the script still has to be *shaped*: Devanagari matras are reordered, Thai and
Lao marks re-cluster. drawtext does bidi and Arabic joining correctly on a build
compiled with fribidi (so Arabic and Hebrew are already right today), but it
never reorders or re-clusters, because it does not use harfbuzz on any build.
libass does. Since 1.15 `graphics.py` therefore renders a shaping script
(`hi bn ta te kn ml gu pa si th lo km my`) through libass automatically — one
generated `<output>_gfx.ass` next to the file, `text_renderer: "ass"` in the
JSON — and `--text-render auto|ass|drawtext` overrides it; `--text-render
drawtext` with such a script is a refusal, not a wrong frame. Latin, CJK and
Arabic output is unchanged. `overlay.py --text` has no ASS route yet and refuses
a shaping script, naming `caption.py`/`graphics.py`.

### Emoji
Colour emoji need **either** a libass that can draw colour glyphs **or** a
directory of PNGs — and on most builds only the second one exists.

- **An installed colour emoji font proves nothing.** Noto Color Emoji installs
  cleanly on Ubuntu and libass on the distro ffmpeg still renders a monochrome
  outline (`Glyph 0x1F389 not found, broken font? Trying all charmaps`). The
  only honest test is a render, which is what `doctor` runs:
  `doctor --json` → `.fonts.emoji` (`mode`: `color` / `png` / `mono` / `none`,
  plus `libass_color` from that render). `contract --json --static` is the way
  to get the contract without running it; `doctor` itself always probes.
- **drawtext cannot load an emoji font at all.** Not a degraded render: a
  CBDT/sbix face fails filter initialisation outright (`Could not set font size
  to 48 pixels: invalid library handle`, and at the font's own strike
  `Monocromatic (1bpp) fonts are not supported.`) and no file is written. That
  is why the colour route is a PNG overlay, never a drawtext font.
- **PNGs**: `--emoji-assets DIR`, a directory of files named by code point in
  the Twemoji/Noto convention — lowercase hex joined by `-`: `1f389.png`,
  `1f1ef-1f1f5.png`, `1f469-200d-1f4bb.png`. Twemoji's `assets/72x72`
  (CC-BY 4.0) and Noto Emoji's `png/128` (OFL/Apache-2.0) are the two people
  already have. **The skill never downloads anything**: a missing directory is
  `kind: input`, never a silent fetch. The same directory can come from
  `brand.json` (`styles.caption.emoji_assets`) or `FFMPEG_SKILL_EMOJI_ASSETS`.
- **Mixed lines are the normal case.** The text stays in the ASS with an
  invisible placeholder reserving exactly the emoji's box, and the PNG is
  composited on top after the `ass=` filter — libass keeps the shaping and the
  karaoke, including inside a `\kf` run (the placeholder is its own
  zero-duration segment).
- **What counts as an emoji.** A cluster only starts at an emoji *base*.
  U+200D ZWJ and U+200C ZWNJ are ordinary Indic/Persian orthography (`क्‍ष` is
  ka + virama + ZWJ + ssa) and are glue only *between* two emoji; a VS16 or a
  skin-tone modifier after a plain letter is not an emoji either. U+FE0E
  (VS15) asks for the character, so `❤︎` is text and `❤️` is an emoji.
- **Placement tolerance.** The position comes from the same averaged em table
  the wrap uses, so an emoji at the start or end of a line is exact and one in
  the middle of a Latin line drifts by the accumulated rounding of the
  characters before it — **measured at 17 px, 0.28 em, about 3 % of the line
  width** on a 24 px caption over a 1280-wide frame, always landing inside the
  reserved gap rather than on a glyph. It never leaves the safe area. An RTL
  line (Arabic, Hebrew) is laid out right-to-left, so the position is measured
  from the rendered end of the line, not the logical prefix.
- **Degraded paths are honest, not silent.** `mode: mono` means libass draws
  whatever glyph the text font has (it has a fallback chain), exits 0, and says
  so in a `warning:` line and in `notes` — so a `graphics.py` run that would
  otherwise use drawtext, which loads one font file and has **no** fallback
  chain, is routed to libass rather than reporting a monochrome glyph it would
  actually draw as an empty box; a run pinned to `--text-render drawtext`
  degrades to `none` and says so. `mode: none` strips the cluster from the drawn
  text (a missing decoration must not fail a delivery) but refuses a
  `graphics.py` template whose text is *only* emoji — that frame would be blank.
  `--emoji-max` (default 60) caps the overlay count; `--emoji-max 0` means none.
- **`--animate` moves the PNG too.** The overlay gets a matching alpha fade, so
  the emoji arrives and leaves with the line instead of popping in.
- `overlay.py --text` has no PNG route: `--emoji png|color` there names
  `caption.py`/`graphics.py` instead.

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

### Platform safe zones
Every vertical app draws its own UI over the delivery: TikTok covers roughly the
bottom 22 % (description and caption block), the right 14 % (like/comment/share
column) and the top 10 % (status bar and tabs); Reels 20/12/8 %; Shorts 18/12/6 %.
The feed destinations (YouTube, X, LinkedIn, Facebook) have no persistent overlay
and use the conventional 5 % title-safe border instead. A file can pass every
`check.py` row and still be unreadable because the caption sits under the
description.

The fractions live in one table (`scripts/_platforms.py`). `caption.py --platform
NAME`, `graphics.py --platform NAME` and `overlay.py --platform NAME` take their
margins from it, `render.py --template NAME` passes it to all three, and
`look.py --safe tiktok` shades the zones on a frame or contact sheet so you can
see what the app covers. An explicit `--margin` always wins.

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
