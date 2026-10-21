"""Post queries and JSON shaping shared by the public and admin APIs.

3.0.0 keeps posts/projects/pages in class-table inheritance (`posts` +
`project_details`), stores ownership in a single `owner_id`, and never touches
comments or view counts (both features removed).
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Iterable

from .avatars import clean_avatar_url
from .content import extract_toc, quote_slug, reading_time
from .db import now_iso
from .images import image_payload, rewrite_inline_images, url_to_filename
from .settings import Settings, load_settings_cached

PUBLIC_CONDITION = (
    "p.type = ? AND p.status IN ('published', 'scheduled') "
    "AND p.published_at IS NOT NULL AND p.published_at <= ?"
)

POST_TYPES = ("post", "project", "page")


def _in_clause(values: Iterable[int]) -> str:
    values = list(values)
    return ",".join("?" for _ in values) if values else "NULL"


def attach_taxonomies(conn: sqlite3.Connection, rows: list[dict[str, Any] | sqlite3.Row]) -> None:
    """Attach categories/tags to mutable dicts in place, one query per kind."""
    if not rows:
        return
    by_id = {int(row["id"]): row for row in rows}
    ids = list(by_id)
    placeholders = _in_clause(ids)

    categories: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    tags: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    for row in conn.execute(
        f"""SELECT pt.post_id, t.id, t.kind, t.name, t.slug, t.description
            FROM post_terms pt JOIN taxonomy_terms t ON t.id = pt.term_id
            WHERE pt.post_id IN ({placeholders}) ORDER BY t.name""",
        ids,
    ):
        target = categories if row["kind"] == "category" else tags
        target[int(row["post_id"])].append(
            {"id": row["id"], "name": row["name"], "slug": row["slug"]}
        )

    # The query above yields one row per (post, term); seed all bucket lists so
    # rows without any term still get empty arrays.
    for post_id, row in by_id.items():
        row["categories"] = categories[post_id]
        row["tags"] = tags[post_id]


def effective_status(row: dict[str, Any] | sqlite3.Row) -> str:
    status = row["status"]
    published_at = row["published_at"]
    if status == "scheduled" and published_at and published_at <= now_iso():
        return "published"
    return status


def public_url(row: dict[str, Any] | sqlite3.Row) -> str:
    if row["type"] == "page":
        return f"/{quote_slug(row['slug'])}"
    if row["type"] == "project":
        return f"/projects/{quote_slug(row['slug'])}"
    return f"/posts/{quote_slug(row['slug'])}"


def _project_fields(data: dict[str, Any]) -> dict[str, str]:
    return {
        "project_year": data.get("project_year") or "",
        "project_role": data.get("project_role") or "",
        "project_client": data.get("project_client") or "",
        "project_kind": data.get("project_kind") or "",
        "project_url": data.get("project_url") or "",
    }


def _reading_minutes(data: dict[str, Any]) -> int:
    """Use the materialised value; only fall back for legacy/partial rows."""
    stored = data.get("reading_time")
    if isinstance(stored, int) and stored > 0:
        return stored
    return reading_time(data.get("content_md", ""))


def _toc(data: dict[str, Any], *, detail: bool) -> list[dict[str, Any]]:
    if not detail:
        return []
    raw = data.get("toc_json")
    if isinstance(raw, str) and raw:
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return value
        except json.JSONDecodeError:
            pass
    return extract_toc(data.get("content_html", ""))


def _author(data: dict[str, Any]) -> dict[str, str]:
    return {
        "name": data.get("author_name") or "MZTLAB",
        "username": data.get("author_username") or "",
        "avatar": clean_avatar_url(data.get("author_avatar") or ""),
        "bio": data.get("author_bio") or "",
    }


def _attach_cover_images(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    settings: Settings,
) -> None:
    """Resolve `cover_image` URLs to media rows and attach image metadata."""
    filenames: list[str] = []
    for item in items:
        item["cover"] = None
        filename = url_to_filename(item.get("cover_image") or "")
        if filename and filename not in filenames:
            filenames.append(filename)
    if not filenames:
        return
    placeholders = ",".join("?" for _ in filenames)
    rows = conn.execute(
        f"SELECT * FROM media WHERE filename IN ({placeholders})", filenames
    ).fetchall()
    payloads = {row["filename"]: image_payload(row, settings) for row in rows}
    for item in items:
        filename = url_to_filename(item.get("cover_image") or "")
        if filename:
            item["cover"] = payloads.get(filename)


def _base_item(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data["id"],
        "type": data["type"],
        "title": data["title"],
        "slug": data["slug"],
        "url": public_url(data),
        "excerpt": data["excerpt"],
        "cover_image": data["cover_image"],
        "status": effective_status(data),
        "featured": bool(data["featured"]),
        "published_at": data["published_at"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "reading_time": _reading_minutes(data),
        "author": {
            "name": data.get("author_name") or "MZTLAB",
            "avatar": clean_avatar_url(data.get("author_avatar") or ""),
        },
        "categories": data.get("categories", []),
        "tags": data.get("tags", []),
        **_project_fields(data),
    }


def serialize_post(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    detail: bool = False,
    admin: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    data = dict(row)
    resolved = settings or load_settings_cached()
    attach_taxonomies(conn, [data])
    item = _base_item(data)
    item["author"] = _author(data)
    item["seo_title"] = data.get("seo_title", "")
    item["seo_description"] = data.get("seo_description", "")
    if detail:
        # Inline image URLs are still rewritten at read time; the media phase
        # moves this into the write/render pipeline (R4/ADR-10).
        item["content_html"] = (
            data["content_html"]
            if admin
            else rewrite_inline_images(data["content_html"], conn, resolved)
        )
        item["toc"] = _toc(data, detail=True)
    if admin:
        item.update(
            {
                "content_md": data["content_md"],
                "raw_status": data["status"],
                "owner_id": data["owner_id"],
                "revision_count": data.get("revision_count", 0),
                "render_version": data.get("render_version", 0),
            }
        )
    else:
        # Never leak e-mail addresses or internal ids.
        item["author"].pop("username", None)
    _attach_cover_images(conn, [item], resolved)
    return item


def serialize_posts(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    admin: bool = False,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    # One taxonomy pass for the whole page instead of N+1 queries.
    resolved = settings or load_settings_cached()
    mutable: list[dict[str, Any]] = [dict(row) for row in rows]
    attach_taxonomies(conn, mutable)
    result: list[dict[str, Any]] = []
    for data in mutable:
        item = _base_item(data)
        if admin:
            item.update(
                {
                    "raw_status": data["status"],
                    "owner_id": data["owner_id"],
                    "seo_title": data.get("seo_title", ""),
                    "seo_description": data.get("seo_description", ""),
                    "revision_count": data.get("revision_count", 0),
                }
            )
        result.append(item)
    _attach_cover_images(conn, result, resolved)
    return result


def pagination(page: int, per_page: int, total: int) -> dict[str, Any]:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def _base_select() -> str:
    return """
        SELECT p.*, pd.kind AS project_kind, pd.year AS project_year,
               pd.role AS project_role, pd.client AS project_client,
               pd.url AS project_url,
               u.display_name AS author_name, u.username AS author_username,
               u.avatar AS author_avatar, u.bio AS author_bio
        FROM posts p
        LEFT JOIN project_details pd ON pd.post_id = p.id
        LEFT JOIN users u ON u.id = p.owner_id
    """


def _search_clause() -> str:
    # Metadata search (year/role/client/kind/taxonomy) is still LIKE-based; the
    # FTS5 index arrives in Phase 5.
    return (
        "(p.title LIKE ? OR p.excerpt LIKE ? OR p.content_md LIKE ? "
        "OR p.seo_description LIKE ? OR COALESCE(pd.year, '') LIKE ? "
        "OR COALESCE(pd.role, '') LIKE ? OR COALESCE(pd.client, '') LIKE ? "
        "OR COALESCE(pd.kind, '') LIKE ? "
        "OR (SELECT uq.display_name FROM users uq WHERE uq.id = p.owner_id) LIKE ? "
        "OR EXISTS (SELECT 1 FROM post_terms ptq "
        "           JOIN taxonomy_terms tq ON tq.id = ptq.term_id "
        "           WHERE ptq.post_id = p.id AND tq.name LIKE ?))"
    )


def fetch_posts(
    conn: sqlite3.Connection,
    *,
    post_type: str = "post",
    page: int = 1,
    per_page: int = 9,
    tag: str | None = None,
    category: str | None = None,
    q: str | None = None,
    featured: bool | None = None,
    admin: bool = False,
    status: str | None = None,
    owner_id: int | None = None,
) -> tuple[list[sqlite3.Row], int]:
    page = max(1, page)
    per_page = max(1, min(per_page, 50))
    joins: list[str] = []
    where: list[str] = []
    args: list[Any] = []

    if admin:
        where.append("p.type = ?")
        args.append(post_type)
        if status in {"draft", "published", "scheduled"}:
            where.append("p.status = ?")
            args.append(status)
    else:
        where.append(PUBLIC_CONDITION)
        args.extend([post_type, now_iso()])

    if owner_id is not None:
        where.append("p.owner_id = ?")
        args.append(owner_id)

    if tag or category:
        joins.append("JOIN post_terms pt_filter ON pt_filter.post_id = p.id")
        joins.append("JOIN taxonomy_terms t_filter ON t_filter.id = pt_filter.term_id")
        where.append("t_filter.kind = ?")
        args.append("tag" if tag else "category")
        where.append("t_filter.slug = ?")
        args.append(tag or category)
    if featured is not None:
        where.append("p.featured = ?")
        args.append(1 if featured else 0)
    if q:
        where.append(_search_clause())
        needle = f"%{q.strip()}%"
        args.extend([needle] * 10)

    base = _base_select()
    if joins:
        base += " " + " ".join(joins)
    if where:
        base += " WHERE " + " AND ".join(where)

    count_sql = (
        "SELECT COUNT(DISTINCT p.id) AS n FROM posts p "
        "LEFT JOIN project_details pd ON pd.post_id = p.id "
        f"{' '.join(joins)}"
    )
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = int(conn.execute(count_sql, args).fetchone()["n"])

    order = (
        "p.updated_at DESC, p.id DESC"
        if admin
        else "p.featured DESC, p.published_at DESC, p.id DESC"
    )
    sql = f"{base} ORDER BY {order} LIMIT ? OFFSET ?"
    rows = list(conn.execute(sql, [*args, per_page, (page - 1) * per_page]))
    return rows, total


def get_post(
    conn: sqlite3.Connection,
    *,
    post_id: int | None = None,
    slug: str | None = None,
    post_type: str | None = None,
    public: bool = False,
) -> sqlite3.Row | None:
    sql = _base_select() + " WHERE "
    args: list[Any] = []
    if post_id is not None:
        sql += "p.id = ?"
        args.append(post_id)
    elif slug is not None:
        if post_type:
            # Class-table inheritance keeps slugs unique per type.
            sql += "p.slug = ? AND p.type = ?"
            args.extend([slug, post_type])
        else:
            sql += "p.slug = ?"
            args.append(slug)
    else:
        return None
    if post_type and post_id is not None:
        sql += " AND p.type = ?"
        args.append(post_type)
    if public:
        sql += (
            " AND p.status IN ('published', 'scheduled')"
            " AND p.published_at IS NOT NULL AND p.published_at <= ?"
        )
        args.append(now_iso())
    return conn.execute(sql, args).fetchone()


def adjacent_posts(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    published = row["published_at"]
    if not published:
        return None, None
    prev = conn.execute(
        f"""{_base_select()} WHERE {PUBLIC_CONDITION} AND p.published_at < ?
            ORDER BY p.published_at DESC LIMIT 1""",
        ("post", now_iso(), published),
    ).fetchone()
    nxt = conn.execute(
        f"""{_base_select()} WHERE {PUBLIC_CONDITION} AND p.published_at > ?
            ORDER BY p.published_at ASC LIMIT 1""",
        ("post", now_iso(), published),
    ).fetchone()

    def brief(item: sqlite3.Row | None) -> dict[str, Any] | None:
        if not item:
            return None
        return {"title": item["title"], "slug": item["slug"], "url": public_url(item)}

    return brief(prev), brief(nxt)


def related_posts(
    conn: sqlite3.Connection, row: sqlite3.Row, limit: int = 3
) -> list[dict[str, Any]]:
    term_ids = [
        int(r["term_id"])
        for r in conn.execute(
            "SELECT term_id FROM post_terms WHERE post_id = ?", (row["id"],)
        )
    ]
    rows: list[sqlite3.Row] = []
    if term_ids:
        placeholders = _in_clause(term_ids)
        rows = list(
            conn.execute(
                f"""{_base_select()} WHERE {PUBLIC_CONDITION} AND p.id != ?
                    AND EXISTS (SELECT 1 FROM post_terms pt WHERE pt.post_id = p.id
                                AND pt.term_id IN ({placeholders}))
                    ORDER BY p.published_at DESC LIMIT ?""",
                ["post", now_iso(), row["id"], *term_ids, limit],
            )
        )
    if len(rows) < limit:
        exclude = [row["id"], *[int(item["id"]) for item in rows]]
        placeholders = _in_clause(exclude)
        more = list(
            conn.execute(
                f"""{_base_select()} WHERE {PUBLIC_CONDITION}
                    AND p.id NOT IN ({placeholders})
                    ORDER BY p.published_at DESC LIMIT ?""",
                ["post", now_iso(), *exclude, limit - len(rows)],
            )
        )
        rows.extend(more)
    return serialize_posts(conn, rows)
