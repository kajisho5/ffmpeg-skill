#!/usr/bin/env python3
"""Cut a clip or several segments out of a video and (optionally) join them.

Lossless stream copy (-c copy) is preferred. Cuts snap to keyframes in that
mode, so if frame accuracy matters pass --accurate to re-encode. Multiple
segments are cut individually and concatenated with the concat demuxer.

Audio: a stream copy lands on a packet boundary (about 21 ms for AAC, one
demuxer block for WAV); --accurate decodes and trims to the sample. The output
extension picks the codec: -o out.wav writes PCM (never an AAC packet inside a
WAV), -o out.m4a writes AAC; an audio extension on a video input drops the
picture (mp4 -> wav extraction). The result reports `precision`
(packet / sample / codec_frame / frame) and the measured duration error, plus
`mode` (copy / accurate / hybrid -- "hybrid" means a lossless cut silently
re-encoded because the keyframe snap exceeded --tolerance), `keyframe_snapped`,
`requested_start`/`requested_end` (or `requested_segments` for --segments),
`requested_duration`, `output_duration` and `duration_delta_seconds` -- so a
caller never has to trust "it probably cut where I asked" on faith.

Examples:
  python3 cut.py input.mp4 --start 00:00:10 --end 00:00:25
  python3 cut.py input.mp4 --segments 0:05-0:12,1:00-1:20 -o highlights.mp4
  python3 cut.py input.mp4 --start 3.5 --duration 10 --accurate
  python3 cut.py talk.wav --start 1.2345 --end 2.3456 --accurate -o part.wav   # sample-exact
  python3 cut.py talk.mp4 --start 1:00 --end 2:00 -o part.wav                   # audio extraction
"""
import argparse
import os
import sys
import tempfile
from typing import List, Tuple

from _common import video_args, STATE, add_common, apply_common, audio_codec_for, emit, aac_args, cfr_args, default_output, die, ffmpeg_base, info, is_audio_output, time_arg, probe, run, X264_PRESETS, keyframes_near, MissingFpsError, concat_list_line, refuse_output_is_input, fmt_secs

# outputs whose re-encode dropped a subtitle/data stream (reported as dropped_non_av_streams)
DROPPED_STREAMS: List[str] = []
# keyframe timestamps found next to a requested cut that the tolerance turned into a re-encode
# (reported so the caller can choose a lossless cut at one of them next time)
NEAREST_KEYFRAMES: list = []


def _t(value: str, fps, flag: str = "--segments") -> float:
    """time_arg() with the input's fps (SMPTE hh:mm:ss:ff, or @fps): the one parser every tool uses (1.9)."""
    return time_arg(value, flag, fps)


def parse_segments(spec: str, fps=None) -> List[Tuple[float, float]]:
    segs = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "-" not in raw:
            die(f"segment '{raw}' must look like START-END (e.g. 0:05-0:12)")
        a, b = raw.rsplit("-", 1)
        start, end = _t(a, fps), _t(b, fps)
        if start < 0:
            die(f"segment '{raw}': start must be >= 0")
        if end <= start:
            die(f"segment '{raw}': end must be after start")
        segs.append((start, end))
    if not segs:
        die("no segments given")
    return segs


def encode_args(meta: dict, dst: str, crf: int, preset: str) -> List[str]:
    """Codec arguments for a re-encoded cut: video + AAC into a video container, otherwise the codec
    the audio extension names (PCM for .wav, FLAC, MP3, AAC...) with no video stream."""
    if is_audio_output(dst) or not meta.get("video"):
        return ["-vn"] + audio_codec_for(dst)
    return video_args(meta, crf, preset) + cfr_args(meta) + aac_args()


def copy_args(meta: dict, dst: str) -> List[str]:
    """Stream-copy arguments: everything into a video container, audio only into an audio extension."""
    if is_audio_output(dst) and meta.get("video"):
        return ["-vn", "-c:a", "copy"]
    return ["-c", "copy"]


LOSSLESS_AUDIO = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "flac"}


def precision_of(meta: dict, dst: str, reencoded: bool) -> str:
    """How exact the cut is, measured on what was written:

    packet      stream copy; the cut lands on a packet (audio) or keyframe (video) boundary
    sample      decoded audio trimmed to the sample and written losslessly (PCM / FLAC)
    codec_frame decoded audio trimmed to the sample, then framed by a lossy encoder (AAC 1024,
                MP3 1152, Opus 960 samples) which also adds its priming delay to the reported length
    frame       re-encoded video: the picture is frame-exact, the audio underneath is sample-trimmed
    """
    if not reencoded:
        return "packet"
    if is_audio_output(dst) or not meta.get("video"):
        codec = audio_codec_for(dst)[1]
        return "sample" if codec in LOSSLESS_AUDIO else "codec_frame"
    return "frame"


