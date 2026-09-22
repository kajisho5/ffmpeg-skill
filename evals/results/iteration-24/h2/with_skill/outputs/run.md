# Commands run

```
python3 /root/.claude/skills/ffmpeg-skill/scripts/probe.py iphone.mp4 --json
```
Key output:
```
"video": {
  "codec": "hevc", "profile": "Main 10", "width": 640, "height": 360,
  "hdr": true, "hdr_signal": true, "bt2020_or_hdr": true,
  "hdr_format": "HDR10/PQ", "color_space": "bt2020nc",
  "color_primaries": "bt2020", "color_transfer": "smpte2084", "pix_fmt": "yuv420p10le"
},
"audio": null
```
Confirms iphone.mp4 is HDR10/PQ (BT.2020, SMPTE2084 transfer) — this is why it looks washed
out/dull on a laptop screen that isn't HDR-aware: SDR displays and most players render PQ-tagged
footage without the required tone mapping.

```
python3 /root/.claude/skills/ffmpeg-skill/scripts/color.py iphone.mp4 --to-sdr -o iphone_sdr.mp4 --json-brief
```
Key output:
```
$ ffmpeg ... zscale=tin=smpte2084:pin=bt2020:...,tonemap=tonemap=hable:desat=0,... -c:v libx264 ... -colorspace bt709 -color_primaries bt709 -color_trc bt709 ... iphone_sdr.mp4
wrote iphone_sdr.mp4 (4.000s, 640x360, bt709/bt709, sdr)
{"status": "completed", "output": "iphone_sdr.mp4", "verified": true,
 "summary": {"duration_s": 4.0, "width": 640, "height": 360, "fps": 30.0, "vcodec": "h264"}}
```

```
python3 /root/.claude/skills/ffmpeg-skill/scripts/check.py iphone_sdr.mp4 --json-brief
```
Key output (no destination platform was given, so YouTube's generic spec was assumed;
judgement rows are WARN not FAIL without a named platform):
```
10 checks, 0 failed, 3 warnings
PASS duration, aspect, fps, vfr, video codec, colour (bt709/bt709), file size
WARN resolution 640x360 (source is only 640x360 — inherent to the original file, not something re-encoding can fix)
WARN subtitles none (optional, not requested)
WARN audio none (source iphone.mp4 has no audio stream at all — nothing to carry over)
```

```
python3 /root/.claude/skills/ffmpeg-skill/scripts/look.py iphone_sdr.mp4 --tiles 3x2
```
Output: `iphone_sdr_sheet.png` (viewed). Colour bars, checkerboard and moving line render as
normal, correctly saturated colours (not washed out/grey) after the SDR conversion — the fix
worked. This is a synthetic test clip (colour bars + moving line + checkerboard), not real
camera footage, but the same HDR->SDR mechanism applies regardless of content.

# Final message to user

Done: iphone_sdr.mp4 — 4.00 s, 640x360, 30 fps, H.264 (bt709/bt709, SDR), no audio (source had none)
Steps: probe (found HDR10/PQ, BT.2020) -> color.py --to-sdr (tonemap to standard SDR/Rec.709)
Check: youtube (assumed, no platform given) — 7/10 pass, 3 warnings: resolution 640x360 is the source's native size (upscaling won't add real detail), no subtitles (not requested), no audio (iphone.mp4 has no audio track to begin with)
Look: iphone_sdr_sheet.png — colours now render as normal saturated colour instead of the dull/grey look you get from HDR footage on a non-HDR screen
Notes: iphone.mp4 was tagged HDR10/PQ (BT.2020 + SMPTE2084) — that's exactly why it looked washed out on your laptop: SDR screens/players don't apply the required HDR tone curve. iphone_sdr.mp4 is standard SDR H.264/Rec.709, so it'll look correct and consistent on any laptop, phone, or platform you post it to. If you want it resized/exported for a specific destination (e.g. Reels, YouTube), just say where and I'll run the matching template.
