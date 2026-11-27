#!/usr/bin/env python3
"""Fit a video to a target duration and/or aspect ratio.

Duration: --duration N with --method speed (retime video+audio, pitch-preserving
via atempo chaining) or --method trim (keep the first N seconds, or a centred
window with --from-center). A duration alone allows a small retime. Beyond
1.15x in either direction, choose --method speed, --method trim, or an explicit
slow-motion filter. A large retime reports large_speed_change with the factor.
Aspect: --aspect 16:9|9:16|1:1|4:5|W:H with
--fit pad (letterbox/pillarbox with --pad-color, default black, or --pad-fill blur\nfor a blurred copy of the frame behind the picture), --fit crop, or --fit blur\n(the whole picture centred on a blurred, darkened copy of itself -- nothing\ncropped, no black bars).
--width and/or --height set the output size: give one and the other follows
the aspect (source aspect if --aspect is not also given); give both for an
exact frame. --rotate 90|180|270 (clockwise) and --flip h|v apply a new
rotation/mirror to the picture -- distinct from the rotation metadata a
source already carries (read automatically to compute the displayed size,
never altered by these flags unless asked). Both can be combined; rotate is
applied before flip.

Crop keeps the centre of the frame by default, which is a guess: going from
16:9 to 9:16 throws away most of the width, and whatever isn't in the middle
third (a person at the edge, a product held to one side) is cut off. Say what
to keep with --crop-x / --crop-y (0=left/top, 0.5=centre, 1=right/bottom, or
a decimal in between) rather than accepting the default silently when the
subject isn't centred; --fit pad never loses anything if you don't know yet.
After a real --fit crop that cuts something away, the result's crop_check
measures where the source's luma motion (in a still shot, its edge detail)
sits against the kept window: a proxy sampled at 9 points, not subject
detection. A crop_content_off_centre warning names --crop-x/--crop-y with a
suggested value, or --fit pad / --fit blur, when most of it is cut away.
Advisory only: the output and the exit status are unchanged.

--zoom in|out: a timed linear push-in/pull-out of the delivered frame toward
--crop-x/--crop-y, the end zoom held after the move. Every frame keeps its
timestamp (zoom.check measures it); the zoom upscales the frame (lanczos), so it
adds no detail.

Examples:
  python3 fit.py input.mp4 --duration 60 --method trim      # keep the first 60s
  python3 fit.py input.mp4 --duration 30 --method speed     # retime the whole clip to exactly 30s
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --width 1080
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --pad-fill blur   # the phone-editor look: blurred frame behind the bars
  python3 fit.py input.mp4 --aspect 9:16 --fit blur                  # same look in one word (blurred + darkened fill)
  python3 fit.py input.mp4 --aspect 1:1 --fit crop --duration 15 --method trim
  python3 fit.py input.mp4 --aspect 9:16 --fit crop --crop-x 1   # keep the right edge (e.g. product held stage-right)
  python3 fit.py input.mp4 --height 1080                         # width follows the source aspect
  python3 fit.py input.mp4 --width 1920 --height 1080            # exact frame, no aspect needed
  python3 fit.py input.mp4 --rotate 90                           # rotate 90 degrees clockwise
  python3 fit.py input.mp4 --flip h                              # mirror horizontally
  python3 fit.py input.mp4 --zoom in --zoom-amount 1.5 --zoom-start 3 --zoom-duration 5   # push in to 1.5x over 3-8 s
"""
import argparse
import os
import sys
from fractions import Fraction
from typing import Any, List, Optional

from _common.runner import require_tool, run_analysis, with_mapped_chapters
from _common.decision import SEEK_MARGIN, enlarge_args, warn_mostly_cropped, atempo_chain_with_lead, line_matrix_filter, delivered_rate, frame_durations, frame_rate, grid_at_or_after, length_output_t, ntsc_rate, stream_starts
from _common.placement import bbox
from _common.timeline import exact_rate, output_timecode_args
from _common import video_args, STATE, add_common, apply_common, emit, aac_args, aspect_ratio, cfr_args, cfr_filter, default_output, die, ffmpeg_base, info, probe, run, run_keeping_subtitles, validate_color, pad_filters, add_pad_fill_args, X264_PRESETS, time_arg, fmt_secs, frame_size, display_size, square_pixels, square_pixels_note, note
from _common.emit import input_length, own_length, refuse, refuse_still, warn
from _common.probe import fingerprint, presentation_times
BLUR_DARKEN = 0.15  # how much --fit blur dims the blurred background copy (eq brightness)
SPEED_WARN_FACTOR = 1.15  # a --method speed retime beyond this, in either direction, is
# reported in the result's diagnostics (large_speed_change): the whole picture and sound
# sped up or slowed down by more than 15% is easy to ask for by accident -- speed is the
# default method -- when what was wanted was a cut, so it is never silent

# crop_check (--fit crop): a luma motion/detail proxy, not subject detection. Provisional values
CROP_SAMPLES = 9  # sample points spread evenly over the kept source range, at (i + 0.5) / 9
CROP_SAMPLE_GAP = 0.2  # seconds between the two frames of a sample point (their difference is motion)
CROP_SAMPLE_LONG = 160  # sampled frames are scaled to this many pixels on their long axis
CROP_DETAIL_MIN = 16  # an 8-bit luma gradient counts as detail at or above this
CROP_MOTION_MIN = 8  # an 8-bit frame difference counts as motion at or above this
CROP_MOTION_FLOOR = 0.05  # mean counted difference per pixel per sample: below it nothing moved
CROP_DETAIL_FLOOR = 0.05  # mean counted gradient per pixel per sample: below it the frames are flat
CROP_MOTION_EXCESS_WARN = 0.15  # with motion: review when the motion share cut away exceeds the area share by this (#630)
CROP_DETAIL_EXCESS_WARN = 0.15  # no motion: review when the detail share cut away exceeds the area share by this


def parse_aspect(value: str) -> Fraction:
    # the one aspect grammar, shared with render.py's frame and --export-timeline's sequence
    ratio = aspect_ratio(value)
    if ratio is None:
        die(f"bad aspect '{value}', use W:H like 16:9")
    return ratio


