#!/usr/bin/env python3
"""Contract tests: the machine-readable execution contract matches the scripts, the MCP
server and the installer, and every ToolSpec claim (dry-run, JSON shape, input preservation,
verification policy) holds when the tool actually runs.

    python3 tests/test_contract.py
"""
import contextlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import types
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out"))
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "mcp"))
import _contract  # noqa: E402
from _common.runner import HW_ENV, HW_FORCED_ENV  # noqa: E402

# The host's own GPU default must not reach the suite (every tool subprocess inherits os.environ):
# a machine with FFMPEG_SKILL_HW=1 would put every encode on VideoToolbox. Tests that exercise it
# opt in with an explicit env. The names come from the runner, so this scrub and the one in
# tests/_fixtures.py cannot drift from what the tools read.
for _k in (HW_ENV, HW_FORCED_ENV):
    os.environ.pop(_k, None)

# The host's own speech defaults must not reach the suite either: FFMPEG_SKILL_ASR_ENGINE,
# FFMPEG_SKILL_ASR_MODEL or a PARAKEET_* setting would change which speech engine or model a
# --transcribe test drives, or where parakeet-mlx writes. Tests that exercise those opt in with an
# explicit env.
for _k in ("FFMPEG_SKILL_ASR_ENGINE", "FFMPEG_SKILL_ASR_MODEL", "PARAKEET_MODEL", "PARAKEET_CPP_MODEL", "PARAKEET_OUTPUT_TEMPLATE"):
    os.environ.pop(_k, None)
import _common  # noqa: E402
import server as mcp_server  # noqa: E402


def script_sources():
    """Every Python file under scripts/, the _common package included.

    _common is a directory since the refactor after 1.15.0, so a plain `scripts/*.py` glob no
    longer reaches the helpers -- which is exactly the source a scan like "no shell=True
    anywhere" must not stop covering. Tool *enumeration* still uses the bare glob on purpose:
    a package directory is not a tool."""
    return sorted(SCRIPTS.glob("*.py")) + sorted(SCRIPTS.glob("*/*.py"))


def sh(*cmd, check=True, env=None, cwd=None):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd)
    if check and proc.returncode != 0:
        raise AssertionError(f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def ffmpeg(*args):
    return sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args)


def has_step(steps, want):
    """A verification step carrying every key of `want` (2.18 steps carry more keys than older
    assertions name: property, tolerance, provenance, attribution)."""
    return any(all(s.get(k) == v for k, v in want.items()) for s in steps)


def probe_streams(path):
    """{codec_type: stream duration in seconds} straight from ffprobe, not through the skill."""
    out = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration,start_time", "-of", "json", path).stdout
    return {st["codec_type"]: st.get("duration") for st in json.loads(out)["streams"]}


def probe_starts(path):
    """{codec_type: stream start_time in seconds} straight from ffprobe."""
    out = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json", path).stdout
    return {st["codec_type"]: float(st.get("start_time") or 0) for st in json.loads(out)["streams"]}


def tool(name, *args, **kw):
    return sh(sys.executable, SCRIPTS / f"{name}.py", *args, **kw)


TONE = "0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.2)+0.3*sin(2*PI*660*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"


def require_ffmpeg_or_skip(*binaries):
    """Locally, a machine without ffmpeg just skips these suites. In CI that same skip would
    make a job whose ffmpeg install silently failed report green with zero tests run (seen for
    real: a Chocolatey install that returned 0 in 6 s and left nothing on PATH -- 14 tests
    ran, 15 skipped, job "OK"). GitHub sets CI=true on every runner, so there it's a failure."""
    missing = [b for b in binaries if not shutil.which(b)]
    if not missing:
        return
    msg = f"{'/'.join(missing)} not on PATH"
    if os.environ.get("CI"):
        raise AssertionError(f"{msg} -- in CI this is a broken install step, not a reason to skip")
    raise unittest.SkipTest(msg)


class ProbeInputPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_ffmpeg_or_skip("ffprobe")

    def test_failed_probe_preserves_input(self):
        # Use real ffprobe and independent fixtures: every failure mode must leave
        # even an unreadable original byte-for-byte intact.
        for flags in ([], ["--dry-run"], ["--progress"], ["--dry-run", "--progress"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "corrupt.mp4"
                original = b"not a valid MP4; preserve this original\n"
                source.write_bytes(original)
                proc = tool("probe", source, "--json", *flags, check=False)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("ffprobe failed", proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["status"], "failed")
                self.assertTrue(source.exists(), "failed inspection deleted the input")
                self.assertEqual(source.read_bytes(), original)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.contract = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "--json").stdout)
        cls.static = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "--json", "--static").stdout)
        cls.tools = {t["name"]: t for t in cls.contract["tools"]}
        # fixtures: normal MP4, VFR, HDR10, audio-only, 5.1, external audio, second camera
        cls.src = OUT / "c_source.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONE}':s=48000",
               "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.src)
        cls.wav = OUT / "c_tone.wav"
        ffmpeg("-i", cls.src, "-vn", "-c:a", "pcm_s16le", cls.wav)
        cls.mic = OUT / "c_mic.wav"
        ffmpeg("-ss", "1.5", "-i", cls.src, "-vn", "-c:a", "pcm_s16le", cls.mic)
        cls.camb = OUT / "c_camB.mp4"
        ffmpeg("-ss", "0.7", "-i", cls.src, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", cls.camb)
        cls.vfr = OUT / "c_vfr.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "4", "-vf", "select='not(mod(n\\,3))',setpts=N/20/TB",
               "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", cls.vfr)
        cls.hdr = OUT / "c_hdr10.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "2", "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
               "-x265-params", "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc", "-tag:v", "hvc1", cls.hdr)
        cls.surround = OUT / "c_surround.mov"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*300*t)|0.4*sin(2*PI*400*t)|0.4*sin(2*PI*500*t)|0.1*sin(2*PI*60*t)|0.2*sin(2*PI*700*t)|0.2*sin(2*PI*800*t)':c=5.1:s=48000",
               "-t", "3", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", cls.surround)
        cls.logo = OUT / "c_logo.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=red@0.8:s=120x40,format=rgba", "-frames:v", "1", cls.logo)
        cls.cues = OUT / "c_cues.txt"
        cls.cues.write_text("0:00-0:02 Hello\n0:02-0:04 World\n", encoding="utf-8")
        cls.srt_en = OUT / "c_en.srt"
        cls.srt_en.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        cls.srt_ja = OUT / "c_ja.srt"
        cls.srt_ja.write_text("1\n00:00:00,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
        cls.subbed = OUT / "c_subbed.mkv"
        ffmpeg("-i", cls.src, "-i", cls.srt_en, "-i", cls.srt_ja, "-map", "0", "-map", "1", "-map", "2",
               "-c:v", "copy", "-c:a", "copy", "-c:s", "srt",
               "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English",
               "-metadata:s:s:1", "language=jpn", "-metadata:s:s:1", "title=Japanese", cls.subbed)
        cls.data_stream = OUT / "c_data_stream.mov"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONE}':s=48000",
               "-t", "3", "-timecode", "00:00:00:00", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", cls.data_stream)
        cls.garbage = OUT / "c_garbage.mp4"
        cls.garbage.write_bytes(bytes((i * 7919) % 256 for i in range(200_000)))
        cls.empty = OUT / "c_empty.mp4"
        cls.empty.write_bytes(b"")
        cls.badlut = OUT / "c_bad.cube"
        cls.badlut.write_text("this is not a LUT\n", encoding="utf-8")
        cls.work = Path(tempfile.mkdtemp(prefix="ffskill_contract_"))
        cls.input_hashes = {p: cls._sha(p) for p in (cls.src, cls.wav, cls.mic, cls.camb, cls.vfr, cls.hdr, cls.surround)}

    @staticmethod
    def _sha(path):
        import hashlib
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def out(self, name):
        return self.work / name

    # ------------------------------------------------------------------ unit: schema and metadata
    def test_contract_schema(self):
        c = self.contract
        for key in ("contract_version", "skill", "requirements", "execution", "invocation", "roles", "capabilities", "tools", "verification_policy", "json_output"):
            self.assertIn(key, c)
        self.assertEqual(c["skill"]["id"], "ffmpeg-skill")
        self.assertEqual(c["skill"]["execution_mode"], "local")
        self.assertFalse(c["execution"]["shell"])
        self.assertFalse(c["execution"]["arbitrary_executables"])
        self.assertTrue(c["invocation"]["structured"]["canonical"])
        self.assertFalse(c["invocation"]["raw_argv"]["canonical"])

    def test_docs_tool_count_matches_the_real_tool_list(self):
        """README/SKILL.md/docs/contract.md each state the tool count in prose (not generated,
        since it reads naturally in a sentence); this pins every stated count against the real
        one so a new/removed tool that forgets to update one of them fails CI instead of
        drifting silently -- see #50, filed after README said 28 twice, 22 once (stale), and
        package.json's description said 21, all at the same time."""
        real_count = len(self.contract["tools"])
        checks = [
            (ROOT / "README.md", re.compile(r"\b(\d+)\s+(?:public )?(?:tools|names)\b|\ball (?P<n>\d+) by\b")),
            (ROOT / "docs" / "contract.md", re.compile(r"\b(\d+)\s+tools\b")),
            (ROOT / "package.json", re.compile(r"(\d+)\s+FFmpeg tools\b")),
            # SKILL.md is the one file the agent actually reads, and it phrases the count as
            # "the N scripts" -- it sat at a stale 28 for weeks while the three above were
            # correct, precisely because this check didn't look at it or at that wording.
            (ROOT / "SKILL.md", re.compile(r"\b(\d+)\s+(?:public )?(?:tools|scripts)\b")),
            (ROOT / ".claude-plugin" / "plugin.json", re.compile(r"\b(\d+)\s+tools\b")),
        ]
        for path, pattern in checks:
            text = path.read_text(encoding="utf-8")
            counts = {int(m.group(1) or m.group("n")) for m in pattern.finditer(text)}
            self.assertTrue(counts, f"{path.relative_to(ROOT)}: no '<N> tools' wording found to check")
            self.assertEqual(counts, {real_count},
                              f"{path.relative_to(ROOT)}: states tool count(s) {sorted(counts)}, "
                              f"but scripts/ actually has {real_count} public tools -- update the stale wording")

    def test_the_why_42_faq_table_matches_the_tools_section_and_the_mcp_core(self):
        """README's "Why 42 tools?" answer restates two facts held elsewhere: which group each
        tool sits in (the Tools section) and which 12 tools/list shows by default
        (_contract.MCP_CORE_TOOLS). Both are pinned here, row by row, with the counts."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tools_md = readme.split("\n## Tools\n", 1)[1].split("\n## ", 1)[0]
        groups, current = {}, None
        for line in tools_md.splitlines():
            head = re.fullmatch(r"\*\*(.+)\*\*", line.strip())
            if head:
                current = head.group(1)
                groups[current] = []
            row = re.match(r"\| `(\w+)\.py` \|", line)
            if row and current:
                groups[current].append(row.group(1))
        m = re.search(r"<!-- why42:start -->\n(.*?)<!-- why42:end -->", readme, re.S)
        self.assertTrue(m, "README.md: the why42 table markers are missing")
        rows = [r for r in m.group(1).splitlines() if r.startswith("| ") and not r.startswith("| Group")]
        seen_core, seen_all = set(), []
        for r in rows[:-1]:
            name, counts, cells = [c.strip() for c in r.strip("|").split("|")]
            listed = [c.strip() for c in cells.split(",")]
            for c in listed:
                self.assertRegex(c, r"^(\*\*\w+\*\*|\w+)$", f"why42 row {name!r}: cell {c!r} is not a name or **name**")
            core = {c.strip("*") for c in listed if c.startswith("**")}
            names = [c.strip("*") for c in listed]
            self.assertIn(name, groups, f"why42 row {name!r} is not a group in README's Tools section")
            self.assertEqual(sorted(names), sorted(groups[name]), f"why42 row {name!r}")
            self.assertEqual(counts, f"{len(core)} / {len(names)}", f"why42 row {name!r} counts")
            seen_core |= core
            seen_all += names
        self.assertEqual(seen_core, set(_contract.MCP_CORE_TOOLS))
        self.assertEqual(sorted(seen_all), sorted(t["name"] for t in self.contract["tools"]))
        self.assertEqual(set(groups), {r.strip("|").split("|")[0].strip() for r in rows[:-1]})
        total_name, total_counts, _ = [c.strip() for c in rows[-1].strip("|").split("|")]
        self.assertEqual(total_name, "**Total**")
        self.assertEqual(total_counts, f"**{len(seen_core)} / {len(seen_all)}**")

    def test_skill_metadata_and_version_separation(self):
        pkg = json.loads((ROOT / "package.json").read_text())
        self.assertEqual(self.contract["skill"]["version"], pkg["version"])
        self.assertEqual(self.contract["contract_version"], _contract.CONTRACT_VERSION)
        self.assertNotEqual(self.contract["contract_version"], self.contract["skill"]["version"])
        self.assertTrue(re.fullmatch(r"\d+\.\d+", self.contract["contract_version"]))
        self.assertIn("Edit video and audio", self.contract["skill"]["description"])
        for t in self.contract["tools"]:
            self.assertEqual(t["version"], pkg["version"])

    def test_claude_plugin_manifest_matches_package_and_skill(self):
        """.claude-plugin/plugin.json makes the repo installable as a Claude Code plugin (#142,
        listed by marketplace.json since 2.17.1); a single-skill plugin may keep SKILL.md at its root. Its
        version must track package.json (release.yml's auto-bump rewrites both), its name must
        equal SKILL.md's frontmatter name (the plugin namespaces the skill as name:name), and it
        must be valid JSON with only the documented top-level fields."""
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], pkg["version"])
        self.assertEqual(manifest["name"], pkg["name"])
        skill_name = re.search(r"(?m)^name:\s*(\S+)", (ROOT / "SKILL.md").read_text(encoding="utf-8")).group(1)
        self.assertEqual(manifest["name"], skill_name)
        self.assertTrue(set(manifest) <= {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}, sorted(manifest))
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", manifest["name"]))

    def test_pages_site_builds_with_no_dead_links(self):
        """The GitHub Pages site (pages.yml) is assembled from the repo's own Markdown by
        .github/scripts/build_pages.py, which refuses a relative link whose target does not
        exist. Running it here means a renamed doc or a moved GIF fails CI instead of
        publishing a dead link, and every image a page points to was copied next to it."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            proc = subprocess.run([sys.executable, str(ROOT / ".github" / "scripts" / "build_pages.py"), str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((out / "index.md").is_file())
            # a titled link is rewritten; a link-shaped inline code span is left as written
            sys.path.insert(0, str(ROOT / ".github" / "scripts"))
            try:
                import build_pages
            finally:
                sys.path.pop(0)
            self.assertEqual(build_pages._rewrite_prose('[c](docs/contract.md "API") `](no.png)`', "README.md", set()),
                             '[c](docs/contract.html "API") `](no.png)`')
            self.assertTrue((out / "_layouts" / "default.html").is_file())
            for page in out.rglob("*.md"):
                text = page.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\nlayout: default\n"), page)
                for src in re.findall(r'(?:src|srcset)="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)\)', text):
                    url = (src[0] or src[1]).split()[0]
                    if not re.match(r"^[a-z]+:", url):
                        self.assertTrue((page.parent / url).is_file(), f"{page.relative_to(out)}: {url}")

    def test_claude_plugin_marketplace_lists_the_plugin_at_the_repo_root(self):
        """Without .claude-plugin/marketplace.json, `claude plugin install` and `claude plugin
        marketplace add kajisho5/ffmpeg-skill` both fail ("not found in any configured
        marketplace" / "Marketplace file not found"), so the README's plugin install line could
        never work. The marketplace lists exactly this plugin, by the manifest's name, from the
        repository root, and the README installs it under that name."""
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", market["name"]))
        self.assertTrue(market["owner"]["name"])
        self.assertEqual([(p["name"], p["source"]) for p in market["plugins"]], [(manifest["name"], "./")])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"/plugin install {manifest['name']} --marketplace kajisho5/ffmpeg-skill", readme)
        self.assertIn(f"claude plugin install {manifest['name']}@{market['name']}", readme)
        self.assertNotIn("claude plugin install kajisho5/ffmpeg-skill\n", readme)

    def test_docs_contract_example_version_matches_package_json(self):
        """docs/contract.md's illustrative JSON example of the Skill object hand-copies a
        skill.version value; it drifted to a stale "0.9.1" while package.json moved on to
        0.11.0 and nothing caught it (test_skill_metadata_and_version_separation only checks
        the live-generated contract, never the hand-written doc example). Parse every fenced
        ```json block in the doc and pin any skill.version found inside it to the real version,
        so this exact class of drift fails CI instead of sitting silently in the docs."""
        pkg = json.loads((ROOT / "package.json").read_text())
        text = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
        self.assertTrue(blocks, "docs/contract.md: no fenced ```json blocks found to check")
        checked = 0
        for block in blocks:
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            version = data.get("skill", {}).get("version") if isinstance(data, dict) else None
            if version is None:
                continue
            checked += 1
            self.assertEqual(version, pkg["version"],
                              f"docs/contract.md: example skill.version is {version!r}, "
                              f"but package.json is {pkg['version']!r} -- update the stale example")
        self.assertGreater(checked, 0, "docs/contract.md: no example block contained skill.version to check")

    def test_roadmap_released_version_matches_package_json(self):
        """docs/roadmap.md's "The released version today is **X**" sentence hand-names a version;
        it drifted to a stale 1.18.3 while package.json moved on to 1.18.4 and nothing caught it
        (found during the 1.18.4 campaign). Pin that sentence's version to package.json so this
        exact class of drift fails CI instead of sitting silently in the roadmap."""
        pkg = json.loads((ROOT / "package.json").read_text())
        text = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
        m = re.search(r"The released version today is \*\*([^*]+)\*\*", text)
        self.assertIsNotNone(m, "docs/roadmap.md: no \"The released version today is **X**\" sentence found")
        self.assertEqual(m.group(1), pkg["version"],
                          f"docs/roadmap.md says the released version is {m.group(1)!r}, "
                          f"but package.json is {pkg['version']!r} -- update the roadmap sentence")

    def test_contract_md_names_only_environment_variables_the_code_reads(self):
        """docs/contract.md is the authority on flags; a review of #305 found its `cache` row naming
        FFMPEG_SKILL_HW, carried over from an unmerged branch, which nothing in this tree read.
        Every FFMPEG_SKILL_* variable it names must be read by a script, the MCP server or the
        installer."""
        text = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        code = "".join(p.read_text(encoding="utf-8", errors="replace")
                       for d in ("scripts", "mcp", "bin") for p in sorted((ROOT / d).rglob("*"))
                       if p.suffix in (".py", ".js") and "__pycache__" not in p.parts)
        named = sorted(set(re.findall(r"\bFFMPEG_SKILL_[A-Z0-9_]*[A-Z0-9]", text)))
        self.assertTrue(named, "docs/contract.md names no FFMPEG_SKILL_* variable at all")
        self.assertEqual([v for v in named if v not in code], [],
                         "docs/contract.md names environment variables nothing in scripts/, mcp/ or bin/ reads")

    def test_docs_failure_json_example_keys_match_the_real_error_shape(self):
        """docs/contract.md's illustrative failure-JSON example listed only kind/message under
        error for years after "code"/"retryable" were added to the real die() output (Hardening
        Phase 2) -- an agent trusting the doc as exhaustive could drop or mishandle fields it
        didn't know existed. Pin the example's error keys to a real die() JSON document's keys so
        this class of drift fails CI instead of sitting silently in the docs, mirroring the
        skill.version check above."""
        text = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
        example = next((json.loads(b) for b in blocks if '"status": "failed"' in b), None)
        self.assertIsNotNone(example, "docs/contract.md: no example failure-JSON block found to check")
        doc = self._fails("probe", self.garbage, kind="input")
        self.assertEqual(set(example["error"].keys()), set(doc["error"].keys()),
                          "docs/contract.md's failure example error keys are out of sync with the real error shape")

    def test_tool_ids_unique_and_canonical(self):
        ids = [t["id"] for t in self.contract["tools"]]
        self.assertEqual(len(ids), len(set(ids)))
        for t in self.contract["tools"]:
            self.assertEqual(t["id"], f"ffmpeg-skill/{t['name']}")
            self.assertTrue(re.fullmatch(r"[a-z]+", t["name"]), t["id"])
        self.assertEqual(ids, sorted(ids), "tools are listed in a stable, sorted order")

    def test_examples_are_parsed_from_skill_md_and_cover_every_tool(self):
        """1.20.0: contract --json's per-tool `examples` field is SKILL.md's own request table
        (the "User says" / "Do" rows), machine-readable -- not a hand-maintained second copy.
        Every one of the 42 tools is named in that table somewhere, so every tool has at least
        one example; a row's markdown backticks are stripped from `command`, and a row with
        several quoted phrasings ("cut from 1:20 to 2:05", "trim the first 10 s") becomes a
        `prompts` list rather than one string."""
        by_name = {t["name"]: t for t in self.contract["tools"]}
        missing = [name for name, t in by_name.items() if not t.get("examples")]
        self.assertEqual(missing, [], "every tool should have at least one SKILL.md example")
        cut = next(e for e in by_name["cut"]["examples"] if "cut from 1:20 to 2:05" in e["prompts"])
        self.assertEqual(cut, {"prompts": ["cut from 1:20 to 2:05", "trim the first 10 s"],
                                "command": "cut.py input.mp4 --start 1:20 --end 2:05"})
        for t in self.contract["tools"]:
            for ex in t["examples"]:
                self.assertEqual(set(ex), {"prompts", "command"})
                self.assertIsInstance(ex["prompts"], list)
                self.assertTrue(ex["prompts"])
                self.assertNotIn("`", ex["command"], "markdown backticks should be stripped")
                self.assertIn(f"{t['name']}.py", ex["command"])
        # a markdown-escaped "\|" inside a cell (broll's --audio b\|mix) is a literal pipe,
        # not a column separator -- confirms the escaping doesn't silently drop the row
        broll = by_name["broll"]["examples"][0]
        self.assertIn("b|mix", broll["command"])
        self.assertIn("B-roll over this bit", broll["prompts"])

    def test_provides_covers_every_tool_with_the_dotted_capability_id(self):
        provides = self.contract["provides"]
        ids = [p["id"] for p in provides]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids), "provides is listed in a stable, sorted order")
        tool_ids = {t["id"] for t in self.contract["tools"]}
        self.assertEqual({p["tool_id"] for p in provides}, tool_ids, "provides covers exactly the tools this build has")
        for p in provides:
            self.assertEqual(p["id"], p["tool_id"].replace("/", ".", 1))
            self.assertEqual(p["lifecycle"], "EXPERIMENTAL")
            self.assertEqual(set(p), {"id", "lifecycle", "tool_id"})

    def test_capability_map_resolves_to_real_tools_and_params(self):
        """capability_map is a hand-authored, descriptive lookup (abstract id -> tool + fixed
        params), not generated like `provides` -- so unlike that test, this doesn't check
        coverage of every tool. It checks the table can't silently drift: every tool_id must
        be a real tool, every fixed param a real input_schema property of that tool, and no
        capability id may collide or duplicate a tool_id 1:1 (this is many:one by design, e.g.
        video.reframe pins fit.py to fit=crop -- it never executes anything itself)."""
        cap_map = self.contract["capability_map"]
        ids = [c["capability"] for c in cap_map]
        self.assertEqual(len(ids), len(set(ids)), "capability ids are unique")
        specs_by_id = {t["id"]: t for t in self.contract["tools"]}
        for entry in cap_map:
            self.assertEqual(set(entry), {"capability", "tool_id", "params"})
            self.assertRegex(entry["capability"], r"^[a-z]+(\.[a-z]+)+$")
            spec = specs_by_id.get(entry["tool_id"])
            self.assertIsNotNone(spec, f"{entry['capability']} maps to unknown tool_id {entry['tool_id']!r}")
            props = spec["input_schema"]["properties"]
            for key, value in entry["params"].items():
                self.assertIn(key, props, f"{entry['capability']}: {key!r} is not a real param of {entry['tool_id']}")
                if "enum" in props[key]:
                    self.assertIn(value, props[key]["enum"])

    def test_docstring_examples_use_flags_that_actually_exist(self):
        """A docstring's own runnable examples are the first thing a reader tries and trusts.
        scenes.py once claimed (in prose, not an example) that highlight ranking used motion --
        it never did. This can't catch a false prose claim, but it does catch the more common
        drift: an Examples: line for script X naming a --flag that X's own parser doesn't have
        (renamed, removed, or typo'd), which is exactly the kind of docs-vs-code gap that let
        that claim go unnoticed for as long as it did."""
        cli_by_tool = {t["name"]: set() for t in self.contract["tools"]}
        for t in self.contract["tools"]:
            for prop in t["input_schema"]["properties"].values():
                cli_by_tool[t["name"]].update(prop.get("cli") or [])
        flag_re = re.compile(r"(--[a-z][a-z0-9-]*)")
        for script in sorted(SCRIPTS.glob("*.py")):
            if script.name.startswith("_"):
                continue
            name = script.stem
            doc = script.read_text(encoding="utf-8").split('"""')[1]
            for line in doc.splitlines():
                line = line.strip()
                if not line.startswith(f"python3 {name}.py"):
                    continue
                code = line.split("#", 1)[0]
                for flag in flag_re.findall(code):
                    self.assertIn(flag, cli_by_tool[name], f"{name}.py's own docstring example uses {flag}, which its parser does not have: {line!r}")

    def test_every_tool_executable_exists_and_internal_scripts_are_hidden(self):
        for t in self.contract["tools"]:
            self.assertTrue((ROOT / t["executable"]).is_file(), t["executable"])
            self.assertEqual(t["executable"], f"scripts/{t['name']}.py")
        names = {t["name"] for t in self.contract["tools"]}
        self.assertNotIn("_common", names)
        self.assertNotIn("_contract", names)
        public = {p.stem for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")}
        self.assertEqual(names, public, "contract tools == public scripts")

    def test_capabilities_declared_only_where_used(self):
        caps = self.contract["capabilities"]
        self.assertIn("ffmpeg", caps["required"])
        self.assertIn("ffprobe", caps["required"])
        for cap in caps["required"] + caps["optional"]:
            self.assertTrue(re.fullmatch(r"ffmpeg|ffprobe|encoder:\w+|filter:\w+|bsf:\w+|external:\w+", cap), cap)
        # every encoder / filter / bsf named in the contract is referenced by some script
        source = "\n".join(p.read_text(encoding="utf-8") for p in script_sources())
        for cap in caps["required"] + caps["optional"]:
            if ":" in cap and not cap.startswith("external:"):
                self.assertIn(cap.split(":", 1)[1], source, f"{cap} declared but no script uses it")
        for t in self.contract["tools"]:
            for cap in t["capabilities"]["required"]:
                self.assertIn(cap, caps["required"])
            for o in t["capabilities"]["optional"]:
                self.assertIn("when", o)
        self.assertNotIn("available", self.static["capabilities"], "--static omits detection")
        self.assertIn("available", caps)
        self.assertEqual(sorted(caps["missing"]), sorted(set(caps["required"]) - set(caps["available"])))

    def test_request_schema_matches_argparse(self):
        for t in self.contract["tools"]:
            schema = t["input_schema"]
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            help_text = tool(t["name"], "--help").stdout
            for dest, prop in schema["properties"].items():
                self.assertIn(prop["type"], ("string", "integer", "number", "boolean", "array"), f"{t['name']}.{dest}")
                if prop["cli"] != "positional":
                    for flag in prop["cli"]:
                        self.assertIn(flag, help_text, f"{t['name']}: {flag} not in --help")
                    longs = [f for f in prop["cli"] if f.startswith("--")]
                    exc = t["mcp"]["argument_exceptions"]
                    if "--" + dest.replace("_", "-") not in longs:
                        self.assertIn(dest, exc, f"{t['name']}: {dest} needs an argument exception")
                        self.assertIn(exc[dest], prop["cli"])
            for pos in schema["positional"]:
                self.assertIn(pos, schema["properties"])
            for req in schema["required"]:
                self.assertIn(req, schema["properties"])
        cut = self.tools["cut"]["input_schema"]["properties"]
        self.assertEqual(cut["input"]["cli"], "positional")
        self.assertEqual(cut["accurate"]["type"], "boolean")
        self.assertEqual(cut["quality"]["type"], "integer")
        self.assertEqual(cut["quality"]["default"], 18)
        self.assertNotIn("crf", cut, "2.0 removed --crf where --quality exists")
        self.assertEqual(self.tools["export"]["input_schema"]["properties"]["crf"]["type"], "integer")
        self.assertEqual(self.tools["export"]["input_schema"]["properties"]["preset"]["enum"], sorted(self.tools["export"]["input_schema"]["properties"]["preset"]["enum"]))

    def test_every_flag_of_every_parser_is_published_once_under_its_own_name(self):
        """Review of #304: --hw (store_true) and --no-hw (store_false) once shared the dest `hw`.
        input_schema keeps one property per dest, so the contract published only --no-hw, typed
        string, under `hw`; mutually_exclusive read [["hw", "hw"]]; and an MCP `hw: true` sent
        --no-hw. Every option string of every parser must sit in exactly one property's cli, and
        the generator refuses a parser whose actions share a dest."""
        import argparse
        for name, spec in self.tools.items():
            with self.subTest(tool=name):
                parser = _contract._capture_parser(SCRIPTS / f"{name}.py")
                published = [f for p in spec["input_schema"]["properties"].values() if p["cli"] != "positional" for f in p["cli"]]
                for action in parser._actions:
                    for flag in action.option_strings:
                        if not isinstance(action, argparse._HelpAction):
                            self.assertEqual(published.count(flag), 1, f"{name}: {flag}")
                for group in spec["input_schema"].get("mutually_exclusive", []):
                    self.assertEqual(len(group), len(set(group)), f"{name}: {group}")
        ap = argparse.ArgumentParser(prog="t")
        ap.add_argument("--x", dest="x", action="store_true")
        ap.add_argument("--no-x", dest="x", action="store_false")
        with self.assertRaisesRegex(RuntimeError, "shares dest 'x'"):
            _contract.input_schema(ap)
        for name in ("fit", "export", "render", "batch"):
            props = self.tools[name]["input_schema"]["properties"]
            self.assertEqual((props["hw"]["type"], props["hw"]["cli"]), ("boolean", ["--hw"]), name)
            self.assertEqual((props["no_hw"]["type"], props["no_hw"]["cli"]), ("boolean", ["--no-hw"]), name)
            self.assertIn(["hw", "no_hw"], self.tools[name]["input_schema"]["mutually_exclusive"])
        on = mcp_server.build_argv("fit", {"input": "a.mp4", "hw": True})
        self.assertIn("--hw", on)
        self.assertNotIn("--no-hw", on)
        self.assertIn("--no-hw", mcp_server.build_argv("fit", {"input": "a.mp4", "no_hw": True}))
        self.assertNotIn("--hw", mcp_server.build_argv("render", {"project": "p.json", "no_hw": True}))
        self.assertIn("--hw", mcp_server.build_argv("render", {"project": "p.json", "hw": True}))

        def required_lists(node):
            if isinstance(node, dict):
                if isinstance(node.get("required"), list):
                    yield node["required"]
                for v in node.values():
                    yield from required_lists(v)
            elif isinstance(node, list):
                for v in node:
                    yield from required_lists(v)
        for t in _contract.mcp_tools():
            for req in required_lists(t["inputSchema"]):
                self.assertEqual(len(req), len(set(req)), f"{t['name']}: JSON Schema `required` items must be unique: {req}")

    def test_a_conditional_notes_description_also_names_the_gpu_line(self):
        """emit() adds the VideoToolbox quality line to `notes` on any tool that takes --hw, so a
        tool whose `notes` description names its own condition (loop: "--boomerang ... the audio
        was dropped") must not read as if that were the only one."""
        for name, spec in self.tools.items():
            if "hw" not in spec["input_schema"]["properties"]:
                continue
            notes = spec["output_schema"]["properties"].get("notes")
            with self.subTest(tool=name):
                self.assertIsNotNone(notes, "a --hw tool publishes notes: emit() adds the GPU line to it")
                self.assertIn("VideoToolbox", notes.get("description", ""))
        self.assertIn("VideoToolbox", self.tools["loop"]["output_schema"]["properties"]["notes"]["description"])
        self.assertIn("VideoToolbox", self.contract["idempotency_hints"]["bit_exact"])

    def test_response_schema(self):
        for t in self.contract["tools"]:
            schema = t["output_schema"]
            self.assertEqual(schema["type"], "object")
            if t["name"] != "probe":
                for key in ("status", "output", "dry_run", "commands"):
                    self.assertIn(key, schema["required"], t["name"])
        self.assertEqual(self.contract["json_output"]["success"]["status"], "completed")
        self.assertEqual(self.contract["json_output"]["failure"]["status"], "failed")

    def test_dry_run_multistage_pipeline_survives_the_probe_stub(self):
        """The dry-run stub probe() returns for a not-yet-written output honestly reports
        width/height/fps as 0/0/0.0 ("not measured", issue #77) instead of the plausible-looking
        1920x1080/30fps placeholder it used to fabricate. render.py/join.py/fit.py chain dry-run
        probes across pipeline stages and used to divide by width/height for aspect-ratio math,
        which is exactly why the first attempt at zeroing this stub was reverted (real
        ZeroDivisionError). Each such call site now treats a zero/unknown source dimension as
        "can't compute a ratio" and falls back sanely instead of dividing by it, so this pins the
        crash-free behavior: a join with only --width set (forcing the height-from-aspect
        division) must not blow up under --dry-run even when its input is itself a dry-run-planned
        clip that was never actually written."""
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "2", "-o", self.out("dr_a.mp4"), "--dry-run", "--json").stdout)
        self.assertTrue(doc["dry_run"])
        proc = tool("join", self.out("dr_a.mp4"), self.out("dr_a.mp4"), "--width", "480",
                     "-o", self.out("dr_joined.mp4"), "--dry-run", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = tool("fit", self.out("dr_a.mp4"), "--width", "480", "--aspect", "9:16",
                     "-o", self.out("dr_fit_w.mp4"), "--dry-run", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = tool("fit", self.out("dr_a.mp4"), "--height", "480", "--aspect", "9:16",
                     "-o", self.out("dr_fit_h.mp4"), "--dry-run", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = tool("fit", self.out("dr_a.mp4"), "--width", "480", "--height", "480",
                     "-o", self.out("dr_fit_wh.mp4"), "--dry-run", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_dry_run_probe_stub_does_not_fabricate_plausible_dimensions(self):
        """Companion to the crash-safety test above: now that every division site that consumes
        the dry-run probe stub's width/height guards against zero, the stub itself can go back to
        reporting the honest "not measured" 0/0/0.0 instead of a fabricated 1920x1080/30fps that
        looked like a real computed preview in a tool's human-readable dry-run summary line."""
        import _common
        _common.STATE.dry_run = True
        try:
            meta = _common.probe(str(self.out("does_not_exist_and_never_will.mp4")))
        finally:
            _common.STATE.dry_run = False
        self.assertEqual(meta["video"]["width"], 0)
        self.assertEqual(meta["video"]["height"], 0)
        self.assertEqual(meta["video"]["fps"], 0.0)

    def test_picture_only_edits_keep_the_sources_subtitle_streams(self):
        """fit.py/color.py/graphics.py/overlay.py used to build an explicit, selective -map
        list naming only video+audio, silently dropping any subtitle track the source had --
        found by an ad hoc audit of all 28 tools for stream preservation (#91), not itself
        checked in. Each now tries run_keeping_subtitles() first (stream-copies subtitle/data
        alongside the re-encoded picture) before falling back to the original video+audio-only
        command. c_subbed.mkv (built in setUpClass) has two real SRT subtitle tracks; every tool
        below must keep BOTH (a partial loss -- e.g. only one surviving -- is still a real
        regression this asserts against), and --json must report dropped_non_av_streams: false
        since nothing here should need the fallback."""
        cases = [
            ("fit", [self.subbed, "--width", "480", "-o", self.out("keepsub_fit.mkv"), "--json"]),
            ("color", [self.subbed, "--correct", "--exposure", "0.3", "-o", self.out("keepsub_color.mkv"), "--json"]),
            ("graphics", [self.subbed, "--template", "lower-third", "--name", "X", "-o", self.out("keepsub_graphics.mkv"), "--json"]),
            ("overlay", [self.subbed, "--text", "hi", "-o", self.out("keepsub_overlay.mkv"), "--json"]),
        ]
        for name, args in cases:
            doc = json.loads(tool(name, *args).stdout)
            self.assertFalse(doc["dropped_non_av_streams"], name)
            kinds = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", doc["output"]).stdout.split()
            self.assertEqual(kinds.count("subtitle"), 2, f"{name}: expected both source subtitle tracks, got {kinds}")

    def test_overlay_image_keeping_a_short_subtitle_does_not_truncate_the_output(self):
        """Real regression caught in review of #91's fix, before it shipped: overlay.py's
        --image branch used -shortest (needed to stop the looped still running forever) alongside
        -t <duration> (an FFmpeg-7+-precision belt-and-suspenders). Once run_keeping_subtitles()
        also mapped the source's subtitle track, -shortest's "-stop at whichever mapped stream
        ends first" semantics meant a subtitle that ends early (c_subbed.mkv's covers only 0-2s
        of its 6s video) silently truncated the WHOLE output to ~2s -- reproduced directly before
        the fix (6s in, ~1s out). Fixed by only falling back to -shortest when no duration is
        known at all; -t alone (exact, bounds only the main input) is used whenever it is."""
        doc = json.loads(tool("overlay", self.subbed, "--image", self.logo, "-o", self.out("keepsub_overlay_img.mkv"), "--json").stdout)
        result = doc["probe"]
        self.assertGreater(result["duration"], 5.0, f"output was truncated to the subtitle's length: {result['duration']}s")

    def test_fit_speed_change_drops_subtitles_instead_of_desyncing_them(self):
        """A stream-copied subtitle keeps the source's original timestamps; --method speed
        retimes video (setpts) and audio (atempo) but has no way to retime a copied subtitle
        track along with them, so keeping it would silently desync captions from the now-faster
        or -slower picture (caught in review of #91's fix, before it shipped). fit.py must not
        call run_keeping_subtitles() when it's changing speed -- dropping the subtitle track is
        the honest outcome, reported via dropped_non_av_streams: true, not a silently-wrong one."""
        doc = json.loads(tool("fit", self.subbed, "--duration", "2", "-o", self.out("speed_fit.mkv"), "--json").stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        kinds = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", doc["output"]).stdout
        self.assertNotIn("subtitle", kinds)

    def test_changelog_mentions_every_closed_issue_since_last_tag(self):
        """A merged fix can land after CHANGELOG.md's current-version section was already
        written (this happened for real: #77's fix, PR #88, merged after the 0.12.0 section was
        drafted and initially missed it -- caught by hand, not by a test, and fixed in a
        follow-up commit). Every "Closes #N." in a commit body since the last release tag should
        show up somewhere in CHANGELOG.md; if it doesn't, either the changelog needs an entry or
        the issue was closed without one on purpose (rare -- e.g. a pure process/doc note) and
        this test's exemption set below should say why. Needs real git history: skips itself on
        a shallow clone (see ci.yml's fetch-depth: 0) where no tag is reachable at all."""
        tags = sh("git", "tag", "--list", "v*", "--sort=-creatordate", cwd=ROOT, check=False).stdout.split()
        if not tags:
            self.skipTest("no reachable release tag (shallow clone?) -- nothing to diff against")
        last_tag = tags[0]
        log = sh("git", "log", f"{last_tag}..HEAD", "--format=%B----COMMIT----", cwd=ROOT, check=False).stdout
        closed = sorted(set(int(n) for n in re.findall(r"(?im)^closes\s+#(\d+)\.?\s*$", log)))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        missing = [n for n in closed if f"#{n}" not in changelog]
        self.assertEqual(missing, [], f"issue(s) closed since {last_tag} but not mentioned in CHANGELOG.md: {missing}")

    def test_dry_run_metadata(self):
        for t in self.contract["tools"]:
            has_flag = "dry_run" in t["input_schema"]["properties"]
            self.assertEqual(t["supports_json"], "json" in t["input_schema"]["properties"])
            if t["name"] == "verify":
                self.assertFalse(t["supports_dry_run"], "verify runs its steps regardless of --dry-run")
            else:
                self.assertEqual(t["supports_dry_run"], has_flag, t["name"])
            self.assertEqual(t["dry_run"]["supported"], t["supports_dry_run"])

    def test_skill_and_scripts_docs_name_the_real_dry_run_exceptions(self):
        """SKILL.md and references/scripts.md used to claim "every script accepts --dry-run
        (runs nothing)" unconditionally, in three places, which was false for sync/multicam/
        scenes/report (they still run ffmpeg/ffprobe to measure/analyze under --dry-run --
        see _contract.py's DRY_RUN_ANALYSIS) and for verify (accepts the flag but ignores it).
        Pin the doc text naming those exact tools against the real exception set so a future
        tool gaining/losing an analysis-only dry-run mode is caught here instead of the docs
        silently drifting out of sync with _contract.py again (issue #82). README's FAQ states
        the same list."""
        analysis_tools = set(_contract.DRY_RUN_ANALYSIS.keys())
        self.assertEqual(analysis_tools, {"sync", "multicam", "scenes", "report", "cropdetect", "silence", "loudness", "check", "stabilize", "overlay"},
                          "the analysis-only dry-run tool set changed -- update SKILL.md/references/scripts.md's exception list to match")
        # "the name appears somewhere in the file" was too weak: every tool name is in SKILL.md's
        # request table anyway, so the list drifted twice (#176 -> #179) with this test green.
        # Pin the sentence that states the exception: the one naming `verify` and `--dry-run`.
        docs = {"SKILL.md": ROOT / "SKILL.md", "references/scripts.md": ROOT / "references" / "scripts.md",
                "docs/contract.md": ROOT / "docs" / "contract.md", "README.md": ROOT / "README.md"}
        for label, path in docs.items():
            text = path.read_text(encoding="utf-8")
            paragraphs = [p for p in text.split("\n\n") if "verify" in p and "dry-run" in p and "multicam" in p]
            self.assertTrue(paragraphs, f"{label}: no paragraph states the dry-run exceptions (names verify, multicam and dry-run)")
            for name in analysis_tools:
                self.assertTrue(any(f"`{name}`" in p for p in paragraphs),
                                f"{label}'s dry-run exception sentence is missing `{name}`")

    def test_skill_workflow_mentions_doctor_and_contract(self):
        """SKILL.md's Workflow section (the first thing an agent reads) used to never mention
        `doctor`/`contract` at all -- an agent on an unfamiliar machine had no documented step to
        check capability before running a tool that depends on an optional filter/encoder,
        discovering it only via a runtime failure (issue #81). Pin their presence in the workflow
        section specifically, not just anywhere in the file."""
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = skill.split("## Workflow", 1)[1].split("\n## ", 1)[0]
        self.assertIn("doctor", workflow)
        self.assertIn("contract", workflow)

    def test_supports_json_brief_mirrors_the_real_flag(self):
        """1.11.0: `--json-brief` is declared the same way `supports_json` is -- measured from the
        parser, never hand-written -- so a tool that somehow lost the shared flag shows up here."""
        for t in self.contract["tools"]:
            with self.subTest(tool=t["name"]):
                self.assertEqual(t["supports_json_brief"], "json_brief" in t["input_schema"]["properties"])
                self.assertTrue(t["supports_json_brief"], "every tool takes --json-brief")
                self.assertEqual(t["supports_json"], t["supports_json_brief"])

    def test_verification_metadata_matches_skill_workflow(self):
        for t in self.contract["tools"]:
            v = t["verification"]
            self.assertEqual(v["required"], bool(v["tools"]))
            for ref in v["tools"]:
                self.assertIn(ref.split("/")[1], self.tools, ref)
                self.assertIn(self.tools[ref.split("/")[1]]["role"], ("analysis", "verification"))
            if t["role"] in ("analysis", "verification"):
                self.assertFalse(v["required"], f"{t['name']} does not need post-verification")
            if t["produces_artifact"] and t["role"] == "execution":
                self.assertIn("ffmpeg-skill/probe", v["tools"], f"{t['name']}: probe first, verify last")
        self.assertEqual(self.tools["export"]["verification"]["tools"], ["ffmpeg-skill/probe", "ffmpeg-skill/check"])
        self.assertEqual(self.tools["cut"]["verification"]["tools"], ["ffmpeg-skill/probe"])

    def test_visual_verification_metadata(self):
        picture = {"fit", "crop", "sphere", "insert", "background", "reverse", "stabilize", "sequence", "caption", "overlay", "graphics", "color", "join", "multicam", "render", "proxy",
                   "deinterlace", "denoise", "redact", "waveform", "straighten", "freeze", "pad", "speedramp", "loop", "grid", "broll"}
        # join, waveform and render are the picture tools that also accept audio-only inputs (audio
        # concat; audio-track visualization; render --template podcast/audiogram); look applies to
        # their video output only, which SKILL.md states next to "Look: not needed"
        both = {"join", "waveform", "render"}
        for t in self.contract["tools"]:
            self.assertEqual(t["requires_visual_verification"], t["name"] in picture, t["name"])
            if t["requires_visual_verification"]:
                self.assertIn("ffmpeg-skill/look", t["verification"]["tools"])
                self.assertEqual(t["video_required"], t["name"] not in both, t["name"])
                self.assertEqual(t["audio_only"], t["name"] in both, t["name"])
            if t["audio_only"] and t["name"] not in both:
                self.assertFalse(t["requires_visual_verification"], f"{t['name']}: audio-only tools never need look.py")
        for name in ("loudness", "silence", "audio", "cut", "sync", "probe", "check", "join"):
            self.assertTrue(self.tools[name]["audio_only"], name)
        # SKILL.md says the same thing
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Look: not needed", skill)

    def test_reencodes_video_and_audio_declared_for_every_tool(self):
        for t in self.contract["tools"]:
            self.assertIn(t["reencodes_video"], ("always", "never", "conditional"), t["name"])
            self.assertIn(t["reencodes_audio"], ("always", "never", "conditional"), t["name"])
        # a handful of the least intuitive ones, checked against what the scripts actually do
        self.assertEqual((self.tools["cut"]["reencodes_video"], self.tools["cut"]["reencodes_audio"]), ("conditional", "conditional"))
        self.assertEqual((self.tools["export"]["reencodes_video"], self.tools["export"]["reencodes_audio"]), ("conditional", "conditional"))
        self.assertEqual((self.tools["caption"]["reencodes_video"], self.tools["caption"]["reencodes_audio"]), ("conditional", "conditional"))
        self.assertEqual((self.tools["loudness"]["reencodes_video"], self.tools["loudness"]["reencodes_audio"]), ("never", "always"))
        self.assertEqual((self.tools["probe"]["reencodes_video"], self.tools["probe"]["reencodes_audio"]), ("never", "never"))
        # sync was declared video="never" but --trim-second re-encodes video whenever the second
        # file starts later (offset >= 0, the common case) or --fix-drift is used -- only the
        # offset<0 stream-copy path leaves video untouched (Hardening Phase 2 P0).
        self.assertEqual((self.tools["sync"]["reencodes_video"], self.tools["sync"]["reencodes_audio"]), ("conditional", "conditional"))
        # color is conditional, not "always": --strip-dovi and --retag are a stream copy of both
        # streams (see test_color_strip_dovi_and_retag_are_stream_copies below), only --to-sdr /
        # --lut / --correct re-encode.
        self.assertEqual((self.tools["color"]["reencodes_video"], self.tools["color"]["reencodes_audio"]), ("conditional", "conditional"))

    def test_color_strip_dovi_and_retag_are_stream_copies(self):
        """color's REENCODE_META claimed "always" re-encodes both streams for years, but
        --strip-dovi and --retag actually run "-c copy" of both streams (SKILL.md always
        documented --retag as "no re-encode") -- pin the real ffmpeg invocation so this class
        of contract-vs-implementation drift fails CI instead of only being caught by reading
        the script by hand."""
        doc = tool("color", self.hdr, "--retag", "bt709", "-o", self.out("v_retag.mp4"), "--json").stdout
        data = json.loads(doc)
        self.assertIn("-c copy", data["commands"][0])
        self.assertNotIn("-c:v", data["commands"][0])

    def test_color_retag_fallback_keeps_extra_audio_and_subtitles_when_it_can(self):
        """--retag's "no re-encode" claim only holds for the stream-copy path; when that copy
        fails (some codec/tag combos can't carry rewritten colour info via -c copy) it used to
        silently fall back to -map 0:v:0 -map 0:a:0 only, dropping every other audio track,
        subtitles, chapters and attached pictures with no signal in --json that this happened.
        Force that fallback (mov_text subtitles copied into MKV, which -c copy can't carry) and
        confirm the fallback now tries to keep the extra audio track + subtitle stream too, and
        that --json honestly reports whether a re-encode/drop occurred instead of a bare
        "completed" that looks identical to the lossless path."""
        multi = self.work / "retag_multitrack.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10", "-f", "lavfi", "-i", f"aevalsrc='{TONE}':s=48000",
               "-f", "lavfi", "-i", "aevalsrc=0.4*sin(2*PI*220*t):s=48000", "-t", "1.5",
               "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", multi)
        subbed = self.work / "retag_multitrack_sub.mp4"
        ffmpeg("-i", multi, "-i", self.srt_en, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text", subbed)
        out = self.out("retag_fallback.mkv")  # MKV can't carry mov_text via copy -- forces the fallback
        doc = json.loads(tool("color", subbed, "--retag", "bt709", "-o", out, "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertTrue(doc["reencoded"], "the copy attempt should have failed and triggered a re-encode")
        import _common
        r = _common.probe(str(out), role="output")
        # whichever fallback tier actually succeeded, the JSON must say plainly whether streams
        # beyond video+selected-audio were dropped -- never silently
        self.assertIn("dropped_non_av_streams", doc)
        self.assertEqual(len(r["audio_streams"]) < 2 or r["subtitle_streams"] == 0, doc["dropped_non_av_streams"],
                          "dropped_non_av_streams must accurately reflect what actually made it into the output")
        # and the re-encode carries the tags it was asked for (setparams on the frames: 7.1+'s
        # negotiation ignored the old output options), checked by the tool itself
        v = r["video"]
        self.assertEqual((v["color_space"], v["color_primaries"], v["color_transfer"]), ("bt709", "bt709", "bt709"))
        self.assertIn({"step": "color_tags", "ok": True, "color_space": "bt709", "color_primaries": "bt709",
                       "color_transfer": "bt709"}, doc["verification"])

    def test_doctor_reports_this_installed_copys_own_version(self):
        """`doctor`'s `version` is this installed copy's own version (never fetched from the
        network or compared against the latest published release) -- so a stale copy that was
        never updated is visible locally, matching `contract --json`'s `skill.version`."""
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json").stdout)
        pkg = json.loads((ROOT / "package.json").read_text())
        self.assertEqual(d["version"], pkg["version"])
        self.assertEqual(d["version"], self.contract["skill"]["version"])
        human = sh(sys.executable, SCRIPTS / "_contract.py", "doctor").stdout
        self.assertIn(d["version"], human)
        self.assertIn("re-run", human, "the human-readable doctor output must say how to refresh a stale install")

    def test_windows_fix_hint_matches_readme_install_guidance(self):
        """A missing subtitles/drawtext/zscale filter on Windows should point to the same fix
        README documents for that platform (the gyan.dev full build), not a generic message --
        mirrors the equivalent macOS `brew install ffmpeg-full` hint."""
        from unittest import mock
        with mock.patch("platform.system", return_value="Windows"):
            hint = _contract._capability_fix_hint("filter:subtitles")
        self.assertIn("Gyan.FFmpeg", hint)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Gyan.FFmpeg", readme)

    def _brew_tree(self, formula="ffmpeg", full=True, other_prefix_full=False):
        """A fake Homebrew prefix: PATH's bin/ffmpeg(+ffprobe) symlink into Cellar/<formula>, and
        opt/ffmpeg-full/bin/* when `full`. Returns (prefix, bin_dir)."""
        td = Path(tempfile.mkdtemp(prefix="brew-", dir=OUT))
        self.addCleanup(shutil.rmtree, td, True)
        prefix = td / "prefix"
        for name in ("ffmpeg", "ffprobe"):
            real = prefix / "Cellar" / formula / "7.1" / "bin" / name
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_text("#!/bin/sh\n")
            real.chmod(0o755)
            (prefix / "bin").mkdir(exist_ok=True)
            (prefix / "bin" / name).symlink_to(real)
            if full:
                f = prefix / "opt" / "ffmpeg-full" / "bin" / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("#!/bin/sh\n")
                f.chmod(0o755)
        if other_prefix_full:
            f = td / "other" / "opt" / "ffmpeg-full" / "bin" / "ffmpeg"
            f.parent.mkdir(parents=True)
            f.write_text("#!/bin/sh\n")
            f.chmod(0o755)
        return prefix, prefix / "bin"

    def _exe(self, name, bindir, system="Darwin"):
        from unittest import mock
        from _common.runner import ffmpeg_exe
        with mock.patch("platform.system", return_value=system), mock.patch.dict(os.environ, {"PATH": str(bindir)}):
            return ffmpeg_exe(name)

    @unittest.skipIf(os.name == "nt", "symlinked fake Homebrew prefix")
    def test_lean_homebrew_ffmpeg_is_replaced_by_ffmpeg_full_of_the_same_prefix(self):
        """#317: brew install ffmpeg-full is keg-only, so PATH keeps the lean formula; both
        binaries come from opt/ffmpeg-full, and the result says why."""
        prefix, bindir = self._brew_tree()
        for name in ("ffmpeg", "ffprobe"):
            path, source = self._exe(name, bindir)
            self.assertEqual((path, source), (str(prefix / "opt" / "ffmpeg-full" / "bin" / name), "homebrew-ffmpeg-full"))
        _, bindir = self._brew_tree(formula="ffmpeg@7")
        self.assertEqual(self._exe("ffmpeg", bindir)[1], "homebrew-ffmpeg-full")

    @unittest.skipIf(os.name == "nt", "symlinked fake Homebrew prefix")
    def test_ffmpeg_is_left_alone_unless_it_is_the_lean_homebrew_formula(self):
        """Not macOS, no ffmpeg-full installed, a different formula, a binary outside any Cellar and
        an ffmpeg-full of ANOTHER prefix all keep what PATH resolves."""
        prefix, bindir = self._brew_tree()
        self.assertEqual(self._exe("ffmpeg", bindir, system="Linux"), (str(bindir / "ffmpeg"), "path"))
        _, bindir = self._brew_tree(full=False)
        self.assertEqual(self._exe("ffmpeg", bindir)[1], "path")
        _, bindir = self._brew_tree(formula="ffmpeg-custom")
        self.assertEqual(self._exe("ffmpeg", bindir)[1], "path")
        _, bindir = self._brew_tree(full=False, other_prefix_full=True)
        self.assertEqual(self._exe("ffmpeg", bindir)[1], "path")
        plain = Path(tempfile.mkdtemp(prefix="plain-", dir=OUT))
        self.addCleanup(shutil.rmtree, plain, True)
        (plain / "ffmpeg").write_text("#!/bin/sh\n")
        (plain / "ffmpeg").chmod(0o755)
        self.assertEqual(self._exe("ffmpeg", plain), (str(plain / "ffmpeg"), "path"))
        self.assertEqual(self._exe("ffprobe", plain), ("", ""))

    @unittest.skipIf(os.name == "nt", "symlinked fake Homebrew prefix")
    def test_doctor_names_the_binary_it_will_run(self):
        """doctor's additive keys, and its plain output, say which build runs and why."""
        from unittest import mock
        prefix, bindir = self._brew_tree()
        with mock.patch("platform.system", return_value="Darwin"), mock.patch.dict(os.environ, {"PATH": str(bindir)}):
            rep = _contract._exe_report()
        self.assertEqual(rep["ffmpeg_path"], str(prefix / "opt" / "ffmpeg-full" / "bin" / "ffmpeg"))
        self.assertEqual(rep["ffprobe_source"], "homebrew-ffmpeg-full")
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json").stdout)
        for key in ("ffmpeg_path", "ffmpeg_source", "ffprobe_path", "ffprobe_source"):
            self.assertIn(key, d)

    def test_drawtext_fix_hint_tells_an_absent_filter_from_a_crash(self):
        absent = _contract._capability_fix_hint("filter:drawtext")
        self.assertIn("no drawtext filter", absent)
        self.assertNotIn("crashed", absent)
        self.assertIn("crashed", _contract._capability_fix_hint("filter:drawtext", True))

    def test_macos_fix_hint_says_ffmpeg_full_is_keg_only(self):
        """Homebrew's ffmpeg-full is keg-only: `brew install ffmpeg-full` alone leaves the lean
        formula (or no ffmpeg) on PATH, so a hint that only says to install it sends the user
        round in a loop. Both the missing-filter and the missing-ffmpeg hints must name the PATH
        step, and README must document the same command."""
        from unittest import mock
        path_step = 'export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"'
        with mock.patch("platform.system", return_value="Darwin"):
            for cap in ("filter:subtitles", "ffmpeg"):
                hint = _contract._capability_fix_hint(cap)
                self.assertIn(path_step, hint, cap)
                self.assertIn("keg-only", hint, cap)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(path_step, readme)
        self.assertIn("keg-only", readme)
        installer = (ROOT / "bin" / "install.js").read_text(encoding="utf-8")
        self.assertIn(path_step, installer, "the npm installer's missing-ffmpeg warning gives the same command")

    def test_original_preservation_and_roles(self):
        for t in self.contract["tools"]:
            self.assertFalse(t["mutates_input"], t["name"])
            self.assertIn(t["role"], self.contract["roles"])
            self.assertIn(t["idempotency_hint"], self.contract["idempotency_hints"])
        self.assertEqual(self.tools["probe"]["role"], "analysis")
        self.assertEqual(self.tools["silence"]["role"], "analysis_and_execution")
        self.assertEqual(self.tools["loudness"]["role"], "analysis_and_execution")
        self.assertEqual(self.tools["cut"]["role"], "execution")
        self.assertEqual(self.tools["export"]["role"], "execution")
        for name in ("check", "look", "verify"):
            self.assertEqual(self.tools[name]["role"], "verification")
        self.assertFalse(self.tools["verify"]["deterministic_inputs"])
        self.assertTrue(self.tools["probe"]["deterministic_inputs"])

    def test_json_determinism(self):
        a = sh(sys.executable, SCRIPTS / "_contract.py", "--json").stdout
        b = sh(sys.executable, SCRIPTS / "_contract.py", "--json").stdout
        self.assertEqual(a, b)
        doc = json.loads(a)
        self.assertEqual(json.dumps(doc, sort_keys=True), json.dumps(doc, sort_keys=True))
        self.assertEqual(list(json.loads(a).keys()), sorted(json.loads(a).keys()), "top-level keys sorted")

    # ------------------------------------------------------------------ release version resolution
    def test_release_version_resolver_rules(self):
        """.github/scripts/resolve_version.py decides whether a push to main releases and what
        version. Pinned with fake label data because the two incidents of 2026-09-11 (1.0.0-1.0.2,
        then 1.0.4) were both a resolver doing something other than what its config was assumed
        to mean, and nothing exercised the rules with fixed inputs."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "resolve_version", ROOT / ".github" / "scripts" / "resolve_version.py")
        rv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rv)

        def labels(table):
            return lambda n: table.get(n, [])

        # chore-only / dependencies-only PRs release nothing (the 1.0.4 case)
        v, _ = rv.resolve("1.0.3", ["chore(release): x (#145)"], labels({145: ["chore"]}))
        self.assertIsNone(v)
        v, _ = rv.resolve("1.0.3", ["build(deps): bump x (#132)"], labels({132: ["dependencies", "github_actions", "chore"]}))
        self.assertIsNone(v)
        # Dependabot labels a semver-major bump of an *action* `major` (actions/checkout 4->7,
        # #168/#169); that is the dependency's major, not ours, and it blocked 1.4.9 on 2026-09-12.
        # A dependencies PR is not releasable whatever else it carries, and does not trip the refusal.
        v, d = rv.resolve("1.4.8", ["fix: x (#183)", "build(deps): bump actions/checkout from 4 to 7 (#168)"],
                          labels({183: ["chore", "fix"], 168: ["dependencies", "github_actions", "chore", "major"]}))
        self.assertEqual(v, "1.4.9")
        self.assertEqual([x["bump"] for x in d], ["patch", None])
        # fix wins over chore on the same PR (#136 -> 1.0.3)
        v, _ = rv.resolve("1.0.2", ["Fix the Codex install path (#136)"], labels({136: ["chore", "fix"]}))
        self.assertEqual(v, "1.0.3")
        # unlabeled PR still ships as a patch
        v, _ = rv.resolve("1.0.3", ["Something (#150)"], labels({})) 
        self.assertEqual(v, "1.0.4")
        # any minor among several -> minor, and patch digit resets
        v, d = rv.resolve("1.0.3", ["Add x (#151)", "Fix y (#152)", "chore: z (#153)"],
                          labels({151: ["feature"], 152: ["fix"], 153: ["chore"]}))
        self.assertEqual(v, "1.1.0")
        self.assertEqual([x["bump"] for x in d], ["minor", "patch", None])
        # a commit that came from no PR: patch unless its subject is chore/ci/docs/build
        v, _ = rv.resolve("1.0.3", ["Fix by direct push"], labels({}))
        self.assertEqual(v, "1.0.4")
        v, _ = rv.resolve("1.0.3", ["docs: typo", "ci: retry", "chore(release): bump version to 1.0.3"], labels({}))
        self.assertIsNone(v)
        # major is never resolved automatically (the 1.0.0 case), whatever else is there
        with self.assertRaises(SystemExit):
            rv.resolve("1.0.3", ["Fix y (#152)", "Big (#154)"], labels({152: ["fix"], 154: ["major"]}))

    # ------------------------------------------------------------------ FFmpeg-version-dependent spellings
    def test_drawtext_boxborderw_spelling_follows_the_ffmpeg_version(self):
        """drawtext's per-side `boxborderw=v|h` arrived in FFmpeg 6.1; 5.x and 6.0 reject the
        `|` outright ("Error setting option boxborderw"), which is how graphics.py's chapter and
        bug templates failed on the 5.1.1 CI job (#146). The helper picks the spelling from the
        parsed `ffmpeg -version`; pinned here with the version forced, so the rule survives
        without a 5.x binary on the machine running the tests."""
        saved = _common._FFMPEG_VERSION
        try:
            for version, expected in (((5, 1), "16"), ((6, 0), "16"), ((6, 1), "9|16"), ((7, 1), "9|16"), ((0, 0), "16")):
                _common._FFMPEG_VERSION = version
                self.assertEqual(_common.drawtext_boxborderw(9, 16), expected, version)
        finally:
            _common._FFMPEG_VERSION = saved
        _common._FFMPEG_VERSION = None
        major, minor = _common.ffmpeg_version()
        self.assertGreaterEqual(major, 5, "the real ffmpeg on PATH must parse to a sane version")
        self.assertIn(_common.drawtext_boxborderw(9, 16), ("16", "9|16"))

    def test_skill_frontmatter_is_strict_yaml(self):
        """The description used to be an unquoted scalar containing ": " ("...natural-language
        requests: cut, trim, ..."), which a strict YAML parser reads as a second mapping key and
        rejects ("mapping values are not allowed here", line 3 column 83) -- GitHub's own renderer
        flagged it, and any installer that parses the frontmatter strictly would lose the one
        field agents discover the skill by. Pinned without PyYAML: every frontmatter line must be
        `key: value` where a value containing ": " or starting with a YAML indicator is quoted,
        and the quoted description must round-trip through the contract's reader."""
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        fm = text.split("---\n", 2)[1].rstrip("\n").split("\n")
        for line in fm:
            key, sep, value = line.partition(": ")
            self.assertTrue(sep and re.fullmatch(r"[a-z_-]+", key), line)
            quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "'\""
            if ": " in value or value[:1] in "[{&*!|>%@`#":
                self.assertTrue(quoted, f"{key}: needs quoting for a strict YAML parser: {value[:60]}")
            if quoted and value[0] == "'":
                self.assertNotRegex(value[1:-1], r"(?<!')'(?!')", f"{key}: a lone ' inside a single-quoted scalar")
        desc = _contract.skill_description()
        self.assertTrue(desc.startswith("Edit video and audio"), desc[:40])
        self.assertNotIn("'", desc[:1] + desc[-1:], "the contract must expose the unquoted text")
        self.assertEqual(desc, self.contract["skill"]["description"])

    def test_bt709_tags_go_through_encoder_vui_from_ffmpeg_7_1(self):
        """FFmpeg 7.1 added colourspace negotiation to libavfilter and feeds the output options
        -colorspace/-color_primaries/-color_trc into the graph's constraints: on a source with
        no colour tags at all, the CLI then auto-inserts a *real* matrix conversion (guessing
        bt601) into every SDR re-encode -- `color --lut-strength 0` came back 23.9 dB PSNR from
        its source on the debian-trixie job (#156), and every x264_args() user was affected.
        5.x/6.x only ever wrote tags. From 7.1 the tags are written through the encoder's own
        VUI parameters, which libavfilter never sees; before it the old spelling stays, so the
        mp4 keeps its colr atom on the builds where that was the only way to get one."""
        saved = _common._FFMPEG_VERSION
        try:
            old = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
            for version, expected in (((5, 1), old), ((6, 1), old), ((7, 0), old), ((0, 0), old),
                                      ((7, 1), ["-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]),
                                      ((8, 0), ["-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"])):
                _common._FFMPEG_VERSION = version
                self.assertEqual(_common.bt709_tag_args("libx264"), expected, version)
                self.assertEqual(_common.x264_args()[-len(expected):], expected, version)
            _common._FFMPEG_VERSION = (7, 1)
            self.assertEqual(_common.bt709_tag_args("libx265"), ["-x265-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"])
        finally:
            _common._FFMPEG_VERSION = saved

    def test_bt601_matrix_conversion_rides_on_the_encoder_line(self):
        """The BT.709 tags are a label (above); a source whose matrix is BT.601 also needs its pixels
        converted, or it comes out BT.709-labelled over BT.601 pixels. The encoder line carries that
        conversion as a -vf, from the source's probe only: an untagged, BT.709 or HDR source, prores
        (which keeps the source's tags) and a tool that converts per input get nothing."""
        def meta(**v):
            return {"file": "src.mp4", "video": dict({"bt2020_or_hdr": False}, **v)}
        conv = "colorspace=ispace={}:iprimaries=bt709:itrc=bt709:space=bt709:primaries=bt709:trc=bt709"
        for matrix in ("smpte170m", "bt470bg", "fcc", "smpte240m"):
            self.assertEqual(_common.bt709_matrix_filter(meta(color_space=matrix)), conv.format(matrix), matrix)
        for m in (None, {}, meta(), meta(color_space="bt709"), meta(color_space="unknown"), meta(color_space="gbr"),
                  meta(color_space="bt2020nc", bt2020_or_hdr=True), meta(color_space="smpte170m", bt2020_or_hdr=True)):
            self.assertIsNone(_common.bt709_matrix_filter(m), m)
        saved = (_common.STATE.codec, _common.STATE.hw)
        try:
            _common.STATE.hw = False
            for codec in (None, "h264", "hevc"):
                _common.STATE.codec = codec
                line = _common.video_args(meta(color_space="smpte170m"))
                self.assertEqual(line[-2:], ["-vf", conv.format("smpte170m")], codec)
                self.assertNotIn("-vf", _common.video_args(meta(color_space="bt709")), codec)
                self.assertNotIn("-vf", _common.video_args(meta()), codec)
                self.assertNotIn("-vf", _common.video_args(meta(color_space="smpte170m"), convert_matrix=False), codec)
                self.assertEqual(_common.x264_args(source=meta(color_space="bt470bg"))[-2:], ["-vf", conv.format("bt470bg")], codec)
                self.assertNotIn("-vf", _common.x264_args(), codec)
                self.assertEqual(_common.matrix_chain(meta(color_space="smpte170m"), meta()), conv.format("smpte170m") + ",")
                self.assertEqual(_common.matrix_chain(meta(), meta()), "")
            # an HDR line keeps its own tags: a BT.601 clip joined into it is not "converted to BT.709"
            self.assertEqual(_common.matrix_chain(meta(color_space="smpte170m"), meta(bt2020_or_hdr=True)), "")
            _common.STATE.codec = "prores"
            self.assertNotIn("-vf", _common.video_args(meta(color_space="smpte170m")))
            self.assertEqual(_common.matrix_chain(meta(color_space="smpte170m"), meta()), "")
        finally:
            _common.STATE.codec, _common.STATE.hw = saved

    def test_fold_bt709_matrix_into_the_tools_graph(self):
        """run() moves the encoder line's conversion -vf into the tool's own graph, first: with no
        other filter it is the graph; a -vf gets it prepended; a -filter_complex reads every input
        that opens input 0's file through it (once per input, split when read twice), other inputs
        untouched. A command without it is returned as it was."""
        conv = _common.bt709_matrix_filter({"video": {"color_space": "smpte170m"}})
        fold = _common.fold_bt709_matrix
        enc = ["-c:v", "libx264", "-crf", "18", "-vf", conv, "out.mp4"]
        self.assertEqual(fold(["ffmpeg", "-i", "a.mp4"] + enc), ["ffmpeg", "-i", "a.mp4"] + enc)
        self.assertEqual(fold(["ffmpeg", "-i", "a.mp4", "-vf", "scale=2:2,setsar=1"] + enc),
                         ["ffmpeg", "-i", "a.mp4", "-vf", f"{conv},scale=2:2,setsar=1", "-c:v", "libx264", "-crf", "18", "out.mp4"])
        # speedramp reads [0:v] once per segment; a logo (input 1) is not the source
        got = fold(["ffmpeg", "-i", "a.mp4", "-i", "logo.png", "-filter_complex",
                    "[0:v]trim=0:1[x];[0:v]trim=1:2[y];[1:v]scale=9:9[l];[x][y]concat[c];[c][l]overlay[out]", "-map", "[out]"] + enc)
        self.assertEqual(got[got.index("-filter_complex") + 1],
                         f"[0:v]{conv},split=2[bt709src0][bt709src1];"
                         "[bt709src0]trim=0:1[x];[bt709src1]trim=1:2[y];[1:v]scale=9:9[l];[x][y]concat[c];[c][l]overlay[out]")
        self.assertNotIn(conv, got[got.index("-filter_complex") + 2:])
        # cut.py's segment join opens the source once per segment; join.py's second clip is another file
        got = fold(["ffmpeg", "-ss", "1", "-i", "a.mp4", "-ss", "5", "-i", "a.mp4", "-i", "b.mp4", "-filter_complex",
                    "[0:v:0]trim=0:1[v0];[1:v:0]trim=0:1[v1];[2:v]null[v2];[v0][v1][v2]concat=n=3[v]", "-map", "[v]"] + enc)
        self.assertEqual(got[got.index("-filter_complex") + 1],
                         f"[0:v:0]{conv}[bt709src0];[1:v:0]{conv}[bt709src1];"
                         "[bt709src0]trim=0:1[v0];[bt709src1]trim=0:1[v1];[2:v]null[v2];[v0][v1][v2]concat=n=3[v]")
        plain = ["ffmpeg", "-i", "a.mp4", "-vf", "scale=2:2", "-c:v", "libx264", "out.mp4"]
        self.assertEqual(fold(plain), plain)
        with self.assertRaises(SystemExit):
            fold(["ffmpeg", "-i", "a.mp4", "-filter_complex", "color=red[v]", "-map", "[v]"] + enc)

    def test_an_rgb_source_or_a_still_is_converted_to_the_bt709_it_is_tagged_with(self):
        """#332's follow-ups. An RGB picture (PNG, image sequence, qtrle) has no matrix; FFmpeg gave it
        BT.601 wherever the graph first needed YUV, under a BT.709 tag. It is converted where it enters:
        a source by the encoder line's -vf (folded like the BT.601 one; a palette is expanded first,
        swscale converts a palette with fixed BT.601), a still the tool made RGBA at the end of its own
        chain (rgb_chain_to_bt709). An untagged picture that meets a converted one in a mixing filter
        gets a BT.709 label, tags only, so 7.1+'s negotiation converts neither (label_chain). Gray,
        YUV, HDR, prores lines and a missing probe get nothing."""
        def meta(**v):
            return {"file": "src", "video": dict({"bt2020_or_hdr": False}, **v)}
        rgb = "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p"
        for pf in ("rgb24", "rgba", "bgra", "argb", "gbrp", "rgb48be", "rgba64be", "bgr0"):
            self.assertEqual(_common.bt709_matrix_filter(meta(pix_fmt=pf, color_space="gbr")), rgb, pf)
            self.assertEqual(_common.bt709_matrix_filter(meta(pix_fmt=pf)), rgb, pf)  # qtrle: no matrix tag at all
        self.assertEqual(_common.bt709_matrix_filter(meta(pix_fmt="pal8", color_space="gbr")), "format=rgb24," + rgb)
        for m in (meta(pix_fmt="gray"), meta(pix_fmt="ya8"), meta(pix_fmt="yuv420p"), meta(pix_fmt="yuvj420p"),
                  meta(pix_fmt="rgb48be", bt2020_or_hdr=True), meta(color_space="gbr")):
            self.assertIsNone(_common.bt709_matrix_filter(m), m)
        # a JPEG probes as yuvj420p/bt470bg: a BT.601 source like any other
        self.assertTrue(_common.bt709_matrix_filter(meta(pix_fmt="yuvj420p", color_space="bt470bg", color_range="pc")).startswith("colorspace=ispace=bt470bg:"))
        png = meta(pix_fmt="rgb24", color_space="gbr")
        saved = (_common.STATE.codec, _common.STATE.hw)
        try:
            _common.STATE.hw = False
            for codec in (None, "h264", "hevc"):
                _common.STATE.codec = codec
                self.assertEqual(_common.video_args(png)[-2:], ["-vf", rgb], codec)
                self.assertEqual(_common.video_args(None, source=png)[-2:], ["-vf", rgb], codec)  # insert.py / sequence.py
                self.assertNotIn("-vf", _common.video_args(None), codec)
                self.assertNotIn("-vf", _common.video_args(None, source=meta(pix_fmt="yuv420p")), codec)
                self.assertEqual(_common.matrix_chain(png, None), rgb + ",")
                self.assertEqual(_common.rgb_chain_to_bt709(None), ",scale=out_color_matrix=bt709:out_range=tv,format=yuva420p")
                self.assertEqual(_common.rgb_chain_to_bt709(meta(pix_fmt="yuv420p"), "yuv420p"),
                                 ",scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
                self.assertEqual(_common.label_chain(meta(pix_fmt="yuv420p"), None), "setparams=colorspace=bt709:range=tv,")
                self.assertEqual(_common.label_chain(meta(pix_fmt="yuvj420p", color_range="pc"), None), "setparams=colorspace=bt709,")
                for tagged in (meta(pix_fmt="yuv420p", color_space="bt709"), meta(pix_fmt="yuv420p", color_space="smpte170m"),
                               png, meta(pix_fmt="yuv420p10le", bt2020_or_hdr=True), meta(), None):
                    self.assertEqual(_common.label_chain(tagged, None), "", tagged)
            # an HDR line keeps its own tags, prores the source's: neither converts nor relabels a still
            hdr = meta(pix_fmt="yuv420p10le", bt2020_or_hdr=True)
            self.assertEqual(_common.rgb_chain_to_bt709(hdr), "")
            self.assertEqual(_common.label_chain(meta(pix_fmt="yuv420p"), hdr), "")
            _common.STATE.codec = "prores"
            self.assertNotIn("-vf", _common.video_args(None, source=png))
            self.assertEqual((_common.rgb_chain_to_bt709(None), _common.label_chain(meta(pix_fmt="yuv420p"), None)), ("", ""))
        finally:
            _common.STATE.codec, _common.STATE.hw = saved
        fold = _common.fold_bt709_matrix
        for conv in (rgb, "format=rgb24," + rgb):
            enc = ["-c:v", "libx264", "-vf", conv, "out.mp4"]
            self.assertEqual(fold(["ffmpeg", "-loop", "1", "-i", "a.png", "-vf", "scale=2:2"] + enc),
                             ["ffmpeg", "-loop", "1", "-i", "a.png", "-vf", f"{conv},scale=2:2", "-c:v", "libx264", "out.mp4"])

    # ------------------------------------------------------------------ consistency: MCP and installer
    def test_mcp_tools_match_contract(self):
        """FFMPEG_SKILL_MCP_FULL=1 is the escape hatch back to the pre-1.18.3 behaviour: every
        contract tool listed. This test proves that view is still byte-for-byte the full set."""
        saved = os.environ.get("FFMPEG_SKILL_MCP_FULL")
        os.environ["FFMPEG_SKILL_MCP_FULL"] = "1"
        try:
            mcp_names = [t["name"] for t in mcp_server.tool_list()]
            self.assertEqual(sorted(mcp_names), sorted(self.tools), "MCP tools/list (full) == contract tools")
            listed = [l.split()[0] for l in sh(sys.executable, ROOT / "mcp" / "server.py", "--list", env={**os.environ}).stdout.splitlines() if l.strip()]
            self.assertEqual(sorted(listed), sorted(self.tools))
        finally:
            os.environ.pop("FFMPEG_SKILL_MCP_FULL", None)
            if saved is not None:
                os.environ["FFMPEG_SKILL_MCP_FULL"] = saved
        for name, spec in self.tools.items():
            self.assertEqual(spec["mcp"]["tool"], name)
            self.assertEqual(spec["mcp"]["positional"], mcp_server.POSITIONAL.get(name, ["input"]) if spec["mcp"]["positional"] else spec["mcp"]["positional"])
        # a real JSON-RPC round trip, full surface
        resp = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], full=True)[0]
        self.assertEqual(sorted(t["name"] for t in resp["result"]["tools"]), sorted(self.tools))

    def test_mcp_tools_list_defaults_to_the_core_12(self):
        """roadmap P1-7 (docs/design-decisions.md): tools/list defaults to _contract.MCP_CORE_TOOLS,
        in contract order, not all 42 -- and every one of those 12 is a real contract tool. The
        other 30 stay reachable through tools/call (proved by test_mcp_schema_drift_follows_the_scripts
        and test_mcp_server_error_paths_raw_argv_and_call_helper calling non-core tools directly)."""
        self.assertEqual(len(_contract.MCP_CORE_TOOLS), 12)
        self.assertTrue(set(_contract.MCP_CORE_TOOLS).issubset(self.tools), "every core tool is a real contract tool")
        expected_order = [n for n in self.tools if n in _contract.MCP_CORE_TOOLS]
        mcp_names = [t["name"] for t in mcp_server.tool_list()]
        self.assertEqual(mcp_names, expected_order, "default MCP tools/list is the core 12, in contract order")
        resp = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]
        self.assertEqual([t["name"] for t in resp["result"]["tools"]], expected_order, "JSON-RPC round trip matches")
        for flag in ("0", ""):
            resp = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], full=False)[0]
            self.assertEqual([t["name"] for t in resp["result"]["tools"]], expected_order, f"FFMPEG_SKILL_MCP_FULL={flag!r} still core 12")
        listed = [l.split()[0] for l in sh(sys.executable, ROOT / "mcp" / "server.py", "--list").stdout.splitlines() if l.strip()]
        self.assertEqual(listed, expected_order)

    def test_mcp_tool_descriptions_are_one_liners_with_the_structured_note_moved_to_initialize(self):
        """1.20.0 agent ergonomics: MCP_STRUCTURED_NOTE used to be appended to every one of the 42
        tool descriptions verbatim (the same ~250 characters repeated 42 times in a tools/list
        dump). It is server-wide, not per-tool, so it now goes once into initialize's
        `instructions` field instead, and each tool's own `description` is just its one-line
        sentence again (no embedded newline, no trailing structured-arguments boilerplate)."""
        for t in mcp_server.tool_list():
            self.assertNotIn("\n", t["description"], f"{t['name']}: description should be one line")
            self.assertNotIn("Structured arguments", t["description"],
                              f"{t['name']}: the structured-arguments note belongs in initialize, not per tool")
        resp = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])[0]
        self.assertEqual(resp["result"]["instructions"], _contract.MCP_STRUCTURED_NOTE)

    def test_mcp_prompts_capability_lists_and_fills_the_five_workflows(self):
        """roadmap 1.20.0 agent ergonomics: a `prompts` capability with the five workflows
        (reel, podcast, multicam, delivery_check, hdr). initialize advertises it; prompts/list
        names each one with its arguments; prompts/get fills the template with real values,
        including the optional-argument clauses (cues, chapters) that drop cleanly when the
        argument is omitted; a missing required argument or an unknown prompt name is a
        JSON-RPC error, not a silently wrong or empty prompt."""
        init = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])[0]
        self.assertIn("prompts", init["result"]["capabilities"])

        listed = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "prompts/list"}])[0]["result"]["prompts"]
        self.assertEqual(sorted(p["name"] for p in listed), sorted(p["name"] for p in _contract.MCP_PROMPTS))
        self.assertEqual({"reel", "podcast", "multicam", "delivery_check", "hdr"}, {p["name"] for p in listed})
        for p in listed:
            self.assertTrue(p["description"])
            self.assertTrue(any(a["required"] for a in p["arguments"]), f"{p['name']}: needs at least one required argument")

        got = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                           "params": {"name": "reel", "arguments": {"input": "/abs/clip.mp4"}}}])[0]["result"]
        text = got["messages"][0]["content"]["text"]
        self.assertIn("/abs/clip.mp4", text)
        self.assertIn("reels", text, "default platform applies when not given")
        self.assertNotIn("cues", text, "no cues argument -> no dangling cues clause")

        with_cues = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                                 "params": {"name": "reel", "arguments": {"input": "/abs/clip.mp4", "platform": "tiktok", "cues": "/abs/cues.txt"}}}])[0]["result"]
        cues_text = with_cues["messages"][0]["content"]["text"]
        self.assertIn("tiktok", cues_text)
        self.assertIn("/abs/cues.txt", cues_text)

        missing = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                               "params": {"name": "delivery_check", "arguments": {"input": "/abs/x.mp4"}}}])[0]
        self.assertIn("error", missing)
        self.assertIn("platform", missing["error"]["message"])

        unknown = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                               "params": {"name": "not_a_real_prompt", "arguments": {}}}])[0]
        self.assertIn("error", unknown)
        self.assertNotEqual(unknown["error"]["code"], -32601, "an unknown prompt name is not the same as an unknown method")

    def test_mcp_tool_surface_matches_the_frozen_1x_snapshot(self):
        """docs/contract.md, "Stability guarantee (1.x)": within 1.x no tool is removed or renamed
        and no argument is removed, renamed or made newly required. The MCP surface is *derived*
        from the argparse parsers, so a careless parser edit changes it with no edit under mcp/ --
        which is exactly why the surface is pinned here as data rather than trusted to a review.
        tests/fixtures/mcp_tools.json holds, per tool, the argument names and which are required.
        Adding a tool or an optional argument is allowed and must be reflected by regenerating the
        snapshot (UPDATE_MCP_SNAPSHOT=1 python3 tests/test_contract.py); removing or renaming
        anything, or making an argument required, is a breaking change and belongs behind the
        deprecation policy and a major bump, not behind a regenerated fixture. The snapshot covers
        all 42 tools, so this reads tool_list() under FFMPEG_SKILL_MCP_FULL=1 -- the default's
        core-12 filter is a separate, tested concern (test_mcp_tools_list_defaults_to_the_core_12)."""
        snapshot_path = ROOT / "tests" / "fixtures" / "mcp_tools.json"
        saved = os.environ.get("FFMPEG_SKILL_MCP_FULL")
        os.environ["FFMPEG_SKILL_MCP_FULL"] = "1"
        try:
            live = [{"name": t["name"],
                     "properties": sorted(t["inputSchema"].get("properties", {}).keys()),
                     "required": sorted(t["inputSchema"].get("required", []))}
                    for t in mcp_server.tool_list()]
        finally:
            os.environ.pop("FFMPEG_SKILL_MCP_FULL", None)
            if saved is not None:
                os.environ["FFMPEG_SKILL_MCP_FULL"] = saved
        if os.environ.get("UPDATE_MCP_SNAPSHOT"):
            snapshot_path.write_text(json.dumps(live, indent=1) + "\n", encoding="utf-8")
        frozen = json.loads(snapshot_path.read_text(encoding="utf-8"))
        frozen_by_name = {t["name"]: t for t in frozen}
        live_by_name = {t["name"]: t for t in live}
        removed = sorted(set(frozen_by_name) - set(live_by_name))
        self.assertEqual(removed, [], f"tools removed/renamed since the 1.x snapshot: {removed}")
        for name, was in frozen_by_name.items():
            now = live_by_name[name]
            gone = sorted(set(was["properties"]) - set(now["properties"]))
            self.assertEqual(gone, [], f"{name}: arguments removed/renamed since the 1.x snapshot: {gone}")
            newly_required = sorted(set(now["required"]) - set(was["required"]))
            self.assertEqual(newly_required, [], f"{name}: arguments made required since the 1.x snapshot: {newly_required}")
        # Additions are fine but must be snapshotted so the next reader sees the current surface.
        self.assertEqual(live, frozen,
                         "MCP surface grew (new tool or optional argument) -- regenerate the snapshot: "
                         "UPDATE_MCP_SNAPSHOT=1 python3 tests/test_contract.py")

    def test_mcp_schema_leaves_out_the_transport_flags(self):
        """2.0 (deprecated in 1.10.0, opt-in then as FFMPEG_SKILL_MCP_LEAN=1): `json` and
        `progress` are CLI transport flags the server sets itself, so no inputSchema lists them --
        and nothing else is dropped: every other CLI option still has its property. A client that
        still sends `json: true` is not refused; the server maps it like any other key."""
        tools = _contract.mcp_tools()
        for tool in tools:
            with self.subTest(tool=tool["name"]):
                props = tool["inputSchema"]["properties"]
                for dest in ("json", "progress"):
                    self.assertNotIn(dest, props)
                cli = set(self.tools[tool["name"]]["input_schema"]["properties"]) - {"json", "progress"}
                self.assertEqual(cli - set(props), set(), "only json/progress are left out")
        resp = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]
        self.assertNotIn("json", resp["result"]["tools"][0]["inputSchema"]["properties"])
        self.assertIn("--json", mcp_server.build_argv("cut", {"input": "/x.mp4", "json": True}))

    def test_contract_lists_what_the_next_major_removes_and_what_2_0_removed(self):
        """docs/contract.md, "Deprecation policy" step 1 and "What 2.0 changed": everything a major
        removes is announced in the contract itself (`deprecated`), and what 2.0.0 removed stays
        listed with the version that deprecated it (`removed`), so a caller can diff the lists
        instead of reading a CHANGELOG."""
        pkg_major = int(json.loads((ROOT / "package.json").read_text())["version"].split(".")[0])
        for key in ("deprecated", "removed"):
            for entry in self.contract[key]:
                with self.subTest(key=key, what=entry["what"]):
                    self.assertEqual(sorted(entry), ["removed_in", "replacement", "since", "what", "where"])
                    self.assertIn(entry["where"], ("cli", "json", "mcp", "behaviour"))
                    self.assertTrue(entry["replacement"])
        for entry in self.contract["deprecated"]:
            self.assertGreater(int(entry["removed_in"].split(".")[0]), pkg_major)
        removed = self.contract["removed"]
        self.assertTrue(removed)
        for entry in removed:
            self.assertEqual(entry["removed_in"], "2.0.0")
        for surface in ("cli", "json", "mcp", "behaviour"):
            self.assertIn(surface, [e["where"] for e in removed])

    def test_contract_md_2_0_table_matches_removed(self):
        """docs/contract.md's "What 2.0 changed" table restates `removed`, row for row, with the
        version each was deprecated in. release.yml's auto-bump used to replace every occurrence
        of the old version in that file, so by 1.26.0 that column read "1.26.0" for deprecations
        made in 1.10.0 -- the date 2.0's window is counted from. Pin the column, in order."""
        text = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        section = text.split("| What changed in 2.0.0 | Deprecated in |", 1)[1].split("\n\n", 1)[0]
        rows = [r for r in section.splitlines()[1:] if r.startswith("| ")]
        self.assertEqual(len(rows), len(_contract.REMOVED))
        for row, entry in zip(rows, _contract.REMOVED):
            self.assertTrue(row.split(" | ")[1].strip().startswith(entry["since"]), row[:80])
        example = re.search(r'"removed": \[\{"what": "\.\.\.", "since": "([^"]+)"', text)
        self.assertIsNotNone(example, "docs/contract.md: removed example not found")
        self.assertIn(example.group(1), {e["since"] for e in _contract.REMOVED})

    # Release date of each version a deprecation dates from (git tag date). CI checks out without
    # tags, so the dates live here, and they stay after the major that removes the entries: they
    # are what that major's own PR is checked against.
    # None: not released yet. Set it to the tag date when that version ships; a major bump fails
    # while it is None, because the 90-day window cannot be counted from an unknown date.
    DEPRECATION_RELEASE_DATES = {"1.10.0": "2026-09-13", "2.10.9": "2026-10-22", "2.14.0": None}
    # A major released before step 2's 90 days had passed, by the maintainer's decision. Each one
    # must be stated in docs/contract.md (the needle below), so it is a written waiver, not a slip.
    WINDOW_WAIVERS = {2: "**2.0.0 waived the 90-day half of step 2.**"}

    def test_major_release_waits_for_the_deprecation_window(self):
        """docs/contract.md "Deprecation policy" step 2: keep a deprecated form for at least two
        further minor releases or 90 days, whichever is longer; step 3 removes it only in the next
        major. Nothing enforced either: release.yml refuses to auto-bump across a major, but a
        hand-bumped package.json in a PR could ship a major the day after a deprecation, or ship it
        with the deprecated forms still in place. This fails on such a PR, not after the release.
        2.0.0 waived the 90 days (WINDOW_WAIVERS); the two-minor half is still checked."""
        import datetime
        pkg = json.loads((ROOT / "package.json").read_text())
        major = int(pkg["version"].split(".")[0])
        for entry in _contract.DEPRECATED:
            with self.subTest(what=entry["what"]):
                self.assertIn(entry["since"], self.DEPRECATION_RELEASE_DATES,
                              f"add {entry['since']}'s release date to DEPRECATION_RELEASE_DATES")
                self.assertGreater(int(entry["removed_in"].split(".")[0]), major,
                                   f"package.json is {pkg['version']} but {entry['what']!r} is still "
                                   f"deprecated, not removed: remove it, then drop the entry")
        for entry in _contract.REMOVED:
            self.assertIn(entry["since"], self.DEPRECATION_RELEASE_DATES)
        contract_md = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        for m, needle in self.WINDOW_WAIVERS.items():
            self.assertIn(needle, contract_md, f"the {m}.0.0 waiver is not stated in docs/contract.md")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        released = {tuple(int(x) for x in v.split(".")) for v in re.findall(r"(?m)^## (\d+\.\d+\.\d+)\s*$", changelog)}
        for since, day in self.DEPRECATION_RELEASE_DATES.items():
            s_major, s_minor, _ = (int(x) for x in since.split("."))
            if s_major >= major:
                continue  # its removal is a later major's; nothing to check until then
            with self.subTest(since=since):
                self.assertIsNotNone(day, f"{since}: set its release date in DEPRECATION_RELEASE_DATES before a major removes it")
                later_minors = {(a, b) for a, b, _ in released if a == s_major and b > s_minor}
                self.assertGreaterEqual(len(later_minors), 2, f"{since}: fewer than two further minor releases")
                if s_major + 1 in self.WINDOW_WAIVERS:
                    continue
                earliest = datetime.date.fromisoformat(day) + datetime.timedelta(days=90)
                self.assertGreaterEqual(datetime.date.today(), earliest,
                                        f"{pkg['version']} removes {since}'s deprecations before {earliest}")

    def test_design_decisions_contents_list_is_current_and_release_renames_unreleased(self):
        """docs/design-decisions.md opens with a contents list built from its `## ` headings
        (.github/scripts/design_decisions_index.py --write regenerates it). release.yml renames a
        `## Unreleased — topic` section to the version that shipped it: eleven had kept saying
        "Unreleased" from 2.3.0 to 2.12.0."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "design_decisions_index", ROOT / ".github" / "scripts" / "design_decisions_index.py")
        idx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(idx)
        text = (ROOT / "docs" / "design-decisions.md").read_text(encoding="utf-8")
        self.assertEqual(idx.apply(text), text,
                         "the contents list is stale: python3 .github/scripts/design_decisions_index.py --write")
        self.assertNotIn("\n## Unreleased", text, "a released section still says Unreleased")
        draft = text.replace("\n## Time limits\n", "\n## Unreleased — a new topic\n\n## Time limits\n", 1)
        out = idx.release_headings(idx.apply(draft), "9.9.9")
        self.assertIn("\n## 9.9.9 — a new topic\n", out)
        self.assertIn("- [9.9.9 — a new topic](#999--a-new-topic)", out)
        self.assertIn("docs/design-decisions.md", (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))

    def test_release_contract_md_bump_moves_only_the_current_version(self):
        """.github/scripts/bump_contract_md.py (release.yml's auto-bump): only the two
        current-version mentions in docs/contract.md move. The step it replaced was
        `contract.replace(old, new)`, which also rewrote every historical version equal to the
        one being released -- the 2.0 table's Since column, "added in 1.17.1", "(1.18.4)"."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bump_contract_md", ROOT / ".github" / "scripts" / "bump_contract_md.py")
        bump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bump)

        old = json.loads((ROOT / "package.json").read_text())["version"]
        ma, mi, _ = old.split(".")
        new = f"{ma}.{int(mi) + 1}.0"
        text = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        out = bump.bump_contract_md(text, old, new)
        changed = [(a, b) for a, b in zip(text.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(len(changed), 2, changed)
        for a, b in changed:
            self.assertEqual(a.replace(old, new), b)

        # the 1.10.0 -> 1.10.1 release is the one that corrupted the Since column; replay it
        hist = ('| x | the npm / package.json version (`1.10.0`) | any release |\n'
                '| --crf | 1.10.0 | --quality |\n'
                '  "skill": {"id": "ffmpeg-skill", "version": "1.10.0", "kind": "execution"},\n')
        out = bump.bump_contract_md(hist, "1.10.0", "1.10.1")
        self.assertIn("| --crf | 1.10.0 |", out)
        self.assertIn("(`1.10.1`)", out)
        self.assertIn('"version": "1.10.1"', out)
        # an anchor that is missing (or doubled) is an error, never a partial bump
        with self.assertRaises(ValueError):
            bump.bump_contract_md(hist, "1.9.9", "1.10.0")
        with self.assertRaises(ValueError):
            bump.bump_contract_md(hist + hist, "1.10.0", "1.10.1")

    def test_release_roadmap_bump_moves_the_released_version_sentence(self):
        """.github/scripts/bump_roadmap_md.py (release.yml's auto-bump): the roadmap sentence
        pinned to package.json moves with the bump. The auto-bump used to skip it, so the 2.2.1
        label release left test_roadmap_released_version_matches_package_json red on main until
        a docs PR (#288). The hand-written prose stays, marked with the version it describes."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bump_roadmap_md", ROOT / ".github" / "scripts" / "bump_roadmap_md.py")
        bump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bump)

        old = json.loads((ROOT / "package.json").read_text())["version"]
        ma, mi, pa = old.split(".")
        new = f"{ma}.{mi}.{int(pa) + 1}"
        text = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
        out = bump.bump_roadmap_md(text, old, new)
        m = re.search(r"The released version today is \*\*([^*]+)\*\*", out)
        self.assertEqual(m.group(1), new)
        changed = [(a, b) for a, b in zip(text.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(len(changed), 1, changed)

        s = "The released version today is **2.2.1** — `render.py` checks inputs.\n"
        once = bump.bump_roadmap_md(s, "2.2.1", "2.2.2")
        self.assertEqual(once, "The released version today is **2.2.2** (notes in CHANGELOG.md); "
                               "**2.2.1** — `render.py` checks inputs.\n")
        twice = bump.bump_roadmap_md(once, "2.2.2", "2.2.3")
        self.assertEqual(twice, once.replace("**2.2.2**", "**2.2.3**"))
        # a missing or doubled sentence is an error, never a partial bump
        with self.assertRaises(ValueError):
            bump.bump_roadmap_md(s, "2.2.0", "2.2.1")
        with self.assertRaises(ValueError):
            bump.bump_roadmap_md(s + s, "2.2.1", "2.2.2")

    # ------------------------------------------------------------------ MCP inputSchema derived from the contract
    def _rpc(self, requests, root=ROOT, full=False):
        text = "".join(json.dumps(r) + "\n" for r in requests)
        env = dict(os.environ)
        if full:
            env["FFMPEG_SKILL_MCP_FULL"] = "1"
        else:
            env.pop("FFMPEG_SKILL_MCP_FULL", None)
        proc = subprocess.run([sys.executable, str(Path(root) / "mcp" / "server.py")], input=text, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in proc.stdout.strip().splitlines()]

    @staticmethod
    def _norm(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    def test_mcp_input_schema_equals_translated_contract_schema(self):
        listed = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], full=True)[0]["result"]["tools"]
        self.assertEqual([t["name"] for t in listed], [t["name"] for t in self.contract["tools"]], "MCP order == contract order")
        for entry in listed:
            spec = self.tools[entry["name"]]
            self.assertEqual(self._norm(entry["inputSchema"]), self._norm(_contract.mcp_input_schema(spec)), entry["name"])
            self.assertEqual(self._norm(entry), self._norm(_contract.mcp_tool(spec)))
            schema = entry["inputSchema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertIn("argv", schema["properties"])
            for dest, prop in spec["input_schema"]["properties"].items():
                if dest in _contract.MCP_TRANSPORT_FLAGS:
                    self.assertNotIn(dest, schema["properties"], "2.0: the transport sets json/progress itself")
                    continue
                self.assertIn(dest, schema["properties"], f"{entry['name']}.{dest} lost in translation")
                self.assertEqual(schema["properties"][dest]["type"], prop["type"])
                for key in ("enum", "default"):
                    if key in prop:
                        self.assertEqual(schema["properties"][dest][key], prop[key])
                self.assertNotIn("cli", schema["properties"][dest])
            if spec["input_schema"]["required"] or spec["input_schema"].get("mutually_exclusive"):
                self.assertEqual(schema["anyOf"][0], {"required": ["argv"]})
                self.assertEqual(schema["anyOf"][1].get("required", []), spec["input_schema"]["required"])
        # a group shows up as pairwise exclusion plus a required-one-of
        color = next(t for t in listed if t["name"] == "color")["inputSchema"]["anyOf"][1]
        self.assertIn({"not": {"required": ["to_sdr", "lut"]}}, color["allOf"])
        self.assertIn({"required": ["to_sdr"]}, color["anyOf"])
        # no hand-written schema or tool table is left in the transport
        src = (ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("TOOLS:", src)
        self.assertNotIn('"inputSchema": {"type"', src)

    def test_mcp_tools_list_is_deterministic(self):
        a = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]
        b = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]
        self.assertEqual(json.dumps(a), json.dumps(b), "tools/list must be byte-identical across processes")
        c1 = sh(sys.executable, SCRIPTS / "_contract.py", "--json", "--static").stdout
        c2 = sh(sys.executable, SCRIPTS / "_contract.py", "--json", "--static").stdout
        self.assertEqual(c1, c2, "contract --json --static must be byte-identical")

    def test_mcp_schema_drift_follows_the_scripts(self):
        """Add a public script, remove one, change a parser: MCP must follow without any edit to mcp/."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(SCRIPTS, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "mcp", root / "mcp", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(ROOT / "package.json", root / "package.json")
            (root / "scripts" / "cut.py").unlink()
            # a new public script without metadata is reported, not silently dropped or guessed
            (root / "scripts" / "zzztool.py").write_text("#!/usr/bin/env python3\nimport argparse\ndef main():\n    argparse.ArgumentParser().parse_args()\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
            err = self._rpc([{"jsonrpc": "2.0", "id": 0, "method": "tools/list"}], root=root, full=True)[0]
            self.assertIn("no TOOL_META entry", err["error"]["message"])
            contract_py = (root / "scripts" / "_contract.py").read_text(encoding="utf-8")
            contract_py = contract_py.replace('TOOL_META: Dict[str, Dict[str, Any]] = {', 'TOOL_META: Dict[str, Dict[str, Any]] = {\n    "zzztool": dict(role="analysis", inputs=["x"], outputs=["y"], required=["ffprobe"], optional=[], video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=False, idempotency="bit_exact", deterministic=True),', 1)
            (root / "scripts" / "_contract.py").write_text(contract_py, encoding="utf-8")
            (root / "scripts" / "zzztool.py").write_text(
                '#!/usr/bin/env python3\n"""Drift probe tool."""\nimport argparse, sys, os\n'
                'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nfrom _common import add_common, apply_common, emit\n'
                'def main():\n    ap = argparse.ArgumentParser(description=__doc__)\n    ap.add_argument("input")\n'
                '    ap.add_argument("--knob", type=int, default=3, choices=[1, 2, 3], help="a knob")\n    add_common(ap)\n'
                '    args = ap.parse_args()\n    apply_common(args)\n    emit(None, knob=args.knob)\n    return 0\n'
                'if __name__ == "__main__":\n    sys.exit(main())\n', encoding="utf-8")
            fit = (root / "scripts" / "fit.py").read_text(encoding="utf-8")
            fit = fit.replace('    add_common(ap)', '    ap.add_argument("--drift-flag", action="store_true", help="added for the drift test")\n    add_common(ap)', 1)
            (root / "scripts" / "fit.py").write_text(fit, encoding="utf-8")
            tools = {t["name"]: t for t in self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], root=root, full=True)[0]["result"]["tools"]}
            self.assertNotIn("cut", tools, "removed script still exposed")
            self.assertIn("zzztool", tools, "new public script not exposed")
            self.assertEqual(tools["zzztool"]["inputSchema"]["properties"]["knob"], {"type": "integer", "description": "a knob", "enum": [1, 2, 3], "default": 3})
            self.assertIn("drift_flag", tools["fit"]["inputSchema"]["properties"], "parser change not reflected")
            self.assertEqual(list(tools), sorted(tools), "order stays sorted after changes")
            # the same drift, seen through the default core-12 view: zzztool never joins it (it
            # isn't in MCP_CORE_TOOLS), the removed "cut" stays gone, and a core tool's parser
            # change ("fit") still reaches it -- both views are derived from the same live scripts.
            core = {t["name"]: t for t in self._rpc([{"jsonrpc": "2.0", "id": 4, "method": "tools/list"}], root=root)[0]["result"]["tools"]}
            self.assertNotIn("cut", core, "removed script still exposed in the core-12 view")
            self.assertNotIn("zzztool", core, "a non-core new script must not appear in the default view")
            self.assertIn("drift_flag", core["fit"]["inputSchema"]["properties"], "parser change not reflected in the core-12 view")
            self.assertEqual(set(core) - {"cut"}, set(_contract.MCP_CORE_TOOLS) - {"cut"}, "core-12 view is exactly MCP_CORE_TOOLS minus the removed script")
            # the temporary tool also runs through the derived mapping (tools/call reaches it even
            # though it is outside the default tools/list view)
            call = self._rpc([{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "zzztool", "arguments": {"input": "x", "knob": 2}}}], root=root)[0]
            self.assertEqual(call["result"]["structuredContent"]["knob"], 2)
            unknown = self._rpc([{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "_contract", "arguments": {}}}], root=root)[0]
            self.assertTrue(unknown["result"]["isError"], "internal scripts are not callable")

    def test_mcp_server_error_paths_raw_argv_and_call_helper(self):
        """The stdio loop and tools/call were only tested on the happy path (#147). Pinned here:
        a non-JSON line, a JSON scalar, an id-less notification and a params-that-is-not-an-object
        request never kill the server; an unknown method is -32601 and any other handler error is
        -32000; a tool that exits non-zero comes back as isError with the stderr tail, never as a
        transport error; the raw `argv` form appends --json only for tools that need it (probe and
        look are exempt) and never after --help; and the `--call` debugging helper prints the same
        result object."""
        proc = subprocess.run([sys.executable, str(ROOT / "mcp" / "server.py")],
                              input="not json at all\n42\n[1, 2]\n"
                                    + json.dumps({"jsonrpc": "2.0", "method": "ping"}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "nope"}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": "x"}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                  "params": {"name": "cut", "arguments": {"input": str(self.out("missing.mp4")), "start": "0", "end": "1", "output": str(self.out("never.mp4"))}}}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                                  "params": {"name": "probe", "arguments": {"argv": [str(self.wav)]}}}) + "\n"
                                    + json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                                  "params": {"name": "silence", "arguments": {"argv": [str(self.src), "--list"]}}}) + "\n",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(l) for l in proc.stdout.strip().splitlines()]
        # the line that is not JSON is answered with a JSON-RPC parse error (-32700, id null)
        # instead of being dropped; a JSON scalar and a notification still get no response
        parse_errors = [r for r in lines if r["id"] is None]
        self.assertEqual([r["error"]["code"] for r in parse_errors], [-32700], "a non-JSON line is answered with -32700")
        self.assertIn("parse error", parse_errors[0]["error"]["message"])
        resps = {r["id"]: r for r in lines if r["id"] is not None}
        self.assertEqual(sorted(resps), [1, 2, 3, 4, 5, 6], "scalars and notifications produce no response; nothing else is lost")
        self.assertEqual(resps[1]["result"], {})
        self.assertEqual(resps[2]["error"]["code"], -32601)
        self.assertEqual(resps[3]["error"]["code"], -32000)
        self.assertTrue(resps[4]["result"]["isError"])
        self.assertIn("cut failed (exit", resps[4]["result"]["content"][0]["text"])
        # the child's failure document rides along: kind/code are what an MCP caller keys on
        failed_doc = resps[4]["result"]["structuredContent"]
        self.assertEqual((failed_doc["status"], failed_doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("code", failed_doc["error"])
        self.assertEqual(resps[5]["result"]["structuredContent"]["audio"]["codec"], "pcm_s16le")
        self.assertIn("structuredContent", resps[6]["result"], "--json appended for a JSON tool in raw argv form")
        # the raw form appends --json exactly for the tools that need it to speak JSON
        self.assertEqual(mcp_server.build_argv("probe", {"argv": [str(self.wav)]}), [str(self.wav)])
        self.assertEqual(mcp_server.build_argv("silence", {"argv": [str(self.src), "--list"]}), [str(self.src), "--list", "--json"])
        self.assertEqual(mcp_server.build_argv("silence", {"argv": [str(self.src), "--help"]}), [str(self.src), "--help"])
        # --call NAME JSON prints the same object the RPC returns
        proc = sh(sys.executable, ROOT / "mcp" / "server.py", "--call", "probe", json.dumps({"inputs": [str(self.wav)]}))
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["structuredContent"]["audio"]["codec"], "pcm_s16le")
        proc = sh(sys.executable, ROOT / "mcp" / "server.py", "--call", "not_a_tool")
        self.assertTrue(json.loads(proc.stdout)["isError"])

    def test_mcp_round_trips_built_from_the_derived_schema(self):
        listed = {t["name"]: t["inputSchema"] for t in self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]["result"]["tools"]}
        project = self.out("mcp_project.json")
        project.write_text(json.dumps({"output": str(self.out("mcp_render.mp4")), "clips": [{"src": str(self.src), "in": 0, "out": 2}], "export": {"preset": "x"}}), encoding="utf-8")
        calls = {
            "probe": {"inputs": [str(self.wav)]},
            "cut": {"input": str(self.src), "start": "1", "end": "3", "output": str(self.out("mcp_cut.mp4"))},
            "silence": {"input": str(self.src), "list": True},
            "loudness": {"input": str(self.wav), "lufs": -16.0, "tp": -1.5, "output": str(self.out("mcp_loud.wav"))},
            "export": {"input": str(self.src), "preset": "x", "fast": True, "output": str(self.out("mcp_export.mp4"))},
            "render": {"project": str(project), "fast": True},
        }
        reqs = []
        for i, (name, args) in enumerate(calls.items(), start=10):
            schema = listed[name]
            for key, val in args.items():
                self.assertIn(key, schema["properties"], f"{name}: {key} not in the derived schema")
                jtype = schema["properties"][key]["type"]
                py = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}[jtype]
                self.assertIsInstance(val, py, f"{name}.{key}")
            for req in schema.get("anyOf", [{}, {}])[1].get("required", []):
                self.assertIn(req, args, f"{name}: required {req} missing")
            reqs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}})
        for name, resp in zip(calls, self._rpc(reqs)):
            self.assertNotIn("error", resp, name)
            self.assertFalse(resp["result"].get("isError"), f"{name}: {resp['result']['content'][0]['text'][:300]}")
            doc = resp["result"]["structuredContent"]
            if name == "probe":
                self.assertEqual(doc["audio"]["codec"], "pcm_s16le")
            else:
                self.assertEqual(doc["status"], "completed", name)
                if doc.get("output"):
                    self.assertTrue(Path(doc["output"]).exists(), name)

    def test_installer_payload_matches_contract(self):
        js = (ROOT / "bin" / "install.js").read_text(encoding="utf-8")
        payload = re.search(r"const PAYLOAD = \[(.*?)\];", js).group(1)
        self.assertIn("'scripts'", payload)
        self.assertIn("'mcp'", payload)
        self.assertIn("'package.json'", payload, "installed skill needs package.json for the skill version")
        files = json.loads((ROOT / "package.json").read_text())["files"]
        self.assertIn("scripts/", files)
        self.assertIn("mcp/", files)
        self.assertIn("bin/", files)
        # the npm entry point answers `contract --json` and `doctor`
        doc = json.loads(sh("node", ROOT / "bin" / "install.js", "contract", "--json", "--static").stdout)
        self.assertEqual([t["id"] for t in doc["tools"]], [t["id"] for t in self.contract["tools"]])
        self.assertEqual(sh("node", ROOT / "bin" / "install.js", "doctor", "--json").returncode, 0)

    def test_windows_store_python_stub_is_not_treated_as_an_interpreter(self):
        """The Microsoft Store python3 alias is a real executable: spawn succeeds (no ENOENT) and
        the process exits non-zero. install.js used to stop there. A probe that fails falls
        through to python, then py; a probe that succeeds does not, even when the script itself
        exits non-zero. Linux still tries python3 only."""
        probe = self.out("python_probe.js")
        probe.write_text(
            "const inst = require(process.argv[2]);\n"
            "function callsOf(fn) { return fn.calls.map(c => c[0] + ' ' + c[1]).join('|'); }\n"
            "function stub(cmd, args) {\n"
            "  stub.calls.push([cmd, args[0]]);\n"
            "  if (cmd === 'python3') return { status: 9009, error: null };\n"
            "  if (cmd === 'python' && args[0] === '-c') return { status: 0, error: null };\n"
            "  if (cmd === 'python') return { status: 7, error: null };\n"
            "  return { error: Object.assign(new Error('spawn ENOENT'), { code: 'ENOENT' }), status: null };\n"
            "}\n"
            "stub.calls = [];\n"
            "const fallen = inst.runWithPython(['doctor'], 'win32', stub);\n"
            "if (fallen.missing || fallen.status !== 7) process.exit(2);\n"
            "if (callsOf(stub) !== 'python3 -c|python -c|python doctor') process.exit(3);\n"
            "function kept(cmd, args) {\n"
            "  kept.calls.push([cmd, args[0]]);\n"
            "  if (args[0] === '-c') return { status: 0, error: null };\n"
            "  return { status: 2, error: null };\n"
            "}\n"
            "kept.calls = [];\n"
            "const scriptFailed = inst.runWithPython(['doctor'], 'win32', kept);\n"
            "if (scriptFailed.missing || scriptFailed.status !== 2) process.exit(4);\n"
            "if (kept.calls.some(c => c[0] !== 'python3')) process.exit(5);\n"
            "function missing(cmd, args) {\n"
            "  missing.calls.push(cmd);\n"
            "  return { error: Object.assign(new Error('spawn ENOENT'), { code: 'ENOENT' }), status: null };\n"
            "}\n"
            "missing.calls = [];\n"
            "const none = inst.runWithPython(['doctor'], 'linux', missing);\n"
            "if (!none.missing || missing.calls.join() !== 'python3') process.exit(6);\n"
            "if (inst.pythonCandidates('linux').join() !== 'python3') process.exit(7);\n"
            "if (inst.pythonCandidates('win32').join() !== 'python3,python,py') process.exit(8);\n",
            encoding="utf-8")
        proc = subprocess.run(["node", str(probe), str(ROOT / "bin" / "install.js")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_python_3_9_is_deprecated_on_every_surface(self):
        """2.10.9 deprecates Python 3.9 per docs/contract.md's policy: an entry in `deprecated`
        (removed in 3.0.0), the floor unchanged (3.9 still runs), and one identical warning line from
        doctor (Python) and the npx installer (Node)."""
        entry = [e for e in self.contract["deprecated"] if "Python 3.9" in e["what"]]
        self.assertEqual(len(entry), 1)
        self.assertEqual((entry[0]["since"], entry[0]["removed_in"], entry[0]["where"]), ("2.10.9", "3.0.0", "behaviour"))
        self.assertIn("3.10", entry[0]["replacement"])
        self.assertTrue(self.contract["requirements"]["python"].startswith(">=3.9 "), "the hard floor stays 3.9 until 3.0")
        self.assertIn("deprecated", self.contract["requirements"]["python"])
        self.assertEqual(_contract.python_deprecation((3, 9, 18)), _contract.PY39_DEPRECATION)
        for vi in ((3, 10, 0), (3, 13, 1), (3, 8, 10)):
            self.assertIsNone(_contract.python_deprecation(vi), vi)
        line = _contract.PY39_DEPRECATION
        self.assertTrue(line.startswith("warning: ") and "\n" not in line)
        for needle in ("3.0", "3.10+"):
            self.assertIn(needle, line)
        js = (ROOT / "bin" / "install.js").read_text(encoding="utf-8")
        self.assertIn(f"const PY39_DEPRECATION = '{line}';", js, "install.js must print the same line as doctor")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('python: ["3.9"]', ci, "deprecating 3.9 does not drop it from CI before 3.0")
        for doc in ("README.md", "docs/contract.md", "CONTRIBUTING.md", "SKILL.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            self.assertRegex(text, r"3\.9[^\n]*deprecated|deprecated[^\n]*3\.9", doc)

    def test_ffmpeg_5_is_deprecated_on_every_surface(self):
        """2.14.0 deprecates FFmpeg 5.x like Python 3.9: an entry in `deprecated` (removed in
        3.0.0), the floor unchanged (5.0 still runs, CI keeps its 5.1.1 job), and one identical
        warning line from doctor (Python) and the npx installer (Node), only for a 5.x release."""
        entry = [e for e in self.contract["deprecated"] if "FFmpeg 5.x" in e["what"]]
        self.assertEqual(len(entry), 1)
        self.assertEqual((entry[0]["since"], entry[0]["removed_in"], entry[0]["where"]), ("2.14.0", "3.0.0", "behaviour"))
        self.assertIn("6.1", entry[0]["replacement"])
        self.assertTrue(self.contract["requirements"]["ffmpeg"].startswith(">=5.0 "), "the hard floor stays 5.0 until 3.0")
        self.assertIn("deprecated", self.contract["requirements"]["ffmpeg"])
        line = _contract.FFMPEG5_DEPRECATION
        self.assertTrue(line.startswith("warning: ") and "\n" not in line)
        for needle in ("2.14.0", "3.0.0", "6.1+"):
            self.assertIn(needle, line)
        for version in ("5.1.1-static", "5.0", "n5.1.6", "5.1.6-0+deb12u1"):
            self.assertEqual(_contract.ffmpeg_deprecation(version), line, version)
        for version in ("6.1.1-3ubuntu5", "8.0.1", "4.4.2", "N-12345-gabcdef", "unknown", None):
            self.assertIsNone(_contract.ffmpeg_deprecation(version), version)
        js = (ROOT / "bin" / "install.js").read_text(encoding="utf-8")
        self.assertIn(f"const FFMPEG5_DEPRECATION = '{line}';", js, "install.js must print the same line as doctor")
        probe = self.out("ffmpeg_dep_probe.js")
        probe.write_text(
            "const inst = require(process.argv[2]);\n"
            "const cases = [['ffmpeg version 5.1.1-static https://johnvansickle.com/ffmpeg/  Copyright', true],\n"
            "  ['ffmpeg version n5.0 Copyright (c) 2000-2022', true], ['ffmpeg version 6.1.1-3ubuntu5 Copyright', false],\n"
            "  ['ffmpeg version N-12345-gabcdef Copyright', false], ['', false], [undefined, false]];\n"
            "for (const [l, want] of cases) if ((inst.ffmpegDeprecation(l) === inst.FFMPEG5_DEPRECATION) !== want) process.exit(2);\n",
            encoding="utf-8")
        proc = subprocess.run(["node", str(probe), str(ROOT / "bin" / "install.js")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("ffmpeg-5.1.1", ci, "deprecating 5.x does not drop its CI job before 3.0")
        for doc in ("README.md", "docs/contract.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            self.assertRegex(text, r"FFmpeg 5\.x[^\n]*deprecated", doc)

    def test_doctor_prints_the_ffmpeg_5_warning_on_stderr_only(self):
        import contextlib
        import io
        from unittest import mock
        for version, expect in (("5.1.1-static", True), ("6.1.1-3ubuntu5", False), (None, False)):
            fake = {"ffmpeg_security": {"warnings": []}, "ok": True, "missing": [], "ffmpeg": version}
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(_contract, "doctor", return_value=fake), \
                    mock.patch.object(sys, "argv", ["_contract.py", "doctor", "--json"]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = _contract.main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue()), fake)
            self.assertEqual(_contract.FFMPEG5_DEPRECATION in err.getvalue(), expect, version)

    def test_doctor_prints_the_python_3_9_warning_on_stderr_only(self):
        """Deprecation warnings go to stderr (policy step 1), never into stdout: `doctor --json`
        stays one JSON document, with no key that exists only on 3.9."""
        import contextlib
        import io
        from unittest import mock
        fake = {"ffmpeg_security": {"warnings": []}, "ok": True, "missing": []}
        for vi, expect in (((3, 9, 18, "final", 0), True), ((3, 12, 1, "final", 0), False)):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(_contract, "doctor", return_value=fake), \
                    mock.patch.object(sys, "argv", ["_contract.py", "doctor", "--json"]), \
                    mock.patch.object(sys, "version_info", vi), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = _contract.main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue()), fake)
            self.assertEqual(_contract.PY39_DEPRECATION in err.getvalue(), expect, vi)

    def test_installer_warns_once_on_python_3_9(self):
        """bin/install.js reads major.minor from its interpreter probe and prints the deprecation
        line after an install on 3.9; nothing on 3.10+, nor when the probe printed no version."""
        probe = self.out("python_dep_probe.js")
        probe.write_text(
            "const inst = require(process.argv[2]);\n"
            "function stubFor(ver) { return (cmd, args) => (args[0] === '-c' ? { status: 0, error: null, stdout: ver } : { status: 0 }); }\n"
            "const seen = [];\n"
            "const warn = (l) => seen.push(l);\n"
            "if (inst.findPython('linux', stubFor('3.9')).version !== '3.9') process.exit(2);\n"
            "if (inst.warnDeprecatedPython('linux', stubFor('3.9'), warn) !== inst.PY39_DEPRECATION) process.exit(3);\n"
            "if (seen.length !== 1 || !seen[0].includes(inst.PY39_DEPRECATION)) process.exit(4);\n"
            "if (inst.warnDeprecatedPython('linux', stubFor('3.10'), warn) !== null) process.exit(5);\n"
            "if (inst.warnDeprecatedPython('linux', stubFor(undefined), warn) !== null) process.exit(6);\n"
            "if (inst.warnDeprecatedPython('linux', () => ({ error: new Error('ENOENT'), status: null }), warn) !== null) process.exit(7);\n"
            "if (seen.length !== 1) process.exit(8);\n"
            "const ran = inst.runWithPython(['doctor'], 'linux', stubFor('3.9'));\n"
            "if (ran.missing || ran.status !== 0) process.exit(9);\n",
            encoding="utf-8")
        proc = subprocess.run(["node", str(probe), str(ROOT / "bin" / "install.js")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        # the real probe prints this interpreter's major.minor
        found = subprocess.run(["node", "-e", "console.log(JSON.stringify(require(process.argv[1]).findPython(process.platform)))",
                                str(ROOT / "bin" / "install.js")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if found.returncode == 0 and found.stdout.strip() and "missing" not in found.stdout:
            self.assertRegex(json.loads(found.stdout)["version"], r"^3\.\d+$")

    def test_npm_package_omits_the_maintainer_diary(self):
        """docs/design-decisions.md: references/process-pitfalls.md stays out of the npm package.

        release_check.sh is the live `npm pack`. This is the check CI actually runs, and it
        does not spawn npm: Windows Python cannot CreateProcess `npm` (the runner ships
        npm.cmd), and the debian-trixie job installs nodejs without the npm package. When
        `files` is set, `npm pack` includes that allow-list and nothing else, so a directory
        entry or a glob under references/ is what would pull the diary in.
        """
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        files = pkg["files"]
        self.assertIsInstance(files, list)
        shipped = {
            "references/scripts.md",
            "references/devices.md",
            "references/ci-platform-pitfalls.md",
            "references/gotchas.md",
            "docs/contract.md",
        }
        self.assertTrue(shipped <= set(files))
        for entry in files:
            norm = entry.replace("\\", "/").strip()
            self.assertNotIn("process-pitfalls", norm, entry)
            base = norm.rstrip("/")
            self.assertNotEqual(base, "references", entry)
            if base.startswith("references/") and any(ch in base for ch in "*?["):
                self.fail(f"{entry} would pack every file under references/, including the diary")
        script = (ROOT / "tests" / "release_check.sh").read_text(encoding="utf-8")
        self.assertIn("package/references/process-pitfalls.md", script)
        self.assertGreaterEqual(script.count("FFMPEG_SKILL_MCP_FULL"), 2)

    def test_installer_agent_targets_are_the_directories_those_agents_actually_read(self):
        """`--codex` installed into ~/.codex/skills for weeks -- a location Codex's own docs never
        list (they name $HOME/.agents/skills, .agents/skills up the repo tree, /etc/codex/skills).
        Nothing pinned the target dirs, so the wrong guess shipped in 23 releases. Pin each
        agent flag to the directory that agent documents, and make `--uninstall --codex` also
        clear the old, wrong location so an upgrade doesn't leave a stale orphan copy behind."""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, USERPROFILE=tmp)
            home = Path(tmp)
            legacy_codex = home / ".codex" / "skills" / "ffmpeg-skill"
            legacy_codex.mkdir(parents=True)
            (legacy_codex / "SKILL.md").write_text("stale copy from an older installer", encoding="utf-8")
            sh("node", ROOT / "bin" / "install.js", "--codex", "--cursor", env=env)
            self.assertTrue((home / ".agents" / "skills" / "ffmpeg-skill" / "SKILL.md").is_file(),
                            "--codex must install where Codex reads user-level skills: ~/.agents/skills")
            self.assertTrue((home / ".cursor" / "skills" / "ffmpeg-skill" / "SKILL.md").is_file())
            self.assertFalse((home / ".claude").exists(), "an explicit agent flag must not also install the default target")
            sh("node", ROOT / "bin" / "install.js", "--codex", "--uninstall", env=env)
            self.assertFalse((home / ".agents" / "skills" / "ffmpeg-skill").exists())
            self.assertFalse(legacy_codex.exists(), "--uninstall --codex must also remove the pre-fix ~/.codex/skills copy")
            self.assertTrue((home / ".cursor" / "skills" / "ffmpeg-skill").exists(), "uninstall is scoped to the selected targets")

    def test_missing_ffmpeg_skips_locally_but_fails_in_ci(self):
        """A job whose ffmpeg install silently failed once reported green: 14 tests ran, 15 were
        skipped with 'ffmpeg not on PATH', job OK. GitHub sets CI=true on every runner, so the
        same condition there must be a failure -- while a contributor's laptop without ffmpeg
        still gets a plain skip, not a red suite."""
        from unittest import mock
        with mock.patch("shutil.which", return_value=None):
            with mock.patch.dict(os.environ, {"CI": "true"}):
                with self.assertRaises(AssertionError):
                    require_ffmpeg_or_skip("ffmpeg")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CI", None)
                with self.assertRaises(unittest.SkipTest):
                    require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with mock.patch.dict(os.environ, {"CI": "true"}):
                require_ffmpeg_or_skip("ffmpeg")  # present: no skip, no failure

    def test_contract_from_installed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Node's os.homedir() reads HOME on POSIX but USERPROFILE on Windows (falling back to
            # HOMEDRIVE+HOMEPATH); HOME alone silently installs into the real runner's home dir on
            # Windows instead of this redirected tmp one, and the file this test then reaches for
            # is not there. Set both so install.js is redirected on every OS.
            env = dict(os.environ, HOME=tmp, USERPROFILE=tmp)
            sh("node", ROOT / "bin" / "install.js", env=env)
            installed = Path(tmp) / ".claude" / "skills" / "ffmpeg-skill"
            doc = json.loads(sh(sys.executable, installed / "scripts" / "_contract.py", "--json", "--static").stdout)
            self.assertEqual(doc["skill"]["version"], self.contract["skill"]["version"])
            self.assertEqual([t["id"] for t in doc["tools"]], [t["id"] for t in self.contract["tools"]])
            for t in doc["tools"]:
                self.assertTrue((installed / t["executable"]).is_file())

    def test_installer_upgrade_survives_an_interruption_mid_copy(self):
        """install.js used to `rmSync(t.dir)` then `mkdirSync` + copy straight into the now-empty
        target -- a process killed partway through that copy (Ctrl-C, disk full, a permission
        error) left the target either empty or half-populated, destroying a working previous
        install for nothing worse than an interrupted upgrade. Verify a copy that dies partway
        through (simulated: a marker item throws right after it's copied) leaves an existing
        install's own file untouched, instead of gone."""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, USERPROFILE=tmp)
            installed = Path(tmp) / ".claude" / "skills" / "ffmpeg-skill"
            installed.mkdir(parents=True)
            marker = installed / "PREVIOUS_INSTALL_MARKER.txt"
            marker.write_text("preserve me", encoding="utf-8")

            js = (ROOT / "bin" / "install.js").read_text(encoding="utf-8")
            crashing_js = js.replace(
                "copyRecursive(src, path.join(tmpDir, item));",
                "copyRecursive(src, path.join(tmpDir, item)); "
                "if (item === 'SKILL.md') throw new Error('SIMULATED_CRASH_MID_COPY');",
                1,
            )
            self.assertNotEqual(crashing_js, js, "expected to find and patch the per-item copy call")
            crashing_installer = Path(tmp) / "install_crash_test.js"
            crashing_installer.write_text(crashing_js, encoding="utf-8")

            proc = sh("node", crashing_installer, "--claude", env=env, check=False)
            self.assertNotEqual(proc.returncode, 0, "the simulated crash should make the installer report failure")
            self.assertTrue(marker.exists(), "an install interrupted mid-copy must not destroy the previous install")
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve me")

    # ------------------------------------------------------------------ integration: claims hold at run time
    @unittest.skipIf(platform.system() == "Windows", "fake ffmpeg is a #!/bin/sh script on a POSIX-only PATH shim; not portable to Windows. The claim itself (run() never invokes ffmpeg under --dry-run) is still exercised on Windows by every --dry-run case in tests/test_all.py, just without a shim proving no *other* ffmpeg-shaped binary would have run.")
    def test_every_1_17_flag_is_reachable_off(self):
        """Each new 1.17 flag defaults to 1.16's behaviour, or is switched off by one flag.

        The command lines below are the ones `main` builds, and they must still be what these
        runs plan: `--fit-size off`, `--snap none` (the default), no `--filler`, `--jobs 1` (the
        default) and no `--cache` are the five ways back.
        """
        outdir = self.work / "reach"
        outdir.mkdir(exist_ok=True)

        def plan(name, *args):
            proc = tool(name, *args, "--dry-run", "--json", check=False)
            self.assertEqual(proc.returncode, 0, f"{name}:\n{proc.stderr}")
            return json.loads(proc.stdout)

        # caption: --fit-size off plans exactly what no flag at all planned before the feature
        off = plan("caption", self.src, "--text", self.cues, "--fit-size", "off",
                   "-o", outdir / "c_off.mp4")
        self.assertEqual(off["caption"]["size_used"], off["caption"]["size_requested"])
        self.assertEqual(off["caption"]["shrunk"], 0)
        explicit = plan("caption", self.src, "--text", self.cues, "--size", "24",
                        "-o", outdir / "c_size.mp4")
        self.assertEqual(explicit["caption"]["size_used"], 24)

        # cut: --snap defaults to none, and no snap key appears
        self.assertIsNone(plan("cut", self.src, "--start", "1", "--end", "3",
                               "-o", outdir / "cut.mp4").get("snap"))

        # silence: no --filler, no filler key, removed_seconds keeps its lone meaning
        sil = plan("silence", self.src, "-o", outdir / "sil.mp4")
        self.assertNotIn("filler", sil)
        self.assertNotIn("removed_seconds_total", sil)

        # render: no --cache, no cache key
        proj = outdir / "p.json"
        proj.write_text(json.dumps({"output": str(outdir / "r.mp4"),
                                    "clips": [{"src": str(self.src), "in": 0, "out": 2}]}),
                        encoding="utf-8")
        rendered = plan("render", proj)
        self.assertIsNone(rendered.get("cache"))
        self.assertIsNone(rendered.get("snap"))
        self.assertFalse(any("--snap" in c or "--cache" in c for c in rendered["commands"]))

    def test_dry_run_never_runs_ffmpeg_and_writes_nothing(self):
        """A fake ffmpeg first on PATH records every invocation; ffprobe stays real."""
        shim = self.work / "shim"
        shim.mkdir(exist_ok=True)
        marker = self.work / "ffmpeg_was_called"
        (shim / "ffmpeg").write_text(f"#!/bin/sh\necho called >> {marker}\nexit 1\n")
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        outdir = self.work / "dry"
        outdir.mkdir(exist_ok=True)
        cases = {
            "cut": [self.src, "--start", "1", "--end", "3", "-o", outdir / "cut.mp4"],
            "fit": [self.src, "--duration", "3", "-o", outdir / "fit.mp4"],
            "caption": [self.src, "--text", self.cues, "-o", outdir / "cap.mp4"],
            "overlay": [self.src, "--image", self.logo, "-o", outdir / "ov.mp4"],
            "graphics": [self.src, "--template", "title", "--title", "T", "-o", outdir / "gfx.mp4"],
            "sync": [self.src, self.mic, "--replace-audio", "-o", outdir / "sync.mp4"],
            "multicam": [self.src, self.camb, "--switch", "0-2:0,2-4:1", "-o", outdir / "mc.mp4"],
            "audio": [self.src, "--voice", "-o", outdir / "au.mp4"],
            "loudness": [self.src, "-o", outdir / "ld.mp4"],
            "silence": [self.src, "-o", outdir / "sil.mp4"],
            "join": [self.src, self.camb, "-o", outdir / "join.mp4"],
            "color": [self.hdr, "--to-sdr", "-o", outdir / "col.mp4"],
            # review 5: --correct measured with two real signalstats passes and --transcribe ran the engine
            "color#correct": [self.src, "--correct", "--exposure", "0.2", "-o", outdir / "colc.mp4"],
            "caption#transcribe": [self.src, "--transcribe", "-o", outdir / "capt.mp4"],
            "export": [self.src, "--preset", "x", "-o", outdir / "exp.mp4"],
            "scenes": [self.src, "--sheet", outdir / "sc.png", "--edl", outdir / "sc.txt"],
            "look": [self.src, "-o", outdir / "look.png"],
            "report": ["--after", self.src, "-o", outdir / "rep.html"],
            "cropdetect": [self.src, "--seconds", "1", "--samples", "1"],
        }
        for name, args in cases.items():
            name = name.split("#")[0]
            spec = self.tools[name]
            self.assertTrue(spec["supports_dry_run"], name)
            strict = spec["dry_run"]["ffmpeg_execution"] == "none"
            # tools whose measurement needs ffmpeg (sync, multicam, scenes, report) run with the real ffmpeg
            proc = tool(name, *args, "--dry-run", "--json", env=env if strict else None, check=False)
            self.assertEqual(proc.returncode, 0, f"{name} --dry-run failed:\n{proc.stderr}")
            doc = json.loads(proc.stdout)
            self.assertTrue(doc["dry_run"], name)
            self.assertNotIn("probe", doc, f"{name}: dry-run must not claim an output probe")
            self.assertNotIn("\nwrote ", proc.stderr, name)
            self.assertEqual(sorted(p.name for p in outdir.iterdir()), [], f"{name} --dry-run wrote files")
            if strict:
                self.assertFalse(marker.exists(), f"{name} --dry-run invoked ffmpeg")
        self.assertEqual({n for n, s in self.tools.items() if s["dry_run"]["ffmpeg_execution"] == "analysis_only"},
                         {"sync", "multicam", "scenes", "report", "cropdetect", "silence", "loudness", "check", "stabilize", "overlay"})
        # the read-only tools keep working under --dry-run (ffprobe still runs)
        self.assertEqual(tool("probe", self.src, "--dry-run", env=env).returncode, 0)
        self.assertEqual(tool("check", self.src, "--platform", "x", "--no-loudness", "--dry-run", env=env).returncode, 0)

    def test_every_reencoding_tool_plans_the_bt601_conversion(self):
        """Through 2.10.0 a BT.601-matrix source came out of every SDR re-encode tagged BT.709 with its
        pixels untouched. The conversion rides on the shared encoder line and run() folds it into each
        tool's own graph, so this plans every tool that re-encodes one or several sources: on a
        BT.601 source each input read from that file is converted once (cut's segment join opens it
        once per segment), a mixed join/multicam/broll/overlay --video converts only the BT.601
        input, and copies, the prores master and an untagged source plan no conversion at all."""
        s601 = OUT / "c_source601.mp4"
        if not s601.exists():
            ffmpeg("-i", self.src, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x264-params",
                   "colorprim=smpte170m:transfer=smpte170m:colormatrix=smpte170m", "-c:a", "copy", s601)
        self.assertEqual(json.loads(tool("probe", s601, "--json").stdout)["video"]["color_space"], "smpte170m")
        conv = "colorspace=ispace=smpte170m:"
        cases = [  # (tool, args after the input, conversions on a BT.601 input)
            ("export", ["--preset", "reels"], 1), ("export", ["--preset", "prores"], 0), ("export", ["--preset", "copy"], 0),
            ("export", ["--preset", "x", "--pad-fill", "blur"], 1),
            ("fit", ["--width", "320", "--height", "320"], 1), ("cut", ["--start", "1", "--end", "3", "--accurate"], 1),
            ("cut", ["--segments", "0.5-1.5,2-3", "--accurate"], 2), ("cut", ["--start", "1", "--end", "3"], 0),
            ("crop", ["--x", "0", "--y", "0", "--width", "100", "--height", "100"], 1), ("deinterlace", [], 1), ("denoise", [], 1),
            ("freeze", ["--at", "1", "--hold", "1"], 1), ("graphics", ["--template", "title", "--title", "T"], 1),
            ("loop", ["--times", "2"], 1), ("loop", ["--times", "2", "--boomerang"], 1),
            ("overlay", ["--image", self.logo], 1), ("overlay", ["--text", "hi"], 1), ("overlay", ["--video", self.camb], 1),
            ("pad", ["--start", "1"], 1), ("proxy", [], 1), ("redact", ["--x", "0", "--y", "0", "--width", "100", "--height", "100"], 1),
            ("reverse", [], 1), ("speedramp", ["--segment", "0-3:2", "--segment", "3-6:1"], 1), ("straighten", ["--degrees", "2"], 1),
            ("caption", ["--text", self.cues], 1), ("color", ["--correct", "--exposure", "0.2"], 1),
            ("join", [self.camb], 1), ("broll", ["--insert", self.camb, "--at", "1", "--duration", "1"], 1),
            ("multicam", [self.camb, "--switch", "0-2:0,2-4:1"], 2),  # camera 0 also fills 4-6 s: one chain per window
        ]
        for n, (name, args, want) in enumerate(cases):
            for src, expected in ((s601, want), (self.src, 0)):
                with self.subTest(tool=name, args=args, source=src.name):
                    ext = ".mov" if "prores" in args else ".mp4"
                    proc = tool(name, src, *args, "-o", self.out(f"bt601_{n}{ext}"), "--dry-run", "--json", check=False)
                    self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
                    commands = " ".join(json.loads(proc.stdout)["commands"])
                    self.assertEqual(commands.count(conv), expected, commands)
                    if src == self.src:
                        # the source is not converted (overlay --image converts its logo, and the title
                        # its brand-yellow accent line, and each labels the untagged main BT.709 for it
                        # to meet: test_still_and_rgb_tools_plan..., test_drawn_colours_plan...)
                        self.assertNotIn("colorspace=ispace", commands)
                        self.assertEqual(commands.count("setparams=colorspace=bt709"),
                                         1 if "--image" in args or name == "graphics" else 0, commands)
        # the other way round: the BT.601 file as the second input is converted in its own chain
        for name, args in (("join", [self.camb, s601]), ("broll", [self.camb, "--insert", s601, "--at", "1", "--duration", "1"]),
                           ("overlay", [self.camb, "--video", s601])):
            with self.subTest(tool=name, second=True):
                commands = " ".join(json.loads(tool(name, *args, "-o", self.out(f"bt601_2nd_{name}.mp4"), "--dry-run", "--json").stdout)["commands"])
                self.assertEqual(commands.count(conv), 1, commands)

    def test_still_and_rgb_tools_plan_the_bt709_conversion(self):
        """#332's follow-ups, planned: an RGB source (a PNG still, a PNG sequence, a qtrle clip) and a
        JPEG are converted to BT.709 by every tool that re-encodes them; a still composited over the
        video (overlay --image) is converted at the end of its own chain, and an untagged main labelled
        BT.709 for it; grid.py converts each cell by its own tags and labels an untagged cell only
        beside a converted one. A grid of untagged/BT.709 clips plans exactly what it did."""
        s601 = OUT / "c_source601.mp4"
        if not s601.exists():
            ffmpeg("-i", self.src, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x264-params",
                   "colorprim=smpte170m:transfer=smpte170m:colormatrix=smpte170m", "-c:a", "copy", s601)
        s709 = OUT / "c_source709.mp4"
        if not s709.exists():
            ffmpeg("-i", self.src, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x264-params",
                   "colorprim=bt709:transfer=bt709:colormatrix=bt709", "-c:a", "copy", s709)
        png, jpg, qtrle, seq = OUT / "c_still.png", OUT / "c_still.jpg", OUT / "c_rgb.mov", OUT / "c_seq"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", "-pix_fmt", "rgb24", png)
        ffmpeg("-i", png, "-pix_fmt", "yuvj420p", jpg)
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10", "-t", "1", "-c:v", "qtrle", "-pix_fmt", "rgb24", qtrle)
        seq.mkdir(exist_ok=True)
        for i in range(3):
            shutil.copyfile(png, seq / f"f_{i:04d}.png")
        rgb, bt601 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p", "colorspace=ispace=bt470bg:"
        still = "scale=out_color_matrix=bt709:out_range=tv,format=yuva420p"
        label = "setparams=colorspace=bt709:range=tv"
        cases = [  # (tool, args, the strings the plan holds, and how many times)
            ("insert", [png, "--duration", "1"], {rgb: 1, bt601: 0, label: 0}),
            ("insert", [jpg, "--duration", "1"], {rgb: 0, bt601: 1, label: 0}),
            ("sequence", ["--dir", seq, "--pattern", "f_%04d.png"], {rgb: 1, label: 0}),
            ("fit", [qtrle, "--width", "320", "--height", "180"], {rgb: 1, label: 0}),
            ("export", [qtrle, "--preset", "x"], {rgb: 1, label: 0}),
            ("overlay", [self.src, "--image", png], {still: 1, label: 1, rgb: 0}),
            ("overlay", [self.src, "--image", jpg], {still: 1, label: 1, bt601: 0}),
            ("overlay", [s709, "--image", self.logo], {still: 1, label: 0}),
            ("overlay", [s601, "--image", self.logo], {still: 1, label: 0, "colorspace=ispace=smpte170m:": 1}),
            ("overlay", [self.src, "--image", self.logo, "--codec", "prores"], {still: 0, label: 0}),
            ("waveform", [self.src, "--image", png], {"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p": 1}),
            ("grid", [self.src, s601, "--cols", "2", "--rows", "1"], {"colorspace=ispace=smpte170m:": 1, label: 1}),
            ("grid", [s601, self.src, png, s709, "--cols", "2", "--rows", "2"], {"colorspace=ispace=smpte170m:": 1, label: 1, rgb: 1}),
            ("grid", [self.src, s709, "--cols", "2", "--rows", "1"], {"colorspace=": 0, "out_color_matrix": 0, "setparams": 0}),
        ]
        for n, (name, args, want) in enumerate(cases):
            with self.subTest(tool=name, args=[Path(str(a)).name for a in args]):
                ext = ".mov" if "prores" in args else ".mp4"
                proc = tool(name, *args, "-o", self.out(f"rgbstill_{n}{ext}"), "--dry-run", "--json", check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
                commands = " ".join(json.loads(proc.stdout)["commands"])
                for s, count in want.items():
                    self.assertEqual(commands.count(s), count, f"{s!r} in {commands}")

    def test_drawn_colours_are_drawn_in_bt709(self):
        """A colour the skill draws (pad, tpad, rotate fill, drawtext, libass) was turned into YUV by
        the drawing filter itself: with BT.601 on 5.1-7.0 whatever the picture is tagged, with the
        link's colourspace from 7.1 on ("unknown" = BT.601). drawn_chain() labels an untagged picture
        BT.709 on 7.1+ (tags only) and draws in RGB on an older build, keeping the untouched pixels
        (rgb_island). A grey -- the same 8-bit YUV under either matrix -- a prores line and an HDR
        line change nothing. Pinned with the version forced."""
        n = _common.is_neutral_color
        for c in ("black", "white", "gray", "Silver", "0x808080", "#FFFFFF", "000000", "black@0.5", "0x101418"):
            self.assertTrue(n(c), c)
        for c in ("red", "lime", "random", "0xFF0000", "#2878C8", "FFD200", "0x00FF00@0.3", "0x1E6F8E", "nonsense"):
            self.assertFalse(n(c), c)

        def meta(**v):
            return {"file": "src", "video": dict({"bt2020_or_hdr": False, "pix_fmt": "yuv420p"}, **v)}
        pad, black = "pad=8:8:0:0:color=red", "pad=8:8:0:0:color=black"
        un, t709, rgb = meta(), meta(color_space="bt709"), meta(pix_fmt="rgb24", color_space="gbr")
        full, hdr = meta(pix_fmt="yuvj420p", color_range="pc"), meta(pix_fmt="yuv420p10le", bt2020_or_hdr=True)
        dc = _common.drawn_chain
        saved = (_common._FFMPEG_VERSION, _common.STATE.codec)
        try:
            for version in ((7, 1), (8, 1)):
                _common._FFMPEG_VERSION = version
                self.assertEqual(dc(pad, un, ["red"], black), "setparams=colorspace=bt709:range=tv," + pad, version)
                self.assertEqual(dc(pad, full, ["red"], black), "setparams=colorspace=bt709," + pad, version)
                for m in (t709, rgb, meta(color_space="smpte170m")):  # a tagged or converted link is followed already
                    self.assertEqual(dc(pad, m, ["red"], black), pad, (version, m))
                self.assertEqual(dc(pad, un, ["red"], black, labelled=True), pad)
            for version in ((5, 1), (6, 1), (7, 0), (0, 0)):
                _common._FFMPEG_VERSION = version
                for m, fmt, rng in ((un, "yuv420p", "tv"), (t709, "yuv420p", "tv"), (rgb, "yuv444p", "tv"), (full, "yuvj420p", "pc")):
                    island = dc(pad, m, ["red"], black)
                    self.assertEqual(island, _common.rgb_island(pad, black, fmt, rng == "pc", "d"))
                    self.assertTrue(island.startswith(f"split=3[_dp][_dc][_dn];[_dp]format={fmt},{black}[_dp1];"), island)
                    self.assertIn(f"[_dc]scale=in_color_matrix=bt709:in_range={rng},format=rgb24,{pad},"
                                  f"scale=out_color_matrix=bt709:out_range={rng},format={fmt},split[_dc1][_dc2];", island)
                    self.assertIn(f"[_dn]scale=in_color_matrix=bt709:in_range={rng},format=rgb24,{black},", island)
                    self.assertTrue(island.endswith("blend=all_mode=difference,lut=c0='255*gt(val,0)':c1='255*gt(val,0)':"
                                                    "c2='255*gt(val,0)'[_dm];[_dp1][_dc2][_dm]maskedmerge"), island)
                self.assertEqual(dc("drawtext=x=1", un, ["red"], tag="t7"),
                                 _common.rgb_island("drawtext=x=1", "null", "yuv420p", False, "t7"))
            for version in ((6, 1), (8, 1)):
                _common._FFMPEG_VERSION = version
                self.assertEqual(dc(pad, un, ["black", "white@0.5", "0x808080", None], black), pad)  # greys
                self.assertEqual(dc(pad, hdr, ["red"], black), pad)  # an HDR line keeps its own tags
                self.assertEqual(dc(pad, un, ["red"], black, line_meta=hdr), pad)
                _common.STATE.codec = "prores"  # prores keeps the source's
                self.assertEqual(dc(pad, un, ["red"], black), pad)
                _common.STATE.codec = None
        finally:
            _common._FFMPEG_VERSION, _common.STATE.codec = saved

        # every tool that draws a colour, planned on this build: a colour with chroma takes the label
        # (7.1+) or the RGB island (older), once per picture it is drawn on; the default greys plan
        # neither. join/broll/grid label every untagged input on any build (the label changes nothing
        # before 7.1). background.py and waveform.py make their colours in RGB and convert them.
        modern = _common.ffmpeg_version() >= (7, 1)
        conv = "scale=out_color_matrix=bt709:out_range=tv"
        cases = [  # (tool, args, labels on 7.1+, (islands, labels) before 7.1, conversions)
            ("fit", [self.src, "--width", "320", "--height", "320", "--pad-color", "red"], 1, (1, 0), 0),
            ("fit", [self.src, "--width", "320", "--height", "320"], 0, (0, 0), 0),
            ("export", [self.src, "--preset", "reels", "--pad-color", "0x2878C8"], 1, (1, 0), 0),
            ("export", [self.src, "--preset", "gif", "--pad-color", "red"], 0, (0, 0), 0),  # palettegen reads BT.601 back
            ("pad", [self.src, "--start", "1", "--color", "red"], 1, (1, 0), 0),
            ("pad", [self.src, "--start", "1", "--color", "0x101010"], 0, (0, 0), 0),
            ("straighten", [self.src, "--degrees", "2", "--fit", "pad", "--fill-color", "0x00FF00"], 1, (1, 0), 0),
            ("overlay", [self.src, "--text", "hi", "--font-color", "yellow"], 1, (1, 0), 0),
            ("overlay", [self.src, "--text", "hi", "--box", "--box-color", "0x2878C8@0.5"], 1, (1, 0), 0),
            ("overlay", [self.src, "--text", "hi", "--box"], 0, (0, 0), 0),
            ("caption", [self.src, "--text", self.cues, "--color", "FF0000"], 1, (1, 0), 0),
            ("caption", [self.src, "--text", self.cues], 0, (0, 0), 0),
            ("join", [self.src, self.camb, "--pad-color", "red"], 2, (2, 2), 0),
            ("join", [self.src, self.camb], 0, (0, 0), 0),
            ("broll", [self.src, "--insert", self.camb, "--at", "1", "--duration", "1", "--pad-color", "red"], 2, (1, 2), 0),
            ("grid", [self.src, self.camb, "--cols", "2", "--rows", "1", "--background", "red", "--gap", "8"], 2, (2, 2), 0),
            ("grid", [self.src, self.camb, "--cols", "2", "--rows", "1", "--gap", "8"], 0, (0, 0), 0),
            ("graphics", [self.src, "--template", "chapter", "--title", "T"], 1, (1, 0), 0),  # the brand-yellow chip
            ("graphics", [self.src, "--template", "meme", "--top", "T"], 0, (0, 0), 0),
            ("background", ["--duration", "1", "--width", "64", "--height", "64", "--color", "red"], 0, (0, 0), 1),
            ("background", ["--duration", "1", "--width", "64", "--height", "64"], 0, (0, 0), 0),
            ("waveform", [self.src], 0, (0, 0), 2),  # lime waves: the background and the waves
            ("waveform", [self.src, "--color", "white"], 0, (0, 0), 0),
        ]
        for k, (name, args, labels, (islands, old_labels), convs) in enumerate(cases):
            with self.subTest(tool=name, args=[Path(str(a)).name for a in args]):
                ext = ".gif" if "gif" in args else ".mp4"
                proc = tool(name, *args, "-o", self.out(f"drawn_{k}{ext}"), "--dry-run", "--json", check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
                commands = " ".join(json.loads(proc.stdout)["commands"])
                if modern:
                    islands, old_labels = 0, labels
                self.assertEqual(commands.count("maskedmerge"), islands, commands)
                self.assertEqual(commands.count("setparams=colorspace=bt709"), old_labels, commands)
                self.assertEqual(commands.count(conv) - 2 * islands, convs, commands)  # an island converts twice

    def test_json_success_and_failure_shapes_and_exit_codes(self):
        doc = json.loads(tool("cut", self.wav, "--start", "1", "--end", "3", "-o", self.out("shape.wav"), "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        for key in self.tools["cut"]["output_schema"]["required"]:
            self.assertIn(key, doc)
        self.assertIn("probe", doc)
        proc = tool("cut", self.work / "missing.mp4", "--json", check=False)
        self.assertEqual(proc.returncode, 1)
        err = json.loads(proc.stdout)
        self.assertEqual(err["status"], "failed")
        self.assertEqual(err["error"]["kind"], "input")
        self.assertIn("not found", err["error"]["message"])
        self.assertIn("error:", proc.stderr, "stderr message kept for existing callers")
        # without --json the old behaviour is unchanged: empty stdout, message on stderr
        proc = tool("cut", self.work / "missing.mp4", check=False)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.returncode, 1)
        # missing ffmpeg -> exit 127, kind missing_tool
        env = dict(os.environ, PATH=str(self.work / "empty"))
        (self.work / "empty").mkdir(exist_ok=True)
        proc = tool("loudness", self.src, "--json", env=env, check=False)
        self.assertEqual(proc.returncode, 127)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "missing_tool")

    def test_probe_and_cut_on_a_non_ascii_filename(self):
        """A file whose *name itself* (not just a path referenced inside a filter-graph string,
        which test_filter_paths_with_drive_colon_spaces_and_unicode already covers) contains CJK
        and accented characters must round-trip correctly as -i/output argv through subprocess.

        Python 3.9 (this repo's CI-pinned version) uses CreateProcessW for subprocess argv on
        Windows, and the filesystem encoding is UTF-8 on macOS/Linux, so this is expected to work
        on all three OSes -- but this sandbox can only actually execute on Linux. This test is
        the mechanism by which the claim gets verified on Windows and macOS too, once this runs
        through the existing CI matrix (see .github/workflows/ci.yml).
        """
        src = self.work / "日本語_ünïcödé.mp4"
        shutil.copyfile(self.src, src)
        # read tool: probe.py against the non-ASCII input path
        meta = json.loads(tool("probe", src, "--json").stdout)
        self.assertAlmostEqual(meta["duration"], 6.0, delta=0.3)
        self.assertEqual(meta["video"]["width"], 640)
        # write tool: cut.py, non-ASCII input -> plain-ASCII output
        out_ascii = self.out("nonascii_cut.mp4")
        doc = json.loads(tool("cut", src, "--start", "1", "--end", "3", "-o", out_ascii, "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertAlmostEqual(doc["probe"]["duration"], 2.0, delta=0.6)
        reprobed = json.loads(tool("probe", out_ascii, "--json").stdout)
        self.assertAlmostEqual(reprobed["duration"], 2.0, delta=0.6)
        # and the other direction: plain-ASCII input -> non-ASCII output path
        out_unicode = self.work / "出力_prüfung.mp4"
        doc2 = json.loads(tool("cut", self.src, "--start", "0", "--end", "2", "-o", out_unicode, "--json").stdout)
        self.assertEqual(doc2["status"], "completed")
        self.assertTrue(out_unicode.exists())
        reprobed2 = json.loads(tool("probe", out_unicode, "--json").stdout)
        self.assertAlmostEqual(reprobed2["duration"], 2.0, delta=0.6)

    # ------------------------------------------------------------------ fail loudly
    def test_timeout_kills_a_hung_ffmpeg_and_reports_kind_timeout(self):
        """A build that deadlocks on a filter combination (conda-forge's 7.1.1 on tpad+adelay,
        seen while chasing #156) used to hang the calling agent with it: no error document, no
        partial-output cleanup, nothing short of a manual kill. --timeout (default 1800 s,
        FFMPEG_SKILL_TIMEOUT) turns that into a failure the agent can read: kind timeout, code
        TIMEOUT, exit 124, the partial output removed, the command still recorded. A limit far
        below what any encode of the 6 s fixture can meet is the cheapest reliable reproduction;
        verify.py keeps its own per-step --timeout, which applies the same way."""
        out = self.out("timeout.mp4")
        proc = tool("fit", self.src, "--aspect", "9:16", "--timeout", "0.05", "--json", "-o", out, check=False)
        self.assertEqual(proc.returncode, 124, proc.stderr[-300:])
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"], doc["error"]["code"], doc["exit_code"]), ("failed", "timeout", "TIMEOUT", 124))
        self.assertIn("--timeout", doc["error"]["message"])
        self.assertTrue(doc["commands"] and "ffmpeg" in doc["commands"][0])
        self.assertFalse(out.exists(), "a killed encode must not leave a partial file behind")
        # 0 disables the limit; a generous limit does not interfere with a normal short run
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "1", "--timeout", "0", "-o", self.out("timeout_off.mp4")).returncode, 0)
        env = dict(os.environ, FFMPEG_SKILL_TIMEOUT="0.05")
        proc = tool("fit", self.src, "--aspect", "9:16", "--json", "-o", self.out("timeout_env.mp4"), env=env, check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "timeout", "the env default applies without the flag")
        self.assertIn("timeout", self.contract["json_output"]["error_kinds"])

    def test_encoder_flags_are_validated_before_ffmpeg_sees_them(self):
        """--preset took any string and --crf any integer; an agent's typo ("--preset fastest",
        "--crf 99") reached ffmpeg and came back as kind ffmpeg with x264's stderr, which reads as
        an encoder failure rather than a bad argument. Every x264 --preset is now an argparse
        choice (so the contract and MCP schema carry the enum) and --quality (2.0; --crf until
        then) and export.py's own --crf are range-checked once in apply_common."""
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--preset", "fastest", "--json", "-o", self.out("p.mp4"), check=False)
        self.assertEqual(proc.returncode, 2, "argparse rejects an unknown preset")
        self.assertIn("invalid choice", proc.stderr)
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--quality", "99", "--json", "-o", self.out("c.mp4"), check=False)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("--quality must be between 0 and 51", doc["error"]["message"])
        self.assertEqual(doc["commands"], [], "refused before any ffmpeg ran")
        proc = tool("export", self.src, "--preset", "youtube", "--crf", "99", "--json", "-o", self.out("e.mp4"), check=False)
        doc = json.loads(proc.stdout)
        self.assertIn("--crf must be between 0 and 51", doc["error"]["message"])
        for name, spec in self.tools.items():
            preset = spec["input_schema"]["properties"].get("preset")
            if preset and name != "export":
                self.assertEqual(set(preset["enum"]), set(_common.X264_PRESETS), name)

    def test_sibling_scripts_run_under_an_outer_ceiling(self):
        """render/batch/report and the MCP server run sibling scripts as subprocesses. The child
        limits each of its own ffmpeg calls with --timeout, but a child hung for any other reason
        (a wedged pipe, a stuck import) was waited on forever: none of those outer subprocess.run
        calls had a timeout. run_tool() applies child_limit() (4x the per-call limit + 60 s) and
        returns this skill's own timeout failure document, so a caller parsing the child's --json
        sees kind timeout exactly as it would from the child. Exercised with a script that sleeps
        past a tiny limit (the ceiling is computed from the per-call limit, not fixed)."""
        self.assertIsNone(_common.child_limit(0), "0 = no limit, as for --timeout")
        self.assertEqual(_common.child_limit(10), 100)
        sleeper = self.out("sleeper.py")
        sleeper.write_text("import time\ntime.sleep(30)\n")
        _common.STATE.reset()
        _common.STATE.timeout = 0.01  # ceiling 60.04 s would be too slow; pass per_call explicitly instead
        proc = _common.run_tool([str(sleeper)], per_call=-14.9)  # -14.9*4+60 = 0.4 s
        self.assertEqual(proc.returncode, 124)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"], doc["error"]["code"]), ("failed", "timeout", "TIMEOUT"))
        self.assertIn("sleeper.py", doc["error"]["message"])
        _common.STATE.reset()

    def test_mcp_argv_timeout_zero_clears_the_outer_ceiling(self):
        """docs/design-decisions.md: --timeout 0 means no limit, including MCP dispatch. The
        structured `timeout` key already did. A raw argv list ignores every other key, so
        `--timeout 0` inside it left the outer ceiling at 4x the 1800 s default while the child
        ran with no limit. A negative value matches apply_common and is also no limit."""
        captured = {}

        def fake_run_tool(argv, per_call=None):
            captured["per_call"] = per_call
            captured["ceiling"] = _common.child_limit(per_call)
            return subprocess.CompletedProcess(argv, 0, "{}", "")

        saved = mcp_server._common.run_tool
        mcp_server._common.run_tool = fake_run_tool
        try:
            mcp_server.call_tool("probe", {"argv": [str(self.wav), "--timeout", "0"]})
            self.assertEqual(captured["per_call"], 0.0)
            self.assertIsNone(captured["ceiling"])
            self.assertEqual(mcp_server.build_argv("probe", {"argv": [str(self.wav), "--timeout", "0"]}),
                             [str(self.wav), "--timeout", "0"])
            mcp_server.call_tool("probe", {"argv": [str(self.wav), "--timeout=0"]})
            self.assertIsNone(captured["ceiling"])
            mcp_server.call_tool("probe", {"input": str(self.wav), "timeout": 0})
            self.assertEqual(captured["per_call"], 0.0)
            self.assertIsNone(captured["ceiling"])
            mcp_server.call_tool("probe", {"argv": [str(self.wav), "--timeout", "30"]})
            self.assertEqual(captured["per_call"], 30.0)
            self.assertEqual(captured["ceiling"], 180.0)
            mcp_server.call_tool("probe", {"argv": [str(self.wav), "--timeout", "-5"]})
            self.assertEqual(captured["per_call"], 0.0)
            self.assertIsNone(captured["ceiling"])
            mcp_server.call_tool("probe", {"argv": [str(self.wav)]})
            self.assertEqual(captured["per_call"], _common._env_timeout())
            self.assertEqual(captured["ceiling"], _common.child_limit(_common._env_timeout()))
        finally:
            mcp_server._common.run_tool = saved

    def test_dry_run_plans_rest_on_real_measurements(self):
        """silence.py, loudness.py, check.py and stabilize.py ran their measurement through run(),
        which --dry-run replaces with a fake empty result: a dry run always reported "0 silences",
        a made-up -20 LUFS, a loudness row that could not be measured, and no stabilisation pass.
        A plan built on a fake measurement is not a plan. The measurement passes now go through
        run_analysis() (real under --dry-run, still under --timeout); only the write is skipped."""
        gappy = self.out("gappy.mp4")
        ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.25*t)\\,0)':s=48000",
               "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30", "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", gappy)
        doc = json.loads(tool("silence", gappy, "--dry-run", "--list", "--json").stdout)
        self.assertTrue(doc["dry_run"])
        self.assertTrue(doc["silences"], "a dry run must detect the fixture's real silences")
        self.assertTrue(any("silencedetect" in c for c in doc["commands"]))
        doc = json.loads(tool("loudness", self.src, "--dry-run", "--json", "-o", self.out("dry_loud.mp4")).stdout)
        self.assertTrue(doc["dry_run"])
        self.assertNotEqual(doc["measured"]["input_i"], "-20.0", "the pass-1 measurement must be real, not the old placeholder")
        self.assertFalse(self.out("dry_loud.mp4").exists())
        doc = json.loads(tool("check", self.src, "--platform", "youtube", "--dry-run", "--json", check=False).stdout)
        rows = {r["check"]: r for r in doc["checks"]}
        self.assertNotIn("could not be measured", rows["loudness"].get("reason", ""), rows["loudness"])

    def test_run_analysis_is_killed_by_timeout(self):
        """A measurement (scenes.py's scdet pass) that hangs is killed under the same --timeout
        as any other ffmpeg call and reported as kind timeout, not waited on forever."""
        if platform.system() == "Windows":
            self.skipTest("the hung ffmpeg is a #!/bin/sh shim on a POSIX-only PATH")
        shim = self.out("hang_analysis_shim")
        shim.mkdir()
        (shim / "ffmpeg").write_text("#!/bin/sh\nsleep 8\nexit 1\n")
        (shim / "ffmpeg").chmod(0o755)
        (shim / "ffprobe").symlink_to(shutil.which("ffprobe"))
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
        t0 = time.time()
        proc = tool("scenes", self.src, "--timeout", "1", "--json", env=env, check=False)
        self.assertEqual(proc.returncode, 124, proc.stderr[-300:])
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "timeout")
        self.assertLess(time.time() - t0, 6)

    def test_caller_supplied_text_files_fail_as_kind_input(self):
        """--text/--srt/--chapters/--commands/--notes files that are missing, a directory or not
        UTF-8 used to surface as FileNotFoundError / IsADirectoryError / UnicodeDecodeError
        tracebacks. read_text_or_die() names the flag and fails as kind input."""
        bad = self.out("latin1.txt")
        bad.write_bytes(b"0:00-0:01 caf\xe9\n")
        adir = self.out("a_directory")
        adir.mkdir()
        for args, needle in ((["--text", str(self.out("nope.txt"))], "does not exist"),
                             (["--text", str(adir)], "is a directory"),
                             (["--text", str(bad)], "not UTF-8")):
            proc = tool("caption", self.src, *args, "--json", "-o", self.out("cap_bad.mp4"), check=False)
            self.assertNotEqual(proc.returncode, 0)
            doc = json.loads(proc.stdout)
            self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"), args)
            self.assertIn("--text", doc["error"]["message"])
            self.assertIn(needle, doc["error"]["message"])
            self.assertEqual(doc["commands"], [], "refused before ffmpeg ran")

    def test_batch_reports_failed_items_as_a_failed_run(self):
        """batch.py printed status completed next to exit 1 when an item failed; it now fails
        with kind verification and keeps the per-item results so the caller sees which."""
        folder = self.out("batch_fail")
        folder.mkdir()
        shutil.copy(self.src, folder / "a.mp4")
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_x",
                                      "steps": [["cut.py", "{in}", "--start", "0", "--end", "1", "--quality", "99", "-o", "{out}"]]}))
        proc = tool("batch", folder, "--recipe", recipe, "--json", check=False)
        self.assertEqual(proc.returncode, 1)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"], doc["processed"], doc["total"]), ("failed", "verification", 0, 1))
        self.assertFalse(doc["results"][0]["ok"])

    def test_bug_report_2026_09_12_regressions(self):
        """Pins from the third audit: concat list lines are Windows-safe; SMPTE parse and format
        agree at 29.97; cut/freeze accept SMPTE with the input's fps and refuse bad times as kind
        input; look.py honours -o for a single --at; audio refuses --mono with --stereo and an
        out-of-range --denoise-strength; render refuses speed 0; batch lists .ogg/.opus/.ts;
        report's 0 s is 0 s; ffmpeg_version has a probe timeout. (speed 0 was already "unset", not a
        division by zero as reported; a negative speed did reach fit.py.)"""
        self.assertEqual(_common.concat_list_line("C:\\Users\\t\\part000.mp4"), "file 'C:/Users/t/part000.mp4'")
        self.assertEqual(_common.concat_list_line("/a/it's.mp4"), "file '/a/it'\\''s.mp4'")
        for tc in ("00:00:00:29", "00:00:01:00", "01:00:00:00", "00:59:56:12"):
            secs = _common.parse_time(tc, 29.97)
            self.assertEqual(_common.fmt_smpte_time(secs, 29.97), tc, tc)
        self.assertAlmostEqual(_common.parse_time("01:00:00:00", 29.97), 3600 * 30 / 29.97, places=3)
        proc = tool("cut", self.src, "--start", "00:00:01:00", "--end", "00:00:02:15", "--json", "-o", self.out("smpte_cut.mp4"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        proc = tool("cut", self.src, "--start", "00:00:01:99", "--end", "2", "--json", "-o", self.out("smpte_bad.mp4"), check=False)
        self.assertEqual((proc.returncode != 0, json.loads(proc.stdout)["error"]["kind"]), (True, "input"))
        self.assertIn("out of range", json.loads(proc.stdout)["error"]["message"])
        proc = tool("freeze", self.src, "--at", "0:01", "--hold", "0.5", "--json", "-o", self.out("freeze_mmss.mp4"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        one = self.out("one_frame.png")
        doc = json.loads(tool("look", self.src, "--at", "1", "--json", "-o", one).stdout)
        self.assertEqual(doc["output"], str(one))
        self.assertTrue(one.exists())
        proc = tool("audio", self.src, "--mono", "--stereo", "-o", self.out("ms.mp4"), check=False)
        self.assertEqual(proc.returncode, 2, "argparse refuses --mono with --stereo")
        proc = tool("audio", self.src, "--denoise", "--denoise-strength", "-25", "--json", "-o", self.out("dn.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        proj = self.out("speed0.json")
        proj.write_text(json.dumps({"output": str(self.out("speed0.mp4")), "clips": [{"src": str(self.src), "speed": -1}]}))
        proc = tool("render", proj, "--dry-run", "--json", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("speed must be a positive number", json.loads(proc.stdout)["error"]["message"])
        import batch as batch_mod  # noqa: E402
        self.assertTrue({".ogg", ".opus", ".ts", ".aac"} <= batch_mod.MEDIA_EXT)
        import report as report_mod  # noqa: E402
        self.assertNotEqual(report_mod.fmt_dur(0.0), "?")
        self.assertEqual(report_mod.fmt_dur(None), "?")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["files"].count("docs/contract.md"), 1)
        self.assertIn("'docs'", (ROOT / "bin" / "install.js").read_text())

    def test_fourth_audit_regressions(self):
        """Pins from the fourth audit (1.4.8). N01: --dry-run used to skip only ffmpeg, so
        silence --edl, scenes --edl and caption's generated .ass were written while stderr said
        "would write". N02: overlay/graphics/look/insert/background/fit/loop called parse_time()
        without the input's fps, so an hh:mm:ss:ff time was a MissingFpsError traceback with no
        --json failure document (cut/freeze had been fixed, the rest had not). N03: pad --start/--end
        were argparse floats, so the mm:ss grammar every other tool accepts exited 2 without JSON."""
        # N01 -- a dry run writes no side files either
        edl = self.out("dry_silence.edl")
        proc = tool("silence", self.src, "--dry-run", "--edl", edl, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertFalse(edl.exists(), "silence --dry-run wrote --edl")
        edl2 = self.out("dry_scenes.edl")
        proc = tool("scenes", self.src, "--dry-run", "--highlights", "2", "--edl", edl2, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertFalse(edl2.exists(), "scenes --dry-run wrote --edl")
        cues = self.out("dry_cues.txt")
        cues.write_text("0:00 hello\n0:02 world\n", encoding="utf-8")
        cap = self.out("dry_cap.mp4")
        proc = tool("caption", self.src, "--text", cues, "--animate", "pop", "--dry-run", "--json", "-o", cap)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertFalse(cap.with_suffix(".ass").exists(), "caption --dry-run wrote the generated .ass")
        self.assertFalse(cap.exists())
        # N02 -- SMPTE resolves with the input's fps; a bad timecode is a kind: input document
        proc = tool("overlay", self.src, "--text", "hi", "--start", "00:00:01:15", "--dry-run", "--json", "-o", self.out("smpte_ov.mp4"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertNotIn("Traceback", proc.stderr)
        proc = tool("look", self.src, "--at", "00:00:01:15", "--dry-run", "--json", "-o", self.out("smpte_look.png"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertIn("1.500", " ".join(map(str, json.loads(proc.stdout)["commands"])))
        proc = tool("overlay", self.src, "--text", "hi", "--start", "00:00:01:99", "--json", "-o", self.out("smpte_ov_bad.mp4"), check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--start", doc["error"]["message"])
        proc = tool("fit", self.src, "--duration", "00:00:01:15", "--dry-run", "--json", "-o", self.out("smpte_fit.mp4"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        proc = tool("background", "--duration", "00:00:01:15", "--fps", "30", "--width", "64", "--height", "64", "--dry-run", "--json", "-o", self.out("smpte_bg.mp4"))
        self.assertIn("1.500", " ".join(map(str, json.loads(proc.stdout)["commands"])))
        # N03 -- pad speaks the shared time grammar and refuses junk as kind: input
        proc = tool("pad", self.src, "--start", "1:30", "--dry-run", "--json", "-o", self.out("pad_mmss.mp4"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertIn("start_duration=90.000", " ".join(map(str, json.loads(proc.stdout)["commands"])))
        proc = tool("pad", self.src, "--start", "abc", "--json", "-o", self.out("pad_bad.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def test_filter_paths_with_apostrophes_open(self):
        """Fourth review, P1: escape_filter_path wrote `\\'`, which the graph parser consumed as a
        quote, so "Ryo's Mac/cues.srt" reached the subtitles filter as "Ryos Mac/cues.srt". Pin
        the escaping and a real burn-in plus LUT through directories and names with apostrophes."""
        self.assertEqual(_common.escape_filter_path("/a/Ryo's Mac/c.srt"), "/a/Ryo\\\\\\'s Mac/c.srt")
        d = self.out("Ryo's Mac"); d.mkdir(exist_ok=True)
        srt = d / "cu'es.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nhi\n\n", encoding="utf-8")
        proc = tool("caption", self.src, "--srt", srt, "--fast", "--json", "-o", d / "ap'os.mp4")
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        cube = d / "id'ent.cube"
        with open(cube, "w") as fh:
            fh.write("LUT_3D_SIZE 2\n")
            for b in (0, 1):
                for g in (0, 1):
                    for r in (0, 1):
                        fh.write(f"{r:.1f} {g:.1f} {b:.1f}\n")
        proc = tool("color", self.src, "--lut", cube, "--fast", "--json", "-o", d / "lu't.mp4")
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])

    def test_loudness_holds_true_peak_in_the_written_file(self):
        """Fourth review, P1: loudnorm held -1 dBTP on its float output and the AAC encoder then
        overshot (+1.2 dBTP on a real film, +3.4 on this square wave), so the file failed the
        ceiling it was made to meet and check.py's fix hint pointed back at loudness.py. The
        tool now measures the written file and re-encodes (more bits, then a lower ceiling)
        until it meets --tp. A lossless output needs one encode."""
        # 50 ms square-wave bursts once a second: quiet on average (so -14 LUFS leaves the peaks
        # at the ceiling) with the hard edges the AAC encoder overshoots on
        sq = self.out("square.wav")
        ffmpeg("-f", "lavfi", "-i", "sine=f=1000:r=48000:d=6,aeval='sgn(val(0))*0.9*lt(mod(t\\,1)\\,0.05)'", "-c:a", "pcm_s16le", sq)
        doc = json.loads(tool("loudness", sq, "-I", "-14", "--tp", "-1", "--json", "-o", self.out("square_norm.m4a")).stdout)
        self.assertEqual(doc["status"], "completed")
        r = doc["result"]
        self.assertLessEqual(float(r["input_tp"]), -0.9, r)
        self.assertGreater(r["encodes"], 1, "the first AAC encode was expected to overshoot")
        doc = json.loads(tool("loudness", sq, "-I", "-14", "--tp", "-1", "--json", "-o", self.out("square_norm.wav")).stdout)
        self.assertEqual(doc["result"]["encodes"], 1)
        self.assertLessEqual(float(doc["result"]["input_tp"]), -0.9)

    @unittest.skipIf(platform.system() == "Windows", "SIGTERM is not deliverable to a process on Windows; the handler is registered there for Ctrl-C only")
    def test_sigterm_and_sigint_stop_ffmpeg_and_report_interrupted(self):
        """Fourth review, P1: SIGTERM killed only the Python parent -- ffmpeg carried on as an
        orphan and finished a file nobody verified, with no JSON; SIGINT was a KeyboardInterrupt
        traceback with the partial left on disk. Now both stop the child, remove the partial and
        print a kind: interrupted failure document (exit 130/143)."""
        import signal
        import time
        long_src = self.out("long_src.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "40", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", long_src)
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGINT, 130)):
            out = self.out(f"sig{code}.mp4")
            p = subprocess.Popen([sys.executable, str(SCRIPTS / "fit.py"), str(long_src), "--aspect", "9:16", "--preset", "placebo", "--json", "-o", str(out)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.time() + 30
            while time.time() < deadline and not out.exists():
                time.sleep(0.2)
            self.assertTrue(out.exists(), "ffmpeg never opened the output")
            time.sleep(1.0)
            p.send_signal(sig)
            stdout, stderr = p.communicate(timeout=60)
            self.assertEqual(p.returncode, code, stderr[-400:])
            self.assertNotIn("Traceback", stderr)
            doc = json.loads(stdout)
            self.assertEqual((doc["status"], doc["error"]["kind"], doc["exit_code"]), ("failed", "interrupted", code))
            self.assertFalse(out.exists(), "partial output left behind")
            # no orphaned ffmpeg writing that path
            ps = subprocess.run(["pgrep", "-f", str(out)], stdout=subprocess.PIPE, text=True) if shutil.which("pgrep") else None
            if ps is not None:
                self.assertEqual(ps.stdout.strip(), "", "an ffmpeg is still running on the output")

    def test_output_directory_mistakes_are_kind_input(self):
        """Fourth review, P2: `-o some/dir` was OUTPUT_INVALID after ffmpeg ran and `-o missing/dir/x.mp4`
        was `kind: ffmpeg` from the muxer's ENOENT, both reading as encoder failures. Both are caller
        mistakes and are refused before ffmpeg runs, under --dry-run too."""
        d = self.out("a_directory"); d.mkdir(exist_ok=True)
        for out, needle in ((d, "is a directory"), (self.out("no_such_dir") / "x.mp4", "does not exist")):
            for extra in ((), ("--dry-run",)):
                proc = tool("fit", self.src, "--aspect", "1:1", "--json", "-o", out, *extra, check=False)
                self.assertNotEqual(proc.returncode, 0)
                doc = json.loads(proc.stdout)
                self.assertEqual(doc["error"]["kind"], "input", doc)
                self.assertIn(needle, doc["error"]["message"])

    def test_batch_default_outdir_is_inside_the_folder_once(self):
        """Fourth review, P2: `batch.py bdir --recipe r.json` with a relative folder wrote to
        bdir/bdir/out because the default outdir (folder / "out") was joined with the folder again."""
        import batch as batch_mod  # noqa: E402
        bdir = self.out("bdir"); bdir.mkdir(exist_ok=True)
        shutil.copyfile(self.src, bdir / "clip.mp4")
        recipe = self.out("batch_recipe.json")
        recipe.write_text(json.dumps({"glob": "*.mp4", "steps": [["fit.py", "{in}", "--aspect", "1:1", "-o", "{out}"]]}), encoding="utf-8")
        # a real (fast) run: since the sweep fixes a --dry-run leaves no directory behind, so the
        # placement of the default outdir is only visible after a write
        proc = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), "bdir", "--recipe", str(recipe), "--fast", "--json"],
                              cwd=str(self.work), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertFalse((bdir / "bdir").exists(), "outdir was doubled")
        self.assertTrue((bdir / "out").is_dir(), "default outdir is <folder>/out")

    def test_fifth_audit_regressions(self):
        r"""Pins from the fifth audit (100 items, 2026-09-12). Confirmed and fixed here: yuv410p
        read as 10-bit (#2); audio --mono halved an already-mono track (#3); sync --replace-audio
        cut the reference to the shorter second (#4); 25+ tools raised TypeError formatting a
        None duration after a successful encode (#5); energy karaoke gave the last word a
        negative \kf on a short cue (#6); the energy decode ran outside --timeout (#7); render's
        final copy bypassed the output guards (#8); the video join forced stereo (#10); multicam
        -shortest (#12); ffprobe JSON parse without a guard (#14); git-build version strings read
        as 0.0 (#15); freeze --mode insert desynced copied subtitles (#31); sequence globbed
        frames lexically (#98); negative --segments start (#18); speedramp refused mm:ss (#29);
        two MEDIA_EXT lists (#55); colour alpha > 1 reached ffmpeg (#69); blur radius > frame (#57)."""
        # 2, 5, 55, 69, 57 -- helpers
        for pix, depth in (("yuv410p", 8), ("yuv420p", 8), ("yuv420p10le", 10), ("gbrp12be", 12), ("gray16le", 16), ("rgb24", 8), ("rgb48le", 16)):
            self.assertEqual(_common._bit_depth(pix), depth, pix)
        self.assertEqual(_common.fmt_secs(None), "?s")
        self.assertEqual(_common.fmt_secs(1.5), "1.500s")
        leftovers = [p.name for p in script_sources() if re.search(r"duration['\"]\]:\.3f\}s|duration['\"]\):\.3f\}s", p.read_text(encoding="utf-8"))]
        self.assertEqual(leftovers, [], "a script still formats a possibly-None duration with :.3f")
        self.assertIn(".mxf", _common.MEDIA_EXT)
        import batch as batch_mod  # noqa: E402
        self.assertTrue(batch_mod.MEDIA_EXT <= _common.MEDIA_EXT)
        self.assertEqual(_common.validate_color("red@0.5"), "red@0.5")
        with self.assertRaises(SystemExit):
            _common.validate_color("red@2")
        self.assertIn("boxblur=7:2", _common.pad_filters(16, 16, "blur", "black", 20))
        import sequence as seq_mod  # noqa: E402
        self.assertEqual(sorted(["img10.png", "img2.png", "img1.png"], key=seq_mod.natural_key), ["img1.png", "img2.png", "img10.png"])
        # 6 -- karaoke never emits a non-positive word length
        import caption as cap_mod  # noqa: E402
        words = cap_mod.word_durations_from_audio(str(self.src), 0.0, 0.5, 20)
        self.assertEqual((len(words), sum(words), min(words) >= 1), (20, 50, True), words)
        # 3 -- mono input, --mono: no stereo pan
        mono = self.out("mono_in.mp4")
        ffmpeg("-f", "lavfi", "-i", "sine=f=440:r=48000:d=2", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "2", "-ac", "1", "-c:a", "aac", "-c:v", "libx264", "-preset", "veryfast", mono)
        doc = json.loads(tool("audio", mono, "--mono", "--dry-run", "--json", "-o", self.out("mono_out.mp4")).stdout)
        self.assertNotIn("pan=mono", " ".join(map(str, doc["commands"])))
        # 10 -- 5.1 + stereo video join keeps 5.1
        six = self.out("six.mp4")
        ffmpeg("-f", "lavfi", "-i", "sine=f=440:r=48000:d=2", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "2", "-af", "aformat=channel_layouts=5.1", "-c:a", "aac", "-c:v", "libx264", "-preset", "veryfast", six)
        doc = json.loads(tool("join", six, mono, "--transition", "none", "--dry-run", "--json", "-o", self.out("join51.mp4")).stdout)
        self.assertIn("channel_layouts=5.1", " ".join(map(str, doc["commands"])))
        self.assertNotIn("channel_layouts=stereo", " ".join(map(str, doc["commands"])))
        # 12 -- multicam trims to the cut list, not the shortest stream
        doc = json.loads(tool("multicam", self.src, self.src, "--auto", "2", "--dry-run", "--json", "-o", self.out("mc.mp4")).stdout)
        cmd = " ".join(map(str, doc["commands"]))
        self.assertNotIn("-shortest", cmd)
        self.assertIn("-t 6.000", cmd)
        # 4 -- replace-audio keeps the reference's length when the second is shorter
        short = self.out("second_short.mp4")
        ffmpeg("-ss", "1", "-t", "3", "-i", self.src, "-c", "copy", short)
        doc = json.loads(tool("sync", self.src, short, "--replace-audio", "--json", "-o", self.out("synced_short.mp4")).stdout)
        self.assertAlmostEqual(doc["probe"]["duration"], 6.0, delta=0.15, msg=doc.get("meaning"))
        # 18, 29 -- time grammar
        proc = tool("cut", self.src, "--segments=-1-2", "--json", "-o", self.out("neg.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        doc = json.loads(tool("speedramp", self.src, "--segment", "0-0:03:2", "--segment", "0:03-0:06:1", "--dry-run", "--json", "-o", self.out("ramp.mp4")).stdout)
        self.assertEqual(doc["status"], "completed")
        # 31 -- freeze --mode insert drops a copied subtitle track instead of desyncing it
        srt = self.out("fz.srt"); srt.write_text("1\n00:00:00,500 --> 00:00:01,000\na\n\n2\n00:00:02,000 --> 00:00:02,500\nb\n\n", encoding="utf-8")
        mkv = self.out("fz_in.mkv")
        ffmpeg("-i", self.src, "-i", srt, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt", mkv)
        doc = json.loads(tool("freeze", mkv, "--at", "1", "--hold", "1", "--mode", "insert", "--fast", "--json", "-o", self.out("fz_out.mkv")).stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        self.assertEqual(doc["probe"].get("subtitle_streams") or 0, 0)
        # 8 -- render's final copy goes through the output guards (existing file replaced via a temp, nothing left behind)
        out = self.out("rend_out.mp4"); shutil.copyfile(self.src, out)
        proj = self.out("rend.json"); proj.write_text(json.dumps({"output": str(out), "clips": [{"src": str(self.src), "in": 0, "out": 1}]}))
        # 2.0: without --overwrite render refuses up front, before any stage runs
        refused = tool("render", proj, "--fast", "--json", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertEqual((json.loads(refused.stdout)["error"]["kind"], json.loads(refused.stdout)["commands"]), ("input", []))
        self.assertNotIn("cut.py", refused.stderr, "no stage ran before the refusal")
        doc = json.loads(tool("render", proj, "--fast", "--json", "--overwrite").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertAlmostEqual(doc["probe"]["duration"], 1.0, delta=0.15)
        self.assertEqual([p.name for p in out.parent.glob(".rend_out.ffskill-*")], [])

    @unittest.skipIf(platform.system() == "Windows", "the fake ffprobe is a #!/bin/sh shim on a POSIX-only PATH")
    def test_ffmpeg_version_falls_back_to_libavutil_on_git_builds(self):
        """Fifth audit #15: `ffprobe version N-115000-g...` has no major.minor, so the version was
        (0, 0) and every version branch took the oldest spelling -- on a 7.1 git build that skipped
        bt709_tag_args()'s workaround. The libavutil major maps onto the FFmpeg major."""
        shim = self.out("verprobe_shim"); shim.mkdir(exist_ok=True)
        (shim / "ffprobe").write_text("#!/bin/sh\nprintf 'ffprobe version N-115000-g1234abcd Copyright (c) 2007-2025\\nlibavutil      59. 39.100 / 59. 39.100\\n'\n")
        (shim / "ffprobe").chmod(0o755)
        code = ("import sys; sys.path.insert(0, %r); import _common; print(_common.ffmpeg_version())" % str(SCRIPTS))
        env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
        out = subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True, check=True).stdout
        self.assertEqual(out.strip(), "(7, 0)")

    def _release_shim(self, name, banner):
        """A PATH holding an ffprobe that answers `-version` with `banner` and hands every other
        call to the real ffprobe, so a tool plans for that release on any machine."""
        shim = self.out(name); shim.mkdir(exist_ok=True)
        (shim / "ffprobe").write_text("#!/bin/sh\nif [ \"$1\" = \"-version\" ]; then printf '%s\\n'; exit 0; fi\n"
                                      "exec %s \"$@\"\n" % (banner, shutil.which("ffprobe")))
        (shim / "ffprobe").chmod(0o755)
        return dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")

    @unittest.skipIf(platform.system() == "Windows", "the fake ffprobe is a #!/bin/sh shim on a POSIX-only PATH")
    def test_ffmpeg_release_reads_the_point_release(self):
        """A drawtext bug that 8.0 introduced and 8.0.2 / 8.1.1 fixed cannot be told apart by
        ffmpeg_version()'s major.minor; ffmpeg_release() reads the patch level too (a distro suffix
        is ignored, a bare major.minor is .0) and has none for a git build."""
        code = ("import sys; sys.path.insert(0, %r); import _common; "
                "print(_common.ffmpeg_release(), _common.drawtext_draws_newline_glyph())" % str(SCRIPTS))
        for banner, expected in (("ffprobe version 8.0.1-3ubuntu2 Copyright (c) 2007-2025", "(8, 0, 1) True"),
                                 ("ffprobe version n8.1 Copyright (c) 2007-2026", "(8, 1, 0) True"),
                                 ("ffprobe version 8.0.2 Copyright (c) 2007-2026", "(8, 0, 2) False"),
                                 ("ffprobe version 8.1.1 Copyright (c) 2007-2026", "(8, 1, 1) False"),
                                 ("ffprobe version 6.1.1-3ubuntu5 Copyright (c) 2007-2023", "(6, 1, 1) False"),
                                 ("ffprobe version N-121000-g1234abcd Copyright (c) 2007-2026", "None False")):
            env = self._release_shim("release_shim", banner)
            out = subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True, check=True).stdout
            self.assertEqual(out.strip(), expected, banner)

    @unittest.skipIf(platform.system() == "Windows", "the fake ffprobe is a #!/bin/sh shim on a POSIX-only PATH")
    def test_multi_line_text_avoids_drawtext_on_releases_that_draw_the_line_break(self):
        """FFmpeg 8.0, 8.0.1 (Ubuntu 26.04's apt build) and 8.1.0 shape each line of a multi-line
        drawtext WITH its newline, so the font's missing-glyph box is drawn at the end of every line
        but the last (CI on ubuntu-latest: the lower-third's title measured as three yellow bands).
        graphics.py's auto route sends such a label -- given with a newline or wrapped there --
        through libass on those releases, keeps drawtext for one line and on fixed releases, and a
        pinned --text-render drawtext warns. overlay.py has no libass route: it now draws each line
        with its own drawtext there, at the block's measured positions (PR #346 only warned in
        notes), and plans the single drawtext it always did on a fixed release."""
        bad = self._release_shim("nl_shim_801", "ffprobe version 8.0.1-3ubuntu2 Copyright (c) 2007-2025")
        good = self._release_shim("nl_shim_802", "ffprobe version 8.0.2 Copyright (c) 2007-2026")

        def gfx(env, *extra):
            proc = tool("graphics", self.src, "--template", "lower-third", "--name", "Jane", *extra,
                        "--dry-run", "--json", "-o", self.out("nl_gfx.mp4"), env=env)
            return json.loads(proc.stdout), proc.stderr

        doc, err = gfx(bad, "--title", "CEO\nand founder")
        self.assertEqual(doc["text_renderer"], "ass", err[-400:])
        self.assertIn("box at each line break", err)
        wrapped = json.loads(tool("graphics", self.src, "--template", "meme", "--top", "a caption far too long to fit "
                                  "across the frame on a single line", "--dry-run", "--json", "-o", self.out("nl_meme.mp4"),
                                  env=bad).stdout)
        self.assertEqual(wrapped["text_renderer"], "ass", "a label graphics.py wrapped to two lines")
        self.assertEqual(gfx(bad, "--title", "CEO")[0]["text_renderer"], "drawtext", "one line keeps drawtext")
        self.assertEqual(gfx(good, "--title", "CEO\nand founder")[0]["text_renderer"], "drawtext", "8.0.2 is fixed")
        doc, err = gfx(bad, "--title", "CEO\nand founder", "--text-render", "drawtext")
        self.assertEqual(doc["text_renderer"], "drawtext")
        self.assertIn("warning: this ffmpeg's drawtext draws a box", err)
        # The per-line route measures with drawtext's top_a/bottom_d and draws at y_align=baseline,
        # which FFmpeg has from 6.1; the shim only fakes the release, so the measuring ffmpeg is the
        # real one, and on the 5.1.1 job it cannot run what an 8.0.x build would.
        drawtext_help = subprocess.run(["ffmpeg", "-hide_banner", "-h", "filter=drawtext"],
                                       capture_output=True, text=True).stdout
        if "y_align" in drawtext_help:
            doc = json.loads(tool("overlay", self.src, "--text", "two\nlines", "--dry-run", "--json",
                                  "-o", self.out("nl_ov.mp4"), env=bad).stdout)
            self.assertNotIn("notes", doc)
            measure, draw = doc["commands"][0], doc["commands"][-1]
            self.assertIn("print(text_w", measure, "the lines are measured, even under --dry-run")
            self.assertEqual(draw.count("drawtext="), 4, "two lines, outlines then text")
            self.assertEqual(draw.count("y_align=baseline"), 4)
            self.assertNotIn("text_w", draw, "x/y carry the measured block size")
        doc = json.loads(tool("overlay", self.src, "--text", "two\nlines", "--dry-run", "--json",
                              "-o", self.out("nl_ov.mp4"), env=good).stdout)
        self.assertNotIn("notes", doc)
        self.assertEqual(len(doc["commands"]), 1)
        self.assertEqual(doc["commands"][0].count("drawtext="), 1)

    def test_fourth_review_p3_regressions(self):
        """Fourth review P3 items: render re-encoded a clip at speed 1.0 (#47); a brand's default
        caption.animate made --mode mux fail (#32); shell_quote left a newline bare (#54);
        --analyze-seconds had no ceiling for the in-memory PCM window (#65)."""
        self.assertEqual(_common.shell_quote("a\nb"), "'a\nb'")
        proj = self.out("speed1.json")
        proj.write_text(json.dumps({"output": str(self.out("speed1.mp4")), "clips": [{"src": str(self.src), "speed": 1.0}]}))
        doc = json.loads(tool("render", proj, "--dry-run", "--json").stdout)
        self.assertNotIn("fit.py", " ".join(map(str, doc["commands"])) + json.dumps(doc.get("stages", [])))
        brand = self.out("brand_anim.json"); brand.write_text(json.dumps({"caption": {"animate": "pop"}}))
        srt = self.out("mux.srt"); srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
        doc = json.loads(tool("caption", self.src, "--srt", srt, "--brand", brand, "--mode", "mux", "--dry-run", "--json", "-o", self.out("mux_out.mkv")).stdout)
        self.assertEqual(doc["status"], "completed")
        proc = tool("sync", self.src, self.src, "--analyze-seconds", "5000", "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def test_boundary_sweep_regressions(self):
        """Pins from the 561-run boundary sweep (2026-09-12). F1: two runs on one -o both said
        completed while one described the other's file -- a lock file next to the output refuses
        the second (a dead-pid lock is taken over). F2/F3: cut's re-encode and pad --start copied a
        subtitle track with stale timestamps -- dropped and reported. F7: render --dry-run planned
        a missing clip. F6: verify printed two JSON documents for a non-media input. F8: odd
        source dimensions failed 15 tools with "not divisible by 2" -- run() retries with an even
        scale. F9: redact's default blur radius failed on regions under 40 px. F10: color
        --correct/--lut tagged PQ pixels as BT.709 without a tone map. F19: loudness
        --measure-only --json was a bare dict. F12: an unwritable output directory is kind input."""
        # F1
        lock = self.out(".lock_victim.mp4.ffskill-lock"); lock.write_text(str(os.getpid()))
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--json", "-o", self.out("lock_victim.mp4"), check=False)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("another run is writing", doc["error"]["message"])
        lock.write_text("999999")
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "--json", "-o", self.out("lock_victim.mp4")).stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertFalse(lock.exists(), "the lock must be released after the run")
        # F2 / F3
        srt = self.out("sw.srt"); srt.write_text("1\n00:00:00,500 --> 00:00:01,000\na\n\n2\n00:00:02,000 --> 00:00:02,500\nb\n\n", encoding="utf-8")
        mkv = self.out("sw_in.mkv")
        ffmpeg("-i", self.src, "-i", srt, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt", mkv)
        doc = json.loads(tool("cut", mkv, "--start", "0.5", "--end", "1.5", "--accurate", "--fast", "--json", "-o", self.out("sw_cut.mkv")).stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        self.assertAlmostEqual(doc["probe"]["duration"], 1.0, delta=0.15)
        doc = json.loads(tool("pad", mkv, "--start", "1", "--fast", "--json", "-o", self.out("sw_pad.mkv")).stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        self.assertEqual(doc["probe"].get("subtitle_streams") or 0, 0)
        # F7
        proj = self.out("sw_missing.json"); proj.write_text(json.dumps({"output": str(self.out("sw_r.mp4")), "clips": [{"src": str(self.out("nope.mp4"))}]}))
        proc = tool("render", proj, "--dry-run", "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        # F6
        txt = self.out("notmedia.txt"); txt.write_text("x")
        proc = tool("verify", txt, "--quick", "--out", self.out("sw_v"), "--json", check=False)
        self.assertEqual(proc.stdout.count('"status"'), 1, proc.stdout[:300])
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "verification")
        # F8
        odd = self.out("odd.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=641x359:rate=30", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "2", "-pix_fmt", "yuv444p", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", odd)
        for name, extra in (("cut", ["--start", "0.5", "--end", "1.5", "--accurate"]), ("fit", ["--duration", "1"]), ("color", ["--correct", "--exposure", "0.2"]), ("overlay", ["--text", "hi"])):
            doc = json.loads(tool(name, odd, *extra, "--fast", "--json", "-o", self.out(f"odd_{name}.mp4")).stdout)
            self.assertEqual(doc["status"], "completed", name)
            self.assertEqual((doc["probe"]["video"]["width"] % 2, doc["probe"]["video"]["height"] % 2), (0, 0), name)
        # F9
        doc = json.loads(tool("redact", self.src, "--x", "10", "--y", "10", "--width", "30", "--height", "30", "--mode", "blur", "--fast", "--json", "-o", self.out("sw_red.mp4")).stdout)
        self.assertEqual(doc["status"], "completed")
        # F10
        hdr = self.out("sw_hdr.mp4")
        # the VUI colour tags must go through x265-params: newer builds (7.1 apt, 8.x brew/choco)
        # do not carry -color_trc & co. into the libx265 encoder, and the fixture came out SDR
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "1", "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc", "-tag:v", "hvc1", hdr)
        proc = tool("color", hdr, "--correct", "--exposure", "0.2", "--fast", "--json", "-o", self.out("sw_col.mp4"), check=False)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("--to-sdr", doc["error"]["message"])
        # F19
        doc = json.loads(tool("loudness", self.src, "--measure-only", "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertIn("input_i", doc["measured"])
        # F12 (permissions do not bind root)
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            ro = self.out("ro_dir"); ro.mkdir(exist_ok=True); ro.chmod(0o555)
            proc = tool("fit", self.src, "--aspect", "1:1", "--dry-run", "--json", "-o", ro / "x.mp4", check=False)
            self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def test_result_v2_preview_is_gone(self):
        """2.0: the result_v2 preview (#189, FFMPEG_SKILL_RESULT_V2=1 since 1.10.0) was withdrawn
        rather than promoted -- it placed a key in `metrics` or `details` by its value -- and the
        top-level keys are the one shape. The old environment variable adds nothing."""
        env = dict(os.environ, FFMPEG_SKILL_RESULT_V2="1")
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.out("v2_cut.mp4"), "--json", env=env).stdout)
        self.assertNotIn("result_v2", doc)
        for key in ("output", "probe", "commands", "verified", "verification", "expected_duration", "precision"):
            self.assertIn(key, doc)

    def test_eval6_followups(self):
        """Eval iteration 6: overlay --fade without --end fades in only; export measures the
        written file against the platform's loudness spec and says how to fix it; cut names the
        lossless alternative when the keyframe snap forced a re-encode."""
        doc = json.loads(tool("overlay", self.src, "--image", self.logo, "--fade", "0.5", "--dry-run", "--json", "-o", self.out("e6_ov.mp4")).stdout)
        self.assertIn("fade=t=in", doc["commands"][-1]); self.assertNotIn("fade=t=out", doc["commands"][-1])
        doc = json.loads(tool("overlay", self.src, "--image", self.logo, "--fade", "0.5", "--end", "4", "--dry-run", "--json", "-o", self.out("e6_ov2.mp4")).stdout)
        self.assertIn("fade=t=out:st=3.500", doc["commands"][-1])
        doc = json.loads(tool("export", self.src, "--preset", "x", "--fast", "--json", "-o", self.out("e6_x.mp4")).stdout)
        self.assertEqual((doc["loudness"]["target_lufs"], doc["loudness"]["ok"]), (-14, False), doc["loudness"])
        self.assertTrue(any("loudness.py -I -14 --tp -1" in n for n in doc["notes"]), doc.get("notes"))
        norm = self.out("e6_norm.mp4")
        tool("loudness", self.src, "-I", "-14", "--tp", "-1", "-o", norm)
        doc = json.loads(tool("export", norm, "--preset", "x", "--fast", "--json", "-o", self.out("e6_x2.mp4")).stdout)
        self.assertTrue(doc["loudness"]["ok"]); self.assertNotIn("notes", doc)
        doc = json.loads(tool("export", self.src, "--preset", "x", "--dry-run", "--json", "-o", self.out("e6_xd.mp4")).stdout)
        self.assertNotIn("loudness", doc)
        doc = json.loads(tool("cut", self.src, "--start", "2", "--end", "4", "--fast", "--json", "-o", self.out("e6_cut.mp4")).stdout)
        self.assertEqual(doc["mode"], "hybrid")
        self.assertIn("--start 0.000", doc["lossless_alternative"])
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "2", "--json", "-o", self.out("e6_cut0.mp4")).stdout)
        self.assertIsNone(doc["lossless_alternative"])

    def test_cut_names_the_lossless_alternative_in_matroska_and_mp4_keeps_its_edit_list(self):
        """.mkv has no edit list, so the copy snaps back to the keyframe at 0 and the lossless
        alternative is offered; an .mp4 copy that keeps its edit list (--edit-list) starts at 2 s
        losslessly."""
        doc = json.loads(tool("cut", self.src, "--start", "2", "--end", "4", "--fast", "--json", "-o", self.out("e6_cut.mkv")).stdout)
        self.assertEqual(doc["mode"], "hybrid")
        self.assertIn("--start 0.000", doc["lossless_alternative"])
        doc = json.loads(tool("cut", self.src, "--start", "2", "--end", "4", "--fast", "--edit-list", "--json",
                              "-o", self.out("e6_cut_el.mp4")).stdout)
        self.assertEqual(doc["mode"], "copy")
        self.assertTrue(doc["edit_list"])

    def test_verified_reports_what_the_tool_measured(self):
        """#189 C: every success document carries `verified` and `verification`. cut: probe and its streams;
        loudness: probe + its own after-write measurements (level, and since 2.20 length); export on a raw source: loudness step
        not ok -> verified false while status stays completed; --dry-run verified nothing."""
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.out("vf_cut.mp4"), "--json").stdout)
        self.assertEqual((doc["verified"], [(s["step"], s["ok"]) for s in doc["verification"]]), (True, [("probe", True), ("streams", True), ("stream_lengths", True), ("decode", True)]))
        doc = json.loads(tool("loudness", self.src, "-o", self.out("vf_loud.mp4"), "--json").stdout)
        self.assertTrue(doc["verified"]); self.assertEqual([s["step"] for s in doc["verification"]], ["probe", "loudness", "duration"])
        self.assertEqual(doc["verification"][1]["target_lufs"], -14)
        doc = json.loads(tool("export", self.src, "--preset", "x", "--fast", "-o", self.out("vf_x.mp4"), "--json").stdout)
        self.assertEqual((doc["status"], doc["verified"]), ("completed", False))
        self.assertEqual([(s["step"], s["ok"]) for s in doc["verification"]],
                         [("probe", True), ("loudness", False), ("duration", True), ("streams", True),
                          ("stream_lengths", True), ("decode", True)])
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.out("vf_dry.mp4"), "--dry-run", "--json").stdout)
        self.assertEqual((doc["verified"], doc["verification"]), (False, []))
        doc = json.loads(tool("report", "--after", self.src, "-o", self.out("vf_rep.html"), "--json").stdout)
        # the report file exists, and (since part 2 of "nothing happens silently") each section it
        # built is a step too, so a section that could not be built cannot hide behind verified
        self.assertTrue(doc["verified"]); self.assertEqual(doc["verification"][0], {"step": "exists", "ok": True})
        self.assertEqual([s["step"] for s in doc["verification"][1:]], ["loudness", "contact_sheet"])
        doc = json.loads(tool("look", self.src, "-o", self.out("vf_look.png"), "--json").stdout)
        self.assertEqual((doc["verified"], doc["verification"]), (True, [{"step": "probe", "ok": True}]))

    def test_sixth_review_regressions(self):
        """Review 6: loudness's verified reflects its target; --plan is written by tools that never
        call emit(); verify refuses --plan; a plan binds argv/side files; a plan's failed platform
        check is completed + verified false like the direct path; render refuses --plan; a
        non-object plan JSON is kind input."""
        import shutil
        doc = json.loads(tool("loudness", self.wav, "-I", "-5", "--tp", "-3", "-o", self.out("r6_loud.wav"), "--json").stdout)
        self.assertEqual((doc["status"], doc["verified"]), ("completed", False))
        self.assertFalse(doc["verification"][1]["ok"])
        plan = self.out("r6_probe.json")
        self.assertEqual(tool("probe", self.src, "--plan", plan).returncode, 0)
        self.assertEqual([i["path"] for i in json.loads(plan.read_text())["inputs"]], [str(self.src)])
        proc = tool("verify", self.src, "--quick", "--out", self.out("r6_v"), "--plan", self.out("r6_verify.json"), "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertFalse(self.out("r6_verify.json").exists())
        srt = self.out("r6.srt"); srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
        plan = self.out("r6_cap.json")
        tool("caption", self.src, "--srt", srt, "-o", self.out("r6_cap.mp4"), "--plan", plan)
        self.assertIn(str(srt), [i["path"] for i in json.loads(plan.read_text())["inputs"]])
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nchanged\n", encoding="utf-8")
        proc = tool("render", plan, "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        xplan = self.out("r6_x.json")
        tool("export", self.src, "--preset", "x", "--fast", "-o", self.out("r6_x.mp4"), "--plan", xplan)
        doc = json.loads(tool("render", xplan, "--json").stdout)
        self.assertEqual((doc["status"], doc["verified"]), ("completed", False))
        self.assertTrue(has_step(doc["verification"], {"step": "check", "ok": False, "platform": "x"}))
        proj = self.out("r6_proj.json"); proj.write_text(json.dumps({"output": str(self.out("r6_r.mp4")), "clips": [{"src": str(self.src)}]}))
        proc = tool("render", proj, "--plan", self.out("r6_rplan.json"), "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        bad = self.out("r6_bad.json"); bad.write_text("[1, 2]")
        proc = tool("render", bad, "--json", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def test_plan_roundtrip(self):
        """--plan writes a plan and runs nothing; render.py executes it, verifies, and refuses when
        an input changed since the plan (issue #189 C)."""
        import shutil
        src = self.out("plan_src.mp4"); shutil.copy(self.src, src)
        plan = self.out("plan_cut.json"); out = self.out("plan_cut.mp4")
        doc = json.loads(tool("cut", src, "--start", "0", "--end", "1", "-o", out, "--plan", plan, "--json").stdout)
        self.assertTrue(doc["dry_run"]); self.assertEqual(doc["plan"], str(plan)); self.assertFalse(out.exists())
        p = json.loads(plan.read_text())
        self.assertEqual((p["plan_version"], p["tool"], p["output"]), (1, "cut", str(out)))
        self.assertEqual([i["path"] for i in p["inputs"]], [str(src)])
        self.assertNotIn("--plan", p["argv"]); self.assertNotIn("--json", p["argv"]); self.assertNotIn("--dry-run", p["argv"])
        self.assertEqual(p["verify"], [{"tool": "probe"}])
        doc = json.loads(tool("render", plan, "--dry-run", "--json").stdout)
        self.assertTrue(doc["dry_run"]); self.assertFalse(out.exists())
        doc = json.loads(tool("render", plan, "--json").stdout)
        self.assertEqual((doc["status"], doc["tool"], doc["output"]), ("completed", "cut", str(out)))
        # a lossless cut lands on packet boundaries: FFmpeg 5.1.1 writes 1.23 s for this 1 s request
        self.assertTrue(0.9 <= doc["probe"]["duration"] <= 1.6, doc["probe"]["duration"])
        self.assertEqual(doc["tool_result"]["status"], "completed")
        # an export plan carries the platform check and runs it
        xplan = self.out("plan_x.json"); xout = self.out("plan_x.mp4")
        tool("export", src, "--preset", "x", "--fast", "-o", xout, "--plan", xplan)
        self.assertEqual(json.loads(xplan.read_text())["verify"], [{"tool": "probe"}, {"tool": "check", "platform": "x"}])
        doc = json.loads(tool("render", xplan, "--json", check=False).stdout)
        self.assertIn(doc["status"], ("completed", "failed"))
        self.assertEqual(doc["check"]["platform"], "x")
        # a check step with "content": true runs check.py --content (same key as a project's check stage)
        cp = json.loads(plan.read_text()); cp["verify"].append({"tool": "check", "content": True})
        cplan = self.out("plan_content.json"); cplan.write_text(json.dumps(cp))
        doc = json.loads(tool("render", cplan, "--json", "--overwrite", check=False).stdout)
        self.assertEqual(doc["stages"], ["cut", "check"])
        self.assertTrue({"black", "frozen"} & {r["check"].split()[0].lower() for r in doc["check"]["checks"]}, doc["check"]["checks"])
        # a changed input is refused
        ffmpeg("-i", self.src, "-t", "0.5", "-c", "copy", "-y", src)
        proc = tool("render", plan, "--json", "--overwrite", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("changed", json.loads(proc.stdout)["error"]["message"])

    def test_a_refused_plan_says_what_changed_and_leaves_an_audit_record(self):
        """docs/design-decisions.md, "Nothing happens silently": a refused plan named the changed
        input only in prose. The refusal now carries error.reason plan_inputs_changed and
        error.details (each input's expected and actual size + head/tail hash, or "missing"; the
        plan's sha256; when it was checked) and appends one JSON line to <plan>.audit.jsonl, or to
        --audit-log FILE. A log that cannot be written is a warning, never the failure."""
        import hashlib
        src = self.out("aud_src.mp4"); shutil.copy(self.src, src)
        plan = self.out("aud_plan.json"); out = self.out("aud_out.mp4")
        tool("cut", src, "--start", "0", "--end", "1", "-o", out, "--plan", plan)
        p = json.loads(plan.read_text())
        self.assertEqual(p["unbound_inputs"], [])
        ffmpeg("-i", self.src, "-t", "0.5", "-c", "copy", "-y", src)
        log = Path(str(plan) + ".audit.jsonl")
        # a dry run predicts the refusal and writes nothing, the audit log included
        doc = json.loads(tool("render", plan, "--dry-run", "--json", check=False).stdout)
        self.assertEqual(doc["error"]["reason"], "plan_inputs_changed")
        self.assertEqual(doc["error"]["details"]["audit_log"], {"path": str(log), "written": False, "reason": "dry_run"})
        self.assertFalse(log.exists())
        proc = tool("render", plan, "--json", check=False)
        err = json.loads(proc.stdout)["error"]
        self.assertEqual((err["kind"], err["reason"]), ("input", "plan_inputs_changed"))
        self.assertIn("changed", err["message"])
        d = err["details"]
        self.assertEqual(d["plan_sha256"], hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertRegex(d["checked_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        row = d["inputs"][0]
        self.assertEqual((row["path"], row["status"]), (str(src), "changed"))
        self.assertEqual(row["expected"], {"size": p["inputs"][0]["size"], "sha256_head_tail": p["inputs"][0]["sha256_head_tail"]})
        self.assertEqual(row["actual"]["size"], src.stat().st_size)
        self.assertNotEqual(row["actual"]["sha256_head_tail"], row["expected"]["sha256_head_tail"])
        self.assertEqual(d["audit_log"], {"path": str(log), "written": True})
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((rec["event"], rec["tool"], rec["plan_sha256"]), ("plan_rejected", "render", d["plan_sha256"]))
        self.assertEqual(rec["details"]["inputs"], d["inputs"])
        self.assertTrue(rec["ts"].endswith("Z"))
        # a missing input: actual "missing"; --audit-log names another file
        src.unlink()
        other = self.out("aud_other.jsonl")
        err = json.loads(tool("render", plan, "--json", "--audit-log", other, check=False).stdout)["error"]
        self.assertEqual((err["details"]["inputs"][0]["status"], err["details"]["inputs"][0]["actual"]), ("missing", "missing"))
        self.assertEqual(json.loads(other.read_text(encoding="utf-8"))["event"], "plan_rejected")
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 1, "--audit-log replaced the default")
        # an audit log that cannot be written: recorded, and the refusal is still the refusal
        doc = json.loads(tool("render", plan, "--json", "--audit-log", self.work / "no_such_dir" / "a.jsonl", check=False).stdout)
        self.assertEqual(doc["error"]["reason"], "plan_inputs_changed")
        self.assertFalse(doc["error"]["details"]["audit_log"]["written"])
        self.assertEqual([w["code"] for w in doc["diagnostics"]["warnings"]], ["audit_log_unwritable"])
        # the neighbours are structured too
        bad = self.out("aud_v2.json"); bad.write_text(json.dumps(dict(p, plan_version=99)))
        err = json.loads(tool("render", bad, "--json", check=False).stdout)["error"]
        self.assertEqual((err["reason"], err["details"]["plan_version"]), ("plan_version_unsupported", 99))
        bad.write_text(json.dumps(dict(p, tool="nope")))
        self.assertEqual(json.loads(tool("render", bad, "--json", check=False).stdout)["error"]["reason"], "plan_unknown_tool")

    def test_a_plan_names_the_inputs_it_could_not_bind_and_render_reports_them(self):
        """_plan_inputs() skips an input that does not exist yet (an earlier step's output), so
        nothing fingerprinted it and nothing said so. The plan now lists it under unbound_inputs
        and render.py reports it on execution: a top-level unbound_inputs and a
        diagnostics.warnings entry."""
        a = self.out("ub_a.mp4"); shutil.copy(self.src, a)
        pending = self.out("ub_pending.mp4")
        if pending.exists():
            pending.unlink()
        plan = self.out("ub_plan.json"); out = self.out("ub_out.mp4")
        tool("join", a, pending, "--transition", "none", "-o", out, "--plan", plan)
        p = json.loads(plan.read_text())
        self.assertEqual(p["unbound_inputs"], [str(pending)])
        self.assertEqual([i["path"] for i in p["inputs"]], [str(a)])
        shutil.copy(self.src, pending)
        doc = json.loads(tool("render", plan, "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["unbound_inputs"], [str(pending)])
        warning = doc["diagnostics"]["warnings"][0]
        self.assertEqual((warning["code"], warning["paths"]), ("plan_unbound_inputs", [str(pending)]))

    def test_refusals_at_the_runner_choke_points_carry_a_reason_and_details(self):
        """The runner's guards refused in prose only. Each now names error.reason and the facts in
        error.details; render.py executing a plan forwards its tool's reason and details."""
        out = self.out("rf_exists.mp4"); out.write_bytes(b"theirs")
        err = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", out, "--json", check=False).stdout)["error"]
        self.assertEqual(err["reason"], "output_exists")
        self.assertEqual(err["details"]["outputs"][0]["path"], str(out))
        self.assertEqual(err["details"]["outputs"][0]["size"], 6)
        clone = self.out("rf_same.mp4"); shutil.copy(self.src, clone)
        err = json.loads(tool("crop", clone, "--x", "0", "--y", "0", "--width", "32", "--height", "32", "--json",
                              "-o", self.work / ("." + os.sep + clone.name), check=False).stdout)["error"]
        self.assertEqual((err["reason"], err["details"]["resolved"]), ("output_is_input", os.path.realpath(clone)))
        err = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.work / "nodir" / "x.mp4", "--json", check=False).stdout)["error"]
        self.assertEqual((err["reason"], err["details"]["directory"]), ("output_dir_missing", str(self.work / "nodir")))
        err = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.work, "--json", check=False).stdout)["error"]
        self.assertEqual(err["reason"], "output_is_directory")
        # a plan whose output now exists: render re-raises the tool's own structured refusal
        plan = self.out("rf_plan.json"); pout = self.out("rf_plan_out.mp4")
        tool("cut", self.src, "--start", "0", "--end", "1", "-o", pout, "--plan", plan)
        pout.write_bytes(b"theirs")
        err = json.loads(tool("render", plan, "--json", check=False).stdout)["error"]
        self.assertEqual((err["kind"], err["reason"]), ("input", "output_exists"))
        self.assertEqual(err["details"]["outputs"][0]["path"], str(pout))

    def test_a_stale_lock_taken_over_is_recorded_in_the_document_and_the_audit_log(self):
        """A dead writer's lock was taken over without a word. The run now records it
        (diagnostics.fallbacks, stderr) and appends a lock_takeover line to the hidden
        .<output>.ffskill-audit.jsonl; render.py carries a stage's record with its stage name."""
        out = self.out("lk_out.mp4")
        lock = self.out(".lk_out.mp4.ffskill-lock"); lock.write_text("999999")
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "-o", out, "--json")
        doc = json.loads(proc.stdout)
        fb = doc["diagnostics"]["fallbacks"][0]
        self.assertEqual((fb["code"], fb["why"], fb["pid"], fb["pid_alive"]), ("stale_lock_taken_over", "pid_dead", 999999, False))
        self.assertIn("took over the stale output lock", proc.stderr)
        rec = json.loads(self.out(".lk_out.mp4.ffskill-audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((rec["event"], rec["tool"], rec["details"]["pid"]), ("lock_takeover", "cut", 999999))
        # through render executing a plan: the stage's record comes back tagged
        plan = self.out("lk_plan.json"); pout = self.out("lk_plan_out.mp4")
        tool("cut", self.src, "--start", "0", "--end", "1", "-o", pout, "--plan", plan)
        self.out(".lk_plan_out.mp4.ffskill-lock").write_text("999999")
        doc = json.loads(tool("render", plan, "--json").stdout)
        fb = doc["diagnostics"]["fallbacks"][0]
        self.assertEqual((fb["code"], fb["stage"]), ("stale_lock_taken_over", "cut"))
        for name in (".lk_out.mp4.ffskill-audit.jsonl", ".lk_plan_out.mp4.ffskill-audit.jsonl"):
            self.out(name).unlink()

    def test_fifth_review_regressions(self):
        """Review 5 (2026-09-12): render refuses an output that is one of its clip sources (it
        overwrote the source and said completed); fit --method trim drops a subtitle track whose
        cues would sit at the source's times (the output came out double length); multicam
        --audio out of range is kind input, not an IndexError; check's fix for a broadcast codec
        failure names a preset that exists; sequence.py has its docstring back."""
        import shutil
        src_copy = self.out("r5_src.mp4"); shutil.copy(self.src, src_copy)
        proj = self.out("r5_proj.json")
        proj.write_text(json.dumps({"output": str(src_copy), "clips": [{"src": str(src_copy), "in": 0, "out": 1}]}))
        before = src_copy.stat().st_size
        proc = tool("render", proj, "--json", "--fast", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertEqual(src_copy.stat().st_size, before, "render must not touch its own source")
        doc = json.loads(tool("fit", self.subbed, "--duration", "2", "--method", "trim", "--from-center", "--fast", "--json", "-o", self.out("r5_trim.mkv")).stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        self.assertAlmostEqual(doc["probe"]["duration"], 2.0, delta=0.15)
        proc = tool("multicam", self.src, self.camb, "--audio", "5", "--switch", "0-1:0", "--dry-run", "--json", "-o", self.out("r5_mc.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        m4 = self.out("r5_mpeg4.mp4")
        ffmpeg("-i", self.src, "-t", "1", "-c:v", "mpeg4", "-c:a", "copy", m4)
        doc = json.loads(tool("check", m4, "--platform", "broadcast", "--no-loudness", "--json", check=False).stdout)
        fix = next(c["fix"] for c in doc["checks"] if c["check"] == "video codec")
        self.assertIn("--preset prores", fix)
        self.assertTrue(self.tools["sequence"]["description"], "sequence.py's docstring must reach the contract")
        with open(ROOT / "scripts" / "sequence.py", encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("#!"))

    def test_settled_policies_exit_code_and_subtitle_tracks(self):
        """docs/design-decisions.md: an ffmpeg failure exits 1 whatever ffmpeg returned (the raw code
        travels as ffmpeg_returncode); tools that leave the timeline alone keep a subtitle track
        (audio/loudness/proxy joined fit/color/overlay), tools that move it say so."""
        bad = self.out("policy_bad.cube")
        bad.write_text('TITLE "x"\nLUT_3D_SIZE 2\ngarbage\n')
        proc = tool("color", self.src, "--lut", bad, "--json", "-o", self.out("policy_lut.mp4"), check=False)
        self.assertEqual(proc.returncode, 1, proc.stderr[-300:])
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"], doc["exit_code"]), ("failed", "ffmpeg", 1))
        self.assertIsInstance(doc["ffmpeg_returncode"], int)
        self.assertNotEqual(doc["ffmpeg_returncode"], 0)
        keep = [
            ("audio", [self.subbed, "--gain", "3", "-o", self.out("policy_audio.mkv"), "--json"]),
            ("loudness", [self.subbed, "-o", self.out("policy_loud.mkv"), "--json"]),
            ("proxy", [self.subbed, "--width", "160", "-o", self.out("policy_proxy.mkv"), "--json"]),
        ]
        for name, args in keep:
            doc = json.loads(tool(name, *args).stdout)
            self.assertFalse(doc["dropped_non_av_streams"], name)
            kinds = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", doc["output"]).stdout.split()
            self.assertEqual(kinds.count("subtitle"), 2, f"{name}: expected both source subtitle tracks, got {kinds}")
        drop = [
            ("join", [self.subbed, self.subbed, "--duration", "0.3", "-o", self.out("policy_join.mp4"), "--json"]),
            ("broll", [self.subbed, "--insert", self.src, "--at", "1", "--duration", "1", "-o", self.out("policy_broll.mp4"), "--json"]),
            ("speedramp", [self.subbed, "--segment", "0-3:2", "--segment", "3-6:1", "-o", self.out("policy_ramp.mp4"), "--json"]),
        ]
        for name, args in drop:
            doc = json.loads(tool(name, *args, "--fast").stdout)
            self.assertTrue(doc["dropped_non_av_streams"], name)
            self.assertEqual(doc["probe"]["subtitle_streams"], 0, name)
        # a plain source reports false, so the key is a fact and not a constant
        doc = json.loads(tool("speedramp", self.src, "--segment", "0-6:2", "-o", self.out("policy_ramp_plain.mp4"), "--json", "--fast").stdout)
        self.assertFalse(doc["dropped_non_av_streams"])

    def test_look_sheet_timecode_counts_from_the_seek(self):
        """A contact sheet starts reading at half a slice (-ss before -i), which resets pts to 0 at
        the seek point: the burned-in labels were half a slice early (8 s, 3x2: a tile showing
        0.667 s labelled 0.000). The timecode now adds the seek back; a sheet that starts at 0
        (a clip with only a handful of frames) keeps the plain pts."""
        doc = json.loads(tool("look", self.src, "--tiles", "3x2", "--dry-run", "--json",
                              "-o", self.out("tc_sheet.png")).stdout)
        cmd = doc["commands"][0]
        seek = re.search(r"-ss (\d+\.\d+) ", cmd).group(1)
        self.assertGreater(float(seek), 0)
        self.assertIn(f"pts\\:hms\\:{seek}", cmd)
        one = self.out("tc_one_frame.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-frames:v", "1", "-c:v", "libx264",
               "-preset", "veryfast", "-pix_fmt", "yuv420p", one)
        cmd = json.loads(tool("look", one, "--tiles", "2x2", "--dry-run", "--json",
                              "-o", self.out("tc_one.png")).stdout)["commands"][0]
        self.assertIn("-ss 0.000000 ", cmd)
        self.assertIn("pts\\:hms}", cmd)

    def test_boundary_sweep_p3_regressions(self):
        """Sweep P3s: export's HDR warning reaches --json (F11); graphics refuses a frame too small
        for its templates (F16); insert refuses a video where it wants a still (F17); look builds
        a sheet from a one-frame clip instead of printing "wrote" and then failing (F18); batch
        --dry-run leaves no directories behind and render removes its auto work dir on failure (F15)."""
        one = self.out("one_frame.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-frames:v", "1", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", one)
        doc = json.loads(tool("look", one, "--tiles", "2x2", "--width", "200", "--json", "-o", self.out("one_sheet.png")).stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertTrue(self.out("one_sheet.png").exists())
        tiny = self.out("tiny16.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=16x16:rate=30", "-t", "1", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", tiny)
        proc = tool("graphics", tiny, "--template", "lower-third", "--name", "x", "--fast", "--json", "-o", self.out("tiny_g.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        proc = tool("insert", self.src, "--duration", "1", "--width", "64", "--height", "64", "--fast", "--json", "-o", self.out("ins_vid.mp4"), check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        hdr = self.out("p3_hdr.mp4")
        # the VUI colour tags must go through x265-params: newer builds (7.1 apt, 8.x brew/choco)
        # do not carry -color_trc & co. into the libx265 encoder, and the fixture came out SDR
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "1", "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc", "-tag:v", "hvc1", hdr)
        doc = json.loads(tool("export", hdr, "--preset", "youtube", "--fast", "--json", "-o", self.out("p3_ex.mp4")).stdout)
        self.assertTrue(any("HDR" in n for n in doc.get("notes", [])), doc.keys())
        bdir = self.out("p3_batch"); bdir.mkdir(exist_ok=True); shutil.copyfile(self.src, bdir / "clip.mp4")
        recipe = self.out("p3_recipe.json"); recipe.write_text(json.dumps({"glob": "*.mp4", "steps": [["fit.py", "{in}", "--aspect", "1:1", "-o", "{out}"]]}))
        doc = json.loads(tool("batch", bdir, "--recipe", recipe, "--dry-run", "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertFalse((bdir / "out").exists(), "batch --dry-run left its output directory behind")
        proj = self.out("p3_missing.json"); proj.write_text(json.dumps({"output": str(self.out("p3_r.mp4")), "clips": [{"src": str(self.out("nope.mp4"))}]}))
        tool("render", proj, "--json", check=False)
        self.assertEqual([p.name for p in self.work.glob("p3_r_work_*")], [], "render left its work dir after a failure")

    def test_cut_segments_refuses_output_equal_to_input(self):
        """Fourth review, P0: `cut.py in.mp4 --segments 0-1,2-3 -o in.mp4` replaced the source
        with the 2 s join. The run() guard compares the ffmpeg command's -i paths with its output,
        and the final concat command's only -i is the temp list file, so it never fired; the
        single-segment path (whose -i is the input) refused correctly. Pin the tool-level guard
        with both spellings of the same file, and that the source is untouched."""
        victim = self.out("victim_segments.mp4")
        shutil.copyfile(self.src, victim)
        before = victim.read_bytes()
        for spelling in (str(victim), os.path.join(str(victim.parent), ".", victim.name)):
            proc = tool("cut", victim, "--segments", "0-1,2-3", "--json", "-o", spelling, check=False)
            self.assertNotEqual(proc.returncode, 0, spelling)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(doc["error"]["kind"], "input")
            self.assertIn("same file as input", doc["error"]["message"])
        self.assertEqual(victim.read_bytes(), before, "the source was modified")

    def test_failed_run_never_deletes_an_output_that_predates_it(self):
        """The partial-output cleanup (#78) removed the output path after every failed ffmpeg run
        without asking whether the file had been there before: a bad filter argument aimed at an
        existing deliverable deleted the deliverable. And on FFmpeg 5.x the cleanup was not even
        needed for that: -y truncates the output during option parsing, before the filter graph
        is initialised, so the same bad LUT left a 0-byte file by itself (6.1+ initialises
        filters first). An existing output is therefore written through a hidden sibling temp
        file and replaced only on success -- with or without --overwrite (consent to replace is
        not consent to lose the file on failure); no temp file survives a failure; a fresh path
        the failed run created is still cleaned up."""
        keep = self.out("deliverable.mp4")
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "1", "-o", keep).returncode, 0)
        before = (keep.stat().st_size, keep.stat().st_mtime_ns)
        bad = self.out("bad.cube")
        bad.write_text('TITLE "x"\nLUT_3D_SIZE 2\ngarbage\n')
        # without --overwrite 2.0 refuses before ffmpeg runs; with it, ffmpeg fails on the LUT
        for extra, kind in (((), "input"), (("--overwrite",), "ffmpeg")):
            proc = tool("color", self.src, "--lut", bad, "--json", "-o", keep, *extra, check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)["error"]["kind"], kind)
            self.assertTrue(keep.exists(), f"failed run deleted a pre-existing output ({extra})")
            self.assertEqual((keep.stat().st_size, keep.stat().st_mtime_ns), before, "pre-existing output was modified")
            # a lock takeover's audit log (another test's) is a deliberate record, not a temp file
            self.assertEqual([p.name for p in keep.parent.glob(".*ffskill*") if not p.name.endswith(".ffskill-audit.jsonl")], [],
                             "temp file left behind after a failure")
        # success replaces the file, through the same temp path, and leaves no temp behind
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "2", "--overwrite", "-o", keep).returncode, 0)
        self.assertNotEqual(keep.stat().st_size, before[0])
        self.assertEqual([p.name for p in keep.parent.glob(".*ffskill*") if not p.name.endswith(".ffskill-audit.jsonl")], [])
        # a fresh path that the failed run created is still cleaned up
        fresh = self.out("fresh.mp4")
        proc = tool("color", self.src, "--lut", bad, "--json", "-o", fresh, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(fresh.exists())

    @unittest.skipIf(platform.system() == "Windows", "the hung ffmpeg is a #!/bin/sh shim on a POSIX-only PATH; the deadline logic itself is platform-neutral")
    def test_timeout_is_enforced_under_progress_when_ffmpeg_prints_nothing(self):
        """--progress read ffmpeg's progress pipe line by line and only compared the clock when a
        line arrived, so the exact case --timeout exists for -- a deadlocked ffmpeg that prints
        nothing -- waited forever. A shell shim standing in for ffmpeg that sleeps silently and
        then fails reproduces it in seconds: with the limit at 1 s the run must end as kind
        timeout well before the shim's own sleep would have returned."""
        shim = self.out("hang_shim")
        shim.mkdir()
        (shim / "ffmpeg").write_text("#!/bin/sh\nsleep 8\nexit 1\n")
        (shim / "ffmpeg").chmod(0o755)
        (shim / "ffprobe").symlink_to(shutil.which("ffprobe"))
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
        t0 = time.time()
        proc = tool("fit", self.src, "--aspect", "9:16", "--progress", "--timeout", "1", "--json",
                    "-o", self.out("hang.mp4"), env=env, check=False)
        elapsed = time.time() - t0
        self.assertEqual(proc.returncode, 124, proc.stderr[-300:])
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "timeout")
        self.assertLess(elapsed, 6, f"--progress waited {elapsed:.1f}s on a silent ffmpeg; the limit was 1 s")

    @unittest.skipIf(platform.system() == "Windows", "the failing ffmpeg is a #!/bin/sh shim on a POSIX-only PATH")
    def test_analysis_tools_report_an_ffmpeg_failure_instead_of_an_empty_result(self):
        """scenes.py and cropdetect.py ran their ffmpeg measurement with a bare subprocess.run and
        never looked at the return code: a file ffprobe accepts but ffmpeg cannot decode came back
        as "0 scenes" / "crop: none" with exit 0. The measurement now goes through run_analysis(),
        which applies --timeout and turns a non-zero exit into kind ffmpeg. An ffmpeg shim that
        fails on every call (ffprobe stays real, so probe() passes) reproduces the decode failure."""
        shim = self.out("fail_shim")
        shim.mkdir()
        (shim / "ffmpeg").write_text("#!/bin/sh\necho 'decode error' >&2\nexit 1\n")
        (shim / "ffmpeg").chmod(0o755)
        (shim / "ffprobe").symlink_to(shutil.which("ffprobe"))
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
        for name, args in (("scenes", ()), ("cropdetect", ())):
            proc = tool(name, self.src, *args, "--json", env=env, check=False)
            self.assertNotEqual(proc.returncode, 0, f"{name} exited 0 over a failing ffmpeg")
            doc = json.loads(proc.stdout)
            self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "ffmpeg"), name)
            self.assertIn("decode error", doc["error"]["message"], name)

    def test_existing_output_is_refused_without_overwrite_and_never_for_its_own_files(self):
        """Every ffmpeg command carries -y (so a run never blocks on a y/N prompt), which meant an
        output path that already existed -- a previous deliverable, a mis-named source -- was
        replaced without a word. 1.x warned (FFMPEG_SKILL_NO_OVERWRITE=1 opted into refusing);
        2.0 refuses, kind input, before any ffmpeg runs, dry runs included. --overwrite is the
        explicit consent; a path this same run wrote (two-pass tools, copy-then-re-encode
        fallbacks) is never treated as someone else's file."""
        out = self.out("exists.mp4")
        if out.exists():
            out.unlink()
        first = tool("cut", self.src, "--start", "0", "--end", "1", "-o", out)
        self.assertNotIn("refusing", first.stderr, "a fresh path is not refused")
        size_before = out.stat().st_size
        proc = tool("cut", self.src, "--start", "0", "--end", "2", "--json", "-o", out, check=False)
        self.assertEqual(proc.returncode, 1)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("refusing to overwrite", doc["error"]["message"])
        self.assertIn("--overwrite", doc["error"]["hint"])
        self.assertEqual(doc["commands"], [], "refused before any ffmpeg ran")
        self.assertEqual(out.stat().st_size, size_before, "the existing file is untouched")
        dry = tool("cut", self.src, "--start", "0", "--end", "2", "--dry-run", "-o", out, check=False)
        self.assertEqual(dry.returncode, 1, "a dry run says the real run would be refused")
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "2", "--overwrite", "-o", out).returncode, 0)
        self.assertNotEqual(out.stat().st_size, size_before, "--overwrite replaced the file")
        # the old opt-in variable changes nothing either way
        env = dict(os.environ, FFMPEG_SKILL_NO_OVERWRITE="0")
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "1", "-o", out, env=env, check=False).returncode, 1)

    def _fails(self, name, *args, kind=None, code=None):
        proc = tool(name, *args, "--json", check=False)
        self.assertNotEqual(proc.returncode, 0, f"{name} {args}: exit 0 on a failure")
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "failed", name)
        # kind="ffmpeg" means the real ffmpeg subprocess itself failed, not our own die() -- on at
        # least one Windows build, an abnormally-terminated ffmpeg (corrupt LUT input, a target
        # directory that doesn't exist) reports a wraparound-looking exit code to the OS that does
        # not exactly match what we captured and reported in the JSON. The failure itself (status
        # "failed", the reported kind, the message, a non-zero exit) is still verified either way;
        # only the exact numeric equality between doc["exit_code"] and the OS-observed exit code
        # is not something ffmpeg's own crash behaviour on that platform guarantees bit-for-bit.
        if kind == "ffmpeg" and platform.system() == "Windows":
            self.assertNotEqual(doc["exit_code"], 0)
        else:
            self.assertEqual(doc["exit_code"], proc.returncode)
        self.assertIn("commands", doc)
        self.assertTrue(doc["error"]["message"], name)
        if kind:
            self.assertEqual(doc["error"]["kind"], kind, f"{name}: {doc['error']}")
        # "code"/"retryable" are additive to "kind" (Hardening Phase 2): a static, honest
        # relabelling of the same 4 kinds, not a new taxonomy the code can't actually back up --
        # see _common.ERROR_CODE. Every failure carries both; retryable is always False today
        # since no kind is distinguishable from a deterministic content-cause failure without
        # exit-code/stderr sniffing this codebase doesn't do.
        import _common
        self.assertIn("code", doc["error"], f"{name}: {doc['error']}")
        self.assertEqual(doc["error"]["code"], _common.ERROR_CODE.get(doc["error"]["kind"], "INTERNAL_ERROR"))
        self.assertEqual(doc["error"]["retryable"], False, f"{name}: {doc['error']}")
        if code:
            self.assertEqual(proc.returncode, code)
        self.assertIn("error:", proc.stderr)
        return doc

    def test_input_failures_are_loud(self):
        missing = self.work / "does_not_exist.mp4"
        self._fails("cut", missing, "--start", "1", "--end", "2", "-o", self.out("f1.mp4"), kind="input")
        self._fails("cut", self.garbage, "--start", "1", "--end", "2", "-o", self.out("f2.mp4"), kind="input")
        self._fails("cut", self.empty, "--start", "1", "--end", "2", "-o", self.out("f3.mp4"), kind="input")
        self._fails("probe", self.garbage, kind="input")
        self._fails("loudness", self.garbage, "-o", self.out("f4.wav"), kind="input")
        self._fails("audio", self.wav, "--replace", missing, "-o", self.out("f5.wav"), kind="input")
        self._fails("export", self.wav, "--preset", "youtube", "-o", self.out("f6.mp4"), kind="input")  # no video stream
        self._fails("cut", self.src, "--start", "20", "--end", "30", "-o", self.out("f7.mp4"), kind="input")  # beyond duration
        self._fails("fit", self.src, "--duration", "3", "--fps", "0", "-o", self.out("f8.mp4"), kind="input")
        self.assertEqual(sorted(p.name for p in self.work.glob("f[0-9].*")), [], "no partial outputs left behind")

    def test_output_path_resolving_to_the_same_file_as_input_is_refused(self):
        """A byte-different but same-file output path ("./x.mp4" for an input opened as "x.mp4",
        or an absolute/relative pair) is not caught by ffmpeg's own "Output same as Input" guard,
        which only compares path strings. Without our own realpath check, "-o ./same.mp4" would
        silently let ffmpeg's -y clobber the source mid-encode (Hardening Phase 2 P0)."""
        clone = self.out("clobber_src.mp4")
        shutil.copyfile(self.src, clone)
        before = self._sha(clone)
        same_but_different_string = self.work / ("." + os.sep + clone.name)
        doc = self._fails("crop", clone, "--x", "0", "--y", "0", "--width", "32", "--height", "32",
                           "-o", same_but_different_string, kind="input")
        self.assertIn("same file", doc["error"]["message"])
        self.assertEqual(self._sha(clone), before, "input must be byte-identical after the refusal")

    def test_ffmpeg_failures_are_loud(self):
        doc = self._fails("color", self.src, "--lut", self.badlut, "--fast", "-o", self.out("g1.mp4"), kind="ffmpeg")
        self.assertTrue(any("ffmpeg" in c for c in doc["commands"]), "the failing command is reported")
        # a missing output directory is the caller's mistake, refused before ffmpeg runs (kind input
        # since 1.4.10; it used to surface as the muxer's ENOENT, kind ffmpeg)
        self._fails("loudness", self.wav, "-o", self.work / "no_such_dir" / "g2.wav", kind="input")
        self._fails("cut", self.src, "--start", "1", "--end", "3", "-o", self.out("g3.txt"))  # unknown container
        self.assertFalse(self.out("g1.mp4").exists())

    @unittest.skipIf(platform.system() == "Windows", "the fake ffmpeg is a #!/bin/sh script on a POSIX-only PATH shim; "
                      "not portable to Windows (see the identical rationale on the shim-based tests above).")
    def test_ffmpeg_failure_after_opening_the_output_leaves_nothing_behind(self):
        """A bad filter argument or missing input never lets ffmpeg touch the output path at all
        (test_ffmpeg_failures_are_loud above), but a real mid-encode failure can happen AFTER
        ffmpeg has already opened/written to the output (a muxer header, a partial frame) --
        different timing, same die(kind="ffmpeg") outcome. Before the fix this left a stray file
        behind, since verify_output()'s cleanup only ran on the success path. A fake ffmpeg here
        writes bytes to the output and THEN exits non-zero, simulating that timing."""
        shim = self.work / "shim_partial"
        shim.mkdir(exist_ok=True)
        (shim / "ffmpeg").write_text("#!/bin/sh\nfor last; do :; done\ncase \"$last\" in -|*null*) exit 1;; esac\n"
                                      "printf 'partial-mp4-bytes' > \"$last\"\necho 'mid-encode failure' >&2\nexit 1\n")
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        out = self.out("g_partial.mp4")
        proc = tool("cut", self.src, "--start", "1", "--end", "3", "--accurate", "-o", out, "--json", env=env, check=False)
        self.assertNotEqual(proc.returncode, 0)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "failed")
        self.assertEqual(doc["error"]["kind"], "ffmpeg")
        self.assertFalse(out.exists(), "a partial file ffmpeg wrote before failing must not be left behind")

    @unittest.skipIf(platform.system() == "Windows", "the fake ffmpeg is a #!/bin/sh script on a POSIX-only PATH shim; "
                      "not portable to Windows (see the identical rationale on the shim-based tests above).")
    def test_output_verification_failures_are_loud(self):
        """A fake ffmpeg that exits 0 but writes an empty file: every writing tool must still fail."""
        shim = self.work / "shim0"
        shim.mkdir(exist_ok=True)
        (shim / "ffmpeg").write_text("#!/bin/sh\nfor last; do :; done\ncase \"$last\" in -|*null*) exit 0;; esac\n: > \"$last\"\nexit 0\n")
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        cases = {
            "cut": [self.src, "--start", "1", "--end", "3", "--accurate", "-o", self.out("v_cut.mp4")],
            "audio": [self.wav, "-o", self.out("v_au.mp3")],
            "silence": [self.src, "-o", self.out("v_sil.mp4")],
            "fit": [self.src, "--duration", "3", "-o", self.out("v_fit.mp4")],
            "export": [self.src, "--preset", "x", "-o", self.out("v_exp.mp4")],
            "caption": [self.src, "--text", self.cues, "-o", self.out("v_cap.mp4")],
            "overlay": [self.src, "--image", self.logo, "-o", self.out("v_ov.mp4")],
            "color": [self.hdr, "--to-sdr", "-o", self.out("v_col.mp4")],
            "look": [self.src, "-o", self.out("v_look.png")],
        }
        for name, args in cases.items():
            proc = tool(name, *args, "--json", env=env, check=False)
            self.assertNotEqual(proc.returncode, 0, f"{name}: exit 0 with an unusable output")
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "failed", name)
            self.assertEqual(doc["error"]["kind"], "output", f"{name}: {doc['error']}")
            self.assertIn("output verification failed", doc["error"]["message"])
            self.assertNotIn("probe", doc)
            self.assertFalse(Path(args[-1]).exists(), f"{name}: empty output left behind")
        # the same path with the real ffmpeg succeeds and carries a probe of the output
        doc = json.loads(tool("cut", self.wav, "--start", "1", "--end", "3", "-o", self.out("v_ok.wav"), "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertGreater(doc["probe"]["duration"], 1.5)

    def test_a_cut_that_loses_its_video_is_not_verified(self):
        """#367, found by the VDC paper's seeded-defect sensitivity run: on some MPEG-TS sources
        ffmpeg's input seek drops the whole video stream, and cut.py said completed, verified: true,
        notes: [] for the audio-only MP4, because it measured duration and start skew but never the
        output's stream composition. Seeded here by stripping the video from the output probe the
        way that defect leaves it; a no-false-alarm control runs the same cut unseeded."""
        out = self.out("vdc_lost_video.mp4")
        seed = ("import sys; sys.path.insert(0, %r); sys.argv = ['cut.py', %r, '--start', '1', '--end', '3', '-o', %r, "
                "'--overwrite', '--json']; import importlib; e = importlib.import_module('_common.emit'); real = e.verify_output; "
                "e.verify_output = lambda path: dict(real(path), video=None); import cut; sys.exit(cut.main())"
                % (str(SCRIPTS), str(self.src), str(out)))
        doc = json.loads(sh(sys.executable, "-c", seed).stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertFalse(doc["verified"], "a cut whose video vanished must not say verified")
        step = next(s for s in doc["verification"] if s["step"] == "streams")
        self.assertEqual((step["ok"], step["missing"], step["attribution"]), (False, ["video"], "unresolved"))
        self.assertEqual(step["expected"], {"video": True, "audio": True})
        # control: the same cut, nothing seeded, passes the same check
        ok = json.loads(tool("cut", self.src, "--start", "1", "--end", "3", "-o", self.out("vdc_kept_video.mp4"),
                             "--overwrite", "--json").stdout)
        self.assertTrue(ok["verified"])
        self.assertTrue(next(s for s in ok["verification"] if s["step"] == "streams")["ok"])
        self.assertEqual(ok["unverified"], ["picture_content"])
        # an audio extension is told to drop the picture: no false alarm there either
        audio = json.loads(tool("cut", self.src, "--start", "1", "--end", "3", "-o", self.out("vdc_audio.m4a"),
                                "--overwrite", "--json").stdout)
        self.assertTrue(audio["verified"], audio["verification"])

    # The #367 follow-up and the "space in a filename dropped 40 s of audio" report (X,
    # 2026-10-29): a stream's presence was checked, but not its count, its length against the
    # other stream, or whether it decodes. Seeded with real damaged files written over the
    # tool's own output just before it is measured.
    SEED = r"""
import os, shutil, subprocess

def _ff(*a):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *a], check=True)

def drop_video(p):
    tmp = p + ".seed.mp4"; _ff("-i", p, "-map", "0:a", "-c", "copy", tmp); os.replace(tmp, p)

def short_audio(p):
    tmp = p + ".seed.mp4"
    _ff("-i", p, "-t", "0.8", "-i", p, "-map", "0:v", "-map", "1:a", "-c", "copy", tmp); os.replace(tmp, p)

def garbage_payload(p):
    data = bytearray(open(p, "rb").read()); i = 0
    while i + 8 <= len(data):
        size = int.from_bytes(data[i:i + 4], "big"); kind = bytes(data[i + 4:i + 8])
        if kind == b"mdat":
            for j in range(i + 8, min(len(data), i + size)):
                data[j] = 0
            break
        i += size if size >= 8 else len(data)
    open(p, "wb").write(bytes(data))
"""

    def seeded(self, mode, name, *args):
        """Run cut.py with its output damaged by `mode` right before the tool measures it."""
        mod = self.work / "seed_mod.py"
        mod.write_text(self.SEED, encoding="utf-8")
        out = self.out(name)
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import seed_mod; "
                "sys.argv = ['cut.py'] + %r + ['-o', %r, '--overwrite', '--json']; import importlib; "
                "e = importlib.import_module('_common.emit'); real = e.verify_output; "
                "e.verify_output = lambda path: (seed_mod.%s(path), real(path))[1]; import cut; sys.exit(cut.main())"
                % (str(SCRIPTS), str(self.work), [str(a) for a in args], str(out), mode))
        return json.loads(sh(sys.executable, "-c", code).stdout)

    def test_a_damaged_ts_cut_names_the_stream_that_broke(self):
        ts = self.out("ts_source.ts")
        ffmpeg("-i", self.src, "-c", "copy", "-f", "mpegts", ts)
        if sh("ffprobe", "-v", "error", "-show_format", ts, check=False).returncode != 0:
            # the johnvansickle static ffprobe builds (5.1.1, 7.0.2) segfault on any MPEG-TS file
            self.skipTest("this ffprobe cannot read MPEG-TS")
        ok = json.loads(tool("cut", ts, "--start", "1", "--end", "4", "-o", self.out("ts_ok.mp4"),
                             "--overwrite", "--json").stdout)
        self.assertTrue(ok["verified"], ok["verification"])
        steps = {s["step"]: s for s in ok["verification"]}
        for name in ("streams", "stream_lengths", "decode"):
            self.assertTrue(steps[name]["ok"], steps.get(name))
        self.assertEqual(steps["streams"]["measured_count"], {"video": 1, "audio": 1})
        self.assertEqual(set(steps["decode"]["frames"]), {"video", "audio"})
        for mode, failing in (("drop_video", "streams"), ("short_audio", "stream_lengths"),
                              ("garbage_payload", "decode")):
            with self.subTest(mode=mode):
                doc = self.seeded(mode, f"ts_{mode}.mp4", ts, "--start", "1", "--end", "4")
                self.assertEqual(doc["status"], "completed")
                self.assertFalse(doc["verified"], f"{mode}: a damaged cut said verified")
                bad = [s["step"] for s in doc["verification"] if s.get("ok") is False]
                self.assertIn(failing, bad, doc["verification"])
        short = next(s for s in self.seeded("short_audio", "ts_short2.mp4", ts, "--start", "1", "--end", "4")["verification"]
                     if s["step"] == "stream_lengths")
        self.assertEqual(short["short"], ["audio"])
        self.assertGreater(short["measured"]["video"] - short["measured"]["audio"], 1.5)

    def test_stream_checks_count_the_tail_window_and_allow_an_unread_input_gap(self):
        """Review of the checks above: the tail decode reads from 10 s early, so only frames in the
        last window may count; an input whose sound length cannot be read has an unknown gap, not
        a zero one, so a gap in the output is not_measured rather than short; a shortfall is
        compared before rounding."""
        import importlib
        E = importlib.import_module("_common.emit")
        crc = types.SimpleNamespace(stdout="#tb 0: 1/1000\n#media_type 0: audio\n0, 1000, 1000, 21, 4, 0x1\n"
                                           "0, 8500, 8500, 21, 4, 0x2\n0, 9200, 9200, 21, 4, 0x3\n")
        self.assertEqual(E._framecrc_frames(crc), 3)
        self.assertEqual(E._framecrc_frames(crc, since=9.0), 1)
        self.assertEqual(E._framecrc_frames(crc, since=9.5), 0)
        held = types.SimpleNamespace(stdout="#tb 0: 1/1000\n0, 7000, 7000, 3000, 4, 0x1\n")  # 7-10 s on screen
        self.assertEqual(E._framecrc_frames(held, since=9.0), 1)
        ref = {"duration": 10.0, "video": {"duration": 10.0, "start_time": 0.0}, "audio": {"duration": None, "start_time": 0.0}}
        out = {"video": {"duration": 4.0, "start_time": 0.0}, "audio": {"duration": 3.5, "start_time": 0.0}}
        step = E.stream_lengths_step(out, [ref])  # the input's own gap is unknown: not a pass, not "short"
        self.assertEqual((step["ok"], "short" in step, step["reason"][:13]), (False, False, "not_measured:"))
        even = {"video": {"duration": 4.0, "start_time": 0.0}, "audio": {"duration": 4.0, "start_time": 0.0}}
        self.assertTrue(E.stream_lengths_step(even, [ref])["ok"])  # no gap to explain
        ref["audio"]["duration"] = 9.4
        self.assertTrue(E.stream_lengths_step(out, [ref])["ok"])  # the input was 0.6 s short already
        edge = {"video": {"duration": 4.0, "start_time": 0.0}, "audio": {"duration": 4.0 - 0.2504, "start_time": 0.0}}
        self.assertEqual(E.stream_lengths_step(edge, [])["short"], ["audio"])
        nan = {"video": {"duration": 4.0, "start_time": 0.0}, "audio": {"duration": float("nan"), "start_time": 0.0}}
        self.assertEqual(E.stream_lengths_step(nan, [])["ok"], False)  # NaN is no length, not a pass
        # a cut window counts only the input's gap inside it (CodeRabbit on #375): video 10 s,
        # sound 5 s; a 2-4 s cut has no gap to inherit, a 4-8 s cut inherits 3 s
        src = {"video": {"duration": 10.0, "start_time": 0.0}, "audio": {"duration": 5.0, "start_time": 0.0}}
        lost = {"video": {"duration": 2.0, "start_time": 0.0}, "audio": {"duration": 1.0, "start_time": 0.0}}
        self.assertEqual(E.stream_lengths_step(lost, [src], windows=[(2.0, 4.0)])["short"], ["audio"])
        self.assertTrue(E.stream_lengths_step(lost, [src])["ok"])  # the whole source's 5 s would hide it
        tail = {"video": {"duration": 4.0, "start_time": 0.0}, "audio": {"duration": 1.0, "start_time": 0.0}}
        self.assertTrue(E.stream_lengths_step(tail, [src], windows=[(4.0, 8.0)])["ok"])
        # a stream with no end of its own is unmeasured at its tail, never "undecodable"
        dec = E.decode_step(str(self.src), {"duration": 6.0, "video": {"duration": 6.0, "start_time": 0.0},
                                            "audio": {"duration": None, "start_time": 0.0}}, ["video", "audio"])
        self.assertEqual((dec["ok"], dec["undecodable"], dec["frames"]["audio"]["tail"]), (False, [], 0))
        self.assertTrue(dec["reason"].startswith("not_measured:") and dec["frames"]["video"]["tail"] > 0, dec)
        # a cover picture stored before the motion video is not what is decoded (0:V, not 0:v), and
        # sound that starts 2 s in is decoded from its own start, not the file's first second
        covered = self.out("dec_cover.mp4")
        ffmpeg("-i", self.logo, "-i", self.src, "-map", "0", "-map", "1", "-c:v:0", "png", "-c:v:1", "copy", "-c:a", "copy",
               "-disposition:v:0", "attached_pic", covered)
        late = self.out("dec_late_audio.mp4")
        ffmpeg("-i", self.src, "-itsoffset", "2", "-i", self.src, "-map", "0:v", "-map", "1:a", "-c", "copy", late)
        Pm = importlib.import_module("_common.probe")
        for path in (covered, late):
            d = E.decode_step(str(path), Pm.probe(str(path)), ["video", "audio"])
            self.assertTrue(d["ok"], (path.name, d))
        # a count, not presence: two sound streams expected and one written is `missing`
        two = {"video": {"codec": "h264"}, "audio": {"codec": "aac"}, "stream_counts": {"video": 1, "audio": 1}}
        inv = E.stream_inventory_step(two, {"video": 1, "audio": 2})
        self.assertEqual((inv["ok"], inv["missing"], inv["measured_count"]), (False, ["audio"], {"video": 1, "audio": 1}))

    def test_paths_with_spaces_quotes_and_japanese_keep_every_second_of_audio(self):
        """The report: a filename with a space "was shell-escaped" and 40 s of audio went missing
        with no error. Every tool passes ffmpeg an argv list (no shell; pinned by
        test_every_tool_help_and_no_shell_paths), so the path reaches ffmpeg as one argument. This
        runs the tools that carry sound on such paths and requires the sound to keep its length,
        measured by ffprobe here and by the tool's own stream_lengths step."""
        odd = "a b's & 日本語 [1];x" + ("" if os.name == "nt" else ' "q"')
        d = self.work / odd
        d.mkdir(exist_ok=True)
        a, b = d / f"clip {odd}.mp4", d / f"two {odd}.mp4"
        shutil.copy(self.src, a)
        shutil.copy(self.camb, b)
        lst = d / f"list {odd}.txt"
        lst.write_text(f"{a}\n{b}\n", encoding="utf-8")
        a_len = float(probe_streams(a)["audio"])
        b_len = float(probe_streams(b)["audio"])
        runs = [("cut", (a, "--start", "1", "--end", "4"), 3.0),
                ("cut", (a, "--segments", "0.5-2,3-5.5"), 4.0),
                ("join", (a, b), a_len + b_len),
                ("join", ("--list", lst), a_len + b_len),
                ("loudness", (a, "-I", "-16"), a_len),
                ("audio", (a, "--denoise"), a_len),
                ("export", (a, "--preset", "youtube"), a_len)]
        for n, (name, args, want) in enumerate(runs):
            with self.subTest(tool=name, args=args[1:]):
                out = d / f"out {n} {odd}.mp4"
                doc = json.loads(tool(name, *args, "-o", out, "--overwrite", "--json").stdout)
                self.assertEqual(doc["status"], "completed", doc)
                lens = {k: float(v) for k, v in probe_streams(out).items()}
                if name == "join":  # the default crossfade overlaps the clips by its own length
                    want -= doc["transition_shortening"]
                self.assertAlmostEqual(lens["audio"], want, delta=0.25, msg=f"{name}: audio is {lens['audio']}s, wanted {want}s")
                self.assertAlmostEqual(lens["audio"], lens["video"], delta=0.25)
                if name in ("cut", "join", "export"):
                    step = next(s for s in doc["verification"] if s["step"] == "stream_lengths")
                    self.assertTrue(step["ok"], step)

    def test_printed_commands_run_unchanged_in_a_posix_shell(self):
        """`commands` are shell-quoted so they can be pasted and run again. A name with a backtick,
        a leading `#` or `~`, or `!` was printed bare: a shell ran the backtick as a command,
        dropped a `#name` as a comment and expanded `~`."""
        from _common.runner import shell_quote
        names = ["clip a.mp4", "it's.mp4", 'say "hi".mp4', "a&b.mp4", "日本語 の 動画.mp4", "x`id`.mp4",
                 "$(echo hi).mp4", "#tag.mp4", "~/clip.mp4", "wow!.mp4", "tab\there.mp4", "-dash.mp4", "50%.mp4",
                 "a=b.mp4", "plain.mp4", ""]
        for n in names:
            self.assertEqual(shlex.split(shell_quote(n)), [n], n)
        if os.name == "nt" or not shutil.which("sh"):
            self.skipTest("no POSIX shell here")
        line = " ".join(shell_quote(n) for n in names)
        got = subprocess.run(["sh", "-c", "set -- " + line + '; for a in "$@"; do printf "%s\\0" "$a"; done'],
                             stdout=subprocess.PIPE, check=True).stdout.decode("utf-8")
        self.assertEqual(got.split("\0")[:-1], names)

    def test_join_reports_which_clips_got_generated_silence(self):
        """The VDC paper's join finding: a clip with no audio stream is joined over anullsrc silence
        (right), and the result said verified with no note (wrong: the sound of that span is not
        the clip's). The substitution is now named in `audio_substituted` and `notes`."""
        silent = self.out("vdc_noaudio.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", silent)
        doc = json.loads(tool("join", self.src, silent, "-o", self.out("vdc_join.mp4"), "--overwrite", "--json").stdout)
        self.assertEqual(doc["audio_substituted"], [str(silent)])
        self.assertTrue(any("generated silence" in n for n in doc["notes"]), doc.get("notes"))
        self.assertTrue(next(s for s in doc["verification"] if s["step"] == "streams")["ok"])

    def test_one_true_peak_tolerance_is_applied_and_reported(self):
        """loudness.py allowed +0.1 dB over a dBTP ceiling, check.py +0.05 and export.py 0.0, so the same
        file could pass one tool and fail another (the VDC paper's loudness/export findings). One
        constant now, and the loudness step reports it."""
        import _platforms
        for name in ("loudness", "check", "export"):
            text = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("TP_TOLERANCE_DB", text, name)
            self.assertNotRegex(text, r'tp"?\]?\)? \+ 0\.\d', f"{name}.py adds its own true-peak margin")
        doc = json.loads(tool("loudness", self.src, "-o", self.out("vdc_loud.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "loudness")
        self.assertEqual(step["tolerance"]["tp"], _platforms.TP_TOLERANCE_DB)
        self.assertEqual(set(step["expected"]), {"lufs", "tp_max"})
        self.assertAlmostEqual(step["delta"]["tp"], step["measured"]["tp"] - step["expected"]["tp_max"], places=1)
        # the verdict at the boundary, not only the constant: a 440 Hz sine whose true peak is
        # 0.05 dB over a -1 dBTP ceiling passes, one 0.15 dB over fails
        for over, status in ((0.05, "PASS"), (0.15, "FAIL")):
            wav = self.out(f"vdc_tp_{over}.wav")
            ffmpeg("-f", "lavfi", "-i", f"aevalsrc={10 ** ((-1 + over) / 20):.6f}*sin(2*PI*440*t):s=48000:d=5", "-c:a", "pcm_s24le", wav)
            rows = json.loads(tool("check", wav, "--platform", "podcast", "--tp", "-1", "--json", check=False).stdout)["checks"]
            self.assertEqual(next(r for r in rows if r["check"] == "true peak")["status"], status, f"+{over} dB")
        # export's step carries what it measured against the platform, not only the verdict
        doc = json.loads(tool("export", self.src, "--preset", "x", "--fast", "-o", self.out("vdc_x.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "loudness")
        self.assertEqual(step["tolerance"]["tp"], _platforms.TP_TOLERANCE_DB)
        self.assertAlmostEqual(step["delta"]["tp"], step["measured"]["tp"] - step["expected"]["tp_max"], places=1)
        self.assertIn("lufs", step["measured"])
        self.assertIn("tp", step["delta"])

    def test_a_levels_pass_keeps_the_input_length_and_says_so(self):
        """loudness.py's AAC output came back longer than its input (0.015 s on 6 s, 0.1 s on a 90 s
        Reels export, which check.py then failed while export.py said verified). The sound is
        trimmed to the input's length, and a duration step measures it (2.20)."""
        src_audio = float(probe_streams(self.src)["audio"])
        doc = json.loads(tool("loudness", self.src, "-o", self.out("len_loud.mp4"), "--overwrite", "--json").stdout)
        self.assertAlmostEqual(float(probe_streams(self.out("len_loud.mp4"))["audio"]), src_audio, delta=0.005)
        step = next(s for s in doc["verification"] if s["step"] == "duration")
        self.assertEqual((step["property"], step["provenance"], step["ok"]), ("audio_duration", "input_premeasurement", True))
        self.assertAlmostEqual(step["expected"], src_audio, places=2)
        # sound that starts a second into the file: the trim counts from its first sample, not
        # from the file's zero (atrim=end= cut the last second off it)
        late = self.out("len_late.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-itsoffset", "1", "-f", "lavfi", "-i", "sine=440:d=4",
               "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", late)
        doc = json.loads(tool("loudness", late, "-o", self.out("len_late_loud.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "duration")
        self.assertTrue(step["ok"], step)
        self.assertAlmostEqual(float(probe_streams(self.out("len_late_loud.mp4"))["audio"]),
                               float(probe_streams(late)["audio"]), delta=0.03)
        # and it still starts where it started, beside the copied picture
        self.assertAlmostEqual(probe_starts(self.out("len_late_loud.mp4"))["audio"], probe_starts(late)["audio"], delta=0.05)
        # Matroska gives no stream duration: the sound's own length comes from its DURATION tag,
        # not from the container, which is the 6 s picture's and failed a correct 4 s output
        mkv = self.out("len_short_audio.mkv")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-f", "lavfi", "-i", "sine=440:d=4",
               "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "libopus", mkv)
        doc = json.loads(tool("loudness", mkv, "-o", self.out("len_short_audio.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "duration")
        self.assertTrue(step["ok"], step)
        self.assertAlmostEqual(step["expected"], 4.0, delta=0.05)
        import importlib
        probe_mod = importlib.import_module("_common.probe")
        for bad in ("nan", "inf", "-00:00:01.0", "00:00:-1", "garbage", None):
            self.assertIsNone(probe_mod._tag_seconds(bad if bad is None or ":" in bad else f"00:00:{bad}"), bad)
        self.assertAlmostEqual(probe_mod._tag_seconds("00:00:04.008000000"), 4.008)

    def test_export_measures_the_length_its_preset_promises(self):
        """export.py trims to the platform maximum but never re-read the written length (the VDC
        paper's 90.10 s Reels file). The step holds the length to the same limit check.py does."""
        import _platforms
        doc = json.loads(tool("export", self.src, "--preset", "x", "--fast", "-o", self.out("len_x.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "duration")
        limit = float(_platforms.PLATFORMS["x"]["spec"]["max_duration"])
        self.assertEqual(step["expected"], {"max": limit})
        self.assertEqual((step["ok"], step["tolerance"], step["provenance"]), (True, 0.0, "specification"))
        self.assertAlmostEqual(step["delta"], step["measured"] - limit, places=3)
        # seeded: the written file measures past the limit (as the 90.10 s Reels file did), and the
        # step and the result both say so; then a length that cannot be read at all
        for seeded, want in (("999.0", 999.0), ("None", None)):
            out = self.out(f"len_x_seeded_{want}.mp4")
            seed = ("import sys; sys.path.insert(0, %r); sys.argv = ['export.py', %r, '--preset', 'x', '--fast', '-o', %r, "
                    "'--overwrite', '--json']; import export; real = export.probe; "
                    "export.probe = lambda path, role=None, **k: dict(real(path, role=role, **k), duration=%s) "
                    "if role == 'output' and path == %r else real(path, role=role, **k); sys.exit(export.main())"
                    % (str(SCRIPTS), str(self.src), str(out), seeded, str(out)))
            doc = json.loads(sh(sys.executable, "-c", seed).stdout)
            step = next(s for s in doc["verification"] if s["step"] == "duration")
            self.assertFalse(step["ok"], seeded)
            self.assertFalse(doc["verified"], seeded)
            self.assertEqual(step.get("measured"), want)

    def test_join_reports_the_clips_total_next_to_the_joined_length(self):
        """join.py's expected length is derived from the transition it applied, so a check against
        it alone hid that a fade took time out of the material (15 s of clips as 14 s). The clips'
        own total is reported beside it, with a note when the transitions shortened the join."""
        doc = json.loads(tool("join", self.src, self.src, "-o", self.out("len_join.mp4"), "--overwrite", "--json").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "duration")
        self.assertAlmostEqual(doc["inputs_duration"], step["inputs_total"], places=2)
        self.assertAlmostEqual(doc["transition_shortening"], doc["inputs_duration"] - doc["expected_duration"], places=3)
        self.assertGreater(doc["transition_shortening"], 0)
        self.assertTrue(any("transitions overlap the clips" in n for n in doc.get("notes") or []))
        cut = json.loads(tool("join", self.src, self.src, "--transition", "none", "-o", self.out("len_join_cut.mp4"),
                              "--overwrite", "--json").stdout)
        self.assertEqual(cut["transition_shortening"], 0.0)
        self.assertFalse(any("transitions overlap" in n for n in cut.get("notes") or []))

    def test_silence_says_which_removed_spans_were_digital_silence(self):
        """silence.py removed quiet sound under --threshold and digital silence alike and reported
        both as "silences". It still removes both, and now says which is which (2.20)."""
        wav = self.out("kinds.wav")
        ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*(lt(t\\,2)+between(t\\,3\\,5)+gt(t\\,6))"
               "+0.003*sin(2*PI*300*t)*between(t\\,5\\,6)':s=48000:d=8", wav)
        doc = json.loads(tool("silence", wav, "--threshold", "-35", "--min-silence", "0.4", "--list", "--json").stdout)
        self.assertEqual(len(doc["silences"]), 2)
        self.assertEqual(doc["silence_kinds"], ["digital", "below_threshold"])
        self.assertEqual(doc["silence_breakdown"]["below_threshold"]["level_db"], -35)
        self.assertEqual(doc["silence_breakdown"]["digital"]["count"], 1)
        self.assertAlmostEqual(doc["silence_breakdown"]["digital"]["seconds"], 1.0, delta=0.1)
        self.assertAlmostEqual(doc["silence_breakdown"]["below_threshold"]["seconds"], 1.0, delta=0.1)

    def test_the_thresholds_table_matches_the_code(self):
        """references/scripts.md restates every verdict threshold (2.21). Each row names the constant
        or flag it comes from, and its value must be that constant's or that flag's default; the
        per-platform table must be _platforms.PLATFORMS, row for row."""
        import importlib, re
        text = (ROOT / "references" / "scripts.md").read_text(encoding="utf-8")
        block = text.split("<!-- thresholds:start -->", 1)[1].split("<!-- thresholds:end -->", 1)[0]
        rows = [r for r in block.strip().splitlines()[2:] if r.startswith("|")]
        # every threshold: a row deleted (or added) must be a deliberate edit here too
        self.assertEqual(len(rows), 28)
        for row in rows:
            what, value, source, _used = [c.strip() for c in row.strip("|").split("|")]
            number = float(re.search(r"-?\d+(?:\.\d+)?", value).group(0))
            src = source.strip("`")
            if ".py --" in src:
                tool_name, flag = src.split(".py ", 1)
                props = self.tools[tool_name]["input_schema"]["properties"]
                prop = next(p for p in props.values() if flag in (p.get("cli") or []))
                actual = prop["default"]
            else:
                module, _, name = src.rpartition(".")
                actual = getattr(importlib.import_module(module), name)
            if isinstance(actual, str):  # an ffmpeg option value such as "-60dB"
                actual = re.search(r"-?\d+(?:\.\d+)?", actual).group(0)
            self.assertAlmostEqual(float(actual), number, places=6, msg=f"{what}: table says {value}, {src} is {actual}")
        # the silent-track row says join, audio and waveform default to it: hold them to that
        from _common.probe import SILENT_PEAK_DBFS
        for name in ("join", "audio", "waveform"):
            props = self.tools[name]["input_schema"]["properties"]
            prop = next(p for p in props.values() if "--silence-threshold" in (p.get("cli") or []))
            self.assertAlmostEqual(prop["default"], SILENT_PEAK_DBFS, places=6, msg=name)
        import _platforms
        block = text.split("<!-- platforms:start -->", 1)[1].split("<!-- platforms:end -->", 1)[0]
        table = [r for r in block.strip().splitlines()[2:] if r.startswith("|")]
        want = []
        for key, entry in _platforms.PLATFORMS.items():
            spec = entry["spec"]
            lufs = "—" if spec.get("lufs") is None else f"{spec['lufs']:g} LUFS"
            longest = "—" if spec.get("max_duration") is None else f"{spec['max_duration']:g} s"
            want.append(f"| `{key}` | {lufs} | ±{spec['lufs_tol']:g} LU | {spec['tp']:g} dBTP | {longest} |")
        self.assertEqual(table, want)

    def test_unverified_range_names_real_tools_and_reaches_the_contract(self):
        from _common.emit import UNVERIFIED
        self.assertLessEqual(set(UNVERIFIED), set(self.tools))
        for name, props in UNVERIFIED.items():
            self.assertEqual(self.tools[name]["unverified_properties"], props)
        self.assertIn("rendered_placement", self.tools["caption"]["unverified_properties"])

    def test_success_requires_a_verified_output(self):
        import _common
        for name in ("cut", "audio", "loudness", "silence", "fit", "export", "caption", "overlay", "color", "join", "graphics", "multicam"):
            src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("emit(", src, f"{name} does not go through emit()")
        self.assertIn("verify_output(output)", (SCRIPTS / "_common" / "emit.py").read_text(encoding="utf-8"))
        with self.assertRaises(SystemExit):
            _common.verify_output(str(self.work / "never_written.mp4"))

    def _run_structured(self, name, args):
        """Drive a tool the way an agent adapter would: structured args -> argv (same mapping as MCP)."""
        argv = mcp_server.build_argv(name, args)
        proc = tool(name, *argv, check=False)
        self.assertEqual(proc.returncode, 0, f"{name} {argv}\n{proc.stderr}")
        return json.loads(proc.stdout) if proc.stdout.strip().startswith(("{", "[")) else proc.stdout

    def _verify(self, name, output):
        """Apply the ToolSpec verification policy to an artifact."""
        for ref in self.tools[name]["verification"]["tools"]:
            vt = ref.split("/")[1]
            if vt == "probe":
                meta = self._run_structured("probe", {"inputs": [str(output)]})
                self.assertGreater(meta["duration"], 0)
            elif vt == "check":
                self._run_structured("check", {"input": str(output), "platform": "custom"})
            elif vt == "look":
                doc = self._run_structured("look", {"input": str(output), "output": str(self.out(f"{name}_look.png")), "json": True})
                self.assertTrue(Path(doc["output"]).exists())

    def test_probe_cut_silence_loudness_sync_audio_via_contract(self):
        meta = self._run_structured("probe", {"inputs": [str(self.src)]})
        self.assertEqual(meta["video"]["width"], 640)
        doc = self._run_structured("cut", {"input": str(self.src), "start": "1", "end": "3", "output": str(self.out("cut.mp4"))})
        self.assertAlmostEqual(doc["probe"]["duration"], 2.0, delta=0.6)
        self._verify("cut", doc["output"])
        doc = self._run_structured("silence", {"input": str(self.src), "output": str(self.out("silence.mp4"))})
        self.assertLessEqual(doc["probe"]["duration"], 6.1)
        self._verify("silence", doc["output"])
        doc = self._run_structured("loudness", {"input": str(self.wav), "lufs": -16, "tp": -1.5, "output": str(self.out("loud.m4a"))})
        self.assertEqual(doc["probe"]["audio"]["codec"], "aac")
        self._verify("loudness", doc["output"])
        # the second-pass (post-normalization) measurement must be in the JSON itself -- an agent
        # shouldn't need a separate --measure-only call to learn what loudness was actually achieved
        self.assertIn("result", doc)
        self.assertAlmostEqual(float(doc["result"]["input_i"]), -16, delta=1.0)
        self.assertFalse(doc["result"]["silent"])
        doc = self._run_structured("sync", {"reference": str(self.src), "second": str(self.mic)})
        self.assertAlmostEqual(doc["offset_seconds"], 1.5, delta=0.05)
        doc = self._run_structured("sync", {"reference": str(self.src), "second": str(self.mic), "replace_audio": True, "output": str(self.out("synced.mp4"))})
        self._verify("sync", doc["output"])
        doc = self._run_structured("audio", {"input": str(self.surround), "downmix": True, "output": str(self.out("stereo.mov"))})
        self.assertEqual(doc["probe"]["audio"]["channels"], 2)
        self._verify("audio", doc["output"])

    def test_probe_subtitle_stream_details(self):
        """subtitle_streams stays the existing int count; subtitle_stream_details is the new,
        additive, audio_streams-shaped array (index/codec/language/title per embedded track)."""
        doc = self._run_structured("probe", {"inputs": [str(self.subbed)]})
        self.assertEqual(doc["subtitle_streams"], 2)
        details = doc["subtitle_stream_details"]
        self.assertEqual(len(details), 2)
        self.assertEqual(details[0]["index"], 0)
        self.assertEqual(details[0]["codec"], "subrip")
        self.assertEqual(details[0]["language"], "eng")
        self.assertEqual(details[0]["title"], "English")
        self.assertEqual(details[1]["index"], 1)
        self.assertEqual(details[1]["codec"], "subrip")
        self.assertEqual(details[1]["language"], "jpn")
        self.assertEqual(details[1]["title"], "Japanese")
        # no subtitle tracks at all: still present, just an empty list; subtitle_streams stays 0
        doc2 = self._run_structured("probe", {"inputs": [str(self.src)]})
        self.assertEqual(doc2["subtitle_streams"], 0)
        self.assertEqual(doc2["subtitle_stream_details"], [])
        # data_streams (added alongside run_keeping_subtitles(), #91 review): a plain fixture
        # with no data/attachment stream reports 0, same additive-field convention as
        # subtitle_streams above.
        self.assertEqual(doc2["data_streams"], 0)
        # positive case: c_data_stream.mov has a real data stream (a -timecode track, the
        # standard way to get one in mov/mp4) -- confirms detection isn't just "always 0".
        doc3 = self._run_structured("probe", {"inputs": [str(self.data_stream)]})
        self.assertEqual(doc3["data_streams"], 1)

    def test_color_overlay_caption_export_check_look_render_via_contract(self):
        doc = self._run_structured("color", {"input": str(self.hdr), "to_sdr": True, "fast": True, "output": str(self.out("sdr.mp4"))})
        self.assertFalse(doc["probe"]["video"]["hdr"])
        self._verify("color", doc["output"])
        doc = self._run_structured("overlay", {"input": str(self.src), "image": str(self.logo), "position": "top-right", "fast": True, "output": str(self.out("ov.mp4"))})
        self._verify("overlay", doc["output"])
        doc = self._run_structured("caption", {"input": str(self.src), "text": str(self.cues), "fast": True, "output": str(self.out("cap.mp4"))})
        self._verify("caption", doc["output"])
        doc = self._run_structured("export", {"input": str(self.vfr), "preset": "x", "fast": True, "output": str(self.out("vfr_x.mp4"))})
        self.assertFalse(doc["probe"]["video"].get("variable_frame_rate_suspected"))
        self._verify("export", doc["output"])
        chk = self._run_structured("check", {"input": doc["output"], "platform": "x"})
        self.assertIn("checks", chk)
        look = self._run_structured("look", {"input": doc["output"], "output": str(self.out("sheet.png")), "json": True})
        self.assertTrue(Path(look["output"]).exists())
        project = self.out("project.json")
        project.write_text(json.dumps({"output": str(self.out("render.mp4")), "frame": {"aspect": "9:16", "width": 360, "fps": 30},
                                       "clips": [{"src": str(self.src), "in": 0, "out": 3}], "loudness": {"lufs": -14, "tp": -1},
                                       "export": {"preset": "reels"}, "check": {"platform": "reels"}}), encoding="utf-8")
        doc = self._run_structured("render", {"project": str(project), "fast": True})
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["check"]["failed"], 0, doc["check"])
        self._verify("render", doc["output"])

    def test_mcp_tool_call_round_trip(self):
        req = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "probe", "arguments": {"inputs": [str(self.wav)]}}}) + "\n"
        proc = subprocess.run([sys.executable, str(ROOT / "mcp" / "server.py")], input=req, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        resp = json.loads(proc.stdout.strip().splitlines()[0])
        self.assertIsNone(resp["result"]["structuredContent"]["video"])
        self.assertEqual(resp["result"]["structuredContent"]["audio"]["codec"], "pcm_s16le")

    def test_every_tool_help_and_no_shell_paths(self):
        for t in self.contract["tools"]:
            self.assertIn("usage:", tool(t["name"], "--help").stdout)
        for path in script_sources() + [ROOT / "mcp" / "server.py"]:
            src = path.read_text(encoding="utf-8")
            for forbidden in ("shell=True", "os.system(", "eval(", "exec(", "os.popen("):
                self.assertNotIn(forbidden, src, f"{path.name} uses {forbidden}")

    def test_inputs_untouched_after_the_run(self):
        for path, digest in self.input_hashes.items():
            self.assertEqual(self._sha(path), digest, f"{path.name} was modified by a tool")

    def test_real_device_corpus_when_present(self):
        wanted = [CORPUS / n for n in ("iphone13pro_4K60p.mov", "android_screen_1.mp4", "dji_DJI_0038.MOV", "gopro_GX010743.MP4")]
        present = [p for p in wanted if p.exists()]
        if not present:
            self.skipTest("real-device corpus not downloaded (tests/corpus.py --fetch)")
        for p in present:
            meta = self._run_structured("probe", {"inputs": [str(p)]})
            before = self._sha(p) if p.stat().st_size < 50_000_000 else p.stat().st_size
            doc = self._run_structured("cut", {"input": str(p), "start": "0", "end": "2", "tolerance": -1, "output": str(self.out(p.stem + "_cut" + p.suffix))})
            self._verify("cut", doc["output"])
            self._run_structured("check", {"input": doc["output"], "platform": "custom", "no_loudness": True})
            if meta.get("video"):
                self._run_structured("look", {"input": doc["output"], "output": str(self.out(p.stem + "_look.png")), "json": True})
            after = self._sha(p) if p.stat().st_size < 50_000_000 else p.stat().st_size
            self.assertEqual(before, after, f"{p.name} modified")


class SilentPathTests(unittest.TestCase):
    """docs/design-decisions.md, "Nothing happens silently": the output lock's decisions, in
    process, and the source-level checks that keep the runner's refusals structured."""

    class Refused(Exception):
        pass

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ffskill_silent_")
        self.out = os.path.join(self.tmp, "out.mp4")
        self.lock = Path(self.tmp, ".out.mp4.ffskill-lock")
        self.audit = Path(self.tmp, ".out.mp4.ffskill-audit.jsonl")
        self.saved = (_common.STATE.timeout, _common.STATE.dry_run, _common.STATE.audit_log)
        _common.STATE.dry_run, _common.STATE.audit_log = False, None
        for bucket in ("warnings", "fallbacks", "skipped", "notes"):
            setattr(_common.STATE, bucket, [])

    def tearDown(self):
        _common.STATE.timeout, _common.STATE.dry_run, _common.STATE.audit_log = self.saved
        for bucket in ("warnings", "fallbacks", "skipped", "notes"):
            setattr(_common.STATE, bucket, [])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def enter(self, at=None):
        """Take the lock (time.time() reads `at` when given); return the refusal's kwargs or None."""
        from unittest import mock

        def refuse(kind, reason, msg, **kw):
            raise self.Refused(dict(kw, kind=kind, reason=reason, message=msg))
        import contextlib
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch("_common.runner.refuse", refuse))
                if at is not None:
                    stack.enter_context(mock.patch("time.time", lambda: at))
                with _common._OutputLock(self.out):
                    return None
        except self.Refused as r:
            return r.args[0]

    def test_a_live_holder_keeps_its_lock_past_an_hour_while_inside_its_own_limit(self):
        """Through 2.10 a lock older than an hour was taken over even while its pid ran, so a
        legitimate encode longer than an hour lost its lock to a second writer. The writer now
        dates the lock to its own deadline (child_limit(): 4x --timeout + 60 s)."""
        _common.STATE.timeout = 1800.0
        lk = _common._OutputLock(self.out)
        lk.__enter__()
        try:
            self.assertEqual(self.lock.read_text(), str(os.getpid()))
            refused = self.enter(at=time.time() + 5400)  # 1.5 h later, inside 4 x 1800 + 60 s
            self.assertIsNotNone(refused, "a live holder inside its own limit lost its lock")
            self.assertEqual((refused["reason"], refused["pid"], refused["pid_alive"], refused["why"]),
                             ("output_locked", os.getpid(), True, "held"))
            self.assertEqual(refused["lock"], str(self.lock))
            late = self.enter(at=time.time() + 7400)
            if platform.system() == "Windows":
                # Windows cannot delete a lock file its holder still has open: the takeover fails,
                # and the refusal says why rather than the failure passing silently
                self.assertIsNotNone(late, "an open lock cannot be deleted on Windows")
                self.assertEqual((late["reason"], late["why"]), ("output_locked", "past_deadline"))
                self.assertIn("takeover_error", late)
                return
            self.assertIsNone(late, "past its limit, a live pid is taken over")
            fb = _common.STATE.fallbacks[-1]
            self.assertEqual((fb["code"], fb["why"], fb["pid_alive"]), ("stale_lock_taken_over", "past_deadline", True))
            self.assertEqual(json.loads(self.audit.read_text(encoding="utf-8"))["event"], "lock_takeover")
        finally:
            lk.__exit__()

    def test_a_takeover_that_cannot_delete_the_lock_is_refused_with_the_reason(self):
        """On Windows a lock its live holder still has open cannot be deleted; that failure used to
        be swallowed (`except OSError: pass`). It now refuses with `takeover_error`."""
        from unittest import mock
        _common.STATE.timeout = 1800.0
        lk = _common._OutputLock(self.out)
        lk.__enter__()
        try:
            with mock.patch("os.remove", side_effect=PermissionError("in use by another process")):
                late = self.enter(at=time.time() + 7400)
            self.assertIsNotNone(late)
            self.assertEqual((late["reason"], late["why"]), ("output_locked", "past_deadline"))
            self.assertIn("in use by another process", late["takeover_error"])
        finally:
            lk.__exit__()

    def test_with_no_time_limit_a_live_holders_lock_is_never_taken_over(self):
        _common.STATE.timeout = 0.0
        lk = _common._OutputLock(self.out)
        lk.__enter__()
        try:
            self.assertIsNotNone(self.enter(at=time.time() + 5 * 365 * 86400))
        finally:
            lk.__exit__()

    def test_a_lock_an_older_version_wrote_is_taken_over_after_an_hour_as_before(self):
        self.lock.write_text(str(os.getpid()))
        self.assertIsNotNone(self.enter(at=time.time() + 600))
        self.assertIsNone(self.enter(at=time.time() + 3700))
        self.assertEqual(_common.STATE.fallbacks[-1]["why"], "past_deadline")

    def test_running_without_a_lock_is_a_recorded_warning(self):
        """An unlockable location (os.open fails with something other than EEXIST) ran with no
        lock and no record. It is now a diagnostics.warnings entry and an audit attempt."""
        from unittest import mock
        real_open = os.open

        def no_lock(path, *a, **k):
            if str(path).endswith(".ffskill-lock"):
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, *a, **k)
        with mock.patch("os.open", no_lock):
            with _common._OutputLock(self.out):
                pass
        w = _common.STATE.warnings[-1]
        self.assertEqual((w["code"], w["lock"]), ("output_unlocked", str(self.lock)))
        self.assertEqual(json.loads(self.audit.read_text(encoding="utf-8"))["event"], "output_unlocked")

    def test_a_failed_audit_write_is_a_warning_not_a_failure(self):
        res = _common.audit("lock_takeover", {"x": 1}, default_path=os.path.join(self.tmp, "missing", "a.jsonl"))
        self.assertEqual((res["written"], res["reason"]), (False, "unwritable"))
        self.assertEqual(_common.STATE.warnings[-1]["code"], "audit_log_unwritable")
        _common.STATE.dry_run = True
        self.assertEqual(_common.audit("x", {}, default_path=str(self.audit))["reason"], "dry_run")
        self.assertFalse(self.audit.exists())

    def test_every_refusal_reason_is_in_the_contract_and_the_runner_guards_use_refuse(self):
        """error.reason is a contract enum (json_output.error_reasons): every refuse(kind, "reason",
        ...) literal under scripts/ must be listed there, and the runner's output guards must refuse
        (structured), not die (prose only)."""
        import inspect
        reasons = set()
        for path in script_sources():
            text = path.read_text(encoding="utf-8")
            reasons |= set(re.findall(r'\brefuse\(\s*"[a-z_]+",\s*"([a-z_]+)"', text))
            reasons |= set(re.findall(r'_reject_plan\(path, digest, "([a-z_]+)"', text))
        self.assertTrue(reasons)
        self.assertEqual(sorted(reasons - set(_contract.ERROR_REASONS)), [], "refusal reasons missing from _contract.ERROR_REASONS")
        self.assertEqual(sorted(set(_contract.ERROR_REASONS) - reasons), [], "_contract.ERROR_REASONS lists a reason nothing refuses with")
        runner = sys.modules["_common.runner"]
        for fn in (runner._check_no_overwrite_input, runner.refuse_output_is_input, runner._check_output_path,
                   runner.refuse_existing_outputs, runner._OutputLock.__enter__):
            src = inspect.getsource(fn)
            self.assertNotRegex(src, r"(?<![\w.])die\(", f"{fn.__qualname__} refuses in prose only (use refuse())")


class SilentResultTests(unittest.TestCase):
    """docs/design-decisions.md, "Nothing happens silently" (part 2): a degraded or partial result
    is never reported as the asked-for one. Each test fails on 2.10.11's code."""

    @classmethod
    def setUpClass(cls):
        require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        cls.work = Path(tempfile.mkdtemp(prefix="ffskill_silent2_"))
        cls.src = cls.work / "src.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25", "-f", "lavfi", "-i", "sine=f=440:r=48000",
               "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.src)
        cls.late = cls.work / "late.mp4"   # the same scene, starting 0.8 s later on the reference timeline
        ffmpeg("-ss", "0.8", "-i", cls.src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", cls.late)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def out(self, name):
        return self.work / name

    def patched(self, module, patch, *argv):
        """Run scripts/<module>.py's main() in a child Python with `patch` (source) applied to the
        imported module first: the narrowest way to make one measurement fail, on every OS."""
        code = ("import sys; sys.path.insert(0, %r); import %s as m\n%s\nsys.argv = [%r] + %r\nsys.exit(m.main())"
                % (str(SCRIPTS), module, patch, module + ".py", [str(a) for a in argv]))
        return subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")

    def project(self, name, **proj):
        p = self.out(name + ".json")
        p.write_text(json.dumps(dict({"output": str(self.out(name + ".mp4")), "clips": [{"src": str(self.src)}]}, **proj)),
                     encoding="utf-8")
        return p

    # ---------------------------------------------------------------- multicam
    def test_multicam_names_the_camera_it_rendered_not_the_one_asked_for(self):
        """A range whose camera had not started played camera 0, but `cuts` still named the camera
        asked for. `cuts` is now what was rendered, and the fallback is recorded."""
        doc = json.loads(tool("multicam", self.src, self.late, "--switch", "0-2:1,2-4:0", "--dry-run", "--json",
                              "-o", self.out("mc.mp4")).stdout)
        self.assertEqual(doc["cuts"][0][2], 0, doc["cuts"])
        fb = doc["diagnostics"]["fallbacks"][0]
        self.assertEqual((fb["code"], fb["requested_camera"], fb["camera"], fb["start"]), ("camera_not_started", 1, 0, 0.0))

    # ---------------------------------------------------------------- export
    def test_export_says_it_trimmed_to_the_platform_maximum(self):
        """A clip over the preset's maximum was cut with only a stderr line."""
        long_src = self.out("long.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=32x32:r=2", "-t", "92", "-c:v", "libx264", "-preset", "ultrafast", long_src)
        doc = json.loads(tool("export", long_src, "--preset", "reels", "--dry-run", "--json", "-o", self.out("long_reels.mp4")).stdout)
        self.assertEqual(doc["trimmed"], {"from": 92.0, "to": 90.0})
        self.assertTrue(any("trimmed from 92.000s" in n for n in doc["notes"]), doc.get("notes"))
        doc = json.loads(tool("export", long_src, "--preset", "reels", "--allow-long", "--dry-run", "--json",
                              "-o", self.out("long_reels2.mp4")).stdout)
        self.assertNotIn("trimmed", doc)

    def test_export_an_unmeasured_loudness_is_a_failing_step_not_an_absence(self):
        """When loudnorm's JSON did not parse, the loudness block and step were left out and the
        export read verified: true against a platform it never measured."""
        proc = self.patched("export", "m.measure_loudness = lambda path: {}", self.src, "--preset", "x", "--fast",
                            "-o", self.out("x_unmeasured.mp4"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["verified"]), ("completed", False))
        self.assertEqual({k: doc["loudness"][k] for k in ("lufs", "ok", "measured", "reason")},
                         {"lufs": None, "ok": None, "measured": False, "reason": "not_measured"})
        self.assertTrue(has_step(doc["verification"], {"step": "loudness", "ok": False, "platform": "x", "reason": "not_measured"}))
        self.assertEqual(doc["diagnostics"]["warnings"][0]["code"], "loudness_not_measured")

    # ---------------------------------------------------------------- report
    def test_report_records_a_section_it_could_not_build(self):
        """A contact sheet, loudness or --platform check that failed was left out of the report and
        the document said verified: true."""
        patch = ("import subprocess\nreal = m.run_tool\n"
                 "def fake(argv, **k):\n"
                 "    if str(argv[0]).endswith(('look.py', 'loudness.py', 'check.py')):\n"
                 "        return subprocess.CompletedProcess(argv, 1, 'not json', 'error: injected failure\\n')\n"
                 "    return real(argv, **k)\n"
                 "m.run_tool = fake")
        proc = self.patched("report", patch, "--after", self.src, "--platform", "x", "-o", self.out("rep.html"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        doc = json.loads(proc.stdout)
        self.assertFalse(doc["verified"])
        self.assertIsNone(doc["check"])
        failed = {s["step"]: s for s in doc["verification"] if not s["ok"]}
        self.assertEqual(sorted(failed), ["compliance", "contact_sheet", "loudness"])
        self.assertEqual(failed["loudness"]["message"], "error: injected failure")
        self.assertEqual({w["section"] for w in doc["diagnostics"]["warnings"]}, {"compliance", "contact_sheet", "loudness"})
        # every section built: each is a passing step, and the compliance step says what the table found
        doc = json.loads(tool("report", "--after", self.src, "--platform", "x", "-o", self.out("rep_ok.html"), "--json").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual([s["step"] for s in doc["verification"]], ["exists", "loudness", "compliance", "contact_sheet"])
        self.assertIn("passed", doc["verification"][2])

    # ---------------------------------------------------------------- render
    def test_render_verified_is_every_stages_and_carries_their_notes(self):
        """export's loudness miss (completed, verified: false) became render's verified: true, and
        the stage's note naming the fix was dropped."""
        proj = self.project("rv", export={"preset": "x", "normalize": False})
        doc = json.loads(tool("render", proj, "--fast", "--json").stdout)
        self.assertEqual((doc["status"], doc["verified"]), ("completed", False))
        self.assertTrue(has_step(doc["verification"], {"step": "loudness", "ok": False, "platform": "x", "stage": "export"}))
        self.assertTrue(any(n.startswith("export: loudness ") for n in doc["notes"]), doc.get("notes"))

    def test_render_runs_a_content_only_check_and_records_a_dry_run_skip(self):
        """"check": {"content": true} without a platform was skipped without a word (a plan's
        check step honoured it); a check skipped by --dry-run left no record."""
        proj = self.project("rc", check={"content": True})
        doc = json.loads(tool("render", proj, "--fast", "--json").stdout)
        self.assertIn("check", doc["stages"])
        self.assertTrue({"black", "frozen", "silence"} <= {r["check"] for r in doc["check"]["checks"]})
        self.assertIn({"step": "check", "ok": True, "platform": None}, doc["verification"])
        dry = json.loads(tool("render", proj, "--dry-run", "--overwrite", "--json").stdout)
        self.assertEqual([s["code"] for s in dry["diagnostics"]["skipped"]], ["check_dry_run"])
        proj = self.project("rc_empty", check={})
        doc = json.loads(tool("render", proj, "--fast", "--json").stdout)
        self.assertEqual([s["code"] for s in doc["diagnostics"]["skipped"]], ["check_nothing_to_check"])

    def test_check_output_that_does_not_parse_is_a_structured_failure(self):
        """execute_plan and the check stage stored check.py's unparsed stderr as a bare string."""
        import render
        from unittest import mock
        fake = subprocess.CompletedProcess(["check.py"], 1, "garbage", "Traceback ...\nValueError: boom\n")
        with mock.patch.object(render, "run_tool", return_value=fake), contextlib.redirect_stderr(io.StringIO()):
            saved = list(_common.STATE.warnings)
            try:
                doc = render.run_check(str(self.src), "x", False)
            finally:
                _common.STATE.warnings[:] = saved
        self.assertEqual((doc["status"], doc["ok"]), ("failed", False))
        self.assertEqual((doc["error"]["reason"], doc["error"]["exit_code"]), ("check_output_unparsed", 1))
        self.assertIn("ValueError: boom", doc["error"]["message"])

    def test_render_cache_says_why_a_stage_missed_and_replays_what_a_hit_verified(self):
        """--cache missed silently (no sidecar, a corrupt one, a truncated artifact), stored
        silently on failure, and a hit carried none of the stage's verification."""
        cdir = self.out("rcache")
        proj = self.project("rcache", clips=[{"src": str(self.src), "in": 0, "out": 3}], export={"preset": "x", "normalize": False})

        def entry(stage):
            """The newest sidecar the cache holds for `stage`."""
            side = [p for p in Path(cdir).glob("*.json") if json.loads(p.read_text(encoding="utf-8") or "{}").get("stage") == stage]
            return max(side, key=lambda p: p.stat().st_mtime_ns)
        render = lambda: json.loads(tool("render", proj, "--fast", "--json", "--overwrite", "--cache", cdir).stdout)  # noqa: E731
        first = render()
        self.assertEqual({m["reason"] for m in first["cache"]["miss_reasons"]}, {"not_cached"})
        again = render()
        self.assertEqual(again["cache"]["hits"], ["clips", "export"])
        self.assertFalse(again["verified"], "a cached export that missed its loudness is still unverified")
        self.assertTrue(has_step(again["verification"], {"step": "loudness", "ok": False, "platform": "x", "stage": "export"}))
        entry("export").write_text("{not json", encoding="utf-8")
        doc = render()
        self.assertEqual([(m["stage"], m["reason"]) for m in doc["cache"]["miss_reasons"]], [("export", "sidecar_corrupt")])
        self.assertEqual(doc["diagnostics"]["warnings"][0]["code"], "cache_entry_damaged")
        self.assertEqual(json.loads((Path(cdir) / ".ffskill-audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event"],
                         "cache_entry_damaged")
        with open(entry("export").with_suffix(".mp4"), "r+b") as fh:
            fh.truncate(100)
        doc = render()
        self.assertEqual([(m["stage"], m["reason"]) for m in doc["cache"]["miss_reasons"]], [("export", "artifact_truncated")])

    def test_render_cache_store_failure_banner_fallback_and_unreadable_input_are_recorded(self):
        import render
        from unittest import mock
        saved = {b: list(getattr(_common.STATE, b)) for b in ("warnings", "fallbacks")}
        saved_cache = dict(render.CACHE)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                render.CACHE.update(dir=str(self.out("no_such_cache_dir")), ffmpeg="x")
                render.cache_store("export", "k" * 40, str(self.src), 1.0, {"verified": True})
                self.assertEqual(_common.STATE.warnings[-1]["code"], "cache_store_failed")
                with mock.patch.object(render.subprocess, "run", side_effect=OSError("no ffprobe")):
                    pair = render.ffmpeg_banner()
                self.assertEqual((_common.STATE.fallbacks[-1]["code"], _common.STATE.fallbacks[-1]["used"]),
                                 ("cache_ffmpeg_banner_unreadable", pair))
                with mock.patch.object(render, "file_key", side_effect=PermissionError(13, "denied")):
                    self.assertEqual(render._content_hash(str(self.src)), "missing")
                self.assertEqual(_common.STATE.warnings[-1]["code"], "cache_input_unreadable")
        finally:
            for b, v in saved.items():
                setattr(_common.STATE, b, v)
            render.CACHE.clear()
            render.CACHE.update(saved_cache)

    # ---------------------------------------------------------------- batch
    def batch_folder(self, name, steps):
        folder = self.out(name)
        folder.mkdir()
        shutil.copy(self.src, folder / "a.mp4")
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_b", "steps": steps}), encoding="utf-8")
        return folder, recipe

    def test_batch_a_failed_item_says_which_step_failed_and_why(self):
        """A failed item was {"ok": false} with no step, kind or message."""
        folder, recipe = self.batch_folder("bfail", [["cut.py", "{in}", "--start", "0", "--end", "1", "--quality", "99", "-o", "{out}"]])
        doc = json.loads(tool("batch", folder, "--recipe", recipe, "--json", check=False).stdout)
        err = doc["results"][0]["error"]
        self.assertEqual((err["step"], err["tool"], err["kind"]), (0, "cut.py", "input"))
        self.assertIn("--quality", err["message"])

    def test_batch_counts_a_completed_but_unverified_step_as_ok_and_says_it_is_unverified(self):
        """design-decisions: a spec miss is completed + verified false, not a failure. The row
        said ok and nothing more; it now says verified: false and which step's check failed, and
        the batch's own verified is the conjunction of its items'."""
        folder, recipe = self.batch_folder("bunver", [["export.py", "{in}", "--preset", "x", "-o", "{out}"]])
        doc = json.loads(tool("batch", folder, "--recipe", recipe, "--fast", "--json").stdout)
        row = doc["results"][0]
        self.assertEqual((row["ok"], row["verified"]), (True, False))
        self.assertEqual(row["unverified"], [{"step": 0, "tool": "export", "failed": ["loudness"]}])
        self.assertEqual((doc["processed"], doc["verified"]), (1, False))
        self.assertEqual(doc["verification"], [{"step": "item", "file": row["file"], "ok": False, "attribution": "unresolved"}])

    def test_batch_serves_a_cached_output_only_while_it_is_unchanged_and_records_a_reset_cache(self):
        """A cache hit checked only that the output existed, so a replaced output was served as
        "cached ok"; a corrupt cache file was reset without a word."""
        folder, recipe = self.batch_folder("bcache", [["fit.py", "{in}", "--height", "64", "-o", "{out}"]])
        run = lambda: json.loads(tool("batch", folder, "--recipe", recipe, "--fast", "--overwrite", "--json").stdout)  # noqa: E731
        run()
        self.assertTrue(run()["results"][0]["cached"])
        out = Path(run()["results"][0]["output"])
        shutil.copy(self.src, out)                       # someone replaced the delivered file
        doc = run()
        row = doc["results"][0]
        self.assertFalse(row.get("cached"))
        self.assertEqual(row["cache_miss"]["reason"], "output_changed")
        self.assertEqual(doc["diagnostics"]["warnings"][0]["code"], "batch_cache_output_changed")
        cache = folder / "out" / ".ffskill_cache.json"
        cache.write_text("{truncated", encoding="utf-8")
        doc = run()
        self.assertEqual(doc["diagnostics"]["warnings"][0]["code"], "batch_cache_reset")
        rec = json.loads((folder / "out" / ".ffskill-audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["event"], "batch_cache_reset")
        # the same file, not the same spelling: Windows' temp dir comes back as RUNNER~1 or runneradmin
        self.assertTrue(os.path.samefile(rec["details"]["path"], cache), rec["details"]["path"])

    def run_batch_in_process(self, folder, recipe, process):
        """batch.main() with process() replaced; returns (exit code, document)."""
        import batch
        import signal
        from unittest import mock
        out = io.StringIO()
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT))}
        code = 0
        try:
            with mock.patch.object(batch, "process", process), \
                    mock.patch.object(sys, "argv", ["batch.py", str(folder), "--recipe", str(recipe), "--force", "--json"]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                _common.STATE.reset()
                try:
                    batch.main()
                except SystemExit as exc:
                    code = exc.code
        finally:
            for s, h in handlers.items():
                signal.signal(s, h)
            _common.STATE.reset()
        return code, json.loads(out.getvalue())

    def test_batch_interrupted_reports_every_item_and_the_right_total(self):
        """Ctrl-C dropped the running and the not-started items: `total` counted only what had
        finished."""
        folder, recipe = self.batch_folder("bint", [["fit.py", "{in}", "--height", "64", "-o", "{out}"]])
        for name in ("b.mp4", "c.mp4"):
            shutil.copy(self.src, folder / name)
        calls = []

        def process(src, recipe, outdir, work, deadline=None):
            calls.append(src.name)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return {"file": str(src), "output": str(outdir / src.name), "ok": True, "verified": True, "seconds": 0.0}
        code, doc = self.run_batch_in_process(folder, recipe, process)
        self.assertEqual((code, doc["error"]["kind"], doc["total"], doc["processed"]), (130, "interrupted", 3, 1))
        rows = doc["results"]
        self.assertEqual([r["ok"] for r in rows], [True, False, False])
        self.assertTrue(rows[1]["interrupted"])
        self.assertEqual(rows[2]["skipped"], "interrupted")

    def test_batch_a_worker_that_raised_names_its_error_not_its_exit_code(self):
        """failed_row stored str(SystemExit), which is the exit code: "1"."""
        folder, recipe = self.batch_folder("bexit", [["fit.py", "{in}", "--height", "64", "-o", "{out}"]])

        def process(src, recipe, outdir, work, deadline=None):
            raise SystemExit(1)
        code, doc = self.run_batch_in_process(folder, recipe, process)
        err = doc["results"][0]["error"]
        self.assertIsInstance(err, dict)
        self.assertEqual((err["exception"], err["exit_code"]), ("SystemExit", 1))
        self.assertNotEqual(err["message"], "1")

    def test_batch_recipe_key_records_an_unreadable_project(self):
        import batch
        saved = list(_common.STATE.warnings)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                batch.recipe_key({"project": str(self.out("no_such_project.json"))})
            self.assertEqual(_common.STATE.warnings[-1]["code"], "recipe_project_unreadable")
        finally:
            _common.STATE.warnings[:] = saved

    # ---------------------------------------------------------------- verify
    def test_verify_keeps_the_tools_own_failure_and_lists_the_steps_it_skipped(self):
        """A step's error was its last stderr line or a fixed string ("ffprobe failed"), its kind was
        lost, and steps that did not apply were dropped."""
        garbage = self.out("garbage.mp4")
        garbage.write_bytes(b"\0not media" * 100)
        wav = self.out("tone.wav")
        ffmpeg("-i", self.src, "-vn", "-c:a", "pcm_s16le", wav)
        proc = tool("verify", garbage, wav, "--quick", "--out", self.out("verify_out"), "--json", check=False)
        doc = json.loads(proc.stdout)
        bad, audio = doc["files"]
        self.assertEqual(bad["steps"][0]["kind"], "input")
        self.assertNotEqual(bad["steps"][0]["error"], "ffprobe failed")
        self.assertEqual(bad["skipped"][0]["reason"], "input_unreadable")
        self.assertIn(("export x", "no_video"), [(s["step"], s["reason"]) for s in audio["skipped"]])
        import verify
        r = verify.step("cut", ["cut.py", str(self.out("missing.mp4")), "--start", "0", "--end", "1", "-o", str(self.out("v.mp4"))], 120)
        self.assertEqual((r["ok"], r["kind"]), (False, "input"))
        self.assertIn("missing.mp4", r["message"])


class SilentFallbackTests(unittest.TestCase):
    """docs/design-decisions.md, "Nothing happens silently" (part 3): the fallbacks, skips and
    stderr-only warnings that remained, each now a `diagnostics` record or a structured field.
    In-process where the decision is a function; one small fixture for the tools that run."""

    BUCKETS = ("warnings", "fallbacks", "skipped", "notes")

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ffskill_silent3_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        runner = sys.modules["_common.runner"]
        self.saved = (_common.STATE.dry_run, _common.STATE.timeout, runner._ENCODERS, runner._BSFS, dict(getattr(runner, "_LIST_ERRORS", {})))
        _common.STATE.dry_run = False
        for bucket in self.BUCKETS:
            setattr(_common.STATE, bucket, [])

    def tearDown(self):
        runner = sys.modules["_common.runner"]
        _common.STATE.dry_run, _common.STATE.timeout, runner._ENCODERS, runner._BSFS, errors = self.saved
        if hasattr(runner, "_LIST_ERRORS"):
            runner._LIST_ERRORS.clear()
            runner._LIST_ERRORS.update(errors)
        for bucket in self.BUCKETS:
            setattr(_common.STATE, bucket, [])

    def codes(self, bucket):
        return [e["code"] for e in getattr(_common.STATE, bucket)]

    def media(self):
        """A 6 s 320x180 clip with a tone, made once per class (each test that runs a tool needs one)."""
        src = self.tmp / "src.mp4"
        if not src.exists():
            require_ffmpeg_or_skip("ffmpeg", "ffprobe")
            ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONE}':s=48000",
                   "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", src)
        return src

    class Refused(Exception):
        pass

    def refuse_raises(self):
        def refuse(kind, reason, msg, **kw):
            raise self.Refused(dict(kw, kind=kind, reason=reason, message=msg))
        return refuse

    # ------------------------------------------------------------------ the runner
    def test_an_odd_sized_source_scaled_to_even_is_a_recorded_fallback(self):
        """runner.run()'s even_retry re-ran an encode that failed on odd dimensions with an even
        scale and said so on stderr only; the output is a pixel smaller than the source."""
        odd = self.tmp / "odd.mp4"
        require_ffmpeg_or_skip("ffmpeg", "ffprobe")
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=161x91:rate=25:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv444p", odd)
        doc = json.loads(tool("denoise", odd, "-o", self.tmp / "odd_dn.mp4", "--fast", "--json").stdout)
        fb = doc["diagnostics"]["fallbacks"]
        self.assertEqual([f["code"] for f in fb], ["odd_dimensions_scaled_even"])
        self.assertEqual(fb[0]["scale"], _common.EVEN_SCALE)
        self.assertEqual((doc["probe"]["video"]["width"], doc["probe"]["video"]["height"]), (160, 90))

    def test_a_measurement_skipped_for_a_pending_input_reaches_the_document(self):
        """dry_run_input_pending(): "measurement skipped" went to stderr only, though
        design-decisions promised a note. It is a diagnostics.skipped entry, once per path."""
        _common.STATE.dry_run = True
        missing = str(self.tmp / "not_yet.mp4")
        self.assertTrue(_common.dry_run_input_pending(missing))
        self.assertTrue(_common.dry_run_input_pending(missing))
        self.assertEqual(self.codes("skipped"), ["measurement_input_pending"])
        self.assertEqual(_common.STATE.skipped[0]["path"], missing)
        _common.STATE.dry_run = False
        self.assertFalse(_common.dry_run_input_pending(missing))
        # end to end: a dry run of loudness.py on a file an earlier stage would write
        doc = json.loads(tool("loudness", missing, "-o", self.tmp / "ln.mp4", "--dry-run", "--json").stdout)
        self.assertEqual([s["code"] for s in doc["diagnostics"]["skipped"]], ["measurement_input_pending"])

    def test_an_unreadable_encoder_list_is_named_not_taken_for_a_missing_encoder(self):
        """ffmpeg_encoders()/ffmpeg_bsfs() turned a list that could not be read into an empty set,
        and --codec av1/prores then refused with "this build has neither", --hw's note with "this
        build has no h264_videotoolbox". The read failure is kept, recorded once, and named."""
        from unittest import mock
        runner = sys.modules["_common.runner"]
        decision = sys.modules["_common.decision"]
        runner._ENCODERS = runner._BSFS = None
        with mock.patch.object(runner.subprocess, "run", side_effect=OSError("exec format error")):
            self.assertEqual(_common.ffmpeg_encoders(), set())
            self.assertEqual(_common.ffmpeg_bsfs(), set())
        self.assertIn("exec format error", _common.ffmpeg_list_error("encoders"))
        self.assertEqual([(w["code"], w["list"]) for w in _common.STATE.warnings],
                         [("ffmpeg_list_unreadable", "encoders"), ("ffmpeg_list_unreadable", "bsfs")])
        with mock.patch.object(decision, "refuse", self.refuse_raises()):
            for codec, encoders in (("av1", ["libsvtav1", "libaom-av1"]), ("prores", ["prores_ks"])):
                with self.assertRaises(self.Refused) as r:
                    decision._cpu_encoder_args(codec, 23, "medium", None)
                got = r.exception.args[0]
                self.assertEqual((got["kind"], got["reason"], got["encoders"]), ("ffmpeg", "encoder_list_unreadable", encoders))
                self.assertIn("exec format error", got["message"])
                self.assertNotIn("has neither", got["message"])
            # a list that was read and lacks the encoder is the missing_tool refusal it always was
            runner._ENCODERS = {"libx264"}
            with self.assertRaises(self.Refused) as r:
                decision._cpu_encoder_args("av1", 23, "medium", None)
            self.assertEqual((r.exception.args[0]["kind"], r.exception.args[0]["reason"]), ("missing_tool", "encoder_missing"))
        # --hw's CPU note says the list could not be read, not that the build lacks the encoder
        runner._ENCODERS = set()
        saved_notes = list(_common.STATE.hw_notes)
        try:
            with mock.patch.object(decision, "hw_platform_reason", return_value=None):
                self.assertIsNone(decision._vt_args("h264", 23, None, True))
            self.assertTrue(any("could not be confirmed" in n and "exec format error" in n for n in _common.STATE.hw_notes),
                            _common.STATE.hw_notes)
        finally:
            _common.STATE.hw_notes[:] = saved_notes

    def test_the_libaom_fallback_and_a_clamped_crf_are_recorded(self):
        """decision.py chose libaom-av1 when SVT-AV1 was missing, and capped the HEVC HDR line's
        CRF+2 at 51, without a word."""
        from unittest import mock
        decision = sys.modules["_common.decision"]
        with mock.patch.object(decision, "ffmpeg_encoders", return_value={"libaom-av1"}):
            args = decision._cpu_encoder_args("av1", 30, "medium", None)
            decision._cpu_encoder_args("av1", 30, "medium", None)
        self.assertEqual(args[args.index("-c:v") + 1], "libaom-av1")
        self.assertEqual(self.codes("fallbacks"), ["av1_encoder_libaom"], "recorded once however many encodes take it")
        hdr = {"video": {"bt2020_or_hdr": True, "color_transfer": "smpte2084"}}
        args = decision._cpu_encoder_args("hevc", 50, "medium", hdr)
        self.assertEqual(args[args.index("-crf") + 1], "51")
        w = _common.STATE.warnings[-1]
        self.assertEqual((w["code"], w["requested"], w["asked"], w["used"]), ("crf_clamped", 50, 52, 51))
        _common.STATE.warnings.clear()
        decision._cpu_encoder_args("hevc", 20, "medium", hdr)
        self.assertEqual(self.codes("warnings"), [], "an unclamped CRF records nothing")

    def test_run_keeping_subtitles_records_the_first_attempts_error(self):
        """A subtitle stream the container cannot hold made the first attempt fail; the retry
        without it was reported only as dropped_non_av_streams: true, with no reason."""
        src = self.media()
        srt = self.tmp / "a.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        subbed = self.tmp / "subbed.mkv"
        ffmpeg("-i", src, "-i", srt, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt", subbed)
        doc = json.loads(tool("denoise", subbed, "-o", self.tmp / "subbed_dn.mp4", "--fast", "--json").stdout)
        self.assertTrue(doc["dropped_non_av_streams"])
        fb = doc["diagnostics"]["fallbacks"][0]
        self.assertEqual(fb["code"], "non_av_streams_dropped")
        self.assertNotEqual(fb["returncode"], 0)
        self.assertTrue(fb["error"], "the first attempt's error is kept")

    def test_an_invalid_ffmpeg_skill_timeout_is_a_recorded_warning(self):
        """FFMPEG_SKILL_TIMEOUT=abc silently became 1800 s, and -5 silently meant no limit."""
        src = self.media()
        for value, limit in (("abc", 1800.0), ("nan", 1800.0), ("-5", 0.0)):
            env = dict(os.environ, FFMPEG_SKILL_TIMEOUT=value)
            doc = json.loads(tool("cut", src, "--start", "0", "--end", "1", "-o", self.tmp / "t.mp4", "--dry-run", "--json", env=env).stdout)
            w = doc["diagnostics"]["warnings"]
            self.assertEqual([(x["code"], x["value"], x["timeout"]) for x in w], [("timeout_env_invalid", value, limit)])
        # an explicit --timeout makes the variable irrelevant, and a valid value says nothing
        env = dict(os.environ, FFMPEG_SKILL_TIMEOUT="abc")
        doc = json.loads(tool("cut", src, "--start", "0", "--end", "1", "-o", self.tmp / "t.mp4", "--dry-run", "--json", "--timeout", "60", env=env).stdout)
        self.assertNotIn("diagnostics", doc)
        doc = json.loads(tool("cut", src, "--start", "0", "--end", "1", "-o", self.tmp / "t.mp4", "--dry-run", "--json",
                              env=dict(os.environ, FFMPEG_SKILL_TIMEOUT="90")).stdout)
        self.assertNotIn("diagnostics", doc)

    # ------------------------------------------------------------------ tools
    def test_filler_words_with_no_timing_are_counted(self):
        """filler_spans() skipped a listed word with no measured timing; silence.py's word reader
        dropped it even before that. Both are counted (matched_untimed / matched_too_long)."""
        stats = {}
        spans = _common.filler_spans([{"word": "um", "start": 1.0, "end": 1.2}, {"word": "um"},
                                      {"word": "uh", "start": 2.0, "end": 1.0}, {"word": "um", "start": 3.0, "end": 5.0}],
                                     {"um", "uh"}, stats=stats)
        self.assertEqual(len(spans), 1)
        self.assertEqual(stats, {"matched_untimed": 2, "matched_too_long": 1})
        src = self.media()
        words = self.tmp / "words.json"
        words.write_text(json.dumps({"words": [{"word": "um", "start": 1.0, "end": 1.2}, {"word": "uh"},
                                               {"word": "hello", "start": 2.0, "end": 2.4}]}), encoding="utf-8")
        doc = json.loads(tool("silence", src, "--filler", "--words", words, "--filler-lang", "en", "--list", "--json").stdout)
        self.assertEqual((doc["filler"]["matched_untimed"], doc["filler"]["matched_too_long"]), (1, 0))
        self.assertEqual(doc["filler"]["word_timings"], 2)
        self.assertEqual([w["code"] for w in doc["diagnostics"]["warnings"]], ["filler_words_untimed"])

    def test_a_skipped_drift_correction_says_why(self):
        """sync.py --fix-drift on a pair too short to measure skipped the correction with a
        stderr warning only; drift_skipped_reason and a diagnostics.skipped entry now say so."""
        src = self.media()
        mic = self.tmp / "mic.wav"
        ffmpeg("-ss", "1.5", "-i", src, "-vn", "-c:a", "pcm_s16le", mic)
        doc = json.loads(tool("sync", src, mic, "--fix-drift", "--json").stdout)
        self.assertEqual(doc["drift_skipped_reason"], "too_short")
        self.assertEqual(doc["sources"][0]["drift_skipped_reason"], "too_short")
        sk = doc["diagnostics"]["skipped"][0]
        self.assertEqual((sk["code"], sk["reason"], sk["path"]), ("drift_correction_skipped", "too_short", str(mic)))
        self.assertNotIn("drift_skipped_reason", json.loads(tool("sync", src, mic, "--json").stdout), "only with --fix-drift")

    def test_cropdetect_counts_the_windows_it_could_not_decode(self):
        """A window ffmpeg could not decode was skipped unseen; the crop then rested on fewer
        readings than --samples said."""
        from unittest import mock
        import cropdetect
        real = cropdetect.run_analysis
        calls = []

        def flaky(cmd, check=True, **kw):
            calls.append(cmd)
            if len(calls) == 2:
                return subprocess.CompletedProcess(cmd, 1, "", "Invalid data found when processing input\n")
            return real(cmd, check=check, **kw)
        src = self.media()
        failed = []
        with mock.patch.object(cropdetect, "run_analysis", flaky):
            rects = cropdetect.detect(str(src), 5.0, 5, 0.0941176, 16, 6.0, failed)
        self.assertTrue(rects)
        self.assertEqual(len(failed), 1)
        self.assertIn("Invalid data", failed[0]["error"])
        doc = json.loads(tool("cropdetect", src, "--json").stdout)
        self.assertEqual((doc["windows"], doc["windows_failed"]), (5, 0))

    def test_caption_counts_ass_lines_it_could_not_shift_or_read(self):
        """caption.py --ass --offset copied a Dialogue line with unreadable timestamps unshifted,
        parse_ass_cues() left it out of the visible-cue count, and the shift count went to stderr
        only. Each count is in `caption`, and each non-zero one is a warning."""
        src = self.media()
        ass = self.tmp / "s.ass"
        ass.write_text("[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
                       "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                       "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Hello\n"
                       "Dialogue: 0,bad,0:00:03.00,Default,,0,0,0,,Broken\n"
                       "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,World\n", encoding="utf-8")
        doc = json.loads(tool("caption", src, "--ass", ass, "--offset", "1", "-o", self.tmp / "cap.mp4", "--dry-run", "--json").stdout)
        cap = doc["caption"]
        self.assertEqual((cap["ass_shifted"], cap["ass_unshifted"], cap["ass_malformed"]), (2, 1, 1))
        self.assertEqual(sorted(w["code"] for w in doc["diagnostics"]["warnings"]), ["ass_lines_malformed", "ass_lines_unshifted"])
        self.assertEqual(doc["font_used"]["how"], "ass_styles")

    def test_a_timeline_that_does_not_parse_keeps_the_reason(self):
        """timeline.parses() returned False and discarded the exception, so render.py's parse
        verification step said ok: false with no reason anywhere."""
        from _common import timeline as tlmod
        bad = self.tmp / "bad.fcpxml"
        bad.write_text("<fcpxml><unclosed>", encoding="utf-8")
        self.assertFalse(tlmod.parses(str(bad), "fcpxml"))
        w = _common.STATE.warnings[-1]
        self.assertEqual((w["code"], w["format"]), ("timeline_parse_failed", "fcpxml"))
        self.assertIn("ParseError", w["error"])
        other = self.tmp / "other.otio"
        other.write_text("[1, 2]", encoding="utf-8")
        self.assertFalse(tlmod.parses(str(other), "otio"), "a JSON list is not a timeline (and no longer an AttributeError)")
        good = self.tmp / "good.otio"
        good.write_text(json.dumps({"OTIO_SCHEMA": "Timeline.1"}), encoding="utf-8")
        self.assertTrue(tlmod.parses(str(good), "otio"))
        self.assertEqual(len(_common.STATE.warnings), 2)

    def test_the_font_drawn_with_is_reported_and_a_substitute_recorded(self):
        """fonts.default_font_file() returned whatever fontconfig (or the Windows Fonts folder)
        answered; a family that is not installed was drawn in another without a word."""
        from unittest import mock
        fonts = sys.modules["_common.fonts"]
        face = self.tmp / "Other.ttf"
        face.write_bytes(b"\0")
        answer = subprocess.CompletedProcess([], 0, f"{face}\nOther Sans,Other Sans Book\n", "")
        with mock.patch.object(fonts.platform, "system", return_value="Linux"), \
                mock.patch.object(fonts.shutil, "which", return_value="/usr/bin/fc-match"), \
                mock.patch.object(fonts.subprocess, "run", return_value=answer):
            got = fonts.resolve_font("Wanted Serif")
            same = fonts.resolve_font("Other Sans")
            alias = fonts.resolve_font("sans-serif")
        self.assertEqual((got["file"], got["family"], got["substituted"], got["via"]), (str(face), "Other Sans", True, "fc-match"))
        self.assertFalse(same["substituted"])
        self.assertFalse(alias["substituted"], "a generic alias is resolved, not substituted")
        with mock.patch.object(fonts, "resolve_font", return_value=got):
            choice = fonts.record_font_choice(fonts.font_choice("Wanted Serif"))
        self.assertEqual((choice["how"], choice["file"], choice["substituted"]), ("resolved", str(face), True))
        self.assertEqual(self.codes("fallbacks"), ["font_substituted"])
        self.assertEqual(fonts.font_choice("X", font_file="/f.ttf")["how"], "font_file")
        # end to end: overlay.py reports the font it handed drawtext
        src = self.media()
        doc = json.loads(tool("overlay", src, "--text", "Hi", "--font", "No Such Family Qx", "-o", self.tmp / "ov.mp4", "--dry-run", "--json").stdout)
        used = doc["font_used"]
        self.assertEqual(used["asked"], "No Such Family Qx")
        if used["how"] == "by_name":
            self.skipTest("no font resolves to a file on this machine (no fc-match, no Windows Arial)")
        self.assertTrue(used["substituted"])
        self.assertEqual([f["code"] for f in doc["diagnostics"]["fallbacks"]], ["font_substituted"])

    def test_stderr_only_warnings_reach_the_document(self):
        """overlay.py's emoji lines, color.py --strip-dovi with no Dolby Vision, and render.py's
        frame-from-preset and --normalize defaults were stderr only."""
        src = self.media()
        doc = json.loads(tool("overlay", src, "--text", "Hi \U0001F600", "--emoji", "none", "-o", self.tmp / "e1.mp4", "--dry-run", "--json").stdout)
        self.assertIn("emoji_stripped", [w["code"] for w in doc["diagnostics"]["warnings"]])
        doc = json.loads(tool("overlay", src, "--text", "Hi \U0001F600", "-o", self.tmp / "e2.mp4", "--dry-run", "--json").stdout)
        self.assertIn("emoji_monochrome", [w["code"] for w in doc["diagnostics"]["warnings"]])
        hevc = self.tmp / "plain.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30", "-t", "1", "-c:v", "libx265", "-preset", "ultrafast",
               "-x265-params", "log-level=error", "-tag:v", "hvc1", hevc)
        doc = json.loads(tool("color", hevc, "--strip-dovi", "-o", self.tmp / "nodv.mp4", "--dry-run", "--json").stdout)
        self.assertEqual([w["code"] for w in doc["diagnostics"]["warnings"]], ["dovi_not_detected"])
        proj = self.tmp / "proj.json"
        proj.write_text(json.dumps({"output": str(self.tmp / "r.mp4"), "clips": [{"src": str(src), "in": "0:01", "out": "0:03"}],
                                    "frame": {"aspect": "9:16"}, "export": {"preset": "reels"}}), encoding="utf-8")
        proc = tool("render", proj, "--dry-run", "--json")
        warned = {w["code"]: w for w in json.loads(proc.stdout)["diagnostics"]["warnings"]}
        self.assertEqual((warned["frame_from_export_preset"]["width"], warned["frame_from_export_preset"]["height"]), (1080, 1920))
        self.assertEqual(warned["normalize_on_by_default"]["preset"], "reels")
        self.assertIn("frame: 1080x1920 from the reels export preset", proc.stderr, "the stderr line stays")

    def test_graphics_pinned_to_drawtext_on_a_newline_glyph_build_is_a_warning(self):
        """graphics.py --text-render drawtext with a multi-line label on FFmpeg 8.0-8.0.1/8.1.0
        draws a box at each line break; the warning was stderr only. Runs where the build has
        the bug (the 8.0.1 CI job, or a local 8.0.1 build first on PATH)."""
        if not _common.drawtext_draws_newline_glyph():
            self.skipTest("this ffmpeg's drawtext does not draw a box at a line break")
        src = self.media()
        doc = json.loads(tool("graphics", src, "--template", "title", "--title", "one\ntwo", "--text-render", "drawtext",
                              "-o", self.tmp / "g.mp4", "--dry-run", "--json").stdout)
        self.assertIn("drawtext_newline_glyph", [w["code"] for w in doc["diagnostics"]["warnings"]])

    # ------------------------------------------------------------------ source checks
    def test_no_stderr_only_warning_is_left_in_the_sources(self):
        """A `warning:` line printed with info() reaches stderr and no document. Every one goes
        through warn() (stderr AND diagnostics.warnings), with no exception left."""
        pattern = re.compile(r"""\b(?:info|print)\(\s*f?["']warning\b|sys\.stderr\.write\(\s*f?["']warning\b""", re.I)
        left = {}
        for path in script_sources() + [ROOT / "mcp" / "server.py"]:
            for line in path.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0]
                if pattern.search(code) and not code.strip().startswith(("(", '"', "'")):
                    left[path.name] = left.get(path.name, 0) + 1
        self.assertEqual(left, {}, "stderr-only warnings: use warn(msg, code, ...) so the line reaches --json too")

    def test_every_diagnostic_code_is_in_the_contract_under_its_bucket(self):
        """json_output.diagnostic_codes is the list a caller switches on: every warn() /
        record_fallback() / record_skip() call under scripts/ names a code listed there under the
        bucket the call writes to, and the contract lists no code nothing records."""
        bucket_of = {"warn": "warnings", "record_fallback": "fallbacks", "record_skip": "skipped"}
        used = {}
        for path in script_sources():
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"(?<![\w.])(warn|record_fallback|record_skip)\(", text):
                if text[max(0, m.start() - 4):m.start()] == "def ":
                    continue
                depth, i = 1, m.end()
                while depth and i < len(text):
                    depth += {"(": 1, ")": -1}.get(text[i], 0)
                    i += 1
                body = text[m.end():i - 1]
                literals = re.findall(r"""["']([a-z][a-z0-9_]+)["']""", body)
                if not body.strip() or not literals:
                    continue  # a mention in prose ("warn()"), or a call whose code is a variable
                listed = [c for c in literals if c in _contract.DIAGNOSTIC_CODES]
                self.assertTrue(listed, f"{path.name}: {m.group(1)}({body[:70]}...) names no code in _contract.DIAGNOSTIC_CODES")
                code = listed[0]
                self.assertEqual(_contract.DIAGNOSTIC_CODES[code][0], bucket_of[m.group(1)], f"{code}: recorded as {m.group(1)}")
                used[code] = path.name
        self.assertEqual(sorted(set(_contract.DIAGNOSTIC_CODES) - set(used)), [], "the contract lists codes nothing records")
        published = _contract.build(detect=False)["json_output"]["diagnostic_codes"]
        self.assertEqual(set(published), set(_contract.DIAGNOSTIC_CODES))


class FfmpegSecurityTableTests(unittest.TestCase):
    """doctor's `ffmpeg_security` table and comparison, without running ffmpeg (every OS)."""

    def test_ffmpeg_security_compares_with_the_fix_on_the_version_s_branch(self):
        """doctor's FFmpeg advisory: a version older than the first upstream release on its branch
        that fixes a listed CVE gets a warning; a fixed or newer one, an unparseable one and no
        binary get none. The wording never claims the build is vulnerable (distros backport)."""
        cases = {
            "8.0.1-3ubuntu2": ("older_than_fix", "8.0.3", True),
            "8.0.2": ("older_than_fix", "8.0.3", True),
            "8.0.3": ("not_older", None, None),
            "8.1": ("older_than_fix", "8.1.2", True),
            "n8.1.1": ("older_than_fix", "8.1.2", True),
            "8.1.2-full_build-www.gyan.dev": ("not_older", None, None),
            "9.0": ("not_older", None, None),
            "9.0.1-essentials_build-www.gyan.dev": ("not_older", None, None),
            "10.0": ("not_older", None, None),
            "7.1.2-0+deb13u1": ("older_than_fix", "8.0.3", False),
            "6.1.1-3ubuntu5": ("older_than_fix", "8.0.3", False),
            "N-121234-g0123abcd": ("unknown", None, None),
            "2026-10-01-git-0123abcd-full_build-www.gyan.dev": ("unknown", None, None),
            "unknown": ("unknown", None, None),
            None: ("unknown", None, None),
        }
        for version, (status, first_fix, on_branch) in cases.items():
            with self.subTest(version=version):
                sec = _contract.ffmpeg_security({"ffmpeg": version, "ffprobe": None})
                self.assertEqual(sec["ffmpeg"]["status"], status)
                self.assertEqual(sec["ffprobe"]["status"], "unknown")
                if first_fix is None:
                    self.assertEqual(sec["ffmpeg"]["advisories"], [])
                    self.assertEqual(sec["warnings"], [])
                    continue
                adv = sec["ffmpeg"]["advisories"][0]
                self.assertEqual((adv["cve"], adv["first_fix"], adv["fix_on_branch"]), ("CVE-2026-8461", first_fix, on_branch))
                self.assertEqual(len(sec["warnings"]), 1)
                line = sec["warnings"][0]
                self.assertTrue(line.startswith(f"warning: ffmpeg {version} is older than"), line)
                self.assertNotIn("\n", line)
                self.assertIn("CVE-2026-8461", line)
                self.assertIn(first_fix, line)
                self.assertIn("backported", line)
                self.assertIn("not proof the build is vulnerable", line)
                self.assertIn(_contract.FFMPEG_ADVISORIES_CHECKED, line)
                if "ubuntu" in version or "+deb" in version:
                    self.assertIn("sudo apt", line)
        # the same version on both binaries warns once; a different ffprobe gets its own line
        same = _contract.ffmpeg_security({"ffmpeg": "8.0.1", "ffprobe": "8.0.1"})
        self.assertEqual(len(same["warnings"]), 1)
        self.assertEqual(same["ffprobe"]["status"], "older_than_fix")
        mixed = _contract.ffmpeg_security({"ffmpeg": "9.0", "ffprobe": "8.1.1"})
        self.assertEqual(len(mixed["warnings"]), 1)
        self.assertTrue(mixed["warnings"][0].startswith("warning: ffprobe 8.1.1"))

    def test_ffmpeg_advisory_table_is_dated_sourced_and_documented(self):
        """The table is hand-maintained: it names its source and the day it was checked, every
        fixing release parses, and docs/contract.md states the same date and field."""
        import datetime
        datetime.date.fromisoformat(_contract.FFMPEG_ADVISORIES_CHECKED)
        self.assertEqual(_contract.FFMPEG_ADVISORY_SOURCE, "https://ffmpeg.org/security.html")
        self.assertTrue(_contract.FFMPEG_ADVISORIES)
        for adv in _contract.FFMPEG_ADVISORIES:
            self.assertRegex(adv["cve"], r"^CVE-\d{4}-\d+$")
            self.assertGreaterEqual(adv["cvss"], 7.0, "the table lists high-severity CVEs only")
            for branch, fix in adv["fixed_in"].items():
                v = _contract._parse_ffmpeg_version(fix)
                self.assertIsNotNone(v, fix)
                self.assertEqual(f"{v[0]}.{v[1]}", branch)
        contract_md = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
        self.assertIn("`ffmpeg_security`", contract_md)
        self.assertIn(_contract.FFMPEG_ADVISORIES_CHECKED, contract_md)
        for adv in _contract.FFMPEG_ADVISORIES:
            self.assertIn(adv["cve"], contract_md)
        self.assertIn("ffmpeg_security", (ROOT / "README.md").read_text(encoding="utf-8"))
        # offline: the advisory is a table lookup, the module opens no connection
        src = (SCRIPTS / "_contract.py").read_text(encoding="utf-8")
        for mod in ("urllib", "http.client", "socket", "requests"):
            self.assertNotRegex(src, rf"(?m)^\s*(import|from) {re.escape(mod)}\b", mod)


@unittest.skipIf(platform.system() == "Windows", "every test here drives a fake ffmpeg via a #!/bin/sh POSIX shell shim on PATH to force specific fixture layouts; not portable to Windows. doctor's own detection logic still runs against the REAL ffmpeg on Windows CI through ContractTests' setUpClass and test_doctor_reports_this_installed_copys_own_version -- what's untested on Windows specifically is the fixture-driven FFmpeg 6/7/8/9 layout-parsing behaviour this class exists to pin. See README, 'Development'.")
class DoctorDetectionTests(unittest.TestCase):
    """Capability detection reads every `ffmpeg -filters` layout and never confuses "unreadable" with "absent".

    FFmpeg 8 shortened the flag column of `ffmpeg -filters` from three characters (`..C`) to two
    (`T.`); ffmpeg-skill 0.9.0 anchored on the three-character column and reported every filter
    missing on FFmpeg 8. These tests drive `doctor` through a fake `ffmpeg` on PATH that prints a
    fixture from tests/fixtures/ for each listing flag.
    """

    FIX = ROOT / "tests" / "fixtures"

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="doctor-"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _doctor(self, filters, encoders="ffmpeg_encoders_6.1.txt", bsfs="ffmpeg_bsfs_6.1.txt", filters_exit=0):
        """`doctor --json` with a fake ffmpeg that prints the named fixtures (stdout cat, no shell interpolation of names)."""
        shim = self.work / "shim"
        shim.mkdir(exist_ok=True)
        script = "#!/bin/sh\ncase \"$2\" in\n"
        for flag, name, code in (("-filters", filters, filters_exit), ("-encoders", encoders, 0), ("-bsfs", bsfs, 0)):
            script += f"  {flag}) cat '{self.FIX / name}'; exit {code};;\n"
        script += "esac\ncase \"$1\" in -version) echo 'ffmpeg version 8.0-fixture'; exit 0;; esac\nexit 1\n"
        (shim / "ffmpeg").write_text(script)
        (shim / "ffmpeg").chmod(0o755)
        # ffprobe stays the real one; PATH keeps the rest so python/whisper detection is unchanged
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
        return json.loads(proc.stdout), proc.returncode

    # 6.1, 8.1.2 and 9.0.1 are captures (Ubuntu apt, Homebrew on the macOS runner, gyan.dev build on the Windows runner);
    # 7.1 is a constructed layout (FFmpeg 7 prints the 6.x layout, no capture at hand)
    FILTER_FIXTURES = ("ffmpeg_filters_6.1.txt", "ffmpeg_filters_7.1_constructed.txt", "ffmpeg_filters_8.1.2_macos.txt", "ffmpeg_filters_9.0.1_windows.txt")

    def test_parser_reads_ffmpeg_6_7_8_9_layouts(self):
        for name in self.FILTER_FIXTURES:
            names = _contract._parse_ff_list("-filters", (self.FIX / name).read_text())
            self.assertGreater(len(names), 450, name)
            for f in ("xfade", "loudnorm", "acompressor", "abuffer", "concat", "scale"):
                self.assertIn(f, names, f"{f} in {name}")
            self.assertNotIn("=", names, name)
            self.assertNotIn("Filters:", names, name)
            self.assertNotIn("------", names, name)
            self.assertEqual(len(names), len(set(names)), f"{name}: no row read twice")
        # the real 9.0.1 capture: two flag characters per row, a three-character legend, a separator, CRLF
        raw = (self.FIX / "ffmpeg_filters_9.0.1_windows.txt").read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertIn(b" TS aap ", raw)
        names9 = _contract._parse_ff_list("-filters", raw.decode())
        self.assertEqual(len(names9), 527)
        self.assertIn("aap", names9)  # a two-flag row with a two-input io-spec (AA->A)
        # the Homebrew 8.1.2 build has no libfreetype / libass: drawtext is absent from its listing, which is
        # what doctor must report (missing), and the other three builds do carry it
        self.assertNotIn("drawtext", _contract._parse_ff_list("-filters", (self.FIX / "ffmpeg_filters_8.1.2_macos.txt").read_text()))
        for name in ("ffmpeg_filters_6.1.txt", "ffmpeg_filters_9.0.1_windows.txt"):
            self.assertIn("drawtext", _contract._parse_ff_list("-filters", (self.FIX / name).read_text()), name)
        for enc_name in ("ffmpeg_encoders_6.1.txt", "ffmpeg_encoders_8.1.2_macos.txt", "ffmpeg_encoders_9.0.1_windows.txt"):
            enc = _contract._parse_ff_list("-encoders", (self.FIX / enc_name).read_text())
            self.assertIn("libx264", enc, enc_name)
            self.assertIn("aac", enc, enc_name)
            self.assertNotIn("=", enc, enc_name)
        for bsf_name in ("ffmpeg_bsfs_6.1.txt", "ffmpeg_bsfs_8.1.2_macos.txt", "ffmpeg_bsfs_9.0.1_windows.txt"):
            self.assertIn("filter_units", _contract._parse_ff_list("-bsfs", (self.FIX / bsf_name).read_text()), bsf_name)
        self.assertEqual(_contract._parse_ff_list("-filters", (self.FIX / "ffmpeg_filters_garbage.txt").read_text()), [])

    def test_two_character_flags_do_not_hide_filters(self):
        """The FFmpeg 8 layout: every declared filter is found, nothing is reported missing or unknown."""
        absent_in_brew = {"filter:drawtext", "filter:subtitles", "filter:ass", "filter:zscale", "filter:vidstabdetect", "filter:vidstabtransform"}  # not built into Homebrew's 8.1.2 (no --enable-libvidstab)
        for name in self.FILTER_FIXTURES:
            d, code = self._doctor(name)
            declared = [c for c in _contract.required_capabilities()["required"] + _contract.required_capabilities()["optional"] if c.startswith("filter:")]
            self.assertTrue(declared)
            expected_missing = absent_in_brew if "8.1.2" in name else set()
            for cap in declared:
                self.assertIn(cap, d["missing"] + d["missing_optional"] if cap in expected_missing else d["available"], f"{cap} with {name}")
            self.assertEqual({c for c in d["missing"] + d["missing_optional"] if c.startswith("filter:")}, expected_missing, name)
            self.assertEqual(d["unknown"], [], name)
            self.assertEqual(d["detection"]["filters"]["status"], "parsed", name)
            self.assertEqual(d["ok"], not expected_missing, name)
            self.assertEqual(code, 1 if expected_missing else 0, name)

    def test_drawtext_crash_downgrades_a_listed_filter_to_missing(self):
        """#100: `-filters` correctly lists drawtext (this ffmpeg build was compiled with it), but
        a real one-frame render crashes -- an access-violation-style bug on some real Windows
        builds. doctor must not repeat "missing required: none" in that case; it has to actually
        run the probe and report drawtext missing, not just trust the listing."""
        shim = self.work / "shim"
        shim.mkdir(exist_ok=True)
        script = "#!/bin/sh\ncase \"$2\" in\n"
        for flag, name, code in (("-filters", "ffmpeg_filters_6.1.txt", 0), ("-encoders", "ffmpeg_encoders_6.1.txt", 0), ("-bsfs", "ffmpeg_bsfs_6.1.txt", 0)):
            script += f"  {flag}) cat '{self.FIX / name}'; exit {code};;\n"
        script += "esac\ncase \"$1\" in -version) echo 'ffmpeg version 8.0-fixture'; exit 0;; esac\n"
        # simulate the real Windows crash: killed by a signal, so subprocess.run reports a negative
        # returncode (the only portable way to reproduce "crashed" from a POSIX shell shim -- the
        # real bug is a huge positive exit code on Windows, but this class only runs on POSIX)
        script += "case \"$*\" in *drawtext=*) kill -s SEGV $$;; esac\nexit 1\n"
        (shim / "ffmpeg").write_text(script)
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
        d = json.loads(proc.stdout)
        self.assertIn("filter:drawtext", d["missing"])
        self.assertNotIn("filter:drawtext", d["available"])
        self.assertTrue(any("filter:drawtext" in e and "crashed" in e for e in d["errors"]), d["errors"])
        self.assertFalse(d["ok"])
        self.assertEqual(proc.returncode, 1)

    def test_drawtext_fontconfig_crash_alone_keeps_drawtext_available(self):
        """#298: on gyan.dev 9.x only a fontconfig lookup crashes; the fontfile= the tools pass
        renders. doctor probes the way the tools call drawtext, so drawtext stays available and
        the fontconfig crash is a note, not a missing required capability."""
        if not shutil.which("fc-match"):
            self.skipTest("default_font_file() resolves no fontfile= without fc-match off Windows")
        shim = self.work / "shim_fc"
        shim.mkdir(exist_ok=True)
        script = "#!/bin/sh\ncase \"$2\" in\n"
        for flag, name in (("-filters", "ffmpeg_filters_6.1.txt"), ("-encoders", "ffmpeg_encoders_6.1.txt"), ("-bsfs", "ffmpeg_bsfs_6.1.txt")):
            script += f"  {flag}) cat '{self.FIX / name}'; exit 0;;\n"
        script += "esac\ncase \"$1\" in -version) echo 'ffmpeg version 8.0-fixture'; exit 0;; esac\n"
        script += "case \"$*\" in *drawtext=fontfile=*) exit 0;; *drawtext=text=x*) kill -s SEGV $$;; esac\nexit 1\n"
        (shim / "ffmpeg").write_text(script)
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False).stdout)
        self.assertIn("filter:drawtext", d["available"])
        self.assertNotIn("filter:drawtext", d["missing"])
        self.assertFalse(any("drawtext" in e for e in d["errors"]), d["errors"])
        self.assertTrue(any("fontconfig" in n and "--font-file" in n for n in d.get("notes", [])), d.get("notes"))

    def test_python_sources_have_no_invalid_escapes(self):
        """#297: an invalid escape in a docstring (`\\%`) is a SyntaxWarning on Python 3.12+ and
        an import failure under -W error; every tracked .py must compile clean."""
        root = SCRIPTS.parent
        bad = []
        for path in sorted(list(root.glob("scripts/**/*.py")) + list(root.glob("mcp/*.py")) + list(root.glob("tests/*.py"))):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                try:
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
                except (SyntaxError, SyntaxWarning, DeprecationWarning) as exc:
                    bad.append(f"{path.relative_to(root)}: {exc}")
        self.assertEqual(bad, [])

    def test_drawtext_ordinary_failure_does_not_downgrade_a_listed_filter(self):
        """An ordinary nonzero exit from the drawtext probe -- not a crash -- proves nothing either
        way, so it must leave a listed-available drawtext alone rather than reporting it missing.
        This is also what every _doctor() fixture call above relies on: their shim's drawtext-probe
        invocation always falls through to the catch-all `exit 1`, not a real render."""
        d, code = self._doctor("ffmpeg_filters_6.1.txt")
        self.assertIn("filter:drawtext", d["available"])
        self.assertNotIn("filter:drawtext", d["missing"])
        self.assertTrue(d["ok"])
        self.assertEqual(code, 0)

    def test_unparsed_listing_is_unknown_not_missing(self):
        """Output no parser understands: filters become `unknown`, `ok` is false, exit 2, and nothing is claimed available."""
        d, code = self._doctor("ffmpeg_filters_garbage.txt")
        self.assertTrue(d["unknown"])
        self.assertTrue(all(c.startswith("filter:") for c in d["unknown"]))
        self.assertEqual([c for c in d["missing"] if c.startswith("filter:")], [])
        self.assertEqual([c for c in d["available"] if c.startswith("filter:")], [])
        self.assertEqual(d["detection"]["filters"]["status"], "unparsed")
        self.assertTrue(any("filters" in e for e in d["errors"]))
        self.assertFalse(d["ok"])
        self.assertEqual(code, 2)
        # encoders came from a readable listing and are still detected
        self.assertIn("encoder:libx264", d["available"])

    def test_failed_listing_is_unknown_not_missing(self):
        """`ffmpeg -filters` exiting non-zero is a structured detection error, not a missing filter."""
        d, code = self._doctor("ffmpeg_filters_8.0_constructed.txt", filters_exit=3)
        self.assertEqual(d["detection"]["filters"]["status"], "failed")
        self.assertIn("exited 3", d["detection"]["filters"]["detail"])
        self.assertTrue(d["unknown"])
        self.assertEqual([c for c in d["missing"] if c.startswith("filter:")], [])
        self.assertFalse(d["ok"])
        self.assertEqual(code, 2)

    def test_audio_loudness_join_stay_usable_without_aac(self):
        """audio.py/loudness.py/join.py all pick their audio codec from the output extension via
        audio_codec_for() (falling back to AAC only when the extension isn't otherwise covered),
        yet the contract declared AAC unconditionally `required` for all three -- so an ffmpeg
        build without an AAC encoder made `doctor` report these tools entirely unusable, even
        though they can still produce e.g. a .flac or .wav output with no AAC involved at all."""
        d, _ = self._doctor("ffmpeg_filters_8.1.2_macos.txt", encoders="ffmpeg_encoders_6.1_no_aac.txt")
        for name in ("audio", "loudness", "join"):
            self.assertEqual(d["tools"][name]["usable"], "yes", f"{name} must stay usable without AAC")
            self.assertNotIn("missing", d["tools"][name])
        # encoder:aac is still globally `missing` (other tools, e.g. multicam, still require it
        # unconditionally) -- the point of this test is that audio/loudness/join specifically
        # don't let that sink their own usability.
        self.assertIn("encoder:aac", d["missing"])

    def test_tool_usability_answers_can_i_run_this_today(self):
        """`doctor`'s tools map answers "usable on this machine now", not just "what capabilities exist" --
        a caller should not have to cross-reference each tool's own required-capability list by hand."""
        # plain Homebrew ffmpeg on macOS: no libass/freetype/harfbuzz/zimg, so no
        # subtitles/ass/drawtext/zscale filters -- caption.py cannot run, cut.py still can
        d, code = self._doctor("ffmpeg_filters_8.1.2_macos.txt", encoders="ffmpeg_encoders_8.1.2_macos.txt", bsfs="ffmpeg_bsfs_8.1.2_macos.txt")
        self.assertEqual(d["tools"]["caption"]["usable"], "no")
        self.assertIn("filter:subtitles", d["tools"]["caption"]["missing"])
        self.assertIn("subtitles", d["tools"]["caption"]["fix"])
        self.assertEqual(d["tools"]["cut"]["usable"], "yes")
        self.assertNotIn("missing", d["tools"]["cut"])
        # a listing that could not be read makes every tool needing it "unknown", never "yes" or a false "no"
        d2, code2 = self._doctor("ffmpeg_filters_garbage.txt")
        self.assertEqual(d2["tools"]["caption"]["usable"], "unknown")
        self.assertIn("filter:subtitles", d2["tools"]["caption"]["unknown"])
        self.assertNotIn("missing", d2["tools"]["caption"])
        # a tool needing only ffprobe/ffmpeg binaries (not a specific filter) is unaffected by the filter listing
        self.assertEqual(d2["tools"]["probe"]["usable"], "yes")

    def test_doctor_advisory_is_a_warning_never_a_failure(self):
        """End to end with a fake `ffmpeg -version`: the advisory is in the JSON and on stderr, and
        `ok`, the tools' `usable` and the exit code are what the same build reports without it."""
        results = {}
        for version in ("8.0.1-3ubuntu2", "8.1.2"):
            shim = self.work / f"shim_{version}"
            shim.mkdir()
            script = "#!/bin/sh\ncase \"$2\" in\n"
            for flag, name in (("-filters", "ffmpeg_filters_6.1.txt"), ("-encoders", "ffmpeg_encoders_6.1.txt"), ("-bsfs", "ffmpeg_bsfs_6.1.txt")):
                script += f"  {flag}) cat '{self.FIX / name}'; exit 0;;\n"
            script += f"esac\ncase \"$1\" in -version) echo 'ffmpeg version {version} Copyright (c) 2000-2026'; exit 0;; esac\nexit 1\n"
            (shim / "ffmpeg").write_text(script)
            (shim / "ffmpeg").chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
            proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
            plain = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", env=env, check=False)
            results[version] = (json.loads(proc.stdout), proc.returncode, proc.stderr, plain)
        old, old_code, old_err, old_plain = results["8.0.1-3ubuntu2"]
        new, new_code, new_err, new_plain = results["8.1.2"]
        self.assertEqual(old["ffmpeg"], "8.0.1-3ubuntu2")
        self.assertEqual(old["ffmpeg_security"]["ffmpeg"]["status"], "older_than_fix")
        self.assertEqual(new["ffmpeg_security"]["ffmpeg"]["status"], "not_older")
        line = next(w for w in old["ffmpeg_security"]["warnings"] if w.startswith("warning: ffmpeg 8.0.1-3ubuntu2"))
        self.assertIn(line, old_err)
        self.assertIn(line, old_plain.stderr)
        self.assertNotIn(line, old_plain.stdout)
        self.assertFalse(any(w.startswith("warning: ffmpeg ") for w in new["ffmpeg_security"]["warnings"]))
        self.assertNotIn("warning: ffmpeg 8.1.2", new_err)
        self.assertEqual((old["ok"], old_code, old_plain.returncode), (new["ok"], new_code, new_plain.returncode))
        self.assertEqual(old["tools"], new["tools"])

    def test_doctor_json_keeps_its_keys(self):
        """Consumers of 0.9.0 read available / missing / missing_optional / ok; those keys and types stay."""
        d, _ = self._doctor("ffmpeg_filters_8.0_constructed.txt")
        for key in ("python", "ffmpeg", "ffprobe", "available", "missing", "missing_optional", "ok"):
            self.assertIn(key, d)
        for key in ("available", "missing", "missing_optional", "unknown", "errors"):
            self.assertIsInstance(d[key], list)
        self.assertIsInstance(d["ok"], bool)
        contract = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "--json").stdout)
        for key in ("available", "missing", "missing_optional", "unknown", "detection", "detected_by"):
            self.assertIn(key, contract["capabilities"])

    def _doctor_listing(self, drop=(), platform_reason=None):
        """doctor() in this process over the real macOS encoder capture minus the `drop` names (the
        other listings are this machine's own), with the platform check stood in for."""
        from unittest import mock
        import _common.runner as runner
        names = [n for n in _contract._parse_ff_list("-encoders", (self.FIX / "ffmpeg_encoders_8.1.2_macos.txt").read_text()) if n not in drop]
        real = _contract._ff_listing

        def listing(binary, flag):
            if flag == "-encoders":
                return {"names": names, "status": "parsed", "detail": f"{len(names)} entries"}
            return real(binary, flag)
        with mock.patch.object(_contract, "_ff_listing", side_effect=listing), \
                mock.patch.object(runner, "hw_platform_reason", return_value=platform_reason):
            return _contract.doctor()

    def test_a_build_without_libx264_is_usable_where_videotoolbox_takes_its_place(self):
        """#314: libx264/libx265 absent but h264/hevc_videotoolbox present on Apple Silicon: the tools
        encode with VideoToolbox without --hw, so doctor does not call them unusable."""
        full = self._doctor_listing()
        self.assertEqual(full["covered_by"], {})
        self.assertIn("encoder:libx264", full["available"])
        self.assertFalse(any("encoder:libx264" in n for n in full.get("notes") or []))
        lean = self._doctor_listing(drop=("libx264", "libx265"))
        self.assertEqual(lean["covered_by"], {"encoder:libx264": "encoder:h264_videotoolbox", "encoder:libx265": "encoder:hevc_videotoolbox"})
        for cap in lean["covered_by"]:
            self.assertNotIn(cap, lean["available"], "it is not in the build")
            self.assertNotIn(cap, lean["missing"] + lean["missing_optional"], "and it blocks nothing")
        self.assertEqual(lean["ok"], full["ok"])
        self.assertEqual(lean["missing"], full["missing"])
        for tool in ("insert", "fit"):
            self.assertEqual(lean["tools"][tool]["usable"], "yes", tool)
            self.assertNotIn("missing", lean["tools"][tool])
        self.assertEqual(lean["tools"]["insert"]["covered_by"], {"encoder:libx264": "encoder:h264_videotoolbox"})
        self.assertNotIn("covered_by", lean["tools"]["probe"])
        self.assertTrue(any("encoder:libx264" in n and "h264_videotoolbox" in n for n in lean["notes"]), lean.get("notes"))
        # only the encoder the build lacks is covered
        self.assertEqual(self._doctor_listing(drop=("libx265",))["covered_by"], {"encoder:libx265": "encoder:hevc_videotoolbox"})

    def test_libx264_stays_required_without_videotoolbox_or_off_apple_silicon(self):
        for label, drop, reason in (("no VideoToolbox in the build", ("libx264", "libx265", "h264_videotoolbox", "hevc_videotoolbox"), None),
                                    ("not Apple Silicon", ("libx264", "libx265"), "VideoToolbox constant-quality encoding needs Apple Silicon"),
                                    ("not macOS", ("libx264", "libx265"), "VideoToolbox is macOS-only")):
            with self.subTest(label):
                d = self._doctor_listing(drop=drop, platform_reason=reason)
                self.assertEqual(d["covered_by"], {})
                self.assertIn("encoder:libx264", d["missing"])
                self.assertEqual(d["tools"]["insert"]["usable"], "no")
                self.assertIn("encoder:libx264", d["tools"]["insert"]["missing"])
                self.assertIn("libx264", d["tools"]["insert"]["fix"])
                self.assertFalse(d["ok"])

    def test_gpu_encoders_are_reported_from_the_build_alone(self):
        """gpu_encoders answers only "did this ffmpeg build ship the capability" -- never affects ok/usable."""
        # the real macOS capture carries VideoToolbox (h264/hevc), the Windows capture carries nvenc/qsv/amf/vaapi
        d_mac, _ = self._doctor("ffmpeg_filters_8.1.2_macos.txt", encoders="ffmpeg_encoders_8.1.2_macos.txt", bsfs="ffmpeg_bsfs_8.1.2_macos.txt")
        self.assertEqual(d_mac["gpu_encoders"]["status"], "parsed")
        self.assertIn("h264_videotoolbox", d_mac["gpu_encoders"]["present"])
        self.assertIn("hevc_videotoolbox", d_mac["gpu_encoders"]["present"])
        self.assertNotIn("h264_nvenc", d_mac["gpu_encoders"]["present"], "macOS build has no nvenc")
        d_win, _ = self._doctor("ffmpeg_filters_9.0.1_windows.txt", encoders="ffmpeg_encoders_9.0.1_windows.txt", bsfs="ffmpeg_bsfs_9.0.1_windows.txt")
        self.assertEqual(d_win["gpu_encoders"]["status"], "parsed")
        self.assertGreater(len(d_win["gpu_encoders"]["present"]), 0)
        for name in d_win["gpu_encoders"]["present"]:
            self.assertTrue(name.endswith(("_nvenc", "_videotoolbox", "_qsv", "_vaapi", "_amf")), name)
        # no tool declares or requires a GPU encoder, so its presence/absence never affects ok or any tool's usability
        # (the Windows gyan.dev capture is a full build with nothing missing, unlike the macOS one above)
        self.assertTrue(d_win["ok"])
        self.assertEqual(d_win["tools"]["export"]["usable"], "yes")
        declared = set(_contract.required_capabilities()["required"] + _contract.required_capabilities()["optional"])
        self.assertFalse(any(c.startswith("encoder:") and c[8:] in d_win["gpu_encoders"]["present"] for c in declared),
                          "no tool declares a GPU encoder as required/optional -- gpu_encoders is purely informational")
        # an unreadable encoder listing (fed the filters-garbage fixture as "encoders" to force
        # unparsed output) is reported honestly by status, never silently claimed as an empty pass
        d_fail, _ = self._doctor("ffmpeg_filters_6.1.txt", encoders="ffmpeg_filters_garbage.txt")
        self.assertNotEqual(d_fail["gpu_encoders"]["status"], "parsed")
        self.assertEqual(d_fail["gpu_encoders"]["present"], [])

    # ------------------------------------------------------------------- font availability (issue #66)
    def _fc_match_shim(self, script_body):
        """PATH with a fake fc-match on it, real ffmpeg/ffprobe/everything else untouched."""
        shim = self.work / "fcshim"
        shim.mkdir(exist_ok=True)
        (shim / "fc-match").write_text("#!/bin/sh\n" + script_body)
        (shim / "fc-match").chmod(0o755)
        return dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")

    def test_default_drawtext_font_matches_this_sandboxs_real_fc_match(self):
        """Exercises the genuine, unmocked fc-match path end to end -- but this repo's own CI only
        installs fonts-dejavu-core on the Linux leg (see issue #66 this detector was built for), so
        DejaVu Sans is only actually present on Linux; macOS/Windows CI resolve it to a substituted
        family. Rather than hardcode "available" (which is only true on one of three CI platforms
        and would make this very test repeat the issue's own bug), ask fc-match directly for the
        ground truth and assert doctor's classification matches reality on whichever platform this
        runs on."""
        if shutil.which("fc-match") is None:
            self.skipTest("no fontconfig on this machine")
        d, code = self._doctor("ffmpeg_filters_6.1.txt")
        self.assertEqual(d["fonts"]["default_font"], "DejaVu Sans")
        resolved = subprocess.run(["fc-match", "--format=%{family}\n", "DejaVu Sans"],
                                   stdout=subprocess.PIPE, text=True).stdout.splitlines()[0].strip()
        expected = "available" if resolved == "DejaVu Sans" else "missing"
        self.assertEqual(d["fonts"]["status"], expected, d["fonts"])
        self.assertIn(resolved, d["fonts"]["detail"])
        # informational only: a missing/available font never affects ok or any tool's usable
        self.assertTrue(d["ok"])

    def test_missing_font_is_reported_missing_not_unknown(self):
        """A real fc-match that substitutes a different family for the request: reported `missing`,
        the same "silent substitution is the risk" case drawtext's own exit code can never catch."""
        env = self._fc_match_shim("echo 'Liberation Sans'\nexit 0\n")
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
        d = json.loads(proc.stdout)
        self.assertEqual(d["fonts"]["status"], "missing")
        self.assertIn("Liberation Sans", d["fonts"]["detail"])
        self.assertIn("DejaVu Sans", d["fonts"]["detail"])
        self.assertTrue(d["ok"], "a missing default font never fails doctor's ok -- caption/graphics still run, just with a substituted typeface")

    def test_font_detection_failure_is_unknown_not_missing(self):
        """fc-match exiting non-zero, or absent entirely, is `unknown` -- never folded into `missing`
        (same three-state invariant as every other capability doctor detects)."""
        env = self._fc_match_shim("exit 1\n")
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
        d = json.loads(proc.stdout)
        self.assertEqual(d["fonts"]["status"], "unknown")

        # fc-match not on PATH at all
        stripped = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if not (Path(p) / "fc-match").exists())
        env2 = dict(os.environ, PATH=stripped)
        proc2 = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env2, check=False)
        d2 = json.loads(proc2.stdout)
        self.assertEqual(d2["fonts"]["status"], "unknown")
        self.assertIn("fc-match", d2["fonts"]["detail"])

    def test_doctor_reports_a_font_status_for_every_script_it_can_detect(self):
        """1.12: `fonts.scripts` answers "which languages can this machine actually render", the
        question `filter:subtitles` never asked. Same three states as every other capability."""
        from _common import SCRIPTS as DETECTED_SCRIPTS
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", check=False)
        d = json.loads(proc.stdout)
        expected = {s for s in DETECTED_SCRIPTS if s != "latin"}
        self.assertEqual(set(d["fonts"]["scripts"]), expected)
        self.assertEqual(len(expected), 12, "ja zh ko ar he hi bn ta th lo ru el (bn/ta/lo added in 1.15)")
        for name, entry in d["fonts"]["scripts"].items():
            with self.subTest(script=name):
                self.assertIn(entry["status"], ("available", "missing", "unknown"))
                self.assertEqual(set(entry), {"status", "file"})
                if entry["status"] == "available":
                    self.assertTrue(os.path.exists(entry["file"]), entry)
                else:
                    self.assertIsNone(entry["file"])
        self.assertTrue(d["ok"], "a script with no font is a machine fact, never a broken install")

    def test_doctor_plain_text_keeps_fonts_to_one_short_line(self):
        """The plain-text doctor was cut to ~520 bytes in 1.11.0; nine scripts must not undo that,
        so they are summarised on the single `fonts:` line and detailed only in --json."""
        out = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", check=False).stdout
        font_lines = [l for l in out.splitlines() if l.startswith("fonts:")]
        self.assertEqual(len(font_lines), 1, out)
        self.assertLess(len(out.encode("utf-8")), 900, "the short doctor text must stay short")
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", check=False).stdout)
        for name, entry in d["fonts"]["scripts"].items():
            if entry["status"] == "available":
                self.assertIn(name, font_lines[0])
            if entry["status"] == "missing":
                self.assertIn(name, font_lines[0])
            self.assertNotIn(str(entry["file"]), font_lines[0], "file paths belong in --json, not the summary")
        # 1.15: the emoji row adds at most one clause to the same line, and no second line
        self.assertIn("emoji", font_lines[0])
        self.assertLessEqual(len(font_lines[0]), 200, font_lines[0])
        self.assertNotIn("\n", font_lines[0])

    def test_doctor_reports_an_emoji_row_under_fonts(self):
        """1.15: `fonts.emoji` answers "can this machine draw an emoji, and in colour" -- a
        question no filter or font capability asks."""
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", check=False).stdout)
        emoji = d["fonts"]["emoji"]
        self.assertEqual(set(emoji), {"mode", "color_font", "color_font_file", "libass_color",
                                      "assets", "detail", "fix"})
        self.assertIn(emoji["mode"], ("color", "png", "mono", "none"))
        self.assertIn(emoji["libass_color"], (True, False, None))
        self.assertTrue(emoji["detail"])
        self.assertIn("--emoji-assets", emoji["fix"])
        if emoji["color_font_file"]:
            self.assertTrue(os.path.exists(emoji["color_font_file"]), emoji)
        # an installed colour emoji family is never on its own a claim of colour
        if emoji["color_font"] and emoji["libass_color"] is not True:
            self.assertNotEqual(emoji["mode"], "color")

    def test_emoji_capability_is_informational_like_gpu_encoders(self):
        """A machine that cannot draw colour emoji is not a broken install: `fonts.emoji` must
        never move `ok` or any tool's `usable`."""
        d = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", check=False).stdout)
        self.assertTrue(d["ok"] or d["missing"] or d["unknown"],
                        "ok went false with nothing missing -- the emoji row must be informational")
        for name, tool in d["tools"].items():
            with self.subTest(tool=name):
                for cap in tool.get("missing", []) + tool.get("unknown", []):
                    self.assertNotIn("emoji", cap)
        self.assertNotIn("emoji", " ".join(d["available"] + d["missing"] + d["missing_optional"] + d["unknown"]))

    def test_static_skips_the_environment_detection_including_the_emoji_probe(self):
        """`--static` is the only user-reachable way to ask for the contract without detection:
        doctor() itself always probes (there is no `doctor --static`, and the dead `detect=`
        parameter that pretended otherwise was removed in 1.15.0). What must hold is that
        `--json --static` runs no detection at all -- including the ~80 ms emoji render probe."""
        unprobed = _contract._fonts_capability(probe=False)
        self.assertIsNone(unprobed["emoji"]["libass_color"])
        self.assertNotEqual(unprobed["emoji"]["mode"], "color",
                            "an unprobed machine must never be reported as colour-capable")
        out = sh(sys.executable, SCRIPTS / "_contract.py", "--json", "--static", check=False).stdout
        doc = json.loads(out)
        self.assertNotIn("available", doc["capabilities"], "--static ran detection")
        self.assertNotIn("fonts", doc.get("capabilities", {}))

    def test_emoji_support_answers_png_or_none_without_fontconfig(self):
        """A static ffmpeg build usually has no fontconfig at all. That is not evidence that this
        machine cannot draw emoji -- the PNG overlay path needs no fontconfig -- so the answer must
        never be a claim of `color`, and its detail must name the missing fontconfig."""
        import _common
        _common._EMOJI_SUPPORT_CACHE.clear()
        real_which = shutil.which
        try:
            _common.shutil.which = lambda name: None if name in ("fc-list", "fc-scan", "fc-match", "ffmpeg") else real_which(name)
            support = _common.emoji_support(probe=True)
        finally:
            _common.shutil.which = real_which
            _common._EMOJI_SUPPORT_CACHE.clear()
        self.assertIn(support["mode"], ("png", "none"))
        self.assertIsNone(support["color_font"])
        self.assertIn("fontconfig", support["detail"])

    def test_skill_md_stays_under_the_30kb_budget(self):
        """SKILL.md is loaded into every session: the 30 000-byte budget was a convention in
        CONTRIBUTING.md, which is how it got to 51 free bytes. Now it is a test."""
        size = (ROOT / "SKILL.md").stat().st_size
        self.assertLess(size, 30_000,
                        f"SKILL.md is {size} bytes, {size - 30_000} over the 30,000-byte budget -- "
                        "trim a line rather than raising the limit (see CONTRIBUTING.md)")

    # ------------------------------------------------- #234: child output is decoded as UTF-8
    def test_every_child_text_capture_names_utf8(self):
        """#234: `text=True` decodes with the machine's locale code page. On a Windows cp932 box
        ffprobe's UTF-8 JSON then raises UnicodeDecodeError inside the reader thread,
        communicate() hands back an empty stdout, and probe.py reported `?s | no video | no
        audio` with exit 0. Every child capture in this repo states its encoding."""
        import ast

        def offending_calls(source, rel):
            """Every subprocess.run/Popen call that asks for text mode without naming UTF-8.
            The scan is over the parsed call, not over one line: review 17 finding 3 -- the
            line-matching version could not see `text=text` in runner.run_analysis(), which is
            exactly the capture that shipped undecorated."""
            found = []
            tree = ast.parse(source)
            funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name not in ("run", "Popen", "check_output", "call"):
                    continue
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                if "text" not in kw and "universal_newlines" not in kw:
                    continue
                flag = kw.get("text", kw.get("universal_newlines"))
                if isinstance(flag, ast.Constant) and flag.value is False:
                    continue                                  # bytes: encoding would be rejected
                if "encoding" in kw:
                    continue
                if any(k.arg is None for k in node.keywords):
                    # a **mapping of encoding kwargs, built in the enclosing function
                    owner = [f for f in funcs if f.lineno <= node.lineno <= (f.end_lineno or node.lineno)]
                    seg = "\n".join(ast.get_source_segment(source, f) or "" for f in owner)
                    if '"encoding": "utf-8"' in seg or "'encoding': 'utf-8'" in seg:
                        continue
                found.append(f"{rel}:{node.lineno}")
            return found

        offenders = []
        for root in ("scripts", "evals"):
            for path in sorted((ROOT / root).rglob("*.py")):
                offenders += offending_calls(path.read_text(encoding="utf-8"), path.relative_to(ROOT))
        self.assertEqual(offenders, [], "decode child output as UTF-8 (errors='replace'), never as the locale code page")
        # the scan must see the shapes the old line match missed
        self.assertEqual(offending_calls("subprocess.run(cmd, text=text)", "x.py"), ["x.py:1"])
        self.assertEqual(offending_calls("subprocess.run(cmd, universal_newlines=True)", "x.py"), ["x.py:1"])
        self.assertEqual(offending_calls("subprocess.run(cmd, text=False)", "x.py"), [])

    def _utf8_ffprobe_shim(self, body):
        shim = OUT / "utf8_shim"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "ffprobe").write_text("#!/bin/sh\n" + body, encoding="utf-8")
        (shim / "ffprobe").chmod(0o755)
        # LANG/LC_ALL=C with the UTF-8 modes off is this machine's stand-in for a cp932 Windows
        # console: Python's preferred encoding becomes ASCII, so a locale-decoded capture of the
        # UTF-8 JSON below fails exactly as it does there.
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", LANG="C", LC_ALL="C",
                   PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        env.pop("PYTHONIOENCODING", None)
        return env

    @unittest.skipIf(platform.system() == "Windows", "the fake ffprobe is a #!/bin/sh script")
    def test_probe_reads_non_ascii_ffprobe_json_under_a_non_utf8_locale(self):
        doc = ('{"format": {"filename": "\u65e5\u672c\u8a9e.mp4", "format_name": "mov,mp4", '
               '"duration": "12.0", "size": "1000", "tags": {"title": "\u65e5\u672c\u8a9e"}}, '
               '"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, '
               '"height": 720, "r_frame_rate": "30/1", "pix_fmt": "yuv420p"}]}')
        env = self._utf8_ffprobe_shim("cat <<'JSON'\n" + doc + "\nJSON\n")
        target = OUT / "utf8_probe.mp4"
        target.write_bytes(b"not really a movie")   # ffprobe is the shim; only the path must exist
        proc = sh(sys.executable, SCRIPTS / "probe.py", target, "--json", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        d = json.loads(proc.stdout)
        self.assertEqual(d["duration"], 12.0)
        self.assertEqual(d["video"]["width"], 1280)
        # the non-ASCII text ffprobe printed survives the capture -- the #234 surface (the path
        # on argv is the filesystem encoding, a different axis, so it is not what is asserted)
        self.assertEqual(d["tags"]["title"], "\u65e5\u672c\u8a9e")

    @unittest.skipIf(platform.system() == "Windows", "the fake ffprobe is a #!/bin/sh script")
    def test_probe_refuses_when_ffprobe_prints_nothing(self):
        """The half of #234 that made it a silent defect: an empty stdout with exit 0 must never
        become a success document of nulls."""
        env = self._utf8_ffprobe_shim("exit 0\n")
        target = OUT / "empty_probe.mp4"
        target.write_bytes(b"not really a movie")
        # this module's own sh() (line 41), not tests/_fixtures.sh: check=False means "do not
        # raise on a non-zero exit", which is the point of the refusal being asserted below.
        proc = sh(sys.executable, SCRIPTS / "probe.py", target, "--json", env=env, check=False)
        self.assertNotEqual(proc.returncode, 0)
        err = json.loads(proc.stdout)
        self.assertEqual(err["status"], "failed")
        self.assertEqual(err["error"]["kind"], "input")
        self.assertIn("no output", err["error"]["message"])

    @unittest.skipIf(platform.system() == "Windows", "the fake ffmpeg is a #!/bin/sh script")
    def test_run_analysis_survives_non_utf8_locale_on_the_loudness_path(self):
        """Review 17 finding 2: run_analysis() is the capture every ffmpeg MEASUREMENT goes
        through -- loudness.py parses the loudnorm JSON out of its stderr. With the locale's
        codec it raised UnicodeDecodeError inside subprocess.run: an unhandled traceback, not a
        `status: failed` document."""
        shim = OUT / "utf8_ffmpeg_shim"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "ffmpeg").write_text(
            "#!/bin/sh\n"
            "printf 'Input #0, mov,mp4, from \\346\\227\\245\\346\\234\\254\\350\\252\\236.mp4:\\n' >&2\n"
            "cat >&2 <<'JSON'\n"
            '{ "input_i" : "-18.5", "input_tp" : "-2.0", "input_lra" : "7.0", '
            '"input_thresh" : "-28.7", "target_offset" : "0.5" }\n'
            "JSON\n", encoding="utf-8")
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", LANG="C", LC_ALL="C",
                   PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        env.pop("PYTHONIOENCODING", None)
        code = ("import json, sys; sys.path.insert(0, %r); import loudness; "
                "print(json.dumps(loudness.measure('x.wav', -14.0, -1.0, 11.0)))" % str(SCRIPTS))
        proc = sh(sys.executable, "-c", code, env=env)
        self.assertEqual(json.loads(proc.stdout)["input_i"], "-18.5")

    def test_skill_md_routes_the_1_17_features(self):
        """Eval 18: SKILL.md never mentioned filler, --snap beats, --jobs or --cache, so three
        runs rebuilt those features by hand and one asserted the skill has no beat detection.
        A feature nobody can find from the routing table does not exist."""
        table = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("## Request \u2192 script", 1)[1]
        for feature, needles in (("filler words", ("silence.py", "--filler", "--words")),
                                 ("beat-synced cuts", ("scenes.py", "--beats", "--snap beats")),
                                 ("parallel batch", ("batch.py", "--jobs auto")),
                                 ("the stage cache", ("render.py", "--cache"))):
            for needle in needles:
                self.assertIn(needle, table, f"{feature}: the routing table never names {needle}")

    def test_skill_md_sanctions_one_label_for_a_partial_result(self):
        """1.17.1: a partial result is `Done:` with the shortfall in `Notes:`. Agents were
        inventing `Done (partially):` because the rule only said what not to write."""
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("A partial result is `Done:` with the shortfall in `Notes:`", text)
        self.assertIn("Done (partially):", text, "the forbidden label is still named, as the counter-example")

    def test_eval_fixtures_stage_a_batch_recipe_with_an_absolute_output_dir(self):
        """eval 18 bp1/bp2: the staged batch.json said "output_dir": "out", which resolves
        against the caller's cwd, so the run wrote outside the prompt's folder and the agent had
        to rewrite the recipe before it could answer the prompt."""
        sys.path.insert(0, str(ROOT / "evals"))
        import importlib
        write_fixtures = importlib.import_module("write_fixtures")
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "bp1"
            written = write_fixtures.write(outdir, {"fixtures": {
                "batch.json": json.dumps({"glob": "*.mp4", "output_dir": "out", "steps": []}),
                "cues.txt": "0:00-0:03 hello\n"}})
            recipe = json.loads((outdir / "batch.json").read_text(encoding="utf-8"))
            self.assertTrue(Path(recipe["output_dir"]).is_absolute())
            # the fixture resolves the path (macOS tempdirs live under a /var -> /private/var symlink)
            self.assertEqual(Path(recipe["output_dir"]), (outdir / "out").resolve())
            self.assertEqual((outdir / "cues.txt").read_text(encoding="utf-8"), "0:00-0:03 hello\n",
                             "a non-JSON fixture is written exactly as the prompt states it")
            self.assertEqual(len(written), 2)
        # an absolute output_dir in the prompt is left alone -- on every OS. Path("/srv/out")
        # .is_absolute() is False on Windows, which used to rewrite a posix-absolute dir under
        # OUTDIR there (review 17 finding 9), so both spellings are asserted here.
        for stated in ("/srv/out", "C:\\srv\\out"):
            with tempfile.TemporaryDirectory() as tmp:
                outdir = Path(tmp) / "bp2"
                write_fixtures.write(outdir, {"fixtures": {"batch.json": json.dumps(
                    {"glob": "*.mp4", "output_dir": stated})}})
                self.assertEqual(
                    json.loads((outdir / "batch.json").read_text(encoding="utf-8"))["output_dir"],
                    stated)

    def test_font_fix_hint_names_the_language_and_how_to_install_one(self):
        hint = _contract._capability_fix_hint("font:ko")
        self.assertIn("Korean", hint)
        self.assertIn("fonts-noto-cjk", hint)
        self.assertIn("--font-file", hint)
        self.assertIn("Thai", _contract._capability_fix_hint("font:th"))

    def test_font_capability_is_informational_like_gpu_encoders(self):
        """fonts, like gpu_encoders, is reported but never gates ok/usable -- it answers a question
        none of the required/optional capabilities ask."""
        declared = set(_contract.required_capabilities()["required"] + _contract.required_capabilities()["optional"])
        self.assertFalse(any(c.startswith("font:") for c in declared), "font availability is informational, not a required/optional capability")
        env = self._fc_match_shim("echo 'Liberation Sans'\nexit 0\n")
        proc = sh(sys.executable, SCRIPTS / "_contract.py", "doctor", "--json", env=env, check=False)
        d = json.loads(proc.stdout)
        self.assertTrue(d["ok"])
        for tool_name in ("caption", "graphics"):
            self.assertEqual(d["tools"][tool_name]["usable"], "yes")


class EvalRunnerTests(unittest.TestCase):
    """evals/run.py's regex-only grading -- the cross-vendor path (Cursor, Codex, or any
    harness that produces a transcript file). No LLM judge, no `claude` CLI dependency: every
    assertion here is against the pure-Python score()/load_tasks() functions."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "evals"))
        import importlib
        cls.evals_run = importlib.import_module("run")

    def test_score_passes_when_every_expect_slot_is_present(self):
        run = self.evals_run
        task = {"id": 1, "request": "r", "expect": ["probe.py", "cut.py"],
                "grader_expect": None, "grader_not": None}
        ok, reasons = run.score("ran probe.py then cut.py", task)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_score_reports_missing_expect_slots(self):
        run = self.evals_run
        task = {"id": 2, "request": "r", "expect": ["probe.py", "cut.py"],
                "grader_expect": None, "grader_not": None}
        ok, reasons = run.score("ran probe.py only", task)
        self.assertFalse(ok)
        self.assertIn("cut.py", reasons[0])

    def test_score_alternation_slot_accepts_either_side(self):
        run = self.evals_run
        task = {"id": 3, "request": "r", "expect": ["fit|render"], "grader_expect": None, "grader_not": None}
        self.assertTrue(run.score("used render.py --template", task)[0])
        self.assertTrue(run.score("used fit.py --duration 2x", task)[0])
        self.assertFalse(run.score("used caption.py", task)[0])

    def test_score_alternation_slot_accepts_dot_py_or_bare_name(self):
        run = self.evals_run
        # tasks.json's expect entries carry ".py"; agent_prompts_24.json's don't. Either spelling
        # of the slot must match a transcript that names the script with ".py".
        task = {"id": 4, "request": "r", "expect": ["render"], "grader_expect": None, "grader_not": None}
        self.assertTrue(run.score("called render.py --template reel", task)[0])

    def test_score_grader_expect_regex_must_match(self):
        run = self.evals_run
        task = {"id": 5, "request": "r", "expect": [], "grader_expect": r"(?i)\d+\s*bpm", "grader_not": None}
        ok, reasons = run.score("tempo is 128 bpm", task)
        self.assertTrue(ok)
        ok, reasons = run.score("tempo unknown", task)
        self.assertFalse(ok)
        self.assertIn("grader_expect", reasons[0])

    def test_score_grader_not_regex_must_not_match(self):
        run = self.evals_run
        task = {"id": 6, "request": "r", "expect": [], "grader_expect": None,
                "grader_not": r"(?i)rewrote the caption"}
        ok, reasons = run.score("Done: burned the captions as written", task)
        self.assertTrue(ok)
        ok, reasons = run.score("Done: rewrote the caption to fit", task)
        self.assertFalse(ok)
        self.assertIn("grader_not", reasons[0])

    def test_load_tasks_normalises_tasks_json_shape(self):
        run = self.evals_run
        tasks = run.load_tasks(ROOT / "evals" / "tasks.json")
        self.assertTrue(tasks)
        t = tasks[0]
        self.assertIn("id", t)
        self.assertIn("request", t)
        self.assertIsInstance(t["expect"], list)
        self.assertIsNone(t["grader_expect"])

    def test_load_tasks_normalises_agent_prompts_shape(self):
        run = self.evals_run
        tasks = run.load_tasks(ROOT / "evals" / "agent_prompts_24.json")
        self.assertTrue(tasks)
        by_id = {t["id"]: t for t in tasks}
        self.assertIn("e01-reel", by_id)
        self.assertEqual(by_id["e01-reel"]["expect"][0], "fit|render")
        # at least one prompt in this set carries a grader_expect/grader_not regex
        self.assertTrue(any(t["grader_expect"] for t in tasks))
        self.assertTrue(any(t["grader_not"] for t in tasks))

    def test_cli_grades_a_flat_directory_of_transcripts(self):
        run = self.evals_run
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            (outdir / "1.txt").write_text("ran probe.py then fit.py then export.py", encoding="utf-8")
            proc = sh(sys.executable, HERE_EVALS_RUN, str(outdir), "--json")
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["passed"], 1)
            self.assertEqual(doc["total"], 1)
            self.assertEqual(proc.returncode, 0)

    def test_cli_exit_code_is_nonzero_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            (outdir / "2.txt").write_text("ran probe.py only", encoding="utf-8")
            proc = sh(sys.executable, HERE_EVALS_RUN, str(outdir), "--json", check=False)
            self.assertNotEqual(proc.returncode, 0)

    def test_cli_accepts_a_prompts_flag_pointing_at_the_108_prompt_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            (outdir / "e02-cut-lossless.txt").write_text("ran probe.py then cut.py --start 0:02 --end 0:08", encoding="utf-8")
            proc = sh(sys.executable, HERE_EVALS_RUN, str(outdir), "--json",
                      "--prompts", str(ROOT / "evals" / "agent_prompts_24.json"))
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["total"], 1)
            self.assertEqual(doc["passed"], 1)

    def test_run_py_has_no_claude_cli_or_llm_judge_dependency(self):
        """The cross-vendor contract: grading is regex/substring only, so a Cursor or Codex
        session can run this without a `claude` binary or an LLM call in the loop."""
        src = (ROOT / "evals" / "run.py").read_text(encoding="utf-8")
        for needle in ("subprocess", "anthropic", "openai", '"claude"', "'claude'", "ANTHROPIC_API_KEY"):
            self.assertNotIn(needle, src, f"evals/run.py should not depend on {needle!r}")


HERE_EVALS_RUN = str(ROOT / "evals" / "run.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
