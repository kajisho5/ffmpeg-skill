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
  python3 join.py --list parts.txt --transition none -o voice.wav          # the segments a TTS step wrote, in order
  python3 join.py --list parts.txt --on-missing skip -o voice.wav          # join what is there, report the rest

Every input is checked before anything is joined: a missing, empty or unreadable segment is
refused with every problem named at once (kind input), never discovered one run at a time.
--on-missing skip joins the usable segments instead and lists the others under `skipped`.
Under --dry-run a segment that does not exist yet is an earlier step's output: it is planned
on and named under `pending` (never `skipped`), whichever --on-missing was given, and its
extension stands in for what it will hold (an audio extension: no picture).
"""
import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from _common import STATE, AUDIO_MEDIA_EXT, video_args, aac_args, add_common, apply_common, audio_codec_for, default_output, die, dry_run_input_pending, emit, ffmpeg_base, info, is_audio_output, probe, require_tool, run, validate_color, X264_PRESETS, fmt_secs

TRANSITIONS = ["fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
               "circleopen", "circleclose", "fadeblack", "fadewhite", "smoothleft", "smoothright", "radial", "none"]
LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}
# inputs --on-missing skip dropped, reported in the success document (empty when nothing was)
STATE_SKIPPED: List[Dict[str, Any]] = []
# --dry-run: inputs that do not exist yet, planned on as an earlier step's output
STATE_PENDING: List[Dict[str, Any]] = []
STATE_NOTES: List[str] = []


def reported() -> Dict[str, Any]:
    """The input bookkeeping both success documents carry: `skipped` is what the join left out,
    `pending` what a dry run planned on without it existing; `notes` says the same in words."""
    extra: Dict[str, Any] = {"skipped": list(STATE_SKIPPED), "pending": list(STATE_PENDING)}
    if STATE_NOTES:
        extra["notes"] = list(STATE_NOTES)
    return extra


def unpending_length(durs: List[float], d: float) -> Optional[float]:
    """The joined length the clip durations add up to, or None while an input is pending: its
    dry-run stub says 0 s, which would count the clip as nothing and still subtract a transition
    for it (a negative length when nothing exists yet)."""
    if STATE_PENDING:
        return None
    return round(sum(durs) - d * (len(durs) - 1), 3)


def expected_text(expected: Optional[float]) -> str:
    """unpending_length() as the stderr summary line puts it."""
    return f"expected ~{expected:.3f}s" if expected is not None else "expected length unknown until the pending inputs exist"


def join_audio(args: argparse.Namespace, metas: List[dict]) -> int:
    """Concatenate audio-only inputs: one sample rate, one channel layout, acrossfade or concat."""
    n = len(args.inputs)
    durs = [m.get("duration") or 0.0 for m in metas]
    d = args.duration if args.transition != "none" else 0.0
    for p, dur in zip(args.inputs, durs):
        if d and dur <= d * 2 and not STATE.dry_run:
            die(f"{p} is only {dur:.2f}s, too short for a {d:.2f}s crossfade; shorten --duration")
    # a pending input's probe is the dry-run stub (rate and layout unmeasured): plan from the
    # clips that exist, and fall back to 48 kHz stereo only when none does
    known = [m for m in metas if not m.get("dry_run")] or metas
    rates = [m["audio"].get("sample_rate") or 48000 for m in known]
    chans = [m["audio"].get("channels") or 2 for m in known]
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
    expected = unpending_length(durs, d)
    r = probe(output, role="output")
    a = r.get("audio") or {}
    if not STATE.dry_run:
        if r.get("video"):
            die(f"{output} unexpectedly contains a video stream")
        if a.get("sample_rate") != rate or a.get("channels") != channels:
            die(f"{output} is {a.get('sample_rate')} Hz {a.get('channels')} ch, expected {rate} Hz {channels} ch")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, {expected_text(expected)}, audio {a.get('codec')} {channels}ch {rate}Hz, {n} clips, "
         + ("crossfade" if d else "butt join") + ")")
    emit(output, mode="audio", **reported(), clips=n, transition=args.transition if d else "none", expected_duration=expected,
         sample_rate=rate, channels=channels, video=False)
    return 0


def read_list(path: str) -> List[str]:
    """--list FILE: one segment per line, in order, relative to the list file's own folder.
    Blank lines and # comments are ignored, and ffmpeg's concat-demuxer spelling
    (`file 'part 01.wav'`) is accepted, so a list written for `ffmpeg -f concat` works as is."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        die(f"cannot read --list {path}: {exc}")
    base = os.path.dirname(os.path.abspath(path))
    entries: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file "):
            line = line[5:].strip()
            if len(line) >= 2 and line[0] == line[-1] and line[0] in "'\"":
                line = line[1:-1].replace("'\\''", "'")
        entries.append(line if os.path.isabs(line) else os.path.join(base, line))
    if not entries:
        # the failure this exists for: an upstream step produced nothing, and the join must
        # say so plainly rather than hand ffmpeg an empty concat and die somewhere later
        die(f"--list {path} names no segments (empty, or only blank lines and comments)",
            hint="check the step that writes the list: it produced no files")
    return entries


