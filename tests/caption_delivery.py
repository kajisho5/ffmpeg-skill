#!/usr/bin/env python3
"""Caption delivery on a real VFR phone capture and on a 30000/1001 CFR control (#729).

    python3 tests/caption_delivery.py PHONE.mov --report-dir DIR    # your capture, and the control
    FFMPEG_SKILL_PHONE_CAPTURE=PHONE.mov python3 tests/caption_delivery.py --report-dir DIR
    python3 tests/caption_delivery.py --report-dir DIR             # the control alone

No phone footage is in this repository or fetched by it: the capture is a file you supply, read
where it is, and only the report leaves the work folder. The control is generated here: testsrc2
at exactly 30000/1001 fps with a 48 kHz tone, so a step that assumes 30 fps shows as drift.

Each case runs what an agent delivering captions runs: `cut.py --accurate` from A to B (A is 2 s,
or a tenth of a short clip, from each end), `caption.py --mode mux` with three cues on the cut's
clock (near the start, at the middle and near the end, the last 0.4 s long so the default
`--min-duration` has something to change), then `export.py --preset copy`. It records

- provenance: the file's name, size and sha256, its container, its streams, and its device tags
  (make, model, software, creation time; location tags are never copied);
- the source's ffprobe packet times: count, first and last, the spread of the intervals, whether
  they vary (VFR), the first and last five; the audio's sample rate and first packet;
- the cut's range and the CFR grid it chose (the rate of its fps filter, or none when the source
  is CFR and kept its own), and the commands each tool ran;
- each cue's requested start and end, the end after caption.py's adjustment, and the delivered
  subtitle packet's start and end, with the first delivered frame on screen at the cue's start;
- every deliberate minimum-duration change (a cue whose end caption.py moved, and by how much);
- the sample rate at each step, and the delivery's container, picture and sound lengths.

It then judges: each cue starts within one delivered frame of the request, and is first on screen
less than one frame after it; each delivered end is within one frame of the adjusted end; the
sample rate is the source's at every step; the delivered picture is CFR on the grid it reports and
its length is within one frame of B - A; each tool's own `verified` is true. A JSON report and a
Markdown one go to --report-dir, named after the case; the exit status is 1 when any check fails.

A report of your capture names the file and its device tags: read it before you share it.
"""
import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ENV = "FFMPEG_SKILL_PHONE_CAPTURE"
TAGS = ("make", "model", "software", "encoder", "creation_time", "com.apple.quicktime.make", "com.apple.quicktime.model",
        "com.apple.quicktime.software", "com.apple.quicktime.creationdate", "com.android.manufacturer", "com.android.model",
        "com.android.version", "major_brand")


def sh(*cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", check=True, timeout=3600)


def tool(name, *argv):
    proc = subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py"), *map(str, argv), "--overwrite", "--json"],
                          capture_output=True, text=True, encoding="utf-8", timeout=3600)
    doc = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    if proc.returncode or doc.get("status") not in ("ok", "completed"):
        raise RuntimeError(f"{name}.py failed ({proc.returncode}): {(doc.get('error') or {}).get('message') or proc.stderr[-800:]}")
    return doc


