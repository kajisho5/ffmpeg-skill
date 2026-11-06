#!/usr/bin/env python3
"""Assemble the GitHub Pages site: the landing page in site/ plus the repository's own Markdown.
The landing page (site/index.html) is the one hand-written page; every other page is a
published document with Jekyll front matter added and its relative links rewritten.

    python3 .github/scripts/build_pages.py [OUT]     # default OUT: _pages

- A link to another published document becomes a link to its page (README.md -> index.html).
- A link to any other file or folder in the repo becomes a link to it on github.com.
- An image or other asset the pages reference is copied next to the page that uses it.
- A relative link whose target does not exist is an error: the build fails rather than
  publish a dead link.
- site/ is copied to the site root as it is (no front matter, so Jekyll does not touch it).
  Its relative src/href must point at a published page, a file in site/, or a repo file
  (a GIF under docs/demos, say), which is copied; anything else is a dead link too.

pages.yml runs this and hands OUT to actions/jekyll-build-pages; tests/test_contract.py runs
it too, so a broken link fails CI before it reaches the site.
"""
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/kajisho5/ffmpeg-skill"

# repo path -> (site path, page title). The site keeps the repo's layout, so a relative link
# between two published documents stays relative.
PAGES = {
    "README.md": ("readme.md", "README"),
    "docs/demos.md": ("docs/demos.md", "Demo gallery"),
    "docs/contract.md": ("docs/contract.md", "Contract"),
    "docs/design-decisions.md": ("docs/design-decisions.md", "Design decisions"),
    "docs/roadmap.md": ("docs/roadmap.md", "Roadmap"),
    "CHANGELOG.md": ("CHANGELOG.md", "Changelog"),
}

# ](target) in Markdown, and src= / href= / srcset= in the inline HTML the README uses.
MD_LINK = re.compile(r"""(\]\()([^)\s]+)((?:\s+(?:"[^"]*"|'[^']*'))?\))""")  # also [t](url "title")
CODE_SPAN = re.compile(r"(``[^\n]*?``|`[^`\n]*`)")
HTML_ATTR = re.compile(r"""(\b(?:src|href|srcset)=")([^"]+)(")""")
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", re.I)


class DeadLink(Exception):
    pass


def _rewrite(target: str, page_repo: str, assets: set) -> str:
    """Map one relative `target`, written in the repo document `page_repo`, to its URL on the
    published page (which sits at the same relative place in the site)."""
    if EXTERNAL.match(target):
        return target
    path, _, frag = target.partition("#")
    if not path:
        return target
    resolved = (ROOT / Path(page_repo).parent / path).resolve()
    try:
        rel = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        raise DeadLink(f"{page_repo}: {target} points outside the repository")
    if not resolved.exists():
        raise DeadLink(f"{page_repo}: {target} does not exist ({rel})")
    anchor = f"#{frag}" if frag else ""
    page_dir = Path(PAGES[page_repo][0]).parent
    if rel in PAGES:
        site = Path(PAGES[rel][0]).with_suffix(".html")
        return _relative(site, page_dir) + anchor
    if resolved.is_file() and resolved.suffix.lower() in {".png", ".gif", ".svg", ".jpg", ".jpeg", ".webp"}:
        assets.add(rel)
        return _relative(Path(rel), page_dir) + anchor
    kind = "tree" if resolved.is_dir() else "blob"
    return f"{REPO_URL}/{kind}/main/{quote(rel)}{anchor}"


def _relative(target: Path, from_dir: Path) -> str:
    up = [".."] * len(from_dir.parts)
    return "/".join(up + list(target.parts)) or "."


