#!/usr/bin/env python3
"""Consistent SQLite backup (3.0.0 Phase 5).

The site is a single SQLite file plus an uploads directory. A plain file copy of
a live WAL database can be inconsistent, so this script uses SQLite's online
backup API, then optionally snapshots the media directories.

    python scripts/backup.py                     # DB backup next to DATA_DIR/backups
    python scripts/backup.py --include-media     # DB + uploads/cache snapshot
    python scripts/backup.py --out D:\\backups   # explicit destination

Restore (offline):
    1. stop the backend;
    2. unzip/copy the backup directory over BLOG_DATA_DIR;
    3. `python scripts/db.py verify` (integrity + foreign keys + schema version);
    4. start the backend and spot-check the admin + a public page.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import DB_PATH, IMAGE_CACHE_DIR, UPLOAD_DIR  # noqa: E402
from app.db import SCHEMA_VERSION  # noqa: E402


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_database(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(DB_PATH)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            # The copy is the only artifact a restore depends on: verify it
            # before reporting success instead of discarding the result (a
            # corrupt backup that "succeeds" is worse than a loud failure).
            row = destination.execute("PRAGMA integrity_check").fetchone()
            verdict = str(row[0]) if row else "unknown"
            if verdict != "ok":
                raise RuntimeError(f"备份完整性校验失败: {verdict}")
        finally:
            destination.close()
    except Exception:
        # Never leave a half-written .db behind that looks like a good backup.
        target.unlink(missing_ok=True)
        raise
    finally:
        source.close()


def archive_media(target: Path) -> bool:
    paths = [path for path in (UPLOAD_DIR, IMAGE_CACHE_DIR) if path.exists()]
    if not paths:
        return False
    with tarfile.open(target, "w:gz") as archive:
        for path in paths:
            archive.add(path, arcname=path.name)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="MZTLAB 3.0.0 数据库备份")
    parser.add_argument("--out", default="", help="备份输出目录（默认 BLOG_DATA_DIR/backups）")
    parser.add_argument("--include-media", action="store_true", help="同时打包 uploads/ 与 cache/")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return 1
    output = Path(args.out).expanduser().resolve() if args.out else DB_PATH.parent / "backups"
    stamp = _stamp()
    database_copy = output / f"blog-{stamp}.db"
    try:
        backup_database(database_copy)
    except (RuntimeError, sqlite3.Error) as error:
        print(f"备份失败: {error}")
        return 1
    manifest: dict[str, object] = {
        "created_at": stamp,
        "schema_version": SCHEMA_VERSION,
        "database": database_copy.name,
        "media_archive": None,
    }
    if args.include_media:
        archive = output / f"media-{stamp}.tar.gz"
        if archive_media(archive):
            manifest["media_archive"] = archive.name
    (output / f"manifest-{stamp}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"数据库备份: {database_copy}")
    if manifest["media_archive"]:
        print(f"媒体归档:   {output / str(manifest['media_archive'])}")
    print(f"清单:       {output / f'manifest-{stamp}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
