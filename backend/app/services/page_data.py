"""Single aggregated page-data entry point (SSG reserve R1).

Public pages must not fan out to several API calls: `page_data()` returns
everything one public route needs — site chrome, taxonomy and the page-specific
payload. The same function is callable at build time (no request context, no
cookies/session/UA), which is exactly what a future `astro build` needs.

`GET /api/bootstrap` is a thin HTTP wrapper around this service.
"""

from __future__ import annotations

from typing import Any, Literal

from ..db import db, now_iso
from ..galleries import (
    fetch_galleries,
    fetch_photos,
    gallery_dict,
    get_gallery,
    photo_dict,
    public_counts,
)
from ..images import image_payload_for_url
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
from ..settings import Settings, load_settings_cached

PageKind = Literal[
    "home",
    "archive",
    "post",
    "page",
    "project",
    "projects",
    "galleries",
    "gallery",
    "taxonomy",
    "search",
]


def taxonomy_rows(conn: Any, kind: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """SELECT t.id, t.name, t.slug, t.description,
                      (SELECT COUNT(*) FROM post_terms pt
                       JOIN posts p ON p.id = pt.post_id
                       WHERE pt.term_id = t.id
                         AND p.status IN ('published', 'scheduled')
                         AND p.published_at <= ?) AS count
               FROM taxonomy_terms t WHERE t.kind = ?
               ORDER BY count DESC, t.name ASC""",
            (now_iso(), kind),
        )
    ]


def site_context(conn: Any, settings: Settings) -> dict[str, Any]:
    """Everything the page chrome (header/footer/hero) needs, exactly once."""
    post_count = int(
        conn.execute(
            """SELECT COUNT(*) AS n FROM posts
               WHERE type = 'post' AND status IN ('published', 'scheduled')
                 AND published_at <= ?""",
            (now_iso(),),
        ).fetchone()["n"]
    )
    project_count = int(
        conn.execute(
            """SELECT COUNT(*) AS n FROM posts
               WHERE type = 'project' AND status IN ('published', 'scheduled')
                 AND published_at <= ?""",
            (now_iso(),),
        ).fetchone()["n"]
    )
    counts = public_counts(conn)
    hero = image_payload_for_url(
        conn, str(settings.appearance.hero_image or ""), settings
    )
    og = image_payload_for_url(conn, str(settings.site.og_image or ""), settings)
    return {
        "settings": settings.public_dump(),
        "categories": taxonomy_rows(conn, "category"),
        "tags": taxonomy_rows(conn, "tag"),
        "post_count": post_count,
        "project_count": project_count,
        **counts,
        "hero_image_info": hero,
        "og_image_info": og,
    }


def _home(conn: Any, settings: Settings) -> dict[str, Any]:
    posts, _ = fetch_posts(conn, per_page=settings.site.posts_per_page, page=1)
    projects, _ = fetch_posts(conn, post_type="project", per_page=6)
    galleries, _ = fetch_galleries(conn, per_page=6)
    return {
        "kind": "home",
        "posts": serialize_posts(conn, posts),
        "projects": serialize_posts(conn, projects),
        "galleries": [gallery_dict(conn, row) for row in galleries],
    }


def _archive(conn: Any) -> dict[str, Any]:
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
        "kind": "archive",
        "items": items,
        "total": len(items),
        "years": [{"year": key, "count": value} for key, value in years.items() if key],
    }


def _content_detail(conn: Any, kind: str, post_type: str, slug: str) -> dict[str, Any]:
    row = get_post(conn, slug=slug, post_type=post_type, public=True)
    if not row:
        raise LookupError(slug)
    item = serialize_post(conn, row, detail=True)
    item["canonical"] = public_url(row)
    if kind == "post":
        prev_post, next_post = adjacent_posts(conn, row)
        item["prev"] = prev_post
        item["next"] = next_post
        item["related"] = related_posts(conn, row)
        return {"kind": kind, "item": item}
    if kind == "project":
        related = list(
            conn.execute(
                """SELECT p.*, pd.kind AS project_kind, pd.year AS project_year,
                          pd.role AS project_role, pd.client AS project_client,
                          pd.url AS project_url,
                          u.display_name AS author_name, u.username AS author_username,
                          u.avatar AS author_avatar, u.bio AS author_bio
                   FROM posts p
                   LEFT JOIN project_details pd ON pd.post_id = p.id
                   LEFT JOIN users u ON u.id = p.owner_id
                   WHERE p.type = 'project' AND p.status IN ('published', 'scheduled')
                     AND p.published_at <= ? AND p.id != ?
                   ORDER BY p.published_at DESC LIMIT 3""",
                (now_iso(), row["id"]),
            )
        )
        item["related"] = serialize_posts(conn, related)
        return {"kind": kind, "item": item}
    return {"kind": kind, "item": item}


