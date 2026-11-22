#!/usr/bin/env python3
"""Class guards: one test per kind of defect the ledger keeps recording, run over every tool.

docs/defect-guards.json names, for each class of docs/defect-ledger.jsonl with three or more
entries, the test here that catches the class wherever it happens: in the tools that exist and in
one written after the test. A fix of a class whose guard is pending does not pass revert_proof.py,
so a fix of one tool cannot be the end of a class that keeps coming back.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def chaptered_clip(path: Path, silence_in_the_middle: bool = False) -> None:
    """4 s, 160x90, chapters A 0-2 and B 2-4, Matroska (which keeps a chapter's exact start). With
    `silence_in_the_middle` the sound is a tone, 1.5 s of silence, a tone, for silence.py to cut."""
    work = path.parent
    meta = work / (path.stem + ".ffmeta")
    meta.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=A\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=B\n", encoding="utf-8")
    sound = (["-f", "lavfi", "-i", "sine=f=440:d=1:r=48000", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1.5",
              "-f", "lavfi", "-i", "sine=f=440:d=1.5:r=48000"] if silence_in_the_middle else ["-f", "lavfi", "-i", "sine=f=440:d=4:r=48000"])
    audio = "[1][2][3]concat=n=3:v=0:a=1[a]" if silence_in_the_middle else "[1]anull[a]"
    n_meta = 4 if silence_in_the_middle else 2
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=4", *sound,
                    "-f", "ffmetadata", "-i", str(meta), "-filter_complex", audio, "-map", "0:v", "-map", "[a]",
                    "-map_chapters", str(n_meta), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)


class TimeGuard(unittest.TestCase):
    """The time class (seven ledger entries by #696: a millisecond read as the next frame, a start
    timecode at the old rate, chapters left at the source's times by pad, fit, reverse, freeze,
    speedramp, cut --segments and silence). The common result writer says chapters_not_retimed
    whenever an output of another length carries chapters and its tool declared no time map
    (emit.source_carry, runner.declare_time_map); this runs every tool on a chaptered clip and
    fails on any tool that says it."""

    def test_no_tool_leaves_chapters_at_the_source_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sil = Path(tmp) / "chaptered.mkv", Path(tmp) / "chaptered_pause.mkv"
            chaptered_clip(src)
            chaptered_clip(sil, silence_in_the_middle=True)
            said = {}
            for source in (src, sil):
                facts = sweep.facts_for(str(source), tmp)
                # the tools that write a media file: a verdict or a measurement has no chapters to carry
                tools = [t for t, (_, ext) in sweep.TABLE.items() if ext and ext not in (".png", ".jpg")] if source == src else ["silence"]
                for tool in tools:
                    row = sweep.row_for(tool, str(source), facts, tmp)
                    if row.get("status") != "completed":
                        said[tool] = f"did not complete, so it was not checked: {row.get('message')}"
                    elif "chapters_not_retimed" in (row.get("warnings") or []):
                        said[tool] = row
            # the multi-range joins are not in the sweep's table (one minimal call per tool)
            for argv in (["--segments", "0-1,2.5-4"], ["--remove", "1-2.5"], ["--segments", "0-1,2.5-4", "--accurate"]):
                doc, _ = sweep.run_json([sys.executable, str(ROOT / "scripts" / "cut.py"), str(src), *argv,
                                         "-o", str(Path(tmp) / "joined.mkv"), "--overwrite", "--json"])
                codes = [w.get("code") for w in ((doc or {}).get("diagnostics") or {}).get("warnings") or []]
                if "chapters_not_retimed" in codes:
                    said["cut " + " ".join(argv)] = doc.get("diagnostics")
            self.assertEqual(said, {}, "these tools moved the picture in time and left the chapters where the source had them")


def awkward_clip(path: Path) -> None:
    """The source the sweep guards run every tool on: 320x180 (16:9), 4 s, 5.1 sound, two
    chapters and a mov_text subtitle track, MP4. Each property is one a tool has lost or
    misreported before (#470 5.1 folded, #696 chapters, #539 subtitles)."""
    work = path.parent
    meta = work / "awkward.ffmeta"
    meta.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=A\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=B\n", encoding="utf-8")
    srt = work / "awkward.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nhello\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4",
                    "-f", "lavfi", "-i", "sine=f=440:d=4:r=48000", "-i", str(srt), "-f", "ffmetadata", "-i", str(meta),
                    "-filter_complex", "[1]pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0[a]", "-map", "0:v", "-map", "[a]", "-map", "2",
                    "-map_chapters", "3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-c:s", "mov_text", "-t", "4", str(path)], check=True)


def ffprobe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out or "{}")


