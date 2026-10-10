#!/usr/bin/env python3
"""Tests for the Parakeet speech engines.

    python3 tests/test_asr.py            # this group alone
    python3 tests/test_all.py            # every group

The Parakeet engines are driven through fake binaries on a PATH that holds nothing else, and a
faster_whisper the host may have installed is hidden from those runs, so these cases never depend on
what the host has installed.
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
from _fixtures import MediaFixtures, OUT, script, sh  # noqa: E402
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
        # ISO 639-2, the spelling caption.py's --language also tags a muxed track with
        self.assertEqual(asr.parakeet_route("auto", "eng", "a.wav", sh_, subprocess)[0], ["parakeet-mlx", "parakeet.cpp"])
        self.assertEqual(asr.parakeet_route("auto", "fr", "a.wav", sh_, subprocess)[0], [])
        self.assertEqual(asr.parakeet_route("auto", "fr", "a.wav", sh_, subprocess).skipped, ("parakeet-mlx",))
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
            self.assertEqual(asr._parakeet_model_for("parakeet-mlx", None, "eng"), asr.PARAKEET_MLX_DEFAULT_MODEL)
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
    writes what the named engine would have written where its arguments say. An engine in `fail`
    exits 1 the way the real one does: parakeet-mlx prints its error to stdout (through rich, with
    a download's progress bar on stderr), the others to stderr. `calls` records (argv, env)."""

    MLX_ERROR = ("Error loading model mlx-community/parakeet-tdt-0.6b-v2: cannot reach\n"
                 "huggingface.co (offline)\n\nparakeet-tdt-0.6b-v2 transcription complete.\n")

    def __init__(self, names, fail=()):
        self.names = set(names)
        self.fail = set(fail)
        self.calls = []

    def which(self, name):
        return f"/x/{name}" if name in self.names or name in ("ffmpeg", "ffprobe") else None

    def ran(self, exe):
        """The argv of every run of `exe`."""
        return [c for c, _ in self.calls if os.path.basename(c[0]) == exe]

    def run(self, cmd, **kw):
        self.calls.append((list(cmd), kw.get("env")))
        exe = os.path.basename(cmd[0])
        if exe in self.fail:
            if exe == "parakeet-mlx":
                return subprocess.CompletedProcess(cmd, 1, self.MLX_ERROR, "Fetching 5 files:   0%|          | 0/5\n")
            return subprocess.CompletedProcess(cmd, 1, "", f"{exe}: failed to load model\n")
        if exe == "parakeet-mlx":
            out = cmd[cmd.index("--output-dir") + 1]
            os.makedirs(out, exist_ok=True)
            # the real CLI names its file by --output-template, else $PARAKEET_OUTPUT_TEMPLATE
            template = (kw["env"] if kw.get("env") is not None else os.environ).get("PARAKEET_OUTPUT_TEMPLATE") or "{filename}"
            name = template.format(filename="audio", parent=out, date="20261009", index="1")
            Path(out, name + ".json").write_text(json.dumps(MLX_DOC), encoding="utf-8")
        elif exe == "whisper-cli" and "-osrt" in cmd:
            Path(cmd[cmd.index("-of") + 1] + ".srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,500\nBonjour tout le monde\n", encoding="utf-8")
        elif exe == "whisper-cli" and "--output-json-full" in cmd:
            Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [{"tokens": [
                {"text": " Bonjour", "offsets": {"from": 0, "to": 600}},
                {"text": " euh", "offsets": {"from": 700, "to": 900}}]}]}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")


class _BridgeHarness:
    """Runs the real bridge in process against _FakeEngines: no binary, no ffmpeg, every OS."""

    def _with(self, engines, call, faster_whisper=None, fail=(), env=None, fake=None):
        import _common
        fake = fake or _FakeEngines(engines, fail)
        stack = [mock.patch.object(_common, "run_analysis", lambda *a, **k: None),
                 mock.patch.object(shutil, "which", fake.which),
                 mock.patch.object(subprocess, "run", fake.run),
                 # None makes `import faster_whisper` fail; a stub module stands in for an install
                 mock.patch.dict(sys.modules, {"faster_whisper": faster_whisper}),
                 # a host ggml model in ~/.cache/whisper.cpp must not change the model named below
                 mock.patch.object(asr, "_whisper_cpp_model", lambda m: m),
                 mock.patch.dict(os.environ, dict({"PARAKEET_MODEL": "", "PARAKEET_CPP_MODEL": "", asr.ASR_ENGINE_ENV: ""},
                                                  **(env or {})))]
        for p in stack:
            p.start()
        try:
            return call()
        finally:
            for p in reversed(stack):
                p.stop()

    def _refusal(self, engines, call, **kw):
        """The one die() a bridge call ends in: (message, kind, extra fields)."""
        calls = []

        def fake_die(msg, code=1, kind="input", **extra):
            calls.append((msg, kind, extra))
            raise SystemExit(code)
        with mock.patch.object(asr, "die", fake_die), self.assertRaises(SystemExit):
            self._with(engines, call, **kw)
        self.assertEqual(len(calls), 1, calls)
        return calls[0]


