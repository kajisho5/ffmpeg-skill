# Device and format notes (from the real-device corpus)

What `probe.py` will show and what to do about it. Learned from running the
toolchain on real files, not from spec sheets.

| Source | What you see | What it means for the edit |
|---|---|---|
| iPhone (iOS 15+) HDR video | `hdr_format: Dolby Vision profile 8`, HLG transfer, 10-bit HEVC, `variable_frame_rate_suspected: true`, `rotation` -90/90 for portrait, extra timecode/metadata tracks | Every re-encode keeps HDR automatically (HEVC Main10 + tags). Use `color.py --to-sdr` first only when the destination is SDR-only (X, LinkedIn, most web players). Only the first audio track is used. Lossless cuts fall back to accurate cuts because of VFR. |
| iPhone SDR / older | HEVC or H.264 4K60, mono AAC | Mono audio: `audio.py --stereo` before music/ducking if the deliverable expects stereo. |
| GoPro HERO | HEVC 4K 10-bit **SDR** (`hdr: false`, `yuv420p10le`), stereo, GPMF data track | 10-bit does not mean HDR; do not tone-map. Re-encodes are 8-bit H.264 unless the user wants a 10-bit master (`export.py --preset prores`). |
| DJI drone | HEVC 4K 50/60, **no audio** | Audio-dependent steps (sync, silence, loudness, ducking) do not apply; add narration or music with `audio.py --replace/--music`. D-Log profiles look flat: `probe.py --analyze` -> `looks_like_log` -> `color.py --lut`. |
| Android screen recording | H.264, odd sizes (720x1600, 1298x1080), 18-120 fps, strongly VFR | Conform with `fit.py --fps 30` (or 60) before anything else; check aspect with `check.py`. |
| Zoom / Teams recordings | H.264 720p-1080p, low bitrate, long, often VFR | `silence.py` and `scenes.py` work; expect long processing on hour-long files; `--fast` for previews. |
| OBS (mkv) | H.264/HEVC, sometimes multiple audio tracks, VFR when the source dropped frames | Only the first audio track is used; remux to mp4 first if a client needs it (`export.py`). |
| HDR10 masters / test patterns | PQ (`smpte2084`), BT.2020, MaxCLL/MDL metadata, 10-bit | `color.py --to-sdr --tonemap hable` (or `bt2390` for broadcast); tone-mapping 4K runs about 1x realtime, so cut first. |
| Broadcast / ProRes .mov | ProRes 422/4444, PCM audio, 24p or 25p | Stream copy where possible; `export.py --preset prores` for masters; `check.py --platform broadcast` (EBU R128 -23 LUFS). |
| Film / web downloads | H.264 with MP3 or AAC, 24p, letterboxed (1280x534) | `fit.py --aspect` pads; `check.py` flags non-standard aspect. |

Rules of thumb that came out of this:

- 10-bit is a container property, HDR is a colour property. Trust `hdr`, not `bit_depth`.
- Anything from a phone or a screen recorder is VFR until proven otherwise; every re-encoding script conforms it, but plan accurate cuts.
- 4K 10-bit re-encodes cost 20-25 s per 6 s of footage on a laptop-class CPU: cut first, then process, and use `--fast` while iterating.
- Files longer than 10 minutes: never run a whole-file tone-map or interpolation; work on cuts.
