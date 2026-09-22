#!/usr/bin/env python3
"""Move docs/contract.md's current-version mentions from one release to the next.

Used by .github/workflows/release.yml's auto-bump step. It replaces the earlier
`contract.replace(old, new)`, which rewrote *every* occurrence of the old version string in
the file -- including the historical ones: the "Since" column of "What 2.0 changes" (every
deprecation there dates from 1.10.0), "added in 1.17.1" headings, "(1.18.4)" key annotations
and "as every version before 1.18.3 did". Sixteen releases later all of them read "1.26.0",
so the record 2.0's deprecation window is counted from said the deprecations were a week old.

Only two places state the version being released, and only those move:

  - the `skill.version` row of the stability table: "the npm / package.json version (`X`)"
  - the `contract --json` example: `"skill": {"id": "ffmpeg-skill", "version": "X"`

Each must be found exactly once; anything else is an error rather than a silent partial bump.
"""
import sys
from typing import Tuple

ANCHORS: Tuple[str, ...] = (
    "the npm / package.json version (`{v}`)",
    '"skill": {{"id": "ffmpeg-skill", "version": "{v}"',
)


def bump_contract_md(text: str, old: str, new: str) -> str:
    for anchor in ANCHORS:
        before, after = anchor.format(v=old), anchor.format(v=new)
        n = text.count(before)
        if n != 1:
            raise ValueError(f"docs/contract.md: expected exactly one {before!r}, found {n}")
        text = text.replace(before, after)
    return text


def main(argv) -> int:
    if len(argv) != 4:
        print("usage: bump_contract_md.py PATH OLD NEW", file=sys.stderr)
        return 2
    path, old, new = argv[1:]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        text = bump_contract_md(text, old, new)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
