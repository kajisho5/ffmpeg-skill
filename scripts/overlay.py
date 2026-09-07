#!/usr/bin/env python3
"""Composite a logo/image or a text title onto a video with position, timing,
opacity and fade in/out.

Positions: top-left, top, top-right, left, center, right, bottom-left, bottom,
bottom-right, or explicit "X,Y" pixels (negative counts from the far edge).

--video composites a second VIDEO as a picture-in-picture layer (position,
scale, opacity, time-range -- same knobs as --image), instead of a still
image or text. Only the main input's audio is kept; the PiP layer's own
audio track, if any, is dropped -- mixing two audio tracks is a job for
audio.py, not this tool. --chromakey COLOR (with --video) turns that colour
transparent first (green-screen removal) before compositing.

Examples:
  python3 overlay.py input.mp4 --image logo.png --position top-right --scale 200 --opacity 0.8
  python3 overlay.py input.mp4 --image lower_third.png --position bottom-left --start 2 --end 8 --fade 0.5
  python3 overlay.py input.mp4 --text "Episode 12" --position bottom --font-size 48 --start 1 --end 5 --fade 0.3
  python3 overlay.py input.mp4 --text "こんにちは" --font-file /path/NotoSansCJK-Bold.ttc --box
  python3 overlay.py input.mp4 --video webcam.mp4 --position bottom-right --scale 480 --opacity 0.9
  python3 overlay.py bg.mp4 --video greenscreen.mp4 --chromakey 0x00ff00 --chromakey-similarity 0.15
"""
import argparse
import sys
from typing import List, Optional

from _common import STATE, load_brand, video_args, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_drawtext, escape_filter_path, ffmpeg_base, info, parse_time, probe, run, run_keeping_subtitles, x264_args

POS = {
    "top-left": ("{m}", "{m}"),
    "top": ("(W-w)/2", "{m}"),
    "top-right": ("W-w-{m}", "{m}"),
    "left": ("{m}", "(H-h)/2"),
    "center": ("(W-w)/2", "(H-h)/2"),
    "right": ("W-w-{m}", "(H-h)/2"),
    "bottom-left": ("{m}", "H-h-{m}"),
    "bottom": ("(W-w)/2", "H-h-{m}"),
    "bottom-right": ("W-w-{m}", "H-h-{m}"),
}


def position_exprs(pos: str, margin: int, text_mode: bool):
    if pos in POS:
        x, y = (e.format(m=margin) for e in POS[pos])
    else:
        try:
            xs, ys = pos.split(",")
            xv, yv = int(xs), int(ys)
        except ValueError:
            die(f"bad --position '{pos}'")
        x = f"W-w{xv}" if xv < 0 else str(xv)
        y = f"H-h{yv}" if yv < 0 else str(yv)
    if text_mode:
        # drawtext uses w/h for the text box but lower-case main dims differ: W/H -> w/h, w/h -> text_w/text_h
        x = x.replace("W", "main_w").replace("w", "text_w").replace("H", "main_h").replace("h", "text_h")
        y = y.replace("W", "main_w").replace("w", "text_w").replace("H", "main_h").replace("h", "text_h")
        x = x.replace("main_text_w", "main_w").replace("main_text_h", "main_h")
        y = y.replace("main_text_w", "main_w").replace("main_text_h", "main_h")
    return x, y


def enable_expr(start: Optional[float], end: Optional[float]) -> str:
    if start is None and end is None:
        return ""
    s = f"{start:.3f}" if start is not None else "0"
    if end is None:
        return f"gte(t,{s})"
    return f"between(t,{s},{end:.3f})"


