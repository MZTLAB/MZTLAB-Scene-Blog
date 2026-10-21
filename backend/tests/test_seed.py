"""Demo seeding: opt-in, user-owned and idempotent.

The application modules read `BLOG_DATA_DIR` / `BLOG_DB_PATH` when `app.config`
is imported, so these tests do not rely on environment variables being set
before import. Instead they use `monkeypatch` on the loaded modules:

* `app.db.DB_PATH`      — `db()` resolves the module global on every connection;
* `app.seed.UPLOAD_DIR` — the demo JPEGs are written there;
* `app.seed.SEED_DEMO`  — the `from .config import SEED_DEMO` opt-in flag.

The schema is created straight from `backend/migrations/` with the same
`apply_migrations()` / `verify_schema()` helpers `init_db()` uses, but without
seeding the grouped settings layer: these tests cover the seeder, not startup.
Nothing here touches `backend/data`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app import config as config_module
from app import db as db_module
from app import seed as seed_module

# These tests never log in; any non-empty placeholder is enough for a user row.
_PASSWORD_HASH = "scrypt$0$0$0$AA$AA"

_SEEDED_TABLES = (
    "posts",
    "project_details",
    "taxonomy_terms",
    "post_terms",
    "galleries",
    "media",
    "photos",
)


def _create_user(role: str = "admin", username: str = "tester") -> int:
    """Insert an account without going through the scrypt hashing path."""
    now = db_module.now_iso()
    with db_module.db() as conn:
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, display_name, email, bio,
                                 avatar, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, '', '', '', ?, 1, ?, ?)""",
            (username, _PASSWORD_HASH, username.title(), role, now, now),
        )
        return int(cur.lastrowid)


def _count(table: str) -> int:
    with db_module.db() as conn:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])


def _counts() -> dict[str, int]:
    return {table: _count(table) for table in _SEEDED_TABLES}


def _enable_demo(monkeypatch: MonkeyPatch, enabled: bool = True) -> None:
    monkeypatch.setattr(seed_module, "SEED_DEMO", enabled)


def _init_schema() -> None:
    """Create the empty 3.0.0 schema in the monkeypatched `app.db.DB_PATH`."""
    with db_module.db() as conn:
        version = db_module.apply_migrations(conn, 0)
        db_module.verify_schema(conn)
    assert version == db_module.SCHEMA_VERSION


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A fresh, empty 3.0.0 database plus an isolated upload directory."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "blog.db")
    monkeypatch.setattr(seed_module, "UPLOAD_DIR", tmp_path / "uploads")
    _enable_demo(monkeypatch, False)
    # A developer's .env must never leak a bootstrap account into the test DB.
    monkeypatch.setattr(config_module, "BOOTSTRAP_ADMIN_USER", "")
    monkeypatch.setattr(config_module, "BOOTSTRAP_ADMIN_PASSWORD", "")
    _init_schema()
    return tmp_path


