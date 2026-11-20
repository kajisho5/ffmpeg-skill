# ffmpeg-skill showcase: twelve clips, edited by asking

**Nine of the clips are AI-generated with Google Veo.** The people and places in them do not
exist. Three (`real_*.mp4`: a city at night, a coast at night, fireworks) were shot on a phone by
the maintainer. The slides in the conference demo were made for it, and say so on the slide. Every edit is
a call to one of the skill's scripts, and each call verified what it wrote.

Watch them on the site: <https://kajisho5.github.io/ffmpeg-skill/#showcase>. The conference and
green-screen demos and the reel exist in English and in Japanese; the site plays the one for the
language it is showing.

| Demo | The request | Result (`demos/out/showcase/`) |
|---|---|---|
| A. Rainy night | "Brighten it, cool the white balance a little, clean the noise, keep the neon" | `rain/before_after.mp4` |
| B. Basketball | "Slow the shot down, cut the highlight, make a vertical version" | `basketball/highlight.mp4`, `vertical_9x16.mp4` |
| C. Conference | "One camera on the speaker, the slides are separate: put them side by side, and make a Reels short with captions" | `talk_en/side_by_side.mp4`, `picture_in_picture.mp4`, `cutaway.mp4`, `social_short.mp4` (and `talk_ja/`) |
| D. Green screen | "Remove the green, put her in the conference hall, smaller, on the right, add a title" | `greenscreen/composited_en.mp4` |
| E. Pause | "Take the long pause out" | `pause/tight.mp4` (7.85 s to 5.9 s) |
| F. Horizon | "Level the horizon" | `horizon/straightened.mp4` |
| G. Handheld (phone) | "Take the shake out" | `steady/stabilized.mp4` |
| H. Night shot (phone) | "It is too dark: brighten it and clean the noise" | `lowlight/clean.mp4` |
| I. Fireworks (phone, 60 fps) | "Slow it down" | `slow/slow_motion.mp4` (2.5 times slower, every frame a real one) |

`reel/showreel_en.mp4` and `showreel_ja.mp4` (50 s) join them, and say on the first and last card
what the footage is: AI-generated, and three clips shot on a phone.

## Build

`python3 demos/showcase.py` runs everything and writes `demos/out/showcase/` and the site's copies
in `site/media/showcase_*.mp4` (about nine minutes here). `python3 demos/showcase.py --web`
rewrites only the site's copies. It needs FFmpeg and nothing else: the captions are read from
`demos/footage/veo_talk_*.srt` and the slides are `demos/footage/slide_*.png`.

The commands, with `SRC=demos/footage`:

