#!/usr/bin/env node
/**
 * ffmpeg-skill installer.
 *
 * Copies SKILL.md and scripts/ into the skills directory of one or more
 * coding agents. Default target is Claude Code (~/.claude/skills/ffmpeg-skill).
 *
 *   npx ffmpeg-skill                 # Claude Code
 *   npx ffmpeg-skill --cursor        # Cursor  (~/.cursor/skills/ffmpeg-skill)
 *   npx ffmpeg-skill --codex         # Codex   (~/.codex/skills/ffmpeg-skill)
 *   npx ffmpeg-skill --all           # all of the above
 *   npx ffmpeg-skill --dir ./skills  # custom parent directory
 *   npx ffmpeg-skill --project       # ./.claude/skills/ffmpeg-skill in the current project
 *   npx ffmpeg-skill --uninstall     # remove from the selected targets
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const SKILL_NAME = 'ffmpeg-skill';
const ROOT = path.resolve(__dirname, '..');
const PAYLOAD = ['SKILL.md', 'scripts', 'mcp'];

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

const home = os.homedir();
const targets = [];
const want = { claude: has('--claude'), cursor: has('--cursor'), codex: has('--codex') };
if (has('--all')) want.claude = want.cursor = want.codex = true;
const customDir = optValue('--dir');
const project = has('--project');

if (!want.claude && !want.cursor && !want.codex && !customDir && !project) want.claude = true;

if (want.claude) targets.push({ label: 'Claude Code', dir: path.join(home, '.claude', 'skills', SKILL_NAME) });
if (want.cursor) targets.push({ label: 'Cursor', dir: path.join(home, '.cursor', 'skills', SKILL_NAME) });
if (want.codex) targets.push({ label: 'Codex', dir: path.join(home, '.codex', 'skills', SKILL_NAME) });
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
    fs.copyFileSync(src, dst);
    if (src.endsWith('.py')) fs.chmodSync(dst, 0o755);
  }
}

function checkFfmpeg() {
  const r = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8' });
  if (r.error || r.status !== 0) {
    console.warn('\n  warning: ffmpeg was not found on PATH. The skill needs FFmpeg to run:');
    console.warn('    macOS:   brew install ffmpeg');
    console.warn('    Ubuntu:  sudo apt install ffmpeg');
    console.warn('    Windows: winget install Gyan.FFmpeg\n');
    return false;
  }
  console.log(`  found ${r.stdout.split('\n')[0]}`);
  return true;
}

let failed = false;
for (const t of targets) {
  try {
    if (has('--uninstall')) {
      fs.rmSync(t.dir, { recursive: true, force: true });
      console.log(`removed ${t.label}: ${t.dir}`);
      continue;
    }
    fs.rmSync(t.dir, { recursive: true, force: true });
    fs.mkdirSync(t.dir, { recursive: true });
    for (const item of PAYLOAD) copyRecursive(path.join(ROOT, item), path.join(t.dir, item));
    console.log(`installed ${t.label}: ${t.dir}`);
  } catch (err) {
    failed = true;
    console.error(`failed for ${t.label} (${t.dir}): ${err.message}`);
  }
}

if (!has('--uninstall')) {
  checkFfmpeg();
  console.log('\nDone. Ask your agent things like "make this video 60 seconds and add captions".');
}
process.exit(failed ? 1 : 0);
