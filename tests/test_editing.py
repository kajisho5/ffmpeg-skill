#!/usr/bin/env python3
"""End-to-end tests for cut, fit, crop, join, insert, broll, freeze, pad, speedramp, loop, reverse, sequence, silence, metadata, straighten and sphere.

    python3 tests/test_editing.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import array
import os
import platform
import json
import math
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, SCRIPTS, _is_faststart, exif_rotated_jpeg, frame_rgb, sar_clip, script, sh, tiny_clip  # noqa: E402
from _fixtures import av_offsets_ms, flash_times, make_flash_beep, make_tones_take, stream_spans  # noqa: E402
from _fixtures import frame_lumas, frame_numbers, numbered_clip, pcm_of, plain_clip, stretches  # noqa: E402
from _common import probe  # noqa: E402
import _common  # noqa: E402


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

    def test_cut_segments_join_is_faded_so_it_does_not_click(self):
        """Butting two cuts of a tone left a step in the waveform at the join 14x the tone's own
        largest sample-to-sample change: an audible click. Every join the re-encode makes is now
        faded (--declick-ms, 20 by default); --no-declick keeps the old butt join."""
        tone = OUT / "declick_tone.wav"
        if not tone.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "sine=f=440:d=4:sample_rate=48000", "-c:a", "pcm_s16le", tone)

        def largest_step(path):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-"],
                                 stdout=subprocess.PIPE, check=True).stdout
            pcm = memoryview(raw).cast("h")
            return max(abs(pcm[i + 1] - pcm[i]) for i in range(len(pcm) - 1))

        own = largest_step(tone)
        runs = {}
        for name, extra in (("faded", ()), ("butted", ("--no-declick",))):
            out = OUT / f"declick_{name}.wav"
            runs[name] = json.loads(script("cut.py", tone, "--segments", "0-1.0011,2-3", "--accurate", *extra,
                                           "-o", out, "--json").stdout)
            runs[name]["step"] = largest_step(out)
        self.assertEqual((runs["faded"]["declick_ms"], runs["butted"]["declick_ms"]), (20.0, 0.0))
        self.assertLessEqual(runs["faded"]["step"], own * 1.1, runs)
        self.assertGreater(runs["butted"]["step"], own * 2, runs)
        # nothing to fade without sound, and a fade length that is not a number is refused
        silent = OUT / "declick_silent.mp4"
        if not silent.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "color=c=gray:s=160x120:r=30:d=4", "-c:v", "libx264", silent)
        data = json.loads(script("cut.py", silent, "--segments", "0-1,2-3", "--accurate", "-o",
                                 OUT / "declick_silent_out.mp4", "--json").stdout)
        self.assertIsNone(data["declick_ms"])
        refused = script("cut.py", tone, "--segments", "0-1,2-3", "--accurate", "--declick-ms=nan",
                         "-o", OUT / "declick_nan.wav", expect_fail=True)
        self.assertIn("finite", refused.stderr)

    def test_cut_json_reports_requested_vs_actual_and_mode(self):
        # exact-second cut on a keyframe-aligned GOP: expect a clean lossless copy
        out = OUT / "cut_honest_copy.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--tolerance", "-1", "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertFalse(data["keyframe_snapped"], "3.0: the start is where asked (start_snapped)")
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
        data3 = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "0.02", "--no-edit-list", "-o", out3, "--json").stdout)
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
        # --no-edit-list: the 3.0 default edit list hides the snapped pre-roll, so the start would not move
        data = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "2.0", "--no-edit-list",
                                 "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["keyframe_snapped"])
        self.assertFalse(data["reencoded"])
        actual = probe(str(out))["duration"]
        self.assertAlmostEqual(data["output_duration"], actual, places=2)
        self.assertGreater(abs(data["duration_delta_seconds"]), 0.05, "this scenario must produce a real, visible divergence, not a rounding artefact")
        self.assertAlmostEqual(data["duration_delta_seconds"], data["output_duration"] - data["requested_duration"], places=6)

    def test_cut_json_says_why_it_reencoded_and_how_exact_each_segment_is(self):
        """reencode_reason names every cause, and --codec is named even when --accurate already
        forced the re-encode; segment_precision and least_exact_precision describe the segments."""
        # a clean copy: nothing re-encoded, one segment
        out = OUT / "cut_reasons_copy.mkv"
        data = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "--tolerance", "-1", "-o", out, "--json").stdout)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        self.assertIsNone(data["segment_precision"], "a single segment has no per-segment list")
        self.assertEqual(data["least_exact_precision"], "packet")
        out2 = OUT / "cut_reasons_accurate.mp4"
        data2 = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--accurate", "-o", out2, "--json").stdout)
        self.assertEqual(data2["reencode_reason"], ["requested"])
        self.assertFalse(data2["start_snapped"], "a re-encode starts where asked")
        # .mkv: no edit list can hide the pre-roll, so this copy snaps its start to the keyframe at 0
        # and misses the tight tolerance
        out3 = OUT / "cut_honest_hybrid.mkv"
        data3 = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "0.02", "-o", out3, "--json").stdout)
        self.assertEqual(data3["mode"], "hybrid")
        self.assertEqual(data3["reencode_reason"], ["tolerance"])
        self.assertFalse(data3["keyframe_snapped"])
        self.assertIn(0.0, data3["nearest_keyframes"])
        out4 = OUT / "cut_reasons_segments.mp4"
        data4 = json.loads(script("cut.py", self.src, "--segments", "1-3,6-9", "--accurate", "-o", out4, "--json").stdout)
        self.assertEqual(data4["reencode_reason"], ["requested"])
        self.assertEqual(data4["segment_precision"], ["frame", "frame"])
        self.assertEqual((data4["precision"], data4["least_exact_precision"]), ("frame", "frame"))
        # --codec forces the re-encode, and says so rather than claiming it was asked for
        out5 = OUT / "cut_honest_codec.mp4"
        data5 = json.loads(script("cut.py", self.src, "--start", "2", "--end", "4", "--codec", "hevc", "-o", out5, "--json").stdout)
        self.assertEqual(data5["mode"], "accurate")
        self.assertEqual(data5["reencode_reason"], ["codec"])
        # ...and --codec is still named when --accurate already forced the re-encode
        out6 = OUT / "cut_honest_accurate_codec.mp4"
        data6 = json.loads(script("cut.py", self.src, "--start", "2", "--end", "4", "--accurate", "--codec", "hevc", "-o", out6, "--json").stdout)
        self.assertEqual(data6["reencode_reason"], ["requested", "codec"])

    def test_cut_top_level_precision_is_the_least_exact_segments(self):
        """least_exact_precision is the least exact segment's precision, so a keyframe-snapped copy
        segment is never hidden behind a re-encoded one."""
        sys.path.insert(0, str(SCRIPTS))
        import cut
        self.assertEqual(cut.least_exact(["frame", "packet"]), "packet")
        self.assertEqual(cut.least_exact(["sample", "codec_frame"]), "codec_frame")
        self.assertEqual(cut.least_exact(["sample", "frame"]), "frame")
        self.assertEqual(cut.least_exact(["sample"]), "sample")

    def test_cut_precision_is_the_least_exact_segments_and_keyframe_snapped_is_start_snapped(self):
        """3.0.0: `precision` is least_exact_precision and `keyframe_snapped` is start_snapped (2.x:
        precision_of() for the run, and keyframe_snapped = precision == packet). The run where they
        differed is an audio-only join of a copied and a re-encoded part: precision now says one
        part is only packet-exact. start_snapped is true when any copied start moved, null while
        one is unmeasured (--dry-run), false otherwise."""
        sys.path.insert(0, str(SCRIPTS))
        import cut
        wav = {"audio": {"codec": "pcm_s16le"}}

        def part(precision, reencoded, snapped):
            return {"precision": precision, "reencoded": reencoded, "start_snapped": snapped}
        mixed = cut.report_precision(wav, "out.wav", True, [part("packet", False, False), part("sample", True, False)])
        self.assertEqual((mixed["precision"], mixed["least_exact_precision"]), ("packet", "packet"))
        self.assertEqual(mixed["segment_precision"], ["packet", "sample"])
        self.assertFalse(mixed["keyframe_snapped"])
        copy = cut.report_precision(wav, "out.wav", False, [part("packet", False, False)])
        self.assertEqual((copy["precision"], copy["least_exact_precision"], copy["keyframe_snapped"]), ("packet", "packet", False))
        self.assertIsNone(copy["segment_precision"])
        video = {"video": {"codec": "h264"}}
        self.assertIs(cut.report_precision(video, "o.mp4", False, [part("packet", False, None), part("packet", False, True)])["start_snapped"], True)
        self.assertIsNone(cut.report_precision(video, "o.mp4", False, [part("packet", False, None), part("packet", False, False)])["start_snapped"])
        self.assertIs(cut.report_precision(video, "o.mp4", True, [part("frame", True, False)])["start_snapped"], False)

    def test_cut_start_snapped_is_measured_and_null_under_dry_run(self):
        """start_snapped (and, since 3.0.0, keyframe_snapped) says whether the copied picture
        really starts away from --start. Matroska keeps no edit list, so a copy from 2 s
        starts at the keyframe at 0; a copy from 0 starts where asked; a dry run measures nothing."""
        out = OUT / "cut_start_snapped.mkv"
        data = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--tolerance", "-1", "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["keyframe_snapped"])
        self.assertTrue(data["start_snapped"])
        self.assertFalse(data["edit_list"])
        out2 = OUT / "cut_start_exact.mkv"
        data2 = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "--tolerance", "-1", "-o", out2, "--json").stdout)
        self.assertFalse(data2["keyframe_snapped"])
        self.assertFalse(data2["start_snapped"])
        data3 = json.loads(script("cut.py", self.src, "--start", "2", "--end", "6", "--dry-run", "-o", OUT / "never_snapped.mkv", "--json").stdout)
        self.assertIsNone(data3["start_snapped"], "nothing was cut, so nothing was measured")
        self.assertIsNone(data3["keyframe_snapped"])

    def test_cut_matroska_copy_keyframe_snap_reports_a_real_nonzero_delta(self):
        """The same divergence in Matroska, which has no edit lists: the copy really starts at the
        keyframe before 1.13, and start_snapped says so."""
        out = OUT / "cut_copy_keyframe_snap.mkv"
        data = json.loads(script("cut.py", self.src, "--start", "1.13", "--end", "5.71", "--tolerance", "2.0", "-o", out, "--json").stdout)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["keyframe_snapped"])
        self.assertTrue(data["start_snapped"])
        self.assertFalse(data["edit_list"])
        self.assertFalse(data["reencoded"])
        actual = probe(str(out))["duration"]
        self.assertAlmostEqual(data["output_duration"], actual, places=2)
        self.assertGreater(abs(data["duration_delta_seconds"]), 0.05)
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

    def test_broll_sizes_the_cutaway_to_the_displayed_frame(self):
        """A 1280x720 file tagged 90 degrees is shown 720x1280. The cutaway used to be scaled
        and padded to the stored 1280x180 landscape box and then clipped onto the portrait frame."""
        v = probe(str(self.rot))["video"]
        self.assertIn(v["rotation"], (90, -90, 270, -270))
        dw, dh = v["height"], v["width"]
        doc = json.loads(script("broll.py", self.rot, "--insert", self.src, "--at", "1", "--duration", "1",
                                "--dry-run", "--json", "-o", OUT / "broll_rot.mp4").stdout)
        cmd = " ".join(doc["commands"])
        self.assertIn(f"scale={dw}:{dh}:", cmd)
        self.assertIn(f"pad={dw}:{dh}:", cmd)
        self.assertNotIn(f"scale={v['width']}:{v['height']}:", cmd)

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

    def test_fit_aspect_reads_each_side_as_2_2_1_did(self):
        """fit.py --aspect reads each side with int(), as 2.2.1 did: 2.2.2's shared parser briefly
        refused `+9:16` and `1_6:9`, which int() takes, and `0:9`, which 2.2.1 ran as no aspect
        (the source frame). A patch release refuses nothing fit.py took."""
        from fractions import Fraction
        from _common import aspect_ratio
        self.assertEqual(aspect_ratio("+9:16"), Fraction(9, 16))
        self.assertEqual(aspect_ratio("1_6:9"), Fraction(16, 9))
        self.assertEqual(aspect_ratio(" 16 : 9 "), Fraction(16, 9))
        self.assertEqual(aspect_ratio("0:9"), Fraction(0))
        for bad in ("16/9", "2.39:1", "16:0", "wide", "1:2:3"):
            self.assertIsNone(aspect_ratio(bad), bad)
        # self.src is 1280x720: 9:16 bounded by its height is 406x720. A zero ratio is no aspect,
        # so --width alone is a square, as 2.2.1 (whose else-branch took the width) made it
        for aspect, extra, size in (("+9:16", (), (406, 720)), ("0:9", ("--width", "640"), (640, 640))):
            with self.subTest(aspect):
                out = OUT / f"fit_asp_{aspect.strip('+').replace(':', '_')}.mp4"
                doc = json.loads(script("fit.py", self.src, "--aspect", aspect, *extra, "-o", out, "--fast", "--json", "--overwrite").stdout)
                self.assertEqual(doc["status"], "completed")
                m = probe(str(out))
                self.assertEqual((m["video"]["width"], m["video"]["height"]), size)

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
        # scaled up and cropped back to the frame's own size: the 2 px each axis lost to two
        # roundings (1278x718 here) was A235, not the border the crop gives up
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1280, 720))
        self.assertEqual(m["video"]["width"] % 2, 0)
        self.assertEqual(m["video"]["height"] % 2, 0)
        frame = OUT / "straighten1_corner.raw"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", out, "-vf", "crop=8:8:0:0",
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", frame)
        data = frame.read_bytes()
        self.assertFalse(all(b == 0 for b in data), "top-left corner is pure black -- straighten left a visible gap")

    def test_straighten_crop_fit_covers_all_four_corners_of_a_wide_frame(self):
        """#416 review: the pre-scale was |cos|+|sin|, a square's factor; a 16:9 frame turned 10
        degrees needs |cos| + 16/9 |sin| (1.293, not 1.158), and two corners came out black."""
        src = tiny_clip(OUT / "straighten_white.mp4", "color=c=white:s=320x180:r=30", seconds=0.5)
        out = OUT / "straighten_white_10.mp4"
        script("straighten.py", src, "--degrees", "10", "-o", out, "--overwrite")
        v = probe(str(out))["video"]
        for x, y in ((1, 1), (v["width"] - 2, 1), (1, v["height"] - 2), (v["width"] - 2, v["height"] - 2)):
            self.assertGreater(min(frame_rgb(out, 0.2, x, y)), 200, (x, y))
        # a size whose centred crop offset was odd (322x184 at -45: 153,87): crop floored it to the
        # chroma grid and the window moved a pixel towards the top-left fill
        src = tiny_clip(OUT / "straighten_white_322.mp4", "color=c=white:s=322x184:r=30", seconds=0.5)
        out = OUT / "straighten_white_322_45.mp4"
        script("straighten.py", src, "--degrees", "-45", "-o", out, "--overwrite")
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (322, 184))
        for x, y in ((0, 0), (v["width"] - 1, 0), (0, v["height"] - 1), (v["width"] - 1, v["height"] - 1)):
            self.assertGreater(min(frame_rgb(out, 0.2, x, y)), 200, (x, y))

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

    def test_pad_with_sound_is_one_filter_graph(self):
        """FFmpeg 8.0.1's scheduler (and conda-forge's 7.1.1) deadlocks (no CPU, until --timeout) when one demuxer feeds
        a -vf graph and an -af graph whose audio both delays its start and pads its tail: pad.py
        hung for 1800 s on Ubuntu 26.04's 8.0.1 (and on conda-forge's 7.1.1 before it). Both
        streams now go through one -filter_complex, which runs on every release. That graph gets
        no even scale from run()'s retry, so pad.py adds it for an odd-sized source itself."""
        doc = json.loads(script("pad.py", self.src, "--start", "1", "--end", "2", "--dry-run", "--json",
                                "-o", OUT / "pad_plan.mp4").stdout)
        cmd = doc["commands"][-1]
        self.assertIn("-filter_complex", cmd)
        self.assertNotIn(" -af ", cmd)
        self.assertNotIn(" -vf ", cmd)
        odd = OUT / "pad_odd_in.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=641x359:rate=30",
           "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "2", "-pix_fmt", "yuv444p", "-c:v", "libx264",
           "-preset", "veryfast", "-c:a", "aac", odd)
        out = OUT / "pad_odd.mp4"
        script("pad.py", odd, "--start", "1", "--end", "1", "--color", "0x2878C8", "--preset", "veryfast", "-o", out)
        m = probe(str(out))
        self.assertEqual((m["video"]["width"] % 2, m["video"]["height"] % 2), (0, 0))
        self.assertClose(m["duration"], 4.0, 0.15)
        streams = json.loads(sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                                "-of", "json", out).stdout)["streams"]
        lengths = {s["codec_type"]: float(s["duration"]) for s in streams}
        self.assertClose(lengths["audio"], lengths["video"], 0.1)

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

    def test_speedramp_refuses_a_segment_that_holds_no_frame(self):
        """#416 review: 1.01-1.02 at 30 fps puts both ends on the frame at 1.0333, so the segment's
        trims were empty and its 0.5x reached no frame, with the run reported as done."""
        proc = script("speedramp.py", self.src, "--segment", "0-1.01:1", "--segment", "1.01-1.02:0.5",
                      "--segment", "1.02-12:1", "--dry-run", "--json", expect_fail=True)
        self.assertIn("holds no frame", json.loads(proc.stdout)["error"]["message"])

    def test_speedramp_last_segment_inside_the_coverage_slack_keeps_its_end(self):
        """The last segment omitted its end bound, and the coverage check allows that end to sit
        up to 0.5 s before the file. A last segment ending 0.4 s early therefore played the tail
        at that segment's speed (1.5 s out of a 2 s source, instead of 1.3 s). The bound is
        omitted only when the stated end is the file's end."""
        src = OUT / "ramp_slack.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
           "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", src)
        out = OUT / "ramp_slack_out.mp4"
        doc = json.loads(script("speedramp.py", src, "--segment", "0-1:1", "--segment", "1-1.6:2",
                                "--preset", "ultrafast", "--json", "-o", out).stdout)
        graph = " ".join(doc["commands"])
        # both streams cut on the frame times 1.0 and 1.6 (the picture's trim half a frame early, #409)
        self.assertIn("trim=start=0.983333:end=1.583333,setpts=PTS-1.000000/TB", graph)
        self.assertIn("atrim=start=1.000000:end=1.600000,asetpts=PTS-1.000000/TB", graph)
        self.assertClose(probe(str(out))["duration"], 1.3, 0.15)
        # an end that is the file's end still runs to the last packet (no end bound to clip it)
        plan = json.loads(script("speedramp.py", src, "--segment", "0-2:1", "--dry-run", "--json",
                                 "-o", OUT / "ramp_slack_eof.mp4").stdout)
        joined = " ".join(plan["commands"])
        self.assertIn("trim=start=-0.016667,setpts", joined)
        self.assertIn("atrim=start=0.000000,asetpts", joined)
        self.assertNotIn(":end=", joined)

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

    def test_loop_refuses_an_output_that_is_its_input(self):
        """The concat list is the only -i, so run()'s own check never saw the source: with
        --overwrite, -o naming the input replaced it with its own loop (#416 review)."""
        victim = OUT / "loop_victim.mp4"
        shutil.copy(self.src, victim)
        before = victim.read_bytes()
        proc = script("loop.py", victim, "--times", "2", "-o", victim, "--overwrite", "--json", expect_fail=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "output_is_input")
        self.assertEqual(victim.read_bytes(), before)

    def test_loop_crossfade_repeats_are_the_clip_minus_the_fade_and_the_seam_is_smooth(self):
        """--crossfade lays the clip's tail over its head: a 4 s clip with a 1 s fade repeats every
        3 s, and the seam's picture step is that of neighbouring frames, where a plain loop of a
        moving clip jumps (#422). The sound is kept; a unit whose audio came out empty once left a
        silent loop that still said verified: true."""
        src = OUT / "loop_xf_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=4",
           "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", "-c:v", "libx264", "-c:a", "aac", src)
        plain = json.loads(script("loop.py", src, "--times", "2", "--json", "-o", OUT / "loop_xf_plain.mp4").stdout)
        doc = json.loads(script("loop.py", src, "--times", "3", "--crossfade", "1", "--json", "-o", OUT / "loop_xf.mp4").stdout)
        self.assertTrue(doc["verified"])
        self.assertEqual(doc["crossfade"], 1.0)
        self.assertEqual(doc["expected_duration"], 9.0)
        self.assertClose(doc["probe"]["duration"], 9.0, 0.05)
        self.assertIsNotNone(doc["probe"].get("audio"))
        self.assertEqual(doc["seam"]["at"], "between_repeats")
        self.assertAlmostEqual(doc["seam"]["time"], 3.0, places=2)
        # a plain loop of a moving clip jumps at the seam; the crossfaded one steps like any frame
        self.assertGreater(plain["seam"]["video_step"], 2 * plain["seam"]["video_typical_step"])
        self.assertLess(doc["seam"]["video_step"], 1.5 * doc["seam"]["video_typical_step"])
        self.assertLess(abs(doc["seam"]["audio_level_step_db"]), 3.0)
        steps = {s["step"]: s for s in doc["verification"]}
        self.assertTrue(steps["duration"]["ok"])
        self.assertEqual(steps["streams"]["measured_count"], {"video": 1, "audio": 1})

    def test_loop_crossfade_times_one_writes_one_seamless_loop(self):
        doc = json.loads(script("loop.py", self.src, "--times", "1", "--crossfade", "2", "--json",
                                "-o", OUT / "loop_xf_one.mp4").stdout)
        self.assertTrue(doc["verified"])
        self.assertEqual(doc["seam"]["at"], "end_to_start")
        self.assertClose(doc["probe"]["duration"], doc["expected_duration"], 0.05)

    def test_loop_crossfade_counts_the_frames_after_the_rate_conform(self):
        """#430 review: 299 stored frames over 10 s at 30 fps (one frame missing) come out of the
        crossfade's fps= as 300; the unit was planned from the 299 and the loop re-timed to the
        source's 29.9 average, so the file missed its own expected length by two frames."""
        gap = OUT / "loop_xf_gap.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=10",
           "-vf", "select='not(eq(n\\,150))'", "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", gap)
        doc = json.loads(script("loop.py", gap, "--crossfade", "0.5", "--times", "2", "--json", "--preset", "veryfast",
                                "-o", OUT / "loop_xf_gap_out.mp4").stdout)
        self.assertEqual(doc["expected_duration"], 19.0)
        self.assertTrue(doc["verified"], doc["verification"])

    def test_loop_conformed_frames_never_falls_back_to_the_stored_count(self):
        """#430 review: with no stream duration and no DURATION tag, _conformed_frames() fell back
        to nb_frames, the count fps= does not keep (299 stored over 10 s at 30 fps is 300 after
        it); it falls back to the container's length."""
        import importlib
        loop = importlib.import_module("loop")
        self.assertEqual(loop._conformed_frames({"nb_frames": 299}, 30.0, 10.0), 300)
        self.assertEqual(loop._conformed_frames({"nb_frames": 299, "duration": 10.0}, 30.0, 12.0), 300)
        self.assertEqual(loop._conformed_frames({"tagged_duration": 9.0}, 30.0, 10.0), 270)

    def test_loop_crossfade_refusals(self):
        for extra, reason in ((["--crossfade", "100"], "at most half"), (["--crossfade", "0.001"], "shorter than one frame"),
                              (["--crossfade", "1", "--boomerang"], "cannot be combined"),
                              # #430 review: round() raised on these and --json printed a traceback
                              (["--crossfade", "nan"], "finite"), (["--crossfade", "inf"], "finite")):
            proc = script("loop.py", self.src, "--times", "2", *extra, "--json", expect_fail=True)
            self.assertIn(reason, json.loads(proc.stdout)["error"]["message"])

    def test_loop_plain_reports_its_seam_and_checks_its_length(self):
        doc = json.loads(script("loop.py", self.src, "--times", "2", "--dry-run", "--json").stdout)
        self.assertIn("expected_duration", doc)
        self.assertNotIn("seam", doc)  # a dry run measured nothing

    def test_loop_times_too_small_refused(self):
        script("loop.py", self.src, "--times", "1", expect_fail=True)

    def test_loop_duration_shorter_than_source_refused(self):
        script("loop.py", self.src, "--duration", "3", expect_fail=True)

    def _ramp(self, name, frames, audio=False):
        """A lossless 10 fps clip whose every frame is a different flat grey, so each output frame
        can be named by its source index; --quality 0 keeps a re-encode bit-exact."""
        path = OUT / name
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=black:s=64x64:r=10:d={frames / 10},format=gray,geq=lum='20+30*N',format=yuv420p"]
        if audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-shortest", "-c:a", "aac"]
        sh(*cmd, "-c:v", "libx264", "-qp", "0", path)
        return path

    @staticmethod
    def _frame_md5s(path):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-fps_mode", "passthrough",
                              "-f", "framemd5", "-"], stdout=subprocess.PIPE, text=True, check=True).stdout
        return [line.split(",")[-1].strip() for line in raw.splitlines() if line and not line.startswith("#")]

    def _source_indices(self, src, out):
        """The output's frames as source frame indices (framemd5); fails on a frame that is no source frame."""
        index = {md5: i for i, md5 in enumerate(self._frame_md5s(src))}
        got = self._frame_md5s(out)
        self.assertTrue(all(md5 in index for md5 in got), "every boomerang frame must be a source frame")
        return [index[md5] for md5 in got]

    def test_loop_boomerang_times_plays_forward_then_back_without_repeating_turnarounds(self):
        src = self._ramp("ramp6.mp4", 6)
        self.assertEqual(len(set(self._frame_md5s(src))), 6, "the ramp's frames must be distinct")
        out = OUT / "loop_boom_times.mp4"
        script("loop.py", src, "--boomerang", "--times", "2", "--quality", "0", "-o", out)
        # 0..N-1 then N-2..1: neither frame 5 nor frame 0 is shown twice in a row, even across a cycle
        self.assertEqual(self._source_indices(src, out), [0, 1, 2, 3, 4, 5, 4, 3, 2, 1] * 2)
        self.assertClose(probe(str(out))["duration"], 2.0, 0.05)

    def test_loop_boomerang_times_one_is_a_single_round_trip(self):
        src = self._ramp("ramp6.mp4", 6)
        out = OUT / "loop_boom_once.mp4"
        script("loop.py", src, "--boomerang", "--times", "1", "--quality", "0", "-o", out)
        self.assertEqual(self._source_indices(src, out), [0, 1, 2, 3, 4, 5, 4, 3, 2, 1])

    def test_loop_boomerang_duration_hits_target(self):
        src = self._ramp("ramp6.mp4", 6)
        out = OUT / "loop_boom_dur.mp4"
        script("loop.py", src, "--boomerang", "--duration", "1.7", "--quality", "0", "-o", out)
        self.assertEqual(self._source_indices(src, out), ([0, 1, 2, 3, 4, 5, 4, 3, 2, 1] * 2)[:17])
        self.assertClose(probe(str(out))["duration"], 1.7, 0.05)

    def test_loop_boomerang_drops_audio_and_says_so(self):
        src = self._ramp("ramp6_audio.mp4", 6, audio=True)
        self.assertIsNotNone(probe(str(src))["audio"])
        out = OUT / "loop_boom_audio.mp4"
        data = json.loads(script("loop.py", src, "--boomerang", "--times", "2", "-o", out, "--json").stdout)
        self.assertIsNone(probe(str(out))["audio"], "reversed audio sounds wrong; a boomerang is silent")
        self.assertTrue(any("audio" in n for n in data["notes"]), data)

    def test_loop_boomerang_vfr_source_shows_each_frame_once(self):
        """A VFR source (phone footage) must not go through -fps_mode cfr after the graph: the CFR
        conform duplicates frames against the reversed timestamps, doubling a turnaround."""
        ramp = self._ramp("ramp6.mp4", 6)
        src = OUT / "ramp6_vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ramp,
           "-vf", "setpts='(N*0.1+gte(N,3)*0.05)/TB'", "-fps_mode", "passthrough", "-use_editlist", "0", "-c:v", "libx264", "-qp", "0", src)
        # -use_editlist 0: FFmpeg 7's mp4 muxer otherwise writes an edit list that hides the last
        # frame (setpts leaves it no duration), so the fixture itself would read as 5 frames
        self.assertTrue(probe(str(src))["video"]["variable_frame_rate_suspected"], "the fixture must read as VFR")
        out = OUT / "loop_boom_vfr.mp4"
        script("loop.py", src, "--boomerang", "--times", "2", "--quality", "0", "-o", out)
        self.assertEqual(self._source_indices(src, out), [0, 1, 2, 3, 4, 5, 4, 3, 2, 1] * 2)
        # and constant-rate: every frame lasts as long (the encoder's time base follows the graph's
        # rate, not the source's r_frame_rate, which is 10/1 here against an average of 60/7)
        durations = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "packet=duration",
                                    "-of", "csv=p=0", str(out)], stdout=subprocess.PIPE, text=True, check=True).stdout.split()
        self.assertEqual(len(set(durations)), 1, durations)
        v = probe(str(out))["video"]
        self.assertEqual(v["r_frame_rate"], v["avg_frame_rate"])

    def test_loop_boomerang_rate_is_the_nominal_fraction_and_never_a_timebase(self):
        import loop  # scripts/ is on sys.path via _fixtures
        rate = lambda **v: loop._nominal_rate(v)
        self.assertEqual(rate(r_frame_rate="60/1", avg_frame_rate="72000/1201"), "60/1")  # iPhone 1/600
        self.assertEqual(rate(r_frame_rate="50/1", avg_frame_rate="75/8"), "75/8")  # VFR: the average
        self.assertEqual(rate(r_frame_rate="1000/1", avg_frame_rate="30/1"), "30/1")
        # no usable average: a time-base r_frame_rate would squeeze the clip to milliseconds
        self.assertEqual(rate(r_frame_rate="90000/1", avg_frame_rate="0/0", nb_frames=250, duration=10.0), "25")
        self.assertEqual(rate(r_frame_rate="90000/1", avg_frame_rate="0/0"), "30")
        self.assertEqual(rate(r_frame_rate="24000/1001", avg_frame_rate="0/0"), "24000/1001")

    def test_loop_boomerang_too_few_frames_refused(self):
        src = self._ramp("ramp2.mp4", 2)
        script("loop.py", src, "--boomerang", "--times", "2", "-o", OUT / "loop_boom_short.mp4", expect_fail=True)

    # ------------------------------------------- a length that is not a whole millisecond
    def test_a_length_or_a_silence_between_two_milliseconds_is_written_to_the_sample(self):
        """The siblings #493 left: overlay.py, waveform.py, loop.py and sync.py --replace-audio
        ended their output with `-t {:.3f}`, and pad.py and freeze.py added silence of
        `adelay={int(ms)}` / `apad=pad_dur={:.3f}`: a length to the millisecond. 59244 samples
        (48 kHz) came out as 59232, a sound that runs on (sync's apad, loop's next repeat) as 59280
        for 59261, and --start 1.001 as 1.000 s (int(1.001 * 1000) is 1000). The count is of the
        written track's samples, as in test_grid_broll_and_multicam_end_their_sound_to_the_sample
        (tests/test_orchestration.py): packet durations with the edit list ignored, less the
        encoder's 1024 of priming.
        The follow-ups of #470 are the same class: fit.py --method trim ended on `-t {:.3f}` too
        (59232 for 59244), broll.py delayed a cutaway's sound by `int(at * 1000)` ms (--at 1.001:
        48000 for 48048) and sync.py --replace-audio by the offset rounded to the millisecond
        (measured with --fine-ms 0.25: 11232 for 11246).
        After 3.8.4 a silence ahead of a clip is as long as the frames put ahead of its picture
        (pad.py --start, freeze.py's hold at the first frame), and a cutaway's sound starts with
        the first frame of its window: the expectations for an amount between two frames are the
        frames' (test_a_start_a_gate_or_a_retimed_length_is_written_to_the_sample)."""
        burst = "0.4*sin(2*PI*440*t)*lt(mod(t\\,0.31)\\,0.1)"
        ff = ("ffmpeg", "-y", "-hide_banner", "-loglevel", "error")
        x264 = ("-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p")

        def clip(name, rate, samples, picture=1):
            path = OUT / name
            sh(*ff, "-f", "lavfi", "-i", f"testsrc=d={picture}:s=160x120:r=25", "-f", "lavfi", "-i", f"aevalsrc={burst}:s={rate}",
               "-af", f"atrim=end_sample={samples}", *x264, "-c:a", "pcm_s16le", path)
            return path

        def track_samples(path):
            rows = sh("ffprobe", "-v", "error", "-ignore_editlist", "1", "-select_streams", "a:0",
                      "-show_entries", "packet=duration", "-of", "csv=p=0", path).stdout.split()
            return sum(int(r.split(",")[0]) for r in rows) - 1024

        def frames(path):
            return int(sh("ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path).stdout.split()[0].strip(","))

        down48, down44, up48 = clip("ms_down_48.mov", 48000, 59244), clip("ms_down_44.mov", 44100, 54433), clip("ms_up_48.mov", 48000, 59261)
        for path, rate, samples, text in ((down48, 48000, 59244, "1.234"), (down44, 44100, 54433, "1.234"), (up48, 48000, 59261, "1.235")):
            length = float(probe(str(path))["duration"])
            self.assertEqual(round(length * rate), samples, "fixture")
            self.assertEqual(f"{length:.3f}", text, "fixture")
            self.assertNotEqual(round(float(text) * rate), samples, "not a whole millisecond: the old text names another count")
        take = OUT / "ms_take.wav"  # sync's second file: ends before the reference does
        sh(*ff, "-f", "lavfi", "-i", f"aevalsrc={burst}:s=48000", "-af", "atrim=end_sample=40000", take)
        layer = OUT / "ms_layer.mp4"
        sh(*ff, "-f", "lavfi", "-i", "testsrc2=d=1:s=64x48:r=25", *x264, layer)
        # fit.py trims a source that runs on: 2 s of picture and of sound
        two48, two44 = clip("ms_two_48.mov", 48000, 96000, picture=2), clip("ms_two_44.mov", 44100, 88200, picture=2)
        self.assertEqual((round(1.2343 * 44100), round(1.234 * 44100)), (54433, 54419), "fixture")
        cases = [
            # (label, tool, arguments, rate, samples, frames, text in the command)
            ("overlay --image", "overlay.py", [down48, "--image", self.logo], 48000, 59244, 31, "-t 1.234250 "),
            ("overlay --video at 44.1 kHz", "overlay.py", [down44, "--video", layer], 44100, 54433, 25, "-t 1.234308 "),
            ("overlay: a millisecond that cuts nothing stays", "overlay.py", [up48, "--image", self.logo], 48000, 59261, 31, "-t 1.235 "),
            ("waveform", "waveform.py", [down48], 48000, 59244, 30, "-t 1.234250 "),
            ("waveform at 44.1 kHz", "waveform.py", [down44], 44100, 54433, 30, "-t 1.234308 "),
            ("sync pads to the reference", "sync.py", [down48, take, "--replace-audio"], 48000, 59244, 25, "-t 1.234250 "),
            ("sync: the pad runs on past a millisecond rounded up", "sync.py", [up48, take, "--replace-audio"], 48000, 59261, 25, "-t 1.234604 "),
            ("loop", "loop.py", [down48, "--duration", "2.23425"], 48000, 107244, None, "-t 2.234250 "),
            ("loop at 44.1 kHz", "loop.py", [down44, "--duration", "2.23425"], 44100, 98530, None, "-t 2.234250 "),
            ("loop: the next repeat runs on past a millisecond rounded up", "loop.py", [down48, "--duration", "2.2346"], 48000, 107261, None, "-t 2.234600 "),
            ("pad --end", "pad.py", [down48, "--end", "0.23425"], 48000, 59244 + 11244, 31, "aformat=sample_rates=48000,apad=pad_len=11244"),
            # --start: 6 frames of black at 25 fps (0.240 s), and the sound waits as long
            ("pad --start at 44.1 kHz", "pad.py", [down44, "--start", "0.23425"], 44100, 54433 + 10584, 31, "adelay=240:all=1,apad=pad_dur=0.000"),
            ("pad --start and --end", "pad.py", [down48, "--start", "0.23425", "--end", "0.5"], 48000, 59244 + 11520 + 24000, 44,
             "adelay=240:all=1,apad=pad_dur=0.500"),
            ("pad --start and an --end between two milliseconds", "pad.py", [down48, "--start", "0.23425", "--end", "0.23425"], 48000, 59244 + 11520 + 11244, 37,
             "aformat=sample_rates=48000,adelay=11520S:all=1,apad=pad_len=11244"),
            ("pad: 1.001 s is 25 frames of black", "pad.py", [down48, "--start", "1.001"], 48000, 59244 + 48000, 50, "adelay=1000:all=1,apad=pad_dur=0.000"),
            ("freeze holds the end", "freeze.py", [down48, "--hold", "0.23425"], 48000, 59244 + 11244, 31, "aformat=sample_rates=48000,apad=pad_len=11244"),
            ("freeze holds the start at 44.1 kHz", "freeze.py", [down44, "--at", "0", "--hold", "0.23425", "--mode", "insert"], 44100, 54433 + 10584, 31,
             "adelay=240:all=1"),
            ("freeze: 1.001 s is 25 held frames", "freeze.py", [down48, "--at", "0", "--hold", "1.001", "--mode", "insert"], 48000, 59244 + 48000, 50,
             "adelay=1000:all=1"),
            ("fit --method trim", "fit.py", [two48, "--method", "trim", "--duration", "1.23425"], 48000, 59244, 31, "-t 1.234250 "),
            ("fit --method trim at 44.1 kHz", "fit.py", [two44, "--method", "trim", "--duration", "1.2343"], 44100, 54433, 31, "-t 1.234300 "),
            ("fit --method trim from the centre", "fit.py", [two48, "--method", "trim", "--duration", "1.23425", "--from-center"], 48000, 59244, 31, "-t 1.234250 "),
            ("fit: the source runs on past a millisecond rounded up", "fit.py", [two48, "--method", "trim", "--duration", "1.2346"], 48000, 59261, 31, "-t 1.234600 "),
            ("fit: a speed change too small to retime the sound", "fit.py", [two48, "--duration", "1.9999"], 48000, 95995, 50, "-t 1.999900 "),
        ]
        for label, tool, args, rate, samples, pictures, text in cases:
            with self.subTest(case=label):
                out = OUT / f"ms_{tool[:-3]}_out.mp4"
                doc = json.loads(script(tool, *args, "-o", out, "--json").stdout)
                self.assertEqual(int(probe(str(out))["audio"]["sample_rate"]), rate)
                self.assertEqual(track_samples(out), samples)
                # the picture is the one the millisecond text wrote (measured on 3.8.1)
                if pictures is not None:
                    self.assertEqual(frames(out), pictures)
                else:
                    # loop.py: the fixture's sound outlasts its picture, so each repeat starts
                    # 0.234 s after the last frame of the one before. FFmpeg 6.1 fills that with
                    # repeated frames (56 packets), FFmpeg 7.1 and 8 hold the frame (50): the count is the
                    # FFmpeg's, the picture's length is the tool's
                    self.assertIn(frames(out), (50, 56))
                    self.assertAlmostEqual(float(probe(str(out))["video"]["duration"]), float(args[-1]), delta=0.045)
                self.assertIn(text, str(doc["commands"]))

        # A silence ahead of a track that is mixed or laid under a picture: where the sound starts
        # is read from the graph itself, the command run again with PCM in place of AAC (an AAC
        # frame smears a start over 1024 samples)
        def first_sound(doc, name):
            cmd = shlex.split(doc["commands"][-1])
            at = cmd.index("aac")
            self.assertEqual((cmd[at - 1], cmd[at + 1]), ("-c:a", "-b:a"))
            cmd[at:at + 3], cmd[-1] = ["pcm_s16le"], str(OUT / name)
            sh(*cmd)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", cmd[-1], "-map", "0:a:0", "-ac", "1", "-f", "s16le", "-"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            pcm = array.array("h")
            pcm.frombytes(raw)
            return next(k for k, v in enumerate(pcm) if abs(v) > 200)

        aroll, cutaway = OUT / "ms_aroll.mov", OUT / "ms_cutaway.mov"
        sh(*ff, "-f", "lavfi", "-i", "testsrc=d=2:s=160x120:r=25", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-af", "atrim=end_sample=96000", *x264, "-c:a", "pcm_s16le", aroll)
        sh(*ff, "-f", "lavfi", "-i", "testsrc2=d=1:s=160x120:r=25", "-f", "lavfi", "-i", "aevalsrc=0.5:s=48000:d=1",
           *x264, "-c:a", "pcm_s16le", cutaway)
        # the sound starts with the cutaway's first frame, the A-roll's first at or after --at
        # (25 fps: 1.04 s, 1.24 s, 0.24 s); an --at on a frame is the delay it always was
        for at, audio, start, text in (("1.001", "mix", 49920, "adelay=1040|1040["),
                                       ("1.2346", "mix", 59520, "adelay=1240|1240["),
                                       ("0.23425", "b", 11520, "adelay=240|240["),
                                       ("1", "mix", 48000, "adelay=1000|1000[")):
            with self.subTest(broll_at=at, audio=audio):
                out = OUT / "ms_broll_out.mp4"
                doc = json.loads(script("broll.py", aroll, "--insert", cutaway, "--at", at, "--duration", "0.5", "--audio", audio, "-o", out, "--json").stdout)
                self.assertIn(text, doc["commands"][-1])
                self.assertEqual(first_sound(doc, "ms_broll_pcm.mov"), start)
                self.assertEqual(track_samples(out), 96000, "the mix is as long as the A-roll")
                self.assertEqual(frames(out), 50)

        # sync.py --replace-audio: the delay is the offset the run measured. --fine-ms 1 measures
        # in whole milliseconds, a finer step between them; either way the sound starts on the
        # sample the reported offset names (to the 4 decimals it is reported with: 2.4 samples)
        noise = "anoisesrc=d=4:c=pink:r=48000:a=0.5:seed=7"
        reference, late = OUT / "ms_sync_ref.mov", OUT / "ms_sync_late.wav"
        sh(*ff, "-f", "lavfi", "-i", "testsrc=d=4:s=160x120:r=25", "-f", "lavfi", "-i", noise, *x264, "-c:a", "pcm_s16le", reference)
        sh(*ff, "-f", "lavfi", "-i", noise, "-af", "atrim=start_sample=11244,asetpts=PTS-STARTPTS", late)  # starts 0.23425 s in
        for fine in ("0.25", "1"):
            with self.subTest(sync_fine_ms=fine):
                out = OUT / "ms_sync_out.mp4"
                doc = json.loads(script("sync.py", reference, late, "--replace-audio", "--fine-ms", fine, "-o", out, "--json").stdout)
                self.assertAlmostEqual(doc["offset_seconds"], 0.23425, delta=0.0006 if fine == "1" else 0.0003)
                delay = re.search(r"adelay=(\d+)(S?):all=1", doc["commands"][-1])
                written = int(delay.group(1)) * (1 if delay.group(2) else 48)
                self.assertLessEqual(abs(written - doc["offset_seconds"] * 48000), 2.5, doc["commands"][-1])
                self.assertLessEqual(abs(first_sound(doc, "ms_sync_pcm.mov") - written), 2)
                self.assertEqual(track_samples(out), 192000, "padded to the reference")
                if fine == "1":
                    self.assertIn(f"adelay={round(doc['offset_seconds'] * 1000)}:all=1,apad", doc["commands"][-1])  # the text it always was
        # what the millisecond says is written as it always was: a whole millisecond, no sound, and
        # a dry run's pending input, which has no rate to count in
        import _common
        self.assertEqual(_common.length_output_t(1.2, 48000), "1.200")
        self.assertEqual(_common.length_output_t(12.0, 44100, runs_on=True), "12.000")
        self.assertEqual(_common.length_output_t(59244 / 48000, 48000), "1.234250")
        self.assertEqual(_common.length_output_t(59261 / 48000, 48000), "1.235")
        self.assertEqual(_common.length_output_t(59261 / 48000, 48000, runs_on=True), "1.234604")
        # the microsecond text is itself a rounding: 2.00001042 s is 96001 samples at 48 kHz and
        # "2.000010" names 96000, so the text is the first microsecond that names the count asked
        self.assertEqual(round(2.00001042 * 48000), 96001)
        self.assertEqual(_common.length_output_t(2.00001042, 48000), "2.000011")
        def ffmpeg_samples(text, rate):  # a rescale that rounds a half up, not to the even count
            return (round(float(text) * 1_000_000) * rate + 500_000) // 1_000_000

        for length, rate in ((2.00001042, 48000), (1.2342505, 44100), (59244 / 48000, 48000), (7.123456789, 96000), (0.0049999, 44100)):
            text = _common.length_output_t(length, rate, runs_on=True)
            self.assertEqual(ffmpeg_samples(text, rate), round(length * rate), (length, rate, text))
        # 0.005 s is 220.5 samples at 44.1 kHz, which FFmpeg writes as 221: for the 220 asked the
        # millisecond text is one too many where the sound runs on (round() called it 220)
        self.assertEqual(_common.length_output_t(0.0049999, 44100, runs_on=True), "0.004999")
        self.assertEqual(_common.length_output_t(0.0049999, 44100), "0.005")
        self.assertEqual(_common.length_output_t(59244 / 48000, 0), "1.234")
        self.assertEqual(_common.length_output_t(59244 / 48000, None, runs_on=True), "1.234")
        self.assertEqual(_common.silence_filter(48000, 0.5, 0.25), "adelay=500:all=1,apad=pad_dur=0.250")
        self.assertEqual(_common.silence_filter(44100, 0.29, 0.0), "adelay=290:all=1,apad=pad_dur=0.000")
        self.assertEqual(_common.silence_filter(48000, tail=2.0), "apad=pad_dur=2.000")
        self.assertEqual(_common.silence_filter(48000, lead=2.0), "adelay=2000:all=1")
        self.assertEqual(_common.silence_filter(48000, lead=1.001), "adelay=1001:all=1")  # int(1.001 * 1000) is 1000
        self.assertEqual(_common.silence_filter(44100, lead=0.23425), "aformat=sample_rates=44100,adelay=10330S:all=1")
        self.assertEqual(_common.silence_filter(0, 0.23425, 0.0), "adelay=234:all=1,apad=pad_dur=0.000")
        pending = OUT / "ms_not_written_yet.mp4"
        mute = OUT / "ms_no_sound.mp4"
        sh(*ff, "-f", "lavfi", "-i", "testsrc=d=2:s=160x120:r=25", *x264, mute)
        for tool, source, args, text in (("pad.py", pending, ["--end", "0.23425"], "apad=pad_dur=0.234"),
                                         ("freeze.py", pending, ["--hold", "0.23425"], "apad=pad_dur=0.234"),
                                         ("overlay.py", pending, ["--image", self.logo], "-shortest"),
                                         ("fit.py", pending, ["--duration", "1.23425"], "-t 1.234 "),
                                         ("fit.py", mute, ["--method", "trim", "--duration", "1.23425"], "-t 1.234 "),
                                         ("fit.py", two48, ["--method", "trim", "--duration", "1.2"], "-t 1.200 "),
                                         # a retimed track is ended on the target's sample by its own filter
                                         ("fit.py", two48, ["--duration", "1.23425"], "-t 1.234250 ")):
            with self.subTest(pending=tool, source=source.name, args=args):
                plan = json.loads(script(tool, source, *args, "--dry-run", "-o", OUT / "ms_plan.mp4", "--json").stdout)
                self.assertIn(text, str(plan["commands"]))
                self.assertNotIn("pad_len", str(plan["commands"]))

    def test_a_window_or_a_length_on_a_frame_time_keeps_that_frame(self):
        """#470's open items: a window, a start or a length that names a frame's own time took the
        frame after it, or the layer's frames decided it. At 30000/1001 frame 37 starts at
        1.2345667 s and `{:.3f}` writes 1.235, past it: broll.py put frames 39-68 of a cutaway on
        frames 38-67 for 37-67, fit.py --method trim without sound wrote 38 frames for 37, and an
        overlay.py window of frames 37-67 showed a 25 fps layer on 36 and 38-65 and 67 (overlay's
        enable is evaluated on the layer's frames too). An SMPTE time was counted at probe()'s
        29.97, so 00:00:01:07 was 1.2345679 s, 1.2 microseconds past frame 37. Measured from the
        written file: frame N of the source has a luma of 16 + 2 * N (numbered_clip)."""
        ntsc = "30000/1001"
        f = lambda n: n * 1001 / 30000  # noqa: E731 -- frame n's time at 30000/1001
        with self.subTest(parse_time="00:00:01:07"):
            self.assertAlmostEqual(_common.parse_time("00:00:01:07", 29.97), f(37), places=9)
            self.assertAlmostEqual(_common.parse_time("00:00:01:07@29.97"), f(37), places=9)
            self.assertEqual(_common.parse_time("00:00:01:05", 25.0), 1.2)  # a whole rate is counted as it was
        aroll = plain_clip(OUT / "fw_aroll.mp4", ntsc, 90)
        cutaway = numbered_clip(OUT / "fw_cutaway.mp4", ntsc, 90)
        numbered = numbered_clip(OUT / "fw_numbered.mp4", ntsc, 90)
        main = plain_clip(OUT / "fw_main.mp4", ntsc, 90, size="128x128", luma=40)
        layer25 = plain_clip(OUT / "fw_layer25.mp4", 25, 100, size="32x32")
        white = OUT / "fw_white.png"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=white:s=32x32", "-frames:v", "1", white)
        self.assertEqual(frame_numbers(cutaway), list(range(90)), "fixture")
        out = OUT / "fw_out.mp4"
        for times in (("1.2345666", "1.2345666", "1.0343666"), ("00:00:01:07", "00:00:01:07", "00:00:01:01")):
            with self.subTest(tool="broll.py", times=times):
                doc = json.loads(script("broll.py", aroll, "--insert", cutaway, "--at", times[0], "--from", times[1],
                                        "--duration", times[2], "-o", out, "--json").stdout)
                shown = frame_numbers(out)
                self.assertEqual(stretches(shown, lambda n: n < 90), [(37, 67)], "the cutaway is on frames 37-67")
                self.assertEqual(shown[37:68], list(range(37, 68)), "showing its own frames 37-67")
                self.assertIn("overlay='if(between(t,1.217883,2.252250),0,-w)':0", " ".join(shlex.split(doc["commands"][-1])))
        for duration, frames in (("1.2345666", 37), ("00:00:01:07", 37), ("1.0014", 31), ("1.001", 30)):
            with self.subTest(tool="fit.py", duration=duration):
                doc = json.loads(script("fit.py", numbered, "--method", "trim", "--duration", duration, "-o", out, "--json").stdout)
                self.assertEqual(frame_numbers(out), list(range(frames)))
                if duration == "1.001":
                    self.assertIn("-t 1.001 ", doc["commands"][-1], "a millisecond that keeps the frames asked stays")
        for layer in (["--image", white], ["--video", layer25], ["--text", "XX", "--font-size", "40", "--box"]):
            for start, end, frames in (("1.2345666", "2.2356666", (37, 67)), ("00:00:01:07", "00:00:02:07", (37, 67)),
                                       ("1.0343666", "2.002", (31, 60))):
                with self.subTest(tool="overlay.py", layer=layer[0], start=start, end=end):
                    script("overlay.py", main, *layer, "--position", "0,0", "--margin", "0", "--start", start, "--end", end, "-o", out)
                    lumas = frame_lumas(out, crop="32:32:0:0")
                    self.assertEqual(stretches(lumas, lambda v: v > 45), [frames])
        with self.subTest(tool="graphics.py"):
            doc = json.loads(script("graphics.py", main, "--template", "title", "--title", "Hi", "--start", "1.2345666",
                                    "--end", "2.2356666", "-o", out, "--json").stdout)
            lumas = frame_lumas(out)
            self.assertEqual(stretches(lumas, lambda v: abs(v - lumas[0]) > 1), [(37, 67)])
            self.assertIn("enable='between(t,1.217883,2.252250)'", " ".join(shlex.split(doc["commands"][-1])))

    def test_a_start_a_gate_or_a_retimed_length_is_written_to_the_sample(self):
        """#470's open items on the sound: broll.py --audio b muted the A-roll with
        `volume=0:enable=...`, evaluated once per 1024-sample frame (48128-96255 for 48000-95999);
        a cutaway's sound started at --at while its picture started on the A-roll's first frame
        at or after it (--at 1.001 at 25 fps: sound from 1.001 s, picture from 1.04 s); sync.py
        --trim-second delayed by `adelay=<ms>` (11232 for an offset of 0.2343 s); fit.py --method
        speed left atempo's sound 13 to 62 ms short of the target; pad.py --start and freeze.py's
        hold at the first frame put whole frames of picture (0.240 s for 0.23425 at 25 fps) ahead
        of an exact 0.23425 s of silence. Read from the graph, the command run again with PCM in
        place of AAC (pcm_of)."""
        quiet, a_dc = "aevalsrc=0:s=48000:d=4", "aevalsrc=0.5:s=48000:d=4"
        aroll = plain_clip(OUT / "fs_aroll.mov", 25, 100, sound=a_dc)
        silent_aroll = plain_clip(OUT / "fs_aroll_silent.mov", 25, 100, sound=quiet)
        cutaway = numbered_clip(OUT / "fs_cutaway.mov", 25, 100, sound=a_dc)
        silent_cutaway = numbered_clip(OUT / "fs_cutaway_silent.mov", 25, 100, sound=quiet)
        out, pcm = OUT / "fs_out.mp4", OUT / "fs_pcm.mov"

        def run(*args):
            return json.loads(script(*args, "-o", out, "--json").stdout)["commands"][-1]

        def spans(samples, loud):
            return [s for s in stretches(samples, (lambda v: abs(v) > 200) if loud else (lambda v: abs(v) < 200)) if s[1] - s[0] > 100]

        # the window is the A-roll's frames from the first at or after --at to the last before the
        # end (1.04-2.00 s for 1.001 s + 1 s; 1.24-1.72 s for 1.23425 + 0.5), 1920 samples each
        for at, length, first, last in (("1", "1", 48000, 95999), ("1.001", "1", 49920, 97919), ("1.23425", "0.5", 59520, 84479)):
            with self.subTest(tool="broll.py", at=at, audio="b"):
                command = run("broll.py", aroll, "--insert", silent_cutaway, "--at", at, "--duration", length, "--audio", "b")
                self.assertEqual(spans(pcm_of(command, pcm), loud=False), [(first, last)], "the A-roll is muted over the window")
                self.assertIn(f"between(t,{(first - 0.5) / 48000:.9f},", command)
                command = run("broll.py", silent_aroll, "--insert", cutaway, "--at", at, "--duration", length, "--audio", "b")
                self.assertEqual(spans(pcm_of(command, pcm), loud=True), [(first, last)], "the cutaway sounds over the same samples")
                shown = frame_numbers(pcm)
                self.assertEqual(stretches(shown, lambda n: n < 100)[0][0] * 1920, first, "and starts with its first frame")
        with self.subTest(tool="sync.py"):
            noise = "anoisesrc=d=4:c=pink:r=48000:a=0.5:seed=7"
            reference, late = OUT / "fs_sync_ref.mov", OUT / "fs_sync_late.mov"
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=4:s=160x120:r=25", "-f", "lavfi", "-i", noise,
               "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_s16le", reference)
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=25", "-f", "lavfi", "-i", noise, "-af",
               "atrim=start_sample=11244,asetpts=PTS-STARTPTS,atrim=end_sample=144000", "-c:v", "libx264", "-preset", "ultrafast",
               "-c:a", "pcm_s16le", late)
            doc = json.loads(script("sync.py", reference, late, "--trim-second", "--fine-ms", "0.25", "-o", out, "--json").stdout)
            written = round(doc["offset_seconds"] * 48000)
            self.assertIn(f"aformat=sample_rates=48000,adelay={written}S:all=1", doc["commands"][-1])
            self.assertEqual(next(k for k, v in enumerate(pcm_of(doc["commands"][-1], pcm)) if abs(v) > 200), written)
            doc = json.loads(script("sync.py", reference, late, "--trim-second", "-o", out, "--json").stdout)
            self.assertIn(f"adelay={round(doc['offset_seconds'] * 1000)}:all=1", doc["commands"][-1], "a whole millisecond is the text it was")
        burst = "0.4*sin(2*PI*440*t)*lt(mod(t\\,0.31)\\,0.1)"
        bursts = numbered_clip(OUT / "fs_bursts.mov", 25, 75, sound=f"aevalsrc={burst}:s=48000:d=3")
        sine = numbered_clip(OUT / "fs_sine.mov", 25, 75, sound="sine=f=440:sample_rate=48000:d=3")
        for source, duration in ((bursts, "1.23425"), (bursts, "2.0"), (sine, "1.23425")):
            with self.subTest(tool="fit.py", source=source.name, duration=duration):
                command = run("fit.py", source, "--duration", duration)
                self.assertEqual(len(pcm_of(command, pcm)), round(float(duration) * 48000))
        sound = plain_clip(OUT / "fs_pad.mov", 25, 25, sound="aevalsrc=0.5:s=48000:d=1", luma=200)
        sound30 = plain_clip(OUT / "fs_pad30.mov", 30, 30, sound="aevalsrc=0.5:s=44100:d=1", luma=200)
        for tool, source, args, first, rate in (("pad.py", sound, ["--start", "0.23425"], 0.24, 48000),
                                                ("pad.py", sound30, ["--start", "0.05"], 2 / 30, 44100),
                                                ("freeze.py", sound, ["--at", "0", "--hold", "0.23425", "--mode", "insert"], 0.24, 48000)):
            with self.subTest(tool=tool, args=args):
                command = run(tool, source, *args)
                self.assertEqual(spans(pcm_of(command, pcm), loud=True)[0][0], round(first * rate), "the silence is the held frames' length")
                if tool == "pad.py":
                    lumas = frame_lumas(pcm)
                    self.assertEqual(next(k for k, v in enumerate(lumas) if v > 150), round(first * {48000: 25, 44100: 30}[rate]))
        from _common.decision import tpad_length
        self.assertEqual(tpad_length(0.23425, probe(str(sound))), 0.24)
        self.assertEqual(tpad_length(1.0, probe(str(sound))), 1.0)

    def test_a_loop_whose_sound_outlasts_its_picture_repeats_the_last_frame_on_the_grid(self):
        """#470: a 1 s 25 fps clip with 1.23425 s of sound starts each repeat 0.23425 s after its
        last frame. What filled that gap was the output's frame-rate handling: FFmpeg 6.1.1 repeated
        the last frame and showed the next repeat's first frame on 1.20 s and 1.24 s, a frame
        before its time (FFmpeg 7.1 and 8 held the last frame instead). The graph ends on the
        clip's rate now: frames 0-24, frame 24 until the repeat, and the repeat's frame 0 on
        1.24 s, the first tick at or after its sound. The packet count is not pinned (the 7.1 and
        8 behaviour is seen in CI only)."""
        gap = numbered_clip(OUT / "fl_gap.mov", 25, 25, sound="aevalsrc=0.5:s=48000:d=1.23425")
        flush = numbered_clip(OUT / "fl_flush.mov", 25, 25, sound="aevalsrc=0.5:s=48000:d=1")
        out = OUT / "fl_out.mp4"
        doc = json.loads(script("loop.py", gap, "--duration", "2.23425", "-o", out, "--json").stdout)
        shown = frame_numbers(out)
        self.assertEqual(shown[:31], list(range(25)) + [24] * 6)
        self.assertEqual(shown[31:40], list(range(9)), "each frame of the next repeat once, from 1.24 s")
        self.assertIn("setpts=PTS-0.000000/TB,fps=25/1[v]", doc["commands"][-1])
        doc = json.loads(script("loop.py", flush, "--duration", "2.5", "-o", out, "--json").stdout)
        self.assertNotIn(",fps=", doc["commands"][-1], "a clip whose repeats meet keeps the command it had")
        self.assertEqual(frame_numbers(out)[20:30], [20, 21, 22, 23, 24, 0, 1, 2, 3, 4])

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
        # the gap reaches the document too, not only stderr
        proc = script("sequence.py", "--dir", frames_dir, "--pattern", "frame_%04d.png", "--fps", "5",
                      "-o", OUT / "seq_gap_plan.mp4", "--dry-run", "--json")
        gap = json.loads(proc.stdout)["diagnostics"]["warnings"][0]
        self.assertEqual((gap["code"], gap["missing"], gap["frames_left_out"]), ("sequence_gap", "frame_0002.png", 2))

    def test_sequence_frame_durations_add_up_to_the_frame_grid(self):
        """#474: every frame was written `duration 0.033333` at 30 fps, 3.3e-7 s short, and the
        concat demuxer adds them up: half a frame behind after about 50,000 frames. The written
        list is read back and summed as the demuxer does (whole microseconds): at every frame the
        running total is i/rate to within half a microsecond, at a whole-microsecond-free rate too."""
        from fractions import Fraction
        sys.path.insert(0, str(SCRIPTS))
        import sequence as seq_mod  # noqa: E402
        n = 60000
        frames = [Path(f"/frames/f{i:05d}.png") for i in range(n)]
        for rate in (Fraction(30), Fraction(30000, 1001), Fraction(24000, 1001), Fraction(60000, 1001)):
            text = seq_mod.concat_list(frames, rate)
            written = [line.split()[1] for line in text.splitlines() if line.startswith("duration ")]
            self.assertEqual(len(written), n)
            total = 0
            for i, d in enumerate(written):
                whole, frac = d.split(".")
                self.assertEqual(len(frac), 6, d)
                total += int(whole) * 1_000_000 + int(frac)
                self.assertLessEqual(abs(Fraction(total) - Fraction((i + 1) * 1_000_000) / rate),
                                     Fraction(1, 2), f"{rate}: frame {i + 1} at {total} us")

    def test_sequence_at_an_ntsc_rate_renders_every_frame(self):
        """#474: a small real render at 29.97 (30000/1001, a frame time that is no whole number of
        microseconds) still has one output frame per input frame."""
        frames_dir = OUT / "seqframes_ntsc"
        frames_dir.mkdir(exist_ok=True)
        for i in range(37):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c={'red' if i % 2 == 0 else 'blue'}:s=64x48", "-frames:v", "1", frames_dir / f"f_{i:03d}.png")
        out = OUT / "seq_ntsc.mp4"
        script("sequence.py", "--dir", frames_dir, "--pattern", "f_%03d.png", "--fps", "29.97", "-o", out)
        counted = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                                  "-show_entries", "stream=nb_read_frames,r_frame_rate", "-of", "json", str(out)],
                                 stdout=subprocess.PIPE, check=True).stdout
        stream = json.loads(counted)["streams"][0]
        self.assertEqual((int(stream["nb_read_frames"]), stream["r_frame_rate"]), (37, "30000/1001"))

    def test_sequence_keeps_every_picture_in_order_at_a_high_rate(self):
        """Each image is read at the requested rate (`option framerate` per concat entry), not the
        image demuxer's default 25: at 120 fps two images used to land on one input timestamp, so
        the fps filter dropped one and repeated a neighbour -- the frame count stayed right."""
        frames_dir = OUT / "seqframes_order"
        frames_dir.mkdir(exist_ok=True)
        n = 40
        for i in range(n):
            v = 6 * i
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c=0x{v:02x}{v:02x}{v:02x}:s=32x32", "-frames:v", "1", frames_dir / f"f_{i:03d}.png")
        for fps in ("120", "29.97"):
            with self.subTest(fps=fps):
                out = OUT / f"seq_order_{fps}.mov"
                script("sequence.py", "--dir", frames_dir, "--pattern", "f_%03d.png", "--start-number", "0",
                       "--fps", fps, "--codec", "prores", "-o", out, "--overwrite")
                raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-vf", "format=gray,scale=1:1",
                                      "-f", "rawvideo", "-"], stdout=subprocess.PIPE, check=True).stdout
                got = list(raw)
                self.assertEqual(len(got), n)
                wrong = [(i, g, 6 * i) for i, g in enumerate(got) if abs(g - 6 * i) > 2]
                self.assertEqual(wrong, [], f"frames out of order at {fps} fps (index, got, expected)")

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
        # its own directory, made here: with another test's it was missing whenever this ran first,
        # and the run below then tested the missing-directory refusal instead
        frames_dir = OUT / "seqframes_nomatch"
        frames_dir.mkdir(exist_ok=True)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48",
           "-frames:v", "1", frames_dir / "frame_0000.png")
        doc = json.loads(script("sequence.py", "--dir", frames_dir, "--pattern", "*.jpg", "--fps", "5",
                                "-o", OUT / "seq_nomatch.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input", doc)
        self.assertIn("match", doc["error"]["message"])
        self.assertNotIn("not a directory", doc["error"]["message"])
        self.assertFalse((OUT / "seq_nomatch.mp4").exists())

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
        self.assertAlmostEqual(c.parse_time("01:00:00:00@29.97"), 108000 * 1001 / 30000)  # 29.97 is 30000/1001 (after 3.8.4)
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
        self.assertIn("timing is variable", proc.stderr)
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
        gappy = OUT / "gappy_sine.mp4"   # not gappy.mp4: MediaFixtures._gappy keeps a different layout under that name
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
        # three 2 s gaps; --margin keeps 0.2 s of each on both sides (0.15 s before 2.22, when this
        # was 5.25 s removed and 6.75 s kept)
        self.assertClose(data["removed_seconds"], 4.9, 0.3)
        out = OUT / "tight.mp4"
        edl = OUT / "keep.txt"
        script("silence.py", gappy, "--preset", "veryfast", "--edl", edl, "-o", out)
        self.assertClose(probe(str(out))["duration"], 7.1, 0.3)
        self.assertEqual(len(edl.read_text().strip().splitlines()), 3)
        # the EDL feeds cut.py --segments directly
        segs = ",".join(edl.read_text().split())
        out2 = OUT / "tight_via_cut.mp4"
        script("cut.py", gappy, "--segments", segs, "--accurate", "--preset", "veryfast", "-o", out2)
        self.assertClose(probe(str(out2))["duration"], 7.1, 0.4)

    def test_silence_removal_cuts_the_sound_with_the_picture(self):
        """FFmpeg 8.0 and 8.0.1 (Ubuntu 26.04) ship an `aselect` that passes every frame through (its
        activate callback was lost when the filter was converted; fixed in 8.0.2/8.1), so silence.py
        cut the picture to 6.75 s and left the sound at 12 s. The container duration is the longer
        stream, so each stream is measured here. The sound is selected through ametadata (tag the
        frames the expression keeps, keep the tagged ones), which behaves the same on every release,
        and is never planned through aselect again."""
        gappy = OUT / "gappy_streams.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
           "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "12", "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", gappy)
        plan = json.loads(script("silence.py", gappy, "--dry-run", "--json", "-o", OUT / "tight_plan.mp4").stdout)
        self.assertNotIn("aselect", plan["commands"][-1])
        for name in ("tight_streams.mp4", "tight_streams.m4a"):
            out = OUT / name
            script("silence.py", gappy, "--preset", "veryfast", "-o", out)
            streams = json.loads(sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                                    "-of", "json", out).stdout)["streams"]
            for s in streams:
                # 7.0 s kept at the 2.22 default --margin 0.2 (6.75 s at 0.15); through 3.1.3 the
                # select graph kept both boundary frames of every range and wrote 7.1 s (#409)
                self.assertClose(float(s["duration"]), 7.0, 0.05, f"{name} {s['codec_type']}")

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

    def test_join_copy_joins_matching_clips_and_refuses_a_mismatch(self):
        """2.24: --copy --transition none joins clips with matching streams by stream copy (the
        joined packets are the clips' packets, nothing re-encoded), and refuses a clip that differs,
        or a picture and sound that end apart, by name and before anything is written."""
        clips = [self._av_clip(OUT / f"copy_{i}.mp4", 2, 2, 300 + 200 * i) for i in range(3)]
        out = OUT / "copy_joined.mp4"
        doc = json.loads(script("join.py", *clips, "--copy", "--transition", "none", "-o", out, "--overwrite", "--json").stdout)
        self.assertEqual((doc["status"], doc["mode"], doc["verified"]), ("completed", "copy", True), doc)
        packets = {v["property"]: v for v in doc["verification"] if v.get("step") == "join"}
        self.assertTrue(packets["video_packets"]["ok"] and packets["video_packets"]["measured"] == 3 * 60, packets)
        self.assertNotIn("libx264", " ".join(doc["commands"]))
        self.assertClose(probe(str(out))["video"]["duration"], 6.0, 0.1)
        wide = OUT / "copy_wide.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=96x48:r=30:d=2",
           "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", wide)
        short = self._av_clip(OUT / "copy_short_sound.mp4", 2, 1, 500)
        for other, what in ((wide, "width 96 (not 64)"), (short, "audio")):
            bad = OUT / "copy_bad.mp4"
            proc = script("join.py", clips[0], other, "--copy", "--transition", "none", "-o", bad, "--json", expect_fail=True)
            err = json.loads(proc.stdout)["error"]
            self.assertEqual((err["kind"], err["reason"]), ("input", "join_copy_mismatch"), err)
            self.assertIn(what, err["message"])
            self.assertFalse(bad.exists())
        proc = script("join.py", *clips[:2], "--copy", "-o", OUT / "copy_fade.mp4", "--json", expect_fail=True)
        self.assertIn("--transition none", json.loads(proc.stdout)["error"]["message"])
        proc = script("join.py", *clips[:2], "--copy", "--transition", "none", "--channels", "1", "-o", OUT / "copy_mono.mp4",
                      "--json", expect_fail=True)
        self.assertIn("--channels", json.loads(proc.stdout)["error"]["message"])
        # equal lengths, but the sound starts 0.3 s late: it ends 0.3 s after the picture
        late = OUT / "copy_late_sound.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x48:r=30:d=2",
           "-f", "lavfi", "-i", "sine=f=700:d=2", "-filter_complex", "[1]adelay=300:all=1,atrim=0:2.3,asetpts=PTS-STARTPTS[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-output_ts_offset", "0", late)
        proc = script("join.py", clips[0], late, "--copy", "--transition", "none", "-o", OUT / "copy_late.mp4", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "join_copy_mismatch")
        # equal ends, but the picture starts 0.3 s after the sound
        offset = OUT / "copy_late_picture.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-itsoffset", "0.3", "-f", "lavfi", "-i",
           "color=c=gray:s=64x48:r=30:d=1.7", "-f", "lavfi", "-i", "sine=f=700:d=2", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-fps_mode", "passthrough", offset)
        proc = script("join.py", clips[0], offset, "--copy", "--transition", "none", "-o", OUT / "copy_offset.mp4", "--json", expect_fail=True)
        self.assertIn("start or end", json.loads(proc.stdout)["error"]["message"])
        # Matroska states no stream length, but a start gap is still caught
        mk_ok, mk_late = OUT / "copy_ok.mkv", OUT / "copy_late_picture.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", clips[0], "-c", "copy", mk_ok)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", offset, "-c", "copy", mk_late)
        proc = script("join.py", mk_ok, mk_late, "--copy", "--transition", "none", "-o", OUT / "copy_offset.mkv", "--json", expect_fail=True)
        self.assertIn("start or end", json.loads(proc.stdout)["error"]["message"])
        # a cover picture between the video and the sound moves the audio to another stream index
        cover_img = OUT / "copy_cover.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1", cover_img)
        covered = OUT / "copy_covered.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", clips[1], "-i", cover_img, "-map", "0:v", "-map", "1",
           "-map", "0:a", "-c:v:0", "copy", "-c:v:1", "png", "-disposition:v:1", "attached_pic", "-c:a", "copy", covered)
        proc = script("join.py", clips[0], covered, "--copy", "--transition", "none", "-o", OUT / "copy_cover_join.mp4",
                      "--json", expect_fail=True)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual(err["reason"], "join_copy_mismatch", err)
        self.assertIn("lay(s) out their streams", err["message"])
        # a silent clip is placed in the copy join's output, as in a re-encoded one
        quiet = OUT / "copy_quiet.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x48:r=30:d=2",
           "-f", "lavfi", "-i", "sine=f=500:d=2", "-af", "volume=0", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", quiet)
        doc = json.loads(script("join.py", clips[0], quiet, clips[1], "--copy", "--transition", "none", "-o",
                                OUT / "copy_with_quiet.mp4", "--overwrite", "--json").stdout)
        self.assertEqual([(s["at"], s["end"]) for s in doc["silent"]], [(2.0, 4.0)], doc.get("silent"))

    def test_join_copy_measures_stream_spans_in_every_container(self):
        """2.24.1: the A/V end check read stated stream lengths, which Matroska/WebM never state (a
        1.5 s hole in the sound passed as verified) and MPEG-TS only estimate (every AAC .ts was
        refused); identical VP9 WebM clips were refused over "extradata"; --codec was silently
        ignored; dropped subtitle tracks were not reported."""
        a, b = self._av_clip(OUT / "span_a.mp4", 2, 2, 300), self._av_clip(OUT / "span_b.mp4", 2, 2, 500)
        short = self._av_clip(OUT / "span_short.mp4", 3, 1.5, 700)
        mka = {}
        for name, src in (("a", a), ("b", b), ("short", short)):
            mka[name] = OUT / f"span_{name}.mkv"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-c", "copy", mka[name])
        proc = script("join.py", mka["short"], mka["b"], "--copy", "--transition", "none", "-o", OUT / "span_bad.mkv",
                      "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "join_copy_mismatch")
        ts = []
        for src in (a, b):
            t = OUT / (src.stem + ".ts")
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-c", "copy", t)
            ts.append(t)
        if subprocess.run(["ffprobe", "-v", "error", "-show_format", str(ts[0])], capture_output=True).returncode == 0:
            # the static ffprobe 5.1.1 build cannot read MPEG-TS at all
            doc = json.loads(script("join.py", *ts, "--copy", "--transition", "none", "-o", OUT / "span_ts.ts",
                                    "--overwrite", "--json").stdout)
            self.assertTrue(doc["verified"], doc)
        webm = []
        for i in range(2):
            w = OUT / f"span_{i}.webm"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x48:r=30:d=1",
               "-f", "lavfi", "-i", "sine=d=1", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-c:a", "libopus", w)
            webm.append(w)
        doc = json.loads(script("join.py", *webm, "--copy", "--transition", "none", "-o", OUT / "span_vp9.webm",
                                "--overwrite", "--json").stdout)
        self.assertEqual((doc["mode"], doc["verified"]), ("copy", True), doc)
        proc = script("join.py", a, b, "--copy", "--transition", "none", "--codec", "hevc", "-o", OUT / "span_hevc.mp4",
                      "--json", expect_fail=True)
        self.assertIn("--codec", json.loads(proc.stdout)["error"]["message"])
        default_quality = re.search(r"--quality N.*?default (\d+)", script("join.py", "--help").stdout, re.S)
        for value in ([default_quality.group(1)] if default_quality else []) + ["30"]:
            proc = script("join.py", a, b, "--copy", "--transition", "none", "--quality", value, "-o", OUT / "span_q.mp4",
                          "--json", expect_fail=True)
            self.assertIn("--quality", json.loads(proc.stdout)["error"]["message"])
        sys.path.insert(0, str(SCRIPTS))
        import join as join_mod
        from unittest import mock
        def listing(*packets):
            return mock.patch.object(join_mod, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"packets": list(packets)}), ""))
        with listing({"pts_time": "0.000000", "duration_time": "0.033"}, {"duration_time": "0.033"}):
            self.assertIsNone(join_mod._stream_span("x.mkv", "V"))
        # a packet without a pts is placed by its dts
        with listing({"pts_time": "0.000000", "duration_time": "0.5"}, {"dts_time": "0.500000", "duration_time": "0.5"}):
            self.assertEqual(join_mod._stream_span("x.mkv", "V"), (0.0, 1.0))
        # a long clip: the head and the tail are read, and give the same span as every packet
        long_clip = self._av_clip(OUT / "span_long.mp4", 40, 40, 440)
        head_tail = join_mod._stream_span(str(long_clip), "V", 40.0)
        whole = join_mod._stream_span(str(long_clip), "V", 0.0)
        self.assertEqual(head_tail, whole)
        # the tail is sought from the file's start time: a clip whose clock starts at 100 s
        late = OUT / "span_late.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", long_clip, "-c", "copy",
           "-output_ts_offset", "100", late)
        start = float(probe(str(late)).get("start_time") or 0.0)
        self.assertGreater(start, 50)
        self.assertEqual(join_mod._stream_span(str(late), "V", 40.0, start), join_mod._stream_span(str(late), "V", 0.0))
        subs = []
        for src in (a, b):
            t = OUT / (src.stem + "_sub.mp4")
            srt = OUT / "span.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-i", srt, "-map", "0", "-map", "1",
               "-c", "copy", "-c:s", "mov_text", t)
            subs.append(t)
        doc = json.loads(script("join.py", *subs, "--copy", "--transition", "none", "-o", OUT / "span_subs.mp4",
                                "--overwrite", "--json").stdout)
        self.assertIs(doc.get("dropped_non_av_streams"), True, doc)

    def test_cut_remove_outside_the_file_is_refused(self):
        """2.24.1: --remove 15-20 on a 4 s file kept a range past the end and removed nothing, silently."""
        src = self._av_clip(OUT / "remove_outside.mp4", 4, 4, 400)
        proc = script("cut.py", src, "--remove", "15-20", "-o", OUT / "remove_outside_out.mp4", "--json", expect_fail=True)
        self.assertIn("outside the file", json.loads(proc.stdout)["error"]["message"])

    def test_cut_remove_keeps_the_rest(self):
        """2.24: --remove is --segments written the other way: dropping 1-2 and 3.5-4 (overlapping
        3.8-4 merged) from 6 s keeps 0-1, 2-3.5 and 4-6."""
        clip = self._av_clip(OUT / "remove_src.mp4", 6, 6, 440)
        out = OUT / "removed.mp4"
        doc = json.loads(script("cut.py", clip, "--remove", "3.5-4,1-2,3.8-4", "--accurate", "-o", out, "--overwrite", "--json").stdout)
        self.assertEqual(doc["status"], "completed", doc)
        self.assertClose(probe(str(out))["video"]["duration"], 4.5, 0.1)
        proc = script("cut.py", clip, "--remove", "0-10", "-o", OUT / "removed_all.mp4", "--json", expect_fail=True)
        self.assertIn("nothing would be left", json.loads(proc.stdout)["error"]["message"])
        for extra in (["--segments", "0-1"], ["--start", "0"]):
            proc = script("cut.py", clip, "--remove", "1-2", *extra, "-o", OUT / "removed_mix.mp4", "--json", expect_fail=True)
            self.assertIn("does not combine", json.loads(proc.stdout)["error"]["message"])
        proc = script("cut.py", clip, "--remove", "1-2", "--snap", "beats", "-o", OUT / "removed_snap.mp4", "--json", expect_fail=True)
        self.assertIn("--snap beats", json.loads(proc.stdout)["error"]["message"])
        # a range starting before 0 is clamped to the file, not refused: dropping -1..2 keeps 2-6
        lead = OUT / "removed_lead.mp4"
        doc = json.loads(script("cut.py", clip, "--remove=-1-2", "--accurate", "-o", lead, "--overwrite", "--json").stdout)
        self.assertEqual(doc["status"], "completed", doc)
        self.assertClose(probe(str(lead))["video"]["duration"], 4.0, 0.1)

    def _av_clip(self, out, picture, tone, freq, fps=30):
        """A tiny clip: `picture` s of colour at `fps`, `tone` s of a sine at `freq` Hz, AAC audio."""
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s=64x48:r={fps}:d={picture}",
           "-f", "lavfi", "-i", f"sine=f={freq}:d={tone}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out)
        return out

    @staticmethod
    def _tone_onset(path, freq):
        """When a tone at `freq` Hz is first heard: the end of the leading silence in a narrow band."""
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                               f"bandpass=f={freq}:width_type=q:w=8,bandpass=f={freq}:width_type=q:w=8,silencedetect=n=-35dB:d=0.1",
                               "-f", "null", "-"], capture_output=True, text=True)
        ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", proc.stderr)]
        return ends[0] if ends else 0.0

    def test_join_transition_keeps_each_clips_sound_with_its_picture(self):
        """Three clips of 5 s picture and 3 s of sound (a TTS line): each clip's sound must start
        where its picture does, 4.5 s and 9.0 s with a 0.5 s fade. join.py used to chain the raw
        audio lengths through acrossfade, so clip 2 spoke at ~2.5 s and clip 3 at ~5 s."""
        d = OUT / "join_sync"
        d.mkdir(exist_ok=True)
        freqs = (500, 1300, 2900)
        clips = [self._av_clip(d / f"c{f}.mp4", 5, 3, f) for f in freqs]
        out = d / "synced.mp4"
        doc = json.loads(script("join.py", *clips, "--transition", "fade", "--duration", "0.5", "--preset", "ultrafast",
                                "--json", "-o", out).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        for f, start in zip(freqs[1:], (4.5, 9.0)):
            self.assertClose(self._tone_onset(out, f), start, 0.1, f"the {f} Hz clip's sound starts with its picture")
        self.assertClose(probe(str(out))["video"]["duration"], 14.0, 0.05)

    def test_join_transition_keeps_a_picture_shorter_than_its_sound(self):
        """Audio past the picture: the clip lasts as long as its sound (the last frame held), so
        the next clip's picture is neither lost nor started early, and `verified` measures the
        video stream against the expected length."""
        d = OUT / "join_long_audio"
        d.mkdir(exist_ok=True)
        a = self._av_clip(d / "a.mp4", 2, 3, 700)
        b = self._av_clip(d / "b.mp4", 2, 2, 1900)
        out = d / "long.mp4"
        doc = json.loads(script("join.py", a, b, "--duration", "0.5", "--preset", "ultrafast", "--json", "-o", out).stdout)
        self.assertEqual(doc["expected_duration"], 4.5)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertClose(probe(str(out))["video"]["duration"], 4.5, 0.05)
        self.assertClose(self._tone_onset(out, 1900), 2.5, 0.1)

    def _moving_clip(self, out, picture, tone, freq, fps=30):
        """Like _av_clip, but every pixel changes on every frame (a luma ramp stepped by the frame
        number), so a held frame is told apart from the next one by its content, not assumed.
        testsrc2 is not enough at this size: its moving parts are a few pixels, and two adjacent
        frames measured 65 dB apart."""
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"nullsrc=s=64x48:r={fps}:d={picture},geq=lum='mod(N*23+X*2,256)':cb=128:cr=128",
           "-f", "lavfi", "-i", f"sine=f={freq}:d={tone}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out)
        return out

    @staticmethod
    def _gray_frames(path):
        """Every frame of `path`, decoded to 64x48 luma bytes."""
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough", "-vf",
                              "scale=64:48,format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE, check=True).stdout
        return [raw[i:i + 64 * 48] for i in range(0, len(raw), 64 * 48)]

    @staticmethod
    def _frame_psnr(a, b):
        """PSNR of two decoded luma frames (bytes), 99 when identical. MediaFixtures._psnr compares files."""
        mse = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
        return 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)

    @staticmethod
    def _pts_steps(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                              "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, text=True, check=True).stdout
        pts = [float(x.strip(",")) for x in out.split()]
        return {round(b - a, 4) for a, b in zip(pts, pts[1:])}

    def test_join_none_holds_a_picture_shorter_than_its_sound(self):
        """A plain cut (--transition none) of a clip whose sound runs 0.3 s past its
        picture. The concat filter starts the next clip after the longer stream, so the video had
        a 0.3 s hole (an odd average rate downstream) and the run still succeeded. Each clip now
        lasts as long as its sound, its last frame held, as the crossfade path already does."""
        d = OUT / "join_none_hold"
        d.mkdir(exist_ok=True)
        a = self._moving_clip(d / "a.mp4", 3, 3.3, 700)
        b = self._moving_clip(d / "b.mp4", 3, 3.3, 1900)
        out = d / "held.mp4"
        doc = json.loads(script("join.py", a, b, "--transition", "none", "--preset", "ultrafast", "--json",
                                "-o", out).stdout)
        self.assertEqual(doc["expected_duration"], 6.6, "two clips of 3.3 s: each lasts as long as its sound")
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(self._pts_steps(out), {0.0333}, "no hole in the video timeline")
        frames = self._gray_frames(out)
        self.assertEqual(len(frames), 2 * 99, "3.3 s per clip at 30 fps")
        for i in range(90, 99):
            self.assertGreaterEqual(self._frame_psnr(frames[i], frames[89]), 45.0, f"frame {i} holds clip a's last frame")
        self.assertLess(self._frame_psnr(frames[89], frames[88]), 35.0, "the premise: the picture moves every frame")
        self.assertLess(self._frame_psnr(frames[99], frames[89]), 35.0, "clip b starts with its own picture")
        self.assertClose(self._tone_onset(out, 1900), 3.3, 0.1)

    def test_join_none_trims_a_sound_tail_under_a_frame(self):
        """The other side of the hold rule: an AAC tail of 20 ms is not held for -- each clip keeps its
        90 frames and nothing is inserted between them."""
        d = OUT / "join_none_tail"
        d.mkdir(exist_ok=True)
        a = self._moving_clip(d / "a.mp4", 3, 3.02, 700)
        b = self._moving_clip(d / "b.mp4", 3, 3.02, 1900)
        out = d / "tail.mp4"
        doc = json.loads(script("join.py", a, b, "--transition", "none", "--preset", "ultrafast", "--json",
                                "-o", out).stdout)
        self.assertEqual(doc["expected_duration"], 6.0, "the 20 ms tails are trimmed, not counted")
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(self._pts_steps(out), {0.0333})
        self.assertEqual(len(self._gray_frames(out)), 2 * 90)

    def test_join_none_starts_a_late_picture_at_its_cut(self):
        """A clip whose picture starts after 0 (a cut part whose first video packet sits at 0.08 s): the
        audio chains started at 0 but the video chain kept that offset, and the concat filter placed it
        after the previous clip -- a one-frame hole and 29.82 fps where 30 was asked (video-editing-skill's
        CONCAT refused the file). Each clip's picture now starts at 0 like its sound."""
        d = OUT / "join_none_late"
        d.mkdir(exist_ok=True)
        a = self._moving_clip(d / "a.mp4", 3, 3, 700)
        b = self._moving_clip(d / "b.mp4", 3, 3, 1900)
        late = d / "b_late.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-itsoffset", "0.08", "-i", str(b), "-i", str(b),
                        "-map", "0:v", "-map", "1:a", "-c", "copy", str(late)], check=True)
        start = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=start_time",
                                "-of", "csv=p=0", str(late)], stdout=subprocess.PIPE, text=True, check=True).stdout
        self.assertAlmostEqual(float(start), 0.08, places=2, msg="the premise: the picture starts at 0.08 s")
        out = d / "late.mp4"
        doc = json.loads(script("join.py", a, late, "--transition", "none", "--preset", "ultrafast", "--json",
                                "-o", out).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(self._pts_steps(out), {0.0333}, "no hole at the cut")
        self.assertEqual(len(self._gray_frames(out)), 2 * 90)

    def test_join_dissolve_of_short_parts_keeps_the_frame_count(self):
        """Two 1 s parts at 30 fps whose AAC sound runs 20 ms past the picture (a cut part) dissolved
        over 0.3 s: 30 + 30 - 9 = 51 frames. Offsetting by the container length added frames and
        cut the dissolve short."""
        d = OUT / "join_frames"
        d.mkdir(exist_ok=True)
        a = self._av_clip(d / "a.mp4", 1, 1.02, 440)
        b = self._av_clip(d / "b.mp4", 1, 1.02, 880)
        out = d / "parts.mp4"
        script("join.py", a, b, "--transition", "dissolve", "--duration", "0.3", "--preset", "ultrafast", "-o", out)
        self.assertEqual(probe(str(out))["video"]["nb_frames"], 51)

    @staticmethod
    def _frame_pts(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                              "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, text=True, check=True).stdout
        return [float(x.strip(",")) for x in out.split()]

    def test_join_clip_lengths_are_whole_frames_and_samples(self):
        """#455, the class "a frame-exact clip length written as rounded seconds into a filter": 5
        frames at 30 fps are 0.166667 s, which `trim=duration=0.167` rounded up, and the concat
        filter started the next clip after it -- 60 such clips left one-frame holes from about 8 s.
        Each clip is now cut to its frames (`trim=end_frame`) and its sound to the samples those
        frames last, at a whole rate and an NTSC one: every source frame once, in order, no hole,
        and the sound as long as the picture."""
        from fractions import Fraction
        d = OUT / "join_frame_exact"
        d.mkdir(exist_ok=True)
        for rate in ("30", "30000/1001"):
            with self.subTest(rate=rate):
                q, tag = Fraction(rate), rate.replace("/", "_")
                # NUT keeps the source's frame times exact (Matroska rounds them to the millisecond)
                src = d / f"src_{tag}.nut"
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"nullsrc=s=64x48:r={rate},geq=lum='mod(N*23+X*2,256)':cb=128:cr=128", "-f", "lavfi", "-i",
                   "sine=f=440:r=48000", "-frames:v", "300", "-t", "11", "-c:v", "ffv1", "-c:a", "pcm_s16le", src)
                clips = []
                for k in range(60):
                    # FFV1 + PCM in MOV: every frame a keyframe (no reordering delay), exact frame
                    # times (Matroska rounds them to the millisecond), and a sound exactly as long as
                    # the clip's frames. An H.264 clip in MP4/MOV is read with different stream
                    # starts by FFmpeg 7.1 (each 5-frame clip was held to 7 frames, AAC or PCM:
                    # #475), which is not what this test measures
                    clip = d / f"c{tag}_{k:02d}.mov"
                    s0, s1 = round(5 * k * 48000 / q), round(5 * (k + 1) * 48000 / q)
                    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vf",
                       f"trim=start_frame={5 * k}:end_frame={5 * k + 5},setpts=PTS-STARTPTS", "-af",
                       f"atrim=start_sample={s0}:end_sample={s1},asetpts=PTS-STARTPTS", "-c:v", "ffv1",
                       "-c:a", "pcm_s16le", "-r", rate, clip)
                    clips.append(clip)
                first = self._frame_pts(clips[0])
                self.assertEqual(len(first), 5, f"the premise: 5 frames a clip (pts {first}, "
                                 f"{ {k: v for k, v in probe(str(clips[0])).items() if k in ('video', 'audio', 'duration')} })")
                out = d / f"joined_{tag}.mp4"
                doc = json.loads(script("join.py", *clips, "--transition", "none", "--preset", "ultrafast", "--json",
                                        "-o", out).stdout)
                self.assertTrue(doc["verified"], doc["verification"])
                pts = self._frame_pts(out)
                if len(pts) != 300:
                    # what this FFmpeg reports for one clip, for #475 (the clip-length rule)
                    from _common.decision import stream_starts
                    m0 = probe(str(clips[0]))
                    seen = {"clip_frames": doc.get("clip_frames"), "stream_starts": stream_starts(m0),
                            "video": {k: m0["video"].get(k) for k in ("duration", "start_time", "fps", "nb_frames")},
                            "audio": {k: (m0.get("audio") or {}).get(k) for k in ("duration", "start_time")},
                            "duration": m0.get("duration")}
                    self.fail(f"total frames {len(pts)} != the clips' 300: {seen}")
                step = 1 / float(q)
                worst = max(abs((b - a) - step) for a, b in zip(pts, pts[1:]))
                self.assertLess(worst, 0.002, f"no hole in the picture's timeline (worst step off by {worst:.4f} s)")
                ours, theirs = self._gray_frames(out), self._gray_frames(src)
                self.assertEqual(len(ours), 300)
                moved = [i for i in range(300) if self._frame_psnr(ours[i], theirs[i]) < 35.0]
                self.assertEqual(moved, [], "every source frame once, in order: no repeated and no lost frame")
                m = probe(str(out))
                self.assertClose(m["audio"]["duration"], m["video"]["duration"], 1024 / 48000,
                                 "the sound lasts as long as the picture, to one AAC frame")
                self.assertClose(m["video"]["duration"], 300 / float(q), 0.5 / float(q))
                self.assertEqual((doc["frame_rate"], doc["clip_frames"], doc["transition_frames"]),
                                 (f"{q.numerator}/{q.denominator}", [5] * 60, 0))
                cmd = doc["commands"][0] if isinstance(doc["commands"][0], str) else " ".join(doc["commands"][0])
                self.assertIn("trim=end_frame=5[", cmd)
                self.assertNotIn("trim=duration", cmd)

    def test_join_transition_starts_on_its_frame(self):
        """#468, the same class through xfade: its offset was `sum(lens) - i*d` written to the
        millisecond, and xfade starts on the first frame at or after the offset, so 2.566667 s
        written 2.567 started the fade a frame late (92 + 60 frames at 30 fps with 0.5 s: 138
        frames, where 91 + 60 gave the exact 136). Offsets are now frames of the output rate,
        written rounded down; a chain of clips at 30000/1001 lands on every frame too."""
        from fractions import Fraction
        d = OUT / "join_xfade_frames"
        d.mkdir(exist_ok=True)
        for rate, counts, want in (("30", (92, 60), 137), ("30", (91, 60), 136),
                                   ("30000/1001", (92, 61, 47, 77), 92 + 61 + 47 + 77 - 3 * 15)):
            with self.subTest(rate=rate, counts=counts):
                q = Fraction(rate)
                clips = []
                for k, nf in enumerate(counts):
                    clip = d / f"{rate.replace('/', '_')}_{k}_{nf}.mp4"
                    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                       f"testsrc2=s=64x48:r={rate}", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-frames:v", str(nf),
                       "-t", f"{nf / float(q):.6f}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip)
                    clips.append(clip)
                out = d / f"x_{rate.replace('/', '_')}_{'_'.join(map(str, counts))}.mp4"
                doc = json.loads(script("join.py", *clips, "--transition", "fade", "--duration", "0.5", "--preset",
                                        "ultrafast", "--json", "-o", out).stdout)
                self.assertEqual(len(self._frame_pts(out)), want)
                self.assertEqual((doc["clip_frames"], doc["transition_frames"]), (list(counts), 15))
                cmd = doc["commands"][0] if isinstance(doc["commands"][0], str) else " ".join(doc["commands"][0])
                start = 0
                for nf, offset in zip(counts, re.findall(r"xfade=[^;\[]*:offset=([0-9.]+)", cmd)):
                    start += nf - 15
                    self.assertLessEqual(Fraction(offset), start / q, "the offset is never after its frame")
                    self.assertGreater(Fraction(offset), (start - Fraction(1, 100)) / q)
                self.assertTrue(doc["verified"], doc["verification"])
                m = probe(str(out))
                self.assertClose(m["audio"]["duration"], m["video"]["duration"], 1024 / 48000,
                                 "acrossfade overlaps the sound by the frames xfade overlaps")

    def test_join_reads_a_clip_without_a_last_frame_duration_at_its_own_rate(self):
        """#475: FFmpeg 7.1 read a 5-frame MOV with no duration for its last frame as 0.1333 s at
        37.5 fps (avg_frame_rate = 5 / 0.1333). join.py took that as the join's rate (75/2) and,
        at it, read the 0.1667 s sound as running past the picture and held every clip to 7
        frames: 60 such clips gave 418 frames for 300. The declared r_frame_rate is used when the
        average is short by exactly the last frame, and the picture counts every frame it holds."""
        import importlib
        from fractions import Fraction
        sys.path.insert(0, str(SCRIPTS))
        join = importlib.import_module("join")
        for rate, dur, avg in (("30/1", 0.133333, "75/2"), ("30000/1001", 0.133467, "37463/1000")):
            with self.subTest(rate=rate):
                q = Fraction(rate)
                video = {"nb_frames": 5, "duration": dur, "fps": float(Fraction(avg)), "r_frame_rate": rate,
                         "avg_frame_rate": avg}
                meta = {"video": video, "audio": {"duration": float(5 / q)}, "duration": float(5 / q)}
                got = join.output_rate(video["fps"], video, False)
                self.assertEqual(got, q, "the join runs at the clip's declared rate, not the short average")
                whole = join.with_whole_picture(meta, got)
                self.assertEqual(join.clip_frames(whole, join.clip_length(whole, float(got)), got), 5)
        # a clip whose duration holds every frame is left as it is, and --fps still decides
        full = {"nb_frames": 5, "duration": 5 / 30, "fps": 30.0, "r_frame_rate": "30/1", "avg_frame_rate": "30/1"}
        self.assertIs(join.with_whole_picture({"video": full}, Fraction(30))["video"], full)
        # ... also at another output rate: 5/30 s is 4 frames at 24, but the clip is checked at its
        # own declared 30 fps, so a complete clip is not stretched to 5/24 s under --fps 24
        self.assertIs(join.with_whole_picture({"video": full}, Fraction(24))["video"], full)
        self.assertEqual(join.output_rate(25.0, full, True), Fraction(25))

    def test_join_short_h264_mp4_clips_keep_their_frames(self):
        """#475's first report: 5-frame H.264 + AAC clips in MP4, as a camera or an export writes
        them, joined with no transition. 6.1 gave 5 frames each; 7.1 gave 7 (418 frames for 60
        clips). Diagnostics print what probe() read, so a failure on another FFmpeg says why."""
        from fractions import Fraction
        d = OUT / "join_h264_short"
        d.mkdir(exist_ok=True)
        sys.path.insert(0, str(SCRIPTS))
        from _common import probe
        from _common.decision import stream_starts
        for rate in ("30", "30000/1001"):
            with self.subTest(rate=rate):
                q = Fraction(rate)
                clips = []
                for k in range(12):
                    clip = d / f"c{rate.replace('/', '_')}_{k}.mp4"
                    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                       f"testsrc2=s=64x48:r={rate}", "-f", "lavfi", "-i", "sine=f=440:r=48000",
                       "-frames:v", "5", "-t", f"{5 / float(q):.6f}", "-c:v", "libx264", "-qp", "0",
                       "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", clip)
                    clips.append(clip)
                out = d / f"joined_{rate.replace('/', '_')}.mp4"
                doc = json.loads(script("join.py", *clips, "--transition", "none", "--json", "-o", out).stdout)
                m = probe(str(clips[0]))
                diag = {"video": {k: m["video"].get(k) for k in ("start_time", "duration", "nb_frames", "fps",
                                                                  "r_frame_rate", "avg_frame_rate")},
                        "audio": {k: (m.get("audio") or {}).get(k) for k in ("start_time", "duration")},
                        "stream_starts": stream_starts(m), "clip_frames": doc.get("clip_frames"),
                        "frame_rate": doc.get("frame_rate")}
                self.assertEqual(doc.get("clip_frames"), [5] * 12, f"clip diagnostics: {diag}")
                counted = sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                             "stream=nb_read_frames", "-of", "csv=p=0", out).stdout.strip().split(",")[0]
                self.assertEqual(int(counted), 60, f"clip diagnostics: {diag}")

    def test_join_of_cut_and_cropped_parts_keeps_every_frame(self):
        """#479: cut a 7.1667 s H.264 + AAC MP4 (215 frames at 30) into three parts, crop each,
        join them with no transition. A dependent project saw 3 frames lost on FFmpeg 8.0.1 (7.066
        s for 7.166) while 6.1 kept all 215. Diagnostics print each part as probe() read it."""
        d = OUT / "join_479"
        d.mkdir(exist_ok=True)
        sys.path.insert(0, str(SCRIPTS))
        from _common import probe
        src = d / "src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30",
           "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "7.166667", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", src)
        parts = []
        for name, span in (("a", ("--start", "0", "--end", "2.4")), ("b", ("--start", "2.4", "--end", "4.8")),
                           ("c", ("--start", "4.8"))):
            cut = d / f"{name}_cut.mp4"
            script("cut.py", src, *span, "--accurate", "-o", cut)
            cropped = d / f"{name}.mp4"
            script("crop.py", cut, "--x", "40", "--y", "0", "--width", "240", "--height", "180", "-o", cropped)
            parts.append(cropped)
        def frames(path):
            out = sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                     "stream=nb_read_frames", "-of", "csv=p=0", path).stdout.strip().split(",")[0]
            return int(out)
        diag = []
        for p in parts:
            m = probe(str(p))
            diag.append({"frames": frames(p), "video": {k: m["video"].get(k) for k in (
                "start_time", "duration", "nb_frames", "fps", "r_frame_rate", "avg_frame_rate")},
                "audio": {k: (m.get("audio") or {}).get(k) for k in ("start_time", "duration")}})
        out = d / "joined.mp4"
        doc = json.loads(script("join.py", *parts, "--transition", "none", "--json", "-o", out).stdout)
        detail = f"parts: {diag}; clip_frames: {doc.get('clip_frames')}; frame_rate: {doc.get('frame_rate')}"
        self.assertEqual([p["frames"] for p in diag], [72, 72, 71], detail)
        self.assertEqual(doc.get("clip_frames"), [72, 72, 71], detail)
        self.assertEqual(frames(out), 215, detail)

    def test_join_sound_overlaps_add_up_to_the_picture(self):
        """A transition whose length is not a whole number of samples: 9 frames at 30000/1001 is
        14414.4 samples. Each acrossfade's overlap was rounded on its own (14414), so the sound
        kept 0.4 samples more than the picture per transition (five 90-frame clips: 663,064
        samples for a 414-frame picture of 663,062.4). Every clip's samples and every overlap are
        now differences of the output's rounded frame positions, so the planned sound is the
        picture's length to the sample. --duration 0 with a transition is one frame, not
        acrossfade=ns=0 (which FFmpeg refuses)."""
        from fractions import Fraction
        d = OUT / "join_xfade_samples"
        d.mkdir(exist_ok=True)
        q = Fraction(30000, 1001)
        clips = []
        for k in range(5):
            clip = d / f"c{k}.mp4"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "testsrc2=s=64x48:r=30000/1001", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-frames:v", "90",
               "-t", f"{90 / float(q):.6f}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip)
            clips.append(clip)
        for duration, tframes in (("0.3", 9), ("0", 1)):
            with self.subTest(duration=duration):
                out = d / f"x_{duration}.mp4"
                doc = json.loads(script("join.py", *clips, "--transition", "fade", "--duration", duration,
                                        "--preset", "ultrafast", "--json", "-o", out).stdout)
                self.assertEqual(doc["transition_frames"], tframes)
                cmd = doc["commands"][0] if isinstance(doc["commands"][0], str) else " ".join(doc["commands"][0])
                kept = sum(int(n) for n in re.findall(r"atrim=end_sample=(\d+)", cmd))
                overlap = sum(int(n) for n in re.findall(r"acrossfade=ns=(\d+)", cmd))
                self.assertNotIn("acrossfade=ns=0", cmd)
                frames_out = 5 * 90 - 4 * tframes
                self.assertEqual(kept - overlap, round(frames_out * 48000 / q),
                                 "the planned sound is the picture's length to the sample")
                self.assertEqual(len(self._frame_pts(out)), frames_out)
                m = probe(str(out))
                self.assertClose(m["audio"]["duration"], m["video"]["duration"], 1024 / 48000,
                                 "the written sound lasts as long as the picture, to one AAC frame")
        r = script("join.py", *clips[:2], "--transition", "fade", "--duration", "-1", "--json",
                   "-o", d / "neg.mp4", expect_fail=True)
        self.assertNotEqual(r.returncode, 0, "a negative --duration is refused, not taken as one frame")
        self.assertIn("--duration must be 0 or more", r.stdout + r.stderr)

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
        hdr_proc = script("fit.py", self.hdr, "--aspect", "9:16", "--fit", "blur",
                          "--dry-run", "--json", "-o", str(OUT / "blur_hdr.mp4"))
        hdr_plan = json.loads(hdr_proc.stdout)
        self.assertTrue(any("eq=brightness" in c for c in sdr_plan["commands"]))
        self.assertTrue(any("boxblur" in c for c in hdr_plan["commands"]))
        self.assertFalse(any("eq=brightness" in c for c in hdr_plan["commands"]),
                         "an HDR source must not be dimmed by an SDR-shaped eq")
        self.assertIn("not the -15% dim it is on SDR", hdr_proc.stderr)
        self.assertNotIn("-15%%", hdr_proc.stderr)

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

    def test_join_warns_on_short_segments_and_duplicates(self):
        """A segment shorter than 2 frames (audio-only: 0.05 s) and a path listed twice used to
        join as verified with nothing said. Both are warnings, not refusals (repeating a clip can
        be intended): `short_segments` [{index, path, duration}] and `duplicates` [{path,
        indices}], always present, plus a note each. The join command is unchanged."""
        d = OUT / "join_short_dup"
        d.mkdir(exist_ok=True)
        ff = ("ffmpeg", "-y", "-hide_banner", "-loglevel", "error")
        sh(*ff, "-f", "lavfi", "-i", "testsrc=s=64x64:r=25:d=1", "-f", "lavfi", "-i", "sine=d=1",
           "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", d / "a.mp4")
        sh(*ff, "-f", "lavfi", "-i", "testsrc=s=64x64:r=25", "-f", "lavfi", "-i", "sine",
           "-frames:v", "1", "-t", "0.04", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", d / "b.mp4")
        sh(*ff, "-f", "lavfi", "-i", "sine=d=1", d / "a.wav")
        sh(*ff, "-f", "lavfi", "-i", "sine=d=0.02", d / "b.wav")
        doc = json.loads(script("join.py", d / "a.mp4", d / "b.mp4", d / "a.mp4", "--transition", "none",
                                "--json", "-o", d / "v.mp4").stdout)
        self.assertEqual((doc["status"], doc["clips"]), ("completed", 3))
        self.assertEqual([(s["index"], Path(s["path"]).name) for s in doc["short_segments"]], [(1, "b.mp4")])
        self.assertLess(doc["short_segments"][0]["duration"], 2 / 25)
        self.assertEqual([(Path(x["path"]).name, x["indices"]) for x in doc["duplicates"]], [("a.mp4", [0, 2])])
        self.assertTrue(any("more than once" in n for n in doc["notes"]))
        self.assertTrue(any("shorter than 2 frames" in n for n in doc["notes"]))
        doc = json.loads(script("join.py", d / "a.wav", d / "b.wav", "--transition", "none",
                                "--json", "-o", d / "o.wav").stdout)
        self.assertEqual([Path(s["path"]).name for s in doc["short_segments"]], ["b.wav"])
        self.assertEqual(doc["duplicates"], [])
        # clean: both keys present and empty
        doc = json.loads(script("join.py", d / "a.wav", d / "a.wav", "--transition", "none",
                                "--json", "-o", d / "c.wav").stdout)
        self.assertEqual(doc["short_segments"], [])
        self.assertEqual(len(doc["duplicates"]), 1)
        doc = json.loads(script("join.py", d / "a.mp4", d / "a.mp4", "--transition", "none", "--dry-run",
                                "--json", "-o", d / "dry.mp4").stdout)
        self.assertEqual(doc["short_segments"], [])
        shutil.rmtree(d, ignore_errors=True)

    def test_join_on_silent_names_a_silent_segment(self):
        """Reported from the same VPS shorts pipeline: TTS sometimes writes a valid but fully
        silent wav, which passes the missing/empty/unreadable preflight, and the video shipped
        with no narration. Every input with audio is measured (peak dBFS): --on-silent warn
        (default) joins it and names it under `silent`, fail refuses it in the one kind-input
        document, skip leaves it out under `skipped`. A clip without audio is never silent."""
        d = OUT / "join_silent"
        d.mkdir(exist_ok=True)
        for i in (1, 3):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"sine=frequency={300 * i}:sample_rate=24000", "-t", "1.5", d / f"line{i}.wav")
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "anullsrc=r=24000:cl=mono", "-t", "1.5", d / "line2.wav")
        # a quiet but audible line: about -40 dBFS peak (sine is -18 dBFS)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "sine=frequency=500:sample_rate=24000", "-t", "1.5", "-af", "volume=-22dB", d / "quiet.wav")
        (d / "parts.txt").write_text("line1.wav\nline2.wav\nline3.wav\n", encoding="utf-8")
        # warn (default): joined, named, verified untouched
        doc = json.loads(script("join.py", "--list", d / "parts.txt", "--transition", "none", "--json",
                                "-o", d / "warn.wav").stdout)
        self.assertEqual((doc["status"], doc["clips"], doc["verified"]), ("completed", 3, True))
        self.assertEqual([(s["index"], Path(s["path"]).name) for s in doc["silent"]], [(1, "line2.wav")])
        self.assertLessEqual(doc["silent"][0]["peak_db"], -50)
        self.assertTrue(any("line2.wav" in n for n in doc["notes"]))
        self.assertTrue((d / "warn.wav").exists())
        # where it sits in the output: after line1 (1.5 s), 1.5 s long
        self.assertEqual((doc["silent"][0]["at"], doc["silent"][0]["end"]), (1.5, 3.0))
        self.assertNotIn("intended", doc["silent"][0])
        # --allow-silent: a planned pause, joined even under fail, marked intended, no note
        doc = json.loads(script("join.py", "--list", d / "parts.txt", "--transition", "none", "--on-silent", "fail",
                                "--allow-silent", "2", "--json", "-o", d / "allow.wav").stdout)
        self.assertEqual((doc["status"], doc["clips"]), ("completed", 3))
        self.assertEqual([(s["index"], s["intended"], s["at"]) for s in doc["silent"]], [(1, True, 1.5)])
        self.assertFalse(any("line2.wav" in n for n in doc.get("notes", [])))
        proc = script("join.py", "--list", d / "parts.txt", "--allow-silent", "4", "--json",
                      "-o", d / "bad.wav", expect_fail=True)
        self.assertIn("--allow-silent", json.loads(proc.stdout)["error"]["message"])
        # fail: one kind-input refusal naming it, nothing written
        proc = script("join.py", "--list", d / "parts.txt", "--transition", "none", "--on-silent", "fail",
                      "--json", "-o", d / "fail.wav", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["error"]["kind"], doc["commands"]), ("input", []))
        self.assertEqual([Path(p["path"]).name for p in doc["problems"]], ["line2.wav"])
        self.assertTrue(doc["problems"][0]["reason"].startswith("silent (peak -"))
        self.assertFalse((d / "fail.wav").exists())
        # skip: joined without it, listed under skipped
        doc = json.loads(script("join.py", "--list", d / "parts.txt", "--transition", "none", "--on-silent", "skip",
                                "--json", "-o", d / "skip.wav").stdout)
        self.assertEqual((doc["clips"], doc["silent"]), (2, []))
        self.assertEqual([Path(p["path"]).name for p in doc["skipped"]], ["line2.wav"])
        self.assertAlmostEqual(doc["probe"]["duration"], 3.0, delta=0.05)
        # threshold: -40 dBFS is audible at the default, silent at -35
        doc = json.loads(script("join.py", d / "line1.wav", d / "quiet.wav", "--transition", "none",
                                "--json", "-o", d / "q1.wav").stdout)
        self.assertEqual(doc["silent"], [])
        doc = json.loads(script("join.py", d / "line1.wav", d / "quiet.wav", "--transition", "none",
                                "--silence-threshold", "-35", "--json", "-o", d / "q2.wav").stdout)
        self.assertEqual([Path(s["path"]).name for s in doc["silent"]], ["quiet.wav"])
        # a clip with no audio stream is never silent
        for n in (1, 2):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "testsrc2=size=160x120:rate=25", "-t", "1", "-an", "-pix_fmt", "yuv420p", d / f"mute{n}.mp4")
        doc = json.loads(script("join.py", d / "mute1.mp4", d / "mute2.mp4", "--transition", "none", "--on-silent", "fail",
                                "--json", "-o", d / "mute.mp4").stdout)
        self.assertEqual((doc["status"], doc["silent"]), ("completed", []))

    def test_join_plain_cut_dry_run_names_a_pending_clips_trim_as_a_placeholder(self):
        """2.4.1 trims/holds every plain-cut clip to clip_length, so a pending clip's planned
        `trim=duration=0.000` is the unmeasured stub's 0 s, not the cut. The plan says so (#77),
        as the crossfade path already does for its offsets."""
        d = OUT / "join_pending_video"
        d.mkdir(exist_ok=True)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25",
           "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           d / "a.mp4")
        doc = json.loads(script("join.py", d / "a.mp4", d / "later.mp4", "--transition", "none", "--dry-run", "--json",
                                "-o", d / "plan.mp4").stdout)
        self.assertTrue(any("planned trim lengths count each pending input as 0 s" in n for n in doc["notes"]), doc["notes"])
        self.assertFalse((d / "plan.mp4").exists())

    def test_join_dry_run_plans_on_pending_segments(self):
        """Under --dry-run a segment that does not exist yet is an earlier step's output. Its
        probe is the dry-run stub, whose (0x0) video stream used to decide the mode: one pending
        TTS line failed the plan with "tts_01.wav has no video stream while tts_03.wav has one",
        and a list of nothing but pending .wav lines planned a libx264 join into voice.wav. A
        pending segment's extension now stands in for its streams, rate and layout come from the
        segments that exist, and it is planned on and named under `pending` -- never `skipped`
        -- in both --on-missing modes; a real run still decides on the file as it then is."""
        d = OUT / "join_pending"
        d.mkdir(exist_ok=True)
        for i in (1, 2):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"sine=frequency={300 * i}:sample_rate=24000", "-t", "1.5", d / f"tts_0{i}.wav")
        for gone in ("tts_03.wav", "intro.mp4", "later.wav"):
            (d / gone).unlink(missing_ok=True)  # what the earlier steps have not written yet
        (d / "parts.txt").write_text("tts_01.wav\ntts_02.wav\ntts_03.wav\n", encoding="utf-8")
        # the pending line first as well: the stub's (unmeasured) rate and layout must not become the plan's
        (d / "first.txt").write_text("tts_03.wav\ntts_01.wav\ntts_02.wav\n", encoding="utf-8")
        for lst, at in (("parts.txt", 2), ("first.txt", 0)):
            for mode, then in (("fail", "refuses the join if one is still missing"), ("skip", "skips one that is still missing")):
                proc = script("join.py", "--list", d / lst, "--transition", "none", "--on-missing", mode,
                              "--dry-run", "--json", "-o", d / "voice_plan.wav")
                doc = json.loads(proc.stdout)
                case = f"{lst} --on-missing {mode}"
                self.assertEqual((doc["status"], doc["mode"], doc["clips"]), ("completed", "audio", 3), case)
                self.assertEqual((doc["sample_rate"], doc["channels"]), (24000, 1), f"{case}: planned from the segments that exist, not the stub")
                self.assertEqual([(p["index"], Path(p["path"]).name) for p in doc["pending"]], [(at, "tts_03.wav")], case)
                self.assertEqual(doc["skipped"], [], f"{case}: a pending segment is planned on, not left out")
                self.assertIsNone(doc["expected_duration"], f"{case}: the pending line's length is unknown, not 0 s")
                self.assertIn("tts_03.wav", doc["commands"][0])
                self.assertNotIn("libx264", doc["commands"][0])
                self.assertTrue(any("tts_03.wav" in n and f"a real run {then}" in n for n in doc["notes"]), doc["notes"])
                self.assertIn("tts_03.wav does not exist yet", proc.stderr)
        self.assertFalse((d / "voice_plan.wav").exists())
        # skipping the pending line would leave one input: the note predicts the refusal the real run gives
        (d / "two.txt").write_text("tts_01.wav\ntts_03.wav\n", encoding="utf-8")
        doc = json.loads(script("join.py", "--list", d / "two.txt", "--transition", "none", "--on-missing", "skip",
                                "--dry-run", "--json", "-o", d / "two.wav").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertTrue(any("refuses the join if that leaves fewer than two inputs" in n for n in doc["notes"]), doc["notes"])
        proc = script("join.py", "--list", d / "two.txt", "--transition", "none", "--on-missing", "skip",
                      "--json", "-o", d / "two.wav", expect_fail=True)
        self.assertIn("nothing to join", json.loads(proc.stdout)["error"]["message"])
        # a pending .mp4 is expected to hold a picture: next to measured audio it is the mix a real
        # run refuses, and a pending .wav next to measured video likewise
        for inputs, out, says in (((d / "tts_01.wav", d / "intro.mp4"), "mix.wav",
                                   "tts_01.wav has no video stream while " + str(d / "intro.mp4") + ", which does not exist yet, is expected to have one"),
                                  ((self.src, d / "later.wav"), "mix.mp4",
                                   str(d / "later.wav") + " does not exist yet, and its audio extension says it will have no video stream while " + str(self.src) + " has one")):
            proc = script("join.py", *inputs, "--transition", "none", "--dry-run", "--json", "-o", d / out, expect_fail=True)
            err = json.loads(proc.stdout)["error"]
            self.assertEqual(err["kind"], "input")
            self.assertIn(says, err["message"])
        # a mix names the input measured to have a picture, never a pending file as if it had one
        (d / "mixed.txt").write_text(f"tts_01.wav\nnot_yet.mp4\n{self.src}\n", encoding="utf-8")
        proc = script("join.py", "--list", d / "mixed.txt", "--dry-run", "--json", "-o", d / "mixed.mp4", expect_fail=True)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn(f"while {self.src} has one", err["message"])
        self.assertNotIn("not_yet.mp4", err["message"])
        # nothing written yet at all: the extensions decide, and .wav plans an audio join
        (d / "later.txt").write_text("gen_01.wav\ngen_02.wav\n", encoding="utf-8")
        doc = json.loads(script("join.py", "--list", d / "later.txt", "--dry-run", "--json", "-o", d / "later.wav").stdout)
        self.assertEqual((doc["mode"], len(doc["pending"]), doc["expected_duration"]), ("audio", 2, None))
        self.assertFalse(any("libx264" in c for c in doc["commands"]), doc["commands"])
        self.assertIn("acrossfade", doc["commands"][0])
        self.assertTrue(any("file extensions" in n for n in doc["notes"]), doc["notes"])
        # every audio extension this skill reads counts, not only the ones it writes: a pending
        # .aiff (macOS `say -o`) was taken for a file with a picture and the plan refused as a mix
        for i in (1, 2):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", f"sine=frequency={300 * i}:sample_rate=24000", "-t", "1.5", d / f"say_0{i}.aiff")
        (d / "say_03.aiff").unlink(missing_ok=True)
        (d / "say.txt").write_text("say_01.aiff\nsay_02.aiff\nsay_03.aiff\n", encoding="utf-8")
        doc = json.loads(script("join.py", "--list", d / "say.txt", "--dry-run", "--json", "-o", d / "say.wav").stdout)
        self.assertEqual((doc["status"], doc["mode"], len(doc["pending"])), ("completed", "audio", 1))
        (d / "say_new.txt").write_text("new_01.aiff\nnew_02.caf\n", encoding="utf-8")
        doc = json.loads(script("join.py", "--list", d / "say_new.txt", "--dry-run", "--json", "-o", d / "say.wav").stdout)
        self.assertEqual(doc["mode"], "audio", "nothing written yet: .aiff and .caf plan an audio join")
        # a pending FIRST clip of a video join: its stub is unmeasured, so the planned frame, rate
        # and xfade offsets built on it are named as placeholders, and the audio layout comes
        # from the clips that exist (the stub's 0 channels made a mono join stereo)
        (d / "cam_later.mp4").unlink(missing_ok=True)
        proc = script("join.py", d / "cam_later.mp4", self.src, self.src, "--dry-run", "--json", "-o", d / "cams.mp4")
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["mode"]), ("completed", "video"))
        self.assertTrue(any("first input is pending" in n and "placeholders" in n for n in doc["notes"]), doc["notes"])
        self.assertTrue(any("xfade offsets" in n for n in doc["notes"]), doc["notes"])
        self.assertIn("channel_layouts=mono", doc["commands"][0])
        self.assertNotIn("channel counts differ", proc.stderr)
        doc = json.loads(script("join.py", self.src, self.src, d / "cam_later.mp4", "--dry-run", "--json", "-o", d / "cams.mp4").stdout)
        self.assertFalse(any("placeholders" in n or "xfade offsets" in n for n in doc["notes"]),
                         "a pending LAST clip changes neither the frame nor an offset")
        # the real run is unchanged: the missing line is skipped (or refused), never pending
        doc = json.loads(script("join.py", "--list", d / "parts.txt", "--transition", "none", "--on-missing", "skip",
                                "--json", "-o", d / "voice.wav").stdout)
        self.assertEqual((doc["clips"], doc["pending"], doc["expected_duration"]), (2, [], 3.0))
        self.assertEqual([Path(p["path"]).name for p in doc["skipped"]], ["tts_03.wav"])

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
        # --margin 0 is no longer needed (#414: the margin is kept around silences only, not
        # around filler spans), but kept so this test's numbers stay those it was written with.
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

    def test_filler_margin_does_not_swallow_a_short_filler(self):
        """#414: --margin is silence's, not a filler span's. An "um" 0.34 s wide (0.38 s with the
        pad) under the default 0.2 s margin was turned inside out: keep [[0,0.88],[0.82,...]],
        kept longer than the input, nothing removed, yet reported as removed."""
        words = self._words_json("short_um.json", words=[
            ("So", 0.2, 0.5), ("um", 0.68, 1.02), ("this", 1.1, 1.5)])
        data = json.loads(script("silence.py", self._gappy(), "--filler", "--filler-list",
                                 "--words", words, "--json").stdout)
        self.assertEqual(data["filler"]["removed_count"], 1)
        keep = data["keep"]
        for (_a, b), (c, _d) in zip(keep, keep[1:]):
            self.assertLessEqual(b, c, keep)
        self.assertLess(data["kept_duration"], data["input_duration"] - 0.3)
        self.assertGreater(data["removed_seconds_total"], 0.3)
        # the "um" starts at 0.68, less the 0.02 s pad: 0.66, which the render holds on its nearest
        # frame (30 fps: 0.6667), and `keep` describes the rendered range since #416
        self.assertEqual(keep[0], [0.0, 0.667])

    def test_a_silence_narrower_than_two_margins_removes_nothing(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        silence = importlib.import_module("silence")
        self.assertEqual(silence.keep_ranges([(1.0, 1.3)], 10, 0.2, 0.2), [(0.0, 10)])
        self.assertEqual(silence.inside_margin([(1.0, 1.3), (2.0, 3.0)], 10, 0.2), [(2.2, 2.8)])

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
            "import _common.asr as asr\n"
            "def fake(video, language=None, model='base', audio_stream=0, engine=None, **kw):\n"
            "    return asr.Transcription(words=[{'word': 'So', 'start': 0.2, 'end': 0.5},\n"
            "             {'word': 'um', 'start': 0.6, 'end': 0.8},\n"
            "             {'word': 'this', 'start': 1.0, 'end': 1.3},\n"
            "             {'word': 'uh', 'start': 2.2, 'end': 2.45}], engine='faster-whisper')\n"
            "asr.transcribe_words_result = fake\n",
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

    def test_filler_lang_auto_follows_the_language_the_engine_transcribed(self):
        """--transcribe with the default --filler-lang auto took the English list whatever the
        engine heard: French speech was transcribed right and its "euh" stayed in the cut. The
        language the engine reports picks the list; one with no built-in list says so."""
        words = ("[{'word': 'Bonjour', 'start': 0.2, 'end': 0.5}, {'word': 'euh', 'start': 0.6, 'end': 0.8},"
                 " {'word': 'tout', 'start': 1.0, 'end': 1.3}]")

        def run(spoken, expect_fail=False):
            shim = OUT / f"asr_shim_{spoken}"
            shim.mkdir(exist_ok=True)
            (shim / "sitecustomize.py").write_text(
                "import sys, os\n"
                "sys.path.insert(0, os.environ['FFSKILL_SCRIPTS'])\n"
                "import _common.asr as asr\n"
                "def fake(video, language=None, model='base', audio_stream=0, engine=None, **kw):\n"
                f"    return asr.Transcription(words={words}, engine='whisper.cpp', facts={{'language': {spoken!r}}})\n"
                "asr.transcribe_words_result = fake\n", encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(shim), FFSKILL_SCRIPTS=str(SCRIPTS))
            r = sh(sys.executable, SCRIPTS / "silence.py", self._gappy(), "--filler",
                   "--transcribe", "--filler-list", "--json", env=env, expect_fail=expect_fail)
            return json.loads(r.stdout)
        fr = run("fr")["filler"]
        self.assertEqual((fr["lang"], fr["removed_words"], fr["warnings"]), ("fr", ["euh"], []))
        en = run("en")["filler"]
        self.assertEqual((en["lang"], en["removed_words"]), ("en", []))
        # a language with no built-in list is refused, not cut with the English list ("er" is "is" in Norwegian)
        no = run("no", expect_fail=True)
        self.assertEqual(no["error"]["kind"], "input")
        self.assertIn("no built-in filler list", no["error"]["message"])
        self.assertIn("--filler-words", no["error"]["message"])

    def test_filler_transcribe_refuses_when_the_engine_gives_no_word_timings(self):
        """An engine that runs but whose build has no word timestamps must say exactly that and
        name --words -- not report an empty removal as a success."""
        shim = OUT / "asr_shim_empty"
        shim.mkdir(exist_ok=True)
        (shim / "sitecustomize.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.environ['FFSKILL_SCRIPTS'])\n"
            "import _common.asr as asr\n"
            "def fake(video, language=None, model='base', audio_stream=0, engine=None, **kw):\n"
            "    return asr.Transcription(engine='whisper.cpp')\n"
            "asr.transcribe_words_result = fake\n",
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

    def test_margin_must_be_a_finite_non_negative_number(self):
        """#427 review: --margin nan made inside_margin() drop every silence, so the run
        re-encoded the whole file unchanged instead of refusing the value."""
        for bad in ("nan", "inf", "-0.1"):
            with self.subTest(margin=bad):
                r = script("silence.py", self._gappy(), "--margin", bad, "-o", OUT / "margin_bad.mp4",
                           "--dry-run", "--json", expect_fail=True)
                err = json.loads(r.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn("--margin", err["message"])

    def test_margin_lead_and_tail_are_kept_on_their_own_sides(self):
        """#449: --margin kept the same amount on both sides of a silence. --margin-tail is what
        stays after speech ends (the start of the silence), --margin-lead what stays before speech
        starts again (its end); each falls back to --margin."""
        import silence
        self.assertEqual(silence.inside_margin([(2.0, 3.0)], 10, 0.4, 0.1), [(2.4, 2.9)])
        self.assertEqual(silence.inside_margin([(2.0, 3.0)], 10, 0.2), [(2.2, 2.8)])
        # too short to hold both: nothing of it is removed
        self.assertEqual(silence.inside_margin([(2.0, 2.4)], 10, 0.4, 0.1), [])
        # a silence that runs to the end of the file has no speech after it: only the tail is kept
        self.assertEqual(silence.inside_margin([(8.0, float("inf"))], 10, 0.4, 0.1), [(8.4, 10)])
        gappy = self._gappy()
        even = json.loads(script("silence.py", gappy, "--list", "--json", "--margin", "0.25").stdout)
        split = json.loads(script("silence.py", gappy, "--list", "--json", "--margin", "0.25",
                                  "--margin-lead", "0.1", "--margin-tail", "0.4").stdout)
        only_tail = json.loads(script("silence.py", gappy, "--list", "--json", "--margin", "0.25",
                                      "--margin-tail", "0.4").stdout)
        self.assertEqual(even["margins"], {"lead": 0.25, "tail": 0.25})
        self.assertEqual(split["margins"], {"lead": 0.1, "tail": 0.4})
        self.assertEqual(only_tail["margins"], {"lead": 0.25, "tail": 0.4})
        self.assertEqual(even["silences"], split["silences"])
        # --filler alone detects no silences, so it applies no margin and reports none
        filler = json.loads(script("silence.py", gappy, "--filler", "--words", self._words_json(),
                                   "--filler-list", "--margin-tail", "0.4", "--json").stdout)
        self.assertNotIn("margins", filler)
        inner = [(s, e) for s, e in even["silences"] if s > 0.3 and e is not None]
        self.assertTrue(inner, even["silences"])
        s, e = inner[0]
        # the kept range before this silence ends `tail` into it; the one after starts `lead` before its end
        frame = 1 / 30
        ends = [k[1] for k in split["keep"]]
        starts = [k[0] for k in split["keep"]]
        self.assertTrue(any(abs(x - (s + 0.4)) <= frame for x in ends), (s, ends))
        self.assertTrue(any(abs(x - (e - 0.1)) <= frame for x in starts), (e, starts))
        self.assertTrue(any(abs(x - (s + 0.25)) <= frame for x in [k[1] for k in even["keep"]]), (s, even["keep"]))

    def test_a_silence_after_a_sentence_end_has_its_own_floor_and_tail(self):
        """#449: a pause inside a sentence and one after it could not be given different limits.
        The transcript's punctuation on the word before a silence says which it is."""
        import silence
        self.assertTrue(all(silence.ends_sentence(w) for w in ("there.", "ok?", "\u3067\u3059\u3002", 'done."', "\u306d\uff01\u300d")))
        self.assertFalse(any(silence.ends_sentence(w) for w in ("there", "well,", "", "\u3067\u3059\u3001")))
        # the word before a silence is the last one that starts before its midpoint
        self.assertEqual(silence.silence_positions(
            [(2.0, 4.0), (6.0, 8.0), (10.0, float("inf"))],
            [{"word": "one", "start": 0.1, "end": 2.3}, {"word": "two.", "start": 4.1, "end": 6.4},
             {"word": "three!", "start": 8.2, "end": 9.9}], 12.0), ["inside", "sentence_end", "sentence_end"])
        # the last word's timing reaches into the silence that runs to the end of the file
        self.assertEqual(silence.silence_positions(
            [(2.0, float("inf"))], [{"word": "Done.", "start": 1.5, "end": 3.0}], 10.0), ["sentence_end"])
        self.assertEqual(silence.silence_positions([(0.0, 1.0)], [{"word": "late.", "start": 1.2, "end": 2}]), ["inside"])
        # an engine stretches a word into the pause beside it: the next word's start (2.6, before
        # the pause's midpoint) must not make it the word before the pause, nor the previous
        # word's late end (3.6) stop it being that word
        self.assertEqual(silence.silence_positions(
            [(2.0, 4.0)], [{"word": "one.", "start": 0.1, "end": 1.9}, {"word": "two", "start": 2.6, "end": 5.0}]), ["sentence_end"])
        self.assertEqual(silence.silence_positions(
            [(2.0, 4.0)], [{"word": "one.", "start": 0.1, "end": 3.6}, {"word": "two", "start": 4.1, "end": 5.0}]), ["sentence_end"])
        # its own clip, so the layout does not depend on which test made OUT/gappy.mp4 first:
        # sound 0-2, 4-6, 8-10; silent 2-4, 6-8, 10-12
        gappy = OUT / "sentence_gappy.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "aevalsrc='0.5*sin(2*PI*440*t)*lt(mod(t\\,4)\\,2)':s=48000", "-t", "12", gappy)
        words = self._words_json("sentence_words.json", words=[("Hello", 0.1, 1.9), ("there.", 4.1, 5.9), ("end", 8.1, 9.9)])
        common = ("silence.py", gappy, "--list", "--json", "--words", words, "--margin", "0.1")
        data = json.loads(script(*common, "--sentence-margin-tail", "0.5").stdout)
        self.assertEqual(data["silence_positions"], ["inside", "sentence_end", "inside"])
        self.assertEqual(data["sentence"]["silences"], 1)
        self.assertEqual(data["sentence"]["sentence_end_words"], 1)
        self.assertEqual(data["sentence"]["margin_tail"], 0.5)
        frame = 1 / 30
        ends = [k[1] for k in data["keep"]]
        s_inside, s_sentence = data["silences"][0][0], data["silences"][1][0]
        self.assertTrue(any(abs(x - (s_inside + 0.1)) <= frame for x in ends), (s_inside, ends))
        self.assertTrue(any(abs(x - (s_sentence + 0.5)) <= frame for x in ends), (s_sentence, ends))
        # its own floor: a 2 s pause after a sentence end stays when the floor for those is 3 s
        floor = json.loads(script(*common, "--sentence-min-silence", "3").stdout)
        self.assertEqual(floor["silence_positions"], ["inside", "inside"])
        self.assertEqual(len(floor["silences"]), 2)
        self.assertEqual(floor["sentence"]["silences"], 0)
        self.assertEqual(floor["sentence"]["sentence_end_words"], 1)
        # and the other way: only the sentence-end pause is short enough to cut
        only = json.loads(script(*common, "--min-silence", "3", "--sentence-min-silence", "1").stdout)
        self.assertEqual(only["silence_positions"][0], "sentence_end")
        # a transcript without punctuation: nothing is told apart, and the run says so
        bare = self._words_json("sentence_bare.json", words=[("Hello", 0.1, 1.9), ("there", 4.1, 5.9)])
        proc = script("silence.py", gappy, "--list", "--json", "--words", bare, "--sentence-margin-tail", "0.5")
        none = json.loads(proc.stdout)
        self.assertEqual(none["sentence"]["sentence_end_words"], 0)
        self.assertNotIn("sentence_end", none["silence_positions"])
        self.assertIn("sentence_ends_not_found", [w["code"] for w in none["diagnostics"]["warnings"]])
        # a silence that runs to the end of the file is measured to the end of the file: the 2 s
        # after "end." is below a 3 s floor for sentence ends and stays
        tail_words = self._words_json("sentence_tail.json", words=[("Hello", 0.1, 1.9), ("there", 4.1, 5.9), ("end.", 8.1, 9.9)])
        open_end = json.loads(script("silence.py", gappy, "--list", "--json", "--words", tail_words,
                                     "--sentence-min-silence", "3").stdout)
        self.assertEqual(open_end["silence_positions"], ["inside", "inside"])
        self.assertTrue(all(e is not None and e < 9 for _s, e in open_end["silences"]), open_end["silences"])
        shorter = json.loads(script("silence.py", gappy, "--list", "--json", "--words", tail_words,
                                    "--sentence-min-silence", "1").stdout)
        self.assertEqual(shorter["silence_positions"], ["inside", "inside", "sentence_end"])
        # without the flags the result carries neither key
        plain = json.loads(script("silence.py", gappy, "--list", "--json").stdout)
        self.assertNotIn("sentence", plain)
        self.assertNotIn("silence_positions", plain)

    def test_sentence_flags_on_recorded_speech(self):
        """The one speech clip in the repository, with the word timings a speech engine wrote for
        it: three sentences, two hesitations, and word starts that sit up to 0.5 s before the
        sound ("Well," is timed at 3.54 s; the pause before it ends at 3.99 s). Each pause after
        a sentence is told from the one inside "hello" and the silence before the first word, and
        no cut lands near sound."""
        clip = SCRIPTS.parent / "demos" / "footage" / "ai_talk_en.mp4"
        words = SCRIPTS.parent / "demos" / "footage" / "ai_talk_en.words.json"
        data = json.loads(script("silence.py", clip, "--list", "--json", "--words", words, "--threshold", "-30",
                                 "--min-silence", "0.2", "--sentence-min-silence", "0.3",
                                 "--margin", "0.1", "--sentence-margin-tail", "0.3").stdout)
        self.assertEqual(data["sentence"]["sentence_end_words"], 3)  # there. morning. day.
        self.assertEqual(data["silence_positions"].count("sentence_end"), 3)
        for (s, e), pos in zip(data["silences"], data["silence_positions"]):
            with self.subTest(silence=(s, e)):
                # the three long pauses follow the three sentences; anything earlier or shorter is inside one
                self.assertEqual(pos, "sentence_end" if (e is None or e - s > 1.0) else "inside")
        self.assertEqual(data["cut_warnings"], [])
        self.assertTrue(data["cut_points"])
        # each sentence end keeps its 0.3 s tail: the range before a sentence-end pause ends 0.3 s into it
        ends = [k[1] for k in data["keep"]]
        for (s, e), pos in zip(data["silences"], data["silence_positions"]):
            if pos == "sentence_end":
                self.assertTrue(any(abs(x - (s + 0.3)) <= 1 / 24 + 0.01 for x in ends), (s, ends))

    def test_the_sentence_flags_refuse_what_they_cannot_answer(self):
        gappy = self._gappy()
        for argv, needle in ((("--sentence-margin-tail", "0.4"), "word timings"),
                             (("--sentence-min-silence", "0.3", "--speech-aware", "--words", self._words_json()), "--speech-aware"),
                             (("--sentence-min-silence", "nan", "--words", self._words_json()), "--sentence-min-silence"),
                             (("--sentence-margin-tail", "-1", "--words", self._words_json()), "--sentence-margin-tail"),
                             # every word without a length: nothing to place against a pause
                             (("--sentence-margin-tail", "0.4", "--words",
                               self._words_json("sentence_zero.json", words=[("Done.", 0, 0), ("Next.", 3.0, 3.0)])), "usable")):
            with self.subTest(argv=argv):
                r = script("silence.py", gappy, *argv, "--list", "--json", expect_fail=True)
                err = json.loads(r.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn(needle, err["message"])

    def test_margin_lead_and_tail_must_be_finite_and_non_negative(self):
        for flag in ("--margin-lead", "--margin-tail"):
            for bad in ("nan", "inf", "-0.1"):
                with self.subTest(flag=flag, value=bad):
                    r = script("silence.py", self._gappy(), flag, bad, "-o", OUT / "margin_side_bad.mp4",
                               "--dry-run", "--json", expect_fail=True)
                    err = json.loads(r.stdout)["error"]
                    self.assertEqual(err["kind"], "input")
                    self.assertIn(flag, err["message"])

    def test_filler_alone_does_not_say_the_output_equals_the_input(self):
        """#427 review: --filler without --speech-aware has no silences, and the run said "no
        removable silence found; output would equal the input" before rendering a shorter file."""
        proc = script("silence.py", self._gappy(), "--filler", "--words", self._words_json(),
                      "-o", OUT / "filler_equal_msg.mp4", "--dry-run", "--json")
        self.assertGreater(json.loads(proc.stdout)["removed_seconds_total"], 0.1)
        self.assertNotIn("output would equal the input", proc.stderr)

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

    def test_filler_auto_language_in_a_words_file_is_no_language(self):
        """A --words document that says "auto" names no language: it keeps the English list, as a
        document with no language field does, rather than being refused as the language "au"."""
        doc = OUT / "words_lang_auto.json"
        doc.write_text(json.dumps({"language": "auto", "words": [
            {"word": "So", "start": 0.2, "end": 0.5}, {"word": "um", "start": 0.6, "end": 0.8}]}), encoding="utf-8")
        fil = json.loads(script("silence.py", self._gappy(), "--filler", "--words", doc, "--filler-list",
                                "--json").stdout)["filler"]
        self.assertEqual((fil["lang"], fil["removed_words"]), ("en", ["um"]))

    def test_filler_iso_639_2_codes_name_the_language_with_a_built_in_list(self):
        """A --words document may say "jpn" (ISO 639-2): that is Japanese, which has a built-in list,
        not the two letters "jp" that have none."""
        doc = OUT / "words_lang_jpn.json"
        doc.write_text(json.dumps({"language": "jpn", "words": [
            {"word": "えー", "start": 0.2, "end": 0.5}, {"word": "今日", "start": 0.6, "end": 0.8}]}), encoding="utf-8")
        fil = json.loads(script("silence.py", self._gappy(), "--filler", "--words", doc, "--filler-list",
                                "--json").stdout)["filler"]
        self.assertEqual((fil["lang"], fil["removed_words"]), ("ja", ["えー"]))

    def test_filler_takes_a_korean_or_chinese_transcript_by_code_or_name(self):
        """2.19: ko and zh have built-in lists, so "kor", "zh-CN" and "chinese" are no longer
        refused; "chinese" used to be cut to the two letters "ch"."""
        for lang, word, expected in (("kor", "음", "ko"), ("ko-KR", "어", "ko"), ("zh-CN", "嗯，", "zh"),
                                     ("chinese", "呃", "zh"), ("spanish", "eh", "es")):
            with self.subTest(lang=lang):
                doc = OUT / "words_lang_more.json"
                doc.write_text(json.dumps({"language": lang, "words": [
                    {"word": word, "start": 0.2, "end": 0.5}, {"word": "x", "start": 0.7, "end": 0.9}]}),
                    encoding="utf-8")
                fil = json.loads(script("silence.py", self._gappy(), "--filler", "--words", doc, "--filler-list",
                                        "--json").stdout)["filler"]
                self.assertEqual(fil["lang"], expected)
                self.assertEqual(fil["removed_count"], 1)

    def test_an_unlisted_three_letter_code_is_refused_not_read_as_its_two_letter_prefix(self):
        """est is Estonian: it has no built-in list, so it is refused. Cutting it to "es" would run the
        Spanish list on Estonian speech."""
        doc = OUT / "words_lang_est.json"
        doc.write_text(json.dumps({"language": "est", "words": [
            {"word": "tere", "start": 0.2, "end": 0.5}]}), encoding="utf-8")
        r = script("silence.py", self._gappy(), "--filler", "--words", doc, "--filler-list", "--json",
                   expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("est", err["message"])

    def test_filler_custom_list_reports_the_language_it_heard(self):
        """With --filler-words the run goes ahead on a language with no built-in list, and says which
        language the transcript is in rather than the English default it did not use."""
        doc = OUT / "words_lang_no.json"
        doc.write_text(json.dumps({"language": "no", "words": [
            {"word": "er", "start": 0.2, "end": 0.5}, {"word": "sant", "start": 0.6, "end": 0.8}]}), encoding="utf-8")
        custom = OUT / "filler_words_no.txt"
        custom.write_text("er\n", encoding="utf-8")
        fil = json.loads(script("silence.py", self._gappy(), "--filler", "--words", doc, "--filler-words", custom,
                                "--filler-list", "--json").stdout)["filler"]
        self.assertEqual((fil["lang"], fil["removed_words"]), ("no", ["er"]))

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


class OneClockTests(MediaFixtures):
    """#409: a tool that cuts, repeats, reverses or re-times both streams keeps them on one clock.
    Each fixture has a one-frame flash and a 40 ms beep at the same instant, so flash minus beep is
    the A/V offset; the late-sound, late-picture and long-sound variants are the shapes a stream
    copy or a camera leaves. Every case below came out 100-570 ms off with `verified: true`."""

    def _fx(self, name, **kw):
        return make_flash_beep(OUT / f"clock_{name}.mp4", **kw)

    def assertInSync(self, offsets, expected=0, tol=5, msg=""):
        self.assertTrue(offsets, msg)
        for o in offsets:
            self.assertLessEqual(abs(o - expected), tol, f"{msg}: flash-beep {offsets} ms")

    def test_silence_keeps_sync_and_its_time_map_over_many_ranges(self):
        """The one-pass select/ametadata render rounded every kept range twice (the picture to
        frames, the sound to AAC frames), so the sound drifted 5, 40, 75 ms over three ranges and
        the picture ran 0.1 s past it; the time map, built from millisecond bounds, missed the
        picture's length too. The ranges are now re-cut as cut.py --segments --accurate cuts them."""
        src = self._fx("talk", talk=True)
        out, tm = OUT / "clock_talk_tight.mp4", OUT / "clock_talk_tight.json"
        for p in (out, tm):
            if p.exists():
                p.unlink()
        script("silence.py", src, "--min-silence", "0.5", "--margin", "0.1", "--preset", "veryfast",
               "--timemap", tm, "-o", out)
        self.assertInSync(av_offsets_ms(out, beep_db=-12), msg="silence")
        spans = stream_spans(out)
        self.assertAlmostEqual(spans["video"][1], spans["audio"][1], delta=0.025)
        kept = json.loads(tm.read_text())["kept"]
        self.assertAlmostEqual(kept[-1]["output_end"], spans["video"][1], delta=0.002)
        # each source flash, carried through the map, is where the output shows it
        for src_t, out_t in zip((1.2, 4.2, 7.2), flash_times(out)):
            k = next(k for k in kept if k["source_start"] <= src_t < k["source_end"])
            self.assertAlmostEqual(k["output_start"] + src_t - k["source_start"], out_t, delta=0.002)

    def test_silence_keeps_a_late_sound_where_it_was(self):
        """asetpts=N/SR started a sound that begins 0.3 s after its picture at 0: +280 ms."""
        out = OUT / "clock_talk_late_tight.mp4"
        script("silence.py", self._fx("talk_late", talk=True, audio_late=0.3), "--min-silence", "0.5",
               "--margin", "0.1", "--preset", "veryfast", "-o", out, "--overwrite")
        self.assertInSync(av_offsets_ms(out, beep_db=-12), msg="silence, late sound")

    def test_silence_refuses_an_output_that_is_its_input_when_the_join_is_chunked(self):
        """#416 review: above 32 kept ranges the join's last command concats a chunk list, never
        naming the source, so `-o <input> --overwrite` replaced the source with the cut."""
        src = OUT / "silence_alias.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "aevalsrc='if(lt(mod(t,1),0.5),0.5*sin(440*2*PI*t),0)':d=40:s=48000", "-c:a", "pcm_s16le", src)
        before = src.read_bytes()
        proc = script("silence.py", src, "--min-silence", "0.3", "-o", src, "--overwrite", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "output_is_input")
        self.assertEqual(src.read_bytes(), before)

    def test_silence_reports_and_exports_the_ranges_it_renders(self):
        """#416 review: `keep`, `kept_duration` and `--edl` carried the unsnapped bounds (0.385-2.115)
        while the render and --timemap held frame times (0.4-2.1); an EDL bound rounded up past its
        frame (0.3667 written 0.367) re-cut one frame later in cut.py --segments."""
        src = self._fx("talk", talk=True)
        edl, tm = OUT / "clock_talk_snap.txt", OUT / "clock_talk_snap.json"
        for margin, first in (("0.115", "0.400"), ("0.13", "0.366")):
            doc = json.loads(script("silence.py", src, "--min-silence", "0.5", "--margin", margin, "--list",
                                    "--edl", edl, "--timemap", tm, "--json", "--overwrite").stdout)
            kept = json.loads(tm.read_text())["kept"]
            self.assertEqual(doc["keep"], [[k["source_start"], k["source_end"]] for k in kept])
            self.assertAlmostEqual(doc["kept_duration"], kept[-1]["output_end"], delta=0.0015)
            self.assertTrue(edl.read_text().startswith(first + "-"), edl.read_text())

    def test_freeze_keeps_a_late_sound_and_a_late_picture_in_sync(self):
        """Each stream was rebased to its own start: +279 ms for a sound 0.3 s late, -100 ms for a
        picture 0.1 s late, both at --at and at the end."""
        for name, kw in (("alate", {"audio_late": 0.3}), ("vlate", {"video_late": 0.1})):
            src = self._fx(name, **kw)
            for extra in (["--at", "1.2"], []):
                out = OUT / f"clock_freeze_{name}{len(extra)}.mp4"
                script("freeze.py", src, "--hold", "1", *extra, "--preset", "veryfast", "-o", out, "--overwrite")
                self.assertInSync(av_offsets_ms(out), msg=f"freeze {name} {extra}")
        self.assertEqual(stream_spans(OUT / "clock_freeze_alate2.mp4")["video"][2], 150)

    def test_speedramp_keeps_a_late_sound_in_sync(self):
        """Each segment's streams were rebased on their own, then sped up: a sound 0.3 s late came
        out +300 ms in a 1x segment (+570 ms at 0.5x), a picture 0.1 s late -79 ms. The flash in the
        1x segment is compared with the same ramp of an in-sync source (atempo's own offset is
        outside this fix)."""
        segs = ["--segment", "0-1:1", "--segment", "1-4:0.5"]
        firsts = {}
        for name, kw in (("sync", {}), ("alate", {"audio_late": 0.3}), ("vlate", {"video_late": 0.1})):
            out = OUT / f"clock_ramp_{name}.mp4"
            script("speedramp.py", self._fx(name, **kw), *segs, "--preset", "veryfast", "-o", out, "--overwrite")
            firsts[name] = av_offsets_ms(out)[0]
        self.assertLessEqual(abs(firsts["alate"] - firsts["sync"]), 5, firsts)
        self.assertLessEqual(abs(firsts["vlate"] - firsts["sync"]), 5, firsts)

    def test_speedramp_a_sped_up_segment_leaves_the_rest_of_the_picture_on_time(self):
        """setpts left each sped-up frame its unscaled duration, and concat starts the next segment
        after the last frame's duration: a 2x segment put the 1x rest of the clip two frames late
        (flashes at 1.567/2.567 s for 1.5/2.5) and the video at 92 frames for 90. The comparison
        above cannot see it (the in-sync source shifts by as much). Absolute times here."""
        out = OUT / "clock_ramp_fast_then_normal.mp4"
        script("speedramp.py", self._fx("sync"), "--segment", "0-2:2", "--segment", "2-4:1",
               "--preset", "veryfast", "-o", out, "--overwrite")
        self.assertEqual([round(t, 3) for t in flash_times(out)], [1.5, 2.5])
        self.assertEqual(stream_spans(out)["video"][2], 90)

    def test_join_keeps_a_late_sound_where_it_was(self):
        """#338 started each clip's picture at 0 and rebased its sound on its own: a clip whose
        sound starts 0.3 s late joined 279 ms early."""
        for name, kw in (("alate", {"audio_late": 0.3}), ("vlate", {"video_late": 0.1}), ("long", {"video_short": 0.6})):
            out = OUT / f"clock_join_{name}.mp4"
            script("join.py", self._fx(name, **kw), self._fx("sync"), "--transition", "none",
                   "--preset", "veryfast", "-o", out, "--overwrite")
            self.assertInSync(av_offsets_ms(out), msg=f"join {name}")

    def test_broll_b_audio_keeps_a_late_sound_in_sync(self):
        """B's sound was rebased to its own first sample while its picture landed on --at: +279 ms."""
        for audio in ("b", "mix"):
            out = OUT / f"clock_broll_{audio}.mp4"
            script("broll.py", self._fx("sync"), "--insert", self._fx("alate", audio_late=0.3), "--at", "1",
                   "--duration", "2", "--audio", audio, "--preset", "veryfast", "-o", out, "--overwrite")
            self.assertInSync(av_offsets_ms(out), msg=f"broll --audio {audio}")

    def test_broll_b_audio_lasts_the_whole_cutaway_when_from_is_between_frames(self):
        """The sound started at B's first frame at or after --from but ended at --from + length,
        so --from 1.01 at 30 fps left the last 23 ms of the cutaway without B's sound (#416 review)."""
        src = self._fx("sync")
        doc = json.loads(script("broll.py", src, "--insert", src, "--at", "1", "--from", "1.01", "--duration", "1",
                                "--audio", "b", "-o", OUT / "clock_broll_from.mp4", "--dry-run", "--json").stdout)
        m = re.search(r"\[1:a:0\]atrim=start=([0-9.]+):end=([0-9.]+)", json.dumps(doc))
        self.assertIsNotNone(m, doc)
        self.assertAlmostEqual(float(m.group(2)) - float(m.group(1)), 1.0, delta=0.001)

    def test_reverse_turns_both_streams_about_one_end(self):
        """Each stream was reversed about its own end: a sound 0.6 s past its picture came out
        +396 ms. Reversed, a flash frame [t, t+1/30) and a beep [t, t+0.04) start 6.7 ms apart."""
        for name, kw in (("long", {"video_short": 0.6}), ("alate", {"audio_late": 0.3}), ("vlate", {"video_late": 0.1})):
            out = OUT / f"clock_reverse_{name}.mp4"
            script("reverse.py", self._fx(name, **kw), "--preset", "veryfast", "-o", out, "--overwrite")
            self.assertInSync(av_offsets_ms(out), expected=7, msg=f"reverse {name}")
            spans = stream_spans(out)
            self.assertAlmostEqual(spans["video"][1], spans["audio"][1], delta=0.025)

    def test_loop_keeps_a_late_sound_in_sync_on_every_repeat(self):
        """-stream_loop shortened every repeat of a clip whose sound starts late by a frame and slid
        the sound (346 of 360 frames, 1 then 68 ms); the concat list repeats the file's whole length,
        and an in-sync AAC source is not moved by the list's priming either."""
        for name, kw in (("alate", {"audio_late": 0.3}), ("sync", {})):
            out = OUT / f"clock_loop_{name}.mp4"
            script("loop.py", self._fx(name, **kw), "--times", "3", "--preset", "veryfast", "-o", out, "--overwrite")
            offsets = av_offsets_ms(out)
            self.assertEqual(len(offsets), 12, offsets)
            self.assertInSync(offsets, msg=f"loop {name}")
            self.assertEqual(stream_spans(out)["video"][2], 360)

    def test_multicam_audio_from_a_camera_whose_sound_starts_late(self):
        """The camera's sound was measured from its first sample, not its file's start (+1.274 s for
        a camera 1.0 s in whose sound starts 0.3 s late, so its picture was cut 274 ms late), and
        its sound was then rebased to that first sample before the delay."""
        ref = make_tones_take(OUT / "clock_cam0.mp4", dur=8)
        cam = make_tones_take(OUT / "clock_cam1.mp4", start=1.0, audio_late=0.3, dur=7)
        out = OUT / "clock_multicam.mp4"
        doc = json.loads(script("multicam.py", ref, cam, "--switch", "0-8:0", "--audio", "1", "--preset", "veryfast",
                                "-o", out, "--overwrite", "--json").stdout)
        self.assertAlmostEqual(doc["offsets_seconds"][1], 1.0, delta=0.01, msg=doc["offsets_seconds"])
        again = json.loads(script("sync.py", ref, out, "--json").stdout)
        self.assertAlmostEqual(again["offset_seconds"], 0.0, delta=0.01, msg=again)


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

    def test_a_filler_split_across_whisper_tokens_is_one_word(self):
        """2.19: whisper splits Japanese and Chinese into tokens, not words -- its own vocabulary
        turns えーと into えー + と and えっと into え + っと, so the list's えーと/えっと never
        matched one token. A run of tokens that joins to a listed word is that word; the longest
        run wins, so えーと is cut whole rather than えー with と left behind."""
        ja = self.D.FILLER_WORDS["ja"]
        spans = self.D.filler_spans(self._w(("えー", 1.0, 1.2), ("と", 1.2, 1.3), ("、", 1.3, 1.3),
                                            ("今日", 1.6, 1.8), ("え", 2.5, 2.6), ("っと", 2.6, 2.8)), ja, pad=0.0)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans],
                         [("えーと", 1.0, 1.3), ("えっと", 2.5, 2.8)])

    def test_an_unspaced_filler_needs_a_word_boundary_on_each_side(self):
        """The same token split means a listed character can be part of a longer word: あの + 人
        is "that person", 我 + 嗯 + 是 runs straight through. A run in an unspaced script is cut
        only with a boundary on both sides: punctuation, a pause of FILLER_BOUNDARY_GAP, the
        transcript's edge or a spaced-script neighbour."""
        ja, zh = self.D.FILLER_WORDS["ja"], self.D.FILLER_WORDS["zh"]
        self.assertEqual(self.D.filler_spans(self._w(("あの", 1.0, 1.2), ("人", 1.2, 1.4)), ja), [])
        self.assertEqual(self.D.filler_spans(self._w(("我", 1.0, 1.1), ("嗯", 1.1, 1.2), ("是", 1.2, 1.3)), zh), [])
        cut = self.D.filler_spans(self._w(("我", 1.0, 1.1), ("嗯，", 1.3, 1.5), ("是", 1.5, 1.6)), zh, pad=0.0)
        self.assertEqual([s["word"] for s in cut], ["嗯"])
        # faster-whisper attaches the comma to the word before it; that is a boundary too
        cut = self.D.filler_spans(self._w(("呃", 0.0, 0.2), ("那个", 0.2, 0.5)), zh | {"那个"}, pad=0.0)
        self.assertEqual([s["word"] for s in cut], [], "two listed words with no boundary between them stay")

    def test_korean_is_spaced_and_matches_whole_words(self):
        ko = self.D.FILLER_WORDS["ko"]
        spans = self.D.filler_spans(self._w(("음,", 0.5, 0.8), ("음악은", 1.0, 1.5), ("어", 2.0, 2.2), ("좋아요", 2.2, 2.6)), ko)
        self.assertEqual([s["word"] for s in spans], ["음", "어"])
        self.assertNotIn("저", ko, "저 is also 'I': a discourse marker, not a default")
        self.assertIn("저", self.D.FILLER_DISCOURSE_MARKERS["ko"])

    def test_a_two_word_discourse_marker_added_with_filler_extra_matches(self):
        """--help offers 'you know' for --filler-extra, but one engine word is one word, so the
        two-word phrase could never match before 2.19."""
        spans = self.D.filler_spans(self._w(("So", 0.0, 0.3), ("you", 0.5, 0.7), ("know", 0.7, 0.9), ("it", 1.0, 1.2)),
                                    {"you know"}, pad=0.0)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans], [("you know", 0.5, 0.9)])

    def test_punctuation_inside_a_run_ends_the_word(self):
        """えー、と is a filler and then a particle, not えーと: the comma is a word boundary, so
        only えー goes and と is kept. The same holds for "you, know"."""
        ja = self.D.FILLER_WORDS["ja"]
        spans = self.D.filler_spans(self._w(("えー、", 1.0, 1.2), ("と", 1.2, 1.3)), ja, pad=0.0)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans], [("えー", 1.0, 1.2)])
        self.assertEqual(self.D.filler_spans(self._w(("you,", 0.5, 0.7), ("know", 0.7, 0.9)), {"you know"}), [])

    def test_a_pause_inside_an_unspaced_run_ends_the_word(self):
        """えー, a 0.2 s pause, then と is a filler and then a particle: the pause is a word
        boundary, so only えー goes and the pause and と stay."""
        ja = self.D.FILLER_WORDS["ja"]
        spans = self.D.filler_spans(self._w(("えー", 1.0, 1.2), ("と", 1.4, 1.5)), ja, pad=0.0)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans], [("えー", 1.0, 1.2)])

    def test_han_extension_characters_are_unspaced(self):
        """U+20000 and up (Extensions B-H) are Han too: 嗯 glued to one is part of a word."""
        zh = self.D.FILLER_WORDS["zh"]
        self.assertTrue(self.D._unspaced_script("\U00020000"))
        self.assertEqual(self.D.filler_spans(self._w(("我", 0.0, 0.1), ("嗯", 0.1, 0.2), ("\U00020000", 0.2, 0.3)), zh), [])

    def test_a_rejected_longer_phrase_does_not_hide_a_listed_word(self):
        """--filler-extra "um huh" held for 3 s is too long to be a filler, but the "um" at its
        start is a filler of its own: it is still cut, and nothing is counted as too long."""
        stats = {}
        spans = self.D.filler_spans(self._w(("um", 1.0, 1.2), ("huh", 1.2, 4.0)), {"um", "um huh"},
                                    pad=0.0, stats=stats)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans], [("um", 1.0, 1.2)])
        self.assertEqual(stats["matched_too_long"], 0)
        # and a listed word at its end: a held "uhhh" then "um" -- the phrase is too long, the um is not
        stats = {}
        spans = self.D.filler_spans(self._w(("uhhh", 1.0, 3.9), ("um", 3.9, 4.1)), {"um", "uhhh um"},
                                    pad=0.0, stats=stats)
        self.assertEqual([(s["word"], s["start"], s["end"]) for s in spans], [("um", 3.9, 4.1)])
        self.assertEqual(stats["matched_too_long"], 1)
        stats = {}
        self.assertEqual(self.D.filler_spans(self._w(("uhhh", 1.0, 3.0)), {"uhhh"}, stats=stats), [])
        self.assertEqual(stats["matched_too_long"], 1)

    def test_a_run_listed_out_of_time_order_is_untimed(self):
        """A run whose last token ends before its first starts has no span to cut; cutting it
        would hand keep_ranges an inverted range."""
        stats = {}
        spans = self.D.filler_spans(self._w(("you", 1.0, 1.2), ("know", 0.5, 0.7)), {"you know"}, stats=stats)
        self.assertEqual(spans, [])
        self.assertEqual(stats["matched_untimed"], 1)

    def test_the_reference_table_lists_every_built_in_list_word_for_word(self):
        """references/scripts.md restates FILLER_WORDS as a table; a language added to one and
        not the other leaves a reader with no row to look up."""
        text = (SCRIPTS.parent / "references" / "scripts.md").read_text(encoding="utf-8")
        table = text.split("Built-in lists, one per language:", 1)[1].split("\n\n", 2)[1]
        rows = {}
        for line in table.splitlines()[2:]:
            lang, words = [c.strip() for c in line.strip("|").split("|")]
            rows[lang] = {w.strip() for w in words.split(",")}
        self.assertEqual(rows, {k: set(v) for k, v in self.D.FILLER_WORDS.items()})

    def test_every_new_language_list_holds_disfluencies_only(self):
        """2.19 adds ko, zh, ru, nl, pl and tr. No list carries a word its own language uses as
        content; those are discourse markers, reachable with --filler-extra."""
        for lang in ("ko", "zh", "ru", "nl", "pl", "tr"):
            self.assertTrue(self.D.FILLER_WORDS[lang], lang)
            self.assertFalse(self.D.FILLER_WORDS[lang] & set(self.D.FILLER_DISCOURSE_MARKERS[lang]), lang)
        self.assertNotIn("额", self.D.FILLER_WORDS["zh"], "额 is a common character in its own right")

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
        # Japanese and Chinese have no spaces, so every token "continues" the one before: between
        # two whole characters the tokens stay apart, a partial character (U+FFFD) is still glued
        doc.write_text(json.dumps({"transcription": [{"tokens": [
            {"text": "えー", "offsets": {"from": 0, "to": 200}},
            {"text": "と", "offsets": {"from": 200, "to": 300}},
            {"text": "\ufffd", "offsets": {"from": 300, "to": 350}},
            {"text": "\ufffd今日", "offsets": {"from": 350, "to": 600}},
        ]}]}), encoding="utf-8")
        self.assertEqual([w["word"] for w in asr._words_from_whisper_cpp_json(str(doc))],
                         ["えー", "と\ufffd\ufffd今日"])
        # a full-width comma token stays with the word before it and ends it: 嗯，+ 呃, not 嗯，呃
        doc.write_text(json.dumps({"transcription": [{"tokens": [
            {"text": "嗯", "offsets": {"from": 0, "to": 200}},
            {"text": "，", "offsets": {"from": 200, "to": 200}},
            {"text": "呃", "offsets": {"from": 400, "to": 600}},
        ]}]}), encoding="utf-8")
        words = asr._words_from_whisper_cpp_json(str(doc))
        self.assertEqual([w["word"] for w in words], ["嗯，", "呃"])
        self.assertEqual([s["word"] for s in self.D.filler_spans(words, self.D.FILLER_WORDS["zh"], pad=0.0)],
                         ["嗯", "呃"])

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


