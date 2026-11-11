#!/usr/bin/env python3
"""Write skills/ffmpeg-skill/SKILL.md, the copy of SKILL.md that plugin hosts discover.

Codex and Gemini CLI only find a plugin's skills under `skills/<name>/SKILL.md` (measured:
Codex 0.167 lists nothing for a SKILL.md at the plugin root, whatever the manifest's `skills`
field says; Gemini CLI 0.68 discovers `skills/ffmpeg-skill/SKILL.md` of a linked extension).
Cursor's reference says the same once a `skills/` directory exists. Claude Code loads either and
counts one skill when both are present.

The scripts, references and templates stay at the repository root, which `npx ffmpeg-skill`
copies as one skill directory. So the plugin copy is generated, never edited: the same
frontmatter and body, a note saying where the plugin root is, and every relative path pointed two
directories up.

    python3 .github/scripts/build_plugin_skill.py --write   # regenerate after editing SKILL.md
    python3 .github/scripts/build_plugin_skill.py --check   # exit 1 when it is stale (the test)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "SKILL.md"
TARGET = ROOT / "skills" / "ffmpeg-skill" / "SKILL.md"
UP = "../../"
NOTE = (
    "> Generated from the repository's root `SKILL.md` by `.github/scripts/build_plugin_skill.py`;\n"
    "> edit that file, not this one. In a plugin install this file sits in `skills/ffmpeg-skill/`\n"
    "> and the plugin root is two directories up: `<skill-dir>` below means that root, so the\n"
    "> scripts are at `<this file's directory>/../../scripts/`. Every plain path below\n"
    "> (`references/...`, `docs/...`, `templates/...`, `scripts/...`) is under that root too, not\n"
    "> next to this file.\n"
)
RELATIVE_LINK = re.compile(r"\]\((?!https?://|#|/|\.\./|mailto:)([^)]+)\)")


def build(text: str) -> str:
    if not text.startswith("---\n"):
        raise SystemExit("SKILL.md has no frontmatter")
    end = text.index("\n---\n", 4) + len("\n---\n")
    front, body = text[:end], text[end:]
    body = RELATIVE_LINK.sub(lambda m: f"]({UP}{m.group(1)})", body)
    return front + "\n" + NOTE + body


def main() -> int:
    want = build(SOURCE.read_text(encoding="utf-8"))
    if "--write" in sys.argv:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(want, encoding="utf-8")
        return 0
    have = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if have != want:
        print("skills/ffmpeg-skill/SKILL.md is stale: run python3 .github/scripts/build_plugin_skill.py --write",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
