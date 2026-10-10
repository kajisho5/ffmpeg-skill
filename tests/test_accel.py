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
    "the audio encoder failed to open (5.1: no stream context, a non-fatal VideoToolbox line before it)":
        "[h264_videotoolbox @ 0x9000] Error setting entropy property: -12900\n"
        "Error initializing output stream 0:1 -- Error while opening encoder for output stream #0:1 - maybe "
        "incorrect parameters such as bit_rate, rate, width or height\n",
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
            # text mode writes the CRLF line ends cmd.exe expects; run() starts a .cmd directly
            # (CreateProcess runs it through cmd.exe), and the arguments here have no cmd metacharacters
            self.path.write_text(f'@"{sys.executable}" "{body}" %*\n@exit /b %ERRORLEVEL%\n', encoding="utf-8")
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
            line = decision.hw_preset_video(["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"], hdr, bt709=True)
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
                                           "-pix_fmt", "yuv420p", "-r", "30"], None, bt709=True)
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
            decision.hw_preset_video(["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"], None, bt709=True)
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

    def test_a_failed_cpu_retry_does_not_claim_a_re_encode_and_a_repeat_refusal_is_noted_once(self):
        """The note is written from the retry's outcome: a document for a job whose CPU retry also
        failed must not say it was re-encoded, and a job of many encodes names the refusal once."""
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["6.1"])
        broken = subprocess.CompletedProcess([], 1, "", "broken")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "o.mp4")
            cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", out]
            with mock.patch.object(runner, "_execute", side_effect=[refused, broken]):
                proc = runner.run(cmd, quiet=True, check=False)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(STATE.hw_fallback, "fallback means a job was re-encoded on the CPU; this one was not")
            self.assertEqual(len(STATE.hw_notes), 1)
            self.assertIn("the CPU retry failed too", STATE.hw_notes[0])
            self.assertNotIn("re-encoded on the CPU", STATE.hw_notes[0])
            STATE.hw_notes, STATE.hw_fallback = [], False
            with mock.patch.object(runner, "_execute", side_effect=[refused, ok, refused, ok]):
                runner.run(cmd, quiet=True)
                runner.run(cmd, quiet=True)
            self.assertTrue(STATE.hw_fallback)
            self.assertEqual(len(STATE.hw_notes), 1, STATE.hw_notes)
            self.assertTrue(STATE.hw_notes[0].endswith("re-encoded on the CPU"))

    def test_a_cpu_retry_that_times_out_leaves_no_claim_that_it_re_encoded(self):
        """A timeout exits from inside the retry, before any outcome exists: the note stays the
        neutral "retrying" line and fallback stays false."""
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["6.1"])
        with tempfile.TemporaryDirectory() as d:
            cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", str(Path(d) / "o.mp4")]
            with mock.patch.object(runner, "_execute", side_effect=[refused, SystemExit(124)]), \
                    self.assertRaises(SystemExit):
                runner.run(cmd, quiet=True)
        self.assertFalse(STATE.hw_fallback)
        self.assertEqual(len(STATE.hw_notes), 1, STATE.hw_notes)
        self.assertTrue(STATE.hw_notes[0].endswith("; retrying on the CPU encoder"), STATE.hw_notes)

    def test_a_later_success_replaces_an_earlier_failed_retry_for_the_same_refusal(self):
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["6.1"])
        broken = subprocess.CompletedProcess([], 1, "", "broken")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as d:
            cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", str(Path(d) / "o.mp4")]
            with mock.patch.object(runner, "_execute", side_effect=[refused, broken]):
                runner.run(cmd, quiet=True, check=False)
            with mock.patch.object(runner, "_execute", side_effect=[refused, ok]):
                runner.run(cmd, quiet=True)
        self.assertTrue(STATE.hw_fallback)
        self.assertEqual(len(STATE.hw_notes), 1, STATE.hw_notes)
        self.assertTrue(STATE.hw_notes[0].endswith("re-encoded on the CPU"), STATE.hw_notes)

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


