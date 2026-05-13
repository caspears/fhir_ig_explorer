"""
Extract narrative IG page content into pages.jsonl.

Preferred mode:
- source: extract from IG source markdown/xml/liquid files such as input/pagecontent.
  This avoids repeated generated HTML boilerplate.

Fallback mode:
- html: extract from generated IG HTML and remove menus/template boilerplate.

Recommendations:
- Prefer source content when available.
- Use generated HTML only when source files are unavailable.
- Keep page chunks separate from computable artifact chunks.
"""

from __future__ import annotations

import argparse
import re
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from bs4 import BeautifulSoup

from common_jsonl import chunk_text, clean_text, stable_id, strip_markdown_noise, write_jsonl, make_artifact_url, ig_context_from_root, add_common_ig_metadata


SOURCE_EXTENSIONS = {".md", ".markdown", ".xml", ".xhtml", ".liquid", ".html"}
HTML_EXTENSIONS = {".html", ".htm"}


BOILERPLATE_SELECTORS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    ".navbar",
    ".breadcrumb",
    ".breadcrumbs",
    ".sidebar",
    ".toc",
    "#segment-navbar",
    "#segment-breadcrumb",
    "#segment-footer",
    "#segment-post-footer",
    "#segment-header",
    "#hl7-nav",
    ".col-3",
    ".menu",
    ".nav",
]


def title_from_source(path: Path, text: str) -> str:
    # YAML front matter title
    match = re.search(r"(?ms)^---\s*.*?^title:\s*[\"']?([^\"'\n]+)[\"']?.*?^---\s*", text)
    if match:
        return clean_text(match.group(1))

    # Markdown first heading
    match = re.search(r"(?m)^\s*#\s+(.+?)\s*$", text)
    if match:
        return clean_text(match.group(1))

    # XML title element
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if match:
        return clean_text(re.sub(r"<.*?>", " ", match.group(1)))

    return path.stem.replace("-", " ").replace("_", " ").title()


def normalize_source_text(path: Path, text: str) -> str:
    suffix = path.suffix.lower()

    if suffix in {".xml", ".xhtml", ".html"}:
        soup = BeautifulSoup(text, "lxml")
        for node in soup(BOILERPLATE_SELECTORS):
            node.decompose()
        text = soup.get_text("\n")
    else:
        text = strip_markdown_noise(text)

    # Remove common IG Publisher liquid/includes fragments
    text = re.sub(r"\{::options.*?/\}", " ", text, flags=re.DOTALL)
    text = re.sub(r"\{:.+?\}", " ", text)
    text = re.sub(r"\[[^\]]+\]:\s+\S+", " ", text)  # markdown reference links
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # keep markdown link text
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = unescape(text)

    return clean_text(text)


def extract_from_source(path: Path, ig_name: str, base_url: Optional[str], max_chars: int) -> Iterable[Dict]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    title = title_from_source(path, raw)
    text = normalize_source_text(path, raw)

    # Skip tiny or mostly-template files
    if len(text) < 120:
        return []

    chunks = chunk_text(text, max_chars=max_chars)
    rows = []
    for index, chunk in enumerate(chunks):
        rows.append(
            {
                "id": stable_id("page", str(path), index),
                "sourceType": "NarrativePage",
                "chunkType": "source-page",
                "ig": ig_name,
                "file": str(path),
                "title": title,
                "pageUrl": make_page_url(path, base_url),
                "chunkIndex": index,
                "text": clean_text(f"Page: {title}\nSource file: {path.name}\n\n{chunk}"),
            }
        )
    return rows


def best_html_content_node(soup: BeautifulSoup):
    candidates = [
        soup.select_one("#segment-content"),
        soup.select_one("main"),
        soup.select_one(".content"),
        soup.select_one("#content"),
        soup.select_one("body"),
    ]
    return next((c for c in candidates if c is not None), soup)


def title_from_html(path: Path, soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" "))
    if soup.title:
        return clean_text(soup.title.get_text(" "))
    return path.stem.replace("-", " ").replace("_", " ").title()


def extract_from_html(path: Path, ig_name: str, base_url: Optional[str], max_chars: int) -> Iterable[Dict]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    for selector in BOILERPLATE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    content = best_html_content_node(soup)
    title = title_from_html(path, soup)

    # Remove repeated generated artifacts/table of contents anchors where possible.
    text = content.get_text("\n")
    text = re.sub(r"\n\s*(Table of Contents|Downloads|Artifacts Summary|Structures:.*)\s*\n", "\n", text, flags=re.I)
    text = clean_text(text)

    if len(text) < 120:
        return []

    chunks = chunk_text(text, max_chars=max_chars)
    rows = []
    for index, chunk in enumerate(chunks):
        rows.append(
            {
                "id": stable_id("page", str(path), index),
                "sourceType": "NarrativePage",
                "chunkType": "html-page",
                "ig": ig_name,
                "file": str(path),
                "title": title,
                "pageUrl": make_page_url(path, base_url),
                "chunkIndex": index,
                "text": clean_text(f"Page: {title}\nGenerated HTML file: {path.name}\n\n{chunk}"),
            }
        )
    return rows


def make_page_url(path: Path, base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    if path.suffix.lower() in {".md", ".markdown", ".liquid", ".xml", ".xhtml"}:
        html_name = path.with_suffix(".html").name
    else:
        html_name = path.name
    return base_url.rstrip("/") + "/" + html_name


def should_skip_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if any(p in parts for p in {".git", "node_modules", "template", "assets", "assets-old"}):
        return True
    name = path.name.lower()
    if name.startswith("_") and path.suffix.lower() in {".liquid", ".html"}:
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Source narrative folder or generated output folder")
    parser.add_argument("--output", required=True, help="Output pages.jsonl")
    parser.add_argument("--ig-name", default=None, help="Optional IG name override")
    parser.add_argument("--base-url", default=None, help="Optional published IG base URL override")
    parser.add_argument("--mode", choices=["source", "html"], default="source")
    parser.add_argument("--max-chars", type=int, default=2400)
    args = parser.parse_args()

    root = Path(args.input)
    ig_context = ig_context_from_root(root)

    if args.ig_name:
        ig_context["ig_title"] = args.ig_name
        ig_context["ig_name"] = args.ig_name

    if args.base_url:
        ig_context["base_url"] = args.base_url
        
    rows = []

    if args.mode == "source":
        extensions = SOURCE_EXTENSIONS
        extractor = extract_from_source
    else:
        extensions = HTML_EXTENSIONS
        extractor = extract_from_html

    for path in root.rglob("*"):
        if not path.is_file() or should_skip_path(path):
            continue
        if path.suffix.lower() not in extensions:
            continue
        
        rows.extend(extractor(path, args.ig_name, args.base_url, args.max_chars))

    count = write_jsonl(Path(args.output), rows)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
