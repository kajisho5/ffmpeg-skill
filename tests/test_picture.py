#!/usr/bin/env python3
"""End-to-end tests for caption, overlay, graphics, color, redact, deinterlace, denoise, stabilize, background and grid, plus fonts, emoji, shaping and caption wrap.

    python3 tests/test_picture.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import contextlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, TONES, _ass_advance, _ass_ink_columns, _ass_ink_rows, _emoji_assets, _families_for, _family_installed, _frame_ink, _is_faststart, _no_fontconfig, _pixel_at, script, sh  # noqa: E402
from _common import default_font_file, detect_script, escape_filter_path, font_family_for_script, font_for_script, probe  # noqa: E402


class PictureTests(MediaFixtures):
    """Caption, overlay, graphics, color, redact, deinterlace, denoise, stabilize, background and grid, plus fonts, emoji, shaping and caption wrap."""

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

    def test_caption_wraps_a_long_latin_cue_to_the_safe_area(self):
        """A 60-character cue at size 48 on a 640-wide frame does not fit one line; it is wrapped
        to the safe area and, past --max-lines, split into consecutive cues rather than running
        off the frame or covering the picture."""
        import caption  # noqa: E402  -- the wrap table under test
        cues = OUT / "wrap_latin.txt"
        text = "the quick brown fox jumps over the lazy dog and keeps runnin"
        self.assertEqual(len(text), 60)
        cues.write_text(f"0:00-0:04 {text}\n", encoding="utf-8")
        srt = OUT / "wrap_latin.srt"
        script("caption.py", self._small(), "--text", cues, "--size", "48", "--max-lines", "2",
               "--write-srt", srt, "--fast", "-o", OUT / "wrap_latin.mp4")
        blocks = self._srt_cues(srt)
        self.assertGreater(len(blocks), 1, "60 characters at size 48 cannot fit 2 lines of a 640px frame")
        max_em = 640 * caption.SAFE_WIDTH_FRACTION / (48 * 360 / 288.0)
        for _, lines in blocks:
            self.assertLessEqual(len(lines), 2, f"--max-lines 2 exceeded: {lines}")
            for line in lines:
                self.assertLessEqual(caption.text_width_em(line), max_em + 1e-6,
                                      f"line wider than the safe area: {line!r}")
        self.assertEqual(" ".join(l for _, lines in blocks for l in lines), text, "no word is lost or cut")

    def test_phrase_wrap_burns_and_reports(self):
        """1.16 end to end: the dl1 and dl4 cues are burnt in, the ASS the run writes carries the
        phrase breaks, and the result document says which wrap produced them."""
        import caption  # noqa: E402
        cues = OUT / "wrap_phrase.txt"
        cues.write_text("0:00-0:02 A third line the tool times for me\n"
                        "0:02-0:04 Una tercera l\u00ednea con tiempos autom\u00e1ticos\n", encoding="utf-8")
        out = OUT / "wrap_phrase.mp4"
        ass = OUT / "wrap_phrase.ass"
        res = json.loads(script("caption.py", self._small(), "--text", cues, "--size", "32",
                                "--max-lines", "2", "--animate", "fade", "--write-ass", ass,
                                "--json", "--fast", "-o", out).stdout)
        self.assertEqual(res["caption"]["wrap"], "phrase")
        self.assertIn("phrase_breaks", res["caption"])
        self.assertTrue(out.exists())
        body = ass.read_text(encoding="utf-8")
        self.assertIn("A third line\\Nthe tool times for me", body)
        self.assertIn("Una tercera l\u00ednea\\Ncon tiempos autom\u00e1ticos", body)
        # and --wrap measured still reproduces 1.15's split, byte for byte in the ASS
        ass2 = OUT / "wrap_measured.ass"
        script("caption.py", self._small(), "--text", cues, "--size", "32", "--max-lines", "2",
               "--wrap", "measured", "--animate", "fade", "--write-ass", ass2, "--fast", "-o", OUT / "wrap_measured.mp4")
        self.assertIn("A third line the\\Ntool times for me", ass2.read_text(encoding="utf-8"))
        self.assertEqual(caption.wrap_text("A third line the tool times for me", 12.96),
                         ["A third line", "the tool times for me"])

    def test_caption_wraps_cjk_between_characters(self):
        """Chinese has no spaces: the line breaks between any two characters, and every character
        counts as a full em (Latin averages just over half)."""
        import caption  # noqa: E402
        from _common import font_for_script  # noqa: E402
        if font_for_script("zh") is None:
            self.skipTest("this machine has no font covering zh")
        text = "你好世界这是一个很长的中文字幕需要换行处理的测试"
        self.assertEqual(len(text), 24)
        cues = OUT / "wrap_cjk.txt"
        cues.write_text(f"0:00-0:04 {text}\n", encoding="utf-8")
        srt = OUT / "wrap_cjk.srt"
        proc = script("caption.py", self._small(), "--text", cues, "--size", "48", "--write-srt", srt,
                      "--fast", "-o", OUT / "wrap_cjk.mp4")
        blocks = self._srt_cues(srt)
        lines = [l for _, ls in blocks for l in ls]
        self.assertGreater(len(lines), 1, "a 24-character CJK cue at size 48 must break")
        max_em = 640 * caption.SAFE_WIDTH_FRACTION / (48 * 360 / 288.0)
        for line in lines:
            self.assertLessEqual(caption.text_width_em(line), max_em + 1e-6, line)
        self.assertEqual("".join(lines), text, "no character is lost")
        self.assertIn("font:", proc.stderr, "a Chinese cue resolves a font by script")
        self.assertRegex(proc.stderr, r"cues: .*(wrapped|split)")

    def test_caption_wrap_puts_mixed_script_text_back_exactly_as_written(self):
        """A wrap must never change the text: CJK gains no spaces, and the author's own spaces
        around a Latin word inside CJK survive."""
        import caption  # noqa: E402
        for text in ("Hello 世界 this is mixed 混合文本 wrapping",
                     "你好世界这是一个很长的中文字幕",
                     "one two three four five six"):
            with self.subTest(text=text):
                lines = caption.wrap_text(text, 8)
                self.assertGreater(len(lines), 1)
                rebuilt = ""
                for line in lines:
                    if not rebuilt:
                        rebuilt = line
                    elif text[len(rebuilt)] == " ":
                        rebuilt += " " + line
                    else:
                        rebuilt += line
                self.assertEqual(rebuilt, text)

    def test_caption_offset_shifts_every_cue_in_both_directions(self):
        cues = OUT / "offset_cues.txt"
        cues.write_text("0:02-0:04 one\n0:05-0:07 two\n", encoding="utf-8")
        late = OUT / "offset_late.srt"
        script("caption.py", "--text", cues, "--write-srt", late, "--offset", "1.5")
        self.assertIn("00:00:03,500 --> 00:00:05,500", late.read_text(encoding="utf-8"))
        early = OUT / "offset_early.srt"
        script("caption.py", "--text", cues, "--write-srt", early, "--offset", "-1.5")
        self.assertIn("00:00:00,500 --> 00:00:02,500", early.read_text(encoding="utf-8"))

    def test_caption_offset_rewrites_a_copy_never_the_callers_srt(self):
        """--offset on a hand-written SRT must not edit the file the user passed in."""
        src_srt = OUT / "offset_source.srt"
        src_srt.write_text("1\n00:00:02,000 --> 00:00:04,000\nhello\n\n", encoding="utf-8")
        before = src_srt.read_text(encoding="utf-8")
        out = OUT / "offset_burn.mp4"
        proc = script("caption.py", self._small(), "--srt", src_srt, "--offset", "1.0", "--fast", "-o", out)
        self.assertEqual(src_srt.read_text(encoding="utf-8"), before, "the caller's SRT is never edited in place")
        adjusted = OUT / "offset_burn_adjusted.srt"
        self.assertTrue(adjusted.exists(), proc.stderr)
        self.assertIn("00:00:03,000 --> 00:00:05,000", adjusted.read_text(encoding="utf-8"))
        self.assertIn(str(adjusted), proc.stderr)

    def test_caption_min_duration_extends_a_flashed_cue_but_never_past_the_next(self):
        cues = OUT / "min_dur_cues.txt"
        cues.write_text("0:00-0:00.3 flash\n0:01-0:03 next\n", encoding="utf-8")
        srt = OUT / "min_dur.srt"
        proc = script("caption.py", "--text", cues, "--write-srt", srt, "--min-duration", "1.5")
        text = srt.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,000", text, "extended up to the next cue's start, not over it")
        self.assertIn("extended", proc.stderr)
        loose = OUT / "min_dur_loose.srt"
        script("caption.py", "--text", cues, "--write-srt", loose, "--min-duration", "0")
        self.assertIn("00:00:00,000 --> 00:00:00,300", loose.read_text(encoding="utf-8"), "--min-duration 0 leaves cues alone")

    def test_caption_karaoke_uses_whisper_word_timings_when_the_transcript_has_them(self):
        """A whisper JSON next to the SRT carries real per-word start/end times; --karaoke must
        follow them instead of splitting the cue evenly or guessing from audio energy."""
        srt = OUT / "words.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:04,000\nalpha beta gamma\n\n", encoding="utf-8")
        (OUT / "words.json").write_text(json.dumps({"segments": [{"words": [
            {"word": "alpha", "start": 0.0, "end": 0.5},
            {"word": "beta", "start": 0.5, "end": 1.0},
            {"word": "gamma", "start": 1.0, "end": 4.0}]}]}), encoding="utf-8")
        ass = OUT / "words.ass"
        proc = script("caption.py", self._small(), "--srt", srt, "--karaoke", "--write-ass", ass,
                      "--fast", "-o", OUT / "words.mp4")
        self.assertIn("word timings", proc.stderr)
        body = ass.read_text(encoding="utf-8-sig")
        self.assertIn(r"{\kf50}alpha", body)
        self.assertIn(r"{\kf50}beta", body)
        self.assertIn(r"{\kf300}gamma", body)

    def test_caption_brand_styles_caption_block_sets_the_look(self):
        """brand.json's `styles.caption` is the documented 1.12 spelling, shared with graphics.py;
        an explicit flag still beats it."""
        brand = OUT / "brand_styles.json"
        brand.write_text(json.dumps({"styles": {"caption": {
            "font": "DejaVu Serif", "size": 33, "colour": "00FF00", "position": "top", "box": True}}}), encoding="utf-8")
        ass = OUT / "brand_styles.ass"
        script("caption.py", self._small(), "--text", self.cues, "--brand", brand, "--animate", "fade",
               "--write-ass", ass, "--fast", "-o", OUT / "brand_styles.mp4")
        style = next(l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Style: Default"))
        self.assertIn("DejaVu Serif", style)
        self.assertIn("&H0000FF00", style, "colour (British spelling) is read")
        self.assertEqual(style.split(",")[-5], "8", "position top -> ASS alignment 8")
        self.assertEqual(style.split(",")[15], "3", "box -> BorderStyle 3")

    def test_caption_non_latin_text_picks_a_font_that_covers_it(self):
        """Korean, Chinese, Arabic and Thai cues burn with a font that has the glyphs: the run
        exits 0, names the font file it chose, and the caption band actually gains ink (tofu
        boxes would too, which is why the font file is asserted as well)."""
        if _no_fontconfig():
            self.skipTest("no fc-list on this machine: fonts cannot be resolved by script here")
        small = self._small()
        base = self._band_luma(small, OUT / "band_plain.png")
        samples = {"ko": "안녕하세요 여러분", "zh": "你好世界大家好", "ar": "مرحبا بالعالم", "th": "สวัสดีชาวโลก"}
        for lang, text in samples.items():
            with self.subTest(lang=lang):
                if font_for_script(lang) is None:
                    self.skipTest(f"this machine has no font covering {lang}")
                cues = OUT / f"nl_{lang}.txt"
                cues.write_text(f"0:00-0:04 {text}\n", encoding="utf-8")
                out = OUT / f"nl_{lang}.mp4"
                proc = script("caption.py", small, "--text", cues, "--lang", lang, "--size", "40",
                              "--fast", "-o", out)
                m = probe(str(out))
                self.assertEqual(m["video"]["width"], 640)
                chosen = re.search(r"^font: (.+?) \(covers (\w+)\)", proc.stderr, re.M)
                self.assertIsNotNone(chosen, proc.stderr)
                self.assertTrue(os.path.exists(chosen.group(1)), chosen.group(1))
                self.assertEqual(chosen.group(2), lang)
                inked = self._band_luma(out, OUT / f"band_{lang}.png")
                self.assertNotAlmostEqual(inked, base, delta=0.05,
                                          msg=f"{lang}: the caption band is identical to the uncaptioned frame")

    def test_graphics_and_overlay_pick_a_font_by_script_for_non_latin_text(self):
        """drawtext renders a box per missing glyph and still exits 0; graphics.py and overlay.py
        resolve a font that covers the text instead, and say which file they chose."""
        if _no_fontconfig():
            self.skipTest("no fc-list on this machine: fonts cannot be resolved by script here")
        if font_for_script("ko") is None:
            self.skipTest("this machine has no font covering ko")
        gfx = OUT / "gfx_ko.mp4"
        proc = script("graphics.py", self._small(), "--template", "lower-third", "--name", "김민준",
                      "--title", "감독", "--lang", "ko", "--preset", "veryfast", "-o", gfx, "--json")
        chosen = re.search(r"^font: (.+?) \(covers ko\)", proc.stderr, re.M)
        self.assertIsNotNone(chosen, proc.stderr)
        self.assertIn(f"fontfile={escape_filter_path(chosen.group(1))}", json.loads(proc.stdout)["commands"][0])
        ov = OUT / "overlay_ja.mp4"
        proc2 = script("overlay.py", self._small(), "--text", "こんにちは世界", "--preset", "veryfast", "-o", ov, "--json")
        chosen2 = re.search(r"^font: (.+?) \(covers ja\)", proc2.stderr, re.M)
        self.assertIsNotNone(chosen2, proc2.stderr)
        self.assertIn("fontfile=", json.loads(proc2.stdout)["commands"][0])

    def test_an_explicit_font_is_kept_even_when_it_does_not_cover_the_script(self):
        """A stated --font is the user's decision: it is warned about, never silently replaced."""
        if _no_fontconfig():
            self.skipTest("no fc-list on this machine")
        cues = OUT / "explicit_font.txt"
        cues.write_text("0:00-0:03 你好世界\n", encoding="utf-8")
        proc = script("caption.py", self._small(), "--text", cues, "--font", "DejaVu Sans",
                      "--fast", "-o", OUT / "explicit_font.mp4")
        self.assertIn("FontName=DejaVu Sans", " ".join(proc.stderr.splitlines()))
        self.assertNotIn("(covers zh)", proc.stderr, "an explicit font is never replaced")
        if shutil.which("fc-list"):
            self.assertIn("does not cover", proc.stderr, "but the caller is told it will not render")
        else:
            # Windows resolves fonts by file name and has no fontconfig to ask: coverage is
            # unknown, so keeping the font silently (no "does not cover" claim) is correct.
            self.assertNotIn("does not cover", proc.stderr)

    def test_no_font_for_the_script_is_a_failed_job_not_tofu(self):
        """The whole point: a machine that cannot render the text refuses the job instead of
        writing a video of empty boxes that ffmpeg reports as a success. Forced with an fc-list
        that answers normally (exit 0) and lists nothing -- fontconfig saying "no font covers
        this", which is what a bare container with fontconfig but no font files looks like."""
        if platform.system() == "Windows":
            self.skipTest("the shim below is a #!/bin/sh script; Windows resolves fonts by file name, not fontconfig")
        shim = OUT / "nofc"
        shim.mkdir(exist_ok=True)
        (shim / "fc-list").write_text("#!/bin/sh\nexit 0\n")
        (shim / "fc-list").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
        cues = OUT / "no_font.txt"
        cues.write_text("0:00-0:03 안녕하세요\n", encoding="utf-8")
        proc = script("caption.py", self._small(), "--text", cues, "--json", "--fast",
                      "-o", OUT / "no_font.mp4", env=env, expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "failed")
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("Korean", doc["error"]["message"])
        self.assertIn("--fonts-dir", doc["error"]["message"], "the message names a flag caption.py has")
        self.assertNotIn("or pass --font-file", doc["error"]["message"], "caption.py has no --font-file")
        self.assertFalse((OUT / "no_font.mp4").exists(), "nothing is written for a job that cannot be read")

    def test_a_broken_or_absent_fontconfig_is_unknown_not_missing(self):
        """`unknown` is not `missing` (the rule every other capability in this repo follows):
        with no fc-list on PATH -- or one that fails -- coverage cannot be verified, so the job
        runs with the caller's font (libass has its own font backend) behind one info line,
        instead of refusing work that 1.11.1 rendered."""
        if platform.system() == "Windows":
            self.skipTest("the shim below is a #!/bin/sh script; Windows resolves fonts by file name, not fontconfig")
        cues = OUT / "unknown_fc.txt"
        cues.write_text("0:00-0:03 안녕하세요\n", encoding="utf-8")
        broken = OUT / "brokenfc"
        broken.mkdir(exist_ok=True)
        (broken / "fc-list").write_text("#!/bin/sh\nexit 1\n")
        (broken / "fc-list").chmod(0o755)
        empty = OUT / "nobin"
        empty.mkdir(exist_ok=True)
        for tool in ("ffmpeg", "ffprobe"):
            link = empty / tool
            if not link.exists():
                link.symlink_to(shutil.which(tool))
        cases = {
            "fc-list fails": dict(os.environ, PATH=f"{broken}{os.pathsep}{os.environ['PATH']}"),
            "no fc-list at all": dict(os.environ, PATH=str(empty)),
        }
        for label, env in cases.items():
            with self.subTest(case=label):
                out = OUT / ("unknown_fc_%s.mp4" % label.replace(" ", "_").replace("-", "_"))
                proc = script("caption.py", self._small(), "--text", cues, "--json", "--fast",
                              "-o", out, env=env)
                doc = json.loads(proc.stdout)
                self.assertEqual(doc["status"], "completed", proc.stderr)
                self.assertIn("could not verify", proc.stderr)
                self.assertNotIn("no installed font covers", proc.stderr)
                self.assertIn("FontName=DejaVu Sans", " ".join(doc["commands"]),
                              "the caller's font stands when coverage is unknown")

    def test_caption_dry_run_plans_the_same_file_the_real_run_burns(self):
        """--dry-run/--plan must describe the job the real run executes: when --offset/--max-lines/
        --min-duration adjust a hand-written SRT, the planned command names the adjusted copy (the
        file the real run burns), the plan document says where it comes from, and no side file is
        written under a dry run."""
        src_srt = OUT / "plan_parity.srt"
        src_srt.write_text("1\n00:00:01,000 --> 00:00:01,300\nflash\n\n"
                           "2\n00:00:02,000 --> 00:00:04,000\n"
                           "this is a very long caption line that certainly needs wrapping here\n\n",
                           encoding="utf-8")
        out = OUT / "plan_parity.mp4"
        adjusted = OUT / "plan_parity_adjusted.srt"
        if adjusted.exists():
            adjusted.unlink()
        plan = OUT / "plan_parity.json"
        proc = script("caption.py", self._small(), "--srt", src_srt, "--size", "48",
                      "-o", out, "--plan", plan)
        doc = json.loads(plan.read_text(encoding="utf-8"))
        planned = [c for c in doc["commands"] if "-vf" in c]
        self.assertTrue(planned, doc["commands"])
        # the filter string escapes the path (Windows: `D\\:/a/...`), so match the file name
        self.assertIn(adjusted.name, planned[0], "the plan burns the adjusted copy, not the caller's file")
        self.assertNotIn(src_srt.name, planned[0])
        self.assertTrue(any(str(adjusted) in n for n in doc.get("notes") or []),
                        f"the plan records the side file: {doc.get('notes')}")
        self.assertFalse(adjusted.exists(), "a dry run writes no side file")
        real = script("caption.py", self._small(), "--srt", src_srt, "--size", "48",
                      "--fast", "-o", out, "--json")
        self.assertTrue(adjusted.exists(), real.stderr)
        burned = [c for c in json.loads(real.stdout)["commands"] if "-vf" in c]
        self.assertIn(adjusted.name, burned[0], "the real run burns the file the plan named")

    def test_caption_never_breaks_before_a_combining_mark(self):
        """Thai tone marks and vowel signs, Devanagari matras, Arabic and Hebrew points are their
        own code points: a line may never start with one, and they advance the pen by nothing."""
        import caption  # noqa: E402
        import unicodedata
        for text in ("กิ้น" * 6, "मैंने" * 6, "مَرْحَبًا " * 4, "שָׁלוֹם " * 4):
            with self.subTest(text=text[:8]):
                for width in (1.5, 3.0, 6.0):
                    for line in caption.wrap_text(text, width):
                        first = line[0]
                        self.assertEqual(unicodedata.combining(first), 0, f"line starts with a mark: {line!r}")
                        self.assertNotIn(unicodedata.category(first), ("Mn", "Mc"), f"line starts with a mark: {line!r}")
                self.assertEqual("".join(caption.wrap_text(text, 3.0)).replace(" ", ""),
                                 text.replace(" ", ""), "no character is lost")
        self.assertEqual(caption.text_width_em("\u0e01\u0e34\u0e49"), caption.text_width_em("\u0e01"),
                         "a combining mark is charged no width")
        self.assertEqual(caption.wrap_text("เก", 10.0), ["เก"], "a leading Thai vowel stays with its consonant")

    def test_caption_offset_takes_the_skills_time_grammar(self):
        """SKILL.md lists --offset among the timestamp flags: mm:ss and hh:mm:ss(.fff) work,
        signed, and a bad value is a `kind: input` refusal document, not an argparse dump."""
        cues = OUT / "offset_grammar.txt"
        cues.write_text("0:05-0:07 one\n", encoding="utf-8")
        for value, expected in (("0:02", "00:00:07,000 --> 00:00:09,000"),
                                ("-0:00:02.500", "00:00:02,500 --> 00:00:04,500"),
                                ("00:00:01:15@30", "00:00:06,500 --> 00:00:08,500")):
            with self.subTest(offset=value):
                srt = OUT / "offset_grammar.srt"
                script("caption.py", "--text", cues, "--write-srt", srt, "--offset", value)
                self.assertIn(expected, srt.read_text(encoding="utf-8"))
        proc = script("caption.py", "--text", cues, "--write-srt", OUT / "offset_bad.srt",
                      "--offset", "half past two", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "failed")
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--offset", doc["error"]["message"])

    def test_caption_max_lines_holds_for_all_caps_text(self):
        """Uppercase is far wider than the mixed-case average: an all-caps cue must be measured
        with a per-character table, or libass re-wraps each line the wrapper produced and four
        lines are drawn where --max-lines 2 was asked for."""
        import caption  # noqa: E402
        text = "WE MEASURE EVERY CAPITAL LETTER BECAUSE UPPERCASE RUNS WIDE"
        cues = OUT / "caps_cue.txt"
        cues.write_text(f"0:01-0:05 {text}\n", encoding="utf-8")
        srt = OUT / "caps_cue.srt"
        script("caption.py", self._small(), "--text", cues, "--size", "48", "--max-lines", "2",
               "--write-srt", srt, "--fast", "-o", OUT / "caps_cue.mp4")
        max_em = 640 * caption.SAFE_WIDTH_FRACTION / (48 * 360 / 288.0)
        blocks = self._srt_cues(srt)
        for _, lines in blocks:
            self.assertLessEqual(len(lines), 2, f"--max-lines 2 exceeded: {lines}")
        # The real DejaVu Sans advances (hmtx/unitsPerEm, unrounded), not caption.py's own table:
        # what libass will actually draw has to fit, or it re-wraps the line and --max-lines 2
        # becomes four lines in the picture.
        real = {"A": .684, "B": .686, "C": .698, "D": .770, "E": .632, "F": .575, "G": .775,
                "H": .752, "I": .295, "J": .295, "K": .656, "L": .557, "M": .863, "N": .748,
                "O": .787, "P": .603, "Q": .787, "R": .695, "S": .635, "T": .611, "U": .732,
                "V": .684, "W": .989, "X": .685, "Y": .611, "Z": .685, " ": .318}
        for _, lines in blocks:
            for line in lines:
                drawn = sum(real[ch] for ch in line)
                self.assertLessEqual(drawn, max_em, f"libass would re-wrap this line: {line!r}")
        self.assertEqual(" ".join(l for _, lines in blocks for l in lines), text)
        self.assertGreater(caption.text_width_em("CAPITALS"), caption.text_width_em("capitals"))

    def test_a_resolved_font_path_with_spaces_survives_into_the_command(self):
        """macOS resolves "/Library/Fonts/Arial Unicode.ttf": a space in the font path must not
        split the info line, the drawtext `fontfile=`, or the libass `fontsdir=`."""
        import _common  # noqa: E402
        spaced_dir = OUT / "font dir"
        spaced_dir.mkdir(exist_ok=True)
        source = default_font_file("DejaVu Sans")
        if not source or not os.path.exists(source):
            self.skipTest("no concrete font file on this machine to copy")
        spaced = spaced_dir / "My Font.ttf"
        shutil.copyfile(source, spaced)

        # the resolver's own answer and the line it prints keep the path whole
        entry = (str(spaced), "My Font")
        saved = dict(_common._SCRIPT_FONT_CACHE)
        try:
            _common._SCRIPT_FONT_CACHE[("ko", None)] = entry
            with contextlib.redirect_stderr(io.StringIO()):  # the resolver's own info line
                _script, resolved, family = _common.script_font_for_text("안녕하세요")
        finally:
            _common._SCRIPT_FONT_CACHE.clear()
            _common._SCRIPT_FONT_CACHE.update(saved)
        self.assertEqual(resolved, str(spaced))
        self.assertEqual(family, "My Font")
        line = f"font: {resolved} (covers ko)"
        self.assertEqual(re.search(r"^font: (.+?) \(covers (\w+)\)", line, re.M).group(1), str(spaced),
                         "the info line's path is read whole, not up to the first space")

        # and the same path reaches ffmpeg as one argument in both draw paths
        proc = script("overlay.py", self._small(), "--text", "spaced", "--font-file", spaced,
                      "--preset", "veryfast", "-o", OUT / "spaced_overlay.mp4", "--json")
        cmd = json.loads(proc.stdout)["commands"][0]
        self.assertIn(f"fontfile={escape_filter_path(str(spaced))}", cmd)
        cues = OUT / "spaced_cue.txt"
        cues.write_text("0:00-0:02 spaced\n", encoding="utf-8")
        proc2 = script("caption.py", self._small(), "--text", cues, "--fonts-dir", spaced_dir,
                       "--fast", "-o", OUT / "spaced_caption.mp4", "--json")
        self.assertIn(f"fontsdir={escape_filter_path(str(spaced_dir))}", json.loads(proc2.stdout)["commands"][0])

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

    def test_caption_mux_writes_faststart_mp4(self):
        """Same shape as #275/#277: --mode mux stream-copies video/audio with -c:v copy / -c:a
        copy while only adding a subtitle track, and must write -movflags +faststart on an mp4
        output the same way every other mp4-writing path does."""
        srt = OUT / "mux_faststart_cues.srt"
        out = OUT / "cap_mux_faststart.mp4"
        script("caption.py", self.src, "--text", self.cues, "--write-srt", srt, "--mode", "mux", "-o", out)
        self.assertTrue(_is_faststart(out), "caption.py --mode mux must write +faststart")

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

    def test_srt_lang_suffix_parsing(self):
        """`FILE:lang` splits on the last colon, and only when the suffix is a language code and
        the whole token is not itself a file on disk -- so a Windows path and a file genuinely
        named `a:b.srt` survive."""
        import caption  # noqa: E402
        self.assertEqual(caption.split_srt_lang("en.srt:en"), ("en.srt", "en"))
        self.assertEqual(caption.split_srt_lang("subs/file.srt:pt-BR"), ("subs/file.srt", "pt-BR"))
        self.assertEqual(caption.split_srt_lang("plain.srt"), ("plain.srt", None))
        # A Windows drive path is handled by the parser alone, with no file on disk: the drive
        # letter is a one-character head that is not a language tag, in either slash style.
        self.assertEqual(caption.split_srt_lang("C:\\subs\\en.srt"), ("C:\\subs\\en.srt", None))
        self.assertEqual(caption.split_srt_lang("C:/subs/en.srt"), ("C:/subs/en.srt", None))
        self.assertEqual(caption.split_srt_lang("D:\\media\\ja.srt"), ("D:\\media\\ja.srt", None))
        # "the whole token is a file on disk, so do not split it" -- exercised with a colon-free
        # name, which every OS can create.
        plain = OUT / "suffix_plain.srt"
        plain.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        self.assertEqual(caption.split_srt_lang(str(plain)), (str(plain), None))
        if platform.system() != "Windows":
            # ... and, where the filesystem allows it, with a name that really contains a colon
            odd = OUT / "a:b.srt"
            odd.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
            self.assertEqual(caption.split_srt_lang(str(odd)), (str(odd), None))
        # MPEG-4 needs the ISO-639-2 spelling (verified empirically: ffmpeg silently writes NO
        # language tag for a two-letter code in .mp4); Matroska stores what it is given.
        self.assertEqual(caption.container_language("ja", "x.mp4"), "jpn")
        self.assertEqual(caption.container_language("ja", "x.mkv"), "ja")

    def test_duplicate_language_and_bad_code_are_refused(self):
        srt = OUT / "mux_dup.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        script("caption.py", self.src, "--mode", "mux", "--srt", f"{srt}:en", "--srt", f"{srt}:en",
               "-o", OUT / "dup.mkv", expect_fail=True)
        script("caption.py", self.src, "--mode", "mux", "--srt", f"{srt}:en",
               "--default-track", "ja", "-o", OUT / "dup2.mkv", expect_fail=True)
        # a suffix meant as a language code but shaped wrong is a language error naming the
        # token, not "SRT file not found: en.srt:zzzz"
        proc = script("caption.py", self.src, "--mode", "mux", "--srt", f"{srt}:zzzzzzzzzzz",
                      "-o", OUT / "dup3.mkv", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("zzzzzzzzzzz", doc["error"]["message"])
        self.assertIn("not a language code", doc["error"]["message"])
        # a genuinely missing file still says so
        missing = script("caption.py", self.src, "--mode", "mux",
                         "--srt", str(OUT / "no_such_file.srt") + ":en",
                         "-o", OUT / "dup4.mkv", expect_fail=True)
        self.assertIn("not found", missing.stderr)

    def test_every_missing_extra_srt_track_is_named_at_once(self):
        """2.2.1: two missing extra tracks are one refusal naming both, not two reruns."""
        srt = OUT / "mux_multi_ok.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        proc = script("caption.py", self.src, "--mode", "mux", "--srt", f"{srt}:en",
                      "--srt", str(OUT / "gone_ja.srt") + ":ja", "--srt", str(OUT / "gone_fr.srt") + ":fr",
                      "-o", OUT / "multi_missing.mkv", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertEqual([p["index"] for p in doc["problems"]], [1, 2])
        self.assertIn("2 SRT file(s) not found", doc["error"]["message"])

    def test_burn_with_two_srts_refused(self):
        srt = OUT / "mux_burn2.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        script("caption.py", self.src, "--srt", f"{srt}:en", "--srt", f"{srt}:ja",
               "-o", OUT / "burn2.mp4", expect_fail=True)

    def test_mux_three_languages_into_mkv(self):
        """Three tracks in one call: nothing re-encoded, every stream tagged, and check.py's new
        informational `subtitles` row lists all three."""
        files = {}
        for lang, text in (("en", "Hello"), ("ja", "\u3053\u3093\u306b\u3061\u306f"), ("es", "Hola")):
            f = OUT / f"mux3_{lang}.srt"
            f.write_text(f"1\n00:00:00,000 --> 00:00:02,000\n{text}\n", encoding="utf-8")
            files[lang] = f
        out = OUT / "cap_mux3.mkv"
        res = json.loads(script("caption.py", self.src, "--mode", "mux",
                                "--srt", f"{files['en']}:en", "--srt", f"{files['ja']}:ja",
                                "--srt", f"{files['es']}:es", "--default-track", "en",
                                "--json", "-o", out).stdout)
        self.assertEqual(res["subtitle_tracks"], 3)
        self.assertEqual([t["language"] for t in res["tracks"]], ["en", "ja", "es"])
        self.assertEqual([t["default"] for t in res["tracks"]], [True, False, False])
        disp = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                  "stream_disposition=default", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(disp, ["1", "0", "0"], "the file disagrees with tracks[].default")
        self.assertEqual(res["tracks"][1]["title"], "\u65e5\u672c\u8a9e")
        src_m, m = probe(str(self.src)), probe(str(out))
        self.assertEqual(m["subtitle_streams"], 3)
        # ffprobe reports Matroska's codes verbatim (empirically: `en`, not `eng`)
        langs = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                   "stream_tags=language", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(langs, ["en", "ja", "es"])
        self.assertEqual(m["video"]["codec"], src_m["video"]["codec"], "video was re-encoded")
        self.assertEqual(m["audio"]["codec"], src_m["audio"]["codec"], "audio was re-encoded")
        chk = json.loads(script("check.py", out, "--platform", "youtube", "--no-loudness",
                                "--json").stdout)
        subs_row = [r for r in chk["checks"] if r["check"] == "subtitles"]
        self.assertEqual(len(subs_row), 1)
        self.assertEqual(subs_row[0]["status"], "PASS")
        for code in ("en", "ja", "es"):
            self.assertIn(code, subs_row[0]["value"])

    def test_mux_without_default_track_leaves_every_matroska_track_off(self):
        """Given two or more new subtitle streams and no --default-track, ffmpeg flags the first
        one `default` by itself -- the opposite of what the flag promises, and `tracks[].default`
        then described a file that did not exist. Every disposition is stated explicitly now."""
        files = []
        for lang in ("en", "ja"):
            f = OUT / f"mux_nodef_{lang}.srt"
            f.write_text("1\n00:00:00,000 --> 00:00:02,000\nx\n", encoding="utf-8")
            files.append(f"{f}:{lang}")
        out = OUT / "cap_mux_nodef.mkv"
        res = json.loads(script("caption.py", self.src, "--mode", "mux",
                                *[a for f in files for a in ("--srt", f)],
                                "--json", "-o", out).stdout)
        disp = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                  "stream_disposition=default", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(disp, ["0", "0"], "a track was marked default that nobody asked for")
        self.assertEqual([t["default"] for t in res["tracks"]], [False, False])

    def test_mux_into_mp4_converts_to_iso639_2_and_warns_about_players(self):
        """Empirically, an .mp4 keeps three mov_text tracks but drops a two-letter language code
        outright -- so the code is converted and the caller is told the container is the wrong
        one for a switchable deliverable."""
        files = []
        for lang in ("en", "ja", "es"):
            f = OUT / f"mux3mp4_{lang}.srt"
            f.write_text("1\n00:00:00,000 --> 00:00:02,000\nx\n", encoding="utf-8")
            files.append(f"{f}:{lang}")
        out = OUT / "cap_mux3.mp4"
        res = json.loads(script("caption.py", self.src, "--mode", "mux", *[a for f in files for a in ("--srt", f)],
                                "--json", "-o", out).stdout)
        self.assertEqual([t["language"] for t in res["tracks"]], ["eng", "jpn", "spa"])
        langs = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                   "stream_tags=language", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(langs, ["eng", "jpn", "spa"])
        self.assertTrue(any(".mkv" in n for n in res.get("notes") or []), res.get("notes"))
        # MPEG-4 stores no per-track title ffprobe reads back, so none is claimed
        self.assertEqual([t["title"] for t in res["tracks"]], [None, None, None])
        self.assertEqual(sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                            "stream_tags=title", "-of", "csv=p=0", out).stdout.split(), [])
        # ... and it always enables its first subtitle track, which tracks[] must not deny
        disp = sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                  "stream_disposition=default", "-of", "csv=p=0", out).stdout.split()
        self.assertEqual([("1" if t["default"] else "0") for t in res["tracks"]], disp)

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

    def test_hdr_to_sdr_tonemap(self):
        out = OUT / "sdr.mp4"
        script("color.py", self.hdr, "--to-sdr", "--preset", "veryfast", "-o", out)
        v = probe(str(out))["video"]
        self.assertFalse(v["hdr"])
        self.assertEqual((v["color_transfer"], v["color_primaries"], v["pix_fmt"]), ("bt709", "bt709", "yuv420p"))
        self.assertEqual((v["width"], v["height"]), (1920, 1080))
        # refuses on SDR input unless forced
        script("color.py", self.src, "--to-sdr", expect_fail=True)

    def test_to_sdr_bt2020_sdr_converts_gamut_without_tonemap(self):
        """BT.2020 primaries on an SDR transfer are not HDR: --to-sdr converts the gamut only.
        It used to tone-map them as PQ, darkening white Y 235 -> 151 and grey 126 -> 90 while
        still reporting verified: true. White and grey must come out where they went in."""
        wide = OUT / "bt2020_sdr_levels.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:size=320x120:rate=30",
           "-f", "lavfi", "-i", "color=c=0x808080:size=320x120:rate=30", "-t", "1",
           "-filter_complex", "[0][1]vstack,format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=bt709:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1", wide)

        def luma(path, crop):
            proc = sh("ffmpeg", "-hide_banner", "-i", str(path), "-frames:v", "1",
                      "-vf", f"crop={crop},format=yuv420p,signalstats,metadata=print:file=-", "-f", "null", "-")
            return float(re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", proc.stdout).group(1))

        out = OUT / "bt2020_sdr_to_sdr.mp4"
        proc = script("color.py", wide, "--to-sdr", "--fast", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["verified"])
        v = probe(str(out))["video"]
        self.assertEqual((v["color_transfer"], v["color_primaries"], v["color_space"]), ("bt709", "bt709", "bt709"))
        for crop in ("iw:ih/2-8:0:4", "iw:ih/2-8:0:ih/2+4"):  # white half, mid-grey half
            self.assertLessEqual(abs(luma(out, crop) - luma(wide, crop)), 3, crop)
        self.assertEqual(doc["sdr_path"], "gamut")
        self.assertTrue(any("without a tone map" in n for n in doc["notes"]))
        self.assertFalse(any("tonemap" in c for c in doc["commands"]), doc["commands"])

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
        self.assertEqual(self._frame_count(zero), self._frame_count(self.src), "no frame may be dropped or duplicated by a no-op grade")
        script("color.py", self.src, "--lut", lut, "--lut-strength", "2.5", "-o", OUT / "lut_oob.mp4", expect_fail=True)
        script("color.py", self.src, "--lut", lut, "--lut-strength", "-1", "-o", OUT / "lut_oob2.mp4", expect_fail=True)

    def test_color_correct_identity_holds_on_a_bt709_tagged_source(self):
        """#159: the identity test below only ever ran on the untagged synthetic source. On a
        source *tagged* bt709 (any camera file, anything export.py wrote) an all-defaults
        --correct came back 26 dB PSNR and ~8 % less saturated, because libavfilter's auto-
        inserted swscale legs around the RGB filters disagreed: yuv->rgb honoured the frame's
        bt709 tag, rgb->yuv used the default bt601. Both legs are now pinned to one matrix, so
        the result is the same on a tagged and an untagged copy of the same pixels, on FFmpeg
        5.1 through 8.1 (measured 39.5 dB on all four)."""
        tagged = OUT / "correct_src709.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.src), "-t", "3",
           "-vf", "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-an", str(tagged))
        self.assertEqual(probe(str(tagged))["video"]["color_space"], "bt709")
        untagged = OUT / "correct_srcU.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.src), "-t", "3", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-an", str(untagged))
        results = {}
        for name, src in (("tagged", tagged), ("untagged", untagged)):
            out = OUT / f"correct_identity_{name}.mp4"
            data = json.loads(script("color.py", src, "--correct", "--preset", "veryfast", "-o", out, "--json").stdout)
            m = data["measurements"]
            self.assertAlmostEqual(m["input"]["saturation_avg"], m["output"]["saturation_avg"], delta=2.5, msg=name)
            results[name] = self._psnr(src, out)
            self.assertGreater(results[name], 36, f"{name}: an all-defaults --correct must be near-identity, got {results[name]:.1f} dB")
        self.assertAlmostEqual(results["tagged"], results["untagged"], delta=1.0, msg="the colour tag must not change what --correct does to the pixels")

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

    # ---------------------------------------------------------------- --karaoke-style word (#276)
    def test_karaoke_style_default_sweep_is_byte_identical_to_omitting_the_flag(self):
        """The mode selector must not change a single byte of today's \\kf output for a caller who
        never asks for --karaoke-style word: the default has to stay exactly 'sweep'."""
        ass_default = OUT / "kstyle_default.ass"
        ass_sweep = OUT / "kstyle_sweep.ass"
        script("caption.py", self.src, "--text", self.cues, "--karaoke", "--write-ass", ass_default,
               "--karaoke-timing", "even", "--preset", "veryfast", "-o", OUT / "kstyle_default.mp4")
        script("caption.py", self.src, "--text", self.cues, "--karaoke", "--karaoke-style", "sweep",
               "--karaoke-timing", "even", "--write-ass", ass_sweep, "--preset", "veryfast", "-o", OUT / "kstyle_sweep.mp4")
        self.assertEqual(ass_default.read_bytes(), ass_sweep.read_bytes(),
                         "--karaoke-style sweep (explicit or default) must be byte-identical")
        self.assertIn("WrapStyle: 0", ass_default.read_text(encoding="utf-8-sig"),
                      "sweep mode's header is unchanged from before this flag existed")

    def test_karaoke_style_word_emits_one_dialogue_event_per_word_covering_its_span(self):
        gappy = OUT / "gappy_kw.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)':s=48000",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "4", "-c:v", "libx264",
           "-preset", "veryfast", "-c:a", "aac", gappy)
        cues = OUT / "kwcues.txt"
        cues.write_text("0:00-0:04 one two three four\n", encoding="utf-8")
        ass = OUT / "kword.ass"
        script("caption.py", gappy, "--text", cues, "--karaoke", "--karaoke-style", "word",
               "--karaoke-timing", "even", "--write-ass", ass, "--fast", "-o", OUT / "kword.mp4")
        text = ass.read_text(encoding="utf-8-sig")
        self.assertIn("WrapStyle: 2", text, "word mode freezes the line break: libass must not re-wrap")
        dialogues = [l for l in text.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 4, "one Dialogue event per word, not per cue")
        # even timing over 4 s / 4 words -> 1 s each
        expected_bounds = [("0:00:00.00", "0:00:01.00"), ("0:00:01.00", "0:00:02.00"),
                           ("0:00:02.00", "0:00:03.00"), ("0:00:03.00", "0:00:04.00")]
        for line, (want_start, want_end) in zip(dialogues, expected_bounds):
            fields = line.split(",", 3)
            self.assertEqual(fields[1], want_start)
            self.assertEqual(fields[2], want_end)
        # every event still carries the WHOLE cue text, not just the active word
        for line in dialogues:
            for word in ("one", "two", "three", "four"):
                self.assertIn(word, line)

    def test_karaoke_style_word_active_word_is_scaled_and_a_distinct_colour(self):
        cues = OUT / "kwcues2.txt"
        cues.write_text("0:00-0:02 alpha beta\n", encoding="utf-8")
        ass = OUT / "kword2.ass"
        script("caption.py", self.src, "--text", cues, "--karaoke", "--karaoke-style", "word",
               "--karaoke-timing", "even", "--karaoke-scale", "130", "--highlight-color", "1EC3FC",
               "--color", "FFFFFF", "--upcoming-color", "808080", "--write-ass", ass,
               "--preset", "veryfast", "-o", OUT / "kword2.mp4")
        dialogues = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 2)
        first, second = dialogues
        self.assertIn(r"\fscx130", first)
        self.assertIn(r"\fscy130", first)
        self.assertIn("&H00FCC31E", first, "active word carries --highlight-color")
        self.assertIn("&H00808080", first, "the not-yet-spoken word carries --upcoming-color")
        self.assertIn("&H00FCC31E", second, "the second event's active word (beta) also gets --highlight-color")
        self.assertIn("&H00FFFFFF", second, "the already-spoken word (alpha) falls back to --color")

    def test_karaoke_style_word_preserves_explicit_line_breaks(self):
        """A cue with a manual two-line break (the `|` syntax) must keep exactly that \\N split in
        every per-word event -- the frozen line list from layout_cues, not a re-wrap."""
        cues = OUT / "kwcues3.txt"
        cues.write_text("0:00-0:02 top line | bottom line\n", encoding="utf-8")
        ass = OUT / "kword3.ass"
        script("caption.py", self.src, "--text", cues, "--karaoke", "--karaoke-style", "word",
               "--karaoke-timing", "even", "--write-ass", ass, "--preset", "veryfast", "-o", OUT / "kword3.mp4")
        dialogues = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 4, "top line + bottom line = 4 words -> 4 events")
        for line in dialogues:
            self.assertEqual(line.count("\\N"), 1, "each event keeps the one frozen line break")
            before, _, after = line.partition("\\N")
            self.assertTrue(any(w in before for w in ("top", "line")))
            self.assertTrue(any(w in after for w in ("bottom", "line")))

    def test_karaoke_style_word_handles_emoji_placeholders_and_brace_escaping(self):
        assets = _emoji_assets()
        cues = OUT / "kwcues4.txt"
        cues.write_text("0:00-0:02 say {hi} \U0001F389 now\n", encoding="utf-8")
        ass = OUT / "kword4.ass"
        script("caption.py", self.src, "--text", cues, "--karaoke", "--karaoke-style", "word",
               "--karaoke-timing", "even", "--emoji-assets", assets, "--write-ass", ass,
               "--preset", "veryfast", "-o", OUT / "kword4.mp4")
        text = ass.read_text(encoding="utf-8-sig")
        dialogues = [l for l in text.splitlines() if l.startswith("Dialogue:")]
        # "say", "{hi}" (escaped) and "now" get their own event; the emoji token is a placeholder
        # with no real duration of its own (same as --karaoke-style sweep's \kf0 emoji segment)
        self.assertEqual(len(dialogues), 3)
        self.assertNotIn("{\\pos", text, "cue text must not be able to open a real override block")
        self.assertIn(r"\{hi\}", text, "the braces the user typed are escaped, not dropped")
        for line in dialogues:
            self.assertNotIn("\U0001F389", line, "the emoji glyph itself is replaced by the drawtext/libass placeholder")

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
        # Python's own bin dir has to stay on PATH, and on a system-python machine (the Debian
        # container job) that dir is /usr/bin, which also holds the real fc-match -- so "hidden
        # by PATH" was not hidden at all there and the tool resolved a real fontfile= instead of
        # taking the font= fallback this test exists to exercise. A stub fc-match that always
        # fails sits first on PATH so the resolver returns None on every layout.
        if platform.system() != "Windows":
            stub = stub_dir / "fc-match"
            stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            stub.chmod(0o755)
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
        script("caption.py", self.src, "--text", self.cues, "--font", hostile_font, "--animate", "fade", "--write-ass", ass_out, "--fast", "-o", OUT / "font_inject.mp4")
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
        # a real (fast) burn: since 1.4.9 --dry-run writes no side files, the generated ASS included
        script("caption.py", self.src, "--text", hostile_cues, "--animate", "fade", "--write-ass", ass_out, "--fast", "-o", OUT / "brace_inject.mp4")
        dialogue = next(l for l in ass_out.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue: "))
        # --animate fade legitimately prepends its own "{\fad(200,200)}" override block; only the
        # cue-text-derived braces from the hostile payload must be gone.
        self.assertNotIn("{\\pos(0,0)\\fscx500}", dialogue, "cue text must not be able to open a real ASS override block")
        self.assertIn("\\{\\pos(0,0)\\fscx500\\}INJECTED", dialogue,
                      "the braces the user typed are ESCAPED (libass \\{ / \\}), not deleted: the cue "
                      "reads out exactly what was written and still cannot open an override block")

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
        """Before 1.15 this text went inline into the filtergraph, where two characters had no
        escape that survives every call shape: ';' splits a filterchain exactly like ',', and the
        quote corrupts a -filter_complex chain that uses explicit [label] pads (trailing option
        text leaked into the picture as burnt-in literal text). The old fix dropped the quote and
        escaped the semicolon. 1.15 removes the whole class: the drawn text is handed to drawtext
        as `textfile=<path>:expansion=none`, so the graph parser never sees it -- the quote is now
        KEPT, and nothing can leak into the options. Assert the new route, not the old escape."""
        out = OUT / "semicolon_quote.mp4"
        doc = json.loads(script("overlay.py", self.src, "--text", "a'b;c", "-o", out, "--json").stdout)
        graph = " ".join(doc["commands"])
        m = re.search(r"textfile=(\S+?\.txt)", graph.replace("\\", ""))
        self.assertTrue(m, "drawn text must go through textfile=, not inline: " + graph)
        self.assertIn("expansion=none", graph)
        self.assertNotIn("a\\;c", graph, "no inline escaped copy of the text may remain in the graph")
        # The textfile lives in a private 0700 per-run directory and is removed when the run
        # ends -- assert both, since a world-shared, never-cleaned /tmp directory was the 1.15.0
        # shape. The frame ink below is what proves the characters reached the picture.
        self.assertTrue(Path(m.group(1)).parent.name.startswith("ffmpeg-skill-text-"),
                        "drawn text must go in a private per-run directory: " + m.group(1))
        self.assertFalse(Path(m.group(1)).exists(),
                         "the drawn-text temp file must not outlive the run")
        self.assertEqual(doc["status"], "completed")
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

    def test_sticker_hook_and_meme_draw_ink_where_they_promise(self):
        """The three social graphics templates: each must render, put ink where the layout says it
        goes (top band for the hook's progress bar, the two edges for a meme), and -- for the
        sticker -- stay inside the platform's safe zone when --platform names one."""
        sys.path.insert(0, str(SCRIPTS))
        from _platforms import PLATFORMS
        vertical = OUT / "safe_vertical.mp4"
        script("fit.py", self.src, "--duration", "4", "--aspect", "9:16", "--fit", "crop",
               "--width", "540", "--fast", "-o", vertical)
        base = self._region_stats(vertical, "iw:60:0:0", at=1.0)

        sticker = OUT / "gfx_sticker.mp4"
        doc = json.loads(script("graphics.py", vertical, "--template", "sticker", "--text", "NEW",
                                "--position", "top-right", "--platform", "tiktok", "--fast",
                                "-o", sticker, "--json").stdout)
        self.assertTrue(os.path.exists(sticker))
        drawtext = [c for c in doc["commands"] if "drawtext" in c][0]
        safe = PLATFORMS["tiktok"]["safe"]
        W, H = 540, 960
        right = int(re.search(r"x=w-text_w-(\d+)", drawtext).group(1))
        top = int(re.search(r"y=[^0-9]*(\d+)\+", drawtext).group(1))  # the shell quoting around the expression varies
        self.assertGreaterEqual(right, round(safe["right"] * W) - 1, "the sticker must clear the like column")
        self.assertGreaterEqual(top, round(safe["top"] * H) - 1, "the sticker must clear the status bar")

        hook = OUT / "gfx_hook.mp4"
        script("graphics.py", vertical, "--template", "hook", "--title", "How I cut this",
               "--duration", "3", "--fast", "-o", hook)
        band_avg, _ = self._region_stats(hook, "iw:12:0:0", at=0.5)
        late_avg, _ = self._region_stats(hook, "iw:12:0:0", at=3.5)
        self.assertGreater(abs(band_avg - late_avg), 4,
                           "the hook's progress bar must be drawn while the card is up and gone after it")
        mid_card, _ = self._region_stats(hook, "iw:200:0:380", at=0.5)
        mid_after, _ = self._region_stats(hook, "iw:200:0:380", at=3.5)
        self.assertNotAlmostEqual(mid_card, mid_after, delta=1.0,
                                  msg="the hook card must darken the middle of the frame while it is up")

        meme = OUT / "gfx_meme.mp4"
        script("graphics.py", vertical, "--template", "meme", "--top", "when the render",
               "--bottom", "finally finishes", "--fast", "-o", meme)
        plain_top, _ = self._region_stats(vertical, "iw:120:0:40", at=1.0)
        meme_top, _ = self._region_stats(meme, "iw:120:0:40", at=1.0)
        plain_bottom, _ = self._region_stats(vertical, "iw:120:0:820", at=1.0)
        meme_bottom, _ = self._region_stats(meme, "iw:120:0:820", at=1.0)
        self.assertNotAlmostEqual(meme_top, plain_top, delta=0.5, msg="meme --top draws nothing")
        self.assertNotAlmostEqual(meme_bottom, plain_bottom, delta=0.5, msg="meme --bottom draws nothing")
        script("graphics.py", vertical, "--template", "sticker", expect_fail=True)
        script("graphics.py", vertical, "--template", "meme", expect_fail=True)

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

    def test_caption_sidecars_are_refused_like_the_video_without_overwrite(self):
        """caption.py's .srt/.ass sidecars go through the --overwrite check the video does, before
        speech recognition and the first write, dry runs included. Through 2.2.3 a hand-corrected
        final.srt was replaced on a re-run with the same -o, even by a run ffmpeg then refused."""
        def raw(name, *a, **kw):  # script() adds --overwrite whenever -o is given
            return sh(sys.executable, SCRIPTS / name, *a, **kw)

        d = OUT / "cap_sidecar_overwrite"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        cues = d / "cues.txt"
        cues.write_text("0-1.5 Hello there\n1.5-3 Second line\n", encoding="utf-8")
        out, srt, ass = d / "final.mp4", d / "final.srt", d / "final.ass"
        hand = "1\n00:00:00,000 --> 00:00:01,000\nHAND EDITED\n"

        def reset():
            for p in (out, ass):
                if p.exists():
                    p.unlink()
            srt.write_text(hand, encoding="utf-8")

        # --text burning into a new video: the existing final.srt alone is enough to refuse
        reset()
        proc = raw("caption.py", self.src, "--text", cues, "-o", out, "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("refusing to overwrite", doc["error"]["message"])
        self.assertIn("final.srt", doc["error"]["message"])
        self.assertEqual(srt.read_text(encoding="utf-8"), hand, "a refused run leaves the hand edit alone")
        self.assertFalse(out.exists(), "refused before ffmpeg ran")
        # the dry run predicts the same refusal and writes nothing
        dry = raw("caption.py", self.src, "--text", cues, "-o", out, "--dry-run", "--json", expect_fail=True)
        self.assertIn("refusing to overwrite", json.loads(dry.stdout)["error"]["message"])
        # both sidecars and the video are named together
        out.write_bytes(b"x")
        ass.write_text("hand ass", encoding="utf-8")
        proc = raw("caption.py", self.src, "--text", cues, "--animate", "pop", "-o", out, "--json", expect_fail=True)
        msg = json.loads(proc.stdout)["error"]["message"]
        for name in ("final.srt", "final.ass", "final.mp4"):
            self.assertIn(name, msg)
        self.assertEqual(ass.read_text(encoding="utf-8"), "hand ass")
        self.assertEqual(srt.read_text(encoding="utf-8"), hand)
        # text-only mode (--write-srt, no video)
        reset()
        proc = raw("caption.py", "--text", cues, "--write-srt", srt, "--json", expect_fail=True)
        self.assertIn("refusing to overwrite", json.loads(proc.stdout)["error"]["message"])
        self.assertEqual(srt.read_text(encoding="utf-8"), hand)
        # --transcribe is refused before any recognition starts (with or without an engine
        # installed: the refusal, not the engine's absence, is the answer)
        proc = raw("caption.py", self.src, "--transcribe", "-o", out, "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertIn("refusing to overwrite", doc["error"]["message"])
        self.assertNotIn("speech-to-text", proc.stderr)
        self.assertEqual(doc.get("commands") or [], [])
        self.assertEqual(srt.read_text(encoding="utf-8"), hand)
        # --overwrite is the consent: the sidecar is replaced
        script("caption.py", "--text", cues, "--write-srt", srt, "--overwrite")
        self.assertIn("Hello there", srt.read_text(encoding="utf-8-sig"))
        reset()
        script("caption.py", self.src, "--text", cues, "-o", out, "--overwrite", "--fast")
        self.assertIn("Hello there", srt.read_text(encoding="utf-8-sig"))
        self.assertTrue(out.exists())
        shutil.rmtree(d)

    def test_overlay_fade_without_start_end_fades_in_only(self):
        """--fade without --end fades in at 0 and stays; the fade-out belongs to --end (eval 6,
        e03-logo: every "fade in at the start" run had to caveat an unasked-for fade-out)."""
        proc = script("overlay.py", self.src, "--image", self.logo, "--fade", "0.5", "--dry-run")
        self.assertIn("fade=t=in:st=0.000", proc.stderr)
        self.assertNotIn("fade=t=out", proc.stderr)
        self.assertNotIn("\nwrote ", proc.stderr, "dry-run must not claim a file was written")
        proc = script("overlay.py", self.src, "--image", self.logo, "--fade", "0.5", "--end", "5", "--dry-run")
        self.assertIn("fade=t=out:st=4.500", proc.stderr)

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

    # ------------------------------------------- 1.17: the size is fitted before the cue splits
    def _fit_cues(self):
        cues = OUT / "cues_fit.txt"
        cues.write_text("0:00-0:03 A third line the tool times for me\n"
                        "0:03-0:06 Segunda l\u00ednea de subt\u00edtulos\n", encoding="utf-8")
        return cues

    def test_caption_fit_size_shrinks_instead_of_splitting_the_sentence(self):
        """e2e: at the TikTok caption size these cues needed four lines and were split into
        consecutive cues (eval 17). 1.17 drops the size until they fit instead."""
        vert, cues = self._vertical(), self._fit_cues()
        out = OUT / "cap_fit.mp4"
        data = json.loads(script("caption.py", vert, "--text", cues, "--platform", "tiktok",
                                 "--max-lines", "2", "--animate", "fade",
                                 "--font", "DejaVu Sans", "--write-ass", OUT / "cap_fit.ass",
                                 "-o", out, "--json").stdout)
        cap = data["caption"]
        self.assertEqual(cap["fit_size"], "auto")
        self.assertEqual(cap["fit_scope"], "file")
        self.assertLess(cap["size_used"], cap["size_requested"])
        self.assertEqual(cap["size_floor"], 13)
        self.assertGreaterEqual(cap["shrunk"], 1)
        self.assertFalse(cap["fit_exhausted"])
        self.assertEqual(cap["split"], 0)           # the whole point: nothing was split
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 1920))
        # the ASS on disk carries the shrunk size, and each cue is one cue of two lines
        ass = (OUT / "cap_fit.ass").read_text(encoding="utf-8-sig")
        style = next(l for l in ass.splitlines() if l.startswith("Style:"))
        self.assertEqual(int(style.split(",")[2]), round(cap["size_used"] * 1920 / 288))
        dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogue), 2)
        for line in dialogue:
            self.assertEqual(line.count("\\N"), 1)

    def test_caption_scope_cue_lays_each_cue_out_at_its_own_size(self):
        """The regression: with scope=cue every cue was wrapped to the FILE's budget -- the
        budget of the smallest size, which is the widest line in em -- and then drawn at its own
        larger size, so lines ran off the side of the frame. Each cue is now laid out at the size
        it is drawn at, and no rendered line exceeds the safe width.

        1.17.2: "the safe width" is now the ASS Style's real column (play_w minus the horizontal
        safe margins), not play_w * SAFE_WIDTH_FRACTION, and the third cue genuinely needs three
        lines at the floor in TikTok's narrower column -- it is split, and says so."""
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        text_mod = importlib.import_module("_common.text")
        caption_mod = importlib.import_module("caption")
        vert = self._vertical()
        cues = OUT / "cues_scope.txt"
        cues.write_text("0:00-0:03 A third line the tool times for me\n"
                        "0:03-0:05 Hi\n"
                        "0:05-0:08 Una tercera l\u00ednea con tiempos autom\u00e1ticos\n",
                        encoding="utf-8")
        ass = OUT / "cap_scope.ass"
        data = json.loads(script("caption.py", vert, "--text", cues, "--platform", "tiktok",
                                 "--max-lines", "2", "--animate", "fade", "--font", "DejaVu Sans",
                                 "--fit-size-scope", "cue", "--write-ass", ass,
                                 "-o", OUT / "cap_scope.mp4", "--json").stdout)
        cap = data["caption"]
        self.assertEqual(cap["fit_scope"], "cue")
        # a cue is split only when the floor really cannot hold it, and then it is reported
        self.assertEqual(bool(cap["split"]), bool(cap["fit_exhausted"]),
                         "a split without fit_exhausted means the budget, not the floor, gave way")

        body = ass.read_text(encoding="utf-8-sig")
        style_line = next(l for l in body.splitlines() if l.startswith("Style:"))
        style_px = int(style_line.split(",")[2])
        margin_l, margin_r = (int(style_line.split(",")[-4]), int(style_line.split(",")[-3]))
        dialogue = [l for l in body.splitlines() if l.startswith("Dialogue:")]
        self.assertGreaterEqual(len(dialogue), 3)
        # at least two different drawn sizes, which is the whole point of the flag
        drawn = set()
        # the column libass actually draws into -- the same number the fitter measured
        safe_px = 1080 - margin_l - margin_r
        self.assertAlmostEqual(safe_px / 1080.0,
                               caption_mod.safe_width_fraction(
                                   type("A", (), {"platform": "tiktok", "animate": "fade",
                                                  "karaoke": False, "ass": None})(), 1080),
                               places=6)
        for line in dialogue:
            payload = line.split(",,0,0,0,,", 1)[1]
            override = re.search(r"\{\\fs(\d+)\}", payload)
            px = int(override.group(1)) if override else style_px
            drawn.add(px)
            body_text = re.sub(r"\{[^}]*\}", "", payload)
            for rendered in body_text.split("\\N"):
                width = text_mod.text_width_em(rendered) * px
                self.assertLessEqual(width, safe_px,
                                     f"{rendered!r} is {width:.0f}px at size {px}, safe {safe_px:.0f}px")
        self.assertGreaterEqual(len(drawn), 2)

    def test_caption_fit_size_off_matches_the_pinned_ass(self):
        """The stability answer: one flag restores the old layout, byte for byte against a pinned
        file (tests/fixtures/caption_1_16_1_fitsize_off.ass).

        The fixture was generated by 1.16.1's own caption.py and RE-PINNED at 1.17.2: it carried
        the defect this release fixes -- MarginL=MarginR=MarginV=420 on a 1080-wide frame, a
        240 px text column -- so it pinned wrong bytes. The re-pin keeps --fit-size off meaning
        exactly what it meant (the size is never shrunk); only the side margins, and the wrap
        budget that now agrees with them, differ."""
        vert, cues = self._vertical(), self._fit_cues()
        ass = OUT / "cap_fit_off.ass"
        script("caption.py", vert, "--text", cues, "--platform", "tiktok", "--max-lines", "2",
               "--animate", "fade", "--font", "DejaVu Sans", "--fit-size", "off",
               "--write-ass", ass, "-o", OUT / "cap_fit_off.mp4")
        pinned = Path(__file__).resolve().parent / "fixtures" / "caption_1_16_1_fitsize_off.ass"
        self.assertEqual(ass.read_bytes(), pinned.read_bytes())

    # ------------------------------------------------- 1.17.2: the horizontal margins are horizontal
    def _style_margins(self, ass_path):
        """(MarginL, MarginR, MarginV) from the ASS Style line."""
        style = next(l for l in Path(ass_path).read_text(encoding="utf-8-sig").splitlines()
                     if l.startswith("Style: Default,"))
        fields = style.split(",")
        return int(fields[-4]), int(fields[-3]), int(fields[-2])

    def test_caption_style_margins_are_the_horizontal_safe_zone(self):
        """1.17.2, the eval-19 defect: --margin is the VERTICAL safe margin (TikTok's 22 % bottom
        bar = 63 ASS units = 420 px on a 1920-tall frame) and 1.14-1.17.1 wrote it into MarginL
        and MarginR as well, leaving a 240 px text column on a 1080-wide frame. The side margins
        come from the destination's own left/right safe zone instead."""
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        platforms = importlib.import_module("_platforms")
        ass = OUT / "cap_margins.ass"
        script("caption.py", self._vertical(), "--text", self._fit_cues(), "--platform", "tiktok",
               "--animate", "pop", "--karaoke", "--font", "DejaVu Sans",
               "--write-ass", ass, "-o", OUT / "cap_margins.mp4")
        left, right, vertical = self._style_margins(ass)
        safe = platforms.safe_of("tiktok")
        self.assertEqual((left, right), (round(safe["left"] * 1080), round(safe["right"] * 1080)))
        self.assertAlmostEqual(vertical, safe["bottom"] * 1920, delta=4)   # via whole ASS units
        # the column libass is given, not the sliver the vertical margin used to leave
        self.assertGreater(1080 - left - right, 0.75 * 1080)
        self.assertLess(left + right, 2 * vertical)

    def test_caption_style_margins_without_a_platform_are_the_conventional_border(self):
        """No --platform: the sides are the (1 - SAFE_WIDTH_FRACTION)/2 border the wrapper has
        always assumed, so the fitter's budget and libass's column are the same number."""
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        text_mod = importlib.import_module("_common.text")
        ass = OUT / "cap_margins_noplat.ass"
        script("caption.py", self._vertical(), "--text", self._fit_cues(), "--animate", "fade",
               "--font", "DejaVu Sans", "--write-ass", ass, "-o", OUT / "cap_margins_noplat.mp4")
        left, right, _ = self._style_margins(ass)
        self.assertEqual(left + right,
                         round((1 - text_mod.SAFE_WIDTH_FRACTION) * 1080))

    def test_caption_two_words_stay_on_one_line_at_tiktok_size(self):
        """The headline symptom: "Hello world" came out as "Hello" over "world" while the tool
        reported split 0 and no wrap at all -- the fitter measured the horizontal safe width and
        libass was handed a 240 px column. With --max-lines 1 the fit is asked for a single line;
        it is a single line in the ASS text AND a single band of lit rows in libass's raster."""
        cues = OUT / "cues_two_words.txt"
        cues.write_text("0:00-0:03 Hello world\n", encoding="utf-8")
        ass = OUT / "cap_two_words.ass"
        data = json.loads(script("caption.py", self._vertical(), "--text", cues,
                                 "--platform", "tiktok", "--fit-size", "on", "--max-lines", "1",
                                 "--animate", "pop", "--karaoke", "--font", "DejaVu Sans",
                                 "--write-ass", ass, "-o", OUT / "cap_two_words.mp4",
                                 "--json").stdout)
        self.assertEqual(data["caption"]["split"], 0)
        dialogue = [l for l in ass.read_text(encoding="utf-8-sig").splitlines()
                    if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogue), 1)
        self.assertNotIn("\\N", dialogue[0].split(",,0,0,0,,", 1)[1])
        bands = _ass_ink_rows(ass, 1080, 1920)
        self.assertEqual(len(bands), 1, "the cue was drawn on %d lines: %s" % (len(bands), bands))

    def test_caption_eval_cues_fit_two_lines_in_the_raster_too(self):
        """The eval-17/18 cw1 cues on the TikTok template: <= 2 lines per cue in the ASS AND
        <= 2 bands of lit rows per cue once libass has applied the Style margins."""
        cues = self._fit_cues()
        for index, (start, text) in enumerate((("0:00", "A third line the tool times for me"),
                                               ("0:00", "Segunda l\u00ednea de subt\u00edtulos"))):
            one = OUT / ("cues_band_%d.txt" % index)
            one.write_text("%s-0:03 %s\n" % (start, text), encoding="utf-8")
            ass = OUT / ("cap_band_%d.ass" % index)
            script("caption.py", self._vertical(), "--text", one, "--platform", "tiktok",
                   "--max-lines", "2", "--animate", "fade", "--font", "DejaVu Sans",
                   "--write-ass", ass, "-o", OUT / ("cap_band_%d.mp4" % index))
            dialogue = [l for l in ass.read_text(encoding="utf-8-sig").splitlines()
                        if l.startswith("Dialogue:")]
            self.assertEqual(len(dialogue), 1, "the cue was split")
            self.assertLessEqual(dialogue[0].count("\\N"), 1)
            bands = _ass_ink_rows(ass, 1080, 1920)
            self.assertLessEqual(len(bands), 2, "%r drew %d lines" % (text, len(bands)))
            # the agreement itself: libass draws exactly the lines the ASS text asks for
            self.assertEqual(len(bands), dialogue[0].count("\\N") + 1)
        self.assertTrue(Path(cues).exists())

    def test_caption_says_when_the_text_is_unchanged(self):
        """1.17.1: the report sentence "the text is yours, unchanged" should not be a judgement
        the agent has to make -- the run states it (eval 18 cs2/cs3, where one run rewrote the
        user's cue text)."""
        vert, cues = self._vertical(), self._fit_cues()
        proc = script("caption.py", vert, "--text", cues, "--platform", "tiktok", "--max-lines", "2",
                      "--font", "DejaVu Sans", "-o", OUT / "cap_unchanged.mp4", "--json")
        data = json.loads(proc.stdout)["caption"]
        self.assertEqual(data["split"], 0)
        self.assertTrue(data["text_unchanged"])
        self.assertIn("caption text unchanged", proc.stderr)

    def test_caption_text_is_not_unchanged_when_a_cue_was_split(self):
        """Review 17 finding 5: a cue the layout chopped into two consecutive cues is not the
        text that was handed in -- and it is the exact defect 1.17.1 exists to fix, so the tool
        must not claim honesty on precisely the runs that are still wrong."""
        vert, cues = self._vertical(), self._fit_cues()
        proc = script("caption.py", vert, "--text", cues, "--platform", "tiktok", "--max-lines", "2",
                      "--size", "24", "--fit-size", "off", "--font", "DejaVu Sans",
                      "-o", OUT / "cap_split.mp4", "--json")
        cap = json.loads(proc.stdout)["caption"]
        self.assertGreater(cap["split"], 0, "this run is the one that splits a cue")
        self.assertFalse(cap["text_unchanged"])
        self.assertNotIn("caption text unchanged", proc.stderr)

    def test_caption_text_is_not_unchanged_when_emoji_none_strips_glyphs(self):
        """--emoji none str.replace()s the clusters out of the drawn text: the viewer reads
        something other than the cue that was handed in (review 17 finding 5)."""
        cues = OUT / "cues_emoji_strip.txt"
        cues.write_text("0:00-0:03 Ship it \U0001F680\n", encoding="utf-8")
        proc = script("caption.py", self._vertical(), "--text", cues, "--platform", "tiktok",
                      "--emoji", "none", "--font", "DejaVu Sans",
                      "-o", OUT / "cap_emoji_none.mp4", "--json")
        cap = json.loads(proc.stdout)["caption"]
        self.assertFalse(cap["text_unchanged"])
        self.assertNotIn("caption text unchanged", proc.stderr)

    def test_caption_fit_size_auto_leaves_an_explicit_size_alone(self):
        vert, cues = self._vertical(), self._fit_cues()
        data = json.loads(script("caption.py", vert, "--text", cues, "--platform", "tiktok",
                                 "--size", "30", "--max-lines", "2",
                                 "-o", OUT / "cap_fit_explicit.mp4", "--json").stdout)
        self.assertEqual(data["caption"]["size_used"], 30)
        self.assertEqual(data["caption"]["size_requested"], 30)

    def test_caption_plan_before_the_input_exists_uses_the_platform_frame(self):
        """A plan that names a different FontSize from the run that executes it is not a plan.
        With --platform there is a real frame to fit against; without one there is nothing, and
        size_used says null rather than presenting the requested size as the fitted one."""
        cues = self._fit_cues()
        missing = OUT / "not_yet_recorded.mp4"
        if missing.exists():
            missing.unlink()
        planned = json.loads(script("caption.py", missing, "--text", cues, "--platform", "tiktok",
                                    "--dry-run", "-o", OUT / "plan_fit.mp4", "--json").stdout)
        real = json.loads(script("caption.py", self._vertical(), "--text", cues,
                                 "--platform", "tiktok", "--dry-run",
                                 "-o", OUT / "plan_fit2.mp4", "--json").stdout)
        self.assertEqual(planned["caption"]["size_used"], real["caption"]["size_used"])
        self.assertLess(planned["caption"]["size_used"], planned["caption"]["size_requested"])
        self.assertEqual(planned["caption"]["size_source"], "platform-frame")
        burn = next(c for c in planned["commands"] if "FontSize" in c)
        self.assertIn(f"FontSize={planned['caption']['size_used']}", burn)

        # no platform and no input: nothing to measure against, so nothing is claimed
        blind = json.loads(script("caption.py", missing, "--text", cues, "--dry-run",
                                  "-o", OUT / "plan_fit3.mp4", "--json").stdout)
        self.assertIsNone(blind["caption"]["size_used"])
        self.assertEqual(blind["caption"]["size_requested"], 24)

    def test_caption_min_size_above_size_is_an_input_refusal(self):
        vert, cues = self._vertical(), self._fit_cues()
        out = OUT / "cap_fit_refuse.mp4"
        if out.exists():
            out.unlink()
        r = script("caption.py", vert, "--text", cues, "--size", "24", "--min-size", "30",
                   "-o", out, "--json", expect_fail=True)
        data = json.loads(r.stdout)
        self.assertEqual(data["error"]["kind"], "input")
        self.assertIn("--min-size", data["error"]["message"])
        self.assertFalse(out.exists())

    def test_caption_mux_is_unaffected_by_the_fitter(self):
        """Soft subtitles carry no size, so --mode mux writes the SRT 1.16 wrote."""
        vert, cues = self._vertical(), self._fit_cues()
        a, b = OUT / "cap_mux_auto.mkv", OUT / "cap_mux_off.mkv"
        script("caption.py", vert, "--text", cues, "--mode", "mux", "--platform", "tiktok",
               "--write-srt", OUT / "cap_mux_auto.srt", "-o", a)
        script("caption.py", vert, "--text", cues, "--mode", "mux", "--platform", "tiktok",
               "--fit-size", "off", "--write-srt", OUT / "cap_mux_off.srt", "-o", b)
        self.assertEqual((OUT / "cap_mux_auto.srt").read_bytes(),
                         (OUT / "cap_mux_off.srt").read_bytes())

