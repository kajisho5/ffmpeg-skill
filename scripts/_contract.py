#!/usr/bin/env python3
"""Machine-readable execution contract for ffmpeg-skill (internal module, not a tool).

    python3 scripts/_contract.py --json              # the contract, with detected capabilities
    python3 scripts/_contract.py --json --static     # same, without environment detection
    python3 scripts/_contract.py doctor [--json]     # which required capabilities this machine has
    ffmpeg-skill contract --json                     # the same through the npm entry point

The contract describes every public tool in scripts/ (one ToolSpec per script that does
not start with "_"): what it needs, what it takes, what it writes, how to verify the
result, and whether an agent can plan it with --dry-run. Input schemas are generated
from each script's argparse parser, so the CLI stays the single source of truth; the
per-tool facts that cannot be read from a parser (role, verification policy, required
ffmpeg components) live in TOOL_META below and are checked against the scripts by
tests/test_contract.py.

The contract has its own version (CONTRACT_VERSION) that only changes when the shape of
this document changes; the skill version comes from package.json.
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL_ID = "ffmpeg-skill"
CONTRACT_VERSION = "1.0"
# `doctor`'s own introspection calls (-filters/-encoders/-bsfs/-version) are meant to be fast,
# bounded, non-media operations; a hang here would silently freeze the one tool meant to report
# whether the machine is broken. Media-processing scripts (cut, fit, ...) are NOT bounded this
# way -- a legitimate --accurate re-encode of a long file can take a long time, so no timeout is
# applied there (see README, "Development").
_DETECT_TIMEOUT = 10

ROLES = {
    "analysis": "reads media and reports measurements; writes no media",
    "analysis_and_execution": "measures by default or with a flag, and can also write a transformed artifact",
    "execution": "writes a new media artifact from the input(s); the input is never modified",
    "verification": "checks or shows an artifact (probe numbers, compliance rows, contact sheets); writes no media",
}

# Facts that are not derivable from the argparse parsers. Capability names:
#   ffmpeg / ffprobe            the binaries on PATH
#   encoder:<name>              `ffmpeg -encoders`
#   filter:<name>               `ffmpeg -filters`
#   bsf:<name>                  `ffmpeg -bsfs`
#   external:whisper            a local whisper engine (whisper.cpp / faster-whisper / openai-whisper)
# "optional" entries name the flag or condition under which the capability is needed.
FF = ["ffmpeg", "ffprobe"]
X264 = "encoder:libx264"
X265 = "encoder:libx265"
AAC = "encoder:aac"
HDR_X265 = {"capability": X265, "when": "the source is HDR (kept as HEVC Main10)"}
AUDIO_OUT = [
    {"capability": "encoder:libmp3lame", "when": "output extension is .mp3"},
    {"capability": "encoder:libopus", "when": "output extension is .opus"},
    {"capability": "encoder:libvorbis", "when": "output extension is .ogg"},
    {"capability": "encoder:flac", "when": "output extension is .flac"},
]

TOOL_META: Dict[str, Dict[str, Any]] = {
    "probe": dict(role="analysis", inputs=["media (video or audio, any container ffprobe reads)"], outputs=["measurement JSON on stdout (no file)"],
                  required=["ffprobe"], optional=[{"capability": "ffmpeg", "when": "--analyze"}, {"capability": "filter:signalstats", "when": "--analyze"}],
                  video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=False, idempotency="bit_exact", deterministic=True),
    "cut": dict(role="execution", inputs=["video or audio asset"], outputs=["cut video/audio artifact (same container family, or audio extracted when -o has an audio extension)"],
                required=FF, optional=[{"capability": X264, "when": "re-encode: --accurate, VFR source, or a keyframe farther than --tolerance"}, HDR_X265, {"capability": AAC, "when": "re-encode of a video container"}] + AUDIO_OUT,
                video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "fit": dict(role="execution", inputs=["video asset"], outputs=["video artifact at the requested duration / aspect / fps"],
                required=FF + [X264, AAC], optional=[HDR_X265, {"capability": "filter:minterpolate", "when": "--smooth interpolate"},
                                                     {"capability": "filter:boxblur", "when": "--pad-fill blur"}],
                video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "crop": dict(role="execution", inputs=["video asset"], outputs=["video artifact cropped to the given pixel rectangle"],
                 required=FF + [X264, AAC], optional=[HDR_X265],
                 video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "deinterlace": dict(role="execution", inputs=["video asset"], outputs=["deinterlaced (progressive) video artifact"],
                        required=FF + [X264, AAC, "filter:yadif"], optional=[HDR_X265],
                        video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "denoise": dict(role="execution", inputs=["video asset"], outputs=["denoised video artifact"],
                    required=FF + [X264, AAC, "filter:hqdn3d"], optional=[HDR_X265],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "cropdetect": dict(role="analysis", inputs=["video asset"], outputs=["detected crop rectangle JSON on stdout (no file)"],
                       required=FF + ["filter:cropdetect"], optional=[],
                       video_required=True, audio_only=False, visual=False, verify=[], produces_artifact=False, idempotency="environment_dependent", deterministic=False),
    "redact": dict(role="execution", inputs=["video asset"], outputs=["video artifact with the given pixel rectangle blurred or pixelated"],
                   required=FF + [X264, AAC, "filter:boxblur"], optional=[HDR_X265],
                   video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "waveform": dict(role="execution", inputs=["audio or video asset (audio track only)"], outputs=["generated waveform or spectrum visualization video artifact"],
                     required=FF + [X264, AAC, "filter:showwaves"], optional=[{"capability": "filter:showspectrum", "when": "--style spectrum"}],
                     video_required=False, audio_only=True, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "sphere": dict(role="execution", inputs=["360/spherical video asset"], outputs=["flat rectilinear video artifact of the chosen viewport"],
                    required=FF + [X264, AAC, "filter:v360"], optional=[HDR_X265],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "grid": dict(role="execution", inputs=["cols*rows video assets, filled left-to-right top-to-bottom"], outputs=["composited grid video artifact"],
                 required=FF + [X264, "filter:xstack"], optional=[{"capability": "filter:drawtext", "when": "--label auto (the default)"}, {"capability": AAC, "when": "--audio-from"}],
                 video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "straighten": dict(role="execution", inputs=["video asset"], outputs=["video artifact rotated by the given angle (horizon correction)"],
                       required=FF + [X264, AAC, "filter:rotate"], optional=[HDR_X265],
                       video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "freeze": dict(role="execution", inputs=["video asset"], outputs=["video artifact with a frame held for the given duration"],
                   required=FF + [X264, AAC, "filter:tpad"], optional=[HDR_X265],
                   video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "pad": dict(role="execution", inputs=["video asset"], outputs=["video artifact with black/silent padding added at the start/end"],
                required=FF + [X264, AAC, "filter:tpad"], optional=[HDR_X265],
                video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "speedramp": dict(role="execution", inputs=["video asset"], outputs=["video artifact with a stepped speed ramp applied across segments"],
                      required=FF + [X264, AAC], optional=[HDR_X265],
                      video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "broll": dict(role="execution", inputs=["A-roll video asset", "one or more B-roll video assets (--insert)"], outputs=["video artifact of exactly the A-roll's length with the B-roll shown during each cutaway window"],
                  required=FF + [X264, AAC, "filter:overlay", "filter:amix"], optional=[HDR_X265],
                  video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "metadata": dict(role="execution", inputs=["video or audio asset", "chapters text file (--chapters)"], outputs=["the same streams, stream-copied, with chapter markers and/or title/artist/comment tags written"],
                     required=FF, optional=[],
                     video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "loop": dict(role="execution", inputs=["video asset"], outputs=["video artifact repeated to the requested count or duration"],
                 required=FF + [X264, AAC], optional=[],
                 video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "insert": dict(role="execution", inputs=["still image"], outputs=["silent video artifact of the requested duration / frame size / fps"],
                   required=FF + [X264], optional=[{"capability": "filter:zoompan", "when": "--zoom / --pan"}],
                   video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "background": dict(role="execution", inputs=[], outputs=["generated solid-colour or gradient video artifact"],
                        required=FF + [X264], optional=[{"capability": "filter:gradients", "when": "--gradient"}],
                        video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "reverse": dict(role="execution", inputs=["video asset"], outputs=["reversed video artifact"],
                    required=FF + [X264, "filter:reverse"], optional=[HDR_X265, {"capability": "filter:areverse", "when": "the input has audio and --no-audio is not given"}, {"capability": AAC, "when": "the input has audio and --no-audio is not given"}],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "stabilize": dict(role="execution", inputs=["video asset"], outputs=["motion-stabilised video artifact"],
                       required=FF + [X264, "filter:vidstabdetect", "filter:vidstabtransform"], optional=[HDR_X265, {"capability": AAC, "when": "the input has audio"}],
                       video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "sequence": dict(role="execution", inputs=["a directory of numbered/globbed still images"], outputs=["video artifact built from the frame sequence"],
                      required=FF + [X264], optional=[],
                      video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "caption": dict(role="execution", inputs=["video asset", "SRT/ASS file or timed text (--text)"], outputs=["video artifact with burnt-in captions (--mode burn)", "video artifact with an added soft subtitle stream (--mode mux)", "generated .srt / .ass sidecar"],
                    required=FF + [X264, AAC, "filter:subtitles"], optional=[{"capability": "filter:ass", "when": "--animate / --karaoke"}, HDR_X265, {"capability": "external:whisper", "when": "--transcribe"},
                                            {"capability": "encoder:mov_text", "when": "--mode mux with a .mp4/.m4v/.mov output"}, {"capability": "encoder:webvtt", "when": "--mode mux with a .webm output"}, {"capability": "encoder:srt", "when": "--mode mux with a .mkv output"}],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "overlay": dict(role="execution", inputs=["video asset", "image (--image / --logo), text (--text), or a second video (--video) to composite"], outputs=["video artifact with the overlay composited"],
                    required=FF + [X264, AAC], optional=[{"capability": "filter:drawtext", "when": "--text"}, {"capability": "filter:chromakey", "when": "--chromakey"}, HDR_X265],
                    video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "graphics": dict(role="execution", inputs=["video asset"], outputs=["video artifact with the drawn template"],
                     required=FF + [X264, AAC, "filter:drawtext"], optional=[HDR_X265],
                     video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "sync": dict(role="analysis_and_execution", inputs=["reference recording (video or audio)", "second recording (video or audio)"], outputs=["offset / drift JSON on stdout", "aligned artifact with --replace-audio / --trim-second / --fix-drift -o"],
                 required=FF, optional=[{"capability": AAC, "when": "writing a video container"}] + AUDIO_OUT,
                 video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "multicam": dict(role="execution", inputs=["reference camera", "other cameras / recorders"], outputs=["switched multicam video artifact"],
                     required=FF + [X264, AAC], optional=[HDR_X265],
                     video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "audio": dict(role="execution", inputs=["video or audio asset", "music bed (--music) or replacement track (--replace)"], outputs=["artifact with the processed audio (video stream-copied, or dropped when -o has an audio extension)"],
                  required=FF, optional=[{"capability": "filter:afftdn", "when": "--denoise / --voice"}, {"capability": "filter:sidechaincompress", "when": "--duck"},
                                        {"capability": "filter:acompressor", "when": "--compress / --voice"}, {"capability": "filter:alimiter", "when": "--limit"}, {"capability": "filter:agate", "when": "--gate"},
                                        {"capability": AAC, "when": "output extension isn't .mp3/.opus/.ogg/.flac (audio_codec_for()'s default)"}] + AUDIO_OUT,
                  video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "loudness": dict(role="analysis_and_execution", inputs=["video or audio asset"], outputs=["loudness measurement JSON (--measure-only)", "normalised artifact (video stream-copied)"],
                     required=FF + ["filter:loudnorm"], optional=[{"capability": AAC, "when": "output extension isn't .mp3/.opus/.ogg/.flac (audio_codec_for()'s default)"}] + AUDIO_OUT,
                     video_required=False, audio_only=True, visual=False, verify=["probe", "check"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "silence": dict(role="analysis_and_execution", inputs=["video or audio asset"], outputs=["silence list JSON (--list)", "artifact with silences removed", "EDL text (--edl)"],
                    required=FF + ["filter:silencedetect"], optional=[{"capability": X264, "when": "removing silences from a video"}, HDR_X265, {"capability": AAC, "when": "removing silences from a video"}] + AUDIO_OUT,
                    video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "join": dict(role="execution", inputs=["two or more video assets, or two or more audio-only assets"], outputs=["concatenated video artifact", "concatenated audio artifact (audio-only inputs, audio output extension)"],
                 required=FF + ["filter:xfade", "filter:acrossfade"],
                 optional=[{"capability": X264, "when": "joining video inputs"}, {"capability": AAC, "when": "joining video inputs, or an audio-only join whose output extension isn't .mp3/.opus/.ogg/.flac"}, HDR_X265] + AUDIO_OUT,
                 video_required=False, audio_only=True, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "color": dict(role="execution", inputs=["video asset", ".cube LUT (--lut)"], outputs=["video artifact with converted colour"],
                  required=FF, optional=[{"capability": X264, "when": "--to-sdr / --lut / --correct"}, {"capability": "filter:zscale", "when": "--to-sdr"}, {"capability": "filter:tonemap", "when": "--to-sdr"},
                                         {"capability": "filter:lut3d", "when": "--lut"}, {"capability": "bsf:filter_units", "when": "--strip-dovi"}, {"capability": X265, "when": "--lut on an HDR source"}, {"capability": AAC, "when": "re-encode"},
                                         {"capability": "filter:exposure", "when": "--correct"}, {"capability": "filter:eq", "when": "--correct"},
                                         {"capability": "filter:colorbalance", "when": "--correct"}, {"capability": "filter:colortemperature", "when": "--correct"},
                                         {"capability": "filter:colorlevels", "when": "--correct with any --levels-*"}, {"capability": "filter:curves", "when": "--correct --curves"}],
                  video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "proxy": dict(role="execution", inputs=["video asset"], outputs=["low-resolution, low-bitrate proxy artifact for downstream analysis, preview or editing decisions"],
                  required=FF + [X264, AAC], optional=[HDR_X265],
                  video_required=True, audio_only=False, visual=True, verify=["probe", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "export": dict(role="execution", inputs=["video asset"], outputs=["delivery artifact in the preset's format"],
                   required=FF, optional=[{"capability": X264, "when": "preset youtube / youtube4k / reels / x"}, {"capability": AAC, "when": "preset youtube / youtube4k / reels / x / h265 (prores uses pcm_s16le, copy stream-copies, gif has no audio)"},
                                          {"capability": X265, "when": "preset h265"}, {"capability": "encoder:prores_ks", "when": "preset prores"},
                                          {"capability": "filter:palettegen", "when": "preset gif"}, {"capability": "encoder:gif", "when": "preset gif"}, {"capability": "filter:boxblur", "when": "--pad-fill blur"}],
                   video_required=True, audio_only=False, visual=False, verify=["probe", "check"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "check": dict(role="verification", inputs=["media artifact"], outputs=["compliance rows JSON on stdout (no file)"],
                  required=["ffprobe"], optional=[{"capability": "ffmpeg", "when": "loudness rows (default)"}, {"capability": "filter:loudnorm", "when": "loudness rows (default)"}],
                  video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=False, idempotency="bit_exact", deterministic=True),
    "scenes": dict(role="analysis", inputs=["video asset"], outputs=["scene / audio-peak / highlight JSON on stdout", "EDL text (--edl)", "per-scene contact sheet PNG (--sheet)"],
                   required=FF + ["filter:scdet"], optional=[{"capability": "filter:drawtext", "when": "--sheet"}, {"capability": "filter:tile", "when": "--sheet"}],
                   video_required=True, audio_only=False, visual=False, verify=[], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "look": dict(role="verification", inputs=["video artifact"], outputs=["PNG contact sheet / frames / side-by-side"],
                 required=FF + ["filter:tile"], optional=[{"capability": "filter:drawtext", "when": "timecode stamps (default; --no-timecode to skip)"}, {"capability": "filter:zscale", "when": "HDR source"}, {"capability": "filter:tonemap", "when": "HDR source"}],
                 video_required=True, audio_only=False, visual=False, verify=[], produces_artifact=True, idempotency="bit_exact", deterministic=True),
    "render": dict(role="execution", inputs=["project.json (clips, transitions, captions, overlays, audio, loudness, export, check)"], outputs=["final video artifact", "work directory of stage outputs (--keep / --work)"],
                   required=FF, optional=[{"capability": "delegated", "when": "each stage runs cut / join / fit / caption / overlay / audio / loudness / export / check with their capabilities"}],
                   video_required=True, audio_only=False, visual=True, verify=["probe", "check", "look"], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
    "batch": dict(role="execution", inputs=["folder of media", "batch.json recipe (steps or a render project)"], outputs=["one artifact per input file in the recipe's output_dir", "content-hash cache"],
                  required=FF, optional=[{"capability": "delegated", "when": "each recipe step runs the named script with its capabilities"}],
                  video_required=False, audio_only=True, visual=False, verify=["probe"], produces_artifact=True, idempotency="cached", deterministic=True),
    "verify": dict(role="verification", inputs=["media files and/or folders"], outputs=["PASS/FAIL JSON per step", "Markdown report (--report)", "step outputs (--out / --keep)"],
                   required=FF, optional=[{"capability": "delegated", "when": "runs cut / fit / caption / export / loudness / color on each file"}],
                   video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=True, idempotency="environment_dependent", deterministic=False),
    "report": dict(role="verification", inputs=["deliverable (--after)", "source (--before)", "commands / notes text"], outputs=["single-file HTML delivery report"],
                   required=FF + ["filter:loudnorm"], optional=[{"capability": "delegated", "when": "runs look (sheets) and check (--platform)"}],
                   video_required=False, audio_only=True, visual=False, verify=[], produces_artifact=True, idempotency="content_equivalent", deterministic=True),
}

# Dry-run behaviour a parser cannot express (measured in tests/test_contract.py with a fake ffmpeg
# on PATH). "analysis_only": ffmpeg still decodes/measures the input under --dry-run, but nothing
# is encoded and no file is written. Every other tool with the flag runs no ffmpeg at all.
DRY_RUN_ANALYSIS = {
    "sync": "audio is decoded to find the offset; the aligned output is not written",
    "multicam": "audio is decoded to align the cameras; the switched output is not written",
    "scenes": "scene and audio-peak measurement runs; --sheet and --edl are not written",
    "report": "probe, loudness and contact-sheet measurements run; the HTML is not written",
    "cropdetect": "the cropdetect filter runs over the sampled windows to measure bars; this tool never writes a file regardless of --dry-run",
}
DRY_RUN_NOTES = {
    "probe": "read-only tool; --dry-run changes nothing (ffprobe still runs)",
    "check": "read-only tool; --dry-run skips the ffmpeg loudness measurement, so loudness rows are absent",
    "verify": "not supported: the flag is accepted but the steps run and outputs are written",
}

# Whether a tool re-encodes each stream *when that stream is present in the input* -- not whether
# the tool touches the file at all. "always"/"never" are unconditional given that stream exists;
# "conditional" means it depends on flags or on how far a lossless attempt misses (see "note").
# Read from each script's actual encode/copy args, not from role or intent, since several tools
# (fit, caption, overlay, graphics, color, join, multicam, silence) always transcode audio to AAC
# alongside a video filter even though the audio itself is untouched content -- there is no
# "-c:a copy while re-encoding video" path in this codebase, so a soft-subtitle-style passthrough
# of the original audio codec never happens on those tools.
REENCODE_META: Dict[str, Dict[str, str]] = {
    "probe":     dict(video="never", audio="never", note="analysis only, no artifact"),
    "cut":       dict(video="conditional", audio="conditional", note="lossless -c copy preferred; re-encodes on --accurate, a VFR source, or a keyframe snap past --tolerance (see cut.py --json: mode, keyframe_snapped)"),
    "fit":       dict(video="always", audio="always", note="always re-encodes to AAC when audio is present, even if only --fps or --aspect was asked for"),
    "crop":      dict(video="always", audio="always", note="the crop filter always forces a re-encode of both streams"),
    "deinterlace": dict(video="always", audio="always", note="the yadif filter always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "denoise":   dict(video="always", audio="always", note="the hqdn3d filter always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "cropdetect": dict(video="never", audio="never", note="analysis only, no artifact"),
    "redact":    dict(video="always", audio="always", note="the boxblur/pixelate filter_complex always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "waveform":  dict(video="always", audio="always", note="always encodes a fresh generated visualization clip; the source audio is always re-encoded to AAC"),
    "sphere":   dict(video="always", audio="always", note="the v360 filter always forces a re-encode of the video stream; audio is passed through to AAC unchanged"),
    "straighten": dict(video="always", audio="always", note="the rotate filter always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "grid":      dict(video="always", audio="conditional", note="the xstack composite always forces a re-encode of the video stream; there is no audio at all unless --audio-from picks one input's track, which is then re-encoded to AAC"),
    "freeze":   dict(video="always", audio="always", note="the tpad/concat filter graph always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "pad":      dict(video="always", audio="always", note="the tpad filter always forces a re-encode of the video stream; audio is re-encoded to AAC when present"),
    "speedramp": dict(video="always", audio="always", note="setpts/atempo per segment always forces a re-encode of both streams"),
    "broll":    dict(video="always", audio="conditional", note="the overlay graph always re-encodes the video stream; A's audio is stream-copied under --audio a and re-encoded to AAC under --audio b/mix"),
    "metadata": dict(video="never", audio="never", note="-c copy on every stream; only the container's chapters and tags change"),
    "loop":     dict(video="always", audio="always", note="-stream_loop always re-encodes both streams; the audio codec is always AAC when present"),
    "insert":    dict(video="always", audio="never", note="always encodes a fresh silent clip from the still image; there is no audio stream to touch"),
    "background": dict(video="always", audio="never", note="always encodes a fresh generated clip; there is no input to copy from"),
    "reverse":   dict(video="always", audio="conditional", note="video always re-encodes (reverse buffers and re-emits every frame); audio re-encodes to AAC when present and not dropped by --no-audio"),
    "stabilize": dict(video="always", audio="conditional", note="video always re-encodes (two-pass vidstab); audio is re-encoded to AAC when present, never touched by the stabilization filters themselves"),
    "sequence":  dict(video="always", audio="never", note="always encodes a fresh clip from the frame sequence; there is no audio stream"),
    "caption":   dict(video="conditional", audio="conditional", note="--mode burn (default) always re-encodes both streams to render pixels; --mode mux copies video and audio untouched and only adds a subtitle stream"),
    "overlay":   dict(video="always", audio="always"),
    "graphics":  dict(video="always", audio="always"),
    "sync":      dict(video="conditional", audio="conditional", note="video is -c:v copy only for --trim-second when the second file started earlier (offset<0) and the copy succeeds; it is re-encoded whenever --replace-audio's stream copy fails, or in --trim-second when the second file started later (offset>=0, the common case) or --fix-drift is used"),
    "multicam":  dict(video="always", audio="always"),
    "audio":     dict(video="never", audio="always", note="video stream is always -c:v copy when present; this tool's job is the audio"),
    "loudness":  dict(video="never", audio="always"),
    "silence":   dict(video="always", audio="always", note="removing gaps requires cutting on non-keyframe boundaries"),
    "join":      dict(video="always", audio="always"),
    "color":     dict(video="conditional", audio="conditional", note="--strip-dovi and --retag (when the stream copy succeeds) are -c copy of both streams; --retag falls back to re-encoding only if the copy attempt fails; --to-sdr / --lut / --correct always re-encode both"),
    "proxy":     dict(video="always", audio="conditional", note="video is always re-encoded at proxy-grade quality; audio is re-encoded when present, dropped entirely with --no-audio or when the source has none"),
    "export":    dict(video="conditional", audio="conditional", note="--preset copy is -c:v copy -c:a copy (no re-encode); every other preset re-encodes both"),
    "check":     dict(video="never", audio="never", note="read-only, no artifact"),
    "scenes":    dict(video="never", audio="never", note="analysis only; --sheet renders a new contact-sheet PNG, not a re-encode of the source"),
    "look":      dict(video="never", audio="never", note="renders a new contact-sheet/frame PNG, not a re-encode of the source"),
    "render":    dict(video="conditional", audio="conditional", note="delegated: depends on which stages a project.json runs and how each one behaves"),
    "batch":     dict(video="conditional", audio="conditional", note="delegated: depends on which script each recipe step runs"),
    "verify":    dict(video="conditional", audio="conditional", note="delegated: runs cut/fit/caption/export/loudness/color internally as checks"),
    "report":    dict(video="never", audio="never", note="measures via look/check; produces an HTML report, not a re-encoded artifact"),
}

IDEMPOTENCY = {
    "bit_exact": "same inputs and flags give byte-identical output",
    "content_equivalent": "same inputs and flags give the same media content; bytes may differ between encoder builds",
    "cached": "re-runs skip inputs whose content hash and recipe are unchanged",
    "environment_dependent": "output includes timings or machine state and differs between runs",
}


# ----------------------------------------------------------------------------- parsers
class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


def _capture_parser(script: Path) -> argparse.ArgumentParser:
    """Import the script and run main() until parse_args() to get its live parser."""
    original = argparse.ArgumentParser.parse_args

    def fake_parse(self: argparse.ArgumentParser, *a: Any, **k: Any) -> Any:
        raise _Captured(self)

    argparse.ArgumentParser.parse_args = fake_parse  # type: ignore[assignment]
    sys_argv = sys.argv
    try:
        sys.argv = [str(script)]
        spec = importlib.util.spec_from_file_location("ffskill_tool_" + script.stem, script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.main()
    except _Captured as cap:
        return cap.parser
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[assignment]
        sys.argv = sys_argv
    raise RuntimeError(f"{script.name}: main() returned before parse_args()")


def _json_type(action: argparse.Action) -> Dict[str, Any]:
    if isinstance(action, argparse._StoreTrueAction):
        return {"type": "boolean"}
    if isinstance(action, argparse._AppendAction) or action.nargs in ("+", "*"):
        return {"type": "array", "items": {"type": "string"}}
    if action.type is int:
        return {"type": "integer"}
    if action.type is float:
        return {"type": "number"}
    return {"type": "string"}


def input_schema(parser: argparse.ArgumentParser) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []
    positional: List[str] = []
    common = {"dry_run", "json", "progress", "fast"}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        prop: Dict[str, Any] = _json_type(action)
        if action.help and action.help != argparse.SUPPRESS:
            prop["description"] = action.help % {"default": action.default} if "%(default)" in action.help else action.help
        if action.choices:
            prop["enum"] = list(action.choices)
        if action.default not in (None, False, argparse.SUPPRESS):
            prop["default"] = action.default
        if action.option_strings:
            prop["cli"] = list(action.option_strings)
            if action.required:
                required.append(action.dest)
        else:
            prop["cli"] = "positional"
            positional.append(action.dest)
            if action.nargs not in ("?", "*"):
                required.append(action.dest)
        if action.dest in common:
            prop["common"] = True
        props[action.dest] = prop
    groups = [g for g in getattr(parser, "_mutually_exclusive_groups", []) if g._group_actions]
    schema: Dict[str, Any] = {"type": "object", "properties": props, "required": required, "positional": positional, "additionalProperties": False}
    if groups:
        schema["mutually_exclusive"] = [[a.dest for a in g._group_actions] for g in groups]
        schema["one_of_required"] = [[a.dest for a in g._group_actions] for g in groups if g.required]
    return schema


def output_schema(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """What the tool prints on stdout with --json (keys observed in the implementation)."""
    if name == "probe":
        return {"type": "object", "description": "one probe document, or an array of them for several inputs",
                "properties": {"file": {"type": "string"}, "format": {"type": "string"}, "duration": {"type": "number"}, "size_bytes": {"type": "integer"},
                               "video": {"type": ["object", "null"]}, "audio": {"type": ["object", "null"]}}, "additionalProperties": True}
    base = {"status": {"enum": ["completed"]}, "output": {"type": ["string", "null"], "description": "path written, or null"},
            "dry_run": {"type": "boolean"}, "commands": {"type": "array", "items": {"type": "string"}, "description": "every ffmpeg command line planned or run"},
            "probe": {"type": "object", "description": "probe of the output when a file was written"}}
    extra: Dict[str, Any] = {}
    if name == "check":
        extra = {"platform": {"type": "string"}, "ok": {"type": "boolean"}, "failed": {"type": "integer"}, "warnings": {"type": "integer"},
                 "checks": {"type": "array", "items": {"type": "object", "properties": {"check": {"type": "string"}, "status": {"enum": ["PASS", "WARN", "FAIL"]}, "value": {}, "expected": {}, "fix": {"type": "string"}, "kind": {"enum": ["format", "judgement"]}}}}}
    elif name == "scenes":
        extra = {"file": {"type": "string"}, "duration": {"type": "number"}, "scene_count": {"type": "integer"}, "scenes": {"type": "array"}, "audio_peaks": {"type": "array"}}
    elif name == "silence":
        extra = {"silences": {"type": "array"}, "keep": {"type": "array"}, "input_duration": {"type": "number"}, "kept_duration": {"type": "number"}, "removed_seconds": {"type": "number"}}
    elif name == "sync":
        extra = {"reference": {"type": "string"}, "second": {"type": "string"}, "offset_seconds": {"type": "number"}, "confidence": {"type": "number"}, "meaning": {"type": "string"}, "drift": {"type": "object"}}
    elif name == "look":
        extra = {"outputs": {"type": "array", "items": {"type": "string"}}}
    elif name == "render":
        extra = {"stages": {"type": "array", "items": {"type": "string"}}, "check": {"type": ["object", "null"]}}
    elif name == "verify":
        extra = {"report": {"type": ["string", "null"]}, "files": {"type": "array"}, "failed": {"type": "integer"}, "total": {"type": "integer"}}
    elif name == "batch":
        extra = {"results": {"type": "array"}, "processed": {"type": "integer"}, "total": {"type": "integer"}}
    elif name == "report":
        extra = {"report": {"type": "string"}, "check": {"type": ["object", "null"]}}
    elif name == "loudness":
        extra = {"measured": {"type": "object", "description": "--measure-only prints the loudnorm measurement instead (input_i, input_tp, input_lra, input_thresh, target_offset)"}}
    elif name == "cut":
        extra = {"expected_duration": {"type": "number", "description": "seconds requested"},
                 "duration_error_ms": {"type": ["number", "null"], "description": "written minus requested, measured by ffprobe (null under --dry-run)"},
                 "precision": {"enum": ["packet", "sample", "codec_frame", "frame"],
                               "description": "packet: stream copy on a packet/keyframe boundary; sample: decoded audio trimmed to the sample, lossless output; codec_frame: sample-trimmed then framed by a lossy encoder (priming delay adds to the length); frame: re-encoded video"},
                 "reencoded": {"type": "boolean"}}
    elif name == "join":
        extra = {"mode": {"enum": ["video", "audio"]}, "clips": {"type": "integer"}, "transition": {"type": "string"}, "expected_duration": {"type": "number"},
                 "sample_rate": {"type": "integer", "description": "audio mode only"}, "channels": {"type": "integer", "description": "audio mode only"},
                 "video": {"type": "boolean", "description": "false in audio mode: the output has no video stream"}}
    elif name == "audio":
        extra = {"video": {"type": "boolean", "description": "true when the input's video stream was copied; false for an audio output extension (extraction)"},
                 "audio_stream": {"type": "integer", "description": "which input audio stream was processed (--audio-stream)"},
                 "dynamics": {"type": "array", "items": {"enum": ["agate", "acompressor", "alimiter"]}, "description": "typed dynamics filters applied, in graph order"}}
    props = dict(base)
    props.update(extra)
    required = ["status", "output", "dry_run", "commands"]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": True}


# ----------------------------------------------------------------------------- environment
def skill_version() -> str:
    for candidate in (ROOT / "package.json",):
        try:
            return str(json.loads(candidate.read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError):
            continue
    return "unknown"


def skill_description() -> str:
    try:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^description:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def public_tools() -> List[str]:
    return sorted(p.stem for p in HERE.glob("*.py") if not p.name.startswith("_"))


# `ffmpeg -filters` rows: FFmpeg <= 7 prints three flag characters (`..C acompressor A->A ...`),
# FFmpeg 8 prints two (`T. acompressor A->A ...`). The row is recognised by its io-spec token
# (`A->A`, `|->V`, `N->N`, ...) so the flag width does not matter; a legend line never carries `->`.
_FILTER_ROW = re.compile(r"^\s*(?:[A-Z.]{1,6}\s+)?([A-Za-z0-9_]+)\s+(\S*->\S*)(?:\s|$)")
# `ffmpeg -encoders` rows follow a ` ------` separator: flags (six characters today; any width of
# letters and dots is accepted) then the encoder name. A legend line has `=` where the name would be.
_ENCODER_ROW = re.compile(r"^\s*[A-Z.]{2,10}\s+([A-Za-z0-9_-]+)(?:\s|$)")
_LIST_SEPARATOR = re.compile(r"^\s*-{3,}\s*$")


def _parse_ff_list(flag: str, text: str) -> List[str]:
    """Names in the stdout of `ffmpeg <flag>`; empty when no row was recognised."""
    names: List[str] = []
    if flag == "-filters":
        for line in text.splitlines():
            m = _FILTER_ROW.match(line)
            if m:
                names.append(m.group(1))
    elif flag == "-encoders":
        lines = text.splitlines()
        sep = next((i for i, l in enumerate(lines) if _LIST_SEPARATOR.match(l)), None)
        rows = lines[sep + 1:] if sep is not None else lines
        for line in rows:
            m = _ENCODER_ROW.match(line)
            if m and m.group(1) != "=":
                names.append(m.group(1))
    elif flag == "-bsfs":
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 1 and not parts[0].endswith(":"):
                names.append(parts[0])
    return names


def _ff_listing(binary: str, flag: str) -> Dict[str, Any]:
    """`{"names": [...], "status": parsed | unparsed | failed | missing, "detail": str}` for `ffmpeg <flag>`.

    `parsed`: rows recognised. `unparsed`: ffmpeg ran but no row matched, so the capabilities it
    covers are unknown, not absent. `failed`: ffmpeg exited non-zero. `missing`: no binary on PATH.
    """
    exe = shutil.which(binary)
    if not exe:
        return {"names": [], "status": "missing", "detail": f"{binary} not on PATH"}
    try:
        proc = subprocess.run([exe, "-hide_banner", flag], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=_DETECT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"names": [], "status": "failed", "detail": f"{binary} {flag} did not exit within {_DETECT_TIMEOUT}s"}
    except OSError as e:
        return {"names": [], "status": "failed", "detail": f"{binary} {flag}: {e}"}
    if proc.returncode != 0:
        tail = " ".join(proc.stderr.strip().splitlines()[-2:])
        return {"names": [], "status": "failed", "detail": f"{binary} {flag} exited {proc.returncode}: {tail}"}
    names = _parse_ff_list(flag, proc.stdout)
    if not names:
        return {"names": [], "status": "unparsed", "detail": f"no row recognised in `{binary} {flag}` output ({len(proc.stdout.splitlines())} lines)"}
    return {"names": names, "status": "parsed", "detail": f"{len(names)} entries"}


def _ff_list(binary: str, flag: str) -> List[str]:
    """Names from `ffmpeg -encoders` / `-filters` / `-bsfs` (empty list when ffmpeg is missing or unparsed)."""
    return _ff_listing(binary, flag)["names"]


# GPU-backed encoders are named `<codec>_<backend>` by every ffmpeg build (h264_nvenc,
# hevc_videotoolbox, av1_qsv, h264_vaapi, hevc_amf, ...); recognised by the backend suffix so a
# new codec in a future ffmpeg build needs no change here.
_GPU_ENCODER_SUFFIXES = ("_nvenc", "_videotoolbox", "_qsv", "_vaapi", "_amf")


def _gpu_encoders(encoders_listing: Dict[str, Any]) -> Dict[str, Any]:
    """GPU-backed encoders this ffmpeg BUILD was compiled with, read from `-encoders` alone.

    This proves the build carries e.g. h264_nvenc; it does NOT prove the GPU/driver on this
    machine will accept a job -- that would require actually running an encode, which doctor's
    introspection deliberately never does beyond listing/-version (see doctor()'s own docstring).
    A caller that needs to know "will a GPU encode actually work here" has to try one; this only
    answers "did this ffmpeg build even ship the capability."
    """
    status = encoders_listing["status"]
    if status != "parsed":
        return {"status": status, "detail": encoders_listing["detail"], "present": []}
    present = sorted(n for n in encoders_listing["names"] if n.endswith(_GPU_ENCODER_SUFFIXES))
    return {"status": "parsed", "present": present}


def _version_line(binary: str) -> Optional[str]:
    exe = shutil.which(binary)
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=_DETECT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    first = (proc.stdout or proc.stderr).splitlines()[:1]
    m = re.match(rf"{binary} version (\S+)", first[0]) if first else None
    return m.group(1) if m else (first[0] if first else "unknown")


def _whisper_available() -> bool:
    if shutil.which("whisper-cli") or shutil.which("whisper-cpp") or shutil.which("whisper"):
        return True
    return importlib.util.find_spec("faster_whisper") is not None or importlib.util.find_spec("whisper") is not None


def _default_font() -> str:
    from _common import BRAND_DEFAULTS
    return str(BRAND_DEFAULTS["font"])


def _drawtext_probe() -> Dict[str, Any]:
    """Actually render one frame through drawtext, rather than trusting `-filters` alone.

    `-filters` only reports whether this ffmpeg build was compiled with the filter; it never
    proves drawtext can actually execute. On some real Windows ffmpeg builds (winget's gyan.dev
    9.x), drawtext crashes with an access violation whenever it has to resolve a font through
    fontconfig -- with or without a valid fonts.conf -- so `-filters` correctly reports drawtext
    present and doctor used to report the capability `available` anyway; every tool that actually
    used it (look, scenes --sheet, overlay --text, graphics) then crashed on first real use (#100).

    This runs the cheapest real drawtext render there is: a one-frame synthetic clip, no font=
    given at all (ffmpeg's own default resolution -- the same path that crashed). A clean exit
    means drawtext genuinely works here. Anything that could not prove either way (no ffmpeg,
    timeout, an ordinary nonzero exit with a real ffmpeg error) is `unknown`, same "unknown is not
    missing" principle as every other capability here. A crash specifically -- killed by signal on
    POSIX, or an unhandled access violation surfacing as a huge unsigned exit code on Windows -- is
    the one case this function exists to catch, and folds into `missing`: the filter is present in
    the build but cannot actually be used as ffmpeg's own default would use it.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"status": "unknown", "detail": "ffmpeg not on PATH"}
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
             "-vf", "drawtext=text=x", "-frames:v", "1", "-f", "null", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=_DETECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "detail": f"drawtext probe did not exit within {_DETECT_TIMEOUT}s"}
    except OSError as e:
        return {"status": "unknown", "detail": f"drawtext probe: {e}"}
    if proc.returncode == 0:
        return {"status": "available", "detail": "one-frame drawtext render succeeded"}
    if proc.returncode < 0 or proc.returncode >= 0x80000000:
        return {"status": "missing",
                "detail": f"drawtext render crashed (exit {proc.returncode}) instead of failing cleanly -- "
                           "the filter is present in this build but cannot be used as-is, likely a fontconfig "
                           "resolution crash (see https://github.com/kajisho5/ffmpeg-skill/issues/100); "
                           "pass an explicit --font-file to every drawtext tool as a workaround"}
    tail = " ".join(proc.stderr.strip().splitlines()[-2:])
    return {"status": "unknown", "detail": f"drawtext probe exited {proc.returncode}: {tail}"}


def _font_available(font_name: str) -> Dict[str, Any]:
    """Whether `font_name` (a fontconfig family name, as passed to drawtext's `font=`) is actually
    installed, distinct from silently resolving to a substitute.

    This cannot be answered by running drawtext and checking its exit code: fontconfig substitutes
    the closest match for ANY name, known or not, so `ffmpeg -vf drawtext=font='<garbage>'` still
    exits 0 (verified against this repo's own sandbox ffmpeg -- a deliberately bogus family name
    produces the same success exit code as "DejaVu Sans"). That is exactly the "false success" this
    capability exists to catch (see issue #66): a missing font never fails the encode, it just
    silently renders with a different typeface. `fc-match` is queried instead, since it reports the
    family fontconfig actually resolved to; that only equals the request when the font is installed.
    """
    exe = shutil.which("fc-match")
    if not exe:
        return {"status": "unknown", "detail": "fc-match not on PATH; drawtext succeeding proves nothing (fontconfig substitutes silently), so availability cannot be verified"}
    try:
        proc = subprocess.run([exe, "--format=%{family}\n", font_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=_DETECT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "detail": f"fc-match did not exit within {_DETECT_TIMEOUT}s"}
    except OSError as e:
        return {"status": "unknown", "detail": f"fc-match: {e}"}
    if proc.returncode != 0:
        tail = " ".join(proc.stderr.strip().splitlines()[-2:])
        return {"status": "unknown", "detail": f"fc-match exited {proc.returncode}: {tail}"}
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    resolved = lines[0].strip() if lines else ""
    if not resolved:
        return {"status": "unknown", "detail": "fc-match produced no output"}
    if resolved.lower() == font_name.lower():
        return {"status": "available", "detail": f"fc-match resolves '{font_name}' to itself"}
    return {"status": "missing", "detail": f"fc-match substitutes '{resolved}' for '{font_name}' -- '{font_name}' is not installed"}


def required_capabilities() -> Dict[str, List[str]]:
    req: set = set()
    opt: set = set()
    for meta in TOOL_META.values():
        req.update(meta["required"])
        opt.update(o["capability"] for o in meta["optional"] if o["capability"] != "delegated")
    opt -= req
    return {"required": sorted(req), "optional": sorted(opt)}


def doctor() -> Dict[str, Any]:
    """Detect which declared capabilities this machine has. No secrets, no environment variables.

    `version` is this INSTALLED COPY's own version (read from its local package.json, same value
    `contract --json`'s `skill.version` reports) -- never fetched from the network or compared
    against the latest published release. A copy installed with `npx ffmpeg-skill` is not updated
    automatically; re-run the installer to refresh it, then `doctor` again to confirm the version
    changed. This exists so a stale installed copy is visible locally, not to check for updates.

    Three states per capability: available, missing, unknown. `unknown` means the ffmpeg listing
    that would prove it could not be read (unparsed output, ffmpeg failure); it is never folded into
    `missing` (a filter that exists is not reported absent) nor into `available` (a failed detection
    is not a pass). `ok` is true only when nothing required is missing or unknown.

    `gpu_encoders` is a separate, honest answer to a question none of the required/optional
    capabilities above ask: which GPU-backed encoders (nvenc, videotoolbox, qsv, vaapi, amf) this
    ffmpeg BUILD carries, from `-encoders` alone. No tool here requires or uses one -- every tool
    still assumes CPU x264/x265 -- so `gpu_encoders` never affects `ok` or any tool's `usable`. It
    only proves the build shipped the capability, never that the GPU/driver on this machine will
    actually accept a job (that needs a real encode, which this introspection never runs).

    `fonts` is the same kind of informational answer for the default drawtext font (caption.py's
    --animate/--karaoke, graphics.py's templates -- see issue #66): available/missing/unknown for
    whether BRAND_DEFAULTS["font"] ("DejaVu Sans") is actually installed, not silently substituted
    by fontconfig. It never affects `ok` or a tool's `usable` -- a missing font is not a broken
    tool, drawtext still runs and still writes an artifact, it may just render with a different
    typeface than requested (which is why this exists: that substitution is otherwise invisible).
    """
    listings = {
        "encoders": _ff_listing("ffmpeg", "-encoders"),
        "filters": _ff_listing("ffmpeg", "-filters"),
        "bsfs": _ff_listing("ffmpeg", "-bsfs"),
    }
    sets = {k: set(v["names"]) for k, v in listings.items()}
    state: Dict[str, str] = {}  # capability -> available | missing | unknown
    wanted = required_capabilities()
    drawtext_probe: Optional[Dict[str, Any]] = None

    def _from(kind: str, name: str) -> str:
        lst = listings[kind]
        if lst["status"] == "parsed":
            return "available" if name in sets[kind] else "missing"
        if lst["status"] == "missing":
            return "missing"  # no ffmpeg at all: nothing it provides is available
        return "unknown"

    for cap in wanted["required"] + wanted["optional"]:
        if cap == "ffmpeg":
            state[cap] = "available" if shutil.which("ffmpeg") else "missing"
        elif cap == "ffprobe":
            state[cap] = "available" if shutil.which("ffprobe") else "missing"
        elif cap.startswith("encoder:"):
            state[cap] = _from("encoders", cap[8:])
        elif cap == "filter:drawtext":
            listing_state = _from("filters", "drawtext")
            if listing_state == "available":
                # Only escalate an "available" listing to "missing" on an unambiguous crash --
                # an ordinary nonzero exit (a real ffmpeg's own -h/-filters-only build variance, or
                # in tests a fake ffmpeg shim that only implements -filters/-encoders/-bsfs/-version)
                # proves nothing either way, so it leaves the listing-based result standing rather
                # than downgrading it; see _drawtext_probe()'s own docstring for why a crash alone
                # is the one case this exists to catch.
                probe = _drawtext_probe()
                if probe["status"] == "missing":
                    drawtext_probe = probe
                    state[cap] = "missing"
                else:
                    state[cap] = "available"
            else:
                state[cap] = listing_state
        elif cap.startswith("filter:"):
            state[cap] = _from("filters", cap[7:])
        elif cap.startswith("bsf:"):
            state[cap] = _from("bsfs", cap[4:])
        elif cap == "external:whisper":
            state[cap] = "available" if _whisper_available() else "missing"
        else:
            state[cap] = "missing"
    available = sorted(c for c, st in state.items() if st == "available")
    missing_required = sorted(c for c in wanted["required"] if state[c] == "missing")
    missing_optional = sorted(c for c in wanted["optional"] if state[c] == "missing")
    unknown = sorted(c for c, st in state.items() if st == "unknown")
    unknown_required = [c for c in unknown if c in wanted["required"]]
    errors = [f"{k}: {v['detail']}" for k, v in listings.items() if v["status"] in ("unparsed", "failed")]
    if drawtext_probe is not None and drawtext_probe["status"] != "available":
        errors.append(f"filter:drawtext: {drawtext_probe['detail']}")
    return {
        "version": skill_version(),
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "ffmpeg": _version_line("ffmpeg"),
        "ffprobe": _version_line("ffprobe"),
        "available": available,
        "missing": missing_required,
        "missing_optional": missing_optional,
        "unknown": unknown,
        "detection": {k: {"status": v["status"], "count": len(v["names"]), "detail": v["detail"]} for k, v in listings.items()},
        "errors": errors,
        "ok": not missing_required and not unknown_required,
        "tools": _tool_usability(state),
        "gpu_encoders": _gpu_encoders(listings["encoders"]),
        "fonts": _fonts_capability(),
    }


def _fonts_capability() -> Dict[str, Any]:
    font = _default_font()
    result = _font_available(font)
    return {"default_font": font, "status": result["status"], "detail": result["detail"]}


def _capability_fix_hint(cap: str) -> str:
    """One-line, plain-language remedy for a single missing/unknown capability."""
    if cap in ("ffmpeg", "ffprobe"):
        from _common import INSTALL_HINTS
        hint = INSTALL_HINTS.get(platform.system(), "see https://ffmpeg.org/download.html").strip().splitlines()[0].strip()
        return f"install ffmpeg: {hint}"
    system = platform.system()
    if system == "Darwin":
        full_hint = "on macOS, brew install ffmpeg-full (the plain formula lacks subtitles/drawtext/zscale)"
    elif system == "Windows":
        full_hint = "on Windows, winget install Gyan.FFmpeg (the gyan.dev full build carries subtitles/drawtext/zscale; a plain choco ffmpeg package can lack them)"
    else:
        full_hint = "install/build ffmpeg with it enabled"
    if cap.startswith("encoder:"):
        return f"this ffmpeg build has no {cap[8:]} encoder; {full_hint}"
    if cap == "filter:drawtext":
        return ("drawtext crashed instead of rendering a frame (see errors[] for the exit detail) -- "
                 "every drawtext tool already resolves a concrete font file automatically when one can "
                 "be found (#100); if it still crashes, use --no-timecode with look.py or scenes.py "
                 "--sheet to skip drawtext entirely, or pass --font-file explicitly to overlay.py/"
                 "graphics.py (the two that accept it) rather than relying on font= resolution")
    if cap.startswith("filter:"):
        return f"this ffmpeg build has no {cap[7:]} filter; {full_hint}"
    if cap.startswith("bsf:"):
        return f"this ffmpeg build has no {cap[4:]} bitstream filter; {full_hint}"
    if cap == "external:whisper":
        return "install a local whisper (whisper-cli, whisper-cpp, faster-whisper or openai-whisper) for --transcribe"
    return f"'{cap}' is not available; see docs/contract.md"


def _tool_usability(state: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Per-tool usable/missing/unknown, folded from the same capability `state` doctor already
    computed. Answers "can I run this tool on this machine today", not just "what capabilities
    exist" -- a caller reading only `available`/`missing` still has to cross-reference each tool's
    own required-capability list by hand to answer that."""
    tools: Dict[str, Dict[str, Any]] = {}
    for name, meta in TOOL_META.items():
        required = list(meta["required"])
        missing = [c for c in required if state.get(c) == "missing"]
        unknown = [c for c in required if state.get(c) == "unknown"]
        entry: Dict[str, Any] = {"usable": "no" if missing else ("unknown" if unknown else "yes")}
        if missing:
            entry["missing"] = missing
            entry["fix"] = "; ".join(dict.fromkeys(_capability_fix_hint(c) for c in missing))
        if unknown:
            entry["unknown"] = unknown
        tools[name] = entry
    return tools


# Cross-repository Capability ids (kajisho5/AI-video-production-OS docs/SPEC.md
# `CapabilityContract.provides`), matching the ids already assigned to these 21 tools in
# that project's own docs/CAPABILITY_MATRIX.md section 9: "ffmpeg-skill's 21 raw tools ...
# are Capabilities in their own right, independent of the higher-level Skills that
# delegate to them". Each tool's own id is `ffmpeg-skill/<tool>` (a slash, matching every
# ToolSpec.id here); the Capability id uses a dot - `ffmpeg-skill.<tool>` - the same
# `<domain>.<verb>`-shaped convention every other Skill's Capability ids use elsewhere in
# that project (`video.trim`, `audio.gain`, ...), with "ffmpeg-skill" as the domain.
def capability_provides() -> List[Dict[str, str]]:
    return [{"id": f"{SKILL_ID}.{name}", "lifecycle": "EXPERIMENTAL", "tool_id": f"{SKILL_ID}/{name}"} for name in public_tools()]


# Abstract, domain-shaped capability ids (`<domain>.<verb>`, matching the convention `provides`
# already documents for cross-repo Capability ids) that a planning agent can resolve without
# already knowing this skill's tool names. Unlike `provides` (one entry per tool, id derived
# from the tool name), this is a hand-authored, many-to-one table: several of these ids name a
# tool PLUS the fixed parameters that pin it to that specific behaviour (`video.reframe` is
# `fit.py` with `fit=crop` fixed, not bare `fit.py`, which also speed-ramps and pads). This is
# still purely descriptive -- a caller still builds and runs the named tool's own CLI/MCP call
# from its `input_schema`; nothing here executes or chooses on the caller's behalf. Deliberately
# excludes any capability that would require judgment to resolve (e.g. no `video.highlight`:
# `scenes.py --highlights` ranks by a measured proxy, never by understood content -- see
# SKILL.md "What this skill does and does not decide" -- so it is not offered as a capability
# a planner can blindly delegate to). `media.proxy` (a low-bitrate, fast-decode proxy, distinct
# from `export.py`'s delivery presets, which target visual quality over size/speed) resolves to
# `proxy.py` -- itself a purely mechanical resize+re-encode with no opinion on which asset should
# be proxied or what for.
CAPABILITY_MAP: List[Dict[str, Any]] = [
    {"capability": "video.trim", "tool_id": f"{SKILL_ID}/cut", "params": {}},
    {"capability": "video.reframe", "tool_id": f"{SKILL_ID}/fit", "params": {"fit": "crop"}},
    {"capability": "audio.loudness", "tool_id": f"{SKILL_ID}/loudness", "params": {}},
    {"capability": "subtitle.burn", "tool_id": f"{SKILL_ID}/caption", "params": {}},
    {"capability": "media.stream.inspect", "tool_id": f"{SKILL_ID}/probe", "params": {}},
    {"capability": "media.frames.extract", "tool_id": f"{SKILL_ID}/look", "params": {}},
    {"capability": "media.proxy", "tool_id": f"{SKILL_ID}/proxy", "params": {}},
]


def capability_map(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate CAPABILITY_MAP against the live tool specs before returning it. A fixed param
    that isn't a real input_schema property is drift, not a typo to ship silently (same "fail
    loudly" posture as tool_spec()'s missing-TOOL_META check). A tool_id that no longer exists
    is not drift in that sense -- a tool can legitimately be removed -- so that capability is
    dropped from the map rather than crashing the whole contract build."""
    by_id = {t["id"]: t for t in tools}
    result = []
    for entry in CAPABILITY_MAP:
        spec = by_id.get(entry["tool_id"])
        if spec is None:
            continue
        props = spec["input_schema"]["properties"]
        for key in entry["params"]:
            if key not in props:
                raise RuntimeError(f"capability {entry['capability']!r} sets param {key!r} which is not in {entry['tool_id']}'s input_schema")
        result.append(dict(entry))
    return result


# ----------------------------------------------------------------------------- contract
def tool_spec(name: str, version: str) -> Dict[str, Any]:
    if name not in TOOL_META:
        # a public script without metadata is drift: fail loudly instead of guessing its role or capabilities
        raise RuntimeError(f"scripts/{name}.py is public but has no TOOL_META entry in scripts/_contract.py; add one (or prefix the file with '_')")
    meta = TOOL_META[name]
    parser = _capture_parser(HERE / f"{name}.py")
    schema = input_schema(parser)
    # structured key -> CLI flag where key.replace("_", "-") is not the long option (MCP uses the same table)
    exceptions: Dict[str, str] = {}
    for dest, prop in schema["properties"].items():
        if prop["cli"] == "positional":
            continue
        longs = [f for f in prop["cli"] if f.startswith("--")]
        if dest == "output":
            exceptions[dest] = "-o"
        elif name == "loudness" and dest == "lufs":
            exceptions[dest] = "-I"
        elif "--" + dest.replace("_", "-") not in longs:
            exceptions[dest] = longs[0] if longs else prop["cli"][0]
    supports_dry_run = "dry_run" in schema["properties"] and name != "verify"
    return {
        "id": f"{SKILL_ID}/{name}",
        "name": name,
        "version": version,
        "description": (parser.description or "").strip().splitlines()[0] if parser.description else "",
        "executable": f"scripts/{name}.py",
        "role": meta["role"],
        "capabilities": {"required": list(meta["required"]), "optional": list(meta["optional"])},
        "inputs": list(meta["inputs"]),
        "outputs": list(meta["outputs"]),
        "input_schema": schema,
        "output_schema": output_schema(name, meta),
        "supports_dry_run": supports_dry_run,
        "dry_run": {"supported": supports_dry_run,
                    "ffmpeg_execution": "full" if not supports_dry_run else "analysis_only" if name in DRY_RUN_ANALYSIS else "none",
                    "semantics": "prints the ffmpeg command lines that would run; no output file is written",
                    **({"note": DRY_RUN_ANALYSIS.get(name) or DRY_RUN_NOTES[name]} if name in DRY_RUN_ANALYSIS or name in DRY_RUN_NOTES else {})},
        "supports_json": "json" in schema["properties"],
        "mutates_input": False,
        "produces_artifact": meta["produces_artifact"],
        "verification": {"required": bool(meta["verify"]), "tools": [f"{SKILL_ID}/{t}" for t in meta["verify"]]},
        # a tool with no declared entry reports "conditional" rather than guessing "always" or
        # "never" -- same "unknown is not missing" principle as doctor's capability detection
        "reencodes_video": REENCODE_META.get(name, {}).get("video", "conditional"),
        "reencodes_audio": REENCODE_META.get(name, {}).get("audio", "conditional"),
        **({"reencode_note": REENCODE_META[name]["note"]} if REENCODE_META.get(name, {}).get("note") else {}),
        "requires_visual_verification": meta["visual"],
        "audio_only": meta["audio_only"],
        "video_required": meta["video_required"],
        "deterministic_inputs": meta["deterministic"],
        "idempotency_hint": meta["idempotency"],
        "mcp": {"tool": name, "positional": schema["positional"], "argument_exceptions": exceptions},
    }


# ----------------------------------------------------------------------------- MCP derivation
# tools that print JSON without --json (probe) or whose primary output is a file path (look): the transport
# does not append --json for them (stated in invocation.structured.argument_mapping.json)
MCP_JSON_EXEMPT = ("look", "probe")
MCP_STRUCTURED_NOTE = ("Structured arguments: keys are the input_schema property names (argparse dests), positionals "
                       "are passed by name, output -> -o. Or argv: the raw CLI list (non-canonical; all other keys are then ignored). "
                       "Media paths must be absolute.")


def mcp_input_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a ToolSpec.input_schema into the JSON Schema an MCP tools/list entry carries.

    Deterministic and lossless where JSON Schema can express argparse semantics:
      - properties keep type / enum / default / description / items; the ffmpeg-skill-only keys
        (`cli`, `common`) are dropped, positionals get a "(positional N)" prefix in the description;
      - required fields, mutually exclusive groups (`not required [a, b]` per pair) and required
        groups (`anyOf required`) apply to the structured branch;
      - the raw-argv compatibility branch (`argv` present) lifts those constraints, which JSON Schema
        expresses as a top-level anyOf of the two branches.
    Not expressible and therefore documented rather than encoded: which keys the tool ignores when
    `argv` is given (all of them), and argparse's `%(default)s` help interpolation (already applied).
    """
    src = spec["input_schema"]
    props: Dict[str, Any] = {}
    positional = list(src.get("positional", []))
    for dest in sorted(src["properties"]):
        p = src["properties"][dest]
        out: Dict[str, Any] = {"type": p["type"]}
        if p["type"] == "array":
            out["items"] = dict(p.get("items", {"type": "string"}))
        desc = p.get("description", "")
        if dest in positional:
            desc = f"(positional {positional.index(dest) + 1}) {desc}".strip()
        if desc:
            out["description"] = desc
        for key in ("enum", "default"):
            if key in p:
                out[key] = p[key]
        props[dest] = out
    props["argv"] = {"type": "array", "items": {"type": "string"}, "description": "raw CLI arguments (non-canonical compatibility path; when present every other key is ignored)"}
    structured: Dict[str, Any] = {}
    if src.get("required"):
        structured["required"] = list(src["required"])
    all_of: List[Dict[str, Any]] = []
    for group in src.get("mutually_exclusive", []):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                all_of.append({"not": {"required": [a, b]}})
    if all_of:
        structured["allOf"] = all_of
    one_of = [[{"required": [d]} for d in group] for group in src.get("one_of_required", [])]
    if one_of:
        structured["anyOf"] = one_of[0] if len(one_of) == 1 else [{"allOf": [{"anyOf": g} for g in one_of]}]
    schema: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if structured:
        schema["anyOf"] = [{"required": ["argv"]}, structured]
    return schema


def mcp_tool(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The MCP tools/list entry for a ToolSpec: name, description and the derived inputSchema."""
    return {"name": spec["name"], "description": f"{spec['description']} {MCP_STRUCTURED_NOTE}".strip(), "inputSchema": mcp_input_schema(spec)}


def mcp_tools(detect: bool = False) -> List[Dict[str, Any]]:
    return [mcp_tool(spec) for spec in build(detect=detect)["tools"]]


def build(detect: bool = True) -> Dict[str, Any]:
    version = skill_version()
    tools = [tool_spec(n, version) for n in public_tools()]
    wanted = required_capabilities()
    caps: Dict[str, Any] = {"required": wanted["required"], "optional": wanted["optional"], "naming": "ffmpeg | ffprobe | encoder:<name> | filter:<name> | bsf:<name> | external:whisper"}
    if detect:
        d = doctor()
        caps.update({"available": d["available"], "missing": d["missing"], "missing_optional": d["missing_optional"],
                     "unknown": d["unknown"], "detection": d["detection"], "detected_by": "doctor"})
    return {
        "contract_version": CONTRACT_VERSION,
        "skill": {
            "id": SKILL_ID,
            "version": version,
            "description": skill_description(),
            "execution_mode": "local",
            "kind": "execution",
            "entrypoints": {
                "cli": "python3 scripts/<tool>.py [args] [--json] [--dry-run]",
                "mcp": "python3 mcp/server.py (stdio JSON-RPC; tools/list == this tool list)",
                "contract": "python3 scripts/_contract.py --json  |  ffmpeg-skill contract --json",
                "doctor": "python3 scripts/_contract.py doctor --json  |  ffmpeg-skill doctor --json",
            },
            "not_provided": ["AI reasoning", "decisions", "production plans", "project IR", "approvals", "network access", "transcription engine"],
        },
        "requirements": {"python": ">=3.9 (standard library only)", "ffmpeg": ">=5.0", "ffprobe": ">=5.0", "node": ">=16 (npx installer only)"},
        "execution": {
            "shell": False,
            "arbitrary_executables": False,
            "subprocess": "argv list only: [python3, scripts/<tool>.py, ...] and [ffmpeg|ffprobe, ...] resolved from PATH",
            "network": False,
            "input_mutation": False,
        },
        "invocation": {
            "structured": {
                "canonical": True,
                "transports": ["cli", "mcp"],
                "argument_mapping": {
                    "positional": "listed in input_schema.positional, in order; array values expand to several arguments",
                    "options": "key -> --key with '_' replaced by '-'; booleans are flags; arrays repeat the flag; input_schema.properties[key].cli lists the accepted spellings",
                    "exceptions": "per tool in mcp.argument_exceptions (key -> flag), e.g. output -> -o, loudness.lufs -> -I, graphics.count_from -> --from",
                    "json": "--json is appended for every tool except look and probe (probe prints JSON by default)",
                },
            },
            "raw_argv": {"canonical": False, "transports": ["mcp"], "note": "MCP tools also accept {\"argv\": [...]} for CLI compatibility; it is still bound to the named script, never a shell"},
        },
        "roles": ROLES,
        "idempotency_hints": IDEMPOTENCY,
        "verification_policy": {
            "probe_first": "run ffmpeg-skill/probe on every input before planning",
            "verify_last": "run the tools named in each ToolSpec.verification after it wrote an artifact",
            "visual": "when requires_visual_verification is true, run ffmpeg-skill/look on the output and inspect the PNG",
            "audio_only": "audio-only inputs and audio-only tools never need ffmpeg-skill/look",
            "check_rows": "ffmpeg-skill/check rows carry kind=format (fix) or kind=judgement (decide with the user)",
        },
        "json_output": {
            "success": {"status": "completed", "exit_code": 0, "stdout": "one JSON document (output_schema)"},
            "failure": {"status": "failed", "exit_code": "non-zero (127 when ffmpeg/ffprobe is missing)", "stdout": "{\"status\": \"failed\", \"exit_code\": N, \"error\": {\"kind\": ..., \"message\": ...}, \"commands\": [...]} when --json was given", "stderr": "human-readable message"},
            "error_kinds": {"input": "missing or unsuitable input, bad arguments", "ffmpeg": "ffmpeg/ffprobe returned an error (message carries the last stderr lines)", "output": "ffmpeg exited 0 but the artifact is missing, empty or unreadable (an empty file is removed)", "missing_tool": "ffmpeg or ffprobe not on PATH"},
            "success_criterion": "exit 0 AND the output exists AND is non-empty AND ffprobe reads a stream from it; only then is status completed printed and the output probe attached",
        },
        "capabilities": caps,
        "tools": tools,
        "provides": capability_provides(),
        "capability_map": capability_map(tools),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["contract", "doctor"], default="contract")
    ap.add_argument("--json", action="store_true", help="JSON on stdout (the contract is always JSON)")
    ap.add_argument("--static", action="store_true", help="omit environment detection (available / missing capabilities)")
    args = ap.parse_args()
    if args.command == "doctor":
        d = doctor()
        if args.json:
            print(json.dumps(d, indent=2, sort_keys=True))
        else:
            print(f"ffmpeg-skill {d['version']} (this installed copy; re-run `npx ffmpeg-skill` to refresh it -- copies are not updated automatically)")
            print(f"python {d['python']}; ffmpeg {d['ffmpeg'] or 'MISSING'}; ffprobe {d['ffprobe'] or 'MISSING'}")
            print(f"available: {', '.join(d['available'])}")
            print(f"missing required: {', '.join(d['missing']) or 'none'}")
            print(f"missing optional: {', '.join(d['missing_optional']) or 'none'}")
            if d["unknown"]:
                print(f"unknown (detection failed, not proven missing): {', '.join(d['unknown'])}")
            not_usable = sorted(name for name, t in d["tools"].items() if t["usable"] != "yes")
            if not_usable and d["ok"]:
                print(f"note: overall 'ok' means nothing REQUIRED BY EVERY TOOL is missing -- {len(not_usable)} tool(s) still can't run today: {', '.join(not_usable)} (see doctor --json .tools for why)")
            gpu = d["gpu_encoders"]
            if gpu["status"] == "parsed":
                print(f"GPU-backed encoders in this build: {', '.join(gpu['present']) or 'none'} (no tool here uses one yet; this build-presence check does not prove the GPU/driver will accept a job)")
            fonts = d["fonts"]
            print(f"default drawtext font '{fonts['default_font']}': {fonts['status']} ({fonts['detail']})")
            for err in d["errors"]:
                print(f"detection error: {err}", file=sys.stderr)
        if d["ok"]:
            return 0
        # 1: something required is missing; 2: nothing proven missing but a required capability is unknown
        return 1 if d["missing"] else 2
    print(json.dumps(build(detect=not args.static), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
