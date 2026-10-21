"""Admin dashboard aggregates.

Discussion and view-count features are gone in 3.0.0, so the payload is
content/gallery counts plus a few "recently edited" previews and the running
version.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from ..api.models import DashboardStats
from ..config import VERSION
from ..db import db, now_iso
from ..deps import require_staff
from ..posts import serialize_posts
from ..services.content_admin import page_counts

router = APIRouter(
    prefix="/admin",
    tags=["dashboard"],
    dependencies=[Depends(require_staff)],
)


def _recent_posts(
    conn: sqlite3.Connection, post_type: str, limit: int = 5
) -> list[dict[str, Any]]:
    rows = list(
        conn.execute(
            """SELECT p.*, pd.kind AS project_kind, pd.year AS project_year,
                      pd.role AS project_role, pd.client AS project_client,
                      pd.url AS project_url,
                      u.display_name AS author_name, u.username AS author_username,
                      u.avatar AS author_avatar, u.bio AS author_bio
               FROM posts p
               LEFT JOIN project_details pd ON pd.post_id = p.id
               LEFT JOIN users u ON u.id = p.owner_id
               WHERE p.type = ? ORDER BY p.updated_at DESC LIMIT ?""",
            (post_type, limit),
        )
    )
    return serialize_posts(conn, rows, admin=True)


@router.get("/stats", response_model=DashboardStats)
def stats() -> dict[str, Any]:
    with db() as conn:
        def scalar(sql: str, args: tuple[Any, ...] = ()) -> int:
            row = conn.execute(sql, args).fetchone()
            return int(row[0]) if row else 0

        post_counts = page_counts(conn, "post")
        project_counts = page_counts(conn, "project")
        pages_count = scalar("SELECT COUNT(*) FROM posts WHERE type = 'page'")
        media_count = scalar("SELECT COUNT(*) FROM media")
        gallery_count = scalar("SELECT COUNT(*) FROM galleries")
        photo_count = scalar("SELECT COUNT(*) FROM photos")
        tag_count = scalar(
            "SELECT COUNT(*) FROM taxonomy_terms WHERE kind = 'tag'"
        )
        category_count = scalar(
            "SELECT COUNT(*) FROM taxonomy_terms WHERE kind = 'category'"
        )
        recent_posts = _recent_posts(conn, "post")
        recent_projects = _recent_posts(conn, "project")
        recent_galleries = [
            dict(row)
            for row in conn.execute(
                """SELECT g.id, g.title, g.slug, g.status, g.updated_at,
                          (SELECT COUNT(*) FROM photos ph
                           WHERE ph.gallery_id = g.id) AS photo_count
                   FROM galleries g ORDER BY g.updated_at DESC LIMIT 4"""
            )
        ]
    return {
        "posts": post_counts,
        "projects": project_counts,
        "pages": pages_count,
        "media": media_count,
        "galleries": gallery_count,
        "photos": photo_count,
        "tags": tag_count,
        "categories": category_count,
        "recent_posts": recent_posts,
        "recent_projects": recent_projects,
        "recent_galleries": recent_galleries,
        "system": {"version": VERSION, "generated_at": now_iso()},
    }
