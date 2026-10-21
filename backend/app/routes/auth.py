"""Setup, login, logout and the current-user endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..api.models import (
    AuthStatusResponse,
    LoginResponse,
    OkResponse,
    ProfileResponse,
    SetupResponse,
)
from ..db import db, get_user_count, now_iso
from ..deps import (
    clear_session_cookie,
    client_ip,
    get_session_user,
    require_staff,
    set_session_cookie,
    start_session,
    user_public,
)
from ..errors import ApiError
from ..schemas import LoginIn, SetupIn
from ..security import (
    clear_login_failures,
    hash_password,
    logger,
    login_account_limiter,
    login_ip_limiter,
    login_pair_limiter,
    verify_password,
)
from ..settings import SettingsPatch, SiteSettingsPatch, save_settings_patch

router = APIRouter(tags=["auth"])


@router.get("/auth/status", response_model=AuthStatusResponse)
def auth_status(request: Request) -> dict:
    user = get_session_user(request)
    return {
        "authenticated": bool(user),
        "user": user,
        "needs_setup": get_user_count() == 0,
    }


@router.post("/setup", response_model=SetupResponse)
def setup(payload: SetupIn, request: Request, response: Response) -> dict:
    if get_user_count() > 0:
        raise ApiError(409, "setup.already_initialized", "站点已经完成初始化")
    now = now_iso()
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if exists:
            raise ApiError(409, "setup.already_initialized", "站点已经完成初始化")
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, display_name, email,
                                 bio, avatar, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, '', '', '', 'admin', 1, ?, ?)""",
            (
                payload.username,
                hash_password(payload.password),
                payload.display_name,
                now,
                now,
            ),
        )
        user_id = int(cur.lastrowid or 0)
        token, _ = start_session(conn, request, user_id)

    site_patch = SiteSettingsPatch(
        site_title=payload.site_title,
        description=payload.site_description or None,
        seo_description=payload.site_description or None,
    )
    save_settings_patch(SettingsPatch(site=site_patch))

    # Demo content is explicit opt-in and needs an owner, so it is seeded after
    # the first account exists.
    from ..seed import seed_demo_content

    seed_demo_content()

    set_session_cookie(response, token)
    return {"ok": True, "redirect": "/admin"}


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    username = payload.username.strip().lower()
    pair = f"{ip}|{username}"

    # Atomic check-and-consume: the old is_blocked()+record() pair allowed
    # concurrent attempts to slip past the limit between the two calls.
    for limiter, key, message in (
        (login_ip_limiter, ip, "尝试次数过多，请稍后再试"),
        (login_pair_limiter, pair, "尝试次数过多，请稍后再试"),
        (login_account_limiter, username, "该账号尝试次数过多，请稍后再试"),
    ):
        if not limiter.allow(key):
            retry_after = limiter.retry_after(key)
            logger.warning("login rate limited (%s)", key)
            raise ApiError(
                429,
                "rate_limit.exceeded",
                message,
                headers={"Retry-After": str(retry_after)},
            )

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            logger.warning("failed login for %r from %s", username, ip)
            raise ApiError(401, "auth.invalid_credentials", "用户名或密码不正确")
        if not row["is_active"]:
            logger.warning("login for disabled account %r from %s", username, ip)
            raise ApiError(403, "auth.account_disabled", "该账号已被停用，请联系管理员")
        token, _ = start_session(conn, request, int(row["id"]))
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now_iso(), int(row["id"])),
        )
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (int(row["id"]),)
        ).fetchone()
        user = user_public(conn, row)
    # Success clears the failure buckets so a legitimate sign-in does not carry
    # a growing penalty.
    clear_login_failures(ip, username)
    set_session_cookie(response, token)
    return {"ok": True, "user": user, "redirect": "/admin"}


@router.post("/auth/logout", response_model=OkResponse)
def logout(request: Request, response: Response) -> dict:
    from ..config import SESSION_COOKIE
    from ..security import token_fingerprint

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_fingerprint(token),),
            )
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me", response_model=ProfileResponse)
def me(request: Request) -> dict:
    user = require_staff(request)
    return {"user": user}