def atempo_chain(factor: float, sample_rate: Any = 0) -> str:
    """atempo accepts 0.5..100 per instance; chain for extreme factors. The chain is led by the
    samples atempo leaves out (atempo_chain_with_lead, at the track's `sample_rate`), so the
    retimed sound keeps its timing against the retimed picture (#523: about 21 ms early in input
    time without them)."""
    parts: List[str] = []
    remaining = factor
    while remaining < 0.5:
        parts.append("0.5")
        remaining /= 0.5
    while remaining > 100.0:
        parts.append("100.0")
        remaining /= 100.0
    parts.append(f"{remaining:.6f}")
    return atempo_chain_with_lead(parts, sample_rate)


def picture_output_t(target: float, meta: dict) -> str:
    """The output `-t` of a trim from the start that has no sound to end: `{target:.3f}` as it
    always was, unless that text keeps another number of frames than `target` does. The frames
    kept are those that start before `target`. 37 frames of a 30000/1001 picture are 1.2345667 s:
    `-t 1.235` is past the 38th frame's start and wrote it, and `-t 1.001` for 1.0014 s stopped
    before the 31st. The limit is then written half a frame before the first frame left out.
    Without a frame grid (no rate: a dry run's pending input; a variable rate, which the output's
    -r regrids) the millisecond text stays."""
    text = f"{target:.3f}"
    rate = frame_rate(meta)
    if not rate or (meta.get("video") or {}).get("variable_frame_rate_suspected"):
        return text
    out = grid_at_or_after(target, stream_starts(meta)[0], rate)  # the first frame left out
    if out - 1 / rate + 1e-6 < float(text) <= out + 1e-9:
        return text
    return f"{out - 0.5 / rate:.6f}"


def _picture_rows(path_meta: dict, chain: str, colour: str, sw: int, sh: int, size: int,
                  out_pix: "Optional[str]") -> "Optional[bytes]":
    """One frame of `colour` at the source's displayed size and pixel format through `chain`, as
    8-bit grey bytes, or None when ffmpeg did not give exactly one frame of `size` bytes. The chain
    ends in the written file's pixel format, as the encoder line makes it end: pad rounds its
    offset and the picture's size to that format's chroma grid (a 203-row picture is padded as 202
    rows of a 4:2:0 frame), and a chain ending in grey would pad in grey."""
    pix = (path_meta.get("video") or {}).get("pix_fmt")
    src = f"color=c={colour}:s={sw}x{sh}:r=1:d=1" + (f",format={pix}" if pix else "")
    # one filter thread: with slice threads FFmpeg 8.0.1 once gave a white frame's band of rows
    # (128-217 of 640, a fifth of the frame down to the picture) a value the black frame's did not
    # have, and the picture was reported 90 rows taller than the file held it (#543 CI)
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", "1",
           "-f", "lavfi", "-i", src,
           "-vf", chain + (f",format={out_pix}" if out_pix else "") + ",format=gray", "-frames:v", "1", "-f", "rawvideo", "-"]
    proc = run_analysis(cmd, check=False, text=False)
    return proc.stdout if proc.returncode == 0 and len(proc.stdout or b"") == size else None


def measure_picture(geometry, meta: dict, sw: int, sh: int, out_video: dict, sized: bool,
                    *, matrix_filter: "Optional[str]" = None) -> dict:
    """Where the picture sits in the written frame (#519): measured, not judged. ffmpeg runs the
    frame's own filters (the scale and pad, the blur graph with its background drawn black, or the
    scale and crop) on one white and one black frame of the source's displayed size and pixel
    format, after the colour conversion the encoder line adds; the picture is where the two
    differ, and the frame is the written file's. No frame of the source is decoded. Whether the
    subject is inside that rectangle is still a look (subject_framing stays unverified)."""
    filters, crop_scale, cropped = geometry
    W, H = int(out_video.get("width") or 0), int(out_video.get("height") or 0)
    why = None
    if not (sw and sh and W and H):
        why = "the source or the written frame has no size"
    else:
        chain = ",".join(([matrix_filter] if matrix_filter else []) + list(filters))
        out_pix = out_video.get("pix_fmt")
        white = _picture_rows(meta, chain, "white", sw, sh, W * H, out_pix)
        black = _picture_rows(meta, chain, "black", sw, sh, W * H, out_pix) if white is not None else None
        if white is None or black is None:
            why = f"ffmpeg did not give one {W}x{H} frame of the frame's filters (the written frame's size)"
    if why:
        note(f"picture: not measured: {why}")
        return {"measured": False, "reason": why}
    box = bbox((int.from_bytes(white, "big") ^ int.from_bytes(black, "big")).to_bytes(W * H, "big"), W, H)
    if box is None:
        note("picture: not measured: no pixel of the frame changed with the picture")
        return {"measured": False, "reason": "no pixel of the frame changed with the picture"}
    x, y, w, h = box
    scale = crop_scale if crop_scale is not None else w / sw
    pic = {"measured": True, "x": x, "y": y, "width": w, "height": h, "frame_width": W, "frame_height": H,
           "frame_share": round(w * h / (W * H), 4), "scale": round(scale, 4),
           "cropped": cropped or {"left": 0, "right": 0, "top": 0, "bottom": 0}}
    if scale < 1 and not sized:
        note(f"picture: scaled to {scale:.1%} of the source's width ({w}x{h} in a {W}x{H} frame): with no --width or "
             "--height the frame keeps the source's height or width (give --width/--height for a larger frame)")
    return pic


