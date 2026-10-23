# MZTLAB · Scene API 参考（3.0.0）

> 适用版本：3.0.0。本文件由脚本生成（`python -m app.scripts.gen_docs`），请勿手改。

OpenAPI `3.0.0` · 61 个路径 · 168 个数据模型

鉴权：除 `/api/site`、`/api/bootstrap`、`/api/posts*`、`/api/pages*`、`/api/projects*`、`/api/galleries*`、`/api/archive`、`/api/search`、`/api/taxonomy`、`/api/health*`、`/api/auth/login`、`/api/setup` 外，均需登录；`/api/admin/*` 的写请求还需要 `X-Blog-Request: 1` 头。

## 端点

| 方法 | 路径 | 说明 | 2xx 响应模型 |
| --- | --- | --- | --- |
| GET | `/` | Root | OkResponse |
| GET | `/api/admin/content-authors` | Content Authors | ContentAuthorsResponse |
| GET | `/api/admin/export` | Export Site | ExportV3Response |
| GET | `/api/admin/galleries` | Admin Galleries | AdminGalleryListPayload |
| POST | `/api/admin/galleries` | Create Gallery | AdminGalleryPayload |
| DELETE | `/api/admin/galleries/{gallery_id}` | Delete Gallery | GalleryDeleteResponse |
| GET | `/api/admin/galleries/{gallery_id}` | Admin Gallery | AdminGalleryPayload |
| PATCH | `/api/admin/galleries/{gallery_id}` | Update Gallery | AdminGalleryPayload |
| PUT | `/api/admin/galleries/{gallery_id}` | Update Gallery | AdminGalleryPayload |
| POST | `/api/admin/galleries/{gallery_id}/photos` | Add Photos | GalleryPhotosAddedPayload |
| POST | `/api/admin/galleries/{gallery_id}/reorder` | Reorder Photos | GalleryReorderPayload |
| POST | `/api/admin/import` | Import Site | ImportV3Response |
| GET | `/api/admin/jobs` | Jobs List | JobListResponse |
| POST | `/api/admin/jobs` | Create Job | JobActionResponse |
| GET | `/api/admin/jobs/{job_id}` | Job Detail | JobStatusResponse |
| POST | `/api/admin/jobs/{job_id}/cancel` | Cancel | JobActionResponse |
| GET | `/api/admin/media` | List Media | MediaListPayload |
| POST | `/api/admin/media` | Upload Media | MediaUploadPayload |
| POST | `/api/admin/media/optimize-all` | Optimize All | JobQueuedPayload |
| DELETE | `/api/admin/media/{media_id}` | Delete Media | MediaDeleteResponse |
| GET | `/api/admin/media/{media_id}` | Media Detail | MediaItemPayload |
| PATCH | `/api/admin/media/{media_id}` | Update Media | MediaItemPayload |
| PUT | `/api/admin/media/{media_id}` | Update Media | MediaItemPayload |
| GET | `/api/admin/media/{media_id}/exif` | Media Exif | MediaExifResponse |
| PUT | `/api/admin/media/{media_id}/exif` | Update Media Exif | MediaItemPayload |
| POST | `/api/admin/media/{media_id}/optimize` | Optimize Media | JobQueuedPayload |
| GET | `/api/admin/pages` | Admin Pages | AdminContentListResponse |
| POST | `/api/admin/pages` | Create Page | AdminContentItem |
| DELETE | `/api/admin/pages/{post_id}` | Delete Page | ContentDeleteResponse |
| GET | `/api/admin/pages/{post_id}` | Admin Page | AdminContentDetail |
| PATCH | `/api/admin/pages/{post_id}` | Update Page | AdminContentItem |
| GET | `/api/admin/photos` | Admin Photos | PhotoListPayload |
| POST | `/api/admin/photos` | Create Photo | PhotoPayload |
| DELETE | `/api/admin/photos/{photo_id}` | Delete Photo | PhotoDeleteResponse |
| PATCH | `/api/admin/photos/{photo_id}` | Update Photo | PhotoPayload |
| PUT | `/api/admin/photos/{photo_id}` | Update Photo | PhotoPayload |
| GET | `/api/admin/posts` | Admin Posts | AdminContentListResponse |
| POST | `/api/admin/posts` | Create Post | AdminContentItem |
| DELETE | `/api/admin/posts/{post_id}` | Delete Post | ContentDeleteResponse |
| GET | `/api/admin/posts/{post_id}` | Admin Post | AdminContentDetail |
| PATCH | `/api/admin/posts/{post_id}` | Update Post | AdminContentItem |
| GET | `/api/admin/posts/{post_id}/revisions` | Revisions | RevisionListResponse |
| POST | `/api/admin/posts/{post_id}/revisions/{revision_id}/restore` | Restore Post Revision | AdminContentDetail |
| POST | `/api/admin/preview` | Preview | PreviewResponse |
| GET | `/api/admin/profile` | Get Profile | ProfileResponse |
| PUT | `/api/admin/profile` | Update Profile | ProfileUpdateResponse |
| GET | `/api/admin/projects` | Admin Projects | AdminContentListResponse |
| POST | `/api/admin/projects` | Create Project | AdminContentItem |
| DELETE | `/api/admin/projects/{post_id}` | Delete Project | ContentDeleteResponse |
| GET | `/api/admin/projects/{post_id}` | Admin Project | AdminContentDetail |
| PATCH | `/api/admin/projects/{post_id}` | Update Project | AdminContentItem |
| GET | `/api/admin/settings` | Get Settings | AdminSettingsResponse |
| PATCH | `/api/admin/settings` | Update Settings | AdminSettingsUpdateResponse |
| GET | `/api/admin/stats` | Stats | DashboardStats |
| GET | `/api/admin/storage/status` | Storage Status | StorageStatusResponse |
| POST | `/api/admin/storage/sync` | Storage Sync | JobQueuedPayload |
| POST | `/api/admin/storage/test` | Storage Test | StorageTestResponse |
| GET | `/api/admin/taxonomy` | Admin Taxonomy | TaxonomyAdminResponse |
| POST | `/api/admin/taxonomy/{kind}` | Create Term | TaxonomyTermResponse |
| DELETE | `/api/admin/taxonomy/{kind}/{term_id}` | Delete Term | TaxonomyDeleteResponse |
| PATCH | `/api/admin/taxonomy/{kind}/{term_id}` | Update Term | TaxonomyTermResponse |
| GET | `/api/admin/users` | List Users | AdminUserListResponse |
| POST | `/api/admin/users` | Create User | AdminUserMutationResponse |
| GET | `/api/admin/users/meta` | Users Meta | UsersMetaResponse |
| DELETE | `/api/admin/users/{user_id}` | Delete User | UserDeleteResponse |
| PUT | `/api/admin/users/{user_id}` | Update User | AdminUserMutationResponse |
| GET | `/api/archive` | Archive | ArchiveResponse |
| POST | `/api/auth/login` | Login | LoginResponse |
| POST | `/api/auth/logout` | Logout | OkResponse |
| GET | `/api/auth/me` | Me | ProfileResponse |
| GET | `/api/auth/status` | Auth Status | AuthStatusResponse |
| GET | `/api/bootstrap` | Bootstrap | BootstrapResponse |
| GET | `/api/galleries` | List Galleries | GalleryListResponse |
| GET | `/api/galleries/{slug}` | Gallery Detail | GalleryDetail |
| GET | `/api/health` | Health | HealthResponse |
| GET | `/api/health/edge` | Edge Health | EdgeHealthResponse |
| GET | `/api/pages` | List Pages | PageListResponse |
| GET | `/api/pages/{slug}` | Page Detail | ContentDetail |
| GET | `/api/posts` | List Posts | ContentListResponse |
| GET | `/api/posts/{slug}` | Post Detail | ContentDetail |
| GET | `/api/projects` | List Projects | ProjectListResponse |
| GET | `/api/projects/{slug}` | Project Detail | ContentDetail |
| GET | `/api/search` | Search | SearchResponse |
| POST | `/api/setup` | Setup | SetupResponse |
| GET | `/api/site` | Site Info | SiteInfoResponse |
| GET | `/api/taxonomy` | Taxonomy | TaxonomyResponse |
| GET | `/media/_v/{media_id}/{token}/{scene}/{name}` | Image Derivative | — |
| GET | `/media/{path}` | Media File | — |