def preflight(paths: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Every problem with every input, found before anything runs: missing, empty (0 bytes,
    the usual trace of a TTS or download step that failed after creating its file), or not
    readable as media. One ffprobe per file; nothing is decoded. Under --dry-run a file that
    does not exist yet is not a problem but pending (the second list, with a note): in a
    planned pipeline it is an earlier step's output, and the plan keeps it."""
    ffprobe = require_tool("ffprobe")
    problems: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for i, p in enumerate(paths):
        if dry_run_input_pending(p):
            pending.append({"index": i, "path": p})
            continue
        if not os.path.exists(p):
            problems.append({"index": i, "path": p, "reason": "missing"})
            continue
        if os.path.isdir(p):
            problems.append({"index": i, "path": p, "reason": "a directory, not a file"})
            continue
        if os.path.getsize(p) == 0:
            problems.append({"index": i, "path": p, "reason": "empty (0 bytes)"})
            continue
        proc = run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p],
                   quiet=True, check=False)
        kinds = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
        if proc.returncode != 0 or not kinds & {"audio", "video"}:
            first = ((proc.stderr or "").strip().splitlines() or ["no audio or video stream"])[-1]
            problems.append({"index": i, "path": p, "reason": f"unreadable: {first}"})
    return problems, pending


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="two or more clips in order (or --list FILE)")
    ap.add_argument("--list", metavar="FILE", help="read the clips from FILE, one per line in order (paths relative to FILE; "
                                                   "ffmpeg concat lines `file 'x.wav'` also accepted); an empty list is refused")
    ap.add_argument("--on-missing", choices=["fail", "skip"], default="fail",
                    help="a missing, empty or unreadable input: fail (default; every problem named at once) or skip "
                         "(join the rest; each skipped input is reported under `skipped`)")
    ap.add_argument("-o", "--output", help="output file (default: <first>_joined.mp4)")
    ap.add_argument("--transition", choices=TRANSITIONS, default="fade", help="transition between clips (default fade)")
    ap.add_argument("--duration", type=float, default=0.5, help="transition length in seconds (default 0.5)")
    ap.add_argument("--width", type=int, help="output width (default: first clip)")
    ap.add_argument("--height", type=int, help="output height (default: first clip)")
    ap.add_argument("--fps", type=float, help="output frame rate (default: first clip)")
    ap.add_argument("--fit", choices=["pad", "crop"], default="pad", help="how clips of another aspect reach the frame (default pad)")
    ap.add_argument("--pad-color", default="black")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS)
    aud = ap.add_argument_group("audio-only inputs")
    aud.add_argument("--sample-rate", type=int, help="output sample rate in Hz (default: first clip's)")
    aud.add_argument("--channels", type=int, choices=[1, 2, 6, 8], help="output channel count (default: the widest clip)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be positive, got {args.fps:g}")

    if args.list:
        if args.inputs:
            die("give the clips either as arguments or with --list, not both")
        args.inputs = read_list(args.list)
    if not args.inputs:
        die("give at least two clips (or --list FILE)")
    skipped: List[Dict[str, Any]] = []
    problems, pending = preflight(args.inputs)
    if problems and args.on_missing == "fail":
        listing = "; ".join(f"#{p['index'] + 1} {p['path']}: {p['reason']}" for p in problems)
        die(f"{len(problems)} of {len(args.inputs)} inputs cannot be joined: {listing}",
            hint="fix or regenerate them, or pass --on-missing skip to join the rest", problems=problems)
    if problems:
        bad = {p["index"] for p in problems}
        skipped = problems
        args.inputs = [p for i, p in enumerate(args.inputs) if i not in bad]
        for p in problems:
            info(f"skipping #{p['index'] + 1} {p['path']}: {p['reason']}")
    STATE_SKIPPED[:] = skipped
    STATE_PENDING[:] = pending
    if pending:
        # a dry run cannot know whether the file will be there: it plans on it, and says what a
        # real run does if it still is not (the same --on-missing rule as any missing input --
        # including the refusal when skipping would leave fewer than two inputs)
        left = len(args.inputs) - len(pending)
        if args.on_missing == "fail":
            then = "refuses the join if one is still missing"
        elif left >= 2:
            then = "skips one that is still missing"
        else:
            then = (f"skips one that is still missing and refuses the join if that leaves fewer than two inputs "
                    f"(only {left} exist{'s' if left == 1 else ''} now)")
        STATE_NOTES.append(f"{len(pending)} of {len(args.inputs) + len(skipped)} inputs do not exist yet and were planned on "
                           "as an earlier step's output: " + ", ".join(f"#{p['index'] + 1} {p['path']}" for p in pending)
                           + f"; a real run {then}")
    if len(args.inputs) < 2:
        die("give at least two clips" if not skipped else
            f"only {len(args.inputs)} usable input(s) left after skipping {len(skipped)}; nothing to join",
            skipped=skipped)
    validate_color(args.pad_color, "--pad-color")
    metas = [probe(p) for p in args.inputs]
    # A pending input's probe is the dry-run stub, whose (0x0) video stream says nothing about the
    # file an earlier step will write. Its extension stands in: a step names its output for what
    # it holds, so an audio extension (.wav, .m4a, .aiff, ... -- every audio file this skill
    # reads, not only the ones it writes) is taken for a file without a picture and any other for
    # one with a picture. Measured and pending inputs then meet the same rules a real run
    # applies: all without a picture is an audio join, a mix is refused.
    pictured = [(os.path.splitext(p)[1].lower() not in AUDIO_MEDIA_EXT) if m.get("dry_run") else bool(m.get("video"))
                for p, m in zip(args.inputs, metas)]
    if all(m.get("dry_run") for m in metas):
        STATE_NOTES.append(f"no input exists yet: {'a video' if any(pictured) else 'an audio'} join was planned from the file extensions")
    if not any(pictured):
        for p, m in zip(args.inputs, metas):
            if not m.get("audio"):
                die(f"{p} has neither a video nor an audio stream")
        return join_audio(args, metas)
    for p, m, pic in zip(args.inputs, metas, pictured):
        if not pic:
            # name an input measured to have a picture first; a pending one only as expected to
            measured = [q for q, mm in zip(args.inputs, metas) if mm.get("video") and not mm.get("dry_run")]
            planned = [q for q, mm, pc in zip(args.inputs, metas, pictured) if pc and mm.get("dry_run")]
            other = (f"{measured[0]} has one" if measured else
                     f"{planned[0]}, which does not exist yet, is expected to have one (its extension is not an audio one)" if planned else "")
            die((f"{p} does not exist yet, and its audio extension says it will have no video stream" if m.get("dry_run")
                 else f"{p} has no video stream")
                + (f" while {other}; join audio with audio or give every clip a picture" if other else ""))
    first = metas[0]["video"]
    fw, fh = first["width"], first["height"]
    if first.get("rotation") in (90, -90, 270, -270):
        fw, fh = fh, fw
    if args.width and args.height:
        w, h = args.width, args.height
    elif args.width:
        w = args.width
        h = int(round(args.width * fh / fw)) if fw else args.width
    elif args.height:
        h = args.height
        w = int(round(args.height * fw / fh)) if fh else args.height
    else:
        w, h = fw, fh
    fps = args.fps or first.get("fps") or 30.0
    fps = round(fps) if abs(fps - round(fps)) < 0.02 else fps
    w, h = w - (w % 2), h - (h % 2)
    durs = [m.get("duration") or 0.0 for m in metas]
    d = args.duration if args.transition != "none" else 0.0
    for p, dur in zip(args.inputs, durs):
        if d and dur <= d * 2 and not STATE.dry_run:
            die(f"{p} is only {dur:.2f}s, too short for a {d:.2f}s transition; shorten --duration")

    cmd = ffmpeg_base()
    extra_inputs: List[str] = []
    parts: List[str] = []
    n = len(args.inputs)
    for i, (p, m) in enumerate(zip(args.inputs, metas)):
        cmd += ["-i", p]
    # silent audio for clips without an audio track. `idx` is this ffmpeg input's position, i.e. n +
    # how many synthetic inputs were already added -- not len(extra_inputs), which counts the six
    # argv tokens ("-f", "lavfi", "-t", duration, "-i", "anullsrc=...") each synthetic input adds, not
    # the input itself. With one no-audio clip both counts coincide (n + 0); from the second no-audio
    # clip onward they diverge, and the previous `n + len(extra_inputs)` named a nonexistent, far-out-of-
    # range ffmpeg input index -- found via a real multi-camera join where every clip lacked audio.
    audio_src: List[str] = []
    added = 0
    for i, m in enumerate(metas):
        if m.get("audio"):
            audio_src.append(f"{i}:a:0")
        else:
            idx = n + added
            extra_inputs += ["-f", "lavfi", "-t", f"{durs[i]:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_src.append(f"{idx}:a:0")
            added += 1
    cmd += extra_inputs

    if args.fit == "crop":
        geo = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        geo = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={args.pad_color}"
    # Any HDR input makes the join HDR (10-bit, HEVC via video_args on that clip's tags): an SDR
    # first clip used to drag an HDR second clip down to 8-bit without a tone map.
    hdr_meta = next((m for m in metas if (m.get("video") or {}).get("bt2020_or_hdr")), None)
    pixfmt = "yuv420p10le" if hdr_meta else "yuv420p"
    # the audio-only join keeps the widest layout; the video join used to force stereo and
    # silently dropped the centre/LFE of 5.1 material. A pending input's stub has no measured
    # layout: plan from the inputs that exist, as join_audio() does.
    chans = [(m.get("audio") or {}).get("channels") or 2 for m in ([m for m in metas if not m.get("dry_run")] or metas)]
    channels = args.channels or max(chans)
    layout = LAYOUTS.get(channels)
    if layout is None:
        die(f"{channels}-channel output has no standard layout here (1, 2, 6 or 8); pass --channels")
    if len(set(chans)) > 1:
        info(f"channel counts differ ({', '.join(str(c) for c in chans)}); every clip becomes {layout}")
    for i in range(n):
        parts.append(f"[{i}:v]{geo},setsar=1,fps={fps:g},format={pixfmt},settb=AVTB[v{i}]")
        parts.append(f"[{audio_src[i]}]aformat=sample_rates=48000:channel_layouts={layout},asetpts=PTS-STARTPTS[a{i}]")

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

    # A pending input's stub is unmeasured (0x0, 0 fps, 0 s -- #77 keeps it honest rather than
    # plausible), and the planned command is built on it: say which numbers are placeholders.
    if metas[0].get("dry_run") and not (args.width and args.height and args.fps):
        STATE_NOTES.append(f"the first input is pending, so the planned frame and rate ({w}x{h} @ {fps:g}fps) are "
                           "placeholders: a real run takes them from that file")
    if d and any(m.get("dry_run") for m in metas[:-1]):
        STATE_NOTES.append("the planned xfade offsets count each pending input as 0 s long: a real run offsets "
                           "by its measured length")
    output = args.output or default_output(args.inputs[0], "joined", "mp4")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]"]
    cmd += video_args(hdr_meta or metas[0], args.crf, args.preset) + aac_args() + [output]
    run(cmd)
    expected = unpending_length(durs, d)
    r = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, {expected_text(expected)}, {w}x{h} @ {fps:g}fps, {n} clips, {args.transition})")
    emit(output, mode="video", **reported(), clips=n, transition=args.transition, expected_duration=expected,
         dropped_non_av_streams=any(m.get("subtitle_streams") or m.get("data_streams") for m in metas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
