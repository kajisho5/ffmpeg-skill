---
name: ffmpeg-skill
description: 'Edit video and audio with local FFmpeg from natural-language requests: cut, trim, join, resize/reframe (9:16, 1:1), speed change, captions and subtitles (SRT/ASS, animated, karaoke), logos and text overlays, lower-thirds and titles, silence removal, multicam and external-mic sync, loudness normalisation, HDR/Dolby Vision to SDR, LUTs, background music with ducking, platform exports (YouTube, Reels, TikTok, X), compliance checks, scene detection and highlight reels, contact sheets to inspect results, and whole-edit project files. Use this skill whenever the user mentions a video or audio file (mp4, mov, mkv, wav, m4a), footage, a clip, captions, subtitles, a reel or short, YouTube/Instagram/TikTok delivery, LUFS, sync, transcoding, ffmpeg, or asks to make something "60 seconds", "vertical", "louder", "captioned" — even when they do not say "edit". Python 3.9 standard library only, no cloud, no API keys.'
---

# ffmpeg-skill

Scripts live in `scripts/` next to this file; run them with `python3 <skill-dir>/scripts/<name>.py`. This file is enough to do a job: the table below routes the request, the recipes give the flags, and `--help` on the one script you are about to run is the cheapest full flag list. The reference files cost as much to read as this file does, so open one only when it answers a question you actually have: `references/scripts.md` (every flag of all 42 scripts, for comparing tools), `references/devices.md` (iPhone HDR, GoPro, DJI, screen recordings, Zoom), `references/gotchas.md` (the long form of the one-line rules at the end of this file).

Shared flags, on every script: `--dry-run`; `--json` (output path, a probe of the output, the commands run); `--json-brief` (that document trimmed to status/output/verified, a compact `summary` and the command count — prefer it on every writing step, `--json` when you need the full probe); `--fast` (preview quality); `--progress`; `--timeout SECONDS` (`kind: timeout`, default 1800); `--overwrite` (consent to replace an existing output — without it the tool warns today, refuses from 2.0); `--plan FILE` (the dry run as a plan document `render.py FILE` executes later, refusing if an input changed: "plan → confirm → execute" in one round trip). Every re-encoding tool also takes `--codec h264|hevc|av1|prores` and `--quality N` (CRF scale, replaces the deprecated `--crf`): unset, SDR is x264 and HDR is x265 Main10; `prores` needs an explicit `-o NAME.mov` (or `.mkv`), `h264` refuses an HDR source (run `color.py --to-sdr` first).

Writing tools run nothing under `--dry-run`; `probe`, `check`, `sync`, `multicam`, `scenes`, `cropdetect`, `report`, `silence`, `loudness` and `stabilize` may still run ffmpeg/ffprobe to measure or analyse — they just don't write their final artifact (nor side files such as `--edl`, `--sheet` or a generated `.ass`); `verify` accepts the flag but ignores it. Exact per-tool semantics: `contract --json`'s `dry_run` field (or `docs/contract.md`).

## Workflow (always follow this order)

