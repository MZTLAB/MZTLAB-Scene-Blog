"""Authenticated admin API.

All routes require a valid session cookie. Unsafe requests additionally need
the `X-Blog-Request: 1` header, enforced in main.py, which makes cross-site
form posts impossible.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..config import VERSION
from ..content import (
    make_excerpt,
    normalize_iso_datetime,
    reading_time,
    render_markdown,
    slugify,
)
from ..db import db, load_settings, now_iso, public_settings, save_settings
from ..defaults import (
    COLOR_MODES,
    FONT_PAIRS,
    HERO_STYLES,
    IMAGE_SCENES,
    POST_LAYOUTS,
    SECRET_SETTING_KEYS,
    STORAGE_BACKENDS,
    STORAGE_SERVE_MODES,
    THEMES,
    UPLOAD_AUDIO_FORMATS,
    UPLOAD_FILE_FORMATS,
    UPLOAD_FORMAT_ALIASES,
    UPLOAD_IMAGE_FORMATS,
    default_settings,
)
from ..deps import require_permission, require_staff
from ..galleries import public_counts
from ..images import AVIF_SUPPORTED, WEBP_SUPPORTED
from ..permissions import ROLE_LABELS, can, owns
from ..posts import fetch_posts, get_post, pagination, serialize_post, serialize_posts
from ..storage import reset_storage
from ..schemas import (
    AppearanceIn,
    CommentStatusIn,
    PostIn,
    PreviewIn,
    ProfileIn,
    TaxonomyIn,
)
from ..security import (
    hash_password,
    password_policy_error,
    preview_limiter,
    verify_password,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_staff)],
)

RESERVED_PAGE_SLUGS = {
    "admin", "api", "media", "posts", "archive", "search", "tags",
    "categories", "photos", "galleries", "projects", "rss.xml",
    "sitemap.xml", "robots.txt", "setup", "login",
}

PostType = Literal["post", "page", "project"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_slug(
    conn: sqlite3.Connection,
    value: str,
    *,
    post_id: int | None = None,
    is_page: bool = False,
) -> str:
    base = slugify(value, fallback="page" if is_page else "post")
    candidate = base
    number = 2
    while True:
        if is_page and candidate in RESERVED_PAGE_SLUGS:
            candidate = f"{base}-{number}"
            number += 1
            continue
        row = conn.execute(
            "SELECT id FROM posts WHERE slug = ? AND (? IS NULL OR id != ?)",
            (candidate, post_id, post_id),
        ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}-{number}"
        number += 1


def _normalize_schedule(
    status: str, published_at: str | None
) -> tuple[str, str | None]:
    now = now_iso()
    published = normalize_iso_datetime(published_at)
    if status == "draft":
        return "draft", published
    if not published:
        published = now
    if status == "published" and published > now:
        return "scheduled", published
    if status == "scheduled" and published <= now:
        return "published", published
    return status, published


def _upsert_term(
    conn: sqlite3.Connection, kind: str, name: str
) -> int:
    table = "categories" if kind == "categories" else "tags"
    row = conn.execute(
        f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return int(row["id"])
    base = slugify(name, fallback="item")
    candidate = base
    number = 2
    while conn.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{base}-{number}"
        number += 1
    now = now_iso()
    cur = conn.execute(
        f"INSERT INTO {table}(name, slug, description, created_at) VALUES (?, ?, '', ?)",
        (name, candidate, now),
    )
    return int(cur.lastrowid)


def _set_terms(conn: sqlite3.Connection, post_id: int, payload: PostIn) -> None:
    conn.execute("DELETE FROM post_tags WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM post_categories WHERE post_id = ?", (post_id,))
    for name in payload.tags:
        tag_id = _upsert_term(conn, "tags", name)
        conn.execute(
            "INSERT OR IGNORE INTO post_tags(post_id, tag_id) VALUES (?, ?)",
            (post_id, tag_id),
        )
    for name in payload.categories:
        category_id = _upsert_term(conn, "categories", name)
        conn.execute(
            "INSERT OR IGNORE INTO post_categories(post_id, category_id) VALUES (?, ?)",
            (post_id, category_id),
        )


def _save_revision(
    conn: sqlite3.Connection, row: sqlite3.Row, user_id: int
) -> None:
    conn.execute(
        """INSERT INTO revisions(post_id, title, excerpt, content_md, author_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (row["id"], row["title"], row["excerpt"], row["content_md"], user_id, now_iso()),
    )
    conn.execute(
        """DELETE FROM revisions WHERE post_id = ? AND id NOT IN (
               SELECT id FROM revisions WHERE post_id = ? ORDER BY id DESC LIMIT 25
           )""",
        (row["id"], row["id"]),
    )


