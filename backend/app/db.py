"""SQLite access layer.

The blog is deliberately built on the Python standard library's sqlite3 so it
has no ORM to learn and no migration tool to install. Each request opens a
short-lived connection; WAL mode keeps readers and the occasional write from
blocking each other.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH
from .defaults import default_settings

SCHEMA_VERSION = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    email         TEXT NOT NULL DEFAULT '',
    bio           TEXT NOT NULL DEFAULT '',
    avatar        TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'author',
    is_active     INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    user_agent  TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS posts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    type              TEXT NOT NULL DEFAULT 'post',
    title             TEXT NOT NULL,
    slug              TEXT NOT NULL UNIQUE,
    excerpt           TEXT NOT NULL DEFAULT '',
    content_md        TEXT NOT NULL DEFAULT '',
    content_html      TEXT NOT NULL DEFAULT '',
    cover_image       TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'draft',
    featured          INTEGER NOT NULL DEFAULT 0,
    allow_comments    INTEGER NOT NULL DEFAULT 1,
    author_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    published_at      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    seo_title         TEXT NOT NULL DEFAULT '',
    seo_description   TEXT NOT NULL DEFAULT '',
    project_year      TEXT NOT NULL DEFAULT '',
    project_role      TEXT NOT NULL DEFAULT '',
    project_client    TEXT NOT NULL DEFAULT '',
    project_kind      TEXT NOT NULL DEFAULT '',   -- free-form project type
    project_url       TEXT NOT NULL DEFAULT '',
    view_count        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_posts_public
    ON posts(type, status, published_at);
CREATE INDEX IF NOT EXISTS idx_posts_updated ON posts(updated_at);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_categories (
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, category_id)
);

CREATE TABLE IF NOT EXISTS post_tags (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_name  TEXT NOT NULL,
    author_email TEXT NOT NULL DEFAULT '',
    author_url   TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    ip           TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, status, created_at);

CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime          TEXT NOT NULL,
    size          INTEGER NOT NULL,
    width         INTEGER NOT NULL DEFAULT 0,
    height        INTEGER NOT NULL DEFAULT 0,
    alt           TEXT NOT NULL DEFAULT '',
    uploaded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    owner_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    exif          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Scene galleries ---------------------------------------------------------
-- A gallery is a curated set ("相册") of photos. A photo always points at a
-- validated media row, but keeps a filename snapshot so a gallery stays
-- readable even if the library entry is removed later.

CREATE TABLE IF NOT EXISTS galleries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'draft',
    featured       INTEGER NOT NULL DEFAULT 0,
    cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    author_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    view_count     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_galleries_public ON galleries(status, featured, updated_at);

CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id INTEGER REFERENCES galleries(id) ON DELETE SET NULL,
    media_id   INTEGER REFERENCES media(id) ON DELETE CASCADE,
    filename   TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    caption    TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    camera     TEXT NOT NULL DEFAULT '',
    lens       TEXT NOT NULL DEFAULT '',
    taken_at   TEXT NOT NULL DEFAULT '',
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    exif_fields TEXT NOT NULL DEFAULT 'camera,lens,focal_length,aperture,exposure,iso,taken_at,dimensions',
    featured   INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'published',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_gallery ON photos(gallery_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status, featured, created_at);

CREATE TABLE IF NOT EXISTS revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    excerpt    TEXT NOT NULL,
    content_md TEXT NOT NULL,
    author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_post ON revisions(post_id, created_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def init_db() -> None:
    with db() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        if version < 3:
            _backfill_owners(conn)
            _backfill_media_exif(conn)
        _ensure_default_settings(conn)
        _migrate_scene(conn)
        _migrate_mono(conn)
        _migrate_scene_v22(conn)
        _migrate_project_kind_text(conn)
        _migrate_editor_manage_others(conn)
        _migrate_scene_wording(conn)
        _migrate_scene_demo_project(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    from .seed import ensure_bootstrap_admin, seed_demo_content  # avoid circular import

    seed_demo_content()
    ensure_bootstrap_admin()


# Columns added after the first release. `CREATE TABLE IF NOT EXISTS` does not
# touch an existing table, so upgrades need an explicit ALTER.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "last_login_at": "TEXT NOT NULL DEFAULT ''",
    },
    "posts": {
        "project_year": "TEXT NOT NULL DEFAULT ''",
        "project_role": "TEXT NOT NULL DEFAULT ''",
        "project_client": "TEXT NOT NULL DEFAULT ''",
        "project_kind": "TEXT NOT NULL DEFAULT ''",
        "project_url": "TEXT NOT NULL DEFAULT ''",
    },
    "photos": {
        "exif_fields": (
            "TEXT NOT NULL DEFAULT "
            "'camera,lens,focal_length,aperture,exposure,iso,taken_at,dimensions'"
        ),
    },
    "media": {
        "owner_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "exif": "TEXT NOT NULL DEFAULT ''",
    },
}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_owner ON media(owner_id, created_at)"
    )
    # Every start can safely mirror the legacy uploader column; this does not
    # invent an owner for genuinely orphaned content.
    conn.execute(
        "UPDATE media SET owner_id = uploaded_by "
        "WHERE owner_id IS NULL AND uploaded_by IS NOT NULL"
    )


def _backfill_owners(conn: sqlite3.Connection) -> None:
    """Give legacy rows an explicit owner.

    Media used to track `uploaded_by` only; posts and galleries could have a
    NULL author for content created before accounts existed. The first account
    becomes the owner of that orphaned content so ownership checks have a
    well-defined answer.
    """
    conn.execute(
        "UPDATE media SET owner_id = uploaded_by "
        "WHERE owner_id IS NULL AND uploaded_by IS NOT NULL"
    )
    first_user = conn.execute(
        "SELECT id FROM users ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, id LIMIT 1"
    ).fetchone()
    if not first_user:
        return
    user_id = int(first_user["id"])
    conn.execute(
        "UPDATE media SET owner_id = ? WHERE owner_id IS NULL", (user_id,)
    )
    conn.execute(
        "UPDATE posts SET author_id = ? WHERE author_id IS NULL", (user_id,)
    )
    conn.execute(
        "UPDATE galleries SET author_id = ? WHERE author_id IS NULL", (user_id,)
    )


def _backfill_media_exif(conn: sqlite3.Connection) -> None:
    """Cache EXIF for media uploaded before the media.exif column existed."""
    from .config import UPLOAD_DIR
    from .exif import dump_exif, read_exif_file

    rows = conn.execute(
        "SELECT id, filename FROM media WHERE exif = ''"
    ).fetchall()
    root = UPLOAD_DIR.resolve()
    for row in rows:
        path = (UPLOAD_DIR / row["filename"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            continue
        exif = read_exif_file(path)
        if exif:
            conn.execute(
                "UPDATE media SET exif = ? WHERE id = ?",
                (dump_exif(exif), row["id"]),
            )


def _migrate_scene(conn: sqlite3.Connection) -> None:
    """Move an Ink Isle site onto the Scene defaults, once.

    Only values that still match the previous defaults are replaced; anything
    the owner typed by hand is preserved. Palettes and hero styles that no
    longer exist are remapped so the CSS keeps rendering.
    """
    from .defaults import DEFAULT_SETTINGS, LEGACY_DEFAULTS, LEGACY_PALETTES

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 5:
        return

    stored: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            stored[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            stored[row["key"]] = row["value"]

    patch: dict[str, Any] = {}
    for key, legacy in LEGACY_DEFAULTS.items():
        if stored.get(key) == legacy and DEFAULT_SETTINGS.get(key) != legacy:
            patch[key] = DEFAULT_SETTINGS[key]

    theme = stored.get("theme")
    if isinstance(theme, str) and theme in LEGACY_PALETTES:
        patch.setdefault("theme", LEGACY_PALETTES[theme])
    if stored.get("hero_style") == "editorial":
        patch.setdefault("hero_style", "split")

    now = now_iso()
    for key, value in patch.items():
        conn.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (json.dumps(value, ensure_ascii=False), now, key),
        )


def _migrate_mono(conn: sqlite3.Connection) -> None:
    """Apply the Scene Mono revision without clobbering hand-written copy."""
    from .defaults import DEFAULT_SETTINGS, SCENE_V1_COPY

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 5:
        return

    stored: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            stored[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            stored[row["key"]] = row["value"]

    patch: dict[str, Any] = {}
    for key, legacy in SCENE_V1_COPY.items():
        if stored.get(key) == legacy and DEFAULT_SETTINGS.get(key) != legacy:
            patch[key] = DEFAULT_SETTINGS[key]

    # Mono is part of the theme, not an optional preference: force it even for
    # sites that had previously picked another pairing.
    patch["font_pair"] = "mono"

    nav = stored.get("nav")
    if isinstance(nav, list):
        cleaned = [
            item
            for item in nav
            if isinstance(item, dict)
            and not str(item.get("url", "")).startswith("/projects")
            and item.get("label") != "项目"
        ]
        if cleaned != nav:
            patch["nav"] = cleaned

    now = now_iso()
    for key, value in patch.items():
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
    conn.execute("DELETE FROM settings WHERE key IN ('home_projects_title', 'home_projects_subtitle')")


def _migrate_scene_v22(conn: sqlite3.Connection) -> None:
    """Apply the Scene 2.2 rebuild once (v6).

    The public theme was rebuilt around three equal columns — photos, projects
    and texts — and almost every line of copy became a setting. Existing sites
    move over only where the stored value is still the previous Scene default;
    customised copy and navigation are preserved. Projects return to the
    default navigation when the owner never edited the list.
    """
    from .defaults import DEFAULT_SETTINGS, SCENE_V2_COPY, SCENE_V2_NAV

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 6:
        return

    stored: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            stored[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            stored[row["key"]] = row["value"]

    patch: dict[str, Any] = {}
    for key, legacy in SCENE_V2_COPY.items():
        if stored.get(key) == legacy and DEFAULT_SETTINGS.get(key) != legacy:
            patch[key] = DEFAULT_SETTINGS[key]

    if stored.get("nav") == SCENE_V2_NAV:
        patch["nav"] = DEFAULT_SETTINGS["nav"]

    now = now_iso()
    for key, value in patch.items():
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
    # The Scene rebuild owns these; older keys belonged to the removed project
    # section or to section titles that are now `copy_*` settings. They must
    # not linger in /api/admin/settings.
    conn.execute(
        "DELETE FROM settings WHERE key IN ("
        "'home_projects_title', 'home_projects_subtitle', 'home_projects_lead', "
        "'home_gallery_title', 'home_gallery_subtitle', "
        "'home_section_title', 'home_section_subtitle'"
        ")"
    )


def _migrate_scene_wording(conn: sqlite3.Connection) -> None:
    """Rename the short-lived "Index" wording back to Scene (场景).

    The 2.2 rebuild briefly named the theme Index. This pass runs on every
    start but only rewrites values that still equal one of those old default
    strings, so hand-edited copy always survives.
    """
    from .defaults import DEFAULT_SETTINGS, SCENE_INDEX_COPY

    stored: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            stored[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            stored[row["key"]] = row["value"]

    patch = {
        key: DEFAULT_SETTINGS[key]
        for key, old in SCENE_INDEX_COPY.items()
        if key in DEFAULT_SETTINGS and stored.get(key) == old and DEFAULT_SETTINGS[key] != old
    }
    if not patch:
        return
    now = now_iso()
    for key, value in patch.items():
        conn.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (json.dumps(value, ensure_ascii=False), now, key),
        )


def _migrate_scene_demo_project(conn: sqlite3.Connection) -> None:
    """Rename the bundled demo project away from the old Index wording.

    Only the untouched demo row is rewritten (same slug and title); any edited
    project is left alone.
    """
    from .content import render_markdown
    from .seed import PROJECTS

    entry = next((item for item in PROJECTS if item["slug"] == "index-portfolio"), None)
    if not entry:
        return
    row = conn.execute(
        "SELECT id, title FROM posts WHERE type = 'project' AND slug = ?",
        (entry["slug"],),
    ).fetchone()
    if not row or row["title"] != "Index / 索引式作品集":
        return
    content = entry["content"].strip() + "\n"
    conn.execute(
        """UPDATE posts SET title = ?, excerpt = ?, content_md = ?,
               content_html = ?, updated_at = ? WHERE id = ?""",
        (
            entry["title"],
            entry.get("excerpt", ""),
            content,
            render_markdown(content),
            now_iso(),
            row["id"],
        ),
    )


def _migrate_project_kind_text(conn: sqlite3.Connection) -> None:
    """Move the old `code` / `video` enum values to plain display text (v7).

    Project types are now a free-text field; the two former presets become the
    readable values the rest of the site used to render.
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 7:
        return
    conn.execute(
        "UPDATE posts SET project_kind = '代码' "
        "WHERE type = 'project' AND LOWER(TRIM(project_kind)) = 'code'"
    )
    conn.execute(
        "UPDATE posts SET project_kind = '影像' "
        "WHERE type = 'project' AND LOWER(TRIM(project_kind)) = 'video'"
    )


