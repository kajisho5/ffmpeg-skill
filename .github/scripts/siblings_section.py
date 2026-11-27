#!/usr/bin/env python3
"""A fix's pull request says what was swept for the same defect elsewhere (AGENTS.md).

A report names one tool and one input, and the same defect usually lives in other tools too.
AGENTS.md asks for a sweep before the fix and for the PR body to say what it showed; the PR
template has a `## Siblings` section for it. Nothing checked that the section was filled, so a
fix could land, from inside or outside, with the sweep skipped. This fails such a PR.

A PR is a fix when its title starts with `fix` or it adds a `### Fixed` changelog note (the same
test revert_proof.py uses). Its body then needs a `## Siblings` section that, with the template's
comment removed, is not empty and names at least one command in backticks: the sweep that was
run (`python3 tests/sweep.py INPUT --baseline PLAIN`, `python3 tests/edge_values.py`, a grep).
"None found" still needs the command that found none.

The body is read from the PR_BODY environment variable, never from the command line, so no
shell ever parses it.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import re
import subprocess
import sys

_spec = importlib.util.spec_from_file_location("changelog_fragments", pathlib.Path(__file__).with_name("changelog_fragments.py"))
FRAGMENTS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FRAGMENTS)

SECTION = re.compile(r"^##[ \t]+Siblings[ \t]*$(.*?)(?=^##[ \t]|\Z)", re.M | re.S | re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
COMMAND = re.compile(r"`[^`\n]*[A-Za-z][^`\n]*`")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def problem(body: str) -> str | None:
    """What is missing from a fix's `## Siblings` section, or None when it says what was swept."""
    m = SECTION.search(body.replace("\r\n", "\n"))
    if not m:
        return "the body has no `## Siblings` section"
    text = COMMENT.sub("", m.group(1)).strip()
    if not text:
        return "the `## Siblings` section is empty"
    if not COMMAND.search(text):
        return "the `## Siblings` section names no command in backticks (the sweep that was run)"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--title", default="")
    ap.add_argument("--base", help="base commit; with --head, a `### Fixed` note added makes the PR a fix")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()
    fixes = bool(re.match(r"fix\b", args.title, re.I)) or bool(args.base and FRAGMENTS.adds_fix(git, args.base, args.head))
    if not fixes:
        print(f"title {args.title!r} and its changelog notes declare no fix: not judged")
        return 0
    why = problem(os.environ.get("PR_BODY", ""))
    if why:
        print(f"a fix's PR says what was swept for the same defect elsewhere (AGENTS.md): {why}.\n"
              "Name the defect's class without the reported tool, the command you ran "
              "(`python3 tests/sweep.py INPUT --baseline PLAIN`, `python3 tests/edge_values.py`, a grep), "
              "the rows that differed, and for each: fixed here, filed, or a decided behaviour.")
        return 1
    print("the `## Siblings` section says what was swept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
