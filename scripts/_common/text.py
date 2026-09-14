"""Text people can see -- since the refactor after 1.17.3 a re-export shim over four modules:

  fonts.py     font resolution per script: the tables, char_script()/detect_script(), the
               fc-match / fc-list / fc-scan lookups and script_font_for_text()
  emoji.py     emoji clusters, the PNG assets, emoji_support() and emoji_filter_chain()
  drawtext.py  drawtext option building and escaping, the shaping-library probe
  wrap.py      the advance table, the caption wrapper and fit_size()

`from _common.text import x` and `_common.text.x` mean what they always meant. Rebinding a name
on this module (`mock.patch("_common.text.<name>")`) rebinds it on the module that defines it,
the way the `_common` facade does, so a test that stands a helper up differently still reaches
the one the code reads at call time.
"""
from __future__ import annotations

import sys
import types as _types

from _common.fonts import (
    default_font_file, SCRIPTS, LANGUAGE_NAMES, FC_LANG, PREFERRED_FAMILIES, WINDOWS_FONTS, _SCRIPT_RANGES,
    font_family_of_file, char_script, detect_script, _SCRIPT_FONT_CACHE, _fc_list_fonts, _family_rank,
    _script_font_entry, FC_UNKNOWN, _script_font_uncached, font_for_script, font_family_for_script,
    script_font_status, font_covers_script, FONT_FLAG_HINT, FONT_INSTALL_HINT, fonts_dir_covers_script,
    script_font_for_text,
)
from _common.emoji import (
    EMOJI_RANGES, _EMOJI_TAIL, _EMOJI_REGIONAL, _ZWJ, _VS15, _VS16, _KEYCAP, _KEYCAP_BASES, _is_emoji_char,
    _is_emoji_base, emoji_clusters, has_emoji, emoji_codepoint_name, _emoji_name_candidates, emoji_asset_for,
    EMOJI_ASSET_HINT, _EMOJI_COLOR_FAMILIES, _EMOJI_SUPPORT_CACHE, _emoji_color_font, _libass_color_probe,
    emoji_support, resolve_emoji_assets, emoji_filter_chain,
)
from _common.drawtext import (
    drawtext_boxborderw, SHAPING_SCRIPTS, BIDI_SCRIPTS, _SHAPING_BUILD_CACHE, drawtext_shaping, needs_shaping,
    escape_drawtext, drawtext_text_opts,
)
from _common.wrap import (
    ADVANCE_EM, NO_SPACE_SCRIPTS, NO_BOUNDARY_SCRIPTS, LATIN_EM, LEADING_VOWELS, _is_mark, _char_em,
    text_width_em, SAFE_WIDTH_FRACTION, ORPHAN_MIN_EM, WRAP_MODES, JA_PARTICLES, JA_PARTICLE_WORDS,
    JA_SENTENCE_END, JA_NO_LINE_START, JA_NO_LINE_END, FUNCTION_WORDS, _FUNCTION_WORDS_ANY, PENALTY_FORBIDDEN,
    PENALTY_OKURIGANA, PENALTY_FUNCTION_WORD, PENALTY_IDEOGRAPHS, PENALTY_NEUTRAL, PENALTY_FUNCTION_WORD_START,
    PENALTY_PARTICLE, PENALTY_SENTENCE_END, _HYPHENS, _atoms, _split_hyphens, _join, _break_spaced, _is_kana,
    _is_katakana_run, _is_hiragana, _is_ideograph, _is_weak_line, _function_words, _bare_word, _particle_starts,
    _particle_ends, break_penalty, _cut_penalty, best_break, _fix_orphans, _fix_weak_lines, _rebalance,
    _rebalance_phrase, _greedy_chunks, _balance, wrap_text, wrap_variants, MIN_CAPTION_FRACTION,
    ASS_SCRIPT_HEIGHT, line_em_for_size, fit_size, ass_units_local,
)

_PARTS = tuple(sys.modules["_common." + _n] for _n in ("fonts", "emoji", "drawtext", "wrap"))


class _Shim(_types.ModuleType):
    """Rebinding a name here rebinds it on the part that defines it (and reads it at call time);
    dunders stay per module, as on the `_common` facade."""

    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        if name.startswith("__") and name.endswith("__"):
            return
        for _m in _PARTS:
            if name in _m.__dict__:
                _types.ModuleType.__setattr__(_m, name, value)

    def __delattr__(self, name):
        _types.ModuleType.__delattr__(self, name)
        if name.startswith("__") and name.endswith("__"):
            return
        for _m in _PARTS:
            if name in _m.__dict__:
                _types.ModuleType.__delattr__(_m, name)


sys.modules[__name__].__class__ = _Shim
