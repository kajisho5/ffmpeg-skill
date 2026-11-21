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
    print("\n== apad with an output -t, the shape sync --replace-audio writes")
    for label, tail in (("-af apad -t 6", ["-af", "apad", "-c:a", "aac", "-t", "6.000"]),
                        ("-af apad=whole_dur=6", ["-af", "apad=whole_dur=6", "-c:a", "aac"]),
                        ("-af apad -shortest", ["-af", "apad", "-c:a", "aac", "-shortest"]),
                        ("-af apad,atrim=end=6", ["-af", "apad,atrim=end=6", "-c:a", "aac"]),
                        ("-af apad -t 6, video encoded", ["-af", "apad", "-c:a", "aac", "-c:v", "libx264", "-preset", "ultrafast", "-t", "6.000"])):
        video = [] if "-c:v" in tail else ["-c:v", "copy"]
        code, _, err, took = sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", ref, "-ss", "0.3", "-i", mic, "-map", "0:v:0", "-map", "1:a:0", *video, *tail, WORK / "apad.mp4", timeout=60)
        print(label, "exit", code, f"{took:.1f}s", "TIMED OUT" if code is None else "", err[-300:])
    print("\n== the tests that timed out, one at a time, with what is still running after 150 s")
    for test in ("test_sync_detects_offset_and_replaces_audio", "test_a_late_sound_is_measured_and_placed_on_its_files_clock", "test_verify_kit_runs_on_real_world_fixtures"):
        started = time.time()
        p = subprocess.Popen([sys.executable, "-m", "unittest", "tests.test_analysis", "-k", test], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            out, _ = p.communicate(timeout=150)
            print(test, "exit", p.returncode, f"{time.time() - started:.1f}s", out.decode("utf-8", "replace")[-1200:])
        except subprocess.TimeoutExpired:
            print(test, "STILL RUNNING after 150 s; processes:")
            if sys.platform == "win32":
                print(sh("powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'ff|python' } | ForEach-Object { $_.ProcessId.ToString() + ' <- ' + $_.ParentProcessId + ' ' + $_.CommandLine }")[1].decode("utf-8", "replace")[-6000:])
                sh("taskkill", "/F", "/T", "/PID", str(p.pid))
            else:
                print(sh("ps", "-eo", "pid,ppid,etime,args")[1].decode()[-3000:])
                p.kill()
            p.communicate()

if __name__ == "__main__":
    main()
