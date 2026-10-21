"""3.x backup import (restore) service.

The export format is the exact database shape plus the full grouped settings
document (see `app/routes/export.py`). Restore is deliberately conservative:

* the document is validated completely - including every cross-table reference
  and the settings model - **before** a single row is deleted;
* the replacement then runs in one short transaction with explicit ids and no
  storage I/O (SQLite holds a single writer lock);
* media binaries are not part of the JSON. After the commit, each media file is
  checked through the configured storage backend and missing names are reported
  without failing the import;
* `sessions` and `schema_meta` are never imported/exported. SQLite cascades the
  session rows of replaced users, so clients must sign in again after a restore.

There is no 2.x import path: `format` must be `mztlab-scene-export` and
`version` must be `3`.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import suppress
from typing import Any

from pydantic import ValidationError

from ..db import db, now_iso
from ..errors import ApiError
from ..settings import GROUPS, invalidate_settings_cache
from ..settings.models import Settings
from ..storage import get_storage, reset_storage

EXPORT_FORMAT = "mztlab-scene-export"
EXPORT_VERSION = 3

# Insert column order for every table in the v3 backup document. These mirror
# `backend/migrations/0001_init.sql` + `0002_artifact_tokens.sql` exactly.
USERS_COLUMNS: tuple[str, ...] = (
    "id", "username", "password_hash", "display_name", "email", "bio", "avatar",
    "role", "is_active", "last_login_at", "created_at", "updated_at",
)
POSTS_COLUMNS: tuple[str, ...] = (
    "id", "type", "title", "slug", "excerpt", "content_md", "content_html",
    "render_version", "cover_image", "status", "published_at", "featured",
    "owner_id", "seo_title", "seo_description", "reading_time", "toc_json",
    "created_at", "updated_at",
)
PROJECT_DETAILS_COLUMNS: tuple[str, ...] = (
    "post_id", "kind", "year", "role", "client", "url",
)
TAXONOMY_TERMS_COLUMNS: tuple[str, ...] = (
    "id", "kind", "name", "slug", "description", "created_at",
)
POST_TERMS_COLUMNS: tuple[str, ...] = ("post_id", "term_id")
REVISIONS_COLUMNS: tuple[str, ...] = (
    "id", "post_id", "title", "excerpt", "content_md", "owner_id", "created_at",
)
# `cover_photo_id` is restored after the photos exist (galleries and photos
# reference each other), so it is not part of the initial insert.
GALLERIES_COLUMNS: tuple[str, ...] = (
    "id", "title", "slug", "description", "status", "featured",
    "owner_id", "created_at", "updated_at",
)
PHOTOS_COLUMNS: tuple[str, ...] = (
    "id", "gallery_id", "media_id", "filename", "title", "caption", "location",
    "camera", "lens", "taken_at", "width", "height", "exif_fields",
    "hide_download_link", "featured", "status", "sort_order", "created_at",
)
MEDIA_COLUMNS: tuple[str, ...] = (
    "id", "filename", "original_name", "mime", "size", "width", "height", "alt",
    "owner_id", "exif", "source_sha1", "derivative_set", "placeholder",
    "created_at",
)
MEDIA_DERIVATIVES_COLUMNS: tuple[str, ...] = (
    "id", "media_id", "token", "pipeline_version", "scene", "width", "format",
    "quality", "height", "size", "key", "created_at",
)

_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": USERS_COLUMNS,
    "posts": POSTS_COLUMNS,
    "project_details": PROJECT_DETAILS_COLUMNS,
    "taxonomy_terms": TAXONOMY_TERMS_COLUMNS,
    "post_terms": POST_TERMS_COLUMNS,
    "revisions": REVISIONS_COLUMNS,
    "galleries": GALLERIES_COLUMNS,
    "photos": PHOTOS_COLUMNS,
    "media": MEDIA_COLUMNS,
    "media_derivatives": MEDIA_DERIVATIVES_COLUMNS,
}

# Every table the v3 document must carry (settings is handled separately).
_TABLE_KEYS: tuple[str, ...] = (
    "users", "posts", "project_details", "taxonomy_terms", "post_terms",
    "revisions", "galleries", "photos", "media", "media_derivatives",
)

# FK-safe delete order for a connection with `PRAGMA foreign_keys = ON`.
_DELETE_ORDER: tuple[str, ...] = (
    "media_derivatives",
    "photos",
    "galleries",
    "project_details",
    "post_terms",
    "revisions",
    "posts",
    "taxonomy_terms",
    "media",
    "users",
    "settings",
)

# AUTOINCREMENT sequences that belong to the replaced tables.
_SEQUENCE_TABLES: tuple[str, ...] = (
    "users", "posts", "revisions", "taxonomy_terms", "galleries", "photos",
    "media", "media_derivatives",
)

POST_TYPES = frozenset({"post", "project", "page"})
POST_STATUSES = frozenset({"draft", "published", "scheduled"})
TERM_KINDS = frozenset({"category", "tag"})


# ---------------------------------------------------------------------------
# Document parsing / validation (no writes)
# ---------------------------------------------------------------------------


def _rows(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list):
        raise ApiError(
            422,
            "import.invalid_document",
            f"备份缺少 {key} 数组",
            field=key,
        )
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(
                422,
                "import.invalid_document",
                f"{key} 的每一项都必须是对象",
                field=key,
            )
        rows.append(dict(item))
    return rows


def _require_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(
            422, "import.invalid_document", f"{label} 必须是整数", field=label
        )
    return value


def _id_set(rows: list[dict[str, Any]], key: str, label: str) -> set[int]:
    seen: set[int] = set()
    for row in rows:
        value = _require_int(row.get(key), label)
        if value in seen:
            raise ApiError(
                409,
                "import.duplicate_id",
                f"{label} 中存在重复 id {value}",
                field=label,
            )
        seen.add(value)
    return seen


def _check_reference(
    value: Any, allowed: set[int], label: str, *, required: bool = False
) -> None:
    if value is None:
        if required:
            raise ApiError(
                422, "import.invalid_reference", f"{label} 不能为空", field=label
            )
        return
    reference = _require_int(value, label)
    if reference not in allowed:
        raise ApiError(
            422,
            "import.invalid_reference",
            f"{label} 引用了不存在的 id {reference}",
            field=label,
        )


def _check_unique_rows(
    rows: list[dict[str, Any]], keys: tuple[str, ...], label: str
) -> None:
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        value = tuple(row.get(key) for key in keys)
        if value in seen:
            raise ApiError(
                409,
                "import.duplicate_row",
                f"{label} 中存在重复记录 {value}",
                field=label,
            )
        seen.add(value)


def _validate_settings(document: dict[str, Any]) -> dict[str, Any]:
    settings = document.get("settings")
    if not isinstance(settings, dict):
        raise ApiError(
            422, "import.settings_invalid", "备份缺少完整的 settings 文档", field="settings"
        )
    try:
        Settings.model_validate(settings)
    except ValidationError as exc:
        errors = exc.errors()
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first["loc"])
            message = str(first["msg"])
            if location:
                message = f"{message} ({location})"
        else:
            message = "settings 校验失败"
        raise ApiError(422, "import.settings_invalid", message, field="settings") from exc
    return dict(settings)


def validate_document(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Validate envelope, settings and every cross-table reference.

    Returns the parsed table rows so the caller does not have to parse twice.
    Raises `ApiError` before any data is touched.
    """
    if document.get("format") != EXPORT_FORMAT:
        raise ApiError(
            409,
            "import.format_unsupported",
            "不支持的备份格式，仅支持 mztlab-scene-export",
            field="format",
        )
    if document.get("version") != EXPORT_VERSION:
        raise ApiError(
            409,
            "import.version_unsupported",
            f"不支持的备份版本，仅支持 version={EXPORT_VERSION}",
            field="version",
        )
    _validate_settings(document)

    rows = {key: _rows(document, key) for key in _TABLE_KEYS}

    user_ids = _id_set(rows["users"], "id", "users")
    if not user_ids:
        raise ApiError(422, "import.no_users", "备份中没有用户，拒绝导入")
    post_ids = _id_set(rows["posts"], "id", "posts")
    term_ids = _id_set(rows["taxonomy_terms"], "id", "taxonomy_terms")
    gallery_ids = _id_set(rows["galleries"], "id", "galleries")
    photo_ids = _id_set(rows["photos"], "id", "photos")
    media_ids = _id_set(rows["media"], "id", "media")
    _id_set(rows["media_derivatives"], "id", "media_derivatives")

    for row in rows["users"]:
        if row.get("role") not in {"admin", "editor", "author"}:
            raise ApiError(
                422, "import.invalid_document", "用户角色不合法", field="users"
            )
    for row in rows["posts"]:
        if row.get("type") not in POST_TYPES:
            raise ApiError(
                422, "import.invalid_document", "内容类型不合法", field="posts"
            )
        if row.get("status") not in POST_STATUSES:
            raise ApiError(
                422, "import.invalid_document", "内容状态不合法", field="posts"
            )
        _check_reference(row.get("owner_id"), user_ids, "posts.owner_id", required=True)
    _check_unique_rows(rows["posts"], ("type", "slug"), "posts")
    _check_unique_rows(rows["users"], ("username",), "users")
    _check_unique_rows(rows["taxonomy_terms"], ("kind", "slug"), "taxonomy_terms")
    _check_unique_rows(rows["galleries"], ("slug",), "galleries")
    _check_unique_rows(rows["media"], ("filename",), "media")

    for row in rows["taxonomy_terms"]:
        if row.get("kind") not in TERM_KINDS:
            raise ApiError(
                422, "import.invalid_document", "分类类型不合法", field="taxonomy_terms"
            )
    for row in rows["project_details"]:
        _check_reference(
            row.get("post_id"), post_ids, "project_details.post_id", required=True
        )
    for row in rows["post_terms"]:
        _check_reference(
            row.get("post_id"), post_ids, "post_terms.post_id", required=True
        )
        _check_reference(
            row.get("term_id"), term_ids, "post_terms.term_id", required=True
        )
    for row in rows["revisions"]:
        _check_reference(
            row.get("post_id"), post_ids, "revisions.post_id", required=True
        )
        _check_reference(row.get("owner_id"), user_ids, "revisions.owner_id")
    for row in rows["galleries"]:
        _check_reference(
            row.get("owner_id"), user_ids, "galleries.owner_id", required=True
        )
        _check_reference(
            row.get("cover_photo_id"), photo_ids, "galleries.cover_photo_id"
        )
    for row in rows["media"]:
        _check_reference(
            row.get("owner_id"), user_ids, "media.owner_id", required=True
        )
    for row in rows["photos"]:
        _check_reference(row.get("gallery_id"), gallery_ids, "photos.gallery_id")
        _check_reference(row.get("media_id"), media_ids, "photos.media_id")
    for row in rows["media_derivatives"]:
        _check_reference(
            row.get("media_id"), media_ids, "media_derivatives.media_id", required=True
        )
    return rows


