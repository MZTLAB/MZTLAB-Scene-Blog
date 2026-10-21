"""Image derivative pipeline.

Uploads keep their original untouched. This module generates AVIF / WebP / JPEG
copies at the widths the public pages actually use, exposes them through stable
hash-based URLs and hands the frontend a compact per-image metadata block.

Formats:
* AVIF — primary source, per-scenario quality (`advanced.image.quality_<scene>`).
* WebP — fallback for browsers without AVIF.
* JPEG — final fallback, also what a plain `<img>` loads.

The width ladder is `advanced.image.widths` (default 720,2560) plus the original
resolution as the "full" tier. Scenes map onto those tiers:

    thumb / tile / card  → smallest ladder width
    hero / viewer        → largest ladder width
    prose                → both
    full                 → original width (optionally capped by
                           `advanced.image.max_width`)

Everything here takes the typed `Settings` object; there is no flat
`dict[str, Any]` configuration any more.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import threading
from typing import Any

from PIL import Image, ImageOps, features

from .config import IMAGE_ENCODE_WORKERS, IMAGE_MAX_WIDTH_HARD_LIMIT
from .db import db, now_iso
from .settings import Settings, load_settings_cached
from .storage import (
    DERIVED_PREFIX,
    StorageMissing,
    content_type_for,
    get_storage,
)

logger = logging.getLogger("mztlab.images")

PIPELINE_VERSION = 3
SCENES = ("thumb", "tile", "card", "hero", "viewer", "prose", "full")
SMALL_SCENES = frozenset({"thumb", "tile", "card"})
LARGE_SCENES = frozenset({"hero", "viewer"})
FORMAT_EXT = {"avif": "avif", "webp": "webp", "jpeg": "jpg"}
EXT_FORMAT = {"avif": "avif", "webp": "webp", "jpg": "jpeg"}
DEFAULT_LADDER = (720, 2560)
DEFAULT_QUALITY = 55
MAX_LADDER_ENTRIES = 10

AVIF_SUPPORTED = bool(features.check("avif"))
WEBP_SUPPORTED = bool(features.check("webp"))

_SEMAPHORE = threading.BoundedSemaphore(IMAGE_ENCODE_WORKERS)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class SkipDerivative(Exception):
    """The source cannot or should not be converted (animated GIF, broken file)."""


# ---------------------------------------------------------------------------
# Settings helpers (typed `Settings`, no flat dictionaries)
# ---------------------------------------------------------------------------

SCENE_QUALITY_FIELDS: dict[str, str] = {scene: f"quality_{scene}" for scene in SCENES}


def width_ladder(settings: Settings) -> list[int]:
    """The validated width ladder; normalised defensively for old databases."""
    values: list[int] = []
    for width in settings.advanced.image.widths:
        try:
            value = int(width)
        except (TypeError, ValueError):
            continue
        if 64 <= value <= IMAGE_MAX_WIDTH_HARD_LIMIT:
            values.append(value)
    unique = sorted(set(values))[:MAX_LADDER_ENTRIES]
    return unique or list(DEFAULT_LADDER)


def avif_enabled(settings: Settings) -> bool:
    return AVIF_SUPPORTED and bool(settings.advanced.image.avif_enabled)


def webp_enabled(settings: Settings) -> bool:
    return WEBP_SUPPORTED and bool(settings.advanced.image.webp_enabled)


def generation_formats(settings: Settings) -> list[str]:
    formats: list[str] = []
    if avif_enabled(settings):
        formats.append("avif")
    if webp_enabled(settings):
        formats.append("webp")
    # JPEG is the universal fallback and always generated.
    formats.append("jpeg")
    return formats


def source_formats(settings: Settings) -> list[str]:
    """Formats offered to `<picture><source>`, in preference order."""
    return [fmt for fmt in ("avif", "webp") if fmt in generation_formats(settings)]


def _clamp_quality(value: int) -> int:
    return max(1, min(100, int(value)))


def scene_quality(scene: str, settings: Settings) -> int:
    image = settings.advanced.image
    field = SCENE_QUALITY_FIELDS.get(scene, "quality_full")
    return _clamp_quality(getattr(image, field, DEFAULT_QUALITY))


def media_quality_override(media_row: Any) -> int | None:
    """Manual AVIF quality for one image, or None when it follows the scenes."""
    if media_row is None:
        return None
    auto = int(_field(media_row, "avif_quality_auto", 1) or 0)
    if auto:
        return None
    quality = int(_field(media_row, "avif_quality", 0) or 0)
    return quality if 1 <= quality <= 100 else None


def quality_for(
    scene: str,
    fmt: str,
    settings: Settings,
    media_row: Any = None,
) -> int:
    image = settings.advanced.image
    if fmt == "webp":
        return _clamp_quality(image.webp_quality)
    if fmt == "jpeg":
        return _clamp_quality(image.jpeg_quality)
    override = media_quality_override(media_row)
    return override if override is not None else scene_quality(scene, settings)


def full_width(settings: Settings, original: int) -> int:
    cap = int(settings.advanced.image.max_width)
    if cap <= 0:
        return original
    return min(original, max(64, min(cap, IMAGE_MAX_WIDTH_HARD_LIMIT)))


def scene_widths(scene: str, original_width: int, settings: Settings) -> list[int]:
    if original_width <= 0:
        return []
    ladder = width_ladder(settings)
    small = min(ladder[0], original_width)
    large = min(ladder[-1], original_width)
    if scene in SMALL_SCENES:
        return [small]
    if scene in LARGE_SCENES:
        return [large]
    if scene == "prose":
        return sorted({small, large})
    return [full_width(settings, original_width)]


def payload_widths(scene: str, payload: dict[str, Any]) -> list[int]:
    """Widths a given scene should advertise from an image payload."""
    if scene in SMALL_SCENES:
        widths = [payload.get("s")]
    elif scene in LARGE_SCENES:
        widths = [payload.get("l")]
    elif scene == "prose":
        widths = [payload.get("s"), payload.get("l")]
    else:
        widths = [payload.get("f")]
    unique = sorted({int(width) for width in widths if width})
    return unique


# ---------------------------------------------------------------------------
# Media rows
# ---------------------------------------------------------------------------


def _field(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def is_image_row(row: Any) -> bool:
    if row is None:
        return False
    return str(_field(row, "mime", "")).startswith("image/")


def variants_hash(row: Any, settings: Settings) -> str:
    """Stable token for the current derivative set of one image.

    Changing a quality, the ladder or the enabled formats changes the token, so
    every generated URL changes with it and stale CDN entries are never served.
    """
    image = settings.advanced.image
    orig = int(_field(row, "width", 0) or 0)
    manual_quality = media_quality_override(row)
    parts = [
        str(PIPELINE_VERSION),
        str(_field(row, "id", 0)),
        str(_field(row, "filename", "")),
        str(_field(row, "size", 0)),
        str(_field(row, "avif_quality_auto", 1) or 0),
        str(manual_quality if manual_quality is not None else "auto"),
        ",".join(str(w) for w in width_ladder(settings)),
        str(full_width(settings, orig or 1)),
        ",".join(f"{scene}:{scene_quality(scene, settings)}" for scene in SCENES),
        ",".join(generation_formats(settings)),
        str(_clamp_quality(image.webp_quality)),
        str(_clamp_quality(image.jpeg_quality)),
        str(max(0, min(10, int(image.avif_speed)))),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def image_payload(row: Any, settings: Settings | None = None) -> dict[str, Any] | None:
    """Compact metadata the frontend needs to build `<picture>` URLs."""
    if not is_image_row(row):
        return None
    if str(_field(row, "mime", "")) == "image/gif":
        # Animated GIFs keep their original file.
        return None
    original_width = int(_field(row, "width", 0) or 0)
    original_height = int(_field(row, "height", 0) or 0)
    if original_width <= 0 or original_height <= 0:
        return None
    settings = settings or load_settings_cached()
    media_id = int(_field(row, "id", 0))
    if media_id <= 0:
        # A photo can outlive its media row (filename snapshot only).
        return None
    token = variants_hash(row, settings)
    ladder = width_ladder(settings)
    small = min(ladder[0], original_width)
    large = min(ladder[-1], original_width)
    full = full_width(settings, original_width)
    base = f"/media/_v/{media_id}/{token}"
    direct: str | None = None
    ready_hash = str(_field(row, "ready_hash", "") or "")
    if ready_hash and ready_hash == token:
        try:
            direct = get_storage().derived_base(media_id, token)
        except Exception:  # misconfigured storage must never break pages
            direct = None
    return {
        "width": original_width,
        "height": original_height,
        "s": small,
        "l": large,
        "f": full,
        "formats": source_formats(settings),
        "base": base,
        "direct": direct,
    }


def derivative_key(media_id: int, token: str, scene: str, width: int, fmt: str) -> str:
    return f"{DERIVED_PREFIX}{media_id}/{token}/{scene}/{width}.{FORMAT_EXT[fmt]}"


def derivative_url(
    payload: dict[str, Any], scene: str, width: int, fmt: str, *, prefer_direct: bool = True
) -> str:
    base = payload.get("base") or ""
    if prefer_direct and payload.get("direct"):
        base = payload["direct"]
    return f"{base}/{scene}/{width}.{FORMAT_EXT[fmt]}"


def srcset(payload: dict[str, Any], scene: str, fmt: str, *, prefer_direct: bool = True) -> str:
    widths = payload_widths(scene, payload)
    return ", ".join(
        f"{derivative_url(payload, scene, width, fmt, prefer_direct=prefer_direct)} {width}w"
        for width in widths
    )


def url_to_filename(url: str) -> str | None:
    """`/media/2026/05/x.jpg` → `2026/05/x.jpg` (external URLs → None)."""
    if not url:
        return None
    if url.startswith("/media/"):
        return url[len("/media/") :]
    return None


def media_by_filename(conn: Any, filename: str) -> Any:
    return conn.execute("SELECT * FROM media WHERE filename = ?", (filename,)).fetchone()


def media_by_url(conn: Any, url: str) -> Any:
    filename = url_to_filename(url)
    return media_by_filename(conn, filename) if filename else None


def image_payload_for_url(
    conn: Any, url: str, settings: Settings | None = None
) -> dict[str, Any] | None:
    row = media_by_url(conn, url)
    return image_payload(row, settings) if row else None


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _single_flight(key: str, factory):
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        return factory()


def _derivative_record(media_id: int, scene: str, width: int, fmt: str) -> Any:
    with db() as conn:
        return conn.execute(
            """SELECT * FROM media_derivatives
               WHERE media_id = ? AND scene = ? AND width = ? AND format = ?""",
            (media_id, scene, width, fmt),
        ).fetchone()


def _record_derivative(
    media_id: int,
    scene: str,
    width: int,
    fmt: str,
    quality: int,
    height: int,
    size: int,
    key: str,
) -> None:
    with db() as conn:
        conn.execute(
            """INSERT INTO media_derivatives
                   (media_id, scene, width, format, quality, height, size, key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(media_id, scene, width, format) DO UPDATE SET
                   quality = excluded.quality, height = excluded.height,
                   size = excluded.size, key = excluded.key,
                   created_at = excluded.created_at""",
            (media_id, scene, width, fmt, quality, height, size, key, now_iso()),
        )


def _load_source(data: bytes, target_width: int) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    if image.format == "JPEG":
        try:  # decode at reduced scale; huge camera files never need full pixels
            image.draft("RGB", (max(1, target_width * 2), max(1, target_width * 2)))
        except Exception:
            pass
    image = ImageOps.exif_transpose(image)
    if getattr(image, "is_animated", False):
        raise SkipDerivative("animated image keeps its original")
    image.load()
    return image


def _encode(
    image: Image.Image, width: int, fmt: str, quality: int, speed: int
) -> tuple[bytes, int, int]:
    original_width, original_height = image.size
    if 0 < width < original_width:
        height = max(1, round(original_height * width / original_width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    has_alpha = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        image = image.convert("RGBA")
    elif image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    icc = image.info.get("icc_profile")
    buffer = io.BytesIO()
    if fmt == "avif":
        image.save(
            buffer,
            "AVIF",
            quality=quality,
            speed=speed,
            subsampling="4:4:4",
            icc_profile=icc,
        )
    elif fmt == "webp":
        image.save(
            buffer,
            "WEBP",
            quality=quality,
            method=4,
            icc_profile=icc if icc else None,
        )
    else:
        if has_alpha:
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        image.save(
            buffer,
            "JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            icc_profile=icc if icc else None,
        )
    return buffer.getvalue(), image.width, image.height


def ensure_derivative(
    media_row: Any,
    settings: Settings,
    scene: str,
    width: int,
    fmt: str,
    *,
    force: bool = False,
) -> str:
    """Return the storage key of one derivative, generating it when missing."""
    media_id = int(_field(media_row, "id", 0))
    token = variants_hash(media_row, settings)
    key = derivative_key(media_id, token, scene, width, fmt)
    storage = get_storage()

    def generate() -> str:
        if not force:
            record = _derivative_record(media_id, scene, width, fmt)
            if record is not None and record["key"] == key and storage.exists(key):
                return key
        try:
            source = storage.read(str(_field(media_row, "filename", "")))
        except StorageMissing as error:
            raise SkipDerivative("original file is missing") from error
        quality = quality_for(scene, fmt, settings, media_row)
        speed = max(0, min(10, int(settings.advanced.image.avif_speed)))
        image = _load_source(source, width)
        try:
            data, out_width, out_height = _encode(image, width, fmt, quality, speed)
        finally:
            image.close()
        with _SEMAPHORE:
            storage.save(key, data, content_type_for(key))
        _record_derivative(media_id, scene, width, fmt, quality, out_height, len(data), key)
        return key

    return _single_flight(key, generate)


def prewarm_media(media_id: int, *, force: bool = False) -> bool:
    """Generate every variant the public scenes can request for one image.

    Marks `media.ready_hash` once the complete set exists so the API may switch
    to direct object-storage URLs. Runs in a worker thread (background task).
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if not is_image_row(row):
        return False
    if str(_field(row, "mime", "")) == "image/gif":
        return False
    settings = load_settings_cached()
    original_width = int(_field(row, "width", 0) or 0)
    if original_width <= 0:
        return False
    complete = True
    for scene in SCENES:
        for width in scene_widths(scene, original_width, settings):
            for fmt in generation_formats(settings):
                try:
                    ensure_derivative(row, settings, scene, width, fmt, force=force)
                except SkipDerivative:
                    continue
                except Exception:
                    logger.exception(
                        "prewarm failed media=%s scene=%s fmt=%s", media_id, scene, fmt
                    )
                    complete = False
    if complete:
        token = variants_hash(row, settings)
        with db() as conn:
            conn.execute("UPDATE media SET ready_hash = ? WHERE id = ?", (token, media_id))
    return complete


def mark_ready(media_id: int) -> None:
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            return
        token = variants_hash(row, load_settings_cached())
        conn.execute("UPDATE media SET ready_hash = ? WHERE id = ?", (token, media_id))


def dominant_color(data: bytes) -> str:
    """A 1×1 average colour used as a decode-time placeholder."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            thumbnail = image.convert("RGB").resize((1, 1), Image.Resampling.LANCZOS)
            red, green, blue = thumbnail.getpixel((0, 0))[:3]
            return f"#{red:02x}{green:02x}{blue:02x}"
    except Exception:
        return ""


def delete_derivatives(media_id: int) -> None:
    """Remove every generated object and row for one media item."""
    with db() as conn:
        rows = conn.execute(
            "SELECT key FROM media_derivatives WHERE media_id = ?", (media_id,)
        ).fetchall()
        conn.execute("DELETE FROM media_derivatives WHERE media_id = ?", (media_id,))
        conn.execute("UPDATE media SET ready_hash = '' WHERE id = ?", (media_id,))
    storage = get_storage()
    for row in rows:
        try:
            storage.delete(row["key"])
        except Exception:
            logger.warning("could not delete derivative %s", row["key"])


def derivative_stats() -> dict[str, int]:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS files, COALESCE(SUM(size), 0) AS bytes FROM media_derivatives"
        ).fetchone()
    return {"files": int(row["files"]), "bytes": int(row["bytes"])}


# ---------------------------------------------------------------------------
# Markdown inline images
# ---------------------------------------------------------------------------

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR = re.compile(r'\bsrc="([^"]*)"', re.IGNORECASE)
_ALT_ATTR = re.compile(r'\balt="([^"]*)"', re.IGNORECASE)
_PROSE_SIZES = "(max-width: 820px) 100vw, 820px"


def picture_html(
    payload: dict[str, Any],
    *,
    scene: str,
    alt: str = "",
    sizes: str,
    eager: bool = False,
    extra_class: str = "",
) -> str:
    """Server-rendered `<picture>` used for Markdown body images."""
    widths = payload_widths(scene, payload)
    if not widths:
        return ""
    sources = []
    for fmt in payload.get("formats") or []:
        mime = "image/avif" if fmt == "avif" else "image/webp"
        candidate = ", ".join(
            f"{derivative_url(payload, scene, width, fmt)} {width}w" for width in widths
        )
        sources.append(f'<source type="{mime}" srcset="{candidate}" sizes="{sizes}">')
    fallback = derivative_url(payload, scene, widths[-1], "jpeg", prefer_direct=False)
    ratio = payload["height"] / payload["width"] if payload.get("width") else 1
    display_width = widths[-1]
    display_height = max(1, round(display_width * ratio))
    loading = "eager" if eager else "lazy"
    image_tag = (
        f'<img src="{fallback}" alt="{alt}" width="{display_width}" '
        f'height="{display_height}" loading="{loading}" decoding="async">'
    )
    class_attr = f' class="{extra_class}"' if extra_class else ""
    return f"<picture{class_attr}>{''.join(sources)}{image_tag}</picture>"


def rewrite_inline_images(html: str, conn: Any, settings: Settings | None = None) -> str:
    """Upgrade `/media/...` `<img>` tags inside rendered Markdown to `<picture>`."""
    if not html or "/media/" not in html:
        return html
    settings = settings or load_settings_cached()
    tags = list(_IMG_TAG.finditer(html))
    if not tags:
        return html
    filenames: list[str] = []
    for match in tags:
        src_match = _SRC_ATTR.search(match.group(0))
        filename = url_to_filename(src_match.group(1)) if src_match else None
        if filename and filename not in filenames:
            filenames.append(filename)
    if not filenames:
        return html
    placeholders = ",".join("?" for _ in filenames)
    rows = conn.execute(
        f"SELECT * FROM media WHERE filename IN ({placeholders})", filenames
    ).fetchall()
    by_filename = {row["filename"]: row for row in rows}

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = _SRC_ATTR.search(tag)
        filename = url_to_filename(src_match.group(1)) if src_match else None
        row = by_filename.get(filename) if filename else None
        if row is None:
            return tag
        payload = image_payload(row, settings)
        if not payload:
            return tag
        alt_match = _ALT_ATTR.search(tag)
        alt = alt_match.group(1) if alt_match else ""
        picture = picture_html(payload, scene="prose", alt=alt, sizes=_PROSE_SIZES)
        return picture or tag

    return _IMG_TAG.sub(replace, html)
