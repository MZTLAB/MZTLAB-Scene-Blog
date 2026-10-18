"""Setup, login, logout and the current-user endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from ..db import db, get_user_count, now_iso, save_settings
from ..deps import (
    clear_session_cookie,
    client_ip,
    get_session_user,
    require_staff,
    set_session_cookie,
    start_session,
    user_public,
)
from ..schemas import LoginIn, SetupIn
from ..security import (
    clear_login_failures,
    hash_password,
    logger,
    login_account_limiter,
    login_backoff_seconds,
    login_ip_limiter,
    login_pair_limiter,
    verify_password,
)

router = APIRouter(tags=["auth"])


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    user = get_session_user(request)
    return {
        "authenticated": bool(user),
        "user": user,
        "needs_setup": get_user_count() == 0,
    }


@router.post("/setup")
def setup(payload: SetupIn, request: Request, response: Response) -> dict:
    if get_user_count() > 0:
        raise HTTPException(status_code=409, detail="站点已经完成初始化")
    now = now_iso()
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="站点已经完成初始化")
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, display_name, email,
                                 bio, avatar, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, '', '', '', 'admin', 1, ?, ?)""",
            (payload.username, hash_password(payload.password), payload.display_name, now, now),
        )
        user_id = int(cur.lastrowid)
        token, _ = start_session(conn, request, user_id)
        # Give seeded content an author / owner so signatures and ownership
        # checks look complete from the first visit.
        conn.execute("UPDATE posts SET author_id = ? WHERE author_id IS NULL", (user_id,))
        conn.execute("UPDATE galleries SET author_id = ? WHERE author_id IS NULL", (user_id,))
        conn.execute(
            "UPDATE media SET uploaded_by = ?, owner_id = ? "
            "WHERE uploaded_by IS NULL AND owner_id IS NULL",
            (user_id, user_id),
        )
    patch = {
        "site_title": payload.site_title,
        "author_name": payload.display_name,
    }
    if payload.site_description:
        patch["description"] = payload.site_description
        patch["seo_description"] = payload.site_description
    save_settings(patch)
    set_session_cookie(response, token)
    return {"ok": True, "redirect": "/admin"}


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    username = payload.username.strip().lower()
    pair = f"{ip}|{username}"

    # Hard limits: a single source cannot keep guessing, and neither can a
    # single source against one account. The per-account limiter below is a
    # high-ceiling throttle so an attacker cannot cheaply lock out the real
    # administrator from other addresses.
    if login_ip_limiter.is_blocked(ip):
        logger.warning("login rate limited by ip: %s", ip)
        raise HTTPException(status_code=429, detail="尝试次数过多，请五分钟后再试")
    if login_pair_limiter.is_blocked(pair):
        logger.warning("login rate limited by ip/account pair: %s", pair)
        raise HTTPException(status_code=429, detail="尝试次数过多，请五分钟后再试")
    if login_account_limiter.is_blocked(username):
        logger.warning("login rate limited by account: %s", username)
        raise HTTPException(status_code=429, detail="该账号尝试次数过多，请稍后再试")

    # Progressive delay for repeated failures against the same account.
    failures = login_account_limiter.count(username)
    delay = login_backoff_seconds(failures)
    if delay:
        time.sleep(delay)

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            login_pair_limiter.record(pair)
            login_ip_limiter.record(ip)
            login_account_limiter.record(username)
            logger.warning("failed login for %r from %s", username, ip)
            raise HTTPException(status_code=401, detail="用户名或密码不正确")
        if not row["is_active"]:
            logger.warning("login for disabled account %r from %s", username, ip)
            raise HTTPException(status_code=403, detail="该账号已被停用，请联系管理员")
        token, _ = start_session(conn, request, int(row["id"]))
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), int(row["id"]))
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(row["id"]),)).fetchone()
        user = user_public(conn, row)
    clear_login_failures(ip, username)
    set_session_cookie(response, token)
    return {"ok": True, "user": user, "redirect": "/admin"}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    from ..config import SESSION_COOKIE
    from ..security import token_fingerprint

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_fingerprint(token),))
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict:
    user = require_staff(request)
    return {"user": user}