class _RealFfmpegCase(unittest.TestCase):
    """A 1 s source made with the real ffmpeg, a work directory, and no GPU variables leaking in."""

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


class HwEverywhereTests(_RealFfmpegCase):
    """The --hw decisions on every CI runner, VideoToolbox or not: the platform check and the
    encoder list are stood in for (_vt_available), the encodes are a fake ffmpeg that fails the
    VideoToolbox command the way FFmpeg does and hands the CPU one to the real ffmpeg."""

    def test_export_preset_needs_an_explicit_hw(self):
        """docs/design-decisions.md: FFMPEG_SKILL_HW=1 leaves export.py's delivery presets on x264 (a
        dry run: the encoder choice), says so, and --hw -- or render.py --hw's explicit marker --
        puts the same preset on VideoToolbox, so the platform stand-in is not what kept it off."""
        out = self.work / "x.mp4"
        doc = self._tool("export", self.src, "--preset", "x", "--dry-run", "-o", out, env={runner.HW_ENV: "1"})
        self.assertEqual(doc["encoder"], "libx264")
        self.assertNotIn("videotoolbox", " ".join(doc["commands"]))
        self.assertEqual({k: doc["hw"][k] for k in ("requested", "source", "used", "fallback")},
                         {"requested": False, "source": "env", "used": None, "fallback": False}, "a dry run: nothing ran")
        self.assertTrue(any("--hw" in n and "FFMPEG_SKILL_HW=1" in n for n in doc["hw"]["notes"]), doc["hw"])
        self.assertFalse(any("CRF-equivalent" in n for n in doc.get("notes") or []))
        for argv, env in ((["--hw"], {}), ([], {runner.HW_ENV: "1", runner.HW_FORCED_ENV: "1"})):
            with self.subTest(argv=argv, env=env):
                doc = self._tool("export", self.src, "--preset", "x", "--dry-run", "-o", out, *argv, env=env)
                self.assertEqual(doc["encoder"], "h264_videotoolbox", "the planned encoder")
                self.assertIsNone(doc["hw"]["used"], "a dry run ran nothing")
                self.assertTrue(any("not CRF-equivalent" in n for n in doc["notes"]), doc.get("notes"))

    def test_the_env_default_reaches_the_other_re_encoding_tools(self):
        doc = self._tool("fit", self.src, "--height", "120", "--dry-run", "-o", self.work / "f.mp4", env={runner.HW_ENV: "1"})
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertEqual((doc["hw"]["requested"], doc["hw"]["source"], doc["hw"]["used"]), (True, "env", None))
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
        self.assertEqual((doc["encoder"], doc["hw"]["used"], doc["hw"]["fallback"]), ("libx264", False, False))
        self.assertTrue(any(n.endswith("the CPU retry failed too") for n in doc["hw"]["notes"]), doc["hw"])


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

    def test_the_export_note_advises_hw_only_where_hw_can_run(self):
        """export.py under FFMPEG_SKILL_HW=1 stays on the CPU and says so; "pass --hw" is advice for
        a machine that can take the GPU, not for a Linux box that would report the CPU encode."""
        STATE.reset()
        STATE.hw_env_ignored = True
        with mock.patch.object(decision, "hw_platform_reason", return_value=None):
            notes = emit_module.hw_report(STATE, "libx264")["notes"]
        self.assertEqual(notes, [emit_module.ENV_NOT_FOR_DELIVERY_NOTE])
        self.assertIn("pass --hw", notes[0])
        with mock.patch.object(decision, "hw_platform_reason", return_value="VideoToolbox is macOS-only"):
            notes = emit_module.hw_report(STATE, "libx264")["notes"]
        self.assertEqual(notes, [emit_module.ENV_NOT_FOR_DELIVERY_BASE])
        self.assertNotIn("--hw", notes[0])

    def test_render_carries_a_stage_s_fallback_and_gpu_quality_note(self):
        """render.py runs each stage as a child process and keeps only its command lines; the
        stage's `hw` facts (fell back and why, ran on VideoToolbox) reach render's own result."""
        STATE.reset()
        STATE.json = True
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
            emit_module.emit(None)  # a real run's document (no file here to probe)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["encoder"], "libx264")
        self.assertEqual({k: doc["hw"][k] for k in ("requested", "source", "used", "fallback")},
                         {"requested": True, "source": "env", "used": False, "fallback": True})
        self.assertTrue(any(n.startswith("fit: VideoToolbox refused") for n in doc["hw"]["notes"]), doc["hw"])
        self.assertTrue(any(n.startswith("caption: ") and "FFMPEG_SKILL_HW=1" in n for n in doc["hw"]["notes"]))
        self.assertTrue(any("h264_videotoolbox -q:v 75 is not CRF-equivalent" in n for n in doc["notes"]), doc.get("notes"))


