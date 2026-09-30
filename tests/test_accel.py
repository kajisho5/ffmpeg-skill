#!/usr/bin/env python3
"""Tests for Apple VideoToolbox encoding (--hw).

    python3 tests/test_accel.py          # this group alone
    python3 tests/test_all.py            # every group

The pure-logic cases run everywhere. The real VideoToolbox encodes run only on Apple Silicon with
an ffmpeg that lists the encoders.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, script, sh  # noqa: E402
from _common import STATE, add_common, apply_common, ffmpeg_encoders  # noqa: E402
from _common import decision, runner  # noqa: E402


def _vt_here() -> bool:
    return (platform.system() == "Darwin" and platform.machine() == "arm64"
            and {"h264_videotoolbox", "hevc_videotoolbox"} <= ffmpeg_encoders())


def _parse(argv, codec=True, orchestrator=False):
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output")
    if codec and not orchestrator:
        ap.set_defaults(crf=18)
    add_common(ap, codec=codec)
    if orchestrator:
        runner.add_hw_orchestrator_args(ap)
    args = ap.parse_args(argv)
    apply_common(args)
    return args


class HwResolutionTests(unittest.TestCase):
    """--hw / --no-hw / $FFMPEG_SKILL_HW resolve the same way in every tool."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for k in (runner.HW_ENV, runner.HW_FORCED_ENV):
            os.environ.pop(k, None)

    def tearDown(self):
        self._env.stop()
        STATE.reset()

    def test_off_by_default(self):
        _parse(["in.mp4"])
        self.assertFalse(STATE.hw)
        self.assertIsNone(STATE.hw_source)

    def test_env_turns_it_on_and_no_hw_turns_it_off(self):
        os.environ[runner.HW_ENV] = "1"
        _parse(["in.mp4"])
        self.assertEqual((STATE.hw, STATE.hw_source), (True, "env"))
        _parse(["in.mp4", "--no-hw"])
        self.assertEqual((STATE.hw, STATE.hw_source), (False, "flag"))

    def test_export_style_tools_ignore_the_env_default(self):
        """A delivery preset (codec=False: export.py) is on the GPU only when asked explicitly."""
        os.environ[runner.HW_ENV] = "1"
        _parse(["in.mp4"], codec=False)
        self.assertFalse(STATE.hw)
        _parse(["in.mp4", "--hw"], codec=False)
        self.assertEqual((STATE.hw, STATE.hw_source), (True, "flag"))

    def test_orchestrator_flag_reaches_export_style_children_as_explicit(self):
        """render.py/batch.py --hw is an explicit choice for every stage, export.py included;
        their --no-hw overrides a machine default for every stage."""
        _parse(["p.json", "--hw"], orchestrator=True)
        self.assertEqual((os.environ.get(runner.HW_ENV), os.environ.get(runner.HW_FORCED_ENV)), ("1", "1"))
        _parse(["in.mp4"], codec=False)          # a child export.py
        self.assertEqual((STATE.hw, STATE.hw_source), (True, "flag"))
        _parse(["p.json", "--no-hw"], orchestrator=True)
        _parse(["in.mp4"])                       # a child fit.py
        self.assertEqual((STATE.hw, STATE.hw_source), (False, "flag"))

    def test_tools_without_an_encoder_never_pick_it_up(self):
        os.environ[runner.HW_ENV] = "1"
        ap = argparse.ArgumentParser()
        ap.add_argument("input")
        add_common(ap)                           # no crf default: an analysis tool
        args = ap.parse_args(["in.mp4"])
        self.assertFalse(hasattr(args, "hw"))
        apply_common(args)
        self.assertFalse(STATE.hw)


