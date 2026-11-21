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
    """Run with a time limit. On Windows the feed's `ffmpeg` is a shim that starts the real one: killing
    the shim leaves its child holding the pipes, so the whole tree is ended before the pipes are read."""
    started = time.time()
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err.decode("utf-8", "replace"), time.time() - started
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        p.kill()
        try:
            out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            out, err = b"", b"(pipes still held)"
        return None, out or b"", (err or b"").decode("utf-8", "replace"), time.time() - started


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
    print("\n== the test's own fixtures (picture with B-frames), the command that was left running, and variants")
    sys.path.insert(0, str(ROOT / "tests"))
    from _fixtures import make_tones_take
    ref8, take = make_tones_take(WORK / "clock_ref.mp4", dur=8), make_tones_take(WORK / "clock_take.mp4", start=1.0, audio_late=0.3, dur=7)
    from _fixtures import TONES
    src12, lav = WORK / "source.mp4", WORK / "lavmic.wav"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
       "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", src12)
    sh("ffmpeg", "-y", "-v", "error", "-ss", "2.5", "-i", src12, "-vn", "-c:a", "pcm_s16le", lav)
    sine = WORK / "sine95.wav"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=660:d=9.5:r=48000", sine)
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    print("-- sound alone, delayed 2.5 s, to AAC: which encoder settings end (mono source, 48 kHz)")
    m4a = WORK / "enc.m4a"
    for label, af, enc in (
            [(f"-b:a {r}", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", r]) for r in ("64k", "96k", "128k", "160k", "192k", "256k")]
            + [("no -b:a", "adelay=2500:all=1", ["-c:a", "aac"]),
               ("192k, no delay", "anull", ["-c:a", "aac", "-b:a", "192k"]),
               ("192k, delay 1000", "adelay=1000:all=1", ["-c:a", "aac", "-b:a", "192k"]),
               ("192k, delay 100", "adelay=100:all=1", ["-c:a", "aac", "-b:a", "192k"]),
               ("192k, as stereo", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]),
               ("192k, -aac_coder fast", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-aac_coder", "fast"]),
               ("192k, -aac_coder twoloop", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-aac_coder", "twoloop"]),
               ("192k, -aac_pns 0", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-aac_pns", "0"]),
               ("192k, -aac_tns 0", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-aac_tns", "0"]),
               ("192k, -cutoff 18000", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-cutoff", "18000"]),
               ("192k, to adts", "adelay=2500:all=1", ["-c:a", "aac", "-b:a", "192k", "-f", "adts"]),
               ("192k, sine source", None, ["-c:a", "aac", "-b:a", "192k"]),
               ("192k, tones without the cut at 2.5 s", "TONES", ["-c:a", "aac", "-b:a", "192k"])]):
        if af is None:
            src = ["-f", "lavfi", "-i", "sine=f=660:d=9.5:r=48000", "-af", "adelay=2500:all=1"]
        elif af == "TONES":
            src = ["-f", "lavfi", "-t", "9.5", "-i", f"aevalsrc='{TONES}':s=48000", "-af", "adelay=2500:all=1"]
        else:
            src = ["-f", "wav", "-i", lav, "-af", af]
        code, _, err, took = sh(*base, *src, *enc, m4a, timeout=15)
        print(label, "| exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else "ok", err[-120:])
    print("-- the skill's own calls that never returned, with the coder named by the runner")
    src12 = WORK / "source.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
       "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", src12)
    for label, a, b in (("sync --replace-audio, wav 2.5 s late", src12, lav), ("sync --replace-audio, take on its own clock", ref8, take)):
        out = WORK / "synced_fixed.mp4"
        code, doc, err, took = sh(sys.executable, ROOT / "scripts" / "sync.py", a, b, "--replace-audio", "-o", out, "--overwrite", "--json", timeout=120)
        try:
            command = json.loads(doc)["commands"][-1]
        except Exception as e:
            command = f"(no command: {e})"
        print(label, "| exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else json.dumps({k: counts(out, 48000)[k] for k in ("decoded_samples", "stream")}), err[-200:])
        print("  ", command[-260:])

if __name__ == "__main__":
    main()
