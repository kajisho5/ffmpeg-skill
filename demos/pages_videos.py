#!/usr/bin/env python3
"""Build the landing page's demo videos with ffmpeg-skill's own tools.

    python3 demos/build.py --only reframe_talk --only filler_en   # the before/after files
    python3 demos/pages_videos.py                                 # -> site/media/*.mp4

The README keeps the GIF previews; the Pages landing page plays these MP4s (with sound). Every
step is a call to a script in scripts/ -- grid.py for the side-by-side, graphics.py for the
labels, join.py to play before and after in turn, look.py for the posters -- and each one
verifies what it wrote, so a video that builds is also a run of those tools on real
(AI-generated) footage.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demos" / "out"
MEDIA = ROOT / "site" / "media"


def tool(name, *args):
    cmd = [sys.executable, str(SCRIPTS / f"{name}.py"), *[str(a) for a in args], "--overwrite"]
    print("->", " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, check=True)


def need(path):
    if not path.exists():
        sys.exit(f"{path} is missing: run python3 demos/build.py --only {path.stem.rsplit('_', 1)[0]} first")
    return path


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # reframe_talk: before and after side by side; grid.py labels each cell with its file name
        before = work / "Before 16x9.mp4"
        after = work / "After fit --aspect 9x16 --crop-x 0.27.mp4"
        shutil.copy(need(OUT / "reframe_talk_before.mp4"), before)
        shutil.copy(need(OUT / "reframe_talk_after.mp4"), after)
        tool("grid", before, after, "--cols", "2", "--rows", "1", "--cell-width", "640", "--cell-height", "432",
             "--audio-from", "0", "--background", "0x0b0f0c", "-o", MEDIA / "reframe_talk.mp4")
        # filler_en: the sound is the point, so the two play one after the other, each labelled
        for part, label in (("before", "BEFORE  (er, um left in)"), ("after", "AFTER  silence.py --filler")):
            tool("graphics", need(OUT / f"filler_en_{part}.mp4"), "--template", "bug", "--title", label,
                 "--position", "top-left", "-o", work / f"filler_{part}.mp4")
        tool("join", work / "filler_before.mp4", work / "filler_after.mp4", "--transition", "none",
             "-o", MEDIA / "filler_en.mp4")
    # posters: a phone shows nothing in a <video> until it plays, so each gets a frame from look.py
    for name, at in (("reframe_talk", "2"), ("filler_en", "1.5")):
        tool("look", MEDIA / f"{name}.mp4", "--at", at, "--no-timecode", "-o", MEDIA / f"{name}.jpg")


if __name__ == "__main__":
    main()