def _migrate_editor_manage_others(conn: sqlite3.Connection) -> None:
    """Editors can now see/manage everyone's content by default (v8).

    Existing databases stored the old opt-in default `false`; widen them once.
    The owner can still switch it off from 设置 → 协作与权限.
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 8:
        return
    conn.execute(
        "UPDATE settings SET value = 'true', updated_at = ? "
        "WHERE key = 'editor_manage_others' AND value = 'false'",
        (now_iso(),),
    )


def _ensure_default_settings(conn: sqlite3.Connection) -> None:
    from .config import SITE_URL

    now = now_iso()
    defaults = default_settings()
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
    # Settings that the Scene rebuild retired. Deleting them on every start
    # also cleans databases that were already upgraded.
    conn.execute(
        "DELETE FROM settings WHERE key IN ("
        "'home_gallery_title', 'home_gallery_subtitle', "
        "'home_section_title', 'home_section_subtitle', "
        "'home_projects_title', 'home_projects_subtitle', 'home_projects_lead', "
        "'copy_project_kind_code', 'copy_project_kind_video'"
        ")"
    )
    # BLOG_SITE_URL is a first-boot convenience for deployments. Once the URL
    # has been changed in the admin it is left alone.
    if SITE_URL:
        row = conn.execute("SELECT value FROM settings WHERE key = 'site_url'").fetchone()
        if row:
            try:
                current = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                current = ""
            if not current or current == defaults["site_url"]:
                conn.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = 'site_url'",
                    (json.dumps(SITE_URL, ensure_ascii=False), now),
                )


def load_settings() -> dict[str, Any]:
    settings = default_settings()
    with db() as conn:
        for row in conn.execute("SELECT key, value FROM settings"):
            try:
                settings[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                settings[row["key"]] = row["value"]
    return settings


def public_settings() -> dict[str, Any]:
    """Only known public keys leave the server."""
    from .defaults import PRIVATE_SETTING_KEYS

    settings = load_settings()
    allowed = set(default_settings().keys()) - PRIVATE_SETTING_KEYS
    return {key: value for key, value in settings.items() if key in allowed}


def setting_flag(
    conn: sqlite3.Connection, key: str, default: bool = False
) -> bool:
    """Read one boolean setting using an existing connection."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return bool(json.loads(row["value"]))
    except (json.JSONDecodeError, TypeError):
        return default


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    now = now_iso()
    with db() as conn:
        for key, value in patch.items():
            if not isinstance(key, str) or not key or len(key) > 80:
                continue
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                               updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now),
            )
    return public_settings()


def get_user_count() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])


def clear_expired_sessions() -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),))
