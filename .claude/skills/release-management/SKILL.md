---
name: managing-python-releases
description: Manages Python library releases including semantic versioning, changelog maintenance (Keep a Changelog format), release automation with GitHub Actions, and deprecation workflows. Use when planning releases, writing changelogs, automating release pipelines, or communicating breaking changes.
---

# Release Management

## Semantic Versioning

```
MAJOR.MINOR.PATCH (e.g., 1.2.3)

PATCH: Bug fixes, no API changes
MINOR: New features, backward compatible
MAJOR: Breaking changes
```

## Changelog Format (Keep a Changelog)

```markdown
# Changelog

## [Unreleased]
### Added
- New `batch_encode()` function

## [1.2.0] - 2024-03-15
### Added
- Support for custom formats (#123)

### Fixed
- Edge case at -180 longitude (#145)

### Deprecated
- `old_function()` - use `new_function()` instead

[Unreleased]: https://github.com/user/repo/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/user/repo/releases/tag/v1.2.0
```

**Categories:** Added, Changed, Deprecated, Removed, Fixed, Security

## Version in Code

```python
# src/package/__init__.py
__version__ = "1.2.3"

# Or use importlib.metadata
from importlib.metadata import version
__version__ = version("my-package")
```

## GitHub Actions Release (PyPI example)

A tag-triggered workflow builds and publishes to a registry via trusted
publishing (no stored token) is the general shape — swap the publish step for
whatever registry the project actually uses (PyPI, npm, crates.io, ...):

```yaml
# .github/workflows/release.yml
on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write      # create the GitHub release
      id-token: write      # trusted publishing (no token)
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*
      - uses: pypa/gh-action-pypi-publish@release/v1
```

## Deprecation Process

Warn with `stacklevel=2` so the message points at the caller.

```python
import warnings

def old_function():
    """Deprecated: Use new_function() instead."""
    warnings.warn(
        "old_function() deprecated, will be removed in 2.0.0",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_function()
```

## Release Process

```bash
# 1. Update CHANGELOG.md (move Unreleased to version)
# 2. Bump version in the project manifest
# 3. Commit and tag
git commit -am "Release v1.2.0"
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin main --tags
# 4. CI publishes automatically (if automated) or publish manually
```

## Checklist

```
Before Release:
- [ ] All tests pass
- [ ] CHANGELOG updated
- [ ] Version bumped
- [ ] Documentation current

After Release:
- [ ] Registry shows new version
- [ ] A fresh install actually works (not just that the tag/publish succeeded)
- [ ] GitHub release created
- [ ] Docs updated
```

## Note for this repository (ffmpeg-skill)

`CHANGELOG.md` here keeps a `## Unreleased` section and one `## X.Y.Z` section
per version (no dates in the headings since the releases became automatic).
Two real differences from the generic PyPI example:

- **Releases are automatic; nothing is cut by hand.**
  `.github/workflows/release.yml` runs on every push to `main`: it resolves the
  next version from the merged PRs' labels (`.github/scripts/resolve_version.py`),
  bumps `package.json`, the plugin manifests, `server.json`, `docs/contract.md`
  and `docs/roadmap.md`, moves `## Unreleased` into the new version's section,
  pushes that commit, tags it, creates the GitHub Release, publishes to npm with
  provenance, the `plugin` branch and the MCP Registry entry. A PR writes its
  notes under `## Unreleased` and never bumps a version, except a major, which
  is a hand bump in a PR. A version that was tagged but did not reach npm is
  finished by the workflow's `recover` job (CONTRIBUTING.md, "Pull requests"),
  never by a local `npm publish`. (The 0.10.0 release was the last one done by
  hand, before the workflow existed.)
- **The registry is npm, not PyPI**, and there is no `__version__` in code —
  `scripts/_contract.py`'s `skill_version()` and `doctor`'s `version` field
  both read `package.json` directly (see this repo's own `concurrent-branches`
  and `build-artifacts` skill notes for the related merge-conflict and
  publish-verification patterns this touches).

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
