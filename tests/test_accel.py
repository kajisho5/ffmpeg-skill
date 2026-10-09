#!/usr/bin/env python3
"""Tests for Apple VideoToolbox encoding (--hw).

    python3 tests/test_accel.py          # this group alone
    python3 tests/test_all.py            # every group

The pure-logic cases run everywhere. The real VideoToolbox encodes run only on Apple Silicon with
an ffmpeg that lists the encoders.
"""
import argparse
import contextlib
import importlib
import io
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
import _common  # noqa: E402
from _common import decision, runner  # noqa: E402

emit_module = importlib.import_module("_common.emit")  # the module; `_common.emit` is the function


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


def require_ffmpeg_or_skip(*binaries):
    """As test_contract.py's: locally a skip, in CI (CI=true) a broken install step."""
    missing = [b for b in binaries if not shutil.which(b)]
    if not missing:
        return
    msg = f"{'/'.join(missing)} not on PATH"
    if os.environ.get("CI"):
        raise AssertionError(f"{msg} -- in CI this is a broken install step, not a reason to skip")
    raise unittest.SkipTest(msg)


# What FFmpeg really prints when a VideoToolbox encoder cannot open, one shape per wording
# (fftools/ffmpeg*.c and libavcodec/videotoolboxenc.c of each version; pointers shortened).
VT_OPEN_FAILED = {
    "5.1": "[h264_videotoolbox @ 0x7f9e1c004a00] Error: cannot create compression session: -12902\n"
           "[h264_videotoolbox @ 0x7f9e1c004a00] Try -allow_sw 1. The hardware encoder may be busy, or not supported.\n"
           "Error initializing output stream 0:0 -- Error while opening encoder for output stream #0:0 - maybe "
           "incorrect parameters such as bit_rate, rate, width or height\n",
    "6.0": "[h264_videotoolbox @ 0x14f6063b0] Error: cannot create compression session: -12908\n"
           "[vost#0:0/h264_videotoolbox @ 0x14f605f40] Error initializing output stream: Error while opening encoder "
           "for output stream #0:0 - maybe incorrect parameters such as bit_rate, rate, width or height\n",
    "6.1": "[h264_videotoolbox @ 0x600002d0c000] Error: cannot create compression session: -12902\n"
           "[h264_videotoolbox @ 0x600002d0c000] Try -allow_sw 1. The hardware encoder may be busy, or not supported.\n"
           "[vost#0:0/h264_videotoolbox @ 0x600002d0c1e0] Error while opening encoder - maybe incorrect parameters "
           "such as bit_rate, rate, width or height.\n",
    "7.1": "[hevc_videotoolbox @ 0x13a604a40] Error: -q:v qscale not available for encoder. Use -b:v bitrate instead.\n"
           "[vost#0:0/hevc_videotoolbox @ 0x13a6046a0] Error while opening encoder - maybe incorrect parameters such "
           "as bit_rate, rate, width or height.\n"
           "[vf#0:0 @ 0x13a604e30] Error sending frames to consumers: Generic error in an external library\n",
    "8.0": "[vost#0:0/h264_videotoolbox @ 0x600003a1c0f0] [enc:h264_videotoolbox @ 0x600003a1c1e0] Error while opening "
           "encoder - maybe incorrect parameters such as bit_rate, rate, width or height.\n"
           "[vf#0:0 @ 0x600003a1c3c0] Error sending frames to consumers: Generic error in an external library\n",
    "master": "[prores_videotoolbox @ 0x12e604a40] Cannot create compression session: -12903\n"
              "[vost#0:0/prores_videotoolbox @ 0x12e6046a0] [enc:prores_videotoolbox @ 0x12e604960] Error while opening "
              "encoder - maybe incorrect parameters such as bit_rate, rate, width or height.\n",
    "mid-stream": "[h264_videotoolbox @ 0x7fa1] Error encoding frame: -12911\n"
                  "[vost#0:0/h264_videotoolbox @ 0x7fa2] Error submitting video frame to the encoder\n",
}
# Failures of a VideoToolbox job that are not VideoToolbox's: retrying them on the CPU would run
# the job twice and blame the GPU.
NOT_VT = {
    "missing font (7.x: the encoder never opened)":
        "[Parsed_drawtext_0 @ 0x6000] Cannot find a valid font for the family Sans\n"
        "[AVFilterGraph @ 0x6001] Error initializing filters\n"
        "[vost#0:0/h264_videotoolbox @ 0x6002] Could not open encoder before EOF\n"
        "[vost#0:0/h264_videotoolbox @ 0x6002] Task finished with error code: -22 (Invalid argument)\n",
    "bad filter graph (6.1)":
        "[AVFilterGraph @ 0x7000] No such filter: 'scalee'\n"
        "Error reinitializing filters!\nFailed to inject frame into filter network: Invalid argument\n",
    "full disk after a non-fatal encoder error line":
        "[h264_videotoolbox @ 0x8000] Error setting profile/level property: -12900. Output will be encoded using a "
        "supported profile/level combination.\n"
        "[vost#0:0/h264_videotoolbox @ 0x8001] Error submitting a packet to the muxer: No space left on device\n"
        "[out#0/mp4 @ 0x8002] Error writing trailer: No space left on device\n",
    "the audio encoder failed to open (6.1+)":
        "[h264_videotoolbox @ 0x9000] Error setting entropy property: -12900\n"
        "[aost#0:1/aac @ 0x9001] Error while opening encoder - maybe incorrect parameters such as bit_rate, rate, "
        "width or height.\n",
    "a missing input": "a.mp4: No such file or directory\n",
}


