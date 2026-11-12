"""Fuzz the SRT reader that caption.py, burn and the transcript path use. A file it cannot read
ends the run through die() (SystemExit with a JSON error); any other exception is a bug."""
import os
import tempfile

import _harness  # noqa: F401  (sets sys.path)
from _common import asr


def test_one_input(data: bytes) -> None:
    fd, path = tempfile.mkstemp(suffix=".srt")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            cues = asr.parse_srt(path)
        except SystemExit:
            return
        for start, end, text in cues:
            if not isinstance(text, str) or start != start or end != end:
                raise AssertionError(f"bad cue {(start, end, text)!r}")
    finally:
        os.remove(path)


if __name__ == "__main__":
    _harness.main(test_one_input)
