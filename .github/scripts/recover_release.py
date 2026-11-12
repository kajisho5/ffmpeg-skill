"""Decisions for release.yml's `recover` job (#448): finishing a tagged version npm never got.

The job publishes one version that already has its vX.Y.Z tag. Two questions here need a version
comparison, which bash does not have:

- Which npm dist-tag it goes out under. `latest` is what `npm install ffmpeg-skill` and
  `npx ffmpeg-skill` resolve, so it moves only to a version higher than every stable version npm
  already has. A version below one of those (a release that failed while a later one succeeded)
  goes out as `backport`, so `latest` never moves back.
- Whether the `plugin` branch may take the version. That branch only moves forward and hosts
  read its tip, so a version below the tip's is not published there.

    recover_release.py dist-tag VERSION VERSIONS_JSON   prints latest or backport
    recover_release.py newer VERSION OTHER              exit 0 when VERSION > OTHER, else 1

VERSIONS_JSON is a file holding `npm view <package> versions --json`: a JSON list, or a bare
string when npm has exactly one version. Versions other than X.Y.Z (pre-releases) are left out of
"the highest published version": a 4.0.0-rc.1 does not make 3.9.0 a backport.
"""
import json
import re
import sys

_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse(version: str) -> tuple:
    m = _VERSION.match(version)
    if not m:
        raise ValueError(f"not an X.Y.Z version: {version!r}")
    return tuple(int(part) for part in m.groups())


def dist_tag(version: str, published) -> str:
    """`latest` when `version` is above every stable published version, else `backport`."""
    if isinstance(published, str):
        published = [published]
    mine = parse(version)
    stable = [parse(v) for v in published if isinstance(v, str) and _VERSION.match(v)]
    if mine in stable:
        raise ValueError(f"npm already has {version}; there is nothing to recover")
    return "latest" if all(mine > other for other in stable) else "backport"


def main(argv) -> int:
    if len(argv) == 3 and argv[0] == "dist-tag":
        with open(argv[2], encoding="utf-8") as fh:
            published = json.load(fh)
        print(dist_tag(argv[1], published))
        return 0
    if len(argv) == 3 and argv[0] == "newer":
        return 0 if parse(argv[1]) > parse(argv[2]) else 1
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: recover_release.py dist-tag VERSION VERSIONS_JSON | newer VERSION OTHER", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as exc:
        print(f"recover_release.py: {exc}", file=sys.stderr)
        sys.exit(2)
