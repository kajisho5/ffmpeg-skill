#!/usr/bin/env python3
"""CHANGELOG.md fragments (#678): one file per change under changelog.d/, so two open PRs never
edit the same lines of CHANGELOG.md.

A fragment starts with its section heading (`### Fixed`, `### Added`, `### Changed`), then its
bullets. The release job's bump step calls `assemble`, which writes the new version's section:
the text under `## Unreleased` (what a branch opened before this split still writes there), then
the fragments grouped by section in the order Fixed / Added / Changed, then the generated
commit-subject bullets; `take_fragments` reads the fragments and deletes them, so the release
commit that writes the section also removes them. `## Unreleased` stays as a heading.
"""
import pathlib
import re
from typing import Callable, List, Tuple

SECTIONS = ("Fixed", "Added", "Changed")
README = "README.md"


def take_fragments(directory: "pathlib.Path | str") -> List[Tuple[str, str]]:
    """(name, text) of every fragment in the directory, sorted by name; each file is deleted."""
    out = []
    for path in sorted(pathlib.Path(directory).glob("*.md")):
        if path.name != README:
            out.append((path.name, path.read_text(encoding="utf-8")))
            path.unlink()
    return out


def split_fragment(text: str) -> Tuple[str, str]:
    """(section, body): the `### Section` heading line and the text below it. Text with no
    heading is filed under Changed rather than lost."""
    m = re.match(r"\s*### +(.+?)\s*\n", text + "\n")
    if not m:
        return "Changed", text.strip()
    return m.group(1), (text + "\n")[m.end():].strip()


def group(fragments: List[Tuple[str, str]]) -> str:
    """The fragments as `### Section` blocks, Fixed / Added / Changed first, other headings after."""
    bodies: dict = {}
    for _, text in sorted(fragments):
        section, body = split_fragment(text)
        if body:
            bodies.setdefault(section, []).append(body)
    order = [s for s in SECTIONS if s in bodies] + sorted(s for s in bodies if s not in SECTIONS)
    return "\n\n".join(f"### {s}\n\n" + "\n".join(bodies[s]) for s in order)


def assemble(changelog: str, fragments: List[Tuple[str, str]], version: str, old: str,
             bullets: str, closes_line: str = "") -> str:
    """CHANGELOG.md with the new version's section above the previous one, `## Unreleased` reset
    to "(nothing yet)". Section = automated-release line, legacy Unreleased text, grouped
    fragments, the generated bullets (and the `Closes:` line)."""
    section = f"## {version}\n\n_Automated release: version and notes generated from pull requests merged since {old}._\n\n"
    # Whatever sits under "## Unreleased" (hand-written bullets from the merged PRs, or the
    # placeholder "(nothing yet)") moves into the new version's section, ahead of the
    # generated commit-subject bullets, and the placeholder is put back. The anchor used to
    # be the literal "(nothing yet)" line, so a PR that wrote real notes there broke the
    # bump step (1.4.1's first run).
    m = re.search(r"## Unreleased\n(.*?)(?=^## )", changelog, re.S | re.M)
    # A hand-bumped major writes its own section on top and leaves no "## Unreleased"
    # (4.0.0): the first release after it then failed here and nothing was published. With
    # no such section there is nothing to carry, and the new section goes above the first
    # version heading.
    first = m or re.search(r"^## ", changelog, re.M)
    assert first, "CHANGELOG.md has no '## Unreleased' section and no version heading"
    unreleased = m.group(1).strip() if m else ""
    parts = [p for p in ((unreleased if unreleased != "(nothing yet)" else ""), group(fragments)) if p]
    notes = "\n\n".join(parts)
    section += (notes + "\n" if notes else "") + f"{bullets}{closes_line}\n\n"
    return (changelog[:first.start()] + "## Unreleased\n\n(nothing yet)\n\n" + section
            + changelog[m.end() if m else first.start():])


def adds_fix(git: Callable[..., str], base: str, head: str) -> bool:
    """Does base..head write a fix note: a `+- ` line in CHANGELOG.md, or a fragment added under
    changelog.d/ whose section is `### Fixed`?"""
    if any(line.startswith("+- ") for line in git("diff", base, head, "--", "CHANGELOG.md").splitlines()):
        return True
    for name in git("diff", "--name-only", "--diff-filter=A", base, head, "--", "changelog.d").splitlines():
        name = name.strip()
        if name.endswith(".md") and not name.endswith("/" + README):
            if split_fragment(git("show", f"{head}:{name}"))[0] == "Fixed":
                return True
    return False
