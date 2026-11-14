#!/usr/bin/env python3
"""End-to-end tests for audio, loudness and waveform.

    python3 tests/test_audio.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import (MULTI_PROBED, MediaFixtures, OUT, SCRIPTS, _is_faststart, integrated_lufs,  # noqa: E402
                       make_multistream, script, sh, written_track)
from _common import probe  # noqa: E402


class AudioTests(MediaFixtures):
    """Audio, loudness and waveform."""

    # ---------------------------------------------------------------- waveform
    def test_voice_with_denoise_denoises_at_the_strength_asked(self):
        """Audit A136: --voice light --denoise dropped the denoise, and --denoise-strength was not
        read under any --voice (medium and strong kept their own nf=-25)."""
        def chain(*flags):
            doc = json.loads(script("audio.py", self.src, *flags, "-o", OUT / "voice_denoise.mp4", "--dry-run",
                                    "--json").stdout)
            last = doc["commands"][-1]
            return last if isinstance(last, str) else " ".join(map(str, last))
        self.assertIn("highpass=f=80,afftdn=nf=-25:tn=1,", chain("--voice", "light", "--denoise"))
        self.assertIn("highpass=f=80,afftdn=nf=-40:tn=1,", chain("--voice", "light", "--denoise", "--denoise-strength", "40"))
        for level in ("medium", "strong"):
            with self.subTest(level):
                strong = chain("--voice", level, "--denoise", "--denoise-strength", "40")
                self.assertIn("afftdn=nf=-40:tn=1", strong)
                self.assertEqual(strong.count("afftdn="), 1, "one denoise stage, at the strength asked")
        # without --denoise, and with it at the default strength, the chains --voice always wrote
        self.assertNotIn("afftdn", chain("--voice", "light"))
        self.assertEqual(chain("--voice", "medium", "--denoise"), chain("--voice", "medium"))

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
        # #275: every other mp4-writing path (x264, colour, export.py) adds -movflags
        # +faststart; this stream-copy branch (video copied, only audio re-encoded -- the path
        # render.py --template's export.py --normalize step runs) silently dropped it, so a
        # template delivery came out with moov at the end despite export.py having just written
        # it faststart.
        self.assertTrue(_is_faststart(out), "#275: loudness.py's stream-copy branch must write +faststart")

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

    def test_audio_keep_video_branch_writes_faststart_mp4(self):
        """Same shape as #275/#277 (loudness.py): --replace's keep_video branch stream-copies the
        video with -c:v copy while only the audio is touched, and must add -movflags +faststart
        on an mp4 output the same way every other mp4-writing path does."""
        out = OUT / "audio_keepvideo_faststart.mp4"
        script("audio.py", self.src, "--replace", self.mic, "-o", out)
        self.assertEqual(probe(str(out))["video"]["codec"], "h264", "video stream copied")
        self.assertTrue(_is_faststart(out), "audio.py's keep_video branch must write +faststart")

    def test_audio_downmix_voice_and_ducking(self):
        out = OUT / "downmix.mp4"
        script("audio.py", self.surround, "--downmix", "--voice", "-o", out)
        a = probe(str(out))["audio"]
        self.assertEqual(a["channels"], 2)
        out2 = OUT / "ducked.mp4"
        proc = script("audio.py", self.src, "--music", self.long_ref, "--duck", "--music-fade-out", "2", "-o", out2)
        self.assertIn("sidechaingate", proc.stderr)
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
        n = round(probe(str(self.src))["duration"] * 48000)
        end = probe(str(self.src))["duration"] + 0.5 / 48000
        self.assertEqual(bare, "[0:a:0]highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,"
                               "acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2[main];"
                               f"[main]aformat=sample_rates=48000,apad=whole_len={n},atrim=end_sample={n},atrim=end={end:.6f}[out]",
                         "a bare --voice is the 1.12 chain, unchanged (conformed to the picture in samples since #478, "
                         "and ended with it on the timestamp for sound that starts late)")
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
        """1.13: the ducking knobs are sayable. The default threshold is the 0.05 linear the bed
        has used since 1.4 (the flag speaks dBFS), and every flag must land in the filter string
        and in --json's audio block. Since A134 the duck is a sidechain gate whose passed part is
        taken back off the bed by 1 - 10^(-amount/20): the depth is --duck-amount in dB."""
        out = OUT / "duck_params.mp4"
        default, data = self._audio_filters(self.src, "--music", self.long_ref, "--duck", "-o", out)
        self.assertIn("[mwet][key]sidechaingate=threshold=0.05:ratio=9000:range=0:knee=1:attack=20:release=400[mspeech];"
                      "[mspeech]volume=-0.748811[mcut]", default, "the default duck: 0.05 linear, 12 dB deep")
        self.assertEqual(data["audio"]["duck"]["threshold_linear"], 0.05)
        tuned, data = self._audio_filters(self.src, "--music", self.long_ref, "--duck", "--duck-amount", "18",
                                          "--duck-threshold", "-30", "--duck-attack", "5", "--duck-release", "250", "-o", out)
        self.assertIn("sidechaingate=threshold=0.0316228:ratio=9000:range=0:knee=1:attack=5:release=250[mspeech];"
                      "[mspeech]volume=-0.874107[mcut]", tuned)
        self.assertEqual(data["audio"]["duck"], {"amount_db": 18.0, "threshold_db": -30.0, "threshold_linear": 0.0316228,
                                                 "ratio": 9000.0, "attack_ms": 5.0, "release_ms": 250.0})
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
        self.assertGreater(graph.index("[effects]"), graph.index("sidechaingate"),
                           "the effects bed is mixed after the duck, so the sidechain never sees it")
        self.assertTrue(data["audio"]["effects"])
        script("audio.py", self.src, "--effects", self.mic, "--effects-volume", "-20", "-o", out)
        self.assertClose(probe(str(out))["duration"], 12.0, 0.2)

    def test_loudness_versions_writes_one_measured_file_per_target(self):
        """#421: one master, several deliveries; each is normalised from the master and measured
        after, and `verified` covers every version."""
        src = OUT / "versions_src.mp4"
        shutil.copy(self.src, src)
        doc = json.loads(script("loudness.py", src, "--versions=streaming,broadcast-jp,-16/-1.5", "--json", "--overwrite").stdout)
        self.assertTrue(doc["verified"])
        self.assertIsNone(doc["output"])
        self.assertEqual([v["target"] for v in doc["versions"]], ["streaming", "broadcast-jp", "m16lufsm1_5tp"])
        for v, lufs in zip(doc["versions"], (-14.0, -24.0, -16.0)):
            self.assertTrue(Path(v["output"]).exists())
            self.assertAlmostEqual(float(v["result"]["input_i"]), lufs, delta=1.0)
        self.assertEqual({s["version"] for s in doc["verification"] if s["step"] == "loudness"},
                         {"streaming", "broadcast-jp", "m16lufsm1_5tp"})
        # "" and "," (#430 review): an explicitly empty list was read as "not given" and wrote one default file
        for bad in ("bogus", "-16", "-3/-1", "streaming,streaming", "", ","):
            proc = script("loudness.py", src, f"--versions={bad}", "--json", expect_fail=True)
            self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input", bad)
        # each version measures the master once against its own target, and nothing else does (#430
        # review: a pass against the default -I/--tp ran first and was never used)
        doc = json.loads(script("loudness.py", src, "--versions=streaming,ebu-r128", "--dry-run", "--overwrite", "--json").stdout)
        self.assertEqual(sum("print_format=json" in c for c in doc["commands"]), 2, doc["commands"])
        # a --plan written over one of the version files would be refused as an existing output when executed
        taken = OUT / "versions_src_loudnorm_ebu-r128.mp4"
        if taken.exists():
            taken.unlink()
        proc = script("loudness.py", src, "--versions=streaming,ebu-r128", "--plan", taken, "--overwrite", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "output_path_taken")
        self.assertFalse(taken.exists())

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
        # at the 2.22 default --margin 0.2 (5.25 s removed, 6.75 s kept at 0.15)
        self.assertClose(data["removed_seconds"], 4.9, 0.3)
        self.assertClose(probe(str(tight))["duration"], 7.1, 0.3)
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


    @staticmethod
    def _pcm(path):
        """The first audio track's first channel as signed 16-bit samples at its own rate."""
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                              "-af", "pan=mono|c0=c0", "-f", "s16le", "-acodec", "pcm_s16le", "-"],
                             stdout=subprocess.PIPE, check=True).stdout
        import array
        pcm = array.array("h")
        pcm.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            pcm.byteswap()
        return pcm

    @staticmethod
    def _onset(pcm, level=1000):
        return next(i for i, s in enumerate(pcm) if abs(s) > level)

    def test_audio_limiter_does_not_delay_the_sound(self):
        """#476: alimiter without latency=1 delays its output by the look-ahead (--limit-attack,
        5 ms: 240 samples at 48 kHz). With latency compensation the limited sound starts on the
        input's own sample, at every attack, and --voice strong's limiter adds no delay over the
        medium chain it extends."""
        src = OUT / "limit_onset.wav"
        # 0.5 s of silence, then a tone 0.9 of full scale (over every ceiling below)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "aevalsrc=if(gte(n\\,24000)\\,0.9*sin(2*PI*1000*(n-24000)/48000)\\,0):s=48000:d=1.5", "-c:a", "pcm_s16le", src)
        ref = self._pcm(src)
        self.assertEqual(self._onset(ref), 24001, "the fixture's tone starts at sample 24000 (sin 0 = 0)")
        for extra in ((), ("--limit-attack", "20"), ("--limit-ceiling", "-6")):
            with self.subTest(extra=extra):
                out = OUT / "limit_onset_out.wav"
                doc = json.loads(script("audio.py", src, "--limit", *extra, "-o", out, "--json").stdout)
                got = self._pcm(out)
                self.assertEqual(len(got), len(ref), "the length is kept")
                self.assertLessEqual(abs(self._onset(got) - self._onset(ref)), 3, "the limited sound starts where the input's does")
                self.assertIn("latency=1", doc["commands"][0])
        onsets = {}
        for level in ("medium", "strong"):
            out = OUT / f"limit_onset_{level}.wav"
            script("audio.py", src, "--voice", level, "-o", out)
            onsets[level] = self._onset(self._pcm(out), level=300)
        self.assertLessEqual(abs(onsets["strong"] - onsets["medium"]), 3, onsets)

    def test_audio_pad_and_trim_are_exact_to_the_sample(self):
        """#478: the sound was conformed with `atrim=0:{dur:.3f}`, to the millisecond, so a length
        that is not a whole millisecond came out up to 24 samples (48 kHz) off. A replacement that
        is shorter (padded), longer (trimmed), and a music bed now give the input's sample count,
        at 48 kHz and at 44.1 kHz."""
        for rate, samples in ((48000, 59244), (44100, 54433)):
            src = OUT / f"exact_src_{rate}.wav"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               f"sine=f=440:sample_rate={rate}", "-af", f"atrim=end_sample={samples}", "-c:a", "pcm_s16le", src)
            self.assertEqual(self._samples(src)[2], samples, "fixture")
            self.assertNotEqual(round(round(samples / rate, 3) * rate), samples, "not a whole millisecond: the old rounding missed it")
            beds = {}
            for name, secs in (("short", 0.7), ("long", 2.0)):
                beds[name] = OUT / f"exact_bed_{name}_{rate}.wav"
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"sine=f=660:sample_rate={rate}:d={secs}", "-c:a", "pcm_s16le", beds[name])
            for flags in (("--replace", beds["short"]), ("--replace", beds["long"]), ("--music", beds["long"])):
                with self.subTest(rate=rate, flags=flags[0], bed=Path(flags[1]).stem):
                    out = OUT / f"exact_out_{rate}.wav"
                    script("audio.py", src, *flags, "-o", out)
                    self.assertEqual(self._samples(out)[1], rate)
                    self.assertEqual(self._samples(out)[2], samples)
                    self.assertEqual(len(self._pcm(out)), samples)

    def test_audio_that_starts_after_the_picture_still_ends_with_it(self):
        """Review of #492: the sample count that replaced the millisecond trim (#478) does not move
        timestamps, so sound that starts 0.3 s into the picture was padded to the picture's length
        in samples and ran 0.3 s past it. It ends with the picture, as it did before."""
        base = OUT / "late_base.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=160x120:r=25",
           "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", base)
        late = OUT / "late_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-itsoffset", "0.3", "-i", base,
           "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", "2", late)
        self.assertGreater(float(probe(str(late))["audio"].get("start_time") or 0), 0.2, "fixture: the sound starts late")
        out = OUT / "late_out.mp4"
        script("audio.py", late, "--voice", "light", "-o", out)
        ends = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=start_time,duration", "-of", "json",
             str(out)], capture_output=True, text=True, check=True).stdout)["streams"][0]
        self.assertLess(float(ends["start_time"]) + float(ends["duration"]), 2.0 + 0.05)

    @staticmethod
    def _frequency(pcm, rate, lo, hi):
        """The frequency of a pure tone over samples lo..hi, from its zero crossings."""
        part = pcm[lo:hi]
        crossings = sum(1 for a, b in zip(part, part[1:]) if (a < 0) != (b < 0))
        return crossings / 2 / ((hi - lo) / rate)

    def test_audio_tempo_keeps_the_pitch_and_length_samples_is_exact(self):
        """#486: --tempo changes the tempo with atempo, chained in 0.5..2.0 stages outside that
        range, and --length-samples pads or trims to an exact sample count. The output has the
        asked-for length to the sample, and a 440 Hz tone measures 440 Hz after it."""
        src = OUT / "tempo_440.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=2",
           "-c:a", "pcm_s16le", src)
        ref = self._pcm(src)
        self.assertAlmostEqual(self._frequency(ref, 48000, 4800, 86400), 440, delta=2)
        for factor, steps in ((1.5, [1.5]), (0.3, [0.5, 0.6]), (3.0, [2.0, 1.5]), (0.8, [0.8])):
            with self.subTest(tempo=factor):
                n = round(96000 / factor) + 17  # a little past what atempo gives: the tail is padded
                out = OUT / "tempo_out.wav"
                doc = json.loads(script("audio.py", src, "--tempo", str(factor), "--length-samples", str(n),
                                        "-o", out, "--json").stdout)
                self.assertTrue(doc["verified"], doc["verification"])
                self.assertEqual(doc["timing"]["atempo"], steps)
                self.assertAlmostEqual(math.prod(doc["timing"]["atempo"]), factor, places=9)
                step = next(s for s in doc["verification"] if s["step"] == "length_samples")
                self.assertEqual((step["measured"], step["expected"], step["tolerance_samples"]), (n, n, 0))
                got = self._pcm(out)
                self.assertEqual(len(got), n)
                self.assertEqual(self._samples(out)[2], n)
                self.assertAlmostEqual(self._frequency(got, 48000, n // 10, n * 8 // 10), 440, delta=4.4,
                                       msg="the pitch is unchanged (within 1 %)")
        # trimmed as well as padded, without --tempo
        out = OUT / "tempo_trim.wav"
        doc = json.loads(script("audio.py", src, "--length-samples", "48001", "-o", out, "--json").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(len(self._pcm(out)), 48001)
        # An Opus file of a 44.1 kHz track is written at 48 kHz, so N samples at 44.1 kHz is not
        # the file's count: refused with the way out, and exact once the rate is one Opus has
        src441 = OUT / "tempo_441.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:sample_rate=44100:d=2",
           "-c:a", "pcm_s16le", src441)
        (OUT / "len.opus").unlink(missing_ok=True)
        proc = script("audio.py", src441, "--length-samples", "44100", "-o", OUT / "len.opus", "--json", expect_fail=True)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--sample-rate 48000", json.dumps(err))
        self.assertFalse((OUT / "len.opus").exists())
        # a rate Opus codes at is not the rate it decodes at: 16 kHz in is 48 kHz out
        proc = script("audio.py", src441, "--sample-rate", "16000", "--length-samples", "16000", "-o", OUT / "len.opus",
                      "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertFalse((OUT / "len.opus").exists())
        doc = json.loads(script("audio.py", src441, "--sample-rate", "48000", "--length-samples", "48000",
                                "-o", OUT / "len.opus", "--json").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        # without --length-samples nothing is refused
        script("audio.py", src441, "-o", OUT / "plain.opus")
        # a fade-out ends where the output ends: timed on the 2 s source it sat past the 1 s trim
        # and was never heard (review of #492)
        out = OUT / "tempo_trim_fade.wav"
        script("audio.py", src, "--length-samples", "48000", "--fade-out", "0.5", "-o", out)
        faded = self._pcm(out)
        self.assertEqual(len(faded), 48000)
        peak = lambda lo, hi: max(abs(v) for v in faded[lo:hi])  # noqa: E731
        self.assertLess(peak(47000, 48000), 0.1 * peak(12000, 24000), "the last 20 ms are faded down")
        self.assertGreater(peak(23000, 24000), 0.9 * peak(12000, 13000), "and the fade starts at 0.5 s, not before")
        # refusals: the input's own sound beside a copied picture, an exact length beside one, a range
        for argv, needle in ((("--tempo", "1.2", "-o", OUT / "tempo_x.mp4"), "stream-copied"),
                             (("--length-samples", "1000", "-o", OUT / "tempo_x.mp4"), "audio output"),
                             (("--tempo", "20", "-o", OUT / "tempo_x.wav"), "0.1..10"),
                             (("--length-samples", "0", "-o", OUT / "tempo_x.wav"), "positive")):
            with self.subTest(argv=argv[:2]):
                proc = script("audio.py", self.src, *argv, "--json", expect_fail=True)
                err = json.loads(proc.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn(needle, err["message"])

    def test_audio_sample_rate_and_channel_are_checked_on_the_output(self):
        """#487: --sample-rate resamples, --channel N keeps one channel by index; both are read
        back from the output with probe as verification steps, and the kept channel is the one
        asked for (each channel of the fixture is its own tone)."""
        tones = (200, 300, 500, 700)
        src = OUT / "quad_tones.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           *[a for f in tones for a in ("-f", "lavfi", "-i", f"sine=f={f}:sample_rate=48000:d=1")],
           "-filter_complex", "[0][1][2][3]amerge=inputs=4", "-c:a", "pcm_s16le", src)
        self.assertEqual(probe(str(src))["audio"]["channels"], 4, "fixture")
        for index, rate in ((0, 44100), (2, 16000), (3, None)):
            with self.subTest(channel=index, rate=rate):
                out = OUT / "quad_pick.wav"
                doc = json.loads(script("audio.py", src, "--channel", str(index),
                                        *(("--sample-rate", str(rate)) if rate else ()), "-o", out, "--json").stdout)
                self.assertTrue(doc["verified"], doc["verification"])
                steps = {s["step"]: s for s in doc["verification"]}
                self.assertEqual((steps["channels"]["expected"], steps["channels"]["measured"]), (1, 1))
                a = probe(str(out))["audio"]
                self.assertEqual(a["channels"], 1)
                self.assertEqual(int(a["sample_rate"]), rate or 48000)
                if rate:
                    self.assertEqual((steps["sample_rate"]["expected"], steps["sample_rate"]["measured"]), (rate, rate))
                else:
                    self.assertNotIn("sample_rate", steps)
                got = self._pcm(out)
                self.assertAlmostEqual(self._frequency(got, rate or 48000, len(got) // 10, len(got) * 9 // 10),
                                       tones[index], delta=tones[index] * 0.01)
        # --stereo duplicates the kept channel; a rate alone resamples a kept picture's sound too
        doc = json.loads(script("audio.py", src, "--channel", "1", "--stereo", "-o", OUT / "quad_pick_st.wav", "--json").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(probe(str(OUT / "quad_pick_st.wav"))["audio"]["channels"], 2)
        mp4 = OUT / "rate_video.mp4"
        doc = json.loads(script("audio.py", self.src, "--sample-rate", "44100", "-o", mp4, "--json").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(int(probe(str(mp4))["audio"]["sample_rate"]), 44100)
        self.assertIsNotNone(probe(str(mp4))["video"])
        for argv, needle in ((("--channel", "4"), "0..3"), (("--channel", "0", "--downmix"), "contradict"),
                             (("--sample-rate", "10"), "1000..768000")):
            with self.subTest(argv=argv):
                proc = script("audio.py", src, *argv, "-o", OUT / "quad_x.wav", "--json", expect_fail=True)
                err = json.loads(proc.stdout)["error"]
                self.assertEqual(err["kind"], "input")
                self.assertIn(needle, err["message"])

    def test_audio_denoise_strength_range_matches_what_afftdn_accepts(self):
        """--denoise-strength is afftdn's nf, which ffmpeg accepts only in -80..-20: both ends of the
        accepted 20..60 produce a file, and 12 (once accepted, then exit 222 inside ffmpeg) is refused first."""
        for strength in ("20", "60"):
            out = OUT / f"denoise_{strength}.wav"
            data = json.loads(script("audio.py", self.mic, "--denoise", "--denoise-strength", strength, "-o", out, "--json").stdout)
            self.assertIn(f"afftdn=nf=-{strength}:tn=1", data["commands"][0])
            self.assertTrue(out.exists() and out.stat().st_size > 0, strength)
        for strength in ("12", "19.99", "61"):
            proc = script("audio.py", self.mic, "--denoise", "--denoise-strength", strength, "-o", OUT / "denoise_bad.wav",
                          "--json", expect_fail=True)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["error"]["kind"], "input", strength)
            self.assertIn("20..60", doc["error"]["message"])
            self.assertNotIn("$ ", proc.stderr, "refused before ffmpeg ran")

    # ------------------------------------------- the track measured is the track written
    def test_loudness_measures_the_track_it_normalises(self):
        """A110: pass 1 had no -map, so FFmpeg measured the track with the most channels (a:1,
        about -22 LUFS) while pass 2 normalised a:0 (-32 LUFS) with that gain: a -16 target came
        out more than 10 LU short and the run reported the other track's input loudness. Both passes now read a:0."""
        src = make_multistream(OUT / "multi_loud.mkv")
        for ext in (".mkv", ".wav"):
            with self.subTest(output=ext):
                out = OUT / f"multi_loud_norm{ext}"
                d = json.loads(script("loudness.py", src, "-I", "-16", "-o", out, "--json").stdout)
                self.assertClose(float(d["measured"]["input_i"]), MULTI_PROBED["lufs"], 1.0)
                self.assertEqual(written_track(out), "a:0")
                self.assertClose(integrated_lufs(out), -16.0, 1.0)

    def test_audio_mono_folds_the_track_audio_stream_picks(self):
        """A128: --mono read the channel count of a:0, not of the --audio-stream track: a stereo
        track 1 beside a mono track 0 came out stereo, and a mono track 1 beside a stereo track 0
        went through the stereo pan and lost 6 dB."""
        for mono_first in (True, False):
            with self.subTest(mono_first=mono_first):
                src = make_multistream(OUT / f"multi_mono_{int(mono_first)}.mkv", mono_first=mono_first)
                out = OUT / f"multi_mono_{int(mono_first)}_out.mkv"
                script("audio.py", src, "--audio-stream", "1", "--mono", "-o", out)
                self.assertEqual(probe(str(out))["audio"]["channels"], 1)
                self.assertEqual(written_track(out), "a:1")
                if not mono_first:  # a mono track stays at its own level
                    self.assertClose(integrated_lufs(out), integrated_lufs(src, "a:1"), 0.5)

    def test_shared_measurements_read_the_track_probe_describes(self):
        """The measuring helpers silence, sync, scenes, multicam, join and cut call took FFmpeg's
        default track (the one with the most channels) while those tools write a:0."""
        import _common
        src = make_multistream(OUT / "multi_measure.mkv")
        first, second = (_common.measured_level_dbfs(str(src), seconds=None, audio_stream=n) for n in (0, 1))
        self.assertGreater(second["peak_dbfs"] - first["peak_dbfs"], 5.0, "the fixture's tracks differ in level")
        self.assertEqual(_common.measured_level_dbfs(str(src), seconds=None), first)
        # a:0 is the sine source's 1/8 amplitude at volume 0.3
        samples = _common.decode_pcm_mono(str(src), 8000, seconds=1.0)
        self.assertClose(20 * math.log10(max(abs(x) for x in samples)), first["peak_dbfs"], 1.0)


class AudiogramTests(MediaFixtures):
    """1.16: waveform.py over a still plate. The command line without any of the new flags must
    stay byte-identical to 1.15, which is the whole reason this is not a new tool."""

    @staticmethod
    def _plan(*args):
        """The ffmpeg command a run would build, from its own --dry-run plan."""
        doc = json.loads(script("waveform.py", *args, "--dry-run", "--json").stdout)
        cmd = doc["commands"][0]
        return shlex.split(cmd) if isinstance(cmd, str) else list(cmd)

    def _plate(self, w=1080, h=1920):
        png = OUT / f"ag_plate_{w}x{h}.png"
        if not png.exists():
            mp4 = OUT / f"ag_plate_{w}x{h}.mp4"
            script("background.py", "--width", str(w), "--height", str(h),
                   "--gradient", "#1a2b3c:#cc3333", "--duration", "1", "-o", mp4)
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", mp4, "-frames:v", "1", png)
        return png

    # The exact command line 1.15.1 built for `waveform.py IN --width 640 --height 360 -o OUT`,
    # taken from a checkout of origin/main and pinned here. Only the ffmpeg binary, the input and
    # the output are substituted; every other argument, and their order, is the pin.
    WAVEFORM_1_15_1 = [
        "{ffmpeg}", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", "{input}",
        "-filter_complex",
        "color=c=black:s=640x360:r=25[bg];[0:a:0]showwaves=s=640x360:mode=line:rate=25:"
        "split_channels=0:colors=lime[vis];[bg][vis]overlay=format=auto",
        "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "{bt709}",   # bt709_tag_args(): three tag pairs up to FFmpeg 7.0, one -x264-params from 7.1
        "-c:a", "aac", "-b:a", "192k",
        "-t", "12.000", "-shortest", "{output}",
    ]

    def test_waveform_without_image_is_byte_identical_to_1_15(self):
        """The whole argv, not a handful of substrings: a run with none of the audiogram flags
        must build the command line 1.15.1 built, argument for argument and in the same order.
        This is the assertion that makes "the audiogram is four flags on waveform.py, not a second
        tool" checkable instead of asserted."""
        out = OUT / "ag_identical.mp4"
        plan = self._plan(self.src, "--width", "640", "--height", "360", "-o", out)
        # 1.15.1 called bt709_tag_args() too, so the tag spelling follows the ffmpeg on this
        # machine (macOS CI runs 7.x, where the tags travel as -x264-params); the pin is the
        # argv around it.
        sys.path.insert(0, str(SCRIPTS))
        from _common import bt709_tag_args
        expected = []
        for part in self.WAVEFORM_1_15_1:
            if part == "{bt709}":
                expected.extend(bt709_tag_args())
            else:
                expected.append(part.format(ffmpeg=plan[0], input=str(self.src), output=str(out)))
        # 2.10.3: the default lime waves have chroma, so they and the plate are made in RGB and
        # converted to the BT.709 the output is tagged with (drawn colours); 1.15.1's graph is
        # otherwise unchanged -- and byte for byte unchanged for grey waves (below)
        graph = expected.index("-filter_complex") + 1
        pinned = expected[graph]
        expected[graph] = (pinned.replace("r=25[bg]", "r=25,format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[bg]")
                           .replace("colors=lime[vis]", "colors=lime,scale=out_color_matrix=bt709:out_range=tv,format=yuva420p[vis]"))
        self.assertEqual(plan, expected)
        grey = self._plan(self.src, "--width", "640", "--height", "360", "--color", "white", "-o", out)
        expected[graph] = pinned.replace("colors=lime", "colors=white")
        self.assertEqual(grey, expected)

    def test_audiogram_graph_has_one_overlay_per_layer(self):
        plate = self._plate(640, 360)
        plan = self._plan(self.src, "--image", plate, "--width", "640", "--height", "360",
                          "-o", OUT / "ag_graph.mp4")
        joined = " ".join(plan)
        self.assertEqual(joined.count("overlay="), 1, "one overlay: the plate and the visualisation")
        self.assertIn("-loop", plan)
        self.assertIn("[1:v]scale=640:360:force_original_aspect_ratio=increase,crop=640:360", joined)
        self.assertIn("format=rgba[plate]", joined)
        self.assertIn("[v]", plan)

    def test_audiogram_position_maps_to_y(self):
        plate = self._plate(640, 360)
        base = [self.src, "--image", plate, "--width", "640", "--height", "360",
                "--vis-height", "0.5"]
        for position, expect_y in (("top", "y=0"), ("centre", "y=90"),
                                   ("bottom", "y=180"), ("strip", "y=180")):
            with self.subTest(position=position):
                joined = " ".join(self._plan(*base, "--position", position,
                                             "-o", OUT / f"ag_pos_{position}.mp4"))
                self.assertIn(expect_y, joined)
                self.assertIn("showwaves=s=640x180:", joined, "the band is --vis-height of the frame")

    def test_audiogram_platform_frame_comes_from_platforms_table(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        frame = importlib.import_module("_platforms").PLATFORMS["reels"]["frame"]
        joined = " ".join(self._plan(self.src, "--image", self._plate(), "--platform", "reels",
                                     "-o", OUT / "ag_reels.mp4"))
        self.assertIn(f"crop={frame['w']}:{frame['h']}", joined)
        # podcast has no frame: refused, not guessed at
        script("waveform.py", self.src, "--platform", "podcast", "-o", OUT / "ag_pod.mp4",
               expect_fail=True)

    def test_audiogram_refuses_a_url_image(self):
        proc = script("waveform.py", self.src, "--image", "https://example.com/cover.png",
                      "-o", OUT / "ag_url.mp4", expect_fail=True)
        self.assertIn("no network access", proc.stderr)
        script("waveform.py", self.src, "--image", "/nonexistent/cover.png",
               "-o", OUT / "ag_missing.mp4", expect_fail=True)
        # an image and a colour plate are two answers to the same question
        script("waveform.py", self.src, "--image", self._plate(), "--background", "white",
               "-o", OUT / "ag_both.mp4", expect_fail=True)

    def test_audiogram_frame_rate_is_the_one_the_run_announced(self):
        """A looped still defaults to 25 fps and overlay takes its rate from the first input, so
        the plate silently decided the output's frame rate: `--platform tiktok` printed 30 fps and
        wrote a 25 fps file. The rate is now part of what the run verifies."""
        plate = self._plate()
        out = OUT / "ag_fps.mp4"
        res = json.loads(script("waveform.py", self.src, "--image", plate, "--platform", "tiktok",
                                "--json", "-o", out).stdout)
        rate = sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                  "stream=r_frame_rate", "-of", "csv=p=0", out).stdout.strip()
        self.assertEqual(rate, "30/1", "the plate decided the frame rate instead of --platform")
        self.assertTrue(res["audiogram"]["verified"])
        self.assertIn("-framerate", self._plan(self.src, "--image", plate, "--platform", "tiktok",
                                               "-o", OUT / "ag_fps2.mp4"))
        # the colour-plate path never had the bug and must keep its own rate
        rate2 = sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=r_frame_rate", "-of", "csv=p=0",
                   script("waveform.py", self.src, "--platform", "tiktok", "--fast",
                          "-o", OUT / "ag_fps_color.mp4") and OUT / "ag_fps_color.mp4").stdout.strip()
        self.assertEqual(rate2, "30/1")

    def test_audiogram_verified_is_false_under_dry_run(self):
        """Nothing was rendered, so there is nothing to have verified -- and the common top-level
        `verified` says so for the same run. The two keys must not disagree."""
        doc = json.loads(script("waveform.py", self.src, "--image", self._plate(640, 360),
                                "--width", "640", "--height", "360", "--dry-run", "--json",
                                "-o", OUT / "ag_dry.mp4").stdout)
        self.assertFalse(doc["verified"])
        self.assertFalse(doc["audiogram"]["verified"])

    def test_waveform_silent_input_warns_or_fails(self):
        """A silent input renders a flat line that used to be reported as verified. The real run
        measures the input's peak (same -50 dBFS --silence-threshold and --on-silent warn|fail as
        audio.py): warn (default) renders it with `silent: true` and a note, fail refuses as kind
        input before ffmpeg runs; --dry-run measures nothing (`silent: null`)."""
        src = OUT / "wave_silent.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=d=1", "-t", "1", src)
        doc = json.loads(script("waveform.py", src, "--width", "128", "--height", "128", "--json",
                                "-o", OUT / "wave_silent.mp4").stdout)
        self.assertIs(doc["silent"], True)
        self.assertTrue(any("silent" in n for n in doc["notes"]))
        proc = script("waveform.py", src, "--on-silent", "fail", "--width", "128", "--height", "128", "--json",
                      "-o", OUT / "wave_silent_fail.mp4", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["error"]["kind"], doc["commands"]), ("input", []))
        self.assertIn("silent", doc["error"]["message"])
        self.assertFalse((OUT / "wave_silent_fail.mp4").exists())
        doc = json.loads(script("waveform.py", src, "--dry-run", "--json", "-o", OUT / "wave_silent_dry.mp4").stdout)
        self.assertIsNone(doc["silent"])
        doc = json.loads(script("waveform.py", self.mic, "--width", "128", "--height", "128", "--json",
                                "-o", OUT / "wave_loud.mp4").stdout)
        self.assertIs(doc["silent"], False)

    def test_audiogram_refuses_a_zero_by_zero_image(self):
        """A truncated PNG that ffprobe reports as 0x0 is an input refusal naming the image."""
        full = self._plate(64, 64)
        trunc = OUT / "ag_trunc.png"
        trunc.write_bytes(full.read_bytes()[:30])
        proc = script("waveform.py", self.mic, "--image", trunc, "-o", OUT / "ag_trunc.mp4",
                      "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn(str(trunc), doc["error"]["message"])

    def test_audiogram_refuses_an_image_ffmpeg_cannot_decode(self):
        """Spec 2.6: a file that is not a decodable image is an input refusal naming it, before
        ffmpeg is ever started -- not a raw ffmpeg failure."""
        notpic = OUT / "ag_not_a_picture.m4a"
        if not notpic.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "sine=d=1", notpic)
        proc = script("waveform.py", self.src, "--image", notpic, "-o", OUT / "ag_nope.mp4",
                      "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn(str(notpic), doc["error"]["message"])
        self.assertFalse((OUT / "ag_nope.mp4").exists())

    def test_audiogram_renders_with_image_and_captions(self):
        plate = self._plate()
        cues = OUT / "ag_cues.txt"
        cues.write_text("0.0 1.5 Episode twelve\n1.5 3.0 The long one\n", encoding="utf-8")
        out = OUT / "audiogram.mp4"
        res = json.loads(script("waveform.py", self.src, "--image", plate, "--platform", "reels",
                                "--title", "Episode 12", "--text", cues, "--json", "-o", out).stdout)
        ag = res["audiogram"]
        self.assertEqual(ag["background"], "image")
        self.assertTrue(ag["verified"])
        self.assertEqual(ag["stages"], ["waveform", "title", "captions"])
        m, src_m = probe(str(out)), probe(str(self.src))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 1920))
        self.assertLessEqual(abs(m["duration"] - src_m["duration"]), 0.15)
        # the plate is really there: a frame of it is not flat black
        frame = OUT / "audiogram_look.png"
        script("look.py", out, "--at", "1", "-o", frame)
        self.assertTrue(frame.exists())
        # a flat plate compresses to almost nothing; a gradient with a waveform over it does not
        self.assertGreater(frame.stat().st_size, 1000, "the plate is flat: the image never reached the picture")

    def test_render_template_audiogram_runs_the_whole_chain(self):
        cues = OUT / "ag_tpl_cues.txt"
        cues.write_text("0.0 2.0 Episode twelve\n", encoding="utf-8")
        out = OUT / "audiogram_tpl.mp4"
        res = json.loads(script("render.py", self.src, "--template", "audiogram",
                                "--image", self._plate(), "--cues", cues,
                                "--json", "-o", out).stdout)
        self.assertIn("audiogram", res["stages"])
        self.assertEqual(res["stages"][1], "audiogram", "the picture is made before anything uses it")
        self.assertIn("captions", res["stages"])
        self.assertIn("check", res["stages"])
        self.assertTrue(out.exists())

    def test_audiogram_is_not_part_of_template_all(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        render = importlib.import_module("render")
        self.assertIn("audiogram", render.template_names())
        self.assertNotIn("audiogram", render.expand_templates("all"))


    # ------------------------------------------------ 2.2.4: the chained stages and their inputs
    def test_waveform_srt_and_title_rerun_with_overwrite(self):
        """The sub-steps used to get only --dry-run: a second run with --overwrite failed in
        caption.py/graphics.py ("refusing to overwrite") and was reported as kind ffmpeg."""
        srt = OUT / "wf_rerun.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello\n", encoding="utf-8")
        for name, extra in (("wf_rerun_srt.mp4", ("--srt", srt)), ("wf_rerun_title.mp4", ("--title", "Ep 1"))):
            out = OUT / name
            for _ in range(2):
                doc = json.loads(script("waveform.py", self.mic, "--width", "320", "--height", "180",
                                        *extra, "--overwrite", "--json", "-o", out).stdout)
                self.assertEqual(doc["status"], "completed")
            stem = str(out)[:-4]
            self.assertFalse(Path(stem + "_vis.mp4").exists())
            self.assertFalse(Path(stem + "_titled.mp4").exists())

    def test_waveform_missing_srt_is_input_before_any_encode(self):
        out = OUT / "wf_nosrt.mp4"
        proc = script("waveform.py", self.mic, "--srt", OUT / "no_such_cues.srt", "--json", "-o", out,
                      expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("no_such_cues.srt", doc["error"]["message"])
        self.assertEqual(doc["commands"], [], "nothing was encoded")
        self.assertFalse((OUT / "wf_nosrt_vis.mp4").exists())

    def test_waveform_srt_outside_the_render_is_refused_as_input(self):
        """2.2.6: caption.py refuses a cue file none of whose cues falls inside the video; the
        audiogram's caption stage passes that refusal on as kind input."""
        srt = OUT / "wf_late.srt"
        srt.write_text("1\n00:10:00,000 --> 00:10:02,000\nLate\n", encoding="utf-8")
        out = OUT / "wf_late.mp4"
        proc = script("waveform.py", self.mic, "--width", "320", "--height", "180", "--srt", srt,
                      "--json", "-o", out, expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("no cue falls inside the video", doc["error"]["message"])

    def test_waveform_failed_caption_stage_keeps_child_kind_and_cleans_up(self):
        """A caption stage that fails re-raises caption.py's own kind (here: an existing output
        without --overwrite is an input refusal), and the _vis intermediate is removed."""
        srt = OUT / "wf_fail.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
        out = OUT / "wf_fail.mp4"
        out.write_bytes(b"x")
        proc = sh(sys.executable, SCRIPTS / "waveform.py", self.mic, "--width", "320", "--height", "180",
                  "--srt", srt, "--json", "-o", out, expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertNotEqual(doc["error"]["kind"], "ffmpeg")
        self.assertFalse((OUT / "wf_fail_vis.mp4").exists())

    def test_waveform_title_dry_run_completes(self):
        doc = json.loads(script("waveform.py", self.mic, "--title", "Ep 1", "--dry-run", "--json",
                                "-o", OUT / "wf_title_dry.mp4").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["audiogram"]["stages"], ["waveform", "title"])

    def test_audio_beds_without_audio_are_refused_together(self):
        """--music / --effects files with no audio stream: one input refusal naming both, before
        ffmpeg runs -- the dry run included."""
        pics = []
        for n in ("a", "b"):
            p = OUT / f"bed_noaudio_{n}.mp4"
            if not p.exists():
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                   "-i", "testsrc=d=1:s=160x120", "-c:v", "libx264", p)
            pics.append(p)
        for dry in ((), ("--dry-run",)):
            proc = script("audio.py", self.src, "--music", pics[0], "--effects", pics[1], "--json",
                          "-o", OUT / "bed_noaudio_out.mp4", *dry, expect_fail=True)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["error"]["kind"], "input")
            self.assertEqual([(p["flag"], p["reason"]) for p in doc["problems"]],
                             [("--music", "no audio stream"), ("--effects", "no audio stream")])
            self.assertIn(str(pics[0]), doc["error"]["message"])
            self.assertIn(str(pics[1]), doc["error"]["message"])
            self.assertEqual(doc["commands"], [])

    # ------------------------------------------------------------ silent tracks (2.2.6)
    def _silent_files(self):
        wav = OUT / "silent_bed.wav"
        if not wav.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", wav)
        clip = OUT / "silent_voice_clip.mp4"
        if not clip.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=d=3:s=160x120",
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264", "-c:a", "aac", clip)
        return wav, clip

    def test_audio_silent_beds_warn_by_default_and_fail_on_request(self):
        """A silent --music / --effects / --replace file used to be mixed and reported as verified.
        Default warn: mixed, named under `silent` and in a note. --on-silent fail: named in the
        single input refusal, before ffmpeg runs. A dry run measures nothing (a writing tool's dry
        run runs no ffmpeg), so it completes and the real run is the one that refuses."""
        wav, _ = self._silent_files()
        for flag in ("--music", "--effects", "--replace"):
            doc = json.loads(script("audio.py", self.src, flag, wav, "--json",
                                    "-o", OUT / "silent_bed_out.mp4").stdout)
            self.assertEqual(doc["status"], "completed")
            self.assertEqual([(t["flag"], t["path"]) for t in doc["silent"]], [(flag, str(wav))])
            self.assertLessEqual(doc["silent"][0]["peak_db"], -50)
            self.assertTrue(any("silent" in n for n in doc["notes"]))
            proc = script("audio.py", self.src, flag, wav, "--on-silent", "fail", "--json",
                          "-o", OUT / "silent_bed_out.mp4", expect_fail=True)
            err = json.loads(proc.stdout)
            self.assertEqual(err["error"]["kind"], "input")
            self.assertEqual(len(err["problems"]), 1)
            self.assertEqual(err["problems"][0]["flag"], flag)
            self.assertRegex(err["problems"][0]["reason"], r"^silent \(peak -?[0-9.]+ dBFS\)$")
            self.assertEqual(err["commands"], [])
            doc = json.loads(script("audio.py", self.src, flag, wav, "--on-silent", "fail", "--json", "--dry-run",
                                    "-o", OUT / "silent_bed_out.mp4").stdout)
            self.assertEqual(doc["status"], "completed")
        # a real bed is never reported, and a lower threshold lets the silent one through
        doc = json.loads(script("audio.py", self.src, "--music", self.mic, "--json", "--dry-run",
                                "-o", OUT / "silent_bed_out.mp4").stdout)
        self.assertNotIn("silent", doc)
        doc = json.loads(script("audio.py", self.src, "--music", wav, "--silence-threshold", "-120",
                                "--on-silent", "fail", "--json", "-o", OUT / "silent_bed_out.mp4").stdout)
        self.assertEqual(doc["status"], "completed")

    def test_audio_duck_under_a_silent_voice_is_reported(self):
        _, clip = self._silent_files()
        doc = json.loads(script("audio.py", clip, "--music", self.mic, "--duck", "--json",
                                "-o", OUT / "silent_duck_out.mp4").stdout)
        self.assertEqual([t["flag"] for t in doc["silent"]], ["input"])
        proc = script("audio.py", clip, "--music", self.mic, "--duck", "--on-silent", "fail", "--json",
                      "-o", OUT / "silent_duck_out.mp4", expect_fail=True)
        self.assertEqual([p["flag"] for p in json.loads(proc.stdout)["problems"]], ["input"])

    def test_audio_every_tool_json_on_silent_input_parses_strictly(self):
        """A silent file measures -inf LUFS; json.dumps wrote it as -Infinity (export.py's
        `loudness.lufs`), which no strict JSON parser reads. Every --json document must parse
        with NaN/Infinity refused, and export's note must say the audio is silent."""
        _, clip = self._silent_files()

        def strict(text):
            def refuse(c):
                raise ValueError(f"non-standard JSON constant {c}")
            return json.loads(text, parse_constant=refuse)

        runs = [("probe.py", clip), ("check.py", clip, "--platform", "youtube"),
                ("loudness.py", clip, "--measure-only"), ("loudness.py", clip, "-o", OUT / "silent_ln.mp4"),
                ("export.py", clip, "--preset", "youtube", "-o", OUT / "silent_export.mp4"),
                ("audio.py", clip, "--fade-in", "0.5", "-o", OUT / "silent_audio.mp4"),
                ("silence.py", clip, "-o", OUT / "silent_cut.mp4")]
        for name, *args in runs:
            extra = ["--overwrite"] if "-o" in args else []
            proc = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args), "--json", *extra],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            doc = strict(proc.stdout)  # success or refusal, either document must be strict JSON
            self.assertIsInstance(doc, dict, name)
            if name == "export.py":
                self.assertEqual(doc["loudness"]["lufs"], "-inf")
                self.assertTrue(doc["loudness"]["silent"])
                self.assertFalse(doc["loudness"]["ok"])
                self.assertTrue(any(n.startswith("output audio is silent") for n in doc["notes"]))
                self.assertFalse(any("run loudness.py" in n for n in doc["notes"]))


