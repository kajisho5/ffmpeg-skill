"""Fuzz the hardened XML reader that checks an exported FCPXML before it is reported written:
it must refuse a DOCTYPE/entity and malformed input with ParseError, never expand an entity or
raise anything else."""
from xml.etree.ElementTree import ParseError

import _harness  # noqa: F401  (sets sys.path)
from _common import timeline


def test_one_input(data: bytes) -> None:
    try:
        timeline._xml_root_tag(data)
    except ParseError:
        pass


if __name__ == "__main__":
    _harness.main(test_one_input)
