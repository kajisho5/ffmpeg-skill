#!/usr/bin/env python3
"""End-to-end tests for render, batch and multicam, plus the toolkit-wide invariants every script has to satisfy.

    python3 tests/test_orchestration.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import contextlib
import importlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, ROOT, SCRIPTS, TONES, _no_fontconfig, script, sh, tiny_clip  # noqa: E402
from _common import font_for_script, probe, shell_quote  # noqa: E402


class OrchestrationTests(MediaFixtures):
    """Render, batch and multicam, plus the toolkit-wide invariants every script has to satisfy."""

    def test_the_review_page_shows_the_plan_and_the_result_and_saves_an_edited_project(self):
        """#633, 4.0.0: scripts/_review.py writes a folder with an index.html for a render project:
        stills at each clip's in point, middle and out point, the dry run's stages, the measured
        result of a run, and fields whose edited project the page saves. Standalone use only: it
        is not a contract tool and the MCP server does not list it, so a caller that owns the
        review (Velisa) never reaches it."""
        work = OUT / "review_page"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        tiny_clip(work / "src.mp4", "testsrc2=s=320x180:r=30", seconds=6, audio=True)
        proj = work / "proj.json"
        proj.write_text(json.dumps({"output": "out.mp4", "clips": [{"src": "src.mp4", "in": 1, "out": 3}, {"src": "src.mp4", "in": 4}]}),
                        encoding="utf-8")
        run = json.loads(sh(sys.executable, SCRIPTS / "render.py", proj, "--json", "--overwrite", cwd=work).stdout)
        (work / "run.json").write_text(json.dumps(run), encoding="utf-8")
        page_path = Path(sh(sys.executable, SCRIPTS / "_review.py", proj, "--result", work / "run.json").stdout.strip())
        self.assertEqual(page_path, work / "proj.review" / "index.html")
        def embedded(path):  # the one document the page is built from
            text = Path(path).read_text(encoding="utf-8")
            return text, json.loads(re.search(r'<script id="data">window\.REVIEW_DATA = (.*?);</script>', text, re.S).group(1))
        page, data = embedded(page_path)
        stills = sorted(p.name for p in (page_path.parent / "stills").glob("*.jpg"))
        self.assertEqual([n for n in stills if n.startswith("clip")], [f"clip{i}_{k}.jpg" for i in range(2) for k in range(3)])
        self.assertEqual(len([n for n in stills if n.startswith("out_")]), 6, stills)
        self.assertEqual(data["stages"], ["clips", "join"], "the dry run ran even though out.mp4 is already there")
        self.assertEqual(data["result"]["probe"]["duration"], run["probe"]["duration"])
        self.assertEqual([(c["s"], c["a"]) for c in data["clips"]], [(0, 1.0), (0, 4.0)])
        self.assertEqual(data["clips"][0]["b"], 3.0)
        self.assertAlmostEqual(data["clips"][1]["b"], 6.0, delta=0.2, msg="a clip with no out ends where its source does")
        self.assertEqual(data["clips"][0]["stills"], [f"stills/clip0_{k}.jpg" for k in range(3)])
        self.assertEqual([s["path"] for s in data["sources"]], ["src.mp4"], "one card per file, however many clips use it")
        self.assertEqual({s["codec_type"] for s in data["sources"][0]["probe"]["streams"]}, {"video", "audio"})
        self.assertEqual((data["cue_file"], data["cues"]), (None, []), "a project with no cue file has no caption track")
        # the output plays from where it is, and its sound is drawn from the file, not invented
        self.assertEqual(data["out"]["video"], (work / "out.mp4").resolve().as_uri())
        self.assertEqual(data["out"]["wave"], "stills/wave.png")
        self.assertGreater((page_path.parent / "stills" / "wave.png").stat().st_size, 0)
        # every tool's flags come from the contract, never a list kept in the page
        contract = json.loads(sh(sys.executable, SCRIPTS / "_contract.py", "--json", "--static").stdout)
        self.assertEqual({n: t["p"] for n, t in data["tools"].items()}, {t["name"]: t["input_schema"]["properties"] for t in contract["tools"]})
        self.assertEqual(set(data["safe"]["reels"]), {"top", "bottom", "left", "right"})
        self.assertNotIn("/*DATA*/", page)
        self.assertNotIn('getElementById("data")', page, "the data is the script's own value, never text read back from the document")
        for needed in ('id="app"', "data-clip", "data-prompt", "navigator.clipboard"):  # the screen, the clip fields, the instruction
            self.assertIn(needed, page)
        self.assertNotRegex(page, r'(src|href)="https?://', "the page asks the network for nothing")
        # a cue file the project names is read into the caption track
        (work / "cues.srt").write_text("1\n00:00:00,500 --> 00:00:01,500\nhello <b>\n", encoding="utf-8")
        cued = work / "cued.json"
        cued.write_text(json.dumps({"output": "c.mp4", "clips": [{"src": "src.mp4"}], "captions": {"srt": "cues.srt"}}), encoding="utf-8")
        _, with_cues = embedded(sh(sys.executable, SCRIPTS / "_review.py", cued, "-o", work / "cued_review").stdout.strip())
        self.assertEqual((with_cues["cue_file"], with_cues["cues"]), ("cues.srt", [[0.5, 1.5, "hello <b>"]]))
        self.assertEqual(with_cues["result"], None)
        self.assertEqual(with_cues["out"], {"video": None, "stills": [], "wave": None}, "not rendered: nothing to play, and it says so")
        # a second page into the same folder is refused unless --overwrite
        again = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj)], capture_output=True, text=True, cwd=str(work))
        self.assertEqual(again.returncode, 1, again.stderr)
        self.assertIn("--overwrite", again.stderr)
        # check rows show their status and value; a run with no probe has sound "not measured"
        failed = {"status": "failed", "verified": False, "check": {"ok": False, "checks": [
            {"check": "loudness", "status": "FAIL", "value": "-30.1 LUFS", "expected": "-14 LUFS"},
            {"check": "codec", "status": "PASS", "value": "h264", "expected": "h264"}]}}
        (work / "failed.json").write_text(json.dumps(failed), encoding="utf-8")
        sh(sys.executable, SCRIPTS / "_review.py", proj, "--result", work / "failed.json", "-o", work / "failed_review")
        page, data = embedded(work / "failed_review" / "index.html")
        self.assertEqual(data["result"], failed, "the run's document as it is: the page marks a missing probe as not measured")
        self.assertEqual(data["out"], {"video": None, "stills": [], "wave": None})
        self.assertIn('"output probe"', page)
        # review of #636: the render command runs from anywhere and is quoted; a folder of other
        # files is not a review folder; a null bound is an empty field
        self.assertIn(str(SCRIPTS / "render.py"), data["run"])
        self.assertIn(str(proj), data["run"])
        media = work / "media"
        media.mkdir(exist_ok=True)
        (media / "clip0_0.jpg").write_bytes(b"not ours")
        refused = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj), "-o", str(media)],
                                 capture_output=True, text=True, cwd=str(work))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertEqual((media / "clip0_0.jpg").read_bytes(), b"not ours")
        nulls = work / "nulls.json"
        nulls.write_text(json.dumps({"output": "n.mp4", "clips": [{"src": "src.mp4", "in": None, "out": None}]}), encoding="utf-8")
        sh(sys.executable, SCRIPTS / "_review.py", nulls, "-o", work / "nulls_review")
        _, data = embedded(work / "nulls_review" / "index.html")
        self.assertEqual(data["project"]["clips"][0], {"src": "src.mp4", "in": None, "out": None}, "null stays null, never the word None")
        self.assertEqual(data["clips"][0]["a"], 0.0)
        self.assertAlmostEqual(data["clips"][0]["b"], 6.0, delta=0.2)
        # an existing review folder that also holds a project input: the input is never touched,
        # and a stills folder the tool did not make is refused (review of #636)
        reused = work / "reused"
        reused.mkdir(exist_ok=True)
        (reused / "index.html").write_text("old", encoding="utf-8")
        (reused / "clip0_0.jpg").write_bytes(b"overlay")
        overlaid = work / "overlaid.json"
        overlaid.write_text(json.dumps({"output": "o.mp4", "clips": [{"src": "src.mp4"}],
                                        "overlays": [{"image": str(reused / "clip0_0.jpg")}]}), encoding="utf-8")
        sh(sys.executable, SCRIPTS / "_review.py", overlaid, "-o", reused, "--overwrite")
        self.assertEqual((reused / "clip0_0.jpg").read_bytes(), b"overlay")
        self.assertTrue((reused / "stills" / "clip0_0.jpg").stat().st_size > 0)
        foreign = work / "foreign"
        (foreign / "stills").mkdir(parents=True, exist_ok=True)
        (foreign / "index.html").write_text("old", encoding="utf-8")
        (foreign / "stills" / "mine.jpg").write_bytes(b"keep")
        refused = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj), "-o", str(foreign), "--overwrite"],
                                 capture_output=True, text=True, cwd=str(work))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertEqual((foreign / "stills" / "mine.jpg").read_bytes(), b"keep")
        # the documents this run reads, kept in a marked stills folder, are inputs too; and only
        # this tool's own stills are ever removed from it (review of #636)
        marked = reused / "stills"
        kept_json = marked / "run.json"
        kept_json.write_text(json.dumps({"status": "completed", "output": "out.mp4"}), encoding="utf-8")
        (marked / "notes.txt").write_text("mine", encoding="utf-8")
        again = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(overlaid), "--result", str(kept_json),
                                "-o", str(reused), "--overwrite"], capture_output=True, text=True, cwd="/")
        self.assertEqual(again.returncode, 1, again.stderr)
        self.assertTrue(kept_json.exists())
        kept_json.unlink()
        sh(sys.executable, SCRIPTS / "_review.py", overlaid, "-o", reused, "--overwrite")
        self.assertEqual((marked / "notes.txt").read_text(encoding="utf-8"), "mine")
        # a relative output is read from the project's folder, wherever the page is built from
        rel = work / "rel.json"
        rel.write_text(json.dumps({"status": "completed", "output": "out.mp4", "probe": run["probe"]}), encoding="utf-8")
        subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj), "--result", str(rel), "-o",
                        str(work / "rel_review")], check=True, capture_output=True, text=True, cwd="/")
        self.assertTrue((work / "rel_review" / "stills" / "out_0.jpg").exists())
        # literal text longer than a file name may be is not a path; a project named index.html
        # in the review folder is never overwritten by the page (review of #636)
        long_text = work / "long.json"
        long_text.write_text(json.dumps({"output": "l.mp4", "clips": [{"src": "src.mp4"}],
                                         "overlays": [{"text": "x" * 300}]}), encoding="utf-8")
        sh(sys.executable, SCRIPTS / "_review.py", long_text, "-o", work / "long_review")
        self.assertTrue((work / "long_review" / "index.html").exists())
        inside = work / "inside"
        inside.mkdir(exist_ok=True)
        as_page = inside / "index.html"
        as_page.write_text(json.dumps({"output": "o.mp4", "clips": [{"src": str(work / "src.mp4")}]}), encoding="utf-8")
        before = as_page.read_bytes()
        refused = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(as_page), "-o", str(inside), "--overwrite"],
                                 capture_output=True, text=True, cwd=str(work))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertEqual(as_page.read_bytes(), before)
        # a marker or a page name that links to an input is replaced as a name, never written
        # through: the input keeps its bytes (review of #636)
        linked = work / "linked"
        (linked / "stills").mkdir(parents=True, exist_ok=True)
        (linked / "index.html").write_text("<html>earlier page</html>", encoding="utf-8")  # so the marker check is reached
        precious = work / "precious.txt"
        precious.write_text("keep me", encoding="utf-8")
        try:  # a Windows runner without symlink rights cannot make one: that half is skipped there
            (linked / "stills" / ".ffmpeg-skill-review-stills").symlink_to(precious)
        except OSError:
            pass
        else:
            refused = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj), "-o", str(linked),
                                      "--overwrite"], capture_output=True, text=True, cwd=str(work))
            self.assertEqual(refused.returncode, 1, refused.stderr)
            self.assertIn("was not made by the review page", refused.stderr)
            self.assertEqual(precious.read_text(encoding="utf-8"), "keep me")
            # a link already standing at the temporary name the page used to be written through
            # is not followed: the temporary file is created exclusively
            if str(SCRIPTS) not in sys.path:
                sys.path.insert(0, str(SCRIPTS))
            review = importlib.import_module("_review")
            target = linked / "page.html"
            (linked / f".page.html.{os.getpid()}.tmp").symlink_to(precious)
            review.write_new(target, "new page")
            self.assertEqual(precious.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(target.read_text(encoding="utf-8"), "new page")
        hard = work / "hard"
        hard.mkdir(exist_ok=True)
        os.link(precious, hard / "index.html")
        sh(sys.executable, SCRIPTS / "_review.py", proj, "-o", hard, "--overwrite")
        self.assertEqual(precious.read_text(encoding="utf-8"), "keep me")
        self.assertIn("<html", (hard / "index.html").read_text(encoding="utf-8"))
        if os.name == "posix":  # the page is as readable as any file, not owner-only like a temporary file
            self.assertEqual((hard / "index.html").stat().st_mode & 0o044, 0o044)
        # a page name hard-linked to an input of this run is that input under another name:
        # refused by file identity, and the input keeps its bytes (review of #636)
        as_input = work / "as_input"
        as_input.mkdir(exist_ok=True)
        os.link(proj, as_input / "index.html")
        kept = Path(proj).read_bytes()
        refused = subprocess.run([sys.executable, str(SCRIPTS / "_review.py"), str(proj), "-o", str(as_input), "--overwrite"],
                                 capture_output=True, text=True, cwd=str(work))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("is an input of this run", refused.stderr)
        self.assertEqual(Path(proj).read_bytes(), kept)
        # the project the page embeds is the project as given, and </script> in it cannot end the script
        hostile = work / "hostile.json"
        hostile.write_text(json.dumps({"output": "o.mp4", "clips": [{"src": "a</script><b>.mp4"}]}), encoding="utf-8")
        sh(sys.executable, SCRIPTS / "_review.py", hostile, "-o", work / "hostile_review")
        page, data = embedded(work / "hostile_review" / "index.html")
        self.assertNotIn("</script><b>", page)
        self.assertNotIn("<b>.mp4", page, "no < of the data reaches the HTML parser")
        self.assertEqual(data["project"]["clips"][0]["src"], "a</script><b>.mp4")
        # standalone only: not a contract tool, not on the MCP server, reached through npx review
        self.assertNotIn("_review", [t["name"] for t in contract["tools"]])
        self.assertNotIn("_review", (ROOT / "mcp" / "server.py").read_text(encoding="utf-8"))
        self.assertIn("args[0] === 'review'", (ROOT / "bin" / "install.js").read_text(encoding="utf-8"))
        self.assertIn("scripts/_review.py", (ROOT / "SKILL.md").read_text(encoding="utf-8"))

    # ------------------------------------------- 1.17: a project may ask for beat-snapped clips
    def test_render_forwards_snap_to_the_clip_cut(self):
        proj = OUT / "snap_project.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "snap_render.mp4"),
            "snap": {"to": "beats", "tolerance": 0.12, "min_confidence": 0.5},
            "clips": [{"src": str(self._beats()), "in": "2.03", "out": "6.01"}],
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--json").stdout)
        self.assertEqual(data["snap"]["mode"], "beats")
        self.assertEqual(data["snap"]["snapped"], 2)
        self.assertIn("clips", data["stages"])

    def test_render_snap_covers_every_clip_and_survives_a_cache_hit(self):
        """Only the first clip's moves were reported, and a cached clips stage reported
        snap: null although the clips had been snapped."""
        cdir = OUT / "rcache_snap"
        shutil.rmtree(cdir, ignore_errors=True)
        proj = OUT / "snap_multi.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "snap_multi.mp4"),
            "snap": {"to": "beats", "tolerance": 0.12},
            "clips": [{"src": str(self._beats()), "in": "2.03", "out": "5.01"},
                      {"src": str(self._beats()), "in": "6.03", "out": "9.01"}],
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertEqual(len(data["snap"]["clips"]), 2)
        self.assertEqual([c["clip"] for c in data["snap"]["clips"]], [0, 1])
        self.assertTrue(all(c["snapped"] for c in data["snap"]["clips"]))
        self.assertEqual(data["snap"]["mode"], "beats")     # the shape a caller reads today
        # second run: the clips come from the cache, and the report must not claim they were
        # never snapped
        again = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertIn("clips", again["cache"]["hits"])
        self.assertIsNotNone(again["snap"])
        self.assertEqual(len(again["snap"]["clips"]), 2)
        self.assertEqual(again["snap"]["clips"][0]["source"], "cache")

    def test_render_without_snap_builds_the_same_command_as_before(self):
        proj = OUT / "nosnap_project.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "nosnap_render.mp4"),
            "clips": [{"src": str(self._beats()), "in": "2.03", "out": "6.01"}],
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        self.assertIsNone(data.get("snap"))
        self.assertFalse(any("--snap" in c for c in data["commands"]))

    def test_render_dry_run_joins_a_trimmed_and_an_untrimmed_audio_clip(self):
        """A trimmed clip is a cut the dry run never wrote, so join.py saw its probe stub (which
        always has a video stream) next to the untrimmed, audio-only clip and refused the plan as
        an audio/video mix. The join is planned as audio, from the clip that exists."""
        proj = OUT / "render_pending_audio.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "render_pending_audio.wav"),
            "transition": {"type": "none"},
            "clips": [{"src": str(self.mic), "in": "0.5", "out": "2"}, {"src": str(self.mic)}],
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        self.assertEqual((data["status"], data["dry_run"], data["stages"]), ("completed", True, ["clips", "join"]))
        join_cmd = [c for c in data["commands"] if "concat=n=2:v=0:a=1" in c]
        self.assertEqual(len(join_cmd), 1, data["commands"])
        self.assertNotIn("libx264", join_cmd[0])
        self.assertTrue(any("clip00.wav does not exist yet" in c for c in data["commands"]), data["commands"])
        # a trimmed video clip (clip00.mp4, pending) next to an untrimmed .wav is the audio/video
        # mix the real run refuses: the plan refuses it too, for that reason, not as an audio join
        # that cannot fill render's joined.mp4
        proj = OUT / "render_pending_mix.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "render_pending_mix.mp4"),
            "transition": {"type": "none"},
            "clips": [{"src": str(self.src), "in": "0.5", "out": "2"}, {"src": str(self.mic)}],
        }), encoding="utf-8")
        err = json.loads(script("render.py", proj, "--dry-run", "--json", expect_fail=True).stdout)["error"]
        self.assertIn(f"{self.mic} has no video stream while ", err["message"])
        self.assertIn("clip00.mp4, which does not exist yet, is expected to have one", err["message"])
        self.assertNotIn("give -o an audio extension", err["message"])


    def test_zero_or_negative_fps_refused_across_every_cfr_script(self):
        """--fps flows straight into cfr_args(meta, args.fps) / a `fps or source_fps or 30.0`
        fallback in several scripts without ever being validated first. `0` is falsy in Python, so
        `--fps 0` used to be silently discarded and fall back to the source's own fps (or 30) --
        the tool claims to force a specific constant frame rate and quietly does something else
        instead. A negative value is truthy, so `--fps -5` passed straight through to ffmpeg's
        `-r`/`fps=` filter option, which rejects it -- an unhelpful ffmpeg-level crash instead of a
        clear error naming --fps. Verify every affected script now refuses both up front."""
        for name, extra in (
            ("crop.py", ["--x", "0", "--y", "0", "--width", "32", "--height", "32"]),
            ("denoise.py", []),
            ("redact.py", ["--x", "0", "--y", "0", "--width", "32", "--height", "32"]),
            ("straighten.py", ["--degrees", "3"]),
            ("sphere.py", []),
            ("join.py", []),  # fps is validated before the "give >= 2 clips" check, one input is enough
            ("multicam.py", []),  # fps is validated before the "give >= 2 inputs" check too
        ):
            for bad in ("0", "-5"):
                proc = script(name, self.src, *extra, "--fps", bad, expect_fail=True)
                self.assertIn("--fps", proc.stderr, f"{name} --fps {bad} should name --fps in its error")

    def test_a_brand_file_without_a_font_does_not_switch_font_by_script_off(self):
        """BRAND_DEFAULTS always supplies a font, so the merged brand document cannot say whether
        the CALLER chose one: a brand.json that only sets colours must still resolve a font by
        script (and still refuse when nothing covers it)."""
        if _no_fontconfig():
            self.skipTest("no fc-list on this machine")
        if font_for_script("ko") is None:
            self.skipTest("this machine has no font covering ko")
        brand = OUT / "brand_no_font.json"
        brand.write_text(json.dumps({"colors": {"text": "FFFFFF"}}), encoding="utf-8")
        cues = OUT / "brand_ko.txt"
        cues.write_text("0:00-0:03 안녕하세요\n", encoding="utf-8")
        proc = script("caption.py", self._small(), "--text", cues, "--brand", brand,
                      "--animate", "none", "--fast", "-o", OUT / "brand_ko.mp4")
        self.assertRegex(proc.stderr, r"(?m)^font: .+? \(covers ko\)")
        self.assertNotIn("does not cover", proc.stderr)
        stated = OUT / "brand_with_font.json"
        stated.write_text(json.dumps({"font": "DejaVu Sans"}), encoding="utf-8")
        proc2 = script("caption.py", self._small(), "--text", cues, "--brand", stated,
                       "--animate", "none", "--fast", "-o", OUT / "brand_ko2.mp4")
        if shutil.which("fc-list"):
            self.assertIn("does not cover", proc2.stderr, "a font the brand file itself states is kept")
        else:
            self.assertNotIn("does not cover", proc2.stderr, "no fontconfig: coverage is unknown, nothing is claimed")
        self.assertNotIn("(covers ko)", proc2.stderr)

    def test_render_audio_stems_and_chapters_stage(self):
        """1.13: stems are a vocabulary over the flags that already exist, and the chapters stage
        puts the markers in the file that ships (metadata.py, streams copied)."""
        proj = OUT / "project_stems.json"
        proj.write_text(json.dumps({
            "output": "render_stems.mp4",
            "clips": [{"src": "source.mp4"}],
            "audio": {"music": "lavmic.wav", "effects": "lavmic.wav", "duck": True, "voice": "light",
                      "stems": {"dialogue": -2, "music": -18, "effects": -24}},
            "export": {"preset": "youtube", "normalize": False},
            "chapters": [{"at": "0:00", "title": "Intro"}, {"at": 3, "title": "Body"}],
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        graph = next(c for c in data["commands"] if "sidechaingate" in c)
        self.assertIn("volume=-2dB", graph, "stems.dialogue is the main track's gain")
        self.assertIn("volume=-18dB", graph, "stems.music is the bed's level")
        self.assertIn("volume=-24dB", graph, "stems.effects is the effects bed's level")
        self.assertIn("highpass=f=80,acompressor=threshold=-18dB:ratio=2", graph, '"voice": "light" picks the light chain')
        # the chapters stage is planned like every other stage: the dry run names the same
        # metadata.py command against the same delivered file, and lists the stage. A plan that
        # hides a stage is a plan the user cannot approve.
        planned = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        real = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertIn("chapters", planned["stages"])
        self.assertEqual(planned["stages"], real["stages"], "the plan lists the stages the run does")
        for doc in (planned, real):
            chapter_cmds = [c for c in doc["commands"] if "-map_chapters 1" in c]
            self.assertEqual(len(chapter_cmds), 1, doc["stages"])
            self.assertIn(str(OUT / "render_stems.mp4"), chapter_cmds[0], "planned against the delivered file")
        data = real
        written = probe(str(OUT / "render_stems.mp4")).get("chapters") or []
        self.assertEqual([c["title"] for c in written], ["Intro", "Body"])
        self.assertClose(written[1]["start"], 3.0, 0.05)
        # a chapters file path works the same way
        proj2 = OUT / "project_chapters_file.json"
        (OUT / "render_chapters.txt").write_text("0:00 One\n0:05 Two\n", encoding="utf-8")
        proj2.write_text(json.dumps({
            "output": "render_chapters.mp4", "clips": [{"src": "source.mp4"}],
            "export": {"preset": "youtube", "normalize": False}, "chapters": "render_chapters.txt",
        }), encoding="utf-8")
        script("render.py", proj2, "--fast", "--json")
        self.assertEqual(len(probe(str(OUT / "render_chapters.mp4")).get("chapters") or []), 2)
        # a stems level with no effects file, and a misspelled stem, are refusals by name
        proj3 = OUT / "project_stems_bad.json"
        proj3.write_text(json.dumps({"output": "render_stems_bad.mp4", "clips": [{"src": "source.mp4"}],
                                     "audio": {"stems": {"effects": -20}}}), encoding="utf-8")
        doc = json.loads(script("render.py", proj3, "--dry-run", "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("effects", doc["error"]["message"])
        proj3.write_text(json.dumps({"output": "render_stems_bad.mp4", "clips": [{"src": "source.mp4"}],
                                     "audio": {"stems": {"voice": -20}}}), encoding="utf-8")
        doc = json.loads(script("render.py", proj3, "--dry-run", "--json", expect_fail=True).stdout)
        self.assertIn("dialogue", doc["error"]["message"], "the nearest valid stem is named")
        # a music level with no music file is refused the same way an effects level is
        proj3.write_text(json.dumps({"output": "render_stems_bad.mp4", "clips": [{"src": "source.mp4"}],
                                     "audio": {"stems": {"music": -18}}}), encoding="utf-8")
        doc = json.loads(script("render.py", proj3, "--dry-run", "--json", expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("music", doc["error"]["message"])

    def test_render_chapters_are_validated_before_any_stage_runs(self):
        """1.13: every other project error is raised before the first ffmpeg call. A bad chapter
        entry used to surface inside the last stage, after place_output had already delivered an
        unchaptered file and reported the render as done."""
        out = OUT / "render_bad_chapters.mp4"
        proj = OUT / "project_bad_chapters.json"
        for chapters, needle in (([{"title": "A"}], "at"), ([{"at": "0:00"}], "title"),
                                 ("no_such_chapters.txt", "not found")):
            if out.exists():
                out.unlink()
            proj.write_text(json.dumps({"output": "render_bad_chapters.mp4", "clips": [{"src": "source.mp4"}],
                                        "export": {"preset": "youtube", "normalize": False},
                                        "chapters": chapters}), encoding="utf-8")
            doc = json.loads(script("render.py", proj, "--fast", "--json", expect_fail=True).stdout)
            self.assertEqual(doc["error"]["kind"], "input", chapters)
            self.assertIn(needle, doc["error"]["message"], chapters)
            self.assertEqual(doc.get("commands") or [], [], "refused before the first ffmpeg call")
            self.assertFalse(out.exists(), "no half-done delivery is left behind")

    def test_shell_quote_quotes_backslashes(self):
        """CodeRabbit (#101): fixing the invalid-escape-sequence SyntaxWarning in shell_quote()'s
        character set (a stray `\\` before an already-unescaped `;`) accidentally dropped a real,
        load-bearing backslash from the quoting trigger set -- the original `\\;` literal, due to
        Python keeping an unrecognised escape's backslash, actually matched on `\\` OR `;`, not just
        `;`. Without a backslash trigger, a Windows path like `C:\\media\\clip.mp4` would render
        unquoted in --dry-run/--json command output. Assert the fixed version still quotes it."""
        self.assertEqual(shell_quote("C:\\media\\clip.mp4"), "'C:\\media\\clip.mp4'")
        self.assertEqual(shell_quote("plain.mp4"), "plain.mp4")
        self.assertEqual(shell_quote("has;semicolon"), "'has;semicolon'")

    def test_dry_run_and_json_on_every_script(self):
        cases = [
            ("cut.py", [self.src, "--start", "1", "--end", "3"]),
            ("fit.py", [self.src, "--duration", "6", "--method", "speed"]),
            ("caption.py", [self.src, "--srt", OUT / "cues.srt"]),
            ("overlay.py", [self.src, "--image", self.logo]),
            ("export.py", [self.src, "--preset", "x"]),
            ("color.py", [self.src, "--retag", "bt709"]),
            ("audio.py", [self.src, "--denoise"]),
            ("join.py", [self.src, self.src]),
        ]
        if not (OUT / "cues.srt").exists():
            script("caption.py", "--text", self.cues, "--write-srt", OUT / "cues.srt")
        for name, argv in cases:
            out = OUT / f"dry_{name}.mp4"
            proc = script(name, *argv, "-o", out, "--dry-run", "--json")
            self.assertFalse(out.exists(), f"{name} wrote a file in --dry-run")
            data = json.loads(proc.stdout)
            self.assertTrue(data["dry_run"], name)
            self.assertTrue(data["commands"] and all("ffmpeg" in c for c in data["commands"]), name)
            self.assertEqual(data["output"], str(out), name)
        # --json on a real run includes the probe of the output
        out = OUT / "json_cut.mp4"
        data = json.loads(script("cut.py", self.src, "--start", "0", "--end", "2", "-o", out, "--json").stdout)
        self.assertClose(data["probe"]["duration"], 2.0, 0.6)

    def test_grid_broll_and_multicam_end_their_sound_to_the_sample(self):
        """#493: grid.py, broll.py and multicam.py ended their sound with `atrim=duration={:.3f}` /
        `atrim=0:{:.3f}` and the output's `-t {:.3f}`, to the millisecond, as audio.py did before
        #478: a length of 59244 samples (48 kHz) was written as 59232. They share audio.py's
        conform (decision.conform_to_length) now. The count is of the written track's own samples:
        its packets' durations with the edit list ignored, less the encoder's 1024 of priming (an
        MP4 edit list is in 1/1000 s, so the stream's stated duration is a whole millisecond)."""
        burst = "0.4*sin(2*PI*440*t)*lt(mod(t\\,0.31)\\,0.1)"

        def clip(name, rate, samples, picture="testsrc"):
            path = OUT / name
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"{picture}=d=1:s=160x120:r=25",
               "-f", "lavfi", "-i", f"aevalsrc={burst}:s={rate}", "-af", f"atrim=end_sample={samples}",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", path)
            return path

        def track_samples(path):
            packets = json.loads(sh("ffprobe", "-v", "error", "-ignore_editlist", "1", "-select_streams", "a:0", "-show_entries",
                                    "packet=duration:packet_side_data=discard_padding", "-of", "json", path).stdout)["packets"]
            # the end of the track is a short last packet (6.1), a short one that also states the
            # samples dropped from its frame (9.0), or a full one that states them (9.1, #659): a
            # packet holds the smaller of its duration and its 1024-sample frame less the drop
            return sum(min(int(p["duration"]), 1024 - sum(int(s.get("discard_padding", 0)) for s in p.get("side_data_list", [])))
                       for p in packets) - 1024

        def frames(path):
            return int(sh("ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path).stdout.split()[0].strip(","))

        long48, short48 = clip("exact_long_48.mov", 48000, 59244), clip("exact_short_48.mov", 48000, 24000, "testsrc2")
        long44, short44 = clip("exact_long_44.mov", 44100, 54433), clip("exact_short_44.mov", 44100, 22050, "testsrc2")
        for path, rate, samples in ((long48, 48000, 59244), (long44, 44100, 54433)):
            self.assertEqual(round(float(probe(str(path))["duration"]) * rate), samples, "fixture")
            self.assertNotEqual(round(round(samples / rate, 3) * rate), samples, "not a whole millisecond: the old rounding missed it")
        at48k_of_44 = round(float(probe(str(long44))["duration"]) * 48000)  # broll and multicam write 48 kHz
        cases = [
            # (label, tool, arguments, rate the sound is written at, samples)
            ("grid pads the shorter clip's sound", "grid.py", [short48, long48, "--cols", "2", "--rows", "1", "--pad", "--audio-from", "0", "--label", "none"], 48000, 59244),
            ("grid trims the longer clip's sound", "grid.py", [short48, long48, "--cols", "2", "--rows", "1", "--pad", "--audio-from", "1", "--label", "none"], 48000, 59244),
            ("grid at 44.1 kHz", "grid.py", [short44, long44, "--cols", "2", "--rows", "1", "--pad", "--audio-from", "0", "--label", "none"], 44100, 54433),
            ("broll mix", "broll.py", [long48, "--insert", short48, "--at", "0.2", "--duration", "0.4", "--audio", "mix"], 48000, 59244),
            ("broll b", "broll.py", [long48, "--insert", short48, "--at", "0.2", "--duration", "0.4", "--audio", "b"], 48000, 59244),
            ("broll from 44.1 kHz", "broll.py", [long44, "--insert", short44, "--at", "0.2", "--duration", "0.4", "--audio", "mix"], 48000, at48k_of_44),
            ("multicam", "multicam.py", [long48, short48, "--switch", "0-0.5:0,0.5-1:1"], 48000, 59244),
            ("multicam from 44.1 kHz", "multicam.py", [long44, short44, "--switch", "0-0.5:0,0.5-1:1"], 48000, at48k_of_44),
        ]
        for label, tool, args, rate, samples in cases:
            with self.subTest(case=label):
                out = OUT / f"exact_{tool[:-3]}_out.mp4"
                doc = json.loads(script(tool, *args, "-o", out, "--json").stdout)
                self.assertEqual(int(probe(str(out))["audio"]["sample_rate"]), rate)
                self.assertEqual(track_samples(out), samples)
                self.assertIn(f"apad=whole_len={samples},atrim=end_sample={samples},atrim=end=", " ".join(map(str, doc["commands"])))
        # the picture is what it was: the output's -t moved by half a sample, not by a frame
        self.assertEqual(frames(OUT / "exact_grid_out.mp4"), 37)  # 1.234 s at grid.py's 30 fps
        self.assertEqual(frames(OUT / "exact_broll_out.mp4"), 25)
        self.assertEqual(frames(OUT / "exact_multicam_out.mp4"), 25)
        # the one conform, as audio.py emits it (tests/test_audio.py pins audio.py's own graph)
        import _common
        self.assertEqual(_common.conform_to_length(59244 / 48000, 48000),
                         "aformat=sample_rates=48000,apad=whole_len=59244,atrim=end_sample=59244,atrim=end=1.234260")
        # a dry run's pending A-roll has no length to count in: the old filter stays, as in audio.py
        plan = script("broll.py", OUT / "exact_not_written_yet.mp4", "--insert", short48, "--at", "0.2", "--duration", "0.4",
                      "--audio", "mix", "--dry-run", "-o", OUT / "exact_plan.mp4", "--json")
        self.assertIn("atrim=duration=0.000", plan.stdout)
        self.assertNotIn("whole_len", plan.stdout)

    def test_multicam_offsets_and_switch(self):
        camB = OUT / "camB.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", self.src, "-vf", "hue=h=90", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", camB)
        data = json.loads(script("multicam.py", self.src, camB, self.mic, "--offsets-only", "--json").stdout)
        self.assertClose(data["offsets_seconds"][1], 1.5, 0.05)
        self.assertClose(data["offsets_seconds"][2], 2.5, 0.05)
        out = OUT / "mc.mp4"
        data = json.loads(script("multicam.py", self.src, camB, self.mic, "--audio", "2", "--switch", "0-3:0,3-6:1,6-9:0", "--fast", "-o", out, "--json").stdout)
        self.assertEqual(len(data["cuts"]), 4, "three named ranges plus the gap-fill to the end")
        m = probe(str(out))
        self.assertClose(m["duration"], 12.0, 0.2)
        self.assertEqual(m["audio"]["channels"], 2)
        # camB is hue-shifted: a frame at 4.5 s (camera 1) must differ from one at 2 s (camera 0)
        script("look.py", out, "--at", "2", "--at", "4.5", "-o", OUT / "mcf")
        self.assertNotEqual((OUT / "mcf_2.000s.png").read_bytes()[100:2000], (OUT / "mcf_4.500s.png").read_bytes()[100:2000])
        auto = OUT / "mc_auto.mp4"
        script("multicam.py", self.src, camB, "--auto", "4", "--fast", "-o", auto)
        self.assertClose(probe(str(auto))["duration"], 12.0, 0.2)
        script("multicam.py", self.src, camB, "--switch", "0-3:5", expect_fail=True)

    # ------------------------------------------------------------ 1.18.0: --switch energy / --edl
    def _loud_cams(self):
        """Two cameras on one reference timeline: camA loud 0-6s / quiet 6-12s, camB the reverse
        -- --switch energy should pick camA for the first half and camB for the second."""
        camA = OUT / "mc_energy_a.mp4"
        camB = OUT / "mc_energy_b.mp4"
        if not camA.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=160x90:rate=30", "-f", "lavfi",
               "-i", "aevalsrc='0.8*sin(2*PI*440*t)*lt(t\\,6)+0.01*sin(2*PI*440*t)*gt(t\\,6)':s=48000",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", camA)
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=160x90:rate=30,hue=h=90", "-f", "lavfi",
               "-i", "aevalsrc='0.01*sin(2*PI*440*t)*lt(t\\,6)+0.8*sin(2*PI*440*t)*gt(t\\,6)':s=48000",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", camB)
        return camA, camB

    def test_multicam_switch_energy_picks_the_loudest_camera(self):
        camA, camB = self._loud_cams()
        out = OUT / "mc_energy.mp4"
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "1",
                                 "--fast", "-o", out, "--json").stdout)
        self.assertEqual(data["switch_mode"], "energy")
        cams_by_time = {}
        for s, e, c in data["cuts"]:
            cams_by_time[(s + e) / 2] = c
        early = [c for t, c in cams_by_time.items() if t < 5]
        late = [c for t, c in cams_by_time.items() if t > 7]
        self.assertTrue(early and all(c == 0 for c in early), f"expected camera 0 (louder) early: {data['cuts']}")
        self.assertTrue(late and all(c == 1 for c in late), f"expected camera 1 (louder) late: {data['cuts']}")

    def test_multicam_switch_energy_respects_min_shot(self):
        camA, camB = self._loud_cams()
        out = OUT / "mc_energy_minshot.mp4"
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "3",
                                 "--fast", "-o", out, "--json").stdout)
        for s, e, _c in data["cuts"]:
            # the very first/last cut may be shorter (it borders the clip edge), interior cuts
            # must respect --min-shot
            if s > 0.01 and e < 11.99:
                self.assertGreaterEqual(round(e - s, 2), 3.0 - 0.05, data["cuts"])

    def test_multicam_edl_matches_the_reported_cuts(self):
        camA, camB = self._loud_cams()
        edl = OUT / "mc_energy.edl"
        out = OUT / "mc_energy_edl.mp4"
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "1",
                                 "--edl", edl, "--fast", "-o", out, "--json").stdout)
        lines = edl.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), len(data["cuts"]))
        for line, (s, e, _c) in zip(lines, data["cuts"]):
            a, b = (float(x) for x in line.split("-"))
            self.assertAlmostEqual(a, s, delta=0.01)
            self.assertAlmostEqual(b, e, delta=0.01)
            self.assertLess(a, b)

    def test_multicam_switch_energy_needs_at_least_one_video_camera(self):
        wav_a = OUT / "mc_energy_audio_only_a.wav"
        wav_b = OUT / "mc_energy_audio_only_b.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "4", wav_a)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "4", wav_b)
        script("multicam.py", wav_a, wav_b, "--switch", "energy", "-o", OUT / "mc_nope.mp4", expect_fail=True)

    def test_multicam_min_shot_must_be_positive(self):
        camA, camB = self._loud_cams()
        script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "0", "-o", OUT / "mc_nope2.mp4", expect_fail=True)

    def test_multicam_edl_is_renderable_as_a_render_project(self):
        """The multicam timeline is expressible as a render.py project without a new stage type:
        each cut becomes a clip that points at its own camera's file with in/out on that camera's
        OWN timeline (reference time shifted by the measured offset), using render.py's existing
        clips array -- see docs/contract.md and docs/design-decisions.md for why no new project
        schema was needed."""
        camA, camB = self._loud_cams()
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "1",
                                 "--fast", "-o", OUT / "mc_energy_proj.mp4", "--json").stdout)
        offsets = data["offsets_seconds"]
        clips = [{"src": [str(camA), str(camB)][c], "in": round(s - offsets[c], 3), "out": round(e - offsets[c], 3)}
                for s, e, c in data["cuts"]]
        project = OUT / "mc_project.json"
        project.write_text(json.dumps({"output": "mc_rendered.mp4", "clips": clips}), encoding="utf-8")
        out = OUT / "mc_rendered.mp4"
        script("render.py", project, "--fast", "-o", out)
        self.assertTrue(out.exists())
        m = probe(str(out))
        # the measured per-camera offset carries its own small error, so this is a looser bound
        # than the multicam output's own duration check -- the point is that render.py accepts the
        # clip list at all, not a frame-accurate re-derivation of multicam's own timeline math.
        self.assertGreater(m["duration"], 8.0)

    # ------------------------------------------------------------ --write-project
    def test_multicam_write_project_energy_mode_two_cams(self):
        """--switch energy --write-project FILE: FILE's clips[] must alternate src between the
        two cameras the same way `cuts` does, with in/out on each camera's own timeline, and a
        render.py --dry-run against it must plan exactly one cut.py per cut."""
        camA, camB = self._loud_cams()
        out = OUT / "mc_wp_energy.mp4"
        proj = OUT / "mc_wp_energy.json"
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "1",
                                 "--write-project", proj, "--fast", "-o", out, "--json").stdout)
        cuts = data["cuts"]
        offsets = data["offsets_seconds"]
        project = json.loads(proj.read_text(encoding="utf-8"))
        clips = project["clips"]
        self.assertEqual(len(clips), len(cuts))
        inputs = [str(camA), str(camB)]
        for clip, (s, e, c) in zip(clips, cuts):
            self.assertEqual(clip["src"], inputs[c])
            self.assertAlmostEqual(clip["in"], s - offsets[c], delta=0.01)
            self.assertAlmostEqual(clip["out"], e - offsets[c], delta=0.01)
        # at least one clip from each camera, confirming the src actually alternates
        self.assertEqual({c["src"] for c in clips}, set(inputs))
        # the combined multicam output itself is still written, unchanged, alongside the project
        self.assertTrue(out.exists())
        r = script("render.py", proj, "--dry-run", "--json")
        rdata = json.loads(r.stdout)
        self.assertEqual(rdata["status"], "completed")
        # render.py's clips stage forwards to cut.py, one child call per clip; its dry-run
        # accounting must match the number of cuts multicam.py itself made.
        cut_calls = [line for line in r.stderr.splitlines() if re.search(r"cut\.py .* --dry-run", line)]
        self.assertEqual(len(cut_calls), len(cuts))

    def test_multicam_write_project_three_cams(self):
        """3-source case: each camera has its own measured offset, and each clip's in/out must be
        shifted by that camera's own offset, not the reference's or another camera's."""
        camA = self.src
        camB = OUT / "mc_wp3_camB.mp4"
        camC = OUT / "mc_wp3_camC.mp4"
        if not camB.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", camA,
               "-vf", "hue=h=90", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", camB)
        if not camC.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "3.0", "-i", camA,
               "-vf", "hue=h=180", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", camC)
        out = OUT / "mc_wp3.mp4"
        proj = OUT / "mc_wp3.json"
        data = json.loads(script("multicam.py", camA, camB, camC, "--switch", "0-3:0,3-6:1,6-9:2",
                                 "--write-project", proj, "--fast", "-o", out, "--json").stdout)
        offsets = data["offsets_seconds"]
        self.assertAlmostEqual(offsets[1], 1.5, delta=0.05)
        self.assertAlmostEqual(offsets[2], 3.0, delta=0.05)
        cuts = data["cuts"]
        project = json.loads(proj.read_text(encoding="utf-8"))
        clips = project["clips"]
        self.assertEqual(len(clips), len(cuts))
        inputs = [str(camA), str(camB), str(camC)]
        for clip, (s, e, c) in zip(clips, cuts):
            self.assertEqual(clip["src"], inputs[c])
            self.assertAlmostEqual(clip["in"], s - offsets[c], delta=0.01)
            self.assertAlmostEqual(clip["out"], e - offsets[c], delta=0.01)
        used = {c["src"] for c in clips}
        self.assertEqual(used, set(inputs), f"expected all three cameras used: {clips}")
        r = script("render.py", proj, "--dry-run", "--json")
        rdata = json.loads(r.stdout)
        self.assertEqual(rdata["status"], "completed")
        self.assertEqual(rdata["stages"][0], "clips")

    def test_multicam_write_project_manual_switch(self):
        """--write-project must work the same off a hand-written --switch spec, not just energy
        mode -- the project-writing logic is built from `cuts` + `offsets` alone."""
        camB = OUT / "camB.mp4"
        if not camB.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", self.src,
               "-vf", "hue=h=90", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", camB)
        out = OUT / "mc_wp_manual.mp4"
        proj = OUT / "mc_wp_manual.json"
        data = json.loads(script("multicam.py", self.src, camB, self.mic, "--audio", "2",
                                 "--switch", "0-3:0,3-6:1,6-9:0", "--write-project", proj,
                                 "--fast", "-o", out, "--json").stdout)
        cuts = data["cuts"]
        offsets = data["offsets_seconds"]
        project = json.loads(proj.read_text(encoding="utf-8"))
        clips = project["clips"]
        self.assertEqual(len(clips), len(cuts), "one clips[] entry per cut, four: three named ranges plus the gap-fill")
        inputs = [str(self.src), str(camB), str(self.mic)]
        for clip, (s, e, c) in zip(clips, cuts):
            self.assertEqual(clip["src"], inputs[c])
            self.assertAlmostEqual(clip["in"], s - offsets[c], delta=0.01)
            self.assertAlmostEqual(clip["out"], e - offsets[c], delta=0.01)
        # a switch is a cut: without a stated transition render.py crossfades 0.5 s at every join,
        # so the project ran 0.5 s a switch short of the direct render and moved each later switch
        self.assertEqual(project["transition"], {"type": "none"})
        r = script("render.py", proj, "--dry-run", "--json")
        rdata = json.loads(r.stdout)
        self.assertEqual(rdata["status"], "completed")
        joined = [c for c in rdata["commands"] if "joined.mp4" in c and "-filter_complex" in c]
        self.assertEqual(len(joined), 1, rdata["commands"])
        self.assertIn(f"concat=n={len(clips)}", joined[0])
        self.assertNotIn("xfade", joined[0])

    def test_multicam_write_project_does_not_change_default_behavior(self):
        """Without --write-project, multicam.py's existing behavior (combined output, --edl,
        --offsets-only) must be exactly what it was before this flag existed."""
        camA, camB = self._loud_cams()
        out = OUT / "mc_wp_regress.mp4"
        edl = OUT / "mc_wp_regress.edl"
        data = json.loads(script("multicam.py", camA, camB, "--switch", "energy", "--min-shot", "1",
                                 "--edl", edl, "--fast", "-o", out, "--json").stdout)
        self.assertTrue(out.exists())
        self.assertTrue(edl.exists())
        lines = edl.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), len(data["cuts"]))
        # --offsets-only is unaffected by the new flag either
        odata = json.loads(script("multicam.py", camA, camB, "--offsets-only", "--json").stdout)
        self.assertIn("offsets_seconds", odata)
        self.assertNotIn("cuts", odata)

    def test_multicam_fix_drift_trims_before_resample_not_after(self):
        """--fix-drift's audio path computes a_start (an atrim start point) in the source's own
        pre-correction time axis, but the filter chain used to apply asetrate/aresample (the drift
        correction) *before* atrim -- so the trim landed on the already-rescaled timeline instead
        of the raw one it was computed for, same bug class as sync.py already avoids by seeking
        with -ss (an input-level, pre-filter operation) before its own drift_af. Build a camera
        whose audio started before the reference (offsets[a] < 0, so a_start > 0) and also drifts
        (ratios[a] != 1), then check the constructed [<audio input>:a] filter chain: atrim=start=
        must appear before asetrate, mirroring sync.py's ordering."""
        base = OUT / "mc_drift_base.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "200", "-c:a", "pcm_s16le", base)
        ref_audio = OUT / "mc_drift_ref.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.2", "-i", base, "-c:a", "pcm_s16le", ref_audio)
        camB = OUT / "mc_drift_camB.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-af", "asetrate=48000*0.9995,aresample=48000", "-c:a", "pcm_s16le", camB)
        cam0 = OUT / "mc_drift_cam0.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-i", ref_audio, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", cam0)

        data = json.loads(script("multicam.py", cam0, camB, "--audio", "1", "--switch", "0-198:0", "--fix-drift", "--max-offset", "5", "--fast", "-o", OUT / "mc_drift_out.mp4", "--json").stdout)
        self.assertLess(data["offsets_seconds"][1], 0, "camera 1 must have started before the reference for a_start > 0 to be exercised")
        self.assertNotEqual(data["drift_ppm"][1], 0.0, "drift must actually be detected for asetrate/aresample to be in the chain")
        audio_chain = data["commands"][0].split("[1:a]", 1)[1]
        self.assertLess(audio_chain.index("atrim=start="), audio_chain.index("asetrate="),
                         "atrim=start= (in the pre-correction time axis) must run before asetrate/aresample rescale that axis")

    def test_multicam_negative_auto_interval_refused_not_infinite_loop(self):
        """--auto builds cuts with `while t < ref_dur: ... t += args.auto` -- `elif args.auto:` is
        only false for exactly 0, so a negative value used to pass that check and enter the loop
        with t decreasing every iteration, meaning t < ref_dur never becomes false: the process
        hangs forever instead of erroring on invalid input. Must be refused up front instead."""
        script("multicam.py", self.src, self.src, "--auto", "-1", "--fast", "-o", OUT / "mc_auto_neg.mp4", expect_fail=True)

    def test_multicam_switch_range_under_a_millisecond_is_refused(self):
        """The sibling of scenes.py --highlights' 0.00-0.00: --switch "0-0.0004:1" passed (end is
        after start) and the cut list, written to the millisecond, held "0.000-0.000", which
        cut.py --segments refuses."""
        edl = OUT / "mc_tiny.txt"
        for extra in ([], ["--dry-run"]):
            with self.subTest(extra=extra):
                r = script("multicam.py", self.src, self.src, "--switch", "0-0.0004:1,0.0004-3:0", "--edl", edl,
                           "-o", OUT / "mc_tiny.mp4", "--json", *extra, expect_fail=True)
                doc = json.loads(r.stdout)
                self.assertEqual(doc["error"]["kind"], "input")
                self.assertIn("millisecond", doc["error"]["message"])
                self.assertFalse(edl.exists())
        # the gap the fill makes before a range that starts 0.4 ms in was the same line: the
        # range takes it, and every line of the cut list is a range cut.py --segments accepts
        data = json.loads(script("multicam.py", self.src, self.src, "--switch", "0.0004-3:1", "--edl", edl,
                                 "--fast", "-o", OUT / "mc_tiny.mp4", "--json").stdout)
        self.assertEqual(data["cuts"][0], [0.0, 3.0, 1])
        lines = edl.read_text(encoding="utf-8").split()
        self.assertEqual(lines[0], "0.000-3.000")
        for line in lines:
            a, b = (float(x) for x in line.split("-"))
            self.assertLess(a, b, line)
        edl.unlink()

    def test_multicam_switch_ranges_that_overlap_are_refused(self):
        """A132: two --switch ranges over the same reference time were both rendered, so the
        overlap's picture played twice beside sound that played once, and every later cut ran
        behind the sound. Refused before ffmpeg runs, in a dry run too; ranges that touch run."""
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra):
                proc = script("multicam.py", self.src, self.src, "--switch", "0-6:0,5-12:1", "--fast",
                              "-o", OUT / "mc_overlap.mp4", "--json", *extra, expect_fail=True)
                doc = json.loads(proc.stdout)
                self.assertEqual(doc["error"]["kind"], "input")
                self.assertIn("overlap", doc["error"]["message"])
                self.assertNotIn("$ ", proc.stderr, "refused before ffmpeg ran")
        doc = json.loads(script("multicam.py", self.src, self.src, "--switch", "0-6:0,6-12:1", "--fast",
                                "-o", OUT / "mc_touching.mp4", "--json").stdout)
        self.assertEqual([c[:2] for c in doc["cuts"]], [[0.0, 6.0], [6.0, 12.0]])

    def test_multicam_fix_drift_retimes_the_picture_with_the_sound(self):
        """A130: --fix-drift resampled a drifting camera's sound to the reference clock, but its
        picture played at its own rate: a range of `d` reference seconds took d * ratio of it, so
        a camera running 2000 ppm slow held a 59 s range 0.12 s too long and the next cut came
        four frames late. Camera A is red, camera B blue with B's sound 0.2 % slow; the cut back
        to A at 60 s is measured on the decoded frames."""
        base = OUT / "mc459_base.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "140", "-c:a", "pcm_s16le", base)
        slow = OUT / "mc459_slow.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-af", "asetrate=48000*0.998,aresample=48000",
           "-c:a", "pcm_s16le", slow)
        cams = []
        for colour, sound in (("red", base), ("blue", slow)):
            cam = OUT / f"mc459_{colour}.mp4"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color={colour}:s=32x32:r=30",
               "-i", sound, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", cam)
            cams.append(cam)
        out = OUT / "mc459_drift.mp4"
        proj = OUT / "mc459_drift.json"
        data = json.loads(script("multicam.py", *cams, "--switch", "1-60:1,60-130:0", "--fix-drift", "--fast",
                                 "--write-project", proj, "-o", out, "--json").stdout)
        self.assertAlmostEqual(data["drift_ppm"][1], 2000, delta=150, msg="fixture: the drift is measured")
        self.assertEqual([c[2] for c in data["cuts"][:3]], [0, 1, 0])
        frames = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "59", "-i", str(out), "-t", "2",
                                 "-vf", "scale=2:2,format=rgb24", "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                                stdout=subprocess.PIPE, check=True).stdout
        first_red = next(i for i in range(len(frames) // 12) if frames[i * 12] > frames[i * 12 + 2])
        self.assertLessEqual(abs(59 + first_red / 30 - 60.0), 1.5 / 30, f"camera A is back at frame {first_red} after 59 s")
        # the project times each clip as the render does: render.py plays a clip at its speed, so
        # a drift-corrected camera's clip lasts its reference range, not (ratio - 1) longer (it
        # carried no speed); camera A, not retimed, carries none
        clips = json.loads(proj.read_text(encoding="utf-8"))["clips"]
        self.assertEqual(len(clips), len(data["cuts"]))
        for clip, (s, e, cam) in zip(clips, data["cuts"]):
            self.assertEqual("speed" in clip, cam == 1, clip)
            self.assertAlmostEqual((clip["out"] - clip["in"]) / clip.get("speed", 1.0), e - s, delta=0.005, msg=clip)
        for p in [base, slow, out, proj] + cams:
            p.unlink()

    def test_multicam_warns_on_a_camera_with_no_shared_audio_event(self):
        """A camera whose audio has nothing in common with the reference must not align silently."""
        unrelated = OUT / "camC_unrelated.mp4"
        # a flat-envelope tone: nothing for the envelope-based cross-correlation to lock onto,
        # unlike the reference's gated tones -- unrelated in the way a different room's constant hum would be
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=233:sample_rate=48000", "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", unrelated)
        proc = script("multicam.py", self.src, unrelated, "--offsets-only", "--json")
        data = json.loads(proc.stdout)
        self.assertLess(data["confidence"][1], 0.1)
        self.assertIn("low correlation confidence", proc.stderr)

    def test_render_export_normalize_forwards_the_flag(self):
        proj = OUT / "project_normalize.json"
        proj.write_text(json.dumps({
            "output": "render_normalize.mp4",
            "clips": [{"src": "source.mp4"}],
            "export": {"preset": "x", "normalize": True},
            "check": {"platform": "x"},
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertTrue(data["check"]["ok"], data["check"])
        rows = {r["check"]: r["status"] for r in data["check"]["checks"]}
        self.assertEqual(rows["loudness"], "PASS", "the -9 LUFS source (whole clip: a 2 s slice happens to sit at -13 LUFS) only passes when export ran --normalize")
        # 1.9: a platform preset with no loudness stage normalises by default; false opts out
        proj.write_text(json.dumps({
            "output": "render_normalize_default.mp4",
            "clips": [{"src": "source.mp4"}],
            "export": {"preset": "x"},
            "check": {"platform": "x"},
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertEqual({r["check"]: r["status"] for r in data["check"]["checks"]}["loudness"], "PASS")
        proj.write_text(json.dumps({
            "output": "render_normalize_off.mp4",
            "clips": [{"src": "source.mp4"}],
            "export": {"preset": "x", "normalize": False},
            "check": {"platform": "x"},
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--fast", "--json", expect_fail=True).stdout)
        self.assertEqual({r["check"]: r["status"] for r in data["check"]["checks"]}["loudness"], "FAIL")
        # 4.0.0: export.py normalises a platform preset by default (#579); a project's own loudness
        # stage keeps its level, so render passes --no-normalize (the -24 LUFS fails x's -14)
        proj.write_text(json.dumps({
            "output": "render_normalize_own_stage.mp4",
            "clips": [{"src": "source.mp4"}],
            "loudness": {"lufs": -24},
            "export": {"preset": "x"},
            "check": {"platform": "x"},
        }), encoding="utf-8")
        data = json.loads(script("render.py", proj, "--fast", "--json", expect_fail=True).stdout)
        self.assertEqual({r["check"]: r["status"] for r in data["check"]["checks"]}["loudness"], "FAIL")

    def test_render_project(self):
        proj = OUT / "project.json"
        proj.write_text(json.dumps({
            "output": "render_final.mp4",
            "frame": {"aspect": "9:16", "width": 720, "fps": 30},
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:05"}, {"src": "source.mp4", "in": 6, "out": 10, "speed": 1.25}],
            "transition": {"type": "fade", "duration": 0.5},
            "captions": {"text": "cues.txt", "animate": "pop", "karaoke": True, "size": 26},
            "overlays": [{"text": "render test", "position": "top-left", "start": 0.5, "end": 3, "fade": 0.3, "box": True}],
            "audio": {"music": "long_ref.wav", "music_volume": -20, "duck": True, "fade_out": 1},
            "loudness": {"lufs": -14, "tp": -1},
            "export": {"preset": "reels"},
            "check": {"platform": "reels"},
        }), encoding="utf-8")
        if not (OUT / "cues.txt").exists():
            (OUT / "cues.txt").write_text("0:00-0:03 Hello world\n", encoding="utf-8")
        (OUT / "render_final.mp4").unlink(missing_ok=True)
        plan = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        self.assertTrue(plan["dry_run"])
        self.assertFalse((OUT / "render_final.mp4").exists())
        data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertEqual(data["stages"], ["clips", "join", "fit", "captions", "overlays", "audio", "loudness", "export", "check"])
        self.assertTrue(data["check"]["ok"], data["check"])
        m = probe(str(OUT / "render_final.mp4"))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 1920))
        self.assertClose(m["duration"], 4 + 3.2 - 0.5, 0.4)
        self.assertEqual(list(OUT.glob("render_final_work*")), [], "work dir removed when not kept")
        init = OUT / "init.json"
        script("render.py", "--init", init)
        self.assertIn("clips", json.loads(init.read_text()))
        # --stop-after keeps the intermediate
        out = json.loads(script("render.py", proj, "--fast", "--stop-after", "join", "--work", OUT / "rw", "--json").stdout)
        self.assertEqual(out["stages"], ["clips", "join"])
        self.assertTrue(Path(out["output"]).exists())
        # 2.24.1: without --work the auto-named directory was removed at exit, deleting the file
        # the result named (and described by output_identity)
        out = json.loads(script("render.py", proj, "--fast", "--stop-after", "join", "--json").stdout)
        self.assertTrue(Path(out["output"]).exists(), out["output"])
        self.assertEqual(Path(out["output"]).stat().st_size, out["output_identity"]["size"])
        shutil.rmtree(Path(out["output"]).parent, ignore_errors=True)

    def test_render_every_stage_flag_and_every_refusal(self):
        """render.py's stage branches that test_render_project does not take (silence, captions
        from srt/ass, graphics, image and logo overlays, audio replace/loop/stereo/mono/downmix,
        export fit/crf, brand forwarding, the no-export copy path) and its refusals (no project,
        unreadable project, empty clips, captions/graphics/overlays without their required key,
        a child script failing) were untested (#147). --dry-run drives every argv-building branch
        without encoding; the copy path and the child failure run for real on a 2 s clip."""
        srt = OUT / "render_full.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello\n\n", encoding="utf-8")
        ass = OUT / "render_full.ass"
        logo = OUT / "render_full_logo.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", logo)
        brand = OUT / "render_full_brand.json"
        brand.write_text(json.dumps({"logo": logo.name, "logo_position": "top-right", "colors": {"primary": "FF6A00", "text": "FFFFFF"}}), encoding="utf-8")
        full = {
            "output": "render_full.mp4",
            "brand": brand.name,
            "clips": [{"src": "source.mp4", "in": 0, "out": 2}, {"src": "source.mp4", "in": 2, "out": 4}],
            "frame": {"width": 640, "height": 360, "fps": 25},
            "fit": {"duration": 3.5, "method": "trim"},
            "captions": {"srt": srt.name, "font": "DejaVu Sans", "position": "top", "bold": True, "box": True},
            "graphics": [{"template": "lower-third", "name": "Ada", "title": "Analyst", "start": 0, "end": 2},
                         {"template": "title", "title": "T", "subtitle": "S", "start": 0, "end": 1, "position": "top-left"}],
            "overlays": [{"image": logo.name, "position": "bottom-right", "opacity": 0.5, "scale": 80},
                         {"logo": True, "start": 0, "end": 1},
                         {"text": "txt", "font_size": 24, "margin": 12, "box": True}],
            # "music" is here since audit A141: its volume and loop without a bed are refused, not ignored
            "audio": {"replace": "long_ref.wav", "music": "long_ref.wav", "music_volume": -12, "gain": 1, "music_loop": True,
                      "stereo": True, "denoise": True},
            "loudness": {"lufs": -16},
            "export": {"preset": "youtube", "fit": "pad", "crf": 20},
        }
        proj = OUT / "render_full.json"
        proj.write_text(json.dumps(full), encoding="utf-8")
        proc = script("render.py", proj, "--dry-run", "--json")
        plan = json.loads(proc.stdout)
        self.assertEqual(plan["stages"], ["clips", "join", "fit", "captions", "graphics", "overlays", "audio", "loudness", "export"])
        forwarded = "\n".join(l for l in proc.stderr.splitlines() if l.startswith("→ "))  # render's own child invocations
        for needle in ("--srt", "--template lower-third", "--image", "--logo", "--replace", "--music-loop", "--fit pad --crf 20", "--brand"):
            self.assertIn(needle, forwarded, f"{needle} not forwarded:\n{forwarded}")
        for stage in ("fit", "captions", "graphics", "overlays", "audio", "loudness"):
            out = json.loads(script("render.py", proj, "--dry-run", "--stop-after", stage, "--json").stdout)
            self.assertEqual(out["stages"][-1], stage)
        # single uncut clip (so silence.py can analyse a real file under --dry-run), silence stage,
        # captions from .ass, mono/downmix/duck audio, voice flag: the other branches of the same tables
        alt = dict(full, clips=[{"src": "source.mp4"}], silence={"threshold": -40, "min_silence": 0.4, "margin": 0.1, "margin_lead": 0.05, "margin_tail": 0.3},
                   captions={"ass": ass.name}, audio={"music": "long_ref.wav", "mono": True, "downmix": True, "duck": True, "voice": True, "duck_amount": 8}, graphics=[], overlays=[])
        ass.write_text("[Script Info]\nScriptType: v4.00+\n\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,hi\n", encoding="utf-8")
        (OUT / "render_full_alt.json").write_text(json.dumps(alt), encoding="utf-8")
        proc = script("render.py", OUT / "render_full_alt.json", "--dry-run", "--json")
        self.assertEqual(json.loads(proc.stdout)["stages"], ["clips", "silence", "fit", "captions", "audio", "loudness", "export"])
        forwarded = "\n".join(l for l in proc.stderr.splitlines() if l.startswith("→ "))
        for needle in ("--ass", "--min-silence 0.4", "--margin-lead 0.05", "--margin-tail 0.3", "--mono", "--downmix", "--duck-amount 8", "--voice"):
            self.assertIn(needle, forwarded, f"{needle} not forwarded:\n{forwarded}")
        out = json.loads(script("render.py", OUT / "render_full_alt.json", "--dry-run", "--stop-after", "silence", "--json").stdout)
        self.assertEqual(out["stages"], ["clips", "silence"])
        # no export block: the last stage is copied to the output, for real
        copy_proj = OUT / "render_copy.json"
        copy_proj.write_text(json.dumps({"output": "render_copy.mp4", "clips": [{"src": "source.mp4", "in": 0, "out": 2}]}), encoding="utf-8")
        data = json.loads(script("render.py", copy_proj, "--fast", "--json").stdout)
        self.assertEqual(data["stages"], ["clips"])
        self.assertClose(probe(str(OUT / "render_copy.mp4"))["duration"], 2.0, 0.3)
        # refusals: each names its cause and exits non-zero
        cases = {
            "no_project": ([], "give a project.json"),
            "unreadable": ([OUT / "render_missing.json"], "cannot read project"),
            "empty_clips": ([self._proj("render_e1.json", {"clips": []})], "clips is empty"),
            "captions_key": ([self._proj("render_e2.json", {"clips": full["clips"], "captions": {"size": 20}}), "--dry-run"], "captions needs text, srt or ass"),
            "graphics_key": ([self._proj("render_e3.json", {"clips": full["clips"], "graphics": [{"name": "x"}]}), "--dry-run"], "needs a template"),
            "overlay_key": ([self._proj("render_e4.json", {"clips": full["clips"], "overlays": [{"opacity": 1}]}), "--dry-run"], "needs logo, image, text or video"),
            "child_failed": ([self._proj("render_e5.json", {"clips": [{"src": "source.mp4", "in": "not-a-time", "out": 2}]}), "--dry-run"], "cut.py failed"),
        }
        for name, (argv, message) in cases.items():
            proc = script("render.py", *argv, expect_fail=True)
            self.assertIn(message, proc.stderr, f"{name}: {proc.stderr[-400:]}")

    def test_render_refuses_an_unknown_project_key_naming_the_nearest_valid_one(self):
        """Review 9: a project was read with dict.get only, so a mistyped key was silently
        ignored -- a clip "start"/"end" (the spelling graphics and overlays use for their own
        times) rendered the whole clip untrimmed, and "exports" dropped the export stage, both
        reported as a successful render. Every key of the project and of each stage/clip object
        is now checked, and the template still validates."""
        cases = {
            "clip_key": ({"clips": [{"src": "source.mp4", "start": 0, "end": 2}], "export": {"preset": "reels"}},
                         "clips[0]: unknown key 'start' (did you mean 'in'?)"),
            "stage_key": ({"clips": [{"src": "source.mp4", "in": 0, "out": 2}], "exports": {"preset": "reels"}},
                          "project: unknown key 'exports' (did you mean 'export'?)"),
            "nested_key": ({"clips": [{"src": "source.mp4"}], "export": {"preset": "reels", "quality": 20}},
                           "export: unknown key 'quality'"),
        }
        for name, (body, message) in cases.items():
            proc = script("render.py", self._proj(f"render_key_{name}.json", body), "--dry-run", "--json", expect_fail=True)
            self.assertIn(message, proc.stderr, f"{name}: {proc.stderr[-400:]}")
            doc = json.loads(proc.stdout)
            self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        tmpl = OUT / "render_template_valid.json"
        script("render.py", "--init", tmpl)
        proc = script("render.py", tmpl, "--dry-run", expect_fail=True)  # only REPLACE_ME.mp4 is missing
        self.assertIn("clip 0: missing: ", proc.stderr)
        self.assertNotIn("unknown key", proc.stderr)

    # ------------------------------------------------ #326: a video layer in overlays[]
    def _pip_plate(self, name, color, inset=False):
        """A 200x50 plate of one colour, 2 s; `inset` adds a white 40x40 square at (80,5)."""
        path = OUT / name
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=200x50:r=30:d=2"]
        if inset:
            cmd += ["-f", "lavfi", "-i", "color=c=white:s=40x40:r=30:d=2", "-filter_complex", "[0][1]overlay=80:5"]
        sh(*cmd, "-c:v", "libx264", "-pix_fmt", "yuv420p", path)
        return path

    @staticmethod
    def _rgb_at(path, x, y, at=1.0):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(path),
                            "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return tuple(r.stdout[:3])

    def test_render_applies_project_crop_to_each_joined_clip(self):
        from xml.etree import ElementTree

        for name, color, size in (("wide", "red", "160x90"), ("tall", "blue", "72x128")):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c={color}:s={size}:r=25:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               OUT / f"join_crop_{name}.mp4")
        cases = (
            ({"width": 72, "height": 128, "fit": "crop"}, {}, (72, 128), "fill"),
            ({"aspect": "16:9", "fit": "pad"}, {"aspect": "9:16", "fit": "crop"}, (52, 90), "fill"),
            ({"width": 72, "height": 128, "fit": "crop"}, {"fit": "pad"}, (72, 128), "fit"),
        )
        for i, (frame, fit, size, conform) in enumerate(cases):
            with self.subTest(frame=frame, fit=fit):
                project = OUT / f"join_crop_{i}.json"
                output = OUT / f"join_crop_{i}.mp4"
                timeline = OUT / f"join_crop_{i}.fcpxml"
                project.write_text(json.dumps({"output": str(output.resolve()), "frame": frame, "fit": fit,
                                               "transition": {"type": "none"},
                                               "clips": [{"src": f"join_crop_{name}.mp4"} for name in ("wide", "tall")]}),
                                   encoding="utf-8")
                script("render.py", project, "--export-timeline", timeline, "--overwrite")
                tree = ElementTree.parse(timeline)
                sequence = tree.find(".//sequence")
                sequence_format = tree.find(f"./resources/format[@id='{sequence.get('format')}']")
                self.assertEqual(tuple(int(sequence_format.get(k)) for k in ("width", "height")), size)
                self.assertIn(conform, [e.get("type") for e in tree.iter("adjust-conform")])
                script("render.py", project, "--fast", "--overwrite")
                picture = probe(str(output))["video"]
                self.assertEqual((picture["width"], picture["height"]), size)
                edge = self._rgb_at(output, size[0] // 2, 4, at=0.4)
                if conform == "fill":
                    self.assertGreater(edge[0], 120, edge)
                else:
                    self.assertLess(max(edge), 20, edge)
                tall = self._rgb_at(output, size[0] // 2, size[1] // 2, at=1.4)
                self.assertGreater(tall[2], 120, tall)

    def test_render_video_overlay_is_placed_after_fit_against_the_final_frame(self):
        """#326: overlays[] took only logo/image/text, so a webcam PiP or a keyed green screen in a
        project was "unknown key 'video'", and running overlay.py before render.py sized the layer
        against the source frame. The layer is now composited in the overlays stage, after fit:
        scale 120 on a 360x640 frame is 120 px of it (on the 1280x720 source before fit it would
        have come out about 34 px wide)."""
        blue = self._pip_plate("pip326_blue.mp4", "blue")
        frame = {"aspect": "9:16", "width": 360, "fit": "pad"}
        proj = self._proj("render_pip326.json", {
            "clips": [{"src": "source.mp4", "in": 0, "out": 2}], "frame": frame,
            "overlays": [{"video": blue.name, "position": "bottom-right", "scale": 120, "margin": 0}]})
        data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertEqual(data["stages"], ["clips", "fit", "overlays"])
        out = Path(data["output"])
        m = probe(str(out))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (360, 640))
        # 120x30 at the bottom-right corner: x 240..360, y 610..640, over the black pad
        r, g, b = self._rgb_at(out, 250, 620)
        self.assertTrue(b > 150 and r < 80, f"the PiP's left part should be blue at x=250, got {(r, g, b)}")
        self.assertLess(max(self._rgb_at(out, 230, 620)), 60, "left of the 120 px PiP the pad must remain")
        # chroma key: the green plate's green goes, its white inset stays
        green = self._pip_plate("pip326_green.mp4", "0x00ff00", inset=True)
        keyed = self._proj("render_pip326_key.json", {
            "clips": [{"src": "source.mp4", "in": 0, "out": 2}], "frame": frame,
            "overlays": [{"video": green.name, "chromakey": "0x00ff00", "chromakey_similarity": 0.2,
                          "chromakey_blend": 0.05, "position": "bottom-right", "scale": 120, "margin": 0}]})
        proc = script("render.py", keyed, "--fast", "--json")
        self.assertIn("--chromakey 0x00ff00 --chromakey-similarity 0.2 --chromakey-blend 0.05", proc.stderr)
        out = Path(json.loads(proc.stdout)["output"])
        self.assertLess(self._rgb_at(out, 250, 620)[1], 80, "the keyed green must show the pad through it")
        self.assertGreater(min(self._rgb_at(out, 298, 620)), 150, "the white inset is not keyed")

    def test_render_video_overlay_refusals_and_dry_run_plan(self):
        """#326: one layer kind per entry (overlay.py's --image/--text/--logo/--video are mutually
        exclusive), the chromakey* keys only with a video, and a missing layer file named before
        the first stage -- under --dry-run too, since no earlier stage writes it. The plan carries
        the overlay.py command with the layer as an input."""
        pip = self._pip_plate("pip326_plan.mp4", "blue")
        clips = [{"src": "source.mp4", "in": 0, "out": 2}]
        cases = {
            "video_and_image": ({"video": pip.name, "image": "logo.png"}, "not video and image"),
            "video_and_logo": ({"video": pip.name, "logo": True}, "not video and logo"),
            "key_without_video": ({"image": "logo.png", "chromakey": "green"}, 'chromakey keys a colour out of a video layer and needs "video"'),
            "tune_without_key": ({"video": pip.name, "chromakey_blend": 0.1}, 'chromakey_blend tunes "chromakey"'),
            "missing_layer": ({"video": "pip326_gone.mp4"}, "overlays[0].video: file not found"),
            "text_scale": ({"text": "Hello", "scale": 200}, "scale sizes an image, logo or video layer"),
        }
        for name, (overlay, message) in cases.items():
            proc = script("render.py", self._proj(f"render_pip326_{name}.json", {"clips": clips, "overlays": [overlay]}),
                          "--dry-run", "--json", expect_fail=True)
            self.assertIn(message, proc.stderr, f"{name}: {proc.stderr[-400:]}")
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["error"]["kind"], "input", name)
            self.assertNotIn("cut.py", proc.stderr, f"{name}: refused before the first stage")
        # a run that stops before the overlays stage never reads the layer
        gone = self._proj("render_pip326_stop.json", {"clips": clips, "overlays": [{"video": "pip326_gone.mp4"}]})
        script("render.py", gone, "--dry-run", "--stop-after", "clips")
        # an entry with a logo, an image or text draws the first of them, as in 2.8.6
        script("render.py", self._proj("render_pip326_old.json", {"clips": clips, "overlays": [{"image": "logo.png", "text": "x"}]}), "--dry-run")
        # the plan: overlay.py with --video, and the layer is an input of its planned command
        proj = self._proj("render_pip326_plan.json", {"clips": clips, "overlays": [{"video": pip.name, "position": "top-left"}]})
        proc = script("render.py", proj, "--dry-run", "--json")
        plan = json.loads(proc.stdout)
        self.assertEqual(plan["stages"], ["clips", "overlays"])
        layer = str((OUT / pip.name).resolve())   # relative to the project file, as every project path is
        self.assertIn(f"--video {layer}", proc.stderr)
        self.assertTrue(any(layer in c and "overlay=" in c for c in plan["commands"]), plan["commands"])
        # an editor timeline cannot hold the layer, and says so
        doc = json.loads(script("render.py", proj, "--export-timeline", OUT / "render_pip326.otio", "--json").stdout)
        self.assertIn("video layers", " ".join(doc["timeline"]["not_exported"]))

    def test_render_cache_misses_the_overlays_stage_when_the_layer_video_changes(self):
        """#326: the layer file is part of the overlays stage's cache key (its content, not its
        name), so replacing webcam.mp4 re-runs the overlay and serves the earlier stages."""
        cdir = OUT / "rcache_pip326"
        shutil.rmtree(cdir, ignore_errors=True)
        self._pip_plate("pip326_cache.mp4", "blue")
        proj = self._proj("render_pip326_cache.json", {
            "clips": [{"src": "source.mp4", "in": 0, "out": 2}],
            "overlays": [{"video": "pip326_cache.mp4", "scale": 100}]})
        first = json.loads(script("render.py", proj, "--cache", cdir, "--fast", "--json").stdout)
        self.assertEqual(first["cache"]["hits"], [])
        same = json.loads(script("render.py", proj, "--cache", cdir, "--fast", "--json").stdout)
        self.assertEqual(sorted(same["cache"]["hits"]), ["clips", "overlays"])
        self._pip_plate("pip326_cache.mp4", "red")   # same path, other picture
        changed = json.loads(script("render.py", proj, "--cache", cdir, "--fast", "--json").stdout)
        self.assertEqual(changed["cache"]["hits"], ["clips"])
        self.assertEqual(changed["cache"]["misses"], ["overlays"])
        r, g, b = self._rgb_at(changed["output"], 1240, 30)
        self.assertTrue(r > 150 and b < 80, f"the new red layer is the one composited, got {(r, g, b)}")

    def test_render_names_every_unusable_clip_source_before_cutting(self):
        """2.2.1: a missing third clip used to surface after the first two were cut, and a second
        missing clip only on the next run. Now every missing/empty source is named in one refusal."""
        empty = OUT / "render_empty_src.mp4"
        empty.write_bytes(b"")
        body = {"clips": [{"src": "source.mp4", "in": 0, "out": 1},
                          {"src": "gone_a.mp4"},
                          {"src": str(empty)},
                          {"src": "gone_b.mp4"}]}
        proc = script("render.py", self._proj("render_preflight.json", body), "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual((doc["status"], doc["error"]["kind"]), ("failed", "input"))
        self.assertEqual([(p["index"], p["reason"]) for p in doc["problems"]],
                         [(1, "missing"), (2, "empty (0 bytes)"), (3, "missing")])
        self.assertIn("3 of 4 clip sources unusable", proc.stderr)

    def test_render_real_run_names_every_unreadable_clip_source(self):
        """2.2.4: the real run probed sources one at a time and stopped at the first unreadable
        one; it now names every one in the same refusal as the missing/empty ones."""
        bad = []
        for n in ("a", "b"):
            p = OUT / f"render_unreadable_{n}.mp4"
            p.write_bytes(b"not a video at all")
            bad.append(p)
        body = {"clips": [{"src": "source.mp4"}, {"src": str(bad[0])}, {"src": str(bad[1])}]}
        proc = script("render.py", self._proj("render_unreadable.json", body), "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertEqual([p["index"] for p in doc["problems"]], [1, 2])
        self.assertTrue(all(p["reason"].startswith("unreadable") for p in doc["problems"]))
        self.assertIn("2 of 3 clip sources unusable", proc.stderr)

    def test_multicam_too_short_names_the_file(self):
        blip = OUT / "mc_blip.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=0.1", blip)
        proc = script("multicam.py", self.src, blip, "--offsets-only", "--json", expect_fail=True)
        doc = json.loads(proc.stdout)
        self.assertIn("not enough audio to analyse", doc["error"]["message"])
        self.assertIn(str(blip), doc["error"]["message"])


    def test_emit_and_die_use_the_ctx_they_were_given_for_the_plan(self):
        """Review 9: run()/emit()/die() took ctx= but write_plan() and the atexit hook still read
        STATE -- emit(ctx=...) wrote an empty plan while reporting one, and die(ctx=...) let the
        hook write a plan for a failed run."""
        code = (
            "import sys, atexit, json\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "import _common as c\n"
            "atexit.register(c._plan_at_exit)\n"
            "mode, src, plan = sys.argv[1], sys.argv[2], sys.argv[3]\n"
            "ctx = c.Context(); ctx.json = True; ctx.dry_run = True; ctx.plan = plan\n"
            "c.STATE.plan = plan\n"
            "c.run(['/usr/bin/ffmpeg', '-i', src, '-t', '1', src + '.out.mp4'], ctx=ctx)\n"
            "if mode == 'emit':\n"
            "    c.emit(None, ctx=ctx)\n"
            "else:\n"
            "    c.die('boom', ctx=ctx)\n"
        )
        src = str(OUT / "source.mp4")
        plan = OUT / "ctx_plan.json"
        sh(sys.executable, "-c", code, "emit", src, plan)
        doc = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["commands"]), 1, doc)
        self.assertIn("ffmpeg", doc["commands"][0])
        plan2 = OUT / "ctx_plan_die.json"
        if plan2.exists():
            plan2.unlink()
        proc = sh(sys.executable, "-c", code, "die", src, plan2, expect_fail=True)
        self.assertIn("boom", proc.stderr)
        self.assertFalse(plan2.exists(), "die() left a plan behind for a failed run")

    def test_render_default_work_dir_is_unique_per_process(self):
        """The default work dir name came only from the output path (e.g. "out_work"), no PID or
        timestamp -- two concurrent render.py runs targeting the same output (a batch.py "project"
        recipe processing files in parallel, or simply two runs by mistake) shared the same work
        directory and clobbered each other's same-named intermediates (clip00.mp4, fit.mp4, ...)
        mid-run. Verify the auto-derived work dir name includes this process's own PID."""
        proj = OUT / "project_workdir.json"
        proj.write_text(json.dumps({"output": "render_workdir_check.mp4", "clips": [{"src": "source.mp4", "in": 0, "out": 2}]}), encoding="utf-8")
        # --keep leaves the PID-suffixed dir behind, so a second run of this suite in the same
        # OUT (a local re-run, or a coverage pass) would count the previous run's dir too.
        for stale in OUT.glob("render_workdir_check_work*"):
            if stale.is_dir():
                shutil.rmtree(stale)
        out = json.loads(script("render.py", proj, "--fast", "--stop-after", "clips", "--keep", "--json").stdout)
        self.assertEqual(out["stages"], ["clips"])
        work_dirs = [p for p in OUT.glob("render_workdir_check_work*") if p.is_dir()]
        self.assertEqual(len(work_dirs), 1)
        # #458 A77: a new directory per run (mkdtemp), not the PID alone with exist_ok
        self.assertRegex(work_dirs[0].name, r"^render_workdir_check_work_\d+_\w+$",
                          "the default work dir name must carry a PID suffix, not just the bare output stem")

    def test_render_single_clip_fit_height_is_not_silently_dropped(self):
        """The single-clip fit path only ever inherited width/fps from project.frame, and the
        flag-forwarding list that turns project.fit's own keys into fit.py argv omitted height
        entirely -- so a project.json specifying "fit": {"height": N} (with no other fit key)
        used to build fit.py argv with nothing in it at all ("nothing to do" crash), and combined
        with another fit key (e.g. duration) the height silently never reached fit.py -- the
        output's height was left unchanged with no error. Verify height alone now actually
        resizes a single-clip render."""
        proj = OUT / "project_height.json"
        proj.write_text(json.dumps({
            "output": "render_height.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:04"}],
            "fit": {"height": 480},
        }), encoding="utf-8")
        script("render.py", proj, "--fast", "--json")
        m = probe(str(OUT / "render_height.mp4"))
        self.assertEqual(m["video"]["height"], 480)

    def test_render_frame_aspect_takes_the_export_presets_size(self):
        """Eval 7 (j08 twice, e01 by hand): "frame": {"aspect": "9:16"} with a reels export fitted
        a 1280x720 source to 406x720, captions were burned there and export.py upscaled them
        soft. When the export preset names a delivery frame of the same aspect, the fit stage
        uses it; a preset of another shape (or an explicit width/height) is left alone."""
        proj = OUT / "project_aspect.json"
        work = OUT / "render_aspect_work"
        proj.write_text(json.dumps({
            "output": "render_aspect.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:03"}],
            "frame": {"aspect": "9:16"},
            "export": {"preset": "reels"},
        }), encoding="utf-8")
        script("render.py", proj, "--fast", "--json", "--work", work, "--keep")
        m = probe(str(work / "fit.mp4"))
        self.assertEqual((m["video"]["width"], m["video"]["height"]), (1080, 1920))
        sys.path.insert(0, str(SCRIPTS))
        try:
            import render
        finally:
            sys.path.pop(0)
        frame = {"aspect": "1:1"}
        render.frame_from_preset(frame, {"preset": "reels"})
        self.assertEqual(frame, {"aspect": "1:1"})
        frame = {"aspect": "9:16", "width": 540}
        render.frame_from_preset(frame, {"preset": "reels"})
        self.assertEqual(frame, {"aspect": "9:16", "width": 540})
        # 2.2.1's match, kept: fit.py refuses "16/9" and "1.78:1", but a render whose own
        # fit.aspect replaces them (or that stops before fit) was sized for delivery by it, and
        # 2.2.2's first draft dropped that frame without a word (captions burned at source size)
        for aspect in ("16/9", "1.78:1", "16:9"):
            with self.subTest(aspect=aspect):
                frame = {"aspect": aspect}
                render.frame_from_preset(frame, {"preset": "youtube"})
                self.assertEqual((frame.get("width"), frame.get("height")), (1920, 1080))
        proj = OUT / "project_aspect_slash.json"
        proj.write_text(json.dumps({
            "output": "render_aspect_slash.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:03"}],
            "frame": {"aspect": "16/9"}, "fit": {"aspect": "16:9"},
            "export": {"preset": "youtube"},
        }), encoding="utf-8")
        proc = script("render.py", proj, "--dry-run", "--json")
        self.assertIn("frame: 1920x1080 from the youtube export preset", proc.stderr)
        self.assertTrue(any("--aspect 16:9 --width 1920 --height 1080" in line for line in proc.stderr.splitlines()
                            if "fit.py" in line), proc.stderr[-2000:])

    def test_render_check_content_forwards_the_content_rows(self):
        """`"check": {"content": true}` forwards check.py --content; the default leaves the rows out."""
        rows = {}
        for flag in (True, None):
            proj = OUT / "project_check_content.json"
            chk = {"platform": "custom"}
            if flag:
                chk["content"] = True
            proj.write_text(json.dumps({"output": "render_check_content.mp4",
                                        "clips": [{"src": "source.mp4", "in": 0, "out": 2}], "check": chk}), encoding="utf-8")
            data = json.loads(script("render.py", proj, "--fast", "--json").stdout)
            rows[flag] = {r["check"] for r in data["check"]["checks"]}
        self.assertTrue({"black", "frozen", "silence"} <= rows[True], rows)
        self.assertFalse({"black", "frozen", "silence"} & rows[None], rows)

    def test_delivery_templates_check_written_content_and_allow_project_opt_out(self):
        templates = SCRIPTS.parent / "templates"
        for path in templates.glob("*.json"):
            with self.subTest(template=path.stem):
                self.assertIs(json.loads(path.read_text(encoding="utf-8"))["check"].get("content"), True)

        tmp = tempfile.TemporaryDirectory(dir=OUT)
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        source = tiny_clip(folder / "black.mp4", "color=black:s=160x90:r=30", seconds=3, audio=True)
        output = folder / "checked.mp4"
        args = ("render.py", source, "--template", "youtube", "--fast", "-o", output, "--json")
        dry = json.loads(script(*args, "--dry-run").stdout)
        self.assertFalse(dry["verified"])
        self.assertIsNone(dry["check"])
        skip = next(d for d in dry["diagnostics"]["skipped"] if d["code"] == "check_dry_run")
        self.assertIs(skip["content"], True)
        self.assertFalse(output.exists())

        result = json.loads(script(*args, expect_fail=True).stdout)
        self.assertEqual(result["error"]["kind"], "verification")
        self.assertIn("black", [r["check"] for r in result["check"]["checks"] if r["status"] == "FAIL"])
        self.assertTrue(output.is_file())

        project_file = folder / "project.json"
        script(*args, "--write-project", project_file)
        project = json.loads(project_file.read_text(encoding="utf-8"))
        self.assertIs(project["check"]["content"], True)
        project["check"]["content"] = False
        project["output"] = str(folder / "opt_out.mp4")
        project_file.write_text(json.dumps(project), encoding="utf-8")
        opt_out = json.loads(script("render.py", project_file, "--fast", "--json").stdout)
        self.assertTrue(opt_out["verified"])
        self.assertEqual(opt_out["check"]["platform"], "youtube")
        rows = {row["check"] for row in opt_out["check"]["checks"]}
        self.assertIn("loudness", rows)
        self.assertNotIn("black", rows)

    def test_render_exits_nonzero_when_the_check_stage_fails(self):
        """A render whose deliverable fails its own check stage must not report success."""
        proj = OUT / "project_bad_check.json"
        proj.write_text(json.dumps({
            "output": "render_bad.mp4",
            "clips": [{"src": "source.mp4", "in": "0:01", "out": "0:04"}],
            "export": {"preset": "reels"},  # portrait 9:16 output
            "check": {"platform": "broadcast"},  # broadcast requires 16:9 -- guaranteed aspect FAIL
        }), encoding="utf-8")
        proc = script("render.py", proj, "--fast", "--json", expect_fail=True)
        data = json.loads(proc.stdout)
        self.assertGreater(data["check"]["failed"], 0, data["check"])
        self.assertEqual((data["status"], data["error"]["kind"]), ("failed", "verification"))
        self.assertIn("aspect", data["error"]["message"])
        self.assertTrue(Path(data["output"]).exists(), "the deliverable is still written even though it fails delivery spec")
        # an impossible limit stops the run at its first probe (render's or a stage's: since #415 --timeout bounds
        # probes too), and the message states the limit as given (it said "0 s")
        proc = script("render.py", proj, "--fast", "--timeout", "0.05", "--json", expect_fail=True)
        tdoc = json.loads(proc.stdout)
        self.assertEqual((tdoc["error"]["kind"], tdoc["exit_code"]), ("timeout", 124))
        self.assertIn("0.05 s time limit", tdoc["error"]["message"])
        if platform.system() == "Windows":
            return  # the stand-in below is a #!/bin/sh script
        # the outer --timeout reaches every stage: an ffmpeg that hangs only on the clips stage's
        # output (probes and render's own work run for real) is killed inside cut.py under the
        # forwarded limit ...
        shim = OUT / "render_timeout_shim"
        shim.mkdir(exist_ok=True)
        (shim / "ffmpeg").write_text('#!/bin/sh\nfor a in "$@"; do last="$a"; done\n'
                                     'case "$last" in */clip00*) exec sleep 120;; esac\n'
                                     f'exec "{shutil.which("ffmpeg")}" "$@"\n', encoding="utf-8")
        (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
        proc = script("render.py", proj, "--fast", "--timeout", "8", "--json", expect_fail=True, env=env)
        self.assertIn("time limit", proc.stderr)
        self.assertIn("--timeout 8", proc.stderr, "the flag must be forwarded to the child command line")
        # ...and the stage's own failure is what render reports: kind timeout, exit 124, the stage named
        tdoc = json.loads(proc.stdout)
        self.assertEqual((tdoc["status"], tdoc["error"]["kind"], tdoc["exit_code"], tdoc["stage"]), ("failed", "timeout", 124, "cut.py"))

    def test_write_project_writes_a_project_render_accepts(self):
        """--write-project is the "let me edit it first" path: it must write a project the real
        renderer takes without a single further change, and render nothing itself."""
        proj = OUT / "wp_project.json"
        out = OUT / "wp_out.mp4"
        out.unlink(missing_ok=True)
        doc = json.loads(script("render.py", self.src, "--template", "reels", "--cues", self.cues,
                                "--write-project", proj, "-o", out, "--json").stdout)
        self.assertEqual(doc["output"], str(proj))
        self.assertFalse(out.exists(), "--write-project renders nothing")
        loaded = json.loads(proj.read_text())
        self.assertEqual(loaded["template"], "reels")
        self.assertEqual(loaded["clips"][0]["src"], str(self.src.resolve()))
        plan = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        self.assertEqual(plan["status"], "completed")
        self.assertIn("export", plan["stages"])

    def test_render_result_keys_are_declared_in_the_contract(self):
        """Every key a render result carries is in contract --json's render output_schema (the
        contract is the authority on result fields): a full template run and an early stop."""
        sys.path.insert(0, str(SCRIPTS))
        import _contract
        tool = [t for t in _contract.build(detect=False)["tools"] if t["name"] == "render"][0]
        declared = set(tool["output_schema"]["properties"])
        for extra in ([], ["--stop-after", "fit"]):
            with self.subTest(extra=extra):
                doc = json.loads(script("render.py", self.src, "--template", "reels", "--cues", self.cues,
                                        "-o", OUT / "rk_out.mp4", "--dry-run", "--json", *extra).stdout)
                self.assertEqual(sorted(set(doc) - declared), [])

    def test_render_intermediate_stages_use_veryfast_only_before_an_encoding_export(self):
        """2.15: the x264 stages before an encoding export run at --intermediate-preset (default
        superfast since 2.16): export.py re-encodes them and its own preset sets the delivered quality. Kept
        at the stages' medium when nothing re-encodes after them: --stop-after before the
        export, a copy export, or --intermediate-preset medium. --fast still wins."""
        proj = OUT / "ip_project.json"
        script("render.py", self.src, "--template", "reels", "--cues", self.cues,
               "--write-project", proj, "-o", OUT / "ip_out.mp4", "--json")

        def presets(project, *extra):
            doc = json.loads(script("render.py", project, "--dry-run", "--json", *extra).stdout)
            x264 = [re.search(r"-preset (\S+)", c).group(1) for c in doc["commands"] if "-c:v libx264" in c]
            return doc.get("intermediate_preset"), x264

        used, x264 = presets(proj)
        self.assertEqual(used, "superfast")
        self.assertEqual(x264[-1], "medium", "the export keeps its preset")
        self.assertTrue(x264[:-1] and set(x264[:-1]) == {"superfast"}, x264)
        self.assertEqual(presets(proj, "--intermediate-preset", "medium"), (None, ["medium"] * len(x264)))
        used, x264_fast = presets(proj, "--fast")
        self.assertIsNone(used, "--fast decides every stage's preset, not --intermediate-preset")
        self.assertEqual(set(x264_fast), {"veryfast"})
        doc_stop = json.loads(script("render.py", proj, "--dry-run", "--json", "--stop-after", "captions").stdout)
        self.assertIn("intermediate_preset", doc_stop, "an early stop reports the key too, as null")
        used, x264_stop = presets(proj, "--stop-after", "captions")
        self.assertIsNone(used)
        self.assertEqual(set(x264_stop), {"medium"}, "a --stop-after output is what the caller keeps")
        loaded = json.loads(proj.read_text())
        loaded["export"] = {"preset": "copy"}
        loaded.pop("check", None)
        copy_proj = OUT / "ip_project_copy.json"
        copy_proj.write_text(json.dumps(loaded), encoding="utf-8")
        used, x264_copy = presets(copy_proj)
        self.assertIsNone(used)
        self.assertEqual(set(x264_copy), {"medium"}, "a copy export keeps the stages' encode")
        # a project whose only encode is the export: nothing received the preset, so null
        bare = OUT / "ip_project_bare.json"
        bare.write_text(json.dumps({"clips": [{"src": str(self.src)}], "export": {"preset": "youtube"},
                                    "output": str(OUT / "ip_bare.mp4")}), encoding="utf-8")
        used, x264_bare = presets(bare)
        self.assertIsNone(used, x264_bare)
        # a pack runs one render per destination: each gets the caller's choice
        pack = json.loads(script("render.py", self.src, "--template", "reels,shorts", "--cues", self.cues,
                                 "--intermediate-preset", "medium", "-o", OUT / "ip_pack" / "x.mp4",
                                 "--dry-run", "--json").stdout)
        self.assertEqual(set(re.findall(r"-preset (\w+)", " ".join(pack["commands"]))), {"medium"})

    # --------------------------------------------- 1.17.1: the template path fits the caption size
    def _cw1_cues(self):
        cues = OUT / "cues_cw1.txt"
        cues.write_text("0:00-0:03 A third line the tool times for me\n"
                        "0:03-0:06 Segunda l\u00ednea de subt\u00edtulos\n", encoding="utf-8")
        return cues

    def test_template_captions_shrink_instead_of_splitting(self):
        """1.17.0 filled the caption size from the platform table and forwarded it as an explicit
        --size, which switched off caption.py's --fit-size auto: on the template path -- the path
        every "make this a TikTok" request takes -- long cues were split across two consecutive
        cues instead of shrinking (eval 18 cw1). The template now states fit_size "on"."""
        out = OUT / "tpl_fit.mp4"
        doc = json.loads(script("render.py", self.src, "--template", "tiktok", "--fast",
                                "--cues", self._cw1_cues(), "-o", out, "--json").stdout)
        cap = doc["caption"]
        self.assertEqual(cap["split"], 0, "no cue may be chopped in two on the template path")
        self.assertEqual(cap["fit_size"], "on")
        self.assertEqual(cap["size_requested"], 24)         # the tiktok table's size
        self.assertLess(cap["size_used"], 24, "the size must come down to fit the cue")
        self.assertGreaterEqual(cap["size_used"], cap["size_floor"])
        self.assertGreaterEqual(cap["shrunk"], 1)
        self.assertFalse(cap["fit_exhausted"])
        # honest BECAUSE nothing was split: a split cue now makes text_unchanged false
        self.assertTrue(cap["text_unchanged"])
        self.assertTrue(Path(out).exists())

    def test_template_captions_fit_under_a_brand_that_states_no_size(self):
        """Review 17 finding 1: `--brand` alone is not a stated caption size. A brand file of
        colours states nothing about type, so the platform table's 24 is still the skill's own
        choice and must stay fittable; a brand that names caption.size does state one."""
        brand = OUT / "brand_colours_only.json"
        brand.write_text(json.dumps({"colors": {"text": "FFFFFF"}}), encoding="utf-8")
        proj = OUT / "tpl_brand_colours.json"
        script("render.py", self.src, "--template", "tiktok", "--cues", self._cw1_cues(),
               "--brand", brand, "--write-project", proj, "-o", OUT / "tpl_brand_colours.mp4")
        self.assertEqual(json.loads(proj.read_text(encoding="utf-8"))["captions"]["fit_size"], "on")
        doc = json.loads(script("render.py", self.src, "--template", "tiktok", "--fast",
                                "--cues", self._cw1_cues(), "--brand", brand,
                                "-o", OUT / "tpl_brand_colours.mp4", "--json").stdout)
        cap = doc["caption"]
        self.assertEqual(cap["fit_size"], "on")
        self.assertEqual(cap["split"], 0, "a colours-only brand must not stand the fitter down")
        self.assertLess(cap["size_used"], 24)

        sized = OUT / "brand_with_size.json"
        sized.write_text(json.dumps({"colors": {"text": "FFFFFF"}, "caption": {"size": 22}}),
                         encoding="utf-8")
        proj2 = OUT / "tpl_brand_sized.json"
        script("render.py", self.src, "--template", "tiktok", "--cues", self._cw1_cues(),
               "--brand", sized, "--write-project", proj2, "-o", OUT / "tpl_brand_sized.mp4")
        self.assertNotIn("fit_size", json.loads(proj2.read_text(encoding="utf-8"))["captions"],
                         "a brand-stated caption size is an explicit size: leave it alone")

    def test_project_fit_size_off_renders_1_17_0s_captions(self):
        """The stability answer: a project that states "fit_size": "off" gets exactly the ASS
        1.17.0 wrote -- which is what a project written before 1.17.1 (no fit_size key at all,
        so an explicit --size and no fit) still produces, byte for byte."""
        proj = OUT / "fitoff_project.json"
        script("render.py", self.src, "--template", "tiktok", "--cues", self._cw1_cues(),
               "--write-project", proj, "-o", OUT / "fitoff.mp4")
        loaded = json.loads(proj.read_text(encoding="utf-8"))
        self.assertEqual(loaded["captions"]["fit_size"], "on",
                         "a template-written project states the fit policy it renders with")

        def render_ass(captions, tag):
            work = OUT / f"fitoff_work_{tag}"
            shutil.rmtree(work, ignore_errors=True)
            doc = dict(loaded)
            doc["captions"] = captions
            doc["output"] = str(OUT / f"fitoff_{tag}.mp4")
            path = OUT / f"fitoff_{tag}.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            script("render.py", path, "--fast", "--stop-after", "captions", "--work", work, "--keep")
            return (work / "captioned.ass").read_bytes()

        stated_off = dict(loaded["captions"], fit_size="off")
        legacy = {k: v for k, v in loaded["captions"].items() if k != "fit_size"}
        self.assertEqual(render_ass(stated_off, "off"), render_ass(legacy, "legacy"),
                         '"fit_size": "off" must reproduce the pre-1.17.1 captions byte for byte')
        self.assertNotEqual(render_ass(stated_off, "off2"), render_ass(loaded["captions"], "on"),
                            "the new default has to actually change the ASS, or it fixes nothing")

    def test_project_captions_accept_the_fit_keys(self):
        """eval 18 cs1: a project could not state the fit policy at all ("unknown key
        'fit_size'"), so the agent hand-ran the four stages instead of using render.py."""
        proj = OUT / "fitkeys.json"
        proj.write_text(json.dumps({
            "output": str(OUT / "fitkeys.mp4"),
            "clips": [{"src": str(self.src.resolve()), "in": 0, "out": 4}],
            "captions": {"text": str(self._cw1_cues()), "size": 24, "max_lines": 2,
                         "fit_size": "on", "min_size": 15, "fit_size_scope": "cue"},
        }), encoding="utf-8")
        doc = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        cap = doc["caption"]
        # the project's fit_size_scope reaches caption.py; on this plain SRT burn (one FontSize)
        # the scope applied is the file's, which the result now says instead of "cue" (A67)
        self.assertEqual((cap["fit_size"], cap["size_floor"], cap["fit_scope"]), ("on", 15, "file"))
        self.assertTrue(any("--fit-size-scope cue" in n for n in doc.get("notes") or []), doc.get("notes"))
        self.assertGreaterEqual(cap["size_used"], 15)
        self.assertEqual(cap["split"], 0)

    def test_project_graphics_entry_renders_a_sticker_and_a_meme(self):
        """The three social graphics templates are advertised as usable inside a render.py
        graphics[] entry, and until review 12 the project validator refused their own keys
        (text/top/bottom/duration), so sticker and meme could only be run from the CLI."""
        out = OUT / "gproj_out.mp4"
        proj = OUT / "gproj.json"
        proj.write_text(json.dumps({
            "output": str(out),
            "clips": [{"src": str(self.src.resolve()), "in": 0, "out": 4}],
            "graphics": [
                {"template": "sticker", "text": "NEW", "position": "top-right", "platform": "tiktok"},
                {"template": "meme", "top": "when the render", "bottom": "finally finishes"},
                {"template": "hook", "title": "How I cut this", "duration": 2},
            ]}), encoding="utf-8")
        doc = json.loads(script("render.py", proj, "--fast", "--json").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertIn("graphics", doc["stages"])
        self.assertTrue(out.exists())
        # ink where the meme layout puts it: the two edges of the frame change, and the sticker
        # corner does too -- a validator that accepted the keys but dropped them would not show here
        for crop, y in (("iw:100:0:20", "top"), ("iw:100:0:600", "bottom")):
            before, _ = self._region_stats(self.src, crop, at=1.0)
            after, _ = self._region_stats(out, crop, at=1.0)
            self.assertNotAlmostEqual(before, after, delta=0.5, msg=f"nothing was drawn at the {y}")
        # an unknown key is still a refusal, with the valid ones named
        proj.write_text(json.dumps({"output": str(out), "clips": [{"src": str(self.src.resolve())}],
                                    "graphics": [{"template": "sticker", "caption": "NEW"}]}), encoding="utf-8")
        proc = script("render.py", proj, "--dry-run", "--json", expect_fail=True)
        self.assertIn("unknown key", proc.stderr)

    def test_pack_dry_run_plans_every_command_and_reports_no_result(self):
        """A pack is the one path that writes seven files, so --dry-run has to show all of them --
        and must never report a check result or a file size for a run that encoded nothing (the
        sizes used to be read off files left behind by an earlier real run)."""
        packdir = OUT / "packdry"
        packdir.mkdir(exist_ok=True)
        stale = packdir / "source_tiktok.mp4"
        stale.write_bytes(b"0" * 4096)  # a leftover from an earlier real run
        doc = json.loads(script("render.py", self.src, "--template", "tiktok,podcast",
                                "--cues", self.cues, "--dry-run", "--json",
                                "-o", str(packdir / "ignored.mp4")).stdout)
        self.assertTrue(any("ffmpeg" in c for c in doc["commands"]),
                        "the pack's planned commands are the plan; --dry-run must show them")
        self.assertTrue(any("loudnorm" in c or "libx264" in c for c in doc["commands"]))
        for row in doc["pack"]:
            self.assertEqual(row["check"], "planned", row)
            self.assertIsNone(row["size_bytes"], row)
            self.assertIsNone(row["duration"], row)
        self.assertEqual(stale.stat().st_size, 4096, "a dry run must not touch the files it plans")
        # the audio-only destination of a pack is named like the single-template form: .m4a
        self.assertEqual([Path(r["file"]).suffix for r in doc["pack"]], [".mp4", ".m4a"])
        self.assertFalse((packdir / "source_pack.md").exists(), "a dry run writes no table either")

    def test_brand_defaults_apply_to_caption_and_logo(self):
        brand = OUT / "brand.json"
        if not brand.exists():
            brand.write_text(json.dumps({"font": "DejaVu Sans", "colors": {"primary": "FF6A00", "text": "FFFFFF", "background": "0B1D2A"},
                                         "logo": "logo.png", "logo_position": "top-right", "logo_scale": 140, "safe_margin": 40,
                                         "caption": {"size": 28, "position": "bottom", "animate": "pop", "karaoke": True, "bold": True}}), encoding="utf-8")
        ass = OUT / "brand.ass"
        script("caption.py", self.src, "--text", self.cues, "--brand", brand, "--write-ass", ass, "--fast", "-o", OUT / "brand_cap.mp4")
        style = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Style:")][0]
        self.assertIn("&H00006AFF", style, "primary FF6A00 becomes the karaoke fill (BGR)")
        self.assertIn(",70,", style, "size 28 scaled to 720p")
        self.assertIn("\\kf", ass.read_text(encoding="utf-8-sig"), "brand enables karaoke")
        proc = script("overlay.py", self.src, "--logo", "--brand", brand, "--fast", "-o", OUT / "brand_logo.mp4")
        self.assertIn("scale=140:-1", proc.stderr)
        # top-right at the brand's safe margin, W-w-40:40, which overlay.py resolves to a pixel (#512)
        self.assertIn(f"overlay={probe(str(self.src))['video']['width'] - 140 - 40}:40", proc.stderr)
        script("overlay.py", self.src, "--logo", expect_fail=True)

    # ---------------------------------------------------------------- v0.7: MCP server / batch / ASR bridge
    def test_mcp_server_stdio(self):
        server = ROOT / "mcp" / "server.py"
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "probe", "arguments": {"inputs": [str(self.src)]}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "cut", "arguments": {"input": str(self.src), "start": 1, "end": 3, "output": str(OUT / "mcp_cut.mp4")}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "cut", "arguments": {"argv": [str(self.src), "--start", "0", "--end", "2", "-o", str(OUT / "mcp_cut2.mp4")]}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "bogus/method"},
        ]
        # FFMPEG_SKILL_MCP_FULL=1: this test is about the stdio wiring (initialize / tools/list /
        # tools/call / unknown name / unknown method), not the core-12-by-default filter, which
        # has its own tests in tests/test_contract.py.
        env = {**os.environ, "FFMPEG_SKILL_MCP_FULL": "1"}
        proc = subprocess.run([sys.executable, str(server)], input="\n".join(json.dumps(r) for r in reqs) + "\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resp = {r["id"]: r for r in (json.loads(l) for l in proc.stdout.splitlines() if l.strip())}
        self.assertEqual(resp[1]["result"]["serverInfo"]["name"], "ffmpeg-skill")
        names = {t["name"] for t in resp[2]["result"]["tools"]}
        self.assertTrue({"probe", "cut", "render", "check", "scenes", "batch"} <= names or {"probe", "cut", "render", "check", "scenes"} <= names)
        self.assertEqual(resp[3]["result"]["structuredContent"]["duration"], 12.0)
        self.assertClose(resp[4]["result"]["structuredContent"]["probe"]["duration"], 2.0, 0.6)
        self.assertTrue(Path(resp[5]["result"]["structuredContent"]["output"]).exists())
        self.assertTrue(resp[6]["result"].get("isError"))
        self.assertEqual(resp[7]["error"]["code"], -32601)

    def test_mcp_server_survives_a_non_object_json_line(self):
        """json.loads accepts any valid JSON value, not just an object -- a bare `42`, `null`,
        `true` or `[1,2]` line parses without raising, but main()'s very next line, `"id" not in
        req`, raised an uncaught TypeError for a non-dict req (an int/bool/None isn't iterable the
        way `in` needs). That check sat outside the try/except wrapping handle(), so the exception
        propagated out of the stdin loop and killed the whole stdio server process -- not just
        that one malformed line, but every other in-flight and future tool call in the session.
        Verify a line like this is now skipped, and the server stays alive and answers the next
        (valid) request instead of exiting non-zero with nothing produced for it."""
        server = ROOT / "mcp" / "server.py"
        lines = ["42", "null", "true", "[1,2,3]",
                 json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})]
        proc = subprocess.run([sys.executable, str(server)], input="\n".join(lines) + "\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, f"server must not crash on non-object JSON lines; stderr: {proc.stderr}")
        resp = [json.loads(response_line) for response_line in proc.stdout.splitlines() if response_line.strip()]
        self.assertEqual(len(resp), 1, "only the one real request should get a response")
        self.assertEqual(resp[0]["id"], 1)
        self.assertIn("tools", resp[0]["result"])

    # ------------------------------------------------------------- 1.17: batch.py --jobs N
    def _jobs_folder(self, name, count=4):
        folder = OUT / name
        folder.mkdir(exist_ok=True)
        for i in range(count):
            (folder / f"j{i}.mp4").write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({
            "glob": "*.mp4", "output_dir": "out", "suffix": "_j",
            "steps": [["fit.py", "{in}", "--duration", "3", "--method", "speed", "-o", "{out}"]]}))
        return folder, recipe

    def test_jobs_summary_is_identical_to_serial(self):
        """The per-item table is the promise: same order, same keys, whatever order the encodes
        actually finished in."""
        folder, recipe = self._jobs_folder("batch_jobs_a")
        serial = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                   "--force", "--jobs", "1", "--json").stdout)
        parallel = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                     "--force", "--jobs", "4", "--json").stdout)
        self.assertEqual(serial["jobs"], 1)
        self.assertGreater(parallel["jobs"], 1)
        self.assertEqual(len(serial["results"]), len(parallel["results"]))
        for a, b in zip(serial["results"], parallel["results"]):
            self.assertEqual({k: v for k, v in a.items() if k != "seconds"},
                             {k: v for k, v in b.items() if k != "seconds"})
        self.assertEqual(serial["processed"], parallel["processed"])
        self.assertFalse(parallel["timed_out"])
        self.assertGreater(parallel["item_seconds_total"], 0)

    def test_results_keep_file_order_with_a_partially_warm_cache(self):
        """Cached hits were appended in one pass and freshly-processed items after them, so the
        per-item table came back out of file order whenever the cache was partially warm -- at
        --jobs 1, the default, not only in parallel."""
        for jobs in ("1", "3"):
            with self.subTest(jobs=jobs):
                folder = OUT / f"batch_order_{jobs}"
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                for name in ("a.mp4", "b.mp4", "c.mp4"):
                    (folder / name).write_bytes(Path(self.src).read_bytes())
                recipe = folder / "batch.json"
                recipe.write_text(json.dumps({
                    "glob": "*.mp4", "output_dir": "out", "suffix": "_o",
                    "steps": [["fit.py", "{in}", "--duration", "3", "--method", "speed", "-o", "{out}"]]}))
                first = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                          "--jobs", jobs, "--json").stdout)
                self.assertEqual([Path(r["file"]).name for r in first["results"]],
                                 ["a.mp4", "b.mp4", "c.mp4"])
                # warm the cache for a and c only: delete b's output so it must be redone
                Path(first["results"][1]["output"]).unlink()
                second = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                           "--jobs", jobs, "--json").stdout)
                self.assertEqual([Path(r["file"]).name for r in second["results"]],
                                 ["a.mp4", "b.mp4", "c.mp4"])
                self.assertTrue(second["results"][0].get("cached"))
                self.assertFalse(second["results"][1].get("cached"))
                self.assertTrue(second["results"][2].get("cached"))

    def test_a_worker_that_raises_becomes_a_failed_row_not_a_dead_run(self):
        """A die() inside a worker thread raised SystemExit through fut.result() and took the
        process down before the summary and the table were printed. The one thing the user needs
        -- which item failed and which succeeded -- was the thing they did not get."""
        folder = OUT / "batch_worker_raise"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        for name in ("ok1.mp4", "ok2.mp4", "ok3.mp4", "ok4.mp4"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        # a step that fails on every item: the run must still report all four rows
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({
            "glob": "*.mp4", "output_dir": "out", "suffix": "_w",
            "steps": [["cut.py", "{in}", "--start", "99", "--end", "120", "-o", "{out}"]]}))
        r = script("batch.py", folder, "--recipe", recipe, "--fast", "--jobs", "2",
                   "--json", expect_fail=True)
        data = json.loads(r.stdout)
        self.assertEqual(len(data["results"]), 4)
        self.assertEqual([Path(x["file"]).name for x in data["results"]],
                         ["ok1.mp4", "ok2.mp4", "ok3.mp4", "ok4.mp4"])
        self.assertTrue(all(not x["ok"] for x in data["results"]))
        self.assertEqual(data["error"]["kind"], "verification")

    def test_jobs_is_capped_by_cpu_count(self):
        folder, recipe = self._jobs_folder("batch_jobs_cap", count=2)
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                 "--jobs", "999", "--json").stdout)
        self.assertEqual(data["jobs_requested"], 999)
        self.assertLessEqual(data["jobs"], min(os.cpu_count() or 1, 8))
        self.assertGreaterEqual(data["jobs"], 1)

    def test_jobs_auto_resolves_to_a_number(self):
        folder, recipe = self._jobs_folder("batch_jobs_auto", count=2)
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                 "--jobs", "auto", "--json").stdout)
        self.assertLessEqual(data["jobs"], min(os.cpu_count() or 1, 4))

    def test_jobs_rejects_a_non_number(self):
        folder, recipe = self._jobs_folder("batch_jobs_bad", count=1)
        r = script("batch.py", folder, "--recipe", recipe, "--fast", "--jobs", "lots",
                   "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "input")

    def test_jobs_share_one_timeout_budget(self):
        """--timeout is the batch's limit, not each item's: a queue of files cannot quietly take
        one timeout each.

        The budget is a few milliseconds, so it has certainly expired by the time the first item
        would be submitted -- the probe, the silence/collision pre-flight and the cache read all
        run before it. That makes the test a statement about the deadline logic rather than a
        race between --timeout and however fast this machine encodes: the previous version gave
        six real encodes one second and passed only when the machine was slow enough.
        """
        for jobs in ("1", "2"):
            with self.subTest(jobs=jobs):
                folder, recipe = self._jobs_folder(f"batch_jobs_timeout_{jobs}", count=6)
                r = script("batch.py", folder, "--recipe", recipe, "--timeout", "0.005",
                           "--force", "--jobs", jobs, "--json", expect_fail=True)
                data = json.loads(r.stdout)
                self.assertEqual(data["error"]["kind"], "timeout")
                self.assertEqual(data["exit_code"], 124)
                self.assertTrue(data["timed_out"])
                skipped = [x for x in data["results"] if x.get("skipped") == "timeout"]
                self.assertTrue(skipped)
                # every item is still in the table, in file order, none of them claiming success
                self.assertEqual(len(data["results"]), 6)
                self.assertEqual([Path(x["file"]).name for x in data["results"]],
                                 sorted(Path(x["file"]).name for x in data["results"]))
                self.assertFalse(any(x["ok"] for x in skipped))

    def test_a_stated_timeout_is_the_batchs_budget_but_the_default_is_not(self):
        """The shared deadline applies when a --timeout was stated, or when --jobs > 1 asked for
        the batch to be treated as one piece of work. The default sequential path keeps 1.16's
        per-item ceiling, so a long folder is never cut off part-way by a flag nobody passed."""
        folder, recipe = self._jobs_folder("batch_default_budget", count=2)
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                 "--force", "--json").stdout)
        self.assertEqual(data["processed"], 2)
        self.assertFalse(data["timed_out"])

    def test_jobs_cache_entries_survive_concurrency(self):
        folder, recipe = self._jobs_folder("batch_jobs_cache", count=6)
        first = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--force",
                                  "--jobs", "4", "--json").stdout)
        self.assertEqual(first["processed"], 6)
        again = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast",
                                  "--jobs", "4", "--json").stdout)
        self.assertTrue(all(x.get("cached") for x in again["results"]),
                        "every entry written under concurrency must be served back")

    def test_jobs_gives_each_item_its_own_work_dir(self):
        """Each item works in a directory of its own, serial or parallel, and takes it with it
        when it ends (3.1.6, #415: 1.17's flat serial layout let two items with one stem, or a
        rerun, refuse each other's intermediates)."""
        folder, recipe = self._jobs_folder("batch_jobs_work", count=3)
        for jobs in ("3", "1"):
            work = OUT / f"batch_jobs_work_dir{jobs}"
            shutil.rmtree(work, ignore_errors=True)
            script("batch.py", folder, "--recipe", recipe, "--fast", "--force", "--jobs", jobs, "--work", work)
            self.assertEqual(list(work.iterdir()), [], "every item's directory is removed with it")


    # --------------------------------------------------- 1.17: render.py --cache DIR / --from
    def _cache_project(self, name, preset="x"):
        proj = OUT / f"{name}.json"
        proj.write_text(json.dumps({
            "output": str(OUT / f"{name}_out.mp4"),
            "clips": [{"src": str(self.src), "in": 0, "out": 3}],
            "export": {"preset": preset}}), encoding="utf-8")
        return proj

    def test_render_cache_hit_skips_the_encode(self):
        cdir = OUT / "rcache_hit"
        shutil.rmtree(cdir, ignore_errors=True)
        cdir.mkdir()
        sentinel = cdir / ".writable"
        sentinel.write_text("keep this file", encoding="utf-8")
        proj = self._cache_project("cache_hit")
        first = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertEqual(first["cache"]["hits"], [])
        self.assertGreater(len(first["commands"]), 0)
        second = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertIn("export", second["cache"]["hits"])
        self.assertEqual(second["cache"]["misses"], [])
        self.assertEqual(second["commands"], [])
        self.assertEqual(second["stages"], first["stages"])   # a cached stage still happened
        self.assertTrue(Path(second["output"]).exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep this file")
        dry = json.loads(script("render.py", proj, "--cache", cdir, "--overwrite",
                                "--dry-run", "--json").stdout)
        self.assertIn("clips", dry["cache"]["would_hit"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep this file")

    def test_render_cache_misses_when_a_stage_arg_changes(self):
        cdir = OUT / "rcache_arg"
        shutil.rmtree(cdir, ignore_errors=True)
        script("render.py", self._cache_project("cache_arg"), "--cache", cdir)
        changed = json.loads(script("render.py", self._cache_project("cache_arg", preset="reels"),
                                    "--cache", cdir, "--json").stdout)
        self.assertIn("clips", changed["cache"]["hits"])      # earlier stage unchanged
        self.assertIn("export", changed["cache"]["misses"])   # the one that changed re-runs

    def test_render_cache_key_never_crosses_an_ffmpeg_or_skill_version(self):
        """The version lines are IN the key: a different build misses rather than being asked to
        trust an artifact it did not write."""
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        render = importlib.import_module("render")
        argv = ["in.mp4", "-o", "out.mp4", "--preset", "x"]
        render.CACHE["ffmpeg"] = "7.1"
        a = render.cache_key("export", "export.py", argv, [])
        render.CACHE["ffmpeg"] = "5.1"
        b = render.cache_key("export", "export.py", argv, [])
        self.assertNotEqual(a, b)
        render.CACHE["ffmpeg"] = "7.1"
        self.assertEqual(render.cache_key("export", "export.py", argv, []), a)
        self.assertNotEqual(a, render.cache_key("export", "export.py", argv + ["--crf", "20"], []))

    def test_render_cache_never_serves_a_fast_draft_as_the_delivery(self):
        """--fast rewrites every child's preset to veryfast, and child_args() appends it AFTER
        the arguments the stage built -- so it was outside the key. A cached draft was handed
        back to a run that did not ask for a draft, with cache.hits calling it a legitimate
        reuse."""
        cdir = OUT / "rcache_fast"
        shutil.rmtree(cdir, ignore_errors=True)
        proj = self._cache_project("cache_fast")
        draft = json.loads(script("render.py", proj, "--cache", cdir, "--fast",
                                  "--json").stdout)
        self.assertEqual(draft["cache"]["hits"], [])
        final = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertEqual(final["cache"]["hits"], [],
                         "a --fast draft must not be served to a run that did not ask for one")
        self.assertGreater(len(final["commands"]), 0)
        # ... and asking for the draft again does hit
        again = json.loads(script("render.py", proj, "--cache", cdir, "--fast", "--json").stdout)
        self.assertTrue(again["cache"]["hits"])

    def test_render_cache_key_covers_the_ffmpeg_build_and_the_container(self):
        sys.path.insert(0, str(SCRIPTS))
        import importlib
        render = importlib.import_module("render")
        argv = ["in.mp4", "-o", "<out>", "--preset", "x"]
        base = render.cache_key("export", "export.py", argv, [], "out.mp4")
        self.assertNotEqual(base, render.cache_key("export", "export.py", argv, [], "out.mkv"),
                            "the container is part of what the stage produces")
        # the banner, not major.minor: two 7.1.x builds differ in it
        self.assertRegex(render.ffmpeg_banner(), r"version")
        saved = render.CACHE.get("ffmpeg")
        try:
            render.CACHE["ffmpeg"] = "ffprobe version 7.1.1-0ubuntu1"
            a = render.cache_key("export", "export.py", argv, [], "out.mp4")
            render.CACHE["ffmpeg"] = "ffprobe version 7.1.2-0ubuntu1"
            self.assertNotEqual(a, render.cache_key("export", "export.py", argv, [], "out.mp4"))
        finally:
            render.CACHE["ffmpeg"] = saved

    def test_render_cache_writes_nothing_under_dry_run(self):
        cdir = OUT / "rcache_dry"
        shutil.rmtree(cdir, ignore_errors=True)
        data = json.loads(script("render.py", self._cache_project("cache_dry"), "--cache", cdir,
                                 "--dry-run", "--json").stdout)
        self.assertFalse(cdir.exists())
        self.assertIn("cache", data)

        cdir.mkdir()
        sentinel = cdir / ".writable"
        sentinel.write_text("keep this file", encoding="utf-8")
        script("render.py", self._cache_project("cache_dry"), "--cache", cdir, "--dry-run", "--json")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep this file")

    def test_render_failure_with_a_cache_leaves_no_work_dir_and_caches_nothing(self):
        """The failure path of --cache, which the happy-path tests do not reach: a stage that
        fails must not leave its work directory behind, and must never put the partial artifact
        in the cache where a later run would be served it as a finished stage."""
        cdir = OUT / "rcache_fail"
        shutil.rmtree(cdir, ignore_errors=True)
        proj = self._cache_project("cache_fail")
        r = script("render.py", proj, "--cache", cdir, "--timeout", "0.05", "--json", expect_fail=True)
        self.assertEqual(json.loads(r.stdout)["error"]["kind"], "timeout")
        self.assertEqual(sorted(p.name for p in cdir.iterdir()), [],
                         "a failed stage must not be cached")
        self.assertEqual([p.name for p in OUT.glob("cache_fail_out*_work_*")], [],
                         "the work directory is removed on the failure path too")
        self.assertFalse((OUT / "cache_fail_out.mp4").exists())
        # and the cache is still usable afterwards: the next (untimed) run fills it normally
        ok = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
        self.assertEqual(ok["cache"]["hits"], [])
        self.assertTrue(list(cdir.glob("*.json")))

    def test_render_from_without_a_cache_refuses(self):
        r = script("render.py", self._cache_project("cache_from"), "--from", "captions",
                   "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("--cache", err["message"])

    def test_render_from_refuses_when_an_earlier_stage_is_not_cached(self):
        cdir = OUT / "rcache_from_empty"
        shutil.rmtree(cdir, ignore_errors=True)
        r = script("render.py", self._cache_project("cache_from2"), "--cache", cdir,
                   "--from", "export", "--json", expect_fail=True)
        err = json.loads(r.stdout)["error"]
        self.assertEqual(err["kind"], "input")
        self.assertIn("clips", err["message"])

    def test_render_without_cache_is_unchanged(self):
        data = json.loads(script("render.py", self._cache_project("cache_none"),
                                 "--dry-run", "--json").stdout)
        self.assertIsNone(data.get("cache"))


    def test_batch_recipe_and_cache(self):
        folder = OUT / "batch_in"
        folder.mkdir(exist_ok=True)
        for name in ("a.mp4", "b.mp4"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_final",
                                      "steps": [["fit.py", "{in}", "--duration", "5", "--method", "speed", "-o", "{out}"], ["export.py", "{in}", "--preset", "x", "-o", "{out}"]]}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertEqual(data["processed"], 2)
        self.assertFalse(any(r.get("cached") for r in data["results"]))
        for r in data["results"]:
            m = probe(r["output"])
            self.assertClose(m["duration"], 5.0, 0.3)
            self.assertEqual(m["video"]["width"], 1280)
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertTrue(all(r.get("cached") for r in data["results"]), "second run served from cache")
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--force", "--json").stdout)
        self.assertFalse(any(r.get("cached") for r in data["results"]))
        # project-based recipe
        proj = folder / "p.json"
        proj.write_text(json.dumps({"clips": [{"src": "x", "in": 0, "out": 3}], "export": {"preset": "x"}}))
        recipe2 = folder / "batch2.json"
        recipe2.write_text(json.dumps({"glob": "a.mp4", "output_dir": "out2", "suffix": "_p", "project": "p.json"}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe2, "--fast", "--json").stdout)
        self.assertEqual(data["processed"], 1)
        self.assertClose(probe(data["results"][0]["output"])["duration"], 3.0, 0.3)

    def test_batch_reports_cuts_stream_copy_vs_hybrid_rate_across_the_folder(self):
        """cut.py's own `reencoded` (mode "copy" vs the tolerance-triggered hybrid re-encode
        fallback -- ORed across every range of a --segments call into one top-level field, since
        cut.py doesn't say which range needed it) was never surfaced anywhere batch.py's caller
        could see without re-deriving it from every step's own stdout. run_step() now forces
        --json on every step (a step's own stdout was never read for anything but the log before;
        only the output path computed by process() itself was used to chain steps) so process()
        can read cut.py's `reencoded` back, and batch.py rolls it up into one `cut_stream_copy`
        summary: how many of the cut.py calls this run made landed on the fast lossless path
        versus fell back to a re-encode on at least one range."""
        folder = OUT / "batch_cut_stats"
        folder.mkdir(exist_ok=True)
        for name in ("a.mp4", "b.mp4"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        # step 0 misses the tight tolerance and must fall back to hybrid (same fixture behaviour
        # test_cut_json_reports_requested_vs_actual_and_mode already pins); step 1 re-cuts that
        # fresh re-encode's own start, which is always its own keyframe, so it stream-copies.
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_cut",
                                      "steps": [["cut.py", "{in}", "--start", "1.13", "--end", "5.71",
                                                 "--tolerance", "0.02", "-o", "{out}"],
                                                ["cut.py", "{in}", "--start", "0", "--end", "2",
                                                 "--tolerance", "-1", "-o", "{out}"]]}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertEqual(data["processed"], 2)
        for r in data["results"]:
            self.assertEqual(r["cut_reencoded"], [True, False])
        summary = data["cut_stream_copy"]
        self.assertEqual(summary, {"calls": 4, "stream_copy": 2, "reencoded": 2, "stream_copy_rate": 0.5})
        # #510: a dry run counts the calls' plans, and its summary line does not call a planned copy
        # one that stayed lossless (the real run above re-encoded the first step's)
        proc = script("batch.py", folder, "--recipe", recipe, "--fast", "--json", "--dry-run", "--force")
        self.assertEqual(json.loads(proc.stdout)["cut_stream_copy"]["stream_copy"], 4)
        self.assertNotIn("stayed fully lossless", proc.stderr)
        self.assertIn("which a real run may still re-encode", proc.stderr)
        # second review of #537: the line points at a per-call field the rows carry
        for row in json.loads(proc.stdout)["results"]:
            self.assertEqual(len(row["cut_possible_reencode_reason"]), 2, row)
            self.assertIn("tolerance", row["cut_possible_reencode_reason"][0])

        # a recipe with no cut.py step reports nothing -- the key isn't invented from nowhere
        recipe2 = folder / "batch_no_cut.json"
        recipe2.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out2", "suffix": "_nc",
                                       "steps": [["fit.py", "{in}", "--duration", "3", "--method", "speed", "-o", "{out}"]]}))
        data2 = json.loads(script("batch.py", folder, "--recipe", recipe2, "--fast", "--json").stdout)
        self.assertIsNone(data2["cut_stream_copy"])
        self.assertNotIn("cut_reencoded", data2["results"][0])

    def test_batch_counts_cut_reencode_reasons_beside_the_stream_copy_rate(self):
        """cut.py's `reencode_reason` reaches batch.py's caller without changing cut_stream_copy:
        each results row lists the reasons its cut.py calls named (once per call), and the
        top-level cut_reencode_reasons counts them across the folder (null when no cut.py step
        ran)."""
        folder = OUT / "batch_cut_reasons"
        folder.mkdir(exist_ok=True)
        # this test edits the cache below, so a rerun starts without one
        (folder / "out" / ".ffskill_cache.json").unlink(missing_ok=True)
        (folder / "a.mp4").write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        # the same two steps as the stream-copy rate test: a tolerance re-encode, then a copy
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out", "suffix": "_cut",
                                      "steps": [["cut.py", "{in}", "--start", "1.13", "--end", "5.71",
                                                 "--tolerance", "0.02", "-o", "{out}"],
                                                ["cut.py", "{in}", "--start", "0", "--end", "2",
                                                 "--tolerance", "-1", "-o", "{out}"]]}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertEqual(data["results"][0]["cut_reencoded"], [True, False])
        self.assertEqual(data["results"][0]["cut_reencode_reasons"], ["tolerance"])
        self.assertEqual(data["cut_reencode_reasons"], {"tolerance": 1})
        self.assertNotIn("reencode_reasons", data["cut_stream_copy"], "cut_stream_copy keeps its 2.x shape")
        # a row served from a cache an earlier 2.x batch wrote has cut_reencoded but no reasons:
        # its re-encoded call counts as "unknown", never as {} ("none re-encoded")
        cache_path = folder / "out" / ".ffskill_cache.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        for row in cache.values():
            row.pop("cut_reencode_reasons", None)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        cached = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertTrue(cached["results"][0]["cached"])
        self.assertEqual(cached["cut_stream_copy"]["reencoded"], 1)
        self.assertEqual(cached["cut_reencode_reasons"], {"unknown": 1})
        recipe2 = folder / "batch_no_cut.json"
        recipe2.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out2", "suffix": "_nc",
                                       "steps": [["fit.py", "{in}", "--duration", "3", "--method", "speed", "-o", "{out}"]]}))
        data2 = json.loads(script("batch.py", folder, "--recipe", recipe2, "--dry-run", "--json").stdout)
        self.assertIsNone(data2["cut_reencode_reasons"])
        self.assertIsNone(data2["cut_stream_copy"])

    def test_batch_project_recipe_cache_invalidates_on_project_json_content_change(self):
        """A "project" recipe is just {"project": "<path>", "clip_key": N} -- the real settings
        (export preset, captions, everything) live in the file at that path. The cache key used
        to hash only this outer recipe dict, so editing project.json's content (export preset
        swapped from "copy" to "x", a real re-encode) without touching batch.json itself left the
        key unchanged, and the stale cached output was served for the new settings with no error
        or warning. Verify a content-only change to project.json invalidates the cache."""
        folder = OUT / "batch_project_cache"
        folder.mkdir(exist_ok=True)
        (folder / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        proj = folder / "p.json"
        proj.write_text(json.dumps({"clips": [{}], "export": {"preset": "copy"}}))
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "clip.mp4", "output_dir": "out", "project": "p.json"}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertFalse(data["results"][0].get("cached"))
        proj.write_text(json.dumps({"clips": [{}], "export": {"preset": "x"}}))
        data = json.loads(script("batch.py", folder, "--recipe", recipe, "--fast", "--json").stdout)
        self.assertFalse(data["results"][0].get("cached"), "a content-only project.json change must not be served from a stale cache")

    def test_batch_cache_write_is_atomic_no_leftover_temp_file(self):
        """The cache file used to be written with a plain write_text(), which is not atomic -- a
        process killed mid-write leaves a truncated file that the next run's json.loads() treats
        as corrupt and silently discards (every prior cache entry lost, not just the interrupted
        one). Now written via a sibling temp file + os.replace(). Verify a normal run leaves the
        cache file valid and no stray .tmp<pid> file behind."""
        folder = OUT / "batch_cache_atomic"
        folder.mkdir(exist_ok=True)
        (folder / "clip.mp4").write_bytes(Path(self.src).read_bytes())
        recipe = folder / "batch.json"
        recipe.write_text(json.dumps({"glob": "clip.mp4", "output_dir": "out", "steps": [["export.py", "{in}", "--preset", "copy", "-o", "{out}"]]}))
        script("batch.py", folder, "--recipe", recipe, "--fast")
        outdir = folder / "out"
        cache_path = outdir / ".ffskill_cache.json"
        self.assertTrue(cache_path.exists())
        json.loads(cache_path.read_text(encoding="utf-8"))  # must not be truncated/corrupt
        leftover = list(outdir.glob(".ffskill_cache.json.tmp*"))
        self.assertEqual(leftover, [], f"temp cache file(s) left behind: {leftover}")

    def test_batch_refuses_a_recipe_step_naming_a_script_outside_scripts_dir(self):
        """run_step() built its command as `HERE / argv[0]`, where argv[0] came straight from an
        untrusted recipe JSON step. Path's / operator silently ignores the left side when the
        right side is itself an absolute path, and does nothing to stop a "../" traversal either
        -- so a recipe (from a template, a shared config, anywhere the caller didn't author it
        themselves) naming an absolute or ../-relative path got that file executed as a Python
        script, with the caller's own privileges, once per matching media file. Verify both an
        absolute path and a traversal path are refused instead of executed."""
        folder = OUT / "batch_security"
        folder.mkdir(exist_ok=True)
        (folder / "a.mp4").write_bytes(Path(self.src).read_bytes())
        evil = OUT / "batch_security_evil.py"
        marker = OUT / "batch_security_pwned.txt"
        marker.unlink(missing_ok=True)
        evil.write_text(f"open({str(marker)!r}, 'w').write('pwned')\n", encoding="utf-8")

        for step in ([str(evil)], ["../../../../tmp/does_not_matter.py"]):
            recipe = folder / "batch.json"
            recipe.write_text(json.dumps({"glob": "*.mp4", "steps": [step]}))
            proc = script("batch.py", folder, "--recipe", recipe, "--fast", "--force", expect_fail=True)
            self.assertIn("scripts/", proc.stderr)
            self.assertFalse(marker.exists(), f"step {step} must not have executed")

    def test_batch_refuses_a_fixed_ext_recipe_that_collapses_two_sources_to_one_output(self):
        """final_path() falls back to each source's OWN extension by default, so files that only
        differ by extension don't collide -- but a recipe with a fixed "ext" (e.g. converting a
        folder of mixed .mp4/.mov masters to one format) makes two sources with the same stem
        (clip.mp4 and clip.mov) resolve to the identical final path (clip_out.mp4). process() had
        no collision detection: the file processed later in sorted() order used to silently
        overwrite the earlier one's finished output, with the cache still recording both entries
        as ok. Verify this is now refused up front, before either file is processed, rather than
        one silently clobbering the other."""
        folder = OUT / "batch_collision_in"
        folder.mkdir(exist_ok=True)
        for name in ("clip.mp4", "clip.mov"):
            (folder / name).write_bytes(Path(self.src).read_bytes())
        recipe = folder / "collide.json"
        recipe.write_text(json.dumps({"ext": "mp4", "steps": [["export.py", "{in}", "--preset", "x", "-o", "{out}"]]}))
        proc = script("batch.py", folder, "--recipe", recipe, "--fast", expect_fail=True)
        self.assertIn("collision", proc.stderr)
        self.assertIn("clip.mp4", proc.stderr)
        self.assertIn("clip.mov", proc.stderr)
        self.assertFalse((folder / "out" / "clip_out.mp4").exists(), "nothing should be written once a collision is detected")

    # ---------------------------------------------------------------- _common
    def test_context_is_attribute_only_and_resets(self):
        """Context once carried dict-style shims for older call sites; every site uses attributes
        now and the shims are gone, so a stray STATE["x"] is a TypeError at the call site rather
        than a second, silently-diverging access path. __slots__ also refuses unknown names."""
        from _common import Context
        ctx = Context()
        ctx.dry_run = True
        ctx.fast = True
        self.assertTrue(ctx.dry_run and ctx.fast)
        self.assertIsNone(ctx.duration_hint)
        with self.assertRaises(TypeError):
            ctx["dry_run"]  # noqa: B018 -- the mapping shim is gone on purpose
        with self.assertRaises(AttributeError):
            ctx.nonexistent = 1
        ctx.commands.append("x")
        ctx.reset()
        self.assertEqual((ctx.dry_run, ctx.fast, ctx.commands), (False, False, []))

    def test_run_records_commands_on_a_passed_context_not_the_global_state(self):
        """1.10 threads an optional `ctx=` through run()/emit()/die() (issue #189 B; 2.0 makes it
        required). A fresh Context() must collect that call's commands itself and leave the
        process-global STATE untouched, which is the property the 2.0 signature change relies on."""
        import _common
        ctx = _common.Context()
        ctx.dry_run = True
        before = list(_common.STATE.commands)
        proc = _common.run(["ffmpeg", "-i", "in.mp4", "out.mp4"], quiet=True, ctx=ctx)
        self.assertEqual(proc.returncode, 0, "a dry run plans without executing ffmpeg")
        self.assertEqual(ctx.commands, ["ffmpeg -i in.mp4 out.mp4"])
        self.assertEqual(_common.STATE.commands, before, "the global STATE must not have seen this call")

    def test_skill_md_stays_within_the_agent_reading_budget(self):
        """1.11.0: SKILL.md is the file every session loads, so its size is a real per-run cost.
        The two-tier split (long-form prose in references/gotchas.md, one line plus an anchor
        here) brought it from 362 lines / 37.8 KB to under this ceiling; a new rule belongs in a
        references/ file with a one-line pointer, not in an ever-growing SKILL.md."""
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        lines, size = len(text.splitlines()), len(text.encode("utf-8"))
        self.assertLessEqual(lines, 220, f"SKILL.md is {lines} lines; move detail to references/")
        self.assertLessEqual(size, 30000, f"SKILL.md is {size} bytes; move detail to references/")
        gotchas = (ROOT / "references" / "gotchas.md").read_text(encoding="utf-8")
        # every "details:" pointer resolves to a real heading in the file it names
        for anchor in re.findall(r"references/gotchas\.md#([a-z0-9-]+)", text):
            headings = ["".join(ch for ch in h.lower().replace(" ", "-") if ch.isalnum() or ch == "-")
                        for h in re.findall(r"(?m)^#+ (.+)$", gotchas)]
            self.assertIn(anchor, headings, f"SKILL.md points at references/gotchas.md#{anchor}, which has no such heading")

    def test_every_script_has_help(self):
        for name in sorted(p.name for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")):
            with self.subTest(script=name):
                out = script(name, "--help").stdout
                self.assertIn("usage:", out)


class DemoGalleryTests(unittest.TestCase):
    """The gallery in docs/demos.md is committed, so its builder is a shipped artefact: if
    demos/build.py stops rendering, the README's pictures quietly describe an older tool.

    One cheap demo is enough to prove the whole path -- fixtures, a real script invocation, the
    side-by-side, the preview and the size budget -- without spending several minutes of CI on all
    of them (the `demos` job in demos/CI.md runs the full set)."""

    def test_build_one_demo_and_stay_under_the_preview_budget(self):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        from _common import script_font_status
        if script_font_status("ja") == "missing":
            # Not a failure: the demo itself skips for the same reason. A machine with no CJK
            # font cannot render Japanese captions, and a tofu-filled GIF would be worse than none.
            raise unittest.SkipTest("no font on this machine covers Japanese: captions_ja cannot render")
        preview = ROOT / "docs" / "demos" / "captions_ja.gif"
        before = preview.read_bytes() if preview.exists() else None
        try:
            sh(sys.executable, ROOT / "demos" / "build.py", "--only", "captions_ja")
            self.assertTrue(preview.exists(), f"{preview} was not written")
            size = preview.stat().st_size
            self.assertLessEqual(size, 500 * 1024,
                                 f"{preview.name} is {size} bytes; previews are committed and "
                                 f"capped at 500 KB (demos/build.py enforces this too)")
            self.assertGreater(size, 1024, "a preview that small did not render anything")
            for name in ("captions_ja_before.mp4", "captions_ja_after.mp4", "captions_ja.mp4"):
                self.assertTrue((ROOT / "demos" / "out" / name).exists(), f"demos/out/{name} missing")
        finally:
            # Leave the committed preview exactly as it was: this machine's ffmpeg writes
            # different GIF bytes than the one that built the gallery, and a test must not
            # dirty the working tree it ran in.
            if before is not None:
                preview.write_bytes(before)

    def test_every_demo_in_the_table_is_listed_and_documented(self):
        """--list and docs/demos.md are two views of the same table; a demo added to the
        builder without a gallery entry is a picture nobody ever sees."""
        listed = sh(sys.executable, ROOT / "demos" / "build.py", "--list").stdout
        names = [line.split()[0] for line in listed.splitlines() if line.strip()]
        self.assertGreaterEqual(len(names), 10, "the gallery lost most of its demos")
        page = (ROOT / "docs" / "demos.md").read_text(encoding="utf-8")
        for name in names:
            self.assertIn(f"demos/{name}.gif", page,
                          f"{name} is built but has no section in docs/demos.md "
                          f"(run: python3 demos/build.py --docs)")

    def test_every_script_is_shown_working_by_a_demo(self):
        """A tool nobody can see working is hard to review and harder to trust. Every script
        under scripts/ either appears in a demo's command line (so the gallery renders it end to
        end on every build) or is on the builder's INSPECTION list -- the tools whose entire
        output is a table or an HTML file, which get a command and a sentence in docs/demos.md
        instead of a picture. Nothing is allowed to be in neither list."""
        sys.path.insert(0, str(ROOT / "demos"))
        try:
            import build as demo_build
        finally:
            sys.path.pop(0)
        commands = " ".join(cmd for name in demo_build.BY_NAME
                            for cmd in demo_build._commands_for(name))
        inspection = {tool for tool, _cmd, _what in demo_build.INSPECTION}
        page = (ROOT / "docs" / "demos.md").read_text(encoding="utf-8")
        for script in sorted(p.name for p in (ROOT / "scripts").glob("*.py")):
            if script.startswith("_"):
                continue
            if script in inspection:
                self.assertIn(script, page,
                              f"{script} is on demos/build.py's INSPECTION list but is not in "
                              f"docs/demos.md (run: python3 demos/build.py --docs)")
                continue
            self.assertIn(f"scripts/{script} ", commands + " ",
                          f"no demo in demos/build.py runs {script}: add one (a before/after "
                          f"demo) or, if it only ever prints a table, add it to INSPECTION")


class RenderSourceCarryTests(unittest.TestCase):
    """A255: render.py's stages run as their own tools, so its own result never carried
    source_carry: a one-clip render that lost its source's subtitle track said nothing."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)

    def test_a_one_source_render_says_what_its_output_lost(self):
        srt = OUT / "rcarry.srt"
        srt.write_text("1\n00:00:00,500 --> 00:00:02,500\nhi\n", encoding="utf-8")
        src = OUT / "rcarry_src.mp4"  # an MP4 throughout: with no export stage the delivery is the clip stage's file
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=3",
           "-f", "lavfi", "-i", "sine=d=3", "-i", srt, "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264",
           "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "mov_text", "-timecode", "01:00:00:00", src)
        music = OUT / "rcarry_music.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=3", music)

        def render(name, clip, *flags, **more):
            proj = OUT / f"rcarry_{name}.json"
            out = OUT / f"rcarry_{name}.mp4"
            proj.write_text(json.dumps({"output": str(out), "clips": [clip], **more}), encoding="utf-8")
            doc = json.loads(script("render.py", proj, "--fast", *flags, "--json").stdout)
            kinds = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", out).stdout.split()
            tc = (probe(str(out)).get("timecode") or {}).get("value")
            warned = [w["dropped"] for w in (doc.get("diagnostics") or {}).get("warnings", []) if w["code"] == "source_items_dropped"]
            return doc, kinds, tc, warned

        # the whole clip: the subtitle track and the timecode are in the written file, and said kept
        doc, kinds, tc, warned = render("whole", {"src": str(src)})
        self.assertIn("subtitle", kinds)
        self.assertEqual(tc, "01:00:00:00")
        self.assertEqual(sorted(doc["source_carry"]["kept"]), ["subtitles", "timecode"], doc.get("source_carry"))
        self.assertEqual(warned, [])
        # from 1 s: the cut's re-encode drops the track (said, with the warning), and the timecode
        # written is the label of the source frame the output starts on, so it is kept
        doc, kinds, tc, warned = render("late", {"src": str(src), "in": "1"})
        self.assertNotIn("subtitle", kinds)
        self.assertEqual(tc, "01:00:01:00")
        self.assertIn("subtitles", doc["source_carry"]["dropped"], doc.get("source_carry"))
        self.assertIn("timecode", doc["source_carry"]["kept"], doc.get("source_carry"))
        self.assertEqual(warned, [["subtitles"]])
        # served from --cache, the stages' own verdicts are replayed: the moved label is still kept
        cdir = OUT / "rcarry_cache"
        shutil.rmtree(cdir, ignore_errors=True)
        render("cached", {"src": str(src), "in": "1"}, "--cache", cdir)
        doc, _kinds, tc, _warned = render("cached", {"src": str(src), "in": "1"}, "--cache", cdir)
        self.assertTrue(doc["cache"]["hits"], doc.get("cache"))
        self.assertEqual(tc, "01:00:01:00")
        self.assertIn("timecode", doc["source_carry"]["kept"], doc.get("source_carry"))
        shutil.rmtree(cdir, ignore_errors=True)
        # a second sound source: which one's items the output carries is the project's choice
        doc, _kinds, _tc, _warned = render("music", {"src": str(src)}, audio={"music": str(music)})
        self.assertNotIn("source_carry", doc)


class CommonFacadeTests(unittest.TestCase):
    """`_common` is a package with a facade since the refactor release after 1.15.0. A name
    rebound through the facade must reach the module that defines it, a read through the facade
    must see the live value the defining module holds, and a reload must not rewrite the
    submodules' own dunders (audit 14, P1-1 and P1-2)."""

    def test_rebinding_through_the_facade_reaches_the_defining_module_and_reads_live(self):
        import importlib
        from unittest import mock
        import _common
        runner = sys.modules["_common.runner"]
        _common.ffmpeg_version()
        self.assertIsNotNone(runner._FFMPEG_VERSION)
        self.assertEqual(_common._FFMPEG_VERSION, runner._FFMPEG_VERSION)
        with mock.patch.object(_common, "_FFMPEG_VERSION", (7, 1)):
            self.assertEqual(runner._FFMPEG_VERSION, (7, 1))
            self.assertEqual(runner.ffmpeg_version(), (7, 1))
        self.assertEqual(_common._FFMPEG_VERSION, runner._FFMPEG_VERSION)
        with mock.patch("_common.ffmpeg_version", return_value=(9, 9)):
            self.assertEqual(runner.ffmpeg_version(), (9, 9))
        self.assertNotEqual(runner.ffmpeg_version(), (9, 9))
        before = runner.__file__
        importlib.reload(_common)
        self.assertEqual(runner.__file__, before)
        self.assertTrue(callable(_common.emit) and callable(_common.probe))

    def test_an_aac_track_is_written_with_the_older_coder_from_ffmpeg_9_1(self):
        """#659: FFmpeg 9.1 made a new coder the AAC encoder's default and it never returns on some
        sound (mono at 192k behind 0.1 s or 2.5 s of silence: `sync.py --replace-audio` ran to its
        time limit on Windows, a file of 48 bytes). Every command passes run(), which from 9.1 on
        names the coder that was the default before; older builds get the command they always got,
        and a command that names a coder keeps it."""
        from unittest import mock
        from _common import runner
        cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "o.mp4"]
        self.assertEqual(runner.pin_aac_coder(cmd, (9, 1)), cmd[:7] + ["-aac_coder", "twoloop"] + cmd[7:])
        self.assertEqual(runner.pin_aac_coder(cmd, (10, 0))[7:9], ["-aac_coder", "twoloop"])
        self.assertEqual(runner.pin_aac_coder(cmd, (9, 0)), cmd)
        self.assertEqual(runner.pin_aac_coder(cmd, (0, 0)), cmd, "an unreadable version takes the older spelling")
        two = ["ffmpeg", "-i", "a.mov", "-c:a:0", "aac", "-acodec", "aac", "-codec:a:1", "aac", "o.mov"]
        self.assertEqual(runner.pin_aac_coder(two, (9, 1)).count("twoloop"), 3)
        named = cmd[:7] + ["-aac_coder", "fast"] + cmd[7:]
        self.assertEqual(runner.pin_aac_coder(named, (9, 1)), named)
        for other in (["ffmpeg", "-i", "a.mp4", "-c:a", "libopus", "o.mkv"], ["ffmpeg", "-i", "a.mp4", "-c", "copy", "o.mp4"]):
            self.assertEqual(runner.pin_aac_coder(other, (9, 1)), other)
        # and it is on the one path every command takes: the plan a caller reads names the coder
        with mock.patch("_common.runner.ffmpeg_version", return_value=(9, 1)), mock.patch.object(runner.STATE, "dry_run", True), \
                mock.patch.object(runner.STATE, "commands", []):
            OUT.mkdir(parents=True, exist_ok=True)
            src = tiny_clip(OUT / "pin_coder_src.mp4", "color=c=red:s=160x120:r=25", audio=True)
            runner.run(["ffmpeg", "-y", "-i", str(src), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(OUT / "pin_coder.mp4")], quiet=True)
            self.assertIn("-c:a aac -aac_coder twoloop -b:a 192k", runner.STATE.commands[-1])