def _faster_whisper_with_words(detected=None):
    """A faster_whisper that loads and returns one segment with word timings; `detected` is the
    language its transcribe() info reports (faster-whisper's info.language)."""
    mod = type(sys)("faster_whisper")

    class Word:
        def __init__(self, word, start, end):
            self.word, self.start, self.end = word, start, end

    class Segment:
        start, end, text = 0.0, 0.9, " Bonjour euh"
        words = [Word(" Bonjour", 0.0, 0.6), Word(" euh", 0.7, 0.9)]

    class WhisperModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, wav, language=None, word_timestamps=False):
            mod.languages.append(language)
            return iter([Segment()]), type("Info", (), {"language": detected})()
    mod.WhisperModel = WhisperModel
    mod.languages = []
    return mod


def _crashing_faster_whisper():
    """A faster_whisper whose model cannot be loaded -- what an offline first run looks like."""
    mod = type(sys)("faster_whisper")

    class WhisperModel:
        def __init__(self, *a, **k):
            raise RuntimeError("cannot fetch Systran/faster-whisper-base: offline")
    mod.WhisperModel = WhisperModel
    return mod


class WhisperFailureTests(_BridgeHarness, unittest.TestCase):
    """Undetected speech goes to Whisper first, so a Whisper engine that fails must read as a
    failure: a faster-whisper whose model would not load used to be swallowed in its thread and
    reported as "found no speech", which also kept Parakeet from ever being tried."""

    def test_a_crashed_faster_whisper_is_not_no_speech(self):
        """...and not "no engine found" either: it was found. The refusal names it and its own error."""
        with tempfile.TemporaryDirectory() as d:
            msg, kind, extra = self._refusal([], lambda: asr.transcribe_result("talk.mp4", os.path.join(d, "a.srt"), None, "base"),
                                             faster_whisper=_crashing_faster_whisper())
        self.assertEqual((kind, extra.get("reason"), extra.get("engine")), ("input", asr.ENGINE_FAILED_REASON, "faster-whisper"))
        self.assertNotIn("no local speech-to-text engine found", msg)
        self.assertNotIn("pip install", msg, "no install line for an engine that is installed")
        self.assertIn("faster-whisper found but failed: cannot fetch Systran/faster-whisper-base: offline", msg)
        self.assertEqual(extra["engines"], [{"engine": "faster-whisper", "reason": asr.ENGINE_FAILED_REASON,
                                             "detail": "found but failed: cannot fetch Systran/faster-whisper-base: offline"}])

    def test_parakeet_runs_last_after_a_crashed_faster_whisper(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._with(["parakeet-mlx"], lambda: asr.transcribe_result("talk.mp4", os.path.join(d, "a.srt"), None, "base"),
                             faster_whisper=_crashing_faster_whisper())
        self.assertEqual(run.engine, "parakeet-mlx")
        self.assertEqual(run.facts["routing"], asr.ROUTING_LAST_RESORT)
        self.assertEqual(run.notes, [asr.assumed_english_note(whisper_failed=True)])
        words = self._with(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4"),
                           faster_whisper=_crashing_faster_whisper())
        self.assertEqual((words.engine, len(words.words)), ("parakeet-mlx", 5))
        self.assertEqual(words.notes, [asr.assumed_english_note("--filler-lang", whisper_failed=True)])

    def test_a_crashed_faster_whisper_word_run_is_still_refused_by_name_without_parakeet(self):
        """No Parakeet to fall back on: silence.py keeps its "<engine> ran but produced no
        word-level timings" refusal, naming faster-whisper, as before."""
        run = self._with([], lambda: asr.transcribe_words_result("talk.mp4"), faster_whisper=_crashing_faster_whisper())
        self.assertEqual((run.engine, run.words), ("faster-whisper", []))

    def test_a_word_run_whose_last_resort_parakeet_also_fails_names_every_engine(self):
        """Parakeet was tried after the Whisper engine failed: the refusal must name both, not
        hand back the Whisper failure as if Parakeet had never run (CodeRabbit on #312)."""
        msg, kind, extra = self._refusal(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4"),
                                         faster_whisper=_crashing_faster_whisper(), fail=("parakeet-mlx",))
        self.assertEqual((kind, extra.get("reason")), ("input", asr.ENGINE_FAILED_REASON))
        self.assertEqual([e["engine"] for e in extra["engines"]], ["faster-whisper", "parakeet-mlx"])
        self.assertIn("--filler --transcribe", msg)


class TranscriptionStateTests(_BridgeHarness, unittest.TestCase):
    """Review of #305: the engine, routing and Parakeet word timings were handed back through
    module-level LAST_RUN / LAST_WORDS, which every call in one process shared (mcp/server.py,
    batch.py, a test). The calls now return them; nothing is kept in the module."""

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


class _SrtDir:
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.srt = os.path.join(self._dir.name, "a.srt")

    def tearDown(self):
        self._dir.cleanup()


class EngineRefusalTests(_SrtDir, _BridgeHarness, unittest.TestCase):
    """Review of #305: "no local speech-to-text engine found", with its install lines, was the refusal
    whenever nothing transcribed -- also when an installed engine had failed (a whisper.cpp with
    nothing after it, as in 2.5.1) or when auto had passed over an installed Parakeet engine for a
    language that is not English. It now means only that no engine was found; the others name each
    engine and why. A named engine is kind missing_tool only when it is not installed."""

    def test_nothing_installed_is_still_no_engine(self):
        msg, kind, _ = self._refusal([], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"))
        self.assertTrue(msg.startswith("no local speech-to-text engine found for --transcribe."), msg)
        self.assertEqual(kind, "input")
        msg, kind, _ = self._refusal([], lambda: asr.transcribe_words_result("talk.mp4"))
        self.assertTrue(msg.startswith("no local speech-to-text engine found for --filler --transcribe."), msg)

    def test_parakeet_passed_over_for_another_language_is_named(self):
        msg, kind, extra = self._refusal(["parakeet-mlx"], lambda: asr.transcribe_result("talk.mp4", self.srt, "fr", "base"))
        self.assertEqual((kind, extra["reason"], extra["engine"]), ("input", asr.ENGLISH_ONLY_REASON, "parakeet-mlx"))
        self.assertNotIn("no local speech-to-text engine found", msg)
        self.assertNotIn("uv tool install parakeet-mlx", msg, "it is installed")
        self.assertIn("parakeet-mlx is installed, but --engine auto runs Parakeet only for English speech, "
                      "and --language fr is not English", msg)
        self.assertIn("Whisper engine", extra["hint"])
        msg, _, extra = self._refusal(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4", "fr"))
        self.assertEqual(extra["reason"], asr.ENGLISH_ONLY_REASON)
        self.assertIn("--filler-lang fr is not English", msg)
        with mock.patch.object(asr, "detect_language", return_value="ja"):
            msg, _, _ = self._refusal(["parakeet-mlx"], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"))
        self.assertIn("the detected language ja is not English", msg)

    def test_a_failed_whisper_cpp_with_nothing_after_it_is_named(self):
        """2.5.1 told the caller to install whisper.cpp when whisper.cpp itself had failed."""
        msg, kind, extra = self._refusal(["whisper-cli"], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"),
                                         fail=["whisper-cli"])
        self.assertEqual((kind, extra["reason"], extra["engine"]), ("input", asr.ENGINE_FAILED_REASON, "whisper.cpp"))
        self.assertIn("whisper.cpp found but failed: whisper-cli: failed to load model", msg)
        self.assertNotIn("no local speech-to-text engine found", msg)

    def test_a_named_engine_that_is_installed_and_failed_is_not_missing_tool(self):
        """kind missing_tool (DEPENDENCY_MISSING, "install it") only when the engine is not there; the
        engine's own error is in the document -- parakeet-mlx prints it to stdout, not stderr."""
        msg, kind, extra = self._refusal(
            ["parakeet-mlx"], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base", engine="parakeet-mlx"),
            fail=["parakeet-mlx"])
        self.assertEqual((kind, extra["reason"], extra["engine"]), ("input", asr.ENGINE_FAILED_REASON, "parakeet-mlx"))
        self.assertEqual(extra["detail"], "found but failed: Error loading model mlx-community/parakeet-tdt-0.6b-v2: "
                                          "cannot reach huggingface.co (offline)")
        self.assertIn(extra["detail"], msg)
        _, kind, extra = self._refusal(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4", engine="parakeet-mlx"),
                                       fail=["parakeet-mlx"])
        self.assertEqual((kind, extra["reason"]), ("input", asr.ENGINE_FAILED_REASON))
        _, kind, extra = self._refusal(
            ["whisper-cli"], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base", engine="whisper.cpp"),
            fail=["whisper-cli"])
        self.assertEqual((kind, extra["engine"]), ("input", "whisper.cpp"))
        self.assertIn("failed to load model", extra["detail"])

    def test_a_named_engine_that_is_not_installed_is_missing_tool(self):
        for engine in asr.ASR_ENGINES:
            msg, kind, _ = self._refusal([], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base", engine=engine))
            self.assertEqual(kind, "missing_tool", engine)
            self.assertIn(f"--engine {engine} is not installed", msg)
            _, kind, _ = self._refusal([], lambda: asr.transcribe_words_result("talk.mp4", engine=engine))
            self.assertEqual(kind, "missing_tool", engine)

    def test_the_failure_line_reads_parakeet_mlx_errors_from_stdout(self):
        proc = subprocess.CompletedProcess([], 1, _FakeEngines.MLX_ERROR, "Fetching 5 files:   0%|\n")
        self.assertEqual(asr._failure_line(proc, errors_on_stdout=True),
                         "Error loading model mlx-community/parakeet-tdt-0.6b-v2: cannot reach huggingface.co (offline)")
        self.assertEqual(asr._failure_line(proc), "Fetching 5 files:   0%|")
        self.assertEqual(asr._failure_line(subprocess.CompletedProcess([], 1, "only stdout\n", "")), "only stdout")
        self.assertEqual(asr._failure_line(subprocess.CompletedProcess([], 1, "", "")), "?")


class WhisperLanguageTests(_SrtDir, _BridgeHarness, unittest.TestCase):
    """Review of #305: whisper.cpp was given -l only with --language, and its own default is -l en,
    so it decoded any speech as English -- on main for every run without --language, on the route
    that sends undetected speech to Whisper because Parakeet is English-only, and after auto's
    detector had named the language. It is now told the language, or "auto"."""

    @staticmethod
    def _l(fake):
        argv = fake.ran("whisper-cli")[-1]
        return argv[argv.index("-l") + 1]

    def test_no_language_asks_whisper_cpp_to_detect_it(self):
        for call in (lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"),
                     lambda: asr.transcribe_words_result("talk.mp4")):
            fake = _FakeEngines(["whisper-cli"])
            run = self._with([], call, fake=fake)
            self.assertEqual((run.engine, self._l(fake)), ("whisper.cpp", "auto"))
            self.assertIsNone(run.facts["language"], "whisper.cpp detected it; nothing named it")

    def test_the_detected_language_is_passed_on(self):
        fake = _FakeEngines(["whisper-cli", "parakeet-mlx"])
        with mock.patch.object(asr, "detect_language", return_value="ja"):
            run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"), fake=fake)
            self.assertEqual(self._l(fake), "ja")
            self.assertEqual(run.facts, {"routing": "auto: detected ja, not English", "detected_language": "ja",
                                         "engine": "whisper.cpp", "model": "base", "language": "ja"})
            self.assertEqual(fake.ran("parakeet-mlx"), [])
            fw = _faster_whisper_with_words()
            run = self._with(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4"), faster_whisper=fw)
            self.assertEqual((run.engine, fw.languages, run.facts["language"]), ("faster-whisper", ["ja"], "ja"))

    def test_undetected_speech_routed_to_whisper_lets_whisper_cpp_detect(self):
        fake = _FakeEngines(["whisper-cli", "parakeet-mlx"])
        with mock.patch.object(asr, "detect_language", return_value=None), \
                mock.patch.object(asr, "_whisper_ready", return_value=True):
            run = self._with([], lambda: asr.transcribe_words_result("talk.mp4"), fake=fake)
        self.assertEqual((run.facts["routing"], self._l(fake)), (asr.ROUTING_UNDETECTED_WHISPER, "auto"))

    def test_a_named_language_is_passed_as_given(self):
        fake = _FakeEngines(["whisper-cli"])
        run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, "fr", "base"), fake=fake)
        self.assertEqual((self._l(fake), run.facts["language"]), ("fr", "fr"))

    def test_auto_and_every_spelling_of_english_reach_the_engines_as_the_engines_take_them(self):
        """`--language auto` is the documented default spelled out, not a language; en-US, eng and
        English are English, and Whisper takes "en" where it would reject the others."""
        for given, passed in (("auto", None), ("AUTO", None), ("", None), ("en-US", "en"), ("eng", "en"),
                              ("English", "en"), ("EN", "en"), ("fr", "fr"), ("FR", "fr"),
                              ("ja-JP", "ja"), ("pt_BR", "pt"), ("zh-Hant", "zh"), ("jpn", "jpn")):
            self.assertEqual(asr.engine_language(given), passed, given)
        fake = _FakeEngines(["whisper-cli"])
        run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, "eng", "base"), fake=fake)
        self.assertEqual((self._l(fake), run.facts["language"]), ("en", "en"))
        fake = _FakeEngines(["whisper-cli"])
        run = self._with([], lambda: asr.transcribe_words_result("talk.mp4", "auto"), fake=fake)
        self.assertEqual((self._l(fake), run.facts["language"]), ("auto", None))
        # an installed Parakeet takes --language auto as the undetected route, not as "not English"
        fake = _FakeEngines(["parakeet-mlx"])
        with mock.patch.object(asr, "detect_language", return_value=None):
            run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, "auto", "base"), fake=fake)
        self.assertEqual((run.engine, run.facts["routing"]), ("parakeet-mlx", asr.ROUTING_ASSUMED_ENGLISH))

    def test_the_language_an_engine_decoded_is_reported_when_nothing_was_named(self):
        """faster-whisper's detected language and openai-whisper's JSON `language` are read back the way
        whisper.cpp's are: silence.py --filler picks its word list from it."""
        fw = _faster_whisper_with_words(detected="JA")
        run = self._with([], lambda: asr.transcribe_words_result("talk.mp4"), faster_whisper=fw)
        self.assertEqual((run.engine, run.facts["language"]), ("faster-whisper", "ja"))
        run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, None, "base"),
                         faster_whisper=_faster_whisper_with_words(detected="fr"))
        self.assertEqual((run.engine, run.facts["language"]), ("faster-whisper", "fr"))
        run = self._with([], lambda: asr.transcribe_words_result("talk.mp4", "de"),
                         faster_whisper=_faster_whisper_with_words(detected="ja"))
        self.assertEqual(run.facts["language"], "de", "a language that was named is the one reported")
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "audio.json"
            doc.write_text(json.dumps({"language": "no", "segments": []}), encoding="utf-8")
            self.assertEqual(asr._whisper_json_language(str(doc)), "no")

    def test_the_language_whisper_cpp_decoded_is_read_back_from_its_json(self):
        """With -l auto nobody named the language and the detector may be absent: whisper.cpp's own
        `result.language` is what lets a caller (silence.py --filler) pick the right word list."""
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "out.json"
            doc.write_text(json.dumps({"result": {"language": "FR"}, "transcription": []}), encoding="utf-8")
            self.assertEqual(asr._whisper_json_language(str(doc)), "fr")
            doc.write_text(json.dumps({"transcription": []}), encoding="utf-8")
            self.assertIsNone(asr._whisper_json_language(str(doc)))
            self.assertIsNone(asr._whisper_json_language(str(Path(d) / "missing.json")))

    def test_a_quantised_english_only_model_is_still_english_only(self):
        for name in ("ggml-base.en.bin", "base.en", "ggml-base.en-q5_1.bin", "tiny.en-q8_0", "/m/ggml-small.en-q5_1.bin",
                     "ggml-small.en-tdrz.bin"):
            self.assertTrue(asr._english_only_whisper_model(name), name)
        for name in ("ggml-base.bin", "base", "ggml-large-v3-q5_0.bin", "ggml-medium-q8_0.bin", "/models.en/ggml-base.bin"):
            self.assertFalse(asr._english_only_whisper_model(name), name)

    def test_an_english_only_whisper_model_is_no_engine_for_any_language(self):
        cli = mock.Mock(which=lambda n: "/x/whisper-cli" if n == "whisper-cli" else None)
        openai = mock.Mock(which=lambda n: "/x/whisper" if n == "whisper" else None)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sys.modules, {"faster_whisper": None}):
            en = Path(d) / "ggml-base.en.bin"
            en.write_bytes(b"")
            self.assertFalse(asr._whisper_ready(cli, str(en)))
            self.assertFalse(asr._whisper_ready(openai, "base.en"))
            self.assertTrue(asr._whisper_ready(openai, "base"))