0. **Environment, only on failure.** Do not start a job with `doctor`: on a working machine it is a call that tells you nothing the job needs, and on a broken one the script fails on its own with `kind: missing_tool` (no ffmpeg) or an ffmpeg error naming the filter or encoder (`No such filter: 'subtitles'`). Run `python3 <skill-dir>/scripts/_contract.py doctor` (also `npx ffmpeg-skill doctor`; there is no doctor.py) after such a failure, or when the user asks what the machine can do. Read `ok` and the tool's `usable`; if `usable` isn't `yes`, report the missing capability (a missing `libass`, `zscale` or encoder is the common case, e.g. `caption.py`) instead of discovering it through a runtime failure. `contract --json`'s full tool schema is for a *planning* agent choosing a tool from an abstract goal, not for this per-job workflow.
1. **Probe what you must plan from.** Run `probe.py` on each input you plan the edit from — duration, fps, resolution, codecs, channels, `variable_frame_rate_suspected` — and whenever the user asks a question about a file. You do not need a separate probe before every edit: every writing tool's `--json` already carries its input and a probe of the output it wrote. Plan from real numbers, never assumptions.
2. **Prefer lossless.** If the request can be met without re-encoding (plain cuts on keyframes, remuxing, audio-only changes), do not re-encode. `cut.py` and `loudness.py` stream-copy video by default; pass `--accurate` to `cut.py` only for frame-exact cuts.
3. **Plan with `--dry-run --json`, then execute.** Trust `--json`, not a dry run's human-readable summary line, for any number after the plan (dimensions there can be a placeholder, not a computed preview — `docs/contract.md`). Use it to confirm a plan before long encodes and to report exact facts. `--fast` is preview quality (x264 veryfast), `--progress` prints percent/ETA on stderr. Never point `-o` at a file you did not create in this job unless the user asked for it to be replaced; pass `--overwrite` only then.
4. **Chain in a sensible order.** Colour (HDR→SDR / LUT) → cut → join → silence → fit → caption/overlay → sync → audio → loudness → export. Frame changes (fit/crop) before captions and overlays, so text is sized for the final frame. Re-encode as few times as possible: intermediates at CRF 18 (the default), `export.py` only for the last step. **Three or more steps: use `render.py` with a project.json** — one call, one JSON, one place for the user to change a number — rather than hand-chaining tools.
5. **Check the deliverable.** Before reporting, run `check.py OUTPUT --platform X` for the destination the user named. Each row is `format` or `judgement`. Format rows (codec, pixel format, size, true peak, colour tags, VFR) are safe to fix mechanically. Judgement rows change the content: duration (cut loses material, speed changes motion), aspect (crop loses edges), fps (drops motion), loudness (ambience must not be boosted) — fix those only when the request already implies the answer, otherwise state the choice and its cost in one line. Mention WARNs; do not chase them.
6. **Verify the output.** Confirm duration, resolution, fps and audio match the request — from the writing tool's own `--json`/`--json-brief` probe, or `probe.py` when you have none — and report those numbers ("final.mp4: 59.98 s, 1080x1920, 30 fps, AAC stereo"). A step is done only when the script exited 0 and the output probes as expected. Writing the command is not doing the job: a non-zero exit, a missing or empty file, or a probe that contradicts the request is a failure, and the report says so with the script's error message.
7. **Keep the user's originals.** Never overwrite the source; write new files next to the input or where the user asked. Set `FFMPEG_SKILL_NO_OVERWRITE=1` in the environment you run these scripts in: an existing output path is then refused (`kind: input`) instead of warned about, and `--overwrite` stays the one way to say "yes, replace it". It is the recommended agent setting — an agent picking output names cannot see which files the user already cares about — and it is what 2.0 does by default.
8. **Look at the picture.** Whenever the picture changed (captions, overlays, graphics, crop/pad, resize, colour, transitions, a `join.py` that scaled or padded a clip to the first clip's frame, a `color.py --to-sdr` that tone-maps an HDR source) run `look.py OUTPUT --tiles 3x2` (or `--at T` for one frame) and view the PNG; the full 4x3 sheet is for a job about layout across the whole clip. The job is not finished until the report's `Look:` line names that PNG — a probe cannot see a caption sitting on someone's face. Audio-only jobs (sync, loudness, silence, or any job whose input is an audio file) write `Look: not needed`; there is no picture. What to look for splits like `check.py`'s rows in step 5:
   - **Mechanical (this skill's own job to verify and report):** the specified text/logo is present at the specified position, subtitles/text appear at the specified timestamps, dimensions are even. Letterboxing/pillarboxing from `fit.py --fit pad` is the *correct* result of that mode, never a defect to flag.
   - **Judgement (report it, don't silently pass or fail):** whether a subject or face is cut off, whether text sits over a face, whether colours look washed out, whether a transition lands. These need deciding what the subject *is*, which belongs to the calling agent (see "What this skill does and does not decide") — say what you see in one line and let them judge it.
   With no vision capability, write `Look: PATH (pixels not inspected; agent has no image view)` — never claim a picture was inspected when it wasn't, and don't stall waiting for a capability that isn't there.

## Before you run anything: what to ask, what to assume

Ask one short question only when the answer changes the output materially and the request does not imply it. When several things are open at once (a vague "make it for social media" leaves destination, aspect method, length and captions unresolved), don't ask them one per turn: propose one bundle with your defaults and let the user change any part ("Reels: 9:16 with padding, trimmed to 60 s, -14 LUFS, no captions — OK, or change something?"). One question, one answer, then the run. Never ask for what `probe.py` can tell you.

- **Destination** decides aspect, length limit, loudness and codec; "for Reels" answers all four. No destination named and a plain cut/caption: keep the source format and say so. If the user says "export", "post" or "deliver", ask where.
- **Duration** ("make it 60 s") without a method: speed up for ≤1.5× changes, trim otherwise, and say which you chose. Ask when the content is a talk (trimming loses words) and the change is large.
- **Captions** without a text source: `--transcribe` if a local whisper exists, otherwise ask for the text or a timed file; never invent dialogue.
- **Fonts and brand**: if the user mentions a brand, colours or "our font", ask for or create `brand.json` once and reuse it.
- **CJK / non-Latin text**: let the tool pick the font by script (`--font` turns that off); `--lang ja|ko` for Han-only text. `doctor --json` `.fonts.scripts` says what renders here. Tofu is a failed job, not a style.
- **Crop position** for `--fit crop`: centre by default, but when the request or the source names an off-centre subject ("keep the product on the right", "don't cut off my hands", someone visibly off-centre in the sheet) use `--crop-x`/`--crop-y` (0=left/top, 1=right/bottom) instead of a silent centre guess. Ask which edge to keep when the sheet shows the subject near an edge and the request doesn't say.
- Anything else (transition type, caption style): pick the conventional default, say what you picked, offer the alternative in one line.

## What this skill does and does not decide

This skill cuts, joins, measures, syncs, exports and checks files — it executes an edit, it does not decide one. What belongs to the human, the calling agent or another skill:

- **Which cut is right, or whether a deliverable is approvable** — this skill measures and reports (`check.py`'s PASS/WARN/FAIL, `cut.py`'s measured duration error); the user or a production agent decides whether that ships.
- **What makes a highlight interesting** — `scenes.py --highlights` ranks by a measured proxy (audio energy, scene duration), never by understanding content: candidates, not a verdict.
- **Thumbnail or cover composition** — a design decision, not a measurement.
- **Understanding what a video is *about*** — there is no transcription or vision here beyond `look.py`'s contact sheets, which exist for the calling agent's eyes, not for this skill to interpret.
- **Judging what looks good** — "apply this LUT", "correct exposure by +0.3 stops" (`color.py`) is mechanical and belongs here; "grade this scene to look cinematic" belongs to a colour-grading skill ([`color-grading-skill`](https://github.com/kajisho5/color-grading-skill)) that decides the parameters and then calls `color.py`.
- **Picking a subject or region you were not given** — "crop to x=200,y=0" (`crop.py`/`fit.py --crop-x/-y`) is mechanical once the box is known; "crop to keep the speaker in frame" needs deciding *what* the speaker is — a judgement for the calling agent (from a `look.py` sheet) or a motion-graphics skill.

The line: same input + same explicit parameters always producing the same verifiable output belongs here; anything that depends on taste, content understanding or what looks or sounds good belongs to whoever makes that judgement. This skill executes parameters it is given, never infers them from what something looks or sounds like.

If a request needs an FFmpeg feature none of the 42 scripts expose, say so and name the closest built-in option (`--dry-run` to show what would run, or a documented limitation) — never fall back to guessing a raw `ffmpeg`/`ffprobe` invocation or a hand-built filter graph outside `scripts/*.py`. A raw command bypasses every guarantee this skill makes (no shell, typed arguments, verification afterwards); it is exactly the failure mode this skill exists to prevent, so it is never the fallback when a script's flag doesn't cover something.

## Request → script

This table and `doctor --json`'s `tools` list are the source of truth for what exists: name only a script you have seen in one of them, never a plausible-sounding one (there is no `doctor.py`, no `trim.py`, no `subtitle.py`).

Timestamp flags — `--start`, `--end`, `--at`, `--from`, `--duration`, `--offset`, and the times in cue and chapter files — take seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` or four-part SMPTE `hh:mm:ss:ff`, with `@fps` naming the rate (`00:01:02:15@29.97`); tolerance-style flags that are a length rather than a point in time (`--min-silence`, `--margin`, `--min-keep`, `--fade`) are plain seconds. Use the timecode forms when the user pastes an editor's timecode list or an NLE cue sheet, so nothing is converted by hand on the way in.

| User says | Do |
|-----------|----|
| "what's in this file", "how long is it" | `probe.py input.mp4` |
| "cut from 1:20 to 2:05", "trim the first 10 s" | `cut.py input.mp4 --start 1:20 --end 2:05` |
| "keep only these parts", "remove the middle" | `cut.py input.mp4 --segments 0-1:00,1:30-2:00` |
| "make it exactly 60 seconds" | `fit.py input.mp4 --duration 60` (speed) or `--method trim` |
| "make it vertical / 9:16 / square" | `fit.py input.mp4 --aspect 9:16 --fit pad` (or `--fit crop`; `--pad-fill blur` for blurred bars) |
| "resize to a height/width" | `fit.py input.mp4 --height 1080` (or `--width`, or both for an exact frame) |
| "crop to this exact box" (known x/y/w/h) | `crop.py input.mp4 --x 100 --y 0 --width 1080 --height 1920` |
| "are there black bars on this?" | `cropdetect.py input.mp4` |
| "this old footage is interlaced" | `deinterlace.py input.mp4` |
| "it's grainy/noisy, clean it up" | `denoise.py input.mp4 --strength medium` |
| "blur/pixelate this face/plate" (known box) | `redact.py input.mp4 --x 820 --y 140 --width 240 --height 240 --mode pixelate` |
| "flat view out of this 360 video" (known yaw/pitch/fov) | `sphere.py insta360.mp4 --yaw 90 --pitch 0 --h-fov 100 --v-fov 70` |
| "the horizon is tilted" (known degrees) | `straighten.py tilted.mp4 --degrees -2.5` |
| "turn this image into a clip", "title card" | `insert.py title.png --duration 3` |
| "slow zoom on a photo", "Ken Burns" | `insert.py photo.jpg --duration 6 --zoom in --pan right --width 1920 --height 1080` |
| "rotate 90 degrees", "mirror it" | `fit.py input.mp4 --rotate 90` / `fit.py input.mp4 --flip h` |
| "reverse this clip" | `reverse.py input.mp4` |
| "stabilize this shaky footage" | `stabilize.py input.mp4` |
| "make a blank/colour background clip" | `background.py -o bg.mp4 --duration 3 --width 1920 --height 1080 --color 0x101010` |
| "turn these numbered frames into a video" | `sequence.py --dir frames --pattern "frame_%04d.png" --fps 24` |
| "waveform/spectrum video for this track" | `waveform.py podcast.wav -o waveform.mp4` |
| "hold on this frame", "freeze the last frame" | `freeze.py clip.mp4 --hold 2` |
| "add black at the start" | `pad.py clip.mp4 --start 1.5` |
| "speed up here, slow-mo there" (known segments) | `speedramp.py action.mp4 --segment 0-3:1.0 --segment 3-4:0.25 --segment 4-8:2.0` |
| "loop this clip to fill 30 seconds" | `loop.py bg_loop.mp4 --duration 30` |
| "cut to the product shot 0:12-0:16", "B-roll over this bit" | `broll.py talk.mp4 --insert product.mp4 --at 12 --end 16` (repeat `--insert/--at`; `--audio b\|mix`) |
| "add chapters", "chapter markers for YouTube" | `metadata.py episode.mp4 --chapters chapters.txt` (`TIME TITLE` per line; streams copied) |
| "set the title / artist / comment" | `metadata.py episode.mp4 --title "Episode 12" --artist "Studio"` |
| "put these videos in a 4x2 grid" | `grid.py t1.mp4 ... t8.mp4 --cols 4 --rows 2` |
| "add subtitles from this SRT", "burn in captions" | `caption.py input.mp4 --srt subs.srt` |
| "caption it with these lines" (text with times) | `caption.py input.mp4 --text cues.txt` |
| "keep the subtitles toggleable", "mux in an SRT" | `caption.py input.mp4 --srt subs.srt --mode mux` |
| "our logo top-right", "a watermark" | `overlay.py input.mp4 --image logo.png --position top-right --scale 200` |
| "a title for the first 4 seconds" | `overlay.py input.mp4 --text "Title" --position top --start 0 --end 4 --fade 0.4` |
| "webcam clip in the corner", "picture-in-picture" | `overlay.py input.mp4 --video webcam.mp4 --position bottom-right --scale 480` |
| "remove the green screen" | `overlay.py bg.mp4 --video greenscreen.mp4 --chromakey 0x00ff00` |
| "sync the lav mic", "line up two cameras" | `sync.py camera.mp4 mic.wav --replace-audio` / `sync.py camA.mp4 camB.mp4 --trim-second` |
| "fix the audio levels", "normalise to -14 LUFS" | `loudness.py input.mp4` (`-I -16 --tp -1.5` podcast, `-I -23` broadcast) |
| "cut this and make it HEVC / AV1 / ProRes" (output codec named) | `cut.py input.mp4 --start 0:10 --end 0:40 --codec hevc` (`--codec`/`--quality` on any re-encoding tool; ProRes needs `-o NAME.mov`) |
| "export for YouTube / Reels / X", "a ProRes master" | `export.py input.mp4 --preset youtube\|reels\|x\|prores\|h265` (`--normalize` hits the loudness spec in the same call) |
| "make a GIF preview" | `export.py input.mp4 --preset gif` |
| "a small proxy / cheap preview file" | `proxy.py input.mp4 [--width 640 --no-audio]` — not a delivery preset (those are `export.py`) |
| "cut out the pauses", "jump cuts" | `silence.py input.mp4 [--threshold -40 --min-silence 0.8]` |
| "stitch these clips", "add a crossfade" | `join.py a.mp4 b.mp4 c.mp4 --transition fade --duration 0.5` |
| "show me what it looks like", "are the captions readable" | `look.py output.mp4 --tiles 3x2` then view the PNG |
| "what would you run?", "don't render yet" | any script with `--dry-run` |
| "a 60 s highlight from this hour" | `scenes.py long.mp4 --highlights 6 --target 60 --edl picks.txt` → `cut.py --segments` |
| "is this OK to upload?" | `check.py final.mp4 --platform reels` |
| "several changes to the same edit", 3+ steps | `render.py --init project.json`, edit, `render.py project.json` |
| "a lower third with my name", "countdown intro", "progress bar" | `graphics.py input.mp4 --template lower-third --name "..." --title "..." --start 2 --end 8` |
| "use our brand fonts/colours/logo" | `--brand brand.json` on caption/overlay/graphics, or `"brand"` in project.json |
| "send me a summary of what you did" | `report.py --before raw.mov --after final.mp4 --platform youtube -o report.html` |
| "do this to every file in the folder" | `batch.py FOLDER --recipe batch.json` (steps or a render project; cached) |
| "transcribe it and caption it" | `caption.py input.mp4 --transcribe --animate pop --karaoke` (needs a local whisper; else `--text`) |
| "three cameras, cut between them" | `multicam.py camA.mp4 camB.mp4 camC.mp4 --switch "0-20:0,20-40:1,40-60:2"` |
| "iPhone Dolby Vision clip looks wrong" | `color.py clip.mov --to-sdr` or `--strip-dovi` (keep HDR, drop the DV layer) |
| "does it look like Log / S-Log?" | `probe.py clip.mp4 --analyze` (`looks_like_log`) then `color.py --lut` |
| "test the tool on my real files" | `verify.py ~/Footage --report verify.md` |
| "show me progress", "quick preview first" | any encoding script with `--progress` and/or `--fast` |
| "the colours look washed out / iPhone HDR" | `color.py input.mov --to-sdr` (probe shows `hdr: true`) |
| "apply this LUT", "convert the S-Log footage" | `color.py input.mp4 --lut grade.cube [--lut-strength 0.7]` |
| "the colours are tagged wrong" | `color.py input.mp4 --retag bt709` (stream copy; re-encodes only if the copy can't carry it — see `reencoded`) |
| "brighten it / punch up contrast / fix white balance" | `color.py input.mp4 --correct --exposure 0.3 --contrast 1.1 --saturation 1.05 --temperature 5600 --tint -0.05` |
| "clean up the audio", "remove the hiss" | `audio.py input.mp4 --voice` (speech) or `--denoise` |
| "add background music under the talking" | `audio.py input.mp4 --music bed.mp3 --duck --fade-out 3` |
| "convert the 5.1 to stereo" | `audio.py input.mov --downmix` |
| "swap in the narration track" | `audio.py input.mp4 --replace narration.wav` |
| "pull the audio out", "give me the sound as WAV" | `audio.py input.mp4 -o input.wav` (an audio extension drops the picture; `--audio-stream 1` picks a track) |
| "compress the voice", "limit the peaks", "gate the room noise" | `audio.py input.mp4 --compress --comp-threshold -20 --comp-ratio 4` / `--limit --limit-ceiling -1` / `--gate --gate-threshold -45` |
| "the audio drifts out of sync over the hour" | `sync.py camera.mp4 recorder.wav --fix-drift --replace-audio` |
| "smooth slow motion", "half speed but fluid" | `fit.py input.mp4 --duration 2x --smooth interpolate` (slow) or `--smooth blend` |
| "TikTok-style captions with the words popping" | `caption.py input.mp4 --text cues.txt --animate pop --karaoke` |
| "it's a phone video with variable frame rate" | nothing extra: re-encodes conform VFR to constant fps; `fit.py --fps 30` picks the rate |

## Audio-only files

Audio is a first-class input: `probe.py`, `cut.py`, `silence.py`, `loudness.py`, `audio.py`, `sync.py` and `check.py --platform podcast` take WAV, FLAC, MP3, M4A/AAC, OGG and Opus, and the output extension picks the format. `Look: not needed` in the report; `Check:` still applies (`check.py file.wav --platform podcast`). Scripts that need a picture (`fit`, `caption`, `overlay`, `graphics`, `color`, `export`, `scenes`, `look`) refuse an audio file with "input has no video stream" — say so instead of forcing a video wrapper. The same commands work with `talk.wav` in place of `talk.mp4`; audio-specific recipes, packet vs sample precision, joining and extracting one track: `references/gotchas.md#audio-only-files`.


## Report format

Reply in the language the request itself is written in — the user's own sentences, not a language the request talks about (a request for subtitles in another language is still answered in the language it was written in) and not the language of a tool's error text or file names. Chinese, Korean, Spanish, Portuguese, French, German, Arabic or any other language works exactly the same way. Keep the field labels (`Done:`, `Steps:`, `Check:`, `Look:`, `Notes:`) in English: they read like log fields and stay recognisable across languages. Everything around them — the sentences, any question, any explanation of a judgement call — is in the user's language. Never default to English because the tool names and flags are English, and never drift into another language because the job was short or the report is a failure: a one-line "file does not exist" is written in the request's language too. A mid-conversation switch follows the user's latest message, not the first one. This holds for a one-command job: a three-second audio trim with English `Done:`/`Steps:` sentences and one word of the user's language in `Notes:` is an English report — the descriptions (what was cut, from where) are in the user's language even when the values are technical.

Finish every job with this shape (numbers from a tool's `--json` or `probe.py`/`check.py`, not memory):

```
Done: final.mp4 — 59.98 s, 1080x1920, 30 fps, H.264, AAC stereo, -14.1 LUFS
Steps: cut 0:12-1:12 (lossless) -> fit 9:16 crop -> captions (pop, karaoke) -> loudness -14 -> export reels
Check: reels — all 12 checks pass (verified: true)
Look: final_sheet.png (captions inside the safe area, logo top-right)
Notes: source was VFR, conformed to 30 fps; audio was mono, made stereo
```

The same five lines for a Japanese request:

```
Done: final.mp4 — 59.98 秒、1080x1920、30 fps、H.264、AAC ステレオ、-14.1 LUFS
Steps: 0:12-1:12 をカット（無劣化）-> 9:16 にクロップ -> 字幕（ポップ、カラオケ）-> ラウドネス -14 -> Reels 書き出し
Check: reels — 12 項目すべて合格（verified: true）
Look: final_sheet.png（字幕はセーフエリア内、ロゴは右上）
Notes: 元は VFR だったので 30 fps に揃えた。音声はモノラルだったのでステレオにした
```

Same shape in every other language, labels still English — zh: `Done: final.mp4 — 59.98 秒、1080x1920、30 fps、H.264` / `Steps: 0:12-1:12 剪切 -> 9:16 裁剪 -> 字幕 -> Reels 导出`; ko: `Done: final.mp4 — 59.98초, 1080x1920, 30 fps, H.264` / `Steps: 0:12-1:12 컷 -> 9:16 크롭 -> 자막 -> Reels 내보내기`.

Keep it to those five lines plus anything the user must decide. Attach the contact sheet when the edit touched the picture. Never report success without the output probe; never describe a fix you did not run.

When a step fails, replace `Done:` with `Failed:` and keep the rest honest:

```
Failed: color.py --lut grade.cube exited 1 — ffmpeg: "Unable to parse LUT file" (the .cube is not a valid LUT)
Steps: probe -> color (failed); nothing written
Check: nothing to verify
Look: not needed (nothing written)
Notes: send a valid .cube, or say if you want the clip left as is
```

A refusal (a judgement this skill does not make, or something outside its scope) uses the same shape: `Failed:` names what was refused and why, `Steps:` lists what did run (usually only probe), `Look: not needed`. Both keep the five labels so a failed report scans like a successful one — the shortest failure (a missing input, an invalid LUT) still gets all five lines, never prose headings in their place. When a failure JSON carries `error.hint`, quote it in `Notes:`: it is the flag change that makes a retry meaningful.

Every script prints `{"status": "failed", "error": {"kind": input | ffmpeg | output | missing_tool | timeout | verification | interrupted, "message": ...}}` with `--json` and exits non-zero; quote the message, never paraphrase it into a success.

## Things that look right but are wrong

One line each, and each line is enough to act on; open the linked `references/gotchas.md` section only when the job is in that area and the line leaves you with a question.

- HDR (iPhone, HDR10) re-encoded through an SDR path goes flat; the scripts keep HDR, and `hdr: true` is wider than `hdr_signal: true` (a real PQ/HLG/Dolby Vision transfer). Details: [#hdr-and-colour](references/gotchas.md#hdr-and-colour)
- Log footage (S-Log/V-Log/C-Log) is tagged SDR and looks grey: `probe.py --analyze`, then `color.py --lut` before anything else. Details: [#log-footage](references/gotchas.md#log-footage)
- A `-c copy` cut can start on a wrong or frozen frame; `cut.py` re-encodes past a 0.5 s snap — respect it. Details: [#keyframe-cuts](references/gotchas.md#keyframe-cuts)
- VFR phone/screen recordings: re-encodes conform to CFR, `cut.py` switches to `--accurate`; pick the rate with `fit.py --fps` when the average is odd. Details: [#variable-frame-rate](references/gotchas.md#variable-frame-rate)
- Sync/multicam `confidence` under 0.3 (or a huge offset) is probably wrong — check every camera, and remember these align audio, never lip sync. Details: [#sync-multicam-and-drift](references/gotchas.md#sync-multicam-and-drift)
- "Normalised" audio can still clip (check true peak), and ambience at -40 LUFS or below must never be raised to a speech target. Details: [#loudness-and-ambience](references/gotchas.md#loudness-and-ambience)
- Captions burned before a crop/resize land off-frame; burned small then upscaled by `export.py` they come out soft — fit to the delivery size first. Details: [#captions-fonts-and-text-order](references/gotchas.md#captions-fonts-and-text-order)
- Non-Latin text picks a font by script since 1.12; `doctor --json` `fonts.scripts` says which languages this machine renders; no font = failed job, not tofu. Details: [#fonts-by-script](references/gotchas.md#fonts-by-script)
- `--fit crop` 16:9 → 9:16 throws away 70 % of the width, 60→30 fps halves the motion, and "60 seconds" by speed or by trim are different answers — say which and why. Details: [#reframing-fps-and-duration](references/gotchas.md#reframing-fps-and-duration)
- `yuv420p` needs even dimensions and phone rotation tags are honoured, both automatically. Details: [#dimensions-and-rotation](references/gotchas.md#dimensions-and-rotation)
- `scenes.py --highlights` ranks by loudness (or duration), never by meaning: check the sheet before treating picks as final. Details: [#highlights](references/gotchas.md#highlights)
- Three hand-chained re-encodes should be one `render.py` project; re-encodes use x264 `medium`. Details: [#chaining-and-speed](references/gotchas.md#chaining-and-speed)
- Windows drawtext crashes on some builds (#100): pass `--font-file` explicitly if one does. Details: `references/ci-platform-pitfalls.md`
