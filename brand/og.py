#!/usr/bin/env python3
"""Draw the social card (brand/og.png, copied to site/brand/og.png) with ffmpeg.

The card states how many tools there are and how many are stable. Those two numbers are read from
the contract, never typed here, and the line that carries them is written into the PNG as a tEXt
chunk (keyword `ffmpeg-skill:text`), so a test can compare the picture's words with the contract
without reading pixels (tests/test_contract.py, `test_the_social_card_says_the_contracts_tool_count`).
When the count changes, that test fails until the card is drawn again:

    python3 brand/og.py            # draw both copies from the contract
    python3 brand/og.py --check    # exit 1 when the card's text is not the contract's

Drawing needs ffmpeg with drawtext and the Inter and JetBrains Mono fonts (found with fc-match;
--fonts DIR takes them from a folder instead). The pixels depend on the font files and the FFmpeg
build, so two machines can draw slightly different cards; the text chunk is what is compared.
The card before this script existed was drawn by hand; this one reproduces its layout.
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "og.png"
COPIES = (ROOT / "site" / "brand" / "og.png",)
KEY = b"ffmpeg-skill:text"
W, H = 1280, 640
BASE = (12, 12, 16)
# three soft lights over the base: centre, spread (x, y) and colour at the centre
LIGHTS = (((1250, -30), (280, 200), (26, 215, 116)),
          ((970, 680), (230, 150), (40, 105, 240)),
          ((-40, 690), (200, 200), (55, 30, 105)))
FONTS = {"display": "Inter Display:style=Black", "bold": "Inter:style=Bold", "medium": "Inter:style=Medium",
         "semibold": "Inter:style=SemiBold", "mono": "JetBrains Mono:style=Regular", "mono_bold": "JetBrains Mono:style=Bold"}
ROWS = (("duration", "59.98 s"), ("size", "1080×1920"), ("frame rate", "30 fps"), ("loudness", "-14.0 LUFS"))


def counts():
    """(tools, stable) as the contract lists them: an alias of another tool is not a tool of its own."""
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "_contract.py"), "--json", "--static"],
                          capture_output=True, text=True, encoding="utf-8", check=True)
    tools = [t for t in json.loads(proc.stdout)["tools"] if "alias_of" not in t]
    return len(tools), sum(1 for t in tools if t.get("stability") == "stable")


def card_text():
    n, stable = counts()
    return f"{n} local FFmpeg tools · {stable} stable · your agent does the work"


def chunks(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    at = 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        yield at, kind, data[at + 8:at + 8 + length]
        at += 12 + length


def read_text(path):
    """The card's text as its tEXt chunk records it, or None when it records none."""
    for _, kind, body in chunks(Path(path).read_bytes()):
        if kind == b"tEXt" and body.split(b"\0", 1)[0] == KEY:
            return body.split(b"\0", 1)[1].decode("latin-1")
    return None


