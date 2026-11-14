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

# The host's own defaults must not reach the suite (every tool subprocess inherits os.environ):
# FFMPEG_SKILL_ASR_ENGINE, FFMPEG_SKILL_ASR_MODEL or a PARAKEET_* setting would change which speech
# engine or model a --transcribe test drives, or where parakeet-mlx writes. Tests that exercise those
# opt in with an explicit env.
for _k in ("FFMPEG_SKILL_ASR_ENGINE", "FFMPEG_SKILL_ASR_MODEL", "PARAKEET_MODEL", "PARAKEET_CPP_MODEL", "PARAKEET_OUTPUT_TEMPLATE"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
from _common import escape_filter_path  # noqa: E402
from _common.runner import HW_ENV, HW_FORCED_ENV  # noqa: E402

# The host's own GPU default must not reach the suite (every tool subprocess inherits os.environ):
# a machine with FFMPEG_SKILL_HW=1 would put every encode on VideoToolbox. Tests that exercise it
# opt in with an explicit env. The names come from the runner, so this scrub and the one in
# test_contract.py cannot drift from what the tools read.
for _k in (HW_ENV, HW_FORCED_ENV):
    os.environ.pop(_k, None)

TONES = ("0.6*sin(2*PI*440*t)*gt(sin(2*PI*0.37*t)\\,0.3)+0.4*sin(2*PI*880*t)*gt(sin(2*PI*0.53*t+1)\\,0.6)"
         "+0.3*sin(2*PI*220*t)*gt(sin(2*PI*0.21*t+2)\\,0.7)")


# A command a test runs is over in seconds; one that is still running after this long never ends
# (a filter graph that does not reach EOF on one FFmpeg: #514, where the job ran until it was
# cancelled and its log named nothing). The test then fails with the command instead.
SH_LIMIT = float(os.environ.get("FFSKILL_TEST_SH_LIMIT", "900"))


def sh(*cmd, expect_fail=False, env=None):
    argv = [str(c) for c in cmd]
    posix = os.name == "posix"
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env=env, start_new_session=posix)
    try:
        out, err = child.communicate(timeout=SH_LIMIT)
    except subprocess.TimeoutExpired:
        if posix:  # the script's ffmpeg too: it is in the child's process group
            import signal
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except OSError:
                pass
        child.kill()
        out, err = child.communicate()
        raise AssertionError(f"still running after {SH_LIMIT:.0f} s, killed: {argv}\nSTDOUT:\n{out[-2000:]}\nSTDERR:\n{err[-2000:]}")
    proc = subprocess.CompletedProcess(argv, child.returncode, out, err)
    if expect_fail:
        assert proc.returncode != 0, f"expected failure but succeeded: {cmd}"
        return proc
    assert proc.returncode == 0, f"{cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc


# A/V sync fixtures (#409): a one-frame white flash and a 40 ms 1 kHz beep at the same instant,
# every second from 0.5 s, so flash minus beep is the A/V offset. `talk` adds three quiet "speech"
# stretches with silence between them for silence.py, and moves the flash/beep into each one.
_FLASH = "lt(mod(t-0.5\\,1)\\,0.03)*gte(t\\,0.5)"
_BEEP = "if(lt(mod(t-0.5\\,1)\\,0.04)*gte(t\\,0.5)\\,sin(2*PI*1000*t)\\,0)"
_TALK_FLASH = "between(t\\,1.2\\,1.23)+between(t\\,4.2\\,4.23)+between(t\\,7.2\\,7.23)"
_TALK_BEEP = ("0.1*(between(t\\,0.5\\,2.0)+between(t\\,3.5\\,5.0)+between(t\\,6.5\\,8.0))*sin(2*PI*300*t)"
              "+0.9*(lt(abs(t-1.22)\\,0.02)+lt(abs(t-4.22)\\,0.02)+lt(abs(t-7.22)\\,0.02))*sin(2*PI*1000*t)")


