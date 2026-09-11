#!/usr/bin/env python3
"""Cut away to clip B over clip A for a while, then come back -- A's timeline unchanged.

"Cut to the product shot from 0:12 to 0:16, keep my voice underneath" is the
classic B-roll instruction. A plays as it is; during each window B's picture is
shown instead (scaled/padded to A's frame like join.py normalises), and A resumes
at its own time when the window ends. This is a cutaway, not a splice: the output
is exactly as long as A, and A is re-encoded once.

--insert/--at come in pairs, once per cutaway; --duration (or --end) and --from
(where in B to start) are per cutaway too and default to 4 s and 0. --audio says
what plays under a cutaway: `a` (default, A's own audio untouched, stream-copied),
`b` (B's audio replaces A's inside the window), or `mix` (both).

Examples:
  python3 broll.py talk.mp4 --insert product.mp4 --at 12 --duration 4
  python3 broll.py talk.mp4 --insert shot1.mp4 --at 12 --end 16 --insert shot2.mp4 --at 40 --from 2
  python3 broll.py talk.mp4 --insert demo.mp4 --at 30 --duration 8 --audio mix
"""
import argparse
import sys
from typing import Any, Dict, List

from _common import STATE, add_common, aac_args, apply_common, cfr_args, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, video_args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="the A-roll (its timeline and length are kept)")
    ap.add_argument("-o", "--output", help="output file (default: <name>_broll.<ext>)")
    ap.add_argument("--insert", action="append", required=True, metavar="B", help="B-roll clip (repeat with --at for several cutaways)")
    ap.add_argument("--at", action="append", required=True, metavar="TIME", help="where in A the cutaway starts (seconds or mm:ss); one per --insert")
    ap.add_argument("--duration", action="append", metavar="T", help="cutaway length (default 4); one per --insert, or omit")
    ap.add_argument("--end", action="append", metavar="TIME", help="where in A the cutaway ends, instead of --duration")
    ap.add_argument("--from", dest="from_", action="append", metavar="TIME", help="where in B to start from (default 0); one per --insert, or omit")
    ap.add_argument("--audio", choices=["a", "b", "mix"], default="a", help="under a cutaway: A's audio (default), B's audio, or both mixed")
    ap.add_argument("--pad-color", default="black", help="pad colour when B's aspect differs from A's (default black)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    n = len(args.insert)
    if len(args.at) != n:
        die(f"{n} --insert but {len(args.at)} --at: give one --at per --insert")
    for name, values in (("--duration", args.duration), ("--end", args.end), ("--from", args.from_)):
        if values and len(values) not in (1, n):
            die(f"{name} given {len(values)} times for {n} cutaways: give it once per --insert, or once for all, or not at all")
    if args.duration and args.end:
        die("--duration and --end exclude each other")

    meta_a = probe(args.input)
    if not meta_a.get("video"):
        die("A-roll has no video stream")
    dur_a = meta_a.get("duration") or 0.0
    w, h = meta_a["video"]["width"], meta_a["video"]["height"]
    fps = meta_a["video"].get("fps") or 30.0
    has_audio_a = bool(meta_a.get("audio"))

    def per(values: List[str], i: int, default: str) -> str:
        if not values:
            return default
        return values[i] if len(values) == n else values[0]

    cutaways: List[Dict[str, Any]] = []
    for i, path in enumerate(args.insert):
        meta_b = probe(path)
        if not meta_b.get("video"):
            die(f"{path} has no video stream")
        at = parse_time(args.at[i], fps)
        start_b = parse_time(per(args.from_, i, "0"), fps)
        if args.end:
            end = parse_time(per(args.end, i, "0"), fps)
            length = end - at
        else:
            length = parse_time(per(args.duration, i, "4"), fps)
        if length <= 0:
            die(f"cutaway {i + 1}: length must be > 0 (at {at:g}s, got {length:g}s)")
        if dur_a and at >= dur_a:
            die(f"cutaway {i + 1}: --at {at:g}s is past the end of the A-roll ({dur_a:.3f}s)")
        if dur_a and at + length > dur_a + 0.01:
            die(f"cutaway {i + 1}: {at:g}s + {length:g}s runs past the end of the A-roll ({dur_a:.3f}s)")
        dur_b = meta_b.get("duration") or 0.0
        if dur_b and start_b + length > dur_b + 0.01 and not STATE["dry_run"]:
            die(f"cutaway {i + 1}: {path} has only {dur_b - start_b:.3f}s from {start_b:g}s, {length:g}s asked for")
        if cutaways and at < cutaways[-1]["at"] + cutaways[-1]["length"]:
            die(f"cutaway {i + 1} at {at:g}s overlaps the previous one (ends {cutaways[-1]['at'] + cutaways[-1]['length']:g}s)")
        cutaways.append({"path": path, "at": at, "length": length, "from": start_b, "has_audio": bool(meta_b.get("audio"))})
    if args.audio != "a" and not all(c["has_audio"] for c in cutaways):
        die("--audio b/mix needs audio on every B-roll clip")

    output = args.output or default_output(args.input, "broll")
    cmd = ffmpeg_base() + ["-i", args.input]
    for c in cutaways:
        cmd += ["-i", c["path"]]

    # Picture: each B window is trimmed, normalised to A's frame and fps, shifted to start at its
    # --at time, and overlaid on A; before its first frame and after its last (eof_action=pass)
    # A shows through unchanged, so A's timeline is never touched.
    parts: List[str] = []
    cur = "[0:v]"
    for i, c in enumerate(cutaways):
        geo = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}"
        parts.append(f"[{i + 1}:v]trim=start={c['from']:.3f}:duration={c['length']:.3f},setpts=PTS-STARTPTS+{c['at']:.3f}/TB,"
                     f"{geo},setsar=1,fps={fps:g},format=yuv420p[b{i}]")
        parts.append(f"{cur}[b{i}]overlay=0:0:eof_action=pass:enable='between(t,{c['at']:.3f},{c['at'] + c['length']:.3f})'[v{i}]")
        cur = f"[v{i}]"
    vout = cur

    # Audio: `a` stream-copies A's track; `b`/`mix` build A (muted inside the windows for `b`)
    # plus each B window delayed to its --at time.
    aout = None
    if has_audio_a or args.audio != "a":
        if args.audio == "a":
            aout = "0:a:0" if has_audio_a else None
        else:
            layers: List[str] = []
            if has_audio_a:
                gate = "".join(f",volume=0:enable='between(t,{c['at']:.3f},{c['at'] + c['length']:.3f})'" for c in cutaways) if args.audio == "b" else ""
                parts.append(f"[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo{gate}[a0]")
                layers.append("[a0]")
            for i, c in enumerate(cutaways):
                parts.append(f"[{i + 1}:a:0]atrim=start={c['from']:.3f}:duration={c['length']:.3f},asetpts=PTS-STARTPTS,"
                             f"aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(c['at'] * 1000)}|{int(c['at'] * 1000)}[ab{i}]")
                layers.append(f"[ab{i}]")
            parts.append(f"{''.join(layers)}amix=inputs={len(layers)}:normalize=0:dropout_transition=0,atrim=duration={dur_a:.3f}[aout]")
            aout = "[aout]"

    cmd += ["-filter_complex", ";".join(parts), "-map", vout]
    if aout:
        cmd += ["-map", aout]
    cmd += video_args(meta_a, args.crf, args.preset) + cfr_args(meta_a, None)
    if aout == "0:a:0":
        cmd += ["-c:a", "copy"]
    elif aout:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd += ["-t", f"{dur_a:.3f}", output]
    run(cmd)

    result = probe(output, role="output")
    if not STATE["dry_run"] and dur_a and abs((result.get("duration") or 0.0) - dur_a) > max(0.1, 1.5 / fps):
        die(f"output is {result.get('duration'):.3f}s but the A-roll is {dur_a:.3f}s -- a cutaway must not change the length", kind="output")
    info(f"wrote {output} ({result.get('duration', 0):.3f}s, {len(cutaways)} cutaway(s), audio={args.audio})")
    emit(output, cutaways=[{"insert": c["path"], "at": c["at"], "end": c["at"] + c["length"], "from": c["from"]} for c in cutaways], audio=args.audio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