def _rewrite_prose(text: str, page_repo: str, assets: set) -> str:
    def md(m):
        return m.group(1) + _rewrite(m.group(2), page_repo, assets) + m.group(3)

    def attr(m):
        if not m.group(1).startswith("srcset"):
            return md(m)
        # srcset="a.png, b.png 2x": rewrite each URL, keep its descriptor
        parts = []
        for candidate in m.group(2).split(","):
            url, *descriptor = candidate.split()
            parts.append(" ".join([_rewrite(url, page_repo, assets)] + descriptor))
        return m.group(1) + ", ".join(parts) + m.group(3)

    # an inline code span is shown as written, like a fenced block
    chunks = CODE_SPAN.split(text)
    return "".join(c if i % 2 else HTML_ATTR.sub(attr, MD_LINK.sub(md, c)) for i, c in enumerate(chunks))


def render(page_repo: str, assets: set) -> str:
    text = (ROOT / page_repo).read_text(encoding="utf-8")
    # fenced code blocks are shown as written: a `](x)` inside one is code, not a link
    chunks = re.split(r"(^```.*?^```[^\n]*$)", text, flags=re.M | re.S)
    text = "".join(c if i % 2 else _rewrite_prose(c, page_repo, assets) for i, c in enumerate(chunks))
    title = PAGES[page_repo][1]
    # {% raw %} keeps Liquid from reading a `{{` or `{%` that a code sample may contain.
    return f"---\nlayout: default\ntitle: {title}\n---\n{{% raw %}}\n{text}\n{{% endraw %}}\n"


SITE = ROOT / "site"
SITE_REF = re.compile(r'\b(?:src|href)="([^"]+)"')


def _copy_site(out: Path) -> "list[str]":
    """Copy site/ to the site root and check every relative src/href in its HTML pages."""
    copied = []
    for f in sorted(SITE.rglob("*")):
        if f.is_file():
            dest = out / f.relative_to(SITE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    for page in sorted(SITE.rglob("*.html")):
        page_dir = page.parent.relative_to(SITE)
        for target in SITE_REF.findall(page.read_text(encoding="utf-8")):
            if EXTERNAL.match(target):
                continue
            path = target.split("#")[0].split("?")[0]
            if not path:
                continue
            rel = Path(os.path.normpath(page_dir / path))
            if rel.parts and rel.parts[0] == "..":
                raise DeadLink(f"site/{page.relative_to(SITE)}: {target} points outside the site")
            if (out / rel).exists():
                continue
            if rel.suffix == ".html" and (out / rel.with_suffix(".md")).is_file():
                continue  # a published document; Jekyll turns the .md into this .html
            src = ROOT / rel
            if src.is_file() and src.suffix.lower() in {".png", ".gif", ".svg", ".jpg", ".jpeg", ".webp"}:
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out / rel)
                copied.append(rel.as_posix())
                continue
            raise DeadLink(f"site/{page.relative_to(SITE)}: {target} does not exist")
    return copied


def build(out: Path) -> "list[str]":
    if out.exists():
        shutil.rmtree(out)
    assets: set = set()
    for repo, (site, _title) in PAGES.items():
        dest = out / site
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(repo, assets), encoding="utf-8")
    for rel in sorted(assets):
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    assets = sorted(assets)
    assets += _copy_site(out)
    (out / "_config.yml").write_text(
        "title: ffmpeg-skill\n"
        "description: Give your coding agent a video editor. Local FFmpeg, no cloud, no API keys.\n"
        "repository: kajisho5/ffmpeg-skill\n"
        "markdown: kramdown\n"
        "kramdown:\n  input: GFM\n  hard_wrap: false\n", encoding="utf-8")
    # The site's own layout, not a theme: a theme pulls in GitHub-API metadata the build
    # does not need, and this one page of HTML is the only design the site has.
    (out / "_layouts").mkdir()
    shutil.copy2(Path(__file__).with_name("pages_layout.html"), out / "_layouts" / "default.html")
    return sorted(set(assets))


def main(argv: "list[str]") -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "_pages"
    try:
        assets = build(out)
    except DeadLink as e:
        print(f"build_pages: dead link: {e}", file=sys.stderr)
        return 1
    print(f"build_pages: {len(PAGES)} pages, {len(assets)} assets -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
