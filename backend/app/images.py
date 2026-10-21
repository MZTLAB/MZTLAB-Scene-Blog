"""Image derivative pipeline (3.0.0, artifact-level tokens).

Uploads keep their original untouched. This module generates AVIF / WebP / JPEG
copies at the widths the public pages actually use and hands the frontend a
compact per-image metadata block.

Key decisions (ADR-6 / ADR-10 / BC-34 / BC-37):

* Every derivative is addressed by the inputs that produced it::

      token = sha1(PIPELINE_VERSION | media_id | source_sha1 |
                   scene | width | format | quality)[:10]
      url   = /media/_v/{media_id}/{token}/{scene}/{width}.{fmt}

  Tokens live on the derivative rows. `media.derivative_set` caches the set that
  is currently published, so reading a page only assembles existing rows.
* Encoding quality and parameters are code constants (`PIPELINE_DEFAULTS`), not
  settings or per-image overrides. Changing them changes the token, but **only
  new uploads or a manual `reencode` job produce new artifacts**: existing
  images keep serving their current URLs until then (decision D5).
* The read path never encodes. Missing artifacts mean the frontend falls back to
  the original file (`ready: false`); a background `prewarm`/`reencode` job does
  the CPU work.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
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

# Bump when the encoding parameters change in a way that should produce new
# bytes; URLs for new uploads change, existing images keep their artifacts until
# a manual `reencode` job runs.
PIPELINE_VERSION = 4

SCENES = ("thumb", "tile", "card", "hero", "viewer", "prose", "full")
SMALL_SCENES = frozenset({"thumb", "tile", "card"})
LARGE_SCENES = frozenset({"hero", "viewer"})
FORMAT_EXT = {"avif": "avif", "webp": "webp", "jpeg": "jpg"}
EXT_FORMAT = {"avif": "avif", "webp": "webp", "jpg": "jpeg"}
DEFAULT_LADDER = (720, 2560)
MAX_LADDER_ENTRIES = 10

# Immutable encoding parameters. Quality is part of every derivative token; to
# change it, edit this constant, bump PIPELINE_VERSION and run a manual
# `reencode` job (see docs/DEVELOPMENT.md).
PIPELINE_DEFAULTS: dict[str, Any] = {
    "scene_quality": {
        "thumb": 45,
        "tile": 50,
        "card": 55,
        "hero": 67,
        "viewer": 65,
        "prose": 60,
        "full": 70,
    },
    "webp_quality": 80,
    "jpeg_quality": 82,
    "avif_speed": 6,
    "max_width": 0,  # 0 = keep the original width for the "full" scene
}

AVIF_SUPPORTED = bool(features.check("avif"))
WEBP_SUPPORTED = bool(features.check("webp"))

_SEMAPHORE = threading.BoundedSemaphore(IMAGE_ENCODE_WORKERS)


class SkipDerivative(Exception):
    """The source cannot or should not be converted (animated GIF, broken file)."""


# ---------------------------------------------------------------------------
# Settings helpers (runtime configuration is only the ladder + format switches)
# ---------------------------------------------------------------------------


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


def scene_quality(scene: str) -> int:
    qualities = PIPELINE_DEFAULTS["scene_quality"]
    return max(1, min(100, int(qualities.get(scene, qualities["full"]))))


def quality_for(scene: str, fmt: str) -> int:
    if fmt == "webp":
        return max(1, min(100, int(PIPELINE_DEFAULTS["webp_quality"])))
    if fmt == "jpeg":
        return max(1, min(100, int(PIPELINE_DEFAULTS["jpeg_quality"])))
    return scene_quality(scene)


def full_width(original: int) -> int:
    cap = int(PIPELINE_DEFAULTS["max_width"])
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
    return [full_width(original_width)]


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
# Media rows / artifact set
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


def is_convertible(row: Any) -> bool:
    if not is_image_row(row):
        return False
    if str(_field(row, "mime", "")) == "image/gif":
        # Animated GIFs keep their original file.
        return False
    return int(_field(row, "width", 0) or 0) > 0 and int(_field(row, "height", 0) or 0) > 0


def artifact_token(
    media_id: int, source_sha1: str, scene: str, width: int, fmt: str, quality: int
) -> str:
    parts = [
        str(PIPELINE_VERSION),
        str(media_id),
        source_sha1,
        scene,
        str(width),
        fmt,
        str(quality),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def derivative_key(media_id: int, token: str, scene: str, width: int, fmt: str) -> str:
    return f"{DERIVED_PREFIX}{media_id}/{token}/{scene}/{width}.{FORMAT_EXT[fmt]}"


def parse_derivative_set(row: Any) -> dict[str, Any]:
    raw = _field(row, "derivative_set", "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def current_tokens(derivative_set: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    artifacts = derivative_set.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return tokens
    for widths in artifacts.values():
        if not isinstance(widths, dict):
            continue
        for formats in widths.values():
            if isinstance(formats, dict):
                tokens.update(str(token) for token in formats.values())
    return tokens


def image_payload(row: Any, settings: Settings | None = None) -> dict[str, Any] | None:
    """Read-only metadata the frontend needs to build `<picture>` URLs.

    When the derivative set is not ready (or the source is not convertible) the
    payload reports `ready: false` and advertises no derivative URLs; the
    frontend falls back to the original file. Never encodes.
    """
    if not is_image_row(row):
        return None
    if not is_convertible(row):
        return None
    settings = settings or load_settings_cached()
    media_id = int(_field(row, "id", 0))
    if media_id <= 0:
        # A photo can outlive its media row (filename snapshot only).
        return None
    original_width = int(_field(row, "width", 0) or 0)
    original_height = int(_field(row, "height", 0) or 0)
    ladder = width_ladder(settings)
    payload: dict[str, Any] = {
        "id": media_id,
        "width": original_width,
        "height": original_height,
        "s": min(ladder[0], original_width),
        "l": min(ladder[-1], original_width),
        "f": full_width(original_width),
        "ready": False,
        "formats": [],
        "base": f"/media/_v/{media_id}",
        "direct_base": None,
        "artifacts": [],
        "placeholder": str(_field(row, "placeholder", "") or ""),
    }
    derivative_set = parse_derivative_set(row)
    if not derivative_set.get("ready"):
        return payload
    artifacts = derivative_set.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return payload
    payload["ready"] = True
    payload["formats"] = [fmt for fmt in ("avif", "webp") if fmt in generation_formats(settings)]
    payload["artifacts"] = derivative_set_artifacts(derivative_set)
    payload["s"] = int(derivative_set.get("s") or payload["s"])
    payload["l"] = int(derivative_set.get("l") or payload["l"])
    payload["f"] = int(derivative_set.get("f") or payload["f"])
    payload["pipeline_version"] = int(derivative_set.get("pipeline_version") or PIPELINE_VERSION)
    try:
        payload["direct_base"] = get_storage().derived_public_prefix(media_id)
    except Exception:  # misconfigured storage must never break pages
        payload["direct_base"] = None
    return payload


def derivative_set_artifacts(derivative_set: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the stored `artifacts` map into a DTO-friendly list.

    A typed list keeps the OpenAPI contract free of free-form objects while the
    storage format stays a compact map.
    """
    artifacts = derivative_set.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    result: list[dict[str, Any]] = []
    for scene, widths in artifacts.items():
        if not isinstance(widths, dict):
            continue
        for width, formats in widths.items():
            if not isinstance(formats, dict):
                continue
            for fmt, token in formats.items():
                result.append(
                    {
                        "scene": str(scene),
                        "width": int(width),
                        "format": str(fmt),
                        "token": str(token),
                    }
                )
    return result