def _page_counts(
    conn: sqlite3.Connection, post_type: str, *, author_id: int | None = None
) -> dict[str, int]:
    counts = {"all": 0, "published": 0, "draft": 0, "scheduled": 0}
    sql = "SELECT status, COUNT(*) AS n FROM posts WHERE type = ?"
    args: list[Any] = [post_type]
    if author_id is not None:
        sql += " AND author_id = ?"
        args.append(author_id)
    for row in conn.execute(sql + " GROUP BY status", args):
        counts[row["status"]] = int(row["n"])
        counts["all"] += int(row["n"])
    return counts


def _assert_can_edit(user: dict[str, Any], row: Any, *, action: str = "编辑") -> None:
    """Authors may only touch rows they created; editors and admins may touch all."""
    if can(user, "content.others") or owns(user, row):
        return
    raise HTTPException(status_code=403, detail=f"只能{action}自己创建的内容")


def _resolve_author_id(
    user: dict[str, Any],
    conn: sqlite3.Connection,
    requested: int | None,
    current: int | None,
) -> int | None:
    """Validate an ownership transfer request (or keep the current author)."""
    if requested is None or requested == current:
        return current
    if not can(user, "content.others"):
        raise HTTPException(
            status_code=403,
            detail="只有管理员或可管理他人内容的编辑可以转移作者",
        )
    target = conn.execute(
        "SELECT id, role, is_active FROM users WHERE id = ?", (requested,)
    ).fetchone()
    if not target or not target["is_active"]:
        raise HTTPException(status_code=400, detail="目标作者不存在或已停用")
    return int(target["id"])