class FakeFfmpeg:
    """A stand-in ffmpeg for run(): an `ffmpeg` (POSIX sh) or `ffmpeg.cmd` (Windows) wrapper that
    runs a Python script with this interpreter, so the same fake works on every CI runner. Each
    call is logged; a command naming a *_videotoolbox encoder gets the `vt` behaviour, any other
    the `cpu` one: {"rc", "stderr"}, or {"real": "<ffmpeg path>"} to hand the command to a real
    ffmpeg (the CPU encode then writes a real, probe-able file)."""

    def __init__(self, directory: Path, behaviour):
        self.dir = Path(directory)
        self.log = self.dir / "calls.jsonl"
        conf = self.dir / "fake_ffmpeg.json"
        conf.write_text(json.dumps(behaviour), encoding="utf-8")
        body = self.dir / "fake_ffmpeg.py"
        body.write_text(
            "import json, subprocess, sys\n"
            f"conf = json.load(open({str(conf)!r}, encoding='utf-8'))\n"
            "args = sys.argv[1:]\n"
            f"with open({str(self.log)!r}, 'a', encoding='utf-8') as fh:\n"
            "    fh.write(json.dumps(args) + '\\n')\n"
            "do = conf['vt' if any(a.endswith('_videotoolbox') for a in args) else 'cpu']\n"
            "if 'real' in do:\n"
            "    sys.exit(subprocess.run([do['real']] + args).returncode)\n"
            "sys.stderr.write(do.get('stderr', ''))\n"
            "sys.exit(do.get('rc', 0))\n", encoding="utf-8")
        if os.name == "nt":
            self.path = self.dir / "ffmpeg.cmd"
            self.path.write_text(f'@"{sys.executable}" "{body}" %*\r\n@exit /b %ERRORLEVEL%\r\n', encoding="utf-8")
        else:
            self.path = self.dir / "ffmpeg"
            self.path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n', encoding="utf-8")
            self.path.chmod(0o755)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _vt_available():
    """VideoToolbox as an Apple Silicon build would report it, on any runner: the platform check
    passes and the encoder list has the VideoToolbox (and CPU) encoders."""
    return (mock.patch.object(decision, "hw_platform_reason", return_value=None),
            mock.patch.object(decision, "ffmpeg_encoders", return_value={
                "h264_videotoolbox", "hevc_videotoolbox", "prores_videotoolbox", "libx264", "libx265", "prores_ks"}))


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
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["6.1"])
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
        self.assertTrue(any("VideoToolbox refused" in n and "cannot create compression session" in n for n in STATE.hw_notes),
                        STATE.hw_notes)
        rep = emit._encoder_report(STATE)
        self.assertEqual(rep["encoder"], "libx264")
        self.assertFalse(rep["hw"]["used"])
        self.assertTrue(rep["hw"]["fallback"])

    def test_the_cpu_fallback_keeps_the_even_dimension_scale_of_a_retry(self):
        """An odd-sized source under --hw: the encode is retried with an even scale, and when
        VideoToolbox refuses that retry the CPU line is swapped into the retry, not into the
        first command (x264 then failed on the same odd frame)."""
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        odd = subprocess.CompletedProcess([], 1, "", "width not divisible by 2 (641x359)\n")
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["8.0"])
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
        """The dry-run promise: --hw's encoder check reads the build through ffprobe, never ffmpeg.
        (On a machine without VideoToolbox the check is never reached; EncoderListTests pins the
        ffprobe-only-in-a-dry-run rule itself on every runner.)"""
        require_ffmpeg_or_skip("ffprobe")
        with tempfile.TemporaryDirectory() as d:
            fake = FakeFfmpeg(Path(d), {"vt": {"rc": 1, "stderr": "called\n"}, "cpu": {"rc": 1, "stderr": "called\n"}})
            env = dict(os.environ, PATH=f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
            proc = subprocess.run([sys.executable, str(SCRIPTS / "fit.py"), str(Path(d) / "pending.mp4"), "--height", "360", "--hw",
                                   "--dry-run", "--json", "-o", str(Path(d) / "o.mp4")], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(fake.calls(), [])


class VideoToolboxFailureTests(unittest.TestCase):
    """Which ffmpeg failures run() retries on the CPU: only VideoToolbox's own (review of #304)."""

    def test_every_ffmpeg_version_s_videotoolbox_open_failure_is_recognised(self):
        for version, stderr in VT_OPEN_FAILED.items():
            with self.subTest(version=version):
                line = runner.videotoolbox_failure(stderr)
                self.assertIsNotNone(line, stderr)
                self.assertIn("videotoolbox", line)
                self.assertNotIn("0x", line, "log-context pointers are dropped from the note")

    def test_a_failure_that_is_not_videotoolbox_s_is_not(self):
        for case, stderr in NOT_VT.items():
            with self.subTest(case=case):
                self.assertIsNone(runner.videotoolbox_failure(stderr))


class EncoderListTests(unittest.TestCase):
    """ffmpeg_encoders() reads the build that encodes (`ffmpeg -encoders`); `ffprobe -encoders`
    only under --dry-run, which promises never to run ffmpeg (review of #304: on a mixed install
    ffprobe's list is another build's, and the AV1/ProRes checks read it too)."""

    def setUp(self):
        runner._ENCODERS = None

    def tearDown(self):
        runner._ENCODERS = None
        STATE.reset()

    def _read(self, dry_run):
        STATE.dry_run = dry_run
        listing = " V....D libsvtav1            SVT-AV1\n V....D h264_videotoolbox    VideoToolbox H.264 Encoder\n"
        with mock.patch.object(runner.shutil, "which", side_effect=lambda name: os.path.join("bin", name)), \
                mock.patch.object(runner.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, listing, "")) as call:
            names = runner.ffmpeg_encoders()
        return os.path.basename(call.call_args[0][0][0]), names

    def test_a_real_run_reads_ffmpeg_s_own_list(self):
        tool, names = self._read(dry_run=False)
        self.assertEqual(tool, "ffmpeg")
        self.assertEqual(names, {"libsvtav1", "h264_videotoolbox"})

    def test_only_a_dry_run_reads_ffprobe_s(self):
        tool, _names = self._read(dry_run=True)
        self.assertEqual(tool, "ffprobe")


class HwEverywhereTests(unittest.TestCase):
    """The --hw decisions on every CI runner, VideoToolbox or not: the platform check and the
    encoder list are stood in for (_vt_available), the encodes are a fake ffmpeg that fails the
    VideoToolbox command the way FFmpeg does and hands the CPU one to the real ffmpeg."""

    @classmethod
    def setUpClass(cls):
        require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        cls.real_ffmpeg = shutil.which("ffmpeg")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.src = Path(cls.tmp.name) / "src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
           "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", cls.src)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        STATE.reset()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for k in (runner.HW_ENV, runner.HW_FORCED_ENV):
            os.environ.pop(k, None)
        self.work = Path(tempfile.mkdtemp(dir=self.tmp.name))

    def tearDown(self):
        self._env.stop()
        STATE.reset()

    def _tool(self, module_name, *argv, env=None):
        """Run a tool's main() in this process (so _vt_available() applies) and parse its --json."""
        import importlib
        module = importlib.import_module(module_name)
        out, err = io.StringIO(), io.StringIO()
        a, b = _vt_available()
        with a, b, mock.patch.dict(os.environ, env or {}), \
                mock.patch.object(sys, "argv", [module_name + ".py"] + [str(x) for x in argv] + ["--json"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            STATE.reset()
            try:
                module.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0, err.getvalue())
        return json.loads(out.getvalue())

    def test_export_preset_needs_an_explicit_hw(self):
        """docs/design-decisions.md: FFMPEG_SKILL_HW=1 leaves export.py's delivery presets on x264 (a
        dry run: the encoder choice), says so, and --hw -- or render.py --hw's explicit marker --
        puts the same preset on VideoToolbox, so the platform stand-in is not what kept it off."""
        out = self.work / "x.mp4"
        doc = self._tool("export", self.src, "--preset", "x", "--dry-run", "-o", out, env={runner.HW_ENV: "1"})
        self.assertEqual(doc["encoder"], "libx264")
        self.assertNotIn("videotoolbox", " ".join(doc["commands"]))
        self.assertEqual({k: doc["hw"][k] for k in ("requested", "source", "used", "fallback")},
                         {"requested": False, "source": "env", "used": False, "fallback": False})
        self.assertTrue(any("--hw" in n and "FFMPEG_SKILL_HW=1" in n for n in doc["hw"]["notes"]), doc["hw"])
        self.assertFalse(any("CRF-equivalent" in n for n in doc.get("notes") or []))
        for argv, env in ((["--hw"], {}), ([], {runner.HW_ENV: "1", runner.HW_FORCED_ENV: "1"})):
            with self.subTest(argv=argv, env=env):
                doc = self._tool("export", self.src, "--preset", "x", "--dry-run", "-o", out, *argv, env=env)
                self.assertEqual(doc["encoder"], "h264_videotoolbox")
                self.assertTrue(doc["hw"]["used"])
                self.assertTrue(any("not CRF-equivalent" in n for n in doc["notes"]), doc.get("notes"))

    def test_the_env_default_reaches_the_other_re_encoding_tools(self):
        doc = self._tool("fit", self.src, "--height", "120", "--dry-run", "-o", self.work / "f.mp4", env={runner.HW_ENV: "1"})
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertEqual((doc["hw"]["requested"], doc["hw"]["source"], doc["hw"]["used"]), (True, "env", True))
        self.assertTrue(any("--no-hw" in n for n in doc["hw"]["notes"]))
        doc = self._tool("fit", self.src, "--height", "120", "--dry-run", "-o", self.work / "f.mp4")
        self.assertEqual(doc["encoder"], "libx264", "never automatic: no flag, no variable, no GPU")
        self.assertNotIn("hw", doc)

    def test_a_batch_row_names_the_encoder_its_steps_ran(self):
        """batch.py encodes nothing itself (its top-level hw.used is null); each item's row carries
        the encoder its steps ran, and `hw` only when VideoToolbox was asked for."""
        folder = self.work / "batch"
        folder.mkdir()
        (folder / "a.mp4").write_bytes(self.src.read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_b",
                                      "steps": [["fit.py", "{in}", "--height", "120", "-o", "{out}"]]}), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), str(folder), "--recipe", str(recipe), "--fast", "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = json.loads(proc.stdout)["results"][0]
        self.assertEqual(row["encoder"], "libx264")
        self.assertNotIn("hw", row)

    def _run_encode(self, fake):
        """What a re-encoding tool does: the encoder line from video_args() (VideoToolbox under
        --hw, the swap recorded), one ffmpeg command, run(), emit()."""
        STATE.hw, STATE.hw_source, STATE.json = True, "flag", True
        a, b = _vt_available()
        with a, b:
            video = decision.video_args(_common.probe(str(self.src)), 23, "ultrafast")
        self.assertEqual(video[video.index("-c:v") + 1], "h264_videotoolbox")
        out = self.work / "o.mp4"
        cmd = [str(fake.path), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(self.src), "-t", "0.5"] + video + ["-an", str(out)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                runner.run(cmd)
                emit_module.emit(str(out))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_a_videotoolbox_open_failure_is_re_encoded_on_the_cpu_and_reported(self):
        fake = FakeFfmpeg(self.work, {"vt": {"rc": 187, "stderr": VT_OPEN_FAILED["6.1"]}, "cpu": {"real": self.real_ffmpeg}})
        code, doc, _err = self._run_encode(fake)
        self.assertEqual(code, 0, doc)
        calls = fake.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertIn("h264_videotoolbox", calls[0])
        self.assertIn("libx264", calls[1])
        self.assertNotIn("h264_videotoolbox", calls[1])
        self.assertTrue(doc["verified"], "verified is the probe of what the CPU wrote")
        self.assertEqual(doc["probe"]["video"]["codec"], "h264")
        self.assertEqual(doc["encoder"], "libx264")
        self.assertIn("libx264", doc["commands"][-1])
        self.assertEqual((doc["hw"]["used"], doc["hw"]["fallback"]), (False, True))
        self.assertTrue(any("VideoToolbox refused" in n and "cannot create compression session" in n
                            for n in doc["hw"]["notes"]), doc["hw"])
        self.assertFalse(any("CRF-equivalent" in n for n in doc.get("notes") or []), "the file is the CPU encode")

    def test_a_failure_that_is_not_videotoolbox_s_is_not_retried_and_names_the_command_that_ran(self):
        fake = FakeFfmpeg(self.work, {"vt": {"rc": 234, "stderr": NOT_VT["missing font (7.x: the encoder never opened)"]},
                                      "cpu": {"real": self.real_ffmpeg}})
        code, doc, _err = self._run_encode(fake)
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.calls()), 1, "a missing font is not the GPU's: one run, no CPU retry")
        self.assertEqual(doc["error"]["kind"], "ffmpeg")
        self.assertIn("h264_videotoolbox", doc["error"]["message"])
        self.assertIn("not retried on the CPU", doc["error"]["message"])
        self.assertIn("Cannot find a valid font", doc["error"]["message"])
        self.assertIn("h264_videotoolbox", doc["commands"][-1])
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertEqual((doc["hw"]["used"], doc["hw"]["fallback"]), (True, False))
        self.assertFalse(any("VideoToolbox refused" in n for n in doc["hw"]["notes"]), doc["hw"])

    def test_when_the_cpu_retry_fails_too_the_error_is_the_cpu_command_s(self):
        fake = FakeFfmpeg(self.work, {"vt": {"rc": 187, "stderr": VT_OPEN_FAILED["5.1"]},
                                      "cpu": {"rc": 1, "stderr": "[libx264 @ 0x55d] broken CPU encode\n"}})
        code, doc, _err = self._run_encode(fake)
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.calls()), 2)
        message = doc["error"]["message"]
        self.assertIn("libx264, the CPU retry after VideoToolbox refused the job", message)
        self.assertIn("broken CPU encode", message)
        self.assertNotIn("compression session", message, "the stderr is the command's that ran last")
        self.assertIn("libx264", doc["commands"][-1])
        self.assertEqual((doc["encoder"], doc["hw"]["used"], doc["hw"]["fallback"]), ("libx264", False, True))