def make_flash_beep(path, *, audio_late=0.0, video_late=0.0, video_short=0.0, talk=False):
    """A tiny H.264/AAC clip whose flash and beep coincide. audio_late: the sound track starts that
    much after the picture (its samples from that source time on); video_late: the picture starts
    that much after the sound; video_short: the picture ends that much before the sound."""
    dur = 9 if talk else 4
    vsrc = (f"color=c=black:s=160x120:r=30:d={dur - video_short:g},"
            f"drawbox=c=white:t=fill:enable='{_TALK_FLASH if talk else _FLASH}'")
    asrc = f"aevalsrc='{_TALK_BEEP if talk else _BEEP}':s=48000:d={dur}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", vsrc]
    if audio_late:
        cmd += ["-itsoffset", f"{audio_late:g}", "-f", "lavfi", "-i", f"{asrc},atrim=start={audio_late:g},asetpts=PTS-STARTPTS"]
    else:
        cmd += ["-f", "lavfi", "-i", asrc]
    if video_late:
        cmd += ["-vf", f"trim=start={video_late:g}", "-fps_mode", "passthrough"]
    sh(*cmd, "-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "128k", path)
    return path


def make_tones_take(path, *, start=0.0, audio_late=0.0, dur=10.0):
    """A camera take of the TONES bed (not periodic, so sync.py's correlation has one answer): its
    picture and its clock start at `start` on the bed, and its sound track starts `audio_late`
    after its picture, with the bed's samples from start + audio_late on."""
    a0 = start + audio_late
    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
       "-f", "lavfi", "-i", f"color=c=gray:s=160x120:r=30:d={dur:g}",
       *(["-itsoffset", f"{audio_late:g}"] if audio_late else []),
       "-f", "lavfi", "-i", f"aevalsrc='{TONES}':s=48000:d={start + dur:g},atrim=start={a0:g},asetpts=PTS-STARTPTS",
       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", path)
    return path


def flash_times(path):
    """The time of every flash in `path`'s picture (a frame whose mean luma jumps above 100)."""
    proc = sh("ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-i", path, "-map", "0:v:0",
              "-vf", "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG", "-f", "null", "-")
    flashes, t, prev = [], None, False
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([-\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", line)
        if m and t is not None:
            on = float(m.group(1)) > 100
            if on and not prev:
                flashes.append(t)
            prev = on
    return flashes


def av_offsets_ms(path, beep_db=-30):
    """Flash minus nearest beep onset, in ms, for every flash in `path` (both read from the file's
    own timestamps: the picture's luma per frame, the sound's silencedetect ends)."""
    flashes = flash_times(path)
    proc = sh("ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
              "-af", f"silencedetect=n={beep_db}dB:d=0.02", "-f", "null", "-")
    beeps = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    assert flashes and beeps, f"{path}: flashes {flashes}, beeps {beeps}"
    return [round((f - min(beeps, key=lambda b: abs(b - f))) * 1000) for f in flashes]


def stream_spans(path):
    """{codec_type: (start_time, duration, frames or packets)} of `path`'s first video and audio."""
    doc = json.loads(sh("ffprobe", "-v", "error", "-count_packets", "-show_entries",
                        "stream=codec_type,start_time,duration,nb_read_packets", "-of", "json", path).stdout)
    out = {}
    for s in doc["streams"]:
        out.setdefault(s["codec_type"], (float(s.get("start_time") or 0), float(s.get("duration") or 0),
                                         int(s.get("nb_read_packets") or 0)))
    return out


# Two pictures and two sound tracks in which FFmpeg's default stream selection does not pick the
# ones probe() describes (A110, A118, A128, A258): Matroska with no default disposition, so the
# larger picture and the track with more channels win. Each stream is told apart by its content.
MULTI_PROBED = {"size": (160, 120), "hz": 440, "lufs": -32.2}  # v:0 testsrc2, a:0 a quiet 440 Hz sine
MULTI_OTHER = {"size": (320, 240), "hz": 660, "lufs": -21.6}   # v:1 solid red, a:1 a louder 660 Hz sine


def make_multistream(path, *, subtitle=False, mono_first=True, seconds=4):
    """v:0 testsrc2 160x120 and v:1 red 320x240; a:0 440 Hz at about -32 LUFS and a:1 660 Hz at
    about -22 LUFS, a:0 mono and a:1 stereo (mono_first) or the reverse; optionally a text
    subtitle track. No stream carries the default disposition."""
    layouts = ("mono", "stereo") if mono_first else ("stereo", "mono")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc2=s=160x120:r=25:d={seconds}",
           "-f", "lavfi", "-i", f"color=c=red:s=320x240:r=25:d={seconds}",
           "-f", "lavfi", "-i", f"sine=f=440:d={seconds}:sample_rate=48000,volume=0.3,aformat=channel_layouts={layouts[0]}",
           "-f", "lavfi", "-i", f"sine=f=660:d={seconds}:sample_rate=48000,aformat=channel_layouts={layouts[1]}"]
    maps = ["-map", "0", "-map", "1", "-map", "2", "-map", "3"]
    if subtitle:
        srt = Path(str(path) + ".srt")
        srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nhello\n", encoding="utf-8")
        cmd += ["-i", str(srt)]
        maps += ["-map", "4"]
    disp = [x for n in ("v:0", "v:1", "a:0", "a:1") + (("s:0",) if subtitle else ()) for x in (f"-disposition:{n}", "0")]
    sh(*cmd, *maps, "-c:v", "libx264", "-preset", "veryfast", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac",
       *(["-c:s", "srt"] if subtitle else []), *disp, path)
    return path


def tone_db(path, hz, stream="a:0"):
    """Mean level (dBFS) of `path`'s `stream` in a 40 Hz band around `hz`: which source track it is."""
    proc = sh("ffmpeg", "-nostdin", "-i", path, "-map", f"0:{stream}", "-af", f"bandpass=f={hz}:w=40,volumedetect",
              "-f", "null", "-")
    return float(re.search(r"mean_volume:\s*(-?[0-9.]+) dB", proc.stderr).group(1))


def written_track(path):
    """'a:0' or 'a:1' of make_multistream(): which source track `path`'s first audio stream holds."""
    return "a:0" if tone_db(path, MULTI_PROBED["hz"]) > tone_db(path, MULTI_OTHER["hz"]) else "a:1"


def integrated_lufs(path, stream="a:0"):
    proc = sh("ffmpeg", "-nostdin", "-i", path, "-map", f"0:{stream}", "-af", "ebur128", "-f", "null", "-")
    return float(re.findall(r"I:\s+(-?[0-9.]+) LUFS", proc.stderr)[-1])


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
    # caption.py's --write-srt/--write-ass sidecars are outputs too since 2.2.4.
    names_output = ("-o" in args or "--output" in args or "--write-srt" in args or "--write-ass" in args
                    or name in ("render.py", "batch.py"))
    if names_output and "--overwrite" not in args and "--help" not in args:
        args = args + ("--overwrite",)
    return sh(sys.executable, SCRIPTS / name, *args, **kw)

def tiny_clip(path, source, *extra, seconds=1, audio=False, pix_fmt="yuv420p"):
    """A tiny lavfi clip for a geometry test (#411): `source` is a lavfi video graph such as
    "color=c=red:s=180x180:r=30"; `extra` goes before the output (a -vf, -timecode ...)."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000"]
    cmd += ["-t", str(seconds), *extra, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", pix_fmt]
    cmd += (["-c:a", "aac", "-shortest"] if audio else [])
    sh(*cmd, path)
    return path


# Clips that say which frame is on screen (#470): frame N of numbered_clip() has a mean luma of
# 16 + 2 * N, stored losslessly, so a decode reads the frame's number back; plain_clip() is one
# flat luma to lay such a clip over. Both end on their own frame count (trim=end_frame): with
# -frames:v the muxer stopped the sound where the picture ended.
def _counted_clip(path, picture, rate, frames, sound, late):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    cmd += (["-itsoffset", str(late)] if late else []) + ["-f", "lavfi", "-i", f"{picture},trim=end_frame={frames}"]
    if sound:
        cmd += ["-f", "lavfi", "-i", sound]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p"] + (["-c:a", "pcm_s16le"] if sound else [])
    sh(*cmd, path)
    return path


def numbered_clip(path, rate, frames, sound=None, size="64x64", late=0):
    """`frames` frames at `rate` whose frame N has a luma of 16 + 2 * N. `sound` is a lavfi audio
    source with its own length; `late` starts the picture that many seconds after the sound."""
    return _counted_clip(path, f"color=black:s={size}:r={rate},geq=lum='16+2*N':cb=128:cr=128", rate, frames, sound, late)


def plain_clip(path, rate, frames, sound=None, size="64x64", luma=235, late=0):
    """`frames` frames at `rate` of one flat luma."""
    return _counted_clip(path, f"color=black:s={size}:r={rate},geq=lum={luma}:cb=128:cr=128", rate, frames, sound, late)


def frame_lumas(path, crop=None):
    """The mean luma of every frame of `path`'s picture in order (of the `crop` region if given)."""
    vf = (f"crop={crop}," if crop else "") + "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"
    out = sh("ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-vf", vf, "-f", "null", "-").stdout
    return [float(line.split("=")[1]) for line in out.splitlines() if "YAVG=" in line]


def frame_numbers(path):
    """The numbers of the numbered_clip() frames `path` shows, in order."""
    return [round((v - 16) / 2) for v in frame_lumas(path)]


def stretches(values, test):
    """[(first, last)] index ranges of `values` over which `test` holds."""
    out, start = [], None
    for i, v in enumerate(list(values) + [None]):
        hit = v is not None and test(v)
        if hit and start is None:
            start = i
        if not hit and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def pcm_of(command, path, channels=1):
    """The samples a result's last command writes, as one array of 16-bit values: the command is
    run again with PCM in place of AAC (an AAC frame smears an edge over 1024 samples)."""
    import array
    import shlex
    cmd = shlex.split(command)
    at = cmd.index("aac")
    assert (cmd[at - 1], cmd[at + 1]) == ("-c:a", "-b:a"), cmd
    cmd[at:at + 3], cmd[-1] = ["pcm_s16le"], str(path)
    sh(*cmd)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", str(channels), "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    pcm = array.array("h")
    pcm.frombytes(raw)
    return pcm


# legal_range_clip(): the share of each plane's samples set to each code in the first half of the
# frames (the rest of a frame, and every sample of the second half, is mid-grey 128). Luma: 10 and
# 250 are out of both bt709 and ebu-r103; 15 and 240 are out of bt709 only. Chroma (Cb): 10 is out
# of bt709 only (ebu-r103 allows 5..251). Cr stays 128.
LEGAL_FIXTURE_Y = ((10, 0.10), (250, 0.05), (15, 0.05), (240, 0.05))
LEGAL_FIXTURE_U = ((10, 0.20),)


def legal_range_clip(path, depth=8, size=64, frames=10, rate=10):
    """A lossless FFV1 clip with known out-of-range sample shares (LEGAL_FIXTURE_*), written from raw
    planes: frames 0..frames/2-1 carry the pattern, the rest are all 128 (scaled to `depth`).
    Returns {"y": {code: count}, "u": {code: count}, "samples": (luma, chroma)} for one patterned frame."""
    import struct
    n, c = size * size, (size // 2) * (size // 2)
    shift = depth - 8

    def plane(total, pattern):
        vals, k, counts = [128] * total, 0, {}
        for code, share in pattern:
            cnt = int(total * share)
            vals[k:k + cnt] = [code] * cnt
            counts[code] = cnt
            k += cnt
        return vals, counts

    y, ycounts = plane(n, LEGAL_FIXTURE_Y)
    u, ucounts = plane(c, LEGAL_FIXTURE_U)
    grey_y, grey_c = [128] * n, [128] * c
    fmt = "<%dH" if depth > 8 else "%dB"
    def pack(vals):
        return struct.pack(fmt % len(vals), *[v << shift for v in vals])
    raw = Path(str(path) + ".yuv")
    with open(raw, "wb") as f:
        for i in range(frames):
            on = i < frames // 2
            f.write(pack(y if on else grey_y) + pack(u if on else grey_c) + pack(grey_c))
    pix = "yuv420p" if depth == 8 else f"yuv420p{depth}le"
    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{size}x{size}",
       "-r", str(rate), "-i", raw, "-c:v", "ffv1", path)
    raw.unlink()
    return {"y": ycounts, "u": ucounts, "samples": (n, c)}


def sar_clip(path, colour="red", size="180x180", sar="16/9", seconds=1, audio=False):
    """A clip that stores non-square pixels: 180x180 at SAR 16:9 is a 320x180 picture on screen."""
    return tiny_clip(path, f"color=c={colour}:s={size}:r=30", "-vf", f"setsar={sar}", seconds=seconds, audio=audio)


def exif_rotated_jpeg(path, orientation=6, size="320x180"):
    """A JPEG of a testsrc frame carrying an EXIF Orientation tag (6: shown turned 90 degrees
    clockwise, a phone's portrait shot), written by inserting the APP1 segment by hand."""
    plain = Path(str(path) + ".plain.jpg")
    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}",
       "-frames:v", "1", plain)
    data = plain.read_bytes()
    ifd = (b"\x00\x01" + b"\x01\x12" + b"\x00\x03" + b"\x00\x00\x00\x01"
           + orientation.to_bytes(2, "big") + b"\x00\x00" + b"\x00\x00\x00\x00")
    tiff = b"MM\x00*\x00\x00\x00\x08" + ifd
    body = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body
    Path(path).write_bytes(data[:2] + app1 + data[2:])
    plain.unlink()
    return path


def frame_rgb(video, t, x, y, *, vf=None):
    """The RGB triple at (x, y) of the frame at `t` seconds, read as a player shows it
    (square pixels at the display aspect when `vf` squares them)."""
    cmd = ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1"]
    cmd += (["-vf", vf] if vf else [])
    proc = subprocess.run(cmd + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(video)],
                          stdout=subprocess.PIPE, text=True).stdout.strip().split(",")
    w = int(size[0])
    off = (y * w + x) * 3
    return tuple(proc.stdout[off:off + 3])


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
         "-vf", "ass=%s" % escape_filter_path(str(path)), "-frames:v", "1",
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
# One build per process, not one per group: setUpClass runs for each of the nine group classes and
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
        sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", cls.src, "-t", "6", "-c", "copy", cls.rot)
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
