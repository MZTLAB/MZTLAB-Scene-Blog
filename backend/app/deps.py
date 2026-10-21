"""Authentication dependencies, permission gates and cookie helpers."""

from __future__ import annotations

import ipaddress
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, Response, status

from .avatars import clean_avatar_url
from .config import COOKIE_SECURE, SESSION_COOKIE, SESSION_DAYS
from .db import db, now_iso
from .permissions import (
    ROLE_LABELS,
    can,
    effective_permissions,
    is_staff,
    normalize_role,
)
from .security import new_session_token, session_expiry, token_fingerprint
from .settings import load_settings_cached


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """Resolve the browser address from uvicorn's trusted-proxy rewriting.

    The backend is started with `--proxy-headers --forwarded-allow-ips=<ingress>`,
    so uvicorn itself ignores a client-supplied `X-Forwarded-For` and only
    rewrites `request.client` for a trusted peer (the operator nginx, or the
    local dev proxy). There is no app-level secret to leak or forge.
    """
    peer = request.client.host if request.client else "unknown"
    return _valid_ip(peer) or peer


def user_public(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Shape a user row for the session, including effective permissions.

    The permission list is computed per request so toggling
    `site.editor_manage_others` in 设置 applies to the next request without
    forcing everyone to sign in again.
    """
    role = normalize_role(row["role"])
    manage_others = load_settings_cached().site.editor_manage_others
    permissions = effective_permissions(role, manage_others=manage_others)
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
        # sqlite3.Row is not a dict; `.keys()` is its membership API.
        "last_login_at": row["last_login_at"] if "last_login_at" in row.keys() else "",  # noqa: SIM118
        "permissions": permissions,
        "can_manage_others": "content.others" in permissions,
        "created_at": row["created_at"],
    }


def get_session_user(request: Request) -> dict[str, Any] | None:
    """Resolve the session cookie to a user without writing to the database.

    Reads never update `sessions` in 3.0.0: the previous "touch user_agent on
    every request" turned every admin GET into a write transaction competing
    for SQLite's single write lock. `user_agent`/`ip` are recorded at login
    only; expired rows are purged at startup and on login.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            """SELECT u.*, s.id AS session_id, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1""",
            (token_fingerprint(token), now_iso()),
        ).fetchone()
        if not row:
            return None
        return user_public(conn, row)


def require_staff(request: Request) -> dict[str, Any]:
    """Any signed-in member of the team."""
    user = get_session_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    if not is_staff(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有访问后台的权限")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    """Backwards-compatible alias: a signed-in member of the team."""
    return require_staff(request)


def require_permission(permission: str) -> Callable[[Request], dict[str, Any]]:
    """Build a dependency that enforces one permission key."""

    def dependency(request: Request) -> dict[str, Any]:
        user = require_staff(request)
        if not can(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前角色没有这项权限",
            )
        return user

    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency


def require_any_permission(*permissions: str) -> Callable[[Request], dict[str, Any]]:
    def dependency(request: Request) -> dict[str, Any]:
        user = require_staff(request)
        if not any(can(user, permission) for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前角色没有这项权限",
            )
        return user

    return dependency


def start_session(
    conn: sqlite3.Connection, request: Request, user_id: int
) -> tuple[str, str]:
    token = new_session_token()
    expires = session_expiry().isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, user_agent, ip) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            token_fingerprint(token),
            user_id,
            now_iso(),
            expires,
            request.headers.get("user-agent", "")[:300],
            client_ip(request),
        ),
    )
    return token, expires


def revoke_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
