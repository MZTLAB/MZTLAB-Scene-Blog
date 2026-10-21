"""First-run demo content for the Scene theme (3.0.0).

Demo content is explicit opt-in: it is only written when `BLOG_SEED_DEMO=true`.
The demo is deliberately small: three articles, four projects, one about page
and three photo galleries. Gallery images are generated as flat colour studies
so a fresh clone has something to look at without shipping binary assets.

Seeding is idempotent and all-or-nothing. Every row carries a NOT NULL
`owner_id`, so seeding only starts once an account exists (the setup page calls
it again after the first account is created) and stops as soon as any content
already exists. Delete anything from the admin and it stays deleted.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from .config import SEED_DEMO, UPLOAD_DIR
from .content import extract_toc, make_excerpt, reading_time, render_markdown, slugify
from .db import db, now_iso
from .exif import dump_exif, read_exif_bytes

logger = logging.getLogger("mztlab.seed")

CATEGORIES = {
    "影像": ("photography", "光、结构与日常画面。"),
    "书写": ("writing", "影像之外的观察。"),
    "档案": ("archive", "笔记、参考与索引。"),
}

TAGS = [
    "自然光", "城市", "结构", "长曝光", "室内", "品牌", "排版",
    "工作方法", "色彩", "田野",
]

ARTICLES: list[dict[str, Any]] = [
    {
        "title": "练习看：一张照片在成为照片之前",
        "slug": "learning-to-see",
        "category": "影像",
        "tags": ["自然光", "工作方法", "色彩"],
        "featured": 1,
        "days_ago": 3,
        "excerpt": "取景框不是画框。按下快门之前，真正发生的事情是选择：放弃什么，留下什么。",
        "content": """\
## 先减法，再构图

刚拿起相机时，我总想把看到的好东西全部塞进画面：远处的山、近处的花、路过的人。结果每一样都在，每一样都不重要。

后来我给自己定了一条很笨的规矩：**一个画面只允许有一个主角**。如果说不清主角是谁，就先不按快门。

一条水平线，一块色域，一个形状的边界——这些已经足够支撑一张照片。构图不是往里加，而是往外拿。

## 光是被记录的材料

光和建筑一样，是可以被测量的材料。它决定影子的长度、色温的倾向、材质表面的粗糙程度。

- 清晨的光偏冷，影子长而软；
- 正午的光短而硬，适合切分结构；
- 傍晚的光带一点橙，适合交代温度。

我不追求"黄金时刻"这四个字，只关心此刻的光能不能把我想说的那句话说完整。

> 好照片不是被拍到的，是被等到的。

## 保留失败

硬盘里有一个叫 `rejects` 的文件夹，存着每次拍摄里最不满意的帧。三个月后回头翻，常常能从里面找到当时看不见的东西——也许是下一个系列的起点。

练习看，就是愿意多看几次。""",
    },
    {
        "title": "一间工作室的秩序：把工具降到最低",
        "slug": "studio-order",
        "category": "书写",
        "tags": ["工作方法", "室内", "结构"],
        "featured": 0,
        "days_ago": 16,
        "excerpt": "关于工作台的整理、文件的命名、以及为什么我最后只留了三支镜头。",
        "content": """\
## 桌面是第一张照片

工作室的桌面每天都会被拍进背景里，所以它首先是一件道具。

规则只有三条：台面只放正在用的东西；线材全部收到桌子背面；每一件工具都有固定位置。听起来像整洁强迫症，实际效果是——**脑子里的噪音少了一半**。

## 文件命名是一种语法

我用同一个模式给所有文件命名：

```text
YYYY-MM-DD_location_subject_vNN
```

排序、检索、备份都不需要额外软件。日期在前，是因为时间是最稳定的坐标；版本在后，是因为同一张照片往往要被推翻很多次。

## 三支镜头

卖掉多余的镜头之后，我发现常用的焦段其实非常集中。限制带来的不是不便，而是更快的决定。