class TimelineExportTests(unittest.TestCase):
    """2.1: render.py --export-timeline writes the project's cut as an editor timeline (EDL,
    FCPXML, OTIO) instead of rendering it. The arithmetic is the contract: every format must put
    the same frames on the same timeline positions render.py's own join would, dissolves included,
    and whatever an editor timeline cannot carry is named in `not_exported`, never dropped."""

    RATE = 30

    @staticmethod
    def _tl():
        from _common import timeline
        return timeline

    def _probes(self, **durations):
        return {f"/m/{name}": {"duration": dur, "video": {"fps": 30.0, "width": 1280, "height": 720},
                               "audio": {"channels": 2}} for name, dur in durations.items()}

    def test_build_centres_each_dissolve_and_keeps_the_rendered_length(self):
        """Three clips, a 0.5 s (15-frame, odd) dissolve, one clip at 1.25x: the total is the sum of
        the clip lengths minus one dissolve per join -- what join.py's xfade renders -- and each
        dissolve's window starts `trim_head` frames before the cut and ends `trim_tail` after it."""
        tl_mod = self._tl()
        proj = {"clips": [{"src": "a.mp4", "in": 1, "out": 5}, {"src": "b.mp4", "in": 2, "out": 7, "speed": 1.25},
                          {"src": "c.mp4"}], "transition": {"type": "fade", "duration": 0.5}}
        tl = tl_mod.build(proj, self._probes(**{"a.mp4": 8, "b.mp4": 8, "c.mp4": 3}), lambda p: f"/m/{p}")
        lengths = [c["length"] for c in tl["clips"]]
        self.assertEqual(lengths, [120, 120, 90])
        self.assertEqual(tl["transition_frames"], 15)
        self.assertEqual(tl["total"], sum(lengths) - 15 * 2)
        a, b, c = tl["clips"]
        self.assertEqual((a["trim_head"], a["trim_tail"], b["trim_head"], b["trim_tail"], c["trim_head"]), (0, 7, 8, 7, 8))
        self.assertEqual(b["record_in"], a["visible"])
        self.assertEqual(c["record_in"], a["visible"] + b["visible"])
        # b's window: from its visible start minus trim_head, for 15 frames; a's media covers it
        self.assertEqual(a["visible"] + a["trim_tail"], a["length"])

    def test_a_half_frame_position_rounds_up(self):
        """#638, velisa/timebase@1 TB-4: a position at an exact half frame rounds up, floor(x + 1/2), as
        decision.py and av_rescale do. round() took it to even: 0.5 s at 25 fps (12.5 frames) became 12,
        a frame off the same cut exported by a tool that follows TB-4."""
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 4})
        probes["/m/a.mp4"]["video"]["fps"] = 25.0
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 0.5, "out": 2.5}], "transition": {"type": "none"}},
                          probes, lambda p: f"/m/{p}")
        clip = tl["clips"][0]
        self.assertEqual((clip["src_in"], clip["src_out"], clip["length"]), (13, 63, 50))
        # one source frame played at 2x is half a timeline frame
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 1.04, "speed": 2}],
                           "transition": {"type": "none"}}, probes, lambda p: f"/m/{p}")
        clip = tl["clips"][0]
        self.assertEqual((clip["src_in"], clip["src_out"], clip["length"]), (25, 26, 1))
        # the start label's offset: 00:00:00:00 plus 0.02 s is half a frame at 25 fps
        meta = {"timecode": {"value": "00:00:00:00"}, "video": {"fps": 25.0}}
        self.assertEqual(tl_mod.output_timecode_args(meta, 0.02)[1], "timecode=00:00:00:01")
        # the exporters count the same way: a 14-frame dissolve gives 7 frames of handle, and at 1.5x
        # that is 10.5 source frames, so the clip's source start is frame 60 + 11 in FCPXML and in OTIO
        probes = self._probes(**{"a.mp4": 8, "b.mp4": 8})
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 5}, {"src": "b.mp4", "in": 2, "out": 7, "speed": 1.5}],
                           "transition": {"type": "fade", "duration": 14 / 30}}, probes, lambda p: f"/m/{p}")
        self.assertEqual((tl["clips"][1]["trim_head"], tl["clips"][1]["visible"]), (7, 93))
        self.assertEqual(re.findall(r'<timept time="[^"]*" value="([^"]*)"', tl_mod.to_fcpxml(tl)), ["71/30s", "211/30s"])
        self.assertIn('"value": 71.0', tl_mod.to_otio(tl))

    def test_crop_only_sequence_uses_the_even_canvas_for_several_clips(self):
        probes = self._probes(**{"a.mp4": 2, "b.mp4": 2})
        probes["/m/a.mp4"]["video"].update(width=161, height=91)
        rel = lambda p: f"/m/{p}"  # noqa: E731
        project = {"frame": {"fit": "crop"}, "clips": [{"src": "a.mp4"}, {"src": "b.mp4"}]}
        timeline = self._tl().build(project, probes, rel)
        self.assertEqual((timeline["width"], timeline["height"]), (164, 92))

    def test_build_refuses_what_a_timeline_cannot_hold(self):
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 8, "b.mp4": 8})
        rel = lambda p: f"/m/{p}"  # noqa: E731
        with self.assertRaises(tl_mod.TimelineError):
            tl_mod.build({"clips": [{"src": "a.mp4", "in": 5, "out": 5}]}, probes, rel)
        with self.assertRaises(tl_mod.TimelineError):  # 0.2 s clip, 0.5 s dissolves on both sides
            tl_mod.build({"clips": [{"src": "a.mp4"}, {"src": "b.mp4", "in": 0, "out": 0.2}, {"src": "a.mp4"}],
                          "transition": {"duration": 0.5}}, probes, rel)
        tl = tl_mod.build({"clips": [{"src": "a.mp4"}], "captions": {"text": "c.txt"}, "silence": {},
                           "audio": {"voice": "light"}, "export": {"preset": "reels"}}, probes, rel)
        joined = " | ".join(tl["not_exported"])
        for word in ("captions", "export preset", "voice"):
            self.assertIn(word, joined)
        self.assertNotIn("silence", joined, "an empty silence block asked for nothing")
        # what the render refuses too: a clip with no source, a fit.py --fit that does not exist
        for proj, word in (({"clips": [{"src": "a.mp4"}, {"in": 0}]}, "clips[1]: no src"),
                           ({"clips": [{"src": "a.mp4"}], "frame": {"aspect": "9:16", "fit": "stretch"}}, "frame.fit")):
            with self.subTest(refused=word):
                with self.assertRaises(tl_mod.TimelineError) as ctx:
                    tl_mod.build(proj, probes, rel)
                self.assertIn(word, str(ctx.exception))

    def test_the_source_start_timecode_is_carried_into_every_format(self):
        """#414: a camera file tagged 01:00:00:00 was exported from 00:00:00:00, outside the media
        for a conform. EDL source timecodes count from it (drop-frame where the source's is), the
        FCPXML asset starts at it and OTIO's available_range does too."""
        import xml.etree.ElementTree as ET
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 8})
        probes["/m/a.mp4"]["timecode"] = {"value": "01:00:00:00", "drop_frame": False}
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 2.5}]}, probes, lambda p: f"/m/{p}")
        event = [ln for ln in tl_mod.to_edl(tl).splitlines() if ln[:3].isdigit()][0]
        self.assertIn(" C        01:00:01:00 01:00:02:15 01:00:00:00 01:00:01:15", event)
        root = ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8"))
        self.assertEqual(root.find("./resources/asset").get("start"), "3600s")
        self.assertEqual(root.find("./library/event/project/sequence/spine/asset-clip").get("start"), "3601s")
        clip = json.loads(tl_mod.to_otio(tl))["tracks"]["children"][0]["children"][0]
        self.assertEqual(clip["source_range"]["start_time"]["value"], 108030)
        self.assertEqual(clip["media_references"]["DEFAULT_MEDIA"]["available_range"]["start_time"]["value"], 108000)
        # 29.97 drop-frame: 01:00:00;00 is frame 107892, and the EDL labels the source as it shows it
        probes["/m/a.mp4"] = {"duration": 8, "video": {"fps": 29.97, "width": 1280, "height": 720},
                              "audio": {"channels": 2}, "timecode": {"value": "01:00:00;00", "drop_frame": True}}
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 2.5}]}, probes, lambda p: f"/m/{p}")
        self.assertEqual(tl["clips"][0]["tc_start"], 107892)
        event = [ln for ln in tl_mod.to_edl(tl).splitlines() if ln[:3].isdigit()][0]
        self.assertIn(" C        01:00:01;00 01:00:02;15 ", event)
        self.assertEqual(tl_mod._tc_label(17982, tl["clips"][0]["rate"], True), "00:10:00;00")
        self.assertEqual(tl_mod._tc_label(1800, tl["clips"][0]["rate"], True), "00:01:00;02")
        # a retimed clip: the timeMap's source times count from the start timecode too
        probes["/m/a.mp4"] = {"duration": 8, "video": {"fps": 30.0, "width": 1280, "height": 720},
                              "audio": {"channels": 2}, "timecode": {"value": "01:00:00:00", "drop_frame": False}}
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 2.5, "speed": 1.25}]}, probes, lambda p: f"/m/{p}")
        root = ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8"))
        self.assertEqual(root.find("./resources/asset").get("start"), "3600s")
        points = root.findall("./library/event/project/sequence/spine/asset-clip/timeMap/timept")
        self.assertEqual([(p.get("time"), p.get("value")) for p in points], [("0s", "3601s"), ("6/5s", "7205/2s")])

    def test_a_start_timecode_that_does_not_exist_at_the_source_rate_is_not_read(self):
        """#427 review: frame 29 at 25 fps, or a frame drop-frame counting skips, was added as an
        offset and every exported source time shifted; it is read as no timecode, as probe()
        skips a malformed tag."""
        from fractions import Fraction
        tl_mod = self._tl()
        ntsc = Fraction(30000, 1001)
        self.assertEqual(tl_mod.start_tc_frames({"value": "01:00:00:29", "drop_frame": False}, Fraction(25)), 0)
        self.assertEqual(tl_mod.start_tc_frames({"value": "01:00:00:24", "drop_frame": False}, Fraction(25)), 90024)
        self.assertEqual(tl_mod.start_tc_frames({"value": "00:01:00;00", "drop_frame": True}, ntsc), 0)
        self.assertEqual(tl_mod.start_tc_frames({"value": "00:01:00;02", "drop_frame": True}, ntsc), 1800)
        self.assertEqual(tl_mod.start_tc_frames({"value": "00:10:00;00", "drop_frame": True}, ntsc), 17982)

    def test_edl_source_timecodes_are_at_each_clips_own_rate(self):
        """#414: a 25 fps clip in a 29.97 sequence was given frame :29, which 25 fps does not have."""
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 6})
        probes["/m/p25.mp4"] = {"duration": 6, "video": {"fps": 25.0, "width": 1280, "height": 720}, "audio": {"channels": 2}}
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 0, "out": 2}, {"src": "p25.mp4", "in": 2.96, "out": 4}],
                           "transition": {"type": "none"}}, probes, lambda p: f"/m/{p}")
        events = [ln for ln in tl_mod.to_edl(tl).splitlines() if ln[:3].isdigit()]
        self.assertIn(" C        00:00:02:24 00:00:04:00 ", events[1])
        # the M2 speed is in the clip's own frames per second, the rate its source labels count in
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 0, "out": 2}, {"src": "p25.mp4", "in": 0, "out": 4, "speed": 1.25}],
                           "transition": {"type": "none"}}, probes, lambda p: f"/m/{p}")
        self.assertIn("M2   AX       031.2", tl_mod.to_edl(tl))

    def test_a_clip_out_past_the_media_end_ends_at_the_media_end(self):
        """#414: the render clamps an out past the end (cut.py); the timeline kept 10 s of a 6 s
        clip. An in at or past the end is refused, as cut.py refuses it."""
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 6})
        tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 1, "out": 10}]}, probes, lambda p: f"/m/{p}")
        self.assertEqual((tl["clips"][0]["src_out"], tl["total"]), (180, 150))
        self.assertTrue(any("past the end of a.mp4" in n for n in tl["notes"]), tl["notes"])
        with self.assertRaisesRegex(tl_mod.TimelineError, "past the end"):
            tl_mod.build({"clips": [{"src": "a.mp4", "in": 6, "out": 10}]}, probes, lambda p: f"/m/{p}")

    def test_a_chapter_metadata_py_refuses_is_refused_not_dropped(self):
        """#414: a chapter past the end was dropped silently while the render's metadata.py refuses
        it ("Neither path accepts a time the other refuses")."""
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 8})
        for chapters, word in (([{"at": 0, "title": "A"}, {"at": 9, "title": "B"}], "end of the timeline"),
                               ([{"at": 8, "title": "A"}], "end of the timeline"),
                               ([{"at": 3, "title": "A"}, {"at": 2, "title": "B"}], "does not come after")):
            with self.subTest(chapters=chapters):
                with self.assertRaisesRegex(tl_mod.TimelineError, word):
                    tl_mod.build({"clips": [{"src": "a.mp4"}], "chapters": chapters}, probes, lambda p: f"/m/{p}")
        tl = tl_mod.build({"clips": [{"src": "a.mp4"}], "chapters": [{"at": 0, "title": "A"}, {"at": 7.99, "title": "B"}]},
                          probes, lambda p: f"/m/{p}")
        self.assertEqual([m["at"] for m in tl["markers"]], [0, 239])

    def test_ntsc_rates_are_exact(self):
        tl_mod = self._tl()
        from fractions import Fraction
        self.assertEqual(tl_mod.exact_rate(29.97), Fraction(30000, 1001))
        self.assertEqual(tl_mod.exact_rate(23.976), Fraction(24000, 1001))
        self.assertEqual(tl_mod.exact_rate(25.0), Fraction(25))

    def test_times_are_read_with_the_render_grammar(self):
        """Clip in/out and chapter times in the forms render.py's own stages take ("0:01",
        hh:mm:ss:ff at the source's fps, @fps) count the frames the numeric form counts. 2.2.1
        called float() on them: the --init starter's own "in": "0:00" was a traceback."""
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 8})
        probes["/m/v.m4a"] = {"duration": 8, "audio": {"channels": 2}}
        rel = lambda p: f"/m/{p}"  # noqa: E731

        def frames(clip, at, **proj):
            tl = tl_mod.build(dict(proj, clips=[dict({"src": "a.mp4"}, **clip)], chapters=[{"at": at, "title": "x"}]),
                              probes, rel)
            c = tl["clips"][0]
            return c["src_in"], c["src_out"], tl["total"], [m["at"] for m in tl["markers"]]

        numeric = frames({"in": 1.5, "out": 5}, 2)
        self.assertEqual(numeric, (45, 150, 105, [60]))
        for clip, at in (({"in": "0:01.5", "out": "0:05"}, "0:02"),
                         ({"in": "00:00:01:15", "out": "00:00:05:00"}, "00:00:02:00@30"),
                         ({"in": "00:00:01:15@30", "out": "0:00:05,000"}, "2")):
            with self.subTest(clip=clip, at=at):
                self.assertEqual(frames(clip, at), numeric)
        self.assertEqual(frames({"in": "0:00", "out": 5}, "0:00"), frames({"in": 0, "out": 5}, 0))
        self.assertEqual(frames({"in": "0:00", "out": 5}, "0:00")[3], [0], 'a chapter at "0:00" is the first frame')
        # hh:mm:ss:ff is on the SOURCE's clock, as cut.py reads it: 00:00:01:15 of a 30 fps source
        # is 1.5 s, 38 frames of a 25 fps sequence (at the sequence's 25 fps it would be 1.6 s, 40)
        self.assertEqual(frames({"in": "00:00:01:15", "out": 5}, 0, frame={"fps": 25})[:2], (38, 125))
        # a clip with no picture has no fps, and cut.py takes no other: frame.fps does not stand in
        # for it (the render refuses 00:00:01:15 there), so it needs its @fps in both paths
        with self.assertRaisesRegex(tl_mod.TimelineError, "@fps"):
            frames({"src": "v.m4a", "in": "00:00:01:15", "out": 5}, 0, frame={"fps": 30})
        self.assertEqual(frames({"src": "v.m4a", "in": "00:00:01:15@30", "out": 5}, 0, frame={"fps": 30})[:2], (45, 150))
        # a chapter list carries no fps: render.py's chapters stage needs @fps there too
        for clip, at, word in (({"in": "1:xx"}, 0, "not a time"), ({"in": "nan"}, 0, "not a time"),
                               ({"in": -1}, 0, "negative"), ({"speed": "fast"}, 0, "not a number"),
                               ({}, "00:00:02:00", "@fps")):
            with self.subTest(refused=clip or at):
                with self.assertRaises(tl_mod.TimelineError) as ctx:
                    frames(clip, at)
                self.assertIn(word, str(ctx.exception))
        with self.assertRaisesRegex(tl_mod.TimelineError, "@fps"):  # no picture and no frame.fps: no rate to read
            tl_mod.build({"clips": [{"src": "a.mp4"}, {"src": "v.m4a", "in": "00:00:01:15"}]}, probes, rel)

    def test_sequence_frame_is_the_frame_the_render_delivers(self):
        """The sequence is sized by fit.py's own rule on the project frame. 2.2.1 took the width
        from the project and the height from the source: {aspect 16:9, width 1920} over a 4K
        source was a 1920x2160 sequence. A picture of another aspect is a reframe: EDL and OTIO
        cannot state it, so they name it in not_exported with the project's frame.fit; FCPXML
        states it (test_fcpxml_describes_each_source_and_states_the_conform)."""
        tl_mod = self._tl()

        def seq(frame, w, h, rotation=0, fmt="edl"):
            probes = {"/m/a.mp4": {"duration": 8, "video": {"fps": 30.0, "width": w, "height": h, "rotation": rotation},
                                   "audio": {"channels": 2}}}
            tl = tl_mod.build({"clips": [{"src": "a.mp4"}], "frame": frame}, probes, lambda p: f"/m/{p}")
            return (tl["width"], tl["height"]), [x for x in tl_mod.summary(tl, fmt)["not_exported"] if "reframe" in x or "blur" in x]

        self.assertEqual(seq({"aspect": "16:9", "width": 1920}, 3840, 2160), ((1920, 1080), []))
        for fit in ("crop", "pad", "blur"):
            with self.subTest(fit=fit):
                size, reframe = seq({"aspect": "16:9", "width": 1920, "fit": fit}, 640, 480)
                self.assertEqual(size, (1920, 1080))
                self.assertEqual(len(reframe), 1)
                self.assertIn("a.mp4", reframe[0])
                self.assertIn(f"(frame.fit {fit})", reframe[0], "the note reports the project's own frame.fit")
                self.assertEqual(seq({"aspect": "16:9", "width": 1920, "fit": fit}, 640, 480, fmt="otio")[1], reframe)
                # FCPXML states pad and crop as the clip's adjust-conform; only blur's background is missing
                self.assertEqual(len(seq({"aspect": "16:9", "width": 1920, "fit": fit}, 640, 480, fmt="fcpxml")[1]),
                                 1 if fit == "blur" else 0)
        self.assertEqual(seq({"width": 1920}, 640, 360), ((1920, 1080), []), "one side follows the source's aspect")
        self.assertEqual(seq({"aspect": "9:16", "height": 1920}, 1920, 1080)[0], (1080, 1920))
        self.assertEqual(seq({"aspect": "9:16"}, 1920, 1080)[0], (608, 1080), "fit.py's bound: no upscale")
        self.assertEqual(seq({}, 1920, 1080, rotation=90), ((1080, 1920), []), "the displayed picture")
        with self.assertRaises(tl_mod.TimelineError):
            seq({"aspect": "wide"}, 1920, 1080)

    def test_fcpxml_describes_each_source_and_states_the_conform(self):
        """Each video asset carries its own source's format and the sequence its frame: with one
        format for both, a 1280x720 asset under a 1080x1920 frame claimed to be 1080x1920. A clip
        of another aspect states its conform, which the DTD reads as fit when it is absent: fill
        for frame.fit crop, fit for pad."""
        import xml.etree.ElementTree as ET
        tl_mod = self._tl()
        probes = self._probes(**{"a.mp4": 8})
        probes["/m/tall.mp4"] = {"duration": 8, "video": {"fps": 30.0, "width": 1080, "height": 1920}, "audio": {"channels": 2}}
        probes["/m/sq25.mp4"] = {"duration": 8, "video": {"fps": 25.0, "width": 96, "height": 96}, "audio": {"channels": 2}}
        for fit, conform in (("crop", "fill"), ("pad", "fit")):
            with self.subTest(fit=fit):
                tl = tl_mod.build({"clips": [{"src": "a.mp4"}, {"src": "tall.mp4"}, {"src": "sq25.mp4"}],
                                   "frame": {"aspect": "9:16", "width": 1080, "fit": fit}}, probes, lambda p: f"/m/{p}")
                root = ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8"))
                formats = {f.get("id"): (f.get("width"), f.get("height"), f.get("frameDuration"))
                           for f in root.findall("./resources/format")}
                assets = {a.get("name"): a.get("format") for a in root.findall("./resources/asset")}
                seq = root.find("./library/event/project/sequence")
                self.assertEqual(formats[seq.get("format")], ("1080", "1920", "1/30s"))
                self.assertEqual(formats[assets["a.mp4"]], ("1280", "720", "1/30s"))
                self.assertEqual(assets["tall.mp4"], seq.get("format"), "a source that is the frame shares its format")
                self.assertEqual(formats[assets["sq25.mp4"]], ("96", "96", "1/25s"))
                spine = seq.find("spine").findall("asset-clip")
                self.assertEqual([c.get("format") for c in spine], [assets["a.mp4"], assets["tall.mp4"], assets["sq25.mp4"]])
                self.assertEqual([[e.get("type") for e in c.findall("adjust-conform")] for c in spine],
                                 [[conform], [], [conform]])

    def test_fcpxml_keeps_the_dtd_child_order_on_a_retimed_first_clip(self):
        """FCPXML 1.10's asset-clip content model is timeMap, the adjust-* elements, anchored
        items, then markers."""
        import xml.etree.ElementTree as ET
        tl_mod = self._tl()
        proj = {"clips": [{"src": "a.mp4", "in": 1, "out": 5, "speed": 1.25}, {"src": "b.mp4"}],
                "audio": {"music": "bed.m4a"}, "chapters": [{"at": "0:00", "title": "Intro"}]}
        tl = tl_mod.build(proj, self._probes(**{"a.mp4": 8, "b.mp4": 8, "bed.m4a": 30}), lambda p: f"/m/{p}")
        first = ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8")).find("./library/event/project/sequence/spine")[0]
        self.assertEqual([e.tag for e in first], ["timeMap", "asset-clip", "chapter-marker"])
        self.assertEqual((first[1].get("lane"), first[2].get("start")), ("-1", "0s"))
        # a reframed clip's adjust-conform is one of the intrinsic adjustments: after timeMap,
        # before the anchored music bed
        tl = tl_mod.build(dict(proj, frame={"aspect": "1:1", "fit": "crop"}),
                          self._probes(**{"a.mp4": 8, "b.mp4": 8, "bed.m4a": 30}), lambda p: f"/m/{p}")
        first = ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8")).find("./library/event/project/sequence/spine")[0]
        self.assertEqual([e.tag for e in first], ["timeMap", "adjust-conform", "asset-clip", "chapter-marker"])

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        d = OUT / "timeline"
        d.mkdir(parents=True, exist_ok=True)
        cls.dir = d
        for name, src, freq in (("a.mp4", "testsrc2", 440), ("b.mp4", "testsrc", 660)):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"{src}=size=640x360:rate=30",
               "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", "8", "-c:v", "libx264",
               "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", d / name)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
           "-t", "30", "-c:a", "aac", d / "bed.m4a")
        cls.project = d / "p.json"
        cls.project.write_text(json.dumps({
            "output": "final.mp4",
            "clips": [{"src": "a.mp4", "in": 1, "out": 5}, {"src": "b.mp4", "in": 2, "out": 7, "speed": 1.25}],
            "transition": {"type": "fade", "duration": 0.5}, "audio": {"music": "bed.m4a"},
            "chapters": [{"at": 0, "title": "Intro"}, {"at": 3.5, "title": "Part B"}],
            "captions": {"text": "cues.txt"}}), encoding="utf-8")

    def _export(self, name, *extra):
        out = self.dir / name
        if out.exists():
            out.unlink()
        doc = json.loads(script("render.py", self.project, "--export-timeline", out, "--json", *extra).stdout)
        return out, doc

    def test_every_format_reports_the_same_cut_and_what_it_left_out(self):
        for name in ("e.edl", "e.fcpxml", "e.otio"):
            with self.subTest(fmt=name):
                out, doc = self._export(name)
                self.assertEqual((doc["status"], doc["verified"]), ("completed", True))
                self.assertEqual(doc["verification"], [{"step": "exists", "ok": True}, {"step": "parse", "ok": True}])
                t = doc["timeline"]
                # a: 4 s = 120 frames; b: 5 s at 1.25x = 120 frames; one 15-frame dissolve
                self.assertEqual((t["frames"], t["duration"], t["rate"]), (225, 7.5, "30"))
                self.assertEqual((t["clips"], t["transition_frames"], t["music"], t["markers"]), (2, 15, True, 2))
                self.assertTrue(any("captions" in x for x in t["not_exported"]))
                self.assertEqual(doc["commands"], [], "a timeline is written, nothing is encoded")

    def test_edl_events_line_up_with_the_dissolve(self):
        out, _ = self._export("golden.edl")
        events = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln[:3].isdigit()]
        self.assertEqual(events, [
            "001  AX       B     C        00:00:01:00 00:00:04:15 01:00:00:00 01:00:03:15",
            "002  AX       B     C        00:00:04:15 00:00:04:15 01:00:03:15 01:00:03:15",
            "002  AX       B     D    015 00:00:02:00 00:00:07:00 01:00:03:15 01:00:07:15",
            "003  AX       A2    C        00:00:00:00 00:00:07:15 01:00:00:00 01:00:07:15"])
        text = out.read_text(encoding="utf-8")
        self.assertIn("M2   AX       037.5", text, "1.25x at 30 fps is an M2 of 37.5")
        self.assertIn("* LOC: 01:00:03:15 WHITE   Part B", text)

    def test_otio_track_lengths_add_up_without_counting_transitions(self):
        """OTIO: a track's length is the sum of its clips' source_range durations; transitions
        overlap them and add nothing. The first version put the speed-scaled source length there
        and the track came out 253 frames for a 225-frame cut (caught with the reference
        opentimelineio library, 0.18)."""
        out, _ = self._export("e2.otio")
        doc = json.loads(out.read_text(encoding="utf-8"))
        video, music = doc["tracks"]["children"]
        clips = [c for c in video["children"] if c["OTIO_SCHEMA"] == "Clip.2"]
        trans = [c for c in video["children"] if c["OTIO_SCHEMA"] == "Transition.1"]
        self.assertEqual(sum(c["source_range"]["duration"]["value"] for c in clips), 225)
        self.assertEqual([(t["in_offset"]["value"], t["out_offset"]["value"]) for t in trans], [(8, 7)])
        self.assertEqual(clips[1]["effects"][0]["time_scalar"], 1.25)
        self.assertEqual(music["children"][0]["source_range"]["duration"]["value"], 225)
        self.assertEqual([m["name"] for m in doc["tracks"]["markers"]], ["Intro", "Part B"])

    def test_fcpxml_spine_matches_the_cut(self):
        import xml.etree.ElementTree as ET
        out, _ = self._export("e2.fcpxml")
        root = ET.fromstring(out.read_bytes())
        self.assertEqual(root.get("version"), "1.10")
        seq = root.find("./library/event/project/sequence")
        self.assertEqual(seq.get("duration"), "15/2s")
        spine = list(seq.find("spine"))
        self.assertEqual([e.tag for e in spine], ["asset-clip", "transition", "asset-clip"])
        self.assertEqual((spine[1].get("offset"), spine[1].get("duration")), ("7/2s", "1/2s"))
        self.assertEqual(spine[2].get("offset"), "113/30s")
        self.assertIsNotNone(spine[2].find("timeMap"), "the 1.25x clip is retimed")
        self.assertEqual(len(spine[0].findall("chapter-marker")), 2)
        self.assertEqual(spine[0].find("asset-clip").get("lane"), "-1", "the music bed is a connected clip below")
        # FCPXML 1.10's asset-clip holds anchored items before markers; 2.1.0-2.2.1 wrote the
        # music bed after the chapter markers, a file that does not validate against the DTD
        self.assertEqual([e.tag for e in spine[0]], ["asset-clip", "chapter-marker", "chapter-marker"])
        fmt = root.find("./resources/format")
        self.assertEqual((fmt.get("width"), fmt.get("height")), ("640", "360"), "no frame: the source's own picture")
        for asset in root.findall("./resources/asset"):
            self.assertTrue(asset.find("media-rep").get("src").startswith("file://"))

    def test_existing_file_dry_run_and_unknown_format(self):
        out, _ = self._export("guard.edl")
        before = out.read_bytes()
        proc = sh(sys.executable, SCRIPTS / "render.py", self.project, "--export-timeline", out, "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input", "2.0: an existing file is refused")
        self.assertEqual(out.read_bytes(), before)
        dry = self.dir / "dry.otio"
        if dry.exists():
            dry.unlink()
        doc = json.loads(script("render.py", self.project, "--export-timeline", dry, "--dry-run", "--json").stdout)
        self.assertEqual((doc["dry_run"], doc["verified"]), (True, False))
        self.assertFalse(dry.exists(), "a dry run writes nothing")
        proc = sh(sys.executable, SCRIPTS / "render.py", self.project, "--export-timeline", self.dir / "x.aaf", "--json", expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")

    def _sequence(self, project, name):
        """Export `project` as FCPXML: the result document, the sequence's width x height, the root."""
        import xml.etree.ElementTree as ET
        out = self.dir / name
        if out.exists():
            out.unlink()
        doc = json.loads(script("render.py", project, "--export-timeline", out, "--json").stdout)
        root = ET.parse(str(out)).getroot()
        seq = root.find("./library/event/project/sequence")
        fmt = root.find(f"./resources/format[@id='{seq.get('format')}']")
        return doc, (int(fmt.get("width")), int(fmt.get("height"))), root

    def test_the_init_starter_exports_as_written(self):
        """--init's project with only its src replaced: "in": "0:00" / "out": "0:30" count the frames
        0 / 30 count, and frame {aspect 16:9, width 1920} over a 4:3 source is a 1920x1080 sequence
        with the reframe stated (FCPXML) or named (EDL). 2.2.1 printed a traceback (and, given
        numbers, a 1920x48 sequence)."""
        src = self.dir / "long43.mp4"
        if not src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=30",
               "-t", "30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src)
        init = self.dir / "init.json"
        script("render.py", "--init", init)
        proj = json.loads(init.read_text(encoding="utf-8"))
        self.assertEqual(proj["clips"][0]["in"], "0:00", "the starter is what this test is about")
        proj["clips"][0]["src"] = src.name
        init.write_text(json.dumps(proj), encoding="utf-8")
        proj["clips"][0].update({"in": 0, "out": 30})
        numeric = self.dir / "init_numeric.json"
        numeric.write_text(json.dumps(proj), encoding="utf-8")
        doc, size, root = self._sequence(init, "init.fcpxml")
        numeric_doc, numeric_size, _ = self._sequence(numeric, "init_numeric.fcpxml")
        self.assertEqual((doc["status"], doc["timeline"]["frames"]), ("completed", 900))
        self.assertEqual(doc["timeline"], numeric_doc["timeline"])
        self.assertEqual(size, (1920, 1080))
        self.assertEqual(numeric_size, (1920, 1080))
        conform = root.find("./library/event/project/sequence/spine/asset-clip/adjust-conform")
        self.assertEqual(conform.get("type"), "fit", "no frame.fit is pad: the 4:3 picture is fitted into 16:9")
        self.assertFalse(any("reframe" in x for x in doc["timeline"]["not_exported"]), "the FCPXML states it")
        edl = self.dir / "init.edl"
        if edl.exists():
            edl.unlink()
        edl_doc = json.loads(script("render.py", init, "--export-timeline", edl, "--json").stdout)
        self.assertTrue(any("reframe" in x and "long43.mp4" in x and "(frame.fit pad)" in x
                            for x in edl_doc["timeline"]["not_exported"]), "an EDL cannot state it")

    def test_an_aspect_only_frame_takes_the_export_preset_size(self):
        """frame_from_preset() is the render's reading of an aspect-only frame; the export reads it too."""
        proj = self.dir / "reels.json"
        proj.write_text(json.dumps({"frame": {"aspect": "9:16"}, "export": {"preset": "reels"},
                                    "clips": [{"src": "a.mp4", "in": 1, "out": 3}]}), encoding="utf-8")
        doc, size, root = self._sequence(proj, "reels.fcpxml")
        self.assertEqual(size, (1080, 1920))
        asset = root.find("./resources/asset[@name='a.mp4']")
        fmt = root.find(f"./resources/format[@id='{asset.get('format')}']")
        self.assertEqual((fmt.get("width"), fmt.get("height")), ("640", "360"), "the asset is its source, not the frame")
        clip = root.find("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual((clip.get("format"), clip.find("adjust-conform").get("type")), (asset.get("format"), "fit"))

    def test_a_multi_clip_render_delivers_the_sequence_size(self):
        """Several clips under a frame of an aspect and one side: join.py scales them to that side
        at the FIRST clip's aspect, then fit.py reframes the join. fit.py used to get only the
        aspect and bound it by the joined picture, so {aspect 9:16, width 72} over two 16:9 clips
        rendered 22x40 against a 72x128 sequence (render.py's own docstring project, at 1080 wide:
        342x608 against 1080x1920)."""
        for name, size, rate in (("w128.mp4", "128x72", 30), ("sq96.mp4", "96x96", 25)):
            if not (self.dir / name).exists():
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"testsrc2=size={size}:rate={rate}", "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p", self.dir / name)
        for i, (frame, srcs) in enumerate((({"aspect": "9:16", "width": 72}, ("w128.mp4", "w128.mp4")),
                                           ({"aspect": "16:9", "height": 72}, ("sq96.mp4", "w128.mp4")))):
            with self.subTest(frame=frame):
                proj = self.dir / f"multi{i}.json"
                proj.write_text(json.dumps({"output": f"multi{i}.mp4", "frame": frame, "transition": {"type": "none"},
                                            "clips": [{"src": src, "in": 0, "out": 1} for src in srcs]}), encoding="utf-8")
                _, seq_size, _ = self._sequence(proj, f"multi{i}.fcpxml")
                work = self.dir / f"multi{i}_work"
                shutil.rmtree(work, ignore_errors=True)
                doc = json.loads(script("render.py", proj, "--fast", "--stop-after", "fit", "--work", work, "--json").stdout)
                m = probe(doc["output"])
                self.assertEqual((m["video"]["width"], m["video"]["height"]), seq_size)
        # A fit object with its own width or aspect takes the frame's sides where it has none, as
        # one clip does (#526): before, fit.py fitted it inside the joined picture and fit {width
        # 36} under a 72x128 crop frame rendered 36x64, where one clip renders 36x128
        for i, (frame, fit, size) in enumerate((
                ({"aspect": "9:16", "width": 72, "height": 128, "fit": "crop"}, {"width": 36}, (36, 128)),
                ({"width": 128, "height": 72}, {"aspect": "9:16", "fit": "crop"}, (128, 72)),
                ({"aspect": "9:16", "width": 72}, {"aspect": "4:5"}, (72, 90)))):
            with self.subTest(frame=frame, fit=fit):
                proj = self.dir / f"multi_own{i}.json"
                proj.write_text(json.dumps({"output": f"multi_own{i}.mp4", "frame": frame, "fit": fit,
                                            "transition": {"type": "none"},
                                            "clips": [{"src": "w128.mp4", "in": 0, "out": 1}] * 2}), encoding="utf-8")
                _, seq_size, _ = self._sequence(proj, f"multi_own{i}.fcpxml")
                work = self.dir / f"multi_own{i}_work"
                shutil.rmtree(work, ignore_errors=True)
                doc = json.loads(script("render.py", proj, "--fast", "--stop-after", "fit", "--work", work, "--json").stdout)
                m = probe(doc["output"])
                self.assertEqual((m["video"]["width"], m["video"]["height"]), size)
                self.assertEqual(seq_size, size)

    def test_a_sequence_of_several_clips_takes_the_fit_objects_frame(self):
        """#526: the fit object wins for any number of clips. Its aspect, mode, sides and rate go to
        fit.py and the frame's only where it has none, so two clips render, and export, what one
        clip does. Before, the export sized a multi-clip sequence from the frame alone, the
        render fitted the fit object inside the join, and join.py rounded a frame's lone side's
        other side down where fit.py rounds it up: over two 160x120 clips, frame 16:9 with fit
        1:1 rendered 120x120 against a 160x90 sequence, frame {16:9, width 320} with fit {4:5,
        crop} 192x240 against 320x180, frame 1:1 with fit {width 200} 200x200 against 120x120,
        frame 16:9 at 25 fps with fit {fps 24} a 24 fps picture against a 25 fps sequence, and
        frame {width 100} 100x74 against 100x76. The one-clip numbers are pinned unchanged."""
        from fractions import Fraction
        if not (self.dir / "q160.mp4").exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30",
               "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", self.dir / "q160.mp4")
        cases = ((({"aspect": "16:9"}, {"aspect": "1:1"}), (120, 120, "1/30s")),
                 (({"aspect": "16:9", "width": 320}, {"aspect": "4:5", "fit": "crop"}), (320, 400, "1/30s")),
                 (({"aspect": "1:1"}, {"width": 200}), (200, 200, "1/30s")),
                 (({"width": 320, "height": 180}, {"aspect": "1:1"}), (320, 180, "1/30s")),
                 (({"aspect": "16:9", "fps": 25}, {"fps": 24}), (160, 90, "1/24s")),
                 (({"width": 100}, None), (100, 76, "1/30s")),
                 # review of #553: the fit object's side sizes the join too (it was joined at the
                 # frame's 100x76 and fitted to 200x152), and a null in the fit object gives nothing
                 (({"width": 100}, {"width": 200}), (200, 150, "1/30s")),
                 (({"width": 320, "height": 180}, {"aspect": "1:1", "width": None}), (320, 180, "1/30s")))
        for i, ((frame, fit), want) in enumerate(cases):
            for n in (1, 2):
                with self.subTest(frame=frame, fit=fit, clips=n):
                    proj = self.dir / f"several{i}_{n}.json"
                    body = {"output": f"several{i}_{n}.mp4", "frame": frame, "transition": {"type": "none"},
                            "clips": [{"src": "q160.mp4", "in": 0, "out": 1}] * n}
                    if fit:
                        body["fit"] = fit
                    proj.write_text(json.dumps(body), encoding="utf-8")
                    _, seq_size, root = self._sequence(proj, f"several{i}_{n}.fcpxml")
                    seq = root.find("./library/event/project/sequence")
                    rate = root.find(f"./resources/format[@id='{seq.get('format')}']").get("frameDuration")
                    work = self.dir / f"several{i}_{n}_work"
                    shutil.rmtree(work, ignore_errors=True)
                    doc = json.loads(script("render.py", proj, "--fast", "--stop-after", "fit", "--work", work, "--json").stdout)
                    v = probe(doc["output"])["video"]
                    self.assertEqual((v["width"], v["height"]), seq_size, "the rendered file is the sequence's size")
                    self.assertEqual(Fraction(rate[:-1]), 1 / Fraction(v["fps"]).limit_denominator(1001))
                    self.assertEqual((*seq_size, rate), want)
                    shutil.rmtree(work, ignore_errors=True)

    def test_several_clips_are_joined_at_the_rate_the_fit_object_delivers(self):
        """Review of #553: with frame.fps 25 and fit.fps 24 the clips were joined at 25 and
        conformed to 24 by fit.py, so each was rounded twice: two 0.7 s clips rendered 35 frames
        against the 34 the sequence states (it rounds each clip once, at the delivered rate).
        The join takes the fit object's rate where it gives one."""
        from fractions import Fraction
        if not (self.dir / "q160.mp4").exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30",
               "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", self.dir / "q160.mp4")
        for i, (frame, fit, out) in enumerate((({"aspect": "16:9", "fps": 25}, {"fps": 24}, 0.7),
                                               ({"aspect": "16:9", "fps": 25}, {"fps": 24}, 8 / 30),
                                               ({"aspect": "16:9"}, {"fps": 24}, 0.7))):
            with self.subTest(frame=frame, fit=fit, out=out):
                proj = self.dir / f"joinrate{i}.json"
                proj.write_text(json.dumps({"output": f"joinrate{i}.mp4", "frame": frame, "fit": fit,
                                            "transition": {"type": "none"},
                                            "clips": [{"src": "q160.mp4", "in": 0, "out": out}] * 2}), encoding="utf-8")
                _, _, root = self._sequence(proj, f"joinrate{i}.fcpxml")
                seq = root.find("./library/event/project/sequence")
                rate = Fraction(root.find(f"./resources/format[@id='{seq.get('format')}']").get("frameDuration")[:-1])
                stated = Fraction(seq.get("duration")[:-1]) / rate
                work = self.dir / f"joinrate{i}_work"
                shutil.rmtree(work, ignore_errors=True)
                doc = json.loads(script("render.py", proj, "--fast", "--stop-after", "fit", "--work", work, "--json").stdout)
                frames = int(sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames", "-of", "csv=p=0", doc["output"]).stdout.strip())
                self.assertEqual(rate, Fraction(1, 24))
                self.assertEqual(frames, stated, "the render has the frames the sequence states")
                shutil.rmtree(work, ignore_errors=True)

    def test_a_one_clip_sequence_takes_the_fit_objects_frame(self):
        """#506: the render's fit stage gives fit.py the fit object's aspect, sides and mode, the
        frame's only where it has none; the export sized the sequence from the frame alone. So
        frame 16:9 with fit 1:1 rendered a square and exported 640x360, and with frame.aspect
        "16/9" (which fit.aspect replaces) the export dropped the aspect altogether. The sequence
        is compared with the rendered file's size."""
        for i, (frame, fit) in enumerate((({"aspect": "16:9"}, {"aspect": "1:1"}),
                                          ({"aspect": "16/9"}, {"aspect": "1:1"}),
                                          ({"aspect": "1:1"}, {"width": 200}),
                                          ({"aspect": "16:9", "width": 320}, {"aspect": "4:5", "fit": "crop"}))):
            with self.subTest(frame=frame, fit=fit):
                proj = self.dir / f"fit_object{i}.json"
                proj.write_text(json.dumps({"output": f"fit_object{i}.mp4", "frame": frame, "fit": fit,
                                            "clips": [{"src": "a.mp4", "in": 0, "out": 1}]}), encoding="utf-8")
                _, seq_size, _ = self._sequence(proj, f"fit_object{i}.fcpxml")
                work = self.dir / f"fit_object{i}_work"
                shutil.rmtree(work, ignore_errors=True)
                doc = json.loads(script("render.py", proj, "--fast", "--stop-after", "fit", "--work", work, "--json").stdout)
                m = probe(doc["output"])
                self.assertEqual(seq_size, (m["video"]["width"], m["video"]["height"]))
                shutil.rmtree(work, ignore_errors=True)
        # a fit object whose aspect fit.py would refuse is refused by the export under its own name
        proj = self.dir / "fit_object_bad.json"
        proj.write_text(json.dumps({"frame": {"aspect": "16:9"}, "fit": {"aspect": "wide"},
                                    "clips": [{"src": "a.mp4", "in": 0, "out": 1}]}), encoding="utf-8")
        proc = script("render.py", proj, "--export-timeline", self.dir / "fit_object_bad.fcpxml", "--json", expect_fail=True)
        self.assertIn("fit.aspect 'wide'", json.loads(proc.stdout)["error"]["message"])

    def test_the_export_and_fit_py_read_one_aspect_grammar(self):
        """The render hands frame.aspect to fit.py --aspect, so the export refuses what fit.py
        refuses: it once read "16/9" and "2.39:1" and wrote a sequence for a project whose render
        then failed with fit.py's "bad aspect"."""
        tl_mod = self._tl()
        for aspect in ("16:9", "4:5", "16/9", "2.39:1", "0:9", "wide"):
            with self.subTest(aspect=aspect):
                fit = subprocess.run([sys.executable, str(SCRIPTS / "fit.py"), str(self.dir / "a.mp4"), "--aspect", aspect,
                                      "--dry-run", "-o", str(self.dir / "aspect.mp4")],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    tl_mod.build({"clips": [{"src": "a.mp4"}], "frame": {"aspect": aspect}},
                                 self._probes(**{"a.mp4": 8}), lambda p: f"/m/{p}")
                    exported = True
                except tl_mod.TimelineError:
                    exported = False
                self.assertEqual(exported, fit.returncode == 0, fit.stderr[-300:])
                # 0:9 is a zero ratio -- no aspect, as fit.py ran it in 2.2.1 -- in both
                self.assertEqual(exported, aspect in ("16:9", "4:5", "0:9"))
        # ...but only an aspect the render hands to fit.py: when the project's own fit.aspect
        # replaces it, the render completes (sized by frame_from_preset()'s 2.2.1 match) and the
        # export writes that frame instead of refusing a project 2.2.1 exported
        proj = self.dir / "aspect_replaced.json"
        proj.write_text(json.dumps({"frame": {"aspect": "16/9"}, "fit": {"aspect": "16:9"}, "export": {"preset": "youtube"},
                                    "clips": [{"src": "a.mp4", "in": 0, "out": 2}]}), encoding="utf-8")
        doc, size, _ = self._sequence(proj, "aspect_replaced.fcpxml")
        self.assertEqual((doc["status"], size), ("completed", (1920, 1080)))
        proj.write_text(json.dumps({"frame": {"aspect": "16/9"}, "export": {"preset": "youtube"},
                                    "clips": [{"src": "a.mp4", "in": 0, "out": 2}]}), encoding="utf-8")
        proc = script("render.py", proj, "--export-timeline", self.dir / "aspect_refused.fcpxml", "--json", expect_fail=True)
        self.assertIn("frame.aspect '16/9'", json.loads(proc.stdout)["error"]["message"])

    def test_a_bad_time_is_an_input_failure_not_a_traceback(self):
        """A time that does not parse, and a project object that is not an object where the run
        reads it, are `kind: input` with the field named. A string frame, a string clip, a clip
        with no src or a transition between two clips was an AttributeError / KeyError traceback
        with nothing on stdout under --json in the render and the export alike; "export": "reels"
        and the other stage sections were one in the render only. A section the run never reads
        is not refused: 2.2.1 rendered a single clip with "transition": "none" (a batch.py
        project recipe carrying join.py's --transition none), and exported a timeline for
        "captions": "subs.srt", listing it as not exported."""
        both, render_only = "both", "render"
        cases = {
            "bad_time": ({"clips": [{"src": "a.mp4", "in": "1:xx", "out": 5}]}, "clips[0].in", both),
            "frame_str": ({"frame": "16:9", "clips": [{"src": "a.mp4"}]}, "frame: must be an object", both),
            "clip_str": ({"clips": ["a.mp4"]}, "clips[0]: must be an object", both),
            "clips_obj": ({"clips": {"src": "a.mp4"}}, "clips: must be a list", both),
            "no_src": ({"clips": [{"src": "a.mp4"}, {"in": 0}]}, "clips[1]: no src", both),
            "audio_str": ({"audio": "bed.m4a", "clips": [{"src": "a.mp4"}]}, "audio: must be an object", both),
            "joined_transition_str": ({"clips": [{"src": "a.mp4"}, {"src": "b.mp4"}], "transition": "fade"},
                                      "transition: must be an object", both),
            "export_str": ({"frame": {"aspect": "9:16"}, "export": "reels", "clips": [{"src": "a.mp4"}]},
                           "export: must be an object", render_only),
            "captions_str": ({"captions": "subs.srt", "loudness": True, "check": "reels", "clips": [{"src": "a.mp4"}]},
                             "captions: must be an object", render_only),
            "cut_snap_str": ({"clips": [{"src": "a.mp4", "in": 0, "out": 2, "snap": "beats"}]},
                             "clips[0].snap: must be an object", render_only),
        }
        for name, (body, message, where) in cases.items():
            with self.subTest(name):
                proj = self.dir / f"{name}.json"
                proj.write_text(json.dumps(body), encoding="utf-8")
                out = self.dir / f"{name}.edl"
                if out.exists():
                    out.unlink()
                # the render path refuses before its first stage (a bad time is cut.py's to refuse
                # there, with its own message)
                refused = ((("--dry-run",),) if name != "bad_time" else ()) + ((("--export-timeline", out),) if where == both else ())
                for argv in refused:
                    proc = sh(sys.executable, SCRIPTS / "render.py", proj, *argv, "--json", expect_fail=True)
                    self.assertNotIn("Traceback", proc.stderr)
                    err = json.loads(proc.stdout)["error"]
                    self.assertEqual(err["kind"], "input")
                    self.assertIn(message, err["message"])
                if where == both:
                    self.assertFalse(out.exists())
                else:
                    # the export never reads the section: it writes the timeline and names it
                    doc = json.loads(script("render.py", proj, "--export-timeline", out, "--json").stdout)
                    self.assertEqual(doc["status"], "completed")
                    self.assertTrue(out.exists())
        # nothing reads these, in either path: they render and export as in 2.2.1
        for name, body in (("single_transition_str", {"clips": [{"src": "a.mp4"}], "transition": "none"}),
                           ("uncut_snap_str", {"clips": [{"src": "a.mp4", "snap": "beats"}]})):
            with self.subTest(name):
                proj = self.dir / f"{name}.json"
                proj.write_text(json.dumps(dict(body, output=f"{name}.mp4")), encoding="utf-8")
                out = self.dir / f"{name}.edl"
                if out.exists():
                    out.unlink()
                self.assertEqual(json.loads(script("render.py", proj, "--dry-run", "--json").stdout)["status"], "completed")
                self.assertEqual(json.loads(script("render.py", proj, "--export-timeline", out, "--json").stdout)["status"],
                                 "completed")
        # --stop-after ends the run before a later stage reads its section: a preview of a
        # project with shorthand sections completed in 2.2.1 and still does
        for name, body, stop in (("stop_fit_captions", {"captions": "subs.srt", "export": "reels", "check": "youtube",
                                                        "graphics": "title", "clips": [{"src": "a.mp4", "in": 0, "out": 1}]}, "fit"),
                                 ("stop_clips_transition", {"transition": "fade",
                                                            "clips": [{"src": "a.mp4", "in": 0, "out": 1}, {"src": "b.mp4"}]}, "clips")):
            with self.subTest(name):
                proj = self.dir / f"{name}.json"
                proj.write_text(json.dumps(dict(body, output=f"{name}.mp4")), encoding="utf-8")
                doc = json.loads(script("render.py", proj, "--stop-after", stop, "--dry-run", "--json").stdout)
                self.assertEqual(doc["status"], "completed")
                # without --stop-after the full run reads them, and refuses up front
                proc = sh(sys.executable, SCRIPTS / "render.py", proj, "--dry-run", "--json", expect_fail=True)
                self.assertEqual(json.loads(proc.stdout)["error"]["kind"], "input")


class Issue458Tests(MediaFixtures):
    """#458 (audit 2026-11 of render.py, batch.py and sequence.py): one test per class, a subtest
    per finding. A refusal asserts the exit code, `kind` and that nothing was written."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.d = OUT / "i458"
        shutil.rmtree(cls.d, ignore_errors=True)
        cls.d.mkdir(parents=True)
        cls.clip = tiny_clip(cls.d / "clip.mp4", "testsrc2=size=160x90:rate=30", seconds=2, audio=True)

    def _project(self, name, body):
        p = self.d / name
        p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return p

    @staticmethod
    def _run(name, *args):
        """A tool run without the test helper's --overwrite; returns (exit code, document)."""
        proc = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args), "--json"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            doc = json.loads(proc.stdout)
        except ValueError:
            doc = {"stdout": proc.stdout, "stderr": proc.stderr[-800:]}
        return proc.returncode, doc

    def assertRefused(self, rc, doc, kind="input", *, unwritten=()):
        self.assertEqual(rc, 1, doc)
        self.assertEqual((doc.get("status"), (doc.get("error") or {}).get("kind")), ("failed", kind), doc)
        for path in unwritten:
            self.assertFalse(Path(path).exists(), f"{path} was written")

    # ------------------------------------------------------------- docs that disagreed with the code
    def test_the_reference_says_what_render_does(self):
        sys.path.insert(0, str(SCRIPTS))
        from export import PLATFORM_OF
        ref = (ROOT / "references" / "scripts.md").read_text(encoding="utf-8")
        with self.subTest("A86: a pack is written into the directory of -o"):
            out = self.d / "packdir" / "named.mp4"
            out.parent.mkdir(exist_ok=True)
            doc = json.loads(script("render.py", self.clip, "--template", "tiktok,x", "-o", out, "--dry-run", "--json").stdout)
            self.assertEqual(Path(doc["output"]), out.parent / "clip_pack.md")
            self.assertNotIn("whose `-o` names the directory", ref)
            self.assertIn("**directory of** `-o`", ref)
        with self.subTest("A103: normalize is on for every platform preset, and render has no --codec"):
            sentence = ref[ref.index("Since\n1.9.0 it is on by default"):][:400]
            for preset in PLATFORM_OF:
                self.assertIn(f"`{preset}`", sentence)
            self.assertNotIn("--codec`), the output's", ref)
            self.assertNotIn("--codec", script("render.py", "--help").stdout)
        with self.subTest("A107: the example brand carries no block that no tool reads"):
            brand = json.loads((ROOT / "examples" / "brand.json").read_text(encoding="utf-8"))
            self.assertNotIn("loudness", brand)

    # ---------------------------------------------------------------------------------- cache keys
    def test_a_cache_key_changes_with_every_file_the_output_depends_on(self):
        sys.path.insert(0, str(SCRIPTS))
        import batch
        with self.subTest("A277: a same-size rewrite within the same second"):
            f = self.d / "key.bin"
            f.write_bytes(b"a" * (3 << 20))
            os.utime(f, ns=(1_700_000_000_100_000_000,) * 2)
            before = batch.file_key(f)
            with open(f, "r+b") as fh:  # the middle MiB, which the key does not read
                fh.seek(3 << 19)
                fh.write(b"b" * 1024)
            os.utime(f, ns=(1_700_000_000_600_000_000,) * 2)
            self.assertEqual(f.stat().st_size, 3 << 20)
            self.assertNotEqual(batch.file_key(f), before)
        with self.subTest("A80: a file the project recipe's project names"):
            cues = self.d / "a80_cues.txt"
            cues.write_text("0:00-0:01 One\n", encoding="utf-8")
            proj = self._project("a80_project.json", {"clips": [{"src": "x.mp4"}], "captions": {"text": "a80_cues.txt"}})
            recipe = {"project": str(proj)}
            first = batch.recipe_key(recipe)
            self.assertEqual(batch.recipe_key(recipe), first)
            # a project of the wrong shape is the render's to refuse, per item: the key does not raise
            bad = self._project("a80_bad.json", {"clips": 1})
            self.assertIsInstance(batch.recipe_key({"project": str(bad)}), str)
            cues.write_text("0:00-0:01 Two\n", encoding="utf-8")
            self.assertNotEqual(batch.recipe_key(recipe), first)
        with self.subTest("A81: --watch reads the recipe's files again on every pass"):
            folder = self.d / "a81"
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            shutil.copy(self.clip, folder / "one.mp4")
            os.utime(folder / "one.mp4", (1_700_000_000, 1_700_000_000))  # settled
            proj = folder / "p.json"
            proj.write_text(json.dumps({"clips": [{"src": "x.mp4"}], "export": {"preset": "copy"}}), encoding="utf-8")
            recipe = folder / "r.json"
            recipe.write_text(json.dumps({"glob": "*.mp4", "project": "p.json", "output_dir": str(self.d / "a81_out")}),
                              encoding="utf-8")
            shutil.rmtree(self.d / "a81_out", ignore_errors=True)
            # two passes: the sleep between them edits the project, the second sleep stops the watch
            code = ("import json, sys, time\nsys.path.insert(0, sys.argv[1])\nimport batch\ncalls = []\nP = sys.argv[2]\n"
                    "def sleep(_s):\n    calls.append(1)\n    if len(calls) > 1:\n        raise KeyboardInterrupt\n"
                    "    p = P\n    d = json.load(open(p))\n    d['export'] = {'preset': 'youtube'}\n"
                    "    json.dump(d, open(p, 'w'))\n"
                    # batch's own name for the module only: time.sleep itself is used by locks and children
                    "class Clock:\n    def __getattr__(self, name):\n        return getattr(time, name)\n"
                    "batch.time = Clock()\nbatch.time.sleep = sleep\nsys.argv = ['batch.py', sys.argv[3], '--recipe', sys.argv[4], '--watch', '1', '--json']\n"
                    "sys.exit(batch.main())\n")
            proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(proj), str(folder), str(recipe)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            doc = json.loads(proc.stdout or "{}") or {"stderr": proc.stderr[-800:]}
            row = (doc.get("results") or [doc])[0]
            self.assertFalse(row.get("cached"), "the edited project was served from the first pass's cache")
            self.assertTrue(row["ok"], row)
        with self.subTest("A100: render --cache serves the chapters stage of an inline chapters list"):
            cdir = self.d / "a100_cache"
            shutil.rmtree(cdir, ignore_errors=True)
            out = self.d / "a100.mp4"
            proj = self._project("a100.json", {"output": str(out), "clips": [{"src": str(self.clip), "in": 0, "out": 1}],
                                               "export": {"preset": "copy"}, "chapters": [{"at": 0, "title": "One"}]})
            script("render.py", proj, "--cache", cdir, "--json")
            doc = json.loads(script("render.py", proj, "--cache", cdir, "--json").stdout)
            self.assertIn("chapters", doc["cache"]["hits"], doc["cache"])

    # ----------------------------------------------------------------------------- work directory
    def test_the_work_directory_belongs_to_one_run(self):
        out = self.d / "w.mp4"
        proj = self._project("w.json", {"output": str(out), "clips": [{"src": str(self.clip), "in": 0, "out": 1}],
                                        "chapters": [{"at": 0, "title": "One"}]})
        with self.subTest("A77: a later run with the same PID leaves an earlier run's directory alone"):
            code = ("import os, sys\nsys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\n"
                    "kept = Path(sys.argv[2][:-4] + f'_work_{os.getpid()}')\nkept.mkdir(exist_ok=True)\n"
                    "(kept / 'clip00.mp4').write_bytes(b'an earlier preview')\nimport render\n"
                    "sys.argv = ['render.py', sys.argv[3], '--overwrite', '--json']\nrender.main()\n"
                    "print('KEPT' if (kept / 'clip00.mp4').exists() else 'GONE', file=sys.stderr)\n")
            proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(out), str(proj)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.stderr.strip().splitlines()[-1], "KEPT", proc.stderr[-600:])
            for d in self.d.glob("w_work_*"):
                shutil.rmtree(d)
        with self.subTest("A98: a re-run with the same --work replaces its own stage files"):
            work = self.d / "w98"
            shutil.rmtree(work, ignore_errors=True)
            for _ in range(2):
                out.unlink(missing_ok=True)
                rc, doc = self._run("render.py", proj, "--work", work)
                self.assertEqual((rc, doc.get("status")), (0, "completed"), doc)
            # one the caller changed is still somebody else's
            (work / "clip00.mp4").write_bytes(b"edited")
            out.unlink()
            rc, doc = self._run("render.py", proj, "--work", work)
            self.assertRefused(rc, doc, unwritten=[out])
            self.assertEqual((work / "clip00.mp4").read_bytes(), b"edited")
            shutil.rmtree(work)
        with self.subTest("a cache hit does not replace a stage file the caller changed either"):
            work, cache = self.d / "w98c", self.d / "w98c_cache"
            for d in (work, cache):
                shutil.rmtree(d, ignore_errors=True)
            out.unlink(missing_ok=True)
            rc, doc = self._run("render.py", proj, "--work", work, "--cache", cache)
            self.assertEqual((rc, doc.get("status")), (0, "completed"), doc)
            (work / "clip00.mp4").write_bytes(b"edited")
            out.unlink()
            rc, doc = self._run("render.py", proj, "--work", work, "--cache", cache)
            self.assertRefused(rc, doc, unwritten=[out])
            self.assertEqual((work / "clip00.mp4").read_bytes(), b"edited")
            for d in (work, cache):
                shutil.rmtree(d)
        with self.subTest("A99: a dry run writes nothing into --work and removes one it created"):
            work = self.d / "w99"
            shutil.rmtree(work, ignore_errors=True)
            out.unlink(missing_ok=True)
            rc, doc = self._run("render.py", proj, "--work", work, "--dry-run")
            self.assertEqual((rc, doc.get("status"), doc.get("stages")), (0, "completed", ["clips", "chapters"]), doc)
            self.assertFalse(work.exists())
            work.mkdir()
            rc, doc = self._run("render.py", proj, "--work", work, "--dry-run")
            self.assertEqual(rc, 0, doc)
            self.assertEqual(list(work.iterdir()), [])
            shutil.rmtree(work)

    # ------------------------------------------------------------------- output name or container
    def test_export_copy_and_gif_refuse_audio_filenames(self):
        out = self.d / "export_as_audio.m4a"
        project = self._project("export_copy_as_audio.json", {
            "output": str(out), "clips": [{"src": str(self.clip)}], "export": {"preset": "copy"},
        })
        commands = (("export.py", self.clip, "--preset", "copy", "-o", out),
                    ("export.py", self.clip, "--preset", "gif", "-o", out), ("render.py", project))
        for command in commands:
            for mode in (("--dry-run",), ()):
                with self.subTest(command=command, dry_run=bool(mode)):
                    rc, doc = self._run(*command, *mode)
                    self.assertRefused(rc, doc, unwritten=[out])
                    self.assertEqual(doc["error"]["reason"], "output_extension_audio_only", doc)
                    self.assertEqual(doc.get("commands", []), [])

    def test_render_copy_refuses_a_picture_delivered_as_audio(self):
        out = self.d / "picture_as_audio.m4a"
        project = self._project("picture_as_audio.json", {"output": str(out), "clips": [{"src": str(self.clip)}]})
        for mode in (("--dry-run",), ()):
            with self.subTest(dry_run=bool(mode)):
                rc, doc = self._run("render.py", project, *mode)
                self.assertRefused(rc, doc, unwritten=[out])
                self.assertEqual(doc["error"]["reason"], "output_extension_audio_only", doc)
                self.assertEqual(doc.get("commands", []), [])

        # A real MPEG-4 audio source can still be copied under the audio-only extension.
        source = self.d / "sound_only.mp4"
        out = self.d / "sound_only.m4a"
        sh("ffmpeg", "-y", "-v", "error", "-i", self.clip, "-vn", "-c:a", "copy", source)
        audio_project = self._project("audio_copy.json", {"output": str(out), "clips": [{"src": str(source)}]})
        for mode in (("--dry-run",), ()):
            rc, doc = self._run("render.py", audio_project, *mode)
            self.assertEqual((rc, doc["status"]), (0, "completed"), doc)
        self.assertEqual(out.read_bytes(), source.read_bytes())

    def test_an_output_is_named_for_the_container_it_holds(self):
        with self.subTest("A84: no export stage, a .webm name"):
            out = self.d / "a84.webm"
            for clip in ({"src": str(self.clip), "in": 0, "out": 1}, {"src": str(self.clip)}):
                for dry in ((), ("--dry-run",)):
                    with self.subTest(clip=clip, dry=bool(dry)):
                        proj = self._project("a84.json", {"output": str(out), "clips": [clip]})
                        rc, doc = self._run("render.py", proj, *dry)
                        self.assertRefused(rc, doc, unwritten=[out])
                        self.assertIn('no "export" stage', doc["error"]["message"])
            proj = self._project("a84_mov.json", {"output": str(self.d / "a84.mov"), "clips": [{"src": str(self.clip), "in": 0, "out": 1}]})
            self.assertEqual(json.loads(script("render.py", proj, "--json").stdout)["status"], "completed",
                             "a .mov is the MP4 family")
        with self.subTest("A83: batch names a .webm source's output .mp4"):
            if "libvpx-vp9" not in sh("ffmpeg", "-hide_banner", "-encoders").stdout:
                self.skipTest("no libvpx-vp9 encoder to make a WebM fixture")
            folder = self.d / "a83"
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.clip, "-c:v", "libvpx-vp9", "-deadline",
               "realtime", "-c:a", "libopus", folder / "w.webm")
            recipe = folder / "r.json"
            recipe.write_text(json.dumps({"glob": "*.webm", "output_dir": str(self.d / "a83_out"),
                                          "steps": [["fit.py", "{in}", "--width", "80", "-o", "{out}"]]}), encoding="utf-8")
            shutil.rmtree(self.d / "a83_out", ignore_errors=True)
            doc = json.loads(script("batch.py", folder, "--recipe", recipe, "--json").stdout)
            row = doc["results"][0]
            self.assertTrue(row["ok"], row)
            self.assertEqual(Path(row["output"]).name, "w_out.mp4")
        with self.subTest("A108: sequence.py --dir . is named after the folder"):
            frames = self.d / "frames108"
            shutil.rmtree(frames, ignore_errors=True)
            frames.mkdir()
            for i in range(3):
                sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32",
                   "-frames:v", "1", frames / f"f{i}.png")
            target = self.d / "frames108_sequence.mp4"
            target.unlink(missing_ok=True)
            proc = subprocess.run([sys.executable, str(SCRIPTS / "sequence.py"), "--dir", ".", "--pattern", "*.png",
                                   "--fps", "10", "--json"], cwd=frames, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
            self.assertEqual(Path(json.loads(proc.stdout)["output"]).resolve(), target.resolve())

    # ------------------------------------------------------- caller strings in a line-based format
    def test_caller_text_cannot_add_lines_to_a_file_render_writes(self):
        out = self.d / "a260.mp4"
        for ch in ("\n", "\r", "\x00"):
            with self.subTest(f"A260: a chapter title with U+{ord(ch):04X}"):
                proj = self._project("a260.json", {"output": str(out), "clips": [{"src": str(self.clip)}],
                                                   "chapters": [{"at": 0, "title": f"Intro{ch}0:01 Evil"}]})
                for dry in ((), ("--dry-run",)):
                    rc, doc = self._run("render.py", proj, *dry)
                    self.assertRefused(rc, doc, unwritten=[out])
                    self.assertIn("chapters[0].title", doc["error"]["message"])
        with self.subTest("A264: a lone surrogate in a project string"):
            p = self.d / "a264.json"
            p.write_text('{"output": "%s", "clips": [{"src": "%s"}], "chapters": [{"at": 0, "title": "A\\ud83d"}]}'
                         % (out.as_posix(), Path(self.clip).as_posix()), encoding="utf-8")
            rc, doc = self._run("render.py", p)
            self.assertRefused(rc, doc, unwritten=[out])
            self.assertIn("surrogate", doc["error"]["message"])
        with self.subTest("A261: names in an EDL stay on their line"):
            from _common import timeline as tl_mod
            probes = {f"/m/a{c}b.mp4": {"duration": 4, "video": {"fps": 30.0, "width": 320, "height": 180},
                                         "audio": {"channels": 2}} for c in ("\n", "\r", "\u2028", "\x0b")}
            proj = {"output": "x\ny.mp4", "clips": [{"src": p} for p in probes], "transition": {"type": "none"},
                    "chapters": [{"at": 1, "title": "One\x85Two"}]}
            tl = tl_mod.build(proj, probes, lambda p: p)
            lines = tl_mod.to_edl(tl).split("\n")
            self.assertTrue(all(ln == "" or ln[:3].isdigit() or ln.startswith(("TITLE:", "FCM:", "* ")) for ln in lines), lines)
            self.assertEqual(len([ln for ln in lines if ln[:3].isdigit()]), 4)
            self.assertEqual(tl_mod.to_edl(tl).splitlines(), lines[:-1], "no line break str.splitlines() sees is left")
            import xml.etree.ElementTree as ET
            ET.fromstring(tl_mod.to_fcpxml(tl).encode("utf-8"))  # a control character made it not well-formed
        with self.subTest("A263: a '|' in a pack's file name stays in its column"):
            sys.path.insert(0, str(SCRIPTS))
            import render
            import report
            cells = ["tiktok", "a | b\\c.mp4", "1.0 MB", "2.00 s", "pass"]
            row = "| " + " | ".join(render.md_cell(c) for c in cells) + " |"
            self.assertEqual(report.md_cells(row), cells)
            pack = self.d / "a263_pack.md"
            pack.write_text("# Social pack — a\n\n| platform | file | size | duration | check |\n|---|---|---|---|---|\n"
                            + row + "\n", encoding="utf-8")
            html_out = self.d / "a263.html"
            html_out.unlink(missing_ok=True)
            doc = json.loads(script("report.py", "--pack", pack, "-o", html_out, "--json").stdout)
            self.assertEqual(doc["pack"][0]["check"], "pass")
            self.assertEqual(doc["pack"][0]["file"], "a | b\\c.mp4")
            self.assertEqual(render.md_line("a\nb\u2028c"), "a b c")

    # ------------------------------------------------------------------------------- EDL limits
    def test_an_edl_refuses_what_cmx_3600_cannot_number(self):
        from fractions import Fraction
        from _common import timeline as tl_mod
        probes = {"/m/a.mp4": {"duration": 400, "video": {"fps": 30.0, "width": 320, "height": 180}, "audio": {"channels": 2}}}
        with self.subTest("A265: 1000 events"):
            tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": i * 0.2, "out": i * 0.2 + 0.1} for i in range(1000)],
                               "transition": {"type": "none"}}, probes, lambda p: f"/m/{p}")
            with self.assertRaisesRegex(tl_mod.TimelineError, "three digits"):
                tl_mod.to_edl(tl)
            tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": i * 0.2, "out": i * 0.2 + 0.1} for i in range(999)],
                               "transition": {"type": "none"}}, probes, lambda p: f"/m/{p}")
            self.assertEqual(max(int(ln[:3]) for ln in tl_mod.to_edl(tl).splitlines() if ln[:3].isdigit()), 999)
        with self.subTest("A266: a source timecode past midnight wraps"):
            probes["/m/a.mp4"]["timecode"] = {"value": "23:59:59:00", "drop_frame": False}
            tl = tl_mod.build({"clips": [{"src": "a.mp4", "in": 0, "out": 3}]}, probes, lambda p: f"/m/{p}")
            event = [ln for ln in tl_mod.to_edl(tl).splitlines() if ln[:3].isdigit()][0]
            self.assertIn(" C        23:59:59:00 00:00:02:00 01:00:00:00 01:00:03:00", event)
            # drop-frame: a 29.97 day is 2589408 frames
            self.assertEqual(tl_mod._tc_label(2589408 + 30, Fraction(30000, 1001), True), "00:00:01;00")

    # ----------------------------------------------------------------------------------- the rest
    def test_render_and_batch_do_what_their_flags_say(self):
        with self.subTest("A87: --stop-after export stops, and a check it never reads is not read"):
            out = self.d / "a87.mp4"
            out.unlink(missing_ok=True)
            proj = self._project("a87.json", {"output": str(out), "clips": [{"src": str(self.clip)}],
                                              "chapters": [{"at": 0, "title": "A"}, {"at": 1, "title": "B"}], "check": "bad"})
            rc, doc = self._run("render.py", proj, "--stop-after", "export")
            self.assertEqual((rc, doc.get("status")), (0, "completed"), doc)
            self.assertNotIn("chapters", doc["stages"])
            self.assertEqual(json.loads(sh("ffprobe", "-v", "error", "-show_chapters", "-of", "json", out).stdout)["chapters"], [])
            out.unlink()
            rc, doc = self._run("render.py", proj)
            self.assertRefused(rc, doc, unwritten=[out])
        with self.subTest("A96: an executed plan reports where its output is"):
            plan_dir = self.d / "a96"
            shutil.rmtree(plan_dir, ignore_errors=True)
            (plan_dir / "other").mkdir(parents=True)
            shutil.copy(self.clip, plan_dir / "in.mp4")
            subprocess.run([sys.executable, str(SCRIPTS / "cut.py"), "in.mp4", "--start", "0", "--end", "1", "-o", "o96.mp4",
                            "--plan", "plan.json", "--json"], cwd=plan_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            proc = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "../plan.json", "--json"], cwd=plan_dir / "other",
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "completed", doc)
            self.assertEqual(Path(doc["output"]), (plan_dir / "o96.mp4").resolve())
        with self.subTest("A82: a glob matches camera files in either case, and an empty batch says so"):
            folder = self.d / "a82"
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            shutil.copy(self.clip, folder / "GOPR0001.MP4")
            recipe = folder / "r.json"
            recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": str(self.d / "a82_out"),
                                          "steps": [["probe.py", "{in}"]]}), encoding="utf-8")
            doc = json.loads(script("batch.py", folder, "--recipe", recipe, "--json").stdout)
            self.assertEqual(doc["total"], 1, doc)
            recipe.write_text(json.dumps({"glob": "*.mov", "output_dir": str(self.d / "a82_out"),
                                          "steps": [["probe.py", "{in}"]]}), encoding="utf-8")
            doc = json.loads(script("batch.py", folder, "--recipe", recipe, "--json").stdout)
            self.assertEqual(doc["total"], 0)
            self.assertTrue(any("matches the recipe's glob" in n for n in doc.get("notes") or []), doc.get("notes"))
            # a class's first member may be "[" or "]": the class still ends, and the letters after it fold
            import fnmatch
            import batch
            for pattern, name in (("[[]take*.mp4", "[TAKE001.MP4"), ("[]a]x.mp4", "aX.MP4"), ("[!]a]x.mp4", "bX.Mp4"),
                                  ("[!]take*.mp4", "[!]TAKE1.MP4"), ("[take*.mp4", "[TAKE1.MP4")):  # unclosed: literal
                self.assertTrue(fnmatch.fnmatchcase(name, batch.caseless_glob(pattern)), (pattern, name))
            self.assertFalse(fnmatch.fnmatchcase("AC.mp4", batch.caseless_glob("[ab]c.mp4")))  # a class keeps its case
        with self.subTest("A267: --export-timeline probes each file once"):
            proj = self._project("a267.json", {"output": "x.mp4", "clips": [{"src": str(self.clip), "in": i, "out": i + 0.5}
                                                                             for i in (0, 0.5, 1)], "transition": {"type": "none"}})
            code = ("import sys\nsys.path.insert(0, sys.argv[1])\nimport render\ncalls = []\nreal = render.probe\n"
                    "render.probe = lambda p, *a, **k: (calls.append(p), real(p, *a, **k))[1]\n"
                    "sys.argv = ['render.py', sys.argv[2], '--export-timeline', sys.argv[3], '--dry-run', '--json']\n"
                    "render.main()\nprint(f'PROBES {len(calls)}', file=sys.stderr)\n")
            proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(proj), str(self.d / "a267.edl")],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.stderr.strip().splitlines()[-1], "PROBES 1", proc.stderr[-600:])
        with self.subTest("A102: --list-templates and --init under --json print a JSON document"):
            doc = json.loads(script("render.py", "--list-templates", "--json").stdout)
            self.assertEqual(doc["status"], "completed")
            self.assertIn("audiogram", [t["template"] for t in doc["templates"]])
            for t in doc["templates"]:  # the four edges are always there, 0 where a destination has none
                self.assertEqual(sorted(t["safe"]), ["bottom", "left", "right", "top"], t)
            init = self.d / "a102_init.json"
            init.unlink(missing_ok=True)
            doc = json.loads(script("render.py", "--init", init, "--json").stdout)
            self.assertEqual((doc["status"], Path(doc["output"])), ("completed", init))
        with self.subTest("A90: the audiogram template takes --brand and --title"):
            brand = self.d / "a90_brand.json"
            brand.write_text(json.dumps({"colors": {"primary": "FF0000"}}), encoding="utf-8")
            plate = self.d / "a90_plate.png"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64",
               "-frames:v", "1", plate)
            filled = self.d / "a90_project.json"
            filled.unlink(missing_ok=True)
            script("render.py", self.clip, "--template", "audiogram", "--image", plate, "--brand", brand,
                   "--title", "Episode 12", "--write-project", filled, "--json")
            proj = json.loads(filled.read_text(encoding="utf-8"))
            self.assertEqual(proj["brand"], os.path.abspath(brand))
            self.assertIn("Episode 12", json.dumps(proj.get("graphics")))



