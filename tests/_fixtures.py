#!/usr/bin/env python3
"""Fixtures and helpers shared by the end-to-end test modules.

The synthetic footage every tool is run against -- 12 s of testsrc2 + tones, a VFR clip, a rotated
phone clip, 5.1 audio, 10-bit HDR10 HEVC, a drifting pair -- is expensive to build and identical
for every group, so MediaFixtures builds it once per process and hands the same paths to each
group's class. Import this module, not one of the test modules, from a new test file.
"""
import json
import platform
import re
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("OUT", ROOT / "tests" / "out"))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
from _common import escape_filter_path  # noqa: E402

TONES = ("0.6*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.3)+0.4*sin(2*PI*880*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"
         "+0.3*sin(2*PI*220*t)*gt(sin(2*PI*0.21*t+2)\\,0.7)")


def sh(*cmd, expect_fail=False, env=None):
    proc = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
    if expect_fail:
        assert proc.returncode != 0, f"expected failure but succeeded: {cmd}"
        return proc
    assert proc.returncode == 0, f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc


def png_size(path) -> tuple:
    with open(path, "rb") as fh:
        head = fh.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _is_faststart(path) -> bool:
    """moov before mdat. Reads the whole file rather than a leading slice: bytes.find() on a
    short read returns -1 for an atom that is actually further in, which compares as "before"
    every other offset and reports a false faststart -- issue #275 called this out explicitly
    after hitting it while confirming the bug. Shared by every test module that writes an mp4
    through a stream-copy path (#277's faststart regression tests)."""
    data = Path(path).read_bytes()
    moov, mdat = data.find(b"moov"), data.find(b"mdat")
    return moov != -1 and mdat != -1 and moov < mdat


def script(name, *args, **kw):
    # Every media test shares one OUT directory and many reuse a name (cap_mux.mp4 is written by
    # three tests), so since 2.0 refuses an existing output the helper gives the consent. What the
    # refusal itself does is pinned by test_contract.py's own helper, which never adds the flag.
    # render.py and batch.py name their outputs in the project / recipe file, not with -o.
    names_output = "-o" in args or "--output" in args or name in ("render.py", "batch.py")
    if names_output and "--overwrite" not in args and "--help" not in args:
        args = args + ("--overwrite",)
    return sh(sys.executable, SCRIPTS / name, *args, **kw)

# ---------------------------------------------------------------------------- fonts by script (1.12)


def _no_fontconfig():
    """fc-list absent (a bare container, Windows) -- the script->font resolution cannot be
    exercised, and skipping says so rather than failing on an environment gap."""
    return shutil.which("fc-list") is None and platform.system() != "Windows"

# ---------------------------------------------------------------------------- emoji + shaping (1.15)


def _emoji_assets(names=("1f389", "1f44d", "1f1ef-1f1f5", "1f469-200d-1f4bb")):
    """A directory of placeholder emoji PNGs drawn by ffmpeg at run time.

    The package ships no emoji art on purpose: Twemoji is CC-BY 4.0 and Noto Emoji OFL/Apache-2.0,
    and a test does not need to redistribute either. What --emoji-assets actually requires is the
    NAMING (lowercase hex code points joined by '-'), which a coloured square proves exactly as
    well as a real glyph.
    """
    d = OUT / "emoji_assets"
    d.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        path = d / (name + ".png")
        if not path.exists():
            colour = ("orange", "gold", "tomato", "limegreen")[i % 4]
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=c=%s:s=72x72:d=0.04" % colour, "-vf", "format=rgba",
               "-frames:v", "1", str(path))
    return d


def _pixel_at(video, t, x, y):
    """The RGB triple at (x, y) of the frame at `t` seconds of `video`."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    w = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width", "-of", "csv=p=0", str(video)],
                           stdout=subprocess.PIPE, text=True).stdout.strip())
    off = (y * w + x) * 3
    return tuple(proc.stdout[off:off + 3])


def _ass_ink_columns(ass_path, w, h, threshold=60):
    """The set of x columns that carry ink when `ass_path` is rendered over black at w x h."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=%dx%d:d=0.04" % (w, h),
         "-vf", "ass=%s" % escape_filter_path(str(ass_path)), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    data = proc.stdout
    if len(data) < w * h:
        return set()
    return {x for x in range(w) if any(data[y * w + x] > threshold for y in range(h))}


