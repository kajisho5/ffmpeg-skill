#!/usr/bin/env python3
"""End-to-end tests: build synthetic footage, run every script, verify with probe.

    python3 tests/test_all.py            # or: python3 -m unittest tests/test_all.py
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out"))
sys.path.insert(0, str(SCRIPTS))
from _common import probe  # noqa: E402

TONES = ("0.6*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.3)+0.4*sin(2*PI*880*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"
         "+0.3*sin(2*PI*220*t)*gt(sin(2*PI*0.21*t+2)\\,0.7)")


def sh(*cmd, expect_fail=False):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if expect_fail:
        assert proc.returncode != 0, f"expected failure but succeeded: {cmd}"
        return proc
    assert proc.returncode == 0, f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc


def script(name, *args, **kw):
    return sh(sys.executable, SCRIPTS / name, *args, **kw)


class FFmpegSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "source.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
           "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", cls.src)
        cls.mic = OUT / "lavmic.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "2.5", "-i", cls.src, "-vn", "-c:a", "pcm_s16le", cls.mic)
        cls.logo = OUT / "logo.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red@0.8:s=240x90,format=rgba", "-frames:v", "1", cls.logo)
        cls.cues = OUT / "cues.txt"
        cls.cues.write_text("0:00-0:03 Hello world\n0:03-0:06 Second | line\nAuto timed cue\n", encoding="utf-8")

    def assertClose(self, a, b, tol, msg=""):
        self.assertIsNotNone(a, msg)
        self.assertLessEqual(abs(a - b), tol, f"{msg}: {a} vs {b} (tol {tol})")

    # ---------------------------------------------------------------- probe
    def test_probe_json_and_fields(self):
        out = script("probe.py", self.src).stdout
        data = json.loads(out)
        self.assertClose(data["duration"], 12.0, 0.1)
        self.assertEqual((data["video"]["width"], data["video"]["height"]), (1280, 720))
        self.assertClose(data["video"]["fps"], 30.0, 0.01)
        self.assertEqual(data["video"]["codec"], "h264")
        self.assertEqual(data["audio"]["channels"], 1)
        self.assertEqual(data["audio"]["sample_rate"], 48000)
        field = script("probe.py", self.src, "--field", "video.width").stdout.strip()
        self.assertEqual(field, "1280")
        compact = script("probe.py", self.src, "--compact").stdout
        self.assertIn("1280x720", compact)

    def test_probe_missing_file_fails(self):
        proc = script("probe.py", OUT / "nope.mp4", expect_fail=True)
        self.assertIn("not found", proc.stderr)

    # ---------------------------------------------------------------- cut
    def test_cut_single_copy(self):
        out = OUT / "cut1.mp4"
        script("cut.py", self.src, "--start", "2", "--end", "6", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 4.0, 0.5, "lossless cut falls back to re-encode when the keyframe snap is too far")
        self.assertEqual(m["video"]["codec"], "h264")

    def test_cut_copy_never_reencodes_when_tolerance_disabled(self):
        out = OUT / "cut3.mp4"
        proc = script("cut.py", self.src, "--start", "2", "--end", "6", "--tolerance", "-1", "-o", out)
        self.assertIn("lossless stream copy", proc.stderr)

    def test_cut_segments_accurate(self):
        out = OUT / "cut2.mp4"
        script("cut.py", self.src, "--segments", "1-3,6-9", "--accurate", "-o", out)
        self.assertClose(probe(str(out))["duration"], 5.0, 0.15)

    def test_cut_bad_range_fails(self):
        script("cut.py", self.src, "--start", "5", "--end", "2", expect_fail=True)

    # ---------------------------------------------------------------- fit
    def test_fit_duration_speed_and_aspect_pad(self):
        out = OUT / "fit1.mp4"
        script("fit.py", self.src, "--duration", "6", "--aspect", "9:16", "--fit", "pad", "--width", "540", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 6.0, 0.15)
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (540, 960))

    def test_fit_trim_and_crop_square(self):
        out = OUT / "fit2.mp4"
        script("fit.py", self.src, "--duration", "4", "--method", "trim", "--from-center", "--aspect", "1:1", "--fit", "crop", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 4.0, 0.15)
        self.assertEqual(m["video"]["width"], m["video"]["height"])

    def test_fit_refuses_extreme_speed(self):
        script("fit.py", self.src, "--duration", "1", expect_fail=True)

    # ---------------------------------------------------------------- caption
    def test_caption_text_to_srt_and_burn(self):
        srt = OUT / "cues.srt"
        out = OUT / "cap.mp4"
        script("caption.py", self.src, "--text", self.cues, "--write-srt", srt, "--position", "top", "--bold", "-o", out)
        text = srt.read_text(encoding="utf-8")
        self.assertIn("00:00:03,000 --> 00:00:06,000", text)
        self.assertIn("Second\nline", text)
        self.assertIn("00:00:06,000 --> 00:00:09,000", text, "auto-timed cue follows previous")
        m = probe(str(out))
        self.assertClose(m["duration"], 12.0, 0.15)
        self.assertEqual(m["video"]["width"], 1280)

    def test_caption_srt_only(self):
        srt = OUT / "only.srt"
        proc = script("caption.py", "--text", self.cues, "--write-srt", srt)
        self.assertTrue(srt.exists())
        self.assertEqual(proc.stdout.strip(), str(srt))

    # ---------------------------------------------------------------- overlay
    def test_overlay_image_and_text(self):
        out1 = OUT / "ov_img.mp4"
        script("overlay.py", self.src, "--image", self.logo, "--position", "top-right", "--scale", "200",
               "--opacity", "0.8", "--start", "1", "--end", "5", "--fade", "0.5", "-o", out1)
        m = probe(str(out1))
        self.assertClose(m["duration"], 12.0, 0.2)
        self.assertIsNotNone(m["audio"], "audio must be kept")
        out2 = OUT / "ov_txt.mp4"
        script("overlay.py", self.src, "--text", "Episode 12", "--position", "bottom", "--box", "--start", "1", "--end", "5", "--fade", "0.3", "-o", out2)
        self.assertClose(probe(str(out2))["duration"], 12.0, 0.15)

    # ---------------------------------------------------------------- sync
    def test_sync_detects_offset_and_replaces_audio(self):
        proc = script("sync.py", self.src, self.mic, "--json")
        data = json.loads(proc.stdout)
        self.assertClose(data["offset_seconds"], 2.5, 0.05, "lav mic started 2.5 s later")
        self.assertGreater(data["confidence"], 0.5)
        out = OUT / "synced.mp4"
        script("sync.py", self.src, self.mic, "--replace-audio", "-o", out)
        again = json.loads(script("sync.py", self.src, out, "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.05, "aligned output has no residual offset")

    def test_sync_negative_offset_trim_second(self):
        early = OUT / "early.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "aevalsrc=0:s=48000:d=1.5",
           "-i", self.src, "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1", early)
        data = json.loads(script("sync.py", self.src, early, "--json").stdout)
        self.assertClose(data["offset_seconds"], -1.5, 0.05)
        out = OUT / "early_synced.wav"
        script("sync.py", self.src, early, "--trim-second", "-o", out)
        self.assertEqual(probe(str(out))["audio"]["codec"], "pcm_s16le")
        again = json.loads(script("sync.py", self.src, out, "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.05)

    # ---------------------------------------------------------------- loudness
    def test_loudness_two_pass(self):
        out = OUT / "loud.mp4"
        script("loudness.py", self.src, "-I", "-16", "--tp", "-1.5", "-o", out)
        stats = json.loads(script("loudness.py", out, "--measure-only", "-I", "-16", "--tp", "-1.5").stdout)
        self.assertClose(float(stats["input_i"]), -16.0, 1.0, "integrated loudness")
        self.assertLessEqual(float(stats["input_tp"]), -1.0, "true peak ceiling")
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")

    # ---------------------------------------------------------------- export
    def test_export_presets(self):
        cases = {
            "youtube": ("mp4", "h264", (1920, 1080)),
            "reels": ("mp4", "h264", (1080, 1920)),
            "x": ("mp4", "h264", (1280, 720)),
            "prores": ("mov", "prores", (1280, 720)),
            "h265": ("mp4", "hevc", (1280, 720)),
        }
        for preset, (ext, codec, size) in cases.items():
            with self.subTest(preset=preset):
                out = OUT / f"export_{preset}.{ext}"
                script("export.py", self.src, "--preset", preset, "-o", out)
                m = probe(str(out))
                self.assertEqual(m["video"]["codec"], codec)
                self.assertEqual((m["video"]["width"], m["video"]["height"]), size)
                self.assertClose(m["duration"], 12.0, 0.2)
                if preset in ("youtube", "reels", "x", "h265"):
                    self.assertEqual(m["video"]["color_space"], "bt709")

    def test_export_list(self):
        self.assertIn("youtube", script("export.py", "--list").stdout)

    # ---------------------------------------------------------------- help
    def test_every_script_has_help(self):
        for name in sorted(p.name for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")):
            with self.subTest(script=name):
                out = script(name, "--help").stdout
                self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