def _post_request(payload: PostIn, user_id: int, post_type: str) -> dict[str, Any]:
    status, published = _normalize_schedule(payload.status, payload.published_at)
    content = payload.content_md.strip()
    if content:
        content += "\n"
    is_page = post_type == "page"
    is_project = post_type == "project"
    return {
        "type": post_type,
        "title": payload.title,
        "excerpt": payload.excerpt or make_excerpt(content, 180),
        "content_md": content,
        "content_html": render_markdown(content),
        "cover_image": payload.cover_image,
        "status": status,
        "featured": 1 if payload.featured and not is_page else 0,
        "allow_comments": 1 if payload.allow_comments and not is_page and not is_project else 0,
        "published_at": published,
        "seo_title": payload.seo_title,
        "seo_description": payload.seo_description,
        "project_year": payload.project_year if is_project else "",
        "project_role": payload.project_role if is_project else "",
        "project_client": payload.project_client if is_project else "",
        "project_kind": payload.project_kind if is_project else "",
        "project_url": payload.project_url if is_project else "",
        "user_id": user_id,
        "slug_source": payload.slug or payload.title,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/stats")
def stats() -> dict[str, Any]:
    with db() as conn:
        def scalar(sql: str, args: tuple = ()) -> int:
            return int(conn.execute(sql, args).fetchone()[0])

        post_counts = _page_counts(conn, "post")
        project_counts = _page_counts(conn, "project")
        recent = serialize_posts(
            conn,
            list(
                conn.execute(
                    """SELECT p.*, u.display_name AS author_name, u.avatar AS author_avatar
                       FROM posts p LEFT JOIN users u ON u.id = p.author_id
                       WHERE p.type = 'post' ORDER BY p.updated_at DESC LIMIT 5"""
                )
            ),
            admin=True,
        )
        recent_projects = serialize_posts(
            conn,
            list(
                conn.execute(
                    """SELECT p.*, u.display_name AS author_name, u.avatar AS author_avatar
                       FROM posts p LEFT JOIN users u ON u.id = p.author_id
                       WHERE p.type = 'project' ORDER BY p.updated_at DESC LIMIT 5"""
                )
            ),
            admin=True,
        )
        pending = [
            dict(row)
            for row in conn.execute(
                """SELECT c.*, p.title AS post_title, p.slug AS post_slug
                   FROM comments c JOIN posts p ON p.id = c.post_id
                   WHERE c.status = 'pending' ORDER BY c.created_at DESC LIMIT 5"""
            )
        ]
        top_posts = [
            dict(row)
            for row in conn.execute(
                """SELECT id, title, slug, view_count, published_at FROM posts
                   WHERE type = 'post' AND status IN ('published','scheduled')
                   ORDER BY view_count DESC LIMIT 5"""
            )
        ]
        recent_comments = [
            dict(row)
            for row in conn.execute(
                """SELECT c.id, c.author_name, c.content, c.status, c.created_at,
                          p.title AS post_title
                   FROM comments c JOIN posts p ON p.id = c.post_id
                   ORDER BY c.created_at DESC LIMIT 5"""
            )
        ]
        pages_count = scalar("SELECT COUNT(*) FROM posts WHERE type = 'page'")
        gallery_count = scalar("SELECT COUNT(*) FROM galleries")
        photo_count = scalar("SELECT COUNT(*) FROM photos")
        comment_counts = {
            "all": scalar("SELECT COUNT(*) FROM comments"),
            "pending": scalar("SELECT COUNT(*) FROM comments WHERE status = 'pending'"),
            "approved": scalar("SELECT COUNT(*) FROM comments WHERE status = 'approved'"),
            "spam": scalar("SELECT COUNT(*) FROM comments WHERE status = 'spam'"),
        }
        media_count = scalar("SELECT COUNT(*) FROM media")
        total_views = scalar("SELECT COALESCE(SUM(view_count), 0) FROM posts")
        tag_count = scalar("SELECT COUNT(*) FROM tags")
        category_count = scalar("SELECT COUNT(*) FROM categories")
        recent_galleries = [
            dict(row)
            for row in conn.execute(
                """SELECT g.id, g.title, g.slug, g.status, g.updated_at,
                          (SELECT COUNT(*) FROM photos ph WHERE ph.gallery_id = g.id) AS photo_count
                   FROM galleries g ORDER BY g.updated_at DESC LIMIT 4"""
            )
        ]
    return {
        "posts": post_counts,
        "projects": project_counts,
        "pages": pages_count,
        "comments": comment_counts,
        "media": media_count,
        "galleries": gallery_count,
        "photos": photo_count,
        "views": total_views,
        "tags": tag_count,
        "categories": category_count,
        "recent_posts": recent,
        "recent_projects": recent_projects,
        "recent_galleries": recent_galleries,
        "pending_comments": pending,
        "recent_comments": recent_comments,
        "top_posts": top_posts,
        "system": {"version": VERSION, "generated_at": now_iso()},
    }


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

@router.get("/posts")
def admin_posts(
    type: PostType = Query("post"),
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    status_filter = status if status in {"draft", "published", "scheduled"} else None
    # Authors only ever see their own shelf; editors and admins see everything.
    author_id = None if can(user, "content.others") else int(user["id"])
    with db() as conn:
        rows, total = fetch_posts(
            conn,
            post_type=type,
            page=page,
            per_page=per_page,
            q=q,
            admin=True,
            status=status_filter,
            author_id=author_id,
        )
        items = serialize_posts(conn, rows, admin=True)
        counts = _page_counts(conn, type, author_id=author_id)
    return {"items": items, "counts": counts, **pagination(page, per_page, total)}


@router.get("/posts/{post_id}")
def admin_post(
    post_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, post_id=post_id)
        if not row:
            raise HTTPException(status_code=404, detail="文章不存在")
        _assert_can_edit(user, row, action="查看")
        item = serialize_post(conn, row, detail=True, admin=True)
        item["revision_count"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM revisions WHERE post_id = ?", (post_id,)
            ).fetchone()[0]
        )
    return item


@router.post("/posts", status_code=201)
def create_post(
    payload: PostIn,
    type: PostType = Query("post"),
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    if payload.status != "draft" and not can(user, "content.publish"):
        raise HTTPException(status_code=403, detail="当前角色没有发布权限")
    is_page = type == "page"
    with db() as conn:
        author_id = _resolve_author_id(user, conn, payload.author_id, int(user["id"]))
        post = _post_request(payload, int(author_id), type)
        slug = _unique_slug(conn, post["slug_source"], is_page=is_page)
        now = now_iso()
        cur = conn.execute(
            """INSERT INTO posts(
                   type, title, slug, excerpt, content_md, content_html, cover_image,
                   status, featured, allow_comments, author_id, published_at,
                   created_at, updated_at, seo_title, seo_description,
                   project_year, project_role, project_client, project_kind, project_url,
                   view_count
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                post["type"], post["title"], slug, post["excerpt"], post["content_md"],
                post["content_html"], post["cover_image"], post["status"], post["featured"],
                post["allow_comments"], post["user_id"], post["published_at"],
                now, now, post["seo_title"], post["seo_description"],
                post["project_year"], post["project_role"], post["project_client"],
                post["project_kind"], post["project_url"],
            ),
        )
        post_id = int(cur.lastrowid)
        _set_terms(conn, post_id, payload)
        row = get_post(conn, post_id=post_id)
        assert row is not None
        item = serialize_post(conn, row, admin=True)
    return item


@router.put("/posts/{post_id}")
def update_post(
    post_id: int,
    payload: PostIn,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    if payload.status != "draft" and not can(user, "content.publish"):
        raise HTTPException(status_code=403, detail="当前角色没有发布权限")
    with db() as conn:
        row = get_post(conn, post_id=post_id)
        if not row:
            raise HTTPException(status_code=404, detail="文章不存在")
        _assert_can_edit(user, row)
        is_page = row["type"] == "page"
        author_id = _resolve_author_id(user, conn, payload.author_id, row["author_id"])
        post = _post_request(payload, int(user["id"]), row["type"])
        _save_revision(conn, row, int(user["id"]))
        slug = _unique_slug(
            conn,
            payload.slug or row["slug"],
            post_id=post_id,
            is_page=is_page,
        )
        conn.execute(
            """UPDATE posts SET title = ?, slug = ?, excerpt = ?, content_md = ?,
                   content_html = ?, cover_image = ?, status = ?, featured = ?,
                   allow_comments = ?, published_at = ?, updated_at = ?,
                   seo_title = ?, seo_description = ?,
                   project_year = ?, project_role = ?, project_client = ?,
                   project_kind = ?, project_url = ?, author_id = ?
               WHERE id = ?""",
            (
                post["title"], slug, post["excerpt"], post["content_md"],
                post["content_html"], post["cover_image"], post["status"],
                post["featured"], post["allow_comments"], post["published_at"],
                now_iso(), post["seo_title"], post["seo_description"],
                post["project_year"], post["project_role"], post["project_client"],
                post["project_kind"], post["project_url"], author_id, post_id,
            ),
        )
        _set_terms(conn, post_id, payload)
        fresh = get_post(conn, post_id=post_id)
        assert fresh is not None
        item = serialize_post(conn, fresh, admin=True)
    return item


@router.delete("/posts/{post_id}")
def delete_post(
    post_id: int, user: dict = Depends(require_permission("content.delete"))
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT type, title, author_id FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="文章不存在")
        _assert_can_edit(user, row, action="删除")
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return {"ok": True, "deleted": post_id, "title": row["title"], "type": row["type"]}


@router.get("/posts/{post_id}/revisions")
def revisions(
    post_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        post = get_post(conn, post_id=post_id)
        if not post:
            raise HTTPException(status_code=404, detail="文章不存在")
        _assert_can_edit(user, post, action="查看")
        rows = conn.execute(
            """SELECT r.id, r.title, r.excerpt, r.created_at, r.content_md,
                      u.display_name AS author_name
               FROM revisions r LEFT JOIN users u ON u.id = r.author_id
               WHERE r.post_id = ? ORDER BY r.id DESC LIMIT 25""",
            (post_id,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["content_md"] = item["content_md"]  # kept for restore/preview
        item["reading_time"] = reading_time(item["content_md"])
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/posts/{post_id}/revisions/{revision_id}/restore")
def restore_revision(
    post_id: int,
    revision_id: int,
    user: dict = Depends(require_permission("content.write")),
) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, post_id=post_id)
        revision = conn.execute(
            "SELECT * FROM revisions WHERE id = ? AND post_id = ?",
            (revision_id, post_id),
        ).fetchone()
        if not row or not revision:
            raise HTTPException(status_code=404, detail="版本不存在")
        _assert_can_edit(user, row)
        _save_revision(conn, row, int(user["id"]))
        content = revision["content_md"]
        conn.execute(
            """UPDATE posts SET title = ?, excerpt = ?, content_md = ?,
                   content_html = ?, updated_at = ? WHERE id = ?""",
            (
                revision["title"],
                revision["excerpt"],
                content,
                render_markdown(content),
                now_iso(),
                post_id,
            ),
        )
        fresh = get_post(conn, post_id=post_id)
        assert fresh is not None
        item = serialize_post(conn, fresh, detail=True, admin=True)
    return item


@router.get("/content-authors")
def content_authors(
    user: dict = Depends(require_permission("content.others")),
) -> dict[str, Any]:
    """Members who can own content, used by the editor's author selector."""
    with db() as conn:
        rows = conn.execute(
            """SELECT id, username, display_name, role, is_active FROM users
               ORDER BY is_active DESC,
                        CASE role WHEN 'admin' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                        display_name COLLATE NOCASE ASC"""
        ).fetchall()
    return {
        "items": [
            {
                "id": int(row["id"]),
                "username": row["username"],
                "name": row["display_name"],
                "role": row["role"],
                "role_label": ROLE_LABELS.get(row["role"], row["role"]),
                "is_active": bool(row["is_active"]),
            }
            for row in rows
        ]
    }


@router.post("/preview")
def preview(payload: PreviewIn, user: dict = Depends(require_permission("content.write"))) -> dict[str, Any]:
    if not preview_limiter.allow(f"preview:{user['id']}"):
        raise HTTPException(
            status_code=429,
            detail="预览刷新过于频繁，请稍后再试",
            headers={"Retry-After": "10"},
        )
    html = render_markdown(payload.content_md)
    from ..content import extract_toc

    return {"html": html, "toc": extract_toc(html), "reading_time": reading_time(payload.content_md)}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.get("/comments")
def admin_comments(
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_permission("comment.moderate")),
) -> dict[str, Any]:
    where: list[str] = []
    args: list[Any] = []
    if status in {"approved", "pending", "spam"}:
        where.append("c.status = ?")
        args.append(status)
    if q:
        where.append("(c.content LIKE ? OR c.author_name LIKE ? OR p.title LIKE ?)")
        needle = f"%{q}%"
        args.extend([needle, needle, needle])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with db() as conn:
        total = int(
            conn.execute(
                f"""SELECT COUNT(*) FROM comments c JOIN posts p ON p.id = c.post_id {clause}""",
                args,
            ).fetchone()[0]
        )
        rows = conn.execute(
            f"""SELECT c.*, p.title AS post_title, p.slug AS post_slug
                FROM comments c JOIN posts p ON p.id = c.post_id
                {clause} ORDER BY c.created_at DESC LIMIT ? OFFSET ?""",
            [*args, per_page, (page - 1) * per_page],
        ).fetchall()
        counts = {
            row["status"]: int(row["n"])
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM comments GROUP BY status"
            )
        }
    counts["all"] = sum(counts.values())
    return {
        "items": [dict(row) for row in rows],
        "counts": counts,
        **pagination(page, per_page, total),
    }


@router.put("/comments/{comment_id}")
def update_comment(
    comment_id: int,
    payload: CommentStatusIn,
    user: dict = Depends(require_permission("comment.moderate")),
) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            "UPDATE comments SET status = ? WHERE id = ?",
            (payload.status, comment_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="评论不存在")
    return {"ok": True, "status": payload.status}


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int, user: dict = Depends(require_permission("comment.moderate"))
) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="评论不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

