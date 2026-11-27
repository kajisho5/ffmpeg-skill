### Added

- **A with/without-skill benchmark in the repository, and its page (#677).** `python3 benchmarks/run.py
  MODEL --arm skill|raw --runs 3` gives 24 ordinary requests to a model through any OpenAI-compatible
  endpoint named in `BENCH_API_URL` / `BENCH_API_KEY` (never committed), with one `bash` tool and a
  limit of 20 calls, grades every output by measuring the file, and writes one results file under
  `benchmarks/results/`. `--dry-run` lists the tasks and the requests with no endpoint. The page,
  [docs/benchmark.md](docs/benchmark.md) and the Pages site, is generated from those files and shows
  the latest result per model and arm with date, release, correct count, calls per request and cost.
  It carries the figures published on 2026-11-21 (#633, #670, #675, #677, #684), each with its
  source; a figure the source did not state reads "not measured". The `benchmark` workflow runs it
  by hand after a release and needs two secrets the maintainer adds; CI does not call a model.
  `benchmarks/calls.py` counts where each task's calls go from the transcripts (#684).
