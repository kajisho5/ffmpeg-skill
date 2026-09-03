#!/usr/bin/env bash
# Generate demo footage from nothing (ffmpeg testsrc2 + synthesized audio),
# run every script in scripts/ on it, and build assets/demo.gif (before/after).
#
#   bash examples/make_demo.sh            # writes examples/out/
#   OUT=/tmp/demo bash examples/make_demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
OUT="${OUT:-$ROOT/examples/out}"
PY="${PYTHON:-python3}"
mkdir -p "$OUT" "$ROOT/assets"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found on PATH" >&2; exit 127; }

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ material
step "1/10 generate source footage (12 s, 1280x720, 30 fps, non-periodic tones)"
TONES="0.6*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\,0.3)+0.4*sin(2*PI*880*t)*gt(sin(2*PI*0.53*t+1)\,0.6)+0.3*sin(2*PI*220*t)*gt(sin(2*PI*0.21*t+2)\,0.7)"
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "aevalsrc='$TONES':s=48000" \
  -t 12 -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k \
  "$OUT/source.mp4"

# external "lav mic" recording that started 2.5 s later than the camera
ffmpeg -y -hide_banner -loglevel error -ss 2.5 -i "$OUT/source.mp4" -vn -c:a pcm_s16le "$OUT/lavmic.wav"

# a logo with transparency
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "color=c=0xff5533@0.85:s=240x90,format=rgba" -frames:v 1 "$OUT/logo.png"

# caption cues in the plain-text format caption.py understands
cat > "$OUT/cues.txt" <<'CUES'
0:00-0:02.5 Shot on nothing but FFmpeg
0:02.5-0:05 Captions | burned in with libass
0:05-0:08 Cut, fit, sync, normalise, export
0:08-0:12 No API keys. No cloud. No dependencies.
CUES

# ------------------------------------------------------------------ pipeline
step "2/10 probe.py"
"$PY" "$SCRIPTS/probe.py" "$OUT/source.mp4" --compact

step "3/10 cut.py  (two segments, lossless copy + concat)"
"$PY" "$SCRIPTS/cut.py" "$OUT/source.mp4" --segments 1-4,7-10 -o "$OUT/01_cut.mp4"

step "4/10 fit.py  (retime to 8 s, pad to 9:16 at 720 px wide)"
"$PY" "$SCRIPTS/fit.py" "$OUT/source.mp4" --duration 8 --aspect 9:16 --fit pad --width 720 -o "$OUT/02_fit.mp4"

step "5/10 caption.py (text cues -> SRT -> burn in)"
"$PY" "$SCRIPTS/caption.py" "$OUT/source.mp4" --text "$OUT/cues.txt" --write-srt "$OUT/cues.srt" \
  --size 26 --bold --position bottom --margin 40 -o "$OUT/03_captioned.mp4"

step "6/10 overlay.py (logo top-right with fade, plus a title)"
"$PY" "$SCRIPTS/overlay.py" "$OUT/03_captioned.mp4" --image "$OUT/logo.png" --position top-right \
  --scale 200 --opacity 0.9 --start 0.5 --end 11.5 --fade 0.5 -o "$OUT/04_logo.mp4"
"$PY" "$SCRIPTS/overlay.py" "$OUT/04_logo.mp4" --text "ffmpeg-skill demo" --position top-left \
  --font-size 40 --box --start 0.5 --end 4 --fade 0.4 -o "$OUT/05_titled.mp4"

step "7/10 sync.py (detect the 2.5 s lav-mic offset, replace camera audio)"
"$PY" "$SCRIPTS/sync.py" "$OUT/source.mp4" "$OUT/lavmic.wav" --json | tee "$OUT/sync.json"
"$PY" "$SCRIPTS/sync.py" "$OUT/05_titled.mp4" "$OUT/lavmic.wav" --replace-audio -o "$OUT/06_synced.mp4"

step "8/10 loudness.py (-14 LUFS, -1 dBTP, two-pass)"
"$PY" "$SCRIPTS/loudness.py" "$OUT/06_synced.mp4" -o "$OUT/07_loudnorm.mp4"

step "9/10 export.py (YouTube, Reels, X, ProRes, H.265)"
"$PY" "$SCRIPTS/export.py" "$OUT/07_loudnorm.mp4" --preset youtube -o "$OUT/08_youtube.mp4"
"$PY" "$SCRIPTS/export.py" "$OUT/07_loudnorm.mp4" --preset reels --fit crop -o "$OUT/08_reels.mp4"
"$PY" "$SCRIPTS/export.py" "$OUT/07_loudnorm.mp4" --preset x -o "$OUT/08_x.mp4"
"$PY" "$SCRIPTS/export.py" "$OUT/07_loudnorm.mp4" --preset prores -o "$OUT/08_prores.mov"
"$PY" "$SCRIPTS/export.py" "$OUT/07_loudnorm.mp4" --preset h265 -o "$OUT/08_h265.mp4"

step "10/10 before/after GIF -> assets/demo.gif"
ffmpeg -y -hide_banner -loglevel error -i "$OUT/source.mp4" -i "$OUT/07_loudnorm.mp4" -filter_complex \
  "[0:v]scale=400:-2,drawtext=text='BEFORE':fontsize=22:fontcolor=white:borderw=2:x=(w-text_w)/2:y=h-34[a];\
   [1:v]scale=400:-2,drawtext=text='AFTER':fontsize=22:fontcolor=white:borderw=2:x=(w-text_w)/2:y=h-34[b];\
   [a][b]hstack=inputs=2,fps=10,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  -t 12 -loop 0 "$ROOT/assets/demo.gif"

step "summary"
"$PY" "$SCRIPTS/probe.py" "$OUT"/0*.mp4 "$OUT"/0*.mov --compact
ls -la "$ROOT/assets/demo.gif"
echo
echo "all scripts ran successfully. outputs in $OUT"
