#!/usr/bin/env python3
"""Explicit database maintenance for MZTLAB 3.0.0.

The application never migrates data at startup; structural changes are applied
by a human or CI through this script.

    python scripts/db.py migrate     # create / upgrade to the latest schema
    python scripts/db.py status      # current version, pending migrations, counts
    python scripts/db.py verify      # integrity + schema + foreign key checks
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import DB_PATH  # noqa: E402
from app.db import (  # noqa: E402
    MIGRATIONS_DIR,
    SCHEMA_VERSION,
    REQUIRED_TABLES,
    SchemaVersionError,
    apply_migrations,
    connect,
    migration_files,
    verify_schema,
)


def _current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def command_migrate() -> int:
    with connect() as conn:
        version = _current_version(conn)
        if version > SCHEMA_VERSION:
            print(f"数据库版本 {version} 高于程序支持的 {SCHEMA_VERSION}，拒绝降级。")
            return 1
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        if version == 0 and tables:
            print("检测到非 3.0.0 数据库（缺少结构版本但已有表），拒绝自动迁移。")
            return 1
        applied = apply_migrations(conn, version)
        if applied > 0:
            from app.settings import seed_default_settings

            seed_default_settings(conn)
        conn.commit()
        print(f"数据库: {DB_PATH}")
        print(f"结构版本: {version} → {_current_version(conn)}")
        if applied == 0:
            print("没有需要应用的迁移。")
    return 0


def command_status() -> int:
    print(f"数据库: {DB_PATH}")
    if not DB_PATH.exists():
        print("状态: 未创建（运行 `python scripts/db.py migrate` 初始化）")
        print(f"可用迁移: {', '.join(path.name for _, path in migration_files())}")
        return 0
    with connect() as conn:
        version = _current_version(conn)
        print(f"结构版本: {version}（程序支持 {SCHEMA_VERSION}）")
        pending = [
            path.name for number, path in migration_files() if number > version
        ]
        print(f"待应用迁移: {', '.join(pending) if pending else '无'}")
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = REQUIRED_TABLES - tables
        print(f"必需表缺失: {', '.join(sorted(missing)) if missing else '无'}")
        for table in sorted(REQUIRED_TABLES & tables):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:20s} {count:>8d} 行")
        try:
            groups = [
                row['"group"']
                for row in conn.execute('SELECT "group" FROM settings ORDER BY "group"')
            ]
            print(f"设置分组: {', '.join(groups) if groups else '无'}")
        except sqlite3.Error:
            print("设置分组: 读取失败")
    return 0


def command_verify() -> int:
    if not DB_PATH.exists():
        print("数据库不存在。")
        return 1
    with connect() as conn:
        try:
            verify_schema(conn)
        except SchemaVersionError as exc:
            print(f"结构校验失败: {exc}")
            return 1
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"integrity_check: {integrity}")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print(f"外键违例: {len(violations)} 条")
            for row in violations[:20]:
                print(f"  {dict(row)}")
            return 1
        print("外键检查: 通过")
        print(f"结构版本: {_current_version(conn)}，迁移目录: {MIGRATIONS_DIR}")
    return 0


COMMANDS = {"migrate": command_migrate, "status": command_status, "verify": command_verify}


def main() -> int:
    parser = argparse.ArgumentParser(description="MZTLAB 3.0.0 数据库维护")
    parser.add_argument("command", choices=sorted(COMMANDS), help="要执行的命令")
    args = parser.parse_args()
    return COMMANDS[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