# ---------------------------------------------------------------------------
# Write transaction
# ---------------------------------------------------------------------------


def _delete_all(conn: sqlite3.Connection) -> None:
    for table in _DELETE_ORDER:
        conn.execute(f'DELETE FROM "{table}"')


def _reset_sequences(conn: sqlite3.Connection) -> None:
    placeholders = ", ".join("?" for _ in _SEQUENCE_TABLES)
    with suppress(sqlite3.OperationalError):
        # `sqlite_sequence` only exists once an AUTOINCREMENT table has rows.
        conn.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
            list(_SEQUENCE_TABLES),
        )


def _insert_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    sql = f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders})'
    conn.executemany(sql, ([row.get(column) for column in columns] for row in rows))


def _replace_settings(conn: sqlite3.Connection, settings_document: dict[str, Any]) -> None:
    """Replace all five settings groups atomically inside the import transaction.

    `app.settings.store` exposes `save_settings_patch()` (merge semantics) but no
    "replace the whole document" API, so the validated document is written with
    the same upsert statement `seed_default_settings` uses. Reported as a store
    gap: a future `replace_settings()` helper would belong in the store module.
    """
    candidate = Settings.model_validate(settings_document)
    conn.execute("DELETE FROM settings")
    now = now_iso()
    for group in GROUPS:
        document = getattr(candidate, group).model_dump()
        conn.execute(
            'INSERT INTO settings("group", data, updated_at) VALUES (?, ?, ?)',
            (group, json.dumps(document, ensure_ascii=False), now),
        )


