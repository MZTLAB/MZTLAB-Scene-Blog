"""Shared write pipeline for the admin content resources (posts/projects/pages).

3.0.0 keeps the three content types in one table (`posts`) with class-table
inheritance for the project-only fields (`project_details`), so the three thin
resource routers share one pipeline here:

* slug uniqueness is per `(type, slug)`; reserved public page slugs are still
  skipped for `type='page'`;
* schedule normalization (`draft` / `published` / `scheduled`);
* rendering is materialised on write (`content_html`, `reading_time`,
  `toc_json`, `render_version`);
* taxonomy terms are upserted into `taxonomy_terms` and linked via
  `post_terms`;
* revisions keep the previous title/excerpt/content and record `owner_id`;
* ownership transfer is validated once (`_resolve_author_id` replacement);
* page counts for the admin lists are filtered by type and optional owner.

HTTP concerns (dependency wiring, response shaping) stay in the routers.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..content import (
    extract_toc,
    make_excerpt,
    normalize_iso_datetime,
    reading_time,
    render_markdown,
    slugify,
)
from ..db import now_iso
from ..errors import ApiError
from ..permissions import can
from ..schemas import PageIn, PagePatch, PostIn, PostPatch, ProjectIn, ProjectPatch

# Version recorded on every rendered `posts.render_version`. Bump it when the
# Markdown pipeline changes; a background job can then re-render old rows.
RENDER_PIPELINE_VERSION = 1

# Slugs that would collide with built-in frontend routes. Only `type='page'`
# public paths are top level, so only pages need to avoid them.
RESERVED_PAGE_SLUGS: frozenset[str] = frozenset(
    {
        "admin", "api", "media", "posts", "archive", "search", "tags",
        "categories", "photos", "galleries", "projects", "rss.xml",
        "sitemap.xml", "robots.txt", "setup", "login",
    }
)

POST_TYPES: tuple[str, ...] = ("post", "project", "page")

# Public path segment -> `taxonomy_terms.kind` value.
TERM_KIND_BY_PATH: dict[str, str] = {"categories": "category", "tags": "tag"}

ContentIn = PostIn | ProjectIn | PageIn
ContentPatch = PostPatch | ProjectPatch | PagePatch


def _last_insert_id(cur: sqlite3.Cursor) -> int:
    """Return a rowid, failing loudly instead of relying on an `assert`."""
    value = cur.lastrowid
    if value is None:
        raise ApiError(500, "server.internal_error", "无法获取新记录 ID")
    return int(value)

# Payload field -> `project_details` column.
PROJECT_COLUMNS: dict[str, str] = {
    "project_kind": "kind",
    "project_year": "year",
    "project_role": "role",
    "project_client": "client",
    "project_url": "url",
}


# ---------------------------------------------------------------------------
# Slugs and schedules
# ---------------------------------------------------------------------------

def unique_slug(
    conn: sqlite3.Connection,
    value: str,
    *,
    post_type: str,
    post_id: int | None = None,
) -> str:
    """Return a slug unique within `(type, slug)`, auto-suffixing on collision."""
    base = slugify(value, fallback="page" if post_type == "page" else "post")
    candidate = base
    number = 2
    while True:
        if post_type == "page" and candidate in RESERVED_PAGE_SLUGS:
            candidate = f"{base}-{number}"
            number += 1
            continue
        row = conn.execute(
            "SELECT id FROM posts WHERE type = ? AND slug = ? "
            "AND (? IS NULL OR id != ?)",
            (post_type, candidate, post_id, post_id),
        ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}-{number}"
        number += 1


def normalize_schedule(status: str, published_at: str | None) -> tuple[str, str | None]:
    """Resolve `draft`/`published`/`scheduled` against the publish timestamp."""
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


# ---------------------------------------------------------------------------
# Taxonomy terms
# ---------------------------------------------------------------------------

def term_kind(path_kind: str) -> str:
    """Map a route path segment (`categories`/`tags`) to the DB kind value."""
    kind = TERM_KIND_BY_PATH.get(path_kind)
    if kind is None:
        raise ApiError(404, "taxonomy.unknown_kind", "未知分类类型", field="kind")
    return kind


def upsert_term(conn: sqlite3.Connection, kind: str, name: str) -> int:
    """Return the id of `(kind, name)`, creating the term when missing."""
    row = conn.execute(
        "SELECT id FROM taxonomy_terms WHERE kind = ? AND name = ? COLLATE NOCASE",
        (kind, name),
    ).fetchone()
    if row:
        return int(row["id"])
    base = slugify(name, fallback="item")
    candidate = base
    number = 2
    while conn.execute(
        "SELECT 1 FROM taxonomy_terms WHERE kind = ? AND slug = ?",
        (kind, candidate),
    ).fetchone():
        candidate = f"{base}-{number}"
        number += 1
    cur = conn.execute(
        """INSERT INTO taxonomy_terms(kind, name, slug, description, created_at)
           VALUES (?, ?, ?, '', ?)""",
        (kind, name, candidate, now_iso()),
    )
    return _last_insert_id(cur)


def replace_terms(
    conn: sqlite3.Connection,
    post_id: int,
    kind: str,
    names: list[str],
) -> None:
    """Replace every term link of one kind for a post (other kinds untouched)."""
    conn.execute(
        """DELETE FROM post_terms WHERE post_id = ? AND term_id IN (
               SELECT id FROM taxonomy_terms WHERE kind = ?
           )""",
        (post_id, kind),
    )
    for name in names:
        term_id = upsert_term(conn, kind, name)
        conn.execute(
            "INSERT OR IGNORE INTO post_terms(post_id, term_id) VALUES (?, ?)",
            (post_id, term_id),
        )


def replace_post_terms(
    conn: sqlite3.Connection,
    post_id: int,
    *,
    categories: list[str],
    tags: list[str],
) -> None:
    replace_terms(conn, post_id, "category", categories)
    replace_terms(conn, post_id, "tag", tags)


# ---------------------------------------------------------------------------
# Revisions and counts
# ---------------------------------------------------------------------------

def save_revision(conn: sqlite3.Connection, row: sqlite3.Row, owner_id: int) -> None:
    """Keep the previous revision, retaining at most 25 per post."""
    conn.execute(
        """INSERT INTO revisions(post_id, title, excerpt, content_md, owner_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            row["id"],
            row["title"],
            row["excerpt"],
            row["content_md"],
            owner_id,
            now_iso(),
        ),
    )
    conn.execute(
        """DELETE FROM revisions WHERE post_id = ? AND id NOT IN (
               SELECT id FROM revisions WHERE post_id = ?
               ORDER BY id DESC LIMIT 25
           )""",
        (row["id"], row["id"]),
    )


