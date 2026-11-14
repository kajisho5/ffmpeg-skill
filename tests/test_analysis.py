#!/usr/bin/env python3
"""End-to-end tests for probe, check, verify, scenes, cropdetect, report, look and sync.

    python3 tests/test_analysis.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import collections
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, TONES, _is_faststart, _no_fontconfig, png_size, sar_clip, script, sh, tiny_clip  # noqa: E402
from _fixtures import make_tones_take, legal_range_clip  # noqa: E402
from _common import default_font_file, font_for_script, probe  # noqa: E402
import importlib  # noqa: E402
content_probe = importlib.import_module("_common.probe")  # the module: `_common.probe` is also a function
import check as check_module  # noqa: E402


class AnalysisTests(MediaFixtures):
    """Probe, check, verify, scenes, cropdetect, report, look and sync."""

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

    def test_probe_reports_the_start_timecode(self):
        """probe's `timecode` (nle-bridge's source timecode): the first well-formed `timecode` tag
        from the video stream, a tmcd data stream, then the container; `drop_frame` is the `;`."""
        cases = [("tc.mov", "25", "01:00:00:00", False), ("tc.mp4", "25", "01:00:00:00", False),
                 ("tc_df.mov", "30000/1001", "01:00:00;00", True)]
        for name, rate, tc, drop in cases:
            out = OUT / name
            sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=d=1:s=160x90:r={rate}", "-timecode", tc, out)
            data = json.loads(script("probe.py", out, "--json").stdout)
            self.assertEqual(data["timecode"]["value"], tc, name)
            self.assertIs(data["timecode"]["drop_frame"], drop, name)
            self.assertRegex(data["timecode"]["source"], r"^(stream:\d+|format)$", name)
        data = json.loads(script("probe.py", self.src, "--json").stdout)
        self.assertEqual(data["timecode"], {"value": None, "drop_frame": None, "source": None})
        pick = content_probe.start_timecode
        tmcd = {"index": 2, "codec_type": "data", "codec_tag_string": "tmcd", "tags": {"timecode": "10:00:00:00"}}
        self.assertEqual(pick([tmcd], {"tags": {"timecode": "00:00:00:00"}}, {"index": 0}),
                         {"value": "10:00:00:00", "drop_frame": False, "source": "stream:2"})
        self.assertEqual(pick([], {"tags": {"TIMECODE": "01:00:00.00"}}, {"index": 0, "tags": {"timecode": "not a tc"}}),
                         {"value": "01:00:00.00", "drop_frame": True, "source": "format"}, "a malformed tag is skipped")
        self.assertEqual(pick([], {"tags": {"timecode": "02:00:00:00"}}, {"index": 0, "tags": {"timecode": "01:99:99:00"}})["source"],
                         "format", "minutes and seconds above 59 are not a timecode")
        # #427 review: a frames field the picture's rate cannot reach is skipped, and a tmcd
        # track's valid tag is used instead of reading the file as having no timecode
        v25 = {"index": 0, "r_frame_rate": "25/1", "tags": {"timecode": "01:00:00:29"}}
        tmcd1 = {"index": 2, "codec_type": "data", "codec_tag_string": "tmcd", "tags": {"timecode": "01:00:00:00"}}
        self.assertEqual(pick([tmcd1], {}, v25)["value"], "01:00:00:00")
        self.assertIsNone(pick([], {}, v25)["value"])
        self.assertEqual(pick([], {}, dict(v25, r_frame_rate="30000/1001"))["value"], "01:00:00:29")
        # the rate probe()'s fps uses: avg_frame_rate first (25 here, though r_frame_rate says 50)
        self.assertEqual(pick([tmcd1], {}, dict(v25, avg_frame_rate="25/1", r_frame_rate="50/1"))["value"], "01:00:00:00")

    def test_probe_accepts_common_flags(self):
        out = script("probe.py", self.src, "--json", "--field", "duration").stdout.strip()
        self.assertClose(float(out), 12.0, 0.1)

    def test_probe_missing_file_fails(self):
        proc = script("probe.py", OUT / "nope.mp4", expect_fail=True)
        self.assertIn("not found", proc.stderr)

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

    def test_cropdetect_limit_1_is_the_top_of_its_range(self):
        """Audit A164: FFmpeg's cropdetect reads a limit of 1 or more as a pixel code, so --limit 1,
        the top of the documented 0..1 range, was code 1 (nearly nothing black) while 0.999 is
        nearly everything. It is now written as the top code of the source's bit depth."""
        bars = OUT / "cropdetect_limit_bars.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "color=c=gray:s=100x50:d=1:r=10,pad=160:90:30:20:black", "-pix_fmt", "yuv420p", bars)

        def run(*extra):
            return json.loads(script("cropdetect.py", bars, "--samples", "1", *extra, "--json").stdout)
        default = run()["crop"]
        self.assertIsNotNone(default, "the fixture has bars to find at the default limit")
        # 0.999 counts nearly every pixel as black, so cropdetect reports nothing; code 1 counted
        # almost none and reported a frame-sized crop
        self.assertEqual(run("--limit", "1")["crop"], run("--limit", "0.999")["crop"])
        self.assertNotEqual(run("--limit", "1")["crop"], run("--limit", "0")["crop"])

    def test_cropdetect_reports_the_displayed_frame_of_a_rotated_source(self):
        """cropdetect runs after ffmpeg applies rotation. The stored 1280x720 phone file is
        720x1280 on screen, and a rectangle reported against the stored size is taller than
        the source it claims to sit in."""
        v = probe(str(self.rot))["video"]
        self.assertIn(v["rotation"], (90, -90, 270, -270))
        dw, dh = v["height"], v["width"]
        data = json.loads(script("cropdetect.py", self.rot, "--seconds", "1", "--samples", "1", "--json").stdout)
        self.assertEqual((data["source_width"], data["source_height"]), (dw, dh))
        crop = data["crop"]
        self.assertIsNotNone(crop)
        self.assertLessEqual(crop["x"] + crop["width"], data["source_width"])
        self.assertLessEqual(crop["y"] + crop["height"], data["source_height"])

    def test_cropdetect_writes_no_file(self):
        before = set(OUT.iterdir())
        script("cropdetect.py", self.src, "--seconds", "1", "--samples", "1")
        self.assertEqual(before, set(OUT.iterdir()))

    def test_cropdetect_bad_seconds_refused(self):
        script("cropdetect.py", self.src, "--seconds", "0", expect_fail=True)

    # ---------------------------------------------------------------- 1.18.0: cropdetect.py --motion-centre
    def test_cropdetect_motion_centre_reports_per_second_points(self):
        data = json.loads(script("cropdetect.py", self.src, "--seconds", "4", "--samples", "2",
                                 "--motion-centre", "--json").stdout)
        self.assertIn("motion_centre", data)
        self.assertGreater(len(data["motion_centre"]), 0)
        for pt in data["motion_centre"]:
            self.assertIn("time", pt)
            if pt["x"] is not None:
                self.assertGreaterEqual(pt["x"], 0)
                self.assertLessEqual(pt["x"], data["source_width"])
                self.assertGreaterEqual(pt["x_frac"], 0.0)
                self.assertLessEqual(pt["x_frac"], 1.0)

    def test_cropdetect_motion_centre_writes_no_file(self):
        before = set(OUT.iterdir())
        script("cropdetect.py", self.src, "--seconds", "1", "--samples", "1", "--motion-centre")
        self.assertEqual(before, set(OUT.iterdir()))

    def test_cropdetect_motion_centre_is_off_by_default(self):
        data = json.loads(script("cropdetect.py", self.src, "--seconds", "1", "--samples", "1",
                                 "--json").stdout)
        self.assertNotIn("motion_centre", data)

    def test_fonts_dir_does_not_bypass_the_coverage_check(self):
        """--fonts-dir says "also look here", not "this exact face": a directory that does not
        cover the script must not silently switch the guarantee off."""
        if _no_fontconfig() or not shutil.which("fc-scan"):
            self.skipTest("no fontconfig tools on this machine")
        if font_for_script("ko") is None:
            self.skipTest("this machine has no font covering ko")
        latin_only = Path(default_font_file("DejaVu Sans") or "")
        if not latin_only.exists():
            self.skipTest("no DejaVu Sans file to point --fonts-dir at")
        # an isolated directory holding only the Latin face: the system font directory that
        # file lives in may well cover Korean too (macOS ships Apple SD Gothic Neo next to it)
        latin_dir = OUT / "fontsdir_latin_only"
        latin_dir.mkdir(exist_ok=True)
        shutil.copyfile(latin_only, latin_dir / latin_only.name)
        cues = OUT / "fontsdir_ko.txt"
        cues.write_text("0:00-0:03 안녕하세요\n", encoding="utf-8")
        proc = script("caption.py", self._small(), "--text", cues, "--fonts-dir", latin_dir,
                      "--fast", "-o", OUT / "fontsdir_ko.mp4", "--json")
        self.assertIn("covers ko", proc.stderr, proc.stderr)
        self.assertIn("no face in", proc.stderr, "the caller is told the directory does not cover the script")
        self.assertNotIn("FontName=DejaVu Sans", " ".join(json.loads(proc.stdout)["commands"]))

    def test_probe_hdr_is_the_signal_and_bt2020_sdr_keeps_the_10bit_route(self):
        """2.0 (deprecated in 1.10.0): `hdr` is true only for PQ / HLG / Dolby Vision, equal to
        `hdr_signal`; BT.2020 primaries on an SDR transfer are `hdr: false` with
        `bt2020_or_hdr: true` (the 1.x meaning) and `hdr_format: "BT.2020 SDR"`. The editing tools
        route on `bt2020_or_hdr`, so such a source still re-encodes as HEVC Main10 keeping its
        BT.2020 tags -- x264 with BT.709 tags would shift its colours."""
        m = probe(str(self.hdr))["video"]
        self.assertEqual((m["hdr"], m["hdr_signal"], m["bt2020_or_hdr"]), (True, True, True))
        m = probe(str(self.src))["video"]
        self.assertEqual((m["hdr"], m["hdr_signal"], m["bt2020_or_hdr"]), (False, False, False))
        wide = OUT / "bt2020_sdr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
           "-t", "1", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=bt709:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1", wide)
        m = probe(str(wide))["video"]
        self.assertEqual((m["hdr"], m["hdr_signal"], m["bt2020_or_hdr"], m["hdr_format"]), (False, False, True, "BT.2020 SDR"))
        padded = OUT / "bt2020_sdr_pad.mp4"
        script("pad.py", wide, "--start", "0.5", "--preset", "ultrafast", "-o", padded, "--overwrite")
        m = probe(str(padded))["video"]
        self.assertEqual((m["codec"], m["bit_depth"], m["color_primaries"]), ("hevc", 10, "bt2020"))

    # ---------------------------------------------------------------- sync
    def test_sync_detects_offset_and_replaces_audio(self):
        proc = script("sync.py", self.src, self.mic, "--json")
        data = json.loads(proc.stdout)
        self.assertClose(data["offset_seconds"], 2.5, 0.05, "lav mic started 2.5 s later")
        self.assertIn("later than reference", data["meaning"])
        self.assertGreater(data["confidence"], 0.5)
        out = OUT / "synced.mp4"
        script("sync.py", self.src, self.mic, "--replace-audio", "-o", out)
        again = json.loads(script("sync.py", self.src, out, "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.05, "aligned output has no residual offset")

    def test_sync_zero_offset_says_the_files_start_together(self):
        """A measured offset of 0 used to take the else of `later if offset > 0` and say the
        second file starts earlier. Identical inputs start together."""
        same = OUT / "sync_identical.mp4"
        shutil.copy(self.src, same)
        data = json.loads(script("sync.py", self.src, same, "--json").stdout)
        self.assertAlmostEqual(data["offset_seconds"], 0.0, delta=5e-4)
        self.assertEqual(data["meaning"], "second starts together with the reference")

    def test_a_late_sound_is_measured_and_placed_on_its_files_clock(self):
        """#409: decode_pcm_mono did not pad a sound that starts after its file's start, so a take
        whose clock starts 1.0 s into the reference and whose sound starts 0.3 s after its picture
        measured +1.3 s (sample 0 taken for the file's 0), and --replace-audio placed the sound that
        far off. The offset is between the files' clocks, and the written sound keeps it."""
        ref = make_tones_take(OUT / "sync_clock_ref.mp4", dur=8)
        take = make_tones_take(OUT / "sync_clock_take.mp4", start=1.0, audio_late=0.3, dur=7)
        data = json.loads(script("sync.py", ref, take, "--json").stdout)
        self.assertAlmostEqual(data["offset_seconds"], 1.0, delta=0.01, msg=data)
        out = OUT / "sync_clock_replaced.mp4"
        script("sync.py", ref, take, "--replace-audio", "-o", out)
        again = json.loads(script("sync.py", ref, out, "--json").stdout)
        self.assertAlmostEqual(again["offset_seconds"], 0.0, delta=0.01, msg=again)

    def test_sync_replace_audio_stream_copy_writes_faststart_mp4(self):
        """Same shape as #275/#277: --replace-audio stream-copies the reference's video with
        -c:v copy while only the audio is rebuilt, and must write -movflags +faststart on the
        mp4 output the same way every other mp4-writing path does."""
        out = OUT / "sync_replace_faststart.mp4"
        script("sync.py", self.src, self.mic, "--replace-audio", "-o", out)
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")
        self.assertTrue(_is_faststart(out), "sync.py --replace-audio must write +faststart")

    def test_sync_trim_second_of_a_video_lands_on_the_reference_and_is_faststart(self):
        """--trim-second stream-copied a second camera that started earlier: the copy began at the
        keyframe before the trim point and -avoid_negative_ts make_zero showed the frames from it,
        so a 1 s GOP came out 0.2 s early (a 5 s GOP: nothing trimmed) and was reported as synced.
        A picture is re-encoded from the frame itself; the written file re-measures at 0, and the
        MP4 is still faststart (#275/#277)."""
        ref = make_tones_take(OUT / "sync_trim_ref.mp4", start=1.2, dur=6)
        take = make_tones_take(OUT / "sync_trim_take_tmp.mp4", start=0.0, dur=7.2)
        early_video = OUT / "sync_trim_take_g30.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", take, "-c:v", "libx264", "-preset", "veryfast",
           "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-c:a", "copy", early_video)
        out = OUT / "sync_trim_second_faststart.mp4"
        data = json.loads(script("sync.py", ref, early_video, "--trim-second", "-o", out, "--json").stdout)
        self.assertAlmostEqual(data["offset_seconds"], -1.2, delta=0.01, msg=data)
        self.assertEqual(probe(str(out))["video"]["codec"], "h264")
        self.assertTrue(_is_faststart(out), "sync.py --trim-second must write +faststart")
        again = json.loads(script("sync.py", ref, out, "--json").stdout)
        self.assertAlmostEqual(again["offset_seconds"], 0.0, delta=0.01, msg=again)
        self.assertLess(abs(probe(str(out))["duration"] - 6.0), 0.05, "1.2 s of head trimmed off 7.2 s")

    def test_sync_trim_second_seeks_early_and_drops_the_margin_on_the_output_side(self):
        """--trim-second re-encoded the picture from an input -ss straight to the trim point. The
        MP4 demuxer seeks over raw decode times, so on a B-frame HEVC camera a seek just before a
        keyframe (its dts 0.1 s before its pts) can land on that keyframe and lose the frames
        before it (cut.py's --accurate did, -ss 9.9 began at 10.0). It now seeks SEEK_MARGIN
        early and drops the margin on the output side, as cut.py does: every frame from the trim
        point is there, the sound still lands on the reference, and the start timecode is the
        first kept frame's."""
        from _common.decision import SEEK_MARGIN
        ref = make_tones_take(OUT / "sync_seek_ref.mp4", start=3.92, dur=3)
        take = make_tones_take(OUT / "sync_seek_take_tmp.mp4", start=0.0, dur=7)
        cam = OUT / "sync_seek_cam.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=7",
           "-i", take, "-map", "0:v", "-map", "1:a", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "bframes=4:b-pyramid=1:keyint=60:min-keyint=60:scenecut=0:log-level=error",
           "-tag:v", "hvc1", "-c:a", "copy", "-timecode", "10:00:00:00", cam)
        out = OUT / "sync_seek_synced.mov"
        data = json.loads(script("sync.py", ref, cam, "--trim-second", "-o", out, "--overwrite", "--json").stdout)
        head = -data["offset_seconds"]
        self.assertAlmostEqual(head, 3.92, delta=0.01, msg=data)
        cmd = shlex.split(data["commands"][-1])
        i = cmd.index("-i")
        self.assertEqual(cmd[i - 2:i], ["-ss", f"{head - SEEK_MARGIN:.6f}"], cmd)
        self.assertEqual(cmd[i + 2:i + 4], ["-ss", f"{SEEK_MARGIN:.6f}"], "the margin is dropped on the output side")
        frames = sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                    "stream=nb_read_frames", "-of", "csv=p=0", out).stdout.strip()
        # frames 118 (3.933 s) .. 209 (6.967 s): every frame from the trim point to the end.
        # FFmpeg 8's ffprobe prints the stream's section twice in csv ("92\n\n92"): the first
        # value is the stream's
        self.assertEqual(int(frames.split()[0]), 210 - 118, frames)
        got = probe(str(out))
        self.assertLess(abs((got["video"]["start_time"] or 0.0) - (got["audio"]["start_time"] or 0.0)), 0.03, got)
        again = json.loads(script("sync.py", ref, out, "--json").stdout)
        self.assertAlmostEqual(again["offset_seconds"], 0.0, delta=0.01, msg=again)
        tc = sh("ffprobe", "-v", "error", "-show_entries", "stream_tags=timecode", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(sorted(set(tc)), ["10:00:03:28"])

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

    # ---------------------------------------------------------------- 1.18.0: sync.py 3+ sources
    def _cam3(self):
        """A third source: the reference shifted 1.2 s later, so it has a real measurable offset
        distinct from self.mic's 2.5 s."""
        cam3 = OUT / "sync_cam3.wav"
        if not cam3.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "aevalsrc=0:s=48000:d=1.2", "-i", self.src,
               "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1", cam3)
        return cam3

    def test_sync_two_sources_keeps_the_original_shape(self):
        """The 2-source CLI shape is a special case of the N-source one, byte-for-byte: the same
        top-level offset_seconds/confidence/second keys tested since 1.0, plus (additively) the
        new `sources` list."""
        data = json.loads(script("sync.py", self.src, self.mic, "--json").stdout)
        self.assertIn("offset_seconds", data)
        self.assertIn("second", data)
        self.assertIn("confidence", data)
        self.assertIn("sources", data)
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(data["sources"][0]["path"], str(self.mic))
        self.assertAlmostEqual(data["sources"][0]["offset_s"], data["offset_seconds"], delta=0.001)

    def test_sync_three_sources_writes_one_offsets_json(self):
        data = json.loads(script("sync.py", self.src, self.mic, self._cam3(), "--json").stdout)
        self.assertNotIn("second", data)         # no single-pair shape for N>1
        self.assertNotIn("offset_seconds", data)
        self.assertEqual(data["reference"], str(self.src))
        self.assertEqual(len(data["sources"]), 2)
        by_path = {s["path"]: s for s in data["sources"]}
        self.assertClose(by_path[str(self.mic)]["offset_s"], 2.5, 0.05)
        self.assertClose(by_path[str(self._cam3())]["offset_s"], -1.2, 0.05)
        for s in data["sources"]:
            self.assertIn("confidence", s)

    def test_sync_three_sources_reports_drift_ppm_per_source(self):
        data = json.loads(script("sync.py", self.long_ref, self.long_drift, self.long_ref,
                                 "--fix-drift", "--json").stdout)
        drifts = {s["path"]: s["drift_ppm"] for s in data["sources"]}
        self.assertClose(drifts[str(self.long_drift)], 500.0, 60.0)
        self.assertClose(drifts[str(self.long_ref)], 0.0, 60.0)

    def test_sync_replace_audio_refuses_multiple_sources(self):
        r = script("sync.py", self.src, self.mic, self._cam3(), "--replace-audio",
                   "-o", OUT / "nope.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_sync_three_sources_text_output(self):
        proc = script("sync.py", self.src, self.mic, self._cam3())
        self.assertIn(str(self.mic), proc.stdout)
        self.assertIn(str(self._cam3()), proc.stdout)

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

    # ---------------------------------------------------------------- check --content
    def _content_clip(self, name, video, audio, seconds=6):
        path = OUT / name
        if not path.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video,
               "-f", "lavfi", "-i", audio, "-t", str(seconds), "-r", "10", "-pix_fmt", "yuv420p",
               "-c:v", "libx264", "-c:a", "aac", "-shortest", path)
        return path

    def _rows(self, path, *extra):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(path), "--platform", "custom",
                               "--json", *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return {r["check"]: r for r in json.loads(proc.stdout)["checks"]}

    def test_check_content_rows(self):
        tone = "sine=frequency=440:sample_rate=48000"
        normal = self._content_clip("content_normal.mp4", "testsrc2=size=160x90:rate=10", tone)
        black = self._content_clip("content_black.mp4", "color=black:size=160x90:rate=10", tone)
        frozen = self._content_clip("content_frozen.mp4", "color=gray:size=160x90:rate=10,drawbox=x=20:y=20:w=40:h=40:color=red:t=fill", tone)
        # 2 s moving then 4 s held: the held span (4 s) exceeds max(3 s, 30% of 6 s) but is not the whole clip
        part = OUT / "content_part_frozen.mp4"
        if not part.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "testsrc2=size=160x90:rate=10,trim=duration=2,tpad=stop_mode=clone:stop_duration=4",
               "-f", "lavfi", "-i", tone, "-t", "6", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", part)
        silent = self._content_clip("content_silent.mp4", "testsrc2=size=160x90:rate=10", "anullsrc=r=48000:cl=mono")
        # 1.5 s black then 4.5 s picture: 25% black -> WARN; tone for 2 s then 4 s silence -> 67% silent -> WARN
        mixed = OUT / "content_mixed.mp4"
        if not mixed.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "testsrc2=size=160x90:rate=10,drawbox=t=fill:color=black:enable='lt(t,1.5)'",
               "-f", "lavfi", "-i", tone + ",volume=enable='gte(t,2)':volume=0", "-t", "6",
               "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", mixed)
        r = self._rows(normal, "--content")
        self.assertEqual([r[k]["status"] for k in ("black", "frozen", "silence", "dropouts", "first frame", "flashes")],
                         ["PASS"] * 6, r)
        self.assertEqual(self._rows(black, "--content")["black"]["status"], "FAIL")
        self.assertEqual(self._rows(frozen, "--content")["frozen"]["status"], "FAIL")
        self.assertEqual(self._rows(part, "--content")["frozen"]["status"], "WARN")
        self.assertEqual(self._rows(silent, "--content")["silence"]["status"], "FAIL")
        r = self._rows(mixed, "--content")
        self.assertEqual((r["black"]["status"], r["silence"]["status"]), ("WARN", "WARN"), r)

    def test_check_content_flashes_and_first_frame_rows(self):
        """2.23: one frame unlike both neighbours (which match each other) is a flashes WARN with its
        time; a hard cut, a cut away and back after several frames, and moving footage are not. A
        first frame of one flat colour (a black lead-in) is a first-frame WARN. Fast motion, where every
        frame jumps as far as a flash does, is not a flash because its frames never return. Neither row FAILs:
        a strobe or a fade from black can be the edit."""
        tone = "sine=frequency=440:sample_rate=48000"
        moving = "testsrc2=size=160x90:rate=10"
        flash = self._content_clip("content_flash.mp4", moving + ",drawbox=t=fill:color=white:enable='eq(n,15)'", tone)
        away = self._content_clip("content_cut_away.mp4", moving + ",drawbox=t=fill:color=red:enable='between(n,15,18)'", tone)
        cut = self._content_clip("content_hard_cut.mp4", moving + ",drawbox=t=fill:color=navy:enable='gte(n,30)'", tone)
        lead = self._content_clip("content_black_lead.mp4", moving + ",drawbox=t=fill:color=black:enable='lt(n,3)'", tone)
        # every frame jumps as far as a flash does, but never comes back: the neighbour rule keeps it out
        whip = self._content_clip("content_whip.mp4", moving + ",scroll=horizontal=0.13", tone)
        r = self._rows(flash, "--content")
        self.assertEqual(r["flashes"]["status"], "WARN", r["flashes"])
        self.assertTrue(r["flashes"]["value"].startswith("1: 1.50s"), r["flashes"])
        self.assertIn("join", r["flashes"]["fix"])
        self.assertEqual((r["flashes"]["kind"], r["first frame"]["kind"]), ("judgement", "judgement"))
        for clip in (away, cut, lead, whip):
            self.assertEqual(self._rows(clip, "--content")["flashes"]["status"], "PASS", clip)
        # a timestamp gap right after the flash: the rawvideo muxer's constant-rate padding repeated
        # records there, which hid this flash and reported two false ones 9 frames later
        gap = OUT / "content_flash_gap.mkv"
        if not gap.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               moving + ":duration=6,drawbox=t=fill:color=white:enable='eq(n,20)',setpts='if(gt(N,20),PTS+1/TB,PTS)'",
               "-fps_mode", "passthrough", "-c:v", "libx264", "-pix_fmt", "yuv420p", gap)
        r = self._rows(gap, "--content")
        self.assertTrue(r["flashes"]["value"].startswith("1: "), r["flashes"])
        self.assertEqual(content_probe.detect_flashes(str(gap)), [20])
        # the gap comes before this flash: its row time is its own presentation time (4.0 s), not 30 / 10 fps
        late = OUT / "content_flash_after_gap.mkv"
        if not late.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               moving + ":duration=6,drawbox=t=fill:color=white:enable='eq(n,30)',setpts='if(gt(N,20),PTS+1/TB,PTS)'",
               "-fps_mode", "passthrough", "-c:v", "libx264", "-pix_fmt", "yuv420p", late)
        self.assertEqual(self._rows(late, "--content")["flashes"]["value"], "1: 4.00s")
        r = self._rows(lead, "--content")
        self.assertEqual(r["first frame"]["status"], "WARN", r["first frame"])
        self.assertEqual(self._rows(cut, "--content")["first frame"]["status"], "PASS")
        self.assertNotIn("flashes", self._rows(flash))  # opt-in: the default row set is unchanged

    def test_check_flash_times_on_the_look_timeline(self):
        """The flashes row's times: a flash frame's own presentation time from the container start
        when it is known, else index / rate plus the video's lead marked "~", else `frame N`."""
        meta = {"start_time": 0.5}
        pts = [0.5 + i / 10 for i in range(20)] + [4.0 + i / 10 for i in range(20)]  # a 1.5 s gap after frame 19
        self.assertEqual(check_module.flash_times([5, 25], {"fps": 10.0}, meta, pts), "0.50s, 4.00s")
        self.assertEqual(check_module.flash_times([15], {"fps": 30.0, "start_time": 0.7}, meta), "~0.70s")
        self.assertEqual(check_module.flash_times([15, 16], {"fps": None}, meta), "frame 15, frame 16")
        self.assertTrue(check_module.flash_times(list(range(7)), {"fps": 10.0}, meta, pts).endswith(" ..."))

    def test_check_flash_pass_failure_is_unmeasured(self):
        """A flash pass that fails is None (a WARN 'could not measure' row in check.py), never []
        (which would read as PASS)."""
        from unittest import mock
        failed = subprocess.CompletedProcess([], 1, b"", b"Error while decoding stream")
        clip = self._content_clip("content_normal.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000")
        with mock.patch.object(content_probe, "run_analysis", lambda *a, **k: failed):
            self.assertIsNone(content_probe.detect_flashes(str(clip)))

    def test_presentation_times_refuse_a_packet_without_pts(self):
        """One unreadable pts makes the whole list [] (the flashes row falls back to its "~" time)
        rather than skipping that packet and shifting every later time onto the wrong frame."""
        from unittest import mock
        def fake(stdout):
            return lambda *a, **k: subprocess.CompletedProcess([], 0, stdout, "")
        with mock.patch.object(content_probe, "run", fake("0.2\n0.0\n0.1\n")):
            self.assertEqual(content_probe.presentation_times("in.mp4", 0.0), [0.0, 0.1, 0.2])
        with mock.patch.object(content_probe, "run", fake("0.0\nN/A\n0.2\n")):
            self.assertEqual(content_probe.presentation_times("in.mp4", 0.0), [])

    def test_content_passes_skip_cover_art(self):
        """Every --content decode selects V:0 (attached pictures excluded, as probe does), so cover
        art ahead of the playable video is never what the black, frozen, flash or first-frame rows
        measure."""
        from unittest import mock
        seen = []
        def fake(cmd, *a, **k):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, b"", b"")
        with mock.patch.object(content_probe, "run_analysis", fake), \
                mock.patch.object(content_probe, "die", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                content_probe.detect_content("in.mp4", 3.0, audio=False)
            content_probe.detect_flashes("in.mp4")
            content_probe.first_frame_stats("in.mp4")
        self.assertEqual(len(seen), 3, seen)
        for cmd in seen:
            joined = " ".join(map(str, cmd))
            self.assertIn("0:V:0", joined, cmd)
            self.assertNotIn("0:v:0", joined, cmd)
    def test_check_expect_identity_ties_the_check_to_one_write(self):
        """2.24: a writing tool reports output_identity; check.py --expect-identity FAILs on any other
        file at that path (here: the same path rewritten by a second run), and reports input_identity."""
        src = self._content_clip("identity_src.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000", 2)
        out = OUT / "identity_out.mp4"
        first = json.loads(subprocess.run([sys.executable, str(SCRIPTS / "cut.py"), str(src), "--end", "1", "-o", str(out),
                                           "--overwrite", "--json"], stdout=subprocess.PIPE, text=True).stdout)
        ident = first["output_identity"]
        self.assertEqual(ident["size"], out.stat().st_size)
        expect = f"{ident['size']}:{ident['mtime_ns']}"
        self.assertEqual(self._rows(out, "--no-loudness", "--expect-identity", expect)["identity"]["status"], "PASS")
        subprocess.run([sys.executable, str(SCRIPTS / "cut.py"), str(src), "--end", "1.5", "-o", str(out), "--overwrite"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(out), "--platform", "custom", "--no-loudness",
                               "--expect-identity", expect, "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        doc = json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual({r["check"]: r["status"] for r in doc["checks"]}["identity"], "FAIL")
        self.assertEqual(doc["input_identity"]["size"], out.stat().st_size)
        # a file replaced while it was being measured fails, even when the second read matches
        import contextlib, io
        from unittest import mock
        first = {"size": 1, "mtime_ns": 1}
        now = {"size": out.stat().st_size, "mtime_ns": out.stat().st_mtime_ns}
        argv = ["check.py", str(out), "--platform", "custom", "--no-loudness", "--expect-identity",
                f"{now['size']}:{now['mtime_ns']}", "--json"]
        buf = io.StringIO()
        with mock.patch.object(check_module, "file_identity", side_effect=[first, now]), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                check_module.main()
        row = {r["check"]: r for r in json.loads(buf.getvalue())["checks"]}["identity"]
        self.assertEqual((row["status"], row["reason"]), ("FAIL", "the file changed while it was being checked"), row)
        # without --expect-identity there is no identity row, but the change is still a note
        buf = io.StringIO()
        with mock.patch.object(check_module, "file_identity", side_effect=[first, now]), \
                mock.patch.object(sys, "argv", argv[:4] + ["--json"]), contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                check_module.main()
            except SystemExit:
                pass
        doc = json.loads(buf.getvalue())
        self.assertNotIn("identity", {r["check"] for r in doc["checks"]})
        self.assertTrue(any("changed while it was being checked" in n for n in doc.get("notes", [])), doc.get("notes"))
        # a dry run reads the file that exists, so the identity row is there under --dry-run too
        self.assertEqual(self._rows(out, "--no-loudness", "--expect-identity", expect, "--dry-run")["identity"]["status"], "FAIL")

    def test_check_compare_measures_against_a_reference(self):
        """2.24: --compare REF: identical frames PASS as identical, a heavily compressed copy WARNs
        under a mean SSIM of 0.98 with its worst frame, another frame size is not compared."""
        ref = self._content_clip("compare_ref.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000", 3)
        poor, small = OUT / "compare_poor.mp4", OUT / "compare_small.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref, "-c:v", "libx264", "-crf", "45", "-c:a", "copy", poor)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref, "-vf", "scale=80:46", "-c:v", "libx264", "-c:a", "copy", small)
        same = self._rows(ref, "--no-loudness", "--compare", ref)["similarity"]
        self.assertEqual(same["status"], "PASS")
        self.assertIn("identical", same["value"])
        low = self._rows(poor, "--no-loudness", "--compare", ref)["similarity"]
        self.assertEqual(low["status"], "WARN", low)
        self.assertIn("worst", low["value"])
        self.assertIn("not compared", self._rows(small, "--no-loudness", "--compare", ref)["similarity"]["value"])

    def _levels(self, path, *extra):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(path), "--platform", "custom",
                               "--no-loudness", "--json", *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        doc = json.loads(proc.stdout)
        return doc, {r["check"]: r for r in doc["checks"]}

    def test_check_levels_counts_out_of_range_samples_exactly(self):
        """--levels: on a lossless clip with known shares (frames 0-4 patterned, 5-9 legal grey), the
        luma and chroma shares per clip, per window and in the worst frame are the counted ones, for
        bt709 and for ebu-r103's wider limits; min/max are the codes written."""
        clip = OUT / "levels8.mkv"
        known = legal_range_clip(clip)
        n, c = known["samples"]
        y709 = sum(known["y"].values()) / n * 100
        u709 = sum(known["u"].values()) / c * 100
        y103 = (known["y"][10] + known["y"][250]) / n * 100
        doc, rows = self._levels(clip, "--levels", "bt709", "--levels-window", "0.5")
        lv = doc["levels"]
        self.assertEqual((lv["standard"], lv["bit_depth"], lv["legal"]), ("bt709", 8, {"y": [16, 235], "c": [16, 240]}))
        self.assertEqual(lv["frames"], 10)
        self.assertAlmostEqual(lv["out_of_range_pct"]["y"], y709 / 2, places=2)
        self.assertAlmostEqual(lv["out_of_range_pct"]["u"], u709 / 2, places=2)
        self.assertAlmostEqual(lv["out_of_range_pct"]["v"], 0.0, places=6)
        self.assertAlmostEqual(lv["out_of_range_pct"]["chroma"], u709 / 4, places=2)
        self.assertAlmostEqual(lv["worst_frame"]["y_pct"], y709, places=2)
        self.assertAlmostEqual(lv["worst_frame"]["time"], 0.0, places=3)
        self.assertEqual((lv["min"], lv["max"]), ({"y": 10, "u": 10, "v": 128}, {"y": 250, "u": 128, "v": 128}))
        self.assertAlmostEqual(lv["brng_pct"], y709 / 2, places=2, msg="every out-of-range Cb sample sits on an out-of-range luma row")
        first, second = lv["windows"]
        self.assertEqual((first["start"], first["end"], first["frames"], second["frames"]), (0.0, 0.5, 5, 5))
        self.assertAlmostEqual(first["out_of_range_pct"]["y"], y709, places=2)
        self.assertEqual(second["out_of_range_pct"], {"y": 0.0, "u": 0.0, "v": 0.0, "chroma": 0.0})
        self.assertEqual(rows["legal levels"]["status"], "FAIL")
        self.assertEqual(rows["legal levels"]["kind"], "format")
        self.assertIn("--legalize bt709", rows["legal levels"]["fix"])
        doc, rows = self._levels(clip, "--levels", "ebu-r103", "--levels-window", "0")
        lv = doc["levels"]
        self.assertEqual(lv["legal"], {"y": [14, 241], "c": [5, 251]})
        self.assertAlmostEqual(lv["out_of_range_pct"]["y"], y103 / 2, places=2)
        self.assertEqual(lv["out_of_range_pct"]["chroma"], 0.0)
        self.assertEqual(lv["windows"], [])
        # the tolerance is per frame: 15 % of luma out passes a 20 % allowance, not a 10 % one
        self.assertEqual(self._levels(clip, "--levels", "ebu-r103", "--levels-tolerance", "20")[1]["legal levels"]["status"], "PASS")
        self.assertEqual(self._levels(clip, "--levels", "ebu-r103", "--levels-tolerance", "10")[1]["legal levels"]["status"], "FAIL")

    def test_check_levels_scales_the_limits_with_the_bit_depth(self):
        """--levels on a 10-bit clip: the same pattern at 4x the codes gives the same shares against
        64-940 / 64-960 (bt709) and 56-966 / 20-1004 (ebu-r103)."""
        clip = OUT / "levels10.mkv"
        known = legal_range_clip(clip, depth=10)
        n, _ = known["samples"]
        doc, _rows = self._levels(clip, "--levels", "bt709")
        self.assertEqual((doc["levels"]["bit_depth"], doc["levels"]["legal"]), (10, {"y": [64, 940], "c": [64, 960]}))
        self.assertAlmostEqual(doc["levels"]["out_of_range_pct"]["y"], sum(known["y"].values()) / n * 50, places=2)
        self.assertEqual((doc["levels"]["min"]["y"], doc["levels"]["max"]["y"]), (40, 1000))
        doc, _rows = self._levels(clip, "--levels", "ebu-r103")
        self.assertEqual(doc["levels"]["legal"], {"y": [56, 966], "c": [20, 1004]})
        self.assertAlmostEqual(doc["levels"]["out_of_range_pct"]["y"], (known["y"][10] + known["y"][250]) / n * 50, places=2)

    def test_check_levels_reads_the_depth_of_the_planes_not_of_the_name(self):
        """#432 review: nv12 is 8-bit 4:2:0 (the 12 in its name is bits per pixel). Its limits and mask
        are the 8-bit ones, so the same pattern counts the same shares as the planar 8-bit file; read
        as 12-bit, every legal sample would have been counted out of range."""
        planar = OUT / "levels8_for_nv12.mkv"
        known = legal_range_clip(planar)
        nv12 = OUT / "levels_nv12.nut"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", planar, "-c:v", "rawvideo", "-pix_fmt", "nv12", nv12)
        self.assertEqual(probe(str(nv12))["video"]["pix_fmt"], "nv12")
        self.assertEqual(content_probe.component_depth("nv12"), 8)
        self.assertEqual(content_probe.component_depth("p010le"), 10)
        doc, _rows = self._levels(nv12, "--levels", "bt709")
        n, _ = known["samples"]
        self.assertEqual((doc["levels"]["bit_depth"], doc["levels"]["legal"]), (8, {"y": [16, 235], "c": [16, 240]}))
        self.assertAlmostEqual(doc["levels"]["out_of_range_pct"]["y"], sum(known["y"].values()) / n * 50, places=2)

    def test_check_levels_is_not_measured_when_the_decode_fails_part_way(self):
        """#432 review: a measurement whose ffmpeg run exits non-zero, or whose two passes counted
        different frames, is None (the row says could not measure) -- never a share of the frames
        read before the failure."""
        import subprocess as sp
        from unittest import mock
        clip = OUT / "levels8_fail.mkv"
        legal_range_clip(clip)
        real = content_probe.run_analysis

        def failing(cmd, **kw):
            proc = real(cmd, **kw)
            return sp.CompletedProcess(proc.args, 1, proc.stdout, proc.stderr) if "lutyuv" in " ".join(map(str, cmd)) else proc

        with mock.patch.object(content_probe, "run_analysis", failing):
            self.assertIsNone(content_probe.measure_signal_range(str(clip), "bt709", bit_depth=8))

        def short(cmd, **kw):
            proc = real(cmd, **kw)
            if "lutyuv" not in " ".join(map(str, cmd)):
                return proc
            out = proc.stdout.split("frame:")
            return sp.CompletedProcess(proc.args, 0, "frame:".join(out[:-1]), proc.stderr)

        with mock.patch.object(content_probe, "run_analysis", short):
            self.assertIsNone(content_probe.measure_signal_range(str(clip), "bt709", bit_depth=8))
        self.assertIsNotNone(content_probe.measure_signal_range(str(clip), "bt709", bit_depth=8))

    def test_check_levels_is_opt_in_and_skips_a_picture_with_no_luma(self):
        """Without --levels the row set and the document are unchanged; a legal clip PASSes at 0 %;
        an RGB picture is not measured (WARN); a bad window or tolerance is refused before decoding."""
        legal = OUT / "levels_legal.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=10:d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", legal)
        doc, rows = self._levels(legal)
        self.assertNotIn("legal levels", rows)
        self.assertNotIn("levels", doc)
        doc, rows = self._levels(legal, "--levels", "bt709")
        self.assertEqual(rows["legal levels"]["status"], "PASS")
        self.assertEqual(doc["levels"]["out_of_range_pct"], {"y": 0.0, "u": 0.0, "v": 0.0, "chroma": 0.0})
        rgb = OUT / "levels_rgb.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=64x64:r=10:d=1",
           "-pix_fmt", "gbrp", "-c:v", "ffv1", rgb)
        doc, rows = self._levels(rgb, "--levels", "bt709")
        self.assertEqual(rows["legal levels"]["status"], "WARN")
        self.assertIn("not measured", rows["legal levels"]["value"])
        self.assertNotIn("levels", doc)
        for bad in (("--levels-window", "-1"), ("--levels-tolerance", "101")):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(legal), "--levels", "bt709", *bad, "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(proc.returncode, 1, bad)
            self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input", bad)

    def test_check_compare_times_the_worst_frame_and_counts_frames(self):
        """2.24: --compare names the worst frame by its presentation time (one damaged frame at
        2.5 s), counts frames from the packets when the container states no nb_frames (an .mkv two
        frames short of the reference), prints that note in plain text too, and keeps the row under
        --dry-run when both files exist."""
        ref = self._content_clip("compare_ref.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000", 3)
        hit = OUT / "compare_one_bad_frame.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref, "-t", "2.8",
           "-vf", "drawbox=t=fill:color=white:enable='eq(n,25)'", "-c:v", "libx264", "-crf", "12", "-an", hit)
        row = self._rows(hit, "--no-loudness", "--compare", ref)["similarity"]
        self.assertIn("at 2.50s", row["value"], row)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(hit), "--platform", "custom", "--no-loudness",
                               "--compare", str(ref)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertIn("note: --compare: 28 frames against the reference's 30", proc.stdout + proc.stderr)
        self.assertIn("similarity", self._rows(hit, "--no-loudness", "--compare", ref, "--dry-run"))

    def test_check_expect_changed_fails_on_a_change_outside_the_declaration(self):
        """#439: --compare --expect-changed SPAN[@X,Y,W,H]|none. A box drawn from 3 s to 5 s on
        0.7 % of the frame (which the whole-frame SSIM row passes) is found with its time and
        place; declared it PASSes, undeclared it FAILs, a declared span with no change WARNs, and
        a comparison that cannot be made is a FAIL, never a pass."""
        x264 = ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]
        src = "testsrc2=size=640x360:rate=10"
        old, new, small, short, other = (OUT / n for n in ("scope_old.mp4", "scope_new.mp4", "scope_small.mp4",
                                                           "scope_short.mp4", "scope_444.mp4"))
        box = "drawbox=x=520:y=300:w=80:h=40:color=red:t=fill:enable='between(t,3,5)'"
        lavfi = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i"]
        sh(*lavfi, src, "-t", "6", *x264, old)
        sh(*lavfi, src + "," + box, "-t", "6", *x264, new)
        sh(*lavfi, "testsrc2=size=320x180:rate=10", "-t", "6", *x264, small)
        sh(*lavfi, src, "-t", "5", *x264, short)
        sh(*lavfi, src, "-t", "6", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv444p", "-an", other)

        def check(path, *extra):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(path), "--platform", "custom", "--no-loudness",
                                   "--json", "--compare", str(old), *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            doc = json.loads(proc.stdout)
            return proc.returncode, doc, {r["check"]: r for r in doc.get("checks", [])}.get("change_scope")

        # the edit is invisible to the existing row, which is why the new one exists
        self.assertEqual(self._rows(new, "--no-loudness", "--compare", old)["similarity"]["status"], "PASS")
        code, doc, row = check(new, "--expect-changed", "3-5")
        self.assertEqual((code, row["status"]), (0, "PASS"), row)
        # the end is inclusive (between(t,3,5) draws on the frame at 5.0 s) and widened to the frame
        self.assertIn("changed 3.00-5.10 inside the declared span", row["value"])
        seen = doc["change_scope"]["observed"]
        self.assertEqual([(o["start"], o["end"], o["frames"]) for o in seen], [(3.0, 5.1, 21)])
        x, y, w, h = seen[0]["rect"]
        self.assertTrue(x <= 520 and y <= 300 and x + w >= 600 and y + h >= 340 and w <= 120 and h <= 80, seen)
        self.assertEqual(doc["change_scope"]["undeclared"], [])
        self.assertLessEqual(doc["change_scope"]["quiet_peak"], doc["change_scope"]["floor"])

        code, doc, row = check(new, "--expect-changed", "0.5-1")
        self.assertEqual((code, row["status"], doc["error"]["kind"]), (1, "FAIL", "verification"), row)
        self.assertIn("changed 3.00-5.10 (21 frames, around x", row["value"])
        self.assertIn("declared 0.50-1.00 but nothing changed there", row["value"])
        self.assertIn("look.py --compare", row["fix"])
        self.assertTrue(row["fix"].endswith("--at 3"), row["fix"])
        self.assertEqual(len(doc["change_scope"]["declared_unchanged"]), 1)

        self.assertEqual(check(new, "--expect-changed", "none")[2]["status"], "FAIL")
        self.assertEqual(check(old, "--expect-changed", "none")[2]["status"], "PASS")
        self.assertEqual(check(new, "--expect-changed", "3-5@500,280,140,80")[2]["status"], "PASS")
        elsewhere = check(new, "--expect-changed", "3-5@0,0,100,100")[2]
        self.assertEqual(elsewhere["status"], "FAIL", elsewhere)
        # two spans, one of them the edit: the other is only a warning
        code, doc, row = check(new, "--expect-changed", "3-5", "--expect-changed", "0-1")
        self.assertEqual((code, row["status"]), (0, "WARN"), row)
        self.assertIn("declared 0.00-1.00 but nothing changed there", row["value"])
        # --change-floor is the floor the pass uses and the document reports: at 254 only a tile
        # at full difference still counts (whether this edit has one depends on the FFmpeg build's
        # colour conversion: none on 6.1, some on later ones, so the status is not asserted)
        code, doc, row = check(new, "--expect-changed", "none", "--change-floor", "254")
        self.assertEqual(doc["change_scope"]["floor"], 254)
        self.assertTrue(all(o["peak"] == 255 for o in doc["change_scope"]["observed"]), doc["change_scope"]["observed"])
        self.assertEqual(row["status"], "FAIL" if doc["change_scope"]["observed"] else "PASS")
        self.assertIn("floor 254", row["value"])

        for path, why in ((small, "320x180 against 640x360"), (short, "50 frames against the reference's 60")):
            code, doc, row = check(path, "--expect-changed", "none")
            self.assertEqual((code, row["status"]), (1, "FAIL"), row)
            self.assertIn("not compared: " + why, row["value"])
            self.assertNotIn("change_scope", doc)
        code, doc, row = check(other, "--expect-changed", "none")
        self.assertNotEqual(row["status"], "PASS", row)
        self.assertTrue(any("not encoded alike (pix_fmt yuv444p against yuv420p)" in n for n in doc["notes"]), doc.get("notes"))

        # the pass itself failing is a FAIL too
        check_mod = check_module
        rows = []
        with unittest.mock.patch.object(check_mod, "change_tiles", return_value=None):
            args = types.SimpleNamespace(input=str(new), compare=str(old), change_floor=24)
            meta = check_mod.probe(str(new))
            out = check_mod.change_scope_row(args, [], meta, meta["video"], lambda *a, **k: rows.append(a))
        self.assertIsNone(out)
        self.assertEqual(rows[0][:2], ("change_scope", "FAIL"))
        self.assertIn("the comparison pass failed", rows[0][2])
        # no readable frame times: nothing can be placed or reported at a time, so it is not
        # compared, for a span and for `none` alike
        for declared in ([{"start": 3.0, "end": 5.0, "rect": None}], []):
            rows = []
            with unittest.mock.patch.object(check_mod, "presentation_times", return_value=[]):
                meta = check_mod.probe(str(new))
                args = types.SimpleNamespace(input=str(new), compare=str(old), change_floor=24)
                out = check_mod.change_scope_row(args, declared, meta, meta["video"], lambda *a, **k: rows.append(a))
            self.assertIsNone(out)
            self.assertEqual(rows[0][:2], ("change_scope", "FAIL"), rows)
            self.assertIn("not compared: the frame times could not be read", rows[0][2])

        # a rectangle is in displayed pixels: 180x180 stored at SAR 16:9 is a 320x180 picture, and a
        # box at stored x 120-170 is shown at x 213-302, past the stored width
        wide_old, wide_new = OUT / "scope_sar_old.mp4", OUT / "scope_sar_new.mp4"
        sar = "testsrc2=size=180x180:rate=10"
        sh(*lavfi, sar, "-t", "2", "-vf", "setsar=16/9", *x264, wide_old)
        sh(*lavfi, sar, "-t", "2", "-vf", "drawbox=x=120:y=60:w=50:h=60:color=red:t=fill,setsar=16/9", *x264, wide_new)

        def wide(*extra):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(wide_new), "--platform", "custom", "--no-loudness",
                                   "--json", "--compare", str(wide_old), *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            doc = json.loads(proc.stdout)
            return doc, {r["check"]: r for r in doc.get("checks", [])}.get("change_scope")

        doc, row = wide("--expect-changed", "0-2@200,50,115,80")
        self.assertEqual(row["status"], "PASS", row)
        x, y, w, h = doc["change_scope"]["observed"][0]["rect"]
        self.assertTrue(200 <= x <= 213 and x + w >= 302 and x + w <= 320, doc["change_scope"]["observed"])
        self.assertEqual(wide("--expect-changed", "0-2@0,0,180,180")[1]["status"], "FAIL", "the stored-pixel rectangle misses it")
        self.assertIn("does not fit inside the 320x180 picture", wide("--expect-changed", "0-2@300,0,40,40")[0]["error"]["message"])
        # the same displayed size stored another way (320x180 square against 180x180 at 16:9) is
        # compared, both squared, and the difference in storage is said: not a "not compared" that
        # prints two equal sizes
        flat = OUT / "scope_sar_flat.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wide_old, "-vf", "scale=320:180,setsar=1", *x264, flat)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(flat), "--platform", "custom", "--no-loudness", "--json",
                               "--compare", str(wide_old), "--expect-changed", "none"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        doc = json.loads(proc.stdout)
        row = {r["check"]: r for r in doc["checks"]}["change_scope"]
        self.assertNotIn("not compared", row["value"], row)
        self.assertIn("change_scope", doc)
        self.assertTrue(any("stored size 320x180 against 180x180" in n for n in doc["notes"]), doc["notes"])

        for bad, say in ((["--expect-changed", "3-5", "--expect-changed", "none"], "cannot be combined"),
                         (["--expect-changed", "5-3"], "ends at or after its start"),
                         (["--expect-changed", "nan-3"], "--expect-changed"),
                         (["--expect-changed", "3"], "START-END"),
                         (["--expect-changed", "3-5@1,2,3"], "X,Y,W,H"),
                         (["--expect-changed", "3-5@0,0,0,10"], "X,Y,W,H"),
                         (["--expect-changed", "3-5@700,0,10,10"], "does not fit inside the 640x360 picture"),
                         (["--expect-changed", "3-5@600,300,80,40"], "does not fit inside the 640x360 picture"),
                         (["--expect-changed", "none", "--change-floor", "0"], "outside 1..254")):
            code, doc, row = check(new, *bad)
            self.assertEqual((code, doc["error"]["kind"]), (1, "input"), (bad, doc))
            self.assertIn(say, doc["error"]["message"], bad)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(new), "--platform", "custom", "--no-loudness",
                               "--json", "--expect-changed", "3-5"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertIn("needs --compare", json.loads(proc.stdout)["error"]["message"])
        # a dry run measures nothing, as --compare does for a file an earlier stage would write
        code, doc, row = check(OUT / "scope_not_written_yet.mp4", "--expect-changed", "none", "--dry-run")
        self.assertEqual((code, row), (0, None), doc)

    def test_change_scope_is_closed_at_both_ends_and_holds_the_rest_of_a_rectangle_frame(self):
        """#439: the pure grading step. A declared span covers every frame whose own interval
        touches it; with a rectangle, tiles it does not touch are still held to "unchanged"."""
        check_mod = check_module
        times = [i / 10 for i in range(11)]            # 10 frames, 0.1 s each
        tiles = {"frames": 10, "changed": {3: 1, 4: 1 | 1 << (31 + 17 * 32), 5: 1}, "peaks": {3: 90, 4: 99, 5: 90}, "quiet_peak": 2}
        doc = check_mod.change_scope(tiles, [{"start": 0.3, "end": 0.5, "rect": None}], times, (640, 360), 24)
        self.assertEqual((doc["undeclared"], doc["declared_unchanged"]), ([], []))
        # 0.3-0.45 still reaches frame 4 (0.4-0.5), not frame 5
        doc = check_mod.change_scope(tiles, [{"start": 0.3, "end": 0.45, "rect": None}], times, (640, 360), 24)
        self.assertEqual([(u["start"], u["end"]) for u in doc["undeclared"]], [(0.5, 0.6)])
        doc = check_mod.change_scope(tiles, [{"start": 0.3, "end": 0.5, "rect": [0, 0, 20, 20]}], times, (640, 360), 24)
        self.assertEqual([(u["start"], u["frames"], u["rect"]) for u in doc["undeclared"]], [(0.4, 1, [620, 340, 20, 20])])
        self.assertEqual(doc["observed"][0]["rect"], [0, 0, 640, 360])
        # a turned file against an upright one of the same displayed size is still "stored another way"
        turned = {"codec": "h264", "pix_fmt": "yuv420p", "fps": 30.0, "width": 1080, "height": 1920, "rotation": 90}
        upright = dict(turned, width=1920, height=1080, rotation=0)
        self.assertEqual(check_mod.encoding_differences(turned, upright), ["stored size 1080x1920 against 1920x1080"])
        self.assertEqual(check_mod.encoding_differences(upright, dict(upright)), [])
        # two declarations that overlap: each is graded against the frame's own tiles, in either order
        whole, corner = {"start": 0.3, "end": 0.5, "rect": None}, {"start": 0.3, "end": 0.5, "rect": [0, 0, 20, 20]}
        for order in ([whole, corner], [corner, whole]):
            doc = check_mod.change_scope(tiles, order, times, (640, 360), 24)
            self.assertEqual((doc["undeclared"], doc["declared_unchanged"]), ([], []), order)

    def test_check_compare_pairs_only_existing_frames_and_is_order_and_rotation_safe(self):
        """2.24.1: a shorter output was paired with its last frame repeated (mean below 0.9 for 52
        identical frames, worst frame timed past the file's end); an RGB file gave "could not
        measure" (SSIM R:/PSNR r: lines) or another value by argument order; a phone clip stored
        sideways was compared by its stored size, so equal pictures were "not compared"."""
        ref = self._content_clip("compare_ref.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000", 3)
        short, rgb, side, upright = (OUT / n for n in ("compare_short.mp4", "compare_rgb.mkv", "compare_side.mp4", "compare_upright.mp4"))
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref, "-t", "1.5", "-c", "copy", short)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ref, "-c:v", "libx264rgb", "-crf", "0", "-an", rgb)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", ref, "-c", "copy", side)
        self.assertIn(abs(int(probe(str(side))["video"].get("rotation") or 0)), (90, 270))
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", side, "-c:v", "libx264", "-crf", "0", "-an", upright)
        row = self._rows(short, "--no-loudness", "--compare", ref)["similarity"]
        self.assertEqual(row["status"], "PASS", row)
        self.assertIn("identical", row["value"])
        self.assertNotIn(" 30 frames", row["value"])
        there, back = (self._rows(a, "--no-loudness", "--compare", b)["similarity"] for a, b in ((rgb, ref), (ref, rgb)))
        self.assertNotIn("could not measure", there["value"])
        self.assertEqual(there["value"].split(" (")[0], back["value"].split(" (")[0])
        self.assertNotIn("not compared", self._rows(upright, "--no-loudness", "--compare", side)["similarity"]["value"])

    def test_check_expect_identity_empty_is_malformed_not_absent(self):
        """2.24.1: --expect-identity "" (an unset shell variable) skipped the identity row and passed."""
        ref = self._content_clip("compare_ref.mp4", "testsrc2=size=160x90:rate=10", "sine=frequency=440:sample_rate=48000", 3)
        proc = script("check.py", ref, "--no-loudness", "--expect-identity", "", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def test_check_content_dropouts_row(self):
        """2.17: a short run of digital silence with sound on both sides (lost audio at a join) is a
        dropouts WARN; the same gap holding -60 dB room tone is a recording's pause and PASSes, and
        a silent lead-in or tail is not a dropout, also when the audio ends before the video. The
        silence row (share below -50 dB) misses all three: 0.2 s of 6 s is 3%."""
        def clip(name, audio_graph):
            path = OUT / name
            if not path.exists():
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=10:d=6",
                   "-f", "lavfi", "-i", "sine=f=440:d=6", "-f", "lavfi", "-i", "anoisesrc=a=0.001:d=6",
                   "-filter_complex", audio_graph, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-t", "6", path)
            return path
        gap = "volume='if(between(t,2,2.2),0,1)':eval=frame"
        dropped = clip("dropout_gap.mp4", f"[1]{gap}[a]")
        room = clip("dropout_roomtone.mp4", f"[1]{gap}[t];[t][2]amix=inputs=2:normalize=0[a]")
        edges = clip("dropout_edges.mp4", "[1]volume='if(lt(t,0.5)+gt(t,5.5),0,1)':eval=frame[a]")
        # audio 2 s shorter than the video, its last 0.2 s silent: silencedetect closes that tail at
        # the audio's EOF, well inside the container's 6 s, so only the padded pass keeps it a tail
        short = clip("dropout_short_audio.mp4", "[1]atrim=0:4,volume='if(gt(t,3.8),0,1)':eval=frame[a]")
        r = self._rows(dropped, "--content")
        self.assertEqual((r["silence"]["status"], r["dropouts"]["status"]), ("PASS", "WARN"), r)
        self.assertTrue(r["dropouts"]["value"].startswith("1: 2."), r["dropouts"])
        self.assertIn("join", r["dropouts"]["fix"])
        self.assertEqual(self._rows(room, "--content")["dropouts"]["status"], "PASS")
        self.assertEqual(self._rows(edges, "--content")["dropouts"]["status"], "PASS")
        self.assertEqual(self._rows(short, "--content")["dropouts"]["status"], "PASS")

    def test_check_colour_row_reads_the_matrix_tag(self):
        """#325: the colour row decided "untagged" from primaries and transfer only, so a file whose
        only tag is a BT.601 matrix passed as "untagged (players assume bt709)" while a tag-honouring
        player decodes it as BT.601. The tags are x264 VUI parameters (a label, no conversion)."""
        cases = {  # name: (x264 VUI params, status, value)
            "matrix-only-601": ("colormatrix=smpte170m", "WARN", "smpte170m matrix, primaries/transfer untagged"),
            "matrix-only-bt470bg": ("colormatrix=bt470bg", "WARN", "bt470bg matrix, primaries/transfer untagged"),
            "full-601": ("colorprim=smpte170m:transfer=smpte170m:colormatrix=smpte170m", "WARN", "smpte170m/smpte170m"),
            "709-601-matrix": ("colorprim=bt709:transfer=bt709:colormatrix=smpte170m", "WARN", "bt709/bt709, smpte170m matrix"),
            "matrix-only-709": ("colormatrix=bt709", "PASS", "bt709 matrix, primaries/transfer untagged (players assume bt709)"),
            "full-709": ("colorprim=bt709:transfer=bt709:colormatrix=bt709", "PASS", "bt709/bt709"),
            "untagged": ("scenecut=0", "PASS", "untagged (players assume bt709)"),
        }
        for name, (params, status, value) in cases.items():
            with self.subTest(name):
                path = OUT / f"colour_{name}.mp4"
                if not path.exists():
                    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                       "-f", "lavfi", "-i", "sine=sample_rate=48000", "-t", "1", "-pix_fmt", "yuv420p",
                       "-c:v", "libx264", "-x264-params", params, "-c:a", "aac", "-shortest", path)
                # the later --platform wins over _rows' custom, which passes any colour
                row = self._rows(path, "--no-loudness", "--platform", "reels")["colour"]
                self.assertEqual((row["status"], row["value"]), (status, value), row)
                if status == "PASS":
                    self.assertEqual((row["fix"], row["reason"]), ("", ""), row)
                else:
                    # every WARN here is a BT.601 matrix: a re-encode converts it (after 2.10.0), --retag bt709
                    # only relabels it, so the fix names the conversion first
                    self.assertTrue(row["fix"].startswith("export.py (any re-encode here converts the BT.601 matrix to BT.709)"), row)
                    self.assertIn("--retag bt709 only relabels", row["fix"])
                    self.assertIn("BT.601", row["reason"])

    def test_check_default_rows_unchanged_without_content(self):
        clip = self._content_clip("content_black.mp4", "color=black:size=160x90:rate=10",
                                  "sine=frequency=440:sample_rate=48000")
        rows = self._rows(clip, "--no-loudness")
        self.assertEqual(list(rows), ["duration", "aspect", "vfr", "colour", "audio", "subtitles"])
        self.assertEqual(rows["audio"]["status"], "PASS")

    def test_check_audio_row_fails_on_silent_track(self):
        silent = self._content_clip("content_silent.mp4", "testsrc2=size=160x90:rate=10", "anullsrc=r=48000:cl=mono")
        # FAIL under a loudness target; WARN with none (a muted screen recording is legitimate)
        for extra, status in ((["--lufs", "-14"], "FAIL"), (["--platform", "custom", "--no-loudness"], "WARN")):
            row = self._rows(silent, *extra)["audio"]
            self.assertEqual(row["status"], status, (extra, row))
            self.assertIn("silent", row["value"])

    def test_check_podcast_reports_chapters_and_channel_count(self):
        """1.13: two informational podcast rows. Neither may FAIL a delivery, and neither may
        appear for a platform that does not care."""
        data = json.loads(script("check.py", self.mic, "--platform", "podcast", "--no-loudness", "--json").stdout)
        rows = {r["check"]: r for r in data["checks"]}
        self.assertEqual(rows["chapters"]["status"], "WARN")
        self.assertEqual(rows["chapters"]["value"], "none")
        self.assertIn("metadata.py", rows["chapters"]["fix"])
        self.assertEqual(rows["channels"]["status"], "PASS", "mono is fine for a podcast")
        self.assertTrue(data["ok"], "informational rows never fail the delivery")
        # after metadata.py the chapters row passes
        chapters = OUT / "podcast_chapters.txt"
        chapters.write_text("0:00 Intro\n0:04 Body\n", encoding="utf-8")
        tagged = OUT / "podcast_tagged.m4a"
        script("audio.py", self.mic, "-o", OUT / "podcast.m4a")
        script("metadata.py", OUT / "podcast.m4a", "--chapters", chapters, "-o", tagged)
        rows = {r["check"]: r for r in json.loads(script("check.py", tagged, "--platform", "podcast", "--no-loudness", "--json").stdout)["checks"]}
        self.assertEqual(rows["chapters"]["status"], "PASS")
        self.assertEqual(rows["chapters"]["value"], "2")
        # 5.1 warns, with the reason a publisher needs
        rows = {r["check"]: r for r in json.loads(script("check.py", self.surround, "--platform", "podcast", "--no-loudness", "--json").stdout)["checks"]}
        self.assertEqual(rows["channels"]["status"], "WARN")
        self.assertIn("downmix", rows["channels"]["reason"])
        # absent for every other platform
        for platform in ("youtube", "reels"):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(self.src), "--platform", platform,
                                   "--no-loudness", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            names = {r["check"] for r in json.loads(proc.stdout)["checks"]}
            self.assertNotIn("chapters", names, platform)
            self.assertNotIn("channels", names, platform)

    def test_sync_fine_resolution_and_drift(self):
        data = json.loads(script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--json").stdout)
        self.assertClose(data["offset_seconds"], 1.2, 0.01, "offset extrapolated to t=0 at 1 ms resolution")
        self.assertClose(data["drift"]["drift_ppm"], 500.0, 40.0)
        out = OUT / "drift_fixed.wav"
        script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--trim-second", "-o", out)
        again = json.loads(script("sync.py", self.long_ref, out, "--fix-drift", "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.01)
        self.assertClose(again["drift"]["drift_ppm"], 0.0, 40.0)

    def test_sync_drift_meaning_says_what_this_run_does(self):
        """#403: `drift.meaning` ended "it will be resampled to match" in a run that only measures
        (--fix-drift without --replace-audio or --trim-second writes nothing)."""
        data = json.loads(script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--json").stdout)
        self.assertIsNone(data["output"])
        self.assertNotIn("will be resampled", data["drift"]["meaning"])
        self.assertIn("nothing is resampled", data["drift"]["meaning"])
        out = OUT / "drift_meaning.wav"
        wrote = json.loads(script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--trim-second", "-o", out, "--json").stdout)
        self.assertIn("is resampled to match", wrote["drift"]["meaning"])
        self.assertNotIn("nothing is resampled", wrote["drift"]["meaning"])
        # a dry run of the same writes nothing: the resampling is planned, not done
        out.unlink(missing_ok=True)
        planned = json.loads(script("sync.py", self.long_ref, self.long_drift, "--fix-drift", "--trim-second", "-o", out,
                                    "--dry-run", "--json").stdout)
        self.assertFalse(out.exists())
        self.assertIn("would be resampled to match in the file this run plans", planned["drift"]["meaning"])
        self.assertNotIn("this run writes", planned["drift"]["meaning"])

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

    def test_look_scenes_overlay_graphics_prefer_fontfile_over_font_when_resolvable(self):
        """#100: drawtext's own fontconfig resolution (font=<name>) crashed with an access violation
        on some real Windows ffmpeg builds, with or without a valid fonts.conf; fontfile=<path> is
        the only form confirmed not to crash, since it never touches fontconfig at all. Every
        drawtext-using tool now resolves a concrete font file (default_font_file() in _common.text)
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

    def test_verify_full_plan_hdr_surround_broken_file_and_timeout(self):
        """verify.py's non---quick plan (overlay, look sheet, probe --analyze, loudness, silence,
        color --to-sdr + the HDR-preserved check on an HDR file, --downmix on >2ch audio), the
        "ffprobe failed" row for a file that is not media, the plain-text report path (no --json)
        and the per-step timeout were all unexercised: the two existing verify tests only ran
        --quick --json on good files (#147). A collection with one HDR10 file, one 5.1 file and
        one file of garbage bytes exits 1 (the garbage), while every step on the two real files
        still passes."""
        folder = OUT / "verify_full"
        folder.mkdir(exist_ok=True)
        (folder / Path(self.hdr).name).write_bytes(Path(self.hdr).read_bytes())
        (folder / Path(self.surround).name).write_bytes(Path(self.surround).read_bytes())
        (folder / "broken.mp4").write_bytes(b"this is not a media file\n" * 64)
        out = OUT / "verify_full_out"
        report = OUT / "verify_full.md"
        proc = script("verify.py", folder, "--seconds", "2", "--keep", "--out", out, "--report", report, expect_fail=True)
        text = report.read_text(encoding="utf-8")
        self.assertIn(text.strip(), proc.stdout.strip(), "without --json the report is printed to stdout")
        # the probe row carries probe's own message (nothing happens silently, part 2), not a fixed "ffprobe failed"
        probe_row = re.search(r"^\| probe \| FAIL \| 0s \| (ffprobe failed on .*broken\.mp4.*) \|$", text, re.M)
        self.assertTrue(probe_row, text)
        self.assertIn("| * | SKIP |", text)
        for step in ("overlay text", "look sheet", "probe analyze", "loudness measure", "silence list",
                     "color to-sdr", "hdr preserved", "audio downmix", "export x"):
            self.assertIn(f"| {step} | PASS |", text, f"{step} missing or failed:\n{text}")
        self.assertNotIn("| FAIL |", text.replace(probe_row.group(0), ""))
        self.assertTrue((out / f"{Path(self.hdr).stem}_sdr.mp4").exists())
        self.assertTrue((out / f"{Path(self.surround).stem}_st.mp4").exists())
        # a per-step timeout is reported per step, never raised
        data = json.loads(script("verify.py", self.src, "--quick", "--timeout", "0.01", "--json", expect_fail=True).stdout)
        self.assertEqual((data["status"], data["error"]["kind"]), ("failed", "verification"))
        # verify's own step limit, or (since #415 bounds a child's ffprobe by --timeout too) the
        # child's own timeout: either way a step row of kind timeout
        timed_out = [s for f in data["files"] for s in f["steps"]
                     if s["error"].startswith("timeout after") or s.get("kind") == "timeout"]
        self.assertTrue(timed_out, data)
        self.assertEqual(data["failed"], len(timed_out))
        # 0 means no limit here as on every other tool; it timed every step out at 0 s before 2.17.4
        data = json.loads(script("verify.py", self.src, "--quick", "--timeout", "0", "--json").stdout)
        self.assertEqual((data["status"], data["failed"]), ("completed", 0), data)

    def test_check_compliance(self):
        reels = OUT / "analysis_reels_crop.mp4"   # its own name: test_delivery writes export_reels.mp4 with --fit pad
        if not reels.exists():
            script("export.py", self.src, "--preset", "reels", "--fit", "crop", "-o", reels)
        data = json.loads(script("check.py", reels, "--platform", "reels", "--json", expect_fail=True).stdout)
        # a failed check is a failed run: status says so (before 1.4.3 it said "completed" next to exit 1)
        self.assertEqual((data["status"], data["error"]["kind"], data["error"]["code"]), ("failed", "verification", "VERIFICATION_FAILED"))
        self.assertFalse(data["ok"])
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

    def test_check_without_a_platform_reports_judgement_rows_as_warn(self):
        """Eval 7: runs that only wanted the format rows got youtube's loudness / true-peak FAILs
        (the default platform) and explained at length why they left them alone. Without a
        named platform those rows are advisory: WARN, exit 0, and a notes line says so."""
        data = json.loads(script("check.py", self.src, "--json").stdout)
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["ok"])
        self.assertEqual(data["failed"], 0)
        rows = {r["check"]: r for r in data["checks"]}
        self.assertEqual(rows["true peak"]["status"], "WARN")
        self.assertEqual(rows["loudness"]["kind"], "judgement")
        self.assertEqual(rows["true peak"]["kind"], "judgement")
        self.assertTrue(any("no --platform" in n for n in data["notes"]))
        # the same file with the platform named is the same FAIL as before
        data = json.loads(script("check.py", self.src, "--platform", "youtube", "--json", expect_fail=True).stdout)
        self.assertFalse(data["ok"])
        self.assertNotIn("notes", data)

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

    def test_social_pack_writes_one_file_per_destination_and_a_table(self):
        """--template all / a comma list: one edit, N deliveries, one table. The table is what the
        user is handed, so it must have exactly one row per destination and name the real files."""
        doc = json.loads(script("render.py", self.src, "--template", "tiktok,x,linkedin",
                                "--cues", self.cues, "--fast", "--json").stdout)
        self.assertEqual([r["platform"] for r in doc["pack"]], ["tiktok", "x", "linkedin"])
        for row in doc["pack"]:
            self.assertTrue(os.path.exists(row["path"]), row)
            self.assertEqual(row["check"], "pass", row)
        pack = Path(doc["output"])
        self.assertTrue(pack.exists())
        body = pack.read_text(encoding="utf-8")
        rows = [l for l in body.splitlines() if l.startswith("|") and not set(l.strip("| ")) <= set("-: |")]
        self.assertEqual(len(rows), 4, "one header row plus one row per destination")
        html_out = OUT / "pack.html"
        script("report.py", "--pack", pack, "-o", html_out)
        html_text = html_out.read_text(encoding="utf-8")
        for name in ("tiktok", "x", "linkedin"):
            self.assertIn(name, html_text)

    def test_check_and_export_read_one_loudness_spec_per_platform(self):
        """The 1.14 table exists so `export.py --normalize` and `check.py` cannot drift: the
        loudness a preset normalises to is read from the same entry the check enforces."""
        sys.path.insert(0, str(SCRIPTS))
        import export as export_mod
        from check import SPECS
        from _platforms import loudness_of
        for preset, platform in export_mod.PLATFORM_OF.items():
            with self.subTest(preset=preset):
                spec = SPECS[platform]
                table = loudness_of(platform)
                self.assertEqual((spec["lufs"], spec["lufs_tol"], spec["tp"]),
                                 (table["lufs"], table["lufs_tol"], table["tp"]))

    def test_look_safe_shades_only_the_platforms_occluded_zones(self):
        """`look.py --safe tiktok` is how "is the caption readable" gets answered about the app and
        not just the file: the bottom fifth and the right column come back visibly marked, the
        middle of the frame untouched."""
        plain, marked = OUT / "safe_plain.png", OUT / "safe_marked.png"
        script("look.py", self.src, "--at", "2", "--no-timecode", "-o", plain)
        doc = json.loads(script("look.py", self.src, "--at", "2", "--no-timecode", "--safe", "tiktok",
                                "-o", marked, "--json").stdout)
        self.assertTrue(os.path.exists(doc["output"]))
        self.assertEqual(png_size(plain), png_size(marked))
        self.assertNotEqual(plain.read_bytes(), marked.read_bytes(), "--safe must mark the frame")
        cmd = [c for c in doc["commands"] if "drawbox" in c]
        self.assertTrue(cmd, doc["commands"])
        self.assertIn("y=ih*(1-0.22)", cmd[0])
        self.assertIn("x=iw*(1-0.14)", cmd[0])

    def test_look_guides_outline_broadcast_safe_areas_on_the_preview_only(self):
        """#423: --guides draws action (93 %), title (90 %) and the 4:3 centre cut on the PNG; the
        frame's middle and its size are untouched, and a frame no wider than 4:3 refuses 4:3."""
        plain, marked = OUT / "guides_plain.png", OUT / "guides_marked.png"
        script("look.py", self.src, "--at", "2", "--no-timecode", "-o", plain, "--overwrite")
        doc = json.loads(script("look.py", self.src, "--at", "2", "--no-timecode", "--guides", "title,action,4:3",
                                "-o", marked, "--json", "--overwrite").stdout)
        self.assertEqual(png_size(plain), png_size(marked))
        self.assertNotEqual(plain.read_bytes(), marked.read_bytes())
        self.assertEqual([g["guide"] for g in doc["guides"]], ["title", "action", "4:3"])
        cmd = next(c for c in doc["commands"] if "drawbox" in c)
        self.assertIn("x=iw*0.035:y=ih*0.035:w=iw*0.93:h=ih*0.93", cmd)
        self.assertIn("x=iw*0.05:y=ih*0.05:w=iw*0.9:h=ih*0.9", cmd)
        self.assertIn("w=ih*4/3:h=ih", cmd)
        square = OUT / "guides_square.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x320:r=10:d=1",
           "-c:v", "libx264", square)
        proc = script("look.py", square, "--at", "0.5", "--guides", "4:3", "--json", expect_fail=True)
        self.assertIn("4:3 centre cut", json.loads(proc.stdout)["error"]["message"])
        # #430 review: under --compare the guides are drawn on each picture as scaled, before the pad
        # that letterboxes it (a 2:1 clip beside 16:9 got guides from the padded height); the
        # timecode is drawn after it
        wide = OUT / "guides_wide.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x320:r=10:d=1",
           "-c:v", "libx264", wide)
        doc = json.loads(script("look.py", self.src, "--compare", wide, "--at", "0.5", "--guides", "title,4:3", "--json",
                                "-o", OUT / "guides_compare_wide.png").stdout)
        graph = next(c for c in doc["commands"] if "hstack" in c)
        for branch in graph.split(";")[:2]:
            self.assertLess(branch.rindex("drawbox"), branch.index("pad="), branch)
            if "drawtext" in branch:  # a build without drawtext (Homebrew's) draws no stamp
                self.assertLess(branch.index("pad="), branch.index("drawtext"), branch)
        # #430 review: the guides are drawn on both pictures of --compare, so the second is checked too
        proc = script("look.py", self.src, "--compare", square, "--at", "0.5", "--guides", "4:3", "--json",
                      "-o", OUT / "guides_compare.png", expect_fail=True)
        self.assertIn("--compare clip", json.loads(proc.stdout)["error"]["message"])
        proc = script("look.py", square, "--at", "0.5", "--guides", "nope", "--json", expect_fail=True)
        self.assertIn("--guides takes", json.loads(proc.stdout)["error"]["message"])

    def test_look_safe_compares_the_displayed_aspect_of_a_rotated_source(self):
        """A 1280x720 file tagged 90 degrees is already 9:16. --safe tiktok used to warn that
        the stored 16:9 frame was the wrong shape for a destination the picture already matches."""
        v = probe(str(self.rot))["video"]
        self.assertIn(v["rotation"], (90, -90, 270, -270))
        proc = script("look.py", self.rot, "--at", "1", "--no-timecode", "--safe", "tiktok",
                      "-o", OUT / "safe_rot.png", "--json")
        self.assertNotIn("not tiktok", proc.stderr)
        self.assertNotIn(f"{v['width']}x{v['height']}", proc.stderr)
        wide = script("look.py", self.src, "--at", "1", "--no-timecode", "--safe", "tiktok",
                      "-o", OUT / "safe_wide.png", "--json")
        self.assertIn(f"{v['width']}x{v['height']}", wide.stderr)

    def test_report_html(self):
        reels = OUT / "analysis_reels_crop.mp4"   # its own name: test_delivery writes export_reels.mp4 with --fit pad
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

    # ------------------------------------------------------ 1.17: the beat grid (scenes --beats)
    def test_scenes_beats_measures_the_tempo(self):
        data = json.loads(script("scenes.py", self._beats(), "--beats", "--json").stdout)
        grid = data["beat_grid"]
        self.assertAlmostEqual(grid["tempo_bpm"], 120.0, delta=2.0)
        self.assertTrue(grid["usable"])
        self.assertGreater(grid["confidence"], 0.5)
        self.assertEqual(grid["method"], "rms-flux-autocorrelation")
        self.assertEqual(grid["range_bpm"], [60.0, 200.0])
        self.assertEqual(grid["supported"] + grid["unsupported"], len(data["beats"]))
        self.assertEqual(len(grid["supported_beats"]), grid["supported"])
        self.assertGreater(len(data["beats"]), 10)
        # the existing document is untouched
        self.assertIn("scenes", data)
        self.assertIn("audio_peaks", data)

    def test_scenes_without_beats_reports_no_grid(self):
        data = json.loads(script("scenes.py", self._beats(), "--json").stdout)
        self.assertNotIn("beat_grid", data)
        self.assertNotIn("beats", data)

    def test_scenes_beats_reports_a_weak_measurement_rather_than_refusing(self):
        """scenes.py measures; it does not refuse. A low confidence is reported as usable: false
        -- refusing belongs to the tools that would change a file on the strength of it."""
        data = json.loads(script("scenes.py", self._silent_clip(), "--beats", "--json").stdout)
        self.assertLess(data["beat_grid"]["confidence"], 0.5)
        self.assertFalse(data["beat_grid"]["usable"])

    def test_scenes_beats_refuses_without_an_audio_stream(self):
        mute = OUT / "beats_mute.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self._beats(),
           "-an", "-c:v", "copy", mute)
        r = script("scenes.py", mute, "--beats", "--json", expect_fail=True)
        data = json.loads(r.stdout)
        self.assertEqual(data["error"]["kind"], "input")
        self.assertIn("audio stream", data["error"]["message"])

    def test_scenes_beat_range_is_validated(self):
        r = script("scenes.py", self._beats(), "--beats", "--beat-range", "notarange",
                   "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_scenes_beat_range_is_ignored_without_beats(self):
        """--beat-range is a --beats flag: a run that never asked for beats must not be able to
        die on one."""
        data = json.loads(script("scenes.py", self._beats(), "--beat-range", "notarange",
                                 "--json").stdout)
        self.assertNotIn("beat_grid", data)

    # ------------------------------------------- After 3.2.0: --beats on an audio-only file, to 20 ms
    @staticmethod
    def _click_track(name, bpm, first, seconds=20, ext="wav"):
        """An audio-only click track (no video stream): a 1 kHz click decaying over 3 ms, every
        60/bpm s from `first`. Returns (path, the click times). The interval is written as a
        fraction so 90 BPM is exactly 2/3 s, not 0.667 s."""
        path = OUT / f"{name}.{ext}"
        iv = f"(60/{bpm})"
        ph = f"(t-{first})"
        click = (f"0.8*sin(2*PI*1000*t)*exp(-mod({ph}\\,{iv})/0.003)"
                 f"*lt(mod({ph}\\,{iv})\\,0.01)*gte(t\\,{first})")
        if not path.exists():
            codec = {"wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"], "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"]}[ext]
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"aevalsrc='{click}':s=44100", "-t", str(seconds), *codec, path)
        interval = 60.0 / bpm
        times, k = [], 0
        while first + k * interval < seconds - 0.05:
            times.append(first + k * interval)
            k += 1
        return path, times

    def _assert_every_click_within(self, data, times, tol):
        """Every click time has a grid point within `tol`, and the grid has exactly one point per
        click over the span the clicks cover (no doubled or skipped beat)."""
        beats = data["beats"]
        worst = max(min(abs(b - t) for b in beats) for t in times)
        self.assertLess(worst, tol, f"a click is {worst * 1000:.1f} ms from the nearest beat "
                                    f"(tempo {data['beat_grid']['tempo_bpm']}, phase {data['beat_grid']['phase']})")
        # and the grid has no extra beat inside the music: one grid point per click
        inside = [b for b in beats if times[0] - tol <= b <= times[-1] + tol]
        self.assertEqual(len(inside), len(times))

    def test_scenes_beats_on_an_audio_only_wav_lands_every_beat_within_20ms(self):
        """sound-design-skill's generate-bgm --bpm writes a WAV and a beat grid with the first beat
        at 0 s, and checks it against scenes.py --beats to 20 ms. Before this fix an audio-only file
        was refused ("input has no video stream"), and wrapped in a video the grid was 40-90 ms
        off a click track: the envelope step was timed at 10 ms when it is 220/22050 s, and the
        tempo was a whole number of steps (90 BPM measured as 0.67 s)."""
        for bpm, first in ((120, 0.0), (90, 0.0), (120, 0.25), (90, 0.137)):
            with self.subTest(bpm=bpm, first=first):
                path, times = self._click_track(f"clicks_{bpm}_{first}", bpm, first)
                self.assertIsNone(probe(str(path)).get("video"))
                data = json.loads(script("scenes.py", path, "--beats", "--json").stdout)
                grid = data["beat_grid"]
                self.assertTrue(data["audio_only"])
                self.assertEqual(data["scene_count"], 1)
                self.assertAlmostEqual(grid["tempo_bpm"], float(bpm), delta=0.1)
                self.assertTrue(grid["usable"])
                self.assertEqual(grid["onset_refinement"], "pcm-window-ratio")
                self._assert_every_click_within(data, times, 0.020)

    def test_scenes_beats_on_flac_and_mp3_within_20ms(self):
        """The same 20 ms on a lossless (FLAC) and a lossy (MP3) music bed."""
        for ext in ("flac", "mp3"):
            with self.subTest(ext=ext):
                path, times = self._click_track("clicks_90_0.137", 90, 0.137, ext=ext)
                data = json.loads(script("scenes.py", path, "--beats", "--json").stdout)
                self.assertAlmostEqual(data["beat_grid"]["tempo_bpm"], 90.0, delta=0.1)
                self._assert_every_click_within(data, times, 0.020)

    def test_scenes_audio_only_refuses_what_needs_a_picture(self):
        """--sheet and --shots have no picture to read on an audio-only file: refused, kind input,
        and no sheet is written."""
        path, _ = self._click_track("clicks_120_0.0", 120, 0.0)
        for flag in (["--sheet", str(OUT / "audio_only_sheet.png")], ["--shots"]):
            with self.subTest(flag=flag[0]):
                r = script("scenes.py", path, *flag, "--json", expect_fail=True)
                err = json.loads(r.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn(flag[0], err["message"])
                self.assertIn("no video stream", err["message"])
        self.assertFalse((OUT / "audio_only_sheet.png").exists())

    def test_scenes_audio_only_without_beats_is_one_scene(self):
        """No picture, no cut: the file is one scene, and the sound measurements still run."""
        path, _ = self._click_track("clicks_120_0.0", 120, 0.0)
        data = json.loads(script("scenes.py", path, "--audio-peaks", "--speech", "--highlights", "1", "--json").stdout)
        self.assertTrue(data["audio_only"])
        self.assertEqual([(sc["start"], sc["end"]) for sc in data["scenes"]], [(0.0, 20.0)])
        for key in ("audio_peaks", "audio_peaks_db", "speech", "highlights"):
            self.assertTrue(data[key], key)
        self.assertNotIn("beat_grid", data)

    def test_scenes_video_input_has_no_audio_only_key(self):
        """A video input's document is unchanged: audio_only is present only for audio-only input."""
        data = json.loads(script("scenes.py", self._beats(), "--json").stdout)
        self.assertNotIn("audio_only", data)

    def test_scenes_dry_run_on_a_pending_input_skips_the_measurement(self):
        """In a render.py/batch.py dry-run plan the input can be an earlier stage's output that was
        never written. scenes.py ran scdet and the audio decode on it anyway and failed in ffmpeg,
        so the plan could not be written; the measurement is now skipped and recorded, as
        loudness.py and cut.py do."""
        for name in ("pending_stage.wav", "pending_stage.mp4"):
            with self.subTest(name=name):
                missing = OUT / name
                self.assertFalse(missing.exists())
                doc = json.loads(script("scenes.py", missing, "--dry-run", "--beats", "--audio-peaks",
                                        "--speech", "--highlights", "1", "--json").stdout)
                self.assertEqual(doc["status"], "completed")
                self.assertEqual([s["code"] for s in doc["diagnostics"]["skipped"]], ["measurement_input_pending"])
                self.assertEqual(doc["beats"], [])
                self.assertFalse(doc["beat_grid"]["usable"])
                self.assertEqual(doc["audio_peaks_db"], [])
                self.assertEqual(doc["speech"], [])
        # with --sheet too: no scene was measured, and the sheet's select summed an empty list by
        # recursing on it (RecursionError, a traceback instead of the plan); it plans one tile
        doc = json.loads(script("scenes.py", OUT / "pending_stage.mp4", "--dry-run", "--sheet",
                                OUT / "pending_sheet.png", "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertIn("tile=1x1", doc["commands"][-1])

    def test_scenes_beats_decodes_with_check_so_a_failed_decode_is_not_no_pulse(self):
        """A decode that failed came back as [] and was reported as "no steady pulse in this audio".
        With --beats the decode is checked (it fails as ffmpeg); without it the scene scoring still
        tolerates a failed decode and runs on the picture."""
        import importlib.util
        import unittest.mock
        path, _ = self._click_track("clicks_120_0.0", 120, 0.0)
        spec = importlib.util.spec_from_file_location("scenes_under_test", SCRIPTS / "scenes.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        calls = []

        def fake_decode(p, rate, *a, check=True, **k):
            calls.append(check)
            if check:
                raise SystemExit(1)   # what decode_pcm_mono(check=True) does on a failed decode
            return []
        for argv, expect_exit in ((["--beats"], True), (["--audio-peaks"], False)):
            with self.subTest(argv=argv):
                calls.clear()
                with unittest.mock.patch.object(mod, "decode_pcm_mono", fake_decode), \
                     unittest.mock.patch.object(sys, "argv", ["scenes.py", str(path), *argv, "--json"]), \
                     unittest.mock.patch("sys.stdout", new_callable=__import__("io").StringIO):
                    if expect_exit:
                        with self.assertRaises(SystemExit):
                            mod.main()
                    else:
                        mod.main()
                self.assertEqual(calls[0], expect_exit)

    # --------------------------------------------------------------- 1.18.0: --shots / --audio-peaks / --speech
    def test_scenes_shots_labels_every_scene(self):
        data = json.loads(script("scenes.py", self.src, "--shots", "--json").stdout)
        self.assertIn("shots", data)
        self.assertEqual(len(data["shots"]), data["scene_count"])
        for sh in data["shots"]:
            self.assertIn(sh["label"], ("static", "pan", "motion"))
            self.assertGreaterEqual(sh["flow_magnitude"], 0.0)
            self.assertIn("start", sh)
            self.assertIn("end", sh)

    def test_scenes_shots_static_clip_is_labelled_static(self):
        """A single unmoving frame held for the whole clip has nothing to flow: static, magnitude 0."""
        still = OUT / "still.mp4"
        if not still.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=c=gray:s=320x180:rate=10", "-f", "lavfi", "-i", "sine=f=440",
               "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", still)
        data = json.loads(script("scenes.py", still, "--shots", "--json").stdout)
        self.assertTrue(all(sh["label"] == "static" for sh in data["shots"]))
        self.assertTrue(all(sh["flow_magnitude"] == 0.0 for sh in data["shots"]))

    def test_scenes_audio_peaks_db_is_measured_in_dbfs_and_separate_from_the_rms_list(self):
        data = json.loads(script("scenes.py", self.src, "--audio-peaks", "--json").stdout)
        self.assertIn("audio_peaks_db", data)
        self.assertIn("audio_peaks", data)  # the pre-existing key, unchanged
        for p in data["audio_peaks_db"]:
            self.assertIn("time", p)
            self.assertIn("level", p)
            self.assertLess(p["level"], 0)  # dBFS, not linear RMS

    def test_scenes_speech_reports_a_ratio_not_a_label(self):
        data = json.loads(script("scenes.py", self.src, "--speech", "--json").stdout)
        self.assertIn("speech", data)
        self.assertGreater(len(data["speech"]), 0)
        for w in data["speech"]:
            self.assertIn("time", w)
            self.assertIn("speech_music_ratio", w)
            self.assertGreaterEqual(w["speech_music_ratio"], 0.0)

    def test_scenes_shots_audio_peaks_speech_combine_with_beats_and_highlights(self):
        data = json.loads(script("scenes.py", self._beats(), "--shots", "--audio-peaks", "--speech",
                                 "--beats", "--highlights", "2", "--json").stdout)
        for key in ("shots", "audio_peaks_db", "speech", "beats", "highlights"):
            self.assertIn(key, data)


    def test_sync_too_short_names_the_file(self):
        blip = OUT / "sync_blip.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=0.1", blip)
        proc = script("sync.py", self.src, blip, "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertIn("not enough audio to analyse", doc["error"]["message"])
        self.assertIn(str(blip), doc["error"]["message"])

    # ---------------------------------------------------------------- issue #459: sync, scenes
    @staticmethod
    def _bursts(name, lead=0.0, seconds=20.0, repeat=1, rate=16000):
        """Seeded noise bursts of random length, level and spacing: an envelope with one true
        alignment. `lead` seconds of zeros go first; `repeat` plays the bursts that many times."""
        import random
        import struct
        import wave
        rnd = random.Random(7)
        n = int(rate * seconds)
        data = [0.0] * n
        t = 0.2
        while t < seconds:
            length, amp = rnd.uniform(0.05, 0.4), rnd.uniform(0.2, 0.9)
            for i in range(int(t * rate), min(n, int((t + length) * rate))):
                data[i] = amp * (rnd.random() * 2 - 1)
            t += length + rnd.uniform(0.1, 0.8)
        data = [0.0] * int(lead * rate) + data * repeat
        path = OUT / name
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(struct.pack("<h", int(x * 32767)) for x in data))
        return path

    def test_sync_confidence_tells_an_exact_match_from_a_tie(self):
        """A126: the runner-up the confidence is penalised by was the peak's own neighbour, one
        lag away, so a file against itself read 0.59 and a tie between two offsets (the same
        material twice) 0.50. The runner-up is now the best other peak."""
        bursts = self._bursts("a459_bursts.wav")
        later = self._bursts("a459_bursts_lead.wav", lead=1.5)
        twice = self._bursts("a459_bursts_twice.wav", repeat=2)
        same = json.loads(script("sync.py", bursts, bursts, "--json").stdout)
        self.assertEqual(same["offset_seconds"], 0.0)
        self.assertGreater(same["confidence"], 0.95)
        shifted = json.loads(script("sync.py", bursts, later, "--json").stdout)
        self.assertAlmostEqual(shifted["offset_seconds"], -1.5, delta=0.002)
        self.assertGreater(shifted["confidence"], 0.95)
        tie = json.loads(script("sync.py", twice, bursts, "--json").stdout)
        self.assertLess(tie["confidence"], 0.55, "two offsets fit equally well")

    def test_sync_help_states_the_correction_the_code_applies(self):
        """A133: --help said a positive offset means the second file must be shifted earlier; the
        code delays it, which is what lines it up. Measured: the --trim-second output's first
        burst lands on the reference's."""
        help_text = " ".join(script("sync.py", "--help").stdout.split())
        self.assertIn("a positive offset means the SECOND input starts LATER than the reference (it began recording "
                      "after it), so its sound is delayed by that amount", help_text)
        self.assertNotIn("shifted earlier", help_text)
        ref = self._bursts("a459_sync_ref.wav", lead=1.0, rate=48000)
        second = self._bursts("a459_sync_second.wav", rate=48000)
        data = json.loads(script("sync.py", ref, second, "--json").stdout)
        self.assertAlmostEqual(data["offset_seconds"], 1.0, delta=0.002, msg="the second started 1 s later")
        out = OUT / "a459_sync_trimmed.wav"
        script("sync.py", ref, second, "--trim-second", "-o", out)

        def onset(path):
            raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "48000",
                                  "-f", "s16le", "-"], stdout=subprocess.PIPE, check=True).stdout
            import array
            pcm = array.array("h")
            pcm.frombytes(raw[:len(raw) // 2 * 2])
            if sys.byteorder == "big":
                pcm.byteswap()
            return next(i for i, s in enumerate(pcm) if abs(s) > 300)
        self.assertLessEqual(abs(onset(out) - onset(ref)), 48, "delayed onto the reference, to the millisecond")

    def test_scenes_highlight_never_opens_before_its_scene(self):
        """A139: a pick's window started on the 0.5 s grid point at or before the scene's start,
        so with the loudness just before a cut at 3.4 s the pick was 3.0-4.0: it opened on the
        previous shot. Every pick (and every --edl line) now lies inside one scene."""
        src = OUT / "a459_highlight.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=64x64:r=30:d=3.4",
           "-f", "lavfi", "-i", "color=blue:s=64x64:r=30:d=4.6", "-f", "lavfi", "-i",
           "sine=f=400:d=8:r=48000,volume='if(between(t,2.9,3.9),6,0.05)':eval=frame",
           "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", src)
        edl = OUT / "a459_highlight.edl"
        data = json.loads(script("scenes.py", src, "--highlights", "2", "--max-scene", "1", "--edl", edl, "--json").stdout)
        scenes = [(s["start"], s["end"]) for s in data["scenes"]]
        self.assertEqual(len(scenes), 2, "fixture: one cut")
        self.assertAlmostEqual(scenes[1][0], 3.4, delta=0.034)
        lines = [tuple(float(x) for x in line.split("-")) for line in edl.read_text().split()]
        self.assertEqual(lines, [(h["start"], h["end"]) for h in data["highlights"]])
        for start, end in lines:
            with self.subTest(pick=(start, end)):
                self.assertTrue(any(s <= start and end <= e for s, e in scenes), f"{start}-{end} spans a cut: {scenes}")
        self.assertIn(3.4, [start for start, _ in lines], "the loud window of the second scene starts on its cut")

    def test_scenes_highlight_never_writes_an_empty_range(self):
        """A pick shorter than the hundredth it is written in was rounded inward to 0.00-0.00 and
        written to --edl, a range cut.py --segments refuses. No range fits: the run is refused
        (kind input) and no EDL is written."""
        src = OUT / "a459_one_second.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1:r=48000", src)
        edl = OUT / "a459_empty_picks.txt"
        if edl.exists():
            edl.unlink()
        proc = script("scenes.py", src, "--highlights", "1", "--target", "0.006", "--edl", edl, "--json", expect_fail=True)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("0.01 s", err["message"])
        self.assertFalse(edl.exists(), "no EDL of an empty range")
        # a pick that fits is written as before
        data = json.loads(script("scenes.py", src, "--highlights", "1", "--target", "0.5", "--edl", edl, "--json").stdout)
        self.assertEqual(len(data["highlights"]), 1)
        self.assertGreater(data["highlights"][0]["end"], data["highlights"][0]["start"])

    def test_decoded_pcm_takes_a_few_bytes_a_sample(self):
        """A140: decode_pcm_mono() returned a list of Python floats, ~32 bytes a sample, which is
        what scenes.py (and multicam --switch energy per camera) held for a whole file: ~2.3 GB an
        hour. Measured with tracemalloc on 20 s at 8 kHz; the values are the s16 samples / 32768."""
        import array
        import tracemalloc
        src = OUT / "a459_pcm_src.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=20:r=8000,volume=5",
           "-c:a", "pcm_s16le", src)
        tracemalloc.start()
        try:
            samples = content_probe.decode_pcm_mono(str(src), 8000)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(samples), 160000)
        self.assertLess(peak / len(samples), 12, f"{peak / len(samples):.1f} bytes a sample at the peak")
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "8000",
                              "-f", "s16le", "-"], stdout=subprocess.PIPE, check=True).stdout
        ref = array.array("h")
        ref.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            ref.byteswap()
        self.assertEqual(list(samples[:4000]), [v / 32768.0 for v in ref[:4000]], "the same values, exactly")

    def test_scenes_sheet_of_thousands_of_scenes_is_written(self):
        """A138: --sheet's select expression is ~50 characters a scene, and 3,000 scenes exceed
        Linux's 128 KiB argument limit: OSError E2BIG, a traceback and no JSON. The runner hands a
        filter graph that long to ffmpeg in a file. Measured: one tile per scene, in order, each
        the grey of its own scene."""
        src = OUT / "a459_many_scenes.mp4"
        # a new grey every 3 frames (luma 97*k mod 256): 3,000 cuts in 300 s of 32x18
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "nullsrc=s=32x18:r=30,geq=lum='mod(floor(N/3)*97\\,256)':cb=128:cr=128,format=yuv420p",
           "-frames:v", "9000", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", src)
        sheet = OUT / "a459_many_scenes.png"
        data = json.loads(script("scenes.py", src, "--min-scene", "0.05", "--sheet", sheet, "--no-timecode", "--json").stdout)
        self.assertEqual(data["scene_count"], 3000, "fixture")
        self.assertEqual(data["status"], "completed")
        # 4 columns of 320x180 tiles with a 2 px margin and padding: 750 rows
        self.assertEqual(png_size(sheet), (4 * 320 + 3 * 2 + 4, 750 * 180 + 749 * 2 + 4))
        for k in (1, 2, 7, 1201, 2998):
            row, col = divmod(k, 4)
            x, y = 2 + col * 322 + 160, 2 + row * 182 + 90
            px = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(sheet), "-vf",
                                 f"crop=1:1:{x}:{y},format=gray", "-f", "rawvideo", "-"],
                                stdout=subprocess.PIPE, check=True).stdout[0]
            luma = (k * 97) % 256
            want = min(255, max(0, round((min(235, max(16, luma)) - 16) * 255 / 219)))
            with self.subTest(scene=k):
                self.assertAlmostEqual(px, want, delta=4)
        sheet.unlink()

    def test_scenes_sheet_select_expressions_do_not_grow_with_the_scene_count(self):
        """One select expression of 3,000 summed terms reached ffmpeg and FFmpeg 7.1 and later refused
        it ("Error while parsing expression", Cannot allocate memory); 6.1 took it. Every select
        in the --sheet graph holds at most SHEET_SELECT_TERMS terms, nested at most 6 deep, for any
        number of scenes, and every scene start is in exactly one of them."""
        import scenes
        self.assertLessEqual(scenes.SHEET_SELECT_TERMS, 64)
        for n in (1, 5, 64, 65, 3000, 30000):
            with self.subTest(scenes=n):
                starts = [0.1 * i for i in range(n)]
                graph = scenes.sheet_graph(starts, "[0:V:0]", "scale=320:-2", "tile=4x4")
                exprs = re.findall(r"select='([^']*)'", graph)
                self.assertTrue(exprs)
                terms = [e.count("gte(t") for e in exprs]
                self.assertLessEqual(max(terms), scenes.SHEET_SELECT_TERMS)
                self.assertEqual(sum(terms), n, "each scene is selected in one expression")
                for e in exprs:
                    depth = deepest = 0
                    for ch in e:
                        depth += {"(": 1, ")": -1}.get(ch, 0)
                        deepest = max(deepest, depth)
                    # 6 levels of the balanced sum, and 3 of one term: gte(), (isnan()+lt())
                    self.assertLessEqual(deepest, 6 + 3, e[:120])
                self.assertTrue(graph.endswith("[sheet]"))

    def test_scenes_beats_keep_their_refit_on_a_range_bound(self):
        """A146: the least-squares refit of the beat grid was discarded when it landed a hair past
        a --beat-range bound, so a tempo on the bound kept the step-rounded interval: 90 BPM under
        60-90 was measured 89.76 and the grid ended 80 ms off the clicks."""
        path, times = self._click_track("clicks_90_0.0", 90, 0.0)
        for bounds in ("60-90", "90-200", "60-200"):
            with self.subTest(beat_range=bounds):
                data = json.loads(script("scenes.py", path, "--beats", "--beat-range", bounds, "--json").stdout)
                self.assertAlmostEqual(data["beat_grid"]["tempo_bpm"], 90.0, delta=0.05)
                self._assert_every_click_within(data, times, 0.020)


