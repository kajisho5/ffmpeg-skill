"""render.py project -> an editor's timeline (EDL, FCPXML, OTIO).

`render.py project.json --export-timeline edit.fcpxml|.edl|.otio` hands a rough cut to a person
who finishes it in Premiere, DaVinci Resolve or Final Cut. It is a translation, not a render:
nothing is encoded, and every decision in the file is one the project already made.

The timeline has to match what render.py itself would deliver, or the editor opens a different
cut than the agent showed. join.py's crossfade overlaps neighbouring clips by the transition
duration `d` (xfade: the last `d` s of A blend with the first `d` s of B, so the whole is `d`
shorter). Editors model a dissolve centred on a cut, using media beyond each clip's visible
range ("handles"), so each side of a dissolve is trimmed by `d/2` and the dissolve spans `d/2`
either side of the new cut: the same frames blend over the same span, and the total length is
the rendered one.

Only what an editor timeline can carry is exported: clips (with in/out and speed), the
transition between them, a music bed on its own audio track, and chapters as markers, on a
sequence of the project's frame (sized by the rule fit.py renders it with). FCPXML also states
how a clip of another aspect fills that frame (`adjust-conform`); EDL and OTIO cannot.
Everything else in the project -- captions, graphics, overlays, the silence cut, fit/crop, a
reframe the format cannot state, audio processing, loudness, the export preset -- is listed
under `not_exported`, never silently dropped.
"""
import json
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as _xml_escape

from _common.decision import MissingFpsError, aspect_ratio, frame_size, parse_time

FORMATS = {".edl": "edl", ".fcpxml": "fcpxml", ".otio": "otio"}
# Common NTSC rates are stored as the exact ratio an editor expects, not as 29.97.
_NTSC = {23.976: Fraction(24000, 1001), 29.97: Fraction(30000, 1001), 59.94: Fraction(60000, 1001),
         47.952: Fraction(48000, 1001), 119.88: Fraction(120000, 1001)}
# project keys an editor timeline cannot carry, with what the caller should know about each
_NOT_EXPORTED = {
    "silence": "the silence cut (render.py measures it at render time; the timeline keeps the clips whole)",
    "captions": "captions (burn them with render.py, or import the .srt into the editor)",
    "graphics": "graphics (titles, lower thirds, social templates)",
    "overlays": "overlays (logos and text)",
    "fit": "fit / reframe to the delivery aspect (set the sequence frame in the editor)",
    "audiogram": "the audiogram picture",
    "loudness": "loudness normalisation",
    "export": "the export preset (the editor's own export decides the delivery)",
    "check": "the platform check",
    "brand": "brand styles",
    "snap": "beat snapping (the timeline uses the project's in/out as written, before any snap)",
}
# frame.fit -> the FCPXML adjust-conform type that fills the sequence the same way. blur has no
# conform of its own: the picture is fitted whole, and its blurred background is not exported.
_CONFORM = {"pad": "fit", "crop": "fill", "blur": "fit"}
_AUDIO_NOT_EXPORTED = ("replace", "voice", "denoise", "duck", "duck_amount", "duck_threshold", "duck_attack",
                       "duck_release", "gain", "stereo", "mono", "downmix", "stereo_widen", "effects",
                       "effects_volume", "stems", "music_volume", "fade_in", "fade_out", "music_fade_out",
                       "music_loop")


class TimelineError(ValueError):
    """A project that cannot be expressed as a timeline (a caller-facing `kind: input`)."""


def exact_rate(fps: float) -> Fraction:
    for approx, exact in _NTSC.items():
        if abs(fps - approx) < 0.01:
            return exact
    frac = Fraction(fps).limit_denominator(1001)
    if frac <= 0:
        raise TimelineError(f"frame rate {fps!r} is not usable for a timeline")
    return frac