def sample_crop_frames(path: str, orient: List[str], sw: int, sh: int, start: float,
                       length: float) -> "Optional[tuple]":
    """The crop check's decode step: CROP_SAMPLES points evenly over the kept source range
    [start, start + length] at (i + 0.5) / CROP_SAMPLES, two 8-bit grey frames CROP_SAMPLE_GAP s
    apart at each, in the displayed frame the crop is cut from (autorotated, then the run's own
    --rotate/--flip filters `orient`) scaled to CROP_SAMPLE_LONG px on the long axis. Returns
    ([(seek_seconds, (first, second)), ...], width, height), or None when no point gave two whole frames. A
    point that fails (past the end, a decode error) is left out; the others still count."""
    if not (sw and sh) or length <= CROP_SAMPLE_GAP:
        return None
    if sw >= sh:
        w, h = CROP_SAMPLE_LONG, max(2, round(CROP_SAMPLE_LONG * sh / sw / 2) * 2)
    else:
        w, h = max(2, round(CROP_SAMPLE_LONG * sw / sh / 2) * 2), CROP_SAMPLE_LONG
    size = w * h
    filters = [f"fps={1 / CROP_SAMPLE_GAP:g}"] + list(orient) + [f"scale={w}:{h}:flags=area", "format=gray"]
    last = start + max(0.0, length - CROP_SAMPLE_GAP - 0.1)  # room for the second frame
    frames = []
    previous_seek = None
    for i in range(CROP_SAMPLES):
        t = min(start + length * (i + 0.5) / CROP_SAMPLES, last)
        seek = f"{t:.6f}"
        if seek == previous_seek:
            continue
        previous_seek = seek
        remaining = start + length - float(seek)
        chain = ",".join([f"trim=end={remaining:.6f}"] + filters)
        cmd = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
               "-ss", seek, "-i", path, "-map", "0:V:0", "-an", "-sn", "-dn",
               "-vf", chain, "-frames:v", "2", "-f", "rawvideo", "-"]
        proc = run_analysis(cmd, check=False, text=False, timeout_is_fatal=False)
        out = proc.stdout or b""
        if proc.returncode == 0 and len(out) == 2 * size:
            frames.append((float(seek), (out[:size], out[size:])))
    return (frames, w, h) if frames else None


def crop_loss(frames, width: int, height: int, window, axis: str) -> dict:
    """Where the luma motion and detail sit against a crop's kept window: a measurement, not a
    judgement, and a proxy, not subject detection. Pure: `frames` is [(first, second), ...] of
    `width` x `height` 8-bit grey bytes; `window` is (start, end) of the kept part as fractions
    0..1 of the frame along `axis` ("x": columns, "y": rows).

    Per column (per row for y): detail D = sum of |luma gradient| (right and down neighbours) of
    the first frame, counting only gradients >= CROP_DETAIL_MIN; motion M = sum of |first -
    second|, counting only differences >= CROP_MOTION_MIN. motion_outside / detail_outside: the
    energy share in the discarded part (a column the window edge cuts counts pro rata).
    centroid: of M when its mean is at or above CROP_MOTION_FLOOR, else of D. suggested_anchor:
    the --crop-x/--crop-y value (0..1) that centres the kept window on the centroid, clamped.
    verdict: review when motion is present and motion_outside - discarded_fraction >=
    CROP_MOTION_EXCESS_WARN (motion spread evenly over the frame is not off centre, #630), or
    with no motion when detail_outside - discarded_fraction >= CROP_DETAIL_EXCESS_WARN; ok
    otherwise; unmeasured when no whole pair was given or the frames are flat (no division by
    zero, centroid and suggested_anchor null)."""
    n = max(1, width if axis == "x" else height)
    size = width * height
    detail = [0] * n
    motion = [0] * n
    used = 0
    for pair in frames or []:
        a = pair[0] if len(pair) > 0 else b""
        b = pair[1] if len(pair) > 1 else b""
        if size <= 0 or len(a) != size or len(b) != size:
            continue
        used += 1
        for r in range(height):
            o = r * width
            row, other = a[o:o + width], b[o:o + width]
            below = a[o + width:o + 2 * width] if r + 1 < height else None
            for c in range(width):
                v = row[c]
                k = c if axis == "x" else r
                s = 0
                if c + 1 < width:
                    g = abs(row[c + 1] - v)
                    if g >= CROP_DETAIL_MIN:
                        s += g
                if below is not None:
                    g = abs(below[c] - v)
                    if g >= CROP_DETAIL_MIN:
                        s += g
                if s:
                    detail[k] += s
                m = abs(other[c] - v)
                if m >= CROP_MOTION_MIN:
                    motion[k] += m
    w0 = min(max(float(min(window)), 0.0), 1.0)
    w1 = min(max(float(max(window)), 0.0), 1.0)
    keep = w1 - w0
    discarded = 1.0 - keep

    def outside(profile):
        total = sum(profile)
        if total <= 0:
            return None
        lost = 0.0
        for k, e in enumerate(profile):
            if e:
                inside = max(0.0, min((k + 1) / n, w1) - max(k / n, w0)) * n
                lost += e * (1.0 - inside)
        return lost / total

    pixels = used * size
    has_motion = bool(pixels) and sum(motion) / pixels >= CROP_MOTION_FLOOR
    has_detail = bool(pixels) and sum(detail) / pixels >= CROP_DETAIL_FLOOR
    m_out, d_out = outside(motion), outside(detail)
    check = {"axis": axis, "discarded_fraction": round(discarded, 4),
             "motion_outside": None if m_out is None else round(m_out, 4),
             "detail_outside": None if d_out is None else round(d_out, 4),
             "centroid": None, "suggested_anchor": None, "samples": used,
             "basis": "luma_motion_proxy", "signal": None, "verdict": "unmeasured"}
    if not (has_motion or has_detail):
        return check
    profile = motion if has_motion else detail
    check["signal"] = "motion" if has_motion else "detail"
    centroid = sum((k + 0.5) / n * e for k, e in enumerate(profile)) / sum(profile)
    check["centroid"] = round(centroid, 4)
    if discarded > 1e-9:
        check["suggested_anchor"] = round(min(1.0, max(0.0, (centroid - keep / 2) / discarded)), 2)
    if has_motion:
        review = (m_out or 0.0) - discarded >= CROP_MOTION_EXCESS_WARN
    else:
        review = (d_out or 0.0) - discarded >= CROP_DETAIL_EXCESS_WARN
    check["verdict"] = "review" if review else "ok"
    return check


