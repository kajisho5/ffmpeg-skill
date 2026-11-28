#!/usr/bin/env python3
"""FFmpeg 9.1 の AAC の方式ごとに、トラックの終わりがどう書かれるか (#659)。表示するだけで失敗しない。

59244 サンプル (48 kHz) と 54433 サンプル (44.1 kHz) のモノラルを AAC 192k で書き、
最後のパケットの discard_padding、パケットの合計、edit list どおりに復号したサンプル数を並べる。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix="ffend_"))


def run(cmd, timeout=60):
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], capture_output=True)
        return None, b"", "timeout"


def report(path):
    _, out, _ = run(["ffprobe", "-v", "error", "-ignore_editlist", "1", "-select_streams", "a:0", "-show_entries",
                     "packet=duration:packet_side_data", "-of", "json", path])
    packets = json.loads(out or b"{}").get("packets", [])
    last = packets[-1] if packets else {}
    _, pcm, _ = run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-f", "s16le", "-"])
    _, st, _ = run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                    "stream=duration,duration_ts,start_time", "-of", "json", path])
    return {"packets": len(packets), "packet_sum_less_priming": sum(int(p.get("duration", 0)) for p in packets) - 1024,
            "last_packet": last, "decoded_samples": len(pcm) // 2, "stream": json.loads(st or b"{}").get("streams", [{}])[0]}


def main():
    print(subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0])
    for rate, samples in ((48000, 59244), (44100, 54433)):
        src = WORK / f"src_{rate}.mov"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=2:s=160x120:r=25", "-f", "lavfi", "-i",
             f"sine=f=440:sample_rate={rate}:d=2", "-af", f"atrim=end_sample={samples}", "-c:v", "libx264",
             "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", src])
        print(f"\n== {samples} samples at {rate} Hz, mono, AAC 192k in MP4 (expected {samples})")
        for coder in ("twoloop", "fast", None):
            out = WORK / f"o_{rate}_{coder or 'default'}.mp4"
            named = ["-aac_coder", coder] if coder else []
            code, _, err = run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:v", "copy", "-c:a", "aac", *named, "-b:a", "192k", out])
            print(f"-- coder {coder or 'default'}: exit {code} {err[-200:]}")
            if code == 0:
                print("   " + json.dumps(report(out)))


if __name__ == "__main__":
    main()
