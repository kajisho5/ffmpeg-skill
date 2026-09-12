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

from _common import STATE, add_common, apply_common, emit, AUDIO_CODECS, audio_codec_for, default_output, die, ffmpeg_base, info, probe, require_tool, run, run_analysis, dry_run_input_pending



def measure(path: str, I: float, tp: float, lra: float) -> dict:
    if dry_run_input_pending(path):
        return {"input_i": "-20.0", "input_tp": "-3.0", "input_lra": "8.0", "input_thresh": "-30.0", "target_offset": "0.0", "silent": False, "placeholder": True}
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", f"loudnorm=I={I}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"]
    # Pass 1 is a measurement: it runs under --dry-run too, so the planned pass-2 command and
    # the reported input_i are real (before 1.4.6 a dry run returned a made-up -20 LUFS).
    proc = run_analysis(cmd, check=False, record=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if proc.returncode != 0 or not m:
        die(f"loudness measurement failed:\n{proc.stderr.strip()[-1500:]}", kind="ffmpeg")
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
    ap.add_argument("--audio-bitrate", default=None, help="AAC bitrate when the container is video (default 192k; raised to 256k/320k only when the encoder overshoots the true-peak ceiling and you did not pin it)")
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
    bitrate_pinned = args.audio_bitrate is not None
    bitrate = args.audio_bitrate or "192k"

    def encode(tp: float, bitrate: str) -> None:
        af = (
            f"loudnorm=I={args.lufs}:TP={tp}:LRA={args.lra}"
            f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
            f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true:print_format=summary"
        )
        cmd = ffmpeg_base() + ["-i", args.input, "-af", af, "-ar", str(sr)]
        if ext in AUDIO_CODECS or not meta.get("video"):
            cmd += ["-vn"] + audio_codec_for(output, bitrate)
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", bitrate]
        cmd.append(output)
        run(cmd)

    encode(args.tp, bitrate)
    if STATE.dry_run:
        # pass 1 measured the input for real; there is no output to measure
        emit(output, measured={k: stats[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset", "silent")})
        return 0
    after = measure(output, args.lufs, args.tp, args.lra)
    # loudnorm holds the ceiling on the float samples it outputs; the lossy encoder then adds
    # its own overshoot. ffmpeg's native AAC at 192k turned one transient of a 12-minute film
    # from -2.4 dBFS into +3.7 dBFS, so the file measured +1.2 dBTP after "--tp -1" and
    # check.py's fix hint pointed straight back here. Two remedies, in this order: more bits
    # (256k, then 320k: the overshoot is quantisation noise and shrinks with bitrate, and the
    # loudness target is untouched) when the caller did not pin the bitrate; then a lower
    # loudnorm ceiling by the measured overshoot, which in linear mode also lowers the
    # integrated loudness -- reported, never hidden.
    ceiling, rounds = args.tp, 0
    steps = [] if bitrate_pinned or ext in AUDIO_CODECS and "aac" not in AUDIO_CODECS[ext] else [b for b in ("256k", "320k") if _kbps(b) > _kbps(bitrate)]
    while not after.get("silent") and float(after["input_tp"]) > args.tp + 0.1 and rounds < 5:
        rounds += 1
        overshoot = float(after["input_tp"]) - args.tp
        if steps:
            bitrate = steps.pop(0)
            info(f"true peak {float(after['input_tp']):.2f} dBTP exceeds the requested {args.tp:g} dBTP after encoding "
                 f"(codec overshoot); re-encoding at {bitrate}")
        else:
            ceiling -= overshoot + 0.2
            info(f"true peak {float(after['input_tp']):.2f} dBTP exceeds the requested {args.tp:g} dBTP after encoding "
                 f"(codec overshoot); re-encoding with the loudnorm ceiling at {ceiling:.2f} dBTP")
        encode(ceiling, bitrate)
        after = measure(output, args.lufs, args.tp, args.lra)
    if not after.get("silent"):
        info(f"result:   {float(after['input_i']):.1f} LUFS, TP {float(after['input_tp']):.1f} dBTP (target {args.lufs} LUFS, TP <= {args.tp:g})")
    result = {k: after[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset", "silent")}
    result["tp_ceiling_used"] = round(ceiling, 2)
    if ext not in AUDIO_CODECS or "aac" in AUDIO_CODECS[ext]:
        result["audio_bitrate_used"] = bitrate
    result["encodes"] = rounds + 1
    if not after.get("silent") and abs(float(after["input_i"]) - args.lufs) > 1.0:
        result["note"] = (f"integrated loudness is {float(after['input_i']) - args.lufs:+.1f} LU from the target because the "
                          f"true-peak ceiling had to absorb the encoder's overshoot; a lossless delivery (wav/flac) or a pinned "
                          f"higher --audio-bitrate keeps both")
    if not after.get("silent") and float(after["input_tp"]) > args.tp + 0.1:
        die(f"true peak is still {float(after['input_tp']):.2f} dBTP after {rounds + 1} encodes (requested <= {args.tp:g}); "
            f"the encoder overshoots more than the loudnorm ceiling can absorb at this bitrate",
            kind="verification", output=output, result=result,
            hint="raise --audio-bitrate (e.g. 256k) or deliver a lossless format (wav/flac) and let the platform encode")
    emit(output, result=result)
    return 0


def _kbps(value: str) -> int:
    v = value.lower().rstrip("k")
    try:
        return int(float(v)) if value.lower().endswith("k") else int(float(v)) // 1000
    except ValueError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
