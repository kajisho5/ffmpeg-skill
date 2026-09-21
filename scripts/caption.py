#!/usr/bin/env python3
"""Burn SRT/ASS subtitles into a video, or mux one in as a soft (toggleable)
subtitle stream, or generate an SRT from plain text.

Styling (font, size, colour, outline, position) applies to SRT input via
libass force_style. ASS files carry their own styles and are rendered as-is.
Styling and animation only apply to --mode burn (the default): they render
pixels, so they have no meaning for a soft subtitle stream.

--mode mux copies the video and audio streams untouched (see contract --json:
reencodes_video/reencodes_audio are "never" for this mode) and adds the SRT
as a separate subtitle stream a player can toggle -- the source is never
touched. It takes only a plain SRT (from --srt, --text or --transcribe), not
--ass: ASS styling has no equivalent soft-subtitle representation across
containers, so --mode mux --ass is refused with a pointer to --mode burn.
The subtitle codec is picked from the output container: mov_text for
.mp4/.m4v/.mov, srt for .mkv, webvtt for .webm.

Text-to-SRT input format (one cue per line, blank lines ignored):
  0:00-0:03 Hello and welcome
  00:00:03.500 --> 00:00:06 Second line | with a manual line break
  00:00:03:15 --> 00:00:06:00 SMPTE non-drop-frame timecode (hh:mm:ss:ff, needs --fps or an @fps suffix: 00:00:03:15@29.97)
  Text without a time is auto-timed after the previous cue (--auto-seconds)

Examples:
  python3 caption.py input.mp4 --srt subs.srt
  python3 caption.py input.mp4 --text cues.txt --animate pop --karaoke        # word-by-word highlight, TikTok style
  python3 caption.py input.mp4 --text cues.txt --karaoke --karaoke-style word # active word scaled + emboldened, past/upcoming colours
  python3 caption.py input.mp4 --srt subs.srt --font "Noto Sans CJK JP" --size 28 --position top
  python3 caption.py --text cues.txt --write-srt cues.srt          # only produce the SRT
  python3 caption.py input.mp4 --text cues.txt                     # generate + burn in one go
  python3 caption.py input.mp4 --text cues_ko.txt --lang ko        # a font that covers the script is picked automatically
  python3 caption.py input.mp4 --srt subs.srt --offset -0.4 --max-lines 2 --min-duration 1.2
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _platforms import (PLATFORMS, PLATFORM_CHOICES, ASS_SCRIPT_HEIGHT, ass_units,
                        resolve as resolve_platform)
from _ass_overlay import EMOJI_SENTINEL, emoji_placeholder, ass_escape
from _common import emoji_filter_chain, EMOJI_ASSET_HINT, emoji_asset_for, emoji_codepoint_name, emoji_support, resolve_emoji_assets, ADVANCE_EM, LATIN_EM, NO_SPACE_SCRIPTS, _char_em, char_script, text_width_em, emoji_clusters, has_emoji, detect_script, BIDI_SCRIPTS, STATE, brand_states_font, script_font_for_text, signed_time_arg, brand_caption_style, color_hex, load_brand, video_args, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_filter_path, ffmpeg_base, fmt_srt_time, fmt_smpte_time, info, MissingFpsError, parse_time, probe, run, x264_args, X264_PRESETS, read_text_or_die, fmt_secs
# The line breaker, lifted into _common/text.py in 1.16.0 so graphics.py can use the same rules.
# The ASR bridge and the SRT reader/writer live in _common.asr since 1.17 (silence.py --filler
# shares them). They stay caption.py's public names -- every caller and test that reached for
# caption.parse_srt / caption.transcribe / caption.whisper_word_timings before 1.17 still does.
from _common import (ASR_INSTALL_HINT, die_no_engine, parse_srt, transcribe, whisper_word_timings,
                     write_srt)
from _common import (SAFE_WIDTH_FRACTION, ORPHAN_MIN_EM, WRAP_MODES, wrap_text, wrap_variants, best_break,
                     fit_size, line_em_for_size, MIN_CAPTION_FRACTION,
                     break_penalty, _is_weak_line, _atoms, _join, _break_spaced, _bare_word, _function_words,
                     _split_hyphens, _slice_atom, FUNCTION_WORDS, JA_PARTICLES, JA_SENTENCE_END, _fix_orphans, _rebalance)

# The breaker's names are caption.py's public surface as much as _common's: every caller and test
# that reached for `caption.wrap_text` before 1.16 still does.
__all__ = ["parse_srt", "write_srt", "transcribe", "whisper_word_timings", "die_no_engine",
           "ASR_INSTALL_HINT",
           "SAFE_WIDTH_FRACTION", "ORPHAN_MIN_EM", "WRAP_MODES", "wrap_text", "wrap_variants",
           "fit_size", "line_em_for_size", "MIN_CAPTION_FRACTION",
           "best_break", "break_penalty", "_is_weak_line", "_atoms", "_join", "_break_spaced",
           "_bare_word", "_function_words", "_split_hyphens", "_slice_atom", "FUNCTION_WORDS", "JA_PARTICLES",
           "JA_SENTENCE_END", "_fix_orphans", "_rebalance", "char_script", "NO_SPACE_SCRIPTS",
           "text_width_em"]

ALIGN = {"bottom": 2, "top": 8, "center": 5, "bottom-left": 1, "bottom-right": 3, "top-left": 7, "top-right": 9}

TIME_RE = re.compile(
    r"^\s*(?P<a>[\d:.,@]+)\s*(?:-->|-|–|to)\s*(?P<b>[\d:.,@]+)\s+(?P<text>.+)$"  # @ = the 1.9 @fps suffix
)


def parse_text_cues(path: str, auto_seconds: float, gap: float, fps: Optional[float] = None) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    cursor = 0.0
    for raw in read_text_or_die(path, "--text").lstrip("\ufeff").splitlines(True):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        m = TIME_RE.match(line)
        if m:
            try:
                start, end = parse_time(m.group("a"), fps), parse_time(m.group("b"), fps)
            except MissingFpsError as e:
                die(f"cue '{line}': {e} -- pass --fps, or --input's own fps is used automatically when given")
            except ValueError:
                # TIME_RE matched (so m.group("text") is the real cue text, not the broken
                # timestamp), but one of the two timestamps itself failed to parse (e.g. a
                # malformed "00:00:03.15.999") -- falling back to `line.strip()` here used to
                # burn the whole raw line, broken timestamp included, into the caption instead
                # of just the text after it.
                start, end, text = cursor, cursor + auto_seconds, m.group("text").strip()
            else:
                text = m.group("text").strip()
        else:
            start, end, text = cursor, cursor + auto_seconds, line.strip()
        if end <= start:
            die(f"cue '{line}': end must be after start")
        text = text.replace(" | ", "\n").replace("|", "\n")
        cues.append((start, end, text))
        cursor = end + gap
    if not cues:
        die(f"no cues found in {path}")
    return cues


def word_durations_from_audio(video: str, start: float, end: float, n_words: int, audio_stream: int = 0) -> List[int]:
    """Split a cue's time across n_words in proportion to speech energy (centiseconds each).

    Decodes the cue window to 8 kHz mono, builds a 10 ms RMS envelope, removes the noise floor,
    and cuts at equal cumulative-energy quantiles: pauses get no words, loud stretches get more time.
    Falls back to an even split when the window is silent or too short.
    """
    import struct
    from _common import require_tool, run_analysis
    total_cs = max(1, int(round((end - start) * 100)))
    if n_words <= 1:
        return [total_cs]
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", video,
           "-map", f"0:a:{audio_stream}", "-t", f"{end - start:.3f}", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    proc = run_analysis(cmd, check=False, text=False)  # under --timeout like every other measurement
    n = len(proc.stdout) // 2
    if proc.returncode != 0 or n < 800:
        per = total_cs // n_words
        return [per] * (n_words - 1) + [total_cs - per * (n_words - 1)]
    samples = struct.unpack(f"<{n}h", proc.stdout[: n * 2])
    step = 80  # 10 ms
    env = []
    for i in range(0, n - step + 1, step):
        block = samples[i:i + step]
        env.append((sum(x * x for x in block) / step) ** 0.5)
    floor = sorted(env)[len(env) // 5]  # 20th percentile ~ noise floor
    energy = [max(0.0, e - floor) for e in env]
    total_e = sum(energy)
    if total_e <= 0:
        per = total_cs // n_words
        return [per] * (n_words - 1) + [total_cs - per * (n_words - 1)]
    # boundaries at cumulative-energy quantiles 1/n .. (n-1)/n
    bounds = []
    acc = 0.0
    k = 1
    for idx, e in enumerate(energy):
        acc += e
        while k < n_words and acc >= total_e * k / n_words:
            bounds.append(idx + 1)
            k += 1
    while len(bounds) < n_words - 1:
        bounds.append(len(energy))
    prev = 0
    out = []
    for b in bounds:
        cs = max(5, int(round((b - prev) * 1.0)))  # 10 ms blocks -> centiseconds
        out.append(cs)
        prev = b
    out.append(max(5, total_cs - sum(out)))
    # normalise to the exact cue length. A cue too short for 5 cs per word (0.5 s, 20 words)
    # used to push the remainder into the last word as a negative \kf; split evenly instead,
    # and never let the last word go below 1 cs.
    if total_cs < 5 * n_words:
        per = max(1, total_cs // n_words)
        out = [per] * (n_words - 1) + [max(1, total_cs - per * (n_words - 1))]
        return out
    scale = total_cs / max(1, sum(out))
    out = [max(5, int(round(x * scale))) for x in out]
    out[-1] += total_cs - sum(out)
    while out[-1] < 1:
        i = max(range(len(out) - 1), key=lambda j: out[j])
        take = min(out[i] - 5, 1 - out[-1]) if out[i] > 5 else 0
        if take <= 0:
            break
        out[i] -= take
        out[-1] += take
    return out



# --------------------------------------------------------------------------- emoji (1.15)
def _cue_lines(text: str) -> List[str]:
    return [l for l in text.split("\n")]


def plan_emoji(cues, args, play_w, play_h, brand=None):
    """Decide how this run draws the emoji in `cues`, and where each PNG goes.

    Returns (cues, plan) where `cues` may have had its emoji replaced by EMOJI_SENTINEL (the PNG
    route) or stripped (`--emoji none`), and `plan` is the `emoji` result key plus the overlay
    entries the filter graph needs. `None` plan means "nothing to do": no emoji in the text.
    """
    clusters_all = [cl for _s, _e, t in cues for _i, cl in emoji_clusters(t)]
    if not clusters_all:
        return cues, None
    assets = resolve_emoji_assets(getattr(args, "emoji_assets", None), None, brand)
    want = getattr(args, "emoji", "auto")
    support = emoji_support(assets, probe=True)
    mode = support["mode"] if want == "auto" else want
    if want == "color" and not support["libass_color"]:
        die("--emoji color: this ffmpeg renders emoji monochrome through libass "
            f"({support['detail']}) -- pass --emoji-assets DIR for colour, or --emoji mono",
            kind="input")
    if want == "png" and not assets:
        die("--emoji png: no emoji assets directory resolved -- " + EMOJI_ASSET_HINT, kind="input")
    plan = {"mode": mode, "count": len(clusters_all),
            "clusters": sorted({emoji_codepoint_name(cl) for cl in clusters_all}),
            "assets": assets, "missing": [], "overlays": []}
    if mode == "none":
        out = []
        for start, end, text in cues:
            for cl in {cl for _i, cl in emoji_clusters(text)}:
                text = text.replace(cl, "")
            out.append((start, end, re.sub(r"[ \t]{2,}", " ", text).strip()))
        info("emoji: stripped from the drawn text (--emoji none)")
        return out, plan
    if mode in ("color", "mono"):
        if mode == "mono":
            info("warning: emoji rendered monochrome (no colour path on this ffmpeg; "
                 "--emoji-assets DIR for colour). " + support["detail"])
        return cues, plan
    # --- the PNG overlay route -------------------------------------------------------------
    if not play_w or not play_h:
        return cues, plan
    scale = float(getattr(args, "emoji_scale", 1.0) or 1.0)
    # --animate moves the TEXT (\fad/\fscx in the ASS); the PNG has to move with it, or the emoji
    # pops in against a line that is still fading up. These match the \fad values below.
    fade_in, fade_out = {"fade": (0.2, 0.2), "pop": (0.08, 0.12),
                         "slide": (0.15, 0.15)}.get(getattr(args, "animate", None) or "none", (0.0, 0.0))
    size_px = args.size * play_h / 288.0
    margin_px = args.margin * play_h / 288.0
    line_h = size_px * 1.2
    box_px = size_px * scale
    align = ALIGN[args.position]
    out_cues = []
    for start, end, text in cues:
        lines = _cue_lines(text)
        n = len(lines)
        new_lines = []
        for i, line in enumerate(lines):
            if align in (7, 8, 9):
                y_top = margin_px + i * line_h
            elif align in (4, 5, 6):
                y_top = play_h / 2.0 - (n * line_h) / 2.0 + i * line_h
            else:
                y_top = play_h - margin_px - (n - i) * line_h
            line_w = text_width_em(line, scale) * size_px
            if align in (1, 4, 7):
                x0 = margin_px
            elif align in (3, 6, 9):
                x0 = play_w - margin_px - line_w
            else:
                x0 = (play_w - line_w) / 2.0
            # libass lays an RTL line out right-to-left, so the LOGICAL prefix of a cluster
            # occupies the RIGHT end of the rendered line. Measuring the prefix from the left
            # edge put the PNG on top of the text, mirrored, on every Arabic/Hebrew cue (1.15.0).
            rtl = detect_script(line) in BIDI_SCRIPTS
            rebuilt = ""
            cursor = 0
            for idx, cluster in emoji_clusters(line):
                prefix = line[:idx]
                asset = emoji_asset_for(cluster, assets)
                name = emoji_codepoint_name(cluster)
                if not asset:
                    if name not in plan["missing"]:
                        plan["missing"].append(name)
                    rebuilt += line[cursor:idx + len(cluster)]
                    cursor = idx + len(cluster)
                    continue
                if rtl:
                    x = x0 + line_w - text_width_em(prefix + cluster, scale) * size_px
                else:
                    x = x0 + text_width_em(prefix, scale) * size_px
                y = y_top + (line_h - box_px) / 2.0
                plan["overlays"].append({
                    "asset": asset, "cluster": name,
                    "x": int(round(max(0.0, min(x, play_w - box_px)))),
                    "y": int(round(max(0.0, min(y, play_h - box_px)))),
                    "start": round(start, 3), "end": round(end, 3), "box": int(round(box_px)),
                    "fade_in": round(min(fade_in, max(0.0, (end - start) / 2.0)), 3),
                    "fade_out": round(min(fade_out, max(0.0, (end - start) / 2.0)), 3)})
                rebuilt += line[cursor:idx] + EMOJI_SENTINEL
                cursor = idx + len(cluster)
            rebuilt += line[cursor:]
            new_lines.append(rebuilt)
        out_cues.append((start, end, "\n".join(new_lines)))
    # `or 60` would swallow the one value that means "no overlays at all".
    _max = getattr(args, "emoji_max", None)
    limit = 60 if _max is None else int(_max)
    if len(plan["overlays"]) > limit:
        die(f"{len(plan['overlays'])} emoji overlays would be built for this job (limit {limit}, "
            "--emoji-max raises it); ffmpeg's filter graph and the per-frame cost both grow "
            "linearly -- split the job, or use --emoji none", kind="input")
    if plan["missing"]:
        info("warning: no PNG in the assets directory for " + ", ".join(plan["missing"]) +
             " -- those clusters are drawn by the text font instead")
    plan["box_px"] = int(round(box_px))
    return out_cues, plan


def layout_cues(cues: List[Tuple[float, float, str]], *, max_em: Optional[float], max_lines: int,
                min_duration: float, offset: float, wrap: str = "phrase",
                lang: Optional[str] = None, per_cue_em: Optional[List[Optional[float]]] = None,
                per_cue_size: Optional[List[int]] = None) -> Tuple[List[Tuple[float, float, str]], dict]:
    """Shift, wrap, split and lengthen cues so they can actually be read.

    `offset` moves every cue (a transcript that runs early/late); `max_em` wraps each cue to the
    safe area at the chosen size (None when no video geometry is known, e.g. --write-srt alone);
    a cue needing more than `max_lines` lines is split into consecutive cues sharing its time in
    proportion to their text; a cue shorter than `min_duration` is lengthened, never past the next
    cue's start. Returns the new cues and a count of what changed.

    `per_cue_em` (--fit-size-scope cue) gives cue i its OWN line budget instead of the file's:
    a cue drawn at a larger size has a narrower line in em, and wrapping it to the file-wide
    budget -- which is the budget of the SMALLEST size -- produced lines that overflowed the
    frame when they were then drawn large. `per_cue_size` rides along so the caller knows which
    size each OUTPUT cue belongs to after splits have renumbered them; it comes back as
    `stats["cue_sizes"]`, one entry per returned cue.
    """
    stats = {"shifted": 0, "wrapped": 0, "split": 0, "extended": 0, "dropped": 0, "rebalanced": 0,
             "wrap": wrap, "phrase_breaks": 0}
    # ass_units_local's floor + the escape hatch below mean an atom this loop hands to
    # wrap_variants(..., slice_overlong=True) can still overflow only if a SINGLE character is
    # wider than the column -- practically unreachable at any real --min-size. `overlong` stays
    # in stats for that theoretical remainder; `broken_inside_word` is the count that matters now.
    staged: List[Tuple[float, float, str]] = []
    staged_sizes: List[Optional[int]] = []
    for cue_index, (start, end, text) in enumerate(cues):
        own_em = max_em
        own_size = None
        if per_cue_em is not None and cue_index < len(per_cue_em):
            own_em = per_cue_em[cue_index]
        if per_cue_size is not None and cue_index < len(per_cue_size):
            own_size = per_cue_size[cue_index]
        if offset:
            start, end = start + offset, end + offset
            if end <= 0:
                stats["dropped"] += 1
                continue
            start = max(0.0, start)
            stats["shifted"] += 1
        if own_em and own_em > 0:
            # one greedy fill per cue, three answers off it: what gets burnt in, what the
            # greedy wrap would have given (`rebalanced`) and what 1.15's wrap would have
            # given (`phrase_breaks`). Three wrap_text() calls re-ran the atomiser each time.
            sliced_atoms: List[int] = []
            lines, greedy, measured = wrap_variants(text, own_em, mode=wrap, lang=lang,
                                                     slice_overlong=True, sliced=sliced_atoms)
            if lines != [l for l in text.split("\n") if l.strip()]:
                stats["wrapped"] += 1
            if sliced_atoms:
                # the escape hatch fired: a word or run with no break point the wrapper may use
                # was still wider than the column alone, even at the size in force, so it was
                # hard-sliced at the column edge (or after its own hyphen) instead of clipping
                stats["broken_inside_word"] = stats.get("broken_inside_word", 0) + len(sliced_atoms)
            if any(text_width_em(l) > own_em for l in lines):
                # the escape hatch above could not make every piece fit -- only possible when a
                # single character is wider than the column itself
                stats["overlong"] = stats.get("overlong", 0) + 1
            if lines != greedy:
                stats["rebalanced"] += 1
            if wrap != "measured" and lines != measured:
                stats["phrase_breaks"] += 1
            if len(lines) > max_lines:
                chunks = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
                weights = [max(1.0, sum(len(l) for l in c)) for c in chunks]
                total_w = sum(weights)
                t = start
                for chunk, weight in zip(chunks, weights):
                    seg = (end - start) * weight / total_w
                    staged.append((t, min(end, t + seg), "\n".join(chunk)))
                    staged_sizes.append(own_size)
                    t += seg
                stats["split"] += len(chunks) - 1
                continue
            text = "\n".join(lines)
        staged.append((start, end, text))
        staged_sizes.append(own_size)
    out: List[Tuple[float, float, str]] = []
    for i, (start, end, text) in enumerate(staged):
        if min_duration and end - start < min_duration:
            limit = staged[i + 1][0] if i + 1 < len(staged) else None
            new_end = start + min_duration if limit is None else min(start + min_duration, limit)
            if new_end > end:
                stats["extended"] += 1
                end = new_end
        out.append((start, end, text))
    if per_cue_size is not None:
        stats["cue_sizes"] = staged_sizes
    return out, stats


def report_layout(stats: dict) -> None:
    """One info line, only when a cue actually changed."""
    parts = [f"{stats[k]} {k}" for k in ("shifted", "wrapped", "rebalanced", "phrase_breaks", "split",
             "extended", "dropped", "broken_inside_word", "overlong") if stats.get(k)]
    if parts:
        info("cues: " + ", ".join(parts))
    if stats.get("broken_inside_word"):
        info(f"{stats['broken_inside_word']} cue line(s) had a word or run with no break point "
             "(Thai writes none inside a phrase) that was still wider than the column alone -- it "
             "was sliced at the column edge (after its own hyphen when it has one) instead of "
             "clipping past the frame; put a space or `|` where the line may break, or use a "
             "smaller --size, to avoid the slice")
    if stats.get("overlong"):
        info(f"{stats['overlong']} cue line(s) wider than the safe width even after slicing: a "
             "single character was wider than the column -- use a smaller --size")


def margins_x(args, play_w: Optional[int]) -> Tuple[int, int]:
    """(MarginL, MarginR) in ASS script pixels -- the HORIZONTAL safe zone, never --margin.

    1.17.2. --margin is the vertical distance from the edge (the platform's bottom UI: TikTok's
    description bar is 22 % of the frame, 63 ASS units, 420 px on a 1920-tall frame). Writing it
    into MarginL/MarginR as well, as 1.14-1.17.1 did, left a 1080-wide frame with a 240 px text
    column and libass wrapped "Hello world" onto two lines while the fitter -- which measures
    against the horizontal safe width -- reported no wrap at all.

    The left/right margins come from the destination's own horizontal safe zone (`safe.left` /
    `safe.right` in scripts/_platforms.py; TikTok reserves 14 % on the right for the like/share
    rail), and without a --platform from the conventional (1 - SAFE_WIDTH_FRACTION)/2 border --
    the same 5 % per side the wrapper has always assumed. A run that writes no ASS of its own
    (the SRT force_style burn) keeps that symmetric border, so its budget is unchanged at
    SAFE_WIDTH_FRACTION and the fitter still agrees with what libass will do.
    """
    if not play_w:
        return 0, 0
    if getattr(args, "platform", None) and PLATFORMS[args.platform].get("frame") and draws_own_ass(args):
        safe = PLATFORMS[args.platform]["safe"]
        left, right = float(safe["left"]), float(safe["right"])
    else:
        left = right = (1.0 - SAFE_WIDTH_FRACTION) / 2.0
    return int(round(left * play_w)), int(round(right * play_w))


def draws_own_ass(args) -> bool:
    """True when this run generates its own ASS, and so sets its own Style margins.

    An SRT burn goes through libass's force_style instead, which states MarginV only and leaves
    the side margins at libass's own defaults -- that path's budget stays the historical
    play_w * SAFE_WIDTH_FRACTION, unchanged by 1.17.2.
    """
    if getattr(args, "ass", None):
        return False          # the caller's own ASS: its Style is theirs, not ours
    return (getattr(args, "animate", "none") or "none") != "none" or bool(getattr(args, "karaoke", False))


def safe_width_fraction(args, play_w: Optional[int]) -> float:
    """The fraction of the frame width a caption line may use -- play_w minus the two margins.

    The fitter and libass have to agree to the pixel, so this is derived from the SAME rounded
    MarginL/MarginR that go into the ASS Style rather than from the raw fractions. On a run that
    writes no ASS of its own the margins are the symmetric border, i.e. SAFE_WIDTH_FRACTION, so
    the SRT force_style path keeps its historical budget.
    """
    if not play_w:
        return SAFE_WIDTH_FRACTION
    left, right = margins_x(args, play_w)
    return max(0.05, (play_w - left - right) / float(play_w))


def max_line_em(args, play_w: Optional[int], play_h: Optional[int]) -> Optional[float]:
    """How many em fit on one caption line at the chosen size, or None without video geometry.

    --size is in ASS points against a 288-line script (what libass's force_style uses), so the
    rendered pixel size is size * play_h / 288.

    --karaoke-style word scales its active word up by --karaoke-scale and freezes the line break
    (WrapStyle: 2 in write_ass) so libass can never re-wrap around that scale-up. The budget here
    is narrowed by the same factor so the longest wrapped line -- computed at the UNscaled width --
    still fits once its active word is drawn --karaoke-scale%% larger; without this, a line that
    exactly filled the safe width would overflow it the moment its emphasised word appears.
    """
    em = line_em_for_size(args.size, play_w, play_h,
                          safe_fraction=safe_width_fraction(args, play_w))
    if em is not None and getattr(args, "karaoke", False) and getattr(args, "karaoke_style", "sweep") == "word":
        em = em / max(1.0, getattr(args, "karaoke_scale", 112) / 100.0)
    return em


def parse_ass_dialogue(path: str) -> str:
    """The spoken text of an ASS file, for script detection -- style/override blocks stripped."""
    text = []
    for line in read_text_or_die(path, "--ass").lstrip("\ufeff").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) == 10:
            text.append(re.sub(r"\{[^}]*\}", "", fields[9]))
    return "\n".join(text)


def shift_ass_file(src: str, dst: str, offset: float) -> int:
    """Copy an ASS file with every Dialogue start/end moved by `offset` seconds."""
    def shift(stamp: str) -> str:
        h, m, rest = stamp.split(":")
        secs = int(h) * 3600 + int(m) * 60 + float(rest) + offset
        secs = max(0.0, secs)
        cs = int(round(secs * 100))
        hh, rem = divmod(cs, 360000)
        mm, rem = divmod(rem, 6000)
        ss, cc = divmod(rem, 100)
        return f"{hh}:{mm:02d}:{ss:02d}.{cc:02d}"

    n = 0
    out = []
    for line in Path(src).read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("Dialogue:"):
            head, sep, rest = line.partition(":")
            fields = rest.split(",")
            if len(fields) >= 3:
                try:
                    fields[1], fields[2] = shift(fields[1].strip()), shift(fields[2].strip())
                    line = head + sep + ",".join(fields)
                    n += 1
                except (ValueError, IndexError):
                    pass
        out.append(line)
    Path(dst).write_text("\n".join(out) + "\n", encoding="utf-8-sig")
    return n


def word_durations_from_timings(words: List[Tuple[float, float, str]], start: float, end: float,
                                n_words: int) -> Optional[List[int]]:
    """Centiseconds per word for one cue, from real word timings; None when they don't cover it."""
    inside = [w for w in words if w[1] > start + 0.01 and w[0] < end - 0.01]
    if len(inside) != n_words or n_words <= 0:
        return None
    total_cs = max(1, int(round((end - start) * 100)))
    bounds = [max(start, inside[0][0])] + [max(start, min(end, w[1])) for w in inside]
    out = [max(1, int(round((bounds[i + 1] - bounds[i]) * 100))) for i in range(n_words)]
    out[-1] += total_cs - sum(out)
    if out[-1] < 1:
        return None
    return out


def _karaoke_word_durations(args, video: Optional[str], start: float, end: float, n_words: int) -> List[int]:
    """Centiseconds per word for one cue, shared by --karaoke-style sweep and word.

    Real word timings from the transcript beat both the energy estimate and the even split --
    they are what the speaker actually did, not a proxy for it.
    """
    dur_cs = max(1, int(round((end - start) * 100)))
    durs = word_durations_from_timings(getattr(args, "_word_timings", None) or [], start, end, n_words)
    if durs is None:
        if getattr(args, "karaoke_timing", "even") == "energy" and video:
            durs = word_durations_from_audio(video, start, end, n_words, getattr(args, "audio_stream", 0))
        else:
            per = max(1, dur_cs // max(1, n_words))
            durs = [per] * n_words
    return durs


def write_ass(cues: List[Tuple[float, float, str]], path: str, args, play_w: int, play_h: int, video: str = None) -> None:
    """Write a styled ASS file with optional animation and word-by-word highlight."""
    def t(sec: float) -> str:
        cs = int(round(sec * 100))
        h, rem = divmod(cs, 360000)
        m, rem = divmod(rem, 6000)
        s_, cs = divmod(rem, 100)
        return f"{h}:{m:02d}:{s_:02d}.{cs:02d}"

    scale = play_h / 288.0  # our --size is relative to a 288-line script like force_style
    size = int(round(args.size * scale))
    margin = int(round(args.margin * scale))          # vertical: MarginV, and the slide origin
    margin_l, margin_r = margins_x(args, play_w)      # horizontal: the frame's safe zone
    # karaoke: PrimaryColour is the "sung" colour, SecondaryColour the "not yet sung" one
    primary = ass_color(args.highlight_color if args.karaoke else args.color)
    secondary = ass_color(args.color)
    outline = ass_color(args.outline_color)
    back = ass_color(args.outline_color, 0x80)
    word_style = args.karaoke and getattr(args, "karaoke_style", "sweep") == "word"
    word_past = ass_color(args.color)
    word_active = ass_color(args.highlight_color)
    word_upcoming = ass_color(args.upcoming_color)
    word_bord = f"{args.outline * scale * (max(1.0, args.karaoke_scale) / 100.0):.2f}"
    word_scale = int(round(args.karaoke_scale))
    # --karaoke-style word emits one Dialogue per word carrying the WHOLE cue with explicit \N
    # breaks (the layout's own fixed line list -- see max_line_em's docstring). WrapStyle: 2 tells
    # libass to honour only those explicit breaks and never re-wrap: with WrapStyle: 0 (the sweep
    # default, unchanged), scaling the active word up would re-flow the line and it would visibly
    # jump every time the highlight advances (the trap the issue this implements is filed against).
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {play_w}", f"PlayResY: {play_h}",
        f"WrapStyle: {2 if word_style else 0}", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{ass_font_name(args.font)},{size},{primary},{secondary},{outline},{back},{-1 if args.bold else 0},0,0,0,100,100,0,0,{3 if args.box else 1},{args.outline * scale:.1f},{args.shadow * scale:.1f},{ALIGN[args.position]},{margin_l},{margin_r},{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = []
    for cue_index, (start, end, text) in enumerate(cues):
        # ASS Dialogue text treats a literal `{...}` as an override block -- real style/animation
        # commands, not literal characters. Cue text (from --text, an SRT, or ASR transcription --
        # all effectively user-controlled) that happens to contain braces would otherwise be
        # interpreted as those commands (\pos, \t, \fscx, ...), letting caption content reposition,
        # rescale, or recolor itself or later text instead of just being read out. libass has real
        # escapes for the braces, so 1.15 escapes them (ass_escape) rather than deleting them:
        # a cue that says "use {curly} braces" is read out with its braces, and still cannot open
        # an override block. Newlines become \N in the same pass.
        text = ass_escape(text)
        fx = ""
        if args.animate == "fade":
            fx = "{\\fad(200,200)}"
        elif args.animate == "pop":
            fx = "{\\fad(80,120)\\fscx60\\fscy60\\t(0,120,\\fscx110\\fscy110)\\t(120,200,\\fscx100\\fscy100)}"
        elif args.animate == "slide":
            fx = "{\\fad(150,150)\\move(%d,%d,%d,%d,0,250)}" % (play_w // 2, play_h - margin + int(30 * scale), play_w // 2, play_h - margin)
        body = text
        # --fit-size-scope cue: one size per cue, as a leading {\fsN} override. Opt-in only --
        # see fit_size()'s docstring for why a size that changes cue to cue is not the default.
        # The size is the one THIS cue was laid out at, carried through layout_cues; re-measuring
        # here would measure the post-layout text (already carrying the wrap's newlines), which
        # is a different string from the one the fit was computed on.
        own_sizes = getattr(args, "_fit_sizes_out", None) or []
        own = own_sizes[cue_index] if cue_index < len(own_sizes) else None
        if own and own != args.size:
            fx += "{\\fs%d}" % int(round(own * scale))
        if args.karaoke and word_style:
            # One Dialogue event per WORD, each carrying the whole cue -- \k/\kf can only
            # interpolate colour, so scaling/emboldening the active word (and a third "upcoming"
            # colour) needs a real per-word override block instead. The line list is `body`'s own
            # \N split, already frozen by layout_cues (this function never re-wraps it), so every
            # event uses the identical break -- WrapStyle: 2 above stops libass re-wrapping around
            # the active word's larger \fscx/\fscy, which is the jump the issue is filed against.
            line_words = [[w for w in seg.split(" ") if w] for seg in body.split("\\N")]
            flat = [w for lw in line_words for w in lw]
            real_idx = [i for i, w in enumerate(flat) if w.strip(EMOJI_SENTINEL)]
            if not real_idx:
                # nothing to highlight (an all-emoji or empty cue) -- one plain event, same as
                # today's karaoke-off rendering, rather than zero Dialogue lines for this cue
                out_body = body
                if EMOJI_SENTINEL in out_body:
                    out_body = out_body.replace(EMOJI_SENTINEL, emoji_placeholder(getattr(args, "_emoji_box_px", size)))
                lines.append(f"Dialogue: 0,{t(start)},{t(end)},Default,,0,0,0,,{fx}{out_body}")
                continue
            n_words = len(real_idx)
            durs = _karaoke_word_durations(args, video, start, end, n_words)
            starts_cs, acc = [], 0
            for d in durs:
                starts_cs.append(acc)
                acc += d
            for j in range(n_words):
                w_start = start + starts_cs[j] / 100.0
                w_end = start + (starts_cs[j] + durs[j]) / 100.0
                # colour/scale each real word by its rank against the active one (j); an
                # emoji-placeholder token is never active and just keeps its plain text
                styled, flat_pos = [], 0
                for lw in line_words:
                    styled_line = []
                    for w in lw:
                        if not w.strip(EMOJI_SENTINEL):
                            styled_line.append(w)
                        else:
                            rank = real_idx.index(flat_pos)
                            if rank < j:
                                styled_line.append(f"{{\\c{word_past}}}{w}")
                            elif rank == j:
                                styled_line.append(
                                    f"{{\\c{word_active}\\fscx{word_scale}\\fscy{word_scale}\\bord{word_bord}}}{w}{{\\r}}")
                            else:
                                styled_line.append(f"{{\\c{word_upcoming}}}{w}")
                        flat_pos += 1
                    styled.append(" ".join(styled_line))
                out_body = "\\N".join(styled)
                if EMOJI_SENTINEL in out_body:
                    out_body = out_body.replace(EMOJI_SENTINEL, emoji_placeholder(getattr(args, "_emoji_box_px", size)))
                # the size/fit override (\fsN) belongs on every event; the entrance animation
                # (\fad/\move/pop) only on the cue's FIRST word event -- replaying it on every
                # later word would re-fade/re-pop the whole cue each time the highlight advances
                event_fx = fx if j == 0 else (fx[fx.index("{\\fs"):] if "{\\fs" in fx else "")
                lines.append(f"Dialogue: 0,{t(w_start)},{t(w_end)},Default,,0,0,0,,{event_fx}{out_body}")
            continue
        if args.karaoke:
            # split each line into words and give every word an equal share of the cue (\k is in centiseconds)
            segments = body.split("\\N")
            words = [w for seg in segments for w in seg.split(" ") if w and w.strip(EMOJI_SENTINEL)]
            durs = _karaoke_word_durations(args, video, start, end, len(words))
            it = iter(durs)
            out_segments = []
            for seg in segments:
                ws = [w for w in seg.split(" ") if w]
                # An emoji placeholder is its own ZERO-duration \kf segment: the highlight sweeps
                # past the reserved gap without spending cue time on a glyph nobody sees (rendered
                # and confirmed -- libass keeps the full gap inside a karaoke run).
                out_segments.append(" ".join(
                    ("{\\kf0}" + w) if not w.strip(EMOJI_SENTINEL) else f"{{\\kf{next(it)}}}{w}" for w in ws))
            body = "\\N".join(out_segments)
        if EMOJI_SENTINEL in body:
            body = body.replace(EMOJI_SENTINEL, emoji_placeholder(getattr(args, "_emoji_box_px", size)))
        lines.append(f"Dialogue: 0,{t(start)},{t(end)},Default,,0,0,0,,{fx}{body}")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write("\n".join(header + lines) + "\n")


# ------------------------------------------------------- multi-language subtitle tracks (1.16)

class AppendPath(argparse.Action):
    """`--srt` repeated, without changing what the contract says `--srt` is.

    `action="append"` would make the derived JSON Schema an array (`_contract._json_type`), and the
    1.x guarantee says no argument changes type -- an MCP client that sends `{"srt": "subs.srt"}`
    must keep working exactly as it did. Subclassing Action directly keeps the schema a plain
    string while the CLI collects every occurrence, so repeating the flag is purely additive.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None)
        if not isinstance(current, list):
            current = [] if current is None else [current]
        current.append(values)
        setattr(namespace, self.dest, current)


# BCP-47-ish: a 2-3 letter primary subtag, optionally followed by script/region/variant subtags.
LANG_TOKEN_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# The name a player lists a track under, when the caller gives no --track-title. Data, not a
# translation: a code that is not in the table gets the code itself, never an invented name.
LANG_TITLES = {
    "en": "English", "es": "Espanol", "pt": "Portugues", "fr": "Francais", "de": "Deutsch",
    "it": "Italiano", "nl": "Nederlands", "pl": "Polski", "ru": "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    "ja": "\u65e5\u672c\u8a9e", "zh": "\u4e2d\u6587", "ko": "\ud55c\uad6d\uc5b4",
    "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629", "he": "\u05e2\u05d1\u05e8\u05d9\u05ea",
    "hi": "\u0939\u093f\u0928\u094d\u0926\u0940", "th": "\u0e44\u0e17\u0e22",
    "tr": "Turkce", "id": "Bahasa Indonesia", "vi": "Tieng Viet", "sv": "Svenska",
    "da": "Dansk", "no": "Norsk", "fi": "Suomi", "cs": "Cestina", "uk": "\u0423\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u0430",
}

# MP4/MOV store the language in an ISO-639-2/T box and silently drop anything that is not three
# letters -- verified against ffmpeg 6.1: `-metadata:s:s:0 language=en` on an .mp4 writes NO
# language tag at all, while `language=eng` writes one ffprobe reads back. Matroska stores the
# code verbatim, so `en` survives there. Only the codes this table knows are converted; an
# unknown one is passed through with a note rather than guessed at.
ISO639_1_TO_2 = {
    "en": "eng", "es": "spa", "pt": "por", "fr": "fra", "de": "deu", "it": "ita", "nl": "nld",
    "pl": "pol", "ru": "rus", "ja": "jpn", "zh": "zho", "ko": "kor", "ar": "ara", "he": "heb",
    "hi": "hin", "th": "tha", "tr": "tur", "id": "ind", "vi": "vie", "sv": "swe", "da": "dan",
    "no": "nor", "fi": "fin", "cs": "ces", "uk": "ukr", "el": "ell", "hu": "hun", "ro": "ron",
    "bg": "bul", "ca": "cat", "fa": "fas", "ta": "tam", "bn": "ben", "ms": "msa", "fil": "fil",
}


def split_srt_lang(token: str) -> Tuple[str, Optional[str]]:
    """`file.srt:ja` -> ("file.srt", "ja"); anything else -> (token, None).

    The split is on the LAST colon and only when the suffix is BCP-47-shaped AND the whole token
    is not itself a readable file -- so `C:\\subs\\en.srt` (a Windows path) and a file genuinely
    named `a:b.srt` are never mangled.
    """
    token = str(token)
    if ":" not in token or os.path.exists(token):
        return token, None
    head, _, tail = token.rpartition(":")
    if head and LANG_TOKEN_RE.match(tail):
        return head, tail
    # A tail that is clearly meant as a language code but is not one is a language error, not a
    # file called `en.srt:zzzz`: only say "file not found" when the whole token could be a path.
    if head and tail and not os.path.exists(token) and os.path.exists(head) \
            and re.match(r"^[A-Za-z][A-Za-z0-9-]*$", tail):
        die(f"--srt {token}: '{tail}' is not a language code (two or three letters, optionally "
            "with a region, e.g. en, ja, pt-BR)", kind="input")
    return token, None


def container_language(code: str, output: str) -> str:
    """The spelling of `code` this container actually stores (see ISO639_1_TO_2)."""
    ext = Path(output).suffix.lower()
    if ext not in (".mp4", ".m4v", ".mov"):
        return code
    primary = code.split("-")[0].lower()
    return ISO639_1_TO_2.get(primary, code)


def track_title_for(code: Optional[str], given: Optional[str]) -> Optional[str]:
    if given:
        return given
    if not code:
        return None
    return LANG_TITLES.get(code.split("-")[0].lower(), code)


def mux_subtitle_codec(output: str) -> str:
    ext = Path(output).suffix.lower()
    if ext in (".mp4", ".m4v", ".mov"):
        return "mov_text"
    if ext == ".mkv":
        return "srt"
    if ext == ".webm":
        return "webvtt"
    die(f"--mode mux: don't know a soft-subtitle codec for '{ext}' output "
        "(know .mp4/.m4v/.mov, .mkv, .webm) -- use --mode burn, or pick one of those containers with -o")


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        die(f"colour must be RRGGBB hex, got '{hex_rgb}'")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_font_name(name: str) -> str:
    """Sanitise a font name for embedding in an ASS [V4+ Styles] Style line (comma-delimited
    fields, no quoting mechanism) and in a `force_style='...'` option list (comma-separated
    Key=Value pairs, colon-separated from the rest of the -vf filter). No real font name uses
    `, : \\ '`, so rather than chase a per-context escape (a Style line and a force_style list
    have different delimiter rules), those characters -- and control characters, which are never
    meaningful in a font name either -- are dropped outright, the same "no escape proven safe
    everywhere it's used" call this codebase already makes for escape_drawtext()'s `'`/`%`."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    for ch in ",:\\'":
        name = name.replace(ch, "")
    return name


def _glue_negative_offset(argv: List[str]) -> List[str]:
    """`--offset -0:00:02` reads as a flag to argparse, not a value: only bare negative NUMBERS
    are exempt from the "starts with -" rule, and a negative timecode is not one. Join the pair
    into `--offset=-0:00:02` so the documented grammar works in the shape people type it."""
    out: List[str] = []
    i = 0
    while i < len(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if argv[i] == "--offset" and nxt.startswith("-") and not nxt.startswith("--"):
            out.append(f"--offset={nxt}")
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="video to burn captions into (omit with --write-srt to only generate)")
    ap.add_argument("-o", "--output", help="output video (default: <name>_captioned.<ext>)")
    ap.add_argument("--mode", choices=["burn", "mux"], default="burn",
                     help="'burn' renders subtitles into the picture (default); "
                          "'mux' copies video/audio untouched and adds the SRT as a soft, toggleable subtitle stream")
    ap.add_argument("--audio-stream", type=int, default=0,
                     help="which audio stream of the input to keep, 0-based in file order (probe.py lists them under "
                          "audio_streams) -- matters on a multi-track input (dubbed languages, M&E stems); default 0, "
                          "the first track, same as leaving it unset always did")
    src = ap.add_argument_group("subtitle source")
    src.add_argument("--srt", action=AppendPath, metavar="FILE[:LANG]",
                     help="SRT file to burn, or (with --mode mux) to add as a soft subtitle track. Repeat it once "
                          "per language to build a multi-track deliverable, each with an optional `:lang` suffix: "
                          "`--srt en.srt:en --srt ja.srt:ja`. A single --srt with no suffix takes --language, as "
                          "it always did. NOTE: .mp4/.mov hold several mov_text tracks but many players show only "
                          "the first, and the format needs ISO-639-2 codes (`eng`, not `en`) -- this tool converts "
                          "them; .mkv is the honest multi-track container and stores the code you give verbatim")
    src.add_argument("--ass", help="ASS file to burn (styles inside the file are used)")
    src.add_argument("--text", help="plain text cue file to convert into SRT (see format above)")
    src.add_argument("--transcribe", action="store_true", help="generate the SRT from the audio with a local speech-to-text engine if one is installed (whisper-cli / whisper / faster-whisper); never required")
    src.add_argument("--language", "--lang", help="language code (e.g. en, ja, zh, ko): the language for --transcribe (default auto), "
                                                  "the tag on the subtitle stream with --mode mux, and the hint that says whether Han-only "
                                                  "text is Chinese, Japanese or Korean when a font is picked by script")
    src.add_argument("--track-title", action=AppendPath, metavar="TITLE",
                     help="--mode mux: the name a player lists a track under, repeated in the same order as --srt "
                          "(default: the language's display name from a frozen table, else the code itself -- the "
                          "table is data, never a guessed or translated name)")
    src.add_argument("--default-track", metavar="LANG",
                     help="--mode mux: mark this language's track `default` so a player selects it by itself "
                          "(default: none, so no player burns in a language the viewer did not ask for)")
    src.add_argument("--offset", default="0", help="shift every cue by TIME (seconds, mm:ss, hh:mm:ss.ms or "
                                                    "hh:mm:ss:ff; a leading - shifts earlier); works for --text, --srt and --ass")
    src.add_argument("--model", default="base", help="whisper model name/path for --transcribe (default base)")
    src.add_argument("--write-srt", help="where to save the generated SRT (default: <text>.srt)")
    src.add_argument("--auto-seconds", type=float, default=3.0, help="duration for cues without timing (default 3)")
    src.add_argument("--gap", type=float, default=0.0, help="gap after auto-timed cues in seconds")
    src.add_argument("--fps", type=float, default=None,
                      help="frame rate for interpreting hh:mm:ss:ff SMPTE timecode cues in --text (non-drop-frame); "
                           "defaults to the input video's own fps when --input is given, required otherwise")
    sty = ap.add_argument_group("style (SRT only)")
    sty.add_argument("--brand", help="brand.json: font, colours, caption size/position/animation defaults")
    sty.add_argument("--font", default=None, help="font family, e.g. 'Noto Sans CJK JP' for Japanese (default DejaVu Sans or brand font)")
    sty.add_argument("--fonts-dir", help="directory with extra .ttf/.otf files")
    sty.add_argument("--size", type=int, default=None, help="font size in ASS points (relative to a 288p script height, scales automatically)")
    sty.add_argument("--color", default=None, help="text colour RRGGBB (default FFFFFF or brand text colour)")
    sty.add_argument("--outline-color", default=None, help="outline colour RRGGBB")
    sty.add_argument("--outline", type=float, default=None, help="outline width (default 2)")
    sty.add_argument("--shadow", type=float, default=0.0, help="shadow depth (default 0)")
    sty.add_argument("--bold", action="store_true")
    sty.add_argument("--position", choices=sorted(ALIGN), default=None, help="on-screen placement (default bottom)")
    sty.add_argument("--margin", type=int, default=None, help="vertical margin from the edge in ASS units (default 30, or the --platform safe zone)")
    sty.add_argument("--platform", choices=PLATFORM_CHOICES, default=None,
                     help="keep the captions out of this destination's UI: the margin becomes the platform's safe "
                          "zone (TikTok's description bar, the Reels/Shorts chrome). An explicit --margin/--position wins")
    sty.add_argument("--box", action="store_true", help="draw an opaque box behind text instead of an outline")
    emo = ap.add_argument_group("emoji (1.15)")
    emo.add_argument("--emoji", choices=["auto", "color", "png", "mono", "none"], default="auto",
                     help="how emoji in the cues are drawn: 'auto' picks the best this machine can do "
                          "(doctor --json .fonts.emoji), 'color' insists on a colour-capable libass, "
                          "'png' composites the --emoji-assets PNGs, 'mono' draws whatever glyph the text "
                          "font has, 'none' strips them")
    emo.add_argument("--emoji-assets", metavar="DIR",
                     help="directory of emoji PNGs named by code point (1f389.png, 1f1ef-1f1f5.png) -- "
                          "Twemoji's assets/72x72 or Noto Emoji's png/128. Nothing is ever downloaded; "
                          "also read from brand.json styles.caption.emoji_assets and FFMPEG_SKILL_EMOJI_ASSETS")
    emo.add_argument("--emoji-scale", type=float, default=1.0,
                     help="emoji box as a multiple of the line's font size (default 1.0)")
    emo.add_argument("--emoji-max", type=int, default=60,
                     help="most emoji overlays one run may build (default 60)")
    sty.add_argument("--max-lines", type=int, default=2, help="most lines one cue may occupy; a longer cue is split into consecutive cues (default 2)")
    sty.add_argument("--fit-size", choices=["auto", "on", "off"], default="auto",
                     help="shrink the caption size until the cue fits --max-lines, BEFORE splitting it: "
                          "'auto' (default) only when no --size was given, 'on' always, 'off' for 1.16 behaviour")
    sty.add_argument("--min-size", type=int, default=None,
                     help="smallest size --fit-size may use, in ASS points (default 13 = 4.5%% of the frame height, "
                          "the legibility floor)")
    sty.add_argument("--fit-size-scope", choices=["file", "cue"], default="file",
                     help="one fitted size for the whole file (default) or one per cue (a size that changes "
                          "cue to cue reads as a mistake, so it is opt-in)")
    sty.add_argument("--min-duration", type=float, default=1.0, help="shortest time a cue stays on screen in seconds, never past the next cue (default 1.0)")
    sty.add_argument("--wrap", choices=list(WRAP_MODES), default="phrase",
                     help="how a cue too wide for the safe area is broken into lines: 'phrase' (default, 1.16) never "
                          "breaks inside a word or on the wrong side of a hyphen, never leaves a lone digit, kana or "
                          "punctuation on a line, prefers Japanese sentence ends and particles over a mid-word break, "
                          "and never ends a line on an article or preposition; 'measured' is 1.15's width-only wrap, "
                          "kept so an older split can be reproduced. Neither ever changes the number of lines, "
                          "rewrites the text or shortens a cue")
    anim = ap.add_argument_group("animation (generates ASS; needs --text or --srt input)")
    anim.add_argument("--animate", choices=["none", "fade", "pop", "slide"], default=None, help="per-cue entrance animation (default none, or brand caption.animate)")
    anim.add_argument("--karaoke", action="store_true", help="word-by-word highlight (fills from --color to --highlight-color across each cue)")
    anim.add_argument("--karaoke-style", choices=["sweep", "word"], default="sweep",
                      help="'sweep' (default): today's \\kf colour fill, one Dialogue event per cue -- unchanged. "
                           "'word': one Dialogue event per word, the active word scaled by --karaoke-scale and "
                           "emboldened, past words in --color, upcoming words in --upcoming-color -- \\k/\\kf can only "
                           "interpolate colour, so this is the only way to also scale/embolden the active word")
    anim.add_argument("--highlight-color", default=None, help="karaoke fill/active-word colour RRGGBB (default FFD200 or brand primary)")
    anim.add_argument("--upcoming-color", default=None,
                      help="--karaoke-style word: colour RRGGBB for words not yet spoken (default B4B4B4)")
    anim.add_argument("--karaoke-scale", type=float, default=112.0,
                      help="--karaoke-style word: the active word's size as a percentage of the caption size (default 112)")
    anim.add_argument("--karaoke-timing", choices=["even", "energy"], default="energy",
                      help="how words are timed inside a cue: 'energy' follows the speech loudness in the audio (default), 'even' splits time equally")
    anim.add_argument("--write-ass", help="where to save the generated ASS (default: next to the output)")
    enc = ap.add_argument_group("encoding")
    enc.add_argument("--crf", type=int, default=18)
    enc.add_argument("--preset", default="medium", choices=X264_PRESETS)
    add_common(ap)
    args = ap.parse_args(_glue_negative_offset(sys.argv[1:]))
    apply_common(args)

    brand = load_brand(args.brand)
    bc, bcap = brand["colors"], brand_caption_style(brand)
    # A brand file that never names a font is not an explicit font: BRAND_DEFAULTS always
    # supplies one, so asking the merged document would turn font-by-script off for every job
    # that passes --brand at all.
    font_explicit = bool(args.font) or bool(args.brand and brand_states_font(brand))
    args.language = args.language or (brand.get("lang") if args.brand else None)
    if args.brand and bcap.get("box") and not args.box:
        args.box = True
    args.font = args.font or (bcap.get("font") if args.brand else None) or brand.get("font") or "DejaVu Sans"
    # --fit-size auto shrinks only a size the skill itself chose. An explicit --size is a
    # statement about the look and is never quietly overridden; a brand's caption size is the
    # same kind of statement, so it counts as explicit too.
    args._size_explicit = args.size is not None or bool(args.brand and bcap.get("size") is not None)
    args.size = args.size if args.size is not None else (bcap.get("size", 24) if args.brand else 24)
    args.color = color_hex(args.color or (bcap.get("color") if args.brand else None) or bc.get("text", "FFFFFF"))
    args.outline_color = color_hex(args.outline_color or bc.get("outline", "000000"))
    args.outline = args.outline if args.outline is not None else (float(bcap.get("outline", 2)) if args.brand else 2.0)
    args.position = args.position or (bcap.get("position", "bottom") if args.brand else "bottom")
    # --platform: the margin is the fraction of the frame that platform's own UI covers
    # (scripts/_platforms.py). An explicit --margin is the more specific statement and wins;
    # without either, the historical default 30 is unchanged.
    # every tool resolves the spellings people write ('youtube-shorts' is 'shorts') in one place
    args.platform = resolve_platform(args.platform)
    if args.margin is None and args.platform and PLATFORMS[args.platform].get("frame"):
        edge = PLATFORMS[args.platform]["safe"]["top" if args.position.startswith("top") else "bottom"]
        args.margin = ass_units(edge)
        info(f"--platform {args.platform}: caption margin {args.margin} ASS units ({edge * 100:.0f}% of the frame height, "
             f"clear of the app's own UI)")
    if args.margin is None:
        args.margin = 30
    # a brand's caption.animate is a burn-in default; over --mode mux (soft subtitles) it used
    # to be applied anyway and then refused as "animation is burn only" -- ignore it there
    args.animate = args.animate or (bcap.get("animate", "none") if args.brand and args.mode != "mux" else "none")
    args.highlight_color = color_hex(args.highlight_color or bc.get("primary", "FFD200"))
    args.upcoming_color = color_hex(args.upcoming_color or bc.get("upcoming", "B4B4B4"))
    if args.karaoke_scale <= 0:
        die("--karaoke-scale must be positive")
    if args.brand and bcap.get("bold") and not args.bold:
        args.bold = True
    if args.brand and bcap.get("karaoke") and not args.karaoke:
        args.karaoke = True
    if args.brand and brand.get("font_file") and not args.fonts_dir:
        args.fonts_dir = str(Path(brand["font_file"]).parent)
    if not (args.srt or args.ass or args.text or args.transcribe):
        die("give one of --srt, --ass, --text or --transcribe")
    if args.mode == "mux":
        if args.ass:
            die("--mode mux takes --srt (or --text/--transcribe), not --ass -- "
                "ASS carries burn-only styling with no soft-subtitle equivalent; use --mode burn for an ASS file")
        if args.animate != "none" or args.karaoke:
            die("--animate/--karaoke render pixels into the picture and require --mode burn")

    args.offset = signed_time_arg(str(args.offset), "--offset")
    if args.max_lines < 1:
        die("--max-lines must be at least 1")
    if args.min_size is not None and args.min_size < 1:
        die("--min-size must be at least 1", kind="input")
    if args.min_size is not None and args.min_size > args.size:
        die(f"--min-size {args.min_size} is larger than --size {args.size}: the floor cannot be "
            "above the size it is a floor for", kind="input")
    if args.min_duration < 0:
        die("--min-duration cannot be negative")

    meta = None
    if args.input:
        meta = probe(args.input)
        if not meta.get("video"):
            die("input has no video stream")
        audio_streams = meta.get("audio_streams") or []
        if audio_streams and not (0 <= args.audio_stream < len(audio_streams)):
            die(f"--audio-stream {args.audio_stream}: input has {len(audio_streams)} audio stream(s), 0..{len(audio_streams) - 1}")
        if args.audio_stream and not audio_streams:
            die("--audio-stream needs an input with audio streams")
    fps_for_tc = args.fps
    if fps_for_tc is None and meta is not None:
        fps_for_tc = meta.get("video", {}).get("fps")

    play_w = play_h = None
    if meta and meta.get("video"):
        play_w, play_h = meta["video"]["width"], meta["video"]["height"]
        if meta["video"].get("rotation") in (90, -90, 270, -270):
            play_w, play_h = play_h, play_w
    # A --plan or --dry-run written before the input exists has no geometry to fit against, and a
    # plan that describes a different FontSize from the run that executes it is not a plan. When
    # --platform names a destination, that destination's frame IS the geometry the real run will
    # have, so the fit is computed against it; with no platform there is nothing to stand in for
    # the frame, and size_used is reported as null rather than presenting the requested size as
    # the size that was used.
    planned_frame = False
    if not (play_w and play_h) and args.platform and PLATFORMS[args.platform].get("frame"):
        frame = PLATFORMS[args.platform]["frame"]
        play_w, play_h = frame["w"], frame["h"]
        planned_frame = True
        info(f"[plan] no geometry to measure yet; fitting the caption size against the "
             f"--platform {args.platform} frame ({play_w}x{play_h})")

    args._fit_floor = args.min_size if args.min_size is not None else ass_units(MIN_CAPTION_FRACTION)
    fit_unmeasurable = not (play_w and play_h)
    fit_stats: dict = {"fit_size": args.fit_size, "size_requested": args.size,
                       "size_used": None if fit_unmeasurable else args.size,
                       "size_floor": args._fit_floor,
                       "size_pct_height": round(args.size * 100.0 / ASS_SCRIPT_HEIGHT, 2),
                       "shrunk": 0, "fit_scope": args.fit_size_scope, "fit_exhausted": False}
    caption_stats: dict = {"shifted": 0, "wrapped": 0, "split": 0, "extended": 0, "dropped": 0,
                           "rebalanced": 0, "wrap": args.wrap, "phrase_breaks": 0}
    caption_stats.update(fit_stats)

    def fit_params():
        return dict(size=fit_stats["size_requested"], min_size=args._fit_floor,
                    max_lines=args.max_lines, play_w=play_w, play_h=play_h,
                    mode=args.wrap, lang=args.language, scope=args.fit_size_scope,
                    safe_fraction=safe_width_fraction(args, play_w))

    def fit_the_size(cue_list):
        """Shrink --size until every cue fits --max-lines, BEFORE the cue is split.

        This is the whole point of the ordering: at a size the cue cannot fit, layout_cues splits
        the sentence into consecutive cues and half of it arrives late (eval 17). The text is never
        touched -- only the type size, and never below the legibility floor.
        """
        if args.fit_size == "off" or (args.fit_size == "auto" and args._size_explicit):
            fit_stats["size_used"] = args.size    # a stated size IS the size used
            return
        if fit_unmeasurable:
            # Nothing to measure against: size_used stays null rather than presenting the
            # requested size as one that was fitted.
            return
        if args.mode == "mux":
            # Soft subtitles carry no size: the player picks it. Shrinking would change nothing a
            # viewer sees and would silently change the SRT this run writes, so the mux path is
            # left exactly as 1.16 wrote it.
            return
        fit = fit_size(cue_list, **fit_params())
        fit_stats["size_used"] = fit["size"]
        fit_stats["size_source"] = "platform-frame" if planned_frame else "input"
        fit_stats["shrunk"] = fit["shrunk"]
        fit_stats["fit_exhausted"] = bool(fit["shrunk"]) and not fit["fits"]
        fit_stats["size_pct_height"] = round(fit["size"] * 100.0 / ASS_SCRIPT_HEIGHT, 2)
        if fit["size"] != args.size:
            info(f"caption size {args.size} -> {fit['size']} ASS units "
                 f"({fit_stats['size_pct_height']:.1f} % of frame height) so {fit['shrunk']} cue(s) "
                 f"fit --max-lines {args.max_lines}; floor {args._fit_floor}")
            args.size = fit["size"]
        elif fit_stats["fit_exhausted"]:
            info(f"caption size stays {args.size} ASS units: {fit['shrunk']} cue(s) still need more "
                 f"than {args.max_lines} line(s) at the floor {args._fit_floor} and are split "
                 "(--min-size goes smaller; `|` sets the break yourself)")
        if args.fit_size_scope == "cue":
            # Each cue is laid out at ITS OWN size, not at the file minimum. A cue drawn larger
            # has a NARROWER line in em, so wrapping everything to the minimum size's (widest)
            # budget and then drawing some cues large put lines off the side of the frame.
            args._fit_cue_em = [line_em_for_size(fit["per_cue"].get(i, fit["size"]),
                                                 play_w, play_h,
                                                 safe_fraction=safe_width_fraction(args, play_w))
                                for i in range(len(cue_list))]
            args._fit_cue_size = [fit["per_cue"].get(i, fit["size"]) for i in range(len(cue_list))]

    def lay_out(cue_list):
        """Wrap to the safe area, split past --max-lines, lengthen to --min-duration, shift by
        --offset -- the one place every cue source goes through, so an SRT, a cue file and a
        transcript all come out equally readable."""
        fit_the_size(cue_list)
        out, stats = layout_cues(cue_list, max_em=max_line_em(args, play_w, play_h),
                                 max_lines=args.max_lines, min_duration=args.min_duration,
                                 offset=args.offset, wrap=args.wrap, lang=args.language,
                                 per_cue_em=getattr(args, "_fit_cue_em", None),
                                 per_cue_size=getattr(args, "_fit_cue_size", None))
        # which size each OUTPUT cue belongs to, after splits have renumbered them
        args._fit_sizes_out = stats.pop("cue_sizes", None)
        report_layout(stats)
        caption_stats.clear()
        caption_stats.update(stats)
        caption_stats.update(fit_stats)
        return out, any(v for k, v in stats.items() if k != "wrap")

    # --srt is repeatable since 1.16 (one per language, each with an optional `:lang` suffix).
    # Every path below that burns, adjusts or transcribes works on the FIRST one, which is what
    # `--srt x.srt` has always meant; the extra tracks only exist for --mode mux.
    srt_tracks: List[Tuple[str, Optional[str]]] = []
    for token in (args.srt or []):
        path_part, lang_part = split_srt_lang(token)
        srt_tracks.append((path_part, lang_part))
    if len(srt_tracks) == 1 and srt_tracks[0][1] is None and args.language:
        srt_tracks[0] = (srt_tracks[0][0], args.language)
    if srt_tracks and args.mode != "mux" and len(srt_tracks) > 1:
        die("burning renders pixels; only one language can be in the picture -- burn one and mux "
            "the rest (caption.py OUT --mode mux --srt en.srt:en --srt ja.srt:ja)", kind="input")
    seen_langs = [lang for _p, lang in srt_tracks if lang]
    for lang in seen_langs:
        if not LANG_TOKEN_RE.match(lang):
            die(f"--srt: '{lang}' is not a language code (two or three letters, optionally with a "
                "region, e.g. en, ja, pt-BR)", kind="input")
    if len(set(seen_langs)) != len(seen_langs):
        dup = sorted({l for l in seen_langs if seen_langs.count(l) > 1})
        die(f"--srt: two tracks tagged '{', '.join(dup)}' -- a player cannot tell them apart; give "
            "each track its own code (and --track-title to name them)", kind="input")
    if args.track_title and len(args.track_title) > max(1, len(srt_tracks)):
        die(f"--track-title given {len(args.track_title)} times for {len(srt_tracks)} --srt file(s)",
            kind="input")
    args.srt = srt_tracks[0][0] if srt_tracks else None
    srt_path = args.srt
    if args.transcribe:
        if not args.input:
            die("--transcribe needs the input video")
        # the sidecar goes next to the output like the --text one, not into the source folder
        # where it silently replaced a hand-written <input>.srt (review 5)
        srt_path = args.write_srt or os.path.splitext(args.output or default_output(args.input, "captioned"))[0] + ".srt"
        if STATE.dry_run:
            cues = []
            info(f"[dry-run] would transcribe {args.input} and write {srt_path}")
        else:
            if os.path.exists(srt_path) and not getattr(args, "overwrite", False):
                info(f"warning: {srt_path} already exists and will be replaced by the transcript (pass --overwrite to confirm)")
            cues = transcribe(args.input, srt_path, args.language, args.model, args.audio_stream)
            args._word_timings = whisper_word_timings(srt_path)
            cues, changed = lay_out(cues)
            if changed:
                write_srt(cues, srt_path)
            info(f"wrote {srt_path} ({len(cues)} cues)")
        args.text = None
    if args.text:
        cues = parse_text_cues(args.text, args.auto_seconds, args.gap, fps_for_tc)
        cues, _ = lay_out(cues)
        if args.write_srt:
            srt_path = args.write_srt
        elif args.input:
            # keep generated files next to the output, not in the user's source folder
            out_guess = args.output or default_output(args.input, "captioned")
            srt_path = os.path.splitext(out_guess)[0] + ".srt"
        else:
            srt_path = os.path.splitext(args.text)[0] + ".srt"
        if not STATE.dry_run:
            write_srt(cues, srt_path)
        tc_range = f", {fmt_smpte_time(cues[0][0], fps_for_tc)}-{fmt_smpte_time(cues[-1][1], fps_for_tc)} @ {fps_for_tc:g}fps" if fps_for_tc else ""
        info(f"wrote {srt_path} ({len(cues)} cues{tc_range})")
        if not args.input:
            print(srt_path)
            return 0

    if not args.input:
        die("input video is required unless you only use --text/--write-srt")

    output = args.output or default_output(args.input, "captioned")

    # An SRT or ASS the caller wrote is never edited in place: when --offset/--max-lines/
    # --min-duration change it, the adjusted copy is written next to the output and burned instead.
    # The path is repointed in BOTH modes: --dry-run/--plan must describe the job the real run
    # executes, so the planned command names the adjusted copy the real run burns. Only the
    # WRITING waits for a real run (the rule every side file in this tool follows), which is why
    # the cues are kept in hand below for the font sample and the ASS generator.
    planned_cues: Optional[List[Tuple[float, float, str]]] = None
    side_notes: List[str] = []
    ass_sample_path = args.ass
    if args.srt and not (args.text or args.transcribe) and os.path.exists(srt_path or ""):
        adjusted, changed = lay_out(parse_srt(srt_path))
        if changed:
            new_srt = os.path.splitext(output)[0] + "_adjusted.srt"
            if STATE.dry_run:
                info(f"[dry-run] would write {new_srt} ({len(adjusted)} cues, adjusted from {os.path.basename(srt_path)})")
            else:
                write_srt(adjusted, new_srt)
                info(f"wrote {new_srt} ({len(adjusted)} cues, adjusted from {os.path.basename(srt_path)})")
            srt_path = new_srt
            planned_cues = adjusted
            side_notes.append(f"the burned subtitles are {new_srt}, the adjusted copy of "
                              f"{os.path.basename(args.srt)} this run writes (--offset/--max-lines/--min-duration); "
                              "re-run this command without --dry-run to produce it")
    if args.ass and args.offset and os.path.exists(args.ass):
        shifted = os.path.splitext(output)[0] + "_offset.ass"
        if STATE.dry_run:
            info(f"[dry-run] would write {shifted} (cues shifted by {args.offset:+g} s)")
        else:
            n = shift_ass_file(args.ass, shifted, args.offset)
            info(f"wrote {shifted} ({n} cues shifted by {args.offset:+g} s)")
        args.ass = shifted
        side_notes.append(f"the burned subtitles are {shifted}, the offset copy of "
                          f"{os.path.basename(ass_sample_path)} this run writes; re-run this command "
                          "without --dry-run to produce it")
    # a side file this run has planned but (under --dry-run) not written is still the file the
    # command names, so its absence must not be reported as a missing input
    planned_only = STATE.dry_run and planned_cues is not None
    planned_ass = STATE.dry_run and bool(args.ass) and args.ass != ass_sample_path

    if args.mode == "mux":
        if not srt_path or (not os.path.exists(srt_path) and not planned_only
                            and not (STATE.dry_run and (args.text or args.transcribe))):
            die(f"SRT file not found: {srt_path}")
        codec = mux_subtitle_codec(output)
        # Keep any subtitle track(s) the input already has (e.g. chaining --mode mux once per
        # language to build a multi-language set) -- copied byte-identical, distinct from the
        # newly-added SRTs' own codec below.
        existing_subs = meta.get("subtitle_streams") or 0
        # the first entry's path is srt_path, which --offset/--max-lines may have repointed at an
        # adjusted copy; the rest are taken as written
        added = [(srt_path, srt_tracks[0][1] if srt_tracks else args.language)] + \
                [(p, lang) for p, lang in srt_tracks[1:]]
        for path, _lang in added[1:]:
            if not os.path.exists(path) and not STATE.dry_run:
                die(f"SRT file not found: {path}")
        titles = list(args.track_title or [])
        mp4_family = Path(output).suffix.lower() in (".mp4", ".m4v", ".mov")
        dropped_titles: List[str] = []
        notes = list(side_notes)
        maps = ["-map", "0:v:0"]
        cmd = ffmpeg_base() + ["-i", args.input]
        for path, _lang in added:
            cmd += ["-i", path]
        if meta.get("audio"):
            maps += ["-map", f"0:a:{args.audio_stream}"]
        if existing_subs:
            maps += ["-map", "0:s?"]
        for n in range(len(added)):
            maps += ["-map", f"{n + 1}:0"]
        cmd += maps + ["-c:v", "copy"] + (["-c:a", "copy"] if meta.get("audio") else [])
        for i in range(existing_subs):
            cmd += [f"-c:s:{i}", "copy"]
        tracks: List[Dict[str, Any]] = []
        for i in range(existing_subs):
            kept = (meta.get("subtitle_stream_details") or [])
            detail = kept[i] if i < len(kept) else {}
            tracks.append({"index": i, "file": None, "language": detail.get("language"),
                           "title": detail.get("title"), "codec": detail.get("codec"),
                           "default": False, "cues": None, "kept_from_input": True})
        for n, (path, lang) in enumerate(added):
            idx = existing_subs + n
            cmd += [f"-c:s:{idx}", codec]
            stored = container_language(lang, output) if lang else None
            if stored:
                cmd += [f"-metadata:s:s:{idx}", f"language={stored}"]
            title = track_title_for(lang, titles[n] if n < len(titles) else None)
            # `-metadata:s:s:N title=` is written for Matroska and silently dropped by the MPEG-4
            # muxer (verified on ffmpeg 6.1: ffprobe reads no title back), so an MP4 track is
            # reported with `title: null` rather than a name the file does not carry.
            if title and not mp4_family:
                cmd += [f"-metadata:s:s:{idx}", f"title={title}"]
            elif title:
                dropped_titles.append(title)
                title = None
            is_default = bool(args.default_track and lang
                              and lang.lower() == args.default_track.lower())
            # ALWAYS stated, never only when it is "default": given two or more new subtitle
            # streams and nothing said, ffmpeg flags the first one `default` by itself -- which
            # is the opposite of what --default-track promises and made tracks[].default
            # disagree with the file it describes. An explicit 0 suppresses that.
            cmd += [f"-disposition:s:{idx}", "default" if is_default else "0"]
            cues_n = None
            if os.path.exists(path):
                try:
                    cues_n = len(parse_srt(path))
                except SystemExit:
                    cues_n = None
            tracks.append({"index": idx, "file": path, "language": stored, "title": title,
                           "codec": codec, "default": is_default, "cues": cues_n,
                           "kept_from_input": False})
        if args.default_track and not any(t["default"] for t in tracks):
            die(f"--default-track {args.default_track}: no --srt was tagged with that language",
                kind="input")
        # MPEG-4 has no way to say "no default subtitle track": the muxer sets the track-header
        # ENABLED flag on the first subtitle track whatever `-disposition:s:N 0` asks for
        # (verified on ffmpeg 6.1; `-disposition:s:N default` does move it to another track).
        # Matroska honours the explicit 0. Report what the file carries, not what was asked.
        if mp4_family and tracks and not any(t["default"] for t in tracks):
            tracks[0]["default"] = True
            notes.append("an MPEG-4 container always enables its first subtitle track, so "
                         f"{tracks[0]['language'] or 'track 0'} is marked default even though none "
                         "was asked for; .mkv is the container that can leave every track off")
        cmd += [output]
        total = existing_subs + len(added)
        if total > 2 and mp4_family:
            notes.append(f"{total} subtitle tracks in an MPEG-4 container: the tracks are all there, "
                         "but many players only ever show the first -- write to .mkv for a "
                         "deliverable a viewer can actually switch")
        if dropped_titles:
            notes.append("an MPEG-4 container has no per-track title this tool can write back "
                         f"({', '.join(dropped_titles)} would be dropped), so the tracks are "
                         "reported with no title; .mkv keeps the names")
        if mp4_family and any(
                t["language"] and len(t["language"]) != 3 for t in tracks if not t["kept_from_input"]):
            notes.append("MPEG-4 stores the language as a three-letter ISO-639-2 code and drops "
                         "anything else; a code this tool has no conversion for was passed through "
                         "as given and may not survive")
        run(cmd)
        result = probe(output, role="output")
        info(f"wrote {output} ({fmt_secs(result.get('duration'))}, mux, {len(added)} "
             f"subtitle track(s) added, codec {codec})")
        emit(output, tracks=tracks, subtitle_tracks=total, **({"notes": notes} if notes else {}))
        return 0

    # A font that covers the text, before anything is rendered: non-Latin cues in a Latin-only
    # family come out as empty boxes, and ffmpeg exits 0 all the same (see references/gotchas.md).
    if args.ass:
        sample = parse_ass_dialogue(ass_sample_path) if ass_sample_path and os.path.exists(ass_sample_path) else ""
    elif args.text or args.transcribe:
        sample = "\n".join(t for _, _, t in cues)
    elif planned_cues is not None:
        sample = "\n".join(t for _, _, t in planned_cues)
    else:
        sample = "\n".join(t for _, _, t in parse_srt(srt_path)) if os.path.exists(srt_path or "") else ""
    _script, font_file, font_family = script_font_for_text(
        sample, lang=args.language, font=args.font, font_explicit=font_explicit,
        fonts_dir=args.fonts_dir)
    if font_file:
        args.font = font_family or args.font
        if not args.fonts_dir:
            args.fonts_dir = os.path.dirname(font_file)

    # Emoji (1.15). Decided once, on the cues the burn will actually use: libass cannot place a
    # PNG, so the text keeps its place in the ASS (with the gap reserved) and each emoji becomes an
    # overlay composited after the ass= filter. A cue file that has no emoji costs nothing here.
    emoji_plan = None
    emoji_cues = None
    if not args.ass:
        if args.text or args.transcribe:
            src_cues = cues
        elif planned_cues is not None:
            src_cues = planned_cues
        elif os.path.exists(srt_path or ""):
            src_cues = parse_srt(srt_path)
        else:
            src_cues = []
        if src_cues and has_emoji("\n".join(t for _s, _e, t in src_cues)):
            emoji_cues, emoji_plan = plan_emoji(src_cues, args, play_w, play_h,
                                                brand if args.brand else None)
    # the PNG route and --emoji none both change the drawn text, so they need the generated ASS
    force_ass = bool(emoji_plan and (emoji_plan.get("overlays") or emoji_plan.get("mode") == "none"))
    if emoji_plan and emoji_plan.get("box_px"):
        args._emoji_box_px = emoji_plan["box_px"]

    if (args.animate != "none" or args.karaoke or force_ass) and not args.ass:
        # both sources are already laid out: `cues` above, and srt_path was rewritten in place of
        # the caller's file when --offset/--max-lines/--min-duration changed anything
        cues_for_ass = emoji_cues if emoji_cues is not None else (
            cues if (args.text or args.transcribe) else (
                planned_cues if planned_cues is not None else parse_srt(srt_path)))
        if args.karaoke and not getattr(args, "_word_timings", None):
            args._word_timings = whisper_word_timings(srt_path)
        ass_path = args.write_ass or os.path.splitext(output)[0] + ".ass"
        w, h = meta["video"]["width"], meta["video"]["height"]
        if meta["video"].get("rotation") in (90, -90, 270, -270):
            w, h = h, w
        if not STATE.dry_run:  # the generated ASS is an artifact of this run: a plan writes nothing
            write_ass(cues_for_ass, ass_path, args, w, h, video=args.input if meta.get("audio") else None)
        info(f"wrote {ass_path} ({len(cues_for_ass)} cues, animate={args.animate}, karaoke={args.karaoke})")
        args.ass = ass_path
        generated_ass = True
    else:
        generated_ass = False

    if args.ass:
        if not generated_ass and not os.path.exists(args.ass) and not planned_ass:
            die(f"ASS file not found: {args.ass}")
        vf = f"ass={escape_filter_path(args.ass)}"
        if args.fonts_dir:
            vf += f":fontsdir={escape_filter_path(args.fonts_dir)}"
    else:
        if not srt_path or (not os.path.exists(srt_path) and not planned_only
                            and not (STATE.dry_run and (args.text or args.transcribe))):
            die(f"SRT file not found: {srt_path}")
        style = [
            f"FontName={ass_font_name(args.font)}",
            f"FontSize={args.size}",
            f"PrimaryColour={ass_color(args.color)}",
            f"OutlineColour={ass_color(args.outline_color)}",
            f"BackColour={ass_color(args.outline_color, 0x80)}",
            f"BorderStyle={3 if args.box else 1}",
            f"Outline={args.outline:g}",
            f"Shadow={args.shadow:g}",
            f"Bold={-1 if args.bold else 0}",
            f"Alignment={ALIGN[args.position]}",
            f"MarginV={args.margin}",
        ]
        force = ",".join(style).replace("\\", "\\\\").replace("'", "\\'")
        vf = f"subtitles={escape_filter_path(srt_path)}:force_style='{force}'"
        if args.fonts_dir:
            vf += f":fontsdir={escape_filter_path(args.fonts_dir)}"

    cmd = ffmpeg_base() + ["-i", args.input]
    chains, emoji_inputs = emoji_filter_chain(emoji_plan or {}, "vsub", "vout") if emoji_plan else ([], [])
    if chains:
        for spec in emoji_inputs:
            cmd += spec
            asset = spec[-1]
            if asset not in STATE.plan_inputs:
                STATE.plan_inputs.append(asset)
        graph = ";".join([f"[0:v]{vf}[vsub]"] + chains)
        cmd += ["-filter_complex", graph, "-map", "[vout]"]
    else:
        cmd += ["-map", "0:v:0", "-vf", vf]
    if meta.get("audio"):
        cmd += ["-map", f"0:a:{args.audio_stream}"]
    cmd += video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += (aac_args() if meta.get("audio") else ["-an"]) + [output]
    run(cmd)
    result = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(result.get('duration'))})")
    extra = {"notes": side_notes} if side_notes else {}
    # 1.17.1: say so when the words on screen are the words that were handed in. This tool never
    # rewrites, shortens or translates a cue -- only line breaks, timing and type size move -- so
    # the honest sentence in a report ("the text is yours, unchanged") needs no extra judgement.
    # Review 17 finding 5: a cue SPLIT across two consecutive cues, a dropped cue, transcription
    # and `--emoji none` (which str.replace()s glyphs out of the drawn text) all change what the
    # viewer reads, so none of them may be reported as unchanged. Wrapping, line breaks and
    # timing do not count -- the words are the same.
    caption_stats["text_unchanged"] = bool(
        not args.transcribe
        and not caption_stats.get("dropped")
        and not caption_stats.get("split")
        and (emoji_plan or {}).get("mode") != "none")
    if caption_stats["text_unchanged"]:
        info("caption text unchanged: the cues were burned exactly as given (line breaks, timing "
             "and type size only)")
    extra["caption"] = dict(caption_stats)
    if emoji_plan:
        notes = list(extra.get("notes") or [])
        if emoji_plan["mode"] == "mono":
            notes.append("emoji rendered monochrome (no colour path on this ffmpeg; "
                         "--emoji-assets DIR for colour)")
        if emoji_plan["mode"] == "none":
            notes.append("emoji stripped from the drawn text (--emoji none)")
        if emoji_plan["missing"]:
            notes.append("no PNG asset for " + ", ".join(emoji_plan["missing"]))
        if notes:
            extra["notes"] = notes
        extra["emoji"] = {k: v for k, v in emoji_plan.items() if k not in ("overlays", "box_px")}
        extra["emoji"]["overlays"] = len(emoji_plan.get("overlays") or [])
    emit(output, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
