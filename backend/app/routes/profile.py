"""Admin profile API: view and update the signed-in member's own account."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..api.models import ProfileResponse, ProfileUpdateResponse
from ..avatars import clean_avatar_url
from ..db import db, now_iso
from ..deps import require_staff
from ..errors import ApiError
from ..schemas import ProfileIn
from ..security import hash_password, password_policy_error, verify_password

router = APIRouter(
    prefix="/admin",
    tags=["profile"],
    dependencies=[Depends(require_staff)],
)


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user: dict = Depends(require_staff)) -> dict[str, Any]:
    return {"user": user}


@router.put("/profile", response_model=ProfileUpdateResponse)
def update_profile(
    payload: ProfileIn, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row:
            raise ApiError(404, "resource.not_found", "用户不存在")
        if payload.new_password:
            if not verify_password(payload.current_password, row["password_hash"]):
                raise ApiError(
                    400,
                    "profile.current_password_invalid",
                    "当前密码不正确",
                    field="current_password",
                )
            problem = password_policy_error(payload.new_password, row["username"])
            if problem:
                raise ApiError(
                    400, "profile.password_weak", problem, field="new_password"
                )
            password_hash = hash_password(payload.new_password)
        else:
            password_hash = row["password_hash"]
        conn.execute(
            """UPDATE users SET display_name = ?, email = ?, bio = ?, avatar = ?,
                   password_hash = ?, updated_at = ? WHERE id = ?""",
            (
                payload.display_name,
                payload.email,
                payload.bio,
                payload.avatar,
                password_hash,
                now_iso(),
                user["id"],
            ),
        )
        updated = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    result = {
        "id": updated["id"],
        "username": updated["username"],
        "display_name": updated["display_name"],
        "email": updated["email"],
        "bio": updated["bio"],
        "avatar": clean_avatar_url(updated["avatar"]),
        "role": updated["role"],
    }
    return {"ok": True, "user": result}
