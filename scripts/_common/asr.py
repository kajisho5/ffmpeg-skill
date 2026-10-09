"""The optional local speech-to-text bridge, and the SRT the rest of the skill reads and writes.

No speech engine is ever required. Nothing here runs unless a caller asked for a transcript:
`caption.py --transcribe` and `silence.py --filler --transcribe` share this one engine probe, so
the "no engine found" message, its install lines and its exit code are stated once rather than
copied per tool. What a call used (engine, model, routing, words, notes) comes back in its
Transcription, never in module state. This module is neither ffprobe nor a decision, which is
why it is its own file.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from _common.decision import fmt_srt_time, parse_time
from _common.emit import die, info
from _common.runner import read_text_or_die

# The engines this skill knows how to drive, and how to install each -- one string, so every
# tool that needs a transcript refuses in the same words. The two Parakeet engines are
# English-first (the default v2 model is English-only): under `--engine auto` they run only for
# English speech and the Whisper engines take every other language.
PARAKEET_ENGINES = ("parakeet-mlx", "parakeet.cpp")
WHISPER_ENGINES = ("whisper.cpp", "faster-whisper", "openai-whisper")
ASR_ENGINES = PARAKEET_ENGINES + WHISPER_ENGINES
ENGINE_CHOICES = ("auto",) + ASR_ENGINES
ASR_ENGINE_ENV = "FFMPEG_SKILL_ASR_ENGINE"
PARAKEET_MLX_DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
# Every engine transcribes on this machine: the audio is never uploaded. Three of them fetch
# their model weights the first time they run (the skill itself downloads nothing), which the
# hint says, so "offline" is never promised for a first run that is not.
ASR_INSTALL_HINT = (
    "Install one (each transcribes on this machine; the audio never leaves it):\n"
    "  parakeet-mlx:   uv tool install parakeet-mlx   (Apple Silicon; English; the first run\n"
    "                  downloads the model from Hugging Face, " + PARAKEET_MLX_DEFAULT_MODEL + ")\n"
    "  parakeet.cpp:   parakeet-cli from github.com/mudler/parakeet.cpp releases, plus a\n"
    "                  tdt-0.6b-v2 .gguf in ~/.cache/parakeet.cpp/ (English)\n"
    "  whisper.cpp:    brew install whisper-cpp   (then download a model: ggml-base.bin)\n"
    "  faster-whisper: pip install faster-whisper   (the first run downloads its model)\n"
    "  openai-whisper: pip install openai-whisper   (the first run downloads its model)")


class Transcription:
    """What one transcription produced, and what produced it.

    transcribe_result() and transcribe_words_result() return one instead of leaving it in module
    state, so two transcriptions in one process (mcp/server.py, batch.py, a test) can never read
    each other's engine, words or routing.

      cues    [(start, end, text)]: what transcribe_result() wrote to the SRT (a Parakeet word
              run fills them too; a whisper word run leaves them [])
      words   [{word, start, end}]: transcribe_words_result()'s word timings; from
              transcribe_result(), a Parakeet engine's word timings for --karaoke ([] for a
              whisper engine, whose word timings are read from a JSON next to the SRT instead)
      engine  the engine that produced them, or None
      facts   the result document's `transcription` block, in its key order:
              {routing, detected_language?, engine, model, language}
      notes   sentences for the result document's top-level `notes`
    """

    def __init__(self, cues: Optional[List[Tuple[float, float, str]]] = None,
                 words: "Optional[List[Dict[str, Any]]]" = None, engine: Optional[str] = None,
                 facts: Optional[Dict[str, Any]] = None, notes: Optional[List[str]] = None) -> None:
        self.cues: List[Tuple[float, float, str]] = list(cues or [])
        self.words: "List[Dict[str, Any]]" = [dict(w) for w in (words or [])]
        self.engine = engine
        self.facts: Dict[str, Any] = dict(facts or {})
        self.notes: List[str] = list(notes or [])

    def __repr__(self) -> str:
        return (f"Transcription(engine={self.engine!r}, cues={len(self.cues)}, words={len(self.words)}, "
                f"facts={self.facts!r}, notes={self.notes!r})")


def parse_srt(path: str) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    block: List[str] = []
    content = read_text_or_die(path, "--srt").lstrip("\ufeff").replace("\r\n", "\n") + "\n\n"
    for line in content.split("\n"):
        if line.strip():
            block.append(line)
            continue
        if block:
            times = next((b for b in block if "-->" in b), None)
            if times:
                a, b = times.split("-->")
                text = "\n".join(block[block.index(times) + 1:]).strip()
                try:
                    cues.append((parse_time(a), parse_time(b), text))
                except ValueError as e:  # includes MissingFpsError: SRT timings are hh:mm:ss,ms, never frames
                    die(f"{path}: cannot read the timing line {times.strip()!r}: {e}")
            block = []
    if not cues:
        die(f"no cues found in {path}")
    return cues


NO_SPEECH_REASON = "no_speech"


def die_no_speech(engine: str, video: str) -> None:
    """An engine ran and heard nothing: kind input, `reason: "no_speech"`, naming the engine and
    the input -- not the "no engine found" refusal (one was found) and not "no cues found in"
    the engine's own temporary SRT (a path the caller never gave and that is already deleted)."""
    die(f"{engine} found no speech in {video}", kind="input", reason=NO_SPEECH_REASON, engine=engine,
        hint="check that the input (and --audio-stream) carries the speech, or write the cues by hand with --text")


