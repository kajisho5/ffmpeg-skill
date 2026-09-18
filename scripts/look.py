#!/usr/bin/env python3
"""Give the agent eyes: pull frames or a contact sheet out of a video as PNG so
the result can be inspected (caption placement, logo position, crop, colour).

Examples:
  python3 look.py final.mp4                          # 12-tile contact sheet with timecodes -> final_sheet.png
  python3 look.py final.mp4 --tiles 4x5 --width 1600
  python3 look.py final.mp4 --at 2.5 --at 7          # single frames -> final_2.500s.png, final_7.000s.png
  python3 look.py before.mp4 --compare after.mp4 --at 4   # side-by-side frame
  python3 look.py reel.mp4 --safe tiktok --at 3          # shade what TikTok's own UI covers
Then view the PNG (Read tool / image viewer) and verify before reporting.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from _platforms import PLATFORMS, PLATFORM_CHOICES, resolve as resolve_platform
from _common import STATE, add_common, apply_common, default_font_file, die, emit, escape_drawtext, escape_filter_path, ffmpeg_base, info, parse_time, probe, run, run_analysis, time_arg

FONT = "fontcolor=white:fontsize=h/18:box=1:boxcolor=black@0.55:boxborderw=6:x=8:y=8"


def fmt_hms(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s_ = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s_:06.3f}"


def timecode_filter(font_prefix: str) -> str:
    return f"drawtext=text='%{{pts\\:hms}}':{font_prefix}{FONT}"


def _png_size(png_path: str) -> "Optional[tuple]":
    # run_analysis(): the same wall-clock ceiling and #234 UTF-8 decoding as every other
    # ffprobe/ffmpeg measurement in this codebase, check=False since a probe failure here is
    # an unknown-metric result (has_ink: None), not a reason to die -- a stall still does,
    # exactly like every other measurement's timeout.
    proc = run_analysis(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height", "-of", "csv=p=0", png_path], check=False)
    parts = proc.stdout.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _png_pixels(png_path: str, w: int, h: int) -> "Optional[bytes]":
    proc = run_analysis(["ffmpeg", "-v", "error", "-i", png_path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                        check=False, text=False)
    data = proc.stdout
    return data if len(data) >= w * h * 3 else None


def measure_ink(png_path: str, *, box=None, margin_frac: float = 0.03, threshold: int = 28) -> dict:
    """Non-background ink in `png_path` (or the `box` = (x0, y0, w, h) sub-region of it): a pixel-only
    measurement, never a judgement of legibility. The background is estimated as the median RGB of a
    thin strip around the region's own edge (so it works on any frame, not just a black synthetic one);
    a pixel is "ink" when any channel differs from that estimate by more than `threshold`. Returns
    {has_ink, bbox (x0,y0,x1,y1 within the region, or None), ink_fraction, row_bands} -- row_bands are
    gap-merged bands of rows carrying ink, the same convention tests/_fixtures.py's _ass_ink_rows uses,
    so a caption wrapped onto two lines shows as two bands without measuring any font."""
    size = _png_size(png_path)
    if not size:
        return {"has_ink": None, "bbox": None, "ink_fraction": None, "row_bands": []}
    full_w, full_h = size
    data = _png_pixels(png_path, full_w, full_h)
    if data is None:
        return {"has_ink": None, "bbox": None, "ink_fraction": None, "row_bands": []}
    if box:
        bx, by, bw, bh = box
        bx, by = max(0, bx), max(0, by)
        bw, bh = min(bw, full_w - bx), min(bh, full_h - by)
    else:
        bx, by, bw, bh = 0, 0, full_w, full_h
    if bw <= 0 or bh <= 0:
        return {"has_ink": None, "bbox": None, "ink_fraction": None, "row_bands": []}

    def px(x, y):
        off = ((by + y) * full_w + (bx + x)) * 3
        return data[off], data[off + 1], data[off + 2]

    margin = max(1, int(min(bw, bh) * margin_frac))
    border = []
    for x in range(0, bw, max(1, bw // 40 or 1)):
        border.append(px(x, 0))
        border.append(px(x, bh - 1))
    for y in range(0, bh, max(1, bh // 40 or 1)):
        border.append(px(0, y))
        border.append(px(bw - 1, y))
    if not border:
        border = [px(0, 0)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))

    lit_rows = []
    min_x = min_y = None
    max_x = max_y = None
    ink_count = 0
    for y in range(bh):
        row_lit = False
        for x in range(bw):
            r, g, b = px(x, y)
            if abs(r - bg[0]) > threshold or abs(g - bg[1]) > threshold or abs(b - bg[2]) > threshold:
                row_lit = True
                ink_count += 1
                min_x = x if min_x is None else min(min_x, x)
                max_x = x if max_x is None else max(max_x, x)
                min_y = y if min_y is None else min(min_y, y)
                max_y = y if max_y is None else max(max_y, y)
        if row_lit:
            lit_rows.append(y)

    bands = []
    for y in lit_rows:
        if bands and y - bands[-1][1] <= margin:
            bands[-1][1] = y
        else:
            bands.append([y, y])

    has_ink = min_x is not None
    return {
        "has_ink": has_ink,
        "bbox": [min_x, min_y, max_x, max_y] if has_ink else None,
        "ink_fraction": round(ink_count / (bw * bh), 4) if bw * bh else 0.0,
        "row_bands": [list(b) for b in bands],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output PNG (contact sheet / compare) or basename for --at frames")
    ap.add_argument("--at", action="append", help="time of a frame to extract (repeatable)")
    ap.add_argument("--tiles", default="4x3", help="contact sheet grid COLSxROWS (default 4x3)")
    ap.add_argument("--width", type=int, default=1280, help="total width of the sheet / compare image (default 1280)")
    ap.add_argument("--compare", help="second video: place its frame next to the first (needs --at)")
    ap.add_argument("--no-timecode", action="store_true")
    ap.add_argument("--safe", choices=PLATFORM_CHOICES, help="shade the zones this platform's UI covers (its description bar, "
                                                       "like column, status bar) so you can see whether anything readable is under them")
    ap.add_argument("--ink", action="store_true", help="measure non-background pixels in each written PNG (bbox, "
                                                 "ink_fraction, row_bands per tile for a contact sheet) instead of "
                                                 "just eyeballing it -- a pixel-only signal, not a legibility judgement")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = meta.get("duration") or 0.0
    stem = Path(args.input).stem
    outdir = str(Path(args.output).parent) if args.output else str(Path(args.input).parent)
    # a resolvable font file, given as fontfile=, is the only form confirmed not to crash drawtext's
    # own fontconfig resolution on some real Windows ffmpeg builds (#100); font= is the fallback when
    # nothing can be resolved, unchanged from before this existed.
    default_font = default_font_file("DejaVu Sans")
    font_prefix = f"fontfile={escape_filter_path(default_font)}:" if default_font else ""
    tc = "" if args.no_timecode else "," + timecode_filter(font_prefix)
    # --safe: the platform's occluded zones, drawn as shaded boxes in fractions of the frame so
    # the same filter is right at any scale (a tile of a contact sheet as much as a full frame).
    safe_filter = ""
    args.safe = resolve_platform(args.safe)
    if args.safe and not PLATFORMS[args.safe].get("frame"):
        info(f"--safe {args.safe}: this destination has no frame and no app chrome; nothing to shade")
        args.safe = None
    if args.safe:
        z = PLATFORMS[args.safe]["safe"]
        frame = PLATFORMS[args.safe]["frame"]
        src = meta["video"]
        if src.get("width") and src.get("height") and abs(src["width"] / src["height"] - frame["w"] / frame["h"]) > 0.02:
            info(f"--safe {args.safe}: this source is {src['width']}x{src['height']}, not {args.safe}'s "
                 f"{frame['w']}x{frame['h']} -- the zones are drawn as fractions of the frame you gave, "
                 f"so reframe first (fit.py --aspect) to see what the app really covers")
        boxes = []
        for edge, frac in (("top", z["top"]), ("bottom", z["bottom"]), ("left", z["left"]), ("right", z["right"])):
            if frac <= 0:
                continue
            if edge == "top":
                boxes.append(f"drawbox=x=0:y=0:w=iw:h=ih*{frac:g}:color=red@0.35:t=fill")
            elif edge == "bottom":
                boxes.append(f"drawbox=x=0:y=ih*(1-{frac:g}):w=iw:h=ih*{frac:g}:color=red@0.35:t=fill")
            elif edge == "left":
                boxes.append(f"drawbox=x=0:y=0:w=iw*{frac:g}:h=ih:color=red@0.20:t=fill")
            else:
                boxes.append(f"drawbox=x=iw*(1-{frac:g}):y=0:w=iw*{frac:g}:h=ih:color=red@0.20:t=fill")
        safe_filter = "," + ",".join(boxes) if boxes else ""
        info(f"--safe {args.safe}: shaded top {z['top'] * 100:.0f}% / bottom {z['bottom'] * 100:.0f}% / "
             f"left {z['left'] * 100:.0f}% / right {z['right'] * 100:.0f}% of the frame -- keep text out of those")
    tc = safe_filter + tc
    # HDR sources: tone-map for the PNG so the agent judges representative colours, not raw HLG/PQ
    if meta["video"].get("hdr"):
        v = meta["video"]
        tm = (f"zscale=tin={v.get('color_transfer') or 'arib-std-b67'}:pin={v.get('color_primaries') or 'bt2020'}:min={v.get('color_space') or 'bt2020nc'}:rin=tv:t=linear:npl=1000,"
              "format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
        tc = "," + tm.rstrip(",") + tc
        info("HDR source: frames are tone-mapped to SDR for display")
    outputs: List[str] = []

    if args.compare:
        if not args.at:
            die("--compare needs --at TIME")
        probe(args.compare)
        for idx, t in enumerate(args.at):
            sec = time_arg(t, "--at", meta["video"].get("fps") if meta.get("video") else None)
            if args.output and len(args.at) == 1:
                out = args.output  # one frame, one named image file: the caller's -o is the contract
            else:
                # several frames, or -o given as a stem/prefix: an occurrence index keeps every
                # requested --at its own file even when two round to the same millisecond
                stem_part = (args.output and Path(args.output).stem) or stem
                out = os.path.join(outdir, f"{stem_part}_vs_{Path(args.compare).stem}_{idx}_{sec:.3f}s.png")
            half = args.width // 2
            stamp = "" if args.no_timecode else f",drawtext=text='{escape_drawtext(fmt_hms(sec))}':{font_prefix}{FONT}"
            tcs = tc.replace("," + timecode_filter(font_prefix), "") + stamp
            fc = (f"[0:v]scale={half}:-2{tcs}[a];[1:v]scale={half}:-2{tcs}[b];"
                  f"[a][b]scale2ref=w=iw:h=ih[a2][b2];[a2][b2]hstack=inputs=2[out]")
            cmd = ffmpeg_base() + ["-ss", f"{sec:.3f}", "-i", args.input, "-ss", f"{sec:.3f}", "-i", args.compare,
                                   "-filter_complex", fc, "-map", "[out]", "-frames:v", "1", out]
            run(cmd)
            outputs.append(out)
    elif args.at:
        for t in args.at:
            sec = time_arg(t, "--at", meta["video"].get("fps") if meta.get("video") else None)
            if dur and sec > dur:
                die(f"--at {t} is beyond the duration ({dur:.2f}s)")
            if args.output and len(args.at) == 1 and Path(args.output).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                out = args.output  # one frame, one named image file: the caller's -o is the contract
            else:
                # several frames, or -o given as a stem/prefix without an image extension
                out = os.path.join(outdir, f"{args.output and Path(args.output).stem or stem}_{sec:.3f}s.png")
            stamp = "" if args.no_timecode else f",drawtext=text='{escape_drawtext(fmt_hms(sec))}':{font_prefix}{FONT}"
            cmd = ffmpeg_base() + ["-ss", f"{sec:.3f}", "-i", args.input, "-vf", f"scale={args.width}:-2{tc.replace(',' + timecode_filter(font_prefix), '')}{stamp}", "-frames:v", "1", out]
            run(cmd)
            outputs.append(out)
    else:
        try:
            cols, rows = (int(x) for x in args.tiles.lower().split("x"))
        except ValueError:
            die("--tiles must look like 4x3")
        n = cols * rows
        if not dur:
            die("cannot build a contact sheet without a known duration")
        frames_avail = int((meta["video"].get("fps") or 0) * dur) or 1
        if n > frames_avail:
            # a 2x2 sheet from a one-frame clip: tile waits for frames that never come and writes nothing
            cols, rows = min(cols, frames_avail), 1
            n = cols * rows
            info(f"only {frames_avail} frame(s) available; sheet reduced to {cols}x{rows}")
        step = dur / n
        tile_w = max(2, (args.width // cols) // 2 * 2)
        out = args.output or os.path.join(outdir, f"{stem}_sheet.png")
        # sample at the middle of each slice so the first/last tiles are not black lead-in/out frames
        vf = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step * 0.98:.6f})',scale={tile_w}:-2{tc},"
              f"tile={cols}x{rows}:padding=2:margin=2:color=0x202020")
        # with only a handful of frames a mid-slice seek skips past them all: start at 0 instead
        seek = 0.0 if frames_avail < 4 else step / 2
        cmd = ffmpeg_base() + ["-ss", f"{seek:.6f}", "-i", args.input, "-vf", vf, "-frames:v", "1", out]
        run(cmd)
        outputs.append(out)
        info(f"contact sheet: {n} frames every {step:.2f}s")

    for o in outputs:
        if STATE.dry_run or os.path.exists(o):
            info(f"wrote {o}")

    ink = None
    if args.ink and not STATE.dry_run:
        if outputs and args.at is None and not args.compare:
            # contact sheet: one PNG holding a cols x rows grid (tile_w:padding=2:margin=2, as built above)
            # -- split it back into per-tile boxes so each tile is measured on its own, not the whole sheet.
            sheet = outputs[0]
            size = _png_size(sheet)
            if size:
                full_w, full_h = size
                margin, padding = 2, 2
                th = (full_h - 2 * margin - (rows - 1) * padding) // rows if rows else full_h
                tiles = []
                for r in range(rows):
                    for c in range(cols):
                        bx = margin + c * (tile_w + padding)
                        by = margin + r * (th + padding)
                        tiles.append(measure_ink(sheet, box=(bx, by, tile_w, th)))
                ink = {"tiles": tiles}
        else:
            ink = {"frames": [measure_ink(o) for o in outputs]}

    emit(outputs[0] if len(outputs) == 1 else None, outputs=outputs, **({"ink": ink} if ink is not None else {}))
    if len(outputs) > 1 and not args.json:
        for o in outputs:
            print(o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
