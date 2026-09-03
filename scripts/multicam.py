#!/usr/bin/env python3
"""Multicam: align two or more cameras (and an optional external recorder) by
audio, then cut between them from a simple switch list.

All sources are aligned to the FIRST input (the reference) using the same
cross-correlation as sync.py. The output takes video from whichever camera the
switch list names for each time range (reference timeline), and audio from the
reference unless --audio picks another source.

Switch list format: "START-END:CAM,START-END:CAM,..." with times on the
reference timeline (seconds or mm:ss) and CAM = input index (0 = reference).
Gaps fall back to camera 0.

Examples:
  python3 multicam.py camA.mp4 camB.mp4 --offsets-only                    # just report the offsets
  python3 multicam.py camA.mp4 camB.mp4 --switch "0-12:0,12-30:1,30-45:0" -o edit.mp4
  python3 multicam.py camA.mp4 camB.mp4 recorder.wav --audio 2 --switch "0-20:0,20-40:1" --fix-drift
  python3 multicam.py camA.mp4 camB.mp4 --auto 8 -o edit.mp4              # alternate cameras every 8 s
"""
import argparse
import sys
from typing import List, Tuple

from _common import video_args, aac_args, add_common, apply_common, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, x264_args
from sync import measure_offset


def parse_switch(spec: str, n: int) -> List[Tuple[float, float, int]]:
    out = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rng, cam = raw.rsplit(":", 1)
            a, b = rng.rsplit("-", 1)
            s, e, c = parse_time(a), parse_time(b), int(cam)
        except ValueError:
            die(f"bad switch entry '{raw}' (want START-END:CAM)")
        if not 0 <= c < n:
            die(f"camera {c} does not exist (inputs are 0..{n - 1})")
        if e <= s:
            die(f"switch entry '{raw}': end must be after start")
        out.append((s, e, c))
    out.sort()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="reference camera first, then other cameras / recorders")
    ap.add_argument("-o", "--output", help="output file (default: <reference>_multicam.mp4)")
    ap.add_argument("--switch", help="switch list START-END:CAM,... on the reference timeline")
    ap.add_argument("--auto", type=float, help="no switch list: alternate through the cameras every N seconds")
    ap.add_argument("--audio", type=int, default=0, help="input index to take audio from (default 0 = reference)")
    ap.add_argument("--offsets-only", action="store_true", help="print the measured offsets and exit")
    ap.add_argument("--max-offset", type=float, default=30.0)
    ap.add_argument("--analyze-seconds", type=float, default=120.0)
    ap.add_argument("--fix-drift", action="store_true", help="also correct clock drift of each source (long recordings)")
    ap.add_argument("--width", type=int, help="output width (default: reference)")
    ap.add_argument("--height", type=int, help="output height (default: reference)")
    ap.add_argument("--fps", type=float, help="output fps (default: reference)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    n = len(args.inputs)
    if n < 2:
        die("give at least two inputs")
    metas = [probe(p) for p in args.inputs]
    for p, m in zip(args.inputs, metas):
        if not m.get("audio"):
            die(f"{p} has no audio to align with")
    if not metas[0].get("video"):
        die("the reference (first input) must have video")

    offsets = [0.0]
    ratios = [1.0]
    conf = [1.0]
    for p in args.inputs[1:]:
        off, score = measure_offset(args.inputs[0], p, 0.0, args.analyze_seconds, 20.0, args.max_offset, 1.0)
        ratio = 1.0
        if args.fix_drift:
            ref_dur = metas[0]["duration"] or 0.0
            sec_dur = probe(p)["duration"] or 0.0
            overlap_end = min(ref_dur, sec_dur + off)
            window = 60.0
            head_len = min(args.analyze_seconds, overlap_end)
            tail_start = overlap_end - window
            if tail_start > head_len / 2 + 5:
                ref_start, sec_start = tail_start, tail_start - off
                if sec_start < 0:
                    ref_start -= sec_start
                    sec_start = 0.0
                from sync import decode_mono, envelope, cross_correlate, refine, SR
                ref_s = decode_mono(args.inputs[0], window, ref_start)
                oth_s = decode_mono(p, window, sec_start)
                step = int(SR * 0.02)
                lag, sc = cross_correlate(envelope(ref_s, step), envelope(oth_s, step), int(2.0 * SR / step))
                residual = refine(ref_s, oth_s, lag * step / SR, int(SR * 0.001), 0.04)
                elapsed = (ref_start + window / 2) - head_len / 2
                if elapsed > 0 and sc > 0.1:
                    ratio = 1.0 - residual / elapsed
                    off = off + (ratio - 1.0) * (head_len / 2)
        offsets.append(off)
        ratios.append(ratio)
        conf.append(score)
        info(f"{p}: offset {off:+.3f}s (confidence {score:.2f})" + (f", drift {(ratio - 1) * 1e6:+.0f} ppm" if args.fix_drift else ""))

    report = {"inputs": args.inputs, "offsets_seconds": [round(o, 4) for o in offsets],
              "confidence": [round(c, 3) for c in conf]}
    if args.fix_drift:
        report["drift_ppm"] = [round((r - 1) * 1e6, 1) for r in ratios]
    if args.offsets_only:
        emit(None, **report)
        if not args.json:
            for p, o, c in zip(args.inputs, offsets, conf):
                print(f"{p}: {o:+.3f}s (confidence {c:.2f})")
        return 0

    ref_dur = metas[0]["duration"] or 0.0
    if args.switch:
        cuts = parse_switch(args.switch, n)
    elif args.auto:
        cams = [i for i, m in enumerate(metas) if m.get("video")]
        cuts, t, k = [], 0.0, 0
        while t < ref_dur:
            cuts.append((t, min(ref_dur, t + args.auto), cams[k % len(cams)]))
            t += args.auto
            k += 1
    else:
        die("give --switch or --auto (or --offsets-only)")
    # fill gaps with camera 0 and clip to the reference length
    filled: List[Tuple[float, float, int]] = []
    cursor = 0.0
    for s, e, c in cuts:
        s, e = max(0.0, s), min(ref_dur, e)
        if s > cursor:
            filled.append((cursor, s, 0))
        if e > s:
            filled.append((s, e, c))
        cursor = max(cursor, e)
    if cursor < ref_dur:
        filled.append((cursor, ref_dur, 0))
    for s, e, c in filled:
        if not metas[c].get("video"):
            die(f"camera {c} ({args.inputs[c]}) has no video; it can only be used with --audio")

    v0 = metas[0]["video"]
    w, h = args.width or v0["width"], args.height or v0["height"]
    if v0.get("rotation") in (90, -90, 270, -270) and not (args.width or args.height):
        w, h = h, w
    fps = args.fps or v0.get("fps") or 30.0
    fps = round(fps) if abs(fps - round(fps)) < 0.02 else fps
    pixfmt = "yuv420p10le" if v0.get("hdr") else "yuv420p"
    geo = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},format={pixfmt}"

    cmd = ffmpeg_base()
    for p in args.inputs:
        cmd += ["-i", p]
    parts: List[str] = []
    labels: List[str] = []
    for i, (s, e, c) in enumerate(filled):
        # reference time t maps to source time (t - offset_c) * ratio_c
        src_s = (s - offsets[c]) * ratios[c]
        src_e = (e - offsets[c]) * ratios[c]
        if src_s < 0:
            info(f"warning: camera {c} has not started at reference {s:.2f}s; using camera 0 for that range")
            c, src_s, src_e = 0, s, e
        parts.append(f"[{c}:v]trim=start={src_s:.4f}:end={src_e:.4f},setpts=PTS-STARTPTS,{geo}[v{i}]")
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(filled)}:v=1:a=0[vout]")
    a = args.audio
    a_start = -offsets[a] if offsets[a] < 0 else 0.0
    afx = []
    if abs(ratios[a] - 1.0) > 1e-7:
        sr = metas[a]["audio"].get("sample_rate") or 48000
        afx += [f"asetrate={sr * ratios[a]:.6f}", f"aresample={sr}"]
    if offsets[a] > 0:
        afx.append(f"adelay={int(round(offsets[a] * 1000))}:all=1")
    afx += [f"atrim=start={a_start:.4f}", "asetpts=PTS-STARTPTS", f"atrim=0:{ref_dur:.3f}", "aformat=sample_rates=48000:channel_layouts=stereo"]
    parts.append(f"[{a}:a]{','.join(afx)}[aout]")

    output = args.output or default_output(args.inputs[0], "multicam", "mp4")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]"]
    cmd += video_args(metas[0], args.crf, args.preset) + aac_args() + ["-shortest", output]
    run(cmd)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, {len(filled)} cuts, audio from input {a})")
    emit(output, cuts=[[round(s, 3), round(e, 3), c] for s, e, c in filled], **report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