def _number(value: Any, what: str) -> float:
    """A numeric project value (a rate, a size, a speed, a transition length) as a float, or a
    TimelineError naming it -- never float()'s traceback."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        raise TimelineError(f"{what}: {value!r} is not a number")
    return number


def _seconds(value: Any, what: str, fps: Optional[float]) -> float:
    """A project time read with the grammar render.py's own stages read it (time_arg()): seconds,
    mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff at `fps` or its own @fps. A value it refuses is a
    TimelineError, so `--json` gets a `kind: input` document, not a traceback and empty stdout."""
    try:
        seconds = parse_time(str(value), fps)
    except MissingFpsError as exc:
        raise TimelineError(f"{what}: {exc}")
    except ValueError as exc:
        raise TimelineError(f"{what}: {exc} (use seconds, mm:ss, hh:mm:ss.ms, or hh:mm:ss:ff at the "
                            "source's fps or with an explicit @fps suffix)")
    if not math.isfinite(seconds):
        raise TimelineError(f"{what}: {value!r} is not a time")
    return seconds


def _picture(meta: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """A source's displayed width x height (rotation metadata swaps them, as fit.py reads it)."""
    video = meta.get("video") or {}
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    if not (w and h):
        return None
    return (h, w) if video.get("rotation") in (90, -90, 270, -270) else (w, h)


