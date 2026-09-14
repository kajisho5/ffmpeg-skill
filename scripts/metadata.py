#!/usr/bin/env python3
"""Write container chapters and title/artist/comment tags without touching the streams.

Chapter markers are what YouTube, VLC, Apple Podcasts and MKV players show as a
seekable list; graphics.py --template chapter burns a *card* into the picture, this
writes the *metadata*. Every stream is copied bit for bit (-c copy): the only thing
that changes is the container's metadata, so this is instant and lossless.

Chapters come from a text file, one per line, `TIME TITLE` with the same time syntax
as cut.py (seconds, mm:ss, hh:mm:ss.ms). Each chapter ends where the next starts; the
last one ends at the file's duration. Containers with no chapter support (.wav, .gif,
.mp3, .flac) are refused for --chapters rather than silently dropping them; tags alone
are written wherever the container can hold them.

Examples:
  python3 metadata.py episode.mp4 --chapters chapters.txt
  python3 metadata.py episode.mp4 --title "Episode 12" --artist "Studio" --comment "final cut"
  python3 metadata.py master.mkv --chapters chapters.txt --title "Master" -o master_tagged.mkv
  python3 metadata.py episode.mp4 --clear-chapters

chapters.txt:
  0:00 Intro
  2:15 Setup
  1:03:00 Outro
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from _common import (add_common, apply_common, default_output, description_block, detect_scenes, detect_silences,
                     die, emit, ffmpeg_base, fmt_chapter_time, info, propose_chapters, time_arg, probe, run,
                     STATE, read_text_or_die)

CHAPTER_CONTAINERS = {".mp4", ".m4v", ".m4a", ".mov", ".mkv", ".mka", ".webm"}
TAG_KEYS = ("title", "artist", "album", "comment", "date", "genre")


def parse_chapters(path: str, duration: float) -> List[Dict[str, Any]]:
    """`TIME TITLE` per line -> [{"start", "end", "title"}], validated: ascending starts, every
    start inside the file, the last chapter running to the file's end."""
    text = read_text_or_die(path, "--chapters")
    entries: List[Dict[str, Any]] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        # chapter files carry no fps, so hh:mm:ss:ff needs its @fps suffix; time_arg() says so
        start = time_arg(parts[0], f"{path}:{n}")
        title = parts[1].strip() if len(parts) > 1 else f"Chapter {len(entries) + 1}"
        if entries and start <= entries[-1]["start"]:
            die(f"{path}:{n}: chapter at {start:g}s does not come after the previous one at {entries[-1]['start']:g}s")
        if duration and start >= duration:
            die(f"{path}:{n}: chapter at {start:g}s starts at or after the end of the file ({duration:.3f}s)")
        entries.append({"start": start, "title": title})
    if not entries:
        die(f"{path}: no chapters found (one per line: `0:00 Intro`)")
    for i, e in enumerate(entries):
        e["end"] = entries[i + 1]["start"] if i + 1 < len(entries) else duration
    return entries


def _ffmeta_escape(value: str) -> str:
    # ffmetadata: backslash escapes =, ;, #, \ and newline
    out = []
    for ch in value:
        if ch in "=;#\\":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\\n")
        else:
            out.append(ch)
    return "".join(out)