class TakeoverReviewTests(unittest.TestCase):
    """Cases the reviews of the #304 takeover found, at the unit level."""

    def setUp(self):
        STATE.reset()

    def tearDown(self):
        STATE.reset()

    def test_the_prores_preset_s_cpu_fallback_keeps_the_source_s_tags(self):
        """export.py tags every fixed preset's CPU line BT.709 except prores, whose master keeps
        the source's tags; the CPU line recorded for a refused VideoToolbox job must be the one
        export would have written (it tagged an HLG master BT.709 and still verified)."""
        STATE.hw = True
        prores = ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"]
        hdr = {"video": {"bt2020_or_hdr": True, "color_space": "bt2020nc", "color_primaries": "bt2020",
                         "color_transfer": "arib-std-b67"}}
        a, b = _vt_available()
        with a, b:
            vt = decision.hw_preset_video(list(prores), hdr, bt709=False)
        self.assertEqual(vt[vt.index("-c:v") + 1], "prores_videotoolbox")
        self.assertEqual(STATE.hw_swaps[-1][1], prores)

    def test_an_h265_preset_on_an_hdr_source_stays_the_preset_s_8_bit_bt709_format(self):
        """The CPU h265 preset writes 8-bit with BT.709 tags whatever the source (and notes that
        it did not convert HDR); the VideoToolbox line must write the same format, not the Main10
        HLG line, so the GPU file and its CPU fallback are the same kind of file."""
        STATE.hw = True
        h265 = ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        hdr = {"video": {"bt2020_or_hdr": True, "color_space": "bt2020nc", "color_primaries": "bt2020",
                         "color_transfer": "arib-std-b67"}}
        a, b = _vt_available()
        with a, b:
            vt = decision.hw_preset_video(list(h265), hdr, bt709=True)
        self.assertEqual(vt[vt.index("-c:v") + 1], "hevc_videotoolbox")
        self.assertEqual(vt[vt.index("-pix_fmt") + 1], "yuv420p")
        self.assertNotIn("main10", vt)
        self.assertNotIn("arib-std-b67", vt)
        self.assertIn("hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1", vt)
        self.assertEqual(vt[vt.index("-q:v") + 1], str(decision.vt_quality("hevc", 24)), "the SDR HEVC curve: x265 8-bit at CRF 24")

    def test_export_s_in_place_movflags_edit_is_restated_in_the_recorded_swap(self):
        """export.py deletes -movflags from encoder_args()'s list in place; the recorded VideoToolbox
        slice is a copy, so restate_last_swap() sees the line as built and the CPU fallback line
        loses its -movflags too (export adds +faststart once, after the encoder line)."""
        STATE.hw = True
        a, b = _vt_available()
        with a, b:
            video = decision.encoder_args("hevc", 20, "medium", {"video": {"bt2020_or_hdr": True, "color_transfer": "smpte2084"}})
        as_built = list(video)
        while "-movflags" in video:                      # export.py's own edit, in place
            i = video.index("-movflags")
            del video[i:i + 2]
        decision.restate_last_swap(as_built, video)
        vt, cpu = STATE.hw_swaps[-1]
        self.assertEqual(vt, video)
        self.assertNotIn("-movflags", cpu)
        back = runner._hw_fallback(["ffmpeg", "-i", "in.mov"] + video + ["-movflags", "+faststart", "out.mp4"], STATE)
        self.assertIn("libx265", back)
        self.assertEqual(back.count("-movflags"), 1, back)

    def test_an_odd_sized_job_videotoolbox_refused_gets_the_even_scale_on_the_cpu(self):
        """VideoToolbox refused the job before anything reported the odd size; the CPU retry then
        fails with x264's "not divisible by 2", and gets the even scale a CPU-only run gets."""
        STATE.hw, STATE.hw_source = True, "flag"
        STATE.hw_swaps = [(["-c:v", "h264_videotoolbox", "-q:v", "75"], ["-c:v", "libx264", "-crf", "18"])]
        refused = subprocess.CompletedProcess([], 1, "", VT_OPEN_FAILED["6.1"])
        odd = subprocess.CompletedProcess([], 1, "", "[libx264 @ 0x1] width not divisible by 2 (321x241)\n")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(runner, "_execute", side_effect=[refused, odd, ok]) as execute:
            proc = runner.run(["ffmpeg", "-i", "a.mp4", "-c:v", "h264_videotoolbox", "-q:v", "75", str(Path(d) / "o.mp4")], quiet=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(execute.call_count, 3)
        last = execute.call_args_list[2][0][0]
        self.assertIn("libx264", last)
        self.assertTrue(any(runner.EVEN_SCALE in a for a in last), last)
        self.assertIn("libx264", STATE.commands[-1])
        self.assertIn(runner.EVEN_SCALE, STATE.commands[-1])
        self.assertTrue(STATE.hw_fallback)

    def test_a_dry_run_reports_the_planned_encoder_and_no_used(self):
        """`used` says what ran; under --dry-run nothing did, so it is null while `encoder` names
        the planned encoder. The FFMPEG_SKILL_HW note still tells a planner what the GPU costs."""
        STATE.hw, STATE.hw_source, STATE.dry_run = True, "env", True
        STATE.commands = ["ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4"]
        rep = emit_module._encoder_report(STATE)
        self.assertEqual(rep["encoder"], "h264_videotoolbox")
        self.assertIsNone(rep["hw"]["used"])
        self.assertFalse(rep["hw"]["fallback"])
        self.assertTrue(any(n.endswith(emit_module.ENV_HW_NOTE) for n in rep["hw"]["notes"]))
        STATE.dry_run = False
        self.assertTrue(emit_module._encoder_report(STATE)["hw"]["used"])
        STATE.dry_run = True                       # batch.py's rows: the steps' documents, re-read
        rows = emit_module.steps_encoder_report([("fit", {"encoder": "h264_videotoolbox", "hw": {
            "requested": True, "source": "env", "used": None, "fallback": False, "notes": []}})])
        self.assertIsNone(rows["hw"]["used"])

    def test_an_export_only_row_names_the_variable_as_its_source(self):
        """A batch row whose only step is export.py under FFMPEG_SKILL_HW=1 (requested false,
        source env): the row's `source` is the stage's, not null."""
        exp = {"encoder": "libx264", "hw": {"requested": False, "source": "env", "used": False, "fallback": False,
                                            "notes": [emit_module.ENV_NOT_FOR_DELIVERY_NOTE]}}
        rep = emit_module.steps_encoder_report([("export", exp)])
        self.assertEqual((rep["hw"]["requested"], rep["hw"]["source"]), (False, "env"))

    def test_a_tool_s_own_ffmpeg_failure_carries_encoder_and_hw(self):
        """cut.py runs run(check=False) and dies itself (kind ffmpeg): under --hw that failure carries
        `encoder` and `hw` like run()'s own, and without --hw it carries neither (unchanged)."""
        for hw in (True, False):
            with self.subTest(hw=hw):
                STATE.reset()
                STATE.hw, STATE.hw_source, STATE.json = hw, ("flag" if hw else None), True
                STATE.commands = ["ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4" if hw else "ffmpeg -i a -c:v libx264 b.mp4"]
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit):
                    emit_module.die("ffmpeg failed:\nboom", kind="ffmpeg")
                doc = json.loads(out.getvalue())
                if hw:
                    self.assertEqual(doc["encoder"], "h264_videotoolbox")
                    self.assertEqual((doc["hw"]["requested"], doc["hw"]["used"]), (True, True))
                else:
                    self.assertNotIn("encoder", doc)
                    self.assertNotIn("hw", doc)
        STATE.reset()
        STATE.hw, STATE.hw_source, STATE.json = True, "flag", True
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            emit_module.die("bad input", kind="input")
        self.assertNotIn("hw", json.loads(out.getvalue()), "only a kind: ffmpeg failure carries it")

    def test_render_s_failed_stage_keeps_its_encoder_and_the_earlier_stages_fallback(self):
        """render.py re-raises a failed stage: the stage's `encoder` and `hw`, and a fallback an
        earlier stage reported, reach render's own failure document."""
        import render
        STATE.json = True
        emit_module.absorb_stage_hw("fit", {"encoder": "libx264", "hw": {
            "requested": True, "source": "flag", "used": False, "fallback": True,
            "notes": ["VideoToolbox refused the encode: [h264_videotoolbox] Error: cannot create compression session: -12902; re-encoded on the CPU"]}})
        failed = {"status": "failed", "exit_code": 1, "commands": ["ffmpeg -i b.mp4 -c:v h264_videotoolbox -q:v 75 c.mp4"],
                  "error": {"kind": "ffmpeg", "message": "command failed (1): ffmpeg (video encoder h264_videotoolbox; not retried on the CPU: ...)"},
                  "encoder": "h264_videotoolbox",
                  "hw": {"requested": True, "source": "flag", "used": True, "fallback": False, "notes": []}}
        proc = subprocess.CompletedProcess([], 1, json.dumps(failed), "")
        out = io.StringIO()
        with mock.patch.object(render, "run_tool", return_value=proc), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            render.sh("caption.py", "b.mp4", "-o", "c.mp4")
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["error"]["kind"], "ffmpeg")
        self.assertEqual(doc["encoder"], "h264_videotoolbox")
        self.assertEqual((doc["hw"]["requested"], doc["hw"]["used"], doc["hw"]["fallback"]), (True, True, True))
        self.assertTrue(any(n.startswith("fit: VideoToolbox refused") for n in doc["hw"]["notes"]), doc["hw"])

    def test_hw_runs_on_apple_silicon_hardware_under_a_rosetta_python(self):
        """An x86_64 Python under Rosetta reports platform.machine() "x86_64" on an M-series Mac;
        the hardware (sysctl hw.optional.arm64) decides, and doctor's platform_ok agrees."""
        import _contract

        def sysctl(argv, **_kw):
            self.assertEqual(argv[1:], ["-n", "hw.optional.arm64"])
            return subprocess.CompletedProcess(argv, 0, answer, "")
        for answer, expected in (("1\n", None), ("", "VideoToolbox constant-quality encoding needs Apple Silicon")):
            with self.subTest(sysctl=answer), \
                    mock.patch("platform.system", return_value="Darwin"), \
                    mock.patch("platform.machine", return_value="x86_64"), \
                    mock.patch.object(runner.subprocess, "run", side_effect=sysctl), \
                    mock.patch.object(runner, "_APPLE_SILICON", None):
                self.assertEqual(runner.hw_platform_reason(), expected)
                runner._APPLE_SILICON = None
                self.assertEqual(_contract._hw_default()["platform_ok"], expected is None)
        with mock.patch("platform.system", return_value="Linux"), mock.patch.object(runner, "_APPLE_SILICON", None):
            self.assertEqual(runner.hw_platform_reason(), "VideoToolbox is macOS-only")


