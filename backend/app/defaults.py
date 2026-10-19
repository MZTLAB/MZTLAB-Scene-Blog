"""Defaults for the public site.

The out-of-the-box look is *Scene*: a quiet, monospaced canvas for photographs
and writing. Every value can be changed at runtime from 管理后台 → 外观 / 设置;
this file is the origin of those defaults and the allow-list of public setting
keys.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .config import MAX_UPLOAD_BYTES

# Upload policy defaults. The admin can change the maximum size and enable a
# subset of these formats from 设置 → 上传与媒体; these tuples are the safe
# allow-list the settings are validated against.
UPLOAD_IMAGE_FORMATS: tuple[str, ...] = ("jpg", "png", "webp", "gif")
UPLOAD_AUDIO_FORMATS: tuple[str, ...] = ("mp3", "m4a", "ogg", "oga", "wav", "flac")
# Extra, non-media files. The catalog is deliberately limited to formats that
# cannot execute in the browser; the admin enables a subset from settings.
UPLOAD_FILE_FORMATS: tuple[str, ...] = (
    "pdf", "zip", "txt", "md", "csv", "json", "docx", "xlsx", "pptx",
)
DEFAULT_UPLOAD_FILE_FORMATS = "pdf,zip,txt,md,csv"
UPLOAD_FORMAT_ALIASES = {"jpeg": "jpg", "tif": "jpg", "tiff": "jpg"}
DEFAULT_UPLOAD_MAX_MB = max(1, MAX_UPLOAD_BYTES // (1024 * 1024))

DEFAULT_SETTINGS: dict[str, Any] = {
    # Identity ---------------------------------------------------------------
    # Text defaults mirror the owner's current appearance configuration, so a
    # fresh database starts from the same copy that is live today.
    "site_title": "MZTLAB",
    "site_subtitle": "Scene",
    "tagline": "影像、项目与文字。",
    "description": "MZTLAB 是一间以影像、项目与文字为媒介的独立工作室档案。",
    "site_url": "http://127.0.0.1:4321",
    "logo": "",
    "favicon": "",
    "author_name": "MightZero",
    "author_bio": "以影像记录光，以项目验证想法，以文字整理观察。",
    "author_avatar": "",

    # Appearance -------------------------------------------------------------
    "theme": "scene",              # scene | stone | sand | night
    "color_mode": "light",         # light | dark | system
    "accent": "#c2451f",
    "font_pair": "mono",           # sans | serif | mono
    "layout_width": 1360,
    "radius": 0,
    "post_layout": "grid",         # grid | list
    "hero_style": "split",         # split | minimal | image
    "hero_show": True,
    "hero_eyebrow": "MZTLAB // SCENE",
    "hero_title": "光落下，\n场景生成。",
    "hero_subtitle": "影像，项目，文字。",
    "hero_image": "",
    "show_reading_time": True,
    "show_author": True,
    "show_views": True,

    # Home -------------------------------------------------------------------
    # Section titles live in the copy_* block below; the old home_*_title /
    # home_*_subtitle settings were removed with the Scene rebuild.
    "posts_per_page": 9,
    "gallery_columns": 3,
    "announcement": "",
    "comments_enabled": True,
    "comment_moderation": True,

    # Uploads ----------------------------------------------------------------
    # Maximum file size in MB and the enabled media formats. media.py enforces
    # these on every upload; the admin edits them in 设置 → 上传与媒体.
    "upload_max_mb": DEFAULT_UPLOAD_MAX_MB,
    "upload_image_formats": ",".join(UPLOAD_IMAGE_FORMATS),
    "upload_audio_formats": ",".join(UPLOAD_AUDIO_FORMATS),
    "upload_file_formats": DEFAULT_UPLOAD_FILE_FORMATS,

    # Theme copy -------------------------------------------------------------
    # Every visible line of the public theme is a setting. The admin edits
    # them in 外观 → 页面文案; pages fall back to these values when a key is
    # empty, so upgrading a theme never leaves a blank label. The theme is
    # called Scene (场景); "index" only survives in legacy key names.
    "copy_hero_primary_label": "浏览影像",
    "copy_hero_primary_url": "/photos",
    "copy_hero_secondary_label": "查看项目",
    "copy_hero_secondary_url": "/projects",
    "copy_index_title": "场景",
    "copy_index_lead": "三个入口：照片、项目与文字。各自独立，也彼此参照。",
    "copy_photos_title": "影像",
    "copy_photos_lead": "以相册整理光线、空间与痕迹。",
    "copy_photos_link": "全部影像",
    "copy_projects_title": "项目",
    "copy_projects_lead": "代码与设计，记录做法与结果。",
    "copy_projects_link": "全部项目",
    "copy_texts_title": "文字",
    "copy_texts_lead": "笔墨之痕，以篇章留存。",
    "copy_texts_link": "全部文字",
    "copy_stat_photos": "PHOTOS",
    "copy_stat_projects": "PROJECTS",
    "copy_stat_texts": "TEXTS",
    "copy_home_empty_title": "空场景",
    "copy_home_empty_text": "上传照片、建立相册，或写一篇文章。",
    "copy_home_empty_cta": "进入后台",
    "copy_cta_title": "保持联系。",
    "copy_cta_text": "订阅 RSS，或者先从场景里挑一个入口。",
    "copy_cta_rss": "RSS",
    "copy_cta_search": "搜索",
    "copy_photos_eyebrow": "// PHOTOS",
    "copy_photos_empty_title": "还没有相册",
    "copy_photos_empty_text": "新建相册，再从媒体库选照片。",
    "copy_photos_empty_cta": "管理相册",
    "copy_projects_eyebrow": "// PROJECTS",
    "copy_projects_empty_title": "还没有项目",
    "copy_projects_empty_text": "新建一个项目，记录它产生的过程。",
    "copy_projects_empty_cta": "管理项目",
    "copy_project_year": "年份",
    "copy_project_role": "角色",
    "copy_project_client": "上下文",
    "copy_project_kind": "类型",
    "copy_project_link": "访问项目",
    "copy_project_back": "返回项目",
    "copy_project_related": "其他项目",
    "copy_texts_eyebrow": "// TEXT_ARCHIVE",
    "copy_texts_empty_title": "还没有文章",
    "copy_texts_empty_text": "写下一篇文章，让时间有迹可循。",
    "copy_texts_empty_cta": "写文章",
    "copy_search_eyebrow": "// SEARCH",
    "copy_search_title": "搜索",
    "copy_search_lead": "寻找你需要的场景",
    "copy_search_placeholder": "输入关键词",
    "copy_search_empty": "没有找到匹配的内容。",
    "copy_search_projects": "项目",
    "copy_search_photos": "影像",
    "copy_search_photo_items": "照片",
    "copy_search_texts": "文字",
    "copy_search_suggestions": "试试标题、正文、地点、器材、年份或角色。",
    "copy_load_error_title": "内容服务离线",
    "copy_load_error_text": "启动 FastAPI 后端后刷新。",
    "copy_notfound_title": "场景不存在",
    "copy_notfound_text": "换一个地址，或者回到首页。",
    "copy_notfound_cta": "回到首页",
    "copy_footer_admin": "后台",
    "copy_skip_link": "跳到正文",
    "copy_back_to_top": "回到顶部",
    "copy_comments_title": "留言",
    "copy_comments_empty": "还没有留言。",
    "copy_comments_closed": "这篇文章的留言已关闭。",
    "copy_article_related": "继续阅读",
    "copy_article_all": "全部文章",
    "copy_article_share": "分享",
    "copy_article_filed": "归档于",

    # Team ---------------------------------------------------------------
    # Off by default: an editor only manages their own posts, galleries and
    # media. Admins can widen this from 设置 → 协作与权限.
    # Editors can see and manage every member's content by default. The owner
    # can narrow this back to own-only in 设置 → 协作与权限.
    "editor_manage_others": True,

    # Navigation / footer ----------------------------------------------------
    "nav": [
        {"label": "首页", "url": "/"},
        {"label": "影像", "url": "/photos"},
        {"label": "项目", "url": "/projects"},
        {"label": "文章", "url": "/archive"},
        {"label": "关于", "url": "/about"},
    ],
    "social": [
        {"label": "GitHub", "url": "https://github.com/"},
        {"label": "RSS", "url": "/rss.xml"},
    ],
    "footer_text": "影像、项目与文字。",
    "footer_note": "MZTLAB // ASTRO × FASTAPI",
    "icp": "",

    # SEO / advanced ---------------------------------------------------------
    "seo_description": "MZTLAB：影像、项目与文字。",
    "seo_keywords": "摄影, 影像, 相册, 项目, 代码, 文字, MZTLAB",
    "og_image": "",
    "custom_css": "",
    "head_html": "",
}

PUBLIC_SETTING_KEYS = set(DEFAULT_SETTINGS)

# Stored with the other settings but never exposed by /api/site or the export.
PRIVATE_SETTING_KEYS = {"editor_manage_others"}

THEMES = {"scene", "stone", "sand", "night"}
COLOR_MODES = {"light", "dark", "system"}
FONT_PAIRS = {"sans", "serif", "mono"}
POST_LAYOUTS = {"grid", "list"}
HERO_STYLES = {"split", "minimal", "image"}

# Values written by the previous "Ink Isle" theme. On upgrade we only rewrite a
# setting when the stored value still equals one of these, so hand-edited copy
# is never flattened back to a default.
LEGACY_DEFAULTS: dict[str, Any] = {
    "site_title": "墨屿",
    "site_subtitle": "INK ISLE",
    "tagline": "在喧嚣之外，留一座岛。",
    "description": "关于技术、设计与日常的个人札记。在快速的世界里，做一个耐心的观察者。",
    "theme": "paper",
    "accent": "#c2552f",
    "font_pair": "serif",
    "layout_width": 1180,
    "radius": 18,
    "post_layout": "grid",
    "hero_style": "editorial",
    "hero_eyebrow": "A PERSONAL JOURNAL",
    "hero_title": "写下来，\n让时间有迹可循。",
    "hero_subtitle": "关于技术、设计与日常的缓慢记录。\n在快速的世界里，做一个耐心的观察者。",
    "author_bio": "写代码，也写字。相信缓慢、具体和长期主义。",
    "nav": [
        {"label": "首页", "url": "/"},
        {"label": "文章", "url": "/archive"},
        {"label": "关于", "url": "/about"},
    ],
    "footer_text": "以文字对抗遗忘。",
    "footer_note": "Built with Astro × FastAPI",
    "seo_description": "一座关于技术、设计与生活的个人小岛。",
    "seo_keywords": "个人博客, 技术, 设计, 随笔",
}

LEGACY_PALETTES = {
    "paper": "scene",
    "graphite": "stone",
    "forest": "sand",
    "ocean": "stone",
    "editorial": "split",
}

# The first Scene release used these values. The Mono revision replaces them
# only when the owner has not typed over them, so hand-written copy survives.
SCENE_V1_COPY: dict[str, Any] = {
    "site_subtitle": "SCENE",
    "tagline": "影像、项目与书写。",
    "description": "MZTLAB 是一间以摄影、项目与文字为媒介的独立工作室档案。",
    "font_pair": "sans",
    "radius": 2,
    "hero_eyebrow": "VISUAL ARCHIVE · MZTLAB",
    "hero_title": "光落下的地方，\n就是场景。",
    "hero_subtitle": "摄影、项目与书写。\n把观察整理成可以停留的形状。",
    "footer_text": "影像是场景，文字是余温。",
    "footer_note": "MZTLAB · Built with Astro × FastAPI",
    "seo_description": "MZTLAB — 影像、项目与文字的场景档案。",
    "seo_keywords": "摄影, 影像, 作品集, 项目, MZTLAB",
}


# The 2.2 rebuild briefly shipped "Index" wording. It is now Scene (场景); this
# map rewrites only values that still equal one of those old defaults, so
# hand-edited copy always survives.
SCENE_INDEX_COPY: dict[str, Any] = {
    "site_subtitle": "INDEX",
    "hero_eyebrow": "MZTLAB // STUDIO_INDEX",
    "hero_title": "光落下。\n索引生成。",
    "hero_subtitle": "影像。项目。文字。\n三种工作，放进同一个索引。",
    "copy_index_title": "索引",
    "copy_home_empty_title": "空索引",
    "copy_cta_text": "订阅 RSS，或者先从索引里挑一个入口。",
    "copy_photos_eyebrow": "// PHOTO_INDEX",
    "copy_projects_eyebrow": "// PROJECT_INDEX",
    "copy_project_back": "返回项目索引",
    "copy_notfound_title": "页面不在索引里",
}

# Scene v2 defaults (before the 2.2 rebuild). The rebuild replaces them only
# when the stored value still equals one of these, so hand-written copy is
# never flattened back to a default.
SCENE_V2_COPY: dict[str, Any] = {
    "site_subtitle": "SCENE",
    "tagline": "影像与文字。",
    "description": "MZTLAB。影像与文字。",
    "author_bio": "以影像记录光，以文字整理观察。",
    "hero_eyebrow": "MZTLAB // VISUAL_ARCHIVE",
    "hero_title": "光落下。\n场景生成。",
    "hero_subtitle": "影像。文字。记录。",
    "footer_text": "影像与文字。",
    "seo_description": "MZTLAB：影像与文字。",
    "seo_keywords": "摄影, 影像, 相册, 文字, MZTLAB",
}

# The previous default nav (Scene v2, without Projects). The Scene rebuild adds
# the Projects entry back when the list has not been customised.
SCENE_V2_NAV: list[dict[str, str]] = [
    {"label": "首页", "url": "/"},
    {"label": "影像", "url": "/photos"},
    {"label": "文章", "url": "/archive"},
    {"label": "关于", "url": "/about"},
]


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)