class SweepGuards(unittest.TestCase):
    """Every tool of tests/sweep.py's table, and the multi-input tools by hand, run once on the
    awkward clip with stdin an open pipe that is never written or closed (the shape an MCP client
    or an agent's shell gives a child, #664). The outputs are kept for the guards below."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        work = cls.work = Path(cls.tmp.name)
        cls.src = str(work / "awkward.mp4")
        awkward_clip(Path(cls.src))
        facts = sweep.facts_for(cls.src, str(work))
        second = str(work / "second.mp4")
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=2",
                        "-f", "lavfi", "-i", "sine=f=880:d=2:r=48000", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", second], check=True)
        calls = {}
        for tool, (args, ext) in sweep.TABLE.items():
            out = str(work / f"g_{tool.replace(' ', '_').replace('-', '')}{ext}") if ext else None
            calls[tool] = ([tool.split()[0], cls.src, *[a.format(**facts) for a in args]], out)
        by_hand = {"join": ["join", cls.src, second, "--transition", "none"],
                   "broll": ["broll", cls.src, "--insert", second, "--at", "1", "--duration", "1", "--audio", "mix"],
                   "insert": ["insert", facts["still"], "--duration", "1"],
                   "sync": ["sync", cls.src, second, "--replace-audio"],
                   # a frame of the other shape: bars (#665) and a crop (#688)
                   "export reels pad": ["export", cls.src, "--preset", "reels", "--no-normalize"],
                   "export reels crop": ["export", cls.src, "--preset", "reels", "--fit", "crop", "--no-normalize"],
                   "fit 9:16 crop": ["fit", cls.src, "--aspect", "9:16", "--fit", "crop"],
                   "fit 9:16 pad": ["fit", cls.src, "--aspect", "9:16"],
                   # a font folder without the asked face: nothing about the face is established (#663)
                   "caption fonts-dir": ["caption", cls.src, "--text", facts["cues"], "--fonts-dir", str(work), "--font", "Nowhere Sans"]}
        for name, argv in by_hand.items():
            calls[name] = (argv, str(work / f"g_{name.replace(' ', '_').replace(':', '')}.mp4"))
        cls.runs = {}
        for name, (argv, out) in calls.items():
            cmd = [sys.executable, str(ROOT / "scripts" / f"{argv[0]}.py"), *argv[1:], *(["-o", out] if out else []), "--overwrite", "--json"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace")
            try:
                stdout, stderr = _wait_with_open_stdin(proc)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                cls.runs[name] = {"hung": True, "out": out, "doc": None, "stderr": stderr}
                continue
            start = stdout.find("{")
            try:
                doc = json.loads(stdout[start:]) if start >= 0 else None
            except ValueError:
                doc = None
            cls.runs[name] = {"hung": False, "out": out, "doc": doc if isinstance(doc, dict) else None, "stderr": stderr}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _done(r):
        # probe.py's success document is the measurement itself (no status key); check.py's failed
        # verdict is an answer about the file, not a failure of the tool
        doc = r["doc"] or {}
        return bool(doc) and (doc.get("status") == "completed" or ("status" not in doc and not doc.get("error"))
                              or (not r["out"] and (doc.get("error") or {}).get("kind") == "verification"))

    def completed(self):
        return {n: r for n, r in self.runs.items() if self._done(r)}

    def test_every_tool_completed_so_the_guards_saw_it(self):
        """A guard that skips a tool that failed guards nothing there: the first version of the claim
        guard passed with broll folding 5.1 to stereo, because a fixture cut short by its subtitle
        track made broll refuse, and the refusal was skipped. Every call here completes."""
        failed = {n: ((r["doc"] or {}).get("error") or {}).get("message") or r["stderr"][-200:]
                  for n, r in self.runs.items() if not self._done(r)}
        self.assertEqual(failed, {})

    def test_every_tool_answers_while_its_stdin_stays_open(self):
        """automation (#664 and the two before it): a tool started with an open, silent stdin --
        an MCP client's pipe, an agent's shell -- ends and answers, with no child left waiting
        on it. The MCP server's own path is test_mcp_answers_a_tool_call_while_the_client_keeps_its_pipe_open."""
        self.assertEqual([n for n, r in self.runs.items() if r["hung"]], [])
        self.assertEqual([n for n, r in self.runs.items() if r["doc"] is None], [], {n: r["stderr"][-300:] for n, r in self.runs.items() if r["doc"] is None})

    def test_what_a_caller_sees_first_is_right_on_every_tool(self):
        """surface (#470 stream order, #558 help text, #620's first line): the picture is the first
        stream of every output that has one, and a result that wrote media starts with status
        and wrote. Help text on every option is test_every_option_has_help_text."""
        wrong = {}
        for name, r in self.completed().items():
            doc, out = r["doc"], r["out"]
            if not out or not os.path.exists(out):
                continue
            kinds = [s.get("codec_type") for s in ffprobe(out).get("streams", [])
                     if not (s.get("disposition") or {}).get("attached_pic")]
            if "video" in kinds and kinds[0] != "video":
                wrong[name] = f"stream order {kinds}"
            if doc.get("probe") and os.path.splitext(out)[1] not in (".png", ".jpg", ".gif") and list(doc)[:2] != ["status", "wrote"]:
                wrong[name] = f"first keys {list(doc)[:3]}"
        self.assertEqual(wrong, {})

    def test_no_record_judges_a_file_it_does_not_name(self):
        """not_measured, the half the dry runs cannot reach: font_used said substituted: false with
        file: null (#663)."""
        found = {n: judged_without_a_file(r["doc"]) for n, r in self.completed().items()}
        self.assertEqual({n: f for n, f in found.items() if f}, {})

    def test_a_result_never_says_less_than_the_output_lost(self):
        """claim (#665 bars, #688 a crop, #470 a 5.1 A-roll folded, #620 a length miss): every
        output is compared with the awkward clip, and a loss the result does not state fails --
        fewer sound channels, or a picture whose frame is another shape, with no warning,
        source_carry entry or note that says it. The single-input tools say it through
        source_carry; this is what holds the multi-input ones and any tool written later to it."""
        src = ffprobe(self.src)
        s_ch = max(int(s.get("channels") or 0) for s in src["streams"] if s.get("codec_type") == "audio")
        s_v = next(s for s in src["streams"] if s.get("codec_type") == "video")
        s_ar = int(s_v["width"]) / int(s_v["height"])
        unsaid = {}
        for name, r in self.completed().items():
            doc, out = r["doc"], r["out"]
            if not out or not os.path.exists(out) or os.path.splitext(out)[1] in (".png", ".jpg", ".gif"):
                continue
            o = ffprobe(out)
            said = json.dumps({k: doc.get(k) for k in ("source_carry", "diagnostics", "notes")}).lower()
            a = [int(s.get("channels") or 0) for s in o.get("streams", []) if s.get("codec_type") == "audio"]
            # sync --replace-audio puts the other file's sound in by request: its channels are the point
            if a and max(a) < s_ch and name != "sync" and "audio_channels" not in said and "channel" not in said:
                unsaid[name] = f"{s_ch} channels became {max(a)}"
            v = [s for s in o.get("streams", []) if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
            # a frame of another shape keeps min(r, 1/r) of the picture (a crop) or fills that much of
            # the frame (a pad); below one half the result names it by its warning code
            r_ = (int(v[0]["width"]) / int(v[0]["height"])) / s_ar if v else 1.0
            if v and min(r_, 1 / r_) < 0.5 and name not in ("crop", "insert") \
                    and not any(k in said for k in ("picture_small_in_frame", "picture_mostly_cropped")):
                unsaid[name] = f"frame {v[0]['width']}x{v[0]['height']} from {s_v['width']}x{s_v['height']}, nothing said"
        self.assertEqual(unsaid, {})


def _wait_with_open_stdin(proc):
    """communicate() closes stdin; the guard keeps it open, so read the pipes until the tool exits."""
    import threading
    out, err = [], []
    t1 = threading.Thread(target=lambda: out.append(proc.stdout.read()))
    t2 = threading.Thread(target=lambda: err.append(proc.stderr.read()))
    t1.start(); t2.start()
    try:
        proc.wait(timeout=sweep.TIMEOUT_S)
    finally:
        proc.stdin.close()
    t1.join(); t2.join()
    proc.stdout.close(); proc.stderr.close()
    return (out[0] if out else ""), (err[0] if err else "")


class NotMeasuredGuard(unittest.TestCase):
    """not_measured (#663 and five before it): a value is reported as measured where nothing was
    measured. Every tool of the sweep's table is run with --dry-run (nothing is written, so
    nothing about the output can be known) and must say so: verified false, no probe, no `wrote`,
    the output measurements null. And in every result of the sweep guards' real runs, a record
    that names no file (`file: null`) carries no boolean judgement about that file."""

    def test_a_dry_run_reports_nothing_about_an_output_it_did_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "plain.mkv"
            chaptered_clip(src)
            facts = sweep.facts_for(str(src), tmp)
            claimed = {}
            for tool, (args, ext) in sweep.TABLE.items():
                if not ext:
                    continue
                cmd = [sys.executable, str(ROOT / "scripts" / f"{tool.split()[0]}.py"), str(src), *[a.format(**facts) for a in args],
                       "-o", str(Path(tmp) / f"dry{ext}"), "--dry-run", "--json"]
                doc, _ = sweep.run_json(cmd)
                if not isinstance(doc, dict) or doc.get("status") != "completed":
                    claimed[tool] = "did not complete, so it was not checked"
                    continue
                wrong = [k for k in ("probe", "wrote", "output_identity") if doc.get(k)]
                wrong += ["verified"] if doc.get("verified") else []
                wrong += [k for k in ("duration", "width", "height", "fps", "size_bytes") if doc.get(k) is not None]
                if wrong:
                    claimed[tool] = wrong
            self.assertEqual(claimed, {})


def judged_without_a_file(node, path=""):
    """Every place in a result where a record has file: null and a true/false about it."""
    found = []
    if isinstance(node, dict):
        if "file" in node and node["file"] is None:
            found += [f"{path}.{k}" for k, v in node.items() if isinstance(v, bool) and k in ("substituted", "embedded", "exists", "matched")]
        for k, v in node.items():
            found += judged_without_a_file(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += judged_without_a_file(v, f"{path}[{i}]")
    return found


class FfmpegVersionGuard(unittest.TestCase):
    """ffmpeg_version (#659, #671, #556): every tool passes through the shared version gate and
    warns once per run (stderr + diagnostics.warnings) when the FFmpeg build sits outside
    TESTED_FFMPEG_MAJORS, rather than failing silently or differing per tool."""

    def test_every_tool_warns_once_on_untested_ffmpeg(self):
        import platform
        import shutil
        real = shutil.which("ffprobe")
        if not real:
            self.skipTest("ffprobe not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            src = work / "plain.mkv"
            chaptered_clip(src)
            facts = sweep.facts_for(str(src), tmp)
            shim = work / "shim"
            shim.mkdir()
            if platform.system() == "Windows":
                (shim / "ffprobe.cmd").write_text(
                    '@echo off\r\nif "%~1"=="-version" (\r\necho ffprobe version 10.0.1 Copyright\r\nexit /b 0\r\n)\r\n'
                    f'"{real}" %*\r\n',
                    encoding="utf-8",
                )
            else:
                (shim / "ffprobe").write_text(
                    '#!/bin/sh\nif [ "$1" = "-version" ]; then printf "%s\\n" "ffprobe version 10.0.1 Copyright"; exit 0; fi\n'
                    f'exec "{real}" "$@"\n',
                    encoding="utf-8",
                )
                (shim / "ffprobe").chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
            missed = {}
            for tool, (args, ext) in sweep.TABLE.items():
                # verify.py ignores --dry-run, captures _probe_capturing() stderr, and delegates to child scripts
                if tool == "verify":
                    continue
                name = tool.split()[0]
                out = ["-o", str(work / f"fv_{tool.replace(' ', '_').replace('-', '')}{ext}")] if ext else []
                cmd = [sys.executable, str(ROOT / "scripts" / f"{name}.py"), str(src),
                       *[a.format(**facts) for a in args], *out, "--dry-run", "--json"]
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=sweep.TIMEOUT_S)
                start = proc.stdout.find("{")
                try:
                    doc = json.loads(proc.stdout[start:]) if start >= 0 else None
                except ValueError:
                    doc = None
                err_hits = proc.stderr.count("warning: FFmpeg 10.0 is outside")
                if err_hits != 1:
                    missed[tool] = f"stderr warning count={err_hits}; rc={proc.returncode}; tail={proc.stderr[-160:]}"
                    continue
                if isinstance(doc, dict) and "diagnostics" in doc:
                    codes = [w.get("code") for w in (doc.get("diagnostics") or {}).get("warnings") or []]
                    if codes.count("ffmpeg_version_untested") != 1:
                        missed[tool] = f"diagnostics warnings={codes}"
            self.assertEqual(missed, {})


class GuardRegistryTests(unittest.TestCase):
    def test_every_class_with_three_entries_has_a_guard_or_a_pending_issue(self):
        """A class the ledger records three times is registered in docs/defect-guards.json, with
        the test that guards it or the issue where the guard is still to be written; a registered
        test exists. A new class that reaches three fails this until it is registered."""
        guards = json.loads((ROOT / "docs" / "defect-guards.json").read_text(encoding="utf-8"))
        rows = [json.loads(l) for l in (ROOT / "docs" / "defect-ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        counts = {}
        for r in rows:
            counts[r["class"]] = counts.get(r["class"], 0) + 1
        due = sorted(c for c, n in counts.items() if n >= guards["threshold"])
        self.assertEqual([c for c in due if c not in guards["classes"]], [], "classes recorded often enough to need a guard")
        sources = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
        for name, entry in guards["classes"].items():
            self.assertTrue(entry.get("test") or entry.get("pending"), name)
            if entry.get("test"):
                module, cls, method = entry["test"].split(".")
                self.assertIn(f"def {method}(", (ROOT / "tests" / f"{module}.py").read_text(encoding="utf-8"), entry["test"])
                self.assertIn(f"class {cls}(", sources, entry["test"])


if __name__ == "__main__":
    unittest.main()
