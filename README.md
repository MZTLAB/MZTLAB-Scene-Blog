# MZTLAB · Scene

影像、项目与文字。Astro 7 负责页面，FastAPI + SQLite 负责内容、认证与权限。

- **Scene 主题**：场景式作品集，照片、项目与文字三列等宽；全站等宽字体、轻量元数据。
- **文案可配置**：主题里绝大多数可见文字（主视觉、三列标题与说明、空状态、404、页脚等）都可以在后台修改，不需要改代码。
- **上传规则可配置**：单文件大小上限、允许的图片 / 音频 / 其他文件格式都能在后台调整，保存后立即生效。
- **自定义音频播放器**：编辑器插入的音频不再使用浏览器默认控件，而是与主题一致的播放器（播放/暂停、进度、时间、音量）。
- **三组内容并列**：相册、项目、文章共用一套所有权与权限，不把任何一组做成附属。
- **项目类型是自由文本**：直接输入「代码」「影像」「字体设计」等任意类型；视频项目只放文字介绍（不嵌视频、不上传视频文件）。
- **搜索内容与元数据**：标题、正文、项目年份 / 角色 / 上下文、照片地点 / 器材 / 拍摄时间都能搜到。
- **只按相册看照片**：`/photos` 是相册索引，照片只在已发布的相册里出现。
- **更完整的 EXIF**：焦距、等效焦距、光圈、快门、ISO、相机、镜头、时间与尺寸。
- **轻量后台**：文章、项目、相册、媒体、评论、成员与细粒度权限。
- **无 SPA / 无 Redis**：一个 Astro 进程、一个 FastAPI 进程、一个 SQLite 文件。

开发文档（框架、模块职责、扩展与改代码的具体路径）见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

## 预览

![首页](docs/home.png)

![后台概览](docs/admin.png)

![影像索引](docs/photos.png)

![相册](docs/gallery.png)

![编辑器](docs/editor.png)

![成员与权限](docs/members.png)

## 技术架构

```text
浏览器
  │
  ▼
Astro 7 SSR (127.0.0.1:4321)
  ├── 公共页面：首页 / 影像索引 / 项目索引 / 相册 / 文章 / 搜索 / 页面
  ├── 管理后台：概览 / 影像 / 项目 / 文章 / 页面 / 媒体 / 评论 / 外观 / 成员
  └── /api/* 与 /media/* 代理
          │
          ▼
      FastAPI (127.0.0.1:8000)
          ├── scrypt 密码 + 数据库 Session + HttpOnly Cookie
          ├── 角色 → 权限键，逐接口校验 + 内容所有权
          ├── Markdown、版本、定时发布、评论
          ├── 相册、照片元数据、排序、封面、EXIF
          ├── 项目（自由文本类型）、元数据与搜索
          └── SQLite + 上传目录 (backend/data)
```

浏览器只访问 `4321`，Cookie 同源，无需 CORS。公共页面由 Astro 服务端取数，后台交互使用原生 TypeScript + `fetch`。

## 快速开始

需要 Python ≥ 3.11、Node.js ≥ 22.22。

```bash
python scripts/setup.py
python scripts/run.py --dev
```

也可以手动安装：

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt   # Windows
backend/.venv/bin/python -m pip install -r backend/requirements.txt       # macOS / Linux
cd frontend && npm ci
```

打开：

- 站点：<http://127.0.0.1:4321>
- 后台：<http://127.0.0.1:4321/admin>
- API 文档：默认关闭（生产安全考虑）。本地开发可设 `BLOG_ENABLE_API_DOCS=true` 后访问 `http://127.0.0.1:4321/api/docs`。

快捷脚本：`.\start.ps1 -Dev` / `.\start.ps1`（Windows），`./start.sh --dev`（macOS / Linux）。`--dev` 会启动 Astro 开发服务器并暴露源码，只应在本机使用；默认生产模式则先构建再运行 `dist/server/entry.mjs`。

首次访问 `/admin` 会进入 `/admin/setup`，创建管理员。也可以设置 `BLOG_ADMIN_USER` / `BLOG_ADMIN_PASSWORD`，详见 `.env.example`。密码需至少 10 位，并包含小写字母、大写字母、数字、符号中的至少三类；常见弱口令会被拒绝。

