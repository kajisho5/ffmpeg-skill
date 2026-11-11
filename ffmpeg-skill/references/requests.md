# Request → script, long form

Every row of SKILL.md's request table with its alternatives, caveats and extra flags. SKILL.md
keeps one command per row; open this file when a row there points here or a request needs a
variant it does not show.

| User says | Do |
|-----------|----|
| "cut from 1:20 to 2:05", "trim the first 10 s" | `cut.py input.mp4 --start 1:20 --end 2:05` |
| "keep only these parts", "remove the middle" | `cut.py input.mp4 --segments 0-1:00,1:30-2:00` or `--remove 1:00-1:30` |
| "make it exactly 60 seconds" | `fit.py input.mp4 --duration 60` (speed) or `--method trim` |
| "cut this and make it HEVC / AV1 / ProRes" (output codec named) | `cut.py input.mp4 --start 0:10 --end 0:40 --codec hevc` (ProRes needs `-o NAME.mov`) |
| "cut out the pauses", "jump cuts" | `silence.py input.mp4 [--threshold -40 --min-silence 0.8]` |
| "cut the ums and uhs", "remove the filler words" | `silence.py input.mp4 --filler --words words.json` (measured word timings; `--transcribe` makes them) |
| "don't cut inside a sentence, just the real pauses" | `silence.py input.mp4 --speech-aware` — a breath under `--min-silence` inside a sentence is kept, only sentence-boundary pauses cut; composes with `--filler` into one list |
| "a 60 s highlight from this hour" | `scenes.py long.mp4 --highlights 6 --target 60 --edl picks.txt` → `cut.py --segments` |
| "cut on the beat", "edit it to the music" | `scenes.py track.mp4 --beats --json > beats.json`, then `cut.py input.mp4 --segments ... --snap beats --snap-source beats.json` (`--snap-source` carries the measured grid over) |
| "speed up here, slow-mo there" (known segments) | `speedramp.py action.mp4 --segment 0-3:1.0 --segment 3-4:0.25 --segment 4-8:2.0` |
| "hold on this frame", "freeze the last frame" | `freeze.py clip.mp4 --hold 2` |
| "smooth slow motion", "half speed but fluid" | `fit.py input.mp4 --duration 2x --smooth interpolate` (slow) or `--smooth blend` |
| "reverse this clip" | `reverse.py input.mp4` |
| "loop this clip to fill 30 seconds" | `loop.py bg_loop.mp4 --duration 30` |
| "make it vertical / 9:16 / square" | `fit.py input.mp4 --aspect 9:16 --fit pad` (or `--fit crop`; `--pad-fill blur` for blurred bars) |
| "resize to a height/width" | `fit.py input.mp4 --height 1080` (or `--width`, or both for an exact frame) |
| "crop to this exact box" (known x/y/w/h) | `crop.py input.mp4 --x 100 --y 0 --width 1080 --height 1920` |
| "blurred background instead of black bars" | `fit.py input.mp4 --aspect 9:16 --fit blur` (whole picture kept, borders a blurred, darkened copy) |
| "rotate 90 degrees", "mirror it" | `fit.py input.mp4 --rotate 90` / `fit.py input.mp4 --flip h` |
| "the horizon is tilted" (known degrees) | `straighten.py tilted.mp4 --degrees -2.5` |
| "flat view out of this 360 video" (known yaw/pitch/fov) | `sphere.py insta360.mp4 --yaw 90 --pitch 0 --h-fov 100 --v-fov 70` |
| "this old footage is interlaced" | `deinterlace.py input.mp4` |
| "it's grainy/noisy, clean it up" | `denoise.py input.mp4 --strength medium` |
| "blur/pixelate this face/plate" (known box) | `redact.py input.mp4 --x 820 --y 140 --width 240 --height 240 --mode pixelate` |
| "remove this fixed logo" (known box) | `redact.py input.mp4 --x 40 --y 20 --width 180 --height 60 --mode delogo` |
| "stabilize this shaky footage" | `stabilize.py input.mp4` |
| "are there black bars on this?" | `cropdetect.py input.mp4` |
| "iPhone Dolby Vision clip looks wrong" | `color.py clip.mov --to-sdr` or `--strip-dovi` (keep HDR, drop the DV layer) |
| "the colours look washed out / iPhone HDR" | `color.py input.mov --to-sdr` (probe shows `hdr: true`) |
| "apply this LUT", "convert the S-Log footage" | `color.py input.mp4 --lut grade.cube [--lut-strength 0.7]` |
| "the colours are tagged wrong" | `color.py input.mp4 --retag bt709` (stream copy; re-encodes only if the copy can't carry it — see `reencoded`) |
| "brighten it / punch up contrast / fix white balance" | `color.py input.mp4 --correct --exposure 0.3 --contrast 1.1 --saturation 1.05 --temperature 5600 --tint -0.05` |
| "add subtitles from this SRT", "burn in captions" | `caption.py input.mp4 --srt subs.srt` |
| "caption it with these lines" (text with times) | `caption.py input.mp4 --text cues.txt` |
| "keep the subtitles toggleable", "mux in an SRT" | `caption.py input.mp4 --srt subs.srt --mode mux`; repeat `--srt file:lang` for several languages, `.mkv` for more than two |
| "the captions are tiny / three lines on a Short", "don't chop the sentence" | `caption.py` shrinks the size until the cue fits `--max-lines` before splitting it (`--fit-size off` keeps `--size` and splits instead, `--min-size` the floor). Keep the template's `--max-lines` (2 on a vertical) and let the size drop; raising it to dodge a shrink stacks two words per line. A word still wider than the column at the floor is sliced at the edge (hyphen preferred), never rewritten, automatic; `broken_inside_word` in the JSON counts it |
| "transcribe it and caption it" | `caption.py input.mp4 --transcribe --animate pop --karaoke` (Parakeet/whisper; else `--text`) |
| "TikTok-style captions with the words popping" | `caption.py input.mp4 --text cues.txt --animate pop --karaoke` |
| "our logo top-right", "a watermark" | `overlay.py input.mp4 --image logo.png --position top-right --scale 200` |
| "a title for the first 4 seconds" | `overlay.py input.mp4 --text "Title" --position top --start 0 --end 4 --fade 0.4` |
| "webcam clip in the corner", "picture-in-picture" | `overlay.py input.mp4 --video webcam.mp4 --position bottom-right --scale 480` |
| "remove the green screen" | `overlay.py bg.mp4 --video greenscreen.mp4 --chromakey 0x00ff00` |
| "a lower third with my name", "countdown intro", "progress bar" | `graphics.py input.mp4 --template lower-third --name "..." --title "..." --start 2 --end 8` |
| "a sticker", "a hook card for the first 3 s", "meme text" | `graphics.py input.mp4 --template sticker --text "NEW" --platform tiktok` / `--template hook --title "..." --duration 3` / `--template meme --top "..." --bottom "..."` |
| "use our brand fonts/colours/logo" | `--brand brand.json` on caption/overlay/graphics, or `"brand"` in project.json |
| "sync the lav mic", "line up two cameras" | `sync.py camera.mp4 mic.wav --replace-audio` / `sync.py camA.mp4 camB.mp4 --trim-second`; a third+ recorder is another positional (`sync.py ref.mp4 mic.wav cam2.mp4`), one offsets JSON |
| "fix the audio levels", "normalise to -14 LUFS" | `loudness.py input.mp4` (`-I -16 --tp -1.5` podcast, `-I -23` broadcast; `--lra N` for the range) |
| "clean up the audio", "remove the hiss" | `audio.py input.mp4 --voice` (speech; `--voice light\|medium\|strong`) or `--denoise` |
| "add background music under the talking" | `audio.py input.mp4 --music bed.mp3 --duck --fade-out 3` (`--effects sfx.wav` adds a third bed, never ducked; project levels: `audio.stems`) |
| "make the music duck harder / come back faster" | add `--duck-amount 18 --duck-threshold -30 --duck-release 250` (`--duck-attack` too) |
| "the mix sounds narrow", "wider stereo" | `audio.py band.wav --stereo-widen 0.5` (needs a real stereo source; 5.1 needs `--downmix`) |
| "convert the 5.1 to stereo" | `audio.py input.mov --downmix` |
| "swap in the narration track" | `audio.py input.mp4 --replace narration.wav` |
| "pull the audio out", "give me the sound as WAV" | `audio.py input.mp4 -o input.wav` (an audio extension drops the picture; `--audio-stream 1` picks a track) |
| "compress the voice", "limit the peaks", "gate the room noise" | `audio.py input.mp4 --compress --comp-threshold -20 --comp-ratio 4` / `--limit --limit-ceiling -1` / `--gate --gate-threshold -45` |
| "the audio drifts out of sync over the hour" | `sync.py camera.mp4 recorder.wav --fix-drift --replace-audio` |
| "turn this podcast into a video", "audiogram" | `render.py --template audiogram ep.m4a --image cover.png` — waveform over a still or colour plate; nothing is fetched |
| "make this a TikTok / Reel / Short / YouTube / X / LinkedIn / podcast" | `render.py --template tiktok\|reels\|shorts\|youtube-shorts\|youtube\|x\|linkedin\|facebook\|podcast input.mp4 [--cues cues.txt] [--title "..."]` — frame, captions, loudness, export, check in one command (`--list-templates`; `--write-project` to edit first) |
| "post it everywhere", "one edit for every platform" | `render.py --template all input.mp4 --cues cues.txt` (or a comma list) → one file per destination plus `<name>_pack.md` (`report.py --pack` renders the HTML) |
| "export for YouTube / Reels / X", "a ProRes master", "under 25 MB" | `export.py input.mp4 --preset youtube\|reels\|tiktok\|shorts\|linkedin\|facebook\|x\|prores\|h265` (`--normalize` hits the loudness spec in the same call; `--max-mb 25` fits a size; `youtube-hdr` keeps HDR, `youtube-av1` writes AV1) |
| "make a GIF preview", "the recording is corrupted" | `export.py input.mp4 --preset gif` / `--preset copy --repair` (remux; counts the damage) |
| "a small proxy / cheap preview file" | `proxy.py input.mp4 [--width 640 --no-audio]` — not a delivery preset (that is `export.py`) |
| "is this OK to upload?", "how much quality was lost" | `check.py final.mp4 --platform reels` (`--compare master.mp4`: SSIM/PSNR) |
| "a podcast episode with chapters" | `loudness.py ep.wav -I -16 --tp -1.5` → `metadata.py ep.m4a --chapters chapters.txt` → `check.py ep.m4a --platform podcast` (chapters and channels rows) |
| "send me a summary of what you did" | `report.py --before raw.mov --after final.mp4 --platform youtube -o report.html` |
| "turn this image into a clip", "title card" | `insert.py title.png --duration 3` |
| "slow zoom on a photo", "Ken Burns" | `insert.py photo.jpg --duration 6 --zoom in --pan right --width 1920 --height 1080` |
| "make a blank/colour background clip" | `background.py -o bg.mp4 --duration 3 --width 1920 --height 1080 --color 0x101010` |
| "turn these numbered frames into a video" | `sequence.py --dir frames --pattern "frame_%04d.png" --fps 24` |
| "waveform/spectrum video for this track" | `waveform.py podcast.wav -o waveform.mp4` |
| "add black at the start" | `pad.py clip.mp4 --start 1.5` |
| "cut to the product shot 0:12-0:16", "B-roll over this bit" | `broll.py talk.mp4 --insert product.mp4 --at 12 --end 16` (repeat `--insert/--at`; `--audio b\|mix`) |
| "add chapters", "chapter markers for YouTube" | `metadata.py episode.mp4 --chapters chapters.txt` (`TIME TITLE` per line; streams copied; in a project: `"chapters"`). `--auto-chapters` proposes them from measured pauses/scene cuts (`Chapter N`) |
| "set the title / artist / comment" | `metadata.py episode.mp4 --title "Episode 12" --artist "Studio"` |
| "put these videos in a 4x2 grid" | `grid.py t1.mp4 ... t8.mp4 --cols 4 --rows 2` |
| "stitch these clips", "add a crossfade" | `join.py a.mp4 b.mp4 c.mp4 --transition fade --duration 0.5` (TTS: `--list parts.txt`, `--on-missing skip`, `--on-silent fail`; no re-encode: `--copy --transition none`) |
| "several changes to one edit", 3+ steps | `render.py --init project.json`, edit, `render.py project.json` |
| "I changed one stage, don't redo the rest" | `render.py project.json --cache DIR` — identical stages reused (`--from STAGE` starts there) |
| "open it in Premiere / Resolve / Final Cut" | `render.py project.json --export-timeline edit.fcpxml\|.edl\|.otio` — renders nothing; read `not_exported`; no project? `--write-project` |
| "do this to every file in the folder", "use all the cores" | `batch.py FOLDER --recipe batch.json --jobs auto` (steps or a render project; cached) |
| "three cameras, cut between them" | `multicam.py camA.mp4 camB.mp4 camC.mp4 --switch "0-20:0,20-40:1,40-60:2"` (manual) or `--switch energy` (`--min-shot`); `--edl` = cut list; editor: `--write-project p.json` → `--export-timeline` |
| "what's in this file", "how long is it" | `probe.py input.mp4` |
| "show me what it looks like", "are the captions readable" | `look.py output.mp4 --tiles 3x2`, then view the PNG |
| "which shots are static vs moving", "volume peaks per second", "is this speech or music" | `scenes.py input.mp4 --shots` (static/pan/motion per shot) / `--audio-peaks` (dBFS list) / `--speech` (a speech-vs-music ratio, not a classification) |
| "where does the subject move, so I can crop it myself" | `cropdetect.py input.mp4 --motion-centre` — motion centroid per second, report-only; the calling agent picks the crop |
| "does it look like Log / S-Log?" | `probe.py clip.mp4 --analyze` (`looks_like_log`) then `color.py --lut` |
| "test the tool on my real files" | `verify.py ~/Footage --report verify.md` |
