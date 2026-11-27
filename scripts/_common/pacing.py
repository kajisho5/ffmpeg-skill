"""Local pacing measurements. All times in the profile are milliseconds."""
import json
import math
import mmap
import tempfile
from contextlib import contextmanager
import os
import sys
from array import array
from pathlib import Path
from statistics import median

from _common import detect_scenes, probe
from _common.runner import run_analysis
from loudness import measure


def preset(name):
    # target, maximum, pre/post padding, head/tail limits, review threshold
    presets = {"sns-short": (90, 180, 30, 60, 40, 70, 500),
               "youtube-talk": (240, 400, 80, 160, 60, 160, 900),
               "podcast-natural": (500, 950, 200, 300, 160, 350, 1600)}
    target, maximum, pre, post, head, tail, flag = presets[name]
    return dict(contract="pacing-profile@1",
                silence_detection=dict(noise_floor_db=-60, noise_floor_offset_db=12,
                                       analysis_bandpass_hz=[120, 3800], min_silence_detect_ms=50),
                pacing=dict(max_keep_silence_ms=maximum, target_keep_silence_ms=target,
                            pad_before_speech_ms=pre, pad_after_speech_ms=post,
                            trim_leading_max_ms=head, trim_trailing_max_ms=tail,
                            flag_long_pause_above_ms=flag),
                cut_rules=dict(min_clip_frames=2, min_removed_frames=2, merge_gap_below_ms=30,
                               frame_snap_mode="inclusive_speech"),
                audio_seam=dict(seam_mode="zero_cross_shift", micro_fade_ms=3,
                                zero_cross_search_ms=3, max_boundary_sample_delta=0.08),
                loudness=dict(target_lufs=None, true_peak_db=None, lra_max=None),
                video_rhythm=dict(median_shot_ms=None, min_shot_ms=None),
                probe_meta=dict(origin=name, analysis_count=0, sample_names=[], bgm_suspected=False,
                                confidence="preset", reasons=[], warnings=[]))


def number(value):
    return type(value) in (float, int) and math.isfinite(value)


def read_profile(name):
    if name in ("sns-short", "youtube-talk", "podcast-natural"):
        return preset(name)
    data = json.loads(Path(name).read_text(encoding="utf-8"))
    template = preset("youtube-talk")
    if not isinstance(data, dict) or data.get("contract") != template["contract"]:
        raise ValueError("expected pacing-profile@1")
    for group, fields in template.items():
        if group == "contract":
            continue
        if not isinstance(data.get(group), dict):
            raise ValueError("missing profile group: " + group)
        for field, default in fields.items():
            value = data[group].get(field)
            if field not in data[group]:
                if group == "probe_meta" and field in ("origin", "warnings"):
                    continue
                raise ValueError("missing " + group + "." + field)
            if number(default) and (not number(value) or
                                    (value < 0 and field != "noise_floor_db")):
                raise ValueError("invalid " + group + "." + field)
            if default is None and value is not None and not number(value):
                raise ValueError("invalid measurement: " + field)
    rules, seam, detection = (data[k] for k in ("cut_rules", "audio_seam", "silence_detection"))
    band = detection["analysis_bandpass_hz"]
    if (not isinstance(band, list) or len(band) != 2 or not all(map(number, band))
            or not 0 < band[0] < band[1] < 4000 or detection["min_silence_detect_ms"] < 10
            or not -120 <= detection["noise_floor_db"] <= 0
            or not 0 <= detection["noise_floor_offset_db"] <= 60
            or seam["seam_mode"] not in ("none", "micro_fade", "zero_cross_shift")
            or max(seam["micro_fade_ms"], seam["zero_cross_search_ms"]) > 50
            or not 0 <= seam["max_boundary_sample_delta"] <= 2
            or rules["frame_snap_mode"] != "inclusive_speech"
            or any(type(rules[k]) is not int or rules[k] < 1 for k in ("min_clip_frames", "min_removed_frames"))
            or data["pacing"]["target_keep_silence_ms"] > data["pacing"]["max_keep_silence_ms"]):
        raise ValueError("invalid timing, band, frame or seam policy")
    meta = data["probe_meta"]
    if (type(meta["analysis_count"]) is not int or meta["analysis_count"] < 0
            or type(meta["bgm_suspected"]) is not bool or not isinstance(meta["confidence"], str)
            or any(not isinstance(meta[k], list) or not all(isinstance(v, str) for v in meta[k])
                   for k in ("sample_names", "reasons"))
            or not isinstance(meta.get("origin", ""), str)
            or not isinstance(meta.get("warnings", []), list) or not all(isinstance(v, str) for v in meta.get("warnings", []))
            or meta["analysis_count"] != len(meta["sample_names"])):
        raise ValueError("invalid probe metadata")
    return data


