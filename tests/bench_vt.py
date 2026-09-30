#!/usr/bin/env python3
"""Quality benchmark for --hw: which VideoToolbox -q:v matches the CPU encode's SSIM at a CRF.

For each clip and codec, encodes the CPU line the skill writes (x264 / x265 medium, from
decision._cpu_encoder_args, so HDR gets x265 Main10 at CRF+2) at each --crf, then sweeps
VideoToolbox -q:v over a grid with the same line --hw writes (decision._vt_args). Each encode's
SSIM is measured against the source with frames paired by index (settb=1/1000,setpts=N): iPhone
timestamps jitter and a re-encode lands on a clean grid, so the ssim filter's timestamp pairing
compares neighbours. N/FRAME_RATE/TB is not enough: in a time base that does not divide the frame
duration (1/1000 at 30 fps, 1/600 at 29.97) it rounds, and two frames in three pair with a
neighbour (measured: 27 dB for an encode that is 47 dB). The q whose SSIM matches the CPU encode is interpolated from the sweep, and
the table reports it beside vt_quality()'s current answer, with bytes for both encoders.

VideoToolbox output is not bit-deterministic, so an SSIM can move in the fourth decimal between
runs; compare the fitted q, not a hash. SSIM is the
original fit's metric, kept for comparability; x264/x265 psy tuning lowers their SSIM at equal
visual quality, so a matched q leans low and the byte ratio reads kind to VideoToolbox. HDR rows
match x265 at CRF+2 (the CPU line HDR gets), so fit them apart from SDR hevc. Timings include
decode and process start: rough ratios, one run each. The VFR conform the scripts add is left out: both encoders
read the same frames, which keeps the index pairing exact.

Clips: three synthetic 1080p30 stand-ins (CG test pattern, a detailed fractal zoom, grainy
gradients) plus any --clip given; each is cut to --seconds.

Usage:
  python3 tests/bench_vt.py --clip ~/Footage/clip.mov --json vt.json
  python3 tests/bench_vt.py --no-synthetic --clip a.mov --crf 23 --hwdec
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from _common import decision, probe  # noqa: E402

SYNTHETIC = {
    "cg-testsrc2": "testsrc2=size=1920x1080:rate=30",
    "fractal-zoom": "mandelbrot=size=1920x1080:rate=30:maxiter=200",
    "grain-gradient": "gradients=size=1920x1080:rate=30:speed=0.02,noise=alls=10:allf=t+u",
}
DEFAULT_GRID = list(range(4, 101, 4))


def sh(cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def encode(src, seconds, vargs, out, vf=None, pre=()):
    cmd = ["ffmpeg", "-v", "error", "-y", *pre, "-t", f"{seconds}", "-i", src, "-map", "0:v:0", "-an"]
    cmd += (["-vf", vf] if vf else []) + list(vargs) + [out]
    t0 = time.monotonic()
    r = sh(cmd)
    took = time.monotonic() - t0
    if r.returncode != 0:
        raise RuntimeError(f"encode failed: {' '.join(map(str, cmd))}\n{r.stderr[-800:]}")
    return os.path.getsize(out), took


def frames(path, seconds=None):
    """Video frames ffmpeg decodes from `path` (its first `seconds`, when given)."""
    r = sh(["ffmpeg", "-v", "info", *(["-t", f"{seconds}"] if seconds else []), "-i", path, "-map", "0:v:0", "-f", "null", "-"])
    m = re.findall(r"frame=\s*(\d+)", r.stderr)
    if not m:
        raise RuntimeError(f"could not count frames of {path}:\n{r.stderr[-400:]}")
    return int(m[-1])


def ssim(ref, dist, seconds, fmt, ref_frames):
    """All-plane SSIM of `dist` against the first `seconds` of `ref`, frames paired by index. The
    ssim filter repeats the shorter input's last frame, so a dropped frame would lower the score
    with no error (measured: 0.893 for a 0.99 encode 30 frames short); a count mismatch fails."""
    got = frames(dist)
    if got != ref_frames:
        raise RuntimeError(f"{dist} has {got} frames, the reference {ref_frames}: SSIM would pair the wrong frames")
    graph = f"[0:v]settb=1/1000,setpts=N,format={fmt}[a];[1:v]settb=1/1000,setpts=N,format={fmt}[b];[a][b]ssim=shortest=1"
    r = sh(["ffmpeg", "-v", "info", "-t", f"{seconds}", "-i", ref, "-i", dist, "-lavfi", graph, "-f", "null", "-"])
    m = re.search(r"SSIM .*All:([0-9.]+)", r.stderr)
    if not m:
        raise RuntimeError(f"no SSIM for {dist}:\n{r.stderr[-800:]}")
    return float(m.group(1))


def db(s):
    return -10 * math.log10(max(1e-9, 1 - s))


def matched_q(curve, target):
    """-q:v where the sweep's SSIM first crosses `target`, interpolated linearly in SSIM dB (near
    1.0 raw SSIM barely moves between grid points), with the VideoToolbox bytes there; (None, None)
    off the grid. VideoToolbox is not deterministic, so a curve can dip: bench_clip flags it."""
    pts = sorted(curve, key=lambda p: p["q"])
    t = db(target)
    for lo, hi in zip(pts, pts[1:]):
        a, b = db(lo["ssim"]), db(hi["ssim"])
        if a <= t <= b and b > a:
            f = (t - a) / (b - a)
            return round(lo["q"] + f * (hi["q"] - lo["q"]), 1), round(lo["bytes"] + f * (hi["bytes"] - lo["bytes"]))
    return None, None


def bench_clip(name, src, meta, args, tmp):
    v = meta["video"]
    hdr = bool(v.get("bt2020_or_hdr"))
    fmt = "yuv420p10le" if hdr else "yuv420p"
    seconds = min(args.seconds, float(meta.get("duration") or args.seconds))
    source_bytes = (meta.get("bitrate") or 0) * seconds / 8
    codecs = ["hevc"] if hdr else args.codec
    ref_frames = frames(src, seconds)
    out = {"clip": name, "width": v.get("width"), "height": v.get("height"), "fps": v.get("fps"),
           "hdr": hdr, "transfer": v.get("color_transfer"), "seconds": seconds,
           "source_bytes": round(source_bytes), "codecs": {}}
    for codec in codecs:
        vt_line = decision._vt_args(codec, 18, meta, True)
        if vt_line is None:
            raise RuntimeError(f"no VideoToolbox {codec} here: {decision.STATE.hw_notes}")
        qi = vt_line.index("-q:v") + 1
        curve = []
        for q in sorted(set(args.grid) | {decision.vt_quality(codec, crf) for crf in args.crf}):
            line = list(vt_line)
            line[qi] = str(q)
            path = os.path.join(tmp, f"vt_{q}.mp4")
            size, took = encode(src, seconds, line, path)
            curve.append({"q": q, "bytes": size, "ssim": ssim(src, path, seconds, fmt, ref_frames), "time": round(took, 2)})
            os.remove(path)
            print(f"  {name} {codec} vt q{q}: {size / 1e6:.2f} MB ssim {curve[-1]['ssim']:.5f}", file=sys.stderr)
        rows = []
        for crf in args.crf:
            cpu_line = decision._cpu_encoder_args(codec, crf, "medium", meta, True)
            path = os.path.join(tmp, f"cpu_{crf}.mp4")
            size, took = encode(src, seconds, cpu_line, path)
            target = ssim(src, path, seconds, fmt, ref_frames)
            os.remove(path)
            q, vt_bytes = matched_q(curve, target)
            now = decision.vt_quality(codec, crf)
            now_pt = next((p for p in curve if p["q"] == now), None)
            rows.append({"crf": crf, "cpu_crf": int(cpu_line[cpu_line.index("-crf") + 1]), "cpu_bytes": size,
                         "cpu_ssim": target, "cpu_time": round(took, 2), "matched_q": q, "matched_vt_bytes": vt_bytes,
                         "vt_quality_now": now, "now_ssim": now_pt and now_pt["ssim"], "now_bytes": now_pt and now_pt["bytes"]})
            print(f"  {name} {codec} crf{crf}: cpu {size / 1e6:.2f} MB ssim {target:.5f} -> q {q} (now {now})", file=sys.stderr)
        entry = {"curve": curve, "rows": rows}
        if args.hwdec:
            entry["hwdec"] = hwdec_timing(src, seconds, vt_line, tmp)
        entry["monotonic"] = all(a["ssim"] <= b["ssim"] for a, b in zip(curve, curve[1:]))
        out["codecs"][codec] = entry
    return out


def hwdec_timing(src, seconds, vt_line, tmp):
    """VideoToolbox encode through a CPU scale, decoding on the CPU and then on the GPU."""
    path = os.path.join(tmp, "hwdec.mp4")
    res = {}
    for label, pre in (("cpu_decode", ()), ("vt_decode", ("-hwaccel", "videotoolbox"))):
        _, took = encode(src, seconds, vt_line, path, vf="scale=1280:-2", pre=pre)
        res[label] = round(took, 2)
    os.remove(path)
    return res


def table(results):
    lines = ["| Clip | Codec | CRF | CPU MB | CPU SSIM | matched q | VT MB at match | now q | VT MB now | SSIM now |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        for codec, e in r["codecs"].items():
            for row in e["rows"]:
                mb = lambda b: f"{b / 1e6:.2f}" if b else "-"  # noqa: E731
                q = row["matched_q"] if row["matched_q"] is not None else "off grid"
                now_ssim = f"{row['now_ssim']:.4f}" if row["now_ssim"] else "-"
                lines.append(f"| {r['clip']} | {codec} | {row['crf']} ({row['cpu_crf']}) | {mb(row['cpu_bytes'])} | "
                             f"{row['cpu_ssim']:.4f} | {q} | {mb(row['matched_vt_bytes'])} | {row['vt_quality_now']} | "
                             f"{mb(row['now_bytes'])} | {now_ssim} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", action="append", default=[], help="a real clip to add (repeatable)")
    ap.add_argument("--no-synthetic", action="store_true", help="leave out the three generated clips")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--crf", type=int, nargs="+", default=[18, 23, 28])
    ap.add_argument("--codec", nargs="+", default=["h264", "hevc"], choices=["h264", "hevc"], help="SDR codecs (HDR is hevc)")
    ap.add_argument("--grid", type=int, nargs="+", default=DEFAULT_GRID, help="VideoToolbox -q:v values to sweep")
    ap.add_argument("--hwdec", action="store_true", help="also time -hwaccel videotoolbox decode (a CPU scale between)")
    ap.add_argument("--json")
    args = ap.parse_args()
    decision.STATE.hw = True
    results = []
    with tempfile.TemporaryDirectory(prefix="ffskill_bvt_") as tmp:
        clips = []
        if not args.no_synthetic:
            for name, graph in SYNTHETIC.items():
                path = os.path.join(tmp, f"{name}.mkv")
                r = sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", graph, "-t", f"{args.seconds}",
                        "-c:v", "ffv1", "-pix_fmt", "yuv420p", path])
                if r.returncode != 0:
                    print(f"could not generate {name}: {r.stderr[-400:]}", file=sys.stderr)
                    return 1
                clips.append((name, path))
        clips += [(Path(c).stem, os.path.expanduser(c)) for c in args.clip]
        if not clips:
            print("no clips: pass --clip or drop --no-synthetic")
            return 1
        for name, path in clips:
            print(f"{name} ...", file=sys.stderr)
            results.append(bench_clip(name, path, probe(path), args, tmp))
            if args.json:  # write as we go: a long run keeps what it measured
                Path(args.json).write_text(json.dumps(results, indent=2))
    print(table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