class ProposeChaptersTests(unittest.TestCase):
    """1.16: the pure half of metadata.py --auto-chapters. No media, no subprocess."""

    def setUp(self):
        from _common import description_block, propose_chapters, fmt_chapter_time
        self.propose = propose_chapters
        self.block = description_block
        self.fmt = fmt_chapter_time

    def test_propose_chapters_always_starts_at_zero(self):
        got = self.propose(600, [(190.1, 192.4)], [], min_chapter=60)
        self.assertEqual(got[0]["at"], 0.0)
        self.assertEqual(got[0]["evidence"]["kind"], "start")
        self.assertEqual(self.propose(600, [], [], min_chapter=60),
                         [{"at": 0.0, "evidence": {"kind": "start"}, "title": "Chapter 1"}])

    def test_propose_chapters_merges_silence_and_scene_evidence(self):
        got = self.propose(600, [(190.1, 192.4)], [192.6], min_chapter=60)
        self.assertEqual(len(got), 2)
        ev = got[1]["evidence"]
        self.assertEqual(ev["kind"], "silence+scene")
        self.assertEqual(ev["silence"], [190.1, 192.4])
        self.assertEqual(ev["silence_length"], 2.3)
        self.assertEqual(ev["scene_at"], 192.6)
        self.assertEqual(got[1]["at"], 192.4, "a chapter starts where speech resumes")

    def test_propose_chapters_respects_min_chapter(self):
        silences = [(50, 51), (70, 71), (200, 202), (210, 211)]
        got = self.propose(600, silences, [], min_chapter=60)
        ats = [c["at"] for c in got]
        for a, b in zip(ats, ats[1:]):
            self.assertGreaterEqual(b - a, 60.0, ats)
        # and nothing within min_chapter of the end
        self.assertTrue(all(a < 600 - 60 for a in ats), ats)

    def test_propose_chapters_never_invents_a_title(self):
        got = self.propose(1200, [(100, 102), (300, 303), (700, 702)], [500.0], min_chapter=60)
        self.assertGreater(len(got), 2)
        for n, c in enumerate(got, start=1):
            self.assertEqual(c["title"], "Chapter %d" % n)
            self.assertRegex(c["title"], r"^Chapter \d+$")

    def test_max_chapters_drops_weakest_evidence_first(self):
        got = self.propose(1200, [(100, 100.5), (300, 305)], [700.0],
                           min_chapter=60, max_chapters=3)
        self.assertEqual(len(got), 3)
        kinds = [c["evidence"]["kind"] for c in got]
        self.assertEqual(kinds[0], "start")
        self.assertIn("silence", kinds)
        self.assertNotIn("scene", kinds, "a bare scene cut outranked a measured pause")
        self.assertEqual([c["at"] for c in got], sorted(c["at"] for c in got))

    def test_description_block_format(self):
        self.assertEqual(self.fmt(0), "00:00")
        self.assertEqual(self.fmt(192.9), "03:12", "the timestamp rounds DOWN to the second")
        self.assertEqual(self.fmt(3723.4), "1:02:03")
        chapters = [{"at": 0.0, "title": "Chapter 1"}, {"at": 192.4, "title": "Chapter 2"}]
        self.assertEqual(self.block(chapters), "00:00 Chapter 1\n03:12 Chapter 2")


