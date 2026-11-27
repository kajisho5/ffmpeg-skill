"""Word timings from a transcript, and the measured start of a spoken word (#449)."""
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from _common import asr as _asr
from _common.asr import _dicts
from _common.emit import die
from _common.probe import decode_pcm_mono
from _common.runner import parse_json, read_text_or_die

ONSET_RATE = 8000      # decode rate of the onset search
ONSET_BLOCK = 40       # 5 ms blocks
ONSET_MIN_RISE_DB = 15.0  # a rise smaller than this is room noise, not a word
ONSET_HELD = (4, 6)    # a rise counts when 4 of the next 6 blocks (30 ms) stay above the threshold


def _words_from_words_file(path, data):
    """_words_from_transcript() for a --words file, plus whisper.cpp's own shape: its
    --output-json-full document (transcription[].tokens[], offsets in milliseconds) is what the
    refusals here tell a caller to make, and it was then refused for having no word timings (#404).
    Read as --transcribe reads the same file."""
    words, had_segments, untimed = _words_from_transcript(data)
    if not words and isinstance(data, dict) and isinstance(data.get("transcription"), list):
        words = _asr._words_from_whisper_cpp_json(path)
        had_segments = had_segments or bool(data["transcription"])
    return words, had_segments, untimed


def _words_from_transcript(data):
    """([{word,start,end}], whether the document had segments at all, [{word}] of the words
    that carried no usable timing) from a whisper JSON. The third list lets --filler count a
    listed word it could not cut instead of dropping it unseen."""
    raw, had_segments = [], False
    if isinstance(data, dict):
        # a "words" or "segments" that is not a list, and a segment that is not an object, carry no
        # words: the file is then refused for having none, not by a traceback
        raw = _dicts(data.get("words"))
        segments = _dicts(data.get("segments"))
        had_segments = bool(segments)
        for seg in segments:
            raw.extend(_dicts(seg.get("words")))
    elif isinstance(data, list):
        raw = list(data)
    out, untimed = [], []
    for w in raw:
        if not isinstance(w, dict):
            continue
        try:
            out.append({"word": str(w.get("word") or w.get("text") or ""),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            untimed.append({"word": str(w.get("word") or w.get("text") or "")})
    return out, had_segments, untimed


def measure_onset(path: str, t: float, before: float, after: float, floor_t: float = 0.0) -> Dict[str, Any]:
    """Where the sound rises nearest to the transcript time `t`, searched from `before` seconds
    earlier to `after` seconds later (and never before `floor_t`). Returns {"measured": seconds} or
    {"measured": None, "reason": ...}: with no rise in the window the transcript time stands and
    nothing is guessed. The threshold is a third of the window's level range above its quiet floor
    (10th percentile), and a rise must span ONSET_MIN_RISE_DB and hold for 30 ms; of the rises that
    qualify, the one nearest `t` is taken."""
    lo = max(floor_t, 0.0, t - before)
    hi = t + after
    samples = decode_pcm_mono(path, ONSET_RATE, hi - lo, lo)
    levels = []
    for i in range(0, len(samples) - ONSET_BLOCK + 1, ONSET_BLOCK):
        power = sum(x * x for x in samples[i:i + ONSET_BLOCK]) / ONSET_BLOCK
        levels.append(10 * math.log10(max(power, 1e-9)))
    if len(levels) < 8:
        return {"measured": None, "reason": "the window holds less than 40 ms of sound"}
    floor = sorted(levels)[len(levels) // 10]
    peak = max(levels)
    if peak - floor < ONSET_MIN_RISE_DB:
        return {"measured": None, "reason": f"no rise of {ONSET_MIN_RISE_DB:g} dB in {lo:.3f}-{hi:.3f}s"}
    threshold = floor + (peak - floor) / 3
    need, of = ONSET_HELD
    rises = [i for i in range(1, len(levels))
             if levels[i] >= threshold > levels[i - 1]
             and sum(v >= threshold for v in levels[i:i + of]) >= min(need, len(levels) - i)]
    if not rises:
        return {"measured": None, "reason": f"no rise of {ONSET_MIN_RISE_DB:g} dB in {lo:.3f}-{hi:.3f}s that holds for 30 ms"}
    block = ONSET_BLOCK / ONSET_RATE
    return {"measured": round(lo + min(rises, key=lambda i: abs(lo + i * block - t)) * block, 6)}


def read_word_list(path: str, flag: str = "--words") -> List[Dict[str, Any]]:
    """The transcript's words in file order, each with a finite start and an end not before it. A
    word without a timing is refused: dropping it would shift every index after it."""
    try:
        words, _segments, untimed = _words_from_words_file(path, parse_json(read_text_or_die(path, flag)))
    except ValueError as exc:
        die(f"{flag} {path}: not readable JSON ({exc})", kind="input")
    if untimed:
        die(f"{flag} {path}: {len(untimed)} word(s) carry no timing (the first is {untimed[0]['word']!r}); word "
            "indices count every word of the file, so every one needs a start and an end", kind="input")
    if not words or not all(math.isfinite(w["start"]) and math.isfinite(w["end"]) and w["end"] >= w["start"] >= 0 for w in words):
        die(f"{flag} {path}: needs word timings with 0 <= start <= end, in seconds", kind="input")
    return words


def parse_word_ranges(spec: str, count: int) -> List[Tuple[int, int]]:
    """'0-4,7-12' (or '5' for one word) as inclusive 0-based word-index pairs, ascending and sharing no word."""
    out: List[Tuple[int, int]] = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not m:
            die(f"--word-segments {part.strip()!r}: write FIRST-LAST word indices, e.g. 0-4,7-12 (0 is the first word)", kind="input")
        a, b = int(m.group(1)), int(m.group(2) if m.group(2) is not None else m.group(1))
        if b < a or b >= count or (out and a <= out[-1][1]):
            die(f"--word-segments {part.strip()!r}: needs FIRST <= LAST < {count} (the transcript's word count), "
                "after the range before it", kind="input")
        out.append((a, b))
    return out


def plan_word_ranges(path: str, words: List[Dict[str, Any]], ranges: List[Tuple[int, int]], lead: float, tail: float,
                     search: Optional[float], v0: float, rate: float, total: float) -> List[Dict[str, Any]]:
    """One entry per range: its word indices and text, the transcript's times, the measured onset
    (when `search` is given; see measure_onset) and `cut`, the seconds to keep: the first word's
    start (measured when it was) less `lead`, the last word's end plus `tail`, on the source's frame
    grid (the start rounded down, the end up) when it has one. Two ranges that the margins make
    overlap meet at the grid point nearest the middle of the overlap."""
    down = lambda t: v0 + math.floor((t - v0) * rate + 1e-6) / rate if rate else t
    up = lambda t: v0 + math.ceil((t - v0) * rate - 1e-6) / rate if rate else t
    docs = []
    for i, j in ranges:
        doc: Dict[str, Any] = {"words": [i, j], "text": " ".join(w["word"].strip() for w in words[i:j + 1]).strip(),
                               "transcript": [words[i]["start"], words[j]["end"]], "onset": None}
        start = words[i]["start"]
        if search is not None:
            prev = words[i - 1] if i else None
            doc["onset"] = {"transcript": start, **measure_onset(
                path, start, search, search, (prev["start"] + prev["end"]) / 2 if prev else 0.0)}
            start = doc["onset"]["measured"] if doc["onset"]["measured"] is not None else start
        end = up(words[j]["end"] + tail)
        doc["cut"] = [down(max(start - lead, 0.0)), min(end, total) if total else end]
        docs.append(doc)
    for a, b in zip(docs, docs[1:]):
        if b["cut"][0] < a["cut"][1]:
            mid = (b["cut"][0] + a["cut"][1]) / 2
            a["cut"][1] = b["cut"][0] = round((mid - v0) * rate) / rate + v0 if rate else mid
    return docs
