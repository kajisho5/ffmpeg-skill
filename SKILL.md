---
name: ffmpeg-skill
description: Edit video and audio with local FFmpeg from natural-language requests: cut, trim, join, resize/reframe (9:16, 1:1), speed change, captions and subtitles (SRT/ASS, animated, karaoke), logos and text overlays, lower-thirds and titles, silence removal, multicam and external-mic sync, loudness normalisation, HDR/Dolby Vision to SDR, LUTs, background music with ducking, platform exports (YouTube, Reels, TikTok, X), compliance checks, scene detection and highlight reels, contact sheets to inspect results, and whole-edit project files. Use this skill whenever the user mentions a video or audio file (mp4, mov, mkv, wav, m4a), footage, a clip, captions, subtitles, a reel or short, YouTube/Instagram/TikTok delivery, LUFS, sync, transcoding, ffmpeg, or asks to make something "60 seconds", "vertical", "louder", "captioned" — even when they do not say "edit". Python 3.9 standard library only, no cloud, no API keys.
---

# ffmpeg-skill

Scripts live in `scripts/` next to this file; run them with `python3 <skill-dir>/scripts/<name>.py`. Every script has `--help`, and all of them accept `--dry-run`, `--json` (structured result with a probe of the output), `--fast` (preview quality) and `--progress`. Writing tools run nothing under `--dry-run`; `probe`/`check`/`sync`/`multicam`/`scenes`/`report` may still run ffmpeg/ffprobe to measure or analyse — they just don't write their final artifact; `verify` accepts the flag but ignores it. Exact per-tool semantics: `contract --json`'s `dry_run` field (or `docs/contract.md`). Details for every flag: `references/scripts.md`. Device-specific behaviour (iPhone HDR, GoPro, DJI, screen recordings, Zoom): `references/devices.md`.

## Workflow (always follow this order)

0. **Check the environment once per session, if unfamiliar.** On a machine
   you haven't confirmed capability on this session, run `doctor --json`
   once: check `ok` and the target tool's `usable` before relying on it. If
   `usable` isn't `yes`, don't run that tool — report the missing capability
   instead of discovering it via a runtime failure (a missing `libass`,
   `zscale`, or encoder is the common case, e.g. `caption.py`). Don't re-run
   `doctor` per job — it queries `ffmpeg -filters`/`-encoders`, not free, and
   once per session/unfamiliar machine is enough. `contract --json`'s full
   tool schema is for a *planning* agent deciding which tool/params to use
   from an abstract goal — not part of this per-job workflow.
1. **Probe first.** Run `probe.py` on every input before touching it. Read the
   duration, fps, resolution, codecs, audio channels and the
   `variable_frame_rate_suspected` flag. Plan the edit from real numbers, never
   from assumptions about the file.
2. **Prefer lossless.** If the request can be satisfied without re-encoding
   (plain cuts on keyframes, remuxing, audio-only changes), do not re-encode.
   `cut.py` and `loudness.py` stream-copy video by default; only pass
   `--accurate` to `cut.py` when the user needs frame-exact cuts.
3. **Plan with `--dry-run --json`, then execute.** Every script accepts
   `--dry-run` (prints the ffmpeg commands that would run) and `--json`
   (structured result: output path, probe of the output, commands run). For
   writing tools this means nothing is written; `probe`/`check` still run
   ffprobe/loudness-measurement passes (they're read-only, so `--dry-run`
   changes nothing for `probe`, and only skips the loudness pass for
   `check`), `sync`/`multicam`/`scenes`/`report` still run ffmpeg/ffprobe to
   measure or analyse, and `verify` accepts the flag but ignores it entirely
   (its steps run regardless) — see `contract --json`'s `dry_run` field per
   tool for exact semantics. Trust `--json`, not a dry-run's human-readable
   summary line, for any number after the plan (dimensions in that line can
   be a placeholder, not a computed preview — see `docs/contract.md`). Use
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
   for the destination the user named. Each row is marked `format` or
   `judgement`. Format rows (codec, pixel format, size, true peak, colour
   tags, VFR) are safe to fix mechanically. Judgement rows change the content:
   duration (cut loses material, speed changes motion), aspect (crop loses
   edges), fps (drops motion), loudness (ambience must not be boosted). Fix
   those only when the user's request already implies the answer, otherwise
   state the choice and its cost in one line. Mention WARNs; do not chase them.
