#!/usr/bin/env bash
# Publish the installable plugin tree to the `plugin` branch.
#
# A plugin host copies whatever its marketplace entry points at. Pointed at this repository's
# root, that is every tracked file (28 MB: tests, evals, site, brand, docs images), of which a
# running skill reads about 2.6 MB. The npm tarball is already that runtime set, chosen by
# package.json's `files`, so this script commits the tarball's contents plus the plugin manifest
# and the skills/ copy to an orphan-rooted branch that a marketplace entry can name with `ref`. Git is all a host needs to install it;
# an npm plugin source would need npm on the user's machine (Claude Code 2.1.322 and Codex
# 0.167 both shell out to it), which the plugin route has never required.
#
#   publish_plugin_branch.sh --tree-only DIR   build and check the tree in DIR, touch no git state
#   publish_plugin_branch.sh --no-push         also make the commit, print it, do not push
#   publish_plugin_branch.sh                   make the commit and push it to origin/plugin
#
# The branch only ever moves forward (each release is a commit on top of the last), so a host
# that fetched it before can fast-forward. Nothing here force-pushes.
set -euo pipefail

BRANCH="plugin"
MODE="push"
TREE_DIR=""
case "${1:-}" in
  --tree-only) MODE="tree"; TREE_DIR="${2:?--tree-only needs a directory}" ;;
  --no-push)   MODE="commit" ;;
  "")          ;;
  *) echo "unknown argument: $1" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

npm pack --silent --pack-destination "$WORK" >/dev/null
TARBALL="$(find "$WORK" -maxdepth 1 -name '*.tgz' | head -n 1)"
[ -n "$TARBALL" ] || { echo "npm pack wrote no tarball" >&2; exit 1; }

if [ "$MODE" = "tree" ]; then
  TREE="$TREE_DIR"
  mkdir -p "$TREE"
  [ -z "$(ls -A "$TREE")" ] || { echo "$TREE is not empty" >&2; exit 1; }
else
  TREE="$WORK/tree"
  mkdir "$TREE"
fi
tar -xzf "$TARBALL" -C "$TREE" --strip-components=1
# The npm package deliberately leaves these two out: `npx ffmpeg-skill` copies the package into
# an agent's skills folder, where a second SKILL.md under skills/ would be the same skill twice.
# A plugin host needs both: the manifest, and the skill where Codex and Gemini look for it.
mkdir -p "$TREE/.claude-plugin" "$TREE/skills/ffmpeg-skill"
cp "$ROOT/.claude-plugin/plugin.json" "$TREE/.claude-plugin/plugin.json"
cp "$ROOT/skills/ffmpeg-skill/SKILL.md" "$TREE/skills/ffmpeg-skill/SKILL.md"
# A local checkout that has run the tools carries bytecode caches into the tarball; a release
# runner's clean checkout does not. Either way they are not part of a plugin.
find "$TREE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# The gate is on the tree that ships, not on the source tree: what a host needs to find the
# skill, and what the skill needs to run.
for needed in .claude-plugin/plugin.json skills/ffmpeg-skill/SKILL.md SKILL.md \
              scripts/_contract.py scripts/probe.py docs/contract.md references/workflow.md LICENSE; do
  [ -s "$TREE/$needed" ] || { echo "plugin tree is missing $needed" >&2; exit 1; }
done
for unwanted in tests evals site brand demos assets .github; do
  [ ! -e "$TREE/$unwanted" ] || { echo "plugin tree carries $unwanted/" >&2; exit 1; }
done
VERSION="$(node -p "require('$TREE/package.json').version")"
PLUGIN_VERSION="$(node -p "require('$TREE/.claude-plugin/plugin.json').version")"
[ "$VERSION" = "$PLUGIN_VERSION" ] || {
  echo "package.json is $VERSION but .claude-plugin/plugin.json is $PLUGIN_VERSION" >&2; exit 1; }

if [ "$MODE" = "tree" ]; then
  echo "plugin tree for $VERSION built in $TREE"
  exit 0
fi

# Build the commit with a private index, so the checkout and its index are never touched.
export GIT_INDEX_FILE="$WORK/index"
git --work-tree="$TREE" add -A -f .
TREE_ID="$(git write-tree)"
unset GIT_INDEX_FILE

# "The branch does not exist yet" and "the remote could not be asked" are different answers: only
# the first may start the branch without a parent. ls-remote --exit-code exits 2 for no such ref;
# anything else (network, auth) stops here, with its own message, before a commit is made.
PARENT=""
REMOTE_STATE=0
git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null || REMOTE_STATE=$?
if [ "$REMOTE_STATE" -ne 0 ] && [ "$REMOTE_STATE" -ne 2 ]; then
  echo "could not ask origin whether $BRANCH exists (git ls-remote exited $REMOTE_STATE)" >&2
  exit 1
fi
if [ "$REMOTE_STATE" -eq 0 ]; then
  git fetch --quiet origin "refs/heads/$BRANCH"
  PARENT="$(git rev-parse FETCH_HEAD)"
  if [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE_ID" ]; then
    echo "origin/$BRANCH already holds this tree ($VERSION); nothing to publish"
    exit 0
  fi
fi

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-github-actions[bot]}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-github-actions[bot]@users.noreply.github.com}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"
MESSAGE="plugin: ffmpeg-skill $VERSION (built from $(git rev-parse --short HEAD))"
if [ -n "$PARENT" ]; then
  COMMIT="$(git commit-tree "$TREE_ID" -p "$PARENT" -m "$MESSAGE")"
else
  COMMIT="$(git commit-tree "$TREE_ID" -m "$MESSAGE")"
fi
echo "plugin commit $COMMIT (tree $TREE_ID) for $VERSION"

if [ "$MODE" = "commit" ]; then
  exit 0
fi
git push origin "$COMMIT:refs/heads/$BRANCH"
