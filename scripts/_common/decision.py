"""Pure choices: given facts (a probe document, a codec name, a path, a flag value), return the
arguments or the value that follows from them.

Nothing here starts a subprocess or touches a media file, which is what makes the copy-vs-re-encode
and encoder-selection rules testable on their own.
"""
from __future__ import annotations

import json
import math
import os
import re
import argparse
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from _common.color import (bt709_label_filter, bt709_matrix_args, bt709_matrix_filter, bt709_tag_args, drawn_stream_format,
                           is_neutral_color, rgb_island, rgb_to_bt709_filter, _sdr_bt709)
from _common.emit import die, record_fallback, refuse, warn
from _common.runner import CODECS, STATE, ffmpeg_encoders, ffmpeg_list_error, ffmpeg_version, hw_platform_reason


def pad_filters(out_w: int, out_h: int, fill: str, color: str, blur: int, darken: float = 0.0,
                meta: Optional[Dict[str, Any]] = None) -> str:
    """The letterbox/pillarbox step shared by fit.py and export.py, as one -vf segment.

    fill="color": scale to fit, then pad with a solid colour (the historical behaviour).
    fill="blur": the bars are a blurred, scaled-to-cover copy of the same frame -- what every
    phone editor's "make it vertical" does with landscape footage (#139). Built as a small
    graph inside the -vf chain: split, one branch scaled to cover and cropped to the frame
    then boxblur'ed, the other scaled to fit, overlaid centred. Only `filter:boxblur` is
    needed beyond the usual scale/pad set, and that is already required by redact.py.
    `darken` > 0 also dims that background copy by that much brightness (eq), so the picture in
    front reads as the subject instead of competing with a bright blurred copy of itself --
    what `fit.py --fit blur` uses (1.14).
    `meta`: the probe of the picture being padded, when the output is that picture's re-encode: a
    --pad-color with chroma is then drawn in the BT.709 the line tags (drawn_chain()). Without it
    (a still made RGB, an export to GIF) the pad is what it always was."""
    if fill == "blur":
        # boxblur rejects a radius larger than half the smaller dimension ("radius 20, must be
        # <= 8" on a 16 px target); clamp instead of failing an otherwise valid request
        radius = max(1, min(int(blur), max(1, min(out_w, out_h) // 2 - 1)))
        return (f"split[__fitfg][__fitbg];"
                f"[__fitbg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur={radius}:2" + (f",eq=brightness=-{darken:g}" if darken else "") + "[__fitbgb];"
                f"[__fitfg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[__fitfgs];"
                f"[__fitbgb][__fitfgs]overlay=(W-w)/2:(H-h)/2:format=auto")
    pad = f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color="
    return (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            + (pad + color if meta is None else drawn_chain(pad + color, meta, [color], pad + "black", tag="pad")))


def add_pad_fill_args(parser: "argparse.ArgumentParser") -> None:
    parser.add_argument("--pad-fill", choices=["color", "blur"], default="color",
                        help="what fills the letterbox/pillarbox bars under --fit pad: a solid --pad-color (default) or a blurred, scaled-up copy of the frame")
    parser.add_argument("--pad-blur", type=int, default=20, help="blur radius in pixels for --pad-fill blur (default 20)")


def aspect_ratio(value: Any) -> Optional[Fraction]:
    """An aspect written W:H as an exact ratio, or None. fit.py --aspect and --export-timeline's
    sequence frame read an aspect through this one function, so the export refuses `16/9` and
    `2.39:1` where the render hands them to fit.py, which refuses them too (the timeline once
    took them and wrote a sequence for a project whose render then failed in fit.py). Each side
    is read with int(), as fit.py read it in 2.2.1, so a patch release refuses nothing fit.py
    took: `+16:9` and `1_6:9` still parse, and `0:9` is a zero ratio, which frame_size() treats
    as no aspect (2.2.1 kept the source frame). render.py's frame_from_preset() keeps 2.2.1's
    looser match: it only picks the export preset's size."""
    parts = str(value).split(":")
    if len(parts) != 2:
        return None
    try:
        return Fraction(int(parts[0]), int(parts[1]))
    except (ValueError, ZeroDivisionError):
        return None


def _even(n: float) -> int:
    v = int(round(n))
    return v if v % 2 == 0 else v + 1


def frame_size(ratio: Optional[Fraction], width: Optional[int], height: Optional[int],
               src_w: int, src_h: int) -> Tuple[int, int]:
    """The frame fit.py sizes for --aspect `ratio` (None: the source's own) and --width/--height,
    from a src_w x src_h picture -- and so the sequence frame render.py --export-timeline writes
    for the same project frame. Both sides given are used directly; one side takes the other from
    the aspect. With neither, the canvas takes the new aspect without exceeding the source's
    resolution in either dimension: a narrower/taller target than the source (e.g. 9:16 from a
    16:9 source) must be bounded by the source's HEIGHT, not its width -- bounding by width there
    multiplies the height by src_ratio/ratio (a 1920x1080 source asked for 9:16 used to come out
    1920x3414, a ~3.16x upscale in both fit=pad and fit=crop, entirely unrequested). Every side is
    rounded to even."""
    src_ratio = Fraction(src_w, src_h) if src_h else None
    if ratio is None:
        ratio = src_ratio
    if width and height:
        return _even(width), _even(height)
    if width:
        out_w = _even(width)
        return out_w, (_even(out_w / ratio) if ratio else width)
    if height:
        out_h = _even(height)
        return (_even(out_h * ratio) if ratio else height), out_h
    if ratio and src_ratio:
        if ratio <= src_ratio:
            out_h = _even(src_h)
            return _even(out_h * ratio), out_h
        out_w = _even(src_w)
        return out_w, _even(out_w / ratio)
    return _even(src_w), _even(src_h)


# x264 preset names mapped onto SVT-AV1's 0-13 speed scale (lower = slower / better)
SVT_PRESET = {"ultrafast": 12, "superfast": 11, "veryfast": 10, "faster": 9, "fast": 8, "medium": 6, "slow": 4, "slower": 3, "veryslow": 2, "placebo": 1}


def default_output(input_path: str, suffix: str, ext: Optional[str] = None) -> str:
    p = Path(input_path)
    new_ext = ext if ext else p.suffix.lstrip(".") or "mp4"
    return str(p.with_name(f"{p.stem}_{suffix}.{new_ext}"))


class MissingFpsError(ValueError):
    """parse_time() saw an hh:mm:ss:ff SMPTE timecode but no fps was given to convert it -- distinct
    from a plain ValueError so a caller that falls back to treating unparseable text as a literal
    line (e.g. caption.py's free-text cue format) can still fail loudly on this one, instead of
    silently swallowing a mistyped/missing --fps as an auto-timed line of digits."""


def concat_list_line(path: str) -> str:
    """One `file '...'` line for the concat demuxer. The demuxer reads backslash as an escape
    inside the quoted form, so a Windows path (C:\\Users\\...\\part000.mp4) must be written
    with forward slashes -- ffmpeg opens either spelling on Windows -- and a single quote in the
    name is closed, escaped and reopened. Shared by cut.py (multi-segment) and sequence.py."""
    escaped = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"


def fmt_secs(value: Optional[float]) -> str:
    """`12.345s`, or `?s` when the probe had no duration (MPEG-TS without a duration tag, a
    stream whose container and streams all omit it). Every writing tool prints the duration
    of what it wrote; formatting None with :.3f used to raise TypeError after a successful
    encode, in 25+ scripts."""
    return "?s" if value is None else f"{value:.3f}s"


def parse_time(value: str, fps: Optional[float] = None) -> float:
    """Accept seconds ('12.5'), mm:ss ('1:30'), hh:mm:ss(.ms) ('00:01:30.250'), SRT '00:01:30,250',
    or -- when `fps` is given -- SMPTE non-drop-frame timecode 'hh:mm:ss:ff' ('00:01:30:15')."""
    v = value.strip().replace(",", ".")
    if not v:
        raise ValueError("empty time")
    if "@" in v:
        # 1.9: 'hh:mm:ss:ff@29.97' names the timecode's rate explicitly (docs/design-decisions.md,
        # time grammar); it overrides the source fps a tool passed in, and is meaningless without
        # the four-part form
        v, _, rate = v.rpartition("@")
        if "@" in v:
            raise ValueError(f"'{value}': only one @fps suffix is allowed")
        try:
            fps = float(rate)
        except ValueError:
            raise ValueError(f"bad @fps suffix in '{value}' (expected a number such as @29.97)")
        if fps <= 0:
            raise ValueError(f"bad @fps suffix in '{value}': the rate must be positive")
        if len(v.split(":")) != 4:
            raise ValueError(f"'{value}': the @fps suffix belongs to an hh:mm:ss:ff timecode, not to seconds or mm:ss")
    parts = v.split(":")
    if len(parts) == 4:
        if fps is None or fps <= 0:
            raise MissingFpsError(f"'{value}' looks like an hh:mm:ss:ff SMPTE timecode, but no fps was given to convert its frame count to seconds (append @fps, e.g. {value}@29.97, or use seconds / mm:ss / hh:mm:ss.ms)")
        h, m, s, f = parts
        if "." in f:
            raise ValueError(f"bad SMPTE timecode: {value}")
        frame, whole_fps = int(f), int(round(fps))
        if not (0 <= frame < whole_fps):
            raise ValueError(f"bad SMPTE timecode '{value}': frame {frame} is out of range for {fps:g} fps (0-{whole_fps - 1})")
        # Non-drop-frame: the timecode counts whole_fps frames per timecode-second, so the real
        # time is the total frame count over the true rate (at 29.97 an hour of timecode is
        # 3596.4 s of video). This is exactly what fmt_smpte_time() inverts; before, the two
        # disagreed by ~0.1 % on the fractional NTSC rates and drifted apart over long files.
        total_frames = (int(h) * 3600 + int(m) * 60 + int(s)) * whole_fps + frame
        return total_frames / fps
    if len(parts) > 3:
        raise ValueError(f"bad time: {value}")
    total = 0.0
    for part in parts:
        try:
            total = total * 60 + float(part)
        except ValueError:
            # not the interpreter's "could not convert string to float: 'zz'" (review 9)
            raise ValueError(f"'{value}': not a time")
    return total


def time_arg(value: str, flag: str, fps: Optional[float] = None) -> float:
    """parse_time() for a command-line flag: SMPTE hh:mm:ss:ff resolves with the input's fps when
    the caller has one, and every parse failure is a `kind: input` refusal naming the flag (so
    `--json` callers get a failure document, never a traceback)."""
    try:
        return parse_time(value, fps)
    except MissingFpsError as e:
        die(f"{flag} {value!r}: {e}")
    except ValueError as e:
        die(f"{flag} {value!r}: {e} (use seconds, mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff at the source's fps or with an explicit @fps suffix)")
    return 0.0  # unreachable


def signed_time_arg(value: str, flag: str, fps: Optional[float] = None) -> float:
    """time_arg() for a flag that may also be negative (an offset, not a point in time): a single
    leading '-'/'+' is taken as the sign and the rest goes through the ordinary time grammar, so
    `--offset -00:00:02`, `--offset -1.5` and `--offset 0:02` all mean what they read as."""
    text = (value or "").strip()
    sign = 1.0
    if text[:1] in "+-":
        sign = -1.0 if text[0] == "-" else 1.0
        text = text[1:].strip()
    if not text:
        die(f"{flag} {value!r}: not a time (use seconds, mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff)")
    return sign * time_arg(text, flag, fps)


def fmt_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_smpte_time(seconds: float, fps: float) -> str:
    """SMPTE non-drop-frame timecode 'hh:mm:ss:ff' for a real fps (not the fractional NTSC rates
    -- 29.97/59.94 need drop-frame counting to stay wall-clock accurate, which this does not do)."""
    if seconds < 0:
        seconds = 0.0
    whole_fps = int(round(fps))
    total_frames = int(round(seconds * fps))
    frame = total_frames % whole_fps
    secs_total = total_frames // whole_fps
    h, rem = divmod(secs_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{frame:02d}"


def escape_filter_path(path: str, *, bind: bool = True) -> str:
    """Escape a file path for use as a filter option value (subtitles=, ass=, lut3d=file=, fontfile=, fontsdir=).

    A filter option value is parsed twice: the graph parser splits filters on `,` / `;` and options
    on `:`, then the filter's own option parser splits key=value pairs on `:` again. A character that
    must survive both passes needs two levels of escaping, so a Windows drive letter `D:/x.srt` is
    written `D\\\\:/x.srt`; with a single backslash the second pass still splits at the colon and
    ffmpeg reads `/x.srt` as the next option (`Unable to parse "original_size" option value`).
    Backslashes are turned into forward slashes first (ffmpeg accepts them on Windows), so a backslash
    never has to be escaped itself; `,`, `;`, `[` and `]` are graph-level characters and survive with
    one backslash. `'` is special: the graph parser also treats a quote as the start of a quoted
    token, so a single `\\'` is consumed by the first pass and "Ryo's Mac/cues.srt" reaches the
    filter as "Ryos Mac/cues.srt" (Unable to open ...). Three backslashes survive both passes
    (measured on 6.1 and 7.1 with subtitles=, ass= and lut3d=file=).

    `bind=False` escapes without recording the path as a plan input. The colour-emoji probe
    uses that: its SRT lives in a temp directory that is gone before any plan is written.
    """
    if bind and os.path.isfile(path) and path not in STATE.plan_inputs:
        STATE.plan_inputs.append(path)  # a plan binds subtitle/LUT/font files too (review 6)
    p = str(Path(path))
    p = p.replace("\\", "/")
    p = p.replace(":", "\\\\:")
    p = p.replace("'", "\\\\\\'")
    for ch in (",", ";", "[", "]"):
        p = p.replace(ch, "\\" + ch)
    return p


def cfr_args(meta: Optional[Dict[str, Any]], fps: Optional[float] = None) -> List[str]:
    """Force a constant frame rate on output when the source looks VFR (or fps is given).

    VFR sources (phone/screen recordings) drift against audio after cuts and joins,
    so every re-encoding script passes this to conform them automatically.
    """
    v = (meta or {}).get("video") or {}
    if fps is None and not v.get("variable_frame_rate_suspected"):
        return []
    rate = fps or v.get("fps") or 30.0
    rate = round(rate) if abs(rate - round(rate)) < 0.02 else rate
    return ["-fps_mode", "cfr", "-r", f"{rate:g}"]


# ------------------------------------------------------- VideoToolbox (--hw)
#
# CRF -> VideoToolbox -q:v (1-100, higher = better): at each CRF the highest -q:v whose SSIM matched
# the CPU line's (x264/x265 medium) across the clips of tests/bench_vt.py -- synthetic CG, fractal
# and grain plus iPhone 17 Pro 1080p (M3, FFmpeg 9.0.2), so a GPU encode never measures below the
# CPU one. HDR has its own curve: its CPU line is x265 Main10 at CRF+2, and the Main10 VideoToolbox
# line needs ~11-15 less -q:v for that SSIM (the SDR curve wrote HLG phone footage at 6-8x x265's
# bytes). Matched quality costs 1.1-2.9x the bytes of x264/x265 on SDR and 1.9-3.5x on HDR --
# which is why --hw is opt-in and delivery presets stay on the CPU (docs/design-decisions.md).


def vt_quality(codec: str, crf: int, hdr: bool = False) -> int:
    base, slope = (63.0, 1.6) if hdr else (75.0, 2.2) if codec == "h264" else (78.0, 2.0)
    return max(1, min(100, int(round(base - slope * (crf - 18)))))


def _vt_bt709(codec: str) -> List[str]:
    """BT.709 tags for a VideoToolbox SDR encode. From FFmpeg 7.1 the -colorspace output options
    drive a real matrix conversion on an untagged source (see bt709_tag_args), and VideoToolbox has
    no -x264-params VUI route; a bitstream filter writes the VUI after encoding, which the filter
    graph never sees (measured: 49.9 dB PSNR tag-neutral vs 23.8 dB through the output options).
    It is used on every version, not only >= 7.1: it is tag-only everywhere, and a git build of
    7.1 reads as (7, 0) from its libavutil major, which would otherwise take the converting path."""
    return ["-bsf:v", f"{codec}_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]


def _vt_args(codec: str, crf: int, meta: Optional[Dict[str, Any]], keep_bt709: bool) -> Optional[List[str]]:
    """VideoToolbox encoder options for `codec`, or None (with a note in STATE.hw_notes) when the
    request stays on the CPU: no VideoToolbox encoder for the codec, this machine cannot, or the
    ffmpeg build lacks it."""
    name = {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox", "prores": "prores_videotoolbox"}.get(codec)
    reason = None if name else f"no VideoToolbox encoder for {codec}"
    reason = reason or hw_platform_reason()
    if not reason and name not in ffmpeg_encoders():
        unread = ffmpeg_list_error("encoders")
        # an encoder list that could not be read says nothing about the build: name the read
        # failure, not a missing encoder (the read itself is a ffmpeg_list_unreadable warning)
        reason = (f"{name} could not be confirmed (this ffmpeg build's encoder list could not be read: {unread})" if unread
                  else f"this ffmpeg build has no {name}")
    if reason:
        note = f"{reason}; encoded on the CPU"
        if note not in STATE.hw_notes:
            STATE.hw_notes.append(note)
        return None
    v = (meta or {}).get("video") or {}
    hdr = bool(v.get("bt2020_or_hdr"))
    hdr_tags = ["-colorspace", v.get("color_space") or "bt2020nc", "-color_primaries", v.get("color_primaries") or "bt2020",
                "-color_trc", v.get("color_transfer") or "arib-std-b67"]
    if codec == "prores":
        return ["-c:v", name, "-profile:v", "hq", "-pix_fmt", "p210le"] + (hdr_tags if hdr else [])
    # The HDR curve was fitted on the Main10 HEVC line; an 8-bit H.264 line (an export preset on
    # an HDR source) replaces x264 at the same CRF and keeps the H.264 curve.
    q = str(vt_quality(codec, crf, hdr and codec == "hevc"))
    if codec == "h264":
        return ["-c:v", name, "-q:v", q, "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + \
            (_vt_bt709("h264") if keep_bt709 else [])
    if hdr:
        # Measured on FFmpeg 9.0: HDR10 mastering-display and content-light side data carry through
        # hevc_videotoolbox exactly as through libx265 (test_hw_hdr10_side_data_survives).
        return ["-c:v", name, "-q:v", q, "-profile:v", "main10", "-pix_fmt", "p010le", "-tag:v", "hvc1"] + hdr_tags + ["-movflags", "+faststart"]
    return ["-c:v", name, "-q:v", q, "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-movflags", "+faststart"] + \
        (_vt_bt709("hevc") if keep_bt709 else [])


# An LGPL ffmpeg (the kind a desktop app ships) has VideoToolbox but neither libx264 nor libx265.
# There the CPU line cannot run at all, so VideoToolbox is the only encoder there is and takes the
# job without --hw (#314). Only when the encoder list was read and lacks the CPU encoder, and only
# where --hw would run; a build that has libx264 never gets here (docs/design-decisions.md).
_VT_FOR_CPU = {"libx264": "h264_videotoolbox", "libx265": "hevc_videotoolbox"}


def _vt_in_place_of(cpu_encoder: Optional[str]) -> Optional[str]:
    """The VideoToolbox encoder that takes over from `cpu_encoder` because this ffmpeg build lacks
    it, else None: not when --hw already decided, nor under an explicit --no-hw (the caller asked
    for the CPU), nor on a machine VideoToolbox cannot run on. The platform is asked before the
    encoder list, so Linux and Windows never read it for this. An empty list (ffmpeg's could not
    be read) proves nothing is missing."""
    vt = _VT_FOR_CPU.get(cpu_encoder or "")
    if vt is None or STATE.hw or STATE.hw_source == "flag" or hw_platform_reason() is not None:
        return None
    have = ffmpeg_encoders()
    return vt if have and cpu_encoder not in have and vt in have else None


def _note_vt_in_place_of(cpu_encoder: str, vt: str) -> None:
    if cpu_encoder not in STATE.hw_auto:
        STATE.hw_auto.append(cpu_encoder)
    note = f"{cpu_encoder} is not in this ffmpeg build, so this encode ran on {vt} (VideoToolbox) instead"
    if note not in STATE.hw_notes:
        STATE.hw_notes.append(note)


def _maybe_hw(codec: str, crf: int, meta: Optional[Dict[str, Any]], keep_bt709: bool, cpu: List[str]) -> List[str]:
    """`cpu` unchanged unless --hw / $FFMPEG_SKILL_HW is on and VideoToolbox can take `codec`, or
    unless the build has no CPU encoder for it (_vt_in_place_of); the --hw swap is remembered so
    run() can put the CPU line back if the GPU refuses the job. A build without the CPU encoder
    has no line to put back, so nothing is remembered for it."""
    cpu_encoder = cpu[cpu.index("-c:v") + 1] if "-c:v" in cpu else None
    vt_name = _vt_in_place_of(cpu_encoder)
    if not STATE.hw and vt_name is None:
        return cpu
    vt = _vt_args(codec, crf, meta, keep_bt709)
    if vt is None:
        return cpu
    if vt_name:
        _note_vt_in_place_of(cpu_encoder or "", vt_name)
        return vt
    # a copy: a caller that edits the returned line in place (export.py strips -movflags) must
    # not edit the recorded slice with it, or restate_last_swap() never sees the line as built
    STATE.hw_swaps.append((list(vt), cpu))
    return vt


_CPU_TO_CODEC = {"libx264": "h264", "libx265": "hevc", "prores_ks": "prores"}


def hw_preset_video(video: List[str], meta: Optional[Dict[str, Any]], *, bt709: bool) -> List[str]:
    """export.py's fixed-preset encoder line moved to VideoToolbox (same codec, the preset's -crf
    mapped to -q:v, its -r kept); unchanged -- with the reason noted -- when that cannot apply.
    Called under --hw, and for a preset whose libx264/libx265 this build lacks (_vt_in_place_of),
    where it is the only encoder there is; otherwise it returns `video` untouched.

    `bt709`: whether export.py tags this preset's CPU line BT.709 (every fixed preset but prores,
    whose master keeps the source's tags). The VideoToolbox line writes the format the CPU preset
    writes: an h264/hevc preset is 8-bit with BT.709 tags whatever the source (on an HDR source it
    says so in a note, as without --hw), so it is built as for an SDR source -- not the Main10 HDR
    line, which would make the GPU file and its CPU fallback different formats."""
    enc = video[video.index("-c:v") + 1] if "-c:v" in video else None
    codec = _CPU_TO_CODEC.get(enc or "")
    if codec is None:
        return video
    vt_name = _vt_in_place_of(enc)
    if not STATE.hw and vt_name is None:
        return video
    crf = int(video[video.index("-crf") + 1]) if "-crf" in video else 18
    vt = _vt_args(codec, crf, meta if codec == "prores" else None, bt709)
    if vt is None:
        return video
    vt = strip_movflags(vt)  # export adds it
    if "-r" in video:
        vt += ["-r", video[video.index("-r") + 1]]
    if vt_name:
        _note_vt_in_place_of(enc or "", vt_name)
        return vt
    # the CPU line export would have written: the preset's own options plus the BT.709 tags export
    # adds to it (only to the CPU line), so a GPU->CPU fallback is tagged exactly like a CPU run
    STATE.hw_swaps.append((list(vt), list(video) + (bt709_tag_args(enc) if bt709 else [])))
    return vt


def strip_movflags(args: List[str]) -> List[str]:
    return [a for i, a in enumerate(args) if not (a == "-movflags" or (i and args[i - 1] == "-movflags"))]


def restate_last_swap(before: List[str], after: List[str]) -> None:
    """A caller that edits an encoder line after encoder_args() returned it (export.py strips
    -movflags) restates the recorded swap, so run()'s GPU->CPU fallback still finds the slice."""
    if STATE.hw_swaps and STATE.hw_swaps[-1][0] == before:
        STATE.hw_swaps[-1] = (list(after), strip_movflags(STATE.hw_swaps[-1][1]))


def encoder_args(codec: str, crf: int, preset: str, meta: Optional[Dict[str, Any]] = None, keep_bt709: bool = True) -> List[str]:
    """encoder options for `codec` (_cpu_encoder_args), on VideoToolbox when --hw asks and it can."""
    return _maybe_hw(codec, crf, meta, keep_bt709, _cpu_encoder_args(codec, crf, preset, meta, keep_bt709))


def _cpu_encoder_args(codec: str, crf: int, preset: str, meta: Optional[Dict[str, Any]] = None, keep_bt709: bool = True) -> List[str]:
    """The one place that turns (--codec, --quality, --preset, source) into encoder options.

    h264 -> x264 8-bit BT.709 (refuses HDR: 8-bit H.264 cannot carry it); hevc -> x265, Main10
    with the source's tags for HDR, 8-bit BT.709 otherwise; av1 -> SVT-AV1 (libaom fallback),
    10-bit for HDR; prores -> ProRes 422 HQ, source tags kept. 1.8: chosen by --codec; without
    it video_args() does what it always did (x264 for SDR, x265 Main10 for HDR).
    """
    v = (meta or {}).get("video") or {}
    hdr = bool(v.get("bt2020_or_hdr"))
    cs = v.get("color_space") or "bt2020nc"
    prim = v.get("color_primaries") or "bt2020"
    trc = v.get("color_transfer") or "arib-std-b67"
    hdr_tags = ["-colorspace", cs, "-color_primaries", prim, "-color_trc", trc]
    if codec == "h264":
        if hdr:
            die(f"--codec h264 cannot carry HDR ({v.get('hdr_format') or 'BT.2020'}): 8-bit H.264 is SDR only",
                hint="run color.py --to-sdr first, or use --codec hevc / av1 / prores, which keep the source's HDR")
        return _x264_raw(crf, preset, keep_bt709)
    if codec == "hevc":
        if hdr:
            x265 = f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}:range=limited:hdr10-opt=1" if trc == "smpte2084" else f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}"
            return ["-c:v", "libx265", "-preset", preset, "-crf", str(_clamped_crf("libx265", crf + 2, 51, crf)), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
                    "-x265-params", x265] + hdr_tags + ["-movflags", "+faststart"]
        params, extra = _sdr_bt709("libx265") if keep_bt709 else ("", [])
        return ["-c:v", "libx265", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-x265-params", "log-level=error" + (":" + params if params else "")] + extra + ["-movflags", "+faststart"]
    if codec == "av1":
        pix = "yuv420p10le" if hdr else "yuv420p"
        if "libsvtav1" in ffmpeg_encoders():
            args = ["-c:v", "libsvtav1", "-preset", str(SVT_PRESET.get(preset, 6)), "-crf", str(_clamped_crf("libsvtav1", crf, 63, crf)), "-pix_fmt", pix]
            if hdr:
                args += hdr_tags
            elif keep_bt709:
                params, extra = _sdr_bt709("libsvtav1")
                args += (["-svtav1-params", params] if params else []) + extra
        elif "libaom-av1" in ffmpeg_encoders():
            # recorded: libaom is the slower AV1 encoder with its own CRF scale and speed setting,
            # so the same --quality does not give the file SVT-AV1 would have
            record_fallback("--codec av1: this ffmpeg build has no libsvtav1 (SVT-AV1), so libaom-av1 encodes instead "
                            "(slower; -cpu-used 6, its own CRF scale)", "av1_encoder_libaom", wanted="libsvtav1", used="libaom-av1")
            args = ["-c:v", "libaom-av1", "-crf", str(_clamped_crf("libaom-av1", crf, 63, crf)), "-b:v", "0", "-cpu-used", "6", "-row-mt", "1", "-pix_fmt", pix]
            args += hdr_tags if hdr else (_sdr_bt709("libaom-av1")[1] if keep_bt709 else [])
        else:
            _refuse_missing_encoder("av1", ["libsvtav1", "libaom-av1"], "an AV1 encoder (libsvtav1 or libaom-av1)",
                                    "install an ffmpeg built with SVT-AV1 (most distribution builds are), or use --codec hevc")
        return args + ["-movflags", "+faststart"]
    if codec == "prores":
        if "prores_ks" not in ffmpeg_encoders():
            _refuse_missing_encoder("prores", ["prores_ks"], "the prores_ks encoder", None)
        return ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"] + (hdr_tags if hdr else [])
    die(f"unknown --codec {codec!r} (one of {', '.join(CODECS)})")
    return []


def _clamped_crf(encoder: str, value: int, top: int, requested: int) -> int:
    """`value` capped at the encoder's maximum CRF, the cap recorded (`crf_clamped`) when it
    bites: the HEVC HDR line asks x265 for CRF+2, so --quality 50 or 51 there is encoded at 51."""
    if value <= top:
        return value
    warn(f"{encoder}: CRF {value} (from {requested}) is above the encoder's maximum {top}; encoded at CRF {top}",
         "crf_clamped", encoder=encoder, requested=requested, asked=value, used=top)
    return top


def _refuse_missing_encoder(codec: str, encoders: List[str], what: str, hint: Optional[str]) -> None:
    """--codec av1/prores with no encoder for it -- or with an encoder list that could not be read,
    which proves nothing about the build and is refused under its own reason rather than as a
    missing encoder (ffmpeg_list_error)."""
    unread = ffmpeg_list_error("encoders")
    if unread:
        refuse("ffmpeg", "encoder_list_unreadable",
               f"--codec {codec} needs {what}, and whether this ffmpeg build has one is unknown: its encoder list "
               f"could not be read ({unread})",
               hint="check that ffmpeg runs (python3 scripts/_contract.py doctor), then retry",
               codec=codec, encoders=encoders, error=unread)
    refuse("missing_tool", "encoder_missing", f"--codec {codec} needs {what} and this ffmpeg build has "
           + ("neither" if len(encoders) > 1 else "none"), hint=hint, codec=codec, encoders=encoders)


def _x264_raw(crf: int, preset: str, keep_bt709: bool = True) -> List[str]:
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if keep_bt709:
        args += bt709_tag_args("libx264")
    return args


def x264_args(crf: int = 18, preset: str = "medium", keep_bt709: bool = True,
              source: Optional[Dict[str, Any]] = None) -> List[str]:
    """SDR H.264 encoder args -- or, when --codec named another encoder, that encoder's SDR args
    (color.py's --to-sdr path builds its own H.264 line; the flag still has to reach it).

    `source`: the probe of the file being re-encoded, when the pixels reaching the encoder are
    still that file's. A BT.709-tagged line then carries the conversion of a non-BT.709 matrix
    (bt709_matrix_args); a caller whose graph already outputs BT.709 (--to-sdr) leaves it out."""
    if STATE.codec and STATE.codec != "h264":
        args = encoder_args(STATE.codec, crf, preset, None, keep_bt709)
    else:
        args = _maybe_hw("h264", crf, None, keep_bt709, _x264_raw(crf, preset, keep_bt709))
    return args + (bt709_matrix_args(source) if keep_bt709 and STATE.codec != "prores" else [])


def video_args(meta: Optional[Dict[str, Any]], crf: int = 18, preset: str = "medium", convert_matrix: bool = True,
               source: Optional[Dict[str, Any]] = None) -> List[str]:
    """Encoder args that preserve what the source is.

    SDR sources -> H.264 8-bit tagged BT.709 (x264_args). HDR sources (HDR10/PQ, HLG,
    Dolby Vision base layer, BT.2020) -> HEVC Main10 with the source's own colour tags,
    so cutting/captioning/fitting an iPhone HDR clip stays HDR instead of becoming a
    washed-out file mislabelled as BT.709. Use color.py --to-sdr when SDR is wanted.

    An SDR source tagged with a BT.601 (or another non-BT.709) matrix is converted to BT.709
    before it is tagged so: the line ends with the `-vf` of bt709_matrix_args(), which run()
    folds into the tool's own graph (color.fold_bt709_matrix). `convert_matrix=False` is for a
    tool that mixes several sources and converts each one in its own graph (join, multicam,
    broll, overlay --video). --codec prores keeps the source's tags, so it converts nothing.
    An RGB source (a PNG, an image sequence, a qtrle clip) is converted the same way.

    `source`: the probe of the picture the encoder gets when the line is chosen without it
    (insert.py and sequence.py make a still or a PNG sequence into video on the SDR line,
    video_args(None)); its RGB or BT.601 pixels are converted to the BT.709 that line is tagged with.
    """
    v = (meta or {}).get("video") or {}
    fix = bt709_matrix_args(meta if source is None else source) if convert_matrix and STATE.codec != "prores" else []
    if STATE.codec:
        return encoder_args(STATE.codec, crf, preset, meta) + fix
    if not v.get("bt2020_or_hdr"):
        return x264_args(crf, preset) + fix
    return _maybe_hw("hevc", crf, meta, True, _x265_hdr_default(v, crf, preset))


def matrix_chain(meta: Optional[Dict[str, Any]], line_meta: Optional[Dict[str, Any]]) -> str:
    """For a tool that mixes several sources in one graph and encodes it through
    video_args(line_meta, convert_matrix=False): the conversion one source's own chain starts
    with ("<filter>," -- bt709_matrix_filter), or "" when that source needs none or the line does
    not tag BT.709 (an HDR/BT.2020 line keeps its tags, --codec prores keeps the source's)."""
    if STATE.codec == "prores" or ((line_meta or {}).get("video") or {}).get("bt2020_or_hdr"):
        return ""
    f = bt709_matrix_filter(meta)
    return f + "," if f else ""


def label_chain(meta: Optional[Dict[str, Any]], line_meta: Optional[Dict[str, Any]]) -> str:
    """For a picture that meets a converted one in a mixing filter (a still over the video, a grid
    cell beside a converted cell), encoded through video_args(line_meta): the BT.709 label an
    untagged one's chain starts with ("<setparams>," -- bt709_label_filter), or "" (a tagged, RGB or
    HDR picture, or a line that does not tag BT.709)."""
    if STATE.codec == "prores" or ((line_meta or {}).get("video") or {}).get("bt2020_or_hdr"):
        return ""
    f = bt709_label_filter(meta)
    return f + "," if f else ""


def rgb_chain_to_bt709(line_meta: Optional[Dict[str, Any]], pix_fmt: str = "yuva420p") -> str:
    """For a picture the tool's own graph has made RGB(A) -- a still's `format=rgba` chain
    (overlay.py --image, an emoji PNG) or an RGBA composite (waveform.py's --image plate) -- that
    is encoded through video_args(line_meta): "," + the conversion to BT.709 YUV to end that chain
    with (rgb_to_bt709_filter), or "" when the line does not tag BT.709 (the lines matrix_chain()
    leaves alone). Without it the graph's own RGB-to-YUV step used FFmpeg's BT.601 default."""
    if STATE.codec == "prores" or ((line_meta or {}).get("video") or {}).get("bt2020_or_hdr"):
        return ""
    return "," + rgb_to_bt709_filter(pix_fmt)


def draws_chroma(colours: Sequence[Any], line_meta: Optional[Dict[str, Any]]) -> bool:
    """True when one of `colours` has chroma (is_neutral_color) and the line video_args(line_meta)
    tags the output BT.709 -- when a drawn colour needs drawn_chain() at all."""
    return (not all(is_neutral_color(c) for c in colours if c is not None) and STATE.codec != "prores"
            and not ((line_meta or {}).get("video") or {}).get("bt2020_or_hdr"))


def drawn_chain(colour_chain: str, meta: Optional[Dict[str, Any]], colours: Sequence[Any], neutral_chain: str = "null",
                line_meta: Any = "same", tag: str = "d", labelled: bool = False) -> str:
    """`colour_chain` -- filters that draw a colour into the picture `meta` probes (drawtext's
    font/box/border colours, pad/tpad's fill, rotate's fillcolor, libass) -- so that a colour of
    `colours` lands in the BT.709 the line video_args(line_meta) tags the output with (line_meta
    defaults to meta).

    FFmpeg's drawing filters turn an RGB colour into YUV with a matrix of their own (ff_draw):
    BT.601 always up to 7.0, the link's colourspace from 7.1 on, "unknown" read as BT.601. Through
    2.10.2 a drawn colour was BT.601 under a BT.709 tag on every build (pure red decoded as
    (255,24,0)), and on 5.1/6.1 for a BT.709-tagged source too. From 7.1 an untagged picture gets
    its BT.709 label (label_chain(): tags only) and the filters follow it; before 7.1 the drawing
    runs in RGB (rgb_island(), `neutral_chain` being the same filters with a black fill, or null).

    Unchanged: a chain whose colours are all greys (the same YUV under every matrix: the default
    black pads and white text), a line that does not tag BT.709 (HDR, prores). `labelled`: the
    caller's graph already labels this picture (label_chain()) earlier in the same chain."""
    line = meta if line_meta == "same" else line_meta
    if not draws_chroma(colours, line):
        return colour_chain
    if ffmpeg_version() >= (7, 1):
        return ("" if labelled else label_chain(meta, line)) + colour_chain
    pix_fmt, full = drawn_stream_format(meta)
    return rgb_island(colour_chain, neutral_chain, pix_fmt, full, tag)


def source_codec_video_args(meta: Optional[Dict[str, Any]], crf: int = 18, preset: str = "medium",
                            keep_hevc: bool = False) -> List[str]:
    """video_args(), except that with `keep_hevc` (cut.py --keep-hevc) an SDR HEVC source re-encodes
    to HEVC (8-bit, BT.709-tagged, on VideoToolbox when --hw asks) instead of H.264: a cut is a trim,
    so a re-encoded segment can come out in the codec the source (and any copied segment beside it)
    is in. Opt-in within 2.x, where an SDR re-encode stays x264 unless asked. An HDR or BT.2020
    source always takes video_args()'s Main10 line, and --codec always wins."""
    v = (meta or {}).get("video") or {}
    if keep_hevc and not STATE.codec and v.get("codec") == "hevc" and not v.get("bt2020_or_hdr"):
        return encoder_args("hevc", crf, preset, meta) + bt709_matrix_args(meta)
    return video_args(meta, crf, preset)


def _x265_hdr_default(v: Dict[str, Any], crf: int, preset: str) -> List[str]:
    cs = v.get("color_space") or "bt2020nc"
    prim = v.get("color_primaries") or "bt2020"
    trc = v.get("color_transfer") or "arib-std-b67"
    x265 = f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}:range=limited:hdr10-opt=1" if trc == "smpte2084" else f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}"
    return ["-c:v", "libx265", "-preset", preset, "-crf", str(min(51, crf + 2)), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
            "-x265-params", x265, "-colorspace", cs, "-color_primaries", prim, "-color_trc", trc, "-movflags", "+faststart"]


def aac_args(bitrate: str = "192k") -> List[str]:
    return ["-c:a", "aac", "-b:a", bitrate]


AUDIO_CODECS = {
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
    ".m4a": ["-c:a", "aac", "-b:a", "256k"],
    ".aac": ["-c:a", "aac", "-b:a", "256k"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


def audio_codec_for(output_path: str, default_bitrate: str = "192k") -> List[str]:
    """Pick an audio codec that the output container can actually hold."""
    ext = os.path.splitext(output_path)[1].lower()
    return list(AUDIO_CODECS.get(ext, ["-c:a", "aac", "-b:a", default_bitrate]))


def is_audio_output(output_path: str) -> bool:
    """True when the output extension is an audio-only container (.wav, .flac, .mp3, .m4a, .aac, .ogg, .opus).

    Such a file cannot hold a video stream and, for .wav, cannot hold compressed audio: scripts use
    this to drop the picture (-vn) and to pick the codec from the extension instead of AAC.
    """
    return os.path.splitext(output_path)[1].lower() in AUDIO_CODECS


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


BRAND_DEFAULTS: Dict[str, Any] = {
    "font": "DejaVu Sans",
    "font_file": None,
    "colors": {"primary": "FFD200", "text": "FFFFFF", "outline": "000000", "background": "101418", "accent": "1E6F8E"},
    "logo": None,
    "logo_position": "top-right",
    "logo_scale": 160,
    "logo_opacity": 0.9,
    "safe_margin": 48,
    "caption": {"size": 26, "position": "bottom", "animate": "pop", "karaoke": False, "bold": True, "outline": 2},
    # 1.12: one place for the caption look every project shares. `styles.caption` is the documented
    # spelling (`{font, size, colour, box, position}`, British or American "colour"); the older
    # top-level `caption` block still works and `styles.caption` wins where both name the same key.
    "styles": {},
    "lang": None,
    "loudness": {"lufs": -14, "tp": -1},
}


def load_brand(path: Optional[str]) -> Dict[str, Any]:
    """Load brand.json (fonts, colours, logo, safe margins, caption defaults); missing keys fall back to defaults."""
    import copy
    brand = copy.deepcopy(BRAND_DEFAULTS)
    brand["_stated"] = {}
    if not path:
        return brand
    if not os.path.exists(path):
        die(f"brand file not found: {path}")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        die(f"brand file is not valid JSON: {exc}")
    base = Path(path).resolve().parent
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(brand.get(k), dict):
            brand[k].update(v)
        else:
            brand[k] = v
    for key in ("logo", "font_file"):
        if brand.get(key) and not os.path.isabs(brand[key]):
            brand[key] = str(base / brand[key])
    brand["_path"] = str(path)
    # What the FILE said, separate from BRAND_DEFAULTS' filler: a brand.json that never mentions
    # a font must not read as "the caller chose a font" (which would switch font-by-script off).
    brand["_stated"] = data
    return brand


def brand_states_font(brand: Dict[str, Any]) -> bool:
    """Did the brand FILE actually name a font (top-level `font`, `caption.font` or
    `styles.caption.font`)? BRAND_DEFAULTS always supplies one, so the merged document can never
    answer this -- and treating the default filler as the caller's choice switched font-by-script
    off for every branded job (review 10)."""
    stated = brand.get("_stated") or {}
    if stated.get("font"):
        return True
    for block in (stated.get("caption"), (stated.get("styles") or {}).get("caption")):
        if isinstance(block, dict) and block.get("font"):
            return True
    return False


def brand_caption_style(brand: Dict[str, Any]) -> Dict[str, Any]:
    """The effective caption style of a brand file: the top-level `caption` block updated with
    `styles.caption`, with `colour` normalised to `color`. Explicit flags still beat both."""
    style: Dict[str, Any] = dict(brand.get("caption") or {})
    extra = (brand.get("styles") or {}).get("caption") or {}
    style.update(extra)
    if "colour" in style and "color" not in style:
        style["color"] = style.pop("colour")
    style.pop("colour", None)
    return style


# ------------------------------------------------------------------- chapter proposal (1.16)

def fmt_chapter_time(t: float) -> str:
    """The YouTube description convention: `00:00`, `03:12`, `1:02:03` past the hour, always
    rounded DOWN to the second so the timestamp never lands after the moment it names."""
    total = max(0, int(t))
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _evidence_rank(ev: Dict[str, Any]) -> tuple:
    """How strong a candidate is, for the drop order: both detectors beat a silence, a silence
    beats a scene cut, and within a kind the longer pause / higher score wins."""
    kind = ev.get("kind")
    tier = {"start": 3, "silence+scene": 2, "silence": 1, "scene": 0}.get(kind, 0)
    within = float(ev.get("silence_length") or ev.get("score") or 0.0)
    return (tier, within)


def propose_chapters(duration: float, silences: "Sequence", scene_cuts: "Sequence", *,
                     min_chapter: float = 60.0, max_chapters: int = 0,
                     source: str = "both") -> "List[Dict[str, Any]]":
    """Chapter markers proposed from measured structure. Pure: the detectors' outputs go in,
    a list of `{"at", "title", "evidence"}` comes out, and nothing is decoded here.

    A chapter starts where speech RESUMES, so a silence contributes its `end`, not its midpoint.
    A scene cut within 1 s of such a point is the same event seen twice and is merged into one
    candidate with `kind: "silence+scene"`, which the `--max-chapters` cap never drops before a
    single-evidence one. Candidates closer than `min_chapter` to the one already kept are dropped,
    stronger evidence winning; so is anything inside `min_chapter` of the end of the file.

    Every title is `Chapter N`. The function never looks at, and never invents, content: naming a
    chapter needs knowing what is said in it, which is the calling agent's job, not this skill's.
    """
    duration = float(duration or 0.0)
    min_chapter = max(0.0, float(min_chapter))
    candidates: "List[Dict[str, Any]]" = []
    if source in ("silence", "both"):
        for span in silences or []:
            start, end = float(span[0]), span[1]
            if end is None or end == float("inf"):
                continue
            end = float(end)
            candidates.append({"at": end, "evidence": {
                "kind": "silence", "silence": [round(start, 3), round(end, 3)],
                "silence_length": round(end - start, 3)}})
    if source in ("scenes", "both"):
        for cut in scene_cuts or []:
            cut = float(cut)
            if cut <= 0.0:
                continue     # scenes.py always reports 0.0 as the first cut; that is the start
            candidates.append({"at": cut, "evidence": {"kind": "scene", "scene_at": round(cut, 3)}})

    # merge a scene cut that stands within 1 s of a silence end: one event, two witnesses
    candidates.sort(key=lambda c: c["at"])
    merged: "List[Dict[str, Any]]" = []
    for cand in candidates:
        prior = merged[-1] if merged else None
        if prior and abs(cand["at"] - prior["at"]) <= 1.0 and \
                {prior["evidence"]["kind"], cand["evidence"]["kind"]} == {"silence", "scene"}:
            ev = dict(prior["evidence"])
            ev.update(cand["evidence"])
            ev["kind"] = "silence+scene"
            silence_first = prior["evidence"]["kind"] == "silence"
            prior["at"] = prior["at"] if silence_first else cand["at"]
            prior["evidence"] = ev
            continue
        merged.append(dict(cand))

    kept: "List[Dict[str, Any]]" = [{"at": 0.0, "evidence": {"kind": "start"}}]
    for cand in merged:
        if duration and cand["at"] >= duration - min_chapter:
            continue
        last = kept[-1]
        if cand["at"] - last["at"] < min_chapter:
            # too close to the marker already kept: keep whichever the evidence supports better,
            # never replacing the 0.0 start
            if last["evidence"]["kind"] != "start" and \
                    _evidence_rank(cand["evidence"]) > _evidence_rank(last["evidence"]) and \
                    (len(kept) < 2 or cand["at"] - kept[-2]["at"] >= min_chapter):
                kept[-1] = dict(cand)
            continue
        kept.append(dict(cand))

    if max_chapters and len(kept) > max_chapters:
        # drop the weakest evidence first, never index 0, then put the survivors back in order
        order = sorted(range(1, len(kept)),
                       key=lambda i: (_evidence_rank(kept[i]["evidence"]), -kept[i]["at"]))
        drop = set(order[:len(kept) - max_chapters])
        kept = [c for i, c in enumerate(kept) if i not in drop]

    for n, chapter in enumerate(kept, start=1):
        chapter["at"] = round(chapter["at"], 3)
        chapter["title"] = f"Chapter {n}"
    return kept


def description_block(chapters: "Sequence") -> str:
    """The YouTube description form of a chapter list: `00:00 Chapter 1` per line."""
    return "\n".join(f"{fmt_chapter_time(c['at'])} {c['title']}" for c in chapters)


# ------------------------------------------------------------------ the beat grid (1.17)
#
# A beat grid is a measurement of the music's periodicity -- not a statement about where a cut
# belongs. Everything here is arithmetic on an RMS envelope somebody else decoded; nothing in this
# module decides to cut anything, and nothing invents a beat the audio does not support.

BEAT_ONSET_K = 1.5          # peak threshold: median + k * MAD over the local window
BEAT_WINDOW_S = 1.0         # +/- this many seconds is "local" for the threshold
BEAT_REFRACTORY_S = 0.06    # two onsets closer than this are one onset
BEAT_SUPPORT_DIVISOR = 4    # a grid point with no onset within interval/4 is "unsupported"
BEAT_ALIGN_DIVISOR = 8      # an onset within interval/8 of a grid point counts as aligned
BEAT_MIN_CONFIDENCE = 0.5   # the default below which a tool that CHANGES a file refuses to snap
BEAT_OCTAVE_MARGIN = 1.2    # a half/double-tempo grid must explain this much more onset strength
BEAT_Z_FLOOR = 2.0          # autocorrelation z-score at which periodicity starts counting
BEAT_Z_SPAN = 4.0           # ... and the span over which it reaches 1.0


def _onset_strength(envelope: "Sequence[float]") -> "List[float]":
    """Half-wave-rectified first difference of log(env), i.e. a compression-domain spectral-flux
    analogue. The log matters: the level-domain difference over-weights the loud sections, so a
    quiet verse contributes no onsets at all and the tempo is measured on the chorus alone."""
    import math as _math
    log_env = [_math.log(max(0.0, float(e)) + 1e-9) for e in envelope]
    return [0.0] + [max(0.0, log_env[i] - log_env[i - 1]) for i in range(1, len(log_env))]


def _pick_onsets(strength: "Sequence[float]", step_s: float) -> "List[int]":
    """Indices of local maxima above median + k*MAD over a +/-BEAT_WINDOW_S window, with a
    refractory gap. A median/MAD threshold rather than a mean/stdev one because a handful of very
    strong hits would drag a mean-based threshold above every other onset in the piece."""
    n = len(strength)
    if n < 3:
        return []
    half = max(1, int(round(BEAT_WINDOW_S / max(step_s, 1e-9))))
    refractory = max(1, int(round(BEAT_REFRACTORY_S / max(step_s, 1e-9))))
    picked: "List[int]" = []
    for i in range(1, n - 1):
        s = strength[i]
        if s <= 0 or s < strength[i - 1] or s < strength[i + 1]:
            continue
        window = sorted(strength[max(0, i - half):min(n, i + half + 1)])
        if not window:
            continue
        med = window[len(window) // 2]
        devs = sorted(abs(x - med) for x in window)
        mad = devs[len(devs) // 2]
        if s < med + BEAT_ONSET_K * mad or s <= med:
            continue
        if picked and i - picked[-1] < refractory:
            if s > strength[picked[-1]]:
                picked[-1] = i
            continue
        picked.append(i)
    return picked


def _autocorrelation_peak(strength: "Sequence[float]", step_s: float,
                          bpm_range: "Sequence[float]") -> "tuple":
    """(best lag in samples, peak, mean, standard deviation) of the onset signal's
    autocorrelation over the lags `bpm_range` allows, or (None, 0.0, 0.0, 0.0).

    The spread matters as much as the peak: every signal's autocorrelation has a maximum
    somewhere, so "the peak is above the mean" says nothing. How far above it stands relative to
    the spread of the other lags is what separates a pulse from noise.
    """
    n = len(strength)
    hi_bpm, lo_bpm = max(bpm_range), min(bpm_range)
    lag_min = max(1, int(round(60.0 / hi_bpm / max(step_s, 1e-9))))
    lag_max = int(round(60.0 / lo_bpm / max(step_s, 1e-9)))
    lag_max = min(lag_max, n - 1)
    if lag_max < lag_min:
        return (None, 0.0, 0.0, 0.0)
    mean = sum(strength) / n if n else 0.0
    centred = [s - mean for s in strength]
    best_lag, best = None, 0.0
    values = []
    for lag in range(lag_min, lag_max + 1):
        acc = sum(centred[i] * centred[i + lag] for i in range(n - lag))
        acc /= (n - lag)
        values.append(acc)
        if best_lag is None or acc > best:
            best_lag, best = lag, acc
    mean_acc = sum(values) / len(values) if values else 0.0
    var = sum((v - mean_acc) ** 2 for v in values) / len(values) if values else 0.0
    return (best_lag, best, mean_acc, math.sqrt(var))


def _grid_score(onset_times: "Sequence[float]", strength_at: "Dict[int, float]",
                interval: float, phase: float) -> float:
    """Total onset strength landing within interval/BEAT_ALIGN_DIVISOR of the grid."""
    if interval <= 0:
        return 0.0
    tol = interval / BEAT_ALIGN_DIVISOR
    total = 0.0
    for i, t in enumerate(onset_times):
        off = (t - phase) % interval
        if min(off, interval - off) <= tol:
            total += strength_at.get(i, 1.0)
    return total


def beat_grid(envelope: "Sequence[float]", step_s: float, *,
              bpm_range: "Sequence[float]" = (60, 200),
              min_confidence: float = BEAT_MIN_CONFIDENCE,
              duration: "Optional[float]" = None) -> "Dict[str, Any]":
    """A beat grid from an RMS envelope. Pure: numbers in, a dict out -- no ffmpeg, no I/O.

    Returns {"beats": [t, ...], "tempo_bpm": float|None, "interval": float|None,
             "confidence": 0..1, "onsets": [t, ...], "phase": float,
             "supported": int, "unsupported": int, "usable": bool,
             "method": "rms-flux-autocorrelation", "step_s": step_s, "range_bpm": [lo, hi]}

    The method, in full, so a report can quote it:
      1. onset strength = half-wave-rectified first difference of log(env + 1e-9);
      2. onsets = local maxima above median + 1.5 * MAD over a +/-1 s window, 60 ms refractory;
      3. tempo = the best autocorrelation lag of the onset signal inside `bpm_range`, with its
         half and double checked and the one whose onsets align better preferred (octave
         disambiguation: 60, 120 and 240 BPM all autocorrelate on a 120 BPM track);
      4. phase = the offset in [0, interval) at which the grid catches the most onset strength;
      5. beats = phase + n * interval across the duration. A grid must be regular, so a grid
         point with no measured onset within interval/4 is still reported -- and counted in
         `unsupported`, so a caller can see how much of the grid the audio actually supports.
         `supported_beats` is the subset that a measured onset does support: it is what a tool
         that MOVES something must snap to, because a regular grid runs on through a passage with
         no music in it and a point moved there was moved to a time nothing in the audio marks;
      6. confidence = 0.5 * clip((z - 2) / 4, 0, 1)
                    + 0.5 * (fraction of onsets within interval/8 of a grid point),
         where z is how many standard deviations the winning autocorrelation lag stands above
         the mean of the others. The plain peak/mean ratio is not used: every signal's
         autocorrelation has a maximum somewhere, so a peak above the mean says nothing -- noise
         scores 2.9 on it, which would read as full confidence.

    A flat or empty envelope has no pulse: confidence 0.0, tempo None, beats []. That is a
    measurement, not a failure -- the caller decides whether 0.0 is enough to act on.
    """
    step_s = float(step_s)
    env = list(envelope or [])
    lo_bpm, hi_bpm = float(min(bpm_range)), float(max(bpm_range))
    out: "Dict[str, Any]" = {
        "beats": [], "supported_beats": [], "tempo_bpm": None, "interval": None,
        "confidence": 0.0, "onsets": [],
        "phase": 0.0, "supported": 0, "unsupported": 0, "usable": False,
        "method": "rms-flux-autocorrelation", "step_s": step_s, "range_bpm": [lo_bpm, hi_bpm],
    }
    if len(env) < 4 or step_s <= 0:
        return out
    total_s = float(duration) if duration else len(env) * step_s

    strength = _onset_strength(env)
    if not any(strength):
        return out
    idx = _pick_onsets(strength, step_s)
    onset_times = [i * step_s for i in idx]
    out["onsets"] = [round(t, 4) for t in onset_times]
    if len(idx) < 2:
        return out

    best_lag, peak, mean_acc, sd_acc = _autocorrelation_peak(strength, step_s, (lo_bpm, hi_bpm))
    if not best_lag or peak <= 0:
        return out
    interval = best_lag * step_s
    strength_at = {i: strength[j] for i, j in enumerate(idx)}

    # Octave disambiguation: try half and double the candidate interval and keep the one whose
    # grid catches the most onset strength per grid point (per point, or a denser grid always wins).
    candidates = [interval]
    for factor in (0.5, 2.0):
        alt = interval * factor
        if 60.0 / hi_bpm <= alt <= 60.0 / lo_bpm:
            candidates.append(alt)

    def best_phase(iv: float) -> "tuple":
        steps = max(4, int(round(iv / step_s)))
        best_ph, best_sc = 0.0, -1.0
        for k in range(steps):
            ph = k * iv / steps
            sc = _grid_score(onset_times, strength_at, iv, ph)
            if sc > best_sc:
                best_ph, best_sc = ph, sc
        return best_ph, best_sc

    # The winner is the grid that explains the most measured onset strength -- "more onsets fall
    # on it", the standard octave rule. An alternative must explain appreciably more (a fifth
    # again) to displace the autocorrelation's own answer: a half-tempo grid catches a subset of
    # the same onsets and a double-tempo grid catches the same set plus empty points, so a bare
    # ">" would flip the answer on noise.
    base_phase, base_score = best_phase(interval)
    interval, phase = interval, base_phase
    for alt in candidates[1:]:
        alt_phase, alt_score = best_phase(alt)
        if alt_score > base_score * BEAT_OCTAVE_MARGIN:
            interval, phase, base_score = alt, alt_phase, alt_score

    beats = []
    t = phase
    while t <= total_s + 1e-9:
        beats.append(round(t, 4))
        t += interval
    support_tol = interval / BEAT_SUPPORT_DIVISOR
    supported_beats = [b for b in beats
                       if any(abs(b - o) <= support_tol for o in onset_times)]
    supported = len(supported_beats)
    align_tol = interval / BEAT_ALIGN_DIVISOR
    aligned = sum(1 for o in onset_times
                  if min((o - phase) % interval, interval - (o - phase) % interval) <= align_tol)

    # How many spreads the best lag stands above the rest of them, mapped onto [0, 1]: a click
    # track measures z ~= 6, a jittery human performance ~= 5, pseudo-random levels ~= 2.4, so
    # the band [BEAT_Z_FLOOR, BEAT_Z_FLOOR + BEAT_Z_SPAN] = [2, 6] is where the answer changes.
    z = ((peak - mean_acc) / sd_acc) if sd_acc > 0 else 0.0
    periodicity = max(0.0, min(1.0, (z - BEAT_Z_FLOOR) / BEAT_Z_SPAN))
    alignment = aligned / len(onset_times) if onset_times else 0.0
    confidence = round(0.5 * periodicity + 0.5 * alignment, 3)

    out.update({
        "beats": beats, "supported_beats": supported_beats,
        "interval": round(interval, 6), "tempo_bpm": round(60.0 / interval, 2),
        "phase": round(phase, 4), "confidence": confidence, "supported": supported,
        "unsupported": len(beats) - supported,
        "usable": confidence >= float(min_confidence),
    })
    return out


def snap_points(points: "Sequence[float]", beats: "Sequence[float]",
                tolerance: float) -> "List[Dict[str, Any]]":
    """Move each given point to the nearest beat within `tolerance` seconds.

    Pure. Returns [{"from": t, "to": t2, "delta": d, "snapped": bool, "beat_index": i|None}].
    A point with no beat inside `tolerance` is returned unchanged with snapped=False.

    NEVER invents a point: len(out) == len(points), always, and every `to` is either a value that
    was in `beats` or the caller's own `from`. This is the whole no-fabrication rule for beat
    snapping -- a cut point may move to a measured grid point, and may not appear from one.
    """
    grid = sorted(float(b) for b in (beats or []))
    out: "List[Dict[str, Any]]" = []
    for p in points:
        p = float(p)
        best_i, best_d = None, None
        for i, b in enumerate(grid):
            d = abs(b - p)
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        if best_i is not None and best_d is not None and best_d <= float(tolerance):
            out.append({"from": p, "to": grid[best_i], "delta": round(grid[best_i] - p, 6),
                        "snapped": True, "beat_index": best_i})
        else:
            out.append({"from": p, "to": p, "delta": 0.0, "snapped": False, "beat_index": None})
    return out


# ------------------------------------------------------------- filler words (1.17)
#
# A filler word is removed only when a speech engine measured a start/end pair for it. There is no
# heuristic fallback -- no "cut the 0.3 s blips that look like an 'um'", no language guess from the
# filename. Without timings there is nothing to cut, and the tool says so.
#
# What is NOT in these lists is the substance of the decision. "like", "tipo" and "cioè" are
# discourse markers, not disfluencies: they are grammatical words in most sentences, and removing
# them cuts meaning rather than noise. That is a judgement about content, which this skill does not
# make. They are reachable with --filler-extra, and documented as what they are.
FILLER_WORDS = {
    "en": frozenset({"um", "uh", "erm", "hmm", "mm", "mhm", "er", "ah"}),
    # なんか is the most common Japanese filler AND a pronoun/adverb spelled identically. It is in the
    # default list because leaving it out makes --filler useless for Japanese, and every run that
    # removes one warns that it is often a content word (--filler-keep なんか takes it out).
    "ja": frozenset({"えー", "えーと", "えっと", "あの", "あのー", "その", "そのー", "まあ", "なんか"}),
    "es": frozenset({"eh", "este", "esto", "mmm"}),
    "de": frozenset({"äh", "ähm", "hm"}),
    "fr": frozenset({"euh", "hein"}),
    "pt": frozenset({"é", "hum"}),
    "it": frozenset({"ehm"}),
    # 2.19: Korean is written with spaces, so a whisper word is a word and the list works as the
    # English one does. 그/저/뭐/이제 are fillers as often as they are "that"/"I"/"what"/"now":
    # discourse markers below, not defaults.
    "ko": frozenset({"음", "으음", "음음", "어", "어어", "에", "흠"}),
    # Chinese has no spaces: these match only as a whole token with a boundary on each side
    # (filler_spans), so the 额 of 金额 or the 呃 inside a word is never cut. 额 itself is left
    # out: it is a common character in its own right.
    "zh": frozenset({"嗯", "嗯嗯", "呃", "呃呃", "唔"}),
    "ru": frozenset({"э", "ээ", "эм", "эмм", "мм", "хм"}),
    "nl": frozenset({"eh", "ehm", "uh", "uhm", "hm"}),
    "pl": frozenset({"yyy", "yy", "eee", "ee", "em", "emm", "hmm"}),
    "tr": frozenset({"ıı", "ııı", "ee", "eee", "hmm"}),
}

# Words in a default list that are also ordinary vocabulary: every run that removes one says so.
FILLER_AMBIGUOUS = {
    "ja": frozenset({"なんか", "あの", "その", "まあ"}),
    "es": frozenset({"este", "esto"}),
    "pt": frozenset({"é"}),
}

# Discourse markers people ask for by name. Not defaults; named here so --help and the docs can
# say what adding one costs.
FILLER_DISCOURSE_MARKERS = {
    "en": ("like", "you know"),
    "pt": ("tipo",),
    "it": ("cioè",),
    "ko": ("그", "저", "뭐", "이제", "약간", "막", "그니까"),
    "zh": ("那个", "这个", "就是", "然后"),
    "ru": ("ну", "типа", "короче", "как бы"),
    "nl": ("nou", "dus", "zeg maar"),
    "pl": ("no", "jakby", "wiesz", "znaczy"),
    "tr": ("şey", "yani", "işte"),
}

FILLER_MAX_WORD = 1.2   # a longer "uhhh" is a held vowel someone meant
FILLER_MIN_GAP = 0.05   # spans closer than this become one span
FILLER_PAD = 0.02       # trimmed either side of the word
FILLER_MAX_TOKENS = 4   # a listed word may span this many engine tokens ("えー" + "と", "you" + "know")
FILLER_BOUNDARY_GAP = 0.1  # a pause this long between two tokens is a word boundary


def _unspaced_script(text: str) -> bool:
    """True when `text` has a character of a script written without spaces between words (Han,
    kana, Thai, Lao, Myanmar, Khmer). Whisper splits those languages into tokens, not words, so a
    token boundary there says nothing about a word boundary. Hangul is spaced and not listed."""
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F   # kana
                or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF  # Han
                or 0x20000 <= o <= 0x323AF  # Han extensions B-H
                or 0x0E00 <= o <= 0x0EFF or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF):  # Thai, Lao, Myanmar, Khmer
            return True
    return False


def normalise_filler_token(word: str) -> str:
    """A spoken token stripped to what a word list can be compared against: case-folded, with
    surrounding punctuation and whitespace removed. Never a substring match -- "umbrella" must
    survive a list containing "um"."""
    import unicodedata as _ud
    text = str(word or "").strip()
    text = "".join(ch for ch in text
                   if not _ud.category(ch).startswith("P") or ch in "-'’")
    return text.strip("-'’").casefold()


def filler_spans(words, wordlist, *, pad: float = FILLER_PAD, min_gap: float = FILLER_MIN_GAP,
                 max_word: float = FILLER_MAX_WORD, stats: "Optional[Dict[str, int]]" = None) -> "List[Dict[str, Any]]":
    """Time spans to remove, from measured word timings. Pure: no subprocess, no I/O.

    `words` is [{"word", "start", "end"}] as whisper emits. A run of up to FILLER_MAX_TOKENS
    consecutive entries is removed only when the run, joined with or without spaces and
    normalised, is in `wordlist` AND every entry carries a real start < end pair AND the run is
    <= max_word long. The longest run wins. Adjacent spans closer than min_gap merge. Returns
    [{"start", "end", "word"}] sorted and non-overlapping.

    Whisper splits Chinese, Japanese and Thai into tokens rather than words ("えーと" arrives as
    "えー" + "と", "金额" as "金" + "额"), so a run in such a script also needs a word boundary on
    each side: the start or end of the transcript, punctuation, a spaced-script neighbour, or a
    pause of FILLER_BOUNDARY_GAP. Without one the run is part of a longer word and is kept.

    `stats`, when given, receives the listed words that were kept anyway, so the caller can say
    so: `matched_untimed` (no usable start < end: nothing to cut on) and `matched_too_long`
    (longer than max_word: a held vowel someone meant).
    """
    import unicodedata as _ud
    listed = {normalise_filler_token(w) for w in (wordlist or set())}
    listed.discard("")
    toks = []
    for entry in words or []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("word") or entry.get("text") or "").strip()
        try:
            start, end = float(entry["start"]), float(entry["end"])
            timed = end > start
        except (KeyError, TypeError, ValueError):
            start = end = 0.0
            timed = False
        toks.append({"norm": normalise_filler_token(raw), "start": start, "end": end, "timed": timed,
                     "punct_before": bool(raw) and _ud.category(raw[0]).startswith("P"),
                     "punct_after": bool(raw) and _ud.category(raw[-1]).startswith("P")})

    def _bounded(i: int, j: int) -> bool:
        """A word boundary before toks[i] and after toks[j - 1]."""
        left = (i == 0 or toks[i]["punct_before"] or toks[i - 1]["punct_after"] or not toks[i - 1]["norm"]
                or not _unspaced_script(toks[i - 1]["norm"])
                or (toks[i - 1]["timed"] and toks[i]["start"] - toks[i - 1]["end"] >= FILLER_BOUNDARY_GAP - 1e-6))
        right = (j == len(toks) or toks[j - 1]["punct_after"] or toks[j]["punct_before"] or not toks[j]["norm"]
                 or not _unspaced_script(toks[j]["norm"])
                 or (toks[j]["timed"] and toks[j]["start"] - toks[j - 1]["end"] >= FILLER_BOUNDARY_GAP - 1e-6))
        return left and right

    hits = []
    untimed = too_long = 0
    i = 0
    while i < len(toks):
        found = 0
        rejected = None
        for k in range(min(FILLER_MAX_TOKENS, len(toks) - i), 0, -1):
            run = toks[i:i + k]
            norms = [t["norm"] for t in run]
            if not all(norms):
                continue
            unspaced = any(_unspaced_script(n) for n in norms)
            joined = ("" if unspaced else " ").join(norms)
            if joined not in listed or (unspaced and not _bounded(i, i + k)):
                continue
            # punctuation inside the run ("えー、" + "と") ends the word: the shorter run decides
            if any(run[m]["punct_after"] or run[m + 1]["punct_before"] for m in range(k - 1)):
                continue
            # so does a pause inside an unspaced run: the tokens were two words
            if unspaced and any(run[m]["timed"] and run[m + 1]["timed"]
                                and run[m + 1]["start"] - run[m]["end"] >= FILLER_BOUNDARY_GAP - 1e-6
                                for m in range(k - 1)):
                continue
            # a run listed out of time order has no span to cut on
            if not all(t["timed"] for t in run) or run[-1]["end"] <= run[0]["start"]:
                rejected = rejected or ("untimed", k)
                continue
            if run[-1]["end"] - run[0]["start"] > max_word:
                rejected = rejected or ("too_long", k)
                continue
            hits.append({"start": max(0.0, run[0]["start"] - pad), "end": run[-1]["end"] + pad, "word": joined})
            found = k
            break
        if not found and rejected:
            # the longest listed run that could not be cut is the one reported; a shorter listed
            # word inside it that could be cut was tried first
            untimed += rejected[0] == "untimed"
            too_long += rejected[0] == "too_long"
            found = rejected[1]
        i += found or 1
    hits.sort(key=lambda h: (h["start"], h["end"]))
    merged: "List[Dict[str, Any]]" = []
    for h in hits:
        if merged and h["start"] - merged[-1]["end"] <= min_gap:
            merged[-1]["end"] = max(merged[-1]["end"], h["end"])
            merged[-1]["word"] = merged[-1]["word"] + " " + h["word"]
        else:
            merged.append(dict(h))
    for m in merged:
        m["start"] = round(m["start"], 4)
        m["end"] = round(m["end"], 4)
    if stats is not None:
        stats["matched_untimed"] = untimed
        stats["matched_too_long"] = too_long
    return merged


# --- 1.18.0: lightweight block-matching motion estimate (scenes.py --shots, cropdetect.py
# --motion-centre) ---------------------------------------------------------------------------

MOTION_GRID = 4          # NxN anchor blocks per frame
MOTION_SEARCH = 3         # +/- pixels searched per block, at the decoded (low) resolution
MOTION_STATIC_PX = 0.35   # average per-frame displacement below this, at decode resolution, is "static"
MOTION_PAN_SPREAD = 0.6   # block-to-block direction agreement above this (0..1) reads as a pan


def _block_match(prev: bytes, cur: bytes, w: int, h: int, cx: int, cy: int, half: int, search: int) -> "Tuple[float, float]":
    """(dx, dy) that best aligns a `half*2` square centred at (cx, cy) in `prev` to `cur`,
    searched over +/- `search` px by sum-of-absolute-differences. Coordinates and the returned
    offset are in decoded-frame pixels (a handful of pixels a side at 1.18.0's sample size)."""
    x0, y0 = max(half, min(w - half - 1, cx)), max(half, min(h - half - 1, cy))
    ref = [prev[(y0 + dy) * w + (x0 + dx)] for dy in range(-half, half + 1) for dx in range(-half, half + 1)]

    def sad_at(xx: int, yy: int) -> "Optional[int]":
        if xx - half < 0 or xx + half >= w or yy - half < 0 or yy + half >= h:
            return None
        sad = 0
        for dy in range(-half, half + 1):
            row = (yy + dy) * w
            for dx in range(-half, half + 1):
                sad += abs(ref[(dy + half) * (2 * half + 1) + (dx + half)] - cur[row + xx + dx])
        return sad

    # Zero shift is the tie-break candidate, not the search order's first cell: on a textureless
    # block (a flat colour, sky, an out-of-focus background) every offset scores the same SAD, and
    # without an explicit tie towards "no motion" the scan used to report the search window's
    # first corner as the measured displacement -- a still frame with nothing to match against
    # read as steady motion in one direction, every time.
    best_sad, best = sad_at(x0, y0), (0.0, 0.0)
    if best_sad is None:
        best_sad = float("inf")
    for sy in range(-search, search + 1):
        for sx in range(-search, search + 1):
            if sx == 0 and sy == 0:
                continue
            sad = sad_at(x0 + sx, y0 + sy)
            if sad is not None and sad < best_sad:
                best_sad, best = sad, (float(sx), float(sy))
    return best


def frame_flow(prev: bytes, cur: bytes, w: int, h: int, *, grid: int = MOTION_GRID,
               search: int = MOTION_SEARCH) -> "Dict[str, Any]":
    """One measurement between two consecutive decoded grayscale frames: the mean block
    displacement vector, its magnitude, and how consistently the blocks agree on direction
    (0 = every block moved a different way, 1 = every block agrees -- a pan or dolly moves the
    whole frame one way, on-screen motion inside a mostly-static frame does not)."""
    half = max(1, min(w, h) // (grid * 3))
    vecs: "List[Tuple[float, float]]" = []
    for gy in range(grid):
        for gx in range(grid):
            cx = int((gx + 0.5) * w / grid)
            cy = int((gy + 0.5) * h / grid)
            vecs.append(_block_match(prev, cur, w, h, cx, cy, half, search))
    mdx = sum(v[0] for v in vecs) / len(vecs)
    mdy = sum(v[1] for v in vecs) / len(vecs)
    magnitude = math.hypot(mdx, mdy)
    mean_len = sum(math.hypot(*v) for v in vecs) / len(vecs)
    agreement = (magnitude / mean_len) if mean_len > 1e-6 else 1.0  # 1.0 = every block agrees
    return {"dx": mdx, "dy": mdy, "magnitude": magnitude, "agreement": min(1.0, agreement)}


def label_shot_flow(flows: "Sequence[Dict[str, Any]]") -> "Dict[str, Any]":
    """{label, flow_magnitude} for one shot from its per-frame-pair flow measurements.

    static: mean displacement below MOTION_STATIC_PX. pan: above it, and blocks agree on
    direction (a camera move shifts the whole frame). motion: above it, blocks disagree (motion
    inside an otherwise still frame -- handheld jitter, or a subject moving across a static
    background). This is a measured proxy, the same spirit as scenes.py --rank-by: it reports
    what a coarse block match saw, not what is interesting about the shot."""
    if not flows:
        return {"label": "static", "flow_magnitude": 0.0}
    magnitude = sum(f["magnitude"] for f in flows) / len(flows)
    agreement = sum(f["agreement"] for f in flows) / len(flows)
    if magnitude < MOTION_STATIC_PX:
        label = "static"
    elif agreement >= MOTION_PAN_SPREAD:
        label = "pan"
    else:
        label = "motion"
    return {"label": label, "flow_magnitude": round(magnitude, 3)}
