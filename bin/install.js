#!/usr/bin/env node
/**
 * ffmpeg-skill installer.
 *
 * Copies the skill (SKILL.md, scripts/, templates/, mcp/, the shipped references and
 * docs/contract.md, package.json, LICENSE) into the skills directory of one or more
 * coding agents. Default target is Claude Code (~/.claude/skills/ffmpeg-skill).
 *
 *   npx ffmpeg-skill                 # Claude Code
 *   npx ffmpeg-skill --cursor        # Cursor  (~/.cursor/skills/ffmpeg-skill)
 *   npx ffmpeg-skill --codex         # Codex   (~/.agents/skills/ffmpeg-skill)
 *   npx ffmpeg-skill --all           # all of the above
 *   npx ffmpeg-skill --dir ./skills  # custom parent directory
 *   npx ffmpeg-skill --project       # ./.claude/skills/ffmpeg-skill in the current project
 *   npx ffmpeg-skill --uninstall     # remove from the selected targets
 *   npx ffmpeg-skill contract --json # machine-readable execution contract (see docs/contract.md)
 *   npx ffmpeg-skill doctor [--json] # which required ffmpeg capabilities this machine has
 *   npx ffmpeg-skill mcp              # stdio MCP server (python3 mcp/server.py); registry clients pass `mcp`
 *
 * Already installed? re-run `npx ffmpeg-skill` to refresh ~/.claude/skills/ffmpeg-skill
 * Copies are not updated automatically.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const SKILL_NAME = 'ffmpeg-skill';
const ROOT = path.resolve(__dirname, '..');
const PAYLOAD = ['SKILL.md', 'scripts', 'templates', 'references', 'docs', 'mcp', 'package.json', 'LICENSE'];

// What of each PAYLOAD item is copied. package.json's "files" is the allow-list of what ships: it
// names whole directories (scripts/, templates/, mcp/) and, for references/ and docs/, single
// files. In the npm package those two directories hold nothing else, but in a git checkout docs/
// also holds the demo gallery and references/ the maintainer diary (17 MB against 2.5 MB), so a
// directory that "files" lists file by file is copied file by file.
function payloadPaths(root) {
  let files = [];
  try {
    files = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).files || [];
  } catch (_) { /* no readable package.json: copy the items whole, as before */ }
  const out = [];
  for (const item of PAYLOAD) {
    const listed = files.filter((f) => f.startsWith(`${item}/`) && f.length > item.length + 1);
    out.push(...(listed.length ? listed : [item]));
  }
  return out;
}

// The installer's own flags. Anything else is refused before a file is touched: an unknown flag
// used to be ignored, so `--uninstall --cursr` (a typo) or `--uninstall --dir` with no value fell
// through to the default target and removed the Claude Code install with exit 0.
const FLAGS = ['--claude', '--cursor', '--codex', '--all', '--dir', '--project', '--uninstall', '--help', '-h'];

// null when the arguments are ones the installer knows, else the line to print.
function argumentError(argv) {
  const dirAt = argv.indexOf('--dir');
  if (dirAt !== -1 && (!argv[dirAt + 1] || argv[dirAt + 1].startsWith('-'))) {
    return 'error: --dir needs a directory (for one whose name starts with "-", write ./-name)';
  }
  const unknown = argv.filter((a, i) => !FLAGS.includes(a) && !(dirAt !== -1 && i === dirAt + 1));
  if (unknown.length) {
    return `error: unknown argument${unknown.length > 1 ? 's' : ''} ${unknown.join(' ')} (known: ${FLAGS.join(', ')}; or the commands contract, doctor, mcp). Nothing was installed or removed.`;
  }
  return null;
}

const args = process.argv.slice(2);
const has = (flag) => args.includes(flag);
const optValue = (flag) => {
  const i = args.indexOf(flag);
  return i !== -1 && args[i + 1] ? args[i + 1] : null;
};

if (has('--help') || has('-h')) {
  console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^\/\*\*?\s?|^\s\*\s?/gm, ''));
  process.exit(0);
}

// Windows Python installers commonly expose `python`/`py`, not `python3`. The Microsoft Store
// app-execution alias is a real python3.exe that spawns (no ENOENT) and exits non-zero, so a
// missing `error` is not proof an interpreter ran. Probe with a version check, then fall through.
// The probe also prints major.minor. 3.0.0 removed Python 3.9 (deprecated in 2.10.9): an older
// interpreter fails the probe, so it is skipped like a missing one.
const PYTHON_PROBE = ['-c', "import sys; sys.stdout.write('%d.%d' % sys.version_info[:2]); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"];

// 3.0.0 removed FFmpeg 5.x (deprecated in 2.14.0). The same line as scripts/_contract.py's
// FFMPEG_UNSUPPORTED (a test keeps them equal); every tool refuses such a build at run time.
const FFMPEG_UNSUPPORTED = 'error: FFmpeg {v} is not supported since ffmpeg-skill 3.0.0 (5.x was deprecated in 2.14.0): use FFmpeg 6.1+.';

