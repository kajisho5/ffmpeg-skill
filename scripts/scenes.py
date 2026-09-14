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
from typing import Dict, List, Optional, Tuple

# `detect_scenes` moved into _common/probe.py in 1.16.0 (see silence.py); the body is unchanged.
from _common import (detect_scenes, STATE, add_common, apply_common, beat_grid, default_font_file, die, emit,
                     escape_filter_path, ffmpeg_base, info, print_json, probe, run, decode_pcm_mono,
                     rms_envelope, BEAT_MIN_CONFIDENCE)



def audio_envelope(path: str, step_s: float, *, rate: int = 8000,
                   samples: "Optional[List[float]]" = None) -> List[float]:
    """RMS level per step_s window, absolute (a loud scene scores higher); [] when the audio
    cannot be decoded (the cut scoring then runs on the picture alone).

    `samples` reuses PCM a caller already decoded rather than decoding the same file twice --
    --beats needs a 10 ms envelope and the scene scoring a 0.5 s one, and 0.5 s is an integer
    multiple of 10 ms, so both come from one pass.
    """
    if samples is None:
        samples = decode_pcm_mono(path, rate, check=False)
    return rms_envelope(samples, int(rate * step_s))


def parse_beat_range(text: str) -> "tuple":
    """`--beat-range 60-200` as (lo, hi) BPM."""
    try:
        lo, hi = (float(p) for p in str(text).replace(" ", "").split("-", 1))
    except ValueError:
        die(f"--beat-range: expected LO-HI in BPM (e.g. 60-200), got {text!r}", kind="input")
    if not (0 < lo < hi):
        die(f"--beat-range {text}: LO must be above 0 and below HI", kind="input")
    return (lo, hi)


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
    ap.add_argument("--beats", action="store_true",
                    help="measure the music's beat grid (tempo, beat times, confidence) and report it; "
                         "a measurement, not a proposal -- no cut is made and no beat is invented")
    ap.add_argument("--beat-step", type=float, default=0.01,
                    help="envelope resolution in seconds for the onset pass with --beats (default 0.01)")
    ap.add_argument("--beat-range", default="60-200",
                    help="tempo search range in BPM for --beats (default 60-200)")
    ap.add_argument("--min-confidence", type=float, default=BEAT_MIN_CONFIDENCE,
                    help="with --beats: below this confidence the grid is still reported, marked "
                         f"usable: false (default {BEAT_MIN_CONFIDENCE})")
    ap.add_argument("--sheet", help="write a contact sheet PNG with the first frame of every scene")
    ap.add_argument("--no-timecode", action="store_true", help="--sheet without the burnt-in timecode stamp (a way out if drawtext itself is unusable, see doctor)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    # Only parsed when it is going to be used: --beat-range is a --beats flag, and a run that
    # never asked for beats should not be able to die on one.
    beat_range = parse_beat_range(args.beat_range) if args.beats else (60.0, 200.0)
    if args.beats:
        if not meta.get("audio"):
            die("--beats needs an audio stream; this file has none", kind="input")
        if args.beat_step <= 0:
            die("--beat-step must be greater than 0", kind="input")
    dur = meta.get("duration") or 0.0
    cuts = detect_scenes(args.input, args.threshold, args.min_scene, dur, args.ratio)
    bounds = cuts + [dur]
    step_s = 0.5
    # With --beats the file is decoded once, at the finer rate, and both envelopes come from that
    # one pass: the 0.5 s scene blocks are an exact multiple of the 10 ms onset blocks.
    beat_rate = 22050
    fine_samples = decode_pcm_mono(args.input, beat_rate, check=False) if (args.beats and meta.get("audio")) else None
    if fine_samples is not None:
        env = audio_envelope(args.input, step_s, rate=beat_rate, samples=fine_samples)
    else:
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

    if args.beats:
        # A beat grid is a measurement of the music's periodicity, not a statement about where a
        # cut belongs. scenes.py reports what it measured, including a low confidence: reporting a
        # weak measurement is honest, and only a tool that CHANGES a file refuses to act on one.
        fine = rms_envelope(fine_samples or [], max(1, int(round(beat_rate * args.beat_step))))
        grid = beat_grid(fine, args.beat_step, bpm_range=beat_range,
                         min_confidence=args.min_confidence, duration=dur)
        result["beats"] = grid["beats"]
        result["beat_grid"] = {
            # The regular grid AND the subset a measured onset supports. A tool that MOVES
            # something (cut.py --snap beats) may only use the subset; scenes.py reports both,
            # because here the regular grid is the measurement being made.
            "supported_beats": grid["supported_beats"],
            "tempo_bpm": grid["tempo_bpm"], "interval": grid["interval"],
            "confidence": grid["confidence"], "phase": grid["phase"],
            "onsets": len(grid["onsets"]), "supported": grid["supported"],
            "unsupported": grid["unsupported"], "method": grid["method"],
            "step_s": grid["step_s"], "range_bpm": grid["range_bpm"], "usable": grid["usable"],
        }
        if grid["tempo_bpm"] is None:
            info(f"--beats: no steady pulse in this audio (confidence {grid['confidence']:.2f}) -- "
                 "speech, ambience or rubato has no tempo to measure")
        else:
            info(f"--beats: {grid['tempo_bpm']:.1f} BPM, {len(grid['beats'])} beats, confidence "
                 f"{grid['confidence']:.2f} ({grid['supported']} of {len(grid['beats'])} grid points "
                 f"have a measured onset)"
                 + ("" if grid["usable"] else f" -- below --min-confidence {args.min_confidence}, usable: false"))

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
