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
        # join is the one picture tool that also accepts audio-only inputs (audio concat); look applies
        # to its video output only, which SKILL.md states next to "Look: not needed"
        both = {"join"}
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

    # 6.1 and 9.0.1 are captures (Ubuntu apt, Windows gyan.dev build); 7.1 and 8.0 are constructed layouts
    FILTER_FIXTURES = ("ffmpeg_filters_6.1.txt", "ffmpeg_filters_7.1_constructed.txt", "ffmpeg_filters_8.0_constructed.txt", "ffmpeg_filters_9.0.1_windows.txt")

    def test_parser_reads_ffmpeg_6_7_8_9_layouts(self):
        for name in self.FILTER_FIXTURES:
            names = _contract._parse_ff_list("-filters", (self.FIX / name).read_text())
            self.assertGreater(len(names), 500, name)
            for f in ("xfade", "loudnorm", "acompressor", "abuffer", "concat", "scale", "drawtext"):
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
        for enc_name in ("ffmpeg_encoders_6.1.txt", "ffmpeg_encoders_9.0.1_windows.txt"):
            enc = _contract._parse_ff_list("-encoders", (self.FIX / enc_name).read_text())
            self.assertIn("libx264", enc, enc_name)
            self.assertIn("aac", enc, enc_name)
            self.assertNotIn("=", enc, enc_name)
        for bsf_name in ("ffmpeg_bsfs_6.1.txt", "ffmpeg_bsfs_9.0.1_windows.txt"):
            self.assertIn("filter_units", _contract._parse_ff_list("-bsfs", (self.FIX / bsf_name).read_text()), bsf_name)
        self.assertEqual(_contract._parse_ff_list("-filters", (self.FIX / "ffmpeg_filters_garbage.txt").read_text()), [])

    def test_two_character_flags_do_not_hide_filters(self):
        """The FFmpeg 8 layout: every declared filter is found, nothing is reported missing or unknown."""
        for name in self.FILTER_FIXTURES:
            d, code = self._doctor(name)
            declared = [c for c in _contract.required_capabilities()["required"] + _contract.required_capabilities()["optional"] if c.startswith("filter:")]
            self.assertTrue(declared)
            for cap in declared:
                self.assertIn(cap, d["available"], f"{cap} with {name}")
            self.assertEqual([c for c in d["missing"] if c.startswith("filter:")], [], name)
            self.assertEqual(d["unknown"], [], name)
            self.assertEqual(d["detection"]["filters"]["status"], "parsed", name)
            self.assertTrue(d["ok"], name)
            self.assertEqual(code, 0, name)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