class ScriptFontTests(unittest.TestCase):
    """1.12: which script text is written in, and a font file that actually covers it."""

    def test_detect_script_reads_the_characters_not_the_locale(self):
        cases = {
            "こんにちは世界": "ja",          # kana + han -> Japanese
            "カタカナ": "ja",
            "你好世界": "zh",                # han alone -> Chinese
            "안녕하세요": "ko",
            "ㅎㅏㄴ": "ko",                  # jamo, not syllables
            "مرحبا بالعالم": "ar",
            "שלום עולם": "he",
            "नमस्ते दुनिया": "hi",
            "สวัสดีชาวโลก": "th",
            "Привет мир": "ru",
            "Γειά σου κόσμε": "el",
            "Hello world": "latin",
            "": "latin",
            "1080p 30fps": "latin",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_script(text), expected)

    def test_detect_script_mixed_text_goes_by_character_count(self):
        self.assertEqual(detect_script("Episode 12 — 日本語のテスト"), "ja")
        self.assertEqual(detect_script("Part 2: 第二部分的内容说明"), "zh")
        # kana anywhere makes the whole string Japanese, however few
        self.assertEqual(detect_script("漢字漢字漢字の"), "ja")
        # the non-Latin script with the most characters wins
        self.assertEqual(detect_script("Привет 你好世界大家好"), "zh")

    def test_lang_hint_only_breaks_the_han_only_tie(self):
        """Han with no kana is Chinese by default; only the caller knows when it is Japanese or
        Korean hanja. The hint never overrides what the characters already prove."""
        self.assertEqual(detect_script("漢字表記"), "zh")
        self.assertEqual(detect_script("漢字表記", lang="ja"), "ja")
        self.assertEqual(detect_script("漢字表記", lang="ko"), "ko")
        self.assertEqual(detect_script("漢字表記", lang="ja-JP"), "ja")
        self.assertEqual(detect_script("こんにちは", lang="zh"), "ja", "kana is not ambiguous -- the hint must not win")
        self.assertEqual(detect_script("안녕하세요", lang="ja"), "ko")

    @unittest.skipIf(_no_fontconfig(), "no fc-list on this machine: fonts cannot be resolved by script here")
    def test_font_for_script_finds_a_real_file_for_every_script(self):
        for script in ("ja", "zh", "ko", "ar", "he", "hi", "th", "ru", "el"):
            with self.subTest(script=script):
                path = font_for_script(script)
                if path is None:
                    self.skipTest(f"this machine has no font covering {script}")
                self.assertTrue(os.path.exists(path), path)
                family = font_family_for_script(script)
                self.assertTrue(family)
                # "Unifont Sample" draws the code point in a box instead of the glyph -- the exact
                # unreadable result this feature exists to avoid. It is only ever acceptable when
                # nothing else on the machine covers the script at all.
                if any(f for f in _families_for(script) if "unifont" not in f.lower()):
                    self.assertNotIn("unifont", family.lower(),
                                      f"{script}: picked {family} while a real font is installed")

    @unittest.skipIf(_no_fontconfig(), "no fc-list on this machine")
    def test_font_for_script_is_cached_and_stable(self):
        self.assertEqual(font_for_script("ja"), font_for_script("ja"))


