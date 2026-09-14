#!/usr/bin/env python3
"""Remove silences / dead air (jump-cut editing) or just list them.

Detects quiet stretches with ffmpeg's silencedetect, keeps a margin on each
side so words are not clipped, drops gaps shorter than --min-silence, and
writes a frame-accurate re-encode in one pass (select/aselect filters).

Examples:
  python3 silence.py talk.mp4                                 # -35 dB, gaps >= 0.6 s, 0.15 s margin
  python3 silence.py talk.mp4 --threshold -40 --min-silence 1 --margin 0.25
  python3 silence.py talk.mp4 --list                          # print the silences and the resulting cut list, no output
  python3 silence.py talk.mp4 --edl keep.txt                  # also save the kept ranges (START-END per line, cut.py --segments format)
"""
import argparse
import json
import os
import sys
from typing import List, Tuple

# `detect` moved into _common/probe.py in 1.16.0 so metadata.py --auto-chapters can measure the
# same silences without importing this tool; the body is unchanged and the name still lives here.
from _common import (filler_spans, FILLER_WORDS, FILLER_AMBIGUOUS, FILLER_DISCOURSE_MARKERS,
                     FILLER_PAD, transcribe_words, read_text_or_die)
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
    source, engine, raw = None, None, None
    if args.words:
        try:
            raw = json.loads(read_text_or_die(args.words, "--words"))
        except ValueError as exc:
            die(f"--words {args.words}: not readable JSON ({exc})", kind="input")
        source = f"whisper-json:{args.words}"
        words, had_segments = _words_from_transcript(raw)
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
        # No pre-check for an installed engine here: transcribe_words() probes for one and
        # raises the same die_no_engine() refusal when there is none. Two places deciding "is
        # whisper here" is two places to disagree.
        # The engine is driven with ITS word-timestamp option (whisper.cpp --output-json-full,
        # faster-whisper word_timestamps=True, openai-whisper --word_timestamps True). An SRT
        # cannot answer this question: a cue has a start and an end, a word does not.
        words, engine = transcribe_words(args.input, args.filler_lang if args.filler_lang != "auto" else None)
        source = f"whisper:{engine}" if engine else "whisper"
        if not words:
            die(f"{engine or 'the local engine'} ran but produced no word-level timings, so there "
                "is nothing for --filler to cut on. Some builds do not support word timestamps. "
                "Re-run that engine yourself with them (whisper.cpp --output-json-full / "
                "faster-whisper word_timestamps=True / openai-whisper --word_timestamps True) and "
                "pass the result with --words.", kind="input")

    lang = args.filler_lang
    if lang == "auto":
        lang = str((raw or {}).get("language") or "").lower()[:2] if isinstance(raw, dict) else ""
        lang = lang if lang in FILLER_WORDS else "en"
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

    spans = filler_spans(words, wordlist, pad=args.filler_pad)
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
        "lang": lang, "source": source, "engine": engine,
        "words": sorted(wordlist), "removed": [dict(s) for s in spans],
        "removed_count": len(spans),
        "removed_seconds": round(sum(s["end"] - s["start"] for s in spans), 3),
        "word_timings": len(words), "list": listname, "removed_words": removed_words,
        "warnings": warnings,
    }
    return block, [(s["start"], s["end"]) for s in spans]


def _words_from_transcript(data):
    """([{word,start,end}], whether the document had segments at all) from a whisper JSON."""
    raw, had_segments = [], False
    if isinstance(data, dict):
        raw = list(data.get("words") or [])
        segments = data.get("segments") or []
        had_segments = bool(segments)
        for seg in segments:
            raw.extend((seg or {}).get("words") or [])
    elif isinstance(data, list):
        raw = list(data)
    out = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        try:
            out.append({"word": str(w.get("word") or w.get("text") or ""),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out, had_segments


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_tight.<ext>)")
    ap.add_argument("--threshold", type=float, default=-35.0, help="silence level in dBFS (default -35; use -40..-45 for quiet rooms)")
    ap.add_argument("--min-silence", type=float, default=0.6, help="only remove gaps at least this long in seconds (default 0.6)")
    ap.add_argument("--margin", type=float, default=0.15, help="seconds of silence to keep on each side of speech (default 0.15)")
    ap.add_argument("--min-keep", type=float, default=0.2, help="drop kept pieces shorter than this (default 0.2)")
    ap.add_argument("--list", action="store_true", help="only print silences and the kept ranges")
    ap.add_argument("--edl", help="write the kept ranges to this file, one START-END per line")
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
                     help="produce the word timings with a local whisper (never required; the same "
                          "bridge caption.py uses)")
    fil.add_argument("--filler-list", action="store_true",
                     help="report what --filler would remove and write nothing")
    fil.add_argument("--max-cuts", type=int, default=400,
                     help="refuse above this many removal ranges: the filter graph grows with them "
                          "(default 400)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium", choices=X264_PRESETS)
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

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
    silences = detect(args.input, args.threshold, args.min_silence)
    filler_info, filler_ranges = resolve_filler(args, meta) if args.filler else (None, [])
    # One sorted, merged removal list through the graph the tool already has: filler removal IS
    # time-range removal, so it reuses keep_ranges() and the same aselect/concat chain.
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
    summary = {
        "silences": [[round(s, 3), None if e == float("inf") else round(e, 3)] for s, e in silences],
        "keep": [[round(s, 3), round(e, 3)] for s, e in keeps],
        "input_duration": round(duration, 3),
        "kept_duration": round(kept, 3),
        "removed_seconds": round(silence_only, 3),
    }
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
            info("warning: " + warning)
    if len(keeps) > args.max_cuts:
        die(f"{len(keeps)} keep ranges is above --max-cuts {args.max_cuts}: the filter graph grows "
            "with every range and a graph this size is slow and fragile. Raise --max-cuts if you "
            "mean it, or use --min-silence/--filler-pad to merge the short ones.", kind="input")
    info(f"{len(silences)} silences, keeping {len(keeps)} ranges: {kept:.2f}s of {duration:.2f}s (removing {removed:.2f}s)")
    if not silences and not (STATE.dry_run and not os.path.exists(args.input)):
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

    if args.edl:
        if not STATE.dry_run:  # the EDL is an artifact like the cut itself: a plan writes nothing
            with open(args.edl, "w", encoding="utf-8") as fh:
                for s, e in keeps:
                    fh.write(f"{s:.3f}-{e:.3f}\n")
        info(f"wrote {args.edl}")

    if args.list or args.filler_list:
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
    af = f"aselect='{expr}',asetpts=N/SR/TB"
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
    emit(output, **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
