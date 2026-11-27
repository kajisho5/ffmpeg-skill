#!/usr/bin/env python3
"""Class guards: one test per kind of defect the ledger keeps recording, run over every tool.

docs/defect-guards.json names, for each class of docs/defect-ledger.jsonl with three or more
entries, the test here that catches the class wherever it happens: in the tools that exist and in
one written after the test. A fix of a class whose guard is pending does not pass revert_proof.py,
so a fix of one tool cannot be the end of a class that keeps coming back.
"""
import ast
import importlib.util
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

    def test_sweep_mp4_audio_and_video_streams_decode(self):
        """Decode the MP4 outputs in the cross-tool sweep on this FFmpeg build.

        The sweep also writes a PNG and has inspection-only tools; those are not MP4s.
        Pixel-value regressions still need their own tests: a successful decode cannot see them.
        """
        runs = {n: r for n, r in self.runs.items() if r["out"] and Path(r["out"]).suffix.lower() == ".mp4"}
        self.assertTrue(runs, "the sweep produced no MP4 cases")
        for name, run in runs.items():
            with self.subTest(tool=name):
                self.assertTrue(self._done(run), f"{name} did not complete: {run['stderr'][-500:]}")
                proc = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                       "stream=codec_type,nb_read_frames", "-of", "json", run["out"]],
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertFalse(proc.stderr.strip(), proc.stderr)
                media = [s for s in json.loads(proc.stdout)["streams"] if s["codec_type"] in ("video", "audio")]
                self.assertTrue(media, run["out"])
                for stream in media:
                    frames = stream.get("nb_read_frames", "")
                    self.assertTrue(frames.isdigit() and int(frames) > 0, stream)

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


def hdr_rgb_clip(path: Path) -> None:
    """2 s of flat red as an HDR RGB picture (gbrp10le FFV1, BT.2020 primaries, PQ), with sound: the
    source that reached the two colour defects (#559 made its YUV with BT.601 under a bt709 tag, #711
    left its primaries and transfer in the container under a bt709 stream)."""
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=0xC03028:s=320x180:r=25:d=2,format=gbrp10le", "-f", "lavfi", "-i", "sine=f=440:d=2:r=48000",
                    "-c:v", "ffv1", "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "rgb",
                    "-c:a", "flac", "-ac", "2", str(path)], check=True)


_SDR = {"bt709", "smpte170m", "bt470bg"}
_HDR = {"bt2020", "bt2020nc", "bt2020c", "smpte2084", "arib-std-b67"}


def mixed_tags(v: dict):
    """The colour tags of a video stream that say two things at once (a BT.709 matrix over BT.2020/PQ
    primaries or transfer, or the reverse), or None. A player picks one of them."""
    tags = {k: v.get(k) for k in ("color_space", "color_primaries", "color_transfer") if v.get(k) not in (None, "unknown")}
    return tags if set(tags.values()) & _SDR and set(tags.values()) & _HDR else None


class ColorGuard(unittest.TestCase):
    """The color class (#559, #711): an output's tags claim a colour its pixels or its other tags do not
    have. Every tool that writes video, and the BT.709 presets and the mixing tools by hand, run on an
    HDR RGB source; an output whose matrix, primaries and transfer mix SDR and HDR names fails. On
    FFmpeg before 9 the #711 form cannot show (the container's tags came from the encoder), so CI's
    FFmpeg 9 jobs are where this bites hardest."""

    def test_no_output_mixes_sdr_and_hdr_colour_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "hdr_rgb.mkv"
            hdr_rgb_clip(src)
            facts = sweep.facts_for(str(src), tmp)
            outs = {}
            for tool, (_, ext) in sweep.TABLE.items():
                if ext in (".mp4", ".mov", ".mkv", ".webm"):
                    row = sweep.row_for(tool, str(src), facts, tmp)
                    if row.get("status") == "completed":
                        outs[tool] = os.path.join(tmp, f"sweep_{tool.replace(' ', '_').replace('-', '')}{ext}")
            for name, argv in {"export youtube": ["export", str(src), "--preset", "youtube"],
                               "export prores": ["export", str(src), "--preset", "prores"],
                               "grid": ["grid", str(src), str(src)], "join": ["join", str(src), str(src), "--transition", "none"]}.items():
                out = os.path.join(tmp, name.replace(" ", "_") + (".mov" if "prores" in name else ".mp4"))
                doc, _ = sweep.run_json([sys.executable, str(ROOT / "scripts" / f"{argv[0]}.py"), *argv[1:], "-o", out, "--overwrite", "--json"])
                if (doc or {}).get("status") == "completed":
                    outs[name] = out
            self.assertIn("export youtube", outs, "the BT.709 preset ran, so the guard saw the line #711 was found on")
            mixed = {}
            for name, out in outs.items():
                v = next((st for st in ffprobe(out).get("streams", []) if st.get("codec_type") == "video"), {})
                if mixed_tags(v):
                    mixed[name] = mixed_tags(v)
            self.assertEqual(mixed, {}, "these outputs say SDR in one colour tag and HDR in another")


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


