"""Admin data export / restore (3.x backup format only).

`GET /api/admin/export` produces a complete 3.0.0 backup: the full grouped
settings document plus every content/gallery/media/user table. No secrets are
included because S3 credentials are environment-only.

`POST /api/admin/import` restores such a document. The destructive replacement
(and its reference validation) lives in `app.services.backup`; media binaries
are *not* part of the JSON and are only reported as missing after the commit.
2.x documents are refused: there is no downgrade/import path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..api.models import ExportV3Response, ImportV3Request, ImportV3Response
from ..db import db, now_iso
from ..deps import require_permission, require_staff
from ..errors import ApiError
from ..services.backup import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    MEDIA_COLUMNS,
    MEDIA_DERIVATIVES_COLUMNS,
    PHOTOS_COLUMNS,
    USERS_COLUMNS,
    import_document,
)
from ..settings import load_settings

router = APIRouter(
    prefix="/admin",
    tags=["export"],
    dependencies=[Depends(require_staff)],
)


def _rows(
    conn: Any, table: str, columns: tuple[str, ...], order_by: str = "id"
) -> list[dict[str, Any]]:
    sql = f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY {order_by}'
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
            # Full grouped document (site/appearance/copy/upload/advanced); the
            # settings table never stores credentials.
            "settings": load_settings().model_dump(),
            "users": _rows(conn, "users", USERS_COLUMNS),
            "posts": _rows(conn, "posts", (
                "id", "type", "title", "slug", "excerpt", "content_md",
                "content_html", "render_version", "cover_image", "status",
                "published_at", "featured", "owner_id", "seo_title",
                "seo_description", "reading_time", "toc_json", "created_at",
                "updated_at",
            )),
            "project_details": _rows(conn, "project_details", (
                "post_id", "kind", "year", "role", "client", "url",
            ), order_by="post_id"),
            "taxonomy_terms": _rows(conn, "taxonomy_terms", (
                "id", "kind", "name", "slug", "description", "created_at",
            )),
            "post_terms": _rows(conn, "post_terms", (
                "post_id", "term_id",
            ), order_by="post_id, term_id"),
            "revisions": _rows(conn, "revisions", (
                "id", "post_id", "title", "excerpt", "content_md", "owner_id",
                "created_at",
            )),
            "galleries": _rows(conn, "galleries", (
                "id", "title", "slug", "description", "status", "featured",
                "cover_photo_id", "owner_id", "created_at", "updated_at",
            )),
            "photos": _rows(conn, "photos", PHOTOS_COLUMNS),
            "media": _rows(conn, "media", MEDIA_COLUMNS),
            "media_derivatives": _rows(
                conn, "media_derivatives", MEDIA_DERIVATIVES_COLUMNS
            ),
        }
    filename = f"mztlab-{now_iso()[:10]}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportV3Response)
def import_site(
    payload: ImportV3Request,
    confirm: str | None = Query(
        None,
        description="Destructive restore confirmation; `replace-all` is equivalent "
        "to `confirm: true` in the body.",
    ),
    user: dict = Depends(require_permission("data.export")),
) -> dict[str, Any]:
    """Replace all site data with a v3 backup document."""
    # Stable `import.*` error codes for unsupported documents, before the
    # destructive confirmation check and before any row is touched.
    if payload.format != EXPORT_FORMAT:
        raise ApiError(
            409,
            "import.format_unsupported",
            "不支持的备份格式，仅支持 mztlab-scene-export",
            field="format",
        )
    if payload.version != EXPORT_VERSION:
        raise ApiError(
            409,
            "import.version_unsupported",
            f"不支持的备份版本，仅支持 version={EXPORT_VERSION}",
            field="version",
        )
    confirmed = payload.confirm or (confirm or "").strip().lower() in {
        "replace-all",
        "true",
        "1",
        "yes",
    }
    if not confirmed:
        raise ApiError(
            409,
            "import.confirm_required",
            "恢复会覆盖全部数据，请传入 confirm=true 或 ?confirm=replace-all",
            field="confirm",
        )
    return import_document(payload.model_dump())