class EmojiTests(unittest.TestCase):
    """1.15: emoji are detected as clusters, measured at a full em, reserved in the ASS and
    composited as PNGs -- and every degraded path says so instead of lying."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "emoji_src.mp4"
        if not cls.src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
               "-t", "4", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(cls.src))
        cls.cues = OUT / "cues_emoji.txt"
        cls.cues.write_text("0:00-0:02 Hello \U0001F389 world\n0:02-0:04 Nice \U0001F44D job\n",
                            encoding="utf-8")

    def test_emoji_cluster_detection_keeps_zwj_and_skin_tone_sequences_together(self):
        from _common import emoji_clusters, emoji_codepoint_name, has_emoji
        text = "\u3084\u3063\u305f \U0001F389 \U0001F469\u200d\U0001F4BB \U0001F1EF\U0001F1F5 \U0001F44D\U0001F3FD 1\ufe0f\u20e3"
        names = [emoji_codepoint_name(cl) for _i, cl in emoji_clusters(text)]
        self.assertEqual(names, ["1f389", "1f469-200d-1f4bb", "1f1ef-1f1f5", "1f44d-1f3fd", "31-fe0f-20e3"])
        self.assertTrue(has_emoji(text))
        self.assertFalse(has_emoji("plain ascii"))

    def test_emoji_is_orthogonal_to_the_writing_system(self):
        """A cue can be Japanese AND emoji: adding an "emoji" script would corrupt the font
        resolution for the rest of the line."""
        self.assertEqual(detect_script("\u3084\u3063\u305f \U0001F389"), "ja")
        self.assertEqual(detect_script("Hello \U0001F389"), "latin")

    def test_caption_wrap_counts_an_emoji_as_a_full_width_atom(self):
        from _common import text_width_em
        import importlib, sys as _s
        _s.path.insert(0, str(SCRIPTS))
        caption = importlib.import_module("caption")
        self.assertAlmostEqual(text_width_em("\U0001F389"), 1.0, places=6)
        self.assertAlmostEqual(text_width_em("\U0001F389", 1.5), 1.5, places=6)
        # a wrap never breaks inside a cluster
        lines = caption.wrap_text("aaa \U0001F469\u200d\U0001F4BB bbb", 3.0)
        self.assertIn("\U0001F469\u200d\U0001F4BB", lines)
        for line in lines:
            self.assertNotEqual(line, "\U0001F469")

    def _plan(self, *extra):
        out = OUT / "emoji_out.mp4"
        proc = script("caption.py", self.src, "--text", self.cues, "-o", out,
                      "--dry-run", "--json", *extra)
        return json.loads(proc.stdout)

    def test_caption_emoji_overlay_places_one_png_per_cluster_inside_the_safe_area(self):
        doc = self._plan("--emoji-assets", _emoji_assets())
        self.assertEqual(doc["emoji"]["mode"], "png")
        self.assertEqual(doc["emoji"]["overlays"], 2)
        graph = [c for c in doc["commands"] if "overlay=" in c][-1]
        overlays = re.findall(r"overlay=x=(\d+):y=(\d+):enable=\D*?between\(t,([\d.]+),([\d.]+)\)", graph)
        self.assertEqual(len(overlays), 2, graph)
        for x, y, start, end in overlays:
            x, y = int(x), int(y)
            self.assertTrue(0.05 * 640 <= x <= 0.95 * 640, f"x={x} outside the safe area")
            self.assertTrue(0.05 * 360 <= y <= 0.95 * 360, f"y={y} outside the safe area")
            self.assertLess(float(start), float(end))
        self.assertEqual([(o[2], o[3]) for o in overlays], [("0.000", "2.000"), ("2.000", "4.000")])

    def test_caption_emoji_placeholder_reserves_the_gap_in_the_generated_ass(self):
        out = OUT / "emoji_ass.mp4"
        script("caption.py", self.src, "--text", self.cues, "-o", out,
               "--emoji-assets", _emoji_assets())
        ass = (OUT / "emoji_ass.ass").read_text(encoding="utf-8-sig")
        dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertTrue(dialogue)
        for line in dialogue:
            self.assertIn("\\alpha&HFF&", line)
            self.assertNotIn("\U0001F389", line, "the raw code point must not reach the drawn text")
            self.assertNotIn("\U0001F44D", line)

    def test_the_emoji_placeholder_reserves_exactly_the_box_it_asks_for(self):
        """The reservation is measured, not assumed: U+2588 is 0.66-0.83 em depending on the face,
        so the gap is reserved with alpha-hidden \\fsp spacing, which is exact in every face."""
        from _ass_overlay import emoji_placeholder
        families = ["FreeSans", "DejaVu Sans", "IPAPGothic", "WenQuanYi Zen Hei", "Loma"]
        tested = 0
        for family in families:
            if not _family_installed(family):
                continue
            tested += 1
            base = _ass_advance(family, "|")
            with_gap = _ass_advance(family, emoji_placeholder(60) + "|")
            if base is None or with_gap is None:
                self.skipTest("libass render probe produced no ink here")
            self.assertAlmostEqual(with_gap - base, 60, delta=2,
                                   msg=f"{family}: reserved {with_gap - base}px, asked for 60")
        if not tested:
            self.skipTest("none of the measured families is installed here")

    def test_caption_emoji_without_assets_is_a_warning_not_a_failure(self):
        from _common import emoji_support
        support = emoji_support(probe=True)
        if support["mode"] not in ("mono", "none"):
            self.skipTest("this machine has a colour emoji path; the degraded branch cannot be exercised")
        out = OUT / "emoji_mono.mp4"
        proc = script("caption.py", self.src, "--text", self.cues, "-o", out, "--json")
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["emoji"]["mode"], support["mode"])
        if support["mode"] == "mono":
            self.assertIn("monochrome", proc.stderr + proc.stdout)
            self.assertTrue(any("monochrome" in n for n in doc.get("notes", [])), doc.get("notes"))

    def test_emoji_assets_directory_that_does_not_exist_is_a_failed_job(self):
        out = OUT / "emoji_missing.mp4"
        proc = script("caption.py", self.src, "--text", self.cues, "-o", out, "--json",
                      "--emoji-assets", str(OUT / "no_such_emoji_dir"), expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("twemoji", doc["error"]["message"].lower())
        self.assertIn("no network", doc["error"]["message"].lower())

    def test_the_skill_never_fetches_an_emoji_asset(self):
        """Mirror of the existing no-network assertions: nothing on the emoji path may import a
        network module, and no tool offers a download flag for one."""
        import _common
        # _common is a package: every module in it, not just the facade.
        source = "\n".join(p.read_text(encoding="utf-8")
                           for p in sorted(Path(_common.__file__).parent.glob("*.py")))
        for banned in ("urllib", "http.client", "requests", "socket."):
            self.assertNotIn(banned, source, f"{banned} is reachable from the emoji path")
        for tool in ("caption.py", "graphics.py", "overlay.py"):
            helptext = script(tool, "--help").stdout.lower()
            self.assertNotIn("--emoji-download", helptext)
            self.assertNotIn("download", helptext.split("--emoji")[-1][:400])

    def test_caption_emoji_overlay_is_capped(self):
        many = OUT / "cues_many_emoji.txt"
        many.write_text("".join("0:0%d-0:0%d %s\n" % (i, i + 1, "\U0001F389" * 9)
                                for i in range(0, 8)), encoding="utf-8")
        out = OUT / "emoji_capped.mp4"
        proc = script("caption.py", self.src, "--text", many, "-o", out, "--json", "--dry-run",
                      "--emoji-assets", _emoji_assets(), "--emoji-max", "4", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--emoji-max", doc["error"]["message"])

    def test_graphics_all_emoji_title_without_a_glyph_is_a_failed_job(self):
        out = OUT / "emoji_title.mp4"
        proc = script("graphics.py", self.src, "--template", "title", "--title", "\U0001F389",
                      "--start", "0", "--end", "2", "--emoji", "none", "-o", out, "--json",
                      expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("blank", doc["error"]["message"])

    def test_overlay_text_refuses_the_png_emoji_route_and_names_the_tools_that_have_one(self):
        out = OUT / "emoji_overlay.mp4"
        proc = script("overlay.py", self.src, "--text", "Ship it \U0001F680", "--emoji", "png",
                      "-o", out, "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("caption.py", doc["error"]["message"])
        self.assertIn("graphics.py", doc["error"]["message"])


    # ---------------------------------------------------------------- 1.15.0 fix pass
    def test_emoji_cluster_never_starts_at_a_joiner_a_selector_or_a_plain_letter(self):
        """U+200D ZWJ and U+200C ZWNJ are ordinary Indic/Persian orthography, not emoji: क्‍ष is
        ka + virama + ZWJ + ssa. Treating a joiner (or a VS16, or a skin-tone modifier) as a
        cluster TAIL that glues itself to whatever stands before it turned a Hindi conjunct into
        "an emoji" -- reported as such, warned about as monochrome, and on the PNG route replaced
        by an invisible gap, i.e. a different word. A cluster may only START at an emoji base."""
        from _common import emoji_clusters, emoji_codepoint_name, has_emoji

        def names(text):
            return [emoji_codepoint_name(cl) for _i, cl in emoji_clusters(text)]

        self.assertEqual(names("\u0915\u094d\u200d\u0937"), [], "a Hindi conjunct is not an emoji")
        self.assertFalse(has_emoji("\u0905\u200c\u092c"), "a ZWNJ is not an emoji either")
        self.assertEqual(names("abc\u200ddef"), [])
        self.assertEqual(names("A\ufe0f"), [], "a VS16 after a letter does not make it an emoji")
        self.assertEqual(names("\u00a9 \u2122 0123456789"), [], "(c), (tm) and digits are not emoji")
        # ... and every real cluster still survives whole
        self.assertEqual(names("\U0001F468\u200d\U0001F469\u200d\U0001F467"),
                         ["1f468-200d-1f469-200d-1f467"])
        self.assertEqual(names("\U0001F3F3\ufe0f\u200d\U0001F308"), ["1f3f3-fe0f-200d-1f308"])
        self.assertEqual(names("1\ufe0f\u20e3"), ["31-fe0f-20e3"])
        self.assertEqual(names("\U0001F1EF\U0001F1F5"), ["1f1ef-1f1f5"])

    def test_vs15_asks_for_the_character_not_the_picture(self):
        """U+FE0E is the TEXT presentation selector: the author explicitly asked for the glyph,
        so the cluster must not be routed to the PNG overlay."""
        from _common import emoji_clusters
        self.assertEqual(emoji_clusters("\u2764\ufe0e"), [], "VS15 means: draw the character")
        self.assertTrue(emoji_clusters("\u2764\ufe0f"), "VS16 still means: draw the emoji")

    def test_caption_emoji_png_is_on_screen_for_the_whole_cue_and_only_that_cue(self):
        """The one assertion the 1.15.0 emoji tests were all missing: a rendered frame from the
        MIDDLE of the cue. A PNG input is a single frame at pts 0, so `eof_action=pass` (which
        switches off overlay's "hold the last frame of the secondary input") composited every
        emoji on frame 0 and nowhere else -- the demo GIF shipped an empty reserved gap."""
        cues = OUT / "cues_one_emoji.txt"
        cues.write_text("0:00-0:02 Hello \U0001F389 world\n", encoding="utf-8")
        out = OUT / "emoji_midcue.mp4"
        doc = json.loads(script("caption.py", self.src, "--text", cues, "-o", out, "--json",
                                "--dry-run", "--emoji-assets", _emoji_assets()).stdout)
        graph = [c for c in doc["commands"] if "overlay=" in c][-1]
        m = re.search(r"overlay=x=(\d+):y=(\d+)", graph)
        self.assertTrue(m, graph)
        x, y = int(m.group(1)) + 4, int(m.group(2)) + 4
        script("caption.py", self.src, "--text", cues, "-o", out,
               "--emoji-assets", _emoji_assets())
        orange = (255, 165, 0)   # _emoji_assets() draws 1f389 as a plain orange square

        def near(pix):
            return sum(abs(a - b) for a, b in zip(pix, orange)) < 60

        self.assertTrue(near(_pixel_at(out, 1.0, x, y)),
                        "the emoji is gone by the middle of its own cue: %r" % (_pixel_at(out, 1.0, x, y),))
        self.assertTrue(near(_pixel_at(out, 1.8, x, y)), "the emoji left before its cue ended")
        self.assertFalse(near(_pixel_at(out, 3.0, x, y)),
                         "the emoji is still on screen a second after its cue ended")

    def test_caption_rtl_emoji_is_placed_by_the_rendered_order_not_the_logical_prefix(self):
        """libass lays an RTL line out right-to-left, so the LOGICAL prefix of a cluster occupies
        the RIGHT end of the rendered line. Measuring from the left put the PNG on top of the
        Arabic text, a prefix-width away from the gap libass actually reserved."""
        from _common import script_font_status
        cues = OUT / "cues_rtl.txt"
        # the emoji is FIRST in logical order, so it must be drawn at the RIGHT end of the line
        cues.write_text("0:00-0:02 \U0001F389 \u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645\n",
                        encoding="utf-8")
        out = OUT / "emoji_rtl.mp4"
        doc = json.loads(script("caption.py", self.src, "--text", cues, "-o", out, "--json",
                                "--dry-run", "--emoji-assets", _emoji_assets()).stdout)
        graph = [c for c in doc["commands"] if "overlay=" in c][-1]
        m = re.search(r"overlay=x=(\d+):y=(\d+)", graph)
        self.assertTrue(m, graph)
        x, y = int(m.group(1)), int(m.group(2))
        self.assertGreater(x, 320, "a logically-first cluster in an RTL line belongs on the right "
                                   "half of a centred line, not the left: x=%d" % x)
        if script_font_status("ar") != "available":
            self.skipTest("no font on this machine covers Arabic; tests never install fonts")
        # and the box must land where libass drew nothing -- the reserved gap, not over a glyph
        script("caption.py", self.src, "--text", cues, "-o", out, "--emoji-assets", _emoji_assets())
        box = doc["emoji"].get("box_px") or 24
        ink = _ass_ink_columns(OUT / "emoji_rtl.ass", 640, 360)
        if not ink:
            # the probe renders the sidecar with a bare `ass=` filter; without fontconfig (Windows,
            # a static build) libass may resolve no face for Arabic and draw nothing, which says
            # nothing about placement -- the caption itself goes through fontsdir handling
            self.skipTest("the ASS probe drew no ink on this build (libass found no Arabic face)")
        covered = [c for c in range(x + 2, x + box - 2) if c in ink]
        self.assertEqual(covered, [], "the PNG would be composited over drawn text at columns %r" % covered)

    def test_caption_emoji_max_zero_means_no_overlays_at_all(self):
        """`int(args.emoji_max or 60)` swallowed the one value a caller would use to say 'none'."""
        out = OUT / "emoji_max0.mp4"
        doc = json.loads(script("caption.py", self.src, "--text", self.cues, "-o", out, "--json",
                                "--dry-run", "--emoji-assets", _emoji_assets(), "--emoji-max", "0",
                                expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("limit 0", doc["error"]["message"])

    def test_caption_animate_fades_the_emoji_with_the_text(self):
        """--animate fade gives the TEXT a \\fad; the PNG used to pop in against a fading line."""
        cues = OUT / "cues_fade_emoji.txt"
        cues.write_text("0:00-0:02 Hello \U0001F389 world\n", encoding="utf-8")
        out = OUT / "emoji_fade.mp4"
        doc = json.loads(script("caption.py", self.src, "--text", cues, "-o", out, "--json",
                                "--dry-run", "--animate", "fade",
                                "--emoji-assets", _emoji_assets()).stdout)
        graph = [c for c in doc["commands"] if "overlay=" in c][-1]
        self.assertIn("fade=t=in", graph)
        self.assertIn("fade=t=out", graph)
        self.assertIn("alpha=1", graph)
        m = re.search(r"overlay=x=(\d+):y=(\d+)", graph)
        x, y = int(m.group(1)) + 4, int(m.group(2)) + 4
        script("caption.py", self.src, "--text", cues, "-o", out, "--animate", "fade",
               "--emoji-assets", _emoji_assets())
        orange = (255, 165, 0)

        def dist(t):
            return sum(abs(a - b) for a, b in zip(_pixel_at(out, t, x, y), orange))

        self.assertLess(dist(1.0), 60, "the emoji never reached full opacity")
        self.assertGreater(dist(0.02), dist(1.0), "the emoji did not fade in with the text")

    def test_graphics_drawtext_route_never_reports_monochrome_emoji(self):
        """drawtext loads ONE font file and has no fallback chain, so "whatever glyph the text
        font has" is an empty box. Reporting `mode: mono` from that route is a claim the frame
        does not keep: the run must route to libass (which does have a fallback chain) or strip."""
        out = OUT / "emoji_gfx_mono.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "title",
                                "--title", "Ship it \U0001F389 now", "--start", "0", "--end", "2",
                                "-o", out, "--json", "--dry-run").stdout)
        if doc.get("emoji", {}).get("mode") == "mono":
            self.assertEqual(doc["text_renderer"], "ass",
                             "mode mono on the drawtext route draws tofu, not a glyph")
        pinned = json.loads(script("graphics.py", self.src, "--template", "title",
                                   "--title", "Ship it \U0001F389 now", "--start", "0", "--end", "2",
                                   "--text-render", "drawtext", "-o", out, "--json", "--dry-run").stdout)
        self.assertEqual(pinned["text_renderer"], "drawtext")
        self.assertNotEqual(pinned.get("emoji", {}).get("mode"), "mono",
                            "a pinned drawtext run must not claim monochrome either")

    def test_graphics_emoji_none_actually_strips_the_cluster(self):
        """`--emoji none` only guarded the all-emoji case: the cluster stayed in the drawn text
        and drawtext drew the same empty box it would have drawn anyway."""
        with_emoji = OUT / "emoji_gfx_none.mp4"
        without = OUT / "emoji_gfx_plain.mp4"
        script("graphics.py", self.src, "--template", "title", "--title", "Ship it \U0001F389 now",
               "--start", "0", "--end", "3", "--emoji", "none", "-o", with_emoji)
        script("graphics.py", self.src, "--template", "title", "--title", "Ship it now",
               "--start", "0", "--end", "3", "-o", without)
        self.assertAlmostEqual(_frame_ink(with_emoji), _frame_ink(without),
                               delta=max(1, _frame_ink(without) // 500),
                               msg="--emoji none must draw the same frame as text with no emoji in it")

    def test_drawn_text_temp_files_are_private_and_never_outlive_the_run(self):
        """1.15.0 wrote every drawn label into a world-shared, predictable, never-cleaned
        /tmp/ffmpeg-skill-text -- including under --dry-run and on the ASS route, which never
        reads them."""
        import glob
        import tempfile as _tf
        out = OUT / "textfile_life.mp4"
        doc = json.loads(script("overlay.py", self.src, "--text", "Label", "-o", out,
                                "--json", "--dry-run").stdout)
        m = re.search(r"textfile=(\S+?\.txt)", " ".join(doc["commands"]).replace("\\", ""))
        self.assertTrue(m, "the plan must still name the path it would use")
        self.assertFalse(os.path.exists(m.group(1)), "a dry run wrote a file")
        self.assertFalse(os.path.isdir(os.path.dirname(m.group(1))), "a dry run created a directory")
        self.assertEqual(glob.glob(os.path.join(_tf.gettempdir(), "ffmpeg-skill-text-*")), [],
                         "a drawn-text directory was left behind")
        self.assertFalse(os.path.exists(os.path.join(_tf.gettempdir(), "ffmpeg-skill-text")),
                         "the shared world-writable directory must not be created at all")

    def test_the_ass_route_writes_no_drawtext_textfile(self):
        from _common import script_font_status
        if script_font_status("hi") != "available":
            self.skipTest("no font on this machine covers Devanagari; tests never install fonts")
        import glob
        import tempfile as _tf
        out = OUT / "textfile_ass_route.mp4"
        script("graphics.py", self.src, "--template", "title", "--title", "\u0915\u093f\u0924\u093e\u092c",
               "--start", "0", "--end", "2", "-o", out)
        self.assertEqual(glob.glob(os.path.join(_tf.gettempdir(), "ffmpeg-skill-text-*")), [],
                         "the ASS route wrote (and kept) a drawtext textfile it never reads")

    def test_the_ass_route_keeps_braces_and_backslashes(self):
        """The same title through drawtext and through libass must produce the same characters:
        1.15.0 deleted `{`, `}` and `\\` on the ASS route while drawtext kept them."""
        from _ass_overlay import ass_escape
        self.assertEqual(ass_escape("A {b} c \\ d"), "A \\{b\\} c \\ d")
        out = OUT / "ass_braces.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "title",
                                "--title", "A {b} c \\ d", "--start", "0", "--end", "2",
                                "--text-render", "ass", "-o", out, "--json").stdout)
        ass = Path(doc["ass"]).read_text(encoding="utf-8-sig")
        dialogue = next(l for l in ass.splitlines() if l.startswith("Dialogue:"))
        self.assertIn("A \\{b\\} c \\ d", dialogue)


class LookInkTests(unittest.TestCase):
    """look.py --ink: a pixel-only non-background measurement per written PNG, so the agent can
    check "is there ink where the caption should be" without eyeballing every frame."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.busy = OUT / "ink_busy.mp4"
        if not cls.busy.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=320x240:rate=10", "-t", "3", "-pix_fmt", "yuv420p", cls.busy)
        cls.blank = OUT / "ink_blank.mp4"
        if not cls.blank.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=c=black:size=320x240:rate=10", "-t", "3", "-pix_fmt", "yuv420p", cls.blank)

    def test_ink_reports_a_lit_frame_via_at(self):
        out = OUT / "ink_at.png"
        proc = script("look.py", self.busy, "--at", "1", "--no-timecode", "--ink", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        frame = doc["ink"]["frames"][0]
        self.assertTrue(frame["has_ink"])
        self.assertIsNotNone(frame["bbox"])
        self.assertGreater(frame["ink_fraction"], 0.0)
        self.assertTrue(frame["row_bands"])

    def test_ink_reports_no_ink_on_a_blank_frame(self):
        out = OUT / "ink_blank_at.png"
        proc = script("look.py", self.blank, "--at", "1", "--no-timecode", "--ink", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        frame = doc["ink"]["frames"][0]
        self.assertFalse(frame["has_ink"])
        self.assertIsNone(frame["bbox"])
        self.assertEqual(frame["ink_fraction"], 0.0)
        self.assertEqual(frame["row_bands"], [])

    def test_ink_is_omitted_without_the_flag(self):
        out = OUT / "ink_off.png"
        proc = script("look.py", self.busy, "--at", "1", "--no-timecode", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        self.assertNotIn("ink", doc)

    def test_ink_measures_each_tile_of_a_contact_sheet(self):
        out = OUT / "ink_sheet.png"
        proc = script("look.py", self.busy, "--tiles", "2x2", "--ink", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        tiles = doc["ink"]["tiles"]
        self.assertEqual(len(tiles), 4)
        for tile in tiles:
            self.assertTrue(tile["has_ink"])

    def test_ink_measures_both_sides_of_a_compare(self):
        out = OUT / "ink_compare.png"
        proc = script("look.py", self.busy, "--compare", self.blank, "--at", "1", "--ink", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        frames = doc["ink"]["frames"]
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0]["has_ink"])  # the hstacked image: busy half lights it up

    def test_compare_with_repeated_at_and_o_writes_distinct_files(self):
        """-o given alongside --compare --at T1 --at T2 must not collapse onto one file: each
        timestamp needs its own comparison image, or ink.frames (and any other per-frame
        measurement) silently describes the same picture twice."""
        out = OUT / "ink_compare_multi.png"
        proc = script("look.py", self.busy, "--compare", self.blank, "--at", "1", "--at", "2",
                     "--ink", "--json", "-o", out)
        doc = json.loads(proc.stdout)
        outputs = doc["outputs"]
        self.assertEqual(len(outputs), 2)
        self.assertNotEqual(outputs[0], outputs[1])
        for o in outputs:
            self.assertTrue(Path(o).exists(), o)
        frames = doc["ink"]["frames"]
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0]["has_ink"])
        self.assertTrue(frames[1]["has_ink"])

    def test_compare_with_the_same_at_value_twice_still_writes_two_files(self):
        """The occurrence index, not just the timestamp, disambiguates the filename: two
        identical --at values (or two that would round to the same millisecond) must not
        collapse onto one file either."""
        out = OUT / "ink_compare_dup.png"
        proc = script("look.py", self.busy, "--compare", self.blank, "--at", "1", "--at", "1",
                     "--json", "-o", out)
        doc = json.loads(proc.stdout)
        outputs = doc["outputs"]
        self.assertEqual(len(outputs), 2)
        self.assertNotEqual(outputs[0], outputs[1])
        for o in outputs:
            self.assertTrue(Path(o).exists(), o)


class GraphicsSliceOverlongTests(unittest.TestCase):
    """graphics.py's own `wrapped()` helper (used by lower-third, title, sticker, hook and meme
    labels) now turns on the same `slice_overlong` escape hatch caption.py's burn path turned on
    in 1.18.4, so a single unbreakable overlong atom drawn through a template no longer renders
    past the frame's safe width."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "gfx_src.mp4"
        if not cls.src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=440",
               "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-pix_fmt", "yuv420p", "-c:a", "aac", cls.src)

    def _dialogue_lines(self, doc):
        ass = Path(doc["ass"]).read_text(encoding="utf-8-sig")
        dialogue = next(l for l in ass.splitlines() if l.startswith("Dialogue:"))
        text = dialogue.split(",", 9)[-1]
        text = re.sub(r"\{[^}]*\}", "", text)  # strip the leading {\an5\pos(...)} override block
        return text.split("\\N")

    def _skip_without(self, script_code):
        from _common import script_font_status
        if script_font_status(script_code) != "available":
            raise unittest.SkipTest("no font on this machine covers %r; tests never install fonts"
                                    % script_code)

    def test_overlong_word_no_longer_clips_a_hook_title(self):
        """The same 32-letter Spanish word from caption's cs2 fixture, with no break point, drawn
        as a --template hook --title at a scale where it used to be kept whole and clip past the
        frame's safe width. Every produced line must now measure within the column."""
        from _common import text_width_em
        word = "Supercalifragilísticoespialidoso"
        out = OUT / "gfx_slice_hook.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "hook", "--title", word,
                                "--scale", "2", "--text-render", "ass", "-o", out, "--json").stdout)
        base = min(640, 360) * 2.0
        h1 = int(base * 0.085)
        max_em = (640 * 0.9) / h1  # SAFE_WIDTH_FRACTION default
        lines = self._dialogue_lines(doc)
        self.assertGreater(len(lines), 1, "the word should have been sliced into more than one line")
        for line in lines:
            self.assertLessEqual(text_width_em(line), max_em + 1e-6, lines)
        # no character was added, dropped or reordered
        self.assertEqual("".join(lines), word)
        self.assertEqual(doc.get("broken_inside_word"), 1, doc)

    def test_fitting_thai_phrase_stays_unbroken_through_graphics_wrapped(self):
        """A short-enough-to-fit Thai phrase with no natural break point must come back as one
        unbroken line -- the escape hatch is only reachable when an atom does NOT fit alone, and
        this must hold through graphics.py's `wrapped()` specifically, not just wrap.py itself."""
        self._skip_without("th")
        thai = "สวัสดีชาวโลก"
        out = OUT / "gfx_slice_thai.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "hook", "--title", thai,
                                "--text-render", "ass", "-o", out, "--json").stdout)
        lines = self._dialogue_lines(doc)
        self.assertEqual(lines, [thai], lines)
        self.assertNotIn("broken_inside_word", doc)

    def test_fitting_katakana_run_stays_unbroken_through_graphics_wrapped(self):
        """A short-enough-to-fit katakana run with no natural break point must also come back as
        one unbroken atom, unchanged, through graphics.py's `wrapped()`."""
        self._skip_without("ja")
        kata = "コンピューター"
        out = OUT / "gfx_slice_kata.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "hook", "--title", kata,
                                "--text-render", "ass", "-o", out, "--json").stdout)
        lines = self._dialogue_lines(doc)
        self.assertEqual(lines, [kata], lines)
        self.assertNotIn("broken_inside_word", doc)