def write_text(path, text):
    """Record `text` in the PNG (replacing an earlier record) without touching its pixels."""
    data = Path(path).read_bytes()
    kept = b"".join(data[at:at + 12 + len(body)] for at, kind, body in chunks(data)
                    if kind != b"IEND" and not (kind == b"tEXt" and body.split(b"\0", 1)[0] == KEY))
    body = KEY + b"\0" + text.encode("latin-1")
    record = struct.pack(">I", len(body)) + b"tEXt" + body + struct.pack(">I", zlib.crc32(b"tEXt" + body))
    Path(path).write_bytes(data[:8] + kept + record + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def font_files(folder):
    """Each face's file: from --fonts DIR by file name, else fc-match. None when one is missing."""
    found = {}
    for role, pattern in FONTS.items():
        family, style = pattern.split(":style=")
        if folder:
            hits = sorted(Path(folder).glob(f"{family.replace(' ', '')}-{style}.*"))
            found[role] = str(hits[0]) if hits else None
        elif shutil.which("fc-match"):
            proc = subprocess.run(["fc-match", "-f", "%{family}\n%{style}\n%{file}", pattern], capture_output=True, text=True, encoding="utf-8")
            lines = proc.stdout.split("\n")
            # fc-match always answers with some font; only the face asked for counts
            found[role] = lines[2] if len(lines) == 3 and family in lines[0].split(",") and style in lines[1].split(",") else None
        else:
            found[role] = None
    return found if all(found.values()) else None


def esc(text):
    """A value for drawtext's text= inside a filter graph."""
    return text.replace("\\", "\\\\\\\\").replace("'", "'\\\\\\''").replace(":", "\\\\:").replace("%", "\\\\%").replace(",", "\\,")


def text(face, words, x, y, size, color, extra=""):
    return f"drawtext=fontfile='{face}':text='{esc(words)}':x={x}:y={y}:fontsize={size}:fontcolor={color}{extra}"


def inset(w, h, r):
    """A geq prefix leaving in register 2 how far (X, Y) is inside a w x h rectangle whose corners have
    radius r (negative outside). Each plane's expression has its own registers, so each repeats it."""
    return (f"st(0,max(max({r}-X,X-{w - 1 - r}),0));st(1,max(max({r}-Y,Y-{h - 1 - r}),0));"
            f"st(2,if(gt(ld(0),0)*gt(ld(1),0),{r}-hypot(ld(0),ld(1)),min(min(X,{w - 1}-X),min(Y,{h - 1}-Y))))")


# the card and the two pills: (name, size, radius, fill colour and alpha, edge colour and alpha, where)
SHAPES = (("card", (429, 303), 22, (255, 255, 255, 20), (255, 255, 255, 34), (787, 118)),
          ("pill", (116, 37), 18, (23, 209, 106, 255), (23, 209, 106, 255), (815, 358)),
          ("cmd", (297, 48), 10, (8, 16, 40, 150), (55, 75, 124, 255), (919, 507)))


def graph(f, line):
    light = lambda c: "+".join(f"{col[c] - BASE[c]}*exp(-(pow((X-{x})/{sx},2)+pow((Y-{y})/{sy},2)))"
                               for (x, y), (sx, sy), col in LIGHTS)
    steps = [f"color=c=black:s={W}x{H}:d=1,format=gbrp,"
             f"geq=r='{BASE[0]}+{light(0)}':g='{BASE[1]}+{light(1)}':b='{BASE[2]}+{light(2)}',"
             # v4, an outline behind the card: the border is the line, the fill the ground it stands on
             + text(f["display"], "v4", 465, "220-ascent", 300, "0x0c0c10", ":borderw=2:bordercolor=0x333336") + ",format=rgba[l0]"]
    for i, (name, (w, h), r, fill, edge, (x, y)) in enumerate(SHAPES):
        pre = inset(w, h, r)
        plane = lambda c: f"{pre};if(lt(ld(2),1),{edge[c]},{fill[c]})"
        alpha = f"{pre};if(lt(ld(2),-1),0,if(lt(ld(2),0),{edge[3]}*(ld(2)+1),if(lt(ld(2),1),{edge[3]},{fill[3]})))"
        steps.append(f"color=c=black:s={w}x{h}:d=1,format=rgba,geq=r='{plane(0)}':g='{plane(1)}':b='{plane(2)}':a='{alpha}'[{name}]")
        steps.append(f"[l{i}][{name}]overlay={x}:{y}[l{i + 1}]")
    draw = [
        # the logo: a bracket, a filled half, a bar and a green dot (the symbol, at 28 px)
        "drawbox=x=64:y=72:w=13:h=2:c=white:t=fill", "drawbox=x=64:y=93:w=13:h=2:c=white:t=fill",
        "drawbox=x=64:y=72:w=2:h=23:c=white:t=fill", "drawbox=x=80:y=72:w=13:h=23:c=white:t=fill",
        "drawbox=x=77:y=71:w=2:h=25:c=0xb4b4b8:t=fill", "drawbox=x=75:y=80:w=6:h=7:c=0x0c0c10:t=fill",
        "drawbox=x=76:y=81:w=4:h=5:c=0x17d16a:t=fill",
        text(f["semibold"], "ffmpeg-skill", 97, "89-ascent", 17, "white"),
        text(f["display"], "Edit. Measure.", 62, "403-ascent", 84, "white"),
        text(f["display"], "Ship.", 62, "480-ascent", 84, "white"),
        text(f["medium"], line, 66, "552-ascent", 20, "0xc7ccd4"),
        text(f["bold"], "FINAL.MP4 · MEASURED", 815, "157-ascent", 12, "0x7e848c"),
        text(f["bold"], "● VERIFIED", 829, "382-ascent", 15, "0x0c0c10"),
        text(f["mono_bold"], "$", 937, "538-ascent", 18, "0x17d16a"),
        text(f["mono_bold"], "npx ffmpeg-skill setup", 960, "538-ascent", 18, "white"),
    ]
    for i, (label, value) in enumerate(ROWS):
        y = 187 + 44 * i
        draw.append(text(f["mono"], label, 815, f"{y + 6}-ascent", 16, "0xc8cdd2"))
        draw.append(text(f["mono_bold"], value, "1187-tw", f"{y + 6}-ascent", 16, "white"))
        draw.append(f"drawbox=x=815:y={y + 22}:w=372:h=1:c=white@0.10:t=fill")
    steps.append(f"[l{len(SHAPES)}]format=rgb24," + ",".join(draw) + "[out]")
    return ";".join(steps)


def render(out, line, fonts):
    with tempfile.TemporaryDirectory() as tmp:
        drawn = Path(tmp) / "og.png"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-filter_complex", graph(fonts, line),
                        "-map", "[out]", "-frames:v", "1", str(drawn)], check=True)
        write_text(drawn, line)
        for path in (out, *(COPIES if out == OUT else ())):
            shutil.copyfile(drawn, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT, help="where to draw the card (default brand/og.png, and site/brand/og.png beside it)")
    ap.add_argument("--fonts", help="a folder holding InterDisplay-Black, Inter-Bold/-Medium/-SemiBold and JetBrainsMono-Regular/-Bold")
    ap.add_argument("--check", action="store_true", help="draw nothing: exit 1 when a card's recorded text is not the contract's")
    args = ap.parse_args()
    line = card_text()
    if args.check:
        stale = [(p, read_text(p)) for p in (OUT, *COPIES) if read_text(p) != line]
        for path, said in stale:
            print(f"{path.relative_to(ROOT)} says {said!r}; the contract says {line!r}: run python3 brand/og.py", file=sys.stderr)
        return 1 if stale else 0
    fonts = font_files(args.fonts)
    if not fonts:
        print("the Inter and JetBrains Mono fonts were not found (fc-match, or --fonts DIR)", file=sys.stderr)
        return 1
    render(args.out.resolve(), line, fonts)
    print(f"{args.out}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
