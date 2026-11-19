#!/usr/bin/env python3
"""Where the code that fixes change came from: the two numbers of the error budget (#632).

For every fix merged to main in a window, blame the lines it changed in scripts/ and mcp/ at the
commit before it, and count whose lines they were: an earlier fix, a feature, or anything else.

  fix_of_fix_share          lines a fix changed that an earlier fix had written / all such lines
  median_net_lines_per_fix  median of (added - removed) Python lines per fix

`.github/code-budget.json` holds the limits. A commit is a fix or a feature by its PR's labels
when --labels gives them (a TSV of number, comma-separated labels), else by its subject's
prefix (fix / feat / add): a title without a prefix counts as neither, so without --labels the
shares are a floor, and the output says which was used.

  python3 .github/scripts/fix_origins.py --since 2026-11-01 [--until DATE] [--labels prs.tsv] [--rev origin/main]
"""
import argparse
import collections
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ("scripts", "mcp")


def git(*args):
    """git's stdout; a git that fails stops the measurement (an unreadable history is not an
    empty window)."""
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode:
        raise SystemExit(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def kind_of(subject, labels):
    """"release", "fix", "feature" or "other" for a first-parent commit of main."""
    s = subject.lower()
    if s.startswith("chore(release)"):
        return "release"
    if "dependencies" in labels:
        return "other"
    # a fix or feature label decides; the subject's prefix only when none does (`chore` alone is
    # not a decision: the autolabeler adds it to every PR that touches a .md file, #631)
    if labels & {"fix", "bug", "patch"}:
        return "fix"
    if labels & {"feature", "enhancement", "minor"}:
        return "feature"
    if re.match(r"fix\b", s):
        return "fix"
    if re.match(r"(feat|add)\b", s):
        return "feature"
    return "other"


def changed_ranges(diff):
    """(file, first line, count) of the old side of every hunk in a -U0 diff of Python files."""
    out, cur = [], None
    for line in diff.splitlines():
        if line.startswith("--- "):
            cur = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("@@") and cur and cur.endswith(".py"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? ", line)
            count = int(m.group(2) or 1)
            if count:
                out.append((cur, int(m.group(1)), count))
    return out


def net_lines(diff):
    """Added minus removed lines of Python files in a diff."""
    net, py = 0, False
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            py = line.endswith(".py")
        elif py and line.startswith("+") and not line.startswith("+++"):
            net += 1
        elif py and line.startswith("-") and not line.startswith("---"):
            net -= 1
    return net


def authors_of(sha, ranges):
    """Counter of the commits that wrote the code lines a fix changed (comments and blanks apart)."""
    seen = collections.Counter()
    for path, first, count in ranges:
        blame = git("blame", "-w", "--line-porcelain", "-L", f"{first},{first + count - 1}", sha + "^", "--", path)
        author = None
        for line in blame.splitlines():
            m = re.match(r"^([0-9a-f]{40}) \d+ \d+", line)
            if m:
                author = m.group(1)
            elif line.startswith("\t") and author:
                code = line[1:].strip()
                if code and not code.startswith("#"):
                    seen[author] += 1
    return seen


def measure(rev, since, until, labels):
    log = git("log", "--first-parent", rev, "--format=%H\t%cI\t%s")
    commits = [line.split("\t", 2) for line in log.splitlines()]
    kinds = {}
    for sha, _, subject in commits:
        m = re.search(r"\(#(\d+)\)\s*$", subject)
        kinds[sha] = kind_of(subject, labels.get(int(m.group(1)), set()) if m else set())
    by, sizes, fixes = collections.Counter(), [], 0
    for sha, when, _ in commits:
        if kinds[sha] != "fix" or when[:10] < since or (until and when[:10] >= until):
            continue
        diff = git("diff", "-U0", "--no-color", sha + "^", sha, "--", *SHIPPED)
        ranges = changed_ranges(diff)
        if not diff.strip():
            continue
        fixes += 1
        sizes.append(net_lines(diff))
        for author, n in authors_of(sha, ranges).items():
            by[kinds.get(author, "other")] += n
    total = sum(by.values())
    return {
        "since": since, "until": until, "rev": rev, "kinds_from": "labels" if labels else "subject prefix (a floor)",
        "fixes": fixes, "lines_changed": total,
        "fix_of_fix_share": round(by["fix"] / total, 3) if total else None,
        "feature_share": round(by["feature"] / total, 3) if total else None,
        "median_net_lines_per_fix": statistics.median(sizes) if sizes else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", required=True, help="first day counted, YYYY-MM-DD (committer date)")
    ap.add_argument("--until", help="first day not counted")
    ap.add_argument("--rev", default="origin/main")
    ap.add_argument("--labels", help="TSV: PR number, comma-separated labels[, anything]")
    a = ap.parse_args(argv)
    labels = {}
    if a.labels:
        for line in Path(a.labels).read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if cols[0].isdigit():
                labels[int(cols[0])] = set(filter(None, cols[1].split(","))) if len(cols) > 1 else set()
    doc = measure(a.rev, a.since, a.until, labels)
    budget = json.loads((ROOT / ".github" / "code-budget.json").read_text(encoding="utf-8"))["budget"]
    doc["over_budget"] = [k for k, limit in (("fix_of_fix_share", budget["fix_of_fix_share_max"]),
                                             ("median_net_lines_per_fix", budget["median_net_lines_per_fix_max"]))
                          if doc[k] is not None and doc[k] > limit]
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
