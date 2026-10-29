#!/usr/bin/env python3
"""Assemble the GitHub Pages site from the repository's own Markdown, so the site never says
anything the repo doesn't. Nothing here is hand-written copy: each page is a published
document with Jekyll front matter added and its relative links rewritten.

    python3 .github/scripts/build_pages.py [OUT]     # default OUT: _pages

- A link to another published document becomes a link to its page (README.md -> index.html).
- A link to any other file or folder in the repo becomes a link to it on github.com.
- An image or other asset the pages reference is copied next to the page that uses it.
- A relative link whose target does not exist is an error: the build fails rather than
  publish a dead link.

pages.yml runs this and hands OUT to actions/jekyll-build-pages; tests/test_contract.py runs
it too, so a broken link fails CI before it reaches the site.
"""
import html
import json
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
    "README.md": ("index.md", "ffmpeg-skill"),
    "docs/demos.md": ("docs/demos.md", "Demo gallery"),
    "docs/contract.md": ("docs/contract.md", "Contract"),
    "docs/design-decisions.md": ("docs/design-decisions.md", "Design decisions"),
    # HTML, not Markdown: the FAQ is a <details> page. Jekyll would otherwise run it
    # through kramdown and can split the widgets. layout: faq is the matching template.
    "docs/faq.md": ("docs/faq.html", "FAQ"),
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


_FAQ_ARTICLE = re.compile(
    r'<article class="qa" id="[^"]+">.*?<summary>(?P<q>.*?)</summary>\s*<div class="a">(?P<a>.*?)</div>',
    re.S,
)


def _html_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return re.sub(r"\s+([?.!,;:])", r"\1", text)


def _faq_jsonld(page_html: str) -> str:
    """FAQPage schema from the visible questions, so the JSON cannot drift from the page."""
    entities = []
    for match in _FAQ_ARTICLE.finditer(page_html):
        answer = re.sub(r'<p class="src">.*?</p>', " ", match.group("a"), flags=re.S)
        entities.append({
            "@type": "Question",
            "name": _html_text(match.group("q")),
            "acceptedAnswer": {"@type": "Answer", "text": _html_text(answer)},
        })
    if not entities:
        raise DeadLink("docs/faq.md: no questions found to build the FAQPage schema")
    payload = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}
    body = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return '<script type="application/ld+json">\n' + body + "\n</script>\n"


def render(page_repo: str, assets: set) -> str:
    text = (ROOT / page_repo).read_text(encoding="utf-8")
    # fenced code blocks are shown as written: a `](x)` inside one is code, not a link
    chunks = re.split(r"(^```.*?^```[^\n]*$)", text, flags=re.M | re.S)
    text = "".join(c if i % 2 else _rewrite_prose(c, page_repo, assets) for i, c in enumerate(chunks))
    if page_repo == "docs/faq.md":
        text += "\n" + _faq_jsonld(text)
        layout = "faq"
    else:
        layout = "default"
    title = PAGES[page_repo][1]
    # {% raw %} keeps Liquid from reading a `{{` or `{%` that a code sample may contain.
    return f"---\nlayout: {layout}\ntitle: {title}\n---\n{{% raw %}}\n{text}\n{{% endraw %}}\n"


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
    (out / "_config.yml").write_text(
        "title: ffmpeg-skill\n"
        "description: Give your coding agent a video editor. Local FFmpeg, no cloud, no API keys.\n"
        "repository: kajisho5/ffmpeg-skill\n"
        "markdown: kramdown\n"
        "kramdown:\n  input: GFM\n  hard_wrap: false\n", encoding="utf-8")
    # The site's own layouts, not a theme: a theme pulls in GitHub-API metadata the build
    # does not need. default.html is every page but the FAQ; faq.html is that page only.
    (out / "_layouts").mkdir()
    here = Path(__file__).parent
    shutil.copy2(here / "pages_layout.html", out / "_layouts" / "default.html")
    shutil.copy2(here / "pages_faq_layout.html", out / "_layouts" / "faq.html")
    return sorted(assets)


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
