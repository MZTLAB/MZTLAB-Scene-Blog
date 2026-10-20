"""Gallery + photo queries and JSON shaping.

A gallery ("相册") is a curated set of photos. Photos always reference a row in
`media`, keeping the validated file metadata, and carry their own caption /
location / date so the photography side of the site has a real content model
instead of reusing Markdown posts.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .content import quote_slug
from .db import load_settings_cached, now_iso
from .exif import parse_stored
from .images import image_payload
from .photo_exif import parse_stored_exif_fields

GALLERY_PUBLIC_CONDITION = "g.status = 'published'"
# Photographs are only public as part of a published album. Loose photos and
# photos in draft albums never leave the studio.
PHOTO_PUBLIC_CONDITION = (
    "ph.status = 'published' AND ph.gallery_id IS NOT NULL AND g.status = 'published'"
)

_BASE_GALLERY = """
    SELECT g.*, u.display_name AS author_name, u.username AS author_username,
           u.avatar AS author_avatar
    FROM galleries g LEFT JOIN users u ON u.id = g.author_id
"""

_PHOTO_COLUMNS = """
    ph.id, ph.gallery_id, ph.media_id, ph.filename, ph.title, ph.caption,
    ph.location, ph.camera, ph.lens, ph.taken_at, ph.width, ph.height,
    ph.exif_fields, ph.featured, ph.status, ph.sort_order, ph.created_at,
    ph.allow_download,
    g.title AS gallery_title, g.slug AS gallery_slug,
    m.exif AS media_exif, m.size AS media_size, m.mime AS media_mime,
    m.avif_quality AS media_avif_quality,
    m.avif_quality_auto AS media_avif_quality_auto,
    m.ready_hash AS media_ready_hash,
    m.width AS media_width, m.height AS media_height,
    m.original_name AS media_original_name
