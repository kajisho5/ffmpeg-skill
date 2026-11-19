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
import ast
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
DEF_LINE = re.compile(r"^[ +](\s+)def (\w+)\(")
OLD_DEF_LINE = re.compile(r"^[ -](\s+)def (\w+)\(")


def git(*args: str, cwd: str = ".") -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_lines(source: str) -> "dict[int, tuple[str, str]]":
    """head line -> (class, test) for every line of a `test_` method, its decorators included,
    from the parsed module: a `class` line inside a string is not a class (review of #635)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    owner: "dict[int, tuple[str, str]]" = {}
    # outer classes first, so a nested class's tests overwrite the lines they own
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                    start = min([d.lineno for d in item.decorator_list] + [item.lineno])
                    for n in range(start, (item.end_lineno or item.lineno) + 1):
                        owner[n] = (node.name, item.name)
    return owner


def changed_tests(diff: str, read=lambda module: "") -> "dict[str, list[str]]":
    """module -> tests the diff adds or edits, as "Class.test_name". With `read(module)`, the
    head's source, each changed line is placed by the parsed module: two classes can hold a test
    of the same name and only the edited one is evidence, a decorator belongs to the test below
    it, and a deleted line belongs to the test around the gap (review of #635). Without a source
    (or one that does not parse) the enclosing `def test_` of each hunk is used, bare."""
    found: "dict[str, list[str]]" = {}
    module, current, depth, lineno, owner, old, old_depth = None, None, 0, 0, {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            m = re.match(r"\+\+\+ b/tests/(test_\w+)\.py$", line)
            module, current = (m.group(1) if m else None), None
            owner = test_lines(read(module)) if module else {}
        elif not module:
            continue
        elif line.startswith("@@"):
            m = HUNK_TEST.match(line)
            # the hunk header names the def it starts inside (a test method: four spaces deep)
            current, depth = (m.group(1), 4) if m else (None, 0)
            old, old_depth = current, depth
            lineno = int(re.match(r"@@ -\S+ \+(\d+)", line).group(1))
        else:
            m = DEF_LINE.match(line)
            # a def line, unchanged or added, opens the method the next lines belong to; one deeper
            # than the current test is a helper inside it and keeps the test (review of #635)
            if m and not (current and len(m.group(1)) > depth):
                current, depth = (m.group(2), len(m.group(1))) if m.group(2).startswith("test_") else (None, 0)
            m = OLD_DEF_LINE.match(line)
            # the test a deleted line was in, read on the base's side (a removed def counts)
            if m and not (old and len(m.group(1)) > old_depth):
                old, old_depth = m.group(2), len(m.group(1))
            if line[:1] in "+-":
                if owner:
                    # a deleted line sits between head lines lineno-1 and lineno: a decorator
                    # belongs to the def below the gap, anything else to the line above it
                    at = lineno if line[0] == "+" or line[1:].lstrip().startswith("@") else lineno - 1
                    hit = owner.get(at)
                    # a line of a test the change removed is no test's: the head's neighbour is not it
                    if hit and line[0] == "-" and not line[1:].lstrip().startswith("@") and hit[1] != old:
                        hit = None
                    name = f"{hit[0]}.{hit[1]}" if hit else None
                else:
                    # a changed line belongs to the test it sits in (a body-only edit counts, #635)
                    name = current
                if name and name not in found.setdefault(module, []):
                    found[module].append(name)
            if line[:1] != "-":
                lineno += 1
    return {k: v for k, v in found.items() if v}


def outcome(stderr: str, case: str) -> str:
    """"fails", "passes" or "unclear" for one test from `unittest -v` output. Only the test's own
    line counts: an import error or a failed setUpClass never reaches it, so the test did not run
    and proves nothing (review of #635); a skip proves nothing either."""
    name = re.escape(case)
    # unittest lists every failure of the test itself, a failing subTest included, as
    # "FAIL: name (...)" or "ERROR: name (...)"; a failed setUpClass or import has another name there
    if re.search(rf"^(FAIL|ERROR): {name} \(", stderr, flags=re.M):
        return "fails"
    # -v prints a docstring's first line after the name, on a line of its own
    m = re.search(rf"^{name} \([^)\n]*\)(?:\n[^\n]*?)? \.\.\. (ok|skipped|expected failure|unexpected success)",
                  stderr, flags=re.M)
    if not m:
        return "unclear"
    # an unexpected success is an assertion that held on the base: not a failure (review of #635)
    return {"ok": "passes", "unexpected success": "passes"}.get(m.group(1), "unclear")


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
    budget = json.loads(git("show", f"{args.head}:.github/code-budget.json"))
    # the freeze is about the contract, not about a title: it is checked before the exemption
    exception = budget.get("feature_freeze_exception") or {}
    version_at = lambda rev: json.loads(git("show", f"{rev}:package.json")).get("version")
    # the one exception the owner decided (#632) is the change that makes that version, not any later one
    excepted = bool(exception.get("version")) and version_at(args.head) == exception["version"] != version_at(base)
    if excepted:
        print(f"feature freeze: excepted for the change that makes {exception['version']} ({exception.get('decided', '')})")
    if budget.get("feature_freeze") and not excepted:
        before, after = RESOLVER._contract_at(base), RESOLVER._contract_at(args.head)
        if before is None or after is None:
            print("feature freeze (.github/code-budget.json): the contract could not be read at "
                  + ("the base" if before is None else "the head") + ", so its additions are not known")
            return 1
        added = RESOLVER.contract_additions(before, after)
        if added:
            print("feature freeze (.github/code-budget.json): this change adds to the contract: "
                  + ", ".join(" ".join(x).strip() for x in added[:8]) + (" ..." if len(added) > 8 else ""))
            return 1
    if EXEMPT_TITLE.match(args.title):
        print(f"title {args.title!r} declares no behaviour change: not judged")
        return 0
    fixes = re.match(r"fix\b", args.title, re.I) or any(
        line.startswith("+- ") for line in git("diff", base, args.head, "--", "CHANGELOG.md").splitlines())
    added_entries = [line for line in git("diff", base, args.head, "--", LEDGER).splitlines() if line.startswith("+{")]
    if fixes and not added_entries and not args.no_ledger:
        print(f"a fix adds a line to {LEDGER}: the defect's class, why it got through, and the mechanism "
              "changed so the class cannot recur (#632)")
        return 1
    if fixes:
        net = sum(int(a) - int(r) for a, r, name in (line.split("\t") for line in git(
            "diff", "--numstat", base, args.head, "--", *SHIPPED).splitlines()) if name.endswith(".py") and a != "-")
        limit = budget.get("fix_max_net_lines")
        reasons = [json.loads(line[1:]).get("size_reason") for line in added_entries]
        if limit is not None and net > limit and not any(reasons) and not args.no_ledger:
            print(f"this fix adds {net} net lines to shipped code (limit {limit}): prefer a refusal or removing a mode, "
                  f"or give the reason as size_reason in its {LEDGER} line")
            return 1
    tests = changed_tests(git("diff", "--function-context", base, args.head, "--", "tests"),
                          lambda module: git("show", f"{args.head}:tests/{module}.py"))
    if not tests:
        print(f"{len(shipped)} shipped file(s) changed and no test was added or edited")
        return 1
    failing, passing, unclear = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        git("worktree", "add", "--detach", "-q", tmp, args.head)
        try:
            # the base's code under the head's tests; --no-overlay also drops files the change added
            git("checkout", "--no-overlay", base, "--", *SHIPPED, cwd=tmp)
            for module, cases in tests.items():
                for case in cases:
                    # Class.test_name runs that one test; a bare name falls back to -k
                    target = [f"tests.{module}.{case}"] if "." in case else [f"tests.{module}", "-k", case]
                    try:
                        proc = subprocess.run([sys.executable, "-m", "unittest", "-v", *target],
                                              cwd=tmp, capture_output=True, text=True, timeout=1800)
                        verdict = outcome(proc.stderr, case.rsplit(".", 1)[-1])
                    except subprocess.TimeoutExpired:
                        # a test that did not finish proves nothing; the others still run (review of #635)
                        verdict = "unclear"
                    {"fails": failing, "passes": passing}.get(verdict, unclear).append(f"{module}.{case}")
        finally:
            git("worktree", "remove", "--force", tmp)
    for name in failing:
        print(f"  fails without the change   {name}")
    for name in passing:
        print(f"  passes without the change  {name}  (pins behaviour that was already there)")
    for name in unclear:
        print(f"  did not run on the base    {name}  (import, setUpClass, a skip or a timeout: not evidence either way)")
    if failing:
        return 0
    print("no added or edited test fails on the base code: the change is not shown to do anything")
    return 1


if __name__ == "__main__":
    sys.exit(main())