```bash
# A. colour
python3 scripts/color.py $SRC/veo_rain.mp4 --correct --exposure 0.35 --gamma 1.08 --temperature 7000 -o white_balanced.mp4
python3 scripts/denoise.py white_balanced.mp4 --strength low -o denoised.mp4
python3 scripts/color.py denoised.mp4 --correct --contrast 1.06 --saturation 1.18 -o color_graded.mp4

# B. speed and reframe
python3 scripts/fit.py $SRC/veo_basketball.mp4 --duration 15.7 --method speed --smooth blend -o slow_motion.mp4   # 50%
python3 scripts/cut.py $SRC/veo_basketball.mp4 --start 2 --end 7 --accurate -o shot.mp4
python3 scripts/speedramp.py shot.mp4 --segment 0-1.2:1 --segment 1.2-3.6:0.5 --segment 3.6-5:1 -o highlight.mp4
python3 scripts/fit.py a.mp4 --aspect 9:16 --fit crop --crop-x 0.26 --width 1080 --height 1920 -o a916.mp4   # the player
python3 scripts/fit.py b.mp4 --aspect 9:16 --fit crop --crop-x 0.72 --width 1080 --height 1920 -o b916.mp4   # the hoop
python3 scripts/join.py a916.mp4 b916.mp4 --transition none -o vertical_9x16.mp4

# C. a talk and its slides
python3 scripts/loudness.py $SRC/veo_talk_en.mp4 --lufs=-14 -o speaker.mp4
python3 scripts/insert.py $SRC/slide_en_1.png --duration 4.3 --width 1920 --height 1080 --fps 24 -o slide1.mp4
python3 scripts/join.py slide1.mp4 slide2.mp4 --transition none -o slides.mp4
python3 scripts/fit.py speaker.mp4 --aspect 4:5 --fit crop --width 864 --height 1080 -o speaker_4x5.mp4
python3 scripts/background.py --gradient 0x101114:0x1a2a4a --angle 45 --width 1920 --height 1080 --fps 24 --duration 7.85 -o canvas.mp4
python3 scripts/overlay.py canvas.mp4 --video slides.mp4 --position 48,205 --margin 0 --scale 1192 -o pbp1.mp4
python3 scripts/overlay.py pbp1.mp4 --video speaker_4x5.mp4 --position 1288,205 --margin 0 --scale 584 -o pbp2.mp4
python3 scripts/audio.py pbp2.mp4 --replace speaker.mp4 -o side_by_side.mp4        # overlay.py keeps the main input's sound only
python3 scripts/overlay.py slides.mp4 --video speaker_4x5.mp4 --position bottom-right --margin 40 --scale 330 -o pip1.mp4
python3 scripts/broll.py speaker.mp4 --insert $SRC/veo_hall.mp4 --at 4.4 --duration 2 -o cutaway.mp4
python3 scripts/caption.py short3.mp4 --srt $SRC/veo_talk_en.srt --lang en --animate pop --karaoke --platform reels -o short4.mp4
python3 scripts/export.py short5.mp4 --preset reels -o social_short.mp4
python3 scripts/check.py social_short.mp4 --platform reels

# D. green screen
python3 scripts/overlay.py bg.mp4 --video $SRC/veo_greenscreen.mp4 --chromakey 0x50b64f --chromakey-similarity 0.1 --chromakey-blend 0.05 \
    --position 620,216 --margin 0 --scale-percent 80 -o keyed.mp4
python3 scripts/audio.py branded.mp4 --replace $SRC/veo_greenscreen.mp4 -o composited.mp4

# E. pause
python3 scripts/silence.py $SRC/veo_pause_en.mp4 --threshold -30 --margin 0.12 --min-silence 0.4 -o tight.mp4

# F. horizon
python3 scripts/straighten.py $SRC/veo_sea.mp4 --degrees 5 -o crooked.mp4      # the "before" is made here
python3 scripts/straighten.py crooked.mp4 --degrees=-5 -o straightened.mp4

# G. handheld, H. night shot, I. 60 fps played at 24
python3 scripts/stabilize.py $SRC/real_city.mp4 -o stabilized.mp4
python3 scripts/color.py $SRC/real_sea.mp4 --correct --exposure 1.2 --gamma 1.25 -o lifted.mp4
python3 scripts/denoise.py lifted.mp4 --strength high -o clean.mp4
python3 scripts/fit.py $SRC/real_fireworks.mp4 --duration 8.235 --method speed --fps 24 -o slow_motion.mp4
```

## What the build showed

- **The key colour is read from the clip, and the tolerance is narrow.** The green is `0x50b64f`,
  not `0x00ff00`. A similarity of 0.2 keyed the presenter out with the screen; 0.1 keeps her.
- **The pause needs a higher threshold.** The room sits near -32 dBFS, so the default -35 dB finds
  no silence. `--threshold -30` finds the pause.
- **`overlay.py --video` keeps the main input's sound.** A layer that carries the voice gets it
  back with `audio.py --replace`.
- **The vertical basketball shot is two fixed crops.** There is no subject tracking: the player,
  then the hoop, joined with a hard cut.
- **The crooked horizon is made here.** The generated sea clip is level, so the build tilts it five
  degrees and then levels it; the site says so under the video.
- **Loudness.** The talk measures -17.6 LUFS and is brought to -14.

- **The shake and the dark shot are real.** The generated "shaky" and "noisy" clips came out steady
  and clean, so those two demos use phone footage instead.

## Not shown

Noise reduction on speech has no demo: there is no clip with a noisy voice.