6. **Verify the output.** Run `probe.py` on each result and confirm duration,
   resolution, fps and audio match what was requested. Report those numbers to
   the user (e.g. "final.mp4: 59.98 s, 1080x1920, 30 fps, AAC stereo").
   A step is done only when the script exited 0 and the output probes as
   expected. Writing the command is not doing the job; a non-zero exit, a
   missing or empty file, or a probe that contradicts the request is a
   failure, and the report says so with the script's error message.
7. **Keep the user's originals.** Never overwrite the source file. Write new
   files next to the input or where the user asked.
8. **Look at the picture.** Whenever the picture changed (captions, overlays,
   graphics, crop/pad, resize, colour, transitions) run `look.py OUTPUT`
   (contact sheet) or `look.py OUTPUT --at T`, view the PNG. The job is not
   finished until the report's `Look:` line names that PNG; a probe alone
   cannot see a caption sitting on someone's face. Audio-only jobs (sync,
   loudness, silence, or any job whose input is an audio file) write
   `Look: not needed`; there is no picture to inspect. What to look for
   splits the same way `check.py`'s rows do in step 5:
   - **Mechanical (verify and report as this skill's own job):** the
     specified text/logo is present at the specified position, subtitles/text
     appear at the specified timestamps, resolution has even dimensions.
     Letterboxing/pillarboxing from `fit.py --fit pad` is the *correct*
     result of that mode, not a defect — never flag it.
   - **Judgement (report to the calling agent/user, don't silently pass or
     fail):** whether a subject or face is cut off, whether text sits over a
     face, whether colours look washed out, whether a transition "lands"
     well or the edit feels cinematic. These require deciding what the
     subject *is*, which belongs to the calling agent (see "What this skill
     does and does not decide") — state what you see in one line and let the
     calling agent or user judge it, don't decide it here.
   If the execution environment cannot actually view images (no vision
   capability), write `Look: PATH (pixels not inspected; agent has no image
   view)` — never claim a picture was inspected when it wasn't, and don't
   stall indefinitely waiting for a capability that isn't there.


## Before you run anything: what to ask, what to assume

Ask one short question only when the answer changes the output materially and the request does not imply it:

- **Destination** decides aspect, length limit, loudness and codec. "For Reels" answers all four. If no destination is named and the edit is a plain cut/caption, keep the source format and say so; if the user asks to "export", "post" or "deliver", ask where.
- **Duration** ("make it 60 s") without a method: speed up for ≤1.5× changes, trim otherwise, and state which you chose. Ask if the content is a talk (trimming loses words) and the change is large.
- **Captions** without a text source: use `--transcribe` if a local whisper exists, otherwise ask for the text or a timed file; never invent dialogue.
- **Fonts and brand**: if the user mentions a brand, colours or "our font", ask for or create `brand.json` once and reuse it.
- **CJK / non-Latin text**: check that a font exists before rendering (`fc-list :lang=ja file` / `:lang=ko` / `:lang=zh`); pass it with `--font "Name"` or `--font-file /path.ttf`. Tofu boxes are a failed job, not a style.
- **Crop position** for `--fit crop`: default to centre, but if the request or the source names an off-centre subject ("keep the product on the right", "don't cut off my hands", a logo/person visibly off-centre in `look.py`'s sheet) use `--crop-x`/`--crop-y` (0=left/top, 1=right/bottom) instead of the silent centre guess. Ask which edge to keep when the sheet shows the subject near an edge and the request doesn't say.
- Anything else (transition type, caption style): pick the conventional default, say what you picked, and offer the alternative in one line.

Do not ask for things `probe.py` can tell you.

## What this skill does and does not decide

This skill cuts, joins, measures, syncs, exports and checks files — it executes an edit, it does not decide one. Some things that sound like part of the job but belong to the human, the calling agent, or another skill instead:

- **Which cut is the right one, or whether a deliverable is approvable for release** — this skill measures and reports (`check.py`'s PASS/WARN/FAIL, `cut.py`'s measured duration error); a production agent or the user decides whether that's good enough to ship.
- **What makes a highlight interesting** — `scenes.py --highlights` ranks by a measured proxy (audio energy or scene duration, see its own docs), never by understanding the content; treat its output as candidates, not a verdict.
- **Thumbnail or cover-image composition** — that's a design decision, not a measurement; a thumbnail-generation skill or the user makes it.
- **Understanding what a video is *about*** — this skill has no transcription or vision beyond `look.py`'s contact sheets, which exist for the calling agent's own eyes, not for this skill to interpret on its own.
- **Judging what looks good** — "apply this LUT" or "correct exposure by +0.3 stops" (`color.py`) is mechanical, parameter-determined execution and belongs here; "grade this scene to look cinematic" is a subjective judgement about what looks right and belongs in a colour-grading skill ([`color-grading-skill`](https://github.com/kajisho5/color-grading-skill), see README's "Standalone, and in an ecosystem") that decides the parameters and then calls `color.py` to apply them.
- **Picking a subject or region without being told one** — "crop to this exact box" or "crop to 9:16 keeping x=200,y=0" (`crop.py`/`fit.py --fit crop --crop-x/-y`) is mechanical once the box is known; "crop to keep the speaker in frame" requires deciding *what* the speaker is, which is a vision/composition judgement for the calling agent (from a `look.py` contact sheet) or a motion-graphics skill, not this one.

The line in general: if the same input and the same explicit parameters always produce the same, verifiable output, it belongs here. If the "right" answer depends on taste, content understanding, or what looks or sounds good, it belongs to whichever skill or agent makes that judgement — this skill only ever executes parameters it's given, never infers them from what something looks or sounds like.

If a request needs an FFmpeg feature none of the 28 scripts expose, say so and name the closest built-in option (`--dry-run` to show what would run, or a documented limitation) — never fall back to guessing a raw `ffmpeg`/`ffprobe` invocation or a hand-built filter graph outside `scripts/*.py`. A raw command bypasses every guarantee this skill makes (no shell, typed arguments, verification afterwards); it is exactly the failure mode this skill exists to prevent, so it is never the fallback when a script's flag doesn't cover something.

## Request → script

| User says | Do |
|-----------|----|
| "what's in this file", "how long is it", "is it 4K" | `probe.py input.mp4` |
| "cut from 1:20 to 2:05", "trim the first 10 seconds" | `cut.py input.mp4 --start 1:20 --end 2:05` |
| "keep only these parts", "remove the middle" | `cut.py input.mp4 --segments 0-1:00,1:30-2:00` |
| "make it exactly 60 seconds", "fit it in 30s" | `fit.py input.mp4 --duration 60` (speed) or `--method trim` |
| "make it vertical / for TikTok / 9:16", "square for Instagram" | `fit.py input.mp4 --aspect 9:16 --fit pad` (or `--fit crop`) |
| "resize to a specific height, width follows" | `fit.py input.mp4 --height 1080` (or `--width`, or both for an exact frame) |
| "crop to this exact box/rectangle" (known x/y/width/height, not an aspect ratio) | `crop.py input.mp4 --x 100 --y 0 --width 1080 --height 1920` |
| "are there black bars on this?", "what's the crop rectangle to remove the letterboxing" | `cropdetect.py input.mp4` |
| "this old footage is interlaced / combed on motion" | `deinterlace.py input.mp4` |
| "this footage is grainy/noisy, clean it up" | `denoise.py input.mp4 --strength medium` |
| "blur/pixelate this face/plate/region" (known x/y/width/height) | `redact.py input.mp4 --x 820 --y 140 --width 240 --height 240 --mode pixelate` |
| "turn this image into a N-second clip", "title card / end slate" | `insert.py title.png --duration 3` |
| "slow zoom on a photo", "Ken Burns effect" | `insert.py photo.jpg --duration 6 --zoom in --pan right --width 1920 --height 1080` |
| "rotate this 90 degrees", "mirror it horizontally" | `fit.py input.mp4 --rotate 90` / `fit.py input.mp4 --flip h` |
| "reverse this clip", "play it backwards" | `reverse.py input.mp4` |
| "stabilize this shaky footage" | `stabilize.py input.mp4` |
| "make a blank/colour background clip" | `background.py -o bg.mp4 --duration 3 --width 1920 --height 1080 --color 0x101010` |
| "turn these numbered frames into a video" | `sequence.py --dir frames --pattern "frame_%04d.png" --fps 24` |
| "make a waveform/spectrum video for this podcast/track" | `waveform.py podcast.wav -o waveform.mp4` |
| "add subtitles from this SRT", "burn in captions" | `caption.py input.mp4 --srt subs.srt` |
| "caption it with these lines" (plain text with times) | `caption.py input.mp4 --text cues.txt` |
| "add subtitles but keep them toggleable / editable", "mux in an SRT, don't burn it" | `caption.py input.mp4 --srt subs.srt --mode mux` |
| "put our logo top-right", "add a watermark" | `overlay.py input.mp4 --image logo.png --position top-right --scale 200` |
| "add a title for the first 4 seconds" | `overlay.py input.mp4 --text "Title" --position top --start 0 --end 4 --fade 0.4` |
| "put this webcam clip in the corner", "picture-in-picture" | `overlay.py input.mp4 --video webcam.mp4 --position bottom-right --scale 480` |
| "remove the green screen", "chroma key this" | `overlay.py bg.mp4 --video greenscreen.mp4 --chromakey 0x00ff00` |
| "sync the lav mic to the camera", "line up the two cameras" | `sync.py camera.mp4 mic.wav --replace-audio` / `sync.py camA.mp4 camB.mp4 --trim-second` |
| "fix the audio levels", "normalise to -14 LUFS" | `loudness.py input.mp4` (`-I -16 --tp -1.5` for podcasts, `-I -23` for broadcast) |
| "export for YouTube / Reels / X", "give me a ProRes master", "make it HEVC" | `export.py input.mp4 --preset youtube|reels|x|prores|h265` |
| "make a GIF preview" | `export.py input.mp4 --preset gif` |
| "make a small/low-res proxy for an analysis pass", "a cheap preview file" | `proxy.py input.mp4 [--width 640 --no-audio]` — not a delivery preset, see `export.py` for those |
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
| "the colours are tagged wrong" | `color.py input.mp4 --retag bt709` (stream copy; re-encodes only if the copy can't carry the retagged colour info — check `reencoded` in `--json`) |
| "brighten it a touch / punch up the contrast and saturation / fix the white balance" | `color.py input.mp4 --correct --exposure 0.3 --contrast 1.1 --saturation 1.05 --temperature 5600 --tint -0.05` (typed, no filter string) |
| "clean up the audio", "remove the hiss / room noise" | `audio.py input.mp4 --voice` (speech) or `--denoise` |
| "add background music under the talking" | `audio.py input.mp4 --music bed.mp3 --duck --fade-out 3` |
| "convert the 5.1 to stereo" | `audio.py input.mov --downmix` |
| "swap in the narration track" | `audio.py input.mp4 --replace narration.wav` |
| "pull the audio out of this video", "give me the sound as WAV" | `audio.py input.mp4 -o input.wav` (any audio extension drops the picture; `--audio-stream 1` picks another track) |
| "compress the voice", "limit the peaks to -1 dB", "gate the room noise" | `audio.py input.mp4 --compress --comp-threshold -20 --comp-ratio 4` / `--limit --limit-ceiling -1` / `--gate --gate-threshold -45` (typed acompressor / alimiter / agate options, range-checked) |
| "the audio drifts out of sync over the hour" | `sync.py camera.mp4 recorder.wav --fix-drift --replace-audio` |
| "smooth slow motion", "half speed but fluid" | `fit.py input.mp4 --duration 2x --smooth interpolate` (slow) or `--smooth blend` |
| "TikTok-style captions with the words popping / highlighted" | `caption.py input.mp4 --text cues.txt --animate pop --karaoke` |
| "it's a phone video with variable frame rate" | nothing extra: every re-encoding script conforms VFR to constant fps automatically; `fit.py --fps 30` to pick the rate |


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

| User says (audio file) | Do |
|-----------|----|
| "normalise this WAV to -14 LUFS", "podcast levels" | `loudness.py talk.wav -I -14 --tp -1 -o talk_norm.wav` (`-I -16 --tp -1.5` for podcasts) |
| "remove the silence from this recording" | `silence.py talk.wav -o talk_tight.wav` |
| "clean up the noise in this M4A" | `audio.py talk.m4a --voice -o talk_clean.m4a` (speech) or `--denoise` |
| "convert this WAV to MP3" | `audio.py talk.wav -o talk.mp3` |
| "trim this audio from 00:30 to 02:00" | `cut.py talk.wav --start 0:30 --end 2:00 -o talk_cut.wav` (`--accurate` for sample-exact) |
| "join these recordings", "intro + episode + outro" | `join.py intro.wav episode.m4a outro.wav -o full.flac` (`--transition none` for a butt join) |
| "extract the audio from the video", "mp4 to wav" | `audio.py talk.mp4 -o talk.wav` (`--voice -o talk.m4a` to clean it on the way) |
| "compress / limit / gate the voice" | `audio.py talk.wav --compress --comp-threshold -20 --comp-ratio 4 --limit --limit-ceiling -1 -o talk_dyn.wav` |
| "is this loud enough for Apple Podcasts?" | `check.py talk.m4a --platform podcast` |

## Report format

Reply in the language the user wrote their request in — a Japanese request gets a Japanese report, English gets English, Chinese gets Chinese, and so on for any other language. Keep the shape below and the field labels (`Done:`, `Steps:`, `Check:`, `Look:`, `Notes:`) in English (they read like log fields, not prose, and stay recognisable across languages); the sentences around them, any question asked, and any explanation of a judgement call are in the user's language. Never default to English because the tool names and flags happen to be English. A mid-conversation language switch follows the user's latest message, not the first one.

Finish every job with this shape (numbers from `probe.py`/`check.py`, not memory):

```
Done: final.mp4 — 59.98 s, 1080x1920, 30 fps, H.264, AAC stereo, -14.1 LUFS
Steps: cut 0:12-1:12 (lossless) -> fit 9:16 crop -> captions (pop, karaoke) -> loudness -14 -> export reels
Check: reels — all 12 checks pass
Look: final_sheet.png (captions inside the safe area, logo top-right)
Notes: source was VFR, conformed to 30 fps; audio was mono, made stereo
```

Keep it to those five lines plus anything the user must decide. Attach the contact sheet when the edit touched the picture. Never report success without the probe of the output; never describe a fix you did not run.

When a step fails, replace `Done:` with `Failed:` and keep the rest honest:

```
Failed: color.py --lut grade.cube exited 1 — ffmpeg: "Unable to parse LUT file" (the .cube is not a valid LUT)
Steps: probe -> color (failed); nothing written
Notes: send a valid .cube, or say if you want the clip left as is
```

Every script prints `{"status": "failed", "error": {"kind": input | ffmpeg | output | missing_tool, "message": ...}}` with `--json` and exits non-zero; quote the message, do not paraphrase it into a success.

## Things that look right but are wrong

- Re-encoding an HDR (iPhone, HDR10) source through the SDR path: colours go flat. The scripts keep HDR; if you hand-write ffmpeg, do not tag BT.709 on BT.2020 pixels.
- Lossless `-c copy` cuts on VFR or non-keyframe boundaries: the file "works" but starts on a frozen or wrong frame. `cut.py` re-encodes automatically when the snap exceeds 0.5 s; respect that.
- A sync or multicam alignment with `confidence` under 0.3, or an offset larger than 60 % of the analysis window: probably wrong; enlarge `--analyze-seconds` or find a clap. `multicam.py` reports one `confidence` per camera — check all of them, not just that the command succeeded, before trusting the cut.
- `sync.py`/`multicam.py` align audio tracks to each other, never lip sync (mouth movement vs. audio) — there is no face or mouth detection anywhere in this skill. A high confidence means the audio matched well, not that the picture looks right; if the user asks whether lip sync is correct, that needs a look at the actual video, not just the reported offset.
- "Normalised" audio that still clips: check true peak, not just LUFS (`check.py` does both).
- Normalising ambience or near-silence to a speech target: a clip measured at
  -40 LUFS or below is room tone, wind or nothing; raising it 25 dB raises the
  noise, not the content. Leave the level, say so, and offer music or narration.
- Captions burned before a crop/resize: text lands off-frame. Frame changes first, then text.
- Anything chained by hand through three re-encodes: use `render.py` so the plan is one file and the user can change one number.
- `--fit crop` to reach 9:16 from 16:9 throws away 70 % of the width: a wide shot loses people at the edges. Check the sheet; pad (bars), `--crop-x`/`--crop-y` toward the subject, or a reframe is often the honest answer — a silent centre crop is a guess, not a decision.
- Conforming 60 fps to 30 halves the motion samples: fine for a talking head, visibly choppy for sports, gaming, drone pans. Keep 60 when the platform allows it.
- "Make it 60 seconds" on a 3-minute talk by speed change is unwatchable (3×); by trim it drops two thirds of the words. Ask which, or propose a highlight cut with `scenes.py`.
- `scenes.py --highlights` defaults to the loudest scenes (`--rank-by audio`): a quiet but important moment (a confession, a punchline landing in silence) is skipped, and pure crowd noise or a mic bump can outrank it. `--rank-by duration` picks the longest unbroken scenes instead. Neither is "the best parts" — check the contact sheet (`--sheet`) before treating the picks as final.

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
- **Windows drawtext crashes on some real builds.** On certain Windows ffmpeg
  builds (e.g. winget's gyan.dev), `drawtext` crashes with an access violation
  whenever it resolves a font by family name through fontconfig, even with a
  valid `fonts.conf` (#100). `look.py`, `scenes.py --sheet`, `overlay.py --text`
  and `graphics.py` all resolve a concrete `--font-file` by default when one is
  available (`fontfile=` skips fontconfig entirely and is the form confirmed
  not to crash), so this should already be handled automatically. If a
  drawtext tool still crashes, pass `--font-file` explicitly rather than
  relying on `--font`/`font=` resolution; `doctor` also runs a real one-frame
  drawtext probe and reports `filter:drawtext` missing (with the crash detail
  in `errors[]`) rather than a false "available" from the `-filters` listing
  alone.
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
