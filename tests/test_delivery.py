#!/usr/bin/env python3
"""End-to-end tests for export, proxy and the delivery templates.

    python3 tests/test_delivery.py       # this group alone
    python3 tests/test_all.py            # every group
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import (MULTI_PROBED, MediaFixtures, OUT, ROOT, SCRIPTS, frame_rgb, make_multistream,  # noqa: E402
                       sar_clip, script, sh, written_track)
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

    def test_export_dnxhr_masters_read_back_codec_profile_and_pixel_format(self):
        """#419: DNxHR presets beside prores, each checked after the write by codec, profile and
        pixel format (an editing master is asked for by all three), at the source's size and rate."""
        for preset, profile, pix in (("dnxhr-sq", "DNXHR SQ", "yuv422p"), ("dnxhr-hqx", "DNXHR HQX", "yuv422p10le"),
                                     ("dnxhr-444", "DNXHR 444", "yuv444p10le"), ("prores", "HQ", "yuv422p10le")):
            with self.subTest(preset=preset):
                doc = json.loads(script("export.py", self.src, "--preset", preset, "--json",
                                        "-o", OUT / f"export_master_{preset}.mov").stdout)
                self.assertTrue(doc["verified"])
                step = next(s for s in doc["verification"] if s["step"] == "codec")
                self.assertTrue(step["ok"])
                self.assertEqual(step["measured"]["profile"], profile)
                self.assertEqual(step["measured"]["pix_fmt"], pix)
                self.assertEqual((doc["probe"]["video"]["width"], doc["probe"]["video"]["height"]), (1280, 720))

    def test_export_alpha_masters_keep_and_read_back_the_alpha(self):
        """#417: the alpha presets keep the source's alpha, measured on a written frame; an opaque
        source is refused, and --alpha-mode is reported."""
        src = OUT / "alpha_src.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,80),255,64)'",
           "-c:v", "qtrle", src)
        for preset, ext in (("prores4444", "mov"), ("qtrle", "mov"), ("vp9-alpha", "webm")):
            with self.subTest(preset=preset):
                doc = json.loads(script("export.py", src, "--preset", preset, "--json", "--overwrite",
                                        "-o", OUT / f"alpha_{preset}.{ext}").stdout)
                self.assertTrue(doc["verified"], doc["verification"])
                self.assertEqual(doc["alpha_mode"], "straight")
                step = next(s for s in doc["verification"] if s["step"] == "alpha")
                self.assertAlmostEqual(step["measured"], 159.5, delta=2.0)
        # #418: a key/fill pair holds the same frames; the key is the alpha as a luma matte
        doc = json.loads(script("export.py", src, "--preset", "key-fill", "--json", "--overwrite",
                                "-o", OUT / "alpha_fill.mov").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(doc["key"]["output"], str(OUT / "alpha_fill_key.mov"))
        steps = {s["step"]: s for s in doc["verification"]}
        self.assertTrue(steps["key_fill_pair"]["ok"])
        self.assertAlmostEqual(steps["key_level"]["measured"], 159.5, delta=2.0)
        self.assertEqual(len(doc["key"]["sha256"]), 64)
        self.assertNotEqual(doc["key"]["sha256"], doc["fill_sha256"])
        doc = json.loads(script("export.py", src, "--preset", "qtrle", "--alpha-mode", "premultiplied", "--json",
                                "--overwrite", "-o", OUT / "alpha_pm.mov").stdout)
        self.assertEqual(doc["alpha_mode"], "premultiplied")
        self.assertIn("premultiply", " ".join(doc["commands"]))
        proc = script("export.py", self.src, "--preset", "qtrle", "--json", "-o", OUT / "alpha_opaque.mov", expect_fail=True)
        self.assertIn("has none", json.loads(proc.stdout)["error"]["message"])
        proc = script("export.py", self.src, "--preset", "prores", "--alpha-mode", "straight", "--json",
                      "-o", OUT / "alpha_mode_wrong.mov", expect_fail=True)
        self.assertIn("only to the alpha presets", json.loads(proc.stdout)["error"]["message"])

    def _rgba_at(self, path, x, y):
        """One pixel's (r, g, b, a) of a file's first frame (libvpx-vp9 for a .webm)."""
        dec = ["-c:v", "libvpx-vp9"] if str(path).endswith(".webm") else []
        out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *dec, "-i", str(path), "-frames:v", "1",
                              "-vf", f"crop=1:1:{x}:{y},format=rgba", "-f", "rawvideo", "-"],
                             stdout=subprocess.PIPE, check=True).stdout
        return tuple(out[:4])

    def test_export_alpha_review_430(self):
        """#430 review. A VP9 alpha source (probed yuv420p: the alpha is a side layer the native
        decoder drops) is decoded with libvpx-vp9, so its master keeps the alpha, and a dry run
        plans it instead of refusing it as opaque; the alpha is compared over every frame, so a
        source whose first frame is opaque is not measured as opaque; premultiplied colour is
        RGB x alpha."""
        webm = OUT / "alpha_rv_src.webm"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,80),255,64)'",
           "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", webm)
        doc = json.loads(script("export.py", webm, "--preset", "prores4444", "--json", "--overwrite",
                                "-o", OUT / "alpha_rv_from_vp9.mov").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertIn("-c:v libvpx-vp9 -i", doc["commands"][0])
        self.assertAlmostEqual(next(s for s in doc["verification"] if s["step"] == "alpha")["measured"], 159.5, delta=2.0)
        doc = json.loads(script("export.py", webm, "--preset", "prores4444", "--json", "--dry-run",
                                "-o", OUT / "alpha_rv_dry.mov").stdout)
        self.assertEqual(doc["status"], "completed")
        # opaque for its first second, then half transparent: the first frame alone read 255 = 255
        late = OUT / "alpha_rv_late.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=2,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(T,1),255,if(lt(X,80),255,64))'",
           "-c:v", "qtrle", late)
        doc = json.loads(script("export.py", late, "--preset", "prores4444", "--json", "--overwrite",
                                "-o", OUT / "alpha_rv_late_out.mov").stdout)
        step = next(s for s in doc["verification"] if s["step"] == "alpha")
        self.assertTrue(step["ok"], step)
        self.assertAlmostEqual(step["frames"]["expected"]["min"], 159.5, delta=2.0)
        self.assertAlmostEqual(step["frames"]["measured"]["min"], 159.5, delta=2.0)
        self.assertLess(step["expected"], 254.0, "the mean over every frame, not the opaque first frame")
        # premultiplied: the colour at alpha 64 is the straight colour x 64/255
        straight, pm = OUT / "alpha_rv_straight.mov", OUT / "alpha_rv_pm.mov"
        src = OUT / "alpha_rv_flat.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "color=c=0xC08040:s=160x96:r=25:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,80),255,64)'",
           "-c:v", "qtrle", src)
        for out, mode in ((straight, "straight"), (pm, "premultiplied")):
            script("export.py", src, "--preset", "qtrle", "--alpha-mode", mode, "--overwrite", "-o", out)
        s_px, p_px = self._rgba_at(straight, 120, 48), self._rgba_at(pm, 120, 48)
        self.assertEqual((s_px[3], p_px[3]), (64, 64))
        for sc, pc in zip(s_px[:3], p_px[:3]):
            self.assertAlmostEqual(pc, sc * 64 / 255, delta=2)

    # ------------------------------------------------- the alpha path beyond export
    def _alpha_clip(self, name, alpha="if(lt(X,80),255,64)", codec=("-c:v", "prores_ks", "-profile:v", "4",
                                                                       "-pix_fmt", "yuva444p10le"), tags=False):
        """A 160x96, 1 s ProRes 4444 clip (testsrc2's colour) with a partly transparent alpha.
        `tags` labels it BT.709 on the frames (setparams: from 7.1 the encoder takes the tags from
        the frames, and output options alone left an RGB-made clip untagged) and in the stream."""
        path = OUT / name
        label = (",format=yuva444p10le,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
                 if tags else "")
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"testsrc2=s=160x96:r=25:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'{label}", *codec,
           *(("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709") if tags else ()), path)
        return path

    def _rgba_png(self, path, t=0.0):
        """One frame of a file as an RGBA PNG beside it, for _rgba_at (a 4:2:0 file cannot be
        cropped to one pixel before its conversion)."""
        png = Path(str(path) + f".{t:g}.png")
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
           "-vf", "format=rgba", png)
        return png

    @staticmethod
    def _alpha_step(doc):
        return next(s for s in doc["verification"] if s["step"] == "alpha")

    def test_color_keep_alpha_grades_a_prores_4444_clip_and_keeps_its_alpha(self):
        """--keep-alpha: the grade changes the colour and leaves the alpha as it was, frame for
        frame, in ProRes 4444 at 4:4:4 with the source's tags; the step that says so is measured."""
        src = self._alpha_clip("alpha_grade_src.mov", tags=True)
        out = OUT / "alpha_grade_kept.mov"
        # --hw is accepted and leaves the alpha line on the CPU (a note says so); it raised
        # UnboundLocalError once (a local `note` in the --to-sdr branch hid the function)
        doc = json.loads(script("color.py", src, "--correct", "--exposure", "0.5", "--keep-alpha", "--hw", "--json",
                                "-o", out).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        src_v, out_v = probe(str(src))["video"], probe(str(out))["video"]
        for key in ("color_space", "color_primaries", "color_transfer"):
            self.assertEqual(out_v[key], src_v[key], key)
        self.assertEqual(src_v["color_space"], "bt709")
        step = self._alpha_step(doc)
        self.assertTrue(step["ok"])
        self.assertTrue(step["comparison"]["paired"])
        self.assertLessEqual(step["comparison"]["worst_delta"], 2.0)
        self.assertEqual((doc["alpha_codec"], doc["alpha_mode"]), ("prores4444", "straight"))
        m = probe(str(out))
        self.assertEqual(m["video"]["codec"], "prores")
        self.assertTrue(m["video"]["pix_fmt"].startswith("yuva444p"))
        # the alpha survived where it was 64 and 255, and the colour was graded (brighter)
        self.assertAlmostEqual(self._rgba_at(out, 120, 48)[3], 64, delta=2)
        self.assertEqual(self._rgba_at(out, 20, 48)[3], 255)
        self.assertGreater(sum(self._rgba_at(out, 20, 20)[:3]), sum(self._rgba_at(src, 20, 20)[:3]))
        # a .cube LUT keeps it the same way, and qtrle / png / vp9 are lines too
        lut = OUT / "alpha_identity.cube"
        lut.write_text("LUT_3D_SIZE 2\n" + "".join(f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
        for codec, ext in (("qtrle", "mov"), ("png", "mkv"), ("vp9", "webm")):
            with self.subTest(codec=codec):
                doc = json.loads(script("color.py", src, "--lut", lut, "--keep-alpha", "--alpha-codec", codec, "--json",
                                        "-o", OUT / f"alpha_grade_{codec}.{ext}").stdout)
                self.assertTrue(self._alpha_step(doc)["ok"], self._alpha_step(doc))
        # premultiplied colour is the straight colour x alpha
        pm = OUT / "alpha_grade_pm.mov"
        script("color.py", src, "--correct", "--exposure", "0.5", "--keep-alpha", "--alpha-codec", "qtrle",
               "--alpha-mode", "premultiplied", "-o", pm)
        straight = OUT / "alpha_grade_qtrle.mov"
        script("color.py", src, "--correct", "--exposure", "0.5", "--keep-alpha", "--alpha-codec", "qtrle", "-o", straight)
        for sc, pc in zip(self._rgba_at(straight, 120, 48)[:3], self._rgba_at(pm, 120, 48)[:3]):
            self.assertAlmostEqual(pc, sc * 64 / 255, delta=2)

    def test_color_keep_alpha_grades_an_rgb_source_tagged_gbr(self):
        """#454: FFmpeg's PNG encoder tags its stream colorspace `gbr` in .mov/.mkv, and the alpha
        line passed that back as `-colorspace gbr`, which the option parser refuses, so every grade
        of a PNG alpha source failed. `gbr` is now left out (the PNG line tags itself), and the
        grade is the one an untagged RGB source of the same pixels gets."""
        png = OUT / "alpha_gbr_src.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,80),255,64)'",
           "-c:v", "png", png)
        mkv, untagged = OUT / "alpha_gbr_src.mkv", OUT / "alpha_gbr_untagged.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", png, "-c", "copy", mkv)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", png, "-c:v", "qtrle", untagged)
        for src in (png, mkv):
            self.assertEqual(probe(str(src))["video"]["color_space"], "gbr", "the fixture is the reported one")
        lut = OUT / "alpha_gbr_identity.cube"
        lut.write_text("LUT_3D_SIZE 2\n" + "".join(f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
        for src in (png, mkv):
            for grade in (("--lut", lut), ("--correct", "--exposure", "0.5")):
                for codec, ext in (("prores4444", "mov"), ("png", "mkv")):
                    with self.subTest(src=src.suffix, grade=grade[0], codec=codec):
                        out = OUT / f"alpha_gbr_{src.suffix[1:]}_{grade[0][2:]}_{codec}.{ext}"
                        doc = json.loads(script("color.py", src, *grade, "--keep-alpha", "--alpha-codec", codec,
                                                "--json", "-o", out).stdout)
                        self.assertEqual(doc["status"], "completed")
                        self.assertTrue(doc["verified"], doc["verification"])
                        for passed_back in ("-colorspace gbr", "colorspace=gbr"):
                            self.assertNotIn(passed_back, " ".join(doc["commands"]))
                        # the tags reported are the ones written: an RGB line says gbr, and a YUV one
                        # never does (6.1 leaves it untagged; FFmpeg 8 writes the matrix it converted with)
                        written = doc["probe"]["video"]["color_space"]
                        self.assertEqual(written, probe(str(out))["video"]["color_space"])
                        if codec == "png":
                            self.assertEqual(written, "gbr")
                        else:
                            self.assertNotIn(written, ("gbr", "rgb"))
        ref = OUT / "alpha_gbr_untagged_graded.mov"
        script("color.py", untagged, "--correct", "--exposure", "0.5", "--keep-alpha", "-o", ref)
        for x, y in ((20, 20), (120, 48)):
            self.assertEqual(self._rgba_at(OUT / "alpha_gbr_mov_correct_prores4444.mov", x, y), self._rgba_at(ref, x, y))

    def test_every_probed_colour_tag_is_spelled_the_way_its_destination_takes_it(self):
        """#454's class: a probed tag passed back to FFmpeg. ffprobe's names are setparams' names;
        the -colorspace/-color_primaries/-color_trc options refuse three of them (gbr, and the
        transfers bt470m/bt470bg, which they call gamma22/gamma28). Every name ffprobe prints is
        tried in both places, through the helper every such caller uses."""
        from _common.color import carried_tag
        names = {
            "colorspace": ("gbr", "bt709", "fcc", "bt470bg", "smpte170m", "smpte240m", "ycgco", "bt2020nc", "bt2020c",
                           "smpte2085", "chroma-derived-nc", "chroma-derived-c", "ictcp"),
            "color_primaries": ("bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m", "film", "bt2020", "smpte428",
                                "smpte431", "smpte432", "ebu3213"),
            "color_trc": ("bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m", "linear", "log100", "log316",
                          "iec61966-2-4", "bt1361e", "iec61966-2-1", "bt2020-10", "bt2020-12", "smpte2084", "smpte428",
                          "arib-std-b67"),
        }
        head = ("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi")
        tail = ("-frames:v", "1", "-f", "null", "-")
        for kind, values in names.items():
            for name in values:
                with self.subTest(kind=kind, name=name):
                    opt, label = carried_tag(kind, name, "option"), carried_tag(kind, name, "setparams")
                    self.assertEqual(opt is None, name == "gbr")
                    if opt:
                        # The frames already carry the tag the option names, as a carried tag's
                        # do: FFmpeg 8 converts to an output option's colour space when the
                        # input's differs, and swscale has no path to several of these (ictcp,
                        # ycgco, ...), which is a refusal of the conversion, not of the name.
                        sh(*head, "-i", f"color=s=16x16:d=0.04,setparams={kind}={label}", f"-{kind}", opt, *tail)
                        sh(*head, "-i", "color=s=16x16:d=0.04", "-vf", f"setparams={kind}={label}", *tail)
        # the smart cut's x264 line is one such caller: a PAL-tagged H.264 re-encoded part
        import _smartcut
        line = _smartcut.x264_line({"profile": "High", "pix_fmt": "yuv420p", "level": 30, "color_space": "bt470bg",
                                    "color_primaries": "bt470bg", "color_transfer": "bt470bg"}, 18, "veryfast")
        self.assertEqual(line[line.index("-color_trc") + 1], "gamma28")

    def test_color_on_an_alpha_source_without_keep_alpha_is_not_verified(self):
        """Regression: an H.264 grade of a ProRes 4444 clip dropped the alpha and still said
        verified: true. The `alpha` step now fails (alpha_dropped), --drop-alpha records the
        choice instead, and an opaque source gets no alpha step at all (unchanged)."""
        src = self._alpha_clip("alpha_lost_src.mov")
        doc = json.loads(script("color.py", src, "--correct", "--exposure", "0.3", "--json",
                                "-o", OUT / "alpha_lost.mp4").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertFalse(doc["verified"])
        step = self._alpha_step(doc)
        self.assertFalse(step["ok"])
        self.assertEqual((step["reason"], step["attribution"]), ("alpha_dropped", "artifact"))
        self.assertFalse(step["written"]["alpha_plane"])
        self.assertTrue(doc["alpha_dropped"])
        self.assertIn("alpha_dropped", [w.get("code") for w in (doc.get("diagnostics") or {}).get("warnings") or []])
        doc = json.loads(script("color.py", src, "--correct", "--exposure", "0.3", "--drop-alpha", "--json",
                                "-o", OUT / "alpha_lost_ok.mp4").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertNotIn("alpha", [s["step"] for s in doc["verification"]])
        self.assertTrue(doc["alpha_dropped"])
        doc = json.loads(script("color.py", self.src, "--correct", "--exposure", "0.3", "--json",
                                "-o", OUT / "alpha_opaque.mp4").stdout)
        self.assertNotIn("alpha", [s["step"] for s in doc["verification"]])
        self.assertNotIn("alpha_dropped", doc)
        # refusals: nothing to keep, a container that cannot hold the line, two opposite flags
        for argv, needle in (((self.src, "--correct", "--keep-alpha", "-o", OUT / "alpha_x.mov"), "has none"),
                             ((src, "--correct", "--keep-alpha", "-o", OUT / "alpha_x.mp4"), "cannot hold it"),
                             ((src, "--correct", "--keep-alpha", "--drop-alpha", "-o", OUT / "alpha_x.mov"), "opposite"),
                             ((src, "--retag", "bt709", "--keep-alpha", "-o", OUT / "alpha_x.mov"), "copy the stream"),
                             ((src, "--correct", "--alpha-codec", "qtrle", "-o", OUT / "alpha_x.mov"), "apply with --keep-alpha")):
            with self.subTest(argv=argv[1:4]):
                proc = script("color.py", *argv, "--json", expect_fail=True)
                self.assertIn(needle, json.loads(proc.stdout)["error"]["message"])

    def test_color_legalize_with_an_alpha_line_is_refused_and_runs_on_the_opaque_line(self):
        """#432 x #433: --legalize clamps the 8-bit 4:2:0 picture the H.264 line encodes, and every
        --alpha-codec converts the graded picture again after it (10-bit 4:4:4, RGB, yuva420p), so
        --legalize --keep-alpha is refused before ffmpeg runs, as --legalize --codec prores is. With
        --drop-alpha the same source takes the H.264 line: the clamp runs and both the legal_levels
        step and the dropped-alpha record are in one document."""
        src = self._alpha_clip("alpha_legalize_src.mov")
        for codec in (None, "qtrle"):
            with self.subTest(alpha_codec=codec):
                proc = script("color.py", src, "--correct", "--legalize", "bt709", "--keep-alpha",
                              *(("--alpha-codec", codec) if codec else ()), "-o", OUT / "alpha_legalize_x.mov",
                              "--json", expect_fail=True)
                err = json.loads(proc.stdout)
                self.assertEqual(err["error"]["kind"], "input")
                self.assertIn("--keep-alpha", err["error"]["message"])
                self.assertEqual(err["commands"], [])
        doc = json.loads(script("color.py", src, "--correct", "--legalize", "bt709", "--drop-alpha", "--quality", "0",
                                "--preset", "veryfast", "--json", "-o", OUT / "alpha_legalize_opaque.mp4").stdout)
        self.assertRegex(doc["commands"][0], r"format=yuv420p,lutyuv=y=")
        steps = {s["step"]: s for s in doc["verification"]}
        self.assertIn("legal_levels", steps)
        self.assertTrue(steps["legal_levels"]["ok"], steps["legal_levels"])
        self.assertNotIn("alpha", steps)
        self.assertTrue(doc["alpha_dropped"])
        self.assertTrue(doc["verified"], doc["verification"])

    def test_graphics_and_overlay_render_on_a_transparent_canvas(self):
        """background.py --transparent makes the canvas (alpha 0 in every frame, read back);
        graphics.py and overlay.py --keep-alpha draw on it and write the element with its alpha:
        transparent where nothing is drawn, opaque where the bar and the logo are."""
        canvas = OUT / "alpha_canvas.mov"
        doc = json.loads(script("background.py", "--transparent", "--duration", "2", "--width", "320", "--height", "180",
                                "--json", "-o", canvas).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual(self._alpha_step(doc)["frames"]["measured"]["min"], 0.0)
        self.assertEqual(self._rgba_at(canvas, 160, 90)[3], 0)
        gfx = OUT / "alpha_lower_third.mov"
        doc = json.loads(script("graphics.py", canvas, "--template", "lower-third", "--name", "Ada", "--title", "Analyst",
                                "--start", "0", "--keep-alpha", "--json", "-o", gfx).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        step = self._alpha_step(doc)
        self.assertEqual(step["property"], "alpha_at_least_source")
        self.assertTrue(step["written"]["alpha_plane"])
        self.assertTrue(0.0 < step["frames"]["measured"]["mean"] < 128.0, step)
        # a frame after the slide-in: the bar is opaque, the top of the frame is still transparent
        frame = self._rgba_png(gfx, 1.5)
        self.assertEqual(self._rgba_at(frame, 160, 10)[3], 0)
        # the bar is the brand background at 85 % (alpha ~217), its accent stripe opaque
        self.assertGreater(max(self._rgba_at(frame, x, y)[3] for x in range(20, 120, 10) for y in range(120, 175, 5)), 200)
        logo = OUT / "alpha_logo.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=40x40", "-frames:v", "1", logo)
        lay = OUT / "alpha_logo_layer.mov"
        doc = json.loads(script("overlay.py", canvas, "--image", logo, "--position", "center", "--keep-alpha", "--json",
                                "-o", lay).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        r, g, b, a = self._rgba_at(lay, 160, 90)
        self.assertEqual(a, 255)
        self.assertGreater(r, 200)
        self.assertEqual(self._rgba_at(lay, 10, 10)[3], 0)
        # on a BT.709-tagged canvas the RGB logo is converted to BT.709 (6.1's own conversion is
        # BT.601: pure red then decodes as (255,24,0) under the kept tag), and a --video layer is
        # composited at 4:4:4, never through 4:2:0
        canvas709 = OUT / "alpha_canvas_709.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", canvas, "-c", "copy", "-colorspace", "bt709",
           "-color_primaries", "bt709", "-color_trc", "bt709", canvas709)
        lay709 = OUT / "alpha_logo_layer_709.mov"
        script("overlay.py", canvas709, "--image", logo, "--position", "center", "--keep-alpha", "-o", lay709)
        frame = self._rgba_png(lay709)
        r, g, b, a = self._rgba_at(frame, 160, 90)
        self.assertEqual(a, 255)
        self.assertLess(max(g, b), 12, (r, g, b))
        doc = json.loads(script("overlay.py", canvas, "--video", lay, "--position", "0,0", "--margin", "0",
                                "--keep-alpha", "--json", "-o", OUT / "alpha_video_layer.mov").stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertIn("format=yuva444p", doc["commands"][-1])
        self.assertNotIn("yuva420p", doc["commands"][-1])
        # without --keep-alpha the element on a transparent canvas is flattened: not verified
        doc = json.loads(script("graphics.py", canvas, "--template", "bug", "--title", "LIVE", "--json",
                                "-o", OUT / "alpha_bug_flat.mp4").stdout)
        self.assertFalse(doc["verified"])
        self.assertEqual(self._alpha_step(doc)["reason"], "alpha_dropped")

    def test_alpha_checks_do_not_pass_what_they_could_not_read(self):
        """A source that stores an alpha plane whose alpha could not be measured counts as using it
        (never as opaque), so an output without alpha fails; a VP9 layer with alpha on a build with
        no libvpx-vp9 decoder is refused (decoder_missing) instead of being composited opaque; a
        planned input a dry run cannot probe yet is not refused as opaque."""
        sys.path.insert(0, str(SCRIPTS))
        from _common import alpha
        self.assertTrue(alpha.uses_alpha(alpha.UNMEASURED))
        self.assertFalse(alpha.uses_alpha(None))
        flat = OUT / "alpha_unmeasured_out.mp4"
        script("background.py", "--duration", "1", "--width", "160", "--height", "96", "-o", flat)
        step = alpha.lost_step(str(flat), probe(str(flat)), alpha.UNMEASURED)
        self.assertFalse(step["ok"])
        self.assertEqual(step["reason"], "alpha_dropped")
        webm = self._alpha_clip("alpha_nodec.webm", codec=("-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p"))
        saved = alpha._DECODERS
        try:
            alpha._DECODERS = {"vp9"}
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    alpha.decoder_args_for(probe(str(webm)), str(webm))
            alpha._DECODERS = {"vp9", "libvpx-vp9"}
            self.assertEqual(alpha.decoder_args_for(probe(str(webm)), str(webm)), ["-c:v", "libvpx-vp9"])
            # a decoder list that could not be read is unknown, not "missing": the decoder is still named
            alpha._DECODERS = set()
            self.assertEqual(alpha.decoder_args_for(probe(str(webm)), str(webm)), ["-c:v", "libvpx-vp9"])
            self.assertEqual(alpha.vp9_decoder_args("vp9"), ["-c:v", "libvpx-vp9"])
        finally:
            alpha._DECODERS = saved
        # export.py: a VP9 alpha source on a build whose decoder list lacks libvpx-vp9 (the encoder
        # may still be there) is refused before it is measured; measured with FFmpeg's own decoder
        # it read opaque, the written line did too, and the alpha step passed (#433 review)
        shim = OUT / "alpha_nodec_shim"
        shim.mkdir(exist_ok=True)
        real = sh("ffmpeg", "-hide_banner", "-decoders").stdout
        (shim / "decoders.txt").write_text("".join(ln for ln in real.splitlines(True) if " libvpx-vp9 " not in ln))
        if os.name != "nt":
            ff = shutil.which("ffmpeg")
            (shim / "ffmpeg").write_text(f"#!/bin/sh\nif [ \"$2\" = -decoders ]; then cat '{shim / 'decoders.txt'}'; exit 0; fi\n"
                                       f"exec '{ff}' \"$@\"\n")
            (shim / "ffmpeg").chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
            for preset, ext in (("vp9-alpha", "webm"), ("prores4444", "mov")):
                with self.subTest(preset=preset):
                    proc = script("export.py", webm, "--preset", preset, "--json", "--overwrite",
                                  "-o", OUT / f"alpha_nodec_out.{ext}", env=env, expect_fail=True)
                    err = json.loads(proc.stdout)["error"]
                    self.assertEqual(err["reason"], "decoder_missing", err)
                    self.assertFalse((OUT / f"alpha_nodec_out.{ext}").exists())
        planned = OUT / "alpha_planned_canvas.mov"
        if planned.exists():
            planned.unlink()
        # the window is given: a planned clip has no length to default --end to yet (as without
        # --keep-alpha), and the alpha line is planned on it rather than refused as opaque
        doc = json.loads(script("graphics.py", planned, "--template", "bug", "--title", "LIVE", "--start", "0",
                                "--end", "2", "--keep-alpha", "--dry-run", "--json",
                                "-o", OUT / "alpha_planned_bug.mov").stdout)
        self.assertEqual(doc["status"], "completed")
        self.assertEqual(doc["alpha_codec"], "prores4444")
        self.assertIn("prores_ks", doc["commands"][-1])

    def test_overlay_keeps_a_video_layers_alpha(self):
        """A --video layer with alpha shows the picture under its transparent half: a VP9 layer
        (export's vp9-alpha) is decoded with libvpx-vp9, where the native decoder covered the base
        with the layer's colour, and an RGB one (qtrle, PNG in .mov: what graphics.py --keep-alpha
        writes) keeps its alpha plane through its BT.709 conversion, which ended in yuv444p."""
        base = OUT / "alpha_white.mp4"
        script("background.py", "--duration", "1", "--width", "320", "--height", "180", "--color", "white", "-o", base)
        for name, codec in (("alpha_layer.webm", ("-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p")),
                            ("alpha_layer_qtrle.mov", ("-c:v", "qtrle", "-pix_fmt", "argb"))):
            with self.subTest(layer=name):
                layer = self._alpha_clip(name, alpha="if(lt(X,80),255,0)", codec=codec)
                out = OUT / f"{name}_over_white.mp4"
                doc = json.loads(script("overlay.py", base, "--video", layer, "--position", "0,0", "--margin", "0",
                                        "--json", "-o", out).stdout)
                if name.endswith(".webm"):
                    self.assertIn("-c:v libvpx-vp9 -i", " ".join(doc["commands"]))
                frame = self._rgba_png(out)
                self.assertGreater(min(self._rgba_at(frame, 140, 48)[:3]), 240, "the transparent half shows the white base")
                self.assertLess(min(self._rgba_at(frame, 40, 48)[:3]), 240, "the opaque half covers it")
                self.assertNotIn("alpha", [s["step"] for s in doc["verification"]], "an opaque main input gets no alpha step")

    def test_export_key_fill_review_430(self):
        """#430 review: key-fill maps only the fill and the sound (a source with a subtitle track
        added the unfiltered picture and the sound twice), reports the subtitle it does not write,
        compares the video streams' lengths (the fill's sound may run longer than its picture),
        guards the fill like the key (an existing fill, the input under another spelling), and
        refuses --max-mb, which it never applied."""
        late = OUT / "keyfill_rv_alpha.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=2,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,80),255,64)'",
           "-c:v", "qtrle", OUT / "keyfill_rv_v.mov")
        srt = OUT / "keyfill_rv.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", OUT / "keyfill_rv_v.mov", "-f", "lavfi",
           "-i", "sine=d=2.5", "-i", srt, "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "copy",
           "-c:a", "pcm_s16le", "-c:s", "mov_text", late)
        fill = OUT / "keyfill_rv_fill.mov"
        for f in (fill, OUT / "keyfill_rv_fill_key.mov"):
            if f.exists():
                f.unlink()
        doc = json.loads(script("export.py", late, "--preset", "key-fill", "--json", "-o", fill).stdout)
        self.assertTrue(doc["verified"], doc["verification"])
        self.assertEqual([(d["type"], d["reason"]) for d in doc["non_av_streams"]["dropped"]], [("subtitle", "key_fill")])
        self.assertTrue(doc["dropped_non_av_streams"])
        types = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", fill).stdout.split()
        self.assertEqual(types, ["video", "audio"])
        # the key exists only after a run: an existing fill alone is someone's file
        (OUT / "keyfill_rv_fill_key.mov").unlink()
        proc = sh(sys.executable, SCRIPTS / "export.py", late, "--preset", "key-fill", "--json", "-o", fill, expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "output_exists")
        proc = script("export.py", late, "--preset", "key-fill", "--json", "--overwrite",
                      "-o", os.path.join(str(late.parent), ".", late.name), expect_fail=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["reason"], "output_is_input")
        proc = script("export.py", late, "--preset", "key-fill", "--max-mb", "5", "--json",
                      "-o", OUT / "keyfill_rv_mb.mov", expect_fail=True)
        self.assertIn("key-fill", json.loads(proc.stdout)["error"]["message"])

    def test_export_key_fill_without_overwrite_writes_both(self):
        """The plain call, no --overwrite (the script() helper always adds it, which hid this): the
        key is staged in a placeholder this run created, which its own output check must not
        refuse as someone's file."""
        src = OUT / "keyfill_plain_src.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x90:d=1,format=yuva420p", "-c:v", "qtrle", "-pix_fmt", "argb", src)
        fill, key = OUT / "keyfill_plain.mov", OUT / "keyfill_plain_key.mov"
        for f in (fill, key):
            if f.exists():
                f.unlink()
        proc = sh(sys.executable, SCRIPTS / "export.py", src, "--preset", "key-fill", "--json", "-o", fill)
        self.assertEqual(json.loads(proc.stdout)["status"], "completed", proc.stdout)
        self.assertTrue(fill.exists() and key.exists())
        self.assertEqual([p.name for p in OUT.iterdir() if p.name.startswith(".keyfill_plain")], [])

    def test_export_key_fill_failure_removes_only_a_fill_it_created(self):
        """#430 review: run() cleans up ffmpeg's last output (the key) after a failed encode, not the
        fill before it, so a partial fill was left and the retry refused it as output_exists. A
        fill this run created is removed; one that was there before is never touched (it is
        written through a temp file, which is removed too). In-process, with an encode that writes
        part of the fill and then fails."""
        import contextlib
        import importlib
        import io
        from unittest import mock
        from _common import STATE
        export = importlib.import_module("export")
        src = OUT / "keyfill_fail_src.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc2=s=160x96:r=25:d=1,format=rgba", "-c:v", "qtrle", src)
        real_run = export.run

        def failing_run(cmd, **kw):
            if "-filter_complex" not in cmd:
                return real_run(cmd, **kw)
            fill_out = cmd[cmd.index("[key]") - 2]  # the fill's path, just before -map [key]
            Path(fill_out).write_bytes(b"partial")
            raise SystemExit(1)

        def attempt(fill, *extra):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(export, "run", failing_run), \
                    mock.patch.object(sys, "argv", ["export.py", str(src), "--preset", "key-fill", "-o", str(fill), *extra]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                STATE.reset()
                with self.assertRaises(SystemExit):
                    export.main()
            STATE.reset()

        fill = OUT / "keyfill_fail_new.mov"
        if fill.exists():
            fill.unlink()
        attempt(fill)
        self.assertFalse(fill.exists(), "a partial fill this run created is removed")
        self.assertEqual([f.name for f in OUT.glob(".keyfill_fail_new.ffskill-*")], [])
        kept = OUT / "keyfill_fail_kept.mov"
        kept.write_bytes(b"the caller's file")
        attempt(kept, "--overwrite")
        self.assertEqual(kept.read_bytes(), b"the caller's file")
        self.assertEqual([f.name for f in OUT.glob(".keyfill_fail_kept.ffskill-*")], [])

    def test_export_alpha_is_compared_frame_by_frame(self):
        """#430 review: 200 frames, two of them transparent, written with one of those turned
        opaque. The aggregate kept the same min and moved the mean by 1.275 (inside 2), so it
        passed; frame i against frame i fails at that frame. A different frame count (a conformed
        variable-rate source) falls back to the aggregate and says it did (`paired: false`)."""
        import importlib
        export = importlib.import_module("export")

        def stats(per):
            return {"mean": sum(per) / len(per), "min": min(per), "frames": len(per), "per_frame": per}
        src = [255.0] * 198 + [0.0, 0.0]
        lost = [255.0] * 198 + [255.0, 0.0]
        cmp = export._alpha_compare(stats(lost), stats(src))
        self.assertEqual((cmp["ok"], cmp["paired"], cmp["worst_frame"]), (False, True, 198))
        self.assertTrue(export._alpha_compare(stats([v + 1.5 for v in src[:-2]] + [1.0, 1.0]), stats(src))["ok"])
        cmp = export._alpha_compare(stats(src + [0.0]), stats(src))
        self.assertEqual((cmp["ok"], cmp["paired"]), (True, False))
        self.assertFalse(export._alpha_compare(None, stats(src))["ok"])

    def test_export_max_mb_refuses_gif_and_a_limit_that_constrains_nothing(self):
        """2.24.1: --preset gif returned before --max-mb was applied, so a 0.7 MB GIF passed a 1 KB
        limit as verified; --max-mb 1e9 reached libx264 as an impossible bitrate (kind ffmpeg)."""
        for preset, size, ext in (("gif", "0.001", "gif"), ("youtube", "1e9", "mp4")):
            proc = script("export.py", self.src, "--preset", preset, "--max-mb", size, "-o", OUT / f"maxmb_{preset}.{ext}",
                          "--json", expect_fail=True)
            err = json.loads(proc.stdout)["error"]
            self.assertEqual(err["kind"], "input", err)
            self.assertIn("--max-mb", err["message"])

    def test_export_repair_classifies_damage_lines(self):
        """2.24.1: "Packet corrupt (stream = 0, dts = N)" names a dts but is damage, and "Last message
        repeated N times" hid N lines and was itself counted as a decode error; repeat+warning
        prints each occurrence."""
        sys.path.insert(0, str(SCRIPTS))
        import export
        from unittest import mock
        stderr = ("[mpegts @ 0x1] Packet corrupt (stream = 0, dts = 393000).\n"
                  "[vist#0:0/h264 @ 0x2] timestamp discontinuity (stream id=256): -2999999, new offset= 2999999\n"
                  "[null @ 0x3] Application provided invalid, non monotonically increasing dts to muxer in stream 1\n"
                  "[null @ 0x3] Application provided invalid, non monotonically increasing dts to muxer in stream 1\n")
        with mock.patch.object(export, "run_analysis", return_value=subprocess.CompletedProcess([], 0, "", stderr)) as ran:
            self.assertEqual(export.media_damage("x.ts"), {"timestamp_warnings": 3, "decode_errors": 1})
        self.assertIn("repeat+warning", ran.call_args[0][0])

    def test_export_max_mb_fits_the_size(self):
        """2.24: --max-mb 1 on a 10 s clip that is several MB at the preset's CRF: two passes, the
        written file under 1 MiB and measured; a budget too small for the picture, --crf with it,
        and a non-x264 preset are refused before anything runs."""
        src = OUT / "max_mb_src.mp4"
        if not src.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:d=10",
               "-f", "lavfi", "-i", "sine=d=10", "-c:v", "libx264", "-crf", "5", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src)
        out = OUT / "max_mb_out.mp4"
        doc = json.loads(script("export.py", src, "--preset", "youtube", "--max-mb", "1", "--no-scale", "-o", out,
                                "--overwrite", "--json").stdout)
        self.assertLessEqual(out.stat().st_size, 1024 * 1024)
        size = next(v for v in doc["verification"] if v.get("step") == "file_size")
        self.assertTrue(size["ok"] and size["measured"] == out.stat().st_size, size)
        self.assertEqual(sum("-pass" in c for c in doc["commands"]), 2)
        for extra, said in ((["--max-mb", "0.05"], "not watchable"), (["--max-mb", "1", "--crf", "20"], "give one of them"),
                            (["--max-mb", "nan"], "not a finite number"), (["--max-mb", "inf"], "not a finite number")):
            proc = script("export.py", src, "--preset", "youtube", *extra, "-o", OUT / "max_mb_bad.mp4", "--json", expect_fail=True)
            self.assertIn(said, json.loads(proc.stdout)["error"]["message"])
        proc = script("export.py", src, "--preset", "h265", "--max-mb", "1", "-o", OUT / "max_mb_bad.mp4", "--json", expect_fail=True)
        self.assertIn("x264", json.loads(proc.stdout)["error"]["message"])

    def test_export_repair_counts_damage_before_and_after(self):
        """2.24: --preset copy --repair on a recording appended to itself: the input is untouched, the
        counts are reported before and after, timestamp warnings do not grow, remaining decode errors
        are named; --repair with a re-encoding preset is refused."""
        lavfi = ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:d=3", "-f", "lavfi", "-i", "sine=d=3"]
        part = OUT / "repair_part.ts"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *lavfi,
           "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-f", "mpegts", part)
        # the same recording appended to itself byte for byte, as a recorder that reconnected
        # writes it: timestamps jump back and the continuity counters break
        src = OUT / "repair_src.ts"
        src.write_bytes(part.read_bytes() * 2)
        before = src.read_bytes()
        out = OUT / "repair_out.mp4"
        doc = json.loads(script("export.py", src, "--preset", "copy", "--repair", "-o", out, "--overwrite", "--json").stdout)
        self.assertEqual(src.read_bytes(), before)
        rep = doc["repair"]
        self.assertGreater(sum(rep["before"].values()), 0, rep)
        self.assertLessEqual(rep["after"]["timestamp_warnings"], rep["before"]["timestamp_warnings"], rep)
        step = next(v for v in doc["verification"] if v["step"] == "repair")
        self.assertTrue(step["ok"] and step["measured"] == rep["after"]["timestamp_warnings"], step)
        if rep["after"]["decode_errors"]:
            self.assertIn("repair_incomplete", {w["code"] for w in doc["diagnostics"]["warnings"]}, doc.get("diagnostics"))
        proc = script("export.py", src, "--preset", "youtube", "--repair", "-o", OUT / "repair_bad.mp4", "--json", expect_fail=True)
        self.assertIn("--preset copy", json.loads(proc.stdout)["error"]["message"])

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

    # ------------------------------------------- subtitle and data streams (2.23)
    _CUES = "1\n00:00:00,200 --> 00:00:01,000\nfirst cue\n\n2\n00:00:01,200 --> 00:00:01,800\nsecond cue\n"

    def _with_subtitles(self, name, source, seconds="2", extra=()):
        """`source`'s first `seconds` with a mov_text track (language eng) muxed in, the way
        subtitle-skill's render --mode mux delivers one; `extra` adds output options (a timecode)."""
        srt = OUT / f"{name}.srt"
        srt.write_text(self._CUES, encoding="utf-8")
        out = OUT / f"{name}.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source, "-i", srt, "-t", seconds,
           "-map", "0:v", "-map", "0:a?", "-map", "1", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
           "-metadata:s:s:0", "language=eng", *extra, out)
        return out

    def _subtitle_text(self, path):
        return sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:s:0", "-f", "srt", "-").stdout

    def test_a_written_data_track_is_matched_to_a_source_stream_by_codec(self):
        """Data tracks are credited by codec, never by position: two copied streams of one codec
        are both kept, and a muxer's own timecode track is not credited to an unrelated stream."""
        sys.path.insert(0, str(SCRIPTS))
        import export
        src = [{"codec": "bin_data"}, {"codec": "bin_data"}, {"codec": "tmcd"}]
        kept = lambda written: [export._written_data_codec(n, src, [{"codec": c} for c in written]) for n in range(3)]
        self.assertEqual(kept(["bin_data", "bin_data"]), [True, True, False])
        self.assertEqual(kept(["tmcd"]), [False, False, True])
        self.assertEqual(kept(["bin_data"]), [True, False, False])

    def test_export_keeps_a_mov_text_track_for_youtube_and_copy(self):
        """Measured on 2.22.1: a .mp4 with a mov_text track exported with --preset youtube or copy
        came out h264 + aac only, and nothing in the result said so (found by an agent that muxes
        soft subtitles before a platform export). The track is now mapped and kept, and
        non_av_streams says which source stream went where."""
        subbed = self._with_subtitles("export_subs_src", self.src)
        for preset in ("youtube", "copy"):
            with self.subTest(preset=preset):
                out = OUT / f"export_subs_{preset}.mp4"
                doc = json.loads(script("export.py", subbed, "--preset", preset, "--fast", "-o", out, "--json").stdout)
                codecs = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", out).stdout.split()
                self.assertEqual(codecs, ["h264", "aac", "mov_text"])
                self.assertFalse(doc["dropped_non_av_streams"])
                self.assertEqual(doc["non_av_streams"], {"kept": [{"type": "subtitle", "index": 0, "codec": "mov_text",
                                                                   "language": "eng", "output_codec": "mov_text"}],
                                                         "dropped": []})
                self.assertNotIn("non_av_streams_dropped", [f["code"] for f in (doc.get("diagnostics") or {}).get("fallbacks") or []])
                text = self._subtitle_text(out)
                self.assertIn("first cue", text)
                self.assertIn("00:00:00,200 --> 00:00:01,000", text, "a re-encoded picture leaves the cue times alone")
                self.assertEqual(sh("ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream_tags=language",
                                    "-of", "csv=p=0", out).stdout.split(), ["eng"])

    def test_export_keeps_the_subtitle_track_for_every_preset_whose_container_holds_one(self):
        """Every preset but gif writes .mp4 or .mov, which hold mov_text; a GIF holds no stream but
        the picture, and the result says the track was not written rather than nothing."""
        subbed = self._with_subtitles("export_subs_all_src", self.src)
        hdr_subbed = self._with_subtitles("export_subs_hdr_src", self.hdr)
        for preset in ("youtube", "youtube4k", "reels", "tiktok", "shorts", "linkedin", "facebook", "x",
                       "prores", "h265", "youtube-hdr", "youtube-av1", "copy"):
            with self.subTest(preset=preset):
                ext = "mov" if preset == "prores" else "mp4"
                out = OUT / f"export_subs_every_{preset}.{ext}"
                source = hdr_subbed if preset == "youtube-hdr" else subbed
                # not script(): an ffmpeg without an AV1 encoder refuses youtube-av1, and that is not this test's failure
                proc = subprocess.run([sys.executable, str(SCRIPTS / "export.py"), str(source), "--preset", preset, "--no-scale",
                                       "--fast", "-o", str(out), "--json", "--overwrite"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
                doc = json.loads(proc.stdout)
                if preset == "youtube-av1" and doc.get("error", {}).get("kind") == "missing_tool":
                    continue  # this ffmpeg has no AV1 encoder; the preset refuses honestly
                self.assertEqual(doc["status"], "completed", doc.get("error"))
                self.assertEqual([k["output_codec"] for k in doc["non_av_streams"]["kept"]], ["mov_text"], doc["non_av_streams"])
                self.assertFalse(doc["dropped_non_av_streams"])
                self.assertIn("first cue", self._subtitle_text(out))
        out = OUT / "export_subs_every_gif.gif"
        doc = json.loads(script("export.py", subbed, "--preset", "gif", "-o", out, "--json").stdout)
        self.assertEqual(doc["non_av_streams"]["kept"], [])
        self.assertEqual([(d["type"], d["reason"]) for d in doc["non_av_streams"]["dropped"]], [("subtitle", "gif")])
        self.assertTrue(doc["dropped_non_av_streams"])
        self.assertTrue(any("GIF" in n for n in doc["notes"]), doc.get("notes"))

    def test_export_writes_the_probed_streams_with_or_without_a_subtitle_track(self):
        """A118: the picture and sound were mapped only beside a subtitle or data stream; without
        one, FFmpeg's default selection exported the larger picture and the track with the most
        channels, so the same source exported a different audio track once its subtitles were
        stripped. Both now export v:0 and a:0, the streams probe() describes."""
        for subtitle in (True, False):
            src = make_multistream(OUT / f"export_multi_{int(subtitle)}.mkv", subtitle=subtitle)
            for preset in ("youtube", "copy"):
                with self.subTest(subtitle=subtitle, preset=preset):
                    out = OUT / f"export_multi_{int(subtitle)}_{preset}.mkv" if preset == "copy" else \
                        OUT / f"export_multi_{int(subtitle)}_{preset}.mp4"
                    script("export.py", src, "--preset", preset, "--no-scale", "--fast", "-o", out, "--json")
                    m = probe(str(out))
                    self.assertEqual((m["video"]["width"], m["video"]["height"]), MULTI_PROBED["size"])
                    self.assertEqual(written_track(out), "a:0")
                    self.assertEqual(m["subtitle_streams"], int(subtitle))

    def test_export_converts_the_track_to_the_containers_own_text_format(self):
        """mov_text cannot be copied into Matroska nor SubRip into MP4 (ffmpeg refuses the header):
        a copy export that changes container converts the text track instead of dropping it."""
        subbed = self._with_subtitles("export_subs_conv_src", self.src)
        out_mkv = OUT / "export_subs_copy.mkv"
        doc = json.loads(script("export.py", subbed, "--preset", "copy", "-o", out_mkv, "--json").stdout)
        self.assertEqual(doc["non_av_streams"]["kept"][0]["output_codec"], "subrip")
        self.assertIn("first cue", self._subtitle_text(out_mkv))
        out_mp4 = OUT / "export_subs_from_mkv.mp4"
        doc = json.loads(script("export.py", out_mkv, "--preset", "youtube", "--fast", "-o", out_mp4, "--json").stdout)
        self.assertEqual([(k["codec"], k["output_codec"]) for k in doc["non_av_streams"]["kept"]], [("subrip", "mov_text")])
        self.assertIn("first cue", self._subtitle_text(out_mp4))

    def test_export_a_refused_data_stream_does_not_cost_the_subtitles(self):
        """A camera clip's timecode (tmcd) data track cannot be stream-copied into an .mp4; one
        retry without every non-A/V stream (loudness.py's run_keeping_subtitles) would have dropped
        the subtitle track with it. The data stream alone is retried away, and recorded."""
        subbed = self._with_subtitles("export_subs_tc_src", self.src, extra=("-timecode", "01:00:00:00"))
        out = OUT / "export_subs_tc.mp4"
        doc = json.loads(script("export.py", subbed, "--preset", "youtube", "--fast", "-o", out, "--json").stdout)
        fb = [f for f in (doc.get("diagnostics") or {}).get("fallbacks") or [] if f["code"] == "non_av_streams_dropped"]
        self.assertEqual([f["dropped"] for f in fb], [["data"]], fb)
        self.assertEqual([k["type"] for k in doc["non_av_streams"]["kept"] if k["type"] == "subtitle"], ["subtitle"])
        self.assertIn("first cue", self._subtitle_text(out))
        # the MP4 muxer writes its own timecode track from the copied tag, so the read-back is what
        # non_av_streams reports, not what the refused copy suggested
        written = sh("ffprobe", "-v", "error", "-select_streams", "d", "-show_entries", "stream=codec_tag_string",
                     "-of", "csv=p=0", out).stdout.split()
        self.assertEqual(any(k["type"] == "data" for k in doc["non_av_streams"]["kept"]), bool(written))
        self.assertEqual(doc["dropped_non_av_streams"], not written)

    def test_export_trim_to_the_platform_maximum_also_cuts_the_subtitles(self):
        """-t is an output option: the kept track ends where the picture does, and a cue after the
        platform's maximum is not delivered."""
        long_src = OUT / "export_subs_long_src.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=32x32:r=2",
           "-t", "92", "-c:v", "libx264", "-preset", "ultrafast", long_src)
        srt = OUT / "export_subs_long.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nkept cue\n\n2\n00:01:31,000 --> 00:01:31,500\nafter the maximum\n",
                       encoding="utf-8")
        subbed = OUT / "export_subs_long.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", long_src, "-i", srt, "-map", "0", "-map", "1",
           "-c:v", "copy", "-c:s", "mov_text", subbed)
        out = OUT / "export_subs_long_reels.mp4"
        doc = json.loads(script("export.py", subbed, "--preset", "reels", "--no-scale", "--fast", "-o", out, "--json").stdout)
        self.assertEqual(doc["trimmed"], {"from": 92.0, "to": 90.0})
        self.assertFalse(doc["dropped_non_av_streams"])
        text = self._subtitle_text(out)
        self.assertIn("kept cue", text)
        self.assertNotIn("after the maximum", text)

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


