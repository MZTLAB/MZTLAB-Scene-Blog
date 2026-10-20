#!/usr/bin/env python3
"""Copy original media files between the local disk and an S3-compatible bucket.

Only originals are copied; image derivatives are regenerated on demand (or with
`scripts/optimize_media.py`). Run with --dry-run first.

Examples:
    # Local disk -> Cloudflare R2 using the settings already saved in the admin
    python scripts/migrate_storage.py --to s3 --dry-run
    python scripts/migrate_storage.py --to s3

    # Bucket -> local disk (current backend must be configured as s3)
    python scripts/migrate_storage.py --to local

    # Delete the source objects after a verified copy
    python scripts/migrate_storage.py --to s3 --delete-source
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import db, init_db  # noqa: E402
from app.storage import (  # noqa: E402
    LocalStorage,
    S3Storage,
    StorageError,
    StorageMissing,
    content_type_for,
    storage_config,
)


def build_target(kind: str):
    config = storage_config()
    if kind == "s3":
        if not config.is_s3:
            print(
                "当前设置的后端不是 s3。请先在 管理后台 → 设置 → 图片与存储 "
                "填写 R2 配置并保存，再运行本脚本。"
            )
            raise SystemExit(2)
        return S3Storage(config)
    return LocalStorage()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate original media files")
    parser.add_argument("--to", choices=("s3", "local"), required=True)
    parser.add_argument("--delete-source", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db()
    source = LocalStorage() if args.to == "s3" else build_target("s3")
    target = build_target("s3") if args.to == "s3" else LocalStorage()

    with db() as conn:
        rows = conn.execute(
            "SELECT filename, mime, size FROM media ORDER BY id"
        ).fetchall()
    if not rows:
        print("媒体库是空的。")
        return 0

    copied = skipped = failed = 0
    for index, row in enumerate(rows, start=1):
        key = str(row["filename"])
        try:
            if target.exists(key):
                skipped += 1
                continue
            data = source.read(key)
            if args.dry_run:
                print(f"[{index}/{len(rows)}] would copy {key} ({len(data)} bytes)")
                copied += 1
                continue
            target.save(key, data, str(row["mime"] or content_type_for(key)))
            if target.read(key) != data:
                raise StorageError("copy verification failed")
            copied += 1
            print(f"[{index}/{len(rows)}] copied {key}")
            if args.delete_source:
                source.delete(key)
        except (StorageMissing, StorageError) as error:
            failed += 1
            print(f"[{index}/{len(rows)}] {key} 失败：{error}")
    print(f"完成：复制 {copied}，已存在 {skipped}，失败 {failed}（{args.to}）。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
