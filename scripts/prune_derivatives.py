#!/usr/bin/env python3
"""Reclaim orphaned image derivatives (job-型 GC 的 CLI 壳).

3.0.0 addresses derivatives by artifact token. After a manual `reencode` the
previous artifact set keeps serving until the `gc_derivatives` job (or this CLI)
deletes rows/objects no longer referenced by `media.derivative_set`.

The admin can trigger the same work through `POST /api/admin/jobs`
(`{"kind": "gc_derivatives"}`); this script is the CLI shell for cron/maintenance
and intentionally calls the same `images.gc_derivatives()` implementation.

    python scripts/prune_derivatives.py --dry-run
    python scripts/prune_derivatives.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import init_db  # noqa: E402
from app.images import derivative_stats, gc_derivatives  # noqa: E402

BATCH = 200


def main() -> int:
    parser = argparse.ArgumentParser(description="清理无引用的图片派生图（GC）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--batch", type=int, default=BATCH, help="单批处理行数（默认 200）")
    args = parser.parse_args()
    init_db()
    if args.dry_run:
        stats = gc_derivatives(limit=args.batch, dry_run=True)
        print(
            f"would delete {stats['rows']} derivative rows "
            f"({stats['objects']} objects in the scanned batch)"
        )
        print(f"当前派生图统计: {derivative_stats()}")
        return 0
    total_rows = 0
    total_objects = 0
    while True:
        stats = gc_derivatives(limit=args.batch)
        total_rows += stats["rows"]
        total_objects += stats["objects"]
        if stats["rows"] == 0:
            break
    print(f"完成：删除派生图记录 {total_rows} 条，对象 {total_objects} 个")
    print(f"派生图统计: {derivative_stats()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
