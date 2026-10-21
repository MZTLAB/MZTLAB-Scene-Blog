-- MZTLAB · Scene 3.0.0 — schema v3: full-text search over content.
--
-- Phase 5 replaces the `LIKE '%needle%'` body scan with an FTS5 index. The
-- tokenizer is `trigram` on purpose: Chinese has no whitespace word boundaries,
-- and the trigram tokenizer gives case-insensitive substring matching without a
-- segmentation dictionary or another dependency. Trade-off: a *single* query
-- token shorter than 3 characters cannot be answered by the index (FTS5
-- limitation), so `app/posts.py` falls back to LIKE for such terms — the index
-- accelerates the common case and never changes the result set for short words.
--
-- The FTS table stores one row per post. `post_id` is UNINDEXED: it is only
-- carried along so the row can be joined back to `posts`. Triggers keep the
-- index in sync on insert/delete and on updates of the indexed text columns.
--
-- The file is idempotent (IF NOT EXISTS + guarded backfill), so re-running a
-- partially applied migration cannot duplicate FTS rows.

CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    post_id UNINDEXED,
    title,
    excerpt,
    content_md,
    seo_description,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS posts_fts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO content_fts(post_id, title, excerpt, content_md, seo_description)
    VALUES (new.id, new.title, new.excerpt, new.content_md, new.seo_description);
END;

CREATE TRIGGER IF NOT EXISTS posts_fts_ad AFTER DELETE ON posts BEGIN
    DELETE FROM content_fts WHERE post_id = old.id;
END;

-- FTS5 external-content cannot be used here (title/excerpt/... are real column
-- values, not `content=`), so an update is delete + insert of the new row.
CREATE TRIGGER IF NOT EXISTS posts_fts_au
AFTER UPDATE OF title, excerpt, content_md, seo_description ON posts BEGIN
    DELETE FROM content_fts WHERE post_id = old.id;
    INSERT INTO content_fts(post_id, title, excerpt, content_md, seo_description)
    VALUES (new.id, new.title, new.excerpt, new.content_md, new.seo_description);
END;

-- Backfill rows that existed before this migration. Guarded so a re-run cannot
-- duplicate a post's FTS row.
INSERT INTO content_fts(post_id, title, excerpt, content_md, seo_description)
SELECT p.id, p.title, p.excerpt, p.content_md, p.seo_description
FROM posts p
WHERE p.id NOT IN (SELECT post_id FROM content_fts);
