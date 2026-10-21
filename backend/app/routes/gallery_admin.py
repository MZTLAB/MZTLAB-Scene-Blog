"""Admin API for Scene photography: galleries and the photos inside them.

Ownership uses the single 3.0.0 rule: galleries carry `owner_id`, photos inherit
their gallery's owner. Every check goes through `app.services.authz` instead of
a local helper. Updates are PATCH-style (omitted fields are kept, an explicit
`null` clears a nullable value).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api.models import (
    AdminGalleryDetail,
    AdminGalleryListResponse,
    GalleryDeleteResponse,
    GalleryPhotosAddedResponse,
    GalleryReorderResponse,
    PhotoDeleteResponse,
    PhotoImage,
    PhotoListResponse,
)
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
from ..permissions import can
from ..posts import pagination
from ..schemas import GalleryIn, PhotoBatchIn, PhotoIn, PhotoUpdateIn, ReorderIn
from ..services.authz import authorize, authorize_photo

router = APIRouter(prefix="/admin", tags=["galleries"], dependencies=[Depends(require_staff)])

RESERVED_GALLERY_SLUGS = {"admin", "api", "media", "photos", "galleries", "new"}


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
                  m.exif AS media_exif
           FROM photos ph
           LEFT JOIN galleries g ON g.id = ph.gallery_id
           LEFT JOIN media m ON m.id = ph.media_id
           WHERE ph.id = ?""",
        (photo_id,),
    ).fetchone()


def _gallery_row_or_404(conn: sqlite3.Connection, gallery_id: int) -> sqlite3.Row:
    row = get_gallery(conn, gallery_id=gallery_id)
    if not row:
        raise HTTPException(status_code=404, detail="相册不存在")
    return row


def _apply_columns(
    conn: sqlite3.Connection, table: str, row_id: int, columns: dict[str, Any]
) -> None:
    """Run the dynamic partial UPDATE built from a fixed column mapping."""
    if not columns:
        return
    assignments = ", ".join(f"{name} = ?" for name in columns)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?",
        [*columns.values(), row_id],
    )


def _photo_patch_columns(payload: PhotoUpdateIn) -> dict[str, Any]:
    """Map only the fields the client actually sent to `photos` columns.

    Omitted field → absent from the mapping (kept); explicit JSON `null` → a
    cleared value (photo removed from its gallery, text emptied, EXIF list
    emptied, download reset to allowed).
    """
    provided = payload.model_dump(exclude_unset=True)
    columns: dict[str, Any] = {}
    for field in ("title", "caption", "location", "camera", "lens", "taken_at"):
        if field in provided:
            columns[field] = str(provided[field] or "")
    if "gallery_id" in provided:
        columns["gallery_id"] = provided["gallery_id"]
    if "exif_fields" in provided:
        columns["exif_fields"] = dump_exif_fields(provided["exif_fields"])
    if "featured" in provided:
        columns["featured"] = 1 if provided["featured"] else 0
    if "status" in provided:
        columns["status"] = str(provided["status"])
    if "sort_order" in provided:
        columns["sort_order"] = int(provided["sort_order"] or 0)
    if "allow_download" in provided:
        value = provided["allow_download"]
        columns["allow_download"] = 1 if value is None else (1 if value else 0)
    return columns


def _gallery_patch_columns(payload: GalleryIn) -> dict[str, Any]:
    """Map only the fields the client sent to `galleries` columns."""
    provided = payload.model_dump(exclude_unset=True)
    columns: dict[str, Any] = {}
    if "title" in provided:
        columns["title"] = str(provided["title"] or "")
    if "description" in provided:
        columns["description"] = str(provided["description"] or "")
    if "status" in provided:
        columns["status"] = str(provided["status"])
    if "featured" in provided:
        columns["featured"] = 1 if provided["featured"] else 0
    if "slug" in provided and str(provided["slug"] or "").strip():
        columns["slug"] = str(provided["slug"])
    if "cover_photo_id" in provided:
        columns["cover_photo_id"] = provided["cover_photo_id"]
    return columns


