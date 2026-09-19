# Result Honesty — the fields that carry claims

Every script ends in exactly one of `emit()` (success) or `die()` (failure), both
in `scripts/_common/emit.py`. Under `--json` both print one document; `die()`
prints the same shape with `status: "failed"`. Review the *document*, because it is
what a caller reads.

## The success document

Produced by `emit()`. Keys a review must trace, with where the value comes from:

| key | source | what a wrong value looks like |
| --- | --- | --- |
| `status` | `emit()` | must never be `completed` on a run `die()` handled |
| `verified` | conjunction of `verify_output()` and each tool's extra steps | `true` for an artifact never probed |
| `verification` | the step list (`loudness` re-measure, `export` platform measure, `render` check) | a step named that did not run |
| `reencodes_*` | whether the copy path fell back to a re-encode | copy fallback silently unreported |
| `dropped_non_av_streams` | `run_keeping_subtitles()` result, or timeline-move tools | `false` when the track was dropped |
| `mode`, `keyframe_snapped`, `duration_delta_seconds` | `cut.py` | a snapped copy reported as lossless |
| `result_v2` | `_result_v2()` when `FFMPEG_SKILL_RESULT_V2=1` | a field that disagrees with its 1.x twin |
| `commands` | the argv actually run | a command that was not the one executed |

`verified` is defined as **what the tool measured itself, not a promise about the
user's intent**. A spec miss the tool cannot fix (e.g. `export`'s loudness against
a platform target) is `completed` + `verified: false` with the next step in
`notes` — not a failure. A change that turns that into `failed`, or that flips
`verified` to `true` without a measurement, is the finding.

## The failure document

Produced by `die()`. Keys: `status: "failed"`, `exit_code`, `error`
(`kind`, `message`, `code`, `retryable`, optional `hint`), `commands`, plus any
`extra` the tool attached.

Error kinds (`scripts/_contract.py`, `error_kinds`):

| kind | meaning | exit |
| --- | --- | --- |
| `input` | missing/unsuitable input or bad arguments | 1 |
| `ffmpeg` | ffmpeg/ffprobe returned an error; message carries last stderr lines | 1 |
| `output` | ffmpeg exited 0 but the artifact is missing/empty/unreadable | 1 |
| `missing_tool` | ffmpeg or ffprobe not on PATH | 127 |
| `timeout` | one run exceeded `--timeout` and was killed; partial output removed | 124 |
| `verification` | the tool ran but its result failed the requested check | 1 |
| `interrupted` | SIGINT/SIGTERM; partial output removed | 130 / 143 |

`retryable` is always `false` (`ERROR_RETRYABLE`). An ffmpeg failure exits 1
whatever ffmpeg's own code was; the raw code is preserved as `ffmpeg_returncode`.

Tools whose *result* failed attach detail while the top-level status still says
`failed`: `check.py` platform rows, `render.py`'s check stage, `batch.py` per-item
results, `verify.py` steps. Before 1.4.3 those four printed `status: "completed"`
next to a non-zero exit — a caller keying on status alone read a failed delivery
as success. Do not reintroduce that shape.

## Dry run

- Measurement passes run under `--dry-run`; only writes are skipped. `analysis_only`
  tools: `probe`, `check`, `sync`, `multicam`, `scenes`, `cropdetect`, `report`,
  `silence`, `loudness`, `stabilize` (`_contract.DRY_RUN_ANALYSIS`).
- `info()` rewrites `wrote X` to `[dry-run] would write X` — a tool must not claim
  a write under dry-run.
- A measured input that is an intermediate an earlier dry-run stage would have
  written is skipped with a note (`_common.dry_run_input_pending()`), not failed.
- `verify` accepts `--dry-run` and ignores it (`_contract.DRY_RUN_NOTES["verify"]`).

## Existing outputs

- An existing output is **warned about, not refused, until 2.0**; `--overwrite` is
  the explicit consent and `FFMPEG_SKILL_NO_OVERWRITE=1` opts into refusal today
  (`_common._check_existing_output()`).
- It is written through a hidden sibling temp (`.<stem>.ffskill-<pid><ext>`) and
  replaced only on success (`_common._stage_existing_output()`), so a failed run
  never costs the caller the file that was there.

## Tests that pin the above

Read these before reporting a violation; if the test exists and passes, the
behaviour is intended.

```
tests/test_contract.py::test_verified_reports_what_the_tool_measured
tests/test_contract.py::test_success_requires_a_verified_output
tests/test_contract.py::test_dry_run_never_runs_ffmpeg_and_writes_nothing
tests/test_contract.py::test_dry_run_plans_rest_on_real_measurements
tests/test_contract.py::test_failed_run_never_deletes_an_output_that_predates_it
tests/test_contract.py::test_batch_reports_failed_items_as_a_failed_run
tests/test_editing.py::test_cut_copy_keyframe_snap_reports_a_real_nonzero_delta
tests/test_contract.py::test_timeout_kills_a_hung_ffmpeg_and_reports_kind_timeout
tests/test_contract.py::test_sibling_scripts_run_under_an_outer_ceiling
```

The `cut` case is the canonical example: the test measured a real 1.24 s
divergence from a keyframe snap and asserts it is reported, rather than assuming
the copy was lossless.
