"""Public, unauthenticated read APIs used by the Astro site.

3.0.0 removed the comment endpoints and both view-count endpoints outright:
there is no public write surface left besides login and (permission-gated)
uploads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..api.models import (
    ArchiveResponse,
    BootstrapResponse,
    ContentDetail,
    ContentListResponse,
    GalleryDetail,
    GalleryListResponse,
    HealthResponse,
    PageListResponse,
    ProjectListResponse,
    SearchResponse,
    SiteInfoResponse,
    TaxonomyResponse,
)
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
from ..services.page_data import PageKind, page_data
from ..settings import load_settings_cached

router = APIRouter(tags=["public"])

# Aggregated page data is the single public read entry point a page needs. It is
# cacheable at the edge for a short window (R1/R4): no cookies, no request state.
BOOTSTRAP_CACHE_CONTROL = "public, max-age=0, must-revalidate, s-maxage=60"


def _cached_json(
    request: Request, data: dict[str, Any], *, cache_control: str
) -> Response:
    body = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    etag = 'W/"' + hashlib.sha1(body.encode("utf-8")).hexdigest() + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": cache_control,
        "Vary": "Accept-Encoding",
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def _taxonomy_rows(conn, kind: str) -> list[dict[str, Any]]:
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


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    # Liveness only; do not disclose the exact application version.
    return {"ok": True, "time": now_iso()}


@router.get("/site", response_model=SiteInfoResponse)
def site_info() -> dict:
    settings = load_settings_cached()
    with db() as conn:
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
        categories = _taxonomy_rows(conn, "category")
        tags = _taxonomy_rows(conn, "tag")
        hero_image_info = image_payload_for_url(
            conn, str(settings.appearance.hero_image or ""), settings
        )
        og_image_info = image_payload_for_url(
            conn, str(settings.site.og_image or ""), settings
        )
    return {
        "settings": settings.public_dump(),
        "categories": categories,
        "tags": tags,
        "post_count": post_count,
        "project_count": project_count,
        **counts,
        "hero_image_info": hero_image_info,
        "og_image_info": og_image_info,
    }


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    request: Request,
    route: PageKind = Query("home"),
    slug: str | None = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    tag: str | None = Query(None, max_length=120),
    category: str | None = Query(None, max_length=120),
    q: str | None = Query(None, max_length=100),
    featured: bool | None = Query(None),
) -> Response:
    """Everything one public page needs, in one request (SSG reserve R1).

    The payload depends only on route parameters and the database: no cookies,
    session, user-agent or other request context is read, so a future
    `astro build` can call the same function at build time.
    """
    try:
        data = page_data(
            route,
            slug=slug,
            page=page,
            tag=tag,
            category=category,
            q=q,
            featured=featured,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="内容不存在或尚未发布") from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    # Validate through the response model as well, so a handler change cannot
    # silently drift from the published contract.
    payload = BootstrapResponse.model_validate(data).model_dump(mode="json")
    return _cached_json(request, payload, cache_control=BOOTSTRAP_CACHE_CONTROL)


@router.get("/posts", response_model=ContentListResponse)
def list_posts(
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=50),
    tag: str | None = None,
    category: str | None = None,
    q: str | None = Query(None, max_length=100),
    featured: bool | None = None,
) -> dict[str, Any]:
    settings = load_settings_cached()
    if per_page is None:
        per_page = settings.site.posts_per_page
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


@router.get("/posts/{slug}", response_model=ContentDetail)
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
    return item


@router.get("/pages", response_model=PageListResponse)
def list_pages() -> dict[str, Any]:
    with db() as conn:
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
                   WHERE p.type = 'page' AND p.status IN ('published', 'scheduled')
                     AND p.published_at <= ?
                   ORDER BY p.updated_at DESC""",
                (now_iso(),),
            )
        )
        items = serialize_posts(conn, rows)
    return {"items": items, "total": len(items)}


@router.get("/pages/{slug}", response_model=ContentDetail)
def page_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, slug=slug, post_type="page", public=True)
        if not row:
            raise HTTPException(status_code=404, detail="页面不存在")
        return serialize_post(conn, row, detail=True)


@router.get("/projects", response_model=ProjectListResponse)
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


@router.get("/projects/{slug}", response_model=ContentDetail)
def project_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_post(conn, slug=slug, post_type="project", public=True)
        if not row:
            raise HTTPException(status_code=404, detail="项目不存在或尚未发布")
        item = serialize_post(conn, row, detail=True)
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
        item["canonical"] = public_url(row)
    return item


@router.get("/archive", response_model=ArchiveResponse)
def archive() -> dict[str, Any]:
    with db() as conn:
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
        "items": items,
        "total": len(items),
        "years": [{"year": key, "count": value} for key, value in years.items() if key],
    }


@router.get("/galleries", response_model=GalleryListResponse)
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


@router.get("/galleries/{slug}", response_model=GalleryDetail)
def gallery_detail(slug: str) -> dict[str, Any]:
    with db() as conn:
        row = get_gallery(conn, slug=slug, public=True)
        if not row:
            raise HTTPException(status_code=404, detail="相册不存在或尚未公开")
        # gallery_dict(detail=True) already builds the photo list exactly once
        # (2.x queried and serialized the photos a second time here).
        item = gallery_dict(conn, row, detail=True)
        others = list(
            conn.execute(
                """SELECT g.*, u.display_name AS author_name, u.username AS author_username,
                          u.avatar AS author_avatar
                   FROM galleries g LEFT JOIN users u ON u.id = g.owner_id
                   WHERE g.status = 'published' AND g.id != ?
                   ORDER BY g.featured DESC, g.updated_at DESC LIMIT 3""",
                (row["id"],),
            )
        )
        item["related"] = [gallery_dict(conn, other) for other in others]
    return item


@router.get("/search", response_model=SearchResponse)
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


@router.get("/taxonomy", response_model=TaxonomyResponse)
def taxonomy() -> dict[str, Any]:
    with db() as conn:
        return {
            "categories": _taxonomy_rows(conn, "category"),
            "tags": _taxonomy_rows(conn, "tag"),
        }