def page_data(
    kind: PageKind,
    *,
    slug: str | None = None,
    page: int = 1,
    tag: str | None = None,
    category: str | None = None,
    q: str | None = None,
    featured: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return {site, page} for one public route. No request context involved."""
    resolved = settings or load_settings_cached()
    with db() as conn:
        site = site_context(conn, resolved)
        if kind == "home":
            payload = _home(conn, resolved)
        elif kind == "archive":
            payload = _archive(conn)
        elif kind in {"post", "page", "project"}:
            if not slug:
                raise ValueError("slug is required")
            post_type = {"post": "post", "page": "page", "project": "project"}[kind]
            payload = _content_detail(conn, kind, post_type, slug)
        elif kind == "projects":
            rows, total = fetch_posts(
                conn, post_type="project", page=page, per_page=24, featured=featured
            )
            payload = {
                "kind": "projects",
                "items": serialize_posts(conn, rows),
                **pagination(page, 24, total),
            }
        elif kind == "galleries":
            rows, total = fetch_galleries(
                conn, page=page, per_page=24, featured=featured
            )
            payload = {
                "kind": "galleries",
                "items": [gallery_dict(conn, row) for row in rows],
                **pagination(page, 24, total),
            }
        elif kind == "gallery":
            if not slug:
                raise ValueError("slug is required")
            row = get_gallery(conn, slug=slug, public=True)
            if not row:
                raise LookupError(slug)
            item = gallery_dict(conn, row, detail=True)
            others = list(
                conn.execute(
                    """SELECT g.*, u.display_name AS author_name,
                              u.username AS author_username, u.avatar AS author_avatar
                       FROM galleries g LEFT JOIN users u ON u.id = g.owner_id
                       WHERE g.status = 'published' AND g.id != ?
                       ORDER BY g.featured DESC, g.updated_at DESC LIMIT 3""",
                    (row["id"],),
                )
            )
            item["related"] = [gallery_dict(conn, other) for other in others]
            payload = {"kind": "gallery", "item": item}
        elif kind == "taxonomy":
            term = None
            if tag:
                term = find_term("tag", tag)
            elif category:
                term = find_term("category", category)
            elif slug:
                term = find_term("tag", slug) or find_term("category", slug)
            if term is not None and (tag or category or slug):
                rows, total = fetch_posts(
                    conn,
                    page=page,
                    per_page=resolved.site.posts_per_page,
                    tag=term["slug"] if (tag or slug) else None,
                    category=term["slug"] if category else None,
                )
                payload = {
                    "kind": "taxonomy",
                    "categories": site["categories"],
                    "tags": site["tags"],
                    "term": term,
                    "items": serialize_posts(conn, rows),
                    **pagination(page, resolved.site.posts_per_page, total),
                }
            else:
                payload = {
                    "kind": "taxonomy",
                    "categories": site["categories"],
                    "tags": site["tags"],
                    "term": None,
                    "items": [],
                }
        elif kind == "search":
            needle = (q or "").strip()
            if not needle:
                payload = {
                    "kind": "search",
                    "query": "",
                    "articles": [],
                    "projects": [],
                    "galleries": [],
                    "photos": [],
                }
            else:
                articles = serialize_posts(
                    conn, fetch_posts(conn, post_type="post", q=needle, per_page=12)[0]
                )
                projects = serialize_posts(
                    conn,
                    fetch_posts(conn, post_type="project", q=needle, per_page=12)[0],
                )
                gallery_rows, _ = fetch_galleries(conn, q=needle, per_page=12)
                photo_rows, _ = fetch_photos(conn, q=needle, per_page=12)
                payload = {
                    "kind": "search",
                    "query": needle,
                    "articles": articles,
                    "projects": projects,
                    "galleries": [gallery_dict(conn, row) for row in gallery_rows],
                    "photos": [photo_dict(row) for row in photo_rows],
                }
        else:  # pragma: no cover - Literal guards this at the type level
            raise ValueError(f"unknown page kind: {kind}")
    return {"site": site, "page": payload}


def find_term(kind: Literal["tag", "category"], slug: str) -> dict[str, Any] | None:
    """Look up one taxonomy term for a path-based listing page."""
    column = "tag" if kind == "tag" else "category"
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, slug, description FROM taxonomy_terms "
            "WHERE kind = ? AND slug = ?",
            (column, slug),
        ).fetchone()
    return dict(row) if row else None
