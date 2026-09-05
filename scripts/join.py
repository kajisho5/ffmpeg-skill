#!/usr/bin/env python3
"""Join clips with transitions, normalising resolution, frame rate and audio
layout so mismatched sources (phone + camera + screen recording) cut together.

Transitions (xfade): fade, dissolve, wipeleft, wiperight, wipeup, wipedown,
slideleft, slideright, circleopen, fadeblack, fadewhite, smoothleft, none.

Audio-only inputs (WAV, FLAC, MP3, M4A, ...) are joined as audio: every clip is
resampled to one rate and channel layout (the first clip's rate, the widest
layout; --sample-rate / --channels override), crossfaded with acrossfade or
butted with concat, and written in the codec the output extension names. The
output of an audio join must be an audio extension; mixing audio and video
inputs is refused.

Examples:
  python3 join.py a.mp4 b.mp4 c.mp4 -o final.mp4                      # 0.5 s crossfade, size/fps from the first clip
  python3 join.py *.mp4 --transition fadeblack --duration 1 -o reel.mp4
  python3 join.py a.mov b.mp4 --transition none --width 1920 --height 1080 --fps 30
  python3 join.py intro.wav talk.m4a outro.wav -o episode.flac            # audio join, 0.5 s crossfade
  python3 join.py part1.wav part2.wav --transition none -o full.wav       # butt join, sample rate of part1
"""
import argparse
import sys
from typing import List

from _common import STATE, video_args, aac_args, add_common, apply_common, audio_codec_for, default_output, die, emit, ffmpeg_base, info, is_audio_output, probe, run

TRANSITIONS = ["fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
               "circleopen", "circleclose", "fadeblack", "fadewhite", "smoothleft", "smoothright", "radial", "none"]
LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


