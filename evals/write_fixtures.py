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
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(outdir: Path, prompt: dict) -> list:
    written = []
    for name, text in (prompt.get("fixtures") or {}).items():
        if "/" in name or "\\" in name or name.startswith("."):
            raise SystemExit(f"fixture name must be a plain file name: {name!r}")
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / name
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
    return written


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
