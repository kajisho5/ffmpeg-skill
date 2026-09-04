#!/usr/bin/env python3
"""Two-pass EBU R128 loudness normalisation (ffmpeg loudnorm).

Pass 1 measures integrated loudness, true peak, LRA and threshold; pass 2
applies loudnorm in linear mode with those measurements so the result hits
the target without the pumping of single-pass mode. Video is stream-copied.

Common targets: -14 LUFS (YouTube/Spotify), -16 (Apple Podcasts), -23 (EBU broadcast).

Examples:
  python3 loudness.py input.mp4                       # -14 LUFS, -1 dBTP
  python3 loudness.py podcast.wav -I -16 --tp -1.5 -o podcast_norm.wav
  python3 loudness.py input.mp4 --measure-only
"""
import argparse
import json
import os
import re
import sys

from _common import STATE, add_common, apply_common, emit, AUDIO_CODECS, audio_codec_for, default_output, die, ffmpeg_base, info, probe, require_tool, run



def measure(path: str, I: float, tp: float, lra: float) -> dict:
    if STATE["dry_run"]:
        return {"input_i": "-20.0", "input_tp": "-3.0", "input_lra": "8.0", "input_thresh": "-30.0", "target_offset": "0.0"}
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", f"loudnorm=I={I}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"]
    proc = run(cmd, check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if proc.returncode != 0 or not m:
        die(f"loudness measurement failed:\n{proc.stderr.strip()[-1500:]}")
    data = json.loads(m.group(0))
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if data.get(k) in (None, "-inf", "inf", "nan"):
            data["silent"] = True
            return data
    data["silent"] = False
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_loudnorm.<ext>)")
    ap.add_argument("-I", "--lufs", type=float, default=-14.0, help="integrated loudness target in LUFS (default -14)")
    ap.add_argument("--tp", type=float, default=-1.0, help="true peak ceiling in dBTP (default -1)")
    ap.add_argument("--lra", type=float, default=11.0, help="loudness range target in LU (default 11)")
    ap.add_argument("--measure-only", action="store_true", help="print the measured stats as JSON and exit")
    ap.add_argument("--audio-bitrate", default="192k", help="AAC bitrate when the container is video (default 192k)")
    ap.add_argument("--sample-rate", type=int, help="output sample rate (default: 48000; loudnorm upsamples internally to 192k)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream")

    stats = measure(args.input, args.lufs, args.tp, args.lra)
    if stats.get("silent"):
        info("audio is silent (integrated loudness -inf); nothing to normalise")
        if args.measure_only:
            print(json.dumps({"silent": True, "input_i": "-inf"}, indent=2))
            return 0
        die("input audio is silent; loudness normalisation is meaningless (use audio.py --replace to add a track)")
    info(f"measured: {float(stats['input_i']):.1f} LUFS, TP {float(stats['input_tp']):.1f} dBTP, LRA {float(stats['input_lra']):.1f} LU")
    if args.measure_only:
        print(json.dumps({k: stats[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}, indent=2))
        return 0

    output = args.output or default_output(args.input, "loudnorm")
    af = (
        f"loudnorm=I={args.lufs}:TP={args.tp}:LRA={args.lra}"
        f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true:print_format=summary"
    )
    sr = args.sample_rate or meta["audio"].get("sample_rate") or 48000
    ext = os.path.splitext(output)[1].lower()
    cmd = ffmpeg_base() + ["-i", args.input, "-af", af, "-ar", str(sr)]
    if ext in AUDIO_CODECS or not meta.get("video"):
        cmd += ["-vn"] + audio_codec_for(output, args.audio_bitrate)
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", args.audio_bitrate]
    cmd.append(output)
    run(cmd)

    after = measure(output, args.lufs, args.tp, args.lra)
    if not after.get("silent"):
        info(f"result:   {float(after['input_i']):.1f} LUFS, TP {float(after['input_tp']):.1f} dBTP (target {args.lufs} LUFS)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
