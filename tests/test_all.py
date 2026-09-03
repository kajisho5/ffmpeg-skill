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


def png_size(path) -> tuple:
    with open(path, "rb") as fh:
        head = fh.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


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

        # --- "real world" material: VFR, rotated phone clip, 5.1 audio, 10-bit HDR10 HEVC, long drifting pair
        cls.vfr = OUT / "vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "12", "-vf", "select='gt(random(1)\\,0.3)'", "-fps_mode", "vfr",
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", cls.vfr)
        cls.rot = OUT / "rot.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", cls.src, "-t", "6", "-c", "copy", cls.rot)
        cls.surround = OUT / "surround.mov"
        six = "|".join([TONES, TONES, "0.5*" + TONES, "0.2*sin(2*PI*60*t)", "0.3*" + TONES, "0.3*" + TONES])
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{six}':s=48000:c=5.1",
           "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ac", "6", cls.surround)
        cls.hdr = OUT / "hdr10.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "4", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error",
           "-tag:v", "hvc1", "-c:a", "aac", cls.hdr)
        cls.long_ref = OUT / "long_ref.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "200", "-c:a", "pcm_s16le", cls.long_ref)
        cls.long_drift = OUT / "long_drift.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.2", "-i", cls.long_ref,
           "-af", "asetrate=48000*0.9995,aresample=48000", "-c:a", "pcm_s16le", cls.long_drift)

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

    # ---------------------------------------------------------------- real-world material
    def test_probe_detects_vfr_rotation_surround_hdr(self):
        self.assertTrue(probe(str(self.vfr))["video"]["variable_frame_rate_suspected"])
        self.assertEqual(probe(str(self.rot))["video"]["rotation"], 90)
        self.assertEqual(probe(str(self.surround))["audio"]["channels"], 6)
        h = probe(str(self.hdr))["video"]
        self.assertTrue(h["hdr"])
        self.assertEqual(h["hdr_format"], "HDR10/PQ")
        self.assertEqual(h["bit_depth"], 10)
        self.assertEqual(h["codec"], "hevc")

    def test_vfr_is_conformed_to_cfr_on_cut_and_fit(self):
        out = OUT / "vfr_cut.mp4"
        proc = script("cut.py", self.vfr, "--start", "2", "--end", "6", "-o", out)
        self.assertIn("variable-frame-rate", proc.stderr)
        m = probe(str(out))
        self.assertFalse(m["video"]["variable_frame_rate_suspected"])
        self.assertClose(m["duration"], 4.0, 0.2)
        out2 = OUT / "vfr_fit.mp4"
        script("fit.py", self.vfr, "--fps", "30", "--aspect", "1:1", "-o", out2)
        m2 = probe(str(out2))
        self.assertClose(m2["video"]["fps"], 30.0, 0.05)
        self.assertFalse(m2["video"]["variable_frame_rate_suspected"])

    def test_rotated_source_uses_display_orientation(self):
        out = OUT / "rot_fit.mp4"
        script("fit.py", self.rot, "--aspect", "9:16", "--fit", "pad", "--width", "540", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (540, 960))
        self.assertEqual(m["video"]["rotation"], 0)

    def test_hdr_to_sdr_tonemap(self):
        out = OUT / "sdr.mp4"
        script("color.py", self.hdr, "--to-sdr", "--preset", "veryfast", "-o", out)
        v = probe(str(out))["video"]
        self.assertFalse(v["hdr"])
        self.assertEqual((v["color_transfer"], v["color_primaries"], v["pix_fmt"]), ("bt709", "bt709", "yuv420p"))
        self.assertEqual((v["width"], v["height"]), (1920, 1080))
        # refuses on SDR input unless forced
        script("color.py", self.src, "--to-sdr", expect_fail=True)

    def test_color_retag_is_stream_copy(self):
        out = OUT / "retag.mp4"
        proc = script("color.py", self.src, "--retag", "bt601", "-o", out)
        self.assertIn("-c copy", proc.stderr)
        self.assertEqual(probe(str(out))["video"]["color_transfer"], "smpte170m")

    def test_color_lut(self):
        lut = OUT / "invert.cube"
        lines = ["LUT_3D_SIZE 2"]
        for b in (0, 1):
            for g in (0, 1):
                for r in (0, 1):
                    lines.append(f"{1 - r} {1 - g} {1 - b}")
        lut.write_text("\n".join(lines) + "\n")
        out = OUT / "lut.mp4"
        script("color.py", self.src, "--lut", lut, "--lut-strength", "0.5", "--preset", "veryfast", "-o", out)
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)

    def test_export_warns_on_hdr(self):
        out = OUT / "hdr_youtube.mp4"
        proc = script("export.py", self.hdr, "--preset", "x", "-o", out)
        self.assertIn("HDR", proc.stderr)

    def test_audio_downmix_voice_and_ducking(self):
        out = OUT / "downmix.mp4"
        script("audio.py", self.surround, "--downmix", "--voice", "-o", out)
        a = probe(str(out))["audio"]
        self.assertEqual(a["channels"], 2)
        out2 = OUT / "ducked.mp4"
        proc = script("audio.py", self.src, "--music", self.long_ref, "--duck", "--fade-out", "2", "-o", out2)
        self.assertIn("sidechaincompress", proc.stderr)
        self.assertClose(probe(str(out2))["duration"], 12.0, 0.2)
        out3 = OUT / "replaced.mp4"
        script("audio.py", self.src, "--replace", self.mic, "--stereo", "-o", out3)
        m3 = probe(str(out3))
        self.assertEqual(m3["audio"]["channels"], 2)
        self.assertClose(m3["duration"], 12.0, 0.2)

    def test_sync_fine_resolution_and_drift(self):
        data = json.loads(script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--json").stdout)
        self.assertClose(data["offset_seconds"], 1.2, 0.01, "offset extrapolated to t=0 at 1 ms resolution")
        self.assertClose(data["drift"]["drift_ppm"], 500.0, 40.0)
        out = OUT / "drift_fixed.wav"
        script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--trim-second", "-o", out)
        again = json.loads(script("sync.py", self.long_ref, out, "--fix-drift", "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.01)
        self.assertClose(again["drift"]["drift_ppm"], 0.0, 40.0)

    def test_fit_smooth_slow_motion_blend(self):
        out = OUT / "slow.mp4"
        script("fit.py", self.src, "--duration", "18", "--smooth", "blend", "--preset", "veryfast", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 18.0, 0.2)
        self.assertClose(m["video"]["fps"], 30.0, 0.05, "frame rate preserved while slowing down")

    def test_caption_animated_karaoke_ass(self):
        out = OUT / "karaoke.mp4"
        ass = OUT / "karaoke.ass"
        script("caption.py", self.src, "--text", self.cues, "--animate", "pop", "--karaoke", "--write-ass", ass, "--preset", "veryfast", "-o", out)
        text = ass.read_text(encoding="utf-8-sig")
        self.assertIn("PlayResX: 1280", text)
        self.assertIn("\\kf", text)
        self.assertIn("\\fscx", text)
        self.assertEqual(text.count("Dialogue:"), 3)
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)
        # from an existing SRT too
        srt = OUT / "cues.srt"
        if not srt.exists():
            script("caption.py", "--text", self.cues, "--write-srt", srt)
        out2 = OUT / "fade.mp4"
        script("caption.py", self.src, "--srt", srt, "--animate", "fade", "--preset", "veryfast", "-o", out2)
        self.assertTrue((OUT / "fade.ass").exists())

    # ---------------------------------------------------------------- v0.3: look / silence / join / agent flags
    def test_look_contact_sheet_and_frames(self):
        sheet = OUT / "sheet.png"
        proc = script("look.py", self.src, "--tiles", "4x3", "--width", "1280", "-o", sheet)
        self.assertTrue(sheet.exists())
        self.assertIn("12 frames", proc.stderr)
        w, h = png_size(sheet)
        self.assertGreaterEqual(w, 1280)
        self.assertGreater(h, 500, "three rows of 16:9 tiles")
        proc = script("look.py", self.src, "--at", "2.5", "--at", "0:07", "-o", OUT / "frame")
        frames = [OUT / "frame_2.500s.png", OUT / "frame_7.000s.png"]
        for f in frames:
            self.assertTrue(f.exists(), f)
        self.assertEqual(png_size(frames[0]), (1280, 720))
        cmp_png = OUT / "cmp.png"
        script("look.py", self.src, "--compare", self.src, "--at", "1", "-o", cmp_png)
        self.assertEqual(png_size(cmp_png)[0], 1280)

    def test_silence_removal(self):
        gappy = OUT / "gappy.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", gappy)
        data = json.loads(script("silence.py", gappy, "--list", "--json").stdout)
        self.assertEqual(len(data["silences"]), 3)
        self.assertClose(data["removed_seconds"], 5.25, 0.3)
        out = OUT / "tight.mp4"
        edl = OUT / "keep.txt"
        script("silence.py", gappy, "--preset", "veryfast", "--edl", edl, "-o", out)
        self.assertClose(probe(str(out))["duration"], 6.75, 0.3)
        self.assertEqual(len(edl.read_text().strip().splitlines()), 3)
        # the EDL feeds cut.py --segments directly
        segs = ",".join(edl.read_text().split())
        out2 = OUT / "tight_via_cut.mp4"
        script("cut.py", gappy, "--segments", segs, "--accurate", "--preset", "veryfast", "-o", out2)
        self.assertClose(probe(str(out2))["duration"], 6.75, 0.4)

    def test_join_with_transition_normalises_mismatched_clips(self):
        out = OUT / "joined.mp4"
        # 720p 30fps stereo + rotated portrait + 640x360 mono clip without audio
        silent = OUT / "silent.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "4", "-c:v", "libx264", "-preset", "veryfast", silent)
        script("join.py", self.src, self.rot, silent, "--transition", "fadeblack", "--duration", "0.5", "--preset", "veryfast", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))
        self.assertClose(m["video"]["fps"], 30.0, 0.05)
        self.assertEqual(m["audio"]["channels"], 2)
        self.assertClose(m["duration"], 12 + 6 + 4 - 1.0, 0.3)
        out2 = OUT / "joined_cut.mp4"
        script("join.py", self.src, silent, "--transition", "none", "--preset", "veryfast", "-o", out2)
        self.assertClose(probe(str(out2))["duration"], 16.0, 0.3)
        script("join.py", self.src, expect_fail=True)

    def test_dry_run_and_json_on_every_script(self):
        cases = [
            ("cut.py", [self.src, "--start", "1", "--end", "3"]),
            ("fit.py", [self.src, "--duration", "6"]),
            ("caption.py", [self.src, "--srt", OUT / "cues.srt"]),
            ("overlay.py", [self.src, "--image", self.logo]),
            ("export.py", [self.src, "--preset", "x"]),
            ("color.py", [self.src, "--retag", "bt709"]),
            ("audio.py", [self.src, "--denoise"]),
            ("join.py", [self.src, self.src]),
        ]
        if not (OUT / "cues.srt").exists():
            script("caption.py", "--text", self.cues, "--write-srt", OUT / "cues.srt")
        for name, argv in cases:
            out = OUT / f"dry_{name}.mp4"
            proc = script(name, *argv, "-o", out, "--dry-run", "--json")
            self.assertFalse(out.exists(), f"{name} wrote a file in --dry-run")
            data = json.loads(proc.stdout)
            self.assertTrue(data["dry_run"], name)
            self.assertTrue(data["commands"] and all("ffmpeg" in c for c in data["commands"]), name)
            self.assertEqual(data["output"], str(out), name)
        # --json on a real run includes the probe of the output
        out = OUT / "json_cut.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "-o", out, "--json").stdout)
        self.assertClose(data["probe"]["duration"], 2.0, 0.6)

    # ---------------------------------------------------------------- help
    def test_every_script_has_help(self):
        for name in sorted(p.name for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")):
            with self.subTest(script=name):
                out = script(name, "--help").stdout
                self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