@router.get("/taxonomy")
def admin_taxonomy() -> dict[str, Any]:
    with db() as conn:
        categories = [
            dict(row)
            for row in conn.execute(
                """SELECT c.*, (SELECT COUNT(*) FROM post_categories pc
                       WHERE pc.category_id = c.id) AS count
                   FROM categories c ORDER BY c.name"""
            )
        ]
        tags = [
            dict(row)
            for row in conn.execute(
                """SELECT t.*, (SELECT COUNT(*) FROM post_tags pt
                       WHERE pt.tag_id = t.id) AS count
                   FROM tags t ORDER BY t.name"""
            )
        ]
    return {"categories": categories, "tags": tags}


def _taxonomy_table(kind: str) -> str:
    if kind not in {"categories", "tags"}:
        raise HTTPException(status_code=404, detail="未知分类类型")
    return kind


@router.post("/taxonomy/{kind}", status_code=201)
def create_term(
    kind: str,
    payload: TaxonomyIn,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    table = _taxonomy_table(kind)
    with db() as conn:
        exists = conn.execute(
            f"SELECT 1 FROM {table} WHERE name = ? COLLATE NOCASE", (payload.name,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="同名条目已存在")
        base = slugify(payload.slug or payload.name, fallback="item")
        slug = base
        number = 2
        while conn.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}-{number}"
            number += 1
        cur = conn.execute(
            f"INSERT INTO {table}(name, slug, description, created_at) VALUES (?, ?, ?, ?)",
            (payload.name, slug, payload.description, now_iso()),
        )
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.put("/taxonomy/{kind}/{term_id}")
def update_term(
    kind: str,
    term_id: int,
    payload: TaxonomyIn,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    table = _taxonomy_table(kind)
    with db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (term_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="条目不存在")
        conflict = conn.execute(
            f"SELECT 1 FROM {table} WHERE name = ? COLLATE NOCASE AND id != ?",
            (payload.name, term_id),
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="同名条目已存在")
        slug = slugify(payload.slug or row["slug"] or payload.name, fallback="item")
        duplicate = conn.execute(
            f"SELECT 1 FROM {table} WHERE slug = ? AND id != ?", (slug, term_id)
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="别名已被使用")
        conn.execute(
            f"UPDATE {table} SET name = ?, slug = ?, description = ? WHERE id = ?",
            (payload.name, slug, payload.description, term_id),
        )
        updated = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (term_id,)).fetchone()
    return dict(updated)


@router.delete("/taxonomy/{kind}/{term_id}")
def delete_term(
    kind: str,
    term_id: int,
    user: dict = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    table = _taxonomy_table(kind)
    with db() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (term_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="条目不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings / appearance / profile
# ---------------------------------------------------------------------------

def _admin_settings() -> dict[str, Any]:
    """Settings for the admin UI, with secret values masked.

    The secret itself is never returned; the `_configured` flag lets the form
    tell "not set yet" from "saved, leave blank to keep". Saving an empty value
    for a secret key means "keep the current one".
    """
    settings = load_settings()
    result = dict(settings)
    for key in SECRET_SETTING_KEYS:
        configured = bool(str(settings.get(key) or "").strip())
        result[key] = ""
        result[f"{key}_configured"] = configured
    return result


@router.get("/settings")
def get_settings(
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    return {
        "settings": _admin_settings(),
        "meta": {
            "version": VERSION,
            "themes": sorted(THEMES),
            "color_modes": sorted(COLOR_MODES),
            "font_pairs": sorted(FONT_PAIRS),
            "post_layouts": sorted(POST_LAYOUTS),
            "hero_styles": sorted(HERO_STYLES),
            "image": {
                "avif": AVIF_SUPPORTED,
                "webp": WEBP_SUPPORTED,
                "scenes": list(IMAGE_SCENES),
            },
            "storage": {
                "backends": sorted(STORAGE_BACKENDS),
                "serve_modes": sorted(STORAGE_SERVE_MODES),
            },
        },
    }


def _as_text(value: Any, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value[:max_len]


def _sanitize_upload_formats(
    value: Any, allowed: tuple[str, ...], aliases: dict[str, str]
) -> list[str]:
    """Keep only known format tokens, in the canonical order."""
    if not isinstance(value, str):
        return []
    tokens = {
        aliases.get(token.strip().lower().lstrip("."), token.strip().lower().lstrip("."))
        for token in value.replace(";", ",").split(",")
    }
    return [format_ for format_ in allowed if format_ in tokens]


def _sanitize_links(value: Any, label_key: str = "label") -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        label = _as_text(item.get(label_key), 40).strip()
        url = _as_text(item.get("url"), 300).strip()
        if not label or not url:
            continue
        if not (url.startswith(("/", "#")) or re.match(r"^(https?://|mailto:)", url)):
            continue
        result.append({"label": label, "url": url})
    return result


def _sanitize_width_ladder(value: Any) -> list[int]:
    """Parse the comma-separated image width ladder, keeping sane entries."""
    widths: set[int] = set()
    for token in str(value or "").replace(";", ",").split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        width = int(token)
        if 64 <= width <= 8192:
            widths.add(width)
    return sorted(widths)[:10]


@router.put("/settings")
def update_settings(
    payload: dict[str, Any],
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="设置格式不正确")
    allowed = set(default_settings().keys())
    clean: dict[str, Any] = {}
    text_limits = {
        "site_title": 60, "site_subtitle": 60, "tagline": 160, "description": 300,
        "site_url": 200, "logo": 500, "favicon": 500, "footer_text": 200,
        "footer_note": 200, "icp": 80, "seo_description": 300,
        "seo_keywords": 200, "og_image": 500, "announcement": 300,
        "hero_eyebrow": 100, "hero_title": 160, "hero_subtitle": 500,
        "hero_image": 500, "custom_css": 60_000, "head_html": 30_000,
    }
    for key, value in payload.items():
        if key not in allowed or len(clean) > 80:
            continue
        if key in text_limits:
            clean[key] = _as_text(value, text_limits[key])
        elif key in {
            "hero_show", "show_reading_time", "show_author", "show_views",
            "comments_enabled", "comment_moderation", "editor_manage_others",
            "image_avif_enabled", "image_webp_enabled", "image_prewarm",
            "image_lazy_enabled", "storage_s3_path_style", "storage_backup_local",
        }:
            clean[key] = bool(value)
        elif key == "image_avif_speed":
            try:
                clean[key] = max(0, min(10, int(value)))
            except (TypeError, ValueError):
                continue
        elif key in {"image_webp_quality", "image_jpeg_quality"} or key in {
            f"image_quality_{scene}" for scene in IMAGE_SCENES
        }:
            try:
                clean[key] = max(1, min(100, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "image_widths":
            widths = _sanitize_width_ladder(value)
            if widths:
                clean[key] = ",".join(str(width) for width in widths)
        elif key == "image_max_width":
            try:
                clean[key] = max(0, min(8192, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "image_cache_days":
            try:
                clean[key] = max(1, min(3650, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "storage_backend":
            if value in STORAGE_BACKENDS:
                clean[key] = value
        elif key == "storage_serve_mode":
            if value in STORAGE_SERVE_MODES:
                clean[key] = value
        elif key == "storage_s3_secret_key":
            # An empty secret means "keep the stored one", so a masked admin
            # form can be submitted without ever exposing the value.
            secret = _as_text(value, 400).strip()
            if secret:
                clean[key] = secret
        elif key in {"storage_s3_endpoint", "storage_public_base_url"}:
            url = _as_text(value, 500).strip().rstrip("/")
            if not url or re.match(r"^https?://", url):
                clean[key] = url
        elif key in {
            "storage_s3_bucket", "storage_s3_region",
            "storage_s3_access_key", "storage_s3_prefix",
        }:
            clean[key] = _as_text(value, 200).strip()
        elif key == "posts_per_page":
            try:
                clean[key] = max(1, min(30, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "gallery_columns":
            try:
                clean[key] = max(2, min(4, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "upload_max_mb":
            try:
                clean[key] = max(1, min(200, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "upload_image_formats":
            formats = _sanitize_upload_formats(value, UPLOAD_IMAGE_FORMATS, UPLOAD_FORMAT_ALIASES)
            if formats:
                clean[key] = ",".join(formats)
        elif key == "upload_audio_formats":
            formats = _sanitize_upload_formats(value, UPLOAD_AUDIO_FORMATS, {})
            if formats:
                clean[key] = ",".join(formats)
        elif key == "upload_file_formats":
            formats = _sanitize_upload_formats(value, UPLOAD_FILE_FORMATS, {})
            clean[key] = ",".join(formats)
        elif key == "layout_width":
            try:
                clean[key] = max(720, min(1600, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "radius":
            try:
                clean[key] = max(0, min(40, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "nav":
            clean[key] = _sanitize_links(value)
        elif key == "social":
            clean[key] = _sanitize_links(value)
        elif key == "theme" and value in THEMES:
            clean[key] = value
        elif key == "color_mode" and value in COLOR_MODES:
            clean[key] = value
        elif key == "font_pair" and value in FONT_PAIRS:
            clean[key] = value
        elif key == "post_layout" and value in POST_LAYOUTS:
            clean[key] = value
        elif key == "hero_style" and value in HERO_STYLES:
            clean[key] = value
        elif key == "accent" and isinstance(value, str) and re.match(
            r"^#[0-9a-fA-F]{6}$", value
        ):
            clean[key] = value.lower()
        elif key in {"site_url", "logo", "favicon", "og_image", "hero_image"}:
            clean[key] = _as_text(value, 500)
        elif key.endswith("_url"):
            # Copy keys such as copy_hero_primary_url are rendered as links.
            url = _as_text(value, 500).strip()
            if not url or url.startswith(("/", "#")) or re.match(r"^https?://", url):
                clean[key] = url
        elif isinstance(value, str):
            # Theme copy: free text lines, editable from 外观 → 页面文案.
            clean[key] = _as_text(value, 500)
    if "site_url" in clean:
        url = str(clean["site_url"]).rstrip("/")
        if url and not re.match(r"^https?://", url):
            raise HTTPException(status_code=400, detail="站点地址需要以 http:// 或 https:// 开头")
        clean["site_url"] = url
    save_settings(clean)
    # A storage / image setting change invalidates the cached backend and the
    # derivative tokens, so reset both together.
    reset_storage()
    return {"ok": True, "settings": _admin_settings(), "updated": sorted(clean)}


@router.put("/appearance")
def update_appearance(
    payload: AppearanceIn,
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    updated = save_settings(payload.model_dump())
    return {"ok": True, "settings": updated}


@router.get("/profile")
def get_profile(user: dict = Depends(require_staff)) -> dict[str, Any]:
    return {"user": user}


@router.put("/profile")
def update_profile(
    payload: ProfileIn, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        if payload.new_password:
            if not verify_password(payload.current_password, row["password_hash"]):
                raise HTTPException(status_code=400, detail="当前密码不正确")
            problem = password_policy_error(payload.new_password, row["username"])
            if problem:
                raise HTTPException(status_code=400, detail=problem)
            password_hash = hash_password(payload.new_password)
        else:
            password_hash = row["password_hash"]
        conn.execute(
            """UPDATE users SET display_name = ?, email = ?, bio = ?, avatar = ?,
                   password_hash = ?, updated_at = ? WHERE id = ?""",
            (
                payload.display_name, payload.email, payload.bio, payload.avatar,
                password_hash, now_iso(), user["id"],
            ),
        )
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    result = {
        "id": updated["id"],
        "username": updated["username"],
        "display_name": updated["display_name"],
        "email": updated["email"],
        "bio": updated["bio"],
        "avatar": updated["avatar"],
        "role": updated["role"],
    }
    return {"ok": True, "user": result}


@router.get("/export")
def export_site(
    user: dict = Depends(require_permission("data.export")),
) -> JSONResponse:
    with db() as conn:
        posts = [dict(row) for row in conn.execute("SELECT * FROM posts ORDER BY id")]
        comments = [dict(row) for row in conn.execute("SELECT * FROM comments ORDER BY id")]
        categories = [dict(row) for row in conn.execute("SELECT * FROM categories ORDER BY id")]
        tags = [dict(row) for row in conn.execute("SELECT * FROM tags ORDER BY id")]
        post_tags = [dict(row) for row in conn.execute("SELECT * FROM post_tags")]
        post_categories = [dict(row) for row in conn.execute("SELECT * FROM post_categories")]
        galleries = [dict(row) for row in conn.execute("SELECT * FROM galleries ORDER BY id")]
        photos = [dict(row) for row in conn.execute("SELECT * FROM photos ORDER BY id")]
        media = [dict(row) for row in conn.execute("SELECT * FROM media ORDER BY id")]
    data = {
        "format": "mztlab-scene-export",
        "version": 2,
        "exported_at": now_iso(),
        "settings": public_settings(),
        "posts": posts,
        "comments": comments,
        "categories": categories,
        "tags": tags,
        "post_tags": post_tags,
        "post_categories": post_categories,
        "galleries": galleries,
        "photos": photos,
        "media": media,
    }
    filename = f"mztlab-{now_iso()[:10]}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
