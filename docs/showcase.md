# ffmpeg-skill showcase: four clips, edited by asking

**The footage in these videos is AI-generated with Grok (Grok Imagine).** The people and places do
not exist. The showreel says so on its first and last card.

Four clips (736x400, 24 fps, 15 s each), edited
with ffmpeg-skill 4.0.0 only. Every command below is one of the skill's tools; an agent picks them
from a plain request. 

| Demo | Ask | Result |
| --- | --- | --- |
| A. Rainy night | "Brighten it, cool the white balance a little, clean the noise, keep the neon" | `demos/out/showcase/rain/before_after.mp4` |
| B. Basketball | "Slow the shot down, cut the highlight, make a vertical version" | `demos/out/showcase/basketball/highlight.mp4`, `vertical_9x16.mp4` |
| C. Conference | "Make a Reels short of this talk with captions and our logo" | `demos/out/showcase/talk/social_short.mp4` |
| D. Green screen | "Remove the green, put her on a dark gradient, smaller, on the right, add a title" | `demos/out/showcase/greenscreen/composited.mp4` |

`showreel.mp4` (40 s) joins all four. The site plays them: <https://kajisho5.github.io/ffmpeg-skill/#showcase>.

## Reproduce

`python3 demos/showcase.py` runs everything below and writes `demos/out/showcase/` and the site's
copies in `site/media/` (about three and a half minutes on a laptop-class machine). The commands,
with `SRC=demos/footage` and the clips `grok_rain.mp4`, `grok_basketball.mp4`,
`grok_greenscreen.mp4` and `grok_talk.mp4`:

### A. Colour

```bash
python3 scripts/color.py $SRC/grok_rain.mp4 --correct --exposure 0.45 --gamma 1.1 -o exposure_corrected.mp4
python3 scripts/color.py $SRC/grok_rain.mp4 --correct --exposure 0.45 --gamma 1.1 --temperature 7000 -o white_balanced.mp4
python3 scripts/denoise.py white_balanced.mp4 --strength low -o denoised.mp4
python3 scripts/color.py denoised.mp4 --correct --contrast 1.06 --saturation 1.22 -o color_graded.mp4
python3 scripts/grid.py before.mp4 after.mp4 --cols 2 --rows 1 --cell-width 736 --cell-height 400 --fps 24 --audio-from 1 -o before_after.mp4
```

### B. Speed, highlight, vertical

```bash
python3 scripts/fit.py $SRC/grok_basketball.mp4 --duration 30.08 --method speed --smooth blend -o slow_motion.mp4   # 50%
python3 scripts/fit.py $SRC/grok_basketball.mp4 --duration 7.52 --method speed -o fast_motion.mp4                   # 200%
python3 scripts/cut.py $SRC/grok_basketball.mp4 --start 5.5 --end 13.5 --accurate -o shot.mp4
python3 scripts/speedramp.py shot.mp4 --segment 0-1.5:1 --segment 1.5-5.5:0.5 --segment 5.5-8:1 -o highlight.mp4
# vertical: the player, then the hoop (no tracking: two fixed crops, joined with a hard cut)
python3 scripts/cut.py $SRC/grok_basketball.mp4 --start 5.5 --end 9.2 --accurate -o a.mp4
python3 scripts/cut.py $SRC/grok_basketball.mp4 --start 9.2 --end 13.5 --accurate -o b.mp4
python3 scripts/fit.py a.mp4 --aspect 9:16 --fit crop --crop-x 0.5  --width 720 --height 1280 -o a916.mp4
python3 scripts/fit.py b.mp4 --aspect 9:16 --fit crop --crop-x 0.84 --width 720 --height 1280 -o b916.mp4
python3 scripts/join.py a916.mp4 b916.mp4 --transition none -o vertical_9x16.mp4
```

### C. Talk to short

```bash
python3 scripts/loudness.py $SRC/grok_talk.mp4 --lufs=-14 -o audio_normalized.mp4          # -11.4 -> -14.0 LUFS
python3 scripts/silence.py audio_normalized.mp4 -o tight.mp4                        # 15.0 s -> 10.3 s
python3 scripts/fit.py tight.mp4 --aspect 9:16 --fit crop --crop-x 0.17 --width 720 --height 1280 -o tight916.mp4
python3 scripts/caption.py tight916.mp4 --srt $SRC/grok_talk_short.srt --animate pop --karaoke --platform reels -o cap916.mp4
python3 scripts/graphics.py cap916.mp4 --template chapter --title "AI x Video Editing" --position top-left --platform reels --end 4.5 -o gfx916.mp4
python3 scripts/overlay.py gfx916.mp4 --image brand/app-icon-dark.png --position top-right --scale 96 --platform reels -o logo916.mp4
python3 scripts/export.py logo916.mp4 --preset reels -o social_short.mp4
python3 scripts/check.py social_short.mp4 --platform reels                          # 0 FAIL
```

The cue file was written once by `caption.py tight916.mp4 --transcribe --language en --model small`
(faster-whisper, on this machine; nothing is sent to a service) and is committed, so the build needs
no speech engine. Two models (small and base) gave the same words.

### D. Green screen

```bash
python3 scripts/background.py --gradient 0x1a2a4a:0x0b0d12 --angle 60 --width 736 --height 400 --fps 24 --duration 15.04 -o bg.mp4
python3 scripts/overlay.py bg.mp4 --video $SRC/grok_greenscreen.mp4 --chromakey 0x1fbe25 --chromakey-similarity 0.18 --chromakey-blend 0.08 \
        --position 260,96 --margin 0 --scale-percent 76 -o comp1.mp4
python3 scripts/overlay.py comp1.mp4 --text "Green screen, replaced" --position 40,150 --font-size 30 -o comp2.mp4
python3 scripts/overlay.py comp2.mp4 --image brand/app-icon-dark.png --position top-left --scale 56 -o comp3.mp4
python3 scripts/audio.py comp3.mp4 --replace $SRC/grok_greenscreen.mp4 -o composited.mp4            # the layer's sound is not kept by overlay.py
```

## What is not here

- No automatic subject tracking: a vertical crop has a fixed position per segment.
- The captions were checked by two models agreeing word for word, not by a person listening.
