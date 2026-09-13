#!/usr/bin/env python3
"""End-to-end tests for audio, loudness and waveform.

    python3 tests/test_audio.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import json
import sys
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, script, sh  # noqa: E402
from _common import probe  # noqa: E402


class AudioTests(MediaFixtures):
    """Audio, loudness and waveform."""

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

    # ---------------------------------------------------------------- loudness
    def test_loudness_two_pass(self):
        out = OUT / "loud.mp4"
        script("loudness.py", self.src, "-I", "-16", "--tp", "-1.5", "-o", out)
        stats = json.loads(script("loudness.py", out, "--measure-only", "-I", "-16", "--tp", "-1.5").stdout)
        self.assertClose(float(stats["input_i"]), -16.0, 1.0, "integrated loudness")
        self.assertLessEqual(float(stats["input_tp"]), -1.0, "true peak ceiling")
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")

    def test_audio_music_bed_never_shortens_the_video(self):
        """#164: a looped music bed under --duck came out 11.925 s from a 12.00 s source, and
        -shortest then cut the stream-copied *video* to match: four frames gone from a tool whose
        contract says the picture is never touched. The audio is now padded/trimmed to the source
        duration and a video-keeping output never uses -shortest. Every music mode, plus --replace
        with a shorter track, must keep the source's duration and frame count exactly."""
        src_dur = probe(str(self.src))["duration"]
        src_frames = self._frame_count(self.src)
        for tag, flags in (("loop_duck", ["--music", str(self.mic), "--duck", "--music-loop"]),
                           ("loop", ["--music", str(self.mic), "--music-loop"]),
                           ("plain", ["--music", str(self.mic)]),
                           ("replace_short", ["--replace", str(OUT / "c_mic_short.wav")])):
            if tag == "replace_short":
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.mic), "-t", "3", str(OUT / "c_mic_short.wav"))
            out = OUT / f"music_len_{tag}.mp4"
            script("audio.py", self.src, *flags, "-o", out)
            m = probe(str(out))
            self.assertAlmostEqual(m["duration"], src_dur, msg=tag, delta=0.02)
            self.assertEqual(self._frame_count(out), src_frames, f"{tag}: the picture lost or gained frames")
            self.assertAlmostEqual(m["audio"].get("duration") or m["duration"], src_dur, msg=tag, delta=0.05)

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

    def test_audio_voice_levels_are_three_different_chains(self):
        """1.13: --voice takes a strength. A bare --voice must stay byte-identical to the chain
        it produced before the flag took a value (every existing call and MCP request sends it
        bare), and each named level must actually be a different chain -- a preset that is only
        a different word in the help is worse than no preset."""
        out = OUT / "voice_level.mp4"
        bare, _ = self._audio_filters(self.src, "--voice", "-o", out)
        self.assertEqual(bare, "[0:a:0]highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,"
                               "acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2[main];"
                               "[main]apad,atrim=0:12.000[out]",
                         "a bare --voice is the 1.12 chain, unchanged")
        chains = {}
        for level in ("light", "medium", "strong"):
            chains[level], data = self._audio_filters(self.src, "--voice", level, "-o", out)
            self.assertEqual(data["audio"]["voice"], level)
        self.assertEqual(chains["medium"], bare, "bare --voice == --voice medium")
        self.assertEqual(len(set(chains.values())), 3, "each level is a different filter chain")
        self.assertNotIn("deesser", chains["light"])
        self.assertNotIn("afftdn", chains["light"], "light leaves the noise floor alone")
        self.assertIn("acompressor=threshold=-18dB:ratio=2", chains["light"])
        self.assertIn("deesser=i=0.6", chains["strong"])
        self.assertIn("alimiter=limit=0.891251:level=disabled", chains["strong"], "strong ends in a soft limiter")
        self.assertTrue(chains["strong"].count("acompressor") == 2, "strong compresses twice")
        # and each one really encodes
        for level in ("light", "strong"):
            real = OUT / f"voice_{level}.m4a"
            script("audio.py", self.mic, "--voice", level, "-o", real)
            self.assertGreater(probe(str(real))["duration"], 1.0)

    def test_audio_duck_parameters_reach_the_sidechain_filter(self):
        """1.13: the ducking knobs are sayable. The default command line must not move (the
        threshold flag speaks dBFS, the filter takes the same 0.05 linear it always did), and
        every flag must land in the filter string and in --json's audio block."""
        out = OUT / "duck_params.mp4"
        default, data = self._audio_filters(self.src, "--music", self.long_ref, "--duck", "-o", out)
        self.assertIn("sidechaincompress=threshold=0.05:ratio=4.0:attack=20:release=400:makeup=1", default,
                      "the default duck filter is unchanged")
        self.assertEqual(data["audio"]["duck"]["threshold_linear"], 0.05)
        tuned, data = self._audio_filters(self.src, "--music", self.long_ref, "--duck", "--duck-amount", "18",
                                          "--duck-threshold", "-30", "--duck-attack", "5", "--duck-release", "250", "-o", out)
        self.assertIn("sidechaincompress=threshold=0.0316228:ratio=6.0:attack=5:release=250:makeup=1", tuned)
        self.assertEqual(data["audio"]["duck"], {"amount_db": 18.0, "threshold_db": -30.0, "threshold_linear": 0.0316228,
                                                 "ratio": 6.0, "attack_ms": 5.0, "release_ms": 250.0})
        # no --duck: the block says so rather than describing settings nothing used
        _, data = self._audio_filters(self.src, "--music", self.long_ref, "-o", out)
        self.assertIsNone(data["audio"]["duck"])
        # out of range is refused before ffmpeg sees it
        doc = json.loads(script("audio.py", self.src, "--music", self.long_ref, "--duck", "--duck-release", "99999",
                                "-o", out, "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--duck-release", doc["error"]["message"])

    def test_audio_stereo_widen_needs_a_real_stereo_source(self):
        """1.13: widening scales the side signal (L-R). Duplicating a mono track to two channels
        leaves L == R, so the side signal is exactly zero and scaling it changes nothing -- the
        file comes out bit-identical and still mono. Mono is refused outright, --stereo included,
        rather than pointed at a workaround that cannot work."""
        mono = OUT / "widen_mono.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.mic), "-ac", "1", str(mono))
        out = OUT / "widened.wav"
        for extra in ([], ["--stereo"]):
            doc = json.loads(script("audio.py", mono, "--stereo-widen", "0.5", *extra, "-o", out,
                                    "--json", expect_fail=True).stdout)
            self.assertEqual(doc["error"]["kind"], "input", extra)
            self.assertIn("real stereo source", doc["error"]["message"], extra)
        # a real stereo source -- different content per channel -- is widened, and the widening
        # is audible in the only place it can be: the side signal
        stereo = OUT / "widen_stereo.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "aevalsrc='0.15*sin(2*PI*300*t)|0.1*sin(2*PI*900*t)':s=48000:c=stereo", "-t", "4", str(stereo))
        before = self._side_peak_db(stereo)
        graph, data = self._audio_filters(stereo, "--stereo-widen", "1", "-o", out)
        self.assertIn("extrastereo=m=3", graph)
        self.assertEqual(data["audio"]["stereo_widen"], 1.0)
        script("audio.py", stereo, "--stereo-widen", "1", "-o", out)
        after = self._side_peak_db(out)
        self.assertEqual(probe(str(out))["audio"]["channels"], 2)
        self.assertGreater(after, -60.0, "L-R must not be silent after widening: that is the whole effect")
        self.assertGreater(after, before + 3.0, "the side signal is louder than it was")
        doc = json.loads(script("audio.py", stereo, "--stereo-widen", "4", "-o", out, "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")

    def test_audio_stereo_widen_refuses_more_than_two_channels_without_downmix(self):
        """1.13: extrastereo is a stereo-only filter, so libavfilter would auto-insert a downmix
        and throw four channels of a 5.1 master away with no flag and no warning. Losing channels
        is the caller's decision (--downmix), and with it the widening runs on the fold-down."""
        out = OUT / "widen_surround.m4a"
        doc = json.loads(script("audio.py", self.surround, "--stereo-widen", "0.5", "-o", out,
                                "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--downmix", doc["error"]["message"])
        self.assertIn("6 channels", doc["error"]["message"])
        graph, _ = self._audio_filters(self.surround, "--stereo-widen", "0.5", "--downmix", "-o", out)
        self.assertLess(graph.index("pan=stereo"), graph.index("extrastereo="), "widen runs after the downmix")
        data = json.loads(script("audio.py", self.surround, "--stereo-widen", "0.5", "--downmix",
                                 "-o", out, "--json").stdout)
        self.assertEqual(data["probe"]["audio"]["channels"], 2)
        self.assertEqual(data["probe"]["audio"]["channel_layout"], "stereo")

    def test_audio_duck_parameters_need_their_switch_and_a_bed(self):
        """1.13: --duck-release 250 that silently delivers the default 400 ms is invisible to the
        caller, and --duck with no --music has nothing to duck. Both are refusals naming the
        missing flag, the same rule the typed dynamics parameters already follow."""
        out = OUT / "duck_guard.mp4"
        for flag, value in (("--duck-threshold", "-40"), ("--duck-attack", "5"), ("--duck-release", "250"), ("--duck-amount", "18")):
            doc = json.loads(script("audio.py", self.src, "--music", self.long_ref, flag, value, "-o", out,
                                    "--json", expect_fail=True).stdout)
            self.assertEqual(doc["error"]["kind"], "input", flag)
            self.assertIn(flag, doc["error"]["message"])
            self.assertIn("--duck", doc["error"]["message"])
        doc = json.loads(script("audio.py", self.src, "--duck", "--duck-release", "250", "-o", out,
                                "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--music", doc["error"]["message"])
        # the combination that means something still runs
        graph, _ = self._audio_filters(self.src, "--music", self.long_ref, "--duck", "--duck-release", "250", "-o", out)
        self.assertIn("release=250", graph)

    def test_audio_effects_bed_is_mixed_and_never_ducked(self):
        """1.13: --effects is a third bed at its own level. It is mixed after the ducked music,
        outside the sidechain, because effects are cut to the picture."""
        out = OUT / "effects.mp4"
        graph, data = self._audio_filters(self.src, "--music", self.long_ref, "--duck",
                                          "--effects", self.mic, "--effects-volume", "-20", "-o", out)
        self.assertIn("volume=-20dB", graph)
        self.assertIn("[effects]", graph)
        self.assertGreater(graph.index("[effects]"), graph.index("sidechaincompress"),
                           "the effects bed is mixed after the duck, so the sidechain never sees it")
        self.assertTrue(data["audio"]["effects"])
        script("audio.py", self.src, "--effects", self.mic, "--effects-volume", "-20", "-o", out)
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)

    def test_loudness_json_reports_the_measurement_and_the_targets(self):
        """1.13: --json carries the input's own loudnorm measurement (including its loudness
        range) and the targets that were asked for, next to the result measured off the written
        file -- so a caller can see what it started from without a second --measure-only run.

        There is deliberately no speech gate here: loudnorm's EBU R128 integrated measurement
        already applies the -70 LUFS absolute and -10 LU relative gates, so gating on
        silencedetect spans moves the result by a fraction of check.py's own tolerance (see
        references/gotchas.md#loudness-and-ambience)."""
        out = OUT / "loud_targets.m4a"
        data = json.loads(script("loudness.py", self.mic, "-I", "-16", "--tp", "-1.5", "--lra", "9",
                                 "-o", out, "--json").stdout)
        self.assertEqual(data["targets"], {"lufs": -16.0, "tp": -1.5, "lra": 9.0})
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            self.assertIn(key, data["measured"], key)
            self.assertIn(key, data["result"], key)
        measured_only = json.loads(script("loudness.py", self.mic, "--measure-only", "--json").stdout)["measured"]
        self.assertEqual(data["measured"]["input_i"], measured_only["input_i"],
                         "the reported measurement is the same pass-1 measurement --measure-only prints")
        self.assertClose(float(data["result"]["input_i"]), -16.0, 1.0)
        self.assertNotIn("dialogue", script("loudness.py", "--help").stdout,
                         "the speech gate was withdrawn; the flag must not come back without the evidence")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
