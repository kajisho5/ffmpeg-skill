#!/usr/bin/env python3
"""End-to-end tests for export, proxy and the delivery templates.

    python3 tests/test_delivery.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import json
import os
import re
import subprocess
import sys
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import MediaFixtures, OUT, ROOT, SCRIPTS, script, sh  # noqa: E402
from _common import probe  # noqa: E402


class DeliveryTests(MediaFixtures):
    """Export, proxy and the delivery templates."""

    # ---------------------------------------------------------------- export
    def test_export_presets(self):
        cases = {
            "youtube": ("mp4", "h264", (1920, 1080)),
            "reels": ("mp4", "h264", (1080, 1920)),
            "x": ("mp4", "h264", (1280, 720)),
            "prores": ("mov", "prores", (1280, 720)),
            "h265": ("mp4", "hevc", (1280, 720)),
        }
        for preset, (ext, codec, size) in cases.items():
            with self.subTest(preset=preset):
                out = OUT / f"export_{preset}.{ext}"
                script("export.py", self.src, "--preset", preset, "-o", out)
                m = probe(str(out))
                self.assertEqual(m["video"]["codec"], codec)
                self.assertEqual((m["video"]["width"], m["video"]["height"]), size)
                self.assertClose(m["duration"], 12.0, 0.2)
                if preset in ("youtube", "reels", "x", "h265"):
                    self.assertEqual(m["video"]["color_space"], "bt709")

    def test_export_list(self):
        self.assertIn("youtube", script("export.py", "--list").stdout)

    def test_export_copy_is_a_real_stream_copy(self):
        """`--preset copy`: same bytes as a source→same-container remux would produce, not a re-encode — verified by
        codec/resolution/bitrate/frame-count staying exactly the source's, not by trusting the preset name."""
        out = OUT / "export_copy.mp4"
        script("export.py", self.src, "--preset", "copy", "-o", out)
        src_m, out_m = probe(str(self.src)), probe(str(out))
        self.assertEqual(out_m["video"]["codec"], src_m["video"]["codec"])
        self.assertEqual((out_m["video"]["width"], out_m["video"]["height"]), (src_m["video"]["width"], src_m["video"]["height"]))
        self.assertEqual(out_m["audio"]["codec"], src_m["audio"]["codec"])
        self.assertClose(out_m["duration"], src_m["duration"], 0.05)
        src_frames = sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", self.src).stdout.strip()
        out_frames = sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", out).stdout.strip()
        self.assertEqual(out_frames, src_frames, "a re-encode could drop/duplicate frames; a copy cannot")
        # a genuinely untouched source has no colour tags to begin with (never asserts a re-encoder's own default)
        self.assertEqual(out_m["video"]["color_space"], src_m["video"]["color_space"])
        # no audio in the source: copy must not invent a silent track, and must not error demanding one
        noaudio = OUT / "noaudio_source.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.src, "-t", "2", "-an", "-c:v", "copy", noaudio)
        out_na = OUT / "export_copy_noaudio.mp4"
        script("export.py", noaudio, "--preset", "copy", "-o", out_na)
        self.assertIsNone(probe(str(out_na)).get("audio"))

    def test_export_copy_preserves_hdr_tags_untouched(self):
        """The HDR-warning branch that every re-encoding preset trips (`export.py` docstring: "outputs SDR BT.709
        tags without tone mapping") must not apply to `copy` — it doesn't touch colour at all, so the source's own
        HDR tags must survive exactly, not get silently flattened to BT.709 like every other preset does."""
        out = OUT / "export_copy_hdr.mov"
        proc = script("export.py", self.hdr, "--preset", "copy", "-o", out)
        self.assertNotIn("BT.709", proc.stdout + proc.stderr, "copy re-encodes nothing, so it never issues the SDR-flattening warning")
        m = probe(str(out))
        self.assertTrue(m["video"]["hdr"], "the source's real HDR tags must survive a stream copy")
        self.assertNotEqual(m["video"]["color_space"], "bt709", "copy must never relabel HDR content as bt709")

    def test_export_warning_names_bt2020_sdr_as_not_hdr(self):
        """Eval 24 h1: after 2.0 narrowed `hdr` to a real PQ/HLG/DV signal, export.py still warned
        "source is HDR (BT.2020 SDR)" for a wide-gamut SDR file -- the 1.x wording, contradicting
        probe. The warning now says which case it is, and still points at color.py --to-sdr."""
        wide = OUT / "export_bt2020_sdr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
           "-t", "1", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=bt709:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1", wide)
        doc = json.loads(script("export.py", wide, "--preset", "youtube", "--fast", "--json",
                                "-o", OUT / "export_bt2020_sdr_yt.mp4").stdout)
        note = " ".join(doc.get("notes") or [])
        self.assertIn("wide-gamut SDR, not HDR", note)
        self.assertIn("color.py --to-sdr", note)
        doc = json.loads(script("export.py", self.hdr, "--preset", "youtube", "--fast", "--json",
                                "-o", OUT / "export_hdr_yt_note.mp4").stdout)
        self.assertIn("source is HDR (HDR10/PQ)", " ".join(doc.get("notes") or []))

    def test_proxy_default_width_and_crf_keeps_audio(self):
        out = OUT / "proxy_default.mp4"
        script("proxy.py", self.src, "-o", out)
        m = probe(str(out))
        self.assertEqual(m["video"]["width"], 640)
        self.assertEqual(m["video"]["codec"], "h264")
        self.assertIsNotNone(m.get("audio"), "default keeps audio when the source has it")
        self.assertClose(m["duration"], 12.0, 0.2)

    def test_proxy_scale_and_no_audio(self):
        out = OUT / "proxy_scale.mp4"
        script("proxy.py", self.src, "--scale", "0.25", "--no-audio", "-o", out)
        src_w = probe(str(self.src))["video"]["width"]
        m = probe(str(out))
        self.assertEqual(m["video"]["width"], src_w // 4)
        self.assertIsNone(m.get("audio"), "--no-audio must drop the track, not just mute it")

    def test_proxy_forces_fps(self):
        out = OUT / "proxy_fps.mp4"
        script("proxy.py", self.vfr, "--fps", "10", "-o", out)
        m = probe(str(out))
        self.assertFalse(m["video"]["variable_frame_rate_suspected"], "an explicit --fps must conform a VFR source to CFR")
        self.assertClose(m["video"]["fps"], 10.0, 0.5)

    def test_proxy_keeps_hdr_dynamic_range_like_every_other_reencode(self):
        """A proxy meant for machine consumption still shouldn't silently wash out HDR to a
        mislabelled BT.709 file — same posture as fit.py/caption.py: keep HDR as HEVC10, and
        let color.py --to-sdr be the tool that makes the SDR-vs-HDR call, not this one."""
        out = OUT / "proxy_hdr.mp4"
        script("proxy.py", self.hdr, "-o", out)
        m = probe(str(out))
        self.assertTrue(m["video"]["hdr"])
        self.assertEqual(m["video"]["codec"], "hevc")

    def test_proxy_rejects_bad_scale_and_width(self):
        script("proxy.py", self.src, "--scale", "1.5", expect_fail=True)
        script("proxy.py", self.src, "--scale", "0", expect_fail=True)
        script("proxy.py", self.src, "--width", "0", expect_fail=True)

    def test_proxy_dry_run_writes_nothing(self):
        out = OUT / "proxy_dry_run_absent.mp4"
        proc = script("proxy.py", self.src, "-o", out, "--dry-run", "--json")
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["dry_run"])
        self.assertFalse(out.exists())

    def test_export_warns_on_hdr(self):
        out = OUT / "hdr_youtube.mp4"
        proc = script("export.py", self.hdr, "--preset", "x", "-o", out)
        self.assertIn("HDR", proc.stderr)

    def test_export_normalize_meets_the_platform_loudness_in_one_call(self):
        """Eval 7: every platform job ran export -> loudness.py -> export again. --normalize runs
        the levels pass on the written file (audio only) so one export delivers the spec."""
        out = OUT / "export_normalize.mp4"
        proc = script("export.py", OUT / "source.mp4", "--preset", "x", "--normalize", "-o", out, "--fast", "--json", "--overwrite")
        d = json.loads(proc.stdout)
        self.assertEqual(d["status"], "completed")
        self.assertTrue(d["loudness"]["ok"], d["loudness"])
        self.assertTrue(d["loudness"]["normalized"])
        self.assertTrue(d["verified"])
        self.assertAlmostEqual(d["loudness"]["lufs"], -14.0, delta=1.0)
        self.assertFalse((OUT / "export_normalize_loudnorm.mp4").exists())
        self.assertTrue(any("linear=true" in c for c in d["commands"]), "the normalising encode is in the command log (review 7)")
        # review 7 P0: a real <output>_loudnorm.<ext> next to the export survives --normalize
        precious = OUT / "export_normalize_loudnorm.mp4"
        precious.write_bytes(b"PRECIOUS")
        try:
            script("export.py", OUT / "source.mp4", "--preset", "x", "--normalize", "-o", out, "--fast", "--json", "--overwrite")
            self.assertEqual(precious.read_bytes(), b"PRECIOUS")
        finally:
            precious.unlink()
        # --normalize on a preset without a loudness spec is refused; under --dry-run it says what it would do
        d = json.loads(script("export.py", OUT / "source.mp4", "--preset", "h265", "--normalize", "-o", OUT / "export_norm_h265.mp4", "--json", expect_fail=True).stdout)
        self.assertEqual(d["error"]["kind"], "input")
        d = json.loads(script("export.py", OUT / "source.mp4", "--preset", "x", "--normalize", "-o", out, "--dry-run", "--json").stdout)
        self.assertTrue(any("--normalize" in n for n in d.get("notes", [])), d)
        # without the flag the same file is reported, not fixed
        proc = script("export.py", OUT / "source.mp4", "--preset", "x", "-o", out, "--fast", "--json", "--overwrite")
        d = json.loads(proc.stdout)
        self.assertFalse(d["loudness"]["ok"])
        self.assertNotIn("normalized", d["loudness"])
        self.assertIn("--normalize", " ".join(d["notes"]))

    def test_every_delivery_template_renders_and_passes_its_own_check(self):
        """1.14: `render.py --template NAME INPUT` is the one command a delivery request becomes,
        so every shipped template has to survive its own pipeline on real footage and come back
        with its own platform's check passing -- the frame, the caption burn, the loudness pass,
        the export preset and check.py agreeing is exactly the thing a template promises and the
        thing that used to be assembled by hand differently every time."""
        names = sorted(p.stem for p in (ROOT / "templates").glob("*.json"))
        self.assertEqual(names, ["audiogram", "facebook", "linkedin", "podcast", "reels", "shorts",
                                 "tiktok", "x", "youtube", "youtube-shorts"],
                         "every shipped template is exercised here")
        plate = OUT / "tpl_audiogram_plate.png"
        if not plate.exists():
            plate_clip = OUT / "tpl_audiogram_plate.mp4"
            script("background.py", "--width", "640", "--height", "360",
                   "--gradient", "#101014:#cc3333", "--duration", "1", "-o", plate_clip)
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", plate_clip,
               "-frames:v", "1", plate)
        for name in names:
            with self.subTest(template=name):
                src = self.mic if name in ("podcast", "audiogram") else self.src
                argv = [str(src), "--template", name, "--fast", "--json",
                        "-o", str(OUT / ("tpl_%s.%s" % (name, "m4a" if name == "podcast" else "mp4")))]
                if name != "podcast":
                    argv += ["--cues", str(self.cues)]
                if name == "audiogram":
                    # the one template that needs a picture given to it: the skill fetches nothing
                    # and invents no cover art, so a run without --image is a refusal by design
                    argv += ["--image", str(plate)]
                doc = json.loads(script("render.py", *argv).stdout)
                self.assertEqual(doc["status"], "completed")
                self.assertTrue(os.path.exists(doc["output"]), doc["output"])
                self.assertTrue(doc["check"]["ok"],
                                f"{name}: {[r for r in doc['check']['checks'] if r['status'] == 'FAIL']}")
                platform = json.loads((ROOT / "templates" / f"{name}.json").read_text())["check"]["platform"]
                self.assertEqual(doc["check"]["platform"], platform)

    def test_template_keeps_caption_and_graphic_out_of_the_platform_safe_zone(self):
        """The whole point of the table's safe zones: TikTok draws its description block over the
        bottom 22 % of the frame and its like/comment column over the right 14 %. A caption burned
        at the historical margin sits under the description; a right-hand graphic sits under the
        buttons. Asserted on the planned commands (--dry-run --json), which is where the ASS
        MarginV and the drawtext x actually are."""
        sys.path.insert(0, str(SCRIPTS))
        from _platforms import PLATFORMS, ass_units
        safe = PLATFORMS["tiktok"]["safe"]
        proj = OUT / "safe_project.json"
        script("render.py", self.src, "--template", "tiktok", "--cues", self.cues,
               "--write-project", proj, "-o", str(OUT / "safe_out.mp4"))
        cap = json.loads(proj.read_text())["captions"]
        self.assertEqual(cap["margin"], ass_units(safe["bottom"]), "the template's caption margin is the safe zone")
        # the burn itself: the generated .ass carries MarginV in the same 288-unit grid, scaled
        plan = json.loads(script("render.py", proj, "--dry-run", "--json").stdout)
        ass_lines = [c for c in plan["commands"] if "captioned.ass" in c]
        self.assertTrue(ass_lines, plan["commands"])
        # the ASS grid is 288 lines, so a fraction of the frame lands on the nearest of ~6.7 px
        margin_px = round(cap["margin"] * 1920 / 288)
        self.assertGreaterEqual(margin_px, round(safe["bottom"] * 1920) - 1920 / 288,
                                "the caption's baseline margin must clear TikTok's description bar")
        # a right-positioned graphic: drawtext's x must leave the like column free
        gfx = json.loads(script("graphics.py", self.src, "--template", "bug", "--title", "@handle",
                                "--position", "top-right", "--platform", "tiktok", "--dry-run", "--json",
                                "-o", str(OUT / "safe_bug.mp4")).stdout)
        W, H = 1280, 720  # the fixture's own frame: the margins are fractions of it
        drawtext = [c for c in gfx["commands"] if "drawtext" in c][0]
        m = re.search(r"x=w-text_w-(\d+)", drawtext)
        self.assertTrue(m, drawtext)
        self.assertGreaterEqual(int(m.group(1)), round(safe["right"] * W) - 1,
                                "a right-hand graphic must sit left of TikTok's like column")
        m = re.search(r"y=(\d+):box", drawtext)
        self.assertGreaterEqual(int(m.group(1)), round(safe["top"] * H) - 1)

    def test_list_templates_names_every_template_with_its_safe_zones(self):
        out = script("render.py", "--list-templates").stdout
        sys.path.insert(0, str(SCRIPTS))
        from _platforms import PLATFORMS
        for path in sorted((ROOT / "templates").glob("*.json")):
            self.assertIn(path.stem, out)
        for edge, frac in PLATFORMS["tiktok"]["safe"].items():
            self.assertIn(f"{edge} {frac:.2f}", out, f"--list-templates must state tiktok's {edge} safe zone")
        self.assertIn("1080x1920", out)
        script("render.py", self.src, "--template", "myspace", expect_fail=True)

    def test_export_presets_per_destination_are_distinct_and_hdr_av1_refuse_honestly(self):
        """1.14: tiktok/shorts/linkedin/facebook stop being aliases of reels/youtube -- each is its
        own frame and duration limit. youtube-hdr must keep a real HDR source's tags (the point of
        the preset) and refuse an SDR one instead of labelling SDR as HDR; youtube-av1 must refuse
        with kind: missing_tool on a build with no AV1 encoder rather than failing inside ffmpeg."""
        sys.path.insert(0, str(SCRIPTS))
        import export as export_mod
        frames = {name: (p["w"], p["h"], p["max"]) for name, p in export_mod.PRESETS.items()
                  if name in ("reels", "tiktok", "shorts", "linkedin", "facebook")}
        self.assertEqual(len(set(frames.values())), 5, f"presets must be distinct entries: {frames}")
        for preset, size in (("tiktok", (1080, 1920)), ("linkedin", (1080, 1080))):
            out = OUT / f"export_{preset}.mp4"
            script("export.py", self.src, "--preset", preset, "--fast", "-o", out)
            m = probe(str(out))
            self.assertEqual((m["video"]["width"], m["video"]["height"]), size)
        hdr_out = OUT / "export_yt_hdr.mp4"
        script("export.py", self.hdr, "--preset", "youtube-hdr", "--fast", "-o", hdr_out)
        m = probe(str(hdr_out))
        self.assertTrue(m["video"]["hdr"], "youtube-hdr must keep the source's HDR")
        self.assertNotEqual(m["video"]["color_space"], "bt709")
        doc = json.loads(script("export.py", self.src, "--preset", "youtube-hdr", "--json",
                                "-o", str(OUT / "never.mp4"), expect_fail=True).stdout)
        self.assertEqual(doc["error"]["kind"], "input")
        self.assertIn("SDR", doc["error"]["message"])
        from _common import ffmpeg_encoders
        av1_out = OUT / "export_yt_av1.mp4"
        if {"libsvtav1", "libaom-av1"} & ffmpeg_encoders():
            script("export.py", self.src, "--preset", "youtube-av1", "--fast", "-o", av1_out)
            self.assertEqual(probe(str(av1_out))["video"]["codec"], "av1")
        else:
            doc = json.loads(script("export.py", self.src, "--preset", "youtube-av1", "--json",
                                    "-o", str(av1_out), expect_fail=True).stdout)
            self.assertEqual(doc["error"]["kind"], "missing_tool")

    def test_template_logo_lands_inside_the_platform_safe_zone(self):
        """A template's --logo used to be drawn 24 px from the corner -- i.e. under TikTok's own
        status bar and next to its tab row. The overlay stage now hears the destination like the
        caption and graphics stages do, so the planned overlay sits inside the safe zone."""
        sys.path.insert(0, str(SCRIPTS))
        from _platforms import PLATFORMS
        safe = PLATFORMS["tiktok"]["safe"]
        W, H = PLATFORMS["tiktok"]["frame"]["w"], PLATFORMS["tiktok"]["frame"]["h"]
        doc = json.loads(script("render.py", self.src, "--template", "tiktok", "--cues", self.cues,
                                "--logo", self.logo, "--dry-run", "--json",
                                "-o", str(OUT / "logo_safe.mp4")).stdout)
        cmd = [c for c in doc["commands"] if "logo.png" in c and "overlay=" in c]
        self.assertTrue(cmd, doc["commands"])
        x, y = re.search(r"overlay=(-?\d+):(-?\d+)", cmd[0]).groups()
        self.assertGreaterEqual(int(x), round(safe["left"] * W) - 1,
                                "the logo must clear the left safe margin")
        self.assertGreaterEqual(int(y), round(safe["top"] * H) - 1,
                                "the logo must clear TikTok's status bar and tab row")
        self.assertLess(int(y), H - round(safe["bottom"] * H))

    def test_export_presets_are_the_platform_tables_frame_and_duration(self):
        """docs/contract.md says export.py's PRESETS/PLATFORM_OF come from scripts/_platforms.py.
        Until review 12 only check.py's SPECS did, and the facebook preset had already drifted
        (no duration cap against the table's 14400 s). Every platform preset is the table now,
        except the two deliberate, documented exceptions."""
        sys.path.insert(0, str(SCRIPTS))
        import export as export_mod
        from _platforms import PLATFORMS, loudness_of
        from check import SPECS
        # youtube4k delivers to youtube at 2160p; neither youtube preset trims at the 12-hour cap
        exceptions = {"youtube": {"max"}, "youtube4k": {"w", "h", "max"},
                      "youtube-hdr": {"w", "h", "max"}, "youtube-av1": {"max"}}
        for preset, platform in sorted(export_mod.PLATFORM_OF.items()):
            with self.subTest(preset=preset):
                p = export_mod.PRESETS[preset]
                frame = PLATFORMS[platform]["frame"]
                spec = PLATFORMS[platform]["spec"]
                skip = exceptions.get(preset, set())
                if "w" not in skip:
                    self.assertEqual((p["w"], p["h"]), (frame["w"], frame["h"]),
                                     f"{preset} frame must be {platform}'s frame")
                if "max" not in skip:
                    self.assertEqual(p["max"], float(spec["max_duration"]) if spec["max_duration"] else None,
                                     f"{preset} duration cap must be {platform}'s")
                table = loudness_of(platform)
                self.assertEqual((SPECS[platform]["lufs"], SPECS[platform]["lufs_tol"], SPECS[platform]["tp"]),
                                 (table["lufs"], table["lufs_tol"], table["tp"]))
        self.assertEqual(export_mod.PRESETS["facebook"]["max"], 14400.0,
                         "the drift review 12 found: facebook had no duration cap at all")

    def test_every_template_caption_block_is_the_tables_safe_zone(self):
        """The templates must not restate the numbers the table exists to own: change a
        destination's safe zone and every shipped template follows, rather than keeping an old
        margin silently."""
        sys.path.insert(0, str(SCRIPTS))
        from _platforms import PLATFORMS, caption_defaults
        import render as render_mod
        for path in sorted((ROOT / "templates").glob("*.json")):
            tpl = json.loads(path.read_text(encoding="utf-8"))
            cap = tpl.get("captions")
            if not cap:
                continue
            dest = tpl["check"]["platform"]
            with self.subTest(template=path.stem):
                want = caption_defaults(dest)
                self.assertEqual((cap["size"], cap["margin"]), (want["size"], want["margin"]),
                                 f"{path.name} restates {dest}'s caption size/margin")
                self.assertTrue(PLATFORMS[dest]["frame"])
        # and the filled project takes them from the table, not from the file's literals
        proj = OUT / "tplcap_project.json"
        script("render.py", self.src, "--template", "reels", "--cues", self.cues,
               "--write-project", proj, "-o", str(OUT / "tplcap.mp4"))
        filled = json.loads(proj.read_text())["captions"]
        want = caption_defaults("reels")
        self.assertEqual((filled["size"], filled["margin"]), (want["size"], want["margin"]))

    def test_platform_aliases_resolve_the_same_on_every_tool(self):
        """One resolve(): 'youtube-shorts' is 'shorts' for check, export, caption, graphics, look
        and render alike. Before review 12 the alias map was written, advertised in the docs and
        called from nowhere, so no tool accepted a single one of them."""
        sys.path.insert(0, str(SCRIPTS))
        import render as render_mod
        self.assertEqual(render_mod.expand_templates("ig"), ["reels"])
        self.assertEqual(render_mod.expand_templates("twitter,yt"), ["x", "youtube"])
        self.assertEqual(render_mod.expand_templates("youtube-shorts"), ["youtube-shorts"],
                         "a template that ships under its own name stays itself")
        target = OUT / "alias_src.mp4"
        script("fit.py", self.src, "--duration", "3", "--aspect", "9:16", "--fit", "crop",
               "--width", "360", "--fast", "-o", target)

        def commands(tool, *argv):
            doc = json.loads(script(tool, target, *argv, "--dry-run", "--json").stdout)
            # drawn text goes through a private PER-RUN temp directory (1.15: mkdtemp, 0700,
            # removed at exit), so its random name differs between two processes by design and
            # is not part of what "the same destination" means.
            return [re.sub(r"ffmpeg-skill-text-[^/]+/", "ffmpeg-skill-text/", c)
                    for c in doc["commands"] if "ffmpeg" in c or "drawtext" in c]

        # the alias is the point here, not compliance: a 3 s crop can miss the fps row on some
        # ffmpeg builds (7.1 reports the speed-changed rate differently), and check.py names
        # the resolved platform in its JSON on failure as well as on success
        proc_a = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(target), "--platform",
                                 "youtube-shorts", "--no-loudness", "--json"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        doc_a = json.loads(proc_a.stdout)
        self.assertEqual(doc_a["platform"], "shorts")
        self.assertTrue(doc_a["checks"], "check.py must have run the shorts rows under the alias")
        for tool, argv in (
                ("export.py", ("--preset", "youtube-shorts", "-o", str(OUT / "alias_exp.mp4"))),
                ("caption.py", ("--text", self.cues, "-o", str(OUT / "alias_cap.mp4"), "--platform", "youtube-shorts")),
                ("graphics.py", ("--template", "bug", "--title", "@x", "-o", str(OUT / "alias_gfx.mp4"), "--platform", "youtube-shorts")),
                ("look.py", ("--at", "1", "-o", str(OUT / "alias_look.png"), "--safe", "youtube-shorts"))):
            with self.subTest(tool=tool):
                canonical = tuple("shorts" if a == "youtube-shorts" else a for a in argv)
                self.assertEqual(commands(tool, *argv), commands(tool, *canonical),
                                 f"{tool} must treat youtube-shorts and shorts as one destination")


if __name__ == "__main__":
    unittest.main(verbosity=2)
