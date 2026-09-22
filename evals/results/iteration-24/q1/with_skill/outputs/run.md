# Task: Crop clip.mp4 to a square at CRF 16

## Commands run (verbatim, in order)

```
python3 /home/user/ffmpeg-skill/scripts/probe.py clip.mp4 --json
```
Key output:
```
"duration": 10.0, "video": {"width": 1280, "height": 720, "display_aspect": "16:9", "fps": 30.0, ...}, "audio": {"codec": "aac", "channels": 1}
```

```
python3 /home/user/ffmpeg-skill/scripts/fit.py clip.mp4 --aspect 1:1 --fit crop --quality 16 -o clip_square.mp4 --dry-run --json
```
Key output:
```
ffmpeg -vf 'scale=720:720:force_original_aspect_ratio=increase,crop=720:720:(in_w-out_w)*0.5:(in_h-out_h)*0.5,setsar=1' ... -c:v libx264 -preset medium -crf 16 ... clip_square.mp4
[dry-run] would write clip_square.mp4 (0.000s, 0x0)
```

```
python3 /home/user/ffmpeg-skill/scripts/fit.py clip.mp4 --aspect 1:1 --fit crop --quality 16 -o clip_square.mp4 --json
```
Key output:
```
wrote clip_square.mp4 (10.005s, 720x720)
"status": "completed", "verified": true,
"probe": {"duration": 10.005, "video": {"width": 720, "height": 720, "display_aspect": "1:1", "fps": 30.0, "codec": "h264"}, "audio": {"codec": "aac", "channels": 1}}
```

```
python3 /home/user/ffmpeg-skill/scripts/look.py clip_square.mp4 --tiles 3x2
```
Key output:
```
contact sheet: 6 frames every 1.67s
wrote ./clip_square_sheet.png
```
Viewed `clip_square_sheet.png`: source is a synthetic test pattern (colour bars, checkerboard, moving diagonal line) with no identifiable off-centre subject, so a centred crop is correct — nothing meaningful is cut off.

## Notes
- No `check.py` platform check run: the user gave no delivery destination (no "for Reels/YouTube/etc."), so this is a plain crop, not an export — per the skill's workflow, no destination + plain edit means keep the source format.
- Centre crop used (default): the source shows no off-centre subject to justify `--crop-x`/`--crop-y`.
- Original `clip.mp4` was left untouched; new file written as `clip_square.mp4`.

## Final message to user

Cropped `clip.mp4` to a square using CRF 16, centred (no off-centre subject visible in the frame to justify otherwise).

- Output: `/tmp/claude-0/ev24/q1/clip_square.mp4`
- 720x720, 10.005 s, 30 fps, H.264 (CRF 16), AAC mono — matches the source's duration/fps/audio, only the frame is cropped from 1280x720 to a centred 720x720 square.
- Look: `/tmp/claude-0/ev24/q1/clip_square_sheet.png` (contact sheet) — source is a synthetic test pattern (bars, checkerboard, moving line), nothing meaningful is cut off by the centre crop.
- Original `clip.mp4` was not modified.
