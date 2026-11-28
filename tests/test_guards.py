#!/usr/bin/env python3
"""Class guards: one test per kind of defect the ledger keeps recording, run over every tool.

docs/defect-guards.json names, for each class of docs/defect-ledger.jsonl with three or more
entries, the test here that catches the class wherever it happens: in the tools that exist and in
one written after the test. A fix of a class whose guard is pending does not pass revert_proof.py,
so a fix of one tool cannot be the end of a class that keeps coming back.
"""
import importlib.util
import json
import os
import re
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

    def test_a_late_sounds_place_is_the_same_in_every_sound_only_read(self):
        """#787's class on a sound-only read: the demuxer rewrites an MPEG-TS/PS timeline to start
        at the earliest stream it reads, so every read of a file's sound without its picture counted
        from the sound's own first sample. The guard remuxes a take whose sound starts 0.3 s late to
        .ts and fails wherever a tool reads that sound elsewhere than the .mp4 does: the sweep rows
        of the tools that read sound only, and sync.py --replace-audio's written sound."""
        from _fixtures import make_tones_take, sh
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = make_tones_take(Path(tmp) / "late.mp4", start=0.0, audio_late=0.3, dur=7)
            ts = Path(tmp) / "late.ts"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4), "-c", "copy", "-f", "mpegts", str(ts))
            differs = {}
            a, b = sweep.facts_for(str(mp4), tmp), sweep.facts_for(str(ts), tmp)
            for tool in ("silence", "scenes", "waveform", "cut", "loop", "caption"):
                if tool not in sweep.TABLE:
                    continue
                rm, rt = sweep.row_for(tool, str(mp4), a, tmp), sweep.row_for(tool, str(ts), b, tmp)
                if {k: v for k, v in rm.items() if k not in ("tool",)} != {k: v for k, v in rt.items() if k not in ("tool",)}:
                    differs[tool] = (rm, rt)
            ref = make_tones_take(Path(tmp) / "ref.mp4", dur=8)
            out = Path(tmp) / "replaced.mp4"
            sh(sys.executable, str(ROOT / "scripts" / "sync.py"), str(ref), str(ts), "--replace-audio", "-o", str(out))
            again = json.loads(sh(sys.executable, str(ROOT / "scripts" / "sync.py"), str(ref), str(out), "--json").stdout)
            if abs(again["offset_seconds"]) > 0.01:
                differs["sync --replace-audio"] = again["offset_seconds"]
            # -copyts is global and -ss preserves timestamps: a .ts reference kept its picture at
            # 1.467 s beside a sound at 0, and a trim of the second's head was padded back
            rstart = json.loads(sh("ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "json", str(ts)).stdout)["format"]["start_time"]
            out2 = Path(tmp) / "replaced_ts_ref.mp4"
            sh(sys.executable, str(ROOT / "scripts" / "sync.py"), str(ts), str(Path(tmp) / "late.mp4"), "--replace-audio", "-o", str(out2))
            starts = json.loads(sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json", str(out2)).stdout)["streams"]
            got = {s["codec_type"]: float(s.get("start_time") or 0) for s in starts}
            if got.get("video") != 0.0 or got.get("audio") != 0.0:
                differs["sync --replace-audio (ts reference)"] = (rstart, got)
            late2 = make_tones_take(Path(tmp) / "early.mp4", start=2.0, dur=8)
            out3 = Path(tmp) / "trimmed.mp4"
            sh(sys.executable, str(ROOT / "scripts" / "sync.py"), str(late2), str(Path(tmp) / "late.mp4"), "--replace-audio", "-o", str(out3))
            measured = json.loads(sh(sys.executable, str(ROOT / "scripts" / "sync.py"), str(late2), str(out3), "--json").stdout)
            if abs(measured["offset_seconds"]) > 0.01:
                differs["sync --replace-audio (trimmed head)"] = measured["offset_seconds"]
            self.assertEqual(differs, {}, "these sound-only reads counted the .ts from its sound's first sample")

    def test_a_sound_read_alone_counts_from_the_files_start(self):
        """#787's render half, beside the reads above: a sound-only render of an MPEG-TS/PS (and
        check.py's dropout pass) counted from the sound's own first sample, so a .wav cut, levelled
        or mixed from a .ts lost the sound's lead, and silence.py cut a plan made on the file's
        clock on the sound's. The same content as .ts and .mp4, its sound 0.28 s after its picture:
        every sound-only render puts its first burst, and check.py its dropout, at the same time."""
        def first_burst(path):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                                  "-f", "s16le", "-"], capture_output=True).stdout
            return next((i / 8000 for i in range(len(raw) // 2) if abs(int.from_bytes(raw[2 * i:2 * i + 2], "little", signed=True)) > 1600), None)
        with tempfile.TemporaryDirectory() as tmp:
            read = {}
            for ext in ("mp4", "ts"):
                src = Path(tmp) / f"late.{ext}"
                # bursts at 1.0-1.2 and 2.0-2.7 s on the file's clock: the 0.8 s between is a dropout
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=4",
                                "-itsoffset", "0.3", "-f", "lavfi", "-i",
                                "aevalsrc='if(between(t+0.3,1,1.2)+between(t+0.3,2,2.7),0.8*sin(2*PI*1000*t),0)':s=48000:d=3.7",
                                "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                str(src)], check=True)
                tool = lambda name, *a: sweep.run_json([sys.executable, str(ROOT / "scripts" / f"{name}.py"), str(src), *a, "--json"])[0] or {}
                dropouts = [c.get("value") for c in tool("check", "--content").get("checks", []) if c.get("check") == "dropouts"]
                got = {"check --content: dropouts": [re.sub(r"\(\d+ ms\)", "", v or "") for v in dropouts]}
                for name, argv in (("cut", ["--start", "0.5", "--end", "3"]), ("loudness", []), ("audio", ["--gain", "0"]), ("silence", [])):
                    out = Path(tmp) / f"{name}_{ext}.wav"
                    tool(name, *argv, "-o", str(out))
                    got[f"{name} -o .wav: first burst"] = round(first_burst(out), 2) if out.exists() else "not written"
                read[ext] = got
            self.assertEqual(read["mp4"]["check --content: dropouts"], ["1: 1.20s "], "the fixture has its dropout")
            differ = {k: (v, read["ts"][k]) for k, v in read["mp4"].items()
                      if json.dumps(v) != json.dumps(read["ts"][k]) and not (isinstance(v, (int, float)) and abs(v - read["ts"][k]) <= 0.01)}
            self.assertEqual(differ, {}, "these rendered or read the sound of a .ts on another clock than the .mp4's (mp4, ts)")

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


class IgnoredFlagGuard(unittest.TestCase):
    """ignored_flag (waveform.py --at's video flags, freeze.py --time read as --timeout, #749): a
    flag is taken and does nothing. This catches the part of the class that the parser and the code
    show by themselves, on every tool and on one written after this test: an option declared and
    never read, unless contract --json `deprecated` lists it, which says it goes. A flag that one
    mode of a tool ignores while another reads it is not seen here."""

    # A dest nothing reads by name, kept on purpose: `--keep-hevc` is the 3.0.0 default, accepted so
    # a 2.x command line runs unchanged (docs/design-decisions.md), and argparse refuses it beside
    # `--no-keep-hevc`.
    UNREAD_BY_DESIGN = {("cut", "keep_hevc")}

    def test_every_declared_option_of_every_tool_is_read(self):
        """#749: overlay.py declared --emoji-assets, --emoji-scale and --emoji-max and never read
        them, so a caller's value was accepted and did nothing. Every dest of every tool's parser is
        read: as `<name>.<dest>` or a "<dest>" string in the tool, or as `args.<dest>` /
        `getattr(args, "<dest>")` in the shared modules the tools hand their args to. An option
        `_contract.DEPRECATED` lists ("<tool>.py --flag", where cli) is known: it still has to go."""
        import argparse
        import re
        scripts = ROOT / "scripts"
        sys.path.insert(0, str(scripts))
        import _contract
        shared = "\n".join(p.read_text(encoding="utf-8") for p in sorted(scripts.glob("_*.py")) + sorted((scripts / "_common").glob("*.py"))
                           if p.name != "_contract.py")
        deprecated = {d["what"] for d in _contract.DEPRECATED if d["where"] == "cli"}
        unread = []
        for tool in sorted(scripts.glob("[!_]*.py")):
            src = tool.read_text(encoding="utf-8")
            if tool.stem in _contract.ALIASES:  # an alias hands its args to the tool it names (crop.py -> fit.crop_rect)
                src += (scripts / f"{_contract.ALIASES[tool.stem]}.py").read_text(encoding="utf-8")
            for action in _contract._capture_parser(tool)._actions:
                if isinstance(action, argparse._HelpAction) or (tool.stem, action.dest) in self.UNREAD_BY_DESIGN \
                        or any(f"{tool.name} {o}" in deprecated for o in action.option_strings):
                    continue
                d = re.escape(action.dest)
                if not (re.search(rf"\b\w+\.{d}\b|[\"']{d}[\"']", src)
                        or re.search(rf"\bargs\.{d}\b|getattr\(\s*args\s*,\s*[\"']{d}[\"']", shared)):
                    unread.append(f"{tool.stem}: {'/'.join(action.option_strings) or action.dest}")
        self.assertEqual(unread, [], "options declared and never read")


class NumericGuard(unittest.TestCase):
    """numeric (#749, #645, #630): a number an option cannot take was taken and read as another
    one. Every numeric option of every tool in the sweep's table is given, in a dry run, the value
    just past each end of the range its help states (a..b, or 0 for "> 0") and 1000000000; each
    must be refused before anything is planned: by the shared step, which names the option, or by
    argparse where the option has choices."""

    def test_no_tool_takes_a_number_outside_the_range_its_help_states(self):
        import edge_values
        clip = str(ROOT / "demos" / "footage" / "veo_sea.mp4")
        taken = {}
        with tempfile.TemporaryDirectory() as tmp:
            facts = sweep.facts_for(clip, tmp)
            by_tool = edge_values.options()
            for entry, (base, ext) in sweep.TABLE.items():
                tool = entry.split()[0]
                if " " in entry:
                    continue
                out = ["-o", str(Path(tmp) / f"edge{ext}")] if ext else []
                for flag, text in by_tool.get(tool, {}).items():
                    span = re.search(r"(-?\d+(?:\.\d+)?)\.\.(-?\d+(?:\.\d+)?)|> 0\b", text)
                    values = ([] if flag == "--length-samples" else ["1000000000"]) + (
                        ["0"] if span and span[0] == "> 0" else [f"{float(span[1]) - 1:g}", f"{float(span[2]) + 1:g}"] if span else [])
                    for value in values:
                        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{tool}.py"), clip, *[a.format(**facts) for a in base],
                                               f"{flag}={value}", *out, "--dry-run", "--overwrite"], capture_output=True, text=True,
                                              encoding="utf-8", errors="replace", timeout=60)
                        if proc.returncode == 0 or not (f"{flag} {float(value):g} is outside what this option takes" in proc.stderr or "invalid choice" in proc.stderr):
                            taken[f"{tool} {flag}={value}"] = next((l for l in proc.stderr.splitlines() if l.startswith("error:")), "ran")[:160]
        self.assertEqual(taken, {})


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