演示内容默认包含 3 本相册（程序生成的色块图）、3 篇文章、4 个项目（3 个代码项目 + 1 个视频项目介绍）和一个「关于」页面，只写入一次。设置 `BLOG_SEED_DEMO=false` 从空站点开始。旧版本留下的项目数据会保留；升级到 2.2 版 Scene 时会把默认导航补上「项目」入口。

## 主题

主题名 **Scene**（2.2 重建）。

1. **场景式首页**：主视觉之后是一个三列内容区 —— 影像、项目、文字。三列等宽、各露出三条、共用同一套标题与留白，不设主次。
2. **等宽**：正文、标题、按钮与元信息都使用 Mono 字体栈。
3. **一个强调色**：默认 `#c2451f`，只用于链接、选中与编号。
4. **安静**：无字符雨、无终端配色、无渐变；靠 1px 线、留白和照片本身。

设计令牌在 `frontend/src/styles/global.css`；Scene 主题层在 `frontend/src/styles/index.css`（在 global 之后加载，覆盖公共页外壳）；Mono 字体层在 `frontend/src/styles/mono.css`。后台可改强调色、宽度、圆角、相册列数与明暗模式。

### 文案配置

后台 **外观 → 首页文案 / 场景文案 / 页面文案** 可以修改几乎所有的可见文字，包括：

- 主视觉的眉题、标题、副标题、两个按钮的文字与链接；
- 三列内容区的标题、说明、列尾链接、统计标签；
- 影像 / 项目 / 文字页的导语与空状态；
- 订阅区、搜索页、404、内容服务离线提示、页脚链接与回到顶部；
- 项目详情的字段名（类型 / 年份 / 角色 / 上下文 / 访问项目）。

所有文案的默认值在 `backend/app/defaults.py`（`copy_*` 开头的键），与当前线上外观配置保持一致；页面在值为空时会回退到内置默认，升级不会出现空白标签。

| `theme` | 画布 |
| --- | --- |
| `scene`（默认） | 米白纸张 |
| `stone` | 冷调灰白 |
| `sand` | 暖调米色 |
| `night` | 深色画布 |

### 项目

- `/projects` 是项目索引，卡片显示类型（原样文本）、年份与角色。
- `/projects/{slug}` 是项目详情：作者、类型、年份、角色、上下文、外链与正文。
- **类型是纯文本**：后台项目编辑器里直接输入，例如「代码」「影像」「字体设计」，按原文展示；没有预设或枚举限制。
- **视频项目只做介绍**：站点不上传、不嵌入视频文件；正文可以记录片长、拍摄方式、放映与制作笔记。
- 后台 **项目** 与文章共用同一个编辑器：Markdown 正文、封面、摘要、SEO、版本历史，额外提供项目信息卡片。

### 影像与相册

- `/photos` 只列相册，不再有全站照片流。
- `/galleries` 301 到 `/photos`；相册详情仍在 `/galleries/{slug}`。
- 首页主视觉使用精选相册封面，首页影像区也只展示相册卡片。
- 相册详情默认大图视图，支持 ← →、按钮、缩略图、滑动；可切网格；点图进入 Lightbox。
- 未发布相册、草稿照片与不属于相册的照片不会出现在公开页面。
- 相册页头显示作者（来自创建者/所有权成员）。

### 作者资料

- 所有成员都可以在后台 **个人资料**（`/admin/profile`）修改自己的显示名称、简介、头像与密码。
- 文章、页面、项目与相册的作者显示统一取自成员账号：名称、简介、头像都会随个人资料更新；站点设置里不再单独维护作者称呼/简介/头像。
- 拥有 `content.others` 的成员仍可在文章编辑器里转移所有权。

### 文章归档

- `/archive` 按年份分组。
- 后台 → 外观 → 文章页面可切换 **网格 / 列表**。
- 两种布局都会显示文章封面；没有设置封面时使用自动生成的文字封面。

### 编辑器