@unittest.skipIf(platform.system() == "Windows", "the lean build is a #!/bin/sh ffmpeg/ffprobe on a PATH shim")
class MissingComponentFirstTests(unittest.TestCase):
    """#510: a real render ran its earlier stages (cut, fit) and then failed at the stage that needs
    a filter the build lacks, where its --dry-run was refused before anything encoded; waveform.py
    encoded the visualisation before its title stage failed. A real run now runs its own dry run
    first and is refused with the same document. The lean build is a PATH shim whose -filters
    list leaves drawtext out; every other call runs the real binary."""

    @classmethod
    def setUpClass(cls):
        cls.d = OUT / "missing_first"
        shutil.rmtree(cls.d, ignore_errors=True)
        (cls.d / "bin").mkdir(parents=True)
        for name in ("ffmpeg", "ffprobe"):
            real = shutil.which(name)
            if not real:
                raise unittest.SkipTest(f"{name} not on PATH")
            if "drawtext" not in subprocess.run([real, "-hide_banner", "-filters"], stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, text=True).stdout:
                raise unittest.SkipTest("this build has no drawtext to hide")
            shim = cls.d / "bin" / name
            shim.write_text("#!/bin/sh\n"
                            'for a in "$@"; do if [ "$a" = "-filters" ]; then '
                            f'"{real}" "$@" | grep -v " drawtext "; exit 0; fi; done\n'
                            f'exec "{real}" "$@"\n', encoding="utf-8")
            shim.chmod(0o755)
        cls.env = dict(os.environ, PATH=str(cls.d / "bin") + os.pathsep + os.environ.get("PATH", ""))
        cls.clip = tiny_clip(cls.d / "clip.mp4", "testsrc2=size=320x180:rate=30", seconds=2, audio=True)
        cls.wav = cls.d / "tone.wav"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", cls.wav)

    def _run(self, name, *args):
        proc = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args), "--json"], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        return proc.returncode, json.loads(proc.stdout), proc.stderr

    def test_a_real_run_is_refused_before_its_first_stage_as_its_dry_run_is(self):
        cases = (("render.py", [self.clip, "--template", "reels", "--title", "T"], "→ fit.py"),
                 ("waveform.py", [self.wav, "--title", "Hi", "--width", "320", "--height", "180"], None))
        for name, args, first_stage in cases:
            with self.subTest(tool=name):
                out = self.d / f"{Path(name).stem}.mp4"
                out.unlink(missing_ok=True)
                rc_dry, dry, _ = self._run(name, *args, "-o", out, "--dry-run")
                rc, real, stderr = self._run(name, *args, "-o", out)
                self.assertEqual((rc_dry, rc), (1, 1), (dry, real))
                keys = ("kind", "message", "reason", "details", "hint")
                self.assertEqual({k: real["error"].get(k) for k in keys}, {k: dry["error"].get(k) for k in keys})
                self.assertEqual((real["error"]["reason"], real["error"]["details"], real.get("stage")),
                                 ("filter_missing", {"name": "drawtext"}, "graphics.py"), real)
                self.assertEqual(real["commands"], [], "no stage encoded before the refusal")
                if first_stage:
                    self.assertNotIn(first_stage, stderr)
                self.assertFalse(out.exists())
        # review of #537: `--dry-run --json` were appended after a `--` that ends the options, the
        # child refused them, and the check was skipped without a word
        out = self.d / "dashdash.mp4"
        out.unlink(missing_ok=True)
        proc = subprocess.run([sys.executable, str(SCRIPTS / "render.py"), "--template", "reels", "--title", "T", "-o", str(out),
                               "--json", "--", str(self.clip)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
        rc, real, stderr = proc.returncode, json.loads(proc.stdout), proc.stderr
        self.assertEqual((rc, real["error"]["reason"], real["commands"]), (1, "filter_missing", []), stderr[-800:])
        self.assertNotIn("→ fit.py", stderr)
        # with every filter there, the same render completes: the dry run first refuses nothing else
        out = self.d / "render_ok.mp4"
        out.unlink(missing_ok=True)
        doc = json.loads(script("render.py", self.clip, "--template", "reels", "--title", "T", "-o", out, "--fast", "--json").stdout)
        self.assertEqual(doc["status"], "completed")



class Issue429DecidedTests(unittest.TestCase):
    """#510, the four #429 items as decided: a batch step that writes without naming {out}, a
    side file lost with an intermediate, a side input built from {in} in the batch cache key, and
    what an interrupted render or batch says it kept."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.d = OUT / "i429"
        shutil.rmtree(cls.d, ignore_errors=True)
        cls.d.mkdir(parents=True)
        cls.clip = tiny_clip(cls.d / "clip.mp4", "testsrc2=size=160x90:rate=30", seconds=2, audio=True)
        cls.cues = cls.d / "cues.txt"
        cls.cues.write_text("00:00:00.300 --> 00:00:01.200 hello there\n", encoding="utf-8")

    def _run(self, name, *args, env=None):
        proc = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args), "--json"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            return proc.returncode, json.loads(proc.stdout), proc.stderr
        except ValueError:
            raise AssertionError(proc.stderr[-1500:])

    def _folder(self, name, n=2):
        folder = self.d / name
        (folder / "in").mkdir(parents=True)
        for i in range(n):
            shutil.copy(self.clip, folder / "in" / f"{'ab'[i]}.mp4")
        return folder

    def _recipe(self, folder, steps, name="r.json"):
        recipe = folder / name
        recipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": str(folder / "out"), "steps": steps}), encoding="utf-8")
        return recipe

    def test_a_batch_step_that_writes_without_out_stops_the_batch(self):
        folder = self._folder("no_out")
        recipe = self._recipe(folder, [["metadata.py", "{in}", "--title", "T"], ["fit.py", "{in}", "--duration", "1", "--method", "speed", "-o", "{out}"]])
        stray = folder / "in" / "a_meta.mp4"
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                rc, doc, _ = self._run("batch.py", folder / "in", "--recipe", recipe, *(["--dry-run"] if dry else []))
                self.assertEqual((rc, doc["error"]["kind"], doc["error"]["reason"]), (1, "input", "step_writes_without_out"), doc["error"])
                det = doc["error"]["details"]
                self.assertEqual((det["step"], det["tool"], det["file"], det["written"]), (0, "metadata.py", str(stray), not dry))
                self.assertEqual(stray.exists(), not dry)
                self.assertIn("nothing was written" if dry else "left it there", doc["error"]["message"])
                self.assertEqual([r.get("skipped") for r in doc["results"]], [None, "recipe_refused"], "the batch stops at the first item")
                self.assertFalse(list((folder / "out").glob("*.mp4")))
        # a step that only reads (output null) is untouched, as is one that names its own -o
        recipe = self._recipe(folder, [["check.py", "{in}"], ["look.py", "{in}", "-o", "{in}.png"],
                                       ["fit.py", "{in}", "--duration", "1", "--method", "speed", "-o", "{out}"]], "r2.json")
        shutil.rmtree(folder / "in")
        (folder / "in").mkdir()
        shutil.copy(self.clip, folder / "in" / "a.mp4")
        rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe)
        self.assertEqual((rc, doc["status"]), (0, "completed"), err[-800:])

    def test_a_render_delivers_its_captions_srt_beside_the_output(self):
        out = self.d / "cap.mp4"
        proj = self.d / "cap.json"
        proj.write_text(json.dumps({"output": str(out), "clips": [{"src": str(self.clip)}], "captions": {"text": str(self.cues)}}),
                        encoding="utf-8")
        srt = self.d / "cap.srt"
        rc, plan, _ = self._run("render.py", proj, "--dry-run")
        self.assertEqual((rc, plan["caption_srt"], srt.exists()), (0, str(srt), False))
        rc, doc, err = self._run("render.py", proj, "--fast")
        self.assertEqual((rc, doc["caption_srt"]), (0, str(srt)), err[-800:])
        self.assertIn("hello there", srt.read_text(encoding="utf-8"))
        # its guard is the output's, before the first stage: an existing SRT is refused without --overwrite
        out.unlink()
        rc, doc, _ = self._run("render.py", proj, "--fast")
        self.assertEqual((rc, doc["error"]["reason"], doc["commands"]), (1, "output_exists", []))
        self.assertFalse(out.exists())
        # a later stage that changed the timeline (the export trimmed the delivery): not delivered, said so
        import render
        from _common import STATE
        STATE.reset()
        try:
            render._LAST_DOC.clear()
            render._LAST_DOC["trimmed"] = {"from": 95.0, "to": 90.0}
            made = {"srt": str(srt), "video": str(self.clip), "cached": False}
            with unittest.mock.patch.object(render, "place_output") as placed, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(render.deliver_caption_srt(str(self.d / "trimmed.srt"), made, str(self.clip)))
            placed.assert_not_called()
            self.assertEqual([(s["code"], s["reason"]) for s in STATE.skipped], [("caption_srt_not_delivered", "timeline_changed")])
        finally:
            render._LAST_DOC.clear()
            STATE.reset()

    def test_a_batch_records_a_side_file_lost_with_an_intermediate(self):
        folder = self._folder("side", n=1)
        recipe = self._recipe(folder, [["caption.py", "{in}", "--text", str(self.cues), "-o", "{out}"],
                                       ["fit.py", "{in}", "--duration", "1", "--method", "speed", "-o", "{out}"]])
        rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe)
        self.assertEqual(rc, 0, err[-800:])
        lost = [s for s in doc["diagnostics"]["skipped"] if s["code"] == "batch_side_file_not_delivered"]
        self.assertEqual([(s["step"], s["tool"], s["files"]) for s in lost], [(0, "caption.py", ["step0.srt"])])

    def test_a_side_input_built_from_in_is_in_the_batch_cache_key(self):
        folder = self._folder("side_key", n=1)
        logo = folder / "in" / "a.mp4.png"

        def plate(colour):
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=32x32", "-frames:v", "1", logo)
        plate("red")
        recipe = self._recipe(folder, [["overlay.py", "{in}", "--image", "{in}.png", "-o", "{out}"]])
        out = folder / "out" / "a_out.mp4"

        def run():
            rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--overwrite")
            self.assertEqual(rc, 0, err[-800:])
            return doc["results"][0], out.read_bytes()
        first, red = run()
        again, _ = run()
        self.assertTrue(again.get("cached"))
        plate("blue")  # edited, not removed
        edited, blue = run()
        self.assertFalse(edited.get("cached"), "an edited side input is a change the cache must see")
        self.assertNotEqual(red, blue)
        # a side input built from a later step's {in} (an intermediate) cannot be keyed: never served
        recipe = self._recipe(folder, [["fit.py", "{in}", "--duration", "1", "--method", "speed", "-o", "{out}"],
                                       ["check.py", "{in}", "--compare", "{in}.ref.mp4"]], "r2.json")
        rc, doc, _ = self._run("batch.py", folder / "in", "--recipe", recipe, "--overwrite")
        self.assertEqual(doc["results"][0]["cache_miss"], {"reason": "side_input_unresolved", "step": 1, "argument": "{in}.ref.mp4"})

    def test_render_cache_keys_the_files_a_brand_file_names(self):
        """The sweep of the cache-key item: a stage's key hashed the --brand file's own bytes, so a
        font file replaced under the same name was served from the cache with the old font drawn."""
        fonts = [f for f in (font_for_script("Latin"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf") if f and os.path.isfile(str(f))]
        fonts = sorted({os.path.realpath(str(f)) for f in fonts})
        if len(fonts) < 2:
            self.skipTest("two font files are needed")
        font = self.d / "brand_font.ttf"
        shutil.copy(fonts[0], font)
        brand = self.d / "brand_cache.json"
        brand.write_text(json.dumps({"font_file": str(font)}), encoding="utf-8")
        proj = self.d / "brand_cache_project.json"
        proj.write_text(json.dumps({"output": str(self.d / "brand_cache.mp4"), "brand": str(brand), "clips": [{"src": str(self.clip)}],
                                    "graphics": [{"template": "title", "title": "Hello", "start": 0, "end": 1}]}), encoding="utf-8")

        def hits():
            rc, doc, err = self._run("render.py", proj, "--cache", self.d / "brand_cache", "--overwrite")
            self.assertEqual(rc, 0, err[-800:])
            return doc["cache"]["hits"]
        hits()
        self.assertEqual(hits(), ["graphics"])
        shutil.copy(fonts[1], font)  # replaced under its name: the brand file is unchanged
        self.assertEqual(hits(), [], "the replaced font is a change the cache key sees")

    def test_an_interrupted_stage_reports_the_file_it_wrote_and_not_the_work_directory(self):
        """In this process: render's sh() with a stand-in child that writes the destination, then
        the interrupt handler, as Ctrl-C reaches both. A file the stage wrote is kept and named; a
        file that was there and the stage left alone is not claimed; a stage file in a work
        directory removed at exit is not called "still on disk"."""
        import signal
        import render
        from _common import STATE, runner
        dest = self.d / "stop_dest.mp4"
        work = self.d / "stop_work"
        work.mkdir(exist_ok=True)
        stage_file = work / "fit.mp4"
        cases = (("written by the stage", False, True, False), ("the caller's file, untouched", True, False, False),
                 # review of #537: a --work that holds the output's folder made the export an intermediate
                 ("--work holds the delivery", False, True, True))
        for label, preexisting, writes, work_holds_dest in cases:
            with self.subTest(case=label):
                dest.unlink(missing_ok=True)
                if preexisting:
                    shutil.copy(self.clip, dest)
                STATE.reset()
                STATE.json = True
                render.WORK_DIR["path"] = str(dest.parent if work_holds_dest else work)
                render.DELIVERY["path"] = str(dest)
                if not work_holds_dest:
                    STATE.temp_dirs.append(str(work))
                shutil.copy(self.clip, stage_file)
                STATE.written.add(str(stage_file))

                def child(cmd, **kw):
                    if writes:
                        dest.write_bytes(b"stage output")
                    runner._on_signal(signal.SIGINT, None)
                out = io.StringIO()
                try:
                    with unittest.mock.patch.object(render, "run_tool", side_effect=child), contextlib.redirect_stdout(out), \
                            contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        render.sh("export.py", str(self.clip), "--preset", "youtube", "-o", str(dest))
                finally:
                    runner._STOPPING["signal"] = None
                    render.WORK_DIR["path"] = render.DELIVERY["path"] = None
                    STATE.reset()
                doc = json.loads(out.getvalue())
                msg = doc["error"]["message"]
                self.assertNotIn(str(stage_file), msg, "the work directory goes at exit")
                if writes:
                    self.assertEqual(doc.get("output"), str(dest))
                    self.assertIn("is kept", msg)
                else:
                    self.assertNotIn("output", doc)
                    self.assertTrue(msg.endswith("nothing was written"), msg)

    def test_a_step_with_a_double_dash_still_gets_the_shared_flags(self):
        """Review of #537's sweep: batch appended --dry-run/--timeout/--json after a step's own `--`,
        where argparse reads them as positionals and the step was refused."""
        from _common.runner import with_flags
        self.assertEqual(with_flags(["a", "--", "b"], ["--json"]), ["a", "--json", "--", "b"])
        self.assertEqual(with_flags(["a", "b"], ["--json"]), ["a", "b", "--json"])
        folder = self._folder("dashdash", n=1)
        recipe = self._recipe(folder, [["fit.py", "--duration", "1", "--method", "speed", "-o", "{out}", "--", "{in}"]])
        rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--dry-run")
        self.assertEqual((rc, doc["status"]), (0, "completed"), err[-800:])

    def test_a_stop_after_the_srt_is_delivered_names_the_video_as_the_output(self):
        """Second review of #537: the SRT delivered beside the output was the last kept file, so a
        stop in the chapters or check stage reported it as `output`; the message names both."""
        import signal
        import render
        from _common import STATE, runner
        video = self.d / "srt_stop.mp4"
        shutil.copy(self.clip, video)
        made_srt = self.d / "srt_stop_made.srt"
        made_srt.write_text("1\n00:00:00,300 --> 00:00:01,200\nhello\n", encoding="utf-8")
        target = self.d / "srt_stop.srt"
        target.unlink(missing_ok=True)
        STATE.reset()
        STATE.json = True
        out = io.StringIO()
        try:
            render._LAST_DOC.clear()
            runner.mark_delivered(str(video))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(render.deliver_caption_srt(str(target), {"srt": str(made_srt), "video": str(video), "cached": False},
                                                            str(video)), str(target))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner._on_signal(signal.SIGINT, None)
        finally:
            runner._STOPPING["signal"] = None
            STATE.reset()
        doc = json.loads(out.getvalue())
        self.assertEqual(doc.get("output"), str(video))
        self.assertIn(str(video), doc["error"]["message"])
        self.assertIn(str(target), doc["error"]["message"])

    def test_brand_assets_are_in_the_batch_key(self):
        """Second review of #537: a step's --brand file (literal or {in}-built) was keyed by its own
        bytes only; its logo and font file, replaced under their names, kept the key."""
        import batch
        import time
        folder = self.d / "brand_key"
        folder.mkdir()
        src = folder / "a.mp4"
        src.write_bytes(b"x")
        for name in ("logo.png", "font.ttf"):
            (folder / name).write_bytes(b"1")
        for brand in (folder / "brand.json", folder / "a.mp4.json"):
            brand.write_text(json.dumps({"logo": "logo.png", "font_file": "font.ttf"}), encoding="utf-8")
        literal = {"steps": [["overlay.py", "{in}", "--brand", str(folder / "brand.json"), "-o", "{out}"]]}
        per_item = {"steps": [["overlay.py", "{in}", "--brand={in}.json", "-o", "{out}"]]}
        for asset in ("logo.png", "font.ttf"):
            with self.subTest(asset=asset):
                before = (batch.side_inputs_key(literal), batch.item_side_inputs_key(literal, src),
                          batch.item_side_inputs_key(per_item, src))
                time.sleep(0.01)
                (folder / asset).write_bytes(os.urandom(8))
                after = (batch.side_inputs_key(literal), batch.item_side_inputs_key(literal, src),
                         batch.item_side_inputs_key(per_item, src))
                self.assertNotEqual(before[0], after[0], "the literal brand's asset")
                self.assertNotEqual(before[2], after[2], "the {in}-built brand's asset")

    def test_an_item_whose_side_input_changed_while_it_ran_is_not_cached(self):
        """Second review of #537: the key was made before the item ran; a side input edited while it
        ran was stored under the old key, and a later restore of the old file served an output made
        from the edited one. Here the recipe's own second step rewrites the first step's logo."""
        folder = self._folder("changed_while", n=1)
        logo = folder / "logo.png"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1", logo)
        recipe = self._recipe(folder, [["overlay.py", "{in}", "--image", str(logo), "-o", "{out}"],
                                       ["look.py", "{in}", "-o", str(logo)]])
        rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--overwrite")
        self.assertEqual(rc, 0, err[-800:])
        self.assertIn("batch_cache_inputs_changed", [s["code"] for s in doc["diagnostics"]["skipped"]])
        cache = folder / "out" / ".ffskill_cache.json"
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}, {})

    def test_a_file_lang_side_input_is_keyed_by_its_file(self):
        """Review of #537: caption.py --srt FILE:LANG reads FILE; the key hashed the whole token, a
        path that does not exist, so an edited subtitle file kept its key (literal and {in}-built)."""
        import batch
        import time
        folder = self.d / "lang_key"
        folder.mkdir()
        src, built, literal = folder / "a.mp4", folder / "a.mp4.srt", folder / "subs.srt"
        for f in (src, built, literal):
            f.write_text("1", encoding="utf-8")
        per_item = {"steps": [["caption.py", "{in}", "--srt", "{in}.srt:eng", "-o", "{out}"]]}
        named = {"steps": [["caption.py", "{in}", "--srt", f"{literal}:eng", "-o", "{out}"]]}
        before = (batch.item_side_inputs_key(per_item, src), batch.side_inputs_key(named))
        time.sleep(0.01)
        built.write_text("22", encoding="utf-8")
        literal.write_text("22", encoding="utf-8")
        after = (batch.item_side_inputs_key(per_item, src), batch.side_inputs_key(named))
        self.assertNotEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        self.assertEqual(batch.side_input_file(f"{literal}:eng"), literal)
        self.assertEqual(batch.side_input_file(str(literal)), literal)

    def test_a_cache_entry_from_before_the_output_check_is_not_served(self):
        """Review of #537: a row cached for ["metadata.py", "{in}"] before step_writes_without_out
        existed (written: false) was served, so the recipe never met the refusal. An entry of a recipe
        with a step that names no {out} is served only when it was stored after that check."""
        folder = self._folder("old_entry", n=1)
        recipe = self._recipe(folder, [["check.py", "{in}"]])

        def run():
            rc, doc, err = self._run("batch.py", folder / "in", "--recipe", recipe)
            self.assertEqual(rc, 0, err[-800:])
            return doc["results"][0]
        run()
        self.assertTrue(run().get("cached"))
        cache = folder / "out" / ".ffskill_cache.json"
        entries = json.loads(cache.read_text(encoding="utf-8"))
        self.assertTrue(all(e.get("output_checked") for e in entries.values()))
        for e in entries.values():
            e.pop("output_checked")  # as an earlier version stored it
        cache.write_text(json.dumps(entries), encoding="utf-8")
        row = run()
        self.assertFalse(row.get("cached"))
        self.assertEqual(row["cache_miss"]["reason"], "entry_predates_output_check")
        self.assertTrue(run().get("cached"), "stored again, with the check")

    @unittest.skipIf(os.name == "nt", "SIGTERM is not delivered to a Python handler on Windows")
    def test_a_second_signal_to_batch_keeps_the_first_signal_s_report(self):
        """Review of #537: batch's own handler took a second signal as a new one: the exit code became
        the SIGTERM's (143 for a Ctrl-C) and the stop ran again inside the first one's report."""
        import signal
        import time
        folder = self.d / "two_signals"
        (folder / "in").mkdir(parents=True)
        slow = folder / "in" / "a.mp4"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=120", "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", slow)
        recipe = self._recipe(folder, [["fit.py", "{in}", "--height", "1080", "-o", "{out}"]])
        p = subprocess.Popen([sys.executable, str(SCRIPTS / "batch.py"), str(folder / "in"), "--recipe", str(recipe), "--json"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3)
        self.assertIsNone(p.poll(), "the step is still running")
        p.send_signal(signal.SIGINT)
        time.sleep(0.05)
        try:
            p.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        out, err = p.communicate(timeout=300)
        doc = json.loads(out)
        self.assertEqual((p.returncode, doc["error"]["kind"]), (130, "interrupted"), err[-800:])
        self.assertTrue(doc["results"][0].get("interrupted"))

    @unittest.skipIf(os.name == "nt", "SIGTERM is not delivered to a Python handler on Windows")
    def test_a_second_signal_during_the_stop_does_not_leave_the_lock(self):
        """Ctrl-C reaches the whole process group, and the parent then sends its SIGTERM: the second
        signal raised again from inside the cleanup the first started (the output lock's __exit__)
        and left the lock and its takeover file beside the output."""
        out = self.d / "locked.mp4"
        child = self.d / "lock_child.py"
        child.write_text(
            "import os, signal, sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "from _common import runner\n"
            "runner.install_signal_handlers()\n"
            "real = runner._TakeoverSection.acquire\n"
            "def acquire(self, *a, **k):\n"
            "    os.kill(os.getpid(), signal.SIGTERM)  # the parent's SIGTERM, inside the cleanup\n"
            "    return real(self, *a, **k)\n"
            "with runner._OutputLock(sys.argv[1]):\n"
            "    runner._TakeoverSection.acquire = acquire\n"
            "    os.kill(os.getpid(), signal.SIGINT)\n", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(child), str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 130, proc.stderr[-800:])
        left = sorted(p.name for p in self.d.glob(".locked.mp4*"))
        self.assertEqual(left, [], "the lock and its takeover file are removed")

    @unittest.skipIf(os.name == "nt", "a process-group SIGINT is POSIX")
    def test_ctrl_c_during_the_export_s_loudness_pass_reports_the_kept_delivery(self):
        """End to end, render and batch: Ctrl-C to the process group while export.py --normalize
        runs its loudness pass, after it wrote the delivery. Render said "nothing was written" with
        the file on disk; batch's row said only that the step was stopped."""
        import signal
        loud = self.d / "loud.mp4"
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x36:r=10:d=150", "-f", "lavfi", "-i",
           "sine=f=440:d=150", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", loud)
        proj = self.d / "stop.json"
        rout = self.d / "stopped" / "x.mp4"
        rout.parent.mkdir()
        proj.write_text(json.dumps({"output": str(rout), "clips": [{"src": str(loud)}],
                                    "export": {"preset": "youtube", "normalize": True}}), encoding="utf-8")
        bfolder = self.d / "bstop"
        (bfolder / "in").mkdir(parents=True)
        shutil.copy(loud, bfolder / "in" / "a.mp4")
        recipe = self._recipe(bfolder, [["export.py", "{in}", "--preset", "youtube", "--normalize", "-o", "{out}"]])
        # review of #537: a project recipe's item is a render that writes the final path itself
        pfolder = self.d / "pstop"
        (pfolder / "in").mkdir(parents=True)
        shutil.copy(loud, pfolder / "in" / "a.mp4")
        pproj = pfolder / "proj.json"
        pproj.write_text(json.dumps({"clips": [{"src": "x.mp4"}], "export": {"preset": "youtube", "normalize": True}}), encoding="utf-8")
        precipe = pfolder / "r.json"
        precipe.write_text(json.dumps({"glob": "*.mp4", "output_dir": str(pfolder / "out"), "project": str(pproj)}), encoding="utf-8")
        for name, tool, argv, where, final in (
                ("render", "render", [proj], rout.parent, rout),
                ("batch", "batch", [bfolder / "in", "--recipe", recipe], bfolder / "out", bfolder / "out" / "a_out.mp4"),
                ("batch project", "batch", [pfolder / "in", "--recipe", precipe], pfolder / "out", pfolder / "out" / "a_out.mp4")):
            with self.subTest(tool=name):
                p = subprocess.Popen([sys.executable, str(SCRIPTS / f"{tool}.py"), *map(str, argv), "--json"], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, start_new_session=True)
                import time
                deadline = time.monotonic() + 600  # a busy machine is slow, not stuck; a stuck run fails here
                while p.poll() is None and not (where.is_dir() and any("normalize" in n.name for n in where.iterdir())):
                    if time.monotonic() > deadline:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.communicate()
                        self.fail(f"{name}: the loudness pass did not start within 600 s")
                    time.sleep(0.02)
                if p.poll() is not None:
                    self.fail(f"{name} finished before its loudness pass could be interrupted: {p.stderr.read()[-800:]}")
                time.sleep(0.3)
                os.killpg(p.pid, signal.SIGINT)
                o, e = p.communicate(timeout=300)
                doc = json.loads(o)
                self.assertEqual((p.returncode, doc["error"]["kind"]), (130, "interrupted"), e[-800:])
                self.assertTrue(final.is_file())
                self.assertIn(str(final), doc["error"]["message"])
                self.assertIn("kept", doc["error"]["message"])
                if tool == "render":
                    self.assertEqual(doc.get("output"), str(final))
                else:
                    self.assertEqual(doc["results"][0].get("kept"), str(final))
                self.assertEqual(sorted(n.name for n in where.iterdir() if "ffskill-lock" in n.name), [])

    def test_a_batch_dry_run_says_a_cached_row_s_cuts_apart_from_its_plans(self):
        """#540: a dry run serves a cache hit as the real run would (cached: true), and that row's
        cut_reencoded is what the run that stored it measured. The summary line counted those calls
        as planned re-encodes and pointed at cut_possible_reencode_reason, which the row lacks."""
        folder = self.d / "dry_cached"
        (folder / "in").mkdir(parents=True)
        # keyframes 2 s apart: a cut from 0.37 is planned as a copy, which lands on the keyframe at 0
        # and is re-encoded for the tolerance
        sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30", "-t", "3", "-c:v", "libx264",
           "-g", "60", "-pix_fmt", "yuv420p", folder / "in" / "a.mp4")
        recipe = self._recipe(folder, [["cut.py", "{in}", "--start", "0.37", "--end", "1.53", "--tolerance", "0.02", "-o", "{out}"]])
        rc, real, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--fast")
        self.assertEqual((rc, real["results"][0]["cut_reencoded"]), (0, [True]), err[-800:])  # the fixture: a measured re-encode
        shutil.copy(folder / "in" / "a.mp4", folder / "in" / "b.mp4")  # an item with no entry: planned
        rc, plan, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--fast", "--dry-run")
        self.assertEqual(rc, 0, err[-800:])
        served, planned = plan["results"]
        self.assertEqual((served.get("cached"), served["cut_reencoded"]), (True, [True]), "served as a real run serves it")
        self.assertNotIn("cut_possible_reencode_reason", served)
        self.assertEqual((planned.get("cached"), planned["cut_reencoded"]), (None, [False]), planned)
        self.assertIn("tolerance", planned["cut_possible_reencode_reason"][0])
        line = next(ln for ln in err.splitlines() if "cut.py:" in ln)
        self.assertIn("1/1 call(s) planned as a lossless stream copy", line)
        self.assertIn("0 planned to re-encode", line)
        self.assertIn("1 call(s) in rows a real run serves from the cache (cached: true), as the run that stored them "
                      "measured: 0 stayed lossless stream-copy, 1 re-encoded", line)
        self.assertEqual(plan["cut_stream_copy"], {"calls": 2, "stream_copy": 1, "reencoded": 1, "stream_copy_rate": 0.5})
        (folder / "in" / "b.mp4").unlink()
        rc, plan, err = self._run("batch.py", folder / "in", "--recipe", recipe, "--fast", "--dry-run")
        line = next(ln for ln in err.splitlines() if "cut.py:" in ln)
        self.assertNotIn("planned", line.split("(cached: true)")[0], "no call was planned")

    def test_a_render_stage_whose_brand_logo_changed_while_it_ran_is_not_cached(self):
        """#540: render's stage key was made before the stage's child ran and stored after it; a
        --brand logo rewritten in between was drawn but stored under the old logo's key, so putting
        the old logo back (mtime kept) served the new one. The child here is the real overlay.py,
        run after a hook in render's run_tool() rewrites the logo."""
        logo, red = self.d / "brand540_logo.png", self.d / "brand540_red.png"
        blue = self.d / "brand540_blue.png"
        for path, colour in ((logo, "red"), (blue, "blue")):
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=32x32", "-frames:v", "1", path)
        shutil.copy2(logo, red)
        brand = self.d / "brand540.json"
        brand.write_text(json.dumps({"logo": str(logo)}), encoding="utf-8")
        proj = self.d / "brand540_project.json"
        proj.write_text(json.dumps({"output": str(self.d / "brand540.mp4"), "brand": str(brand), "clips": [{"src": str(self.clip)}],
                                    "overlays": [{"logo": True}]}), encoding="utf-8")
        cdir = self.d / "brand540_cache"
        args = [str(proj), "--cache", str(cdir), "--overwrite", "--fast", "--json"]
        hook = ("import shutil, sys\n"
                f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "import render\n"
                "real = render.run_tool\n"
                "def hooked(cmd, *a, **k):\n"
                "    if str(cmd[0]).endswith('overlay.py'):\n"
                f"        shutil.copy({str(blue)!r}, {str(logo)!r})\n"
                "    return real(cmd, *a, **k)\n"
                "render.run_tool = hooked\n"
                f"sys.argv = ['render.py'] + {args!r}\n"
                "sys.exit(render.main())\n")
        proc = subprocess.run([sys.executable, "-c", hook], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        doc = json.loads(proc.stdout)
        self.assertIn({"code": "cache_inputs_changed", "stage": "overlays"},
                      [{k: s.get(k) for k in ("code", "stage")} for s in (doc.get("diagnostics") or {}).get("skipped") or []])
        self.assertEqual(doc["cache"]["entries"], 0, doc["cache"])
        shutil.copy2(red, logo)  # the old logo back, its mtime kept
        rc, doc, err = self._run("render.py", *args[:-1])
        self.assertEqual(rc, 0, err[-800:])
        self.assertEqual(doc["cache"]["hits"], [], "the blue logo's overlay is not served for the red one")
        self.assertNotIn("cache_inputs_changed", [s["code"] for s in (doc.get("diagnostics") or {}).get("skipped") or []])
        rc, doc, err = self._run("render.py", *args[:-1])
        self.assertEqual(doc["cache"]["hits"], ["overlays"], "a stage whose inputs held still is stored as before")


if __name__ == "__main__":
    unittest.main(verbosity=2)
