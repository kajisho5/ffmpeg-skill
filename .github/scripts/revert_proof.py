#!/usr/bin/env python3
"""Does a change's own test fail without the change?

A regression test that passes on the code it was written against proves nothing, and "I saw it
fail first" is a sentence in a PR body. This runs the tests a change added or edited against the
base's shipped code (scripts/, mcp/) with the head's tests, and reports which of them fail there.

    python3 .github/scripts/revert_proof.py --base origin/main [--head HEAD]

Exit 0: the change touches no shipped code, or at least one of its tests fails on the base code.
Exit 1: shipped code changed and no added or edited test fails without it (or there is none).
A test that passes on the base is listed as pinning behaviour that was already there; that is
allowed beside one that fails. A change that is meant to alter no behaviour says so in its title
(refactor:, chore:, docs:, ci:, test:, build:), given as --title, and is not judged.
"""
import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

SHIPPED = ("scripts/", "mcp/")
_spec = importlib.util.spec_from_file_location("resolve_version", pathlib.Path(__file__).with_name("resolve_version.py"))
RESOLVER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RESOLVER)
LEDGER = "docs/defect-ledger.jsonl"
EXEMPT_TITLE = re.compile(r"^(refactor|chore|docs|ci|test|build)\b", re.I)
HUNK_TEST = re.compile(r"^@@ .* @@.*\bdef (test_\w+)")
ADDED_TEST = re.compile(r"^\+\s+def (test_\w+)\(")


def git(*args: str, cwd: str = ".") -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def changed_tests(diff: str) -> "dict[str, list[str]]":
    """module -> test names the diff adds or edits (the enclosing `def test_` of each hunk)."""
    found: "dict[str, list[str]]" = {}
    module = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            m = re.match(r"\+\+\+ b/tests/(test_\w+)\.py$", line)
            module = m.group(1) if m else None
        elif module:
            m = HUNK_TEST.match(line) or ADDED_TEST.match(line)
            if m and m.group(1) not in found.setdefault(module, []):
                found[module].append(m.group(1))
    return {k: v for k, v in found.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--title", default="")
    ap.add_argument("--no-ledger", action="store_true", help="do not ask for a ledger line (history before #632)")
    args = ap.parse_args()
    base = git("merge-base", args.base, args.head).strip()
    names = git("diff", "--name-only", base, args.head).splitlines()
    shipped = [n for n in names if n.startswith(SHIPPED) and not n.lower().endswith(".md")]
    if not shipped:
        print("no shipped code changed: nothing to prove")
        return 0
    if EXEMPT_TITLE.match(args.title):
        print(f"title {args.title!r} declares no behaviour change: not judged")
        return 0
    fixes = re.match(r"fix\b", args.title, re.I) or any(
        line.startswith("+- ") for line in git("diff", base, args.head, "--", "CHANGELOG.md").splitlines())
    if fixes and LEDGER not in names and not args.no_ledger:
        print(f"a fix adds a line to {LEDGER}: the defect's class, why it got through, and the mechanism "
              "changed so the class cannot recur (#632)")
        return 1
    budget = json.loads(git("show", f"{args.head}:.github/code-budget.json"))
    if fixes:
        net = sum(int(a) - int(r) for a, r, name in (line.split("\t") for line in git(
            "diff", "--numstat", base, args.head, "--", *SHIPPED).splitlines()) if name.endswith(".py") and a != "-")
        limit = budget.get("fix_max_net_lines")
        reasons = [json.loads(line[1:]).get("size_reason") for line in git("diff", base, args.head, "--", LEDGER).splitlines()
                   if line.startswith("+{")]
        if limit is not None and net > limit and not any(reasons) and not args.no_ledger:
            print(f"this fix adds {net} net lines to shipped code (limit {limit}): prefer a refusal or removing a mode, "
                  f"or give the reason as size_reason in its {LEDGER} line")
            return 1
    if budget.get("feature_freeze"):
        added = RESOLVER.contract_additions(RESOLVER._contract_at(base), RESOLVER._contract_at(args.head))
        if added:
            print("feature freeze (.github/code-budget.json): this change adds to the contract: "
                  + ", ".join(" ".join(x).strip() for x in added[:8]) + (" ..." if len(added) > 8 else ""))
            return 1
    tests = changed_tests(git("diff", "--function-context", base, args.head, "--", "tests"))
    if not tests:
        print(f"{len(shipped)} shipped file(s) changed and no test was added or edited")
        return 1
    failing, passing = [], []
    with tempfile.TemporaryDirectory() as tmp:
        git("worktree", "add", "--detach", "-q", tmp, args.head)
        try:
            git("checkout", base, "--", *SHIPPED, cwd=tmp)  # the base's code under the head's tests
            for module, cases in tests.items():
                for case in cases:
                    proc = subprocess.run([sys.executable, "-m", "unittest", f"tests.{module}", "-k", case],
                                          cwd=tmp, capture_output=True, text=True, timeout=1800)
                    (failing if proc.returncode else passing).append(f"{module}.{case}")
        finally:
            git("worktree", "remove", "--force", tmp)
    for name in failing:
        print(f"  fails without the change   {name}")
    for name in passing:
        print(f"  passes without the change  {name}  (pins behaviour that was already there)")
    if failing:
        return 0
    print("no added or edited test fails on the base code: the change is not shown to do anything")
    return 1


if __name__ == "__main__":
    sys.exit(main())
