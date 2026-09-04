#!/usr/bin/env python3
"""Accuracy benchmark for silence.py: insert known silences into real speech
and score what it keeps and cuts.

For each case: take a 20 s speech window from the source, splice in N gaps of
known length (0.4–3 s) at known positions, run silence.py --list and compare
the kept ranges with the ground truth.

Metrics: clipped speech (ms of real speech removed, per gap edge), leftover
silence (ms of inserted silence kept beyond the margin), missed gaps.

Usage:
  python3 tests/bench_silence.py --cases 30
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
    ap.add_argument("--cases", type=int, default=20)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=-35.0)
    ap.add_argument("--min-silence", type=float, default=0.6)
    ap.add_argument("--margin", type=float, default=0.15)
    ap.add_argument("--json")
    args = ap.parse_args()
    if not Path(args.source).exists():
        print(f"source not found: {args.source}")
        return 1
    dur = float(json.loads(sh("ffprobe", "-v", "error", "-print_format", "json", "-show_format", args.source).stdout)["format"]["duration"])
    rng = random.Random(args.seed)
    rows = []
    with tempfile.TemporaryDirectory(prefix="ffskill_bsil_") as tmp:
        for i in range(args.cases):
            start = rng.uniform(60, dur - 90)
            # 3 speech chunks of 4-7 s with gaps of known length between them (true silence = digital zero + tiny noise)
            chunks = [rng.uniform(4, 7) for _ in range(3)]
            gaps = [rng.uniform(0.4, 3.0) for _ in range(2)]
            parts = []
            fc = []
            t = start
            inputs = []
            n = 0
            timeline = []  # (kind, s, e) in output time
            cur = 0.0
            for k, c in enumerate(chunks):
                inputs += ["-ss", f"{t:.3f}", "-t", f"{c:.3f}", "-i", args.source]
                fc.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=mono,volume=1.0[s{n}]")
                parts.append(f"[s{n}]")
                timeline.append(("speech", cur, cur + c))
                cur += c
                t += c + 3
                n += 1
                if k < len(gaps):
                    g = gaps[k]
                    fc.append(f"anoisesrc=a=0.0005:c=white:r=48000:d={g:.3f},aformat=channel_layouts=mono[g{k}]")
                    parts.append(f"[g{k}]")
                    timeline.append(("gap", cur, cur + g))
                    cur += g
            fc.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1[out]")
            wav = Path(tmp) / f"case{i}.wav"
            sh("ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]", wav)
            proc = sh(sys.executable, ROOT / "scripts" / "silence.py", wav, "--list", "--json", "--threshold", args.threshold, "--min-silence", args.min_silence, "--margin", args.margin)
            try:
                data = json.loads(proc.stdout)
            except ValueError:
                print(f"{i:3d} silence.py failed: {proc.stderr.strip()[-120:]}")
                continue
            keep = data["keep"]
            # score each inserted gap
            clipped_ms = 0.0
            leftover_ms = 0.0
            missed = 0
            for kind, s, e in timeline:
                if kind != "gap":
                    continue
                if e - s < args.min_silence:
                    continue  # too short to be removed by design
                # portion of the gap that is kept (beyond margins) = leftover
                kept_in_gap = sum(max(0.0, min(ke, e - args.margin) - max(ks, s + args.margin)) for ks, ke in keep)
                if kept_in_gap >= (e - s) - 2 * args.margin - 0.05:
                    missed += 1
                leftover_ms += kept_in_gap * 1000
            for kind, s, e in timeline:
                if kind != "speech":
                    continue
                kept_speech = sum(max(0.0, min(ke, e) - max(ks, s)) for ks, ke in keep)
                clipped_ms += max(0.0, (e - s) - kept_speech) * 1000
            rows.append({"case": i, "gaps": [round(g, 2) for g in gaps], "clipped_speech_ms": round(clipped_ms), "leftover_silence_ms": round(leftover_ms), "missed_gaps": missed,
                         "removed": data["removed_seconds"], "expected_removed": round(sum(max(0.0, g - 2 * args.margin) for g in gaps if g >= args.min_silence), 2)})
            print(f"{i:3d} gaps {rows[-1]['gaps']} clipped {clipped_ms:6.0f} ms leftover {leftover_ms:6.0f} ms missed {missed} removed {data['removed_seconds']:.2f}s (expected {rows[-1]['expected_removed']:.2f}s)")
    if not rows:
        return 1
    print("---")
    clip = [r["clipped_speech_ms"] for r in rows]
    left = [r["leftover_silence_ms"] for r in rows]
    print(f"cases {len(rows)}: clipped speech median {statistics.median(clip):.0f} ms, max {max(clip):.0f} ms; "
          f"leftover silence median {statistics.median(left):.0f} ms, max {max(left):.0f} ms; missed gaps {sum(r['missed_gaps'] for r in rows)}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
