#!/usr/bin/env python3
"""Decide the next release version from the labels of the PRs merged since the last tag.

Used by .github/workflows/release.yml. Replaces the earlier release-drafter "dry-run" call,
which (a) was not a dry run at all -- `dry-run` is not an input of release-drafter v6, the
warning was ignored, and the step rewrote the draft release on every run -- and (b) could
never say "nothing to release": release-drafter's `exclude-labels` only hides PRs from the
notes, the version resolver still applies `default: patch`, so a merge of nothing but chore
PRs resolved to last+patch and 1.0.4 was published for a workflow-only change (2026-09-11).

Rules (same label vocabulary as .github/release-drafter.yml, so the autolabeler and a human
reading the PR see the same thing):

  dependencies (Dependabot)          -> not releasable, whatever else it carries: Dependabot
                                        labels its own semver-major bumps of an *action* `major`
                                        (actions/checkout 4->7 blocked 1.4.9 on 2026-09-12); a
                                        dependency pin is never this package's major
  major                              -> refuse (exit 2): a major is a hand edit of package.json
  minor / feature / enhancement      -> minor
  patch / fix / bug                  -> patch
  only chore / ci / docs / dependencies (or any other label) -> not releasable
  no label at all                    -> patch (a PR nobody labelled still ships)

The labels are not the only evidence (3.13.2, 2026-11-19): the autolabeler reads a PR's title,
and four PRs titled without a fix/feat prefix carried only `chore` (every PR touches a .md), so a
new flag, a new result field and two fixes sat on main unreleased. Two facts of the tree now set
a floor under the labels:

  a commit that changes shipped code (SHIPPED_CODE, not a .md) -> at least patch, unless it is a
                                        Dependabot PR or the release's own bump commit
  the contract gained a tool, a flag or a result field since the last tag -> minor, when
                                        anything is released at all

A PR with `chore` AND `fix` is a fix. A commit on main that came from no PR is treated as
patch unless its subject starts with chore/ci/docs/build (the autolabeler's own title rules).

Which PR a commit came from: the "(#N)" GitHub puts at the end of a squash subject, and, when
the subject does not end with one, the merged PR whose merge commit is that SHA (a failed lookup stops the job). 3.2.3 was a
patch for three features because the squash subject ended "(#433, carries #432 and #434)": the
subject matched nothing, the PR's `feature` label was never read, and the commit counted as a
direct push.
If nothing since the last tag is releasable, the resolved version is empty and release.yml
does nothing.

Pure logic lives in resolve(); the CLI wraps it with `git log` and `gh api`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Iterable, List, Optional, Tuple

MAJOR = {"major"}
MINOR = {"minor", "feature", "enhancement"}
PATCH = {"patch", "fix", "bug"}
NOT_RELEASABLE_TITLE = re.compile(r"^(chore|ci|docs|build)\b", re.I)
PR_NUMBER = re.compile(r"\(#(\d+)\)\s*$")
# What `npm publish` ships and a user runs (package.json "files"), less the documents: a change
# under one of these is a change to the product whatever the PR was titled or labelled.
SHIPPED_CODE = ("scripts/", "mcp/", "bin/", "templates/")
RELEASE_COMMIT = re.compile(r"^chore\(release\): bump version to ")


def changes_shipped_code(paths: Iterable[str]) -> bool:
    """True when one of a commit's changed paths is shipped code (not a document under it)."""
    return any(p.startswith(SHIPPED_CODE) and not p.lower().endswith(".md") for p in paths)


def contract_surface(doc: Dict[str, object]) -> set:
    """The names a caller can depend on in a contract document (`_contract.py --json`): every
    tool, every flag of its input schema with each spelling it accepts on the command line (a
    second spelling of an existing flag is a new name too), and every field of its output schema."""
    surface = set()
    for tool in doc.get("tools") or []:
        name = tool.get("name")
        surface.add(("tool", name, ""))
        for kind, key in (("flag", "input_schema"), ("field", "output_schema")):
            for prop, spec in ((tool.get(key) or {}).get("properties") or {}).items():
                surface.add((kind, name, prop))
                cli = spec.get("cli") if kind == "flag" and isinstance(spec, dict) else None
                for spelling in (cli if isinstance(cli, list) else []):  # a positional's is the marker "positional"
                    surface.add(("spelling", name, spelling))
    return surface


def contract_additions(old: Optional[Dict[str, object]], new: Optional[Dict[str, object]]) -> List[Tuple[str, str, str]]:
    """What the new contract has that the old one lacks, sorted. Empty when either is unknown:
    a floor that cannot be measured is not applied (the shipped-code floor does not depend on it)."""
    if not old or not new:
        return []
    return sorted(contract_surface(new) - contract_surface(old))


def bump_for_labels(labels: Iterable[str]) -> Optional[str]:
    """'major' / 'minor' / 'patch' / None (not releasable) for one PR's labels."""
    names = {l.lower() for l in labels}
    if "dependencies" in names:
        return None
    if names & MAJOR:
        return "major"
    if names & MINOR:
        return "minor"
    if names & PATCH:
        return "patch"
    if not names:
        return "patch"
    return None


