# Commands run

```
cat /home/user/ffmpeg-skill/SKILL.md | head -100
ls -la /tmp/claude-0/ev24/h1/
cd /tmp/claude-0/ev24/h1/ && python3 /home/user/ffmpeg-skill/scripts/probe.py wide.mp4 --json
```

# Key output (probe.py --json on wide.mp4)

```json
{
  "file": "wide.mp4",
  "duration": 4.0,
  "video": {
    "codec": "hevc",
    "profile": "Main 10",
    "width": 640,
    "height": 360,
    "pix_fmt": "yuv420p10le",
    "bit_depth": 10,
    "hdr": false,
    "hdr_signal": false,
    "bt2020_or_hdr": true,
    "hdr_format": "BT.2020 SDR",
    "dolby_vision": null,
    "color_space": "bt2020nc",
    "color_primaries": "bt2020",
    "color_transfer": "bt709",
    "color_range": "tv"
  },
  "audio": null
}
```

Also checked `/home/user/ffmpeg-skill/docs/design-decisions.md` (per AGENTS.md instructions), which confirms `hdr: false` here is the tool's real, intended meaning: since the skill's 2.0 contract, `hdr` reports a true HDR signal (PQ/HLG/Dolby Vision) only. This file has BT.2020 color primaries but an SDR (bt709) transfer curve — a "BT.2020 SDR" edge case, not actual HDR. That combination is 10-bit and routed through the HDR-capable encode path internally, but it displays and behaves as SDR.

# Final message to user

wide.mp4 is **not HDR** — it's safe to send to an SDR-only client as-is.

Details from probing it: it's HEVC Main 10 (10-bit, 640x360, yuv420p10le), and its color primaries are tagged BT.2020, but its transfer characteristic is `bt709` (the standard SDR gamma curve), and there's no PQ/HLG/Dolby Vision signal (`dolby_vision: null`). So this is a "BT.2020 primaries with an SDR transfer" file — an edge case, not true HDR (PQ/HLG). No `color.py --to-sdr` conversion is needed for delivery.

One caveat: it's 10-bit (`yuv420p10le`), which some older SDR-only playback/editing systems can be picky about even though the color signal itself is SDR. If your client's pipeline specifically requires 8-bit, let me know and I can convert it (e.g. via `color.py` or a re-encode to 8-bit h264) — but purely on the HDR question, this file will display correctly as SDR.
