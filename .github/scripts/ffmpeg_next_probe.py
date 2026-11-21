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
    print("\n== the calls that ran past their limit (sync --replace-audio, verify on a folder)")
    sea = ROOT / "demos" / "footage" / "veo_sea.mp4"
    ref, mic, folder = WORK / "ref.mp4", WORK / "mic.wav", WORK / "kit"
    sh("ffmpeg", "-y", "-v", "error", "-i", sea, "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", ref)
    sh("ffmpeg", "-y", "-v", "error", "-i", ref, "-vn", "-af", "adelay=300:all=1", "-ar", "48000", mic)
    folder.mkdir()
    sh("ffmpeg", "-y", "-v", "error", "-i", ref, "-t", "2", "-c", "copy", folder / "a.mp4")
    code, out, err, took = sh(sys.executable, ROOT / "scripts" / "sync.py", ref, mic, "--replace-audio", "-o", WORK / "synced.mp4", "--dry-run", "--json")
    print("sync --replace-audio --dry-run exit", code, f"{took:.1f}s")
    print(out.decode("utf-8", "replace")[-3000:], err[-500:])
    for label, cmd in (("sync --replace-audio", [sys.executable, ROOT / "scripts" / "sync.py", ref, mic, "--replace-audio", "-o", WORK / "synced.mp4", "--overwrite"]),
                       ("sync measure only", [sys.executable, ROOT / "scripts" / "sync.py", ref, mic, "--json"]),
                       ("verify --quick folder", [sys.executable, ROOT / "scripts" / "verify.py", folder, "--quick", "--report", WORK / "verify.md", "--json"]),
                       ("verify --quick file", [sys.executable, ROOT / "scripts" / "verify.py", ref, "--quick", "--json"])):
        code, out, err, took = sh(*cmd, timeout=150)
        print(label, "exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else "", out.decode("utf-8", "replace")[-700:], err[-1500:])
    print("\n== a delayed, padded sound under a copied picture: which spelling ends (sync --replace-audio writes the first)")
    n = 12 * 48000
    long_ref = WORK / "ref12.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=12:s=320x240:r=25", "-f", "lavfi", "-i", "sine=f=440:d=12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", long_ref)
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=660:d=8:r=48000", mic)
    for label, af, tail, video in (
            ("adelay,apad -t 12", "adelay=2500:all=1,apad", ["-t", "12.000"], ["-c:v", "copy"]),
            ("apad -t 12 (no delay)", "apad", ["-t", "12.000"], ["-c:v", "copy"]),
            ("adelay -t 12 (no pad)", "adelay=2500:all=1", ["-t", "12.000"], ["-c:v", "copy"]),
            ("adelay,apad=whole_dur=12 -t 12", "adelay=2500:all=1,apad=whole_dur=12", ["-t", "12.000"], ["-c:v", "copy"]),
            ("adelay,apad,atrim=end=12", "adelay=2500:all=1,apad,atrim=end=12", [], ["-c:v", "copy"]),
            ("adelay,apad=whole_len,atrim=end_sample", f"adelay=2500:all=1,apad=whole_len={n},atrim=end_sample={n}", [], ["-c:v", "copy"]),
            ("adelay,apad=whole_len,atrim=end_sample -t 12", f"adelay=2500:all=1,apad=whole_len={n},atrim=end_sample={n}", ["-t", "12.000"], ["-c:v", "copy"]),
            ("adelay,apad -t 12, picture encoded", "adelay=2500:all=1,apad", ["-t", "12.000"], ["-c:v", "libx264", "-preset", "ultrafast"]),
            ("adelay,apad -shortest", "adelay=2500:all=1,apad", ["-shortest"], ["-c:v", "copy"]),
            ("adelay,apad -t 12 -filter_complex", None, ["-t", "12.000"], ["-c:v", "copy"])):
        out = WORK / "delayed.mp4"
        graph = ["-map", "0:v:0", "-map", "1:a:0", "-af", af] if af else ["-filter_complex", "[1:a:0]adelay=2500:all=1,apad[a]", "-map", "0:v:0", "-map", "[a]"]
        code, _, err, took = sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", long_ref, "-f", "wav", "-i", mic, *graph, *video, "-c:a", "aac", *tail, out, timeout=40)
        if code is None and sys.platform == "win32":
            sh("taskkill", "/F", "/IM", "ffmpeg.exe")
            time.sleep(1)
        print(label, "| exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else json.dumps({k: counts(out, 48000)[k] for k in ("decoded_samples", "stream")}), err[-200:])

if __name__ == "__main__":
    main()