def resolve(last_version: str, subjects: List[str],
            labels_for: Callable[[int], List[str]],
            shas: Optional[List[str]] = None,
            pr_for_sha: Optional[Callable[[str], Optional[int]]] = None,
            paths_for: Optional[Callable[[str], List[str]]] = None,
            contract_added: Optional[List[Tuple[str, str, str]]] = None,
            ) -> Tuple[Optional[str], List[Dict[str, object]]]:
    """Return (next_version or None, per-commit decisions).

    subjects: commit subjects on main since the last tag, newest first (git log order).
    labels_for: PR number -> its label names.
    shas, pr_for_sha: the commits' SHAs (same order as subjects) and SHA -> the number of the
    merged PR it is the merge commit of (None when there is none). Asked only for a subject that
    does not end with "(#N)".
    paths_for: SHA -> the paths that commit changed; a commit the labels call not releasable is a
    patch when it changed shipped code (`floor: "shipped_code"` in its decision).
    contract_added: contract_additions() over the range; non-empty turns a release into a minor.
    """
    decisions: List[Dict[str, object]] = []
    bumps: List[str] = []
    for i, subject in enumerate(subjects):
        m = PR_NUMBER.search(subject)
        number: Optional[int] = int(m.group(1)) if m else None
        if number is None and shas and pr_for_sha:
            number = pr_for_sha(shas[i])
        if number is not None:
            labels = labels_for(number)
            bump = bump_for_labels(labels)
            decisions.append({"subject": subject, "pr": number, "labels": sorted(labels), "bump": bump})
            exempt = "dependencies" in {l.lower() for l in labels}
        else:
            bump = None if NOT_RELEASABLE_TITLE.match(subject) else "patch"
            decisions.append({"subject": subject, "pr": None, "labels": [], "bump": bump})
            exempt = bool(RELEASE_COMMIT.match(subject))
        if bump is None and not exempt and shas and paths_for and changes_shipped_code(paths_for(shas[i])):
            bump = "patch"
            decisions[-1].update(bump=bump, floor="shipped_code")
        if bump:
            bumps.append(bump)
    if not bumps:
        return None, decisions
    if "major" in bumps:
        raise SystemExit(
            "refusing to resolve a major version automatically; a major release is a deliberate, "
            "hand-made package.json bump in a PR (see docs/contract.md, Stability guarantee)")
    parts = [int(p) for p in last_version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[:3]
    if "minor" in bumps or contract_added:
        return f"{major}.{minor + 1}.0", decisions
    return f"{major}.{minor}.{patch + 1}", decisions


def _gh_labels(repo: str) -> Callable[[int], List[str]]:
    def labels_for(number: int) -> List[str]:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", "[.labels[].name]"],
            capture_output=True, text=True, check=True).stdout
        return list(json.loads(out or "[]"))
    return labels_for


def _gh_pr_for_sha(repo: str) -> Callable[[str], Optional[int]]:
    def pr_for_sha(sha: str) -> Optional[int]:
        # Only the PR this commit is the merge commit of: the endpoint also lists every PR that
        # merely contains the commit. An empty answer is "no PR" (a direct push). A failed request
        # is not: falling back to the title rules is exactly how a feature became a patch, so the
        # job stops and can be re-run.
        proc = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits/{sha}/pulls", "--jq",
             f'[.[] | select(.merged_at != null and .merge_commit_sha == "{sha}") | .number]'],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"could not look up the pull request of {sha[:9]} (re-run the job): "
                             f"{proc.stderr.strip()[:300]}")
        numbers = json.loads(proc.stdout or "[]")
        return int(numbers[0]) if numbers else None
    return pr_for_sha


def _git_paths(sha: str) -> List[str]:
    out = subprocess.run(["git", "show", "--format=", "--name-only", sha],
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def _contract_at(rev: Optional[str]) -> Optional[Dict[str, object]]:
    """`_contract.py --json` of the working tree (rev None) or of a tag, read from an export of
    that tag's scripts/. None when it cannot be produced: the caller then applies no contract floor."""
    import tempfile

    def read(script: str) -> Dict[str, object]:
        # UTF-8 both ways: the document holds non-ASCII text, and a Windows console code page
        # cannot print it (the child failed there with the default encoding)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        return json.loads(subprocess.run([sys.executable, script, "--json"], capture_output=True, text=True,
                                         encoding="utf-8", env=env, check=True, timeout=120).stdout)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        if rev is None:
            return read(os.path.join(root, "scripts", "_contract.py"))
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.run(["git", "-C", root, "archive", rev, "scripts"], capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
            return read(os.path.join(tmp, "scripts", "_contract.py"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"  contract at {rev or 'HEAD'} not read ({type(exc).__name__}): no contract floor")
        return None


def main() -> int:
    last = os.environ["LAST_VERSION"]
    repo = os.environ["GITHUB_REPOSITORY"]
    rev_range = f"v{last}..HEAD" if last != "0.0.0" else "HEAD"
    pairs = [line.split(" ", 1) for line in subprocess.run(
        ["git", "log", rev_range, "--format=%H %s"], capture_output=True, text=True, check=True
    ).stdout.splitlines() if line.strip()]
    pairs = [p for p in pairs if len(p) == 2 and p[1].strip()]
    subjects = [p[1] for p in pairs]
    shas = [p[0] for p in pairs]
    added = contract_additions(_contract_at(f"v{last}"), _contract_at(None)) if last != "0.0.0" else []
    version, decisions = resolve(last, subjects, _gh_labels(repo), shas, _gh_pr_for_sha(repo),
                                 _git_paths, added)
    if added:
        print(f"  contract gained {len(added)} name(s) since v{last}: "
              + ", ".join(f"{kind} {tool} {name}".strip() for kind, tool, name in added[:8])
              + (" ..." if len(added) > 8 else ""))
    for d in decisions:
        tag = (d["bump"] or "-") + ("*" if d.get("floor") else "")
        print(f"  {tag:6} {'#' + str(d['pr']) if d['pr'] else '(no PR)':8} {','.join(d['labels']) or '(unlabeled)':30} {d['subject']}")
    print(f"last tag v{last} -> {'no release' if version is None else version}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        fh.write(f"resolved_version={version or ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