def check_crop(path: str, orient: List[str], sw: int, sh: int, window, start: float, length: float,
               *, speed: float = 1.0, output_video: Optional[dict] = None) -> dict:
    """crop_check for a --fit crop that cut something away: samples the kept source range,
    measures it with crop_loss and records crop_content_off_centre when the verdict is review.
    Advisory: nothing here changes the output or the exit status. A measurement that fails is
    verdict unmeasured with a note, never another diagnostic code."""
    axis, w0, w1 = window
    output_video = output_video or {}
    fps = output_video.get("fps")
    video_length = own_length(output_video)
    # A duration includes the last frame's hold. Accurate seeking past that frame's
    # timestamp would find nothing, even when an audio tail keeps the container open.
    last_seek = (video_length - 1 / ntsc_rate(fps)
                 if fps and video_length and not output_video.get("variable_frame_rate_suspected") else None)
    points = []
    measurement_error = None
    try:
        got = sample_crop_frames(path, orient, sw, sh, start, length)
        samples, fw, fh = got if got else ([], 1, 1)
        check = crop_loss([pair for _, pair in samples], fw, fh, (w0, w1), axis)
        for source_time, pair in samples:
            sample = crop_loss([pair], fw, fh, (w0, w1), axis)
            if sample["verdict"] != "review":
                continue
            estimate = round(max(0.0, (source_time - start) / speed), 6)
            point = {key: sample[key] for key in ("signal", "motion_outside", "detail_outside",
                                                   "centroid", "suggested_anchor")}
            point["source_time"] = source_time
            point["output_time_estimate"] = estimate if last_seek is not None and estimate <= last_seek else None
            points.append(point)
    except Exception as exc:  # a measurement, never the run's failure
        measurement_error = str(exc)
        check = crop_loss([], 1, 1, (w0, w1), axis)
        points = []
    check["kept"] = {"start": round(w0, 6), "end": round(w1, 6)}
    check["review_points"] = points
    aggregate_review = check["verdict"] == "review"
    if points:
        check["verdict"] = "review"
    if check["verdict"] == "unmeasured":
        reason = measurement_error or ("no sample gave two frames" if not check["samples"]
                                       else "the sampled frames have no luma motion or detail")
        note(f"crop check: not measured: {reason}")
        return check
    if check["verdict"] == "review":
        if aggregate_review:
            signal = check["signal"]
            share = check[f"{signal}_outside"]
            advice = f"{share:.0%} of the sampled luma {signal} lies outside the kept window."
            in_use = round(w0 / check["discarded_fraction"], 2) if check["discarded_fraction"] else None
            # naming the anchor this run already used is no remedy (#630)
            if check["suggested_anchor"] is not None and check["suggested_anchor"] != in_use:
                advice += f" --crop-{axis} {check['suggested_anchor']:g} centres the window on the aggregate signal."
        else:
            advice = "Some samples have substantial luma motion or detail outside the kept window."
        if points:
            advice += f" Inspect {len(points)} flagged point(s) in crop_check.review_points."
        warn(f"--fit crop ({axis} axis): {advice} --fit pad or --fit blur keeps the whole frame.",
             "crop_content_off_centre", **{key: value for key, value in check.items() if key != "verdict"})
    return check


def zoom_filters(w: int, h: int, z0: float, z1: float, start: float, length: float, ax: float, ay: float,
                 t0: float = 0.0) -> List[str]:
    """A timed zoom of a w x h frame (#647): z0 to z1, linear over [start, start + length] output
    seconds (`t0`: the graph's time at the output's first frame), toward the anchor (ax, ay). A
    per-frame lanczos scale and a crop back keep every frame and timestamp (zoompan makes its own).
    Sides grow by 4 and offsets stay even (4:2:0); crop's in_w is the first frame's, so x/y are written out."""
    z = f"({z0:g}+({z1 - z0:g})*clip((t-{t0 + start:.6f})/{length:.6f},0,1))"
    sw_, sh_ = (f"({n}+4*round(({z}-1)*{n}/4))" for n in (w, h))
    return [f"scale=w='{sw_}':h='{sh_}':eval=frame:flags=lanczos",
            f"crop={w}:{h}:x='2*round(({sw_}-{w})*{ax:g}/2)':y='2*round(({sh_}-{h})*{ay:g}/2)'"]


