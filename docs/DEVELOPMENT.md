# MZTLAB · Scene 开发文档

> 面向后续开发者 / 维护者的工程手册：项目框架、模块职责、数据流、扩展与修改代码的具体路径。
>
> 目标版本：`2.1.0`（`backend/app/config.py` → `VERSION`，`frontend/package.json` → `version`）
> 数据库结构版本：`5`（`backend/app/db.py` → `SCHEMA_VERSION`）
>
> 相关文档：[`README.md`](../README.md) 偏使用说明与功能概览；本文偏实现与二次开发。

---

## 目录

- [0. 快速定位：想改什么，去哪里改](#0-快速定位想改什么去哪里改)
- [1. 项目总览](#1-项目总览)
- [2. 目录结构](#2-目录结构)
- [3. 本地开发环境](#3-本地开发环境)
- [4. 后端框架（FastAPI）](#4-后端框架fastapi)
- [5. 前端框架（Astro）](#5-前端框架astro)
- [6. 数据模型与可见性规则](#6-数据模型与可见性规则)
- [7. API 参考](#7-api-参考)
- [8. 扩展开发指南（从需求到改动的完整路径）](#8-扩展开发指南从需求到改动的完整路径)
- [9. 调试与排错手册](#9-调试与排错手册)
- [10. 测试、构建与部署](#10-测试构建与部署)
- [11. 编码约定与风险清单](#11-编码约定与风险清单)
- [附录 A：文件职责速查表](#附录-a文件职责速查表)
- [附录 B：术语表](#附录-b术语表)

---

## 0. 快速定位：想改什么，去哪里改

| 需求 | 主要改动位置 |
| --- | --- |
| 改首页文案 / 站点名 / 导航 | 后台 → 设置（运行时生效，无需改代码）；默认值在 `backend/app/defaults.py` |
| 改配色、字体、宽度、圆角 | `frontend/src/styles/global.css` 设计令牌；后台 → 外观 可覆盖强调色/宽度/圆角 |
| 改首页结构 | `frontend/src/pages/index.astro` + `frontend/src/components/HomeHero.astro` |
| 改相册页 / 大图浏览 | `frontend/src/pages/galleries/[slug].astro`、`components/GalleryViewer.astro`、`scripts/gallery-viewer.ts` |
| 改文章详情页 | `frontend/src/pages/posts/[slug].astro` |
| 改后台某个页面 | `frontend/src/pages/admin/*.astro` + `frontend/src/scripts/admin-*.ts` |
| 新增/修改 API 接口 | `backend/app/routes/*.py`，挂载点 `backend/app/main.py:73` |
| 新增数据表 / 字段 | `backend/app/db.py`（`SCHEMA`、`_ADDED_COLUMNS`、迁移函数） |
| 新增权限 | `backend/app/permissions.py` + `frontend/src/lib/permissions.ts`（镜像） |
| 改 Markdown 渲染与 HTML 白名单 | `backend/app/content.py` |
| 改上传格式 / 大小限制 | `backend/app/routes/media.py`、`backend/app/config.py`、`.env` |
| 改 EXIF 读取与字段 | `backend/app/exif.py`、`backend/app/photo_exif.py` |
| 改 RSS / sitemap / robots | `frontend/src/pages/rss.xml.ts`、`sitemap.xml.ts`、`robots.txt.ts` |
| 演示数据 | `backend/app/seed.py`（`DEMO_SEED_VERSION` 控制是否重播种） |

---

## 1. 项目总览

### 1.1 技术栈

| 层 | 技术 | 版本来源 |
| --- | --- | --- |
| 页面渲染 | Astro（SSR，`output: 'server'`）+ `@astrojs/node` standalone | `frontend/package.json`（Astro 7 / Node adapter 11） |
| 后台交互 | 原生 TypeScript + `fetch`（无 React/Vue，无 SPA） | `frontend/src/scripts/*.ts` |
| API | FastAPI + Pydantic | `backend/requirements.txt`（fastapi 0.143） |
| 数据库 | SQLite（标准库 `sqlite3`，无 ORM、无迁移框架，WAL 模式） | `backend/app/db.py` |
| Markdown | `markdown` + `bleach` 白名单净化 | `backend/app/content.py` |
| 图片 | Pillow（格式校验、尺寸、EXIF） | `backend/app/routes/media.py`、`exif.py` |
| 认证 | scrypt 密码哈希 + 数据库 Session + HttpOnly Cookie | `backend/app/security.py`、`deps.py` |

设计上刻意保持"少依赖"：**一个 Astro 进程 + 一个 FastAPI 进程 + 一个 SQLite 文件**，没有 Redis、没有任务队列、没有 ORM、没有前端构建框架。

### 1.2 运行时拓扑

```text
浏览器
  │  只访问 4321（同源，Cookie 天然可用，无 CORS）
  ▼
Astro 7 SSR  (127.0.0.1:4321)
  ├── 公共页面：/ /photos /galleries/{slug} /archive /posts/{slug} /search /{slug}
  ├── 后台页面：/admin /admin/posts /admin/galleries /admin/media /admin/comments
  │            /admin/taxonomy /admin/appearance /admin/users /admin/settings
  ├── 服务端取数：lib/api.ts → apiServer() → http://127.0.0.1:8000
  ├── /api/*  代理：pages/api/[...path].ts → lib/proxy.ts
  ├── /media/* 代理：pages/media/[...path].ts → lib/proxy.ts
  └── 生成：/rss.xml /sitemap.xml /robots.txt
          │
          ▼
FastAPI  (127.0.0.1:8000，由 Astro 通过 BLOG_API_INTERNAL_URL 访问)
  ├── /api/auth /api/site /api/posts …（公共读）
  ├── /api/admin/*（需登录 + 权限键 + 所有权）
  ├── /media/*（StaticFiles 直接托管上传目录）
  └── SQLite: backend/data/blog.db  +  uploads: backend/data/uploads/YYYY/MM/*.jpg
```

关键点：

- **浏览器只认识 4321**。`/api`、`/media` 都由 Astro 代理转发（`frontend/src/lib/proxy.ts:24`），因此 Cookie 是第一方 Cookie、无需 CORS、生产环境只暴露一个端口。
- **公共页面在服务端取数**（Astro frontmatter 里 `await getSite()` / `apiServer()`）；只有后台页面内的交互通过浏览器 `fetch` 调 `/api`。
- **FastAPI 不应直接暴露到公网**：只监听 `127.0.0.1`（或容器内网），且必须用 `uvicorn --no-proxy-headers` 启动，否则客户端伪造 `X-Forwarded-For` 就能改写来源 IP、绕过登录限速。后端只接受携带 `BLOG_PROXY_SECRET` 的请求所附带的 `x-blog-real-ip`（`backend/app/deps.py:22`），CSRF 由 `x-blog-request` 头防护。

### 1.3 一个请求的完整链路（两类）

**A. 公共页面（服务端渲染）**

```text
GET /posts/hello
  → Astro 页面 frontmatter
      getSite()        → GET http://127.0.0.1:8000/api/site
      getPost(slug)    → GET http://127.0.0.1:8000/api/posts/hello
  → 后端 serialize_post() 拼 JSON（content_html、toc、prev/next/related）
  → Astro 输出 HTML（BaseLayout 注入 --accent / --layout-width / data-palette 等）
  → 浏览器执行页面内联 <script>（阅读进度、复制、浏览量、TOC 高亮…）
```

**B. 后台写操作（浏览器）**

```text
点击"保存"
  → scripts/admin-*.ts 调用 lib/api.ts 的 api()
      fetch('/api/admin/posts/12', { method:'PUT', headers:{ 'x-blog-request':'1' }, credentials:'same-origin' })
  → Astro /api/[...path] 代理（转发 Cookie、覆盖写 x-blog-real-ip 与 x-blog-proxy-secret）
  → FastAPI 中间件校验 x-blog-request（main.py:49，缺失返回 403）
  → require_staff / require_permission / owns 逐层校验
  → Pydantic schema 校验 → SQL 写库 → 返回 JSON
  → 前端 toast 提示 / 局部重渲染
```

### 1.4 三条必须遵守的架构约束

1. **公开可见性只由后端 SQL 条件决定**：`posts.PUBLIC_CONDITION`、`galleries.PHOTO_PUBLIC_CONDITION`（见 6.3）。前端不要自行过滤敏感数据，也不要给公开接口加"顺便返回草稿"的开关。
2. **权限判断在服务端**：前端 `lib/permissions.ts` 只用于隐藏导航/按钮，真正的边界在 `backend/app/deps.py` 与各路由的 `_ensure_owner`。
3. **SQLite 单进程假设**：限流器 `RateLimiter` 是进程内内存实现（`security.py`），若改成多 worker，需改用 Redis 或反向代理限流。

---

## 2. 目录结构

```text
blog/
├── README.md                 使用说明（功能、主题、工作流）
├── docs/                     截图 + 本开发文档
├── .env / .env.example       环境变量（根目录 .env 优先生效，backend/.env 可覆盖）
├── docker-compose.yml        双容器编排（backend + frontend）
├── start.ps1 / start.sh      包装 scripts/run.py 的快捷脚本
├── scripts/
│   ├── setup.py              一键创建 venv、装 pip / npm 依赖
│   └── run.py                同时启动 FastAPI 与 Astro（--dev / --reload / --open）
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py           FastAPI 入口：lifespan、CSRF 中间件、安全响应头、路由挂载、/media 静态
│   │   ├── config.py         环境变量 → 常量；数据目录创建
│   │   ├── db.py             sqlite3 连接、SCHEMA、迁移、settings 读写
│   │   ├── defaults.py       默认设置值 + 公开/私有设置键 + 主题枚举 + 历史默认值（迁移用）
│   │   ├── security.py       scrypt 哈希、Session Token、时间函数、内存限流
│   │   ├── deps.py           请求上下文用户、权限依赖、Cookie 会话
│   │   ├── permissions.py    权限键、角色矩阵、effective_permissions、owns
│   │   ├── schemas.py        Pydantic 请求模型（全部写入入口的校验层）
│   │   ├── content.py        Markdown → HTML + bleach 白名单、slug、摘要、阅读时长、TOC
│   │   ├── posts.py          文章/页面查询与 JSON 序列化
│   │   ├── galleries.py      相册/照片查询与 JSON 序列化（含 EXIF 公开白名单）
│   │   ├── exif.py           读 EXIF、JSON 安全化、缓存写入
│   │   ├── photo_exif.py     每张照片可公开的 EXIF 字段白名单
│   │   ├── seed.py           首次演示内容（3 相册 + 3 文章 + 关于页）、bootstrap 管理员
│   │   └── routes/
│   │       ├── auth.py           /api/auth/*、/api/setup
│   │       ├── public.py         公共读接口、搜索、评论、浏览量
│   │       ├── admin.py          后台：统计、文章/页面、版本、预览、评论、分类标签、设置、外观、个人资料、导出
│   │       ├── gallery_admin.py  后台：相册 CRUD、照片增删改、排序
│   │       ├── media.py          后台：上传、媒体列表、EXIF 编辑、删除
│   │       └── users.py          后台：成员与角色
│   ├── data/                 运行时数据（gitignored）：blog.db、uploads/
│   └── tests/                unittest：content / exif / galleries / permissions
└── frontend/
    ├── astro.config.mjs      output: server、node adapter、端口、开发期 CJS 桥接插件
    ├── package.json          dev / build / check / preview / start
    ├── public/favicon.svg
    └── src/
        ├── config.ts         少量代码内常量 + fallbackSite（后端不可达时的兜底）
        ├── types.ts          与后端 JSON 对齐的 TypeScript 类型
        ├── layouts/          BaseLayout（公共）/ AdminLayout（后台）/ AuthLayout（登录/初始化）
        ├── components/       公共组件 + components/admin/（PostEditor、AudioEmbedDialog）
        ├── pages/            路由；pages/api、pages/media 为代理 catch-all
        ├── scripts/          后台与交互脚本（原生 TS，按页面一个文件）
        ├── lib/              api / auth / permissions / format / photo / proxy / audio-embed / admin-client
        └── styles/           global.css（设计系统）、mono.css（Mono 层）、admin.css（后台）
```

---

## 3. 本地开发环境

### 3.1 版本要求

| 依赖 | 最低版本 | 说明 |
| --- | --- | --- |
| Python | 3.11 | `scripts/setup.py:81` 校验 |
| Node.js | 22.22 | Astro 7 要求（`scripts/setup.py:37`、`frontend/package.json` engines） |
| npm | 随 Node | 使用 `npm ci`（有 lock 文件时） |

### 3.2 安装与启动

```bash
# 一次性安装（创建 backend/.venv、pip install、npm ci）
python scripts/setup.py

# 开发模式：Astro dev（HMR）+ uvicorn
python scripts/run.py --dev

# 生产模式：先 npm run build，再 node dist/server/entry.mjs + uvicorn
python scripts/run.py
```

Windows 快捷方式：`.\start.ps1 -Dev` / `.\start.ps1`；macOS / Linux：`./start.sh --dev`。

打开：

| 地址 | 说明 |
| --- | --- |
| <http://127.0.0.1:4321> | 站点 |
| <http://127.0.0.1:4321/admin> | 后台（首次跳 `/admin/setup` 创建管理员） |
| `/api/docs` / `/api/openapi.json` | **默认关闭**；开发时设 `BLOG_ENABLE_API_DOCS=true` 后可用（经 Astro 代理） |

**只启动一半也可以调试**：

```bash
# 仅后端（在 backend/ 下）
.venv/Scripts/python -m uvicorn app.main:app --reload --no-proxy-headers --port 8000

# 仅前端
cd frontend && npm run dev
```

此时若后端不可达，页面会显示"内容服务离线"（`index.astro`）或使用 `fallbackSite` 兜底，`/api` 代理返回 502 + `后端服务暂时不可用`。

### 3.3 环境变量

由 `backend/app/config.py` 读取；`scripts/run.py:29` 也会把根目录 `.env` 注入子进程。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `BLOG_DATA_DIR` | `backend/data` | SQLite 与上传根目录 |
| `BLOG_DB_PATH` | `$DATA_DIR/blog.db` | 数据库路径 |
| `BLOG_UPLOAD_DIR` | `$DATA_DIR/uploads` | 媒体文件根目录 |
| `BLOG_FRONTEND_URL` | `http://127.0.0.1:4321` | 前端地址（后端日志/跳转用） |
| `BLOG_SITE_URL` | 空 | 首启动写入 `site_url` 设置（canonical/RSS/sitemap） |
| `BLOG_SESSION_COOKIE` | `mztlab_session` | Cookie 名 |
| `BLOG_SESSION_DAYS` | `7` | 会话有效期 |
| `BLOG_COOKIE_SECURE` | 按 `BLOG_SITE_URL` 是否 HTTPS 自动判断 | 生产 HTTPS 下应保持 `true` |
| `BLOG_PROXY_SECRET` | 空 | 前后端共享的代理密钥；只有带此密钥的请求才信任 `x-blog-real-ip`。`scripts/run.py` 每次运行随机生成，Docker 需在两端设置同一值 |
| `BLOG_ENABLE_API_DOCS` | `false` | 是否公开 `/api/docs` 与 `/api/openapi.json` |
| `BLOG_ADMIN_USER` / `BLOG_ADMIN_PASSWORD` | 空 | 首启动自动建管理员（二者都填且无用户时） |
| `BLOG_ADMIN_NAME` | `MZTLAB` | 自动创建管理员的显示名 |
| `BLOG_SEED_DEMO` | `true` | 是否播种演示内容 |
| `BLOG_MAX_UPLOAD_MB` | `12` | 上传大小上限 |
| `BLOG_CORS_ORIGINS` | 空 | 仅跨源直连 API 时需要 |
| `BLOG_API_INTERNAL_URL` | `http://127.0.0.1:8000` | **前端**访问后端的地址（`frontend/src/lib/api.ts:15`、`proxy.ts:3`） |
| `HOST` / `PORT` | `127.0.0.1` / `4321` | Astro 监听地址 |
| `BLOG_BACKEND_PORT` / `BLOG_FRONTEND_PORT` | `8000` / `4321` | **仅** `scripts/run.py` 使用 |

### 3.4 Docker

```bash
export BLOG_PROXY_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
docker compose up --build
# frontend: http://localhost:4321   backend 仅容器内网络暴露 8000
```

`BLOG_PROXY_SECRET` 是必填项（compose 会拒绝空值）：前后端必须使用同一个随机值，否则后端不信任代理写入的客户端 IP。

- `backend/Dockerfile`：`python:3.13-slim`，`BLOG_DATA_DIR=/app/data`，数据挂在 `blog_data` volume。
- `frontend/Dockerfile`：多阶段构建，产物为 `dist/` + 生产依赖，`node dist/server/entry.mjs`。
- compose 中 frontend 通过 `BLOG_API_INTERNAL_URL=http://backend:8000` 访问后端；`depends_on` 等后端健康检查通过。

### 3.5 数据目录与重置

```text
backend/data/
├── blog.db          SQLite（WAL 模式，可能有 blog.db-wal / -shm）
└── uploads/
    ├── seed/        演示内容生成的图片
    └── 2026/05/     真实上传：年/月/uuid.ext
```

备份 = 复制整个 `backend/data`。重置演示站点 = 停止服务后删除 `backend/data`（注意会丢内容）。

---

## 4. 后端框架（FastAPI）

### 4.1 入口与中间件（`backend/app/main.py`）

```python
app = FastAPI(
    ...,
    docs_url="/api/docs" if ENABLE_API_DOCS else None,
    openapi_url="/api/openapi.json" if ENABLE_API_DOCS else None,
)
```

- `lifespan`（`main.py`）：启动时 `init_db()`（建表 + 迁移 + 播种 + bootstrap 管理员）与 `clear_expired_sessions()`。
- `protect_admin_and_add_headers`（`main.py`）：
  - **CSRF 防护**：`/api/admin` 下的 POST/PUT/PATCH/DELETE 必须带 `x-blog-request: 1`，否则 403。
  - 追加安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`、`Cross-Origin-Resource-Policy`；`/api/*` 一律 `Cache-Control: no-store`。
- **异常处理**：参数校验错误统一返回 `{"detail": "中文消息"}`；超大整数 / SQLite 溢出返回 400/422；其余未处理异常记日志后返回统一 500 JSON，不泄露堆栈与路径。
- 路由挂载：所有 router 都加 `prefix="/api"`；各 router 自己再带 `prefix="/admin"` 或 `tags`。
- `/media` 用 `StaticFiles(directory=UPLOAD_DIR, check_dir=False)` 直接托管——文件名随机 + 上传已校验，故可公开；生产中由 Astro 代理。

### 4.2 配置（`backend/app/config.py`）

全部配置来自环境变量，模块导入时求值并 `mkdir` 数据目录。新增配置项的规范做法：

```python
# config.py
NEW_FLAG = os.getenv("BLOG_NEW_FLAG", "false").lower() in {"1", "true", "yes", "on"}
```

同步更新 `.env.example`（必须），否则部署者不知道有这个开关。

> 注意：`load_dotenv(ROOT/.env)` 后被 `load_dotenv(BASE_DIR/.env, override=True)` 覆盖，即 `backend/.env` 优先级更高。

### 4.3 数据库层（`backend/app/db.py`）

**连接模型**：每个请求/操作 `with db() as conn` 打开短连接，自动 commit / rollback / close。`connect()` 设置：

```python
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = 5000
PRAGMA journal_mode = WAL
```

**表结构**（`SCHEMA`，`db.py:22`）：

| 表 | 用途 | 关键列 |
| --- | --- | --- |
| `users` | 成员 | `username`(unique)、`password_hash`、`role`、`is_active` |
| `sessions` | 会话 | `token_hash`(unique，只存 SHA-256)、`expires_at` |
| `posts` | 文章 + 页面 | `type`('post'/'page')、`slug`(unique)、`content_md`、`content_html`、`status`、`published_at`、`author_id` |
| `categories` / `tags` | 分类 / 标签 | `slug`(unique) |
| `post_categories` / `post_tags` | 多对多 | 复合主键 |
| `comments` | 评论 | `status`('pending'/'approved'/'spam')、`post_id` |
| `media` | 媒体库 | `filename`(相对路径)、`mime`、`width/height`、`owner_id`、`uploaded_by`(历史)、`exif`(JSON 文本) |
| `galleries` | 相册 | `slug`(unique)、`status`、`featured`、`cover_photo_id`、`author_id` |
| `photos` | 相册内照片 | `gallery_id`、`media_id`、`filename`(快照)、`sort_order`、`exif_fields`(公开白名单) |
| `revisions` | 文章历史版本 | `post_id`、`content_md` |
| `settings` | 键值设置 | `key`(PK)、`value`(JSON 文本) |

**迁移机制**（无 Alembic，靠 `PRAGMA user_version`）：

1. `SCHEMA_VERSION = 5`（`db.py:20`）。
2. `init_db()`：读旧版本 → `executescript(SCHEMA)`（`CREATE TABLE IF NOT EXISTS` 不改已有表）→ `_ensure_columns` → 条件回填 → 默认设置 → 场景迁移 → 写回版本号 → 播种。
3. 加列走 `_ADDED_COLUMNS`（`db.py:253`）：

```python
_ADDED_COLUMNS = {
    "posts": {"new_column": "TEXT NOT NULL DEFAULT ''"},
}
```

`_ensure_columns` 会 `PRAGMA table_info` 检查后 `ALTER TABLE ... ADD COLUMN`，因此**幂等**，每次启动都安全。

4. 数据迁移函数（`_backfill_owners`、`_backfill_media_exif`、`_migrate_scene`、`_migrate_mono`）只做一次性修补，通过 `user_version` 或值比较决定是否执行；风格是"只在值仍等于旧默认值时才覆盖"，避免抹掉用户手写内容。

**settings 读写**：

| 函数 | 说明 |
| --- | --- |
| `load_settings()` | 默认值 + 数据库覆盖，返回全部键（含私有键） |
| `public_settings()` | 过滤掉 `PRIVATE_SETTING_KEYS`（目前只有 `editor_manage_others`） |
| `save_settings(patch)` | upsert，key 长度 ≤ 80 |
| `setting_flag(conn, key, default)` | 在已有连接内读布尔设置 |

### 4.4 认证与会话（`security.py` + `deps.py`）

- **密码**：`hash_password` 生成 `scrypt$N$r$p$salt$digest`（`security.py`），`verify_password` 拆参数重算 + `hmac.compare_digest`。改哈希参数时旧密码仍可验证（参数已编码在字符串里）。
- **密码策略**：`password_policy_error()` 要求 ≥ 10 位、大小写字母/数字/符号至少三类、拒绝常见弱口令（含 `admin123`/`user1234` 这类常见词+数字）以及包含用户名的密码；初始化、建成员、改密、个人资料修改都会校验。
- **会话**：登录生成 `secrets.token_urlsafe(40)`，DB 只存 `sha256(token)`；Cookie 为 `HttpOnly + SameSite=Lax + path=/`，`Secure` 由 `BLOG_COOKIE_SECURE` 控制（未显式设置时按 `BLOG_SITE_URL` 是否 HTTPS 自动判断）。默认有效期 7 天；改密/停用/改角色会吊销该用户全部会话。
- **当前用户**：`get_session_user(request)` 每次请求查 `sessions JOIN users`，并**实时计算权限列表**（`user_public`）——所以后台改 `editor_manage_others` 后无需重新登录。
- **依赖项**（写新路由时直接用）：

| 依赖 | 行为 |
| --- | --- |
| `require_staff(request)` | 未登录 401；不是 staff（无 `content.read`）403 |
| `require_admin` | `require_staff` 的兼容别名 |
| `require_permission("x.y")` | staff + 指定权限键，返回 user dict |
| `require_any_permission("a","b")` | 任一满足即可 |

- **限流**：登录同时按 IP（30 次 / 5 分钟）、`IP+账号`（6 次 / 5 分钟）、账号（60 次 / 15 分钟）三层计数，只统计失败并在成功后清零；重复失败带指数退避延迟并写警告日志。`comment_limiter` 为 5 次 / 10 分钟 / IP，内存实现。来源 IP 仅在代理密钥匹配时取自 `x-blog-real-ip`，否则用 TCP 对端地址。

### 4.5 权限模型（`permissions.py`）

**权限键**（`PERMISSIONS`，`permissions.py:24`）：
`content.read` / `content.write` / `content.publish` / `content.delete` / `content.others` / `media.manage` / `gallery.manage` / `comment.moderate` / `taxonomy.manage` / `settings.manage` / `users.manage` / `data.export`

**角色矩阵**（`ROLE_PERMISSIONS`，`permissions.py:53`）：

| 权限 | admin | editor | author |
| --- | --- | --- | --- |
| `content.read` | ✅ | ✅ | ✅ |
| `content.write` | ✅ | ✅ | ✅ |
| `content.publish` | ✅ | ✅ | ✅ |
| `content.delete` | ✅ | ✅ | ❌ |
| `content.others` | ✅ | 条件* | ❌ |
| `media.manage` | ✅ | ✅ | ✅ |
| `gallery.manage` | ✅ | ✅ | ✅ |
| `comment.moderate` | ✅ | ✅ | ❌ |
| `taxonomy.manage` | ✅ | ✅ | ❌ |
| `settings.manage` | ✅ | ❌ | ❌ |
| `users.manage` | ✅ | ❌ | ❌ |
| `data.export` | ✅ | ✅ | ❌ |

\* `content.others` 不是静态授予：由 `effective_permissions(role, manage_others=setting)` 决定，`setting` 即设置项 `editor_manage_others`（默认 false）。

**所有权**：`owns(user, item)` 依次尝试 `author_id` / `owner_id` / `uploaded_by`，任一命中且等于当前用户即视为拥有。所有"编辑他人内容"的入口都写成：

```python
if can(user, "content.others") or owns(user, row):
    ...
```

### 4.6 内容管线（`content.py`）

`render_markdown(text)`（`content.py:55`）：

```text
Markdown 文本
  → markdown.Markdown(extensions=["extra","sane_lists","smarty","toc","codehilite","nl2br"])
  → bleach.clean(tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
                  protocols={"http","https","mailto"}, strip=True)
  → 给外链补 rel="noopener noreferrer" target="_blank"
  → 存入 posts.content_html（写库时渲染，读时不再渲染）
```

- 新增可用的 HTML 标签/属性 → 只改 `ALLOWED_TAGS` / `ALLOWED_ATTRIBUTES` / `ALLOWED_PROTOCOLS`（`content.py:17`）。
- 新增 Markdown 扩展 → 改 `MD_EXTENSIONS`（`content.py:41`）+ `MD_CONFIG`，并检查产出标签是否在白名单内。
- 其他工具：`slugify`（支持中文，URL 用 `quote_slug` 编码）、`make_excerpt`、`reading_time`（CJK 400 字/分 + 英文 220 词/分）、`extract_toc`（解析 h2/h3）、`normalize_iso_datetime`（浏览器 `datetime-local` / ISO8601 → UTC `...Z`）。

> **重要**：`content_html` 是"写入时物化"的。若修改管线（白名单、扩展），历史文章不会自动重渲染。需要一次性重算时，写一个临时脚本遍历 `posts` 调 `render_markdown(content_md)` 更新 `content_html`。

### 4.7 查询与序列化层（`posts.py` / `galleries.py`）

这两个模块是"公开 API 的真相来源"，**不要在路由里手写序列化**。

`posts.py`：

| 函数 | 作用 |
| --- | --- |
| `PUBLIC_CONDITION` | 公开文章条件：`status IN ('published','scheduled') AND published_at <= now` |
| `fetch_posts(...)` | 列表查询（分页、tag/category/q/featured/author/status、admin 模式） |
| `get_post(...)` | 单条（可按 id/slug/type/public） |
| `serialize_post(conn, row, detail=, admin=)` | 单条 JSON；`detail` 含 `content_html` + `toc`，`admin` 含 `content_md/raw_status/author_id` |
| `serialize_posts(conn, rows, admin=)` | 列表 JSON（一次批量查 taxonomy，避免 N+1） |
| `effective_status` | `scheduled` 且已到时间 → 对外显示 `published`（**没有后台定时任务，靠查询时判断**） |
| `adjacent_posts` / `related_posts` | 上一篇/下一篇、相关文章 |
| `pagination(page, per_page, total)` | 统一分页字段 |

`galleries.py`：

| 函数 | 作用 |
| --- | --- |
| `GALLERY_PUBLIC_CONDITION` | `g.status = 'published'` |
| `PHOTO_PUBLIC_CONDITION` | 照片必须 `status='published'` **且**属于已发布相册 |
| `photo_dict(row)` | 单张照片 JSON：URL、宽高比、EXIF（按 `exif_fields` 白名单过滤） |
| `gallery_dict(conn, row, detail=, admin=)` | 相册 JSON；`detail` 带 `photos` 数组；封面取 `cover_photo_id`，缺失回退第一张 |
| `fetch_galleries` / `get_gallery` / `fetch_photos` / `gallery_photo_rows` | 查询 |
| `public_counts(conn)` | 公开照片数 / 相册数 |
| `next_photo_order` / `touch_gallery` | 排序步长 10；改动照片后刷新相册 `updated_at` |

EXIF 合并规则（`galleries.py:64` 起）：`media.exif` 是权威来源，`photos.camera/lens/taken_at` 只是快照兜底；公开字段再由 `photos.exif_fields` 二次过滤（`taken_at_raw` 跟随 `taken_at`，`focal_length_35mm` 跟随 `focal_length`）。

### 4.8 EXIF（`exif.py` / `photo_exif.py`）

- 读取：Pillow `image.getexif()` + `IFD.Exif` + `IFD.GPSInfo`，产出规范化字段 `camera/lens/taken_at/taken_at_raw/exposure/aperture/iso/focal_length/focal_length_35mm/orientation/software/artist/copyright/gps/raw`。
- JSON 安全化：有理数、元组、bytes、嵌套 dict 都会被转换成 JSON 可存的值；`raw` 最多 80 键，跳过 MakerNote/缩略图等二进制标签。
- 存储：JSON 文本写 `media.exif`；老数据在 `GET /api/admin/media/{id}/exif` 时按需读文件并回填。
- **永不改写原图**：EXIF 编辑只更新数据库（`routes/media.py:242`），且已存在的字段不允许改值（只能补空字段），冲突返回 409。
- 公开白名单：`photo_exif.EXIF_FIELDS = (camera, lens, focal_length, aperture, exposure, iso, taken_at, dimensions)`。

### 4.9 校验模型（`schemas.py`）

所有写接口的 body 都是 Pydantic 模型（`StrippedModel`：去首尾空白、忽略多余字段）。常见约束：

| 模型 | 用途 | 关键限制 |
| --- | --- | --- |
| `SetupIn` | 初始化管理员 | 用户名 3–32、密码满足强度策略（≥ 10 位 + 三类字符） |
| `LoginIn` | 登录 | — |
| `PostIn` | 文章/页面 | 标题 ≤ 200、正文 ≤ 500k、tags ≤ 20、categories ≤ 6；`scheduled` 必须有 `published_at` |
| `CommentIn` | 评论 | 内容 ≤ 3000，`website` 是蜜罐字段 |
| `GalleryIn` / `PhotoIn` / `PhotoUpdateIn` / `PhotoBatchIn` / `ReorderIn` | 相册与照片 | 状态枚举、EXIF 字段白名单、日期格式 `YYYY-MM(-DD)` |
| `MediaExifIn` / `MediaAltIn` | 媒体 | ISO ≤ 409600、焦距 ≤ 2000 |
| `AppearanceIn` | 外观 | 主题/明暗/字体/布局枚举、accent `#RRGGBB`、宽度 720–1600、圆角 0–40 |
| `UserCreateIn` / `UserUpdateIn` / `ProfileIn` | 成员 | 角色枚举、密码强度策略、改密需旧密码 |

新增字段时，**先把校验写进 schema**，再改路由与序列化——这样错误信息（422）由 Pydantic 统一产出。

### 4.10 路由清单

**`routes/auth.py`**（无前缀，挂在 `/api`）

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/auth/status` | — | 是否登录、当前用户、是否需要初始化 |
| POST | `/api/setup` | 仅当用户数为 0 | 创建管理员并直接登录 |
| POST | `/api/auth/login` | 限流 | 登录 |
| POST | `/api/auth/logout` | — | 删除会话并清 Cookie |
| GET | `/api/auth/me` | staff | 当前用户 |

**`routes/public.py`**（无前缀）—— 公共读，全部无需登录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（仅 `ok` + 时间，不返回版本） |
| GET | `/api/site` | 公开设置、分类、标签、计数 |
| GET | `/api/posts` | 文章列表（`page/per_page/tag/category/q/featured`） |
| GET | `/api/posts/{slug}` | 文章详情（含 toc/prev/next/related、评论开关） |
| GET | `/api/pages` / `/api/pages/{slug}` | 独立页面 |
| GET | `/api/archive` | 归档（按年分组计数） |
| GET | `/api/galleries` | 已发布相册列表 |
| GET | `/api/galleries/{slug}` | 相册详情 + 照片 + 相关相册 |
| POST | `/api/galleries/{id}/view` | 相册浏览量 +1 |
| GET | `/api/search?q=` | 文章 + 相册 |
| GET | `/api/taxonomy` | 分类与标签 |
| GET | `/api/comments?post_id=` | 已通过评论 |
| POST | `/api/posts/{id}/comments` | 提交评论（限流 + 蜜罐 + 审核开关） |
| POST | `/api/posts/{id}/view` | 文章浏览量 +1 |

**`routes/admin.py`**（`prefix="/admin"`，router 级 `require_staff`）

| 方法 | 路径 | 额外权限 | 行号 |
| --- | --- | --- | --- |
| GET | `/api/admin/stats` | staff | 214 |
| GET | `/api/admin/posts` | staff（作者仅自己） | 301 |
| GET | `/api/admin/posts/{id}` | staff + 所有权 | 329 |
| POST | `/api/admin/posts?type=post\|page` | `content.write`（非草稿还需 `content.publish`） | 347 |
| PUT | `/api/admin/posts/{id}` | `content.write` + 所有权 | 381 |
| DELETE | `/api/admin/posts/{id}` | `content.delete` + 所有权 | 423 |
| GET | `/api/admin/posts/{id}/revisions` | staff + 所有权 | 438 |
| POST | `/api/admin/posts/{id}/revisions/{rid}/restore` | `content.write` | 463 |
| POST | `/api/admin/preview` | `content.write` | 498 |
| GET | `/api/admin/comments` | `comment.moderate` | 510 |
| PUT | `/api/admin/comments/{id}` | `comment.moderate` | 555 |
| DELETE | `/api/admin/comments/{id}` | `comment.moderate` | 571 |
| GET | `/api/admin/taxonomy` | staff | 586 |
| POST/PUT/DELETE | `/api/admin/taxonomy/{kind}[/{id}]` | `taxonomy.manage` | 614/641/673 |
| GET | `/api/admin/settings` | `settings.manage` | 691 |
| PUT | `/api/admin/settings` | `settings.manage` | 733 |
| PUT | `/api/admin/appearance` | `settings.manage` | 813 |
| GET/PUT | `/api/admin/profile` | staff | 822/827 |
| GET | `/api/admin/export` | `data.export` | 862 |

**`routes/gallery_admin.py`**（`prefix="/admin"`）

| 方法 | 路径 | 权限 | 行号 |
| --- | --- | --- | --- |
| GET | `/api/admin/galleries` | staff（受限者仅自己） | 101 |
| GET | `/api/admin/galleries/{id}` | staff + 所有权 | 138 |
| POST | `/api/admin/galleries` | `gallery.manage` | 149 |
| PUT | `/api/admin/galleries/{id}` | `gallery.manage` + 所有权 | 178 |
| DELETE | `/api/admin/galleries/{id}` | `gallery.manage` + 所有权 | 216 |
| POST | `/api/admin/galleries/{id}/photos` | `gallery.manage` | 229 |
| POST | `/api/admin/galleries/{id}/reorder` | `gallery.manage` | 286 |
| GET | `/api/admin/photos` | staff | 314 |
| POST | `/api/admin/photos` | `gallery.manage` | 338 |
| PUT | `/api/admin/photos/{id}` | `gallery.manage` + 所有权 | 388 |
| DELETE | `/api/admin/photos/{id}` | `gallery.manage` + 所有权 | 428 |

**`routes/media.py`**（`prefix="/admin"`）

| 方法 | 路径 | 权限 | 行号 |
| --- | --- | --- | --- |
| GET | `/api/admin/media` | staff（无 `content.others` 只见自己） | 115 |
| POST | `/api/admin/media` | `media.manage` | 151 |
| GET | `/api/admin/media/{id}` | staff + 所有权 | 232 |
| PUT | `/api/admin/media/{id}/exif` | `media.manage` + 所有权 | 242 |
| GET | `/api/admin/media/{id}/exif` | staff + 所有权 | 306 |
| PUT | `/api/admin/media/{id}` | `media.manage` + 所有权 | 335 |
| DELETE | `/api/admin/media/{id}` | `media.manage` + 所有权 | 351 |

**`routes/users.py`**（`prefix="/admin"`）

| 方法 | 路径 | 权限 | 行号 |
| --- | --- | --- | --- |
| GET | `/api/admin/users/meta` | `users.manage` | 68 |
| GET | `/api/admin/users` | `users.manage` | 77 |
| POST | `/api/admin/users` | `users.manage` | 144 |
| PUT | `/api/admin/users/{id}` | `users.manage` | 176 |
| DELETE | `/api/admin/users/{id}` | `users.manage` | 225 |

### 4.11 上传与媒体（`routes/media.py`）

允许的类型（`FORMAT_EXTENSIONS` / `AUDIO_EXTENSIONS`）：

| 类型 | 扩展名 | MIME | 校验方式 |
| --- | --- | --- | --- |
| 图片 | jpg/png/webp/gif | image/* | Pillow `verify()` + 尺寸 ≤ 4800 万像素 |
| 音频 | mp3/m4a/ogg/oga/wav/flac | audio/* | 扩展名 + 魔数（`_audio_format`） |

流程（`upload_media`，`media.py:151`）：

```text
读取 ≤ MAX_UPLOAD_BYTES+1 → 判图片（Pillow）→ 否则判音频 → 落盘 uploads/YYYY/MM/{uuid}.{ext}
→ 读 EXIF（仅图片）→ INSERT media（含 owner_id、exif JSON）→ 返回 _serialize(row)
```

安全细节：

- `_file_path()` 做 `resolve()` + `is_relative_to(UPLOAD_DIR)`，防路径穿越。
- 删除媒体只删文件 + 行；`photos.media_id` 是 `ON DELETE CASCADE`，但 `photos.filename` 快照保留，相册仍可读。
- 授权：`_ensure_owner` = `content.others` 或本人上传。

### 4.12 默认值与种子（`defaults.py` / `seed.py`）

- `DEFAULT_SETTINGS`（`defaults.py:14`）是设置项的**唯一真相**：`update_settings` 只接受这里存在的键（`admin.py:740`），`public_settings()` 也只返回这里的键。
- `PRIVATE_SETTING_KEYS = {"editor_manage_others"}`：存库但不通过 `/api/site` 与导出泄露。
- `seed_demo_content()`（`seed.py:438`）：用 `settings.demo_seed_version` 标记幂等；首次插入分类/标签/3 篇文章/关于页/3 个相册（Pillow 程序生成色块图，写入 `uploads/seed/`）与示例评论。
- `ensure_bootstrap_admin()`（`seed.py:527`）：`BLOG_ADMIN_USER` + `BLOG_ADMIN_PASSWORD` 且无用户时创建管理员。
- 演示内容只写一次；`BLOG_SEED_DEMO=false` 可空站启动。

---

## 5. 前端框架（Astro）

### 5.1 配置（`frontend/astro.config.mjs`）

```js
output: 'server'                     // SSR，无预渲染
adapter: node({ mode: 'standalone' }) // 产物 dist/server/entry.mjs
server: { host: HOST || '127.0.0.1', port: PORT || 4321 }
build: { sourcemap: false }          // 生产不输出源码映射
vite.server.fs: { strict: true, deny: ['.env', '*.pem', '**/.git/**'] }
vite.plugins: [cjsBridgePlugin, blockSensitiveDevFiles]
```

**关于开发服务器**：`astro dev` 会提供 `/src/*`、`/@vite/client` 等源码入口，**只能在本机开发时使用，不能对外**。生产必须 `npm run build` 后用 `node dist/server/entry.mjs`（`scripts/run.py` 默认即此模式，`--dev` 会打印警告）。额外插件会拦截 `/package.json`、`/astro.config.mjs`、`/tsconfig.json`、`.env` 等配置文件的 dev 请求。

**关于 `cjsBridgePlugin`**：Astro 7 / Vite 8 的 dev SSR 会用内联方式执行部分 CommonJS 依赖，导致 `require` 不可用。`lib/picomatch-esm.mjs`、`lib/yaml-esm.mjs`、`lib/eventemitter3-esm.mjs` 是三个极小的包装文件，把包映射到 `createRequire` 版本。**只在开发期生效，生产打包用真包**；不要删这三个文件。

### 5.2 路由与代理

| 文件 | 行为 |
| --- | --- |
| `pages/api/[...path].ts` | `ALL → forwardToApi(context, '/api')` |
| `pages/media/[...path].ts` | `ALL → forwardToApi(context, '/media')` |

`src/middleware.ts` 对每个响应统一追加安全头：`Content-Security-Policy`（仅生产构建；开发期由 Vite HMR 需要内联/eval）、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`、`Cross-Origin-Opener-Policy`；请求经 HTTPS（含 `x-forwarded-proto: https`）时再追加 HSTS。

`lib/proxy.ts:24` 做的事：

1. 拼接 `BLOG_API_INTERNAL_URL + 前缀 + path + query`；
2. 复制请求头，删除 `host/content-length/connection` 与客户端可能伪造的 `forwarded/x-forwarded-for/x-real-ip/x-blog-real-ip`，再写入可信的 `x-blog-real-ip` 与 `x-blog-proxy-secret`（供后端限流/审计）；
3. 非 GET/HEAD 时读取 `arrayBuffer()` 转发 body，`redirect: 'manual'`，20s 超时；
4. 过滤 hop-by-hop 头；删除 `content-encoding/content-length`（Node fetch 已解压）；用 `getSetCookie()` 逐条转发 Set-Cookie；
5. fetch 抛错 → 返回 502 JSON：`后端服务暂时不可用，请确认 FastAPI 已启动`。

### 5.3 lib 层

| 文件 | 关键导出 | 说明 |
| --- | --- | --- |
| `lib/api.ts` | `apiServer<T>()`、`api<T>()`、`getSite()`、`getPost()`、`getPage()`、`ApiError`、`qs()`、`clearSiteCache()` | `apiServer` 只在服务端用（带 Cookie 透传、默认带 `x-blog-request`、12s 超时）；`api` 是浏览器客户端（同源 Cookie、401 自动跳登录）；`getSite()` 有 1 秒内存缓存 + 并发去重 |
| `lib/auth.ts` | `guardAdmin(astro, permission?)` | 页面级守卫：未登录 → `/admin/login?next=`；无权限 → `/admin?denied=`；返回 user 或 Response（调用方 `if (guard instanceof Response) return guard`） |
| `lib/permissions.ts` | `ROLE_PERMISSIONS`、`hasPermission()`、`canAny()` | **后端 `permissions.py` 的镜像**，只用于 UI 显隐。改角色矩阵必须两边同步 |
| `lib/format.ts` | `formatDate/formatMonth/timeAgo/number/initial/absoluteUrl/safeJson/coverVariant/stripStyleClose` | 日期均为 `zh-CN` 本地化；`safeJson` 防 `</script>` 注入；`stripStyleClose` 防自定义 CSS 提前闭合 `<style>` |
| `lib/photo.ts` | `PHOTO_EXIF_FIELDS`、`PHOTO_EXIF_LABELS`、`exifFieldVisible()`、`photoSpecs()`、`photoMetaLine()`、`specsJson()` | 照片 EXIF 展示的唯一入口，网格/大图/Lightbox 共用；必须尊重 `exif_fields` 白名单 |
| `lib/audio-embed.ts` | `normalizeAudioUrl()`、`buildAudioEmbed()`、`audioMimeFor()` | 生成 `<figure class="audio-embed"><audio>…`，后端 bleach 白名单已允许 `audio/source` |
| `lib/admin-client.ts` | `toast/escapeHtml/errorMessage/formatBytes/statusBadge/debounce/logout/initAdminShell` | 后台通用交互；`initAdminShell()` 在 AdminLayout 里调用一次 |
| `lib/exif-dialog.ts` | EXIF 弹窗控制 | 媒体库/相册编辑共用 |
| `lib/proxy.ts` | `forwardToApi()` | 见 5.2 |

### 5.4 布局与全局注入

**`layouts/BaseLayout.astro`**（公共页）：

- 从 `site.settings` 读取并在 `<html>` 上注入：`data-color-mode` / `data-palette` / `data-font` / `data-theme`，以及内联 style：

```text
--accent / --layout-width / --radius / --photo-columns / --hero-image
```

- 渲染 SEO：title、description、keywords、canonical、OG/Twitter、RSS 链接、favicon、可选 `noindex`。
- 内联脚本（`is:inline`）在首屏前确定明暗模式（`localStorage['scene-color-mode']` 优先，兼容旧键 `ink-color-mode`），避免闪烁。
- 注入 `settings.head_html`（后台可填统计脚本）与清洗后的 `custom_css`。
- 全局脚本：吸顶 header、明暗切换、移动端菜单；末尾挂 `<Lightbox />`。

**`layouts/AdminLayout.astro`**：

- 同样注入设计令牌，`<body data-role>`。
- 导航项按权限过滤（`AdminLayout.astro:51`）：`影像` 需 `gallery.manage`、`页面` 需 `content.others`、`媒体库` 需 `media.manage`、`评论` 需 `comment.moderate`、`分类与标签` 需 `taxonomy.manage`、`外观/设置` 需 `settings.manage`、`成员` 需 `users.manage`。
- 末尾 `initAdminShell()`：侧栏开合、退出登录、待审核评论角标。

**`layouts/AuthLayout.astro`**：登录/初始化页的外壳。

### 5.5 页面清单

**公共页面**

| 路由 | 文件 | 取数 |
| --- | --- | --- |
| `/` | `pages/index.astro` | `/api/galleries?per_page=6` + `/api/posts?per_page=4` |
| `/photos` | `pages/photos.astro` | `/api/galleries?per_page=60` |
| `/galleries/{slug}` | `pages/galleries/[slug].astro` | `/api/galleries/{slug}` |
| `/galleries` | `pages/galleries/index.astro` | 301 → `/photos` |
| `/archive` | `pages/archive.astro` | `/api/archive` |
| `/posts/{slug}` | `pages/posts/[slug].astro` | `/api/posts/{slug}` + `/api/comments` |
| `/{slug}` | `pages/[slug].astro` | `/api/pages/{slug}`（**注意与静态路由的优先级**） |
| `/tags/{tag}` | `pages/tags/[tag].astro` | `/api/taxonomy` + `/api/posts?tag=` |
| `/categories/{cat}` | `pages/categories/[category].astro` | 同上（category） |
| `/search` | `pages/search.astro` | `/api/search?q=` |
| `/404` | `pages/404.astro` | — |
| `/rss.xml` | `pages/rss.xml.ts` | `/api/posts?per_page=40` |
| `/sitemap.xml` | `pages/sitemap.xml.ts` | `/api/archive` + galleries + pages + taxonomy |
| `/robots.txt` | `pages/robots.txt.ts` | Disallow `/admin`、`/api` |

**后台页面**（每个都是 `guardAdmin(...)` + `AdminLayout` + 一个 `scripts/admin-*.ts`）

| 路由 | 页面文件 | 脚本 | 权限 |
| --- | --- | --- | --- |
| `/admin` | `admin/index.astro` | `admin-dashboard.ts` | staff |
| `/admin/posts` | `admin/posts/index.astro` | `admin-post-list.ts` | `content.read` |
| `/admin/posts/new`、`/admin/posts/{id}` | 同上目录 | `components/admin/PostEditor.astro` | `content.write` |
| `/admin/pages`… | `admin/pages/*` | `admin-post-list.ts` | `content.others` |
| `/admin/galleries` | `admin/galleries/index.astro` | `admin-galleries.ts` | `gallery.manage` |
| `/admin/galleries/{id}` | `admin/galleries/[id].astro` | `admin-gallery-detail.ts` | `gallery.manage` |
| `/admin/media` | `admin/media.astro` | `admin-media.ts` | `media.manage` |
| `/admin/comments` | `admin/comments.astro` | `admin-comments.ts` | `comment.moderate` |
| `/admin/taxonomy` | `admin/taxonomy.astro` | `admin-taxonomy.ts` | `taxonomy.manage` |
| `/admin/appearance` | `admin/appearance.astro` | `admin-appearance.ts` | `settings.manage` |
| `/admin/settings` | `admin/settings.astro` | `admin-settings.ts` | `settings.manage` |
| `/admin/users` | `admin/users.astro` | `admin-users.ts` | `users.manage` |
| `/admin/login`、`/admin/setup` | `admin/login.astro`、`admin/setup.astro` | 内联 | — |

**组件**

| 组件 | 用途 |
| --- | --- |
| `HomeHero.astro` | 首页主视觉（split/minimal/image） |
| `GalleryCard.astro` | 相册卡片（编号、封面、照片数） |
| `GalleryViewer.astro` | 相册大图浏览（← →、按钮、缩略图、滑动） |
| `PhotoGrid.astro` | 照片网格 / 瀑布流 |
| `Lightbox.astro` + `scripts/lightbox.ts` | 全站图片灯箱（事件委托，`data-photo`） |
| `StoryCard.astro` | 文章卡片（归档/搜索/相关） |
| `CoverArt.astro` | 无封面时的程序化文字封面（6 种色板） |
| `Comments.astro` | 评论区（读取 + 提交 + 蜜罐） |
| `Pagination.astro` | 分页 |
| `SiteHeader.astro` / `SiteFooter.astro` | 站点页头/页脚 |
| `Icon.astro` | 内联 SVG 图标集合（`name` 选择） |
| `admin/PostEditor.astro` | 文章编辑器（Markdown 工具栏、预览、版本、定时、SEO、音频插入） |
| `admin/AudioEmbedDialog.astro` + `scripts/audio-embed-dialog.ts` | 音频插入对话框（媒体库选择或填 URL） |

### 5.6 后台 CRUD 页面的固定写法

新增一个后台页面时，照着现有页面复制这套"三件套"结构：

**① 页面（`.astro`）**

```astro
---
import AdminLayout from '../../layouts/AdminLayout.astro';
import Icon from '../../components/Icon.astro';
import { guardAdmin } from '../../lib/auth';

const guard = await guardAdmin(Astro, 'your.permission');   // 页面级守卫
if (guard instanceof Response) return guard;                // 重定向/拒绝
const user = guard;
---
<AdminLayout user={user} title="标题" subtitle="Section / Name" active="yourkey">
  <div data-your-page>                                     <!-- 脚本的根钩子 -->
    <div class="admin-toolbar">…</div>
    <div data-your-list></div>
  </div>

  <script>
    import '../../scripts/admin-your-page';                <!-- 交互脚本 -->
  </script>
</AdminLayout>
```

**② 导航入口**：在 `layouts/AdminLayout.astro:51` 的 `nav` / `siteNav` 数组加一项，并填 `show: can('your.permission')`。`active` 与 `key` 对应。

**③ 脚本（`.ts`）**

```ts
import { api, qs } from '../lib/api';
import { errorMessage, escapeHtml, toast } from '../lib/admin-client';

const root = document.querySelector<HTMLElement>('[data-your-page]');
if (root) {
  const load = async () => { /* api<T>(...) → root.innerHTML = ... */ };
  root.querySelector('[data-save]')?.addEventListener('click', async () => {
    try { await api('/api/admin/...', { method: 'POST', body }); toast('已保存', 'success'); load(); }
    catch (error) { toast(errorMessage(error), 'error'); }
  });
  load();
}
```

约定：

- 脚本一律"有根节点才执行"（`if (root)`），避免在其他页面报错。
- DOM 钩子用 `data-*`，不依赖 class 名（样式改动不影响逻辑）。
- 用户输入进模板前必须 `escapeHtml()`；`toast()` 统一提示；`statusBadge()` 统一状态标签。
- 列表数据量大时用 `debounce()` 做搜索；分页字段来自后端 `pagination()`。

### 5.7 样式系统

**加载顺序**：`BaseLayout` → `global.css` + `mono.css`；`AdminLayout` → `global.css` + `admin.css`（`admin.css` 末尾有 Scene 扁平化覆盖层）。

**`global.css` 结构**（按文件内注释分段）：

1. `:root` 设计令牌（`global.css:15`）
2. Reset & base
3. Layout primitives
4. Small typographic devices
5. Header / Footer
6. Home — hero / Section headings
7. Photo grid & tiles / Gallery large-image viewer
8. Journal list / Galleries
9. Story cards / Articles / Prose（Markdown 渲染结果）
10. Page hero / Archive / Terms & search
11. Comments / Cover art / Empty states / Pagination / Bands / Not found
12. Responsive

**核心令牌**：

```css
--font-mono / --font-display / --font-body
--bg / --bg-elevated / --bg-sunken / --bg-inverse
--ink / --ink-soft / --ink-faint / --ink-inverse
--line / --line-soft / --line-strong
--accent / --accent-ink / --accent-wash
--layout-width / --reading-width / --radius / --header-height
--gutter / --grid-gap / --band / --ease
```

**主题切换机制**（三层叠加）：

| 层 | 选择器 | 来源 |
| --- | --- | --- |
| 色板 | `html[data-palette="scene\|stone\|sand\|night"]` | 后台 `theme` |
| 明暗 | `html[data-color-mode="light\|dark"]` | 后台 `color_mode` + 前端 localStorage 即时切换 |
| 字体 | `html[data-font="sans\|serif\|mono"]` | 后台 `font_pair`（默认 mono，`mono.css` 是 Mono 层） |

外加**运行时内联变量**（`--accent`、`--layout-width`、`--radius`、`--photo-columns`），由后台写入、`BaseLayout` 注入。

改主题的正确姿势：

1. 改色 → 改 `:root` / `html[data-palette=...]` 中的 `--bg/--ink/--line`；
2. 改排版 → 改 `--font-*` 或对应 `data-font` 块；
3. 改整体密度/留白 → 改 `--band/--gutter/--grid-gap`；
4. **不要在组件里写死颜色**，一律用变量；后台 `custom_css` 是用户级覆盖，不要写进仓库。

### 5.8 类型（`types.ts`）

与后端 JSON 对齐的接口：`SiteSettings`、`SiteInfo`、`Author`、`PostSummary`、`PostDetail`、`AdminPost`、`Gallery`、`Photo`、`Term`、`Comment`、`AdminUser`、`Paginated<T>`、`SearchResults`、`SiteStatus`、`PhotoExifField` 等。

**新增/修改后端字段时，必须同步更新 `SiteSettings` 或对应接口**，否则 `astro check` 会报错或运行期取到 `undefined`。

---

## 6. 数据模型与可见性规则

### 6.1 关系图

```text
users ──┬─< posts (author_id)      ──< post_categories >── categories
        │                          ──< post_tags >─────── tags
        │                          ──< comments
        │                          ──< revisions
        ├─< sessions
        ├─< galleries (author_id)  ──< photos (gallery_id) ──> media (media_id)
        └─< media (owner_id / uploaded_by)                      │
                                                                └─ exif JSON

galleries.cover_photo_id ──> photos.id
photos.filename 保存 media.filename 的快照（media 删除后相册仍可渲染）
photos.exif_fields 是每张照片的 EXIF 公开白名单（逗号分隔）
```

### 6.2 状态机

| 实体 | 状态 | 说明 |
| --- | --- | --- |
| `posts.status` | `draft` / `published` / `scheduled` | `scheduled` + `published_at <= now` 时对外等同 `published`（查询时判断，无后台定时器） |
| `galleries.status` | `draft` / `published` | 只有 published 出现在 `/photos` 与详情页 |
| `photos.status` | `draft` / `published` | 且必须属于 published 相册才公开 |
| `comments.status` | `pending` / `approved` / `spam` | 公开接口只返回 approved；`comment_moderation=false` 时新评论直接 approved |

### 6.3 公开可见性（唯一真相）

```python
# backend/app/posts.py:12
PUBLIC_CONDITION = (
    "p.type = ? AND p.status IN ('published', 'scheduled') "
    "AND p.published_at IS NOT NULL AND p.published_at <= ?"
)

# backend/app/galleries.py:19
GALLERY_PUBLIC_CONDITION = "g.status = 'published'"
# backend/app/galleries.py:22
PHOTO_PUBLIC_CONDITION = (
    "ph.status = 'published' AND ph.gallery_id IS NOT NULL AND g.status = 'published'"
)
```

推论：

- 草稿照片、未发布相册、游离照片都不会出现在公开页面；
- 后台照片可以 `gallery_id IS NULL`（媒体库管理），但公开侧不会单独展示；
- 任何"新增公开列表"的接口都应该复用这些条件，而不是自己写 `status != 'draft'`。

### 6.4 与旧版本的兼容

- `posts` 仍保留 `project_*` 列（历史项目数据），但公开/后台入口已移除；
- `media.uploaded_by` 是旧列，`owner_id` 是现值；所有查询用 `COALESCE(owner_id, uploaded_by)`；
- `_migrate_scene` / `_migrate_mono` 会把旧的 "Ink Isle" 默认值/色板映射到 Scene，但只在值仍等于旧默认值时覆盖；
- `/galleries`（索引）保留 301 到 `/photos`，旧的 `/projects` 系列已无入口。

## 7. API 参考

### 7.1 通用约定

- Base URL：浏览器侧统一 `/api/...`（经 Astro 代理）；服务端渲染时用 `BLOG_API_INTERNAL_URL + '/api/...'`。
- 请求/响应均为 JSON（上传除外，用 `multipart/form-data`）。
- 管理端写操作必须带 `x-blog-request: 1`（`apiServer()` 与浏览器 `api()` 已自动带）。
- 时间格式：ISO 8601 UTC，形如 `2026-05-01T12:34:56Z`。
- 错误格式：

```json
{ "detail": "当前角色没有这项权限" }
```

Pydantic 校验失败时 `detail` 是数组，前端 `detailToMessage()` 会转成中文字符串。

常见状态码：`401` 未登录、`403` 无权限/CSRF 头缺失、`404` 不存在、`409` 冲突（用户名重复、EXIF 已有值、最后一个管理员）、`413` 上传过大、`415` 不支持的类型、`422` 参数校验失败、`429` 限流。

### 7.2 主要响应结构

**`GET /api/site`**

```json
{
  "settings": { "site_title": "MZTLAB", "theme": "scene", "nav": [], "…": "见 defaults.py" },
  "categories": [{ "id": 1, "name": "技术", "slug": "tech", "description": "", "count": 3 }],
  "tags": [{ "id": 1, "name": "随笔", "slug": "essay", "count": 2 }],
  "post_count": 3,
  "photo_count": 12,
  "gallery_count": 3,
  "version": "2.1.0"
}
```

**`GET /api/posts/{slug}`（PostDetail）**

| 字段 | 说明 |
| --- | --- |
| `id/type/title/slug/url/excerpt/cover_image` | 基本信息 |
| `status` | 对外有效状态（scheduled 到点后为 published） |
| `published_at/created_at/updated_at` | 时间 |
| `reading_time/view_count/comment_count` | 计数 |
| `author{name,avatar,bio}` | 公开作者信息（不含 username） |
| `categories[]/tags[]` | `{id,name,slug}` |
| `seo_title/seo_description` | SEO 覆盖 |
| `content_html` | 渲染并净化后的 HTML（仅 detail） |
| `toc[]` | `{id,text,level}`（仅 detail） |
| `prev/next` | `{title,slug,url}` 或 null |
| `related[]` | PostSummary 列表 |
| `canonical` | 相对 URL |
| `comments_enabled/comment_moderation` | 评论开关 |

**`GET /api/galleries/{slug}`（Gallery）**

| 字段 | 说明 |
| --- | --- |
| `id/title/slug/url/description/status/featured` | 基本信息 |
| `cover` | Photo 或 null（`cover_photo_id` 优先，否则第一张） |
| `photo_count/view_count/created_at/updated_at` | 计数与时间 |
| `author{name,avatar}` | 公开作者 |
| `photos[]` | Photo 列表（detail） |
| `related[]` | 其他相册（最多 3） |

**Photo 结构**（`galleries.py:50` `photo_dict`）：

| 字段 | 说明 |
| --- | --- |
| `id/gallery_id/media_id/url/filename` | `url` 形如 `/media/2026/05/xxx.jpg` |
| `title/caption/alt/location` | 文案；`alt` 回退 title → caption → "摄影作品" |
| `camera/lens/taken_at/taken_at_raw/aperture/exposure/iso/focal_length/focal_length_35mm` | EXIF 技术字段 |
| `exif_fields[]` | 公开白名单 |
| `exif` | 过滤后的 EXIF 对象或 null |
| `width/height/aspect` | 尺寸与宽高比 |
| `featured/status/sort_order/created_at` | 状态与排序 |

**`GET /api/admin/media`（Media）**：`id/filename/original_name/mime/size/width/height/alt/url/kind('image'|'audio')/exif/owner{id,name,username}/created_at`。

**`GET /api/admin/stats`**：`posts{all,published,draft,scheduled}`、`pages`、`comments{all,pending,approved,spam}`、`media`、`galleries`、`photos`、`views`、`tags`、`categories`、`recent_posts[]`、`recent_galleries[]`、`pending_comments[]`、`recent_comments[]`、`top_posts[]`、`system{version,generated_at}`。

**分页结构**（`posts.pagination()`）：

```json
{ "page": 1, "per_page": 9, "total": 24, "pages": 3, "has_prev": false, "has_next": true }
```

### 7.3 新增接口时不要忘记

1. 在 `backend/app/routes/` 中定义（或新建 router 并在 `main.py:73` 附近 `include_router`）。
2. 写操作必须挂权限依赖（`Depends(require_permission("…"))`），涉及他人内容再加 `_assert_can_edit` / `_ensure_owner`。
3. 请求体进 `schemas.py`，返回走 `serialize_*` / 统一 dict。
4. 前端调用统一走 `lib/api.ts` 的 `api()` / `apiServer()`，不要手写 `fetch`。
5. 若接口返回公开数据，复用 `PUBLIC_CONDITION` 等条件。

---

## 8. 扩展开发指南（从需求到改动的完整路径）

> 每一节都是"改哪些文件、按什么顺序、怎么验证"。建议按顺序改，最后统一跑测试与构建。

### 8.1 新增一个站点设置项

示例：增加"首页底部一句话" `home_note`（纯文本）。

**步骤 1 — 声明默认值与白名单**
`backend/app/defaults.py`，在 `DEFAULT_SETTINGS` 里加键：

```python
DEFAULT_SETTINGS: dict[str, Any] = {
    # …
    "home_note": "安静地记录。",
}
```

这一步同时把它加入 `PUBLIC_SETTING_KEYS`（`defaults.py:84`），所以 `/api/site` 和导出都会包含它；如果不希望公开，加到 `PRIVATE_SETTING_KEYS`。

**步骤 2 — 允许后台写入并做长度限制**
`backend/app/routes/admin.py` 的 `update_settings`（`admin.py:733`）：

```python
text_limits = {
    # …
    "home_note": 120,
}
```

布尔项加入 `{"hero_show", …}` 那个集合；数值项仿照 `posts_per_page` 分支；枚举仿照 `theme` 分支。**不在此处声明的键会被静默丢弃**。

**步骤 3 — 前端类型与兜底**
`frontend/src/types.ts` → `SiteSettings` 加 `home_note: string;`
`frontend/src/config.ts` → `fallbackSite.settings` 加同名默认值。

**步骤 4 — 后台编辑表单**
`frontend/src/pages/admin/settings.astro`，在合适面板（如 `data-settings-panel="general"`）里加一行：

```astro
<div class="setting-row">
  <div class="setting-row__label"><strong>首页附注</strong><span>显示在首页底部。</span></div>
  <div class="a-field"><input type="text" maxlength="120" data-setting="home_note" /></div>
</div>
```

`admin-settings.ts` 会自动按 `[data-setting]` 读写（`load()` 与 `collect()`，`admin-settings.ts:42` / `:100`），纯文本无需改脚本。若是数值要加入 `numericKeys`，布尔下拉加入 `booleanKeys`。

**步骤 5 — 页面使用**
`frontend/src/pages/index.astro` 中 `settings.home_note` 直接用即可。

**验证**：`/admin/settings` 改值 → 保存 → 刷新首页 → 重新运行 `npm run check`。

---

### 8.2 给文章增加一个字段

示例：`subtitle`（副标题，字符串）。

**步骤 1 — 数据库列**
`backend/app/db.py`：

```python
# 1) 新库建表也需要这列（SCHEMA 里的 posts 定义）
CREATE TABLE IF NOT EXISTS posts (
    …
    subtitle TEXT NOT NULL DEFAULT '',
);

# 2) 老库补列（幂等，每次启动执行）
_ADDED_COLUMNS = {
    "posts": {
        "subtitle": "TEXT NOT NULL DEFAULT ''",
        # 已有列保持不变
    },
}
```

只改 `_ADDED_COLUMNS` 就能让老库升级；同时把列写进 `SCHEMA` 让新库一次到位。若需要回填历史数据，新增一个 `_migrate_xxx(conn)` 并在 `init_db()` 中按 `user_version` 调用，然后把 `SCHEMA_VERSION` +1。

**步骤 2 — 请求校验**
`backend/app/schemas.py` → `PostIn`：

```python
subtitle: str = Field(default="", max_length=200)
```

**步骤 3 — 写入逻辑**
`backend/app/routes/admin.py`：

- `_post_request()`（`admin.py:186`）返回值里加 `"subtitle": payload.subtitle`；
- `create_post` 的 INSERT（`admin.py:360`）列清单与参数加 `subtitle`；
- `update_post` 的 UPDATE（`admin.py:403`）加 `subtitle = ?`；
- （可选）预览接口不需要，因为预览只渲染 Markdown。

**步骤 4 — 序列化**
`backend/app/posts.py`：`serialize_post()` 的 `item`、`_list_item()` 里加 `"subtitle": data.get("subtitle", "")`；`admin=True` 分支可按需加。

**步骤 5 — 前端类型**
`frontend/src/types.ts`：`PostSummary`（如果列表也返回）与 `PostDetail` / `AdminPost` 加 `subtitle?: string`。

**步骤 6 — 后台编辑器**
`frontend/src/components/admin/PostEditor.astro`：加输入框（`data-field="subtitle"` 之类，参照现有 `title` / `excerpt` 的写法），并在该组件内的保存收集逻辑里带上；`admin-post-list.ts` 若列表展示则同步。

**步骤 7 — 公共页**
`frontend/src/pages/posts/[slug].astro`：在 `<h1>` 下渲染 `{post.subtitle && <p class="article-deck">{post.subtitle}</p>}`。

**步骤 8 — 验证**

```bash
cd backend && .venv/Scripts/python -m unittest discover -s tests
cd frontend && npm run check && npm run build
```

用旧数据库启动一次，确认 `PRAGMA table_info(posts)` 已有新列、旧文章不报错。

---

### 8.3 新增一个后台页面

示例：`/admin/analytics`（只读统计页）。

1. **页面**：新建 `frontend/src/pages/admin/analytics.astro`，使用 5.6 的模板，`guardAdmin(Astro, 'content.read')`（或新权限）。
2. **导航**：`frontend/src/layouts/AdminLayout.astro:51` 的 `nav` 数组加：

```ts
{ key: 'analytics', label: '分析', href: '/admin/analytics', icon: 'dashboard', show: can('content.read') },
```

`icon` 必须是 `components/Icon.astro` 里已存在的名字，否则图标不显示。
3. **脚本**：新建 `frontend/src/scripts/admin-analytics.ts`，页面里 `<script>import '../../scripts/admin-analytics';</script>`。
4. **数据接口**：若现有 `/api/admin/stats` 不够，按 8.5 增加接口。
5. **样式**：优先复用 `admin.css` 已有类（`admin-card`、`admin-toolbar`、`a-btn`、`settings-panel`…），避免新增样式。
6. **验证**：用 `author` 账号登录确认无权限时不显示导航且直接访问会被重定向到 `/admin?denied=…`。

---

### 8.4 新增一个公共页面

示例：`/now` 展示当前状态页。

1. 新建 `frontend/src/pages/now.astro`，套 `BaseLayout`：

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import { getSite } from '../lib/api';
const site = await getSite();
---
<BaseLayout site={site} title="Now" description="此刻在做的事。">
  <section class="container page-hero">
    <span class="eyebrow">// NOW</span>
    <h1>Now</h1>
  </section>
</BaseLayout>
```

2. **路由冲突**：`pages/[slug].astro` 会把根路径下的 `/{slug}` 当作"独立页面"去后端查 `type='page'`。Astro 中**静态路由优先于动态路由**，所以 `now.astro` 会覆盖 `[slug].astro`，无需额外处理；但命名时别和已有静态路由重名（`photos`、`archive`、`search`、`admin`、`rss.xml`…）。
3. 若页面需要数据，在 frontmatter 用 `apiServer<T>()`，并像 `posts/[slug].astro` 一样捕获 `ApiError` 404 → `Astro.rewrite('/404')`。
4. 加导航：后台 → 设置 → 导航（运行时配置，不用改代码）；或改 `defaults.py` 的 `nav` 默认值。
5. 加 sitemap：`frontend/src/pages/sitemap.xml.ts` 的 `entries` 初始数组里加 `{ loc: '/now' }`。
6. 验证 `npm run check` + 页面可直接访问、`/rss.xml` 不受影响。

---

### 8.5 新增一个 API 端点

示例：`GET /api/admin/media/usage`（媒体占用统计）。

```python
# backend/app/routes/media.py  （已有 router = APIRouter(prefix="/admin", …)）
@router.get("/media/usage")
def media_usage(user: dict = Depends(require_staff)) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM media"
        ).fetchone()
    return {"count": int(row["n"]), "bytes": int(row["bytes"])}
```

要点：

- 路由顺序：`/media/usage` 必须定义在 `/media/{media_id}` **之前**，否则会被 `{media_id}` 捕获并因 `int` 转换失败返回 422。
- 权限：读用 `require_staff`；写用 `require_permission("…")`；涉及他人数据再 `_ensure_owner`。
- router 已在 `main.py` 挂载，无需再改入口。新建 router 才需要 `app.include_router(new.router, prefix="/api")`。
- 前端调用：`const data = await api<{count:number;bytes:number}>('/api/admin/media/usage');`
- 在 `BLOG_ENABLE_API_DOCS=true` 启动后的 `/api/docs`（Swagger）里确认参数、响应模型是否正确。

---

### 8.6 新增权限键或调整角色矩阵

权限有两份**必须同步**的定义：

- 后端：`backend/app/permissions.py` → `PERMISSIONS`、`ROLE_PERMISSIONS`、`ROLE_LABELS`、`ROLE_SUMMARIES`
- 前端镜像：`frontend/src/lib/permissions.ts` → `ROLE_PERMISSIONS`（仅用于 UI 显隐）

新增权限键示例 `analytics.read`：

```python
# permissions.py
PERMISSIONS = { …, "analytics.read": "查看访问统计" }
ROLE_PERMISSIONS = {
    "admin": frozenset(PERMISSIONS),
    "editor": frozenset({…, "analytics.read"}),
    "author": frozenset({…}),
}
```

```ts
// frontend/src/lib/permissions.ts
editor: ['…', 'analytics.read'],
```

然后在路由上用 `Depends(require_permission("analytics.read"))`，在页面/导航上用 `guardAdmin(Astro, 'analytics.read')` / `show: can('analytics.read')`。

**动态权限**：像 `content.others` 这种"由设置开启"的权限，做法是：

1. 从 `ROLE_PERMISSIONS` 中**不要**静态授予；
2. 在 `effective_permissions(role, manage_others=…)` 中按设置追加（`permissions.py:89`）；
3. 在 `user_public()`（`deps.py:31`）里把设置值传进去。

改完记得更新 `backend/tests/test_permissions.py`：它断言"editor 默认没有 content.others、admin 拥有全部权限、author 永远不会获得"。

---

### 8.7 相册 / 照片相关扩展

| 需求 | 改动 |
| --- | --- |
| 增加可公开的 EXIF 字段 | `photo_exif.py` 的 `EXIF_FIELDS` + `frontend/src/lib/photo.ts` 的 `PHOTO_EXIF_FIELDS` / `PHOTO_EXIF_LABELS` + `galleries.py:75` 的 `technical` dict + `components/GalleryViewer.astro` / `PhotoGrid.astro` 展示 |
| 改照片公开过滤规则 | `galleries.py` 的 `PHOTO_PUBLIC_CONDITION`（会影响所有公开查询） |
| 改排序（手动/taken/recent） | `galleries.py:308` 的 `ordering` 分支 + 后台拖拽逻辑（`gallery_admin.reorder_photos`） |
| 改封面回退逻辑 | `gallery_dict()`（`galleries.py:148`） |
| 新增照片字段 | `db.py` 的 `SCHEMA` + `_ADDED_COLUMNS["photos"]` → `schemas.PhotoIn/PhotoUpdateIn` → `gallery_admin.create_photo/update_photo` → `galleries.photo_dict` → `frontend/src/types.ts` 的 `Photo` → 后台 `admin-gallery-detail.ts` + 公共组件 |
| 媒体库支持新图片格式 | `routes/media.py` 的 `FORMAT_EXTENSIONS`；注意 `<input accept>`（`admin/media.astro`）与 `README` 文案 |
| 支持视频 | 仿照音频：`media.py` 增加 `VIDEO_EXTENSIONS` + 魔数校验 + `kind='video'` + `_serialize` 分支；`content.py` 的 `ALLOWED_TAGS` 加 `video`/`source` 属性；前端媒体库与播放器组件 |

**注意**：照片的 `filename` 是 `media.filename` 的**快照**，删除媒体后照片仍可读旧路径（文件已删则 404）。如果要做"媒体引用完整性"检查，需要在 `delete_media` 前查询 `photos.media_id`。

---

### 8.8 修改主题与样式

按"由粗到细"的顺序改：

1. **全局色板/字体**：`frontend/src/styles/global.css` 的 `:root`（`global.css:15`）与 `html[data-palette=…]` 块。
2. **Mono 层的排版细节**：`frontend/src/styles/mono.css`（标题字距、代码标签、hero 字号、EXIF 行）。
3. **组件级样式**：对应段落（Photo grid / Gallery viewer / Prose / Archive…），用文件内注释定位。
4. **后台样式**：`frontend/src/styles/admin.css`（末尾是 Scene 覆盖层，新增后台样式优先加在覆盖层之后）。
5. **新增可配置项**（如"新的色板"）：
   - `defaults.py` 的 `THEMES` 加值、`DEFAULT_SETTINGS.theme` 可选值说明；
   - `schemas.AppearanceIn.theme` 的 `Literal` 加值；
   - `global.css` 增加 `html[data-palette="新值"]` 块；
   - `BaseLayout.astro` / `AdminLayout.astro` 的 `palette` 校验数组加值；
   - `admin/appearance.astro` 的主题选择按钮加一项（`data-choice-group="theme"`）；
   - `frontend/src/config.ts` 的 fallback 可选值同步（可选）。
6. **不要在组件里写死颜色/字号**；不要改 `stripStyleClose` 的安全逻辑（它防止 `custom_css` 提前闭合 `<style>`）。

---

### 8.9 Markdown 与嵌入内容

**新增一个 Markdown 扩展**：

1. `backend/app/content.py` 的 `MD_EXTENSIONS` 加扩展名，必要时改 `MD_CONFIG`；
2. 检查扩展产出的标签/属性是否在 `ALLOWED_TAGS` / `ALLOWED_ATTRIBUTES` 里，否则会被 bleach 丢弃（表现为"编辑器里有、前台没有"）；
3. 旧文章需要重渲染才会生效（见 4.6 的提示）。

**新增一种嵌入块**（参考音频）：

1. 前端生成 HTML 字符串的模块放 `frontend/src/lib/`（如 `audio-embed.ts`），做 URL 白名单校验与 HTML 转义；
2. `content.py` 白名单加对应标签；
3. `backend/tests/test_content.py` 加一条"该 HTML 能通过净化"的测试（现有 `test_allows_html5_audio_embed` 就是模板）；
4. 编辑器工具栏入口：`components/admin/PostEditor.astro`（参考 `♫` 按钮与 `AudioEmbedDialog.astro`）。

**修改代码高亮**：`Pygments` 已在 `MD_CONFIG.codehilite` 启用（`css_class="highlight"`），样式在 `global.css` 的 Prose 段；换主题只需改 CSS，不用动后端。

---

### 8.10 RSS / Sitemap / SEO 扩展

| 需求 | 文件 |
| --- | --- |
| RSS 增加全文或封面 | `frontend/src/pages/rss.xml.ts` 的 `<item>` 模板（注意 `escapeXml`，以及正文需从 `content_html` 取，而列表接口不返回它 → 可能要逐篇调 `/api/posts/{slug}`） |
| 调整 RSS 条数 | 同上 `?per_page=40` |
| sitemap 增加静态页/新内容类型 | `sitemap.xml.ts` 的 `entries` |
| robots 规则 | `robots.txt.ts` |
| 文章结构化数据 | `pages/posts/[slug].astro` 的 `jsonLd` 对象（BlogPosting） |
| OG/Twitter 卡片 | `layouts/BaseLayout.astro` + 后台设置 `og_image` / `seo_description` |
| canonical 域名 | 后台 → 设置 → 站点地址（`site_url`），或 `BLOG_SITE_URL` 首启动注入 |

---

### 8.11 数据库迁移规范

**加列（最常见）** —— 只需 `_ADDED_COLUMNS`，不必动版本号：

```python
_ADDED_COLUMNS = {
    "posts": {"new_col": "TEXT NOT NULL DEFAULT ''"},
}
```

**改结构 / 数据回填 / 删列** —— 走版本化迁移：

1. `SCHEMA_VERSION` +1（例如 5 → 6）；
2. 在 `db.py` 里写幂等函数：

```python
def _migrate_v6(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 6:
        return
    # 只在旧值仍等于旧默认值时覆盖，避免抹掉用户内容
    conn.execute("UPDATE settings SET value = ? WHERE key = 'x' AND value = ?", ("新值", '"旧值"'))
```

3. 在 `init_db()` 的 `_migrate_scene(conn)` / `_migrate_mono(conn)` 之后调用 `_migrate_v6(conn)`；
4. 更新 `SCHEMA`（新库直接得到新结构）；
5. 在测试或本地用**旧数据库**跑一次：`python scripts/run.py --no-build`，看启动日志无异常、数据保留。

**删除列**（SQLite 3.35+ 支持 `ALTER TABLE … DROP COLUMN`，但本仓库更倾向"保留列 + 停止使用"，如 `project_*`）。若必须删，先确认没有代码引用，再在版本化迁移里执行。

**回滚**：本仓库没有 down migration。回滚做法是备份恢复（`backend/data` 整体复制）。上生产前务必先备份。

---

### 8.12 修改演示内容 / 种子数据

`backend/app/seed.py`：

- `DEMO_SEED_VERSION`（`seed.py:435`）：内容改版时 +1，已存在的库会重新播种（只补缺失的分区：文章/关于页/相册）；
- 文章内容在 `ARTICLES`，分类在 `CATEGORIES`，标签在 `TAGS`，关于页在 `ABOUT_PAGE`；
- 相册图片是 `_seed_galleries()` 用 Pillow 现场生成的色块图，写入 `uploads/seed/`；
- `BLOG_SEED_DEMO=false` 可完全关闭。

注意：种子**只插入缺失项**，不会覆盖用户改过的内容；想彻底重来就删 `backend/data`。

---

### 8.13 为改动添加测试

后端测试在 `backend/tests/`，用标准库 `unittest`（共 4 个文件、27 个用例）：

| 文件 | 覆盖 |
| --- | --- |
| `test_content.py` | Markdown 渲染、XSS 净化、音频白名单、slug、摘要、阅读时长、TOC、密码哈希 |
| `test_exif.py` | EXIF 读取、JSON 安全化、`photo_defaults` |
| `test_galleries.py` | `photo_dict` 的 URL/宽高比/相册信息、游离照片 |
| `test_permissions.py` | 角色矩阵、`effective_permissions`、`owns`、`role_meta` |

运行：

```bash
cd backend
.venv/Scripts/python -m unittest discover -s tests -v     # Windows
.venv/bin/python -m unittest discover -s tests -v         # macOS / Linux
```

加测试的原则：**纯函数优先**（不依赖数据库/HTTP）。现有测试都直接 import 纯函数；若需要测试路由，建议用 `fastapi.testclient.TestClient` + 临时 `BLOG_DATA_DIR`（模块导入前设置环境变量）。

前端没有自动化测试，靠 `npm run check`（TypeScript 类型检查）+ `npm run build` + 手工冒烟。

---

## 9. 调试与排错手册

### 9.1 症状 → 原因 → 位置

| 症状 | 常见原因 | 排查位置 |
| --- | --- | --- |
| 页面显示"内容服务离线" | FastAPI 没启动 / 端口不对 | `BLOG_API_INTERNAL_URL`，`http://127.0.0.1:8000/api/health` |
| `/api/...` 返回 502 `后端服务暂时不可用` | 代理连不上后端 | `frontend/src/lib/proxy.ts:46`，后端日志 |
| 后台保存返回 403 `请求缺少校验头` | 手写 fetch 没带 `x-blog-request: 1` | `backend/app/main.py:49`；改用 `lib/api.ts` |
| 后台保存返回 401 并跳登录 | 会话过期 / Cookie 没带 | `deps.get_session_user`，`credentials: 'same-origin'` |
| 登录后立刻又回登录页 | `BLOG_SESSION_COOKIE` 被改 / HTTPS 下 Cookie Secure 不匹配 / 反向代理没转发 Set-Cookie | `proxy.ts` 的 `getSetCookie()`，`config.py` |
| 403 `当前角色没有这项权限` | 角色矩阵或 `editor_manage_others` | `permissions.py`，后台 → 设置 → 协作与权限 |
| 403 `只能管理自己上传的媒体` / 只能编辑自己的内容 | `owns()` 不通过且无 `content.others` | 对应路由的 `_ensure_owner` / `_assert_can_edit` |
| 改了 Markdown 白名单但老文章没变化 | `content_html` 是写入时物化的 | 重渲染脚本（见 4.6） |
| 后台改了设置，前台要等一会儿才变 | `getSite()` 有 1 秒内存缓存 | `frontend/src/lib/api.ts:73` |
| 新加的设置项保存后丢失 | 没在 `update_settings` 的 `text_limits`/分支中声明 | `backend/app/routes/admin.py:733` |
| 新加的文章字段接口里没有 | 序列化层没加 | `backend/app/posts.py` `serialize_post` |
| 上传返回 413 | 超过 `BLOG_MAX_UPLOAD_MB` 或像素 > 4800 万 | `config.py`、`media.py:44` |
| 上传返回 415 | 类型不在白名单 / 魔数不匹配 | `media.py` `FORMAT_EXTENSIONS` / `_audio_format` |
| 图片没有 EXIF | 原图确实没有 / 旧数据未缓存 | `GET /api/admin/media/{id}/exif` 看 `source` 字段 |
| EXIF 编辑返回 409 | 已有字段不允许改写（设计如此） | `media.py:277` |
| 相册/照片前台不显示 | 状态或相册未发布 | `galleries.py` 的公开条件 |
| 根路径页面 404 | `pages/[slug].astro` 要求后端存在同 slug 的 `type='page'` | 后台 → 页面 |
| `/galleries` 打不开 | 它 301 到 `/photos` | `pages/galleries/index.astro` |
| 样式/主题不生效 | 内联变量被后台覆盖 / 选择器优先级 / 缓存 | DevTools 看 `<html>` 上的 data 属性与 style |
| `npm run dev` 报 `require is not defined` | 开发期 CJS 桥接被删/被改 | `astro.config.mjs` 的 `cjsBridges` 三个 `.mjs` |
| `database is locked` | 并发写 / 未用 WAL / 外部工具占用 | `db.connect()`（已设 WAL + busy_timeout）；避免长事务 |
| Windows 下 `python scripts/run.py` 起不来 | venv 路径 / npm 引号问题 | `run.py` 的 `npm_command()`；先跑 `setup.py` |

### 9.2 调试手段

- **后端**：`/api/docs` Swagger 直接试接口；`uvicorn --reload` 看异常栈；临时 `print` 在 `with db()` 前后。
- **数据库**：`sqlite3 backend/data/blog.db`（或用 DB Browser），先看 `PRAGMA user_version`、`PRAGMA table_info(posts)`、`SELECT * FROM settings`。
- **前端**：`npm run dev` 有 HMR；服务端渲染的报错会显示在终端；浏览器 Network 看 `/api` 请求与响应。
- **权限**：直接 `GET /api/auth/me` 看 `permissions` 数组，比猜快。
- **代理**：`curl -H 'x-blog-request: 1' http://127.0.0.1:4321/api/site` 验证整条链路。

---

## 10. 测试、构建与部署

### 10.1 提交前检查清单

```bash
# 1. 后端测试
cd backend && .venv/Scripts/python -m unittest discover -s tests

# 2. 前端类型检查 + 构建
cd frontend && npm run check && npm run build
```

手工冒烟（建议每次改动后至少跑一遍）：

1. 首页能打开，相册卡片与文章列表有数据；
2. `/photos` → 任一相册 → 大图 ← → 切换 → 网格 → Lightbox；
3. `/posts/{slug}` 正文、TOC、评论（若开启）；
4. 后台登录 → 新建草稿 → 预览 → 发布 → 前台可见；
5. 媒体库上传一张图 → 加入相册 → 前台可见；
6. 无权限账号登录，确认导航项与直接 URL 访问都被正确拒绝。

### 10.2 生产构建

```bash
# 前端产物：frontend/dist/server/entry.mjs + dist/client/*
cd frontend && npm run build

# 运行
cd frontend && node dist/server/entry.mjs          # 需要 BLOG_API_INTERNAL_URL
cd backend  && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

或 `python scripts/run.py`（非 `--dev` 会自动先 build）。

### 10.3 Docker 部署

```bash
docker compose up --build -d
docker compose logs -f backend
```

上线后必须做：

1. 设 `BLOG_COOKIE_SECURE=true`（在 HTTPS 之后）；若 `BLOG_SITE_URL` 已是 `https://`，默认即启用；
2. 用 Nginx/Caddy 把 `:4321` 暴露到公网并终止 TLS，**不要**暴露 `:8000`；
3. 为前后端设置同一个随机 `BLOG_PROXY_SECRET`（compose 里两端都读取该变量）；
4. 备份 `blog_data` volume（或 `backend/data`）：`blog.db` + `uploads/`；
5. 设置 `BLOG_SITE_URL` 为正式域名（或在后台 → 设置里改）。

### 10.4 升级步骤（部署新版本时）

1. 备份 `backend/data`；
2. 更新代码 → `python scripts/setup.py`（依赖有变时）；
3. 启动一次，`init_db()` 会自动迁移（看日志；`PRAGMA user_version` 应升到最新）；
4. `npm run build`（前端有改动时）；
5. 跑冒烟清单。

### 10.5 安全清单

- 密码哈希用 scrypt，密码强度策略拒绝弱口令，Session 只存 SHA-256 摘要，Cookie `HttpOnly + SameSite=Lax`（HTTPS 下自动 `Secure`）；
- 管理端写操作有 CSRF 头校验；所有富文本经 bleach 白名单；
- 上传做格式魔数 + 尺寸校验，路径做穿越防护；
- 公开设置与导出不会带出私有设置/密码哈希；
- 登录限流按 IP + 账号双维度、失败退避并记录告警；代理来源 IP 需要共享密钥，后端以 `--no-proxy-headers` 启动；
- `/api/docs`、`/api/openapi.json`、版本号与服务器指纹默认不外露；前端统一安全响应头 + CSP；
- 限流是单进程内存实现：多 worker 时换 Redis 或网关限流；
- 后台无二次验证，生产上建议加 IP 白名单或反向代理 Basic Auth。

---

## 11. 编码约定与风险清单

### 11.1 约定

1. **面向用户的文案用中文**，代码注释/标识符用英文；错误 `detail` 直接给用户看，写清楚"为什么 + 怎么办"。
2. **不引新依赖**除非必要：后端已经是"标准库 + 少量包"，前端只有 Astro + TS。加依赖要同步 `requirements.txt` / `package.json` 与 Dockerfile。
3. **权限两份定义必须同步**：`backend/app/permissions.py` ↔ `frontend/src/lib/permissions.ts`。
4. **序列化只在 `posts.py` / `galleries.py`**：路由里不要手写返回 JSON 结构。
5. **公开查询复用 `PUBLIC_CONDITION`**：不要自己拼状态条件。
6. **写库前先过 Pydantic**：任何来自请求的字段都进 `schemas.py`。
7. **迁移必须幂等**：`init_db()` 每次启动都会执行。
8. **前端后台脚本"有根节点才执行"**，DOM 钩子用 `data-*`，输入进模板前 `escapeHtml`。
9. **不要提交** `backend/data/`、`frontend/dist/`、`node_modules/`、`.env`、`.tmp/`（已在 `.gitignore`）。
10. **`.tmp/` 是本地浏览器缓存目录**，不属于项目代码，不要在里面找实现。

### 11.2 隐藏耦合点（改这些要特别小心）

| 位置 | 耦合关系 |
| --- | --- |
| `permissions.py` ↔ `lib/permissions.ts` | 角色矩阵重复定义 |
| `schemas.py` ↔ `types.ts` | 字段名/类型必须一致 |
| `defaults.py` ↔ `config.ts(fallbackSite)` ↔ `types.ts(SiteSettings)` | 设置键三处对齐 |
| `content.py` 白名单 ↔ `audio-embed.ts` 输出 | 标签/属性必须被允许 |
| `db.py SCHEMA_VERSION` ↔ 迁移函数 | 版本号与 `if version >= N` 判定 |
| `gallery_dict` / `photo_dict` ↔ `types.ts Photo/Gallery` ↔ 组件 | EXIF 字段与 `exif_fields` |
| `proxy.ts` ↔ `main.py` 中间件 | `x-blog-real-ip`、`x-blog-proxy-secret`、`x-blog-request`、Set-Cookie 转发 |
| `AdminLayout` nav ↔ 各 `guardAdmin` 权限 | 导航可见性与页面守卫要一致 |

### 11.3 Pull Request / 提交前自检

- [ ] 后端测试通过；前端 `check` + `build` 通过；
- [ ] 新字段：DB 迁移（幂等）+ schema + 序列化 + 类型 + 展示 全链路完成；
- [ ] 新设置项：`defaults.py` + `update_settings` 白名单 + 前端表单 + 类型；
- [ ] 新权限：两份定义同步 + 路由依赖 + 页面守卫 + 导航显隐；
- [ ] 公开接口不泄露草稿、邮箱、GPS、密码哈希；
- [ ] 用户输入已转义/净化；上传路径无穿越风险；
- [ ] 中文错误信息可直接展示；
- [ ] 更新本文件或 README 中受影响的部分。

---

## 附录 A：文件职责速查表

### A.1 后端

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `backend/app/main.py` | 92 | 入口、lifespan、CSRF/安全头中间件、路由挂载、`/media` 静态 |
| `backend/app/config.py` | 49 | 环境变量 → 常量 |
| `backend/app/db.py` | 516 | 连接、SCHEMA、迁移、settings |
| `backend/app/defaults.py` | 158 | 默认设置、公开/私有键、主题枚举、历史默认值 |
| `backend/app/security.py` | 113 | scrypt、token、限流 |
| `backend/app/deps.py` | 170 | 当前用户、权限依赖、会话 Cookie |
| `backend/app/permissions.py` | 168 | 权限键、角色矩阵、所有权 |
| `backend/app/schemas.py` | 331 | 请求模型校验 |
| `backend/app/content.py` | 173 | Markdown、slug、摘要、阅读时长、TOC |
| `backend/app/posts.py` | 393 | 文章查询/序列化、公开条件 |
| `backend/app/galleries.py` | 353 | 相册/照片查询/序列化、EXIF 白名单 |
| `backend/app/exif.py` | 298 | EXIF 解析与 JSON 安全化 |
| `backend/app/photo_exif.py` | 50 | 每张照片 EXIF 公开字段 |
| `backend/app/seed.py` | 599 | 演示内容、bootstrap 管理员 |
| `backend/app/routes/auth.py` | 110 | setup/login/logout/me |
| `backend/app/routes/public.py` | 349 | 公共读、搜索、评论、浏览量 |
| `backend/app/routes/admin.py` | 895 | 后台内容/评论/分类/设置/外观/导出 |
| `backend/app/routes/gallery_admin.py` | 454 | 相册与照片后台 |
| `backend/app/routes/media.py` | 362 | 上传、媒体、EXIF |
| `backend/app/routes/users.py` | 243 | 成员与角色 |
| `backend/tests/*.py` | — | 27 个 unittest 用例 |

### A.2 前端

| 文件/目录 | 职责 |
| --- | --- |
| `astro.config.mjs` | SSR/node adapter/端口/CJS 桥 |
| `src/config.ts` | 代码内常量 + `fallbackSite` |
| `src/types.ts` | API 类型 |
| `src/lib/api.ts` | 服务端/浏览器 API 客户端 |
| `src/lib/auth.ts` | 页面守卫 `guardAdmin` |
| `src/lib/permissions.ts` | 权限镜像 |
| `src/lib/proxy.ts` | `/api`、`/media` 代理 |
| `src/lib/format.ts` | 格式化工具 |
| `src/lib/photo.ts` | 照片 EXIF 展示 |
| `src/lib/audio-embed.ts` | 音频嵌入 HTML |
| `src/lib/admin-client.ts` | 后台通用交互 |
| `src/layouts/BaseLayout.astro` | 公共页骨架、SEO、主题注入 |
| `src/layouts/AdminLayout.astro` | 后台骨架、权限导航 |
| `src/layouts/AuthLayout.astro` | 登录/初始化骨架 |
| `src/components/*.astro` | 公共组件（见 5.5） |
| `src/components/admin/*` | 编辑器、音频对话框 |
| `src/pages/**` | 路由（公共 + admin + 代理 + RSS/sitemap） |
| `src/scripts/*.ts` | 后台与交互脚本（按页面一个文件） |
| `src/styles/global.css` | Scene 设计系统（令牌 + 全部公共样式） |
| `src/styles/mono.css` | Mono 排版层 |
| `src/styles/admin.css` | 后台样式 + Scene 覆盖层 |

---

## 附录 B：术语表

| 术语 | 含义 |
| --- | --- |
| Scene | 当前主题名，也是全站视觉系统的代号 |
| Mono | Scene 的等宽字体层（`mono.css`），后台 `font_pair` 默认值 |
| 相册 / Gallery | 一组策展照片，详见 `galleries` 表；公开路由 `/galleries/{slug}` |
| 照片 / Photo | 相册内条目，引用 `media`，带自己的文案与 EXIF 白名单 |
| 媒体 / Media | 媒体库中的文件记录（图片或音频），`media` 表 |
| 独立页面 / Page | `posts.type='page'`，URL 在根路径 |
| 版本 / Revision | 文章更新前保存的快照（`revisions` 表），可恢复 |
| 有效状态 | `scheduled` 到时间后对外显示为 `published`（查询时计算） |
| 公开条件 | `PUBLIC_CONDITION` 等 SQL 片段，决定什么内容能被公网看到 |
| CSRF 头 | 管理端写请求必须携带的 `x-blog-request: 1` |
| 所有权 | `author_id`/`owner_id`/`uploaded_by` 与当前用户匹配 |
| `content.others` | "可管理他人内容"的权限键，由设置 `editor_manage_others` 动态授予 |

---

*本文档基于仓库当前代码整理（`2.1.0` / schema `5`）。修改代码后，请同步更新对应章节，尤其是第 4.10、5.5、7、8 节中的行号与路径。*