- Markdown 工具栏包含标题、列表、代码、链接、图片、音乐与分隔线。
- 点击 **♫** 打开音频对话框，从媒体库选择音频，或填写音频 URL、标题与作者。插入的是可读的 **```audio 代码块**，而不是 HTML 源码：

  ````text
  ```audio
  src: /media/2026/10/night-walk.wav
  title: Night Walk
  artist: MZTLAB
  ```
  ````

- 代码块可以直接在正文里修改地址、标题与作者；服务端渲染时（`content.py: expand_audio_blocks`）会把它转成播放器 HTML，再经过 bleach 白名单。无效地址会保留为普通代码块，不会静默丢失。
- 播放器构建在 `src/lib/audio-embed.ts`（生成代码块）与 `src/scripts/audio-player.ts`（前端增强），会把原生控件替换为 Scene 风格播放器：方形播放键、细线进度条、等宽时间与音量，同一页面同时只播放一条音频。旧文章里已存在的 HTML `<audio>` 也会自动升级。
- **预览按需请求**：停留在「编写」标签时不请求预览接口；内容未变化时（例如来回切换标签）复用上次结果；只有「预览 / 分栏」下内容真正改变才发请求。服务端对预览接口按用户限流（默认 60 次/分钟），超限会提示稍后再试。
- 媒体库同时支持图片、音频与其他文件；音频卡片可直接试听、复制链接，并会出现在音频插入对话框里。

### 上传限制

后台 **设置 → 上传与媒体** 可调整：

- **最大文件大小**（1–200MB，所有类型共用）；
- **允许的图片格式**（jpg / png / webp / gif 的子集）；
- **允许的音频格式**（mp3 / m4a / ogg / oga / wav / flac 的子集）；
- **允许的其他文件**（pdf / zip / txt / md / csv / json / docx / xlsx / pptx 的子集，留空则不接受其他文件）。

限制在服务端逐次校验，保存后立即生效；已上传的文件不受影响。媒体库页面会读取当前设置，用同样的上限与格式列表做客户端预检查（超出大小或格式未启用的文件会直接跳过并提示），服务端仍会再次校验。格式或大小填写为空/无效时会回退为全部受支持格式与默认大小，避免把自己锁在门外。`.env` 的 `BLOG_MAX_UPLOAD_MB` 仍是**首次建站**时的默认值。

**管理员例外**：`admin` 角色上传时不受上述格式与大小限制，可上传任意文件；大小仅受服务端技术上限 `BLOG_ADMIN_MAX_UPLOAD_MB`（默认 200MB）约束。可被浏览器执行的类型（html / svg / js 等）即使上传成功也只会以附件下载形式提供，并附带 sandbox CSP，避免同源脚本注入。编辑 / 作者账号仍严格遵循设置。

### EXIF

上传时读取并缓存到 `media.exif`。**EXIF 的编辑在媒体库**：图片卡片的「EXIF」按钮可补充相机、镜头、拍摄日期、焦距、光圈、快门、ISO 与等效焦距。已有值的字段为只读，不允许改写；保存只更新媒体库数据，不修改原始图像文件。

相册编辑页不再编辑 EXIF，只保留「显示 EXIF」面板，逐张勾选要公开的字段：

`相机 / 镜头 / 焦距 / 光圈 / 快门 / ISO / 拍摄时间 / 尺寸`

每行的 `EXIF` 链接会直接打开媒体库中对应图片的 EXIF 编辑器。默认全部显示；取消勾选后，该字段不会出现在相册信息、网格摘要、大图说明或 Lightbox 中。GPS 只在后台弹窗中可见。

## 内容模型

| 类型 | 表 | 说明 |
| --- | --- | --- |
| 文章 | `posts.type = 'post'` | Markdown、分类、标签、评论、定时发布、版本、所有者 |
| 项目 | `posts.type = 'project'` | Markdown、类型（自由文本）、年份、角色、上下文、外链、精选、所有者 |
| 页面 | `posts.type = 'page'` | 关于、联系等长期内容，URL 位于根目录 |
| 相册 | `galleries` | 标题、别名、描述、状态、精选、封面、所有者 |
| 照片 | `photos` | 指向 `media`，标题、说明、地点、器材、日期、排序、状态、EXIF 显示白名单 |
| 媒体 | `media` | 原图 / 音频 / 通用文件、尺寸、所有者、EXIF JSON |

### 公开路由

| 路径 | 内容 |
| --- | --- |
| `/` | 主视觉 + 场景三列（影像 / 项目 / 文字） |
| `/photos` | 相册索引 |
| `/galleries/{slug}` | 相册详情 |
| `/projects` | 项目索引 |
| `/projects/{slug}` | 项目详情（任意类型介绍） |
| `/archive` | 文章归档 |
| `/posts/{slug}` | 文章详情 |
| `/search` | 搜索内容与元数据（项目、照片、相册、文章） |
| `/{slug}` | 独立页面 |
| `/rss.xml` `/sitemap.xml` `/robots.txt` | 自动生成 |

### 相册工作流

1. 媒体库上传照片，自动读取 EXIF。
2. 影像 → 新建相册。
3. 从媒体库多选照片加入相册；自动带相机 / 镜头 / 日期。
4. 补标题、说明、地点，调整顺序与封面。
5. 设为已发布后出现在 `/photos` 与 `/galleries/{slug}`。

### 项目工作流

1. 后台 → 项目 → 新建项目。
2. 填项目信息：类型（自由文本，例如 代码 / 影像 / 字体设计）、年份、角色、上下文与可选外链。
3. 用 Markdown 写介绍。视频项目只写介绍（片长、拍摄方式、放映记录），不嵌入视频。
4. 设为已发布后出现在 `/projects` 与 `/projects/{slug}`，首页项目列取最新三条。

### 搜索

`/search` 检索四组结果，并同时匹配正文与元数据：

- **项目**：标题、正文、摘要、年份、角色、类型、上下文、作者、标签与分类；
- **照片**：标题、说明、地点、相机、镜头、拍摄时间；
- **相册**：标题、描述，以及相册内已发布照片的元数据；
- **文章**：标题、正文、摘要、SEO 描述、作者、标签与分类。

例如搜索「全栈」能找到角色为全栈的项目，搜索「35mm」能找到对应镜头拍的照片与所在相册。

## 权限

| 角色 | 说明 |
| --- | --- |
| `admin` | 全部内容、影像、评论、分类、外观、成员、导出 |
| `editor` | 默认查看并管理所有人的文章 / 相册 / 媒体，评论、分类、导出；可在设置里关闭“编辑可管理他人内容” |
| `author` | 自己的文章 / 相册 / 媒体 |

权限键：`content.read`、`content.write`、`content.publish`、`content.delete`、`content.others`、`media.manage`、`gallery.manage`、`comment.moderate`、`taxonomy.manage`、`settings.manage`、`users.manage`、`data.export`。

文章 / 页面 / 相册使用 `author_id`，媒体使用 `owner_id`。越权请求由后端返回 403。拥有 `content.others` 的成员可以在文章编辑器的“发布”面板里把文章 / 页面 / 项目的作者转移给其他成员（所有权随之转移）。

## 项目结构

```text
backend/
  app/
    main.py             FastAPI 入口、静态媒体、CSRF 头
    db.py               SQLite、设置、v6 迁移
    defaults.py         默认文案 / 导航 / 主题值（含 copy_* 文案键）
    posts.py            文章 / 项目 / 页面查询与序列化
    galleries.py        相册 / 照片 / EXIF 公开字段
    exif.py             EXIF 解析、JSON 安全化
    routes/public.py    公共读取、相册、项目、搜索、评论
    routes/admin.py     文章 / 项目 / 页面 / 设置 / 统计
    routes/gallery_admin.py
    routes/media.py
    seed.py             首次演示内容（相册 + 文章 + 项目）
  tests/
