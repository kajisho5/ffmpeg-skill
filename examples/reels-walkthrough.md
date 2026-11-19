# From a source recording to subtitled Reels

Run these commands in Bash from the repository root with Python 3 and FFmpeg on PATH.
The bundled source is an AI-generated talking-head clip. The three English captions
use its cached faster-whisper word timings, grouped into phrases for this edit.
The walkthrough needs FFmpeg's subtitles filter and an installed font for English.

```bash
set -e
OUT="$(mktemp -d)"
SOURCE="demos/footage/ai_talk_en.mp4"

python3 scripts/probe.py "$SOURCE" --compact
python3 scripts/cut.py "$SOURCE" --start 0 --end 9.4 --accurate \
  -o "$OUT/cut.mp4" --json > "$OUT/cut.json"
python3 scripts/fit.py "$OUT/cut.mp4" --aspect 9:16 --width 1080 --height 1920 \
  --fit blur --output "$OUT/vertical.mp4" --json > "$OUT/fit.json"
python3 scripts/caption.py "$OUT/vertical.mp4" --srt examples/reels-walkthrough.srt \
  --platform reels --language en -o "$OUT/captioned.mp4" --json > "$OUT/caption.json"
python3 scripts/export.py "$OUT/captioned.mp4" --preset reels --normalize \
  -o "$OUT/reels.mp4" --json > "$OUT/export.json"
python3 scripts/check.py "$OUT/reels.mp4" --platform reels --content \
  --json > "$OUT/check.json"
python3 scripts/look.py "$OUT/reels.mp4" --at 1.8 --safe reels -o "$OUT/caption-frame.png"
printf 'Delivery %s\nCheck report %s\nReview image %s\n' \
  "$OUT/reels.mp4" "$OUT/check.json" "$OUT/caption-frame.png"
```

The cut starts at zero, so the cached cue times remain on the edited timeline. The
reframe keeps the whole source picture over a blurred fill in the 1080×1920 frame.
The caption step draws subtitles after that geometry is known. The Reels preset
measures the exported audio and applies correction if needed. Open `check.json`
to read the platform and content rows, including warnings.

The example run delivered 1080×1920 at 30 fps, approximately 9.43 seconds, with
three burned-in cues and a measured −14.0 LUFS after correction. The subtitle
stream row warned that there was no separate track. The first cue is visible in
`caption-frame.png`, which shades the app's UI zones for inspection.

For a fresh source, replace `--srt examples/reels-walkthrough.srt` with
`--transcribe --write-srt "$OUT/captions.srt"` in the caption command. Run
`python3 scripts/_contract.py doctor --json` to check for a local speech engine first.
The engine may fetch model weights on its first transcription. Review the cues and
watch and listen to the finished video before delivery. The caller chooses the cut
range and approves the captions, framing and audio.