class ShapingTests(unittest.TestCase):
    """1.15: drawtext does bidi and Arabic joining on a fribidi build but never reorders or
    re-clusters. graphics.py routes what it cannot shape through libass; overlay.py refuses."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "emoji_src.mp4"
        if not cls.src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "4",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(cls.src))

    def _skip_without(self, script_code):
        from _common import script_font_status
        if script_font_status(script_code) != "available":
            raise unittest.SkipTest("no font on this machine covers %r; tests never install fonts"
                                    % script_code)

    def test_graphics_devanagari_renders_through_libass_not_drawtext(self):
        self._skip_without("hi")
        out = OUT / "shape_hi.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "lower-third",
                                "--name", "\u092a\u094d\u0930\u093f\u092f\u093e \u0936\u0930\u094d\u092e\u093e",
                                "--title", "\u0928\u093f\u0930\u094d\u0926\u0947\u0936\u0915",
                                "--start", "0", "--end", "3", "-o", out, "--dry-run", "--json").stdout)
        self.assertEqual(doc["text_renderer"], "ass")
        self.assertEqual(doc["script"], "hi")
        graph = " ".join(doc["commands"])
        self.assertIn("ass=", graph)
        self.assertNotIn("drawtext=", graph, "the text must not also go through drawtext")

    def test_graphics_latin_still_renders_through_drawtext(self):
        out = OUT / "shape_latin.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "title",
                                "--title", "Episode 12", "--start", "0", "--end", "3",
                                "-o", out, "--dry-run", "--json").stdout)
        self.assertEqual(doc["text_renderer"], "drawtext")
        self.assertNotIn("ass", doc)
        self.assertIn("drawtext=", " ".join(doc["commands"]))

    def test_graphics_drawtext_forced_with_an_indic_script_is_refused_naming_the_script(self):
        self._skip_without("hi")
        out = OUT / "shape_refuse.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "title",
                                "--title", "\u0915\u093f\u0924\u093e\u092c", "--start", "0", "--end", "3",
                                "--text-render", "drawtext", "-o", out, "--json",
                                expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("Devanagari", doc["error"]["message"])
        self.assertIn("harfbuzz", doc["error"]["message"])

    def test_graphics_arabic_is_not_rerouted_on_a_fribidi_build(self):
        from _common import drawtext_shaping
        if not drawtext_shaping()["fribidi"]:
            raise unittest.SkipTest("this ffmpeg has no fribidi: Arabic legitimately needs the ASS route")
        self._skip_without("ar")
        out = OUT / "shape_ar.mp4"
        doc = json.loads(script("graphics.py", self.src, "--template", "title",
                                "--title", "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
                                "--start", "0", "--end", "3", "-o", out, "--dry-run", "--json").stdout)
        self.assertEqual(doc["text_renderer"], "drawtext")

    def test_graphics_font_file_override_survives_the_ass_route(self):
        self._skip_without("hi")
        font = font_for_script("hi")
        out = OUT / "shape_fontfile.mp4"
        proc = script("graphics.py", self.src, "--template", "title", "--title",
                      "\u0915\u093f\u0924\u093e\u092c", "--start", "0", "--end", "3",
                      "--font-file", font, "-o", out, "--json")
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["text_renderer"], "ass")
        self.assertIn("fontsdir=", " ".join(doc["commands"]))
        from _common import font_family_of_file
        family = font_family_of_file(font)
        ass = Path(doc["ass"]).read_text(encoding="utf-8-sig")
        self.assertIn(family, ass, "the --font-file's own family must reach the ASS Style line")

    def test_overlay_text_refuses_a_shaping_script_naming_the_tools_that_render_it(self):
        out = OUT / "shape_overlay.mp4"
        doc = json.loads(script("overlay.py", self.src, "--text", "\u0915\u093f\u0924\u093e\u092c",
                                "-o", out, "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("caption.py", doc["error"]["message"])
        self.assertIn("graphics.py", doc["error"]["message"])


class ApostropheAndPercentTests(unittest.TestCase):
    """1.15: `'` and `%` reach the picture. They used to be dropped outright by escape_drawtext."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "emoji_src.mp4"
        if not cls.src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "4",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(cls.src))

    def test_drawtext_keeps_an_apostrophe_and_a_percent_sign(self):
        out = OUT / "pct_overlay.mp4"
        doc = json.loads(script("overlay.py", self.src, "--text", "it's 100% done",
                                "-o", out, "--json").stdout)
        graph = " ".join(doc["commands"])
        m = re.search(r"textfile=(\S+?\.txt)", graph.replace("\\", ""))
        self.assertTrue(m, graph)
        self.assertIn("expansion=none", graph)
        self.assertTrue(Path(m.group(1)).parent.name.startswith("ffmpeg-skill-text-"),
                        "drawn text must go in a private per-run directory: " + m.group(1))
        self.assertFalse(Path(m.group(1)).exists(), "the drawn-text temp file must not outlive the run")
        self.assertEqual(doc["status"], "completed")
        # the drawn ink differs from the same render with the two characters stripped
        stripped = OUT / "pct_overlay_stripped.mp4"
        script("overlay.py", self.src, "--text", "its 100 done", "-o", stripped)
        self.assertNotEqual(_frame_ink(out), _frame_ink(stripped),
                            "the apostrophe and the percent sign left no ink on the frame")

    def test_caption_keeps_apostrophe_and_percent_in_the_drawn_text(self):
        cues = OUT / "cues_pct.txt"
        cues.write_text("0:00-0:02 it's 100% done\n", encoding="utf-8")
        out = OUT / "pct_caption.mp4"
        script("caption.py", self.src, "--text", cues, "--animate", "fade", "-o", out)
        srt = (OUT / "pct_caption.srt").read_text(encoding="utf-8")
        ass = (OUT / "pct_caption.ass").read_text(encoding="utf-8-sig")
        self.assertIn("it's 100% done", srt)
        self.assertIn("it's 100% done", ass)