class AutoChaptersTests(MediaFixtures):
    """1.16 end to end, on the fixture that has real silences."""

    def test_auto_chapters_writes_markers_and_description(self):
        gappy = self._gappy()
        out = OUT / "auto_chapters.mp4"
        chapters_txt = OUT / "auto_chapters.txt"
        desc = OUT / "auto_chapters_desc.txt"
        res = json.loads(script("metadata.py", gappy, "--auto-chapters", "--min-chapter", "1",
                                "--chapters-out", chapters_txt, "--description-out", desc,
                                "--json", "-o", out).stdout)
        auto = res["auto_chapters"]
        self.assertEqual(auto["titles"], "placeholder")
        self.assertTrue(res["streams_copied"], "nothing may be re-encoded")
        written = sh("ffprobe", "-v", "error", "-show_chapters", "-of", "json", out).stdout
        self.assertEqual(len(json.loads(written)["chapters"]), auto["kept"])
        for n, c in enumerate(auto["chapters"], start=1):
            self.assertEqual(c["title"], "Chapter %d" % n)
        self.assertTrue(desc.read_text(encoding="utf-8").startswith("00:00 "))
        # the chapters file round-trips through this tool's own --chapters reader
        again = OUT / "auto_chapters_again.mp4"
        script("metadata.py", gappy, "--chapters", chapters_txt, "-o", again)
        self.assertEqual(len(json.loads(sh("ffprobe", "-v", "error", "-show_chapters",
                                           "-of", "json", again).stdout)["chapters"]),
                         auto["kept"])

    def test_auto_chapters_excludes_the_manual_forms(self):
        script("metadata.py", self._gappy(), "--auto-chapters", "--chapters", "/nope.txt",
               "-o", OUT / "x_auto.mp4", expect_fail=True)
        script("metadata.py", self._gappy(), "--auto-chapters", "--clear-chapters",
               "-o", OUT / "x_auto2.mp4", expect_fail=True)