def page_counts(
    conn: sqlite3.Connection,
    post_type: str,
    *,
    owner_id: int | None = None,
) -> dict[str, int]:
    """Status counts for one content type, optionally restricted to one owner."""
    counts = {"all": 0, "published": 0, "draft": 0, "scheduled": 0}
    sql = "SELECT status, COUNT(*) AS n FROM posts WHERE type = ?"
    args: list[Any] = [post_type]
    if owner_id is not None:
        sql += " AND owner_id = ?"
        args.append(owner_id)
    for row in conn.execute(sql + " GROUP BY status", args):
        counts[str(row["status"])] = int(row["n"])
        counts["all"] += int(row["n"])
    return counts


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def resolve_owner_id(
    user: dict[str, Any],
    conn: sqlite3.Connection,
    requested: int | None,
    current: int,
) -> int:
    """Validate an ownership transfer request (or keep the current owner)."""
    if requested is None or requested == current:
        return current
    if not can(user, "content.others"):
        raise ApiError(
            403,
            "content.owner_transfer_forbidden",
            "只有管理员或可管理他人内容的编辑可以转移作者",
            field="owner_id",
        )
    target = conn.execute(
        "SELECT id, role, is_active FROM users WHERE id = ?", (requested,)
    ).fetchone()
    if not target or not target["is_active"]:
        raise ApiError(
            400,
            "content.owner_invalid",
            "目标作者不存在或已停用",
            field="owner_id",
        )
    return int(target["id"])


