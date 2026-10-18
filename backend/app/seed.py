"""First-run demo content for the Scene theme.

The demo is deliberately small: three articles, one about page and three photo
galleries. Gallery images are generated as flat colour studies so a fresh
clone has something to look at without shipping binary assets in the repo.

Delete anything from the admin and it stays deleted. To start empty, set
`BLOG_SEED_DEMO=false` before the first launch.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import SEED_DEMO, UPLOAD_DIR
from .content import make_excerpt, render_markdown, slugify
from .db import db, now_iso
from .exif import dump_exif, read_exif_bytes

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
        "views": 148,
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
        "views": 96,
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
        "views": 233,
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

影像与文字。

- **影像**：自然光、空间与痕迹。
- **文字**：方法、过程与回看。

少说一点，多看一会儿。
"""


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


def _insert_post(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    category_id: int | None,
    tag_ids: list[int],
    *,
    post_type: str = "post",
    author_id: int | None = None,
) -> int:
    content = entry["content"].strip() + "\n"
    published = _iso(int(entry.get("days_ago", 7)))
    cur = conn.execute(
        """INSERT INTO posts(
               type, title, slug, excerpt, content_md, content_html, cover_image,
               status, featured, allow_comments, author_id, published_at,
               created_at, updated_at, seo_title, seo_description, view_count
           ) VALUES (?, ?, ?, ?, ?, ?, '', 'published', ?, ?, ?, ?, ?, ?, '', '', ?)""",
        (
            post_type,
            entry["title"],
            entry["slug"],
            entry.get("excerpt") or make_excerpt(content),
            content,
            render_markdown(content),
            1 if entry.get("featured") else 0,
            0 if post_type == "page" else 1,
            author_id,
            published,
            published,
            published,
            int(entry.get("views", 0)),
        ),
    )
    post_id = int(cur.lastrowid)
    if category_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO post_categories(post_id, category_id) VALUES (?, ?)",
            (post_id, category_id),
        )
    for tag_id in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO post_tags(post_id, tag_id) VALUES (?, ?)",
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


