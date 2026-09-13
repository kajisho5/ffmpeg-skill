"""Pure choices: given facts (a probe document, a codec name, a path, a flag value), return the
arguments or the value that follows from them.

Nothing here starts a subprocess or touches a media file, which is what makes the copy-vs-re-encode
and encoder-selection rules testable on their own.
"""
from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from _common.color import bt709_tag_args, _sdr_bt709
from _common.emit import die
from _common.runner import CODECS, STATE, ffmpeg_encoders


def pad_filters(out_w: int, out_h: int, fill: str, color: str, blur: int, darken: float = 0.0) -> str:
    """The letterbox/pillarbox step shared by fit.py and export.py, as one -vf segment.

    fill="color": scale to fit, then pad with a solid colour (the historical behaviour).
    fill="blur": the bars are a blurred, scaled-to-cover copy of the same frame -- what every
    phone editor's "make it vertical" does with landscape footage (#139). Built as a small
    graph inside the -vf chain: split, one branch scaled to cover and cropped to the frame
    then boxblur'ed, the other scaled to fit, overlaid centred. Only `filter:boxblur` is
    needed beyond the usual scale/pad set, and that is already required by redact.py.
    `darken` > 0 also dims that background copy by that much brightness (eq), so the picture in
    front reads as the subject instead of competing with a bright blurred copy of itself --
    what `fit.py --fit blur` uses (1.14)."""
    if fill == "blur":
        # boxblur rejects a radius larger than half the smaller dimension ("radius 20, must be
        # <= 8" on a 16 px target); clamp instead of failing an otherwise valid request
        radius = max(1, min(int(blur), max(1, min(out_w, out_h) // 2 - 1)))
        return (f"split[__fitfg][__fitbg];"
                f"[__fitbg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur={radius}:2" + (f",eq=brightness=-{darken:g}" if darken else "") + "[__fitbgb];"
                f"[__fitfg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[__fitfgs];"
                f"[__fitbgb][__fitfgs]overlay=(W-w)/2:(H-h)/2:format=auto")
    return f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color={color}"


def add_pad_fill_args(parser: "argparse.ArgumentParser") -> None:
    parser.add_argument("--pad-fill", choices=["color", "blur"], default="color",
                        help="what fills the letterbox/pillarbox bars under --fit pad: a solid --pad-color (default) or a blurred, scaled-up copy of the frame")
    parser.add_argument("--pad-blur", type=int, default=20, help="blur radius in pixels for --pad-fill blur (default 20)")


# x264 preset names mapped onto SVT-AV1's 0-13 speed scale (lower = slower / better)
SVT_PRESET = {"ultrafast": 12, "superfast": 11, "veryfast": 10, "faster": 9, "fast": 8, "medium": 6, "slow": 4, "slower": 3, "veryslow": 2, "placebo": 1}


def default_output(input_path: str, suffix: str, ext: Optional[str] = None) -> str:
    p = Path(input_path)
    new_ext = ext if ext else p.suffix.lstrip(".") or "mp4"
    return str(p.with_name(f"{p.stem}_{suffix}.{new_ext}"))


class MissingFpsError(ValueError):
    """parse_time() saw an hh:mm:ss:ff SMPTE timecode but no fps was given to convert it -- distinct
    from a plain ValueError so a caller that falls back to treating unparseable text as a literal
    line (e.g. caption.py's free-text cue format) can still fail loudly on this one, instead of
    silently swallowing a mistyped/missing --fps as an auto-timed line of digits."""


def concat_list_line(path: str) -> str:
    """One `file '...'` line for the concat demuxer. The demuxer reads backslash as an escape
    inside the quoted form, so a Windows path (C:\\Users\\...\\part000.mp4) must be written
    with forward slashes -- ffmpeg opens either spelling on Windows -- and a single quote in the
    name is closed, escaped and reopened. Shared by cut.py (multi-segment) and sequence.py."""
    escaped = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"


def fmt_secs(value: Optional[float]) -> str:
    """`12.345s`, or `?s` when the probe had no duration (MPEG-TS without a duration tag, a
    stream whose container and streams all omit it). Every writing tool prints the duration
    of what it wrote; formatting None with :.3f used to raise TypeError after a successful
    encode, in 25+ scripts."""
    return "?s" if value is None else f"{value:.3f}s"


def parse_time(value: str, fps: Optional[float] = None) -> float:
    """Accept seconds ('12.5'), mm:ss ('1:30'), hh:mm:ss(.ms) ('00:01:30.250'), SRT '00:01:30,250',
    or -- when `fps` is given -- SMPTE non-drop-frame timecode 'hh:mm:ss:ff' ('00:01:30:15')."""
    v = value.strip().replace(",", ".")
    if not v:
        raise ValueError("empty time")
    if "@" in v:
        # 1.9: 'hh:mm:ss:ff@29.97' names the timecode's rate explicitly (docs/design-decisions.md,
        # time grammar); it overrides the source fps a tool passed in, and is meaningless without
        # the four-part form
        v, _, rate = v.rpartition("@")
        if "@" in v:
            raise ValueError(f"'{value}': only one @fps suffix is allowed")
        try:
            fps = float(rate)
        except ValueError:
            raise ValueError(f"bad @fps suffix in '{value}' (expected a number such as @29.97)")
        if fps <= 0:
            raise ValueError(f"bad @fps suffix in '{value}': the rate must be positive")
        if len(v.split(":")) != 4:
            raise ValueError(f"'{value}': the @fps suffix belongs to an hh:mm:ss:ff timecode, not to seconds or mm:ss")
    parts = v.split(":")
    if len(parts) == 4:
        if fps is None or fps <= 0:
            raise MissingFpsError(f"'{value}' looks like an hh:mm:ss:ff SMPTE timecode, but no fps was given to convert its frame count to seconds (append @fps, e.g. {value}@29.97, or use seconds / mm:ss / hh:mm:ss.ms)")
        h, m, s, f = parts
        if "." in f:
            raise ValueError(f"bad SMPTE timecode: {value}")
        frame, whole_fps = int(f), int(round(fps))
        if not (0 <= frame < whole_fps):
            raise ValueError(f"bad SMPTE timecode '{value}': frame {frame} is out of range for {fps:g} fps (0-{whole_fps - 1})")
        # Non-drop-frame: the timecode counts whole_fps frames per timecode-second, so the real
        # time is the total frame count over the true rate (at 29.97 an hour of timecode is
        # 3596.4 s of video). This is exactly what fmt_smpte_time() inverts; before, the two
        # disagreed by ~0.1 % on the fractional NTSC rates and drifted apart over long files.
        total_frames = (int(h) * 3600 + int(m) * 60 + int(s)) * whole_fps + frame
        return total_frames / fps
    if len(parts) > 3:
        raise ValueError(f"bad time: {value}")
    total = 0.0
    for part in parts:
        try:
            total = total * 60 + float(part)
        except ValueError:
            # not the interpreter's "could not convert string to float: 'zz'" (review 9)
            raise ValueError(f"'{value}': not a time")
    return total


def time_arg(value: str, flag: str, fps: Optional[float] = None) -> float:
    """parse_time() for a command-line flag: SMPTE hh:mm:ss:ff resolves with the input's fps when
    the caller has one, and every parse failure is a `kind: input` refusal naming the flag (so
    `--json` callers get a failure document, never a traceback)."""
    try:
        return parse_time(value, fps)
    except MissingFpsError as e:
        die(f"{flag} {value!r}: {e}")
    except ValueError as e:
        die(f"{flag} {value!r}: {e} (use seconds, mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff at the source's fps or with an explicit @fps suffix)")
    return 0.0  # unreachable


def signed_time_arg(value: str, flag: str, fps: Optional[float] = None) -> float:
    """time_arg() for a flag that may also be negative (an offset, not a point in time): a single
    leading '-'/'+' is taken as the sign and the rest goes through the ordinary time grammar, so
    `--offset -00:00:02`, `--offset -1.5` and `--offset 0:02` all mean what they read as."""
    text = (value or "").strip()
    sign = 1.0
    if text[:1] in "+-":
        sign = -1.0 if text[0] == "-" else 1.0
        text = text[1:].strip()
    if not text:
        die(f"{flag} {value!r}: not a time (use seconds, mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff)")
    return sign * time_arg(text, flag, fps)


def fmt_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_smpte_time(seconds: float, fps: float) -> str:
    """SMPTE non-drop-frame timecode 'hh:mm:ss:ff' for a real fps (not the fractional NTSC rates
    -- 29.97/59.94 need drop-frame counting to stay wall-clock accurate, which this does not do)."""
    if seconds < 0:
        seconds = 0.0
    whole_fps = int(round(fps))
    total_frames = int(round(seconds * fps))
    frame = total_frames % whole_fps
    secs_total = total_frames // whole_fps
    h, rem = divmod(secs_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{frame:02d}"


def escape_filter_path(path: str) -> str:
    """Escape a file path for use as a filter option value (subtitles=, ass=, lut3d=file=, fontfile=, fontsdir=).

    A filter option value is parsed twice: the graph parser splits filters on `,` / `;` and options
    on `:`, then the filter's own option parser splits key=value pairs on `:` again. A character that
    must survive both passes needs two levels of escaping, so a Windows drive letter `D:/x.srt` is
    written `D\\\\:/x.srt`; with a single backslash the second pass still splits at the colon and
    ffmpeg reads `/x.srt` as the next option (`Unable to parse "original_size" option value`).
    Backslashes are turned into forward slashes first (ffmpeg accepts them on Windows), so a backslash
    never has to be escaped itself; `,`, `;`, `[` and `]` are graph-level characters and survive with
    one backslash. `'` is special: the graph parser also treats a quote as the start of a quoted
    token, so a single `\\'` is consumed by the first pass and "Ryo's Mac/cues.srt" reaches the
    filter as "Ryos Mac/cues.srt" (Unable to open ...). Three backslashes survive both passes
    (measured on 6.1 and 7.1 with subtitles=, ass= and lut3d=file=).
    """
    if os.path.isfile(path) and path not in STATE.plan_inputs:
        STATE.plan_inputs.append(path)  # a plan binds subtitle/LUT/font files too (review 6)
    p = str(Path(path))
    p = p.replace("\\", "/")
    p = p.replace(":", "\\\\:")
    p = p.replace("'", "\\\\\\'")
    for ch in (",", ";", "[", "]"):
        p = p.replace(ch, "\\" + ch)
    return p


def cfr_args(meta: Optional[Dict[str, Any]], fps: Optional[float] = None) -> List[str]:
    """Force a constant frame rate on output when the source looks VFR (or fps is given).

    VFR sources (phone/screen recordings) drift against audio after cuts and joins,
    so every re-encoding script passes this to conform them automatically.
    """
    v = (meta or {}).get("video") or {}
    if fps is None and not v.get("variable_frame_rate_suspected"):
        return []
    rate = fps or v.get("fps") or 30.0
    rate = round(rate) if abs(rate - round(rate)) < 0.02 else rate
    return ["-fps_mode", "cfr", "-r", f"{rate:g}"]


def encoder_args(codec: str, crf: int, preset: str, meta: Optional[Dict[str, Any]] = None, keep_bt709: bool = True) -> List[str]:
    """The one place that turns (--codec, --quality, --preset, source) into encoder options.

    h264 -> x264 8-bit BT.709 (refuses HDR: 8-bit H.264 cannot carry it); hevc -> x265, Main10
    with the source's tags for HDR, 8-bit BT.709 otherwise; av1 -> SVT-AV1 (libaom fallback),
    10-bit for HDR; prores -> ProRes 422 HQ, source tags kept. 1.8: chosen by --codec; without
    it video_args() does what it always did (x264 for SDR, x265 Main10 for HDR).
    """
    v = (meta or {}).get("video") or {}
    hdr = bool(v.get("hdr"))
    cs = v.get("color_space") or "bt2020nc"
    prim = v.get("color_primaries") or "bt2020"
    trc = v.get("color_transfer") or "arib-std-b67"
    hdr_tags = ["-colorspace", cs, "-color_primaries", prim, "-color_trc", trc]
    if codec == "h264":
        if hdr:
            die(f"--codec h264 cannot carry HDR ({v.get('hdr_format') or 'BT.2020'}): 8-bit H.264 is SDR only",
                hint="run color.py --to-sdr first, or use --codec hevc / av1 / prores, which keep the source's HDR")
        return _x264_raw(crf, preset, keep_bt709)
    if codec == "hevc":
        if hdr:
            x265 = f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}:range=limited:hdr10-opt=1" if trc == "smpte2084" else f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}"
            return ["-c:v", "libx265", "-preset", preset, "-crf", str(min(51, crf + 2)), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
                    "-x265-params", x265] + hdr_tags + ["-movflags", "+faststart"]
        params, extra = _sdr_bt709("libx265") if keep_bt709 else ("", [])
        return ["-c:v", "libx265", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-x265-params", "log-level=error" + (":" + params if params else "")] + extra + ["-movflags", "+faststart"]
    if codec == "av1":
        pix = "yuv420p10le" if hdr else "yuv420p"
        if "libsvtav1" in ffmpeg_encoders():
            args = ["-c:v", "libsvtav1", "-preset", str(SVT_PRESET.get(preset, 6)), "-crf", str(min(63, crf)), "-pix_fmt", pix]
            if hdr:
                args += hdr_tags
            elif keep_bt709:
                params, extra = _sdr_bt709("libsvtav1")
                args += (["-svtav1-params", params] if params else []) + extra
        elif "libaom-av1" in ffmpeg_encoders():
            args = ["-c:v", "libaom-av1", "-crf", str(min(63, crf)), "-b:v", "0", "-cpu-used", "6", "-row-mt", "1", "-pix_fmt", pix]
            args += hdr_tags if hdr else (_sdr_bt709("libaom-av1")[1] if keep_bt709 else [])
        else:
            die("--codec av1 needs an AV1 encoder (libsvtav1 or libaom-av1) and this ffmpeg build has neither", kind="missing_tool",
                hint="install an ffmpeg built with SVT-AV1 (most distribution builds are), or use --codec hevc")
        return args + ["-movflags", "+faststart"]
    if codec == "prores":
        if "prores_ks" not in ffmpeg_encoders():
            die("--codec prores needs the prores_ks encoder and this ffmpeg build lacks it", kind="missing_tool")
        return ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"] + (hdr_tags if hdr else [])
    die(f"unknown --codec {codec!r} (one of {', '.join(CODECS)})")
    return []


def _x264_raw(crf: int, preset: str, keep_bt709: bool = True) -> List[str]:
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if keep_bt709:
        args += bt709_tag_args("libx264")
    return args


def x264_args(crf: int = 18, preset: str = "medium", keep_bt709: bool = True) -> List[str]:
    """SDR H.264 encoder args -- or, when --codec named another encoder, that encoder's SDR args
    (color.py's --to-sdr path builds its own H.264 line; the flag still has to reach it)."""
    if STATE.codec and STATE.codec != "h264":
        return encoder_args(STATE.codec, crf, preset, None, keep_bt709)
    return _x264_raw(crf, preset, keep_bt709)


def video_args(meta: Optional[Dict[str, Any]], crf: int = 18, preset: str = "medium") -> List[str]:
    """Encoder args that preserve what the source is.

    SDR sources -> H.264 8-bit tagged BT.709 (x264_args). HDR sources (HDR10/PQ, HLG,
    Dolby Vision base layer, BT.2020) -> HEVC Main10 with the source's own colour tags,
    so cutting/captioning/fitting an iPhone HDR clip stays HDR instead of becoming a
    washed-out file mislabelled as BT.709. Use color.py --to-sdr when SDR is wanted.
    """
    if STATE.codec:
        return encoder_args(STATE.codec, crf, preset, meta)
    v = (meta or {}).get("video") or {}
    if not v.get("hdr"):
        return x264_args(crf, preset)
    cs = v.get("color_space") or "bt2020nc"
    prim = v.get("color_primaries") or "bt2020"
    trc = v.get("color_transfer") or "arib-std-b67"
    x265 = f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}:range=limited:hdr10-opt=1" if trc == "smpte2084" else f"log-level=error:colorprim={prim}:transfer={trc}:colormatrix={cs}"
    return ["-c:v", "libx265", "-preset", preset, "-crf", str(min(51, crf + 2)), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
            "-x265-params", x265, "-colorspace", cs, "-color_primaries", prim, "-color_trc", trc, "-movflags", "+faststart"]


def aac_args(bitrate: str = "192k") -> List[str]:
    return ["-c:a", "aac", "-b:a", bitrate]


AUDIO_CODECS = {
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
    ".m4a": ["-c:a", "aac", "-b:a", "256k"],
    ".aac": ["-c:a", "aac", "-b:a", "256k"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


def audio_codec_for(output_path: str, default_bitrate: str = "192k") -> List[str]:
    """Pick an audio codec that the output container can actually hold."""
    ext = os.path.splitext(output_path)[1].lower()
    return list(AUDIO_CODECS.get(ext, ["-c:a", "aac", "-b:a", default_bitrate]))


def is_audio_output(output_path: str) -> bool:
    """True when the output extension is an audio-only container (.wav, .flac, .mp3, .m4a, .aac, .ogg, .opus).

    Such a file cannot hold a video stream and, for .wav, cannot hold compressed audio: scripts use
    this to drop the picture (-vn) and to pick the codec from the extension instead of AAC.
    """
    return os.path.splitext(output_path)[1].lower() in AUDIO_CODECS


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


BRAND_DEFAULTS: Dict[str, Any] = {
    "font": "DejaVu Sans",
    "font_file": None,
    "colors": {"primary": "FFD200", "text": "FFFFFF", "outline": "000000", "background": "101418", "accent": "1E6F8E"},
    "logo": None,
    "logo_position": "top-right",
    "logo_scale": 160,
    "logo_opacity": 0.9,
    "safe_margin": 48,
    "caption": {"size": 26, "position": "bottom", "animate": "pop", "karaoke": False, "bold": True, "outline": 2},
    # 1.12: one place for the caption look every project shares. `styles.caption` is the documented
    # spelling (`{font, size, colour, box, position}`, British or American "colour"); the older
    # top-level `caption` block still works and `styles.caption` wins where both name the same key.
    "styles": {},
    "lang": None,
    "loudness": {"lufs": -14, "tp": -1},
}


def load_brand(path: Optional[str]) -> Dict[str, Any]:
    """Load brand.json (fonts, colours, logo, safe margins, caption defaults); missing keys fall back to defaults."""
    import copy
    brand = copy.deepcopy(BRAND_DEFAULTS)
    brand["_stated"] = {}
    if not path:
        return brand
    if not os.path.exists(path):
        die(f"brand file not found: {path}")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        die(f"brand file is not valid JSON: {exc}")
    base = Path(path).resolve().parent
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(brand.get(k), dict):
            brand[k].update(v)
        else:
            brand[k] = v
    for key in ("logo", "font_file"):
        if brand.get(key) and not os.path.isabs(brand[key]):
            brand[key] = str(base / brand[key])
    brand["_path"] = str(path)
    # What the FILE said, separate from BRAND_DEFAULTS' filler: a brand.json that never mentions
    # a font must not read as "the caller chose a font" (which would switch font-by-script off).
    brand["_stated"] = data
    return brand


def brand_states_font(brand: Dict[str, Any]) -> bool:
    """Did the brand FILE actually name a font (top-level `font`, `caption.font` or
    `styles.caption.font`)? BRAND_DEFAULTS always supplies one, so the merged document can never
    answer this -- and treating the default filler as the caller's choice switched font-by-script
    off for every branded job (review 10)."""
    stated = brand.get("_stated") or {}
    if stated.get("font"):
        return True
    for block in (stated.get("caption"), (stated.get("styles") or {}).get("caption")):
        if isinstance(block, dict) and block.get("font"):
            return True
    return False


def brand_caption_style(brand: Dict[str, Any]) -> Dict[str, Any]:
    """The effective caption style of a brand file: the top-level `caption` block updated with
    `styles.caption`, with `colour` normalised to `color`. Explicit flags still beat both."""
    style: Dict[str, Any] = dict(brand.get("caption") or {})
    extra = (brand.get("styles") or {}).get("caption") or {}
    style.update(extra)
    if "colour" in style and "color" not in style:
        style["color"] = style.pop("colour")
    style.pop("colour", None)
    return style


# ------------------------------------------------------------------- chapter proposal (1.16)

def fmt_chapter_time(t: float) -> str:
    """The YouTube description convention: `00:00`, `03:12`, `1:02:03` past the hour, always
    rounded DOWN to the second so the timestamp never lands after the moment it names."""
    total = max(0, int(t))
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _evidence_rank(ev: Dict[str, Any]) -> tuple:
    """How strong a candidate is, for the drop order: both detectors beat a silence, a silence
    beats a scene cut, and within a kind the longer pause / higher score wins."""
    kind = ev.get("kind")
    tier = {"start": 3, "silence+scene": 2, "silence": 1, "scene": 0}.get(kind, 0)
    within = float(ev.get("silence_length") or ev.get("score") or 0.0)
    return (tier, within)


def propose_chapters(duration: float, silences: "Sequence", scene_cuts: "Sequence", *,
                     min_chapter: float = 60.0, max_chapters: int = 0,
                     source: str = "both") -> "List[Dict[str, Any]]":
    """Chapter markers proposed from measured structure. Pure: the detectors' outputs go in,
    a list of `{"at", "title", "evidence"}` comes out, and nothing is decoded here.

    A chapter starts where speech RESUMES, so a silence contributes its `end`, not its midpoint.
    A scene cut within 1 s of such a point is the same event seen twice and is merged into one
    candidate with `kind: "silence+scene"`, which the `--max-chapters` cap never drops before a
    single-evidence one. Candidates closer than `min_chapter` to the one already kept are dropped,
    stronger evidence winning; so is anything inside `min_chapter` of the end of the file.

    Every title is `Chapter N`. The function never looks at, and never invents, content: naming a
    chapter needs knowing what is said in it, which is the calling agent's job, not this skill's.
    """
    duration = float(duration or 0.0)
    min_chapter = max(0.0, float(min_chapter))
    candidates: "List[Dict[str, Any]]" = []
    if source in ("silence", "both"):
        for span in silences or []:
            start, end = float(span[0]), span[1]
            if end is None or end == float("inf"):
                continue
            end = float(end)
            candidates.append({"at": end, "evidence": {
                "kind": "silence", "silence": [round(start, 3), round(end, 3)],
                "silence_length": round(end - start, 3)}})
    if source in ("scenes", "both"):
        for cut in scene_cuts or []:
            cut = float(cut)
            if cut <= 0.0:
                continue     # scenes.py always reports 0.0 as the first cut; that is the start
            candidates.append({"at": cut, "evidence": {"kind": "scene", "scene_at": round(cut, 3)}})

    # merge a scene cut that stands within 1 s of a silence end: one event, two witnesses
    candidates.sort(key=lambda c: c["at"])
    merged: "List[Dict[str, Any]]" = []
    for cand in candidates:
        prior = merged[-1] if merged else None
        if prior and abs(cand["at"] - prior["at"]) <= 1.0 and \
                {prior["evidence"]["kind"], cand["evidence"]["kind"]} == {"silence", "scene"}:
            ev = dict(prior["evidence"])
            ev.update(cand["evidence"])
            ev["kind"] = "silence+scene"
            silence_first = prior["evidence"]["kind"] == "silence"
            prior["at"] = prior["at"] if silence_first else cand["at"]
            prior["evidence"] = ev
            continue
        merged.append(dict(cand))

    kept: "List[Dict[str, Any]]" = [{"at": 0.0, "evidence": {"kind": "start"}}]
    for cand in merged:
        if duration and cand["at"] >= duration - min_chapter:
            continue
        last = kept[-1]
        if cand["at"] - last["at"] < min_chapter:
            # too close to the marker already kept: keep whichever the evidence supports better,
            # never replacing the 0.0 start
            if last["evidence"]["kind"] != "start" and \
                    _evidence_rank(cand["evidence"]) > _evidence_rank(last["evidence"]) and \
                    (len(kept) < 2 or cand["at"] - kept[-2]["at"] >= min_chapter):
                kept[-1] = dict(cand)
            continue
        kept.append(dict(cand))

    if max_chapters and len(kept) > max_chapters:
        # drop the weakest evidence first, never index 0, then put the survivors back in order
        order = sorted(range(1, len(kept)),
                       key=lambda i: (_evidence_rank(kept[i]["evidence"]), -kept[i]["at"]))
        drop = set(order[:len(kept) - max_chapters])
        kept = [c for i, c in enumerate(kept) if i not in drop]

    for n, chapter in enumerate(kept, start=1):
        chapter["at"] = round(chapter["at"], 3)
        chapter["title"] = f"Chapter {n}"
    return kept


def description_block(chapters: "Sequence") -> str:
    """The YouTube description form of a chapter list: `00:00 Chapter 1` per line."""
    return "\n".join(f"{fmt_chapter_time(c['at'])} {c['title']}" for c in chapters)