def build(proj: Dict[str, Any], probes: Dict[str, Dict[str, Any]], rel) -> Dict[str, Any]:
    """The editor-neutral timeline: every time in frames at `rate`.

    `probes` maps each resolved clip/music path to its probe(); `rel` resolves a project path
    the way render.py does. Raises TimelineError for what an editor timeline cannot represent."""
    clips_in = proj.get("clips") or []
    if not clips_in:
        raise TimelineError("project.clips is empty")
    for i, c in enumerate(clips_in):
        if not isinstance(c, dict) or not c.get("src"):
            raise TimelineError(f"clips[{i}]: no src")
    frame = proj.get("frame") or {}
    first = probes[rel(clips_in[0]["src"])]
    frame_fps = _number(frame["fps"], "frame.fps") if frame.get("fps") else None
    fps = frame_fps or (first.get("video") or {}).get("fps")
    if not fps:
        raise TimelineError("no frame rate: the first clip has no video stream and project.frame.fps is not set")
    rate = exact_rate(float(fps))
    # The sequence is the project's frame sized by fit.py's rule (render.py has already filled an
    # aspect-only frame from the export preset), so {aspect 16:9, width 1920} is 1920x1080
    # whatever the source's height -- the size the render's fit stage delivers. No frame at all
    # is the first clip's own picture, which is what the render keeps.
    aspect = frame.get("aspect")
    ratio = aspect_ratio(aspect) if aspect else None
    if aspect and ratio is None:
        raise TimelineError(f"frame.aspect {aspect!r}: use W:H with whole numbers, like 16:9 (fit.py refuses it too)")
    want_w, want_h = (int(_number(frame[k], f"frame.{k}")) if frame.get(k) else None for k in ("width", "height"))
    if (want_w or 0) < 0 or (want_h or 0) < 0:
        raise TimelineError(f"frame width/height must be positive, got {frame.get('width')!r} x {frame.get('height')!r}")
    src_w, src_h = _picture(first) or (1920, 1080)
    if ratio is None and not want_w and not want_h:
        width, height = src_w, src_h
    else:
        width, height = frame_size(ratio, want_w, want_h, src_w, src_h)
    fit_mode = str(frame.get("fit") or "pad")
    if fit_mode not in _CONFORM:
        raise TimelineError(f"frame.fit {frame.get('fit')!r}: use pad, crop or blur (fit.py's --fit)")

    def fr(seconds: float) -> int:
        return int(round(Fraction(seconds).limit_denominator(1000000) * rate))

    trans = proj.get("transition") or {}
    t_type = str(trans.get("type", "fade")) if len(clips_in) > 1 else "none"
    d_frames = 0 if t_type == "none" else fr(_number(trans.get("duration", 0.5), "transition.duration"))
    notes: List[str] = []
    if d_frames and t_type != "fade":
        notes.append(f'transition "{t_type}" is exported as a cross dissolve: editors do not share xfade\'s other patterns')

    clips: List[Dict[str, Any]] = []
    reframed: List[str] = []
    for i, c in enumerate(clips_in):
        src = rel(c["src"])
        meta = probes[src]
        dur = float(meta.get("duration") or 0.0)
        # in/out are on the source's own clock, as cut.py reads them: hh:mm:ss:ff at the
        # source's fps, never frame.fps. A clip with no picture has no fps, and cut.py takes no
        # other, so its hh:mm:ss:ff needs an @fps suffix here as in the render.
        clip_fps = (meta.get("video") or {}).get("fps")
        start = _seconds(c["in"], f"clips[{i}].in", clip_fps) if c.get("in") is not None else 0.0
        if start < 0:
            raise TimelineError(f"clips[{i}].in must not be negative, got {c['in']!r}")
        end = _seconds(c["out"], f"clips[{i}].out", clip_fps) if c.get("out") is not None else dur
        if end <= start:
            raise TimelineError(f"clip {i}: out ({end:g}) is not after in ({start:g})")
        speed = _number(c.get("speed") or 1.0, f"clips[{i}].speed")
        if not speed > 0:
            raise TimelineError(f"clip {i}: speed must be positive, got {c.get('speed')!r}")
        picture = _picture(meta)
        reframe = bool(picture and abs(Fraction(*picture) - Fraction(width, height)) > Fraction(1, 100))
        if reframe:
            reframed.append(os.path.basename(src))
        src_in, src_out = fr(start), fr(end)
        clips.append({"index": i, "src": os.path.abspath(src), "name": os.path.basename(src),
                      "src_in": src_in, "src_out": src_out, "speed": speed,
                      "length": int(round((src_out - src_in) / speed)),
                      "media_frames": fr(dur), "has_video": bool(meta.get("video")),
                      "has_audio": bool(meta.get("audio")),
                      "picture": picture, "fps": clip_fps, "reframed": reframe})

    # Centre each dissolve on the cut: trim d/2 off the outgoing tail and d/2 off the incoming head.
    half_a, half_b = d_frames // 2, d_frames - d_frames // 2
    for i, c in enumerate(clips):
        c["trim_head"] = half_b if (i > 0 and d_frames) else 0
        c["trim_tail"] = half_a if (i < len(clips) - 1 and d_frames) else 0
        visible = c["length"] - c["trim_head"] - c["trim_tail"]
        if visible <= 0:
            raise TimelineError(f"clip {c['index']} ({c['name']}) is shorter than its transitions")
        c["visible"] = visible
    pos = 0
    for c in clips:
        c["record_in"] = pos
        pos += c["visible"]
    total = pos

    music = None
    audio = proj.get("audio") or {}
    if audio.get("music"):
        msrc = rel(audio["music"])
        mmeta = probes[msrc]
        mlen = min(fr(float(mmeta.get("duration") or 0.0)), total)
        if mlen > 0:
            music = {"src": os.path.abspath(msrc), "name": os.path.basename(msrc), "length": mlen,
                     "media_frames": fr(float(mmeta.get("duration") or 0.0))}
        if audio.get("music_loop"):
            notes.append("music_loop is not exported: the bed plays once, up to the timeline's length")

    markers: List[Dict[str, Any]] = []
    chapters = proj.get("chapters")
    if isinstance(chapters, list):
        for j, ch in enumerate(chapters):
            # read as render.py's chapters stage reads it (metadata.py): a chapter list carries
            # no fps, so hh:mm:ss:ff needs its @fps there and here alike
            at = fr(_seconds(ch.get("at", 0), f"chapters[{j}].at", None))
            if 0 <= at < total:
                markers.append({"at": at, "title": str(ch.get("title") or "")})
    elif chapters:
        notes.append("chapters given as a file are not exported as markers; write them inline as [{at, title}]")

    # A clip of another aspect than the sequence is a reframe: whether the file can state it
    # depends on the format, so summary() adds it to not_exported per format (_reframe_note).
    not_exported = [text for key, text in _NOT_EXPORTED.items() if proj.get(key)]
    dropped_audio = sorted(k for k in _AUDIO_NOT_EXPORTED if audio.get(k) not in (None, False, "", 0) and k != "music")
    if dropped_audio:
        not_exported.append("audio processing: " + ", ".join(dropped_audio))
    return {"name": Path(str(proj.get("output") or "timeline")).stem, "rate": rate, "width": width, "height": height,
            "fit": fit_mode, "reframed": list(dict.fromkeys(reframed)),
            "clips": clips, "transition": t_type if d_frames else "none", "transition_frames": d_frames,
            "music": music, "markers": markers, "total": total, "notes": notes, "not_exported": not_exported}


