"""The optional local speech-to-text bridge, and the SRT the rest of the skill reads and writes.

Whisper is never required. Nothing here runs unless a caller asked for a transcript:
`caption.py --transcribe` and `silence.py --filler --transcribe` share this one engine probe, so
the "no engine found" message, its install lines and its exit code are stated once rather than
copied per tool. This module is neither ffprobe nor a decision, which is why it is its own file.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
ASR_INSTALL_HINT = (
    "Install one (all run offline):\n"
    "  parakeet-mlx:   uv tool install parakeet-mlx   (Apple Silicon; English)\n"
    "  parakeet.cpp:   parakeet-cli from github.com/mudler/parakeet.cpp releases, plus a\n"
    "                  tdt-0.6b-v2 .gguf in ~/.cache/parakeet.cpp/ (English)\n"
    "  whisper.cpp:    brew install whisper-cpp   (then download a model: ggml-base.bin)\n"
    "  faster-whisper: pip install faster-whisper\n"
    "  openai-whisper: pip install openai-whisper")

# What the last transcribe() / transcribe_words() call actually used, for the caller's result
# document: {"engine", "model", "language", "routing"}. A caller reads it right after the call.
LAST_RUN: Dict[str, Any] = {}
# The word timings the last Parakeet run measured ({word, start, end}), for --karaoke; whisper
# engines leave it empty (their word timings are read from a JSON next to the SRT instead).
LAST_WORDS: "List[Dict[str, Any]]" = []


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


def transcribe(video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int = 0,
               engine: Optional[str] = None) -> List[Tuple[float, float, str]]:
    """Optional local ASR bridge. `engine` (else $FFMPEG_SKILL_ASR_ENGINE, else auto) picks the
    engine; auto tries Parakeet (parakeet-mlx, parakeet.cpp) for English speech, then whisper-cli /
    main (whisper.cpp), faster-whisper (python), whisper (openai-whisper CLI). What ran is left in
    LAST_RUN. No engine installed -> clear error with install hints; the skill never depends on one."""
    import shutil
    import subprocess
    import tempfile
    from _common import require_tool, run_analysis, STATE
    ffmpeg = require_tool("ffmpeg")
    wanted = requested_engine(engine)
    LAST_RUN.clear()
    LAST_WORDS.clear()
    tmpdir = tempfile.mkdtemp(prefix="ffskill_asr_")
    try:
        return _transcribe_in(tmpdir, video, out_srt, language, model, audio_stream, ffmpeg, shutil, subprocess, wanted)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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


def _transcribe_in(tmpdir: str, video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int,
                   ffmpeg: str, shutil, subprocess, wanted: str = "auto") -> List[Tuple[float, float, str]]:
    from _common import run_analysis, STATE, die
    wav = os.path.join(tmpdir, "audio.wav")
    # A wav in our own temp dir: a measurement input for the engine, not a deliverable, so it
    # is not a run() call (no --dry-run gate, not recorded), but it keeps the time limit and
    # reports an unreadable input as kind ffmpeg instead of a CalledProcessError traceback.
    run_analysis([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video,
                  "-map", f"0:a:{audio_stream}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    # 0. Parakeet (English), when auto-routing picks it or it was asked for by name
    first, route = parakeet_route(wanted, language, wav, shutil, subprocess, model)
    LAST_RUN.update(route)
    for eng in first:
        got = run_parakeet(eng, wav, tmpdir, model, language, shutil, subprocess, video)
        if got:
            cues, words, chosen = got
            LAST_WORDS.extend(words)
            info(f"transcribed with {eng} (model {os.path.basename(chosen)})")
            LAST_RUN.update(engine=eng, model=chosen, language=language or route.get("detected_language"))
            write_srt(cues, out_srt)
            return cues
    if wanted in PARAKEET_ENGINES:
        die(f"--engine {wanted} could not transcribe {video} (see the line above)", kind="missing_tool",
            hint="install it (see --help), or use --engine auto to fall back to Whisper")
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
            LAST_RUN.update(engine="whisper.cpp", model=model_path, language=language)
            cues = _engine_cues(base + ".srt", "whisper.cpp", video)
            write_srt(cues, out_srt)
            return cues
        info("whisper.cpp found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
    # 2. faster-whisper (python package)
    try:
        if wanted not in ("auto", "faster-whisper"):
            raise ImportError
        from faster_whisper import WhisperModel  # type: ignore
        import threading
        result: list = []

        def work() -> None:
            m = WhisperModel(model, device="cpu", compute_type="int8")
            segments, _ = m.transcribe(wav, language=language, word_timestamps=False)
            result.extend((seg.start, seg.end, seg.text.strip()) for seg in segments if seg.text.strip())

        # An in-process engine gets the same wall-clock limit as the CLI engines and ffmpeg.
        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(STATE.timeout or None)
        if t.is_alive():
            die(f"faster-whisper exceeded the {STATE.timeout:.0f} s time limit; raise --timeout for a long recording", code=124, kind="timeout")
        cues = list(result)
        if not cues:
            die_no_speech("faster-whisper", video)
        info("transcribed with faster-whisper")
        LAST_RUN.update(engine="faster-whisper", model=model, language=language)
        write_srt(cues, out_srt)
        return cues
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
            LAST_RUN.update(engine="openai-whisper", model=model, language=language)
            cues = _engine_cues(srt, "openai-whisper", video)
            write_srt(cues, out_srt)
            return cues
    if wanted != "auto":
        die(f"--engine {wanted} is not installed or could not transcribe {video}", kind="missing_tool",
            hint="install it (see --help), or use --engine auto to use whichever engine is installed")
    die_no_engine("Or write the cues by hand with --text cues.txt (see format above).")
    return []


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


def parakeet_route(engine: str, language: Optional[str], wav: str, shutil, subprocess,
                   model: Optional[str] = None) -> Tuple[List[str], Dict[str, Any]]:
    """(the Parakeet engines to try first, routing facts for the result document).

    `auto` tries Parakeet only for English: an explicit --language, else whisper.cpp's detector,
    else (no detector installed) English is assumed and the result says so. A named Parakeet
    engine always runs; with a non-English --language it needs a multilingual (v3) model, which
    _parakeet_model_for() checks.
    """
    if engine in PARAKEET_ENGINES:
        return [engine], {"routing": "requested"}
    if engine != "auto":
        return [], {"routing": "requested"}
    if not any(_parakeet_available(e, shutil, model) for e in PARAKEET_ENGINES):
        return [], {"routing": "auto: no Parakeet engine installed"}
    if language:
        if _is_english(language):
            return list(PARAKEET_ENGINES), {"routing": "auto: --language is English"}
        return [], {"routing": f"auto: --language {language} is not English"}
    detected = detect_language(wav, shutil, subprocess)
    if detected is None:
        return list(PARAKEET_ENGINES), {"routing": "auto: language not detectable here, assumed English"}
    if _is_english(detected):
        return list(PARAKEET_ENGINES), {"routing": "auto: detected English", "detected_language": detected}
    return [], {"routing": f"auto: detected {detected}, not English", "detected_language": detected}


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
    """([{word, start, end}, ...], the engine that produced them) from a local speech engine.

    `engine` (else $FFMPEG_SKILL_ASR_ENGINE, else auto) picks it; auto tries Parakeet for English
    speech first (parakeet-mlx sub-word tokens merged into words, parakeet.cpp `--json` words),
    then drives whichever whisper is installed with ITS word-timestamp option -- whisper.cpp
    `--output-json-full`, faster-whisper `word_timestamps=True`, openai-whisper
    `--word_timestamps True` -- and returns the words it measured. ([], engine) when the engine
    ran but its build produced no word-level timings, so the caller can refuse naming that engine
    instead of pretending the audio had no words in it. No engine at all raises through
    die_no_engine(), the same refusal caption.py gives. What ran is left in LAST_RUN.
    """
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile
    from _common import require_tool, run_analysis, STATE
    ffmpeg = require_tool("ffmpeg")
    wanted = requested_engine(engine)
    LAST_RUN.clear()
    tmpdir = _tempfile.mkdtemp(prefix="ffskill_asrw_")
    try:
        wav = os.path.join(tmpdir, "audio.wav")
        run_analysis([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video,
                      "-map", f"0:a:{audio_stream}", "-vn", "-ac", "1", "-ar", "16000",
                      "-c:a", "pcm_s16le", wav])

        # 0. Parakeet (English), when auto-routing picks it or it was asked for by name
        first, route = parakeet_route(wanted, language, wav, _shutil, _subprocess, None if model == "base" else model)
        LAST_RUN.update(route)
        for eng in first:
            got = run_parakeet(eng, wav, tmpdir, None if model == "base" else model, language, _shutil, _subprocess, video)
            if got and not got[1] and wanted not in PARAKEET_ENGINES:
                # cues read but no word times (a caption could use them; this caller cannot); a
                # named engine keeps its own "no word-level timings" refusal instead
                info(f"{eng} gave cues but no readable word timings; trying the next engine")
                got = None
            if got:
                _cues, words, chosen = got
                info(f"word timings from {eng} ({len(words)} words, model {os.path.basename(chosen)})")
                LAST_RUN.update(engine=eng, model=chosen, language=language or route.get("detected_language"))
                return words, eng
        if wanted in PARAKEET_ENGINES:
            die(f"--engine {wanted} could not transcribe {video} (see the line above)", kind="missing_tool",
                hint="install it, or use --engine auto to fall back to Whisper")

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
                LAST_RUN.update(engine="whisper.cpp", model=model_path, language=language)
                return words, "whisper.cpp"
            info("whisper.cpp found but produced no word-timing JSON: "
                 + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            return [], "whisper.cpp"

        # 2. faster-whisper
        try:
            if wanted not in ("auto", "faster-whisper"):
                raise ImportError
            from faster_whisper import WhisperModel  # type: ignore
            import threading
            collected: list = []

            def work() -> None:
                m = WhisperModel(model, device="cpu", compute_type="int8")
                segments, _ = m.transcribe(wav, language=language, word_timestamps=True)
                for seg in segments:
                    for w in (getattr(seg, "words", None) or []):
                        collected.append({"word": str(w.word).strip(),
                                          "start": float(w.start), "end": float(w.end)})

            t = threading.Thread(target=work, daemon=True)
            t.start()
            t.join(STATE.timeout or None)
            if t.is_alive():
                die(f"faster-whisper exceeded the {STATE.timeout:.0f} s time limit; raise "
                    "--timeout for a long recording", code=124, kind="timeout")
            info(f"word timings from faster-whisper ({len(collected)} words)")
            LAST_RUN.update(engine="faster-whisper", model=model, language=language)
            return [w for w in collected if w["word"]], "faster-whisper"
        except ImportError:
            pass

        # 3. openai-whisper CLI
        if wanted in ("auto", "openai-whisper") and _shutil.which("whisper"):
            cmd = ["whisper", wav, "--model", model, "--word_timestamps", "True",
                   "--output_format", "json", "--output_dir", tmpdir]
            if language:
                cmd += ["--language", language]
            proc = _asr_run(cmd, _subprocess, "openai-whisper")
            doc = os.path.join(tmpdir, "audio.json")
            if proc.returncode == 0 and os.path.exists(doc):
                words = _words_from_openai_whisper_json(doc)
                info(f"word timings from openai-whisper ({len(words)} words)")
                LAST_RUN.update(engine="openai-whisper", model=model, language=language)
                return words, "openai-whisper"
            info("openai-whisper found but produced no word-timing JSON: "
                 + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
            return [], "openai-whisper"

        if wanted != "auto":
            die(f"--engine {wanted} is not installed", kind="missing_tool",
                hint="install it, or use --engine auto to use whichever engine is installed")
        die_no_engine("or pass --words with a transcript you already have.",
                      flag="--filler --transcribe")
        return [], None
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)
