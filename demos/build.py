#!/usr/bin/env python3
"""Build the before/after demo gallery: synthetic footage in, previews out.

Everything here is generated from nothing -- ffmpeg's own synthetic sources (testsrc2,
mandelbrot, life, aevalsrc) make the footage, and every "after" file is produced by running
this repo's own scripts, so a demo that renders is also a smoke test of the tool behind it.

    python3 demos/build.py                 # build every demo
    python3 demos/build.py --list          # names + groups, render nothing
    python3 demos/build.py --only captions_ja
    python3 demos/build.py --docs          # rewrite docs/demos.md from the table, render nothing

Each demo writes demos/out/<name>_before.mp4, demos/out/<name>_after.mp4, a side-by-side
demos/out/<name>.mp4 (640 px wide, <= 6 s) and a palette-optimised preview
docs/demos/<name>.gif (<= 480 px, 10-12 fps). The preview is the only file committed, so the
build FAILS if any of them is over 500 KB rather than letting a fat binary into git.

demos/out/ is gitignored; --keep-fixtures (the default) reuses fixtures across runs, so a
second run of --only is fast. Python 3.9 standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = Path(os.environ.get("DEMO_OUT", ROOT / "demos" / "out"))
FIX = OUT / "fixtures"
PREVIEWS = ROOT / "docs" / "demos"

PREVIEW_MAX_BYTES = 500 * 1024      # hard limit: the build fails rather than commit a fatter file
PREVIEW_TARGET_BYTES = 250 * 1024   # what the ladder aims for, so the cap is never a near miss
CELL_W, CELL_H = 320, 180          # each half of the side-by-side; 640 px wide in total
COMPARE_MAX_SECONDS = 6.0
PY = sys.executable or "python3"

sys.path.insert(0, str(SCRIPTS))
from _common import font_for_script, script_font_status  # noqa: E402

# A speech-like bed: a two-formant "voice" gated by a slow square wave, so there are real
# pauses for silence.py to find and real level changes for loudness.py to move.
SPEECH = ("0.45*(sin(2*PI*180*t)+0.5*sin(2*PI*420*t)+0.25*sin(2*PI*900*t))"
          "*gt(sin(2*PI*0.55*t)\\,0.15)*(0.6+0.4*sin(2*PI*5*t))")
# A music-like tone bed: a held triad with a pulsing fifth, quiet enough to duck under speech.
MUSIC = "0.30*sin(2*PI*110*t)+0.22*sin(2*PI*165*t)+0.18*sin(2*PI*220*t)*gt(sin(2*PI*2*t)\\,0)"


# --------------------------------------------------------------------------- process helpers
class BuildError(RuntimeError):
    pass


def run(cmd, capture=False):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise BuildError("command failed: %s\n%s\n%s" % (" ".join(str(c) for c in cmd),
                                                         proc.stdout[-2000:], proc.stderr[-2000:]))
    return proc.stdout if capture else None


def ffmpeg(*args):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + list(args))


def duration(path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)], capture=True)
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def label_font() -> str:
    """A concrete font file for the BEFORE/AFTER labels drawn on the comparison."""
    for script in ("latin", "ja"):
        path = font_for_script(script)
        if path:
            return path
    for guess in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "C:\\Windows\\Fonts\\arial.ttf"):
        if Path(guess).exists():
            return guess
    raise BuildError("no usable font found for the BEFORE/AFTER labels")


def esc(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter argument (fontfile=)."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# --------------------------------------------------------------------------- context
class Ctx:
    """One demo's working area. Records every skill-script invocation it makes, so the gallery
    page can print the exact command that produced the picture instead of a retyped one."""

    def __init__(self, name, verbose=True):
        self.name = name
        self.verbose = verbose
        self.commands = []
        self.notes = []

    def path(self, suffix):
        return OUT / ("%s_%s" % (self.name, suffix))

    def script(self, tool, *args, capture=False):
        """Run scripts/<tool> and record it as a copyable one-liner."""
        cmd = [PY, str(SCRIPTS / tool)] + [str(a) for a in args]
        self.commands.append(" ".join(["python3", "scripts/" + tool] + [_short(a) for a in args]))
        if self.verbose:
            print("    $ " + self.commands[-1])
        return run(cmd, capture=capture)

    def note(self, text):
        self.notes.append(text)


def _short(arg) -> str:
    """Render an argument for the docs: absolute paths under demos/out become relative."""
    text = str(arg)
    for base, prefix in ((OUT, "demos/out"), (ROOT, "")):
        try:
            rel = Path(text).resolve().relative_to(base)
        except (ValueError, OSError):
            continue
        text = (prefix + "/" + str(rel).replace("\\", "/")).lstrip("/")
        break
    return "'%s'" % text if " " in text and not text.startswith("'") else text


# --------------------------------------------------------------------------- fixtures
def build_fixtures(force=False):
    """Synthetic source material. Nothing here is downloaded and nothing is committed."""
    FIX.mkdir(parents=True, exist_ok=True)
    made = []

    def need(name):
        path = FIX / name
        if force or not path.exists() or path.stat().st_size == 0:
            made.append(name)
            return path
        return None

    # 1. The main clip: a moving test pattern with speech-like audio (pauses included).
    path = need("motion.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000" % SPEECH,
               "-t", "8", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(path))

    # 2. A fractal zoom: real, non-repeating motion, so a transition or a speed change is
    #    actually visible frame to frame (a static pattern hides both).
    path = need("mandel.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=30:maxiter=200",
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000" % MUSIC,
               "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(path))

    # 3. Conway's life: coarse cells at 12 fps -- real motion that a GIF palette can still
    #    carry (a fine-grained life pattern changes every pixel every frame and blows the budget).
    path = need("life.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i",
               "life=size=80x45:rate=12:mold=32:ratio=0.1:death_color=#101030:life_color=#39ff88",
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000" % MUSIC,
               "-t", "6", "-vf", "scale=1280:720:flags=neighbor,fps=30", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", str(path))

    # 4. A music bed on its own, for the ducking demo.
    path = need("music.m4a")
    if path:
        ffmpeg("-f", "lavfi", "-i", "aevalsrc='%s':s=48000" % MUSIC,
               "-t", "8", "-c:a", "aac", "-b:a", "128k", str(path))

    # 5. A 5.1 clip: six distinct tones, one per channel, so a downmix is audible and provable.
    path = need("surround.mp4")
    if path:
        tones = ["0.5*sin(2*PI*%d*t)" % f for f in (220, 330, 440, 60, 550, 660)]
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000:c=5.1" % "|".join(tones),
               "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "6", str(path))

    # 6. An HDR10 clip: 10-bit HEVC tagged PQ / BT.2020, like tests/ builds.
    path = need("hdr10.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000" % MUSIC, "-t", "5",
               "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
               "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error",
               "-tag:v", "hvc1", "-c:a", "aac", str(path))

    # 7. A semi-transparent logo for the overlay demo.
    path = need("logo.png")
    if path:
        ffmpeg("-f", "lavfi", "-i", "color=c=0xff5533@0.85:s=240x90,format=rgba",
               "-frames:v", "1", str(path))

    # 8. Caption cues, one file per script, in caption.py's plain-text cue format.
    cues = {
        "cues_en.txt": ["0:00-0:02 Shot on nothing but FFmpeg",
                        "0:02-0:04 Captions burned in with libass",
                        "0:04-0:06 No cloud. No API keys.",
                        "0:06-0:08 Just python3 and ffmpeg."],
        "cues_ja.txt": ["0:00-0:02 FFmpeg だけで作った映像です",
                        "0:02-0:04 字幕は libass で焼き込み",
                        "0:04-0:06 クラウドも API キーも不要",
                        "0:06-0:08 python3 と ffmpeg だけ"],
        "cues_zh.txt": ["0:00-0:02 完全由 FFmpeg 生成的画面",
                        "0:02-0:04 字幕用 libass 烧录",
                        "0:04-0:06 不需要云端，也不需要密钥",
                        "0:06-0:08 只要 python3 和 ffmpeg"],
        "cues_ko.txt": ["0:00-0:02 FFmpeg 만으로 만든 영상입니다",
                        "0:02-0:04 자막은 libass 로 굽습니다",
                        "0:04-0:06 클라우드도 API 키도 필요 없습니다",
                        "0:06-0:08 python3 과 ffmpeg 만 있으면 됩니다"],
        "cues_ar.txt": ["0:00-0:02 فيديو من صنع FFmpeg وحده",
                        "0:02-0:04 الترجمة محروقة عبر libass",
                        "0:04-0:06 بلا سحابة وبلا مفاتيح",
                        "0:06-0:08 يكفي python3 و ffmpeg"],
        "cues_pop.txt": ["0:00-0:02 word by word",
                         "0:02-0:04 the karaoke highlight tracks the beat",
                         "0:04-0:06 pop scales each cue in",
                         "0:06-0:08 all of it is plain ASS"],
    }
    for name, lines in cues.items():
        path = need(name)
        if path:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 9. A render.py project that stitches several of the above into one edit.
    path = need("project.json")
    if path:
        project = {
            "output": str(OUT / "render_project_after.mp4"),
            "frame": {"aspect": "16:9", "width": 960, "fps": 30},
            "clips": [{"src": str(FIX / "motion.mp4"), "in": 0, "out": 3},
                      {"src": str(FIX / "mandel.mp4"), "in": 0, "out": 3}],
            "transition": {"type": "fade", "duration": 0.5},
            "captions": {"text": str(FIX / "cues_en.txt"), "animate": "pop", "size": 26,
                         "position": "bottom"},
            "graphics": [{"template": "title", "title": "ffmpeg-skill",
                          "subtitle": "one project file, one render", "start": 0, "end": 2.5}],
            "export": {"preset": "youtube"},
        }
        path.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")

    return made


# --------------------------------------------------------------------------- comparison + preview
def _side(idx, label, font, seconds):
    """One half of the side-by-side: letterboxed into a fixed cell so a 9:16 'after' and a
    16:9 'before' still stack cleanly, held on its last frame if it is the shorter of the two."""
    return ("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x101014,setsar=1,fps=25,"
            "tpad=stop_mode=clone:stop_duration=%.2f,"
            "drawtext=fontfile='%s':text='%s':fontsize=18:fontcolor=white:borderw=2:"
            "bordercolor=black@0.8:x=(w-text_w)/2:y=6[v%d]"
            % (idx, CELL_W, CELL_H, CELL_W, CELL_H, seconds, esc(font), label, idx))


def make_compare(before, after, dest, font):
    """640x180 side-by-side, <= 6 s. Both sides are held on their last frame to the same
    length, so silence removal (a genuinely shorter 'after') reads as the timeline shrinking
    rather than as one side simply vanishing."""
    seconds = min(COMPARE_MAX_SECONDS, max(duration(before), duration(after)) or COMPARE_MAX_SECONDS)
    chain = "%s;%s;[v0][v1]hstack=inputs=2[out]" % (_side(0, "BEFORE", font, COMPARE_MAX_SECONDS),
                                                    _side(1, "AFTER", font, COMPARE_MAX_SECONDS))
    ffmpeg("-i", str(before), "-i", str(after), "-filter_complex", chain,
           "-map", "[out]", "-t", "%.2f" % seconds, "-an", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(dest))
    return dest


def make_wave_compare(before, after, dest, font, labels=("BEFORE", "AFTER")):
    """For audio-only work there is nothing to see in the video, so the comparison is the two
    waveforms (showwavespic) side by side, held for 3 s."""
    pics = []
    for idx, src in enumerate((before, after)):
        pic = OUT / ("%s_wave%d.png" % (dest.stem, idx))
        ffmpeg("-i", str(src), "-filter_complex",
               "[0:a]aformat=channel_layouts=stereo,showwavespic=s=%dx%d:colors=0x39ff88|0x33aaff"
               % (CELL_W, CELL_H), "-frames:v", "1", str(pic))
        pics.append(pic)
    chain = ";".join([
        "[0:v]pad=%d:%d:0:0:color=0x101014,drawtext=fontfile='%s':text='%s':fontsize=18:"
        "fontcolor=white:borderw=2:bordercolor=black@0.8:x=(w-text_w)/2:y=6[v0]"
        % (CELL_W, CELL_H, esc(font), labels[0]),
        "[1:v]pad=%d:%d:0:0:color=0x101014,drawtext=fontfile='%s':text='%s':fontsize=18:"
        "fontcolor=white:borderw=2:bordercolor=black@0.8:x=(w-text_w)/2:y=6[v1]"
        % (CELL_W, CELL_H, esc(font), labels[1]),
        "[v0][v1]hstack=inputs=2,format=yuv420p[out]"])
    ffmpeg("-loop", "1", "-t", "3", "-i", str(pics[0]), "-loop", "1", "-t", "3", "-i", str(pics[1]),
           "-filter_complex", chain, "-map", "[out]", "-r", "10", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "24", str(dest))
    return dest


def make_preview(compare_mp4, dest):
    """Palette-optimised GIF, aiming at 250 KB and hard-capped at 500 KB.

    The ladder steps quality down only as far as it has to: a still waveform comparison lands
    at a few KB on the first rung, a noisy fractal walks several rungs down. Aiming below the
    cap rather than at it matters because GIF size varies with the ffmpeg build -- a preview
    that squeaks in at 499 KB here would fail the same check on a different runner.
    """
    # fps, width, palette colours, seconds: the preview is a taster, not the deliverable, so
    # it is allowed to be shorter than the 6 s side-by-side it is cut from.
    ladder = [(12, 480, 96, 4.0), (10, 480, 64, 4.0), (10, 480, 48, 3.5), (10, 420, 48, 3.5),
              (10, 380, 32, 3.5), (10, 320, 24, 3.0)]
    last = None
    for fps, width, colors, seconds in ladder:
        chain = ("fps=%d,scale=%d:-2:flags=lanczos,split[s0][s1];"
                 "[s0]palettegen=max_colors=%d:stats_mode=diff[p];"
                 "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
                 % (fps, width, colors))
        ffmpeg("-i", str(compare_mp4), "-t", "%.2f" % seconds, "-filter_complex", chain,
               "-loop", "0", str(dest))
        last = (dest.stat().st_size, fps, width, colors)
        if last[0] <= PREVIEW_TARGET_BYTES:
            return last
    if last[0] <= PREVIEW_MAX_BYTES:  # under the cap, just not under the target
        return last
    raise BuildError("preview %s is %d bytes, over the %d byte budget even at the smallest "
                     "setting -- shorten the demo or drop its frame rate"
                     % (dest.name, last[0], PREVIEW_MAX_BYTES))


# --------------------------------------------------------------------------- demos
def _caption_demo(ctx, cues, extra=()):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("caption.py", before, "--text", FIX / cues, "--size", "30", "--bold",
               "--position", "bottom", "--margin", "40", *extra, "-o", after)
    return before, after


def demo_captions_en(ctx):
    return _caption_demo(ctx, "cues_en.txt")


def demo_captions_ja(ctx):
    return _caption_demo(ctx, "cues_ja.txt")


def demo_captions_zh(ctx):
    return _caption_demo(ctx, "cues_zh.txt")


def demo_captions_ko(ctx):
    return _caption_demo(ctx, "cues_ko.txt")


def demo_captions_ar(ctx):
    return _caption_demo(ctx, "cues_ar.txt")


def demo_captions_pop_karaoke(ctx):
    return _caption_demo(ctx, "cues_pop.txt", ("--animate", "pop", "--karaoke",
                                               "--highlight-color", "#39ff88"))


def demo_lower_third(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("graphics.py", before, "--template", "lower-third", "--name", "Ada Lovelace",
               "--title", "Analytical Engine", "--start", "0.5", "--end", "5", "-o", after)
    return before, after


def demo_title_card(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("graphics.py", before, "--template", "title", "--title", "Episode 12",
               "--subtitle", "The math of video", "--start", "0", "--end", "4", "-o", after)
    return before, after


def demo_logo_overlay(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("overlay.py", before, "--image", FIX / "logo.png", "--position", "top-right",
               "--scale", "200", "--opacity", "0.9", "--start", "0.5", "--end", "7.5",
               "--fade", "0.6", "-o", after)
    return before, after


def demo_hdr_tonemap(ctx):
    before = FIX / "hdr10.mp4"
    after = ctx.path("after.mp4")
    ctx.script("color.py", before, "--to-sdr", "--tonemap", "hable", "--preset", "veryfast",
               "-o", after)
    return before, after


def demo_reframe_crop(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("fit.py", before, "--aspect", "9:16", "--fit", "crop", "--width", "540",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_reframe_pad(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("fit.py", before, "--aspect", "9:16", "--fit", "pad", "--pad-fill", "blur",
               "--width", "540", "--preset", "veryfast", "-o", after)
    return before, after


def demo_speed_up(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("fit.py", before, "--duration", "4", "--method", "speed", "--preset", "veryfast",
               "-o", after)
    return before, after


def demo_reverse(ctx):
    before = FIX / "life.mp4"
    after = ctx.path("after.mp4")
    ctx.script("reverse.py", before, "--preset", "veryfast", "-o", after)
    return before, after


def demo_join_fade(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("join.py", FIX / "motion.mp4", FIX / "mandel.mp4", "--transition", "fade",
               "--duration", "0.8", "--width", "960", "--preset", "veryfast", "-o", after)
    return before, after


def demo_join_fadeblack(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("join.py", FIX / "motion.mp4", FIX / "mandel.mp4", "--transition", "fadeblack",
               "--duration", "0.8", "--width", "960", "--preset", "veryfast", "-o", after)
    return before, after


def demo_silence_removal(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("silence.py", before, "--threshold", "-35", "--min-silence", "0.4",
               "--margin", "0.1", "--preset", "veryfast", "-o", after)
    ctx.note("%.2f s in, %.2f s out" % (duration(before), duration(after)))
    return before, after


def demo_loudness(ctx):
    """The input is deliberately quiet, so the two waveforms differ by more than rounding."""
    before = ctx.path("before.mp4")
    ffmpeg("-i", str(FIX / "motion.mp4"), "-af", "volume=-14dB", "-c:v", "copy", "-c:a", "aac",
           str(before))
    after = ctx.path("after.mp4")
    ctx.script("loudness.py", before, "-I", "-14", "--tp", "-1", "-o", after)
    return before, after


def demo_downmix_51(ctx):
    before = FIX / "surround.mp4"
    after = ctx.path("after.mp4")
    ctx.script("audio.py", before, "--downmix", "-o", after)
    return before, after


def demo_bgm_ducking(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("audio.py", before, "--music", FIX / "music.m4a", "--duck", "--duck-amount", "12",
               "--music-volume", "0.6", "--fade-out", "1.5", "-o", after)
    return before, after


def demo_export_reels(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("export.py", before, "--preset", "reels", "--fit", "crop", "-o", after)
    report = ctx.script("check.py", after, "--platform", "reels", "--json", capture=True)
    if report:
        (OUT / ("%s_check.json" % ctx.name)).write_text(report, encoding="utf-8")
        ctx.note("check.py --platform reels: %s" % json.loads(report).get("status", "?"))
    return before, after


def demo_render_project(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("render.py", FIX / "project.json", "--fast")
    if not after.exists():
        raise BuildError("render.py did not write %s" % after)
    return before, after


def demo_contact_sheet(ctx):
    """look.py answers 'did that actually work?' with a picture; the 'after' side of the
    comparison is that contact sheet, held as video so the gallery can show it inline."""
    before = FIX / "mandel.mp4"
    sheet = ctx.path("sheet.png")
    ctx.script("look.py", before, "--tiles", "4x3", "--width", "960", "-o", sheet)
    after = ctx.path("after.mp4")
    ffmpeg("-loop", "1", "-t", "3", "-i", str(sheet), "-vf",
           "scale=960:-2,format=yuv420p", "-r", "10", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "24", str(after))
    return before, after


CAPTIONS, PICTURE, AUDIO, DELIVERY, PROJECTS = (
    "Captions & text", "Picture", "Audio", "Delivery & checks", "Projects & inspection")

DEMOS = [
    # name, group, title, what to look for, builder, comparison kind, required script
    ("captions_en", CAPTIONS, "Burned-in captions (English)",
     "Plain-text cues become an SRT and are rendered by libass -- outline and margin come from the flags, not from a template.",
     demo_captions_en, "video", "latin"),
    ("captions_ja", CAPTIONS, "Japanese captions",
     "The font is chosen per script: Japanese cues get a CJK face automatically, so no box-glyph tofu appears.",
     demo_captions_ja, "video", "ja"),
    ("captions_zh", CAPTIONS, "Chinese captions",
     "Same command, Han text: line breaking and the font switch are handled without a --font flag.",
     demo_captions_zh, "video", "zh"),
    ("captions_ko", CAPTIONS, "Korean captions",
     "Hangul wins script detection even when Latin words are mixed into the same cue.",
     demo_captions_ko, "video", "ko"),
    ("captions_ar", CAPTIONS, "Arabic captions",
     "Right-to-left text shaped by libass; the Latin fragments inside it stay left-to-right.",
     demo_captions_ar, "video", "ar"),
    ("captions_pop_karaoke", CAPTIONS, "Animated pop captions with karaoke",
     "Each cue scales in, and the highlight colour walks word by word across the line.",
     demo_captions_pop_karaoke, "video", "latin"),
    ("lower_third", CAPTIONS, "Lower third",
     "Name and role slide in from the left over the picture and slide out again -- no image asset involved.",
     demo_lower_third, "video", "latin"),
    ("title_card", CAPTIONS, "Title card",
     "A centred title and subtitle fade in over the first seconds and leave the rest of the clip untouched.",
     demo_title_card, "video", "latin"),

    ("logo_overlay", PICTURE, "Logo overlay with fade",
     "The semi-transparent logo fades in at 0.5 s and out before the end; the underlying picture is unchanged.",
     demo_logo_overlay, "video", None),
    ("hdr_tonemap", PICTURE, "HDR10 to SDR",
     "The PQ / BT.2020 source is tone-mapped to BT.709: on an SDR screen the 'before' is the washed-out one.",
     demo_hdr_tonemap, "video", None),
    ("reframe_crop", PICTURE, "16:9 to 9:16 by cropping",
     "The vertical frame is cut out of the centre of the wide one -- full height, sides lost.",
     demo_reframe_crop, "video", None),
    ("reframe_pad", PICTURE, "16:9 to 9:16 by padding",
     "Nothing is lost: the wide frame is kept whole and the gap above and below is filled with a blurred copy.",
     demo_reframe_pad, "video", None),
    ("speed_up", PICTURE, "Speed change to hit a duration",
     "An 8 s clip retimed to land exactly on 4 s; audio is pitch-corrected rather than chipmunked.",
     demo_speed_up, "video", None),
    ("reverse", PICTURE, "Reverse",
     "The life pattern runs backwards -- cells un-die; the audio is reversed with it.",
     demo_reverse, "video", None),
    ("join_fade", PICTURE, "Join with a cross fade",
     "Two clips of different content become one; watch the 0.8 s dissolve in the middle.",
     demo_join_fade, "video", None),
    ("join_fadeblack", PICTURE, "Join through black",
     "The same join with fadeblack: the cut dips to black instead of blending the two pictures.",
     demo_join_fadeblack, "video", None),

    ("silence_removal", AUDIO, "Silence removal",
     "The 'after' side runs out of material and freezes: that held frame is the part of the timeline that was cut.",
     demo_silence_removal, "video", None),
    ("loudness", AUDIO, "Loudness normalisation to -14 LUFS",
     "Two showwavespic plots: the quiet input on the left, the same programme brought up to broadcast level on the right without clipping.",
     demo_loudness, "wave", None),
    ("downmix_51", AUDIO, "5.1 to stereo downmix",
     "Six discrete tones folded into two channels at the standard coefficients -- the centre and LFE are still audible.",
     demo_downmix_51, "wave", None),
    ("bgm_ducking", AUDIO, "Music bed with ducking",
     "The bed drops by 12 dB whenever the speech-like track is active and comes back up in the pauses.",
     demo_bgm_ducking, "wave", None),

    ("export_reels", DELIVERY, "Reels export, then checked",
     "One command produces the 1080x1920 deliverable; check.py then reports the spec row by row and exits non-zero on a FAIL.",
     demo_export_reels, "video", None),

    ("render_project", PROJECTS, "Whole edit from one project file",
     "Clips, a transition, captions and a title card described as JSON and rendered in one pass.",
     demo_render_project, "video", "latin"),
    ("contact_sheet", PROJECTS, "Contact sheet",
     "Twelve timecoded frames in one PNG: the fastest way to confirm an edit landed where it should.",
     demo_contact_sheet, "video", None),
]

GROUP_ORDER = [CAPTIONS, PICTURE, AUDIO, DELIVERY, PROJECTS]
BY_NAME = {d[0]: d for d in DEMOS}


# --------------------------------------------------------------------------- docs
DOC_HEADER = """# Demo gallery

