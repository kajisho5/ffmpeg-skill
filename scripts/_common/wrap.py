"""Text measurement, caption line breaking and the size that fits the cue: the per-character
advance table, the phrase/measured wrapper and fit_size(). Pure -- no subprocess, no probe.
Split out of _common.text in the refactor after 1.17.3; every body is byte-identical.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple
from _common.emoji import emoji_clusters
from _common.fonts import char_script


# --------------------------------------------------------------------------- text measurement (1.12)
# Moved here in 1.15 so graphics.py's ASS route and the emoji placement share caption.py's table.
# Average advance width per character, in em (a fraction of the font size). Proportional Latin text
# averages a bit over half an em; CJK and Thai are drawn on a full-width grid; Arabic/Hebrew and
# Devanagari sit in between. These are deliberately averages, not per-glyph metrics: measuring the
# real advance needs a font parser (no stdlib one) and would still be wrong for libass's own
# shaping, while a cue wrapped from an average is right to within a character on every line.
# (Latin is measured per character from LATIN_EM below, not from this average.)
ADVANCE_EM = {"ja": 1.0, "zh": 1.0, "ko": 1.0, "th": 1.0, "hi": 0.7, "ar": 0.6, "he": 0.6,
              "ru": 0.55, "el": 0.55, "latin": 0.55}


# Scripts written without spaces: a line breaks between any two characters.
# Scripts a line may break inside a run of, one character at a time. Thai is deliberately NOT
# here since 1.16.1: it writes no space inside a phrase, and without a dictionary the wrapper
# cannot see where one word ends -- every character-level break it took in eval 17 landed inside
# a word. A Thai run is therefore one atom, broken only at the spaces (or the manual `|`) the
# writer put there; an over-long run stays long on its own line, the rule long Latin words
# already follow.
NO_SPACE_SCRIPTS = ("ja", "zh", "ko")
NO_BOUNDARY_SCRIPTS = ("th",)   # per-character breaking would chop words: keep the run whole


# Per-character Latin advances in em, read off DejaVu Sans (the default caption family, and close
# enough to any other proportional sans for a wrap) and rounded UP: a capital runs 0.56-0.99 em
# against the single 0.55 average that used to stand for all of Latin, so an all-caps caption --
# the style most burn-ins use -- overflowed the safe area and was silently re-wrapped by libass
# past --max-lines. Rounding up is the safe direction: libass re-wraps a too-long line, it never
# un-wraps a short one. Characters outside the table fall back by class (0.7 uppercase/digit,
# 0.57 lowercase and anything else Latin-ish).
LATIN_EM = {
    ' ': 0.32, '!': 0.41, '"': 0.46, '#': 0.84, '$': 0.64, '%': 0.96, '&': 0.78, "'": 0.28,
    '(': 0.4, ')': 0.4, '*': 0.5, '+': 0.84, ',': 0.32, '-': 0.37, '.': 0.32, '/': 0.34, '0': 0.64,
    '1': 0.64, '2': 0.64, '3': 0.64, '4': 0.64, '5': 0.64, '6': 0.64, '7': 0.64, '8': 0.64,
    '9': 0.64, ':': 0.34, ';': 0.34, '<': 0.84, '=': 0.84, '>': 0.84, '?': 0.54, '@': 1.0,
    'A': 0.69, 'B': 0.69, 'C': 0.7, 'D': 0.78, 'E': 0.64, 'F': 0.58, 'G': 0.78, 'H': 0.76,
    'I': 0.3, 'J': 0.3, 'K': 0.66, 'L': 0.56, 'M': 0.87, 'N': 0.75, 'O': 0.79, 'P': 0.61,
    'Q': 0.79, 'R': 0.7, 'S': 0.64, 'T': 0.62, 'U': 0.74, 'V': 0.69, 'W': 0.99, 'X': 0.69,
    'Y': 0.62, 'Z': 0.69, '[': 0.4, '\\': 0.34, ']': 0.4, '^': 0.84, '_': 0.5, '`': 0.5, 'a': 0.62,
    'b': 0.64, 'c': 0.55, 'd': 0.64, 'e': 0.62, 'f': 0.36, 'g': 0.64, 'h': 0.64, 'i': 0.28,
    'j': 0.28, 'k': 0.58, 'l': 0.28, 'm': 0.98, 'n': 0.64, 'o': 0.62, 'p': 0.64, 'q': 0.64,
    'r': 0.42, 's': 0.53, 't': 0.4, 'u': 0.64, 'v': 0.6, 'w': 0.82, 'x': 0.6, 'y': 0.6, 'z': 0.53,
    '{': 0.64, '|': 0.34, '}': 0.64, '~': 0.84
}


# Thai and Lao write some vowels BEFORE the consonant they belong to: the break must not land
# between them and the base that follows.
LEADING_VOWELS = set(range(0x0E40, 0x0E45)) | set(range(0x0EC0, 0x0EC5))


def _is_mark(ch: str) -> bool:
    """A character that hangs off the one before it: a combining mark (any script) or one of the
    Thai/Lao vowel signs and tone marks, which are Mn/Mc but carry no combining class."""
    return unicodedata.combining(ch) != 0 or unicodedata.category(ch) in ("Mn", "Mc")


def _char_em(ch: str) -> float:
    # CJK punctuation and the fullwidth forms (、。，！？　and U+FF01-FF60) are drawn on the same
    # full-width grid as the ideographs they sit between, even though they are not "Han" to a
    # script detector -- measuring them as Latin under-counts a wrapped CJK line by a character.
    cp = ord(ch)
    # A combining mark is drawn on top of (or under) its base and advances the pen by nothing:
    # charging it a full em wrapped Thai and Devanagari lines far shorter than they needed to be.
    if unicodedata.combining(ch) != 0 or unicodedata.category(ch) in ("Mn", "Cf"):
        # "Cf" catches ZWJ/ZWNJ: an Indic joiner is orthography, and it advances the pen by
        # nothing -- charging it a full em (it used to count as "emoji") shrank a Hindi line.
        return 0.0
    if 0x3000 <= cp <= 0x303F or 0xFF01 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6:
        return 1.0
    script = char_script(ch)
    if script == "emoji":
        # 1.15: an emoji is drawn (or reserved) at a full em box, not at Latin's 0.57 -- counting
        # it as Latin overflowed the safe area on an emoji-heavy line.
        return 1.0
    if script == "latin":
        if ch in LATIN_EM:
            return LATIN_EM[ch]
        if ch.isupper() or ch.isdigit():
            return 0.7
        return 0.57
    return ADVANCE_EM.get(script, 0.55)


def text_width_em(text: str, emoji_em: float = 1.0) -> float:
    """Width of `text` in em, from the per-script average advance table. `emoji_em` is what one
    emoji cluster costs (--emoji-scale), so a wrap counts the box that will actually be drawn."""
    total = 0.0
    spans = {i: len(c) for i, c in emoji_clusters(text)}
    i = 0
    while i < len(text):
        if i in spans:
            total += emoji_em
            i += spans[i]
            continue
        total += _char_em(text[i])
        i += 1
    return total


# --------------------------------------------------------------- caption line breaking (1.16)
# Lifted out of caption.py in 1.16.0 so graphics.py can wrap the same way (caption.py keeps the
# names it exported, re-imported from here). The whole breaker is pure: a string in, a list of
# lines out, no subprocess and no probe, which is what makes the eval regression corpus cheap
# to lock down in unit tests.

# How much of the frame width a caption line may use. libass's own default SRT margins are 10 of a
# 384-wide script (2.6 % a side); 5 % a side is the safe area every platform check in this repo uses.
SAFE_WIDTH_FRACTION = 0.9
# ORPHAN_MIN_EM: one full-width CJK/Thai character plus a hair. A last line narrower than this is a
# single stranded character -- eval 14's th1 (a lone 'ล') and dl3 (a lone '行').
ORPHAN_MIN_EM = 1.1

WRAP_MODES = ("phrase", "measured")

# R3's Japanese preference table. These are *preferences* applied only among positions that
# already fit the line, so the table can never make a line too wide or change the line count.
#
# JA_PARTICLES is a "do not strand at the start of a line" table, which is the direction kinsoku
# practice actually goes: a particle is enclitic -- it attaches to the word BEFORE it and marks
# that word's role -- so a line beginning with は or が reads as a fragment torn off its phrase.
# A break AFTER a particle is therefore preferred (the particle stays with what it marks) and a
# break BEFORE one is forbidden. The list is the eight case/topic particles named in the 1.16.0
# task brief (は が を に で と の へ) plus も や から まで より, which a reader of Japanese would
# add for the same reason. It is a judgement call with no upstream source; treat it as tunable
# data, not as grammar.
JA_PARTICLES = "はがをにでとのへもや"              # a break AFTER one of these is preferred, BEFORE one forbidden
# The multi-character members of the same table. They are matched as whole strings against the
# text on each side of a candidate break -- putting them in the character string above turned
# か, ら, ま, で, よ and り into one-character particles of their own, which none of them is.
JA_PARTICLE_WORDS = ("から", "まで", "より")
JA_SENTENCE_END = "。、！？」』）"                  # a break AFTER one of these is preferred
# Characters that may never start a line: small kana, the prolonged sound mark, closing brackets
# and the Japanese punctuation that hangs on the end of the line before it.
JA_NO_LINE_START = "ぁぃぅぇぉっゃゅょァィゥェォッャュョーヽヾゝゞ、。！？）」』】〕》’”％"
JA_NO_LINE_END = "（「『【〔《‘“"                   # ... and the ones that may never end a line

# R4. Function words belong to the phrase that FOLLOWS them: an article or preposition begins the
# noun phrase it governs, so a break before one is the good break (the word opens the next line
# with its phrase) and a break after one is the bad break (it is stranded at the end of a line,
# away from what it governs). Both directions are scored, which is what makes the rule decide
# rather than merely veto. Frozen data, matched case-folded on the atom with its punctuation
# stripped; six languages because those are the Latin-script languages the eval corpus covers. A
# word in several sets means the same thing structurally in each, so the union is used when no
# --lang was given.
FUNCTION_WORDS = {
    "en": {"a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "by", "from", "and",
           "or", "as", "is", "it", "its", "this", "that", "into", "than", "but", "so"},
    "es": {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en", "con",
           "por", "para", "y", "o", "que", "su", "sus", "lo", "se", "es"},
    "pt": {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na",
           "nos", "nas", "com", "por", "para", "e", "que", "se", "ao", "aos"},
    "fr": {"le", "la", "les", "un", "une", "de", "du", "des", "à", "au", "aux", "en", "dans",
           "et", "ou", "que", "qui", "ce", "ces", "son", "sa", "ses", "par", "pour", "avec", "sur"},
    "de": {"der", "die", "das", "ein", "eine", "einen", "einem", "einer", "den", "dem", "des",
           "zu", "in", "im", "auf", "mit", "und", "oder", "von", "vom", "für", "aus", "an"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "di", "del", "della", "da",
           "in", "nel", "con", "per", "e", "che", "su", "al", "ai"},
}
_FUNCTION_WORDS_ANY = frozenset().union(*FUNCTION_WORDS.values())

# Penalty scores. Only the ordering matters; 1.0 means "never choose this if anything else fits".
PENALTY_FORBIDDEN = 1.0
PENALTY_OKURIGANA = 0.9       # between a kanji stem and the hiragana that inflects it
PENALTY_FUNCTION_WORD = 0.8   # R4: the line before the break ends in an article/preposition
PENALTY_IDEOGRAPHS = 0.6      # between two kanji: no evidence either way, mildly discouraged
PENALTY_NEUTRAL = 0.5         # between two content words, or two characters with nothing to say
PENALTY_FUNCTION_WORD_START = 0.2  # R4: the next line opens with the article/preposition it governs
PENALTY_PARTICLE = 0.2        # R3: after a particle, so the particle stays with the word it marks
PENALTY_SENTENCE_END = 0.0    # R3: after 。、！？ -- the one break a reader expects

_HYPHENS = ("-", "‐")    # ‑ (non-breaking hyphen) is deliberately NOT here


def _atoms(line: str) -> "List[Tuple[str, bool]]":
    """Break a line into the smallest pieces a wrap may separate -- one atom per CJK/Thai
    character, one per emoji cluster, one per whitespace-delimited word otherwise -- each with
    whether a space stood before it in the original. The flag is what puts the text back together
    exactly as written: "Hello 世界" keeps its space, "世界です" gains none."""
    out: "List[Tuple[str, bool]]" = []
    word = ""
    spaced = False        # a space stands before the atom being built
    pending = False       # a space stands before the NEXT atom
    attach_next = False   # a leading Thai/Lao vowel is waiting for its base consonant
    # An emoji cluster is one atom: a wrap must never land inside a ZWJ sequence, a flag pair or
    # between a base and its skin-tone modifier (the same rule combining marks already follow).
    clusters = {i: len(cl) for i, cl in emoji_clusters(line)}
    i = 0
    while i < len(line):
        ch = line[i]
        if i in clusters:
            cluster = line[i:i + clusters[i]]
            if word:
                out.append((word, spaced))
                word = ""
            out.append((cluster, pending))
            pending = False
            attach_next = False
            i += clusters[i]
            continue
        i += 1
        if char_script(ch) in NO_SPACE_SCRIPTS:
            if word:
                out.append((word, spaced))
                word = ""
            if out and not pending and _is_katakana_run(ch) and _is_katakana_run(out[-1][0][-1]):
                # a katakana word (タイミング, コンピューター) is one atom: eval 17 saw タイ|ミング
                out[-1] = (out[-1][0] + ch, out[-1][1])
            elif out and (attach_next or _is_mark(ch)):
                # never break between a base and the mark (or the leading vowel) that belongs to
                # it: the line would start with an orphaned tone mark or vowel sign
                out[-1] = (out[-1][0] + ch, out[-1][1])
            else:
                out.append((ch, pending))
                pending = False
            attach_next = ord(ch) in LEADING_VOWELS
        elif ch.isspace():
            if word:
                out.append((word, spaced))
                word = ""
            pending = True
        else:
            if not word:
                spaced, pending = pending, False
            word += ch
    if word:
        out.append((word, spaced))
    return out


def _split_hyphens(atoms: "List[Tuple[str, bool]]") -> "List[Tuple[str, bool]]":
    """R1's one addition to the atom list: a hyphenated token may break *after* its hyphen.

    "end-to-end" becomes `end-` / `to-` / `end`, each piece carrying the space flag of the token
    it came from for the first piece and False for the rest, so _join() puts it back with no space
    at all. A hyphen that is the first or last character of the token (`-5`, `well-`) is never a
    break point: the guard is that both sides must be non-empty."""
    out: "List[Tuple[str, bool]]" = []
    for atom, spaced in atoms:
        if len(atom) < 3 or not any(h in atom[1:-1] for h in _HYPHENS):
            out.append((atom, spaced))
            continue
        piece = ""
        first = True
        for i, ch in enumerate(atom):
            piece += ch
            if ch in _HYPHENS and 0 < i < len(atom) - 1:
                out.append((piece, spaced if first else False))
                piece = ""
                first = False
        if piece:
            out.append((piece, spaced if first else False))
    return out


def _slice_atom(atom: str, max_em: float) -> "List[str]":
    """The escape hatch (1.18.4): hard-slice a single atom that is wider than `max_em` all by
    itself -- a word or run with no break point the wrapper may use, and that STILL does not fit
    even alone on its own line. Nothing else in this file may ever chop an atom mid-character;
    this is the one place that does, and only once every other mechanism (wrapping, then
    caption.py's --min-size shrink) has already failed to make it fit.

    No dictionary, no hyphenation library: an existing hyphen is preferred as the cut (the same
    break R1 already allows), then whatever is left is cut again at exactly the widest prefix
    that still measures within `max_em`, one character at a time. The characters themselves are
    never rewritten -- every piece concatenates back to the original atom exactly."""
    if text_width_em(atom) <= max_em:
        return [atom]
    for i in range(len(atom) - 2, 0, -1):
        # latest hyphen whose left side still fits -- keeps the left half as large as possible
        if atom[i] in _HYPHENS and text_width_em(atom[:i + 1]) <= max_em:
            return [atom[:i + 1]] + _slice_atom(atom[i + 1:], max_em)
    pieces: "List[str]" = []
    cur = ""
    for ch in atom:
        candidate = cur + ch
        if cur and text_width_em(candidate) > max_em:
            pieces.append(cur)
            cur = ch
        else:
            cur = candidate
    if cur:
        pieces.append(cur)
    return pieces or [atom]


def _join(left: str, atom: str, spaced: bool) -> str:
    """Put an atom back on a line, restoring the space that stood before it."""
    if not left:
        return atom
    return left + (" " if spaced else "") + atom


def _break_spaced(first: str, second: str) -> bool:
    """Did a space stand at the break between these two wrapped lines? Only spaced scripts put one
    there -- a CJK/Thai break sits between two characters that were written with nothing between
    them, and re-joining them with a space would insert a character the cue never had."""
    if not first or not second:
        return False
    return char_script(first[-1]) not in NO_SPACE_SCRIPTS and char_script(second[0]) not in NO_SPACE_SCRIPTS \
        and char_script(first[-1]) != "emoji" and char_script(second[0]) != "emoji"


def _is_kana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x30FF


def _is_katakana_run(ch: str) -> bool:
    """Katakana proper plus the prolonged-sound mark: the characters one loan word is made of."""
    cp = ord(ch)
    return (0x30A1 <= cp <= 0x30FA) or cp == 0x30FC or (0x31F0 <= cp <= 0x31FF) or (0xFF66 <= cp <= 0xFF9F)


def _is_hiragana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x309F


def _is_ideograph(ch: str) -> bool:
    cp = ord(ch)
    return 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF


def _is_weak_line(line: str) -> "bool":
    """A line no reader should be given on its own (R2).

    1.15 asked only "is the last line one atom narrower than ORPHAN_MIN_EM", which a full-width
    character passes: dl3 still showed a lone `2` and a stranded `行`. Three cases instead, any of
    which makes a line too thin to stand alone:
      - a single character narrower than ORPHAN_MIN_EM (1.15's rule, kept);
      - nothing but digits, punctuation and symbols, at most two characters ("2", "--");
      - a single kana, whatever its width -- a kana is a full em and passes the width test, but a
        line holding one is a syllable, not a word.
    """
    stripped = (line or "").strip()
    if not stripped:
        return True
    if len(stripped) == 1 and text_width_em(stripped) < ORPHAN_MIN_EM:
        return True
    if len(stripped) <= 2 and all(unicodedata.category(c)[0] in "NPS" for c in stripped):
        return True
    if len(stripped) == 1 and char_script(stripped) == "ja" and _is_kana(stripped):
        return True
    return False


def _function_words(lang: "Optional[str]") -> "frozenset":
    """R4's table for this language. An unknown or absent language gets the union of the six sets:
    a token that appears in several of them is the same kind of word in each, which is why the
    rule is a penalty and not a refusal."""
    key = (lang or "").strip().lower().split("-")[0]
    if key in FUNCTION_WORDS:
        return frozenset(FUNCTION_WORDS[key])
    return _FUNCTION_WORDS_ANY


def _bare_word(atom: str) -> str:
    return "".join(c for c in (atom or "") if c.isalpha() or c == "'").strip("'").lower()


def _particle_starts(text: str) -> bool:
    """Does `text` begin with a particle -- one character, or one of the two-character ones?"""
    if not text:
        return False
    return text[0] in JA_PARTICLES or text.startswith(JA_PARTICLE_WORDS)


def _particle_ends(text: str) -> bool:
    """Does `text` end with a particle? `から` counts, a bare `ら` does not."""
    if not text:
        return False
    return text[-1] in JA_PARTICLES or text.endswith(JA_PARTICLE_WORDS)


def break_penalty(prev_char: str, next_char: str, lang: "Optional[str]" = None,
                  before: str = "", after: str = "") -> float:
    """How bad a break between these two characters is, 0.0 (preferred) to 1.0 (forbidden).

    Only consulted among break positions that already fit `max_em`, so a preference can never
    widen a line or change the line count. Japanese gets the particle half of the table -- a break
    AFTER a particle is preferred and a break BEFORE one forbidden, because a particle attaches to
    the word before it; Chinese gets only the sentence-end and forbidden halves, because particles
    are Japanese grammar.

    `before`/`after` are the text on each side of the break when the caller has it, which is what
    lets the two-character particles (から/まで/より) be matched as words. Without them only the
    single-character table applies."""
    if not prev_char or not next_char:
        return PENALTY_NEUTRAL
    script = (lang or "").strip().lower().split("-")[0]
    if script not in ("ja", "zh"):
        # A kana on either side settles it: only Japanese has them, and char_script() reads a bare
        # Han character as Chinese, which used to switch the particle rules off for exactly the
        # break they exist to judge (`...が|決まる` -- kana before, kanji after).
        if _is_kana(prev_char) or _is_kana(next_char):
            script = "ja"
        else:
            script = char_script(next_char)
            if script not in ("ja", "zh"):
                script = char_script(prev_char)
    if next_char in JA_NO_LINE_START or prev_char in JA_NO_LINE_END or _is_mark(next_char):
        return PENALTY_FORBIDDEN
    if script not in ("ja", "zh"):
        return PENALTY_NEUTRAL
    if prev_char in JA_SENTENCE_END:
        return PENALTY_SENTENCE_END
    if script == "ja" and _particle_starts(after or next_char):
        # a particle may not open a line: it belongs to the word before it (kinsoku)
        return PENALTY_FORBIDDEN
    if script == "ja" and _particle_ends(before or prev_char):
        return PENALTY_PARTICLE
    if script == "ja" and _is_ideograph(prev_char) and _is_hiragana(next_char):
        # okurigana: 決|まる is inside a word even though neither half is a "word" on its own
        return PENALTY_OKURIGANA
    if _is_ideograph(prev_char) and _is_ideograph(next_char):
        return PENALTY_IDEOGRAPHS
    return PENALTY_NEUTRAL


def _cut_penalty(atoms: "Sequence[Tuple[str, bool]]", cut: int, lang: "Optional[str]") -> float:
    """The penalty of breaking `atoms` before index `cut`."""
    prev_atom = atoms[cut - 1][0]
    next_atom = atoms[cut][0]
    if not prev_atom or not next_atom:
        return PENALTY_NEUTRAL
    if atoms[cut][1]:
        # a space stood here: a spaced script, so R4 is the rule that applies, in both directions
        if all(not ch.isalnum() for ch in next_atom):
            return PENALTY_FORBIDDEN   # never strand punctuation at the start of a line
        words = _function_words(lang)
        if _bare_word(prev_atom) in words:
            return PENALTY_FUNCTION_WORD        # stranded at the end of a line, away from its noun
        if _bare_word(next_atom) in words:
            return PENALTY_FUNCTION_WORD_START  # opens the next line with the phrase it governs
        return PENALTY_NEUTRAL
    if prev_atom.endswith(_HYPHENS):
        return PENALTY_NEUTRAL         # R1: a hyphen is a legitimate break point
    # the text on each side, so a two-character particle (から/まで/より) is seen as one
    before = "".join(a for a, _sp in atoms[:cut])
    after = "".join(a for a, _sp in atoms[cut:])
    return break_penalty(prev_atom[-1], next_atom[0], lang, before=before, after=after)


def best_break(atoms: "Sequence[Tuple[str, bool]]", max_em: float,
               lang: "Optional[str]" = None) -> "Optional[int]":
    """The index to break `atoms` at so they become two lines, or None when none fits.

    Among every position whose two halves both fit `max_em`, the one minimising
    (penalty, widest line, |width difference|) wins: R1-R4 choose first, and 1.15's
    minimise-the-widest-line rule breaks the ties it used to decide alone."""
    best = None
    for cut in range(1, len(atoms)):
        a = b = ""
        for atom, sp in atoms[:cut]:
            a = _join(a, atom, sp)
        for atom, sp in atoms[cut:]:
            b = _join(b, atom, sp)
        wa, wb = text_width_em(a), text_width_em(b)
        if max(wa, wb) > max_em:
            continue
        if _is_weak_line(a) or _is_weak_line(b):
            continue
        key = (_cut_penalty(atoms, cut, lang), max(wa, wb), abs(wa - wb))
        if best is None or key < best[0]:
            best = (key, cut)
    return None if best is None else best[1]


def _fix_orphans(lines: "List[str]", max_em: float) -> "List[str]":
    """No last line that is a single stranded atom.

    Greedy wrapping leaves one character alone whenever the line before it filled exactly: eval 14
    produced a Thai cue ending in a lone `ล` and a Japanese one ending in a lone `行`. While the
    last line is one atom narrower than ORPHAN_MIN_EM, the last atom of the line above moves down
    onto it -- but only while the result still fits and the line above does not become an orphan
    itself, so a two-word cue is never made worse."""
    lines = list(lines)
    for _ in range(len(lines)):
        if len(lines) < 2:
            break
        tail = _atoms(lines[-1])
        if len(tail) != 1 or text_width_em(lines[-1]) >= ORPHAN_MIN_EM:
            break
        prev = _atoms(lines[-2])
        if len(prev) < 2:
            break
        moved, spaced = prev[-1]
        new_prev = ""
        for atom, sp in prev[:-1]:
            new_prev = _join(new_prev, atom, sp)
        new_last = _join(moved, tail[0][0], _break_spaced(lines[-2], lines[-1]))
        if text_width_em(new_last) > max_em or text_width_em(new_prev) < ORPHAN_MIN_EM:
            break
        lines[-2], lines[-1] = new_prev, new_last
    return lines


def _fix_weak_lines(lines: "List[str]", max_em: float) -> "List[str]":
    """R2, generalised: _fix_orphans run at *every* boundary, against _is_weak_line.

    1.15 only ever looked at the last line, so a stranded digit or kana in the middle of a
    three-line cue survived. Walking upward from the last line, while a line is weak the last atom
    of the line above moves down onto it -- with 1.15's two guards intact (the result must still
    fit, and the line above must not itself become weak), so the line count never changes."""
    lines = list(lines)
    for i in range(len(lines) - 1, 0, -1):
        for _ in range(len(lines)):
            if not _is_weak_line(lines[i]):
                break
            prev = _atoms(lines[i - 1])
            if len(prev) < 2:
                break
            moved, _spaced = prev[-1]
            new_prev = ""
            for atom, sp in prev[:-1]:
                new_prev = _join(new_prev, atom, sp)
            new_last = _join(moved, lines[i], _break_spaced(lines[i - 1], lines[i]))
            if text_width_em(new_last) > max_em or _is_weak_line(new_prev) \
                    or text_width_em(new_prev) < ORPHAN_MIN_EM:
                break
            lines[i - 1], lines[i] = new_prev, new_last
    return lines


def _rebalance(lines: "List[str]", max_em: float) -> "List[str]":
    """Move each break to the one that minimises the widest line of the pair, without changing the
    line count.

    Greedy wrapping fills line 1 to the brim and leaves line 2 short, which is what split eval 14's
    `"A third line the tool times for me"` mid-phrase. Only spaced scripts are rebalanced: a
    non-spaced script has no phrase structure in its atom list, so moving the break there only
    moves the ragged edge. A break is never placed before a punctuation-only atom."""
    if len(lines) < 2:
        return lines
    out = list(lines)
    for i in range(len(out) - 1):
        first, second = out[i], out[i + 1]
        tail_atoms = _atoms(second)
        if tail_atoms:
            tail_atoms[0] = (tail_atoms[0][0], _break_spaced(first, second))
        atoms = _atoms(first) + tail_atoms
        if not atoms or any(char_script(ch) in NO_SPACE_SCRIPTS for ch in first + second):
            continue
        best = None
        for cut in range(1, len(atoms)):
            if not atoms[cut][1]:
                continue  # only break where a space stood
            if all(not ch.isalnum() for ch in atoms[cut][0]):
                continue  # never strand punctuation at the start of a line
            a = b = ""
            for atom, sp in atoms[:cut]:
                a = _join(a, atom, sp)
            for atom, sp in atoms[cut:]:
                b = _join(b, atom, sp)
            wa, wb = text_width_em(a), text_width_em(b)
            if max(wa, wb) > max_em:
                continue
            key = (max(wa, wb), abs(wa - wb))
            if best is None or key < best[0]:
                best = (key, a, b)
        if best is not None:
            out[i], out[i + 1] = best[1], best[2]
    return out


def _rebalance_phrase(lines: "List[str]", max_em: float, lang: "Optional[str]") -> "Tuple[List[str], int]":
    """_rebalance with R1-R4 deciding, for every script rather than spaced ones only.

    Returns the new lines and how many breaks a phrase rule moved away from the position 1.15's
    widest-line rule alone would have chosen -- the `phrase_breaks` count in the result."""
    if len(lines) < 2:
        return list(lines), 0
    out = list(lines)
    moved = 0
    for i in range(len(out) - 1):
        first, second = out[i], out[i + 1]
        tail_atoms = _atoms(second)
        if tail_atoms:
            tail_atoms[0] = (tail_atoms[0][0], _break_spaced(first, second))
        atoms = _split_hyphens(_atoms(first) + tail_atoms)
        if len(atoms) < 2:
            continue
        cut = best_break(atoms, max_em, lang)
        if cut is None:
            continue
        a = b = ""
        for atom, sp in atoms[:cut]:
            a = _join(a, atom, sp)
        for atom, sp in atoms[cut:]:
            b = _join(b, atom, sp)
        if (a, b) != (first, second):
            moved += 1
        out[i], out[i + 1] = a, b
    return out, moved


def _greedy_chunks(raw: str, max_em: float, *, slice_overlong: bool = False,
                   sliced: "Optional[List[int]]" = None) -> "List[str]":
    """The greedy fill on its own: the line count every mode must keep.

    `slice_overlong` (off by default -- only caption.py's final burn-in pass turns it on, never
    fit_size()'s search) is the escape hatch: an atom that lands alone on a line and is STILL
    wider than `max_em` -- a fitting atom never reaches this branch, so a Thai phrase or a
    katakana run that already fits is completely untouched -- is hard-sliced by _slice_atom()
    instead of kept whole. `sliced`, when given, gets one entry (the number of extra lines that
    one atom produced) per atom actually sliced, which is how the caller counts
    `broken_inside_word` without re-deriving it from the output lines."""
    current = ""
    chunk: "List[str]" = []
    for atom, spaced in _atoms(raw):
        if slice_overlong and not current and text_width_em(atom) > max_em:
            pieces = _slice_atom(atom, max_em)
            if sliced is not None and len(pieces) > 1:
                sliced.append(len(pieces) - 1)
            chunk.extend(pieces[:-1])
            current = pieces[-1]
            continue
        candidate = _join(current, atom, spaced)
        if current and text_width_em(candidate) > max_em:
            chunk.append(current)
            if slice_overlong and text_width_em(atom) > max_em:
                pieces = _slice_atom(atom, max_em)
                if sliced is not None and len(pieces) > 1:
                    sliced.append(len(pieces) - 1)
                chunk.extend(pieces[:-1])
                current = pieces[-1]
            else:
                current = atom
        else:
            current = candidate
    if current:
        chunk.append(current)
    return chunk


def _balance(chunk: "List[str]", max_em: float, mode: str, lang: "Optional[str]") -> "List[str]":
    """The post-passes for one greedy chunk, in the mode's own order. Never changes the count:
    a pass that would is discarded, exactly as 1.15 did."""
    if len(chunk) < 2:
        return chunk
    if mode == "measured":
        fixed = _fix_orphans(chunk, max_em)
        rebalanced = _rebalance(fixed, max_em)
    else:
        fixed = _fix_weak_lines(_fix_orphans(chunk, max_em), max_em)
        rebalanced, _moved = _rebalance_phrase(fixed, max_em, lang)
        rebalanced = _fix_weak_lines(rebalanced, max_em)
    if len(rebalanced) == len(chunk):
        return rebalanced
    return fixed if len(fixed) == len(chunk) else chunk


def wrap_text(text: str, max_em: float, *, balance: bool = True, mode: str = "phrase",
              lang: "Optional[str]" = None, slice_overlong: bool = False,
              sliced: "Optional[List[int]]" = None) -> "List[str]":
    """Wrap `text` to lines no wider than `max_em` em, keeping the manual breaks it already has.

    An atom wider than the whole line (one very long word) is left alone on its line rather than
    cut mid-word: an over-long line is readable, a chopped word is not.

    `mode="phrase"` (the default since 1.16) then applies the four phrase rules -- never inside a
    word or across a hyphen's wrong side (R1), no line that is a lone digit, punctuation or kana
    (R2), Japanese/Chinese breaks preferred at sentence ends and after particles, never before one
    and never inside a word (R3), and an article or preposition kept with the phrase it governs by
    preferring the break before it and avoiding the break after it (R4). `mode="measured"` is
    1.15's behaviour exactly: no one-character orphan line, and a break chosen only to minimise the
    widest line. Neither mode ever changes the number of lines the greedy fill produced.
    """
    lines: "List[str]" = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        chunk = _greedy_chunks(raw, max_em, slice_overlong=slice_overlong, sliced=sliced)
        lines.extend(_balance(chunk, max_em, mode, lang) if balance else chunk)
    return lines or [text]
def wrap_variants(text: str, max_em: float, *, mode: str = "phrase",
                  lang: "Optional[str]" = None, slice_overlong: bool = False,
                  sliced: "Optional[List[int]]" = None) -> "Tuple[List[str], List[str], List[str]]":
    """`(wrapped, greedy, measured)` for one cue from a single greedy fill.

    layout_cues needs all three -- `wrapped` is what is burnt in, `greedy` is what `rebalanced`
    counts against and `measured` what `phrase_breaks` counts against -- and used to call
    wrap_text() three times, re-running the atomiser and the greedy fill each time. The fill is
    the same for every mode, so it is done once here and only the post-passes are repeated.
    `measured` is the same list object as `wrapped` when that is already the mode.
    """
    wrapped: "List[str]" = []
    greedy: "List[str]" = []
    measured: "List[str]" = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        chunk = _greedy_chunks(raw, max_em, slice_overlong=slice_overlong, sliced=sliced)
        greedy.extend(chunk)
        wrapped.extend(_balance(list(chunk), max_em, mode, lang))
        measured.extend(chunk if mode == "measured" else _balance(list(chunk), max_em, "measured", None))
    if not greedy:
        greedy = [text]
    return (wrapped or [text], greedy, measured or [text])


# --- caption size that fits the cue (1.17) -------------------------------------------------
# The legibility floor: 4.5 % of the frame height, ass_units(0.045) = 13 against the 288-line
# ASS script grid. One floor for every destination -- 87 px of type on a 1920-tall frame, above
# the ~3.5 % where mobile legibility bottoms out and where the platforms' own caption UIs sit.
# Nothing per-platform is measured, so nothing per-platform is claimed. (The eval-17 cues happen
# to land exactly on it: 13 is the smallest size at which every one of them fits two lines.)
MIN_CAPTION_FRACTION = 0.045
ASS_SCRIPT_HEIGHT = 288  # caption.py's --size/--margin reference grid; mirrors _platforms


def line_em_for_size(size: float, play_w: "Optional[int]", play_h: "Optional[int]", *,
                     safe_fraction: float = SAFE_WIDTH_FRACTION,
                     script_height: int = ASS_SCRIPT_HEIGHT) -> "Optional[float]":
    """How many em fit on one caption line at `size`, or None without geometry.

    `size` is in ASS points against a `script_height`-line script (what libass's force_style
    uses), so the rendered pixel size is size * play_h / script_height. This is the one width
    formula: caption.py::max_line_em and fit_size() both call it.
    """
    if not play_w or not play_h or not size:
        return None
    size_px = size * play_h / float(script_height)
    if size_px <= 0:
        return None
    return (play_w * safe_fraction) / size_px


def fit_size(cues, *, size: int, min_size: "Optional[int]" = None, max_lines: int = 2,
             play_w: "Optional[int]" = None, play_h: "Optional[int]" = None,
             safe_fraction: float = SAFE_WIDTH_FRACTION, mode: str = "phrase",
             lang: "Optional[str]" = None, script_height: int = ASS_SCRIPT_HEIGHT,
             step: int = 1, scope: str = "file") -> "Dict[str, Any]":
    """The largest size in [min_size, size] at which every cue wraps to <= max_lines lines.

    Pure: strings and integers in, a dict out. No ffmpeg, no ffprobe, no I/O -- the caption size
    is a text-measurement decision, and measuring it must not need a subprocess.

    `cues` is an iterable of cue texts (or of (start, end, text) tuples, as caption.py holds
    them before layout). Returns
    {"size", "floor", "requested", "scope", "shrunk", "fits", "per_cue", "max_em", "steps"}.

    The search is a linear walk downwards, not a bisection, and deliberately so:
    len(wrap_text(t, max_em)) is NOT guaranteed monotone in max_em under the phrase rules -- a
    rebalance that is discarded at one width can be applied at the next -- and a non-monotone
    predicate breaks bisection. 24 -> 13 is at most twelve iterations of pure string work.

    `scope="cue"` returns one size per cue index in `per_cue`, with `size` the minimum of them;
    the caller writes a per-cue {\\fsN} override. The default is `scope="file"`: a caption track
    whose type size changes from cue to cue reads as a mistake, and one measured line width per
    file is what makes the wrap behaviour reproducible.
    """
    # `texts` stays parallel to `cues`: a blank cue becomes None rather than being dropped, so
    # per_cue[i] always refers to the caller's cue i. caption.py indexes layout by these keys.
    texts: "List[Optional[str]]" = []
    for cue in cues or []:
        if isinstance(cue, (tuple, list)):
            raw = cue[2] if len(cue) > 2 else cue[-1]
        else:
            raw = cue
        texts.append(raw if raw and str(raw).strip() else None)
    measurable = [t for t in texts if t is not None]
    requested = int(size)
    floor = int(min_size) if min_size is not None else ass_units_local(MIN_CAPTION_FRACTION,
                                                                      script_height)
    floor = max(1, min(floor, requested))
    step = max(1, int(step))
    result: "Dict[str, Any]" = {"size": requested, "floor": floor, "requested": requested,
                                "scope": scope, "shrunk": 0, "fits": True, "per_cue": {},
                                "max_em": None, "steps": 0}
    em_at = lambda sz: line_em_for_size(sz, play_w, play_h, safe_fraction=safe_fraction,
                                        script_height=script_height)
    base_em = em_at(requested)
    result["max_em"] = base_em
    if not measurable or base_em is None or max_lines < 1:
        # No geometry means no measurable width: leave the size exactly as asked.
        return result

    def lines_at(text: str, sz: int) -> int:
        em = em_at(sz)
        if em is None:
            return 1
        return len(wrap_text(text, em, mode=mode, lang=lang))

    over_at_requested = [t for t in measurable if lines_at(t, requested) > max_lines]
    result["shrunk"] = len(over_at_requested)

    def best_for(subset) -> "Tuple[int, bool]":
        """(largest size in [floor, requested] fitting every text in `subset`, did it fit)."""
        sz = requested
        while sz >= floor:
            result["steps"] += 1
            if all(lines_at(t, sz) <= max_lines for t in subset):
                return sz, True
            sz -= step
        return floor, all(lines_at(t, floor) <= max_lines for t in subset)

    if scope == "cue":
        per_cue = {}
        fits_all = True
        for i, t in enumerate(texts):
            if t is None:
                per_cue[i] = requested    # a blank cue draws nothing; it constrains nothing
                continue
            sz, ok = best_for([t])
            per_cue[i] = sz
            fits_all = fits_all and ok
        result["per_cue"] = per_cue
        sized = [v for i, v in per_cue.items() if texts[i] is not None]
        result["size"] = min(sized) if sized else requested
        result["fits"] = fits_all
    else:
        sz, ok = best_for(measurable)
        result["size"] = sz
        result["fits"] = ok
    result["max_em"] = em_at(result["size"])
    return result


def ass_units_local(fraction: float, script_height: int = ASS_SCRIPT_HEIGHT) -> int:
    """`fraction` of the frame height in ASS units. Mirrors _platforms.ass_units, kept here so
    _common.text stays importable without the scripts/ top level on sys.path."""
    return int(round(fraction * script_height))
