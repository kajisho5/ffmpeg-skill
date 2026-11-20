#!/usr/bin/env python3
"""Build the showcase: four AI-generated clips edited with ffmpeg-skill's own tools.

    python3 demos/showcase.py            # -> demos/out/showcase/..., site/media/showcase_*.mp4
    python3 demos/showcase.py --web      # only the site's copies, from what is already built

The footage (demos/footage/grok_*.mp4) is AI-generated with Grok Imagine: the people and places
do not exist. Every step is a call to a script in scripts/, and each one verifies what it wrote.
docs/showcase.md lists the same commands with what each demo shows. The talk's captions are read
from demos/footage/grok_talk_short.srt (written once by `caption.py --transcribe` with
faster-whisper), so the build needs no speech engine.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FOOTAGE = ROOT / "demos" / "footage"
OUT = ROOT / "demos" / "out" / "showcase"
MEDIA = ROOT / "site" / "media"
LOGO = ROOT / "brand" / "app-icon-dark.png"
NOTE = "Footage: AI-generated with Grok Imagine"
KEY = "0x1fbe25"  # the green of grok_greenscreen.mp4, read from its top-left corner


def tool(name, *args):
    cmd = [sys.executable, str(SCRIPTS / f"{name}.py"), *[str(a) for a in args], "--overwrite"]
    print("->", " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, check=True)


def side_by_side(before, after, dest, width, height, audio):
    """grid.py labels each cell with its file name, so the two are copied to those names."""
    pair = dest.parent / "_pair"
    pair.mkdir(exist_ok=True)
    shutil.copy(before, pair / "before.mp4")
    shutil.copy(after, pair / "after.mp4")
    tool("grid", pair / "before.mp4", pair / "after.mp4", "--cols", 2, "--rows", 1, "--cell-width", width,
         "--cell-height", height, "--fps", 24, "--font-size", 22, "--audio-from", audio, "-o", dest)


def rain(src, d):
    tool("color", src, "--correct", "--exposure", 0.45, "--gamma", 1.1, "-o", d / "exposure_corrected.mp4")
    tool("color", src, "--correct", "--exposure", 0.45, "--gamma", 1.1, "--temperature", 7000, "-o", d / "white_balanced.mp4")
    tool("denoise", d / "white_balanced.mp4", "--strength", "low", "-o", d / "denoised.mp4")
    tool("color", d / "denoised.mp4", "--correct", "--contrast", 1.06, "--saturation", 1.22, "-o", d / "color_graded.mp4")
    side_by_side(src, d / "color_graded.mp4", d / "before_after.mp4", 736, 400, 1)


def basketball(src, d):
    tool("fit", src, "--duration", 30.08, "--method", "speed", "--smooth", "blend", "-o", d / "slow_motion.mp4")
    tool("fit", src, "--duration", 7.52, "--method", "speed", "-o", d / "fast_motion.mp4")
    tool("cut", src, "--start", 5.5, "--end", 13.5, "--accurate", "-o", d / "shot.mp4")
    tool("speedramp", d / "shot.mp4", "--segment", "0-1.5:1", "--segment", "1.5-5.5:0.5", "--segment", "5.5-8:1",
         "-o", d / "highlight.mp4")
    # no subject tracking: the player, then the hoop, each with its own fixed crop, joined with a hard cut
    for name, start, end, x in (("a", 5.5, 9.2, 0.5), ("b", 9.2, 13.5, 0.84)):
        tool("cut", src, "--start", start, "--end", end, "--accurate", "-o", d / f"{name}.mp4")
        tool("fit", d / f"{name}.mp4", "--aspect", "9:16", "--fit", "crop", "--crop-x", x, "--width", 720, "--height", 1280,
             "-o", d / f"{name}916.mp4")
    tool("join", d / "a916.mp4", d / "b916.mp4", "--transition", "none", "-o", d / "vertical_9x16.mp4")
    side_by_side(d / "shot.mp4", d / "vertical_9x16.mp4", d / "before_after.mp4", 640, 640, 0)


def talk(src, d):
    tool("loudness", src, "--lufs=-14", "-o", d / "audio_normalized.mp4")
    tool("silence", d / "audio_normalized.mp4", "-o", d / "tight.mp4")
    tool("fit", d / "tight.mp4", "--aspect", "9:16", "--fit", "crop", "--crop-x", 0.17, "--width", 720, "--height", 1280,
         "-o", d / "tight916.mp4")
    tool("caption", d / "tight916.mp4", "--srt", FOOTAGE / "grok_talk_short.srt", "--animate", "pop", "--karaoke",
         "--platform", "reels", "-o", d / "captioned.mp4")
    tool("graphics", d / "captioned.mp4", "--template", "chapter", "--title", "AI x Video Editing", "--position", "top-left",
         "--platform", "reels", "--end", 4.5, "-o", d / "titled.mp4")
    tool("overlay", d / "titled.mp4", "--image", LOGO, "--position", "top-right", "--scale", 96, "--platform", "reels",
         "-o", d / "branded.mp4")
    tool("export", d / "branded.mp4", "--preset", "reels", "-o", d / "social_short.mp4")
    tool("check", d / "social_short.mp4", "--platform", "reels")
    side_by_side(src, d / "social_short.mp4", d / "before_after.mp4", 640, 640, 1)


def greenscreen(src, d):
    tool("background", "--gradient", "0x1a2a4a:0x0b0d12", "--angle", 60, "--width", 736, "--height", 400, "--fps", 24,
         "--duration", 15.04, "-o", d / "bg.mp4")
    tool("overlay", d / "bg.mp4", "--video", src, "--chromakey", KEY, "--chromakey-similarity", 0.18, "--chromakey-blend", 0.08,
         "--position", "260,96", "--margin", 0, "--scale-percent", 76, "-o", d / "keyed.mp4")
    tool("overlay", d / "keyed.mp4", "--text", "Green screen, replaced", "--position", "40,150", "--font-size", 30,
         "--font-color", "white", "-o", d / "titled.mp4")
    tool("overlay", d / "titled.mp4", "--image", LOGO, "--position", "top-left", "--scale", 56, "-o", d / "branded.mp4")
    # overlay.py keeps the main input's sound only, and the background has none: her voice goes back on
    tool("audio", d / "branded.mp4", "--replace", src, "-o", d / "composited.mp4")
    side_by_side(src, d / "composited.mp4", d / "before_after.mp4", 736, 400, 1)


def reel(d):
    """Title card, a few seconds of each demo with a label, end card; both cards say the footage is AI-generated."""
    tool("background", "--gradient", "0x101114:0x1a2a4a", "--angle", 45, "--width", 1280, "--height", 720, "--fps", 24,
         "--duration", 3.5, "-o", d / "card.mp4")
    for name, subtitle in (("title", "Ask for the edit. Get a verified video."), ("end", "github.com/kajisho5/ffmpeg-skill")):
        tool("graphics", d / "card.mp4", "--template", "title", "--title", "ffmpeg-skill", "--subtitle", subtitle, "-o", d / f"{name}_plain.mp4")
        tool("overlay", d / f"{name}_plain.mp4", "--text", NOTE, "--position", "bottom", "--font-size", 24,
             "--font-color", "0xA3A9B4", "--margin", 56, "-o", d / f"{name}.mp4")
    parts = (("a", OUT / "rain" / "before_after.mp4", 4, 10, "Colour: exposure, white balance, denoise, grade"),
             ("b1", OUT / "basketball" / "highlight.mp4", 1, 8, "Speed ramp: 50% slow motion on the shot"),
             ("b2", OUT / "basketball" / "before_after.mp4", 1.5, 7.5, "Reframe 16:9 to 9:16"),
             ("c", OUT / "talk" / "before_after.mp4", 0, 10.3, "Talk to short: loudness, silence cut, captions, 9:16"),
             ("d", OUT / "greenscreen" / "before_after.mp4", 1, 7.5, "Green screen: key, new background, title"))
    for name, src, start, end, label in parts:
        tool("cut", src, "--start", start, "--end", end, "--accurate", "-o", d / f"{name}_cut.mp4")
        tool("fit", d / f"{name}_cut.mp4", "--aspect", "16:9", "--fit", "pad", "--width", 1280, "--height", 720, "-o", d / f"{name}_169.mp4")
        tool("graphics", d / f"{name}_169.mp4", "--template", "chapter", "--title", label, "--position", "top-left", "--scale", 1.4,
             "-o", d / f"{name}.mp4")
    tool("join", d / "title.mp4", *[d / f"{p[0]}.mp4" for p in parts], d / "end.mp4", "--transition", "fade", "--duration", 0.4,
         "--width", 1280, "--height", 720, "--fps", 24, "-o", d / "showreel.mp4")


def main():
    demos = (("rain", rain), ("basketball", basketball), ("talk", talk), ("greenscreen", greenscreen))
    for name, build in demos:
        (OUT / name).mkdir(parents=True, exist_ok=True)
        build(FOOTAGE / f"grok_{name}.mp4", OUT / name)
    (OUT / "reel").mkdir(parents=True, exist_ok=True)
    reel(OUT / "reel")
    # the site's copies: small enough to commit, each with a poster a phone can show before it plays
    web()


def web():
    """site/media/showcase_*.mp4 from what main() built: `python3 demos/showcase.py --web` runs this alone."""
    MEDIA.mkdir(parents=True, exist_ok=True)
    clips = (("reel", OUT / "reel" / "showreel.mp4", 4, "1.5"), ("colour", OUT / "rain" / "before_after.mp4", 2, "6"),
             ("reframe", OUT / "basketball" / "before_after.mp4", 0, "3"), ("short", OUT / "talk" / "before_after.mp4", 0, "2"),
             ("key", OUT / "greenscreen" / "before_after.mp4", 0, "3.5"))
    for name, src, megabytes, at in clips:
        if megabytes:  # the two large ones are encoded down to a size; the others are small as built
            tool("export", src, "--preset", "x", "--no-scale", "--no-normalize", "--max-mb", megabytes, "-o", MEDIA / f"showcase_{name}.mp4")
        else:
            tool("export", src, "--preset", "copy", "-o", MEDIA / f"showcase_{name}.mp4")
        tool("look", MEDIA / f"showcase_{name}.mp4", "--at", at, "--no-timecode", "-o", MEDIA / f"showcase_{name}.jpg")


if __name__ == "__main__":
    web() if sys.argv[1:] == ["--web"] else main()