def _reframe_note(tl: Dict[str, Any], fmt: str) -> List[str]:
    """What `not_exported` says about the clips whose picture has another aspect than the
    sequence. FCPXML states each one's spatial conform (adjust-conform: fit for frame.fit pad,
    fill for crop), so there only blur's blurred background is missing; EDL and OTIO have no
    field for a conform at all, so the editor's own default decides and the caller is told."""
    if not tl["reframed"]:
        return []
    names = ", ".join(tl["reframed"])
    if fmt == "fcpxml":
        if tl["fit"] != "blur":
            return []
        return [f"frame.fit blur's blurred background behind {names}: the FCPXML fits the picture into "
                f"{tl['width']}x{tl['height']} (adjust-conform fit), leaving bars where the render blurs"]
    return [f"the reframe to {tl['width']}x{tl['height']} (frame.fit {tl['fit']}) of {names}: "
            "set the clips' spatial conform in the editor (fit = pad, fill = crop)"]


# ---------------------------------------------------------------------------------------- EDL
def _tc(frames: int, fps_int: int) -> str:
    h, rem = divmod(frames, fps_int * 3600)
    m, rem = divmod(rem, fps_int * 60)
    s, f = divmod(rem, fps_int)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def to_edl(tl: Dict[str, Any]) -> str:
    """CMX 3600, non-drop timecode at the nominal integer rate, record starting at 01:00:00:00.
    Every event is reel AX (the convention for file-based media) with the file named in
    FROM CLIP NAME / SOURCE FILE comments, which Premiere and Resolve both relink from. A speed
    change is an M2 line. A dissolve is the standard pair: a zero-length cut on the outgoing
    source where its event ended, then a D event that brings the incoming clip in over `d`
    frames starting at the incoming clip's own in point -- so each event's record range runs
    from where the previous one stopped to where the next dissolve begins."""
    fps_int = int(round(float(tl["rate"])))
    hour = fps_int * 3600
    clips = tl["clips"]
    d = tl["transition_frames"]
    # record range of each event: starts `trim_head` before its visible start (the dissolve
    # window), ends where the next event starts
    starts = [c["record_in"] - c["trim_head"] for c in clips]
    ends = starts[1:] + [tl["total"]]
    lines = [f"TITLE: {tl['name']}", "FCM: NON-DROP FRAME", ""]
    n = 0
    prev_src_end = 0
    for i, c in enumerate(clips):
        n += 1
        chan = "B" if c["has_audio"] and c["has_video"] else ("V" if c["has_video"] else "A")
        rec_in, rec_out = hour + starts[i], hour + ends[i]
        s_in = c["src_in"]
        s_out = s_in + int(round((ends[i] - starts[i]) * c["speed"]))
        if i > 0 and d:
            lines.append(f"{n:03d}  AX       {chan:<5} C        {_tc(prev_src_end, fps_int)} {_tc(prev_src_end, fps_int)} "
                         f"{_tc(rec_in, fps_int)} {_tc(rec_in, fps_int)}")
            lines.append(f"{n:03d}  AX       {chan:<5} D    {d:03d} {_tc(s_in, fps_int)} {_tc(s_out, fps_int)} "
                         f"{_tc(rec_in, fps_int)} {_tc(rec_out, fps_int)}")
            lines.append(f"* FROM CLIP NAME: {clips[i - 1]['name']}")
            lines.append(f"* TO CLIP NAME: {c['name']}")
        else:
            lines.append(f"{n:03d}  AX       {chan:<5} C        {_tc(s_in, fps_int)} {_tc(s_out, fps_int)} "
                         f"{_tc(rec_in, fps_int)} {_tc(rec_out, fps_int)}")
            lines.append(f"* FROM CLIP NAME: {c['name']}")
        lines.append(f"* SOURCE FILE: {c['src']}")
        if abs(c["speed"] - 1.0) > 1e-6:
            lines.append(f"M2   AX       {fps_int * c['speed']:05.1f}                {_tc(s_in, fps_int)}")
        lines.append("")
        prev_src_end = s_out
    if tl["music"]:
        n += 1
        m = tl["music"]
        lines.append(f"{n:03d}  AX       A2    C        {_tc(0, fps_int)} {_tc(m['length'], fps_int)} "
                     f"{_tc(hour, fps_int)} {_tc(hour + m['length'], fps_int)}")
        lines.append(f"* FROM CLIP NAME: {m['name']}")
        lines.append(f"* SOURCE FILE: {m['src']}")
        lines.append("")
    for mk in tl["markers"]:
        lines.append(f"* LOC: {_tc(hour + mk['at'], fps_int)} WHITE   {mk['title']}")
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------------------- FCPXML
def _t(frames: int, rate: Fraction) -> str:
    """A rational FCPXML time: frames at `rate`, as `N/Ds` (or `Ns` when whole)."""
    value = Fraction(frames) / rate
    return f"{value.numerator}s" if value.denominator == 1 else f"{value.numerator}/{value.denominator}s"