def _ass_ink_rows(ass_path, w, h, threshold=60, gap=8, at=1.0):
    """Bands of y rows that carry ink when `ass_path` is rendered over black at w x h.

    One band per drawn text line (a blank row taller than `gap` separates two lines), so a caption
    that libass wrapped onto two lines is visible as two bands without measuring any font.
    """
    # `at` matters: --animate fade/pop start at zero alpha, so the frame at t=0 is blank.
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=%dx%d:d=%.2f" % (w, h, at + 0.5),
         "-ss", "%.2f" % at, "-vf", "ass=%s" % escape_filter_path(str(ass_path)), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    data = proc.stdout
    if len(data) < w * h:
        return []
    lit = [y for y in range(h) if sum(1 for v in data[y * w:(y + 1) * w] if v > threshold) > 2]
    bands = []
    for y in lit:
        if bands and y - bands[-1][1] <= gap:
            bands[-1][1] = y
        else:
            bands.append([y, y])
    return [tuple(b) for b in bands]


def _family_installed(family):
    if not shutil.which("fc-list"):
        return False
    proc = subprocess.run(["fc-list", ":family=%s" % family, "file"], stdout=subprocess.PIPE, text=True)
    return bool(proc.stdout.strip())


def _ass_advance(family, body):
    """x of the rightmost lit pixel of a left-anchored one-line ASS render, or None."""
    W, H, FS = 900, 140, 60
    path = OUT / "advance.ass"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, "
        "Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: D,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:05.00,D,,0,0,0,,{\\pos(0,0)}%s\n" % (W, H, family, FS, body),
        encoding="utf-8-sig")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=%dx%d:d=0.04" % (W, H),
         "-vf", "ass=%s" % str(path).replace("\\", "/"), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = proc.stdout
    if proc.returncode != 0 or len(data) < W * H:
        return None
    for x in range(W - 1, -1, -1):
        if any(data[y * W + x] > 60 for y in range(H)):
            return x
    return None


def _frame_ink(path):
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ss", "1", "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    return sum(proc.stdout)


def _families_for(script):
    """Families fontconfig lists for `script`, or [] where there is no fontconfig to ask (Windows
    resolves fonts by file name, so font_for_script() answers there without an fc-list on PATH --
    shelling out unconditionally raised FileNotFoundError in CI)."""
    from _common import FC_LANG
    if not shutil.which("fc-list"):
        return []
    proc = subprocess.run(["fc-list", f":lang={FC_LANG[script]}", "family"], stdout=subprocess.PIPE, text=True)
    return [f for line in proc.stdout.splitlines() for f in line.split(",")]
# One build per process, not one per group: setUpClass runs for each of the six group classes and
# the footage below takes the best part of a minute to encode. The first class through builds it
# and records every attribute it set; the rest are handed the same paths.
_BUILT = {}


