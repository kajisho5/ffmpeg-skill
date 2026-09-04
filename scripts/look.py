#!/usr/bin/env python3
"""Give the agent eyes: pull frames or a contact sheet out of a video as PNG so
the result can be inspected (caption placement, logo position, crop, colour).

Examples:
  python3 look.py final.mp4                          # 12-tile contact sheet with timecodes -> final_sheet.png
  python3 look.py final.mp4 --tiles 4x5 --width 1600
  python3 look.py final.mp4 --at 2.5 --at 7          # single frames -> final_2.500s.png, final_7.000s.png
  python3 look.py before.mp4 --compare after.mp4 --at 4   # side-by-side frame
Then view the PNG (Read tool / image viewer) and verify before reporting.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List

from _common import add_common, apply_common, die, emit, escape_drawtext, ffmpeg_base, info, parse_time, probe, run

FONT = "fontcolor=white:fontsize=h/18:box=1:boxcolor=black@0.55:boxborderw=6:x=8:y=8"


def fmt_hms(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s_ = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s_:06.3f}"


def timecode_filter() -> str:
    return f"drawtext=text='%{{pts\\:hms}}':{FONT}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output PNG (contact sheet / compare) or basename for --at frames")
    ap.add_argument("--at", action="append", help="time of a frame to extract (repeatable)")
    ap.add_argument("--tiles", default="4x3", help="contact sheet grid COLSxROWS (default 4x3)")
    ap.add_argument("--width", type=int, default=1280, help="total width of the sheet / compare image (default 1280)")
    ap.add_argument("--compare", help="second video: place its frame next to the first (needs --at)")
    ap.add_argument("--no-timecode", action="store_true")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")
    dur = meta.get("duration") or 0.0
    stem = Path(args.input).stem
    outdir = str(Path(args.output).parent) if args.output else str(Path(args.input).parent)
    tc = "" if args.no_timecode else "," + timecode_filter()
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
        for t in args.at:
            sec = parse_time(t)
            out = args.output or os.path.join(outdir, f"{stem}_vs_{Path(args.compare).stem}_{sec:.3f}s.png")
            half = args.width // 2
            stamp = "" if args.no_timecode else f",drawtext=text='{escape_drawtext(fmt_hms(sec))}':{FONT}"
            tcs = tc.replace("," + timecode_filter(), "") + stamp
            fc = (f"[0:v]scale={half}:-2{tcs}[a];[1:v]scale={half}:-2{tcs}[b];"
                  f"[a][b]scale2ref=w=iw:h=ih[a2][b2];[a2][b2]hstack=inputs=2[out]")
            cmd = ffmpeg_base() + ["-ss", f"{sec:.3f}", "-i", args.input, "-ss", f"{sec:.3f}", "-i", args.compare,
                                   "-filter_complex", fc, "-map", "[out]", "-frames:v", "1", out]
            run(cmd)
            outputs.append(out)
    elif args.at:
        for t in args.at:
            sec = parse_time(t)
            if dur and sec > dur:
                die(f"--at {t} is beyond the duration ({dur:.2f}s)")
            out = os.path.join(outdir, f"{args.output and Path(args.output).stem or stem}_{sec:.3f}s.png")
            stamp = "" if args.no_timecode else f",drawtext=text='{escape_drawtext(fmt_hms(sec))}':{FONT}"
            cmd = ffmpeg_base() + ["-ss", f"{sec:.3f}", "-i", args.input, "-vf", f"scale={args.width}:-2{tc.replace(',' + timecode_filter(), '')}{stamp}", "-frames:v", "1", out]
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
        step = dur / n
        tile_w = max(2, (args.width // cols) // 2 * 2)
        out = args.output or os.path.join(outdir, f"{stem}_sheet.png")
        # sample at the middle of each slice so the first/last tiles are not black lead-in/out frames
        vf = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step * 0.98:.6f})',scale={tile_w}:-2{tc},"
              f"tile={cols}x{rows}:padding=2:margin=2:color=0x202020")
        cmd = ffmpeg_base() + ["-ss", f"{step / 2:.6f}", "-i", args.input, "-vf", vf, "-frames:v", "1", out]
        run(cmd)
        outputs.append(out)
        info(f"contact sheet: {n} frames every {step:.2f}s")

    for o in outputs:
        info(f"wrote {o}")
    emit(outputs[0] if len(outputs) == 1 else None, outputs=outputs)
    if len(outputs) > 1 and not args.json:
        for o in outputs:
            print(o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