class Hdr10StaticMetadataTests(unittest.TestCase):
    """#401: a PQ source's mastering-display / content-light metadata reaches libx265 and SVT-AV1
    re-encodes (FFmpeg before 7 does not pass it on by itself), and an output that still lacks it
    is reported (hdr10_metadata_dropped), measured on the written file."""
    MD = "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"

    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.src = OUT / "hdr10_md.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=1",
           "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1", "-x265-params",
           f"log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:master-display={cls.MD}:max-cll=1000,400",
           "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", cls.src)

    def side_data(self, path):
        return sh("ffprobe", "-v", "error", "-select_streams", "v", "-read_intervals", "%+#1", "-show_frames",
                  "-show_entries", "frame_side_data=side_data_type", path).stdout

    def test_probe_reads_the_static_metadata(self):
        st = probe(str(self.src))["video"]["hdr10_static"]
        self.assertEqual(st["content_light"], {"max_content": 1000, "max_average": 400})
        self.assertAlmostEqual(st["mastering_display"]["max_luminance"], 1000.0)
        self.assertAlmostEqual(st["mastering_display"]["red_x"], 0.68)

    def test_a_still_is_not_a_second_picture_source(self):
        """#412 review: an overlay's PNG must not switch the HDR10 loss check off."""
        from _common import STATE
        logo = OUT / "hdr10_logo.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=32x32",
           "-frames:v", "1", "-update", "1", logo)
        saved = set(STATE.video_inputs)
        try:
            STATE.video_inputs = set()
            probe(str(self.src)); probe(str(logo))
            self.assertEqual(len(STATE.video_inputs), 1, STATE.video_inputs)
        finally:
            STATE.video_inputs = saved

    def test_a_zero_minimum_luminance_is_a_value(self):
        """CodeRabbit on #412: a 0 cd/m2 minimum is a value, not a missing field."""
        src = OUT / "hdr10_md_zero.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=0.4",
           "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1", "-x265-params",
           "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
           "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,0):max-cll=1000,400",
           "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", src)
        md = probe(str(src))["video"]["hdr10_static"]["mastering_display"]
        self.assertEqual(md["min_luminance"], 0.0)
        from _common import decision
        self.assertIn("L(10000000,0)", decision.hdr10_x265_params(probe(str(src))["video"]))

    def test_x265_params_restate_it(self):
        from _common import decision
        v = probe(str(self.src))["video"]
        self.assertEqual(decision.hdr10_x265_params(v), f":master-display={self.MD}:max-cll=1000,400")
        self.assertIn("content-light=1000,400", decision.hdr10_svtav1_params(v))
        self.assertEqual(decision.hdr10_x265_params(dict(v, color_transfer="arib-std-b67")), "")

    def test_hevc_and_av1_reencodes_keep_it(self):
        codecs = ["hevc"] + (["av1"] if "libsvtav1" in sh("ffmpeg", "-hide_banner", "-encoders").stdout else [])
        for codec in codecs:
            with self.subTest(codec=codec):
                out = OUT / f"hdr10_md_{codec}.mp4"
                doc = json.loads(script("fit.py", self.src, "--width", "320", "--codec", codec, "--fast", "--json",
                                        "--overwrite", "-o", out).stdout)
                side = self.side_data(out)
                self.assertIn("Mastering display metadata", side)
                self.assertIn("Content light level metadata", side)
                # the values, not only the records: CLL exactly, the display within each format's step
                got = probe(str(out))["video"]["hdr10_static"]
                self.assertEqual(got["content_light"], {"max_content": 1000, "max_average": 400})
                md = got["mastering_display"]
                self.assertAlmostEqual(md["max_luminance"], 1000.0, delta=1.0)
                self.assertAlmostEqual(md["red_x"], 0.68, delta=2 ** -15)
                self.assertAlmostEqual(md["white_point_y"], 0.329, delta=2 ** -15)
                codes = [w["code"] for w in (doc.get("diagnostics") or {}).get("warnings", [])]
                self.assertNotIn("hdr10_metadata_dropped", codes)

    def test_an_output_without_it_is_reported(self):
        out = OUT / "hdr10_md_prores.mov"
        doc = json.loads(script("fit.py", self.src, "--width", "320", "--codec", "prores", "--json", "--overwrite", "-o", out).stdout)
        have = probe(str(out))["video"].get("hdr10_static") or {}
        lost = [k for k in ("mastering_display", "content_light") if not have.get(k)]
        if not lost:
            self.skipTest("this FFmpeg carries the side data into ProRes")
        warns = [w for w in (doc.get("diagnostics") or {}).get("warnings", []) if w["code"] == "hdr10_metadata_dropped"]
        self.assertEqual(len(warns), 1, doc)
        self.assertEqual(warns[0]["dropped"], lost)
        self.assertIn(warns[0]["message"], doc["notes"])


