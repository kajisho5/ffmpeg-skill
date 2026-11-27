# Changelog fragments

One file per change, so two open PRs never edit the same lines of `CHANGELOG.md` (#678).

`changelog.d/<slug>.md`, for example `changelog.d/678-fragments.md`. The file starts with its
section heading, then its bullet or bullets:

```markdown
### Fixed

- `grid.py` keeps the colours of an untagged clip (#696).
```

The heading is `### Fixed`, `### Added` or `### Changed`. A fix PR needs a `### Fixed` fragment
(`revert_proof.py` counts it as a fix note) and names the issue it closes, as
`test_changelog_mentions_every_closed_issue_since_last_tag` expects.

Do not edit `## Unreleased` in `CHANGELOG.md`; it stays `(nothing yet)`. The release job
(`.github/workflows/release.yml`, `.github/scripts/changelog_fragments.py`) writes the new
version's section from, in this order: text still under `## Unreleased` (a branch opened before
fragments), the fragments grouped Fixed / Added / Changed, then the generated commit-subject
bullets. The same commit deletes the fragments. This README is never folded in.
