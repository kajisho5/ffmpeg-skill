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
  python3 loudness.py music.wav --lra 7                 # tighter loudness range target
"""
import argparse
import json
import os
import re
import sys

from _platforms import TP_TOLERANCE_DB

AUDIO_LENGTH_TOLERANCE = 0.03  # seconds: one AAC frame at 48 kHz is 0.021 s
LUFS_TOLERANCE = 1.0  # LU: a normalised file within this of the requested -I is on target
from _common import STATE, add_common, apply_common, emit, AUDIO_CODECS, audio_codec_for, default_output, die, ffmpeg_base, info, probe, require_tool, run, run_analysis, run_keeping_subtitles, dry_run_input_pending



# --versions' named targets: integrated loudness (LUFS) and true-peak ceiling (dBTP)
VERSION_TARGETS = {
    "streaming": (-14.0, -1.0),     # YouTube, Spotify and most streaming services
    "ebu-r128": (-23.0, -1.0),      # EBU R128 broadcast
    "broadcast-jp": (-24.0, -1.0),  # ARIB TR-B32 (Japanese broadcast, LKFS = LUFS)
}


def parse_versions(text: str) -> "list":
    """[(label, lufs, tp)] from --versions; a refusal names the item that did not parse."""
    out, seen = [], set()
    for item in (x.strip() for x in text.split(",")):
        if not item:
            continue
        if item in VERSION_TARGETS:
            label, (lufs, tp) = item, VERSION_TARGETS[item]
        else:
            try:
                lufs_s, tp_s = item.split("/")
                lufs, tp = float(lufs_s), float(tp_s)
            except ValueError:
                die(f"--versions item {item!r} is neither a named target ({', '.join(VERSION_TARGETS)}) nor LUFS/TP such as -16/-1.5")
            if not (-70 <= lufs <= -5 and -9 <= tp <= 0):
                die(f"--versions item {item!r}: LUFS must be -70..-5 and TP -9..0 (loudnorm's ranges)")
            label = f"{lufs:g}lufs{tp:g}tp".replace("-", "m").replace(".", "_")
        if label in seen:
            die(f"--versions names {label!r} twice")
        seen.add(label)
        out.append((label, lufs, tp))
    if not out:
        die("--versions is empty")
    return out


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


def _normalize(args, meta: dict, stats: dict, lufs: float, tp_max: float, output: str) -> dict:
    """One normalised file at `lufs` / `tp_max`, measured after: the keys emit() takes for it."""
    af = (
        f"loudnorm=I={lufs}:TP={tp_max}:LRA={args.lra}"
        f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true:print_format=summary"
    )
    sr = args.sample_rate or meta["audio"].get("sample_rate") or 48000
    ext = os.path.splitext(output)[1].lower()
    bitrate_pinned = args.audio_bitrate is not None
    bitrate = args.audio_bitrate or "192k"

    dropped_streams = False
    # loudnorm emits its last block whole, and through the AAC encoder that came out as 0.1 s more
    # sound than the input had (a 90.000 s Reels export left at 90.100 s, which check.py fails):
    # the sound is trimmed back to the input's own length. `duration=` counts from the first sample,
    # so sound that starts late keeps its end (`end=` is a timestamp, and cut it). atrim follows
    # loudnorm directly: an aresample between them fails channel-layout negotiation on FFmpeg 5.1
    in_audio = audio_length(meta)

    def encode(tp: float, bitrate: str) -> None:
        nonlocal dropped_streams
        af = (
            f"loudnorm=I={lufs}:TP={tp}:LRA={args.lra}"
            f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}"
            f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true:print_format=summary"
        )
        if in_audio:
            af += f",atrim=duration={float(in_audio):.6f}"
        cmd = ffmpeg_base() + ["-i", args.input, "-af", af, "-ar", str(sr)]
        if ext in AUDIO_CODECS or not meta.get("video"):
            cmd += ["-vn"] + audio_codec_for(output, bitrate)
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", bitrate]
            if ext in (".mp4", ".mov", ".m4v"):
                cmd += ["-movflags", "+faststart"]
            dropped_streams = run_keeping_subtitles(cmd, output)
            return
        cmd.append(output)
        run(cmd)

    encode(tp_max, bitrate)
    if STATE.dry_run:
        # pass 1 measured the input for real; there is no output to measure
        return {"output": output, "measured": {k: stats[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset", "silent")}}
    after = measure(output, lufs, tp_max, args.lra)
    # loudnorm holds the ceiling on the float samples it outputs; the lossy encoder then adds
    # its own overshoot. ffmpeg's native AAC at 192k turned one transient of a 12-minute film
    # from -2.4 dBFS into +3.7 dBFS, so the file measured +1.2 dBTP after "--tp -1" and
    # check.py's fix hint pointed straight back here. Two remedies, in this order: more bits
    # (256k, then 320k: the overshoot is quantisation noise and shrinks with bitrate, and the
    # loudness target is untouched) when the caller did not pin the bitrate; then a lower
    # loudnorm ceiling by the measured overshoot, which in linear mode also lowers the
    # integrated loudness -- reported, never hidden.
    ceiling, rounds = tp_max, 0
    steps = [] if bitrate_pinned or ext in AUDIO_CODECS and "aac" not in AUDIO_CODECS[ext] else [b for b in ("256k", "320k") if _kbps(b) > _kbps(bitrate)]
    while not after.get("silent") and float(after["input_tp"]) > tp_max + TP_TOLERANCE_DB and rounds < 5:
        rounds += 1
        overshoot = float(after["input_tp"]) - tp_max
        if steps:
            bitrate = steps.pop(0)
            info(f"true peak {float(after['input_tp']):.2f} dBTP exceeds the requested {tp_max:g} dBTP after encoding "
                 f"(codec overshoot); re-encoding at {bitrate}")
        else:
            ceiling -= overshoot + 0.2
            info(f"true peak {float(after['input_tp']):.2f} dBTP exceeds the requested {tp_max:g} dBTP after encoding "
                 f"(codec overshoot); re-encoding with the loudnorm ceiling at {ceiling:.2f} dBTP")
        encode(ceiling, bitrate)
        after = measure(output, lufs, tp_max, args.lra)
    if not after.get("silent"):
        info(f"result:   {float(after['input_i']):.1f} LUFS, TP {float(after['input_tp']):.1f} dBTP (target {lufs} LUFS, TP <= {tp_max:g})")
    result = {k: after[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset", "silent")}
    result["tp_ceiling_used"] = round(ceiling, 2)
    if ext not in AUDIO_CODECS or "aac" in AUDIO_CODECS[ext]:
        result["audio_bitrate_used"] = bitrate
    result["encodes"] = rounds + 1
    if not after.get("silent") and abs(float(after["input_i"]) - lufs) > LUFS_TOLERANCE:
        result["note"] = (f"integrated loudness is {float(after['input_i']) - lufs:+.1f} LU from the target because the "
                          f"true-peak ceiling had to absorb the encoder's overshoot; a lossless delivery (wav/flac) or a pinned "
                          f"higher --audio-bitrate keeps both")
    if not after.get("silent") and float(after["input_tp"]) > tp_max + TP_TOLERANCE_DB:
        die(f"true peak is still {float(after['input_tp']):.2f} dBTP after {rounds + 1} encodes (requested <= {tp_max:g}); "
            f"the encoder overshoots more than the loudnorm ceiling can absorb at this bitrate",
            kind="verification", output=output, result=result,
            hint="raise --audio-bitrate (e.g. 256k) or deliver a lossless format (wav/flac) and let the platform encode")
    verification = [{"step": "loudness",
                     "ok": bool(after.get("silent")) or (abs(float(after["input_i"]) - lufs) <= LUFS_TOLERANCE and float(after["input_tp"]) <= tp_max + TP_TOLERANCE_DB),
                     "lufs": float(after["input_i"]), "tp": float(after["input_tp"]), "target_lufs": lufs, "target_tp": tp_max,
                     "property": "loudness", "expected": {"lufs": lufs, "tp_max": tp_max},
                     "measured": {"lufs": float(after["input_i"]), "tp": float(after["input_tp"])},
                     "delta": {"lufs": round(float(after["input_i"]) - lufs, 2), "tp": round(float(after["input_tp"]) - tp_max, 2)},
                     "tolerance": {"lufs": LUFS_TOLERANCE, "tp": TP_TOLERANCE_DB}, "provenance": "user_specified"}]
    written = probe(output, role="output")
    out_audio = audio_length(written)
    if in_audio and out_audio:
        # a levels pass changes no timing: the sound is as long as the input's, to one AAC frame
        tol = max(1024.0 / float(sr), AUDIO_LENGTH_TOLERANCE)
        verification.append({"step": "duration", "property": "audio_duration", "ok": abs(out_audio - in_audio) <= tol,
                             "expected": round(float(in_audio), 3), "measured": round(float(out_audio), 3),
                             "delta": round(float(out_audio) - float(in_audio), 3), "tolerance": round(tol, 3),
                             "provenance": "input_premeasurement"})
    else:
        # a length that could not be read is not a length that matched
        verification.append({"step": "duration", "property": "audio_duration", "ok": False,
                             "reason": "not_measured: the " + ("input" if not in_audio else "output") + " reports no duration"})
    return {"output": output, "result": result, "dropped_non_av_streams": dropped_streams,
            "measured": {k: stats[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset", "silent")},
            "targets": {"lufs": lufs, "tp": tp_max, "lra": args.lra}, "verification": verification}


def _versions(args, meta: dict, plan: list) -> int:
    """--versions: one file per target from the one master, each a whole two-pass normalisation
    (pass 1 is per target: loudnorm's target_offset depends on it) measured after. `verified` is
    true only when every version met its own target."""
    versions, steps, dropped = [], [], False
    for label, lufs, tp in plan:
        out = default_output(args.input, f"loudnorm_{label}")
        stats = measure(args.input, lufs, tp, args.lra)
        if stats.get("silent"):
            die("input audio is silent; loudness normalisation is meaningless (use audio.py --replace to add a track)")
        doc = _normalize(args, meta, stats, lufs, tp, out)
        dropped = dropped or bool(doc.get("dropped_non_av_streams"))
        versions.append({"target": label, "output": out, "targets": {"lufs": lufs, "tp": tp, "lra": args.lra},
                         **({"result": doc["result"]} if "result" in doc else {})})
        steps += [dict(st, version=label) for st in doc.get("verification") or []]
    emit(None, versions=versions, outputs=[v["output"] for v in versions], dropped_non_av_streams=dropped,
         **({"verification": steps} if steps else {}))
    if not STATE.json and not STATE.plan:
        print("\n".join(v["output"] for v in versions))  # one path per line, as a single run prints its one
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_loudnorm.<ext>)")
    ap.add_argument("-I", "--lufs", type=float, default=-14.0, help="integrated loudness target in LUFS (default -14)")
    ap.add_argument("--tp", type=float, default=-1.0, help="true peak ceiling in dBTP (default -1)")
    ap.add_argument("--lra", type=float, default=11.0, help="loudness range target in LU (default 11)")
    ap.add_argument("--measure-only", action="store_true", help="print the measured stats as JSON and exit")
    ap.add_argument("--audio-bitrate", default=None, help="AAC bitrate when the container is video (default 192k; raised to 256k/320k only when the encoder overshoots the true-peak ceiling and you did not pin it)")
    ap.add_argument("--versions", metavar="LIST",
                    help="write one normalised file per target from this master, each measured after: a comma list of "
                         + ", ".join(f"{n} ({i:g} LUFS / {t:g} dBTP)" for n, (i, t) in VERSION_TARGETS.items())
                         + ", or LUFS/TP pairs such as -16/-1.5; files are <name>_loudnorm_<target>.<ext> (not with -o)")
    ap.add_argument("--sample-rate", type=int, help="output sample rate (default: 48000; loudnorm upsamples internally to 192k)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    # parsed before anything is measured, and an explicitly empty --versions ('' or ',') is refused
    # by parse_versions rather than read as "not given", which wrote one default file instead
    plan = parse_versions(args.versions) if args.versions is not None else None
    if plan is not None and args.output:
        die("--versions writes one file per target, named <name>_loudnorm_<target>.<ext>; it does not take -o")

    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream")
    if plan is not None and not args.measure_only:
        # each version measures the master against its own target (loudnorm's offset depends on
        # it): a pass against -I/--tp first would be one more full decode whose result is unused
        return _versions(args, meta, plan)

    stats = measure(args.input, args.lufs, args.tp, args.lra)
    if stats.get("silent"):
        info("audio is silent (integrated loudness -inf); nothing to normalise")
        if args.measure_only:
            if STATE.json:
                emit(None, measured={"silent": True, "input_i": "-inf"})
            else:
                print(json.dumps({"silent": True, "input_i": "-inf"}, indent=2))
            return 0
        die("input audio is silent; loudness normalisation is meaningless (use audio.py --replace to add a track)")
    info(f"measured: {float(stats['input_i']):.1f} LUFS, TP {float(stats['input_tp']):.1f} dBTP, LRA {float(stats['input_lra']):.1f} LU")
    if args.measure_only:
        measured = {k: stats[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
        if STATE.json:
            emit(None, measured=measured)  # the contract's document shape (status, commands), not a bare dict
        else:
            print(json.dumps(measured, indent=2))
        return 0

    output = args.output or default_output(args.input, "loudnorm")
    doc = _normalize(args, meta, stats, args.lufs, args.tp, output)
    emit(doc.pop("output"), **doc)
    return 0


def audio_length(meta: dict) -> "Optional[float]":
    """The sound's own length: the stream's duration, else Matroska's DURATION tag. Never the
    container's, which is the picture's when the picture runs longer (and would fail a correct
    output against an expected length the sound never had)."""
    audio = meta.get("audio") or {}
    return audio.get("duration") or audio.get("tagged_duration")


def _kbps(value: str) -> int:
    v = value.lower().rstrip("k")
    try:
        return int(float(v)) if value.lower().endswith("k") else int(float(v)) // 1000
    except ValueError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
