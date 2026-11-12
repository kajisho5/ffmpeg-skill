"""Fuzz the JSON readers for caller files: parse_json() (projects, recipes, plans, --words) and the
whisper word-timing JSON caption.py --karaoke finds next to an SRT. parse_json() may only return
or raise ValueError; a word-timing file of any shape is no word timings, never an exception."""
import os
import tempfile

import _harness  # noqa: F401  (sets sys.path)
from _common import asr
from _common.runner import parse_json


def test_one_input(data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    try:
        parse_json(text)
    except ValueError:
        pass
    d = tempfile.mkdtemp()
    srt, words = os.path.join(d, "t.srt"), os.path.join(d, "t.json")
    try:
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        with open(words, "wb") as f:
            f.write(data)
        for start, end, word in asr.whisper_word_timings(srt):
            if not isinstance(word, str) or start != start or end != end:
                raise AssertionError(f"bad word {(start, end, word)!r}")
    finally:
        for p in (srt, words):
            os.remove(p)
        os.rmdir(d)


if __name__ == "__main__":
    _harness.main(test_one_input)
