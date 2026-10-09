#!/usr/bin/env python3
"""cut.py's stream-copy and --segments join paths, checked on the decoded frames they produce.

    python3 tests/test_cut_copy.py      # this group alone
    python3 tests/test_all.py           # every group

The fixtures are small and built once here: an HEVC source with B-frames (the Core Media shape
the carry-forward fixes are about), an H.264 source whose audio starts 0.379 s after its video,
and a WAV. Frames are identified by PSNR against the source's own frames rather than by hash,
because a re-encoded join cannot reproduce a frame bit for bit; testsrc2 changes on every frame,
so the right frame and its neighbours are tens of dB apart.
"""
import importlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import OUT, SCRIPTS, script, sh  # noqa: E402
from _common import decision, probe  # noqa: E402
probe_mod = sys.modules["_common.probe"]  # the module (the package re-exports probe() under its name)

sys.path.insert(0, str(SCRIPTS))
import cut  # noqa: E402

DIR = OUT / "cut_copy"
FPS = 30
W, H = 64, 36


def gray_frames(path):
    """Every frame of `path`, decoded and scaled to a 64x36 grey thumbnail."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough", "-vf", f"scale={W}:{H},format=yuv420p,extractplanes=y",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE, check=True).stdout
    n = W * H
    return [raw[i:i + n] for i in range(0, len(raw), n)]


def psnr(a, b):
    mse = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    return 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)


def frame_pts(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                          "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, text=True, check=True).stdout
    return [float(x.split(",")[0]) for x in out.split()]


def md5_frames(path):
    """Every decoded frame's MD5, in presentation order: a stream copy reproduces them exactly."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-fps_mode", "passthrough",
                          "-f", "framemd5", "-"], stdout=subprocess.PIPE, text=True, check=True).stdout
    return [line.split(",")[-1].strip() for line in raw.splitlines() if line and not line.startswith("#")]


def steps(path):
    pts = sorted(frame_pts(path))
    return {round(b - a, 4) for a, b in zip(pts, pts[1:])}


def stderr_of_decode(path):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stderr.strip()


def cut_json(*args):
    return json.loads(script("cut.py", *args, "--json").stdout)


class CutJoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DIR.mkdir(parents=True, exist_ok=True)
        cls.hevc = DIR / "hevc.mp4"
        if not cls.hevc.exists():
            # keyframes every 2 s (keyint 60), 4 B-frames, hvc1 as Core Media writes it
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=12",
               "-f", "lavfi", "-i", "sine=f=440:d=12", "-c:v", "libx265",
               "-x265-params", "bframes=4:b-pyramid=1:keyint=60:min-keyint=60:scenecut=0:log-level=error",
               "-tag:v", "hvc1", "-c:a", "aac", "-shortest", cls.hevc)
        cls.hevc25 = DIR / "hevc25.mp4"
        if not cls.hevc25.exists():
            # the shape a join-length check misjudged: 25 fps, keyint 50, 4 B-frames, 48 kHz AAC
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12",
               "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000", "-c:v", "libx265",
               "-x265-params", "bframes=4:keyint=50:min-keyint=50:scenecut=0:log-level=error",
               "-tag:v", "hvc1", "-c:a", "aac", "-shortest", cls.hevc25)
        cls.late = DIR / "late_audio.mp4"
        if not cls.late.exists():
            # baseline profile, so a re-encoded part (x264 high) can never match a copied one
            base = DIR / "late_base.mp4"
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=8",
               "-f", "lavfi", "-i", "sine=f=440:d=8", "-c:v", "libx264", "-profile:v", "baseline", "-g", str(FPS),
               "-c:a", "aac", base)
            sh("ffmpeg", "-y", "-v", "error", "-i", base, "-itsoffset", "0.379", "-i", base,
               "-map", "0:v", "-map", "1:a", "-c", "copy", cls.late)
        cls.wav = DIR / "tone.wav"
        if not cls.wav.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=300:d=6:sample_rate=44100",
               "-c:a", "pcm_s16le", cls.wav)
        cls.rot = DIR / "rot.mp4"
        if not cls.rot.exists():
            sh("ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", cls.hevc, "-c", "copy", cls.rot)
        cls.subs = DIR / "subs.mp4"
        if not cls.subs.exists():
            srt = DIR / "subs.srt"
            srt.write_text("1\n00:00:00,500 --> 00:00:09,000\nhello\n", encoding="utf-8")
            sh("ffmpeg", "-y", "-v", "error", "-i", cls.hevc, "-i", srt, "-map", "0", "-map", "1",
               "-c", "copy", "-c:s", "mov_text", cls.subs)
        cls.noise = DIR / "hevc_noise.mp4"
        if not cls.noise.exists():
            # the same pictures with a non-periodic audio track, so a cross-correlation has one peak
            sh("ffmpeg", "-y", "-v", "error", "-i", cls.hevc, "-f", "lavfi", "-i", "anoisesrc=seed=7:d=12:a=0.3:r=48000",
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", cls.noise)
        cls.offset = DIR / "hevc_offset.mp4"
        if not cls.offset.exists():
            # a source whose timestamps start at 10 s
            sh("ffmpeg", "-y", "-v", "error", "-i", cls.hevc, "-c", "copy", "-output_ts_offset", "10", cls.offset)
        cls.long = DIR / "long_audio.mp4"
        if not cls.long.exists():
            # sound that outlasts the picture by 0.3 s (a music bed padded to the container), g30
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=6",
               "-f", "lavfi", "-i", "sine=f=440:d=6.3:sample_rate=48000", "-c:v", "libx264", "-g", "30",
               "-c:a", "aac", cls.long)
        cls.tail = DIR / "tail_audio.mp4"
        if not cls.tail.exists():
            # the same, by 20 ms: an ordinary AAC tail, under one frame
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=6",
               "-f", "lavfi", "-i", "sine=f=440:d=6.02:sample_rate=48000", "-c:v", "libx264", "-g", "30",
               "-c:a", "aac", cls.tail)
        cls.long_offset = DIR / "long_audio_offset.mp4"
        if not cls.long_offset.exists():
            sh("ffmpeg", "-y", "-v", "error", "-i", cls.long, "-c", "copy", "-output_ts_offset", "10", cls.long_offset)
        # the copy-join sources:
        # x264 B-frames (a closed GOP), x265 with open-gop=0, and x265's default open GOP in HLG
        x264bf = ("-c:v", "libx264", "-g", "60", "-bf", "3", "-x264-params", "scenecut=0")
        cls.h264bf = DIR / "h264bf.mp4"
        if not cls.h264bf.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=12",
               "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000", *x264bf, "-c:a", "aac", "-shortest", cls.h264bf)
        cls.hevc25c = DIR / "hevc25c.mp4"
        if not cls.hevc25c.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12",
               "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000", "-c:v", "libx265",
               "-x265-params", "bframes=4:keyint=50:min-keyint=50:scenecut=0:open-gop=0:log-level=error",
               "-tag:v", "hvc1", "-c:a", "aac", "-shortest", cls.hevc25c)
        cls.beep = DIR / "beep_bf.mp4"
        if not cls.beep.exists():
            # a 40 ms beep at every k + 0.5 s, so every onset has silence before it to measure from
            beep = "aevalsrc='if(between(mod(t\\,1)\\,0.5\\,0.54)\\,0.8*sin(2*PI*1000*t)\\,0)':s=48000:d=12"
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=12",
               "-f", "lavfi", "-i", beep, *x264bf, "-c:a", "aac", "-shortest", cls.beep)
        cls.hlg = DIR / "hlg_open.mp4"
        if not cls.hlg.exists():
            # the iPhone "High Efficiency" shape: 10-bit HLG HEVC with an open GOP at every keyframe
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=6",
               "-f", "lavfi", "-i", "sine=f=440:d=6:sample_rate=48000", "-pix_fmt", "yuv420p10le", "-c:v", "libx265",
               "-x265-params", "bframes=4:keyint=60:min-keyint=60:scenecut=0:log-level=error:"
                               "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
               "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
               "-tag:v", "hvc1", "-c:a", "aac", "-shortest", cls.hlg)
        cls.nob60 = DIR / "nob60.mp4"
        if not cls.nob60.exists():
            # the iPhone "Most Compatible" shape: H.264 with no B-frames, here at 60 fps and 44.1 kHz
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=60:d=12",
               "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=44100", "-c:v", "libx264", "-bf", "0", "-g", "120",
               "-x264-params", "scenecut=0", "-c:a", "aac", "-shortest", cls.nob60)
        cls.src_frames = gray_frames(cls.hevc)
        cls.long_frames = gray_frames(cls.long)

    def assertFrameIs(self, frame, expected, msg="", src_frames=None):
        """`frame` is source frame `expected`: its best match within 5 frames, at 40 dB or more,
        and 10 dB clear of the next best."""
        src_frames = self.src_frames if src_frames is None else src_frames
        lo, hi = max(0, expected - 5), min(len(src_frames), expected + 6)
        scores = sorted(((psnr(frame, src_frames[i]), i) for i in range(lo, hi)), reverse=True)
        (best, idx), (second, _) = scores[0], scores[1]
        self.assertEqual(idx, expected, f"{msg}: best match {idx} at {best:.1f} dB")
        self.assertGreaterEqual(best, 40.0, msg)
        self.assertGreaterEqual(best - second, 10.0, msg)

    def assertFrameExact(self, frame, expected, msg=""):
        """A stream copy decodes bit-identically: `frame` is source frame `expected` exactly."""
        self.assertEqual(psnr(frame, self.src_frames[expected]), 99.0, msg)

    # ------------------------------------------------------------------ single-segment copies
    def test_an_mp4_copy_starts_its_picture_at_the_requested_time(self):
        """Core Media HEVC once gave 3.7 s of sound with no picture: make_zero showed the keyframe's
        pre-roll. The copy now keeps its edit list, which hides it."""
        out = DIR / "copy_4.3.mp4"
        data = cut_json(self.hevc, "--start", "4.3", "--duration", "3", "--tolerance", "-1", "-o", out)
        self.assertEqual(data["mode"], "copy")
        self.assertEqual(data["reencode_reason"], [])
        self.assertTrue(data["edit_list"])
        self.assertTrue(data["keyframe_snapped"], "a stream copy end to end")
        self.assertFalse(data["start_snapped"])
        self.assertAlmostEqual(data["stored_preroll_seconds"], 0.3, places=3, msg="4.3 s back to the keyframe at 4.0")
        self.assertIn("edit list", " ".join(data["notes"]))
        self.assertLessEqual(abs(data["av_start_skew_seconds"]), 1 / FPS)
        frames = gray_frames(out)
        self.assertFrameExact(frames[0], 129, "first presented frame is the source frame at 4.3 s")
        # the end still lands on a packet boundary: bounded, and the last frame is the source's own
        over = probe(str(out))["video"]["duration"] - 3.0
        self.assertGreaterEqual(over, -1e-6)
        self.assertLessEqual(over, 6 / FPS)
        # the frames past the requested end are not contiguous (B-frames whose references were not
        # copied are dropped: measured 218, 221, 223), so the last one is located by its own pts
        last_pts = frame_pts(out)[-1]
        self.assertFrameExact(frames[-1], 129 + round(last_pts * FPS), "last frame, at its own presented time")

    def test_a_dry_run_mp4_copy_reports_the_edit_list_it_plans(self):
        data = cut_json(self.hevc, "--start", "4.3", "--duration", "2", "--dry-run", "-o", DIR / "never.mp4")
        self.assertTrue(data["edit_list"])
        self.assertEqual(data["commands"][0].count("-avoid_negative_ts"), 0)

    def test_an_edit_listed_copy_past_tolerance_blames_the_end_not_the_start(self):
        """The start is exact, so offering another --start as the lossless alternative would be
        wrong: only the end overshoots (+4 to +5 frames on this fixture)."""
        out = DIR / "copy_tight.mp4"
        proc = script("cut.py", self.hevc, "--start", "4.3", "--duration", "3", "--tolerance", "0.05", "-o", out, "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["reencode_reason"], ["tolerance"])
        self.assertIsNone(data["lossless_alternative"])
        self.assertIsNone(data["nearest_keyframes"])
        self.assertIn("starts where asked", proc.stderr)

    def test_an_off_grid_start_presents_the_next_source_frame(self):
        out = DIR / "copy_4.31.mp4"
        cut_json(self.hevc, "--start", "4.31", "--duration", "2", "--tolerance", "-1", "-o", out)
        self.assertFrameExact(gray_frames(out)[0], 130, "the first frame at or after 4.31 s is 4.333 s")

    def test_a_start_just_before_a_keyframe_is_reported_as_snapped(self):
        """The demuxer seeks by decode time: the keyframe at 10.0 (dts 9.833) is taken for 9.9, so
        the copy's picture starts three frames late. That is a snap, and it says so."""
        out = DIR / "copy_9.9.mp4"
        data = cut_json(self.hevc, "--start", "9.9", "--duration", "1", "--tolerance", "-1", "-o", out)
        self.assertEqual(data["mode"], "copy")
        self.assertTrue(data["start_snapped"])
        self.assertIsNone(data["stored_preroll_seconds"])
        self.assertFrameExact(gray_frames(out)[0], 300)

    def test_a_source_that_starts_at_ten_seconds_cuts_the_same_frame(self):
        out = DIR / "copy_offset.mp4"
        data = cut_json(self.offset, "--start", "4.3", "--duration", "2", "--tolerance", "-1", "-o", out)
        self.assertTrue(data["edit_list"])
        # --start is relative to the file's start and packet times are absolute: the report must
        # still find the keyframe at 4.0 (14.0 in the file)
        self.assertFalse(data["start_snapped"])
        self.assertAlmostEqual(data["stored_preroll_seconds"], 0.3, places=3)
        self.assertFrameExact(gray_frames(out)[0], 129)
        # cutting that result again: the VFR sampler must read its stored pre-roll, or a seek to its
        # start skips the keyframe (negative pts) and finds too few frames to judge
        again = cut_json(out, "--start", "0.5", "--duration", "1", "--dry-run", "-o", DIR / "never_again.mp4")
        self.assertEqual(again["vfr_check"]["measured"], "sampled_cfr")

    def test_an_edit_listed_source_cut_again_starts_where_asked(self):
        first = DIR / "copy_again_1.mp4"
        cut_json(self.hevc, "--start", "4.3", "--duration", "4", "--tolerance", "-1", "-o", first)
        out = DIR / "copy_again_2.mp4"
        data = cut_json(first, "--start", "1", "--duration", "2", "--tolerance", "-1", "-o", out)
        # the VFR sampler reads the stored pre-roll too (a seek to 0 skipped its keyframe and found
        # too few frames to judge, forcing a re-encode)
        self.assertEqual((data["vfr_check"]["measured"], data["mode"]), ("sampled_cfr", "copy"))
        self.assertFrameExact(gray_frames(out)[0], 159, "1 s into a cut that starts at 4.3 s")

    def test_the_copy_keeps_audio_in_step_with_the_picture(self):
        out = DIR / "copy_noise.mp4"
        cut_json(self.noise, "--start", "4.3", "--duration", "2", "--tolerance", "-1", "-o", out)
        rate = 8000

        def pcm(path, *pre):
            raw = subprocess.run(["ffmpeg", "-v", "error", *pre, "-i", str(path), "-t", "0.5", "-ac", "1", "-ar", str(rate),
                                  "-f", "s16le", "-"], stdout=subprocess.PIPE, check=True).stdout
            return [int.from_bytes(raw[i:i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)]
        # the source from 0.1 s before the cut, decoded the same way; the output's first 0.2 s
        # should sit 0.1 s (800 samples) into it
        ref = pcm(self.noise, "-ss", "4.2")
        got = pcm(out)[:int(0.2 * rate)]

        def corr(lag):
            return sum(a * b for a, b in zip(got, ref[lag:lag + len(got)]))
        lag = max(range(700, 901), key=corr)
        self.assertLessEqual(abs(lag - 800), 8, f"audio is {lag - 800} samples off the picture (±1 ms allowed)")

    def test_an_unmeasured_start_is_never_reported_as_exact(self):
        """No packet at or after the start in the probed window: the start is unknown, so it is
        not claimed exact and no pre-roll is reported."""
        self.assertEqual(cut.copy_presentation(4.3, (4.0, 3.9, None), True, 30.0),
                         {"start_snapped": True, "stored_preroll_seconds": None})
        self.assertEqual(cut.copy_presentation(4.3, (4.0, 3.9, 4.3), True, 30.0),
                         {"start_snapped": False, "stored_preroll_seconds": 0.3})

    def test_judging_a_copy_by_its_video_is_noted_even_when_it_then_reencodes(self):
        """The late-audio source's container outlasts its video by 0.379 s, so the copy is judged
        by the video; that explanation survives the tolerance re-encode that follows (--tolerance 0
        re-encodes every copy, since abs(delta) >= 0)."""
        # to the end of the file, where the late audio runs 0.379 s past the video
        data = cut_json(self.late, "--start", "0.5", "--tolerance", "0",
                        "-o", DIR / "late_judged.mp4")
        self.assertIn("tolerance", data["reencode_reason"])
        self.assertTrue(any("judged by the video" in n for n in data["notes"]), data["notes"])

    def test_av_skew_is_measured_and_named_past_the_threshold(self):
        skew, note = cut.av_skew({"video": {"start_time": 0.0, "fps": 30.0}, "audio": {"start_time": 0.5}})
        self.assertEqual(skew, 0.5)
        self.assertIn("--accurate", note)
        self.assertEqual(cut.av_skew({"video": {"start_time": 0.0, "fps": 30.0}, "audio": {"start_time": 0.02}}), (0.02, None))
        self.assertEqual(cut.av_skew({"video": {"start_time": 0.0, "fps": 30.0}}), (None, None))

    def test_accurate_keeps_the_frames_before_a_keyframe(self):
        """--accurate seeked straight to the start, and by decode time -ss 9.9 lands on the
        keyframe at 10.0; the three frames before it were lost."""
        out = DIR / "accurate_9.9.mp4"
        data = cut_json(self.hevc, "--start", "9.9", "--end", "10.1", "--accurate", "-o", out)
        self.assertEqual(data["mode"], "accurate")
        frames = gray_frames(out)
        self.assertEqual(len(frames), 6)
        self.assertFrameIs(frames[0], 297, "first frame of 9.9-10.1")
        self.assertFrameIs(frames[-1], 302, "last frame of 9.9-10.1")

    # ------------------------------------------------------------------ the source codec
    def test_a_reencoded_cut_of_an_sdr_hevc_source_stays_hevc(self):
        """A re-encode went through x264 whatever the source, so trimming an iPhone HEVC
        clip with --accurate handed back H.264. It now keeps HEVC, 8-bit and tagged BT.709."""
        out = DIR / "accurate_hevc.mp4"
        data = cut_json(self.hevc, "--start", "4.3", "--duration", "1", "--accurate", "--preset", "ultrafast", "-o", out)
        self.assertTrue(data["reencoded"])
        v = probe(str(out))["video"]
        self.assertEqual(v["codec"], "hevc")
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertEqual((v["color_primaries"], v["color_transfer"], v["color_space"]), ("bt709", "bt709", "bt709"))
        self.assertEqual(stderr_of_decode(out), "")

    def test_codec_h264_still_overrides_the_source_codec(self):
        out = DIR / "accurate_h264.mp4"
        data = cut_json(self.hevc, "--start", "4.3", "--duration", "1", "--codec", "h264", "--preset", "ultrafast", "-o", out)
        self.assertIn("codec", data["reencode_reason"])
        self.assertEqual(probe(str(out))["video"]["codec"], "h264")

    # ------------------------------------------------------------------ the join fallback
    def test_mismatched_parts_are_recut_from_the_source_with_exact_boundaries(self):
        """The live bug: a copied HEVC segment next to a re-encoded one used to be joined by the
        concat demuxer -- H.264 after HEVC decoded with errors from a run that exited 0. The join
        now re-cuts both segments from the source in one encode."""
        out = DIR / "mixed.mp4"
        # 0-2 starts on the keyframe at 0 and copies; 5.1 snaps back to the keyframe at 4, 1.1 s
        # past the 0.3 s tolerance, so it re-encodes
        data = cut_json(self.hevc, "--segments", "0-2,5.1-7", "--tolerance", "0.3", "-o", out)
        self.assertEqual(data["reencode_reason"], ["tolerance", "concat_fallback"])
        self.assertTrue(data["reencoded"])
        self.assertEqual(data["mode"], "hybrid")
        self.assertEqual(data["segment_precision"], ["frame", "frame"])
        self.assertEqual((data["precision"], data["least_exact_precision"]), ("frame", "frame"))
        self.assertFalse(data["keyframe_snapped"])
        self.assertFalse(data["start_snapped"], "every segment was re-cut, so every start is where asked")
        self.assertEqual(stderr_of_decode(out), "")
        self.assertEqual(probe(str(out))["video"]["codec"], "hevc", "the re-cut join keeps the source codec")
        pts = frame_pts(out)
        self.assertEqual(len(pts), 60 + 57)
        deltas = [round(b - a, 4) for a, b in zip(pts, pts[1:])]
        self.assertEqual(set(deltas), {round(1 / FPS, 4)}, "no pts gap at the join")
        m = probe(str(out))
        self.assertLessEqual(abs(m["video"]["duration"] - m["audio"]["duration"]), 1 / FPS + 0.03)
        frames = gray_frames(out)
        self.assertFrameIs(frames[0], 0, "first frame of segment 0")
        self.assertFrameIs(frames[59], 59, "last frame of segment 0")
        self.assertFrameIs(frames[60], 153, "first frame of segment 1 (5.1 s)")
        self.assertFrameIs(frames[116], 209, "last frame of segment 1")

    def test_a_delayed_audio_track_keeps_its_offset_through_the_fallback(self):
        out = DIR / "late_join.mp4"
        data = cut_json(self.late, "--segments", "0-2,4.5-6", "--tolerance", "0.3", "-o", out)
        self.assertIn("concat_fallback", data["reencode_reason"], "the premise: the parts must not match")
        log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-af", "silencedetect=n=-40dB:d=0.05",
                              "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stderr
        starts = [float(v) for v in re.findall(r"silence_start: (-?[0-9.]+)", log)]
        ends = [float(v) for v in re.findall(r"silence_end: (-?[0-9.]+)", log)]
        self.assertTrue(starts and ends, log)
        self.assertAlmostEqual(starts[0], 0.0, delta=0.02)
        self.assertAlmostEqual(ends[0], 0.379, delta=0.02)
        m = probe(str(out))
        self.assertLessEqual(abs(m["video"]["duration"] - m["audio"]["duration"]), 1 / FPS + 0.03)

    # ------------------------------------------------------------------ a segment past the video's end
    def assertHeldJoin(self, out, data):
        """`--segments 4-6.3,0-2` of long_audio: 2.3 s then 2 s, with no hole. Output frames 0-59
        are source 120-179, 60-68 hold source frame 179 for the sound that runs on, and 69-128 are
        source 0-59."""
        pts = frame_pts(out)
        self.assertEqual(len(pts), 69 + 60, data.get("notes"))
        self.assertEqual({round(b - a, 4) for a, b in zip(pts, pts[1:])}, {round(1 / FPS, 4)}, "no hole in the video")
        frames = gray_frames(out)

        def best(frame, candidates):
            return max(candidates, key=lambda i: psnr(frame, self.long_frames[i]))
        self.assertEqual(best(frames[0], range(115, 126)), 120)
        for i in (59, 60, 64, 68):
            self.assertEqual(best(frames[i], range(170, 180)), 179, f"output frame {i} holds the last picture")
            self.assertGreaterEqual(psnr(frames[i], self.long_frames[179]), 35.0)
        self.assertEqual(best(frames[69], range(0, 6)), 0, "the next segment starts on its own first frame")
        self.assertEqual(best(frames[128], range(54, 60)), 59)
        self.assertIn("concat_fallback", data["reencode_reason"])

    def test_a_segment_past_the_video_end_holds_its_last_frame_in_a_copy_join(self):
        """The copy join placed the next segment after the 0.3 s of sound with no picture, leaving a
        0.355 s hole in the video, and reported mode copy. A copy cannot add a frame, so the join
        is re-cut from the source with the last frame held for the sound."""
        out = DIR / "held_copy.mp4"
        data = cut_json(self.long, "--segments", "4-6.3,0-2", "-o", out)
        self.assertEqual(data["mode"], "hybrid")
        self.assertTrue(any("past the end of the video" in n for n in data["notes"]), data["notes"])
        self.assertNotIn("vfr_check", data, "a held join cannot copy, so the frame timing is not sampled")
        self.assertHeldJoin(out, data)

    def test_a_repeat_of_a_held_segment_in_last_place_is_not_held(self):
        """The hold is decided by position: the same range twice, first and last, holds only the
        first. 69 + 60 + 60 frames, not 69 + 60 + 69."""
        out = DIR / "held_repeat.mp4"
        cut_json(self.long, "--segments", "4-6.3,0-2,4-6.3", "--accurate", "-o", out)
        self.assertEqual(len(frame_pts(out)), 69 + 60 + 60)

    def test_a_segment_past_the_video_end_holds_its_last_frame_when_accurate(self):
        """--accurate re-encoded each part and then copy-joined them, with the same hole."""
        out = DIR / "held_accurate.mp4"
        data = cut_json(self.long, "--segments", "4-6.3,0-2", "--accurate", "-o", out)
        self.assertEqual(data["mode"], "accurate")
        self.assertHeldJoin(out, data)

    def test_the_video_end_is_measured_from_the_files_own_start(self):
        """A source whose timestamps start at 10 s: stream start_time is raw, segment times are
        relative to the file, so the video's end is 6.0 here, not 16.0."""
        out = DIR / "held_offset.mp4"
        data = cut_json(self.long_offset, "--segments", "4-6.3,0-2", "--accurate", "-o", out)
        self.assertHeldJoin(out, data)

    def test_a_sound_tail_under_a_frame_ends_the_segment_with_its_picture(self):
        """20 ms of sound past the picture is trimmed, not held for: a 60 + 60 frame join with no
        fractional hole, and the trim is named. requested_segments keeps what was asked (clamped
        to the media's duration, as in every 2.x release); duration_delta_seconds shows the trim."""
        out = DIR / "tail_trim.mp4"
        data = cut_json(self.tail, "--segments", "4-6.02,0-2", "--accurate", "-o", out)
        pts = frame_pts(out)
        self.assertEqual(len(pts), 120)
        self.assertEqual({round(b - a, 4) for a, b in zip(pts, pts[1:])}, {round(1 / FPS, 4)})
        self.assertEqual(data["requested_segments"][0], [4.0, 6.02])
        self.assertAlmostEqual(data["requested_duration"], 4.02, places=6)
        self.assertAlmostEqual(data["expected_duration"], 4.02, places=6)
        # the trim shows in the delta against the request (120 frames are 4.0 s against 4.02 s
        # asked), give or take an AAC frame of the joined sound, which FFmpeg versions pad differently
        self.assertAlmostEqual(data["duration_delta_seconds"], data["output_duration"] - 4.02, places=6)
        self.assertLess(abs(data["duration_delta_seconds"]), 1 / FPS + 1024 / 48000)
        self.assertTrue(any("ends with the video" in n for n in data["notes"]), data["notes"])

    def test_an_accurate_join_has_no_hole_at_its_joins(self):
        """--accurate used to re-encode each part on its own and copy-join them: each part's AAC ran
        an encoder frame past its picture and the concat demuxer placed the next part after it, a
        23 ms hole at every join of every --accurate --segments run. One encode through the concat
        filter has none, and it is what was asked for, not a fallback."""
        out = DIR / "accurate_join.mp4"
        data = cut_json(self.hevc, "--segments", "0-2,4-6", "--accurate", "-o", out)
        self.assertEqual(data["reencode_reason"], ["requested"])
        self.assertEqual(data["mode"], "accurate")
        pts = frame_pts(out)
        self.assertEqual(len(pts), 120)
        self.assertEqual({round(b - a, 4) for a, b in zip(pts, pts[1:])}, {round(1 / FPS, 4)})
        frames = gray_frames(out)
        self.assertFrameIs(frames[59], 59, "last frame of segment 0")
        self.assertFrameIs(frames[60], 120, "first frame of segment 1 (4.0 s)")

    def test_the_last_segment_past_the_video_end_is_left_alone(self):
        """No join follows the last segment, so its sound-only tail is what the source had: no hold,
        no pre-check fallback."""
        out = DIR / "held_last.mp4"
        data = cut_json(self.long, "--segments", "0-2,4-6.3", "--accurate", "-o", out)
        self.assertNotIn("concat_fallback", data["reencode_reason"])
        self.assertFalse(any("past the end of the video" in n for n in data["notes"]))
        self.assertEqual(data["requested_segments"][1], [4.0, 6.3])
        self.assertEqual(len(frame_pts(out)), 60 + 60, "the picture ends where the source's does; no frame is held")

    def test_a_rotated_source_joins_in_display_orientation(self):
        out = DIR / "rot_join.mp4"
        data = cut_json(self.rot, "--segments", "0-2,5.1-7", "--tolerance", "0.3", "-o", out)
        self.assertIn("concat_fallback", data["reencode_reason"])
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (180, 320))
        self.assertEqual(m["video"]["rotation"], 0)
        self.assertEqual(len(frame_pts(out)), 60 + 57)
        self.assertEqual(stderr_of_decode(out), "")

    def test_subtitles_are_dropped_by_the_fallback_and_reported(self):
        out = DIR / "subs_join.mp4"
        data = cut_json(self.subs, "--segments", "0-2,5.1-7", "--tolerance", "0.3", "-o", out)
        self.assertIn("concat_fallback", data["reencode_reason"])
        self.assertTrue(data["dropped_non_av_streams"])
        self.assertEqual(probe(str(out))["subtitle_streams"], 0)

    def test_more_segments_than_one_call_takes_are_joined_in_chunks(self):
        out = DIR / "many.mp4"
        # 40 segments of 0.2 s; those not on a keyframe re-encode, so the parts are mixed
        segs = ",".join(f"{i * 0.3:.1f}-{i * 0.3 + 0.2:.1f}" for i in range(40))
        data = cut_json(self.hevc, "--segments", segs, "--tolerance", "0.1", "--preset", "ultrafast", "-o", out)
        self.assertIn("concat_fallback", data["reencode_reason"])
        self.assertEqual(sum("concat=n=32:" in c for c in data["commands"]), 1)
        self.assertEqual(sum("concat=n=8:" in c for c in data["commands"]), 1)
        self.assertEqual(stderr_of_decode(out), "")
        self.assertEqual(len(frame_pts(out)), 40 * 6)
        starts = dict(line.split(",")[:2] for line in subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "csv=p=0", str(out)],
            stdout=subprocess.PIPE, text=True, check=True).stdout.split())
        self.assertLessEqual(abs(float(starts["video"]) - float(starts["audio"])), 0.005, "chunking adds no A/V offset")
        tag = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_tag_string",
                              "-of", "csv=p=0", str(out)], stdout=subprocess.PIPE, text=True, check=True).stdout.strip()
        self.assertEqual(tag, "hvc1", "the Matroska chunks' HEVC keeps the tag Apple players need")

    # ------------------------------------------------------------------ an exact stream-copy join
    def test_keyframe_aligned_bframe_segments_join_frame_exact(self):
        """The copy join used to add the next GOP's keyframe and P-frame to every part (an
        input -t stops in decode order) and show them: 186 frames for 180, with holes, reported as
        mode copy. Each part now ends at its end keyframe's dts and keeps its edit list."""
        out = DIR / "keyframe_join.mp4"
        data = cut_json(self.h264bf, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        self.assertEqual(data["segment_precision"], ["packet", "packet", "packet"])
        src = md5_frames(self.h264bf)
        self.assertEqual(md5_frames(out), src[0:60] + src[120:180] + src[240:300])
        self.assertEqual(steps(out), {round(1 / FPS, 4)})
        self.assertEqual((data["join_check"]["packets"], data["join_check"]["expected_packets"]), (180, 180))
        self.assertTrue(data["join_check"]["ok"])
        self.assertEqual(data["segment_end_snap_seconds"], [0.0, 0.0, 0.0])

    def test_closed_gop_hevc_segments_join_frame_exact(self):
        """The same on HEVC with a closed GOP: 150 frames, each the source's own."""
        out = DIR / "keyframe_join_hevc.mp4"
        data = cut_json(self.hevc25c, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        self.assertEqual(probe(str(out))["video"]["codec"], "hevc")
        src = md5_frames(self.hevc25c)
        self.assertEqual(md5_frames(out), src[0:50] + src[100:150] + src[200:250])
        self.assertEqual(steps(out), {0.04})
        self.assertTrue(data["join_check"]["ok"])

    def test_a_60fps_source_without_bframes_stays_an_exact_copy(self):
        """With no B-frames each part's AAC runs up to one audio frame (23 ms at 44.1 kHz) past its
        picture, and the concat demuxer places the next part after it, so the frame before a join
        shows longer than 1/60 s -- past half a frame, which a stricter check would have sent to a
        re-encode. The frames are the source's own, as a copy join of this footage always was."""
        out = DIR / "nob60_join.mp4"
        data = cut_json(self.nob60, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        src = md5_frames(self.nob60)
        self.assertEqual(md5_frames(out), src[0:120] + src[240:360] + src[480:600])
        self.assertTrue(data["join_check"]["ok"])
        self.assertGreater(data["join_check"]["max_step_seconds"], 1.5 / 60, "the premise: a step past half a frame")

    def test_a_matroska_join_is_checked_and_recut_when_it_is_wrong(self):
        """Matroska parts keep the old cut (make_zero, -t end-start, no end snap), which carries the
        next GOP's keyframe and P-frame into each part. Nothing predicts that; the join check
        measures it, and the join is re-cut, keeping the failed measurement."""
        out = DIR / "mkv_join.mkv"
        data = cut_json(self.h264bf, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertIn("concat_fallback", data["reencode_reason"])
        self.assertFalse(data["join_check"]["ok"])
        self.assertEqual(data["join_check"]["expected_packets"], 180)
        self.assertTrue(any("checked and failed" in n for n in data["notes"]), data["notes"])
        self.assertIsNone(data["segment_end_snap_seconds"])
        self.assertEqual(len(frame_pts(out)), 180)
        for step in steps(out):  # Matroska stores whole milliseconds: 33 or 34
            self.assertAlmostEqual(step, 1 / FPS, delta=0.001)

    def test_an_open_gop_source_is_joined_by_one_reencode(self):
        """In an open GOP the frames just before a keyframe decode after it, so a part cut in
        decode order loses them (144 frames for 150). The join was 672 ms long and said mode
        copy; it is now re-cut from the source, with the right frames and no gaps."""
        out = DIR / "open_gop_join.mp4"
        data = cut_json(self.hevc25, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertTrue(data["reencoded"])
        self.assertIn("concat_fallback", data["reencode_reason"])
        self.assertTrue(any("open GOP" in n for n in data["notes"]), data["notes"])
        self.assertIsNone(data["segment_end_snap_seconds"])
        self.assertEqual(len(frame_pts(out)), 150)
        self.assertEqual(steps(out), {0.04})
        frames, src = gray_frames(out), gray_frames(self.hevc25)
        for got, want in ((0, 0), (49, 49), (50, 100), (99, 149), (100, 200), (149, 249)):
            self.assertFrameIs(frames[got], want, f"output frame {got}", src_frames=src)

    def test_an_exact_copy_join_keeps_every_beep_on_its_picture(self):
        """The old join put the beep 67 ms, then 133 ms, after its picture in the second and
        third segments. Each beep (at k + 0.5 s) now starts on the pts of output frame
        (k + 0.5) * 30."""
        out = DIR / "beep_join.mp4"
        data = cut_json(self.beep, "--segments", "0-2,4-6,8-10", "-o", out)
        self.assertEqual(data["mode"], "copy")
        log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-af", "silencedetect=n=-30dB:d=0.3",
                              "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stderr
        onsets = [float(v) for v in re.findall(r"silence_end: (-?[0-9.]+)", log)][:6]
        pts = sorted(frame_pts(out))
        self.assertEqual(len(onsets), 6, log)
        for onset, frame in zip(onsets, (15, 45, 75, 105, 135, 165)):
            self.assertAlmostEqual(onset, pts[frame], delta=0.005, msg=f"beep at frame {frame}")

    def test_an_end_within_tolerance_snaps_to_the_keyframe_after_it(self):
        """0-1.8 ends 0.2 s before the keyframe at 2.0: the part runs to that keyframe, so the
        join is 60 + 60 of the source's frames. start_snapped describes the starts only; the
        end's move is reported per segment."""
        out = DIR / "end_snap_join.mp4"
        data = cut_json(self.h264bf, "--segments", "0-1.8,4-6", "-o", out)
        self.assertEqual(data["mode"], "copy")
        self.assertFalse(data["start_snapped"])
        self.assertEqual(data["segment_end_snap_seconds"], [0.2, 0.0])
        src = md5_frames(self.h264bf)
        self.assertEqual(md5_frames(out), src[0:60] + src[120:180])

    def test_an_end_past_tolerance_reencodes_and_the_join_falls_back(self):
        """0-1.0 is 1.0 s from the next keyframe, past a 0.3 s tolerance: that part
        re-encodes, the parts differ, and the join is re-cut with exact boundaries."""
        out = DIR / "end_far_join.mp4"
        data = cut_json(self.h264bf, "--segments", "0-1.0,4-6", "--tolerance", "0.3", "-o", out)
        self.assertEqual(data["reencode_reason"], ["tolerance", "concat_fallback"])
        self.assertIsNone(data["segment_end_snap_seconds"])
        self.assertEqual(len(frame_pts(out)), 30 + 60)
        self.assertEqual(steps(out), {round(1 / FPS, 4)})
        frames, src = gray_frames(out), gray_frames(self.h264bf)
        for got, want in ((29, 29), (30, 120), (89, 179)):
            self.assertFrameIs(frames[got], want, f"output frame {got}", src_frames=src)

    def test_a_segment_in_the_last_gop_is_not_a_tolerance_reencode(self):
        """10-11 starts on the last keyframe (10.0) and ends before the video does: no
        keyframe follows it to snap the end to. That is not a tolerance miss (it was reported as
        one, even under --tolerance -1, "no keyframe within -1.00s"): the end stays where asked
        and the join check judges the copy. On B-frame video a part cut mid-GOP in decode order
        is not exact (main's copy showed 82 frames for 78), so the join is re-cut from source."""
        for extra in ((), ("--tolerance", "-1")):
            with self.subTest(tolerance=extra):
                out = DIR / f"last_gop_join{len(extra)}.mp4"
                data = cut_json(self.h264bf, "--segments", "0-2,10-11", *extra, "-o", out)
                self.assertEqual(data["reencode_reason"], ["concat_fallback"])
                self.assertEqual(len(frame_pts(out)), 60 + 30)
                self.assertEqual(steps(out), {round(1 / FPS, 4)})

    def test_a_short_segment_across_a_bframe_keyframe_never_cuts_a_negative_length(self):
        """-ss 1.95 lands on the keyframe at 2.0 (its dts, 1.933, is before 1.95). That
        keyframe cannot also end the part: its dts is before the start, so -t would be negative.
        The end is snapped among keyframes decoded after the landing, and none is near 2.1."""
        out = DIR / "short_across_key.mp4"
        data = cut_json(self.h264bf, "--segments", "1.95-2.1,4-6", "-o", out)
        self.assertEqual(data["reencode_reason"], ["tolerance", "concat_fallback"])
        self.assertEqual(stderr_of_decode(out), "")
        frames = gray_frames(out)
        self.assertEqual(len(frames), 4 + 60)
        self.assertFrameIs(frames[0], 59, "the first frame at or after 1.95", src_frames=gray_frames(self.h264bf))

    def test_an_hdr_open_gop_join_is_reencoded_as_hdr(self):
        """iPhone HEVC is open-GOP HLG. A detector that let it through would
        stream-copy it, so the re-encode is asserted first; then that it kept HEVC, 10 bits and
        the HLG transfer rather than flattening the picture."""
        out = DIR / "hlg_join.mp4"
        data = cut_json(self.hlg, "--segments", "0-2,4-6", "-o", out)
        self.assertTrue(data["reencoded"])
        self.assertIn("concat_fallback", data["reencode_reason"])
        stream = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                            "stream=codec_name,pix_fmt,color_transfer", "-of", "json", str(out)],
                                           stdout=subprocess.PIPE, text=True, check=True).stdout)["streams"][0]
        self.assertEqual((stream["codec_name"], stream["pix_fmt"], stream["color_transfer"]),
                         ("hevc", "yuv420p10le", "arib-std-b67"))

    def test_the_last_segment_past_the_video_end_stays_an_exact_copy(self):
        """On the copy path, the last part runs to the end of the file (-t e-s, nothing after it
        to leak), and the join is the source's own 60 + 60 frames."""
        out = DIR / "held_last_copy.mp4"
        data = cut_json(self.long, "--segments", "0-2,4-6.3", "-o", out)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        src = md5_frames(self.long)
        self.assertEqual(md5_frames(out), src[0:60] + src[120:180])
        self.assertAlmostEqual(probe(str(out))["video"]["duration"], 4.0, delta=0.001)
        self.assertEqual(data["segment_end_snap_seconds"], [0.0, None])

    def test_a_sound_tail_under_a_frame_stays_an_exact_copy(self):
        """On the copy path, the first part ends at the end of the file with its sound one AAC
        frame at most past its picture; the concat demuxer places the next part after the sound,
        so its last frame shows up to that long. The frames are exact and the check accepts it."""
        out = DIR / "tail_copy.mp4"
        data = cut_json(self.tail, "--segments", "4-6.02,0-2", "-o", out)
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        src = md5_frames(self.tail)
        self.assertEqual(md5_frames(out), src[120:180] + src[0:60])
        self.assertTrue(data["join_check"]["ok"])
        self.assertLess(data["join_check"]["max_step_seconds"], 1 / FPS + 1024 / 48000)

    def test_a_failed_concat_copy_is_reported_as_the_reencode_it_became(self):
        """2.x re-encoded the join when the concat demuxer's stream copy failed but still reported
        mode copy, reencoded false and packet precision. The failure is simulated (cut.py run
        with its concat-copy command failing): a keyframe-aligned video join and a WAV join, both
        of which copy when nothing fails."""
        mock_concat = (
            "import subprocess, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import cut\n"
            "real = cut.run\n"
            "def run(cmd, *a, **k):\n"
            "    cmd = [str(c) for c in cmd]\n"
            "    if '-f' in cmd and cmd[cmd.index('-f') + 1] == 'concat' and '-c' in cmd and cmd[cmd.index('-c') + 1] == 'copy':\n"
            "        return subprocess.CompletedProcess(cmd, 1, '', 'simulated concat failure')\n"
            "    return real(cmd, *a, **k)\n"
            "cut.run = run\n"
            "sys.argv = ['cut.py'] + sys.argv[2:]\n"
            "sys.exit(cut.main())\n")
        for src, segs, out, precision in ((self.h264bf, "0-2,4-6", DIR / "concat_failed.mp4", "frame"),
                                          (self.wav, "1-2,3-4.5", DIR / "concat_failed.wav", "sample")):
            with self.subTest(out=out.name):
                proc = sh(sys.executable, "-c", mock_concat, SCRIPTS, src, "--segments", segs, "-o", out,
                          "--overwrite", "--json")
                data = json.loads(proc.stdout)
                self.assertIn("concat with stream copy failed", proc.stderr, "the premise: the copy join failed")
                self.assertEqual((data["mode"], data["reencoded"]), ("hybrid", True))
                self.assertEqual(data["reencode_reason"], ["concat_fallback"])
                self.assertEqual(data["precision"], precision)
                self.assertFalse(data["keyframe_snapped"])
                self.assertFalse(data["start_snapped"])

    def test_a_wav_join_stays_a_lossless_copy(self):
        """PCM has no extradata at all; a "missing means incompatible" rule would have sent every
        multi-segment WAV cut to a re-encode."""
        out = DIR / "tone_join.wav"
        data = cut_json(self.wav, "--segments", "1-2,3-4.5", "-o", out)
        self.assertEqual(data["mode"], "copy")
        self.assertEqual(data["reencode_reason"], [])

    def test_the_audio_only_fallback_writes_one_pcm_stream_of_the_exact_length(self):
        out = DIR / "tone_recut.wav"
        if out.exists():
            out.unlink()  # called in-process, without the CLI's --overwrite
        with tempfile.TemporaryDirectory() as tmp:
            cut.join_from_source(str(self.wav), [(1.0, 2.0), (3.0, 4.5)], str(out), probe(str(self.wav)), 18, "medium", tmp)
        streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,duration_ts",
                                             "-of", "json", str(out)], stdout=subprocess.PIPE, text=True, check=True).stdout)["streams"]
        self.assertEqual([s["codec_type"] for s in streams], ["audio"])
        self.assertEqual(streams[0]["codec_name"], "pcm_s16le")
        self.assertEqual(int(streams[0]["duration_ts"]), 44100 + 66150)

    def test_a_segment_shorter_than_a_frame_is_refused(self):
        out = DIR / "subframe.mp4"
        proc = script("cut.py", self.hevc, "--segments", "1-1.01,3-4", "-o", out, expect_fail=True)
        self.assertIn("shorter than one frame", proc.stderr)
        self.assertFalse(out.exists())

    def test_a_gpu_chunk_refusal_reencodes_every_chunk_on_the_cpu(self):
        """Under --hw, run() retries a chunk VideoToolbox refused on the CPU; the chunks then differ,
        and the join encodes them all on the CPU rather than refusing (no real encode here)."""
        encodes, hw_seen = [], []

        def fake_chunk(src, segs, dst, meta, crf, preset, has_v, intermediate=False, **_hold):
            encodes.append(dst)
            hw_seen.append(cut.STATE.hw)

        # first round mixed (one chunk fell back to the CPU), second round all CPU
        sigs = iter([[{"type": "video", "codec_name": "hevc", "extradata_hash": "A"}],
                     [{"type": "video", "codec_name": "hevc", "extradata_hash": "B"}],
                     [{"type": "video", "codec_name": "hevc", "extradata_hash": "C"}],
                     [{"type": "video", "codec_name": "hevc", "extradata_hash": "C"}]])
        segs = [(i * 0.3, i * 0.3 + 0.2) for i in range(40)]
        meta = {"video": {"fps": 30.0}, "audio": None}
        with mock.patch.object(cut, "_join_chunk", fake_chunk), \
                mock.patch.object(cut, "join_signature", lambda p: next(sigs)), \
                mock.patch.object(cut, "run", lambda cmd, **kw: None), \
                mock.patch.object(cut.STATE, "hw", True), \
                mock.patch.object(cut.STATE, "hw_notes", []), \
                mock.patch.object(cut.STATE, "hw_source", "flag"), \
                mock.patch.object(cut.STATE, "commands", ["ffmpeg -i src.mp4 -c:v libx265 -crf 18 chunk.mkv"]), \
                tempfile.TemporaryDirectory() as tmp:
            cut.join_from_source("src.mp4", segs, os.path.join(tmp, "out.mp4"), meta, 18, "medium", tmp)
            self.assertEqual(hw_seen, [True, True, False, False], "two chunks on the GPU, then both again on the CPU")
            self.assertEqual(len(cut.STATE.hw_notes), 1)
            # the result still says the GPU was asked for and why it was not used
            rep = importlib.import_module("_common.emit")._encoder_report(cut.STATE)
            self.assertEqual((rep["hw"]["requested"], rep["hw"]["used"]), (True, False), rep)
            self.assertIn("fell back to the CPU", " ".join(rep["hw"]["notes"]))

    # ------------------------------------------------------------------ signatures (unit, prepared parts)
    def _part(self, name, *args):
        path = DIR / name
        if not path.exists():
            sh("ffmpeg", "-y", "-v", "error", *args, path)
        return str(path)

    def test_part_signatures_tell_joinable_parts_apart(self):
        copy_a = self._part("sig_copy_a.mp4", "-ss", "0", "-i", self.hevc, "-t", "1", "-c", "copy")
        copy_b = self._part("sig_copy_b.mp4", "-ss", "4", "-i", self.hevc, "-t", "1", "-c", "copy")
        h264 = self._part("sig_h264.mp4", "-ss", "4", "-i", self.hevc, "-t", "1", "-c:v", "libx264", "-c:a", "aac")
        hevc_re = self._part("sig_hevc_re.mp4", "-ss", "4", "-i", self.hevc, "-t", "1", "-c:v", "libx265",
                             "-x265-params", "log-level=error", "-tag:v", "hvc1", "-c:a", "aac")
        rot_copy = self._part("sig_rot_copy.mp4", "-ss", "0", "-i", self.rot, "-t", "1", "-c", "copy")
        rot_re = self._part("sig_rot_re.mp4", "-ss", "0", "-i", self.rot, "-t", "1", "-c:v", "libx265",
                            "-x265-params", "log-level=error", "-tag:v", "hvc1", "-c:a", "aac")
        wav_a = self._part("sig_a.wav", "-i", self.wav, "-t", "1", "-c", "copy")
        wav_b = self._part("sig_b.wav", "-ss", "2", "-i", self.wav, "-t", "1", "-c", "copy")
        sig = {p: cut.join_signature(p) for p in (copy_a, copy_b, h264, hevc_re, rot_copy, rot_re, wav_a, wav_b)}
        self.assertTrue(cut.signatures_match([sig[copy_a], sig[copy_b]], ".mp4"), "two copies of one source join")
        self.assertFalse(cut.signatures_match([sig[copy_a], sig[h264]], ".mp4"), "HEVC then H.264")
        # the premise of the same-codec case: the re-encode really carries different extradata
        self.assertNotEqual(sig[copy_a][0]["extradata_hash"], sig[hevc_re][0]["extradata_hash"])
        self.assertFalse(cut.signatures_match([sig[copy_a], sig[hevc_re]], ".mp4"), "a copy and a re-encode of one codec")
        self.assertFalse(cut.signatures_match([sig[rot_copy], sig[rot_re]], ".mp4"), "rotated copy vs rotated re-encode")
        self.assertIsNone(sig[wav_a][0]["extradata_hash"])
        self.assertTrue(cut.signatures_match([sig[wav_a], sig[wav_b]], ".wav"), "PCM parts join without extradata")
        self.assertIsNone(cut.join_signature(str(DIR / "no_such_part.mp4")))

    def test_a_missing_extradata_hash_only_matches_where_the_config_is_in_band(self):
        def sig(codec):
            return [{"type": "audio", "codec_name": codec, "profile": None, "sample_rate": "48000", "channels": 2,
                     "time_base": "1/48000", "extradata_hash": None}]
        self.assertFalse(cut.signatures_match([sig("aac"), sig("aac")], ".mp4"))
        self.assertTrue(cut.signatures_match([sig("aac"), sig("aac")], ".ts"))
        self.assertTrue(cut.signatures_match([sig("pcm_s16le"), sig("pcm_s16le")], ".wav"))
        self.assertTrue(cut.signatures_match([sig("mp3"), sig("mp3")], ".mp3"))
        one = sig("aac")
        other = sig("aac")
        other[0]["extradata_hash"] = "SHA256:ab"
        self.assertFalse(cut.signatures_match([one, other], ".ts"), "a hash on one side only is a mismatch")


