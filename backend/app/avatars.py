"""Avatar URL policy.

Avatars are rendered straight into ``<img src>`` on public pages and in the
admin shell. The value must therefore never point at an active document:
SVG (scriptable when the URL is opened directly), HTML, PDF, ``data:`` /
``blob:`` / ``javascript:`` URLs or anything else that is not a plainly
image-typed file. Only root-relative paths and absolute http(s) URLs that end
in a raster-image extension are accepted; everything else is rejected on input
and dropped when serializing legacy rows.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Raster formats every browser renders as a static image. SVG is deliberately
# absent: an SVG can carry script and, unlike JPEG/PNG, is a document.
AVATAR_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "avif"})

# Control characters, whitespace and quotes/angle brackets never belong in an
# image URL; rejecting them also keeps the value inert in HTML attributes.
_FORBIDDEN_CHARS = re.compile(r"[\s\x00-\x1f\x7f\"'<>\\]")

AVATAR_ERROR = (
    "头像需要是 JPG / PNG / WebP / GIF / AVIF 图片链接"
    "（站内路径以 / 开头，或使用 http(s):// 地址）"
)


def _avatar_path(value: str) -> str:
    """Return the URL path to inspect, or "" when the URL shape is rejected."""
    if value.startswith("/"):
        # `//host/...` is protocol-relative (i.e. external), not a site path.
        if value.startswith("//"):
            return ""
        return value.split("#", 1)[0].split("?", 1)[0]
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed.path


def avatar_url_error(value: str) -> str | None:
    """Return a user-facing policy violation, or None when the URL is safe."""
    value = (value or "").strip()
    if not value:
        return None
    if _FORBIDDEN_CHARS.search(value):
        return AVATAR_ERROR
    path = _avatar_path(value)
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return AVATAR_ERROR
    if name.rsplit(".", 1)[-1].lower() not in AVATAR_EXTENSIONS:
        return AVATAR_ERROR
    return None


def clean_avatar_url(value: str) -> str:
    """Return `value` when it is a safe avatar URL, otherwise "".

    Used on output as well as input so avatars stored before this policy (or
    written directly to the database) can never reach a page.
    """
    value = (value or "").strip()
    return value if value and avatar_url_error(value) is None else ""