_OUTPUT_FLAGS = {"-o", "--output", "--out", "--output-dir", "--out-dir", "--outdir"}
_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch", "symlink_to", "hardlink_to"}
_COPIES = {"copy", "copy2", "copyfile", "copytree", "move"}

# A test that writes a fixed name into a shared directory and is still right to: none today. An entry
# is "file.py:function: the name", with the reason the collision cannot happen.
SHARED_WRITE_BY_DESIGN: "dict[str, str]" = {}


def _call_name(node):
    f = node.func if isinstance(node, ast.Call) else node
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _is_text(node):
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


class _SharedPaths:
    """Which expressions of one test module name a directory every test, run and module shares:
    _fixtures.SHARED_OUT, tests/out spelled out, $OUT read by hand, tempfile.gettempdir(), and a
    module-level name bound to one of them -- or to OUT itself, which outside a test method (at import)
    is SHARED_OUT, so `DIR = OUT / "cut_copy"` is #685's old form and `DIR = OUT.sub("cut_copy")` is not."""

    def __init__(self, tree):
        self.proxies = {"OUT"}   # names that are the per-test proxy inside a test method
        self.shared = {"SHARED_OUT"}
        for node in tree.body + [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body]:
            if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
                names = {t.id for t in node.targets}
                v = node.value
                if isinstance(v, ast.Call) and _call_name(v) == "sub" and self.is_proxy(v.func.value):
                    self.proxies |= names
                elif self.is_proxy(v):
                    self.proxies |= names
                elif self.is_dir(v, at_import=True):
                    self.shared |= names
                    self.proxies -= names

    def is_proxy(self, node):
        return (isinstance(node, ast.Name) and node.id in self.proxies) or (isinstance(node, ast.Attribute) and node.attr == "OUT")

    def is_dir(self, node, at_import=False, local=()):
        if isinstance(node, ast.Name):
            return node.id in self.shared or node.id in local or (at_import and node.id in self.proxies)
        if isinstance(node, ast.Attribute):
            return node.attr == "SHARED_OUT" or (at_import and self.is_proxy(node))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return "tests/out" in node.value.replace("\\", "/")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if isinstance(node.right, ast.Constant) and node.right.value == "out" and isinstance(node.left, ast.BinOp) \
                    and isinstance(node.left.right, ast.Constant) and node.left.right.value == "tests":
                return True
            return self.is_dir(node.left, at_import, local)
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "gettempdir":
                return True
            if name in ("get", "getenv") and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "OUT":
                return True
            if name in ("Path", "PurePath", "str", "fspath", "resolve", "_path"):
                inner = node.args[0] if node.args else (node.func.value if isinstance(node.func, ast.Attribute) else None)
                return inner is not None and self.is_dir(inner, at_import, local)
            if name == "join" and node.args:
                return self.is_dir(node.args[0], at_import, local)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "OUT":
            return True
        return False

    def is_named_file(self, node, local_dirs, local_files):
        """A path into a shared directory with a name the test wrote down."""
        if isinstance(node, ast.Name):
            return node.id in local_files
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return _is_text(node.right) and self.is_dir(node.left, local=local_dirs)
        if isinstance(node, ast.Call) and node.args:
            name = _call_name(node)
            if name == "join" and len(node.args) > 1:
                return self.is_dir(node.args[0], local=local_dirs) and any(_is_text(a) for a in node.args[1:])
            if name == "joinpath" and isinstance(node.func, ast.Attribute):
                return self.is_dir(node.func.value, local=local_dirs) and any(_is_text(a) for a in node.args)
            if name in ("Path", "str", "fspath"):
                return self.is_named_file(node.args[0], local_dirs, local_files)
        return False


