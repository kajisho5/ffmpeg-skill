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
                tools = list(sweep.TABLE) if source == src else ["silence"]
                for tool in tools:
                    row = sweep.row_for(tool, str(source), facts, tmp)
                    if "chapters_not_retimed" in (row.get("warnings") or []):
                        said[tool] = row
            # the multi-range joins are not in the sweep's table (one minimal call per tool)
            for argv in (["--segments", "0-1,2.5-4"], ["--remove", "1-2.5"], ["--segments", "0-1,2.5-4", "--accurate"]):
                doc, _ = sweep.run_json([sys.executable, str(ROOT / "scripts" / "cut.py"), str(src), *argv,
                                         "-o", str(Path(tmp) / "joined.mkv"), "--overwrite", "--json"])
                codes = [w.get("code") for w in ((doc or {}).get("diagnostics") or {}).get("warnings") or []]
                if "chapters_not_retimed" in codes:
                    said["cut " + " ".join(argv)] = doc.get("diagnostics")
            self.assertEqual(said, {}, "these tools moved the picture in time and left the chapters where the source had them")


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
