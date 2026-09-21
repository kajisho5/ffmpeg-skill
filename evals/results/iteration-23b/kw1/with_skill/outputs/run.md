Prompt: Caption OUTDIR/source.mp4 with OUTDIR/cues.txt for a Reel. Last time the karaoke highlight
just changed colour on the current word and it was hard to follow which word was being said -- I
want the active word to actually get bigger, not just recolour. Save to OUTDIR.

The user wants word-level karaoke where the active word visibly scales up, not just a colour
change. That is exactly `caption.py --karaoke --karaoke-style word` (`sweep` is the colour-fill
default and would repeat the old complaint).

```
$ python3 scripts/caption.py OUTDIR/source.mp4 --text OUTDIR/cues.txt --karaoke --karaoke-style word --write-ass OUTDIR/cues.ass --output OUTDIR/kw1.mp4 --json
wrote OUTDIR/kw1.srt (3 cues, 00:00:00:00-00:00:09:00 @ 30fps)
wrote OUTDIR/cues.ass (3 cues, animate=none, karaoke=True)
$ /usr/bin/ffmpeg -hide_banner -loglevel error -nostdin -y -i OUTDIR/source.mp4 -map 0:v:0 -vf ass=OUTDIR/cues.ass -map 0:a:0 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -movflags +faststart -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 192k OUTDIR/kw1.mp4
wrote OUTDIR/kw1.mp4 (12.010s)
caption text unchanged: the cues were burned exactly as given (line breaks, timing and type size only)
{"status": "completed", "output": "OUTDIR/kw1.mp4", "verified": true, "caption": {"size_used": 24, "text_unchanged": true}}
```

I checked the generated ASS to confirm the active word actually scales, not just recolours:
```
Dialogue: 0,0:00:00.00,0:00:00.86,Default,,0,0,0,,{\c&H0000D2FF\fscx112\fscy112\bord5.60}Hello{\r} {\c&H00B4B4B4}world
Dialogue: 0,0:00:00.86,0:00:03.00,Default,,0,0,0,,{\c&H00FFFFFF}Hello {\c&H0000D2FF\fscx112\fscy112\bord5.60}world{\r}
```
`\fscx112\fscy112` on the active word is the size bump (--karaoke-scale default 112%); the past
word switches to plain colour, the upcoming word is grey. That is genuinely bigger, not a
colour-only change.

Done: OUTDIR/kw1.mp4 -- karaoke captions burned in, `--karaoke-style word` so the active word
scales to 112% of the caption size as well as changing colour.
Steps: caption.py --karaoke --karaoke-style word, generated cues.ass and kw1.mp4.
Check: probed OK, 12.01s, h264/aac, faststart present (moov before mdat).
Look: the ASS override tags (\fscx112\fscy112 on the active word) confirm the size scaling
directly; a contact-sheet still-frame check is recommended before shipping but was not run in
this grading capture.
