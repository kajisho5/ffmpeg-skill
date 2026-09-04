#!/usr/bin/env python3
"""Contract tests: the machine-readable execution contract matches the scripts, the MCP
server and the installer, and every ToolSpec claim (dry-run, JSON shape, input preservation,
verification policy) holds when the tool actually runs.

    python3 tests/test_contract.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out"))
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "mcp"))
import _contract  # noqa: E402
import server as mcp_server  # noqa: E402


def sh(*cmd, check=True, env=None, cwd=None):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=cwd)
    if check and proc.returncode != 0:
        raise AssertionError(f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def ffmpeg(*args):
    return sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args)


def tool(name, *args, **kw):
    return sh(sys.executable, SCRIPTS / f"{name}.py", *args, **kw)


TONE = "0.5*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.2)+0.3*sin(2*PI*660*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg/ffprobe not on PATH")
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
               "-vsync", "vfr", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", cls.vfr)
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

    def test_skill_metadata_and_version_separation(self):
        pkg = json.loads((ROOT / "package.json").read_text())
        self.assertEqual(self.contract["skill"]["version"], pkg["version"])
        self.assertEqual(self.contract["contract_version"], _contract.CONTRACT_VERSION)
        self.assertNotEqual(self.contract["contract_version"], self.contract["skill"]["version"])
        self.assertTrue(re.fullmatch(r"\d+\.\d+", self.contract["contract_version"]))
        self.assertIn("Edit video and audio", self.contract["skill"]["description"])
        for t in self.contract["tools"]:
            self.assertEqual(t["version"], pkg["version"])

    def test_tool_ids_unique_and_canonical(self):
        ids = [t["id"] for t in self.contract["tools"]]
        self.assertEqual(len(ids), len(set(ids)))
        for t in self.contract["tools"]:
            self.assertEqual(t["id"], f"ffmpeg-skill/{t['name']}")
            self.assertTrue(re.fullmatch(r"[a-z]+", t["name"]), t["id"])
        self.assertEqual(ids, sorted(ids), "tools are listed in a stable, sorted order")

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

    def test_dry_run_metadata(self):
        for t in self.contract["tools"]:
            has_flag = "dry_run" in t["input_schema"]["properties"]
            self.assertEqual(t["supports_json"], "json" in t["input_schema"]["properties"])
            if t["name"] == "verify":
                self.assertFalse(t["supports_dry_run"], "verify runs its steps regardless of --dry-run")
            else:
                self.assertEqual(t["supports_dry_run"], has_flag, t["name"])
            self.assertEqual(t["dry_run"]["supported"], t["supports_dry_run"])

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
        picture = {"fit", "caption", "overlay", "graphics", "color", "join", "multicam", "render"}
        for t in self.contract["tools"]:
            self.assertEqual(t["requires_visual_verification"], t["name"] in picture, t["name"])
            if t["requires_visual_verification"]:
                self.assertIn("ffmpeg-skill/look", t["verification"]["tools"])
                self.assertTrue(t["video_required"])
                self.assertFalse(t["audio_only"])
            if t["audio_only"]:
                self.assertFalse(t["requires_visual_verification"], f"{t['name']}: audio-only tools never need look.py")
        for name in ("loudness", "silence", "audio", "cut", "sync", "probe", "check"):
            self.assertTrue(self.tools[name]["audio_only"], name)
        # SKILL.md says the same thing
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Look: not needed", skill)

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

    def test_contract_from_installed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp)
            sh("node", ROOT / "bin" / "install.js", env=env)
            installed = Path(tmp) / ".claude" / "skills" / "ffmpeg-skill"
            doc = json.loads(sh(sys.executable, installed / "scripts" / "_contract.py", "--json", "--static").stdout)
            self.assertEqual(doc["skill"]["version"], self.contract["skill"]["version"])
            self.assertEqual([t["id"] for t in doc["tools"]], [t["id"] for t in self.contract["tools"]])
            for t in doc["tools"]:
                self.assertTrue((installed / t["executable"]).is_file())

    # ------------------------------------------------------------------ integration: claims hold at run time
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
            "export": [self.src, "--preset", "x", "-o", outdir / "exp.mp4"],
            "scenes": [self.src, "--sheet", outdir / "sc.png", "--edl", outdir / "sc.txt"],
            "look": [self.src, "-o", outdir / "look.png"],
            "report": ["--after", self.src, "-o", outdir / "rep.html"],
        }
        for name, args in cases.items():
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
        self.assertEqual({n for n, s in self.tools.items() if s["dry_run"]["ffmpeg_execution"] == "analysis_only"}, {"sync", "multicam", "scenes", "report"})
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
        doc = self._run_structured("sync", {"reference": str(self.src), "second": str(self.mic)})
        self.assertAlmostEqual(doc["offset_seconds"], 1.5, delta=0.05)
        doc = self._run_structured("sync", {"reference": str(self.src), "second": str(self.mic), "replace_audio": True, "output": str(self.out("synced.mp4"))})
        self._verify("sync", doc["output"])
        doc = self._run_structured("audio", {"input": str(self.surround), "downmix": True, "output": str(self.out("stereo.mov"))})
        self.assertEqual(doc["probe"]["audio"]["channels"], 2)
        self._verify("audio", doc["output"])

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
                                       "clips": [{"src": str(self.src), "in": 0, "out": 3}], "export": {"preset": "reels"}, "check": {"platform": "reels"}}), encoding="utf-8")
        doc = self._run_structured("render", {"project": str(project), "fast": True})
        self.assertEqual(doc["status"], "completed")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
