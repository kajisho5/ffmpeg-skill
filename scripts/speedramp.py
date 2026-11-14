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

from _common.decision import av_trim, conform_filter, delivered_rate, frame_durations, frame_rate, grid_at_or_after, stream_starts
from _common import add_common, apply_common, aac_args, default_output, die, emit, ffmpeg_base, info, probe, run, video_args, X264_PRESETS, fmt_secs, time_arg
from _common.emit import input_length

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
        span, factor_s = raw.rsplit(":", 1)
        start_s, end_s = span.rsplit("-", 1)
        factor = float(factor_s)
    except ValueError:
        die(f"--segment must look like START-END:FACTOR, got '{raw}'")
    start, end = time_arg(start_s, f"--segment {raw!r} start"), time_arg(end_s, f"--segment {raw!r} end")
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
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    segments = [parse_segment(s) for s in args.segments]
    segments.sort(key=lambda s: s[0])
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = input_length(meta)
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

    vparts, aparts = [], []
    # The coverage check above allows the last end to sit up to 0.5 s off the probed duration.
    # That slack is for a caller who rounded the duration, not a reason to redraw the tail at
    # the last factor. The end bound is omitted only when the stated end is the file's end
    # (within 50 ms): a trim a few milliseconds short of the last packet drops that packet.
    last_runs_to_eof = abs(segments[-1][1] - dur) <= 0.05
    # Every boundary is a frame time and both streams of a segment are cut on it and shifted by the
    # same constant before the speed change (#409), as cut.py's re-cut does. Rebasing each stream
    # of each segment to its own first sample moved a sound that starts 0.3 s late 0.3 s early, and
    # the factor scaled that (+570 ms at 0.5x). The first segment starts at the first frame.
    v0 = stream_starts(meta)[0]
    rate = frame_rate(meta)
    # on a VFR source the picture is delivered at the rate the encoder line forces (its average):
    # closed on r_frame_rate, -r then resampled the joined picture and it drifted 113 ms late (#512)
    out_rate = delivered_rate(meta) or rate
    srate = int((meta.get("audio") or {}).get("sample_rate") or 0)
    bounds = [v0] + [grid_at_or_after(end, v0, rate) for _, end, _ in segments[:-1]]
    retimed = 0.0  # where the segment starts on the output's clock
    for i, (start, end, factor) in enumerate(segments):
        vlabel, alabel = f"v{i}", f"a{i}"
        to_eof = i == len(segments) - 1 and last_runs_to_eof
        seg_end = None if to_eof else (bounds[i + 1] if i + 1 < len(bounds) else grid_at_or_after(end, v0, rate))
        if seg_end is not None and seg_end <= bounds[i] + 1e-6:
            # both ends on the same frame: the trims would be empty and the factor reach no frame
            die(f"--segment {start:g}-{end:g}:{factor:g} holds no frame: both ends fall on the frame at "
                f"{bounds[i]:.3f}s; widen it or merge it into a neighbour")
        vtrim, atrim = av_trim(bounds[i], seg_end, rate)
        # the closing fps puts the sped-up frames back on the delivered grid with its frame
        # duration: concat starts the next segment after the last frame's duration, which setpts
        # leaves at the unscaled 1/rate, so every 2x segment pushed the rest of the picture two
        # frames late against the sound (and added those frames)
        vchain = f"[0:v]{vtrim},setpts=PTS/{factor:.6f},{frame_durations(meta, out_rate)}"
        achain = f"[0:a]{atrim},{atempo_chain(factor)}"
        if out_rate:
            # Each segment holds the frames (and samples) between its retimed ends on the whole
            # output's grid, not its own length rounded: eight 0.5 s segments at 27 fps rounded
            # to 14 frames each, concat advanced 14/27 s per segment and the last flash landed
            # 130 ms late. The picture is sampled on the output's grid (an offset of under half
            # a frame, and fps's start_time) and, but for a last segment that runs to the end,
            # padded by a frame or two and cut to its count; the sound is padded or cut to its
            # own count, so neither stream drifts across segments.
            first = round(retimed * out_rate)
            shift = first / out_rate - retimed
            vchain = (f"[0:v]{vtrim},setpts=PTS/{factor:.6f}{-shift:+.6f}/TB,"
                      f"{frame_durations(meta, out_rate)}:start_time=0")
            if seg_end is not None:
                after = retimed + (seg_end - bounds[i]) / factor
                vchain += f",tpad=stop=2:stop_mode=clone,trim=end_frame={round(after * out_rate) - first}"
                if srate:
                    achain += f",{conform_filter(round(after * srate) - round(retimed * srate), srate)}"
                retimed = after
        vparts.append(f"{vchain}[{vlabel}]")
        if has_audio:
            aparts.append(f"{achain}[{alabel}]")

    # the two streams are joined by two concats: one concat over both started each segment after
    # the longer of its two streams, so a picture a frame longer than its sound moved both late
    n = len(segments)
    fc = ";".join(vparts) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    maps = ["-map", "[outv]"]
    if has_audio:
        fc += ";" + ";".join(aparts) + ";" + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[outa]"
        maps += ["-map", "[outa]"]

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
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v['width']}x{v['height']}, {len(segments)} speed segments)")
    emit(output, dropped_non_av_streams=bool(meta.get("subtitle_streams") or meta.get("data_streams")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
