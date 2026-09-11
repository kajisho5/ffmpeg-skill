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

from _common import add_common, apply_common, default_output, die, emit, ffmpeg_base, info, parse_time, probe, run, STATE

CHAPTER_CONTAINERS = {".mp4", ".m4v", ".m4a", ".mov", ".mkv", ".mka", ".webm"}
TAG_KEYS = ("title", "artist", "album", "comment", "date", "genre")


def parse_chapters(path: str, duration: float) -> List[Dict[str, Any]]:
    """`TIME TITLE` per line -> [{"start", "end", "title"}], validated: ascending starts, every
    start inside the file, the last chapter running to the file's end."""
    text = Path(path).read_text(encoding="utf-8")
    entries: List[Dict[str, Any]] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        try:
            start = parse_time(parts[0])
        except ValueError:
            die(f"{path}:{n}: cannot read the time in {line!r} (use seconds, mm:ss or hh:mm:ss.ms)")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output file (default: <name>_meta.<ext>)")
    ap.add_argument("--chapters", help="text file, one chapter per line: `TIME TITLE` (cut.py time syntax)")
    ap.add_argument("--clear-chapters", action="store_true", help="remove every chapter marker the input carries")
    for key in TAG_KEYS:
        ap.add_argument(f"--{key}", help=f"set the container's {key} tag (empty string clears it)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if args.chapters and args.clear_chapters:
        die("--chapters and --clear-chapters exclude each other")
    tags = {k: getattr(args, k) for k in TAG_KEYS if getattr(args, k) is not None}
    if not args.chapters and not args.clear_chapters and not tags:
        die("nothing to write: give --chapters FILE, --clear-chapters and/or --title/--artist/...")
    if args.chapters and not os.path.exists(args.chapters):
        die(f"chapters file not found: {args.chapters}")

    meta = probe(args.input)
    output = args.output or default_output(args.input, "meta")
    if os.path.abspath(output) == os.path.abspath(args.input):
        die("output must differ from the input (metadata.py never rewrites a file in place)")
    out_ext = Path(output).suffix.lower()
    if (args.chapters or args.clear_chapters) and out_ext not in CHAPTER_CONTAINERS:
        die(f"{out_ext or 'this'} container cannot hold chapter markers; write to one of "
            f"{', '.join(sorted(CHAPTER_CONTAINERS))} (the streams are copied, so choose the matching family: .mp4/.mov/.m4a for MPEG-4, .mkv/.mka/.webm for Matroska)")

    duration = meta.get("duration") or 0.0
    chapters: Optional[List[Dict[str, Any]]] = parse_chapters(args.chapters, duration) if args.chapters else None

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
    if chapters is not None and not STATE["dry_run"] and len(written) != len(chapters):
        die(f"wrote {len(written)} chapters but {len(chapters)} were asked for", kind="output")
    if args.clear_chapters and not STATE["dry_run"] and written:
        die(f"{len(written)} chapters survived --clear-chapters", kind="output")
    info(f"wrote {output} ({len(written)} chapters, tags: {', '.join(sorted(tags)) or 'unchanged'}, streams copied)")
    emit(output, chapters=written, tags=result.get("tags") or {}, streams_copied=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
