#!/usr/bin/env python3
"""Audio post: denoise, voice clean-up, background music with auto-ducking,
fades and stereo/mono handling. Video is stream-copied.

Examples:
  python3 audio.py interview.mp4 --denoise                      # FFT noise reduction
  python3 audio.py interview.mp4 --voice                        # highpass + de-esser + compressor + denoise
  python3 audio.py talk.mp4 --music bed.mp3 --duck              # music under speech, auto-ducked
  python3 audio.py talk.mp4 --music bed.mp3 --music-volume -18 --music-fade-out 3   # bed fades, voice does not
  python3 audio.py clip.mp4 --fade-in 0.5 --fade-out 1 --stereo
  python3 audio.py surround.mov --downmix                       # 5.1 -> stereo with proper centre/LFE weights
  python3 audio.py clip.mp4 --replace narration.wav             # swap the audio track entirely
"""
import argparse
import sys
from typing import List

from _common import add_common, apply_common, emit, audio_codec_for, default_output, die, ffmpeg_base, info, probe, run

VOICE_CHAIN = "highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2"


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
    ap.add_argument("--bitrate", default="192k")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    dur = meta.get("duration") or 0.0
    has_video = bool(meta.get("video"))
    if not meta.get("audio") and not args.replace:
        die("input has no audio stream (use --replace to add one)")
    output = args.output or default_output(args.input, "audio")

    inputs: List[str] = ["-i", args.input]
    main_src = "0:a:0"
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
    if has_video:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
    cmd += audio_codec_for(output, args.bitrate) + ["-shortest", output]
    run(cmd)
    r = probe(output)
    a = r["audio"]
    info(f"wrote {output} ({r['duration']:.3f}s, audio {a['codec']} {a['channels']}ch {a['sample_rate']}Hz)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
