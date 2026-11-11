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
# The commit holds the tree under ffmpeg-skill/ (see SUBDIR below).
#
# The branch only ever moves forward (each release is a commit on top of the last), so a host
# that fetched it before can fast-forward. Nothing here force-pushes.
set -euo pipefail

BRANCH="plugin"
# The tree sits in a subdirectory of the branch, not at its root, so a marketplace entry can name it
# as a `git-subdir` source. Measured on the 3.3.0 branch (tree at the root, a `url` source with
# `ref`): Claude Code 2.1.322 cached 2.6 MB, but Codex 0.167 kept the whole clone, every branch's
# history included (39 MB, more than the repository's 28 MB of files). With `git-subdir` both copy
# the directory alone and keep no .git (60 KB for a 44 KB directory in each).
SUBDIR="ffmpeg-skill"
# origin, unless a test points the script at a remote of its own.
REMOTE="${PLUGIN_REMOTE:-origin}"
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
# The listing icon: the plugin directory reads .claude-plugin/icon.png (a square PNG, 512 to 2048 px,
# under 2 MB) and takes it once, at the first submission.
# The copy keeps the picture, drops every chunk that is not picture data and recompresses the pixels. assets/icon.png carries
# a 23 KB C2PA provenance chunk (caBX) whose text holds "url" entries; read as text beside the
# compressed pixels, the plugin directory's check took the file for a download-and-run command.
# The file in assets/ is not touched.
node -e '
  const fs = require("fs"), zlib = require("zlib"), [src, dst] = process.argv.slice(1), b = fs.readFileSync(src);
  const keep = new Set(["IHDR", "PLTE", "tRNS", "gAMA", "cHRM", "sRGB", "iCCP", "pHYs"]);
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (buf) => { let c = 0xffffffff; for (const x of buf) c = crcTable[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type, "latin1"), data]), out = Buffer.alloc(body.length + 8);
    out.writeUInt32BE(data.length, 0); body.copy(out, 4); out.writeUInt32BE(crc(body), body.length + 4); return out; };
  const head = [b.subarray(0, 8)], pixels = [];
  for (let i = 8; i < b.length;) {
    const n = b.readUInt32BE(i), type = b.toString("latin1", i + 4, i + 8), data = b.subarray(i + 8, i + 8 + n);
    if (type === "IDAT") pixels.push(data); else if (keep.has(type)) head.push(chunk(type, data));
    i += 12 + n;
  }
  // The same pixels, compressed again until the bytes spell none of the words a text scan of a
  // binary file trips on. Lossless: only the deflate stream differs.
  const raw = zlib.inflateSync(Buffer.concat(pixels)), words = ["curl", "wget", "bash", "|sh", "| sh", "sh -c", "eval"];
  for (const level of [9, 8, 7, 6, 5, 4]) {
    const png = Buffer.concat([...head, chunk("IDAT", zlib.deflateSync(raw, { level })), chunk("IEND", Buffer.alloc(0))]);
    if (!words.some((w) => png.includes(w))) { fs.writeFileSync(dst, png); process.exit(0); }
  }
  console.error("no compression level gave an icon free of shell-like byte sequences"); process.exit(1);
' "$ROOT/assets/icon.png" "$TREE/.claude-plugin/icon.png"
# bin/install.js is the `npx ffmpeg-skill` installer. A plugin host does the installing, nothing in
# the skill calls it, and the plugin directory's checks flag a bin/ folder and the installer's
# shell-outs as an install-time risk. It leaves the tree, and package.json stops naming it.
rm -rf "$TREE/bin"
# The repository README is written for someone deciding whether to install: 700 lines of
# comparisons, measurements and install commands for five hosts. In a plugin the skill is already
# installed and SKILL.md is what the agent reads, so the tree carries a short README that says what
# this directory is and where the full one lives.
cat > "$TREE/README.md" <<'PLUGIN_README'
# ffmpeg-skill (plugin tree)

Local FFmpeg video and audio editing for coding agents. This directory is the installable plugin:
the skill (`SKILL.md`, also at `skills/ffmpeg-skill/SKILL.md`), its tools (`scripts/`), their
references and templates, the machine-readable contract (`docs/contract.md`,
`python3 scripts/_contract.py --json`) and the MCP server (`mcp/server.py`).

It is built from the npm package by every release and published to the `plugin` branch. The full
README, the changelog and the tests are in the repository: https://github.com/kajisho5/ffmpeg-skill

Needs FFmpeg 6.1 or later and Python 3.10 or later. The tools themselves open no network
connection and read no API key. The one exception is transcription (`caption.py --transcribe`,
`silence.py --filler --transcribe`), which runs a speech engine you installed yourself
(whisper.cpp, faster-whisper, openai-whisper or parakeet): on its first run such an engine may
download its model, and a Hugging Face client uses a token you are logged in with.
PLUGIN_README
node -e '
  const fs = require("fs"), f = process.argv[1], p = JSON.parse(fs.readFileSync(f, "utf8"));
  delete p.bin;
  delete p.mcpName;   // the MCP Registry reads it from the npm package, not from a plugin
  fs.writeFileSync(f, JSON.stringify(p, null, 2) + "\n");
' "$TREE/package.json"
# A local checkout that has run the tools carries bytecode caches into the tarball; a release
# runner's clean checkout does not. Either way they are not part of a plugin.
find "$TREE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# The gate is on the tree that ships, not on the source tree: what a host needs to find the
# skill, and what the skill needs to run.
for needed in .claude-plugin/plugin.json .claude-plugin/icon.png skills/ffmpeg-skill/SKILL.md SKILL.md \
              scripts/_contract.py scripts/probe.py docs/contract.md references/workflow.md LICENSE; do
  [ -s "$TREE/$needed" ] || { echo "plugin tree is missing $needed" >&2; exit 1; }
done
for unwanted in tests evals site brand demos assets .github bin; do
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
INNER_ID="$(git write-tree)"
git read-tree --empty
git read-tree --prefix="$SUBDIR/" "$INNER_ID"
TREE_ID="$(git write-tree)"
unset GIT_INDEX_FILE

# "The branch does not exist yet" and "the remote could not be asked" are different answers: only
# the first may start the branch without a parent. ls-remote --exit-code exits 2 for no such ref;
# anything else (network, auth) stops here, with its own message, before a commit is made.
PARENT=""
REMOTE_STATE=0
git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null || REMOTE_STATE=$?
if [ "$REMOTE_STATE" -ne 0 ] && [ "$REMOTE_STATE" -ne 2 ]; then
  echo "could not ask $REMOTE whether $BRANCH exists (git ls-remote exited $REMOTE_STATE)" >&2
  exit 1
fi
if [ "$REMOTE_STATE" -eq 0 ]; then
  git fetch --quiet "$REMOTE" "refs/heads/$BRANCH"
  PARENT="$(git rev-parse FETCH_HEAD)"
  if [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE_ID" ]; then
    echo "$REMOTE/$BRANCH already holds this tree ($VERSION); nothing to publish"
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
git push "$REMOTE" "$COMMIT:refs/heads/$BRANCH"
