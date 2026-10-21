"""Team management: list, invite, change role, deactivate, delete.

Every mutation is behind `users.manage`. Three rules keep the site from
locking itself out: you cannot demote or disable yourself, the last active
administrator can never be demoted, disabled or deleted, and changing a
password (or disabling an account) revokes that person's sessions.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..avatars import clean_avatar_url
from ..db import db, now_iso, setting_flag
from ..deps import require_permission, require_staff, revoke_user_sessions
from ..permissions import (
    ROLE_LABELS,
    can,
    effective_permissions,
    normalize_role,
    permission_meta,
    role_meta,
)
from ..schemas import UserCreateIn, UserUpdateIn
from ..security import hash_password, password_policy_error

router = APIRouter(prefix="/admin", tags=["users"], dependencies=[Depends(require_staff)])


def _active_admin_count(conn: sqlite3.Connection, excluding: int | None = None) -> int:
    sql = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    args: list[Any] = []
    if excluding is not None:
        sql += " AND id != ?"
        args.append(excluding)
    return int(conn.execute(sql, args).fetchone()[0])


def _serialize(
    row: sqlite3.Row,
    counts: dict[str, int] | None = None,
    *,
    manage_others: bool = False,
) -> dict[str, Any]:
    role = normalize_role(row["role"])
    counts = counts or {}
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "email": row["email"],
        "bio": row["bio"],
        "avatar": clean_avatar_url(row["avatar"]),
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "is_active": bool(row["is_active"]),
        "last_login_at": row["last_login_at"] or "",
        "created_at": row["created_at"],
        "permissions": effective_permissions(role, manage_others=manage_others),
        "content_count": counts.get("content_count", 0),
        "gallery_count": counts.get("gallery_count", 0),
        "media_count": counts.get("media_count", 0),
    }


@router.get("/users/meta")
def users_meta(user: dict = Depends(require_permission("users.manage"))) -> dict[str, Any]:
    return {
        "roles": role_meta(),
        "permissions": permission_meta(),
        "role_labels": ROLE_LABELS,
    }


@router.get("/users")
def list_users(
    q: str | None = Query(None, max_length=80),
    role: str | None = Query(None, max_length=20),
    user: dict = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    where: list[str] = []
    args: list[Any] = []
    if q:
        needle = f"%{q.strip()}%"
        where.append("(username LIKE ? OR display_name LIKE ? OR email LIKE ?)")
        args.extend([needle, needle, needle])
    if role in ROLE_LABELS:
        where.append("role = ?")
        args.append(role)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with db() as conn:
        rows = list(
            conn.execute(
                f"""SELECT * FROM users{clause}
                    ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                             is_active DESC, created_at ASC""",
                args,
            )
        )
        content_counts = {
            row["author_id"]: int(row["n"])
            for row in conn.execute(
                "SELECT author_id, COUNT(*) AS n FROM posts WHERE author_id IS NOT NULL GROUP BY author_id"
            )
        }
        gallery_counts = {
            row["author_id"]: int(row["n"])
            for row in conn.execute(
                "SELECT author_id, COUNT(*) AS n FROM galleries WHERE author_id IS NOT NULL GROUP BY author_id"
            )
        }
        media_counts = {
            row[0]: int(row[1])
            for row in conn.execute(
                "SELECT COALESCE(owner_id, uploaded_by), COUNT(*) "
                "FROM media WHERE COALESCE(owner_id, uploaded_by) IS NOT NULL "
                "GROUP BY COALESCE(owner_id, uploaded_by)"
            )
        }
        manage_others = setting_flag(conn, "editor_manage_others", True)
    items = [
        _serialize(
            row,
            {
                "content_count": content_counts.get(row["id"], 0),
                "gallery_count": gallery_counts.get(row["id"], 0),
                "media_count": media_counts.get(row["id"], 0),
            },
            manage_others=manage_others,
        )
        for row in rows
    ]
    # Counts describe the whole team, not the current filter, so the tabs stay
    # stable while searching or filtering by role.
    with db() as conn:
        counts = {role: 0 for role in ROLE_LABELS}
        for row in conn.execute("SELECT role, COUNT(*) AS n FROM users GROUP BY role"):
            counts[normalize_role(row["role"])] = int(row["n"])
    return {"items": items, "total": len(items), "counts": counts}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreateIn,
    actor: dict = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    now = now_iso()
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (payload.username,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="用户名已被使用")
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, display_name, email, bio,
                                 avatar, role, is_active, last_login_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '', ?, 1, '', ?, ?)""",
            (
                payload.username,
                hash_password(payload.password),
                payload.display_name,
                payload.email,
                payload.bio,
                normalize_role(payload.role),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        manage_others = setting_flag(conn, "editor_manage_others", True)
    return {"ok": True, "user": _serialize(row, manage_others=manage_others)}


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    actor: dict = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    role = normalize_role(payload.role)
    is_self = int(actor["id"]) == user_id
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        was_admin = row["role"] == "admin" and bool(row["is_active"])
        losing_admin = was_admin and (role != "admin" or not payload.is_active)
        if losing_admin and _active_admin_count(conn, excluding=user_id) == 0:
            raise HTTPException(status_code=409, detail="至少需要保留一名启用中的管理员")

        if is_self and role != row["role"]:
            raise HTTPException(status_code=409, detail="不能修改自己的角色")
        if is_self and not payload.is_active:
            raise HTTPException(status_code=409, detail="不能停用自己的账号")

        password_hash = row["password_hash"]
        password_changed = bool(payload.password)
        if password_changed:
            problem = password_policy_error(payload.password, row["username"])
            if problem:
                raise HTTPException(status_code=400, detail=problem)
            password_hash = hash_password(payload.password)

        conn.execute(
            """UPDATE users SET display_name = ?, email = ?, bio = ?, role = ?,
                   is_active = ?, password_hash = ?, updated_at = ? WHERE id = ?""",
            (
                payload.display_name,
                payload.email,
                payload.bio,
                role,
                1 if payload.is_active else 0,
                password_hash,
                now_iso(),
                user_id,
            ),
        )
        if password_changed or not payload.is_active or role != row["role"]:
            revoke_user_sessions(conn, user_id)
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        manage_others = setting_flag(conn, "editor_manage_others", True)
    return {"ok": True, "user": _serialize(updated, manage_others=manage_others)}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    actor: dict = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    if int(actor["id"]) == user_id:
        raise HTTPException(status_code=409, detail="不能删除自己的账号")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        if row["role"] == "admin" and _active_admin_count(conn, excluding=user_id) == 0:
            raise HTTPException(status_code=409, detail="至少需要保留一名启用中的管理员")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True, "deleted": user_id, "username": row["username"]}


def can_manage_users(user: dict[str, Any]) -> bool:
    return can(user, "users.manage")