class SourceCodecArgsTests(unittest.TestCase):
    """source_codec_video_args routes by the source (pure: no encode runs)."""
    SDR_HEVC = {"video": {"codec": "hevc", "bt2020_or_hdr": False}}
    HDR_HEVC = {"video": {"codec": "hevc", "bt2020_or_hdr": True, "color_space": "bt2020nc",
                          "color_primaries": "bt2020", "color_transfer": "smpte2084"}}
    SDR_H264 = {"video": {"codec": "h264", "bt2020_or_hdr": False}}

    def encoder(self, meta, codec=None, hw=False, swaps=None):
        """The encoder line, run through the real VideoToolbox routing with this machine's platform
        and encoder list mocked, so the test means the same on any host."""
        with mock.patch.object(decision.STATE, "codec", codec), mock.patch.object(decision.STATE, "hw", hw), \
                mock.patch.object(decision.STATE, "hw_swaps", [] if swaps is None else swaps), \
                mock.patch.object(decision.STATE, "hw_notes", []), \
                mock.patch.object(decision, "hw_platform_reason", lambda: None), \
                mock.patch.object(decision, "ffmpeg_encoders", lambda: {"libx264", "libx265", "hevc_videotoolbox", "h264_videotoolbox"}):
            args = decision.source_codec_video_args(meta, 18, "ultrafast")
        return args[args.index("-c:v") + 1], args

    def test_sdr_hevc_is_encoded_as_hevc_8bit_bt709(self):
        enc, args = self.encoder(self.SDR_HEVC)
        self.assertEqual(enc, "libx265")
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(args[args.index("-tag:v") + 1], "hvc1")

    def test_sdr_hevc_goes_to_videotoolbox_with_a_cpu_fallback_when_hw_is_on(self):
        swaps = []
        enc, args = self.encoder(self.SDR_HEVC, hw=True, swaps=swaps)
        self.assertEqual(enc, "hevc_videotoolbox")
        self.assertEqual(args[args.index("-bsf:v") + 1],
                         "hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1")
        self.assertEqual(len(swaps), 1, "run() can put the CPU line back if the GPU refuses")
        gpu, cpu = swaps[0]
        self.assertEqual(gpu, args)
        self.assertEqual(cpu[cpu.index("-c:v") + 1], "libx265")

    def test_a_codec_flag_wins_over_the_source(self):
        enc, _ = self.encoder(self.SDR_HEVC, codec="h264")
        self.assertEqual(enc, "libx264")

    def test_sdr_h264_is_still_encoded_as_h264(self):
        enc, args = self.encoder(self.SDR_H264)
        self.assertEqual(enc, "libx264")
        self.assertNotIn("-tag:v", args)

    def test_hdr_hevc_stays_main10_with_its_own_tags(self):
        enc, args = self.encoder(self.HDR_HEVC)
        self.assertEqual(enc, "libx265")
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p10le")
        self.assertEqual(args[args.index("-color_trc") + 1], "smpte2084")
        self.assertIn("hdr10-opt=1", args[args.index("-x265-params") + 1])


