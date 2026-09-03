#!/usr/bin/env python3
"""Detect the time offset between two recordings by audio cross-correlation
and (optionally) write a synced output.

Pure standard library: both tracks are decoded by ffmpeg to mono 8 kHz PCM,
reduced to a coarse loudness envelope, and cross-correlated with an FFT
implemented in Python. Precision is roughly +/- one envelope step (default
5 ms), which is plenty for lining up a lav mic or a second camera.

Offset semantics: a positive offset means the SECOND input starts LATER
than the reference, i.e. `second` must be shifted earlier by that amount.

Examples:
  python3 sync.py camera.mp4 lavmic.wav                       # print offset only
  python3 sync.py camera.mp4 lavmic.wav --replace-audio -o synced.mp4
  python3 sync.py camA.mp4 camB.mp4 --trim-second -o camB_synced.mp4
  python3 sync.py cam.mp4 mic.wav --max-offset 60 --json
"""
import argparse
import cmath
import json
import math
import os
import struct
import subprocess
import sys
from typing import List

from _common import aac_args, audio_codec_for, default_output, die, ffmpeg_base, info, probe, require_tool, run, x264_args

SR = 8000  # decode sample rate


def decode_mono(path: str, seconds: float) -> List[float]:
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-t", f"{seconds:.3f}",
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        die(f"could not decode audio from {path}:\n{proc.stderr.decode(errors='replace').strip()}")
    n = len(proc.stdout) // 2
    return [v / 32768.0 for v in struct.unpack(f"<{n}h", proc.stdout[: n * 2])]


def envelope(samples: List[float], step: int) -> List[float]:
    """RMS energy per block, mean-removed so silence does not correlate."""
    env = []
    for i in range(0, len(samples) - step + 1, step):
        block = samples[i : i + step]
        env.append(math.sqrt(sum(x * x for x in block) / step))
    if not env:
        return env
    mean = sum(env) / len(env)
    return [e - mean for e in env]