class AutoRoutingFallbackTests(_SrtDir, _BridgeHarness, unittest.TestCase):
    """Review of #305: what --engine auto does when its first choice fails, and what it then says."""

    def test_whisper_after_a_failed_parakeet_says_why_it_ran(self):
        """The routing said why Parakeet was chosen, next to engine whisper.cpp."""
        fake = _FakeEngines(["parakeet-mlx", "whisper-cli"], fail=["parakeet-mlx"])
        run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, "en", "base"), fake=fake)
        self.assertEqual(run.engine, "whisper.cpp")
        self.assertEqual(run.facts["routing"], "auto: --language is English, no Parakeet engine transcribed it")
        words = self._with(["parakeet-mlx", "whisper-cli"], lambda: asr.transcribe_words_result("talk.mp4", "en"),
                           fail=["parakeet-mlx"])
        self.assertEqual((words.engine, words.facts["routing"]),
                         ("whisper.cpp", "auto: --language is English" + asr.ROUTING_PARAKEET_FAILED))

    def test_undetected_speech_reaches_faster_whisper_after_a_failed_whisper_cpp(self):
        """_whisper_ready() counted faster-whisper, but the word path stopped at the failed
        whisper.cpp and ran Parakeet on English assumed, saying no Whisper engine transcribed it."""
        fake = _FakeEngines(["whisper-cli", "parakeet-mlx"], fail=["whisper-cli"])
        run = self._with([], lambda: asr.transcribe_words_result("talk.mp4"), faster_whisper=_faster_whisper_with_words(),
                         fake=fake)
        self.assertEqual(run.engine, "faster-whisper")
        self.assertEqual([w["word"] for w in run.words], ["Bonjour", "euh"])
        self.assertEqual(run.facts["routing"], asr.ROUTING_UNDETECTED_WHISPER)
        self.assertEqual((run.notes, fake.ran("parakeet-mlx")), ([], []))

    def test_without_parakeet_a_failed_whisper_cpp_word_run_is_named_as_before(self):
        """No routing decision rests on faster-whisper here: the engine that ran and failed is the
        one silence.py's "no word-level timings" refusal names, as in 2.5.1."""
        run = self._with(["whisper-cli"], lambda: asr.transcribe_words_result("talk.mp4"),
                         faster_whisper=_faster_whisper_with_words(), fail=["whisper-cli"])
        self.assertEqual((run.engine, run.words), ("whisper.cpp", []))

    def test_a_multilingual_parakeet_model_assumes_no_english(self):
        v3 = "mlx-community/parakeet-tdt-0.6b-v3"
        run = self._with(["parakeet-mlx", "whisper-cli"], lambda: asr.transcribe_result("talk.mp4", self.srt, None, v3))
        self.assertEqual((run.engine, run.facts["model"]), ("parakeet-mlx", v3))
        self.assertEqual(run.facts["routing"], "auto: --model names a Parakeet model and the language is not detectable "
                                               "here; the Parakeet model is multilingual")
        self.assertEqual(run.notes, [])
        # the model from PARAKEET_MODEL, no Whisper engine: nothing assumed either
        run = self._with(["parakeet-mlx"], lambda: asr.transcribe_words_result("talk.mp4"), env={"PARAKEET_MODEL": v3})
        self.assertEqual(run.facts["model"], v3)
        self.assertNotIn("assumed English", run.facts["routing"])
        self.assertEqual(run.notes, [])

    def test_an_english_only_parakeet_model_named_with_model_points_at_the_model(self):
        """Not "no Whisper engine ... install one": a Whisper engine cannot load a Parakeet model."""
        run = self._with(["parakeet-mlx", "whisper-cli"],
                         lambda: asr.transcribe_result("talk.mp4", self.srt, None, asr.PARAKEET_MLX_DEFAULT_MODEL))
        self.assertEqual(run.facts["routing"], asr.ROUTING_PARAKEET_MODEL)
        self.assertEqual(run.notes, [asr.assumed_english_note(parakeet_model=True)])
        self.assertNotIn("install a Whisper engine", run.notes[0])

    def test_a_host_output_template_does_not_hide_parakeet_mlx_output(self):
        """parakeet-mlx names its file by $PARAKEET_OUTPUT_TEMPLATE; the bridge reads audio.json."""
        fake = _FakeEngines(["parakeet-mlx"])
        run = self._with([], lambda: asr.transcribe_result("talk.mp4", self.srt, "en", "base"), fake=fake,
                         env={"PARAKEET_OUTPUT_TEMPLATE": "{filename}_{date}"})
        self.assertEqual(run.engine, "parakeet-mlx")
        (_, env), = fake.calls
        self.assertNotIn("PARAKEET_OUTPUT_TEMPLATE", env)


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

    def test_the_capability_fix_hint_says_the_same(self):
        """_capability_fix_hint() is the `fix` doctor gives for a missing *required* capability; no
        tool requires a speech engine today, so doctor lists external:* under missing_optional
        without it. The text is still kept true for the day one does."""
        import _contract
        fix = _contract._capability_fix_hint("external:parakeet")
        for words in ("first run", "Hugging Face", asr.PARAKEET_MLX_DEFAULT_MODEL, "never uploaded"):
            self.assertIn(words, fix)

    def test_the_network_claim_matches_where_each_engine_runs(self):
        """Review of #305: "the skill itself opens no network connection" was false for faster-whisper,
        a library the skill runs in its own process, whose first run downloads its model. And
        "doctor's fix line" was named as a place that says so, which doctor never shows for an
        optional capability."""
        import _contract
        root = Path(__file__).resolve().parent.parent
        contract_md = (root / "docs" / "contract.md").read_text(encoding="utf-8")
        decisions = (root / "docs" / "design-decisions.md").read_text(encoding="utf-8")
        self.assertNotIn("skill itself opens no network connection", contract_md)
        self.assertIn("faster-whisper is a Python library the skill runs inside its own process", " ".join(contract_md.split()))
        self.assertNotIn("(the skill's own process) stay true", decisions)
        for text in (decisions, (root / "CHANGELOG.md").read_text(encoding="utf-8")):
            self.assertNotIn("doctor's fix line", text)
            self.assertNotIn("`doctor`'s fix line", text)
        # the engines it runs are listed where the contract says what it runs
        execution = _contract.build(detect=False)["execution"]
        ran = execution["subprocess"]
        for exe in ("whisper-cli", "whisper-cpp", "parakeet-mlx", "parakeet-cli", "whisper"):
            self.assertIn(exe, ran)
        # ...and the machine-readable contract says which engine downloads, from which process: a
        # caller that read only `network: false` took a first faster-whisper run for network-free
        # (CodeRabbit on #312)
        downloads = execution["model_downloads"]
        self.assertEqual(set(downloads["in_process"]), {"faster-whisper"})
        self.assertEqual(set(downloads["child_process"]), {"parakeet-mlx", "openai-whisper"})
        self.assertEqual(set(downloads["none"]), {"whisper.cpp", "parakeet.cpp"})
        self.assertIn("model_downloads", contract_md)

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
        # A PATH hides the host's engine binaries, but not a Python module: the tools would import a
        # faster_whisper the host has installed (a Mac where Parakeet is used often has one) and
        # Whisper would then go first. This sitecustomize makes `import faster_whisper` fail in
        # every subprocess, as on CI.
        cls.shim = Path(tempfile.mkdtemp(prefix="ffskill_nofw_"))
        (cls.shim / "sitecustomize.py").write_text("import sys\nsys.modules['faster_whisper'] = None\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.bin, ignore_errors=True)
        shutil.rmtree(cls.shim, ignore_errors=True)
        super().tearDownClass()

    def env(self, **extra):
        e = dict(os.environ, PATH=f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", PARAKEET_CPP_MODEL=str(self.gguf),
                 PYTHONPATH=os.pathsep.join(p for p in (str(self.shim), os.environ.get("PYTHONPATH")) if p))
        e.update(extra)
        return e

    def test_a_host_faster_whisper_is_hidden_from_the_tools(self):
        """With a faster_whisper importable on the host (a stub package on PYTHONPATH stands in for
        one), the tools still cannot import it."""
        stub = Path(tempfile.mkdtemp(prefix="ffskill_fwstub_"))
        try:
            (stub / "faster_whisper").mkdir()
            (stub / "faster_whisper" / "__init__.py").write_text("class WhisperModel:\n    pass\n", encoding="utf-8")
            env = self.env()
            env["PYTHONPATH"] += os.pathsep + str(stub)
            probe = sh(sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from _common import asr; "
                       "print(asr._module_importable('faster_whisper'))", str(Path(__file__).resolve().parent.parent / "scripts"),
                       env=env)
        finally:
            shutil.rmtree(stub, ignore_errors=True)
        self.assertEqual(probe.stdout.strip(), "False")

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
        cli.write_text(f"#!{sys.executable}\nFAIL = {fail!r}\nARGS = {str(home / 'whisper-args.json')!r}\n" + textwrap.dedent("""
            import json, sys
            a = sys.argv[1:]
            if "-dl" not in a:
                json.dump(a, open(ARGS, "w"))
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
        args = home / "whisper-args.json"
        try:
            env = self.env(PATH=str(d), HOME=str(home))
            doc = json.loads(script("caption.py", self.src, "--transcribe", "--mode", "mux", "--json",
                                    "-o", OUT / "pk_whisperfirst.mp4", env=env).stdout)
            caption_args = json.loads(args.read_text())
            fil = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                    env=env).stdout)
            filler_args = json.loads(args.read_text())
        finally:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(doc["transcription"], {"routing": asr.ROUTING_UNDETECTED_WHISPER, "engine": "whisper.cpp",
                                                "model": str(home / ".cache" / "whisper.cpp" / "ggml-base.bin"),
                                                "language": None})
        # whisper.cpp's own default is -l en: "handles any language" only holds when it is told to detect
        for argv in (caption_args, filler_args):
            self.assertEqual(argv[argv.index("-l") + 1], "auto", argv)
        self.assertIn("Bonjour tout le monde", (OUT / "pk_whisperfirst.srt").read_text())
        self.assertFalse(_assumed(doc))
        self.assertEqual(fil["filler"]["source"], "whisper:whisper.cpp")
        self.assertEqual(fil["filler"]["transcription"]["routing"], asr.ROUTING_UNDETECTED_WHISPER)
        self.assertNotIn("notes", fil)

    def test_parakeet_runs_last_when_every_whisper_engine_fails(self):
        """Whisper went first and failed: Parakeet is still better than refusing, on English
        assumed, and the note says which fix applies."""
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
        """Parakeet is installed and auto passes it over for French: the refusal says that, not
        "no local speech-to-text engine found" with a line telling the caller to install it."""
        proc = script("caption.py", self.src, "--transcribe", "--language", "fr", "--fast", "--json",
                      "-o", OUT / "pk_fr.mp4", env=self.env(PATH=str(self.bin)), expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["error"]["kind"], doc["reason"], doc["engine"]), ("input", asr.ENGLISH_ONLY_REASON, "parakeet-mlx"))
        self.assertNotIn("no local speech-to-text engine found", doc["error"]["message"])
        self.assertIn("--language fr is not English", doc["error"]["message"])
        self.assertEqual([e["engine"] for e in doc["engines"]], ["parakeet-mlx", "parakeet.cpp"])

    def test_a_named_engine_that_failed_says_why_in_the_document(self):
        """parakeet-mlx prints its errors to stdout and exits 1: the failure document carries that
        line (a JSON caller never sees the log), and the kind is not missing_tool -- it is installed."""
        broken = Path(tempfile.mkdtemp(prefix="ffskill_mlxerr_"))
        try:
            for name in os.listdir(self.bin):
                if name != "parakeet-mlx":
                    os.symlink(self.bin / name, broken / name)
            mlx = broken / "parakeet-mlx"
            mlx.write_text("#!/bin/sh\necho 'Fetching 5 files:   0%|' >&2\n"
                           "echo 'Error loading model mlx-community/parakeet-tdt-0.6b-v2: Metal device lost'\nexit 1\n")
            mlx.chmod(0o755)
            proc = script("caption.py", self.src, "--transcribe", "--engine", "parakeet-mlx", "--fast", "--json",
                          "-o", OUT / "pk_mlxerr.mp4", env=self.env(PATH=str(broken)), expect_fail=True)
        finally:
            shutil.rmtree(broken, ignore_errors=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["error"]["kind"], doc["reason"], doc["engine"]), ("input", asr.ENGINE_FAILED_REASON, "parakeet-mlx"))
        self.assertNotEqual(doc["error"]["code"], "DEPENDENCY_MISSING")
        self.assertEqual(doc["detail"], "found but failed: Error loading model mlx-community/parakeet-tdt-0.6b-v2: Metal device lost")

    def test_silence_filler_words_from_parakeet(self):
        doc = json.loads(script("silence.py", self.src, "--filler", "--transcribe", "--filler-list", "--json",
                                "--engine", "parakeet.cpp", env=self.env()).stdout)
        self.assertEqual(doc["filler"]["source"], "parakeet:parakeet.cpp")
        self.assertEqual([r["word"] for r in doc["filler"]["removed"]], ["um"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
