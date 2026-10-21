"""Markdown rendering, slugs, excerpts and reading time."""

from __future__ import annotations

import html
import math
import re
import unicodedata
from datetime import UTC
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

# ```audio blocks are the human-friendly way to embed a player: the editor
# inserts a small fenced block (no HTML), and the renderer turns it into the
# same figure markup that bleach already allows.
_AUDIO_FENCE_RE = re.compile(
    r"(?ms)^[ \t]*(?:```|~~~)audio[ \t]*\r?\n(.*?)\r?\n[ \t]*(?:```|~~~)[ \t]*$"
)
_AUDIO_MIME = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "webm": "audio/webm",
}
_AUDIO_KEY_RE = re.compile(r"^[ \t]*(src|url|title|artist)[ \t]*:[ \t]*(.*)$", re.I)


def _audio_src(value: str) -> str:
    value = value.strip().strip("\"'")
    if not value:
        return ""
    if re.match(r"^/(?!/)", value):
        return value
    if re.match(r"^https?://", value, re.I):
        return value
    return ""


def _audio_fence_html(body: str) -> str:
    url = ""
    title = ""
    artist = ""
    for line in body.splitlines():
        match = _AUDIO_KEY_RE.match(line)
        if match:
            key = match.group(1).lower()
            value = match.group(2).strip()
            if key in {"src", "url"}:
                url = value
            elif key == "title":
                title = value
            elif key == "artist":
                artist = value
            continue
        if not url and line.strip():
            url = line.strip()
    src = _audio_src(url)
    if not src:
        return ""
    title = title.strip()[:120] or "音乐播放器"
    artist = artist.strip()[:120]
    extension = src.split("?", 1)[0].split("#", 1)[0].rsplit(".", 1)[-1].lower()
    mime = _AUDIO_MIME.get(extension, "")
    safe_src = html.escape(src, quote=True)
    safe_title = html.escape(title)
    safe_artist = html.escape(artist)
    caption = html.escape(" · ".join(part for part in (title, artist) if part), quote=True)
    source = f'<source src="{safe_src}"' + (f' type="{mime}"' if mime else "") + ">"
    artist_html = f'<span class="audio-embed__artist">{safe_artist}</span>' if artist else ""
    return (
        '\n\n<figure class="audio-embed">\n'
        "<figcaption>"
        '<span class="audio-embed__label">AUDIO</span>'
        f'<span class="audio-embed__title">{safe_title}</span>'
        f"{artist_html}"
        "</figcaption>\n"
        f'<audio controls preload="metadata" title="{caption}">{source}</audio>\n'
        "</figure>\n\n"
    )


def expand_audio_blocks(text: str) -> str:
    """Turn ```audio fences into player markup before Markdown conversion."""

    def replace(match: re.Match[str]) -> str:
        rendered = _audio_fence_html(match.group(1))
        # An invalid block stays untouched and renders as a normal code fence,
        # so nothing is silently lost.
        return rendered or match.group(0)

    return _AUDIO_FENCE_RE.sub(replace, text)


def render_markdown(text: str) -> str:
    """Render Markdown and strip anything that could execute in a browser."""
    if not text:
        return ""
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_CONFIG)
    raw = md.convert(expand_audio_blocks(text))
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
    text = _AUDIO_FENCE_RE.sub(" ", text)
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
    from datetime import datetime

    value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (
        parsed.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def plain_text(value: str) -> str:
    return html.unescape(strip_markdown(value))
