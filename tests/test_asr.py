#!/usr/bin/env python3
"""Tests for the Parakeet speech engines.

    python3 tests/test_asr.py            # this group alone
    python3 tests/test_all.py            # every group

The Parakeet engines are driven through fake binaries on a PATH that holds nothing else, so these
cases never depend on what the host has installed.
"""
import json
import os
import platform
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


def _assumed(doc):
    """The result document's top-level notes that say English was assumed."""
    return [n for n in doc.get("notes") or [] if n.startswith("English was assumed")]


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

    def test_malformed_engine_output_yields_no_words_instead_of_crashing(self):
        """Garbage, the wrong shape, and words missing fields are skipped, never raised."""
        for text in ("not json", "[]", "null", json.dumps({"words": "x"}), json.dumps({"words": 5}),
                     json.dumps({"words": [5, None, []]})):
            self.assertEqual(asr._words_from_parakeet_cpp_json(text), [], text)
        mixed = {"words": [{"w": "ok", "start": 0.1, "end": 0.3}, {"w": "no-times"}, {"start": 1, "end": 2},
                           {"w": "bad", "start": "x", "end": 1}, "str", {"w": "fine", "start": 1.0, "end": 1.2}]}
        self.assertEqual([w["word"] for w in asr._words_from_parakeet_cpp_json(json.dumps(mixed))], ["ok", "fine"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.json"
            for body in ("{truncated", "[1, 2]", json.dumps({"sentences": [{"text": "no times"}]}),
                         json.dumps({"sentences": 5}), json.dumps({"sentences": [5, None]}),
                         json.dumps({"sentences": [{"tokens": 5}]}), json.dumps({"sentences": [{"tokens": [5, None]}]})):
                p.write_text(body)
                self.assertEqual(asr._cues_from_parakeet_mlx_json(str(p)), [], body)
                self.assertEqual(asr._words_from_parakeet_mlx_json(str(p)), [], body)
            self.assertEqual(asr._words_from_parakeet_mlx_json(str(Path(d) / "missing.json")), [])

    def test_cues_split_on_a_pause_and_on_length(self):
        words = [{"word": "a", "start": 0.0, "end": 0.2}, {"word": "b", "start": 1.5, "end": 1.7}]
        self.assertEqual(len(asr.cues_from_words(words)), 2)
        # 0.5 s apart, 0.4 s long: w13 ends at 6.9 s, w14 would stretch the cue to 7.4 s (> 7 s)
        long = [{"word": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(20)]
        self.assertEqual(asr.cues_from_words(long), [
            (0.0, 6.9, " ".join(f"w{i}" for i in range(14))),
            (7.0, 9.9, " ".join(f"w{i}" for i in range(14, 20)))])


class ParakeetRoutingTests(unittest.TestCase):
    def test_auto_routes_by_language(self):
        which = mock.Mock(side_effect=lambda n: "/x/" + n if n == "parakeet-mlx" else None)
        sh_ = mock.Mock(which=which)
        self.assertEqual(asr.parakeet_route("auto", "en", "a.wav", sh_, subprocess)[0], ["parakeet-mlx", "parakeet.cpp"])
        self.assertEqual(asr.parakeet_route("auto", "fr", "a.wav", sh_, subprocess)[0], [])
        self.assertEqual(asr.parakeet_route("whisper.cpp", None, "a.wav", sh_, subprocess)[0], [])
        self.assertEqual(asr.parakeet_route("parakeet.cpp", "de", "a.wav", sh_, subprocess)[0], ["parakeet.cpp"])
        with mock.patch.object(asr, "detect_language", return_value="ja"):
            self.assertEqual(asr.parakeet_route("auto", None, "a.wav", sh_, subprocess)[0], [])
        with mock.patch.object(asr, "detect_language", return_value=None), \
                mock.patch.object(asr, "_whisper_ready", return_value=False):
            route = asr.parakeet_route("auto", None, "a.wav", sh_, subprocess)
            self.assertEqual(route.first, ["parakeet-mlx", "parakeet.cpp"])
            self.assertEqual(route.last, ())
            self.assertIn("assumed English", route.facts["routing"])

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

    def test_engine_flag_beats_the_environment_which_beats_auto(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(asr.ASR_ENGINE_ENV, None)
            self.assertEqual(asr.requested_engine(None), "auto")
            os.environ[asr.ASR_ENGINE_ENV] = "parakeet.cpp"
            self.assertEqual(asr.requested_engine(None), "parakeet.cpp")
            self.assertEqual(asr.requested_engine("whisper.cpp"), "whisper.cpp")


class UndetectedLanguageTests(unittest.TestCase):
    """Review of #305: with no --language and nothing to detect one, auto handed the speech to the
    English-only Parakeet model and the only trace was `transcription.routing`. A Whisper engine
    that can run now goes first; only with none does Parakeet run on English assumed, and then
    the caller gets a top-level `notes` line saying the transcript may be wrong."""

    def setUp(self):
        self.mlx_only = mock.Mock(which=lambda n: "/x/parakeet-mlx" if n == "parakeet-mlx" else None)

    def test_a_runnable_whisper_goes_first_and_parakeet_waits(self):
        with mock.patch.object(asr, "detect_language", return_value=None), \
                mock.patch.object(asr, "_whisper_ready", return_value=True):
            route = asr.parakeet_route("auto", None, "a.wav", self.mlx_only, subprocess)
        self.assertEqual(route.first, [])
        self.assertEqual(route.last, asr.PARAKEET_ENGINES)
        self.assertEqual(route.facts, {"routing": asr.ROUTING_UNDETECTED_WHISPER})

    def test_only_parakeet_runs_on_english_assumed(self):
        with mock.patch.object(asr, "detect_language", return_value=None), \
                mock.patch.object(asr, "_whisper_ready", return_value=False):
            route = asr.parakeet_route("auto", None, "a.wav", self.mlx_only, subprocess)
        self.assertEqual(route.first, list(asr.PARAKEET_ENGINES))
        self.assertEqual(route.facts, {"routing": asr.ROUTING_ASSUMED_ENGLISH})

    def test_a_named_language_or_a_detected_one_never_asks_for_whisper(self):
        with mock.patch.object(asr, "_whisper_ready", side_effect=AssertionError("not consulted")):
            self.assertEqual(asr.parakeet_route("auto", "en", "a.wav", self.mlx_only, subprocess).first,
                             list(asr.PARAKEET_ENGINES))
            with mock.patch.object(asr, "detect_language", return_value="en"):
                self.assertEqual(asr.parakeet_route("auto", None, "a.wav", self.mlx_only, subprocess).last, ())
            # a named engine runs as asked
            self.assertEqual(asr.parakeet_route("parakeet-mlx", None, "a.wav", self.mlx_only, subprocess),
                             asr.Route(["parakeet-mlx"], {"routing": "requested"}))

    def test_whisper_ready_means_an_engine_auto_would_run(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sys.modules, {"faster_whisper": None}):
            model = Path(d) / "ggml-base.bin"
            cli_only = mock.Mock(which=lambda n: "/x/whisper-cli" if n == "whisper-cli" else None)
            self.assertFalse(asr._whisper_ready(cli_only, str(Path(d) / "missing.bin")), "whisper-cli with no model")
            model.write_bytes(b"")
            self.assertTrue(asr._whisper_ready(cli_only, str(model)))
            self.assertFalse(asr._whisper_ready(cli_only, "mlx-community/parakeet-tdt-0.6b-v3"), "a Parakeet model")
            self.assertFalse(asr._whisper_ready(cli_only, str(Path(d) / "tdt-0.6b-v2-f16.gguf")))
            self.assertTrue(asr._whisper_ready(mock.Mock(which=lambda n: "/x/whisper" if n == "whisper" else None), "base"))
            self.assertFalse(asr._whisper_ready(self.mlx_only, "base"))
        stub = type(sys)("faster_whisper")  # a module with no __spec__, as a test stub is
        with mock.patch.dict(sys.modules, {"faster_whisper": stub}):
            self.assertTrue(asr._whisper_ready(self.mlx_only, "base"))

    def test_the_note_names_the_callers_flag(self):
        self.assertIn("--filler-lang", asr.assumed_english_note("--filler-lang"))
        self.assertIn("install a Whisper engine", asr.assumed_english_note())
        self.assertIn("fix the Whisper engine", asr.assumed_english_note(whisper_failed=True))


class _FakeEngines:
    """shutil / subprocess stand-ins for the bridge: `which` answers only for `names`, and `run`
    writes what the named engine would have written where its arguments say."""

    def __init__(self, names):
        self.names = set(names)

    def which(self, name):
        return f"/x/{name}" if name in self.names or name in ("ffmpeg", "ffprobe") else None

    def run(self, cmd, **kw):
        exe = os.path.basename(cmd[0])
        if exe == "parakeet-mlx":
            out = cmd[cmd.index("--output-dir") + 1]
            os.makedirs(out, exist_ok=True)
            Path(out, "audio.json").write_text(json.dumps(MLX_DOC), encoding="utf-8")
        elif exe == "whisper-cli" and "-osrt" in cmd:
            Path(cmd[cmd.index("-of") + 1] + ".srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,500\nBonjour tout le monde\n", encoding="utf-8")
        elif exe == "whisper-cli" and "--output-json-full" in cmd:
            Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [{"tokens": [
                {"text": " Bonjour", "offsets": {"from": 0, "to": 600}},
                {"text": " euh", "offsets": {"from": 700, "to": 900}}]}]}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")


class TranscriptionStateTests(unittest.TestCase):
    """Review of #305: the engine, routing and Parakeet word timings were handed back through
    module-level LAST_RUN / LAST_WORDS, which every call in one process shared (mcp/server.py,
    batch.py, a test). The calls now return them; nothing is kept in the module."""

    def _patched(self, engines):
        import _common
        fake = _FakeEngines(engines)
        stack = [mock.patch.object(_common, "run_analysis", lambda *a, **k: None),
                 mock.patch.object(shutil, "which", fake.which),
                 mock.patch.object(subprocess, "run", fake.run),
                 mock.patch.dict(sys.modules, {"faster_whisper": None}),
                 # a host ggml model in ~/.cache/whisper.cpp must not change the model named below
                 mock.patch.object(asr, "_whisper_cpp_model", lambda m: m),
                 mock.patch.dict(os.environ, {"PARAKEET_MODEL": "", "PARAKEET_CPP_MODEL": "", asr.ASR_ENGINE_ENV: ""})]
        return stack

    def _with(self, engines, call):
        stack = self._patched(engines)
        for p in stack:
            p.start()
        try:
            return call()
        finally:
            for p in reversed(stack):
                p.stop()

    def test_two_transcriptions_in_one_process_do_not_share_state(self):
        self.assertFalse(hasattr(asr, "LAST_RUN") or hasattr(asr, "LAST_WORDS"),
                         "module-level hand-off state is back")
        with tempfile.TemporaryDirectory() as d:
            srt = os.path.join(d, "a.srt")
            first = self._with(["parakeet-mlx"], lambda: asr.transcribe_result("talk.mp4", srt, "en", "base"))
            snapshot = (first.engine, [dict(w) for w in first.words], dict(first.facts), list(first.cues))
            self.assertEqual(first.engine, "parakeet-mlx")
            self.assertEqual([w["word"] for w in first.words], ["So", "um", "we", "start.", "Here."])
            self.assertEqual(first.facts, {"routing": "auto: --language is English", "engine": "parakeet-mlx",
                                           "model": asr.PARAKEET_MLX_DEFAULT_MODEL, "language": "en"})

            # a whisper caption run after it: no Parakeet words, model or routing carried over
            second = self._with(["whisper-cli"], lambda: asr.transcribe_result("talk.mp4", srt, None, "base",
                                                                                engine="whisper.cpp"))
            self.assertEqual(second.engine, "whisper.cpp")
            self.assertEqual(second.words, [])
            self.assertEqual(second.cues, [(0.0, 1.5, "Bonjour tout le monde")])
            self.assertEqual(second.facts, {"routing": "requested", "engine": "whisper.cpp", "model": "base", "language": None})
            self.assertEqual(second.notes, [])

            # a word run in between and after: its own words, engine and facts only
            third = self._with(["whisper-cli", "parakeet-mlx"],
                               lambda: asr.transcribe_words_result("talk.mp4", "fr", engine="whisper.cpp"))
            self.assertEqual([w["word"] for w in third.words], ["Bonjour", "euh"])
            self.assertEqual(third.facts["language"], "fr")

            # and the earlier results are still exactly what their own calls returned
            self.assertEqual((first.engine, first.words, first.facts, first.cues), snapshot)
            self.assertEqual(second.words, [])

    def test_the_old_call_shapes_still_answer(self):
        """transcribe() -> cues and transcribe_words() -> (words, engine): what callers had."""
        with tempfile.TemporaryDirectory() as d:
            cues = self._with(["parakeet-mlx"], lambda: asr.transcribe("talk.mp4", os.path.join(d, "a.srt"), "en", "base"))
            self.assertEqual(cues, [(0.2, 1.6, "So um we start."), (2.0, 2.4, "Here.")])
            words, engine = self._with(["parakeet-mlx"], lambda: asr.transcribe_words("talk.mp4", "en"))
            self.assertEqual((len(words), engine), (5, "parakeet-mlx"))


class InstallHintTests(unittest.TestCase):
    """Review of #305: parakeet-mlx fetches its default model from Hugging Face on first use. The
    hints say so, and say the audio stays on the machine, so "no cloud" stays a true sentence."""

    def test_the_refusal_hint_names_the_first_run_download_and_keeps_audio_local(self):
        hint = asr.ASR_INSTALL_HINT
        line = next(ln for ln in hint.splitlines() if ln.strip().startswith("parakeet-mlx:"))
        rest = hint[hint.index(line):].split("parakeet.cpp:")[0]
        self.assertIn("first run", rest)
        self.assertIn("Hugging Face", rest)
        self.assertIn(asr.PARAKEET_MLX_DEFAULT_MODEL, rest)
        self.assertIn("never leaves", hint.splitlines()[0])
        self.assertNotIn("offline", hint, "a first run that downloads is not offline")

    def test_doctors_fix_line_says_the_same(self):
        import _contract
        fix = _contract._capability_fix_hint("external:parakeet")
        for words in ("first run", "Hugging Face", asr.PARAKEET_MLX_DEFAULT_MODEL, "never uploaded"):
            self.assertIn(words, fix)

    def test_the_reference_page_no_longer_says_nothing_is_downloaded(self):
        root = Path(__file__).resolve().parent.parent
        page = (root / "references" / "scripts.md").read_text(encoding="utf-8")
        section = page[page.index("### caption.py --transcribe"):]
        section = section[:section.index("\n### ", 5)]
        self.assertNotIn("Nothing is downloaded", section)
        for words in ("Hugging Face", "never uploaded", "first time it runs"):
            self.assertIn(words, section)


@unittest.skipIf(platform.system() == "Windows", "the fake engines are #! scripts on a POSIX PATH shim; the routing "
                 "they drive is covered on every OS by the in-process tests above")
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
        self.assertFalse(_assumed(doc), "English was named, not assumed")

    def test_caption_engine_flag_picks_parakeet_cpp(self):
        """One end-to-end parakeet.cpp run; flag-over-env precedence is a unit test above."""
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--engine", "parakeet.cpp", "--fast", "--json",
                                "-o", OUT / "pk_cpp.mp4", env=self.env()).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")
        self.assertIn("So um we start.", (OUT / "pk_cpp.srt").read_text())
        # a named engine runs as asked, with no language: no routing decision, so no warning
        self.assertEqual(doc["transcription"]["routing"], "requested")
        self.assertFalse(_assumed(doc))

    def test_caption_mux_reports_the_transcription_too(self):
        """--mode mux wrote a soft subtitle track from the transcript but left `transcription` out of
        its result, so a caller could not tell which engine made it."""
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--engine", "parakeet.cpp", "--mode", "mux",
                                "--json", "-o", OUT / "pk_mux.mp4", env=self.env()).stdout)
        self.assertEqual(doc["subtitle_tracks"], 1)
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")

    def test_caption_takes_the_engine_from_the_environment(self):
        """$FFMPEG_SKILL_ASR_ENGINE reaches caption.py through its real parser (no --engine given)."""
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--fast", "--json", "-o", OUT / "pk_cpp_env.mp4",
                                env=self.env(FFMPEG_SKILL_ASR_ENGINE="parakeet.cpp")).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")

    def _run_with_mlx_writing(self, body, tool, *args, expect_fail=False):
        """`tool` with a parakeet-mlx that exits 0 after writing `body` as its JSON."""
        fake = Path(tempfile.mkdtemp(prefix="ffskill_oddasr_"))
        try:
            for name in os.listdir(self.bin):
                if name != "parakeet-mlx":
                    os.symlink(self.bin / name, fake / name)
            mlx = fake / "parakeet-mlx"
            mlx.write_text(f"#!{sys.executable}\nimport os, sys\na = sys.argv[1:]; out = a[a.index('--output-dir') + 1]\n"
                           "os.makedirs(out, exist_ok=True)\n"
                           "open(os.path.join(out, os.path.splitext(os.path.basename(a[0]))[0] + '.json'), 'w')"
                           f".write({body!r})\n")
            mlx.chmod(0o755)
            proc = script(tool, self.src, *args, "--json", env=self.env(PATH=str(fake)), expect_fail=expect_fail)
        finally:
            shutil.rmtree(fake, ignore_errors=True)
        return json.loads(proc.stdout)

    def test_unreadable_engine_output_falls_through_instead_of_claiming_silence(self):
        """parakeet-mlx exited 0 but wrote something that is not a transcript: that is a failed
        run, so auto moves on to parakeet.cpp instead of reporting "no speech" in the video."""
        doc = self._run_with_mlx_writing('{"sentences": 5}', "caption.py", "--transcribe", "--fast", "-o", OUT / "pk_garbage.mp4")
        self.assertEqual(doc["transcription"]["engine"], "parakeet.cpp")

    def test_filler_words_fall_through_an_engine_with_sentences_but_no_word_times(self):
        """Sentences whose text and times read but whose tokens do not: cues for a caption, but no
        word timings, which is all silence.py --filler needs -- so the next engine is tried."""
        body = json.dumps({"text": "So um we start.", "sentences": [{"text": "So um we start.", "start": 0.2, "end": 1.6,
                                                                     "tokens": [{"text": " So"}, 5]}]})
        doc = self._run_with_mlx_writing(body, "silence.py", "--filler", "--transcribe", "--filler-list")
        self.assertEqual(doc["filler"]["source"], "parakeet:parakeet.cpp")
        self.assertEqual([r["word"] for r in doc["filler"]["removed"]], ["um"])

    def test_a_named_engine_with_no_word_times_is_refused_by_name(self):
        """--engine parakeet-mlx ran and gave no word timings: say that, not "install it"."""
        body = json.dumps({"text": "So um we start.", "sentences": [{"text": "So um we start.", "start": 0.2, "end": 1.6,
                                                                     "tokens": [{"text": " So"}, 5]}]})
        doc = self._run_with_mlx_writing(body, "silence.py", "--filler", "--transcribe", "--filler-list",
                                         "--engine", "parakeet-mlx", expect_fail=True)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("parakeet-mlx ran but produced no word-level timings", doc["error"]["message"])

    def test_an_engine_that_heard_nothing_still_reports_no_speech(self):
        """What both real engines write for 3 s of silence (measured): an empty list. That is an
        answer, not a failure, so it is still the no-speech refusal and nothing else is tried."""
        doc = self._run_with_mlx_writing('{"text": "", "sentences": []}', "caption.py", "--transcribe", "--fast",
                                         "-o", OUT / "pk_silent.mp4", expect_fail=True)
        self.assertEqual((doc["error"]["kind"], doc.get("reason"), doc.get("engine")), ("input", "no_speech", "parakeet-mlx"))

    def test_auto_falls_through_a_failing_parakeet_mlx_to_parakeet_cpp(self):
        """parakeet-mlx is installed but crashes: auto moves on to the next Parakeet engine."""
        broken = Path(tempfile.mkdtemp(prefix="ffskill_brokenasr_"))
        try:
            for name in os.listdir(self.bin):
                if name != "parakeet-mlx":
                    os.symlink(self.bin / name, broken / name)
            ran = broken / "mlx-ran"
            mlx = broken / "parakeet-mlx"
            mlx.write_text(f"#!/bin/sh\n: > '{ran}'\necho 'Metal device lost' >&2\nexit 3\n")
            mlx.chmod(0o755)
            # only the fakes and ffmpeg on PATH: no host whisper can detect a language or take over,
            # so auto assumes English and the order is parakeet-mlx, then parakeet.cpp
            doc = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                    env=self.env(PATH=str(broken))).stdout)
            mlx_ran = ran.exists()
        finally:
            shutil.rmtree(broken, ignore_errors=True)
        self.assertTrue(mlx_ran, "the crashing parakeet-mlx was never run, so nothing fell through")
        self.assertEqual(doc["filler"]["source"], "parakeet:parakeet.cpp")
        self.assertEqual([r["word"] for r in doc["filler"]["removed"]], ["um"])

    def _no_host_whisper(self):
        if asr._module_importable("faster_whisper"):
            self.skipTest("faster-whisper is importable here, so a Whisper engine is always available")

    def _with_whisper_cli(self, fail):
        """A PATH holding the fake Parakeet engines, ffmpeg and a fake whisper-cli whose language
        detector names nothing; it transcribes ("Bonjour tout le monde") unless `fail`. HOME
        holds the ggml-base.bin it is run with. Returns (PATH dir, HOME dir); the caller removes both."""
        d = Path(tempfile.mkdtemp(prefix="ffskill_whisperasr_"))
        home = Path(tempfile.mkdtemp(prefix="ffskill_whisperhome_"))
        for name in os.listdir(self.bin):
            os.symlink(self.bin / name, d / name)
        (home / ".cache" / "whisper.cpp").mkdir(parents=True)
        (home / ".cache" / "whisper.cpp" / "ggml-base.bin").write_bytes(b"")
        cli = d / "whisper-cli"
        cli.write_text(f"#!{sys.executable}\nFAIL = {fail!r}\n" + textwrap.dedent("""
            import json, sys
            a = sys.argv[1:]
            if "-dl" in a:
                print("whisper_full_with_state: no language line in this build", file=sys.stderr)
                sys.exit(0)
            if FAIL:
                print("whisper_init_from_file_with_params: failed to load model", file=sys.stderr)
                sys.exit(1)
            of = a[a.index("-of") + 1]
            if "-osrt" in a:
                open(of + ".srt", "w").write("1\\n00:00:00,000 --> 00:00:01,500\\nBonjour tout le monde\\n")
            if "--output-json-full" in a:
                json.dump({"transcription": [{"tokens": [{"text": " Bonjour", "offsets": {"from": 0, "to": 600}},
                                                         {"text": " euh", "offsets": {"from": 700, "to": 900}}]}]},
                          open(of + ".json", "w"))
            """))
        cli.chmod(0o755)
        return d, home

    def test_no_language_and_only_parakeet_says_english_was_assumed(self):
        """Review of #305: a Mac with parakeet-mlx and no Whisper captioning speech nobody named.
        Parakeet still runs, but the result says, at the top level, that English was assumed."""
        self._no_host_whisper()
        doc = json.loads(script("caption.py", self.src, "--transcribe", "--fast", "--json",
                                "-o", OUT / "pk_assumed.mp4", env=self.env(PATH=str(self.bin))).stdout)
        self.assertEqual(doc["transcription"]["engine"], "parakeet-mlx")
        self.assertEqual(doc["transcription"]["routing"], asr.ROUTING_ASSUMED_ENGLISH)
        self.assertEqual(len(_assumed(doc)), 1, doc.get("notes"))
        self.assertIn("--language", _assumed(doc)[0])
        self.assertTrue(doc["verified"], "the render itself is still verified; the note carries the doubt")
        fil = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                env=self.env(PATH=str(self.bin))).stdout)
        self.assertEqual(fil["filler"]["source"], "parakeet:parakeet-mlx")
        self.assertEqual(len(_assumed(fil)), 1, fil.get("notes"))
        self.assertIn("--filler-lang", _assumed(fil)[0])

    def test_no_language_goes_to_whisper_before_parakeet(self):
        """The same machine with whisper.cpp installed but no language it can detect: Whisper,
        which handles any language, takes the speech; the English-only model is not trusted with it."""
        d, home = self._with_whisper_cli(fail=False)
        try:
            env = self.env(PATH=str(d), HOME=str(home))
            doc = json.loads(script("caption.py", self.src, "--transcribe", "--mode", "mux", "--json",
                                    "-o", OUT / "pk_whisperfirst.mp4", env=env).stdout)
            fil = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                    env=env).stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(doc["transcription"], {"routing": asr.ROUTING_UNDETECTED_WHISPER, "engine": "whisper.cpp",
                                                "model": str(home / ".cache" / "whisper.cpp" / "ggml-base.bin"),
                                                "language": None})
        self.assertIn("Bonjour tout le monde", (OUT / "pk_whisperfirst.srt").read_text())
        self.assertFalse(_assumed(doc))
        self.assertEqual(fil["filler"]["source"], "whisper:whisper.cpp")
        self.assertEqual(fil["filler"]["transcription"]["routing"], asr.ROUTING_UNDETECTED_WHISPER)
        self.assertNotIn("notes", fil)

    def test_parakeet_runs_last_when_every_whisper_engine_fails(self):
        """Whisper went first and failed: Parakeet is still better than refusing, on English
        assumed, and the note says which fix applies."""
        self._no_host_whisper()
        d, home = self._with_whisper_cli(fail=True)
        try:
            env = self.env(PATH=str(d), HOME=str(home))
            doc = json.loads(script("caption.py", self.src, "--transcribe", "--mode", "mux", "--json",
                                    "-o", OUT / "pk_lastresort.mp4", env=env).stdout)
            fil = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                    env=env).stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(doc["transcription"]["engine"], "parakeet-mlx")
        self.assertEqual(doc["transcription"]["routing"], asr.ROUTING_LAST_RESORT)
        self.assertEqual(len(_assumed(doc)), 1, doc.get("notes"))
        self.assertIn("fix the Whisper engine", _assumed(doc)[0])
        self.assertEqual(fil["filler"]["source"], "parakeet:parakeet-mlx")
        self.assertEqual(fil["filler"]["transcription"]["routing"], asr.ROUTING_LAST_RESORT)
        self.assertEqual(len(_assumed(fil)), 1, fil.get("notes"))

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
