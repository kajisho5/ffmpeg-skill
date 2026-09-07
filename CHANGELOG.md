# Changelog

> `main` moves ahead of the last published npm/GitHub release; a dependent repo should pin a tagged version, not `main`. See README § Development, "Releasing".

## Unreleased

- **Test: the prose tool count in README/`docs/contract.md`/`package.json` is now checked against the real tool list.** 0.11.0 was cut to fix exactly this drift (README said 28 twice and 22 once; `package.json` said 21) by hand, with nothing to stop it recurring. `tests/test_contract.py`'s `test_docs_tool_count_matches_the_real_tool_list` scans all three for `"<N> tools"` wording and fails if any number doesn't match `scripts/`'s actual public-tool count, so the next tool added/removed without updating every mention fails CI instead of drifting silently. `contract_version`/`skill.version` were already split (0.9.0) and already documented as "additive keeps `contract_version`, breaking bumps it" — `docs/contract.md` now also repeats the tagged-version pin guidance next to that table, since `capability_map` makes this the most cross-repo-facing part of the contract. Closes [#50](https://github.com/kajisho5/ffmpeg-skill/issues/50).

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