class SourceCarryTests(MediaFixtures):
    """#401: what the output lost from its source is said, by every tool, in one place."""

    def test_source_carry_says_what_the_output_lost_from_its_source(self):
        """A dozen tools dropped a subtitle track, chapters, creation_time or surround channels and
        reported verified: true with no note. emit() now compares the first input's items with the
        written file's: `source_carry: {kept, dropped}`, a `source_items_dropped` warning for
        content (not for tags, not for a subtitle loss the tool already reports), and nothing at
        all for a source that carried none of the items."""
        from _common.probe import carry_inventory
        srt = OUT / "carry.srt"
        srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nhi\n", encoding="utf-8")
        meta = OUT / "carry_chapters.txt"
        meta.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=A\n"
                        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=B\n", encoding="utf-8")
        rich = OUT / "carry_rich.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=4",
           "-f", "lavfi", "-i", "sine=d=4", "-i", srt, "-i", meta,
           "-filter_complex", "[1:a]pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0[a]",
           "-map", "0:v", "-map", "[a]", "-map", "2", "-map_metadata", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-c:s", "mov_text", "-metadata", "creation_time=2026-01-02T03:04:05Z",
           "-metadata:s:a:0", "language=jpn", "-timecode", "01:00:00:00", rich)
        probe(str(rich))
        have = carry_inventory(str(rich))
        # the fixture is checked before any tool is: an FFmpeg that stopped writing one of these
        # would otherwise read as "the tool kept nothing"
        self.assertEqual((have["subtitles"], have["chapters"], have["creation_time"], have["audio_language"],
                          have["timecode"], have["audio_channels"]), (1, 2, 1, 1, 1, 6), have)

        def run(tool, *args):
            doc = json.loads(script(tool, *args, "--overwrite", "--json").stdout)
            codes = [w["code"] for w in (doc.get("diagnostics") or {}).get("warnings", [])]
            return doc, codes

        # a tool with no field of its own for the loss: listed, and one warning for the content
        doc, codes = run("crop.py", rich, "--x", "0", "--y", "0", "--width", "160", "--height", "120", "-o", OUT / "carry_crop.mp4")
        carry = doc["source_carry"]
        self.assertIn("subtitles", carry["dropped"], doc)
        self.assertIn("chapters", carry["kept"], doc)
        self.assertIn("audio_channels", carry["kept"], doc)
        self.assertEqual(codes.count("source_items_dropped"), 1, doc)
        warning = next(w for w in doc["diagnostics"]["warnings"] if w["code"] == "source_items_dropped")
        self.assertEqual(warning["dropped"], ["subtitles"], "tags are listed, not warned about")
        self.assertIn("creation_time", carry["dropped"], doc)
        self.assertTrue(doc["verified"], "a report, not a check")
        self.assertTrue(any("subtitle track" in n for n in doc.get("notes") or []), doc)
        self.assertEqual(sorted(carry["kept"] + carry["dropped"]), sorted(set(carry["kept"]) | set(carry["dropped"])))

        # a tool that already says the subtitle track went: listed, not warned about twice
        doc, codes = run("color.py", rich, "--correct", "--contrast", "1.1", "-o", OUT / "carry_color.mp4")
        if doc.get("dropped_non_av_streams"):
            self.assertIn("subtitles", doc["source_carry"]["dropped"], doc)
            self.assertNotIn("source_items_dropped", codes, doc)

        # cut.py reads its own output back as an input: that is not a second source (the stream
        # copy that drops the mov_text track with dropped_non_av_streams false is #401's own case)
        doc, codes = run("cut.py", rich, "--start", "1", "--end", "3", "-o", OUT / "carry_cut.mp4")
        self.assertIn("source_carry", doc, doc)
        if "subtitles" in doc["source_carry"]["dropped"] and not doc.get("dropped_non_av_streams"):
            self.assertIn("source_items_dropped", codes, doc)

        # export keeps the subtitle track: kept, and nothing to warn about
        doc, codes = run("export.py", rich, "--preset", "youtube", "-o", OUT / "carry_export.mp4")
        self.assertIn("subtitles", doc["source_carry"]["kept"], doc)
        self.assertNotIn("source_items_dropped", codes, doc)

        # a sound-only extract has no subtitle track or timecode to lose
        doc, codes = run("audio.py", rich, "-o", OUT / "carry_audio.m4a")
        carry = doc.get("source_carry") or {"kept": [], "dropped": []}
        self.assertNotIn("subtitles", carry["kept"] + carry["dropped"], doc)
        self.assertNotIn("timecode", carry["kept"] + carry["dropped"], doc)

        # a source with none of the items: the key is absent and nothing is warned
        doc, codes = run("crop.py", self.src, "--x", "0", "--y", "0", "--width", "160", "--height", "120", "-o", OUT / "carry_plain.mp4")
        self.assertNotIn("source_carry", doc)
        self.assertNotIn("source_items_dropped", codes)
        # a dry run measured nothing; a still holds none of these; two picture sources are not compared
        doc = json.loads(script("crop.py", rich, "--x", "0", "--y", "0", "--width", "160", "--height", "120",
                                "-o", OUT / "carry_dry.mp4", "--dry-run", "--json").stdout)
        self.assertNotIn("source_carry", doc)
        doc, codes = run("look.py", rich, "--at", "1", "-o", OUT / "carry_look.png")
        self.assertNotIn("source_carry", doc)
        self.assertNotIn("source_items_dropped", codes)
        doc, codes = run("join.py", rich, self.src, "-o", OUT / "carry_join.mp4")
        self.assertNotIn("source_carry", doc)
        self.assertNotIn("source_items_dropped", codes)

    def test_a_tool_that_moves_the_start_moves_the_start_timecode(self):
        """cut, fit --method trim and sync --trim-second wrote the source's start timecode on a
        file that starts later (a cut from 1 s stamped 01:00:00:00 on frame 30: FFmpeg copies the
        stream's tag and the MOV muxer rebuilds a tmcd track from it), and source_carry listed it
        as kept, comparing presence only. The label now moves to the output's first frame,
        drop-frame where the source is; a join of several ranges writes none and says so."""
        from _fixtures import make_tones_take

        def clip(path, rate, tc):
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=160x90:r={rate}:d=4",
               "-f", "lavfi", "-i", "sine=d=4", "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-timecode", tc, path)
            return path

        def written(path):
            tags = sh("ffprobe", "-v", "error", "-show_entries", "stream_tags=timecode:format_tags=timecode",
                      "-of", "csv=p=0", path).stdout.split()
            return sorted(set(tags))

        def run(tool, *args):
            doc = json.loads(script(tool, *args, "--overwrite", "--json").stdout)
            return doc.get("source_carry") or {}

        tc30 = clip(OUT / "tc30.mov", "30", "01:00:00:00")
        tc2997 = clip(OUT / "tc2997.mov", "30000/1001", "01:00:00;00")
        cases = [
            ("cut.py", [tc30, "--start", "0.5", "--end", "1.5", "--accurate"], "tc_accurate.mov", "01:00:00:15"),
            ("cut.py", [tc30, "--start", "1", "--end", "3"], "tc_copy.mov", "01:00:01:00"),
            ("cut.py", [tc30, "--start", "1.2", "--end", "3", "--no-edit-list"], "tc_copy_keyframe.mov", "01:00:01:00"),
            ("cut.py", [tc30, "--start", "1.2", "--end", "3"], "tc_copy_edit_list.mov", "01:00:01:06"),
            ("cut.py", [tc30, "--remove", "0-1"], "tc_remove_head.mov", "01:00:01:00"),
            ("cut.py", [tc2997, "--start", "2.002", "--end", "3.5", "--accurate"], "tc_df.mov", "01:00:02;00"),
            ("fit.py", [tc30, "--duration", "2", "--method", "trim", "--from-center"], "tc_fit.mov", "01:00:01:00"),
        ]
        for tool, args, name, want in cases:
            carry = run(tool, *args, "-o", OUT / name)
            self.assertEqual(written(OUT / name), [want], f"{tool} {args}")
            self.assertIn("timecode", carry.get("kept", []), f"{tool} {args}: {carry}")
        carry = run("cut.py", tc30, "--segments", "1-2,3-4", "-o", OUT / "tc_join.mov")
        self.assertEqual(written(OUT / "tc_join.mov"), [], "a join writes no start timecode")
        self.assertIn("timecode", carry.get("dropped", []), carry)
        # the second camera started 1 s earlier: trimmed by 1 s, its label moves on 30 frames
        ref = make_tones_take(OUT / "tc_sync_ref.mp4", start=1.0, dur=5)
        cam = OUT / "tc_sync_cam.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", make_tones_take(OUT / "tc_sync_cam_tmp.mp4", dur=6),
           "-c", "copy", "-timecode", "10:00:00:00", cam)
        script("sync.py", ref, cam, "--trim-second", "-o", OUT / "tc_sync.mov", "--overwrite")
        self.assertEqual(written(OUT / "tc_sync.mov"), ["10:00:01:00"])

    def _timecode_written(self, path):
        tags = sh("ffprobe", "-v", "error", "-show_entries", "stream_tags=timecode:format_tags=timecode",
                  "-of", "csv=p=0", path).stdout.split()
        return sorted(set(tags))

    def test_a_cut_before_a_late_picture_keeps_the_start_timecode_of_its_first_frame(self):
        """A source whose video starts after the file's origin (0.5 s here): a re-encoded cut from
        0.2 s and a fit trim from 0 both start on the picture's first frame, but the grid lookup
        counted back from it to a frame before the picture and stamped 00:59:59:21 and
        00:59:59:15. The start is clamped to the picture's first frame before the lookup."""
        base, late = OUT / "tc_late_base.mov", OUT / "tc_late.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=3",
           "-f", "lavfi", "-i", "sine=d=3", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p",
           "-c:a", "aac", base)
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-itsoffset", "0.5", "-i", base,
           "-map", "1:v", "-map", "0:a", "-c", "copy", "-timecode", "01:00:00:00", late)
        self.assertAlmostEqual(probe(str(late))["video"]["start_time"], 0.5, places=3)
        for tool, args, name in (("cut.py", ["--start", "0.2", "--end", "2", "--accurate"], "tc_late_cut.mov"),
                                 ("fit.py", ["--duration", "2", "--method", "trim"], "tc_late_fit.mov")):
            script(tool, late, *args, "--preset", "ultrafast", "-o", OUT / name, "--overwrite")
            self.assertEqual(self._timecode_written(OUT / name), ["01:00:00:00"], f"{tool} {args}")

    def test_the_start_timecode_is_counted_at_the_rate_fit_delivers(self):
        """fit --fps 50 on a 25 fps source counted its start timecode at 25: a trim from 0.28 s
        (frame 7) of a source starting 01:00:00:12 was stamped 01:00:00:19, which at 50 fps names
        0.38 s, not 0.76 s; and a rate change alone kept 01:00:00:12 (the source's tmcd track was
        copied), which render.py's clip-then-fit --fps also wrote. The label is now read at the
        source's rate and written at the delivered one; a --fps that keeps the rate changes
        nothing."""
        from _common.timeline import output_timecode_args
        meta = {"timecode": {"value": "01:00:00:12"}, "video": {"fps": 25.0}}
        self.assertEqual(output_timecode_args(meta, 0.28), output_timecode_args(meta, 0.28, 25))
        self.assertEqual(output_timecode_args(meta, 0.28, 50)[1], "timecode=01:00:00:38")
        src = OUT / "tc25.mov"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=2",
           "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-timecode", "01:00:00:12", src)
        for args, name, want in ((["--fps", "50"], "tc25_fps50.mov", "01:00:00:24"),
                                 (["--duration", "1.5", "--method", "trim", "--from-center", "--fps", "50"],
                                  "tc25_trim_fps50.mov", "01:00:00:38"),
                                 (["--duration", "1.5", "--method", "trim", "--from-center"], "tc25_trim.mov", "01:00:00:19"),
                                 (["--fps", "25"], "tc25_fps25.mov", "01:00:00:12")):
            doc = json.loads(script("fit.py", src, *args, "--preset", "ultrafast", "-o", OUT / name,
                                    "--overwrite", "--json").stdout)
            self.assertEqual(self._timecode_written(OUT / name), [want], args)
            self.assertIn("timecode", (doc.get("source_carry") or {}).get("kept", []), f"{args}: {doc.get('source_carry')}")

    def test_the_start_label_rounds_once_and_a_rate_below_one_fps_drops_it(self):
        """00:00:00:02 at 25 fps plus 0.08 s is 4.8 frames at 30 fps: rounded once it is frame 5,
        and the source label and the offset rounded apart made it 2 + 2 = 4. A delivered rate
        below 1 fps rounded to a zero-length day and fit --fps 0.4 raised ZeroDivisionError
        before encoding; no frame count names a frame there, so the label is removed."""
        from _common.timeline import output_timecode_args
        meta = {"timecode": {"value": "00:00:00:02"}, "video": {"fps": 25.0}}
        self.assertEqual(output_timecode_args(meta, 0.08, 30)[1], "timecode=00:00:00:05")
        self.assertEqual(output_timecode_args(meta, 0.08)[1], "timecode=00:00:00:04")
        self.assertEqual(output_timecode_args(meta, 0.0, 0.4), ["-metadata:s:v:0", "timecode=", "-metadata", "timecode="])

    def test_fit_trim_seeks_early_and_drops_the_margin_on_the_output_side(self):
        """fit --method trim seeked straight to its start before -i, which can land on a
        keyframe whose picture follows it (a B-frame HEVC source) and lose the frames before it,
        while the start timecode names the requested frame. It now seeks SEEK_MARGIN early and
        drops the margin after -i, as cut.py does, and still delivers the requested length."""
        src = OUT / "fit_trim_seek.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=4",
           "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-pix_fmt", "yuv420p", src)
        plan = json.loads(script("fit.py", src, "--duration", "2", "--method", "trim", "--from-center",
                                 "-o", OUT / "fit_trim_seek_out.mp4", "--overwrite", "--dry-run", "--json").stdout)
        cmd = (plan.get("commands") or [{}])[0]
        argv = cmd.get("argv") if isinstance(cmd, dict) else cmd
        argv = argv.split() if isinstance(argv, str) else list(argv)
        i = argv.index("-i")
        self.assertEqual(argv[argv.index("-ss"):argv.index("-ss") + 2], ["-ss", "0.000"], argv)
        self.assertEqual(argv[i + 1:].count("-ss"), 1, argv)
        self.assertEqual(argv[argv.index("-ss", i) + 1], "1.000", argv)
        out = OUT / "fit_trim_seek_out.mp4"
        script("fit.py", src, "--duration", "2", "--method", "trim", "--from-center", "--preset", "ultrafast",
               "-o", out, "--overwrite")
        self.assertEqual(probe(str(out))["video"].get("nb_frames") or 50, 50)
        self.assertAlmostEqual(probe(str(out))["duration"], 2.0, delta=0.05)


class GeometryAuditDeliveryTests(unittest.TestCase):
    """Issue #411 (audit H): a delivery preset sizes a non-square-pixel master in square pixels."""

    @classmethod
    def setUpClass(cls):
        import shutil
        if not shutil.which("ffmpeg"):
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        cls.sar = sar_clip(OUT / "g411d_sar.mp4", audio=True)

    def test_export_fills_the_preset_frame_with_a_non_square_pixel_master(self):
        """The 180x180 storage of a SAR 16:9 master was fitted into 1280x720 as a square picture
        with pillarbox bars; squared first, the 320x180 picture fills the frame."""
        out = OUT / "g411d_export.mp4"
        script("export.py", self.sar, "--preset", "x", "-o", out)
        v = probe(str(out))["video"]
        self.assertEqual((v["width"], v["height"], v["sample_aspect_ratio"]), (1280, 720, "1:1"))
        rgb = frame_rgb(out, 0.5, 8, 360)
        self.assertGreater(rgb[0], 180, rgb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
