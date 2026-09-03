# Examples

Natural-language requests and the commands the agent runs for them. Paths
assume the skill is installed at `~/.claude/skills/ffmpeg-skill`; shorten with
`S=~/.claude/skills/ffmpeg-skill/scripts`.

Run `bash examples/make_demo.sh` to generate sample footage from nothing and
push it through every script (outputs land in `examples/out/`).

---

### "What am I working with?"
```bash
python3 $S/probe.py footage.mov --compact
python3 $S/probe.py footage.mov            # full JSON, check variable_frame_rate_suspected
```

### "Cut from 1:20 to 2:05"
```bash
python3 $S/cut.py footage.mov --start 1:20 --end 2:05             # lossless, keyframe-snapped
python3 $S/cut.py footage.mov --start 1:20 --end 2:05 --accurate  # frame-exact
```

### "Keep the intro and the ending, drop the middle"
```bash
python3 $S/cut.py talk.mp4 --segments 0-1:30,18:40-20:00 -o talk_short.mp4
```

### "Make it exactly 60 seconds"
```bash
python3 $S/fit.py talk_short.mp4 --duration 60                  # speed up/down (pitch preserved)
python3 $S/fit.py talk_short.mp4 --duration 60 --method trim    # keep the first 60 s
```

### "Make a vertical version for TikTok / Reels"
```bash
python3 $S/fit.py final.mp4 --aspect 9:16 --fit pad --width 1080 --pad-color black
python3 $S/fit.py final.mp4 --aspect 9:16 --fit crop --width 1080   # centre-crop instead
```

### "Square for Instagram feed, 15 seconds"
```bash
python3 $S/fit.py final.mp4 --aspect 1:1 --fit crop --duration 15 --method trim --from-center
```

### "Add these captions"
`cues.txt`:
```
0:00-0:02.5 Welcome back
0:02.5-0:06 Today: three tips | for cleaner audio
Tip one: get the mic close
```
```bash
python3 $S/caption.py final.mp4 --text cues.txt --size 26 --bold --position bottom
python3 $S/caption.py final.mp4 --srt subtitles.srt --font "Inter" --color FFFFFF --outline 3
python3 $S/caption.py final.mp4 --ass styled.ass
python3 $S/caption.py --text cues.txt --write-srt cues.srt           # SRT only, no video
```

### "Japanese subtitles"
```bash
fc-list | grep -i "cjk"      # find an installed CJK font
python3 $S/caption.py final.mp4 --srt jp.srt --font "Noto Sans CJK JP" --size 28
python3 $S/overlay.py final.mp4 --text "第1話" --font-file /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc --position top --box
```

### "Logo top-right, 80% opacity, fade in and out"
```bash
python3 $S/overlay.py final.mp4 --image logo.png --position top-right --scale 220 --opacity 0.8 --start 0.5 --end 58 --fade 0.5
```

### "Title card for the first 4 seconds"
```bash
python3 $S/overlay.py final.mp4 --text "Episode 12 — Clean Audio" --position top-left --font-size 48 --box --start 0 --end 4 --fade 0.4
```

### "Cut out the pauses"
```bash
python3 $S/silence.py talk.mp4 --list                          # see what would go
python3 $S/silence.py talk.mp4 --threshold -40 --margin 0.2    # render talk_tight.mp4
python3 $S/silence.py talk.mp4 --edl keep.txt                  # hand-edit keep.txt, then:
python3 $S/cut.py talk.mp4 --segments "$(paste -sd, keep.txt)" --accurate
```

### "Stitch the clips with a crossfade"
```bash
python3 $S/join.py intro.mp4 main.mp4 outro.mp4 --transition fade --duration 0.5 -o final.mp4
python3 $S/join.py phone.mov camera.mp4 screen.mkv --transition fadeblack --width 1920 --height 1080 --fps 30
```

### "Let me see it" (and let the agent see it)
```bash
python3 $S/look.py final.mp4                          # final_sheet.png, 12 tiles with timecodes
python3 $S/look.py final.mp4 --at 4.5 --at 12         # individual frames
python3 $S/look.py before.mp4 --compare after.mp4 --at 4
```

### "Tell me what you'd run first"
```bash
python3 $S/fit.py input.mp4 --duration 60 --aspect 9:16 --dry-run
python3 $S/export.py input.mp4 --preset reels --json          # structured result incl. probe of the output
```

### "Do the whole edit and let me tweak it"
```bash
python3 $S/render.py --init project.json      # fill in clips, captions, music, export, check
python3 $S/render.py project.json --dry-run   # review the command plan
python3 $S/render.py project.json --fast      # preview
python3 $S/render.py project.json             # final
```

### "Make a 60 second highlight from an hour"
```bash
python3 $S/scenes.py event.mp4 --highlights 6 --target 60 --edl picks.txt --sheet scenes.png
python3 $S/cut.py event.mp4 --segments "$(paste -sd, picks.txt)" --accurate -o digest.mp4
```

### "Is it OK to upload?"
```bash
python3 $S/check.py final.mp4 --platform reels
python3 $S/check.py spot.mov --platform broadcast      # EBU R128 -23 LUFS
```