def _engine_cues(srt: str, engine: str, video: str) -> List[Tuple[float, float, str]]:
    """The cues of an SRT an engine wrote; an SRT with no cue in it is die_no_speech()."""
    try:
        text = Path(srt).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if "-->" not in text:
        die_no_speech(engine, video)
    return parse_srt(srt)


def write_srt(cues: List[Tuple[float, float, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (s, e, t) in enumerate(cues, 1):
            # A blank line is SRT's own block separator (index/timecode/text, blank, next block).
            # Cue text can contain one -- parse_text_cues() turns a bare "|" into "\n", so a source
            # line with two adjacent pipes ("a||b") becomes "a\n\nb" -- and writing that blank line
            # raw would split one cue into two malformed half-blocks (the second missing its own
            # index/timecode). Collapse any run of blank lines within the cue text to a single
            # newline so the cue's own text can never fake the format's block boundary.
            t = re.sub(r"\n{2,}", "\n", t).strip("\n")
            fh.write(f"{i}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{t}\n\n")


def transcribe_result(video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int = 0,
                      engine: Optional[str] = None) -> Transcription:
    """Optional local ASR bridge: the SRT written to `out_srt`, and a Transcription saying what
    produced it. `engine` (else $FFMPEG_SKILL_ASR_ENGINE, else auto) picks the engine; auto tries
    Parakeet (parakeet-mlx, parakeet.cpp) for English speech, then whisper-cli / main
    (whisper.cpp), faster-whisper (python), whisper (openai-whisper CLI). No engine installed ->
    clear error with install hints; the skill never depends on one."""
    import shutil
    import subprocess
    import tempfile
    from _common import require_tool
    ffmpeg = require_tool("ffmpeg")
    wanted = requested_engine(engine)
    tmpdir = tempfile.mkdtemp(prefix="ffskill_asr_")
    try:
        return _transcribe_in(tmpdir, video, out_srt, language, model, audio_stream, ffmpeg, shutil, subprocess, wanted)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def transcribe(video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int = 0,
               engine: Optional[str] = None) -> List[Tuple[float, float, str]]:
    """transcribe_result()'s cues alone: the call shape caption.transcribe has always had. A caller
    that reports which engine ran (caption.py does) calls transcribe_result() instead."""
    return transcribe_result(video, out_srt, language, model, audio_stream, engine).cues


def _asr_run(cmd: List[str], subprocess, name: str) -> "subprocess.CompletedProcess":
    """Run a speech-to-text engine under the same wall-clock limit as an ffmpeg call."""
    from _common import STATE, die
    limit = STATE.timeout or None
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=limit)
    except subprocess.TimeoutExpired:
        die(f"{name} exceeded the {limit:.0f} s time limit and was killed; raise --timeout for a long recording",
            code=124, kind="timeout")
    return None  # unreachable


def assumed_english_note(language_flag: str = "--language", whisper_failed: bool = False) -> str:
    """The top-level `notes` line for a transcript the English-only Parakeet model made from speech
    whose language nobody named and nothing here could detect."""
    fix = ("or fix the Whisper engine that failed (the log names it)" if whisper_failed else
           "or install a Whisper engine, which --engine auto then uses for speech it cannot identify")
    return (f"English was assumed: no {language_flag} was given and the spoken language could not be "
            "detected here (that needs whisper.cpp with a multilingual ggml model), so the English-only "
            "Parakeet model made this transcript. If the speech is not English the transcript is wrong: "
            f"name the language with {language_flag}, " + fix)


def _parakeet_attempt(engines: "List[str]", facts: Dict[str, Any], wanted: str, language: Optional[str],
                      wav: str, tmpdir: str, model: Optional[str], shutil, subprocess, video: str,
                      language_flag: str, need_words: bool = False) -> Optional[Tuple[Transcription, str]]:
    """(Transcription, the model's file name) from the first of `engines` that transcribes, or None.

    Under --engine auto with no language named or detected, the English-only model ran on an
    assumption: the Transcription then carries assumed_english_note(), and a warning is logged.
    `need_words`: an engine whose cues read but whose word times do not is passed over (silence.py
    --filler can cut nothing on cues), unless it was asked for by name."""
    for eng in engines:
        got = run_parakeet(eng, wav, tmpdir, model, language, shutil, subprocess, video)
        if got and need_words and not got[1] and wanted not in PARAKEET_ENGINES:
            # cues read but no word times (a caption could use them; this caller cannot); a
            # named engine keeps its own "no word-level timings" refusal instead
            info(f"{eng} gave cues but no readable word timings; trying the next engine")
            got = None
        if not got:
            continue
        cues, words, chosen = got
        run = Transcription(cues=cues, words=words, engine=eng,
                            facts=dict(facts, engine=eng, model=chosen, language=language or facts.get("detected_language")))
        if wanted == "auto" and not language and not facts.get("detected_language"):
            run.notes.append(assumed_english_note(language_flag, whisper_failed=facts.get("routing") == ROUTING_LAST_RESORT))
            info("warning: " + run.notes[-1])
        return run, os.path.basename(chosen)
    return None


def _transcribe_in(tmpdir: str, video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int,
                   ffmpeg: str, shutil, subprocess, wanted: str = "auto") -> Transcription:
    from _common import run_analysis, STATE, die
    wav = os.path.join(tmpdir, "audio.wav")
    # A wav in our own temp dir: a measurement input for the engine, not a deliverable, so it
    # is not a run() call (no --dry-run gate, not recorded), but it keeps the time limit and
    # reports an unreadable input as kind ffmpeg instead of a CalledProcessError traceback.
    run_analysis([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video,
                  "-map", f"0:a:{audio_stream}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])

    def parakeet(engines: "List[str]", facts: Dict[str, Any]) -> Optional[Transcription]:
        done = _parakeet_attempt(engines, facts, wanted, language, wav, tmpdir, model, shutil, subprocess, video, "--language")
        if not done:
            return None
        run, model_name = done
        info(f"transcribed with {run.engine} (model {model_name})")
        write_srt(run.cues, out_srt)
        return run

    # 0. Parakeet (English), when auto-routing picks it or it was asked for by name
    route = parakeet_route(wanted, language, wav, shutil, subprocess, model)
    done = parakeet(route.first, route.facts)
    if done:
        return done
    if wanted in PARAKEET_ENGINES:
        die(f"--engine {wanted} could not transcribe {video} (see the line above)", kind="missing_tool",
            hint="install it (see --help), or use --engine auto to fall back to Whisper")
    facts = route.facts
    # 1. whisper.cpp
    cli = _whisper_cpp_cli(shutil) if wanted in ("auto", "whisper.cpp") else None
    if cli:
        model_path = _whisper_cpp_model(model)
        base = os.path.join(tmpdir, "out")
        cmd = [cli, "-m", model_path, "-f", wav, "-osrt", "-of", base]
        if language:
            cmd += ["-l", language]
        proc = _asr_run(cmd, subprocess, "whisper.cpp")
        if proc.returncode == 0 and os.path.exists(base + ".srt"):
            info(f"transcribed with whisper.cpp ({os.path.basename(cli)}, model {os.path.basename(model_path)})")
            cues = _engine_cues(base + ".srt", "whisper.cpp", video)
            write_srt(cues, out_srt)
            return Transcription(cues=cues, engine="whisper.cpp",
                                 facts=dict(facts, engine="whisper.cpp", model=model_path, language=language))
        info("whisper.cpp found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
    # 2. faster-whisper (python package)
    try:
        if wanted not in ("auto", "faster-whisper"):
            raise ImportError
        from faster_whisper import WhisperModel  # type: ignore
        import threading
        result: list = []
        crashed: list = []

        def work() -> None:
            try:
                m = WhisperModel(model, device="cpu", compute_type="int8")
                segments, _ = m.transcribe(wav, language=language, word_timestamps=False)
                result.extend((seg.start, seg.end, seg.text.strip()) for seg in segments if seg.text.strip())
            except Exception as exc:  # noqa: BLE001 -- a model that would not load or run: a failed engine
                crashed.append(exc)

        # An in-process engine gets the same wall-clock limit as the CLI engines and ffmpeg.
        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(STATE.timeout or None)
        if t.is_alive():
            die(f"faster-whisper exceeded the {STATE.timeout:.0f} s time limit; raise --timeout for a long recording", code=124, kind="timeout")
        if crashed:
            # it failed (a model it could not fetch or load), which is not "found no speech":
            # move on to the next engine, as a failed whisper.cpp does
            info(f"faster-whisper found but failed: {crashed[0]!s}"[:240])
        else:
            cues = list(result)
            if not cues:
                die_no_speech("faster-whisper", video)
            info("transcribed with faster-whisper")
            write_srt(cues, out_srt)
            return Transcription(cues=cues, engine="faster-whisper",
                                 facts=dict(facts, engine="faster-whisper", model=model, language=language))
    except ImportError:
        pass
    # 3. openai-whisper CLI
    if wanted in ("auto", "openai-whisper") and shutil.which("whisper"):
        cmd = ["whisper", wav, "--model", model, "--output_format", "srt", "--output_dir", tmpdir]
        if language:
            cmd += ["--language", language]
        proc = _asr_run(cmd, subprocess, "openai-whisper")
        srt = os.path.join(tmpdir, "audio.srt")
        if proc.returncode == 0 and os.path.exists(srt):
            info("transcribed with openai-whisper")
            cues = _engine_cues(srt, "openai-whisper", video)
            write_srt(cues, out_srt)
            return Transcription(cues=cues, engine="openai-whisper",
                                 facts=dict(facts, engine="openai-whisper", model=model, language=language))
    # 4. Parakeet after all, when the language was never known and every Whisper engine failed
    if route.last:
        info("no Whisper engine transcribed it; trying Parakeet with English assumed")
        done = parakeet(list(route.last), {"routing": ROUTING_LAST_RESORT})
        if done:
            return done
    if wanted != "auto":
        die(f"--engine {wanted} is not installed or could not transcribe {video}", kind="missing_tool",
            hint="install it (see --help), or use --engine auto to use whichever engine is installed")
    die_no_engine("Or write the cues by hand with --text cues.txt (see format above).")
    return Transcription()


def die_no_engine(alternative: str, flag: str = "--transcribe") -> None:
    """The one "no local speech-to-text engine" refusal, in the one set of words.

    kind: input, exit 1, and the three install lines -- caption.py and silence.py both land here
    rather than each spelling out its own version of the same missing dependency.
    """
    die(f"no local speech-to-text engine found for {flag}.\n" + ASR_INSTALL_HINT + "\n" + alternative,
        kind="input")


def whisper_word_timings(srt_path: Optional[str]) -> List[Tuple[float, float, str]]:
    """Word timings from a whisper JSON transcript sitting next to the SRT, if there is one.

    whisper (and faster-whisper, and whisper.cpp's --output-json) can emit per-word start/end
    times; when they are there, --karaoke should follow the real speech instead of splitting the
    cue evenly. Looked for as <stem>.json and <stem>.words.json next to the SRT, in either the
    {"segments": [{"words": [{"word": ..., "start": ..., "end": ...}]}]} or a bare
    {"words": [...]} shape. Anything unreadable is simply "no word timings".
    """
    if not srt_path:
        return []
    stem = os.path.splitext(srt_path)[0]
    for cand in (stem + ".words.json", stem + ".json"):
        if not os.path.exists(cand):
            continue
        try:
            data = json.loads(Path(cand).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        raw = []
        if isinstance(data, dict):
            raw = list(data.get("words") or [])
            for seg in data.get("segments") or []:
                raw.extend((seg or {}).get("words") or [])
        words = []
        for w in raw:
            try:
                text = str(w.get("word") or w.get("text") or "").strip()
                if text:
                    words.append((float(w["start"]), float(w["end"]), text))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        if words:
            info(f"karaoke: word timings from {os.path.basename(cand)} ({len(words)} words)")
            return sorted(words)
    return []


# ------------------------------------------------------- word-level timings (1.17)
#
# transcribe() above produces an SRT, which is all --transcribe on caption.py ever needed: a cue
# has a start and an end and that is what gets burnt in. silence.py --filler needs something
# stricter -- a start and an end PER WORD -- and no amount of reading an SRT back produces one.
# Each engine has its own flag for it, and each writes a different shape, so each is driven and
# parsed here rather than in the tool.


def _words_from_whisper_cpp_json(path: str) -> "List[Dict[str, Any]]":
    """whisper.cpp --output-json-full: transcription[].tokens[] with offsets in MILLISECONDS.

    Token text carries leading spaces and the model's special tokens ([_BEG_], [_TT_123]); those
    are dropped, and a token that is a word continuation (no leading space) is glued onto the
    previous word so "un" + "believable" is one word with one span, not two.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: "List[Dict[str, Any]]" = []
    for seg in (doc.get("transcription") or []):
        for tok in (seg.get("tokens") or []):
            text = str(tok.get("text") or "")
            if not text.strip() or text.strip().startswith("[_"):
                continue
            offsets = tok.get("offsets") or {}
            try:
                start, end = float(offsets["from"]) / 1000.0, float(offsets["to"]) / 1000.0
            except (KeyError, TypeError, ValueError):
                continue
            if out and not text.startswith(" "):
                out[-1]["word"] += text
                out[-1]["end"] = end
            else:
                out.append({"word": text.strip(), "start": start, "end": end})
    return [w for w in out if w["word"].strip()]


def _words_from_openai_whisper_json(path: str) -> "List[Dict[str, Any]]":
    """openai-whisper --word_timestamps True --output_format json: segments[].words[]."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: "List[Dict[str, Any]]" = []
    for seg in (doc.get("segments") or []):
        for w in (seg.get("words") or []):
            try:
                out.append({"word": str(w.get("word") or w.get("text") or "").strip(),
                            "start": float(w["start"]), "end": float(w["end"])})
            except (KeyError, TypeError, ValueError):
                continue
    return [w for w in out if w["word"]]


# ------------------------------------------------------- Parakeet engines and routing


def _words_from_parakeet_mlx_json(path: str) -> "List[Dict[str, Any]]":
    """parakeet-mlx --output-format json: sentences[].tokens[] of SUB-word pieces, times in seconds.

    A piece with a leading space starts a word; a bare " " piece is a separator, so the piece
    after it starts a word too (" m" "is" "ter" " " "Q" "u" "il" "ter" -> "mister", "Quilter").
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: "List[Dict[str, Any]]" = []
    for sent in _dicts(doc.get("sentences")) if isinstance(doc, dict) else []:
        brk = True  # every sentence starts a new word
        for tok in _dicts(sent.get("tokens")):
            text = str(tok.get("text") or "")
            try:
                start, end = float(tok["start"]), float(tok["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not text.strip():
                brk = True
                continue
            if brk or text.startswith(" ") or not out:
                out.append({"word": text.strip(), "start": start, "end": end})
            else:
                out[-1]["word"] += text
                out[-1]["end"] = end
            brk = False
    return [w for w in out if w["word"]]


def _cues_from_parakeet_mlx_json(path: str) -> List[Tuple[float, float, str]]:
    """parakeet-mlx's own sentence segmentation, as cues."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cues: List[Tuple[float, float, str]] = []
    for sent in _dicts(doc.get("sentences")) if isinstance(doc, dict) else []:
        try:
            text = str(sent.get("text") or "").strip()
            if text:
                cues.append((float(sent["start"]), float(sent["end"]), text))
        except (KeyError, TypeError, ValueError):
            continue
    return cues


def _dicts(value: Any) -> "List[Dict[str, Any]]":
    """The dict items of a JSON list; anything else (a number, a string, null) is no items. The
    engines' JSON is parsed defensively: a wrong shape yields no words, never a traceback."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _words_from_parakeet_cpp_json(text: str) -> "List[Dict[str, Any]]":
    """parakeet-cli transcribe --json: {"words": [{"w", "start", "end", "conf"}]}, times in seconds."""
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    out: "List[Dict[str, Any]]" = []
    for w in _dicts(doc.get("words")) if isinstance(doc, dict) else []:
        try:
            word = str(w.get("w") or w.get("word") or "").strip()
            if word:
                out.append({"word": word, "start": float(w["start"]), "end": float(w["end"])})
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


# Cue boundaries for an engine that gives words but no sentences (parakeet.cpp): the same limits
# parakeet-mlx's own segmentation is run with, so both Parakeet engines cut cues alike.
CUE_MAX_SECONDS = 7.0
CUE_MAX_CHARS = 84
CUE_GAP_SECONDS = 0.8


def cues_from_words(words: "List[Dict[str, Any]]") -> List[Tuple[float, float, str]]:
    """Group timed words into cues: a cue ends after sentence-final punctuation, before a pause of
    CUE_GAP_SECONDS or more, or before it would pass CUE_MAX_SECONDS / CUE_MAX_CHARS."""
    cues: List[Tuple[float, float, str]] = []
    cur: "List[Dict[str, Any]]" = []

    def flush() -> None:
        if cur:
            cues.append((cur[0]["start"], cur[-1]["end"], " ".join(w["word"] for w in cur)))
            cur.clear()

    for w in words:
        if cur:
            text_len = len(" ".join(x["word"] for x in cur)) + 1 + len(w["word"])
            if (w["start"] - cur[-1]["end"] >= CUE_GAP_SECONDS or w["end"] - cur[0]["start"] > CUE_MAX_SECONDS
                    or text_len > CUE_MAX_CHARS):
                flush()
        cur.append(w)
        if w["word"][-1:] in ".?!":
            flush()
    flush()
    return cues


def requested_engine(engine: Optional[str]) -> str:
    """--engine, else $FFMPEG_SKILL_ASR_ENGINE, else "auto"; an unknown env value is refused."""
    name = engine or os.environ.get(ASR_ENGINE_ENV, "").strip() or "auto"
    if name not in ENGINE_CHOICES:
        die(f"{ASR_ENGINE_ENV}={name!r} is not a speech engine this skill drives (one of {', '.join(ENGINE_CHOICES)})",
            kind="input", hint=f"unset {ASR_ENGINE_ENV} or set it to one of {', '.join(ENGINE_CHOICES)}")
    return name


def _is_english(language: Optional[str]) -> bool:
    return (language or "").lower().split("-")[0].split("_")[0] in ("en", "english")


def _whisper_cpp_cli(shutil) -> Optional[str]:
    cli = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if not cli:
        # older whisper.cpp builds ship the binary as plain `main`; accept it only when it lives
        # in a directory that names whisper, so an unrelated /usr/bin/main is never run
        main_bin = shutil.which("main")
        if main_bin and "whisper" in os.path.dirname(os.path.realpath(main_bin)).lower():
            cli = main_bin
    return cli


def _whisper_cpp_model(model: str) -> str:
    if os.path.exists(model):
        return model
    for cand in (os.path.expanduser(f"~/.cache/whisper.cpp/ggml-{model}.bin"), f"models/ggml-{model}.bin",
                 f"/usr/local/share/whisper/ggml-{model}.bin"):
        if os.path.exists(cand):
            return cand
    return model


def detect_language(wav: str, shutil, subprocess) -> Optional[str]:
    """The spoken language of `wav` from whisper.cpp's detector (-dl), or None when it cannot tell.

    The smallest installed ggml model is used: detection reads the first 30 s once, and a small
    model answers it in well under a second on the GPU.
    """
    cli = _whisper_cpp_cli(shutil)
    if not cli:
        return None
    model = next((p for p in (_whisper_cpp_model(m) for m in ("tiny", "base", "small", "tiny.en"))
                  if os.path.exists(p) and not p.endswith(".en.bin")), None)
    if not model:
        return None
    proc = _asr_run([cli, "-m", model, "-f", wav, "-dl", "-l", "auto"], subprocess, "whisper.cpp language detection")
    m = re.search(r"auto-detected language:\s*([a-z]{2,3})", (proc.stderr or "") + (proc.stdout or ""))
    return m.group(1) if m else None


ROUTING_ASSUMED_ENGLISH = "auto: language not detectable here and no Whisper engine, assumed English"
ROUTING_UNDETECTED_WHISPER = "auto: language not detectable here, Whisper first (Parakeet is English-only)"
ROUTING_LAST_RESORT = "auto: language not detectable here and no Whisper engine transcribed it, assumed English"


class Route(NamedTuple):
    """parakeet_route()'s answer: which Parakeet engines run, and when."""
    first: List[str]  # Parakeet engines to try before any Whisper engine
    facts: Dict[str, Any]  # the routing facts for the result document's `transcription`
    last: Tuple[str, ...] = ()  # Parakeet engines to try once every Whisper engine has failed


def parakeet_route(engine: str, language: Optional[str], wav: str, shutil, subprocess,
                   model: Optional[str] = None, whisper_model: Optional[str] = None) -> Route:
    """Route(the Parakeet engines to try first, routing facts for the result document, the ones to
    try last).

    `auto` tries Parakeet only for English: an explicit --language, else whisper.cpp's detector.
    When neither can say, the English-only model is not trusted with it: a Whisper engine that
    can run (`whisper_model`, default `model`) goes first and Parakeet only after every Whisper
    engine failed; with no Whisper engine, Parakeet runs on English assumed and the caller's
    result carries assumed_english_note(). A named Parakeet engine always runs; with a non-English
    --language it needs a multilingual (v3) model, which _parakeet_model_for() checks.
    """
    if engine in PARAKEET_ENGINES:
        return Route([engine], {"routing": "requested"})
    if engine != "auto":
        return Route([], {"routing": "requested"})
    if not any(_parakeet_available(e, shutil, model) for e in PARAKEET_ENGINES):
        return Route([], {"routing": "auto: no Parakeet engine installed"})
    if language:
        if _is_english(language):
            return Route(list(PARAKEET_ENGINES), {"routing": "auto: --language is English"})
        return Route([], {"routing": f"auto: --language {language} is not English"})
    detected = detect_language(wav, shutil, subprocess)
    if detected is None:
        if _whisper_ready(shutil, whisper_model if whisper_model is not None else model):
            info("the spoken language could not be detected here; a Whisper engine takes it (Parakeet's model is English-only)")
            return Route([], {"routing": ROUTING_UNDETECTED_WHISPER}, PARAKEET_ENGINES)
        return Route(list(PARAKEET_ENGINES), {"routing": ROUTING_ASSUMED_ENGLISH})
    if _is_english(detected):
        return Route(list(PARAKEET_ENGINES), {"routing": "auto: detected English", "detected_language": detected})
    return Route([], {"routing": f"auto: detected {detected}, not English", "detected_language": detected})


def _module_importable(name: str) -> bool:
    """`import name` would find something, without importing it (faster-whisper pulls in ctranslate2)."""
    import importlib.util
    import sys
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # a module already in sys.modules with no __spec__ (a stub)
        return sys.modules.get(name) is not None


def _whisper_ready(shutil, model: Optional[str]) -> bool:
    """A Whisper engine that --engine auto would run with `model`: whisper.cpp with that model on
    disk, faster-whisper importable, or the openai-whisper CLI. A Parakeet model name is no
    Whisper model, so it answers False."""
    name = (model or "base")
    if "parakeet" in name.lower() or name.lower().endswith(".gguf"):
        return False
    if _whisper_cpp_cli(shutil) and os.path.exists(_whisper_cpp_model(name)):
        return True
    return _module_importable("faster_whisper") or bool(shutil.which("whisper"))


def _parakeet_available(engine: str, shutil, model: Optional[str] = None) -> bool:
    if engine == "parakeet-mlx":
        return bool(shutil.which("parakeet-mlx"))
    gguf = _parakeet_cpp_gguf(model)
    return bool(shutil.which("parakeet-cli")) and gguf is not None and os.path.isfile(gguf)


def _parakeet_cpp_gguf(model: Optional[str]) -> Optional[str]:
    """--model when it is a .gguf, else $PARAKEET_CPP_MODEL, else an English tdt-0.6b-v2 .gguf in
    ~/.cache/parakeet.cpp/ (f16 first, then q8_0, then any other quantisation)."""
    if model and model.lower().endswith(".gguf"):
        return os.path.expanduser(model)
    env = os.environ.get("PARAKEET_CPP_MODEL", "").strip()
    if env:
        return os.path.expanduser(env)
    cache = Path(os.path.expanduser("~/.cache/parakeet.cpp"))
    found = sorted(cache.glob("tdt-0.6b-v2-*.gguf")) if cache.is_dir() else []
    for pref in ("-f16.gguf", "-q8_0.gguf"):
        for p in found:
            if p.name.endswith(pref):
                return str(p)
    return str(found[0]) if found else None


def _parakeet_model_for(engine: str, model: Optional[str], language: Optional[str]) -> str:
    """The model the Parakeet engine runs: --model when it names a Parakeet model, else the
    engine's own environment variable, else the English v2 default. A non-English --language on a
    model without "v3" in its name is refused: v2 would transcribe it as English gibberish."""
    if engine == "parakeet-mlx":
        chosen = model if model and "parakeet" in model.lower() and not model.lower().endswith(".gguf") else \
            (os.environ.get("PARAKEET_MODEL", "").strip() or PARAKEET_MLX_DEFAULT_MODEL)
    else:
        chosen = _parakeet_cpp_gguf(model) or ""
    if language and not _is_english(language) and "v3" not in os.path.basename(chosen).lower():
        die(f"{engine} with model {os.path.basename(chosen) or '?'} is English-only; --language {language} needs a multilingual (v3) Parakeet model",
            kind="input", hint="pass --model with a parakeet-tdt-0.6b-v3 model, or --engine auto / whisper.cpp for this language")
    return chosen


def run_parakeet(engine: str, wav: str, tmpdir: str, model: Optional[str], language: Optional[str], shutil, subprocess,
                 video: str) -> Optional[Tuple[List[Tuple[float, float, str]], "List[Dict[str, Any]]", str]]:
    """(cues, words, model) from one Parakeet engine, or None when it is not installed or failed
    (an info line says which), so the caller moves on to the next engine. Output that yields no
    words is only "no speech" when it is the engine's own empty answer; anything else it could not
    be read, which is a failed run too."""
    if not _parakeet_available(engine, shutil, model):
        info(f"{engine} not available" + (" (no readable .gguf: --model, PARAKEET_CPP_MODEL, or tdt-0.6b-v2 in ~/.cache/parakeet.cpp)"
                                          if engine == "parakeet.cpp" and shutil.which("parakeet-cli") else ""))
        return None
    chosen = _parakeet_model_for(engine, model, language)
    if engine == "parakeet-mlx":
        outdir = os.path.join(tmpdir, "pmlx")
        cmd = ["parakeet-mlx", wav, "--model", chosen, "--output-format", "json", "--output-dir", outdir,
               "--max-duration", f"{CUE_MAX_SECONDS:g}", "--silence-gap", f"{CUE_GAP_SECONDS:g}"]
        proc = _asr_run(cmd, subprocess, "parakeet-mlx")
        doc = os.path.join(outdir, os.path.splitext(os.path.basename(wav))[0] + ".json")
        if proc.returncode != 0 or not os.path.exists(doc):
            info("parakeet-mlx found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            return None
        cues, words = _cues_from_parakeet_mlx_json(doc), _words_from_parakeet_mlx_json(doc)
        try:
            raw, key = Path(doc).read_text(encoding="utf-8", errors="replace"), "sentences"
        except OSError:
            raw, key = "", "sentences"
    else:
        cmd = ["parakeet-cli", "transcribe", "--model", chosen, "--input", wav, "--json"]
        proc = _asr_run(cmd, subprocess, "parakeet.cpp")
        if proc.returncode != 0:
            info("parakeet.cpp found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            return None
        words = _words_from_parakeet_cpp_json(proc.stdout)
        cues = cues_from_words(words)
        raw, key = proc.stdout or "", "words"
    if not cues:
        if _heard_nothing(raw, key):
            die_no_speech(engine, video)
        info(f"{engine} ran but wrote output this skill cannot read as a transcript "
             f"({(raw.strip() or 'nothing')[:80]!r}); trying the next engine")
        return None
    return cues, words, chosen


def _heard_nothing(text: str, key: str) -> bool:
    """True when an engine's JSON is its well-formed empty answer, {key: []}: what parakeet-cli
    ("words") and parakeet-mlx ("sentences") both write for silence (measured on 3 s of it).
    Anything else that yields no words -- not JSON, the wrong shape, entries that do not parse --
    is output that could not be read, not a finding that nobody spoke."""
    try:
        doc = json.loads(text)
    except ValueError:
        return False
    return isinstance(doc, dict) and doc.get(key) == []


def transcribe_words(video: str, language: "Optional[str]" = None, model: str = "base",
                     audio_stream: int = 0, engine: "Optional[str]" = None) -> "Tuple[List[Dict[str, Any]], Optional[str]]":
    """transcribe_words_result()'s (words, engine) alone: the call shape this function has had
    since 1.17. A caller that reports which engine ran (silence.py does) calls
    transcribe_words_result() instead."""
    run = transcribe_words_result(video, language, model, audio_stream, engine)
    return run.words, run.engine


def transcribe_words_result(video: str, language: "Optional[str]" = None, model: str = "base",
                            audio_stream: int = 0, engine: "Optional[str]" = None,
                            language_flag: str = "--filler-lang") -> Transcription:
    """[{word, start, end}, ...] from a local speech engine, as a Transcription naming the engine.

    `engine` (else $FFMPEG_SKILL_ASR_ENGINE, else auto) picks it; auto tries Parakeet for English
    speech first (parakeet-mlx sub-word tokens merged into words, parakeet.cpp `--json` words),
    then drives whichever whisper is installed with ITS word-timestamp option -- whisper.cpp
    `--output-json-full`, faster-whisper `word_timestamps=True`, openai-whisper
    `--word_timestamps True` -- and returns the words it measured. Words [] with the engine set
    when the engine ran but its build produced no word-level timings, so the caller can refuse
    naming that engine instead of pretending the audio had no words in it. No engine at all
    raises through die_no_engine(), the same refusal caption.py gives. `language_flag` is the
    caller's flag for the language, named in assumed_english_note().
    """
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile
    from _common import require_tool, run_analysis, STATE
    ffmpeg = require_tool("ffmpeg")
    wanted = requested_engine(engine)
    parakeet_model = None if model == "base" else model
    tmpdir = _tempfile.mkdtemp(prefix="ffskill_asrw_")
    try:
        wav = os.path.join(tmpdir, "audio.wav")
        run_analysis([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video,
                      "-map", f"0:a:{audio_stream}", "-vn", "-ac", "1", "-ar", "16000",
                      "-c:a", "pcm_s16le", wav])

        def parakeet(engines: "List[str]", facts: Dict[str, Any]) -> Optional[Transcription]:
            done = _parakeet_attempt(engines, facts, wanted, language, wav, tmpdir, parakeet_model,
                                     _shutil, _subprocess, video, language_flag, need_words=True)
            if not done:
                return None
            run, model_name = done
            info(f"word timings from {run.engine} ({len(run.words)} words, model {model_name})")
            return run

        # 0. Parakeet (English), when auto-routing picks it or it was asked for by name
        route = parakeet_route(wanted, language, wav, _shutil, _subprocess, parakeet_model, whisper_model=model)
        done = parakeet(route.first, route.facts)
        if done:
            return done
        if wanted in PARAKEET_ENGINES:
            die(f"--engine {wanted} could not transcribe {video} (see the line above)", kind="missing_tool",
                hint="install it, or use --engine auto to fall back to Whisper")
        facts = route.facts
        failed: Optional[str] = None  # the Whisper engine that ran and wrote no word-timing JSON

        # 1. whisper.cpp
        cli = _whisper_cpp_cli(_shutil) if wanted in ("auto", "whisper.cpp") else None
        if cli:
            model_path = _whisper_cpp_model(model)
            base = os.path.join(tmpdir, "out")
            cmd = [cli, "-m", model_path, "-f", wav, "--output-json-full", "-of", base]
            if language:
                cmd += ["-l", language]
            proc = _asr_run(cmd, _subprocess, "whisper.cpp")
            if proc.returncode == 0 and os.path.exists(base + ".json"):
                words = _words_from_whisper_cpp_json(base + ".json")
                info(f"word timings from whisper.cpp ({len(words)} words)")
                return Transcription(words=words, engine="whisper.cpp",
                                     facts=dict(facts, engine="whisper.cpp", model=model_path, language=language))
            info("whisper.cpp found but produced no word-timing JSON: "
                 + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            failed = "whisper.cpp"

        # 2. faster-whisper
        try:
            if failed or wanted not in ("auto", "faster-whisper"):
                raise ImportError
            from faster_whisper import WhisperModel  # type: ignore
            import threading
            collected: list = []
            crashed: list = []

            def work() -> None:
                try:
                    m = WhisperModel(model, device="cpu", compute_type="int8")
                    segments, _ = m.transcribe(wav, language=language, word_timestamps=True)
                    for seg in segments:
                        for w in (getattr(seg, "words", None) or []):
                            collected.append({"word": str(w.word).strip(),
                                              "start": float(w.start), "end": float(w.end)})
                except Exception as exc:  # noqa: BLE001 -- a model that would not load or run
                    crashed.append(exc)

            t = threading.Thread(target=work, daemon=True)
            t.start()
            t.join(STATE.timeout or None)
            if t.is_alive():
                die(f"faster-whisper exceeded the {STATE.timeout:.0f} s time limit; raise "
                    "--timeout for a long recording", code=124, kind="timeout")
            if crashed:
                info(f"faster-whisper found but failed: {crashed[0]!s}"[:240])
                failed = "faster-whisper"
            else:
                info(f"word timings from faster-whisper ({len(collected)} words)")
                return Transcription(words=[w for w in collected if w["word"]], engine="faster-whisper",
                                     facts=dict(facts, engine="faster-whisper", model=model, language=language))
        except ImportError:
            pass

        # 3. openai-whisper CLI
        if not failed and wanted in ("auto", "openai-whisper") and _shutil.which("whisper"):
            cmd = ["whisper", wav, "--model", model, "--word_timestamps", "True",
                   "--output_format", "json", "--output_dir", tmpdir]
            if language:
                cmd += ["--language", language]
            proc = _asr_run(cmd, _subprocess, "openai-whisper")
            doc = os.path.join(tmpdir, "audio.json")
            if proc.returncode == 0 and os.path.exists(doc):
                words = _words_from_openai_whisper_json(doc)
                info(f"word timings from openai-whisper ({len(words)} words)")
                return Transcription(words=words, engine="openai-whisper",
                                     facts=dict(facts, engine="openai-whisper", model=model, language=language))
            info("openai-whisper found but produced no word-timing JSON: "
                 + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            failed = "openai-whisper"

        # 4. Parakeet after all, when the language was never known and no Whisper engine gave words
        if route.last:
            info("no Whisper engine produced word timings; trying Parakeet with English assumed")
            done = parakeet(list(route.last), {"routing": ROUTING_LAST_RESORT})
            if done:
                return done
        if failed:
            # it ran: the caller refuses naming it ("no word-level timings"), not "no engine"
            return Transcription(engine=failed, facts=facts)
        if wanted != "auto":
            die(f"--engine {wanted} is not installed", kind="missing_tool",
                hint="install it, or use --engine auto to use whichever engine is installed")
        die_no_engine("or pass --words with a transcript you already have.",
                      flag="--filler --transcribe")
        return Transcription()
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)