class WrapReadabilityTests(unittest.TestCase):
    """1.15: no one-character orphan line, and a balanced break for spaced scripts."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        self.caption = importlib.import_module("caption")

    def test_caption_wrap_never_leaves_a_one_character_orphan_line(self):
        C = self.caption
        cases = [
            # dl3's Japanese cue at sizes where greedy wrapping stranded one character (the Thai
            # case this test carried until 1.16.0 is gone: a Thai run is no longer broken inside,
            # see test_th1_cue_exact_split); a Chinese run stands in for the per-character scripts
            ("\u4eca\u5929\u5929\u6c14\u5f88\u597d\u6211\u4eec\u53bb\u516c\u56ed\u6563\u6b65\u5427\u597d", 7),
            ("\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c 2 \u884c\u76ee\u306e\u5b57\u5e55\u3067\u3059 "
             "\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c\u6c7a\u307e\u308b\u884c", 10),
            ("\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c 2 \u884c\u76ee\u306e\u5b57\u5e55\u3067\u3059 "
             "\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c\u6c7a\u307e\u308b\u884c", 29),
        ]
        for text, max_em in cases:
            with self.subTest(max_em=max_em):
                greedy = C.wrap_text(text, max_em, balance=False)
                self.assertTrue(len(C._atoms(greedy[-1])) == 1 and C.text_width_em(greedy[-1]) < C.ORPHAN_MIN_EM,
                                "the case no longer reproduces greedily: %r" % greedy)
                lines = C.wrap_text(text, max_em)
                self.assertGreater(C.text_width_em(lines[-1]), C.ORPHAN_MIN_EM, lines)
                for line in lines:
                    self.assertLessEqual(C.text_width_em(line), max_em, lines)
                self.assertEqual("".join(lines).replace(" ", ""), "".join(greedy).replace(" ", ""))

    def test_caption_wrap_prefers_a_balanced_break_for_latin(self):
        C = self.caption
        text = "A third line the tool times for me"
        greedy = C.wrap_text(text, 14, balance=False)
        balanced = C.wrap_text(text, 14)
        self.assertEqual(len(greedy), len(balanced))
        self.assertLessEqual(max(C.text_width_em(l) for l in balanced),
                             max(C.text_width_em(l) for l in greedy))
        self.assertEqual(" ".join(balanced), text)
        self.assertNotEqual(greedy, balanced, "dl1's break did not move")

    def test_caption_wrap_rebalance_never_changes_the_line_count(self):
        C = self.caption
        samples = ["A third line the tool times for me",
                   "Hello world", "one two three four five six seven eight nine ten",
                   "\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c\u306e\u5b57\u5e55\u3067\u3059",
                   "Shipping day \U0001F389 for everyone here"]
        for text in samples:
            for max_em in range(4, 30):
                with self.subTest(text=text[:12], max_em=max_em):
                    self.assertEqual(len(C.wrap_text(text, max_em)),
                                     len(C.wrap_text(text, max_em, balance=False)))


class PhraseWrapTests(unittest.TestCase):
    """1.16: the four phrase rules (R1 never inside a word, R2 no weak line, R3 ja/zh preferred
    break points, R4 no function word at the end of a line), locked against the eval-16 cues."""

    # The em width a caption line has at a real destination's caption size, computed from the
    # platform table rather than pinned as a magic float (the size, the frame and the safe-area
    # fraction can all move; the test should move with them).
    @staticmethod
    def _max_em(platform_name):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        _platforms = importlib.import_module("_platforms")
        caption = importlib.import_module("caption")
        frame = _platforms.PLATFORMS[platform_name]["frame"]
        cap = _platforms.caption_defaults(platform_name)
        size_px = cap["size"] * frame["h"] / 288.0
        return (frame["w"] * caption.SAFE_WIDTH_FRACTION) / size_px

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        self.caption = importlib.import_module("caption")
        self.W = self._max_em("linkedin")     # 12.96 em: wide enough for a two-line cue
        self.NARROW = self._max_em("tiktok")  # 6.075 em: the vertical caption width

    # -------------------------------------------------------------- R1: never inside a word
    def test_wrap_never_splits_inside_a_word(self):
        C = self.caption
        corpus = [
            "A third line the tool times for me",
            "Segunda linea de subtitulos con acentos",
            "one two three four five six seven eight nine ten",
            "\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c 2 \u884c\u76ee\u306e\u5b57\u5e55\u3067\u3059",
            "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e0a\u0e32\u0e27\u0e42\u0e25\u0e01 \u0e40\u0e2a\u0e35\u0e22\u0e07\u0e19\u0e49\u0e33\u0e44\u0e2b\u0e25",
        ]
        for text in corpus:
            for max_em in (4.0, 6.075, 9.0, 12.96, 20.0):
                with self.subTest(text=text[:12], max_em=max_em):
                    lines = C.wrap_text(text, max_em)
                    self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""))
                    # every boundary between two spaced-script lines stood at a space or a hyphen
                    for a, b in zip(lines, lines[1:]):
                        if not a or not b:
                            continue
                        spaced = C.char_script(a[-1]) not in C.NO_SPACE_SCRIPTS \
                            and C.char_script(b[0]) not in C.NO_SPACE_SCRIPTS
                        if not spaced:
                            continue   # a no-space script breaks between characters by design
                        if not C._break_spaced(a, b):
                            self.assertTrue(a.endswith(("-", "\u2010")),
                                            "broke inside a word: %r | %r" % (a, b))

    def test_wrap_breaks_a_hyphenated_word_only_after_the_hyphen(self):
        C = self.caption
        lines = C.wrap_text("an end-to-end example", 6.0)
        self.assertEqual("".join(lines).replace(" ", ""), "anend-to-endexample")
        for a, b in zip(lines, lines[1:]):
            if a and b and not C._break_spaced(a, b):
                self.assertTrue(a.endswith("-"), "broke inside a word: %r | %r" % (a, b))
        # a non-breaking hyphen is never a break point
        self.assertEqual(C._split_hyphens([("well\u2011known", False)]), [("well\u2011known", False)])
        # ... and neither is a leading or trailing one
        self.assertEqual(C._split_hyphens([("-5", False)]), [("-5", False)])

    # -------------------------------------------------------------- R2: no weak line
    def test_is_weak_line_names_the_lines_no_reader_should_get(self):
        C = self.caption
        for weak in ("2", "--", "\u3066", "\u30f3", " "):
            self.assertTrue(C._is_weak_line(weak), repr(weak))
        for fine in ("me", "\u4e16\u754c", "\u0e44\u0e2b\u0e25"):
            self.assertFalse(C._is_weak_line(fine), repr(fine))

    def test_dl3_cue_exact_split(self):
        """dl3: no line that is a lone digit; the break is not between a kanji stem and its
        okurigana (`\u6c7a\u307e` | `\u308b`); and no line OPENS with a particle -- a particle is
        enclitic, so kinsoku keeps it with the word before it."""
        C = self.caption
        jp = "\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c\u6c7a\u307e\u308b\u884c"
        for max_em in (self.NARROW, self.W, 10.0, 14.0):
            with self.subTest(max_em=max_em):
                lines = C.wrap_text("2 \u884c\u76ee\u306e\u5b57\u5e55\u3067\u3059", max_em)
                self.assertNotIn("2", lines, lines)
                lines = C.wrap_text(jp, max_em)
                for a, b in zip(lines, lines[1:]):
                    self.assertFalse(a.endswith("\u6c7a\u307e") and b.startswith("\u308b"),
                                     "broke inside \u6c7a\u307e\u308b: %r" % (lines,))
                    self.assertNotIn(b[0], C.JA_PARTICLES,
                                     "a line opens with a particle: %r" % (lines,))
        # the break falls after \u304c, not before it
        self.assertEqual(C.wrap_text(jp, 10.0),
                         ["\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c", "\u6c7a\u307e\u308b\u884c"])
        self.assertEqual(C.wrap_text(jp, self.W),
                         ["\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c", "\u6c7a\u307e\u308b\u884c"])

    def test_th1_cue_exact_split(self):
        """th1: the trailing line is never the stranded `\u0e44\u0e2b\u0e25` alone -- and since 1.16.1 a
        Thai run is never broken inside at all. Thai writes no space inside a phrase and the
        wrapper has no dictionary, so every character-level break eval 17 took landed inside a
        word (`\u0e02|\u0e2d\u0e07`, `\u0e40\u0e27|\u0e25\u0e32`). The break goes where the writer put a space; a run
        with none stays long on its own line, the rule long Latin words already follow."""
        C = self.caption
        first, second = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e0a\u0e32\u0e27\u0e42\u0e25\u0e01", "\u0e40\u0e2a\u0e35\u0e22\u0e07\u0e19\u0e49\u0e33\u0e44\u0e2b\u0e25"
        text = first + " " + second
        for max_em in (self.NARROW, 8.0, self.W):
            with self.subTest(max_em=max_em):
                lines = C.wrap_text(text, max_em)
                self.assertEqual(lines, [first, second], lines)
                self.assertFalse(C._is_weak_line(lines[-1]), lines)
        # a Thai run with no space is one atom: never chopped, however narrow the line
        run = "\u0e1a\u0e23\u0e23\u0e17\u0e31\u0e14\u0e17\u0e35\u0e48\u0e2a\u0e2d\u0e07\u0e02\u0e2d\u0e07\u0e04\u0e33\u0e1a\u0e23\u0e23\u0e22\u0e32\u0e22"
        self.assertEqual(C.wrap_text(run, self.NARROW), [run])
        self.assertEqual(C.wrap_text(run, 8.0, mode="measured"), [run])

    def test_katakana_run_is_one_atom(self):
        """eval 17 dl3: `\u30bf\u30a4|\u30df\u30f3\u30b0` -- a katakana loan word was broken like a run of kanji.
        Katakana plus the prolonged-sound mark are one atom; the break lands before or after
        the word, and a word too wide for the line stays long rather than chopped."""
        C = self.caption
        jp = "\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c\u6c7a\u307e\u308b\u884c"
        for max_em in (self.NARROW, 8.0, 10.0):
            with self.subTest(max_em=max_em):
                joined = "".join(C.wrap_text(jp, max_em))
                self.assertEqual(joined, jp)
                for line in C.wrap_text(jp, max_em):
                    self.assertFalse(line.endswith("\u30bf\u30a4") or line.startswith("\u30df\u30f3\u30b0"), line)
        self.assertEqual(C.wrap_text(jp, self.NARROW), ["\u81ea\u52d5\u3067", "\u30bf\u30a4\u30df\u30f3\u30b0\u304c", "\u6c7a\u307e\u308b\u884c"])
        self.assertEqual(C.wrap_text("\u30b3\u30f3\u30d4\u30e5\u30fc\u30bf\u30fc\u3092\u8cb7\u3063\u305f", 7.0), ["\u30b3\u30f3\u30d4\u30e5\u30fc\u30bf\u30fc", "\u3092\u8cb7\u3063\u305f"])
        self.assertEqual([a for a, _ in C._atoms("\u30bf\u30a4\u30df\u30f3\u30b0\u304c")][0], "\u30bf\u30a4\u30df\u30f3\u30b0")

    # -------------------------------------------------------------- escape hatch (1.18.4, cs2)
    def test_overlong_word_is_sliced_at_the_column_edge(self):
        """cs2 (eval 20): a single 32-letter word with no break point, wider than the live column
        even at --min-size, used to be kept whole and clipped past both frame edges. It is now
        hard-sliced at exactly the column width, wherever `slice_overlong` is turned on -- the
        escape hatch itself is off by default in wrap_text()/wrap_variants(), so nothing here
        changes unless a caller asks for it (caption.py's burn-in pass is the only caller that
        does)."""
        C = self.caption
        word = "Supercalifragil\u00edsticoespialidoso"
        for max_em in (self.NARROW, 8.0, self.W):
            with self.subTest(max_em=max_em):
                # off by default: the word is kept whole, exactly as before this change
                self.assertEqual(C.wrap_text(word, max_em), [word])
                # the escape hatch: every produced line now measures within the column
                lines = C.wrap_text(word, max_em, slice_overlong=True)
                for line in lines:
                    self.assertLessEqual(C.text_width_em(line), max_em, lines)
                # no character was added, dropped or reordered
                self.assertEqual("".join(lines), word)

    def test_overlong_word_prefers_its_own_hyphen(self):
        """When the overlong atom already has a hyphen, the slice prefers the cut right after it
        -- the same break R1 already allows elsewhere -- over an arbitrary character cut, as long
        as that still fits the column."""
        C = self.caption
        atom = "co-occurrencemeasurementsomethingunbreakablylong"
        pieces = C._slice_atom(atom, 12.0)
        self.assertTrue(pieces[0].endswith("-"), pieces)
        for piece in pieces:
            self.assertLessEqual(C.text_width_em(piece), 12.0, pieces)
        self.assertEqual("".join(pieces), atom)

    def test_layout_cues_reports_broken_inside_word_not_overlong(self):
        """caption.py's per-cue loop (layout_cues) is the one caller that turns the escape hatch
        on. cs2's cue now burns in with every line inside the safe column, and the new
        `broken_inside_word` stat -- not `overlong` -- counts it."""
        C = self.caption
        word = "Supercalifragil\u00edsticoespialidoso"
        max_em = self.NARROW
        cues = [(0.0, 3.0, word)]
        out, stats = C.layout_cues(cues, max_em=max_em, max_lines=4, min_duration=0.0, offset=0.0)
        self.assertEqual(stats.get("broken_inside_word", 0), 1, stats)
        self.assertNotIn("overlong", stats)
        for _start, _end, text in out:
            for line in text.split("\n"):
                self.assertLessEqual(C.text_width_em(line), max_em, out)

    def test_overlong_still_fires_when_even_one_character_does_not_fit(self):
        """The escape hatch guarantees every piece fits as long as at least one character does.
        `overlong` is not dead code: it is the fallback for the one case the hatch cannot fix, a
        single character wider than the column itself (a pathologically small --size)."""
        C = self.caption
        # a full-width ideograph is 1.0 em; 0.5 em is narrower than any single character of it
        text = "\u4e00\u4e8c\u4e09"
        max_em = 0.5
        cues = [(0.0, 3.0, text)]
        out, stats = C.layout_cues(cues, max_em=max_em, max_lines=1, min_duration=0.0, offset=0.0)
        self.assertEqual(stats.get("overlong", 0), 1, stats)

    def test_escape_hatch_never_touches_a_fitting_thai_or_katakana_run(self):
        """The hard constraint: an atom that already fits is never eligible for the escape hatch,
        even with `slice_overlong=True` -- a fitting Thai phrase or katakana run must come back
        exactly as written, same as 1.16.1."""
        C = self.caption
        thai_run = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e0a\u0e32\u0e27\u0e42\u0e25\u0e01"
        kata_run = "\u30b3\u30f3\u30d4\u30e5\u30fc\u30bf\u30fc"
        wide = self.W  # both runs fit comfortably at the wide platform width
        self.assertLessEqual(C.text_width_em(thai_run), wide)
        self.assertLessEqual(C.text_width_em(kata_run), wide)
        self.assertEqual(C.wrap_text(thai_run, wide, slice_overlong=True), [thai_run])
        self.assertEqual(C.wrap_text(kata_run, wide, slice_overlong=True), [kata_run])
        # and unbroken through wrap_variants, the entry point caption.py actually calls
        wrapped, greedy, measured = C.wrap_variants(thai_run, wide, slice_overlong=True)
        self.assertEqual(wrapped, [thai_run])
        wrapped, greedy, measured = C.wrap_variants(kata_run, wide, slice_overlong=True)
        self.assertEqual(wrapped, [kata_run])

    # -------------------------------------------------------------- R4: function words
    def test_function_word_never_ends_a_line(self):
        C = self.caption
        cases = {
            "en": "A third line the tool times for me",
            "es": "Una tercera linea con tiempos automaticos",
            "pt": "Uma terceira linha com tempos automaticos",
            "fr": "La ligne trois avec temps automatiques",
            "de": "Zeile drei zeigt die Zeiten automatisch",
            "it": "Una terza riga con i tempi automatici",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                lines = C.wrap_text(text, self.W, lang=lang)
                for line in lines[:-1]:
                    last = C._bare_word(line.split(" ")[-1])
                    self.assertNotIn(last, C._function_words(lang),
                                     "%s: line ends on a function word: %r" % (lang, lines))
                # and the rule works by preferring the break BEFORE the word, not only by
                # vetoing the one after it
                self.assertNotEqual(lines, C.wrap_text(text, self.W, mode="measured"),
                                    "%s: the greedy break did not move" % lang)

    def test_dl4_cue_exact_split(self):
        """dl4, both cues, at the width that reproduced the eval-16 splits."""
        C = self.caption
        self.assertEqual(C.wrap_text("Segunda l\u00ednea de subt\u00edtulos", self.W, lang="es"),
                         ["Segunda l\u00ednea", "de subt\u00edtulos"])
        self.assertEqual(C.wrap_text("Una tercera l\u00ednea con tiempos autom\u00e1ticos", self.W, lang="es"),
                         ["Una tercera l\u00ednea", "con tiempos autom\u00e1ticos"])

    def test_dl1_cue_exact_split(self):
        """dl1. R4 scores both directions: `the` opens the phrase it governs, so the break BEFORE
        it is the preferred one and the break after it the penalised one. Both halves fit, so the
        cue comes out as one whole phrase per line. `--wrap measured` still gives 1.15's split."""
        C = self.caption
        text = "A third line the tool times for me"
        for max_em in (self.W, 14.0, 16.0):
            with self.subTest(max_em=max_em):
                self.assertEqual(C.wrap_text(text, max_em, lang="en"),
                                 ["A third line", "the tool times for me"])
        self.assertEqual(C.wrap_text(text, self.W, mode="measured"),
                         ["A third line the", "tool times for me"])

    # -------------------------------------------------------------- modes and invariants
    def test_wrap_measured_is_byte_identical_to_1_15(self):
        """`--wrap measured` reproduces the outputs the 1.15 tests pinned."""
        C = self.caption
        self.assertEqual(C.wrap_text("A third line the tool times for me", 14.0, mode="measured"),
                         ["A third line the", "tool times for me"])
        self.assertEqual(C.wrap_text("A third line the tool times for me", 14.0,
                                     balance=False, mode="measured"),
                         ["A third line the tool times", "for me"])
        self.assertEqual(C.wrap_text("Segunda l\u00ednea de subt\u00edtulos", self.W, mode="measured"),
                         ["Segunda l\u00ednea", "de subt\u00edtulos"])

    def test_wrap_line_count_never_grows(self):
        C = self.caption
        corpus = ["A third line the tool times for me", "Hello world",
                  "one two three four five six seven eight nine ten",
                  "Una tercera l\u00ednea con tiempos autom\u00e1ticos",
                  "\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c\u306e\u5b57\u5e55\u3067\u3059",
                  "\u81ea\u52d5\u3067\u30bf\u30a4\u30df\u30f3\u30b0\u304c\u6c7a\u307e\u308b\u884c",
                  "an end-to-end example of a long hyphenated line"]
        for text in corpus:
            for max_em in range(4, 30):
                with self.subTest(text=text[:12], max_em=max_em):
                    for mode in ("phrase", "measured"):
                        self.assertEqual(len(C.wrap_text(text, float(max_em), mode=mode)),
                                         len(C.wrap_text(text, float(max_em), balance=False)),
                                         mode)

    def test_multi_character_particles_are_matched_as_words_not_characters(self):
        """から / まで / より are two-character particles. Keeping them in the CHARACTER table made
        か, ら, ま, で, よ and り one-character particles of their own, which none of them is."""
        C = self.caption
        for ch in "\u304b\u3089\u307e\u3088\u308a":
            self.assertNotIn(ch, C.JA_PARTICLES, "%r is not a particle on its own" % ch)
        # \u304b after a kanji stem is okurigana, not a forbidden line start
        self.assertEqual(C.break_penalty("\u6f22", "\u304b", "ja",
                                         before="\u6f22", after="\u304b\u305f\u3061"), 0.9)
        # the whole word is seen when the caller passes the surrounding text
        self.assertEqual(C.break_penalty("\u305f", "\u304b", "ja",
                                         before="\u898b\u305f", after="\u304b\u3089\u3067\u3059"), 1.0)
        self.assertEqual(C.break_penalty("\u3089", "\u8a71", "ja",
                                         before="\u898b\u305f\u304b\u3089", after="\u8a71\u3057\u305f"), 0.2)
        # ... and a \u3089 that merely ends a word is not a particle
        self.assertEqual(C.break_penalty("\u3089", "\u8a71", "ja",
                                         before="\u3055\u304f\u3089", after="\u8a71\u3057\u305f"), 0.5)

    def test_break_penalty_prefers_a_sentence_end_and_a_particle(self):
        C = self.caption
        self.assertEqual(C.break_penalty("\u3002", "\u6b21", "ja"), 0.0)
        # a particle keeps company with the word BEFORE it: breaking after one is preferred,
        # breaking before one is forbidden
        self.assertEqual(C.break_penalty("\u306f", "\u4e16", "ja"), 0.2)   # after a particle
        self.assertEqual(C.break_penalty("\u754c", "\u306f", "ja"), 1.0)   # before a particle
        self.assertLess(C.break_penalty("\u306f", "\u4e16", "ja"),         # after a particle
                        C.break_penalty("\u6c7a", "\u307e", "ja"))         # inside a word
        self.assertEqual(C.break_penalty("\u3042", "\u3063", "ja"), 1.0)  # small kana may not start a line


