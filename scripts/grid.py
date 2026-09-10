#!/usr/bin/env python3
"""Composite several video clips into one COLSxROWS grid, e.g. a 4x2 wall of
takes, angles, or A/B renders side by side.

Every cell is letterboxed (not stretched) to a common --cell-width/--cell-height
so clips of different aspect ratios and resolutions line up cleanly. By default
each cell gets its source filename (extension stripped) burnt into the bottom
right corner -- --label none turns that off. The grid has no audio unless
--audio-from picks one input's track to carry through; mixing every clip's
audio together is rarely what a comparison grid is for, so this tool never
does it silently.

The grid runs only as long as its shortest clip (--shortest, the default) or
is padded to the longest with black+silence (--pad); a mismatched frame rate
across sources is conformed to --fps first so cells stay in sync.

Examples:
  python3 grid.py take1.mp4 take2.mp4 take3.mp4 take4.mp4 take5.mp4 take6.mp4 take7.mp4 take8.mp4 --cols 4 --rows 2
  python3 grid.py a.mp4 b.mp4 c.mp4 d.mp4 --cols 2 --rows 2 --label none -o compare.mp4
  python3 grid.py cam1.mp4 cam2.mp4 --cols 2 --rows 1 --audio-from 0 --pad
"""
import argparse
import os
import sys

from _common import add_common, apply_common, aac_args, cfr_args, default_font_file, default_output, die, emit, \
    escape_drawtext, escape_filter_path, ffmpeg_base, info, probe, run, validate_color, video_args

LABEL_MARGIN = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="video clips, filled into the grid left-to-right, top-to-bottom")
    ap.add_argument("-o", "--output", help="output file (default: <first name>_grid.<ext>)")
    ap.add_argument("--cols", type=int, required=True, help="grid columns")
    ap.add_argument("--rows", type=int, required=True, help="grid rows")
    ap.add_argument("--cell-width", type=int, default=480, help="each cell's width in px, must be even (default 480)")
    ap.add_argument("--cell-height", type=int, default=270, help="each cell's height in px, must be even (default 270)")
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate every cell is conformed to (default 30)")
    ap.add_argument("--label", choices=["auto", "none"], default="auto",
                     help="auto (default): burn each cell's filename (extension stripped) into its bottom-right corner; none: no label")
    ap.add_argument("--font", default="DejaVu Sans", help="label font (fontconfig family name, default DejaVu Sans)")
    ap.add_argument("--font-size", type=int, default=16, help="label font size (default 16)")
    ap.add_argument("--font-color", default="white", help="label text colour (default white)")
    ap.add_argument("--pad", action="store_true", help="pad every cell to the longest clip's duration with black+silence instead of stopping at the shortest")
    ap.add_argument("--audio-from", type=int, help="0-based index into inputs to take audio from (default: no audio)")
    ap.add_argument("--gap", type=int, default=0, help="gap between cells in px, must be even (default 0, cells touch)")
    ap.add_argument("--background", default="black", help="colour of the gap/pad borders (default black)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    n = args.cols * args.rows
    if args.cols <= 0 or args.rows <= 0:
        die(f"--cols/--rows must be > 0, got cols={args.cols} rows={args.rows}")
    if len(args.inputs) != n:
        die(f"--cols {args.cols} --rows {args.rows} needs exactly {n} inputs, got {len(args.inputs)}")
    if args.cell_width <= 0 or args.cell_height <= 0:
        die(f"--cell-width/--cell-height must be > 0, got width={args.cell_width} height={args.cell_height}")
    if args.cell_width % 2 or args.cell_height % 2:
        die(f"--cell-width/--cell-height must be even (4:2:0 chroma), got width={args.cell_width} height={args.cell_height}")
    if args.fps <= 0:
        die(f"--fps must be > 0, got {args.fps:g}")
    if args.gap < 0 or args.gap % 2:
        die(f"--gap must be >= 0 and even, got {args.gap}")
    validate_color(args.background, "--background")
    if args.font_color:
        validate_color(args.font_color, "--font-color")
    if args.audio_from is not None and not 0 <= args.audio_from < n:
        die(f"--audio-from {args.audio_from}: must be an input index 0..{n - 1}")

    metas = [probe(p) for p in args.inputs]
    for p, m in zip(args.inputs, metas):
        if not m.get("video"):
            die(f"{p}: input has no video stream")
    if args.audio_from is not None and not metas[args.audio_from].get("audio"):
        die(f"--audio-from {args.audio_from}: {args.inputs[args.audio_from]} has no audio stream")

    durations = [m.get("duration") or 0.0 for m in metas]
    target_duration = max(durations) if args.pad else min(durations)

    font_file = default_font_file(args.font)
    output = args.output or default_output(args.inputs[0], "grid")

    cmd = ffmpeg_base()
    for p in args.inputs:
        cmd += ["-i", p]

    parts = []
    for i, p in enumerate(args.inputs):
        chain = [
            f"fps={args.fps:g}",
            f"scale={args.cell_width}:{args.cell_height}:force_original_aspect_ratio=decrease",
            f"pad={args.cell_width}:{args.cell_height}:(ow-iw)/2:(oh-ih)/2:color={args.background}",
            "setsar=1",
        ]
        if args.pad and durations[i] < target_duration:
            chain.append(f"tpad=stop_mode=clone:stop_duration={target_duration - durations[i]:.3f}")
        elif not args.pad:
            chain.append(f"trim=duration={target_duration:.3f}")
        if args.label == "auto":
            stem = os.path.splitext(os.path.basename(p))[0]
            font_opt = f"fontfile={escape_filter_path(font_file)}" if font_file else f"font='{escape_drawtext(args.font)}'"
            chain.append(f"drawtext=text='{escape_drawtext(stem)}':{font_opt}:fontsize={args.font_size}:"
                         f"fontcolor={args.font_color}:x=w-tw-{LABEL_MARGIN}:y=h-th-{LABEL_MARGIN}:"
                         f"box=1:boxcolor=black@0.5:boxborderw=4")
        parts.append(f"[{i}:v]{','.join(chain)}[v{i}]")

    cw, ch = args.cell_width + args.gap, args.cell_height + args.gap
    layout = "|".join(f"{c * cw}_{r * ch}" for r in range(args.rows) for c in range(args.cols))
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill={args.background}[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]"]

    if args.audio_from is not None:
        cmd += ["-map", f"{args.audio_from}:a:0"]
    cmd += video_args(None, args.crf, args.preset)
    cmd += cfr_args(None, args.fps)
    if args.audio_from is not None:
        cmd += aac_args()
    else:
        cmd += ["-an"]
    cmd += ["-t", f"{target_duration:.3f}", output]
    run(cmd)

    result = probe(output, role="output")
    v = result["video"]
    info(f"wrote {output} ({result['duration']:.3f}s, {v['width']}x{v['height']}, {args.cols}x{args.rows} grid, "
         f"{n} clips, {'padded to longest' if args.pad else 'stopped at shortest'})")
    emit(output, cols=args.cols, rows=args.rows, clips=n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