def artifact_url(
    payload: dict[str, Any], scene: str, width: int, fmt: str, *, prefer_direct: bool = True
) -> str:
    token = ""
    for artifact in payload.get("artifacts") or []:
        if (
            artifact.get("scene") == scene
            and int(artifact.get("width") or 0) == width
            and artifact.get("format") == fmt
        ):
            token = str(artifact.get("token") or "")
            break
    if not token:
        return ""
    if prefer_direct and payload.get("direct_base"):
        base = str(payload["direct_base"])
    else:
        base = str(payload.get("base") or "")
    return f"{base}/{token}/{scene}/{width}.{FORMAT_EXT[fmt]}"


def derivative_url(
    payload: dict[str, Any], scene: str, width: int, fmt: str, *, prefer_direct: bool = True
) -> str:
    return artifact_url(payload, scene, width, fmt, prefer_direct=prefer_direct)


def srcset(payload: dict[str, Any], scene: str, fmt: str, *, prefer_direct: bool = True) -> str:
    candidates = []
    for width in payload_widths(scene, payload):
        url = artifact_url(payload, scene, width, fmt, prefer_direct=prefer_direct)
        if url:
            candidates.append(f"{url} {width}w")
    return ", ".join(candidates)


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


def _derivative_record(media_id: int, token: str, scene: str, width: int, fmt: str) -> Any:
    with db() as conn:
        return conn.execute(
            """SELECT * FROM media_derivatives
               WHERE media_id = ? AND token = ? AND scene = ? AND width = ? AND format = ?""",
            (media_id, token, scene, width, fmt),
        ).fetchone()


