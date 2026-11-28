#!/usr/bin/env python3
"""Which part of the two tempo encodes that ran past 900 s on FFmpeg 9.1 does not end (#659):
the audio filter chain, the AAC encoder, or the two together. Prints, never fails."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
WORK = Path(tempfile.mkdtemp(prefix="fftempo_"))
LIMIT = 90


def sh(cmd, timeout=LIMIT):
    started = time.time()
    p = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _, err = p.communicate(timeout=timeout)
        return p.returncode, err.decode("utf-8", "replace"), time.time() - started
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        p.kill()
        try:
            _, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            err = b"(pipes still held)"
        return None, (err or b"").decode("utf-8", "replace"), time.time() - started


FIT_AF = "adelay=3072S:all=1,atempo=0.909091,atrim=start_sample=2253,asetpts=PTS-2253/SR/TB"
RAMP_FC = ("[0:a]atrim=start=0.000000:end=1.000000,asetpts=PTS-0.000000/TB,aresample=async=1:first_pts=0,"
           "adelay=5120S:all=1,atempo=2.000000,atrim=start_sample=2048,asetpts=PTS-2048/SR/TB,"
           "aformat=sample_rates=48000,apad=whole_len=24000,atrim=end_sample=24000[a0];"
           "[0:a]atrim=start=1.000000,asetpts=PTS-1.000000/TB,aresample=async=1:first_pts=0[a1];"
           "[a0][a1]concat=n=2:v=0:a=1[outa]")
BASE = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]


def main():
    from _fixtures import make_flash_beep
    print(subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0])
    src = WORK / "beeps.mp4"
    make_flash_beep(src)
    print("source:", subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels,duration",
                                     "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.split())
    aac = ["-c:a", "aac", "-b:a", "192k"]
    variants = (
        ("aac twoloop 192k", aac[:2] + ["-aac_coder", "twoloop"] + aac[2:], ".m4a"),
        ("aac fast 192k", aac[:2] + ["-aac_coder", "fast"] + aac[2:], ".m4a"),
        ("aac default 192k", aac, ".m4a"),
        ("aac twoloop 160k", ["-c:a", "aac", "-aac_coder", "twoloop", "-b:a", "160k"], ".m4a"),
        ("aac twoloop 192k stereo", ["-c:a", "aac", "-aac_coder", "twoloop", "-b:a", "192k", "-ac", "2"], ".m4a"),
        ("pcm", ["-c:a", "pcm_s16le"], ".wav"),
        ("null", ["-f", "null"], None),
    )
    for case, graph in (("fit 0.91x", ["-af", FIT_AF, "-map", "0:a:0", "-t", "4.400"]),
                        ("speedramp 2x", ["-filter_complex", RAMP_FC, "-map", "[outa]"])):
        print(f"\n== {case} (audio only)")
        for name, enc, ext in variants:
            out = "-" if ext is None else WORK / f"o{ext}"
            code, err, took = sh(BASE + ["-i", src] + graph + enc + [out])
            print(f"{name:26s} exit {code}  {took:6.1f}s  {err.strip()[-200:]}")
        print(f"-- {case}: filter to wav, then the wav to aac twoloop 192k")
        wav = WORK / "f.wav"
        code, err, took = sh(BASE + ["-i", src] + graph + ["-c:a", "pcm_s16le", wav])
        print(f"{'filter -> wav':26s} exit {code}  {took:6.1f}s  {err.strip()[-200:]}")
        if code == 0:
            for coder in ("twoloop", "fast", None):
                enc = ["-c:a", "aac"] + (["-aac_coder", coder] if coder else []) + ["-b:a", "192k"]
                code, err, took = sh(BASE + ["-i", wav] + enc + [WORK / "w.m4a"])
                print(f"{'wav -> aac ' + (coder or 'default'):26s} exit {code}  {took:6.1f}s  {err.strip()[-200:]}")
    print("\n== the full fit 0.91x command as the tool runs it (video and audio)")
    code, err, took = sh(BASE + ["-i", src, "-vf", "setpts=1.10000000*PTS,fps=30/1", "-af", FIT_AF, "-map", "0:v:0", "-map", "0:a:0",
                                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                                 "-c:a", "aac", "-aac_coder", "twoloop", "-b:a", "192k", "-t", "4.400", WORK / "full.mp4"])
    print(f"{'full, twoloop':26s} exit {code}  {took:6.1f}s  {err.strip()[-200:]}")


def loop_probe():
    """loop.py on a clip whose sound starts 0.3 s late: 9.1 put repeats 2 and 3 at -12 and +9 ms.
    The fixture's AAC is written by plain ffmpeg, so on 9.1 by its new default coder unless named."""
    import json
    import _fixtures as fx
    print("\n== loop: the fixture's AAC, by coder")
    for coder in (None, "twoloop"):
        src = WORK / f"alate_{coder or 'default'}.mp4"
        real = fx.sh
        if coder:
            def sh_named(*cmd, **kw):
                cmd = list(cmd)
                at = cmd.index("aac") + 1 if "aac" in cmd else None
                if at:
                    cmd[at:at] = ["-aac_coder", coder]
                return real(*cmd, **kw)
            fx.sh = sh_named
        try:
            fx.make_flash_beep(src, audio_late=0.3)
        finally:
            fx.sh = real
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                               "stream=start_time,duration,duration_ts,nb_frames,initial_padding:stream_side_data",
                               "-of", "json", str(src)], capture_output=True, text=True).stdout
        pk = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts,duration",
                             "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.split()
        print(f"-- source, coder {coder or 'default'}: {json.dumps(json.loads(info or '{}').get('streams'))}")
        print(f"   packets {len(pk)}, first {pk[:2]}, last {pk[-2:]}; flash-beep {fx.av_offsets_ms(src)} ms")
        out = WORK / f"loop_{coder or 'default'}.mp4"
        code, err, took = sh([sys.executable, ROOT / "scripts" / "loop.py", src, "--times", "3", "--preset", "veryfast",
                              "-o", out, "--overwrite"], timeout=300)
        print(f"   loop.py exit {code} {took:.1f}s; flash-beep {fx.av_offsets_ms(out) if code == 0 else err[-300:]} ms")
        lst = WORK / "list.txt"
        lst.write_text("".join(f"file '{src.as_posix()}'\n" for _ in range(3)), encoding="utf-8")
        cat = WORK / f"cat_{coder or 'default'}.mp4"
        code, err, _ = sh(BASE + ["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", cat])
        print(f"   concat -c copy exit {code}; flash-beep {fx.av_offsets_ms(cat) if code == 0 else err[-300:]} ms")


if __name__ == "__main__":
    main()
    loop_probe()