def shared_writes(path: Path) -> "list[str]":
    """Every place a test method (or setUp) of `path` writes a fixed name into a shared directory:
    the path's write_text/write_bytes/mkdir/touch, open() for writing, shutil's destination, the
    value after -o/--output, or the last argument of an ffmpeg-style call (one with "-i"). Reads of
    a shared fixture, and setUpClass, which builds the shared fixtures, are not writes here."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sp = _SharedPaths(tree)
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not (fn.name.startswith("test") or fn.name == "setUp"):
            continue
        dirs, files = set(), set()
        for _ in range(2):  # an alias of an alias
            for node in ast.walk(fn):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    names = {t.id for t in targets if isinstance(t, ast.Name)}
                    if node.value is None:
                        continue
                    if sp.is_named_file(node.value, dirs, files):
                        files |= names
                    elif sp.is_dir(node.value, local=dirs):
                        dirs |= names
        hit = lambda n: sp.is_named_file(n, dirs, files)  # noqa: E731
        for node in ast.walk(fn):
            written = []
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if isinstance(node.func, ast.Attribute) and hit(node.func.value) and (
                        name in _WRITE_METHODS or (name == "open" and any(_is_text(a) and set(a.value) & set("wax+") for a in node.args
                                                                          if isinstance(a, ast.Constant)))):
                    written.append(node.func.value)
                if name == "open" and isinstance(node.func, ast.Name) and node.args:
                    mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
                    if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+"):
                        written.append(node.args[0])
                if name in _COPIES and len(node.args) > 1:
                    written.append(node.args[1])
                if any(isinstance(a, ast.Constant) and a.value == "-i" for a in node.args) and node.args:
                    written.append(node.args[-1])
            if isinstance(node, (ast.Call, ast.List, ast.Tuple)):
                seq = node.args if isinstance(node, ast.Call) else node.elts
                written += [b for a, b in zip(seq, seq[1:]) if isinstance(a, ast.Constant) and a.value in _OUTPUT_FLAGS]
            for w in written:
                if hit(w):
                    found.append(f"{path.name}:{fn.name}: {ast.unparse(w)} (line {w.lineno})")
    return sorted(set(found))


def _slot_negatives(slot: str) -> "tuple[list[str], list[str]]":
    """(texts that call nothing the slot names, texts that call it), for each alternative of a slot.
    A negative holds the alternative's stem inside a longer word or file, as prose, as another file
    of the same stem, in another case, or as a longer flag; a positive is the call itself, so a
    negative that passes is not passing because the matcher fills nothing."""
    neg, pos = [], []
    for alt in (a.strip() for a in slot.split("|")):
        if not alt:
            continue
        if alt.startswith("-"):
            neg += [f"$ python3 scripts/x.py {alt}-presets a", f"$ python3 scripts/x.py {alt}x a", f"$ python3 scripts/x.py {alt}_b a",
                    f"$ python3 scripts/x.py x{alt} a"]
            pos += [f"$ python3 scripts/x.py {alt} a"]
            continue
        stem = alt[:-3] if alt.endswith(".py") else alt
        neg += [f"I will {stem} the clip", f"execute pre{stem} and {stem}s", f"$ python3 scripts/auto_{stem}.py a",
                f"$ python3 scripts/short{stem}.py a", f"$ python3 scripts/pre-{stem}.py a", f"$ python3 scripts/{stem}_x.py a",
                f"$ python3 scripts/x.{stem}.py a", f"$ ls {stem}.pyc {stem}.py.bak {stem}.mp4", f"$ python3 scripts/{stem.capitalize()}.py a"
                if stem.capitalize() != stem else f"$ python3 scripts/{stem.upper()}.py a", f"mcp__ffmpeg-skill__{stem}_x", f"mcp__ffmpeg-skill__x{stem}"]
        pos += [f"$ python3 scripts/{stem}.py in.mp4 --json"] + ([f"mcp__ffmpeg-skill__{stem}"] if not alt.endswith(".py") else [])
    return neg, pos


def _hand_rolled_slot_tests(tree) -> "list[int]":
    """Lines where a grader tests an alternative of a slot (a name bound by iterating x.split("|"))
    with `in`: a substring of the text or a member of a word set, the form #786's second entry was."""
    lines = []
    for node in ast.walk(tree):
        gens = node.generators if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)) else \
            [node] if isinstance(node, (ast.For, ast.comprehension)) else []
        for g in gens:
            it = g.iter
            if isinstance(it, ast.Call) and _call_name(it) == "split" and it.args and isinstance(it.args[0], ast.Constant) \
                    and it.args[0].value == "|" and isinstance(g.target, ast.Name):
                for n in ast.walk(node):
                    if isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops) \
                            and any(isinstance(s, ast.Name) and s.id == g.target.id for s in ast.walk(n.left)):
                        lines.append(n.lineno)
    return sorted(set(lines))