def ramp(n, step, start=0):
    return [start + i * step for i in range(n)]


class FrameTimingTests(unittest.TestCase):
    """classify_frame_timing on fixed timestamps: no encodes, the rules one at a time."""

    def classify(self, windows, tb="1/30"):
        return probe_mod.classify_frame_timing(windows, tb)["measured"]

    def test_exact_thirtieths_are_constant(self):
        self.assertEqual(self.classify([ramp(60, 1), ramp(60, 1, 300)]), "sampled_cfr")

    def test_ntsc_rounding_to_a_600_timescale_is_constant(self):
        """29.97 fps in 1/600 ticks is 20.02 ticks a frame: mostly 20-tick intervals with a 21
        about every 50 frames. That rounding is not variable timing."""
        pts = [round(n * 600 * 1001 / 30000) for n in range(180)]
        deltas = [b - a for a, b in zip(pts, pts[1:])]
        self.assertEqual(set(deltas), {20, 21})
        self.assertEqual(deltas.count(21), 4)
        self.assertEqual(self.classify([pts[:90], pts[90:]], "1/600"), "sampled_cfr")

    def test_a_stretched_first_interval_at_the_file_start_is_not_evidence(self):
        first = [0] + ramp(59, 1, 3)       # the first frame held for three frame times
        self.assertEqual(self.classify([first, ramp(60, 1, 300)]), "sampled_cfr")

    def test_the_same_interval_second_in_the_file_is_vfr(self):
        second = [0, 1] + ramp(58, 1, 4)
        self.assertEqual(self.classify([second, ramp(60, 1, 300)]), "vfr")

    def test_a_stretched_first_interval_in_a_later_window_is_vfr(self):
        later = [300] + ramp(59, 1, 303)
        self.assertEqual(self.classify([ramp(60, 1), later]), "vfr")

    def test_one_dropped_frame_in_one_window_is_vfr(self):
        dropped = ramp(30, 1, 300) + ramp(30, 1, 331)
        self.assertEqual(self.classify([ramp(60, 1), dropped]), "vfr")

    def test_one_dropped_frame_at_a_fine_time_base_is_vfr(self):
        dropped = ramp(30, 512, 153600) + ramp(30, 512, 153600 + 31 * 512)    # 1/15360, as MP4 writes 30 fps
        self.assertEqual(self.classify([ramp(60, 512), dropped], "1/15360"), "vfr")

    def test_jitter_is_vfr(self):
        jitter = [n * 33 + (0 if n % 2 else 7) for n in range(60)]   # 1/1000 s ticks: 26 and 40 ms
        self.assertEqual(self.classify([jitter], "1/1000"), "vfr")

    def test_windows_at_different_rates_are_vfr(self):
        self.assertEqual(self.classify([ramp(60, 2), ramp(60, 1, 300)], "1/60"), "vfr")

    def test_variable_timing_between_the_windows_is_not_seen(self):
        """The documented limit: the clean windows are all the classifier gets."""
        self.assertEqual(self.classify([ramp(60, 1), ramp(60, 1, 900)]), "sampled_cfr")

    def test_bframe_decode_order_classifies_like_presentation_order(self):
        shown = ramp(60, 1)
        stored = [shown[0]] + [shown[i + d] for i in range(1, 57, 3) for d in (2, 0, 1)] + shown[58:]
        self.assertEqual(sorted(stored), shown, "the premise: the same frames, out of order")
        self.assertEqual(self.classify([stored, ramp(60, 1, 300)]), self.classify([shown, ramp(60, 1, 300)]))
        self.assertEqual(self.classify([stored, ramp(60, 1, 300)]), "sampled_cfr")

    def test_fewer_than_twenty_intervals_is_inconclusive(self):
        result = probe_mod.classify_frame_timing([ramp(20, 1)], "1/30")
        self.assertEqual((result["measured"], result["deltas"]), ("inconclusive", 18))

    def test_missing_and_repeated_timestamps_are_skipped(self):
        pts = ramp(60, 1)
        pts[10:10] = [None, float("nan"), 10]
        self.assertEqual(self.classify([pts, ramp(60, 1, 300)]), "sampled_cfr")

    def test_a_read_that_stops_mid_reorder_keeps_only_complete_frames(self):
        """Decode order I0 P3 B1 B2 P6 (stop): frames 4 and 5 were never read. Only the pts up to
        the last dts read are all present."""
        packets = [{"pts": 0, "dts": -2}, {"pts": 3, "dts": -1}, {"pts": 1, "dts": 0}, {"pts": 2, "dts": 1},
                   {"pts": 6, "dts": 2}]
        self.assertEqual(sorted(probe_mod.complete_pts(packets)), [0, 1, 2])

    def test_windows_are_spread_over_the_file_from_its_first_packet(self):
        self.assertEqual(probe_mod.timing_window_starts(60.0, 0.0), [0.0, 13.5, 27.0, 40.5, 54.0])
        self.assertEqual(probe_mod.timing_window_starts(60.0, 10.0), [10.0, 23.5, 37.0, 50.5, 64.0])
        self.assertEqual(probe_mod.timing_window_starts(13.0, 0.0), [0.0, 7.0])
        self.assertEqual(probe_mod.timing_window_starts(4.0, 0.0), [0.0])

    def test_a_window_that_seeks_back_reads_only_from_its_start(self):
        """A long GOP: every read seeks back to the keyframe at 0, whose first interval is stretched
        (an edit-list start). Only the file-start window may ignore that interval, so the later
        windows must drop what precedes their own start."""
        pts = [0] + ramp(599, 1, 3)                        # 1/30 ticks: 20 s, the first frame held 3x
        doc = json.dumps({"packets": [{"pts": p, "dts": p} for p in pts], "streams": [{"time_base": "1/30"}]})
        ran = subprocess.CompletedProcess([], 0, doc, "")
        with mock.patch.object(probe_mod, "run", lambda cmd, **kw: ran):
            result = probe_mod.measure_frame_timing("x.mp4", 20.0, 0.0)
        self.assertEqual((result["measured"], result["windows"]), ("sampled_cfr", 3))

    def test_an_ffprobe_failure_is_inconclusive(self):
        failed = subprocess.CompletedProcess([], 1, "", "boom")
        with mock.patch.object(probe_mod, "run", lambda cmd, **kw: failed):
            self.assertEqual(probe_mod.measure_frame_timing("x.mp4", 30.0, 0.0)["measured"], "inconclusive")