Every clip on this page was generated from nothing: ffmpeg's own synthetic sources make the
footage, and each "after" is produced by running one of this repo's scripts on it. Rebuild the
whole page's material with:

```bash
python3 demos/build.py            # or: npm run demo
python3 demos/build.py --list     # what gets built
python3 demos/build.py --only captions_ja
```

The full-resolution `<name>_before.mp4`, `<name>_after.mp4` and side-by-side `<name>.mp4` land
in `demos/out/` (gitignored). Only the small previews below are committed, and the build fails
if any of them exceeds 500 KB.

In every preview the left half is the input and the right half is what the command produced.
"""


def write_docs(path=ROOT / "docs" / "demos.md"):
    """Generate the gallery page from the same table the builder runs, so the command printed
    under a preview cannot drift from the command that made it."""
    lines = [DOC_HEADER]
    for group in GROUP_ORDER:
        lines.append("\n## %s\n" % group)
        for name, grp, title, look, builder, _kind, _script in DEMOS:
            if grp != group:
                continue
            lines.append("### %s\n" % title)
            lines.append("![%s](demos/%s.gif)\n" % (title, name))
            lines.append("```bash\n%s\n```\n" % "\n".join(_commands_for(name)))
            lines.append("**Look for:** %s\n" % look)
    lines.append("\n---\n")
    lines.append("Missing a feature you use? A `feat` PR is expected to add a demo here and in "
                 "`demos/build.py` -- see [CONTRIBUTING.md](../CONTRIBUTING.md).\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class _DryCtx(Ctx):
    """Records what a builder would run without running any of it."""

    def script(self, tool, *args, capture=False):
        self.commands.append(" ".join(["python3", "scripts/" + tool] + [_short(a) for a in args]))
        return ""


def _commands_for(name):
    """Replay a demo's builder against a recorder, so the docs print the exact command the
    build runs rather than a hand-copied approximation of it."""
    ctx = _DryCtx(name, verbose=False)
    global ffmpeg, duration
    real_ffmpeg, real_duration = ffmpeg, duration
    ffmpeg, duration = (lambda *a: None), (lambda p: 0.0)
    try:
        BY_NAME[name][4](ctx)
    except Exception:  # a builder that inspects its own output stops early; its commands stand
        pass
    finally:
        ffmpeg, duration = real_ffmpeg, real_duration
    return ctx.commands or ["python3 scripts/%s.py ..." % name]


# --------------------------------------------------------------------------- driver
def build_demo(name, font, verbose=True):
    _, group, title, _look, builder, kind, need_script = BY_NAME[name]
    if need_script and need_script != "latin" and script_font_status(need_script) == "missing":
        return {"name": name, "status": "skipped",
                "reason": "no font on this machine covers script %r" % need_script}
    print("==> %s (%s)" % (name, group))
    ctx = Ctx(name, verbose=verbose)
    started = time.time()
    before, after = builder(ctx)

    # Normalise the "before" side into demos/out/ so a demo's three files sit together.
    before_copy = OUT / ("%s_before.mp4" % name)
    if Path(before).resolve() != before_copy.resolve():
        shutil.copyfile(str(before), str(before_copy))

    compare = OUT / ("%s.mp4" % name)
    if kind == "wave":
        make_wave_compare(before_copy, after, compare, font)
    else:
        make_compare(before_copy, after, compare, font)

    PREVIEWS.mkdir(parents=True, exist_ok=True)
    size, fps, width, colors = make_preview(compare, PREVIEWS / ("%s.gif" % name))
    return {"name": name, "status": "ok", "title": title, "group": group,
            "bytes": size, "fps": fps, "width": width, "colors": colors,
            "seconds": round(time.time() - started, 1), "commands": ctx.commands,
            "notes": ctx.notes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--only", action="append", metavar="NAME",
                    help="build just this demo (repeatable); --list shows the names")
    ap.add_argument("--list", action="store_true", help="list the demos and exit")
    ap.add_argument("--docs", action="store_true",
                    help="rewrite docs/demos.md from the table and exit, rendering nothing")
    ap.add_argument("--force-fixtures", action="store_true",
                    help="regenerate the synthetic source material even if it is already there")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)

    if args.list:
        for name, group, title, _look, _b, _k, _s in DEMOS:
            print("%-22s %-20s %s" % (name, group, title))
        return 0
    if args.docs:
        print("wrote %s" % write_docs())
        return 0

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print("%s not found on PATH" % tool, file=sys.stderr)
            return 127

    names = args.only or [d[0] for d in DEMOS]
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        print("unknown demo(s): %s (try --list)" % ", ".join(unknown), file=sys.stderr)
        return 2

    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    made = build_fixtures(force=args.force_fixtures)
    if made:
        print("==> fixtures: %s" % ", ".join(made))

    font = label_font()
    results = [build_demo(n, font) for n in names]
    if not args.only:
        write_docs()

    ok = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    total = sum(r["bytes"] for r in ok)
    elapsed = time.time() - started
    if args.json:
        print(json.dumps({"demos": results, "preview_bytes": total,
                          "seconds": round(elapsed, 1)}, indent=2, ensure_ascii=False))
    else:
        print("\n%-24s %8s %s" % ("demo", "preview", "notes"))
        for r in results:
            if r["status"] == "ok":
                print("%-24s %7.1fK  %s" % (r["name"], r["bytes"] / 1024.0, "; ".join(r["notes"])))
            else:
                print("%-24s %8s  %s" % (r["name"], "skip", r["reason"]))
        print("\n%d demos, %d skipped, docs/demos/ total %.1f KB, %.1f s"
              % (len(ok), len(skipped), total / 1024.0, elapsed))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as exc:
        print("demo build failed: %s" % exc, file=sys.stderr)
        sys.exit(1)