def _url(path: str) -> str:
    # pathlib builds the percent-encoded file:// URL itself (and the drive-letter form on
    # Windows): no network-library import in scripts/, not even for quoting (see the no-fetch test)
    return Path(os.path.abspath(path)).as_uri()


def to_fcpxml(tl: Dict[str, Any]) -> str:
    """FCPXML 1.10 (Final Cut Pro 10.6+, DaVinci Resolve): one library/event/project, a spine of
    asset-clips with cross dissolves between them, the music bed as a connected clip on lane -1
    of the first clip, chapters as chapter-markers. Speed is a linear timeMap on the clip. The
    sequence has its own format (r1); each video asset has its source's, and a clip of another
    aspect states its spatial conform (adjust-conform) for frame.fit."""
    rate = tl["rate"]
    q = lambda s: _xml_escape(str(s), {'"': "&quot;"})  # noqa: E731
    fd = _t(1, rate)
    res: List[str] = []
    ids: Dict[Any, str] = {}  # a format's (width, height, frameDuration) or an asset's path -> its id

    def fmt(width: int, height: int, frame_duration: str) -> str:
        key = (width, height, frame_duration)
        if key not in ids:
            ids[key] = f"r{len(ids) + 1}"
            res.append(f'    <format id="{ids[key]}" name="FFVideoFormat{height}p" frameDuration="{frame_duration}" '
                       f'width="{width}" height="{height}"/>')
        return ids[key]

    seq_fmt = fmt(tl["width"], tl["height"], fd)  # r1: the sequence's frame

    def clip_fmt(c: Dict[str, Any]) -> str:
        # An asset describes its own media, not the sequence: with every asset on r1, a 320x180
        # file under a 1080x1920 frame claimed to be 1080x1920, and its conform had nothing to do.
        if not (c["has_video"] and c["picture"]):
            return seq_fmt
        return fmt(c["picture"][0], c["picture"][1], _t(1, exact_rate(float(c["fps"]))) if c["fps"] else fd)

    def asset(path: str, name: str, frames: int, has_video: bool, has_audio: bool, format_id: str = "") -> str:
        if path in ids:
            return ids[path]
        rid = f"r{len(ids) + 1}"
        ids[path] = rid
        res.append(f'    <asset id="{rid}" name="{q(name)}" start="0s" duration="{_t(frames, rate)}" '
                   f'hasVideo="{int(has_video)}" hasAudio="{int(has_audio)}"'
                   + (f' format="{format_id}"' if has_video else "") + ' audioSources="1" audioChannels="2">\n'
                   f'      <media-rep kind="original-media" src="{q(_url(path))}"/>\n    </asset>')
        return rid

    spine: List[str] = []
    d = tl["transition_frames"]
    markers = list(tl["markers"])
    for i, c in enumerate(tl["clips"]):
        cid = clip_fmt(c)
        rid = asset(c["src"], c["name"], c["media_frames"], c["has_video"], c["has_audio"], cid)
        if i > 0 and d:
            spine.append(f'        <transition name="Cross Dissolve" offset="{_t(c["record_in"] - c["trim_head"], rate)}" '
                         f'duration="{_t(d, rate)}"/>')
        src_start = c["src_in"] + int(round(c["trim_head"] * c["speed"]))
        inner: List[str] = []
        if abs(c["speed"] - 1.0) > 1e-6:
            # timeMap maps clip-local time to source time; two linear points give a constant speed
            inner.append("          <timeMap>")
            inner.append(f'            <timept time="0s" value="{_t(src_start, rate)}" interp="linear"/>')
            inner.append(f'            <timept time="{_t(c["visible"], rate)}" '
                         f'value="{_t(src_start + int(round(c["visible"] * c["speed"])), rate)}" interp="linear"/>')
            inner.append("          </timeMap>")
            start_attr = "0s"
        else:
            start_attr = _t(src_start, rate)
        local0 = src_start if abs(c["speed"] - 1.0) <= 1e-6 else 0
        # the FCPXML 1.10 DTD's order inside an asset-clip: timeMap, then the adjust-* elements
        # (adjust-conform), then anchored items (the music bed), then markers. Anything out of
        # that order does not validate, and Final Cut validates what it imports against that DTD.
        if c["reframed"]:
            # the DTD reads a missing adjust-conform as fit, so crop has to say fill; fit is
            # written too, so the file states the project's choice rather than a default
            inner.append(f'          <adjust-conform type="{_CONFORM[tl["fit"]]}"/>')
        if i == 0 and tl["music"]:
            m = tl["music"]
            mid = asset(m["src"], m["name"], m["media_frames"], False, True)
            inner.append(f'          <asset-clip ref="{mid}" lane="-1" offset="{_t(local0, rate)}" name="{q(m["name"])}" '
                         f'start="0s" duration="{_t(m["length"], rate)}" audioRole="music"/>')
        for mk in [m for m in markers if c["record_in"] <= m["at"] < c["record_in"] + c["visible"]]:
            inner.append(f'          <chapter-marker start="{_t(local0 + mk["at"] - c["record_in"], rate)}" '
                         f'duration="{fd}" value="{q(mk["title"])}"/>')
        head = (f'        <asset-clip ref="{rid}" offset="{_t(c["record_in"], rate)}" name="{q(c["name"])}" '
                f'start="{start_attr}" duration="{_t(c["visible"], rate)}" format="{cid}" tcFormat="NDF"')
        spine.append(head + (">\n" + "\n".join(inner) + "\n        </asset-clip>" if inner else "/>"))
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE fcpxml>", '<fcpxml version="1.10">',
           "  <resources>", *res, "  </resources>", "  <library>", f'    <event name="{q(tl["name"])}">',
           f'      <project name="{q(tl["name"])}">',
           f'        <sequence format="{seq_fmt}" duration="{_t(tl["total"], rate)}" tcStart="0s" tcFormat="NDF">',
           "      <spine>", *spine, "      </spine>", "        </sequence>", "      </project>", "    </event>",
           "  </library>", "</fcpxml>"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------- OTIO