def write_ffmetadata(chapters: List[Dict[str, Any]], path: str) -> None:
    lines = [";FFMETADATA1"]
    for c in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(round(c['start'] * 1000))}",
                  f"END={int(round(c['end'] * 1000))}", f"title={_ffmeta_escape(c['title'])}"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def propose(args, meta: Dict[str, Any], duration: float,
            notes: List[str]) -> "tuple":
    """--auto-chapters: measure the structure, then hand it to the pure proposer.

    The detectors are the ones silence.py and scenes.py run (they live in _common/probe.py since
    1.16 so that no tool has to import another tool); the decision is propose_chapters(), which
    is pure and never looks at content.
    """
    source = args.detect_from
    if not meta.get("audio") and source in ("silence", "both"):
        if source == "silence":
            die("--from silence needs an input with an audio stream; use --from scenes", kind="input")
        source = "scenes"
        notes.append("no audio stream: the markers come from scene changes alone (--from scenes)")
    if not meta.get("video") and source in ("scenes", "both"):
        if source == "scenes":
            die("--from scenes needs an input with a video stream; use --from silence", kind="input")
        source = "silence"
        notes.append("no video stream: the markers come from the pauses alone (--from silence)")
    silences = detect_silences(args.input, args.silence_threshold, args.silence_min) \
        if source in ("silence", "both") else []
    cuts = detect_scenes(args.input, args.scene_threshold, 1.0, duration) \
        if source in ("scenes", "both") else []
    if source == "both":
        notes.append("measured in 2 passes (silencedetect and scdet each decode the file once); "
                     "--from silence is the cheap path")
    proposed = propose_chapters(duration, silences, cuts, min_chapter=args.min_chapter,
                                max_chapters=args.max_chapters, source=source)
    if len(proposed) == 1:
        # every suggestion has to be a value the caller is not already using, or the hint reads
        # "try --min-chapter 1" to someone who passed --min-chapter 1
        tries = []
        shorter_silence = round(args.silence_min / 2.0, 2)
        if shorter_silence >= 0.1 and shorter_silence < args.silence_min:
            tries.append(f"--silence-min {shorter_silence:g}")
        shorter_chapter = max(1.0, round(args.min_chapter / 2.0, 2))
        if shorter_chapter < args.min_chapter:
            tries.append(f"--min-chapter {shorter_chapter:g}")
        if args.detect_from != "both" and meta.get("audio") and meta.get("video"):
            tries.append("--from both")
        notes.append(f"no pause longer than {args.silence_min:g}s and no scene change far enough apart "
                     "to start a chapter: the file gets one marker at 0:00"
                     + (". Try " + " or ".join(tries) if tries else
                        ", and the thresholds are already as low as this tool will suggest"))
    total = len([1 for _s in silences]) + len([c for c in cuts if c > 0])
    auto = {
        "source": {"silence": "silence", "scenes": "scenes", "both": "silence+scenes"}[source],
        "min_chapter": float(args.min_chapter),
        "max_chapters": int(args.max_chapters),
        "proposed": total,
        "kept": len(proposed),
        "titles": "placeholder",
        "chapters": proposed,
        "description_block": description_block(proposed),
    }
    entries = [{"start": c["at"], "title": c["title"]} for c in proposed]
    for i, e in enumerate(entries):
        e["end"] = entries[i + 1]["start"] if i + 1 < len(entries) else duration
    info(f"proposed {len(entries)} chapters from {auto['source']} "
         f"(titles are placeholders: Chapter 1..{len(entries)})")
    return entries, auto


