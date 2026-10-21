"""Admin taxonomy API for categories and tags.

Both kinds live in `taxonomy_terms` (`kind='category'|'tag'`) and are linked to
content through `post_terms`; slug and name uniqueness is per kind.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from ..api.models import (
    TaxonomyAdminResponse,
    TaxonomyDeleteResponse,
    TaxonomyTermResponse,
)
from ..content import slugify
from ..db import db, now_iso
from ..deps import require_permission, require_staff
from ..errors import ApiError
from ..schemas import TaxonomyIn
from ..services.content_admin import term_kind

router = APIRouter(
    prefix="/admin",
    tags=["taxonomy"],
    dependencies=[Depends(require_staff)],
)


def _term_rows(conn: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """SELECT t.id, t.name, t.slug, t.description,
                      (SELECT COUNT(*) FROM post_terms pt
                       WHERE pt.term_id = t.id) AS count
               FROM taxonomy_terms t WHERE t.kind = ?
               ORDER BY t.name""",
            (kind,),
        )
    ]


def _term_or_404(conn: sqlite3.Connection, kind: str, term_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM taxonomy_terms WHERE id = ? AND kind = ?", (term_id, kind)
    ).fetchone()
    if not row:
        raise ApiError(404, "taxonomy.not_found", "条目不存在")
    return row


def _unique_term_slug(
    conn: sqlite3.Connection, kind: str, value: str, *, term_id: int | None = None
) -> str:
    base = slugify(value, fallback="item")
    candidate = base
    number = 2
    while conn.execute(
        "SELECT 1 FROM taxonomy_terms WHERE kind = ? AND slug = ? "
        "AND (? IS NULL OR id != ?)",
        (kind, candidate, term_id, term_id),
    ).fetchone():
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def _assert_name_free(
    conn: sqlite3.Connection, kind: str, name: str, *, term_id: int | None = None
) -> None:
    conflict = conn.execute(
        "SELECT 1 FROM taxonomy_terms WHERE kind = ? AND name = ? COLLATE NOCASE "
        "AND (? IS NULL OR id != ?)",
        (kind, name, term_id, term_id),
    ).fetchone()
    if conflict:
        raise ApiError(409, "taxonomy.name_taken", "同名条目已存在", field="name")


@router.get("/taxonomy", response_model=TaxonomyAdminResponse)
def admin_taxonomy() -> dict[str, Any]:
    with db() as conn:
        categories = _term_rows(conn, "category")
        tags = _term_rows(conn, "tag")
    return {"categories": categories, "tags": tags}


@router.post("/taxonomy/{kind}", status_code=201, response_model=TaxonomyTermResponse)
def create_term(
    kind: str,
    payload: TaxonomyIn,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    db_kind = term_kind(kind)
    with db() as conn:
        _assert_name_free(conn, db_kind, payload.name)
        slug = _unique_term_slug(conn, db_kind, payload.slug or payload.name)
        cur = conn.execute(
            """INSERT INTO taxonomy_terms(kind, name, slug, description, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (db_kind, payload.name, slug, payload.description, now_iso()),
        )
        assert cur.lastrowid is not None  # INSERT always assigns a rowid
        row = _term_or_404(conn, db_kind, int(cur.lastrowid))
    return dict(row)


@router.patch("/taxonomy/{kind}/{term_id}", response_model=TaxonomyTermResponse)
def update_term(
    kind: str,
    term_id: int,
    payload: TaxonomyIn,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    db_kind = term_kind(kind)
    with db() as conn:
        row = _term_or_404(conn, db_kind, term_id)
        _assert_name_free(conn, db_kind, payload.name, term_id=term_id)
        slug = _unique_term_slug(
            conn,
            db_kind,
            payload.slug or str(row["slug"]) or payload.name,
            term_id=term_id,
        )
        conn.execute(
            "UPDATE taxonomy_terms SET name = ?, slug = ?, description = ? "
            "WHERE id = ?",
            (payload.name, slug, payload.description, term_id),
        )
        updated = _term_or_404(conn, db_kind, term_id)
    return dict(updated)


@router.delete("/taxonomy/{kind}/{term_id}", response_model=TaxonomyDeleteResponse)
def delete_term(
    kind: str,
    term_id: int,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    db_kind = term_kind(kind)
    with db() as conn:
        row = _term_or_404(conn, db_kind, term_id)
        conn.execute("DELETE FROM taxonomy_terms WHERE id = ?", (term_id,))
    return {"ok": True, "deleted": term_id, "name": row["name"]}
