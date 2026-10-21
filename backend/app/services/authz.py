"""Single authorization entry point for resource ownership.

Before 3.0.0 the same rule was implemented three times (admin content, media,
galleries) with different messages and different lookup columns. Now:

    authorize(user, row, "write")      # raises ApiError(403) when not allowed

Ownership is a single `owner_id` column on every authorizable row
(`posts`, `galleries`, `media`); photos inherit their gallery's owner.
`content.others` (granted to admins, and to editors when the site policy
`editor_manage_others` is on) bypasses the ownership check.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..errors import ApiError
from ..permissions import can

ACTION_LABELS = {
    "read": "查看",
    "write": "编辑",
    "delete": "删除",
    "publish": "发布",
}


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def owner_id_of(row: Any) -> int | None:
    value = _row_value(row, "owner_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def owns(user: dict[str, Any] | None, row: Any) -> bool:
    if not user or row is None:
        return False
    owner_id = owner_id_of(row)
    if owner_id is None:
        return False
    try:
        return owner_id == int(user["id"])
    except (KeyError, TypeError, ValueError):
        return False


def authorize(user: dict[str, Any], row: Any, action: str = "write") -> None:
    """Allow owners and `content.others` holders; reject everyone else."""
    if row is None:
        raise ApiError(404, "resource.not_found", "资源不存在")
    if owns(user, row) or can(user, "content.others"):
        return
    label = ACTION_LABELS.get(action, "操作")
    raise ApiError(
        403,
        "auth.ownership_required",
        f"只能{label}自己创建的内容",
    )


def gallery_owner_id(conn: sqlite3.Connection, gallery_id: int | None) -> int | None:
    if gallery_id is None:
        return None
    row = conn.execute(
        "SELECT owner_id FROM galleries WHERE id = ?", (gallery_id,)
    ).fetchone()
    return owner_id_of(row)


def authorize_photo(
    user: dict[str, Any],
    conn: sqlite3.Connection,
    photo: Any,
    action: str = "write",
) -> None:
    """A photo is authorized through its gallery's owner (photos own nothing)."""
    if owns(user, photo) or can(user, "content.others"):
        return
    gallery_id = _row_value(photo, "gallery_id")
    if gallery_id is not None:
        owner = gallery_owner_id(conn, int(gallery_id))
        if owner is not None and owner == int(user["id"]):
            return
    label = ACTION_LABELS.get(action, "操作")
    raise ApiError(403, "auth.ownership_required", f"只能{label}自己相册中的照片")