class MediaFixtures(unittest.TestCase):
    """Base class for the end-to-end group tests: the shared footage and the shared assertions."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            # Locally a skip; in CI (GitHub sets CI=true) a missing ffmpeg is a broken install
            # step and must fail, or a job with zero real tests reports green -- see
            # test_contract.py's require_ffmpeg_or_skip for the incident this guards against.
            if os.environ.get("CI"):
                raise AssertionError("ffmpeg not on PATH -- in CI this is a broken install step, not a reason to skip")
            raise unittest.SkipTest("ffmpeg not on PATH")
        OUT.mkdir(parents=True, exist_ok=True)
        if _BUILT:
            for _name, _value in _BUILT.items():
                setattr(cls, _name, _value)
            return
        _before = set(vars(cls))
        cls.src = OUT / "source.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
           "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", cls.src)
        cls.mic = OUT / "lavmic.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "2.5", "-i", cls.src, "-vn", "-c:a", "pcm_s16le", cls.mic)
        cls.logo = OUT / "logo.png"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red@0.8:s=240x90,format=rgba", "-frames:v", "1", cls.logo)
        cls.cues = OUT / "cues.txt"
        cls.cues.write_text("0:00-0:03 Hello world\n0:03-0:06 Second | line\nAuto timed cue\n", encoding="utf-8")

        # --- "real world" material: VFR, rotated phone clip, 5.1 audio, 10-bit HDR10 HEVC, long drifting pair
        cls.vfr = OUT / "vfr.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "12", "-vf", "select='gt(random(1)\\,0.3)'", "-fps_mode", "vfr",
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", cls.vfr)
        cls.rot = OUT / "rot.mp4"
        # -display_rotation arrived in FFmpeg 6.0; on 5.x the rotation is written the old way,
        # as the stream's rotate tag, which every probe here reads the same. Only the fixture
        # builder cares -- the tools under test never emit either.
        if subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.1", "-f", "null", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0:
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", cls.src, "-t", "6", "-c", "copy", cls.rot)
        else:
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", cls.src, "-t", "6", "-c", "copy", "-metadata:s:v:0", "rotate=90", cls.rot)
        cls.surround = OUT / "surround.mov"
        six = "|".join([TONES, TONES, "0.5*" + TONES, "0.2*sin(2*PI*60*t)", "0.3*" + TONES, "0.3*" + TONES])
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{six}':s=48000:c=5.1",
           "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ac", "6", cls.surround)
        cls.hdr = OUT / "hdr10.mp4"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000",
           "-t", "4", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
           "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error",
           "-tag:v", "hvc1", "-c:a", "aac", cls.hdr)
        cls.long_ref = OUT / "long_ref.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000", "-t", "200", "-c:a", "pcm_s16le", cls.long_ref)
        cls.long_drift = OUT / "long_drift.wav"
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.2", "-i", cls.long_ref,
           "-af", "asetrate=48000*0.9995,aresample=48000", "-c:a", "pcm_s16le", cls.long_drift)
        _BUILT.update({_name: getattr(cls, _name) for _name in set(vars(cls)) - _before})

    def assertClose(self, a, b, tol, msg=""):
        self.assertIsNotNone(a, msg)
        self.assertLessEqual(abs(a - b), tol, f"{msg}: {a} vs {b} (tol {tol})")
    # ------------------------------------------------- captions people can read (1.12)
    def _small(self):
        """A 640x360 clip: the wrap is computed from the real frame geometry, and a small frame
        makes the safe-area limit bite at an ordinary caption size."""
        small = OUT / "cap_small.mp4"
        if not small.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=440",
               "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-pix_fmt", "yuv420p", "-c:a", "aac", small)
        return small
    def _vertical(self):
        """A 1080x1920 clip: the real TikTok/Reels geometry, where the default caption size is
        wide enough that an ordinary sentence needs four lines (eval 17)."""
        vert = OUT / "cap_vertical.mp4"
        if not vert.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=size=1080x1920:rate=30", "-f", "lavfi", "-i", "sine=f=440",
               "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
               "-pix_fmt", "yuv420p", "-c:a", "aac", vert)
        return vert

    def _beats(self):
        """A 12 s clip with a synthetic 120 BPM click over moving pictures: a 440 Hz tone gated
        to a short pulse every 0.5 s. Built from ffmpeg's own sources, so it is the same click on
        every machine and the measured tempo is a fact of the fixture, not of the CI runner."""
        clip = OUT / "beats.mp4"
        if not clip.exists():
            # a 40 ms pulse at the top of every half second
            click = "0.8*sin(2*PI*880*t)*lt(mod(t\\,0.5)\\,0.04)"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", f"aevalsrc='{click}':s=48000",
               "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", clip)
        return clip

    def _silent_clip(self):
        """12 s of near-silence over moving pictures: an audio stream with no pulse to measure."""
        clip = OUT / "no_beats.mp4"
        if not clip.exists():
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "anoisesrc=amplitude=0.002:r=48000",
               "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", clip)
        return clip

    def _gappy(self):
        """A 12 s clip whose audio is speech-and-pause: tone for 2 s, silence for 2 s, six times
        over. The structure detectors (silence.py, metadata.py --auto-chapters) have something
        real to find, and the pauses sit at known seconds so an assertion can name them."""
        gappy = OUT / "gappy.mp4"
        if not gappy.exists():
            gate = "gt(mod(t\\,4)\\,2)"
            sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*440*t)*{gate}':s=48000",
               "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", gappy)
        return gappy

    @staticmethod
    def _srt_cues(path):
        blocks = [b for b in Path(path).read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
        out = []
        for b in blocks:
            lines = b.splitlines()
            out.append((lines[1], lines[2:]))
        return out
    def _band_luma(self, video, png):
        """Mean luminance of the bottom quarter of a frame -- the caption band."""
        script("look.py", video, "--at", "1", "-o", png, "--no-timecode")
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(png),
                              "-vf", "crop=iw:ih/4:0:ih*3/4", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             stdout=subprocess.PIPE).stdout
        self.assertTrue(raw)
        return sum(raw) / len(raw)
    # ------------------------------------------------------------------ 1.13: the audio bed
    def _audio_filters(self, *args):
        """The filter graph audio.py plans, from --dry-run --json (no encode)."""
        data = json.loads(script("audio.py", *args, "--dry-run", "--json").stdout)
        cmd = next(c for c in data["commands"] if "-filter_complex" in c)
        return cmd.split("-filter_complex ", 1)[1].split(" -map", 1)[0].strip("'"), data
    def _side_peak_db(self, path):
        """Peak level of the side signal (L-R) in dBFS; -inf (returned as -120) means the two
        channels are identical, i.e. the file has no stereo image at all."""
        proc = sh("ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-af",
                  "pan=mono|c0=c0-c1,astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-")
        peak = re.search(r"Peak level dB: (-?[0-9.]+|-inf)", proc.stderr)
        self.assertIsNotNone(peak, proc.stderr[-400:])
        return -120.0 if peak.group(1) == "-inf" else float(peak.group(1))
    def _proj(self, name, body):
        p = OUT / name
        p.write_text(json.dumps(dict({"output": name.replace(".json", ".mp4")}, **body)), encoding="utf-8")
        return p
    # ------------------------------------------------------- delivery templates (1.14)
    def _region_stats(self, path, crop, at=1.0):
        """Mean luma and spread of one region of a frame, as signalstats reports them."""
        proc = sh("ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
                  "-vf", f"crop={crop},signalstats,metadata=print:file=-", "-f", "null", "-")
        vals = {k: float(v) for k, v in re.findall(r"lavfi\.signalstats\.(YAVG|YMIN|YMAX)=([0-9.]+)", proc.stdout)}
        return vals["YAVG"], vals["YMAX"] - vals["YMIN"]
    # ---------------------------------------------------------------- help

    # ------------------------------------------------------------------ audio: extraction, concat, precision, dynamics
    @staticmethod
    def _samples(path):
        """(codec, sample_rate, duration_ts) of the first audio stream as ffprobe sees it."""
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,duration_ts",
                              "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, text=True, check=True).stdout.strip().split(",")
        return out[0], int(out[1]), int(out[2])
    @staticmethod
    def _peak_rms(path):
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "astats=measure_overall=Peak_level+RMS_level:measure_perchannel=none",
                               "-f", "null", "-"], stderr=subprocess.PIPE, text=True)
        vals = dict(re.findall(r"(Peak level|RMS level) dB: (-?[\d.]+)", proc.stderr))
        return float(vals["Peak level"]), float(vals["RMS level"])
    # ------------------------------------------------------------------ FFmpeg 8+ / Windows compatibility
    @staticmethod
    def _frame_count(path):
        proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                              stdout=subprocess.PIPE, text=True)
        return int(proc.stdout.strip())
    @staticmethod
    def _psnr(a, b):
        """Average PSNR of b against a (dB); lower means the picture changed more. inf when identical."""
        # Two things make this compare pixels and nothing else. (1) Both inputs are re-stamped by
        # frame *number*, so the psnr filter (which pairs frames by timestamp) never compares a
        # frame with its neighbour; frame *count* equality is asserted separately by the callers
        # that care, so a genuinely dropped frame still fails. (2) Both inputs get the *same*
        # colour tags before psnr. From FFmpeg 7.1 libavfilter negotiates colourspace, and psnr
        # on an untagged source vs a bt709-tagged output auto-inserts a real bt709->bt601
        # conversion on one side (8.x: 26 dB for a byte-identical picture) -- and, worse, hides
        # an encode-time conversion by undoing it (8.x reported 40 dB for an output whose pixels
        # had been re-matrixed, which is how the 7.1+ -colorspace bug in #156 went unnoticed on
        # macOS). With the tags pinned identical, every build from 5.1 to 8.1 reports the same
        # number for the same two files.
        same = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi",
                               f"[0:v]setpts=N/FRAME_RATE/TB,{same}[a];[1:v]setpts=N/FRAME_RATE/TB,{same}[b];[a][b]psnr", "-f", "null", "-"],
                              stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"average:(inf|[\d.]+)", proc.stderr)
        assert m, proc.stderr[-400:]
        return float("inf") if m.group(1) == "inf" else float(m.group(1))
    @staticmethod
    def _any_ttf():
        for root in ("/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts", "/System/Library/Fonts", "C:/Windows/Fonts"):
            for pat in ("**/DejaVuSans.ttf", "**/Arial.ttf", "**/arial.ttf", "**/*.ttf"):
                hits = list(Path(root).glob(pat)) if Path(root).exists() else []
                if hits:
                    return hits[0]
        return None
