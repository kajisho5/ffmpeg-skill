# Changelog

> `main` moves ahead of the last published npm/GitHub release; a dependent repo should pin a tagged version, not `main`. See README § Development, "Releasing".

## Unreleased

- README gains a "Gotchas and best practices" section for human readers: VFR, keyframe snapping, HDR, loudness targets, caption order, 9:16 crops, fonts, silence threshold, sync confidence, plans; every flag named is checked against the scripts' `--help`.
- `--dry-run` writes no side files either: `silence.py --edl`, `scenes.py --edl` and the `.ass` that `caption.py --animate/--karaoke` generates were written while stderr said "would write". The contract's note for these tools was right; the code was not.
- SMPTE `hh:mm:ss:ff` times resolve with the input's fps in every tool that takes a time (`overlay`, `graphics`, `look`, `insert`, `background`, `fit`, `loop`), and a bad time is a `kind: input` failure document naming the flag instead of a traceback (`time_arg()` in `_common.py`; `cut`/`freeze` already did this).
- `pad.py --start/--end` accept the shared time grammar (`1:30`) like every other tool; junk is a `kind: input` refusal, not an argparse exit 2 without JSON.
- `cut.py --segments` refuses an output that is the same file as its input. The run() guard compares each ffmpeg command's `-i` with its output, and the final concat's only `-i` is the temp list file, so `-o in.mp4` replaced the source with the join (fourth review, P0); the single-segment path already refused.
- The dry-run exception list in SKILL.md and `docs/contract.md` names `silence`, `loudness` and `stabilize` again; the pinning test now checks the sentence that states the exception in all three docs, not "the name appears somewhere in the file", which is how the list drifted twice.
- Release resolver: a PR labelled `dependencies` is never releasable, even when Dependabot also labelled it `major` (its bump of actions/checkout 4→7 was the action's major, not this package's, and blocked the 1.4.9 release).

## 1.4.8

_Automated release: version and notes generated from pull requests merged since 1.4.7._

- Multi-segment `cut.py` writes its concat list with forward slashes, so a Windows temp path (`C:\Users\...`) is not read as escape sequences by the concat demuxer; `sequence.py` shares the helper.
- SMPTE `hh:mm:ss:ff` parsing counts frames per timecode-second like `fmt_smpte_time()` does, so the two agree at 29.97/59.94 over long files. `cut.py` passes the input's fps (so SMPTE works there) and refuses a bad time as `kind: input`; `freeze.py --at` accepts the shared time grammar.
- `caption.py --transcribe`: faster-whisper runs under `--timeout` like the CLI engines; an old whisper.cpp binary named `main` is used when it lives in a whisper directory.
- `bin/install.js` moves the old install aside and back on a failed swap, so an upgrade never leaves the target empty; the npm package and installer ship `docs/contract.md`.
- `join.py` goes 10-bit HEVC when any input is HDR (not only the first); `broll.py` keeps a 10-bit cutaway over an HDR main clip; `grid.py` notes that an HDR input is composited into an 8-bit SDR grid.
- `look.py -o` names the file for a single `--at` when it carries an image extension; `audio.py` refuses `--mono` with `--stereo` and an out-of-range `--denoise-strength`; `render.py` refuses a negative clip speed; `batch.py` also picks up `.ogg`/`.opus`/`.ts`/`.gif`/`.aac`/`.aiff`; `report.py` shows a 0 s duration as 0 s; `ffmpeg_version()` has a probe timeout.
- Windows: `default_font_file()` looks for the requested family in `C:\Windows\Fonts` (and common CJK system fonts for a CJK request) before falling back to Arial.
- fix: third audit's confirmed items — Windows concat lists, SMPTE round trip, ASR timeout, installer swap, HDR joins, argument checks, shipped docs (#181)

## 1.4.7

_Automated release: version and notes generated from pull requests merged since 1.4.6._

