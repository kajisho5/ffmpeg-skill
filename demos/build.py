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
from collections import namedtuple
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

    # 10. A letterboxed clip: real picture in the middle, black bars top and bottom, so
    #     cropdetect.py has something to measure and crop.py something to remove.
    path = need("letterbox.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1280x400:rate=25:maxiter=150", "-t", "4",
               "-vf", "pad=1280:720:0:160:black", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "22", "-pix_fmt", "yuv420p", str(path))

    # 11. A noisy clip: heavy film-grain-like noise added on purpose, so denoise.py has
    #     something real to remove rather than rounding error.
    path = need("noisy.mp4")
    if path:
        ffmpeg("-i", str(FIX / "motion.mp4"), "-t", "4", "-vf", "noise=alls=42:allf=t+u",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(path))

    # 12. An interlaced clip: tinterlace weaves each pair of frames into one, which is exactly
    #     the combing yadif (deinterlace.py) undoes.
    path = need("interlaced.mp4")
    if path:
        ffmpeg("-i", str(FIX / "motion.mp4"), "-t", "4", "-vf",
               "tinterlace=mode=interleave_top,setparams=field_mode=tff",
               "-flags", "+ilme+ildct", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "aac", str(path))

    # 13. A shaky clip: a crop window jittering around a larger frame -- handheld camera shake
    #     with no camera, and the motion vidstab (stabilize.py) is built to cancel.
    path = need("shaky.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1400x800:rate=25:maxiter=150", "-t", "4",
               "-vf", "crop=1280:720:x='60+26*sin(2*PI*3.1*t)+12*sin(2*PI*6.7*t)':"
                      "y='40+18*cos(2*PI*2.3*t)+9*sin(2*PI*5.3*t)'",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
               str(path))

    # 14. A tilted clip: the frame rotated 5 degrees, the "horizon is off" case straighten.py
    #     corrects (the black corner wedges are part of the problem, not the fixture's).
    path = need("tilted.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=25:maxiter=150", "-t", "4",
               "-vf", "rotate=5*PI/180:fillcolor=black", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "22", "-pix_fmt", "yuv420p", str(path))

    # 15. A 2:1 "equirectangular" panorama for sphere.py. Nothing here proves a file is really
    #     spherical (see sphere.py's docstring) -- this is a synthetic panorama shaped like one.
    path = need("equirect.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x640:rate=25", "-t", "4",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
               str(path))

    # 16. A green-screen clip: a moving subject on chroma green, to be keyed onto a background.
    path = need("green.mp4")
    if path:
        ffmpeg("-f", "lavfi", "-i", "color=c=0x00b140:s=960x540:rate=25",
               "-f", "lavfi", "-i", "mandelbrot=size=300x300:rate=25:maxiter=150", "-t", "4",
               "-filter_complex", "[0:v][1:v]overlay=x='330+230*sin(2*PI*0.35*t)':y=120",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
               str(path))

    # 17. A second camera angle of the same "event": the same audio, started 0.6 s earlier and
    #     graded differently, so multicam.py has a real offset to find and a visible B angle.
    path = need("camb.mp4")
    if path:
        ffmpeg("-i", str(FIX / "motion.mp4"), "-t", "6", "-vf",
               "hue=h=150:s=1.4,tpad=start_duration=0.6:start_mode=add:color=black",
               "-af", "adelay=600|600", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-c:a", "aac", str(path))

    # 18. An external mic recording of the same speech: louder, thinner, and started 1 s late.
    path = need("mic.wav")
    if path:
        ffmpeg("-i", str(FIX / "motion.mp4"), "-t", "6", "-vn", "-af",
               "adelay=1000,volume=6dB,highpass=f=220", "-ac", "1", "-ar", "48000",
               "-c:a", "pcm_s16le", str(path))

    # 19. A numbered still sequence, the shape sequence.py expects from a render farm or a
    #     camera's burst mode.
    frames = FIX / "frames"
    if force or not (frames / "frame_0001.png").exists():
        made.append("frames/")
        frames.mkdir(parents=True, exist_ok=True)
        ffmpeg("-i", str(FIX / "life.mp4"), "-vf", "fps=8,scale=640:360:flags=neighbor",
               "-frames:v", "24", "-start_number", "1", str(frames / "frame_%04d.png"))

    # 20. Chapter marks for metadata.py, in its `TIME TITLE` format.
    path = need("chapters.txt")
    if path:
        path.write_text("0:00 Cold open\n0:02 The demo\n0:05 Outro\n", encoding="utf-8")

    # 21. A tiny .cube LUT (a warm-highlight / cool-shadow look). A 2x2x2 cube is the smallest
    #     legal one: eight corners, interpolated in between, which is enough to see a grade.
    path = need("look.cube")
    if path:
        rows = ["# Synthetic demo look, generated by demos/build.py", "LUT_3D_SIZE 2", ""]
        for b in (0.0, 1.0):
            for g in (0.0, 1.0):
                for r in (0.0, 1.0):
                    out = (min(1.0, r * 1.10 + 0.05), min(1.0, g * 0.94 + 0.02),
                           min(1.0, b * 0.80 + 0.10 * (1.0 - r)))
                    rows.append("%.6f %.6f %.6f" % out)
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    # 22. A still frame, for insert.py's Ken Burns card.
    path = need("slate.png")
    if path:
        ffmpeg("-ss", "3", "-i", str(FIX / "mandel.mp4"), "-frames:v", "1",
               "-vf", "scale=960:540", str(path))

    # 23. A clip with hard cuts in it: three unrelated shots butted together, which is what
    #     scenes.py's scdet pass is looking for.
    path = need("shots.mp4")
    if path:
        ffmpeg("-i", str(FIX / "motion.mp4"), "-i", str(FIX / "mandel.mp4"),
               "-i", str(FIX / "life.mp4"), "-filter_complex",
               "[0:v]trim=0:2,setpts=PTS-STARTPTS,scale=960:540[a];"
               "[1:v]trim=0:2,setpts=PTS-STARTPTS,scale=960:540[b];"
               "[2:v]trim=0:2,setpts=PTS-STARTPTS,scale=960:540[c];"
               "[a][b][c]concat=n=3:v=1:a=0[v];"
               "[0:a]atrim=0:6,asetpts=PTS-STARTPTS[aud]",
               "-map", "[v]", "-map", "[aud]", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path))

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