class FitSizeTests(unittest.TestCase):
    """1.17: the caption size is fitted to the cue before the cue is split (eval 17).

    Pure -- no fixtures, no ffmpeg. The geometry and the requested size come from the platform
    table, never from a pinned float, so the lock moves if the platform's caption default moves.
    """

    # The eval-17 cues, verbatim. cw1 and dl1 carry the same English sentence.
    CW1 = "A third line the tool times for me"
    DL4 = "Una tercera l\u00ednea con tiempos autom\u00e1ticos"
    DL4B = "Segunda l\u00ednea de subt\u00edtulos"

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        self.caption = importlib.import_module("caption")
        self._platforms = importlib.import_module("_platforms")
        frame = self._platforms.PLATFORMS["tiktok"]["frame"]
        self.W, self.H = frame["w"], frame["h"]
        self.SIZE = self._platforms.caption_defaults("tiktok")["size"]

    def _fit(self, cues, **kw):
        kw.setdefault("size", self.SIZE)
        kw.setdefault("max_lines", 2)
        return self.caption.fit_size(cues, play_w=self.W, play_h=self.H, **kw)

    def _wrap(self, text, size):
        em = self.caption.line_em_for_size(size, self.W, self.H)
        return self.caption.wrap_text(text, em)

    def test_the_floor_is_four_and_a_half_percent_of_the_frame(self):
        C = self.caption
        self.assertEqual(C.MIN_CAPTION_FRACTION, 0.045)
        self.assertEqual(self._platforms.ass_units(C.MIN_CAPTION_FRACTION), 13)
        self.assertEqual(self._fit([self.CW1])["floor"], 13)

    def test_eval17_cues_fit_two_lines_at_the_shrunk_size(self):
        """The regression lock. At the TikTok caption size every one of these needs three or
        four lines, so --max-lines 2 split each into consecutive cues; shrinking fits them."""
        # At the requested size, all three are over the line budget -- the defect.
        for text in (self.CW1, self.DL4, self.DL4B):
            self.assertGreater(len(self._wrap(text, self.SIZE)), 2)

        cw1 = self._fit([self.CW1])
        self.assertEqual(cw1["size"], 16)
        self.assertEqual(self._wrap(self.CW1, 16), ["A third line the", "tool times for me"])

        dl4 = self._fit([self.DL4])
        self.assertEqual(dl4["size"], 13)
        self.assertEqual(self._wrap(self.DL4, 13),
                         ["Una tercera l\u00ednea con", "tiempos autom\u00e1ticos"])

        # 19, not 18: 18 is simply the next size the spec's coarse table sampled. 19 is the
        # largest size at which this cue fits two lines, and the fitter returns the largest.
        dl4b = self._fit([self.DL4B])
        self.assertEqual(dl4b["size"], 19)
        self.assertEqual(self._wrap(self.DL4B, 19), ["Segunda l\u00ednea", "de subt\u00edtulos"])

        whole = self._fit([self.CW1, self.DL4, self.DL4B])
        self.assertEqual(whole["size"], 13)
        self.assertEqual(whole["scope"], "file")
        self.assertTrue(whole["fits"])
        self.assertEqual(whole["shrunk"], 3)
        for text in (self.CW1, self.DL4, self.DL4B):
            self.assertLessEqual(len(self._wrap(text, whole["size"])), 2)

    def test_fit_size_never_goes_below_the_floor(self):
        # One unbreakable run far wider than the line at any size in range.
        fit = self._fit(["Donaudampfschifffahrtsgesellschaftskapitaenspatentpruefung " * 3])
        self.assertEqual(fit["size"], 13)
        self.assertEqual(fit["floor"], 13)
        self.assertFalse(fit["fits"])

    def test_fit_size_leaves_a_cue_that_already_fits_alone(self):
        fit = self._fit(["Short line"])
        self.assertEqual(fit["size"], self.SIZE)
        self.assertEqual(fit["shrunk"], 0)

    def test_fit_size_honours_an_explicit_min_size(self):
        fit = self._fit([self.DL4], min_size=16)
        self.assertEqual(fit["floor"], 16)
        self.assertEqual(fit["size"], 16)
        self.assertFalse(fit["fits"])

    def test_fit_size_without_geometry_changes_nothing(self):
        fit = self.caption.fit_size([self.DL4], size=self.SIZE, max_lines=2,
                                    play_w=None, play_h=None)
        self.assertEqual(fit["size"], self.SIZE)
        self.assertEqual(fit["shrunk"], 0)

    def test_scope_cue_gives_per_cue_sizes(self):
        fit = self._fit([self.CW1, self.DL4, "Short line"], scope="cue")
        self.assertEqual(fit["scope"], "cue")
        self.assertEqual(fit["per_cue"][0], 16)
        self.assertEqual(fit["per_cue"][1], 13)
        self.assertEqual(fit["per_cue"][2], self.SIZE)
        self.assertEqual(fit["size"], min(fit["per_cue"].values()))

    def test_fit_size_accepts_cue_tuples(self):
        tuples = [(0.0, 1.0, self.CW1), (1.0, 2.0, self.DL4)]
        self.assertEqual(self._fit(tuples)["size"], self._fit([self.CW1, self.DL4])["size"])

    def test_fit_size_is_pure(self):
        """No subprocess, no ffmpeg, no ffprobe: the size is a text measurement."""
        import importlib
        _common = importlib.import_module("_common")
        def boom(*a, **k):
            raise AssertionError("fit_size ran a subprocess")
        with unittest.mock.patch.object(_common, "run", boom), \
             unittest.mock.patch.object(_common, "run_analysis", boom), \
             unittest.mock.patch.object(subprocess, "run", boom), \
             unittest.mock.patch.object(subprocess, "Popen", boom):
            self.assertEqual(self._fit([self.CW1])["size"], 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
