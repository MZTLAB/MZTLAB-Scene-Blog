"""Roles, permissions and ownership rules.

The site supports several people writing under one roof. Instead of a hard
"admin or nothing" flag we describe a small set of permissions and map roles
onto them, so the same checks serve the API, the admin UI and the templates.

Roles:
    admin   — owns the site: content, people, settings, data.
    editor  — runs the desk: sees and manages all content, media and
              galleries, comments, taxonomy and exports. The owner can narrow
              this back to "own content only" in 设置 → 协作与权限.
    author  — writes: own articles / galleries and the media needed for them.

`content.others` is the switch that turns "my work" into "everyone's work".
It is never granted statically to editors: a session's permission list is
computed from the site setting `editor_manage_others` (default on), so the
same switch governs posts, media and galleries.
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
    "comment.moderate": "审核评论",
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
    "editor": "查看并管理所有人的文章、媒体与相册，负责评论与分类；可在设置里收紧为只管自己的内容。",
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
            "comment.moderate",
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
    """Permissions for a session, optionally widening editors to all content.

    `manage_others` comes from the site setting `editor_manage_others`. Admins
    already own `content.others`; authors never gain it.
    """
    normalized = normalize_role(role)
    granted = set(ROLE_PERMISSIONS[normalized])
    if manage_others and normalized in {"admin", "editor"}:
        granted.add("content.others")
    return sorted(granted)


def can(user: dict[str, Any] | None, permission: str) -> bool:
    if not user:
        return False
    if user.get("is_active") is False:
        return False
    # A signed-in session carries its effective permission list, which already
    # accounts for the `editor_manage_others` setting. Bare role dicts (tests,
    # one-off helpers) fall back to the static role table.
    granted = user.get("permissions")
    if isinstance(granted, (list, tuple, set, frozenset)):
        return permission in granted
    return permission in ROLE_PERMISSIONS[normalize_role(user.get("role"))]


def can_any(user: dict[str, Any] | None, permissions: Iterable[str]) -> bool:
    return any(can(user, permission) for permission in permissions)


def is_staff(user: dict[str, Any] | None) -> bool:
    return can(user, "content.read")


def _row_value(item: Any, key: str) -> Any:
    try:
        return item[key]
    except (KeyError, IndexError, TypeError):
        return None


def owns(user: dict[str, Any] | None, item: Any) -> bool:
    """True when `user` is the owner of a post, media file, gallery or photo.

    Posts and galleries use `author_id`; media uses `owner_id` with the legacy
    `uploaded_by` column as a fallback. Keeping the lookup in one place means
    every route enforces the same rule.
    """
    if not user or item is None:
        return False
    owner_id = None
    for key in ("author_id", "owner_id", "uploaded_by"):
        value = _row_value(item, key)
        if value is not None:
            owner_id = value
            break
    if owner_id is None:
        return False
    try:
        return int(owner_id) == int(user["id"])
    except (KeyError, TypeError, ValueError):
        return False


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
