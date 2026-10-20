"""Admin API for Scene photography: galleries and the photos inside them."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..content import slugify
from ..db import db, now_iso
from ..deps import require_permission, require_staff
from ..exif import parse_stored, photo_defaults
from ..photo_exif import DEFAULT_EXIF_FIELDS, dump_exif_fields
from ..galleries import (
    fetch_galleries,
    fetch_photos,
    gallery_dict,
    gallery_photo_rows,
    get_gallery,
    next_photo_order,
    photo_dict,
    touch_gallery,
)
from ..permissions import can, owns
from ..posts import pagination
from ..schemas import GalleryIn, PhotoBatchIn, PhotoIn, PhotoUpdateIn, ReorderIn

router = APIRouter(prefix="/admin", tags=["galleries"], dependencies=[Depends(require_staff)])

RESERVED_GALLERY_SLUGS = {"admin", "api", "media", "photos", "galleries", "new"}


def _ensure_owner(user: dict[str, Any], row: Any) -> None:
    if can(user, "content.others") or owns(user, row):
        return
    raise HTTPException(status_code=403, detail="只能管理自己创建的相册")


def _unique_gallery_slug(
    conn: sqlite3.Connection, value: str, *, gallery_id: int | None = None
) -> str:
    base = slugify(value, fallback="gallery")
    candidate = base
    number = 2
    while True:
        if candidate in RESERVED_GALLERY_SLUGS:
            candidate = f"{base}-{number}"
            number += 1
            continue
        row = conn.execute(
            "SELECT id FROM galleries WHERE slug = ? AND (? IS NULL OR id != ?)",
            (candidate, gallery_id, gallery_id),
        ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}-{number}"
        number += 1


def _get_photo(conn: sqlite3.Connection, photo_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT ph.*, g.slug AS gallery_slug, g.title AS gallery_title,
                  m.owner_id AS media_owner_id, m.uploaded_by AS media_uploaded_by,
                  m.exif AS media_exif
           FROM photos ph
           LEFT JOIN galleries g ON g.id = ph.gallery_id
           LEFT JOIN media m ON m.id = ph.media_id
           WHERE ph.id = ?""",
        (photo_id,),
    ).fetchone()


def _ensure_photo_owner(
    conn: sqlite3.Connection, user: dict[str, Any], row: sqlite3.Row
) -> None:
    """A photo belongs to its gallery; a loose photo belongs to its media owner."""
    if can(user, "content.others"):
        return
    if row["gallery_id"] is not None:
        _ensure_owner(user, _gallery_row_or_404(conn, int(row["gallery_id"])))
        return
    if owns(
        user,
        {
            "owner_id": row["media_owner_id"],
            "uploaded_by": row["media_uploaded_by"],
        },
    ):
        return
    raise HTTPException(status_code=403, detail="只能管理自己相册里的照片")


def _gallery_row_or_404(conn: sqlite3.Connection, gallery_id: int) -> sqlite3.Row:
    row = get_gallery(conn, gallery_id=gallery_id)
    if not row:
        raise HTTPException(status_code=404, detail="相册不存在")
    return row


