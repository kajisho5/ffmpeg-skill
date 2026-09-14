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
from typing import List, Optional, Tuple

from _common.decision import fmt_srt_time, parse_time
from _common.emit import die, info
from _common.runner import read_text_or_die

# The three engines this skill knows how to drive, and how to install each -- one string, so
# every tool that needs a transcript refuses in the same words.
ASR_ENGINES = ("whisper.cpp", "faster-whisper", "openai-whisper")
ASR_INSTALL_HINT = (
    "Install one (all run offline):\n"
    "  whisper.cpp:    brew install whisper-cpp   (then download a model: ggml-base.bin)\n"
    "  faster-whisper: pip install faster-whisper\n"
    "  openai-whisper: pip install openai-whisper")


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


def transcribe(video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int = 0) -> List[Tuple[float, float, str]]:
    """Optional local ASR bridge. Tries, in order: whisper-cli / main (whisper.cpp), faster-whisper (python),
    whisper (openai-whisper CLI). Produces an SRT with word timings where the engine supports it.
    No engine installed -> clear error with install hints; the skill never depends on one."""
    import shutil
    import subprocess
    import tempfile
    from _common import require_tool, run_analysis, STATE
    ffmpeg = require_tool("ffmpeg")
    tmpdir = tempfile.mkdtemp(prefix="ffskill_asr_")
    try:
        return _transcribe_in(tmpdir, video, out_srt, language, model, audio_stream, ffmpeg, shutil, subprocess)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _asr_run(cmd: List[str], subprocess, name: str) -> "subprocess.CompletedProcess":
    """Run a speech-to-text engine under the same wall-clock limit as an ffmpeg call."""
    from _common import STATE, die
    limit = STATE.timeout or None
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        die(f"{name} exceeded the {limit:.0f} s time limit and was killed; raise --timeout for a long recording",
            code=124, kind="timeout")
    return None  # unreachable


def _transcribe_in(tmpdir: str, video: str, out_srt: str, language: Optional[str], model: str, audio_stream: int,
                   ffmpeg: str, shutil, subprocess) -> List[Tuple[float, float, str]]:
    from _common import run_analysis, STATE, die
    wav = os.path.join(tmpdir, "audio.wav")
    # A wav in our own temp dir: a measurement input for the engine, not a deliverable, so it
    # is not a run() call (no --dry-run gate, not recorded), but it keeps the time limit and
    # reports an unreadable input as kind ffmpeg instead of a CalledProcessError traceback.
    run_analysis([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video,
                  "-map", f"0:a:{audio_stream}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    # 1. whisper.cpp
    cli = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if not cli:
        # older whisper.cpp builds ship the binary as plain `main`; accept it only when it lives
        # in a directory that names whisper, so an unrelated /usr/bin/main is never run
        main_bin = shutil.which("main")
        if main_bin and "whisper" in os.path.dirname(os.path.realpath(main_bin)).lower():
            cli = main_bin
    if cli:
        model_path = model
        if not os.path.exists(model_path):
            for cand in (os.path.expanduser(f"~/.cache/whisper.cpp/ggml-{model}.bin"), f"models/ggml-{model}.bin", f"/usr/local/share/whisper/ggml-{model}.bin"):
                if os.path.exists(cand):
                    model_path = cand
                    break
        base = os.path.join(tmpdir, "out")
        cmd = [cli, "-m", model_path, "-f", wav, "-osrt", "-of", base]
        if language:
            cmd += ["-l", language]
        proc = _asr_run(cmd, subprocess, "whisper.cpp")
        if proc.returncode == 0 and os.path.exists(base + ".srt"):
            info(f"transcribed with whisper.cpp ({os.path.basename(cli)}, model {os.path.basename(model_path)})")
            cues = parse_srt(base + ".srt")
            write_srt(cues, out_srt)
            return cues
        info("whisper.cpp found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
    # 2. faster-whisper (python package)
    try:
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
        if cues:
            info("transcribed with faster-whisper")
            write_srt(cues, out_srt)
            return cues
    except ImportError:
        pass
    # 3. openai-whisper CLI
    if shutil.which("whisper"):
        cmd = ["whisper", wav, "--model", model, "--output_format", "srt", "--output_dir", tmpdir]
        if language:
            cmd += ["--language", language]
        proc = _asr_run(cmd, subprocess, "openai-whisper")
        srt = os.path.join(tmpdir, "audio.srt")
        if proc.returncode == 0 and os.path.exists(srt):
            info("transcribed with openai-whisper")
            cues = parse_srt(srt)
            write_srt(cues, out_srt)
            return cues
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