def gop_packets(fps=30, keyint=60, gops=6, delay=2, leading=0):
    """Synthetic packets in decode order, as (pts, dts, key): each GOP's keyframe first, then its
    other frames by pts; dts runs `delay` frames behind. `leading` frames before each keyframe
    after the first decode after it (an open GOP's leading pictures)."""
    order = []
    for g in range(gops):
        k = g * keyint
        order.append((k, True))
        if g and leading:
            order += [(k - leading + j, False) for j in range(leading)]
        last = k + keyint - (leading if g < gops - 1 else 0)
        order += [(n, False) for n in range(k + 1, last)]
    return [(n / fps, (i - delay) / fps, key) for i, (n, key) in enumerate(order)]


class CopyJoinPlanTests(unittest.TestCase):
    """The copy-join helpers on synthetic packet lists: where a copied part ends, open-GOP detection,
    and the check of the joined file."""

    def test_a_closed_gop_keyframe_is_not_open(self):
        packets = gop_packets()
        self.assertFalse(cut.gop_is_open(packets, 60))
        self.assertFalse(cut.gop_is_open(packets, 0))

    def test_leading_pictures_after_a_keyframe_make_it_open(self):
        packets = gop_packets(leading=3)
        i = next(i for i, p in enumerate(packets) if p[2] and abs(p[0] - 2.0) < 1e-9)
        self.assertTrue(cut.gop_is_open(packets, i))
        self.assertFalse(cut.gop_is_open(packets, 0), "the first keyframe has nothing before it")

    def test_a_keyframe_at_the_end_of_the_file_is_not_open(self):
        packets = gop_packets()[:61]
        self.assertTrue(packets[60][2])
        self.assertFalse(cut.gop_is_open(packets, 60))

    def test_a_missing_timestamp_in_the_gop_counts_as_open(self):
        packets = gop_packets()
        packets[62] = (None, packets[62][1], False)
        self.assertTrue(cut.gop_is_open(packets, 60))
        packets = gop_packets()
        packets[62] = (packets[62][0], None, False)
        self.assertTrue(cut.gop_is_open(packets, 60))

    def test_the_part_ends_at_the_end_keyframes_dts(self):
        packets = gop_packets()
        plan = cut.plan_part(packets, 0.0, 1.8, 0.5, 12.0, 30)
        self.assertIsNone(plan["reason"])
        self.assertEqual((plan["start_pts"], plan["end_pts"]), (0.0, 2.0))
        self.assertAlmostEqual(plan["t"], 2.0 - 2 / 30, delta=0.001)
        self.assertLess(plan["t"], 2.0 - 2 / 30, "the keyframe's own packet stays out of the part")

    def test_an_end_keyframe_decoded_before_the_start_is_not_a_candidate(self):
        """-ss 1.95 lands on the keyframe at 2.0 (dts 1.933): that keyframe would give -t < 0, and
        the next one (4.0) is 1.9 s from the end, past tolerance."""
        packets = gop_packets()
        plan = cut.plan_part(packets, 1.95, 2.1, 0.5, 12.0, 30)
        self.assertEqual(plan["start_pts"], 2.0)
        self.assertEqual(plan["reason"], "tolerance")
        plan = cut.plan_part(packets, 1.95, 3.9, 0.5, 12.0, 30)
        self.assertEqual(plan["end_pts"], 4.0)
        self.assertGreater(plan["t"], 0)
        # 2.0 is nearer 2.3, but the copy starts from it: the end is the keyframe after
        plan = cut.plan_part(packets, 1.95, 2.3, 1.8, 12.0, 30)
        self.assertEqual((plan["reason"], plan["end_pts"]), (None, 4.0))

    def test_a_start_just_before_the_end_keyframes_dts_is_not_cut(self):
        """Keyframes 5 ms apart: a start 0.05 ms before the next keyframe's dts lands on the one
        before, and -t to that dts would round to nothing."""
        packets = [(0.0, 0.0, True), (0.005, 0.005, True), (0.010, 0.010, False)]
        plan = cut.plan_part(packets, 0.00495, 0.005, -1, 1.0, 200)
        self.assertEqual(plan["reason"], "tolerance")

    def test_each_end_is_judged_on_its_own(self):
        """A start 0.4 s early and an end 0.4 s early used to cancel out in the part's length."""
        packets = gop_packets()
        self.assertEqual(cut.plan_part(packets, 2.4, 5.9, 0.3, 12.0, 30)["reason"], "tolerance")
        self.assertEqual(cut.plan_part(packets, 2.0, 5.6, 0.3, 12.0, 30)["reason"], "tolerance")
        self.assertIsNone(cut.plan_part(packets, 2.0, 5.8, 0.3, 12.0, 30)["reason"])

    def test_a_part_that_ends_with_the_video_is_cut_to_its_length(self):
        packets = gop_packets()
        plan = cut.plan_part(packets, 10.0, 12.0, 0.5, 12.0, 30)
        self.assertIsNone(plan["reason"])
        self.assertIsNone(plan["end_pts"])
        self.assertEqual(plan["t"], 2.0)

    def test_the_expected_packets_are_the_sources_in_each_range(self):
        packets = gop_packets()
        self.assertEqual(cut.expected_packets(packets, [(0.0, 2.0), (4.0, 6.0), (10.0, None)]), 60 + 60 + 60)

    def test_an_exact_join_passes_the_check(self):
        pts = [n / 30 for n in range(180)]
        check = cut.check_join(pts, 180, 30, 1024 / 48000, True)
        self.assertTrue(check["ok"])
        self.assertAlmostEqual(check["max_step_seconds"], 1 / 30, places=6)

    def test_bframe_packet_order_sorts_to_an_exact_join(self):
        # I P B B, as decoded: every P before the two B-frames it references
        pts = [n / 30 for i in range(0, 180, 3) for n in (i + 2, i, i + 1)]
        self.assertNotEqual(pts, sorted(pts))
        self.assertTrue(cut.check_join(pts, 180, 30, 0.0, True)["ok"])

    def test_one_extra_packet_fails_the_check(self):
        pts = [n / 30 for n in range(180)] + [2.0]
        check = cut.check_join(pts, 180, 30, 0.0, True)
        self.assertFalse(check["ok"])
        self.assertEqual((check["packets"], check["expected_packets"]), (181, 180))

    def test_one_missing_frame_fails_the_check(self):
        pts = [n / 30 for n in range(180) if n != 90]
        self.assertFalse(cut.check_join(pts, 180, 30, 0.0, True)["ok"])

    def test_a_hole_up_to_one_audio_frame_passes_and_more_fails(self):
        """With no B-frames a part's sound runs up to one AAC frame past its picture, and the next
        part is placed after it: the frames are all there, one of them shown longer."""
        audio = 1024 / 48000
        within = [n / 30 + (0.02 if n >= 60 else 0) for n in range(120)]
        self.assertTrue(cut.check_join(within, 120, 30, audio, True)["ok"])
        beyond = [n / 30 + (0.03 if n >= 60 else 0) for n in range(120)]
        check = cut.check_join(beyond, 120, 30, audio, True)
        self.assertFalse(check["ok"])
        self.assertAlmostEqual(check["max_step_seconds"], 1 / 30 + 0.03, places=6)
        self.assertFalse(cut.check_join(within, 120, 30, 0.0, True)["ok"], "no audio: half a frame is the bound")

    def test_a_checked_join_is_placed_under_the_outputs_lock(self):
        """The checked join is written beside the parts and placed afterwards; placing it must
        respect another run's lock on the output, as an ffmpeg write does."""
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "joined.mp4"), os.path.join(tmp, "out.mp4")
            Path(src).write_bytes(b"new")
            Path(dst).write_bytes(b"theirs")
            Path(tmp, ".out.mp4.ffskill-lock").write_text(str(os.getpid()))
            with mock.patch.object(cut.STATE, "overwrite", True), self.assertRaises(SystemExit):
                cut.place_output(src, dst)
            self.assertEqual(Path(dst).read_bytes(), b"theirs")

    def test_the_audio_frame_is_the_most_common_packet_not_the_longest(self):
        """One long packet (a codec with variable frames) must not widen every join's bound."""
        self.assertAlmostEqual(cut.typical_duration([0.021333] * 10 + [0.5, 0.005333]), 0.021333, places=6)
        self.assertEqual(cut.typical_duration([None, 0.0]), 0.0)

    def test_without_constant_timing_only_the_count_is_checked(self):
        pts = [n / 30 + (0.5 if n >= 60 else 0) for n in range(120)]
        check = cut.check_join(pts, 120, 30, 0.0, False)
        self.assertTrue(check["ok"])
        self.assertIsNone(check["max_step_seconds"])


