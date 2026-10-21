"""Admin data export (3.x backup / restore format).

3.0.0 no longer imports or exports 2.x data: the payload is the exact 3.0.0
table shape (`posts` + `project_details` class-table inheritance, taxonomy
terms, galleries/photos/media, revisions) plus the grouped public settings.
The discussion feature was removed, so no discussion tables are exported.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..api.models import ExportV3Response
from ..db import db, now_iso
from ..deps import require_permission, require_staff
from ..settings import load_settings_cached

router = APIRouter(
    prefix="/admin",
    tags=["export"],
    dependencies=[Depends(require_staff)],
)

EXPORT_FORMAT = "mztlab-scene-export"
EXPORT_VERSION = 3


def _rows(conn: Any, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql)]


@router.get("/export", response_model=ExportV3Response)
def export_site(
    user: dict = Depends(require_permission("data.export")),
) -> JSONResponse:
    with db() as conn:
        data: dict[str, Any] = {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": now_iso(),
            "settings": load_settings_cached().public_dump(),
            "posts": _rows(conn, "SELECT * FROM posts ORDER BY id"),
            "project_details": _rows(
                conn, "SELECT * FROM project_details ORDER BY post_id"
            ),
            "taxonomy_terms": _rows(
                conn, "SELECT * FROM taxonomy_terms ORDER BY id"
            ),
            "post_terms": _rows(
                conn, "SELECT * FROM post_terms ORDER BY post_id, term_id"
            ),
            "galleries": _rows(conn, "SELECT * FROM galleries ORDER BY id"),
            "photos": _rows(conn, "SELECT * FROM photos ORDER BY id"),
            "media": _rows(conn, "SELECT * FROM media ORDER BY id"),
            "revisions": _rows(conn, "SELECT * FROM revisions ORDER BY id"),
        }
    filename = f"mztlab-{now_iso()[:10]}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