class HwChildStageTests(_RealFfmpegCase):
    """The tools that run other tools pass the GPU choice on and report what their stages did
    (reviews of the #304 takeover). Real ffmpeg; VideoToolbox is stood in only in-process."""

    def _recipe(self, folder):
        folder.mkdir()
        (folder / "a.mp4").write_bytes(self.src.read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_b",
                                      "steps": [["fit.py", "{in}", "--height", "120", "-o", "{out}"]]}), encoding="utf-8")
        return recipe

    def test_batch_never_serves_a_cached_item_across_the_gpu_setting(self):
        """The item cache key folds in the GPU setting, as render.py's does: --no-hw after --hw
        (the remedy an env-chosen GPU row prints) re-encodes; and a run that overwrote an output
        drops the other setting's entry, so switching back re-encodes too."""
        folder = self.work / "cache"
        recipe = self._recipe(folder)

        def run(*flags):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), str(folder), "--recipe", str(recipe),
                                   "--fast", "--overwrite", "--json", *flags],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        cached = [bool(run(*f)["results"][0].get("cached")) for f in (["--hw"], ["--no-hw"], ["--hw"], ["--hw"], [])]
        self.assertEqual(cached, [False, False, False, True, False])

    def test_batch_s_top_level_hw_carries_its_items(self):
        """batch.py's own `hw` aggregates its rows: an item's fallback shows at the top level, and
        FFMPEG_SKILL_HW=1 alone (no flag) still gives a top-level `hw`, with `used` null."""
        import batch
        folder = self.work / "agg"
        recipe = self._recipe(folder)
        step = {"status": "completed", "encoder": "libx264", "commands": ["ffmpeg -i a -c:v libx264 -crf 18 b.mp4"],
                "hw": {"requested": True, "source": "flag", "used": False, "fallback": True,
                       "notes": ["VideoToolbox refused the encode: [h264_videotoolbox] Error: cannot create compression session: -12902; re-encoded on the CPU"]}}
        env_step = {"status": "completed", "encoder": "h264_videotoolbox", "commands": ["ffmpeg -i a -c:v h264_videotoolbox -q:v 75 b.mp4"],
                    "hw": {"requested": True, "source": "env", "used": True, "fallback": False, "notes": [emit_module.ENV_HW_NOTE]}}
        for argv, env, doc, expected in ((["--hw"], {}, step, {"requested": True, "source": "flag", "used": None, "fallback": True}),
                                         ([], {runner.HW_ENV: "1"}, env_step, {"requested": True, "source": "env", "used": None, "fallback": False})):
            with self.subTest(argv=argv, env=env):
                out = io.StringIO()
                with mock.patch.object(batch, "run_step", return_value=(True, doc)), mock.patch.dict(os.environ, env), \
                        mock.patch.object(sys, "argv", ["batch.py", str(folder), "--recipe", str(recipe), "--force", "--json"] + argv), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    STATE.reset()
                    batch.main()
                res = json.loads(out.getvalue())
                self.assertEqual({k: res["hw"][k] for k in expected}, expected, res["hw"])
                self.assertEqual(res["results"][0]["hw"]["fallback"], expected["fallback"])
                if expected["fallback"]:
                    self.assertTrue(any(n.startswith("a.mp4: fit: VideoToolbox refused") for n in res["hw"]["notes"]), res["hw"])

    def test_a_hw_plan_executed_by_render_reports_hw(self):
        """`render.py plan.json` runs the planned tool as a child: its `hw` facts reach the result,
        as a direct `fit.py --hw` reports them."""
        plan = self.work / "plan.json"
        out = self.work / "planned.mp4"
        subprocess.run([sys.executable, str(SCRIPTS / "fit.py"), str(self.src), "--height", "120", "--hw", "--fast",
                        "--plan", str(plan), "-o", str(out)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), str(plan), "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["hw"]["requested"], doc["hw"]["source"]), (True, "flag"), doc.get("hw"))
        self.assertEqual(doc["encoder"], doc["tool_result"]["encoder"])
        self.assertEqual(doc["hw"]["used"], doc["tool_result"]["hw"]["used"])

    def test_a_cut_ffmpeg_failure_under_hw_names_its_encoder(self):
        """cut.py --accurate under --hw: its own kind: ffmpeg failure carries `encoder` and `hw`."""
        fake = FakeFfmpeg(self.work, {"vt": {"rc": 1, "stderr": "[enc @ 0x55d] broken encode\n"},
                                      "cpu": {"rc": 1, "stderr": "[enc @ 0x55d] broken encode\n"}})
        env = dict(os.environ, PATH=f"{fake.dir}{os.pathsep}{os.environ.get('PATH', '')}")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "cut.py"), str(self.src), "--start", "0.1", "--end", "0.7",
                               "--accurate", "--hw", "--json", "-o", str(self.work / "c.mp4")], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "ffmpeg")
        self.assertIn(doc["encoder"], ("libx264", "h264_videotoolbox"))
        self.assertEqual((doc["hw"]["requested"], doc["hw"]["source"]), (True, "flag"))

    def _waveform(self, *argv, env=None):
        """waveform.py in this process (its own encode sees VideoToolbox stood in), its caption.py
        stage a real child: (the document, the child's argv, the child's own document)."""
        import waveform
        wav = self.work / "tone.wav"
        if not wav.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", "-c:a", "pcm_s16le", wav)
        srt = self.work / "s.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello\n", encoding="utf-8")
        seen = []

        def spy(cmd, **kw):
            proc = runner.run_tool(cmd, **kw)
            seen.append((list(cmd), json.loads(proc.stdout)))
            return proc
        out = io.StringIO()
        a, b = _vt_available()
        with a, b, mock.patch.object(waveform, "run_tool", side_effect=spy), mock.patch.dict(os.environ, env or {}), \
                mock.patch.object(sys, "argv", ["waveform.py", str(wav), "--width", "320", "--height", "180", "--srt", str(srt),
                                                "--dry-run", "--json", "-o", str(self.work / "w.mp4")] + list(argv)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            STATE.reset()
            waveform.main()
        (child_argv, child_doc), = seen
        return json.loads(out.getvalue()), child_argv, child_doc

    def test_waveform_passes_its_gpu_choice_to_the_stage_that_writes_the_file(self):
        """caption.py writes waveform.py's deliverable: --hw reaches it, and the result's
        `encoder` is the encoder of the file delivered, not of the intermediate render."""
        doc, child_argv, child_doc = self._waveform("--hw")
        self.assertIn("--hw", child_argv)
        self.assertEqual(child_doc["hw"]["requested"], True)
        self.assertEqual(doc["encoder"], child_doc["encoder"])
        self.assertEqual(doc["commands"][-1], child_doc["commands"][-1])

    def test_waveform_s_no_hw_overrides_the_variable_for_its_stage_too(self):
        doc, child_argv, child_doc = self._waveform("--no-hw", env={runner.HW_ENV: "1"})
        self.assertIn("--no-hw", child_argv)
        self.assertNotIn("hw", child_doc, "the caption stage ran on the CPU, as asked")
        self.assertNotIn("hw", doc)
        self.assertEqual(doc["encoder"], "libx264")


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
        self.assertEqual(doc["hw"], {"requested": True, "source": "flag", "used": True, "fallback": False, "notes": []})
        self.assertTrue(any("h264_videotoolbox -q:v" in n and "not CRF-equivalent" in n for n in doc["notes"]), doc.get("notes"))
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
        self.assertTrue(doc["hw"]["fallback"])
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
