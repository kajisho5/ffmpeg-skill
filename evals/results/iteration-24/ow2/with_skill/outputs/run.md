# Commands run

```
python3 /home/user/ffmpeg-skill/scripts/probe.py talk.mp4 --json
```
Key output: 1280x720 (16:9), 30 fps, h264/aac mono, duration 10.0s.

```
python3 /home/user/ffmpeg-skill/scripts/render.py --template reels talk.mp4 -o talk_reels.mp4 --json
```
Key output:
```
frame: 1080x1920 from the reels export preset (captions and overlays are sized for delivery)
→ fit.py ... --aspect 9:16 --fit crop --width 1080 --height 1920
    wrote fit.mp4 (10.005s, 1080x1920)
→ loudness.py ... -I -14 --tp -1.0
    measured: -21.8 LUFS, TP -13.1 dBTP, LRA 0.1 LU
    result:   -14.0 LUFS, TP -5.4 dBTP (target -14.0 LUFS, TP <= -1)
→ export.py ... --preset reels --normalize
    wrote talk_reels.mp4 (10.005s, 1080x1920, h264)
check: OK for reels
rendered talk_reels.mp4 via clips → fit → loudness → export → check
```
`check.py --platform reels` (run automatically by the template): all checks PASS except one WARN (no subtitle track — optional, not requested).
Final probe: 1080x1920 (9:16), 30 fps constant, h264 High yuv420p bt709, AAC mono 48kHz, 10.005s, -14.0 LUFS, TP -5.2 dBTP, 2.9 MB.

```
python3 /home/user/ffmpeg-skill/scripts/look.py talk_reels.mp4 --tiles 3x2
```
Output: wrote `talk_reels_sheet.png`. Viewed it — `talk.mp4` is a synthetic test pattern (moving diagonal color bar plus a QR-style marker), not a real talking-head shot, so there is no face/subject to judge as cut off by the centre crop.

# Final message to user

Made a vertical 9:16 Reels version: `/tmp/claude-0/ev24/ow2/talk_reels.mp4` — 1080x1920, 30fps, H.264/AAC, 10.0s, loudness normalized to -14 LUFS (true peak -5.2 dBTP). Used `render.py --template reels`, which framed to 9:16 by centre-cropping (source is 16:9), normalized loudness, exported with the Reels preset, and ran the platform check — all checks passed (one WARN: no subtitle track, which is optional and wasn't requested). Note: `talk.mp4` is a synthetic test-pattern clip (no visible face/subject), so the centre crop has nothing to judge as cut off — if this is actually footage with a subject, let me know and I can re-crop to keep them in frame. There's also a pre-existing `talk_vertical.mp4` in the folder I left untouched since I didn't create it in this job.
