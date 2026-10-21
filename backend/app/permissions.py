"""Roles and permission keys.

The role → permission matrix is defined here and nowhere else. The frontend no
longer mirrors it: `/api/auth/me` returns the effective `permissions` list for
the session and the admin UI only checks membership.

Ownership rules live in `app.services.authz`, not here.
"""

from __future__ import annotations

from typing import Any, Iterable

PERMISSIONS: dict[str, str] = {
    "content.read": "查看后台内容",
    "content.write": "创建与编辑内容",
    "content.publish": "发布与定时发布",
    "content.delete": "删除内容",
    "content.others": "管理他人内容",
    "media.manage": "管理媒体库",
    "gallery.manage": "管理影像画廊",
    "taxonomy.manage": "管理分类与标签",
    "settings.manage": "修改站点设置与外观",
    "users.manage": "管理用户与权限",
    "data.export": "导出站点数据",
}

ROLE_ORDER = ("admin", "editor", "author")

ROLE_LABELS: dict[str, str] = {
    "admin": "管理员",
    "editor": "编辑",
    "author": "作者",
}

ROLE_SUMMARIES: dict[str, str] = {
    "admin": "拥有全部权限，包括成员、权限与站点设置。",
    "editor": "查看并管理所有人的文章、媒体与相册；可在设置里收紧为只管自己的内容。",
    "author": "撰写文章，管理自己的相册与媒体。",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(PERMISSIONS),
    "editor": frozenset(
        {
            "content.read",
            "content.write",
            "content.publish",
            "content.delete",
            "media.manage",
            "gallery.manage",
            "taxonomy.manage",
            "data.export",
        }
    ),
    "author": frozenset(
        {
            "content.read",
            "content.write",
            "content.publish",
            "media.manage",
            "gallery.manage",
        }
    ),
}


def normalize_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    return value if value in ROLE_PERMISSIONS else "author"


def permissions_for(role: Any) -> list[str]:
    return sorted(ROLE_PERMISSIONS[normalize_role(role)])


def effective_permissions(role: Any, *, manage_others: bool = False) -> list[str]:
    """Permissions for a session, widening editors to all content when enabled.

    `manage_others` comes from the settings document
    `site.editor_manage_others`. Admins already own `content.others`; authors
    never gain it.
    """
    normalized = normalize_role(role)
    granted = set(ROLE_PERMISSIONS[normalized])
    if manage_others and normalized in {"admin", "editor"}:
        granted.add("content.others")
    return sorted(granted)


def can(user: dict[str, Any] | None, permission: str) -> bool:
    """Check one permission against a session's effective permission list.

    A session always carries `permissions` (see `deps.user_public`); there is no
    role-dict fallback, so a bug cannot silently grant permissions from a role
    name alone.
    """
    if not user:
        return False
    if user.get("is_active") is False:
        return False
    granted = user.get("permissions")
    if not isinstance(granted, (list, tuple, set, frozenset)):
        return False
    return permission in granted


def can_any(user: dict[str, Any] | None, permissions: Iterable[str]) -> bool:
    return any(can(user, permission) for permission in permissions)


def is_staff(user: dict[str, Any] | None) -> bool:
    return can(user, "content.read")


def role_meta() -> list[dict[str, Any]]:
    """Shape consumed by the member management screen."""
    return [
        {
            "key": role,
            "label": ROLE_LABELS[role],
            "summary": ROLE_SUMMARIES[role],
            "permissions": sorted(ROLE_PERMISSIONS[role]),
        }
        for role in ROLE_ORDER
    ]


def permission_meta() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in PERMISSIONS.items()]
