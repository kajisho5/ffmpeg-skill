#!/usr/bin/env python3
"""Fit a video to a target duration and/or aspect ratio.

Duration: --duration N with --method speed (retime video+audio, pitch-preserving
via atempo chaining) or --method trim (keep the first N seconds, or a centred
window with --from-center). Aspect: --aspect 16:9|9:16|1:1|4:5|W:H with
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

Examples:
  python3 fit.py input.mp4 --duration 60                    # speed up/down to exactly 60s
  python3 fit.py input.mp4 --duration 30 --method trim
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --width 1080
  python3 fit.py input.mp4 --aspect 9:16 --fit pad --pad-fill blur   # the phone-editor look: blurred frame behind the bars
  python3 fit.py input.mp4 --aspect 9:16 --fit blur                  # same look in one word (blurred + darkened fill)
  python3 fit.py input.mp4 --aspect 1:1 --fit crop --duration 15
  python3 fit.py input.mp4 --aspect 9:16 --fit crop --crop-x 1   # keep the right edge (e.g. product held stage-right)
  python3 fit.py input.mp4 --height 1080                         # width follows the source aspect
  python3 fit.py input.mp4 --width 1920 --height 1080            # exact frame, no aspect needed
  python3 fit.py input.mp4 --rotate 90                           # rotate 90 degrees clockwise
  python3 fit.py input.mp4 --flip h                              # mirror horizontally
"""
import argparse
import sys
from fractions import Fraction
from typing import Any, List, Optional

from _common.color import bt709_matrix_filter
from _common.runner import require_tool, run_analysis
from _common.decision import SEEK_MARGIN, atempo_chain_with_lead, keeps_source_tags, delivered_rate, frame_durations, frame_rate, grid_at_or_after, length_output_t, stream_starts
from _common.timeline import exact_rate, output_timecode_args
from _common import video_args, STATE, add_common, apply_common, emit, aac_args, aspect_ratio, cfr_args, cfr_filter, default_output, die, ffmpeg_base, info, probe, run, run_keeping_subtitles, validate_color, pad_filters, add_pad_fill_args, X264_PRESETS, time_arg, fmt_secs, frame_size, display_size, square_pixels, square_pixels_note, note
from _common.emit import input_length, refuse_still
BLUR_DARKEN = 0.15  # how much --fit blur dims the blurred background copy (eq brightness)


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