class VfrGuardTests(unittest.TestCase):
    """cut.py's VFR guard on real files: measured timing, the reasons, and --vfr-copy."""

    @classmethod
    def setUpClass(cls):
        DIR.mkdir(parents=True, exist_ok=True)
        cls.fp = DIR / "vfr_false_positive.mp4"
        if not cls.fp.exists():
            # every frame 1/30 s apart, but the last one held 8x: the average rate drops to 29.3
            # against a nominal 30, the shape that tripped the old whole-file check
            base = DIR / "vfr_fp_base.mp4"
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=10", "-f", "lavfi", "-i", "sine=d=10",
               "-c:v", "libx264", "-bf", "0", "-g", "30", "-video_track_timescale", "600", "-c:a", "aac", base)
            sh("ffmpeg", "-y", "-v", "error", "-i", base, "-c", "copy", "-bsf:v",
               "setts=duration=if(eq(N\\,299)\\,DURATION*8\\,DURATION)", "-video_track_timescale", "600", cls.fp)
        cls.drop = DIR / "vfr_dropped.mp4"
        if not cls.drop.exists():
            # one frame in every ten dropped, the gaps kept: genuinely variable timing
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=10", "-f", "lavfi", "-i", "sine=d=10",
               "-vf", "select='not(eq(mod(n\\,10)\\,5))'", "-fps_mode", "vfr", "-c:v", "libx264", "-bf", "0", "-g", "30",
               "-c:a", "aac", cls.drop)
        cls.short = DIR / "vfr_short.mp4"
        if not cls.short.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=0.5", "-c:v", "libx264", "-bf", "0", cls.short)
        cls.late_drops = DIR / "vfr_late_drops.mp4"
        if not cls.late_drops.exists():
            # one keyframe for 20 s, frames dropped only after 14 s: every window seeks back to 0
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=20",
               "-vf", "select='not(gt(t\\,14)*eq(mod(n\\,10)\\,5))'", "-fps_mode", "vfr",
               "-c:v", "libx264", "-bf", "0", "-g", "1000", "-x264-params", "scenecut=0", cls.late_drops)
        cls.tone = DIR / "vfr_tone.wav"
        if not cls.tone.exists():
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=4", cls.tone)

    def test_an_average_rate_below_nominal_is_not_vfr(self):
        self.assertTrue(probe(str(self.fp))["video"]["variable_frame_rate_suspected"], "the premise: the old check trips")
        data = cut_json(self.fp, "--start", "0", "--duration", "2", "-o", DIR / "vfr_fp_cut.mp4")
        self.assertEqual(data["vfr_check"]["measured"], "sampled_cfr")
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))

    def test_dropped_frames_force_a_reencode(self):
        data = cut_json(self.drop, "--start", "0", "--duration", "2", "-o", DIR / "vfr_drop_cut.mp4")
        self.assertEqual(data["vfr_check"]["measured"], "vfr")
        self.assertEqual(data["reencode_reason"], ["vfr"])
        self.assertTrue(data["reencoded"])
        self.assertEqual(data["precision"], "frame")

    def test_dropped_frames_late_in_a_long_gop_are_seen(self):
        """Each window reads from its own start, not from the keyframe the read seeks back to."""
        data = cut_json(self.late_drops, "--start", "0", "--duration", "2", "--dry-run", "-o", DIR / "never_late.mp4")
        self.assertEqual(data["vfr_check"]["windows"], 3)
        self.assertEqual(data["vfr_check"]["measured"], "vfr")

    def test_vfr_copy_keeps_the_copy_and_says_so(self):
        data = cut_json(self.drop, "--start", "0", "--duration", "2", "--vfr-copy", "--tolerance", "-1",
                        "-o", DIR / "vfr_drop_copy.mp4")
        self.assertEqual(data["vfr_check"]["measured"], "vfr")
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        self.assertTrue(any("--vfr-copy" in n for n in data["notes"]), data["notes"])

    def test_a_vfr_copy_join_is_checked_by_its_packet_count_only(self):
        """Variable timing has no step to hold a join to, so --vfr-copy keeps the copy and the
        join check counts packets only."""
        data = cut_json(self.drop, "--segments", "0-2,4-6", "--vfr-copy", "--tolerance", "-1",
                        "-o", DIR / "vfr_drop_join.mp4")
        self.assertEqual((data["mode"], data["reencode_reason"]), ("copy", []))
        self.assertIsNone(data["join_check"]["max_step_seconds"])
        self.assertTrue(data["join_check"]["ok"])
        self.assertEqual(data["join_check"]["packets"], data["join_check"]["expected_packets"])

    def test_too_few_frames_to_measure_reencodes(self):
        data = cut_json(self.short, "--start", "0", "--duration", "0.3", "-o", DIR / "vfr_short_cut.mp4")
        self.assertEqual(data["vfr_check"]["measured"], "inconclusive")
        self.assertEqual(data["reencode_reason"], ["vfr_inconclusive"])
        self.assertEqual(data["precision"], "frame")

    def test_a_dry_run_measures_and_reports(self):
        data = cut_json(self.drop, "--start", "0", "--duration", "2", "--dry-run", "-o", DIR / "never_vfr.mp4")
        self.assertEqual(data["vfr_check"]["measured"], "vfr")
        self.assertEqual(data["reencode_reason"], ["vfr"])

    def test_nothing_is_measured_when_nothing_would_copy(self):
        audio = cut_json(self.tone, "--start", "1", "--duration", "1", "-o", DIR / "vfr_tone_cut.wav")
        self.assertNotIn("vfr_check", audio)
        accurate = cut_json(self.drop, "--start", "0", "--duration", "1", "--accurate", "-o", DIR / "vfr_drop_acc.mp4")
        self.assertNotIn("vfr_check", accurate)
        self.assertEqual(accurate["reencode_reason"], ["requested"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
