#!/usr/bin/env python3
"""Pre-generate AVIF / WebP / JPEG derivatives for the media library.

Run after upgrading an existing site, or after changing the image quality /
width ladder in the admin panel. Variants are normally generated on first
request as well; this script just warms everything (and marks each image as
ready, which enables direct object-storage URLs when configured).

Examples:
    python scripts/optimize_media.py
    python scripts/optimize_media.py --force
    python scripts/optimize_media.py --media-id 42
    python scripts/optimize_media.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import db, init_db, load_settings_cached  # noqa: E402
from app.images import (  # noqa: E402
    AVIF_SUPPORTED,
    SCENES,
    WEBP_SUPPORTED,
    generation_formats,
    prewarm_media,
    scene_widths,
)


def media_ids(only: int | None, limit: int | None) -> list[int]:
    with db() as conn:
        if only:
            rows = conn.execute(
                "SELECT id FROM media WHERE id = ? AND mime LIKE 'image/%'", (only,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM media WHERE mime LIKE 'image/%' ORDER BY id"
            ).fetchall()
    ids = [int(row["id"]) for row in rows]
    return ids[:limit] if limit else ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate image derivatives")
    parser.add_argument("--media-id", type=int, help="only this media id")
    parser.add_argument("--limit", type=int, help="stop after N images")
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    args = parser.parse_args()

    init_db()
    settings = load_settings_cached()
    ids = media_ids(args.media_id, args.limit)
    if not ids:
        print("没有可处理的图片。")
        return 0

    print(
        f"AVIF={'yes' if AVIF_SUPPORTED else 'no'} WebP={'yes' if WEBP_SUPPORTED else 'no'} "
        f"formats={','.join(generation_formats(settings))}"
    )
    if args.dry_run:
        with db() as conn:
            for media_id in ids:
                row = conn.execute(
                    "SELECT width FROM media WHERE id = ?", (media_id,)
                ).fetchone()
                width = int(row["width"] or 0)
                plan = {
                    scene: scene_widths(scene, width, settings) for scene in SCENES
                }
                print(f"#{media_id} width={width} {plan}")
        return 0

    done = failed = 0
    for index, media_id in enumerate(ids, start=1):
        try:
            ok = prewarm_media(media_id, force=args.force)
        except Exception as error:  # keep going; report at the end
            print(f"[{index}/{len(ids)}] #{media_id} 失败：{error}")
            failed += 1
            continue
        status = "ok" if ok else "partial"
        print(f"[{index}/{len(ids)}] #{media_id} {status}")
        done += 1
    print(f"完成：{done} 张图片，失败 {failed} 张。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
