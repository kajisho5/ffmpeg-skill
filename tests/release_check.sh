#!/usr/bin/env bash
# Pre-release smoke test. Run before `npm publish`; exits non-zero on any problem.
#   1. the packed tarball contains SKILL.md, scripts/, references/, mcp/, bin/
#   2. the tarball installs via the real installer into a temp HOME
#   3. every installed script answers --help
#   4. the MCP server lists tools
#   5. (optional, --corpus) tests/corpus.py --expect --quick on downloaded real files
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d -t ffskill-release-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

echo "== 1. pack contents"
npm pack --pack-destination "$TMP" >/dev/null 2>&1
TGZ="$(ls "$TMP"/*.tgz)"
LIST="$(tar -tzf "$TGZ")"
for need in package/SKILL.md package/scripts/_common.py package/scripts/probe.py package/references/scripts.md package/references/devices.md package/mcp/server.py package/bin/install.js; do
  echo "$LIST" | grep -qx "$need" || { echo "FAIL: $need missing from the package"; exit 1; }
done
echo "   ok ($(echo "$LIST" | wc -l | tr -d ' ') files)"

echo "== 2. install from the tarball into a temp HOME"
mkdir -p "$TMP/home" "$TMP/pkg"
tar -xzf "$TGZ" -C "$TMP/pkg"
HOME="$TMP/home" node "$TMP/pkg/package/bin/install.js" >/dev/null
for d in SKILL.md scripts references mcp; do
  [ -e "$TMP/home/.claude/skills/ffmpeg-skill/$d" ] || { echo "FAIL: $d not installed"; exit 1; }
done
echo "   ok"

echo "== 3. every script answers --help"
for f in "$TMP"/home/.claude/skills/ffmpeg-skill/scripts/*.py; do
  case "$(basename "$f")" in _common.py) continue;; esac
  python3 "$f" --help >/dev/null 2>&1 || { echo "FAIL: $(basename "$f") --help"; exit 1; }
done
echo "   ok"

echo "== 4. MCP server lists tools"
n="$(python3 "$TMP/home/.claude/skills/ffmpeg-skill/mcp/server.py" --list | wc -l | tr -d ' ')"
[ "$n" -ge 15 ] || { echo "FAIL: MCP server lists only $n tools"; exit 1; }
echo "   ok ($n tools)"

if [ "${1:-}" = "--corpus" ]; then
  echo "== 5. real-device corpus (quick)"
  python3 tests/corpus.py --expect --verify --quick
fi
echo "release check passed: $(node -p "require('./package.json').version")"
