#!/usr/bin/env python3
"""Write a prompt's "fixtures" files into its OUTDIR before the agent runs.

    python3 evals/write_fixtures.py OUTDIR PROMPT_ID [PROMPTS_JSON]   # one prompt
    python3 evals/write_fixtures.py ITERATION_DIR --all [PROMPTS_JSON] # every prompt, into ITERATION_DIR/<id>/

A prompt in agent_prompts_24.json may carry {"fixtures": {"cues_zh.txt": "..."}}. Those files are
text the prompt refers to (cue files in the prompt's language); they are written by the harness,
never committed, so the repo stays free of generated media and generated fixtures. Existing files
are overwritten. Prompts without a "fixtures" key write nothing.
"""
import json
import ntpath
import os
import posixpath
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def absolute_output_dir(text: str, name: str, outdir: Path) -> str:
    """A batch recipe's "output_dir" is resolved against the CALLER's cwd, not against the folder
    of inputs, so a relative "out" in a staged fixture wrote somewhere the run never looked and
    the agent had to rewrite the recipe (eval 18 bp1/bp2). Stage it absolute, under OUTDIR.
    """
    if not name.endswith(".json"):
        return text
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    if not isinstance(doc, dict) or not isinstance(doc.get("output_dir"), str):
        return text
    # ntpath/posixpath rather than Path: on Windows `Path("/srv/out").is_absolute()` is False, so
    # a posix-absolute output_dir would be rewritten under OUTDIR there (review 17 finding 9).
    stated = os.path.normpath(doc["output_dir"]).replace("\\", "/")
    if posixpath.isabs(stated) or ntpath.isabs(doc["output_dir"]):
        return text
    doc["output_dir"] = str((outdir / doc["output_dir"]).resolve())
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def write(outdir: Path, prompt: dict) -> list:
    written = []
    for name, text in (prompt.get("fixtures") or {}).items():
        if "/" in name or "\\" in name or name.startswith("."):
            raise SystemExit(f"fixture name must be a plain file name: {name!r}")
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / name
        text = absolute_output_dir(text, name, outdir)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    # 1.15: a prompt may ask for a directory of emoji PNGs. The repo ships NO emoji art -- Twemoji
    # is CC-BY 4.0 and Noto Emoji OFL/Apache-2.0 -- so the placeholders are DRAWN here with ffmpeg
    # under the file names --emoji-assets actually requires (lowercase hex code points joined by
    # '-'). The naming convention is what the run has to get right; the glyph is not.
    names = prompt.get("emoji_assets") or []
    if names:
        import subprocess
        assets = outdir / "emoji"
        assets.mkdir(parents=True, exist_ok=True)
        palette = ("orange", "gold", "tomato", "limegreen", "deepskyblue")
        for i, name in enumerate(names):
            target = assets / (name + ".png")
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", "color=c=%s:s=72x72:d=0.04" % palette[i % len(palette)],
                            "-vf", "format=rgba", "-frames:v", "1", str(target)], check=True)
            written.append(target)
    for name in prompt.get("media_fixtures") or []:
        target = outdir / name
        if not target.exists():
            outdir.mkdir(parents=True, exist_ok=True)
            build_media_fixture(name, target)
        written.append(target)
    return written


