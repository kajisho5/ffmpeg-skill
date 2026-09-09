#!/usr/bin/env python3
"""Step through different constant speeds across a clip's timeline (a speed ramp).

Distinct from fit.py --duration --method speed, which applies one constant
factor to the whole clip. This tool takes a list of --segment START-END:FACTOR
pieces covering the clip start to end with no gaps or overlaps, each played
at its own constant speed (pitch-preserving audio, matching fit.py), then
concatenates them back together -- the classic "speed up, then slow way
down for the punch, then speed back up" edit, built from a few constant
segments rather than a continuous curve (which this tool does not attempt:
picking exactly where a ramp should ease in or out is a judgement call for
the calling agent, made concrete here as segment boundaries it supplies).

Examples:
  python3 speedramp.py action.mp4 --segment 0-3:1.0 --segment 3-4:0.25 --segment 4-8:2.0
  python3 speedramp.py clip.mp4 --segment 0-2:2.0 --segment 2-6:1.0
"""
import argparse
import sys
from typing import List, Tuple

from _common import add_common, apply_common, aac_args, default_output, die, emit, ffmpeg_base, info, probe, run, video_args

MAX_SPEED = 20.0
MIN_SPEED = 0.05


def atempo_chain(factor: float) -> str:
    """atempo accepts 0.5..100 per instance; chain for factors outside that range."""
    parts: List[str] = []
    remaining = factor
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 100.0:
        parts.append("atempo=100.0")
        remaining /= 100.0
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def parse_segment(raw: str) -> Tuple[float, float, float]:
    try:
        span, factor_s = raw.split(":")
        start_s, end_s = span.split("-")
        start, end, factor = float(start_s), float(end_s), float(factor_s)
    except ValueError:
        die(f"--segment must look like START-END:FACTOR, got '{raw}'")
    if end <= start:
        die(f"--segment {raw}: END must be after START")
    if not MIN_SPEED <= factor <= MAX_SPEED:
        die(f"--segment {raw}: FACTOR must be {MIN_SPEED}..{MAX_SPEED}")
    return start, end, factor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_ramp.<ext>)")
    ap.add_argument("--segment", action="append", required=True, dest="segments",
                     help=f"START-END:FACTOR, repeatable; segments must cover 0..duration with no gaps or overlaps, in order. FACTOR is {MIN_SPEED}..{MAX_SPEED} (2.0 = twice as fast, 0.5 = half speed)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    segments = [parse_segment(s) for s in args.segments]
    segments.sort(key=lambda s: s[0])
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = meta.get("duration") or 0.0
    if abs(segments[0][0] - 0.0) > 0.01:
        die(f"segments must start at 0, first segment starts at {segments[0][0]:g}")
    if abs(segments[-1][1] - dur) > 0.5:
        die(f"segments must cover the whole clip (0..{dur:.3f}), last segment ends at {segments[-1][1]:g}")
    for i in range(len(segments) - 1):
        if abs(segments[i][1] - segments[i + 1][0]) > 0.01:
            die(f"segments must be contiguous with no gap/overlap: segment {i} ends at {segments[i][1]:g}, "
                f"segment {i + 1} starts at {segments[i + 1][0]:g}")
    has_audio = bool(meta.get("audio"))
    output = args.output or default_output(args.input, "ramp")

    vparts, aparts, labels = [], [], []
    for i, (start, end, factor) in enumerate(segments):
        vlabel, alabel = f"v{i}", f"a{i}"
        end_expr = f"{end:.3f}" if i < len(segments) - 1 else None
        trim = f"trim=start={start:.3f}" + (f":end={end_expr}" if end_expr else "")
        vparts.append(f"[0:v]{trim},setpts=(PTS-STARTPTS)/{factor:.6f}[{vlabel}]")
        labels.append(f"[{vlabel}]")
        if has_audio:
            atrim = f"atrim=start={start:.3f}" + (f":end={end_expr}" if end_expr else "")
            aparts.append(f"[0:a]{atrim},asetpts=PTS-STARTPTS,{atempo_chain(factor)}[{alabel}]")

    if has_audio:
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
        fc = ";".join(vparts + aparts) + f";{concat_inputs}concat=n={len(segments)}:v=1:a=1[outv][outa]"
        maps = ["-map", "[outv]", "-map", "[outa]"]
    else:
        concat_inputs = "".join(f"[v{i}]" for i in range(len(segments)))
        fc = ";".join(vparts) + f";{concat_inputs}concat=n={len(segments)}:v=1:a=0[outv]"
        maps = ["-map", "[outv]"]

    cmd = ffmpeg_base() + ["-i", args.input, "-filter_complex", fc] + maps
    cmd += video_args(meta, args.crf, args.preset)
    cmd += ["-fps_mode", "cfr", "-r", f"{meta['video'].get('fps') or 30.0:g}"]
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd.append(output)
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {len(segments)} speed segments)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
