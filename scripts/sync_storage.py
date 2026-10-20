#!/usr/bin/env python3
"""Force-sync local media files to the configured S3-compatible object storage.

Useful after switching `storage_backend` from `local` to `s3`, restoring a
bucket, or repairing a partially lost remote. By default only missing objects
and files whose size differs are uploaded; `--force` overwrites everything.

Example:
    python scripts/sync_storage.py --dry-run
    python scripts/sync_storage.py
    python scripts/sync_storage.py --force
    python scripts/sync_storage.py --scope derivatives --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import init_db  # noqa: E402
from app.storage import LocalStorage, get_remote_storage  # noqa: E402
from app.storage_sync import SCOPES, local_objects, sync_local_to_remote  # noqa: E402


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync local files to object storage")
    parser.add_argument("--force", action="store_true", help="overwrite existing remote objects")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="all",
        help="all (default) / originals / derivatives",
    )
    parser.add_argument("--dry-run", action="store_true", help="only report what would be uploaded")
    args = parser.parse_args()

    init_db()
    remote = get_remote_storage()
    if remote is None:
        print(
            "对象存储未配置：请先在 管理后台 → 设置 → 图片与存储 选择 s3 并填写 "
            "endpoint / bucket / 凭证，再运行本脚本。"
        )
        return 2

    local = LocalStorage()
    objects = local_objects(local, args.scope)
    if not objects:
        print("本地没有可同步的文件。")
        return 0
    total_bytes = sum(size for _, size in objects)
    print(
        f"本地 {len(objects)} 个文件 / {human_size(total_bytes)} "
        f"· scope={args.scope} · force={'yes' if args.force else 'no'}"
    )

    if args.dry_run:
        for key, size in objects[:20]:
            print(f"  {key} ({human_size(size)})")
        if len(objects) > 20:
            print(f"  … 其余 {len(objects) - 20} 个")
        return 0

    def progress(result) -> None:
        done = result.uploaded + result.skipped + result.failed
        if done == result.total or done % 25 == 0:
            print(
                f"  [{done}/{result.total}] 上传 {result.uploaded} · 跳过 "
                f"{result.skipped} · 失败 {result.failed} · "
                f"{human_size(result.bytes_uploaded)}"
            )

    result = sync_local_to_remote(
        local, remote, force=args.force, scope=args.scope, progress=progress
    )
    print(
        f"完成：上传 {result.uploaded}，跳过 {result.skipped}，失败 {result.failed}，"
        f"共 {human_size(result.bytes_uploaded)}。"
    )
    for message in result.errors:
        print(f"  ! {message}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
