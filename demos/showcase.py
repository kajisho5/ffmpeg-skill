#!/usr/bin/env python3
"""Build the showcase: nine AI-generated clips edited with ffmpeg-skill's own tools.

    python3 demos/showcase.py            # -> demos/out/showcase/..., site/media/showcase_*.mp4
    python3 demos/showcase.py --web      # only the site's copies, from what is already built

The footage (demos/footage/veo_*.mp4) is AI-generated with Google Veo: the people and places do
not exist. Every step is a call to a script in scripts/, and each one verifies what it wrote.
docs/showcase.md lists the same commands with what each demo shows. The talks' captions are read
from demos/footage/veo_talk_*.srt (written by `caption.py --transcribe` with faster-whisper and
corrected against what is said) and the slides are demos/footage/slide_*.png, so the build needs
neither a speech engine nor a browser.
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
KEY = "0x50b64f"  # the green of veo_greenscreen.mp4, read from its top-left corner
TEXT = {"en": {"note": "Footage: AI-generated with Google Veo, and three clips shot on a phone", "tag": "Ask for the edit. Get a verified video.",
               "labels": ("Colour: exposure, white balance, denoise, grade", "Speed ramp: 50% slow motion on the shot",
                          "Reframe 16:9 to 9:16", "A talk and its slides, side by side", "The same talk as a captioned short",
                          "Dead air cut: 7.9 s to 5.9 s", "Green screen: key, new background, title", "Horizon straightened",
                          "Handheld, stabilised (phone footage)", "Night shot lifted and denoised (phone footage)"),
               "talk": "AI x Video Editing", "key": "Green screen, replaced"},
        "ja": {"note": "映像は Google Veo による AI 生成と、スマホで撮った実写 3 本です", "tag": "頼むだけで編集。仕上がりは測って確かめます。",
               "labels": ("色: 露出・ホワイトバランス・ノイズ・グレード", "速度変化: シュートを 50% のスローに",
                          "16:9 を 9:16 に組み直す", "講演とスライドを横並びに", "同じ講演を字幕つきのショートに",
                          "間を詰める: 7.9 秒を 5.9 秒に", "グリーンバック: 抜いて背景を差し替え", "水平線をまっすぐに",
                          "手ぶれ補正（スマホの実写）", "暗い夜景を明るくしてノイズ除去（スマホの実写）"),
               "talk": "AI × 動画編集", "key": "グリーンバックを差し替え"}}


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
         "--cell-height", height, "--fps", 24, "--font-size", 26, "--audio-from", audio, "-o", dest)


def rain(d):
    src = FOOTAGE / "veo_rain.mp4"
    tool("color", src, "--correct", "--exposure", 0.35, "--gamma", 1.08, "-o", d / "exposure_corrected.mp4")
    tool("color", src, "--correct", "--exposure", 0.35, "--gamma", 1.08, "--temperature", 7000, "-o", d / "white_balanced.mp4")
    tool("denoise", d / "white_balanced.mp4", "--strength", "low", "-o", d / "denoised.mp4")
    tool("color", d / "denoised.mp4", "--correct", "--contrast", 1.06, "--saturation", 1.18, "-o", d / "color_graded.mp4")
    side_by_side(src, d / "color_graded.mp4", d / "before_after.mp4", 960, 540, 1)


def basketball(d):
    src = FOOTAGE / "veo_basketball.mp4"
    tool("fit", src, "--duration", 15.7, "--method", "speed", "--smooth", "blend", "-o", d / "slow_motion.mp4")
    tool("fit", src, "--duration", 3.925, "--method", "speed", "-o", d / "fast_motion.mp4")
    tool("cut", src, "--start", 1.0, "--end", 6.25, "--accurate", "-o", d / "shot.mp4")
    tool("speedramp", d / "shot.mp4", "--segment", "0-2.2:1", "--segment", "2.2-4.2:0.5", "--segment", "4.2-5.25:1", "-o", d / "highlight.mp4")
    # no subject tracking: the player, then the hoop, each with its own fixed crop, joined with a hard cut
    for name, start, end, x in (("a", 1.0, 4.5, 0.18), ("b", 4.5, 6.25, 0.95)):
        tool("cut", src, "--start", start, "--end", end, "--accurate", "-o", d / f"{name}.mp4")
        tool("fit", d / f"{name}.mp4", "--aspect", "9:16", "--fit", "crop", "--crop-x", x, "--width", 1080, "--height", 1920,
             "-o", d / f"{name}916.mp4")
    tool("join", d / "a916.mp4", d / "b916.mp4", "--transition", "none", "-o", d / "vertical_9x16.mp4")
    # the wide frame and the tall one on one canvas, each at its own shape (a grid's equal cells would letterbox both)
    tool("background", "--color", "0x101114", "--width", 1920, "--height", 1080, "--fps", 24, "--duration", 5.25, "-o", d / "canvas.mp4")
    tool("overlay", d / "canvas.mp4", "--video", d / "shot.mp4", "--position", "48,210", "--margin", 0, "--scale", 1176, "-o", d / "pair1.mp4")
    tool("overlay", d / "pair1.mp4", "--video", d / "vertical_9x16.mp4", "--position", "1288,24", "--margin", 0, "--scale", 580, "-o", d / "pair2.mp4")
    tool("overlay", d / "pair2.mp4", "--text", "16:9", "--position", "48,140", "--margin", 0, "--font-size", 44, "-o", d / "pair3.mp4")
    tool("overlay", d / "pair3.mp4", "--text", "9:16", "--position", "1160,140", "--margin", 0, "--font-size", 44, "-o", d / "pair4.mp4")
    tool("audio", d / "pair4.mp4", "--replace", d / "shot.mp4", "-o", d / "before_after.mp4")


def talk(d, lang):
    """One camera on the speaker and the slides as a second source: side by side, picture in
    picture, a cutaway, and a vertical short with captions."""
    src, t = FOOTAGE / f"veo_talk_{lang}.mp4", TEXT[lang]
    tool("loudness", src, "--lufs=-14", "-o", d / "speaker.mp4")
    for n, seconds in ((1, 4.3), (2, 3.55)):
        tool("insert", FOOTAGE / f"slide_{lang}_{n}.png", "--duration", seconds, "--width", 1920, "--height", 1080, "--fps", 24,
             "-o", d / f"slide{n}.mp4")
    tool("join", d / "slide1.mp4", d / "slide2.mp4", "--transition", "none", "-o", d / "slides.mp4")
    tool("fit", d / "speaker.mp4", "--aspect", "4:5", "--fit", "crop", "--width", 864, "--height", 1080, "-o", d / "speaker_4x5.mp4")
    # side by side: the slides large on the left, the speaker on the right, on a made background
    tool("background", "--gradient", "0x101114:0x1a2a4a", "--angle", 45, "--width", 1920, "--height", 1080, "--fps", 24,
         "--duration", 7.85, "-o", d / "canvas.mp4")
    tool("overlay", d / "canvas.mp4", "--video", d / "slides.mp4", "--position", "48,205", "--margin", 0, "--scale", 1192, "-o", d / "pbp1.mp4")
    tool("overlay", d / "pbp1.mp4", "--video", d / "speaker_4x5.mp4", "--position", "1288,205", "--margin", 0, "--scale", 584, "-o", d / "pbp2.mp4")
    tool("overlay", d / "pbp2.mp4", "--image", LOGO, "--position", "top-left", "--scale", 72, "--margin", 48, "-o", d / "pbp3.mp4")
    tool("audio", d / "pbp3.mp4", "--replace", d / "speaker.mp4", "-o", d / "side_by_side.mp4")
    # picture in picture: the slides full frame, the speaker small in the corner
    tool("overlay", d / "slides.mp4", "--video", d / "speaker_4x5.mp4", "--position", "bottom-right", "--margin", 40, "--scale", 330, "-o", d / "pip1.mp4")
    tool("audio", d / "pip1.mp4", "--replace", d / "speaker.mp4", "-o", d / "picture_in_picture.mp4")
    # a cutaway to the hall while he keeps talking
    tool("broll", d / "speaker.mp4", "--insert", FOOTAGE / "veo_hall.mp4", "--at", 4.4, "--duration", 2.0, "-o", d / "cutaway.mp4")
    # the short: slides on top, speaker below, captions over him, 9:16 for Reels
    tool("fit", d / "speaker.mp4", "--aspect", "1:1", "--fit", "crop", "--width", 1080, "--height", 1080, "-o", d / "speaker_1x1.mp4")
    tool("background", "--color", "0x101114", "--width", 1080, "--height", 1920, "--fps", 24, "--duration", 7.85, "-o", d / "tall.mp4")
    tool("overlay", d / "tall.mp4", "--video", d / "slides.mp4", "--position", "0,232", "--margin", 0, "--scale", 1080, "-o", d / "short1.mp4")
    tool("overlay", d / "short1.mp4", "--video", d / "speaker_1x1.mp4", "--position", "0,840", "--margin", 0, "--scale", 1080, "-o", d / "short2.mp4")
    tool("audio", d / "short2.mp4", "--replace", d / "speaker.mp4", "-o", d / "short3.mp4")
    tool("caption", d / "short3.mp4", "--srt", FOOTAGE / f"veo_talk_{lang}.srt", "--lang", lang, "--animate", "pop", "--karaoke",
         "--platform", "reels", "-o", d / "short4.mp4")
    tool("graphics", d / "short4.mp4", "--template", "chapter", "--title", t["talk"], "--lang", lang, "--position", "top-left",
         "--platform", "reels", "-o", d / "short5.mp4")
    tool("export", d / "short5.mp4", "--preset", "reels", "-o", d / "social_short.mp4")
    tool("check", d / "social_short.mp4", "--platform", "reels")
    side_by_side(src, d / "social_short.mp4", d / "before_after.mp4", 960, 960, 1)


def pause(d):
    """The room is not silent (about -32 dBFS), so the default -35 dB finds no pause: -30 does."""
    src = FOOTAGE / "veo_pause_en.mp4"
    tool("silence", src, "--threshold", -30, "--margin", 0.12, "--min-silence", 0.4, "-o", d / "tight.mp4")
    for part, clip, label in (("before", src, "BEFORE  7.9 s, a long pause"), ("after", d / "tight.mp4", "AFTER  silence.py, 5.9 s")):
        tool("graphics", clip, "--template", "bug", "--title", label, "--position", "top-left", "-o", d / f"{part}.mp4")
    tool("join", d / "before.mp4", d / "after.mp4", "--transition", "none", "-o", d / "before_after.mp4")


def greenscreen(d, lang):
    src = FOOTAGE / "veo_greenscreen.mp4"
    tool("fit", FOOTAGE / "veo_hall.mp4", "--aspect", "16:9", "--width", 1920, "--height", 1080, "--fps", 24, "-o", d / "bg.mp4")
    tool("overlay", d / "bg.mp4", "--video", src, "--chromakey", KEY, "--chromakey-similarity", 0.1, "--chromakey-blend", 0.05,
         "--position", "620,216", "--margin", 0, "--scale-percent", 80, "-o", d / "keyed.mp4")
    tool("overlay", d / "keyed.mp4", "--text", TEXT[lang]["key"], "--position", "96,420", "--font-size", 64, "--font-color", "white",
         "--box", "-o", d / f"titled_{lang}.mp4")
    tool("overlay", d / f"titled_{lang}.mp4", "--image", LOGO, "--position", "top-left", "--scale", 96, "--margin", 64, "-o", d / f"branded_{lang}.mp4")
    # overlay.py keeps the main input's sound only: her voice goes back on
    tool("audio", d / f"branded_{lang}.mp4", "--replace", src, "-o", d / f"composited_{lang}.mp4")
    side_by_side(src, d / f"composited_{lang}.mp4", d / f"before_after_{lang}.mp4", 960, 540, 1)


def horizon(d):
    """The generated clip is level, so the crooked "before" is made here: five degrees on, then five off."""
    tool("straighten", FOOTAGE / "veo_sea.mp4", "--degrees", 5, "-o", d / "crooked.mp4")
    tool("straighten", d / "crooked.mp4", "--degrees=-5", "-o", d / "straightened.mp4")
    side_by_side(d / "crooked.mp4", d / "straightened.mp4", d / "before_after.mp4", 960, 540, 0)


def steady(d):
    """Handheld phone footage of a city at night (real, not generated), stabilised."""
    src = FOOTAGE / "real_city.mp4"
    tool("stabilize", src, "-o", d / "stabilized.mp4")
    side_by_side(src, d / "stabilized.mp4", d / "before_after.mp4", 960, 540, 0)


def lowlight(d):
    """A phone clip of a coast at night (real): lifted, then the noise the lift shows is cleaned."""
    src = FOOTAGE / "real_sea.mp4"
    tool("color", src, "--correct", "--exposure", 1.2, "--gamma", 1.25, "-o", d / "lifted.mp4")
    tool("denoise", d / "lifted.mp4", "--strength", "high", "-o", d / "clean.mp4")
    side_by_side(src, d / "clean.mp4", d / "before_after.mp4", 960, 540, 0)


def slow(d):
    """Fireworks shot at 60 fps (real): played at 24 fps every frame is a real one, 2.5 times slower."""
    src = FOOTAGE / "real_fireworks.mp4"
    tool("fit", src, "--duration", 8.235, "--method", "speed", "--fps", 24, "-o", d / "slow_motion.mp4")
    tool("fit", src, "--fps", 24, "-o", d / "normal.mp4")
    side_by_side(d / "normal.mp4", d / "slow_motion.mp4", d / "before_after.mp4", 960, 540, 0)


def reel(d, lang):
    """Title card, a few seconds of each demo with a label, end card; both cards say the footage is AI-generated."""
    t = TEXT[lang]
    tool("background", "--gradient", "0x101114:0x1a2a4a", "--angle", 45, "--width", 1920, "--height", 1080, "--fps", 24,
         "--duration", 3.5, "-o", d / "card.mp4")
    for name, subtitle in (("title", t["tag"]), ("end", "github.com/kajisho5/ffmpeg-skill")):
        tool("graphics", d / "card.mp4", "--template", "title", "--title", "ffmpeg-skill", "--subtitle", subtitle, "--lang", lang,
             "-o", d / f"{name}_plain_{lang}.mp4")
        tool("overlay", d / f"{name}_plain_{lang}.mp4", "--text", t["note"], "--position", "bottom", "--font-size", 34,
             "--font-color", "0xA3A9B4", "--margin", 84, "-o", d / f"{name}_{lang}.mp4")
    parts = (("a", OUT / "rain" / "before_after.mp4", 1, 6), ("b1", OUT / "basketball" / "highlight.mp4", 0.6, 6.2),
             ("b2", OUT / "basketball" / "before_after.mp4", 0, 5), ("c1", OUT / f"talk_{lang}" / "side_by_side.mp4", 0, 7.8),
             ("c2", OUT / f"talk_{lang}" / "before_after.mp4", 0, 7.8), ("e", OUT / "pause" / "tight.mp4", 0, 4.5),
             ("d", OUT / "greenscreen" / f"before_after_{lang}.mp4", 0.5, 6.5), ("f", OUT / "horizon" / "before_after.mp4", 1, 5.5),
             ("g", OUT / "steady" / "before_after.mp4", 0, 4.8), ("h", OUT / "lowlight" / "before_after.mp4", 0, 4.5))
    for (name, src, start, end), label in zip(parts, t["labels"]):
        tool("cut", src, "--start", start, "--end", end, "--accurate", "-o", d / f"{name}_cut.mp4")
        tool("fit", d / f"{name}_cut.mp4", "--aspect", "16:9", "--fit", "pad", "--width", 1920, "--height", 1080, "-o", d / f"{name}_169.mp4")
        tool("graphics", d / f"{name}_169.mp4", "--template", "chapter", "--title", label, "--lang", lang, "--position", "top-left",
             "--scale", 1.6, "-o", d / f"{name}_{lang}.mp4")
    tool("join", d / f"title_{lang}.mp4", *[d / f"{p[0]}_{lang}.mp4" for p in parts], d / f"end_{lang}.mp4", "--transition", "fade",
         "--duration", 0.4, "--width", 1920, "--height", 1080, "--fps", 24, "-o", d / f"showreel_{lang}.mp4")


def main():
    for name in ("rain", "basketball", "talk_en", "talk_ja", "pause", "greenscreen", "horizon", "steady", "lowlight", "slow", "reel"):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    rain(OUT / "rain")
    basketball(OUT / "basketball")
    pause(OUT / "pause")
    horizon(OUT / "horizon")
    steady(OUT / "steady")
    lowlight(OUT / "lowlight")
    slow(OUT / "slow")
    for lang in ("en", "ja"):
        talk(OUT / f"talk_{lang}", lang)
        greenscreen(OUT / "greenscreen", lang)
        reel(OUT / "reel", lang)
    web()


def web():
    """site/media/showcase_*.mp4 from what main() built, at two thirds of the size and a weight that can be committed."""
    MEDIA.mkdir(parents=True, exist_ok=True)
    wide, tall, full = (1280, 360), (1280, 640), (1280, 720)
    clips = [("colour", OUT / "rain" / "before_after.mp4", wide, "3"), ("reframe", OUT / "basketball" / "before_after.mp4", full, "2.6"),
             ("pause", OUT / "pause" / "before_after.mp4", full, "1"), ("horizon", OUT / "horizon" / "before_after.mp4", wide, "3"),
             ("steady", OUT / "steady" / "before_after.mp4", wide, "2"), ("lowlight", OUT / "lowlight" / "before_after.mp4", wide, "2"),
             ("slow", OUT / "slow" / "before_after.mp4", wide, "1.5")]
    for lang in ("en", "ja"):
        clips += [(f"reel_{lang}", OUT / "reel" / f"showreel_{lang}.mp4", full, "1.5"),
                  (f"talk_{lang}", OUT / f"talk_{lang}" / "side_by_side.mp4", full, "5"),
                  (f"short_{lang}", OUT / f"talk_{lang}" / "before_after.mp4", tall, "5"),
                  (f"key_{lang}", OUT / "greenscreen" / f"before_after_{lang}.mp4", wide, "3")]
    for name, src, (width, height), at in clips:
        tool("fit", src, "--width", width, "--height", height, "-o", OUT / "reel" / "_web.mp4")
        tool("export", OUT / "reel" / "_web.mp4", "--preset", "x", "--no-scale", "--no-normalize", "--crf", 30, "-o", MEDIA / f"showcase_{name}.mp4")
        tool("look", MEDIA / f"showcase_{name}.mp4", "--at", at, "--no-timecode", "-o", MEDIA / f"showcase_{name}.jpg")


if __name__ == "__main__":
    web() if sys.argv[1:] == ["--web"] else main()
