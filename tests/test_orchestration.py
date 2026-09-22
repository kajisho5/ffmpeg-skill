#!/usr/bin/env python3
"""End-to-end tests for render, batch and multicam, plus the toolkit-wide invariants every script has to satisfy.

    python3 tests/test_orchestration.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, ROOT, SCRIPTS, TONES, _no_fontconfig, script, sh  # noqa: E402
from _common import font_for_script, probe, shell_quote  # noqa: E402


class OrchestrationTests(MediaFixtures):
    """Render, batch and multicam, plus the toolkit-wide invariants every script has to satisfy."""

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
        graph = next(c for c in data["commands"] if "sidechaincompress" in c)
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
            ("fit.py", [self.src, "--duration", "6"]),
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
        r = script("render.py", proj, "--dry-run", "--json")
        rdata = json.loads(r.stdout)
        self.assertEqual(rdata["status"], "completed")

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
            "audio": {"replace": "long_ref.wav", "music_volume": -12, "gain": 1, "music_loop": True, "stereo": True, "denoise": True},
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
        alt = dict(full, clips=[{"src": "source.mp4"}], silence={"threshold": -40, "min_silence": 0.4, "margin": 0.1},
                   captions={"ass": ass.name}, audio={"music": "long_ref.wav", "mono": True, "downmix": True, "duck": True, "voice": True, "duck_amount": 8}, graphics=[], overlays=[])
        ass.write_text("[Script Info]\nScriptType: v4.00+\n\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,hi\n", encoding="utf-8")
        (OUT / "render_full_alt.json").write_text(json.dumps(alt), encoding="utf-8")
        proc = script("render.py", OUT / "render_full_alt.json", "--dry-run", "--json")
        self.assertEqual(json.loads(proc.stdout)["stages"], ["clips", "silence", "fit", "captions", "audio", "loudness", "export"])
        forwarded = "\n".join(l for l in proc.stderr.splitlines() if l.startswith("→ "))
        for needle in ("--ass", "--min-silence 0.4", "--mono", "--downmix", "--duck-amount 8", "--voice"):
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
            "overlay_key": ([self._proj("render_e4.json", {"clips": full["clips"], "overlays": [{"opacity": 1}]}), "--dry-run"], "needs image or text"),
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
        self.assertIn("source not found", proc.stderr)
        self.assertNotIn("unknown key", proc.stderr)

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
        self.assertRegex(work_dirs[0].name, r"^render_workdir_check_work_\d+$",
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
        # the outer --timeout reaches every stage: an impossible limit fails inside the first stage
        proc = script("render.py", proj, "--fast", "--timeout", "0.05", "--json", expect_fail=True)
        self.assertIn("time limit", proc.stderr)
        self.assertIn("--timeout 0.05", proc.stderr, "the flag must be forwarded to the child command line")
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
        self.assertEqual((cap["fit_size"], cap["size_floor"], cap["fit_scope"]), ("on", 15, "cue"))
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
        self.assertIn("overlay=W-w-40:40", proc.stderr)
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
            "steps": [["fit.py", "{in}", "--duration", "3", "-o", "{out}"]]}))
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
                    "steps": [["fit.py", "{in}", "--duration", "3", "-o", "{out}"]]}))
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
        folder, recipe = self._jobs_folder("batch_jobs_work", count=3)
        work = OUT / "batch_jobs_work_dir"
        script("batch.py", folder, "--recipe", recipe, "--fast", "--force", "--jobs", "3",
               "--work", work)
        subdirs = sorted(p.name for p in work.iterdir() if p.is_dir())
        self.assertEqual(len(subdirs), 3)
        # ... and a serial run keeps the flat layout it always had
        work2 = OUT / "batch_jobs_work_serial"
        script("batch.py", folder, "--recipe", recipe, "--fast", "--force", "--jobs", "1",
               "--work", work2)
        self.assertEqual([p.name for p in work2.iterdir() if p.is_dir()], [])


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
        self.assertEqual(sorted(p.name for p in cdir.iterdir()), [])
        self.assertIn("cache", data)

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
                                      "steps": [["fit.py", "{in}", "--duration", "5", "-o", "{out}"], ["export.py", "{in}", "--preset", "x", "-o", "{out}"]]}))
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

        # a recipe with no cut.py step reports nothing -- the key isn't invented from nowhere
        recipe2 = folder / "batch_no_cut.json"
        recipe2.write_text(json.dumps({"glob": "*.mp4", "output_dir": "out2", "suffix": "_nc",
                                       "steps": [["fit.py", "{in}", "--duration", "3", "-o", "{out}"]]}))
        data2 = json.loads(script("batch.py", folder, "--recipe", recipe2, "--fast", "--json").stdout)
        self.assertIsNone(data2["cut_stream_copy"])
        self.assertNotIn("cut_reencoded", data2["results"][0])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