def measure_picture(geometry, meta: dict, sw: int, sh: int, out_video: dict, sized: bool) -> dict:
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
        conv = None if keeps_source_tags() else bt709_matrix_filter(meta)
        chain = ",".join(([conv] if conv else []) + list(filters))
        out_pix = out_video.get("pix_fmt")
        white = _picture_rows(meta, chain, "white", sw, sh, W * H, out_pix)
        black = _picture_rows(meta, chain, "black", sw, sh, W * H, out_pix) if white is not None else None
        if white is None or black is None:
            why = f"ffmpeg did not give one {W}x{H} frame of the frame's filters (the written frame's size)"
    if why:
        note(f"picture: not measured: {why}")
        return {"measured": False, "reason": why}
    rows = [r for r in range(H) if white[r * W:(r + 1) * W] != black[r * W:(r + 1) * W]]
    if not rows:
        note("picture: not measured: no pixel of the frame changed with the picture")
        return {"measured": False, "reason": "no pixel of the frame changed with the picture"}
    left, right = W, -1
    for r in rows:
        # the row's difference as one integer: its leading zero bytes are the columns before the
        # first differing pixel, its trailing ones those after the last (no per-pixel loop)
        d = int.from_bytes(white[r * W:(r + 1) * W], "big") ^ int.from_bytes(black[r * W:(r + 1) * W], "big")
        x0 = W - (d.bit_length() + 7) // 8
        x1 = W - 1 - ((d & -d).bit_length() - 1) // 8
        left, right = min(left, x0), max(right, x1)
    x, y, w, h = left, rows[0], right - left + 1, rows[-1] - rows[0] + 1
    scale = crop_scale if crop_scale is not None else w / sw
    pic = {"measured": True, "x": x, "y": y, "width": w, "height": h, "frame_width": W, "frame_height": H,
           "frame_share": round(w * h / (W * H), 4), "scale": round(scale, 4),
           "cropped": cropped or {"left": 0, "right": 0, "top": 0, "bottom": 0}}
    if scale < 1 and not sized:
        note(f"picture: scaled to {scale:.1%} of the source's width ({w}x{h} in a {W}x{H} frame): with no --width or "
             "--height the frame keeps the source's height or width (give --width/--height for a larger frame)")
    return pic


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
    d.add_argument("--method", choices=["speed", "trim"], default="speed", help="how to reach the duration (default speed)")
    d.add_argument("--from-center", action="store_true", help="with --method trim, keep the middle instead of the start")
    d.add_argument("--max-speed", type=float, default=4.0, help="refuse speed factors above this (default 4x)")
    d.add_argument("--smooth", choices=["none", "blend", "interpolate"], default="none",
                   help="slow-motion quality: blend (frame blending) or interpolate (motion-compensated, slow but fluid). default none = duplicate frames")
    a = ap.add_argument_group("aspect")
    a.add_argument("--aspect", help="target aspect ratio, e.g. 16:9, 9:16, 1:1, 4:5")
    a.add_argument("--fit", choices=["pad", "crop", "blur"], default="pad",
                   help="how to reach the aspect: pad (letterbox), crop, or blur -- the whole picture centred on a "
                        "blurred, darkened copy of itself filling the rest (the phone-editor vertical, 1.14). "
                        "The darkening is applied to SDR sources only: on an HDR source the background is blurred "
                        "but left at its own levels, since an eq on PQ/HLG code values is not a -15%% perceptual dim")
    a.add_argument("--width", type=int, help="output width in px (default: keep source width or the width implied by the aspect); with --height also given, both are used directly")
    a.add_argument("--height", type=int, help="output height in px (default: keep source height or the height implied by the aspect); with --width also given, both are used directly")
    a.add_argument("--pad-color", default="black", help="pad colour, e.g. black, white, 0x101010 (default black)")
    add_pad_fill_args(a)
    a.add_argument("--crop-x", type=float, default=0.5, help="with --fit crop, horizontal anchor 0=left, 0.5=centre (default), 1=right")
    a.add_argument("--crop-y", type=float, default=0.5, help="with --fit crop, vertical anchor 0=top, 0.5=centre (default), 1=bottom")
    r = ap.add_argument_group("rotate / flip")
    r.add_argument("--rotate", type=int, choices=[90, 180, 270], help="rotate the picture clockwise by this many degrees")
    r.add_argument("--flip", choices=["h", "v"], help="mirror the picture horizontally (h) or vertically (v)")
    e = ap.add_argument_group("encoding")
    e.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    e.add_argument("--preset", default="medium", choices=X264_PRESETS)
    e.add_argument("--fps", type=float, help="force a constant output frame rate (recommended for VFR sources)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.fps is not None and args.fps <= 0:
        die(f"--fps must be positive, got {args.fps:g}")
    for flag, value in (("--width", args.width), ("--height", args.height)):
        # A165: 0 read as "not given" (the side was sized from the other one, or the run was
        # "nothing to do") and a negative size reached ffmpeg's pad as kind ffmpeg
        if value is not None and value < 1:
            die(f"{flag} must be a positive number of pixels, got {value}")
    if not args.duration and not args.aspect and not args.width and not args.height and not args.fps and not args.rotate and not args.flip:
        die("nothing to do: give --duration, --aspect, --width/--height, --rotate/--flip and/or --fps")
    if not 0.0 <= args.crop_x <= 1.0:
        die(f"--crop-x must be 0..1, got {args.crop_x}")
    if not 0.0 <= args.crop_y <= 1.0:
        die(f"--crop-y must be 0..1, got {args.crop_y}")
    validate_color(args.pad_color, "--pad-color")
    if args.pad_blur <= 0:
        die(f"--pad-blur must be > 0, got {args.pad_blur}")

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
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
    tc_first = None  # seconds from the source's first frame to the output's, when a trim moves it
    regridded = False  # a speed change already put the picture on the delivered grid
    out_seek = 0.0  # the output-side -ss a --method trim drops its seek margin with

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

    # ---- duration
    if args.duration:
        target = time_arg(args.duration, "--duration", meta["video"].get("fps") if meta.get("video") else None)
        if target <= 0:
            die("target duration must be > 0")
        # speed refused it as "0.00x", and trim wrote one frame as verified (#531)
        refuse_still(meta, args.input, "--duration retimes or trims the input's length, and a still has none")
        # speed and trim are both computed from the source's length: one that states none is refused
        # (#491). Not under --dry-run, where render.py plans a clip's speed stage on the source in
        # place of a cut that does not exist yet and records the stand-in itself (A97)
        src_dur = (meta.get("duration") or 0.0) if STATE.dry_run else input_length(meta)
        # The output's -t is all that ends the kept track where the source's sound runs on past
        # the target (a trim; a speed change too small to retime), so it is written to the sample
        # of that track's rate, not to the millisecond: `-t 1.234` wrote 59244 samples (48 kHz)
        # as 59232 and `-t 1.235` wrote 59261 as 59280 (length_output_t). No sound, or a dry
        # run's pending input, has no rate and keeps the millisecond.
        rate = (audio_streams[args.audio_stream].get("sample_rate") if has_audio and audio_streams else None)
        if args.method == "speed":
            if src_dur <= 0 and STATE.dry_run:
                src_dur = target  # planning against an intermediate that does not exist yet
            factor = src_dur / target  # >1 = speed up
            if factor > args.max_speed or factor < 1 / args.max_speed:
                die(f"required speed factor {factor:.2f}x exceeds --max-speed {args.max_speed}x; use --method trim or raise the limit")
            if abs(factor - 1.0) > 1e-4:
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
            retimed = abs(factor - 1.0) > 1e-4
            post += ["-t", f"{target:.3f}" if af else length_output_t(target, rate, runs_on=True) if rate
                     else f"{target:.3f}" if retimed or args.fps or has_audio else picture_output_t(target, meta)]
            STATE.duration_hint = target
        else:
            if target < src_dur:
                start = (src_dur - target) / 2 if args.from_center else 0.0
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
            else:
                info(f"source ({src_dur:.2f}s) is already shorter than {target:.2f}s; trim does nothing")

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
    if args.aspect or args.width or args.height:
        # the one sizing rule, shared with render.py --export-timeline's sequence frame
        out_w, out_h = frame_size(parse_aspect(args.aspect) if args.aspect else None, args.width, args.height, sw, sh)
        if args.fit == "crop" and sw and sh:
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
    if abs(factor - 1.0) > 1e-4 or "-ss" in pre_input:
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
    if abs(factor - 1.0) > 1e-4:
        msg += f", speed {factor:.3f}x"
    info(msg)
    extra = {}
    if geometry and not STATE.dry_run:
        extra["picture"] = measure_picture(geometry, meta, sw, sh, result["video"], sized=bool(args.width or args.height))
    emit(output, dropped_non_av_streams=dropped_streams, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
