"""Post queries and JSON shaping shared by the public and admin APIs."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Iterable

from .avatars import clean_avatar_url
from .content import extract_toc, quote_slug, reading_time
from .db import load_settings_cached, now_iso
from .images import image_payload, rewrite_inline_images, url_to_filename

PUBLIC_CONDITION = (
    "p.type = ? AND p.status IN ('published', 'scheduled') "
    "AND p.published_at IS NOT NULL AND p.published_at <= ?"
)


def _in_clause(values: Iterable[int]) -> str:
    values = list(values)
    return ",".join("?" for _ in values) if values else "NULL"


def attach_taxonomies(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    """Attach tags/categories/comment counts to mutable dicts in place."""
    if not rows:
        return
    by_id = {int(row["id"]): row for row in rows}
    ids = list(by_id)
    placeholders = _in_clause(ids)

    categories: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    tags: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    comment_counts: dict[int, int] = {i: 0 for i in ids}

    for row in conn.execute(
        f"""SELECT pc.post_id, c.id, c.name, c.slug, c.description
            FROM post_categories pc JOIN categories c ON c.id = pc.category_id
            WHERE pc.post_id IN ({placeholders}) ORDER BY c.name""",
        ids,
    ):
        categories[int(row["post_id"])].append(
            {"id": row["id"], "name": row["name"], "slug": row["slug"]}
        )

    for row in conn.execute(
        f"""SELECT pt.post_id, t.id, t.name, t.slug, t.description
            FROM post_tags pt JOIN tags t ON t.id = pt.tag_id
            WHERE pt.post_id IN ({placeholders}) ORDER BY t.name""",
        ids,
    ):
        tags[int(row["post_id"])].append(
            {"id": row["id"], "name": row["name"], "slug": row["slug"]}
        )

    for row in conn.execute(
        f"""SELECT post_id, COUNT(*) AS n FROM comments
            WHERE status = 'approved' AND post_id IN ({placeholders})
            GROUP BY post_id""",
        ids,
    ):
        comment_counts[int(row["post_id"])] = int(row["n"])

    for post_id, row in by_id.items():
        row["categories"] = categories[post_id]
        row["tags"] = tags[post_id]
        row["comment_count"] = comment_counts[post_id]


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


def _attach_cover_images(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    settings: dict[str, Any],
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


def serialize_post(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    detail: bool = False,
    admin: bool = False,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(row)
    settings = settings or load_settings_cached()
    attach_taxonomies(conn, [data])
    author = {
        "name": data.get("author_name") or "MZTLAB",
        "username": data.get("author_username") or "",
        "avatar": clean_avatar_url(data.get("author_avatar") or ""),
        "bio": data.get("author_bio") or "",
    }
    item: dict[str, Any] = {
        "id": data["id"],
        "type": data["type"],
        "title": data["title"],
        "slug": data["slug"],
        "url": public_url(data),
        "excerpt": data["excerpt"],
        "cover_image": data["cover_image"],
        "status": effective_status(data),
        "featured": bool(data["featured"]),
        "allow_comments": bool(data["allow_comments"]),
        "published_at": data["published_at"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "reading_time": reading_time(data.get("content_md", "")),
        "view_count": data["view_count"],
        "comment_count": data["comment_count"],
        "author": author,
        "categories": data["categories"],
        "tags": data["tags"],
        "seo_title": data.get("seo_title", ""),
        "seo_description": data.get("seo_description", ""),
        "project_year": data.get("project_year", ""),
        "project_role": data.get("project_role", ""),
        "project_client": data.get("project_client", ""),
        "project_kind": data.get("project_kind", ""),
        "project_url": data.get("project_url", ""),
    }
    if detail:
        item["content_html"] = (
            data["content_html"]
            if admin
            else rewrite_inline_images(data["content_html"], conn, settings)
        )
        item["toc"] = extract_toc(data["content_html"])
    if admin:
        item.update(
            {
                "content_md": data["content_md"],
                "raw_status": data["status"],
                "author_id": data["author_id"],
                "owner_id": data["author_id"],
                "revision_count": data.get("revision_count", 0),
            }
        )
    else:
        # Never leak e-mail addresses or the author's internal ids.
        item["author"].pop("username", None)
    _attach_cover_images(conn, [item], settings)
    return item


def serialize_posts(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    admin: bool = False,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # One taxonomy pass for the whole page instead of N+1 queries.
    settings = settings or load_settings_cached()
    mutable: list[dict[str, Any]] = [dict(row) for row in rows]
    attach_taxonomies(conn, mutable)
    result = []
    for row in mutable:
        # serialize_post re-queries one post for detail only; for lists we feed
        # the row through a tiny shim that keeps the already attached data.
        result.append(_list_item(row, admin=admin))
    _attach_cover_images(conn, result, settings)
    return result


def _list_item(data: dict[str, Any], *, admin: bool) -> dict[str, Any]:
    item = {
        "id": data["id"],
        "type": data["type"],
        "title": data["title"],
        "slug": data["slug"],
        "url": public_url(data),
        "excerpt": data["excerpt"],
        "cover_image": data["cover_image"],
        "status": effective_status(data),
        "featured": bool(data["featured"]),
        "allow_comments": bool(data["allow_comments"]),
        "published_at": data["published_at"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "reading_time": reading_time(data.get("content_md", "")),
        "view_count": data["view_count"],
        "comment_count": data["comment_count"],
        "author": {
            "name": data.get("author_name") or "MZTLAB",
            "avatar": clean_avatar_url(data.get("author_avatar") or ""),
        },
        "categories": data["categories"],
        "tags": data["tags"],
        "project_year": data.get("project_year", ""),
        "project_role": data.get("project_role", ""),
        "project_client": data.get("project_client", ""),
        "project_kind": data.get("project_kind", ""),
        "project_url": data.get("project_url", ""),
    }
    if admin:
        item.update(
            {
                "raw_status": data["status"],
                "author_id": data["author_id"],
                "owner_id": data["author_id"],
                "seo_title": data.get("seo_title", ""),
                "seo_description": data.get("seo_description", ""),
                "revision_count": data.get("revision_count", 0),
            }
        )
    return item


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
        SELECT p.*, u.display_name AS author_name, u.username AS author_username,
               u.avatar AS author_avatar, u.bio AS author_bio
        FROM posts p LEFT JOIN users u ON u.id = p.author_id
    """


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
    author_id: int | None = None,
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

    if author_id is not None:
        where.append("p.author_id = ?")
        args.append(author_id)

    if tag:
        joins.append("JOIN post_tags pt_filter ON pt_filter.post_id = p.id")
        joins.append("JOIN tags t_filter ON t_filter.id = pt_filter.tag_id")
        where.append("t_filter.slug = ?")
        args.append(tag)
    if category:
        joins.append("JOIN post_categories pc_filter ON pc_filter.post_id = p.id")
        joins.append("JOIN categories c_filter ON c_filter.id = pc_filter.category_id")
        where.append("c_filter.slug = ?")
        args.append(category)
    if featured is not None:
        where.append("p.featured = ?")
        args.append(1 if featured else 0)
    if q:
        # Search the body *and* the metadata: project fields, taxonomy names and
        # the author, so "2025" or "全栈" can find a project too.
        where.append(
            "(p.title LIKE ? OR p.excerpt LIKE ? OR p.content_md LIKE ? "
            "OR p.seo_description LIKE ? OR p.project_year LIKE ? "
            "OR p.project_role LIKE ? OR p.project_client LIKE ? "
            "OR p.project_kind LIKE ? "
            "OR (SELECT uq.display_name FROM users uq WHERE uq.id = p.author_id) LIKE ? "
            "OR EXISTS (SELECT 1 FROM post_tags ptq JOIN tags tq ON tq.id = ptq.tag_id "
            "           WHERE ptq.post_id = p.id AND tq.name LIKE ?) "
            "OR EXISTS (SELECT 1 FROM post_categories pcq "
            "           JOIN categories cq ON cq.id = pcq.category_id "
            "           WHERE pcq.post_id = p.id AND cq.name LIKE ?))"
        )
        needle = f"%{q.strip()}%"
        args.extend([needle] * 11)

    base = _base_select()
    if joins:
        base += " " + " ".join(joins)
    if where:
        base += " WHERE " + " AND ".join(where)

    count_sql = f"SELECT COUNT(DISTINCT p.id) AS n FROM posts p {' '.join(joins)}"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = int(conn.execute(count_sql, args).fetchone()["n"])

    if admin:
        order = "p.updated_at DESC, p.id DESC"
    else:
        order = "p.featured DESC, p.published_at DESC, p.id DESC"
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
        sql += "p.slug = ?"
        args.append(slug)
    else:
        return None
    if post_type:
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
    categories = [
        int(r["category_id"])
        for r in conn.execute(
            "SELECT category_id FROM post_categories WHERE post_id = ?", (row["id"],)
        )
    ]
    tags = [
        int(r["tag_id"])
        for r in conn.execute("SELECT tag_id FROM post_tags WHERE post_id = ?", (row["id"],))
    ]
    clauses = []
    args: list[Any] = []
    if categories:
        clauses.append(
            f"EXISTS (SELECT 1 FROM post_categories pc WHERE pc.post_id = p.id AND pc.category_id IN ({_in_clause(categories)}))"
        )
        args.extend(categories)
    if tags:
        clauses.append(
            f"EXISTS (SELECT 1 FROM post_tags pt WHERE pt.post_id = p.id AND pt.tag_id IN ({_in_clause(tags)}))"
        )
        args.extend(tags)

    rows: list[sqlite3.Row] = []
    if clauses:
        rows = list(
            conn.execute(
                f"""{_base_select()} WHERE {PUBLIC_CONDITION} AND p.id != ?
                    AND ({' OR '.join(clauses)})
                    ORDER BY p.published_at DESC LIMIT ?""",
                ["post", now_iso(), row["id"], *args, limit],
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
