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
    nob = WORK / "source_nob.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-i", src12, "-c:v", "libx264", "-preset", "veryfast", "-bf", "0", "-c:a", "copy", nob)
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    out = WORK / "under.mp4"
    tail = ["-c:a", "aac", "-b:a", "192k", "-t", "12.000", out]
    pic, snd, lead = ["-i", src12], ["-f", "wav", "-i", lav], "adelay=2500:all=1,apad"
    print("-- a late sound under a copied picture, -t 12: what lets it end")
    for label, cmd in (
            ("as sync writes it", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead] + tail),
            ("no delay (control)", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "apad"] + tail),
            ("delay 100 ms", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "adelay=100:all=1,apad"] + tail),
            ("delay 1000 ms", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "adelay=1000:all=1,apad"] + tail),
            ("sound input first", base + snd + pic + ["-map", "1:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", lead] + tail),
            ("-filter_complex", base + pic + snd + ["-filter_complex", f"[1:a:0]{lead}[a]", "-map", "0:v:0", "-map", "[a]", "-c:v", "copy"] + tail),
            ("-max_muxing_queue_size 9999", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead, "-max_muxing_queue_size", "9999"] + tail),
            ("-thread_queue_size 4096", base + ["-thread_queue_size", "4096"] + pic + ["-thread_queue_size", "4096"] + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead] + tail),
            ("-itsoffset 2.5 and aresample", base + pic + ["-itsoffset", "2.5"] + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "aresample=async=1:first_pts=0,apad"] + tail),
            ("picture encoded", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-af", lead] + tail),
            ("picture without B-frames", base + ["-i", nob] + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead] + tail),
            ("-shortest in place of -t", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead, "-c:a", "aac", "-shortest", out]),
            ("-t 12 on the picture input too", base + ["-t", "12"] + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead] + tail),
            ("silence joined ahead (concat)", base + pic + ["-f", "lavfi", "-t", "2.5", "-i", "anullsrc=r=48000:cl=mono"] + snd + ["-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1,apad[a]", "-map", "0:v:0", "-map", "[a]", "-c:v", "copy"] + tail),
            ("-filter_threads 1 -threads 1", base + ["-filter_threads", "1"] + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead, "-threads", "1"] + tail),
            ("to mkv", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead, "-c:a", "aac", "-t", "12.000", WORK / "under.mkv"]),
            ("sound to pcm in mov", base + pic + snd + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", lead, "-c:a", "pcm_s16le", "-t", "12.000", WORK / "under.mov"])):
        code, _, err, took = sh(*cmd, timeout=20)
        print(label, "| exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else "ok", err[-160:])
    print("-- two steps: the sound alone, then both copied")
    c1, _, e1, t1 = sh(*base, *snd, "-af", "adelay=2500:all=1,apad=whole_dur=12", "-c:a", "aac", "-b:a", "192k", WORK / "lead.m4a", timeout=20)
    c2, _, e2, t2 = sh(*base, *pic, "-i", WORK / "lead.m4a", "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-t", "12.000", out, timeout=20)
    print("step 1 exit", c1, f"{t1:.1f}s", e1[-100:], "| step 2 exit", c2, f"{t2:.1f}s", e2[-100:], json.dumps({k: counts(out, 48000)[k] for k in ("decoded_samples", "stream")}) if c2 == 0 else "")

if __name__ == "__main__":
    main()
