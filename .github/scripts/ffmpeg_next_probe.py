#!/usr/bin/env python3
"""What the newest FFmpeg does where the suite broke on 9.1.0 (#659): prints, never fails.

Two questions. Does sound really end late, or does the file only state its last packet
differently (the tests add up packet durations)? And which call runs past its time limit?"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(tempfile.mkdtemp(prefix="ffnext_"))


def sh(*cmd, timeout=180):
    started = time.time()
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace"), time.time() - started
    except subprocess.TimeoutExpired as e:
        return None, e.stdout or b"", (e.stderr or b"").decode("utf-8", "replace"), time.time() - started


def counts(path, rate):
    """The same track three ways: packet durations (what the tests add up), decoded samples, stated length."""
    _, out, _, _ = sh("ffprobe", "-v", "error", "-ignore_editlist", "1", "-select_streams", "a:0", "-show_entries", "packet=duration", "-of", "csv=p=0", path)
    rows = [int(r.split(",")[0]) for r in out.decode().split() if r.strip(",")]
    _, pcm, _, _ = sh("ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-f", "s16le", "-")
    _, dur, _, _ = sh("ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration,nb_frames,start_time", "-of", "json", path)
    _, side, _, _ = sh("ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=duration:packet_side_data", "-of", "json", path)
    packets = json.loads(side or b"{}").get("packets", [])
    return {"packets": len(rows), "packet_sum_less_priming": sum(rows) - 1024, "last_packets": rows[-3:], "decoded_samples": len(pcm) // 2,
            "stream": json.loads(dur or b"{}").get("streams", [{}])[0], "last_packet_side_data": packets[-1] if packets else None, "rate": rate}


def main():
    print(sh("ffmpeg", "-version")[1].decode().splitlines()[0])
    burst = "0.4*sin(2*PI*440*t)*lt(mod(t\\,0.31)\\,0.1)"
    clips = {}
    for name, samples, picture in (("long", 59244, "testsrc"), ("short", 24000, "testsrc2")):
        clips[name] = WORK / f"{name}.mov"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{picture}=d=1:s=160x120:r=25", "-f", "lavfi", "-i", f"aevalsrc={burst}:s=48000",
           "-af", f"atrim=end_sample={samples}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", clips[name])
    print("\n== plain ffmpeg, 59244 samples in, AAC in MP4 out")
    for label, extra in (("atrim only", []), ("with -t", ["-t", f"{59244 / 48000:.6f}"]), ("-shortest off, mov", [])):
        out = WORK / ("plain." + ("mov" if "mov" in label else "mp4"))
        code, _, err, took = sh("ffmpeg", "-y", "-v", "error", "-i", clips["long"], "-af", "atrim=end_sample=59244", "-c:v", "copy", "-c:a", "aac", *extra, out)
        print(label, "exit", code, f"{took:.1f}s", json.dumps(counts(out, 48000)), err[-300:])
    print("\n== the skill's own tools (expected 59244)")
    for label, tool, args in (("broll", "broll.py", [clips["long"], "--insert", clips["short"], "--at", "0.2", "--duration", "0.4", "--audio", "mix"]),
                              ("multicam", "multicam.py", [clips["long"], clips["short"], "--switch", "0-0.5:0,0.5-1:1"]),
                              ("grid", "grid.py", [clips["short"], clips["long"], "--cols", "2", "--rows", "1", "--pad", "--audio-from", "1", "--label", "none"])):
        out = WORK / f"{label}.mp4"
        code, _, err, took = sh(sys.executable, ROOT / "scripts" / tool, *args, "-o", out, "--json")
        print(label, "exit", code, f"{took:.1f}s", json.dumps(counts(out, 48000)) if out.exists() else err[-600:])
    print("\n== the calls that ran past their limit")
    sea = ROOT / "demos" / "footage" / "veo_sea.mp4"
    late = WORK / "late.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-i", sea, "-t", "6", "-af", "adelay=300:all=1", "-c:v", "copy", "-c:a", "aac", late)
    for label, cmd in (("verify", [sys.executable, ROOT / "scripts" / "verify.py", sea, "--json"]),
                       ("sync", [sys.executable, ROOT / "scripts" / "sync.py", late, sea, "-o", WORK / "synced.mp4", "--json"]),
                       ("sync dry-run", [sys.executable, ROOT / "scripts" / "sync.py", late, sea, "-o", WORK / "synced2.mp4", "--dry-run", "--json"])):
        code, out, err, took = sh(*cmd, timeout=240)
        print(label, "exit", code, f"{took:.1f}s", (out.decode("utf-8", "replace")[-500:] if code else ""), err[-800:] if code != 0 else "")


if __name__ == "__main__":
    main()