def make_compare(before, after, dest, font, labels=("BEFORE", "AFTER")):
    """640x180 side-by-side, <= 6 s. Both sides are held on their last frame to the same
    length, so silence removal (a genuinely shorter 'after') reads as the timeline shrinking
    rather than as one side simply vanishing.

    `labels` overrides the two captions for a demo where "before/after" is the wrong pair of
    words -- a lossless cut against an accurate one is two settings, not two generations."""
    seconds = min(COMPARE_MAX_SECONDS, max(duration(before), duration(after)) or COMPARE_MAX_SECONDS)
    chain = "%s;%s;[v0][v1]hstack=inputs=2[out]" % (_side(0, labels[0], font, COMPARE_MAX_SECONDS),
                                                    _side(1, labels[1], font, COMPARE_MAX_SECONDS))
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


# --------------------------------------------------------------------------- capabilities
_FILTERS = None


def have_filter(name) -> bool:
    """Is `name` compiled into the ffmpeg on PATH? vidstab (stabilize) and v360 (sphere) are
    optional at build time on several distributions, so a demo that needs one skips with a
    reason rather than failing the whole gallery."""
    global _FILTERS
    if _FILTERS is None:
        try:
            out = run(["ffmpeg", "-hide_banner", "-filters"], capture=True) or ""
        except BuildError:
            out = ""
        _FILTERS = {line.split()[1] for line in out.splitlines()
                    if len(line.split()) > 2 and line.startswith(" ")}
    return name in _FILTERS


def missing_requirement(needs):
    """Why this demo cannot render here, or None. A requirement is either a script name for
    the font check ("ja") or "filter:NAME" for an ffmpeg feature check."""
    for need in ((needs,) if isinstance(needs, str) else tuple(needs or ())):
        if need.startswith("filter:"):
            name = need.split(":", 1)[1]
            if not have_filter(name):
                return "this ffmpeg build has no %s filter" % name
        elif need != "latin" and script_font_status(need) == "missing":
            return "no font on this machine covers script %r" % need
    return None


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


