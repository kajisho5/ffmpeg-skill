#!/usr/bin/env python3
"""Render an audio track as a waveform or spectrum visualization video.

Wraps FFmpeg's showwaves (--style waveform, the default) or showspectrum
(--style spectrum) source filter over the input's audio -- for a podcast
episode, a music release, or any clip that has no picture worth showing.
The rendered clip always carries the same audio it visualizes; the video is
generated fresh, there is no source picture involved.

--style waveform draws the amplitude over time; --style spectrum draws a
frequency-over-time heatmap instead, which reads more information out of
dense mixes at the cost of being less immediately readable to a general
audience. Both accept --width/--height and --color; waveform additionally
takes --waveform-mode (how each sample is drawn) and --split-channels
(stereo drawn as two separate lanes instead of summed to one).

Examples:
  python3 waveform.py podcast.wav -o waveform.mp4
  python3 waveform.py track.wav --style spectrum --width 1920 --height 1080 -o spectrum.mp4
  python3 waveform.py interview.mp4 --split-channels --color cyan|magenta

An *audiogram* is the same render over a picture: --image cover.png puts a
still behind the visualisation, --platform sizes the frame for a
destination, --srt burns the captions on afterwards (by running caption.py,
not by re-implementing the subtitle path) and --title draws one static
label through graphics.py. Nothing is ever fetched and no cover art is ever
invented: give an image or a colour.

  python3 waveform.py ep.m4a --image cover.png --platform reels --position strip -o ep.mp4
  python3 waveform.py ep.m4a --image cover.png --srt ep.srt --title "Episode 12" -o ep.mp4
"""
import argparse
import os
import subprocess
import sys

from _platforms import PLATFORMS, PLATFORM_CHOICES, resolve as resolve_platform
from _common import (add_common, apply_common, aac_args, default_output, die, emit, ffmpeg_base,
                     info, load_brand, pad_filters, probe, run, STATE, validate_color, video_args, X264_PRESETS,
                     fmt_secs)