class DownmixLevelTests(unittest.TestCase):
    """3.6.1: --downmix summed 2.7x per side through pan's '=' (no renormalisation) and mixed the
    LFE in at 0.5, so a loud 5.1 clipped (flat factor 20+, thousands of clipped samples) while the
    run said verified, and the weights were not the ITU ones the docs named. The fold-down is now
    ITU-R BS.775 (centre and surrounds at 0.707, LFE dropped) scaled by pan's '<' so its gains sum
    to 1. The worst case is every channel in phase at the same level: that must come out at that
    level, not above it, on 5.1(side), 5.1(back) and 7.1."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)

    def _surround(self, name, layout, channels, gains=None):
        """`channels` copies of one 440 Hz sine at -6 dBFS (amplitude 0.5), in phase, scaled by `gains`."""
        gains = gains or [1.0] * channels
        path = OUT / name
        pan = "|".join(f"c{i}={g:g}*c0" for i, g in enumerate(gains))
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"sine=f=440:d=1:sample_rate=48000,volume=4,pan={layout}|{pan}", "-c:a", "pcm_s16le", path)
        return path

    @staticmethod
    def _peak_db(path):
        proc = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af", "astats=measure_perchannel=none:measure_overall=Peak_level",
                  "-f", "null", "-")
        return float(re.findall(r"Peak level dB: (-?[0-9.]+|-inf)", proc.stderr)[-1])

    def test_an_in_phase_full_level_surround_does_not_clip(self):
        for layout, n in (("5.1(side)", 6), ("5.1", 6), ("7.1", 8)):
            with self.subTest(layout=layout):
                src = self._surround(f"dm_{layout.replace('(', '_').replace(')', '')}.wav", layout, n)
                self.assertAlmostEqual(self._peak_db(src), -6.02, delta=0.1, msg="fixture: every channel at -6 dBFS")
                out = src.with_name(src.stem + "_st.wav")
                doc = json.loads(script("audio.py", src, "--downmix", "--json", "-o", out).stdout)
                self.assertTrue(doc["verified"], doc)
                self.assertEqual(probe(str(out))["audio"]["channels"], 2)
                # gains normalised to 1: in-phase channels at -6 dBFS fold to -6 dBFS (it was +1.7
                # on 5.1 and clipped at 0)
                self.assertAlmostEqual(self._peak_db(out), -6.02, delta=0.3, msg=layout)

    def test_the_lfe_is_dropped_and_the_centre_is_at_minus_3_db_of_the_front(self):
        # FL, FR, FC, LFE, SL, SR: only the LFE carries the tone, then only FC and FL
        lfe = self._surround("dm_lfe_only.wav", "5.1(side)", 6, [0, 0, 0, 1, 0, 0])
        out = OUT / "dm_lfe_only_st.wav"
        script("audio.py", lfe, "--downmix", "-o", out)
        self.assertLess(self._peak_db(out), -80, "BS.775 drops the LFE")
        fc = self._surround("dm_fc_only.wav", "5.1(side)", 6, [0, 0, 1, 0, 0, 0])
        fl = self._surround("dm_fl_only.wav", "5.1(side)", 6, [1, 0, 0, 0, 0, 0])
        out_c, out_l = OUT / "dm_fc_only_st.wav", OUT / "dm_fl_only_st.wav"
        script("audio.py", fc, "--downmix", "-o", out_c)
        script("audio.py", fl, "--downmix", "-o", out_l)
        self.assertAlmostEqual(self._peak_db(out_l) - self._peak_db(out_c), 3.01, delta=0.2)


class Audit459AudioTests(MediaFixtures):
    """Issue #459's audio.py and waveform.py items, each measured on the written file: a limiter
    that ran before the beds were mixed in (A129), a duck depth that was a compressor ratio
    (A134), a bed's fade timed past the bed's end (A142), a bitrate that never reached an audio
    codec (A143, and loudness.py's sibling), help that gave the filters' defaults wrongly (A135)
    and a waveform named after an audio input (A137)."""

    RATE = 48000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def tone(name, graph):
            path = OUT / name
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", graph, "-ac", "1",
               "-c:a", "pcm_s16le", path)
            return path
        # lavfi's sine is 1/8 of full scale: volume=7 puts these at -1.16 dBFS
        cls.voice = tone("a459_voice.wav", "sine=f=300:d=6:r=48000,volume=7")
        cls.bed = tone("a459_bed.wav", "sine=f=500:d=8:r=48000,volume=7")
        # speech (200 Hz) from 2 to 6 s and exact zeros around it, a bed (2 kHz) for 8 s
        cls.speech = tone("a459_speech.wav", "sine=f=200:d=8:r=48000,volume='if(between(t,2,6),4,0)':eval=frame")
        cls.bed_hi = tone("a459_bed_hi.wav", "sine=f=2000:d=8:r=48000,volume=2")
        cls.silence = tone("a459_silence.wav", "anullsrc=r=48000:cl=mono,atrim=0:6")
        cls.short_bed = tone("a459_short_bed.wav", "sine=f=500:d=3:r=48000,volume=4")

    @classmethod
    def _pcm(cls, path, af="anull"):
        # -f wav: FFmpeg 9.0.2 probes some of these tone mixes as MPEG-TS (see riff_wave_args)
        fmt = ["-f", "wav"] if str(path).lower().endswith(".wav") else []
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *fmt, "-i", str(path), "-map", "0:a:0",
                              "-af", af, "-ac", "1", "-ar", str(cls.RATE), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
                             stdout=subprocess.PIPE, check=True).stdout
        import array
        pcm = array.array("h")
        pcm.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            pcm.byteswap()
        return pcm

    def test_a_written_wav_is_probed_as_a_wav(self):
        """FFmpeg 9.0.2 read the mix of test_a_limiter_is_the_ceiling_of_the_mix_it_delivers as
        MPEG-TS (its probe outscores WAV's when the PCM holds 0x47 at a packet's spacing), so the
        run failed its own output check with "End of file". A file that opens with a RIFF/WAVE
        header is probed with -f wav; nothing else is."""
        sys.path.insert(0, str(SCRIPTS))
        from _common.probe import probe, riff_wave_args
        self.assertEqual(riff_wave_args(str(self.voice)), ["-f", "wav"])
        self.assertEqual(riff_wave_args(str(self.src)), [])
        self.assertEqual(riff_wave_args(str(OUT / "a459_absent.wav")), [])
        if hasattr(os, "mkfifo"):  # a pipe is not opened to read its header: that open blocks
            fifo = OUT / "a459_pipe.wav"
            if not fifo.exists():
                os.mkfifo(fifo)
            self.assertEqual(riff_wave_args(str(fifo)), [])
            fifo.unlink()
        named = OUT / "a459_named.dat"  # the header decides, not the name
        named.write_bytes(self.voice.read_bytes())
        self.assertEqual(riff_wave_args(str(named)), ["-f", "wav"])
        self.assertEqual(probe(str(named))["audio"]["codec"], "pcm_s16le")

    @staticmethod
    def _db(value):
        return 20 * math.log10(value) if value > 0 else -120.0

    def _peak_db(self, pcm):
        return self._db(max(abs(s) for s in pcm) / 32768.0)

    def _rms_db(self, pcm, start, end):
        block = pcm[int(start * self.RATE):int(end * self.RATE)]
        return self._db(math.sqrt(sum(s * s for s in block) / max(1, len(block))) / 32768.0)

    def test_a_limiter_is_the_ceiling_of_the_mix_it_delivers(self):
        """A129: --limit (and --voice strong's limiter) ran on the voice before --music/--effects
        were mixed in, so the delivered file peaked over the ceiling: -6 asked, 0 dBFS written."""
        self.assertGreater(self._peak_db(self._pcm(self.voice)), -1.5, "fixture: a voice near full scale")
        cases = ((("--music", self.bed, "--music-volume", "-3", "--limit", "--limit-ceiling", "-6"), -6.0),
                 (("--effects", self.bed, "--effects-volume", "-3", "--limit", "--limit-ceiling", "-6"), -6.0),
                 (("--music", self.bed, "--music-volume", "-3", "--duck", "--limit", "--limit-ceiling", "-6"), -6.0),
                 (("--music", self.bed, "--music-volume", "-3", "--voice", "strong"), -1.0))
        for n, (flags, ceiling) in enumerate(cases):
            with self.subTest(flags=[str(f) for f in flags if str(f).startswith("--")]):
                out = OUT / f"a459_limit_{n}.wav"
                script("audio.py", self.voice, *flags, "-o", out)
                self.assertLessEqual(self._peak_db(self._pcm(out)), ceiling + 0.1, "the written file holds the ceiling")
        # without a bed the limiter still runs on the main track, where it always ran
        _, data = self._audio_filters(self.voice, "--limit", "-o", OUT / "a459_limit_alone.wav")
        self.assertIn("[0:a:0]alimiter=", data["commands"][-1])

    def test_duck_amount_is_the_depth_in_db(self):
        """A134: --duck-amount was a compressor ratio (max(2, amount/3)): 0 and 3 ducked the same
        9.7 dB here and 60 ducked 18. The bed under the speech is now `amount` dB lower than in the
        pauses, the bed's own level measured apart from the speech (a 1 kHz high-pass)."""
        bed_only = "highpass=f=1000,highpass=f=1000,highpass=f=1000"
        for amount in (0, 3, 12, 30):
            with self.subTest(amount=amount):
                out = OUT / f"a459_duck_{amount}.wav"
                doc = json.loads(script("audio.py", self.speech, "--music", self.bed_hi, "--music-volume", "0", "--duck",
                                        "--duck-amount", str(amount), "-o", out, "--json").stdout)
                self.assertEqual(doc["audio"]["duck"]["amount_db"], amount)
                pcm = self._pcm(out, bed_only)
                depth = self._rms_db(pcm, 0.5, 1.5) - self._rms_db(pcm, 3.0, 5.0)
                self.assertAlmostEqual(depth, amount, delta=0.5 if amount < 30 else 1.0)
                # in the pauses the bed is left at its level, at the start (a key of zeros) as after the speech
                self.assertAlmostEqual(self._rms_db(pcm, 0.5, 1.5), self._rms_db(pcm, 7.2, 7.9), delta=0.3)

    def test_music_fade_out_ends_with_a_bed_shorter_than_the_output(self):
        """A142: a 3 s bed under 6 s of sound faded from 5 s, after it had stopped at full level."""
        out = OUT / "a459_short_bed_fade.wav"
        script("audio.py", self.silence, "--music", self.short_bed, "--music-volume", "0", "--music-fade-out", "1", "-o", out)
        pcm = self._pcm(out)
        full = self._rms_db(pcm, 1.0, 1.9)
        self.assertGreater(full, -12, "the bed plays at its level before the fade")
        self.assertLess(self._rms_db(pcm, 2.85, 2.97), full - 20, "faded out by the bed's own end")

    def test_a_fade_out_longer_than_its_bed_still_ends_silent(self):
        """A fade longer than the sound it fades started at 0 with its whole length: a 5 s
        --music-fade-out on a 3 s bed stopped at 40% gain, and --fade-out 8 on 6 s of sound
        ended at 25%. The fade is cut to the bed (the output), so it ends silent there."""
        out = OUT / "a459_long_bed_fade.wav"
        script("audio.py", self.silence, "--music", self.short_bed, "--music-volume", "0", "--music-fade-out", "5", "-o", out)
        pcm = self._pcm(out)
        self.assertGreater(self._rms_db(pcm, 0.1, 0.3), -12, "the bed starts at its level")
        self.assertLess(self._rms_db(pcm, 2.85, 2.97), self._rms_db(pcm, 0.1, 0.3) - 20, "faded out by the bed's own end")
        out = OUT / "a459_long_fade.wav"
        script("audio.py", self.voice, "--fade-out", "8", "-o", out)
        pcm = self._pcm(out)
        self.assertLess(self._rms_db(pcm, 5.88, 5.98), self._rms_db(pcm, 0.1, 0.3) - 20, "faded out by the output's end")

    def test_a_bed_fade_ends_where_the_bed_is_heard_to_end(self):
        """Two more ends a bed's fade was timed past. An output longer than the main track
        (--length-samples): the bed is trimmed at the main track's end, and the fade sat on the
        output's end, after the bed had stopped at full level. A bed whose sound starts late in
        its file (Matroska, picture from 0, sound from 2 to 5 s): afade reads the timestamps, 2 to
        5 s, so a fade timed on the 3 s length ran over the bed's FIRST second and silenced the
        rest (amix plays the bed from the output's start whatever its timestamps)."""
        out = OUT / "a459_fade_long_output.wav"
        script("audio.py", self.silence, "--music", self.bed, "--music-volume", "0", "--music-fade-out", "1",
               "--length-samples", str(8 * self.RATE), "-o", out)
        pcm = self._pcm(out)
        self.assertGreater(self._rms_db(pcm, 1.0, 2.0), -12, "the bed plays at its level")
        self.assertLess(self._rms_db(pcm, 5.88, 5.98), self._rms_db(pcm, 1.0, 2.0) - 20, "faded out by the end of the main track")
        late = OUT / "a459_late_bed.mkv"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=25:d=5",
           "-itsoffset", "2", "-f", "lavfi", "-i", "sine=f=500:d=3:r=48000,volume=4", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_s16le", late)
        out = OUT / "a459_fade_late_bed.wav"
        script("audio.py", self.silence, "--music", late, "--music-volume", "0", "--music-fade-out", "1", "-o", out)
        pcm = self._pcm(out)
        level = self._rms_db(pcm, 0.5, 1.5)
        self.assertGreater(level, -12, "the bed plays from the start")
        self.assertGreater(self._rms_db(pcm, 1.6, 1.9), level - 1, "and is not faded before its last second")
        self.assertLess(self._rms_db(pcm, 2.9, 2.98), level - 20, "faded out by its own end")

    def test_a_key_just_over_the_duck_threshold_ducks_the_bed(self):
        """agate's default soft knee (2.82843) opened the duck's gate only about 2 dB over the
        threshold: speech peaking 1.5 dB over --duck-threshold left the bed at its level (0 of
        12 dB). The gate's knee is hard, so the bed is ducked by the amount."""
        bed_only = "highpass=f=1000,highpass=f=1000,highpass=f=1000"
        out = OUT / "a459_duck_near_threshold.wav"
        # the speech peaks at -6.02 dBFS (a sine of amplitude 0.5)
        script("audio.py", self.speech, "--music", self.bed_hi, "--music-volume", "0", "--duck",
               "--duck-amount", "12", "--duck-threshold", "-7.5", "-o", out)
        pcm = self._pcm(out, bed_only)
        self.assertAlmostEqual(self._rms_db(pcm, 0.5, 1.5) - self._rms_db(pcm, 3.0, 5.0), 12, delta=0.5)

    def test_bitrate_reaches_the_codec_of_an_audio_output(self):
        """A143: --bitrate was ignored for every audio extension (.m4a stayed 256k, .mp3 -q:a 0);
        loudness.py's --audio-bitrate likewise, and its retries re-encoded an .m4a at 256k."""
        def kbps(path):
            meta = probe(str(path))
            return os.path.getsize(path) * 8 / meta["duration"] / 1000
        for ext in (".m4a", ".mp3"):
            with self.subTest(ext=ext):
                out = OUT / f"a459_bitrate{ext}"
                script("audio.py", self.voice, "--bitrate", "64k", "-o", out)
                self.assertAlmostEqual(kbps(out), 64, delta=12)
        # libopus is VBR and overshoots on a pure tone (99 kbps at 64k): two rates, compared
        low, high = OUT / "a459_bitrate_32.opus", OUT / "a459_bitrate_160.opus"
        script("audio.py", self.voice, "--bitrate", "32k", "-o", low)
        script("audio.py", self.voice, "--bitrate", "160k", "-o", high)
        self.assertLess(kbps(low), kbps(high) * 0.6)
        out = OUT / "a459_loud_bitrate.m4a"
        script("loudness.py", self.voice, "--audio-bitrate", "96k", "-o", out)
        self.assertAlmostEqual(kbps(out), 96, delta=14)
        out = OUT / "a459_loud_bitrate.mp3"
        doc = json.loads(script("loudness.py", self.voice, "--audio-bitrate", "96k", "-o", out, "--json").stdout)
        self.assertAlmostEqual(kbps(out), 96, delta=14)
        self.assertEqual(doc["result"]["audio_bitrate_used"], "96k", "the result names the rate the .mp3 was written at")
        for tool, flag in (("audio.py", "--bitrate"), ("loudness.py", "--audio-bitrate")):
            with self.subTest(tool=tool, ext=".wav"):
                doc = json.loads(script(tool, self.voice, flag, "64k", "-o", OUT / "a459_bitrate.wav", "--json",
                                        expect_fail=True).stdout)
                self.assertEqual(doc["error"]["kind"], "input")
                self.assertIn("lossless", doc["error"]["message"])

    def test_dynamics_help_gives_the_filters_own_defaults_in_the_flags_unit(self):
        """A135: the help said acompressor's threshold defaults to -12.4 dB (it is 0.125, -18.06 dB),
        agate's range to -6.1 dB (0.06125, -24.26 dB), and gave the knee's linear 1..8 and 2.83 as
        dB. Each default is read from ffmpeg's own filter help and converted to the flag's dB."""
        def default(filt, opt):
            text = sh("ffmpeg", "-hide_banner", "-h", f"filter={filt}").stdout
            return float(re.search(rf"^\s+{opt}\s+<double>.*\(default ([0-9.]+)\)", text, re.M).group(1))
        help_text = " ".join(sh(sys.executable, SCRIPTS / "audio.py", "--help").stdout.split())
        for flag, filt, opt in (("--comp-threshold", "acompressor", "threshold"), ("--comp-knee", "acompressor", "knee"),
                                ("--gate-threshold", "agate", "threshold"), ("--gate-range", "agate", "range"),
                                ("--gate-knee", "agate", "knee")):
            with self.subTest(flag=flag):
                said = re.search(rf"{flag} [A-Z_]+ [^\[\]]*?default (-?[0-9.]+)", help_text).group(1)
                self.assertAlmostEqual(float(said), 20 * math.log10(default(filt, opt)), delta=0.01)
        # the knee's whole range can be asked for: 18 dB is linear 7.94 (1..8 dB stopped at 2.51)
        _, data = self._audio_filters(self.voice, "--compress", "--comp-knee", "18", "-o", OUT / "a459_knee.wav")
        self.assertIn("knee=7.94328", data["commands"][-1])

    def test_waveform_of_an_audio_input_is_a_video_by_default(self):
        """A137: the default output kept the input's extension: a .wav input failed in the WAV
        muxer and a .m4a input got an H.264 video named .m4a."""
        for ext in (".wav", ".m4a"):
            with self.subTest(ext=ext):
                src = OUT / f"a459_wave_src{ext}"
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.voice, "-t", "2", src)
                want = OUT / "a459_wave_src_waveform.mp4"
                if want.exists():
                    want.unlink()
                doc = json.loads(script("waveform.py", src, "--width", "320", "--height", "180", "--json").stdout)
                self.assertEqual(Path(doc["output"]).name, want.name)
                meta = probe(str(want))
                self.assertIsNotNone(meta["video"])
                self.assertIsNotNone(meta["audio"])
        doc = json.loads(script("waveform.py", self.voice, "-o", OUT / "a459_wave.wav", "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")

    def test_waveform_refuses_every_audio_only_extension(self):
        """The refusal read the extensions this skill writes sound to (AUDIO_CODECS): -o .aiff,
        .aif or .caf failed in ffmpeg's muxer instead (kind ffmpeg), and a dry run planned it."""
        for ext in (".aiff", ".aif", ".caf"):
            for dry in ((), ("--dry-run",)):
                with self.subTest(ext=ext, dry_run=bool(dry)):
                    out = OUT / f"a459_wave_out{ext}"
                    doc = json.loads(script("waveform.py", self.voice, "-o", out, *dry, "--json", expect_fail=True).stdout)
                    self.assertEqual(doc["error"]["kind"], "input", doc)
                    self.assertIn("holds sound only", doc["error"]["message"])
                    self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
