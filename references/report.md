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

Keep these five lines as the report itself. Include any decision the user needs to make. Never describe a fix you did not run. `verified` covers only what was measured: in `Notes:` name any `unverified` item the user would assume checked. Report a step with `attribution: unresolved`; do not re-run it.

For a standalone edit, deliver the result and the five report lines first. When the host can
present a review and it would help, offer it once in the user's language. In Japanese,
「編集前と編集後を、プレビューで見比べますか？」. Mention waveforms when the host can display
them and the media has an audio track. Prepare the review only after
the user asks for it or accepts the offer. If they already asked for it, check what the host
can present and proceed after the edit and report without a second prompt. When the host
lacks a review view, explain the limitation and share any supported previews the user requested.

Where the host supports side-by-side playback, show the original and edited video when both
have picture. For an audio-only edit, provide playback for the available audio. Where the
host supports waveforms, draw them from the available audio, including a flat waveform for a
silent track. Synchronize playback and waveform seeking when the host can do so using a known
source-to-output time mapping. Otherwise, label and show the two clocks separately. The host owns the
view, numbered edit items, and how it maps feedback to a new edit request. Use ffmpeg-skill to
supply media, measured results, and available preview files, and to execute the requested
changes. Velisa and other callers that own the review handle it through their own workflow.

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