class TestClassGuard(unittest.TestCase):
    """The test class (#685 fixed names in a shared output directory, the evals slot that a word
    containing its stem filled, #659 an outcome asserted without the fixture's condition): a verdict
    that rests on something the test does not state. Two of its forms are mechanical and are
    checked here over every test module and every grader. The third, #659's, is not: whether a
    test asserts the condition its fixture's outcome rests on (an alignment of 0 s, a loudness range
    clear of 0) is a fact about FFmpeg and the fixture, not about the code's shape, so no scan finds
    it; #786 stays open for it, and each such test states its condition (test_multicam_switch_energy_
    picks_the_loudest_camera, test_loudness_keeps_each_sound_where_its_picture_is)."""

    def test_no_test_writes_a_fixed_name_into_a_shared_directory(self):
        """#685: every tests/test_*.py, parsed. A test method or setUp that writes a name it wrote
        down into SHARED_OUT, tests/out, $OUT, the system temp directory or a module-level directory
        made from one of them (or from OUT at import) fails: a -k run across modules, a repeated run
        or another test sees that file. OUT, OUT.sub(...), out_path(), out_dir() and tempfile's own
        directories are per test and pass."""
        found = [h for p in sorted((ROOT / "tests").glob("test_*.py")) for h in shared_writes(p)]
        self.assertEqual([h for h in found if h.split(" (line")[0] not in SHARED_WRITE_BY_DESIGN], [],
                         "write these through OUT / out_path() (one directory per test) or a TemporaryDirectory")
        stale = [k for k in SHARED_WRITE_BY_DESIGN if not any(h.startswith(k) for h in found)]
        self.assertEqual(stale, [], "allowed shared writes that no test makes any more")

    def test_the_shared_write_scan_sees_the_685_forms(self):
        """The scan's own control: #685's two forms, the old module-level DIR = OUT / "cut_copy"
        and the old module's own OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out")), and the
        cache form SHARED_OUT / name, are found; the per-test forms are not."""
        old = ('import os\nfrom pathlib import Path\nfrom _fixtures import OUT, SHARED_OUT\nROOT = Path(".")\n'
               'MINE = Path(os.environ.get("OUT", ROOT / "tests" / "out"))\nDIR = OUT / "cut_copy"\nNEW = OUT.sub("cut_copy")\n'
               'class T:\n    def test_a(self):\n        out = DIR / "copy_4.3.mp4"\n        cut_json(self.src, "-o", out)\n'
               '        (MINE / "c_identity.cube").write_text("x")\n        s = SHARED_OUT / "c_source601.mp4"\n'
               '        ffmpeg("-i", self.src, "-c:v", "libx264", s)\n        t = Path(tempfile.gettempdir()) / f"{self.id()}.json"\n'
               '        t.write_text("{}")\n'
               '    def test_b(self):\n        cut_json(self.src, "-o", NEW / "a.mp4")\n        (OUT / "b.txt").write_text("x")\n'
               '        (SHARED_OUT / "source.mp4").exists()\n        ffmpeg("-i", SHARED_OUT / "source.mp4", OUT / "c.mp4")\n')
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test_old.py"
            f.write_text(old, encoding="utf-8")
            found = shared_writes(f)
        self.assertEqual([h.split(" (line")[0] for h in found],
                         ["test_old.py:test_a: MINE / 'c_identity.cube'", "test_old.py:test_a: out",
                          "test_old.py:test_a: s", "test_old.py:test_a: t"], found)

    def test_no_grader_fills_a_slot_with_a_word_that_contains_its_stem(self):
        """The evals slot form: evals/run.py filled `cut` from "execute". Every grader in evals/
        that reads a prompt's `expect` decides each slot with run._slot_hit and tests no alternative
        with `in` by hand; and for every slot of every corpus, _slot_hit, run.score and
        grade_runs_25.grade leave it unfilled by its stem in prose, in a longer word, in another
        file of the same stem, in another case or as a longer flag, and fill it with the call."""
        sys.path.insert(0, str(ROOT / "evals"))
        try:
            run = importlib.import_module("run")
            g25 = importlib.import_module("grade_runs_25")
        finally:
            sys.path.remove(str(ROOT / "evals"))
        bypass = {}
        for p in sorted((ROOT / "evals").rglob("*.py")):
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
            reads_expect = any(isinstance(n, ast.Constant) and n.value == "expect" for n in ast.walk(tree))
            if reads_expect and p.name != "run.py" and "_slot_hit" not in src:
                bypass[p.name] = "reads expect without run._slot_hit"
            if _hand_rolled_slot_tests(tree):
                bypass[p.name] = f"tests a slot alternative with `in` at lines {_hand_rolled_slot_tests(tree)}"
        self.assertEqual(bypass, {}, "a grader with its own slot matcher")
        slots = set()
        for f in sorted((ROOT / "evals").glob("*.json")):
            raw = json.loads(f.read_text(encoding="utf-8"))
            items = raw.get("tasks", []) if isinstance(raw, dict) else raw
            slots |= {e for t in items if isinstance(t, dict) for e in (t.get("expect") or []) if isinstance(e, str)}
        self.assertGreater(len(slots), 40, "the corpora's slots were read")
        filled, missed = {}, {}
        with tempfile.TemporaryDirectory() as tmp:
            for i, slot in enumerate(sorted(slots)):
                neg, pos = _slot_negatives(slot)
                for text in neg:
                    d = Path(tmp) / f"n{i}"
                    d.mkdir(exist_ok=True)
                    (d / "transcript.txt").write_text(text + "\n\n## Report\nDone: out.mp4\n", encoding="utf-8")
                    verdicts = {"_slot_hit": run._slot_hit(slot, text), "score": run.score(text, {"expect": [slot]})[0],
                                "grade_runs_25": g25.grade({"id": "n", "expect": [slot]}, d)["verdict"] == "pass"}
                    if any(verdicts.values()):
                        filled.setdefault(slot, []).append((text, [k for k, v in verdicts.items() if v]))
                for text in pos:
                    d = Path(tmp) / f"p{i}"
                    d.mkdir(exist_ok=True)
                    (d / "transcript.txt").write_text(text + "\n\n## Report\nDone: out.mp4\n", encoding="utf-8")
                    # grade_runs_25 reads commands only (`$ ` lines); an MCP tool name is not one there
                    if not run._slot_hit(slot, text) or (text.startswith("$ ") and g25.grade({"id": "p", "expect": [slot]}, d)["verdict"] != "pass"):
                        missed.setdefault(slot, []).append(text)
        self.assertEqual(filled, {}, "slots a text that calls none of their scripts fills")
        self.assertEqual(missed, {}, "slots the call itself does not fill (the negatives above would prove nothing)")


class GuardRegistryTests(unittest.TestCase):
    def test_every_class_with_three_entries_has_a_guard_or_a_pending_issue(self):
        """A class the ledger records three times is registered in docs/defect-guards.json, with
        the test that guards it or the issue where the guard is still to be written; a registered
        test exists. A new class that reaches three fails this until it is registered."""
        guards = json.loads((ROOT / "docs" / "defect-guards.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("defect_ledger", ROOT / ".github" / "scripts" / "defect_ledger.py")
        ledger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ledger)
        rows = ledger.rows(ROOT)
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
