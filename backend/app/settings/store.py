"""Grouped settings storage.

Each group is one JSON row in `settings`. Loading merges the stored document
over the model defaults, so a missing/older field never leaves a hole; saving
validates the merged document before writing, and the whole save happens in one
short transaction.

The cache is process-local and invalidated on save. 3.0.0 refuses to start with
more than one worker (see main.py), so the cache is authoritative for the
process lifetime; the small TTL only covers external edits made by scripts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from pydantic import ValidationError

from ..config import SITE_URL
from ..db import db, now_iso
from .models import Settings, SettingsPatch

logger = logging.getLogger("mztlab.settings")

GROUPS: tuple[str, ...] = ("site", "appearance", "copy", "upload", "advanced")

# Group name -> model attribute. Kept explicit so a typo fails loudly.
_DEFAULT_DOCS: dict[str, dict[str, Any]] = {
    group: getattr(Settings(), group).model_dump() for group in GROUPS
}

_CACHE: Settings | None = None
_CACHE_AT = 0.0
_CACHE_TTL = 3.0


def default_settings() -> Settings:
    return Settings()


def invalidate_settings_cache() -> None:
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


def _read_group(conn: sqlite3.Connection, group: str) -> dict[str, Any]:
    row = conn.execute(
        'SELECT data FROM settings WHERE "group" = ?', (group,)
    ).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("settings group %s holds invalid JSON; using defaults", group)
        return {}
    if not isinstance(value, dict):
        logger.warning("settings group %s is not an object; using defaults", group)
        return {}
    return value


def _filter_known(default: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """Drop stored keys the current models no longer know about.

    Settings documents evolve across 3.x releases; removed fields (for example
    the per-scene encoding quality after ADR-10) are ignored instead of making
    the whole group fail validation.
    """
    result: dict[str, Any] = {}
    for key, value in stored.items():
        if key not in default:
            continue
        base = default[key]
        if isinstance(base, dict) and isinstance(value, dict):
            result[key] = {**base, **_filter_known(base, value)}
        else:
            result[key] = value
    return result


def _load_from_conn(conn: sqlite3.Connection) -> Settings:
    documents: dict[str, Any] = {}
    for group in GROUPS:
        stored = _read_group(conn, group)
        documents[group] = {
            **_DEFAULT_DOCS[group],
            **_filter_known(_DEFAULT_DOCS[group], stored),
        }
    try:
        return Settings.model_validate(documents)
    except ValidationError as exc:
        # A hand-edited database must not take the site down. Fall back per
        # group so the rest of the configuration keeps working.
        logger.error("invalid stored settings (%s); falling back per group", exc)
        safe: dict[str, Any] = {}
        for group in GROUPS:
            try:
                safe[group] = getattr(
                    Settings.model_validate(documents), group
                ).model_dump()
            except ValidationError:
                safe[group] = dict(_DEFAULT_DOCS[group])
        return Settings.model_validate(safe)


def load_settings() -> Settings:
    with db() as conn:
        return _load_from_conn(conn)


def load_settings_cached(ttl: float = _CACHE_TTL) -> Settings:
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if _CACHE is not None and now - _CACHE_AT < ttl:
        return _CACHE
    _CACHE = load_settings()
    _CACHE_AT = now
    return _CACHE


def public_settings() -> dict[str, Any]:
    """Render-only projection handed to public pages."""
    return load_settings_cached().public_dump()


def seed_default_settings(conn: sqlite3.Connection) -> None:
    """Insert the five default documents on an empty database (idempotent)."""
    now = now_iso()
    site = dict(_DEFAULT_DOCS["site"])
    # BLOG_SITE_URL is a first-boot convenience for container deployments; it
    # only fills the default, so an URL edited in the admin is never clobbered.
    if SITE_URL and site.get("site_url") == _DEFAULT_DOCS["site"]["site_url"]:
        site["site_url"] = SITE_URL
    documents = {**_DEFAULT_DOCS, "site": site}
    for group in GROUPS:
        conn.execute(
            'INSERT OR IGNORE INTO settings("group", data, updated_at) VALUES (?, ?, ?)',
            (group, json.dumps(documents[group], ensure_ascii=False), now),
        )


def save_settings_patch(patch: SettingsPatch) -> Settings:
    provided = patch.provided()
    with db() as conn:
        current = _load_from_conn(conn).model_dump()
        for group, fields in provided.items():
            merged = {**current[group]}
            for key, value in fields.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            current[group] = merged
        # Validate the complete merged document before writing anything.
        candidate = Settings.model_validate(current)
        now = now_iso()
        for group in GROUPS:
            conn.execute(
                """INSERT INTO settings("group", data, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT("group") DO UPDATE SET data = excluded.data,
                                                     updated_at = excluded.updated_at""",
                (
                    group,
                    json.dumps(
                        candidate.model_dump()[group], ensure_ascii=False
                    ),
                    now,
                ),
            )
    invalidate_settings_cache()
    return candidate