@router.get("/galleries")
def admin_galleries(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    q: str | None = Query(None, max_length=80),
    status: str | None = Query(None, max_length=20),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    author_id = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_galleries(
            conn,
            admin=True,
            page=page,
            per_page=per_page,
            q=q,
            status=status,
            author_id=author_id,
        )
        items = [gallery_dict(conn, row, admin=True) for row in rows]
        counts_sql = "SELECT status, COUNT(*) AS n FROM galleries"
        counts_args: list[Any] = []
        if author_id is not None:
            counts_sql += " WHERE author_id = ?"
            counts_args.append(author_id)
        counts = {
            row["status"]: int(row["n"])
            for row in conn.execute(counts_sql + " GROUP BY status", counts_args)
        }
    counts["all"] = sum(counts.values())
    return {
        "items": items,
        "counts": counts,
        **pagination(page, per_page, total),
    }


@router.get("/galleries/{gallery_id}")
def admin_gallery(
    gallery_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        _ensure_owner(user, row)
        item = gallery_dict(conn, row, detail=True, admin=True)
    return item


@router.post("/galleries", status_code=201)
def create_gallery(
    payload: GalleryIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    now = now_iso()
    with db() as conn:
        slug = _unique_gallery_slug(conn, payload.slug or payload.title)
        cur = conn.execute(
            """INSERT INTO galleries(title, slug, description, status, featured,
                                     cover_photo_id, author_id, view_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                payload.title,
                slug,
                payload.description,
                payload.status,
                1 if payload.featured else 0,
                payload.cover_photo_id,
                int(user["id"]),
                now,
                now,
            ),
        )
        row = _gallery_row_or_404(conn, int(cur.lastrowid))
        item = gallery_dict(conn, row, detail=True, admin=True)
    return item


@router.put("/galleries/{gallery_id}")
def update_gallery(
    gallery_id: int,
    payload: GalleryIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        _ensure_owner(user, row)
        slug = _unique_gallery_slug(
            conn, payload.slug or row["slug"], gallery_id=gallery_id
        )
        if payload.cover_photo_id is not None:
            cover = conn.execute(
                "SELECT 1 FROM photos WHERE id = ? AND gallery_id = ?",
                (payload.cover_photo_id, gallery_id),
            ).fetchone()
            if not cover:
                payload.cover_photo_id = None
        conn.execute(
            """UPDATE galleries SET title = ?, slug = ?, description = ?, status = ?,
                   featured = ?, cover_photo_id = ?, updated_at = ? WHERE id = ?""",
            (
                payload.title,
                slug,
                payload.description,
                payload.status,
                1 if payload.featured else 0,
                payload.cover_photo_id,
                now_iso(),
                gallery_id,
            ),
        )
        fresh = _gallery_row_or_404(conn, gallery_id)
        item = gallery_dict(conn, fresh, detail=True, admin=True)
    return item


@router.delete("/galleries/{gallery_id}")
def delete_gallery(
    gallery_id: int,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        _ensure_owner(user, row)
        conn.execute("DELETE FROM photos WHERE gallery_id = ?", (gallery_id,))
        conn.execute("DELETE FROM galleries WHERE id = ?", (gallery_id,))
    return {"ok": True, "deleted": gallery_id, "title": row["title"]}


@router.post("/galleries/{gallery_id}/photos", status_code=201)
def add_photos(
    gallery_id: int,
    payload: PhotoBatchIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        _ensure_owner(user, row)
        media_rows = []
        for media_id in dict.fromkeys(payload.media_ids):
            media = conn.execute(
                "SELECT * FROM media WHERE id = ? AND mime LIKE 'image/%'", (media_id,)
            ).fetchone()
            if not media:
                continue
            if not (can(user, "content.others") or owns(user, media)):
                raise HTTPException(status_code=403, detail="只能使用自己上传的媒体")
            media_rows.append(media)
        if not media_rows:
            raise HTTPException(status_code=400, detail="没有找到可用的图片")
        order = next_photo_order(conn, gallery_id)
        now = now_iso()
        added: list[int] = []
        for media in media_rows:
            defaults = photo_defaults(parse_stored(media["exif"]))
            cur = conn.execute(
                """INSERT INTO photos(gallery_id, media_id, filename, title, caption,
                                      location, camera, lens, taken_at, width, height,
                                      featured, status, sort_order, allow_download, created_at)
                   VALUES (?, ?, ?, ?, '', '', ?, ?, ?, ?, ?, 0, ?, ?, 1, ?)""",
                (
                    gallery_id,
                    media["id"],
                    media["filename"],
                    (media["alt"] or media["original_name"]).strip()[:140],
                    defaults["camera"],
                    defaults["lens"],
                    defaults["taken_at"],
                    media["width"],
                    media["height"],
                    payload.status,
                    order,
                    now,
                ),
            )
            added.append(int(cur.lastrowid))
            order += 10
        conn.execute(
            "UPDATE galleries SET cover_photo_id = COALESCE(cover_photo_id, ?), updated_at = ? WHERE id = ?",
            (added[0], now, gallery_id),
        )
        fresh = _gallery_row_or_404(conn, gallery_id)
        item = gallery_dict(conn, fresh, detail=True, admin=True)
    return {"ok": True, "added": added, "gallery": item}


@router.post("/galleries/{gallery_id}/reorder")
def reorder_photos(
    gallery_id: int,
    payload: ReorderIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        _ensure_owner(user, row)
        existing = {
            int(item["id"])
            for item in gallery_photo_rows(conn, gallery_id, public=False)
        }
        order = 10
        for photo_id in payload.ids:
            if photo_id not in existing:
                continue
            conn.execute(
                "UPDATE photos SET sort_order = ? WHERE id = ? AND gallery_id = ?",
                (order, photo_id, gallery_id),
            )
            order += 10
        touch_gallery(conn, gallery_id)
        fresh = _gallery_row_or_404(conn, gallery_id)
        item = gallery_dict(conn, fresh, detail=True, admin=True)
    return {"ok": True, "gallery": item}


@router.get("/photos")
def admin_photos(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=120),
    gallery_id: int | None = None,
    q: str | None = Query(None, max_length=80),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    author_id = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_photos(
            conn,
            admin=True,
            gallery_id=gallery_id,
            page=page,
            per_page=per_page,
            q=q,
            order="manual",
            author_id=author_id,
        )
        items = [photo_dict(row) for row in rows]
    return {"items": items, **pagination(page, per_page, total)}


@router.post("/photos", status_code=201)
def create_photo(
    payload: PhotoIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        media = conn.execute(
            "SELECT * FROM media WHERE id = ? AND mime LIKE 'image/%'", (payload.media_id,)
        ).fetchone()
        if not media:
            raise HTTPException(status_code=404, detail="图片不存在")
        if not (can(user, "content.others") or owns(user, media)):
            raise HTTPException(status_code=403, detail="只能使用自己上传的媒体")
        if payload.gallery_id is not None:
            _ensure_owner(user, _gallery_row_or_404(conn, payload.gallery_id))
        defaults = photo_defaults(parse_stored(media["exif"]))
        cur = conn.execute(
            """INSERT INTO photos(gallery_id, media_id, filename, title, caption,
                                  location, camera, lens, taken_at, width, height,
                                  exif_fields, featured, status, sort_order,
                                  allow_download, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.gallery_id,
                media["id"],
                media["filename"],
                payload.title or (media["alt"] or media["original_name"])[:140],
                payload.caption,
                payload.location,
                payload.camera or defaults["camera"],
                payload.lens or defaults["lens"],
                payload.taken_at or defaults["taken_at"],
                media["width"],
                media["height"],
                dump_exif_fields(
                    payload.exif_fields
                    if payload.exif_fields is not None
                    else list(DEFAULT_EXIF_FIELDS)
                ),
                1 if payload.featured else 0,
                payload.status,
                next_photo_order(conn, payload.gallery_id),
                1 if payload.allow_download else 0,
                now_iso(),
            ),
        )
        touch_gallery(conn, payload.gallery_id)
        row = _get_photo(conn, int(cur.lastrowid))
        item = photo_dict(row) if row else {}
    return item


@router.put("/photos/{photo_id}")
def update_photo(
    photo_id: int,
    payload: PhotoUpdateIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_photo(conn, photo_id)
        if not row:
            raise HTTPException(status_code=404, detail="照片不存在")
        _ensure_photo_owner(conn, user, row)
        if payload.gallery_id is not None and payload.gallery_id != row["gallery_id"]:
            _ensure_owner(user, _gallery_row_or_404(conn, payload.gallery_id))
        conn.execute(
            """UPDATE photos SET gallery_id = ?, title = ?, caption = ?, location = ?,
                   camera = ?, lens = ?, taken_at = ?, exif_fields = COALESCE(?, exif_fields),
                   featured = ?, status = ?, sort_order = COALESCE(?, sort_order),
                   allow_download = COALESCE(?, allow_download)
               WHERE id = ?""",
            (
                payload.gallery_id,
                payload.title,
                payload.caption,
                payload.location,
                payload.camera,
                payload.lens,
                payload.taken_at,
                dump_exif_fields(payload.exif_fields) if payload.exif_fields is not None else None,
                1 if payload.featured else 0,
                payload.status,
                payload.sort_order,
                None
                if payload.allow_download is None
                else (1 if payload.allow_download else 0),
                photo_id,
            ),
        )
        touch_gallery(conn, payload.gallery_id)
        touch_gallery(conn, int(row["gallery_id"]) if row["gallery_id"] else None)
        updated = _get_photo(conn, photo_id)
        item = photo_dict(updated) if updated else {}
    return item


@router.delete("/photos/{photo_id}")
def delete_photo(
    photo_id: int,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_photo(conn, photo_id)
        if not row:
            raise HTTPException(status_code=404, detail="照片不存在")
        _ensure_photo_owner(conn, user, row)
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        if row["gallery_id"] is not None:
            gallery_id = int(row["gallery_id"])
            cover = conn.execute(
                "SELECT cover_photo_id FROM galleries WHERE id = ?", (gallery_id,)
            ).fetchone()
            if cover and cover["cover_photo_id"] == photo_id:
                replacement = conn.execute(
                    "SELECT id FROM photos WHERE gallery_id = ? ORDER BY sort_order, id LIMIT 1",
                    (gallery_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE galleries SET cover_photo_id = ? WHERE id = ?",
                    (replacement["id"] if replacement else None, gallery_id),
                )
            touch_gallery(conn, gallery_id)
    return {"ok": True, "deleted": photo_id}
