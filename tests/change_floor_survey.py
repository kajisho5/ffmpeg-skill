#!/usr/bin/env python3
"""The survey behind check.py --expect-changed's change floors (#442): how large an unchanged tile
gets after an encode, and how small the tiles of a real small edit get, per encoder, frame size
and grid. Not a test (nothing asserts); `test_check_change_floor_holds_for_every_available_encoder`
in tests/test_analysis.py pins the decision this prints the evidence for, and
docs/design-decisions.md ("After 4.19.0 — ... (#442)") holds the table it printed.

    python3 tests/change_floor_survey.py [--quick] [--jobs 3] [--work DIR] [--json FILE]

Each source becomes a 1.5 s, 24 fps lossless mezzanine (libx264 -qp 0, the 4:2:0 picture every
delivery encoder takes) at each size it is surveyed at: every demos/footage clip and five synthetic
pictures at 1080p (all thirteen settings on the seven hardest, four common ones on the rest), four of
them at 720p and 480p and the two small clips at their own size (the --quick seven). 201
encodes, about 15 minutes with three jobs on a loaded four-core machine. Per encoder setting it is encoded twice:
untouched (`ref`) and with four edits at their own frames (`edit`): a caption cue (frames 4-9), a
60x60 logo (12-17), a 24x24 logo (20-25) and a colour tweak of the whole frame (29-33), sizes in
1080p pixels and scaled with the frame. Three differences are measured, each on the 32x18, 64x36
and 96x54 grids with check.py's own graph (8-bit RGB, blend difference, area scale, a tile's value
the largest of its channels):

- `untouched`: ref against the mezzanine, every tile. What a re-encode alone gives, the side a
  caller who compares a render with its source meets.
- `spill`: edit against ref, the tiles no edit covers in that frame. What an edit leaves elsewhere
  when both files come from the same encoder settings, the side check.py's docs ask for.
- per edit, the smallest of its frames' largest tile inside the edit (edit against ref): what the
  floor must stay under for the edit to be found.

Hardware encoders (NVENC, QSV, VAAPI, VideoToolbox, AMF) are not measured: this machine has none.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOOTAGE = ROOT / "demos" / "footage"
GRIDS = ((32, 18), (64, 36), (96, 54))
FRAMES, RATE = 36, 24
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SIZES = {"1080p": (1920, 1080), "720p": (1280, 720), "480p": (854, 480)}

# every 1080p clip in demos/footage, then synthetic content; the small native clips at their own size
FOOTAGE_1080 = ["real_city", "real_fireworks", "real_sea", "veo_basketball", "veo_greenscreen", "veo_hall", "veo_hands",
                "veo_pause_en", "veo_rain", "veo_sea", "veo_talk_en", "veo_talk_ja"]
FOOTAGE_NATIVE = {"ai_talk": (640, 430), "ai_talk_en": (854, 480)}
SYNTHETIC = {
    "testsrc2": "testsrc2=size={w}x{h}:rate=24",
    "noise": "color=c=gray:size={w}x{h}:rate=24,noise=alls=40:allf=t+u",
    "gradients": "gradients=size={w}x{h}:rate=24:speed=0.02",
    "dark": "color=c=0x101418:size={w}x{h}:rate=24,noise=alls=12:allf=t+u,drawbox=x=iw/3:y=ih/3:w=iw/4:h=ih/4:color=0x302820:t=fill",
    "fast_pan": "testsrc2=size={w2}x{h}:rate=24,crop={w}:{h}:x='mod(n*{step},{w})':y=0",
}

CONFIGS = [
    ("libx264 crf 18 medium", ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]),
    ("libx264 crf 23 medium", ["-c:v", "libx264", "-crf", "23", "-preset", "medium"]),
    ("libx264 crf 28 medium", ["-c:v", "libx264", "-crf", "28", "-preset", "medium"]),
    ("libx264 crf 23 veryfast", ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]),
    ("libx264 crf 35 medium", ["-c:v", "libx264", "-crf", "35", "-preset", "medium"]),
    ("libx265 crf 28 fast", ["-c:v", "libx265", "-crf", "28", "-preset", "fast", "-x265-params", "log-level=error"]),
    ("libx265 crf 34 fast", ["-c:v", "libx265", "-crf", "34", "-preset", "fast", "-x265-params", "log-level=error"]),
    ("libsvtav1 crf 35 preset 10", ["-c:v", "libsvtav1", "-crf", "35", "-preset", "10", "-svtav1-params", "svt-log-level=0"]),
    ("libsvtav1 crf 50 preset 10", ["-c:v", "libsvtav1", "-crf", "50", "-preset", "10", "-svtav1-params", "svt-log-level=0"]),
    ("libaom-av1 crf 35 cpu-used 8 realtime", ["-c:v", "libaom-av1", "-crf", "35", "-usage", "realtime", "-cpu-used", "8", "-row-mt", "1"]),
    ("libvpx-vp9 crf 33 cpu-used 8 realtime", ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1"]),
    ("prores proxy", ["-c:v", "prores", "-profile:v", "0"]),
    ("prores standard", ["-c:v", "prores", "-profile:v", "2"]),
]
HARDEST = {"veo_rain", "real_fireworks", "veo_basketball", "testsrc2", "noise", "fast_pan", "dark"}
COMMON = {"libx264 crf 23 medium", "libx264 crf 28 medium", "libx265 crf 28 fast", "libsvtav1 crf 50 preset 10"}
QUICK = {"libx264 crf 23 medium", "libx264 crf 28 medium", "libx265 crf 28 fast", "libsvtav1 crf 50 preset 10",
         "libaom-av1 crf 35 cpu-used 8 realtime", "libvpx-vp9 crf 33 cpu-used 8 realtime", "prores proxy"}


def edits(w, h):
    """[(name, first frame, last frame, rect or None, filter)] in this frame size."""
    u = h / 1080

    def px(v):
        return int(round(v))

    cap = (px(0.3 * w), px(0.80 * h), px(0.4 * w), px(0.09 * h))
    l60 = (px(0.8 * w + 7 * u), px(0.1 * h + 11 * u), px(60 * u), px(60 * u))
    l24 = (px(0.15 * w + 5 * u), px(0.15 * h + 3 * u), max(2, px(24 * u)), max(2, px(24 * u)))

    def logo(r, a, b):
        x, y, s, _ = r
        q = max(1, s // 4)
        return (f"drawbox=x={x}:y={y}:w={s}:h={s}:color=white:t=fill:enable='between(n,{a},{b})',"
                f"drawbox=x={x + q}:y={y + q}:w={s - 2 * q}:h={s - 2 * q}:color=0x2050c0:t=fill:enable='between(n,{a},{b})'")

    return [
        ("caption", 4, 9, cap, f"drawtext=fontfile={FONT}:text='A caption cue':fontsize={px(48 * u)}:fontcolor=white:"
                               f"borderw={max(1, px(3 * u))}:bordercolor=black:x=(w-text_w)/2:y={px(0.82 * h)}:enable='between(n,4,9)'"),
        ("logo 60x60", 12, 17, l60, logo(l60, 12, 17)),
        ("logo 24x24", 20, 25, l24, logo(l24, 20, 25)),
        ("colour tweak", 29, 33, None, "eq=brightness=0.03:saturation=1.15:enable='between(n,29,33)'"),
    ]


def run(cmd):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(" ".join(map(str, cmd)) + "\n" + proc.stderr.decode(errors="replace")[-800:])
    return proc


LOCK = threading.Lock()


def mezzanine(work, name, size):
    w, h = size
    out = work / f"m_{name}_{w}x{h}.mkv"
    with LOCK:  # one writer per file: a second job read a half-written one
        if not out.exists():
            part = out.with_suffix(".part.mkv")
            _mezzanine(name, size, part)
            part.replace(out)
    return out


def _mezzanine(name, size, out):
    w, h = size
    tail = ["-frames:v", str(FRAMES), "-an", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-y", out]
    if name in SYNTHETIC:
        spec = SYNTHETIC[name].format(w=w, h=h, w2=2 * w, step=max(2, w // 40))
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", spec, *tail])
    else:
        run(["ffmpeg", "-v", "error", "-i", FOOTAGE / f"{name}.mp4", "-vf",
             f"fps={RATE},scale={w}:{h}:flags=bicubic,setsar=1", *tail])


def tile_diffs(a, b, work, tag):
    """{grid: [frame -> [tile values]]}, check.py's graph (change_tiles()) on every grid at once."""
    outs = [work / f"d_{tag}_{gw}.raw" for gw, _ in GRIDS]
    graph = ("[0:V:0]settb=1/1000,setpts=N,format=gbrp[a];[1:V:0]settb=1/1000,setpts=N,format=gbrp[b];"
             f"[a][b]blend=all_mode=difference:shortest=1,split={len(GRIDS)}" + "".join(f"[s{i}]" for i in range(len(GRIDS))) + ";"
             + ";".join(f"[s{i}]scale={gw}:{gh}:flags=area[o{i}]" for i, (gw, gh) in enumerate(GRIDS)))
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", a, "-i", b, "-filter_complex", graph]
    for i, o in enumerate(outs):
        cmd += ["-map", f"[o{i}]", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-y", o]
    run(cmd)
    res = {}
    for (gw, gh), o in zip(GRIDS, outs):
        data = o.read_bytes()
        o.unlink()
        size = gw * gh * 3
        res[gw] = [list(map(max, data[i:i + size:3], data[i + 1:i + size:3], data[i + 2:i + size:3]))
                   for i in range(0, len(data) - size + 1, size)]
    return res


def rect_tiles(rect, size, grid):
    if rect is None:
        return None
    (w, h), (gw, gh) = size, grid
    tw, th = w / gw, h / gh
    x, y, rw, rh = rect
    return {c + r * gw for c in range(gw) for r in range(gh)
            if c * tw < x + rw and (c + 1) * tw > x and r * th < y + rh and (r + 1) * th > y}


def measure(work, name, size, label, args):
    w, h = size
    tag = f"{name}_{w}x{h}_{label.replace(' ', '_')}"
    m = mezzanine(work, name, size)
    ext = ".mov" if "prores" in label else ".mkv"
    ref, edit = work / f"r_{tag}{ext}", work / f"e_{tag}{ext}"
    started = time.time()
    run(["ffmpeg", "-v", "error", "-y", "-i", m, "-threads", "2", *args, ref])
    run(["ffmpeg", "-v", "error", "-y", "-i", m, "-vf", ",".join(e[4] for e in edits(w, h)), "-threads", "2", *args, edit])
    untouched = tile_diffs(ref, m, work, tag + "_u")
    edited = tile_diffs(edit, ref, work, tag + "_e")
    for p in (ref, edit):
        p.unlink()
    doc = {"source": name, "size": f"{w}x{h}", "config": label, "seconds": round(time.time() - started, 1), "grids": {}}
    for grid in GRIDS:
        gw = grid[0]
        frames = edited[gw]
        covered = [set() for _ in frames]
        scores = {}
        for ename, a, b, rect, _ in edits(w, h):
            tiles = rect_tiles(rect, size, grid)
            for n in range(a, min(b, len(frames) - 1) + 1):
                covered[n] |= tiles if tiles is not None else set(range(len(frames[n])))
            per_frame = [max(frames[n][t] for t in (tiles if tiles is not None else range(len(frames[n]))))
                         for n in range(a, min(b, len(frames) - 1) + 1)]
            scores[ename] = min(per_frame) if per_frame else None
        spill = max((v for n, f in enumerate(frames) for t, v in enumerate(f) if t not in covered[n]), default=0)
        doc["grids"][f"{gw}x{grid[1]}"] = {"untouched": max(max(f) for f in untouched[gw]), "spill": spill, "edits": scores}
    return doc


def plan(quick):
    """Every encoder setting on the sources most likely to give a large tile (noise, fast motion,
    fine detail); four common ones on the rest of the footage; the --quick seven on smaller sizes."""
    full = [c for c in CONFIGS if not quick or c[0] in QUICK]
    small = [c for c in CONFIGS if c[0] in QUICK]
    common = [c for c in CONFIGS if c[0] in COMMON]
    jobs = []
    for name in FOOTAGE_1080 + list(SYNTHETIC):
        jobs += [(name, SIZES["1080p"], c) for c in (full if name in HARDEST else common)]
    for name in ("real_city", "veo_rain", "noise", "testsrc2"):
        for size in ("720p", "480p"):
            jobs += [(name, SIZES[size], c) for c in small]
    for name, size in FOOTAGE_NATIVE.items():
        jobs += [(name, size, c) for c in small]
    return jobs


def table(results):
    """The summary: per encoder setting and grid, the largest untouched and spill tile and the
    smallest score of each edit, over every source and size."""
    lines = []
    for grid in [f"{gw}x{gh}" for gw, gh in GRIDS]:
        lines.append(f"\ngrid {grid}")
        lines.append("| encode | untouched (max) | spill (max) | caption (min) | logo 60x60 (min) | logo 24x24 (min) | colour tweak (min) |")
        lines.append("|---|---|---|---|---|---|---|")
        for label, _ in CONFIGS:
            rows = [r for r in results if r["config"] == label]
            if not rows:
                continue
            g = [r["grids"][grid] for r in rows]

            def worst(key, fn):
                vals = [(x[key], r) for x, r in zip(g, rows)]
                v, r = fn(vals, key=lambda p: p[0])
                return f"{v} ({r['source']} {r['size']})"

            def edit_min(e):
                vals = [(x["edits"][e], r) for x, r in zip(g, rows) if x["edits"][e] is not None]
                v, r = min(vals, key=lambda p: p[0])
                return f"{v} ({r['source']} {r['size']})"
            lines.append(f"| {label} | {worst('untouched', max)} | {worst('spill', max)} | "
                         + " | ".join(edit_min(e) for e in ("caption", "logo 60x60", "logo 24x24", "colour tweak")) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true", help="seven encoder settings instead of thirteen")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--work", help="scratch directory (default: a new temporary one)")
    ap.add_argument("--json", help="also write every measurement here")
    ap.add_argument("--only", help="comma-separated source names")
    args = ap.parse_args()
    encoders = run(["ffmpeg", "-hide_banner", "-encoders"]).stdout.decode()
    work = Path(args.work or tempfile.mkdtemp(prefix="floor_survey_"))
    work.mkdir(parents=True, exist_ok=True)
    jobs = [j for j in plan(args.quick) if f" {j[2][1][1]} " in encoders]
    if args.only:
        keep = set(args.only.split(","))
        jobs = [j for j in jobs if j[0] in keep]
    started = time.time()
    # every measurement is appended as it lands, and a re-run with the same --work skips what is there
    log = work / "results.jsonl"
    results = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    done = {(r["source"], r["size"], r["config"]) for r in results}
    jobs = [j for j in jobs if (j[0], f"{j[1][0]}x{j[1][1]}", j[2][0]) not in done]
    with ThreadPoolExecutor(args.jobs) as pool:
        for doc in pool.map(lambda j: measure(work, j[0], j[1], *j[2]), jobs):
            results.append(doc)
            with log.open("a") as f:
                f.write(json.dumps(doc) + "\n")
            g = doc["grids"]["32x18"]
            print(f"{doc['source']:16} {doc['size']:9} {doc['config']:40} untouched {g['untouched']:3} spill {g['spill']:3} "
                  f"edits {g['edits']}  [{doc['seconds']}s]", file=sys.stderr, flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1))
    print(f"{len(results)} encodes in {time.time() - started:.0f} s; FFmpeg: "
          + run(["ffmpeg", "-version"]).stdout.decode().splitlines()[0])
    print(table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
