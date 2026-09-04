#!/usr/bin/env python3
"""Burn SRT/ASS subtitles into a video, or generate an SRT from plain text.

Styling (font, size, colour, outline, position) applies to SRT input via
libass force_style. ASS files carry their own styles and are rendered as-is.

Text-to-SRT input format (one cue per line, blank lines ignored):
  0:00-0:03 Hello and welcome
  00:00:03.500 --> 00:00:06 Second line | with a manual line break
  Text without a time is auto-timed after the previous cue (--auto-seconds)

Examples:
  python3 caption.py input.mp4 --srt subs.srt
  python3 caption.py input.mp4 --text cues.txt --animate pop --karaoke        # word-by-word highlight, TikTok style
  python3 caption.py input.mp4 --srt subs.srt --font "Noto Sans CJK JP" --size 28 --position top
  python3 caption.py --text cues.txt --write-srt cues.srt          # only produce the SRT
  python3 caption.py input.mp4 --text cues.txt                     # generate + burn in one go
"""
import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from _common import STATE, color_hex, load_brand, video_args, add_common, apply_common, emit, aac_args, cfr_args, default_output, die, escape_filter_path, ffmpeg_base, fmt_srt_time, info, parse_time, probe, run, x264_args

ALIGN = {"bottom": 2, "top": 8, "center": 5, "bottom-left": 1, "bottom-right": 3, "top-left": 7, "top-right": 9}

TIME_RE = re.compile(
    r"^\s*(?P<a>[\d:.,]+)\s*(?:-->|-|–|to)\s*(?P<b>[\d:.,]+)\s+(?P<text>.+)$"
)


def parse_text_cues(path: str, auto_seconds: float, gap: float) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    cursor = 0.0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            m = TIME_RE.match(line)
            if m:
                try:
                    start, end = parse_time(m.group("a")), parse_time(m.group("b"))
                except ValueError:
                    start, end, text = cursor, cursor + auto_seconds, line.strip()
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


