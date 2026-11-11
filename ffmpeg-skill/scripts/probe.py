#!/usr/bin/env python3
"""Inspect a media file and print a compact JSON summary.

Reports duration, fps (and whether variable frame rate is suspected), resolution,
codecs, pixel format / color space, audio channels and sample rate.

Examples:
  python3 probe.py input.mp4
  python3 probe.py a.mp4 b.mov --compact
  python3 probe.py input.mp4 --field duration
  python3 probe.py input.mp4 --keyframes-near 12.4,47 --keyframe-window 5

--keyframes-near T[,T...] adds `keyframes`: for each time, the video keyframes within
--keyframe-window seconds of it, and the nearest one at or before it and at or after it -- the
points a stream copy can start at, and where cut.py --smart's re-encode around a cut ends.
"""
import argparse
import math
import sys

from _common import add_common, analyze_levels, apply_common, die, keyframe_times, print_json, probe, time_arg


def keyframe_candidates(result: dict, times: list, window: float) -> list:
    """For each time (seconds from the file's start), the keyframes within `window` of it and the
    nearest of those at or before / at or after it (null when none is within the window), on the
    same clock (the file's start_time subtracted). The picture is the stream probe() reports (`V`:
    not a cover picture). A failed read is an error, not an empty neighbourhood."""
    origin = float(result.get("start_time") or 0.0)
    out = []
    for t in times:
        # keyframe_times() reads past hi (an interval's end is exclusive), so one on the edge is kept
        read = keyframe_times(result["file"], origin + t - window, origin + t + window, "V:0")
        if read is None:
            die(f"ffprobe could not read the keyframes of {result['file']} around {t:g}s", kind="ffmpeg")
        # the read starts at the keyframe at or before the window, which may lie outside it
        keys = [k for k in (round(k - origin, 6) for k in read) if t - window - 1e-6 <= k <= t + window + 1e-6]
        before = [k for k in keys if k <= t + 1e-6]
        after = [k for k in keys if k >= t - 1e-6]
        out.append({"at": t, "window": window, "keyframes": keys, "before": before[-1] if before else None,
                    "after": after[0] if after else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="media file(s) to inspect")
    ap.add_argument("--compact", action="store_true", help="one human-readable line per file instead of JSON")
    ap.add_argument("--field", help="print only this top-level field (e.g. duration) or dotted path (video.fps)")
    ap.add_argument("--analyze", action="store_true", help="also sample picture levels (first 20 s) and flag Log-looking footage")
    ap.add_argument("--keyframes-near", metavar="T[,T...]",
                    help="also list the video keyframes around these times (seconds, mm:ss or hh:mm:ss.ms): the ones within "
                         "--keyframe-window and the nearest before and after each, as `keyframes`")
    ap.add_argument("--keyframe-window", type=float, default=5.0, metavar="S",
                    help="--keyframes-near: seconds either side of each time to read (default 5)")
    add_common(ap)  # --json / --dry-run / --fast / --progress accepted for uniformity; output is JSON already
    args = ap.parse_args()
    apply_common(args)

    if not math.isfinite(args.keyframe_window) or args.keyframe_window <= 0:
        die(f"--keyframe-window must be a positive, finite number of seconds, got {args.keyframe_window:g}")
    if args.keyframes_near is not None and not any(t.strip() for t in args.keyframes_near.split(",")):
        die("--keyframes-near takes one or more times (e.g. 12.4,47), got none")
    results = [probe(p) for p in args.inputs]
    if args.keyframes_near:
        for r in results:
            fps = (r.get("video") or {}).get("fps")
            times = [time_arg(t.strip(), "--keyframes-near", fps) for t in args.keyframes_near.split(",") if t.strip()]
            if any(not math.isfinite(t) or t < 0 for t in times):
                die("--keyframes-near takes finite times at or after 0")
            r["keyframes"] = keyframe_candidates(r, times, args.keyframe_window) if r.get("video") else []
    if args.analyze:
        for r in results:
            if r.get("video"):
                r["levels"] = analyze_levels(r["file"])

    if args.field:
        for r in results:
            cur = r
            for key in args.field.split("."):
                cur = cur.get(key) if isinstance(cur, dict) else None
            print(cur if cur is not None else "")
        return 0

    if args.compact:
        for r in results:
            v, a = r.get("video") or {}, r.get("audio") or {}
            dur = r.get("duration")
            line = f"{r['file']}: {dur:.3f}s" if dur is not None else f"{r['file']}: ?s"
            if v:
                line += f" | {v.get('width')}x{v.get('height')} @ {v.get('fps')}fps {v.get('codec')} {v.get('pix_fmt')}"
                if v.get("variable_frame_rate_suspected"):
                    line += " (VFR?)"
                if v.get("bt2020_or_hdr"):  # hdr_format also names the BT.2020 SDR case
                    line += f" [{v.get('hdr_format')}]"
                if r.get("levels", {}).get("looks_like_log"):
                    line += " [Log?]"
            else:
                line += " | no video"
            if a:
                line += f" | audio {a.get('codec')} {a.get('channels')}ch {a.get('sample_rate')}Hz"
            else:
                line += " | no audio"
            for k in r.get("keyframes") or []:
                before, after = ("-" if x is None else f"{x:g}" for x in (k["before"], k["after"]))
                line += f" | keyframes near {k['at']:g}s: {before}/{after} ({len(k['keyframes'])} within {k['window']:g}s)"
            print(line)
        return 0

    print_json(results[0] if len(results) == 1 else results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