"""

_PHOTO_JOINS = (
    " FROM photos ph LEFT JOIN galleries g ON g.id = ph.gallery_id "
    "LEFT JOIN media m ON m.id = ph.media_id "
)


def media_url(filename: str) -> str:
    return f"/media/{filename}"


def photo_dict(
    row: sqlite3.Row | dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(row)
    width = int(data.get("width") or 0)
    height = int(data.get("height") or 0)
    settings = settings or load_settings_cached()
    gallery = None
    if data.get("gallery_id") and data.get("gallery_slug"):
        gallery = {
            "id": int(data["gallery_id"]),
            "title": data.get("gallery_title") or "",
            "slug": data.get("gallery_slug") or "",
            "url": f"/galleries/{quote_slug(data['gallery_slug'])}",
        }
    title = data.get("title") or ""
    caption = data.get("caption") or ""
    exif = parse_stored(data.get("media_exif")) or {}
    # Media-library EXIF is authoritative; photo columns are only a fallback
    # when a photo has no linked EXIF block at all.
    if exif:
        camera = exif.get("camera") or ""
        lens = exif.get("lens") or ""
        taken_at = exif.get("taken_at") or ""
    else:
        camera = data.get("camera") or ""
        lens = data.get("lens") or ""
        taken_at = data.get("taken_at") or ""
    technical = {
        "camera": camera,
        "lens": lens,
        "taken_at": taken_at,
        "taken_at_raw": exif.get("taken_at_raw") or "",
        "aperture": exif.get("aperture") or "",
        "exposure": exif.get("exposure") or "",
        "iso": exif.get("iso") or None,
        "focal_length": exif.get("focal_length") or "",
        "focal_length_35mm": exif.get("focal_length_35mm") or None,
    }
    visible_fields = parse_stored_exif_fields(data.get("exif_fields"))
    public_exif = (
        {
            key: value
            for key, value in technical.items()
            if key in visible_fields
            or (key == "taken_at_raw" and "taken_at" in visible_fields)
            or (key == "focal_length_35mm" and "focal_length" in visible_fields)
        }
        if exif
        else None
    )
    # Media-library metadata drives the image pipeline. A photo keeps a
    # filename snapshot, so a deleted media row simply falls back to `<img>`.
    media_row = {
        "id": data.get("media_id"),
        "filename": data["filename"],
        "mime": data.get("media_mime") or "image/jpeg",
        "size": data.get("media_size") or 0,
        "width": data.get("media_width") or width,
        "height": data.get("media_height") or height,
        "avif_quality": data.get("media_avif_quality") or 55,
        "avif_quality_auto": data.get("media_avif_quality_auto", 1),
        "ready_hash": data.get("media_ready_hash") or "",
    }
    filename = data["filename"]
    download_name = (
        data.get("media_original_name")
        or str(filename).rsplit("/", 1)[-1]
        or "photo"
    )
    allow_download = bool(data.get("allow_download", 1))
    return {
        "id": int(data["id"]),
        "gallery_id": int(data["gallery_id"]) if data.get("gallery_id") else None,
        "gallery": gallery,
        "media_id": data.get("media_id"),
        "url": media_url(data["filename"]),
        "filename": data["filename"],
        "title": title,
        "caption": caption,
        "alt": title or caption or "摄影作品",
        "location": data.get("location") or "",
        "camera": camera,
        "lens": lens,
        "taken_at": taken_at,
        "taken_at_raw": technical["taken_at_raw"],
        "aperture": technical["aperture"],
        "exposure": technical["exposure"],
        "iso": technical["iso"],
        "focal_length": technical["focal_length"],
        "focal_length_35mm": technical["focal_length_35mm"],
        "exif_fields": visible_fields,
        "exif": public_exif,
        "image": image_payload(media_row, settings),
        "allow_download": allow_download,
        "download_name": download_name,
        "download_url": f"{media_url(filename)}?download=1" if allow_download else "",
        "width": width,
        "height": height,
        "aspect": round(width / height, 4) if width and height else 1.5,
        "featured": bool(data.get("featured")),
        "status": data.get("status") or "published",
        "sort_order": int(data.get("sort_order") or 0),
        "created_at": data.get("created_at") or "",
    }


def gallery_dict(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    detail: bool = False,
    admin: bool = False,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(row)
    settings = settings or load_settings_cached()
    photos = list(
        conn.execute(
            f"SELECT {_PHOTO_COLUMNS}{_PHOTO_JOINS}"
            "WHERE ph.gallery_id = ? "
            + ("" if admin else "AND ph.status = 'published' ")
            + "ORDER BY ph.sort_order ASC, ph.id ASC",
            (data["id"],),
        )
    )
    photo_items = [photo_dict(item, settings) for item in photos]
    cover = None
    cover_id = data.get("cover_photo_id")
    if cover_id:
        for item in photo_items:
            if item["id"] == int(cover_id):
                cover = item
                break
    if cover is None:
        cover = photo_items[0] if photo_items else None

    item: dict[str, Any] = {
        "id": data["id"],
        "title": data["title"],
        "slug": data["slug"],
        "url": f"/galleries/{quote_slug(data['slug'])}",
        "description": data["description"],
        "status": data["status"],
        "featured": bool(data["featured"]),
        "cover": cover,
        "photo_count": len(photo_items),
        "view_count": data["view_count"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "author": {
            "name": data.get("author_name") or "MZTLAB",
            "avatar": data.get("author_avatar") or "",
        },
    }
    if admin:
        item["author_id"] = data.get("author_id")
        item["cover_photo_id"] = cover_id
    if detail:
        item["photos"] = photo_items
    return item


def fetch_galleries(
    conn: sqlite3.Connection,
    *,
    admin: bool = False,
    featured: bool | None = None,
    page: int = 1,
    per_page: int = 24,
    q: str | None = None,
    author_id: int | None = None,
    status: str | None = None,
) -> tuple[list[sqlite3.Row], int]:
    page = max(1, page)
    per_page = max(1, min(per_page, 60))
    where: list[str] = []
    args: list[Any] = []
    if not admin:
        where.append(GALLERY_PUBLIC_CONDITION)
    elif status in {"draft", "published"}:
        where.append("g.status = ?")
        args.append(status)
    if featured is not None:
        where.append("g.featured = ?")
        args.append(1 if featured else 0)
    if author_id is not None:
        where.append("g.author_id = ?")
        args.append(author_id)
    if q:
        # Galleries are searchable by their own copy and by the metadata of the
        # published photos inside them (title, caption, place, camera, date).
        where.append(
            "(g.title LIKE ? OR g.description LIKE ? OR EXISTS ("
            "  SELECT 1 FROM photos phq WHERE phq.gallery_id = g.id "
            "  AND phq.status = 'published' AND ("
            "    phq.title LIKE ? OR phq.caption LIKE ? OR phq.location LIKE ? "
            "    OR phq.camera LIKE ? OR phq.lens LIKE ? OR phq.taken_at LIKE ?"
            "  )))"
        )
        needle = f"%{q.strip()}%"
        args.extend([needle] * 8)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM galleries g{clause}", args).fetchone()[0]
    )
    order = "g.featured DESC, g.updated_at DESC, g.id DESC"
    rows = list(
        conn.execute(
            f"{_BASE_GALLERY}{clause} ORDER BY {order} LIMIT ? OFFSET ?",
            [*args, per_page, (page - 1) * per_page],
        )
    )
    return rows, total


def get_gallery(
    conn: sqlite3.Connection,
    *,
    gallery_id: int | None = None,
    slug: str | None = None,
    public: bool = False,
) -> sqlite3.Row | None:
    sql = _BASE_GALLERY + " WHERE "
    args: list[Any] = []
    if gallery_id is not None:
        sql += "g.id = ?"
        args.append(gallery_id)
    elif slug is not None:
        sql += "g.slug = ?"
        args.append(slug)
    else:
        return None
    if public:
        sql += " AND " + GALLERY_PUBLIC_CONDITION
    return conn.execute(sql, args).fetchone()


def gallery_photo_rows(
    conn: sqlite3.Connection, gallery_id: int, *, public: bool = True
) -> list[sqlite3.Row]:
    sql = (
        f"SELECT {_PHOTO_COLUMNS}{_PHOTO_JOINS}"
        "WHERE ph.gallery_id = ?"
    )
    if public:
        sql += " AND ph.status = 'published'"
    sql += " ORDER BY ph.sort_order ASC, ph.id ASC"
    return list(conn.execute(sql, (gallery_id,)))


def fetch_photos(
    conn: sqlite3.Connection,
    *,
    admin: bool = False,
    gallery_id: int | None = None,
    gallery_slug: str | None = None,
    featured: bool | None = None,
    page: int = 1,
    per_page: int = 24,
    q: str | None = None,
    order: str = "recent",
    author_id: int | None = None,
) -> tuple[list[sqlite3.Row], int]:
    page = max(1, page)
    per_page = max(1, min(per_page, 120))
    where: list[str] = []
    args: list[Any] = []
    if not admin:
        where.append(PHOTO_PUBLIC_CONDITION)
    if gallery_id is not None:
        where.append("ph.gallery_id = ?")
        args.append(gallery_id)
    if gallery_slug:
        where.append("g.slug = ?")
        args.append(gallery_slug)
    if featured is not None:
        where.append("ph.featured = ?")
        args.append(1 if featured else 0)
    if author_id is not None:
        where.append("g.author_id = ?")
        args.append(author_id)
    if q:
        where.append(
            "(ph.title LIKE ? OR ph.caption LIKE ? OR ph.location LIKE ? OR g.title LIKE ? "
            "OR ph.camera LIKE ? OR ph.lens LIKE ? OR ph.taken_at LIKE ?)"
        )
        needle = f"%{q.strip()}%"
        args.extend([needle] * 7)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM photos ph LEFT JOIN galleries g ON g.id = ph.gallery_id{clause}",
            args,
        ).fetchone()[0]
    )

    if order == "manual":
        ordering = "ph.sort_order ASC, ph.id ASC"
    elif order == "taken":
        ordering = "COALESCE(NULLIF(ph.taken_at, ''), ph.created_at) DESC, ph.id DESC"
    else:
        ordering = "ph.created_at DESC, ph.id DESC"
    rows = list(
        conn.execute(
            f"""SELECT {_PHOTO_COLUMNS}{_PHOTO_JOINS}
                {clause} ORDER BY {ordering} LIMIT ? OFFSET ?""",
            [*args, per_page, (page - 1) * per_page],
        )
    )
    return rows, total


def public_counts(conn: sqlite3.Connection) -> dict[str, int]:
    photo_count = int(
        conn.execute(
            f"""SELECT COUNT(*) FROM photos ph
                LEFT JOIN galleries g ON g.id = ph.gallery_id
                WHERE {PHOTO_PUBLIC_CONDITION}"""
        ).fetchone()[0]
    )
    gallery_count = int(
        conn.execute(
            f"SELECT COUNT(*) FROM galleries g WHERE {GALLERY_PUBLIC_CONDITION}"
        ).fetchone()[0]
    )
    return {"photo_count": photo_count, "gallery_count": gallery_count}


def next_photo_order(conn: sqlite3.Connection, gallery_id: int | None) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS n FROM photos WHERE gallery_id IS ?",
        (gallery_id,),
    ).fetchone()
    return int(row["n"]) + 10


def touch_gallery(conn: sqlite3.Connection, gallery_id: int | None) -> None:
    if gallery_id is None:
        return
    conn.execute(
        "UPDATE galleries SET updated_at = ? WHERE id = ?", (now_iso(), gallery_id)
    )