- `--dry-run` plans rest on real measurements: `silence.py`, `loudness.py`, `check.py` and `stabilize.py` run their measurement passes (silencedetect, loudnorm pass 1, vidstabdetect) under `--dry-run` and skip only the write. Before, a dry run reported 0 silences, a made-up -20 LUFS, an unmeasured loudness row and no stabilisation pass. The contract lists them as `analysis_only`.
- `render.py`'s check stage and `report.py`'s look/loudness/check children receive the shared flags (`--timeout`, `--overwrite`, `--fast`, `--dry-run`); `render.py`'s failure document carries the output probe.
- `cropdetect.py` skips a sampled window ffmpeg cannot decode and measures the rest; only when every window fails is it `kind: ffmpeg`.
- `caption.py --text`/`--srt` and `batch.py`'s `recipe.project` read through the guarded reader: a missing, directory or non-UTF-8 file is a `kind: input` refusal naming the flag.
- fix: dry-run plans rest on real measurements; shared flags reach every child; guarded cue reads; cropdetect skips an undecodable window (#179)

## 1.4.6

_Automated release: version and notes generated from pull requests merged since 1.4.5._

- `docs/design-decisions.md` lists behaviours that look like bugs but are decisions (timeout 0, dry-run measurements, BT.2020 handling, overwrite policy, `speed: 0`, packaging), each with its rationale and pinning test; `AGENTS.md`, CONTRIBUTING and the bug template point reviewers to it first.
- Docs: README no longer claims media ffmpeg calls have no timeout; tool counts read 42 everywhere (the count test now catches the "all N by" / "same N names" phrasings); `docs/contract.md` lists every dry-run exception; the error-kind list is identical in SKILL.md, README and the contract; SKILL.md states the dry-run exceptions once and moves the Windows drawtext story to `references/ci-platform-pitfalls.md`; CODE_OF_CONDUCT.md added.
- The npm package ships `references/scripts.md`, `devices.md` and `ci-platform-pitfalls.md` only; the maintainer diary `process-pitfalls.md` stays in the repository. Internal: the `Context` dict-style shims are gone, every call site uses attributes.
- Every sibling-script run (`render.py`/`batch.py`/`report.py` stages and the MCP server's dispatch) has an outer wall-clock ceiling of 4x the per-ffmpeg `--timeout` plus 60 s, so a child hung for a reason other than ffmpeg is killed and reported as `kind: timeout`. The MCP caller's `timeout` argument sets both.
- `scenes.py` and `sync.py` share one PCM decode and RMS-envelope implementation (`decode_pcm_mono`/`rms_envelope` in `_common.py`); results are unchanged.
- fix: outer wall-clock ceiling on every sibling-script run; scenes and sync share one PCM decode and envelope (#178)
- docs: add design-decisions record and AGENTS.md (#180)
- chore: attribute-only Context; ship only the agent-facing references in the npm package (#177)
- docs: remove the contradictions the 1.4.2 review found; count test catches more phrasings; code of conduct (#176)

## 1.4.5

_Automated release: version and notes generated from pull requests merged since 1.4.4._

- `--preset` is an argparse choice of the x264 presets in every encoding tool (the contract and MCP schema carry the enum) and `--crf` is range-checked (0-51) before ffmpeg runs; a typo is a `kind: input` refusal, not an encoder error.
- `silence.py` says why nothing was found: with zero silences the result carries a `hint` with the track's measured mean/peak level and a threshold to try. `cut.py` names the nearest keyframes (`nearest_keyframes`) when a lossless cut had to re-encode, so the caller can move the cut instead. Failure JSON may carry `error.hint`.
- `broll.py --pad-color` is validated like every other colour flag (it was spliced into the filter graph unchecked; a value containing `,` could append a filter).
- The MCP server attaches the tool's own failure document as `structuredContent` on a failed call, so a caller reads `error.kind`/`code` instead of parsing prose.
- `render.py` re-raises a stage's own failure (kind, exit code, hint, `stage`) instead of reporting every child failure as `kind: input`; `report.py` shows "check could not run" instead of crashing when `check.py` fails to run; `--commands`/`--notes`/`--chapters` files that are missing or not UTF-8 are a `kind: input` refusal, not a traceback.
- SKILL.md: a failed or refused report keeps the five labels (`Look: not needed (nothing written)`), quotes `error.hint` in `Notes:`, and several open questions are asked as one bundled proposal instead of one per turn.
- fix: validate --preset/--crf before ffmpeg; silence.py and cut.py say what to change next; failure JSON may carry a hint (#175)

## 1.4.4

_Automated release: version and notes generated from pull requests merged since 1.4.3._

- `check.py`, `render.py` (check stage), `batch.py` and `verify.py` report a failed result as `status: failed` with the new `kind: verification` (`VERIFICATION_FAILED`, exit 1) and keep their detail fields (`checks`, `check`, `results`, `files`); before, they printed `status: completed` next to a non-zero exit code.
- `scenes.py`, `cropdetect.py`, `sync.py`, `caption.py --transcribe` and the colour-level probe run their ffmpeg measurements under `--timeout` and report a decode failure as `kind: ffmpeg` instead of an empty result or a traceback; the transcribe temp directory is removed afterwards.
- `render.py` and `batch.py` forward `--timeout` and `--overwrite` to every stage, not only `--fast`/`--dry-run`.
- fix: failed check/render/batch/verify report status failed; analysis runs get --timeout; render/batch forward the shared flags (#174)

## 1.4.3

_Automated release: version and notes generated from pull requests merged since 1.4.2._

- A failed ffmpeg run no longer costs the caller an output file that existed before the run. Such a file is now written through a hidden sibling temp file and replaced only on success; on failure the original is untouched and the temp removed. Previously the partial-output cleanup deleted it (any FFmpeg), and on FFmpeg 5.x ffmpeg itself truncated it to 0 bytes before a filter error, with or without `--overwrite`.
- `--timeout` is enforced under `--progress`: the deadline is checked on a clock, so a deadlocked ffmpeg that prints no progress lines is killed and reported as `kind: timeout` instead of being waited on forever.
- fix: a failed run never costs the caller an existing output; --timeout is enforced under --progress (#173)
- ci(release): bump on the tip of main so a merge during the run cannot reject the push (#172)

## 1.4.2

_Automated release: version and notes generated from pull requests merged since 1.4.1._

- `color.py --correct` no longer desaturates bt709-tagged sources: the RGB stages are wrapped in explicit, matching YUV<->RGB conversions instead of libavfilter's auto-inserted pair, which used bt709 one way and bt601 the other (#159).
- docs(pitfalls): a literal skip-ci marker in a PR body silences the squash merge (#171)
- fix(color): --correct no longer desaturates bt709-tagged sources (#167)

## 1.4.1

_Automated release: version and notes generated from pull requests merged since 1.4.0._

- Every tool takes `--timeout SECONDS` (default 1800, `FFMPEG_SKILL_TIMEOUT`): a single ffmpeg run past the limit is killed, its partial output removed, and the failure reported as `kind: timeout` (exit 124) instead of hanging the caller.
- Every tool takes `--overwrite`. An output path that already exists (and was not written by this run) now prints a warning; `FFMPEG_SKILL_NO_OVERWRITE=1` makes it a refusal today, and 2.0 will refuse by default.
- `audio.py --music` (with or without `--duck`/`--music-loop`) no longer shortens the video: the mixed track is padded/trimmed to the source duration and a video-keeping output never uses `-shortest` (#164).
- fix(audio): a music bed never shortens the video; pad the mix to the source duration (#165)
- ci(release): push the bump commit with RELEASE_PUSH_TOKEN so the main ruleset lets it through (#170)
- fix(release): fold hand-written Unreleased notes into the bump instead of asserting the placeholder (#166)
- fix: --timeout kills a hung ffmpeg and reports it; --overwrite guards existing outputs (#163)
- evals: iteration 5 against 1.4.0 (24-set, exec set, trigger set) and README row (#162)
- docs: badges for CodeQL, downloads, stars, last commit and the tested FFmpeg/Python versions (#160)

## 1.4.0

_Automated release: version and notes generated from pull requests merged since 1.3.1._

- Add broll.py: cut away to a B-roll clip for a window and come back, A's timeline untouched (#158)

## 1.3.1

_Automated release: version and notes generated from pull requests merged since 1.3.0._

- fix: quote SKILL.md's description so the frontmatter is valid strict YAML (#161)

## 1.3.0

_Automated release: version and notes generated from pull requests merged since 1.2.0._

- Add metadata.py: container chapter markers and title/artist/comment tags, streams copied (#157)

## 1.2.0

_Automated release: version and notes generated from pull requests merged since 1.1.1._

- Add --pad-fill blur to fit.py and export.py: blurred frame behind the letterbox bars (#155)

## 1.1.1

_Automated release: version and notes generated from pull requests merged since 1.1.0._

- Fix three FFmpeg 5.x incompatibilities and run CI on FFmpeg 5.1.1 and 7.1 (#156)
- ci(release): tag the bump commit, not the commit that triggered the run (#154)
- chore(release): bump version to 1.1.0

## 1.1.0

_Automated release: version and notes generated from pull requests merged since 1.0.4._

- Add a Claude Code plugin manifest so the repo installs with `claude plugin install` (#153)
- chore(tests): cover verify.py's full plan and the MCP server's error paths (#152)
- ci: run the test suite on Python 3.13 too (Ubuntu only) (#151)
- build(deps): bump release-drafter/release-drafter from 6 to 7 (#132)
- docs: state the 1.x stability guarantee and deprecation policy, pin the tool surface, verify each npm publish (#149)
- ci(release): resolve the next version ourselves; a chore-only merge really releases nothing (#150)

## 1.0.4

_Automated release: version and notes generated from pull requests merged since 1.0.3._

- chore(release): never auto-bump the major, and stop releasing chore-only merges (#145)

## 1.0.3

_Automated release: version and notes generated from pull requests merged since 1.0.2._

- Fix the Codex install path, a stale SKILL.md tool count, and two silent CI holes (#136)

## 1.0.2

_Automated release: version and notes generated from pull requests merged since 1.0.1._

- build(deps): bump dependabot/fetch-metadata from 2 to 3 (#135)

## 1.0.1

_Automated release: version and notes generated from pull requests merged since 1.0.0._

- build(deps): bump actions/setup-node from 4 to 7 (#134)

## 1.0.0

**Accidental major.** 1.0.0, 1.0.1 and 1.0.2 contain no user-facing or compatibility change over 0.16.15 -- they are three routine CI dependency bumps that a release-automation bug labelled `major` (see `references/process-pitfalls.md`, fixed in #145). They are left published because npm never lets a version number be reused; treat 1.0.x as 0.16.x under a different name.

_Automated release: version and notes generated from pull requests merged since 0.16.15._

- build(deps): bump actions/upload-artifact from 4 to 7 (#133)

## 0.16.15

_Automated release: version and notes generated from pull requests merged since 0.16.14._

- build(deps): bump actions/setup-python from 5 to 7 (#131)

## 0.16.14

_Automated release: version and notes generated from pull requests merged since 0.16.13._

- Add Dependabot, CodeQL, PR-labeling, CI concurrency, and more (#130)

## 0.16.13

_Automated release: version and notes generated from pull requests merged since 0.16.12._

- Auto-bump the release version too, not just tag/release/npm publish (#129)

## 0.16.12 — verify the fully-automated release pipeline end to end

No functional code changes. `.github/workflows/release.yml` was rewritten to
auto-create the git tag, GitHub Release, and npm publish on every push to
`main` that bumps `package.json`'s version, but the first real run of it
(for 0.16.11) never got an npm publish to succeed: the `NPM_TOKEN` secret
wasn't valid yet, and once the tag existed the workflow's own guard
prevented a clean re-attempt under the same version. This bump exists
solely to give the pipeline a fresh, untagged version to run against so
the whole chain — tag, GitHub Release, and npm publish — can be verified
working in one pass.

## 0.16.11 — fix a contract/reality mismatch on AAC, three batch.py/render.py reliability bugs, and a non-atomic installer

Continuing the same external audit report's architecture/data-integrity/reliability findings:

- `_contract.py` declared `encoder:aac` unconditionally `required` for `audio.py`,
  `loudness.py` and `join.py`, but all three pick their audio codec from the output
  extension via `audio_codec_for()` (falling back to AAC only when the extension
  isn't otherwise covered) -- so `doctor` reported these tools entirely unusable
  on an ffmpeg build without an AAC encoder, even though they can still produce
  e.g. a `.flac` output with no AAC involved at all. Moved to `optional` with a
  `when`, matching the pattern `cut.py`/`silence.py` already used; `join.py`'s
  `libx264` requirement was similarly conditioned on joining video inputs.
  `export.py`'s AAC `when` also named "any preset except gif", though `prores`
  (`pcm_s16le`) and `copy` (stream copy) don't use AAC either -- corrected.
- `batch.py`'s `--recipe` project mode (`{"project": "p.json", "clip_key": N}`)
  computed its cache key by hashing only that small outer dict, never the
  referenced project file's own content -- so editing `p.json` (an export preset
  swapped from `copy` to a real re-encode, captions text, anything) without
  touching the recipe file itself left the cache key unchanged, and the stale
  cached output was silently served for the new settings. Fixed by folding the
  referenced file's content into the key.
- `batch.py`'s cache file was written with a plain `write_text()`, not atomic --
  a process killed mid-write left a truncated file that the next run's
  `json.loads()` treats as corrupt and silently discards, losing every prior
  cache entry, not just the interrupted one. Fixed via a sibling temp file +
  `os.replace()`.
- `render.py`'s default work directory name came only from the output path (e.g.
  `final_work`), with no PID or timestamp -- two concurrent `render.py` runs
  targeting the same output (a `batch.py` "project" recipe processing several
  files in parallel, or simply two runs by mistake) shared the same work
  directory and clobbered each other's same-named intermediates mid-run. Fixed
  by suffixing the auto-derived default with this process's PID (an explicit
  `--work` is left as given, since the caller asked for that exact path).
- `bin/install.js` deleted an existing install (`rmSync`) before copying the new
  one in -- normal install, not just `--uninstall`. A process killed partway
  through the copy (Ctrl-C, disk full, a permission error) left the target
  either empty or half-populated, destroying a working previous install for
  nothing worse than an interrupted upgrade. Confirmed live: a simulated crash
  mid-copy left the target directory completely empty, an existing marker file
  gone. Fixed by copying into a scratch directory next to the real target first,
  then swapping it into place with a single rename.

## 0.16.10 — fix batch.py arbitrary script execution, and four fit/background/caption/freeze correctness bugs

- **Security:** `batch.py`'s recipe `steps` named the script to run for each
  step as a plain, untrusted string from `batch.json` (`run_step()` built
  `HERE / argv[0]`). `pathlib`'s `/` operator silently ignores the left side
  when the right side is itself an absolute path, and does nothing to stop a
  `../` traversal either -- so a `batch.json` the caller didn't author
  themselves (a template, a shared config, anything from outside) could name
  any Python file on disk (absolute path or `../` traversal) and have it
  executed with the caller's own privileges, once per matching media file.
  Confirmed with a live repro: a recipe step of `["/tmp/evil.py"]` executed
  and wrote a file outside the project. Fixed by validating each step's
  script name against the real, non-underscore-prefixed scripts in
  `scripts/` before running it.
- `fit.py` with only `--aspect` given (no `--width`/`--height`) bounded a
  narrower/taller target by the source's *width* instead of its height --
  a 1280x720 source asked for `--aspect 9:16` came out 1280x2276, a ~3.16x
  unrequested upscale, in both `--fit pad` and `--fit crop`. Fixed by
  bounding by whichever of the source's dimensions the new aspect actually
  needs, so the output never exceeds the source's own resolution.
- `background.py --gradient` used ffmpeg's `gradients` source filter without
  pinning its `speed` option, which defaults to `0.01` -- a slow rotation
  applied every frame. A "static" background (per this tool's own purpose:
  a title card, a placeholder behind a logo) silently drifted frame to
  frame instead of staying put, breaking the `bit_exact`/`deterministic`
  contract `_contract.py` declares for this tool. Confirmed live: the same
  pixel read a different value one second into a three-second clip. Fixed
  by pinning `speed` near the filter's own enforced floor (`1e-05`; `0`
  itself is refused) and `seed` to a fixed value.
- `caption.py`'s cue parser could match a line's `-->`/text structure while
  one of its two timestamps still failed to parse (e.g. a malformed
  `00:00:03.15.999`); the fallback then used the *entire raw line*,
  broken timestamp included, as the caption text instead of the text
  already captured after the arrow. Fixed to fall back to just the parsed
  text.
- `freeze.py`'s mid-clip freeze rounds the video hold to a whole number of
  frames (`n = round(hold * fps)`) but padded the audio by the raw,
  unrounded `--hold` value -- up to half a frame off from what the video
  actually holds for, a permanent A/V drift from that point on. Fixed by
  padding audio by the same frame-rounded duration the video gets.
- `cut.py` passed `--start`/`--end` straight to `parse_time()` with no sign
  check, unlike `freeze.py`/`background.py`, which already refuse negative
  durations -- a negative value reached ffmpeg's `-ss` as `-5.000000`
  instead of being refused with a clear error naming the flag. Fixed by
  refusing negative `--start`/`--end` up front.

## 0.16.9 — fix the MCP server crashing on a non-object JSON-RPC line

`mcp/server.py`'s stdio loop parsed each line with `json.loads()`, which
accepts any valid JSON value, not just an object -- a bare `42`, `null`,
`true` or `[1,2,3]` line parses without error. The very next check,
`"id" not in req`, then raised an uncaught `TypeError` for a non-dict
`req` (an int/bool/None isn't iterable the way `in` needs). That check
sat outside the `try/except` wrapping `handle()`, so the exception
propagated out of the stdin loop and killed the entire stdio server
process -- not just that one malformed line, but every other in-flight
and future tool call in the session along with it. Fixed by skipping any
parsed JSON value that isn't a dict before the `"id" not in req` check.

## 0.16.7 — fix a silently-dropped render.py fit height and a multicam.py drift-trim ordering bug

- `render.py`'s single-clip fit path only ever inherited `width`/`fps` from
  `project.frame` (never `height`), and the flag-forwarding list that turns
  `project.fit`'s own keys into `fit.py` argv had no entry for `height` at
  all. A `project.json` specifying `"fit": {"height": N}` alone built an
  empty `fit.py` argv and crashed with "nothing to do"; combined with
  another `fit` key (e.g. `duration`), `height` silently never reached
  `fit.py` and the output's height was left unchanged with no error. Fixed
  by adding the missing `frame.get("height")` inheritance and the
  `("height", "--height")` forwarding entry, matching the multi-clip `join`
  path, which already handled `height` correctly.
- `multicam.py --fix-drift` computed its audio trim start (`a_start`) in
  the source's own pre-correction time axis, but applied it via `atrim=
  start=` *after* the `asetrate`/`aresample` drift-correction filters had
  already rescaled that axis in the same filter chain -- so the trim
  landed on the wrong point once the timeline had been stretched or
  compressed by the drift ratio. `sync.py` already avoids this by seeking
  with `-ss` (an input-level operation) before its own drift filters;
  `multicam.py` now applies `atrim=start=`/`asetpts` before `asetrate`/
  `aresample` in the filter chain to match.

## 0.16.5 — fix silence.py breaking on audio-only WAV, unvalidated --fps, and a LUT-strength inversion in color.py

A deep line-by-line pass over the most-used editing tools:

- `silence.py` unconditionally appended `aac_args()` (`-c:a aac`) to its
  final ffmpeg command regardless of the output container. AAC cannot be
  muxed into a `.wav` file, so silence removal crashed outright on any
  audio-only WAV input or `-o out.wav` target -- a very ordinary case
  (podcasts, voice memos) the existing test suite happened to only cover
  with `.m4a` (where AAC is always valid, masking the bug). Fixed by
  picking the codec from the output extension via `audio_codec_for()`,
  the same helper every sibling script already uses, and by adding `-vn`
  when the output is audio-only but the input has video.
- `--fps` flowed straight into `cfr_args()` / a
  `fps or source_fps or 30.0` fallback in `crop.py`, `denoise.py`,
  `redact.py`, `sphere.py`, `straighten.py`, `join.py` and `multicam.py`
  without ever being validated. `0` is falsy in Python, so `--fps 0` was
  silently discarded and fell back to the source's own fps instead of
  erroring; a negative value passed straight through to ffmpeg's `-r`/
  `fps=` filter option, which rejects it with an unhelpful crash instead
  of a clear message naming `--fps`. Fixed by refusing `--fps <= 0` up
  front in all seven scripts, matching the guard `fit.py`/`proxy.py`/
  `background.py`/`grid.py`/`insert.py`/`sequence.py` already had.
- `color.py --lut-strength` (documented "blend LUT result with the
  original, 0..1") only branched into its blend logic for the *open*
  interval `(0, 1)` -- so `--lut-strength 0`, meant to mean "no LUT at
  all", instead fell into the "apply at full strength" fallback and
  silently graded the picture at 100%, the opposite of what was asked.
  Any out-of-range value (`2.5`, `-1`) did the same instead of being
  refused. Fixed by validating the range up front and handling `0`
  explicitly as "leave the picture untouched."
- `verify.py` built every file's output prefix from only its basename
  (`stem = outdir / f.stem`), so two files with the same name from
  different folders -- ordinary for real footage pulled from multiple
  cameras/SD cards -- resolved to the identical output prefix; with
  `--keep`, the file processed second silently overwrote the first one's
  finished output, with the report still showing PASS for both and no
  collision ever flagged. Same bug class as 0.16.4's `batch.py` fix.
  Fixed by disambiguating every colliding stem with a stable per-
  collision index before any file is processed.

## 0.16.4 — fix a silent false-PASS in check.py, an infinite loop in multicam.py, and a silent output collision in batch.py

Three unrelated bugs found in a wider audit past `caption.py`:

- `check.py`: `measure_loudness()` returns `{}` when ffmpeg's `loudnorm` JSON
  doesn't parse out of stderr (unexpected/garbled output). `main()` only
  appended the `loudness`/`true peak` rows when that measurement succeeded,
  so a failed measurement made those rows vanish entirely -- not FAIL, not
  WARN, just absent -- while `check.py` still reported an overall PASS for
  a platform with a loudness requirement it never actually verified. Fixed
  by reporting `WARN` (could not measure) instead of dropping the rows: a
  silent false PASS is worse than visible noise on a compliance tool.
- `multicam.py`: `--auto` alternates cameras with
  `while t < ref_dur: ... t += args.auto`, gated by `elif args.auto:` --
  which is only false for exactly `0`, so a negative value passed the
  check and entered the loop with `t` decreasing every iteration, hanging
  forever instead of erroring on invalid input. Fixed by refusing
  `--auto <= 0` up front.
- `batch.py`: a recipe's default output extension falls back to each
  source's own extension, so files that only differ by extension don't
  collide -- but a recipe with a fixed `"ext"` (e.g. converting a folder
  of mixed `.mp4`/`.mov` masters to one format) makes two sources with the
  same stem (`clip.mp4` and `clip.mov`) resolve to the identical final
  path (`clip_out.mp4`). `process()` had no collision detection, so the
  file processed later in sorted order silently overwrote the earlier
  one's finished output, with the cache still recording both entries as
  `"ok": true`. Fixed with a pre-flight collision check across the whole
  batch, refusing before any file is processed rather than after data is
  already lost.

## 0.16.3 — fix two more caption.py delimiter bugs: ASS override injection, SRT blank-line split

Following on from 0.16.2's `--font` fix, a closer look at `caption.py` found
two more places where user-controlled cue text (from `--text`, an SRT
file, or ASR transcription) flows raw into a delimited text format:

- ASS `Dialogue:` text treats a literal `{...}` as an override block --
  real style/animation commands (`\pos`, `\fscx`, `\t`, ...), not literal
  characters. Cue text containing braces was interpreted as those
  commands instead of read out, letting a caption reposition, rescale,
  or recolor itself or later text. Fixed by dropping `{`/`}` from cue
  text before writing the ASS `Dialogue:` line (also closes the same gap
  in the karaoke word-by-word path, which built its `{\kf..}` tags from
  the same unsanitised text).
- `write_srt()` wrote cue text raw. `parse_text_cues()` turns a bare `|`
  into a newline (the documented two-line-caption syntax), so two
  adjacent pipes (`a||b`) produced cue text containing a blank line --
  and a blank line is SRT's own block separator. Writing it raw split
  one cue into two malformed half-blocks, silently dropping the text
  after the fake boundary when re-parsed. Fixed by collapsing any run of
  blank lines within a cue's text to a single newline before writing.

## 0.16.2 — fix caption.py's --font not sanitised for ASS Style/force_style

An attack-surface audit of every call site that embeds user-controlled text
into a filter/subtitle construct found that `caption.py` was the one script
that never routed `--font` through a sanitiser before using it, unlike
`overlay.py`/`graphics.py`/`grid.py`/`look.py`, which all call
`escape_drawtext()` first. `caption.py` doesn't build a `drawtext=` filter,
though -- it embeds `--font` into two different ASS constructs
`escape_drawtext()` was never designed for: the comma-delimited
`[V4+ Styles]` `Style:` line, and the comma-separated `Key=Value` list
inside a `-vf subtitles=...:force_style='...'` option. A font name
containing a comma shifted every field after it in the `Style:` line
(size, colours, bold flag, alignment, margins); a comma or colon inside
`force_style`'s `FontName=` broke the option-list/`-vf` parsing the same
way.

Fixed with a new `ass_font_name()` helper in `caption.py` that drops
`, : \ '` and control characters from the font name outright -- the same
"no real font name needs this character, so don't chase a per-context
escape" call this codebase already made for `escape_drawtext()`'s `'`/`%`.

## 0.16.1 — fix two more escape_drawtext() gaps, and grid.py --pad's audio

Adversarial testing (deliberately hostile filenames -- very long, Unicode,
shell metacharacters, quotes, semicolons, `%` specifiers, literal filter-
graph syntax) found two more gaps in `escape_drawtext()`, the shared helper
every `drawtext=text=...` call site uses (`overlay.py --text`, the
`--font`/brand-font fallback, and 0.16.0's `grid.py` labels):

- An unescaped `;` split a filterchain exactly like an unescaped `,` does --
  minimal repro: `overlay.py clip.mp4 --text "a'b;c"` crashed real ffmpeg
  with `No such filter: 'c...'`. Fixed by adding `;` to the backslash-escape
  set.
- The quote character itself had no backslash escape that survives every
  call shape this codebase uses it in: both the existing `\'`-style escape
  and a POSIX-shell `'\''` close-insert-reopen escape parse fine in a
  simple `-vf` chain, but corrupt a `-filter_complex` chain with explicit
  `[label]` pads (grid.py's shape) -- confirmed by rendering the result:
  the text value doesn't end where the quote closes it, and trailing
  option text (`fontfile=...`, `fontsize=...`) leaks into the picture as
  literal burnt-in text. Fixed by dropping the quote character outright
  instead of escaping it -- losing one apostrophe from a label is a fair
  trade for the filter graph parsing correctly everywhere.
- `%` had the same problem the quote character did: the existing `\%`
  escape is not a real escape as far as drawtext's own text-expansion
  scanner (on by default, for `%{pts}`/`%{localtime}`/etc., a separate
  pass from the graph-level backslash escaping) is concerned -- a bare
  backslash-escaped `%` always logs "Stray % near ...", which is merely
  noisy on one ffmpeg build but a hard filtering failure that writes no
  output at all on another. No caller ever wants `%{...}` expansion, so
  `%` (and control characters, same underlying cause) are dropped outright
  instead of chasing a per-build-safe escape.

Also fixed a real bug CodeRabbit's review of 0.16.0 caught before it was
acted on: `grid.py --pad` held each shorter cell's video on its last frame
out to the longest clip, but a `--audio-from` track shorter than that was
mapped straight through with no padding at all -- the release note's "with
silence" claim wasn't true. Now `--pad` pads the selected audio track with
`apad`/`atrim` to match, and the docstring/help text describe what `--pad`
actually does (holds the last frame; does not add black video).

## 0.16.0 — add grid.py

New tool: composite `--cols`x`--rows` clips into one grid (e.g. a 4x2 wall
of takes or angles), each cell letterboxed (not stretched) to a common
`--cell-width`/`--cell-height` so mismatched aspect ratios and resolutions
line up cleanly. `--label auto` (default) burns each clip's own filename,
extension stripped, into its cell's bottom-right corner; `--label none`
turns that off. No audio unless `--audio-from` picks one input's track --
mixing every clip's audio together is rarely what a comparison grid needs,
so this tool never does it silently. Runs only as long as the shortest
clip by default; `--pad` instead holds each shorter clip's last frame (with
silence) out to the longest.

The per-cell label is filename-derived text reaching a `drawtext=text=...`
option, the same injection class fixed in 0.15.3 -- wrapped with the
existing `escape_drawtext()` helper from the start, with a regression test
that builds a clip literally named to look like a filter-graph breakout
payload and confirms it renders as inert literal text (not a new filter).

## 0.15.3 — fix a real filter-graph injection via --font fallback

Found by the same adversarial pass that produced 0.15.2, this time auditing
file-path/text escaping instead of colour flags. `overlay.py --font` and
`graphics.py`'s brand-font fallback both accept a fontconfig family NAME (not
a file path) and try to resolve it to a concrete file via `default_font_file()`
(`fc-match`) first -- but that resolution returns `None` whenever `fc-match`
isn't on `PATH` (true on some real systems, and always true on Windows, per
`default_font_file()`'s own docstring). When it returns `None`, both tools
fell back to `font='{args.font}'` with zero escaping, unlike the adjacent
`text='{escape_drawtext(args.text)}'` one line above it in `overlay.py`.
Since drawtext options are comma/colon-delimited, a font value like
`X',drawtext=text=OWNED` doesn't just fail to resolve a font -- the comma
ends the option (and the whole filter) early and starts an entirely new
drawtext filter, which actually rendered. Confirmed this is a real, working
injection (not theoretical): forced the `fc-match`-missing fallback path,
ran `overlay.py --font "X',drawtext=text=OWNED:fontcolor=yellow..."`, and the
injected "OWNED" text was actually burnt into the output picture.

Fixed by wrapping both fallback values with the existing `escape_drawtext()`
helper, matching the already-safe `text=` pattern next to it:

- `overlay.py`'s `font='{args.font}'` fallback (line ~250)
- `graphics.py`'s `font_opts()` fallback (`font='{font or brand.get(...)}'`)

## 0.15.2 — fix a real filter-graph injection via colour flags

Found by adversarial testing: every flag that string-formats a colour straight
into an ffmpeg filter graph accepted the value verbatim, with no validation.
Since ffmpeg filter options are comma/colon-delimited, a value like
`black,drawtext=text=INJECTED` doesn't just set an odd colour -- the comma
ends the colour filter early and starts an entirely new one. Confirmed this is
a real, working injection, not a theoretical one: rendered a frame with
`pad.py --color 'black,drawtext=text=INJECTED:fontcolor=white'` and the
injected text was actually burnt into the output picture.

Added `validate_color()` to `_common.py` (refuses anything that isn't a named
colour, `0xRRGGBB[AA]`, or `#RRGGBB[AA]`, optionally with an `@alpha` suffix)
and applied it to every colour-like flag that reaches a filter graph
unescaped:

- `pad.py --color`, `straighten.py --fill-color`, `waveform.py --background`
  and `--color` (new tools, this release cycle)
- `background.py --color`/`--gradient`, `fit.py --pad-color`,
  `export.py --pad-color`, `join.py --pad-color`, `overlay.py --chromakey`/
  `--font-color`/`--border-color`/`--box-color` (pre-existing tools -- this
  gap predates the recent tool additions)

`caption.py`'s colour flags were already safe (routed through the existing
`color_hex()`/`ass_color()` strict RRGGBB validators) and needed no change.

This is the same "no filter graph accepted from the caller" invariant every
other typed flag in this codebase already holds to -- colour flags were the
one place a free-form string still reached a filter graph unescaped. New
regression test proves the exploit across all 9 fixed call sites and that
real colour values still work; full suite (183 tests) and the contract suite
(67 tests) both pass.

## 0.15.1 — bug-check pass on the 39-tool set

Found and fixed while auditing the tools added across 0.13.0-0.15.0:

- `freeze.py`: `--at 0` (freeze on the very first frame -- the default when
  no `--mode`/`--at` is given at all combines with a source that starts
  right where you'd freeze it) crashed ffmpeg: the general insert-mode
  filter graph trims an empty "head" segment when `at == 0`, and filtering
  an empty stream fails. Added a dedicated `at == 0` branch that pads the
  front of the clip instead (`tpad` `start_mode=clone`), symmetric to
  `--mode extend`'s handling of the clip's end.
- `waveform.py`: `--audio-stream` was validated but never actually wired
  into the filter graph, which unconditionally read `[0:a]` -- every
  multi-track input visualized track 0 regardless of which track was
  requested, while the output's audio correctly followed `--audio-stream`.
  Now the filter reads `[0:a:{audio_stream}]`.
- `loop.py`: re-encoded with a hardcoded `libx264`/no `cfr_args`, unlike
  every other re-encoding tool -- an HDR source silently became SDR mislabelled
  BT.709, and VFR sources weren't conformed. Switched to `video_args(meta,
  ...)` and `cfr_args(meta)`, and added the `--crf`/`--preset` flags every
  other tool exposes (previously `--fast` silently had no effect).
- `_contract.py`: `cropdetect.py` always runs a real `cropdetect` measurement
  regardless of `--dry-run` (like `scenes.py`/`sync.py`/`multicam.py`/
  `report.py`), but wasn't declared in `DRY_RUN_ANALYSIS` -- the
  machine-readable contract falsely claimed `--dry-run` ran no ffmpeg for
  it. Registered alongside the other analysis-only tools.

Found via a fresh worktree off `main` post-merge, adversarial testing of
edge cases (zero/boundary values, multi-track inputs) rather than only the
happy paths the original PRs' tests covered. New regression tests for all
four; full suite (181 tests) and the contract suite (67 tests) both pass.

## 0.15.0 — 5 more tools: straighten, freeze, pad, speedramp, loop

Five more mechanical, typed-flag FFmpeg capabilities:

- `straighten.py` — rotates by an arbitrary angle for horizon correction
  (`rotate` filter), `--fit crop` (scale to fill, no visible gap) or `--fit
  pad` (keep the full picture, fill the corners). Distinct from `fit.py
  --rotate`'s exact 90-degree turns.
- `freeze.py` — holds a frame for N seconds (`tpad`/`concat`), `--mode
  insert` (pushes the rest of the clip later) or `--mode extend` (only at
  the clip's end, no push).
- `pad.py` — adds black/silent padding at the start and/or end of the
  timeline (`tpad`/`apad`). Distinct from `fit.py --fit pad`'s per-frame
  letterbox bars.
- `speedramp.py` — steps through different constant speeds across a clip
  via repeatable `--segment START-END:FACTOR` pieces (setpts/atempo per
  segment, concatenated). Distinct from `fit.py`'s single whole-clip speed
  factor.
- `loop.py` — repeats a clip `--times` N or to a target `--duration`
  (`-stream_loop`).

Same conventions as every other tool here: every numeric flag range-checked
before ffmpeg runs, no subject detection or judgement (straighten doesn't
measure the tilt, loop doesn't smooth the seam, freeze doesn't pick where
to hold -- the calling agent supplies all of that).

Registered in `_contract.py`'s `TOOL_META`/`REENCODE_META` (39 tools total,
up from 34); 19 new regression tests in `tests/test_all.py`, including a
pixel-level check that `straighten.py --fit crop` leaves no black corner.

## 0.14.0 — 5 new tools: cropdetect, deinterlace, denoise, redact, waveform

Five mechanical, typed-flag FFmpeg capabilities that had no wrapper yet:

- `cropdetect.py` — measures existing black letterbox/pillarbox bars (FFmpeg's
  `cropdetect` filter) and reports the `crop.py`-ready rectangle. Analysis only,
  writes no file. Distinct from `fit.py --fit crop`, which crops to a target
  aspect ratio it computes itself with no black-bar measurement involved.
- `deinterlace.py` — deinterlaces old interlaced source footage (`yadif`),
  `--mode frame` (keeps fps) or `--mode field` (doubles fps), `--parity`.
- `denoise.py` — video noise/grain reduction (`hqdn3d`), `--strength low/
  medium/high` or individual spatial/temporal luma/chroma overrides. Distinct
  from `audio.py --denoise`, which only touches audio.
- `redact.py` — blurs or pixelates an exact caller-given pixel rectangle for
  the whole clip (privacy/compliance redaction: faces, plates). Same
  rectangle convention as `crop.py`; does not locate anything itself.
- `waveform.py` — renders an audio track as a waveform or spectrum
  visualization video (`showwaves`/`showspectrum`), for audio-only inputs
  with no picture worth showing.

All five follow this skill's typed-flags-only convention: every numeric flag
is range-checked against FFmpeg's own real documented AVOptions before
ffmpeg runs, and none introduces any subject detection or judgement --
cropdetect measures existing bars, redact blurs the exact rectangle it's
given, neither decides what belongs in frame.

Registered in `_contract.py`'s `TOOL_META`/`REENCODE_META` (34 tools total,
up from 29); 22 new regression tests in `tests/test_all.py` cover the
functional path and validated ranges for each tool.

## 0.13.0 — add `sphere.py`: flat-viewport extraction from 360/spherical video

New tool wrapping FFmpeg's `v360` filter for the most common 360-video job: pointing a fixed,
typed camera (`--yaw`/`--pitch`/`--roll`, `--h-fov`/`--v-fov`) at an equirectangular (or
fisheye/cubemap/etc., via `--input-projection`) source and baking out an ordinary flat video.
Consistent with this skill's design boundary: it aims and extracts a viewport, it does not detect
or track a subject — that decision stays with the calling agent. Registered in `TOOL_META`/
`REENCODE_META`, 29 tools total.

## 0.12.6 — stop shipping `__pycache__` in the npm tarball

`package.json`'s `files` array scopes the tarball to `bin/`, `scripts/`, `mcp/`, `references/`,
`SKILL.md`, `README.md` and `LICENSE`, but a `files`-scoped pack does not automatically respect
`.gitignore` the way a plain `git`-tracked-files pack would — the 0.12.5 tarball on npm shipped
every `scripts/__pycache__/*.pyc` a local interpreter had produced (interpreter-version-specific,
harmless at runtime since Python regenerates them, but ~45% of the package's unpacked size for
nothing). Added an explicit `.npmignore` for `__pycache__/`, `*.pyc`, `*.pyo`, which npm honors
even when `files` is set. Unpacked size drops from 913.7 kB / 64 files to 496.8 kB / 40 files.

## 0.12.5 — fix Windows `drawtext` crash (#100), and 4 smaller review findings

`look.py`, `scenes.py --sheet`, `overlay.py --text` and `graphics.py` could crash on real Windows
FFmpeg builds (confirmed on winget's gyan.dev 9.x): `drawtext`'s own fontconfig resolution dies
with an access violation whenever it has to resolve a font by family name, with or without a
valid `fonts.conf` — and `doctor` reported `missing required: none`, since `-filters` correctly
lists `drawtext` as present; the crash only ever surfaced as a runtime failure, the exact thing
the step-0 capability check exists to prevent.

- All four tools now resolve a concrete font file by default (`default_font_file()` in
  `_common.py`: a well-known system font path on Windows, `fc-match` on Linux/macOS) and emit
  `fontfile=` instead of `font=` whenever one can be found — `fontfile=` skips fontconfig
  entirely, the one form confirmed not to crash. `font=` remains the fallback when nothing can be
  resolved, unchanged from before.
- `doctor` now actually renders one frame through `drawtext` instead of trusting the `-filters`
  listing alone. A confirmed crash (killed by signal on POSIX, an access-violation-style exit on
  Windows) downgrades `filter:drawtext` from "listed" to `missing`, with the crash detail in
  `errors[]`; an ordinary nonzero exit proves nothing either way and leaves the listing-based
  result standing (same "unknown is not missing" principle used everywhere else in capability
  detection).
- `scenes.py --sheet` gained `--no-timecode`, matching `look.py`, as a way out if drawtext is
  ever genuinely unusable on a machine.
- Fixed a `SyntaxWarning: invalid escape sequence '\;'` in `_common.py`'s `shell_quote()` (a stray
  backslash before an already-unescaped character; harmless today, an error in a future Python).
- README's Quick Start script examples now note that Windows/Git Bash needs `python`, not
  `python3` (`bin/install.js` and `doctor`/`contract` already handled this; the raw examples
  didn't say so).
- SKILL.md's Gotchas section documents the crash and the fixes above.

Thanks to [@willy92wins](https://github.com/willy92wins) for the detailed repro in #100.

## 0.12.4 — `stabilize.py` gains `--tripod` and `--crop` (#96)

A follow-on audit of the same class of gap 0.12.3 closed in `color.py --correct`: scripts that
wrap a real FFmpeg filter but only expose a subset of what that filter actually supports.
`stabilize.py` wrapped `vidstabdetect`/`vidstabtransform` with only `--shakiness`/`--smoothing`/
`--zoom`, leaving two genuinely useful, real options unreachable:

- `--tripod`: virtual tripod mode (`vidstabdetect`'s `tripod=1`, `vidstabtransform`'s own
  `tripod=1`, equivalent to `relative=0:smoothing=0`) locks every frame to one fixed reference
  frame instead of following the camera's intended motion — for a shot meant to be static but
  nudged, or one you want dead-locked rather than merely smoothed.
- `--crop {keep,black}`: what happens to whatever edge `--zoom` doesn't crop away.
  `vidstabtransform`'s `crop=0` (the previously hardcoded default, "keep") stretches border
  pixels; `crop=1` ("black") was unreachable — the only prior workaround was cropping in further
  with `--zoom`, at the cost of framing/resolution.

Both are typed flags (`--crop` restricted to the filter's own two real option names via
`choices`), verified against `ffmpeg -h filter=vidstabdetect`/`vidstabtransform`'s real AVOptions
before implementation, with new regression tests that actually run both flags end-to-end and
check the output's duration/resolution. (`silence.py`, `audio.py`, `loudness.py`, and `fit.py`'s
`minterpolate` usage were also checked against their real filters' full option sets and found
either not applicable — `silence.py` doesn't wrap `silenceremove` at all, it does its own
`silencedetect` + range-trim — or already adequately covered.)

## 0.12.3 — `color.py --correct` gains gamma, lift/gain, levels and curves

Closes a long-standing, documented gap: the downstream `color-grading-skill` has carried
`GAMMA`/`LIFT`/`GAIN`/`LEVELS`/`CURVES` in its own `UNSUPPORTED_OPERATIONS` because
"ffmpeg-skill exposes no typed X filter in its public contract". `--correct` gains five more
typed flags, all folded into the same fixed filter chain the existing `--exposure`/`--contrast`/
`--saturation`/`--temperature`/`--tint` already build — no new mode, no filter string ever
accepted from the caller:

- **`--gamma`** (0.1..10, default 1=unchanged): `eq`'s own `gamma` option, added to the same
  `eq=contrast=...:saturation=...` term contrast/saturation already use, not a second `eq` call.
- **`--lift` / `--gain`** (-1..1 each, default 0=unchanged): classic three-way colour correction,
  extending the same `colorbalance` call `--tint` already used for midtones — `--lift` sets the
  shadow channels (`rs=gs=bs`), `--gain` the highlight channels (`rh=gh=bh`), the same
  all-three-channels-together convention `--tint` uses for `rm/gm/bm`. Confirmed against
  `ffmpeg -h filter=colorbalance`: `rs/gs/bs`, `rm/gm/bm`, `rh/gh/bh`, each documented -1..1.
- **`--levels-in-black` / `--levels-in-white` / `--levels-out-black` / `--levels-out-white`**
  (0..255 each, defaults 0/255/0/255=unchanged; rejects `in_black >= in_white` or
  `out_black >= out_white` before ffmpeg runs): `colorlevels`, whose real parameters
  (`ffmpeg -h filter=colorlevels`) take fractional 0.0..1.0 input/output black/white points, not
  0..255 — this tool exposes the familiar 8-bit unit and divides by 255.0 when building the
  filter, the same "human unit in, filter's native unit out" convention `--temperature` already
  uses. The `colorlevels=` term is only added to the chain when at least one of the four flags is
  given; an all-default `--correct` call adds no `colorlevels` term, matching how every stage in
  this chain is either always present at its own no-op default or (for this new pair) omitted
  entirely when unused.
- **`--curves PRESET`** (argparse `choices`, default: none, no `curves=` term added): the `curves`
  filter's own built-in presets, read from `ffmpeg -h filter=curves` rather than assumed:
  `color_negative`, `cross_process`, `darker`, `increase_contrast`, `lighter`,
  `linear_contrast`, `medium_contrast`, `negative`, `strong_contrast`, `vintage` (the filter's own
  11th choice, `none`, is omitted from `--curves`'s choices since leaving the flag unset already
  gets that identity result without adding a filter term for it).
- Contract: `color`'s optional capabilities gain `filter:colorlevels` (`when: "--correct with any
  --levels-*"`) and `filter:curves` (`when: "--correct --curves"`). No change to any existing flag,
  contract field, MCP schema or tool semantics.
- Tests: 5 real-media tests in `tests/test_all.py` mirroring the existing `--correct` style —
  gamma/lift/gain run and measurably change signalstats luma, levels narrows the measured dynamic
  range, curves runs and preserves geometry/duration, and out-of-range or inverted values for
  every new flag (`--gamma`, `--lift`, `--gain`, `--levels-in-black`/`--levels-in-white` inverted,
  `--levels-out-black`/`--levels-out-white` inverted, an invalid `--curves` choice) are each
  refused before ffmpeg ever runs, with no partial output.

## 0.12.2 — `caption.py --mode mux` no longer drops the input's existing subtitle track(s)

Found while discussing a real use case (adding both an English and a Japanese soft subtitle
track to a foreign video) and reproduced directly: chaining `--mode mux` once per language —
the natural way to build a multi-language subtitle set — silently dropped every earlier
language but the last, because the mode's `-map` list never included the main input's own
existing subtitle stream(s), only the freshly-added one. Same class of bug fixed across
`fit.py`/`color.py`/`graphics.py`/`overlay.py` in 0.12.1/#91 (deliberately scoped out of that
pass since burn mode raises a real design question mux mode doesn't have: mux mode explicitly
promises "copies video/audio untouched, adds the SRT as a soft, toggleable subtitle stream", so
keeping what was already there has one obvious answer). Existing tracks are now mapped and
stream-copied (`-c:s:i copy` per existing index) ahead of the new one, whose own `-c:s`/
`-metadata:s:s:N` now target its real index instead of always `0`. Closes
[#93](https://github.com/kajisho5/ffmpeg-skill/issues/93).

## 0.12.1 — Stream-preservation audit: subtitle/data streams no longer silently dropped by picture-only edits

Prompted by an external review pushing back that "feature-complete" for this project now means
proving reliability, not adding tools. Audited all 28 tools against a real fixture carrying
video + audio + subtitle + chapters, by actually running each tool and `ffprobe`-ing its output
rather than reading the code and guessing (an ad hoc pass, not itself checked in as a test). The
checked-in regression test below covers the four tools this pass actually changed, against a
narrower existing fixture (video + audio + two subtitle tracks, no chapters).

- **`fit.py`, `color.py` (`--correct`/`--lut`/`--to-sdr`), `graphics.py`, `overlay.py`: kept the
  source's subtitle/data streams instead of silently dropping them.** Each of these builds an
  explicit `-map` list naming only the video and audio streams it re-encodes; a source with an
  embedded subtitle track (or a data stream) lost it with no signal to the caller, even though
  the operation never touched it. `chapters` already survived regardless (`-map_chapters`
  defaults independently of `-map`) — this was specifically about subtitle/data. Each of the four
  now tries `-map 0:s? -map 0:d? -c:s copy -c:d copy` alongside its existing maps first (a no-op
  via `?` when the source has none), falling back to the original video+audio-only command only
  if that combined attempt fails (e.g. a subtitle codec that can't be stream-copied into a
  changed output container) — the same fallback shape `color.py --retag` already used for this
  in 0.12.0. `--json` gains `dropped_non_av_streams` (`true` only when that fallback was actually
  needed), matching the field name `--retag` already introduced.
- **Deliberately left as-is, tracked in [#91](https://github.com/kajisho5/ffmpeg-skill/issues/91):**
  `caption.py`'s burn mode (whether a pre-existing embedded subtitle should coexist with a newly
  *burned-in* one is a real design question, not a clear-cut preservation fix); `audio.py` when
  its output is a video container; `join.py`/`multicam.py`/`sync.py`, which combine multiple
  separate input files or replace the audio track outright — "which input's subtitle survives"
  has no single correct answer the way a single-input picture/colour edit does, matching the
  existing "different problem shape" carve-out already used for the 0.12.0 `--audio-stream`
  extension. Attachments (`-map 0:t?`, e.g. embedded ASS fonts) are also not covered yet — no
  tool here currently reads/writes ASS-with-fonts end to end, so the risk is theoretical for now.
- Test: `test_picture_only_edits_keep_the_sources_subtitle_streams` runs all four fixed tools
  against `c_subbed.mkv` (two real embedded SRT tracks, already used by other tests) and asserts
  BOTH subtitle tracks survive and `dropped_non_av_streams` is `false`.
- **Two real regressions caught in code review before this shipped, both fixed and covered by a
  new test:** `overlay.py`'s `--image`/`--video` branches combined the pre-existing `-shortest`
  with the new subtitle map -- a subtitle ending before the main video could truncate the WHOLE
  output to the subtitle's length (reproduced: 6s video, 1s subtitle -> 1.04s output). `-shortest`
  is now used only when the source's duration is unknown; the existing `-t <duration>` (already
  there for FFmpeg 7+ precision) is used alone whenever it's known, since it only bounds the main
  input. Separately, `fit.py --method speed` retimes video/audio (`setpts`/`atempo`) but a
  stream-copied subtitle keeps its original timestamps, so it would silently desync from the
  now-faster/slower picture; `fit.py` now skips subtitle preservation specifically when changing
  speed and reports `dropped_non_av_streams: true` honestly instead. `probe()` gains an additive
  `data_streams` count (alongside the existing `subtitle_streams`) so that determination also
  catches a data-only stream with no subtitle track.

## 0.12.0 — 2026-09-07 — Hardening pass: stream/input safety, contract-vs-implementation drift, SKILL.md/eval consistency

A hardening-focused release: no new tools, no new features. Everything here closes a gap between
what the contract/docs/evals claimed and what the implementation actually did, or fixes a real
runtime defect found by reproducing it first. `contract_version` is unchanged — every contract
field addition here is additive.

- **Safety: a tool could be made to overwrite its own input via a same-file-different-string
  output path.** `-o ./same.mp4` against an input opened as `same.mp4` (or any relative/absolute
  pair, `..` segment, or symlink) resolves to the same file but passed ffmpeg's own
  byte-identical-string "Output same as Input" guard — `-y` then silently clobbered the source
  mid-encode. Reproduced on `crop.py` before the fix. `_check_no_overwrite_input()` in
  `_common.py`'s `run()` compares `os.path.realpath()` of every `-i` argument against the output
  path and refuses before ffmpeg starts, covering every writing tool from one choke point.
- **Safety: a failed `run()` call could leave a partial (often 0-byte) output file behind.**
  `verify_output()`'s cleanup only ran on the success path; a failure after ffmpeg had already
  opened the output (muxer header written, then a mid-stream error) left a stray file a caller
  could mistake for a real artifact. `_cleanup_partial_output()` now runs for every nonzero
  ffmpeg exit, `check=True` or `check=False`.
- **`color.py --retag`'s re-encode fallback used to silently drop every stream beyond
  video+audio-0.** The stream-copy path (`-map 0 -c copy`) keeps every stream — extra audio
  tracks, subtitles, chapters; the re-encode fallback (triggered when the copy fails) dropped all
  of them with no signal in `--json`. Added a middle tier that tries to keep subtitle/data
  streams via `-c:s`/`-c:d copy` alongside the required video/audio re-encode, and `--json` now
  reports `reencoded`/`dropped_non_av_streams` honestly instead of a bare `"completed"`.
- **`sync.py`'s `REENCODE_META` claimed `video="never"`; `--trim-second` actually re-encodes
  video** whenever the second recording starts later than the reference (the common case,
  `offset>=0`) or `--fix-drift` is used — only the `offset<0` stream-copy path leaves video
  untouched. Fixed to `"conditional"`/`"conditional"` with a note.
- **Error taxonomy (additive): `error.code` and `error.retryable`** now sit alongside every
  failure's existing `error.kind`/`error.message` — `code` is a static relabelling of the same 4
  kinds this codebase has always used (`INPUT_INVALID`/`DEPENDENCY_MISSING`/
  `FFMPEG_EXECUTION_FAILED`/`OUTPUT_INVALID`, `INTERNAL_ERROR` fallback), not a new taxonomy the
  code can't back up; `retryable` is currently always `false` (no kind is distinguishable from a
  deterministic failure without exit-code/stderr sniffing this codebase doesn't do). `kind`'s
  existing values and the rest of the JSON shape are unchanged.
- **`loudness.py --json` now includes the second-pass (post-normalization) measurement** as a
  `result` field — it was computed but only ever printed to stderr, so a caller had to make a
  separate `--measure-only` call to learn what loudness was actually achieved.
- **`--audio-stream N` extended to `overlay.py`, `graphics.py`, `color.py`; `fit.py` gained
  explicit audio mapping.** Every tool that re-encodes audio from a multi-track input now behaves
  consistently instead of silently defaulting to track 0 (or, for `fit.py`, to ffmpeg's own
  implicit "best stream" heuristic, which for audio favours channel count over track order).
  `join.py`/`multicam.py` are out of scope — they combine separate input files, a different
  problem shape. Closes [#62](https://github.com/kajisho5/ffmpeg-skill/issues/62) (the same gap
  `caption.py`/`audio.py` already closed in [#55](https://github.com/kajisho5/ffmpeg-skill/issues/55)).
- **`doctor --json` gains a `fonts` field**, informational like `gpu_encoders`: drawtext's default
  font (`caption.py --animate`/`--karaoke`, `graphics.py`) can silently substitute a different
  family when the requested one isn't installed — a drawtext exit code can't detect this
  (fontconfig substitutes for any name, valid or not), so `fc-match` is queried directly.
  Never gates `ok`/`usable`; a substituted font doesn't make the tool unusable, just possibly
  styled differently than intended.
- **`probe.py` gains `subtitle_stream_details`**, a detailed per-subtitle-stream array
  (`index`/`codec`/`language`/`title`) mirroring `audio_streams`' shape — `subtitle_streams`'
  existing int-count type and meaning are unchanged.
- **Doc-vs-implementation drift fixes**, each with a regression test pinning the doc text against
  the live code so the same drift can't recur silently:
  - `docs/contract.md`'s hand-copied `skill.version` example had drifted to a stale `0.9.1`
    while `package.json` had moved to `0.11.0`.
  - `docs/contract.md`'s failure-JSON example was missing the `code`/`retryable` fields above.
  - `SKILL.md`/`references/scripts.md` claimed unconditionally that every script's `--dry-run`
    runs nothing; `sync`/`multicam`/`scenes`/`report` genuinely run ffmpeg/ffprobe to measure or
    analyse under `--dry-run` (they just don't write the final artifact), and `verify` accepts
    the flag but ignores it — all three doc locations now name the real exception set.
  - `SKILL.md`'s Workflow section never mentioned `doctor`/`contract` at all, so an agent on an
    unfamiliar machine had no documented step to check capability before running a tool that
    depends on an optional filter/encoder. Added a step 0.
  - `SKILL.md`'s "Look at the picture" step told the agent to judge subject framing and
    text-over-faces as part of its own job, directly contradicting "What this skill does and does
    not decide"'s statement that this belongs to the calling agent. Split into a mechanical tier
    this skill verifies directly and a judgement tier reported to the calling agent — explicitly
    *not* flagging `fit.py --fit pad`'s letterboxing as a defect, since that's that mode's correct
    output. Also formalized `Look: PATH (pixels not inspected; agent has no image view)` for an
    execution environment that can't actually view images.
  - `bin/install.js`'s `contract`/`doctor` subcommand hardcoded `python3`; Windows Python
    installers commonly expose `python`/`py` instead (only the Microsoft Store package ships
    `python3`) — now falls back through `python3` → `python` → `py` on Windows. The same
    hardcoding was also present, unfixed by that change, in `mcp/server.py`'s and README's MCP
    client config examples — both now note the Windows alternative.
  - `evals/agent_prompts_exec.json`'s `f05-unsupported` claimed "no reverse tool in the skill"
    and scored refusing a reverse request as correct — `reverse.py` has existed the whole time
    and `SKILL.md`'s own routing table names it. It also endorsed a hand-written raw-ffmpeg
    fallback as acceptable, contradicting this project's own "never fall back to raw ffmpeg"
    policy stated elsewhere. Replaced with a genuinely unsupported case and a normal `reverse.py`
    success case; `evals/results/exec-1.json`'s historical record is left unedited with a note
    explaining the old grading was wrong.
- **Cross-platform: end-to-end non-ASCII filename coverage.** Filter-graph *string* escaping for
  Unicode paths was already tested; nothing exercised a non-ASCII filename as the actual `-i`/
  output argument through `subprocess` argv. Added a test copying a fixture to a CJK/accented
  filename and running `probe`/`cut` against it both directions — passes on all 3 CI platforms.
- **Docs: `CONTRIBUTING.md`**, a `.github/workflows/release.yml` that automates GitHub Release
  creation once a version tag is pushed (tag creation itself stays a manual, deliberate act), and
  a one-line honest note that GPU-accelerated encoding stays off the roadmap without a
  real-hardware-verified design (build-presence detection, which `gpu_encoders` already limits
  itself to, is not proof a job succeeds).
- **`--dry-run`'s probe stub no longer fabricates plausible-looking `1920x1080`/`30fps` dimensions
  for a not-yet-written output.** A first attempt at this (reporting the honest `0`/`0.0` "not
  measured" value instead, matching `duration`/`size_bytes`'s existing convention in the same
  stub) had to be reverted mid-pass: `join.py` and `fit.py` both divide by a probed source
  width/height when computing the other dimension from an aspect ratio, and dry-run probes chain
  across multi-stage pipelines (a prior stage's still-unwritten dry-run output gets probed as the
  next stage's input), so a zero source dimension reached those divisions and crashed with
  `ZeroDivisionError`. Root-cause fixed instead: both division sites now treat a zero/unknown
  source dimension as "can't compute a ratio" and fall back to the requested dimension rather than
  dividing by it; every other tool touching probed width/height for aspect-ratio math was audited
  and either doesn't divide by it or hands it straight to an ffmpeg filter (moot under `--dry-run`,
  since ffmpeg never runs). `--json` was never affected by any of this — it always omitted the
  placeholder; only a dry-run's human-readable summary line could echo the fake number. Closes
  [#77](https://github.com/kajisho5/ffmpeg-skill/issues/77).

- **`probe.py`: `subtitle_stream_details`.** `subtitle_streams` was a plain integer count while `audio_streams` was already a detailed array, so nothing could tell which subtitle index was which language on a multi-track input (e.g. an MKV with Japanese and English subs already muxed in). `subtitle_stream_details` adds that detail as a new, purely additive array — `[{"index", "codec", "language", "title"}, ...]`, one entry per embedded subtitle stream in file order (index n is `-map 0:s:n`), mirroring `audio_streams`' shape minus the audio-only fields (channels, layout, sample rate) ffprobe doesn't expose for subtitle streams. `subtitle_streams`' existing type and meaning (the int count) are unchanged. No writing tool selects among existing embedded subtitle streams yet; this is a `probe.py`-only enrichment. Closes [#63](https://github.com/kajisho5/ffmpeg-skill/issues/63).
- **`caption.py --audio-stream N`: explicit multi-audio-track selection.** Confirmed `caption.py` did silently pick a track on a multi-audio-track input (dubbed languages, M&E stems): burn mode had no `-map` at all (ffmpeg's own automatic stream-selection heuristic, not necessarily index 0, decided), mux mode and the karaoke energy-timing/`--transcribe` audio extraction both hardcoded `0:a:0`. `--audio-stream N` (default 0, matching `audio.py`'s existing flag and unchanged prior behaviour) now threads the same explicit track index through all four: burn's re-encoded audio, mux's stream-copied audio, `--transcribe`'s speech-to-text source, and karaoke's energy-timing analysis, refusing an out-of-range index the same way `audio.py --audio-stream` already does. Closes [#55](https://github.com/kajisho5/ffmpeg-skill/issues/55).
- **`caption.py --text`: SMPTE non-drop-frame timecode cues.** Cues were positioned by decimal seconds only; broadcast-style deliverables often supply cue timing as `hh:mm:ss:ff` frame timecode instead. `--text` cue lines now also accept that format (e.g. `00:00:03:15 --> 00:00:06:00 ...`) — the frame count is converted to seconds with `--fps`, or the input video's own probed fps when `--input` is given and `--fps` is not. A cue that is shaped like a timecode but has no fps available (no `--fps`, no `--input`) is refused with a clear error naming the missing `--fps`, rather than silently misread as a plain text line the way an ordinary unparseable cue line already is. `_common.py` gains the reusable pieces other tools can build on later: `parse_time()` takes an optional `fps` argument for the `hh:mm:ss:ff` case (raising the new `MissingFpsError`, a `ValueError` subclass, when fps is needed but absent), and `fmt_smpte_time()` formats seconds back to `hh:mm:ss:ff` — used here to echo the interpreted cue range in the `wrote ... .srt` report line so a caller can confirm the timecode was read correctly. The written `.srt` itself stays decimal-millisecond SRT timing, since that is the only timing SRT/mux subtitle codecs actually carry; nothing claims frame-exact precision it can't hold. Drop-frame (29.97/59.94 fps) counting is out of scope. Closes [#54](https://github.com/kajisho5/ffmpeg-skill/issues/54).
- **`references/process-pitfalls.md`: development-process mistakes already made once.** Distinct from `references/ci-platform-pitfalls.md` (ffmpeg/CI behaviour differences): this is about the process of making a change safely, not FFmpeg itself. Three entries to start: narrowing a `TOOL_META[...]["required"]` capability list without first grepping `tests/test_contract.py`'s `DoctorDetectionTests` for the fixture-pinned `usable` outcome it protects (nearly broken twice, in #51 and #52, caught before landing both times); retrying a git tag push or GitHub Release creation in this environment, where both are scoped out (branch pushes work, tag pushes 403 at the git-receive-pack level; no `create_release`/`create_tag` MCP tool exists; the outbound proxy itself blocks a raw REST API call to the releases endpoint) rather than accepting it after one confirmation; and redesigning a test fixture a third time instead of recognising, after two independently-redesigned fixtures failed differently on the same platform, that the platform's real behaviour (not the fixture) is the actual cause (`stabilize.py`'s macOS libvidstab test). A living document — add to it whenever one of these recurs. Docs-only; no behaviour changed.
- **`doctor --json`: `gpu_encoders`.** No tool here uses GPU-accelerated encoding — every tool assumes CPU x264/x265 — but `doctor` had no way to answer "is GPU encoding available on this machine" at all, unlike every other capability it already reports `yes`/`no`/`unknown` for. `gpu_encoders` reports GPU-backed encoders (`nvenc`, `videotoolbox`, `qsv`, `vaapi`, `amf`) present in this ffmpeg *build*, read from the same `-encoders` listing `doctor` already parses — `{"status": "parsed"|"unparsed"|"failed"|"missing", "present": [...]}`. Deliberately build-presence only: proving a real GPU/driver will accept a job would need an actual encode, which `doctor`'s introspection never runs (matching its existing 10s-timeout, listing-only philosophy). Purely informational — no tool declares or requires a GPU encoder, so this field never affects `ok` or any tool's `usable`. The human-readable `doctor` output gets one line naming what's present (or "none"). Closes [#52](https://github.com/kajisho5/ffmpeg-skill/issues/52).
- **`caption.py --mode mux`: soft subtitle stream instead of burn-in.** Every caption call previously re-encoded both streams to render pixels (`reencodes_video`/`reencodes_audio`: `"always"`) even when the caller only wanted a subtitle track added, not the picture changed. `--mode mux` (new; `--mode burn` stays the default) copies video and audio untouched (`-c:v copy -c:a copy`) and adds the SRT as a separate, player-toggleable subtitle stream — `reencodes_video`/`reencodes_audio` are now `"conditional"` with a note explaining the split. Only takes a plain SRT (`--srt`/`--text`/`--transcribe`), not `--ass`, `--animate` or `--karaoke`: styling and animation render pixels, so they have no soft-subtitle equivalent and are refused with a pointer to `--mode burn`. The subtitle codec is picked from the output container (`mov_text` for `.mp4`/`.m4v`/`.mov`, `srt` for `.mkv`, `webvtt` for `.webm`); an unrecognized container is refused rather than guessed at. `contract --json` gains three new optional capabilities (`encoder:mov_text`/`encoder:webvtt`/`encoder:srt`, each `"when"`-gated to the matching output container) so `doctor` can report them honestly; the existing required capabilities (`encoder:libx264`, `encoder:aac`, `filter:subtitles`) are unchanged, since `--mode burn` is still the default and doctor's usability model doesn't vary by flag. Closes [#51](https://github.com/kajisho5/ffmpeg-skill/issues/51) — timecode-aware cue timing and explicit multi-audio-track selection were split out to [#54](https://github.com/kajisho5/ffmpeg-skill/issues/54) and [#55](https://github.com/kajisho5/ffmpeg-skill/issues/55) to keep this change reviewable.
- **Test: the prose tool count in README/`docs/contract.md`/`package.json` is now checked against the real tool list.** 0.11.0 was cut to fix exactly this drift (README said 28 twice and 22 once; `package.json` said 21) by hand, with nothing to stop it recurring. `tests/test_contract.py`'s `test_docs_tool_count_matches_the_real_tool_list` scans all three for `"<N> tools"` wording and fails if any number doesn't match `scripts/`'s actual public-tool count, so the next tool added/removed without updating every mention fails CI instead of drifting silently. `contract_version`/`skill.version` were already split (0.9.0) and already documented as "additive keeps `contract_version`, breaking bumps it" — `docs/contract.md` now also repeats the tagged-version pin guidance next to that table, since `capability_map` makes this the most cross-repo-facing part of the contract. Closes [#50](https://github.com/kajisho5/ffmpeg-skill/issues/50).
- **Tests: `overlay.py --image` on an audio-less video is now covered.** Every existing overlay test used a
  source with audio; investigating a downstream report of `overlay.py` "hanging" on audio-less input (the
  historical 0.9.x defect this tool's own `-t <duration>` fix, added in 0.10.0, was meant to close) found the
  fix already works — the run had just been mistaken for a hang under a too-short timeout while it was still
  transcoding a 1080p60 frame with a fade filter. No code change; `test_overlay_on_audio_less_video_terminates`
  closes the coverage gap so this defect class can't silently regress.

## 0.11.0 — 2026-09-07 — Pixel crop, still-to-clip, rotate/flip/PiP/reverse/chromakey/stabilize/sequence/Ken Burns, fail-loudly output verification, capability map

Closes the video-editing-skill ADR-002/ADR-003 gap investigation (11 confirmed gaps): `crop.py`, `insert.py` (incl. Ken Burns), `fit.py --rotate`/`--flip`, `overlay.py --video`/`--chromakey` (video-on-video PiP, chroma key), `reverse.py`, `stabilize.py`, `sequence.py`, `background.py`, `proxy.py`, `contract --json`'s `capability_map`, and a repo-wide "fail loudly" pass making `verify_output()` the single success criterion for every writing tool. 28 tools total (was 21 at 0.10.0); README/package.json's stale "21"/"22" tool-count strings are also corrected to the real count here — see [#50](https://github.com/kajisho5/ffmpeg-skill/issues/50) for making that count self-maintaining going forward.

- **SKILL.md: two more worked examples of the mechanical-vs-judgement line.** "What this skill does and does not decide" already named categories (which cut is right, highlight ranking, thumbnails, content understanding) but not the line itself. Adds "apply this LUT" (mechanical, in scope) vs. "grade this scene to look cinematic" (judgement, belongs to a colour-grading skill) and "crop to this exact box" vs. "crop to keep the speaker in frame" (needs a subject decision this skill doesn't make), plus one sentence stating the general rule: same input + same explicit parameters -> same verifiable output stays here; anything depending on taste or understanding goes to whichever skill or agent makes that call. Docs-only; no behaviour changed. Closes [#53](https://github.com/kajisho5/ffmpeg-skill/issues/53).
- **`references/ci-platform-pitfalls.md`: known per-OS ffmpeg/CI behaviour differences.** Several fixes in this repo exist only because of platform-specific, empirically observed behaviour (Windows Chocolatey ffmpeg lacking `-pattern_type glob` support, the concat demuxer's end-of-list duration trick over-counting by a frame, `#!/bin/sh` PATH shims not being portable to Windows, Windows reporting a crashed ffmpeg subprocess's exit code differently from what this repo captured, and macOS's libvidstab build disagreeing with Linux's on whether a shake fixture got better or worse) — each was independently diagnosed once, at the cost of a full CI cycle and log-reading. Writing them down means the next platform-only test failure gets checked against this list before spending another cycle re-diagnosing it. Docs-only; no behaviour changed.
- **`proxy.py`: low-bitrate proxy for downstream AI analysis, preview and editing decisions.** No tool here served a "cheap for a machine to decode" output distinct from `export.py`'s delivery presets, which all target near-visually-lossless platform delivery (CRF 18-24) rather than size/speed. `proxy.py` resizes to `--width` (default 640) or by `--scale` factor, re-encodes at a proxy-grade `--crf` (default 30) with the fastest x264/x265 preset, supports `--fps` and `--no-audio`, and keeps the source's own dynamic range (an HDR source proxies to HEVC10, same as every other re-encoding tool here — run `color.py --to-sdr` first if SDR is wanted). Pure mechanical resize+re-encode, same primitives `fit.py`/`export.py` already use: no new dependency, no GPU requirement, works identically regardless of source resolution (1080p/4K/6K/8K) or codec (H.264/H.265/ProRes, since ffmpeg's own decoders are already codec-agnostic everywhere in this repo). This tool only executes the spec it is given — it does not decide which asset should be proxied or what the proxy will be used for; that stays with the calling agent. `capability_map` gains `media.proxy` -> `proxy` (see below). Tests cover default width/CRF, `--scale`/`--no-audio`, forcing CFR on a VFR source, HDR passthrough, and dry-run.
- **`contract --json`: `capability_map`.** `provides` re-indexes each tool by an id shaped like its own name (`ffmpeg-skill.cut`); it doesn't let a planner that only knows an abstract goal ("I need to trim a video") find the right tool. `capability_map` is a new, small, hand-authored table: `[{"capability": "<domain>.<verb>", "tool_id": "ffmpeg-skill/<tool>", "params": {...}}, ...]`, covering `video.trim`, `video.reframe` (pins `fit` to `fit=crop`, since `fit.py` also duration-fits and pads), `audio.loudness`, `subtitle.burn`, `media.stream.inspect`, `media.frames.extract` and `media.proxy`. It is purely descriptive — a caller still builds and runs the named tool's own CLI/MCP call from its `input_schema`; this skill never picks a capability or executes on the caller's behalf. Deliberately excludes anything that would require judgment to resolve (no `video.highlight`, since `scenes.py --highlights` ranks by a measured proxy, not understood content). `docs/contract.md` documents the table and why it stays short; `tests/test_contract.py` verifies every entry resolves to a real tool and real params. Additive; no existing field changed.
- **`doctor`: this installed copy's own `version`.** `doctor --json` and the human-readable `doctor` now report the version of the copy answering, read locally from its own `package.json` (same value `contract --json`'s `skill.version` reports) — never fetched from the network, never compared against the latest published release. A copy installed with `npx ffmpeg-skill` is not updated automatically; the human-readable output and the installer `--help`/README Quick start now say to re-run the installer to refresh it. Additive; every existing `doctor` key is unchanged.
- **`doctor`: `ok` vs. per-tool `usable` clarified.** The human-readable `doctor` output now adds one line when `ok` is true but at least one tool's `usable` isn't `"yes"` (e.g. a plain Homebrew `ffmpeg` on macOS: overall `ok` since nothing required by *every* tool is missing, while `caption.py` specifically can't run). README Quick start says the same. No field changed, no behaviour changed — a caller reading `doctor` no longer has to already know to check `tools` separately from `ok`.
- **`doctor`'s Windows fix hint for a missing subtitles/drawtext/zscale filter** now names the same remedy README documents for that platform (`winget install Gyan.FFmpeg`, since the gyan.dev full build carries them and a plain choco package can lack them) instead of falling through to a generic "install/build it" message — matching the existing macOS `brew install ffmpeg-full` hint. No change on any other platform.
- **`doctor`'s own introspection calls get a 10s timeout.** `ffmpeg -filters`/`-encoders`/`-bsfs`/`-version` are meant to be fast, bounded, non-media operations; a hang here would silently freeze the one tool meant to report whether the machine is broken. They now time out and report `failed` rather than blocking forever. Deliberately NOT applied to any tool's actual media-processing ffmpeg invocation (cut, fit, caption, ...): a legitimate long re-encode must not be killed by an arbitrary ceiling. `-nostdin` was already passed everywhere (0.9.0), so a hang waiting on stdin was not possible; this closes the other silent-hang path. See README, "Requirements", for what remains the caller's own responsibility.
- **`tests/test_contract.py` now runs on Windows CI.** Only two spots (`test_dry_run_never_runs_ffmpeg_and_writes_nothing` and the whole `DoctorDetectionTests` class) actually depend on a POSIX `#!/bin/sh` PATH shim to force specific FFmpeg fixture layouts; everything else in the file — contract schema, `reencodes_*`, `doctor.tools`, MCP derivation, and every tool exercised through the contract including `cut.py`'s provenance fields — already ran against the real `ffmpeg` on whichever OS the test ran on, but CI skipped the *entire file* on Windows regardless. The two shim-dependent spots are now `skipIf`'d individually (visible as `skipped` in the Windows job's log, not silently absent) and CI runs the rest of the file on all three OSes. Doing this surfaced a real, previously-invisible bug: `test_contract_from_installed_copy` redirects the installer's target directory by overriding `HOME`, which Node's `os.homedir()` ignores on Windows (it reads `USERPROFILE`), so the test silently installed into the runner's real home directory instead of its temp one and then failed to find the file it expected — fixed by setting both. See README, "Development".
- **Test: `cut.py`'s copy-mode keyframe snap can genuinely change the output's duration, not just its precision label.** A non-keyframe-aligned `--start`/`--end` within `--tolerance` stays in fast stream-copy mode (`mode: "copy"`), but the underlying `-ss` seek still snaps to an earlier keyframe and pulls in extra content — `output_duration` and `requested_duration` can diverge by more than a rounding error while `keyframe_snapped` stays `true`. This was already reported in `cut.py --json` (0.10.0); a new test in `tests/test_all.py` pins a real, measured, non-trivial divergence so a regression that silently reports `duration_delta_seconds: 0.0` in this scenario would be caught. No field or behaviour changed.
- **Fail loudly: `verify_output()` is now the single success criterion for every writing tool.**
  Audit of the execution chain (natural language → script → real ffmpeg → exit status → output
  verification → report) against 17 input/ffmpeg failure scenarios and a fake ffmpeg that exits 0
  with an empty output. Every scenario already failed with a non-zero exit; the fixes below make
  the failures precise and leave nothing misleading behind.
  - `verify_output()` in `_common.py`: exists, non-empty, ffprobe reads a stream. `emit()` runs it
    before printing any success, with or without `--json`.
  - Output problems are reported as `kind: "output"` ("output verification failed: <path>: not
    written | 0 bytes | ffprobe cannot read it"), no longer as an input error; a 0-byte artifact
    is removed.
  - Failure JSON carries `exit_code` and `commands` (what was planned or run) next to
    `error.kind` / `error.message`. ffmpeg failures raised by cut, loudness, silence and sync
    carry `kind: "ffmpeg"`.
  - `fit.py --fps 0` was silently treated as "no fps requested"; it is now an error.
  - SKILL.md: what "done" means (exit 0 and a probe that matches the request), and a `Failed:`
    report shape.
  - Tests: input failures (missing, corrupt, empty, wrong stream, beyond duration, bad fps),
    ffmpeg failures (invalid LUT, unwritable directory, unknown container), output verification
    with a fake ffmpeg across nine tools, no partial files left behind.
  - Evals: `evals/agent_prompts_exec.json`, five success and five failure prompts graded for real
    execution (an ffprobe-readable output exists) and honest failure (no `Done:` and no output
    when the tool failed).
- **`fit.py --rotate`/`--flip`.** New rotate 90/180/270 (clockwise; 90/270 swap width and
  height) and horizontal/vertical flip flags -- distinct from the rotation *metadata* fit.py
  already reads to size a source correctly, which is never altered by these. Verified against
  a real red/left, blue/right test fixture: `--flip h` swaps the two halves and `--rotate 90`
  rotates the left column into the top row, both confirmed pixel-exact, not just by output
  dimensions.
- **`overlay.py --video`: video-on-video picture-in-picture.** `overlay.py` could only
  composite a still image or text onto a video; there was no way to place a second *video* as
  a layer. `--video CLIP` composites it with the same `--position`/`--scale`/`--opacity`/
  `--start`/`--end` knobs `--image` already has (`scale2ref`-style scale + `format=yuva420p` +
  `colorchannelmixer` for opacity + `overlay` with a timeline `enable`). Only the main input's
  audio is kept; the PiP layer's own audio is dropped -- mixing two audio tracks is a job for
  `audio.py`. Verified with a real composite: a blue clip lands at the exact expected
  bottom-right pixel position, the rest of the frame is unaffected.
- **`overlay.py --chromakey`: green-screen compositing.** With `--video`, `--chromakey COLOR`
  (plus `--chromakey-similarity`/`--chromakey-blend`) keys that colour transparent before
  compositing, for green-screen foreground-over-background work. Verified: a green background
  behind a white square is correctly replaced by the destination clip's colour, the white
  square is untouched.
- **`insert.py --zoom`/`--pan`: Ken Burns effect.** A slow linear zoom in/out (`--zoom-amount`
  sets the end/start factor, default 1.3) and, with `--zoom`, a pan across the image while
  zoomed, built from typed enums into a generated `zoompan` expression -- never a raw
  expression from the caller. Verified against a real image with a centred marker at a known
  position: the exact screen pixel the marker's edge should reach at the final zoom factor
  changes from background to marker colour between the first and last frame, and a panned
  clip differs (PSNR ~13) from the same zoom without pan at the same timestamp -- proving the
  frame actually changes scale/position over the clip, not just that the command ran.
- **`background.py`: generate a solid-colour or gradient clip.** New tool, no input file:
  ffmpeg's own `color`/`gradients` source filters generate an exact-size, exact-duration clip
  directly, for a title-card background or a base layer for `overlay.py` to composite onto.
  Verified: a solid-colour clip's pixel matches the requested colour; a gradient's left and
  right edges are measurably different colours in the requested direction.
- **`reverse.py`: reverse playback.** New tool wrapping ffmpeg's `reverse`/`areverse` filters
  (video always, audio unless `--no-audio`). These filters buffer the whole clip in memory, so
  this is for clips it makes sense to reverse (seconds to a couple of minutes) rather than
  something the tool limits for the caller. Verified against a real two-colour clip (first
  half red, second half blue): the reversed output starts with the original's last half and
  ends with its first half, confirmed by sampled pixel colour, not just duration/dimensions.
- **`stabilize.py`: motion stabilisation.** New tool wrapping ffmpeg's two-pass
  `vidstabdetect`/`vidstabtransform` (`--shakiness`, `--smoothing`, `--zoom` to hide the black
  edges stabilizing can introduce). The transforms file passed between the two passes lives in
  a `tempfile.TemporaryDirectory` for the run only -- this is the first tool in the codebase to
  need an on-disk intermediate between two ffmpeg passes (existing two-pass tools, like
  `loudness.py`, pass their intermediate measurement through stdout JSON instead). Requires an
  ffmpeg built with `--enable-libvidstab`; `doctor` correctly reports `stabilize` as
  `usable: no` (not a crash) on builds that lack it, such as Homebrew's default macOS build --
  verified against this repo's own `ffmpeg_filters_8.1.2_macos.txt` fixture, where
  `vidstabdetect`/`vidstabtransform` are genuinely absent from the real `-filters` listing.
  Verified the actual stabilizing effect, not just that the command runs: a synthetic shaky
  clip's measured frame-to-frame motion (via `signalstats` on a `tblend=difference` pass) drops
  from ~7.4 to ~2.9 after stabilization.
- **`sequence.py`: numbered/globbed image sequence to video.** New tool: `--pattern` accepts
  either a printf-style numbered pattern (`frame_%04d.png`) or a glob (`*.png`, sorted
  alphabetically), with the match checked against the real filesystem before ffmpeg runs (an
  empty match or a missing first frame is refused here, not discovered from an opaque ffmpeg
  error). Verified frame order is preserved end to end with a real 5-frame red/blue/red/blue/red
  sequence, both in numbered and glob mode.

- **`fit.py --height`.** Only `--width` existed ("output width ... height follows the aspect").
  Added a symmetric `--height` that mirrors `join.py`'s existing width/height resolution: give
  one and the other follows the aspect (the source aspect, or `--aspect` if also given); give
  both for an exact frame. `--width` alone still behaves exactly as before.
- **`crop.py`: crop to an exact pixel rectangle.** `fit.py --fit crop` crops to a target *aspect
  ratio*, computing the rectangle itself; there was no way to crop to a rectangle the caller
  already knows (a face-detection box, a saved crop, a hand-picked region). New tool takes
  `--x --y --width --height` in source pixels, validated before ffmpeg runs: refuses negative
  offsets, non-positive or odd width/height (4:2:0 chroma, this codebase's even-size convention
  — refused rather than silently rounded, since a caller-specified rectangle should do exactly
  what was asked or fail loudly), and a rectangle that doesn't fit inside the source frame
  (accounting for display rotation).
- **`insert.py`: still image to a timed silent video clip.** Given one image, a duration, and
  optional target frame size / fps, produces a silent, constant-frame-rate clip of exactly that
  duration and size — for title cards, end slates, or placeholders alongside real footage in
  `join.py`. `--width`/`--height` resolve the same way `fit.py`'s do (one given -> the other
  follows the image's aspect; both given -> exact frame, scaled to fill and centre-cropped, never
  distorted). Refuses non-positive `--duration`/`--fps`.
- **`join.py`: joining two or more audio-less clips together failed.** Each clip missing an audio
  track gets a synthetic silent input (`-f lavfi -i anullsrc=...`) appended to the ffmpeg command;
  the filtergraph index for that input was computed as `n + len(extra_inputs)`, but
  `extra_inputs` is a flat argv list (six tokens per synthetic input: `-f`, `lavfi`, `-t`,
  duration, `-i`, `anullsrc=...`), not a count of inputs added so far. With exactly one no-audio
  clip the two counts happen to coincide (`n + 0`); from the second no-audio clip onward the
  computed index overshoots the real one by a multiple of 6, and ffmpeg refused the whole command
  with "Invalid file index" naming an input far past the actual count. Found joining five real,
  audio-less camera samples (a genuine multi-camera source with no audio channel is not an edge
  case in real footage). Fixed by tracking the number of synthetic inputs added directly, instead
  of inferring it from the argv list's length. No change to the single-no-audio-clip path, which
  was already correct.

## 0.10.0 — 2026-09-06 — FFmpeg 8+/Windows compatibility, per-tool doctor/contract usability, provenance and honesty fixes

- **`doctor --json`: per-tool `usable`.** `doctor` reported capability-level `available`/`missing`/`unknown`, but a caller had to cross-reference each tool's own required capabilities by hand to answer "can I run `caption.py` on this machine today" -- a plain Homebrew `ffmpeg` on macOS is `ok` overall (nothing *required by every tool* is missing) while `caption.py` specifically cannot run at all. The new `tools` field folds the same per-capability state into `{"<tool>": {"usable": "yes"|"no"|"unknown", "missing": [...], "fix": "one-line remedy", "unknown": [...]}}` per tool, following the same "unknown is not missing" rule doctor already uses. Additive; every existing `doctor` key is unchanged.
- **`contract --json`: `reencodes_video`/`reencodes_audio` per tool.** Each of the 21 tools now declares, per stream type, `"always"` / `"never"` / `"conditional"` (with a `reencode_note` for the conditional ones), read from what each script's own encode/copy args actually do. Surfaces a fact that wasn't documented anywhere: `fit`, `caption`, `overlay`, `graphics`, `color`, `join`, `multicam` and `silence` always transcode audio to AAC alongside a video filter — there is no `-c:a copy` path in this codebase for a tool that also re-encodes video, so a caller cannot assume the original audio codec survives a picture-only edit. `caption.py`'s docstring now says plainly that burn-in is the only mode (no soft-subtitle mux) and always re-encodes both streams. Additive contract field; no tool's behaviour changed.
- **SKILL.md: explicit "what this skill does and does not decide".** Added a section naming what belongs to a production agent (approval, which cut is right), another skill (thumbnail composition), or nobody in this skill (content understanding, judging a highlight's interest beyond a measured proxy) -- and an explicit rule against ever falling back to a raw `ffmpeg`/`filter_complex` invocation when a request needs something none of the 21 scripts expose. The trigger description (frontmatter) is intentionally left as-is: it stays broad on purpose (any video/audio file touch), since narrowing it risks under-triggering on requests that do belong here; what changed is what the skill does once triggered. `evals/agent_prompts_24.json` gains one refusal case (`r05-no-raw-ffmpeg`) asking directly for a raw `-filter_complex` command.
- **`check.py`: plain-language `reason` on the less obvious FAILs.** Every row already had `fix` (the command that resolves it); video codec, pixel format, HDR colour and loudness FAILs now also carry `reason` ("QuickTime and iOS commonly reject video that isn't 8-bit 4:2:0") for a caller reporting the result to someone who doesn't already know why the spec value matters. Empty on PASS rows and every other check. Additive, no existing field changed.
- **`cut.py --json`: full requested-vs-actual provenance.** `expected_duration`/`duration_error_ms`/`precision`/`reencoded` already existed (0.9.1); added `requested_start`/`requested_end` (or `requested_segments` for `--segments`), `requested_duration`, `output_duration`, `duration_delta_seconds` (seconds-unit alias of `duration_error_ms`) and `mode` (`copy`/`accurate`/`hybrid` — "hybrid" means a lossless cut silently re-encoded because the keyframe snap exceeded `--tolerance`) and `keyframe_snapped`. Additive only, no existing field changed. Intended for a downstream repo (an editing skill, an agent) that wants this in its own provenance/audit trail without re-deriving it from `reencoded`+`precision`.
- **`render.py`'s check stage now sets the exit code.** A `project.json` with a `"check"` stage always returned 0, even when the delivery-spec check failed or `check.py` itself couldn't run — `render.py` was the one tool in the skill that could report a broken deliverable as a success. It now exits 1 in both cases, matching `check.py`'s own exit code exactly; `--json`'s `check` field still carries the full row-by-row result either way, and the output file is still written (this changes the exit code, not what gets rendered).
- **Test: docstring examples can't drift from the parser.** `scenes.py`'s docstring once claimed a ranking option (motion) that was never implemented; that was prose, not an example, so nothing caught it. A new `test_contract.py` test at least closes the more common version of this gap: every `--flag` used in a script's own `Examples:` lines must exist in that script's real argparse parser, checked via the contract's `input_schema`. Verified to catch a deliberately introduced typo before writing this entry. Does not (and cannot) catch a false claim made only in prose.
- **SKILL.md: explicit language-matching instruction.** The agent has always been graded on replying in the user's language (see the 24-prompt eval), but SKILL.md never actually said to — it worked by the model's own default, not by instruction. The Report format section now says explicitly: reply in whatever language the request was written in (Japanese, English, Chinese, or any other), keep only the field labels (`Done:`, `Steps:`, ...) in English, and follow a language switch mid-conversation. No code change; this only affects the model-facing instructions.
- **`multicam.py` low-confidence warning.** `sync.py` warns on stderr when its cross-correlation confidence is below 0.1 ("check that both files contain the same audio event"); `multicam.py` used the same measurement per camera but never warned, even though it applies the offset to a rendered cut rather than just reporting it. It now warns per camera below the same threshold. SKILL.md's existing "check `confidence` before trusting a sync" guidance now names `multicam.py`'s per-camera confidence explicitly.
- **`sync.py`/`multicam.py` documentation: audio sync is not lip sync.** Both align audio tracks to each other by cross-correlation; neither has ever done any face or mouth detection, and a high `confidence` only means the audio matched well, not that the final picture looks in sync. This was previously undocumented; `sync.py`'s docstring, `multicam.py`'s docstring and SKILL.md now say so explicitly. No behaviour change.
- **`export.py --preset copy`.** Every existing preset re-encodes (even `prores`/`h265`, which
  keep the source resolution). A caller with nothing to change — the deliverable already matches
  the source, no platform target — had no way to get a real, delivered file out of `export.py`
  without paying for and risking a needless re-encode. `copy` is a genuine stream copy (`-c:v
  copy -c:a copy`, no `-an` unless the source truly has no audio track): same codecs, same
  container (keeps the source's own extension unless `-o` names one), same colour tags — it
  skips the CFR-conforming (`-r`/`-fps_mode cfr`) and BT.709-retagging steps every re-encoding
  preset applies, since neither is meaningful (or safe) without decoding the picture, and it
  never issues the HDR "outputs SDR BT.709 tags" warning other presets do, because it doesn't
  touch colour at all. `-movflags +faststart` still applies when the resolved output is `.mp4`
  (a real optimisation a copy can do for free). Verified codec/resolution/frame-count/HDR-tags
  stay byte-for-byte the source's, not just nominally unchanged (frame count via `ffprobe
  -count_frames`, which a re-encode could silently drop or duplicate).

- **`scenes.py --rank-by`.** `--highlights` ranked candidate scenes by audio energy only, and the docstring falsely claimed motion was also used (it never was — dead documentation). `--rank-by {audio,duration}` (default audio, unchanged) makes the criterion explicit and adds a real second option (longest scene first); the result JSON now reports `highlights_rank_by`.
- **`fit.py --crop-x` / `--crop-y`.** `--fit crop` always cropped from the centre, so reframing a wide shot to 9:16 could cut off a subject held to one side (a product, a person off-centre). `--crop-x`/`--crop-y` (0=left/top, 0.5=centre default, 1=right/bottom) pick which edge to keep instead; range-checked before ffmpeg runs. No change to the default (centre) behaviour.
- **Filter file paths on Windows.** `subtitles=`, `ass=`, `lut3d=file=`, `fontfile=` and `fontsdir=` values are parsed twice by ffmpeg (graph, then filter options), so a drive letter needs two levels of colon escaping (`D\\\\:/x.srt`). 0.9.1 escaped once and every caption / LUT job on Windows failed with `Unable to parse "original_size" option value` or `Error parsing a filter description`. `escape_filter_path` now escapes for both passes; `;` is escaped too. Reproduced and tested on Linux with a directory literally named `D:` plus spaces and non-ASCII in the path.
- **`overlay.py --image` length on FFmpeg 7+.** `-shortest` alone left up to 2 s of the looped still after the video ended (8.1 / 9.0); the command now also passes `-t <video duration>`.
- **`--help` on a legacy Windows console.** stdout / stderr are reconfigured to UTF-8 (with replacement) by `_common`, so non-ASCII help text (Japanese example, arrows) no longer raises `UnicodeEncodeError`; the test harness decodes script output as UTF-8.
- **macOS CI** installs `ffmpeg-full`: Homebrew's `ffmpeg` formula no longer links libass / freetype / harfbuzz / zimg, so it has no `subtitles`, `ass`, `drawtext` or `zscale` filter. README, the installer hint and `_common`'s own `require_tool` error message (`INSTALL_HINTS`) all say so now.
- Tests: the contract-test fixture used `-vsync vfr`, an option FFmpeg 9 removed (`-fps_mode vfr` since 5.1); filter paths with a drive colon, spaces and Unicode through caption (SRT, ASS, fonts dir), color (LUT full and blended) and overlay (`fontfile`), with PSNR proving the caption and LUT changed the picture; overlay still bounded by the video length; `--help` under a cp1252 console.
- **`provides`**: `contract --json` gains a top-level `provides` field listing all 21 tools by a cross-repository Capability id (`ffmpeg-skill.<tool>`) for `kajisho5/AI-video-production-OS`'s `CapabilityContract.provides` — see `docs/contract.md`.

## 0.9.2 — typed primary colour correction

- **color.py**: `--correct` (exposure / contrast / saturation / white balance), a fourth colour mode
  alongside `--to-sdr` / `--lut` / `--retag` / `--strip-dovi`. Each flag is one option of one real,
  always-available libavfilter filter — `--exposure` (`exposure` filter, -3..3 stops), `--contrast` /
  `--saturation` (`eq` filter, 0..2, 1=unchanged), `--temperature` (`colortemperature`, 2000..12000 K,
  6500=unchanged) and `--tint` (green -1 .. +1 magenta, mapped to `colorbalance`'s three midtone
  channels: `gm=-tint`, `rm=bm=tint/2`) — range-checked against this script's own safe subset of what
  each filter documents (`ffmpeg -h filter=<name>`) before ffmpeg runs; no filter string, `filter_complex`
  or raw argv is ever accepted from the caller. The four stages (exposure → white balance → contrast →
  saturation) are always chained in that fixed order, each one always present at its filter's own
  documented no-op default, so the pipeline is one stable four-filter chain regardless of which flags
  were given. `--json`'s `measurements` field carries `analyze_levels()` (signalstats luma/saturation)
  for the input and the output side by side — an OBSERVED technical measurement, never a "looks better"
  judgement.
- Contract: `color`'s optional capabilities gain `filter:exposure` / `filter:eq` / `filter:colorbalance` /
  `filter:colortemperature` (declared `when: "--correct"`); `X264` now also lists `--correct` among its
  callers. No change to any existing flag, contract field, MCP schema or tool semantics.
- Tests: 4 real-media tests in `tests/test_all.py` (defaults are near-identity, positive exposure raises
  measured luma, `--saturation 0` desaturates, temperature/tint run and preserve geometry, five
  out-of-range parameters are each refused with no partial output).

## 0.9.1 — FFmpeg 8 capability detection; audio extraction, audio join, sample-accurate trims, typed dynamics

- **doctor / contract on FFmpeg 8.** `ffmpeg -filters` prints two flag characters on FFmpeg 8 (`T. acompressor A->A`) where 6 and 7 print three (`..C`); 0.9.0 anchored on three and reported every `filter:*` capability missing on FFmpeg 8 (macOS / Windows CI of consumers). Rows are now recognised by their `A->A` io-spec token, encoders by the `------` separator, so the flag width no longer matters. A listing that cannot be read yields a third state, `unknown`, distinct from `missing` (an installed filter is never reported absent) and from `available` (a failed detection is never a pass); `detection` and `errors` say which listing failed and why; exit 2 for "required but unknown". Existing keys unchanged. Fixtures for the 6.1 capture and the 7 / 8 layouts in `tests/fixtures/`, tests through a fake ffmpeg.
- **audio.py**: an audio output extension on a video input drops the picture (`audio.py talk.mp4 -o talk.wav` extracts; `--voice -o talk.m4a` cleans on the way) instead of failing inside the WAV muxer; `--audio-stream N` picks a track (`probe` lists `audio_streams`). Typed dynamics: `--compress` (`--comp-threshold/-ratio/-attack/-release/-makeup/-knee`), `--limit` (`--limit-ceiling/-attack/-release`), `--gate` (`--gate-threshold/-ratio/-attack/-release/-range/-knee`), each flag one documented option of acompressor / alimiter / agate, range-checked before ffmpeg runs, dB converted to the linear value the filter takes; no filter string is accepted from the caller.
- **join.py**: audio-only inputs (WAV, FLAC, MP3, M4A, ...) are joined as audio at one sample rate (first clip's, `--sample-rate`) and channel layout (widest, `--channels`), with `acrossfade` or a butt join; the output must have an audio extension; audio and video inputs cannot be mixed. Contract: `join` is `audio_only: true`, `video_required: false`.
- **cut.py**: the codec follows the output extension on re-encode (`-o x.wav` is PCM; a `.wav` never receives AAC packets, which 0.9.0 wrote on `--accurate` and on the keyframe fallback for audio inputs); an audio extension on a video input extracts the audio; audio stream copies seek on the output side so `-c copy` lands on the packet, not the previous video keyframe; `--accurate` on audio trims at the sample (`atrim`). The JSON reports `precision` (`packet` / `sample` / `codec_frame` / `frame`), `duration_error_ms` and `reencoded`. Measured: WAV copy within 2 ms, `--accurate` WAV / FLAC / AAC-to-WAV exact to the sample at 44.1 and 48 kHz, AAC output +21 ms (encoder priming, reported as `codec_frame`).
- `probe` adds `audio_streams` (index, codec, channels, layout, sample rate, language, title).
- Tests: 5 doctor detection tests (FFmpeg 6 / 7 / 8 layouts, garbage, failure), 4 audio tests (extraction and stream selection, audio join, measured precision, typed dynamics); evals `evals/agent_prompts_audio2.json`.

## 0.9.0 — machine-readable execution contract

`ffmpeg-skill contract --json` (`python3 scripts/_contract.py --json`) describes the skill for agent frameworks: `contract_version` 1.0 separate from the skill version; one ToolSpec per public script (`ffmpeg-skill/<name>`) with an input schema generated from its argparse parser, an output schema, role (analysis / analysis_and_execution / execution / verification), required and conditional ffmpeg capabilities, dry-run support, `mutates_input: false`, the verification tools to run afterwards, and whether a visual check is required. `ffmpeg-skill doctor` reports which capabilities the machine has. `docs/contract.md` explains the fields and how a planner consumes them.

- `--json` results now carry `"status": "completed"`; failures under `--json` also print `{"status": "failed", "error": {"kind", "message"}}` on stdout (stderr message and exit codes unchanged).
- `--dry-run` no longer writes the generated SRT (`caption.py --text`) or the HTML (`report.py`).
- MCP server lists `batch` (the one script it was missing); `tools/list` now equals the contract's tool list, and a test keeps it that way.
- MCP `tools/list` is derived from the contract: no tool table or hand-written `inputSchema` in `mcp/server.py` any more. Names, order, `inputSchema` (translated from `ToolSpec.input_schema`: types, enums, defaults, descriptions, required fields, mutually exclusive groups, the non-canonical `argv` branch) and the structured-argument mapping all come from `scripts/_contract.py`. Tests: schema equality for all 21 tools, byte-identical `tools/list`, drift (add / remove / edit a script), and JSON-RPC round trips of probe, cut, silence, loudness, export and render built from the derived schema.
- Installer copies `package.json` so an installed skill knows its version, and answers `contract` / `doctor`.
- `tests/test_contract.py` (unit + integration, including a fake-ffmpeg dry-run guard and the real-device corpus when present), `evals/contract/`, `npm run release-check` extended.
- No new editing features; no script changed its media behaviour.

## 0.8.5 — audio-only inputs, spelled out

- SKILL.md: "Audio-only files" section. WAV, FLAC, MP3, M4A/AAC, OGG and Opus go through `probe`, `cut`, `silence`, `loudness`, `audio`, `sync` and `check --platform podcast` unchanged; the output extension picks the codec; `Look: not needed`; picture scripts refuse with "input has no video stream". Six audio-only request→script rows.
- Evals: six audio-only agent prompts (`evals/agent_prompts_audio.json`), grader checks that audio-only runs use no picture script and mark the visual check not needed, routing tasks 25–29, two audio-only trigger cases. First run: 6/6 on every criterion.
- Test for WAV/M4A/MP3 through the audio scripts (56 tests).
- GitHub Sponsors: `.github/FUNDING.yml` and a Support section in the README.

## 0.8.4 — three repeats, independent grading

The 24-prompt evaluation was run three times (72 agent runs, `evals/results/iteration-2-4.json`) and every run was graded by a separate model (`evals/results/iteration-2-4-independent-grades.json`): routing 72/72, honest 72/72, user's language 72/72, report format 71/72, visual check whenever the picture changed 24/24, mean quality 4.9 / 5. Script choices were identical across repeats; only defaults (crop vs pad, silence margin) varied.

- `overlay.py --fade` without `--start`/`--end` now fades in at 0 and out at the end of the video (it was silently ignored; found by an agent during the runs).
- `--dry-run` no longer prints "wrote <file>" for a file that was not written (central fix in `_common.info`).

## 0.8.3 — internals and triggering

- `_common.py`: the shared flag state is an explicit `Context` object (`STATE.dry_run` etc., dict-style access kept), `run()` is split into recording, dry-run, captured and progress paths with one failure handler. Behaviour unchanged: 54/54 tests and the sync benchmark give identical numbers before and after.
- `sync.py`: the 35 % minimum-overlap and the square-root overlap weight are named constants with the benchmark rationale (what 0.2 / 0.5 and exponents 0.25 / 1.0 did) written next to them.
- Trigger tests (`evals/trigger/`): 10 should-trigger and 10 should-not requests judged by an independent model against a catalog with four decoy skills. 20/20 on this description.

## 0.8.2 — second agent-run evaluation

24 prompts (12 English edits, 8 Japanese edits, 4 that must be declined) run by independent agents against the 0.8.1 skill (`evals/agent_prompts_24.json`, `evals/grade_runs_24.py`, `evals/results/iteration-2.json`). Routing 24/24, honest refusals 4/4, Japanese reports 9/9, visual check whenever the picture changed 8/8, mean 6.5 commands per job.

- `caption.py --text` now writes the generated SRT beside the output file, not beside the source.
- `probe.py` accepts the common flags (`--json`, `--field` etc.) like every other script.
- `audio.py`: `--music-fade-out` fades only the bed; `--fade-out` fades the whole mix (previously both were applied at once). `render.py` project audio gained `music_fade_out`.
- SKILL.md: how to find a CJK font before burning Japanese captions.
- Tests for all of the above; render test no longer depends on a clean output directory.

## 0.8.1 — skill craft

The skill file itself, measured. Six realistic prompts were run by independent agents with the old and the restructured SKILL.md (`evals/agent_prompts.json`, `evals/grade_runs.py`, results in `evals/results/`).

- SKILL.md rewritten for the agent, not as a catalogue: a description that says when to trigger; body 402 → 169 lines with workflow, what to ask vs assume, request→script map, report format and "looks right but is wrong" pitfalls; per-script CLI reference moved to `references/scripts.md`, real-device notes to `references/devices.md` (both installed and packaged).
- Results: routing 100 % for both versions; mean commands per job 9.0 → 7.7 (the Reels job went from 16 commands with a forced redo to a single `render.py` pass); report format followed 4/6 → 6/6.
- Found and fixed from the transcripts: `check.py` warned on untagged 8-bit H.264 and agents added a pointless retag (now PASS); `look.py --at` stamped 00:00:00.000 on every frame (now the requested time); the "fix FAILs" instruction made an agent boost -44 LUFS park ambience by 30 dB (check step reworded, pitfall added).

## 0.8.0 — validation release

Measured instead of assumed. New `tests/corpus.py` pulls public real-device videos (GoPro HERO 4K 10-bit, DJI 4K60 no-audio, two iPhones incl. Dolby Vision 4K60, two Android screen recordings incl. 18 fps VFR and 120 fps, an HDR10 PQ test pattern, a 24p clip, and Blender's Tears of Steel) and runs `verify.py` over them; `tests/bench_*.py` score algorithms against known ground truth.

- `sync.py`: normalised cross-correlation over the overlap (prefix-sum energies) with a runner-up-aware confidence. Lags with under 35 % overlap are ignored and scores carry a sqrt(overlap) weight so partial coincidental matches cannot beat the true alignment. Benchmark on real dialogue/music (±30 s offsets, gain, noise, EQ): 120 s windows 40/40 within 10 ms (max 1.1 ms); 60 s stress windows went from 86 % to 95 %, with 4 of the 5 remaining misses flagged by confidence < 0.3.
- `scenes.py`: cuts are now one-frame spikes (score above threshold and > 3× the neighbouring median), not any frame over a threshold; motion, flashes and pans stop registering. `--ratio` added. Benchmark on 53 hard cuts between single-take corpus clips: precision 0.95, recall 1.00 (F1 0.97) at the default threshold 8; 0.98 / 0.94 at 12.
- `loudness.py`: silent input is reported (`"silent": true`) instead of crashing; normalisation refuses with a clear message.
- `verify.py`: tone-maps the HDR-preserved cut instead of the whole file (a 10-minute 4K HDR source timed out).
- Corpus results: 90/92 verify steps pass on first run; both failures fixed above. Silence benchmark: 0 missed gaps, ≤1 ms leftover silence over 20 cases.
- SKILL.md: sync guidance now cites the benchmark and the 4× window rule.

## 0.7.0

- `mcp/server.py` (new): the whole toolkit as an MCP server over stdio (JSON-RPC 2.0, standard library only). Every script is a tool; named args or raw argv; results as structured JSON. Installed alongside scripts by `npx ffmpeg-skill`.
- `batch.py` (new): apply a step recipe or a render project to every file in a folder, content-hash cache so re-runs only touch changed files, `--watch` polling.
- `caption.py --transcribe`: optional local speech-to-text bridge (whisper.cpp `whisper-cli`, faster-whisper, or openai-whisper if present). Never required; a clear install hint otherwise.
- Tests: 49 end-to-end cases.

## 0.6.0

- `graphics.py` (new): motion-graphics templates with no image assets — lower-third (slide in/out), title card, chapter chip, progress bar, countdown, corner bug — coloured from brand.json.
- `brand.json` support: fonts, colours, logo (position/scale/opacity), safe margin, caption defaults. `caption.py --brand`, `overlay.py --brand --logo`, `graphics.py --brand`, and a `"brand"` key in `render.py` projects (plus a `graphics` stage and `{"logo": true}` overlays).
- `report.py` (new): single-file HTML delivery report with before/after contact sheets, media facts, loudness, compliance table and the commands run.
- Tests: 46 end-to-end cases.

## 0.5.0

- `render.py` (new): declarative edits from one `project.json` (clips → join → silence → fit → captions → overlays → audio → loudness → export → check). `--init` writes a starter, `--dry-run` prints every command, `--stop-after` for iterating.
- `scenes.py` (new): scene changes (scdet) and audio peaks, highlight proposals sized to a target duration, `--edl` for `cut.py --segments`, per-scene contact sheet.
- `check.py` (new): pre-delivery compliance for youtube / shorts / reels / tiktok / x / linkedin / broadcast / podcast / custom: duration, aspect, resolution, fps, VFR, codec, pixel format, colour/HDR, file size, loudness, true peak, with the fix command per failure.
- `evals/`: 24 natural-language routing tasks with expected scripts, plus a transcript scorer.
- `.github/workflows/ci.yml`: 3-OS matrix, manual trigger only until the Actions quota resets.
- `join.py`: `--width` alone keeps the first clip's aspect; `--fast` no longer breaks `export.py` presets.

## 0.4.1

Fixes found by running `verify.py` on a real iPhone clip (Dolby Vision 8.4 / HLG, 10-bit HEVC, 60 fps VFR, portrait rotation, extra metadata tracks):

- HDR sources now stay HDR through every re-encode (`cut`, `fit`, `caption`, `overlay`, `silence`, `join`, `multicam`, `sync`): HEVC Main10 with the source's HLG/PQ tags instead of an 8-bit H.264 file mislabelled BT.709. Use `color.py --to-sdr` when you want SDR.
- Audio mapping uses the first audio stream only (`0:a:0?`); iPhone `.mov` files carry timecode/metadata tracks that broke `-map 0:a?`.
- `probe.py --analyze` normalises 10-/12-bit levels to an 8-bit scale before the Log heuristic.
- `look.py` tone-maps HDR frames for display so the agent judges representative colours.
- `verify.py` runs `color --to-sdr` on the original file and adds an "hdr preserved" check on the accurate cut.

## 0.4.0

- `verify.py` (new): real-footage verification kit — runs the toolchain over the user's own files and reports PASS/FAIL per step, Markdown and JSON.
- `multicam.py` (new): align N cameras/recorders by audio (drift correction optional), switch between them from a time list or automatically, pick the audio source.
- `probe.py`: Dolby Vision detection (`dolby_vision`, `hdr_format`), `--analyze` samples picture levels and flags Log-looking footage.
- `color.py`: `--strip-dovi` removes the Dolby Vision RPU losslessly; HLG and DV 8.4 sources verified through `--to-sdr`.
- `caption.py`: karaoke word timing now follows speech energy in the audio (`--karaoke-timing energy|even`).
- `--progress` (percent / ETA) and `--fast` (preview preset) on every script.
- Tests: 38 end-to-end cases.

## 0.3.0

- `look.py` (new): contact sheet with timecodes, single-frame extraction, side-by-side before/after PNGs — the agent can inspect its own output.
- `silence.py` (new): silence detection and frame-accurate removal with margins, `--list` and `--edl` cut-list export compatible with `cut.py --segments`.
- `join.py` (new): xfade/acrossfade transitions between clips with automatic normalisation of size, fps, pixel format and audio layout (silent track synthesised when missing).
- `--dry-run` and `--json` on every script: print the ffmpeg commands without running, or emit a structured result (output, probe, commands).
- SKILL.md workflow now includes plan (`--dry-run`) and visual verification (`look.py`) steps.

## 0.2.0

- `color.py` (new): HDR10/HLG → SDR BT.709 tone mapping (zscale + tonemap), 3D `.cube` LUTs with strength blending, metadata-only colour retagging.
- `audio.py` (new): voice clean-up chain, FFT denoise, music bed with sidechain ducking, fades, 5.1 → stereo downmix, mono/stereo layout, track replacement.
- `sync.py`: coarse-to-fine search (20 ms FFT → 1 ms direct) and `--fix-drift` clock-drift measurement and correction by resampling; roughly 5x faster on the default window.
- `caption.py`: `--animate fade|pop|slide` and `--karaoke` word-by-word highlight, generated as a styled ASS sized to the video; SRT input can be animated too.
- `fit.py`: `--smooth blend|interpolate` for slow motion.
- VFR sources are conformed to constant frame rate automatically by every re-encoding script; `cut.py` switches to accurate mode on VFR.
- `probe.py`: `hdr`, `hdr_format`, `bit_depth` fields.
- `export.py`: warns when an HDR source is exported without tone mapping.
- Tests now cover VFR, rotated, 5.1, 10-bit HDR10 HEVC and drifting sources.

## 0.1.0

- Initial release: probe, cut, caption, fit, sync, loudness, overlay, export; npx installer; demo and tests.