@router.get("/galleries", response_model=AdminGalleryListResponse)
def admin_galleries(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    q: str | None = Query(None, max_length=80),
    status: str | None = Query(None, max_length=20),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    owner_id = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_galleries(
            conn,
            admin=True,
            page=page,
            per_page=per_page,
            q=q,
            status=status,
            owner_id=owner_id,
        )
        items = [gallery_dict(conn, row, admin=True) for row in rows]
        counts_sql = "SELECT status, COUNT(*) AS n FROM galleries"
        counts_args: list[Any] = []
        if owner_id is not None:
            counts_sql += " WHERE owner_id = ?"
            counts_args.append(owner_id)
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


@router.get("/galleries/{gallery_id}", response_model=AdminGalleryDetail)
def admin_gallery(gallery_id: int, user: dict = Depends(require_staff)) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        authorize(user, row, "write")
        item = gallery_dict(conn, row, detail=True, admin=True)
    return item


@router.post("/galleries", status_code=201, response_model=AdminGalleryDetail)
def create_gallery(
    payload: GalleryIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    now = now_iso()
    with db() as conn:
        slug = _unique_gallery_slug(conn, payload.slug or payload.title)
        cur = conn.execute(
            """INSERT INTO galleries(title, slug, description, status, featured,
                                     cover_photo_id, owner_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


@router.put("/galleries/{gallery_id}", response_model=AdminGalleryDetail)
@router.patch("/galleries/{gallery_id}", response_model=AdminGalleryDetail)
def update_gallery(
    gallery_id: int,
    payload: GalleryIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    """Partial update: only fields present in the request body are written.

    `GalleryIn.title` stays required by the shared request model, so a true
    PATCH that omits the title still returns 422; a dedicated `GalleryPatchIn`
    (all fields optional) is the schema change the Lead would need to lift that.
    """
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        authorize(user, row, "write")
        columns = _gallery_patch_columns(payload)
        if "slug" in columns:
            columns["slug"] = _unique_gallery_slug(
                conn, str(columns["slug"] or row["slug"]), gallery_id=gallery_id
            )
        if "cover_photo_id" in columns:
            cover_id = columns["cover_photo_id"]
            if cover_id is not None:
                cover = conn.execute(
                    "SELECT 1 FROM photos WHERE id = ? AND gallery_id = ?",
                    (cover_id, gallery_id),
                ).fetchone()
                if not cover:
                    # Same behaviour as 2.x: a cover that is not part of the
                    # gallery silently clears instead of failing the update.
                    columns["cover_photo_id"] = None
        columns["updated_at"] = now_iso()
        _apply_columns(conn, "galleries", gallery_id, columns)
        fresh = _gallery_row_or_404(conn, gallery_id)
        item = gallery_dict(conn, fresh, detail=True, admin=True)
    return item


@router.delete("/galleries/{gallery_id}", response_model=GalleryDeleteResponse)
def delete_gallery(
    gallery_id: int,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        authorize(user, row, "write")
        conn.execute("DELETE FROM photos WHERE gallery_id = ?", (gallery_id,))
        conn.execute("DELETE FROM galleries WHERE id = ?", (gallery_id,))
    return {"ok": True, "deleted": gallery_id, "title": row["title"]}


@router.post(
    "/galleries/{gallery_id}/photos",
    status_code=201,
    response_model=GalleryPhotosAddedResponse,
)
def add_photos(
    gallery_id: int,
    payload: PhotoBatchIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        authorize(user, row, "write")
        media_rows = []
        for media_id in dict.fromkeys(payload.media_ids):
            media = conn.execute(
                "SELECT * FROM media WHERE id = ? AND mime LIKE 'image/%'", (media_id,)
            ).fetchone()
            if not media:
                continue
            authorize(user, media, "write")
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


@router.post("/galleries/{gallery_id}/reorder", response_model=GalleryReorderResponse)
def reorder_photos(
    gallery_id: int,
    payload: ReorderIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _gallery_row_or_404(conn, gallery_id)
        authorize(user, row, "write")
        existing = {int(item["id"]) for item in gallery_photo_rows(conn, gallery_id, public=False)}
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


@router.get("/photos", response_model=PhotoListResponse)
def admin_photos(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=120),
    gallery_id: int | None = None,
    q: str | None = Query(None, max_length=80),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    owner_id = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_photos(
            conn,
            admin=True,
            gallery_id=gallery_id,
            page=page,
            per_page=per_page,
            q=q,
            order="manual",
            owner_id=owner_id,
        )
        items = [photo_dict(row) for row in rows]
    return {"items": items, **pagination(page, per_page, total)}


@router.post("/photos", status_code=201, response_model=PhotoImage)
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
        authorize(user, media, "write")
        if payload.gallery_id is not None:
            authorize(user, _gallery_row_or_404(conn, payload.gallery_id), "write")
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


@router.put("/photos/{photo_id}", response_model=PhotoImage)
@router.patch("/photos/{photo_id}", response_model=PhotoImage)
def update_photo(
    photo_id: int,
    payload: PhotoUpdateIn,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    """Partial update: omitted fields are kept, explicit null clears.

    `gallery_id: null` is the documented way to remove a photo from its gallery;
    omitting `gallery_id` now keeps the photo where it is (the 2.x data bug).
    """
    with db() as conn:
        row = _get_photo(conn, photo_id)
        if not row:
            raise HTTPException(status_code=404, detail="照片不存在")
        authorize_photo(user, conn, row, "write")
        columns = _photo_patch_columns(payload)
        if columns.get("gallery_id") is not None and (columns["gallery_id"] != row["gallery_id"]):
            authorize(user, _gallery_row_or_404(conn, int(columns["gallery_id"])), "write")
        _apply_columns(conn, "photos", photo_id, columns)
        touch_gallery(conn, columns.get("gallery_id"))
        old_gallery_id = int(row["gallery_id"]) if row["gallery_id"] else None
        touch_gallery(conn, old_gallery_id)
        updated = _get_photo(conn, photo_id)
        item = photo_dict(updated) if updated else {}
    return item


@router.delete("/photos/{photo_id}", response_model=PhotoDeleteResponse)
def delete_photo(
    photo_id: int,
    user: dict = Depends(require_permission("gallery.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_photo(conn, photo_id)
        if not row:
            raise HTTPException(status_code=404, detail="照片不存在")
        authorize_photo(user, conn, row, "write")
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
