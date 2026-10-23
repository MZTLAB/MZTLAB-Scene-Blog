# MZTLAB · Scene 数据库结构（3.0.0）

> 适用版本：3.0.0-beta3。本文件由脚本生成（`python -m app.scripts.gen_docs`），请勿手改。

## 迁移文件

| # | 文件 |
| --- | --- |
| 1 | `0001_init.sql` |
| 2 | `0002_artifact_tokens.sql` |
| 3 | `0003_content_fts.sql` |

## 表

### `galleries`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `title` | TEXT | 否 | — |
| `slug` | TEXT | 否 | — |
| `description` | TEXT | 否 | `''` |
| `status` | TEXT | 否 | `'draft'` |
| `featured` | INTEGER | 否 | `0` |
| `cover_photo_id` | INTEGER | 是 | — |
| `owner_id` | INTEGER | 否 | — |
| `created_at` | TEXT | 否 | — |
| `updated_at` | TEXT | 否 | — |

外键：
- `owner_id` → `users.id`（ON DELETE RESTRICT）
- `cover_photo_id` → `photos.id`（ON DELETE SET NULL）

索引：
- `idx_galleries_owner`: owner_id, updated_at
- `idx_galleries_public`: status, featured, updated_at

### `jobs`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `kind` | TEXT | 否 | — |
| `payload` | TEXT | 否 | `'{}'` |
| `status` | TEXT | 否 | `'queued'` |
| `progress` | INTEGER | 否 | `0` |
| `result` | TEXT | 否 | `''` |
| `error` | TEXT | 否 | `''` |
| `attempts` | INTEGER | 否 | `0` |
| `heartbeat_at` | TEXT | 是 | — |
| `created_at` | TEXT | 否 | — |
| `started_at` | TEXT | 是 | — |
| `finished_at` | TEXT | 是 | — |

索引：
- `idx_jobs_status`: status, kind, created_at

### `media`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `filename` | TEXT | 否 | — |
| `original_name` | TEXT | 否 | — |
| `mime` | TEXT | 否 | — |
| `size` | INTEGER | 否 | — |
| `width` | INTEGER | 否 | `0` |
| `height` | INTEGER | 否 | `0` |
| `alt` | TEXT | 否 | `''` |
| `owner_id` | INTEGER | 否 | — |
| `exif` | TEXT | 否 | `''` |
| `source_sha1` | TEXT | 否 | `''` |
| `derivative_set` | TEXT | 否 | `''` |
| `placeholder` | TEXT | 否 | `''` |
| `created_at` | TEXT | 否 | — |

外键：
- `owner_id` → `users.id`（ON DELETE RESTRICT）

索引：
- `idx_media_owner`: owner_id, created_at

### `media_derivatives`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `media_id` | INTEGER | 否 | — |
| `token` | TEXT | 否 | `''` |
| `pipeline_version` | INTEGER | 否 | `1` |
| `scene` | TEXT | 否 | — |
| `width` | INTEGER | 否 | — |
| `format` | TEXT | 否 | — |
| `quality` | INTEGER | 否 | — |
| `height` | INTEGER | 否 | `0` |
| `size` | INTEGER | 否 | `0` |
| `key` | TEXT | 否 | — |
| `created_at` | TEXT | 否 | — |

外键：
- `media_id` → `media.id`（ON DELETE CASCADE）

索引：
- `idx_derivatives_token`: media_id, token
- `idx_derivatives_media`: media_id, format, width

### `photos`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `gallery_id` | INTEGER | 是 | — |
| `media_id` | INTEGER | 是 | — |
| `filename` | TEXT | 否 | — |
| `title` | TEXT | 否 | `''` |
| `caption` | TEXT | 否 | `''` |
| `location` | TEXT | 否 | `''` |
| `camera` | TEXT | 否 | `''` |
| `lens` | TEXT | 否 | `''` |
| `taken_at` | TEXT | 否 | `''` |
| `width` | INTEGER | 否 | `0` |
| `height` | INTEGER | 否 | `0` |
| `exif_fields` | TEXT | 否 | `'camera,lens,focal_length,aperture,exposure,iso,taken_at,dimensions'` |
| `hide_download_link` | INTEGER | 否 | `0` |
| `featured` | INTEGER | 否 | `0` |
| `status` | TEXT | 否 | `'published'` |
| `sort_order` | INTEGER | 否 | `0` |
| `created_at` | TEXT | 否 | — |