def assert_can_publish(user: dict[str, Any], status: str) -> None:
    """Publishing/scheduling needs `content.publish`, not just `content.write`."""
    if status != "draft" and not can(user, "content.publish"):
        raise ApiError(403, "content.publish_forbidden", "当前角色没有发布权限")


# ---------------------------------------------------------------------------
# Write pipeline
# ---------------------------------------------------------------------------

def _normalized_content(value: Any) -> str:
    content = str(value or "").strip()
    return f"{content}\n" if content else ""


def _provided_text(provided: dict[str, Any], key: str, current: str) -> str:
    """Omitted keeps `current`; explicit null clears to an empty string."""
    if key not in provided:
        return current
    value = provided[key]
    return "" if value is None else str(value)


def _kept_text(provided: dict[str, Any], key: str, current: str) -> str:
    """Omitted or null keeps `current` (for NOT NULL columns that cannot clear)."""
    if key not in provided or provided[key] is None:
        return current
    return str(provided[key])


def _flag(provided: dict[str, Any], key: str, current: int) -> int:
    if key not in provided:
        return current
    return 1 if provided[key] else 0


def _project_values(payload: ContentIn) -> dict[str, str]:
    return {
        column: str(getattr(payload, field, "") or "")
        for field, column in PROJECT_COLUMNS.items()
    }


def _merged_project_values(
    provided: dict[str, Any], row: sqlite3.Row
) -> dict[str, str]:
    values: dict[str, str] = {}
    for field, column in PROJECT_COLUMNS.items():
        if field in provided:
            raw = provided[field]
            values[column] = "" if raw is None else str(raw)
        else:
            values[column] = str(row[field] or "")
    return values


def _upsert_project_details(
    conn: sqlite3.Connection, post_id: int, values: dict[str, str]
) -> None:
    conn.execute(
        """INSERT INTO project_details(post_id, kind, year, role, client, url)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(post_id) DO UPDATE SET
               kind = excluded.kind,
               year = excluded.year,
               role = excluded.role,
               client = excluded.client,
               url = excluded.url""",
        (
            post_id,
            values["kind"],
            values["year"],
            values["role"],
            values["client"],
            values["url"],
        ),
    )


