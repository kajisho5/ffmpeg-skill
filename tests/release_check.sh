#!/usr/bin/env bash
# Pre-release smoke test. Run before `npm publish`; exits non-zero on any problem.
#   1. the packed tarball contains SKILL.md, scripts/, references/, mcp/, bin/
#   2. the tarball installs via the real installer into a temp HOME
#   3. every installed script answers --help
#   4. the MCP server lists tools
#   5. contract --json from the packed copy and the installed copy; every declared tool exists and answers --help
#   6. MCP tools/list == contract tools; doctor finds every required capability
#   7. test suites (tests/test_all.py, tests/test_contract.py) and the contract evals
#   8. (optional, --corpus) tests/corpus.py --expect --quick on downloaded real files
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d -t ffskill-release-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

echo "== 1. pack contents"
npm pack --pack-destination "$TMP" >/dev/null 2>&1
TGZ="$(ls "$TMP"/*.tgz)"
LIST="$(tar -tzf "$TGZ")"
for need in package/SKILL.md package/scripts/_common.py package/scripts/_contract.py package/scripts/probe.py package/references/scripts.md package/references/devices.md package/mcp/server.py package/bin/install.js; do
  echo "$LIST" | grep -qx "$need" || { echo "FAIL: $need missing from the package"; exit 1; }
done
echo "   ok ($(echo "$LIST" | wc -l | tr -d ' ') files)"

echo "== 2. install from the tarball into a temp HOME"
mkdir -p "$TMP/home" "$TMP/pkg"
tar -xzf "$TGZ" -C "$TMP/pkg"
HOME="$TMP/home" node "$TMP/pkg/package/bin/install.js" >/dev/null
for d in SKILL.md scripts references mcp package.json; do
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

INST="$TMP/home/.claude/skills/ffmpeg-skill"
echo "== 5. contract from the packed and the installed copy"
node "$TMP/pkg/package/bin/install.js" contract --json --static > "$TMP/contract_pkg.json" || { echo "FAIL: contract --json (packed)"; exit 1; }
python3 "$INST/scripts/_contract.py" --json --static > "$TMP/contract_inst.json" || { echo "FAIL: contract --json (installed)"; exit 1; }
python3 - "$TMP/contract_pkg.json" "$TMP/contract_inst.json" "$INST" "$ROOT" <<'PY'
import json, subprocess, sys
pkg, inst, skill, root = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
assert pkg["tools"] == inst["tools"], "packed and installed contracts differ"
assert pkg["skill"]["version"] == json.load(open(root + "/package.json"))["version"], "installed contract has the wrong version"
assert "contract_version" in pkg and pkg["contract_version"] != pkg["skill"]["version"]
for t in pkg["tools"]:
    path = skill + "/" + t["executable"]
    subprocess.run([sys.executable, path, "--help"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(f"   ok ({len(pkg['tools'])} tools, contract {pkg['contract_version']}, skill {pkg['skill']['version']})")
PY

echo "== 6. MCP tools == contract tools; doctor"
python3 - "$TMP/contract_inst.json" "$INST" <<'PY'
import json, subprocess, sys
doc = json.load(open(sys.argv[1]))
listed = subprocess.run([sys.executable, sys.argv[2] + "/mcp/server.py", "--list"], stdout=subprocess.PIPE, text=True, check=True).stdout
names = {l.split()[0] for l in listed.splitlines() if l.strip()}
want = {t["name"] for t in doc["tools"]}
assert names == want, f"MCP {sorted(names ^ want)} differs from contract"
print(f"   ok ({len(names)} tools)")
PY
python3 "$INST/scripts/_contract.py" doctor >/dev/null || { echo "FAIL: doctor reports missing required capabilities"; python3 "$INST/scripts/_contract.py" doctor; exit 1; }
echo "   doctor ok"

echo "== 7. tests and contract evals"
python3 tests/test_all.py >"$TMP/test_all.log" 2>&1 || { tail -30 "$TMP/test_all.log"; echo "FAIL: tests/test_all.py"; exit 1; }
python3 tests/test_contract.py >"$TMP/test_contract.log" 2>&1 || { tail -30 "$TMP/test_contract.log"; echo "FAIL: tests/test_contract.py"; exit 1; }
python3 evals/contract/check.py >/dev/null || { echo "FAIL: evals/contract/check.py"; exit 1; }
echo "   ok"

if [ "${1:-}" = "--corpus" ]; then
  echo "== 8. real-device corpus (quick)"
  python3 tests/corpus.py --expect --verify --quick
fi
echo "release check passed: $(node -p "require('./package.json').version")"
