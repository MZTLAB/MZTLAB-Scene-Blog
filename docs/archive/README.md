# 文档归档索引

> 适用版本：3.0.0
>
> 本目录保存已退役的历史文档。归档文档只作追溯参考，**请勿据此部署或开发**；现行文档见下方“当前文档入口”。

## 版本目录

| 目录 | 归档日期 | 说明 |
| --- | --- | --- |
| [`2.x/`](2.x/) | 2026-10-21 | MZTLAB · Scene 2.x 的 README、开发文档与图片管线方案（3.0.0 发布前原貌） |

### `2.x/`

| 文件 | 原路径 | 说明 |
| --- | --- | --- |
| [`2.x/README.md`](2.x/README.md) | `README.md` | 2.x 使用说明与功能概览 |
| [`2.x/DEVELOPMENT.md`](2.x/DEVELOPMENT.md) | `docs/DEVELOPMENT.md` | 2.x 工程手册（含旧迁移章节与行号引用，已过时） |
| [`2.x/IMAGE-PIPELINE-PLAN.md`](2.x/IMAGE-PIPELINE-PLAN.md) | `docs/IMAGE-PIPELINE-PLAN.md` | 图片管线实现方案；内容已并入 3.0.0 的开发文档与 `docs/SCHEMA.md` |

每个归档文件顶部只加了历史横幅，正文保持归档时的原貌（未做增量修改）。

## 2.x → 3.0.0 差异摘要

- **单层接入**：删除 Astro 内嵌代理（`/api`、`/media` 转发）与代理密钥；生产由运维 nginx 路由，本地由 Vite dev proxy 路由。仓库不提交 nginx 配置，见 `docs/EDGE.md`。
- **无评论、无浏览量**：评论表/接口/审核页/文案与浏览量自增、展示、统计全部删除。
- **分组设置**：142 键扁平 KV → `site` / `appearance` / `copy` / `upload` / `advanced` 五组带类型的 JSON 文档；S3 凭据仅来自环境变量。
- **类表继承**：文章/项目/页面共用 `posts`，项目专属字段入 `project_details`；所有权统一为 `owner_id`。
- **持久化 jobs**：`jobs` 表 + 单 worker 线程（心跳、恢复、取消），取代进程内进度字典。
- **产物级 token**：图片派生层以 `sha1(PIPELINE_VERSION|media_id|source_sha1|scene|width|format|quality)` 作为 token，`media.derivative_set` 物化就绪状态；质量是代码常量，存量图像不自动重编码。
- **SSG 预留**：聚合读接口 `/api/bootstrap`、路径式分页、渲染上下文审计、`derivative_set`、`rebuild_site` 任务形状等；SSG 本身不在 3.0.0 实现。
- **不兼容升级**：3.0.0 只支持空库初始化（`SCHEMA_VERSION=3`），不提供 2.x 数据导入。

## 当前文档入口

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| [`README.md`](../../README.md) | 使用者 / 部署者 | 定位、能力、快速开始、升级政策、运维要点 |
| [`docs/DEVELOPMENT.md`](../DEVELOPMENT.md) | 维护者 | 架构、数据层、配置、写入管线、授权、媒体管线、契约生成、测试 |
| [`docs/EDGE.md`](../EDGE.md) | 运维 | 接入层（nginx）要求、转发头、核对清单与参考片段（不含可部署配置） |
| [`docs/SCHEMA.md`](../SCHEMA.md) | 维护者 | 数据库结构（由脚本生成，勿手改） |
| [`docs/API.md`](../API.md) | 维护者 / 集成方 | API 端点表（由脚本生成，勿手改） |
| [`docs/SSG-FEASIBILITY.md`](../SSG-FEASIBILITY.md) | 维护者 | SSG 可行性、阻塞项与 3.0.0 预留闭环状态 |
| [`docs/REFACTOR-3.0.0.md`](../REFACTOR-3.0.0.md) | 维护者 | 3.0.0 重构方案（历史方案文档，保留在原路径，未随文档重写移动） |

> 说明：按用户要求，`docs/REFACTOR-3.0.0.md` **保留在原始路径**，不归档、不改名、不改内容；它记录的是 3.0.0 的决策与计划，而不是当前操作手册。