def insert_content(
    conn: sqlite3.Connection,
    post_type: str,
    payload: ContentIn,
    user: dict[str, Any],
) -> int:
    """Create one content row (plus project details / terms) and return its id."""
    if post_type not in POST_TYPES:
        raise ApiError(400, "content.unknown_type", "未知内容类型")
    owner_id = resolve_owner_id(user, conn, payload.owner_id, int(user["id"]))
    status, published_at = normalize_schedule(payload.status, payload.published_at)
    content = _normalized_content(payload.content_md)
    content_html = render_markdown(content)
    now = now_iso()
    slug = unique_slug(conn, payload.slug or payload.title, post_type=post_type)
    values: dict[str, Any] = {
        "type": post_type,
        "title": payload.title,
        "slug": slug,
        "excerpt": payload.excerpt or make_excerpt(content, 180),
        "content_md": content,
        "content_html": content_html,
        "render_version": RENDER_PIPELINE_VERSION,
        "cover_image": payload.cover_image,
        "status": status,
        "published_at": published_at,
        "featured": 1 if payload.featured else 0,
        "owner_id": owner_id,
        "seo_title": payload.seo_title,
        "seo_description": payload.seo_description,
        "reading_time": reading_time(content),
        "toc_json": json.dumps(extract_toc(content_html), ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO posts({columns}) VALUES ({placeholders})",
        list(values.values()),
    )
    post_id = _last_insert_id(cur)
    if post_type == "project" and isinstance(payload, ProjectIn):
        _upsert_project_details(conn, post_id, _project_values(payload))
    else:
        # Class-table inheritance: only projects may own a project_details row.
        conn.execute("DELETE FROM project_details WHERE post_id = ?", (post_id,))
    if isinstance(payload, PostIn):
        replace_post_terms(
            conn,
            post_id,
            categories=list(payload.categories),
            tags=list(payload.tags),
        )
    return post_id


def update_content(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    payload: ContentPatch,
    user: dict[str, Any],
) -> int:
    """Apply a PATCH payload to one content row and return its id."""
    post_id = int(row["id"])
    post_type = str(row["type"])
    provided = payload.model_dump(exclude_unset=True)

    content_changed = "content_md" in provided
    content = (
        _normalized_content(provided["content_md"])
        if content_changed
        else str(row["content_md"] or "")
    )
    content_html = (
        render_markdown(content) if content_changed else str(row["content_html"] or "")
    )
    if content_changed:
        reading_minutes = reading_time(content)
        toc_json = json.dumps(extract_toc(content_html), ensure_ascii=False)
        render_version = RENDER_PIPELINE_VERSION
    else:
        reading_minutes = int(row["reading_time"] or 0)
        toc_json = str(row["toc_json"] or "[]")
        render_version = int(row["render_version"] or 0)

    if "excerpt" in provided:
        excerpt = str(provided["excerpt"] or "").strip()
        excerpt = excerpt or make_excerpt(content, 180)
    else:
        excerpt = str(row["excerpt"] or "")

    title = _kept_text(provided, "title", str(row["title"] or ""))
    cover_image = _provided_text(provided, "cover_image", str(row["cover_image"] or ""))
    seo_title = _provided_text(provided, "seo_title", str(row["seo_title"] or ""))
    seo_description = _provided_text(
        provided, "seo_description", str(row["seo_description"] or "")
    )
    featured = _flag(provided, "featured", int(row["featured"] or 0))

    raw_status: Any = provided.get("status", row["status"])
    if raw_status is None:
        raw_status = row["status"]
    raw_published = provided.get("published_at", row["published_at"])
    status, published_at = normalize_schedule(str(raw_status), raw_published)

    slug = str(row["slug"] or "")
    if "slug" in provided and provided["slug"]:
        slug = unique_slug(
            conn, str(provided["slug"]), post_type=post_type, post_id=post_id
        )

    requested_owner = provided.get("owner_id") if "owner_id" in provided else None
    owner_id = resolve_owner_id(
        user, conn, requested_owner, int(row["owner_id"])
    )

    conn.execute(
        """UPDATE posts SET title = ?, slug = ?, excerpt = ?, content_md = ?,
               content_html = ?, render_version = ?, cover_image = ?, status = ?,
               published_at = ?, featured = ?, owner_id = ?, seo_title = ?,
               seo_description = ?, reading_time = ?, toc_json = ?, updated_at = ?
           WHERE id = ?""",
        (
            title,
            slug,
            excerpt,
            content,
            content_html,
            render_version,
            cover_image,
            status,
            published_at,
            featured,
            owner_id,
            seo_title,
            seo_description,
            reading_minutes,
            toc_json,
            now_iso(),
            post_id,
        ),
    )

    if post_type == "project":
        _upsert_project_details(conn, post_id, _merged_project_values(provided, row))
    else:
        conn.execute("DELETE FROM project_details WHERE post_id = ?", (post_id,))

    if isinstance(payload, PostPatch):
        if "categories" in provided:
            replace_terms(
                conn, post_id, "category", list(provided["categories"] or [])
            )
        if "tags" in provided:
            replace_terms(conn, post_id, "tag", list(provided["tags"] or []))

    if post_type == "post":
        save_revision(conn, row, int(user["id"]))
    return post_id


def restore_revision(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    revision: sqlite3.Row,
    owner_id: int,
) -> None:
    """Snapshot the current state, then restore one saved revision."""
    post_id = int(row["id"])
    save_revision(conn, row, owner_id)
    content = str(revision["content_md"] or "")
    content_html = render_markdown(content)
    conn.execute(
        """UPDATE posts SET title = ?, excerpt = ?, content_md = ?,
               content_html = ?, reading_time = ?, toc_json = ?,
               render_version = ?, updated_at = ?
           WHERE id = ?""",
        (
            revision["title"],
            revision["excerpt"],
            content,
            content_html,
            reading_time(content),
            json.dumps(extract_toc(content_html), ensure_ascii=False),
            RENDER_PIPELINE_VERSION,
            now_iso(),
            post_id,
        ),
    )
