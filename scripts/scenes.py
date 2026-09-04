#!/usr/bin/env python3
"""Find scene changes and loud moments, and propose highlight candidates so the
agent can plan an edit or a digest without watching the whole file.

Scene cuts come from ffmpeg's scdet; energy peaks from a 0.5 s RMS envelope
of the audio. Highlight candidates are the scenes ranked by audio energy
(and, optionally, by motion).

Examples:
  python3 scenes.py talk.mp4                                # scenes + peaks, JSON
  python3 scenes.py event.mp4 --highlights 5 --target 60   # 5 candidate ranges summing to ~60 s
  python3 scenes.py event.mp4 --highlights 4 --edl picks.txt   # cut.py --segments compatible list
  python3 scenes.py event.mp4 --sheet scenes.png             # one thumbnail per scene
"""
import argparse
import math
import os
import re
import struct
import subprocess
import sys
from typing import Dict, List, Tuple

from _common import add_common, apply_common, die, emit, ffmpeg_base, info, print_json, probe, require_tool, run

SCORE_RE = re.compile(r"frame:(\d+)\s+pts:\d+\s+pts_time:([0-9.]+)")


def detect_scenes(path: str, threshold: float, min_len: float, duration: float, ratio: float = 3.0) -> List[float]:
    """Scene cuts = frames whose scdet score is above `threshold` AND stands out from its
    neighbourhood (score > ratio x median of the surrounding +-12 frames). Sustained motion,
    flashes and fast pans raise the score on many consecutive frames and are rejected;
    a real cut is a one-frame spike. On real footage this roughly doubles precision at
    equal recall compared with the raw scdet threshold."""
    ffmpeg = require_tool("ffmpeg")
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-an", "-vf",
                           "scale=320:-2,scdet=threshold=0:sc_pass=1,metadata=print:file=-", "-f", "null", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    times: List[float] = []
    scores: List[float] = []
    cur_t = None
    for line in proc.stdout.splitlines():
        m = SCORE_RE.match(line)
        if m:
            cur_t = float(m.group(2))
            continue
        if line.startswith("lavfi.scd.score=") and cur_t is not None:
            try:
                times.append(cur_t)
                scores.append(float(line.split("=", 1)[1]))
            except ValueError:
                pass
    cuts = [0.0]
    if not scores:
        return cuts
    w = 12
    for i, sc in enumerate(scores):
        if sc < threshold:
            continue
        lo, hi = max(0, i - w), min(len(scores), i + w + 1)
        neigh = sorted(scores[lo:i] + scores[i + 1:hi])
        med = neigh[len(neigh) // 2] if neigh else 0.0
        if sc < ratio * max(med, 0.5):
            continue
        # keep only the local maximum inside +-2 frames
        if any(scores[j] > sc for j in range(max(0, i - 2), min(len(scores), i + 3)) if j != i):
            continue
        t = times[i]
        if t - cuts[-1] >= min_len:
            cuts.append(t)
    if duration - cuts[-1] < min_len and len(cuts) > 1:
        cuts.pop()
    return cuts


def audio_envelope(path: str, step_s: float) -> List[float]:
    ffmpeg = require_tool("ffmpeg")
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    n = len(proc.stdout) // 2
    if n == 0:
        return []
    samples = struct.unpack(f"<{n}h", proc.stdout[: n * 2])
    step = max(1, int(8000 * step_s))
    env = []
    for i in range(0, n, step):
        block = samples[i:i + step]
        env.append(math.sqrt(sum(x * x for x in block) / len(block)) / 32768.0)
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--threshold", type=float, default=8.0, help="minimum scdet score for a cut, 0-100 (default 8)")
    ap.add_argument("--ratio", type=float, default=3.0, help="a cut must exceed this multiple of the neighbouring frames' median score (default 3; lower = more cuts)")
    ap.add_argument("--min-scene", type=float, default=1.0, help="ignore cuts closer than this in seconds (default 1)")
    ap.add_argument("--highlights", type=int, default=0, help="number of highlight ranges to propose")
    ap.add_argument("--target", type=float, help="with --highlights: total seconds the picks should add up to (trims long scenes)")
    ap.add_argument("--max-scene", type=float, default=15.0, help="cap a highlight range at this many seconds (default 15)")
    ap.add_argument("--edl", help="write highlight ranges as START-END lines (cut.py --segments format)")
    ap.add_argument("--sheet", help="write a contact sheet PNG with the first frame of every scene")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = meta.get("duration") or 0.0
    cuts = detect_scenes(args.input, args.threshold, args.min_scene, dur, args.ratio)
    bounds = cuts + [dur]
    step_s = 0.5
    env = audio_envelope(args.input, step_s) if meta.get("audio") else []

    scenes = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        if e - s <= 0.05:
            continue
        seg = env[int(s / step_s): max(int(s / step_s) + 1, int(e / step_s))] if env else []
        energy = (sum(seg) / len(seg)) if seg else 0.0
        peak = max(seg) if seg else 0.0
        scenes.append({"index": len(scenes), "start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3),
                       "audio_rms": round(energy, 4), "audio_peak": round(peak, 4)})
    peaks = []
    if env:
        thr = sorted(env)[int(len(env) * 0.9)] if len(env) > 10 else max(env)
        for i, val in enumerate(env):
            if val >= thr and val > 0.02 and (i == 0 or env[i - 1] < val) and (i == len(env) - 1 or env[i + 1] <= val):
                peaks.append({"time": round(i * step_s, 2), "rms": round(val, 4)})
        peaks = sorted(peaks, key=lambda p: -p["rms"])[:20]
        peaks.sort(key=lambda p: p["time"])

    result: Dict = {"file": args.input, "duration": round(dur, 3), "scene_count": len(scenes), "scenes": scenes, "audio_peaks": peaks}
    info(f"{len(scenes)} scenes, {len(peaks)} audio peaks over {dur:.1f}s")

    if args.highlights:
        ranked = sorted(scenes, key=lambda sc: (-sc["audio_rms"], sc["start"]))[: args.highlights]
        picks: List[Tuple[float, float]] = []
        budget = args.target if args.target else None
        per = (budget / max(1, len(ranked))) if budget else args.max_scene
        for sc in ranked:
            length = min(sc["duration"], per, args.max_scene)
            # take the loudest window inside the scene
            best_s = sc["start"]
            if env and length < sc["duration"]:
                best, best_s = -1.0, sc["start"]
                win = max(1, int(length / step_s))
                lo, hi = int(sc["start"] / step_s), max(int(sc["start"] / step_s) + 1, int(sc["end"] / step_s) - win)
                for i in range(lo, hi + 1):
                    val = sum(env[i:i + win])
                    if val > best:
                        best, best_s = val, i * step_s
            picks.append((round(best_s, 2), round(min(sc["end"], best_s + length), 2)))
        picks.sort()
        result["highlights"] = [{"start": s, "end": e, "duration": round(e - s, 2)} for s, e in picks]
        result["highlights_total"] = round(sum(e - s for s, e in picks), 2)
        info(f"proposed {len(picks)} highlight ranges totalling {result['highlights_total']:.1f}s")
        if args.edl:
            with open(args.edl, "w", encoding="utf-8") as fh:
                for s, e in picks:
                    fh.write(f"{s:.2f}-{e:.2f}\n")
            info(f"wrote {args.edl}")

    if args.sheet:
        n = len(scenes)
        cols = min(4, max(1, n))
        rows = max(1, math.ceil(n / cols))
        tile_w = 1280 // cols // 2 * 2
        # exactly one frame per scene: the frame index at the scene start
        fps = meta["video"].get("fps") or 30.0
        expr = "+".join(f"eq(n\\,{int(round(sc['start'] * fps))})" for sc in scenes)
        vf = (f"select='{expr}',scale={tile_w}:-2,drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=h/14:box=1:boxcolor=black@0.55:boxborderw=4:x=6:y=6,"
              f"tile={cols}x{rows}:padding=2:margin=2:color=0x202020")
        run(ffmpeg_base() + ["-i", args.input, "-vf", vf, "-frames:v", "1", "-fps_mode", "vfr", args.sheet])
        info(f"wrote {args.sheet}")
        result["sheet"] = args.sheet

    if args.json:
        emit(None, **result)
    else:
        print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
