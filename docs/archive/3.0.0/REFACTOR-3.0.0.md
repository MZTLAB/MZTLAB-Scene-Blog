> **3.0.0 历史方案文档，请勿据此开发/部署。**
>
> 适用版本：3.0.0（归档于 2026-10-23，随 3.0.0 发布归档）。现行文档见仓库根 `README.md` 与 `docs/DEVELOPMENT.md`、`docs/EDGE.md`、`docs/CSS.md`、`docs/SCHEMA.md`、`docs/API.md`、`docs/SSG-FEASIBILITY.md`。
>
> 本文是 3.0.0 发布时的重构方案、问题目录、实施计划与验收记录，保留归档原貌；发布后的变更不再回写本文。

---

# MZTLAB · Scene 3.0.0 架构重构方案

> 状态：**待评审（修订 2）**
> 目标版本：`3.0.0`（`backend/app/config.py` → `VERSION`，`frontend/package.json` → `version`）
> 部署拓扑：**平台 nginx（运维维护，仓库不提交其配置文件，只在文档中给出配置要求与参考片段）→ Astro 4321（公共页 SSR + `/admin`）/ FastAPI 8000（`/api`、`/media`）**。项目**不再内置任何反向代理层**：不引入 Caddy，不恢复 Astro 手写代理。
> 渲染：**3.0.0 公共页保持 SSR**。SSG **暂缓**，本版只做可行性分析与预留（见 §3.6 与附录 B）。
> 数据库：**`SCHEMA_VERSION = 1`**（重置编号）。**只支持空库初始化**：不考虑存量数据、不提供 2.x → 3.0.0 的迁移/导入路径、不做结构特征探测。
> 兼容性：**不向下兼容**。破坏性变更集中在本版，评审通过后冻结。
> 基线快照：本文的问题与行号均针对 2.3.0 提测快照；改造后大部分代码会被删除，本文随 3.0.0 发布归档，不作为长期维护文档。
> 关联文档：2.x 的 [`README.md`](../README.md)、[`DEVELOPMENT.md`](DEVELOPMENT.md)、[`IMAGE-PIPELINE-PLAN.md`](IMAGE-PIPELINE-PLAN.md) 归档到 `docs/archive/2.x/` 并彻底重写（见 7.3 与第 11 节待办）。

### 本次修订（相对初版）对照

| 决策 | 内容                                                                                                              | 主要影响章节                                                                    |
| ---- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| D1   | 不考虑存量数据、不向后兼容                                                                                        | 1.2、1.3、3.3.1、5、6、7、8、附录 B（原导入桥删除）                             |
| D2   | 移除 **Astro 的代理/中转角色**（Astro 前端框架本身保留），**不采用 Caddy**，仓库不提交 nginx 配置，只在文档中写明 | 3.1 全节、3.10、4（BC-11/27/28/31/32）、5 Phase 0、7.4、8、10（ADR-2/8/12）、11 |
| D3   | 移除整个评论功能                                                                                                  | 2.1（P-S1）、3.4、3.10、4（BC-35）、5 Phase 2、7、附录 B/B.3                    |
| D4   | SSG 暂缓；详细分析框架主体迁移 SSG 的可行性；本版开发做预留                                                       | 0.3、3.6、3.7、5 Phase 4、6.2、附录 B                                           |
| D5   | 存量图像除非手动触发，否则不重编码                                                                                | 3.7.1、3.7.3、4（BC-34/37）、5 Phase 3、8、10（ADR-10）                         |

> D2 的范围已明确：**只移除 Astro 在请求链路中的代理/中转角色**（删除 `pages/api/[...path].ts`、`pages/media/[...path].ts`、`lib/proxy.ts`），**Astro 作为前端框架与 SSR 运行体完整保留**（公共页、`/admin`、`/_astro` 资产继续由它提供），后续 SSG 预留（附录 B）也以 Astro 的预渲染能力为目标。不引入 Caddy，接入层只保留一层由运维维护的 nginx。

---

## 目录

