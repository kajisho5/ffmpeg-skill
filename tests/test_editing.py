#!/usr/bin/env python3
"""End-to-end tests for cut, fit, crop, join, insert, broll, freeze, pad, speedramp, loop, reverse, sequence, silence, metadata, straighten and sphere.

    python3 tests/test_editing.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import os
import platform
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, _is_faststart, script, sh  # noqa: E402
from _common import probe  # noqa: E402


class EditingTests(MediaFixtures):
    """Cut, fit, crop, join, insert, broll, freeze, pad, speedramp, loop, reverse, sequence, silence, metadata, straighten and sphere."""

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
        # same shape as #275/#277: a stream-copy mp4-writing path must add -movflags +faststart
        self.assertTrue(_is_faststart(out), "cut.py's lossless single-segment stream copy must write +faststart")

    def test_cut_multi_segment_concat_copy_writes_faststart_mp4(self):
        """Same shape as #275/#277: the multi-segment concat join (`-f concat ... -c copy`) is a
        second, separate mp4-writing stream-copy path from the single-segment one above."""
        out = OUT / "cut_concat_faststart.mp4"
        script("cut.py", self.src, "--segments", "1-3,6-9", "-o", out)
        self.assertTrue(_is_faststart(out), "cut.py's multi-segment concat join must write +faststart")

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
        # ...and name the keyframes a lossless cut could have used instead (x264's default GOP on the
        # fixture puts the only one within 5 s of 1.13 at 0.0)
        self.assertTrue(data3["nearest_keyframes"], data3)
        self.assertIn(0.0, data3["nearest_keyframes"])
        self.assertIsNone(data["nearest_keyframes"], "a clean copy has no alternative to offer")

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

    def test_broll_cutaway_shows_b_in_the_window_and_keeps_a_elsewhere(self):
        """#141: broll.py shows B's picture over A for a window and returns to A at A's own time;
        the output is exactly A's length. Checked frame by frame: inside the window a frame
        matches B (at --from + offset) and not A; outside it matches A. --audio a stream-copies
        A's audio; two cutaways in one call; overlapping or past-the-end windows are refused."""
        def frame_luma(path, t):
            proc = sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                      "-vf", "signalstats,metadata=print:file=-", "-f", "null", "-")
            return float(re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", proc.stdout).group(1))
        b = OUT / "broll_b.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "smptebars=size=960x540:rate=25:d=8",
           "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=8", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", b)
        out = OUT / "broll_out.mp4"
        data = json.loads(script("broll.py", self.src, "--insert", b, "--at", "4", "--end", "7", "--from", "1", "--fast", "--json", "-o", out).stdout)
        # --pad-color is spliced into the filter graph like every other colour flag, so it is validated like them
        inj = script("broll.py", self.src, "--insert", b, "--at", "4", "--end", "7", "--pad-color", "black,drawtext=text=INJECTED",
                     "--json", "-o", OUT / "broll_inj.mp4", expect_fail=True)
        self.assertIn("plain colour", json.loads(inj.stdout)["error"]["message"])
        self.assertEqual(json.loads(inj.stdout)["commands"], [], "refused before ffmpeg ran")
        self.assertEqual(data["cutaways"], [{"insert": str(b), "at": 4.0, "end": 7.0, "from": 1.0}])
        m = probe(str(out))
        self.assertClose(m["duration"], probe(str(self.src))["duration"], 0.1)
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))
        self.assertEqual(m["audio"]["codec"], probe(str(self.src))["audio"]["codec"], "--audio a stream-copies A's audio")
        inside_out, inside_b, inside_a = frame_luma(str(out), 5.5), frame_luma(str(b), 2.5), frame_luma(str(self.src), 5.5)
        self.assertLess(abs(inside_out - inside_b), 6, f"inside the window the frame must be B's: out {inside_out} b {inside_b} a {inside_a}")
        self.assertGreater(abs(inside_out - inside_a), 6, "inside the window the frame must not be A's")
        for t in (2.0, 9.0):
            self.assertLess(abs(frame_luma(str(out), t) - frame_luma(str(self.src), t)), 3, f"outside the window ({t}s) A must show unchanged")
        # two cutaways, B's audio mixed in, per-cutaway durations
        out2 = OUT / "broll_out2.mp4"
        script("broll.py", self.src, "--insert", b, "--at", "1", "--duration", "2", "--insert", b, "--at", "8", "--duration", "3", "--audio", "mix", "--fast", "-o", out2)
        m2 = probe(str(out2))
        self.assertClose(m2["duration"], 12.0, 0.1)
        self.assertEqual(m2["audio"]["codec"], "aac")
        self.assertLess(abs(frame_luma(str(out2), 9.5) - frame_luma(str(b), 1.5)), 6)
        # refusals: overlap, past the end, B too short, missing --at
        script("broll.py", self.src, "--insert", b, "--at", "1", "--duration", "3", "--insert", b, "--at", "2", "-o", OUT / "broll_bad1.mp4", expect_fail=True)
        script("broll.py", self.src, "--insert", b, "--at", "10", "--duration", "5", "-o", OUT / "broll_bad2.mp4", expect_fail=True)
        script("broll.py", self.src, "--insert", b, "--at", "1", "--duration", "5", "--from", "5", "-o", OUT / "broll_bad3.mp4", expect_fail=True)
        script("broll.py", self.src, "--insert", b, "--insert", b, "--at", "1", "-o", OUT / "broll_bad4.mp4", expect_fail=True)
        dry = OUT / "broll_dry.mp4"
        script("broll.py", self.src, "--insert", b, "--at", "4", "--dry-run", "-o", dry)
        self.assertFalse(dry.exists())

    def test_metadata_writes_chapters_and_tags_with_streams_copied(self):
        """#140: metadata.py writes container chapter markers from a `TIME TITLE` file and the
        common tags, with every stream copied bit for bit; probe reports both back. Chapters on a
        container that cannot hold them are refused, --clear-chapters removes them, a chapter
        past the end or out of order is refused, and the input is never rewritten in place."""
        chapters = OUT / "chapters.txt"
        chapters.write_text("# episode\n0:00 Intro\n4 Setup, with a comma; and =signs\n0:08 Outro\n", encoding="utf-8")
        out = OUT / "meta_chapters.mp4"
        data = json.loads(script("metadata.py", self.src, "--chapters", chapters, "--title", "Episode 12", "--artist", "Studio", "--comment", "final", "--json", "-o", out).stdout)
        self.assertTrue(data["streams_copied"])
        m = probe(str(out))
        self.assertEqual([(round(c["start"]), round(c["end"]), c["title"]) for c in m["chapters"]],
                         [(0, 4, "Intro"), (4, 8, "Setup, with a comma; and =signs"), (8, 12, "Outro")])
        self.assertEqual(m["tags"].get("title"), "Episode 12")
        self.assertEqual(m["tags"].get("artist"), "Studio")
        self.assertEqual(m["tags"].get("comment"), "final")
        src = probe(str(self.src))
        self.assertEqual((m["video"]["codec"], m["audio"]["codec"]), (src["video"]["codec"], src["audio"]["codec"]))
        self.assertEqual(self._frame_count(out), self._frame_count(self.src))
        self.assertEqual(self._psnr(self.src, out), float("inf"), "streams must be copied, not re-encoded")
        # tags alone keep the chapters; --clear-chapters removes them and keeps the tags
        tagged = OUT / "meta_tagged.mp4"
        script("metadata.py", out, "--comment", "v2", "-o", tagged)
        self.assertEqual(len(probe(str(tagged))["chapters"]), 3)
        self.assertEqual(probe(str(tagged))["tags"].get("comment"), "v2")
        cleared = OUT / "meta_cleared.mp4"
        script("metadata.py", out, "--clear-chapters", "-o", cleared)
        self.assertEqual(probe(str(cleared))["chapters"], [])
        self.assertEqual(probe(str(cleared))["tags"].get("title"), "Episode 12")
        # refusals
        script("metadata.py", OUT / "long_ref.wav", "--chapters", chapters, "-o", OUT / "meta_bad.wav", expect_fail=True)
        script("metadata.py", self.src, "-o", OUT / "meta_nothing.mp4", expect_fail=True)
        script("metadata.py", self.src, "--title", "x", "-o", self.src, expect_fail=True)
        bad = OUT / "chapters_bad.txt"
        bad.write_text("0:00 A\n0:30 B\n", encoding="utf-8")
        script("metadata.py", self.src, "--chapters", bad, "-o", OUT / "meta_bad2.mp4", expect_fail=True)
        bad.write_text("0:05 A\n0:02 B\n", encoding="utf-8")
        script("metadata.py", self.src, "--chapters", bad, "-o", OUT / "meta_bad3.mp4", expect_fail=True)
        # dry run writes nothing
        dry = OUT / "meta_dry.mp4"
        script("metadata.py", self.src, "--chapters", chapters, "--dry-run", "-o", dry)
        self.assertFalse(dry.exists())

    def test_fit_pad_fill_blur_puts_picture_in_the_bars_and_color_stays_solid(self):
        """#139: --fit pad --pad-fill blur fills the letterbox/pillarbox bars with a blurred,
        scaled-to-cover copy of the frame (the phone-editor "make it vertical" look) instead of a
        solid --pad-color. The source is landscape, so 9:16 gives bars above and below: with
        blur they must carry picture (not black, not one flat value), with color (the default)
        they must stay the solid pad colour exactly as before. export.py shares the same path."""
        def bar_stats(path, top_px=60):
            # mean and spread of the top bar's luma over a frame at t=1s
            proc = sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", path, "-frames:v", "1",
                      "-vf", f"crop=iw:{top_px}:0:0,signalstats,metadata=print:file=-", "-f", "null", "-")
            vals = {k: float(v) for k, v in re.findall(r"lavfi\.signalstats\.(YAVG|YMIN|YMAX)=([0-9.]+)", proc.stdout)}
            return vals["YAVG"], vals["YMAX"] - vals["YMIN"]
        blur = OUT / "fit_pad_blur.mp4"
        script("fit.py", self.src, "--duration", "3", "--aspect", "9:16", "--fit", "pad", "--pad-fill", "blur", "--width", "360", "--fast", "-o", blur)
        m = probe(str(blur))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (360, 640))
        avg, spread = bar_stats(str(blur))
        self.assertGreater(avg, 20, f"blurred bar is (nearly) black: YAVG {avg}")
        self.assertGreater(spread, 10, f"blurred bar is flat: spread {spread}")
        solid = OUT / "fit_pad_color.mp4"
        script("fit.py", self.src, "--duration", "3", "--aspect", "9:16", "--fit", "pad", "--width", "360", "--fast", "-o", solid)
        avg, spread = bar_stats(str(solid))
        self.assertLess(avg, 20, f"solid black bar is not black: YAVG {avg}")
        self.assertLess(spread, 4, f"solid bar is not flat: spread {spread}")
        # the same option on export.py's preset frame
        exp = OUT / "export_pad_blur.mp4"
        script("export.py", self.src, "--preset", "reels", "--pad-fill", "blur", "--fast", "-o", exp)
        avg, spread = bar_stats(str(exp), 120)
        self.assertGreater(avg, 20); self.assertGreater(spread, 10)
        script("fit.py", self.src, "--aspect", "9:16", "--pad-fill", "blur", "--pad-blur", "0", "--dry-run", expect_fail=True)

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

    def test_sequence_warns_about_frames_past_a_numbering_gap(self):
        """2.2.1: frame 2 missing used to silently stop the sequence at 2 frames."""
        frames_dir = OUT / "seqframes_gap"
        frames_dir.mkdir(exist_ok=True)
        for i in (0, 1, 3, 4):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48",
               "-frames:v", "1", frames_dir / f"frame_{i:04d}.png")
        proc = script("sequence.py", "--dir", frames_dir, "--pattern", "frame_%04d.png", "--fps", "5",
                      "-o", OUT / "seq_gap.mp4")
        self.assertIn("frame_0002.png is missing; 2 later frame(s)", proc.stderr)

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

    def test_time_grammar_is_one_parser_with_an_fps_suffix(self):
        """1.9 (roadmap): hh:mm:ss:ff@fps names the rate; broll / cut / freeze refuse a bad time as
        kind input naming the flag, like every other tool, instead of their own wording."""
        sys.path.insert(0, str(SCRIPTS))
        try:
            import _common as c
        finally:
            sys.path.pop(0)
        self.assertAlmostEqual(c.parse_time("00:00:01:15@30"), 1.5)
        self.assertAlmostEqual(c.parse_time("00:00:01:15@30", fps=24), 1.5, msg="the suffix beats the fps a tool passed in")
        self.assertAlmostEqual(c.parse_time("01:00:00:00@29.97"), 108000 / 29.97)
        with self.assertRaises(ValueError):
            c.parse_time("12.5@30")
        with self.assertRaises(ValueError):
            c.parse_time("00:00:01:15@fast")
        with self.assertRaises(c.MissingFpsError):
            c.parse_time("00:00:01:15")
        # the three tools that had their own wrappers
        d = json.loads(script("cut.py", self.src, "--start", "00:00:01:15@30", "--end", "00:00:02:00@30", "-o", OUT / "tc_cut.mp4", "--json", "--overwrite").stdout)
        self.assertAlmostEqual(d["expected_duration"], 0.5, places=2)
        d = json.loads(script("cut.py", self.src, "--start", "nonsense", "-o", OUT / "tc_bad.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("--start", d["error"]["message"])
        d = json.loads(script("freeze.py", self.src, "--at", "1:xx", "--hold", "1", "-o", OUT / "tc_freeze.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("--at", d["error"]["message"])
        d = json.loads(script("broll.py", self.src, "--insert", self.src, "--at", "1:xx", "-o", OUT / "tc_broll.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("--at", d["error"]["message"])
        # 1.9.1 (audit 8): a cue file may carry the suffix too -- the timecodes must not become the caption text
        with self.assertRaises(ValueError) as cm:
            c.parse_time("00:00:01:15@30@30")
        self.assertIn("only one @fps", str(cm.exception), "no interpreter internals in the refusal")
        tc = OUT / "tc_at_cues.txt"
        tc.write_text("00:00:00:15@30 --> 00:00:02:00@30 Hello there\n", encoding="utf-8")
        srt = OUT / "tc_at.srt"
        script("caption.py", "--text", tc, "--write-srt", srt)
        text = srt.read_text(encoding="utf-8")
        self.assertIn("00:00:00,500 --> 00:00:02,000\nHello there", text)
        self.assertNotIn("@30", text)
        # metadata / multicam / speedramp refuse through the same parser and name the suffix
        ch = OUT / "tc_chapters.txt"
        ch.write_text("00:00:01:00 Intro\n", encoding="utf-8")
        d = json.loads(script("metadata.py", self.src, "--chapters", ch, "-o", OUT / "tc_md.mp4", "--json", "--dry-run", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("@fps", d["error"]["message"])
        ch.write_text("00:00:01:00@30 Intro\n", encoding="utf-8")
        script("metadata.py", self.src, "--chapters", ch, "-o", OUT / "tc_md.mp4", "--json", "--dry-run")
        d = json.loads(script("multicam.py", self.src, self.src, "--switch", "0-1:xx:0", "-o", OUT / "tc_mc.mp4", "--json", "--dry-run", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("@fps", d["error"]["message"])
        d = json.loads(script("speedramp.py", self.src, "--segment", "0-1:xx:2", "-o", OUT / "tc_sr.mp4", "--json", "--dry-run", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("@fps", d["error"]["message"])

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

    def test_fit_smooth_slow_motion_blend(self):
        out = OUT / "slow.mp4"
        script("fit.py", self.src, "--duration", "18", "--smooth", "blend", "--preset", "veryfast", "-o", out)
        m = probe(str(out))
        self.assertClose(m["duration"], 18.0, 0.2)
        self.assertClose(m["video"]["fps"], 30.0, 0.05, "frame rate preserved while slowing down")

    def test_silence_removal(self):
        gappy = OUT / "gappy.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", gappy)
        data = json.loads(script("silence.py", gappy, "--list", "--json").stdout)
        self.assertEqual(len(data["silences"]), 3)
        self.assertNotIn("hint", data, "a hit needs no hint")
        # a track with nothing under the threshold says what the floor is and which flag to change,
        # instead of a bare "0 silences" that sends an agent off to raw ffmpeg (evals iteration 5, finding 1)
        tone = OUT / "tone.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
           "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "4", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", tone)
        none = json.loads(script("silence.py", tone, "--list", "--json").stdout)
        self.assertEqual(none["silences"], [])
        self.assertIn("--threshold", none["hint"])
        self.assertIn("mean level", none["hint"])
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

    def test_progress_and_fast_flags(self):
        out = OUT / "prog.mp4"
        proc = script("fit.py", self.src, "--duration", "6", "--fast", "--progress", "-o", out)
        self.assertIn("%", proc.stderr)
        self.assertIn("-preset veryfast", proc.stderr, "--fast overrides the preset")
        self.assertClose(probe(str(out))["duration"], 6.0, 0.2)

    # ---------------------------------------------------------------- v0.5: check / scenes / render
    def test_codec_and_quality_resolve_in_one_place(self):
        """1.8 (issue #189 B pre-shipped): --codec / --quality on every re-encoding tool, resolved by
        encoder_args(). hevc on SDR is 8-bit BT.709 HEVC; prores needs a .mov; h264 refuses HDR;
        --quality is the CRF; export keeps its presets; without --codec nothing changes."""
        sys.path.insert(0, str(SCRIPTS))
        try:
            import _common
        finally:
            sys.path.pop(0)
        out = OUT / "codec_hevc.mp4"
        d = json.loads(script("fit.py", self.src, "--width", "320", "--codec", "hevc", "--quality", "30", "-o", out, "--fast", "--json", "--overwrite").stdout)
        self.assertEqual(d["status"], "completed")
        m = probe(str(out))
        self.assertEqual(m["video"]["codec"], "hevc")
        self.assertIn("yuv420p", m["video"].get("pix_fmt", "yuv420p"))
        self.assertTrue(any("-crf 30" in c for c in d["commands"]), d["commands"])
        # prores wants a .mov: .mp4 is refused before ffmpeg runs, .mov works
        d = json.loads(script("fit.py", self.src, "--width", "320", "--codec", "prores", "-o", OUT / "codec_prores.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn(".mov", d["error"]["hint"])
        mov = OUT / "codec_prores.mov"
        script("fit.py", self.src, "--width", "320", "--codec", "prores", "-o", mov, "--fast", "--json", "--overwrite")
        self.assertEqual(probe(str(mov))["video"]["codec"], "prores")
        # h264 cannot carry HDR; hevc keeps it
        d = json.loads(script("fit.py", self.hdr, "--width", "320", "--codec", "h264", "-o", OUT / "codec_hdr_h264.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("to-sdr", d["error"]["hint"])
        hdr_out = OUT / "codec_hdr_hevc.mp4"
        script("fit.py", self.hdr, "--width", "320", "--codec", "hevc", "-o", hdr_out, "--fast", "--json", "--overwrite")
        self.assertTrue(probe(str(hdr_out))["video"]["hdr"])
        # av1 when the build has an encoder, a missing_tool refusal otherwise
        av1 = OUT / "codec_av1.mp4"
        proc = script("fit.py", self.src, "--width", "320", "--codec", "av1", "-o", av1, "--fast", "--json", "--overwrite", expect_fail=not (_common.ffmpeg_encoders() & {"libsvtav1", "libaom-av1"}))
        d = json.loads(proc.stdout)
        if d["status"] == "completed":
            self.assertEqual(probe(str(av1))["video"]["codec"], "av1")
        else:
            self.assertEqual(d["error"]["kind"], "missing_tool")
        # --quality bounds follow the codec; export refuses --codec
        d = json.loads(script("fit.py", self.src, "--width", "320", "--quality", "60", "-o", out, "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        proc = script("export.py", self.src, "--preset", "x", "--codec", "hevc", "-o", OUT / "codec_export.mp4", "--json", expect_fail=True)
        self.assertIn("--codec", proc.stderr)  # argparse: the preset decides, the flag is not offered (review 7)
        self.assertNotIn("--codec", script("export.py", "--help").stdout)
        # review 7: prores without -o would have failed inside ffmpeg (mp4 cannot hold it)
        d = json.loads(script("fit.py", self.src, "--width", "320", "--codec", "prores", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        self.assertIn("-o NAME.mov", d["error"]["hint"])
        # review 7: cut's lossless path used to keep the source codec under --codec
        cutout = OUT / "codec_cut.mp4"
        script("cut.py", self.src, "--start", "0", "--end", "2", "--codec", "hevc", "-o", cutout, "--fast", "--json", "--overwrite")
        self.assertEqual(probe(str(cutout))["video"]["codec"], "hevc")
        # review 7: waveform.py built its own x264 line and ignored the flag
        wf = OUT / "codec_wave.mp4"
        script("waveform.py", self.src, "--codec", "hevc", "-o", wf, "--fast", "--json", "--overwrite")  # source.mp4: c_tone.wav is a test_contract fixture
        self.assertEqual(probe(str(wf))["video"]["codec"], "hevc")
        # review 7: the av1 bound is named in the --quality message, and HDR hevc --quality 51 does not overflow
        d = json.loads(script("fit.py", self.src, "--width", "320", "--codec", "av1", "--quality", "70", "-o", out, "--json", expect_fail=True).stdout)
        self.assertIn("63", d["error"]["message"])
        sys.path.insert(0, str(SCRIPTS))
        try:
            import _common as c
        finally:
            sys.path.pop(0)
        args = c.encoder_args("hevc", 51, "medium", {"video": {"hdr": True, "color_transfer": "smpte2084"}})
        self.assertEqual(args[args.index("-crf") + 1], "51")
        self.assertNotIn("-colorspace", c.encoder_args("hevc", 18, "medium", None, keep_bt709=False))
        # the contract lists each --codec encoder once per tool
        spec = json.loads(script("_contract.py", "--json").stdout)
        fit_caps = [o["capability"] for o in next(t for t in spec["tools"] if t["name"] == "fit")["capabilities"]["optional"]]
        self.assertEqual(len(fit_caps), len(set(fit_caps)), fit_caps)
        self.assertNotIn("codec", next(t for t in spec["tools"] if t["name"] == "export")["input_schema"]["properties"])
        # no --codec: the old default line, byte for byte
        d = json.loads(script("fit.py", self.src, "--width", "320", "-o", out, "--fast", "--json", "--overwrite").stdout)
        self.assertTrue(any("libx264" in c for c in d["commands"]))
        # every tool that declares --crf now advertises the two flags
        for name in ("cut", "caption", "overlay", "color", "join", "proxy"):
            h = script(f"{name}.py", "--help").stdout
            self.assertIn("--codec", h, name)
            self.assertIn("--quality", h, name)

    def test_join_width_keeps_aspect(self):
        out = OUT / "join_w.mp4"
        script("join.py", self.src, self.src, "--transition", "none", "--width", "640", "--fast", "-o", out)
        m = probe(str(out))["video"]
        self.assertEqual((m["width"], m["height"]), (640, 360))

    def test_fit_blur_keeps_the_whole_picture_on_a_blurred_border(self):
        """--fit blur: the target aspect, nothing cropped, borders that carry a dimmed copy of the
        picture rather than black, and a centre band that is still the scaled source."""
        out = OUT / "fit_blur.mp4"
        script("fit.py", self.src, "--duration", "3", "--aspect", "9:16", "--fit", "blur",
               "--width", "360", "--fast", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (360, 640))
        top_avg, top_spread = self._region_stats(out, "iw:80:0:0")
        self.assertGreater(top_avg, 10, f"blurred border is black: {top_avg}")
        self.assertGreater(top_spread, 8, f"blurred border is flat: {top_spread}")
        # the centre band is the fitted source: 360x202 sits at y=(640-202)/2
        ref = OUT / "fit_blur_ref.mp4"
        script("fit.py", self.src, "--duration", "3", "--width", "360", "--fast", "-o", ref)
        mid_avg, _ = self._region_stats(out, "iw:180:0:230")
        ref_avg, _ = self._region_stats(ref, "iw:180:0:10")
        self.assertClose(mid_avg, ref_avg, 12, "the centre of a blur fit is the scaled source")
        # the darkening is an eq on code values: a -15 % perceptual dim on SDR, something else on
        # PQ/HLG, so an HDR source keeps its background at its own levels (review 12)
        sdr_plan = json.loads(script("fit.py", self.src, "--aspect", "9:16", "--fit", "blur",
                                     "--dry-run", "--json", "-o", str(OUT / "blur_sdr.mp4")).stdout)
        hdr_plan = json.loads(script("fit.py", self.hdr, "--aspect", "9:16", "--fit", "blur",
                                     "--dry-run", "--json", "-o", str(OUT / "blur_hdr.mp4")).stdout)
        self.assertTrue(any("eq=brightness" in c for c in sdr_plan["commands"]))
        self.assertTrue(any("boxblur" in c for c in hdr_plan["commands"]))
        self.assertFalse(any("eq=brightness" in c for c in hdr_plan["commands"]),
                         "an HDR source must not be dimmed by an SDR-shaped eq")

    def test_join_list_checks_every_segment_before_joining(self):
        """Reported by a user generating shorts on a VPS: TTS writes one audio file per line,
        a concat step joins them, and one failed TTS call left a gap that emptied the list and
        crashed the whole run. `--list` reads the segments, and every missing, empty or
        unreadable one is named in a single refusal (kind input, nothing run) instead of being
        found one rerun at a time; `--on-missing skip` joins the rest and reports what it left out."""
        d = OUT / "join_list"
        d.mkdir(exist_ok=True)
        for i in (1, 2, 4):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"sine=frequency={300 * i}:sample_rate=24000", "-t", "1.5", d / f"line{i}.wav")
        (d / "line5.wav").write_bytes(b"")             # a TTS call that created its file and then failed
        (d / "line6.wav").write_bytes(b"not audio")    # a download that saved an error page
        (d / "parts.txt").write_text("line1.wav\n# the TTS step's own comment\n\nline2.wav\nline3.wav\n"
                                     "file 'line4.wav'\nline5.wav\nline6.wav\n", encoding="utf-8")
        proc = script("join.py", "--list", d / "parts.txt", "--transition", "none", "--json",
                      "-o", d / "voice_fail.wav", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["error"]["kind"], doc["commands"]), ("input", []))
        self.assertEqual([(p["index"], Path(p["path"]).name) for p in doc["problems"]],
                         [(2, "line3.wav"), (4, "line5.wav"), (5, "line6.wav")], "every problem, in list order")
        self.assertEqual([p["reason"].split(":")[0] for p in doc["problems"]], ["missing", "empty (0 bytes)", "unreadable"])
        self.assertIn("--on-missing skip", doc["error"]["hint"])
        self.assertFalse((d / "voice_fail.wav").exists())
        doc = json.loads(script("join.py", "--list", d / "parts.txt", "--transition", "none", "--on-missing", "skip",
                                "--json", "-o", d / "voice.wav").stdout)
        self.assertEqual((doc["status"], doc["clips"], doc["verified"]), ("completed", 3, True))
        self.assertAlmostEqual(doc["probe"]["duration"], 4.5, delta=0.05)
        self.assertEqual([Path(p["path"]).name for p in doc["skipped"]], ["line3.wav", "line5.wav", "line6.wav"])
        # the crash itself: an upstream step wrote an empty list
        (d / "empty.txt").write_text("\n# nothing\n", encoding="utf-8")
        proc = script("join.py", "--list", d / "empty.txt", "-o", d / "x.wav", "--json", expect_fail=True)
        self.assertIn("names no segments", json.loads(proc.stdout)["error"]["message"])
        # skipping everything but one leaves nothing to join
        (d / "one.txt").write_text("line1.wav\nline3.wav\n", encoding="utf-8")
        proc = script("join.py", "--list", d / "one.txt", "--on-missing", "skip", "-o", d / "y.wav", "--json", expect_fail=True)
        self.assertEqual([Path(p["path"]).name for p in json.loads(proc.stdout)["skipped"]], ["line3.wav"])
        script("join.py", d / "line1.wav", "--list", d / "parts.txt", "-o", d / "z.wav", expect_fail=True)
        # a clean join reports an empty skipped list, not a missing key
        doc = json.loads(script("join.py", d / "line1.wav", d / "line2.wav", "--transition", "none",
                                "--json", "-o", d / "clean.wav").stdout)
        self.assertEqual(doc["skipped"], [])

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

    def test_crf_is_gone_and_quality_keeps_its_default(self):
        """2.0 (deprecated in 1.10.0): --crf is no longer an alias of --quality on the re-encoding
        tools -- argparse refuses it -- and --quality's default is what --crf's was (18, proxy 30).
        export.py keeps its own --crf: its preset chooses the encoder, so it has no --quality."""
        gone = script("cut.py", self.src, "--start", "0", "--end", "1", "--crf", "20", "--dry-run",
                      "-o", str(OUT / "crf_gone.mp4"), expect_fail=True)
        self.assertIn("unrecognized arguments: --crf", gone.stderr)
        self.assertIn("default 18", " ".join(script("cut.py", "--help").stdout.split()))
        self.assertIn("default 30", " ".join(script("proxy.py", "--help").stdout.split()))
        doc = json.loads(script("cut.py", self.src, "--start", "0", "--end", "1", "--accurate", "--dry-run",
                                "-o", str(OUT / "crf_default.mp4"), "--json").stdout)
        self.assertIn("-crf 18", " ".join(doc["commands"]))
        self.assertIn("--crf", script("export.py", "--help").stdout)

    def test_json_brief_is_a_shorter_json_with_the_same_verdict(self):
        """1.11.0 token diet: `--json-brief` is additive -- the same success document with the
        probe summarised, the command lines counted and the per-step verification list dropped.
        `--json` itself must be untouched, so both are run on the same edit and compared."""
        full = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "-o", str(OUT / "brief_full.mp4"), "--json").stdout)
        brief = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "-o", str(OUT / "brief_short.mp4"), "--json-brief").stdout)
        self.assertEqual(set(full) - set(brief), {"probe", "verification"}, "only the bulky keys go")
        self.assertEqual(set(brief) - set(full), {"summary"})
        self.assertEqual(brief["status"], "completed")
        self.assertEqual(brief["dry_run"], full["dry_run"])
        self.assertEqual(brief["verified"], full["verified"])
        self.assertNotIn("probe", brief)
        self.assertNotIn("verification", brief)
        self.assertEqual(brief["commands"], len(full["commands"]), "commands is the count, not the list")
        summary = brief["summary"]
        self.assertEqual(summary["width"], full["probe"]["video"]["width"])
        self.assertEqual(summary["height"], full["probe"]["video"]["height"])
        self.assertEqual(summary["vcodec"], full["probe"]["video"]["codec"])
        self.assertEqual(summary["acodec"], full["probe"]["audio"]["codec"])
        self.assertAlmostEqual(summary["duration_s"], full["probe"]["duration"], places=2)
        for key in ("precision", "reencoded", "expected_duration"):
            self.assertEqual(brief[key], full[key], f"{key}: the tool's own keys survive the diet")
        self.assertLess(len(json.dumps(brief)), len(json.dumps(full)) / 2, "the point of the flag is fewer bytes")

    def test_json_brief_failure_is_the_usual_failure_document(self):
        """A failure must not be trimmed: die() prints the same document with or without the flag,
        so a caller never loses the error kind, message or hint by asking for brevity."""
        proc = script("cut.py", str(OUT / "does_not_exist.mp4"), "--start", "0", "--end", "1", "--json-brief", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "failed")
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertTrue(doc["error"]["message"])
        self.assertNotIn("summary", doc)

    # --------------------------------------------------- 1.17: beat-snapped cuts (cut.py --snap)
    def test_cut_snap_beats_moves_the_points_to_measured_beats(self):
        out = OUT / "snap_cut.mp4"
        data = json.loads(script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01",
                                 "--snap", "beats", "-o", out, "--json").stdout)
        snap = data["snap"]
        self.assertEqual(snap["mode"], "beats")
        self.assertEqual(snap["source"], "measured")
        self.assertEqual(snap["snapped"], 2)
        self.assertEqual(len(snap["moved"]), 2)       # never more points than were asked for
        self.assertAlmostEqual(snap["tempo_bpm"], 120.0, delta=2.0)
        for row in snap["moved"]:
            self.assertLessEqual(abs(row["delta"]), snap["tolerance"])
        # the cut lands on a whole number of beats
        span = snap["moved"][1]["to"] - snap["moved"][0]["to"]
        beats = span / (60.0 / snap["tempo_bpm"])
        self.assertLess(abs(beats - round(beats)), 0.05)
        # container duration, not the cut: AAC packs audio in 1024-sample frames (21 ms at
        # 48 kHz) and ffmpeg 5.1 pads the last one, so allow a few frames of slack
        self.assertLess(abs(data["output_duration"] - span), 0.1)

    def test_cut_snap_beats_moves_only_onto_onset_supported_points(self):
        """The grid is regular by construction, so it runs on through a passage with no music.
        A cut asked for inside that passage is NOT moved: the only points this tool may snap to
        are the ones a measured onset marks."""
        clip = OUT / "beats_half.mp4"
        if not clip.exists():
            # 12 s: a 120 BPM click for the first 5 s, then silence
            click = "0.8*sin(2*PI*880*t)*lt(mod(t\\,0.5)\\,0.04)*lt(t\\,5)"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", f"aevalsrc='{click}':s=48000",
               "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", clip)
        data = json.loads(script("cut.py", clip, "--start", "2.03", "--end", "9.01",
                                 "--snap", "beats", "-o", OUT / "snap_half.mp4",
                                 "--json").stdout)
        snap = data["snap"]
        self.assertEqual(snap["grid"], "supported")
        self.assertLess(snap["grid_points"], 24)     # fewer than the full 12 s grid
        # the in point sits in the music and moves; the out point sits in the silence and does not
        self.assertTrue(snap["moved"][0]["snapped"])
        self.assertFalse(snap["moved"][1]["snapped"])
        self.assertEqual(snap["moved"][1]["to"], snap["moved"][1]["from"])
        self.assertEqual(snap["snapped"], 1)

    def test_cut_snap_beats_refuses_a_zero_confidence_floor(self):
        r = script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01", "--snap", "beats",
                   "--min-confidence", "0", "-o", OUT / "snap_zero.mp4", "--json",
                   expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--min-confidence", err["message"])

    def test_cut_snap_source_without_a_supported_list_is_refused(self):
        """A document from an older build lists beats but cannot say which of them an onset
        supports. An unknown subset is not an empty one -- and it is not a measurement either."""
        doc = OUT / "snap_old.json"
        doc.write_text(json.dumps({"beats": [1.0, 2.0, 3.0],
                                   "beat_grid": {"tempo_bpm": 120.0, "confidence": 0.9}}),
                       encoding="utf-8")
        r = script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01", "--snap", "beats",
                   "--snap-source", doc, "-o", OUT / "snap_old.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_cut_snap_source_with_no_tempo_is_refused(self):
        doc = OUT / "snap_notempo.json"
        doc.write_text(json.dumps({"beats": [1.0, 2.0],
                                   "beat_grid": {"tempo_bpm": None, "confidence": 0.9,
                                                 "supported_beats": [1.0, 2.0]}}),
                       encoding="utf-8")
        r = script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01", "--snap", "beats",
                   "--snap-source", doc, "-o", OUT / "snap_nt.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_cut_snap_beats_refuses_a_whole_file_copy_spelled_as_a_time(self):
        """`--start 0:00` is the same whole-file copy as no --start at all; a string comparison
        against "0" let it through and the run then shortened the file at the far end."""
        for start in ("0:00", "0.0", "00:00:00"):
            with self.subTest(start=start):
                r = script("cut.py", self._beats(), "--start", start, "--snap", "beats",
                           "-o", OUT / "snap_wholetime.mp4", "--json", expect_fail=True)
                err = json.loads(r.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn("--snap", err["message"])

    def test_cut_snap_beats_refuses_a_grid_it_cannot_measure(self):
        """Never fabricate: without a measurable pulse the points are not moved to invented
        times -- the run refuses and names --snap none."""
        out = OUT / "snap_refuse.mp4"
        if out.exists():
            out.unlink()
        r = script("cut.py", self._silent_clip(), "--start", "2.03", "--end", "6.01",
                   "--snap", "beats", "-o", out, "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--snap none", err["message"])
        self.assertIn("confidence", err["message"])
        self.assertFalse(out.exists())

    def test_cut_snap_beats_refuses_without_audio(self):
        mute = OUT / "snap_mute.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self._beats(),
           "-an", "-c:v", "copy", mute)
        r = script("cut.py", mute, "--start", "2.03", "--end", "6.01", "--snap", "beats",
                   "-o", OUT / "snap_mute_cut.mp4", "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--snap none", err["message"])

    def test_cut_snap_beats_refuses_a_whole_file_copy(self):
        r = script("cut.py", self._beats(), "--snap", "beats",
                   "-o", OUT / "snap_whole.mp4", "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--snap", err["message"])

    def test_cut_snap_source_takes_the_grid_from_a_scenes_document(self):
        doc = OUT / "snap_grid.json"
        doc.write_text(script("scenes.py", self._beats(), "--beats", "--json").stdout,
                       encoding="utf-8")
        data = json.loads(script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01",
                                 "--snap", "beats", "--snap-source", doc,
                                 "-o", OUT / "snap_src.mp4", "--json").stdout)
        self.assertEqual(data["snap"]["source"], str(doc))
        self.assertEqual(data["snap"]["snapped"], 2)

    def test_cut_without_snap_reports_no_snap_key(self):
        data = json.loads(script("cut.py", self._beats(), "--start", "2.03", "--end", "6.01",
                                 "-o", OUT / "snap_off.mp4", "--json").stdout)
        self.assertIsNone(data.get("snap"))

    # ------------------------------------------------ 1.17: filler words (silence.py --filler)
    def _words_json(self, name="words.json", lang="en", words=None):
        path = OUT / name
        words = words if words is not None else [
            ("So", 0.2, 0.5), ("um", 0.6, 0.8), ("this", 1.0, 1.3), ("uh", 2.2, 2.45),
            ("umbrella", 3.0, 3.6), ("erm", 4.1, 4.35), ("works", 5.0, 5.4)]
        path.write_text(json.dumps({"language": lang, "segments": [
            {"words": [{"word": w, "start": a, "end": b} for w, a, b in words]}]}),
            encoding="utf-8")
        return path

    def test_filler_removes_only_the_timed_filler_words(self):
        out = OUT / "filler_out.mp4"
        # --margin 0: the filler words in _words_json() are ~0.2-0.3s wide with a 0.02s pad, and
        # the default 0.15s margin trims each side of *every* removal span (silence or filler
        # alike) -- with no generic silence to also cut, a margin comparable to the span itself
        # would swallow it. 0 isolates what this test is checking: filler-only removal.
        data = json.loads(script("silence.py", self._gappy(), "--filler",
                                 "--words", self._words_json(), "--margin", "0",
                                 "-o", out, "--json").stdout)
        fil = data["filler"]
        self.assertEqual(fil["removed_count"], 3)
        self.assertEqual(fil["lang"], "en")
        self.assertEqual(fil["list"], "builtin")
        self.assertEqual(fil["word_timings"], 7)
        self.assertEqual(sorted(fil["removed_words"]), ["erm", "uh", "um"])
        self.assertIn("removed_seconds_total", data)
        self.assertGreater(fil["removed_seconds"], 0)
        # --filler alone (no --speech-aware) removes only the filler spans: no generic silence
        self.assertEqual(data["silences"], [])
        self.assertAlmostEqual(data["removed_seconds"], 0.0, delta=0.01)
        # "umbrella" is not "um": whole tokens only
        self.assertNotIn("umbrella", fil["removed_words"])
        m = probe(str(out))
        self.assertLess(m["duration"], data["input_duration"])

    def _talk_with_a_gap(self):
        """10 s: tone, 4 s of silence in the middle, tone. A filler word placed at 3.0 s sits
        INSIDE that silence, which is where a mumbled "um" usually is."""
        talk = OUT / "talk_gap.m4a"
        if not talk.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "aevalsrc='0.5*sin(2*PI*440*t)*(lt(t\\,2)+gt(t\\,6))':s=48000",
               "-t", "10", talk)
        return talk

    def test_filler_alone_does_not_jump_cut_unrelated_silence(self):
        """The 1.18.5 regression (fw1/fw3): --filler without --speech-aware must remove ONLY the
        timed filler-word spans -- not every ordinary silence gap in the file. Previously the
        `else: silences = detect(...)` branch ran unconditionally, so a plain --filler run also
        jump-cut the unrelated 4s dead-air gap in this fixture, even though only the filler word
        was asked for. `silences` must now be empty and `removed_seconds` (the silence-only
        figure) must be ~0; only `removed_seconds_total` (which includes the filler span) may be
        nonzero."""
        talk = self._talk_with_a_gap()
        words = OUT / "words_inside.json"
        # the filler word sits INSIDE the unrelated 4s dead-air gap (2-6s) -- the worst case for
        # the old bug, since the filler span and the silence gap overlap
        words.write_text(json.dumps({"language": "en", "segments": [
            {"words": [{"word": "um", "start": 3.0, "end": 3.2}]}]}), encoding="utf-8")
        plain = json.loads(script("silence.py", talk, "--list", "--json").stdout)
        withf = json.loads(script("silence.py", talk, "--filler", "--filler-list",
                                  "--words", words, "--margin", "0", "--json").stdout)
        # the plain run (no --filler) does cut the 4s dead-air gap, as always
        self.assertGreater(plain["removed_seconds"], 3.0)
        # --filler alone runs no generic silence detection at all
        self.assertEqual(withf["silences"], [])
        self.assertAlmostEqual(withf["removed_seconds"], 0.0, delta=0.01)
        # only the filler word's own (padded) span is removed -- far less than the 4s gap
        self.assertGreater(withf["removed_seconds_total"], 0.0)
        self.assertLess(withf["removed_seconds_total"], 1.0)

    def test_removed_seconds_keeps_its_silence_only_meaning(self):
        """A caller reading `removed_seconds` since 1.0 asked how much dead air went.
        `removed_seconds_total` is the additive figure that also covers filler time. With
        --filler alone (no --speech-aware) no dead air is removed at all, so `removed_seconds`
        is 0 and everything reported comes from `removed_seconds_total`."""
        talk = self._talk_with_a_gap()
        words = OUT / "words_outside.json"
        # a filler word in the SPEECH, well away from the silence gap
        words.write_text(json.dumps({"language": "en", "segments": [
            {"words": [{"word": "um", "start": 0.5, "end": 0.9}]}]}), encoding="utf-8")
        withf = json.loads(script("silence.py", talk, "--filler", "--filler-list",
                                  "--words", words, "--json").stdout)
        self.assertAlmostEqual(withf["removed_seconds"], 0.0, delta=0.01)
        self.assertGreater(withf["removed_seconds_total"], withf["removed_seconds"])

    def test_keep_ranges_is_monotone_with_a_nested_span(self):
        """keep_ranges walks one cursor forward; a nested span used to rewind it."""
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        silence = importlib.import_module("silence")
        nested = silence.keep_ranges(sorted([(1.0, 3.0), (1.5, 1.8)]), 10, 0.05, 0.2)
        plain = silence.keep_ranges([(1.0, 3.0)], 10, 0.05, 0.2)
        self.assertEqual(nested, plain)
        self.assertEqual(silence.merge_spans([(1.0, 3.0), (1.5, 1.8), (4.0, 4.5), (4.5, 5.0)]),
                         [(1.0, 3.0), (4.0, 5.0)])
        # an unsorted input is sorted on the way in
        self.assertEqual(silence.keep_ranges([(4.0, 5.0), (1.0, 2.0)], 10, 0.05, 0.2),
                         silence.keep_ranges([(1.0, 2.0), (4.0, 5.0)], 10, 0.05, 0.2))

    def test_filler_list_writes_nothing(self):
        out = OUT / "filler_nothing.mp4"
        if out.exists():
            out.unlink()
        data = json.loads(script("silence.py", self._gappy(), "--filler", "--filler-list",
                                 "--words", self._words_json(), "-o", out, "--json").stdout)
        self.assertEqual(data["filler"]["removed_count"], 3)
        self.assertFalse(out.exists())

    def test_filler_keep_and_extra_change_the_list(self):
        kept = json.loads(script("silence.py", self._gappy(), "--filler", "--filler-list",
                                 "--filler-keep", "um,uh", "--words", self._words_json(),
                                 "--json").stdout)["filler"]
        self.assertEqual(kept["removed_words"], ["erm"])
        extra = json.loads(script("silence.py", self._gappy(), "--filler", "--filler-list",
                                  "--filler-extra", "so", "--words", self._words_json(),
                                  "--json").stdout)["filler"]
        self.assertIn("so", extra["removed_words"])

    # ------------------------------------------------ 1.18.0: silence.py --speech-aware
    def _breathy(self):
        """10 s: speech 0-3s, a 0.25 s breath (well under the 0.6 s default --min-silence),
        speech 3.25-6s, a 1 s sentence-boundary pause 6-7s, speech 7-10s."""
        clip = OUT / "breathy.mp4"
        if not clip.exists():
            expr = "0.5*sin(2*PI*440*t)*(lt(t\\,3)+between(t\\,3.25\\,6)+gt(t\\,7))"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"aevalsrc='{expr}':s=48000", "-t", "10", clip)
        return clip

    def test_speech_aware_keeps_a_short_breath_and_cuts_the_sentence_boundary(self):
        data = json.loads(script("silence.py", self._breathy(), "--speech-aware", "--list",
                                 "--margin", "0.05", "--json").stdout)
        sa = data["speech_aware"]
        self.assertEqual(sa["breaths_kept"], 1)
        self.assertAlmostEqual(sa["breaths"][0][0], 3.0, delta=0.1)
        self.assertAlmostEqual(sa["breaths"][0][1], 3.25, delta=0.1)
        # the sentence-boundary pause (6-7s) is the only one removed
        self.assertEqual(len(data["silences"]), 1)
        self.assertAlmostEqual(data["silences"][0][0], 6.0, delta=0.1)

    def test_speech_aware_without_the_flag_would_have_cut_the_breath_too(self):
        """With a --min-silence short enough to catch the breath, the plain (non-speech-aware)
        run removes it; --speech-aware is what keeps it."""
        plain = json.loads(script("silence.py", self._breathy(), "--min-silence", "0.2",
                                  "--threshold", "-35", "--list", "--json").stdout)
        aware = json.loads(script("silence.py", self._breathy(), "--min-silence", "0.6",
                                  "--speech-aware", "--list", "--json").stdout)
        self.assertEqual(len(plain["silences"]), 2)   # breath + sentence pause, both cut
        self.assertEqual(len(aware["silences"]), 1)   # only the sentence pause
        self.assertEqual(aware["speech_aware"]["breaths_kept"], 1)

    def test_speech_aware_writes_an_edl_like_the_plain_flag(self):
        edl = OUT / "speech_aware.edl"
        script("silence.py", self._breathy(), "--speech-aware", "--edl", edl, "--list", "--json")
        lines = edl.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        for line in lines:
            a, b = line.split("-")
            self.assertLess(float(a), float(b))

    def test_speech_aware_composes_with_filler_into_one_removal_list(self):
        """The trickiest part of 1.18.0: --speech-aware and --filler must flow through the same
        keep_ranges() and produce one removal list, not two independent cuts. A filler word
        placed inside the kept breath must still be removed -- and the breath must still not be
        cut just because --filler ran."""
        clip = self._breathy()
        words = OUT / "words_breath.json"
        # a filler word squarely inside the kept breath (3.0-3.25s)
        words.write_text(json.dumps({"language": "en", "segments": [
            {"words": [{"word": "um", "start": 3.05, "end": 3.15}]}]}), encoding="utf-8")
        out = OUT / "speech_aware_filler.mp4"
        data = json.loads(script("silence.py", clip, "--speech-aware", "--filler",
                                 "--words", words, "-o", out, "--margin", "0.02", "--json").stdout)
        self.assertIn("speech_aware", data)
        self.assertIn("filler", data)
        # the breath is still reported as kept by --speech-aware...
        self.assertEqual(data["speech_aware"]["breaths_kept"], 1)
        # ...but the filler word inside it is removed anyway: one composed list, not two cuts
        # that ignore each other. removed_seconds_total covers both the sentence pause and the
        # filler word.
        self.assertGreater(data["removed_seconds_total"], data["removed_seconds"])
        m = probe(str(out))
        self.assertLess(m["duration"], data["input_duration"])

    def test_filler_warns_about_a_japanese_discourse_marker(self):
        words = [("\u305d\u308c\u306f", 0.2, 0.5), ("\u306a\u3093\u304b", 0.6, 0.85), ("\u3044\u3044", 1.0, 1.3)]
        data = json.loads(script("silence.py", self._gappy(), "--filler", "--filler-list",
                                 "--words", self._words_json("words_ja.json", "ja", words),
                                 "--json").stdout)
        fil = data["filler"]
        self.assertEqual(fil["lang"], "ja")
        self.assertIn("\u306a\u3093\u304b", fil["removed_words"])
        self.assertTrue(any("\u306a\u3093\u304b" in w for w in fil["warnings"]))

    def test_filler_transcribe_uses_measured_word_timings(self):
        """e2e with the engine bridge mocked: --transcribe must reach filler_spans with real
        per-word start/end pairs. The bridge is mocked because the suite must pass on a machine
        with no whisper at all -- which is what CI is."""
        shim = OUT / "asr_shim"
        shim.mkdir(exist_ok=True)
        (shim / "sitecustomize.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.environ['FFSKILL_SCRIPTS'])\n"
            "import _common.asr as asr, _common as c\n"
            "def fake(video, language=None, model='base', audio_stream=0):\n"
            "    return ([{'word': 'So', 'start': 0.2, 'end': 0.5},\n"
            "             {'word': 'um', 'start': 0.6, 'end': 0.8},\n"
            "             {'word': 'this', 'start': 1.0, 'end': 1.3},\n"
            "             {'word': 'uh', 'start': 2.2, 'end': 2.45}], 'faster-whisper')\n"
            "asr.transcribe_words = fake\n"
            "c.transcribe_words = fake\n",
            encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(shim), FFSKILL_SCRIPTS=str(SCRIPTS))
        r = sh(sys.executable, SCRIPTS / "silence.py", self._gappy(), "--filler",
               "--transcribe", "--filler-list", "--json", env=env)
        fil = json.loads(r.stdout)["filler"]
        self.assertEqual(fil["engine"], "faster-whisper")
        self.assertEqual(fil["word_timings"], 4)
        self.assertEqual(sorted(fil["removed_words"]), ["uh", "um"])
        for span in fil["removed"]:
            self.assertLess(span["start"], span["end"])

    def test_filler_transcribe_refuses_when_the_engine_gives_no_word_timings(self):
        """An engine that runs but whose build has no word timestamps must say exactly that and
        name --words -- not report an empty removal as a success."""
        shim = OUT / "asr_shim_empty"
        shim.mkdir(exist_ok=True)
        (shim / "sitecustomize.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.environ['FFSKILL_SCRIPTS'])\n"
            "import _common.asr as asr, _common as c\n"
            "def fake(video, language=None, model='base', audio_stream=0):\n"
            "    return ([], 'whisper.cpp')\n"
            "asr.transcribe_words = fake\n"
            "c.transcribe_words = fake\n",
            encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(shim), FFSKILL_SCRIPTS=str(SCRIPTS))
        out = OUT / "filler_nowords.mp4"
        if out.exists():
            out.unlink()
        r = sh(sys.executable, SCRIPTS / "silence.py", self._gappy(), "--filler",
               "--transcribe", "-o", out, "--json", expect_fail=True, env=env)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("whisper.cpp", err["message"])
        self.assertIn("--words", err["message"])
        self.assertFalse(out.exists())

    def test_filler_pad_must_not_be_negative(self):
        """A negative pad turns each span inside out and filler_spans then drops them all, so the
        run would report a successful removal of nothing."""
        r = script("silence.py", self._gappy(), "--filler", "--filler-pad", "-0.5",
                   "--words", self._words_json(), "-o", OUT / "filler_pad.mp4",
                   "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_filler_refuses_without_a_transcript(self):
        out = OUT / "filler_refuse.mp4"
        if out.exists():
            out.unlink()
        r = script("silence.py", self._gappy(), "--filler", "-o", out, "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--words", err["message"])
        self.assertIn("--transcribe", err["message"])
        self.assertFalse(out.exists())

    def test_filler_refuses_a_segment_only_transcript(self):
        doc = OUT / "segments_only.json"
        doc.write_text(json.dumps({"language": "en", "segments": [
            {"start": 0.0, "end": 2.0, "text": "So um this"}]}), encoding="utf-8")
        r = script("silence.py", self._gappy(), "--filler", "--words", doc,
                   "-o", OUT / "filler_seg.mp4", "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("word timings", err["message"])

    def test_filler_refuses_when_no_whisper_is_installed(self):
        """The eval image has no engine; the refusal must name the three installs. PATH is
        stripped so the test does not depend on whether this machine has one."""
        try:
            import faster_whisper  # noqa: F401
            self.skipTest("faster-whisper is installed on this machine; the absent-engine path "
                          "cannot be exercised without uninstalling it")
        except ImportError:
            pass
        # A PATH with ffmpeg/ffprobe and nothing else: stripping PATH outright would make the
        # run fail on ffprobe long before it reached the engine probe.
        if platform.system() == "Windows":
            # A symlink needs a privilege here, and a COPIED ffmpeg.exe cannot find its sibling
            # DLLs -- so neither branch of the shim works on Windows, and pretending one does
            # would make this a test that passes without exercising anything. The refusal it
            # covers is platform-independent (it is a PATH/import probe in _common/asr.py), and
            # the mocked-bridge tests above cover the same message on every OS.
            self.skipTest("no way to build a PATH shim on Windows: a copied ffmpeg.exe loses "
                          "its DLLs and a symlink needs a privilege")
        shim = OUT / "no_whisper_path"
        shim.mkdir(exist_ok=True)
        for tool in ("ffmpeg", "ffprobe"):
            real = shutil.which(tool)
            if not real:
                self.skipTest(f"{tool} not on PATH")
            link = shim / Path(real).name
            if link.exists():
                continue
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError, AttributeError):
                self.skipTest("cannot symlink ffmpeg into a PATH shim on this machine")
        env = dict(os.environ, PATH=str(shim))
        out = OUT / "filler_nowhisper.mp4"
        if out.exists():
            out.unlink()
        r = sh(sys.executable, SCRIPTS / "silence.py", self._gappy(), "--filler", "--transcribe",
               "-o", out, "--json", expect_fail=True, env=env)
        message = json.loads(r.stdout)["error"]["message"]
        for engine in ("whisper.cpp", "faster-whisper", "openai-whisper"):
            self.assertIn(engine, message)
        self.assertFalse(out.exists())

    def test_silence_without_filler_is_unchanged(self):
        data = json.loads(script("silence.py", self._gappy(), "--list", "--json").stdout)
        self.assertNotIn("filler", data)
        self.assertNotIn("removed_seconds_total", data)


class FillerSpansTests(unittest.TestCase):
    """1.17: which words become removal spans, as pure arithmetic on measured timings."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        self.D = importlib.import_module("_common.decision")

    def _w(self, *triples):
        return [{"word": w, "start": a, "end": b} for w, a, b in triples]

    def test_matches_whole_tokens_only(self):
        spans = self.D.filler_spans(
            self._w(("umbrella", 0.0, 0.4), ("Umm,", 1.0, 1.2), ("UM", 2.0, 2.15)),
            self.D.FILLER_WORDS["en"] | {"umm"})
        self.assertEqual([s["word"] for s in spans], ["umm", "um"])

    def test_never_without_timings(self):
        self.assertEqual(self.D.filler_spans([{"word": "um"}], {"um"}), [])
        self.assertEqual(self.D.filler_spans([{"word": "um", "start": 2.0, "end": 1.0}], {"um"}), [])
        self.assertEqual(self.D.filler_spans([{"word": "um", "start": None, "end": 1.0}], {"um"}), [])

    def test_merges_adjacent_spans(self):
        close = self.D.filler_spans(self._w(("um", 1.0, 1.1), ("uh", 1.13, 1.25)),
                                    {"um", "uh"}, pad=0.0)
        self.assertEqual(len(close), 1)
        apart = self.D.filler_spans(self._w(("um", 1.0, 1.1), ("uh", 1.3, 1.45)),
                                    {"um", "uh"}, pad=0.0)
        self.assertEqual(len(apart), 2)

    def test_rejects_a_long_held_word(self):
        self.assertEqual(self.D.filler_spans(self._w(("uhhh", 1.0, 3.0)), {"uhhh"}), [])

    def test_japanese_list(self):
        ja = self.D.FILLER_WORDS["ja"]
        spans = self.D.filler_spans(
            self._w(("\u3048\u30fc\u3068", 1.0, 1.3), ("\u3042\u306e", 2.0, 2.2), ("\u3042\u306e\u3072\u3068", 3.0, 3.4)), ja)
        self.assertEqual([s["word"] for s in spans], ["\u3048\u30fc\u3068", "\u3042\u306e"])

    def test_like_is_not_a_default_filler_word(self):
        """A discourse marker is a content word: cutting it cuts meaning, which is a judgement
        this skill does not make. It is reachable with --filler-extra and documented."""
        self.assertNotIn("like", self.D.FILLER_WORDS["en"])
        self.assertNotIn("tipo", self.D.FILLER_WORDS["pt"])
        self.assertIn("like", self.D.FILLER_DISCOURSE_MARKERS["en"])

    def test_whisper_cpp_json_becomes_word_timings(self):
        """whisper.cpp --output-json-full: transcription[].tokens[] with MILLISECOND offsets,
        special tokens dropped, and a continuation token glued to the word before it."""
        import importlib
        asr = importlib.import_module("_common.asr")
        doc = OUT / "wcpp.json"
        doc.write_text(json.dumps({"transcription": [{"tokens": [
            {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
            {"text": " So", "offsets": {"from": 200, "to": 500}},
            {"text": " un", "offsets": {"from": 600, "to": 700}},
            {"text": "believable", "offsets": {"from": 700, "to": 1100}},
            {"text": " um", "offsets": {"from": 1200, "to": 1400}},
            {"text": " broken", "offsets": {}},
        ]}]}), encoding="utf-8")
        words = asr._words_from_whisper_cpp_json(str(doc))
        self.assertEqual([w["word"] for w in words], ["So", "unbelievable", "um"])
        self.assertAlmostEqual(words[0]["start"], 0.2, places=6)
        self.assertAlmostEqual(words[1]["end"], 1.1, places=6)      # glued span ends at the tail
        self.assertEqual(asr._words_from_whisper_cpp_json(str(OUT / "nope.json")), [])

    def test_openai_whisper_json_becomes_word_timings(self):
        import importlib
        asr = importlib.import_module("_common.asr")
        doc = OUT / "owhisper.json"
        doc.write_text(json.dumps({"segments": [
            {"words": [{"word": " So", "start": 0.2, "end": 0.5},
                       {"word": " um", "start": 0.6, "end": 0.8},
                       {"word": " bad", "start": None, "end": 1.0}]}]}), encoding="utf-8")
        words = asr._words_from_openai_whisper_json(str(doc))
        self.assertEqual([w["word"] for w in words], ["So", "um"])
        self.assertAlmostEqual(words[1]["start"], 0.6, places=6)

    def test_filler_spans_is_pure(self):
        import unittest.mock
        def boom(*a, **k):
            raise AssertionError("filler_spans ran a subprocess")
        with unittest.mock.patch.object(subprocess, "run", boom), \
             unittest.mock.patch.object(subprocess, "Popen", boom):
            self.assertEqual(len(self.D.filler_spans(self._w(("um", 1.0, 1.2)), {"um"})), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