- 一支广角，用来交代空间；
- 一支标准，用来记录关系；
- 一支中长焦，用来剥离背景。

工具减少之后，注意力才有地方放。""",
    },
    {
        "title": "在城市的背面工作：一组城市影像",
        "slug": "habitat-notes",
        "category": "影像",
        "tags": ["城市", "自然光", "田野"],
        "featured": 0,
        "days_ago": 34,
        "excerpt": "HABITAT 拍摄了四十天。这篇笔记记录方法、失误，以及一次被保安请出去的下午。",
        "content": """\
## 一次关于居所的观察

HABITAT 想回答一个很朴素的问题：人们如何在自己的居住空间里留下痕迹。

我们走进 26 户人家，不用闪光灯，不移动任何家具，只在他们原本的生活里待一个下午。

## 方法

- 先聊四十分钟，再打开相机；
- 只用自然光，等眼睛适应房间的暗；
- 每户至少拍一个"没有人的角落"。

最后一条最关键。人不在画面里，但所有痕迹都在说话：门口的鞋、桌上的杯子、窗帘被拉开的角度。

## 失误

有三次拍摄几乎完全失败：一次是雨天，一次被保安请出去，一次是存储卡在关键帧前写满。

失败记录和成片放在同一个目录里。它们提醒我，这些画面是由具体的时间、具体的疲劳堆出来的，而不是一组漂亮的结论。

## 结果

最终选了 18 张照片，做成一本 64 页的小书。没有大道理，只有一些可以被反复观看的房间。""",
    },
]

ABOUT_PAGE = """\
## MZTLAB

影像、项目与文字。

- **影像**：自然光、空间与痕迹。
- **项目**：把想法做成可以运行、可以维护的东西。
- **文字**：方法、过程与回看。

少说一点，多看一会儿，多动手一次。
"""


# Code projects reuse the posts table (`type = 'project'`), so the three
# columns on the home page share one content pipeline and one admin editor.
PROJECTS: list[dict[str, Any]] = [
    {
        "title": "Scene Engine / 博客引擎",
        "slug": "scene-engine",
        "kind": "代码",
        "year": "2026",
        "role": "设计 / 全栈",
        "client": "内部工具",
        "url": "https://github.com/",
        "featured": 1,
        "days_ago": 6,
        "excerpt": "一个刻意保持小的博客系统：Astro 负责页面，FastAPI + SQLite 负责内容与权限。",
        "content": """\
## 要解决的问题

我想让写文章、整理相册和发布图片发生在同一个地方，并且不引入 Redis、任务队列或前端框架。整个站点只有两个进程和一个 SQLite 文件。

```text
浏览器 → Astro SSR → FastAPI → SQLite
```

## 做法

- **数据先行**：文章、页面、相册、照片、项目共用一套所有权与权限；
- **少依赖**：Markdown 用 `markdown` + `bleach`，图片用 Pillow，认证用 scrypt；
- **可迁移**：数据库升级靠 `PRAGMA user_version`，不装迁移框架；
- **慢一点**：不追求实时，服务端渲染已经足够。

## 结果

部署成本是一台最小规格的机器。备份只需要复制 `backend/data` 目录。

> 工具应该消失在内容后面。""",
    },
    {
        "title": "Scene Grid / 场景式作品集",
        "slug": "index-portfolio",
        "kind": "代码",
        "year": "2025",
        "role": "信息架构 / 前端",
        "client": "独立工作室",
        "url": "",
        "featured": 0,
        "days_ago": 40,
        "excerpt": "把照片、项目与文字放进同一组等宽列里，让三种工作获得同等的注意力。",
        "content": """\
## 问题

作品集很容易变成某一种内容的展示柜：照片最大、文字最少，项目只是附件。但三种工作其实是同一件事的三个侧面。

## 结构

首页只保留一个内容区，横向三列：

