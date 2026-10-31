# Report format, in full

The long form of SKILL.md's Report format: the language rules, the Japanese example and the
failure, refusal and partial-result rules.

Reply in the language the request is written in — subtitles in another language are still reported in the request's language. Keep the labels (`Done:`, `Steps:`, `Check:`, `Look:`, `Notes:`) in English; everything else is the user's language. Never drift because the job was short or failed: even a one-line "file does not exist". A mid-conversation switch follows the user's latest message.

Finish every job with this shape (numbers from `--json` or `probe.py`/`check.py`, not memory):

```
Done: final.mp4 — 59.98 s, 1080x1920, 30 fps, H.264, AAC stereo, -14.1 LUFS
Steps: cut 0:12-1:12 (lossless) -> fit 9:16 crop -> captions (pop, karaoke) -> loudness -14 -> export reels
Check: reels — all 12 checks pass (verified: true)
Look: final_sheet.png (captions inside the safe area, logo top-right)
Notes: source was VFR, conformed to 30 fps; audio was mono, made stereo
```

The same five lines for a Japanese request:

```
Done: final.mp4 — 59.98 秒、1080x1920、30 fps、H.264、AAC ステレオ、-14.1 LUFS
Steps: 0:12-1:12 をカット（無劣化）-> 9:16 にクロップ -> 字幕（ポップ、カラオケ）-> ラウドネス -14 -> Reels 書き出し
Check: reels — 12 項目すべて合格（verified: true）
Look: final_sheet.png（字幕はセーフエリア内、ロゴは右上）
Notes: 元は VFR だったので 30 fps に揃えた。音声はモノラルだったのでステレオにした
```

Keep it to those five lines plus anything the user must decide. Never describe a fix you did not run. `verified` covers only what was measured: in `Notes:` name any `unverified` item the user would assume checked. Report a step with `attribution: unresolved`; do not re-run it.

When a step fails, replace `Done:` with `Failed:` and keep the rest honest:

```
Failed: color.py --lut grade.cube exited 1 — ffmpeg: "Unable to parse LUT file" (the .cube is not a valid LUT)
Steps: probe -> color (failed); nothing written
Check: nothing to verify
Look: not needed
Notes: send a valid .cube, or say if you want the clip left as is
```

Those filler lines are sentences, not labels: the same report for a Japanese request ends
`Check: 検証するものなし` / `Look: 不要`.

A refusal uses the same shape: `Failed:` names what was refused and why, `Steps:` lists what did run, `Look: not needed`. A partial result is `Done:` with the shortfall in `Notes:`; a refusal that still delivers something is `Failed:` — never a third label like `Done (partially):`. A failure's `--json` is `status: failed` plus `error.kind`, `error.message` and `error.hint`: quote the message in `Failed:`, never paraphrase it, and the hint in `Notes:`.