class BeatGridTests(unittest.TestCase):
    """1.17: the beat grid and the snap, as pure arithmetic on an envelope.

    Nothing here decodes anything -- that is the point: a beat is measured from numbers, and the
    measurement can be tested without a media file.
    """

    STEP = 0.01

    @staticmethod
    def _clicks(interval, seconds=10.0, step=0.01, strengths=None, floor=0.01):
        """An RMS envelope with an impulse every `interval` seconds -- a click track."""
        n = int(round(seconds / step))
        env = [floor] * n
        k = 0
        t = 0.0
        while t < seconds:
            i = int(round(t / step))
            amp = 1.0 if strengths is None else strengths[k % len(strengths)]
            if i < n - 1:
                env[i] = amp
                env[i + 1] = amp * 0.6
            t += interval
            k += 1
        return env

    def test_synthetic_120bpm_grid(self):
        from _common import beat_grid
        g = beat_grid(self._clicks(0.5), self.STEP)
        self.assertAlmostEqual(g["tempo_bpm"], 120.0, delta=1.0)
        self.assertAlmostEqual(g["interval"], 0.5, delta=0.01)
        self.assertGreater(g["confidence"], 0.8)
        self.assertTrue(g["usable"])
        self.assertEqual(g["method"], "rms-flux-autocorrelation")
        # every beat lands within 15 ms of a real impulse
        for b in g["beats"][:10]:
            self.assertLess(min(abs(b - k * 0.5) for k in range(25)), 0.015)

    def test_half_and_double_tempo_disambiguation(self):
        """Impulses every 0.5 s with alternating strength: the grid is 120, not 60 (only the
        strong hits) and not 240 (twice as many points as there are onsets)."""
        from _common import beat_grid
        g = beat_grid(self._clicks(0.5, strengths=[1.0, 0.55]), self.STEP)
        self.assertAlmostEqual(g["tempo_bpm"], 120.0, delta=1.0)

    def test_a_different_tempo_is_measured_not_assumed(self):
        from _common import beat_grid
        g = beat_grid(self._clicks(0.4), self.STEP)   # 150 BPM
        self.assertAlmostEqual(g["tempo_bpm"], 150.0, delta=2.0)

    def test_flat_envelope_is_zero_confidence(self):
        from _common import beat_grid
        g = beat_grid([0.5] * 1000, self.STEP)
        self.assertEqual(g["beats"], [])
        self.assertIsNone(g["tempo_bpm"])
        self.assertEqual(g["confidence"], 0.0)
        self.assertFalse(g["usable"])

    def test_empty_envelope_is_zero_confidence(self):
        from _common import beat_grid
        self.assertEqual(beat_grid([], self.STEP)["confidence"], 0.0)
        self.assertEqual(beat_grid([0.1, 0.2], self.STEP)["beats"], [])

    def test_noise_is_not_a_beat(self):
        """Pseudo-random levels have no steady pulse; whatever grid comes out must not be sold
        as usable at the default threshold."""
        from _common import beat_grid
        import random
        rng = random.Random(7)
        env = [rng.random() for _ in range(1000)]
        g = beat_grid(env, self.STEP)
        self.assertLess(g["confidence"], 0.5)
        self.assertFalse(g["usable"])

    def test_min_confidence_only_moves_the_usable_flag(self):
        from _common import beat_grid
        env = self._clicks(0.5)
        self.assertTrue(beat_grid(env, self.STEP, min_confidence=0.5)["usable"])
        self.assertFalse(beat_grid(env, self.STEP, min_confidence=1.01)["usable"])

    def test_unsupported_grid_points_are_counted_not_hidden(self):
        """A grid must be regular, so a gap in the music still gets grid points -- and they are
        reported as unsupported rather than quietly presented as measured beats."""
        from _common import beat_grid
        env = self._clicks(0.5, seconds=5.0) + [0.01] * 500
        g = beat_grid(env, self.STEP)
        self.assertGreater(g["unsupported"], 0)
        self.assertEqual(g["supported"] + g["unsupported"], len(g["beats"]))

    def test_supported_beats_excludes_the_grid_over_a_silent_passage(self):
        """The regular grid runs on through a passage with no music in it -- that is what a grid
        is. `supported_beats` is the subset a measured onset marks, and it is the only list a tool
        that moves a cut may snap to: 8.0 s here is fifteen seconds into dead silence."""
        from _common import beat_grid, snap_points
        env = [0.001] * 2000
        for i in range(0, 500, 50):        # a 120 BPM click for the first 5 s
            env[i] = 1.0
        for i in range(500, 2000):         # then 15 s of near-silence
            env[i] = 0.0005
        g = beat_grid(env, self.STEP)
        self.assertAlmostEqual(g["tempo_bpm"], 120.0, delta=2.0)
        self.assertLess(len(g["supported_beats"]), len(g["beats"]))
        self.assertEqual(len(g["supported_beats"]), g["supported"])
        self.assertTrue(all(b in g["beats"] for b in g["supported_beats"]))
        self.assertLess(max(g["supported_beats"]), 6.0)
        # the full grid would move a cut into the silence; the supported subset does not
        self.assertTrue(snap_points([8.02], g["beats"], 0.12)[0]["snapped"])
        self.assertFalse(snap_points([8.02], g["supported_beats"], 0.12)[0]["snapped"])

    def test_flat_envelope_has_no_supported_beats(self):
        from _common import beat_grid
        self.assertEqual(beat_grid([0.5] * 1000, self.STEP)["supported_beats"], [])

    def test_snap_points_never_adds_or_drops_a_point(self):
        from _common import snap_points
        import random
        rng = random.Random(11)
        for _ in range(50):
            beats = sorted(round(rng.uniform(0, 30), 3) for _ in range(rng.randint(0, 20)))
            points = [round(rng.uniform(0, 30), 3) for _ in range(rng.randint(1, 8))]
            out = snap_points(points, beats, rng.uniform(0, 0.5))
            self.assertEqual(len(out), len(points))
            for row, p in zip(out, points):
                self.assertEqual(row["from"], p)
                self.assertTrue(row["to"] in beats or row["to"] == p)
                if row["snapped"]:
                    self.assertIn(row["to"], beats)

    def test_snap_respects_tolerance(self):
        from _common import snap_points
        out = snap_points([2.3], [1.0, 2.0, 3.0], 0.12)
        self.assertFalse(out[0]["snapped"])
        self.assertEqual(out[0]["to"], 2.3)
        self.assertEqual(out[0]["delta"], 0.0)
        near = snap_points([2.03], [1.0, 2.0, 3.0], 0.12)
        self.assertTrue(near[0]["snapped"])
        self.assertEqual(near[0]["to"], 2.0)
        self.assertAlmostEqual(near[0]["delta"], -0.03, places=6)

    def test_snap_with_no_beats_changes_nothing(self):
        from _common import snap_points
        out = snap_points([1.0, 2.0], [], 1.0)
        self.assertEqual([r["to"] for r in out], [1.0, 2.0])
        self.assertFalse(any(r["snapped"] for r in out))

    def test_a_tempo_between_envelope_steps_is_not_rounded_to_one(self):
        """After 3.2.0: the autocorrelation lag is a whole number of steps, so 90 BPM (0.6667 s) came
        out as 0.67 s and the grid drifted 3.3 ms a beat, 0.1 s off the clicks within 30 s. The
        grid is refitted to the onsets: every click within 20 ms, the tempo to 0.1 BPM."""
        from _common import beat_grid
        for bpm in (90.0, 137.0, 72.0):
            with self.subTest(bpm=bpm):
                iv = 60.0 / bpm
                g = beat_grid(self._clicks(iv, seconds=30.0), self.STEP, duration=30.0)
                self.assertAlmostEqual(g["tempo_bpm"], bpm, delta=0.1)
                clicks = [k * iv for k in range(int(30.0 / iv) + 1) if k * iv < 30.0]
                worst = max(min(abs(b - t) for b in g["beats"]) for t in clicks)
                self.assertLess(worst, 0.020)

    def test_a_track_that_starts_on_the_beat_has_a_beat_at_zero(self):
        """An onset at the very first envelope step cannot be measured (there is no step before
        it), so the grid's phase is fitted from the later beats; one that lands a few ms either
        side of 0 s is the beat at 0.0, not a dropped one."""
        from _common import beat_grid
        for bpm in (90.0, 120.0, 137.0):
            with self.subTest(bpm=bpm):
                g = beat_grid(self._clicks(60.0 / bpm, seconds=20.0), self.STEP, duration=20.0)
                self.assertGreaterEqual(g["beats"][0], 0.0)
                self.assertLess(g["beats"][0], 0.005)

    def test_a_grid_point_well_before_zero_is_not_moved_to_zero(self):
        """A 120 BPM grid with phase 0.46 has its point before the first at -0.04 s. Clamping it to
        0.0 made 0.0 a beat -- and with an onset at 0.08 s a "supported" one, so a cut at 0.08
        snapped to a time the grid does not mark. Only a point within BEAT_ZERO_TOL_S of 0 is the
        beat at 0.0."""
        from _common import beat_grid, snap_points
        from _common.decision import BEAT_ZERO_TOL_S
        env = [0.01] * 1000
        env[8] = 0.3                       # a weak onset at 0.08 s
        for k in range(20):                # clicks from 0.46 s, every 0.5 s
            i = 46 + 50 * k
            env[i], env[i + 1] = 1.0, 0.6
        g = beat_grid(env, self.STEP, duration=10.0)
        self.assertAlmostEqual(g["tempo_bpm"], 120.0, delta=0.5)
        self.assertAlmostEqual(g["beats"][0], 0.46, delta=0.01)
        self.assertNotIn(0.0, g["beats"])
        self.assertNotIn(0.0, g["supported_beats"])
        self.assertFalse(snap_points([0.08], g["supported_beats"], 0.12)[0]["snapped"])
        self.assertEqual(BEAT_ZERO_TOL_S, 0.01)

    def test_refine_onset_times_places_a_click_to_the_sample(self):
        """An onset picked on a 10 ms envelope is only known to the step; the PCM places it."""
        from _common.decision import refine_onset_times
        import math as _m
        rate = 22050
        pcm = [0.0] * rate
        starts = (0.2037, 0.5012, 0.7999)
        for t0 in starts:
            s0 = int(round(t0 * rate))
            for k in range(int(rate * 0.01)):
                pcm[s0 + k] = 0.8 * _m.sin(2 * _m.pi * 1000 * k / rate) * _m.exp(-k / (rate * 0.003))
        step = 220 / rate
        coarse = [int(t0 / step) * step for t0 in starts]   # what the envelope pick gives
        fine = refine_onset_times(coarse, step, pcm, rate)
        for t0, t in zip(starts, fine):
            self.assertLess(abs(t - t0), 0.001)
        # a time too close to the edge of the PCM is returned as it was
        self.assertEqual(refine_onset_times([0.001], step, pcm, rate), [0.001])

    def test_beat_grid_is_pure(self):
        import unittest.mock
        import _common
        from _common import beat_grid, snap_points
        def boom(*a, **k):
            raise AssertionError("beat_grid ran a subprocess")
        with unittest.mock.patch.object(_common, "run", boom), \
             unittest.mock.patch.object(_common, "run_analysis", boom), \
             unittest.mock.patch.object(subprocess, "run", boom), \
             unittest.mock.patch.object(subprocess, "Popen", boom):
            g = beat_grid(self._clicks(0.5), self.STEP)
            self.assertAlmostEqual(g["tempo_bpm"], 120.0, delta=1.0)
            self.assertEqual(len(snap_points([1.0], g["beats"], 0.1)), 1)