def test_seed_is_a_noop_when_opt_in_is_disabled(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    _create_user()
    _enable_demo(monkeypatch, False)

    seed_module.seed_demo_content()

    assert _counts() == dict.fromkeys(_SEEDED_TABLES, 0)
    assert not (isolated_data / "uploads").exists()


def test_seed_is_a_noop_when_no_user_exists(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    _enable_demo(monkeypatch, True)

    # The setup route calls this again after the first account is created.
    seed_module.seed_demo_content()

    assert _count("users") == 0
    assert _counts() == dict.fromkeys(_SEEDED_TABLES, 0)
    assert not (isolated_data / "uploads").exists()


def test_seed_is_a_noop_when_content_already_exists(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    owner_id = _create_user()
    now = db_module.now_iso()
    with db_module.db() as conn:
        conn.execute(
            """INSERT INTO posts(type, title, slug, status, published_at, owner_id,
                                 created_at, updated_at)
               VALUES ('post', 'Existing', 'existing', 'published', ?, ?, ?, ?)""",
            (now, owner_id, now, now),
        )
    _enable_demo(monkeypatch, True)

    seed_module.seed_demo_content()

    assert _count("posts") == 1
    assert _count("galleries") == 0
    assert _count("media") == 0
    assert not (isolated_data / "uploads").exists()


def test_seeding_twice_is_idempotent(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    _create_user()
    _enable_demo(monkeypatch, True)

    seed_module.seed_demo_content()
    first = _counts()
    seed_module.seed_demo_content()
    second = _counts()

    assert first == second
    # Content kept from 2.x: 3 articles + 4 projects + 1 about page.
    assert first["posts"] == 8
    assert first["project_details"] == 4
    assert first["galleries"] == 3
    assert first["media"] == 16
    assert first["photos"] == 16
    # 3 categories + 10 tags, 12 article links (1 category + 3 tags per article).
    assert first["taxonomy_terms"] == 13
    assert first["post_terms"] == 12
    assert len(list((isolated_data / "uploads" / "seed").glob("*.jpg"))) == 16


def test_seeded_rows_are_owned_and_relationally_complete(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    # First author then admin: the owner must be the admin, not the first row.
    _create_user(role="author", username="author")
    admin_id = _create_user(role="admin", username="admin")
    _enable_demo(monkeypatch, True)

    seed_module.seed_demo_content()

    with db_module.db() as conn:
        # Ownership is NOT NULL and always the account chosen by the seeder.
        for table in ("posts", "galleries", "media"):
            owners = {int(row[0]) for row in conn.execute(f"SELECT owner_id FROM {table}")}
            assert owners == {admin_id}
        orphan_posts = conn.execute(
            "SELECT COUNT(*) AS n FROM posts p "
            "LEFT JOIN users u ON u.id = p.owner_id WHERE u.id IS NULL"
        ).fetchone()["n"]
        assert orphan_posts == 0

        # Post types and the project_details extension table.
        types = {
            str(row["type"]): int(row["n"])
            for row in conn.execute("SELECT type, COUNT(*) AS n FROM posts GROUP BY type")
        }
        assert types == {"post": 3, "project": 4, "page": 1}
        project_rows = conn.execute(
            "SELECT pd.kind, pd.year, p.id FROM project_details pd "
            "JOIN posts p ON p.id = pd.post_id WHERE p.type = 'project'"
        ).fetchall()
        assert len(project_rows) == 4
        assert all(row["kind"] and row["year"] for row in project_rows)

        # Taxonomy lives in taxonomy_terms + post_terms now, not the 2.x tables.
        kinds = {
            str(row["kind"]): int(row["n"])
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM taxonomy_terms GROUP BY kind"
            )
        }
        assert kinds == {"category": 3, "tag": 10}
        linked_terms = conn.execute(
            "SELECT COUNT(*) AS n FROM post_terms pt "
            "JOIN taxonomy_terms t ON t.id = pt.term_id"
        ).fetchone()["n"]
        assert linked_terms == 12

        # The about page is a page, not an article.
        about = conn.execute(
            "SELECT type, owner_id FROM posts WHERE slug = 'about'"
        ).fetchone()
        assert about is not None
        assert about["type"] == "page"
        assert int(about["owner_id"]) == admin_id

        # Rendered content fields are materialised on insert.
        article = conn.execute(
            "SELECT content_html, reading_time, toc_json FROM posts WHERE type = 'post' LIMIT 1"
        ).fetchone()
        assert article is not None
        assert "<h2 " in str(article["content_html"])
        assert int(article["reading_time"]) > 0
        assert str(article["toc_json"]).startswith("[")

        # Every photo references a gallery and a media row.
        photos = conn.execute(
            """SELECT ph.filename, ph.media_id, ph.gallery_id
               FROM photos ph
               JOIN media m ON m.id = ph.media_id
               JOIN galleries g ON g.id = ph.gallery_id"""
        ).fetchall()
        assert len(photos) == 16

    for photo in photos:
        assert (isolated_data / "uploads" / str(photo["filename"])).is_file()

    # The generated originals are real JPEGs with the seeded camera EXIF.
    from PIL import Image

    with Image.open(isolated_data / "uploads" / "seed" / "form-studies-01.jpg") as image:
        assert image.format == "JPEG"
        assert image.width > 0


def test_bootstrap_admin_is_created_once(
    isolated_data: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(config_module, "BOOTSTRAP_ADMIN_USER", "root")
    monkeypatch.setattr(config_module, "BOOTSTRAP_ADMIN_PASSWORD", "Str0ng-Pass-987!")
    monkeypatch.setattr(config_module, "BOOTSTRAP_ADMIN_NAME", "Root")

    seed_module.ensure_bootstrap_admin()
    seed_module.ensure_bootstrap_admin()

    with db_module.db() as conn:
        users = conn.execute(
            "SELECT username, display_name, role FROM users"
        ).fetchall()
    assert len(users) == 1
    assert users[0]["username"] == "root"
    assert users[0]["display_name"] == "Root"
    assert users[0]["role"] == "admin"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
