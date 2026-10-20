#!/usr/bin/env python3
"""Delete generated image derivatives that are no longer referenced.

Changing the image quality / width ladder changes every derivative URL token;
the old files stay in the cache (or bucket) so pages rendered before the change
keep working. Once caches have expired, this script reclaims that space.

Examples:
    python scripts/prune_derivatives.py --dry-run
    python scripts/prune_derivatives.py
    python scripts/prune_derivatives.py --vacuum   # also drop orphan tokens
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import IMAGE_CACHE_DIR  # noqa: E402
from app.db import db, init_db, load_settings_cached  # noqa: E402
from app.images import variants_hash  # noqa: E402
from app.storage import DERIVED_PREFIX, get_storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune stale image derivatives")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="also remove whole token directories that are not referenced",
    )
    args = parser.parse_args()

    init_db()
    settings = load_settings_cached()
    storage = get_storage()
    with db() as conn:
        media_rows = conn.execute("SELECT * FROM media").fetchall()
        derivative_rows = conn.execute("SELECT * FROM media_derivatives").fetchall()

    current = {
        int(row["id"]): variants_hash(row, settings)
        for row in media_rows
        if str(row["mime"] or "").startswith("image/")
    }
    removed = 0
    for row in derivative_rows:
        media_id = int(row["media_id"])
        token = current.get(media_id)
        keep = token and f"/{token}/" in str(row["key"])
        if keep:
            continue
        removed += 1
        if args.dry_run:
            print(f"would delete {row['key']}")
            continue
        try:
            storage.delete(row["key"])
        except Exception as error:
            print(f"delete failed {row['key']}: {error}")
            continue
        with db() as conn:
            conn.execute("DELETE FROM media_derivatives WHERE id = ?", (row["id"],))

    vacuumed = 0
    if args.vacuum:
        # Local cache only; bucket prefixes are removed by the same rule.
        if storage.local_path(f"{DERIVED_PREFIX}0") is not None:
            for media_dir in sorted(IMAGE_CACHE_DIR.glob(f"{DERIVED_PREFIX}*")):
                if not media_dir.is_dir():
                    continue
                try:
                    media_id = int(media_dir.name[len(DERIVED_PREFIX):])
                except ValueError:
                    continue
                token = current.get(media_id)
                for token_dir in media_dir.iterdir():
                    if not token_dir.is_dir():
                        continue
                    if token and token_dir.name == token:
                        continue
                    vacuumed += 1
                    if args.dry_run:
                        print(f"would remove {token_dir}")
                    else:
                        storage.delete_prefix(
                            f"{DERIVED_PREFIX}{media_id}/{token_dir.name}"
                        )
        else:
            print("--vacuum only prunes the local cache; bucket cleanup uses DB rows.")

    print(
        f"完成：删除派生图记录 {removed} 条"
        + (f"，清理旧 token {vacuumed} 组" if args.vacuum else "")
        + ("（dry-run）" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
