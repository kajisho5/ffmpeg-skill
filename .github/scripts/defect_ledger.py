#!/usr/bin/env python3
"""The defect ledger (#632): one JSON file per entry under docs/defect-ledger/ (#678).

Every fix used to append a line to docs/defect-ledger.jsonl, so any two open fixes conflicted in
its last line, and an external PR (whose branch the maintainer cannot push to) stalled on it each
time main moved. An entry is now its own file, docs/defect-ledger/<date>-<issue or slug>.json, so
two fixes add two files and never meet. The .jsonl keeps the entries written before the split,
read as they are; it is not appended to (a branch opened before the split may still add its line
there, and that counts too).

    rows(root)                -> every entry, the .jsonl's lines first, then the files by name
    added(git, base, head)    -> the entries a change adds, in either place
"""
import json
import pathlib
from typing import Any, Callable, Dict, List

LEGACY = "docs/defect-ledger.jsonl"
DIR = "docs/defect-ledger"


def rows(root: "pathlib.Path | str" = ".") -> List[Dict[str, Any]]:
    """Every ledger entry, each with `_where` (file, and line for the .jsonl) for messages."""
    root = pathlib.Path(root)
    out: List[Dict[str, Any]] = []
    legacy = root / LEGACY
    if legacy.exists():
        for n, line in enumerate(legacy.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                out.append(dict(json.loads(line), _where=f"{LEGACY}:{n}"))
    for path in sorted((root / DIR).glob("*.json")):
        out.append(dict(json.loads(path.read_text(encoding="utf-8")), _where=f"{DIR}/{path.name}"))
    return out


def added(git: Callable[..., str], base: str, head: str) -> List[Dict[str, Any]]:
    """The entries the change base..head adds: a line added to the .jsonl, or a file added under
    docs/defect-ledger/ (read at head)."""
    entries = [json.loads(line[1:]) for line in git("diff", base, head, "--", LEGACY).splitlines()
               if line.startswith("+{")]
    for name in git("diff", "--name-only", "--diff-filter=A", base, head, "--", DIR).splitlines():
        if name.strip().endswith(".json"):
            entries.append(json.loads(git("show", f"{head}:{name.strip()}")))
    return entries