def cut_one(src: str, start: float, end: float, dst: str, reencode: bool, crf: int, preset: str, tolerance: float = 0.5, meta: dict = None) -> bool:
    """Cut one segment. Returns True if the result was re-encoded."""
    dur = end - start
    meta = meta or probe(src)
    audio_only = is_audio_output(dst) or not meta.get("video")
    if not reencode and audio_only and audio_codec_for(dst)[1].startswith("pcm") and not str((meta.get("audio") or {}).get("codec", "")).startswith("pcm"):
        info(f"{(meta.get('audio') or {}).get('codec')} packets cannot be copied into a PCM container; decoding to PCM")
        reencode = True
    if reencode:
        # -ss before -i seeks, then decoding discards samples up to the exact start (accurate_seek);
        # atrim bounds the decoded stream to the requested length at sample resolution.
        cmd = ffmpeg_base() + ["-ss", f"{start:.6f}", "-i", src, "-t", f"{dur:.6f}"]
        if is_audio_output(dst) or not meta.get("video"):
            cmd += ["-af", f"atrim=end={dur:.6f},asetpts=PTS-STARTPTS"]
        # ffmpeg's default stream selection also picks one subtitle stream; a re-encode cannot
        # trim it (the cues kept their timestamps and the container grew to 2 s for a 1 s cut,
        # sweep F2), so the re-encode carries video/audio only and the result says so
        cmd += ["-sn", "-dn"]
        if meta.get("subtitle_streams") or meta.get("data_streams"):
            DROPPED_STREAMS.append(dst)
        cmd += encode_args(meta, dst, crf, preset) + ["-avoid_negative_ts", "make_zero", dst]
    elif audio_only:
        # output-side seek: an input seek on a video file lands on the previous video keyframe and on
        # FLAC/MP3 on a coarse index; reading from the start and dropping packets is exact to the packet
        cmd = ffmpeg_base() + ["-i", src, "-ss", f"{start:.6f}", "-t", f"{dur:.6f}"] + copy_args(meta, dst) + ["-avoid_negative_ts", "make_zero", dst]
    else:
        cmd = ffmpeg_base() + ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"] + copy_args(meta, dst) + ["-avoid_negative_ts", "make_zero", dst]
    proc = run(cmd, check=False)
    if proc.returncode != 0:
        if not reencode:
            info("stream copy failed, falling back to re-encode")
            return cut_one(src, start, end, dst, True, crf, preset, tolerance, meta)
        die(f"ffmpeg failed:\n{proc.stderr.strip()}", kind="ffmpeg")
    if not reencode and tolerance >= 0 and not STATE.dry_run:
        got = probe(dst).get("duration") or 0.0
        if abs(got - dur) >= tolerance:  # a snap of exactly the tolerance is not "within" it (sweep F20)
            near = keyframes_near(src, start)
            alt = ""
            if near:
                closest = min(near, key=lambda k: abs(k - start))
                alt = (f"; for a lossless cut move --start to a keyframe (nearest: {closest:.3f}s"
                       + (f", others within 5 s: {', '.join(f'{k:.3f}' for k in near if k != closest)}" if len(near) > 1 else "") + ")")
                NEAREST_KEYFRAMES.extend(k for k in near if k not in NEAREST_KEYFRAMES)
            info(f"stream copy landed on a keyframe {abs(got - dur):.2f}s away from the requested cut "
                 f"(> {tolerance:.2f}s tolerance); re-encoding this segment for accuracy{alt}")
            return cut_one(src, start, end, dst, True, crf, preset, tolerance, meta)
    return reencode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_cut.<ext>)")
    g = ap.add_argument_group("range (single segment)")
    g.add_argument("--start", default="0", help="start time (seconds, mm:ss or hh:mm:ss.ms). default 0")
    g.add_argument("--end", help="end time")
    g.add_argument("--duration", help="duration instead of --end")
    ap.add_argument("--segments", help="comma separated START-END list, e.g. '0:05-0:12,1:00-1:20' (joined in order)")
    ap.add_argument("--accurate", action="store_true", help="always re-encode for frame-accurate (video) / sample-accurate (audio) cuts (default: lossless -c copy, re-encoding only when the keyframe snap exceeds --tolerance)")
    ap.add_argument("--tolerance", type=float, default=0.5, help="max seconds a lossless cut may deviate before re-encoding kicks in (default 0.5, -1 = never)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF when re-encoding (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset when re-encoding")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    total = meta.get("duration") or 0.0
    if meta.get("video", {}) and meta["video"].get("variable_frame_rate_suspected") and not args.accurate:
        info("source looks variable-frame-rate; lossless cuts on VFR are unreliable, switching to --accurate")
        args.accurate = True
    if STATE.codec and not args.accurate:
        # "cut this and make it HEVC": a stream copy keeps the source codec, so the request is a re-encode
        info(f"--codec {STATE.codec} asks for a re-encode; the lossless copy path keeps the source codec, switching to --accurate")
        args.accurate = True

    fps = (meta.get("video") or {}).get("fps")
    if args.segments:
        segments = parse_segments(args.segments, fps)
    else:
        start = _t(args.start, fps, "--start")
        if start < 0:
            die(f"--start must not be negative, got {args.start!r}")
        if args.end and args.duration:
            die("use --end or --duration, not both")
        if args.end:
            end = _t(args.end, fps, "--end")
            if end < 0:
                die(f"--end must not be negative, got {args.end!r}")
        elif args.duration:
            end = start + _t(args.duration, fps, "--duration")
        else:
            end = total
        if end <= start:
            die("end must be after start")
        segments = [(start, end)]

    for s, e in segments:
        if total and s >= total:
            die(f"segment start {s:.3f}s is beyond the media duration {total:.3f}s")
    segments = [(s, min(e, total) if total else e) for s, e in segments]

    output = args.output or default_output(args.input, "cut")
    refuse_output_is_input(output, args.input)
    ext = os.path.splitext(output)[1] or ".mp4"

    reencoded = False
    if len(segments) == 1:
        reencoded = cut_one(args.input, segments[0][0], segments[0][1], output, args.accurate, args.crf, args.preset, args.tolerance, meta)
    else:
        with tempfile.TemporaryDirectory(prefix="ffskill_cut_") as tmp:
            parts = []
            for i, (s, e) in enumerate(segments):
                part = os.path.join(tmp, f"part{i:03d}{ext}")
                reencoded |= cut_one(args.input, s, e, part, args.accurate, args.crf, args.preset, args.tolerance, meta)
                parts.append(part)
            listfile = os.path.join(tmp, "list.txt")
            with open(listfile, "w", encoding="utf-8") as fh:
                for p in parts:
                    fh.write(concat_list_line(p) + "\n")
            cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", output]
            proc = run(cmd, check=False)
            if proc.returncode != 0:
                info("concat with stream copy failed, re-encoding the join")
                cmd = ffmpeg_base() + ["-f", "concat", "-safe", "0", "-i", listfile] + encode_args(meta, output, args.crf, args.preset) + [output]
                run(cmd)

    result = probe(output, role="output")
    expected = sum(e - s for s, e in segments)
    precision = precision_of(meta, output, reencoded)
    got = result.get("duration")
    error_ms = round((got - expected) * 1000, 3) if got is not None and not STATE.dry_run else None
    # mode: "copy" (untouched lossless), "accurate" (--accurate was asked for), "hybrid" (asked for
    # lossless but the keyframe snap exceeded --tolerance so this segment silently re-encoded instead)
    mode = "copy" if not reencoded else ("accurate" if args.accurate else "hybrid")
    keyframe_snapped = precision == "packet"
    info(f"wrote {output} ({fmt_secs(got)}, expected ~{expected:.3f}s, "
         + ("re-encoded" if reencoded else "lossless stream copy") + f", {precision} precision)")
    emit(output, expected_duration=round(expected, 6), duration_error_ms=error_ms, precision=precision, reencoded=reencoded,
         dropped_non_av_streams=bool(DROPPED_STREAMS),
         requested_start=round(segments[0][0], 6) if len(segments) == 1 else None,
         requested_end=round(segments[0][1], 6) if len(segments) == 1 else None,
         requested_segments=[[round(s, 6), round(e, 6)] for s, e in segments] if len(segments) > 1 else None,
         requested_duration=round(expected, 6), output_duration=round(got, 6) if got is not None else None,
         duration_delta_seconds=round(error_ms / 1000, 6) if error_ms is not None else None,
         mode=mode, keyframe_snapped=keyframe_snapped,
         nearest_keyframes=sorted(NEAREST_KEYFRAMES) if NEAREST_KEYFRAMES else None,
         # the trade the caller can offer instead of a re-encode (eval e02: "without losing quality")
         lossless_alternative=(f"--start {min(NEAREST_KEYFRAMES, key=lambda k: abs(k - segments[0][0])):.3f} lands on a keyframe: "
                               f"stream copy with no re-encode, {abs(min(NEAREST_KEYFRAMES, key=lambda k: abs(k - segments[0][0])) - segments[0][0]):.2f}s off the requested start")
         if mode == "hybrid" and NEAREST_KEYFRAMES and len(segments) == 1 else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