def join_audio(args: argparse.Namespace, metas: List[dict]) -> int:
    """Concatenate audio-only inputs: one sample rate, one channel layout, acrossfade or concat."""
    n = len(args.inputs)
    durs = [m.get("duration") or 0.0 for m in metas]
    d = args.duration if args.transition != "none" else 0.0
    for p, dur in zip(args.inputs, durs):
        if d and dur <= d * 2 and not STATE["dry_run"]:
            die(f"{p} is only {dur:.2f}s, too short for a {d:.2f}s crossfade; shorten --duration")
    rates = [m["audio"].get("sample_rate") or 48000 for m in metas]
    chans = [m["audio"].get("channels") or 2 for m in metas]
    rate = args.sample_rate or rates[0]
    channels = args.channels or max(chans)
    layout = LAYOUTS.get(channels)
    if layout is None:
        die(f"{channels}-channel output has no standard layout here (1, 2, 6 or 8); pass --channels")
    if len(set(rates)) > 1:
        info(f"sample rates differ ({', '.join(str(r) for r in rates)} Hz); resampling every clip to {rate} Hz")
    if len(set(chans)) > 1:
        info(f"channel counts differ ({', '.join(str(c) for c in chans)}); every clip becomes {layout}")
    output = args.output or default_output(args.inputs[0], "joined")
    if not is_audio_output(output):
        die(f"audio-only inputs cannot fill a video container: give -o an audio extension (.wav, .flac, .mp3, .m4a, .ogg, .opus), not {output}")

    cmd = ffmpeg_base()
    for p in args.inputs:
        cmd += ["-i", p]
    parts = [f"[{i}:a:0]aformat=sample_rates={rate}:channel_layouts={layout},asetpts=PTS-STARTPTS[a{i}]" for i in range(n)]
    if args.transition == "none":
        parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]")
    else:
        prev = "a0"
        for i in range(1, n):
            out = f"ax{i}" if i < n - 1 else "aout"
            parts.append(f"[{prev}][a{i}]acrossfade=d={d:g}:c1=tri:c2=tri[{out}]")
            prev = out
    cmd += ["-filter_complex", ";".join(parts), "-map", "[aout]", "-vn"] + audio_codec_for(output) + [output]
    run(cmd)
    expected = sum(durs) - d * (n - 1)
    r = probe(output)
    a = r.get("audio") or {}
    if not STATE["dry_run"]:
        if r.get("video"):
            die(f"{output} unexpectedly contains a video stream")
        if a.get("sample_rate") != rate or a.get("channels") != channels:
            die(f"{output} is {a.get('sample_rate')} Hz {a.get('channels')} ch, expected {rate} Hz {channels} ch")
    info(f"wrote {output} ({r['duration']:.3f}s, expected ~{expected:.3f}s, audio {a.get('codec')} {channels}ch {rate}Hz, {n} clips, "
         + ("crossfade" if d else "butt join") + ")")
    emit(output, mode="audio", clips=n, transition=args.transition if d else "none", expected_duration=round(expected, 3),
         sample_rate=rate, channels=channels, video=False)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="two or more clips in order")
    ap.add_argument("-o", "--output", help="output file (default: <first>_joined.mp4)")
    ap.add_argument("--transition", choices=TRANSITIONS, default="fade", help="transition between clips (default fade)")
    ap.add_argument("--duration", type=float, default=0.5, help="transition length in seconds (default 0.5)")
    ap.add_argument("--width", type=int, help="output width (default: first clip)")
    ap.add_argument("--height", type=int, help="output height (default: first clip)")
    ap.add_argument("--fps", type=float, help="output frame rate (default: first clip)")
    ap.add_argument("--fit", choices=["pad", "crop"], default="pad", help="how clips of another aspect reach the frame (default pad)")
    ap.add_argument("--pad-color", default="black")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    aud = ap.add_argument_group("audio-only inputs")
    aud.add_argument("--sample-rate", type=int, help="output sample rate in Hz (default: first clip's)")
    aud.add_argument("--channels", type=int, choices=[1, 2, 6, 8], help="output channel count (default: the widest clip)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if len(args.inputs) < 2:
        die("give at least two clips")
    metas = [probe(p) for p in args.inputs]
    if all(not m.get("video") for m in metas):
        for p, m in zip(args.inputs, metas):
            if not m.get("audio"):
                die(f"{p} has neither a video nor an audio stream")
        return join_audio(args, metas)
    for p, m in zip(args.inputs, metas):
        if not m.get("video"):
            others = [q for q, mm in zip(args.inputs, metas) if mm.get("video")]
            die(f"{p} has no video stream" + (f" while {others[0]} has one; join audio with audio or give every clip a picture" if others else ""))
    first = metas[0]["video"]
    fw, fh = first["width"], first["height"]
    if first.get("rotation") in (90, -90, 270, -270):
        fw, fh = fh, fw
    if args.width and args.height:
        w, h = args.width, args.height
    elif args.width:
        w, h = args.width, int(round(args.width * fh / fw))
    elif args.height:
        w, h = int(round(args.height * fw / fh)), args.height
    else:
        w, h = fw, fh
    fps = args.fps or first.get("fps") or 30.0
    fps = round(fps) if abs(fps - round(fps)) < 0.02 else fps
    w, h = w - (w % 2), h - (h % 2)
    durs = [m.get("duration") or 0.0 for m in metas]
    d = args.duration if args.transition != "none" else 0.0
    for p, dur in zip(args.inputs, durs):
        if d and dur <= d * 2 and not STATE["dry_run"]:
            die(f"{p} is only {dur:.2f}s, too short for a {d:.2f}s transition; shorten --duration")

    cmd = ffmpeg_base()
    extra_inputs: List[str] = []
    parts: List[str] = []
    n = len(args.inputs)
    for i, (p, m) in enumerate(zip(args.inputs, metas)):
        cmd += ["-i", p]
    # silent audio for clips without an audio track
    audio_src: List[str] = []
    for i, m in enumerate(metas):
        if m.get("audio"):
            audio_src.append(f"{i}:a:0")
        else:
            idx = n + len(extra_inputs)
            extra_inputs += ["-f", "lavfi", "-t", f"{durs[i]:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_src.append(f"{idx}:a:0")
    cmd += extra_inputs

    if args.fit == "crop":
        geo = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        geo = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}"
    pixfmt = "yuv420p10le" if (metas[0].get("video") or {}).get("hdr") else "yuv420p"
    for i in range(n):
        parts.append(f"[{i}:v]{geo},setsar=1,fps={fps:g},format={pixfmt},settb=AVTB[v{i}]")
        parts.append(f"[{audio_src[i]}]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")

    if args.transition == "none":
        chain = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{chain}concat=n={n}:v=1:a=1[vout][aout]")
    else:
        vprev, aprev = "v0", "a0"
        offset = 0.0
        for i in range(1, n):
            offset += durs[i - 1] - d
            vout = f"vx{i}" if i < n - 1 else "vout"
            aout = f"ax{i}" if i < n - 1 else "aout"
            parts.append(f"[{vprev}][v{i}]xfade=transition={args.transition}:duration={d:g}:offset={offset:.3f}[{vout}]")
            parts.append(f"[{aprev}][a{i}]acrossfade=d={d:g}:c1=tri:c2=tri[{aout}]")
            vprev, aprev = vout, aout

    output = args.output or default_output(args.inputs[0], "joined", "mp4")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]"]
    cmd += video_args(metas[0], args.crf, args.preset) + aac_args() + [output]
    run(cmd)
    expected = sum(durs) - d * (n - 1)
    r = probe(output)
    info(f"wrote {output} ({r['duration']:.3f}s, expected ~{expected:.3f}s, {w}x{h} @ {fps:g}fps, {n} clips, {args.transition})")
    emit(output, mode="video", clips=n, transition=args.transition, expected_duration=round(expected, 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
