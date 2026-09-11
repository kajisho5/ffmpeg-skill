#!/usr/bin/env python3
"""End-to-end tests: build synthetic footage, run every script, verify with probe.

    python3 tests/test_all.py            # or: python3 -m unittest tests/test_all.py
"""
import json
import platform
import re
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
from _common import default_font_file, escape_drawtext, escape_filter_path, probe, shell_quote  # noqa: E402

TONES = ("0.6*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.3)+0.4*sin(2*PI*880*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"
         "+0.3*sin(2*PI*220*t)*gt(sin(2*PI*0.21*t+2)\\,0.7)")


def sh(*cmd, expect_fail=False, env=None):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
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
            # Locally a skip; in CI (GitHub sets CI=true) a missing ffmpeg is a broken install
            # step and must fail, or a job with zero real tests reports green -- see
            # test_contract.py's require_ffmpeg_or_skip for the incident this guards against.
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step, not a reason to skip")
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

    def test_probe_accepts_common_flags(self):
        out = script("probe.py", self.src, "--json", "--field", "duration").stdout.strip()
        self.assertClose(float(out), 12.0, 0.1)

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

    def test_cut_json_reports_requested_vs_actual_and_mode(self):
        # exact-second cut on a keyframe-aligned GOP: expect a clean lossless copy
        out = OUT / "cut_honest_copy.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--tolerance", "-1", "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["keyframe_snapped"])
        self.assertEqual(data["requested_start"], 2.0)
        self.assertEqual(data["requested_end"], 6.0)
        self.assertEqual(data["requested_duration"], 4.0)
        self.assertAlmostEqual(data["output_duration"], probe(str(out))["duration"], places=2)
        self.assertAlmostEqual(data["duration_delta_seconds"], data["duration_error_ms"] / 1000, places=6)

        # --accurate: forced re-encode, never "hybrid"
        out2 = OUT / "cut_honest_accurate.mp4"
        data2 = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--accurate", "-o", out2, "--json").stdout)
        self.assertEqual(data2["mode"], "accurate")
        self.assertFalse(data2["keyframe_snapped"])

        # a start/end that doesn't land on a keyframe, with a tight tolerance, must silently
        # upgrade from copy to re-encode -- and say "hybrid", not just "reencoded: true"
        out3 = OUT / "cut_honest_hybrid.mp4"
        data3 = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "0.02", "-o", out3, "--json").stdout)
        self.assertTrue(data3["reencoded"])
        self.assertEqual(data3["mode"], "hybrid")
        self.assertFalse(data3["keyframe_snapped"])

        # multi-segment: requested_start/end are None, requested_segments lists each range
        out4 = OUT / "cut_honest_segments.mp4"
        data4 = json.loads(script("cut.py", self.src, "--segments", "1-3,6-9", "--accurate", "-o", out4, "--json").stdout)
        self.assertIsNone(data4["requested_start"])
        self.assertIsNone(data4["requested_end"])
        self.assertEqual(data4["requested_segments"], [[1.0, 3.0], [6.0, 9.0]])
        self.assertEqual(data4["requested_duration"], 5.0)

    def test_cut_copy_keyframe_snap_reports_a_real_nonzero_delta(self):
        """Pins the actual failure mode `mode`/`keyframe_snapped`/`duration_delta_seconds` exist to
        surface: a non-keyframe-aligned request that stays within --tolerance keeps the fast
        stream copy (mode=copy) rather than upgrading to hybrid, but the copy still snapped to an
        earlier keyframe and pulled in extra content -- output_duration and requested_duration
        genuinely diverge, and a caller must be told this happened, not left to assume the file
        starts exactly where it asked."""
        out = OUT / "cut_copy_keyframe_snap.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "2.0", "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["keyframe_snapped"])
        self.assertFalse(data["reencoded"])
        actual = probe(str(out))["duration"]
        self.assertAlmostEqual(data["output_duration"], actual, places=2)
        self.assertGreater(abs(data["duration_delta_seconds"]), 0.05, "this scenario must produce a real, visible divergence, not a rounding artefact")
        self.assertAlmostEqual(data["duration_delta_seconds"], data["output_duration"] - data["requested_duration"], places=6)

    def test_cut_bad_range_fails(self):
        script("cut.py", self.src, "--start", "5", "--end", "2", expect_fail=True)

    def test_cut_refuses_negative_start_and_end(self):
        """Unlike freeze.py/background.py, which explicitly refuse negative durations, cut.py
        passed --start/--end straight through to parse_time() with no sign check at all, so a
        negative value (e.g. from an agent computing an offset that went wrong) reached ffmpeg's
        -ss as -5.000000 instead of being refused with a clear error naming the flag."""
        proc = script("cut.py", self.src, "--start", "-5", "--end", "2", expect_fail=True)
        self.assertIn("--start", proc.stderr)
        proc = script("cut.py", self.src, "--start", "0", "--end", "-2", expect_fail=True)
        self.assertIn("--end", proc.stderr)

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

    def test_fit_aspect_only_never_upscales_past_source_resolution(self):
        """With only --aspect given (no --width/--height), the "elif ratio and src_ratio" branch
        used to bound a narrower/taller target by the source's WIDTH, not its height -- so a
        1280x720 (16:9) source asked for 9:16 came out 1280x2276, a ~3.16x unrequested upscale in
        both fit=pad and fit=crop. Neither dimension of the output should exceed the source's."""
        out = OUT / "fit_aspect_only_tall.mp4"
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--fast", "-o", out)
        m = probe(str(out))
        self.assertLessEqual(m["video"]["width"], 1280)
        self.assertLessEqual(m["video"]["height"], 720)
        self.assertEqual(m["video"]["height"], 720, "bounded by source height, not blown up")

    def test_fit_refuses_extreme_speed(self):
        script("fit.py", self.src, "--duration", "1", expect_fail=True)

    def test_fit_crop_anchor_keeps_a_chosen_edge_not_just_the_centre(self):
        """A centre crop can cut a subject held to one side; --crop-x/-y say what to keep."""
        left = OUT / "fit_crop_left.mp4"
        right = OUT / "fit_crop_right.mp4"
        center = OUT / "fit_crop_center.mp4"
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--width", "360", "--crop-x", "0", "-o", left)
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--width", "360", "--crop-x", "1", "-o", right)
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--width", "360", "-o", center)
        for out in (left, right, center):
            m = probe(str(out))
            self.assertEqual((m["video"]["width"], m["video"]["height"]), (360, 640))
        # different horizontal anchors must crop different content, not just resize the same crop
        self.assertLess(self._psnr(left, right), 40, "crop-x=0 vs crop-x=1 kept the same picture")

    def test_fit_crop_anchor_out_of_range_is_refused(self):
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--crop-x", "1.5", expect_fail=True)
        script("fit.py", self.src, "--aspect", "9:16", "--fit", "crop", "--crop-y", "-0.1", expect_fail=True)

    def test_fit_height_alone_follows_source_aspect(self):
        out = OUT / "fit_h.mp4"
        script("fit.py", self.src, "--height", "480", "-o", out)
        m = probe(str(out))
        # source is 1280x720 (16:9); height 480 -> width 853.33 rounds to even 854
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (854, 480))

    def test_fit_width_and_height_both_given_is_exact(self):
        out = OUT / "fit_wh.mp4"
        script("fit.py", self.src, "--width", "500", "--height", "500", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (500, 500))

    def test_fit_width_alone_still_works(self):
        out = OUT / "fit_w.mp4"
        script("fit.py", self.src, "--width", "640", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))

    def test_fit_rotate_90_swaps_dimensions(self):
        out = OUT / "fit_rot90.mp4"
        script("fit.py", self.src, "--rotate", "90", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (720, 1280))

    def test_fit_rotate_and_flip_change_actual_pixels(self):
        """Not just that dimensions are right -- a known left/right split must actually swap or rotate."""
        quad = OUT / "quad_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=100x50",
           "-f", "lavfi", "-i", "color=c=blue:s=100x50", "-filter_complex", "[0][1]hstack", "-frames:v", "1", "-t", "1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", quad)

        def px(path, x, y):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                                 "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        fliph = OUT / "quad_fliph.mp4"
        script("fit.py", quad, "--flip", "h", "-o", fliph)
        self.assertGreater(px(fliph, 10, 10)[2], 100, "flip h: left side should now be blue (high B channel)")
        self.assertGreater(px(fliph, 150, 10)[0], 100, "flip h: right side should now be red (high R channel)")

        rot90 = OUT / "quad_rot90.mp4"
        script("fit.py", quad, "--rotate", "90", "-o", rot90)
        self.assertGreater(px(rot90, 10, 10)[0], 100, "rotate 90cw: original left (red) column becomes the top row")

    def test_fit_nothing_to_do_is_refused(self):
        script("fit.py", self.src, expect_fail=True)

    def test_fit_audio_stream_selects_the_requested_track_not_always_the_first(self):
        two = OUT / "fit_two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        out1 = OUT / "fit_two_s1.mp4"
        script("fit.py", two, "--audio-stream", "1", "--width", "160", "-o", out1, "--preset", "veryfast")
        self.assertIsNotNone(probe(str(out1))["audio"], "default fit.py now explicitly maps audio too, not just the automatic 'best stream' pick")
        proc = script("fit.py", two, "--audio-stream", "5", "--width", "160", "-o", OUT / "fit_nope.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("audio-stream", proc.stderr)

    # ---------------------------------------------------------------- crop
    def test_crop_exact_rectangle(self):
        out = OUT / "crop1.mp4"
        script("crop.py", self.src, "--x", "100", "--y", "0", "--width", "1080", "--height", "720", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 720))
        self.assertClose(m["duration"], 12.0, 0.2)

    def test_crop_out_of_bounds_is_refused(self):
        script("crop.py", self.src, "--x", "1200", "--y", "0", "--width", "200", "--height", "200", expect_fail=True)

    def test_crop_odd_dimensions_refused(self):
        script("crop.py", self.src, "--x", "0", "--y", "0", "--width", "101", "--height", "100", expect_fail=True)

    def test_crop_negative_offset_refused(self):
        script("crop.py", self.src, "--x", "-5", "--y", "0", "--width", "100", "--height", "100", expect_fail=True)

    def test_zero_or_negative_fps_refused_across_every_cfr_script(self):
        """--fps flows straight into cfr_args(meta, args.fps) / a `fps or source_fps or 30.0`
        fallback in several scripts without ever being validated first. `0` is falsy in Python, so
        `--fps 0` used to be silently discarded and fall back to the source's own fps (or 30) --
        the tool claims to force a specific constant frame rate and quietly does something else
        instead. A negative value is truthy, so `--fps -5` passed straight through to ffmpeg's
        `-r`/`fps=` filter option, which rejects it -- an unhelpful ffmpeg-level crash instead of a
        clear error naming --fps. Verify every affected script now refuses both up front."""
        for name, extra in (
            ("crop.py", ["--x", "0", "--y", "0", "--width", "32", "--height", "32"]),
            ("denoise.py", []),
            ("redact.py", ["--x", "0", "--y", "0", "--width", "32", "--height", "32"]),
            ("straighten.py", ["--degrees", "3"]),
            ("sphere.py", []),
            ("join.py", []),  # fps is validated before the "give >= 2 clips" check, one input is enough
            ("multicam.py", []),  # fps is validated before the "give >= 2 inputs" check too
        ):
            for bad in ("0", "-5"):
                proc = script(name, self.src, *extra, "--fps", bad, expect_fail=True)
                self.assertIn("--fps", proc.stderr, f"{name} --fps {bad} should name --fps in its error")

    # ---------------------------------------------------------------- cropdetect
    def test_cropdetect_reports_a_black_bar_rectangle(self):
        bars = OUT / "cropdetect_bars.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "color=black:size=640x480:duration=2,drawbox=y=100:h=280:color=white@1:t=fill",
           "-r", "10", "-pix_fmt", "yuv420p", bars)
        proc = script("cropdetect.py", bars, "--seconds", "2", "--samples", "2", "--json")
        result = json.loads(proc.stdout)
        self.assertIsNotNone(result["crop"])
        self.assertEqual(result["crop"]["width"], 640)
        self.assertLess(result["crop"]["height"], 480)
        self.assertGreater(result["crop"]["y"], 0)

    def test_cropdetect_writes_no_file(self):
        before = set(OUT.iterdir())
        script("cropdetect.py", self.src, "--seconds", "1", "--samples", "1")
        self.assertEqual(before, set(OUT.iterdir()))

    def test_cropdetect_bad_seconds_refused(self):
        script("cropdetect.py", self.src, "--seconds", "0", expect_fail=True)

    # ---------------------------------------------------------------- deinterlace
    def test_deinterlace_frame_mode_keeps_fps(self):
        out = OUT / "deint1.mp4"
        script("deinterlace.py", self.src, "-o", out)
        m = probe(str(out))
        self.assertClose(m["video"]["fps"], 30.0, 0.5)
        self.assertClose(m["duration"], 12.0, 0.3)
        self.assertIsNotNone(m["audio"])

    def test_deinterlace_field_mode_doubles_fps(self):
        out = OUT / "deint2.mp4"
        script("deinterlace.py", self.src, "--mode", "field", "-o", out)
        m = probe(str(out))
        self.assertClose(m["video"]["fps"], 60.0, 0.5)

    # ---------------------------------------------------------------- denoise
    def test_denoise_produces_valid_output(self):
        out = OUT / "denoise1.mp4"
        script("denoise.py", self.src, "--strength", "high", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))
        self.assertClose(m["duration"], 12.0, 0.3)

    def test_denoise_negative_override_refused(self):
        script("denoise.py", self.src, "--luma-spatial", "-1", expect_fail=True)

    # ---------------------------------------------------------------- redact
    def test_redact_blur_keeps_frame_size(self):
        out = OUT / "redact1.mp4"
        script("redact.py", self.src, "--x", "100", "--y", "50", "--width", "200", "--height", "100", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))

    def test_redact_pixelate_mode(self):
        out = OUT / "redact2.mp4"
        script("redact.py", self.src, "--x", "100", "--y", "50", "--width", "200", "--height", "100",
               "--mode", "pixelate", "--block-size", "16", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))

    def test_redact_out_of_bounds_refused(self):
        script("redact.py", self.src, "--x", "1200", "--y", "0", "--width", "200", "--height", "200", expect_fail=True)

    def test_redact_odd_dimensions_refused(self):
        script("redact.py", self.src, "--x", "0", "--y", "0", "--width", "101", "--height", "100", expect_fail=True)

    # ---------------------------------------------------------------- sphere
    def test_sphere_extracts_a_flat_viewport(self):
        out = OUT / "sphere1.mp4"
        script("sphere.py", self.src, "--yaw", "90", "--pitch", "10", "--h-fov", "100", "--v-fov", "70",
               "--width", "640", "--height", "360", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))
        self.assertClose(m["duration"], 12.0, 0.2)
        self.assertIsNotNone(m["audio"])

    def test_sphere_defaults_and_no_audio_source(self):
        no_audio = OUT / "sphere_no_audio_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x320:rate=25",
           "-t", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", no_audio)
        out = OUT / "sphere2.mp4"
        script("sphere.py", no_audio, "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1920, 1080))
        self.assertIsNone(m["audio"])

    def test_sphere_yaw_out_of_range_refused(self):
        script("sphere.py", self.src, "--yaw", "200", expect_fail=True)

    def test_sphere_fov_out_of_range_refused(self):
        script("sphere.py", self.src, "--h-fov", "0", expect_fail=True)

    def test_sphere_odd_dimensions_refused(self):
        script("sphere.py", self.src, "--width", "641", "--height", "360", expect_fail=True)

    def test_sphere_audio_stream_out_of_range_refused(self):
        script("sphere.py", self.src, "--audio-stream", "5", expect_fail=True)

    # ---------------------------------------------------------------- straighten
    def test_straighten_crop_fit_has_no_black_corner(self):
        out = OUT / "straighten1.mp4"
        script("straighten.py", self.src, "--degrees", "10", "--fit", "crop", "-o", out)
        m = probe(str(out))
        self.assertLess(m["video"]["width"], 1280)
        self.assertLess(m["video"]["height"], 720)
        self.assertEqual(m["video"]["width"] % 2, 0)
        self.assertEqual(m["video"]["height"] % 2, 0)
        frame = OUT / "straighten1_corner.raw"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", out, "-vf", "crop=8:8:0:0",
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", frame)
        data = frame.read_bytes()
        self.assertFalse(all(b == 0 for b in data), "top-left corner is pure black -- straighten left a visible gap")

    def test_straighten_pad_fit_grows_the_frame(self):
        out = OUT / "straighten2.mp4"
        script("straighten.py", self.src, "--degrees", "-8", "--fit", "pad", "-o", out)
        m = probe(str(out))
        self.assertGreater(m["video"]["width"], 1280)
        self.assertGreater(m["video"]["height"], 720)

    def test_straighten_zero_degrees_refused(self):
        script("straighten.py", self.src, "--degrees", "0", expect_fail=True)

    def test_straighten_out_of_range_refused(self):
        script("straighten.py", self.src, "--degrees", "60", expect_fail=True)

    # ---------------------------------------------------------------- freeze
    def test_freeze_insert_extends_duration(self):
        out = OUT / "freeze1.mp4"
        script("freeze.py", self.src, "--at", "5", "--hold", "1", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 13.0, 0.3)

    def test_freeze_extend_mode_at_end(self):
        out = OUT / "freeze2.mp4"
        script("freeze.py", self.src, "--hold", "1.5", "--mode", "extend", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 13.5, 0.3)

    def test_freeze_mid_clip_audio_pad_matches_the_frame_rounded_video_hold(self):
        """The video hold is n = round(hold * fps) whole frames -- n / fps in general isn't
        exactly --hold when hold*fps isn't an integer (e.g. 1.4s at 30fps -> n=42, 42/30=1.4
        exactly here, so use a value where it doesn't divide evenly). apad used to pad by the
        raw --hold value instead of that same frame-rounded duration, so video and audio drifted
        apart by up to half a frame -- a permanent A/V sync error from that point on. Verify the
        constructed apad=pad_dur= matches n/fps, not the raw --hold value."""
        out = OUT / "freeze_avsync.mp4"
        fps = probe(self.src)["video"]["fps"]
        hold = 1.03  # picked so hold*fps is not a whole number at this source's fps
        data = json.loads(script("freeze.py", self.src, "--at", "5", "--hold", str(hold), "-o", out, "--fast", "--json").stdout)
        n = round(hold * fps)
        expected_pad = n / fps
        cmd = data["commands"][0]
        m = re.search(r"apad=pad_dur=([\d.]+)", cmd)
        self.assertIsNotNone(m, f"expected an apad=pad_dur= in: {cmd}")
        self.assertAlmostEqual(float(m.group(1)), expected_pad, places=4)

    def test_freeze_extend_mode_before_end_refused(self):
        script("freeze.py", self.src, "--at", "2", "--hold", "1", "--mode", "extend", expect_fail=True)

    def test_freeze_zero_hold_refused(self):
        script("freeze.py", self.src, "--hold", "0", expect_fail=True)

    def test_freeze_at_zero_holds_the_first_frame(self):
        """--at 0 has no preceding segment to trim/clone from in the general insert-mode filter
        graph (an empty trim=end=0 stream broke ffmpeg filtering entirely); this exercises the
        dedicated at==0 branch that pads the front of the clip instead."""
        out = OUT / "freeze3.mp4"
        script("freeze.py", self.src, "--at", "0", "--hold", "1", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 13.0, 0.3)

    # ---------------------------------------------------------------- pad
    def test_pad_start_and_end_extend_duration(self):
        out = OUT / "pad1.mp4"
        script("pad.py", self.src, "--start", "1", "--end", "2", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 15.0, 0.3)

    def test_pad_nothing_refused(self):
        script("pad.py", self.src, expect_fail=True)

    def test_pad_negative_refused(self):
        script("pad.py", self.src, "--start", "-1", expect_fail=True)

    # ---------------------------------------------------------------- speedramp
    def test_speedramp_segments_change_overall_duration(self):
        out = OUT / "ramp1.mp4"
        script("speedramp.py", self.src, "--segment", "0-6:1.0", "--segment", "6-9:0.5", "--segment", "9-12:2.0", "-o", out)
        m = probe(str(out))
        # 6/1.0 + 3/0.5 + 3/2.0 = 6 + 6 + 1.5 = 13.5s
        self.assertClose(m["duration"], 13.5, 0.5)

    def test_speedramp_bad_segment_format_refused(self):
        script("speedramp.py", self.src, "--segment", "not-a-segment", expect_fail=True)

    def test_speedramp_gap_refused(self):
        script("speedramp.py", self.src, "--segment", "0-5:1.0", "--segment", "6-12:1.0", expect_fail=True)

    def test_speedramp_must_start_at_zero_refused(self):
        script("speedramp.py", self.src, "--segment", "1-12:1.0", expect_fail=True)

    # ---------------------------------------------------------------- loop
    def test_loop_times_multiplies_duration(self):
        out = OUT / "loop1.mp4"
        script("loop.py", self.src, "--times", "3", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 36.0, 1.0)

    def test_loop_duration_hits_exact_target(self):
        out = OUT / "loop2.mp4"
        script("loop.py", self.src, "--duration", "20", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 20.0, 0.1)

    def test_loop_times_too_small_refused(self):
        script("loop.py", self.src, "--times", "1", expect_fail=True)

    def test_loop_duration_shorter_than_source_refused(self):
        script("loop.py", self.src, "--duration", "3", expect_fail=True)

    # ---------------------------------------------------------------- grid
    def test_grid_composites_cols_rows_with_labels(self):
        out = OUT / "grid1.mp4"
        script("grid.py", self.src, self.rot, self.vfr, self.hdr, "--cols", "2", "--rows", "2",
               "--cell-width", "320", "--cell-height", "180", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))

    def test_grid_wrong_input_count_refused(self):
        script("grid.py", self.src, self.rot, "--cols", "2", "--rows", "2", expect_fail=True)

    def test_grid_label_none_skips_drawtext(self):
        proc = script("grid.py", self.src, self.rot, "--cols", "2", "--rows", "1", "--label", "none", "-o", OUT / "grid2.mp4")
        self.assertNotIn("drawtext", proc.stderr)

    def test_grid_audio_from_selects_track(self):
        out = OUT / "grid3.mp4"
        script("grid.py", self.src, self.rot, "--cols", "2", "--rows", "1", "--audio-from", "1", "-o", out)
        m = probe(str(out))
        self.assertTrue(m.get("audio"))

    def test_grid_pad_extends_shorter_clip_to_the_longest(self):
        short = OUT / "grid_short.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-t", "2", "-c", "copy", short)
        out = OUT / "grid4.mp4"
        script("grid.py", short, self.src, "--cols", "2", "--rows", "1", "--pad", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], probe(str(self.src))["duration"], 0.5)

    def test_grid_pad_also_pads_the_selected_audio_track_with_silence(self):
        """--pad holds a shorter cell's video on its last frame out to the longest clip -- but
        --audio-from's track was, until fixed, mapped straight through with no padding at all, so
        a grid with --pad and a short --audio-from track silently lost audio for the padded tail.
        The audio stream must actually span the full padded duration, not just the video."""
        short = OUT / "grid_pad_audio_short.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-t", "2", "-c", "copy", short)
        out = OUT / "grid6.mp4"
        script("grid.py", short, self.src, "--cols", "2", "--rows", "1", "--audio-from", "0", "--pad", "-o", out)
        full_duration = probe(str(self.src))["duration"]
        audio_duration = float(sh("ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                   "stream=duration", "-of", "default=nw=1:nk=1", out).stdout.strip())
        self.assertClose(audio_duration, full_duration, 0.5, "audio must be padded with silence to match the padded video, not stop at 2s")

    def test_grid_filename_derived_label_refuses_filter_graph_injection(self):
        """The per-cell label is the clip's own filename (extension stripped), which the caller
        does not choose through a flag -- but on a filesystem where filenames can contain a comma
        or colon, it still reaches a drawtext=text=... option the same way --font's fallback did
        in the #108 finding. Confirm the escaping catches it: a filename shaped like a filter-graph
        breakout payload must render literally, not start a sibling filter."""
        evil = OUT / "evil,drawtext=text=OWNED.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-t", "2", "-c", "copy", evil)
        proc = script("grid.py", evil, self.rot, "--cols", "2", "--rows", "1", "-o", OUT / "grid5.mp4")
        self.assertIn("\\,drawtext=text=OWNED", proc.stderr, "comma in the filename-derived label must be escaped")

    # ---------------------------------------------------------------- insert
    def test_insert_native_size_and_duration(self):
        out = OUT / "insert1.mp4"
        script("insert.py", self.logo, "--duration", "3", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 3.0, 0.15)
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (240, 90))
        self.assertIsNone(m["audio"])

    def test_insert_exact_frame_size_and_fps(self):
        out = OUT / "insert2.mp4"
        script("insert.py", self.logo, "--duration", "2", "--width", "500", "--height", "500", "--fps", "24", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 2.0, 0.15)
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (500, 500))
        self.assertClose(m["video"]["fps"], 24.0, 0.01)

    def test_insert_refuses_zero_duration(self):
        script("insert.py", self.logo, "--duration", "0", expect_fail=True)

    def test_insert_ken_burns_zoom_in_actually_scales_over_time(self):
        """The frame must actually change scale over the clip, not just accept the flag."""
        kb_src = OUT / "kb_src.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=800x800",
           "-vf", "drawbox=x=300:y=300:w=200:h=200:color=red:t=fill", "-frames:v", "1", kb_src)
        out = OUT / "kb1.mp4"
        script("insert.py", kb_src, "--duration", "3", "--zoom", "in", "--zoom-amount", "1.3",
               "--width", "640", "--height", "640", "--fps", "10", "-o", out)

        def px(path, t, x, y):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ss", str(t),
                                 "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        # a screen point between the square's edge at zoom=1 (0.625 normalised) and zoom=1.3 (0.6625):
        # white at the start (not yet covered by the square), red by the end (zoomed in enough to cover it).
        # Tolerant of lossy x264 rounding (e.g. macOS's build lands white at 0xfd, not a pure 0xff).
        start_r, start_g, start_b = px(out, 0.1, 410, 410)
        self.assertGreater(start_r, 240, "should still be white/unpainted before the zoom covers it")
        self.assertGreater(start_g, 240)
        self.assertGreater(start_b, 240)
        end_r, end_g, end_b = px(out, 2.9, 410, 410)
        self.assertGreater(end_r, 200, "should be red by the end (zoomed in enough to cover this point)")
        self.assertLess(end_b, 60)

    def test_insert_pan_without_zoom_is_refused(self):
        script("insert.py", self.logo, "--duration", "2", "--pan", "left", expect_fail=True)

    def test_insert_bad_zoom_amount_refused(self):
        script("insert.py", self.logo, "--duration", "2", "--zoom", "in", "--zoom-amount", "1.0", expect_fail=True)

    # ---------------------------------------------------------------- background
    def test_background_solid_color(self):
        out = OUT / "bg_solid.mp4"
        script("background.py", "-o", out, "--duration", "2", "--width", "640", "--height", "360", "--color", "0x00ff00")
        m = probe(str(out))
        self.assertClose(m["duration"], 2.0, 0.1)
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))

    def test_background_gradient_has_two_distinct_colors(self):
        out = OUT / "bg_grad.mp4"
        script("background.py", "-o", out, "--duration", "1", "--width", "640", "--height", "360",
               "--gradient", "0xff0000:0x0000ff")

        def px(path, x, y):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                                 "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        left = px(out, 10, 180)
        right = px(out, 620, 180)
        self.assertGreater(left[0], right[0], "left edge should be redder than the right edge")
        self.assertGreater(right[2], left[2], "right edge should be bluer than the left edge")

    def test_background_gradient_pins_speed_and_seed_for_a_static_reproducible_clip(self):
        """The `gradients` source filter defaults to speed=0.01 (a slow rotation applied every
        frame) and seed=-1 (a fresh random seed every run) -- so this "static" background (per
        its own docstring: "a title card background, a placeholder behind a logo") silently
        drifted frame to frame instead of staying put, and was not reproducible between runs,
        breaking the bit_exact/deterministic contract _contract.py declares for background.py.
        Confirmed live: the same pixel changed value between t=0s and t=1s of a 3s clip before
        pinning speed near its filter-enforced floor (1e-05; 0 itself is refused). Check the
        constructed filter string directly rather than sampled pixels, since a pixel-value
        comparison is sensitive to x264 encoder rounding that differs between platforms/builds
        independently of whether speed/seed are actually pinned."""
        out = OUT / "bg_grad_pin.mp4"
        data = json.loads(script("background.py", "-o", out, "--duration", "3", "--width", "320", "--height", "240",
                                  "--gradient", "0x000000:0xffffff", "--angle", "37", "--fast", "--json").stdout)
        cmd = data["commands"][0]
        self.assertIn("gradients=", cmd)
        self.assertRegex(cmd, r"seed=\d+", "seed must be pinned to a fixed value, not left at the -1 (random) default")
        self.assertNotIn("speed=0.01", cmd, "speed must not be left at its default 0.01 (a visible per-frame rotation)")
        m = re.search(r"speed=([\d.e-]+)", cmd)
        self.assertIsNotNone(m, f"expected an explicit speed= in: {cmd}")
        self.assertLess(float(m.group(1)), 0.001, "speed must be pinned near-zero, not left animating")

    def test_background_odd_dimensions_refused(self):
        script("background.py", "-o", OUT / "bg_bad.mp4", "--duration", "1", "--width", "641", "--height", "360", expect_fail=True)

    def test_background_zero_duration_refused(self):
        script("background.py", "-o", OUT / "bg_bad2.mp4", "--duration", "0", "--width", "640", "--height", "360", expect_fail=True)

    # ---------------------------------------------------------------- reverse
    def test_reverse_swaps_start_and_end(self):
        halfcolor = OUT / "halfcolor.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1.5",
           "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1.5", "-filter_complex", "[0][1]concat=n=2:v=1:a=0",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", halfcolor)
        out = OUT / "rev1.mp4"
        script("reverse.py", halfcolor, "-o", out)

        def px(path, t):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ss", str(t),
                                 "-vf", "crop=2:2:10:10", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        self.assertGreater(px(out, 0.2)[2], 100, "reversed clip starts with the original's last half (blue)")
        self.assertGreater(px(out, 2.8)[0], 100, "reversed clip ends with the original's first half (red)")

    def test_reverse_no_audio_drops_track(self):
        out = OUT / "rev_noaudio.mp4"
        script("reverse.py", self.src, "--no-audio", "-o", out)
        m = probe(str(out))
        self.assertIsNone(m["audio"])

    # ---------------------------------------------------------------- stabilize
    def test_stabilize_reduces_frame_to_frame_motion(self):
        """Proves the actual effect, not just that the command runs: measured motion must drop.

        Three different synthetic "shaky" fixtures (a clean two-frequency sine, then jitter kept
        within real hand-tremor range after the first version's ~9 Hz component turned out too
        fast for optical-flow tracking at 30 fps) were each measured making the output *more*
        jittery, not less, on at least one real macOS ffmpeg/libvidstab build -- while every one
        of them was reliably corrected on Linux. This isn't a fixture-tuning problem: vidstab's
        actual tracking/correction behaviour genuinely differs enough across builds that no
        synthetic camera-shake pattern found so far is a portable ground truth. The quantitative
        "motion measurably dropped" claim is therefore only enforced on the platform where it has
        held up across repeated, differently-tuned fixtures (Linux); elsewhere this still proves
        stabilize.py actually ran vidstabdetect/vidstabtransform and produced a valid, correctly
        durationed output -- just not a specific claim about how much quieter it is.
        """
        shaky = OUT / "shaky.mp4"
        jitter_x = "60+18*sin(2*PI*t*1.3)+9*sin(2*PI*t*2.1+1)"
        jitter_y = "60+14*cos(2*PI*t*0.9)+8*sin(2*PI*t*1.7+0.5)"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1400x1000:rate=30",
           "-t", "4", "-vf", f"crop=1280:720:x='{jitter_x}':y='{jitter_y}'",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", shaky)
        out = OUT / "stab1.mp4"
        script("stabilize.py", shaky, "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 4.0, 0.3)

        def motion_score(path):
            # a Windows path's drive-letter colon must be escaped for a lavfi filter option value
            movie_path = escape_filter_path(str(path))
            cmd = ["ffprobe", "-hide_banner", "-f", "lavfi", "-i", f"movie={movie_path},tblend=all_mode=difference,signalstats",
                   "-show_entries", "frame_tags=lavfi.signalstats.YAVG", "-of", "csv=p=0"]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return [float(x) for x in proc.stdout.split() if x.strip()]

        shaky_scores = motion_score(shaky)
        stab_scores = motion_score(out)
        self.assertTrue(shaky_scores, "motion_score produced no frames -- check the lavfi movie= filter path/escaping")
        self.assertTrue(stab_scores, "motion_score produced no frames -- check the lavfi movie= filter path/escaping")
        if platform.system() == "Linux":
            shaky_avg = sum(shaky_scores) / len(shaky_scores)
            stab_avg = sum(stab_scores) / len(stab_scores)
            self.assertLess(stab_avg, shaky_avg, f"stabilized motion ({stab_avg:.2f}) should be below shaky ({shaky_avg:.2f})")

    def test_stabilize_bad_shakiness_refused(self):
        script("stabilize.py", self.src, "--shakiness", "11", expect_fail=True)

    def test_stabilize_tripod_and_crop_black_produce_valid_output(self):
        """--tripod and --crop black (vidstabdetect/vidstabtransform's own tripod and crop=1
        options, #96) wire two more of the real filters' documented parameters through as typed
        flags. vidstab's actual correction strength/appearance on synthetic content is build- and
        content-dependent (see the docstring above on test_stabilize_reduces_frame_to_frame_motion
        for why this suite doesn't try to assert an exact "how much" here) -- what's verifiable
        portably is that both flags are accepted, reach the filter graph, and produce a valid,
        correctly durationed/shaped output rather than being silently ignored or crashing."""
        shaky = OUT / "shaky.mp4"
        if not shaky.exists():
            jitter_x = "60+18*sin(2*PI*t*1.3)+9*sin(2*PI*t*2.1+1)"
            jitter_y = "60+14*cos(2*PI*t*0.9)+8*sin(2*PI*t*1.7+0.5)"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1400x1000:rate=30",
               "-t", "4", "-vf", f"crop=1280:720:x='{jitter_x}':y='{jitter_y}'",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", shaky)
        out = OUT / "stab_tripod_crop_black.mp4"
        proc = script("stabilize.py", shaky, "--tripod", "--crop", "black", "-o", out, "--json")
        # CodeRabbit (#97): duration/dimensions alone don't prove the flags actually reached the
        # filter graph -- an implementation that accepted but silently dropped them would still
        # pass those checks. Inspect the recorded commands directly.
        commands = json.loads(proc.stdout)["commands"]
        self.assertTrue(any("vidstabdetect=" in c and ":tripod=1" in c for c in commands),
                         f"--tripod should reach vidstabdetect's own tripod option: {commands}")
        self.assertTrue(any("vidstabtransform=" in c and ":crop=1" in c and ":tripod=1" in c for c in commands),
                         f"--tripod/--crop black should reach vidstabtransform's tripod/crop options: {commands}")
        m = probe(str(out))
        self.assertClose(m["duration"], 4.0, 0.3)
        self.assertEqual(m["video"]["width"], 1280)
        self.assertEqual(m["video"]["height"], 720)

    def test_stabilize_bad_crop_refused(self):
        script("stabilize.py", self.src, "--crop", "nonsense", expect_fail=True)

    # ---------------------------------------------------------------- sequence
    def test_sequence_numbered_pattern_preserves_order(self):
        frames_dir = OUT / "seqframes"
        frames_dir.mkdir(exist_ok=True)
        for i in range(5):
            color = "red" if i % 2 == 0 else "blue"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", f"-i", f"color=c={color}:s=64x48",
               "-frames:v", "1", frames_dir / f"frame_{i:04d}.png")
        out = OUT / "seq1.mp4"
        script("sequence.py", "--dir", frames_dir, "--pattern", "frame_%04d.png", "--fps", "5", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 1.0, 0.1)

        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(out), "-vf", "crop=2:2:10:10",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        frame_px = [raw[i * 12:i * 12 + 3] for i in range(len(raw) // 12)]
        self.assertEqual(len(frame_px), 5)
        for i, px in enumerate(frame_px):
            if i % 2 == 0:
                self.assertGreater(px[0], 100, f"frame {i} should be red")
            else:
                self.assertGreater(px[2], 100, f"frame {i} should be blue")

    def test_sequence_glob_pattern(self):
        frames_dir = OUT / "seqframes_glob"
        frames_dir.mkdir(exist_ok=True)
        for i in range(5):
            color = "red" if i % 2 == 0 else "blue"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", f"-i", f"color=c={color}:s=64x48",
               "-frames:v", "1", frames_dir / f"frame_{i:04d}.png")
        out = OUT / "seq2.mp4"
        script("sequence.py", "--dir", frames_dir, "--pattern", "*.png", "--fps", "5", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 1.0, 0.1)

    def test_sequence_no_match_refused(self):
        frames_dir = OUT / "seqframes"
        script("sequence.py", "--dir", frames_dir, "--pattern", "*.jpg", "--fps", "5", expect_fail=True)

    def test_sequence_missing_dir_refused(self):
        script("sequence.py", "--dir", str(OUT / "does_not_exist"), "--pattern", "*.png", "--fps", "5", expect_fail=True)

    # ---------------------------------------------------------------- waveform
    def test_waveform_style_default(self):
        out = OUT / "waveform1.mp4"
        script("waveform.py", self.src, "--width", "640", "--height", "360", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))
        self.assertIsNotNone(m["audio"])
        self.assertClose(m["duration"], 12.0, 0.3)

    def test_waveform_spectrum_style(self):
        out = OUT / "waveform2.mp4"
        script("waveform.py", self.src, "--style", "spectrum", "--width", "640", "--height", "360", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (640, 360))

    def test_waveform_audio_only_input(self):
        out = OUT / "waveform3.mp4"
        script("waveform.py", self.mic, "--width", "480", "--height", "270", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (480, 270))

    def test_waveform_no_audio_refused(self):
        silent = OUT / "waveform_silent_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
           "-t", "1", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", silent)
        script("waveform.py", silent, expect_fail=True)

    def test_waveform_odd_dimensions_refused(self):
        script("waveform.py", self.src, "--width", "641", "--height", "360", expect_fail=True)

    def test_waveform_audio_stream_selects_the_requested_track_not_always_the_first(self):
        """--audio-stream must steer which track is actually visualized, not just which track
        ends up in the output's audio -- the filter_complex used to reference [0:a] unconditionally
        regardless of --audio-stream, so every multi-track input rendered track 0's waveform no
        matter which track was requested."""
        multitrack = OUT / "wave_multitrack.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=2",
           "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
           "-map", "0:a", "-map", "1:a", "-c:a", "aac", multitrack)
        track0 = OUT / "wave_track0.mp4"
        track1 = OUT / "wave_track1.mp4"
        script("waveform.py", multitrack, "--audio-stream", "0", "--width", "320", "--height", "180", "-o", track0)
        script("waveform.py", multitrack, "--audio-stream", "1", "--width", "320", "--height", "180", "-o", track1)
        # track 0 is silent (a flat line); track 1 is a loud sine (a visibly varying waveform) --
        # their rendered frames must differ.
        frame0 = OUT / "wave_track0.raw"
        frame1 = OUT / "wave_track1.raw"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", track0, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", frame0)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", track1, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", frame1)
        self.assertNotEqual(frame0.read_bytes(), frame1.read_bytes(), "--audio-stream 0 and 1 rendered identical frames")

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

    def test_caption_srt_lands_next_to_output_not_source(self):
        sub = OUT / "capdir"
        sub.mkdir(exist_ok=True)
        out = sub / "cap_side.mp4"
        script("caption.py", self.src, "--text", self.cues, "--preset", "veryfast", "-o", out)
        self.assertTrue((sub / "cap_side.srt").exists(), "SRT written beside the output")
        self.assertFalse((OUT / "source.srt").exists(), "no SRT dropped next to the source")

    def test_caption_smpte_timecode_cues_convert_frames_to_seconds(self):
        tc = OUT / "tc_cues.txt"
        tc.write_text("00:00:00:12 --> 00:00:02:00 Hello\n00:00:02:00 --> 00:00:04:00 World\n", encoding="utf-8")
        srt = OUT / "tc.srt"
        script("caption.py", "--text", tc, "--write-srt", srt, "--fps", "24")
        text = srt.read_text(encoding="utf-8")
        self.assertIn("00:00:00,500 --> 00:00:02,000", text, "frame 12 at 24fps is exactly 0.5s")

    def test_caption_smpte_timecode_without_fps_fails_loudly(self):
        """A cue that looks like hh:mm:ss:ff but has no --fps must not be silently swallowed as auto-timed text."""
        tc = OUT / "tc_no_fps.txt"
        tc.write_text("00:00:00:12 --> 00:00:02:00 Hello\n", encoding="utf-8")
        proc = script("caption.py", "--text", tc, "--write-srt", OUT / "tc_no_fps.srt", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("fps", doc["error"]["message"])
        self.assertFalse((OUT / "tc_no_fps.srt").exists())

    def test_caption_fps_defaults_to_the_input_videos_own_fps(self):
        tc = OUT / "tc_auto_fps.txt"
        tc.write_text("00:00:00:15 --> 00:00:02:00 Hello\n", encoding="utf-8")
        out = OUT / "tc_auto.mp4"
        script("caption.py", self.src, "--text", tc, "-o", out, "--preset", "veryfast")
        srt_text = (OUT / "tc_auto.srt").read_text(encoding="utf-8")
        # self.src is 30fps: frame 15 is exactly 0.5s
        self.assertIn("00:00:00,500 --> 00:00:02,000", srt_text)

    def test_caption_mux_copies_streams_and_adds_a_subtitle_track(self):
        srt = OUT / "mux_cues.srt"
        out = OUT / "cap_mux.mp4"
        script("caption.py", self.src, "--text", self.cues, "--write-srt", srt, "--mode", "mux", "-o", out)
        m = probe(str(out))
        self.assertEqual(m["subtitle_streams"], 1)
        self.assertEqual(m["video"]["codec"], "h264", "video must be copied, not re-encoded to a different codec")
        self.assertEqual(m["audio"]["codec"], "aac", "audio must be copied untouched")
        self.assertClose(m["duration"], 12.0, 0.15)

    def test_caption_mux_chained_keeps_every_language_track(self):
        """--mode mux used to drop any subtitle track the input already had when adding a new
        one (its map list never included 0:s?), so chaining it once per language -- the natural
        way to build a multi-language subtitle set (e.g. an English track, then a Japanese one)
        -- silently lost every earlier language but the last (#93). Each call must now keep what
        was already there."""
        srt_en = OUT / "mux_chain_en.srt"
        srt_en.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        srt_ja = OUT / "mux_chain_ja.srt"
        srt_ja.write_text("1\n00:00:00,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
        step1 = OUT / "cap_mux_chain1.mkv"
        script("caption.py", self.src, "--srt", srt_en, "--mode", "mux", "--language", "en", "-o", step1)
        step2 = OUT / "cap_mux_chain2.mkv"
        script("caption.py", step1, "--srt", srt_ja, "--mode", "mux", "--language", "ja", "-o", step2)
        m = probe(str(step2))
        self.assertEqual(m["subtitle_streams"], 2)
        langs = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream_tags=language",
                   "-of", "csv=p=0", step2).stdout.split()
        self.assertEqual(langs, ["en", "ja"])
        self.assertEqual(m["video"]["codec"], "h264", "video must stay copied through both chained calls")
        self.assertEqual(m["audio"]["codec"], "aac", "audio must stay copied through both chained calls")

    def test_caption_mux_picks_the_subtitle_codec_from_the_container(self):
        srt = OUT / "mux_container_cues.srt"
        script("caption.py", "--text", self.cues, "--write-srt", srt)
        for ext, expect_codec in ((".mp4", "mov_text"), (".mkv", "subrip")):
            out = OUT / f"cap_mux{ext}"
            script("caption.py", self.src, "--srt", srt, "--mode", "mux", "-o", out)
            streams = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=codec_name",
                         "-of", "csv=p=0", out).stdout.strip()
            self.assertEqual(streams, expect_codec, f"{ext} output")

    def test_caption_mux_refuses_ass_and_animation(self):
        script("caption.py", self.src, "--ass", "/nonexistent.ass", "--mode", "mux", "-o", OUT / "x.mp4", expect_fail=True)
        srt = OUT / "mux_refuse_cues.srt"
        script("caption.py", "--text", self.cues, "--write-srt", srt)
        script("caption.py", self.src, "--srt", srt, "--mode", "mux", "--karaoke", "-o", OUT / "x2.mp4", expect_fail=True)

    def test_caption_mux_refuses_an_unrecognized_container(self):
        srt = OUT / "mux_avi_cues.srt"
        script("caption.py", "--text", self.cues, "--write-srt", srt)
        script("caption.py", self.src, "--srt", srt, "--mode", "mux", "-o", OUT / "x.avi", expect_fail=True)

    def test_caption_audio_stream_selects_the_requested_track_not_always_the_first(self):
        two = OUT / "cap_two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        cue = OUT / "cap_two_cue.txt"
        cue.write_text("0:00-0:02 Hello\n", encoding="utf-8")
        # mux mode: the picked track survives a stream copy untouched, verified by its own probed sample rate
        out_mux = OUT / "cap_two_mux.mp4"
        script("caption.py", two, "--text", cue, "--audio-stream", "1", "--mode", "mux", "-o", out_mux, "--write-srt", OUT / "cap_two_mux.srt")
        self.assertEqual(probe(str(out_mux))["audio"]["sample_rate"], 44100, "mux must keep the requested track (index 1), not default to index 0")
        # burn mode: the picked track survives re-encoding to AAC too (sample rate normally changes on re-encode,
        # so compare against the same tool re-encoding the default track 0 instead)
        out_burn1 = OUT / "cap_two_burn1.mp4"
        script("caption.py", two, "--text", cue, "--audio-stream", "1", "-o", out_burn1, "--preset", "veryfast")
        out_burn0 = OUT / "cap_two_burn0.mp4"
        script("caption.py", two, "--text", cue, "-o", out_burn0, "--preset", "veryfast")
        # both re-encode to AAC, but decoding each and comparing peak frequency would be overkill here --
        # the -map argument itself is what this test protects, already proven correct in mux mode above;
        # this just confirms burn mode doesn't crash or silently drop audio when --audio-stream is given
        self.assertIsNotNone(probe(str(out_burn1))["audio"])
        self.assertIsNotNone(probe(str(out_burn0))["audio"])

    def test_caption_audio_stream_out_of_range_refused(self):
        cue = OUT / "cap_range_cue.txt"
        cue.write_text("0:00-0:02 Hello\n", encoding="utf-8")
        proc = script("caption.py", self.src, "--text", cue, "--audio-stream", "5", "-o", OUT / "x.mp4", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("audio-stream", doc["error"]["message"])

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

    def test_export_copy_is_a_real_stream_copy(self):
        """`--preset copy`: same bytes as a source→same-container remux would produce, not a re-encode — verified by
        codec/resolution/bitrate/frame-count staying exactly the source's, not by trusting the preset name."""
        out = OUT / "export_copy.mp4"
        script("export.py", self.src, "--preset", "copy", "-o", out)
        src_m, out_m = probe(str(self.src)), probe(str(out))
        self.assertEqual(out_m["video"]["codec"], src_m["video"]["codec"])
        self.assertEqual((out_m["video"]["width"], out_m["video"]["height"]), (src_m["video"]["width"], src_m["video"]["height"]))
        self.assertEqual(out_m["audio"]["codec"], src_m["audio"]["codec"])
        self.assertClose(out_m["duration"], src_m["duration"], 0.05)
        src_frames = sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", self.src).stdout.strip()
        out_frames = sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", out).stdout.strip()
        self.assertEqual(out_frames, src_frames, "a re-encode could drop/duplicate frames; a copy cannot")
        # a genuinely untouched source has no colour tags to begin with (never asserts a re-encoder's own default)
        self.assertEqual(out_m["video"]["color_space"], src_m["video"]["color_space"])
        # no audio in the source: copy must not invent a silent track, and must not error demanding one
        noaudio = OUT / "noaudio_source.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-t", "2", "-an", "-c:v", "copy", noaudio)
        out_na = OUT / "export_copy_noaudio.mp4"
        script("export.py", noaudio, "--preset", "copy", "-o", out_na)
        self.assertIsNone(probe(str(out_na)).get("audio"))

    def test_export_copy_preserves_hdr_tags_untouched(self):
        """The HDR-warning branch that every re-encoding preset trips (`export.py` docstring: "outputs SDR BT.709
        tags without tone mapping") must not apply to `copy` — it doesn't touch colour at all, so the source's own
        HDR tags must survive exactly, not get silently flattened to BT.709 like every other preset does."""
        out = OUT / "export_copy_hdr.mov"
        proc = script("export.py", self.hdr, "--preset", "copy", "-o", out)
        self.assertNotIn("BT.709", proc.stdout + proc.stderr, "copy re-encodes nothing, so it never issues the SDR-flattening warning")
        m = probe(str(out))
        self.assertTrue(m["video"]["hdr"], "the source's real HDR tags must survive a stream copy")
        self.assertNotEqual(m["video"]["color_space"], "bt709", "copy must never relabel HDR content as bt709")

    def test_proxy_default_width_and_crf_keeps_audio(self):
        out = OUT / "proxy_default.mp4"
        script("proxy.py", self.src, "-o", out)
        m = probe(str(out))
        self.assertEqual(m["video"]["width"], 640)
        self.assertEqual(m["video"]["codec"], "h264")
        self.assertIsNotNone(m.get("audio"), "default keeps audio when the source has it")
        self.assertClose(m["duration"], 12.0, 0.2)

    def test_proxy_scale_and_no_audio(self):
        out = OUT / "proxy_scale.mp4"
        script("proxy.py", self.src, "--scale", "0.25", "--no-audio", "-o", out)
        src_w = probe(str(self.src))["video"]["width"]
        m = probe(str(out))
        self.assertEqual(m["video"]["width"], src_w // 4)
        self.assertIsNone(m.get("audio"), "--no-audio must drop the track, not just mute it")

    def test_proxy_forces_fps(self):
        out = OUT / "proxy_fps.mp4"
        script("proxy.py", self.vfr, "--fps", "10", "-o", out)
        m = probe(str(out))
        self.assertFalse(m["video"]["variable_frame_rate_suspected"], "an explicit --fps must conform a VFR source to CFR")
        self.assertClose(m["video"]["fps"], 10.0, 0.5)

    def test_proxy_keeps_hdr_dynamic_range_like_every_other_reencode(self):
        """A proxy meant for machine consumption still shouldn't silently wash out HDR to a
        mislabelled BT.709 file — same posture as fit.py/caption.py: keep HDR as HEVC10, and
        let color.py --to-sdr be the tool that makes the SDR-vs-HDR call, not this one."""
        out = OUT / "proxy_hdr.mp4"
        script("proxy.py", self.hdr, "-o", out)
        m = probe(str(out))
        self.assertTrue(m["video"]["hdr"])
        self.assertEqual(m["video"]["codec"], "hevc")

    def test_proxy_rejects_bad_scale_and_width(self):
        script("proxy.py", self.src, "--scale", "1.5", expect_fail=True)
        script("proxy.py", self.src, "--scale", "0", expect_fail=True)
        script("proxy.py", self.src, "--width", "0", expect_fail=True)

    def test_proxy_dry_run_writes_nothing(self):
        out = OUT / "proxy_dry_run_absent.mp4"
        proc = script("proxy.py", self.src, "-o", out, "--dry-run", "--json")
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["dry_run"])
        self.assertFalse(out.exists())

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

    def test_color_audio_stream_selects_the_requested_track_not_always_the_first(self):
        two = OUT / "color_two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        out1 = OUT / "color_two_correct1.mp4"
        script("color.py", two, "--correct", "--exposure", "0.2", "--audio-stream", "1", "-o", out1, "--preset", "veryfast")
        self.assertIsNotNone(probe(str(out1))["audio"])
        proc = script("color.py", two, "--correct", "--audio-stream", "5", "-o", OUT / "color_nope.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("audio-stream", proc.stderr)

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

    def test_color_lut_strength_zero_means_no_lut_and_out_of_range_is_refused(self):
        """--lut-strength's blend branch only fired for the OPEN interval (0, 1); anything outside
        it -- including exactly 0, and any value > 1 or < 0 -- fell into the "apply at full
        strength" fallback with the number silently discarded. --lut-strength 0 is documented as
        "blend graded and original, 0..1" -- 0 should mean the original, unmodified picture, not a
        100%-strength grade (the opposite of what was asked). Verify 0 now leaves the picture
        untouched, and an out-of-range value is refused instead of silently applying full strength."""
        lut = OUT / "invert_strength.cube"
        lines = ["LUT_3D_SIZE 2"]
        for b in (0, 1):
            for g in (0, 1):
                for r in (0, 1):
                    lines.append(f"{1 - r} {1 - g} {1 - b}")
        lut.write_text("\n".join(lines) + "\n")
        zero = OUT / "lut_zero.mp4"
        script("color.py", self.src, "--lut", lut, "--lut-strength", "0", "--preset", "veryfast", "-o", zero)
        self.assertGreater(self._psnr(self.src, zero), 40, "--lut-strength 0 must leave the picture unchanged, not fully inverted")
        script("color.py", self.src, "--lut", lut, "--lut-strength", "2.5", "-o", OUT / "lut_oob.mp4", expect_fail=True)
        script("color.py", self.src, "--lut", lut, "--lut-strength", "-1", "-o", OUT / "lut_oob2.mp4", expect_fail=True)

    def test_color_correct_defaults_are_near_identity(self):
        out = OUT / "correct_neutral.mp4"
        data = json.loads(script("color.py", self.src, "--correct", "--preset", "veryfast", "-o", out, "--json").stdout)
        m = data["measurements"]
        self.assertIn("y_avg", m["input"])
        self.assertAlmostEqual(m["input"]["y_avg"], m["output"]["y_avg"], delta=2.0)
        self.assertAlmostEqual(m["input"]["saturation_avg"], m["output"]["saturation_avg"], delta=2.0)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (1280, 720))

    def test_color_correct_exposure_and_saturation_change_measured_levels(self):
        brighter = OUT / "correct_bright.mp4"
        data = json.loads(script("color.py", self.src, "--correct", "--exposure", "0.6", "--preset", "veryfast", "-o", brighter, "--json").stdout)
        m = data["measurements"]
        self.assertGreater(m["output"]["y_avg"], m["input"]["y_avg"], "positive exposure must raise measured luma")

        gray = OUT / "correct_gray.mp4"
        data2 = json.loads(script("color.py", self.src, "--correct", "--saturation", "0", "--preset", "veryfast", "-o", gray, "--json").stdout)
        m2 = data2["measurements"]
        self.assertLess(m2["output"]["saturation_avg"], m2["input"]["saturation_avg"], "saturation 0 must desaturate")
        self.assertLess(m2["output"]["saturation_avg"], 5.0, "saturation 0 must be close to grayscale")

    def test_color_correct_temperature_and_tint_run_and_preserve_geometry(self):
        out = OUT / "correct_wb.mp4"
        script("color.py", self.src, "--correct", "--temperature", "3200", "--tint", "-0.3", "--contrast", "1.1", "--preset", "veryfast", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (1280, 720))
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)

    def test_color_correct_rejects_out_of_safe_range_parameters(self):
        for flag, bad in (("--exposure", "5"), ("--contrast", "3"), ("--saturation", "-1"), ("--temperature", "40000"), ("--tint", "2")):
            out = OUT / "correct_reject.mp4"
            proc = script("color.py", self.src, "--correct", flag, bad, "-o", out, expect_fail=True)
            self.assertIn("outside", proc.stderr, f"{flag} {bad} should be refused as out of range")
            self.assertFalse(out.exists(), f"{flag} {bad}: no partial output on refusal")

    def test_color_correct_gamma_changes_measured_luma(self):
        brighter = OUT / "correct_gamma_up.mp4"
        data = json.loads(script("color.py", self.src, "--correct", "--gamma", "1.6", "--preset", "veryfast", "-o", brighter, "--json").stdout)
        m = data["measurements"]
        self.assertGreater(m["output"]["y_avg"], m["input"]["y_avg"], "gamma > 1 must raise measured luma")

        darker = OUT / "correct_gamma_down.mp4"
        data2 = json.loads(script("color.py", self.src, "--correct", "--gamma", "0.5", "--preset", "veryfast", "-o", darker, "--json").stdout)
        m2 = data2["measurements"]
        self.assertLess(m2["output"]["y_avg"], m2["input"]["y_avg"], "gamma < 1 must lower measured luma")

    def test_color_correct_lift_and_gain_run_and_shift_measured_levels(self):
        lifted = OUT / "correct_lift.mp4"
        data = json.loads(script("color.py", self.src, "--correct", "--lift", "0.3", "--preset", "veryfast", "-o", lifted, "--json").stdout)
        m = data["measurements"]
        self.assertGreater(m["output"]["y_min"], m["input"]["y_min"], "positive lift must raise the shadow floor")

        gained = OUT / "correct_gain.mp4"
        data2 = json.loads(script("color.py", self.src, "--correct", "--gain", "-0.3", "--preset", "veryfast", "-o", gained, "--json").stdout)
        m2 = data2["measurements"]
        self.assertLess(m2["output"]["y_avg"], m2["input"]["y_avg"], "negative gain must dim the highlights and lower measured luma")
        v = probe(str(gained))["video"]
        self.assertEqual((v["width"], v["height"]), (1280, 720))

    def test_color_correct_levels_narrows_measured_dynamic_range(self):
        out = OUT / "correct_levels_out.mp4"
        data = json.loads(script("color.py", self.src, "--correct", "--levels-out-black", "64", "--levels-out-white", "192",
                                  "--preset", "veryfast", "-o", out, "--json").stdout)
        m = data["measurements"]
        # colorlevels' output remap is an affine map into [romin, romax]: no output pixel can fall
        # outside it (mod encoder rounding), so this is a mathematical guarantee, not a content guess.
        self.assertGreaterEqual(m["output"]["y_min"], 64 - 3, "--levels-out-black 64 must floor the output near 64")
        self.assertLessEqual(m["output"]["y_max"], 192 + 3, "--levels-out-white 192 must ceiling the output near 192")
        self.assertLess(m["output"]["y_max"] - m["output"]["y_min"], m["input"]["y_max"] - m["input"]["y_min"],
                         "narrowing the output levels must narrow the measured dynamic range")

        out2 = OUT / "correct_levels_in.mp4"
        script("color.py", self.src, "--correct", "--levels-in-black", "16", "--levels-in-white", "235", "--preset", "veryfast", "-o", out2)
        v = probe(str(out2))["video"]
        self.assertEqual((v["width"], v["height"]), (1280, 720))
        self.assertClose(probe(str(out2))["duration"], 12.0, 0.2)

        # an all-default --levels-* call must not add a colorlevels term to the chain
        neutral_chain = script("color.py", self.src, "--correct", "--dry-run").stderr
        self.assertNotIn("colorlevels", neutral_chain)

    def test_color_correct_curves_preset_runs_and_preserves_geometry(self):
        out = OUT / "correct_curves.mp4"
        script("color.py", self.src, "--correct", "--curves", "medium_contrast", "--preset", "veryfast", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (1280, 720))
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)
        # omitting --curves must not add a curves term to the chain
        neutral_chain = script("color.py", self.src, "--correct", "--dry-run").stderr
        self.assertNotIn("curves=", neutral_chain)
        proc = script("color.py", self.src, "--correct", "--curves", "not-a-real-preset", "-o", OUT / "correct_curves_bad.mp4", expect_fail=True)
        self.assertIn("invalid choice", proc.stderr)

    def test_color_correct_rejects_new_flags_out_of_range(self):
        for flag, bad in (("--gamma", "0.05"), ("--gamma", "11"), ("--lift", "-1.5"), ("--gain", "1.5")):
            out = OUT / "correct_reject_new.mp4"
            proc = script("color.py", self.src, "--correct", flag, bad, "-o", out, expect_fail=True)
            self.assertIn("outside", proc.stderr, f"{flag} {bad} should be refused as out of range")
            self.assertFalse(out.exists(), f"{flag} {bad}: no partial output on refusal")

        out = OUT / "correct_reject_levels_in.mp4"
        proc = script("color.py", self.src, "--correct", "--levels-in-black", "200", "--levels-in-white", "100", "-o", out, expect_fail=True)
        self.assertIn("must be less than", proc.stderr)
        self.assertFalse(out.exists())

        out2 = OUT / "correct_reject_levels_out.mp4"
        proc2 = script("color.py", self.src, "--correct", "--levels-out-black", "200", "--levels-out-white", "100", "-o", out2, expect_fail=True)
        self.assertIn("must be less than", proc2.stderr)
        self.assertFalse(out2.exists())

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
        proc = script("audio.py", self.src, "--music", self.long_ref, "--duck", "--music-fade-out", "2", "-o", out2)
        self.assertIn("sidechaincompress", proc.stderr)
        self.assertEqual(proc.stderr.count("afade=t=out"), 1, "only the bed fades, not the whole mix")
        proc_mix = script("audio.py", self.src, "--fade-out", "1", "--dry-run")
        self.assertEqual(proc_mix.stderr.count("afade=t=out"), 1)
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

    def test_shell_quote_quotes_backslashes(self):
        """CodeRabbit (#101): fixing the invalid-escape-sequence SyntaxWarning in shell_quote()'s
        character set (a stray `\\` before an already-unescaped `;`) accidentally dropped a real,
        load-bearing backslash from the quoting trigger set -- the original `\\;` literal, due to
        Python keeping an unrecognised escape's backslash, actually matched on `\\` OR `;`, not just
        `;`. Without a backslash trigger, a Windows path like `C:\\media\\clip.mp4` would render
        unquoted in --dry-run/--json command output. Assert the fixed version still quotes it."""
        self.assertEqual(shell_quote("C:\\media\\clip.mp4"), "'C:\\media\\clip.mp4'")
        self.assertEqual(shell_quote("plain.mp4"), "plain.mp4")
        self.assertEqual(shell_quote("has;semicolon"), "'has;semicolon'")

    def test_look_scenes_overlay_graphics_prefer_fontfile_over_font_when_resolvable(self):
        """#100: drawtext's own fontconfig resolution (font=<name>) crashed with an access violation
        on some real Windows ffmpeg builds, with or without a valid fonts.conf; fontfile=<path> is
        the only form confirmed not to crash, since it never touches fontconfig at all. Every
        drawtext-using tool now resolves a concrete font file (default_font_file() in _common.py)
        and prefers fontfile= whenever one can be found, falling back to font= only when nothing
        resolves. This sandbox has fc-match + DejaVu Sans, so a file is always resolvable here --
        skip rather than false-fail on a machine where it genuinely cannot be (no fc-match, no
        fonts installed), since font= is still the documented, correct fallback there."""
        if not default_font_file("DejaVu Sans"):
            self.skipTest("no resolvable default font on this machine (no fc-match / no fonts) -- font= fallback is correct here")

        out = OUT / "fontfile_look.png"
        proc = script("look.py", self.src, "--at", "1", "-o", out, "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(any("fontfile=" in c for c in data["commands"]), data["commands"])

        scenes_sheet = OUT / "fontfile_scenes.png"
        proc = subprocess.run([sys.executable, str(SCRIPTS / "scenes.py"), str(self.src), "--sheet", str(scenes_sheet), "--json"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fontfile=", proc.stderr, "scenes.py --sheet should log a drawtext with fontfile=")

        out2 = OUT / "fontfile_overlay.mp4"
        proc = script("overlay.py", self.src, "--text", "hi", "-o", out2, "--json")
        data2 = json.loads(proc.stdout)
        self.assertTrue(any("fontfile=" in c for c in data2["commands"]), data2["commands"])

        out3 = OUT / "fontfile_gfx.mp4"
        proc = script("graphics.py", self.src, "--template", "title", "--title", "hi", "-o", out3, "--json")
        data3 = json.loads(proc.stdout)
        self.assertTrue(any("fontfile=" in c for c in data3["commands"]), data3["commands"])

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

    def test_silence_on_wav_input_keeps_pcm_not_forced_aac(self):
        """silence.py's final ffmpeg command used to unconditionally append aac_args() (-c:a aac)
        regardless of the output container. That's fine for .mp4/.m4a, but AAC cannot be muxed
        into a .wav file -- so silence removal on any audio-only WAV input (a very ordinary case:
        podcasts, voice memos, any --list workflow feeding straight into a WAV pipeline) crashed
        ffmpeg outright, whether or not -o was given explicitly. Verify a WAV input still produces
        a valid, playable WAV output (PCM), not a codec/container mismatch crash."""
        wav_in = OUT / "silence_wav_in.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
           "-t", "6", wav_in)
        proc = script("silence.py", wav_in)
        out = Path(proc.stdout.strip())
        self.assertEqual(out.suffix, ".wav")
        m = probe(str(out))
        self.assertTrue(m["audio"]["codec"].startswith("pcm"), f"WAV output must stay PCM, got {m['audio']['codec']}")

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

    def test_join_two_or_more_audio_less_clips(self):
        """Every no-audio clip gets a synthetic silent audio track added as an extra ffmpeg input (join.py
        builds this itself, not this test's fixtures) -- `idx` must be this ffmpeg input's actual position
        (n + how many synthetic inputs were already added), not `n + len(extra_inputs)` (the six argv tokens
        each synthetic input contributes, not a count of inputs). With exactly one no-audio clip both counts
        happen to agree; a real multi-camera join where every clip lacked audio is what caught the divergence
        starting from the second one -- ffmpeg refused with "Invalid file index" naming an input far past the
        real count, since the miscomputed index grew by 6 (not 1) per extra no-audio clip."""
        silent_a = OUT / "silent_a.mp4"
        silent_b = OUT / "silent_b.mp4"
        silent_c = OUT / "silent_c.mp4"
        for out, size in ((silent_a, "640x360"), (silent_b, "480x270"), (silent_c, "960x540")):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25", "-t", "3", "-c:v", "libx264", "-preset", "veryfast", out)
        out = OUT / "joined_all_silent.mp4"
        script("join.py", silent_a, silent_b, silent_c, "--transition", "none", "--preset", "veryfast", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 9.0, 0.3)
        self.assertEqual(m["audio"]["channels"], 2, "every clip's missing track became silent stereo, not a dropped audio stream")
        # mixed: audio-bearing clip first, then two without -- exercises the same off-by-more-than-one index
        # for the second and third synthetic input regardless of which position the real audio clip sits in
        out2 = OUT / "joined_mixed_silent.mp4"
        script("join.py", self.src, silent_a, silent_b, "--transition", "none", "--preset", "veryfast", "-o", out2)
        self.assertClose(probe(str(out2))["duration"], 12 + 3 + 3, 0.3)

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

    # ---------------------------------------------------------------- v0.4: verify / multicam / HLG / Log / energy karaoke / progress
    def test_probe_hlg_and_log_detection(self):
        hlg = OUT / "hlg.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "3",
           "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1", hlg)
        v = probe(str(hlg))["video"]
        self.assertEqual(v["hdr_format"], "HLG")
        self.assertIsNone(v["dolby_vision"])
        out = OUT / "hlg_sdr.mp4"
        script("color.py", hlg, "--to-sdr", "--fast", "-o", out)
        self.assertEqual(probe(str(out))["video"]["color_transfer"], "bt709")
        nodv = OUT / "hlg_nodv.mp4"
        proc = script("color.py", hlg, "--strip-dovi", "-o", nodv)
        self.assertIn("filter_units", proc.stderr)
        self.assertEqual(probe(str(nodv))["video"]["hdr_format"], "HLG")
        flat = OUT / "loglike.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "3",
           "-vf", "curves=all='0/0.36 1/0.88',hue=s=0.4,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", flat)
        data = json.loads(script("probe.py", flat, "--analyze").stdout)
        self.assertTrue(data["levels"]["looks_like_log"])
        data = json.loads(script("probe.py", self.src, "--analyze").stdout)
        self.assertFalse(data["levels"]["looks_like_log"])
        compact = script("probe.py", flat, "--analyze", "--compact").stdout
        self.assertIn("[Log?]", compact)

    def test_karaoke_energy_timing_follows_audio(self):
        gappy = OUT / "gappy_k.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*lt(t\\,2)':s=48000",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "4", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", gappy)
        cues = OUT / "kcues.txt"
        cues.write_text("0:00-0:04 one two three four\n", encoding="utf-8")
        ass = OUT / "ke.ass"
        script("caption.py", gappy, "--text", cues, "--karaoke", "--write-ass", ass, "--fast", "-o", OUT / "ke.mp4")
        line = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue")][0]
        durs = [int(x) for x in re.findall(r"\\kf(\d+)", line)]
        self.assertEqual(len(durs), 4)
        self.assertEqual(sum(durs), 400)
        self.assertLess(sum(durs[:3]), 200, "first three words should sit inside the 2 s of sound")
        ass2 = OUT / "ke_even.ass"
        script("caption.py", gappy, "--text", cues, "--karaoke", "--karaoke-timing", "even", "--write-ass", ass2, "--fast", "-o", OUT / "ke2.mp4")
        line2 = [l for l in ass2.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue")][0]
        self.assertEqual([int(x) for x in re.findall(r"\\kf(\d+)", line2)], [100, 100, 100, 100])

    def test_multicam_offsets_and_switch(self):
        camB = OUT / "camB.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", self.src, "-vf", "hue=h=90", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", camB)
        data = json.loads(script("multicam.py", self.src, camB, self.mic, "--offsets-only", "--json").stdout)
        self.assertClose(data["offsets_seconds"][1], 1.5, 0.05)
        self.assertClose(data["offsets_seconds"][2], 2.5, 0.05)
        out = OUT / "mc.mp4"
        data = json.loads(script("multicam.py", self.src, camB, self.mic, "--audio", "2", "--switch", "0-3:0,3-6:1,6-9:0", "--fast", "-o", out, "--json").stdout)
        self.assertEqual(len(data["cuts"]), 4, "three named ranges plus the gap-fill to the end")
        m = probe(str(out))
        self.assertClose(m["duration"], 12.0, 0.2)
        self.assertEqual(m["audio"]["channels"], 2)
        # camB is hue-shifted: a frame at 4.5 s (camera 1) must differ from one at 2 s (camera 0)
        script("look.py", out, "--at", "2", "--at", "4.5", "-o", OUT / "mcf")
        self.assertNotEqual((OUT / "mcf_2.000s.png").read_bytes()[100:2000], (OUT / "mcf_4.500s.png").read_bytes()[100:2000])
        auto = OUT / "mc_auto.mp4"
        script("multicam.py", self.src, camB, "--auto", "4", "--fast", "-o", auto)
        self.assertClose(probe(str(auto))["duration"], 12.0, 0.2)
        script("multicam.py", self.src, camB, "--switch", "0-3:5", expect_fail=True)

    def test_multicam_fix_drift_trims_before_resample_not_after(self):
        """--fix-drift's audio path computes a_start (an atrim start point) in the source's own
        pre-correction time axis, but the filter chain used to apply asetrate/aresample (the drift
        correction) *before* atrim -- so the trim landed on the already-rescaled timeline instead
        of the raw one it was computed for, same bug class as sync.py already avoids by seeking
        with -ss (an input-level, pre-filter operation) before its own drift_af. Build a camera
        whose audio started before the reference (offsets[a] < 0, so a_start > 0) and also drifts
        (ratios[a] != 1), then check the constructed [<audio input>:a] filter chain: atrim=start=
        must appear before asetrate, mirroring sync.py's ordering."""
        base = OUT / "mc_drift_base.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "200", "-c:a", "pcm_s16le", base)
        ref_audio = OUT / "mc_drift_ref.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.2", "-i", base, "-c:a", "pcm_s16le", ref_audio)
        camB = OUT / "mc_drift_camB.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-af", "asetrate=48000*0.9995,aresample=48000", "-c:a", "pcm_s16le", camB)
        cam0 = OUT / "mc_drift_cam0.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-i", ref_audio, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", cam0)

        data = json.loads(script("multicam.py", cam0, camB, "--audio", "1", "--switch", "0-198:0", "--fix-drift", "--max-offset", "5", "--fast", "-o", OUT / "mc_drift_out.mp4", "--json").stdout)
        self.assertLess(data["offsets_seconds"][1], 0, "camera 1 must have started before the reference for a_start > 0 to be exercised")
        self.assertNotEqual(data["drift_ppm"][1], 0.0, "drift must actually be detected for asetrate/aresample to be in the chain")
        audio_chain = data["commands"][0].split("[1:a]", 1)[1]
        self.assertLess(audio_chain.index("atrim=start="), audio_chain.index("asetrate="),
                         "atrim=start= (in the pre-correction time axis) must run before asetrate/aresample rescale that axis")

    def test_multicam_negative_auto_interval_refused_not_infinite_loop(self):
        """--auto builds cuts with `while t < ref_dur: ... t += args.auto` -- `elif args.auto:` is
        only false for exactly 0, so a negative value used to pass that check and enter the loop
        with t decreasing every iteration, meaning t < ref_dur never becomes false: the process
        hangs forever instead of erroring on invalid input. Must be refused up front instead."""
        script("multicam.py", self.src, self.src, "--auto", "-1", "--fast", "-o", OUT / "mc_auto_neg.mp4", expect_fail=True)

    def test_multicam_warns_on_a_camera_with_no_shared_audio_event(self):
        """A camera whose audio has nothing in common with the reference must not align silently."""
        unrelated = OUT / "camC_unrelated.mp4"
        # a flat-envelope tone: nothing for the envelope-based cross-correlation to lock onto,
        # unlike the reference's gated tones -- unrelated in the way a different room's constant hum would be
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=233:sample_rate=48000", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", unrelated)
        proc = script("multicam.py", self.src, unrelated, "--offsets-only", "--json")
        data = json.loads(proc.stdout)
        self.assertLess(data["confidence"][1], 0.1)
        self.assertIn("low correlation confidence", proc.stderr)

    def test_verify_kit_runs_on_real_world_fixtures(self):
        folder = OUT / "vfx"
        folder.mkdir(exist_ok=True)
        for f in (self.hdr, self.surround, self.vfr):
            (folder / Path(f).name).write_bytes(Path(f).read_bytes())
        report = OUT / "verify.md"
        data = json.loads(script("verify.py", folder, "--quick", "--report", report, "--json").stdout)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(len(data["files"]), 3)
        text = report.read_text()
        self.assertIn("| PASS |", text)
        self.assertNotIn("| FAIL |", text)
        self.assertIn("HDR10/PQ", text)
        script("verify.py", OUT / "does_not_exist", expect_fail=True)

    def test_verify_disambiguates_same_named_files_from_different_folders(self):
        """Every file's outputs share one flat --out directory keyed only on stem = outdir /
        f.stem -- two files with the same basename from different subfolders (entirely normal for
        real footage pulled from multiple cameras/SD cards, e.g. two "clip.mp4"s in separate
        campaign folders) used to resolve to the identical output prefix. Each file's own steps
        ran correctly in isolation, but with --keep the second file's outputs silently overwrote
        the first file's on disk, with the report still showing PASS for both and no collision
        ever flagged (same bug class fixed in batch.py). Verify same-named files from different
        folders now get distinct, non-colliding output prefixes."""
        folder = OUT / "verify_collision"
        (folder / "campaignA").mkdir(parents=True, exist_ok=True)
        (folder / "campaignB").mkdir(parents=True, exist_ok=True)
        (folder / "campaignA" / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        (folder / "campaignB" / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        out = OUT / "verify_collision_out"
        data = json.loads(script("verify.py", folder, "--quick", "--keep", "--out", out, "--json").stdout)
        self.assertEqual(len(data["files"]), 2)
        self.assertTrue(all(s["ok"] for f in data["files"] for s in f["steps"]))
        cut_files = sorted(p.name for p in out.glob("clip*_cut.mp4"))
        self.assertEqual(len(cut_files), 2, f"expected two distinct 'cut' outputs, one per same-named source file, got {cut_files}")
        cap_files = sorted(p.name for p in out.glob("clip*_cap.mp4"))
        self.assertEqual(len(cap_files), 2, f"expected two distinct 'caption' outputs, got {cap_files}")

    def test_progress_and_fast_flags(self):
        out = OUT / "prog.mp4"
        proc = script("fit.py", self.src, "--duration", "6", "--fast", "--progress", "-o", out)
        self.assertIn("%", proc.stderr)
        self.assertIn("-preset veryfast", proc.stderr, "--fast overrides the preset")
        self.assertClose(probe(str(out))["duration"], 6.0, 0.2)

    # ---------------------------------------------------------------- colour-flag filter-graph injection (adversarial)
    def test_color_like_flags_refuse_filter_graph_injection(self):
        """Every flag that string-formats a colour straight into a filter graph (color=c=...,
        tpad=...:color=..., rotate=...:fillcolor=..., drawtext=...:fontcolor=..., pad=...:color=...)
        used to accept any string verbatim. Since ffmpeg filter options are comma/colon-delimited,
        a value like "black,drawtext=text=INJECTED" doesn't just set an odd colour -- the comma ends
        the colour filter early and starts an entirely new one, so the payload actually gets burnt
        into the frame (confirmed by rendering it and inspecting the pixels before this fix existed).
        This is a real filter-graph injection, not just a cosmetic validation gap -- every colour-like
        flag across the codebase must refuse anything that isn't a plain colour token."""
        payload = "black,drawtext=text=INJECTED"
        cases = [
            ("pad.py", [self.src, "--start", "1", "--color", payload]),
            ("straighten.py", [self.src, "--degrees", "5", "--fit", "pad", "--fill-color", payload]),
            ("waveform.py", [self.src, "--background", payload]),
            ("waveform.py", [self.src, "--color", payload]),
            ("background.py", ["--duration", "1", "--width", "640", "--height", "360", "--color", payload, "-o", OUT / "bg_inject.mp4"]),
            ("background.py", ["--duration", "1", "--width", "640", "--height", "360", "--gradient", f"{payload}:0x0057ff", "-o", OUT / "bg_inject2.mp4"]),
            ("fit.py", [self.src, "--aspect", "1:1", "--fit", "pad", "--pad-color", payload]),
            ("export.py", [self.src, "--preset", "reels", "--pad-color", payload]),
            ("join.py", [self.src, self.src, "--pad-color", payload]),
            ("overlay.py", [self.src, "--text", "hi", "--font-color", payload]),
            ("overlay.py", [self.src, "--text", "hi", "--border-color", payload]),
            ("overlay.py", [self.src, "--text", "hi", "--box-color", payload]),
            ("overlay.py", [self.src, "--video", self.src, "--chromakey", payload]),
        ]
        for name, argv in cases:
            proc = script(name, *argv, expect_fail=True)
            self.assertIn("colour", proc.stderr, f"{name} {argv}: expected a colour-validation refusal")

    def test_color_like_flags_still_accept_real_colors(self):
        script("pad.py", self.src, "--start", "0.5", "--color", "0x101010", "-o", OUT / "colorok1.mp4")
        script("straighten.py", self.src, "--degrees", "5", "--fit", "pad", "--fill-color", "black", "-o", OUT / "colorok2.mp4")
        script("waveform.py", self.src, "--background", "0x101010", "--color", "cyan|magenta", "-o", OUT / "colorok3.mp4")
        script("background.py", "--duration", "1", "--width", "640", "--height", "360", "--gradient", "0xff6a00:0x0057ff", "-o", OUT / "colorok4.mp4")
        script("overlay.py", self.src, "--text", "hi", "--box-color", "black@0.5", "-o", OUT / "colorok5.mp4")

    # ---------------------------------------------------------------- font-name filter-graph injection (adversarial)
    @unittest.skipIf(platform.system() == "Windows", "forces the fc-match-missing fallback path by symlinking just "
                      "ffmpeg/ffprobe into a stub PATH dir -- os.symlink needs an elevated/dev-mode privilege on "
                      "Windows that CI runners don't grant, and default_font_file() doesn't even consult fc-match "
                      "there (it resolves a fixed arial.ttf under WINDIR, see its docstring), so this specific "
                      "repro doesn't generalise to Windows. The fix itself (escape_drawtext() around the fallback "
                      "value) is plain string handling with no OS branch, so it's equally in effect there.")
    def test_font_flag_escapes_filter_graph_injection_when_unresolved(self):
        """overlay.py and graphics.py both accept --font as a family NAME, not a file path, and try
        to resolve it to a concrete file via default_font_file() (fc-match) first -- but that
        resolution returns None whenever fc-match isn't on PATH (always true on some real systems,
        e.g. minimal containers and every Windows build), in which case both tools used to fall back
        to embedding the raw name straight into `font='{args.font}'` with zero escaping. Since
        drawtext=... options are comma/colon-delimited, a value like "X',drawtext=text=OWNED"
        doesn't just set an odd font -- the comma ends the font option (and the whole drawtext
        filter) early and starts an entirely new drawtext filter, which actually rendered (confirmed
        by rendering the pre-fix code and visually inspecting the burnt-in "OWNED" text). Force the
        None-fallback path by hiding fc-match from PATH, exactly as it's naturally absent on some
        real systems, and confirm the built filter graph no longer contains a live breakout."""
        payload = "X',drawtext=text=OWNED:fontcolor=yellow:fontsize=40:x=10:y=10"
        stub_dir = OUT / "no_fc_match_path"
        stub_dir.mkdir(exist_ok=True)
        for exe in ("ffmpeg", "ffprobe"):
            real = shutil.which(exe)
            link = stub_dir / exe
            if not link.exists():
                os.symlink(real, link)
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(stub_dir), str(Path(sys.executable).parent)])

        out = OUT / "font_inject_overlay.mp4"
        proc = sh(sys.executable, SCRIPTS / "overlay.py", self.src, "--text", "hello", "--font", payload, "-o", out, env=env)
        # The escaped payload must show up with a backslash-escaped comma ahead of the injected
        # "drawtext=text=OWNED" -- proof it stays a literal char inside font='...' instead of
        # closing the option early and starting a sibling filter.
        self.assertIn("\\,drawtext=text=OWNED", proc.stderr, "comma must be escaped so it can't break out of font= into a new filter")

        frame = OUT / "font_inject_overlay_frame.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", out, "-ss", "1", "-vframes", "1", frame)
        self.assertTrue(frame.exists())

    def test_caption_font_with_comma_and_colon_does_not_corrupt_ass_style(self):
        """caption.py's --font flows into two ASS constructs escape_drawtext() was never meant to
        cover: the comma-delimited [V4+ Styles] Style: line (write_ass()), and the comma-separated
        Key=Value list inside a -vf subtitles=...:force_style='...' option. Neither is a drawtext
        filter, so unlike overlay.py/graphics.py this call site used to embed args.font completely
        raw. A font name containing a comma shifts every field after it (size, colours, bold flag,
        alignment, margins) in the Style: line, and a comma or colon inside force_style's FontName=
        breaks the option-list/-vf parsing the same way. Verify a hostile font name survives as an
        inert, field-count-preserving value in both the --write-ass path and the plain SRT-burn
        (force_style) path."""
        hostile_font = "Arial,Bold:evil"
        ass_out = OUT / "font_inject.ass"
        script("caption.py", self.src, "--text", self.cues, "--font", hostile_font, "--animate", "fade", "--write-ass", ass_out, "--dry-run")
        style_line = next(l for l in ass_out.read_text(encoding="utf-8").splitlines() if l.startswith("Style: Default,"))
        self.assertNotIn(",Arial,Bold:evil,", style_line, "raw hostile font must not appear -- it would shift every later field")
        fields = style_line.split(",")
        self.assertEqual(len(fields), 23, "Style: line must keep its full field count (Format: line lists 23 columns)")

        out = OUT / "font_inject_caption.mp4"
        proc = sh(sys.executable, SCRIPTS / "caption.py", self.src, "--text", self.cues, "--font", hostile_font, "-o", out, "--dry-run")
        self.assertNotIn("Arial,Bold:evil", proc.stderr, "hostile font must not reach force_style unsanitised")

    def test_caption_ass_dialogue_text_cannot_forge_override_blocks(self):
        """ASS Dialogue text treats a literal `{...}` as an override block -- real style/animation
        commands (\\pos, \\fscx, \\t, ...), not literal characters. Cue text is effectively user-
        controlled (--text cues, an SRT file, or ASR transcription), so cue content containing
        braces used to be interpreted as those commands instead of being read out literally,
        letting a caption reposition/rescale/recolor itself or later text. Verify a hostile cue
        survives as inert text with the override syntax neutralised."""
        hostile_cues = OUT / "brace_inject_cues.txt"
        hostile_cues.write_text("00:00:00 --> 00:00:03 hi {\\pos(0,0)\\fscx500}INJECTED\n", encoding="utf-8")
        ass_out = OUT / "brace_inject.ass"
        script("caption.py", self.src, "--text", hostile_cues, "--animate", "fade", "--write-ass", ass_out, "--dry-run")
        dialogue = next(l for l in ass_out.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue: "))
        # --animate fade legitimately prepends its own "{\fad(200,200)}" override block; only the
        # cue-text-derived braces from the hostile payload must be gone.
        self.assertNotIn("{\\pos(0,0)\\fscx500}", dialogue, "cue text must not be able to open a real ASS override block")
        self.assertIn("\\pos(0,0)\\fscx500INJECTED", dialogue, "the rest of the cue text still renders, just as literal (now brace-free) text")

    def test_caption_srt_blank_line_in_cue_text_does_not_split_the_block(self):
        """parse_text_cues() turns a bare '|' into a newline (a documented way to write a two-line
        caption), so a source line with two adjacent pipes ("a||b") produces cue text containing a
        blank line ("a\\n\\nb"). A blank line is SRT's own block separator (index / timecode / text
        / blank / next block) -- writing it raw used to split one cue into two malformed half-
        blocks, the second missing its own index and timecode. Verify the generated SRT still
        parses back as exactly the cues that were written, not more."""
        hostile_cues = OUT / "blank_line_cues.txt"
        hostile_cues.write_text("00:00:00 --> 00:00:03 a||b\n00:00:03 --> 00:00:06 second cue\n", encoding="utf-8")
        srt_out = OUT / "blank_line.srt"
        script("caption.py", "--text", hostile_cues, "--write-srt", srt_out)
        from caption import parse_srt
        cues = parse_srt(str(srt_out))
        self.assertEqual(len(cues), 2, "the blank line inside cue text must not fake a third block boundary")
        self.assertEqual(cues[0][2], "a\nb", "text after the fake blank-line boundary must not be silently dropped")
        self.assertEqual(cues[1][2], "second cue", "the second cue must still have its own timecode/index, not be swallowed as stray text")

    def test_caption_malformed_timestamp_falls_back_to_just_the_text_not_the_whole_line(self):
        """TIME_RE can match a line (finding a text portion after the arrow) even when one of the
        two timestamps inside it fails parse_time() (e.g. a malformed "00:00:03.15.999" with a
        stray extra segment). The except ValueError fallback used `line.strip()` -- the entire raw
        line, broken timestamp included -- instead of the already-captured `m.group("text")`, so
        the malformed timestamp string itself got burned into the caption as visible text."""
        cues = OUT / "malformed_timestamp_cues.txt"
        cues.write_text("00:00:00.15.999 --> 00:00:02 Hello there\n", encoding="utf-8")
        srt_out = OUT / "malformed_timestamp.srt"
        script("caption.py", "--text", cues, "--write-srt", srt_out)
        from caption import parse_srt
        parsed = parse_srt(str(srt_out))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0][2], "Hello there", "the broken timestamp text must not leak into the caption")

    def test_drawtext_semicolon_and_quote_render_as_inert_literal_text(self):
        """escape_drawtext() (shared by overlay.py --text, graphics.py/overlay.py's --font
        fallback, and grid.py's filename-derived labels) had two more gaps beyond the comma/colon/
        bracket class fixed in 0.15.2/0.15.3: (1) an unescaped ';' -- ffmpeg's graph parser splits
        a filterchain there exactly like an unescaped ',' does, confirmed with the minimal repro
        `--text "a'b;c"` crashing real ffmpeg with "No such filter: 'c...'" on the unpatched code;
        (2) the quote character itself has no backslash escape that survives every call shape --
        both `\\'` and the POSIX `'\\''` close-insert-reopen trick corrupt a -filter_complex chain
        that uses explicit [label] pads (confirmed by rendering: trailing option text like
        "fontfile=...:fontsize=..." leaks into the picture as literal burnt-in text instead of
        being parsed as options), even though the same escape works fine in a simple -vf chain.
        Render a text containing both a quote and a semicolon and confirm it appears verbatim
        (minus the dropped quote) with nothing named after it leaking into the frame."""
        out = OUT / "semicolon_quote.mp4"
        proc = script("overlay.py", self.src, "--text", "a'b;c", "-o", out)
        # The quote is dropped (a'b -> ab) and the semicolon escaped, then the value must close
        # cleanly right where the template's own quote closes it -- ":fontsize=" must follow
        # immediately, not somewhere downstream after leaked option text.
        self.assertIn("ab\\;c'\\'':fontsize", proc.stderr, "value must render as 'ab;c' and close cleanly into :fontsize=, no leakage")
        frame = OUT / "semicolon_quote_frame.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", out, "-vframes", "1", frame)
        self.assertTrue(frame.exists())

    # ---------------------------------------------------------------- real iPhone regressions (Dolby Vision 8.4 / HLG, VFR, extra tracks)
    def test_hdr_source_stays_hdr_through_reencodes(self):
        # HLG 10-bit HEVC with audio AND a timecode data track, like an iPhone .mov
        hlg = OUT / "hlg_tc.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "5", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1",
           "-c:a", "aac", "-timecode", "01:00:00:00", hlg)
        streams = json.loads(sh("ffprobe", "-v", "error", "-print_format", "json", "-show_streams", hlg).stdout)["streams"]
        self.assertEqual(len(streams), 3, "video + audio + tmcd data track")
        for name, argv in [
            ("cut.py", [hlg, "--start", "1", "--end", "3", "--accurate"]),
            ("fit.py", [hlg, "--aspect", "1:1", "--width", "480"]),
            ("caption.py", [hlg, "--text", self.cues]),
            ("overlay.py", [hlg, "--text", "hdr"]),
            ("silence.py", [hlg]),
            ("join.py", [hlg, hlg, "--transition", "none"]),
        ]:
            out = OUT / f"hdrkeep_{name}.mp4"
            script(name, *argv, "--fast", "-o", out)
            v = probe(str(out))["video"]
            self.assertTrue(v["hdr"], name)
            self.assertEqual((v["codec"], v["pix_fmt"], v["color_transfer"]), ("hevc", "yuv420p10le", "arib-std-b67"), name)
        # tone-mapping and the display path still work on the multi-track file
        sdr = OUT / "hlg_tc_sdr.mp4"
        script("color.py", hlg, "--to-sdr", "--fast", "-o", sdr)
        self.assertFalse(probe(str(sdr))["video"]["hdr"])
        proc = script("look.py", hlg, "--at", "1", "-o", OUT / "hlgframe")
        self.assertIn("tone-mapped", proc.stderr)
        self.assertTrue((OUT / "hlgframe_1.000s.png").exists())
        # 10-bit levels are reported on an 8-bit scale, so a normal HDR clip is not called Log
        data = json.loads(script("probe.py", hlg, "--analyze").stdout)
        self.assertLessEqual(data["levels"]["y_max"], 255)
        self.assertFalse(data["levels"]["looks_like_log"])

    # ---------------------------------------------------------------- v0.5: check / scenes / render
    def test_check_compliance(self):
        reels = OUT / "export_reels.mp4"
        if not reels.exists():
            script("export.py", self.src, "--preset", "reels", "--fit", "crop", "-o", reels)
        data = json.loads(script("check.py", reels, "--platform", "reels", "--json", expect_fail=True).stdout)
        names = {r["check"]: r["status"] for r in data["checks"]}
        kinds = {r["check"]: r["kind"] for r in data["checks"]}
        self.assertEqual(kinds["loudness"], "judgement")
        self.assertEqual(kinds["video codec"], "format")
        self.assertIn("ambience", [r["fix"] for r in data["checks"] if r["check"] == "loudness"][0])
        self.assertEqual(names["aspect"], "PASS")
        self.assertEqual(names["pixel format"], "PASS")
        self.assertEqual(names["loudness"], "FAIL", "unnormalised test tone is far from -14 LUFS")
        self.assertFalse(data["ok"])
        # FAILs a non-technical caller would ask "so what?" about carry a plain-language reason,
        # distinct from `fix` (the command); PASS rows never carry one
        loudness_row = [r for r in data["checks"] if r["check"] == "loudness"][0]
        self.assertTrue(loudness_row["reason"])
        self.assertNotEqual(loudness_row["reason"], loudness_row["fix"])
        pass_rows = [r for r in data["checks"] if r["status"] == "PASS"]
        self.assertTrue(pass_rows)
        self.assertTrue(all(r["reason"] == "" for r in pass_rows))
        # after loudness.py the same file passes
        norm = OUT / "reels_norm.mp4"
        script("loudness.py", reels, "-o", norm)
        data = json.loads(script("check.py", norm, "--platform", "reels", "--json").stdout)
        self.assertTrue(data["ok"], [r for r in data["checks"] if r["status"] != "PASS"])
        # HDR on an SDR-only platform fails the colour check
        data = json.loads(script("check.py", self.hdr, "--platform", "x", "--no-loudness", "--json", expect_fail=True).stdout)
        colour_row = [r for r in data["checks"] if r["check"] == "colour"][0]
        self.assertEqual(colour_row["status"], "FAIL")
        self.assertTrue(colour_row["reason"])
        # custom overrides
        data = json.loads(script("check.py", self.src, "--platform", "custom", "--max-duration", "5", "--no-loudness", "--json", expect_fail=True).stdout)
        self.assertEqual({r["check"]: r["status"] for r in data["checks"]}["duration"], "FAIL")

    def test_check_unmeasurable_loudness_warns_instead_of_silently_passing(self):
        """measure_loudness() returns {} when ffmpeg's loudnorm JSON doesn't parse out of stderr
        (malformed/unexpected output). main() used to gate the loudness/true-peak rows entirely on
        `if lm:`, so a measurement failure meant those rows were never appended at all -- not FAIL,
        not WARN, just absent -- and check.py would still report an overall PASS for a platform
        with a loudness requirement it never actually verified. A silent false PASS is worse than a
        crash for a compliance tool. Verify a forced measurement failure surfaces as WARN rows,
        not a vanished check."""
        from unittest.mock import patch
        sys.path.insert(0, str(SCRIPTS))
        import check
        with patch.object(check, "measure_loudness", return_value={}):
            buf = __import__("io").StringIO()
            import contextlib
            with contextlib.redirect_stdout(buf):
                sys.argv = ["check.py", str(self.src), "--platform", "youtube", "--json"]
                check.main()
            data = json.loads(buf.getvalue())
        statuses = {r["check"]: r["status"] for r in data["checks"]}
        self.assertIn("loudness", statuses, "an unmeasurable loudness check must still appear in the report")
        self.assertIn("true peak", statuses)
        self.assertEqual(statuses["loudness"], "WARN")
        self.assertEqual(statuses["true peak"], "WARN")

    def test_scenes_and_highlights(self):
        src = OUT / "scenes_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:d=4", "-f", "lavfi", "-i", "smptebars=size=640x360:rate=30:d=4",
           "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=30",
           "-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*440*t)*between(t\\,5\\,7)+0.3*sin(2*PI*330*t)*between(t\\,9\\,10)':s=48000",
           "-filter_complex", "[2:v]trim=0:4,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
           "-map", "[v]", "-map", "3:a", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", src)
        edl = OUT / "picks.txt"
        sheet = OUT / "scenes.png"
        data = json.loads(script("scenes.py", src, "--highlights", "2", "--target", "6", "--edl", edl, "--sheet", sheet, "--json").stdout)
        self.assertEqual(data["scene_count"], 3)
        self.assertEqual([round(sc["start"]) for sc in data["scenes"]], [0, 4, 8])
        self.assertEqual(len(data["highlights"]), 2)
        self.assertClose(data["highlights_total"], 6.0, 0.6)
        # the loudest pick must cover the 5-7 s tone
        self.assertTrue(any(h["start"] <= 5.5 and h["end"] >= 6.5 for h in data["highlights"]), data["highlights"])
        self.assertTrue(sheet.exists())
        self.assertGreater(png_size(sheet)[0], 1200, "three tiles across")
        # EDL feeds cut.py
        segs = ",".join(edl.read_text().split())
        out = OUT / "digest.mp4"
        script("cut.py", src, "--segments", segs, "--accurate", "--fast", "-o", out)
        self.assertClose(probe(str(out))["duration"], 6.0, 0.6)

    def test_scenes_rank_by_duration_picks_longest_scenes_not_loudest(self):
        src = OUT / "scenes_rank_src.mp4"
        # three scenes: 2s, 6s (longest, silent), 4s (loud tone) -- audio and duration ranking must disagree
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:d=2", "-f", "lavfi", "-i", "smptebars=size=640x360:rate=30:d=6",
           "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=30",
           "-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*440*t)*between(t\\,8\\,11)':s=48000",
           "-filter_complex", "[2:v]trim=0:4,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
           "-map", "[v]", "-map", "3:a", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", src)
        by_audio = json.loads(script("scenes.py", src, "--highlights", "1", "--json").stdout)
        by_duration = json.loads(script("scenes.py", src, "--highlights", "1", "--rank-by", "duration", "--json").stdout)
        self.assertEqual(by_audio["highlights_rank_by"], "audio")
        self.assertEqual(by_duration["highlights_rank_by"], "duration")
        # audio ranking picks the loud scene (8-11s window, inside scene 3 at 8-12s)
        self.assertTrue(any(h["start"] >= 7.5 for h in by_audio["highlights"]), by_audio["highlights"])
        # duration ranking picks the longest (silent) scene, which starts at 2s
        self.assertTrue(any(round(h["start"]) == 2 for h in by_duration["highlights"]), by_duration["highlights"])

    def test_render_project(self):
        proj = OUT / "project.json"
        proj.write_text(json.dumps({
            "output": "render_final.mp4",
            "frame": {"aspect": "9:16", "width": 720, "fps": 30},
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:05"}, {"src": "source.mp4", "in": 6, "out": 10, "speed": 1.25}],
            "transition": {"type": "fade", "duration": 0.5},
            "captions": {"text": "cues.txt", "animate": "pop", "karaoke": True, "size": 26},
            "overlays": [{"text": "render test", "position": "top-left", "start": 0.5, "end": 3, "fade": 0.3, "box": True}],
            "audio": {"music": "long_ref.wav", "music_volume": -20, "duck": True, "fade_out": 1},
            "loudness": {"lufs": -14, "tp": -1},
            "export": {"preset": "reels"},
            "check": {"platform": "reels"},
        }), encoding="utf-8")
        if not (OUT / "cues.txt").exists():
            (OUT / "cues.txt").write_text("0:00-0:03 Hello world\n", encoding="utf-8")
        (OUT / "render_final.mp4").unlink(missing_ok=True)
        plan = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        self.assertTrue(plan["dry_run"])
        self.assertFalse((OUT / "render_final.mp4").exists())
        data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertEqual(data["stages"], ["clips", "join", "fit", "captions", "overlays", "audio", "loudness", "export", "check"])
        self.assertTrue(data["check"]["ok"], data["check"])
        m = probe(str(OUT / "render_final.mp4"))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 1920))
        self.assertClose(m["duration"], 4 + 3.2 - 0.5, 0.4)
        self.assertEqual(list(OUT.glob("render_final_work*")), [], "work dir removed when not kept")
        init = OUT / "init.json"
        script("render.py", "--init", init)
        self.assertIn("clips", json.loads(init.read_text()))
        # --stop-after keeps the intermediate
        out = json.loads(script("render.py", proj, "--fast", "--stop-after", "join", "--work", OUT / "rw", "--json").stdout)
        self.assertEqual(out["stages"], ["clips", "join"])
        self.assertTrue(Path(out["output"]).exists())

    def test_render_default_work_dir_is_unique_per_process(self):
        """The default work dir name came only from the output path (e.g. "out_work"), no PID or
        timestamp -- two concurrent render.py runs targeting the same output (a batch.py "project"
        recipe processing files in parallel, or simply two runs by mistake) shared the same work
        directory and clobbered each other's same-named intermediates (clip00.mp4, fit.mp4, ...)
        mid-run. Verify the auto-derived work dir name includes this process's own PID."""
        proj = OUT / "project_workdir.json"
        proj.write_text(json.dumps({"output": "render_workdir_check.mp4", "clips": [{"src": "source.mp4", "in": 0, "out": 2}]}), encoding="utf-8")
        # --keep leaves the PID-suffixed dir behind, so a second run of this suite in the same
        # OUT (a local re-run, or a coverage pass) would count the previous run's dir too.
        for stale in OUT.glob("render_workdir_check_work*"):
            if stale.is_dir():
                shutil.rmtree(stale)
        out = json.loads(script("render.py", proj, "--fast", "--stop-after", "clips", "--keep", "--json").stdout)
        self.assertEqual(out["stages"], ["clips"])
        work_dirs = [p for p in OUT.glob("render_workdir_check_work*") if p.is_dir()]
        self.assertEqual(len(work_dirs), 1)
        self.assertRegex(work_dirs[0].name, r"^render_workdir_check_work_\d+$",
                          "the default work dir name must carry a PID suffix, not just the bare output stem")

    def test_render_single_clip_fit_height_is_not_silently_dropped(self):
        """The single-clip fit path only ever inherited width/fps from project.frame, and the
        flag-forwarding list that turns project.fit's own keys into fit.py argv omitted height
        entirely -- so a project.json specifying "fit": {"height": N} (with no other fit key)
        used to build fit.py argv with nothing in it at all ("nothing to do" crash), and combined
        with another fit key (e.g. duration) the height silently never reached fit.py -- the
        output's height was left unchanged with no error. Verify height alone now actually
        resizes a single-clip render."""
        proj = OUT / "project_height.json"
        proj.write_text(json.dumps({
            "output": "render_height.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:04"}],
            "fit": {"height": 480},
        }), encoding="utf-8")
        script("render.py", proj, "--fast", "--json")
        m = probe(str(OUT / "render_height.mp4"))
        self.assertEqual(m["video"]["height"], 480)

    def test_render_exits_nonzero_when_the_check_stage_fails(self):
        """A render whose deliverable fails its own check stage must not report success."""
        proj = OUT / "project_bad_check.json"
        proj.write_text(json.dumps({
            "output": "render_bad.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:04"}],
            "export": {"preset": "reels"},  # portrait 9:16 output
            "check": {"platform": "broadcast"},  # broadcast requires 16:9 -- guaranteed aspect FAIL
        }), encoding="utf-8")
        proc = script("render.py", proj, "--fast", "--json", expect_fail=True)
        data = json.loads(proc.stdout)
        self.assertGreater(data["check"]["failed"], 0, data["check"])
        self.assertTrue(Path(data["output"]).exists(), "the deliverable is still written even though it fails delivery spec")

    def test_join_width_keeps_aspect(self):
        out = OUT / "join_w.mp4"
        script("join.py", self.src, self.src, "--transition", "none", "--width", "640", "--fast", "-o", out)
        m = probe(str(out))["video"]
        self.assertEqual((m["width"], m["height"]), (640, 360))

    # ---------------------------------------------------------------- v0.6: graphics / brand / report
    def test_graphics_templates(self):
        brand = OUT / "brand.json"
        brand.write_text(json.dumps({"font": "DejaVu Sans", "colors": {"primary": "FF6A00", "text": "FFFFFF", "background": "0B1D2A"},
                                     "logo": "logo.png", "logo_position": "top-right", "logo_scale": 140, "safe_margin": 40,
                                     "caption": {"size": 28, "position": "bottom", "animate": "pop", "karaoke": True, "bold": True}}), encoding="utf-8")
        cases = {
            "lower-third": ["--name", "Ada Lovelace", "--title", "Analyst", "--start", "1", "--end", "6"],
            "title": ["--title", "Episode 12", "--subtitle", "The math of video", "--start", "0", "--end", "4"],
            "chapter": ["--title", "Part 2", "--start", "0", "--end", "5"],
            "progress": [],
            "countdown": ["--from", "3", "--start", "1", "--end", "5"],
            "bug": ["--title", "@handle"],
        }
        for name, argv in cases.items():
            out = OUT / f"gfx_{name}.mp4"
            proc = script("graphics.py", self.src, "--template", name, "--brand", brand, "--fast", "-o", out, *argv)
            self.assertClose(probe(str(out))["duration"], 12.0, 0.2, name)
            self.assertTrue("FF6A00" in proc.stderr or "0B1D2A" in proc.stderr, f"{name} uses the brand colours")
        # animated templates must actually move: lower-third frame mid-slide differs from settled frame
        script("look.py", OUT / "gfx_lower-third.mp4", "--at", "1.15", "--at", "3", "--no-timecode", "-o", OUT / "lt")
        a, b = (OUT / "lt_1.150s.png").read_bytes(), (OUT / "lt_3.000s.png").read_bytes()
        self.assertNotEqual(a[200:4000], b[200:4000])
        script("graphics.py", self.src, "--template", "lower-third", expect_fail=True)

    def test_graphics_audio_stream_selects_the_requested_track_not_always_the_first(self):
        two = OUT / "gfx_two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        out1 = OUT / "gfx_two_s1.mp4"
        script("graphics.py", two, "--template", "bug", "--title", "@handle", "--audio-stream", "1", "-o", out1, "--fast")
        self.assertIsNotNone(probe(str(out1))["audio"])
        out_prog = OUT / "gfx_two_progress.mp4"
        script("graphics.py", two, "--template", "progress", "--audio-stream", "1", "-o", out_prog, "--fast")
        self.assertIsNotNone(probe(str(out_prog))["audio"])
        proc = script("graphics.py", two, "--template", "bug", "--title", "x", "--audio-stream", "5", "-o", OUT / "gfx_nope.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("audio-stream", proc.stderr)

    def test_brand_defaults_apply_to_caption_and_logo(self):
        brand = OUT / "brand.json"
        if not brand.exists():
            self.test_graphics_templates()
        ass = OUT / "brand.ass"
        script("caption.py", self.src, "--text", self.cues, "--brand", brand, "--write-ass", ass, "--fast", "-o", OUT / "brand_cap.mp4")
        style = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Style:")][0]
        self.assertIn("&H00006AFF", style, "primary FF6A00 becomes the karaoke fill (BGR)")
        self.assertIn(",70,", style, "size 28 scaled to 720p")
        self.assertIn("\\kf", ass.read_text(encoding="utf-8-sig"), "brand enables karaoke")
        proc = script("overlay.py", self.src, "--logo", "--brand", brand, "--fast", "-o", OUT / "brand_logo.mp4")
        self.assertIn("scale=140:-1", proc.stderr)
        self.assertIn("overlay=W-w-40:40", proc.stderr)
        script("overlay.py", self.src, "--logo", expect_fail=True)

    def test_report_html(self):
        reels = OUT / "export_reels.mp4"
        if not reels.exists():
            script("export.py", self.src, "--preset", "reels", "--fit", "crop", "-o", reels)
        cmds = OUT / "cmds.txt"
        cmds.write_text("python3 export.py source.mp4 --preset reels\n")
        out = OUT / "report.html"
        data = json.loads(script("report.py", "--before", self.src, "--after", reels, "--platform", "reels", "--commands", cmds, "--title", "Test delivery", "-o", out, "--json").stdout)
        self.assertEqual(data["report"], str(out))
        html_text = out.read_text(encoding="utf-8")
        self.assertIn("Test delivery", html_text)
        self.assertEqual(html_text.count("data:image/png;base64"), 2, "before and after contact sheets")
        self.assertIn("export.py source.mp4 --preset reels", html_text)
        self.assertIn("class='verdict", html_text)
        self.assertIn("1080×1920", html_text)
        script("report.py", "--after", reels, "--no-sheets", "-o", OUT / "report2.html")
        self.assertLess((OUT / "report2.html").stat().st_size, 40000)

    # ---------------------------------------------------------------- v0.7: MCP server / batch / ASR bridge
    def test_mcp_server_stdio(self):
        server = ROOT / "mcp" / "server.py"
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "probe", "arguments": {"inputs": [str(self.src)]}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "cut", "arguments": {"input": str(self.src), "start": 1, "end": 3, "output": str(OUT / "mcp_cut.mp4")}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "cut", "arguments": {"argv": [str(self.src), "--start", "0", "--end", "2", "-o", str(OUT / "mcp_cut2.mp4")]}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "bogus/method"},
        ]
        proc = subprocess.run([sys.executable, str(server)], input="\n".join(json.dumps(r) for r in reqs) + "\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resp = {r["id"]: r for r in (json.loads(l) for l in proc.stdout.splitlines() if l.strip())}
        self.assertEqual(resp[1]["result"]["serverInfo"]["name"], "ffmpeg-skill")
        names = {t["name"] for t in resp[2]["result"]["tools"]}
        self.assertTrue({"probe", "cut", "render", "check", "scenes", "batch"} <= names or {"probe", "cut", "render", "check", "scenes"} <= names)
        self.assertEqual(resp[3]["result"]["structuredContent"]["duration"], 12.0)
        self.assertClose(resp[4]["result"]["structuredContent"]["probe"]["duration"], 2.0, 0.6)
        self.assertTrue(Path(resp[5]["result"]["structuredContent"]["output"]).exists())
        self.assertTrue(resp[6]["result"].get("isError"))
        self.assertEqual(resp[7]["error"]["code"], -32601)

    def test_mcp_server_survives_a_non_object_json_line(self):
        """json.loads accepts any valid JSON value, not just an object -- a bare `42`, `null`,
        `true` or `[1,2]` line parses without raising, but main()'s very next line, `"id" not in
        req`, raised an uncaught TypeError for a non-dict req (an int/bool/None isn't iterable the
        way `in` needs). That check sat outside the try/except wrapping handle(), so the exception
        propagated out of the stdin loop and killed the whole stdio server process -- not just
        that one malformed line, but every other in-flight and future tool call in the session.
        Verify a line like this is now skipped, and the server stays alive and answers the next
        (valid) request instead of exiting non-zero with nothing produced for it."""
        server = ROOT / "mcp" / "server.py"
        lines = ["42", "null", "true", "[1,2,3]",
                 json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})]
        proc = subprocess.run([sys.executable, str(server)], input="\n".join(lines) + "\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, f"server must not crash on non-object JSON lines; stderr: {proc.stderr}")
        resp = [json.loads(response_line) for response_line in proc.stdout.splitlines() if response_line.strip()]
        self.assertEqual(len(resp), 1, "only the one real request should get a response")
        self.assertEqual(resp[0]["id"], 1)
        self.assertIn("tools", resp[0]["result"])

    def test_batch_recipe_and_cache(self):
        folder = OUT / "batch_in"
        folder.mkdir(exist_ok=True)
        for name in ("a.mp4", "b.mp4"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_final",
                                      "steps": [["fit.py", "{in}", "--duration", "5", "-o", "{out}"], ["export.py", "{in}", "--preset", "x", "-o", "{out}"]]}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertEqual(data["processed"], 2)
        self.assertFalse(any(r.get("cached") for r in data["results"]))
        for r in data["results"]:
            m = probe(r["output"])
            self.assertClose(m["duration"], 5.0, 0.3)
            self.assertEqual(m["video"]["width"], 1280)
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertTrue(all(r.get("cached") for r in data["results"]), "second run served from cache")
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--force", "--json").stdout)
        self.assertFalse(any(r.get("cached") for r in data["results"]))
        # project-based recipe
        proj = folder / "p.json"
        proj.write_text(json.dumps({"clips": [{"src": "x", "in": 0, "out": 3}], "export": {"preset": "x"}}))
        recipe2 = folder / "batch2.json"
        recipe2.write_text(json.dumps({"glob": "a.mp4", "output_dir": "out2", "suffix": "_p", "project": "p.json"}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe2, "--fast", "--json").stdout)
        self.assertEqual(data["processed"], 1)
        self.assertClose(probe(data["results"][0]["output"])["duration"], 3.0, 0.3)

    def test_batch_project_recipe_cache_invalidates_on_project_json_content_change(self):
        """A "project" recipe is just {"project": "<path>", "clip_key": N} -- the real settings
        (export preset, captions, everything) live in the file at that path. The cache key used
        to hash only this outer recipe dict, so editing project.json's content (export preset
        swapped from "copy" to "x", a real re-encode) without touching batch.json itself left the
        key unchanged, and the stale cached output was served for the new settings with no error
        or warning. Verify a content-only change to project.json invalidates the cache."""
        folder = OUT / "batch_project_cache"
        folder.mkdir(exist_ok=True)
        (folder / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        proj = folder / "p.json"
        proj.write_text(json.dumps({"clips": [{}], "export": {"preset": "copy"}}))
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "clip.mp4", "output_dir": "out", "project": "p.json"}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertFalse(data["results"][0].get("cached"))
        proj.write_text(json.dumps({"clips": [{}], "export": {"preset": "x"}}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertFalse(data["results"][0].get("cached"), "a content-only project.json change must not be served from a stale cache")

    def test_batch_cache_write_is_atomic_no_leftover_temp_file(self):
        """The cache file used to be written with a plain write_text(), which is not atomic -- a
        process killed mid-write leaves a truncated file that the next run's json.loads() treats
        as corrupt and silently discards (every prior cache entry lost, not just the interrupted
        one). Now written via a sibling temp file + os.replace(). Verify a normal run leaves the
        cache file valid and no stray .tmp<pid> file behind."""
        folder = OUT / "batch_cache_atomic"
        folder.mkdir(exist_ok=True)
        (folder / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "clip.mp4", "output_dir": "out", "steps": [["export.py", "{in}", "--preset", "copy", "-o", "{out}"]]}))
        script("batch.py", folder, "--recipe", recipe, "--fast")
        outdir = folder / "out"
        cache_path = outdir / ".ffskill_cache.json"
        self.assertTrue(cache_path.exists())
        json.loads(cache_path.read_text(encoding="utf-8"))  # must not be truncated/corrupt
        leftover = list(outdir.glob(".ffskill_cache.json.tmp*"))
        self.assertEqual(leftover, [], f"temp cache file(s) left behind: {leftover}")

    def test_batch_refuses_a_recipe_step_naming_a_script_outside_scripts_dir(self):
        """run_step() built its command as `HERE / argv[0]`, where argv[0] came straight from an
        untrusted recipe JSON step. Path's / operator silently ignores the left side when the
        right side is itself an absolute path, and does nothing to stop a "../" traversal either
        -- so a recipe (from a template, a shared config, anywhere the caller didn't author it
        themselves) naming an absolute or ../-relative path got that file executed as a Python
        script, with the caller's own privileges, once per matching media file. Verify both an
        absolute path and a traversal path are refused instead of executed."""
        folder = OUT / "batch_security"
        folder.mkdir(exist_ok=True)
        (folder / "a.mp4").write_bytes(Path(self.src).read_bytes())
        evil = OUT / "batch_security_evil.py"
        marker = OUT / "batch_security_pwned.txt"
        marker.unlink(missing_ok=True)
        evil.write_text(f"open({str(marker)!r}, 'w').write('pwned')\n", encoding="utf-8")

        for step in ([str(evil)], ["../../../../tmp/does_not_matter.py"]):
            recipe = folder / "batch.json"
            recipe.write_text(json.dumps({"glob": "*.mp4", "steps": [step]}))
            proc = script("batch.py", folder, "--recipe", recipe, "--fast", "--force", expect_fail=True)
            self.assertIn("scripts/", proc.stderr)
            self.assertFalse(marker.exists(), f"step {step} must not have executed")

    def test_batch_refuses_a_fixed_ext_recipe_that_collapses_two_sources_to_one_output(self):
        """final_path() falls back to each source's OWN extension by default, so files that only
        differ by extension don't collide -- but a recipe with a fixed "ext" (e.g. converting a
        folder of mixed .mp4/.mov masters to one format) makes two sources with the same stem
        (clip.mp4 and clip.mov) resolve to the identical final path (clip_out.mp4). process() had
        no collision detection: the file processed later in sorted() order used to silently
        overwrite the earlier one's finished output, with the cache still recording both entries
        as ok. Verify this is now refused up front, before either file is processed, rather than
        one silently clobbering the other."""
        folder = OUT / "batch_collision_in"
        folder.mkdir(exist_ok=True)
        for name in ("clip.mp4", "clip.mov"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        recipe = folder / "collide.json"
        recipe.write_text(json.dumps({"ext": "mp4", "steps": [["export.py", "{in}", "--preset", "x", "-o", "{out}"]]}))
        proc = script("batch.py", folder, "--recipe", recipe, "--fast", expect_fail=True)
        self.assertIn("collision", proc.stderr)
        self.assertIn("clip.mp4", proc.stderr)
        self.assertIn("clip.mov", proc.stderr)
        self.assertFalse((folder / "out" / "clip_out.mp4").exists(), "nothing should be written once a collision is detected")

    def test_transcribe_without_engine_explains(self):
        import shutil
        if shutil.which("whisper-cli") or shutil.which("whisper"):
            self.skipTest("a local ASR engine is installed")
        try:
            import faster_whisper  # noqa: F401
            self.skipTest("faster-whisper installed")
        except ImportError:
            pass
        proc = script("caption.py", self.src, "--transcribe", "-o", OUT / "asr.mp4", expect_fail=True)
        self.assertIn("no local speech-to-text engine", proc.stderr)
        self.assertIn("whisper", proc.stderr)

    # ---------------------------------------------------------------- Phase 3 regressions
    def test_sync_large_offset_on_repetitive_music(self):
        # repetitive music-like signal: a 4-bar loop with slow variation; raw correlation used to prefer
        # the small-overlap-friendly wrong lag, NCC must find the true -28 s offset in a 60 s window
        loop = OUT / "loop.wav"
        # speech-like: dialogue from the demo tones plus random-looking bursts (incommensurate gates,
        # a slowly drifting pitch and pink-noise "room"), so no two 9 s stretches look alike
        expr = (TONES + "+0.25*sin(2*PI*(165+30*sin(2*PI*0.031*t))*t)*gt(sin(2*PI*0.113*t+0.4)\\,0.55)"
                "+0.3*sin(2*PI*(520+80*sin(2*PI*0.017*t+1))*t)*gt(sin(2*PI*0.29*t+2.1)*sin(2*PI*0.073*t)\\,0.35)")
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000",
           "-f", "lavfi", "-i", "anoisesrc=a=0.02:c=pink:r=48000", "-t", "200", "-filter_complex", "amix=inputs=2:duration=first:normalize=0", "-c:a", "pcm_s16le", loop)
        ref = OUT / "loop_ref.wav"
        sec = OUT / "loop_sec.wav"
        # 28 s offset inside a 120 s analysis window (the documented rule: window >= 4x max offset)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "40", "-i", loop, "-t", "120", "-c:a", "pcm_s16le", ref)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "12", "-i", loop, "-t", "120", "-af", "volume=-8dB,highpass=f=300", "-c:a", "pcm_s16le", sec)
        data = json.loads(script("sync.py", ref, sec, "--json", "--max-offset", "30").stdout)
        self.assertClose(data["offset_seconds"], -28.0, 0.02)
        self.assertGreater(data["confidence"], 0.3)

    def test_audio_only_inputs_through_the_audio_scripts(self):
        """WAV / M4A / MP3 with no video stream: loudness, silence, audio (voice, convert), cut, check."""
        m4a = OUT / "gappy.m4a"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
           "-t", "12", "-c:a", "aac", "-b:a", "128k", m4a)
        self.assertIsNone(probe(str(m4a)).get("video"))
        # loudness: wav -> m4a, codec follows the output extension
        norm = OUT / "lav_norm.m4a"
        script("loudness.py", self.mic, "-I", "-16", "--tp", "-1.5", "-o", norm)
        a = probe(str(norm))["audio"]
        self.assertEqual(a["codec"], "aac")
        self.assertIn("PASS", script("check.py", norm, "--platform", "podcast").stdout)
        # silence removal on an m4a
        tight = OUT / "gappy_tight.m4a"
        data = json.loads(script("silence.py", m4a, "-o", tight, "--json").stdout)
        self.assertClose(data["removed_seconds"], 5.25, 0.3)
        self.assertClose(probe(str(tight))["duration"], 6.75, 0.3)
        # voice clean-up keeps the container, plain -o converts
        clean = OUT / "gappy_clean.m4a"
        script("audio.py", m4a, "--voice", "-o", clean)
        self.assertEqual(probe(str(clean))["audio"]["codec"], "aac")
        mp3 = OUT / "lav.mp3"
        script("audio.py", self.mic, "-o", mp3)
        self.assertEqual(probe(str(mp3))["audio"]["codec"], "mp3")
        # trim is a stream copy on wav and mp3
        cut_wav = OUT / "lav_cut.wav"
        proc = script("cut.py", self.mic, "--start", "0:02", "--end", "0:06", "-o", cut_wav)
        self.assertIn("lossless", proc.stderr)
        self.assertClose(probe(str(cut_wav))["duration"], 4.0, 0.05)
        cut_mp3 = OUT / "lav_cut.mp3"
        script("cut.py", mp3, "--start", "2", "--end", "6", "-o", cut_mp3)
        self.assertClose(probe(str(cut_mp3))["duration"], 4.0, 0.1)
        # picture-only scripts refuse clearly instead of failing inside ffmpeg
        for argv in (("fit.py", "--duration", "5"), ("export.py", "--preset", "youtube"), ("look.py",)):
            proc = script(argv[0], self.mic, *argv[1:], "-o", OUT / "nope.out", expect_fail=True)
            self.assertIn("no video stream", proc.stderr)

    def test_loudness_silent_input_is_reported_not_crashed(self):
        silent = OUT / "silent.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", "3", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", silent)
        data = json.loads(script("loudness.py", silent, "--measure-only").stdout)
        self.assertTrue(data["silent"])
        proc = script("loudness.py", silent, "-o", OUT / "silent_norm.mp4", expect_fail=True)
        self.assertIn("silent", proc.stderr)

    def test_overlay_fade_without_start_end_fades_at_video_edges(self):
        proc = script("overlay.py", self.src, "--image", self.logo, "--fade", "0.5", "--dry-run")
        self.assertIn("fade=t=in:st=0.000", proc.stderr)
        self.assertIn("fade=t=out:st=11.500", proc.stderr)
        self.assertNotIn("\nwrote ", proc.stderr, "dry-run must not claim a file was written")

    # ---------------------------------------------------------------- _common
    def test_context_attribute_and_mapping_access_agree(self):
        from _common import Context
        ctx = Context()
        ctx["dry_run"] = True
        self.assertTrue(ctx.dry_run)
        ctx.fast = True
        self.assertTrue(ctx["fast"])
        self.assertIsNone(ctx.get("duration_hint"))
        self.assertIsNone(ctx.get("nonexistent"))
        with self.assertRaises(KeyError):
            ctx["nonexistent"] = 1
        ctx.commands.append("x")
        ctx.reset()
        self.assertEqual((ctx.dry_run, ctx.fast, ctx.commands), (False, False, []))

    # ---------------------------------------------------------------- help

    # ------------------------------------------------------------------ audio: extraction, concat, precision, dynamics
    @staticmethod
    def _samples(path):
        """(codec, sample_rate, duration_ts) of the first audio stream as ffprobe sees it."""
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,duration_ts",
                              "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, text=True, check=True).stdout.strip().split(",")
        return out[0], int(out[1]), int(out[2])

    @staticmethod
    def _peak_rms(path):
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "astats=measure_overall=Peak_level+RMS_level:measure_perchannel=none",
                               "-f", "null", "-"], stderr=subprocess.PIPE, text=True)
        vals = dict(re.findall(r"(Peak level|RMS level) dB: (-?[\d.]+)", proc.stderr))
        return float(vals["Peak level"]), float(vals["RMS level"])

    def test_audio_extraction_from_video_container(self):
        """mp4 -> wav / m4a through audio.py and cut.py: no video stream, codec from the extension, stream selection."""
        wav = OUT / "ex_audio.wav"
        data = json.loads(script("audio.py", self.src, "-o", wav, "--json").stdout)
        self.assertIsNone(data["probe"]["video"])
        self.assertEqual(data["probe"]["audio"]["codec"], "pcm_s16le")
        self.assertFalse(data["video"])
        m4a = OUT / "ex_voice.m4a"
        data = json.loads(script("audio.py", self.src, "--voice", "-o", m4a, "--json").stdout)
        self.assertIsNone(data["probe"]["video"])
        self.assertEqual(data["probe"]["audio"]["codec"], "aac")
        # a video output keeps the stream-copied picture as before
        mp4 = OUT / "ex_keep.mp4"
        data = json.loads(script("audio.py", self.src, "--denoise", "-o", mp4, "--json").stdout)
        self.assertIsNotNone(data["probe"]["video"])
        self.assertTrue(data["video"])
        # two audio streams: --audio-stream 1 picks the 880 Hz / 44.1 kHz track, an index past the end fails as input
        two = OUT / "two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        self.assertEqual(probe(str(two))["audio_streams"][1]["sample_rate"], 44100)
        s1 = OUT / "two_s1.wav"
        data = json.loads(script("audio.py", two, "--audio-stream", "1", "-o", s1, "--json").stdout)
        self.assertEqual(data["audio_stream"], 1)
        self.assertEqual(self._samples(s1)[1], 44100)
        proc = script("audio.py", two, "--audio-stream", "2", "-o", OUT / "nope.wav", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("2 audio stream", proc.stderr)
        # cut.py with an audio extension extracts too, and never copies AAC packets into a WAV
        cw = OUT / "ex_cut.wav"
        data = json.loads(script("cut.py", self.src, "--start", "1", "--end", "3", "-o", cw, "--json").stdout)
        self.assertIsNone(data["probe"]["video"])
        self.assertEqual(self._samples(cw)[0], "pcm_s16le")
        self.assertEqual(data["precision"], "sample")

    def test_join_audio_only_inputs(self):
        """WAV + M4A + MP3 of different rates and channel counts join as audio; video containers and mixed inputs are refused."""
        st = OUT / "j_stereo44.m4a"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100", "-t", "3", "-ac", "2", "-c:a", "aac", st)
        mp3 = OUT / "j_mono.mp3"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000", "-t", "3", "-c:a", "libmp3lame", mp3)
        mic_dur = probe(str(self.mic))["duration"]
        # crossfade -> flac: rate of the first clip, widest layout
        out = OUT / "j_audio.flac"
        data = json.loads(script("join.py", self.mic, st, mp3, "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "audio")
        self.assertEqual((data["sample_rate"], data["channels"]), (48000, 2))
        self.assertIsNone(data["probe"]["video"])
        self.assertEqual(data["probe"]["audio"]["codec"], "flac")
        self.assertClose(data["probe"]["duration"], mic_dur + 3 + 3 - 2 * 0.5, 0.15)
        # butt join -> wav, explicit rate and channels
        out2 = OUT / "j_audio.wav"
        data = json.loads(script("join.py", st, mp3, "--transition", "none", "--sample-rate", "44100", "--channels", "1", "-o", out2, "--json").stdout)
        self.assertEqual(self._samples(out2)[:2], ("pcm_s16le", 44100))
        self.assertEqual(data["probe"]["audio"]["channels"], 1)
        self.assertClose(data["probe"]["duration"], 6.0, 0.1)
        # refusals are input errors, before ffmpeg runs
        proc = script("join.py", self.mic, mp3, "-o", OUT / "j_audio.mp4", "--json", expect_fail=True)
        self.assertIn("audio extension", json.loads(proc.stdout)["error"]["message"])
        self.assertNotIn("ffmpeg ", proc.stderr.replace("/usr/bin/", ""), "refused before ffmpeg ran")
        proc = script("join.py", self.src, self.mic, "-o", OUT / "j_mixed.mp4", "--json", expect_fail=True)
        self.assertIn("has no video stream", proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        # dry-run plans the audio join and writes nothing
        planned = OUT / "j_dry.wav"
        data = json.loads(script("join.py", self.mic, mp3, "-o", planned, "--dry-run", "--json").stdout)
        self.assertTrue(data["dry_run"])
        self.assertIn("acrossfade", data["commands"][0])
        self.assertFalse(planned.exists())

    def test_cut_audio_precision_is_measured(self):
        """Stream copy is packet-accurate, --accurate is sample-exact on PCM/FLAC, lossy outputs say codec_frame."""
        start, end = 1.2345, 2.3456
        want = round((end - start) * 48000)  # 53333 samples
        # WAV copy: packet boundary, reported as such, within a few ms
        cw = OUT / "prec_copy.wav"
        data = json.loads(script("cut.py", self.mic, "--start", str(start), "--end", str(end), "-o", cw, "--json").stdout)
        self.assertEqual(data["precision"], "packet")
        self.assertFalse(data["reencoded"])
        self.assertLess(abs(data["duration_error_ms"]), 50)
        self.assertEqual(self._samples(cw)[0], "pcm_s16le")
        # WAV --accurate: exactly the requested number of samples
        ca = OUT / "prec_acc.wav"
        data = json.loads(script("cut.py", self.mic, "--start", str(start), "--end", str(end), "--accurate", "-o", ca, "--json").stdout)
        self.assertEqual(data["precision"], "sample")
        self.assertEqual(self._samples(ca), ("pcm_s16le", 48000, want))
        self.assertLess(abs(data["duration_error_ms"]), 0.05)
        # 44.1 kHz FLAC, --accurate: exact at its own rate
        flac = OUT / "prec_44.flac"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100", "-t", "3", "-c:a", "flac", flac)
        fa = OUT / "prec_44_cut.flac"
        data = json.loads(script("cut.py", flac, "--start", "0.5", "--end", "1.7", "--accurate", "-o", fa, "--json").stdout)
        self.assertEqual(data["precision"], "sample")
        self.assertEqual(self._samples(fa), ("flac", 44100, round(1.2 * 44100)))
        # compressed source (AAC in mp4) decoded to PCM with --accurate: exact; to AAC: codec_frame, not "sample"
        ma = OUT / "prec_from_aac.wav"
        data = json.loads(script("cut.py", self.src, "--start", str(start), "--end", str(end), "--accurate", "-o", ma, "--json").stdout)
        self.assertEqual(data["precision"], "sample")
        self.assertEqual(self._samples(ma)[2], want)
        m4a = OUT / "prec_to_aac.m4a"
        data = json.loads(script("cut.py", self.src, "--start", str(start), "--end", str(end), "--accurate", "-o", m4a, "--json").stdout)
        self.assertEqual(data["precision"], "codec_frame")
        self.assertEqual(self._samples(m4a)[0], "aac")
        # video re-encode keeps reporting frame precision; a plain copy keeps packet
        mp4 = OUT / "prec_video.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "1", "--end", "3", "--accurate", "--preset", "ultrafast", "-o", mp4, "--json").stdout)
        self.assertEqual(data["precision"], "frame")
        self.assertIsNotNone(data["probe"]["video"])

    def test_audio_typed_dynamics(self):
        """--gate / --compress / --limit map typed flags onto acompressor, alimiter, agate; ranges are enforced; the ceiling holds."""
        out = OUT / "dyn.wav"
        data = json.loads(script("audio.py", self.mic, "--gate", "--gate-threshold", "-50", "--compress", "--comp-threshold", "-20",
                                 "--comp-ratio", "4", "--comp-attack", "5", "--comp-release", "80", "--comp-makeup", "6",
                                 "--limit", "--limit-ceiling", "-3", "-o", out, "--json").stdout)
        self.assertEqual(data["dynamics"], ["agate", "acompressor", "alimiter"])
        cmd = data["commands"][0]
        self.assertIn("agate=threshold=0.00316228", cmd)
        self.assertIn("acompressor=threshold=0.1:ratio=4:attack=5:release=80:makeup=1.99526", cmd)
        self.assertIn("alimiter=limit=0.707946:level=disabled", cmd)
        peak, rms = self._peak_rms(out)
        self.assertLessEqual(peak, -3.0 + 0.1, "limiter ceiling")
        # the compressor alone on a full-scale sine: threshold -20 dB, ratio 4 settle far below 0 dB and above the threshold
        sine = OUT / "dyn_sine.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-af", "volume=18.06dB", "-c:a", "pcm_s16le", sine)
        comp = OUT / "dyn_comp.wav"
        script("audio.py", sine, "--compress", "--comp-threshold", "-20", "--comp-ratio", "4", "--comp-attack", "5", "--comp-release", "80", "-o", comp)
        peak_c, _ = self._peak_rms(comp)
        self.assertGreater(self._peak_rms(sine)[0], -0.5)
        self.assertLess(peak_c, -3.0, "compressor reduced a 0 dBFS tone (measured -7.5 dB: ffmpeg detects RMS, knee 2.83 dB)")
        self.assertGreater(peak_c, -20.0, "compression, not a gate")
        # every flag is range-checked before ffmpeg runs
        for flags, text in ((("--compress", "--comp-ratio", "50"), "1..20"),
                            (("--limit", "--limit-ceiling", "1"), "-24..0"),
                            (("--gate", "--gate-attack", "0"), "0.01..9000"),
                            (("--compress", "--comp-makeup", "40"), "0..36")):
            proc = script("audio.py", self.mic, *flags, "-o", OUT / "dyn_bad.wav", "--json", expect_fail=True)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["error"]["kind"], "input")
            self.assertIn(text, doc["error"]["message"])
            self.assertNotIn("$ ", proc.stderr, "refused before ffmpeg ran")
        # a parameter without its switch is an error, not silently ignored
        proc = script("audio.py", self.mic, "--comp-ratio", "4", "-o", OUT / "dyn_bad.wav", expect_fail=True)
        self.assertIn("add --compress", proc.stderr)
        # the limiter alone on a video input keeps the picture
        mp4 = OUT / "dyn_video.mp4"
        data = json.loads(script("audio.py", self.src, "--limit", "--limit-ceiling", "-1", "-o", mp4, "--json").stdout)
        self.assertIsNotNone(data["probe"]["video"])
        self.assertLessEqual(self._peak_rms(mp4)[0], -1.0 + 0.3)


    # ------------------------------------------------------------------ FFmpeg 8+ / Windows compatibility
    @staticmethod
    def _psnr(a, b):
        """Average PSNR of b against a (dB); lower means the picture changed more. inf when identical."""
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"],
                              stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"average:(inf|[\d.]+)", proc.stderr)
        assert m, proc.stderr[-400:]
        return float("inf") if m.group(1) == "inf" else float(m.group(1))

    def test_filter_paths_with_drive_colon_spaces_and_unicode(self):
        """subtitles= / ass= / lut3d=file= / fontfile= take a path with a colon, spaces and non-ASCII.

        A Windows path `D:\\a\\x.srt` is what broke on the Windows CI: the filter option value is
        parsed twice, so the colon needs two levels of escaping. On POSIX a directory literally named
        `D:` reproduces it; on Windows the real drive letter does.
        """
        base = OUT / "compat dir ünïcode"
        d = base if os.name == "nt" else base / "D:"
        d.mkdir(parents=True, exist_ok=True)
        src = d / "src vid.mp4"
        shutil.copyfile(self.src, src)
        cues = d / "cues täxt.txt"
        cues.write_text("0:00-0:06 Hello caption\n", encoding="utf-8")
        # captions via subtitles= (SRT) and ass=, both re-parsed by libass
        cap = d / "cap.mp4"
        script("caption.py", src, "--text", cues, "--size", "40", "--fast", "-o", cap)
        self.assertLess(self._psnr(self.src, cap), 45, "burned caption changed the picture")
        capa = d / "cap ass.mp4"
        script("caption.py", src, "--text", cues, "--animate", "pop", "--fast", "-o", capa)
        self.assertTrue((d / "cap ass.ass").exists())
        self.assertLess(self._psnr(self.src, capa), 45)
        # a fonts dir with the same kind of path
        script("caption.py", src, "--text", cues, "--fonts-dir", d, "--fast", "-o", d / "cap fonts.mp4")
        # LUT file: full strength inverts the picture, half strength goes through the split/blend graph
        lut = d / "invert lut.cube"
        lines = ["LUT_3D_SIZE 2"] + [f"{1 - r} {1 - g} {1 - b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)]
        lut.write_text("\n".join(lines) + "\n")
        inv = d / "lut.mp4"
        script("color.py", src, "--lut", lut, "--preset", "veryfast", "-o", inv)
        self.assertLess(self._psnr(self.src, inv), 15, "inverted LUT changed every pixel")
        half = d / "lut half.mp4"
        script("color.py", src, "--lut", lut, "--lut-strength", "0.5", "--preset", "veryfast", "-o", half)
        self.assertClose(probe(str(half))["duration"], 12.0, 0.2)
        # drawtext fontfile= with the same path shape (when a TTF is available to copy)
        font = self._any_ttf()
        if font:
            ttf = d / "my font.ttf"
            shutil.copyfile(font, ttf)
            script("overlay.py", src, "--text", "Hi", "--font-file", ttf, "--fast", "-o", d / "ov.mp4")

    @staticmethod
    def _any_ttf():
        for root in ("/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts", "/System/Library/Fonts", "C:/Windows/Fonts"):
            for pat in ("**/DejaVuSans.ttf", "**/Arial.ttf", "**/arial.ttf", "**/*.ttf"):
                hits = list(Path(root).glob(pat)) if Path(root).exists() else []
                if hits:
                    return hits[0]
        return None

    def test_overlay_still_is_bounded_by_the_video_length(self):
        """A looped still (-loop 1) must not make the output longer than the video (FFmpeg 7+ -shortest keeps a buffer)."""
        out = OUT / "ov_bound.mp4"
        data = json.loads(script("overlay.py", self.src, "--image", self.logo, "--fast", "-o", out, "--json").stdout)
        self.assertIn("-t", data["commands"][0])
        self.assertClose(data["probe"]["duration"], 12.0, 0.15)

    def test_overlay_on_audio_less_video_terminates(self):
        """Every other overlay test uses self.src, which has audio. Cover the audio-less case too:
        overlay is documented elsewhere as risky on inputs with no audio stream to help -shortest
        bound the looped-image (-loop 1) input, so pin down that it completes and the output duration
        matches the source exactly (the explicit -t, not -shortest, is what actually bounds it)."""
        noaudio = OUT / "overlay_noaudio_source.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-an", "-c:v", "copy", noaudio)
        self.assertIsNone(probe(str(noaudio)).get("audio"))
        out = OUT / "overlay_noaudio.mp4"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "overlay.py"), str(noaudio), "--image", str(self.logo),
             "--position", "bottom-right", "--start", "1", "--end", "5", "--fade", "0.3", "-o", str(out)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        self.assertClose(probe(str(out))["duration"], probe(str(noaudio))["duration"], 0.15)

    def test_overlay_audio_stream_selects_the_requested_track_not_always_the_first(self):
        two = OUT / "ov_two_streams.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
           "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", two)
        self.assertEqual(len(probe(str(two))["audio_streams"]), 2)
        out_text = OUT / "ov_two_text.mp4"
        script("overlay.py", two, "--text", "hi", "--audio-stream", "1", "-o", out_text, "--preset", "veryfast")
        self.assertIsNotNone(probe(str(out_text))["audio"])
        out_img = OUT / "ov_two_img.mp4"
        script("overlay.py", two, "--image", self.logo, "--audio-stream", "1", "-o", out_img, "--preset", "veryfast")
        self.assertIsNotNone(probe(str(out_img))["audio"])
        proc = script("overlay.py", two, "--text", "hi", "--audio-stream", "5", "-o", OUT / "ov_nope.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("audio-stream", proc.stderr)

    def test_overlay_video_pip_composites_at_the_right_position(self):
        red_bg = OUT / "red_bg.mp4"
        blue_quad = OUT / "blue_quad.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=1280x720:d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", red_bg)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=200x50:d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", blue_quad)
        out = OUT / "pip1.mp4"
        script("overlay.py", red_bg, "--video", blue_quad, "--position", "bottom-right", "--scale", "200", "-o", out)

        def px(path, x, y):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                                 "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        # PiP at bottom-right, 200 wide (50 tall for the 4:1 source), default margin 24:
        # x=1280-200-24=1056, y=720-50-24=646
        self.assertGreater(px(out, 1100, 660)[2], 100, "PiP area should show the blue overlay")
        self.assertGreater(px(out, 100, 100)[0], 100, "outside the PiP area, the red background must remain")

    def test_overlay_chromakey_removes_the_key_color(self):
        red_bg = OUT / "ck_red_bg.mp4"
        green_fg = OUT / "ck_green_fg.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=100x100:d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", red_bg)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00ff00:s=100x100:d=1",
           "-f", "lavfi", "-i", "color=c=white:s=20x20:d=1", "-filter_complex", "[0][1]overlay=40:40",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", green_fg)
        out = OUT / "ck1.mp4"
        script("overlay.py", red_bg, "--video", green_fg, "--chromakey", "0x00ff00", "--position", "top-left",
               "--margin", "0", "--scale", "100", "-o", out)

        def px(path, x, y):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                                 "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return r.stdout[:3]

        self.assertGreater(px(out, 10, 10)[0], 100, "keyed-out green should show the red background through it")
        self.assertGreater(min(px(out, 45, 45)), 100, "the white square inside the green should be unaffected")

    def test_overlay_chromakey_without_video_refused(self):
        script("overlay.py", self.src, "--chromakey", "green", expect_fail=True)

    def test_help_survives_a_legacy_console_encoding(self):
        """--help contains non-ASCII (Japanese example, arrows); a cp1252 console must not raise UnicodeEncodeError."""
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        for name in ("overlay.py", "render.py", "caption.py"):
            proc = subprocess.run([sys.executable, str(SCRIPTS / name), "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[-300:]}")
            self.assertIn("usage:", proc.stdout)

    def test_every_script_has_help(self):
        for name in sorted(p.name for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")):
            with self.subTest(script=name):
                out = script(name, "--help").stdout
                self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