frontend/
  src/
    pages/              公共页 + admin（含 projects）
    components/         Header / Hero / ProjectCard / GalleryCard / Viewer / Lightbox
    styles/global.css   Scene 设计系统
    styles/index.css    Scene 主题层（三列内容区、项目卡片、新外壳）
    styles/mono.css     Mono 字体与代码标签层
    scripts/            原生 TS（含 admin-projects 复用的文章列表脚本）
    lib/                API、权限、EXIF、格式化
scripts/                setup / run
```

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/site` | 设置、分类、标签、计数 |
| GET | `/api/galleries` | 已发布相册 |
| GET | `/api/galleries/{slug}` | 相册详情与照片 |
| GET | `/api/posts` | 文章列表 |
| GET | `/api/posts/{slug}` | 文章详情 |
| GET | `/api/archive` | 文章归档 |
| GET | `/api/search?q=` | `articles` + `galleries` |
| POST | `/api/galleries/{id}/view` | 相册浏览数 |
| GET | `/api/projects` | 已发布项目 |
| GET | `/api/projects/{slug}` | 项目详情与相关项目 |
| GET | `/api/search?q=` | 搜索项目、照片、相册与文章（含元数据） |
| POST | `/api/posts/{id}/comments` | 提交评论 |
| GET | `/api/admin/stats` | 后台统计（需登录） |
| GET / PUT | `/api/admin/posts...` | 文章 / 项目 / 页面 |
| GET / POST | `/api/admin/galleries...` | 相册 |
| GET / POST | `/api/admin/photos...` | 相册照片 |
| GET / POST | `/api/admin/media...` | 媒体与 EXIF |
| GET / PUT | `/api/admin/settings` / `appearance` | 设置 |

