-- MZTLAB · Scene 3.0.0 — schema v1 (empty-database initialisation only).
--
-- 3.0.0 deliberately does not accept a 2.x database: there is no migration,
-- no data import and no structural probing. A fresh `BLOG_DATA_DIR` is created
-- from this file; anything else fails loudly at startup.
--
-- Conventions:
--   * every authorizable row carries `owner_id REFERENCES users(id)` and user
--     deletion is RESTRICTed so content can never be orphaned;
--   * enum-like columns carry CHECK constraints, the database refuses invalid
--     combinations instead of relying on route-level resets;
--   * timestamps are ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`).

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    email         TEXT NOT NULL DEFAULT '',
    bio           TEXT NOT NULL DEFAULT '',
    avatar        TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'author' CHECK(role IN ('admin', 'editor', 'author')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    user_agent  TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Content -------------------------------------------------------------------
-- Class-table inheritance: shared columns live in `posts`, the project-only
-- fields live in `project_details`. `UNIQUE(type, slug)` lets a page and an
-- article share a slug because their public paths differ.

CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL CHECK(type IN ('post', 'project', 'page')),
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL,
    excerpt         TEXT NOT NULL DEFAULT '',
    content_md      TEXT NOT NULL DEFAULT '',
    content_html    TEXT NOT NULL DEFAULT '',
    render_version  INTEGER NOT NULL DEFAULT 8,
    cover_image     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'published', 'scheduled')),
    published_at    TEXT,
    featured        INTEGER NOT NULL DEFAULT 0,
    owner_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    seo_title       TEXT NOT NULL DEFAULT '',
    seo_description TEXT NOT NULL DEFAULT '',
    reading_time    INTEGER NOT NULL DEFAULT 0,
    toc_json        TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(type, slug)
);

CREATE INDEX IF NOT EXISTS idx_posts_public
    ON posts(type, status, published_at);
CREATE INDEX IF NOT EXISTS idx_posts_owner ON posts(owner_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_posts_updated ON posts(updated_at);

CREATE TABLE IF NOT EXISTS project_details (
    post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL DEFAULT '',
    year    TEXT NOT NULL DEFAULT '',
    role    TEXT NOT NULL DEFAULT '',
    client  TEXT NOT NULL DEFAULT '',
    url     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    excerpt    TEXT NOT NULL,
    content_md TEXT NOT NULL,
    owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_post ON revisions(post_id, created_at);

-- Taxonomy ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS taxonomy_terms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK(kind IN ('category', 'tag')),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE(kind, slug),
    UNIQUE(kind, name COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS post_terms (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    term_id INTEGER NOT NULL REFERENCES taxonomy_terms(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, term_id)
);

CREATE INDEX IF NOT EXISTS idx_post_terms_term ON post_terms(term_id);

-- Media ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    mime          TEXT NOT NULL,
    size          INTEGER NOT NULL,
    width         INTEGER NOT NULL DEFAULT 0,
    height        INTEGER NOT NULL DEFAULT 0,
    alt           TEXT NOT NULL DEFAULT '',
    owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    exif          TEXT NOT NULL DEFAULT '',
    -- Per-image AVIF override. Kept until the media pipeline moves to immutable
    -- global quality (Phase 3); the quality is always part of the derivative
    -- token.
    avif_quality      INTEGER NOT NULL DEFAULT 55 CHECK(avif_quality BETWEEN 1 AND 100),
    avif_quality_auto INTEGER NOT NULL DEFAULT 1 CHECK(avif_quality_auto IN (0, 1)),
    placeholder   TEXT NOT NULL DEFAULT '',
    ready_hash    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_media_owner ON media(owner_id, created_at);

CREATE TABLE IF NOT EXISTS media_derivatives (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id   INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    scene      TEXT NOT NULL,
    width      INTEGER NOT NULL,
    format     TEXT NOT NULL,
    quality    INTEGER NOT NULL,
    height     INTEGER NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL DEFAULT 0,
    key        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(media_id, scene, width, format)
);

CREATE INDEX IF NOT EXISTS idx_derivatives_media
    ON media_derivatives(media_id, format, width);

-- Galleries -----------------------------------------------------------------
-- A gallery is a curated set of photos. Photos reference a validated media
-- row and keep a filename snapshot. Ownership is inherited from the gallery.

CREATE TABLE IF NOT EXISTS galleries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published')),
    featured       INTEGER NOT NULL DEFAULT 0,
    cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    owner_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_galleries_public
    ON galleries(status, featured, updated_at);
CREATE INDEX IF NOT EXISTS idx_galleries_owner ON galleries(owner_id, updated_at);

CREATE TABLE IF NOT EXISTS photos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id     INTEGER REFERENCES galleries(id) ON DELETE SET NULL,
    media_id       INTEGER REFERENCES media(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    caption        TEXT NOT NULL DEFAULT '',
    location       TEXT NOT NULL DEFAULT '',
    camera         TEXT NOT NULL DEFAULT '',
    lens           TEXT NOT NULL DEFAULT '',
    taken_at       TEXT NOT NULL DEFAULT '',
    width          INTEGER NOT NULL DEFAULT 0,
    height         INTEGER NOT NULL DEFAULT 0,
    exif_fields    TEXT NOT NULL DEFAULT
                   'camera,lens,focal_length,aperture,exposure,iso,taken_at,dimensions',
    allow_download INTEGER NOT NULL DEFAULT 1,
    featured       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft', 'published')),
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_gallery ON photos(gallery_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status, featured, created_at);

-- Settings, jobs, metadata ---------------------------------------------------
-- Settings are five grouped JSON documents (site / appearance / copy / upload /
-- advanced). Secrets are never stored here: they come from the environment.

CREATE TABLE IF NOT EXISTS settings (
    "group"    TEXT PRIMARY KEY CHECK("group" IN ('site', 'appearance', 'copy', 'upload', 'advanced')),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK(kind IN (
                     'prewarm', 'reencode', 'gc_derivatives', 'rerender_content',
                     'storage_sync', 'export', 'rebuild_site')),
    payload      TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK(status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    progress     INTEGER NOT NULL DEFAULT 0,
    result       TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    attempts     INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, kind, created_at);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
