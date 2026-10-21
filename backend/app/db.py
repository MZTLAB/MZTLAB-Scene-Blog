"""SQLite access layer.

3.0.0 keeps the standard library's sqlite3 (no ORM, no migration framework) but
changes the contract: the schema is created from versioned SQL files under
`backend/migrations/`, and a startup with anything other than an empty, current
database fails loudly. There is no 2.x migration path (decision D1).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import BASE_DIR, DB_PATH

SCHEMA_VERSION = 3
MIGRATIONS_DIR = BASE_DIR / "migrations"

# Tables every 3.0.0 database must contain. Used by the startup check and by
# `scripts/db.py verify`.
REQUIRED_TABLES = frozenset(
    {
        "users",
        "sessions",
        "posts",
        "project_details",
        "revisions",
        "taxonomy_terms",
        "post_terms",
        "media",
        "media_derivatives",
        "galleries",
        "photos",
        "settings",
        "jobs",
        "schema_meta",
        # FTS5 virtual table (plus its shadow tables). Search silently degrades
        # to LIKE without it, but a 3.0.0 database must ship it.
        "content_fts",
    }
)

SCHEMA_RESET_HINT = (
    "3.0.0 only supports initialising an empty database. "
    "Clear BLOG_DATA_DIR (or point BLOG_DATA_DIR at a new directory) and restart."
)


class SchemaVersionError(RuntimeError):
    """Raised when the database is not a fresh, current 3.0.0 database."""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # SQLite has a single writer. A busy timeout keeps short write transactions
    # from failing under concurrent uploads instead of blocking the whole site.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """A short transaction: commit on success, roll back on error.

    Transactions must only wrap short database critical sections. Long work
    (uploads, Pillow decoding, object-storage I/O, builds) happens outside so
    SQLite's single write lock never blocks the rest of the site.
    """
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
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def migration_files() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    if not MIGRATIONS_DIR.exists():
        return migrations
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            raise SchemaVersionError(f"迁移文件名缺少版本号前缀: {path.name}")
        migrations.append((int(prefix), path))
    return migrations


def _user_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def apply_migrations(conn: sqlite3.Connection, from_version: int) -> int:
    version = from_version
    for number, path in migration_files():
        if number <= version:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {number}")
        version = number
    return version


def verify_schema(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"数据库结构版本为 {version}，3.0.0 需要 {SCHEMA_VERSION}。{SCHEMA_RESET_HINT}"
        )
    missing = REQUIRED_TABLES - _user_tables(conn)
    if missing:
        raise SchemaVersionError(
            "数据库缺少 3.0.0 必需的表: " + ", ".join(sorted(missing)) + "。" + SCHEMA_RESET_HINT
        )


def init_db() -> None:
    """Create a fresh database or verify an existing one; never migrate data."""
    from .settings import seed_default_settings

    with db() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = _user_tables(conn)
        if version == 0 and tables:
            raise SchemaVersionError(
                "检测到非 3.0.0 的数据库结构（可能是 2.x 或未完成的初始化）。" + SCHEMA_RESET_HINT
            )
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"检测到 2.x 或更高版本的数据库（结构版本 {version}，"
                f"本程序支持 {SCHEMA_VERSION}）。{SCHEMA_RESET_HINT}"
            )
        if version == 0:
            apply_migrations(conn, 0)
        elif version < SCHEMA_VERSION:
            # Future 3.x versions add migrations/0002_*.sql etc.; applying them
            # is explicit and versioned, never a startup data patch.
            apply_migrations(conn, version)
        verify_schema(conn)
        seed_default_settings(conn)
        conn.execute(
            """INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (str(SCHEMA_VERSION),),
        )
        conn.execute(
            """INSERT OR IGNORE INTO schema_meta(key, value)
               VALUES ('initialised_at', ?)""",
            (now_iso(),),
        )

    from .seed import ensure_bootstrap_admin, seed_demo_content  # circular-safe

    # An account must exist before demo content can own it (`owner_id` is
    # NOT NULL). With the setup-page flow there is no account yet, so demo
    # seeding is deferred until /api/setup creates one.
    ensure_bootstrap_admin()
    seed_demo_content()


def get_user_count() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])


def clear_expired_sessions() -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),))


def get_meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else ""
