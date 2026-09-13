#!/usr/bin/env python3
"""Find scene changes and loud moments, and propose highlight candidates so the
agent can plan an edit or a digest without watching the whole file.

Scene cuts come from ffmpeg's scdet; energy peaks from a 0.5 s RMS envelope
of the audio. Highlight candidates are scenes ranked by --rank-by: "audio"
(default, loudest first) or "duration" (longest first). Both are proxies,
not a judgement of what matters: "audio" misses a quiet but important
moment (a confession, a punchline landing in silence) and can surface pure
crowd noise; "duration" just finds long unbroken takes. Neither replaces
watching the contact sheet (--sheet) before committing to a cut.

Examples:
  python3 scenes.py talk.mp4                                # scenes + peaks, JSON
  python3 scenes.py event.mp4 --highlights 5 --target 60   # 5 candidate ranges summing to ~60 s
  python3 scenes.py event.mp4 --highlights 4 --edl picks.txt   # cut.py --segments compatible list
  python3 scenes.py event.mp4 --sheet scenes.png             # one thumbnail per scene
  python3 scenes.py talk.mp4 --highlights 5 --rank-by duration  # longest unbroken scenes, not loudest
"""
import argparse
import math
import sys
from typing import Dict, List, Tuple

# `detect_scenes` moved into _common/probe.py in 1.16.0 (see silence.py); the body is unchanged.
from _common import detect_scenes, STATE, add_common, apply_common, default_font_file, die, emit, escape_filter_path, ffmpeg_base, info, print_json, probe, run, decode_pcm_mono, rms_envelope



def audio_envelope(path: str, step_s: float) -> List[float]:
    """RMS level per step_s window at 8 kHz, absolute (a loud scene scores higher); [] when the
    audio cannot be decoded (the cut scoring then runs on the picture alone)."""
    return rms_envelope(decode_pcm_mono(path, 8000, check=False), int(8000 * step_s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--threshold", type=float, default=8.0, help="minimum scdet score for a cut, 0-100 (default 8)")
    ap.add_argument("--ratio", type=float, default=3.0, help="a cut must exceed this multiple of the neighbouring frames' median score (default 3; lower = more cuts)")
    ap.add_argument("--min-scene", type=float, default=1.0, help="ignore cuts closer than this in seconds (default 1)")
    ap.add_argument("--highlights", type=int, default=0, help="number of highlight ranges to propose")
    ap.add_argument("--rank-by", choices=["audio", "duration"], default="audio",
                    help="how to rank scenes for --highlights: audio energy (default) or scene duration")
    ap.add_argument("--target", type=float, help="with --highlights: total seconds the picks should add up to (trims long scenes)")
    ap.add_argument("--max-scene", type=float, default=15.0, help="cap a highlight range at this many seconds (default 15)")
    ap.add_argument("--edl", help="write highlight ranges as START-END lines (cut.py --segments format)")
    ap.add_argument("--sheet", help="write a contact sheet PNG with the first frame of every scene")
    ap.add_argument("--no-timecode", action="store_true", help="--sheet without the burnt-in timecode stamp (a way out if drawtext itself is unusable, see doctor)")
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
        if args.rank_by == "duration":
            rank_key = lambda sc: (-sc["duration"], sc["start"])
        else:
            rank_key = lambda sc: (-sc["audio_rms"], sc["start"])
        ranked = sorted(scenes, key=rank_key)[: args.highlights]
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
        result["highlights_rank_by"] = args.rank_by
        info(f"proposed {len(picks)} highlight ranges totalling {result['highlights_total']:.1f}s")
        if args.edl:
            if not STATE.dry_run:  # the contract says --edl is not written under --dry-run
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
        stamp = ""
        if not args.no_timecode:
            default_font = default_font_file("DejaVu Sans")
            font_prefix = f"fontfile={escape_filter_path(default_font)}:" if default_font else ""
            stamp = f",drawtext=text='%{{pts\\:hms}}':{font_prefix}fontcolor=white:fontsize=h/14:box=1:boxcolor=black@0.55:boxborderw=4:x=6:y=6"
        vf = (f"select='{expr}',scale={tile_w}:-2{stamp},"
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
