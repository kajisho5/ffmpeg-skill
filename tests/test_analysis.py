#!/usr/bin/env python3
"""End-to-end tests for probe, check, verify, scenes, cropdetect, report, look and sync.

    python3 tests/test_analysis.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, TONES, _is_faststart, _no_fontconfig, png_size, script, sh  # noqa: E402
from _common import default_font_file, font_for_script, probe  # noqa: E402


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
        self.assertGreater(data["confidence"], 0.5)
        out = OUT / "synced.mp4"
        script("sync.py", self.src, self.mic, "--replace-audio", "-o", out)
        again = json.loads(script("sync.py", self.src, out, "--json").stdout)
        self.assertClose(again["offset_seconds"], 0.0, 0.05, "aligned output has no residual offset")

    def test_sync_replace_audio_stream_copy_writes_faststart_mp4(self):
        """Same shape as #275/#277: --replace-audio stream-copies the reference's video with
        -c:v copy while only the audio is rebuilt, and must write -movflags +faststart on the
        mp4 output the same way every other mp4-writing path does."""
        out = OUT / "sync_replace_faststart.mp4"
        script("sync.py", self.src, self.mic, "--replace-audio", "-o", out)
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")
        self.assertTrue(_is_faststart(out), "sync.py --replace-audio must write +faststart")

    def test_sync_trim_second_stream_copy_writes_faststart_mp4(self):
        """Same shape as #275/#277, the other stream-copy spot in sync.py: --trim-second's
        head-trim path (`-c copy`) when the second file has video and started earlier."""
        early_video = OUT / "early_video.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=1.5",
           "-f", "lavfi", "-i", "aevalsrc=0:s=48000:d=1.5",
           "-i", self.src, "-filter_complex",
           "[0:v][2:v]concat=n=2:v=1:a=0[v];[1:a][2:a]concat=n=2:v=0:a=1[a]",
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
           str(early_video))
        out = OUT / "sync_trim_second_faststart.mp4"
        script("sync.py", self.src, early_video, "--trim-second", "-o", out)
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")
        self.assertTrue(_is_faststart(out), "sync.py --trim-second's stream-copy branch must write +faststart")

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
        self.assertEqual([r[k]["status"] for k in ("black", "frozen", "silence")], ["PASS"] * 3, r)
        self.assertEqual(self._rows(black, "--content")["black"]["status"], "FAIL")
        self.assertEqual(self._rows(frozen, "--content")["frozen"]["status"], "FAIL")
        self.assertEqual(self._rows(part, "--content")["frozen"]["status"], "WARN")
        self.assertEqual(self._rows(silent, "--content")["silence"]["status"], "FAIL")
        r = self._rows(mixed, "--content")
        self.assertEqual((r["black"]["status"], r["silence"]["status"]), ("WARN", "WARN"), r)

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
        self.assertIn("| probe | FAIL | 0s | ffprobe failed |", text)
        for step in ("overlay text", "look sheet", "probe analyze", "loudness measure", "silence list",
                     "color to-sdr", "hdr preserved", "audio downmix", "export x"):
            self.assertIn(f"| {step} | PASS |", text, f"{step} missing or failed:\n{text}")
        self.assertNotIn("| FAIL |", text.replace("| probe | FAIL | 0s | ffprobe failed |", ""))
        self.assertTrue((out / f"{Path(self.hdr).stem}_sdr.mp4").exists())
        self.assertTrue((out / f"{Path(self.surround).stem}_st.mp4").exists())
        # a per-step timeout is reported per step, never raised
        data = json.loads(script("verify.py", self.src, "--quick", "--timeout", "0.01", "--json", expect_fail=True).stdout)
        self.assertEqual((data["status"], data["error"]["kind"]), ("failed", "verification"))
        timed_out = [s for f in data["files"] for s in f["steps"] if s["error"].startswith("timeout after")]
        self.assertTrue(timed_out, data)
        self.assertEqual(data["failed"], len(timed_out))

    def test_check_compliance(self):
        reels = OUT / "export_reels.mp4"
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