def probe(path):
    return json.loads(sh("ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path).stdout)


def packets(path, stream):
    """(pts, duration, size) of every packet of one stream, in presentation order."""
    out = sh("ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "packet=pts_time,duration_time,size",
             "-of", "csv=p=0", path).stdout
    rows = []
    for line in out.splitlines():
        pts, dur, size = (line.split(",") + ["", "", ""])[:3]
        if pts not in ("", "N/A"):
            rows.append((float(pts), float(dur) if dur not in ("", "N/A") else None, int(size or 0)))
    return sorted(rows)


def stream(doc, kind):
    return next((s for s in doc["streams"] if s.get("codec_type") == kind and not (s.get("disposition") or {}).get("attached_pic")), None)


def rate(text):
    return Fraction(text) if text and text not in ("0/0", "N/A") else None


def summary(rows):
    """The spread of one stream's packet times. `vfr` is true when the intervals differ by more than
    a millisecond, which a constant rate stored in a 1/90000 or 1/30000 timebase never does."""
    times = [r[0] for r in rows]
    steps = [b - a for a, b in zip(times, times[1:])]
    spread = {"min": min(steps) * 1000, "median": statistics.median(steps) * 1000, "max": max(steps) * 1000} if steps else None
    return {"count": len(times), "first": times[0] if times else None, "last": times[-1] if times else None,
            "intervals_ms": spread and {k: round(v, 3) for k, v in spread.items()},
            "distinct_intervals_ms": len({round(s * 1000, 1) for s in steps}),
            "vfr": bool(spread) and spread["max"] - spread["min"] > 1.0,
            "head": [round(t, 6) for t in times[:5]], "tail": [round(t, 6) for t in times[-5:]]}


def provenance(path, generated):
    doc = probe(path)
    tags = {k: v for k, v in (doc["format"].get("tags") or {}).items()
            if k.lower() in TAGS and "location" not in k.lower() and "gps" not in k.lower()}
    v, a = stream(doc, "video"), stream(doc, "audio")
    side = {d.get("side_data_type"): d.get("rotation") for d in (v or {}).get("side_data_list", [])}
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return {"file": Path(path).name, "bytes": Path(path).stat().st_size, "sha256": digest.hexdigest(),
            "generated": generated, "container": doc["format"].get("format_name"), "device_tags": tags,
            "video": v and {"codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"),
                            "pix_fmt": v.get("pix_fmt"), "color_transfer": v.get("color_transfer"),
                            "rotation": side.get("Display Matrix"), "time_base": v.get("time_base")},
            "audio": a and {"codec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0), "channels": a.get("channels")}}


def make_control(path, seconds):
    """30000/1001 fps CFR with a 48 kHz tone: what a 29.97 camera writes, with nothing variable."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30000/1001:duration={seconds:g}",
           "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds:g}", "-fps_mode", "cfr",
           "-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(path)]
    sh(*cmd)
    return "ffmpeg " + " ".join(cmd[cmd.index("-f"):-1]) + " control.mp4"


def plan_cues(length):
    """Three cues on the cut's clock, off the frame grid by 3 ms: near the start, at the middle, and a
    0.4 s one near the end (scaled down for a clip under 14 s)."""
    k = min(1.0, length / 14)
    return [("start", round(1.0 * k + 0.003, 3), round(2.5 * k + 0.003, 3)),
            ("middle", round(length / 2 + 0.003, 3), round(length / 2 + 1.2 * k + 0.003, 3)),
            ("end", round(length - 1.6 * k + 0.003, 3), round(length - 1.2 * k + 0.003, 3))]


def stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def read_srt(path):
    times = re.findall(r"(\d+):(\d\d):(\d\d)[,.](\d{3}) --> (\d+):(\d\d):(\d\d)[,.](\d{3})", Path(path).read_text(encoding="utf-8"))
    sec = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    return [(round(sec(*t[:4]), 3), round(sec(*t[4:]), 3)) for t in times]


def run_case(name, source, work, generated=None):
    work.mkdir(parents=True, exist_ok=True)
    scrub = lambda text: text.replace(str(work), "<work>").replace(str(Path(source).parent), "<source dir>")
    src = probe(source)
    duration = float(src["format"]["duration"])
    sv, sa = stream(src, "video"), stream(src, "audio")
    a = round(min(2.0, duration / 10), 3)
    b = round(duration - a, 3)
    length = b - a
    cut_out, cap_out, final = work / f"{name}_cut.mp4", work / f"{name}_captioned.mp4", work / f"{name}_delivered.mp4"
    cut = tool("cut", source, "--start", f"{a:g}", "--end", f"{b:g}", "--accurate", "-o", cut_out)
    grid = next((m[1] for c in cut["commands"] for m in [re.search(r"\bfps=(\d+(?:\.\d+)?(?:/\d+)?)", c)] if m), None)
    cues = plan_cues(length)
    srt = work / f"{name}_cues.srt"
    srt.write_text("".join(f"{i}\n{stamp(s)} --> {stamp(e)}\n{label}\n\n" for i, (label, s, e) in enumerate(cues, 1)), encoding="utf-8")
    cap = tool("caption", cut_out, "--srt", srt, "--mode", "mux", "-o", cap_out)
    written = cap["tracks"][0]["file"]
    adjusted = read_srt(next(p for p in (cap_out.with_name(Path(written).name), Path(written), srt) if p.is_file()))
    export = tool("export", cap_out, "--preset", "copy", "-o", final)

    out = probe(final)
    fv, fa = stream(out, "video"), stream(out, "audio")
    fps = rate(fv.get("r_frame_rate"))
    frame = float(1 / fps)
    vpk = packets(final, "v:0")
    vtimes = [p[0] for p in vpk]
    subs = [p for p in packets(final, "s:0") if p[2] > 2]  # mov_text writes a 2-byte empty sample between cues
    picture = (vpk[-1][0] + (vpk[-1][1] or frame) - vpk[0][0]) if vpk else 0.0
    rows, changes = [], []
    for (label, start, end), (_, adj_end), sub in zip(cues, adjusted, subs + [None] * len(cues)):
        shown = next((t for t in vtimes if t >= (sub[0] if sub else start) - 1e-6), None)
        rows.append({"cue": label, "requested_start": start, "requested_end": end, "adjusted_end": adj_end,
                     "delivered_start": round(sub[0], 6) if sub else None,
                     "delivered_end": round(sub[0] + sub[1], 6) if sub and sub[1] is not None else None,
                     "start_delta_ms": round((sub[0] - start) * 1000, 3) if sub else None,
                     "first_frame_on_screen": round(shown, 6) if shown is not None else None,
                     "on_screen_after_ms": round((shown - start) * 1000, 3) if shown is not None else None})
        if abs(adj_end - end) > 0.0005:
            changes.append({"cue": label, "requested_seconds": round(end - start, 3), "delivered_seconds": round(adj_end - start, 3),
                            "moved_end_ms": round((adj_end - end) * 1000, 3),
                            "past_picture_end_ms": round((adj_end - picture) * 1000, 3) if adj_end > picture + 1e-6 else None,
                            "why": "caption.py --min-duration (default 1.0 s) extends a shorter cue's end, never past the next cue; --min-duration 0 keeps it"})
    rates = {"source": int(sa["sample_rate"]) if sa else None, "cut": int(stream(probe(cut_out), "audio")["sample_rate"]) if sa else None,
             "delivered": int(fa["sample_rate"]) if fa else None}
    steps = [y - x for x, y in zip(vtimes, vtimes[1:])]
    apk = packets(final, "a:0") if fa else []
    sound = (apk[-1][0] + (apk[-1][1] or 0) - apk[0][0]) if apk else None
    checks = [
        *({"check": f"{r['cue']} cue starts within one delivered frame", "ok": r["start_delta_ms"] is not None and abs(r["start_delta_ms"]) <= frame * 1000 + 0.001,
           "detail": f"{r['start_delta_ms']} ms, one frame is {frame * 1000:.3f} ms"} for r in rows),
        *({"check": f"{r['cue']} cue is on screen less than a frame after its start", "ok": r["on_screen_after_ms"] is not None and 0 <= r["on_screen_after_ms"] < frame * 1000 + 0.001,
           "detail": f"first frame at {r['first_frame_on_screen']} s, {r['on_screen_after_ms']} ms after"} for r in rows),
        *({"check": f"{r['cue']} cue ends within one frame of its adjusted end", "ok": r["delivered_end"] is not None and abs(r["delivered_end"] - r["adjusted_end"]) <= frame + 1e-6,
           "detail": f"delivered {r['delivered_end']} s, adjusted {r['adjusted_end']} s"} for r in rows),
        {"check": "every cue delivered", "ok": len(subs) == len(cues), "detail": f"{len(subs)} of {len(cues)} subtitle packets with text"},
        {"check": "sample rate kept at every step", "ok": len(set(rates.values())) == 1 and None not in rates.values(), "detail": rates},
        {"check": "delivered picture is CFR on its reported grid", "ok": bool(steps) and max(abs(s - frame) for s in steps) <= 0.0005,
         "detail": f"r_frame_rate {fv.get('r_frame_rate')}, intervals {min(steps) * 1000:.3f}..{max(steps) * 1000:.3f} ms" if steps else "no packets"},
        {"check": "delivered picture lasts B - A within one frame", "ok": abs(picture - length) <= frame + 1e-6,
         "detail": f"{picture:.6f} s against {length:.6f} s ({(picture - length) * 1000:+.3f} ms)"},
        {"check": "each tool verified its own output", "ok": all(d.get("verified") for d in (cut, cap, export)),
         "detail": {"cut": cut.get("verified"), "caption": cap.get("verified"), "export": export.get("verified")}},
    ]
    return {"case": name, "ffmpeg": sh("ffmpeg", "-version").stdout.splitlines()[0],
            "provenance": provenance(source, generated),
            "source": {"duration": duration, "video": {"r_frame_rate": sv.get("r_frame_rate"), "avg_frame_rate": sv.get("avg_frame_rate"),
                                                       "packets": summary(packets(source, "v:0"))},
                       "audio": sa and {"sample_rate": int(sa["sample_rate"]), "channels": sa.get("channels"),
                                        "first_packet": (packets(source, "a:0") or [(None,)])[0][0]}},
            "cut": {"start": a, "end": b, "accurate": True, "cfr_grid": grid,
                    "grid_note": "the rate of cut.py's fps filter" if grid else "no fps filter: the source is CFR and kept its own rate",
                    "commands": [scrub(c) for c in cut["commands"]]},
            "caption": {"mode": "mux", "codec": cap["tracks"][0]["codec"], "commands": [scrub(c) for c in cap["commands"]]},
            "export": {"preset": "copy", "commands": [scrub(c) for c in export["commands"]]},
            "cues": rows, "min_duration_changes": changes, "sample_rates": rates,
            "delivery": {"container_seconds": float(out["format"]["duration"]), "picture_seconds": round(picture, 6),
                         "sound_seconds": sound and round(sound, 6), "requested_seconds": round(length, 6),
                         "r_frame_rate": fv.get("r_frame_rate"), "avg_frame_rate": fv.get("avg_frame_rate"), "frame_ms": round(frame * 1000, 3)},
            "checks": checks, "ok": all(c["ok"] for c in checks)}


def markdown(report):
    p, s, d, c = report["provenance"], report["source"], report["delivery"], report["cut"]
    vp = s["video"]["packets"]
    lines = [f"# Caption delivery: {report['case']}", "",
             f"{'PASS' if report['ok'] else 'FAIL'} on {report['ffmpeg']}. Made by `tests/caption_delivery.py` (#729).", "",
             f"- Source: `{p['file']}`, {p['bytes']} bytes, sha256 `{p['sha256'][:16]}...`, {p['container']}; "
             + (f"generated: `{p['generated']}`" if p["generated"] else f"device tags: {json.dumps(p['device_tags'], ensure_ascii=False)}"),
             f"- Video: {p['video']['codec']} {p['video']['width']}x{p['video']['height']}, r_frame_rate {s['video']['r_frame_rate']}, "
             f"avg {s['video']['avg_frame_rate']}; {vp['count']} packets from {vp['first']} to {vp['last']} s, intervals {vp['intervals_ms']} ms, "
             f"{vp['distinct_intervals_ms']} distinct, {'VFR' if vp['vfr'] else 'CFR'}",
             f"- Audio: {s['audio'] and s['audio']['sample_rate']} Hz, first packet at {s['audio'] and s['audio']['first_packet']} s",
             f"- Cut: `--accurate` {c['start']} to {c['end']} s; CFR grid: {c['cfr_grid'] or '-'} ({c['grid_note']})",
             f"- Delivery: container {d['container_seconds']} s, picture {d['picture_seconds']} s, sound {d['sound_seconds']} s "
             f"(asked {d['requested_seconds']} s), {d['r_frame_rate']} ({d['frame_ms']} ms a frame); sample rates {report['sample_rates']}", "",
             "| cue | requested | adjusted end | delivered | start delta | first frame on screen |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['cue']} | {r['requested_start']}-{r['requested_end']} | {r['adjusted_end']} | {r['delivered_start']}-{r['delivered_end']} | "
              f"{r['start_delta_ms']} ms | {r['first_frame_on_screen']} (+{r['on_screen_after_ms']} ms) |" for r in report["cues"]]
    lines += ["", "Minimum-duration changes: " + ("; ".join(f"{m['cue']}: {m['requested_seconds']} s became {m['delivered_seconds']} s"
                                                     + (f", {m['past_picture_end_ms']} ms past the picture's end, which the container follows" if m["past_picture_end_ms"] else "")
                                                     + f" ({m['why']})"
                                                     for m in report["min_duration_changes"]) or "none"), "",
              "| check | result | detail |", "|---|---|---|"]
    lines += [f"| {k['check']} | {'PASS' if k['ok'] else 'FAIL'} | {k['detail']} |" for k in report["checks"]]
    return "\n".join(lines) + "\n"


def write(report, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{report['case']}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / f"{report['case']}.md").write_text(markdown(report), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", nargs="?", default=os.environ.get(ENV) or None, help=f"a phone capture of yours (or ${ENV}); it is only read")
    ap.add_argument("--report-dir", type=Path, help="where the reports go (default: the work folder, or tests/out/caption_delivery)")
    ap.add_argument("--work", type=Path, help="where the cut, captioned and delivered files go (default: a temporary folder, removed)")
    ap.add_argument("--control-seconds", type=float, default=600.0, help="length of the generated 30000/1001 control (default 600)")
    ap.add_argument("--no-control", action="store_true", help="run the capture only")
    args = ap.parse_args(argv)
    if args.no_control and not args.capture:
        ap.error(f"--no-control needs a capture (an argument or ${ENV})")
    with tempfile.TemporaryDirectory() as tmp:
        work = (args.work or Path(tmp)).resolve()
        reports = []
        if not args.no_control:
            control = work / "control_30000_1001.mp4"
            work.mkdir(parents=True, exist_ok=True)
            how = make_control(control, args.control_seconds)
            reports.append(run_case("cfr-30000-1001-control", control, work, generated=how))
        if args.capture:
            reports.append(run_case("phone-capture", Path(args.capture).resolve(), work))
        else:
            print(f"no phone capture given (an argument or ${ENV}): the control alone was run", file=sys.stderr)
        for report in reports:
            write(report, args.report_dir or args.work or ROOT / "tests" / "out" / "caption_delivery")
            failed = [c["check"] for c in report["checks"] if not c["ok"]]
            print(f"{report['case']}: {'PASS' if report['ok'] else 'FAIL: ' + '; '.join(failed)}")
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
