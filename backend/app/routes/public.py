"""Public, unauthenticated read APIs used by the Astro site."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request

from ..config import MAX_SQLITE_INT
from ..db import db, load_settings, now_iso, public_settings
from ..deps import client_ip
from ..galleries import (
    fetch_galleries,
    fetch_photos,
    gallery_dict,
    gallery_photo_rows,
    get_gallery,
    photo_dict,
    public_counts,
)
from ..posts import (
    adjacent_posts,
    fetch_posts,
    get_post,
    pagination,
    public_url,
    related_posts,
    serialize_post,
    serialize_posts,
)
from ..schemas import CommentIn
from ..security import comment_limiter

router = APIRouter(tags=["public"])


@router.get("/health")
def health() -> dict:
    # Liveness only; do not disclose the exact application version.
    return {"ok": True, "time": now_iso()}


@router.get("/site")
def site_info() -> dict:
    settings = public_settings()
    with db() as conn:
        categories = [
            dict(row)
            for row in conn.execute(
                """SELECT c.id, c.name, c.slug, c.description,
                          (SELECT COUNT(*) FROM post_categories pc
                           JOIN posts p ON p.id = pc.post_id
                           WHERE pc.category_id = c.id
                             AND p.status IN ('published', 'scheduled')
                             AND p.published_at <= ?) AS count
                   FROM categories c ORDER BY count DESC, c.name ASC""",
                (now_iso(),),
            )
        ]
        tags = [
            dict(row)
            for row in conn.execute(
                """SELECT t.id, t.name, t.slug, t.description,
                          (SELECT COUNT(*) FROM post_tags pt
                           JOIN posts p ON p.id = pt.post_id
                           WHERE pt.tag_id = t.id
                             AND p.status IN ('published', 'scheduled')
                             AND p.published_at <= ?) AS count
                   FROM tags t ORDER BY count DESC, t.name ASC""",
                (now_iso(),),
            )
        ]
        post_count = conn.execute(
            """SELECT COUNT(*) AS n FROM posts
               WHERE type = 'post' AND status IN ('published', 'scheduled')
                 AND published_at <= ?""",
            (now_iso(),),
        ).fetchone()["n"]
        project_count = conn.execute(
            """SELECT COUNT(*) AS n FROM posts
               WHERE type = 'project' AND status IN ('published', 'scheduled')
                 AND published_at <= ?""",
            (now_iso(),),
        ).fetchone()["n"]
        counts = public_counts(conn)
    return {
        "settings": settings,
        "categories": categories,
        "tags": tags,
        "post_count": post_count,
        "project_count": project_count,
        **counts,
    }


@router.get("/posts")
def list_posts(
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=50),
    tag: str | None = None,
    category: str | None = None,
    q: str | None = Query(None, max_length=100),
    featured: bool | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    if per_page is None:
        per_page = int(settings.get("posts_per_page") or 9)
    with db() as conn:
        rows, total = fetch_posts(
            conn,
            page=page,
            per_page=per_page,
            tag=tag,
            category=category,
            q=q,
            featured=featured,
        )
        items = serialize_posts(conn, rows)
    return {"items": items, **pagination(page, per_page, total)}


@router.get("/posts/{slug}")
def post_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, slug=slug, post_type="post", public=True)
        if not row:
            raise HTTPException(status_code=404, detail="文章不存在或尚未发布")
        item = serialize_post(conn, row, detail=True)
        prev_post, next_post = adjacent_posts(conn, row)
        item["prev"] = prev_post
        item["next"] = next_post
        item["related"] = related_posts(conn, row)
        item["canonical"] = public_url(row)
    settings = load_settings()
    item["comments_enabled"] = bool(settings.get("comments_enabled", True)) and item["allow_comments"]
    item["comment_moderation"] = bool(settings.get("comment_moderation", True))
    return item


@router.get("/pages")
def list_pages() -> dict[str, Any]:
    with db() as conn:
        rows = list(
            conn.execute(
                """SELECT p.*, u.display_name AS author_name, u.avatar AS author_avatar
                   FROM posts p LEFT JOIN users u ON u.id = p.author_id
                   WHERE p.type = 'page' AND p.status IN ('published', 'scheduled')
                     AND p.published_at <= ?
                   ORDER BY p.updated_at DESC""",
                (now_iso(),),
            )
        )
        items = serialize_posts(conn, rows)
    return {"items": items, "total": len(items)}


@router.get("/pages/{slug}")
def page_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, slug=slug, post_type="page", public=True)
        if not row:
            raise HTTPException(status_code=404, detail="页面不存在")
        return serialize_post(conn, row, detail=True)


@router.get("/projects")
def list_projects(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    featured: bool | None = None,
) -> dict[str, Any]:
    with db() as conn:
        rows, total = fetch_posts(
            conn,
            post_type="project",
            page=page,
            per_page=per_page,
            featured=featured,
        )
        items = serialize_posts(conn, rows)
    return {"items": items, **pagination(page, per_page, total)}


@router.get("/projects/{slug}")
def project_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, slug=slug, post_type="project", public=True)
        if not row:
            raise HTTPException(status_code=404, detail="项目不存在或尚未发布")
        item = serialize_post(conn, row, detail=True)
        related = list(
            conn.execute(
                """SELECT p.*, u.display_name AS author_name, u.avatar AS author_avatar
                   FROM posts p LEFT JOIN users u ON u.id = p.author_id
                   WHERE p.type = 'project' AND p.status IN ('published', 'scheduled')
                     AND p.published_at <= ? AND p.id != ?
                   ORDER BY p.published_at DESC LIMIT 3""",
                (now_iso(), row["id"]),
            )
        )
        item["related"] = serialize_posts(conn, related)
        item["canonical"] = public_url(row)
    return item


@router.get("/archive")
def archive() -> dict[str, Any]:
    with db() as conn:
        rows = list(
            conn.execute(
                """SELECT p.*, u.display_name AS author_name, u.avatar AS author_avatar
                   FROM posts p LEFT JOIN users u ON u.id = p.author_id
                   WHERE p.type = 'post' AND p.status IN ('published', 'scheduled')
                     AND p.published_at <= ?
                   ORDER BY p.published_at DESC LIMIT 500""",
                (now_iso(),),
            )
        )
        items = serialize_posts(conn, rows)
    years: dict[str, int] = {}
    for item in items:
        year = (item.get("published_at") or "")[:4]
        years[year] = years.get(year, 0) + 1
    return {
        "items": items,
        "total": len(items),
        "years": [{"year": key, "count": value} for key, value in years.items() if key],
    }


@router.get("/galleries")
def list_galleries(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    featured: bool | None = None,
) -> dict[str, Any]:
    with db() as conn:
        rows, total = fetch_galleries(
            conn, page=page, per_page=per_page, featured=featured
        )
        items = [gallery_dict(conn, row) for row in rows]
    return {"items": items, **pagination(page, per_page, total)}


@router.get("/galleries/{slug}")
def gallery_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_gallery(conn, slug=slug, public=True)
        if not row:
            raise HTTPException(status_code=404, detail="相册不存在或尚未公开")
        item = gallery_dict(conn, row, detail=True)
        others = list(
            conn.execute(
                f"""SELECT g.*, u.display_name AS author_name, u.avatar AS author_avatar
                    FROM galleries g LEFT JOIN users u ON u.id = g.author_id
                    WHERE g.status = 'published' AND g.id != ?
                    ORDER BY g.featured DESC, g.updated_at DESC LIMIT 3""",
                (row["id"],),
            )
        )
        item["related"] = [gallery_dict(conn, other) for other in others]
        item["photos"] = [photo_dict(p) for p in gallery_photo_rows(conn, int(row["id"]))]
    return item


@router.post("/galleries/{gallery_id}/view")
def record_gallery_view(
    gallery_id: int = Path(..., ge=1, le=MAX_SQLITE_INT),
) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            "UPDATE galleries SET view_count = view_count + 1 WHERE id = ? AND status = 'published'",
            (gallery_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="相册不存在")
        value = conn.execute(
            "SELECT view_count FROM galleries WHERE id = ?", (gallery_id,)
        ).fetchone()["view_count"]
    return {"ok": True, "view_count": value}


@router.get("/search")
def search(q: str = Query("", max_length=100)) -> dict[str, Any]:
    needle = q.strip()
    if not needle:
        return {"query": "", "articles": [], "projects": [], "galleries": [], "photos": []}
    with db() as conn:
        articles = serialize_posts(
            conn,
            fetch_posts(conn, post_type="post", q=needle, per_page=12)[0],
        )
        projects = serialize_posts(
            conn,
            fetch_posts(conn, post_type="project", q=needle, per_page=12)[0],
        )
        gallery_rows, _ = fetch_galleries(conn, q=needle, per_page=12)
        galleries = [gallery_dict(conn, row) for row in gallery_rows]
        photo_rows, _ = fetch_photos(conn, q=needle, per_page=12)
        photos = [photo_dict(row) for row in photo_rows]
    return {
        "query": needle,
        "articles": articles,
        "projects": projects,
        "galleries": galleries,
        "photos": photos,
    }


@router.get("/taxonomy")
def taxonomy() -> dict[str, Any]:
    with db() as conn:
        categories = [
            dict(row)
            for row in conn.execute(
                """SELECT c.*, (SELECT COUNT(*) FROM post_categories pc
                    JOIN posts p ON p.id = pc.post_id
                    WHERE pc.category_id = c.id AND p.status IN ('published','scheduled')
                      AND p.published_at <= ?) AS count
                   FROM categories c ORDER BY count DESC, c.name""",
                (now_iso(),),
            )
        ]
        tags = [
            dict(row)
            for row in conn.execute(
                """SELECT t.*, (SELECT COUNT(*) FROM post_tags pt
                    JOIN posts p ON p.id = pt.post_id
                    WHERE pt.tag_id = t.id AND p.status IN ('published','scheduled')
                      AND p.published_at <= ?) AS count
                   FROM tags t ORDER BY count DESC, t.name""",
                (now_iso(),),
            )
        ]
    return {"categories": categories, "tags": tags}


@router.get("/comments")
def list_comments(
    post_id: int = Query(..., ge=1, le=MAX_SQLITE_INT),
) -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            """SELECT id, post_id, author_name, author_url, content, created_at
               FROM comments WHERE post_id = ? AND status = 'approved'
               ORDER BY created_at ASC LIMIT 300""",
            (post_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}


@router.post("/posts/{post_id}/comments", status_code=201)
def create_comment(
    payload: CommentIn,
    request: Request,
    post_id: int = Path(..., ge=1, le=MAX_SQLITE_INT),
) -> dict[str, Any]:
    settings = load_settings()
    if not settings.get("comments_enabled", True):
        raise HTTPException(status_code=403, detail="评论功能已关闭")
    with db() as conn:
        post = conn.execute(
            """SELECT id, allow_comments FROM posts
               WHERE id = ? AND type = 'post' AND status IN ('published','scheduled')
                 AND published_at <= ?""",
            (post_id, now_iso()),
        ).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="文章不存在")
        if not post["allow_comments"]:
            raise HTTPException(status_code=403, detail="这篇文章不接受评论")

    # Honeypot: bots fill the hidden website field. Pretend everything worked.
    if payload.website.strip():
        return {"ok": True, "pending": True, "message": "评论已提交，等待审核。"}

    ip = client_ip(request)
    if not comment_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="留言过于频繁，请稍后再试")

    moderation = bool(settings.get("comment_moderation", True))
    status_value = "pending" if moderation else "approved"
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO comments(post_id, author_name, author_email, author_url,
                                    content, status, ip, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                payload.author_name,
                payload.author_email,
                payload.author_url,
                payload.content,
                status_value,
                ip,
                now_iso(),
            ),
        )
    message = "留言已提交，审核通过后会出现在这里。" if moderation else "谢谢你的留言。"
    return {"ok": True, "id": cur.lastrowid, "pending": moderation, "message": message}


@router.post("/posts/{post_id}/view")
def record_view(
    post_id: int = Path(..., ge=1, le=MAX_SQLITE_INT),
) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            """UPDATE posts SET view_count = view_count + 1
               WHERE id = ? AND type = 'post' AND status IN ('published','scheduled')
                 AND published_at <= ?""",
            (post_id, now_iso()),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="文章不存在")
        views = conn.execute("SELECT view_count FROM posts WHERE id = ?", (post_id,)).fetchone()[
            "view_count"
        ]
    return {"ok": True, "view_count": views}