def write_proposal(args, chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """--chapters-out / --description-out, the two side files a caller edits and feeds back."""
    files: Dict[str, Any] = {"chapters": None, "description": None}
    if args.chapters_out:
        body = "\n".join(f"{fmt_chapter_time(c['at'])} {c['title']}" for c in chapters) + "\n"
        if STATE.dry_run:
            info(f"[dry-run] would write {args.chapters_out} ({len(chapters)} chapters)")
        else:
            Path(args.chapters_out).write_text(body, encoding="utf-8")
            info(f"wrote {args.chapters_out} ({len(chapters)} chapters)")
        files["chapters"] = args.chapters_out
    if args.description_out:
        body = description_block(chapters) + "\n"
        if STATE.dry_run:
            info(f"[dry-run] would write {args.description_out}")
        else:
            Path(args.description_out).write_text(body, encoding="utf-8")
            info(f"wrote {args.description_out}")
        files["description"] = args.description_out
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_meta.<ext>)")
    ap.add_argument("--chapters", help="text file, one chapter per line: `TIME TITLE` (cut.py time syntax)")
    ap.add_argument("--clear-chapters", action="store_true", help="remove every chapter marker the input carries")
    auto = ap.add_argument_group("proposed chapters (1.16)",
                                 "Chapter timestamps measured from the file's own structure instead of read from a "
                                 "file. The markers are proposed, the titles are not: every one is `Chapter N` and "
                                 "renaming them is the caller's job -- knowing what is said in a chapter is not "
                                 "something this skill can measure. Two detectors mean two full decodes of the "
                                 "input; --from silence is the cheap path.")
    auto.add_argument("--auto-chapters", action="store_true",
                      help="propose the markers from measured pauses and scene changes instead of reading --chapters FILE")
    auto.add_argument("--min-chapter", type=float, default=60.0,
                      help="shortest chapter in seconds (default 60, a long-form default: a 12-minute episode gets at most 12)")
    auto.add_argument("--max-chapters", type=int, default=0,
                      help="cap the number of markers (default 0 = no cap); the weakest evidence is dropped first")
    auto.add_argument("--from", dest="detect_from", choices=["silence", "scenes", "both"], default="both",
                      help="which detector(s) propose the markers (default both)")
    auto.add_argument("--silence-threshold", type=float, default=-35.0,
                      help="silence level in dBFS for --auto-chapters (default -35)")
    auto.add_argument("--silence-min", type=float, default=1.5,
                      help="a pause must last this long to propose a chapter (default 1.5 -- deliberately longer than silence.py's 0.6: a chapter break is a long pause)")
    auto.add_argument("--scene-threshold", type=float, default=8.0,
                      help="minimum scdet score for a scene cut with --auto-chapters (default 8, as scenes.py)")
    auto.add_argument("--chapters-out", help="write the proposal as a `TIME TITLE` file in this tool's own --chapters format, so the titles can be edited and fed back")
    auto.add_argument("--description-out", help="write the YouTube description block (`00:00 Chapter 1` per line)")
    for key in TAG_KEYS:
        ap.add_argument(f"--{key}", help=f"set the container's {key} tag (empty string clears it)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.chapters and args.clear_chapters:
        die("--chapters and --clear-chapters exclude each other")
    if args.auto_chapters and (args.chapters or args.clear_chapters):
        die("--auto-chapters proposes the markers; it excludes --chapters FILE and --clear-chapters")
    if args.min_chapter <= 0:
        die(f"--min-chapter must be > 0, got {args.min_chapter:g}")
    if args.max_chapters < 0:
        die(f"--max-chapters must be >= 0 (0 = no cap), got {args.max_chapters}")
    tags = {k: getattr(args, k) for k in TAG_KEYS if getattr(args, k) is not None}
    if not args.chapters and not args.clear_chapters and not args.auto_chapters and not tags:
        die("nothing to write: give --chapters FILE, --auto-chapters, --clear-chapters and/or --title/--artist/...")
    if args.chapters and not os.path.exists(args.chapters):
        die(f"chapters file not found: {args.chapters}")

    meta = probe(args.input)
    output = args.output or default_output(args.input, "meta")
    if os.path.abspath(output) == os.path.abspath(args.input):
        die("output must differ from the input (metadata.py never rewrites a file in place)")
    out_ext = Path(output).suffix.lower()
    if (args.chapters or args.clear_chapters or args.auto_chapters) and out_ext not in CHAPTER_CONTAINERS:
        die(f"{out_ext or 'this'} container cannot hold chapter markers; write to one of "
            f"{', '.join(sorted(CHAPTER_CONTAINERS))} (the streams are copied, so choose the matching family: .mp4/.mov/.m4a for MPEG-4, .mkv/.mka/.webm for Matroska)")

    duration = meta.get("duration") or 0.0
    chapters: Optional[List[Dict[str, Any]]] = parse_chapters(args.chapters, duration) if args.chapters else None
    auto: Optional[Dict[str, Any]] = None
    notes: List[str] = []
    if args.auto_chapters:
        chapters, auto = propose(args, meta, duration, notes)

    cmd = ffmpeg_base() + ["-i", args.input]
    tmpdir = None
    if chapters:
        tmpdir = tempfile.TemporaryDirectory(prefix="ffskill_meta_")
        ffmeta = os.path.join(tmpdir.name, "chapters.ffmeta")
        write_ffmetadata(chapters, ffmeta)
        cmd += ["-i", ffmeta, "-map", "0", "-map_metadata", "0", "-map_chapters", "1"]
    elif args.clear_chapters:
        cmd += ["-map", "0", "-map_metadata", "0", "-map_chapters", "-1"]
    else:
        cmd += ["-map", "0", "-map_metadata", "0", "-map_chapters", "0"]
    for key, value in tags.items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd += ["-c", "copy", output]
    run(cmd)
    if tmpdir:
        tmpdir.cleanup()

    result = probe(output, role="output")
    written = result.get("chapters") or []
    if chapters is not None and not STATE.dry_run and len(written) != len(chapters):
        die(f"wrote {len(written)} chapters but {len(chapters)} were asked for", kind="output")
    if args.clear_chapters and not STATE.dry_run and written:
        die(f"{len(written)} chapters survived --clear-chapters", kind="output")
    info(f"wrote {output} ({len(written)} chapters, tags: {', '.join(sorted(tags)) or 'unchanged'}, streams copied)")
    extra: Dict[str, Any] = {}
    if auto is not None:
        auto["files"] = write_proposal(args, auto["chapters"])
        extra["auto_chapters"] = auto
    if notes:
        extra["notes"] = notes
    emit(output, chapters=written, tags=result.get("tags") or {}, streams_copied=True, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
