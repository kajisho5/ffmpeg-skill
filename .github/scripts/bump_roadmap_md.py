#!/usr/bin/env python3
"""Move docs/roadmap.md's "The released version today is **X**" sentence to the next release.

Used by .github/workflows/release.yml's auto-bump step. Before this, the auto-bump moved
package.json, plugin.json, contract.md and CHANGELOG.md but not this sentence, which
tests/test_contract.py pins to package.json -- so every label-driven release (2.2.1: f95e3c7)
left main red until a docs PR (#288) moved it by hand.

The prose after the version describes one particular release, written by hand in its PR. An
automatic bump cannot write that prose, so it keeps it and says which version it describes:

    The released version today is **2.2.1** — `render.py` ...
 -> The released version today is **2.2.2** (notes in CHANGELOG.md); **2.2.1** — `render.py` ...

A later automatic bump only moves the leading version; the hand-written prose stays attached to
the version it was written for until a PR replaces the sentence. The sentence must be found
exactly once; anything else is an error rather than a silent partial bump.
"""
import re
import sys

NOTE = " (notes in CHANGELOG.md); "


def bump_roadmap_md(text: str, old: str, new: str) -> str:
    pattern = re.compile(r"The released version today is \*\*" + re.escape(old) + r"\*\*"
                         + r"(" + re.escape(NOTE) + r"\*\*[^*]+\*\*)?")
    found = pattern.findall(text)
    if len(found) != 1:
        raise ValueError(f"docs/roadmap.md: expected exactly one 'The released version today is "
                         f"**{old}**' sentence, found {len(found)}")

    def repl(m: "re.Match[str]") -> str:
        described = m.group(1) or f"{NOTE}**{old}**"
        return f"The released version today is **{new}**{described}"

    return pattern.sub(repl, text, count=1)


def main(argv) -> int:
    if len(argv) != 4:
        print("usage: bump_roadmap_md.py PATH OLD NEW", file=sys.stderr)
        return 2
    path, old, new = argv[1:]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        text = bump_roadmap_md(text, old, new)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
