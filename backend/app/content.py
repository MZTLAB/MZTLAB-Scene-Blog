"""Markdown rendering, slugs, excerpts and reading time."""

from __future__ import annotations

import html
import math
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import bleach
import markdown
from markdown.extensions.toc import slugify_unicode

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code", "col",
    "colgroup", "dd", "del", "details", "div", "dl", "dt", "em", "figcaption",
    "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins",
    "kbd", "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span",
    "strong", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "u", "ul", "input", "audio", "source",
}
ALLOWED_ATTRIBUTES = {
    "*": ["class", "id", "title"],
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "th": ["align", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
    "input": ["type", "checked", "disabled"],
    "audio": ["src", "controls", "preload", "loop", "muted", "title"],
    "source": ["src", "type"],
    "code": ["class"],
    "span": ["class"],
    "div": ["class"],
    "pre": ["class"],
}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}

MD_EXTENSIONS = [
    "extra",
    "sane_lists",
    "smarty",
    "toc",
    "codehilite",
    "nl2br",
]
MD_CONFIG = {
    "toc": {"permalink": False, "slugify": slugify_unicode},
    "codehilite": {"guess_lang": False, "css_class": "highlight", "linenums": False},
}


def render_markdown(text: str) -> str:
    """Render Markdown and strip anything that could execute in a browser."""
    if not text:
        return ""
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_CONFIG)
    raw = md.convert(text)
    cleaned = bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Make external links safe and comfortable. bleach's linkify is not used:
    # authors type Markdown links explicitly.
    cleaned = re.sub(
        r'<a (?![^>]*\brel=)([^>]*\bhref="https?://[^"]*"[^>]*)>',
        r'<a \1 rel="noopener noreferrer" target="_blank">',
        cleaned,
    )
    return cleaned


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~\-]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_excerpt(markdown_text: str, limit: int = 150) -> str:
    plain = strip_markdown(markdown_text)
    if len(plain) <= limit:
        return plain
    return plain[:limit].rstrip("，。,.、；;：: ") + "…"


def reading_time(markdown_text: str) -> int:
    plain = strip_markdown(markdown_text)
    cjk = len(re.findall(r"[\u3400-\u9fff]", plain))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", plain))
    minutes = cjk / 400 + latin_words / 220
    return max(1, math.ceil(minutes))


def slugify(value: str, fallback: str = "post") -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    value = re.sub(r"[^\w\u3400-\u9fff-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    value = value[:90].strip("-_")
    return value or fallback


def quote_slug(slug: str) -> str:
    """Slugs may contain CJK characters; keep URL-safe paths readable."""
    return quote(slug, safe="-_.~")


class _TocParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h2", "h3"}:
            attrs_map = dict(attrs)
            if attrs_map.get("id"):
                self._current = {
                    "id": attrs_map["id"],
                    "text": "",
                    "level": int(tag[1]),
                }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h2", "h3"} and self._current is not None:
            self._current["text"] = html.unescape(self._current["text"]).strip()
            if self._current["text"]:
                self.items.append(self._current)
            self._current = None


def extract_toc(rendered_html: str) -> list[dict[str, Any]]:
    parser = _TocParser()
    parser.feed(rendered_html)
    return parser.items


def normalize_iso_datetime(value: str | None) -> str | None:
    """Accept browser datetime-local or ISO 8601; store UTC with a Z suffix."""
    if not value:
        return None
    from datetime import datetime, timezone

    value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def plain_text(value: str) -> str:
    return html.unescape(strip_markdown(value))