class GeometryAuditAnalysisTests(unittest.TestCase):
    """Issue #411 (audit H) for look.py and scenes.py: the contact sheet's stamp on a source that
    does not start at 0, scenes --sheet on a variable-frame-rate source, --compare keeping each
    picture's aspect, and a non-square-pixel source looked at in square pixels. Every fixture is
    a short lavfi clip built here."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.red43 = tiny_clip(OUT / "g411a_red43.mp4", "color=c=red:s=240x180:r=30", seconds=2)
        cls.blue169 = tiny_clip(OUT / "g411a_blue169.mp4", "color=c=blue:s=320x180:r=30", seconds=2)
        cls.sar = sar_clip(OUT / "g411a_sar.mp4", seconds=2)
        # an MPEG-TS starts its timeline at 1.4 s
        cls.ts = OUT / "g411a.ts"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30",
           "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
           "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "mpegts", cls.ts)
        # VFR: red 2 s at 5 fps, blue 1 s at 30 fps, green 2 s at 5 fps (50 frames over 5 s, so
        # start x average fps names frame 30 for the green scene's start at 3 s -- a blue frame)
        parts = []
        for i, (colour, rate, secs) in enumerate((("red", 5, 2), ("blue", 30, 1), ("green", 5, 2))):
            part = OUT / f"g411a_vfr{i}.mp4"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"color=c={colour}:s=320x180:r={rate}", "-t", str(secs), "-c:v", "libx264",
               "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-video_track_timescale", "90000", part)
            parts.append(part)
        listing = OUT / "g411a_vfr.txt"
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
        cls.vfr = OUT / "g411a_vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing,
           "-c", "copy", cls.vfr)

    def _rgb(self, png, x, y):
        proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE)
        w = png_size(png)[0]
        off = (y * w + x) * 3
        return tuple(proc.stdout[off:off + 3])

    def test_contact_sheet_stamps_count_from_the_file_start_on_mpeg_ts(self):
        """An input -ss resets an MPEG-TS's timestamps differently from an MP4's, so the stamp
        (pts + seek) came out one seek late on TS. The sheet now keeps the file's own timestamps
        counted from its start (-copyts -start_at_zero) and stamps each frame's pts as it is.
        The stamp is drawn text, so the test reads the pts the stamp is drawn from: the same
        graph with showinfo in place of drawtext and tile."""
        self.assertGreater(probe(str(self.ts))["start_time"], 1.0)
        doc = json.loads(script("look.py", self.ts, "--tiles", "3x1", "-o", OUT / "g411a_ts_sheet.png",
                                "--json").stdout)
        argv = shlex.split(doc["commands"][-1])
        vf = argv[argv.index("-vf") + 1]
        stamp = re.search(r"drawtext=text='%\{pts\\:hms(?:\\:([0-9.]+))?\}'", vf)
        self.assertIsNotNone(stamp, vf)
        offset = float(stamp.group(1) or 0)
        argv[argv.index("-vf") + 1] = vf.split(",scale=")[0] + ",showinfo"
        argv[-1:] = ["-an", "-f", "null", "-"]  # the PNG the tool writes has no audio either
        i = argv.index("-frames:v")
        argv[i:i + 2] = []
        argv = [a for a in argv if a not in ("-loglevel", "error")]
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stamps = [float(t) + offset for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
        # the tiles sample the middle of each third: about 0.5, 1.5 and 2.5 s from the file's start
        self.assertEqual(len(stamps), 3, proc.stderr[-2000:])
        for got, want in zip(stamps, (0.5, 1.5, 2.5)):
            self.assertAlmostEqual(got, want, delta=0.1)

    def test_compare_keeps_each_pictures_aspect(self):
        """scale2ref stretched the first picture to the second's size: a 4:3 beside a 16:9 came
        out 16:9. Both now sit in boxes as tall as the taller one, letterboxed."""
        out = OUT / "g411a_compare.png"
        script("look.py", self.red43, "--compare", self.blue169, "--at", "1", "--no-timecode", "-o", out)
        self.assertEqual(png_size(out), (1280, 480))
        top_of_blue = self._rgb(out, 960, 10)
        self.assertLess(top_of_blue[2], 100, top_of_blue)  # the letterbox, not blue picture

    def test_look_shows_a_non_square_pixel_source_at_its_display_aspect(self):
        out = OUT / "g411a_sar_at.png"
        script("look.py", self.sar, "--at", "1", "--no-timecode", "-o", out)
        self.assertEqual(png_size(out), (1280, 720))

    def test_scenes_sheet_picks_each_scene_start_by_time_on_vfr(self):
        doc = json.loads(script("scenes.py", self.vfr, "--sheet", OUT / "g411a_vfr_sheet.png", "--no-timecode",
                                "--json", "--overwrite").stdout)
        starts = [s["start"] for s in doc["scenes"]]
        self.assertEqual(len(starts), 3, starts)
        self.assertAlmostEqual(starts[2], 3.0, delta=0.05)
        tile_w = 1280 // 3 // 2 * 2
        green = self._rgb(OUT / "g411a_vfr_sheet.png", 2 + 2 * (tile_w + 2) + tile_w // 2, 60)
        self.assertGreater(green[1], 100, green)
        self.assertLess(green[2], 80, green)


class NotMeasuredAnalysisTests(unittest.TestCase):
    """#403: a result says what was measured. A picture that fills its frame is not a crop, and a
    guess made for SDR-tagged pictures is not made about an HDR one."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.dir = OUT / "not_measured"
        cls.dir.mkdir(parents=True, exist_ok=True)

    def clip(self, name, source, *extra):
        p = self.dir / name
        if not p.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", source, *extra, "-c:v", "libx264", "-pix_fmt", "yuv420p", p)
        return p

    def test_cropdetect_reports_a_bar_free_frame_as_the_frame_whatever_round_is(self):
        """180 and 1080 are not multiples of 16: the filter's own rounding made a bar-free frame
        read 320x176 (1920x1072), and the no-bars branch compared that with the source's size."""
        full = self.clip("full_320x180.mp4", "testsrc2=s=320x180:r=30:d=2")
        for extra in ([], ["--round", "16"], ["--round", "2"], ["--round", "32"]):
            with self.subTest(round=extra):
                data = json.loads(script("cropdetect.py", full, "--seconds", "1", "--samples", "2", "--json", *extra).stdout)
                self.assertEqual(data["crop"], {"width": 320, "height": 180, "x": 0, "y": 0})
                self.assertEqual((data["source_width"], data["source_height"]), (320, 180))
        # a real bar is still rounded as the filter's round option rounds it: compared with the
        # filter's own reading at that round, not with numbers pinned here
        bars = self.clip("bars_320x180.mp4", "testsrc2=s=320x140:r=30:d=2", "-vf", "pad=320:180:0:20:black")
        for rnd in (16, 4, 3, 1):  # the filter takes 1 as 16 and doubles an odd value
            with self.subTest(bars_round=rnd):
                data = json.loads(script("cropdetect.py", bars, "--seconds", "1", "--samples", "1", "--round", str(rnd), "--json").stdout)
                proc = sh("ffmpeg", "-hide_banner", "-nostdin", "-t", "1", "-i", bars, "-vf", f"cropdetect=round={rnd}:reset=1", "-f", "null", "-")
                w, h, x, y = collections.Counter(re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)).most_common(1)[0][0]
                self.assertEqual(data["crop"], {"width": int(w), "height": int(h), "x": int(x), "y": int(y)})
                self.assertLess(data["crop"]["height"], 180)

    def test_probe_analyze_does_not_call_an_hdr_stream_sdr(self):
        if "libx265" not in sh("ffmpeg", "-hide_banner", "-encoders").stdout:
            self.skipTest("this build has no libx265 to make the PQ input with")
        pq = self.dir / "pq.mp4"
        if not pq.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=2", "-c:v", "libx265", "-pix_fmt", "yuv420p10le",
               "-tag:v", "hvc1", "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
               "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error", pq)
        levels = json.loads(script("probe.py", pq, "--analyze").stdout)["levels"]
        self.assertIsNone(levels["looks_like_log"])
        self.assertTrue(levels["reason"].startswith("not_measured:"), levels)
        self.assertIn("tagged HDR", levels["note"])
        self.assertNotIn("normal display-referred SDR", levels["note"])
        self.assertIn("y_avg", levels, "the numbers are still the measurement")
        self.assertNotIn("[Log?]", script("probe.py", pq, "--analyze", "--compact").stdout)
        sdr = self.clip("full_320x180.mp4", "testsrc2=s=320x180:r=30:d=2")
        levels = json.loads(script("probe.py", sdr, "--analyze").stdout)["levels"]
        self.assertIs(levels["looks_like_log"], False)
        self.assertNotIn("reason", levels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