### "Three cameras and a recorder — cut it together"
```bash
python3 $S/multicam.py camA.mp4 camB.mp4 camC.mp4 zoom.wav --offsets-only
python3 $S/multicam.py camA.mp4 camB.mp4 camC.mp4 zoom.wav --audio 3 --fix-drift \
  --switch "0-45:0,45-80:1,80-95:2,95-140:0" -o edit.mp4
python3 $S/multicam.py camA.mp4 camB.mp4 --auto 10 -o rough.mp4     # alternate every 10 s
```

### "Run it on my actual footage first"
```bash
python3 $S/verify.py ~/Footage/iphone.MOV ~/Footage/gopro.MP4 ~/Footage/obs.mkv --report verify.md
python3 $S/verify.py ~/Footage --quick
```

### "Is this Log footage?"
```bash
python3 $S/probe.py a7s.mp4 --analyze --compact          # [Log?] when flat + desaturated
```

### "The iPhone HDR footage looks washed out"
```bash
python3 $S/probe.py IMG_0231.MOV --field video.hdr_format        # HDR10/PQ, HLG, ...
python3 $S/color.py IMG_0231.MOV --to-sdr                          # real tone mapping to BT.709
python3 $S/color.py IMG_0231.MOV --to-sdr --tonemap mobius --peak 1200
python3 $S/color.py IMG_0231.MOV --strip-dovi                      # keep HDR, drop the Dolby Vision layer
```

### "Apply the S-Log3 conversion LUT" / "give it this look"
```bash
python3 $S/color.py a7s.mp4 --lut SLog3SGamut3.CineToLC-709TypeA.cube
python3 $S/color.py final.mp4 --lut teal_orange.cube --lut-strength 0.6
```

### "Clean up the audio and add music under it"
```bash
python3 $S/audio.py talk.mp4 --voice                                     # highpass, de-ess, denoise, compress
python3 $S/audio.py talk.mp4 --music bed.mp3 --duck --music-volume -16 --fade-out 3
python3 $S/audio.py surround.mov --downmix                               # 5.1 -> stereo
python3 $S/audio.py clip.mp4 --replace narration.wav --fade-in 0.5
```

### "TikTok-style captions"
```bash
python3 $S/caption.py final.mp4 --text cues.txt --animate pop --karaoke --bold --size 30
python3 $S/caption.py final.mp4 --srt subs.srt --animate fade --position center
# the generated .ass sits next to the output; tweak it and re-run with --ass
```

### "Smooth half-speed slow motion"
```bash
python3 $S/fit.py shot.mp4 --duration 10 --smooth interpolate     # 5 s clip -> fluid 10 s (slow to render)
python3 $S/fit.py shot.mp4 --duration 10 --smooth blend           # quick alternative
```

### "Sync the lav mic to the camera"
```bash
python3 $S/sync.py camera.mp4 lav.wav --json                       # just tell me the offset
python3 $S/sync.py camera.mp4 lav.wav --replace-audio -o camera_synced.mp4
python3 $S/sync.py camera_synced.mp4 lav.wav --json                # verify: offset should be ~0 (on the new file's audio)
```

### "Line up camera B with camera A"
```bash
python3 $S/sync.py camA.mp4 camB.mp4 --trim-second -o camB_aligned.mp4
```

### "It's an hour-long recording and the audio drifts"
```bash
python3 $S/sync.py camera.mp4 zoom_h5.wav --fix-drift --json                 # reports offset + drift ppm
python3 $S/sync.py camera.mp4 zoom_h5.wav --fix-drift --replace-audio -o camera_synced.mp4
```

### "Fix the levels"
```bash
python3 $S/loudness.py final.mp4                    # -14 LUFS / -1 dBTP (YouTube, Spotify)
python3 $S/loudness.py podcast.wav -I -16 --tp -1.5 # Apple Podcasts
python3 $S/loudness.py final.mp4 --measure-only     # report only
```

### "Export for YouTube and Reels, plus a ProRes master"
```bash
python3 $S/export.py final.mp4 --preset youtube
python3 $S/export.py final.mp4 --preset reels --fit crop
python3 $S/export.py final.mp4 --preset prores -o final_master.mov
python3 $S/export.py final.mp4 --preset h265
python3 $S/export.py final.mp4 --preset gif -o preview.gif
```

### Full pipeline in one go
```bash
python3 $S/probe.py raw.mp4 --compact
python3 $S/cut.py raw.mp4 --segments 0:45-3:10,5:00-6:30 -o step1.mp4
python3 $S/fit.py step1.mp4 --duration 60 --aspect 9:16 --fit crop --width 1080 -o step2.mp4
python3 $S/caption.py step2.mp4 --text cues.txt -o step3.mp4
python3 $S/overlay.py step3.mp4 --image logo.png --position top-right --scale 180 -o step4.mp4
python3 $S/loudness.py step4.mp4 -o step5.mp4
python3 $S/export.py step5.mp4 --preset reels -o final_reels.mp4
python3 $S/probe.py final_reels.mp4 --compact     # confirm 60 s, 1080x1920, 30 fps
```
