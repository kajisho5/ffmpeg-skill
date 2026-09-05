#!/usr/bin/env python3
"""Audio post: denoise, voice clean-up, typed dynamics (compressor, limiter,
gate), background music with auto-ducking, fades and stereo/mono handling.
Video is stream-copied; an audio output extension (.wav/.flac/.mp3/.m4a/...)
drops the picture, so `audio.py talk.mp4 -o talk.wav` is an extraction.

Examples:
  python3 audio.py interview.mp4 --denoise                      # FFT noise reduction
  python3 audio.py interview.mp4 --voice                        # highpass + de-esser + compressor + denoise
  python3 audio.py talk.mp4 --music bed.mp3 --duck              # music under speech, auto-ducked
  python3 audio.py talk.mp4 --music bed.mp3 --music-volume -18 --music-fade-out 3   # bed fades, voice does not
  python3 audio.py clip.mp4 --fade-in 0.5 --fade-out 1 --stereo
  python3 audio.py surround.mov --downmix                       # 5.1 -> stereo with proper centre/LFE weights
  python3 audio.py clip.mp4 --replace narration.wav             # swap the audio track entirely
  python3 audio.py interview.mp4 -o interview.wav               # extract the audio (no video in the output)
  python3 audio.py multi.mkv --audio-stream 1 --voice -o lav.m4a # pick the second audio track, clean it, write M4A
  python3 audio.py talk.wav --compress --comp-threshold -20 --comp-ratio 4 --limit --limit-ceiling -1 -o talk_dyn.wav
"""
import argparse
import sys
from typing import List

from _common import STATE, add_common, apply_common, audio_codec_for, db_to_linear, default_output, die, emit, ffmpeg_base, info, is_audio_output, probe, run

VOICE_CHAIN = "highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2"

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_audio.<ext>)")
    clean = ap.add_argument_group("clean-up")
    clean.add_argument("--denoise", action="store_true", help="FFT noise reduction (afftdn, adaptive)")
    clean.add_argument("--denoise-strength", type=float, default=25.0, help="noise floor in dB to remove, 10..60 (default 25)")
    clean.add_argument("--voice", action="store_true", help="speech preset: highpass 80 Hz, de-esser, denoise, gentle compression")
    clean.add_argument("--gain", type=float, help="gain in dB applied to the main track")
    music = ap.add_argument_group("music")
    music.add_argument("--music", help="music file to mix underneath")
    music.add_argument("--music-volume", type=float, default=-14.0, help="music level in dB relative to full scale (default -14)")
    music.add_argument("--duck", action="store_true", help="auto-duck the music when the main track has speech (sidechain compressor)")
    music.add_argument("--duck-amount", type=float, default=12.0, help="how many dB to duck (default 12)")
    music.add_argument("--music-loop", action="store_true", help="loop the music if shorter than the video")
    fades = ap.add_argument_group("fades / layout")
    fades.add_argument("--fade-in", type=float, default=0.0, help="seconds")
    fades.add_argument("--fade-out", type=float, default=0.0, help="seconds; fades the whole final mix (voice included)")
    music.add_argument("--music-fade-out", type=float, default=0.0, help="seconds; fades only the music bed at the end, voice untouched")
    fades.add_argument("--stereo", action="store_true", help="force 2-channel output (mono is duplicated to both sides)")
    fades.add_argument("--mono", action="store_true", help="force 1-channel output")
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

    meta = probe(args.input)
    dur = meta.get("duration") or 0.0
    has_video = bool(meta.get("video"))
    if not meta.get("audio") and not args.replace:
        die("input has no audio stream (use --replace to add one)")
    output = args.output or default_output(args.input, "audio")
    audio_out = is_audio_output(output)
    streams = meta.get("audio_streams") or []
    if streams and not (0 <= args.audio_stream < len(streams)) and not STATE["dry_run"]:
        die(f"--audio-stream {args.audio_stream}: input has {len(streams)} audio stream(s), 0..{len(streams) - 1}")
    if args.audio_stream and not streams and not STATE["dry_run"]:
        die("--audio-stream needs an input with audio streams")

    inputs: List[str] = ["-i", args.input]
    main_src = f"0:a:{args.audio_stream}"
    idx = 1
    if args.replace:
        probe(args.replace)
        inputs += ["-i", args.replace]
        main_src = f"{idx}:a:0"
        idx += 1

    fx: List[str] = []
    if args.downmix:
        fx.append("pan=stereo|FL=0.707*FC+FL+0.5*BL+0.5*SL+0.5*LFE|FR=0.707*FC+FR+0.5*BR+0.5*SR+0.5*LFE")
    if args.voice:
        fx.append(VOICE_CHAIN)
    elif args.denoise:
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
        fx.append("pan=mono|c0=0.5*c0+0.5*c1")
    elif args.stereo:
        fx.append("aformat=channel_layouts=stereo")

    graph: List[str] = []
    graph.append(f"[{main_src}]{','.join(fx) if fx else 'anull'}[main]")
    last = "main"

    if args.music:
        probe(args.music)
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
                f"[music][sc]sidechaincompress=threshold=0.05:ratio={max(2.0, args.duck_amount / 3):.1f}:attack=20:release=400:makeup=1[ducked]"
            )
            graph.append("[mainA][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        else:
            graph.append("[main][music]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        last = "mix"

    post: List[str] = []
    if args.fade_in:
        post.append(f"afade=t=in:st=0:d={args.fade_in:g}")
    if args.fade_out and dur:
        post.append(f"afade=t=out:st={max(0.0, dur - args.fade_out):.3f}:d={args.fade_out:g}")
    if args.replace and dur:
        post.append(f"apad,atrim=0:{dur:.3f}")
    if post:
        graph.append(f"[{last}]{','.join(post)}[out]")
        last = "out"

    cmd = ffmpeg_base() + inputs + ["-filter_complex", ";".join(graph), "-map", f"[{last}]"]
    if has_video and not audio_out:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
    elif has_video:
        cmd += ["-vn"]  # audio extension: the picture is dropped, not copied into a container that cannot hold it
    cmd += audio_codec_for(output, args.bitrate) + ["-shortest", output]
    run(cmd)
    r = probe(output)
    a = r["audio"]
    if r.get("video") and audio_out and not STATE["dry_run"]:
        die(f"{output} unexpectedly contains a video stream")
    info(f"wrote {output} ({r['duration']:.3f}s, audio {a['codec']} {a['channels']}ch {a['sample_rate']}Hz"
         + (", video stream-copied" if has_video and not audio_out else ", video dropped" if has_video else "") + ")")
    emit(output, video=bool(has_video and not audio_out), audio_stream=args.audio_stream,
         dynamics=[f for f in (args.gate and "agate", args.compress and "acompressor", args.limit and "alimiter") if f])
    return 0


if __name__ == "__main__":
    sys.exit(main())
