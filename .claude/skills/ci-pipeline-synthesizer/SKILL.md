---
name: ci-pipeline-synthesizer
description: Generate GitHub Actions CI/CD pipeline configurations for automated building and testing of library and package projects. Use when creating or updating CI workflows for npm packages, Python packages, Go modules, Rust crates, or other library projects that need automated build and test pipelines. Includes templates for common package ecosystems with best practices for dependency caching, matrix testing, and artifact publishing.
---

# CI Pipeline Synthesizer

## Overview

Generate production-ready GitHub Actions workflow files for library and package projects with automated build and test stages, dependency caching, and multi-version testing matrices.

## Workflow

### 1. Identify Project Type

Determine the package ecosystem by examining project files:
- **Node.js/npm**: `package.json` present
- **Python**: `setup.py`, `pyproject.toml`, or `requirements.txt` present
- **Go**: `go.mod` present
- **Rust**: `Cargo.toml` present

### 2. Select Template

Use the appropriate template from `assets/` based on project type:
- `github-actions-nodejs.yml` - Node.js/npm packages
- `github-actions-python.yml` - Python packages
- `github-actions-go.yml` - Go modules
- `github-actions-rust.yml` - Rust crates

### 3. Customize Configuration

Adapt the template to project-specific needs:

**Test commands**: Update test scripts to match project conventions
- Node.js: `npm test`, `npm run test:coverage`
- Python: `pytest`, `python -m unittest`
- Go: `go test ./...`
- Rust: `cargo test`

**Build commands**: Adjust build steps if needed
- Node.js: `npm run build` (if build step exists)
- Python: `python -m build`
- Go: `go build`
- Rust: `cargo build --release`

**Version matrix**: Modify tested versions based on support policy
- Node.js: LTS versions (16.x, 18.x, 20.x)
- Python: Active versions (3.9, 3.10, 3.11, 3.12)
- Go: Recent versions (1.21, 1.22)
- Rust: stable, beta (optional)

**Trigger conditions**: Adjust when pipeline runs
- Default: Push to main/master, all pull requests
- Custom: Specific branches, paths, or schedules

### 4. Place Workflow File

Create the workflow file at `.github/workflows/ci.yml` in the project root. If `.github/workflows/` doesn't exist, create the directory structure first.

### 5. Verify Configuration

Check that the generated workflow:
- Uses appropriate actions versions (e.g., `actions/checkout@v4`, `actions/setup-node@v4`)
- Includes dependency caching for faster builds
- Runs on appropriate triggers (push, pull_request)
- Tests against relevant version matrices
- Has clear job and step names

## Template Features

All templates include:
- **Dependency caching**: Speeds up builds by caching package managers
- **Matrix testing**: Tests across multiple language/runtime versions
- **Parallel execution**: Runs tests for different versions concurrently
- **Clear naming**: Descriptive job and step names for easy debugging
- **Best practices**: Uses recommended actions and configurations

## Customization Examples

**Add code coverage reporting**:
```yaml
- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

**Add linting step**:
```yaml
- name: Run linter
  run: npm run lint  # or: pylint, golangci-lint, cargo clippy
```

**Restrict to specific branches**:
```yaml
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
```

**Add scheduled runs**:
```yaml
on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday
```

## Tips

- Start with the template and customize incrementally
- Test the workflow by creating a pull request or pushing to a test branch
- Use `actions/cache` for dependencies to reduce build times
- Keep matrix versions current with language support policies
- Add status badges to README.md: `![CI](https://github.com/user/repo/workflows/CI/badge.svg)`

## Note for this repository (ffmpeg-skill)

This skill's generic templates assume ordinary language-toolchain dependencies
(pip/npm/go/cargo). They do NOT model this repo's actual CI needs — installing
a real `ffmpeg` binary per OS (apt/brew ffmpeg-full/choco), capturing its
`-filters`/`-encoders`/`-bsfs` listings as an artifact, or the `skipIf`-based
Windows test coverage in `tests/test_contract.py` — all of which
`.github/workflows/ci.yml` already handles and this skill's templates would
not reproduce. Treat this as reference/scaffolding for a plain Python/Node/Go/
Rust package elsewhere, not a drop-in replacement for this repo's own
workflow.