class GeometryAuditTests(unittest.TestCase):
    """Issue #411 (audit H): non-square pixels, odd-sized and EXIF-rotated inputs, freeze's frame
    and the SMPTE hint. Every fixture is a one-to-three-second lavfi clip built here."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        # 180x180 stored at SAR 16:9: a 320x180 red picture on screen
        cls.sar = sar_clip(OUT / "g411_sar.mp4", audio=True)
        cls.blue = tiny_clip(OUT / "g411_blue.mp4", "color=c=blue:s=320x180:r=30", audio=True)
        cls.odd = tiny_clip(OUT / "g411_odd.mp4", "color=c=gray:s=321x181:r=30,format=yuv444p", seconds=2, pix_fmt="yuv444p")
        # red for the first second, blue from 1.0 s: a cut at exactly t = 1
        cls.shot = tiny_clip(OUT / "g411_shot.mp4", "color=c=red:s=160x90:r=30,drawbox=c=blue:t=fill:enable='gte(t,1)'",
                             seconds=2)
        cls.tc = tiny_clip(OUT / "g411_tc.mp4", "testsrc2=s=160x90:r=30", "-timecode", "01:00:00:00", seconds=3)
        cls.exif = exif_rotated_jpeg(OUT / "g411_exif6.jpg")

    def _red(self, rgb):
        self.assertGreater(rgb[0], 180, rgb)
        self.assertLess(rgb[2], 80, rgb)

    def test_probe_reports_the_pixel_aspect_and_the_square_display_size(self):
        from _common import display_size, square_pixels
        v = probe(str(self.sar))["video"]
        self.assertEqual(v["sample_aspect_ratio"], "16:9")
        self.assertEqual(display_size(v), (320, 180))
        self.assertEqual(square_pixels(v), "scale=320:180,setsar=1")
        self.assertEqual(probe(str(self.blue))["video"]["sample_aspect_ratio"], "1:1")

    def test_fit_fills_the_frame_with_a_non_square_pixel_source(self):
        """Through 3.1.3 the 180x180 storage was fitted as a square picture: a 16:9 frame got
        pillarbox bars beside a squashed picture."""
        out = OUT / "g411_fit.mp4"
        doc = json.loads(script("fit.py", self.sar, "--width", "320", "--height", "180", "-o", out, "--json").stdout)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (320, 180, "1:1"))
        self._red(frame_rgb(out, 0.5, 6, 90))
        self.assertTrue(any("non-square pixels" in n for n in doc.get("notes") or []), doc.get("notes"))

    def test_crop_takes_its_rectangle_in_the_displayed_frame(self):
        out = OUT / "g411_crop.mp4"
        script("crop.py", self.sar, "--x", "160", "--y", "0", "--width", "160", "--height", "180", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (160, 180, "1:1"))

    def test_join_sizes_to_the_displayed_frame(self):
        out = OUT / "g411_join.mp4"
        script("join.py", self.sar, self.sar, "--transition", "none", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (320, 180, "1:1"))

    def test_broll_squares_a_non_square_pixel_a_roll(self):
        out = OUT / "g411_broll.mp4"
        script("broll.py", self.sar, "--insert", self.blue, "--at", "0", "--duration", "0.4", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (320, 180, "1:1"))
        self._red(frame_rgb(out, 0.7, 6, 90))

    def test_multicam_sizes_to_the_displayed_frame(self):
        out = OUT / "g411_multicam.mp4"
        script("multicam.py", self.sar, self.sar, "--auto", "0.5", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (320, 180, "1:1"))

    def test_broll_scales_an_odd_sized_a_roll_to_even_and_records_it(self):
        """The even-dimension retry only reaches a -vf; broll's filter_complex failed as kind
        "ffmpeg" on a 321x181 A-roll through 3.1.3."""
        out = OUT / "g411_broll_odd.mp4"
        doc = json.loads(script("broll.py", self.odd, "--insert", self.blue, "--at", "0.5", "--duration", "0.5",
                                "-o", out, "--json").stdout)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (320, 180))
        codes = [f["code"] for f in (doc.get("diagnostics") or {}).get("fallbacks") or []]
        self.assertEqual(codes, ["odd_dimensions_scaled_even"])

    def test_broll_scales_a_one_pixel_wide_a_roll_to_two(self):
        """#416 review: 1 - 1 % 2 is 0, which scale reads as "keep the input's size", so a 1x181
        A-roll stayed 1 px wide and the run failed."""
        one = tiny_clip(OUT / "g416_one.mp4", "color=c=gray:s=1x181:r=30,format=yuv444p", pix_fmt="yuv444p")
        out = OUT / "g416_broll_one.mp4"
        script("broll.py", one, "--insert", self.blue, "--at", "0.2", "--duration", "0.3", "-o", out, "--overwrite")
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (2, 180))

    def test_freeze_at_holds_the_frame_shown_at_that_time(self):
        """--at 1 on a cut at 1.0 s holds the first frame of the new shot (blue), not the last
        frame of the previous one (red), which 3.1.3 held."""
        out = OUT / "g411_freeze.mp4"
        script("freeze.py", self.shot, "--at", "1", "--hold", "1", "-o", out)
        rgb = frame_rgb(out, 1.5, 80, 45)
        self.assertGreater(rgb[2], 180, rgb)
        self.assertLess(rgb[0], 80, rgb)
        self.assertAlmostEqual(probe(str(out))["duration"], 3.0, delta=0.1)

    def test_freeze_without_at_holds_the_last_frame(self):
        """#416 review: with no --at (the clip's end) insert mode cut its tail at the first frame
        at or after the end, which does not exist: the picture stayed 1 s and only the sound
        gained the hold. It now holds the last frame, as --mode extend does."""
        out = OUT / "g416_freeze_end.mp4"
        script("freeze.py", self.blue, "--hold", "1", "-o", out, "--overwrite")
        v = probe(str(out))["video"]
        self.assertAlmostEqual(v["duration"], 2.0, delta=0.05)
        self.assertEqual(v["nb_frames"], 60)

    def test_freeze_holds_a_frame_on_a_variable_frame_rate_gap(self):
        """#416 review: frames at 0.033 and 0.100 (one dropped) and --at 0.06: the hold took the
        one-frame window around 0.067, which held no frame, so the picture gained nothing while
        the sound gained the second. The hold is now the first frame at or after the cut."""
        src = OUT / "g416_vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=2",
           "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=2", "-vf", "select='not(eq(n,2))'",
           "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", src)
        out = OUT / "g416_vfr_freeze.mp4"
        script("freeze.py", src, "--at", "0.06", "--hold", "1", "-o", out, "--overwrite")
        self.assertAlmostEqual(probe(str(out))["video"]["duration"], 3.0, delta=0.1)

    def test_a_smpte_time_past_the_end_of_a_timecoded_source_names_its_start_timecode(self):
        """The grammar is unchanged (hh:mm:ss:ff counts from the file's first frame); the refusal
        now says so and names the frame the caller probably meant."""
        proc = script("cut.py", self.tc, "--start", "01:00:01:00", "--end", "01:00:02:00",
                      "-o", OUT / "g411_tc_cut.mp4", "--json", expect_fail=True)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("01:00:00:00", err.get("hint") or "")
        self.assertIn("--start 01:00:01:00 is 00:00:01:00", err.get("hint") or "")
        # a time inside the file is not touched
        script("cut.py", self.tc, "--start", "00:00:01:00", "--end", "00:00:02:00", "-o", OUT / "g411_tc_cut.mp4")

    def test_the_smpte_hint_names_the_timecode_of_the_input_the_time_is_in(self):
        """#416 review: the hint used the first timecoded input's start and length for every flag,
        so a B-roll's --from was explained against the A-roll's timecode."""
        b = tiny_clip(OUT / "g416_tc_b.mp4", "testsrc2=s=160x90:r=30", "-timecode", "02:00:00:00", seconds=3)
        proc = script("broll.py", self.tc, "--insert", b, "--at", "0", "--from", "02:00:01:00", "--duration", "1",
                      "-o", OUT / "g416_tc_broll.mp4", "--json", expect_fail=True)
        hint = json.loads(proc.stdout)["error"].get("hint") or ""
        self.assertIn("02:00:00:00", hint)
        self.assertIn("--from 02:00:01:00 is 00:00:01:00", hint)
        self.assertNotIn("01:00:00:00", hint)

    def test_insert_turns_an_exif_rotated_still_upright(self):
        """ffmpeg turns an Orientation 6 JPEG upright on decode; probe now reads the rotation off
        the decoded frame, so insert sizes the portrait picture instead of cropping a landscape
        window out of it."""
        self.assertIn(probe(str(self.exif))["video"]["rotation"], (90, -90))
        out = OUT / "g411_insert.mp4"
        script("insert.py", self.exif, "--duration", "0.5", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (180, 320))

    def test_an_exif_rotated_still_with_a_percent_in_its_name_is_read_upright(self):
        """#416 review: the rotation probe read `photo%02d.jpg` as an image2 sequence (no
        `-pattern_type none`), found no frame and reported 0."""
        pct = OUT / "g411_exif%02d.jpg"
        shutil.copyfile(self.exif, pct)
        self.assertIn(probe(str(pct))["video"]["rotation"], (90, -90))

    def test_cropdetect_sequence_and_waveform_say_they_squared_the_pixels(self):
        """#416 review: the three measured or drew on the squared frame without the `notes` line
        every other geometry tool writes."""
        def notes(*argv):
            return " ".join(json.loads(script(*argv, "--json").stdout).get("notes") or [])
        self.assertIn("non-square pixels", notes("cropdetect.py", self.sar))
        frames = OUT / "g416_sar_seq"
        frames.mkdir(exist_ok=True)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=180x180:r=5",
           "-vf", "setsar=16/9", "-frames:v", "2", "-start_number", "1", frames / "f%02d.png")
        self.assertIn("non-square pixels", notes("sequence.py", "--dir", frames, "--pattern", "f%02d.png",
                                                 "--start-number", "1", "-o", OUT / "g416_seq.mp4", "--overwrite"))
        self.assertIn("non-square pixels", notes("waveform.py", self.sar, "--image", frames / "f01.png",
                                                 "-o", OUT / "g416_wave.mp4", "--overwrite"))

    def test_insert_squares_a_non_square_pixel_still_before_it_fills_the_frame(self):
        """#416 review: insert noted the square-pixel scale but never ran it, so a 180x180 SAR 16:9
        still was filled into 320x180 as a square picture and lost a band top and bottom."""
        still = OUT / "g416_sar_still.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=180x180",
           "-vf", "drawbox=y=160:h=20:c=blue:t=fill,setsar=16/9", "-frames:v", "1", still)
        out = OUT / "g416_insert_sar.mp4"
        script("insert.py", still, "--duration", "0.5", "-o", out, "--overwrite")
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"]), (320, 180))
        rgb = frame_rgb(out, 0.2, 160, 175)  # the blue band along the bottom is still there
        self.assertGreater(rgb[2], 180, rgb)
        self.assertLess(rgb[0], 80, rgb)


class WordsFileTests(unittest.TestCase):
    """#404: silence.py --words. The whisper.cpp document its own refusals tell a caller to make is
    read, and word timings that lie past the input (milliseconds, another file's transcript) are said."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.dir = OUT / "words_file"
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.src = cls.dir / "talk.mp4"
        if not cls.src.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=4", "-f", "lavfi", "-i", "sine=f=300:d=4",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.src)

    def run_filler(self, name, doc):
        words = self.dir / name
        words.write_text(json.dumps(doc), encoding="utf-8")
        out = self.dir / (name + ".mp4")
        out.unlink(missing_ok=True)
        result = json.loads(script("silence.py", self.src, "--filler", "--filler-lang", "en", "--words", words, "-o", out,
                                   "--dry-run", "--json").stdout)
        self.assertFalse(out.exists())
        return result

    def test_a_whisper_cpp_document_is_read_and_timings_past_the_input_are_said(self):
        tok = lambda text, a, b: {"text": text, "offsets": {"from": a, "to": b}}  # noqa: E731
        cpp = {"result": {"language": "en"},
               "transcription": [{"offsets": {"from": 0, "to": 3000}, "text": " hello um world",
                                  "tokens": [tok("[_BEG_]", 0, 0), tok(" hello", 500, 900), tok(" um", 1500, 1900), tok(" world", 2500, 2900)]}]}
        same = {"words": [{"word": "hello", "start": 0.5, "end": 0.9}, {"word": "um", "start": 1.5, "end": 1.9},
                          {"word": "world", "start": 2.5, "end": 2.9}]}
        got, want = self.run_filler("cpp.json", cpp), self.run_filler("words.json", same)
        self.assertEqual(got["status"], "completed")
        self.assertEqual(got["filler"]["removed"], want["filler"]["removed"])
        self.assertEqual(len(want["filler"]["removed"]), 1, want["filler"])
        self.assertNotIn("words_outside_input", [w["code"] for w in (got.get("diagnostics") or {}).get("warnings", [])])
        # the same words in milliseconds: every one is past the 4 s input, which is said
        ms = {"words": [{"word": w["word"], "start": w["start"] * 1000, "end": w["end"] * 1000} for w in same["words"]]}
        late = self.run_filler("ms.json", ms)
        warn = [w for w in late["diagnostics"]["warnings"] if w["code"] == "words_outside_input"]
        self.assertEqual([(w["count"], w["words"]) for w in warn], [(3, 3)])
        self.assertIn("milliseconds", warn[0]["message"])
        self.assertIn("ms.json", warn[0]["message"])

    def test_a_whisper_cpp_document_s_language_picks_the_filler_list(self):
        """With the default --filler-lang auto, whisper.cpp's `result.language` is the transcript's
        language as openai-whisper's top-level `language` is: Norwegian has no built-in list, and the
        English one would cut "er" ("is"), so the run is refused; an English document is cut as before."""
        tok = lambda text, a, b: {"text": text, "offsets": {"from": a, "to": b}}  # noqa: E731
        for lang, refused in (("no", True), ("en", False)):
            with self.subTest(language=lang):
                doc = {"result": {"language": lang},
                       "transcription": [{"offsets": {"from": 0, "to": 3000}, "text": " det er bra",
                                          "tokens": [tok(" det", 500, 900), tok(" er", 1500, 1700), tok(" bra", 2500, 2900)]}]}
                words = self.dir / f"cpp_{lang}.json"
                words.write_text(json.dumps(doc), encoding="utf-8")
                out = self.dir / f"cpp_{lang}.mp4"
                out.unlink(missing_ok=True)
                proc = script("silence.py", self.src, "--filler", "--words", words, "-o", out, "--dry-run", "--json",
                              expect_fail=refused)
                result = json.loads(proc.stdout)
                if refused:
                    self.assertEqual((proc.returncode, result["error"]["kind"]), (1, "input"), result)
                    self.assertIn("the transcript is in no,", result["error"]["message"])
                else:
                    self.assertEqual((result["status"], result["filler"]["lang"]), ("completed", "en"), result)
                    self.assertEqual([s["word"] for s in result["filler"]["removed"]], ["er"])
                self.assertFalse(out.exists())


class CompositingAndEdgeInputTests(unittest.TestCase):
    """Issues #460 and #461 (audit 2026-11): a cutaway order, a hold that moves nothing, a chapter
    track copied as data, what reverse holds in memory and how it ends on a variable rate, and
    straighten's crop window. Every fixture is a lavfi clip of a few seconds built here."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.clip = tiny_clip(OUT / "a460_clip.mp4", "testsrc2=s=320x180:r=25", seconds=3, audio=True)

    @staticmethod
    def _counts(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                              "stream=codec_type,codec_tag_string,nb_read_frames,duration", "-of", "json", str(path)],
                             stdout=subprocess.PIPE, text=True, check=True).stdout
        return json.loads(out)["streams"]

    def test_broll_judges_overlap_by_time_not_by_the_order_given(self):
        """A179: cutaways that do not overlap, given later one first, were refused as 'overlaps the
        previous one'. Both windows are now written, and an overlap is still refused, naming both."""
        out = OUT / "a460_broll_order.mp4"
        # the cutaway is plain red, which the main clip (testsrc2) never is at the pixel read: one
        # sample of two moving test patterns could not tell them apart on every encoder
        red = tiny_clip(OUT / "a460_broll_red.mp4", "color=c=red:s=320x180:r=25", seconds=1, audio=True)
        doc = json.loads(script("broll.py", self.clip, "--insert", red, "--at", "2", "--duration", "0.5",
                                "--insert", red, "--at", "0.4", "--duration", "0.5", "--fast", "-o", out,
                                "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual([round(c["at"], 3) for c in doc["cutaways"]], [2.0, 0.4])

        def is_red(t):
            r, g, b = frame_rgb(out, t, 160, 90)
            return r > 150 and g < 90 and b < 90

        for at in (0.4, 2.0):
            self.assertTrue(is_red(at + 0.2), f"the cutaway at {at}s must show the inserted clip: {frame_rgb(out, at + 0.2, 160, 90)}")
        for t in (0.1, 1.4, 2.8):
            self.assertFalse(is_red(t), f"the main clip must show at {t}s: {frame_rgb(out, t, 160, 90)}")
        proc = script("broll.py", self.clip, "--insert", self.clip, "--at", "2", "--duration", "0.5",
                      "--insert", self.clip, "--at", "1.8", "--duration", "0.5", "-o", OUT / "a460_broll_bad.mp4",
                      "--json", expect_fail=True)
        self.assertIn("overlaps cutaway 2", json.loads(proc.stdout)["error"]["message"])

    def test_freeze_of_the_last_frame_keeps_the_subtitle_track(self):
        """A180: a hold of the last frame (the default with no --at) moves no cue, but the track was
        dropped as for a hold that pushes the rest of the clip later. It is kept now; a hold inside
        the clip still drops it (decided: its cues would fire early)."""
        srt = OUT / "a460_cue.srt"
        srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nhello\n", encoding="utf-8")
        subs = OUT / "a460_subs.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.clip, "-i", srt, "-map", "0", "-map", "1",
           "-c", "copy", "-c:s", "srt", subs)
        out = OUT / "a460_freeze_end.mkv"
        doc = json.loads(script("freeze.py", subs, "--hold", "0.5", "--fast", "-o", out, "--json").stdout)
        self.assertIn("subtitle", [s["codec_type"] for s in self._counts(out)])
        self.assertFalse(doc.get("dropped_non_av_streams"))
        self.assertEqual(doc["source_carry"]["dropped"], [])
        mid = OUT / "a460_freeze_mid.mkv"
        script("freeze.py", subs, "--at", "1", "--hold", "0.5", "--fast", "-o", mid)
        self.assertNotIn("subtitle", [s["codec_type"] for s in self._counts(mid)])

    def test_a_chapter_track_is_not_copied_as_a_data_stream(self):
        """A173: an MP4's chapter text track (a data stream FFmpeg reads with the tag `text`) was
        copied by `-map 0` / `-map 0:d?` as a stray `gpmd` data track holding the old titles:
        --clear-chapters left them in the file and every pass added a track. The written file holds
        no data track but the chapter track its own chapters make."""
        chapters = OUT / "a460_chapters.txt"
        chapters.write_text("0:00 Intro\n0:01 Middle\n0:02 End\n", encoding="utf-8")
        tagged = OUT / "a460_chapters.mp4"
        script("metadata.py", self.clip, "--chapters", chapters, "-o", tagged)
        self.assertEqual([s["codec_tag_string"] for s in self._counts(tagged) if s["codec_type"] == "data"], ["text"])
        cleared = OUT / "a460_cleared.mp4"
        script("metadata.py", tagged, "--clear-chapters", "-o", cleared)
        self.assertEqual([s for s in self._counts(cleared) if s["codec_type"] == "data"], [])
        self.assertNotIn(b"Middle", cleared.read_bytes(), "the old chapter titles must not stay in the file")
        again = OUT / "a460_again.mp4"
        script("metadata.py", tagged, "--chapters", chapters, "-o", again)
        self.assertEqual([s["codec_tag_string"] for s in self._counts(again) if s["codec_type"] == "data"], ["text"])
        for tool, args, name in (("denoise.py", ["--fast"], "a460_denoise.mp4"),
                                 ("export.py", ["--preset", "youtube", "--fast"], "a460_export.mp4")):
            with self.subTest(tool=tool):
                out = OUT / name
                script(tool, tagged, *args, "-o", out)
                self.assertEqual([s["codec_tag_string"] for s in self._counts(out) if s["codec_type"] == "data"], ["text"])

    def test_reverse_warns_from_what_it_holds_not_from_the_length(self):
        """A174: memory_heavy was keyed on a length above 60 s, so a 30 s 4K60 clip (about 21 GiB of
        decoded frames) got no warning and a 61 s 320x180 one (about 0.1 GiB) did. 5 s of 4K60 is
        about 3.5 GiB of 4:2:0 frames."""
        big = OUT / "a460_4k60.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=3840x2160:r=60:d=5",
           "-c:v", "libx264", "-preset", "ultrafast", "-qp", "40", big)
        small = OUT / "a460_small61.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=61",
           "-c:v", "libx264", "-preset", "ultrafast", "-qp", "40", small)
        for path, heavy in ((big, True), (small, False)):
            with self.subTest(clip=path.name):
                doc = json.loads(script("reverse.py", path, "--dry-run", "-o", OUT / "a460_rev_plan.mp4", "--json").stdout)
                codes = [w["code"] for w in (doc.get("diagnostics") or {}).get("warnings", [])]
                self.assertEqual("memory_heavy" in codes, heavy, codes)
        big.unlink()

    def test_reverse_of_a_variable_rate_clip_ends_with_its_sound(self):
        """A234: on a variable frame rate the graph closed on r_frame_rate and the output's -r then
        resampled it to the average rate, so reverse wrote 51 frames for 49 that ran 81 ms past its
        sound. The graph now closes on the rate the encoder line delivers. The picture's length is
        measured, not its frame count (which is the FFmpeg's)."""
        vfr = OUT / "a460_vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=2",
           "-f", "lavfi", "-i", "sine=d=2", "-vf", "select='not(between(n,10,15))*not(between(n,40,44))'",
           "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", vfr)
        src = probe(str(vfr))
        self.assertTrue(src["video"].get("variable_frame_rate_suspected"), "the fixture must read as VFR")
        out = OUT / "a460_vfr_rev.mp4"
        script("reverse.py", vfr, "--fast", "-o", out)
        streams = {s["codec_type"]: s for s in self._counts(out)}
        frame = 1 / float(probe(str(out))["video"]["fps"])
        self.assertLess(abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])), frame / 2, streams)
        self.assertLess(abs(float(streams["video"]["duration"]) - float(src["video"]["duration"])), frame / 2, streams)

    def test_reverse_of_a_variable_rate_clip_opens_on_its_last_frame(self):
        """#513 review: with the closing rate the delivered one (about 20 fps here), the trim that
        drops the hold's spare clones cut half a DELIVERED frame before the end, and a real last
        frame nearer the end than that (1.983 s on the source's 1/60 grid) was dropped before the
        reversal, which then opened on the frame before it. The last frame is the only white one."""
        vfr = OUT / "a460_vfr_last.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=60:d=2",
           "-f", "lavfi", "-i", "sine=d=2",
           "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='eq(n,119)',select='not(mod(n,3))+eq(n,119)'",
           "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", vfr)
        self.assertTrue(probe(str(vfr))["video"].get("variable_frame_rate_suspected"), "the fixture must read as VFR")
        out = OUT / "a460_vfr_last_rev.mp4"
        script("reverse.py", vfr, "--fast", "-o", out)
        self.assertGreater(min(frame_rgb(out, 0, 80, 60)), 200, "the reversed clip must open on the source's last frame")

    def test_loop_crossfade_keeps_a_late_picture_with_its_sound(self):
        """A168: the crossfade's unit rebased each stream to its own start (the picture's setpts,
        the sound's aresample first_pts=0), so a picture that starts 0.2 s after its sound came out
        200 ms behind it in every repeat. Both are now shifted by the picture's start. The first
        flash is the faded-in tail's, which no beep marks."""
        for name, kw in (("vlate", {"video_late": 0.2}), ("alate", {"audio_late": 0.2}), ("sync", {})):
            with self.subTest(source=name):
                src = make_flash_beep(OUT / f"a460_loop_{name}.mp4", **kw)
                out = OUT / f"a460_loop_{name}_x.mp4"
                script("loop.py", src, "--crossfade", "0.5", "--times", "2", "--fast", "-o", out)
                offsets = av_offsets_ms(out)[1:]
                self.assertTrue(offsets, name)
                for o in offsets:
                    self.assertLessEqual(abs(o), 5, f"{name}: flash minus beep {offsets} ms")

    def test_straighten_crop_writes_the_source_size_with_square_pixels(self):
        """A235: --fit crop scaled by s and cropped back to trunc(iw/s/2)*2, two roundings that
        wrote 1920x1080 as 1918x1078 (and, on other angles, a SAR such as 6112:6111)."""
        hd = tiny_clip(OUT / "a460_hd.mp4", "testsrc2=s=1920x1080:r=25", seconds=0.4)
        for degrees in ("3", "-7", "12"):
            with self.subTest(degrees=degrees):
                out = OUT / "a460_straight.mp4"
                script("straighten.py", hd, "--degrees", degrees, "--fit", "crop", "--fast", "-o", out)
                v = probe(str(out))["video"]
                self.assertEqual((v["width"], v["height"]), (1920, 1080))
                self.assertIn(v.get("sample_aspect_ratio"), ("1:1", None, "0:1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