// The line for `ffmpeg -version`'s first line, or null (6.1 or later, or not a release number).
function ffmpegUnsupported(versionLine) {
  const m = /^ffmpeg version n?(\d+)\.(\d+)/.exec(versionLine || '');
  if (!m) return null;
  const major = Number(m[1]), minor = Number(m[2]);
  return major < 6 || (major === 6 && minor < 1) ? FFMPEG_UNSUPPORTED.replace('{v}', `${major}.${minor}`) : null;
}

function pythonCandidates(platform) {
  return platform === 'win32' ? ['python3', 'python', 'py'] : ['python3'];
}

// The first candidate that runs and is 3.10+: { cmd, version } (version "3.12", or null when the
// probe printed nothing), or { missing: true, ... } when none is.
function findPython(platform, spawn) {
  const candidates = pythonCandidates(platform);
  const run = spawn || spawnSync;
  let last = null;
  for (const cmd of candidates) {
    const probe = run(cmd, PYTHON_PROBE, { stdio: ['ignore', 'pipe', 'ignore'], encoding: 'utf8', timeout: 15000 });
    if (probe.error || probe.status !== 0) {
      last = probe;
      continue;
    }
    const out = typeof probe.stdout === 'string' ? probe.stdout.trim() : '';
    return { cmd, version: /^\d+\.\d+$/.test(out) ? out : null };
  }
  return { missing: true, error: last && last.error, status: last && last.status, candidates };
}

function runWithPython(scriptArgs, platform, spawn) {
  const py = findPython(platform, spawn);
  if (py.missing) return py;
  return (spawn || spawnSync)(py.cmd, scriptArgs, { stdio: 'inherit' });
}

// After an install: say so when no Python 3.10+ is on PATH, since every script needs one.
function warnMissingPython(platform, spawn, warn) {
  const py = findPython(platform, spawn);
  if (!py.missing) return null;
  const line = `warning: no Python 3.10+ interpreter was found (tried: ${py.candidates.join(', ')}); the skill's scripts need one (3.0.0 removed Python 3.9).`;
  (warn || console.warn)(`\n  ${line}`);
  return line;
}

function main() {
// `contract` / `doctor` are answered by scripts/_contract.py. `mcp` is the stdio server
// (server.json's packageArguments). Everything else installs.
if (args[0] === 'contract' || args[0] === 'doctor') {
  const py = runWithPython([path.join(ROOT, 'scripts', '_contract.py'), ...args], process.platform, spawnSync);
  if (py.missing) {
    console.error(`error: could not find a Python 3.10+ interpreter (tried: ${py.candidates.join(', ')}). Install Python 3.10+ and ensure it is on PATH.`);
    process.exit(127);
  }
  process.exit(py.error ? 127 : (py.status == null ? 1 : py.status));
}
if (args[0] === 'mcp') {
  const py = runWithPython([path.join(ROOT, 'mcp', 'server.py'), ...args.slice(1)], process.platform, spawnSync);
  if (py.missing) {
    console.error(`error: could not find a Python 3.10+ interpreter (tried: ${py.candidates.join(', ')}). Install Python 3.10+ and ensure it is on PATH.`);
    process.exit(127);
  }
  process.exit(py.error ? 127 : (py.status == null ? 1 : py.status));
}

const badArgs = argumentError(args);
if (badArgs) {
  console.error(badArgs);
  process.exit(2);
}

const home = os.homedir();
const targets = [];
const want = { claude: has('--claude'), cursor: has('--cursor'), codex: has('--codex') };
if (has('--all')) want.claude = want.cursor = want.codex = true;
const customDir = optValue('--dir');
const project = has('--project');

if (!want.claude && !want.cursor && !want.codex && !customDir && !project) want.claude = true;

if (want.claude) targets.push({ label: 'Claude Code', dir: path.join(home, '.claude', 'skills', SKILL_NAME) });
if (want.cursor) targets.push({ label: 'Cursor', dir: path.join(home, '.cursor', 'skills', SKILL_NAME) });
// Codex reads user-level skills from ~/.agents/skills (its docs list $HOME/.agents/skills,
// .agents/skills up the repo tree, and /etc/codex/skills), not ~/.codex/skills -- the
// latter was this installer's original guess and is not a location current Codex scans.
if (want.codex) targets.push({ label: 'Codex', dir: path.join(home, '.agents', 'skills', SKILL_NAME), legacy: path.join(home, '.codex', 'skills', SKILL_NAME) });
if (project) targets.push({ label: 'project (.claude/skills)', dir: path.join(process.cwd(), '.claude', 'skills', SKILL_NAME) });
if (customDir) targets.push({ label: 'custom', dir: path.join(path.resolve(customDir), SKILL_NAME) });

function copyRecursive(src, dst) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      if (entry === '__pycache__') continue;
      copyRecursive(path.join(src, entry), path.join(dst, entry));
    }
  } else {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    if (src.endsWith('.py')) fs.chmodSync(dst, 0o755);
  }
}