## 运维

- 数据：`backend/data/blog.db` + `backend/data/uploads/`。备份整个目录即可。
- 导出：后台 → 设置 → 导出；包含文章、项目、页面、相册、照片、媒体元数据、评论、分类、标签与公开设置，不含密码哈希与媒体二进制。
- 数据库升级由 `PRAGMA user_version` 管理（当前 `SCHEMA_VERSION = 8`，定义在 `backend/app/db.py`）。迁移会在启动时幂等执行：补列（含 `project_kind`）、回填所有者与 EXIF、把旧主题值映射到 Scene、把旧的 `code` / `video` 项目类型转为「代码」/「影像」文本、把 `editor_manage_others` 旧默认改为开启，并在导航未被修改时补上「项目」。
- 测试：`cd backend && .venv/Scripts/python -m unittest discover -s tests`。
- 构建：`cd frontend && npm run check && npm run build`。

### 安全配置

- **只暴露前端端口**：FastAPI 监听 `127.0.0.1:8000`（Docker 中仅容器内网），并必须带 `--no-proxy-headers` 启动；`8000` 不要映射到公网。
- **代理密钥**：`scripts/run.py` 每次运行会随机生成 `BLOG_PROXY_SECRET` 供前后端使用；Docker 部署需在启动前设置随机值（例如 `BLOG_PROXY_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(32))")`，或写入 compose 同目录的 `.env`），后端只信任带该密钥请求中的 `x-blog-real-ip`。
- **HTTPS**：启用后设置 `BLOG_COOKIE_SECURE=true`（`BLOG_SITE_URL` 以 `https://` 开头时会自动开启），并由反向代理下发 HSTS；站点已内置 CSP、XFO、nosniff、Referrer-Policy、Permissions-Policy。
- **API 文档**：`/api/docs`、`/api/openapi.json` 默认关闭，仅在 `BLOG_ENABLE_API_DOCS=true` 时开启。
- **登录防护**：失败限流按 IP、IP+账号、账号三层计数并指数退避；登录成功会清零。会话默认 7 天，改密/停用/改角色会吊销该用户全部会话。

## FAQ

**项目类型有限制吗？**  
没有。类型是纯文本字段，直接填写「代码」「影像」「字体设计」「装置」等任意名称，按原文展示。旧数据里的 `code` / `video` 会在升级时自动转成「代码」/「影像」。视频项目只放文字介绍：站点不上传、不嵌入视频文件，也不提供站内播放器；观看链接可以放在正文或项目外链里。

**能改首页、404、搜索页这些文字吗？**  
可以。后台 → 外观 → 首页文案 / 场景文案 / 页面文案。默认值在 `backend/app/defaults.py`，清空某项会回退到内置默认。

**作者的名字 / 简介 / 头像在哪里改？**  
后台 → 个人资料（所有成员都可访问）。文章、项目和相册的作者信息都读取成员资料；站点设置里不再有单独的作者字段。

**搜索能搜到什么？**  
正文与元数据都会匹配：项目年份 / 角色 / 类型 / 上下文、照片地点 / 器材 / 拍摄时间、文章标签与作者等。

**照片能单独发布吗？**  
公开侧不能。照片必须属于已发布相册；媒体库与后台仍可单独管理文件。

**EXIF 会公开 GPS 吗？**  
不会。公开侧只展示技术参数；GPS 在后台弹窗中查看。

**可以换回浅色 / 深色吗？**  
可以。右上角切换，后台可设默认明暗模式；Mono 字体保持不变。

演示内容为虚构示例。项目未附带许可证文件，公开使用前请自行补充。
