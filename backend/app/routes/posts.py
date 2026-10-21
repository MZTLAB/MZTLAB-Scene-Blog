"""Admin API for articles (`type='post'`).

Publishing, ownership and rendering rules live in
`app.services.content_admin`; this module only wires HTTP concerns. Updates are
true PATCH requests: omitted fields keep their value, an explicit `null` clears.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..api.models import (
    AdminContentDetail,
    AdminContentItem,
    AdminContentListResponse,
    ContentAuthorsResponse,
    ContentDeleteResponse,
    PreviewResponse,
    RevisionListResponse,
)
from ..content import extract_toc, reading_time, render_markdown
from ..db import db
from ..deps import require_permission, require_staff
from ..errors import ApiError
from ..permissions import ROLE_LABELS, can
from ..posts import fetch_posts, get_post, pagination, serialize_post, serialize_posts
from ..schemas import PostIn, PostPatch, PreviewIn
from ..security import preview_limiter
from ..services.authz import authorize
from ..services.content_admin import (
    assert_can_publish,
    insert_content,
    page_counts,
    restore_revision,
    update_content,
)

router = APIRouter(
    prefix="/admin",
    tags=["posts"],
    dependencies=[Depends(require_staff)],
)

STATUS_FILTERS = frozenset({"draft", "published", "scheduled"})


def _row_or_404(conn: sqlite3.Connection, post_id: int) -> sqlite3.Row:
    row = get_post(conn, post_id=post_id, post_type="post")
    if not row:
        raise ApiError(404, "content.not_found", "文章不存在")
    return row


@router.get("/posts", response_model=AdminContentListResponse)
def admin_posts(
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    status_filter = status if status in STATUS_FILTERS else None
    # Authors only see their own shelf; editors/admins see everything.
    owner_filter = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_posts(
            conn,
            post_type="post",
            page=page,
            per_page=per_page,
            q=q,
            admin=True,
            status=status_filter,
            owner_id=owner_filter,
        )
        items = serialize_posts(conn, rows, admin=True)
        counts = page_counts(conn, "post", owner_id=owner_filter)
    return {"items": items, "counts": counts, **pagination(page, per_page, total)}


@router.get("/posts/{post_id}", response_model=AdminContentDetail)
def admin_post(
    post_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        authorize(user, row, "read")
        item = serialize_post(conn, row, detail=True, admin=True)
        item["revision_count"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM revisions WHERE post_id = ?", (post_id,)
            ).fetchone()[0]
        )
    return item


@router.post("/posts", status_code=201, response_model=AdminContentItem)
def create_post(
    payload: PostIn,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    assert_can_publish(user, payload.status)
    with db() as conn:
        post_id = insert_content(conn, "post", payload, user)
        row = _row_or_404(conn, post_id)
        item = serialize_post(conn, row, admin=True)
    return item


@router.patch("/posts/{post_id}", response_model=AdminContentItem)
def update_post(
    post_id: int,
    payload: PostPatch,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        authorize(user, row, "write")
        assert_can_publish(user, payload.status or str(row["status"]))
        update_content(conn, row, payload, user)
        fresh = _row_or_404(conn, post_id)
        item = serialize_post(conn, fresh, admin=True)
    return item


@router.delete("/posts/{post_id}", response_model=ContentDeleteResponse)
def delete_post(
    post_id: int, user: dict = Depends(require_permission("content.delete"))
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        authorize(user, row, "write")
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return {
        "ok": True,
        "deleted": post_id,
        "title": row["title"],
        "type": row["type"],
    }


@router.get("/posts/{post_id}/revisions", response_model=RevisionListResponse)
def revisions(
    post_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        authorize(user, row, "read")
        rows = conn.execute(
            """SELECT r.id, r.title, r.excerpt, r.created_at, r.content_md,
                      u.display_name AS author_name
               FROM revisions r LEFT JOIN users u ON u.id = r.owner_id
               WHERE r.post_id = ? ORDER BY r.id DESC LIMIT 25""",
            (post_id,),
        ).fetchall()
    items = []
    for revision in rows:
        item = dict(revision)
        item["reading_time"] = reading_time(item["content_md"])
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post(
    "/posts/{post_id}/revisions/{revision_id}/restore",
    response_model=AdminContentDetail,
)
def restore_post_revision(
    post_id: int,
    revision_id: int,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        revision = conn.execute(
            "SELECT * FROM revisions WHERE id = ? AND post_id = ?",
            (revision_id, post_id),
        ).fetchone()
        if not revision:
            raise ApiError(404, "content.revision_not_found", "版本不存在")
        authorize(user, row, "write")
        restore_revision(conn, row, revision, int(user["id"]))
        fresh = _row_or_404(conn, post_id)
        item = serialize_post(conn, fresh, detail=True, admin=True)
    return item


@router.get("/content-authors", response_model=ContentAuthorsResponse)
def content_authors(
    user: dict = Depends(require_permission("content.others")),
) -> dict[str, Any]:
    """Members who can own content, used by the editor's author selector."""
    with db() as conn:
        rows = conn.execute(
            """SELECT id, username, display_name, role, is_active FROM users
               ORDER BY is_active DESC,
                        CASE role WHEN 'admin' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                        display_name COLLATE NOCASE ASC"""
        ).fetchall()
    return {
        "items": [
            {
                "id": int(row["id"]),
                "username": row["username"],
                "name": row["display_name"],
                "role": row["role"],
                "role_label": ROLE_LABELS.get(row["role"], row["role"]),
                "is_active": bool(row["is_active"]),
            }
            for row in rows
        ]
    }


@router.post("/preview", response_model=PreviewResponse)
def preview(
    payload: PreviewIn,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    if not preview_limiter.allow(f"preview:{user['id']}"):
        raise ApiError(
            429,
            "rate_limit.exceeded",
            "预览刷新过于频繁，请稍后再试",
            headers={"Retry-After": "10"},
        )
    html = render_markdown(payload.content_md)
    return {
        "html": html,
        "toc": extract_toc(html),
        "reading_time": reading_time(payload.content_md),
    }
