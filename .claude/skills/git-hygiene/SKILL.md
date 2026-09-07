---
name: keeping-git-repos-clean
description: Prevents, detects, and remediates files that should never be committed — secrets (.env, API tokens, hardcoded credentials) and dev artifacts (build output, scratch databases, editor/OS files). Covers .gitignore (and why it does not untrack), git rm --cached, auditing tracked files, history scrubbing, and credential rotation. Use when a repo has committed secrets or junk, when setting up a new repo's ignore rules, or when reviewing what a repo actually tracks.
---

# Keeping Git Repos Clean

Two classes of files keep ending up in repos: **secrets** and **dev artifacts**.
Both are cheap to prevent and expensive to clean up after the fact, because git
history is forever and public repos publish everything.

## The one rule everyone forgets

**`.gitignore` does NOT untrack files that are already committed.** Adding a path
to `.gitignore` only prevents *future untracked* files from being staged. A file
git is already tracking keeps getting committed regardless. This bites repeatedly:
a `.env` is listed in `.gitignore` but was committed before the rule existed, so
it keeps shipping.

To actually stop tracking a file while keeping your local copy:

```bash
git rm --cached path/to/file        # untrack, leave working-tree copy in place
git rm -r --cached some/dir/        # for a directory
echo "path/to/file" >> .gitignore   # then ignore it so it doesn't come back
git commit -m "Stop tracking <file>; add to .gitignore"
```

`--cached` is the important flag — plain `git rm` deletes the working copy too.

## Audit what a repo actually tracks

Don't trust `.gitignore` to tell you what's clean — read the index directly:

```bash
git ls-files | grep -iE '\.(env|pem|key|p12|profraw|log|bak|db|sqlite3?)$'
git ls-files | grep -iE '(^|/)(\.DS_Store|~\$|todo\.db|node_modules/|__pycache__/)'
git ls-files '*.db' '*.sqlite*'                 # scratch databases
git ls-files | xargs -I{} du -h {} | sort -rh | head   # surprisingly large tracked files
```

Usual suspects seen across real repos:

- **Secrets:** `.env` with a live token, hardcoded `AWS_*`/DB creds in a settings
  module, `SECRET_KEY = "CHANGEME"`/`"foobar"` placeholders shipped to prod.
- **Build artifacts:** LaTeX `.aux/.toc/.log/.synctex.gz/.pdf`, LLVM `*.profraw`,
  compiled binaries, `htmlcov/`, `dist/`, `*.egg-info/`.
- **Scratch / personal artifacts:** `todo.db` and other tool-local SQLite scratch
  DBs, editor backups (`*.backup`, `*.bak`, `~$*.docx` Word lock files), stray
  `*.log`.
- **OS noise:** `.DS_Store`, `Thumbs.db`.

## Secrets need more than `git rm`

Removing a secret from `HEAD` does **not** remove it from history — `git log -p`
and the commit that introduced it still expose it. Three things must happen, in
order, and the first is the only one that actually protects you:

1. **Rotate the credential.** Treat any secret that ever touched a remote as
   compromised. Issue a new token/key/password and revoke the old one. Do this
   first — the leaked value is public the moment it was pushed.
2. **Untrack going forward** (`git rm --cached` + `.gitignore` + `.env.example`
   documenting which vars are needed, with placeholder values only).
3. **Scrub history** if required (`git filter-repo --invert-paths --path .env`,
   or BFG) and force-push. This rewrites SHAs and disrupts collaborators, so it's
   usually a deliberate maintainer step done after rotation — not an automated PR.

A PR that does (2) and (3) but skips (1) gives false comfort: the value is still
valid and still in history clones/forks. Always call out rotation as the required
human follow-up.

## "Committed" means "published"

For public repos — and especially static sites deployed with `path: '.'`
(GitHub Pages uploads the entire repo) — every tracked file is fetchable at a
public URL. A scratch `todo.db` at the repo root of a brochure site is served at
`/todo.db`. Before committing to any public repo, assume anyone can download it.

## Prevent it: global ignore + a secret scanner