外键：
- `media_id` → `media.id`（ON DELETE CASCADE）
- `gallery_id` → `galleries.id`（ON DELETE SET NULL）

索引：
- `idx_photos_status`: status, featured, created_at
- `idx_photos_gallery`: gallery_id, sort_order, id

### `post_terms`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `post_id` | INTEGER | 否 | — |
| `term_id` | INTEGER | 否 | — |

外键：
- `term_id` → `taxonomy_terms.id`（ON DELETE CASCADE）
- `post_id` → `posts.id`（ON DELETE CASCADE）

索引：
- `idx_post_terms_term`: term_id

### `posts`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `type` | TEXT | 否 | — |
| `title` | TEXT | 否 | — |
| `slug` | TEXT | 否 | — |
| `excerpt` | TEXT | 否 | `''` |
| `content_md` | TEXT | 否 | `''` |
| `content_html` | TEXT | 否 | `''` |
| `render_version` | INTEGER | 否 | `8` |
| `cover_image` | TEXT | 否 | `''` |
| `status` | TEXT | 否 | `'draft'` |
| `published_at` | TEXT | 是 | — |
| `featured` | INTEGER | 否 | `0` |
| `owner_id` | INTEGER | 否 | — |
| `seo_title` | TEXT | 否 | `''` |
| `seo_description` | TEXT | 否 | `''` |
| `reading_time` | INTEGER | 否 | `0` |
| `toc_json` | TEXT | 否 | `'[]'` |
| `created_at` | TEXT | 否 | — |
| `updated_at` | TEXT | 否 | — |

外键：
- `owner_id` → `users.id`（ON DELETE RESTRICT）

索引：
- `idx_posts_updated`: updated_at
- `idx_posts_owner`: owner_id, updated_at
- `idx_posts_public`: type, status, published_at

### `project_details`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `post_id` | INTEGER | 是 | — |
| `kind` | TEXT | 否 | `''` |
| `year` | TEXT | 否 | `''` |
| `role` | TEXT | 否 | `''` |
| `client` | TEXT | 否 | `''` |
| `url` | TEXT | 否 | `''` |

外键：
- `post_id` → `posts.id`（ON DELETE CASCADE）

### `revisions`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `post_id` | INTEGER | 否 | — |
| `title` | TEXT | 否 | — |
| `excerpt` | TEXT | 否 | — |
| `content_md` | TEXT | 否 | — |
| `owner_id` | INTEGER | 是 | — |
| `created_at` | TEXT | 否 | — |

外键：
- `owner_id` → `users.id`（ON DELETE SET NULL）
- `post_id` → `posts.id`（ON DELETE CASCADE）

索引：
- `idx_revisions_post`: post_id, created_at

### `schema_meta`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `key` | TEXT | 是 | — |
| `value` | TEXT | 否 | — |

索引：

### `sessions`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `token_hash` | TEXT | 否 | — |
| `user_id` | INTEGER | 否 | — |
| `created_at` | TEXT | 否 | — |
| `expires_at` | TEXT | 否 | — |
| `user_agent` | TEXT | 否 | `''` |
| `ip` | TEXT | 否 | `''` |

外键：
- `user_id` → `users.id`（ON DELETE CASCADE）

索引：
- `idx_sessions_user`: user_id

### `settings`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `group` | TEXT | 是 | — |
| `data` | TEXT | 否 | — |
| `updated_at` | TEXT | 否 | — |

索引：

### `taxonomy_terms`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `kind` | TEXT | 否 | — |
| `name` | TEXT | 否 | — |
| `slug` | TEXT | 否 | — |
| `description` | TEXT | 否 | `''` |
| `created_at` | TEXT | 否 | — |

索引：

### `users`

| 列 | 类型 | 可空 | 默认值 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | — |
| `username` | TEXT | 否 | — |
| `password_hash` | TEXT | 否 | — |
| `display_name` | TEXT | 否 | — |
| `email` | TEXT | 否 | `''` |
| `bio` | TEXT | 否 | `''` |
| `avatar` | TEXT | 否 | `''` |
| `role` | TEXT | 否 | `'author'` |
| `is_active` | INTEGER | 否 | `1` |
| `last_login_at` | TEXT | 否 | `''` |
| `created_at` | TEXT | 否 | — |
| `updated_at` | TEXT | 否 | — |

索引：