def _record_derivative(
    media_id: int,
    token: str,
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
                   (media_id, token, pipeline_version, scene, width, format,
                    quality, height, size, key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(media_id, token, scene, width, format) DO UPDATE SET
                   quality = excluded.quality, height = excluded.height,
                   size = excluded.size, key = excluded.key,
                   created_at = excluded.created_at""",
            (
                media_id,
                token,
                PIPELINE_VERSION,
                scene,
                width,
                fmt,
                quality,
                height,
                size,
                key,
                now_iso(),
            ),
        )


def source_sha1_of(row: Any) -> str:
    """Return the cached original hash, computing and storing it when missing."""
    cached = str(_field(row, "source_sha1", "") or "")
    if cached:
        return cached
    media_id = int(_field(row, "id", 0) or 0)
    filename = str(_field(row, "filename", "") or "")
    if media_id <= 0 or not filename:
        return ""
    try:
        digest = hashlib.sha1()
        for chunk in get_storage().stream(filename):
            digest.update(chunk)
    except Exception:  # storage errors are non-fatal for token computation
        logger.warning("cannot hash source for media %s", media_id)
        return ""
    value = digest.hexdigest()
    with db() as conn:
        conn.execute("UPDATE media SET source_sha1 = ? WHERE id = ?", (value, media_id))
    return value


def _load_source(data: bytes, target_width: int) -> Image.Image:
    image: Image.Image = Image.open(io.BytesIO(data))
    if image.format == "JPEG":
        # Decode at reduced scale; huge camera files never need full pixels.
        with contextlib.suppress(Exception):
            image.draft("RGB", (max(1, target_width * 2), max(1, target_width * 2)))
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
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
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


def _artifact_plan(row: Any, settings: Settings) -> list[tuple[str, int, str, int, str]]:
    """Every (scene, width, format, quality, token) this image should publish."""
    media_id = int(_field(row, "id", 0) or 0)
    original_width = int(_field(row, "width", 0) or 0)
    source_sha1 = source_sha1_of(row)
    plan: list[tuple[str, int, str, int, str]] = []
    for scene in SCENES:
        for width in scene_widths(scene, original_width, settings):
            for fmt in generation_formats(settings):
                quality = quality_for(scene, fmt)
                token = artifact_token(media_id, source_sha1, scene, width, fmt, quality)
                plan.append((scene, width, fmt, quality, token))
    return plan


def prewarm_media(media_id: int, *, force: bool = False) -> bool:
    """Generate the complete artifact set for one image and publish it.

    Runs in a background worker (jobs table). Existing artifacts are reused
    unless `force` is set. `media.derivative_set` is only replaced after the
    whole set has been generated, so a reencode never makes an image disappear:
    the previous set keeps serving until the new one is ready.
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if not is_convertible(row):
        return False
    settings = load_settings_cached()
    plan = _artifact_plan(row, settings)
    if not plan:
        return False
    token = str(_field(row, "filename", "") or "")
    try:
        source = get_storage().read(token)
    except StorageMissing:
        logger.warning("prewarm media=%s: original file is missing", media_id)
        return False
    except Exception:
        logger.exception("prewarm media=%s: cannot read original", media_id)
        return False

    artifacts: dict[str, dict[str, dict[str, str]]] = {}
    sizes: dict[str, int] = {}
    complete = True
    for scene, width, fmt, quality, artifact_token_ in plan:
        artifacts.setdefault(scene, {}).setdefault(str(width), {})[fmt] = artifact_token_
        key = derivative_key(media_id, artifact_token_, scene, width, fmt)
        existing = None if force else _derivative_record(
            media_id, artifact_token_, scene, width, fmt
        )
        storage = get_storage()
        if existing is not None and storage.exists(key):
            sizes[scene] = max(sizes.get(scene, 0), width)
            continue
        try:
            speed = max(0, min(10, int(PIPELINE_DEFAULTS["avif_speed"])))
            image = _load_source(source, width)
            try:
                data, out_width, out_height = _encode(image, width, fmt, quality, speed)
            finally:
                image.close()
            with _SEMAPHORE:
                storage.save(key, data, content_type_for(key))
            _record_derivative(
                media_id, artifact_token_, scene, width, fmt, quality, out_height, len(data), key
            )
            sizes[scene] = max(sizes.get(scene, 0), width)
        except SkipDerivative:
            continue
        except Exception:
            logger.exception(
                "prewarm failed media=%s scene=%s width=%s fmt=%s",
                media_id,
                scene,
                width,
                fmt,
            )
            complete = False

    if not complete:
        return False
    ladder = width_ladder(settings)
    original_width = int(_field(row, "width", 0) or 0)
    derivative_set = {
        "ready": True,
        "pipeline_version": PIPELINE_VERSION,
        "s": min(ladder[0], original_width),
        "l": min(ladder[-1], original_width),
        "f": full_width(original_width),
        "artifacts": artifacts,
    }
    with db() as conn:
        conn.execute(
            "UPDATE media SET derivative_set = ? WHERE id = ?",
            (json.dumps(derivative_set, ensure_ascii=False), media_id),
        )
    return True


def mark_ready(media_id: int) -> None:
    """Compatibility helper: publish whatever artifact set is already on disk."""
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if row is not None:
        prewarm_media(media_id, force=False)


def dominant_color(data: bytes) -> str:
    """A 1×1 average colour used as a decode-time placeholder."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            thumbnail = image.convert("RGB").resize((1, 1), Image.Resampling.LANCZOS)
            pixel = thumbnail.getpixel((0, 0))
            if not isinstance(pixel, tuple):
                return ""
            red, green, blue = pixel[:3]
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
        conn.execute("UPDATE media SET derivative_set = '' WHERE id = ?", (media_id,))
    storage = get_storage()
    for row in rows:
        try:
            storage.delete(row["key"])
        except Exception:
            logger.warning("could not delete derivative %s", row["key"])


def gc_derivatives(limit: int = 200, *, dry_run: bool = False) -> dict[str, int]:
    """Delete derivative rows (and objects) no longer referenced by a media set.

    Old tokens survive a reencode until this job runs, so pages never lose an
    image while new artifacts are generated. Bounded by `limit` to keep the
    SQLite write lock short. `dry_run` only reports the batch it would delete.
    """
    deleted_rows = 0
    deleted_objects = 0
    with db() as conn:
        rows = conn.execute(
            """SELECT d.id, d.key, d.token, m.derivative_set
               FROM media_derivatives d JOIN media m ON m.id = d.media_id
               ORDER BY d.id LIMIT ?""",
            (max(1, min(limit, 2000)),),
        ).fetchall()
    storage = get_storage()
    stale_ids: list[int] = []
    stale_keys: list[str] = []
    for row in rows:
        referenced = current_tokens(parse_derivative_set(dict(row)))
        if row["token"] in referenced:
            continue
        stale_ids.append(int(row["id"]))
        stale_keys.append(str(row["key"]))
    if dry_run:
        return {"rows": len(stale_ids), "objects": len(stale_keys)}
    if stale_ids:
        placeholders = ",".join("?" for _ in stale_ids)
        with db() as conn:
            conn.execute(
                f"DELETE FROM media_derivatives WHERE id IN ({placeholders})",
                stale_ids,
            )
        deleted_rows = len(stale_ids)
    for key in stale_keys:
        try:
            storage.delete(key)
            deleted_objects += 1
        except Exception:
            logger.warning("could not delete derivative %s", key)
    return {"rows": deleted_rows, "objects": deleted_objects}


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
    if not widths or not payload.get("ready"):
        return ""
    sources = []
    for fmt in payload.get("formats") or []:
        mime = "image/avif" if fmt == "avif" else "image/webp"
        candidate = ", ".join(
            f"{artifact_url(payload, scene, width, fmt)} {width}w"
            for width in widths
            if artifact_url(payload, scene, width, fmt)
        )
        if candidate:
            sources.append(
                f'<source type="{mime}" srcset="{candidate}" sizes="{sizes}">'
            )
    fallback = artifact_url(payload, scene, widths[-1], "jpeg", prefer_direct=False)
    if not fallback:
        return ""
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
        if not payload or not payload.get("ready"):
            return tag
        alt_match = _ALT_ATTR.search(tag)
        alt = alt_match.group(1) if alt_match else ""
        picture = picture_html(payload, scene="prose", alt=alt, sizes=_PROSE_SIZES)
        return picture or tag

    return _IMG_TAG.sub(replace, html)
