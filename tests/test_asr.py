#!/usr/bin/env python3
"""Tests for the Parakeet speech engines.

    python3 tests/test_asr.py            # this group alone
    python3 tests/test_all.py            # every group

The Parakeet engines are driven through fake binaries on a PATH that holds nothing else, so these
cases never depend on what the host has installed.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, script  # noqa: E402
from _common import asr  # noqa: E402


class ParakeetCppModelTests(unittest.TestCase):
    """parakeet.cpp runs only with a .gguf it can find: an explicit --model is enough, for a
    forced engine and for --engine auto alike."""

    def test_parakeet_cpp_runs_with_only_an_explicit_model(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOME": d}):
            os.environ.pop("PARAKEET_CPP_MODEL", None)
            gguf = Path(d) / "tdt-0.6b-v3-f16.gguf"
            gguf.write_bytes(b"GGUF")
            which = mock.Mock(which=lambda n: "/x/parakeet-cli" if n == "parakeet-cli" else None)
            self.assertFalse(asr._parakeet_available("parakeet.cpp", which))
            self.assertTrue(asr._parakeet_available("parakeet.cpp", which, str(gguf)))
            self.assertEqual(asr._parakeet_model_for("parakeet.cpp", str(gguf), "de"), str(gguf))
            # --engine auto must see it too, not only a forced --engine parakeet.cpp
            self.assertEqual(asr.parakeet_route("auto", "en", "a.wav", which, subprocess)[0], [])
            self.assertEqual(asr.parakeet_route("auto", "en", "a.wav", which, subprocess, str(gguf))[0], list(asr.PARAKEET_ENGINES))


MLX_DOC = {"text": "So um we start. Here.", "sentences": [
    {"text": "So um we start.", "start": 0.2, "end": 1.6, "tokens": [
        {"text": " So", "start": 0.2, "end": 0.4}, {"text": " u", "start": 0.5, "end": 0.6}, {"text": "m", "start": 0.6, "end": 0.7},
        {"text": " ", "start": 0.7, "end": 0.8}, {"text": "we", "start": 0.9, "end": 1.0}, {"text": " start", "start": 1.1, "end": 1.5},
        {"text": ".", "start": 1.5, "end": 1.6}]},
    {"text": "Here.", "start": 2.0, "end": 2.4, "tokens": [{"text": " Here", "start": 2.0, "end": 2.3}, {"text": ".", "start": 2.3, "end": 2.4}]}]}
CPP_DOC = {"text": "So um we start. Here.", "frame_sec": 0.08, "words": [
    {"w": "So", "start": 0.2, "end": 0.4, "conf": 0.99}, {"w": "um", "start": 0.5, "end": 0.7, "conf": 0.9},
    {"w": "we", "start": 0.9, "end": 1.0, "conf": 0.99}, {"w": "start.", "start": 1.1, "end": 1.6, "conf": 0.99},
    {"w": "Here.", "start": 2.0, "end": 2.4, "conf": 0.99}]}


class ParakeetParsingTests(unittest.TestCase):
    def test_mlx_subword_tokens_become_words(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(MLX_DOC, fh)
        words = asr._words_from_parakeet_mlx_json(fh.name)
        self.assertEqual([w["word"] for w in words], ["So", "um", "we", "start.", "Here."])
        self.assertEqual((words[1]["start"], words[1]["end"]), (0.5, 0.7))
        self.assertEqual(asr._cues_from_parakeet_mlx_json(fh.name), [(0.2, 1.6, "So um we start."), (2.0, 2.4, "Here.")])
        os.unlink(fh.name)

    def test_cpp_words_and_the_cues_built_from_them(self):
        words = asr._words_from_parakeet_cpp_json(json.dumps(CPP_DOC))
        self.assertEqual(len(words), 5)
        self.assertEqual(asr.cues_from_words(words), [(0.2, 1.6, "So um we start."), (2.0, 2.4, "Here.")])

    def test_cues_split_on_a_pause_and_on_length(self):
        words = [{"word": "a", "start": 0.0, "end": 0.2}, {"word": "b", "start": 1.5, "end": 1.7}]
        self.assertEqual(len(asr.cues_from_words(words)), 2)
        long = [{"word": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(20)]
        self.assertTrue(all(e - s <= asr.CUE_MAX_SECONDS for s, e, _ in asr.cues_from_words(long)))


class ParakeetRoutingTests(unittest.TestCase):
    def test_auto_routes_by_language(self):
        which = mock.Mock(side_effect=lambda n: "/x/" + n if n == "parakeet-mlx" else None)
        sh_ = mock.Mock(which=which)
        self.assertEqual(asr.parakeet_route("auto", "en", "a.wav", sh_, subprocess)[0], list(asr.PARAKEET_ENGINES))
        self.assertEqual(asr.parakeet_route("auto", "fr", "a.wav", sh_, subprocess)[0], [])
        self.assertEqual(asr.parakeet_route("whisper.cpp", None, "a.wav", sh_, subprocess)[0], [])
        self.assertEqual(asr.parakeet_route("parakeet.cpp", "de", "a.wav", sh_, subprocess)[0], ["parakeet.cpp"])
        with mock.patch.object(asr, "detect_language", return_value="ja"):
            self.assertEqual(asr.parakeet_route("auto", None, "a.wav", sh_, subprocess)[0], [])
        with mock.patch.object(asr, "detect_language", return_value=None):
            eng, route = asr.parakeet_route("auto", None, "a.wav", sh_, subprocess)
            self.assertEqual(eng, list(asr.PARAKEET_ENGINES))
            self.assertIn("assumed English", route["routing"])

    def test_english_only_model_refuses_another_language(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PARAKEET_MODEL", None)
            with self.assertRaises(SystemExit):
                asr._parakeet_model_for("parakeet-mlx", None, "fr")
            self.assertIn("v3", asr._parakeet_model_for("parakeet-mlx", "mlx-community/parakeet-tdt-0.6b-v3", "fr"))
            self.assertEqual(asr._parakeet_model_for("parakeet-mlx", "large-v3-turbo", "en"), asr.PARAKEET_MLX_DEFAULT_MODEL)

    def test_unknown_engine_in_the_environment_is_refused(self):
        with mock.patch.dict(os.environ, {asr.ASR_ENGINE_ENV: "vosk"}):
            with self.assertRaises(SystemExit):
                asr.requested_engine(None)


class ParakeetEngineTests(MediaFixtures):
    """caption.py / silence.py drive fake Parakeet binaries on a PATH that holds only them and ffmpeg."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bin = Path(tempfile.mkdtemp(prefix="ffskill_fakeasr_"))
        for tool in ("ffmpeg", "ffprobe", "fc-match", "fc-list"):
            if shutil.which(tool):
                os.symlink(shutil.which(tool), cls.bin / tool)
        mlx = """
            import json, os, sys
            a = sys.argv[1:]; out = a[a.index("--output-dir") + 1]; os.makedirs(out, exist_ok=True)
            json.dump(DOC, open(os.path.join(out, os.path.splitext(os.path.basename(a[0]))[0] + ".json"), "w"))
            """
        cpp = """
            import json, sys
            assert sys.argv[1] == "transcribe" and "--json" in sys.argv
            print(json.dumps(DOC))
            """
        for name, body, doc in (("parakeet-mlx", mlx, MLX_DOC), ("parakeet-cli", cpp, CPP_DOC)):
            p = cls.bin / name
            p.write_text(f"#!{sys.executable}\nDOC = {doc!r}\n" + textwrap.dedent(body))
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        cls.gguf = cls.bin / "tdt-0.6b-v2-f16.gguf"
        cls.gguf.write_bytes(b"GGUF")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.bin, ignore_errors=True)
        super().tearDownClass()

    def env(self, **extra):
        e = dict(os.environ, PATH=f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", PARAKEET_CPP_MODEL=str(self.gguf))
        e.update(extra)
        return e

    def test_caption_auto_picks_parakeet_for_english_and_reports_it(self):
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--language", "en", "--fast", "--json",
                                "-o", OUT / "pk_auto.mp4", env=self.env()).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet-mlx")
        self.assertEqual(doc["transcription"]["model"], asr.PARAKEET_MLX_DEFAULT_MODEL)
        self.assertIn("So um we start.", (OUT / "pk_auto.srt").read_text())

    def test_caption_engine_flag_and_env_pick_parakeet_cpp(self):
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--engine", "parakeet.cpp", "--fast", "--json",
                                "-o", OUT / "pk_cpp.mp4", env=self.env()).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--fast", "--json", "-o", OUT / "pk_cpp_env.mp4",
                                env=self.env(FFMPEG_SKILL_ASR_ENGINE="parakeet.cpp")).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")

    def test_caption_another_language_skips_parakeet(self):
        proc = script("caption.py", self.src, "--transcribe", "--language", "fr", "--fast", "--json",
                      "-o", OUT / "pk_fr.mp4", env=self.env(), expect_fail=True)
        err = json.loads(proc.stdout)["error"]["message"]
        self.assertIn("no local speech-to-text engine", err)

    def test_silence_filler_words_from_parakeet(self):
        doc = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                "--engine", "parakeet.cpp", env=self.env()).stdout)
        self.assertEqual(doc["filler"]["source"], "parakeet:parakeet.cpp")
        self.assertEqual([r["word"] for r in doc["filler"]["removed"]], ["um"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
