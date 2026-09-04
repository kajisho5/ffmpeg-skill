#!/usr/bin/env python3
"""Accuracy benchmark for sync.py against known ground truth.

Takes a real dialogue/music source (Tears of Steel by default), cuts random
60 s reference windows, and builds a "second recording" of each with a known
delay, gain change, added noise, a mild EQ tilt and optional clock drift.
Then asks sync.py for the offset (and drift) and records the error.

Usage:
  python3 tests/bench_sync.py --cases 100
  python3 tests/bench_sync.py --cases 30 --drift            # add ±300 ppm drift, measure with --fix-drift
  python3 tests/bench_sync.py --source my_interview.mp4 --cases 50 --json results.json
"""
import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "tests" / "corpus" / "tears_of_steel_720p.mov"


def sh(*cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_SRC))
    ap.add_argument("--cases", type=int, default=50)
    ap.add_argument("--window", type=float, default=120.0, help="reference window length in seconds (keep >= 4x --max-offset, the documented rule; 60 is the stress setting)")
    ap.add_argument("--max-offset", type=float, default=30.0)
    ap.add_argument("--drift", action="store_true", help="also apply ±300 ppm drift and measure with --fix-drift (uses 240 s windows)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", help="write per-case results here")
    args = ap.parse_args()
    if not Path(args.source).exists():
        print(f"source not found: {args.source} (run tests/corpus.py --fetch --only blender_tos_720)")
        return 1
    dur = float(json.loads(sh("ffprobe", "-v", "error", "-print_format", "json", "-show_format", args.source).stdout)["format"]["duration"])
    rng = random.Random(args.seed)
    window = 240.0 if args.drift else args.window
    results = []
    with tempfile.TemporaryDirectory(prefix="ffskill_bench_") as tmp:
        for i in range(args.cases):
            start = rng.uniform(10, max(11, dur - window - args.max_offset - 10))
            delay = rng.uniform(-args.max_offset, args.max_offset)
            gain_db = rng.uniform(-12, 6)
            noise = rng.choice([0.0, 0.002, 0.01, 0.03])
            tilt = rng.choice([0, 1, 2])
            ppm = rng.uniform(-300, 300) if args.drift else 0.0
            ref = Path(tmp) / f"ref{i}.wav"
            sec = Path(tmp) / f"sec{i}.wav"
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", args.source, "-t", f"{window:.3f}", "-vn", "-ac", "1", "-ar", "48000", ref)
            # second recording: starts `delay` later than the reference (positive = later start)
            sec_start = start + delay
            filters = [f"volume={gain_db:.2f}dB"]
            if tilt == 1:
                filters.append("highpass=f=300")
            elif tilt == 2:
                filters.append("lowpass=f=3000")
            if ppm:
                filters += [f"asetrate=48000*{1 + ppm / 1e6:.9f}", "aresample=48000"]
            af = ",".join(filters)
            if noise:
                sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{sec_start:.3f}", "-i", args.source, "-f", "lavfi", "-i", f"anoisesrc=a={noise}:c=pink:r=48000",
                   "-t", f"{window:.3f}", "-filter_complex", f"[0:a]{af}[a];[a][1:a]amix=inputs=2:duration=first:normalize=0[out]", "-map", "[out]", "-ac", "1", "-ar", "48000", sec)
            else:
                sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{sec_start:.3f}", "-i", args.source, "-t", f"{window:.3f}", "-vn", "-af", af, "-ac", "1", "-ar", "48000", sec)
            cmd = [sys.executable, ROOT / "scripts" / "sync.py", ref, sec, "--json", "--max-offset", str(args.max_offset + 5)]
            if args.drift:
                cmd.append("--fix-drift")
            proc = sh(*cmd)
            try:
                data = json.loads(proc.stdout)
                measured = data["offset_seconds"]
                conf = data["confidence"]
                drift_ppm = data.get("drift", {}).get("drift_ppm")
            except (ValueError, KeyError):
                measured, conf, drift_ppm = None, 0.0, None
            # the second file was cut `delay` seconds later in the source, i.e. the recorder started `delay`
            # seconds after the camera: sync.py reports that as offset = +delay ("second starts later")
            expected = delay
            err_ms = None if measured is None else (measured - expected) * 1000
            # the second file plays at (1+ppm) speed of the source -> sync reports the second file as running slow/long by -ppm
            exp_drift = -ppm if ppm else 0.0
            drift_err = None if drift_ppm is None else drift_ppm - exp_drift
            results.append({"case": i, "delay": round(delay, 3), "gain_db": round(gain_db, 1), "noise": noise, "tilt": tilt, "ppm": round(ppm, 1),
                            "measured": measured, "expected": round(expected, 3), "err_ms": None if err_ms is None else round(err_ms, 1),
                            "confidence": conf, "drift_ppm": drift_ppm, "drift_err_ppm": None if drift_err is None else round(drift_err, 1)})
            flag = "" if err_ms is not None and abs(err_ms) <= 10 else "  <-- "
            print(f"{i:3d} delay {delay:+7.3f}s gain {gain_db:+5.1f}dB noise {noise:<5} tilt {tilt} ppm {ppm:+6.0f} | got {measured!s:>8} err {err_ms!s:>8} ms conf {conf:.2f}"
                  + (f" drift {drift_ppm:+.0f} (err {drift_err:+.0f})" if drift_ppm is not None else "") + flag)
    errs = [abs(r["err_ms"]) for r in results if r["err_ms"] is not None]
    fails = [r for r in results if r["err_ms"] is None or abs(r["err_ms"]) > 10]
    print("---")
    print(f"cases {len(results)}, within 10 ms: {len(results) - len(fails)} ({100 * (len(results) - len(fails)) / len(results):.0f}%), "
          f"median |err| {statistics.median(errs):.1f} ms, p95 {sorted(errs)[int(len(errs) * 0.95) - 1] if len(errs) > 1 else errs[0]:.1f} ms, max {max(errs):.1f} ms")
    if args.drift:
        derr = [abs(r["drift_err_ppm"]) for r in results if r["drift_err_ppm"] is not None]
        if derr:
            print(f"drift: median |err| {statistics.median(derr):.1f} ppm, p95 {sorted(derr)[int(len(derr) * 0.95) - 1] if len(derr) > 1 else derr[0]:.1f} ppm, within 20 ppm: {sum(1 for d in derr if d <= 20)}/{len(derr)}")
    if fails:
        low_conf = sum(1 for r in fails if r["confidence"] < 0.3)
        print(f"failures: {len(fails)}, of which flagged by confidence < 0.3: {low_conf}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