- [0. 摘要](#0-摘要)
- [1. 版本策略与兼容性契约](#1-版本策略与兼容性契约)
- [2. 问题目录](#2-问题目录)
- [3. 目标架构](#3-目标架构)
- [4. 破坏性变更清单](#4-破坏性变更清单)
- [5. 实施计划](#5-实施计划)
- [6. 验收标准](#6-验收标准)
- [7. 需要删除的代码](#7-需要删除的代码)
- [8. 风险与回滚](#8-风险与回滚)
- [9. 成功度量](#9-成功度量)
- [10. 决策记录（ADR 摘要）](#10-决策记录adr-摘要)
- [11. 待办事项（Backlog）](#11-待办事项backlog)
- [附录 A：术语表](#附录-a术语表)
- [附录 B：SSG 迁移可行性评估与 3.0.0 预留](#附录-bssg-迁移可行性评估与-300-预留)

---

## 0. 摘要

### 0.1 一句话结论

2.x 的功能与领域切分是合格的，但它把大量复杂度花在了 **“用文档和启动脚本代替类型、测试与迁移机制”** 上：配置是一张 142 键的无 schema KV 表，跨端契约靠手写镜像，读路径全动态重算，历史债务靠每次启动的迁移函数消化。

3.0.0 的目标不是加功能，而是**删掉这几层负债**，用一次不兼容的破坏换取之后每个需求只改一处。与初版方案相比，本版进一步**缩小爆炸半径**：不引入第二层边缘（不采用 Caddy）、不迁移存量数据、不启用 SSG、移除评论——把“重构”和“新增运行形态”拆开。

### 0.2 三个根因

| 编号 | 根因                               | 表现                                                                                | 3.0.0 处置                                                                                               |
| ---- | ---------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| R1   | **配置系统没有 schema**            | 142 个设置键、31 分支 if/elif 校验、默认值存在三份、迁移靠“值等于旧默认才覆盖”      | 用 Pydantic 分组模型统一读写，密钥移出数据库，前端类型由后端生成                                         |
| R2   | **跨端契约靠人肉同步**             | 响应无 `response_model`、`types.ts` 手写、权限矩阵两份、默认值三份、文档 4 天即漂移 | OpenAPI 作为唯一契约，`openapi-typescript` 生成前端类型，CI 检查漂移                                     |
| R3   | **读路径没有缓存、写路径没有事务** | 公共页全量 SSR + 每页 1+N 次进程内 HTTP；删除媒体跨存储无事务；每请求写 sessions    | 页面对接单一聚合数据接口 + ETag/短缓存（**不做 SSG**，见附录 B）；跨存储操作引入补偿流程；去掉读请求写库 |

### 0.3 预期收益（量化目标）

| 指标                     | 2.3.0                                 | 3.0.0 目标                                                                            |
| ------------------------ | ------------------------------------- | ------------------------------------------------------------------------------------- |
| 公共页渲染               | 每次请求 SSR + 最多 4 次后端往返      | 仍为 SSR，但每页 **1 次聚合请求** + ETag/`Cache-Control`（SSG 预留见附录 B）          |
| 评论功能                 | 表/接口/审核/反垃圾/文案/前后台十余处 | **整体移除**（0 维护面、0 攻击面）                                                    |
| 设置项新增成本           | 6 处改动                              | 1 处（模型定义）                                                                      |
| 新增一个后台字段的改动点 | 5~7 处                                | 2~3 处（模型 + 模板；结构变更另有 SQL 文件）                                          |
| 后端 HTTP 集成测试       | 0                                     | 覆盖全部鉴权/所有权/上传/写入路径                                                     |
| Python 静态检查          | 无                                    | `ruff` + `mypy --strict`（新代码；存量代码用渐进清单）                                |
| CSS 行数                 | 9,985（实测 8,466）                   | **已完成收口**：65 个分层样式文件（9,726 行含 banner；0 个 >400 行），见 3.9 状态更新 |
| 迁移函数数量             | 13                                    | 0（无存量迁移；结构变更走版本化 SQL + 显式执行）                                      |
| 存量图像自动重编码       | 改配置即全站失效                      | **0**（只有手动触发 `reencode` 任务才会重编码）                                       |

### 0.4 工作量估算

约 **19~25 人日**（单人，含测试与文档）。相对初版（20~28）的差异：省掉双层边缘联调（约 2~3）、2.x 导入桥（约 1~2）、SSG 落地（约 3~4）；新增评论功能移除（约 1~2）、SSG 可行性分析与预留（约 2~3）、nginx 接入文档（约 0.5）。附录 B 的**未来 SSG 落地**另计 5~8 人日（不在本版预算内）。

可分 6 个阶段交付，每个阶段结束时站点都应可运行。

### 0.5 本期范围决策（相对初版方案的变更索引）

1. **移除浏览量功能**（BC-18）：删除 `view_count` 列、两个 view 接口、后台统计与前台展示。
2. **AVIF 质量改为全局默认且不可变**（BC-34）：删除每图 `avif_quality` / `avif_quality_auto` 与相关 UI/API，质量由 `PIPELINE_DEFAULTS` 决定。
3. **移除整个评论功能**（BC-35）：删除 `comments` 表、公开提交接口、后台审核页、`comments_enabled` / `comment_moderation` / `copy_comments_*` 设置、前台评论区组件与样式、导出字段。评论的内容治理（审核、反垃圾、通知、IP 记录）由外部系统承担，本版不再内置。
4. **不采用 Caddy，仓库不提供 nginx 配置文件**（BC-11 / BC-27）：只保留一层由运维维护的 nginx；项目侧删除 Astro 代理路由，生产路由由 nginx 承担、行为写进 `docs/EDGE.md`；本地开发用 Vite `server.proxy` 维持同源（仅 dev 生效）。
5. **SSG 暂缓**（BC-33 转为决策记录）：公共页 3.0.0 保持 SSR；本版完成“框架主体迁移 SSG”的可行性评估（附录 B）并落地 7 项预留，不实现构建/发布管道。
6. **不考虑存量数据**（BC-02）：不接受 2.x 数据库，不提供导入桥；3.0.0 只支持空库初始化；演示内容改为显式 opt-in。
7. **存量图像不自动重编码**（BC-34/37）：派生图 URL 由已存在的派生记录寻址；`PIPELINE_VERSION` / 编码参数变化只影响新上传，存量图沿用旧产物，直到手动执行 `reencode` 任务。

---

## 1. 版本策略与兼容性契约

### 1.1 语义化版本

3.0.0 是**首个明确声明破坏性变更**的版本。此后遵循 SemVer：

- **主版本**：删除/重命名公开 API、数据库结构不兼容、配置键不兼容、移除功能。
- **次版本**：新增 API/页面/设置项，向后兼容。
- **补丁**：修复与内部重构，无行为变化。

2.x 到 3.0.0 的所有破坏集中在第 4 节，评审通过后冻结，不再追加。

### 1.2 数据策略（无迁移、无导入）

**不考虑存量数据，也不提供任何升级桥。** 具体规则：

1. 启动时检查 `PRAGMA user_version`：必须为 `1`；否则**直接启动失败**并提示“3.0.0 只支持空库初始化，请清空 `BLOG_DATA_DIR` 后重启”。不做结构特征探测、不做自动迁移、不做数据修补。
2. 不提供 `import_2x_export`、不提供设置迁移脚本、不支持读取 2.x 导出的 JSON，也不保留 2.x 导出格式解析器。
3. 媒体目录不再是需要迁移的资产：3.0.0 从空库、空 `uploads/` 开始（本地/演示可用 `BLOG_SEED_DEMO=true` 播种）。
4. 3.0.0 首次启动只做两件事：建表（`CREATE TABLE IF NOT EXISTS`）、写入默认设置（幂等 `INSERT OR IGNORE`）。
5. **演示内容改为显式 opt-in**：`BLOG_SEED_DEMO` 默认 `false`；`docker-compose.yml` 显式设为 `false`，本地开发脚本显式设为 `true`。删除“旧库补种 / `DEMO_SEED_VERSION`”逻辑（BC-36）。

> 为什么可以直接放弃兼容：本版评审已确认当前没有需要保护的生产数据（D1）。若将来出现需要保留的实例，应通过 3.x 自身的导出/导入能力（BC-29）完成，而不是复活 2.x 迁移函数。

### 1.3 不保留的兼容层（直接删除）

- 所有 `_migrate_*` 函数、`_ADDED_COLUMNS`、`_ensure_columns`、`LEGACY_DEFAULTS`、`LEGACY_PALETTES`、`SCENE_V1_COPY`、`SCENE_V2_COPY`、`SCENE_V2_NAV`、`SCENE_INDEX_COPY`。
- 主题别名（`paper` / `graphite` / `forest` / `ocean` / `editorial`）与 `data-theme` 第二套机制。
- 旧 localStorage 键 `ink-color-mode`（只保留 `scene-color-mode`）。
- `/galleries` → `/photos` 的 301 路由（3.0.0 直接不存在该路径）。
- 旧设置键（`author_name` / `author_bio` / `author_avatar` / `home_*` 系列 / `project_kind` 的 `code|video` 枚举值 / `comments_enabled` / `comment_moderation` / `copy_comments_*`）。
- `BLOG_PROXY_SECRET` / `x-blog-proxy-secret` / `x-blog-real-ip` 信任链（由单层 nginx 的 XFF 覆盖写 + 后端 `--forwarded-allow-ips` 取代）。
- 开发期 CJS 桥接文件 `picomatch-esm.mjs` / `yaml-esm.mjs` / `eventemitter3-esm.mjs`：3.0.0 要求升级或固定 Astro/Vite 版本并验证 `npm run dev` 不再触发该问题，确认后删除；若无法规避，改为 Vite `ssr.noExternal` 配置而非散落源码 shim。
- 任何“为兼容旧库而保留”的分支、哨兵值（如 `avif_quality = 0` 表示自动）与注释掉的旧代码。

---

## 2. 问题目录

### 2.1 总表

级别：**P0** 数据/安全/可用性缺陷；**P1** 结构性债务；**P2** 卫生问题。

| 编号 | 子系统   | 问题                                                                                                                 | 级别 |
| ---- | -------- | -------------------------------------------------------------------------------------------------------------------- | ---- |
| P-A1 | 运行时   | 用 98 行 TS 手写反向代理，重实现 hop-by-hop/Set-Cookie/超时/IP 信任                                                  | P1   |
| P-A2 | 运行时   | 上传 body 在 Astro 与 FastAPI 各整块缓冲一次（200MB 级双份内存）                                                     | P1   |
| P-A3 | 运行时   | 公共页每页 1+N 次进程内 HTTP + JSON 往返，无聚合、无缓存                                                             | P1   |
| P-A4 | 运行时   | 安全响应头在三处重复定义，改一处会漏                                                                                 | P2   |
| P-B1 | 配置     | 142 键无 schema，校验是 31 分支 if/elif                                                                              | P1   |
| P-B2 | 配置     | 默认值存在三份（`defaults.py` / `config.ts` / `types.ts`），强调色已出现 4 个不同值                                  | P0   |
| P-B3 | 配置     | 密钥与文案同表，靠手工 mask 与手工 private 键集合                                                                    | P1   |
| P-B4 | 配置     | `/api/site` 每请求全量返回 142 键（含 60KB `custom_css`、30KB `head_html`）                                          | P2   |
| P-C1 | 数据层   | 13 个 schema 版本中 4 个仅挪动 AVIF 质量默认值；版本号被当设置变更日志                                               | P1   |
| P-C2 | 数据层   | 迁移函数每次启动运行，部分无版本守卫，重渲染演示数据                                                                 | P1   |
| P-C3 | 数据层   | 生产启动逻辑依赖演示 fixtures（`_migrate_scene_demo_project` ← `seed.PROJECTS`）                                     | P1   |
| P-C4 | 数据层   | 跨存储删除无事务边界；一个请求多次开连接/提交                                                                        | P1   |
| P-D1 | 认证     | 登录退避用 `time.sleep`（最多 3s）阻塞线程池，40 并发失败登录即可打满                                                | P0   |
| P-D2 | 认证     | 限流器为进程内内存，多 worker 静默失效，无启动检查                                                                   | P1   |
| P-D3 | 认证     | 每个带会话请求都 `UPDATE sessions`，读请求写库并争抢 WAL 写锁                                                        | P1   |
| P-D4 | 认证     | `is_blocked()` + `record()` 非原子，并发可越限                                                                       | P2   |
| P-E1 | 授权     | 所有权检查存在三份实现，403 文案与判定入口不一致                                                                     | P1   |
| P-E2 | 授权     | 权限矩阵前端手写镜像，靠注释“必须同步”                                                                               | P1   |
| P-E3 | 授权     | 77 个路由的权限散落，无“路由 → 权限”可审计清单                                                                       | P2   |
| P-F1 | 内容     | `serialize_post` 与 `_list_item` 两份字段映射，已可漂移                                                              | P0   |
| P-F2 | 内容     | 详情读路径重跑图片改写 + 每图重算 token；列表页对全文跑正则算阅读时长                                                | P1   |
| P-F3 | 内容     | 单表继承无任何数据库约束，类型行为全靠代码分支                                                                       | P1   |
| P-F4 | 内容     | `_post_request` 返回无类型 dict，`user_id` 实为作者 id                                                               | P2   |
| P-F5 | 内容     | 用 `assert` 做控制流；bleach 后用正则补 `rel`/`target`                                                               | P2   |
| P-G1 | 影像     | `PhotoUpdateIn` 是伪部分更新：漏传 `gallery_id` 会把照片移出相册                                                     | P0   |
| P-G2 | 影像     | 相册详情把照片查询与序列化做两遍                                                                                     | P1   |
| P-G3 | 影像     | EXIF 有四个真相层（media / photos 快照 / exif_fields / 前端再过滤）                                                  | P1   |
| P-G4 | 影像     | 媒体删除后照片保留 filename 快照，前台回退 URL 必然 404                                                              | P2   |
| P-H1 | 媒体     | 唯一 `async def` 路由承载 200MB 读 + Pillow 解码 + EXIF + 取色，阻塞事件循环                                         | P0   |
| P-H2 | 媒体     | “可执行文件降级为下载”只在上传后的服务层实现，新出口可绕过                                                           | P1   |
| P-H3 | 媒体     | 上传策略校验存在三处，空值回退语义不一致                                                                             | P1   |
| P-H4 | 媒体     | 后台任务状态是进程内全局字典，无持久化/无 job id/不可取消                                                            | P2   |
| P-I1 | 图片管线 | token 包含全局配置，改一次质量滑块即全站 URL 失效并全量重编码                                                        | P1   |
| P-I2 | 图片管线 | 每图最多约 21 次编码；缺图时在请求线程同步编码（6K full 可阻塞数十秒）                                               | P1   |
| P-I3 | 图片管线 | 旧 token 产物变孤儿，只能手动 `prune_derivatives.py` 清理                                                            | P1   |
| P-I4 | 图片管线 | 编码参数硬编码；3.0.0 起改为有意的不可变全局默认（ADR-10）                                                           | P2   |
| P-J1 | 存储     | `Storage` Protocol 泄漏：`local_path()` 对 S3 返回 None、`stream()` 对本地抛错                                       | P1   |
| P-J2 | 存储     | 媒体永久公开，`allow_download` 只隐藏入口，命名让人误以为是访问控制                                                  | P1   |
| P-J3 | 存储     | 无公网域名时每张图一次 302 预签名，浏览器多一次 RTT                                                                  | P2   |
| P-K1 | 公共读   | 浏览量裸自增且可被刷；3.0.0 直接移除该功能（BC-18）                                                                  | P1   |
| P-K2 | 公共读   | 搜索为 11 个 `LIKE '%…%'` 全表扫描，无 FTS、无分词                                                                   | P1   |
| P-K3 | 公共读   | `/api/site` 每请求重算 taxonomy 计数与媒体计数                                                                       | P2   |
| P-L1 | 后台 API | 路由即服务层即仓储层：1,125 行承担 7 类业务                                                                          | P1   |
| P-L2 | 后台 API | `update_settings` 是手写类型系统（31 分支）                                                                          | P1   |
| P-L3 | 后台 API | 导出单向，无导入                                                                                                     | P1   |
| P-M1 | 前端渲染 | 全站 `output: 'server'`，博客却无渲染缓存；SSG 暂缓，本版只做预留（附录 B）                                          | P1   |
| P-M2 | 前端渲染 | 布局令牌归一化逻辑在两个 Layout 逐行重复                                                                             | P1   |
| P-M3 | 前端渲染 | 页面把后端错误吞成 200 并展示“离线”，SEO/监控失真                                                                    | P2   |
| P-N1 | 前端交互 | 15 个后台脚本各写一套 DOM/状态/错误处理                                                                              | P1   |
| P-N2 | 前端交互 | 字符串拼 HTML + `innerHTML`，XSS 依赖逐个调用 `escapeHtml`                                                           | P1   |
| P-O1 | 样式     | CSS 9,985 行（实测 8,466），为全仓最大模块；三层覆盖式主题无隔离                                                     | P1   |
| P-O2 | 样式     | 默认强调色 4 处不一致；两套主题机制并存                                                                              | P2   |
| P-P1 | 契约     | 响应无 `response_model`，OpenAPI 关闭，前端类型手写，契约不可验证                                                    | P0   |
| P-P2 | 契约     | 错误体为 `{detail: 中文}`，UI 文案与 API 耦合                                                                        | P2   |
| P-Q1 | 部署     | compose 硬编码 `BLOG_COOKIE_SECURE=false`，无 TLS/备份/日志/前端健康检查                                             | P1   |
| P-Q2 | 部署     | 图片预热/清理/迁移/同步有 CLI 与后台按钮两套入口                                                                     | P1   |
| P-R1 | 测试     | 85 个单测全为纯函数，且直接 import 私有函数；无 HTTP 集成测试                                                        | P1   |
| P-R2 | 测试     | 无 CI、无 ruff/mypy/eslint，Python 侧零静态检查                                                                      | P1   |
| P-R3 | 文档     | 文档已漂移（schema 8 vs 13、2.2 vs 2.3、StaticFiles 已不存在、PRIVATE 键数量不符）                                   | P1   |
| P-S1 | 评论     | 评论功能维护面大（表/公开提交/审核/反垃圾/IP 记录/文案/前后台 UI/导出），与站点定位不成比例；3.0.0 整体移除（BC-35） | P1   |

### 2.2 分域详述

#### A. 运行时与代理

**现状**：浏览器 → Astro 4321 → 手写代理 → FastAPI 8000；后端靠 `BLOG_PROXY_SECRET` 决定是否信任 `x-blog-real-ip`。

**问题**

- `P-A1` `frontend/src/lib/proxy.ts` 用 98 行重新实现反向代理：手动过滤 hop-by-hop 头、手动逐条转发 `Set-Cookie`、手动 20s 超时、手动删除客户端伪造的转发头。这些能力属于接入层，不属于业务代码。
- `P-A2` `proxy.ts:59-62` 把 body 整块读成 `ArrayBuffer`；`routes/media.py:319` 又整块读入 FastAPI。管理员上限 200MB 时，两个进程各占一份。
- `P-A3` 首页 SSR 需要 4 次进程内 HTTP（`site` / `galleries` / `projects` / `posts`），后台每页 3~6 次；每个 `/api/*` 响应都是 `no-store`。
- `P-A4` 安全响应头在 `main.py:78-87`、`middleware.ts:11-35`、`media_serve.py:80-86` 三处定义；CSP 有两份，改一处会漏。

**3.0.0 处置**：删除 Astro 手写代理与 `BLOG_PROXY_SECRET` 信任链；**不引入 Caddy**；生产由运维 nginx 承担路由（配置要求文档化，仓库不提交该文件，见 3.1）；应用侧每个进程只为自己产出的响应设置安全头（页面 / API / 媒体三类各自一处，共享常量）；本地开发用 Vite `server.proxy` 维持同源（仅 dev 生效，见 3.1.5）。

#### B. 配置系统

**现状**：`settings(key TEXT PRIMARY KEY, value JSON)`，142 键，默认值在 `defaults.py`，写入校验在 `admin.py` 的 if/elif，前端另有 `fallbackSite` 与 `types.ts`。

**问题**

- `P-B1` 新增一个设置项要同步 6 处：`defaults.py` → `update_settings` 白名单/校验 → `types.ts` → `config.ts(fallbackSite)` → 后台表单 `data-setting` → 文档。项目自己的计划文档（`IMAGE-PIPELINE-PLAN.md:42`）就承认了这条链路。
- `P-B2` 默认值三份且已漂移：强调色在 `defaults.py` 为 `#c2451f`、`global.css` 为 `#e8481d`、`BaseLayout.astro:46` 兜底为 `#e8481d`、`config.ts` 为 `#c2451f`。**已修复**：3.0.0 样式收口后 CSS 兜底统一为 `#c2451f`，`global.css` 已删除。
- `P-B3` `storage_s3_secret_key` 与主题文案同表；靠 `SECRET_SETTING_KEYS` 做响应 mask、靠 `PRIVATE_SETTING_KEYS` 做公开过滤。当前过滤正确，但每加一个敏感键都要记得加入两个集合。
- `P-B4` `/api/site` 每请求 `load_settings()`（无缓存）并返回全部公开键，包含 60KB `custom_css` 与 30KB `head_html`。

**3.0.0 处置**：见 3.2。分组 Pydantic 模型 + 分组存储 + 密钥只走环境变量 + 生成前端类型 + 一个聚合的 `SiteBootstrap` 响应只含渲染必需字段。

#### C. 数据层与迁移

**现状**：`db.py`，`SCHEMA_VERSION = 13`，13 个 `_migrate_*` 函数，每次启动 `executescript(SCHEMA)` + `_ensure_columns` + 默认设置 + 迁移。

**问题**

- `P-C1` v10/v11/v12/v13 四个版本只做同一件事：把 AVIF 质量默认值 62→72→90→75→70 挪动。schema 版本号被当成“设置默认值变更日志”。
- `P-C2` 迁移函数形态不一：`_migrate_scene_wording`、`_migrate_scene_demo_project` 每次启动都执行；后者每次启动重新 `render_markdown` 演示项目。
- `P-C3` `_migrate_scene_demo_project` 从 `seed.PROJECTS` 读取内容 → 生产启动路径依赖演示 fixtures。
- `P-C4` `delete_media` 先删派生文件、再删原图、最后删行（`media.py:820-827`）；`delete_derivatives` 先删行再删文件。崩溃窗口内状态不一致。一个请求内多次 `with db()` 也意味着多次提交。

**3.0.0 处置**：见 3.3。schema 重置为 1，删除全部迁移函数与演示补种；结构变更改为“版本化 SQL 文件 + 显式执行”；跨存储删除改为“先标记删除 → 后台 GC → 最后删行”的补偿式流程。

#### D. 认证、会话与限流

**现状**：scrypt + DB session + HttpOnly Cookie；三层登录限流 + 指数退避；预览/上传限流为内存实现。

**问题**

- `P-D1` `auth.py:105` 在同步路由里 `time.sleep(delay)`，`security.py:249` 最多 3 秒。FastAPI 同步路由跑在约 40 线程的池里，40 个并发失败登录即可占满线程池，全站 API 停摆。这是**可被远程触发的拒绝服务**。
- `P-D2` `RateLimiter` 是进程内内存（`security.py:164-172` 自述），`--workers 2` 后限流额度翻倍，没有任何启动检查或测试会提醒。
- `P-D3` `deps.py:103-106` 对每个有效会话执行 `UPDATE sessions SET user_agent` → 每个后台 GET 都写库并争抢 SQLite 唯一写锁。
- `P-D4` 登录用 `is_blocked()` 再 `record()`，两个锁区间之间可并发越限。

**3.0.0 处置**：**限流仍然是应用层的安全能力**（因为接入层配置由运维掌握、仓库无法验证，不能把安全押在“nginx 一定配了”上）。`time.sleep` 退避删除，超限直接 `429 + Retry-After`；限流器抽成 `RateLimitStore` 接口，默认内存实现，启动时若检测到多 worker 直接拒绝启动；nginx 的 `limit_req` 作为**可选加固**写入接入文档（见 3.1.3）。会话 `user_agent` 只在登录与会话续期时更新；登录限流改用原子 `allow()` 变体（失败计数用“成功后 reset”补偿）。

> 由 P-A1 删除带来的直接收益：登录退避的线程池 DoS 攻击面从“任何能发 HTTP 的人”缩小为“能直连后端的人”（后端只监听内网/回环）。

#### E. 授权与所有权

**现状**：`permissions.py`（12 键 / 3 角色 / `owns()`），各路由自写所有权检查。

**问题**

- `P-E1` 三份实现：`admin._assert_can_edit`、`media._ensure_owner`、`gallery_admin._ensure_owner` + `_ensure_photo_owner`。403 文案不同，判定入口不同。改规则要改三处。
- `P-E2` `frontend/src/lib/permissions.ts` 复制了角色矩阵，注释要求“必须两边同步”。
- `P-E3` 77 个路由的 `Depends(require_permission(...))` 分散，没有可审计清单，无法自动验证“是否每个 admin 路由都挂了权限”。

**3.0.0 处置**：单一 `authorize()` 服务 + 路由权限注册表（见 3.10.2）。所有权模型收敛为“资源表统一 `owner_id` 列”（见 3.3.3），`owns()` 不再猜 key。

#### F. 内容域（文章 / 项目 / 页面 + Markdown）

**现状**：单表继承（`posts.type`），`content_html` 写入时物化，`PUBLIC_CONDITION` 统一公开条件。

**问题**

- `P-F1` `serialize_post`（`posts.py:112`）与 `_list_item`（`posts.py:201`）是两份字段清单，重复约 40 行，字段已不完全一致。
- `P-F2` 详情每次请求重跑 `rewrite_inline_images`（正则 + 每图查库 + 重算 token）；列表页对每篇全文跑 `strip_markdown` 算阅读时长（`posts.py:216`）。写时物化的收益被读时再加工抵消。
- `P-F3` 单表继承没有任何数据库约束：page 可以带 `project_year`；`_post_request` 用 `if is_page / is_project` 清零；API 用 `POST /api/admin/posts?type=project` 表达三种资源。
- `P-F4` `_post_request` 返回无类型 dict，`"user_id"` 实际是 author id，更新时还被忽略。
- `P-F5` `admin.py:439/486/561` 用 `assert` 做控制流（`python -O` 会去掉）；bleach 清洗后用正则补 `rel`/`target`。

**3.0.0 处置**：见 3.4。类表继承（`posts` + `project_details`）+ CHECK 约束 + 每类型独立 router + 渲染版本号（见 3.4.3）。评论功能移除后，`posts.allow_comments` 列一并删除。

#### G. 影像域（相册 / 照片 / EXIF）

**问题**

- `P-G1` **数据缺陷**：`PhotoUpdateIn.gallery_id` 默认 `None`，SQL 直接覆盖（`gallery_admin.py:403-426`），只有 `allow_download`/`sort_order`/`exif_fields` 用 `COALESCE` 保留。任何漏传 `gallery_id` 的 PUT 都会把照片移出相册 → 前台立即消失。当前 UI 每次都传（`admin-gallery-detail.ts:145-148`），所以是潜伏缺陷。
- `P-G2` `gallery_dict(detail=True)` 已查照片并构建 `photos`（`galleries.py:176-185`），`public.py:260-271` 又查一遍、再构建一遍。
- `P-G3` EXIF 四层真相：`media.exif` → `photos.camera/lens/taken_at` 快照 → `photos.exif_fields` 白名单 → 前端 `lib/photo.ts` 再过滤。优先级只写在注释里。
- `P-G4` 媒体删除后照片保留 `filename` 快照，`image_payload` 返回 None，前端回退 `/media/{filename}` 必 404。

**3.0.0 处置**：更新接口改 PATCH 语义（未提供的字段保留，清空需显式 `null`）；相册详情只构建一次；EXIF 收敛为“媒体单一来源 + 照片只存展示白名单与覆盖值”，前端不再二次过滤（白名单由后端投影成 `exif_public`）。

#### H. 媒体上传与媒体库

**问题**

- `P-H1` `routes/media.py:307` 是全仓唯一 `async def` 路由，却做整文件读入 + Pillow `verify()` + 二次解码算尺寸 + EXIF + 取主色，全部在事件循环上 → 上传期间全站 API 假死。
- `P-H2` 可执行扩展名（html/svg/js…）的 `attachment` 降级只在 `media_serve.py:44-48` 生效。配置对象存储直链后，该规则被绕过。
- `P-H3` 上传策略校验三处：`media._upload_policy()`（运行时）、`admin._sanitize_upload_formats()`（保存时）、`defaults.UPLOAD_*_FORMATS`（目录），对“空值”的解释不同。
- `P-H4` `_OPTIMIZE_STATE` / `_SYNC_STATE` 为进程内全局字典，无持久化、无 job id、不可取消。

**3.0.0 处置**：见 3.7。流式落盘 + 同步 handler；上传策略只保留一份（模型校验）；后台任务改 `jobs` 表 + 单 worker（见 3.7.3）；可执行类型在上传入库时即标记 `force_download=1`，由数据而非路由保证。

#### I. 图片派生管线

**问题**

- `P-I1` `variants_hash` 把全局配置（宽度阶梯、7 个场景质量、格式集合、WebP/JPEG 质量）纳入 token（`images.py:199-222`）。改一次质量 → 全站 URL 变化 → 浏览器/CDN 缓存全废 + 全量重编码。
- `P-I2` 每图最多约 21 个编码任务（7 场景 × 1~2 宽度 × 3 格式）；缺失变体在请求线程内同步生成，6K 全尺寸 AVIF 可阻塞数十秒。
- `P-I3` `media_derivatives` 的 `UNIQUE(media_id, scene, width, format)` 在 token 变化时覆盖行，旧文件成为无主孤儿，只能靠手动 `scripts/prune_derivatives.py`。
- `P-I4` 编码参数硬编码（4:4:4、WebP `method=4`、JPEG progressive），仅 AVIF speed 可配。3.0.0 起这是**有意为之**：质量与编码参数成为代码内不可变常量（ADR-10），调优等于改代码 + 升 `PIPELINE_VERSION`，且**不会自动重编码存量图像**（决策 D5）。

**3.0.0 处置**：见 3.7.1。删除每图 `avif_quality` / `avif_quality_auto` 与单图覆盖 UI/API；质量来自 `PIPELINE_DEFAULTS` 常量；派生图 URL 由**已存在的派生记录**寻址，而不是每次读路径用全局配置重算 token；旧产物继续可用，清理交给 GC；只有手动触发 `reencode` 任务才会产生新产物。

#### J. 存储与媒体服务

**问题**

- `P-J1` `Storage` Protocol 泄漏：`local_path()` 对 S3 返回 `None`、`stream()` 对本地抛错，调用方必须分支（`media_serve.py:90-115`）。
- `P-J2` 媒体 URL 永久公开，`allow_download` 只隐藏入口按钮——命名让人误以为是访问控制。
- `P-J3` 无公网域名时每张图一次 302 预签名，浏览器多一次往返。

**3.0.0 处置**：拆成 `ReadableStorage` / `WritableStorage` 两个窄接口（或保留一个但去掉 `local_path`，媒体服务只经 `stream()` + `size()`）；`allow_download` 改名为 `hide_download_link` 以消除误导；直链与代理由“启动时探测 + 单次判定”决定，不在每张图上 302。

#### K. 公共读 API

**问题**

- `P-K1` 浏览量 `view_count + 1` 无任何去重（`public.py:412-428`），且用 POST 触发但语义是 GET 副作用。**该功能在 3.0.0 中整体移除**。
- `P-K2` 搜索 11 个 `LIKE '%…%'` + 相关子查询全表扫描；无 FTS5、无分词。
- `P-K3` `/api/site` 每请求重算分类/标签计数、公开照片/相册计数。

**3.0.0 处置**：删除 `posts.view_count` / `galleries.view_count` 列、两个 view 接口、后台 `top_posts` 与总浏览量统计、前台展示（`show_views` 设置一并删除）；删除公开评论提交接口与评论读取（BC-35）；搜索改用 SQLite FTS5 虚表（`content_fts`）并在写入时同步；`/api/site` 拆分：`/api/bootstrap`（渲染必需，可缓存）与 `/api/site`（管理用）。

#### L. 后台 API 组织

**问题**

- `P-L1` `routes/admin.py` 1,125 行同时承担统计、文章、评论、分类、设置、外观、个人资料、导出；SQL、校验、授权、序列化全在一个函数里。
- `P-L2` `update_settings` 31 分支手写类型系统。
- `P-L3` 导出单向，无导入（保留为 3.x 自用备份/恢复能力，不提供 2.x 导入，见 3.3.1）。

**3.0.0 处置**：按资源拆 router（`posts.py` / `projects.py` / `pages.py` / `taxonomy.py` / `settings.py` / `profile.py` / `export.py`；评论 router 随功能删除）；服务逻辑下沉到 `app/services/`；导出格式升到 v3，仅用于 3.x 备份/恢复。

#### M. 前端渲染层

**问题**

- `P-M1` 全站 `output: 'server'`，无 `prerender`、无 HTML 缓存头；博客内容只在保存时变化，却每次全量重算。**SSG 本版暂缓**（D4），只做可行性与预留。
- `P-M2` `BaseLayout.astro:46-75` 与 `AdminLayout.astro:30-48` 的令牌归一化（accent 校验、width clamp、palette 别名、font 回退）几乎逐行重复；`copy()` helper 在多个页面重复定义。
- `P-M3` 页面把后端错误吞成 200 并渲染“内容服务离线”（`index.astro:29-31`），监控与 SEO 看不到 5xx。

**3.0.0 处置**：公共页保持 SSR，但改为“单一聚合数据入口 + ETag/短缓存头”（见 3.6）；令牌归一化抽到 `lib/theme.ts` 单处；错误页返回真实状态码（构建失败/后端不可用不再渲染半成品 200）；SSG 预留见附录 B。

#### N. 前端交互层

**问题**

- `P-N1` 15 个 `admin-*.ts` 各自实现 DOM 渲染、loading、空状态、错误 toast、表单绑定。
- `P-N2` 字符串拼 HTML + `innerHTML`，转义完全依赖逐个调用 `escapeHtml`（`admin-client.ts:3`），漏一处即存储型 XSS。

**3.0.0 处置**：见 3.8。短期抽公共 `dom.ts`/`form.ts` 并用“自动转义的模板函数”替代裸 `innerHTML`；中期把三个复杂页面（文章编辑器、媒体库、相册详情）改成岛屿组件（排在 3.0.0 之后）。

#### O. 样式系统

**问题**

- `P-O1` 9,985 行 CSS（实测 8,466）是全仓最大模块；`global.css` → `mono.css` → `index.css` 靠 import 顺序互相覆盖；`admin.css` 单文件 3,654 行。
- `P-O2` 强调色 4 个不同默认值；`data-theme="scene"` 硬编码与 `data-palette` 两套主题机制并存。

**3.0.0 处置**：样式收口已在 3.0.0 中补齐实施（见 3.9 状态更新）：旧五张表拆成 65 个 `@layer` 文件、后台拆到 `admin/*.css`、`data-theme="scene"` 覆盖层删除、强调色兜底统一为 `#c2451f`。

#### P. 契约与类型

**问题**

- `P-P1` 响应没有 `response_model`，OpenAPI 在生产关闭，前端 `types.ts` 手写 536 行，默认值再手写一份。契约没有任何自动校验点，2.x 的四类漂移都是它的后果。
- `P-P2` 错误体 `{detail: "中文"}`，前端直接展示。

**3.0.0 处置**：见 3.5。全量 `response_model` + 构建期导出 `openapi.json` + `openapi-typescript` 生成 `api.types.ts` + CI diff 检查；错误体改 `{error:{code,message,field?}}`。

#### Q. 构建、部署与运维

**问题**

- `P-Q1` `docker-compose.yml:16` 硬编码 `BLOG_COOKIE_SECURE: "false"`；无 TLS/反代说明、无备份策略、无日志、前端无 healthcheck。
- `P-Q2` 预热/清理/迁移/同步有 CLI 与后台按钮两套入口，`prune_derivatives` 只有 CLI。

**3.0.0 处置**：见 3.1 / 3.7.3。compose 保持两个服务（backend + frontend），去掉不安全默认（Cookie Secure 由 `SITE_URL` 推导）；**nginx 由运维维护，仓库不提交其配置**，只在 `docs/EDGE.md` 写清必须满足的路由/转发头/体积/日志要求与参考片段，并在应用侧提供 `/api/health/edge` 自检端点；备份改为 cron `sqlite3 .backup`；所有维护动作统一走 `jobs` 表并由后台触发，CLI 仅作为同一实现的壳。

#### R. 测试与文档

**问题**

- `P-R1` 85 个测试全为纯函数单测，且 import 私有函数（`test_media.py` 测 `_serialize`/`_audio_format`）；鉴权、CSRF、所有权、上传、派生图路由零覆盖。35 个前端 TS 文件零测试。
- `P-R2` 无 CI、无 ruff/mypy/eslint/prettier；前端只有 `astro check`。
- `P-R3` 文档已漂移：`SCHEMA_VERSION` 文档写 8、代码 13；版本文档 2.2.0、代码 2.3.0；文档称 `/media` 用 `StaticFiles`，实际是 `media_serve.py` 的 router；`PRIVATE_SETTING_KEYS` 文档写“只有 1 个”，实际 30 个；`IMAGE-PIPELINE-PLAN.md` 仍标“待评审、尚未改代码”，但功能已上线，且引用的 `main.py:147` 已不存在。

**3.0.0 处置**：见 6.2 测试矩阵与 6.3 文档规则。

#### S. 评论功能

**现状**：`comments` 表 + 公开提交接口 + 后台审核页 + `comment_moderation` 开关 + 评论限流 + 前台评论区组件与样式；无邮件通知、无第三方反垃圾。

**问题**

- `P-S1` 对一个个人博客，评论的**维护面**（审核、反垃圾、IP 记录与隐私、文案键、前后台 UI、导出兼容、测试）远大于其价值；且它是公共页上唯一的“动态读数据”，持续阻碍把公共页静态化（附录 B）。
- 移除后，公共页渲染输入完全来自“内容 + 设置 + 媒体元数据”，为未来 SSG 去掉一个主要阻塞项。

**3.0.0 处置**：整体删除（BC-35）。评论区、审核页、`/api/comments*`、`comments` 表、`comments_enabled` / `comment_moderation` / `copy_comments_*`、`allow_comments` 列、导出字段、评论限流器、相关测试一并移除；若未来需要互动，走外部系统（独立服务/第三方）而不是再内建。

---

## 3. 目标架构

### 3.1 进程与入口（单层接入：运维 nginx）

```text
浏览器
  │  HTTPS（TLS 终止，HSTS 由接入层负责）
  ▼
平台 nginx（运维维护；仓库不提交配置，只在 docs/EDGE.md 写明要求与参考片段）
  │  覆盖写 X-Forwarded-For / X-Forwarded-Proto；可选 X-Request-ID
  │  client_max_body_size ≥ 210m；可选 limit_req；访问日志
  │
  ├── /api/*   → 127.0.0.1:8000（FastAPI）
  ├── /media/* → 127.0.0.1:8000（FastAPI，关闭缓冲）
  └── /*       → 127.0.0.1:4321（Astro SSR：公共页 + /admin + /_astro 资产）
```

**3.1.0 范围说明（重要）**：本版**只移除 Astro 的代理/中转角色**，删除 `pages/api/[...path].ts`、`pages/media/[...path].ts`、`lib/proxy.ts`；**Astro 作为前端框架与 SSR 运行体完整保留**——公共页与 `/admin` 仍由 Astro 渲染，`/_astro/*` 资产仍由 Astro 进程提供，后续 SSG 预留（附录 B）也以 Astro 的预渲染能力为目标。**不采用 Caddy**，项目不引入第二层边缘；接入层只保留一层由运维维护的 nginx。

**3.1.1 为什么不再内置反向代理（并明确不采用 Caddy）**

- 2.x 的教训是“业务代码里实现代理”：hop-by-hop 头、`Set-Cookie`、超时、真实 IP 信任，全是持续的安全与维护负担（P-A1）。
- 初版方案曾用 Caddy 替代，但这会引入**第二层边缘**：body 上限、压缩、安全头、限流、真实 IP 在两层之间重复定义并需要人肉对齐，恰好复制了方案 R2 要消灭的问题；同时仓库内的 nginx/Caddy 配置**无法代表生产真实配置**，CI 校验只是假保证。
- 因此本版：**单层接入，由运维 nginx 承担**；项目侧只关心“我产出的响应应该带什么头”和“我如何正确取得真实 IP”；接入层配置以文档 + 运行时自检的方式约束，而不是以仓库文件冒充生产配置。

**3.1.2 职责切分（每项只有一个 owner）**

| 能力                           | owner                                | 说明                                                                                                |
| ------------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| TLS / 证书 / HSTS              | 运维 nginx                           | TLS 终止点；HSTS 语义在此；应用不设置 HSTS                                                          |
| `client_max_body_size`         | 运维 nginx                           | ≥ 应用上限（默认 210m），越早拒绝越省资源                                                           |
| 路由（`/api`、`/media`、其余） | 运维 nginx                           | 仓库不提交配置；见 3.1.3 契约                                                                       |
| 真实 IP 归一                   | 运维 nginx 覆盖写 XFF → 应用信任名单 | 后端以 `--proxy-headers --forwarded-allow-ips=<nginx 地址>` 启动；禁止 `$proxy_add_x_forwarded_for` |
| 压缩（gzip/brotli）            | 运维 nginx（可选）                   | 只在一层压缩；不要与应用重复                                                                        |
| 边缘限流                       | 运维 nginx（**可选加固**）           | 应用层限流是必需的兜底，不依赖此层                                                                  |
| 访问日志                       | 运维 nginx（+ 应用日志）             | 用 `X-Request-ID` 关联                                                                              |
| 页面渲染 + 页面安全头          | Astro                                | HTML 响应头（CSP/XFO/Referrer/Permissions 等）在 Astro middleware 中单一定义                        |
| API / 媒体安全头与缓存头       | FastAPI                              | 由 `main.py` 中间件与 `media_serve.py` 分别负责，共享常量                                           |
| `X-Request-ID`                 | nginx（可选生成）→ 应用兜底生成      | 缺失时应用生成并回写响应头                                                                          |
| 应用层限流                     | FastAPI                              | 登录（IP + 账号）、预览、上传；单进程强制                                                           |
| 响应缓存头 / ETag              | 应用（页面与公开 API）               | 不依赖 nginx 缓存                                                                                   |

**3.1.3 接入层契约（写入 `docs/EDGE.md` 的必须项）**

以下为**部署方必须满足**的约定；仓库不提供可部署的配置文件，只在文档中给出要求与参考片段（参考片段必须由运维按自己的 vhost 结构改写，并以 `nginx -t` 校验）。

1. **路由**：`/api/`、`/media/` → FastAPI；其余 → Astro。后端与 Astro 只监听内网/回环，不直接暴露公网。
2. **转发头**：对两条 `proxy_pass` 都必须 `proxy_set_header X-Forwarded-For $remote_addr;`（**覆盖**语义）与 `proxy_set_header X-Forwarded-Proto $scheme;`、`proxy_set_header Host $host;`。**严禁** `$proxy_add_x_forwarded_for`（最左值会被客户端控制）。
3. **体积**：`client_max_body_size ≥ 210m`，与应用 `upload_max_mb` 一致。
4. **媒体**：`/media/` 关闭代理缓冲（`proxy_buffering off`），避免大图落两层临时文件。
5. **压缩**：只在一层启用；用 `curl -H 'Accept-Encoding: gzip' -I` 检查响应头不出现重复编码。
6. **超时**：`proxy_read_timeout ≥ 180s`（覆盖大图上传/下载）。
7. **可选加固**：`limit_req_zone` 必须声明在 `http {}` 层（不能写在 `server {}` 内），登录路径可加 `limit_req zone=... burst=5 nodelay`；这是应用层限流之外的额外一层，**不作为安全前提**。
8. **可选缓存**：若使用 `proxy_cache`，必须排除 `/api/admin/*`、带 Cookie 的请求与任何 `Set-Cookie` 响应；本站应用侧已输出 ETag/`Cache-Control`，默认不需要代理缓存。
9. **日志与关联**：访问日志保留；可选生成 `X-Request-ID`（`$request_id`）并透传。
10. **参考片段（仅供文档示例，不提交为仓库配置）**：

```nginx
# http 层（与其它站点共用时放在 http {} 内）
limit_req_zone $binary_remote_addr zone=blog_login:10m rate=10r/m;

server {
    listen 443 ssl;
    server_name your.site;
    ssl_certificate     /path/site.pem;
    ssl_certificate_key /path/site.key;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 210m;
    proxy_read_timeout   180s;
    proxy_http_version   1.1;
    proxy_set_header     Connection "";
    proxy_set_header     X-Request-ID $request_id;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;   # 覆盖，不追加
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /api/auth/login {                 # 可选加固，且必须同样覆盖转发头
        limit_req zone=blog_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:4321;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**3.1.4 应用侧真实 IP**

1. 删除 `BLOG_PROXY_SECRET`、`x-blog-proxy-secret`、`x-blog-real-ip`；删除 Astro 代理。
2. 后端以 `uvicorn --proxy-headers --forwarded-allow-ips=${BLOG_TRUSTED_PROXY:-127.0.0.1}` 启动（当前 Dockerfile 的 `--no-proxy-headers` 同步修改）；只有来自该地址的 XFF 才可信。
3. 本地开发：Vite dev proxy 会把客户端伪造的转发头清掉并写入 `127.0.0.1`（见 3.1.5），保证开发/生产的真实 IP 语义一致（开发环境所有请求都来自本机，限流按 127.0.0.1 分桶）。
4. 新增 `GET /api/health/edge`（只读）：返回应用实际观测到的 `client_ip`、`X-Forwarded-Proto`、`X-Request-ID` 是否存在；staging/上线后用 curl 校验接入层是否按要求工作。**这是“仓库不提交 nginx 配置”的补偿手段**：配置正确性由运行时观测而非仓库文件证明。

**3.1.5 本地开发（不涉及 nginx）**

- `astro.config.mjs` 增加 **仅 dev 生效** 的 `vite.server.proxy`：`/api` 与 `/media` 代理到 `http://127.0.0.1:8000`，并设置 `xfwd: false`（不回传客户端的转发头）。
- 生产与开发的路由差异只有“谁做路由”这一点：生产是 nginx，开发是 Vite proxy；两者都不再依赖 Astro 业务代码里的代理实现。
- 本地保持单层直连（浏览器 → 4321），不要求安装/运行 nginx；接入层行为验证放在 staging/CI（见 6.2）。
- Cookie：`BLOG_COOKIE_SECURE` 由 `SITE_URL`（或 `BLOG_FRONTEND_URL`）是否为 https 推导，本地 http 保持可用；生产只需正确设置 `SITE_URL`。

**3.1.6 回滚**：应用侧可独立回滚（tag）。接入层变更由运维流程负责，本项目只保证“不依赖特定反向代理实现”。

### 3.2 配置系统

#### 3.2.1 数据形状

配置从“142 键扁平 KV”改为**5 个分组文档**，每组一个 Pydantic 模型、一行存储：

```
settings(group TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)
groups = site | appearance | copy | upload | advanced
```

- `site`：站点标识、URL、导航、页脚、社交、SEO、分页与相册展示参数。
- `appearance`：主题、明暗、强调色、宽度、圆角、栏数、字体、Hero、`custom_css`、`head_html`。
- `copy`：文案键 → 显式字段（不再用 `copy_*` 前缀的任意字符串）；**评论相关文案键随功能删除**；提供 `copy: dict` 覆写入口。
- `upload`：大小上限、图片/音频/文件格式集合（`set[str]` 而不是逗号字符串）。
- `advanced`：图片管线参数（**仅**宽度阶梯与格式开关；质量与编码参数改为代码常量 `PIPELINE_DEFAULTS`，不可运行时修改，见 ADR-10）。

**密钥不再进数据库**：`storage_s3_secret_key`、`storage_s3_access_key` 只从环境变量读取（12-factor）。后台设置页只显示“已配置/未配置”，不提供输入框。删除 `SECRET_SETTING_KEYS` 与响应 mask 逻辑。

**删除的设置键**（不再有任何兼容映射）：`comments_enabled`、`comment_moderation`、`copy_comments_*`、`show_views`、`author_name` / `author_bio` / `author_avatar`、`home_*`，以及 2.x 遗留的 `project_kind` 旧枚举值。

#### 3.2.2 读取与写入

```python
class Settings(BaseModel):
    site: SiteSettings
    appearance: AppearanceSettings
    copy: CopySettings
    upload: UploadSettings
    advanced: AdvancedSettings

def load_settings() -> Settings: ...        # 按组读 + 模型校验 + 默认值
def save_settings(patch: SettingsPatch) -> Settings: ...  # 组级原子写
```

- 删除 `default_settings()` 的扁平字典、`update_settings` 的 31 分支、`public_settings()` 的键集合过滤。
- 缓存：进程内 `lru_cache` + 保存时失效（3.0.0 明确单进程；多 worker 启动时直接拒绝，`RateLimitStore`/设置缓存为将来外置留口）。
- 公开投影：`SiteSettings.public()` 只输出渲染字段；`custom_css`/`head_html` 作为 `SiteBootstrap.appearance` 下发一次（页面内联或外链带哈希，见 9 的度量项），不再随每个 API 响应重复。

#### 3.2.3 前端类型生成

- 构建期 `python -m app.scripts.export_contracts` → `frontend/src/api/schema.json`（或 `openapi.json`）。
- `npm run gen:types` → 生成 `frontend/src/api/types.gen.ts`。
- 删除 `frontend/src/types.ts` 与 `config.ts` 中的 `fallbackSite`；后端不可达时返回真实错误页（不再用前端默认值渲染半成品页面）。
- CI 检查：重新生成后 `git diff --exit-code`，漂移即失败。

### 3.3 数据层

#### 3.3.1 版本重置与空库初始化

- `SCHEMA_VERSION = 1`。库由一份完整 `SCHEMA.sql` 创建，不再有“建表 + 补列 + 数据修补”的三段式。
- 启动时：`PRAGMA user_version` 不等于 1 → 抛错并提示“请清空 `BLOG_DATA_DIR` 后重启”。不做 2.x 结构识别、不做迁移、不做补种。
- 空库首次启动只建表 + 写默认设置；`BLOG_SEED_DEMO=true` 时额外播种演示内容（默认 false，BC-36）。
- 表清单：`users`、`sessions`、`posts`、`project_details`、`media`、`media_derivatives`、`galleries`、`photos`、`taxonomy_terms`、`post_terms`、`revisions`、`settings`、`jobs`、`schema_meta`（结构版本与构建信息）。**无 `comments` 表。**

#### 3.3.2 结构变更流程（取代迁移函数）

- 目录 `backend/migrations/`：`0001_init.sql`、`0002_xxx.sql`……每个文件幂等（`IF NOT EXISTS`）。
- `scripts/db.py` 提供 `migrate` / `status` / `verify` 三个命令，**只由人/CI 显式执行**，启动不执行。
- 每次结构变更后更新 `SCHEMA_VERSION`，并在 `docs/SCHEMA.md` 记录变更（由 `scripts/db.py status` 生成差异，不手写）。
- 数据修补（如回填）写成独立脚本 `scripts/backfill_xxx.py`，执行完即删或归档，不留在应用代码里。

#### 3.3.3 所有者统一

所有可授权资源统一列名：`posts.owner_id`、`galleries.owner_id`、`media.owner_id`、`photos` 继承相册所有权。删除 `uploaded_by`、`author_id` 双轨制与 `owns()` 的 key 猜测。

- 统一约束：`owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT`（删除用户前必须先转移内容，避免孤儿内容）。
- 所有权检查只保留一个函数：`app/services/authz.py:authorize(user, resource, action)`。

#### 3.3.4 事务与补偿

- 引入 `unit_of_work`，但**事务只包数据库短临界区**，不得覆盖上传、Pillow 解码、外部存储 I/O、构建等长操作（否则 SQLite 单写锁会阻塞全站写入）。
- 跨存储操作统一为“DB 先行、文件后清”：
  1. 事务内把行标记 `deleted_at`（软删除）并提交；
  2. 后台 GC 任务删除文件、清理派生图，成功后硬删除行；
  3. 失败可重试，不产生“文件没了但行还在”的中间态。
- 连接层显式设置 `busy_timeout`（如 5000ms）与 WAL 策略，并写入 `docs/DEVELOPMENT.md`。

### 3.4 内容模型

#### 3.4.1 类表继承

```sql
posts(id, type CHECK(type IN ('post','project','page')), title, slug,
      excerpt, content_md, content_html, render_version, cover_image,
      status CHECK(status IN ('draft','published','scheduled')),
      published_at, featured, owner_id,
      seo_title, seo_description, created_at, updated_at,
      reading_time, toc_json,
      UNIQUE(type, slug))

project_details(post_id PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT '', year TEXT, role TEXT,
                client TEXT, url TEXT)
```

- 项目专属字段从 `posts` 移出，删除 `project_*` 在 page/post 上的空列。
- `UNIQUE(type, slug)` 允许文章与页面同名不同路径，语义更准确。
- 删除 `CHECK` 之外的业务清零逻辑（`_post_request` 的 `if is_page`）。
- 所有状态/类型加 `CHECK` 约束，数据库自己拒绝非法组合。
- **评论移除**：删除 `posts.allow_comments`；删除 `comments` 表与相关外键/索引。

#### 3.4.2 API 资源拆分

| 2.3.0                                | 3.0.0                                                              |
| ------------------------------------ | ------------------------------------------------------------------ |
| `POST /api/admin/posts?type=project` | `POST /api/admin/projects`                                         |
| `POST /api/admin/posts?type=page`    | `POST /api/admin/pages`                                            |
| `PUT /api/admin/posts/{id}`          | `PATCH /api/admin/{posts\|projects\|pages}/{id}`（未提供字段保留） |
| `POST /api/posts/{id}/comments` 等   | 删除（评论功能移除）                                               |

每个资源一个 router 文件、一个 `Request`/`Response` 模型、一个权限声明。

#### 3.4.3 渲染版本

- `posts.render_version INTEGER NOT NULL`：写入时记录 `RENDER_PIPELINE_VERSION`。
- 读取时只做“版本一致才直接用 `content_html`”，不一致的由后台任务批量重渲染（可见的“需要重建”提示），不再在请求路径里静默加工。
- `rewrite_inline_images` 改为写入时执行（渲染管线内完成），读路径不再扫描 HTML。
- 阅读时长、TOC 在写入时物化到 `posts.reading_time` / `toc_json`，列表页不再对全文跑正则。
- 这一组“写时物化 + 版本化”同时是 SSG 预留的一部分（附录 B）。

### 3.5 契约层

- 每个路由声明 `response_model`，分页/错误/枚举统一 DTO。
- 错误体：

```json
{
  "error": {
    "code": "content.slug_taken",
    "message": "别名已被占用",
    "field": "slug"
  }
}
```

- 前端只按 `code` 做分支，`message` 仅作兜底；中文文案集中在前端 `i18n/zh-CN.ts`（后端不再关心 UI 文案）。
- `scripts/export_openapi.py` 在构建期输出 `openapi.json`；`openapi-typescript` 生成类型；CI 校验漂移。
- OpenAPI 在线文档仍默认关闭（安全考虑），但产物进入仓库与 CI。

### 3.6 读路径与缓存（SSR 保留 + SSG 预留）

**决策（ADR-4）**：3.0.0 **不引入 SSG**。公共页继续由 Astro SSR 渲染；本版只做“降低 SSR 单页成本”和“为将来 SSG 迁移做预留”。SSG 的可行性、阻塞项与预留清单见附录 B。

#### 3.6.1 3.0.0 的读路径优化（不含 SSG）

1. **单一聚合数据入口**：新增 `/api/bootstrap`，返回渲染一个公共页所需的全部数据（站点设置公开投影、导航、taxonomy、页面所需列表/详情）；页面从“每页 1+N 次请求”降为“1 次请求”。SSG 迁移时同一个接口就是构建期取数接口（预留 1）。
2. **渲染期不再重算**：图片 `image_payload`、阅读时长、TOC、`rewrite_inline_images` 全部写时物化（见 3.4.3、3.7.1），读路径只组装。
3. **HTTP 缓存头**：HTML 输出 `ETag` + `Cache-Control: public, max-age=0, must-revalidate`；`/api/bootstrap` 可 `s-maxage=60`（为将来 CDN/nginx 缓存预留）；`/api/admin/*` 保持 `no-store`；`/media/_v/*` 永久不可变；`/media/{original}` 短缓存 + `ETag`。
4. **错误语义**：后端不可用或渲染异常时返回 5xx/静态错误页，不再渲染“内容服务离线”的 200 半成品（P-M3）。
5. **可选接入层缓存**：若运维希望进一步降负载，可在 nginx 为公开 GET 加短 TTL `proxy_cache`（必须排除 `/api/admin/*`、带 Cookie 请求与 `Set-Cookie` 响应），见 3.1.3 第 8 条。这**不是**本版必需项。

#### 3.6.2 SSG 预留（本版必须落地，验收见 6.2）

| #   | 预留项                     | 3.0.0 要做的事                                                                                                 | 为什么现在做                                                  |
| --- | -------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| R1  | 构建期可取数的单一数据接口 | `/api/bootstrap`（公开、只读、无会话依赖）+ `page_data()` 服务；页面禁止散调多个接口                           | 未来 SSG 的取数入口就是它；否则要在迁移时重写所有页面         |
| R2  | 路径式分页                 | 标签/分类分页由 `?page=N` 改为 `/tags/{tag}/page/{n}`（含 301 兼容映射到新路径）                               | `getStaticPaths` 只能产出路径；query 分页在静态托管下无法工作 |
| R3  | 渲染不依赖请求上下文       | 公共页禁止读取 Cookie / session / UA / `Astro.request`；所有绝对 URL 来自 `SITE_URL` 配置；加 ESLint/grep 检查 | 静态 HTML 无法按请求变化                                      |
| R4  | 派生图就绪信息物化         | `media.derivative_set`（JSON）在预热完成后写入；`image_payload` 只读该字段；页面不触发编码                     | 构建期不能等编码，也不能烘焙占位                              |
| R5  | 后台重建任务形状           | 定义 `jobs.kind='rebuild_site'` 的枚举/状态机/API 形状（`GET /api/admin/jobs/{id}`），**本版不实现执行器**     | 未来只补执行器，不改业务代码与前端                            |
| R6  | 公共页资产可静态化         | `/_astro/*` 现阶段仍由 Astro 提供；保证页面不引用运行期生成的临时路径；为“nginx 直接托管构建产物”留出结构      | 未来切换托管方式时不改模板                                    |
| R7  | 增量失败语义               | 公共页渲染失败时返回 5xx（而非降级半成品），以便未来“构建失败保留上一版”的语义一致                             | 与 SSG 的原子发布语义对齐                                     |

> 明确不做（本版）：`astro build` 的预渲染、构建产物目录、原子切换、重建触发器、构建失败告警。这些属于附录 B 的未来工作，不在 3.0.0 预算内。

### 3.7 媒体、上传与图片管线

#### 3.7.1 产物级 token + 存量不自动重编码（决策 D5）

```
token = sha1( PIPELINE_VERSION | media_id | source_sha1 |
              scene | width | format | quality )[:10]
url   = /media/_v/{media_id}/{token}/{scene}/{width}.{fmt}
```

- **token 记录在派生行上**（`media_derivatives.token`），而不是每次读路径用全局配置重算。`image_payload`/页面只读“已存在的派生行”，因此改配置**不会**让存量 URL 失效。
- 质量与编码参数由 `PIPELINE_DEFAULTS` 常量决定（ADR-10）；`quality` 写进 token 但不参与运行时寻址决策（只用于保证 URL 与字节一致）。
- **只有新上传的媒体**使用当前的 `PIPELINE_VERSION`/质量生成产物；**存量图像沿用现有产物**，直到有人手动执行 `jobs(kind='reencode')`（可按媒体、按相册或全站范围）。
- 手动 `reencode` 生成新 token 行 → 更新 `media.derivative_set` → 旧产物由 GC 在无人引用后清理；整个过程不阻塞读路径。
- `media_derivatives` 增加 `pipeline_version`、`quality` 列；`UNIQUE(media_id, token, scene, width, format)`。
- GC：`jobs` 任务比较“当前 `derivative_set` 引用集合 + 手动重编码保留集合”与表内记录，删除无引用产物与行；按配额执行（每次最多 N 个，避免长事务）。
- 约定写入 `docs/DEVELOPMENT.md`：**改 `PIPELINE_DEFAULTS` 或 `PIPELINE_VERSION` 只影响新上传；要让存量图生效必须手动跑 `reencode`**（并注明 6K 全量重编码的时长/磁盘预算，见 8）。

#### 3.7.2 上传流程

1. `UploadFile` 以 1MB 分块写入 `tempfile`，边写边累计大小，超限立即 `413` 并删除临时文件；
2. 从临时文件用 Pillow 校验（`verify()` + 尺寸），不再整块读入内存；
3. 计算 SHA-256（用于去重与 token），落盘为 `uploads/YYYY/MM/{uuid}.{ext}`（原子 rename）；
4. 图片：写 `media` 行 + 入队 `jobs(kind='prewarm', media_id=…)`；音频/文件：只写入库。
5. 任何 CPU 重活都在**同步 `def` 路由**（线程池）中执行，或显式 `run_in_threadpool`；`async def` 路由内禁止同步重活（CI 用规则/测试卡住）。

#### 3.7.3 任务系统

```sql
jobs(id, kind, payload, status CHECK(status IN ('queued','running','done','failed','cancelled')),
     progress INTEGER, result TEXT, error TEXT, heartbeat_at,
     created_at, started_at, finished_at)
```

- 一个后台 worker（lifespan 内启动的线程）顺序消费；`UPDATE ... SET status='running' WHERE id=(SELECT ... LIMIT 1) RETURNING ...` 保证原子领取。
- **任务回收**：worker 定期刷新 `heartbeat_at`；启动时把 `running` 但心跳超时的任务重置为 `queued`（最多重试 N 次后置 `failed`）。没有这条，“重启后任务可恢复”不成立。
- **队列隔离**：`rebuild_site`（未来）与长耗时的 `reencode`/`prewarm` 不能与轻量任务共用一个队头；至少按 kind 分组轮询（本版实现 `prewarm`/`gc` 的轮询，其他 kind 预留）。
- 任务类型：`prewarm`、`reencode`、`gc_derivatives`、`rerender_content`、`storage_sync`、`export`；**预留** `rebuild_site`（枚举与 API 形状存在，不实现执行器）。
- 后台进度查询 `GET /api/admin/jobs/{id}`，统一替代 `_OPTIMIZE_STATE` / `_SYNC_STATE`。
- 3.0.0 明确：worker 与 API 同进程但通过 DB 通信；未来拆进程不需改业务代码。

#### 3.7.4 首次访问不编码

- `ensure_derivative()` 只允许“已存在则返回，不存在则 202 + 占位图/原图回退”，不再在请求线程内编码。
- 列表/详情返回的 `image` 元数据包含 `ready: bool` 与占位色，前端在未就绪时用原图 + 小尺寸。
- 与存量图像策略的关系：存量图像已有派生行，`ready=true`；新上传在预热完成前 `ready=false`；`reencode` 期间旧产物仍 `ready=true`，因此不会因手动重编码出现“图片暂时消失”。

### 3.8 前端交互层

**决策（ADR-5）**：分两步，不一次性重写。

**第一步（3.0.0 内）**

- 新增 `frontend/src/lib/dom.ts`：
  - `html` 标签模板（默认转义，`raw()` 显式放行）；
  - `qs` / `on` / `mount` / `setBusy` / `emptyState` 等最小原语；
  - `form.ts`：表单与 `data-*` 双向绑定、脏检查、错误展示。
- 15 个脚本改为使用上述原语，删除各自重复实现；禁止裸 `innerHTML`（ESLint 规则 `no-restricted-syntax` 或自写规则检查）。
- 公共页脚本保持原生，不引入框架。
- **评论相关脚本/组件/页面全部删除**（`Comments.astro`、`admin-comments.ts`、`admin/comments.astro` 等）。

**第二步（3.0.0 之后，可独立排期）**

- 把三个最复杂页面（`PostEditor`、媒体库、相册详情）改为 `@astrojs/preact` 岛屿；其余页面继续服务端渲染 + 轻量脚本。
- 迁移标准：页面交互状态 > 5 个或脚本 > 300 行时，评估岛屿化。

### 3.9 样式系统（Phase 1–6，已在 3.0.0 中实施）

> **状态更新**：本节候选设计已在 3.0.0 中分两个批次落地：Phase 1–4 结构重构 + Phase 5 语义收敛 + Phase 6 文档同步，并随 `chore(release): 3.0.0` 提交入库（过程检查点保留在 `git stash` 的 `css-refactor/phase-*`，仅作历史参照）。落地结果与本节原方案的主要差异：
>
> - 目录为 `styles/{tokens,base,shared,site,admin}/` + 单独保留的 `audio-player.css`；共 65 个文件，0 个文件超过 400 行。
> - 层序为 `@layer tokens, base, components, pages, utilities;`；因为 Vite/rollup 会把 route chunk 中重复的 `@layer …;` 语句去重，权威声明放在三套 layout `<head>` 的内联 `<style>` 里，每个文件顶部的 banner 只用于可读性。
> - 组件样式仍是全局分层文件 + 组件级 `import`（不走 Astro `<style>` 作用域，因为 Lightbox / GalleryViewer / 后台列表 / 编辑器 / 音频嵌入是脚本动态生成 DOM，拿不到 scope 属性）。
> - `custom_css` 保持非分层、注入在所有样式表之后（原方案是挂到 utilities 之后）。
> - 零视觉变化通过 `scripts/css/snapshot.mjs` + `diff.mjs` 验证：27 条路由 × 3 视口 × 6 套主题下，**Phase 1–4 的每个元素每个属性胜出声明与重构前完全一致**（57,931 个元素桶、486 组令牌；仅放行两个已删除的死令牌与新引入的 `--color-*` 别名）。快照基于 `BLOG_CSS_UNMINIFIED=1` 的未压缩构建（lightningcss 会合并简写/长写，导致声明级比较出现噪声）。
> - **Phase 5 语义收敛**（允许 ≤0.5px 字号与近似颜色）：字号 84 种 → 16 档静态刻度 + 3 个相对档（最大偏差 0.5px），断点 9 → 4 个，58 个值名颜色别名 → 58 个语义令牌（仅一处 0.22→0.24 的 alpha 合并），`!important` 23 → 15 且全部为 reduced-motion 无障碍重置，`--pillar-pad`/`--gallery-columns` 归位、`--accent` 兜底统一 `#c2451f`、移除死 `data-theme` 属性。相位差快照：DOM/状态差异 0，除字号（≤0.5px）、上述颜色合并、令牌改名外**其他属性 0 差异**。
> - 实测生产负载（minified，逐文件 gzip 相加）：Phase 1–4 后公共页均值 74.4 → 22.7 KB raw（−69%）、15.2 → 6.2 KB gzip（−59%）；后台 105.5 → 40.9 KB raw（−61%）、19.6 → 9.9 KB gzip（−49%）；每页样式表请求从 3 个变为 4–8 个小文件（建议 HTTP/2）。Phase 5 令牌化使 gzip 微增 +1.5%（公共 6.3 KB）/ +3.0%（后台 10.2 KB）。
>
> **后续项**：原列的五项（字号、断点、色板、`!important`、重复令牌）中前四项已完成。剩余 `duplicate-prop` 105 条 WARN 属于"按代际保留同名规则、胜出值不变"的预期结果，作为可选整理（合并时逐条跑 `css:diff`）；后台/公共 palette 的合并仍是显式决策，未在本次范围。详见 `docs/CSS.md` §9。
>
> 以下为本节原始候选设计（保留作历史对照）。

> 本版沿用 2.x 样式体系（`global.css` / `admin.css` / `mono.css` / `index.css` / `audio-player.css`），不做 `@layer` 重构、不拆分样式文件、不引入 Stylelint。以下内容仅作为后续版本候选设计保留。

- 使用 CSS `@layer` 固定层叠顺序：`@layer reset, tokens, base, components, pages, utilities;`
- 文件结构：
  - `styles/tokens.css`（设计令牌唯一来源，含 4 套 palette）
  - `styles/base.css`（reset + 排版）
  - `styles/components/*.css`（按组件）
  - `styles/pages/*.css`（按页面）
  - 删除 `mono.css` 与 `index.css` 的“覆盖层”定位，合并为 `theme.css`（只放令牌与场景化变量）。
- 组件样式优先使用 Astro `<style>` 作用域；全局样式只允许出现在 `components/` 之外的层。
- 后台样式按页面拆分到 `admin/*.css`，单文件上限 600 行（ESLint/Stylelint 规则）。
- `custom_css` 保留但只允许追加在 `@layer utilities` 之后，且文档写明“不得覆盖令牌”。
- 引入 `stylelint` + 令牌使用规范（禁止硬编码颜色/间距，除 `tokens.css`）。
- 删除评论相关样式（评论列表/表单/审核页/统计卡片）。

### 3.10 安全模型

#### 3.10.1 信任边界

```text
浏览器 → 运维 nginx：TLS 终止、HSTS、body 上限、可选 limit_req、访问日志。
nginx → 应用：应用只监听内网/回环；nginx 覆盖写 X-Forwarded-For / X-Forwarded-Proto。
应用 → 存储：凭据来自环境变量；对象存储桶默认私有，直链通过签名或公开前缀策略显式开启。
```

- 任何一层对 `X-Forwarded-*` 采用“追加”语义（如 `$proxy_add_x_forwarded_for`），都会让最左值落入客户端控制 → **必须覆盖**。
- 后端以 `--proxy-headers --forwarded-allow-ips=<nginx 地址>` 启动；只信任来自该地址的 XFF。后端与 Astro 不发布公网端口（compose 内只暴露给 nginx 所在网络/回环）。
- 由于接入层配置由运维掌握、仓库无法验证，应用侧保留**限流兜底**与 `/api/health/edge` 自检，不把安全完全外包给 nginx（见 3.1.4）。

#### 3.10.2 授权

- `app/services/authz.py`：`authorize(user, resource, action)` 唯一入口。
- 路由权限注册表：每个 router 在装饰器/注册表里声明所需权限；测试遍历所有路由，断言“每个非公开路由都有显式权限声明”。公开路由维护 allow-list，新增公开路由必须改这个文件（评审可见）。
- 前端权限不再手写矩阵：由后端 `/api/auth/me` 返回 `permissions`，前端只判断 `includes`。

#### 3.10.3 媒体可见性（语义修正）

- 媒体增加 `visibility TEXT CHECK(visibility IN ('public','unlisted'))`（默认 `public`；`unlisted` 不出现于列表、不可被搜索，但知道 URL 可访问——与 2.x 行为一致，只是诚实命名）。
- `photos.allow_download` 改名 `hide_download_link`，文档明确“这不是访问控制”。
- 3.0.0 不实现私密媒体；如需，走“签名 URL + 短期过期”的独立设计（见 10.1 Open Questions）。

#### 3.10.4 上传与 XSS

- 可执行扩展名在**入库时**标记 `force_download=1`；媒体服务只按该列决定 `Content-Disposition` 与 sandbox CSP，不再按扩展名推断。
- 富文本：保留 bleach 白名单 + 在渲染管线里用 HTML 解析器（而非正则）补 `rel`/`target`。
- 后台：`dom.ts` 默认转义 + ESLint 禁止裸 `innerHTML`。
- **评论移除**直接消除了公开的富文本写入入口：3.0.0 的公开写入面只剩登录、预览（仅管理员）、上传（需权限）。这是安全面的净收缩，需在 7 的删除清单里确认没有残留路由。

---

## 4. 破坏性变更清单

| 编号  | 变更           | 旧行为                                                    | 新行为                                                                                                     | 影响面         |
| ----- | -------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------- |
| BC-01 | 版本号         | 2.3.0                                                     | 3.0.0；`SCHEMA_VERSION = 1`                                                                                | 全部           |
| BC-02 | 数据库         | 启动时自动迁移                                            | **只支持空库初始化**；旧库启动即报错，无迁移/导入                                                          | 运维           |
| BC-03 | 设置存储       | 142 键扁平 KV                                             | 5 组 JSON 文档 + Pydantic 模型                                                                             | 后端/前端/运维 |
| BC-04 | 设置键         | `copy_*` 等扁平键                                         | 分组字段；评论/浏览量相关键删除                                                                            | 后台表单/前端  |
| BC-05 | 密钥           | DB 存储 + 响应 mask                                       | 仅环境变量                                                                                                 | 部署           |
| BC-06 | API 错误体     | `{detail}`                                                | `{error:{code,message,field?}}`                                                                            | 前端/第三方    |
| BC-07 | 内容 API       | `/api/admin/posts?type=`                                  | `/api/admin/{posts\|projects\|pages}`                                                                      | 前端           |
| BC-08 | 更新语义       | PUT 全量（部分字段 COALESCE）                             | PATCH 部分更新；`null` 表示清空                                                                            | 前端           |
| BC-09 | 内容表         | 单表 + `project_*` 空列                                   | `posts` + `project_details` 类表继承                                                                       | 数据/查询      |
| BC-10 | 所有者列       | `author_id` / `owner_id` / `uploaded_by` 并存             | 统一 `owner_id`；删除 `uploaded_by`                                                                        | 数据/代码      |
| BC-11 | 代理           | Astro 手写代理 + 共享密钥                                 | 删除代理与 `PROXY_SECRET`；**不引入 Caddy**；生产由运维 nginx 路由（文档化契约），本地用 Vite dev proxy    | 部署/前端      |
| BC-12 | 设置响应       | `/api/site` 全量                                          | `/api/bootstrap`（渲染必需，可缓存）+ `/api/site`（管理）                                                  | 前端           |
| BC-13 | 图片 URL 语义  | token 含全局配置，读时重算                                | token 记录在派生行，读路径只读已存在产物                                                                   | 前端/缓存      |
| BC-14 | 图片未就绪     | 请求内同步生成                                            | 202 + 占位，后台生成                                                                                       | 前端           |
| BC-15 | 后台任务       | 内存状态 + 轮询自定义端点                                 | `jobs` 表 + `/api/admin/jobs/{id}`                                                                         | 前端           |
| BC-16 | 上传           | 整块读入内存                                              | 流式落盘；超限即断                                                                                         | 前端/后端      |
| BC-17 | 会话           | 每请求更新 user_agent                                     | 仅登录/续期更新                                                                                            | 后端           |
| BC-18 | 浏览量         | 页面/相册浏览量自增（列 + 两个接口 + 统计 + 展示）        | 功能整体移除                                                                                               | 前端/后端/数据 |
| BC-19 | 搜索           | LIKE 全表扫描                                             | FTS5 虚表                                                                                                  | 后端           |
| BC-20 | 媒体下载开关   | `allow_download`                                          | `hide_download_link`（语义不变）                                                                           | 前端/数据      |
| BC-21 | 可执行媒体     | 路由层按扩展名推断                                        | 入库时 `force_download` 列                                                                                 | 后端/存储      |
| BC-22 | 主题           | `data-theme` + `data-palette` + 别名                      | 仅 `data-palette`；删除别名与 `data-theme`                                                                 | 前端           |
| BC-23 | `/galleries`   | 301 → `/photos`                                           | 路由不存在                                                                                                 | 外部链接       |
| BC-24 | localStorage   | 兼容 `ink-color-mode`                                     | 仅 `scene-color-mode`                                                                                      | 前端           |
| BC-25 | 前端类型       | 手写 `types.ts` + `fallbackSite`                          | 生成类型；删除前端默认值                                                                                   | 前端           |
| BC-26 | 权限矩阵       | 前后端各一份                                              | 后端唯一定义；前端读 `permissions`                                                                         | 前端           |
| BC-27 | 安全头         | 三处定义（含计划中的 Caddy 层）                           | 按“响应类别”各自单一定义：页面在 Astro、API/媒体在 FastAPI；nginx 只负责 HSTS/TLS；**不引入 Caddy**        | 运维/后端/前端 |
| BC-28 | 前端代理路由   | `/api`、`/media` 由 Astro 转发                            | 删除两个 catch-all 页面；生产由 nginx 路由，本地由 Vite proxy                                              | 前端           |
| BC-29 | 导出格式       | `mztlab-scene-export` v2                                  | v3，含 `project_details` 与分组设置；**仅用于 3.x 备份/恢复**，不提供 2.x 导入                             | 运维           |
| BC-30 | 文档           | `DEVELOPMENT.md` 1,744 行含行号                           | 重写为 ≤ 800 行，无行号引用；API 参考由 OpenAPI 生成；新增 `docs/EDGE.md` 写接入层要求                     | 文档           |
| BC-31 | 登录退避与限流 | `time.sleep` 退避；限流仅应用内存且多 worker 静默失效     | 退避删除，超限 429 + `Retry-After`；应用层限流为必需（单进程强制），nginx `limit_req` 为可选加固           | 后端/运维      |
| BC-32 | 可观测性       | 各层独立日志，无关联 ID                                   | nginx 可选生成 `X-Request-ID`，应用兜底生成；日志贯通                                                      | 运维/后端      |
| BC-33 | 公共页渲染     | 全站 SSR（`output: 'server'`）                            | **保持 SSR**；SSG 暂缓，本版只做可行性与 7 项预留（附录 B）                                                | 前端/部署      |
| BC-34 | AVIF 质量      | 每图 `avif_quality` / `avif_quality_auto`，后台可覆盖     | 全局常量 `PIPELINE_DEFAULTS`；删除单图覆盖 UI/API 与相关列；**存量图像不自动重编码**                       | 前端/后端/数据 |
| BC-35 | 评论           | 表 + 公开提交 + 后台审核 + 设置 + 文案 + 前后台 UI + 导出 | 功能整体移除；无 `comments` 表、无 `/api/comments*`、无审核页、无 `allow_comments`                         | 前端/后端/数据 |
| BC-36 | 演示播种       | 启动时按 `DEMO_SEED_VERSION` 补种/重渲染演示内容          | 仅 `BLOG_SEED_DEMO=true` 时首次播种；compose 默认 `false`；删除补种逻辑                                    | 数据/部署      |
| BC-37 | 存量派生图     | 改配置即全站 token 变化、旧产物变孤儿                     | 派生行带 token/pipeline_version；**存量不自动重编码**；手动 `reencode` 才生成新产物；旧产物继续服务直到 GC | 后端/运维      |

---

## 5. 实施计划

每个阶段结束时站点应可运行；阶段内可并行的任务已标注。

### Phase 0：地基（2~3 人日）

| 任务            | 产出                                                                                                           | 验收                                                                                         |
| --------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 删除 Astro 代理 | 删除 `pages/api/[...path].ts`、`pages/media/[...path].ts`、`lib/proxy.ts`、`BLOG_PROXY_SECRET` 相关代码        | 代码中 `grep` 不到 proxy secret；`/api`、`/media` 不再经 Astro 业务代码                      |
| 本地开发链路    | `astro.config.mjs` 的 dev-only `vite.server.proxy`（`xfwd: false`）                                            | `npm run dev` 下登录、上传、媒体加载全部可用；浏览器同源                                     |
| 真实 IP         | 后端 `--proxy-headers --forwarded-allow-ips`；`/api/health/edge`                                               | 应用能报告观测到的 `client_ip` / `X-Forwarded-Proto`                                         |
| 接入层文档      | `docs/EDGE.md`：路由、转发头、体积、缓冲、压缩、可选限流/缓存、上线核对清单、参考片段（不提交 nginx 配置文件） | 文档可独立指导运维配置；核对清单可逐条验证                                                   |
| 工具链          | `pyproject.toml`（ruff/mypy）、`eslint.config.js`、`prettier`、`.pre-commit-config.yaml`、GitHub Actions       | `ruff check`、`mypy app`、`npm run lint`、`npm run check` 全绿（存量文件进渐进清单，见 6.2） |
| 版本号          | `VERSION = "3.0.0"`、`package.json` 3.0.0、文档头                                                              | 一致                                                                                         |

> 本阶段**不**引入 Caddy、**不**提交 `deploy/` 下任何 nginx 配置；生产接入层验证在 staging 按 `docs/EDGE.md` 执行。

### Phase 1：契约与配置（4~5 人日）

| 任务         | 产出                                                                                                                | 验收                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| 响应模型     | **公开 API + 核心 DTO** 全量 `response_model` + 统一错误体（管理端路由的契约随 Phase 2 拆分同步补齐，避免重复劳动） | OpenAPI 生成无 `additionalProperties: true` 的漏网响应 |
| 契约产物     | `openapi.json` + `api.types.gen.ts` + CI diff                                                                       | 手改 `types.ts` 会被 CI 拦下                           |
| 设置模型     | `app/settings/models.py` + 分组存储 + 默认值单源；**无 2.x 迁移脚本**                                               | 空库首启即得到 5 组默认文档；后台表单可读写            |
| 删除设置键   | 评论/浏览量/旧作者字段/`home_*` 键清理                                                                              | 代码与表单中无残留键                                   |
| 密钥外置     | 环境变量读取 + 状态展示                                                                                             | 库中不存在密钥；`/api/site` 无密钥                     |
| 前端去默认值 | 删除 `fallbackSite`；后端不可用返回真实错误页                                                                       | 后端停机时页面返回 5xx 而非半成品 200                  |

### Phase 2：数据与授权（4~5 人日）

| 任务       | 产出                                                                        | 验收                                                               |
| ---------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| schema v1  | `migrations/0001_init.sql` + `scripts/db.py`（migrate/status/verify）       | 空库一键建库；旧库启动即报错并给出清库指引                         |
| 类表继承   | `posts` + `project_details`；删除 `allow_comments`                          | 项目字段不再出现在文章行；CHECK 生效                               |
| 统一所有者 | `owner_id` 单列 + `authorize()`                                             | 三份所有权检查删除；集成测试覆盖每种资源 × 每种角色                |
| PATCH 语义 | 各更新接口                                                                  | 漏传字段保留；显式 `null` 清空；照片漏传 `gallery_id` 不再移出相册 |
| 会话与限流 | 去掉 GET 写库；应用层 IP/账号双维度限流；429 语义                           | 单 worker 下行为不变；多 worker 启动时明确拒绝；`Retry-After` 正确 |
| 移除浏览量 | 删列、删接口、删后台统计与前台展示                                          | 数据库无 `view_count`；后台与前台均无浏览量入口                    |
| 移除评论   | 删表、删公开提交/读取接口、删后台审核页与导航、删设置与文案键、删评论限流器 | `grep -ri comment` 仅剩无关词；公开写入面只剩登录/上传/预览        |

### Phase 3：媒体与图片（4~5 人日）

| 任务            | 产出                                                                            | 验收                                                            |
| --------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 流式上传        | `upload_media` 重写为同步 `def` + 临时文件                                      | 200MB 上传内存峰值 < 50MB；上传期间其他 API 正常响应            |
| 派生图寻址      | `media_derivatives` 增加 `token/pipeline_version/quality`；读路径只按已有行组装 | 改 `PIPELINE_DEFAULTS` 后存量 URL 不变，不触发重编码            |
| 手动重编码      | `jobs(kind='reencode')`（按媒体/相册/全站）+ `derivative_set` 更新              | 手动触发后才产生新产物；期间旧图仍可访问；可查询进度            |
| 任务系统        | `jobs` 表 + worker + 心跳/回收 + kind 轮询隔离                                  | 进程被杀后 `running` 任务可回收重试；不再有全局字典             |
| 未就绪降级      | `ready` 元数据 + 占位                                                           | 首次访问不触发编码                                              |
| 存储接口收窄    | 去 `local_path` 依赖                                                            | `media_serve` 无后端分支                                        |
| AVIF 质量常量化 | 删除每图参数与覆盖 UI/API；质量来自 `PIPELINE_DEFAULTS`                         | 后台/API 无质量覆盖入口；只有新上传或手动 `reencode` 会改变产物 |

### Phase 4：前端与预留（3~4 人日）

> 本阶段原计划**不做样式收口**；该范围已在 3.0.0 发布前补齐（Phase 1–6，见 §3.9 状态更新），其余任务照常实施。

| 任务                 | 产出                                                                      | 验收                                                        |
| -------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 聚合数据入口         | `/api/bootstrap` + `page_data()`，公共页改为单次取数                      | 每个公共路由只调用 1 个数据接口；页面无散调 API             |
| HTTP 缓存头          | 页面 ETag/`Cache-Control`；`/api/bootstrap` 可缓存；admin 保持 `no-store` | `curl -I` 校验头正确；后台页面不被缓存                      |
| 路径式分页（R2）     | `/tags/{tag}/page/{n}`、`/categories/{cat}/page/{n}` + 旧 query 301       | 静态托管形态下分页可工作（预留验收）                        |
| 渲染上下文审计（R3） | 公共页禁止 cookie/session/UA；加 grep/ESLint 检查                         | 检查规则在 CI 生效；公共页 HTML 与请求头无关                |
| 派生图就绪物化（R4） | 预热完成后写 `derivative_set`                                             | 页面取图不触发编码；未就绪有占位                            |
| 重建任务形状（R5）   | `jobs.kind='rebuild_site'` 枚举/状态机/API 形状（不实现执行器）           | 任务 API 可返回 `queued` 形状的预留记录；文档写明未来实现点 |
| 前端原语             | `dom.ts` / `form.ts` + 脚本迁移；删除评论脚本/页面                        | 无裸 `innerHTML`；ESLint 规则生效                           |
| 令牌归一化           | `lib/theme.ts` 单处                                                       | 两个 Layout 无重复逻辑                                      |

### Phase 5：收尾（2~3 人日）

| 任务           | 产出                                                                                                                                                                                                  | 验收                                                                                 |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 搜索 FTS5      | `content_fts` + 写入同步（无评论内容）                                                                                                                                                                | 1 万篇内搜索 P95 < 100ms                                                             |
| 导出/恢复      | `export` v3 + `import_3x`（仅 3.x 格式）                                                                                                                                                              | 3.0.0 导出 → 3.0.0 全量还原；**不提供 2.x 导入**                                     |
| GC 与备份      | `jobs` 型 GC + cron `sqlite3 .backup` + 恢复演练一次                                                                                                                                                  | 孤儿产物可回收；备份可还原（含演练记录）                                             |
| 文档归档与重写 | 旧 README / DEVELOPMENT / IMAGE-PIPELINE-PLAN 归档；重写 README、DEVELOPMENT（≤ 800 行）、`docs/SCHEMA.md`、`docs/EDGE.md`（nginx 接入指南）、OpenAPI 参考；附录 B 长期化为 `docs/SSG-FEASIBILITY.md` | 归档件可追溯；新文档无行号引用；README 与 3.0.0 行为一致（无评论、无 SSG、单层接入） |
| 删除清单执行   | 见第 7 节                                                                                                                                                                                             | `grep` 不到任何迁移/评论/代理/兼容代码                                               |
| 验收脚本化     | 把 6.1/6.2 的检查写成 `scripts/verify.sh`（或 CI job）                                                                                                                                                | 一条命令可复现验收结论                                                               |

---

## 6. 验收标准

### 6.1 功能 DoD（每个变更都适用）

1. 有对应的集成测试（HTTP 级），且覆盖失败路径（401/403/404/409/413/422/429）。
2. 无新增 `assert` 控制流、无新增手写 HTML 字符串拼接、无新增裸 `innerHTML`。
3. 不引入第二份默认值/权限矩阵/字段映射；如确实需要镜像，必须由生成器产生并在 CI 校验。
4. 涉及写操作的路由在 OpenAPI 中声明 `response_model` 与错误模型。
5. 涉及跨存储的操作写明补偿/重试策略。
6. 涉及接入层的行为（真实 IP、Cookie Secure、`X-Request-ID`）必须能在**应用侧**断言或观测（`/api/health/edge`）；nginx 配置本身不在仓库内，其正确性由 staging 按 `docs/EDGE.md` 核对清单验证，**不进入本地开发流程**。
7. 涉及公共页渲染的变更，必须同时满足 3.6.2 的 7 项预留检查（否则未来 SSG 迁移要返工）。

### 6.2 测试矩阵（最低要求）

| 层                     | 工具                                            | 覆盖                                                                                                                         |
| ---------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 纯函数单测             | `pytest`                                        | Markdown 渲染、EXIF、slug、分页、权限矩阵                                                                                    |
| 服务层单测             | `pytest`                                        | `authz`、`settings`、`jobs`（含心跳回收）、`artifact_token`、`reencode` 计划                                                 |
| HTTP 集成              | `pytest` + `httpx` `TestClient`（临时数据目录） | 认证/会话/CSRF/所有 admin 路由/所有权/上传/派生图/导出；**评论路由不存在（404 断言）**                                       |
| 契约                   | `pytest` + OpenAPI diff                         | 响应字段与模型一致；前端类型与 OpenAPI 一致                                                                                  |
| 前端单测               | `vitest`                                        | `dom.ts` 转义、`form.ts`、`images.ts` srcset 生成                                                                            |
| E2E                    | `playwright`（3 条主流程）                      | 登录 → 新建文章并发布 → 前台可见；上传图片 → 建相册 → 前台可见；权限越权被拒                                                 |
| SSG 预留               | pytest + 脚本检查                               | 公共页只调用 1 个聚合接口；分页无 `?page=`；页面不读 cookie/session/UA；`derivative_set` 就绪；`rebuild_site` 任务形状可查询 |
| 边缘（staging，仅 CI） | `docs/EDGE.md` 核对清单 + curl 断言             | `X-Forwarded-For` 覆盖生效（伪造无效）、413 来自 nginx、Cookie `Secure`、`X-Request-ID` 贯通、`/media` 无缓冲                |
| 静态检查               | `ruff` + `mypy`（渐进清单）+ `eslint`           | 新代码严格；存量文件在 ignore 清单中逐项减少                                                                                 |

覆盖率门禁：服务层与路由层 ≥ 80%，`frontend/src/lib` ≥ 70%；存量文件可采用“只卡改动行”的 ratchet 模式（见 8）。

### 6.3 文档规则

- 禁止在文档中写行号（`main.py:73` 这类引用一律改为函数名/章节名）。
- API 参考由 OpenAPI 生成，不手写请求/响应字段表。
- 设置项、数据表字段由脚本生成（`scripts/docs/gen.py`），CI 检查 `git diff --exit-code`。
- `docs/EDGE.md` 是接入层唯一文档：写明必须满足的路由/转发头/体积/缓冲/压缩/可选限流与缓存/上线核对清单，以及参考片段（该片段**不是**仓库配置，不参与 CI 校验）。
- 每份文档头部标注“适用版本”。主版本升级时，旧文档**整体移入 `docs/archive/{旧版本}/`**，新文档从零重写。

---

## 7. 需要删除的代码

### 7.1 后端

| 位置                                    | 内容                                                                                                                                                                            | 原因                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `app/db.py`                             | `_ADDED_COLUMNS`、`_ensure_columns`、13 个 `_migrate_*`、`_backfill_*`、`_ensure_default_settings` 的退役键删除逻辑、`DEMO_SEED_VERSION` 补种                                   | 3.0.0 只支持空库初始化                           |
| `app/db.py`                             | `load_settings` / `public_settings` / `save_settings` 的扁平实现、`_SETTINGS_CACHE`                                                                                             | 被分组模型取代                                   |
| `app/defaults.py`                       | `LEGACY_DEFAULTS`、`LEGACY_PALETTES`、`SCENE_V1_COPY`、`SCENE_V2_COPY`、`SCENE_V2_NAV`、`SCENE_INDEX_COPY`、`PUBLIC_SETTING_KEYS`、`SECRET_SETTING_KEYS`、评论/浏览量相关默认键 | 历史债务/功能移除                                |
| `app/config.py`                         | `PROXY_SECRET`、`PROXY_SECRET_HEADER`、`REAL_IP_HEADER`                                                                                                                         | 单层 nginx 覆盖写 + `--forwarded-allow-ips` 接管 |
| `app/deps.py`                           | 每请求 `UPDATE sessions`、`can()` 的 role-dict 回退、评论 IP 记录                                                                                                               | 见 P-D3 / P-E2 / BC-35                           |
| `app/routes/admin.py`                   | `update_settings` 31 分支、`_sanitize_*`（迁入模型校验）、`_post_request`                                                                                                       | 拆分                                             |
| `app/routes/admin.py`                   | 全部 handler 拆到 `routes/{posts,projects,pages,taxonomy,settings,profile,export}.py`                                                                                           | 见 P-L1                                          |
| `app/routes/*.py`                       | 评论相关：公开提交/读取、后台审核/列表、统计卡片、`comment_moderation` 分支                                                                                                     | 评论功能移除（BC-35）                            |
| `app/routes/public.py`                  | `record_view` / `record_gallery_view` / `view_count` 自增                                                                                                                       | 浏览量功能移除（BC-18）                          |
| `app/routes/admin.py`                   | `stats()` 的 `top_posts` / `views` 统计                                                                                                                                         | 浏览量功能移除（BC-18）                          |
| `app/routes/media.py` + `app/images.py` | 每图 AVIF 质量覆盖（`avif_quality` / `avif_quality_auto`、`media_quality_override`）                                                                                            | 质量改为不可变常量（BC-34）                      |
| `app/routes/media_serve.py`             | 按扩展名推断可执行文件的 `ACTIVE_MEDIA_EXTENSIONS` 分支                                                                                                                         | 改 `force_download` 列                           |
| `app/schemas.py`                        | `MediaAltIn.avif_quality` / `avif_quality_auto`、评论相关模型                                                                                                                   | 功能移除                                         |
| `app/security.py`                       | 评论限流器；登录退避的 `sleep` 逻辑                                                                                                                                             | BC-31 / BC-35                                    |
| `app/seed.py`                           | `DEMO_SEED_VERSION` 与“旧库补种”逻辑、评论演示数据                                                                                                                              | 3.0.0 只做首次播种                               |
| `app/routes/auth.py:70-77`              | `author_name` 写入                                                                                                                                                              | 已退役键                                         |
| `backend/tests/test_*.py`               | import 私有函数的测试、评论相关测试                                                                                                                                             | 改为服务层/HTTP 测试                             |

### 7.2 前端

| 位置                                                                                                                    | 内容                                              | 原因                                                 |
| ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------- |
| `src/lib/proxy.ts`、`pages/api/[...path].ts`、`pages/media/[...path].ts`                                                | 手写代理                                          | 单层接入：生产 nginx、开发 Vite proxy                |
| `src/config.ts`                                                                                                         | `fallbackSite`（150 行）                          | 第三份默认值                                         |
| `src/types.ts`                                                                                                          | 手写 API 类型                                     | 生成类型取代                                         |
| `src/lib/permissions.ts`                                                                                                | 手写角色矩阵                                      | 后端唯一来源                                         |
| `src/styles/*.css`（2.x 的 `global.css` / `admin.css` / `mono.css` / `index.css`）                                      | 覆盖式主题层 + 巨型单文件                         | **已删除**：拆成 65 个分层文件（3.0.0 实施，见 3.9） |
| `src/lib/*-esm.mjs`                                                                                                     | CJS 桥接 shim                                     | 依赖升级后删除；若必须保留则移入 `vite` 配置         |
| `pages/galleries/index.astro`                                                                                           | `/galleries` 301                                  | BC-23                                                |
| `components/admin/ImageQualityDialog.astro`、`lib/quality-dialog.ts`                                                    | 单图 AVIF 质量覆盖 UI                             | 删除（质量不可变，BC-34）                            |
| `pages/posts/[slug].astro`、`pages/galleries/[slug].astro`、后台统计卡片                                                | 浏览量 UI 与 `show_views` 判断                    | 删除（BC-18）                                        |
| `components/Comments.astro`、`scripts/admin-comments.ts`、`pages/admin/comments.astro`、`scripts/comments.ts`、评论样式 | 评论前后台全部实现                                | 删除（BC-35）                                        |
| 导航/统计/图标中评论入口                                                                                                | `admin` 导航项、`pending-comments` 卡片、图标引用 | 删除（BC-35）                                        |

### 7.3 文档归档与重写

- `README.md`（368 行）→ 归档到 `docs/archive/2.x/README.md`，然后**彻底重写**：面向 3.0.0 使用者，覆盖单层接入（nginx 由运维按 `docs/EDGE.md` 配置）、无评论、无浏览量、质量不可变、存量图像不自动重编码、SSG 暂缓与预留、不兼容升级政策。
- `docs/DEVELOPMENT.md`（1,744 行）→ 归档到 `docs/archive/2.x/DEVELOPMENT.md`，然后**彻底重写**为 ≤ 800 行：删除迁移/历史章节与行号引用，补充接入层契约、jobs 与心跳回收、`reencode` 策略、契约生成、测试矩阵、SSG 预留与附录 B 索引。
- `docs/IMAGE-PIPELINE-PLAN.md`（已实现且过期）→ 归档到 `docs/archive/2.x/`，内容并入新 DEVELOPMENT 与 `docs/SCHEMA.md` 后从当前目录移除。
- 新增 `docs/EDGE.md`：接入层唯一文档（nginx 要求 + 参考片段 + 上线核对清单；**不包含可部署的仓库配置**）。
- 新增 `docs/SSG-FEASIBILITY.md`：附录 B 的长期版本（阻塞项、预留清单、未来工作量）。
- 本文已于 2026-10-23（3.0.0 发布后）归档到 `docs/archive/3.0.0/REFACTOR-3.0.0.md`。
- 新增 `docs/archive/README.md` 说明归档规则与各版本差异索引。

### 7.4 需要新增的非删除项

- `docs/EDGE.md`（接入层文档，替代初版的 `deploy/nginx.conf` 与 `deploy/Caddyfile`）。
- `docs/SSG-FEASIBILITY.md`。
- `GET /api/health/edge`（接入层观测端点）。
- CI job：契约 diff、静态检查、HTTP 集成测试、SSG 预留检查、staging 边缘核对（**不校验仓库内不存在的 nginx 配置**）。

---

## 8. 风险与回滚

| 风险                                                               | 概率 | 影响 | 缓解                                                                                                                            |
| ------------------------------------------------------------------ | ---- | ---- | ------------------------------------------------------------------------------------------------------------------------------- |
| 生产 nginx 配置与 `docs/EDGE.md` 不符（仓库无法校验）              | 中   | 高   | 上线核对清单逐条验证；`/api/health/edge` 观测真实 IP/协议；staging 与生产同构复查；把“接入层必须是单层且覆盖写 XFF”写进部署准入 |
| 移除 Astro 代理后本地/生产链路回归                                 | 中   | 高   | dev 用 Vite proxy（仅 dev）并加 e2e；生产按 EDGE 清单核对；保留“接口路径不变”保证页面无需改动                                   |
| 真实 IP 在接入层失效（限流被绕过）                                 | 中   | 高   | 应用只信任 `--forwarded-allow-ips` 白名单；健康检查端点观测；集成测试断言伪造 XFF 无效                                          |
| 应用层限流单进程假设被打破（多 worker）                            | 中   | 中   | 启动检测 `WEB_CONCURRENCY`，多 worker 直接拒绝启动；`RateLimitStore` 接口为将来外置留口                                         |
| 存量图像不自动重编码导致“不同图像质量/格式不一致”                  | 高   | 低   | 派生行记录 `pipeline_version`，后台可筛选“旧版本产物”；`reencode` 任务可按范围执行；文档写明这是有意设计                        |
| 手动全量重编码时长/磁盘超预期（6K × 20+ 变体）                     | 中   | 中   | `reencode` 按配额分批执行 + 进度/取消；上线前用真实媒体验证一次；磁盘水位告警                                                   |
| 评论移除不彻底（导航/统计/文案/导出残留）                          | 中   | 中   | 删除清单 + `grep -ri comment` 检查；集成测试断言相关路由 404                                                                    |
| SSG 预留不足导致未来返工                                           | 中   | 中   | 7 项预留逐项验收（6.2）；附录 B 的阻塞项清单作为迁移前置检查                                                                    |
| Phase 1 为全部路由加 `response_model`、Phase 2 又拆路由 → 重复劳动 | 中   | 中   | Phase 1 只冻结公开 API 与核心 DTO；管理端契约随 router 拆分在 Phase 2 完成                                                      |
| `mypy --strict` / 80% 覆盖率 / e2e 在预算内不可达                  | 中   | 中   | 采用 ratchet：新代码严格、存量文件 ignore 清单；覆盖率只卡改动行；playwright 放 nightly                                         |
| 设置模型遗漏键导致行为变化                                         | 中   | 中   | 由于无存量数据，风险降为“默认值是否符合预期”：用快照测试固定 5 组默认文档                                                       |
| 类表继承改动查询面大                                               | 中   | 中   | 保留视图 `v_posts_with_project` 供旧查询过渡一个阶段，Phase 2 结束删除                                                          |
| 事务与长操作混用导致 SQLite 写锁阻塞                               | 中   | 中   | 规定“事务只包短临界区”；`busy_timeout` + 集成测试（上传期间写请求可用）                                                         |
| 时间超支                                                           | 中   | 中   | 每个 Phase 独立可发布；Phase 0/1 即可交付收益                                                                                   |

**回滚策略**：每个 Phase 独立 tag（`v3.0.0-p0`…`v3.0.0`）。由于不涉及存量数据迁移，数据库切换（Phase 2）不构成不可逆操作：回滚即切回旧 tag 并清空数据目录重建。接入层变更由运维独立回滚，应用不依赖其实现。

---

## 9. 成功度量

上线后 2 周采集：

- **性能**：公共页 TTFB P95（SSR）、`/api/bootstrap` 命中率与体积、图片首字节、上传期间 API P95。
- **工程**：新增设置项/字段的改动文件数（人工统计 3 个需求）、CI 平均时长、测试覆盖、`reencode` 触发次数（越少越好）。
- **稳定性**：5xx 数量、429 数量、GC 后孤儿产物数量（应为 0）、任务失败率与心跳回收次数。
- **安全**：公开写入面清单（应为 0：登录/预览/上传均需权限或限流）、无评论后垃圾内容入口为 0。
- **代码**：总 LOC 变化、CSS LOC、迁移函数数量（目标 0）、`grep` 兼容/评论/代理代码命中数（目标 0）。
- **SSG 就绪度**：附录 B 阻塞项清单中已闭环的比例（目标：3.0.0 结束时 R1~R7 全部满足）。

---

## 10. 决策记录（ADR 摘要）

- **ADR-1 不向下兼容**：理由——历史债务集中在迁移与配置；本版已确认无存量数据需要保护（D1），保留兼容层只会继续背 13 个迁移函数与 142 键扁平配置。
- **ADR-2 不内置反向代理，接入层只保留一层运维 nginx**：理由——2.x 的自研代理是持续的安全与维护负担（P-A1）；初版方案的 Caddy 会引入第二层边缘与“仓库配置冒充生产配置”的假保证。备选：保留 Astro 代理（已否）、引入 Caddy（已否，D2）、nginx + Caddy 双层（已否）、浏览器直连 FastAPI + CORS（安全与同源成本更高）。
- **ADR-3 配置用分组模型而非多表**：理由——SQLite + 单机，5 行 JSON 文档比 142 列的规范化表更易演进；模型负责类型与校验，存储只负责持久化。
- **ADR-4 保留 SSR，SSG 暂缓**：理由——SSG 的收益真实，但当前阻塞项（构建/发布管道、资产托管、派生图就绪、分页路径、重建触发）与公告/评论等动态读数据耦合，一次做完会把重构和新增运行形态绑死；评论移除已消除一个主要阻塞。3.0.0 先做“降低 SSR 单页成本 + 7 项预留”，未来按附录 B 迁移。备选：直接上 SSG（已否，D4）、nginx 短 TTL 缓存（保留为可选过渡）。
- **ADR-5 前端先抽原语、后岛屿化**：理由——一次性重写的风险高于收益；先消灭 XSS 面与重复代码，再评估框架。
- **ADR-6 产物级 token**：理由——缓存键必须只包含“产物本身”的输入；全局配置进入缓存键会导致全站缓存互相绑架。注意：质量是产物输入，因此**保留在 token 中**（与 ADR-10 一致，而非初版“从 token 中删除质量”）。
- **ADR-7 任务用 DB 表而非内存**：理由——需要跨重启持久化、可查询、可取消；单机场景不需要 Redis/Celery。
- **ADR-8 接入层职责单一化**：理由——每项能力只有一个 owner（3.1.2）：nginx 管传输/日志/可选限流，应用管渲染、响应头、真实 IP 信任、限流兜底；仓库不提交 nginx 配置，改为文档 + 运行时自检。
- **ADR-9 移除浏览量**：理由——无去重的自增数字不可信，做去重聚合又要额外存储与隐私权衡；删除列/接口/统计/展示，减少攻击面与写放大。
- **ADR-10 AVIF 质量常量化 + 存量不自动重编码**：理由——质量是编码参数而非业务内容，放进设置/数据库会制造“全局哈希联动 + 单图覆盖分支 + 迁移债务”。统一为 `PIPELINE_DEFAULTS` 常量；`PIPELINE_VERSION` 变化**只影响新上传**，存量图像只有手动执行 `reencode` 才会重编码（D5）。这与初版“升版本即全站重编码”不同，避免一次改代码导致全站缓存与编码雪崩。
- **ADR-11 移除评论**：理由——维护面/攻击面与个人博客定位不成比例；没有邮件通知与反垃圾，评论价值低；移除后公共页渲染输入变为纯内容，为 SSG 去掉一个动态读阻塞项。备选：保留 + 引入第三方评论（本次未评估，若需要另立方案）。
- **ADR-12 本地开发不经 nginx**：理由——起两层代理会显著拖慢反馈；dev 用 Vite proxy 保持同源语义，接入层行为在 staging/CI 验证。

### 10.1 待定问题（Open Questions）

1. SSG 迁移的触发预算：全量构建在 500 篇以内 ≤ 60s 是否成立？超过后是否需要增量构建/分区部署（见附录 B.5）？
2. 搜索是否需要中文分词？SQLite FTS5 `unicode61` 对中文按整句切分基本不可用，Phase 5 前需在 `unicode61` / `trigram` / 自建分词之间决策（BC-19 的验收依赖它）。
3. 私密媒体（签名 URL）是否列入 3.1？
4. `tags/categories` 是否需要多语言字段（当前为单语中文）？
5. 导出格式是否需要兼容第三方（如 Ghost/Hugo）？
6. 平台 nginx 若为其他站点开启了统一缓存，是否需要为本站点单独绕过？（本站应用侧已输出 ETag/`Cache-Control`，默认不需要代理缓存）
7. 手动 `reencode` 的范围 UX：按媒体 / 按相册 / 按“旧 `pipeline_version`”一键筛选，哪个是主入口？
8. 移除 Astro 代理后，是否需要为旧路径（如 `/api` 被外部直接引用）保留任何跳转？当前结论：不需要（站点无对外 API 承诺）。
9. 分页路径化（`/tags/{tag}/page/{n}`）是否在 3.0.0 一并改？本文按“改”设计（R2），若评审希望减少 URL 变更可延后，但会削弱 SSG 预留。
10. 是否保留 `/galleries` → `/photos` 的 301？（当前按初版删除，成本一行；若站点已有外部链接可保留）

---

## 11. 待办事项（Backlog）

本节只登记**文档类待办**；实现类任务见第 5 节各 Phase。规则：完成一项即在对应 PR 勾选，并在 `docs/archive/README.md` 记录归档信息。**11.1 与 11.2 全部完成前，3.0.0 不发布。**

### 11.1 归档（先做，且必须在重写之前完成）

| ID       | 事项                               | 产出                                      | 验收                                                                   |
| -------- | ---------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------- |
| TODO-D01 | 归档当前 README（368 行）          | `docs/archive/2.x/README.md`              | 可访问；头部加“2.x 历史文档，请勿据此部署”说明；当前目录不再保留旧内容 |
| TODO-D02 | 归档当前 DEVELOPMENT（1,744 行）   | `docs/archive/2.x/DEVELOPMENT.md`         | 原貌归档（不改内容）；头部加历史说明                                   |
| TODO-D03 | 归档 IMAGE-PIPELINE-PLAN（653 行） | `docs/archive/2.x/IMAGE-PIPELINE-PLAN.md` | 内容已并入新 DEVELOPMENT 与 `docs/SCHEMA.md` 后移除                    |
| TODO-D04 | 建立归档索引                       | `docs/archive/README.md`                  | 列出各版本目录、归档日期、差异摘要、当前文档入口                       |

### 11.2 重写（从零写，不做增量修补）

| ID       | 事项                 | 产出                                    | 验收                                                                                                                                                                                                                                 |
| -------- | -------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TODO-D05 | 彻底重写 README      | `README.md`（≤ 250 行）                 | 面向使用者：定位、单层接入（nginx 由运维按 `docs/EDGE.md` 配置）、无评论、无浏览量、质量不可变、存量图像不自动重编码、SSG 暂缓、不兼容升级政策、常用命令；不得出现 `view_count`、评论、单图质量覆盖、手写代理、Caddy 等 2.x/初版描述 |
| TODO-D06 | 彻底重写 DEVELOPMENT | `docs/DEVELOPMENT.md`（≤ 800 行）       | 面向维护者：模块职责、数据流、契约生成、接入层契约、jobs/心跳、`reencode`、测试矩阵、SSG 预留与附录 B 索引；无行号引用、无迁移章节                                                                                                   |
| TODO-D07 | 生成 schema 文档     | `docs/SCHEMA.md`                        | 由 `scripts/db.py` 从 `migrations/*.sql` 生成；CI `git diff --exit-code`                                                                                                                                                             |
| TODO-D08 | 生成 API 参考        | `docs/API.md` 或站点内页面              | 由 `openapi.json` 生成；不手写请求/响应字段表                                                                                                                                                                                        |
| TODO-D09 | 接入层手册           | `docs/EDGE.md`                          | 路由/转发头/体积/缓冲/压缩/可选限流与缓存/上线核对清单/参考片段；明确本地开发不涉及 nginx；**不包含可部署配置**                                                                                                                      |
| TODO-D10 | SSG 可行性文档       | `docs/SSG-FEASIBILITY.md`               | 附录 B 的长期版本：阻塞项、预留闭环状态、未来工作量与验收                                                                                                                                                                            |
| TODO-D11 | 版本号一致性         | `VERSION`、`package.json`、两份文档头部 | CI 校验三者与 git tag 一致                                                                                                                                                                                                           |

### 11.3 依赖与完成定义

- TODO-D05 / D06 依赖 Phase 4 完成（读路径、预留项与行为冻结后再定稿）；D07–D10 依赖 Phase 1（契约产物）与 3.1（接入契约）冻结。
- D01–D04 可在 Phase 0 立即执行，不阻塞实现。
- 完成定义：
  1. README 与 DEVELOPMENT 的旧内容 **100% 归档**，当前目录只剩 3.0.0 版本；
  2. 新文档中的每个数字（行数、键数、路由数、指标）要么由脚本生成，要么标注采集日期；
  3. 文档 CI 覆盖：无行号引用检查、链接检查、生成物 `git diff --exit-code`。

## 附录 A：术语表

| 术语                       | 解释                                                                            |
| -------------------------- | ------------------------------------------------------------------------------- |
| SSR / SSG / ISR            | 服务端渲染 / 构建时静态生成 / 静态 + 定期重建                                   |
| BFF / 反向代理             | 前端专用后端 / 位于客户端与上游之间的中间层                                     |
| 同源 / CORS / CSRF         | 浏览器同源策略 / 跨源放行头 / 借 Cookie 伪造请求                                |
| CSP / XSS                  | 内容来源白名单 / 注入可执行脚本                                                 |
| Session / Token 指纹       | 服务端会话 / DB 只存 token 哈希                                                 |
| scrypt / 盐 / 恒定时间比较 | 内存硬密码哈希 / 防彩虹表 / 防时序侧信道                                        |
| WAL / 单写者               | SQLite 预写日志 / 同一时刻仅一个写事务                                          |
| 迁移 / 幂等                | 结构版本化演进 / 重复执行结果一致                                               |
| STI / 类表继承             | 单表靠 type 区分 / 共享列 + 子类型扩展表                                        |
| DTO / OpenAPI / 代码生成   | 跨边界数据形状 / 机器可读契约 / 由契约生成类型                                  |
| 派生图 / srcset / picture  | 多尺寸格式副本 / 浏览器自选 / 格式回退                                          |
| 不可变缓存 / 缓存键        | 内容哈希进 URL / 决定缓存命中的维度                                             |
| 物化                       | 把计算结果提前算好存库                                                          |
| single-flight / 背压       | 并发去重 / 限流保护下游                                                         |
| 事务 / 补偿                | ACID 原子提交 / 无法回滚时的显式修复动作                                        |
| SSOT                       | 单一真相来源                                                                    |
| ADR                        | 架构决策记录                                                                    |
| 接入层                     | 本文中的运维 nginx：负责 TLS、路由、体积、日志、可选限流/缓存；仓库不提交其配置 |
| limit_req                  | nginx 自带的请求速率限制，按 key（如客户端 IP）分桶                             |
| X-Request-ID               | 一次性请求标识，用于跨 nginx / 应用日志串联同一次请求                           |
| getStaticPaths             | Astro 的预渲染接口：声明构建期要生成哪些动态路由                                |
| 预留（SSG）                | 为将来迁移到 SSG 而在当前版本落实的结构性设计，见 3.6.2                         |
| reencode                   | 手动触发的存量图像重新编码任务（ADR-10）                                        |

---

## 附录 B：SSG 迁移可行性评估与 3.0.0 预留

> 本附录是决策 D4 的交付物：**3.0.0 不实现 SSG**，但要给出“框架主体迁移到 SSG”的可行性分析，并把不返工所需的预留落到本版开发里。

### B.1 结论

- **方向可行，但不适合放在 3.0.0 内**。SSG 的核心收益（运行期零渲染、TTFB 更低、抗流量抖动）成立；主要成本不在“预渲染”本身，而在**构建/发布管道、资产托管切换、数据就绪与触发延迟**这四件基础设施。
- 3.0.0 的推进顺序是：先完成 7 项预留（3.6.2），使“页面数据 = 单一接口 + 纯函数渲染 + 已物化的媒体元数据”；这样未来迁移时只需要新增构建器与发布流程，不需要重写页面与服务。
- **评论移除显著降低迁移难度**：公共页不再有随请求变化的读数据，这是本版对 SSG 最重要的一项使能。

### B.2 现状与目标差异

| 维度       | 3.0.0（本版）                   | SSG 目标                                                          |
| ---------- | ------------------------------- | ----------------------------------------------------------------- |
| 公共页渲染 | Astro SSR，每次请求组装         | `astro build` 预渲染为 HTML 文件                                  |
| 数据来源   | 运行期 1 次 `/api/bootstrap`    | 构建期同接口取数，写入构建产物                                    |
| 托管       | Astro 进程（含 `/_astro` 资产） | 接入层 nginx `file_server` 静态托管（`/_astro` 可缓存 immutable） |
| 发布延迟   | 即时                            | 重建完成（目标 ≤ 2 分钟）                                         |
| `/admin`   | Astro SSR                       | 保持 SSR（唯一需要 Node 的路径）                                  |
| 搜索       | SSR 页面                        | 空壳 + 客户端 `fetch('/api/search')`                              |
| 动态数据   | 无评论、无浏览量                | 无（本版已移除）                                                  |

### B.3 阻塞项清单（迁移前必须闭环）

| #   | 阻塞项                | 现状                                        | 3.0.0 预留                                                | 未来动作                                                                                                                                             |
| --- | --------------------- | ------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1  | 页面数据聚合          | 每页 1+N 次请求                             | **R1** `/api/bootstrap` + `page_data()`                   | 构建期调用同一接口                                                                                                                                   |
| B2  | query 分页            | `/tags/x?page=2`                            | **R2** 路径式分页 + 旧 URL 301                            | `getStaticPaths` 按路径生成                                                                                                                          |
| B3  | 请求上下文依赖        | 未系统审计                                  | **R3** 公共页禁 cookie/session/UA + CI 检查               | 无（本版已保证）                                                                                                                                     |
| B4  | 派生图就绪            | 请求时可能触发编码；SSG 会把占位烘焙进 HTML | **R4** `derivative_set` 物化 + `image_payload` 只读       | 构建前置条件：目标媒体 ready；不 ready 则构建失败并保留上一版                                                                                        |
| B5  | 构建与发布管道        | 不存在（compose 只有 backend/frontend）     | **R5** 定义 `jobs.kind='rebuild_site'` 形状，不实现执行器 | 新增 builder 容器（需 Node + 只读 API 访问 + 共享产物卷）+ 原子切换 + 失败保留上一版 + 告警                                                          |
| B6  | 静态资产托管切换      | `/_astro` 由 Astro 进程提供                 | **R6** 页面不引用运行期临时路径                           | 二选一并写入部署文档：nginx 托管 `/_astro`（需在重建后同步 frontend 进程/构建，否则 `/admin` 引用旧哈希）或继续由 Astro 提供资产（少一层静态化收益） |
| B7  | 重建触发与延迟        | 无                                          | **R5** + `jobs` 表 + 内容变更事件                         | 发布/取消发布/删除/外观/导航/SEO 写入 `rebuild_site`；合并 5s 内多次请求；定时发布到点触发                                                           |
| B8  | 搜索页                | SSR                                         | 无（`/api/search` 已在）                                  | `/search` 改成静态空壳 + 客户端取数                                                                                                                  |
| B9  | sitemap / RSS         | SSR 生成                                    | R1 的同一数据接口                                         | 构建期生成文件                                                                                                                                       |
| B10 | 404 / slug 变更重定向 | SSR 可动态判断                              | 无                                                        | 需 `redirects` 表或构建期生成的跳转清单（本次未决策，见 10.1）                                                                                       |
| B11 | 草稿/定时发布的可见性 | SSR 天然正确                                | `jobs` 已定义                                             | 构建只含 published；定时任务到点触发重建                                                                                                             |
| B12 | 规模                  | 未测                                        | 无                                                        | 500 篇以内全量构建能否 ≤ 60s；超限评估增量构建/分区                                                                                                  |

### B.4 备选方案对比

| 方案                                         | 收益                        | 成本/风险                                                | 结论                              |
| -------------------------------------------- | --------------------------- | -------------------------------------------------------- | --------------------------------- |
| A. Astro 预渲染（SSG）+ 静态托管             | 运行期零渲染、TTFB 最优     | 构建/发布管道 + 资产托管切换 + 重建延迟                  | **未来目标**，3.0.0 只做预留      |
| B. 保留 SSR + 接入层短 TTL `proxy_cache`     | 不改渲染模型，TTFB 改善明显 | 缓存失效与 Cookie/`Set-Cookie` 排除要正确；延迟以 TTL 计 | **可选过渡**，写进 `docs/EDGE.md` |
| C. 保持 SSR + 应用侧 ETag/短缓存（本版默认） | 零新增基础设施，改动最小    | 每次请求仍有组装成本                                     | **3.0.0 采用**                    |

### B.5 未来迁移工作量（不含 3.0.0 预算）

- 构建器与发布管道（B5）：2~3 人日。
- 资产托管切换与 `/admin` 协调（B6）：0.5~1 人日。
- 重建触发、合并、失败保留与告警（B7）+ sitemap/RSS（B9）：1~2 人日。
- 规模压测与增量/分区（B12）：1~2 人日。
- 合计约 **5~8 人日** + 一次 staging→生产演练；若 B6 选择“继续由 Astro 提供资产”，可减 1 人日但静态化收益打折。

### B.6 不迁移的后果

- 保持 SSR：每页仍有组装成本，接入层缓存只能做到 TTL 级；流量峰值时需要靠缓存与限流吸收。
- 由于本版已完成 R1~R7，**迁移只是基础设施工作**；反之若不做预留，未来迁移会重新触碰页面模板与数据访问层（估计多 3~5 人日返工）。

## 附录 D：归档审查（2026-10-23）

> 归档前对全文逐项核对：对照仓库当前实现、CI 与验收脚本，登记完成情况、与正文记录的差异、以及按设计未执行的项。结论见文末。

### D.1 Phase 0–5 完成情况

| 阶段               | 核对结果（证据）                                                                                                                                                                                                                                         |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 0 地基       | ✅ 代理代码与 `BLOG_PROXY_SECRET` 已无残留；`astro.config.mjs` 保留 dev-only Vite proxy；`GET /api/health/edge` 存在并有集成测试；`docs/EDGE.md` 就绪；ruff/mypy/eslint/prettier/pre-commit/CI 全部在仓；版本 3.0.0 一致                                 |
| Phase 1 契约与配置 | ✅ `app/settings/{models,store}.py` 分组设置与默认值单源；`openapi.json` 中 `additionalProperties: true` 实测 0 处；契约生成 + CI drift 检查（`types.gen.ts`）；`fallbackSite` 已删除                                                                    |
| Phase 2 数据与授权 | ✅ `migrations/0001_init.sql` + `scripts/db.py`；`posts`/`project_details`；评论/浏览量仅剩说明性注释（`grep` 无功能残留）；`owner_id` + `services/authz.py`；会话/限流 job 化                                                                           |
| Phase 3 媒体       | ✅ 流式上传、`token/pipeline_version/quality` 派生图、`jobs`（`reencode` + reserved `rebuild_site`）、未就绪占位、质量常量化均有实现与测试                                                                                                               |
| Phase 4 前端与预留 | ✅ `/api/bootstrap` + `page_data()`；页面 ETag/`no-store`；`/tags                                                                                                                                                                                        | /categories/.../page/{n}`路由 + 旧`?page=` 301；`check_public_render` 进入 CI（R3）；`derivative_set`/`rebuild_site` 预留；`dom.ts`/`form.ts`/`theme.ts` 落地；样式收口已在发布前补齐（见 §3.9） |
| Phase 5 收尾       | ✅ FTS5（`0003_content_fts.sql` + `test_search.py`）；3.x 导出/导入（`routes/export.py` + `test_export_import.py`）；GC/`scripts/backup.py` 与恢复演练说明；2.x 文档归档 + 现行文档重写；删除清单已执行；`scripts/verify.py` 一键验收（含 `docs-drift`） |

### D.2 与正文记录的差异（以实现为准）

| 正文写法                                         | 实际实现                                                                                       |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| 数据库：`SCHEMA_VERSION = 1`（当时计划重置编号） | 实际为 **`SCHEMA_VERSION = 3`**（`migrations/0001…0003`，根 README 与 `scripts/db.py` 均为 3） |
| 契约文件 `api.types.gen.ts`                      | `frontend/src/api/types.gen.ts`（`npm run gen:types` 生成）                                    |
| 生成脚本 `scripts/docs/gen.py`                   | `backend/app/scripts/gen_docs.py`（`python -m app.scripts.gen_docs`）                          |
| 验收脚本 `scripts/verify.sh`                     | `scripts/verify.py`（另有 `.sh`/`.ps1` 包装；步骤清单见文件头）                                |
| Phase 4 "本阶段不做样式收口"                     | 已在 3.0.0 发布前补齐（Phase 1–6，见 §3.9 状态更新）                                           |
| 正文："发布后移到 `docs/archive/3.0.0/`"         | 已执行；本文件所在路径即归档路径                                                               |

### D.3 按设计未执行 / 发布时接受的偏差

| 项                                                     | 状态                                                                                                                          |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Playwright E2E（§6.2 的 3 条主流程）                   | 未配置；§8 风险表已把 playwright 定位为 nightly 降级项，3.0.0 以 pytest HTTP 集成 + `check_public_render` + verify smoke 覆盖 |
| 覆盖率数字门禁（服务层 ≥80%、`frontend/src/lib` ≥70%） | 未设自动阈值；沿用正文 §8 的 ratchet 策略（CI 跑 pytest，无硬阈值）                                                           |
| TODO-D11 版本号与 git tag 一致性 CI                    | 版本号一致性由发布流程人工保证；CI 未做 tag 校验                                                                              |
| SSG / 2.x 导入 / 多 worker                             | 按正文明确不做：SSG 仅预留、无 2.x 导入通道、多 worker 启动即拒绝                                                             |
| nginx 配置                                             | 按正文不提交仓库，仅 `docs/EDGE.md` 核对清单 + staging/CI 验证                                                                |

### D.4 §11 文档待办

- 11.1（D01–D04）✅：`docs/archive/2.x/` 三份归档 + `docs/archive/README.md` 索引。
- 11.2（D05–D10）✅：README / DEVELOPMENT / SCHEMA / API / EDGE / SSG-FEASIBILITY 均已重写或由脚本生成；D11 部分完成（见 D.3）。
- 11.3 完成定义：旧内容 100% 归档 ✅；新文档数字有脚本来源或采集日期 ✅；`docs-drift` 与契约 drift CI ✅；行号/链接检查未单独脚本化（§6.3 规则保留，发布前人工核对）。

### D.5 审查结论

3.0.0 计划内的实现类任务（Phase 0–5）全部完成；§11 文档待办全部完成（D11 的 CI 部分除外）；§6.2 测试矩阵除 Playwright E2E 与覆盖率数字门禁外均已落地。D.3 列出的偏差是发布时明确接受的取舍，不是隐藏的未完成项。本文自归档后不再更新，现行状态见仓库根 `README.md` 与 `docs/` 下的现行文档。