def fft(a: List[complex]) -> List[complex]:
    """Iterative radix-2 Cooley-Tukey FFT. len(a) must be a power of two."""
    n = len(a)
    a = list(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        ang = -2 * math.pi / length
        wlen = complex(math.cos(ang), math.sin(ang))
        half = length // 2
        for i in range(0, n, length):
            w = 1 + 0j
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * w
                a[i + k] = u + v
                a[i + k + half] = u - v
                w *= wlen
        length <<= 1
    return a


def ifft(a: List[complex]) -> List[complex]:
    n = len(a)
    conj = [x.conjugate() for x in a]
    out = fft(conj)
    return [x.conjugate() / n for x in out]


def cross_correlate(ref: List[float], other: List[float], max_lag: int):
    n = 1
    while n < len(ref) + len(other):
        n <<= 1
    fa = fft([complex(x) for x in ref] + [0j] * (n - len(ref)))
    fb = fft([complex(x) for x in other] + [0j] * (n - len(other)))
    prod = [x * y.conjugate() for x, y in zip(fa, fb)]
    corr = ifft(prod)
    # corr[k] = sum ref[i+k]*other[i]  -> lag k means 'other' is delayed by k relative to ref? see below
    best_lag, best_val = 0, -float("inf")
    max_lag = min(max_lag, n // 2 - 1)
    for lag in range(-max_lag, max_lag + 1):
        val = corr[lag % n].real
        if val > best_val:
            best_val, best_lag = val, lag
    energy = math.sqrt(sum(x * x for x in ref) * sum(x * x for x in other)) or 1.0
    return best_lag, best_val / energy


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", help="reference recording (usually the camera video)")
    ap.add_argument("second", help="recording to align (external audio or second camera)")
    ap.add_argument("-o", "--output", help="output file when writing a synced result")
    ap.add_argument("--max-offset", type=float, default=30.0, help="largest offset to search in seconds (default 30)")
    ap.add_argument("--analyze-seconds", type=float, default=120.0, help="how much audio to analyse from each file (default 120)")
    ap.add_argument("--step-ms", type=float, default=5.0, help="envelope resolution in ms (default 5)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replace-audio", action="store_true", help="write reference video with the second file's audio, aligned")
    mode.add_argument("--trim-second", action="store_true", help="write the second file shifted so it lines up with the reference")
    ap.add_argument("--crf", type=int, default=18)
    args = ap.parse_args()

    for p in (args.reference, args.second):
        if not probe(p).get("audio"):
            die(f"{p} has no audio stream to correlate")

    step = max(1, int(SR * args.step_ms / 1000))
    ref = envelope(decode_mono(args.reference, args.analyze_seconds), step)
    oth = envelope(decode_mono(args.second, args.analyze_seconds), step)
    if len(ref) < 10 or len(oth) < 10:
        die("not enough audio to analyse")

    max_lag = int(args.max_offset * SR / step)
    lag, score = cross_correlate(ref, oth, max_lag)
    # With prod = FFT(ref) * conj(FFT(other)), the peak sits at lag k where ref[i] ~ other[i - k]:
    # the same event happens k steps later in the reference than in the second file, which
    # means the second recording STARTED k steps later. Positive offset = second starts later.
    offset = lag * step / SR

    result = {
        "reference": args.reference,
        "second": args.second,
        "offset_seconds": round(offset, 4),
        "confidence": round(max(0.0, min(1.0, score)), 3),
        "meaning": ("second starts %.3fs %s than reference" % (abs(offset), "later" if offset > 0 else "earlier")),
    }
    if result["confidence"] < 0.1:
        info("warning: low correlation confidence; check that both files contain the same audio event")

    if args.replace_audio or args.trim_second:
        output = args.output or default_output(args.reference if args.replace_audio else args.second, "synced", "mp4")
        # second started later (offset > 0)  -> delay it by `offset` (pad the head)
        # second started earlier (offset < 0) -> drop its first `-offset` seconds
        delay_ms = int(round(offset * 1000))
        head_trim = -offset if offset < 0 else 0.0
        second_meta = probe(args.second)
        has_video = bool(second_meta.get("video"))

        if args.replace_audio:
            cmd = ffmpeg_base() + ["-i", args.reference]
            if head_trim > 0:
                cmd += ["-ss", f"{head_trim:.4f}"]
            cmd += ["-i", args.second, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
            if delay_ms > 0:
                cmd += ["-af", f"adelay={delay_ms}:all=1"]
            cmd += aac_args() + ["-shortest", output]
            proc = run(cmd, check=False)
            if proc.returncode != 0:
                cmd = [c for c in cmd if c != "copy"]
                idx = cmd.index("-c:v"); del cmd[idx]
                cmd = cmd[:-1] + x264_args(args.crf) + [output]
                run(cmd)
        else:
            if head_trim > 0:
                cmd = ffmpeg_base() + ["-ss", f"{head_trim:.4f}", "-i", args.second, "-c", "copy", "-avoid_negative_ts", "make_zero", output]
                proc = run(cmd, check=False)
                if proc.returncode != 0:
                    cmd = ffmpeg_base() + ["-ss", f"{head_trim:.4f}", "-i", args.second] + (x264_args(args.crf) if has_video else []) + audio_codec_for(output) + [output]
                    run(cmd)
            else:
                af = f"adelay={delay_ms}:all=1"
                cmd = ffmpeg_base() + ["-i", args.second]
                if has_video:
                    cmd += ["-vf", f"tpad=start_duration={offset:.4f}"] + x264_args(args.crf)
                cmd += ["-af", af] + audio_codec_for(output) + [output]
                run(cmd)
        result["output"] = output
        info(f"wrote {output}")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"offset: {result['offset_seconds']:+.3f}s ({result['meaning']}), confidence {result['confidence']:.2f}")
        if "output" in result:
            print(result["output"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