def transcribe(video: str, out_srt: str, language: Optional[str], model: str) -> List[Tuple[float, float, str]]:
    """Optional local ASR bridge. Tries, in order: whisper-cli / main (whisper.cpp), faster-whisper (python),
    whisper (openai-whisper CLI). Produces an SRT with word timings where the engine supports it.
    No engine installed -> clear error with install hints; the skill never depends on one."""
    import shutil
    import subprocess
    import tempfile
    from _common import require_tool
    ffmpeg = require_tool("ffmpeg")
    tmpdir = tempfile.mkdtemp(prefix="ffskill_asr_")
    wav = os.path.join(tmpdir, "audio.wav")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav], check=True)
    # 1. whisper.cpp
    cli = shutil.which("whisper-cli") or shutil.which("whisper-cpp") or shutil.which("main")
    if cli and (shutil.which("whisper-cli") or shutil.which("whisper-cpp")):
        model_path = model
        if not os.path.exists(model_path):
            for cand in (os.path.expanduser(f"~/.cache/whisper.cpp/ggml-{model}.bin"), f"models/ggml-{model}.bin", f"/usr/local/share/whisper/ggml-{model}.bin"):
                if os.path.exists(cand):
                    model_path = cand
                    break
        base = os.path.join(tmpdir, "out")
        cmd = [cli, "-m", model_path, "-f", wav, "-osrt", "-of", base]
        if language:
            cmd += ["-l", language]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and os.path.exists(base + ".srt"):
            info(f"transcribed with whisper.cpp ({os.path.basename(cli)}, model {os.path.basename(model_path)})")
            cues = parse_srt(base + ".srt")
            write_srt(cues, out_srt)
            return cues
        info("whisper.cpp found but failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
    # 2. faster-whisper (python package)
    try:
        from faster_whisper import WhisperModel  # type: ignore
        m = WhisperModel(model, device="cpu", compute_type="int8")
        segments, _ = m.transcribe(wav, language=language, word_timestamps=False)
        cues = [(seg.start, seg.end, seg.text.strip()) for seg in segments if seg.text.strip()]
        if cues:
            info("transcribed with faster-whisper")
            write_srt(cues, out_srt)
            return cues
    except ImportError:
        pass
    # 3. openai-whisper CLI
    if shutil.which("whisper"):
        cmd = ["whisper", wav, "--model", model, "--output_format", "srt", "--output_dir", tmpdir]
        if language:
            cmd += ["--language", language]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        srt = os.path.join(tmpdir, "audio.srt")
        if proc.returncode == 0 and os.path.exists(srt):
            info("transcribed with openai-whisper")
            cues = parse_srt(srt)
            write_srt(cues, out_srt)
            return cues
    die("no local speech-to-text engine found for --transcribe.\n"
        "Install one (all run offline):\n"
        "  whisper.cpp:    brew install whisper-cpp   (then download a model: ggml-base.bin)\n"
        "  faster-whisper: pip install faster-whisper\n"
        "  openai-whisper: pip install openai-whisper\n"
        "Or write the cues by hand with --text cues.txt (see format above).")
    return []


def parse_srt(path: str) -> List[Tuple[float, float, str]]:
    cues: List[Tuple[float, float, str]] = []
    block: List[str] = []
    with open(path, encoding="utf-8-sig") as fh:
        content = fh.read().replace("\r\n", "\n") + "\n\n"
    for line in content.split("\n"):
        if line.strip():
            block.append(line)
            continue
        if block:
            times = next((b for b in block if "-->" in b), None)
            if times:
                a, b = times.split("-->")
                text = "\n".join(block[block.index(times) + 1:]).strip()
                cues.append((parse_time(a), parse_time(b), text))
            block = []
    if not cues:
        die(f"no cues found in {path}")
    return cues


def write_srt(cues: List[Tuple[float, float, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (s, e, t) in enumerate(cues, 1):
            fh.write(f"{i}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{t}\n\n")


def word_durations_from_audio(video: str, start: float, end: float, n_words: int) -> List[int]:
    """Split a cue's time across n_words in proportion to speech energy (centiseconds each).

    Decodes the cue window to 8 kHz mono, builds a 10 ms RMS envelope, removes the noise floor,
    and cuts at equal cumulative-energy quantiles: pauses get no words, loud stretches get more time.
    Falls back to an even split when the window is silent or too short.
    """
    import struct
    import subprocess as sp
    from _common import require_tool
    total_cs = max(1, int(round((end - start) * 100)))
    if n_words <= 1:
        return [total_cs]
    ffmpeg = require_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", video,
           "-t", f"{end - start:.3f}", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    proc = sp.run(cmd, stdout=sp.PIPE, stderr=sp.PIPE)
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
    # normalise to the exact cue length
    scale = total_cs / max(1, sum(out))
    out = [max(5, int(round(x * scale))) for x in out]
    out[-1] += total_cs - sum(out)
    return out


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
    margin = int(round(args.margin * scale))
    # karaoke: PrimaryColour is the "sung" colour, SecondaryColour the "not yet sung" one
    primary = ass_color(args.highlight_color if args.karaoke else args.color)
    secondary = ass_color(args.color)
    outline = ass_color(args.outline_color)
    back = ass_color(args.outline_color, 0x80)
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {play_w}", f"PlayResY: {play_h}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{args.font},{size},{primary},{secondary},{outline},{back},{-1 if args.bold else 0},0,0,0,100,100,0,0,{3 if args.box else 1},{args.outline * scale:.1f},{args.shadow * scale:.1f},{ALIGN[args.position]},{margin},{margin},{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = []
    for start, end, text in cues:
        text = text.replace("\n", "\\N")
        fx = ""
        if args.animate == "fade":
            fx = "{\\fad(200,200)}"
        elif args.animate == "pop":
            fx = "{\\fad(80,120)\\fscx60\\fscy60\\t(0,120,\\fscx110\\fscy110)\\t(120,200,\\fscx100\\fscy100)}"
        elif args.animate == "slide":
            fx = "{\\fad(150,150)\\move(%d,%d,%d,%d,0,250)}" % (play_w // 2, play_h - margin + int(30 * scale), play_w // 2, play_h - margin)
        body = text
        if args.karaoke:
            # split each line into words and give every word an equal share of the cue (\k is in centiseconds)
            dur_cs = max(1, int(round((end - start) * 100)))
            segments = body.split("\\N")
            words = [w for seg in segments for w in seg.split(" ") if w]
            if getattr(args, "karaoke_timing", "even") == "energy" and video:
                durs = word_durations_from_audio(video, start, end, len(words))
            else:
                per = max(1, dur_cs // max(1, len(words)))
                durs = [per] * len(words)
            it = iter(durs)
            out_segments = []
            for seg in segments:
                ws = [w for w in seg.split(" ") if w]
                out_segments.append(" ".join(f"{{\\kf{next(it)}}}{w}" for w in ws))
            body = "\\N".join(out_segments)
        lines.append(f"Dialogue: 0,{t(start)},{t(end)},Default,,0,0,0,,{fx}{body}")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write("\n".join(header + lines) + "\n")


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        die(f"colour must be RRGGBB hex, got '{hex_rgb}'")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="video to burn captions into (omit with --write-srt to only generate)")
    ap.add_argument("-o", "--output", help="output video (default: <name>_captioned.<ext>)")
    src = ap.add_argument_group("subtitle source")
    src.add_argument("--srt", help="SRT file to burn")
    src.add_argument("--ass", help="ASS file to burn (styles inside the file are used)")
    src.add_argument("--text", help="plain text cue file to convert into SRT (see format above)")
    src.add_argument("--transcribe", action="store_true", help="generate the SRT from the audio with a local speech-to-text engine if one is installed (whisper-cli / whisper / faster-whisper); never required")
    src.add_argument("--language", help="language code for --transcribe (e.g. en, ja); default auto")
    src.add_argument("--model", default="base", help="whisper model name/path for --transcribe (default base)")
    src.add_argument("--write-srt", help="where to save the generated SRT (default: <text>.srt)")
    src.add_argument("--auto-seconds", type=float, default=3.0, help="duration for cues without timing (default 3)")
    src.add_argument("--gap", type=float, default=0.0, help="gap after auto-timed cues in seconds")
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
    sty.add_argument("--margin", type=int, default=30, help="vertical margin from the edge (default 30)")
    sty.add_argument("--box", action="store_true", help="draw an opaque box behind text instead of an outline")
    anim = ap.add_argument_group("animation (generates ASS; needs --text or --srt input)")
    anim.add_argument("--animate", choices=["none", "fade", "pop", "slide"], default=None, help="per-cue entrance animation (default none, or brand caption.animate)")
    anim.add_argument("--karaoke", action="store_true", help="word-by-word highlight (fills from --color to --highlight-color across each cue)")
    anim.add_argument("--highlight-color", default=None, help="karaoke fill colour RRGGBB (default FFD200 or brand primary)")
    anim.add_argument("--karaoke-timing", choices=["even", "energy"], default="energy",
                      help="how words are timed inside a cue: 'energy' follows the speech loudness in the audio (default), 'even' splits time equally")
    anim.add_argument("--write-ass", help="where to save the generated ASS (default: next to the output)")
    enc = ap.add_argument_group("encoding")
    enc.add_argument("--crf", type=int, default=18)
    enc.add_argument("--preset", default="medium")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    brand = load_brand(args.brand)
    bc, bcap = brand["colors"], brand["caption"]
    args.font = args.font or brand.get("font") or "DejaVu Sans"
    args.size = args.size if args.size is not None else (bcap.get("size", 24) if args.brand else 24)
    args.color = color_hex(args.color or bc.get("text", "FFFFFF"))
    args.outline_color = color_hex(args.outline_color or bc.get("outline", "000000"))
    args.outline = args.outline if args.outline is not None else (float(bcap.get("outline", 2)) if args.brand else 2.0)
    args.position = args.position or (bcap.get("position", "bottom") if args.brand else "bottom")
    args.animate = args.animate or (bcap.get("animate", "none") if args.brand else "none")
    args.highlight_color = color_hex(args.highlight_color or bc.get("primary", "FFD200"))
    if args.brand and bcap.get("bold") and not args.bold:
        args.bold = True
    if args.brand and bcap.get("karaoke") and not args.karaoke:
        args.karaoke = True
    if args.brand and brand.get("font_file") and not args.fonts_dir:
        args.fonts_dir = str(Path(brand["font_file"]).parent)
    if not (args.srt or args.ass or args.text or args.transcribe):
        die("give one of --srt, --ass, --text or --transcribe")

    srt_path = args.srt
    if args.transcribe:
        if not args.input:
            die("--transcribe needs the input video")
        srt_path = args.write_srt or os.path.splitext(args.input)[0] + ".srt"
        cues = transcribe(args.input, srt_path, args.language, args.model)
        info(f"wrote {srt_path} ({len(cues)} cues)")
        args.text = None
    if args.text:
        cues = parse_text_cues(args.text, args.auto_seconds, args.gap)
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
        info(f"wrote {srt_path} ({len(cues)} cues)")
        if not args.input:
            print(srt_path)
            return 0

    if not args.input:
        die("input video is required unless you only use --text/--write-srt")
    meta = probe(args.input)
    if not meta.get("video"):
        die("input has no video stream")

    output = args.output or default_output(args.input, "captioned")
    if (args.animate != "none" or args.karaoke) and not args.ass:
        cues_for_ass = cues if args.text else parse_srt(srt_path)
        ass_path = args.write_ass or os.path.splitext(output)[0] + ".ass"
        w, h = meta["video"]["width"], meta["video"]["height"]
        if meta["video"].get("rotation") in (90, -90, 270, -270):
            w, h = h, w
        write_ass(cues_for_ass, ass_path, args, w, h, video=args.input if meta.get("audio") else None)
        info(f"wrote {ass_path} ({len(cues_for_ass)} cues, animate={args.animate}, karaoke={args.karaoke})")
        args.ass = ass_path

    if args.ass:
        if not os.path.exists(args.ass):
            die(f"ASS file not found: {args.ass}")
        vf = f"ass={escape_filter_path(args.ass)}"
        if args.fonts_dir:
            vf += f":fontsdir={escape_filter_path(args.fonts_dir)}"
    else:
        if not srt_path or (not os.path.exists(srt_path) and not (STATE.dry_run and args.text)):
            die(f"SRT file not found: {srt_path}")
        style = [
            f"FontName={args.font}",
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

    cmd = ffmpeg_base() + ["-i", args.input, "-vf", vf] + video_args(meta, args.crf, args.preset) + cfr_args(meta)
    cmd += (aac_args() if meta.get("audio") else ["-an"]) + [output]
    run(cmd)
    result = probe(output)
    info(f"wrote {output} ({result.get('duration'):.3f}s)")
    emit(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