1. **影像** — 以相册为单位；
2. **项目** — 以「年份 / 角色 / 上下文」为单位；
3. **文字** — 以时间为单位。

每列只露出三条，数量、字号、留白完全一致。读者自己决定往哪个方向走。

## 细节

- 三列共用一套网格与行高；
- 不设置主次，避免「精选」压过其他内容；
- 移动端按同一顺序纵向堆叠。

平衡不是平均，而是每种内容都有同等被看见的机会。""",
    },
    {
        "title": "Field Notes / 田野记录器",
        "slug": "field-notes-cli",
        "kind": "代码",
        "year": "2025",
        "role": "命令行工具",
        "client": "个人项目",
        "url": "https://github.com/",
        "featured": 0,
        "days_ago": 90,
        "excerpt": "在户外用一个命令记下时间、位置与一段文字，回到工作室自动整理成 Markdown。",
        "content": """\
## 背景

拍摄时最缺的是记录：光线的方向、当时的声音、为什么按下这一次快门。手机备忘录会把这些打散。

## 工具

一个很小的 Python 命令行程序：

```bash
fieldnote "下午四点的侧面光" --tag light --tag studio
```

- 写入一行 JSONL，包含时间、坐标与标签；
- 回到工作室运行 `fieldnote build`，按日期生成 Markdown；
- 输出目录正好是博客的文章目录。

## 收获

记录的门槛要足够低，低到不需要决定「这算不算一篇文章」。先记下来，再决定它的形状。""",
    },
    {
        "title": "Slow Light / 光的短片",
        "slug": "slow-light-film",
        "kind": "影像",
        "year": "2024",
        "role": "导演 / 摄影 / 剪辑",
        "client": "独立短片 · 12 分钟",
        "url": "",
        "featured": 0,
        "days_ago": 18,
        "excerpt": "一部关于清晨光线的短片。这里只放文字介绍，影像本身在别处放映。",
        "content": """\
## 说明

这是一部视频项目的文字档案。站点本身不承载视频文件，也不嵌入播放器——只记录它是什么、为什么拍、以及后来发生了什么。

## 短片

**《Slow Light》**，12 分钟，彩色，2024 年。

镜头跟随一间朝东的工作室，从日出前一小时到上午十点。没有旁白，没有配乐，只有环境声与光在墙面上的移动。

## 拍摄方式

- 固定机位，三个月的清晨，每天拍同一条时间线；
- 不补光，不调色，只做最基本的曝光匹配；
- 剪辑顺序按光的入射角排列，而不是按拍摄日期。

## 为什么放出文字而不是视频

视频需要合适的带宽与播放环境。这里保留它的观看说明、场次与制作笔记；观看链接只在私下分享，不放在公开页面上。

## 后来

