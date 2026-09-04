#!/usr/bin/env python3
"""Detect the time offset between two recordings by audio cross-correlation
and (optionally) write a synced output, with optional clock-drift correction.

Pure standard library: both tracks are decoded by ffmpeg to mono 8 kHz PCM,
reduced to a loudness envelope, cross-correlated with an FFT implemented in
Python (coarse, 20 ms), then refined by direct correlation at 1 ms.

Offset semantics: a positive offset means the SECOND input starts LATER
than the reference, i.e. `second` must be shifted earlier by that amount.

Examples:
  python3 sync.py camera.mp4 lavmic.wav                       # print offset only
  python3 sync.py camera.mp4 lavmic.wav --replace-audio -o synced.mp4
  python3 sync.py camA.mp4 camB.mp4 --trim-second -o camB_synced.mp4
  python3 sync.py cam.mp4 mic.wav --max-offset 60 --json
  python3 sync.py cam.mp4 recorder.wav --fix-drift --replace-audio   # long takes: fix clock drift too
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

from _common import video_args, add_common, apply_common, emit, aac_args, audio_codec_for, default_output, die, ffmpeg_base, info, probe, require_tool, run, x264_args

SR = 8000  # decode sample rate


def decode_mono(path: str, seconds: float, start: float = 0.0) -> List[float]:
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", path, "-t", f"{seconds:.3f}",
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
    """Normalised cross-correlation over the overlapping region only.

    The raw FFT correlation sum grows with the overlap length, so with a 60 s window a
    correct 28 s offset (32 s overlap) loses to a wrong 2 s offset (58 s overlap) on
    music-like material. Dividing each lag by the energy of the overlapping parts
    (prefix sums, O(1) per lag) makes lags comparable and turns the peak value into a
    real similarity score in 0..1 that doubles as the confidence.
    """
    n = 1
    while n < len(ref) + len(other):
        n <<= 1
    fa = fft([complex(x) for x in ref] + [0j] * (n - len(ref)))
    fb = fft([complex(x) for x in other] + [0j] * (n - len(other)))
    prod = [x * y.conjugate() for x, y in zip(fa, fb)]
    corr = ifft(prod)
    # prefix sums of squares for overlap energy
    def prefix(v: List[float]) -> List[float]:
        out = [0.0]
        acc = 0.0
        for x in v:
            acc += x * x
            out.append(acc)
        return out
    pr, po = prefix(ref), prefix(other)
    lr, lo = len(ref), len(other)
    max_lag = min(max_lag, n // 2 - 1)
    best_lag, best_val, second = 0, -float("inf"), -float("inf")
    # ignore lags with less than 35 % overlap: with the documented rule (analysis window >= 4x the
    # largest expected offset) true offsets always keep >= 75 % overlap, while short-overlap lags are
    # where coincidental matches on quasi-periodic material (music, tone beds) live
    min_overlap = max(10, int(0.35 * min(lr, lo)))
    scores = []
    for lag in range(-max_lag, max_lag + 1):
        # corr[lag] = sum_i ref[i] * other[i - lag]  -> ref index range and other index range overlap:
        r0, r1 = max(0, lag), min(lr, lo + lag)
        if r1 - r0 < min_overlap:
            continue
        e_ref = pr[r1] - pr[r0]
        e_oth = po[r1 - lag] - po[r0 - lag]
        denom = math.sqrt(e_ref * e_oth)
        if denom <= 0:
            continue
        val = corr[lag % n].real / denom
        # mild preference for longer overlaps: a perfect match over 55 % of the window must not tie
        # with a perfect match over 100 % (quasi-periodic material). Exponent 0.5: with the window rule (>= 4x offset) a true match keeps >= 75 % overlap (x0.87) while a coincidental 55 % match drops to x0.74; keeps large true
        # offsets (28 s in 60 s = 53 % overlap -> x0.94) competitive while still breaking exact ties.
        val *= ((r1 - r0) / min(lr, lo)) ** 0.5
        scores.append((val, lag))
        if val > best_val:
            second = best_val
            best_val, best_lag = val, lag
        elif val > second and abs(lag - best_lag) > 5:
            second = val
    # confidence: peak similarity, penalised when a distant runner-up is nearly as good
    conf = max(0.0, min(1.0, best_val))
    if second > -float("inf") and best_val > 0:
        margin = (best_val - second) / best_val
        conf *= min(1.0, 0.5 + margin)
    return best_lag, conf


def refine(ref_s: List[float], oth_s: List[float], coarse_offset: float, fine_step: int, window_s: float) -> float:
    """Direct correlation at fine resolution around a coarse estimate (+/- window_s)."""
    ref_e = envelope(ref_s, fine_step)
    oth_e = envelope(oth_s, fine_step)
    centre = int(round(coarse_offset * SR / fine_step))
    span = int(window_s * SR / fine_step)
    best_lag, best_val = centre, -float("inf")
    n = min(len(ref_e), len(oth_e))
    for lag in range(centre - span, centre + span + 1):
        # ref[i] ~ oth[i - lag]
        lo, hi = max(0, lag), min(n, n + lag)
        if hi - lo < 10:
            continue
        val = 0.0
        for i in range(lo, hi):
            val += ref_e[i] * oth_e[i - lag]
        val /= (hi - lo)
        if val > best_val:
            best_val, best_lag = val, lag
    return best_lag * fine_step / SR


def measure_offset(ref_path: str, oth_path: str, start: float, seconds: float, step_ms: float, max_offset: float, fine_ms: float):
    """Return (offset_seconds, confidence) for a window starting at `start` in both files."""
    ref_s = decode_mono(ref_path, seconds, start)
    oth_s = decode_mono(oth_path, seconds, start)
    step = max(1, int(SR * step_ms / 1000))
    ref = envelope(ref_s, step)
    oth = envelope(oth_s, step)
    if len(ref) < 10 or len(oth) < 10:
        die("not enough audio to analyse")
    max_lag = int(max_offset * SR / step)
    lag, score = cross_correlate(ref, oth, max_lag)
    offset = lag * step / SR
    if fine_ms and fine_ms < step_ms:
        offset = refine(ref_s, oth_s, offset, max(1, int(SR * fine_ms / 1000)), step_ms / 1000 * 2)
    return offset, max(0.0, min(1.0, score))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", help="reference recording (usually the camera video)")
    ap.add_argument("second", help="recording to align (external audio or second camera)")
    ap.add_argument("-o", "--output", help="output file when writing a synced result")
    ap.add_argument("--max-offset", type=float, default=30.0, help="largest offset to search in seconds (default 30)")
    ap.add_argument("--analyze-seconds", type=float, default=120.0, help="how much audio to analyse from each file (default 120)")
    ap.add_argument("--step-ms", type=float, default=20.0, help="coarse envelope resolution in ms for the FFT search (default 20)")
    ap.add_argument("--fine-ms", type=float, default=1.0, help="fine resolution in ms for the refinement pass, 0 to skip (default 1)")
    ap.add_argument("--fix-drift", action="store_true", help="also measure the offset near the END and correct clock drift by resampling the second file")
    ap.add_argument("--drift-window", type=float, default=60.0, help="seconds of audio analysed at each end for drift (default 60)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replace-audio", action="store_true", help="write reference video with the second file's audio, aligned")
    mode.add_argument("--trim-second", action="store_true", help="write the second file shifted so it lines up with the reference")
    ap.add_argument("--crf", type=int, default=18)
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    for p in (args.reference, args.second):
        if not probe(p).get("audio"):
            die(f"{p} has no audio stream to correlate")

    offset, score = measure_offset(args.reference, args.second, 0.0, args.analyze_seconds, args.step_ms, args.max_offset, args.fine_ms)

    drift_ratio = 1.0
    drift_info = None
    if args.fix_drift:
        ref_dur = probe(args.reference)["duration"] or 0.0
        sec_dur = probe(args.second)["duration"] or 0.0
        overlap_end = min(ref_dur, sec_dur + offset)  # last reference time both files cover
        head_len = min(args.analyze_seconds, overlap_end)
        tail_start = overlap_end - args.drift_window
        if tail_start <= head_len / 2 + 5:
            info("warning: files too short to measure drift reliably; skipping drift correction")
        else:
            ref_start = tail_start
            sec_start = tail_start - offset
            if sec_start < 0:
                ref_start -= sec_start
                sec_start = 0.0
            ref_s = decode_mono(args.reference, args.drift_window, ref_start)
            oth_s = decode_mono(args.second, args.drift_window, sec_start)
            step = max(1, int(SR * args.step_ms / 1000))
            lag, end_score = cross_correlate(envelope(ref_s, step), envelope(oth_s, step), int(2.0 * SR / step))
            residual = lag * step / SR
            if args.fine_ms:
                residual = refine(ref_s, oth_s, residual, max(1, int(SR * args.fine_ms / 1000)), args.step_ms / 1000 * 2)
            # both measurements represent the offset at the centre of their windows
            head_mid = head_len / 2
            tail_mid = ref_start + args.drift_window / 2
            elapsed = tail_mid - head_mid
            if elapsed > 0 and end_score > 0.1:
                # offset(T) = offset0 - (ratio - 1) * T, where ratio is how fast the second file's clock
                # runs relative to the reference (ratio > 1 = the second file is too long / plays slow)
                drift_ratio = 1.0 - residual / elapsed
                offset = offset + (drift_ratio - 1.0) * head_mid  # extrapolate back to T = 0
                drift_info = {"residual_at_end_seconds": round(residual, 4), "measured_over_seconds": round(elapsed, 2),
                              "drift_ppm": round((drift_ratio - 1) * 1e6, 1),
                              "meaning": "second file runs %.1f ppm %s (%.3fs over %.0fs); it will be resampled to match" % (
                                  abs(drift_ratio - 1) * 1e6, "long/slow" if drift_ratio > 1 else "short/fast", abs(residual), elapsed),
                              "confidence": round(end_score, 3)}
            else:
                info("warning: could not measure drift with confidence; skipping drift correction")

    result = {
        "reference": args.reference,
        "second": args.second,
        "offset_seconds": round(offset, 4),
        "confidence": round(max(0.0, min(1.0, score)), 3),
        "meaning": ("second starts %.3fs %s than reference" % (abs(offset), "later" if offset > 0 else "earlier")),
    }
    if drift_info:
        result["drift"] = drift_info
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
        sec_sr = (second_meta.get("audio") or {}).get("sample_rate") or 48000
        drift_af: List[str] = []
        if abs(drift_ratio - 1.0) > 1e-7:
            # the second file runs long by drift_ratio -> play it faster by that ratio (pitch shift is ~ppm, inaudible)
            drift_af = [f"asetrate={sec_sr * drift_ratio:.6f}", f"aresample={sec_sr}"]

        if args.replace_audio:
            cmd = ffmpeg_base() + ["-i", args.reference]
            if head_trim > 0:
                cmd += ["-ss", f"{head_trim:.4f}"]
            cmd += ["-i", args.second, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
            af_parts = drift_af + ([f"adelay={delay_ms}:all=1"] if delay_ms > 0 else [])
            if af_parts:
                cmd += ["-af", ",".join(af_parts)]
            cmd += aac_args() + ["-shortest", output]
            proc = run(cmd, check=False)
            if proc.returncode != 0:
                cmd = [c for c in cmd if c != "copy"]
                idx = cmd.index("-c:v"); del cmd[idx]
                cmd = cmd[:-1] + video_args(probe(args.reference) if args.replace_audio else probe(args.second), args.crf) + [output]
                run(cmd)
        else:
            if head_trim > 0 and not drift_af:
                cmd = ffmpeg_base() + ["-ss", f"{head_trim:.4f}", "-i", args.second, "-c", "copy", "-avoid_negative_ts", "make_zero", output]
                proc = run(cmd, check=False)
                if proc.returncode != 0:
                    cmd = ffmpeg_base() + ["-ss", f"{head_trim:.4f}", "-i", args.second] + (video_args(probe(args.reference) if args.replace_audio else probe(args.second), args.crf) if has_video else []) + audio_codec_for(output) + [output]
                    run(cmd)
            else:
                cmd = ffmpeg_base()
                if head_trim > 0:
                    cmd += ["-ss", f"{head_trim:.4f}"]
                cmd += ["-i", args.second]
                af_parts = list(drift_af)
                if delay_ms > 0:
                    af_parts.append(f"adelay={delay_ms}:all=1")
                if has_video:
                    vf = []
                    if delay_ms > 0:
                        vf.append(f"tpad=start_duration={offset:.4f}")
                    if drift_af:
                        vf.append(f"setpts=PTS/{drift_ratio:.9f}")
                    if vf:
                        cmd += ["-vf", ",".join(vf)]
                    cmd += video_args(probe(args.reference) if args.replace_audio else probe(args.second), args.crf)
                if af_parts:
                    cmd += ["-af", ",".join(af_parts)]
                cmd += audio_codec_for(output) + [output]
                run(cmd)
        result["output"] = output
        info(f"wrote {output}")

    if args.json:
        emit(result.get("output"), **{k: v for k, v in result.items() if k != "output"})
    else:
        print(f"offset: {result['offset_seconds']:+.3f}s ({result['meaning']}), confidence {result['confidence']:.2f}")
        if drift_info:
            print(f"drift: {drift_info['drift_ppm']:+.1f} ppm ({drift_info['residual_at_end_seconds']:+.3f}s over {drift_info['measured_over_seconds']:.0f}s), confidence {drift_info['confidence']:.2f}")
        if "output" in result:
            print(result["output"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