def _seed_galleries(conn: sqlite3.Connection, author_id: int | None) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM galleries").fetchone()[0]
    if existing:
        return

    now = now_iso()
    seed_dir = UPLOAD_DIR / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    photo_index = 0

    for gallery in GALLERIES:
        palette = _PALETTES[gallery["palette"] % len(_PALETTES)]
        cur = conn.execute(
            """INSERT INTO galleries(title, slug, description, status, featured,
                                     cover_photo_id, author_id, view_count, created_at, updated_at)
               VALUES (?, ?, ?, 'published', ?, NULL, ?, ?, ?, ?)""",
            (
                gallery["title"],
                gallery["slug"],
                gallery["description"],
                1 if gallery["featured"] else 0,
                author_id,
                int(gallery.get("views", 0)),
                _iso(int(gallery["days_ago"])),
                _iso(int(gallery["days_ago"])),
            ),
        )
        gallery_id = int(cur.lastrowid)
        taken = datetime.now(timezone.utc) - timedelta(days=int(gallery["days_ago"]))
        exif_datetime = taken.strftime("%Y:%m:%d %H:%M:%S")
        taken_date = taken.strftime("%Y-%m-%d")
        try:
            lens_mm = float("".join(ch for ch in str(gallery["lens"]) if ch.isdigit()) or 35)
        except ValueError:
            lens_mm = 35.0

        cover_photo_id: int | None = None
        from PIL import Image

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

            media_cur = conn.execute(
                """INSERT INTO media(filename, original_name, mime, size, width, height,
                                     alt, uploaded_by, owner_id, exif, created_at)
                   VALUES (?, ?, 'image/jpeg', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filename,
                    f"{gallery['slug']}-{index + 1:02d}.jpg",
                    len(data),
                    size[0],
                    size[1],
                    f"{gallery['title']} 第 {index + 1} 帧",
                    author_id,
                    author_id,
                    dump_exif(read_exif_bytes(data)),
                    _iso(int(gallery["days_ago"])),
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
                    filename,
                    f"{gallery['title'].split('/')[0].strip()} {index + 1:02d}",
                    "自然光下的表面与边界。",
                    gallery["location"],
                    gallery["camera"],
                    gallery["lens"],
                    taken_date,
                    size[0],
                    size[1],
                    1 if index == 0 else 0,
                    (index + 1) * 10,
                    _iso(int(gallery["days_ago"])),
                ),
            )
            if cover_photo_id is None:
                cover_photo_id = int(photo_cur.lastrowid)
            photo_index += 1

        conn.execute(
            "UPDATE galleries SET cover_photo_id = ? WHERE id = ?",
            (cover_photo_id, gallery_id),
        )


DEMO_SEED_VERSION = 3


def seed_demo_content() -> None:
    """Idempotent. Runs once per database, tracked by a private setting."""
    if not SEED_DEMO:
        return
    with db() as conn:
        marker = conn.execute(
            "SELECT value FROM settings WHERE key = 'demo_seed_version'"
        ).fetchone()
        if marker is not None:
            try:
                seeded_version = int(str(marker["value"]).strip('"'))
            except (TypeError, ValueError):
                seeded_version = DEMO_SEED_VERSION
            if seeded_version >= DEMO_SEED_VERSION:
                return

        has_articles = conn.execute(
            "SELECT 1 FROM posts WHERE type = 'post' LIMIT 1"
        ).fetchone()
        has_about = conn.execute(
            "SELECT 1 FROM posts WHERE type = 'page' AND slug = 'about'"
        ).fetchone()

        category_ids: dict[str, int] = {}
        for name, (slug, description) in CATEGORIES.items():
            row = conn.execute("SELECT id FROM categories WHERE slug = ?", (slug,)).fetchone()
            if row:
                category_ids[name] = int(row["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO categories(name, slug, description, created_at) VALUES (?, ?, ?, ?)",
                    (name, slug, description, now_iso()),
                )
                category_ids[name] = int(cur.lastrowid)

        tag_ids: dict[str, int] = {}
        for name in TAGS:
            row = conn.execute("SELECT id FROM tags WHERE slug = ?", (slugify(name),)).fetchone()
            if row:
                tag_ids[name] = int(row["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO tags(name, slug, description, created_at) VALUES (?, ?, '', ?)",
                    (name, slugify(name), now_iso()),
                )
                tag_ids[name] = int(cur.lastrowid)

        article_ids: list[int] = []
        if not has_articles:
            for entry in ARTICLES:
                article_ids.append(
                    _insert_post(
                        conn,
                        entry,
                        category_ids.get(entry["category"]),
                        [tag_ids[name] for name in entry["tags"]],
                    )
                )
        has_comments = conn.execute("SELECT 1 FROM comments LIMIT 1").fetchone()
        if article_ids and not has_comments:
            _seed_comments(conn, article_ids[0])

        if not has_about:
            entry = {
                "title": "关于 MZTLAB",
                "slug": "about",
                "excerpt": "影像与文字。",
                "content": ABOUT_PAGE,
                "views": 0,
            }
            _insert_post(conn, entry, None, [], post_type="page")

        _seed_galleries(conn, _first_admin_id(conn))

        conn.execute(
            """INSERT INTO settings(key, value, updated_at) VALUES ('demo_seed_version', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                              updated_at = excluded.updated_at""",
            (str(DEMO_SEED_VERSION), now_iso()),
        )


def _first_admin_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM users ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, id LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def ensure_bootstrap_admin() -> None:
    """Optionally create the first administrator from environment variables.

    This runs independently of demo seeding, so a production deployment can
    disable demo content and still bootstrap its account from .env / Docker.
    """
    from .config import BOOTSTRAP_ADMIN_NAME, BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_ADMIN_USER
    from .security import hash_password

    if not (BOOTSTRAP_ADMIN_USER and BOOTSTRAP_ADMIN_PASSWORD):
        return
    now = now_iso()
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if exists:
            return
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, display_name,
                                 email, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, '', 'admin', 1, ?, ?)""",
            (
                BOOTSTRAP_ADMIN_USER.lower(),
                hash_password(BOOTSTRAP_ADMIN_PASSWORD),
                BOOTSTRAP_ADMIN_NAME,
                now,
                now,
            ),
        )
        user_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE posts SET author_id = ? WHERE author_id IS NULL", (user_id,)
        )
        conn.execute(
            "UPDATE galleries SET author_id = ? WHERE author_id IS NULL", (user_id,)
        )
        conn.execute(
            "UPDATE media SET uploaded_by = ?, owner_id = ? "
            "WHERE uploaded_by IS NULL AND owner_id IS NULL",
            (user_id, user_id),
        )


def _seed_comments(conn: sqlite3.Connection, post_id: int) -> None:
    comments = [
        (
            "林间",
            "lin@example.com",
            "这组照片的顺序很有意思，最后一张像是把前面的房间都关上了。",
            "approved",
            1,
        ),
        (
            "Mori",
            "mori@example.com",
            "在搜索里偶然路过，已经订阅 RSS。期待看到更多影像笔记。",
            "approved",
            3,
        ),
        (
            "小满",
            "xiaoman@example.com",
            "想问一下拍摄时用的自然光处理方式，是全程不补光吗？",
            "pending",
            5,
        ),
    ]
    for name, email, content, status, days_ago in comments:
        conn.execute(
            """INSERT INTO comments(post_id, author_name, author_email, content,
                                    status, ip, created_at)
               VALUES (?, ?, ?, ?, ?, '', ?)""",
            (post_id, name, email, content, status, _iso(days_ago)),
        )