def _rt(frames: int, rate: Fraction) -> Dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(rate), "value": float(frames)}


def _range(start: int, dur: int, rate: Fraction) -> Dict[str, Any]:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, rate), "duration": _rt(dur, rate)}


def to_otio(tl: Dict[str, Any]) -> str:
    """OpenTimelineIO JSON (Resolve imports it natively; Premiere/Avid through OTIO's adapters):
    a video track of clips and SMPTE dissolves, a music track, markers on the stack. Times are in
    timeline frames; a speed change is a LinearTimeWarp effect over the clip's source range."""
    rate = tl["rate"]
    d = tl["transition_frames"]
    video: List[Dict[str, Any]] = []
    for i, c in enumerate(tl["clips"]):
        if i > 0 and d:
            video.append({"OTIO_SCHEMA": "Transition.1", "name": "Cross Dissolve", "metadata": {},
                          "transition_type": "SMPTE_Dissolve",
                          # OTIO: in_offset is the part before the cut, out_offset the part after
                          "in_offset": _rt(c["trim_head"], rate), "out_offset": _rt(tl["clips"][i - 1]["trim_tail"], rate)})
        src_start = c["src_in"] + int(round(c["trim_head"] * c["speed"]))
        clip = {"OTIO_SCHEMA": "Clip.2", "name": c["name"], "metadata": {}, "enabled": True,
                # OTIO's own convention: source_range starts at the media's in point and lasts the
                # clip's length on the timeline; a LinearTimeWarp says how fast the media runs
                # through it (core OTIO does not rescale durations by effects).
                "source_range": _range(src_start, c["visible"], rate),
                "effects": [], "markers": [],
                "media_references": {"DEFAULT_MEDIA": {
                    "OTIO_SCHEMA": "ExternalReference.1", "name": c["name"], "metadata": {},
                    "target_url": _url(c["src"]), "available_range": _range(0, c["media_frames"], rate),
                    "available_image_bounds": None}},
                "active_media_reference_key": "DEFAULT_MEDIA"}
        if abs(c["speed"] - 1.0) > 1e-6:
            clip["effects"].append({"OTIO_SCHEMA": "LinearTimeWarp.1", "name": "speed", "metadata": {},
                                    "effect_name": "LinearTimeWarp", "time_scalar": c["speed"]})
        video.append(clip)
    tracks = [{"OTIO_SCHEMA": "Track.1", "name": "V1", "kind": "Video", "metadata": {}, "enabled": True,
               "source_range": None, "effects": [], "markers": [], "children": video}]
    if tl["music"]:
        m = tl["music"]
        tracks.append({"OTIO_SCHEMA": "Track.1", "name": "Music", "kind": "Audio", "metadata": {}, "enabled": True,
                       "source_range": None, "effects": [], "markers": [], "children": [{
                           "OTIO_SCHEMA": "Clip.2", "name": m["name"], "metadata": {}, "enabled": True,
                           "source_range": _range(0, m["length"], rate), "effects": [], "markers": [],
                           "media_references": {"DEFAULT_MEDIA": {
                               "OTIO_SCHEMA": "ExternalReference.1", "name": m["name"], "metadata": {},
                               "target_url": _url(m["src"]), "available_range": _range(0, m["media_frames"], rate),
                               "available_image_bounds": None}},
                           "active_media_reference_key": "DEFAULT_MEDIA"}]})
    markers = [{"OTIO_SCHEMA": "Marker.2", "name": mk["title"], "metadata": {}, "color": "RED", "comment": "",
                "marked_range": _range(mk["at"], 0, rate)} for mk in tl["markers"]]
    doc = {"OTIO_SCHEMA": "Timeline.1", "name": tl["name"], "metadata": {}, "global_start_time": _rt(0, rate),
           "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "metadata": {}, "enabled": True,
                      "source_range": None, "effects": [], "markers": markers, "children": tracks}}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


