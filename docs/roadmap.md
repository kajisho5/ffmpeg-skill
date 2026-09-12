# Roadmap: 1.7.1 → 1.10.0 → 2.0

The 1.x contract is frozen (docs/contract.md, "Stability guarantee"). Every minor below adds
opt-in flags or parallel keys that pre-ship a 2.0 decision (issue #189, docs/design-decisions.md
"Decided for 2.0"), plus the follow-ups the evals keep surfacing. 2.0.0 then removes the old
spelling and flips the defaults; it adds no feature of its own. Each minor ships with an evals
iteration and an audit pass, as 1.5 → 1.7 did. `resolve_version.py` turns `feat` PRs into a
minor and `fix` PRs into a patch, so each block below is one or two `feat` PRs plus fixes.

## 1.8.0 — one-call delivery, quieter checks, encoder flags

- **`check.py` judgement rows without a named platform.** Today `--platform` defaults to
  `youtube`, so a run that only wanted the format rows gets loudness / true-peak FAILs and the
  agent spends a paragraph explaining why it left them alone (eval 7: e07, e12, j02, j04). When
  `--platform` is not given explicitly, judgement rows report `WARN` (not `FAIL`, not counted in
  `failed`) and a `notes` line says the target was assumed. Named platforms are unchanged.
- **`render.py` `export.normalize`.** The project's export stage forwards `--normalize` so a
  project renders a platform-compliant file in one export (1.7.1 gave the flag to `export.py`).
- **`--codec h264|hevc|av1|prores` and `--quality N`** (2.0 B, pre-shipped): added by
  `add_common()` to every re-encoding tool, resolved once in `video_args()` (CRF for x264/x265,
  `-crf`/`-b:v` for av1, profile for ProRes; HDR / 10-bit branch stays in the same place).
  `--crf` / `--preset` keep working as aliases with no deprecation yet. Contract snapshot and
  MCP snapshot regenerated; `docs/contract.md` gains one paragraph.
- **Eval iteration 8 at 1.8.0** (3 repeats, independent grader): confirms the 1.7.1 language
  fix (r04 / f01), measures whether `--normalize` removed the second export, and whether
  `--codec` gets picked for "make it HEVC" / "ProRes master". Seventh audit pass on the tree.

## 1.9.0 — one time grammar, one HDR meaning

- **`time_arg()` everywhere** (2.0 B): `broll.py`, `cut.py`, `freeze.py`, `render.py`,
  `sequence.py`, `verify.py` still call `parse_time()` or their own helpers; every time-taking
  flag goes through `time_arg()`, so seconds, `mm:ss(.fff)`, `hh:mm:ss(.fff)` and four-part
  SMPTE behave the same in all 42 tools. Documented once in `references/scripts.md`.
- **`@fps` suffix**: `00:01:02:15@29.97` names the rate explicitly; without it a four-part value
  uses the source fps and a missing fps stays `kind: input`. Accepted by `time_arg()` only.
- **`hdr_signal`** (2.0 A, parallel key): `probe` adds `hdr_signal: true` only for PQ / HLG
  transfer; `hdr` keeps today's meaning (BT.2020 primaries count) until 2.0 renames it. The
  HDR-aware tools (`color`, `export`, `check`, `proxy`) read `hdr_signal` so BT.2020 SDR stops
  going down the HDR path, with `hdr_format: "BT.2020 SDR"` as the explanation.
- **Eval iteration 9**; pins in `docs/design-decisions.md` for the grammar and the HDR split.

## 1.10.0 — 2.0 readiness

- **Deprecation notices**, per the three-step policy in `docs/contract.md`: `--help` text,
  CHANGELOG, and a `deprecated` list in `contract --json` for what 2.0 removes: the per-tool
  v1 success keys superseded by `result_v2`, `--crf` / `--preset` as aliases of `--quality`,
  `json` / `progress` in the MCP `inputSchema`, the current `hdr` meaning, the overwrite default.
- **`Context` threading** (2.0 B, internal): `STATE` becomes the default `Context` instance and
  `run()` / `emit()` / `die()` accept an optional `ctx=`; no tool changes behaviour. 2.0 makes
  the argument required, which is the signature change the major is for.
- **MCP lean schema, opt-in**: `FFMPEG_SKILL_MCP_LEAN=1` drops `json` / `progress` from
  `tools/list` (2.0 A3 pre-shipped; the default stays byte-identical to the CLI, as the
  contract promises).
- **`FFMPEG_SKILL_NO_OVERWRITE=1`** documented in SKILL.md as the recommended agent setting,
  with a test, so 2.0's default flip has been exercised.
- **Eval iteration 10** and an eighth audit pass; the real-device corpus (92 verification
  steps) re-run on the tree; `docs/contract.md` "What 2.0 changes" section written from the
  `deprecated` list.

## 2.0.0 (after 1.10.x settles)

Manual `package.json` bump in one PR (the release workflow never picks a major). It removes
the deprecated spellings, promotes `result_v2` to the top level, makes `ctx` required, renames
`hdr`, flips the overwrite default, and drops `json` / `progress` from MCP. Nothing else.

## Not planned

- A feature that needs 2.0: features land in 1.x behind flags (1.4.0, 1.6.0, 1.7.0 did).
- A new tool: the 42-tool table is the contract's surface; new behaviour goes on existing
  tools as options.