def check_zoom(source: str, meta: dict, output: str, out_video: dict) -> dict:
    """Whether the output's frames, timestamps, length and rate are the source's, from both files'
    packets (presentation_times()); unreadable frame times are not measured."""
    v = meta.get("video") or {}
    src = presentation_times(source, float(v.get("start_time") or 0.0))
    out = presentation_times(output, float(out_video.get("start_time") or 0.0))
    rate = frame_rate(meta)
    if not (src and out and rate):
        note("zoom: frames not measured: the frame times of the source or the output could not be read")
        return {"measured": False, "reason": "the frame times of the source or the output could not be read"}
    drift = max((abs((o - out[0]) - (s - src[0])) for o, s in zip(out, src)), default=0.0)
    lengths = own_length(v), own_length(out_video)
    same = {"frames": len(out) == len(src), "timestamps": len(out) == len(src) and drift <= 0.5 / rate,
            "duration": None not in lengths and abs(lengths[1] - lengths[0]) <= 1 / rate,
            "fps": exact_rate(float(out_video.get("fps") or 0)) == exact_rate(float(v.get("fps") or 0))}
    check = {"measured": True, "source_frames": len(src), "output_frames": len(out), "max_timestamp_drift": round(drift, 6),
             "source_duration": lengths[0], "output_duration": lengths[1], "source_fps": v.get("fps"),
             "output_fps": out_video.get("fps"), **{f"{k}_match": ok for k, ok in same.items()}}
    if not all(same.values()):
        note(f"zoom: the output's {', '.join(k for k, ok in same.items() if not ok)} differ from the source's")
    return check


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_fit.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    d = ap.add_argument_group("duration")
    d.add_argument("--duration", help="target duration (seconds or mm:ss)")
    d.add_argument("--method", choices=["speed", "trim"],
                   help="how to reach the duration (small retimes default to speed; larger changes need an explicit choice)")
    d.add_argument("--from-center", action="store_true", help="with --method trim, keep the middle instead of the start")
    d.add_argument("--max-speed", type=float, default=4.0, help="refuse speed factors above this (default 4x)")
    d.add_argument("--smooth", choices=["none", "blend", "interpolate"], default="none",
                   help="slow-motion quality: blend (frame blending) or interpolate (motion-compensated, slow but fluid). default none = duplicate frames")
    a = ap.add_argument_group("aspect")
    a.add_argument("--aspect", help="target aspect ratio, e.g. 16:9, 9:16, 1:1, 4:5")
    a.add_argument("--fit", choices=["pad", "crop", "blur"], default="pad",
                   help="the fit mode, how to reach the aspect: pad (letterbox), crop, or blur -- the whole picture centred on a "
                        "blurred, darkened copy of itself filling the rest (the phone-editor vertical, 1.14). "
                        "The darkening is applied to SDR sources only: on an HDR source the background is blurred "
                        "but left at its own levels, since an eq on PQ/HLG code values is not a -15%% perceptual dim")
    a.add_argument("--width", type=int, help="output width in px, 1..16384 (default: keep source width or the width implied by the aspect); with --height also given, both are used directly")
    a.add_argument("--height", type=int, help="output height in px, 1..16384 (default: keep source height or the height implied by the aspect); with --width also given, both are used directly")
    a.add_argument("--pad-color", default="black", help="pad colour, e.g. black, white, 0x101010 (default black)")
    add_pad_fill_args(a)
    a.add_argument("--crop-x", type=float, default=0.5, help="with --fit crop or --zoom, horizontal anchor 0=left, 0.5=centre (default), 1=right")
    a.add_argument("--crop-y", type=float, default=0.5, help="with --fit crop or --zoom, vertical anchor 0=top, 0.5=centre (default), 1=bottom")
    a.add_argument("--zoom", choices=["in", "out"], help="timed linear push-in/pull-out toward --crop-x/-y")
    a.add_argument("--zoom-amount", type=float, help="end (in) or start (out) zoom, > 1 (default 1.3)")
    a.add_argument("--zoom-start", type=float, metavar="S", help="output second the move starts (default 0)")
    a.add_argument("--zoom-duration", type=float, metavar="S", help="move length (default: to the end), end zoom held")
    a.add_argument("--fade-in", type=float, default=0.0, metavar="S", help="fade the picture and the sound in from black over this many seconds at the start")
    a.add_argument("--fade-out", type=float, default=0.0, metavar="S", help="fade the picture and the sound out to black over this many seconds at the end")
    r = ap.add_argument_group("rotate / flip")
    r.add_argument("--rotate", type=int, choices=[90, 180, 270], help="rotate the picture clockwise by this angle in degrees")
    r.add_argument("--flip", choices=["h", "v"], help="mirror the picture horizontally (h) or vertically (v)")
    e = ap.add_argument_group("encoding")
    e.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    e.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    e.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    method_given = args.method is not None
    args.method = args.method or "speed"

    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be positive, got {args.fps:g}")
    zoom_given = [f for f in ("amount", "start", "duration") if getattr(args, f"zoom_{f}") is not None]
    if zoom_given and not args.zoom:
        die(f"--zoom-{zoom_given[0]} needs --zoom in|out")
    if not args.duration and not args.aspect and not args.width and not args.height and not args.fps and not args.rotate and not args.flip and not (args.fade_in or args.fade_out) and not args.zoom:
        die("nothing to do: give --duration, --aspect, --width/--height, --rotate/--flip, --zoom and/or --fps")
    if args.zoom_amount is not None and args.zoom_amount <= 1.0:  # a negative --zoom-start is refused in apply_common
        die(f"--zoom-amount must be > 1.0, got {args.zoom_amount:g}")
    if args.zoom_duration is not None and args.zoom_duration <= 0:
        die(f"--zoom-duration must be > 0, got {args.zoom_duration:g}")
    if not 0.0 <= args.crop_x <= 1.0:
        die(f"--crop-x must be 0..1, got {args.crop_x}")
    if not 0.0 <= args.crop_y <= 1.0:
        die(f"--crop-y must be 0..1, got {args.crop_y}")
    validate_color(args.pad_color, "--pad-color")

    if STATE.plan and args.duration and os.path.isfile(args.input):
        try:
            source = fingerprint(args.input)
        except OSError as exc:
            die(f"cannot fingerprint the source for the duration plan: {exc}", kind="input")
        STATE.measured_plan_inputs[source["path"]] = source
    meta = probe(args.input, advise_deinterlace=True)
    if not meta.get("video"):
        die("input has no video stream")
    if args.zoom:
        refuse_still(meta, args.input, "--zoom moves over the input's length, and a still has none")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    src_dur = meta["duration"] or 0.0
    # the displayed frame: rotation applied and non-square pixels squared (#411)
    sw, sh = display_size(meta["video"])
    if args.rotate in (90, 270):
        sw, sh = sh, sw
    has_audio = bool(meta.get("audio"))

    vf: List[str] = []
    af: List[str] = []
    pre_input: List[str] = []
    post: List[str] = []
    factor = 1.0
    retimed = False
    extra = {}
    tc_first = None  # seconds from the source's first frame to the output's, when a trim moves it
    regridded = False  # a speed change already put the picture on the delivered grid
    out_seek = 0.0  # the output-side -ss a --method trim drops its seek margin with
    kept = None  # (start, length) of the source a --method trim keeps; None: the whole source

    # ---- rotate / flip
    if args.rotate == 90:
        vf.append("transpose=1")
    elif args.rotate == 270:
        vf.append("transpose=2")
    elif args.rotate == 180:
        vf.append("transpose=2,transpose=2")
    if args.flip == "h":
        vf.append("hflip")
    elif args.flip == "v":
        vf.append("vflip")
    orient = list(vf)  # the run's own rotate/flip filters: the crop check samples the frame they make

    # ---- duration
    if args.duration:
        target = time_arg(args.duration, "--duration", meta["video"].get("fps") if meta.get("video") else None)
        if target <= 0:
            die("target duration must be > 0")
        # speed refused it as "0.00x", and trim wrote one frame as verified (#531)
        refuse_still(meta, args.input, "--duration retimes or trims the input's length, and a still has none")
        # A dry run can plan the command even when the source's usable length is unknown.
        src_dur = (meta.get("duration") or 0.0) if STATE.dry_run else input_length(meta)
        length_unknown = STATE.dry_run and src_dur <= 0
        # The output's -t is all that ends the kept track where the source's sound runs on past
        # the target (a trim; a speed change too small to retime), so it is written to the sample
        # of that track's rate, not to the millisecond: `-t 1.234` wrote 59244 samples (48 kHz)
        # as 59232 and `-t 1.235` wrote 59261 as 59280 (length_output_t). No sound, or a dry
        # run's pending input, has no rate and keeps the millisecond.
        rate = (audio_streams[args.audio_stream].get("sample_rate") if has_audio and audio_streams else None)
        if args.method == "speed":
            factor = 1.0 if length_unknown else src_dur / target  # >1 = speed up
            if factor > args.max_speed or factor < 1 / args.max_speed:
                die(f"required speed factor {factor:.2f}x exceeds --max-speed {args.max_speed}x; use --method trim or raise the limit")
            if factor > SPEED_WARN_FACTOR or factor < 1 / SPEED_WARN_FACTOR:
                change = dict(factor=round(factor, 3), threshold=SPEED_WARN_FACTOR,
                              source_duration=round(src_dur, 3), target_duration=round(target, 3))
                if not method_given and not (factor < 1 and args.smooth != "none"):
                    refuse("input", "fit_method_required",
                           f"--duration {target:g} would retime the entire clip at {factor:.2f}x. Choose how to reach the target.",
                           hint="pass --method speed to retime, --method trim to keep the start, "
                                "or select what to keep with cut.py --segments or silence.py",
                           **change)
                warn(f"speed {factor:.2f}x: retiming the entire picture and sound to {target:.2f}s",
                     "large_speed_change", **change)
            retimed = abs(factor - 1.0) > 1e-4
            if retimed:
                vf.append(f"setpts={1/factor:.8f}*PTS")
                src_fps = meta["video"].get("fps") or 30.0
                if factor < 1.0 and args.smooth == "interpolate":
                    # the new frames are made at the rate delivered: made at the source's 30 and
                    # then put on --fps 60 by the fps filter below, every other frame of the slow
                    # motion was a repeat (#527). Without --fps it is the source's rate, as before
                    vf.append(f"minterpolate=fps={args.fps or src_fps:g}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
                elif factor < 1.0 and args.smooth == "blend":
                    vf.append(f"fps={src_fps:g}")
                    vf.append("tblend=all_mode=average")
                elif not args.fps:
                    # the retimed frames are put back on the output's grid by the fps filter, the
                    # nearest frame for each slot: left to the encoder line's rate, a 1.11x speed-up
                    # showed every picture up to two frames late against its sound (#512's class).
                    # A rate the caller names is that grid (the conform below): conformed here to
                    # the source's 30 first, a 2x speed-up to --fps 60 dropped every other picture
                    # and the second fps filter repeated the rest
                    vf.append(frame_durations(meta, delivered_rate(meta) or frame_rate(meta) or src_fps))
                    regridded = True
                if has_audio:
                    af.append(atempo_chain(factor, rate))
            # atempo's sound is not the input's length over the factor (it comes out some
            # milliseconds short or long), and the millisecond -t stays on a retimed track: padding
            # it to the target's samples (apad after atempo in -af) never ended on FFmpeg 8.0.1
            # (seen in CI: killed at the time limit), so the track keeps the length atempo gives.
            # Where the sound is not retimed (a factor within 1e-4 of 1) the source's runs on and
            # the -t ends it to the sample. A picture without sound that is not retimed either is
            # a trim, counted in frames; one that is retimed, or regridded by --fps, keeps the
            # millisecond
            post += ["-t", f"{target:.3f}" if af else length_output_t(target, rate, runs_on=True) if rate
                     else f"{target:.3f}" if retimed or args.fps or has_audio else picture_output_t(target, meta)]
            STATE.duration_hint = target
        else:
            if target < src_dur:
                start = (src_dur - target) / 2 if args.from_center else 0.0
                kept = (start, target)
                # seek SEEK_MARGIN early and drop the margin on the output side, as cut.py does:
                # an input seek straight to `start` can land on a keyframe whose picture comes
                # after it (a B-frame HEVC source) and lose the frames before it, so the first
                # picture would not be the one the start timecode below names
                m = min(SEEK_MARGIN, round(start, 3))
                # a trim from the start seeks nowhere: no -ss, so the timeline stays where it is and
                # a subtitle/data track is kept below (`-ss 0.000` dropped it, A158)
                pre_input += ["-ss", f"{start - m:.3f}"] if round(start, 3) > 0 else []
                # without sound the -t only counts frames (picture_output_t). Not from the centre:
                # there the output's clock starts at the seek, between two frames, and the encoder
                # rounds each frame to its own tick
                keep = (picture_output_t(target, meta) if not rate and not args.fps and not args.from_center
                        else length_output_t(target, rate, runs_on=True))
                post += (["-ss", f"{m:.3f}"] if m > 0 else []) + ["-t", keep]
                out_seek = round(m, 3) if m > 0 else 0.0
                # the output starts on the first frame at or after the seek (a seek before a
                # picture that starts after the file's origin: on its first frame): its start
                # timecode is that frame's, not the source's first frame's
                v0, rate = stream_starts(meta)[0], frame_rate(meta)
                tc_first = grid_at_or_after(max(round(start, 3), v0), v0, rate) - v0
            elif not length_unknown:
                info(f"source ({src_dur:.2f}s) is already shorter than {target:.2f}s; trim does nothing")
        speed_unknown = length_unknown and args.method == "speed"
        extra["timing"] = {
            "method": args.method,
            "source_duration": None if length_unknown else src_dur,
            "target_duration": target,
            "speed_factor": None if speed_unknown else factor,
            "retimed": None if speed_unknown else retimed,
        }

    # ---- the output's rate: after any retiming, ahead of the frame's own filters. --fit blur and
    # --pad-fill blur are a split/overlay graph, and FFmpeg 6.1's overlay ends its output at its
    # last frame's start, so an fps filter after it lost the last frame (#512's placement).
    # A speed change without --fps has already been put on the delivered grid above
    if args.fps:
        vf.append(f"fps={args.fps:g}")
    elif meta["video"].get("variable_frame_rate_suspected"):
        # said whichever filter conforms it: a speed change's regrid above is that conform, and the
        # line was missing there (#527)
        info("source looks variable-frame-rate; conforming to constant fps automatically")
        if not regridded:
            # the conform is the fps filter, as --fps is: -fps_mode cfr alone let a frame run up to
            # two frames late against the sound (#512), its grid laid from the output-side seek
            # (#538: --from-center put the picture of a 27 fps average clip 24-37 ms late)
            vf.append(cfr_filter(meta, seek=out_seek))

    # ---- aspect / size
    geometry = None  # (the frame's filters with every fill drawn black, scale, cropped) for the picture measurement
    crop_window = None  # (axis, start, end) of the kept part, fractions of the displayed frame, for crop_check
    if args.aspect or args.width or args.height:
        # the one sizing rule, shared with render.py --export-timeline's sequence frame
        out_w, out_h = frame_size(parse_aspect(args.aspect) if args.aspect else None, args.width, args.height, sw, sh)
        post += enlarge_args(meta, out_w, out_h)
        if args.aspect and not (args.width or args.height) and out_w * out_h < sw * sh and out_w < (usual := (1080, 1920)[out_w > out_h]):
            note(f"the frame is {out_w}x{out_h}: --aspect alone keeps the source's size and never enlarges; --width {usual} gives the usual delivery frame of this shape (enlarged {usual / out_w:.2g}x)")
        if args.fit == "crop" and sw and sh:
            warn_mostly_cropped(meta.get("video"), out_w, out_h)
            # The scaled frame's margin on each axis is a multiple of 4 and the offset is computed
            # here, to even: crop floors an odd offset to the chroma grid of a 4:2:0 frame, so
            # --crop-x 1 lost the source's last column and showed one column of the margin, and a
            # centred crop sat a pixel left of / above the centre (#512). exact=1 would put the
            # chroma half a sample off the luma instead. The size is the one
            # force_original_aspect_ratio=increase gives (av_rescale rounds half away from zero),
            # widened by at most 3 px on the cropped axis.
            sc_w = max(out_w, (2 * out_h * sw + sh) // (2 * sh))
            sc_h = max(out_h, (2 * out_w * sh + sw) // (2 * sw))
            mx, my = (-(-(sc - o) // 4) * 4 for sc, o in ((sc_w, out_w), (sc_h, out_h)))
            ox, oy = (int(m * f / 2 + 0.5) * 2 for m, f in ((mx, args.crop_x), (my, args.crop_y)))
            for axis, m, f, got in (("x", mx, args.crop_x, ox), ("y", my, args.crop_y, oy)):
                if abs(m * f - got) > 1e-9:
                    # the offset is kept even (the chroma grid); a caller who asked for another one
                    # is told which it got, as proxy.py says which width it wrote
                    note(f"--crop-{axis} {f:g}: crop offset {got}px, not {m * f:g}px: the offset is kept even "
                         f"(4:2:0 chroma), on a {m}px margin")
            vf.append(f"scale={out_w + mx}:{out_h + my}")
            vf.append(f"crop={out_w}:{out_h}:{ox}:{oy}")
            # the source pixels the crop leaves out on each side, at the scale it was cut at: each
            # axis by its own, since the margin widened to a multiple of 4 scales the two apart
            kx, ky = sw / (out_w + mx), sh / (out_h + my)
            geometry = (vf[-2:], (out_w + mx) / sw, {"left": round(ox * kx), "right": round((mx - ox) * kx),
                                                     "top": round(oy * ky), "bottom": round((my - oy) * ky)})
            # the kept window from the same numbers the crop filter above was built from (the
            # anchor's even offset included): fractions of the scaled frame, which is the displayed
            # frame's proportions on each axis. No margin on either axis: nothing is cut, no check
            # the window as data (#581), from the same numbers: in the source's displayed pixels, and
            # in the scaled frame the crop filter cuts it from
            extra["crop"] = {"x": round(ox * kx), "y": round(oy * ky), "width": round(out_w * kx), "height": round(out_h * ky),
                             "source_width": sw, "source_height": sh,
                             "scaled": {"x": ox, "y": oy, "width": out_w, "height": out_h,
                                        "frame_width": out_w + mx, "frame_height": out_h + my}}
            rel_x, rel_y = mx / (out_w + mx), my / (out_h + my)
            if rel_x > 0 or rel_y > 0:
                crop_window = (("x", ox / (out_w + mx), (ox + out_w) / (out_w + mx)) if rel_x >= rel_y
                               else ("y", oy / (out_h + my), (oy + out_h) / (out_h + my)))
        elif args.fit == "crop":  # a dry run's pending input has no size: the expressions, planned only
            vf.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase")
            vf.append(f"crop={out_w}:{out_h}:(in_w-out_w)*{args.crop_x:g}:(in_h-out_h)*{args.crop_y:g}")
        elif args.fit == "blur":
            # nothing is cropped and nothing is a black bar: the picture keeps its own aspect in
            # the middle of a blurred, dimmed copy of itself (BLUR_DARKEN) filling the frame.
            # The dimming is an eq on the code values, which is a -15 % perceptual dim on an SDR
            # (gamma-encoded) signal and something else entirely on a PQ/HLG one -- so an HDR
            # source keeps its blurred background undimmed rather than being silently altered
            # (review 12). The blur itself is neutral either way, and no tone mapping happens.
            darken = 0.0 if meta["video"].get("bt2020_or_hdr") else BLUR_DARKEN
            if not darken:
                info("--fit blur: HDR source, so the blurred background is not dimmed "
                     "(an eq on PQ/HLG code values is not the -15% dim it is on SDR); "
                     "run color.py --to-sdr first for the SDR look")
            vf.append(pad_filters(out_w, out_h, "blur", args.pad_color, args.pad_blur, darken))
            geometry = ([pad_filters(out_w, out_h, "blur", args.pad_color, args.pad_blur, darken, blank=True)], None, None)
        else:
            vf.append(pad_filters(out_w, out_h, args.pad_fill, args.pad_color, args.pad_blur, meta=meta))
            geometry = ([pad_filters(out_w, out_h, args.pad_fill, args.pad_color, args.pad_blur, meta=meta, blank=True)], None, None)
        vf.append("setsar=1")
        # a non-square-pixel source is made square at its display aspect before anything else
        # (the size above is computed in that frame), so the fitted picture is not squashed
        if square_pixels(meta["video"]):
            vf.insert(0, square_pixels(meta["video"]))
            note(square_pixels_note(meta["video"]))

    total = min(target, src_dur) if args.duration and args.method == "trim" else target if args.duration else src_dur
    # ---- zoom: on the frame delivered (after the reframe, before the fades), in output seconds
    if args.zoom:
        amount = args.zoom_amount or 1.3
        z_start = args.zoom_start or 0.0
        z_len = args.zoom_duration if args.zoom_duration is not None else total - z_start
        if total > 0 and z_start >= total:
            die(f"--zoom-start {z_start:g} is at or past the output's end ({total:g}s)")
        if total > 0 and z_start + z_len > total + 0.5 / (frame_rate(meta) or 1000.0):  # half a frame of slack
            die(f"--zoom-start {z_start:g} --zoom-duration {z_len:g} ends at {z_start + z_len:g}s, past the output's "
                f"end ({total:g}s)")
        sized = bool(args.aspect or args.width or args.height)
        zw, zh = (out_w, out_h) if sized else (sw, sh)
        if not (zw and zh):  # a dry run's pending input has no size: the move cannot be planned in pixels
            die("--zoom needs the input's frame size; the input is not there yet")
        if max(zw, zh) * amount > 16384:  # the zoomed frame is scaled whole: bounded as --width is
            die(f"--zoom-amount {amount:g} scales the {zw}x{zh} frame past 16384 px; at most {16384 / max(zw, zh):.2f} here")
        if not sized and square_pixels(meta["video"]):
            vf.insert(0, square_pixels(meta["video"]))
            note(square_pixels_note(meta["video"]))
        z0, z1 = (1.0, amount) if args.zoom == "in" else (amount, 1.0)
        vf += zoom_filters(zw, zh, z0, z1, z_start, max(z_len, 1e-6), args.crop_x, args.crop_y, t0=out_seek)
        extra["zoom"] = {"direction": args.zoom, "from": z0, "to": z1, "start": round(z_start, 6),
                         "end": round(z_start + z_len, 6), "anchor": {"x": args.crop_x, "y": args.crop_y},
                         "frame": {"width": zw, "height": zh}}

    # ---- fades: last, so they are drawn on the frame that is delivered, over its final length
    for kind, secs, at in (("in", args.fade_in, 0.0), ("out", args.fade_out, total - args.fade_out)):
        if secs > 0 and total > 0:
            vf.append(f"fade=t={kind}:st={max(at, 0):.3f}:d={secs:g}")
            af += [f"afade=t={kind}:st={max(at, 0):.3f}:d={secs:g}"] if has_audio else []

    # the start timecode is counted at the rate the output is delivered at: a --fps that changes
    # the rate relabels it (01:00:00:12 at 25 fps is 01:00:00:24 at 50) even with no trim, which
    # is also how a render.py clip cut at its own rate reaches the project's frame.fps
    out_rate = args.fps or delivered_rate(meta)
    src_fps = meta["video"].get("fps")
    rate_changed = bool(out_rate and src_fps and exact_rate(float(out_rate)) != exact_rate(float(src_fps)))
    relabel = tc_first is not None or rate_changed
    if relabel:
        post += output_timecode_args(meta, tc_first or 0.0, out_rate)

    output = args.output or default_output(args.input, "fit")
    cmd = ffmpeg_base() + pre_input + ["-i", args.input]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", f"0:a:{args.audio_stream}"]
    cmd += video_args(meta, args.crf, args.preset)
    cmd += cfr_args(meta, args.fps) if not args.fps else []
    if has_audio:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd += post
    if retimed or kept:
        # the chapters follow the retime or the trim (#470): FFmpeg kept them at the source's times
        # (an output-side -ss is subtracted from them by FFmpeg, so it is added back here)
        chap_lead = out_seek if kept else 0.0
        cmd = with_mapped_chapters(cmd, meta, (lambda t: t / factor) if retimed else (lambda t: t - kept[0] + chap_lead),
                                   target + chap_lead if kept else None)
    if retimed or "-ss" in pre_input:
        # A subtitle/data stream stream-copied by run_keeping_subtitles keeps the source's
        # original timestamps; --method speed retimes video (setpts) and audio (atempo) but has
        # no equivalent way to retime a copied subtitle track, so it would desync from the
        # now-faster/slower picture. Drop them here rather than ship a captions track that lies
        # about when a line is spoken. --method trim's -ss moves the timeline the same way: a copied
        # track kept its cues at the source's times and doubled the output's length (review 5).
        run(cmd + [output])
        dropped_streams = bool(meta.get("subtitle_streams") or meta.get("data_streams"))
    else:
        dropped_streams = run_keeping_subtitles(cmd, output, relabel_timecode=relabel)

    result = probe(output, role="output")
    msg = f"wrote {output} ({fmt_secs(result['duration'])}, {result['video']['width']}x{result['video']['height']})"
    if retimed:
        msg += f", speed {factor:.3f}x"
    info(msg)
    if geometry and not STATE.dry_run:
        extra["picture"] = measure_picture(geometry, meta, sw, sh, result["video"],
                                           sized=bool(args.width or args.height), matrix_filter=line_matrix_filter(meta))
    if crop_window and not STATE.dry_run:
        # the source range the output shows: a trim's window, else the whole source (speed retimes all of it)
        k0, klen = kept if kept else (0.0, src_dur or (meta.get("duration") or 0.0))
        extra["crop_check"] = check_crop(
            args.input, orient, sw, sh, crop_window, k0, klen,
            speed=factor if abs(factor - 1.0) > 1e-4 else 1.0, output_video=result.get("video"))
    if args.zoom and not STATE.dry_run:
        # the source's frames are the output's only when nothing else in the run changes the timing
        timed = retimed or kept or args.fps or meta["video"].get("variable_frame_rate_suspected")
        extra["zoom"]["check"] = ({"measured": False, "reason": "the run also trims, retimes or regrids the picture"}
                                  if timed else check_zoom(args.input, meta, output, result.get("video") or {}))
    emit(output, dropped_non_av_streams=dropped_streams, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