WRITERS = {"edl": to_edl, "fcpxml": to_fcpxml, "otio": to_otio}


def parses(path: str, fmt: str) -> bool:
    """The verification step: the written file reads back as what it claims to be."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        if fmt == "fcpxml":
            import xml.etree.ElementTree as ET
            return ET.fromstring(text.encode("utf-8")).tag == "fcpxml"
        if fmt == "otio":
            return json.loads(text).get("OTIO_SCHEMA") == "Timeline.1"
        return text.startswith("TITLE:") and any(line[:3].isdigit() for line in text.splitlines())
    except (OSError, ValueError, SyntaxError):
        return False


def summary(tl: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """The part of the timeline a caller reads back in render.py's --json document."""
    rate = tl["rate"]
    return {"format": fmt, "rate": f"{rate.numerator}/{rate.denominator}" if rate.denominator != 1 else str(rate.numerator),
            "duration": round(float(Fraction(tl["total"]) / rate), 3), "frames": tl["total"],
            "clips": len(tl["clips"]), "transition": tl["transition"],
            "transition_frames": tl["transition_frames"], "music": bool(tl["music"]),
            "markers": len(tl["markers"]), "notes": tl["notes"],
            "not_exported": tl["not_exported"] + _reframe_note(tl, fmt)}
