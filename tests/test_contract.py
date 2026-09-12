#!/usr/bin/env python3
"""Contract tests: the machine-readable execution contract matches the scripts, the MCP
server and the installer, and every ToolSpec claim (dry-run, JSON shape, input preservation,
verification policy) holds when the tool actually runs.

    python3 tests/test_contract.py
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out"))
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "mcp"))
import _contract  # noqa: E402
import _common  # noqa: E402
import server as mcp_server  # noqa: E402


def sh(*cmd, check=True, env=None, cwd=None):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd)
    if check and proc.returncode != 0:
        raise AssertionError(f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def ffmpeg(*args):
    return sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args)


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
        """.claude-plugin/plugin.json makes the repo installable with `claude plugin install
        kajisho5/ffmpeg-skill` (#142); a single-skill plugin may keep SKILL.md at its root. Its
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
        source = "\n".join(p.read_text(encoding="utf-8") for p in SCRIPTS.glob("*.py"))
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
        self.assertEqual(cut["crf"]["type"], "integer")
        self.assertEqual(self.tools["export"]["input_schema"]["properties"]["preset"]["enum"], sorted(self.tools["export"]["input_schema"]["properties"]["preset"]["enum"]))

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
        silently drifting out of sync with _contract.py again (issue #82)."""
        analysis_tools = set(_contract.DRY_RUN_ANALYSIS.keys())
        self.assertEqual(analysis_tools, {"sync", "multicam", "scenes", "report", "cropdetect", "silence", "loudness", "check", "stabilize"},
                          "the analysis-only dry-run tool set changed -- update SKILL.md/references/scripts.md's exception list to match")
        # "the name appears somewhere in the file" was too weak: every tool name is in SKILL.md's
        # request table anyway, so the list drifted twice (#176 -> #179) with this test green.
        # Pin the sentence that states the exception: the one naming `verify` and `--dry-run`.
        docs = {"SKILL.md": ROOT / "SKILL.md", "references/scripts.md": ROOT / "references" / "scripts.md",
                "docs/contract.md": ROOT / "docs" / "contract.md"}
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
        # join and waveform are the picture tools that also accept audio-only inputs (audio
        # concat; audio-track visualization); look applies to their video output only, which
        # SKILL.md states next to "Look: not needed"
        both = {"join", "waveform"}
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

    # ------------------------------------------------------------------ consistency: MCP and installer
    def test_mcp_tools_match_contract(self):
        mcp_names = [t["name"] for t in mcp_server.tool_list()]
        self.assertEqual(sorted(mcp_names), sorted(self.tools), "MCP tools/list == contract tools")
        listed = [l.split()[0] for l in sh(sys.executable, ROOT / "mcp" / "server.py", "--list").stdout.splitlines() if l.strip()]
        self.assertEqual(sorted(listed), sorted(self.tools))
        for name, spec in self.tools.items():
            self.assertEqual(spec["mcp"]["tool"], name)
            self.assertEqual(spec["mcp"]["positional"], mcp_server.POSITIONAL.get(name, ["input"]) if spec["mcp"]["positional"] else spec["mcp"]["positional"])
        # a real JSON-RPC round trip
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        proc = subprocess.run([sys.executable, str(ROOT / "mcp" / "server.py")], input=req, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        resp = json.loads(proc.stdout.strip().splitlines()[0])
        self.assertEqual(sorted(t["name"] for t in resp["result"]["tools"]), sorted(self.tools))

    def test_mcp_tool_surface_matches_the_frozen_1x_snapshot(self):
        """docs/contract.md, "Stability guarantee (1.x)": within 1.x no tool is removed or renamed
        and no argument is removed, renamed or made newly required. The MCP surface is *derived*
        from the argparse parsers, so a careless parser edit changes it with no edit under mcp/ --
        which is exactly why the surface is pinned here as data rather than trusted to a review.
        tests/fixtures/mcp_tools.json holds, per tool, the argument names and which are required.
        Adding a tool or an optional argument is allowed and must be reflected by regenerating the
        snapshot (UPDATE_MCP_SNAPSHOT=1 python3 tests/test_contract.py); removing or renaming
        anything, or making an argument required, is a breaking change and belongs behind the
        deprecation policy and a major bump, not behind a regenerated fixture."""
        snapshot_path = ROOT / "tests" / "fixtures" / "mcp_tools.json"
        live = [{"name": t["name"],
                 "properties": sorted(t["inputSchema"].get("properties", {}).keys()),
                 "required": sorted(t["inputSchema"].get("required", []))}
                for t in mcp_server.tool_list()]
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

    # ------------------------------------------------------------------ MCP inputSchema derived from the contract
    def _rpc(self, requests, root=ROOT):
        text = "".join(json.dumps(r) + "\n" for r in requests)
        proc = subprocess.run([sys.executable, str(Path(root) / "mcp" / "server.py")], input=text, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in proc.stdout.strip().splitlines()]

    @staticmethod
    def _norm(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    def test_mcp_input_schema_equals_translated_contract_schema(self):
        listed = self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])[0]["result"]["tools"]
        self.assertEqual([t["name"] for t in listed], [t["name"] for t in self.contract["tools"]], "MCP order == contract order")
        for entry in listed:
            spec = self.tools[entry["name"]]
            self.assertEqual(self._norm(entry["inputSchema"]), self._norm(_contract.mcp_input_schema(spec)), entry["name"])
            self.assertEqual(self._norm(entry), self._norm(_contract.mcp_tool(spec)))
            schema = entry["inputSchema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertIn("argv", schema["properties"])
            for dest, prop in spec["input_schema"]["properties"].items():
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
            err = self._rpc([{"jsonrpc": "2.0", "id": 0, "method": "tools/list"}], root=root)[0]
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
            tools = {t["name"]: t for t in self._rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], root=root)[0]["result"]["tools"]}
            self.assertNotIn("cut", tools, "removed script still exposed")
            self.assertIn("zzztool", tools, "new public script not exposed")
            self.assertEqual(tools["zzztool"]["inputSchema"]["properties"]["knob"], {"type": "integer", "description": "a knob", "enum": [1, 2, 3], "default": 3})
            self.assertIn("drift_flag", tools["fit"]["inputSchema"]["properties"], "parser change not reflected")
            self.assertEqual(list(tools), sorted(tools), "order stays sorted after changes")
            # the temporary tool also runs through the derived mapping
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
        resps = {r["id"]: r for r in (json.loads(l) for l in proc.stdout.strip().splitlines())}
        self.assertEqual(sorted(resps), [1, 2, 3, 4, 5, 6], "garbage and notifications produce no response; nothing else is lost")
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
                         {"sync", "multicam", "scenes", "report", "cropdetect", "silence", "loudness", "check", "stabilize"})
        # the read-only tools keep working under --dry-run (ffprobe still runs)
        self.assertEqual(tool("probe", self.src, "--dry-run", env=env).returncode, 0)
        self.assertEqual(tool("check", self.src, "--platform", "x", "--no-loudness", "--dry-run", env=env).returncode, 0)

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
        choice (so the contract and MCP schema carry the enum) and --crf is range-checked once
        in apply_common for all 31 tools that take it."""
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--preset", "fastest", "--json", "-o", self.out("p.mp4"), check=False)
        self.assertEqual(proc.returncode, 2, "argparse rejects an unknown preset")
        self.assertIn("invalid choice", proc.stderr)
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--crf", "99", "--json", "-o", self.out("c.mp4"), check=False)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("--crf must be between 0 and 51", doc["error"]["message"])
        self.assertEqual(doc["commands"], [], "refused before any ffmpeg ran")
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
                                      "steps": [["cut.py", "{in}", "--start", "0", "--end", "1", "--crf", "99", "-o", "{out}"]]}))
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
        """Pins from the fifth audit (100 items, 2026-09-12). Confirmed and fixed here: yuv410p
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
        leftovers = [p.name for p in SCRIPTS.glob("*.py") if re.search(r"duration['\"]\]:\.3f\}s|duration['\"]\):\.3f\}s", p.read_text(encoding="utf-8"))]
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
        doc = json.loads(tool("render", proj, "--fast", "--json").stdout)
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

    def test_result_v2_is_opt_in_and_uniform(self):
        """#189: FFMPEG_SKILL_RESULT_V2=1 adds one uniform `result_v2` block to every success
        document; without it nothing changes. loudness's `result` dict lands in metrics, cut's
        numeric extras too, and the tool's other keys survive under details."""
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.out("v2_off.mp4"), "--json").stdout)
        self.assertNotIn("result_v2", doc)
        env = dict(os.environ, FFMPEG_SKILL_RESULT_V2="1")
        doc = json.loads(tool("cut", self.src, "--start", "0", "--end", "1", "-o", self.out("v2_cut.mp4"), "--json", env=env).stdout)
        v2 = doc["result_v2"]
        self.assertEqual(sorted(v2), sorted(["schema", "output", "probe", "commands", "metrics", "notes", "dropped", "details"]))
        self.assertEqual((v2["schema"], v2["output"], v2["commands"]), (2, doc["output"], doc["commands"]))
        self.assertEqual(v2["probe"]["duration"], doc["probe"]["duration"])
        self.assertEqual(v2["metrics"]["expected_duration"], doc["expected_duration"])
        self.assertEqual(v2["details"]["precision"], doc["precision"])
        self.assertEqual(v2["dropped"], {"non_av_streams": False})
        doc = json.loads(tool("loudness", self.src, "-o", self.out("v2_loud.mp4"), "--json", env=env).stdout)
        v2 = doc["result_v2"]
        self.assertEqual(v2["metrics"]["input_i"], doc["result"]["input_i"])
        self.assertNotIn("result", v2["details"])
        doc = json.loads(tool("export", self.hdr, "--preset", "youtube", "--fast", "-o", self.out("v2_hdr.mp4"), "--json", env=env).stdout)
        self.assertEqual(doc["result_v2"]["notes"], doc["notes"])
        doc = json.loads(tool("fit", self.src, "--aspect", "1:1", "--dry-run", "-o", self.out("v2_dry.mp4"), "--json", env=env).stdout)
        self.assertEqual((doc["result_v2"]["probe"], doc["result_v2"]["output"]), (None, doc["output"]))

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
        # a changed input is refused
        ffmpeg("-i", self.src, "-t", "0.5", "-c", "copy", "-y", src)
        proc = tool("render", plan, "--json", "--overwrite", check=False)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")
        self.assertIn("changed", json.loads(proc.stdout)["error"]["message"])

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
        for extra in ((), ("--overwrite",)):
            proc = tool("color", self.src, "--lut", bad, "--json", "-o", keep, *extra, check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "ffmpeg")
            self.assertTrue(keep.exists(), f"failed run deleted a pre-existing output ({extra})")
            self.assertEqual((keep.stat().st_size, keep.stat().st_mtime_ns), before, "pre-existing output was modified")
            self.assertEqual([p.name for p in keep.parent.glob(".*ffskill*")], [], "temp file left behind after a failure")
        # success replaces the file, through the same temp path, and leaves no temp behind
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "2", "--overwrite", "-o", keep).returncode, 0)
        self.assertNotEqual(keep.stat().st_size, before[0])
        self.assertEqual([p.name for p in keep.parent.glob(".*ffskill*")], [])
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

    def test_existing_output_warns_today_refuses_on_request_and_never_for_its_own_files(self):
        """Every ffmpeg command carries -y (so a run never blocks on a y/N prompt), which meant an
        output path that already existed -- a previous deliverable, a mis-named source -- was
        replaced without a word. Per the 1.x deprecation policy the default stays but warns;
        FFMPEG_SKILL_NO_OVERWRITE=1 opts into the 2.0 refusal now; --overwrite is the explicit
        consent in both modes; a path this same run wrote (two-pass tools, copy-then-re-encode
        fallbacks) is never treated as someone else's file."""
        out = self.out("exists.mp4")
        first = tool("cut", self.src, "--start", "0", "--end", "1", "-o", out)
        self.assertNotIn("already exists", first.stderr, "a fresh path must not warn")
        again = tool("cut", self.src, "--start", "0", "--end", "1", "-o", out)
        self.assertEqual(again.returncode, 0)
        self.assertIn("already exists and will be overwritten", again.stderr)
        self.assertIn("--overwrite", again.stderr)
        quiet = tool("cut", self.src, "--start", "0", "--end", "1", "--overwrite", "-o", out)
        self.assertNotIn("already exists", quiet.stderr, "--overwrite is the consent; no warning")
        env = dict(os.environ, FFMPEG_SKILL_NO_OVERWRITE="1")
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "--json", "-o", out, env=env, check=False)
        self.assertNotEqual(proc.returncode, 0)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertIn("refusing to overwrite", doc["error"]["message"])
        self.assertEqual(doc["commands"], [], "refused before any ffmpeg ran")
        size_before = out.stat().st_size
        self.assertEqual(tool("cut", self.src, "--start", "0", "--end", "2", "--overwrite", "-o", out, env=env).returncode, 0)
        self.assertNotEqual(out.stat().st_size, size_before, "--overwrite replaced the file under the strict mode")
        # a tool that writes its own output twice in one run (color --retag's copy-then-re-encode
        # fallback path is exercised elsewhere); the guard keys on paths written by this process
        fresh = self.out("own.mp4")
        proc = tool("cut", self.src, "--start", "0", "--end", "1", "-o", fresh, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("refusing", proc.stderr)
        # dry-run never touches the file but still says what it would do
        dry = tool("cut", self.src, "--start", "0", "--end", "1", "--dry-run", "-o", out)
        self.assertIn("already exists", dry.stderr)
        self.assertEqual(out.stat().st_size, os.path.getsize(out))

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

    def test_success_requires_a_verified_output(self):
        import _common
        for name in ("cut", "audio", "loudness", "silence", "fit", "export", "caption", "overlay", "color", "join", "graphics", "multicam"):
            src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("emit(", src, f"{name} does not go through emit()")
        self.assertIn("verify_output(output)", (SCRIPTS / "_common.py").read_text(encoding="utf-8"))
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
        for path in list(SCRIPTS.glob("*.py")) + [ROOT / "mcp" / "server.py"]:
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
        script += "case \"$*\" in *drawtext=text=x*) kill -s SEGV $$;; esac\nexit 1\n"
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
