#!/usr/bin/env python3
"""Run the whole suite in parallel, in separate processes: test_all.py's group modules and test_contract.

    python3 tests/run_parallel.py            # processes at once = CPU count
    python3 tests/run_parallel.py --jobs 2
    python3 tests/run_parallel.py --part 2/3  # CI: the second of three machines' share

The tests of `python3 tests/test_all.py` and `python3 -m unittest tests.test_contract`, in the same
modules; only the wall time changes. test_contract used to run only under --part, so a local run
without it reported "all OK" for a suite that had not run its 460 contract tests (#635).
Each module runs in its own interpreter with its own OUT directory (tests/out/<module>), because
the modules share output names (cap_mux.mp4 is written by three tests) and must not overwrite
each other's files. A module's output is printed whole when it finishes, never interleaved, and
the run fails if any module fails. The slowest modules start first so the longest one is not
left running alone at the end. The four largest modules run as two shards each (every other test
of the module, in its own process and OUT directory), so no one module sets the wall time.

`--part I/N` runs one machine's share when the suite is spread over N CI jobs: the shards are
dealt out by their rough cost, longest first, each to the part with the least so far, so the N
parts take about the same time; test_contract is one of the items, so a part needs nothing else.
Every item lands in exactly one part.
"""
import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_all  # noqa: E402

# Seconds each module took on a 4-core GitHub Linux runner (3.0.0, summed over its shards): the order
# to start them in, and the weights --part balances.
ROUGH_SECONDS = {"test_picture": 1480, "test_orchestration": 960, "test_delivery": 660, "test_editing": 600,
                 "test_analysis": 570, "test_cut_copy": 330, "test_audio": 300, "test_contract": 230,
                 "test_asr": 70, "test_accel": 10, "test_guards": 190}
SHARDS = {"test_picture": 4, "test_orchestration": 3, "test_delivery": 2, "test_analysis": 2, "test_editing": 2,
          "test_cut_copy": 2}


def split_parts(work: "list", n: int) -> "list":
    """Deal the work items into n lists of about equal rough cost (longest first, each to the
    lightest part so far)."""
    parts: "list" = [[] for _ in range(n)]
    load = [0.0] * n
    for job in sorted(work, key=lambda j: -ROUGH_SECONDS.get(j[0], 0) / j[2]):
        i = load.index(min(load))
        parts[i].append(job)
        load[i] += ROUGH_SECONDS.get(job[0], 0) / job[2]
    return parts


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


SKIP_MARK = "SKIPPED-TEST: "
CLASS_SKIP = ", every test in it: "


def skip_summary(skipped: "dict[str, int]") -> str:
    """What the run did not test, most frequent reason first: the line a reader of a green job
    looks at to see whether it tested what its name says."""
    if not skipped:
        return "\nskipped: none"
    rows = sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))
    # a skipped setUpClass is a whole class, whose tests unittest never lists: counted apart
    classes = sum(n for reason, n in skipped.items() if CLASS_SKIP in reason)
    tests = sum(skipped.values()) - classes
    whole = f", and {classes} whole class(es) whose tests did not run" if classes else ""
    return "\n".join([f"\nskipped: {tests} test(s){whole}, {len(rows)} reason(s)"]
                     + [f"  {count:3d}  {reason}" for reason, count in rows])


def run_shard(name: str, k: int, n: int) -> int:
    """Child mode: run every n-th test of module `name`, starting at k, in definition order."""
    tests = list(_flatten(unittest.defaultTestLoader.loadTestsFromName(name)))
    suite = unittest.TestSuite(t for i, t in enumerate(tests) if i % n == k)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    # one line per skipped test, for the parent's summary: a job that skips is still green, so a
    # runner whose ffmpeg lost libass or whose fonts are gone ran less than its tick says (#558)
    if result.skipped:
        print()  # a test's own output may have left the line open; the marker must start one
    for test, reason in result.skipped:
        # a skipped setUpClass is one entry for a whole class that did not run: say so (review of #635)
        whole = f"{test.description}{CLASS_SKIP}" if isinstance(test, unittest.suite._ErrorHolder) else ""
        print(SKIP_MARK + whole + " ".join(str(reason).split()))
    return 0 if result.wasSuccessful() else 1


def run_job(job: "tuple", out_root: Path) -> "tuple":
    name, k, n = job
    label = name if n == 1 else f"{name}[{k + 1}/{n}]"
    out = out_root / (name.replace("test_", "") + ("" if n == 1 else f"_{k + 1}"))
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OUT=str(out))
    # always through run_shard(), a whole module as shard 0 of 1: it reports what it skipped
    cmd = [sys.executable, str(Path(__file__).resolve()), "--shard", name, str(k), str(n)]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(HERE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    return label, proc.returncode, time.time() - t0, proc.stdout


def all_modules() -> "list":
    """Every test module a run covers, with or without --part."""
    return [m.__name__ for m in test_all.MODULES] + ["test_contract"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=0, help="processes run at once (default: CPU count)")
    ap.add_argument("--part", metavar="I/N", help="run only part I of N (1-based); for CI jobs")
    ap.add_argument("--shard", nargs=3, metavar=("MODULE", "K", "N"), help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.shard:
        return run_shard(args.shard[0], int(args.shard[1]), int(args.shard[2]))
    names = all_modules()
    work = sorted(((n, k, SHARDS.get(n, 1)) for n in names for k in range(SHARDS.get(n, 1))),
                  key=lambda j: -ROUGH_SECONDS.get(j[0], 0) / j[2])
    if args.part:
        m = re.fullmatch(r"(\d+)/(\d+)", args.part)
        if not m or not 1 <= int(m.group(1)) <= int(m.group(2)) <= len(work):
            ap.error(f"--part must be I/N with 1 <= I <= N <= {len(work)}, got {args.part!r}")
        work = split_parts(work, int(m.group(2)))[int(m.group(1)) - 1]
        names = sorted({j[0] for j in work})
    jobs = args.jobs or min(os.cpu_count() or 1, len(work))
    # absolute: the children run with cwd=tests/, so a relative OUT would mean a different place there
    out_root = Path(os.environ.get("OUT", HERE / "out")).resolve()
    t0 = time.time()
    failed, ran = [], 0
    skipped: "dict[str, int]" = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        # printed as each module finishes, not in the order they were started: a job that is
        # cancelled or runs out of time still shows every module that got to its end (#514)
        for done in as_completed([pool.submit(run_job, j, out_root) for j in work]):
            name, code, secs, output = done.result()
            shown = [line for line in output.strip().splitlines() if not line.startswith(SKIP_MARK)]
            last = shown[-1] if shown else ""
            ran += sum(int(m) for m in re.findall(r"^Ran (\d+) tests?", output, flags=re.M))
            for reason in re.findall("^" + re.escape(SKIP_MARK) + "(.*)$", output, flags=re.M):
                skipped[reason] = skipped.get(reason, 0) + 1
            print(f"\n===== {name}: {'OK' if code == 0 else 'FAILED'} in {secs:.0f}s ({last}) =====")
            if code != 0:
                failed.append(name)
                print(output)
            else:
                print("\n".join(shown[-3:]))
            sys.stdout.flush()
    print(skip_summary(skipped))
    print(f"\n{ran} tests, {len(names)} modules in {len(work)} processes, {jobs} at a time, {time.time() - t0:.0f}s wall; "
          + ("FAILED: " + ", ".join(failed) if failed else "all OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