def demo_fit_blur(ctx):
    """16:9 to 9:16 with nothing cropped: the picture sits on a blurred, dimmed copy of itself."""
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("fit.py", before, "--aspect", "9:16", "--fit", "blur", "--width", "540",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_template_tiktok(ctx):
    """One command per destination: the delivery template does the whole chain and checks it."""
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("render.py", before, "--template", "tiktok", "--cues", FIX / "cues_en.txt",
               "--fast", "-o", after)
    if not after.exists():
        raise BuildError("render.py --template tiktok did not write %s" % after)
    ctx.note("1080x1920, captions clear of TikTok's description bar, check.py --platform tiktok passes")
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


def demo_cut_accurate(ctx):
    """Two cuts of the same request: the lossless one snaps to the nearest keyframe, the
    accurate one re-encodes and lands on the asked-for frame."""
    src = FIX / "mandel.mp4"
    before = ctx.path("before.mp4")
    after = ctx.path("after.mp4")
    # --tolerance 5 lets the stream copy keep its keyframe snap instead of quietly re-encoding
    # (cut.py's "hybrid" mode), which is the behaviour this demo exists to show.
    out = ctx.script("cut.py", src, "--start", "2.05", "--duration", "3", "--tolerance", "5",
                     "--json", "-o", before, capture=True)
    ctx.script("cut.py", src, "--start", "2.05", "--duration", "3", "--accurate",
               "--preset", "veryfast", "-o", after)
    if out:
        found = json.loads(out)
        ctx.note("copy: keyframe_snapped=%s, %.2f s of extra material; accurate: 2.05 s exactly"
                 % (found.get("keyframe_snapped"), found.get("duration_delta_seconds", 0.0)))
    return before, after


def demo_crop_rect(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("crop.py", before, "--x", "320", "--y", "120", "--width", "640", "--height", "480",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_cropdetect_crop(ctx):
    """Measure the bars, then remove them: cropdetect.py reports the rectangle and crop.py is
    the tool that acts on it -- two commands, because measuring is not deciding."""
    before = FIX / "letterbox.mp4"
    after = ctx.path("after.mp4")
    out = ctx.script("cropdetect.py", before, "--seconds", "4", "--json", capture=True)
    rect = {"x": 0, "y": 160, "width": 1280, "height": 400}
    if out:
        found = json.loads(out)
        rect = {k: found.get(k, rect[k]) for k in rect}
        ctx.note("detected x=%(x)s y=%(y)s %(width)sx%(height)s" % rect)
    ctx.script("crop.py", before, "--x", rect["x"], "--y", rect["y"], "--width", rect["width"],
               "--height", rect["height"], "--preset", "veryfast", "-o", after)
    return before, after


def demo_pad_timeline(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("pad.py", before, "--start", "1", "--end", "1", "--color", "0x101014",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_freeze_hold(ctx):
    """A title over the picture, then the frame under it held: the card has time to be read."""
    before = FIX / "mandel.mp4"
    titled = ctx.path("titled.mp4")
    after = ctx.path("after.mp4")
    ctx.script("graphics.py", before, "--template", "title", "--title", "Hold this frame",
               "--subtitle", "freeze.py --at 2 --hold 1.5", "--start", "1.6", "--end", "4",
               "-o", titled)
    ctx.script("freeze.py", titled, "--at", "2", "--hold", "1.5", "--preset", "veryfast",
               "-o", after)
    return before, after


def demo_loop_times(ctx):
    before = ctx.path("before.mp4")
    after = ctx.path("after.mp4")
    ctx.script("cut.py", FIX / "life.mp4", "--start", "0", "--duration", "1.5", "--accurate",
               "--preset", "veryfast", "-o", before)
    ctx.script("loop.py", before, "--times", "4", "--preset", "veryfast", "-o", after)
    ctx.note("%.1f s in, %.1f s out" % (duration(before), duration(after)))
    return before, after


def demo_insert_still(ctx):
    """A still becomes a timed clip with a Ken Burns move, then lands in the middle of the
    timeline: insert.py makes the card, join.py puts it between the two shots."""
    before = FIX / "motion.mp4"
    card = ctx.path("card.mp4")
    after = ctx.path("after.mp4")
    ctx.script("insert.py", FIX / "slate.png", "--duration", "2", "--width", "960",
               "--height", "540", "--fps", "25", "--zoom", "in", "--pan", "right",
               "--preset", "veryfast", "-o", card)
    ctx.script("join.py", FIX / "motion.mp4", card, FIX / "mandel.mp4", "--transition", "fade",
               "--duration", "0.5", "--width", "960", "--height", "540", "--fps", "25",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_sequence_frames(ctx):
    """A folder of numbered PNGs becomes a clip. The 'before' side is the first frame held,
    because that is all a still sequence is until something assembles it."""
    first = FIX / "frames" / "frame_0001.png"
    before = ctx.path("before.mp4")
    ffmpeg("-loop", "1", "-t", "3", "-i", str(first), "-vf", "scale=640:360,format=yuv420p",
           "-r", "10", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", str(before))
    after = ctx.path("after.mp4")
    ctx.script("sequence.py", "--dir", FIX / "frames", "--pattern", "frame_%04d.png",
               "--start-number", "1", "--fps", "8", "--preset", "veryfast", "-o", after)
    return before, after


def demo_speedramp(ctx):
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("speedramp.py", before, "--segment", "0-2:2.0", "--segment", "2-3:0.35",
               "--segment", "3-6:1.5", "--preset", "veryfast", "-o", after)
    return before, after


def demo_denoise(ctx):
    before = FIX / "noisy.mp4"
    after = ctx.path("after.mp4")
    ctx.script("denoise.py", before, "--strength", "high", "--preset", "veryfast", "-o", after)
    return before, after


def demo_deinterlace(ctx):
    before = FIX / "interlaced.mp4"
    after = ctx.path("after.mp4")
    ctx.script("deinterlace.py", before, "--mode", "frame", "--parity", "tff",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_stabilize(ctx):
    before = FIX / "shaky.mp4"
    after = ctx.path("after.mp4")
    ctx.script("stabilize.py", before, "--shakiness", "8", "--smoothing", "20", "--zoom", "5",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_straighten(ctx):
    before = FIX / "tilted.mp4"
    after = ctx.path("after.mp4")
    ctx.script("straighten.py", before, "--degrees", "-5", "--fit", "crop",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_redact_blur(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("redact.py", before, "--x", "420", "--y", "180", "--width", "440",
               "--height", "360", "--mode", "blur", "--blur-strength", "24",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_sphere_flat(ctx):
    before = FIX / "equirect.mp4"
    after = ctx.path("after.mp4")
    ctx.script("sphere.py", before, "--input-projection", "equirect", "--yaw", "40",
               "--pitch", "-10", "--h-fov", "100", "--v-fov", "70", "--width", "960",
               "--height", "540", "--preset", "veryfast", "-o", after)
    return before, after


def demo_greenscreen(ctx):
    """Two tools: background.py generates the plate (no input file at all), overlay.py keys the
    green out of the subject and composites it on top."""
    before = FIX / "green.mp4"
    plate = ctx.path("plate.mp4")
    after = ctx.path("after.mp4")
    ctx.script("background.py", "--duration", "4", "--width", "960", "--height", "540",
               "--gradient", "0xff6a00:0x0057ff", "--angle", "45", "--fps", "25",
               "--preset", "veryfast", "-o", plate)
    ctx.script("overlay.py", plate, "--video", before, "--chromakey", "0x00b140",
               "--chromakey-similarity", "0.18", "--chromakey-blend", "0.05",
               "--position", "center", "--scale", "960", "--preset", "veryfast", "-o", after)
    return before, after


def demo_color_lut(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("color.py", before, "--lut", FIX / "look.cube", "--lut-strength", "1.0",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_color_correct(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("color.py", before, "--correct", "--exposure", "0.25", "--contrast", "1.25",
               "--saturation", "1.3", "--temperature", "7000", "--gamma", "1.1",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_grid_2x2(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("grid.py", FIX / "motion.mp4", FIX / "mandel.mp4", FIX / "life.mp4",
               FIX / "camb.mp4", "--cols", "2", "--rows", "2", "--cell-width", "480",
               "--cell-height", "270", "--fps", "25", "--audio-from", "0", "--gap", "4",
               "--preset", "veryfast", "-o", after)
    return before, after


def demo_multicam_switch(ctx):
    """Two angles of one event, aligned by their shared audio and then cut between on a list of
    ranges -- the cut list is the caller's, the alignment is measured."""
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("multicam.py", FIX / "motion.mp4", FIX / "camb.mp4",
               "--switch", "0-2:0,2-4:1,4-6:0", "--width", "960", "--height", "540",
               "--fps", "25", "--preset", "veryfast", "-o", after)
    return before, after


def demo_broll_cutaway(ctx):
    before = FIX / "motion.mp4"
    after = ctx.path("after.mp4")
    ctx.script("broll.py", before, "--insert", FIX / "mandel.mp4", "--at", "2",
               "--duration", "3", "--audio", "a", "--preset", "veryfast", "-o", after)
    return before, after


def demo_sync_mic(ctx):
    """The external mic started 1 s late. sync.py measures the offset by cross-correlating
    the two envelopes and writes the camera clip with the aligned mic as its audio."""
    before = FIX / "mic.wav"
    after = ctx.path("after.mp4")
    out = ctx.script("sync.py", FIX / "motion.mp4", before, "--replace-audio", "--json",
                     "-o", after, capture=True)
    if out:
        try:
            found = json.loads(out)
            ctx.note("offset %.3f s, confidence %.2f"
                     % (found.get("offset_seconds", 0.0), found.get("confidence", 0.0)))
        except ValueError:
            pass
    return before, after


def demo_waveform_render(ctx):
    """An audio-only file has nothing to show; waveform.py gives it a picture that moves with
    the sound it carries."""
    before = ctx.path("before.mp4")
    ffmpeg("-f", "lavfi", "-i", "color=c=0x101014:s=640x360:rate=10", "-i", str(FIX / "music.m4a"),
           "-shortest", "-t", "5", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
           "-pix_fmt", "yuv420p", "-c:a", "aac", str(before))
    after = ctx.path("after.mp4")
    ctx.script("waveform.py", FIX / "music.m4a", "--style", "waveform", "--width", "960",
               "--height", "540", "--color", "0x39ff88", "--background", "0x101014",
               "--waveform-mode", "cline", "--preset", "veryfast", "-o", after)
    return before, after


def demo_proxy(ctx):
    """Both sides are shown at the same size, which is the only honest way to compare a proxy
    with its master: the proxy is smaller on disk, not on screen."""
    before = FIX / "mandel.mp4"
    after = ctx.path("after.mp4")
    ctx.script("proxy.py", before, "--width", "320", "--crf", "34", "--fps", "12", "-o", after)
    ctx.note("%.1f MB master, %.2f MB proxy"
             % (before.stat().st_size / 1e6, after.stat().st_size / 1e6 if after.exists() else 0))
    return before, after


def demo_scenes_highlights(ctx):
    """scenes.py finds the cuts and proposes ranges; cut.py --segments is what turns that list
    into a reel. The proposal is a measurement, the edit is still a command someone ran."""
    before = FIX / "shots.mp4"
    edl = ctx.path("picks.txt")
    after = ctx.path("after.mp4")
    ctx.script("scenes.py", before, "--highlights", "2", "--min-scene", "1", "--edl", edl)
    segments = "0.00-1.50,4.00-5.50"
    if edl.exists():
        picked = [line.strip() for line in edl.read_text(encoding="utf-8").split() if line.strip()]
        if picked:
            segments = ",".join(picked)
            ctx.note("%d highlight ranges: %s" % (len(picked), segments))
    ctx.script("cut.py", before, "--segments", segments, "--accurate", "--preset", "veryfast",
               "-o", after)
    return before, after


def demo_metadata_chapters(ctx):
    """Chapters are container metadata, not pixels: nothing about the picture changes. The
    'after' side is the chapter list read back out of the file and drawn as a timeline strip,
    which is what a player's chapter bar shows."""
    before = FIX / "mandel.mp4"
    tagged = ctx.path("tagged.mp4")
    ctx.script("metadata.py", before, "--chapters", FIX / "chapters.txt",
               "--title", "Demo episode", "-o", tagged)
    marks = []
    if tagged.exists():
        raw = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters",
                   str(tagged)], capture=True)
        total = duration(tagged) or 6.0
        for chapter in json.loads(raw).get("chapters", []):
            start = float(chapter["start_time"])
            marks.append((start / total, "%d:%02d %s" % (int(start) // 60, int(start) % 60,
                                                         chapter.get("tags", {}).get("title", "?"))))
        ctx.note("%d chapters written, streams copied" % len(marks))
    strip = ctx.path("strip.png")
    font = label_font()
    draws = ["drawbox=x=0:y=70:w=960:h=8:color=0x39ff88@0.7:t=fill"]
    for idx, (frac, title) in enumerate(marks or [(0.0, "Chapter")]):
        x = int(frac * 940)
        draws.append("drawbox=x=%d:y=56:w=4:h=36:color=white:t=fill" % x)
        draws.append("drawtext=fontfile='%s':text='%s':fontsize=20:fontcolor=white:"
                     "x=%d:y=%d" % (esc(font), title.replace(":", "\\:"), min(x + 10, 700),
                                    100 if idx % 2 else 20))
    ffmpeg("-f", "lavfi", "-i", "color=c=0x101014:s=960x160", "-frames:v", "1",
           "-vf", ",".join(draws), str(strip))
    after = ctx.path("after.mp4")
    ffmpeg("-loop", "1", "-t", "3", "-i", str(strip), "-vf",
           "pad=960:540:0:190:0x101014,format=yuv420p", "-r", "10", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "24", str(after))
    return before, after


CAPTIONS, PICTURE, AUDIO, DELIVERY, PROJECTS = (
    "Captions & text", "Picture", "Audio", "Delivery & checks", "Projects & inspection")

# One demo. `kind` is "video" (side-by-side clips) or "wave" (two showwavespic plots, for work
# only the ears can hear). `needs` is what this machine must have for the demo to render at all:
# a script name for the font check ("ja") or "filter:NAME" for an optional ffmpeg filter --
# either may also be a tuple. `labels` overrides the two captions burnt into the comparison.
Demo = namedtuple("Demo", "name group title look builder kind needs labels",
                  defaults=(None, ("BEFORE", "AFTER")))

_ROWS = [
    # name, group, title, what to look for, builder, comparison kind, requirements[, labels]
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

    ("fit_blur", PICTURE, "16:9 to 9:16 on a blurred background",
     "Nothing is cropped and there are no black bars: the whole wide frame sits centred on a blurred, dimmed copy of itself.",
     demo_fit_blur, "video", None),

    ("template_tiktok", DELIVERY, "TikTok delivery template",
     "One command turns the master into the 1080x1920 deliverable: reframe, burned-in captions kept clear of TikTok's own UI, loudness to -14 LUFS, the tiktok export preset and check.py's platform rows.",
     demo_template_tiktok, "video", "latin"),

    ("render_project", PROJECTS, "Whole edit from one project file",
     "Clips, a transition, captions and a title card described as JSON and rendered in one pass.",
     demo_render_project, "video", "latin"),
    ("contact_sheet", PROJECTS, "Contact sheet",
     "Twelve timecoded frames in one PNG: the fastest way to confirm an edit landed where it should.",
     demo_contact_sheet, "video", None),

    ("cut_accurate", PICTURE, "Lossless cut vs. accurate cut",
     "Both sides asked for the same 2.05 s start. The stream copy could only snap to the nearest keyframe, so its first frame is from earlier in the clip; --accurate re-encodes and starts on the frame that was asked for.",
     demo_cut_accurate, "video", None, ("LOSSLESS", "--ACCURATE")),
    ("crop_rect", PICTURE, "Crop to an exact rectangle",
     "A literal 640x480 window at x=320, y=120 in the source frame -- no aspect maths, no auto-centring; the rectangle is the caller's and is refused rather than rounded if it does not fit.",
     demo_crop_rect, "video", None),
    ("cropdetect_crop", PICTURE, "Detect letterbox bars, then remove them",
     "cropdetect.py measures the bars and prints the rectangle; crop.py is what actually cuts them off. Measuring and deciding stay two commands.",
     demo_cropdetect_crop, "video", None),
    ("pad_timeline", PICTURE, "Pad the timeline with black",
     "A second of black and silence before and after the clip -- the TIMELINE grows, the frame does not (that is fit.py --fit pad).",
     demo_pad_timeline, "video", None),
    ("freeze_hold", PICTURE, "Freeze frame under a title",
     "The clip stops dead at 2 s for a beat and a half while the title card sits over it, then carries on -- everything after the freeze is pushed later, nothing is lost.",
     demo_freeze_hold, "video", "latin"),
    ("loop_times", PICTURE, "Loop a short clip",
     "A 1.5 s clip repeated four times back to back. The seam is not smoothed: a clip that does not already loop cleanly shows its cut, which is a judgement about the material, not a flag.",
     demo_loop_times, "video", None),
    ("insert_still", PICTURE, "A still card dropped into the timeline",
     "insert.py turns one PNG into a 2 s clip with a slow zoom and pan, and join.py cross-fades it in between the two shots.",
     demo_insert_still, "video", None),
    ("sequence_frames", PICTURE, "Numbered stills into a clip",
     "Twenty-four PNGs named frame_0001.png onwards become one 8 fps clip; the frame list is resolved and checked on disk before ffmpeg is asked to read it.",
     demo_sequence_frames, "video", None, ("FIRST FRAME", "SEQUENCE")),
    ("speedramp", PICTURE, "Speed ramp",
     "Three constant-speed segments in one pass: 2x, then a 0.35x slam for the beat, then 1.5x out. Audio is pitch-corrected through all three.",
     demo_speedramp, "video", None),
    ("denoise", PICTURE, "Denoise",
     "hqdn3d at --strength high takes the grain out; look closely and the fine detail softens with it, which is the trade the flag is making.",
     demo_denoise, "video", None),
    ("deinterlace", PICTURE, "Deinterlace",
     "The combing on moving edges -- alternate lines from two different moments -- is woven back into whole progressive frames by yadif.",
     demo_deinterlace, "video", None),
    ("stabilize", PICTURE, "Stabilize shaky footage",
     "vidstab's two passes cancel the handheld jitter and crop in 5% to hide the edges that smoothing exposes; the frame stops wandering.",
     demo_stabilize, "video", ("filter:vidstabdetect", "filter:vidstabtransform")),
    ("straighten", PICTURE, "Straighten a tilted horizon",
     "A 5 degree tilt taken back out. --fit crop scales up just enough that the rotated corners leave no gap, costing a thin border of picture.",
     demo_straighten, "video", None),
    ("redact_blur", PICTURE, "Redact a rectangle",
     "One region blurred for the whole clip and the rest of the frame untouched. The rectangle has to be given: this tool finds no faces and no plates.",
     demo_redact_blur, "video", None),
    ("sphere_flat", PICTURE, "360 panorama to a flat view",
     "v360 maps the 2:1 equirectangular source onto a rectilinear camera pointed 40 degrees right and 10 degrees down -- the same viewport a headset would show, baked into a file.",
     demo_sphere_flat, "video", "filter:v360"),
    ("greenscreen", PICTURE, "Green screen onto a generated background",
     "background.py draws the gradient plate from nothing (there is no input file), then overlay.py keys the chroma green out of the subject and composites it on top.",
     demo_greenscreen, "video", None),
    ("color_lut", PICTURE, "Apply a .cube LUT",
     "A 3D LUT applied at full strength: highlights warm, shadows cool. The same flag takes a camera vendor's Log-to-709 transform or a creative look -- the file decides, the tool does not.",
     demo_color_lut, "video", None),
    ("color_correct", PICTURE, "Primary colour correction",
     "Typed values, not a look: exposure +0.25, contrast 1.25, saturation 1.3, white balance to 7000 K, gamma 1.1 -- each one a number the caller chose.",
     demo_color_correct, "video", None),
    ("grid_2x2", PICTURE, "2x2 comparison grid",
     "Four clips of different content in one frame, each letterboxed into its cell rather than stretched, with the source name burnt into the corner and only input 0's audio carried through.",
     demo_grid_2x2, "video", "latin"),
    ("broll_cutaway", PICTURE, "B-roll cutaway",
     "From 2 s to 5 s the picture cuts away to the insert while the interview audio keeps running underneath, then comes back at its own time -- the output is exactly as long as the A-roll.",
     demo_broll_cutaway, "video", None),
    ("multicam_switch", PICTURE, "Two cameras, one cut list",
     "Camera B's audio is the same event 0.6 s offset; multicam.py measures that by cross-correlation, aligns both, then cuts between them on the ranges it was given.",
     demo_multicam_switch, "video", None),

    ("sync_mic", AUDIO, "External mic aligned to the camera",
     "The mic was started after the camera, so its envelope begins late in its own file; after the sync the same speech sits where the camera's does. Left is the mic as recorded, right is the track that ends up on the picture -- the measured offset and its confidence are printed by the command.",
     demo_sync_mic, "wave", None, ("MIC AS RECORDED", "ALIGNED")),
    ("waveform_render", AUDIO, "Audio rendered as a waveform video",
     "An audio-only file has nothing to show; showwaves draws the amplitude as it plays, and the rendered clip carries the same audio it is drawing.",
     demo_waveform_render, "video", None, ("AUDIO ONLY", "WAVEFORM")),

    ("proxy", DELIVERY, "Proxy vs. master, shown at the same size",
     "Both halves are scaled to the same cell, which is the honest comparison: the proxy is smaller on disk and cheaper to decode, not smaller on screen. The softness is the point of it.",
     demo_proxy, "video", None, ("MASTER", "PROXY")),

    ("scenes_highlights", PROJECTS, "Scene detection into a highlight reel",
     "scdet finds the hard cuts, scenes.py ranks the scenes and writes the ranges as an EDL, and cut.py --segments is what turns that proposal into a reel. The ranking is a proxy for interest, not a judgement of it.",
     demo_scenes_highlights, "video", None),
    ("metadata_chapters", PROJECTS, "Chapter marks written into the container",
     "Nothing in the picture changes -- every stream is copied bit for bit. The right half is the chapter list read back out of the file with ffprobe and drawn as the timeline strip a player would show.",
     demo_metadata_chapters, "video", "latin", ("NO CHAPTERS", "CHAPTER MARKS")),
]

DEMOS = [Demo(*row) for row in _ROWS]
GROUP_ORDER = [CAPTIONS, PICTURE, AUDIO, DELIVERY, PROJECTS]
BY_NAME = {d.name: d for d in DEMOS}

# Tools whose whole output is a table, a JSON document or an HTML file: there is no before/after
# picture to render, so they are listed in the gallery's Inspection section with the command
# instead. tests/test_all.py reads this list -- every other script under scripts/ must appear in
# at least one demo's command, so a tool cannot quietly arrive with nothing to look at.
INSPECTION = [
    ("probe.py", "python3 scripts/probe.py demos/out/render_project_after.mp4 --compact",
     "duration, fps and VFR suspicion, frame size, codecs, pixel format and colour tags, audio "
     "channels and sample rate -- one JSON document, or one line per file with --compact."),
    ("verify.py", "python3 scripts/verify.py ~/Footage --quick --report verify.md",
     "runs the whole toolchain over your own files and prints a PASS/FAIL table, one row per "
     "tool per file. Synthetic fixtures cannot show what a real phone container does; this can."),
    ("batch.py", "python3 scripts/batch.py ~/Footage --recipe batch.json --dry-run",
     "applies one recipe to a folder with a content-hash cache, printing what it would run, "
     "what it skipped as unchanged, and where each output lands."),
    ("report.py", "python3 scripts/report.py --before raw.mov --after final.mp4 -o report.html",
     "a single self-contained HTML page: before/after contact sheets, loudness, the platform "
     "check table and the exact commands. It is a file to open, not a picture to embed here."),
]


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

In every preview the left half is the input and the right half is what the command produced --
except where the burnt-in labels say otherwise, for a demo comparing two settings (a lossless
cut against an accurate one) rather than a before against an after.

The tools at the bottom, under **Inspection**, have no picture: they answer a question instead
of changing one, so the command is the demo.
"""


INSPECTION_HEADER = """These tools answer a question instead of changing a picture, so there is
nothing to put a before and an after next to. Each one prints a table, a JSON document or writes
an HTML file; the command is the demo.
"""


def write_docs(path=ROOT / "docs" / "demos.md"):
    """Generate the gallery page from the same table the builder runs, so the command printed
    under a preview cannot drift from the command that made it."""
    lines = [DOC_HEADER]
    for group in GROUP_ORDER:
        lines.append("\n## %s\n" % group)
        for demo in DEMOS:
            if demo.group != group:
                continue
            lines.append("### %s\n" % demo.title)
            lines.append("![%s](demos/%s.gif)\n" % (demo.title, demo.name))
            lines.append("```bash\n%s\n```\n" % "\n".join(_commands_for(demo.name)))
            lines.append("**Look for:** %s\n" % demo.look)
    lines.append("\n## Inspection\n")
    lines.append(INSPECTION_HEADER)
    for tool, command, what in INSPECTION:
        lines.append("### %s\n" % tool)
        lines.append("```bash\n%s\n```\n" % command)
        lines.append("**No picture:** %s\n" % what)
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
        BY_NAME[name].builder(ctx)
    except Exception:  # a builder that inspects its own output stops early; its commands stand
        pass
    finally:
        ffmpeg, duration = real_ffmpeg, real_duration
    return ctx.commands or ["python3 scripts/%s.py ..." % name]


# --------------------------------------------------------------------------- driver
def build_demo(name, font, verbose=True):
    demo = BY_NAME[name]
    group, title, builder, kind = demo.group, demo.title, demo.builder, demo.kind
    reason = missing_requirement(demo.needs)
    if reason:
        return {"name": name, "status": "skipped", "reason": reason}
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
        make_wave_compare(before_copy, after, compare, font, demo.labels)
    else:
        make_compare(before_copy, after, compare, font, demo.labels)

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
        for demo in DEMOS:
            print("%-22s %-20s %s" % (demo.name, demo.group, demo.title))
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
