"""Database bootstrap tests: empty DB only, versioned migrations, no 2.x path."""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app import db as db_module
from app.db import (
    REQUIRED_TABLES,
    SCHEMA_VERSION,
    SchemaVersionError,
    apply_migrations,
    connect,
    init_db,
    migration_files,
    verify_schema,
)
from app.settings import invalidate_settings_cache


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._old_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmp.name) / "test.db"
        invalidate_settings_cache()

    def tearDown(self) -> None:
        db_module.DB_PATH = self._old_path
        invalidate_settings_cache()
        self._tmp.cleanup()

    def _tables(self, conn: sqlite3.Connection) -> set[str]:
        return {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }

    def test_migrations_are_numbered_and_include_the_initial_schema(self) -> None:
        files = migration_files()
        self.assertTrue(files)
        self.assertEqual(files[0][0], 1)
        self.assertEqual(files[0][1].name, "0001_init.sql")
        self.assertEqual(SCHEMA_VERSION, max(number for number, _ in files))

    def test_empty_database_is_initialised_to_the_current_version(self) -> None:
        init_db()
        with closing(connect()) as conn:
            self.assertEqual(
                int(conn.execute("PRAGMA user_version").fetchone()[0]),
                SCHEMA_VERSION,
            )
            self.assertEqual(REQUIRED_TABLES - self._tables(conn), set())
            groups = [
                row['group']
                for row in conn.execute('SELECT "group" FROM settings ORDER BY "group"')
            ]
            self.assertEqual(
                groups, ["advanced", "appearance", "copy", "site", "upload"]
            )
            # Removed features have no tables.
            self.assertNotIn("comments", self._tables(conn))
            self.assertNotIn("categories", self._tables(conn))
            self.assertNotIn("tags", self._tables(conn))

    def test_init_is_idempotent(self) -> None:
        init_db()
        init_db()
        with closing(connect()) as conn:
            verify_schema(conn)

    def test_2x_database_is_rejected_with_a_clear_message(self) -> None:
        conn = sqlite3.connect(db_module.DB_PATH)
        conn.execute("PRAGMA user_version = 13")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError) as raised:
            init_db()
        self.assertIn("BLOG_DATA_DIR", str(raised.exception))

    def test_database_with_tables_but_no_version_is_rejected(self) -> None:
        conn = sqlite3.connect(db_module.DB_PATH)
        conn.execute("CREATE TABLE legacy_thing (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            init_db()

    def test_verify_schema_reports_missing_tables(self) -> None:
        init_db()
        with closing(connect()) as conn:
            conn.execute("DROP TABLE jobs")
        with closing(connect()) as conn, self.assertRaises(SchemaVersionError) as raised:
            verify_schema(conn)
        self.assertIn("jobs", str(raised.exception))

    def test_migrations_do_not_reapply(self) -> None:
        with closing(connect()) as conn:
            self.assertEqual(apply_migrations(conn, 0), SCHEMA_VERSION)
            self.assertEqual(apply_migrations(conn, SCHEMA_VERSION), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