class VtArgsTests(unittest.TestCase):
    def tearDown(self):
        STATE.reset()

    def test_quality_mapping_is_monotonic_and_bounded(self):
        for codec, hdr in (("h264", False), ("hevc", False), ("hevc", True)):
            qs = [decision.vt_quality(codec, crf, hdr) for crf in range(0, 52)]
            self.assertEqual(qs, sorted(qs, reverse=True))
            self.assertTrue(all(1 <= q <= 100 for q in qs))

    def test_an_hdr_source_gets_the_hdr_quality_curve(self):
        """HLG phone footage at the SDR curve's -q:v came out 6-8x x265's bytes at a higher SSIM
        (tests/bench_vt.py); the Main10 line takes its own, lower curve, chosen from the source."""
        STATE.hw = True
        hdr = {"video": {"bt2020_or_hdr": True, "color_transfer": "arib-std-b67"}}
        sdr = {"video": {"bt2020_or_hdr": False}}
        with mock.patch.object(decision, "hw_platform_reason", return_value=None), \
                mock.patch.object(decision, "ffmpeg_encoders", return_value={"hevc_videotoolbox"}):
            for crf in (18, 23, 28):
                q_hdr = decision._vt_args("hevc", crf, hdr, True)
                q_sdr = decision._vt_args("hevc", crf, sdr, True)
                q_hdr, q_sdr = int(q_hdr[q_hdr.index("-q:v") + 1]), int(q_sdr[q_sdr.index("-q:v") + 1])
                self.assertEqual(q_hdr, decision.vt_quality("hevc", crf, True))
                self.assertEqual(q_sdr, decision.vt_quality("hevc", crf))
                self.assertLess(q_hdr, q_sdr - 10, crf)

    def test_the_curves_keep_the_measured_values(self):
        """The CRF 18/23/28 values tests/bench_vt.py measured (the highest -q:v that matched the CPU
        encode's SSIM on every clip); a slope typo moves one of them."""
        self.assertEqual([decision.vt_quality("h264", c) for c in (18, 23, 28)], [75, 64, 53])
        self.assertEqual([decision.vt_quality("hevc", c) for c in (18, 23, 28)], [78, 68, 58])
        self.assertEqual([decision.vt_quality("hevc", c, True) for c in (18, 23, 28)], [63, 55, 47])

    def test_an_h264_line_on_an_hdr_source_keeps_the_h264_curve(self):
        """An export preset's x264 line on an HLG source: the VideoToolbox H.264 line replaces x264
        at the same CRF, so the HDR (Main10, CRF+2) curve does not apply."""
        STATE.hw = True
        hdr = {"video": {"bt2020_or_hdr": True, "color_transfer": "arib-std-b67"}}
        with mock.patch.object(decision, "hw_platform_reason", return_value=None), \
                mock.patch.object(decision, "ffmpeg_encoders", return_value={"h264_videotoolbox"}):
            line = decision.hw_preset_video(["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"], hdr)
        self.assertEqual(line[line.index("-q:v") + 1], "75")

    def test_av1_and_an_intel_mac_stay_on_the_cpu_with_a_note(self):
        STATE.hw = True
        self.assertIsNone(decision._vt_args("av1", 30, None, True))
        with mock.patch.object(decision, "hw_platform_reason", return_value="VideoToolbox constant-quality encoding needs Apple Silicon"):
            cpu = ["-c:v", "libx264", "-crf", "18"]
            self.assertEqual(decision._maybe_hw("h264", 18, None, True, cpu), cpu)
        self.assertTrue(any("av1" in n for n in STATE.hw_notes))
        self.assertTrue(any("Apple Silicon" in n for n in STATE.hw_notes))

    def test_run_can_put_the_cpu_line_back(self):
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", "out.mp4"]
        self.assertEqual(runner._hw_fallback(cmd, STATE), ["ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "-crf", "18", "out.mp4"])
        self.assertIsNone(runner._hw_fallback(["ffmpeg", "-i", "a", "b"], STATE))

    def test_export_preset_keeps_its_frame_rate_and_leaves_faststart_to_export(self):
        STATE.hw = True
        with mock.patch.object(decision, "hw_platform_reason", return_value=None), \
                mock.patch.object(decision, "ffmpeg_encoders", return_value={"h264_videotoolbox"}):
            vt = decision.hw_preset_video(["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
                                           "-pix_fmt", "yuv420p", "-r", "30"], None)
        self.assertEqual(vt[vt.index("-c:v") + 1], "h264_videotoolbox")
        self.assertEqual(vt[vt.index("-r") + 1], "30")
        self.assertNotIn("-movflags", vt)
        self.assertNotIn("-preset", vt)

    def test_render_cache_key_changes_with_the_gpu_setting(self):
        """A VideoToolbox artifact is never served to a CPU run (and the other way round)."""
        import render
        with mock.patch.dict(os.environ, {runner.HW_ENV: "0"}):
            os.environ.pop(runner.HW_FORCED_ENV, None)
            cpu = render.cache_key("fit", "fit.py", ["--height", "720"], [])
        with mock.patch.dict(os.environ, {runner.HW_ENV: "1"}):
            gpu = render.cache_key("fit", "fit.py", ["--height", "720"], [])
        with mock.patch.dict(os.environ, {runner.HW_ENV: "1", runner.HW_FORCED_ENV: "1"}):
            forced = render.cache_key("fit", "fit.py", ["--height", "720"], [])
        self.assertEqual(len({cpu, gpu, forced}), 3)


class HwReviewRegressionTests(unittest.TestCase):
    """Cases a review of the first --hw implementation found."""

    def tearDown(self):
        STATE.reset()

    def _vt_ok(self):
        return (mock.patch.object(decision, "hw_platform_reason", return_value=None),
                mock.patch.object(decision, "ffmpeg_encoders", return_value={"h264_videotoolbox", "hevc_videotoolbox", "prores_videotoolbox"}))

    def test_export_edits_to_a_vt_line_keep_the_fallback_findable(self):
        """export.py strips -movflags from encoder_args()'s line; the swap must follow the edit."""
        STATE.hw = True
        a, b = self._vt_ok()
        with a, b:
            built = decision.encoder_args("hevc", 20, "medium", {"video": {"bt2020_or_hdr": True, "color_transfer": "smpte2084"}})
        stripped = decision.strip_movflags(built)
        decision.restate_last_swap(built, stripped)
        cmd = ["ffmpeg", "-i", "in.mov"] + stripped + ["-movflags", "+faststart", "out.mp4"]
        back = runner._hw_fallback(cmd, STATE)
        self.assertIsNotNone(back)
        self.assertIn("libx265", back)

    def test_export_preset_fallback_is_tagged_like_a_cpu_run(self):
        STATE.hw = True
        a, b = self._vt_ok()
        with a, b:
            decision.hw_preset_video(["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"], None)
        cpu = STATE.hw_swaps[-1][1]
        self.assertTrue("-x264-params" in cpu or "-colorspace" in cpu, cpu)

    def test_vt_bt709_tags_come_from_a_bitstream_filter_on_every_version(self):
        """On FFmpeg >= 7.1 the -colorspace output options insert a real matrix conversion on an
        untagged source, so VideoToolbox gets its tags from a bitstream filter instead. A git build
        of 7.1 reads as (7, 0), so the tag path must not change with the version guess either."""
        for codec in ("h264", "hevc"):
            for v in ((6, 1), (7, 0), (7, 1), (9, 0)):
                with mock.patch.object(decision, "ffmpeg_version", return_value=v):
                    tags = decision._vt_bt709(codec)
                self.assertEqual(tags[0], "-bsf:v", (codec, v))
                self.assertNotIn("-colorspace", tags)
                self.assertNotIn("-x264-params", tags)

    def test_run_retries_a_refused_videotoolbox_encode_on_the_cpu_and_reports_it(self):
        """run() itself: a failed VT encode is re-run once with the recorded CPU line, the note and
        the recorded command follow, and the result reports the CPU encoder."""
        import importlib
        emit = importlib.import_module("_common.emit")
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        refused = subprocess.CompletedProcess([], 1, "", "[vt] Error: cannot encode 8192x4608\n")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(runner, "_execute", side_effect=[refused, ok]) as execute:
            out = str(Path(d) / "o.mp4")
            proc = runner.run(["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", out], quiet=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(execute.call_count, 2)
        retried = execute.call_args_list[1][0][0]
        self.assertIn("libx264", retried)
        self.assertNotIn("h264_videotoolbox", retried)
        self.assertIn("libx264", STATE.commands[-1])
        self.assertTrue(any("VideoToolbox refused" in n and "8192x4608" in n for n in STATE.hw_notes), STATE.hw_notes)
        rep = emit._encoder_report(STATE)
        self.assertEqual(rep["encoder"], "libx264")
        self.assertFalse(rep["hw"]["used"])

    def test_the_cpu_fallback_keeps_the_even_dimension_scale_of_a_retry(self):
        """An odd-sized source under --hw: the encode is retried with an even scale, and when
        VideoToolbox refuses that retry the CPU line is swapped into the retry, not into the
        first command (x264 then failed on the same odd frame)."""
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        odd = subprocess.CompletedProcess([], 1, "", "width not divisible by 2 (641x359)\n")
        refused = subprocess.CompletedProcess([], 1, "", "[vt] Error: session refused\n")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(runner, "_execute", side_effect=[odd, refused, ok]) as execute:
            out = str(Path(d) / "o.mp4")
            proc = runner.run(["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", out], quiet=True)
        self.assertEqual(proc.returncode, 0)
        cpu = execute.call_args_list[2][0][0]
        self.assertIn("libx264", cpu)
        self.assertTrue(any("scale" in a for a in cpu), cpu)
        self.assertIn("scale", STATE.commands[-1])

    def test_encoder_report_keeps_the_encode_behind_a_later_copy(self):
        import importlib
        emit = importlib.import_module("_common.emit")
        STATE.commands = ["ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4", "ffmpeg -i b.mp4 -c:v copy -af loudnorm c.mp4"]
        STATE.hw, STATE.hw_source = True, "flag"
        rep = emit._encoder_report(STATE)
        self.assertEqual(rep["encoder"], "h264_videotoolbox")
        self.assertTrue(rep["hw"]["used"])
        STATE.commands = ["ffmpeg -ss 1 -i a.mp4 -c copy -t 2 b.mp4"]
        self.assertEqual(emit._encoder_report(STATE)["encoder"], "copy")
        STATE.commands = []  # batch.py: the stages are child processes it does not record
        self.assertIsNone(emit._encoder_report(STATE)["hw"]["used"])

    def test_an_env_chosen_gpu_encode_says_how_to_get_the_cpu_one(self):
        """FFMPEG_SKILL_HW=1 puts every tool on VideoToolbox, whose files are larger at the same
        quality; a result says so only when the environment chose the GPU and the GPU ran."""
        import importlib
        emit = importlib.import_module("_common.emit")
        gpu, cpu = "ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4", "ffmpeg -i a -c:v libx264 -crf 18 b.mp4"
        for hw, source, command, noted in [(True, "env", gpu, True), (True, "flag", gpu, False),
                                           (True, "env", cpu, False), (False, None, cpu, False)]:
            with self.subTest(hw=hw, source=source, command=command):
                STATE.hw, STATE.hw_source, STATE.hw_notes, STATE.commands = hw, source, [], [command]
                rep = emit._encoder_report(STATE)
                if not hw:
                    self.assertNotIn("hw", rep)
                    continue
                notes = rep["hw"]["notes"]
                self.assertEqual(any("FFMPEG_SKILL_HW=1" in n and "--no-hw" in n for n in notes), noted, notes)
                self.assertEqual(STATE.hw_notes, [], "the report adds the note; the run's own list is untouched")

    def test_hw_dry_run_runs_no_ffmpeg(self):
        """The dry-run promise: --hw's encoder check reads the build through ffprobe, never ffmpeg."""
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "calls.log"
            fake = Path(d) / "ffmpeg"
            fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nexit 1\n")
            fake.chmod(0o755)
            for tool in ("ffprobe",):
                os.symlink(shutil.which(tool), Path(d) / tool)
            env = dict(os.environ, PATH=f"{d}{os.pathsep}/usr/bin{os.pathsep}/bin")
            runner._ENCODERS = None
            proc = subprocess.run([sys.executable, str(SCRIPTS / "fit.py"), str(OUT / "source.mp4"), "--height", "360", "--hw",
                                   "--dry-run", "--json", "-o", str(Path(d) / "o.mp4")], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(log.exists(), log.read_text() if log.exists() else "")


@unittest.skipUnless(_vt_here(), "VideoToolbox encoders need Apple Silicon and an ffmpeg that lists them")
class VtEncodeTests(MediaFixtures):
    """Real VideoToolbox encodes, probed."""

    def test_hw_encode_reports_itself_and_keeps_an_untagged_source_unconverted(self):
        src = OUT / "vt_untagged.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=1",
           "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "0", src)
        out = OUT / "vt_fit.mp4"
        doc = json.loads(script("fit.py", src, "--height", "360", "--hw", "--json", "-o", out).stdout)
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertEqual(doc["hw"], {"requested": True, "source": "flag", "used": True, "notes": []})
        v = doc["probe"]["video"]
        self.assertEqual((v["color_space"], v["color_primaries"], v["color_transfer"]), ("bt709", "bt709", "bt709"))
        neutral = "setparams=colorspace=unknown:color_primaries=unknown:color_trc=unknown"
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-i", str(src), "-lavfi",
                               f"[0:v]{neutral}[a];[1:v]{neutral}[b];[a][b]psnr", "-f", "null", "-"],
                              stderr=subprocess.PIPE, text=True)
        psnr = float(proc.stderr.split("average:")[1].split()[0])
        self.assertGreater(psnr, 40, "the BT.709 tag turned into a colour conversion (~24 dB)")

    def test_hw_hdr10_side_data_survives(self):
        """PQ + mastering-display + content-light metadata come through hevc_videotoolbox."""
        src = OUT / "vt_hdr10_md.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=1",
           "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1", "-x265-params",
           "log-level=error:hdr10=1:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400",
           "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=16:matrix_coefficients=9", src)
        out = OUT / "vt_hdr10_out.mp4"
        doc = json.loads(script("fit.py", src, "--height", "360", "--hw", "--json", "-o", out).stdout)
        self.assertEqual(doc["encoder"], "hevc_videotoolbox")
        self.assertEqual(doc["probe"]["video"]["color_transfer"], "smpte2084")
        side = sh("ffprobe", "-v", "error", "-select_streams", "v", "-read_intervals", "%+#1", "-show_frames",
                  "-show_entries", "frame_side_data=side_data_type", out).stdout
        self.assertIn("Mastering display metadata", side)
        self.assertIn("Content light level metadata", side)

    def test_a_job_videotoolbox_refuses_falls_back_to_the_cpu_and_says_so(self):
        """H.264 on VideoToolbox stops at 4096 wide; an 8K frame is re-encoded on x264, reported.
        Half a second is enough for the real refusal (the full clip took ~26 s of x264 at 8K)."""
        out = OUT / "vt_8k.mp4"
        doc = json.loads(script("fit.py", self.src, "--duration", "0.5", "--method", "trim", "--width", "8192",
                                "--height", "4608", "--hw", "--fast", "--json", "-o", out).stdout)
        self.assertEqual(doc["encoder"], "libx264")
        self.assertFalse(doc["hw"]["used"])
        self.assertTrue(any("VideoToolbox refused" in n for n in doc["hw"]["notes"]), doc["hw"])

    def test_export_preset_needs_an_explicit_hw(self):
        """The env default leaves a delivery preset on the CPU (a dry run: encoder choice only);
        an explicit --hw export really runs on VideoToolbox and keeps the preset's frame rate."""
        env = dict(os.environ, FFMPEG_SKILL_HW="1")
        doc = json.loads(script("export.py", self.src, "--preset", "x", "--dry-run", "--json",
                                "-o", OUT / "vt_x_env.mp4", env=env).stdout)
        self.assertEqual(doc["encoder"], "libx264")
        doc = json.loads(script("export.py", self.src, "--preset", "x", "--hw", "--json",
                                "-o", OUT / "vt_x_hw.mp4").stdout)
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertTrue(doc["hw"]["used"])
        self.assertEqual(round(doc["probe"]["video"]["fps"]), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
