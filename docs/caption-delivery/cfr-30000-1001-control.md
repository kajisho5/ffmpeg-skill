# Caption delivery: cfr-30000-1001-control

PASS on ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers. Made by `tests/caption_delivery.py` (#729).

- Source: `control_30000_1001.mp4`, 67113977 bytes, sha256 `9425c804ac32ecdb...`, mov,mp4,m4a,3gp,3g2,mj2; generated: `ffmpeg -f lavfi -i testsrc2=size=640x360:rate=30000/1001:duration=600 -f lavfi -i sine=frequency=440:sample_rate=48000:duration=600 -fps_mode cfr -c:v libx264 -preset veryfast -g 60 -pix_fmt yuv420p -c:a aac -b:a 128k control.mp4`
- Video: h264 640x360, r_frame_rate 30000/1001, avg 30000/1001; 17983 packets from 0.0 to 599.9994 s, intervals {'min': 33.366, 'median': 33.367, 'max': 33.367} ms, 1 distinct, CFR
- Audio: 48000 Hz, first packet at -0.021333 s
- Cut: `--accurate` 2.0 to 598.033 s; CFR grid: - (no fps filter: the source is CFR and kept its own rate)
- Delivery: container 596.062133 s, picture 596.062134 s, sound 596.054333 s (asked 596.033 s), 30000/1001 (33.367 ms a frame); sample rates {'source': 48000, 'cut': 48000, 'delivered': 48000}

| cue | requested | adjusted end | delivered | start delta | first frame on screen |
|---|---|---|---|---|---|
| start | 1.003-2.503 | 2.503 | 1.003-2.503 | 0.0 ms | 1.034367 (+31.367 ms) |
| middle | 298.019-299.219 | 299.219 | 298.019-299.219 | 0.0 ms | 298.031067 (+12.067 ms) |
| end | 594.436-594.836 | 595.436 | 594.436-595.436 | 0.0 ms | 594.460533 (+24.533 ms) |

Minimum-duration changes: end: 0.4 s became 1.0 s (caption.py --min-duration (default 1.0 s) extends a shorter cue's end, never past the next cue; --min-duration 0 keeps it)

| check | result | detail |
|---|---|---|
| start cue starts within one delivered frame | PASS | 0.0 ms, one frame is 33.367 ms |
| middle cue starts within one delivered frame | PASS | 0.0 ms, one frame is 33.367 ms |
| end cue starts within one delivered frame | PASS | 0.0 ms, one frame is 33.367 ms |
| start cue is on screen less than a frame after its start | PASS | first frame at 1.034367 s, 31.367 ms after |
| middle cue is on screen less than a frame after its start | PASS | first frame at 298.031067 s, 12.067 ms after |
| end cue is on screen less than a frame after its start | PASS | first frame at 594.460533 s, 24.533 ms after |
| start cue ends within one frame of its adjusted end | PASS | delivered 2.503 s, adjusted 2.503 s |
| middle cue ends within one frame of its adjusted end | PASS | delivered 299.219 s, adjusted 299.219 s |
| end cue ends within one frame of its adjusted end | PASS | delivered 595.436 s, adjusted 595.436 s |
| every cue delivered | PASS | 3 of 3 subtitle packets with text |
| sample rate kept at every step | PASS | {'source': 48000, 'cut': 48000, 'delivered': 48000} |
| delivered picture is CFR on its reported grid | PASS | r_frame_rate 30000/1001, intervals 33.366..33.367 ms |
| delivered picture lasts B - A within one frame | PASS | 596.062134 s against 596.033000 s (+29.134 ms) |
| each tool verified its own output | PASS | {'cut': True, 'caption': True, 'export': True} |