def alpha_expr(opacity: float, start: Optional[float], end: Optional[float], fade: float) -> str:
    """Time-varying alpha with linear fade in/out inside [start, end]."""
    if fade <= 0 or (start is None and end is None):
        return f"{opacity:g}"
    s = start if start is not None else 0.0
    parts = [f"{opacity:g}"]
    fin = f"min(1,(t-{s:.3f})/{fade:g})"
    parts.append(fin)
    if end is not None:
        parts.append(f"min(1,({end:.3f}-t)/{fade:g})")
    return "max(0," + "*".join(parts) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_overlay.<ext>)")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--image", help="PNG/JPG (alpha respected) to composite")
    src.add_argument("--text", help="text to draw (drawtext)")
    src.add_argument("--logo", action="store_true", help="composite the brand logo from --brand (position/scale/opacity from brand.json)")
    src.add_argument("--video", help="a second video to composite as a picture-in-picture layer")
    ck = ap.add_argument_group("chroma key (with --video)")
    ck.add_argument("--chromakey", help="colour to key out (green-screen removal), e.g. 0x00ff00 or green")
    ck.add_argument("--chromakey-similarity", type=float, default=0.15, help="how close a pixel must be to --chromakey to become transparent, 0..1 (default 0.15)")
    ck.add_argument("--chromakey-blend", type=float, default=0.05, help="soften the key edge, 0..1 (default 0.05)")
    ap.add_argument("--brand", help="brand.json (logo, font, colours, safe margin)")
    ap.add_argument("--position", default="top-right", help="named position or X,Y (default top-right)")
    ap.add_argument("--margin", type=int, default=24, help="margin from the edges in px (default 24)")
    ap.add_argument("--start", help="show from this time (default: whole video)")
    ap.add_argument("--end", help="hide after this time")
    ap.add_argument("--fade", type=float, default=0.0, help="fade in/out duration in seconds")
    ap.add_argument("--opacity", type=float, default=1.0, help="0..1 (default 1)")
    img = ap.add_argument_group("image options")
    img.add_argument("--scale", type=int, help="scale the image to this width in px (keeps aspect)")
    img.add_argument("--scale-percent", type=float, help="scale the image to this %% of the video width")
    txt = ap.add_argument_group("text options")
    txt.add_argument("--font", default="DejaVu Sans", help="fontconfig font name")
    txt.add_argument("--font-file", help="explicit .ttf/.otf/.ttc path (use this for CJK fonts)")
    txt.add_argument("--font-size", type=int, default=42)
    txt.add_argument("--font-color", default="white")
    txt.add_argument("--border", type=int, default=2, help="text outline width (default 2)")
    txt.add_argument("--border-color", default="black")
    txt.add_argument("--box", action="store_true", help="draw a translucent box behind the text")
    txt.add_argument("--box-color", default="black@0.5")
    enc = ap.add_argument_group("encoding")
    enc.add_argument("--crf", type=int, default=18)
    enc.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    brand = load_brand(args.brand)
    if args.logo:
        if not brand.get("logo"):
            die("--logo needs a brand.json with a 'logo' entry")
        args.image = brand["logo"]
        if args.position == ap.get_default("position"):
            args.position = brand.get("logo_position", "top-right")
        if not args.scale and not args.scale_percent:
            args.scale = int(brand.get("logo_scale", 160))
        if args.opacity == 1.0:
            args.opacity = float(brand.get("logo_opacity", 1.0))
    if not (args.image or args.text or args.video):
        die("give --image, --text, --logo or --video")
    if args.brand:
        if args.margin == ap.get_default("margin"):
            args.margin = int(brand.get("safe_margin", args.margin))
        if args.font == ap.get_default("font"):
            args.font = brand.get("font", args.font)
        if not args.font_file and brand.get("font_file"):
            args.font_file = brand["font_file"]
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    audio_streams = meta.get("audio_streams") or []
    if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
        die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
    if args.audio_stream and not audio_streams:
        die("--audio-stream needs an input with audio streams")
    vw = meta["video"]["width"]
    start = parse_time(args.start) if args.start else None
    end = parse_time(args.end) if args.end else None
    if start is not None and end is not None and end <= start:
        die("--end must be after --start")
    if not 0 <= args.opacity <= 1:
        die("--opacity must be within 0..1")
    if args.chromakey and not args.video:
        die("--chromakey needs --video")
    if not 0 < args.chromakey_similarity <= 1:
        die("--chromakey-similarity must be within (0, 1]")
    if not 0 <= args.chromakey_blend <= 1:
        die("--chromakey-blend must be within 0..1")

    output = args.output or default_output(args.input, "overlay")
    enable = enable_expr(start, end)
    cmd = ffmpeg_base() + ["-i", args.input]

    if args.image:
        probe(args.image)
        chain: List[str] = ["format=rgba"]
        if args.scale_percent:
            chain.append(f"scale={int(vw * args.scale_percent / 100)}:-1")
        elif args.scale:
            chain.append(f"scale={args.scale}:-1")
        if args.opacity < 1:
            chain.append(f"colorchannelmixer=aa={args.opacity:g}")
        if args.fade > 0:
            # no --start/--end: fade in at 0 and out at the end of the video
            s = start if start is not None else 0.0
            e = end if end is not None else (meta.get("duration") or 0.0)
            chain.append(f"fade=t=in:st={s:.3f}:d={args.fade:g}:alpha=1")
            if e > args.fade:
                chain.append(f"fade=t=out:st={e - args.fade:.3f}:d={args.fade:g}:alpha=1")
        x, y = position_exprs(args.position, args.margin, text_mode=False)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        # -loop 1 turns the still into a timed stream so fade/enable expressions see real timestamps
        cmd = ffmpeg_base() + ["-i", args.input, "-loop", "1", "-i", args.image]
        fc = f"[1:v]{','.join(chain)},setpts=PTS-STARTPTS[ov];[0:v][ov]{ov}[out]"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", f"0:a:{args.audio_stream}?"]
        if meta.get("duration"):
            # An explicit -t is exact and, unlike -shortest, only bounds the *main* input's
            # streams -- a preserved subtitle/data stream that ends earlier (run_keeping_subtitles)
            # must not be allowed to cut the whole output short via -shortest's "stop at whichever
            # mapped stream finishes first" semantics.
            cmd += ["-t", f"{meta['duration']:.3f}"]
        else:
            # No known duration to bound by -t (e.g. probe found no video duration): -shortest is
            # the only thing stopping the looped still from running forever. FFmpeg 7+'s
            # shortest_buf_duration slack (up to 10s) is an accepted imprecision here since there is
            # no better bound available.
            cmd += ["-shortest"]
    elif args.video:
        pip_meta = probe(args.video)
        if not pip_meta.get("video"):
            die(f"--video {args.video} has no video stream")
        chain = []
        if args.scale_percent:
            chain.append(f"scale={int(vw * args.scale_percent / 100)}:-2")
        elif args.scale:
            chain.append(f"scale={args.scale}:-2")
        chain.append("format=yuva420p")
        if args.chromakey:
            chain.append(f"chromakey={args.chromakey}:{args.chromakey_similarity:g}:{args.chromakey_blend:g}")
        if args.opacity < 1:
            chain.append(f"colorchannelmixer=aa={args.opacity:g}")
        x, y = position_exprs(args.position, args.margin, text_mode=False)
        ov = f"overlay={x}:{y}:format=auto"
        if enable:
            ov += f":enable='{enable}'"
        cmd = ffmpeg_base() + ["-i", args.input, "-i", args.video]
        fc = f"[1:v]{','.join(chain)}[ov];[0:v][ov]{ov}[out]"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map", f"0:a:{args.audio_stream}?"]
        if meta.get("duration"):
            # See the --image branch above: -t (exact, bounds only the main input) instead of
            # -shortest (would also stop at a preserved subtitle/data stream that ends earlier).
            cmd += ["-t", f"{meta['duration']:.3f}"]
        else:
            cmd += ["-shortest"]
    else:
        x, y = position_exprs(args.position, args.margin, text_mode=True)
        opts = [f"text='{escape_drawtext(args.text)}'", f"fontsize={args.font_size}", f"x={x}", f"y={y}",
                f"borderw={args.border}", f"bordercolor={args.border_color}"]
        if args.font_file:
            opts.append(f"fontfile={escape_filter_path(args.font_file)}")
        else:
            opts.append(f"font='{args.font}'")
        alpha = alpha_expr(args.opacity, start if start is not None else (0.0 if args.fade > 0 else None),
                           end if end is not None else ((meta.get("duration") or None) if args.fade > 0 else None), args.fade)
        opts.append(f"fontcolor={args.font_color}")
        if alpha != "1":
            opts.append(f"alpha='{alpha}'")
        if args.box:
            opts += ["box=1", f"boxcolor={args.box_color}", "boxborderw=12"]
        if enable:
            opts.append(f"enable='{enable}'")
        cmd += ["-vf", "drawtext=" + ":".join(opts), "-map", "0:v:0"]
        if meta.get("audio"):
            cmd += ["-map", f"0:a:{args.audio_stream}"]

    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += aac_args() if meta.get("audio") else ["-an"]
    dropped_streams = run_keeping_subtitles(cmd, output)
    if not STATE.dry_run:
        result = probe(output, role="output")
        info(f"wrote {output} ({result['duration']:.3f}s)")
    emit(output, dropped_non_av_streams=dropped_streams)
    return 0


if __name__ == "__main__":
    sys.exit(main())