Per-developer noise (editor files, OS files, tool scratch DBs like `todo.db`)
should be ignored **globally**, not in every project's `.gitignore` — that way it
never lands anywhere:

```bash
git config --global core.excludesFile ~/.gitignore_global
printf '%s\n' '.DS_Store' '*.swp' 'todo.db' '*.profraw' >> ~/.gitignore_global
```

Block secrets at commit time with a pre-commit hook so they never reach history:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks: [{id: gitleaks}]
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks: [{id: detect-secrets, args: ["--baseline", ".secrets.baseline"]}]
```

A starter project `.gitignore` (commit this):

```gitignore
# Secrets / local config
.env
.env.*
!.env.example
*.pem
*.key

# Python build/test artifacts
__pycache__/
*.py[cod]
build/
dist/
*.egg-info/
.coverage
htmlcov/
.pytest_cache/

# Scratch / OS / editor
*.db
*.sqlite
*.sqlite3
*.profraw
*.log
*.bak
*.backup
.DS_Store
~$*
```

## Verification can dirty the tree

Compilers, test runners, and asset pipelines often write into the checkout even
when the command is only meant to verify a change. They may create unignored
cache files or regenerate a tracked distributable such as a PDF or compiled CSS.
A green command does not mean the working tree still contains only your change.

Bracket verification with status checks and stage only reviewed paths:

```bash
git status --short
make test                         # or the project's real build command
git status --short
git diff -- path/you/changed
git add path/you/changed          # never sweep in generated files with git add -A
git diff --cached --check
git diff --cached --stat
```

If a tool necessarily produces noisy output, run it in a disposable copy of the
checkout. This preserves a real build while keeping generated files away from
the patch:

```bash
scratch_dir=$(mktemp -d)
rsync -a --exclude .git ./ "$scratch_dir/"
(cd "$scratch_dir" && make build)
```

When verification modifies a tracked generated output that is intentionally out
of scope, restore **that exact path only after reviewing its diff**:

```bash
git diff -- docs/manual.pdf
git restore -- docs/manual.pdf
```

Do not use a broad restore/reset to clean up: the checkout may already contain
someone else's work. Also do not rely on `git stash` as cleanup for untracked
artifacts; ordinary stashes omit them, and even `--include-untracked` can collide
with files regenerated before `stash pop`. Prevent or remove known generated
paths explicitly instead.

## Checklist

```
Audit:
- [ ] `git ls-files` reviewed for secrets, build output, scratch DBs, OS files
- [ ] No live credentials in tracked source or .env
- [ ] No surprisingly large/binary tracked files

Remediate (if dirty):
- [ ] Secret rotated/revoked FIRST (history is public the moment it was pushed)
- [ ] `git rm --cached` + .gitignore entry for each offending file
- [ ] .env.example documents required vars with placeholder values only
- [ ] History scrub flagged as a maintainer follow-up if the secret is in history

Prevent:
- [ ] Project .gitignore covers secrets, build artifacts, OS/editor noise
- [ ] Global core.excludesFile catches per-developer scratch files
- [ ] gitleaks / detect-secrets pre-commit hook installed
- [ ] Verification bracketed by `git status --short`; only reviewed paths staged
```

For scanning source code for vulnerabilities and hardcoded-secret *patterns*
rather than what git tracks, use the `/security-review` skill already available
in this session.

## Note for this repository (ffmpeg-skill)

`.gitignore` already covers `__pycache__/`, and `package.json`'s `"files"` list
is the actual publish gate — but this session hit exactly the "verification can
dirty the tree" case: running `python3 scripts/proxy.py` and the test suites
locally created `__pycache__/*.pyc` files that then showed up in an `npm
publish --dry-run` listing before they were deleted. The `git status --short`
bracket-and-check habit above (or, cheaper here, just re-running the dry-run
after deleting stray `__pycache__/` directories) is the concrete fix. There
are no secrets or `.env`-shaped files in this repo (no cloud/API keys by
design), so the credential-rotation half of this skill does not currently
apply — the dev-artifact half is the one worth watching.

Source: [wdm0006/python-skills](https://github.com/wdm0006/python-skills) (MIT).
