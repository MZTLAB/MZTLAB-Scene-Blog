-- MZTLAB · Scene 3.0.0 — schema v2: artifact-level image tokens.
--
-- Phase 3 makes every derivative addressable by the inputs that produced it:
--   token = sha1(PIPELINE_VERSION | media_id | source_sha1 | scene | width |
--                format | quality)[:10]
-- The token lives on the derivative row (`media_derivatives.token`) and the
-- media row caches the currently published set in `media.derivative_set` (JSON).
-- Reading a page therefore only assembles existing rows; changing the pipeline
-- never invalidates existing URLs and never re-encodes existing images.
--
-- Encoding quality is no longer user data: per-image `avif_quality` /
-- `avif_quality_auto` and `ready_hash` are removed (ADR-10). Quality and
-- encoding parameters live in `app.images.PIPELINE_DEFAULTS`; changing them
-- requires a manual `reencode` job.
--
-- `photos.allow_download` becomes `hide_download_link` with inverted semantics:
-- the old name implied access control, the new one says exactly what it does
-- (media is public; this only hides the download affordance).
--
-- SQLite needs a table rebuild to change constraints/defaults; run with foreign
-- keys disabled so dropping the old tables cannot cascade into galleries/photos.

PRAGMA foreign_keys = OFF;

CREATE TABLE media_v2 (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    filename       TEXT NOT NULL UNIQUE,
    original_name  TEXT NOT NULL,
    mime           TEXT NOT NULL,
    size           INTEGER NOT NULL,
    width          INTEGER NOT NULL DEFAULT 0,
    height         INTEGER NOT NULL DEFAULT 0,
    alt            TEXT NOT NULL DEFAULT '',
    owner_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    exif           TEXT NOT NULL DEFAULT '',
    -- SHA-1 of the original bytes; part of every derivative token.
    source_sha1    TEXT NOT NULL DEFAULT '',
    -- JSON: {"token": ..., "pipeline_version": ..., "ready": bool,
    --        "s": int, "l": int, "f": int,
    --        "scenes": {scene: {"widths": [...], "formats": [...]}}}
    derivative_set TEXT NOT NULL DEFAULT '',
    placeholder    TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL
);

INSERT INTO media_v2 (
    id, filename, original_name, mime, size, width, height, alt, owner_id,
    exif, source_sha1, derivative_set, placeholder, created_at
)
SELECT id, filename, original_name, mime, size, width, height, alt, owner_id,
       exif, '', '', placeholder, created_at
FROM media;

DROP TABLE media;
ALTER TABLE media_v2 RENAME TO media;
CREATE INDEX IF NOT EXISTS idx_media_owner ON media(owner_id, created_at);

CREATE TABLE media_derivatives_v2 (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id         INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    token            TEXT NOT NULL DEFAULT '',
    pipeline_version INTEGER NOT NULL DEFAULT 1,
    scene            TEXT NOT NULL,
    width            INTEGER NOT NULL,
    format           TEXT NOT NULL,
    quality          INTEGER NOT NULL,
    height           INTEGER NOT NULL DEFAULT 0,
    size             INTEGER NOT NULL DEFAULT 0,
    key              TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(media_id, token, scene, width, format)
);

INSERT INTO media_derivatives_v2 (
    id, media_id, token, pipeline_version, scene, width, format, quality,
    height, size, key, created_at
)
SELECT id, media_id, 'legacy', 1, scene, width, format, quality,
       height, size, key, created_at
FROM media_derivatives;

DROP TABLE media_derivatives;
ALTER TABLE media_derivatives_v2 RENAME TO media_derivatives;
CREATE INDEX IF NOT EXISTS idx_derivatives_media
    ON media_derivatives(media_id, format, width);
CREATE INDEX IF NOT EXISTS idx_derivatives_token
    ON media_derivatives(media_id, token);

CREATE TABLE photos_v2 (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id         INTEGER REFERENCES galleries(id) ON DELETE SET NULL,
    media_id           INTEGER REFERENCES media(id) ON DELETE CASCADE,
    filename           TEXT NOT NULL,
    title              TEXT NOT NULL DEFAULT '',
    caption            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    camera             TEXT NOT NULL DEFAULT '',
    lens               TEXT NOT NULL DEFAULT '',
    taken_at           TEXT NOT NULL DEFAULT '',
    width              INTEGER NOT NULL DEFAULT 0,
    height             INTEGER NOT NULL DEFAULT 0,
    exif_fields        TEXT NOT NULL DEFAULT
                       'camera,lens,focal_length,aperture,exposure,iso,taken_at,dimensions',
    hide_download_link INTEGER NOT NULL DEFAULT 0,
    featured           INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft', 'published')),
    sort_order         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);

INSERT INTO photos_v2 (
    id, gallery_id, media_id, filename, title, caption, location, camera, lens,
    taken_at, width, height, exif_fields, hide_download_link, featured, status,
    sort_order, created_at
)
SELECT id, gallery_id, media_id, filename, title, caption, location, camera, lens,
       taken_at, width, height, exif_fields,
       CASE WHEN allow_download = 1 THEN 0 ELSE 1 END,
       featured, status, sort_order, created_at
FROM photos;

DROP TABLE photos;
ALTER TABLE photos_v2 RENAME TO photos;
CREATE INDEX IF NOT EXISTS idx_photos_gallery ON photos(gallery_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status, featured, created_at);

-- Settings: drop the retired encoding-quality fields from the advanced document
-- (they are code constants from now on). The application also filters unknown
-- stored keys while loading, so this is a cleanup rather than a hard dependency.
UPDATE settings
SET data = json_remove(
        data,
        '$.image.avif_speed',
        '$.image.webp_quality',
        '$.image.jpeg_quality',
        '$.image.quality_thumb',
        '$.image.quality_tile',
        '$.image.quality_card',
        '$.image.quality_hero',
        '$.image.quality_viewer',
        '$.image.quality_prose',
        '$.image.quality_full'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE "group" = 'advanced';

PRAGMA foreign_keys = ON;
