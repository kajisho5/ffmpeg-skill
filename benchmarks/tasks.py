"""The requests of the with/without-skill benchmark (#677) and the checkers that grade them.

Each task is one ordinary request a person types, the input files it names (made with ffmpeg at run
time, never committed), the output file it asks for, and a checker that measures that file: its
length, frame size, streams, loudness, the brightness of a frame, the pitch of its sound. What the
model says it did is recorded beside the result and never graded.

The 2026-11-21 benchmark behind #633, #670 and #684 ran 24 requests from a scratch directory; its
task file was not committed. The requests it named (cut, resize, 9:16, mute, fade, join, captions,
loudness, a Reel, cut out the pauses) are here; the other fourteen are ordinary edits written for
this set. Results from this file are therefore a new series: they are compared with each other,
not with the published 2026-11-21 figures (docs/benchmark.md says which is which).

Standard library only; every measurement is an ffprobe or ffmpeg call.
"""
import json
import os
import re
import subprocess
from pathlib import Path

TASK_SET = "common-24"

# --- fixtures: name -> ffmpeg arguments after `ffmpeg -v error -y` (the output name is appended)
SINE = "sine=f=440:d={d}:sample_rate=48000"
FIXTURES = {
    "clip.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=8", "-f", "lavfi", "-i", SINE.format(d=8),
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest"],
    # brightness rises 25 levels a second (16 at 0 s, 216 at 8 s): a frame's level says its time
    "ramp.mp4": ["-f", "lavfi", "-i", "color=gray:s=640x360:r=25:d=8,format=yuv420p,geq=lum='16+25*T':cb=128:cr=128",
                 "-f", "lavfi", "-i", SINE.format(d=8), "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest"],
    "a.mp4": ["-f", "lavfi", "-i", "color=0xc8c8c8:s=640x360:r=25:d=3", "-f", "lavfi", "-i", SINE.format(d=3),
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "b.mp4": ["-f", "lavfi", "-i", "color=0x303030:s=640x360:r=25:d=4", "-f", "lavfi", "-i", "sine=f=880:d=4:sample_rate=48000",
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "flat.mp4": ["-f", "lavfi", "-i", "color=gray:s=640x360:r=25:d=8", "-f", "lavfi", "-i", SINE.format(d=8),
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    # a tone at about -30 dBFS: far from -14 LUFS
    "quiet.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=8", "-f", "lavfi", "-i", SINE.format(d=8),
                  "-af", "volume=-12dB", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "long.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=30", "-f", "lavfi", "-i", SINE.format(d=30),
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    # #684's case: a tone for 3 s in every 5 over a room whose hiss peaks above -35 dBFS, so the
    # default threshold finds no pause. The tone is 12 s of the 20.
    "talk.mp4": ["-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:d=20:seed=7", "-f", "lavfi", "-i", "sine=f=300:d=20",
                 "-f", "lavfi", "-i", "color=gray:s=640x360:r=25:d=20",
                 "-filter_complex", "[1]volume='if(lt(mod(t,5),3),2.5,0)':eval=frame[t];[0][t]amix=inputs=2:normalize=0[a]",
                 "-map", "2:v", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    # left half white, right half black: a rotation's direction is where the white half lands
    "halves.mp4": ["-f", "lavfi", "-i", "color=black:s=640x360:r=25:d=4", "-f", "lavfi", "-i", "color=white:s=320x360:r=25:d=4",
                   "-f", "lavfi", "-i", SINE.format(d=4), "-filter_complex", "[0][1]overlay=0:0,format=yuv420p[v]",
                   "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest"],
    "music.wav": ["-f", "lavfi", "-i", "sine=f=880:d=8:sample_rate=48000"],
    "tall.mp4": ["-f", "lavfi", "-i", "color=white:s=360x640:r=25:d=4", "-f", "lavfi", "-i", SINE.format(d=4),
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    # moving noise: about 14 MB for 10 s
    "big.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=10,noise=alls=12:allf=t", "-f", "lavfi", "-i", SINE.format(d=10),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
}
TEXT_FIXTURES = {"subs.srt": "1\n00:00:01,000 --> 00:00:04,000\nHELLO WORLD\n\n2\n00:00:05,000 --> 00:00:05,500\nOK\n"}


def fixture_command(name, workdir):
    return ["ffmpeg", "-v", "error", "-nostdin", "-y", *FIXTURES[name], str(Path(workdir) / name)]


def make_fixtures(names, workdir):
    for name in names:
        if name in TEXT_FIXTURES:
            (Path(workdir) / name).write_text(TEXT_FIXTURES[name], encoding="utf-8")
        else:
            subprocess.run(fixture_command(name, workdir), check=True, capture_output=True)


# --- measurements
def probe(path):
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                          capture_output=True, text=True)
    return json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else None


def streams(info, kind):
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind and not (s.get("disposition") or {}).get("attached_pic")]


def duration(info):
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def display_size(info):
    """Width and height as shown: a 90-degree rotation tag swaps them, the sample aspect scales the width."""
    v = streams(info, "video")[0]
    w, h = int(v["width"]), int(v["height"])
    num, _, den = (v.get("sample_aspect_ratio") or "1:1").partition(":")
    if num.isdigit() and den.isdigit() and int(num) and int(den):
        w = round(w * int(num) / int(den))
    rotation = next((sd.get("rotation") for sd in v.get("side_data_list", []) if "rotation" in sd), 0) or 0
    return (h, w) if abs(int(rotation)) % 180 == 90 else (w, h)


def frame_stats(path, t, crop=None):
    """YAVG / YMAX / SATAVG of the frame shown at t (rotation applied, as a player shows it)."""
    vf = (f"crop={crop}," if crop else "") + "signalstats,metadata=print:file=-"
    proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                           "-vf", vf, "-f", "null", "-"], capture_output=True, text=True)
    found = {}
    for key, value in re.findall(r"lavfi\.signalstats\.(YAVG|YMAX|SATAVG)=([\d.]+)", proc.stdout):
        found.setdefault(key, float(value))  # the first frame: the filter prints a few past -frames:v 1
    return found or None


def integrated_lufs(path):
    proc = subprocess.run(["ffmpeg", "-v", "info", "-nostdin", "-i", str(path), "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-"],
                          capture_output=True, text=True)
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    return float(found[-1]) if found else None


def mean_volume(path):
    proc = subprocess.run(["ffmpeg", "-v", "info", "-nostdin", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True)
    found = re.search(r"mean_volume:\s*(-?[\d.]+) dB", proc.stderr)
    return float(found[1]) if found else None


def tone_hz(path, at=1.0):
    """The pitch of one second of a pure tone, from its zero crossings."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{at:.3f}", "-t", "1", "-i", str(path), "-map", "0:a:0",
                           "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True)
    import array
    pcm = array.array("h", proc.stdout[: len(proc.stdout) // 2 * 2])
    if len(pcm) < 4000:
        return None
    crossings = sum(1 for a, b in zip(pcm, pcm[1:]) if (a < 0) != (b < 0))
    return crossings / 2 / (len(pcm) / 8000)


def near(value, target, tol):
    return value is not None and abs(value - target) <= tol


# --- checkers: each takes the output path and returns (ok, what was measured)
def _video(out):
    info = probe(out)
    if not info or not streams(info, "video"):
        return None, "no readable video in the output"
    return info, ""


def check_length(out, target, tol, first_level=None, need_audio=True):
    info, why = _video(out)
    if not info:
        return False, why
    d = duration(info)
    msg = f"length {d}s (asked {target}+-{tol})"
    if not near(d, target, tol):
        return False, msg
    if need_audio and not streams(info, "audio"):
        return False, msg + "; the sound is gone"
    if first_level is not None:
        y = (frame_stats(out, 0.0) or {}).get("YAVG")
        msg += f"; first frame level {y} (the asked start is {first_level})"
        if not near(y, first_level, 12):
            return False, msg
    return True, msg


def check_size(out, w, h):
    info, why = _video(out)
    if not info:
        return False, why
    size = display_size(info)
    return size == (w, h) and near(duration(info), 8, 0.2), f"frame {size[0]}x{size[1]}, length {duration(info)}s"


def check_aspect(out, ratio, length, tol=0.2, min_width=0):
    info, why = _video(out)
    if not info:
        return False, why
    w, h = display_size(info)
    ok = abs(w / h - ratio) <= 0.01 and w >= min_width and near(duration(info), length, tol)
    return ok, f"frame {w}x{h} (aspect {w / h:.4f}, asked {ratio:.4f}), length {duration(info)}s"


def check_mute(out):
    info, why = _video(out)
    if not info:
        return False, why
    return not streams(info, "audio") and near(duration(info), 8, 0.2), f"{len(streams(info, 'audio'))} sound stream(s), length {duration(info)}s"


def check_fade(out):
    info, why = _video(out)
    if not info:
        return False, why
    d = duration(info) or 0
    first, mid, last = ((frame_stats(out, t) or {}).get("YAVG") for t in (0.0, d / 2, max(0.0, d - 0.08)))
    ok = near(d, 8, 0.2) and None not in (first, mid, last) and first < 30 and last < 30 and mid > 60 and streams(info, "audio")
    return bool(ok), f"levels first {first}, middle {mid}, last {last}; length {d}s"


def check_join(out):
    ok, msg = check_length(out, 7.0, 0.25)
    if not ok:
        return ok, msg
    a, b = ((frame_stats(out, t) or {}).get("YAVG") for t in (1.0, 5.5))
    return (a or 0) > 150 and (b or 255) < 100, msg + f"; level at 1 s {a} (a.mp4), at 5.5 s {b} (b.mp4)"


def check_captions(out):
    info, why = _video(out)
    if not info:
        return False, why
    band = "iw:ih/3:0:ih*2/3"
    on, off = ((frame_stats(out, t, band) or {}).get("YMAX") for t in (2.5, 6.5))
    ok = near(duration(info), 8, 0.2) and on is not None and off is not None and on >= 200 and off < 170
    return bool(ok), f"brightest pixel of the lower third: {on} during a cue, {off} between cues"


def check_lufs(out, target):
    info = probe(out)
    if not info or not streams(info, "audio"):
        return False, "no sound in the output"
    lufs = integrated_lufs(out)
    return near(lufs, target, 1.5) and bool(streams(info, "video")), f"integrated loudness {lufs} LUFS (asked {target})"


def check_pauses(out):
    info, why = _video(out)
    if not info:
        return False, why
    d = duration(info)
    return d is not None and 11.5 <= d <= 15.5 and bool(streams(info, "audio")), f"length {d}s (the 20 s talk has 12 s of tone)"


def check_speed(out):
    info, why = _video(out)
    if not info:
        return False, why
    audio = streams(info, "audio")
    a = float(audio[0].get("duration") or 0) if audio else None
    return near(duration(info), 4, 0.2) and near(a, 4, 0.3), f"length {duration(info)}s, sound {a}s (asked 4 s for both)"


def check_rotate(out):
    info, why = _video(out)
    if not info:
        return False, why
    w, h = display_size(info)
    top, bottom = ((frame_stats(out, 1.0, crop) or {}).get("YAVG") for crop in ("iw:ih/2:0:0", "iw:ih/2:0:ih/2"))
    ok = (w, h) == (360, 640) and top is not None and bottom is not None and top > bottom + 100
    return ok, f"frame {w}x{h}; top half level {top}, bottom {bottom} (the white left half lands on top when turned clockwise)"


def check_mp3(out):
    info = probe(out)
    if not info:
        return False, "no readable output"
    audio = streams(info, "audio")
    ok = bool(audio) and audio[0].get("codec_name") == "mp3" and not streams(info, "video") and near(duration(info), 8, 0.2)
    return ok, f"codecs {[s.get('codec_name') for s in info.get('streams', [])]}, length {duration(info)}s"


def check_gif(out):
    info, why = _video(out)
    if not info:
        return False, why
    return "gif" in info["format"].get("format_name", "") and near(duration(info), 3, 0.3), \
        f"format {info['format'].get('format_name')}, length {duration(info)}s"


def check_still(out, level):
    info, why = _video(out)
    if not info:
        return False, why
    y = (frame_stats(out, 0.0) or {}).get("YAVG")
    is_image = info["format"].get("format_name", "") in ("image2", "jpeg_pipe", "mjpeg")
    return is_image and near(y, level, 12), f"format {info['format'].get('format_name')}, level {y} (the frame at 4 s is {level})"


def check_square(out):
    info, why = _video(out)
    if not info:
        return False, why
    w, h = display_size(info)
    return w == h and h >= 340 and near(duration(info), 8, 0.2), f"frame {w}x{h}"


def check_louder(out, source):
    info = probe(out)
    if not info or not streams(info, "audio") or not streams(info, "video"):
        return False, "the output lacks its picture or its sound"
    gain = (mean_volume(out) or -99) - (mean_volume(source) or 0)
    return 5.0 <= gain <= 7.0, f"mean level {gain:+.1f} dB against the source (asked +6)"


def check_gray(out):
    info, why = _video(out)
    if not info:
        return False, why
    sat = (frame_stats(out, 2.0) or {}).get("SATAVG")
    return sat is not None and sat < 1.5 and near(duration(info), 8, 0.2), f"mean saturation {sat} (0 is black and white)"


def check_music(out):
    info, why = _video(out)
    if not info:
        return False, why
    hz = tone_hz(out) if streams(info, "audio") else None
    return near(hz, 880, 40) and near(duration(info), 8, 0.3), f"pitch {hz} Hz (music.wav is 880, the clip 440), length {duration(info)}s"


def check_webm(out):
    info, why = _video(out)
    if not info:
        return False, why
    codec = streams(info, "video")[0].get("codec_name")
    ok = "webm" in info["format"].get("format_name", "") and codec in ("vp8", "vp9", "av1") and near(duration(info), 8, 0.2)
    return ok, f"format {info['format'].get('format_name')}, video {codec}"


def check_fps(out, fps):
    info, why = _video(out)
    if not info:
        return False, why
    num, _, den = streams(info, "video")[0].get("avg_frame_rate", "0/1").partition("/")
    rate = int(num) / int(den) if den and int(den) else 0
    return near(rate, fps, 0.01) and near(duration(info), 8, 0.2) and bool(streams(info, "audio")), f"{rate:.3f} fps"


def check_letterbox(out):
    info, why = _video(out)
    if not info:
        return False, why
    side, middle = ((frame_stats(out, 1.0, crop) or {}).get("YAVG") for crop in ("200:ih:0:0", "200:ih:860:0"))
    ok = display_size(info) == (1920, 1080) and side is not None and middle is not None and side < 25 and middle > 200
    return ok, f"frame {display_size(info)}, side level {side}, middle level {middle}"


def check_under(out, limit_bytes):
    info, why = _video(out)
    if not info:
        return False, why
    size = os.path.getsize(out)
    return size < limit_bytes and near(duration(info), 10, 0.3) and bool(streams(info, "audio")), f"{size} bytes (limit {limit_bytes})"


# --- the set. `reference` is an ffmpeg command (after `ffmpeg -v error -y`, inputs relative to
# the work folder) that writes a correct output: the checkers' own tests run it and the input
# unchanged, and expect a pass and a fail.
TASKS = [
    dict(id="cut", request="Cut ramp.mp4 from 0:02 to 0:06 and save it as out.mp4.", inputs=["ramp.mp4"], output="out.mp4",
         check=lambda o, w: check_length(o, 4.0, 0.12, first_level=66),
         reference=["-ss", "2", "-i", "ramp.mp4", "-t", "4", "-c:v", "libx264", "-c:a", "aac"]),
    dict(id="resize", request="Resize clip.mp4 to 1280x720 and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_size(o, 1280, 720), reference=["-i", "clip.mp4", "-vf", "scale=1280:720", "-preset", "ultrafast"]),
    dict(id="vertical", request="Make clip.mp4 vertical (9:16) for phones and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_aspect(o, 9 / 16, 8), reference=["-i", "clip.mp4", "-vf", "crop=202:360,scale=1080:1920,setsar=1", "-preset", "ultrafast"]),
    dict(id="mute", request="Remove the sound from clip.mp4 and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_mute(o), reference=["-i", "clip.mp4", "-an", "-c:v", "copy"]),
    dict(id="fade", request="Fade clip.mp4 in from black over 1 second and out to black over the last second. Save it as out.mp4.",
         inputs=["clip.mp4"], output="out.mp4", check=lambda o, w: check_fade(o),
         reference=["-i", "clip.mp4", "-vf", "fade=in:d=1,fade=out:st=7:d=1", "-af", "afade=in:d=1,afade=out:st=7:d=1"]),
    dict(id="join", request="Join a.mp4 and b.mp4 one after the other into out.mp4.", inputs=["a.mp4", "b.mp4"], output="out.mp4",
         check=lambda o, w: check_join(o),
         reference=["-i", "a.mp4", "-i", "b.mp4", "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]),
    dict(id="captions", request="Burn the captions in subs.srt into flat.mp4 and save it as out.mp4.", inputs=["flat.mp4", "subs.srt"],
         output="out.mp4", check=lambda o, w: check_captions(o),
         reference=["-i", "flat.mp4", "-vf", "subtitles=subs.srt:force_style='Fontsize=32,PrimaryColour=&H00FFFFFF'"]),
    dict(id="loudness", request="Normalize the loudness of quiet.mp4 to -14 LUFS and save it as out.mp4.", inputs=["quiet.mp4"],
         output="out.mp4", check=lambda o, w: check_lufs(o, -14.0),
         reference=["-i", "quiet.mp4", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1:LRA=11", "-ar", "48000"]),
    dict(id="reel", request="Make an Instagram Reel of the first 15 seconds of long.mp4 and save it as out.mp4.", inputs=["long.mp4"],
         output="out.mp4", check=lambda o, w: check_aspect(o, 9 / 16, 15, min_width=720),
         reference=["-i", "long.mp4", "-t", "15", "-vf", "crop=404:720,scale=1080:1920,setsar=1", "-preset", "ultrafast"]),
    dict(id="silence", request="Cut out the pauses in talk.mp4 and save it as out.mp4.", inputs=["talk.mp4"], output="out.mp4",
         check=lambda o, w: check_pauses(o),
         # the four 3 s spans of tone, cut and joined by name: select= with setpts kept a 20 s length on FFmpeg 8
         reference=["-i", "talk.mp4", "-filter_complex", "[0:v]trim=0:3,setpts=PTS-STARTPTS[v0];[0:a]atrim=0:3,asetpts=PTS-STARTPTS[a0];[0:v]trim=5:8,setpts=PTS-STARTPTS[v1];[0:a]atrim=5:8,asetpts=PTS-STARTPTS[a1];[0:v]trim=10:13,setpts=PTS-STARTPTS[v2];[0:a]atrim=10:13,asetpts=PTS-STARTPTS[a2];[0:v]trim=15:18,setpts=PTS-STARTPTS[v3];[0:a]atrim=15:18,asetpts=PTS-STARTPTS[a3];[v0][a0][v1][a1][v2][a2][v3][a3]concat=n=4:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]),
    dict(id="speed", request="Make clip.mp4 play twice as fast, sound included, and save it as out.mp4.", inputs=["clip.mp4"],
         output="out.mp4", check=lambda o, w: check_speed(o),
         reference=["-i", "clip.mp4", "-vf", "setpts=PTS/2", "-af", "atempo=2"]),
    dict(id="rotate", request="Rotate halves.mp4 90 degrees clockwise and save it as out.mp4.", inputs=["halves.mp4"], output="out.mp4",
         check=lambda o, w: check_rotate(o), reference=["-i", "halves.mp4", "-vf", "transpose=clock"]),
    dict(id="extract_audio", request="Extract the audio of clip.mp4 as out.mp3.", inputs=["clip.mp4"], output="out.mp3",
         check=lambda o, w: check_mp3(o), reference=["-i", "clip.mp4", "-vn", "-c:a", "libmp3lame"]),
    dict(id="gif", request="Make a GIF of the first 3 seconds of clip.mp4, saved as out.gif.", inputs=["clip.mp4"], output="out.gif",
         check=lambda o, w: check_gif(o), reference=["-t", "3", "-i", "clip.mp4", "-vf", "fps=10,scale=320:-1"]),
    dict(id="thumbnail", request="Save the frame at 4 seconds of ramp.mp4 as out.jpg.", inputs=["ramp.mp4"], output="out.jpg",
         check=lambda o, w: check_still(o, 116), reference=["-ss", "4", "-i", "ramp.mp4", "-frames:v", "1"]),
    dict(id="last5", request="Keep only the last 5 seconds of ramp.mp4 and save it as out.mp4.", inputs=["ramp.mp4"], output="out.mp4",
         check=lambda o, w: check_length(o, 5.0, 0.15, first_level=91), reference=["-ss", "3", "-i", "ramp.mp4"]),
    dict(id="square", request="Crop clip.mp4 to a centred square and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_square(o), reference=["-i", "clip.mp4", "-vf", "crop=360:360"]),
    dict(id="louder", request="Make the sound of clip.mp4 6 dB louder and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_louder(o, Path(w) / "clip.mp4"), reference=["-i", "clip.mp4", "-c:v", "copy", "-af", "volume=6dB"]),
    dict(id="grayscale", request="Make clip.mp4 black and white and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_gray(o), reference=["-i", "clip.mp4", "-vf", "hue=s=0"]),
    dict(id="replace_audio", request="Replace the sound of clip.mp4 with music.wav and save it as out.mp4.",
         inputs=["clip.mp4", "music.wav"], output="out.mp4", check=lambda o, w: check_music(o),
         reference=["-i", "clip.mp4", "-i", "music.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest"]),
    dict(id="webm", request="Convert clip.mp4 to WebM, saved as out.webm.", inputs=["clip.mp4"], output="out.webm",
         check=lambda o, w: check_webm(o), reference=["-i", "clip.mp4", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"]),
    dict(id="fps24", request="Change clip.mp4 to 24 frames per second and save it as out.mp4.", inputs=["clip.mp4"], output="out.mp4",
         check=lambda o, w: check_fps(o, 24), reference=["-i", "clip.mp4", "-vf", "fps=24"]),
    dict(id="letterbox", request="Put tall.mp4 in a 1920x1080 frame with black bars at the sides and save it as out.mp4.",
         inputs=["tall.mp4"], output="out.mp4", check=lambda o, w: check_letterbox(o),
         reference=["-i", "tall.mp4", "-vf", "scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:black,setsar=1", "-preset", "ultrafast"]),
    dict(id="size_limit", request="Make big.mp4 smaller than 2 MB so I can send it, and save it as out.mp4.", inputs=["big.mp4"],
         output="out.mp4", check=lambda o, w: check_under(o, 2_000_000),
         reference=["-i", "big.mp4", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1000k", "-c:a", "aac", "-b:a", "64k"]),
]
BY_ID = {t["id"]: t for t in TASKS}


def grade(task, workdir):
    """(ok, what was measured) for the task's output in workdir; a missing output is a fail."""
    out = Path(workdir) / task["output"]
    if not out.is_file() or out.stat().st_size == 0:
        return False, f"{task['output']} was not written"
    try:
        ok, detail = task["check"](out, workdir)
    except Exception as e:  # a file the measurements cannot read is a fail, never a crash of the run
        return False, f"could not measure {task['output']}: {type(e).__name__}: {e}"
    return bool(ok), detail