短片在两次小型放映中出现，之后一直放在硬盘里。它教给我的事比它本身更重要：**有些作品的价值在于过程被完整地走了一遍**。""",
    },
]


# ---------------------------------------------------------------------------
# Demo photo sets (generated on first run)
# ---------------------------------------------------------------------------

_PALETTES = [
    {"bg": (242, 240, 234), "ink": (24, 24, 22), "accent": (232, 72, 29)},
    {"bg": (28, 30, 32), "ink": (238, 236, 230), "accent": (196, 208, 92)},
    {"bg": (226, 222, 212), "ink": (48, 52, 58), "accent": (186, 96, 62)},
    {"bg": (238, 234, 226), "ink": (32, 36, 44), "accent": (74, 106, 138)},
    {"bg": (20, 22, 24), "ink": (232, 226, 214), "accent": (222, 118, 62)},
    {"bg": (246, 244, 238), "ink": (18, 18, 18), "accent": (108, 128, 104)},
]

_SIZES = [(1600, 1067), (1200, 1500), (1600, 900), (1400, 1400), (1500, 1000)]

GALLERIES: list[dict[str, Any]] = [
    {
        "title": "FORM / 结构练习",
        "slug": "form-studies",
        "description": "一组关于边界、遮挡与比例的照片。多数画面里只有一块色域和一条线。",
        "featured": 1,
        "days_ago": 8,
        "palette": 0,
        "count": 6,
        "location": "上海 · 杨浦",
        "camera": "Ricoh GR III",
        "lens": "28mm",
    },
    {
        "title": "NOCTURNE / 夜色",
        "slug": "nocturne",
        "description": "入夜之后的城市表面。光源很少，形状因此更清楚。",
        "featured": 0,
        "days_ago": 24,
        "palette": 1,
        "count": 5,
        "location": "杭州 · 拱墅",
        "camera": "Sony A7C",
        "lens": "35mm",
    },
    {
        "title": "FIELD / 田野笔记",
        "slug": "field-notes",
        "description": "在城镇边缘拍下的材料与光线。没有主线，只有一段时间的气味。",
        "featured": 0,
        "days_ago": 52,
        "palette": 2,
        "count": 5,
        "location": "浙江 · 临安",
        "camera": "Fujifilm X-T4",
        "lens": "23mm",
    },
]


def _iso(days_ago: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(days=days_ago))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _has_content(conn: sqlite3.Connection) -> bool:
    """True when any authorizable content row already exists."""
    return bool(
        conn.execute("SELECT 1 FROM posts LIMIT 1").fetchone()
        or conn.execute("SELECT 1 FROM galleries LIMIT 1").fetchone()
    )


def _first_owner_id(conn: sqlite3.Connection) -> int | None:
    """Prefer the first administrator, otherwise the first account."""
    row = conn.execute(
        "SELECT id FROM users ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, id LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def _seed_taxonomy(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    """Create the demo categories/tags in `taxonomy_terms` (idempotent)."""
    created_at = now_iso()
    category_ids: dict[str, int] = {}
    for name, (slug, description) in CATEGORIES.items():
        row = conn.execute(
            "SELECT id FROM taxonomy_terms WHERE kind = 'category' AND slug = ?", (slug,)
        ).fetchone()
        if row:
            category_ids[name] = int(row["id"])
            continue
        cur = conn.execute(
            """INSERT INTO taxonomy_terms(kind, name, slug, description, created_at)
               VALUES ('category', ?, ?, ?, ?)""",
            (name, slug, description, created_at),
        )
        category_ids[name] = int(cur.lastrowid)

    tag_ids: dict[str, int] = {}
    for name in TAGS:
        slug = slugify(name)
        row = conn.execute(
            "SELECT id FROM taxonomy_terms WHERE kind = 'tag' AND slug = ?", (slug,)
        ).fetchone()
        if row:
            tag_ids[name] = int(row["id"])
            continue
        cur = conn.execute(
            """INSERT INTO taxonomy_terms(kind, name, slug, description, created_at)
               VALUES ('tag', ?, ?, '', ?)""",
            (name, slug, created_at),
        )
        tag_ids[name] = int(cur.lastrowid)
    return category_ids, tag_ids


def _insert_post(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    *,
    owner_id: int,
    post_type: str = "post",
    category_id: int | None = None,
    tag_ids: list[int] | None = None,
) -> int:
    content_md = str(entry["content"]).strip() + "\n"
    content_html = render_markdown(content_md)
    published = _iso(int(entry.get("days_ago", 7)))
    cur = conn.execute(
        """INSERT INTO posts(
               type, title, slug, excerpt, content_md, content_html, cover_image,
               status, published_at, featured, owner_id,
               reading_time, toc_json, seo_title, seo_description,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, '', '', ?, ?)""",
        (
            post_type,
            entry["title"],
            entry["slug"],
            entry.get("excerpt") or make_excerpt(content_md),
            content_md,
            content_html,
            entry.get("cover_image", ""),
            published,
            1 if entry.get("featured") else 0,
            owner_id,
            reading_time(content_md),
            json.dumps(extract_toc(content_html), ensure_ascii=False),
            published,
            published,
        ),
    )
    post_id = int(cur.lastrowid)
    if post_type == "project":
        conn.execute(
            """INSERT INTO project_details(post_id, kind, year, role, client, url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                entry.get("kind", ""),
                entry.get("year", ""),
                entry.get("role", ""),
                entry.get("client", ""),
                entry.get("url", ""),
            ),
        )
    if category_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO post_terms(post_id, term_id) VALUES (?, ?)",
            (post_id, category_id),
        )
    for tag_id in tag_ids or []:
        conn.execute(
            "INSERT OR IGNORE INTO post_terms(post_id, term_id) VALUES (?, ?)",
            (post_id, tag_id),
        )
    return post_id