def quantile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    return ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)


def stats(values):
    return dict(median=median(values), p95=quantile(values, .95), range=[min(values), max(values)]) if values else None


@contextmanager
def decoded_pcm(path, options, fmt, code):
    """Disk-backed native samples, with the shared analysis timeout and local protocol guard."""
    with tempfile.TemporaryDirectory(prefix="pacing-pcm-") as directory:
        raw = Path(directory)/"samples.raw"
        cmd = ["ffmpeg", "-v", "error", "-nostdin",
               "-i", path, "-map", "0:a:0", *options, "-f", fmt, str(raw)]
        run_analysis(cmd)
        if not raw.stat().st_size:
            raise ValueError("audio decoded to zero samples")
        with raw.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
            if sys.byteorder != "little":
                samples = array(code)
                samples.fromfile(stream, len(mapping)//samples.itemsize)
                samples.byteswap()
                yield samples
            else:
                with memoryview(mapping).cast(code) as view:
                    yield view


def envelope(path, band, alignment=""):
    # Loudest channel avoids cancellation on an opposite-polarity stereo microphone.
    meta = probe(path)
    if not meta.get("audio"):
        raise ValueError("a pacing measurement requires audio")
    channels = meta["audio"]["channels"]
    filters = f"highpass=f={band[0]},lowpass=f={band[1]},aresample=8000"
    if alignment:
        filters = alignment + "," + filters
    step = 80 * channels
    levels = []
    with decoded_pcm(path, ["-af", filters], "s16le", "h") as pcm:
        duration = len(pcm) / channels / 8
        for pos in range(0, len(pcm), step):
            window = array("h", pcm[pos:pos + step])
            sums = [sum(x*x for x in window[c::channels]) for c in range(channels)]
            power = max(sums) / (len(window) / channels * 32768**2)
            levels.append(10 * math.log10(max(power, 1e-12)))
    return levels, duration


def pauses(levels, duration, detection):
    threshold = min(-20, detection["noise_floor_db"] + detection["noise_floor_offset_db"])
    result = []
    start = None
    for index in range(len(levels) + 1):
        if index < len(levels) and levels[index] <= threshold:
            if start is None:
                start = index * 10
        elif start is not None:
            end = min(index * 10, duration)
            if start == 0 or end == duration or end - start >= detection["min_silence_detect_ms"]:
                result.append((start, end))
            start = None
    return result


def extract(paths):
    profile = preset("youtube-talk")
    samples = []
    rows = {}
    reasons = []
    for path in paths:
        detection = profile["silence_detection"].copy()
        levels, duration = envelope(path, detection["analysis_bandpass_hz"])
        floor = quantile(levels, .1)
        detection["noise_floor_db"] = floor
        # Estimate the threshold from speech-to-floor separation. Bound the offset
        # because a digital zero floor and a continuous bed both skew that separation.
        detection["noise_floor_offset_db"] = min(18, max(6, (quantile(levels, .75)-floor)/3))
        spans = pauses(levels, duration, detection)
        interior = [b-a for a, b in spans if a > 0 and b < duration]
        low = sum(b-a for a, b in spans) / duration
        flags = []
        if low < .02:
            flags.append("below-threshold windows cover less than 2%")
        if floor > -38:
            flags.append("10th-percentile RMS above -38 dBFS")
        reasons.extend(f"{os.path.basename(path)}: {s}" for s in flags)
        audio = measure(path, -16, -1, 7)
        meta = probe(path)
        shots = []
        if meta.get("video"):
            length = meta["video"].get("duration") or meta["duration"]
            cuts = detect_scenes(path, 10, 0, length) + [length]
            shots = [(b-a)*1000 for a, b in zip(cuts, cuts[1:]) if b > a]
        row = dict(noise_floor_db=floor, noise_floor_offset_db=detection["noise_floor_offset_db"],
                   target_keep_silence_ms=median(interior) if interior else None,
                   max_keep_silence_ms=quantile(interior, .95) if interior else None,
                   trim_leading_max_ms=spans[0][1] if spans and spans[0][0] == 0 else 0,
                   trim_trailing_max_ms=duration-spans[-1][0] if spans and spans[-1][1] == duration else 0,
                   median_shot_ms=median(shots) if shots else None, min_shot_ms=min(shots) if shots else None)
        for key, raw in (("target_lufs", "input_i"), ("true_peak_db", "input_tp"), ("lra_max", "input_lra")):
            value = float(audio[raw]) if audio.get(raw) is not None else float("nan")
            row[key] = value if math.isfinite(value) else None
        for key, value in row.items():
            if value is not None:
                rows.setdefault(key, []).append(value)
        samples.append(dict(name=os.path.basename(path), measurements=row, interior_pauses=stats(interior),
                            below_threshold_fraction=low, bgm_reasons=flags))
    for group in ("silence_detection", "pacing", "loudness", "video_rhythm"):
        for key in profile[group]:
            if key in rows:
                profile[group][key] = round(median(rows[key]), 4)
    pacing = profile["pacing"]
    target = pacing["target_keep_silence_ms"]
    pacing.update(pad_before_speech_ms=target/3, pad_after_speech_ms=target*2/3,
                  flag_long_pause_above_ms=max(pacing["max_keep_silence_ms"], 2*target))
    profile["probe_meta"].update(origin="references", analysis_count=len(paths),
                                sample_names=[s["name"] for s in samples], samples=samples,
                                warnings=["Possible music bed: use an isolated voice track, a preset or a reviewed threshold."] if reasons else [],
                                between_files={k: stats(v) for k, v in rows.items()}, reasons=reasons,
                                bgm_suspected=bool(reasons), confidence="low" if reasons or "target_keep_silence_ms" not in rows else "measured",
                                policy_fields=["analysis_bandpass_hz", "min_silence_detect_ms",
                                               "pad_before_speech_ms", "pad_after_speech_ms", "flag_long_pause_above_ms",
                                               "cut_rules", "audio_seam"],
                                fallback_fields=[k for k in ("target_keep_silence_ms", "max_keep_silence_ms") if k not in rows])
    return profile


def profile_schema():
    """The contract publishes the same required groups the reader consumes."""
    fields = {"contract": {"const": "pacing-profile@1", "type": "string"}}
    for group, values in preset("youtube-talk").items():
        if group == "contract":
            continue
        props = {}
        for key, default in values.items():
            if key == "frame_snap_mode":
                spec = {"enum": ["inclusive_speech"]}
            elif key == "seam_mode":
                spec = {"enum": ["zero_cross_shift", "micro_fade", "none"]}
            elif key == "analysis_bandpass_hz":
                spec = dict(type="array", minItems=2, maxItems=2, items={"type": "number"})
            elif default is None:
                spec = {"type": ["number", "null"]}
            elif isinstance(default, bool):
                spec = {"type": "boolean"}
            elif isinstance(default, list):
                spec = {"type": "array", "items": {"type": "string"}}
            elif isinstance(default, str):
                spec = {"type": "string"}
            elif key in ("min_clip_frames", "min_removed_frames", "analysis_count"):
                spec = {"type": "integer"}
            else:
                spec = {"type": "number"}
            if number(default):
                spec["minimum"] = {"noise_floor_db": -120, "min_silence_detect_ms": 10,
                                   "min_clip_frames": 1, "min_removed_frames": 1}.get(key, 0)
                maxima = {"noise_floor_db": 0, "noise_floor_offset_db": 60, "micro_fade_ms": 50,
                          "zero_cross_search_ms": 50, "max_boundary_sample_delta": 2}
                if key in maxima:
                    spec["maximum"] = maxima[key]
            if key == "analysis_bandpass_hz":
                spec["items"].update(exclusiveMinimum=0, exclusiveMaximum=4000)
            props[key] = spec
        fields[group] = dict(type="object", properties=props,
                             required=[k for k in props if k not in ("origin", "warnings")])
    return dict(type="object", required=list(fields), properties=fields)
