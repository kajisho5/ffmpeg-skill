#!/usr/bin/env python3
"""Remove silences / dead air (jump-cut editing) or just list them.

Detects quiet stretches with ffmpeg's silencedetect, keeps a margin on each
side so words are not clipped, drops gaps shorter than --min-silence, and
writes a frame-accurate re-encode in one pass (select/aselect filters).

Examples:
  python3 silence.py talk.mp4                                 # -35 dB, gaps >= 0.6 s, 0.15 s margin
  python3 silence.py talk.mp4 --threshold -40 --min-silence 1 --margin 0.25
  python3 silence.py talk.mp4 --list                          # print the silences and the resulting cut list, no output
  python3 silence.py talk.mp4 --edl keep.txt                  # also save the kept ranges (START-END per line, cut.py --segments format)
"""
import argparse
import re
import sys
from typing import List, Tuple

from _common import video_args, aac_args, add_common, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, print_json, probe, require_tool, run, x264_args

SIL_RE = re.compile(r"silence_(start|end): ([0-9.]+)")


def detect(path: str, threshold: float, min_silence: float) -> List[Tuple[float, float]]:
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af",
           f"silencedetect=noise={threshold}dB:d={min_silence}", "-f", "null", "-"]
    proc = run(cmd, quiet=True, check=False)
    if proc.returncode != 0:
        die(f"silencedetect failed:\n{proc.stderr.strip()[-800:]}")
    silences: List[Tuple[float, float]] = []
    start = None
    for kind, val in SIL_RE.findall(proc.stderr):
        if kind == "start":
            start = float(val)
        elif start is not None:
            silences.append((start, float(val)))
            start = None
    if start is not None:  # silence runs to the end
        silences.append((start, float("inf")))
    return silences


def keep_ranges(silences: List[Tuple[float, float]], duration: float, margin: float, min_keep: float) -> List[Tuple[float, float]]:
    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in silences:
        s_adj = max(cursor, s + margin)
        if s_adj - cursor >= min_keep:
            keeps.append((cursor, s_adj))
        cursor = min(duration, e - margin) if e != float("inf") else duration
    if duration - cursor >= min_keep:
        keeps.append((cursor, duration))
    return keeps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_tight.<ext>)")
    ap.add_argument("--threshold", type=float, default=-35.0, help="silence level in dBFS (default -35; use -40..-45 for quiet rooms)")
    ap.add_argument("--min-silence", type=float, default=0.6, help="only remove gaps at least this long in seconds (default 0.6)")
    ap.add_argument("--margin", type=float, default=0.15, help="seconds of silence to keep on each side of speech (default 0.15)")
    ap.add_argument("--min-keep", type=float, default=0.2, help="drop kept pieces shorter than this (default 0.2)")
    ap.add_argument("--list", action="store_true", help="only print silences and the kept ranges")
    ap.add_argument("--edl", help="write the kept ranges to this file, one START-END per line")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream to analyse")
    duration = meta.get("duration") or 0.0
    silences = detect(args.input, args.threshold, args.min_silence)
    keeps = keep_ranges(silences, duration, args.margin, args.min_keep)
    kept = sum(e - s for s, e in keeps)
    removed = max(0.0, duration - kept)
    summary = {
        "silences": [[round(s, 3), None if e == float("inf") else round(e, 3)] for s, e in silences],
        "keep": [[round(s, 3), round(e, 3)] for s, e in keeps],
        "input_duration": round(duration, 3),
        "kept_duration": round(kept, 3),
        "removed_seconds": round(removed, 3),
    }
    info(f"{len(silences)} silences, keeping {len(keeps)} ranges: {kept:.2f}s of {duration:.2f}s (removing {removed:.2f}s)")

    if args.edl:
        with open(args.edl, "w", encoding="utf-8") as fh:
            for s, e in keeps:
                fh.write(f"{s:.3f}-{e:.3f}\n")
        info(f"wrote {args.edl}")

    if args.list:
        if args.json:
            emit(None, **summary)
        else:
            print_json(summary)
        return 0
    if not keeps:
        die("nothing would be kept; raise --threshold (e.g. -45) or check the audio")
    if not silences or removed < 0.05:
        info("no removable silence found; output would equal the input")

    output = args.output or default_output(args.input, "tight")
    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{expr}',asetpts=N/SR/TB"
    cmd = ffmpeg_base() + ["-i", args.input]
    if meta.get("video"):
        cmd += ["-vf", vf] + video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += ["-af", af] + aac_args() + [output]
    run(cmd)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, expected ~{kept:.3f}s)")
    emit(output, **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
