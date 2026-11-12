"""Fuzz the time grammar every --start/--end/--at flag goes through (seconds, mm:ss,
hh:mm:ss.ms, SRT commas, hh:mm:ss:ff with an fps or an @fps suffix). A ValueError is the
documented refusal; anything else, or a non-finite result, is a bug. A negative value is a
valid answer here: offsets (`sync.py --offset -0.5`) go through the same grammar, and each tool
refuses a negative start or end itself."""
import math

import _harness  # noqa: F401  (sets sys.path)
from _common.decision import parse_time


def test_one_input(data: bytes) -> None:
    text = data.decode("utf-8", "replace")
    for fps in (None, 25.0, 29.97):
        try:
            value = parse_time(text, fps)
        except ValueError:
            continue
        if not math.isfinite(value):
            raise AssertionError(f"parse_time({text!r}, {fps}) returned {value!r}")


if __name__ == "__main__":
    _harness.main(test_one_input)
