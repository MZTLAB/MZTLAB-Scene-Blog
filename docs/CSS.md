# MZTLAB · Scene 样式系统（CSS）

> 适用版本：3.0.0
>
> 面向维护者：样式文件在哪、级联顺序怎么定、令牌从哪来、改一处 CSS 要跑哪些验证。
> 架构与后端约定见 [`DEVELOPMENT.md`](DEVELOPMENT.md)；本轮样式重构的动因与范围见 [`REFACTOR-3.0.0.md`](REFACTOR-3.0.0.md) 的 §O 与 §3.9。

---

## 目录

- [1. 架构与目录](#1-架构与目录)
- [2. 加载与级联](#2-加载与级联)
- [3. 令牌契约](#3-令牌契约)
- [4. 文件粒度与归属](#4-文件粒度与归属)
- [5. 如何新增或修改样式](#5-如何新增或修改样式)
- [6. 验证与护栏](#6-验证与护栏)
- [7. 与其他文档的关系](#7-与其他文档的关系)
- [8. 不做与边界](#8-不做与边界)

## 1. 架构与目录

一句话：样式全部拆成 `@layer` 分层的**全局文件**，由渲染它的组件自己 import；令牌只定义一处，运行时由 `<html>` 上的内联变量覆盖。

重构前是五张按 import 顺序互相覆盖的全局表（合计约 9,500 行）：`global.css`（约 3,000 行）、`admin.css`（约 4,200 行）、`index.css`（约 1,480 行）、`mono.css`（约 440 行）、`audio-player.css`（约 345 行）。公共站叠加三代（`global` → `mono` → `index`），后台叠加两代（`global` → `admin`），`admin.css` 末尾还挂着约 1,440 行 `html[data-theme="scene"]` 覆盖段；`data-theme="scene"` 与 `data-palette` 两套主题机制并存。层叠结果因此由 import 顺序决定，顺序没人敢动。

```text
frontend/src/styles/
├── tokens/              设计令牌：只有声明，不含组件外观（每文件 ≤ 80 行）
│   ├── layers.css       层序说明（每条文件也带 banner，权威声明在 layout <head> 内联，见 §2.2）
│   ├── typography.css · accent.css · palette.css · metrics.css · colors.css
│   │                    字体栈与 data-font / 强调色 / palette × 明暗 / 尺寸节奏 /
│   │                    从组件里抽出的 58 个精确色值别名（--color-*，零视觉变化）
│   └── admin/           palette.css、metrics.css（后台冻结值 + 2 个响应式覆盖）
├── base/                reset、elements、layout、type-devices（150–250 行/文件）
├── shared/              公共站与后台都用的组件：prose、brand、icon-btn、avatar
├── site/                只在公共站渲染的组件，按域分目录
│   ├── shell/           header、footer、shell.css（.site-body 排版）、
│   │                    refinements.css（mono/index 对 base/shared 的公共站专用细化 + 公共站 reduced-motion）
│   │                    refinements-late.css（必须晚于 shell.css 的两条标题字距）
│   ├── home/            masthead（Hero）、pillars、cta-band
│   ├── cards/           story / project / gallery 卡片、cover-art
│   ├── photos/          photo-grid、lightbox、gallery-viewer、gallery-page
│   ├── articles/        article（文章页正文与元信息）
│   ├── journal/         journal-list（首页/归档的条目列表）
│   ├── pages/           archive / search / project / page-hero / notfound
│   └── ui/              pagination、empty-state、section-headings
├── admin/               后台：shell、nav、topbar、cards、dashboard、tables、badges、toolbar、
│                        buttons、forms、editor×3、media、galleries、taxonomy、appearance、
│                        settings、users、auth、modal、feedback
└── audio-player.css     唯一保留的单文件（约 350 行），仍属 components 层
```

共 **65 个样式文件**（重构前 5 张表、合计约 9,500 行），0 个文件超过 400 行。

## 2. 加载与级联

### 2.1 三套 layout 的 import 顺序

| Layout        | import 顺序                                                                                                                                                                                                                    |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `BaseLayout`  | `tokens/layers` → `typography` → `accent` → `palette` → `metrics` → `colors` → `base/*` → `site/shell/refinements.css` → `site/shell/shell.css` → `site/shell/refinements-late.css`；其余样式由组件/页面自己 import            |
| `AdminLayout` | `tokens/layers` → `typography` → `accent` → `palette` → `metrics` → `colors` → `tokens/admin/palette` → `tokens/admin/metrics` → `base/*` → `shared/*` → `admin/` 公共原语（shell…feedback，含 dashboard）→ `audio-player.css` |
| `AuthLayout`  | `tokens/*`（含 admin 变体）→ `base/*` → `shared/brand` → `shared/icon-btn` → `admin/auth` → `admin/buttons` → `admin/forms`                                                                                                    |

只有 **tokens + base（+ shell 级几个文件）** 是 layout 级导入，其余全部由拥有该块的组件/页面 import。`astro.config.mjs` 开着 `build.inlineStylesheets: 'auto'`，Astro 只把当前路由真正用到的样式表内联或链进页面：漏 import 会直接表现为样式缺失（快照会抓到）。

`site/shell/refinements.css` 与 `refinements-late.css` 是零视觉变化的产物：前者的规则来自旧 `mono.css`/`index.css`，只作用于公共站（后台从未加载这两个表，所以不能放进 `base/`/`shared/`）；后者只放两条必须在 `.site-body h1/h2/h3` 之后生效的标题字距。后台的 `tokens/admin/*` 同理是旧 `global.css` 值的冻结副本。这些文件在后续整理中可以显式收敛，收敛时必须逐条看 `css:diff`。

### 2.2 层序

层序只有一条：`@layer tokens, base, components, pages, utilities;`

| 层           | 放什么                                             | 会压过（层序越后越强）                      |
| ------------ | -------------------------------------------------- | ------------------------------------------- |
| `tokens`     | 令牌声明（颜色、字体、尺寸）                       | 谁都不压：只提供 `var()` 值，不参与外观竞争 |
| `base`       | reset、元素默认、布局原语、共享排版装置            | `tokens`                                    |
| `components` | `shared/`、`site/`、`admin/`、`audio-player.css`   | `tokens`、`base`                            |
| `pages`      | 某个页面独有的组合样式（默认不用，能放组件就别建） | `tokens`、`base`、`components`              |
| `utilities`  | 少量**有意**压过组件的工具类                       | 下面所有层                                  |

每个文件恰好一个 `@layer <名字> { ... }`；**不建子层**（`@layer components.cards` 这类会让层序按首次出现注册，顺序不可预测，快照工具的层序排名也会失真）。

### 2.3 为什么层序独立于 import 顺序

- **权威声明在 layout `<head>` 里**：三套 layout 的 `<head>` 第一行是 `<style is:inline>@layer tokens, base, components, pages, utilities;</style>`，它在任何 `<link rel="stylesheet">` 之前，保证浏览器看到的第一个 `@layer` 语句就是完整顺序。
  为什么不能只靠文件 banner：Vite/rollup 会把 route chunk 里重复的 `@layer …;` 语句去重，拆分包后页面 chunk 可能先于共享 chunk 加载，banner 缺失的文件里的 `@layer components {` 会把 `components` 注册成第 0 层，整个层序反转。`@layer` 的注册顺序只看**首次出现**，所以必须有一处"永远最先出现"的声明。
- 每个文件顶部仍然保留同一条 banner（`css:check` 强制），用途是可读性和"单独拷贝一个文件也自洽"；层序正确性由 layout 内联声明兜底，不依赖 banner 的相对顺序。
- 之后的 import 顺序只影响**同一层内**的源序，跨层永远按层序比较。于是"谁渲染谁 import"是安全的：新增或挪动一个组件的 import 位置，不会改变已有元素的胜出声明 —— 这是组件级拆分成立的前提。

### 2.4 `custom_css` 的优先级契约

- 后台「设置 → 外观 → 自定义 CSS」（`appearance.custom_css`）由 `BaseLayout` 以 `<style is:inline>` 注入在 `<body>` 末尾、所有样式表之后，**不带 `@layer`**；只用于站点个性化（隐藏、微调、加装饰），不要用它承载新组件。
- 非分层（unlayered）的 normal 声明胜过任何分层声明，与特异性无关 —— 运营写的覆盖一定生效，这是有意设计。
- 反向例外：`!important` 在层内更强，分层 `!important` 会压过非分层 `!important`。所以运营侧不要用 `!important` 去顶组件样式，团队侧组件层也禁止 `!important`（`css:check` 报白名单外的用法）。
- 快照把它当普通 `<style>` 一起收集，改 `custom_css` 会让 diff 非空 —— 那属于设置变更，不是样式重构回归。

## 3. 令牌契约

### 3.1 运行时内联令牌

| 令牌              | 注入处                      | 取值来源                                      | CSS 侧兜底                             |
| ----------------- | --------------------------- | --------------------------------------------- | -------------------------------------- |
| `--accent`        | 三套 layout                 | `normalizeTheme()`：`#rrggbb`，否则 `#c2451f` | `tokens/accent.css`                    |
| `--layout-width`  | `BaseLayout`、`AdminLayout` | 720–1600 夹取；公共 1360 / 后台 1400          | `tokens/metrics.css`                   |
| `--radius`        | 三套 layout                 | 0–40 夹取                                     | `tokens/metrics.css`（0px）            |
| `--photo-columns` | 仅 `BaseLayout`             | 2–4，来自 `site.gallery_columns`              | 调用侧 `var(--photo-columns, 3)`       |
| `--hero-image`    | 仅 `BaseLayout`（有图时）   | `appearance.hero_image`，URL 已转义           | 无消费方，用 `var(--hero-image, none)` |

- 内联值写在 `<html style>`，特异性等同行内样式，只有 `!important` 能压过它；所以令牌默认值只能写在 `:root` / `html` 上，且不得加 `!important`。令牌是"运行时值 + 文件兜底"两段式：改站点值去后台设置，改未注入时的默认值去 `tokens/`。
- `AuthLayout` 只注入 `--accent`、`--radius`（宽度走 `tokens/admin/metrics.css` 的 1400 兜底）；后台与登录页不注入 `--photo-columns` / `--hero-image`，后台文件不得假设这两个存在。

### 3.2 四套 palette × 明暗

| palette         | 选择器                       | 说明                                   |
| --------------- | ---------------------------- | -------------------------------------- |
| `scene`（默认） | `:root`                      | 纸感画布，未设置 `data-palette` 时的值 |
| `stone`         | `html[data-palette='stone']` | 冷灰调                                 |
| `sand`          | `html[data-palette='sand']`  | 暖沙调                                 |
| `night`         | `html[data-palette='night']` | 夜间画布                               |

- `data-color-mode="dark"` 与 `html[data-palette='night']` 共用同一组夜间值，写在文件末尾：同特异性下后出现的胜出 —— 这是重构前的实际行为，所以明暗与 palette 重叠时不打架。
- `data-color-mode="system"` 是**服务端瞬时值**：三套 layout 的内联脚本在首帧前按 `prefers-color-scheme` 换成 `light` / `dark` 并写 `localStorage` 的 `scene-color-mode`。CSS 里不要为 `system` 写规则。
- `data-font` 只换 `--font-display`：`serif` 换成衬线栈，`mono` 与默认都落回 `--font-mono`，正文栈不变。

### 3.3 为什么后台有单独的 palette / metrics

零视觉变化约束。后台画布是纯白、`--header-height` 68（≤900px 时 60）、`--layout-width` 1400（公共 1360）、gutter / gap / band 也各略不同；这些值来自旧 `global.css` 的不同代际，并进公共 palette 会让整个后台位移。

做法：`tokens/admin/palette.css` 与 `tokens/admin/metrics.css` 是后台值的**冻结副本**，只在 `AdminLayout` / `AuthLayout` 引入，公共 token 文件保持公共站的值。想合并成一套是一次显式决策：改完跑 `css:diff`，差异只应落在后台，逐条确认后重拍基线并在本文件记录（`REFACTOR-3.0.0.md` §3.9 把它列为后续候选）。

**使用规则**：组件文件只消费 `var(--token)`，不写字面色值与像素魔法数（例外：`1px` 发丝线、`0`、`100%`、`transparent`、`currentColor`）；新令牌按颜色→`palette`、字体→`typography`、尺寸与节奏→`metrics` 归位，后台专属进 `tokens/admin/`；组件内的局部变量必须同文件声明、同文件消费，命名以 `--local-` 开头且不放 `:root`。

## 4. 文件粒度与归属

### 4.1 一个选择器只有一个所有者

同一个选择器（含 `:hover`、`::before`、媒体查询里的同一选择器）只允许出现在一个文件里。跨文件重复等于把"谁赢"重新交回 import 顺序，等于撤销这次重构；`css:check` 拒绝新增的重复，存量重复在拆分批次里就地合并，不做"再加一层覆盖"。

### 4.2 放哪一层

| 归属             | 判据                                              | 例子                                                                                                      |
| ---------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `base/`          | 元素级默认，不依赖任何页面类名                    | `body`、`a`、`img`、`hr`、`::selection`、容器/栅格/纵向节奏                                               |
| `shared/`        | 公共站与后台都会渲染的组件                        | prose、brand、icon-btn、avatar                                                                            |
| `site/<domain>/` | 只有公共站渲染的组件                              | `SiteHeader` → `shell/header.css`；`HomeHero` → `home/masthead.css`；`StoryCard` → `cards/story-card.css` |
| `admin/`         | 后台外壳、ui 原语、`editor`、按功能页分块         | `admin/media.css`、`admin/editor.css`                                                                     |
| `pages/`         | 整个页面独有的组合，且只有该页 import（默认不用） | 复杂页面确实需要组合层时才建                                                                              |
| `utilities/`     | 确实要"故意压过组件"的少量工具类                  | 打印、无障碍隐藏                                                                                          |

### 4.3 响应式、动态 DOM、行数与命名

- **响应式**：媒体查询写在选择器后面（同一文件），不集中到 `responsive.css`——改一处宽高比要在一个文件里看全。断点沿用现状（最常用 900，另有 620 / 720 / 760 / 860 / 1020 / 1080 / 1180 与 `prefers-reduced-motion: reduce`），新增块复用同文件已有断点，不引入新断点。
- **JS 动态生成的 DOM**：脚本生成的节点（Lightbox、GalleryViewer、后台列表、编辑器、音频嵌入）拿不到 Astro 作用域属性，样式必须留在全局分层文件里并**跟着宿主组件走**；类名以脚本模块为前缀，脚本改类名时同一提交改对应样式文件。这也是"不改成 Astro 作用域样式"的理由，见 §8。
- **行数与命名**：单文件 400 行硬上限、目标 150–250，`tokens` ≤ 80；超限先拆域（`admin/media.css` → `admin/media-grid.css` + `admin/media-dialog.css`），不拆层。文件名 kebab-case 且与宿主同名：`GalleryCard.astro` → `site/cards/gallery-card.css`；`admin/posts/index.astro` → `admin/posts.css`。
- **文件头**：每条样式文件的第一条语句都是层序 banner（注释可写在它前面），随后恰好一个 `@layer <层名> { … }`；`css:check` 校验"banner 存在且未被挤到后面"和"规则都在已知层内"：

```css
/* gallery-card · owner: components/GalleryCard.astro */
@layer tokens, base, components, pages, utilities;

@layer components {
  /* … */
}
```

## 5. 如何新增或修改样式

前置：以下 `npm run` 均在 `frontend/` 下执行（仓库根没有 `package.json`）。快照对着**正在跑的站点与 API** 工作（默认 `--base http://127.0.0.1:4322`、`--api http://127.0.0.1:18123`，端口不同就显式传；`npm run dev` / `start` 默认 4321）。后台路由需要能登录的 smoke 账号（`CSS_ADMIN_USER` / `CSS_ADMIN_PASSWORD`，默认 `smoke-admin` / `Sm0ke-Test-Passphrase!`），登录失败会整段跳过后台；`scripts/verify.ps1` 的 smoke 只起后端、用临时数据目录，别拿它当快照目标。

### 5.1 改一个已有组件的样式

1. 找所有者：`npm run css:inventory`，或 `rg -n '\.gallery-card' frontend/src/styles` 确认该选择器只有一个文件。
2. 只改那个文件、那一层；需要更强的覆盖时改所有者，不加新覆盖。
3. `npm run css:check`（banner、单层、行数、`!important`）。
4. `npm run css:snapshot -- --out .tmp/css-snap/after.json.gz`，再 `npm run css:diff .tmp/css-snap/baseline.json.gz .tmp/css-snap/after.json.gz`；纯重构要求 diff 为空，有意的视觉调整要求 diff 只命中预期的元素与属性，确认后重拍基线。

### 5.2 新增一个组件（含样式）

1. 定归属（§4.2）：两套 layout 都用 → `shared/`；只公共站 → `site/<domain>/`；只后台 → `admin/`。
2. 建 `components/Foo.astro` 与对应 CSS：文件头 banner + 恰好一个 `@layer components { ... }`，行数落在 150–250。
3. 组件里用相对路径 import：`import '../styles/site/cards/foo.css';`（路径按组件所在目录算，不从页面出发）。
4. `npm run build`：确认新样式只出现在渲染它的路由的样式表里（组件级 import 落地后即可逐页核对，见 §2.1）；再 `npm run css:check` + 快照/diff —— 新增组件会有"new element"差异，属预期，其余差异必须为零。

### 5.3 改令牌或配色

1. 只改默认值：颜色 → `tokens/palette.css`（后台 → `tokens/admin/palette.css`），字体 → `typography.css`，尺寸 → `metrics.css`；运行时四个值（accent / layout-width / radius / photo-columns）不要硬编码进组件，只 `var()` 消费。
2. `npm run css:check`（tokens 行数 ≤ 80、无 `!important`、只有声明）。
3. 快照/diff：令牌改动必然产生 `token[...]` 差异，逐条核对；确实删除令牌时用 `--allow-token-removed <名>` 单独放行。
4. 全链路：`./scripts/verify.ps1 --skip-slow`（跳过 mypy / pytest / build，含前端 check、lint 与 smoke）；需要构建产物时另跑 `npm run build` 或完整 `./scripts/verify.ps1`。

### 5.4 命令速查

| 命令（在 `frontend/` 下）                     | 作用                                                                             | 何时跑                     |
| --------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------- |
| `npm run build`                               | Astro 构建，产出 per-route CSS 拆分                                              | 每次改完                   |
| `$env:BLOG_CSS_UNMINIFIED='1'; npm run build` | 未压缩构建（`vite.build.cssMinify=false`），拍快照必须用                         | refactor / 等价性验收      |
| `npm run css:snapshot` / `css:diff`           | 拍级联快照 / 比对两份快照                                                        | 改前拍基线、改后比对       |
| `npm run css:inventory`                       | 只读报告：文件行数、`@media`/`@layer` 密度、跨文件重复、`!important`、硬编码颜色 | 找归属、查超限             |
| `npm run css:check`                           | 结构检查，逐条打印 `ERROR` / `WARN <文件>:<行> <规则>`                           | 提交前（CI 加 `--strict`） |
| `./scripts/verify.ps1 --skip-slow`            | 快速全链路（前端 check/lint + smoke）                                            | 提交前                     |

四条 `css:*` 命令都已接进 `package.json`。`css:inventory` 是规划辅助，**不改变退出码**；`css:check` 默认只报告，加 `--strict` 才在有 ERROR 时以 1 退出（`--allow-important` 可传白名单）。

## 6. 验证与护栏

### 6.1 等价性快照如何工作

`frontend/scripts/css/snapshot.mjs` 四步：**渲染**（抓 27 条代表性路由，公共页 + 后台页，后台先 `POST /api/auth/login` 拿 cookie）→ **收集**（解析每页 HTML，取出该页实际 `link` / `style` 的样式表再下载缓存，组件级 import 的效果在这里被看见；`<head>` 的内联 `@layer …;` 也被当成第一条声明解析，所以层序判定与浏览器一致）→ **计算**（解析每个声明的选择器、`@media`、`@layer`、源序、`!important`，对每个元素每个属性算出胜出声明：层序 → 特异性 → 源序；`:hover` / `:focus` 等状态与 `::before` 等伪元素各进独立桶；令牌单独一拍，只取能命中 `<html>` 的声明，按视口 × 6 套主题各存一份 `--*` 值）→ **比对**（`diff.mjs` 逐路由 → 视口 → 主题 → 元素/属性比较最终 `prop=value`，退出码 0 = 完全一致，1 = 列出差异，`--limit` 控条数；`--allow-removed-prop` / `--added-prop` 放行声明中已确认的令牌增删）。

**必须用未压缩构建拍快照**：生产构建里 lightningcss 会把简写/长写合并（`transition` ↔ `transition-*`），声明级比较会出现大量无意义的差异。`astro.config.mjs` 提供了开关：

```powershell
# 在 frontend/ 下
$env:BLOG_CSS_UNMINIFIED='1'; npm run build   # vite.build.cssMinify = false
npm run css:snapshot -- --out ../.tmp/css-snap/after.json.gz
npm run css:diff ../.tmp/css-snap/baseline-unmin.json.gz ../.tmp/css-snap/after.json.gz `
  --allow-removed-prop '--shadow-soft,--shadow-card' --allow-added-prop '<--color-* 列表>'
```

本轮重构的最终验收：**27 路由 × 3 视口 × 6 主题下与重构前 HEAD 构建逐元素逐属性完全一致**（57,931 个元素桶、486 组令牌；仅放行两个已删除死令牌与 58 个 `--color-*` 精确别名）。补丁改过 `snapshot.mjs` 的两处：`@layer` 尾随语句解析（内联层序）与 `var(--color-*)` 到字面值的解析（否则色值别名会被当成差异）。

### 6.2 矩阵：27 路由 × 3 视口 × 6 主题

- 视口：1440、390，外加 1440 + `prefers-reduced-motion`。
- 主题：`scene-light`、`scene-dark`、`stone-light`、`sand-light`、`night`、`serif`。
- 路由由 `/api/bootstrap` 的真实内容生成（文章/相册/项目各取一条，标签/分类各取一条，后台 15 条），是"当前数据下的代表集"而非硬编码清单；后台登录失败时后台路由整段跳过，`--no-admin` 可显式跳过 —— 跳过不等于通过。

### 6.3 `css:inventory` 与 `css:check` 各自查什么

- `css:inventory`（只读、不影响退出码）：逐文件大小、`@media` / `@layer` 密度、跨文件重复、`!important` 与硬编码颜色 —— 规划与"找归属"用，先看它再动手。
- `css:check` 八条规则：① 层序 banner 存在且是第一条语句；② 规则都在已知层内（未分层或未知层报错）；③ 行数（> 250 警告、> 400 错误）；④ 单所有者（跨文件重复的选择器 + 属性）；⑤ `!important`；⑥ `tokens/` 之外的硬编码颜色；⑦ 孤儿样式表（没有任何 `.astro`/`.ts` import 它）；⑧ 遗留根文件（`global.css`、`mono.css`、`index.css`）。
- `tokens/layers.css` 与 `styles/archive/` 豁免；输出格式固定为 `ERROR|WARN <文件>:<行> <规则> <详情>`，便于 CI 抓取。
- 有意豁免已写进工具：④ 不会把 `tokens/admin/*` ↔ `tokens/*`、`site/shell/refinements*`/`site/shell/header.css` ↔ 它们的 `shared/*` 对应文件算作重复（这些是公共站/后台的零视觉变化冻结副本）；⑤ 用 `--allow-important animation,transition,animation-duration,transition-duration,width,height,color,letter-spacing` 放行 reduced-motion reset 与已知历史用法。
- 当前基线（重构完成时）：`css:check` 剩 **2 个 ERROR**（`admin/media.css` 的 2 个 `font-size !important`，属于后续收敛项）+ 119 个 WARN（`duplicate-prop` 106 = 多代际规则按代际分开保存的预期结果；`size.warn` 13 = 250–400 行文件；其余规则 0）。硬编码颜色 0、孤儿 0、遗留根文件 0、层序 banner 65/65。`css:inventory` 报告 65 个文件、`!important` 共 23 条（集中在 5 个文件）。

## 7. 与其他文档的关系

| 文档                                                            | 关系                                                                                                                                                                    |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`DEVELOPMENT.md`](DEVELOPMENT.md)                              | §2.3 给出前端分层与目录职责，§13 是编码约定与风险清单。样式相关**以本文件为准**；§13 里"2.x 样式原样保留"的表述属于重构前状态，随重构落地由维护者更新，本文件不重复它。 |
| [`REFACTOR-3.0.0.md`](REFACTOR-3.0.0.md) §3.9                   | 原候选设计（当时标注"本版不实施"）+ 落地后的"状态更新"块：实施结果、层序内联声明的真实原因、验证矩阵与生产负载数字、剩余后续项。                                        |
| [`tokens/layers.css`](../frontend/src/styles/tokens/layers.css) | 层序的一手事实源：层名、各层意图、`custom_css` 为何不分层都写在那段注释里。本文 §2.2 是它的展开；两者冲突时以 `layers.css` 为准，并回来改本文。                         |

版本规则同其它文档：主版本升级时整体移入 `docs/archive/{旧版本}/` 后重写，不在旧文上打补丁。

## 8. 不做与边界

- **不引入** Tailwind / 原子类 / CSS-in-JS / CSS Modules：类名与模板、脚本已经耦合，换命名空间要同步改 JS，收益不抵风险。
- **不把已有全局类改成 Astro `<style>` 作用域**：Lightbox、GalleryViewer、后台列表、编辑器、音频嵌入的节点都是脚本动态生成的，拿不到 scope 属性，样式会静默失效。新组件即使不被脚本生成，也照样放全局分层文件以保持一致。
- **不引入 stylelint**：`css:check` 覆盖本轮需要的结构规则；将来要做"令牌之外禁止硬编码"的完整规则集再评估。
- **`audio-player.css` 不拆**：约 345 行、宿主清晰（prose 内的音频嵌入），拆开只会让 `<audio>` 相关规则分散。
- **不做视觉改版（本轮已验收）**：级联快照与重构前 HEAD 构建逐元素逐属性一致；配色、断点、间距、类名不变。后续 Phase 5 语义收敛（字号刻度、断点、色板）需要单独开批次，按 `≤0.5px` 差异逐条视觉验收。
- **生产负载实测**（minified，逐文件 gzip 相加）：公共页均值 74.4 → 22.7 KB raw（−69%）、15.2 → 6.2 KB gzip（−59%）；后台 105.5 → 40.9 KB raw（−61%）、19.6 → 9.9 KB gzip（−49%）；样式表请求 3 → 4–8 个小文件，部署端应开 HTTP/2 或 HTTP/3。
- **不建子层、不写 600 行级大文件、不允许多个文件共同拥有一个选择器**。
- 组件级 import 的硬性约定：路径相对组件文件，只 import 自己拥有的那一个文件；一个文件只属于一个宿主，文件名 = 宿主名（kebab-case）；`tokens/` 与 `base/` 只由三套 layout import，组件与页面不得直接 import；Astro 页面（`src/pages/**`）不 import 别的组件的样式；同一个 CSS 被多处 import 由 Astro/Vite 去重，但仍须满足"单层 + banner + 唯一所有者"。