WAVEFORM_MODES = ["point", "line", "p2p", "cline"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_waveform.<ext>)")
    ap.add_argument("--style", choices=["waveform", "spectrum"], default="waveform", help="waveform (default) or spectrum visualization")
    ap.add_argument("--width", type=int, default=1920, help="output width in px, must be even (default 1920)")
    ap.add_argument("--height", type=int, default=1080, help="output height in px, must be even (default 1080)")
    ap.add_argument("--fps", type=float, default=25.0, help="output frame rate (default 25)")
    ap.add_argument("--color", default="lime", help="channel colour(s), pipe-separated per channel, e.g. 'lime' or 'cyan|magenta' (default lime)")
    ap.add_argument("--background", default="black", help="background colour (default black)")
    ap.add_argument("--waveform-mode", choices=WAVEFORM_MODES, default="line", help="--style waveform only: how each sample is drawn (default line)")
    ap.add_argument("--split-channels", action="store_true", help="draw each channel in its own lane instead of summing to one")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to render, 0-based in file order (default 0)")
    ag = ap.add_argument_group("audiogram (1.16)",
                               "The visualisation over a picture, for an episode that has no video. The image is a "
                               "local file you give: this skill has no network access and never invents cover art.")
    ag.add_argument("--image", help="still image or brand plate to put behind the visualisation (a local file; scaled to cover the frame and centre-cropped)")
    ag.add_argument("--image-fit", choices=["cover", "contain", "blur"], default="cover",
                    help="how a still of the wrong aspect fills the frame: cover (default, crop the overflow), contain (bars in --background), blur (bars are a blurred copy, as fit.py)")
    ag.add_argument("--position", choices=["bottom", "centre", "center", "top", "strip"], default="strip",
                    help="where the visualisation sits over the plate (default strip: a band of --vis-height along the bottom, the podcast-audiogram convention)")
    ag.add_argument("--vis-height", type=float, default=0.35,
                    help="height of the visualisation band as a fraction of the frame (default 0.35)")
    ag.add_argument("--opacity", type=float, default=1.0, help="visualisation alpha over the plate, 0..1 (default 1)")
    ag.add_argument("--platform", choices=PLATFORM_CHOICES, default=None,
                    help="take the frame size and fps from this destination instead of --width/--height/--fps")
    ag.add_argument("--srt", help="burn these captions into the render afterwards, by running caption.py (never re-implemented here)")
    ag.add_argument("--text", help="plain cue file to burn, same as caption.py --text")
    ag.add_argument("--title", help="one static label drawn over the plate, through graphics.py's sticker template")
    ag.add_argument("--brand", help="brand.json: --color / --background / font defaults")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS, help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    args.platform = resolve_platform(args.platform)
    if args.platform:
        frame = PLATFORMS[args.platform].get("frame")
        if not frame:
            die(f"--platform {args.platform}: that destination has no frame (it is an audio spec); "
                "give --width/--height, or name a destination that has a picture", kind="input")
        args.width, args.height = frame["w"], frame["h"]
        args.fps = float(PLATFORMS[args.platform].get("fps") or args.fps)
        info(f"--platform {args.platform}: {args.width}x{args.height} @ {args.fps:g}fps")
    brand = load_brand(args.brand) if args.brand else None
    if brand:
        bc = brand.get("colors") or {}
        if args.color == "lime" and bc.get("primary"):
            args.color = bc["primary"]
        if args.background == "black" and bc.get("background"):
            args.background = bc["background"]
    if args.image:
        if "://" in args.image:
            die("--image must be a readable local file; this skill has no network access, so save "
                "the image locally and pass its path", kind="input")
        if not os.path.exists(args.image):
            die(f"--image file not found: {args.image}", kind="input")
        if not STATE.dry_run:
            plate = probe(args.image, role="input")
            if not (plate.get("video") or {}).get("width"):
                die(f"--image is not an image ffmpeg can decode: {args.image}", kind="input")
        if args.background != "black":
            die("--image and a non-default --background exclude each other: the plate is either "
                "the picture or the colour", kind="input")
    if not 0.0 <= args.opacity <= 1.0:
        die(f"--opacity must be between 0 and 1, got {args.opacity:g}")
    if not 0.0 < args.vis_height <= 1.0:
        die(f"--vis-height must be between 0 and 1, got {args.vis_height:g}")
    if args.srt and args.text:
        die("--srt and --text exclude each other (both name the cues to burn)")

    if args.width <= 0 or args.height <= 0:
        die(f"--width/--height must be > 0, got width={args.width} height={args.height}")
    if args.width % 2 or args.height % 2:
        die(f"--width/--height must be even (4:2:0 chroma), got width={args.width} height={args.height}")
    for token in args.color.split("|"):
        validate_color(token, "--color")
    validate_color(args.background, "--background")
    if args.fps <= 0:
        die(f"--fps must be > 0, got {args.fps:g}")

    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    output = args.output or default_output(args.input, "waveform")

    # The visualisation's own band. Without --image/--position it fills the frame, which is what
    # every 1.15 command line did, so the graph below is byte-identical when no new flag is given.
    vis_h = args.height
    vis_y = 0
    if args.image:
        vis_h = max(2, int(round(args.height * args.vis_height)) // 2 * 2)
        pos = "centre" if args.position == "center" else args.position
        vis_y = {"top": 0, "centre": (args.height - vis_h) // 2,
                 "bottom": args.height - vis_h, "strip": args.height - vis_h}[pos]

    if args.style == "waveform":
        vf = (f"showwaves=s={args.width}x{vis_h}:mode={args.waveform_mode}:rate={args.fps:g}:"
              f"split_channels={1 if args.split_channels else 0}:colors={args.color}")
    else:
        vf = f"showspectrum=s={args.width}x{vis_h}:mode={'separate' if args.split_channels else 'combined'}:fps={args.fps:g}"
    if args.image:
        # One filter_complex, one encode: the still gets a timeline with -loop 1, is scaled to the
        # frame by --image-fit, and the visualisation is overlaid on it at --opacity.
        if args.image_fit == "cover":
            plate = (f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
                     f"crop={args.width}:{args.height},setsar=1")
        else:
            plate = pad_filters(args.width, args.height,
                                "blur" if args.image_fit == "blur" else "color",
                                args.background, 20)
        graph = f"[1:v]{plate},format=rgba[plate];[0:a:{args.audio_stream}]{vf},format=rgba"
        if args.opacity < 1.0:
            graph += f",colorchannelmixer=aa={args.opacity:g}"
        graph += f"[vis];[plate][vis]overlay=x=(W-w)/2:y={vis_y}:format=auto[v]"
        vf = graph
    else:
        # showwaves/showspectrum paint the visualization on a transparent-black canvas; composite
        # it over an explicit solid background instead of assuming that canvas already matches
        # --background.
        vf = f"color=c={args.background}:s={args.width}x{args.height}:r={args.fps:g}[bg];[0:a:{args.audio_stream}]{vf}[vis];[bg][vis]overlay=format=auto"

    render = output
    if args.title or args.srt or args.text:
        # the visualisation is rendered first and the label/captions are drawn on it by the tools
        # that own those code paths, so neither is re-implemented here
        stem, ext = os.path.splitext(output)
        render = stem + "_vis" + ext
    cmd = ffmpeg_base() + ["-i", args.input]
    if args.image:
        # -framerate before -loop: a looped still defaults to 25 fps, and overlay takes its rate
        # from the FIRST input -- so without this the file came out 25 fps however loud --fps or
        # --platform said otherwise (the colour-plate path never had the bug: `color=` carries r=).
        cmd += ["-framerate", f"{args.fps:g}", "-loop", "1", "-i", args.image]
    cmd += ["-filter_complex", vf]
    if args.image:
        cmd += ["-map", "[v]"]
    cmd += ["-map", f"0:a:{args.audio_stream}"]
    cmd += video_args(None, args.crf, args.preset)  # the one encoder line, so --codec / --quality reach it (review 7)
    cmd += aac_args()
    # -shortest alone is not enough on FFmpeg 5.x: showwaves keeps emitting frames after the
    # audio ends (a 12 s source came out 14.08 s on 5.1.1, #146), so the output is also capped
    # at the source's own duration when probe knows it.
    if meta.get("duration"):
        cmd += ["-t", f"{float(meta['duration']):.3f}"]
    cmd += ["-shortest", render]
    run(cmd)

    stages = ["waveform"]
    current = render
    if args.title:
        stem, ext = os.path.splitext(output)
        titled = stem + "_titled" + ext if (args.srt or args.text) else output
        _child("graphics.py", [current, "--template", "sticker", "--text", args.title,
                               "--position", "top-left", "-o", titled]
               + (["--brand", args.brand] if args.brand else []))
        stages.append("title")
        current = titled
    if args.srt or args.text:
        _child("caption.py", [current] + (["--srt", args.srt] if args.srt else ["--text", args.text])
               + (["--platform", args.platform] if args.platform else []) + ["-o", output])
        stages.append("captions")
        current = output
    if current != output and not STATE.dry_run:
        os.replace(current, output)
        current = output
    # the intermediates exist only to keep each tool's own code path the only one there is
    for temp in (render, os.path.splitext(output)[0] + "_titled" + os.path.splitext(output)[1]):
        if temp != output and os.path.exists(temp) and not STATE.dry_run:
            os.remove(temp)

    result = probe(output, role="output")
    v = result["video"] or {}
    notes: "list" = []
    if args.image and args.platform and args.srt:
        safe_px = int(round(PLATFORMS[args.platform]["safe"]["bottom"] * args.height))
        overlap = (vis_h + safe_px) - args.height
        if args.position in ("strip", "bottom") and overlap > 0:
            notes.append(f"the visualisation band and {args.platform}'s bottom safe zone overlap by "
                         f"{overlap}px: the captions or the app's own UI will sit over the waveform "
                         f"(lower --vis-height to {max(0.05, (args.height - safe_px) / args.height):.2f})")
    duration_ok = True
    if not STATE.dry_run and meta.get("duration") and result.get("duration"):
        duration_ok = abs(float(result["duration"]) - float(meta["duration"])) <= 0.05
        if not duration_ok:
            notes.append("the render is " + fmt_secs(result.get("duration")) + " against "
                         + fmt_secs(meta.get("duration")) + " of audio")
    size_ok = (v.get("width"), v.get("height")) == (args.width, args.height) or STATE.dry_run
    # the rate the run announced is the rate the file must carry: the audiogram path builds the
    # plate as a second input, so getting this wrong is silent (see the -framerate above)
    fps_ok = True
    if not STATE.dry_run and v.get("fps"):
        fps_ok = abs(float(v["fps"]) - float(args.fps)) <= 0.01
        if not fps_ok:
            notes.append(f"the render is {float(v['fps']):g} fps against the {args.fps:g} fps asked for")
    # reported on every run, not only an audiogram one: a caller that keys on `audiogram.background`
    # should not have to guess whether the key exists (`"color"` is the plain-waveform answer).
    extra = {"audiogram": {
        "style": args.style,
        "background": "image" if args.image else "color",
        "image": args.image,
        "position": args.position if args.image else None,
        "vis_height": args.vis_height if args.image else 1.0,
        "platform": args.platform,
        "captions": (args.srt or args.text) if (args.srt or args.text) else None,
        "title": args.title,
        "stages": stages,
        # a dry run rendered nothing, so there is nothing to have verified -- the common
        # top-level `verified` says false for the same run and these two must not disagree
        "verified": False if STATE.dry_run else bool(duration_ok and size_ok and fps_ok),
    }}
    if notes:
        extra["notes"] = notes
    info(f"wrote {output} ({fmt_secs(result['duration'])}, {v.get('width')}x{v.get('height')}, {args.style}"
         + (", audiogram" if args.image else "") + ")")
    emit(output, **extra)
    return 0


def _child(script_name: str, argv: "list") -> None:
    """Run one of this skill's own tools as a second process, so the code path it owns (the ASS
    generator, the drawtext template) stays the only one there is."""
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(here, script_name)] + [str(a) for a in argv]
    if STATE.dry_run:
        cmd.append("--dry-run")
    info("-> " + " ".join(os.path.basename(c) if c.endswith(".py") else str(c) for c in cmd[1:]))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        die(f"{script_name} failed:\n{(proc.stderr or proc.stdout).strip()[-800:]}", kind="ffmpeg")


if __name__ == "__main__":
    sys.exit(main())
