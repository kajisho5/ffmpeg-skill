#!/usr/bin/env python3
"""Audio post: denoise, voice clean-up, typed dynamics (compressor, limiter,
gate), background music with auto-ducking, fades and stereo/mono handling.
Video is stream-copied; an audio output extension (.wav/.flac/.mp3/.m4a/...)
drops the picture, so `audio.py talk.mp4 -o talk.wav` is an extraction.

Examples:
  python3 audio.py interview.mp4 --denoise                      # FFT noise reduction
  python3 audio.py interview.mp4 --voice                        # highpass + de-esser + compressor + denoise
  python3 audio.py interview.mp4 --voice light                  # highpass + gentle compression only (light|medium|strong)
  python3 audio.py talk.mp4 --music bed.mp3 --duck              # music under speech, auto-ducked
  python3 audio.py talk.mp4 --music bed.mp3 --music-volume -18 --music-fade-out 3   # bed fades, voice does not
  python3 audio.py clip.mp4 --fade-in 0.5 --fade-out 1 --stereo
  python3 audio.py talk.mp4 --music bed.mp3 --duck --duck-threshold -30 --duck-release 250   # ducks earlier and recovers faster
  python3 audio.py band.wav --stereo-widen 0.5 -o wide.wav      # wider stereo image (a real stereo source; mono is refused)
  python3 audio.py surround.mov --downmix                       # 5.1 -> stereo with proper centre/LFE weights
  python3 audio.py clip.mp4 --replace narration.wav             # swap the audio track entirely
  python3 audio.py interview.mp4 -o interview.wav               # extract the audio (no video in the output)
  python3 audio.py multi.mkv --audio-stream 1 --voice -o lav.m4a # pick the second audio track, clean it, write M4A
  python3 audio.py talk.wav --compress --comp-threshold -20 --comp-ratio 4 --limit --limit-ceiling -1 -o talk_dyn.wav
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from _common import STATE, add_common, dry_run_input_pending, require_tool, apply_common, audio_codec_for, db_to_linear, default_output, die, emit, ffmpeg_base, info, is_audio_output, probe, run, run_keeping_subtitles, fmt_secs

VOICE_CHAIN = "highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2"

# --voice [light|medium|strong] (1.13). "medium" is the chain --voice has always produced, so a
# bare --voice (and every existing call and MCP request) is byte-identical to before. "light"
# leaves the noise floor and the sibilance alone -- it only removes rumble and evens the level,
# which is what a good room recording needs; "strong" is for phone/laptop audio: a harder
# de-esser, a second compression stage and a soft limiter at -1 dBFS so the peaks stop there
# instead of at whatever the make-up gain produced.
VOICE_LEVELS = {
    "light": "highpass=f=80,acompressor=threshold=-18dB:ratio=2:attack=5:release=80:makeup=1",
    "medium": VOICE_CHAIN,
    "strong": VOICE_CHAIN + ",deesser=i=0.6,acompressor=threshold=-24dB:ratio=4:attack=5:release=120:makeup=3,alimiter=limit=0.891251:level=disabled",
}

# The sidechain threshold the music bed has used since 1.4 is the linear 0.05 that ffmpeg's
# sidechaincompress takes; -26.0206 dBFS is that same number in the unit the flag speaks, so the
# default command line is unchanged to the byte while the value is now sayable.
DUCK_THRESHOLD_DB = -26.0206

# Typed dynamics: every flag maps to one real option of one ffmpeg filter, validated against the
# range that filter documents (ffmpeg -h filter=acompressor / alimiter / agate). dB flags are
# converted to the linear value the filter takes, so no string reaches the graph unchecked.
DYNAMICS = {
    "acompressor": {
        "comp_threshold": ("threshold", "dB", -60.0, 0.0),        # 0.000976563..1 linear
        "comp_ratio": ("ratio", "x", 1.0, 20.0),
        "comp_attack": ("attack", "ms", 0.01, 2000.0),
        "comp_release": ("release", "ms", 0.01, 9000.0),
        "comp_makeup": ("makeup", "dB", 0.0, 36.0),               # 1..64 linear
        "comp_knee": ("knee", "dB", 1.0, 8.0),
    },
    "alimiter": {
        "limit_ceiling": ("limit", "dB", -24.0, 0.0),             # 0.0625..1 linear
        "limit_attack": ("attack", "ms", 0.1, 80.0),
        "limit_release": ("release", "ms", 1.0, 8000.0),
    },
    "agate": {
        "gate_threshold": ("threshold", "dB", -60.0, 0.0),        # 0..1 linear
        "gate_ratio": ("ratio", "x", 1.0, 9000.0),
        "gate_attack": ("attack", "ms", 0.01, 9000.0),
        "gate_release": ("release", "ms", 0.01, 9000.0),
        "gate_range": ("range", "dB", -90.0, 0.0),                # 0..1 linear: how far the gate closes
        "gate_knee": ("knee", "dB", 1.0, 8.0),
    },
}


def dynamics_filter(name: str, args: argparse.Namespace) -> str:
    """One validated `acompressor=...` / `alimiter=...` / `agate=...` filter string from typed flags."""
    opts = []
    for flag, (opt, unit, lo, hi) in DYNAMICS[name].items():
        value = getattr(args, flag)
        if value is None:
            continue
        if not (lo <= value <= hi):
            die(f"--{flag.replace('_', '-')} {value:g} is outside {lo:g}..{hi:g} {unit if unit != 'x' else ''}".rstrip()
                + f" (the range ffmpeg's {name} accepts)")
        if unit == "dB":
            # the filters take linear amplitude (agate range: -90 dB -> 0.00003 closed, 0 dB -> 1 open)
            opts.append(f"{opt}={db_to_linear(value):.6g}")
        else:
            opts.append(f"{opt}={value:g}")
    if name == "alimiter":
        opts.append("level=disabled")  # keep the level: a limiter must not normalise the whole track upwards
    return name + ("=" + ":".join(opts) if opts else "")


def preflight_beds(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Every problem with every --replace / --music / --effects file, found before anything runs:
    missing, a directory, empty, unreadable, or readable but with no audio stream (a picture-only
    clip given as a bed used to reach ffmpeg's `[1:a:0]` and fail there, as kind ffmpeg, one file
    at a time). Under --dry-run a file that does not exist yet is an earlier stage's output and is
    left to the plan, as join.py's preflight does; a real file is checked under --dry-run too."""
    problems: List[Dict[str, Any]] = []
    beds = [(f, v) for f, v in (("--replace", args.replace), ("--music", args.music),
                                ("--effects", args.effects)) if v]
    if not beds:
        return problems
    ffprobe = require_tool("ffprobe")
    for flag, path in beds:
        if dry_run_input_pending(path):
            continue
        reason = None
        if not os.path.exists(path):
            reason = "missing"
        elif os.path.isdir(path):
            reason = "a directory, not a file"
        elif os.path.getsize(path) == 0:
            reason = "empty (0 bytes)"
        else:
            proc = run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                       quiet=True, check=False)
            kinds = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
            if proc.returncode != 0 or not kinds:
                reason = "unreadable: " + ((proc.stderr or "").strip().splitlines() or ["no streams"])[-1]
            elif "audio" not in kinds:
                reason = "no audio stream"
        if reason:
            problems.append({"flag": flag, "path": path, "reason": reason})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_audio.<ext>)")
    clean = ap.add_argument_group("clean-up")
    clean.add_argument("--denoise", action="store_true", help="FFT noise reduction (afftdn, adaptive)")
    clean.add_argument("--denoise-strength", type=float, default=25.0, help="noise floor in dB to remove, 10..60 (default 25)")
    clean.add_argument("--voice", nargs="?", const="medium", choices=["light", "medium", "strong"], default=None,
                       help="speech preset (default medium when the flag is given bare): light = highpass 80 Hz + gentle compression; "
                            "medium = highpass, de-esser, denoise, gentle compression; strong = medium plus a harder de-esser, a second "
                            "compressor and a soft limiter at -1 dBFS. MCP/JSON callers may still send the 1.12 boolean true, "
                            "which is the bare flag and so means medium")
    clean.add_argument("--gain", type=float, help="gain in dB applied to the main track")
    music = ap.add_argument_group("music")
    music.add_argument("--music", help="music file to mix underneath")
    music.add_argument("--music-volume", type=float, default=-14.0, help="music level in dB relative to full scale (default -14)")
    music.add_argument("--duck", action="store_true", help="auto-duck the music when the main track has speech (sidechain compressor)")
    music.add_argument("--duck-amount", type=float, default=12.0, help="how many dB to duck (default 12)")
    music.add_argument("--duck-threshold", type=float, default=DUCK_THRESHOLD_DB,
                       help="sidechain threshold in dBFS: the main track is heard as speech above this (default -26.02, the 0.05 linear used since 1.4)")
    music.add_argument("--duck-attack", type=float, default=20.0, help="ms the bed takes to duck once speech starts (default 20)")
    music.add_argument("--duck-release", type=float, default=400.0, help="ms the bed takes to come back up after speech (default 400)")
    music.add_argument("--effects", help="a third track (sound effects/atmos) mixed in at --effects-volume; never ducked")
    music.add_argument("--effects-volume", type=float, default=-14.0, help="effects level in dB relative to full scale (default -14)")
    music.add_argument("--music-loop", action="store_true", help="loop the music if shorter than the video")
    fades = ap.add_argument_group("fades / layout")
    fades.add_argument("--fade-in", type=float, default=0.0, help="seconds")
    fades.add_argument("--fade-out", type=float, default=0.0, help="seconds; fades the whole final mix (voice included)")
    music.add_argument("--music-fade-out", type=float, default=0.0, help="seconds; fades only the music bed at the end, voice untouched")
    channels = fades.add_mutually_exclusive_group()
    channels.add_argument("--stereo", action="store_true", help="force 2-channel output (mono is duplicated to both sides)")
    channels.add_argument("--mono", action="store_true", help="force 1-channel output")
    fades.add_argument("--stereo-widen", type=float, default=None, metavar="AMOUNT",
                       help="widen the stereo image, 0..1 (0 = untouched, 1 = maximum); needs a real stereo source: a mono input is "
                            "refused (duplicating it leaves both channels identical, so there is nothing to widen) and more than two "
                            "channels are refused unless --downmix folds them to stereo first")
    fades.add_argument("--downmix", action="store_true", help="downmix 5.1/7.1 to stereo using standard weights")
    fades.add_argument("--replace", help="replace the audio with this file (trimmed/padded to the video)")
    dyn = ap.add_argument_group("dynamics (typed; each flag is one option of ffmpeg's acompressor / alimiter / agate)")
    dyn.add_argument("--compress", action="store_true", help="compressor (acompressor); order: gate -> compressor -> limiter")
    dyn.add_argument("--comp-threshold", type=float, help="dBFS above which gain is reduced, -60..0 (ffmpeg default -12.4)")
    dyn.add_argument("--comp-ratio", type=float, help="ratio 1..20 (default 2)")
    dyn.add_argument("--comp-attack", type=float, help="ms 0.01..2000 (default 20)")
    dyn.add_argument("--comp-release", type=float, help="ms 0.01..9000 (default 250)")
    dyn.add_argument("--comp-makeup", type=float, help="make-up gain dB 0..36 (default 0)")
    dyn.add_argument("--comp-knee", type=float, help="knee dB 1..8 (default 2.83)")
    dyn.add_argument("--limit", action="store_true", help="look-ahead limiter (alimiter), level left as is")
    dyn.add_argument("--limit-ceiling", type=float, help="ceiling dBFS -24..0 (default 0)")
    dyn.add_argument("--limit-attack", type=float, help="ms 0.1..80 (default 5)")
    dyn.add_argument("--limit-release", type=float, help="ms 1..8000 (default 50)")
    dyn.add_argument("--gate", action="store_true", help="noise gate (agate)")
    dyn.add_argument("--gate-threshold", type=float, help="dBFS below which the gate closes, -60..0 (default -18.1)")
    dyn.add_argument("--gate-ratio", type=float, help="ratio 1..9000 (default 2)")
    dyn.add_argument("--gate-attack", type=float, help="ms 0.01..9000 (default 20)")
    dyn.add_argument("--gate-release", type=float, help="ms 0.01..9000 (default 250)")
    dyn.add_argument("--gate-range", type=float, help="attenuation when closed, dB -90..0 (default -6.1)")
    dyn.add_argument("--gate-knee", type=float, help="knee dB 1..8 (default 2.83)")
    ap.add_argument("--audio-stream", type=int, default=0, help="which audio stream of the input to process, 0-based in file order (probe lists them under audio_streams)")
    ap.add_argument("--bitrate", default="192k")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    for flag_group, switch in (("acompressor", "compress"), ("alimiter", "limit"), ("agate", "gate")):
        if not getattr(args, switch) and any(getattr(args, f) is not None for f in DYNAMICS[flag_group]):
            die(f"--{switch} is off but one of its parameters was given; add --{switch}")

    # Same rule as the typed dynamics above, for the ducking knobs: a parameter for a switch that
    # is off does nothing, and a caller who says --duck-release 250 and gets the default 400 ms has
    # no way to notice. --duck itself needs a bed to duck.
    duck_params = [f"--duck-{name}" for name in ("threshold", "attack", "release")
                   if getattr(args, f"duck_{name}") != ap.get_default(f"duck_{name}")] + \
                  (["--duck-amount"] if args.duck_amount != ap.get_default("duck_amount") else [])
    if not args.duck and duck_params:
        die(f"--duck is off but {duck_params[0]} was given; add --duck")
    if args.duck and not args.music:
        die("--duck ducks the music bed under the main track, but no --music was given; add --music FILE")

    for flag, value, lo, hi in (("--duck-amount", args.duck_amount, 0.0, 60.0),
                                ("--duck-threshold", args.duck_threshold, -60.0, 0.0),
                                ("--duck-attack", args.duck_attack, 0.01, 2000.0),
                                ("--duck-release", args.duck_release, 0.01, 9000.0)):
        if not (lo <= value <= hi):
            die(f"{flag} {value:g} is outside {lo:g}..{hi:g} (the range ffmpeg's sidechaincompress accepts)")
    if args.stereo_widen is not None and not (0.0 <= args.stereo_widen <= 1.0):
        die(f"--stereo-widen must be 0..1 (0 = untouched, 1 = maximum), got {args.stereo_widen:g}")

    problems = preflight_beds(args)
    if problems:
        die(f"{len(problems)} of the extra audio files cannot be mixed: "
            + "; ".join(f"{p['flag']} {p['path']}: {p['reason']}" for p in problems),
            kind="input", problems=problems,
            hint="each --music / --effects / --replace file must be a readable file with an audio stream")

    meta = probe(args.input)
    dur = meta.get("duration") or 0.0
    has_video = bool(meta.get("video"))
    if not meta.get("audio") and not args.replace:
        die("input has no audio stream (use --replace to add one)")
    output = args.output or default_output(args.input, "audio")
    audio_out = is_audio_output(output)
    streams = meta.get("audio_streams") or []
    if streams and not (0 <= args.audio_stream < len(streams)) and not STATE.dry_run:
        die(f"--audio-stream {args.audio_stream}: input has {len(streams)} audio stream(s), 0..{len(streams) - 1}")
    if args.audio_stream and not streams and not STATE.dry_run:
        die("--audio-stream needs an input with audio streams")
    in_channels = (meta.get("audio") or {}).get("channels") or 0
    if args.stereo_widen is not None:
        if args.mono:
            die("--stereo-widen and --mono contradict each other: there is no stereo image in a 1-channel output")
        # Widening scales the side signal (L-R). Duplicating a mono track to two channels leaves
        # L == R, so the side signal is exactly zero and scaling it changes nothing: --stereo is
        # not a way in, it is a way to a file that measures mono no matter the amount asked for.
        if in_channels == 1:
            die("--stereo-widen needs a real stereo source: mono has no stereo image to widen; keep it mono or "
                "use --stereo to duplicate it, but widening needs a real stereo source")
        if in_channels > 2 and not args.downmix:
            die(f"--stereo-widen needs a stereo track; this input has {in_channels} channels. Add --downmix to fold it "
                "to stereo first (the widening then happens after the downmix), or leave the channels alone.")

    inputs: List[str] = ["-i", args.input]
    main_src = f"0:a:{args.audio_stream}"
    idx = 1
    if args.replace:
        inputs += ["-i", args.replace]
        main_src = f"{idx}:a:0"
        idx += 1

    fx: List[str] = []
    if args.downmix:
        fx.append("pan=stereo|FL=0.707*FC+FL+0.5*BL+0.5*SL+0.5*LFE|FR=0.707*FC+FR+0.5*BR+0.5*SR+0.5*LFE")
    if args.voice:
        fx.append(VOICE_LEVELS[args.voice])
    elif args.denoise:
        if not 10 <= args.denoise_strength <= 60:
            die(f"--denoise-strength must be 10..60 (dB of noise floor to remove), got {args.denoise_strength:g}")
        fx.append(f"afftdn=nf=-{args.denoise_strength:g}:tn=1")
    if args.gain:
        fx.append(f"volume={args.gain:g}dB")
    if args.gate:
        fx.append(dynamics_filter("agate", args))
    if args.compress:
        fx.append(dynamics_filter("acompressor", args))
    if args.limit:
        fx.append(dynamics_filter("alimiter", args))
    if args.mono:
        in_ch = (meta.get("audio") or {}).get("channels") or 2
        if in_ch == 2:
            fx.append("pan=mono|c0=0.5*c0+0.5*c1")
        elif in_ch > 2:
            fx.append("aformat=channel_layouts=mono")  # swresample's standard downmix (centre/LFE weighted)
        # 1 channel: already mono; the stereo pan used to halve it (-6 dB) because c1 was silence
    elif args.stereo:
        fx.append("aformat=channel_layouts=stereo")
    if args.stereo_widen is not None:
        # extrastereo widens by scaling the side (L-R) signal: m=1 is the input, m=3 is as wide
        # as it goes before the centre collapses. It runs after the channel layout is settled, so
        # a --downmix 5.1 source is widened on the stereo fold-down rather than on six channels.
        fx.append(f"extrastereo=m={1 + 2 * args.stereo_widen:g}")

    graph: List[str] = []
    graph.append(f"[{main_src}]{','.join(fx) if fx else 'anull'}[main]")
    last = "main"

    if args.music:
        if args.music_loop:
            inputs += ["-stream_loop", "-1", "-i", args.music]
        else:
            inputs += ["-i", args.music]
        m = f"{idx}:a:0"
        idx += 1
        mfx = [f"volume={args.music_volume:g}dB", f"atrim=0:{dur:.3f}" if dur else "anull"]
        if args.music_fade_out and dur:
            mfx.append(f"afade=t=out:st={max(0.0, dur - args.music_fade_out):.3f}:d={args.music_fade_out:g}")
        graph.append(f"[{m}]{','.join(mfx)}[music]")
        if args.duck:
            graph.append("[main]asplit=2[mainA][sc]")
            graph.append(
                f"[music][sc]sidechaincompress=threshold={db_to_linear(args.duck_threshold):.6g}"
                f":ratio={max(2.0, args.duck_amount / 3):.1f}:attack={args.duck_attack:g}:release={args.duck_release:g}:makeup=1[ducked]"
            )
            graph.append("[mainA][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        else:
            graph.append("[main][music]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        last = "mix"

    if args.effects:
        # A third bed, mixed in at its own level and deliberately never ducked: effects are cut
        # to the picture, so dipping them under speech would move them off their own frames.
        inputs += ["-i", args.effects]
        e = f"{idx}:a:0"
        idx += 1
        efx = [f"volume={args.effects_volume:g}dB", f"atrim=0:{dur:.3f}" if dur else "anull"]
        graph.append(f"[{e}]{','.join(efx)}[effects]")
        graph.append(f"[{last}][effects]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixfx]")
        last = "mixfx"

    post: List[str] = []
    if args.fade_in:
        post.append(f"afade=t=in:st=0:d={args.fade_in:g}")
    if args.fade_out and dur:
        post.append(f"afade=t=out:st={max(0.0, dur - args.fade_out):.3f}:d={args.fade_out:g}")
    # The audio track is conformed to the source duration whenever it is known: padded with
    # silence if the graph came out short, trimmed if long. A mixed track can come out a few
    # hundredths short (amix's dropout_transition, a looped bed's atrim boundary), and with
    # -shortest below that used to shorten the *video* to match: 12.00 s in, 11.925 s out, four
    # frames of a stream-copied picture gone (#164). Padding the audio, not cutting the picture,
    # is the only correct answer for a tool whose contract says the video is never touched.
    keep_video = has_video and not audio_out
    if dur and (args.replace or args.music or keep_video):
        post.append(f"apad,atrim=0:{dur:.3f}")
    if post:
        graph.append(f"[{last}]{','.join(post)}[out]")
        last = "out"

    cmd = ffmpeg_base() + inputs + ["-filter_complex", ";".join(graph), "-map", f"[{last}]"]
    if keep_video:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if Path(output).suffix.lower() in (".mp4", ".mov", ".m4v"):
            cmd += ["-movflags", "+faststart"]
    elif has_video:
        cmd += ["-vn"]  # audio extension: the picture is dropped, not copied into a container that cannot hold it
    cmd += audio_codec_for(output, args.bitrate)
    if not keep_video:
        # audio-only outputs: a looped music bed is infinite, -shortest ends the run with the main track
        cmd.append("-shortest")
    if keep_video:
        dropped_streams = run_keeping_subtitles(cmd, output)
    else:
        dropped_streams = bool(has_video and (meta.get("subtitle_streams") or meta.get("data_streams")))
        run(cmd + [output])
    r = probe(output, role="output")
    a = r["audio"]
    if r.get("video") and audio_out and not STATE.dry_run:
        die(f"{output} unexpectedly contains a video stream")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, audio {a['codec']} {a['channels']}ch {a['sample_rate']}Hz"
         + (", video stream-copied" if has_video and not audio_out else ", video dropped" if has_video else "") + ")")
    audio_block: Dict[str, Any] = {"voice": args.voice, "stereo_widen": args.stereo_widen,
                                   "effects": bool(args.effects), "effects_volume": args.effects_volume if args.effects else None}
    if args.music:
        audio_block["music_volume"] = args.music_volume
        audio_block["duck"] = ({"amount_db": args.duck_amount, "threshold_db": round(args.duck_threshold, 4),
                                "threshold_linear": float(f"{db_to_linear(args.duck_threshold):.6g}"),
                                "ratio": round(max(2.0, args.duck_amount / 3), 1),
                                "attack_ms": args.duck_attack, "release_ms": args.duck_release}
                               if args.duck else None)
    emit(output, audio=audio_block, video=bool(has_video and not audio_out), audio_stream=args.audio_stream,
         dynamics=[f for f in (args.gate and "agate", args.compress and "acompressor", args.limit and "alimiter") if f],
         dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
