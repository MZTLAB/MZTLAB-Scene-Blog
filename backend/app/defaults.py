"""Defaults for the public site.

The out-of-the-box look is *Scene*: a quiet, monospaced canvas for photographs
and writing. Every value can be changed at runtime from 管理后台 → 外观 / 设置;
this file is the origin of those defaults and the allow-list of public setting
keys.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    # Identity ---------------------------------------------------------------
    "site_title": "MZTLAB",
    "site_subtitle": "SCENE",
    "tagline": "影像与文字。",
    "description": "MZTLAB。影像与文字。",
    "site_url": "http://127.0.0.1:4321",
    "logo": "",
    "favicon": "",
    "author_name": "MZTLAB",
    "author_bio": "以影像记录光，以文字整理观察。",
    "author_avatar": "",

    # Appearance -------------------------------------------------------------
    "theme": "scene",              # scene | stone | sand | night
    "color_mode": "light",         # light | dark | system
    "accent": "#e8481d",
    "font_pair": "mono",           # sans | serif | mono
    "layout_width": 1400,
    "radius": 0,
    "post_layout": "grid",         # grid | list
    "hero_style": "split",         # split | minimal | image
    "hero_show": True,
    "hero_eyebrow": "MZTLAB // VISUAL_ARCHIVE",
    "hero_title": "光落下。\n场景生成。",
    "hero_subtitle": "影像。文字。记录。",
    "hero_image": "",
    "show_reading_time": True,
    "show_author": True,
    "show_views": True,

    # Home -------------------------------------------------------------------
    "home_gallery_title": "影像相册",
    "home_gallery_subtitle": "",
    "home_section_title": "文字",
    "home_section_subtitle": "",
    "posts_per_page": 9,
    "gallery_columns": 3,
    "announcement": "",
    "comments_enabled": True,
    "comment_moderation": True,

    # Team ---------------------------------------------------------------
    # Off by default: an editor only manages their own posts, galleries and
    # media. Admins can widen this from 设置 → 协作与权限.
    "editor_manage_others": False,

    # Navigation / footer ----------------------------------------------------
    "nav": [
        {"label": "首页", "url": "/"},
        {"label": "影像", "url": "/photos"},
        {"label": "文章", "url": "/archive"},
        {"label": "关于", "url": "/about"},
    ],
    "social": [
        {"label": "GitHub", "url": "https://github.com/"},
        {"label": "RSS", "url": "/rss.xml"},
    ],
    "footer_text": "影像与文字。",
    "footer_note": "MZTLAB // ASTRO × FASTAPI",
    "icp": "",

    # SEO / advanced ---------------------------------------------------------
    "seo_description": "MZTLAB：影像与文字。",
    "seo_keywords": "摄影, 影像, 相册, 文字, MZTLAB",
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
    "home_section_title": "最近更新",
    "home_section_subtitle": "一些正在生长中的文字。",
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
    "home_gallery_title": "影像选辑",
    "home_gallery_subtitle": "从最近的拍摄里，挑出的几帧。",
    "home_section_title": "最近书写",
    "home_section_subtitle": "影像之外，文字是另一种取景。",
    "footer_text": "影像是场景，文字是余温。",
    "footer_note": "MZTLAB · Built with Astro × FastAPI",
    "seo_description": "MZTLAB — 影像、项目与文字的场景档案。",
    "seo_keywords": "摄影, 影像, 作品集, 项目, MZTLAB",
}


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)