def _insert_all(
    conn: sqlite3.Connection, rows: dict[str, list[dict[str, Any]]],
    settings_document: dict[str, Any],
) -> None:
    _insert_rows(conn, "users", USERS_COLUMNS, rows["users"])
    _replace_settings(conn, settings_document)
    _insert_rows(conn, "taxonomy_terms", TAXONOMY_TERMS_COLUMNS, rows["taxonomy_terms"])
    _insert_rows(conn, "posts", POSTS_COLUMNS, rows["posts"])
    _insert_rows(
        conn, "project_details", PROJECT_DETAILS_COLUMNS, rows["project_details"]
    )
    _insert_rows(conn, "post_terms", POST_TERMS_COLUMNS, rows["post_terms"])
    _insert_rows(conn, "revisions", REVISIONS_COLUMNS, rows["revisions"])
    _insert_rows(conn, "galleries", GALLERIES_COLUMNS, rows["galleries"])
    _insert_rows(conn, "media", MEDIA_COLUMNS, rows["media"])
    _insert_rows(conn, "photos", PHOTOS_COLUMNS, rows["photos"])
    _insert_rows(
        conn, "media_derivatives", MEDIA_DERIVATIVES_COLUMNS, rows["media_derivatives"]
    )
    # `galleries.cover_photo_id` references `photos(id)`, so the cover pointer is
    # restored after the photos exist (the column is nullable in the meantime).
    for row in rows["galleries"]:
        cover_photo_id = row.get("cover_photo_id")
        if cover_photo_id is not None:
            conn.execute(
                "UPDATE galleries SET cover_photo_id = ? WHERE id = ?",
                (cover_photo_id, row.get("id")),
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _missing_media_files(media_rows: list[dict[str, Any]]) -> list[str]:
    """Check media binaries after the commit; a missing file never aborts restore."""
    try:
        storage = get_storage()
    except Exception:
        return [str(row.get("filename") or "") for row in media_rows]
    missing: list[str] = []
    for row in media_rows:
        filename = str(row.get("filename") or "")
        if not filename:
            continue
        try:
            present = storage.exists(filename)
        except Exception:
            present = False
        if not present:
            missing.append(filename)
    return missing


def import_document(document: dict[str, Any]) -> dict[str, Any]:
    """Replace the whole site with a validated v3 backup document.

    Returns `{"ok": True, "imported": {table: count}, "missing_media_files": [...]}`.
    """
    rows = validate_document(document)
    settings_document = dict(document["settings"])
    try:
        with db() as conn:
            _delete_all(conn)
            _reset_sequences(conn)
            _insert_all(conn, rows, settings_document)
    except sqlite3.IntegrityError as exc:
        raise ApiError(
            422, "import.constraint_failed", f"导入数据违反数据库约束：{exc}"
        ) from exc

    # The settings cache and the cached storage backend now describe the old
    # site; rebuild both before the post-commit storage check.
    invalidate_settings_cache()
    reset_storage()

    imported = {key: len(value) for key, value in rows.items()}
    imported["settings"] = len(GROUPS)
    return {
        "ok": True,
        "imported": imported,
        "missing_media_files": _missing_media_files(rows["media"]),
    }
