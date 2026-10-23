# MZTLAB · Scene 开发文档

> 适用版本：3.0.0
>
> 面向维护者的工程手册：架构、数据层、配置、写入管线、授权、媒体管线、契约生成与测试。
> 使用与部署见 [`README.md`](../README.md)；接入层要求见 [`EDGE.md`](EDGE.md)；数据库结构与 API 参考分别是脚本生成的 [`SCHEMA.md`](SCHEMA.md) 与 [`API.md`](API.md)。

---

## 目录

- [1. 快速定位](#1-快速定位)
- [2. 架构总览](#2-架构总览)
- [3. 数据层](#3-数据层)
- [4. 配置系统](#4-配置系统)
- [5. 内容写入管线](#5-内容写入管线)
- [6. 授权](#6-授权)
- [7. 媒体与图片管线](#7-媒体与图片管线)
- [8. 接入层契约](#8-接入层契约)
- [9. 契约与文档生成](#9-契约与文档生成)
- [10. 测试矩阵](#10-测试矩阵)
- [11. SSG 预留与附录 B](#11-ssg-预留与附录-b)
- [12. 常见任务操作手册](#12-常见任务操作手册)
- [13. 编码约定与风险清单](#13-编码约定与风险清单)
- [14. 相关文档](#14-相关文档)

---

## 1. 快速定位

| 想改什么                                         | 去哪里改                                                                                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| 站点名、导航、页脚、SEO、每页条数                | `backend/app/settings/models.py` 的 `SiteSettings`；后台“设置”页                                  |
| 主题、明暗、强调色、宽度、Hero、自定义 CSS       | `backend/app/settings/models.py` 的 `AppearanceSettings`；`frontend/src/styles/`                  |
| 页面固定文案                                     | `backend/app/settings/models.py` 的 `CopySettings`；前端通过 `copyReader()` 读取                  |
| 上传大小与允许格式                               | `backend/app/settings/models.py` 的 `UploadSettings`                                              |
| 派生图宽度阶梯、格式开关                         | `ImagePipelineSettings`（`advanced.image`）                                                       |
| 派生图编码质量/编码参数                          | `backend/app/images.py` 的 `PIPELINE_DEFAULTS`（改后需提升 `PIPELINE_VERSION` 并手动 `reencode`） |
| Markdown 渲染、摘录、slug、阅读时长              | `backend/app/content.py`                                                                          |
| 文章/项目/页面写入规则（发布、slug、标签、修订） | `backend/app/services/content_admin.py`                                                           |
| 所有权与权限校验                                 | `backend/app/services/authz.py`、`backend/app/permissions.py`                                     |
| 文章/相册查询与 JSON 形状                        | `backend/app/posts.py`、`backend/app/galleries.py`                                                |
| 图片派生、token、`derivative_set`                | `backend/app/images.py`                                                                           |
| 媒体上传                                         | `backend/app/routes/media.py`                                                                     |
| 媒体读取（原图/派生图）                          | `backend/app/routes/media_serve.py`、`backend/app/storage.py`                                     |
| 后台任务（队列/心跳/恢复）                       | `backend/app/jobs.py`、`backend/app/routes/jobs.py`                                               |
| 公开页面数据聚合                                 | `backend/app/services/page_data.py`、`backend/app/routes/public.py`                               |
| 页面结构 / 组件                                  | `frontend/src/pages/`、`frontend/src/components/`、`frontend/src/layouts/`                        |
| 后台交互脚本                                     | `frontend/src/scripts/`                                                                           |
| 新增/修改 API 接口                               | `backend/app/routes/*.py` + `backend/app/api/models.py`（响应模型）                               |
| 数据表/索引                                      | `backend/migrations/*.sql`（新迁移文件，不修改已发布文件）                                        |
| 环境变量                                         | `backend/app/config.py`、`.env.example`                                                           |

---

## 2. 架构总览

### 2.1 进程与拓扑

```text
浏览器
  │  HTTPS
  ▼
运维 nginx（仓库不提交配置；TLS/HSTS、路由、体积、日志）
  ├── /api/    → FastAPI 127.0.0.1:8000
  ├── /media/  → FastAPI 127.0.0.1:8000（proxy_buffering off）
  └── /*       → Astro SSR 127.0.0.1:4321
```

- **Astro**：渲染公共页与 `/admin` 页面，提供 `/_astro/*` 资产；服务端取数走 `BLOG_API_INTERNAL_URL`（默认 `http://127.0.0.1:8000`）。Astro **不再代理** `/api`、`/media`。
- **FastAPI**：JSON API 与媒体字节流；只监听回环/私网，由接入层转发。
- **本地开发**：不启动 nginx；Astro/Vite 的仅 dev 生效 `vite.server.proxy`（`xfwd: false`）把 `/api`、`/media` 转发到本机 FastAPI，浏览器保持同源 `127.0.0.1:4321`。
- **单进程约束**：应用层限流与设置缓存都在进程内存，`WEB_CONCURRENCY > 1` 时后端拒绝启动。

### 2.2 后端包职责

| 模块                                     | 职责                                                              |
| ---------------------------------------- | ----------------------------------------------------------------- |
| `app/config.py`                          | 环境变量、路径、版本、可信代理、上传上限等部署级常量              |
| `app/db.py`                              | SQLite 连接与短事务上下文、迁移应用、启动结构校验                 |
| `app/settings/`                          | 五组设置模型（`models.py`）、存储与 PATCH 合并（`store.py`）      |
| `app/permissions.py`                     | 角色 → 权限矩阵（唯一来源）                                       |
| `app/services/authz.py`                  | 统一的 `owner_id` 所有权校验                                      |
| `app/services/content_admin.py`          | 文章/项目/页面共享写入管线（渲染物料化、slug、排期、标签、修订）  |
| `app/services/page_data.py`              | 公共页聚合数据 `page_data()`（`/api/bootstrap` 的实现）           |
| `app/services/backup.py`                 | 3.0.0 导出格式的校验与恢复                                        |
| `app/content.py`                         | Markdown 渲染（bleach 白名单）、摘录、阅读时长、TOC、slug         |
| `app/posts.py` / `app/galleries.py`      | 内容/相册查询与序列化（公开与后台共用）                           |
| `app/images.py`                          | 派生图计划、token、编码、`derivative_set`、srcset、GC、内联图重写 |
| `app/storage.py` / `app/storage_sync.py` | 本地/S3 存储抽象与本地→远端同步                                   |
| `app/jobs.py`                            | `jobs` 表队列、单 worker 线程、心跳、恢复、任务处理器             |
| `app/routes/`                            | 每个资源一个路由模块，只处理 HTTP 关注点                          |
| `app/api/models.py`                      | 所有 `response_model` DTO（OpenAPI 契约来源）                     |
| `app/scripts/`                           | 契约导出、契约审计、公共页渲染审计、文档生成                      |
| `migrations/*.sql`                       | 版本化建库 SQL（只新增，不修改已发布文件）                        |

### 2.3 前端分层

| 目录                | 职责                                                                                                                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/pages/`        | Astro 路由：公共页、`/admin/*`、`rss.xml` / `sitemap.xml` / `robots.txt`                                                                                                                                                                   |
| `src/layouts/`      | `BaseLayout`（公共页壳）、`AdminLayout`、`AuthLayout`                                                                                                                                                                                      |
| `src/components/`   | 展示组件；`SmartImage` 负责 `<picture>`/srcset 与未就绪回退                                                                                                                                                                                |
| `src/lib/`          | 纯函数与客户端：`api.ts`（`getBootstrap()` 聚合取数、浏览器请求）、`images.ts`、`format.ts`、`auth.ts`、`jobs.ts`、`site.ts`                                                                                                               |
| `src/scripts/`      | 后台页面的 DOM 交互脚本（原生 TypeScript）                                                                                                                                                                                                 |
| `src/api/`          | 生成的 `openapi.json` 与 `types.gen.ts`（勿手改）                                                                                                                                                                                          |
| `src/styles/`       | 细粒度、按层组织的全局样式：`tokens/`（含 `tokens/admin/` 后台冻结值）、`base/`、`shared/`、`site/`、`admin/`、`audio-player.css`；每个组件 import 自己的样式，`@layer` 顺序由 layout `<head>` 的内联声明权威固定。详见 [`CSS.md`](CSS.md) |
| `src/middleware.ts` | 页面安全响应头、旧 `?page=` → 路径式分页的 301、公共页弱 ETag/304 与 admin `no-store` 缓存策略、`X-Request-ID` 兜底                                                                                                                        |

---

## 3. 数据层

### 3.1 迁移与初始化

- 结构由 `backend/migrations/` 下的版本化 SQL 文件定义；编号前缀即结构版本。当前 `SCHEMA_VERSION = 3`。
- 空库首次启动时由 `app.db` 按顺序应用全部迁移，并写入 `schema_meta` 与 `PRAGMA user_version`。
- **只支持空库初始化**：启动时若发现旧版本、缺失必需表或非 3.0.0 结构，抛出 `SchemaVersionError` 并提示清空 `BLOG_DATA_DIR`；不存在 2.x 数据迁移路径。
- 人工/CI 的结构操作走显式命令：`python scripts/db.py migrate`、`status`、`verify`（完整性、外键、结构版本）。应用启动不会自动迁移既有数据。
- 新增结构变更 = 新增一个 `NNNN_name.sql`，并把 `SCHEMA_VERSION` 加一；**不要改已发布的迁移文件**。

### 3.2 表清单

完整字段、外键与索引见脚本生成的 [`SCHEMA.md`](SCHEMA.md)（由 `python -m app.scripts.gen_docs` 从迁移文件生成，勿手改）。概念分组：

| 组   | 表                                      | 说明                                                                           |
| ---- | --------------------------------------- | ------------------------------------------------------------------------------ |
| 账号 | `users`、`sessions`                     | 角色、权限、scrypt 密码哈希、会话 token 指纹                                   |
| 内容 | `posts`、`project_details`、`revisions` | 文章/项目/页面共用 `posts`；项目字段类表继承；修订保留最近 25 条               |
| 分类 | `taxonomy_terms`、`post_terms`          | 分类与标签共用一张表，`kind` 区分                                              |
| 媒体 | `media`、`media_derivatives`            | 原图元数据 + 派生图行（token 寻址）；`media.derivative_set` 缓存已发布产物集合 |
| 相册 | `galleries`、`photos`                   | 相册持有 `owner_id`，照片继承相册所有权                                        |
| 配置 | `settings`                              | 五组 JSON 文档（`site`/`appearance`/`copy`/`upload`/`advanced`）               |
| 任务 | `jobs`                                  | 持久任务队列：状态、进度、心跳、结果、错误                                     |
| 搜索 | `content_fts`（FTS5）                   | trigram 分词全文索引；短于 3 字符的查询回退 LIKE                               |
| 版本 | `schema_meta`                           | 结构版本与迁移记录                                                             |

### 3.3 事务与并发

- `app.db.db()` 是**短事务**上下文：成功提交、异常回滚。长耗时工作（文件流、Pillow 解码/编码、对象存储 I/O、构建）必须在事务外完成。
- SQLite 单写者：连接启用 WAL、`busy_timeout`，写事务保持短小，避免阻塞其他请求。
- 跨进程协作只通过数据库（如 `jobs` 表），不引入 Redis 或内存共享。
- 幂等：迁移文件使用 `IF NOT EXISTS`/幂等语句；重复执行不得产生重复数据。

### 3.4 备份与恢复

- `python scripts/backup.py`：用 SQLite 在线备份 API 生成一致快照，并做 `integrity_check`；`--include-media` 把 `uploads/`、`cache/` 打成 `tar.gz`，同时写 manifest JSON。
- 恢复流程（离线）：停后端 → 用备份覆盖 `BLOG_DATA_DIR` → `python scripts/db.py verify` → 启动并抽查后台与公共页。**恢复演练已验证**：`python scripts/backup.py --include-media` → 恢复到第二个数据目录 → `python scripts/db.py verify`（完整性/外键/结构版本）→ 启动并核对 `/api/site`、`/api/posts` 计数一致。
- 后台另有 3.0.0 格式的 JSON 导出/导入（`GET /api/admin/export`、`POST /api/admin/import`）：格式为数据库形状 + 完整设置文档，导入前完整校验、单事务替换；**媒体二进制不在 JSON 内**，导入后报告缺失文件。2.x 文档会被拒绝。

---

## 4. 配置系统

### 4.1 五组设置

- `site`：站点标识、`site_url`、导航/社交/页脚、SEO、分页与相册列数、公告、`editor_manage_others`。
- `appearance`：主题、明暗、强调色、字体、宽度、圆角、Hero、`custom_css`、`head_html`。
- `copy`：所有页面固定文案（字段名即 JSON 路径，如 `copy.photos_title`）。
- `upload`：`max_mb` 与图片/音频/文件格式白名单。
- `advanced.image`：派生图宽度阶梯与格式开关；`advanced.storage`：存储坐标（非密钥）。

`app/settings/models.py` 是字段名、默认值与校验的**唯一来源**；前端类型由 OpenAPI 生成。S3 访问密钥只来自环境变量（`BLOG_S3_ACCESS_KEY` / `BLOG_S3_SECRET_KEY`），永不入库、不出现在任何响应。

### 4.2 读取与写入

- 存储为 `settings("group", data, updated_at)` 一行一组 JSON。读取时把存储文档合并到模型默认值上，并丢弃当前模型不认识的旧键。
- `save_settings_patch()`：先加载当前完整文档，只覆盖 PATCH 提供的字段，对**合并后的完整文档**做模型校验，然后在一个短事务中写五组；失败则整体不写。
- PATCH 语义：省略字段 = 保持；显式 `null` = 对可空字段清空；未知字段被 `extra="forbid"` 拒绝。
- 进程内缓存 `load_settings_cached()`（短 TTL + 保存时失效）；因强制单 worker，缓存是该进程内权威值。

### 4.3 部署级环境变量

由 `app/config.py` 读取（清单见 [`.env.example`](../.env.example)）：`BLOG_SITE_URL`、`BLOG_DATA_DIR`、`BLOG_API_INTERNAL_URL`、`BLOG_TRUSTED_PROXY`、`BLOG_SESSION_DAYS`、`BLOG_COOKIE_SECURE`、`BLOG_ENABLE_API_DOCS`、`BLOG_SEED_DEMO`、`BLOG_MAX_UPLOAD_MB`、`BLOG_ADMIN_MAX_UPLOAD_MB`、`BLOG_IMAGE_CACHE_DIR`、`BLOG_IMAGE_ENCODE_WORKERS`、`BLOG_STORAGE_BACKEND`、`BLOG_S3_*`、`WEB_CONCURRENCY`。

`COOKIE_SECURE` 默认由公共 URL 是否为 https 推导；生产只需正确设置 `BLOG_SITE_URL`。

### 4.4 不可运行时修改的图片参数

编码质量、AVIF speed、full 场景宽度上限是 `app/images.py` 的 `PIPELINE_DEFAULTS` 常量（见 ADR-10）。修改步骤：改常量 → 提升 `PIPELINE_VERSION` → 新上传自动使用新参数 → 需要历史的图像时手动创建 `reencode` 任务。**不要**把质量重新做成设置项或数据库列。

---

## 5. 内容写入管线

### 5.1 类表继承与所有权

- 文章、项目、页面共用 `posts`（`type` 区分），项目专属字段在 `project_details`，通过 `post_id` 一对一。
- 每行有 `owner_id`；`UNIQUE(type, slug)` 允许不同类型复用同一 slug。
- 项目之外的 `type` 不允许拥有 `project_details` 行（写入管线会清理）。

### 5.2 物化渲染

保存内容时同步物化以下列，读路径不再渲染 Markdown：

| 字段             | 内容                                                   |
| ---------------- | ------------------------------------------------------ |
| `content_html`   | bleach 白名单清理后的 HTML                             |
| `reading_time`   | 估算阅读分钟数                                         |
| `toc_json`       | 标题大纲 JSON                                          |
| `render_version` | 渲染管线版本 `RENDER_PIPELINE_VERSION`，用于批量重渲染 |
| `excerpt`        | 未提供时由正文生成                                     |

Markdown 渲染管线变更时提升 `RENDER_PIPELINE_VERSION`，通过 `rerender_content` 任务重写 `content_html`/`render_version`（`reencode` 任务结束时会自动入队一次）。

### 5.3 slug、排期、标签与修订

- slug：`(type, slug)` 唯一，冲突自动加后缀；`type='page'` 额外避开内置路由（`RESERVED_PAGE_SLUGS`）。
- 排期：`draft` / `published` / `scheduled` 按 `published_at` 归一；发布/定时发布需要 `content.publish`。
- 标签/分类：写入时 upsert 到 `taxonomy_terms`，通过 `post_terms` 全量替换某一种类的关联。
- 修订：文章 PATCH 前保存上一版（标题/摘录/正文/作者），每篇最多保留 25 条；恢复修订会先快照当前状态。
- 所有权转移需要 `content.others`，且目标账号必须存在并启用。

---

## 6. 授权

- `app/permissions.py` 定义 11 个权限键与三种角色（`admin` / `editor` / `author`）的映射，**其他任何地方不得复制角色矩阵**。
- 会话携带 `permissions` 列表；`can(user, key)` 只查该列表，没有“按角色名回退”的漏洞路径。
- `site.editor_manage_others` 打开时，编辑者额外获得 `content.others`；管理员始终拥有。
- `app/services/authz.py` 是所有权唯一入口：`authorize(user, row, action)`；照片通过所属相册的 `owner_id` 鉴权。
- 后台写请求（`/api/admin/*` 的 POST/PUT/PATCH/DELETE）要求 `X-Blog-Request: 1` 头作为 CSRF 辅助校验；前端 `api()` / `apiServer()` 统一附带。
- 账号安全规则：不能降级/停用自己；最后一个启用管理员不可降级/停用/删除；改密或停用会撤销该账号所有会话。

---

## 7. 媒体与图片管线

### 7.1 上传

- 上传是**同步路由**（线程池执行，不占事件循环）：以 1 MB 块流式写入临时文件，同时计算 SHA-1；超过上限立即返回 413，绝不把整文件读进内存。
- Pillow 校验临时文件后原子移动到 `uploads/YYYY/MM/{uuid}.{ext}`，随后写入 `media` 行；图片额外入队 `prewarm` 任务。
- 管理员不受“上传策略”的格式/大小限制，只受 `BLOG_ADMIN_MAX_UPLOAD_MB` 技术上限约束。

### 7.2 后台任务

所有维护动作都是 `jobs` 表中的持久任务，由 FastAPI 生命周期里的**单 worker 线程**消费（`app/jobs.py`）：

| kind               | 作用                                                                |
| ------------------ | ------------------------------------------------------------------- |
| `prewarm`          | 为一张图片生成完整产物集                                            |
| `reencode`         | 强制重编码一个范围（媒体/相册/全部），结束后入队 `rerender_content` |
| `rerender_content` | 重渲染引用了媒体的已发布文章                                        |
| `gc_derivatives`   | 删除不再被 `derivative_set` 引用的派生行/对象                       |
| `storage_sync`     | 把本地原图/派生图强制同步到对象存储                                 |
| `export`           | 预留（执行器后续版本实现），任务以说明结果完成                      |
| `rebuild_site`     | 预留（R5）：API 可创建，worker 永不 claim，行保持 `queued`          |

队列语义：原子 claim（`UPDATE ... RETURNING`）、按 kind 的优先级（交互任务优先）、心跳（`heartbeat_at`）、启动时回收心跳超时的 `running` 行（超次数则失败）、只有 `queued` 任务可取消（取消 `running` 返回 409）。

### 7.3 产物 token 与 `derivative_set`

- `token = sha1(PIPELINE_VERSION | media_id | source_sha1 | scene | width | format | quality)[:10]`。
- 派生图键为 `_derived/{media_id}/{token}/{scene}/{width}.{ext}`，URL 只由产物输入决定，因此可长期缓存，改配置不会污染既有页面。
- `media.derivative_set` 存 JSON：`ready`、`artifacts`（scene → width → format → token）、尺寸与 `pipeline_version`。只有在全部产物成功后才整体替换。
- `images.image_payload()` 是**只读**：未就绪或不可转换时返回 `ready: false` 且不给出派生 URL；前端 `SmartImage` 回退原图。读路径永不现场编码（R4）。

### 7.4 读取与存储

- `/media/{path}` 服务原图；`/media/_v/{media_id}/{token}/{scene}/{width}.{ext}` 服务派生图：只有存在精确坐标的 `media_derivatives` 行才返回，否则 404（由前端回退原图）。
- 读取只经过 `Storage.size()` / `Storage.stream()` 抽象，不依赖本地路径或后端分支；因此本地磁盘、S3 与镜像包装器共用同一套代码。
- 不可变派生 URL 返回长缓存头；原图保留 `Content-Disposition` / 沙箱 CSP 等安全规则。
- 存储后端：`local`（默认）或 `s3`（R2 为参考）；坐标在后台设置，凭据只在环境变量；`storage_sync` 用于切换后端、恢复桶或修复缺失对象。

---

## 8. 接入层契约

完整要求、参考片段与上线核对清单见 [`EDGE.md`](EDGE.md)；这里只列维护者需要知道的约定：

- 路由：`/api/`、`/media/` → FastAPI 8000；其余 → Astro 4321。两个进程只监听回环/私网。
- 转发头：接入层必须**覆盖**写 `X-Forwarded-For: $remote_addr`（禁止追加语义）、`X-Forwarded-Proto: $scheme`、`Host: $host`。后端以 `--proxy-headers --forwarded-allow-ips=${BLOG_TRUSTED_PROXY:-127.0.0.1}` 启动，只信任该 peer。
- `X-Request-ID`：接入层可选生成；FastAPI 与 Astro 在缺失时兜底生成并回写响应头。
- `GET /api/health/edge` 返回应用实际观测到的 `client_ip`、`forwarded_for`、`forwarded_proto`、`request_id`、`trusted_proxy`、`cookie_secure`，是“仓库不提交 nginx 配置”的运行时补偿。
- 本地开发不涉及 nginx：dev-only Vite proxy（`xfwd: false`）承担路由；接入层行为只在 staging/生产按 EDGE 清单验证。
- 应用层限流必须存在（登录 IP + 账号、上传、预览），nginx 限流只是可选加固。

---

## 9. 契约与文档生成

契约的单一来源是后端路由的 `response_model`：

```bash
cd backend
python -m app.scripts.export_contracts     # → frontend/src/api/openapi.json
python -m app.scripts.audit_contracts      # 2xx JSON 必须为命名 $ref，禁止 additionalProperties: true
python -m app.scripts.gen_docs             # → docs/SCHEMA.md + docs/API.md
python -m app.scripts.check_public_render  # 公共页禁读 cookie/session/UA/请求头；禁 ?page= 分页
cd ../frontend
npm run gen:types                          # openapi.json → src/api/types.gen.ts
```

- `openapi.json` 与 `types.gen.ts` 是**生成物**，提交到仓库，CI 重跑后要求 `git diff --exit-code`；手改类型或契约会失败。
- `check_public_render` 是 SSG 预留 R3 的静态审计：公共页与共享组件不得出现 `Astro.request/cookies/clientAddress/locals`、cookie 头、user-agent、`searchParams.get('page')`。
- `gen_docs` 从迁移文件与 `openapi.json` 生成文档；不要手写字段表。
- 新增/修改接口的流程：在 `app/api/models.py` 定义 DTO → 路由声明 `response_model` → 导出契约 → 生成类型 → 生成文档 → 提交全部生成物。

---

## 10. 测试矩阵

| 层            | 命令                                                                                                                                                                                                                   | 内容                                                                                                    |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 后端静态检查  | `cd backend && python -m ruff check app`、`python -m mypy app`                                                                                                                                                         | 新代码严格；存量模块在 `pyproject.toml` 的 ratchet 清单中逐步减少                                       |
| 后端单测/集成 | `cd backend && python -m pytest`                                                                                                                                                                                       | 内容渲染、EXIF、slug、设置、权限、jobs、媒体上传/读取、搜索、导出导入、HTTP 集成                        |
| 契约          | `export_contracts` + `gen:types` + `git diff`                                                                                                                                                                          | 响应模型与前端类型一致                                                                                  |
| 公共页审计    | `check_public_render`                                                                                                                                                                                                  | R3 渲染上下文约束 + 路径分页                                                                            |
| 前端检查      | `cd frontend && npm run check`                                                                                                                                                                                         | Astro + TypeScript                                                                                      |
| 前端 lint     | `cd frontend && npm run lint`                                                                                                                                                                                          | ESLint；`npm run format:check` 检查 Prettier 格式                                                       |
| 前端样式      | `npm run css:check -- --allow-important animation,transition,animation-duration,transition-duration`（结构 lint，`--strict` 才失败）+ `css:snapshot`/`css:diff`（级联等价性，改样式时使用）；说明见 [`CSS.md`](CSS.md) | —                                                                                                       |
| 前端单测      | `cd frontend && npm test`                                                                                                                                                                                              | vitest                                                                                                  |
| 前端构建      | `cd frontend && npm run build`                                                                                                                                                                                         | 生产构建必须成功                                                                                        |
| 一键验收      | `python scripts/verify.py [--skip-slow]`                                                                                                                                                                               | 串联上述门禁（含契约/文档漂移）并执行运行时 smoke；`scripts/verify.sh`、`scripts/verify.ps1` 为等价包装 |
| 接入层        | staging 按 [`EDGE.md`](EDGE.md) 核对清单 + curl                                                                                                                                                                        | 伪造 XFF 无效、413 来自 nginx、Cookie `Secure`、`X-Request-ID` 贯通、`/media` 无缓冲                    |

> CI（`.github/workflows/ci.yml`）分四个 job：backend（ruff/mypy/契约审计/公共页审计/pytest）、frontend（check/lint/build/vitest）、contracts（重新生成契约与类型后 `git diff --exit-code`）、acceptance（`python scripts/verify.py --skip-slow`，含运行时 smoke）。

### 一键验收

`python scripts/verify.py` 是 3.0.0 的发布准入脚本，按顺序执行并打印 PASS/FAIL 表：

- 后端：`ruff check app tests`、`mypy app`、`pytest tests`。
- 契约：`audit_contracts`、重新导出 `openapi.json` 与重新生成 `types.gen.ts` 后做漂移检查。
- 文档：重新生成 `docs/SCHEMA.md`、`docs/API.md` 后做漂移检查。
- 公共页：`check_public_render`（当前扫描 32 个文件、0 处请求上下文读取）。
- 前端：`npm run check`、`npm run lint`、`npm run build`。
- 运行时 smoke：用临时数据目录启动 uvicorn，断言 `/api/site` 分组设置、`/api/bootstrap?route=home` 返回 200 且带 ETag、`If-None-Match` 返回 304、`/api/posts` 可读、已移除的 `/api/comments` 返回 404。

`--skip-slow` 跳过 mypy、pytest、前端构建等慢步骤，适合本地快速循环；`--no-smoke` 只去掉运行时 smoke。漂移类步骤会先快照生成物、比对后再还原，因此运行验收不会弄脏工作区；smoke 拒绝在 `.env` 固定了真实 `BLOG_DATA_DIR`/`BLOG_DB_PATH` 时运行，避免碰到开发者的数据库。

测试约定：

- HTTP 集成测试用 `httpx`/`TestClient` 与临时数据目录；测试时设 `BLOG_DISABLE_JOBS_WORKER=1` 并显式调用 `jobs.run_once()` 驱动队列。
- 失败路径（401/403/404/409/413/422/429）必须覆盖；错误体统一为 `{"error": {"code", "message", "field?"}}`。
- 图片相关测试不得依赖网络或固定测试图之外的资源。

---

## 11. SSG 预留与附录 B

3.0.0 **不实现 SSG**，但完成了 7 项预留（详见 [`SSG-FEASIBILITY.md`](SSG-FEASIBILITY.md) 与重构方案附录 B）：

| 预留 | 内容                                             | 当前实现                                                                                                                                                                                      |
| ---- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1   | 单一聚合读接口 `/api/bootstrap`（`page_data()`） | 已实现：后端接口 + 所有公共页恰好调用一次 `getBootstrap()`，不再逐页拼接接口；无请求上下文、无 cookie，可构建期调用                                                                           |
| R2   | 路径式分页 + 旧 `?page=` 301                     | 已实现：`/tags/{tag}/page/{n}`、`/categories/{category}/page/{n}` 路由，旧 `?page=N` 由 `middleware.ts` 301 到路径；`Pagination.astro` 输出路径 URL。`/photos`、`/projects` 按设计保持第 1 页 |
| R3   | 公共页禁读请求上下文                             | 已实现：`check_public_render` 进 CI，当前 32 个文件 0 处请求上下文读取                                                                                                                        |
| R4   | `derivative_set` 物化 + 只读 `image_payload`     | 已实现；读路径不编码，未就绪回退原图                                                                                                                                                          |
| R5   | `jobs.kind='rebuild_site'` 形状预留              | 已实现；worker 永不 claim，行保持 `queued`                                                                                                                                                    |
| R6   | 页面不引用运行期临时路径                         | 已实现；`/_astro` 与媒体 URL 稳定                                                                                                                                                             |
| R7   | 5xx 语义（页面错误页、API 统一错误体）           | 已实现；`/500` 页面与统一错误体                                                                                                                                                               |

迁移前的完整检查清单、备选方案与工作量见 [`SSG-FEASIBILITY.md`](SSG-FEASIBILITY.md)。

---

## 12. 常见任务操作手册

### 新增一个设置项

1. 在 `app/settings/models.py` 对应分组模型加字段（默认值 + 校验），并在同名 `*Patch` 模型加可选字段。
2. 后台设置页模板/脚本读取并提交该字段（`frontend/src/pages/admin/settings.astro`、`scripts/admin-settings.ts`）。
3. 运行 `export_contracts` → `gen:types` → `gen_docs`，提交生成物。
4. 补一个设置测试（PATCH 后读回；非法值 422）。

### 新增一个后台字段（内容类）

1. 迁移文件增加列（`backend/migrations/NNNN_*.sql`）并提升 `SCHEMA_VERSION`。
2. `app/schemas.py` 的 In/Patch 模型加字段；`app/services/content_admin.py` 的插入/更新 SQL 与序列化同步。
3. `app/api/models.py` 的响应模型加字段 → 重新生成契约与类型。
4. 前端编辑器加控件并提交该字段；补写入与序列化测试。

### 新增一个 API 接口

1. 在对应 `app/routes/*.py` 加处理函数，声明 `response_model`；权限用 `Depends(require_permission(...))`。
2. 业务规则若可复用则放 `app/services/`；所有权用 `services.authz.authorize`。
3. 所有错误用 `ApiError(status, "domain.code", "中文提示", field=...)`。
4. 重新生成契约/类型/文档；补成功与失败路径测试。

### 修改图片编码参数

1. 改 `app/images.py` 的 `PIPELINE_DEFAULTS`，并提升 `PIPELINE_VERSION`。
2. 新上传立即使用新参数；历史图像保持旧产物（URL 不变）。
3. 需要统一时在后台创建 `reencode` 任务（按媒体/相册/全部），任务完成会自动入队 `rerender_content`。
4. 不要为“改质量”新增数据库列或设置项。

### 回滚

- 应用回滚：部署上一个 tag；数据库结构不降级（3.0.0 拒绝降级）。
- 数据回滚：停服 → 用 `scripts/backup.py` 的备份覆盖 `BLOG_DATA_DIR` → `python scripts/db.py verify` → 启动。
- 接入层回滚：由运维按自己的变更流程回滚（应用不依赖特定反向代理实现）。

---

## 13. 编码约定与风险清单

- 错误响应只有一种形状：`{"error": {"code", "message", "field?"}}`；不要新增 `{detail: ...}` 风格的响应。
- 不要用 `assert` 做控制流；不要手写 HTML 拼接或裸 `innerHTML`（用 `dom` 工具/文本节点）。
- 事务只包短数据库临界区；文件、编码、网络、构建等 I/O 放事务外。
- 所有权只通过 `services.authz`；权限只通过 `permissions.can`；不要在路由里复制判断。
- 设置字段只改模型一处；前端类型必须由生成器产生。
- CSS 写在 `src/styles/` 的细粒度文件里（`tokens/` / `base/` / `shared/` / `site/` / `admin/`）；层序由 layout `<head>` 内联声明 + 文件 banner 固定，组件自己 import 自己的样式，单文件硬上限 400 行。字号一律用 `--text-*` 刻度（16 档静态 + 3 个相对档），颜色一律用 `tokens/colors.css` 的语义令牌，`@media` 断点只用 `620/760/900/1080` 四档，`!important` 仅限 reduced-motion 重置。规则与验证命令见 [`CSS.md`](CSS.md)。
- 时间统一 ISO-8601 UTC 字符串（`YYYY-MM-DDTHH:MM:SSZ`）。
- 生成物（`openapi.json`、`types.gen.ts`、`SCHEMA.md`、`API.md`）禁止手改。
- 文档禁止行号引用；API/结构字段由脚本生成。
- 已知风险与缓解见重构方案第 8 节；其中“生产 nginx 与 EDGE 不符”由 staging 核对清单 + `/api/health/edge` 缓解。

---

## 14. 相关文档

- 使用与部署：[`../README.md`](../README.md)
- 接入层：[`EDGE.md`](EDGE.md)
- 数据库结构（生成）：[`SCHEMA.md`](SCHEMA.md)
- API 参考（生成）：[`API.md`](API.md)
- SSG 可行性：[`SSG-FEASIBILITY.md`](SSG-FEASIBILITY.md)
- 重构方案与决策：[`REFACTOR-3.0.0.md`](REFACTOR-3.0.0.md)（历史方案，保留原路径）
- 2.x 历史文档：[`archive/README.md`](archive/README.md)