def _draw_study(index: int, palette: dict[str, tuple[int, int, int]], size: tuple[int, int]):
    from PIL import Image, ImageDraw, ImageFont

    width, height = size
    image = Image.new("RGB", size, palette["bg"])
    draw = ImageDraw.Draw(image)
    ink = palette["ink"]
    accent = palette["accent"]
    unit = min(width, height)

    shape = index % 6
    if shape == 0:
        draw.rectangle([width * 0.08, height * 0.18, width * 0.52, height * 0.86], fill=ink)
        draw.rectangle([width * 0.62, height * 0.52, width * 0.92, height * 0.56], fill=accent)
    elif shape == 1:
        draw.ellipse(
            [width * 0.34, height * 0.08, width * 0.34 + unit * 0.6, height * 0.08 + unit * 0.6],
            fill=accent,
        )
        draw.line([(0, height * 0.78), (width, height * 0.78)], fill=ink, width=max(2, unit // 220))
    elif shape == 2:
        draw.rectangle([0, height * 0.42, width, height * 0.62], fill=ink)
        draw.rectangle([width * 0.7, height * 0.12, width * 0.86, height * 0.4], fill=accent)
    elif shape == 3:
        draw.rectangle([width * 0.06, height * 0.1, width * 0.46, height * 0.9], fill=ink)
        draw.rectangle([width * 0.54, height * 0.1, width * 0.94, height * 0.9], fill=accent)
    elif shape == 4:
        draw.rectangle([width * 0.2, height * 0.2, width * 0.8, height * 0.8], fill=ink)
        draw.rectangle(
            [width * 0.2 + unit * 0.05, height * 0.2 + unit * 0.05, width * 0.8 - unit * 0.05, height * 0.8 - unit * 0.05],
            fill=palette["bg"],
        )
        draw.rectangle([width * 0.5, 0, width * 0.52, height], fill=accent)
    else:
        draw.line([(width * 0.1, height * 0.9), (width * 0.9, height * 0.1)], fill=ink, width=max(3, unit // 140))
        draw.ellipse(
            [width * 0.58, height * 0.58, width * 0.58 + unit * 0.24, height * 0.58 + unit * 0.24],
            fill=accent,
        )

    label = f"MZTLAB / {index + 1:02d}"
    try:
        font = ImageFont.load_default(size=max(14, unit // 34))
    except TypeError:  # pragma: no cover - very old Pillow
        font = ImageFont.load_default()
    draw.text((width * 0.05, height * 0.94), label, fill=ink, font=font, anchor="ls")
    return image


class _DemoPhoto(TypedDict):
    """One generated demo photo, fully materialised before the DB transaction."""

    filename: str
    original_name: str
    data: bytes
    width: int
    height: int
    exif: str
    alt: str
    title: str
    caption: str
    location: str
    camera: str
    lens: str
    taken_at: str
    featured: bool
    sort_order: int
    created_at: str


class _DemoGallery(TypedDict):
    entry: dict[str, Any]
    created_at: str
    photos: list[_DemoPhoto]


def _lens_mm(lens: object) -> float:
    digits = "".join(ch for ch in str(lens) if ch.isdigit())
    return float(digits) if digits else 35.0


def _render_demo_photos() -> list[_DemoGallery]:
    """Draw every demo photo and write the originals to `UPLOAD_DIR`.

    Pillow encoding and file writes are deliberately kept outside the SQLite
    write transaction (`db()` docs): only the row inserts take the write lock.
    """
    from PIL import Image  # local import: Pillow is only needed when seeding

    rendered: list[_DemoGallery] = []
    photo_index = 0
    for gallery in GALLERIES:
        palette = _PALETTES[gallery["palette"] % len(_PALETTES)]
        created_at = _iso(int(gallery["days_ago"]))
        taken = datetime.now(timezone.utc) - timedelta(days=int(gallery["days_ago"]))
        exif_datetime = taken.strftime("%Y:%m:%d %H:%M:%S")
        taken_date = taken.strftime("%Y-%m-%d")
        lens_mm = _lens_mm(gallery["lens"])
        short_title = str(gallery["title"]).split("/")[0].strip()
        photos: list[_DemoPhoto] = []

        for index in range(int(gallery["count"])):
            size = _SIZES[(photo_index + index) % len(_SIZES)]
            image = _draw_study(photo_index + index, palette, size)
            exif = Image.Exif()
            exif[0x010F] = str(gallery["camera"]).split()[0]
            exif[0x0110] = gallery["camera"]
            exif[0x0131] = "Scene demo generator"
            exif[0x0132] = exif_datetime
            exif[0x8769] = {
                0x9003: exif_datetime,
                0xA434: gallery["lens"],
                0x829D: 2.8,
                0x829A: (1, 250),
                0x8827: 200,
                0x920A: lens_mm,
            }
            buffer = io.BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=88,
                optimize=True,
                progressive=True,
                exif=exif,
            )
            data = buffer.getvalue()
            filename = f"seed/{gallery['slug']}-{index + 1:02d}.jpg"
            target = UPLOAD_DIR / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

            photos.append(
                _DemoPhoto(
                    filename=filename,
                    original_name=f"{gallery['slug']}-{index + 1:02d}.jpg",
                    data=data,
                    width=size[0],
                    height=size[1],
                    exif=dump_exif(read_exif_bytes(data)),
                    alt=f"{gallery['title']} 第 {index + 1} 帧",
                    title=f"{short_title} {index + 1:02d}",
                    caption="自然光下的表面与边界。",
                    location=str(gallery["location"]),
                    camera=str(gallery["camera"]),
                    lens=str(gallery["lens"]),
                    taken_at=taken_date,
                    featured=index == 0,
                    sort_order=(index + 1) * 10,
                    created_at=created_at,
                )
            )

        rendered.append(
            _DemoGallery(entry=gallery, created_at=created_at, photos=photos)
        )
        photo_index += len(photos)
    return rendered


def _seed_galleries(
    conn: sqlite3.Connection, owner_id: int, galleries: list[_DemoGallery]
) -> None:
    for item in galleries:
        entry = item["entry"]
        created_at = item["created_at"]
        cur = conn.execute(
            """INSERT INTO galleries(title, slug, description, status, featured,
                                     cover_photo_id, owner_id, created_at, updated_at)
               VALUES (?, ?, ?, 'published', ?, NULL, ?, ?, ?)""",
            (
                entry["title"],
                entry["slug"],
                entry["description"],
                1 if entry["featured"] else 0,
                owner_id,
                created_at,
                created_at,
            ),
        )
        gallery_id = int(cur.lastrowid)
        cover_photo_id: int | None = None

        for photo in item["photos"]:
            media_cur = conn.execute(
                """INSERT INTO media(filename, original_name, mime, size, width, height,
                                     alt, owner_id, exif, created_at)
                   VALUES (?, ?, 'image/jpeg', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    photo["filename"],
                    photo["original_name"],
                    len(photo["data"]),
                    photo["width"],
                    photo["height"],
                    photo["alt"],
                    owner_id,
                    photo["exif"],
                    photo["created_at"],
                ),
            )
            photo_cur = conn.execute(
                """INSERT INTO photos(gallery_id, media_id, filename, title, caption,
                                      location, camera, lens, taken_at, width, height,
                                      featured, status, sort_order, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)""",
                (
                    gallery_id,
                    int(media_cur.lastrowid),
                    photo["filename"],
                    photo["title"],
                    photo["caption"],
                    photo["location"],
                    photo["camera"],
                    photo["lens"],
                    photo["taken_at"],
                    photo["width"],
                    photo["height"],
                    1 if photo["featured"] else 0,
                    photo["sort_order"],
                    photo["created_at"],
                ),
            )
            if cover_photo_id is None:
                cover_photo_id = int(photo_cur.lastrowid)

        conn.execute(
            "UPDATE galleries SET cover_photo_id = ? WHERE id = ?",
            (cover_photo_id, gallery_id),
        )


def _seed_posts(conn: sqlite3.Connection, owner_id: int) -> None:
    category_ids, tag_ids = _seed_taxonomy(conn)

    for entry in ARTICLES:
        _insert_post(
            conn,
            entry,
            owner_id=owner_id,
            category_id=category_ids.get(entry["category"]),
            tag_ids=[tag_ids[name] for name in entry["tags"]],
        )

    # Code/video projects reuse the posts pipeline; their own metadata lives in
    # `project_details` (class-table inheritance).
    for entry in PROJECTS:
        _insert_post(conn, entry, owner_id=owner_id, post_type="project")

    _insert_post(
        conn,
        {
            "title": "关于 MZTLAB",
            "slug": "about",
            "excerpt": "影像、项目与文字。",
            "content": ABOUT_PAGE,
        },
        owner_id=owner_id,
        post_type="page",
    )


def seed_demo_content() -> None:
    """Seed the opt-in demo content once; safe to call on every startup."""
    if not SEED_DEMO:
        return

    with db() as conn:
        # `owner_id` is NOT NULL, so demo content can only exist after the first
        # account. The setup route calls this function again once it is created.
        if _first_owner_id(conn) is None:
            logger.info("demo seed deferred: no user account exists yet")
            return
        if _has_content(conn):
            return

    # Drawing and encoding the demo JPEGs is slow: keep Pillow and disk writes
    # outside the SQLite write transaction and only insert rows inside it.
    photo_sets = _render_demo_photos()

    with db() as conn:
        # Re-check inside the transaction: a concurrent process may have seeded
        # first, and there is deliberately no version marker to coordinate on.
        if _has_content(conn):
            return
        owner_id = _first_owner_id(conn)
        if owner_id is None:
            logger.info("demo seed deferred: no user account exists yet")
            return
        _seed_posts(conn, owner_id)
        _seed_galleries(conn, owner_id, photo_sets)


def ensure_bootstrap_admin() -> None:
    """Optionally create the first administrator from environment variables.

    Runs independently of demo seeding, so a production deployment can disable
    demo content and still bootstrap its account from .env / Docker. Idempotent:
    it does nothing once any account exists.
    """
    from .config import BOOTSTRAP_ADMIN_NAME, BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_ADMIN_USER
    from .security import hash_password, password_policy_error
    from .security import logger as security_logger

    if not (BOOTSTRAP_ADMIN_USER and BOOTSTRAP_ADMIN_PASSWORD):
        return
    problem = password_policy_error(BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_ADMIN_USER)
    if problem:
        security_logger.warning("bootstrap administrator password is weak: %s", problem)
    now = now_iso()
    with db() as conn:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        conn.execute(
            """INSERT INTO users(username, password_hash, display_name, email,
                                 bio, avatar, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, '', '', '', 'admin', 1, ?, ?)""",
            (
                BOOTSTRAP_ADMIN_USER.lower(),
                hash_password(BOOTSTRAP_ADMIN_PASSWORD),
                BOOTSTRAP_ADMIN_NAME,
                now,
                now,
            ),
        )
