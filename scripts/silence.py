#!/usr/bin/env python3
"""Remove silences / dead air (jump-cut editing) or just list them.

Detects quiet stretches with ffmpeg's silencedetect, keeps a margin on each
side so words are not clipped, drops gaps shorter than --min-silence, and
writes a frame-accurate re-encode in one pass (select, and ametadata for the sound).

Examples:
  python3 silence.py talk.mp4                                 # -35 dB, gaps >= 0.6 s, 0.2 s margin
  python3 silence.py talk.mp4 --threshold -40 --min-silence 1 --margin 0.25
  python3 silence.py talk.mp4 --list                          # print the silences and the resulting cut list, no output
  python3 silence.py talk.mp4 --edl keep.txt                  # also save the kept ranges (START-END per line, cut.py --segments format)
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# `detect` moved into _common/probe.py in 1.16.0 so metadata.py --auto-chapters can measure the
# same silences without importing this tool; the body is unchanged and the name still lives here.
from _common import (filler_spans, FILLER_WORDS, FILLER_AMBIGUOUS, FILLER_DISCOURSE_MARKERS,
                     FILLER_PAD, read_text_or_die)
from _common import asr as _asr
from _common.emit import warn
from _common import refuse_existing_outputs, refuse_output_is_input, _check_output_path
from _common.emit import refuse
from _common import detect_silences as detect, STATE, video_args, add_common, apply_common, audio_codec_for, cfr_args, default_output, die, emit, ffmpeg_base, info, is_audio_output, print_json, probe, run, X264_PRESETS, measured_level_dbfs, fmt_secs



def merge_spans(spans: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """`spans` sorted and coalesced: any pair that touches or overlaps becomes one.

    keep_ranges() walks a single cursor forward, so it needs a removal list in which no span
    starts before the previous one ended. Silences and filler spans are each merged only among
    themselves -- and a mumbled "um" is very often quiet enough to sit INSIDE a detected silence --
    so the union has to be taken before the two lists are handed over as one.
    """
    out: List[Tuple[float, float]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


# around each cut, how many seconds on either side the level is measured over, and how close to
# --threshold (in dB) that level may come before the cut is flagged: room tone sits far below the
# threshold, a breath or a word's weak tail just under it
CUT_LEVEL_WINDOW = 0.05
CUT_SOUND_MARGIN_DB = 10.0
CUT_LEVEL_RATE = 8000
CUT_LEVEL_CHANNELS = 2  # measured one by one; a surround source is folded to two first
DIGITAL_SILENCE_DB = -90.0  # 2.20: at or below this a span is digital silence (16-bit dither sits near -96)
BREATH_FLOOR = 0.12  # shortest gap silencedetect is asked for under --speech-aware


def speech_aware_silences(path: str, threshold: float, min_silence: float) -> "Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]":
    """(sentence-boundary silences to remove, breaths kept) for --speech-aware.

    Re-runs the same silencedetect() already used everywhere else in this file, but with a much
    shorter minimum duration, so short in-sentence breaths are measured at all -- the plain
    `detect()` call above never sees them because its own --min-silence floor filters them out
    before they reach Python. Every gap silencedetect measured that is still shorter than
    --min-silence sits *inside* a sentence -- the two speech-flagged stretches on either side of
    it are close together in time because nothing longer separated them from the gaps around
    them -- and is kept rather than cut; --min-silence keeps the meaning it already has for
    --filler and the plain run: the shortest gap this tool will remove."""
    floor = min(BREATH_FLOOR, min_silence)
    fine = detect(path, threshold, floor)
    boundaries, breaths = [], []
    for s, e in fine:
        length = (e - s) if e != float("inf") else float("inf")
        if length >= min_silence:
            boundaries.append((s, e))
        else:
            breaths.append((s, e))
    return boundaries, breaths


def keep_ranges(silences: List[Tuple[float, float]], duration: float, margin: float, min_keep: float) -> List[Tuple[float, float]]:
    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in sorted(silences):
        s_adj = max(cursor, s + margin)
        if s_adj - cursor >= min_keep:
            keeps.append((cursor, s_adj))
        # max(cursor, ...) so the walk is monotone. A span nested inside the previous one used to
        # rewind the cursor and hand back the very stretch that had just been removed: with a
        # filler word inside a detected silence, adding --filler made the tool remove LESS.
        # merge_spans() above is the caller-side fix; this keeps the function safe on its own.
        cursor = max(cursor, min(duration, e - margin) if e != float("inf") else duration)
    if duration - cursor >= min_keep:
        keeps.append((cursor, duration))
    return keeps


def time_map(keeps: List[Tuple[float, float]], duration: float) -> Dict[str, Any]:
    """Each kept range with its time in the source and in the output, and each removed range with
    the output time it was cut at: re-timing subtitles, or finding a removed sentence again."""
    kept: List[Dict[str, float]] = []
    removed: List[Dict[str, float]] = []
    out, prev = 0.0, 0.0
    for s, e in keeps:
        # the render cuts on bounds rounded to the millisecond (between(t,s,e) below): advance by
        # that rounded length, or every off-grid range adds its own error to every later time
        s, e = round(s, 3), round(e, 3)
        if s - prev > 0.0005:
            removed.append({"source_start": round(prev, 3), "source_end": round(s, 3), "output_time": round(out, 3)})
        kept.append({"source_start": round(s, 3), "source_end": round(e, 3),
                     "output_start": round(out, 3), "output_end": round(out + (e - s), 3)})
        out += e - s
        prev = e
    if duration - prev > 0.0005:
        removed.append({"source_start": round(prev, 3), "source_end": round(duration, 3), "output_time": round(out, 3)})
    return {"kept": kept, "removed": removed}


def write_time_map(path: str, tm: Dict[str, Any]) -> None:
    """--timemap: JSON, or CSV for a .csv path (one row per kept and removed range)."""
    if os.path.splitext(path)[1].lower() == ".csv":
        rows = ["type,source_start,source_end,output_start,output_end"]
        rows += [f"kept,{k['source_start']:.3f},{k['source_end']:.3f},{k['output_start']:.3f},{k['output_end']:.3f}" for k in tm["kept"]]
        rows += [f"removed,{r['source_start']:.3f},{r['source_end']:.3f},{r['output_time']:.3f},{r['output_time']:.3f}" for r in tm["removed"]]
        text = "\n".join(rows) + "\n"
    else:
        text = json.dumps(tm, indent=2) + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def cut_levels(path: str, tm: Dict[str, Any], duration: float,
               filler_spans_: List[Tuple[float, float]]) -> Optional[List[Dict[str, Any]]]:
    """The RMS level just around every cut, in dBFS (None for digital silence), measured on the
    source: one decode at CUT_LEVEL_RATE, CUT_LEVEL_WINDOW on each side of the cut point. A probe
    of the output can say its length and streams are right, not whether a cut landed in a breath
    or a word's weak tail; the level there is the measurable part of that question. `edge` is
    `out` where the source is left, `in` where it is picked up again; `filler` marks an edge that
    sits on a removed word (it is meant to sit in sound). Each channel is measured on its own and
    the loudest is reported: a mono mix reads antiphase stereo as silence. The PCM goes to a temp
    file and only the windows are read back, so an hour of audio is not held in memory. None when
    the decode fails: an unmeasured cut is not a silent one."""
    import array
    import math
    import tempfile
    from _common import require_tool, run_analysis
    points = []
    for r in tm["removed"]:
        for t, edge in ((r["source_start"], "out"), (r["source_end"], "in")):
            if (edge == "out" and t <= 0.0005) or (edge == "in" and t >= duration - 0.0005):
                continue
            # this edge, not the whole removed range: a filler merged into a silence leaves the
            # silence's own edge next to speech, and that one still gets checked
            on_word = any(fs - CUT_LEVEL_WINDOW <= t <= fe + CUT_LEVEL_WINDOW for fs, fe in filler_spans_)
            points.append((t, r["output_time"], edge, on_word))
    if not points:
        return []
    channels = CUT_LEVEL_CHANNELS
    half = int(CUT_LEVEL_WINDOW * CUT_LEVEL_RATE)
    frame = 2 * channels
    out = []
    with tempfile.TemporaryDirectory(prefix="silence-levels-") as tmp:
        raw = os.path.join(tmp, "pcm.s16le")
        proc = run_analysis([require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-vn",
                             "-ac", str(channels), "-ar", str(CUT_LEVEL_RATE), "-f", "s16le", "-y", raw],
                            check=False, text=False)
        if proc.returncode != 0 or not os.path.isfile(raw) or not os.path.getsize(raw):
            return None
        with open(raw, "rb") as fh:
            for t, ot, edge, on_word in points:
                first = max(0, int(round(t * CUT_LEVEL_RATE)) - half)
                fh.seek(first * frame)
                data = fh.read(2 * half * frame)
                block = array.array("h")
                block.frombytes(data[: len(data) // frame * frame])
                if sys.byteorder == "big":
                    block.byteswap()
                level = None
                if block:
                    n = len(block) // channels
                    peak = max(math.sqrt(sum(x * x for x in block[c::channels]) / n) for c in range(channels)) / 32768.0
                    level = round(20 * math.log10(peak), 1) if peak > 0 else None
                entry = {"source_time": round(t, 3), "output_time": round(ot, 3), "edge": edge, "rms_dbfs": level}
                if on_word:
                    entry["filler"] = True
                out.append(entry)
    return out


def _word_list(text: "str") -> "list":
    return [w.strip() for w in str(text or "").replace(",", "\n").splitlines() if w.strip()]


def resolve_filler(args, meta):
    """(the `filler` result block, the spans to remove) for --filler. Refuses before any encode.

    Never without measured word timings: no heuristic fallback, no guess from the filename. The
    three refusals below are the whole safety story for this flag.
    """
    if not args.words and not args.transcribe:
        die("--filler needs word timings: pass --words transcript.json (a whisper JSON with word "
            "timestamps) or --transcribe. There is no way to find a filler word without them -- "
            "cutting the short quiet blips instead would remove real speech.", kind="input")
    source, engine, raw, transcription = None, None, None, {}
    untimed: list = []  # transcript words without a usable timing (a --words file can carry them)
    if args.words:
        try:
            raw = json.loads(read_text_or_die(args.words, "--words"))
        except ValueError as exc:
            die(f"--words {args.words}: not readable JSON ({exc})", kind="input")
        source = f"whisper-json:{args.words}"
        words, had_segments, untimed = _words_from_transcript(raw)
        if not words:
            if had_segments:
                die(f"the transcript in {args.words} has segment timings but no word timings; "
                    "--filler removes words, and cutting on segment boundaries would remove whole "
                    "sentences. Re-run whisper with word timestamps (whisper.cpp "
                    "--output-json-full / faster-whisper word_timestamps=True), or use --list to "
                    "see the pauses instead.", kind="input")
            die(f"no word timings in {args.words}: --filler needs "
                '{"words": [{"word": ..., "start": ..., "end": ...}]} (or the same inside '
                '"segments").', kind="input")
    else:
        # No pre-check for an installed engine here: transcribe_words_result() probes for one and
        # raises the same die_no_engine() refusal when there is none. Two places deciding "is
        # whisper here" is two places to disagree.
        # The engine is driven with ITS word-timestamp option (whisper.cpp --output-json-full,
        # faster-whisper word_timestamps=True, openai-whisper --word_timestamps True). An SRT
        # cannot answer this question: a cue has a start and an end, a word does not.
        # The call's own result, not module state: engine, routing and notes belong to this run.
        asr_run = _asr.transcribe_words_result(args.input, args.filler_lang if args.filler_lang != "auto" else None,
                                               model=args.model, engine=args.engine)
        words, engine = asr_run.words, asr_run.engine
        transcription = dict(asr_run.facts)
        args._asr_notes = list(asr_run.notes)
        family = "parakeet" if engine in _asr.PARAKEET_ENGINES else "whisper"
        source = f"{family}:{engine}" if engine else "whisper"
        if not words:
            die(f"{engine or 'the local engine'} ran but produced no word-level timings, so there "
                "is nothing for --filler to cut on. Some builds do not support word timestamps. "
                "Re-run that engine yourself with them (whisper.cpp --output-json-full / "
                "faster-whisper word_timestamps=True / openai-whisper --word_timestamps True) and "
                "pass the result with --words.", kind="input")

    lang = args.filler_lang
    reported_lang = lang
    if lang == "auto":
        # the language the transcript says it is in: a --words document's own field, else what the
        # engine was told or detected for this run (`--transcribe`). A language that is known and has
        # no built-in list is refused, as --filler-lang names it: the English list would cut real
        # words of that language (Norwegian "er" is "is"), and a transcript with no language at all
        # (or one that says "auto", which is no language either) keeps the English list it always had
        # the ISO 639-2 spellings of the languages that have a built-in list (the mux tag uses them)
        iso3 = {"eng": "en", "spa": "es", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr",
                "ita": "it", "jpn": "ja", "por": "pt", "kor": "ko", "zho": "zh", "chi": "zh",
                "rus": "ru", "nld": "nl", "dut": "nl", "pol": "pl", "tur": "tr"}
        names = {"spanish": "es", "german": "de", "portuguese": "pt", "chinese": "zh", "mandarin": "zh",
                 "dutch": "nl", "polish": "pl", "turkish": "tr"}

        def _code(value) -> str:
            value = str(value or "").strip().lower().replace("_", "-")
            if value in ("", "auto"):
                return ""
            # a regional tag names its primary language (ja-JP is ja); a three-letter code that is not
            # in the table stays as it is (est is Estonian, not the Spanish "es"); a word such as
            # "english" is cut to its two-letter code; a name whose first two letters are not its
            # code ("spanish" is es, "chinese" zh) is looked up, as whisper's own language table spells it
            primary = value.split("-")[0]
            if primary in iso3:
                return iso3[primary]
            if primary in names:
                return names[primary]
            return primary[:2] if len(primary) > 3 else primary
        spoken = _code((raw or {}).get("language")) if isinstance(raw, dict) else ""
        spoken = spoken or _code(transcription.get("language") or transcription.get("detected_language"))
        if spoken and spoken not in FILLER_WORDS and not args.filler_words:
            die(f"the transcript is in {spoken}, which has no built-in filler list. The languages with one are "
                f"{', '.join(sorted(FILLER_WORDS))}; pass --filler-words FILE with your own list for {spoken}, or "
                "--filler-lang for a language that has one.", kind="input")
        lang = spoken if spoken in FILLER_WORDS else "en"
        # with a custom list the run goes ahead, and the result names the language it heard, not the
        # English list it did not use
        reported_lang = spoken or lang
    listname = "builtin"
    if args.filler_words:
        wordlist = set(_word_list(read_text_or_die(args.filler_words, "--filler-words")))
        listname = args.filler_words
    else:
        if lang not in FILLER_WORDS:
            die(f"--filler-lang {lang}: no built-in filler list for that language. The languages "
                f"with one are {', '.join(sorted(FILLER_WORDS))}; pass --filler-words FILE with "
                "your own list for anything else.", kind="input")
        wordlist = set(FILLER_WORDS[lang])
    wordlist |= set(_word_list(args.filler_extra))
    wordlist -= set(_word_list(args.filler_keep))

    kept: dict = {}
    spans = filler_spans(list(words) + untimed, wordlist, pad=args.filler_pad, stats=kept)
    removed_words = sorted({s["word"] for s in spans})
    warnings = []
    ambiguous = sorted(set(FILLER_AMBIGUOUS.get(lang, ())) & set(
        t for s in spans for t in s["word"].split()))
    if ambiguous:
        warnings.append(
            f"removed {', '.join(ambiguous)} -- in {lang} these are as often ordinary words as "
            f"fillers. Keep one with --filler-keep {ambiguous[0]} and re-run if a sentence lost "
            "its meaning.")
    if FILLER_DISCOURSE_MARKERS.get(lang):
        extra_markers = sorted(set(_word_list(args.filler_extra))
                               & set(FILLER_DISCOURSE_MARKERS[lang]))
        if extra_markers:
            warnings.append(f"--filler-extra {', '.join(extra_markers)}: a discourse marker, not a "
                            "disfluency -- this will cut real sentences.")
    block = {
        "lang": reported_lang, "source": source, "engine": engine,
        **({"transcription": transcription} if engine and transcription else {}),
        "words": sorted(wordlist), "removed": [dict(s) for s in spans],
        "removed_count": len(spans),
        "removed_seconds": round(sum(s["end"] - s["start"] for s in spans), 3),
        "word_timings": len(words), "list": listname, "removed_words": removed_words,
        "warnings": warnings,
        # listed words this run did not cut, and why: a transcript word with no timing has
        # nothing to cut on, and one longer than a filler is a held vowel someone meant
        "matched_untimed": kept.get("matched_untimed", 0),
        "matched_too_long": kept.get("matched_too_long", 0),
    }
    if block["matched_untimed"]:
        warn(f"--filler: {block['matched_untimed']} listed word(s) in the transcript carry no usable timing and were "
             "not removed (nothing measured to cut on)", "filler_words_untimed", count=block["matched_untimed"])
    return block, [(s["start"], s["end"]) for s in spans]


def _words_from_transcript(data):
    """([{word,start,end}], whether the document had segments at all, [{word}] of the words
    that carried no usable timing) from a whisper JSON. The third list lets --filler count a
    listed word it could not cut instead of dropping it unseen."""
    raw, had_segments = [], False
    if isinstance(data, dict):
        raw = list(data.get("words") or [])
        segments = data.get("segments") or []
        had_segments = bool(segments)
        for seg in segments:
            raw.extend((seg or {}).get("words") or [])
    elif isinstance(data, list):
        raw = list(data)
    out, untimed = [], []
    for w in raw:
        if not isinstance(w, dict):
            continue
        try:
            out.append({"word": str(w.get("word") or w.get("text") or ""),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            untimed.append({"word": str(w.get("word") or w.get("text") or "")})
    return out, had_segments, untimed


def silence_kinds(path: str, silences: "List[Tuple[float, float]]", duration: float,
                  threshold: float) -> "Dict[str, Any]":
    """Which detected silences are digital silence and which are quiet sound under the threshold
    (2.20). Both are removed alike, but they are not the same finding: a room tone, a breath or a
    whisper under --threshold is sound, and a report that called all of it "silence" hid that the
    cut took audible material. One more silencedetect pass at DIGITAL_SILENCE_DB finds the digital
    spans; a detected silence that is at least 99% digital counts as digital."""
    if not silences or STATE.dry_run:
        return {}
    digital = [(s, duration if e == float("inf") else e) for s, e in detect(path, DIGITAL_SILENCE_DB, 0.02)]
    labels, tally = [], {"digital": [0, 0.0], "below_threshold": [0, 0.0]}
    for s, e in silences:
        e = duration if e == float("inf") else e
        span = max(e - s, 1e-9)
        covered = sum(max(0.0, min(e, de) - max(s, ds)) for ds, de in digital)
        kind = "digital" if covered / span >= 0.99 else "below_threshold"
        labels.append(kind)
        tally[kind][0] += 1
        tally[kind][1] += e - s
    return {"silence_kinds": labels,
            "silence_breakdown": {"digital": {"count": tally["digital"][0], "seconds": round(tally["digital"][1], 3),
                                              "level_db": DIGITAL_SILENCE_DB},
                                  "below_threshold": {"count": tally["below_threshold"][0],
                                                      "seconds": round(tally["below_threshold"][1], 3),
                                                      "level_db": threshold}}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_tight.<ext>)")
    ap.add_argument("--threshold", type=float, default=-35.0, help="silence level in dBFS (default -35; use -40..-45 for quiet rooms)")
    ap.add_argument("--min-silence", type=float, default=0.6, help="only remove gaps at least this long in seconds (default 0.6)")
    ap.add_argument("--margin", type=float, default=0.2, help="seconds of silence to keep on each side of speech (default 0.2; 0.15 before 2.22)")
    ap.add_argument("--min-keep", type=float, default=0.2, help="drop kept pieces shorter than this (default 0.2)")
    ap.add_argument("--speech-aware", action="store_true",
                    help="keep breaths shorter than --min-silence when they sit inside a sentence "
                         "(measured by re-running silence detection at a much shorter floor), and "
                         "only cut at sentence-boundary pauses (--min-silence or longer). Composes "
                         "with --filler through the same keep_ranges() removal list.")
    ap.add_argument("--list", action="store_true", help="only print silences and the kept ranges")
    ap.add_argument("--edl", help="write the kept ranges to this file, one START-END per line")
    ap.add_argument("--timemap", metavar="FILE",
                    help="write the source-to-output time map: every kept range with its source and output "
                         "times and every removed range with the output time it was cut at; .csv for CSV, "
                         "otherwise JSON (re-time subtitles, find a removed sentence again)")
    fil = ap.add_argument_group("filler words (1.17)")
    fil.add_argument("--filler", action="store_true",
                     help="also remove filler words. Needs measured word timings: pass --words or "
                          "--transcribe. There is no heuristic fallback -- a word is cut only where "
                          "a speech engine timed it.")
    fil.add_argument("--filler-lang", choices=["auto"] + sorted(FILLER_WORDS), default="auto",
                     help="which built-in list to use (default auto: the transcript's language field)")
    fil.add_argument("--filler-words", metavar="FILE",
                     help="one word per line; replaces the built-in list for this run")
    fil.add_argument("--filler-extra", metavar="W[,W...]",
                     help="add words to the list. 'like', 'tipo' and 'cio\u00e8' live here rather than in "
                          "the defaults: they are discourse markers, not disfluencies, and cutting "
                          "them cuts real sentences.")
    fil.add_argument("--filler-keep", metavar="W[,W...]",
                     help="remove words from the built-in list (e.g. --filler-keep \u306a\u3093\u304b)")
    fil.add_argument("--filler-pad", type=float, default=FILLER_PAD,
                     help=f"seconds trimmed either side of a filler word (default {FILLER_PAD})")
    fil.add_argument("--words", metavar="FILE",
                     help="a whisper JSON with word-level timings, for --filler")
    fil.add_argument("--transcribe", action="store_true",
                     help="produce the word timings with a local speech engine, Parakeet or whisper (never required; the same "
                          "bridge caption.py uses)")
    fil.add_argument("--engine", choices=_asr.ENGINE_CHOICES, default=None,
                     help="speech engine for --transcribe (default: $FFMPEG_SKILL_ASR_ENGINE, else auto = Parakeet "
                          "for English speech when installed, else whisper)")
    fil.add_argument("--model", default=None,
                     help="speech model for --transcribe, as caption.py's: a whisper model name/path (default: "
                          "$FFMPEG_SKILL_ASR_MODEL, else base), or a Parakeet model for the Parakeet engines")
    fil.add_argument("--filler-list", action="store_true",
                     help="report what --filler would remove and write nothing")
    fil.add_argument("--max-cuts", type=int, default=400,
                     help="refuse above this many removal ranges: the filter graph grows with them "
                          "(default 400)")
    ap.set_defaults(crf=18)  # --quality's default (the --crf alias was removed in 2.0)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS)
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)
    if args.timemap:
        if os.path.splitext(args.timemap)[1].lower() not in (".json", ".csv"):
            die(f"--timemap must end in .json or .csv: {args.timemap}", kind="input")
        # before any decode or write, so a dry run predicts it too: a missing directory or a
        # directory at the path is a `kind: input` refusal, not a traceback from open()
        _check_output_path([args.timemap])
        # --overwrite allows replacing an old map, never the source, the cut or the EDL
        refuse_output_is_input(args.timemap, args.input)
        for flag, other in (("-o", args.output), ("--edl", args.edl)):
            if other and os.path.realpath(other) == os.path.realpath(args.timemap):
                refuse("input", "timemap_path_taken",
                       f"--timemap {args.timemap} is the same file as {flag}; give the map its own path",
                       timemap=args.timemap, flag=flag, path=other)
        refuse_existing_outputs([args.timemap])

    if args.filler_pad < 0:
        die("--filler-pad cannot be negative: a negative pad turns each word's span inside out "
            "(end before start) and the span is then silently dropped, so nothing is removed",
            kind="input")
    if args.max_cuts < 1:
        die("--max-cuts must be at least 1", kind="input")
    if args.filler_list and not args.filler:
        die("--filler-list reports what --filler would remove: pass --filler as well", kind="input")
    meta = probe(args.input)
    if not meta.get("audio"):
        die("input has no audio stream to analyse")
    duration = meta.get("duration") or 0.0
    breaths: List[Tuple[float, float]] = []
    if args.speech_aware:
        silences, breaths = speech_aware_silences(args.input, args.threshold, args.min_silence)
    elif args.filler:
        silences = []  # --filler alone: remove only the filler-word spans, not generic dead air
    else:
        silences = detect(args.input, args.threshold, args.min_silence)
    filler_info, filler_ranges = resolve_filler(args, meta) if args.filler else (None, [])
    # One sorted, merged removal list through the graph the tool already has: filler removal IS
    # time-range removal, so it reuses keep_ranges() and the same select chain.
    removals = merge_spans(list(silences) + list(filler_ranges))
    keeps = keep_ranges(removals, duration, args.margin, args.min_keep)
    kept = sum(e - s for s, e in keeps)
    removed = max(0.0, duration - kept)
    # `removed_seconds` keeps the meaning it has had since this tool existed: the seconds of
    # SILENCE this run removes. It must not quietly start counting filler time as well, because a
    # caller that has been reading it since 1.0 asked how much dead air went. The silence-only
    # figure is the one the same run would have reported without --filler, so it is computed from
    # the silences alone; everything removed is `removed_seconds_total`.
    silence_only = removed
    if args.filler:
        silence_keeps = keep_ranges(merge_spans(list(silences)), duration, args.margin, args.min_keep)
        silence_only = max(0.0, duration - sum(e - s for s, e in silence_keeps))
    kinds = silence_kinds(args.input, silences, duration, args.threshold)
    summary = {
        "silences": [[round(s, 3), None if e == float("inf") else round(e, 3)] for s, e in silences],
        "keep": [[round(s, 3), round(e, 3)] for s, e in keeps],
        "input_duration": round(duration, 3),
        "kept_duration": round(kept, 3),
        "removed_seconds": round(silence_only, 3),
    }
    if kinds:
        summary.update(kinds)
    if args.speech_aware:
        summary["speech_aware"] = {
            "min_silence": args.min_silence, "floor": min(BREATH_FLOOR, args.min_silence),
            "breaths_kept": len(breaths),
            "breaths_kept_seconds": round(sum((e - s) for s, e in breaths if e != float("inf")), 3),
            "breaths": [[round(s, 3), None if e == float("inf") else round(e, 3)] for s, e in breaths],
        }
        info(f"--speech-aware: {len(breaths)} breath(s) kept "
             f"({summary['speech_aware']['breaths_kept_seconds']:.2f}s), "
             f"{len(silences)} sentence-boundary silence(s) cut")
    if filler_info is not None:
        # removed_seconds above is the silence-only figure, unchanged in meaning; the filler share
        # is reported inside `filler`, and removed_seconds_total is the additive sibling that
        # covers everything this run took out.
        summary["filler"] = filler_info
        summary["removed_seconds_total"] = round(removed, 3)
        info(f"--filler: {filler_info['removed_count']} filler word(s), "
             f"{filler_info['removed_seconds']:.2f}s, from {filler_info['word_timings']} word timings "
             f"({filler_info['lang']}, list {filler_info['list']})")
        for warning in filler_info.get("warnings") or []:
            warn(warning, "filler_removal_caution")
    if getattr(args, "_asr_notes", None):
        # an English-only transcript made on an assumption (asr.assumed_english_note): the
        # bridge already logged the warning; the result document carries it at the top level
        summary["notes"] = list(args._asr_notes)
    if len(keeps) > args.max_cuts:
        die(f"{len(keeps)} keep ranges is above --max-cuts {args.max_cuts}: the filter graph grows "
            "with every range and a graph this size is slow and fragile. Raise --max-cuts if you "
            "mean it, or use --min-silence/--filler-pad to merge the short ones.", kind="input")
    filler_only = args.filler and not args.speech_aware
    if filler_only:
        info(f"--filler only (no --speech-aware): skipping generic silence detection, "
             f"keeping {len(keeps)} range(s): {kept:.2f}s of {duration:.2f}s (removing {removed:.2f}s, filler only)")
    else:
        info(f"{len(silences)} silences, keeping {len(keeps)} ranges: {kept:.2f}s of {duration:.2f}s (removing {removed:.2f}s)")
    if not silences and not filler_only and not (STATE.dry_run and not os.path.exists(args.input)):
        # Nothing under the threshold is a valid result, not a failure -- but an agent that only
        # sees "0 silences" tends to reach for raw ffmpeg next. Say what the floor actually is and
        # what threshold would bite, so the retry is a flag change, not a workaround.
        level = measured_level_dbfs(args.input)
        if level:
            suggested = min(-5.0, round(level["mean_dbfs"] + 6.0))
            summary["hint"] = (f"no passage sits below {args.threshold:g} dBFS for {args.min_silence:g}s; the track's mean level is "
                               f"{level['mean_dbfs']:.1f} dBFS (peak {level['peak_dbfs']:.1f}). For a quiet-room recording try "
                               f"--threshold {suggested:g}, or a shorter --min-silence")
        else:
            summary["hint"] = f"no passage sits below {args.threshold:g} dBFS for {args.min_silence:g}s; try a higher --threshold (e.g. -25) or a shorter --min-silence"
        info("hint: " + summary["hint"])

    tm = time_map(keeps, duration)
    points: Any = False  # False: not measured (a dry run over a pending input); None: the decode failed
    if not (STATE.dry_run and not os.path.exists(args.input)):
        points = cut_levels(args.input, tm, duration, list(filler_ranges))
    if points is None:
        warn("could not decode the source to measure the level at each cut; cut_points and cut_warnings are null "
             "(unmeasured, not silent): listen at the cuts", "cut_levels_unmeasured")
        summary["cut_points"] = summary["cut_warnings"] = None
    elif points is not False:
        near = [{k: v for k, v in c.items() if k != "filler"} for c in points
                if not c.get("filler") and c["rms_dbfs"] is not None and c["rms_dbfs"] > args.threshold - CUT_SOUND_MARGIN_DB]
        summary["cut_points"] = points
        summary["cut_warnings"] = near
        if near:
            where = ", ".join("%.2fs" % c["source_time"] for c in near[:5]) + (", ..." if len(near) > 5 else "")
            warn(f"{len(near)} cut point(s) sit within {CUT_SOUND_MARGIN_DB:g} dB of --threshold ({where}): "
                 "a breath or a word's weak tail may be cut; listen there, or lower --threshold / raise --margin",
                 "cut_near_sound", cuts=len(near))

    def finish_time_map() -> None:
        """Written last, once the cut it describes exists (or under --list, where the map is the
        result): a map left beside a failed or refused encode would describe media never made."""
        if not args.timemap:
            return
        if not STATE.dry_run:  # an artifact like the EDL: a plan writes nothing
            write_time_map(args.timemap, tm)
            info(f"wrote {args.timemap}")
        summary["timemap"] = args.timemap

    if args.edl:
        if not STATE.dry_run:  # the EDL is an artifact like the cut itself: a plan writes nothing
            with open(args.edl, "w", encoding="utf-8") as fh:
                for s, e in keeps:
                    fh.write(f"{s:.3f}-{e:.3f}\n")
        info(f"wrote {args.edl}")

    if args.list or args.filler_list:
        finish_time_map()
        if args.json:
            emit(None, **summary)
        else:
            print_json(summary)
        return 0
    if not keeps:
        die("nothing would be kept; raise --threshold (e.g. -45) or check the audio")
    if not silences or removed < 0.05:
        info("no removable silence found; output would equal the input")

    output = args.output or default_output(args.input, "tight")
    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    # Not `aselect='{expr}'`: FFmpeg 8.0 and 8.0.1 (Ubuntu 26.04's apt build) ship an aselect that
    # passes every frame through (its activate callback was lost when the filter was converted;
    # fixed in 8.0.2/8.1), which cut the picture and left the sound whole. Tagging the frames the
    # expression keeps (timeline `enable`, the same per-frame t) and selecting the tagged ones keeps
    # exactly the frames aselect keeps, on every release, in a command no longer than before.
    af = (f"ametadata=mode=add:key=ffskill_keep:value=1:enable='{expr}',"
          "ametadata=mode=select:key=ffskill_keep,asetpts=N/SR/TB")
    cmd = ffmpeg_base() + ["-i", args.input]
    audio_only = is_audio_output(output) or not meta.get("video")
    if audio_only:
        cmd += ["-vn"]
    else:
        cmd += ["-vf", vf] + video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += ["-af", af] + audio_codec_for(output) + [output]
    run(cmd)
    r = probe(output, role="output")
    info(f"wrote {output} ({fmt_secs(r['duration'])}, expected ~{kept:.3f}s)")
    finish_time_map()
    emit(output, **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