function checkFfmpeg() {
  const r = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8' });
  if (r.error || r.status !== 0) {
    console.warn('\n  warning: ffmpeg was not found on PATH. The skill needs FFmpeg to run:');
    console.warn('    macOS:   brew install ffmpeg-full; export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"');
    console.warn('             # keg-only, so installing it does not put it on PATH: keep the export in your shell profile;');
    console.warn('             # the plain ffmpeg formula lacks subtitles/drawtext/zscale');
    console.warn('    Ubuntu:  sudo apt install ffmpeg');
    console.warn('    Windows: winget install Gyan.FFmpeg\n');
    return false;
  }
  const first = r.stdout.split('\n')[0];
  console.log(`  found ${first}`);
  const line = ffmpegUnsupported(first);
  if (line) console.warn(`\n  ${line}`);
  return true;
}

// Scratch directories an install that was killed (or that failed before this was cleaned up in
// the catch below) left next to the target: <name>.tmp-<pid>, each a partial copy with a SKILL.md.
function staleScratchDirs(dir) {
  const parent = path.dirname(dir);
  const prefix = `${path.basename(dir)}.tmp-`;
  let entries = [];
  try { entries = fs.readdirSync(parent); } catch (_) { return []; }
  return entries
    .filter((e) => e.startsWith(prefix) && /^\d+$/.test(e.slice(prefix.length)))
    .filter((e) => !processIsRunning(Number(e.slice(prefix.length))))
    .map((e) => path.join(parent, e));
}

// The number after ".tmp-" is the pid of the install that made the directory. One whose process
// is still running is that install's work in progress, not a leftover: removing it lets the
// install recreate the directory with only the files it had not copied yet and then rename that
// into place as a finished install. Signal 0 asks without signalling: ESRCH is "no such
// process"; EPERM is a live process this user may not signal, so it counts as running.
function processIsRunning(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code !== 'ESRCH'; }
}

let failed = false;
for (const t of targets) {
  let tmpDir = null;
  try {
    if (has('--uninstall')) {
      fs.rmSync(t.dir, { recursive: true, force: true });
      console.log(`removed ${t.label}: ${t.dir}`);
      for (const stale of staleScratchDirs(t.dir)) {
        fs.rmSync(stale, { recursive: true, force: true });
        console.log(`removed ${t.label} (left by an interrupted install): ${stale}`);
      }
      // A copy left by the installer's earlier, wrong guess at this agent's directory (see the
      // Codex target above) would otherwise survive every uninstall from here on.
      if (t.legacy && fs.existsSync(t.legacy)) {
        fs.rmSync(t.legacy, { recursive: true, force: true });
        console.log(`removed ${t.label} (older install location): ${t.legacy}`);
      }
      continue;
    }
    // Copy into a scratch directory next to the real target first, then swap it into place
    // with a single rename -- not delete-then-copy-into-the-gap. A process killed mid-copy
    // (Ctrl-C, disk full, a permission error partway through) used to leave the target either
    // empty or half-populated; now it leaves the previous install untouched (first run: no
    // previous install to preserve, so an interruption here still leaves nothing, same as
    // before -- the guarantee is specifically for an upgrade of an existing install).
    tmpDir = `${t.dir}.tmp-${process.pid}`;
    fs.rmSync(tmpDir, { recursive: true, force: true });
    fs.mkdirSync(tmpDir, { recursive: true });
    for (const item of payloadPaths(ROOT)) {
      const src = path.join(ROOT, item);
      if (!fs.existsSync(src)) { if (item !== 'SKILL.md' && item !== 'scripts') continue; throw new Error(`missing ${item} in package`); }
      copyRecursive(src, path.join(tmpDir, item));
    }
    // Swap: move the old install aside, move the new one in, then drop the old copy. If the
    // second rename fails (a locked file on Windows, a permission error) the old install is put
    // back, so an upgrade can fail but never leaves the target empty.
    const bakDir = `${t.dir}.bak-${process.pid}`;
    fs.rmSync(bakDir, { recursive: true, force: true });
    const hadOld = fs.existsSync(t.dir);
    if (hadOld) fs.renameSync(t.dir, bakDir);
    try {
      fs.renameSync(tmpDir, t.dir);
    } catch (err) {
      if (hadOld) { try { fs.renameSync(bakDir, t.dir); } catch (_) { /* the old copy stays at bakDir */ } }
      throw err;
    }
    if (hadOld) fs.rmSync(bakDir, { recursive: true, force: true });
    console.log(`installed ${t.label}: ${t.dir}`);
  } catch (err) {
    failed = true;
    console.error(`failed for ${t.label} (${t.dir}): ${err.message}`);
    // The partial copy is of no use to anyone and holds a SKILL.md, so an agent scanning the
    // skills folder would find a second, broken skill there. Nothing else ever removed it.
    if (tmpDir) { try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* reported above */ } }
  }
}

if (!has('--uninstall')) {
  checkFfmpeg();
  warnMissingPython(process.platform, spawnSync);
  console.log('\nDone. Ask your agent things like "make this video 60 seconds and add captions".');
}
process.exit(failed ? 1 : 0);
}

if (require.main === module) {
  main();
}

module.exports = { argumentError, payloadPaths, PAYLOAD, FLAGS, pythonCandidates, runWithPython, findPython, warnMissingPython, ffmpegUnsupported, FFMPEG_UNSUPPORTED, PYTHON_PROBE };