def build_media_fixture(name: str, target: Path) -> None:
    """Synthetic media eval 22's Set B prompts need, ffmpeg-generated on demand (never
    committed) so the repo stays free of generated media. Ground truth for each file is
    documented next to its build here, and was verified against the tool it exercises
    (scenes.py --shots, silence.py --speech-aware, sync.py, multicam.py --switch energy)
    when these prompts were staged as scratchpad/eval22."""
    import subprocess

    def ffmpeg(*args):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *[str(a) for a in args]], check=True)

    if name == "shots.mp4":
        # 0-4s locked-off (static, a Life pattern with no camera motion); 4-8s a crop window
        # sliding across a wide testsrc (measured scenes.py --shots label: "motion"); 8-12s a
        # box crossing an otherwise static frame (measured label: "pan"). The labels below are
        # what scenes.py's flow-based classifier actually returns for this synthetic footage --
        # verified once with scenes.py --shots --json against this exact build -- not a semantic
        # guess about which construction "should" read as camera motion vs in-frame motion.
        ffmpeg("-f", "lavfi", "-i",
               "life=size=80x45:rate=30:mold=32:ratio=0.1:death_color=#101030:life_color=#39ff88:seed=1",
               "-t", "4", "-vf", "scale=640:360:flags=neighbor", target.parent / "_shots_a.mp4")
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
               "-t", "4", "-vf", "crop=640:360:'80*t':0", target.parent / "_shots_b.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=0x101832:s=640x360:rate=30",
               "-f", "lavfi", "-i", "color=c=0xffcc00:s=80x80:rate=30",
               "-filter_complex", "[0:v][1:v]overlay=x='(640-80)*t/4':y=140", "-t", "4",
               target.parent / "_shots_c.mp4")
        list_file = target.parent / "_shots_concat.txt"
        list_file.write_text("\n".join(f"file '{target.parent / n}'" for n in
                                       ("_shots_a.mp4", "_shots_b.mp4", "_shots_c.mp4")) + "\n",
                             encoding="utf-8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", list_file, "-c:v", "libx264",
               "-preset", "ultrafast", "-pix_fmt", "yuv420p", target)
        for n in ("_shots_a.mp4", "_shots_b.mp4", "_shots_c.mp4"):
            (target.parent / n).unlink(missing_ok=True)
        list_file.unlink(missing_ok=True)
    elif name == "speech_breaths.m4a":
        # 11.0s: speech bursts with three 0.30s in-sentence breaths (1.2-1.5, 2.6-2.9, 6.7-7.0)
        # and two 1.50s sentence-boundary pauses (4.0-5.5, 8.2-9.7). silence.py --speech-aware
        # keeps the three breaths (0.90s) and cuts only the two pauses (8.60s of 11.00s kept).
        expr = ("0.5*sin(2*PI*180*t)*(lt(t\\,1.2)+between(t\\,1.5\\,2.6)+between(t\\,2.9\\,4.0)"
                "+between(t\\,5.5\\,6.7)+between(t\\,7.0\\,8.2)+gt(t\\,9.7))")
        ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000", "-t", "11", "-c:a", "aac", target)
    elif name in ("camA.mp4", "camB.mp4"):
        # Two cameras on one reference timeline: camA loud 0-6s / quiet 6-12s, camB the reverse
        # -- multicam.py --switch energy should pick camA for the first half, camB the second.
        # Same construction as tests/test_orchestration.py's own _loud_cams().
        loud_first = name == "camA.mp4"
        hue = "" if loud_first else ",hue=h=90"
        vol_expr = ("0.8*sin(2*PI*440*t)*lt(t\\,6)+0.01*sin(2*PI*440*t)*gt(t\\,6)" if loud_first else
                   "0.01*sin(2*PI*440*t)*lt(t\\,6)+0.8*sin(2*PI*440*t)*gt(t\\,6)")
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=160x90:rate=30{hue}",
               "-f", "lavfi", "-i", f"aevalsrc='{vol_expr}':s=48000",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", target)
    elif name == "lav.m4a":
        # camA's audio (loud 0-6s / quiet 6-12s tone) delayed 2.500s -- sync ground truth -2.500s.
        vol_expr = "0.8*sin(2*PI*440*t)*lt(t\\,6)+0.01*sin(2*PI*440*t)*gt(t\\,6)"
        ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{vol_expr}':s=48000", "-t", "9.5",
               "-af", "adelay=2500|2500", "-c:a", "aac", target)
    elif name == "cam3.m4a":
        # camA's audio advanced 1.180s -- sync ground truth +1.18s.
        vol_expr = "0.8*sin(2*PI*440*(t+1.18))*lt(t+1.18\\,6)+0.01*sin(2*PI*440*(t+1.18))*gt(t+1.18\\,6)"
        ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{vol_expr}':s=48000", "-t", "10.82", "-c:a", "aac", target)
    else:
        raise SystemExit(f"no media fixture builder for {name!r}")


def main(argv) -> int:
    args = [a for a in argv if a != "--all"]
    every = "--all" in argv
    if not args:
        raise SystemExit(__doc__)
    root = Path(args[0])
    if every:
        prompts_json = Path(args[1]) if len(args) > 1 else HERE / "agent_prompts_24.json"
        prompts = json.loads(prompts_json.read_text(encoding="utf-8"))
        for p in prompts:
            for f in write(root / p["id"], p):
                print(f)
        return 0
    if len(args) < 2:
        raise SystemExit(__doc__)
    prompts_json = Path(args[2]) if len(args) > 2 else HERE / "agent_prompts_24.json"
    prompts = {p["id"]: p for p in json.loads(prompts_json.read_text(encoding="utf-8"))}
    if args[1] not in prompts:
        raise SystemExit(f"no prompt {args[1]} in {prompts_json}")
    for f in write(root, prompts[args[1]]):
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
