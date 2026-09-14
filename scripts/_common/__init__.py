#!/usr/bin/env python3
"""Shared helpers for ffmpeg-skill scripts.

Standard library only. Locates ffmpeg/ffprobe on PATH, runs them with clear
error reporting, and provides a compact media probe used by every script.

Since the refactor release after 1.15.0 the helpers live in one module per responsibility --
runner (process execution and timeouts), probe (ffprobe and the measured facts), decision (the
pure copy-vs-re-encode and capability choices), emit (result documents, die(), info()), color
(colour tags and the HDR paths) and text (fonts, scripts, emoji, drawtext) -- and this file is a
facade that re-exports every name they define. `import _common` and `from _common import x` mean
exactly what they meant when this was one 3072-line module; nothing else about the package is
part of the contract.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import types as _types
import unicodedata
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The standard-library modules above were module-level names of the old single-file _common and
# stay reachable as `_common.<mod>`: a test that stands `shutil.which` up differently reaches for
# `_common.shutil`, and it has to be the one module object every submodule calls through -- which
# it is, since an `import` binds the same object everywhere.

# Every script prints paths, help text and reports that may contain non-ASCII (Japanese examples,
# arrows). On Windows the console streams default to a legacy code page and raise
# UnicodeEncodeError; make them UTF-8 with replacement so a --help never crashes on encoding.
# (First thing the package does, before any submodule can print.)
for _stream in (sys.stdout, sys.stderr):
    try:
        if getattr(_stream, "encoding", "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# The submodules import each other; importing runner first pulls the whole graph in (see the
# deferred imports at the foot of runner.py and emit.py). The `from ... import ...` lines below
# are the facade proper: every public and underscore name any caller in scripts/, mcp/, tests/,
# demos/ or evals/ has ever reached for through `_common`.

from _common.runner import (
    add_common, apply_common, _check_existing_output, _check_no_overwrite_input, _check_output_path, child_args,
    child_limit, _CHILDREN, _cleanup_partial_output, _cmdline, CODECS, Context, _CRF_DEFAULT, DEFAULT_TIMEOUT,
    _DRAWTEXT_PENDING, _DRAWTEXT_TMPDIR, _drawtext_tmpdir, dry_run_input_pending, _ENCODERS, _env_timeout,
    ERROR_CODE, ERROR_RETRYABLE, EVEN_SCALE, _execute, _fail, ffmpeg_base, ffmpeg_encoders, _FFMPEG_VERSION,
    ffmpeg_version, flush_drawtext_textfiles, INSTALL_HINTS, install_signal_handlers, _is_ffmpeg, _limit_for,
    _odd_dimension_retry, _on_signal, _OutputLock, _pid_dead, place_output, PROBE_TIMEOUT, _progress_line,
    read_text_or_die, refuse_output_is_input, _remember_output, require_tool, run, run_analysis, _run_captured,
    run_keeping_subtitles, run_tool, _run_with_progress, shell_quote, _SIGNALS_INSTALLED, _stage_existing_output,
    STATE, _timed_out, _unwatch, _watch, X264_PRESETS
)
from _common.emit import (
    _brief, _BRIEF_DROP, _brief_summary, _CURRENT_CTX, die, emit, info, _plan_at_exit, _plan_inputs, _PLAN_STRIP,
    PLAN_VERSION, print_json, _result_v2, _set_current_ctx, _V2_HANDLED, write_plan
)
from _common.probe import (
    analyze_levels, _aspect_string, _bit_depth, decode_pcm_mono, detect_scenes, detect_silences, fingerprint,
    _fraction, keyframes_near, SCORE_RE, SIL_RE,
    measured_level_dbfs, MEDIA_EXT, _output_failed, probe, rms_envelope, _to_float, _to_int, verify_output
)
from _common.decision import (
    aac_args, add_pad_fill_args, audio_codec_for, AUDIO_CODECS, brand_caption_style, BRAND_DEFAULTS,
    description_block, _evidence_rank, fmt_chapter_time, propose_chapters,
    brand_states_font, cfr_args, concat_list_line, db_to_linear, default_output, encoder_args, escape_filter_path,
    fmt_secs, fmt_smpte_time, fmt_srt_time, is_audio_output, load_brand, MissingFpsError, pad_filters, parse_time,
    signed_time_arg, SVT_PRESET, time_arg, video_args, x264_args, _x264_raw
)
from _common.color import (
    bt709_tag_args, color_hex, _COLOR_TOKEN_RE, _sdr_bt709, validate_color
)
from _common.text import (
    ADVANCE_EM, BIDI_SCRIPTS, _char_em, char_script, default_font_file, detect_script, drawtext_boxborderw,
    drawtext_shaping, drawtext_text_opts, emoji_asset_for, EMOJI_ASSET_HINT, emoji_clusters, emoji_codepoint_name,
    _EMOJI_COLOR_FAMILIES, _emoji_color_font, emoji_filter_chain, _emoji_name_candidates, EMOJI_RANGES,
    _EMOJI_REGIONAL, emoji_support, _EMOJI_SUPPORT_CACHE, _EMOJI_TAIL, escape_drawtext, _family_rank, FC_LANG,
    _fc_list_fonts, FC_UNKNOWN, font_covers_script, font_family_for_script, font_family_of_file, FONT_FLAG_HINT,
    font_for_script, FONT_INSTALL_HINT, fonts_dir_covers_script, has_emoji, _is_emoji_base, _is_emoji_char,
    _is_mark, _KEYCAP, _KEYCAP_BASES, LANGUAGE_NAMES, LATIN_EM, LEADING_VOWELS, _libass_color_probe, needs_shaping,
    NO_SPACE_SCRIPTS, PREFERRED_FAMILIES, resolve_emoji_assets, _SCRIPT_FONT_CACHE, _script_font_entry,
    _atoms, best_break, _bare_word, break_penalty, _break_spaced, _cut_penalty, _fix_orphans, _fix_weak_lines,
    _function_words, FUNCTION_WORDS, _HYPHENS, _is_hiragana, _is_ideograph, _is_kana, _is_weak_line,
    JA_NO_LINE_END, JA_NO_LINE_START, JA_PARTICLE_WORDS, JA_PARTICLES, JA_SENTENCE_END, _join, ORPHAN_MIN_EM,
    PENALTY_FORBIDDEN, PENALTY_FUNCTION_WORD, PENALTY_FUNCTION_WORD_START, PENALTY_IDEOGRAPHS,
    PENALTY_NEUTRAL, PENALTY_OKURIGANA,
    PENALTY_PARTICLE, PENALTY_SENTENCE_END, _rebalance, _rebalance_phrase, SAFE_WIDTH_FRACTION, _split_hyphens,
    _particle_ends, _particle_starts, wrap_text, wrap_variants, WRAP_MODES,
    script_font_for_text, script_font_status, _script_font_uncached, _SCRIPT_RANGES, SCRIPTS, _SHAPING_BUILD_CACHE,
    SHAPING_SCRIPTS, text_width_em, _VS15, _VS16, WINDOWS_FONTS, _ZWJ
)

from _common import color, decision, runner, text  # noqa: F401,E402

# `_common.emit` and `_common.probe` are the FUNCTIONS, as they have always been -- the
# from-imports above rebound the package attribute the submodule import had set. The two modules
# that share a name with a helper are reached through sys.modules instead; nothing outside this
# package refers to them. Consequently `import _common.emit` / `import _common.probe` bind the
# function, not the module: reach the modules as `from _common import emit as _` never, use
# `sys.modules["_common.emit"]` or `importlib.import_module("_common.emit")` instead.
_emit_module = sys.modules["_common.emit"]
_probe_module = sys.modules["_common.probe"]

_MODULES = (runner, _emit_module, _probe_module, decision, color, text)


class _Facade(_types.ModuleType):
    """The package module's own type, so that rebinding a name on the facade rebinds it on the
    module that defines it.

    Tests reach into `_common` to stand a name up differently for one case -- `_common._FFMPEG_VERSION
    = (7, 1)`, `mock.patch("_common.<name>")`. While this was one module that simply worked; against
    a package, a plain re-export is a second binding and the defining module goes on calling its
    own. Mirroring the assignment keeps those call sites honest without asking every helper to look
    itself up through the facade. Names mutated in place (STATE, the caches) need none of this --
    the facade re-exports the same object.
    """

    # The globals a helper REBINDS (`global x; x = ...`) live in their submodule; the facade's
    # own copy is the import-time binding and would read stale. Reads of these names go to the
    # defining module (audit 14, P1-1); every other name is a plain re-export of the same object.
    _LIVE = {
        "_FFMPEG_VERSION": "runner", "_CRF_DEFAULT": "runner", "_SIGNALS_INSTALLED": "runner",
        "_DRAWTEXT_TMPDIR": "runner", "_ENCODERS": "runner", "_CURRENT_CTX": "emit",
    }

    def __getattribute__(self, name):
        live = _types.ModuleType.__getattribute__(self, "_LIVE")
        if name in live:
            return getattr(sys.modules["_common." + live[name]], name)
        return _types.ModuleType.__getattribute__(self, name)

    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        if name.startswith("__") and name.endswith("__"):
            return   # importlib.reload() rewrites __file__/__spec__: those stay per module (P1-2)
        for _m in _MODULES:
            if name in _m.__dict__:
                _types.ModuleType.__setattr__(_m, name, value)

    def __delattr__(self, name):
        _types.ModuleType.__delattr__(self, name)
        if name.startswith("__") and name.endswith("__"):
            return
        for _m in _MODULES:
            if name in _m.__dict__:
                _types.ModuleType.__delattr__(_m, name)


sys.modules[__name__].__class__ = _Facade

__all__ = [
    "Any", "Dict", "Fraction", "List", "Optional", "Path", "Sequence", "Tuple", "argparse", "json", "math", "os",
    "platform", "re", "shutil", "subprocess", "sys", "unicodedata",
    "aac_args", "add_common", "add_pad_fill_args", "ADVANCE_EM", "analyze_levels", "apply_common", "detect_scenes", "detect_silences", "SCORE_RE", "SIL_RE", "_aspect_string",
    "audio_codec_for", "AUDIO_CODECS", "BIDI_SCRIPTS", "_bit_depth", "brand_caption_style", "BRAND_DEFAULTS",
    "brand_states_font", "_brief", "_BRIEF_DROP", "_brief_summary", "bt709_tag_args", "cfr_args", "_char_em",
    "char_script", "_check_existing_output", "_check_no_overwrite_input", "_check_output_path", "child_args",
    "child_limit", "_CHILDREN", "_cleanup_partial_output", "_cmdline", "CODECS", "color_hex", "_COLOR_TOKEN_RE",
    "concat_list_line", "Context", "_CRF_DEFAULT", "_CURRENT_CTX", "db_to_linear", "decode_pcm_mono", "description_block", "_evidence_rank", "fmt_chapter_time", "propose_chapters",
    "default_font_file", "default_output", "DEFAULT_TIMEOUT", "detect_script", "die", "drawtext_boxborderw",
    "_DRAWTEXT_PENDING", "drawtext_shaping", "drawtext_text_opts", "_DRAWTEXT_TMPDIR", "_drawtext_tmpdir",
    "dry_run_input_pending", "emit", "emoji_asset_for", "EMOJI_ASSET_HINT", "emoji_clusters",
    "emoji_codepoint_name", "_EMOJI_COLOR_FAMILIES", "_emoji_color_font", "emoji_filter_chain",
    "_emoji_name_candidates", "EMOJI_RANGES", "_EMOJI_REGIONAL", "emoji_support", "_EMOJI_SUPPORT_CACHE",
    "_EMOJI_TAIL", "encoder_args", "_ENCODERS", "_env_timeout", "ERROR_CODE", "ERROR_RETRYABLE", "escape_drawtext",
    "escape_filter_path", "EVEN_SCALE", "_execute", "_fail", "_family_rank", "FC_LANG", "_fc_list_fonts",
    "FC_UNKNOWN", "ffmpeg_base", "ffmpeg_encoders", "_FFMPEG_VERSION", "ffmpeg_version", "fingerprint",
    "flush_drawtext_textfiles", "fmt_secs", "fmt_smpte_time", "fmt_srt_time", "font_covers_script",
    "font_family_for_script", "font_family_of_file", "FONT_FLAG_HINT", "font_for_script", "FONT_INSTALL_HINT",
    "fonts_dir_covers_script", "_fraction", "has_emoji", "info", "INSTALL_HINTS", "install_signal_handlers",
    "is_audio_output", "_is_emoji_base", "_is_emoji_char", "_is_ffmpeg", "_is_mark", "_KEYCAP", "_KEYCAP_BASES",
    "keyframes_near", "LANGUAGE_NAMES", "LATIN_EM", "LEADING_VOWELS", "_libass_color_probe", "_limit_for",
    "load_brand", "measured_level_dbfs", "MEDIA_EXT", "MissingFpsError", "needs_shaping", "NO_SPACE_SCRIPTS",
    "_odd_dimension_retry", "_on_signal", "_output_failed", "_OutputLock", "pad_filters", "parse_time", "_pid_dead",
    "place_output", "_plan_at_exit", "_plan_inputs", "_PLAN_STRIP", "PLAN_VERSION", "PREFERRED_FAMILIES",
    "print_json", "probe", "PROBE_TIMEOUT", "_progress_line", "read_text_or_die", "refuse_output_is_input",
    "_remember_output", "require_tool", "resolve_emoji_assets", "_result_v2", "rms_envelope", "run", "run_analysis",
    "_run_captured", "run_keeping_subtitles", "run_tool", "_run_with_progress", "_SCRIPT_FONT_CACHE",
    "_script_font_entry", "script_font_for_text", "script_font_status", "_script_font_uncached", "_SCRIPT_RANGES",
    "SCRIPTS", "_sdr_bt709", "_set_current_ctx", "_SHAPING_BUILD_CACHE", "SHAPING_SCRIPTS", "shell_quote",
    "_SIGNALS_INSTALLED", "signed_time_arg", "_stage_existing_output", "STATE", "SVT_PRESET", "text_width_em",
    "time_arg", "_timed_out", "_to_float", "_to_int", "_unwatch", "_V2_HANDLED", "validate_color", "verify_output",
    "video_args", "_VS15", "_VS16", "_watch", "WINDOWS_FONTS", "write_plan", "x264_args", "X264_PRESETS",
    "_x264_raw", "_ZWJ",
    "_atoms", "best_break", "_bare_word", "break_penalty", "_break_spaced", "_cut_penalty", "_fix_orphans",
    "_fix_weak_lines", "_function_words", "FUNCTION_WORDS", "_HYPHENS", "_is_hiragana", "_is_ideograph",
    "_is_kana", "_is_weak_line", "JA_NO_LINE_END", "JA_NO_LINE_START", "JA_PARTICLE_WORDS", "JA_PARTICLES",
    "PENALTY_FUNCTION_WORD_START",
    "JA_SENTENCE_END", "_join", "ORPHAN_MIN_EM", "PENALTY_FORBIDDEN", "PENALTY_FUNCTION_WORD",
    "PENALTY_IDEOGRAPHS", "PENALTY_NEUTRAL", "PENALTY_OKURIGANA", "PENALTY_PARTICLE", "PENALTY_SENTENCE_END",
    "_rebalance", "_rebalance_phrase", "SAFE_WIDTH_FRACTION", "_split_hyphens", "_particle_ends",
    "_particle_starts", "wrap_text", "wrap_variants", "WRAP_MODES"
]
