#!/usr/bin/env python3
"""Accuracy benchmark for scenes.py cut detection (precision / recall / F1)
against synthetic sequences with known cut positions built from real footage.

Each case concatenates 6-10 random shots of 2-8 s taken from far-apart
positions in the source (so consecutive shots differ), records the exact cut
times, runs scenes.py and compares (a hit = detected cut within ±0.25 s).

Usage:
  python3 tests/bench_scenes.py --cases 10
  python3 tests/bench_scenes.py --cases 10 --threshold 6
"""
import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
# continuous single-take sources (no internal cuts) so every detected cut inside a shot is a true false positive
DEFAULT_SRCS = [CORPUS / "gopro_GX010743.MP4", CORPUS / "dji_DJI_0038.MOV", CORPUS / "iphone_IMG_3179.MOV",
                CORPUS / "iphone13pro_4K60p.mov", CORPUS / "rtings_305_24p.mp4", CORPUS / "android_screen_2.mp4"]


def sh(*cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", help="continuous-take source(s); default: corpus single-take files")
    ap.add_argument("--cases", type=int, default=8)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--threshold", type=float, default=10.0)
    ap.add_argument("--tolerance", type=float, default=0.25)
    ap.add_argument("--json")
    args = ap.parse_args()
    sources = [Path(p) for p in (args.source or [str(p) for p in DEFAULT_SRCS]) if Path(p).exists()]
    if not sources:
        print("no sources found (run tests/corpus.py --fetch)")
        return 1
    durs = {p: float(json.loads(sh("ffprobe", "-v", "error", "-print_format", "json", "-show_format", p).stdout)["format"]["duration"]) for p in sources}
    rng = random.Random(args.seed)
    tp = fp = fn = 0
    rows = []
    with tempfile.TemporaryDirectory(prefix="ffskill_bsc_") as tmp:
        for i in range(args.cases):
            n = rng.randint(6, 10)
            shots = []
            prev = None
            for _ in range(n):
                # alternate sources so consecutive shots always come from different footage
                cands = [p for p in sources if p != prev] or sources
                src = rng.choice(cands)
                l = rng.uniform(2, min(8, durs[src] - 1))
                st = rng.uniform(0.5, max(0.6, durs[src] - l - 0.5))
                shots.append((src, st, l))
                prev = src
            inputs, fc, labels = [], [], []
            cuts, t = [], 0.0
            for k, (src, s, l) in enumerate(shots):
                inputs += ["-ss", f"{s:.3f}", "-t", f"{l:.3f}", "-i", src]
                fc.append(f"[{k}:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1,format=yuv420p[v{k}]")
                labels.append(f"[v{k}]")
                t += l
                if k < n - 1:
                    cuts.append(round(t, 3))
            fc.append("".join(labels) + f"concat=n={n}:v=1:a=0[out]")
            clip = Path(tmp) / f"case{i}.mp4"
            sh("ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", clip)
            proc = sh(sys.executable, ROOT / "scripts" / "scenes.py", clip, "--json", "--threshold", args.threshold, "--min-scene", "0.5")
            try:
                data = json.loads(proc.stdout)
            except ValueError:
                print(f"{i} scenes.py failed: {proc.stderr[-200:]}")
                continue
            detected = [sc["start"] for sc in data["scenes"] if sc["start"] > 0.01]
            matched = set()
            hits = 0
            for c in cuts:
                for j, d in enumerate(detected):
                    if j not in matched and abs(d - c) <= args.tolerance:
                        matched.add(j)
                        hits += 1
                        break
            case_fp = len(detected) - hits
            case_fn = len(cuts) - hits
            tp += hits
            fp += case_fp
            fn += case_fn
            rows.append({"case": i, "cuts": cuts, "detected": detected, "tp": hits, "fp": case_fp, "fn": case_fn})
            print(f"{i:2d} shots {n:2d} cuts {len(cuts):2d} detected {len(detected):2d} hit {hits:2d} fp {case_fp} fn {case_fn}")
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print("---")
    print(f"threshold {args.threshold:g}: precision {prec:.2f} recall {rec:.2f} F1 {f1:.2f} (tp {tp} fp {fp} fn {fn})")
    if args.json:
        Path(args.json).write_text(json.dumps({"threshold": args.threshold, "precision": prec, "recall": rec, "f1": f1, "cases": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