class HwResultTests(unittest.TestCase):
    """What a result says about a GPU encode (review of #304: two encoders, one quality scale)."""

    def tearDown(self):
        STATE.reset()

    def _doc(self, commands, hw=True):
        STATE.reset()
        STATE.hw, STATE.hw_source, STATE.json, STATE.dry_run = hw, ("flag" if hw else None), True, True
        STATE.commands = list(commands)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            emit_module.emit("planned.mp4")
        return json.loads(out.getvalue())

    def test_a_gpu_encode_notes_that_its_quality_is_not_crf_equivalent(self):
        doc = self._doc(["ffmpeg -i a.mp4 -c:v h264_videotoolbox -q:v 64 -pix_fmt yuv420p out.mp4"])
        notes = [n for n in doc["notes"] if "not CRF-equivalent" in n]
        self.assertEqual(len(notes), 1, doc["notes"])
        self.assertIn("h264_videotoolbox -q:v 64", notes[0])
        self.assertIn("--no-hw", notes[0])
        doc = self._doc(["ffmpeg -i a.mov -c:v prores_videotoolbox -profile:v hq out.mov"])
        self.assertTrue(any(n.startswith("prores_videotoolbox is not prores_ks") for n in doc["notes"]), doc["notes"])
        for commands, hw in ((["ffmpeg -i a.mp4 -c:v libx264 -crf 23 out.mp4"], True),
                             (["ffmpeg -i a.mp4 -c:v libx264 -crf 23 out.mp4"], False)):
            self.assertNotIn("notes", self._doc(commands, hw))

    def test_verified_is_the_measured_output_whatever_the_encoder(self):
        """`verified` is the probe (and the tool's own measured steps), never a property of the
        encoder line: the same file verifies the same under a VideoToolbox command line."""
        require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.mp4"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30",
               "-t", "0.3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out)
            docs = []
            for enc in ("h264_videotoolbox -q:v 64", "libx264 -crf 23"):
                STATE.reset()
                STATE.hw, STATE.hw_source, STATE.json = True, "flag", True
                STATE.commands = [f"ffmpeg -i a.mp4 -c:v {enc} {out}"]
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    emit_module.emit(str(out))
                docs.append(json.loads(buf.getvalue()))
        for doc in docs:
            self.assertTrue(doc["verified"])
            self.assertEqual(doc["verification"], [{"step": "probe", "ok": True}])
        self.assertEqual(docs[0]["probe"], docs[1]["probe"])

    def test_a_batch_item_s_steps_report_their_gpu_facts_once(self):
        fit = {"encoder": "h264_videotoolbox", "commands": ["ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4"],
               "hw": {"requested": True, "source": "env", "used": True, "fallback": False, "notes": [emit_module.ENV_HW_NOTE]}}
        loud = {"encoder": "copy", "commands": ["ffmpeg -i b.mp4 -c:v copy -af loudnorm c.mp4"]}
        rep = emit_module.steps_encoder_report([("fit", fit), ("loudness", loud)])
        self.assertEqual(rep["encoder"], "h264_videotoolbox", "a later stream copy keeps the encode before it")
        self.assertEqual({k: rep["hw"][k] for k in ("requested", "source", "used", "fallback")},
                         {"requested": True, "source": "env", "used": True, "fallback": False})
        self.assertEqual(sum(n.endswith(emit_module.ENV_HW_NOTE) for n in rep["hw"]["notes"]), 1, rep["hw"]["notes"])
        self.assertTrue(any("not CRF-equivalent" in n for n in rep["notes"]))
        self.assertEqual(emit_module.steps_encoder_report([("fit", {"encoder": "libx264"})]), {"encoder": "libx264"})

    def test_render_carries_a_stage_s_fallback_and_gpu_quality_note(self):
        """render.py runs each stage as a child process and keeps only its command lines; the
        stage's `hw` facts (fell back and why, ran on VideoToolbox) reach render's own result."""
        STATE.reset()
        STATE.json, STATE.dry_run = True, True
        fit = {"encoder": "libx264", "commands": ["ffmpeg -i a -c:v libx264 -crf 18 b.mp4"],
               "hw": {"requested": True, "source": "env", "used": False, "fallback": True,
                      "notes": ["VideoToolbox refused the encode: [h264_videotoolbox] Error: cannot create compression session: -12902; re-encoded on the CPU"]}}
        cap = {"encoder": "h264_videotoolbox", "commands": ["ffmpeg -i b.mp4 -c:v h264_videotoolbox -q:v 75 c.mp4"],
               "hw": {"requested": True, "source": "env", "used": True, "fallback": False, "notes": [emit_module.ENV_HW_NOTE]}}
        exp = {"encoder": "libx264", "commands": ["ffmpeg -i c.mp4 -c:v libx264 -crf 18 d.mp4"],
               "hw": {"requested": False, "source": "env", "used": False, "fallback": False, "notes": [emit_module.ENV_NOT_FOR_DELIVERY_NOTE]}}
        for stage, doc in (("fit", fit), ("caption", cap), ("export", exp)):
            emit_module.absorb_stage_hw(stage, doc)
            STATE.commands += doc["commands"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            emit_module.emit("d.mp4")
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["encoder"], "libx264")
        self.assertEqual({k: doc["hw"][k] for k in ("requested", "source", "used", "fallback")},
                         {"requested": True, "source": "env", "used": False, "fallback": True})
        self.assertTrue(any(n.startswith("fit: VideoToolbox refused") for n in doc["hw"]["notes"]), doc["hw"])
        self.assertTrue(any(n.startswith("caption: ") and "FFMPEG_SKILL_HW=1" in n for n in doc["hw"]["notes"]))
        self.assertTrue(any("h264_videotoolbox -q:v 75 is not CRF-equivalent" in n for n in doc["notes"]), doc.get("notes"))


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

    def test_export_with_hw_really_runs_on_videotoolbox(self):
        """An explicit --hw export really runs on VideoToolbox and keeps the preset's frame rate
        (the env-default half of the decision is pinned on every runner by
        HwEverywhereTests.test_export_preset_needs_an_explicit_hw)."""
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
