"""Admin API for standalone pages (`type='page'`).

Pages share the posts table but own no taxonomy or project metadata; their
slugs additionally avoid the built-in frontend routes (`RESERVED_PAGE_SLUGS`).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..api.models import (
    AdminContentDetail,
    AdminContentItem,
    AdminContentListResponse,
    ContentDeleteResponse,
)
from ..db import db
from ..deps import require_permission, require_staff
from ..errors import ApiError
from ..permissions import can
from ..posts import fetch_posts, get_post, pagination, serialize_post, serialize_posts
from ..schemas import PageIn, PagePatch
from ..services.authz import authorize
from ..services.content_admin import (
    assert_can_publish,
    insert_content,
    page_counts,
    update_content,
)

router = APIRouter(
    prefix="/admin",
    tags=["pages"],
    dependencies=[Depends(require_staff)],
)

STATUS_FILTERS = frozenset({"draft", "published", "scheduled"})


def _row_or_404(conn: sqlite3.Connection, post_id: int) -> sqlite3.Row:
    row = get_post(conn, post_id=post_id, post_type="page")
    if not row:
        raise ApiError(404, "content.not_found", "页面不存在")
    return row


@router.get("/pages", response_model=AdminContentListResponse)
def admin_pages(
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    status_filter = status if status in STATUS_FILTERS else None
    owner_filter = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_posts(
            conn,
            post_type="page",
            page=page,
            per_page=per_page,
            q=q,
            admin=True,
            status=status_filter,
            owner_id=owner_filter,
        )
        items = serialize_posts(conn, rows, admin=True)
        counts = page_counts(conn, "page", owner_id=owner_filter)
    return {"items": items, "counts": counts, **pagination(page, per_page, total)}


@router.get("/pages/{post_id}", response_model=AdminContentDetail)
def admin_page(
    post_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = _row_or_404(conn, post_id)
        authorize(user, row, "read")
        item = serialize_post(conn, row, detail=True, admin=True)
    return item


@router.post("/pages", status_code=201, response_model=AdminContentItem)
def create_page(
    payload: PageIn,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    assert_can_publish(user, payload.status)
    with db() as conn:
        post_id = insert_content(conn, "page", payload, user)
        row = _row_or_404(conn, post_id)
        item = serialize_post(conn, row, admin=True)
    return item


@router.patch("/pages/{post_id}", response_model=AdminContentItem)
def update_page(
    post_id: int,
    payload: PagePatch,
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


@router.delete("/pages/{post_id}", response_model=ContentDeleteResponse)
def delete_page(
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
