"""Grouped settings models.

Settings are five JSON documents (`site`, `appearance`, `copy`, `upload`,
`advanced`), each validated by a Pydantic model. This file is the single source
of truth for field names, defaults and validation: adding a setting means
editing one model, and the frontend type is generated from the OpenAPI schema.

Secrets are not part of the models. Object-storage credentials come from the
environment (`BLOG_S3_ACCESS_KEY` / `BLOG_S3_SECRET_KEY`) and never touch the
database.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import MAX_UPLOAD_BYTES

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Upload catalogue. These are the only formats the admin may enable; the
# allowed tokens are validated here instead of being re-parsed by each route.
UPLOAD_IMAGE_FORMATS: tuple[str, ...] = ("jpg", "png", "webp", "gif")
UPLOAD_AUDIO_FORMATS: tuple[str, ...] = ("mp3", "m4a", "ogg", "oga", "wav", "flac")
UPLOAD_FILE_FORMATS: tuple[str, ...] = (
    "pdf", "zip", "txt", "md", "csv", "json", "docx", "xlsx", "pptx",
)
UPLOAD_FORMAT_ALIASES = {"jpeg": "jpg", "tif": "jpg", "tiff": "jpg"}
DEFAULT_UPLOAD_MAX_MB = max(1, MAX_UPLOAD_BYTES // (1024 * 1024))

IMAGE_SCENES = ("thumb", "tile", "card", "hero", "viewer", "prose", "full")
THEMES = ("scene", "stone", "sand", "night")
COLOR_MODES = ("light", "dark", "system")
FONT_PAIRS = ("sans", "serif", "mono")
POST_LAYOUTS = ("grid", "list")
HERO_STYLES = ("split", "minimal", "image")
STORAGE_BACKENDS = ("local", "s3")
STORAGE_SERVE_MODES = ("auto", "proxy", "direct")

DEFAULT_ACCENT = "#c2451f"


def _clean_link(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("/", "#")) or re.match(r"^(https?://|mailto:)", value):
        return value
    raise ValueError("链接需要以 /、#、http://、https:// 或 mailto: 开头")


class StripModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class NavLink(StripModel):
    label: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=300)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return _clean_link(value)


def _clean_links(links: list[NavLink], limit: int = 12) -> list[NavLink]:
    result: list[NavLink] = []
    for link in links[:limit]:
        if link.label and link.url:
            result.append(link)
    return result


class SiteSettings(StripModel):
    # Identity
    site_title: str = Field(default="MZTLAB", max_length=60)
    site_subtitle: str = Field(default="Scene", max_length=60)
    tagline: str = Field(default="影像、项目与文字。", max_length=160)
    description: str = Field(
        default="MZTLAB 是一间以影像、项目与文字为媒介的独立工作室档案。",
        max_length=300,
    )
    site_url: str = Field(default="http://127.0.0.1:4321", max_length=200)
    logo: str = Field(default="", max_length=500)
    favicon: str = Field(default="", max_length=500)

    # Navigation / footer / social
    nav: list[NavLink] = Field(
        default_factory=lambda: [
            NavLink(label="首页", url="/"),
            NavLink(label="影像", url="/photos"),
            NavLink(label="项目", url="/projects"),
            NavLink(label="文章", url="/archive"),
            NavLink(label="关于", url="/about"),
        ]
    )
    social: list[NavLink] = Field(
        default_factory=lambda: [
            NavLink(label="GitHub", url="https://github.com/"),
            NavLink(label="RSS", url="/rss.xml"),
        ]
    )
    footer_links: list[NavLink] = Field(
        default_factory=lambda: [
            NavLink(label="影像", url="/photos"),
            NavLink(label="项目", url="/projects"),
            NavLink(label="文字", url="/archive"),
            NavLink(label="搜索", url="/search"),
            NavLink(label="后台", url="/admin"),
        ]
    )
    footer_text: str = Field(default="影像、项目与文字。", max_length=200)
    footer_note: str = Field(default="MZTLAB // ASTRO × FASTAPI", max_length=200)
    icp: str = Field(default="", max_length=80)

    # SEO / feed
    seo_description: str = Field(default="MZTLAB：影像、项目与文字。", max_length=300)
    seo_keywords: str = Field(
        default="摄影, 影像, 相册, 项目, 代码, 文字, MZTLAB", max_length=200
    )
    og_image: str = Field(default="", max_length=500)

    # Listing / home
    posts_per_page: int = Field(default=9, ge=1, le=30)
    gallery_columns: int = Field(default=3, ge=2, le=4)
    announcement: str = Field(default="", max_length=300)

    # Collaboration policy (never exposed by the public projection)
    editor_manage_others: bool = True

    @field_validator("site_url")
    @classmethod
    def valid_site_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if value and not re.match(r"^https?://", value):
            raise ValueError("站点地址需要以 http:// 或 https:// 开头")
        return value

    @field_validator("logo", "favicon", "og_image")
    @classmethod
    def safe_asset_url(cls, value: str) -> str:
        if value and not (
            value.startswith("/") or re.match(r"^https?://", value)
        ):
            raise ValueError("图片地址需要以 / 或 http(s):// 开头")
        return value

    @field_validator("nav", "social", "footer_links")
    @classmethod
    def clean_links(cls, value: list[NavLink]) -> list[NavLink]:
        return _clean_links(value)

    def public(self) -> dict[str, object]:
        """Render-only projection; internal policy flags never leave the server."""
        data = self.model_dump()
        data.pop("editor_manage_others", None)
        return data


class AppearanceSettings(StripModel):
    theme: Literal["scene", "stone", "sand", "night"] = "scene"
    color_mode: Literal["light", "dark", "system"] = "light"
    accent: str = DEFAULT_ACCENT
    font_pair: Literal["sans", "serif", "mono"] = "mono"
    layout_width: int = Field(default=1360, ge=720, le=1600)
    radius: int = Field(default=0, ge=0, le=40)
    post_layout: Literal["grid", "list"] = "grid"
    hero_style: Literal["split", "minimal", "image"] = "split"
    hero_show: bool = True
    hero_eyebrow: str = Field(default="MZTLAB // SCENE", max_length=100)
    hero_title: str = Field(default="光落下，\n场景生成。", max_length=160)
    hero_subtitle: str = Field(default="影像，项目，文字。", max_length=500)
    hero_image: str = Field(default="", max_length=500)
    show_reading_time: bool = True
    show_author: bool = True
    custom_css: str = Field(default="", max_length=60_000)
    head_html: str = Field(default="", max_length=30_000)

    @field_validator("accent")
    @classmethod
    def valid_accent(cls, value: str) -> str:
        value = value.strip().lower()
        if not HEX_COLOR_RE.match(value):
            raise ValueError("强调色需要使用 #RRGGBB 格式")
        return value

    @field_validator("hero_image")
    @classmethod
    def safe_hero_image(cls, value: str) -> str:
        if value and not (value.startswith("/") or re.match(r"^https?://", value)):
            raise ValueError("图片地址需要以 / 或 http(s):// 开头")
        return value


# Theme copy. `copy_*` prefixes are gone: the JSON path is `copy.photos_title`.
# Comment-related copy keys were removed with the comment feature.
class CopySettings(StripModel):
    hero_primary_label: str = Field(default="浏览影像", max_length=500)
    hero_primary_url: str = Field(default="/photos", max_length=500)
    hero_secondary_label: str = Field(default="查看项目", max_length=500)
    hero_secondary_url: str = Field(default="/projects", max_length=500)
    index_title: str = Field(default="场景", max_length=500)
    index_lead: str = Field(
        default="三个入口：照片、项目与文字。各自独立，也彼此参照。", max_length=500
    )
    photos_title: str = Field(default="影像", max_length=500)
    photos_lead: str = Field(default="以相册整理光线、空间与痕迹。", max_length=500)
    photos_link: str = Field(default="全部影像", max_length=500)
    projects_title: str = Field(default="项目", max_length=500)
    projects_lead: str = Field(default="代码与设计，记录做法与结果。", max_length=500)
    projects_link: str = Field(default="全部项目", max_length=500)
    texts_title: str = Field(default="文字", max_length=500)
    texts_lead: str = Field(default="笔墨之痕，以篇章留存。", max_length=500)
    texts_link: str = Field(default="全部文字", max_length=500)
    stat_photos: str = Field(default="PHOTOS", max_length=500)
    stat_projects: str = Field(default="PROJECTS", max_length=500)
    stat_texts: str = Field(default="TEXTS", max_length=500)
    home_empty_title: str = Field(default="空场景", max_length=500)
    home_empty_text: str = Field(
        default="上传照片、建立相册，或写一篇文章。", max_length=500
    )
    home_empty_cta: str = Field(default="进入后台", max_length=500)
    cta_title: str = Field(default="保持联系。", max_length=500)
    cta_text: str = Field(
        default="订阅 RSS，或者先从场景里挑一个入口。", max_length=500
    )
    cta_rss: str = Field(default="RSS", max_length=500)
    cta_search: str = Field(default="搜索", max_length=500)
    photos_eyebrow: str = Field(default="// PHOTOS", max_length=500)
    photos_empty_title: str = Field(default="还没有相册", max_length=500)
    photos_empty_text: str = Field(
        default="新建相册，再从媒体库选照片。", max_length=500
    )
    photos_empty_cta: str = Field(default="管理相册", max_length=500)
    projects_eyebrow: str = Field(default="// PROJECTS", max_length=500)
    projects_empty_title: str = Field(default="还没有项目", max_length=500)
    projects_empty_text: str = Field(
        default="新建一个项目，记录它产生的过程。", max_length=500
    )
    projects_empty_cta: str = Field(default="管理项目", max_length=500)
    project_year: str = Field(default="年份", max_length=500)
    project_role: str = Field(default="角色", max_length=500)
    project_client: str = Field(default="上下文", max_length=500)
    project_kind: str = Field(default="类型", max_length=500)
    author: str = Field(default="作者", max_length=500)
    project_link: str = Field(default="访问项目", max_length=500)
    project_back: str = Field(default="返回项目", max_length=500)
    project_related: str = Field(default="其他项目", max_length=500)
    texts_eyebrow: str = Field(default="// TEXT_ARCHIVE", max_length=500)
    texts_empty_title: str = Field(default="还没有文章", max_length=500)
    texts_empty_text: str = Field(
        default="写下一篇文章，让时间有迹可循。", max_length=500
    )
    texts_empty_cta: str = Field(default="写文章", max_length=500)
    search_eyebrow: str = Field(default="// SEARCH", max_length=500)
    search_title: str = Field(default="搜索", max_length=500)
    search_lead: str = Field(default="寻找你需要的场景", max_length=500)
    search_placeholder: str = Field(default="输入关键词", max_length=500)
    search_empty: str = Field(default="没有找到匹配的内容。", max_length=500)
    search_projects: str = Field(default="项目", max_length=500)
    search_photos: str = Field(default="影像", max_length=500)
    search_photo_items: str = Field(default="照片", max_length=500)
    search_texts: str = Field(default="文字", max_length=500)
    search_suggestions: str = Field(
        default="试试标题、正文、地点、器材、年份或角色。", max_length=500
    )
    notfound_title: str = Field(default="场景不存在", max_length=500)
    notfound_text: str = Field(default="换一个地址，或者回到首页。", max_length=500)
    notfound_cta: str = Field(default="回到首页", max_length=500)
    footer_admin: str = Field(default="后台", max_length=500)
    skip_link: str = Field(default="跳到正文", max_length=500)
    back_to_top: str = Field(default="回到顶部", max_length=500)
    article_related: str = Field(default="继续阅读", max_length=500)
    article_all: str = Field(default="全部文章", max_length=500)
    article_share: str = Field(default="分享", max_length=500)
    article_filed: str = Field(default="归档于", max_length=500)


def _format_list(allowed: tuple[str, ...], aliases: dict[str, str]):
    allowed_set = set(allowed)

    def validate(value: list[str]) -> list[str]:
        tokens: set[str] = set()
        for token in value:
            token = aliases.get(str(token).strip().lower().lstrip("."),
                                str(token).strip().lower().lstrip("."))
            if token in allowed_set:
                tokens.add(token)
        return [fmt for fmt in allowed if fmt in tokens]

    return validate


class UploadSettings(StripModel):
    max_mb: int = Field(default=DEFAULT_UPLOAD_MAX_MB, ge=1, le=200)
    image_formats: list[str] = Field(default_factory=lambda: list(UPLOAD_IMAGE_FORMATS))
    audio_formats: list[str] = Field(default_factory=lambda: list(UPLOAD_AUDIO_FORMATS))
    file_formats: list[str] = Field(
        default_factory=lambda: ["pdf", "zip", "txt", "md", "csv"]
    )

    @field_validator("image_formats")
    @classmethod
    def valid_image_formats(cls, value: list[str]) -> list[str]:
        return _format_list(UPLOAD_IMAGE_FORMATS, UPLOAD_FORMAT_ALIASES)(value)

    @field_validator("audio_formats")
    @classmethod
    def valid_audio_formats(cls, value: list[str]) -> list[str]:
        return _format_list(UPLOAD_AUDIO_FORMATS, {})(value)

    @field_validator("file_formats")
    @classmethod
    def valid_file_formats(cls, value: list[str]) -> list[str]:
        return _format_list(UPLOAD_FILE_FORMATS, {})(value)


class ImagePipelineSettings(StripModel):
    """Image pipeline knobs.

    Width ladder and format switches are runtime settings; encoding quality is
    an intentional code constant (`PIPELINE_DEFAULTS`, Phase 3) because changing
    it used to invalidate every derivative URL.
    """

    widths: list[int] = Field(default_factory=lambda: [720, 2560])
    max_width: int = Field(default=0, ge=0, le=8192)
    cache_days: int = Field(default=365, ge=1, le=3650)
    prewarm: bool = True
    lazy: bool = True
    avif_enabled: bool = True
    avif_speed: int = Field(default=6, ge=0, le=10)
    webp_enabled: bool = True
    webp_quality: int = Field(default=80, ge=1, le=100)
    jpeg_quality: int = Field(default=82, ge=1, le=100)
    quality_thumb: int = Field(default=45, ge=1, le=100)
    quality_tile: int = Field(default=50, ge=1, le=100)
    quality_card: int = Field(default=55, ge=1, le=100)
    quality_hero: int = Field(default=67, ge=1, le=100)
    quality_viewer: int = Field(default=65, ge=1, le=100)
    quality_prose: int = Field(default=60, ge=1, le=100)
    quality_full: int = Field(default=70, ge=1, le=100)

    @field_validator("widths")
    @classmethod
    def clean_widths(cls, value: list[int]) -> list[int]:
        widths = sorted({int(width) for width in value if 64 <= int(width) <= 8192})
        return widths[:10] or [720, 2560]


class StorageSettings(StripModel):
    """Object storage coordinates. Credentials are environment-only."""

    backend: Literal["local", "s3"] = "local"
    serve_mode: Literal["auto", "proxy", "direct"] = "auto"
    public_base_url: str = Field(default="", max_length=500)
    s3_endpoint: str = Field(default="", max_length=500)
    s3_bucket: str = Field(default="", max_length=200)
    s3_region: str = Field(default="auto", max_length=200)
    s3_prefix: str = Field(default="mztlab", max_length=200)
    s3_path_style: bool = False
    backup_local: bool = False

    @field_validator("public_base_url", "s3_endpoint")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if value and not re.match(r"^https?://", value):
            raise ValueError("地址需要以 http:// 或 https:// 开头")
        return value


class AdvancedSettings(StripModel):
    image: ImagePipelineSettings = Field(default_factory=ImagePipelineSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)


class Settings(BaseModel):
    """The complete, validated settings document."""

    model_config = ConfigDict(extra="forbid")

    site: SiteSettings = Field(default_factory=SiteSettings)
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
    copy: CopySettings = Field(default_factory=CopySettings)
    upload: UploadSettings = Field(default_factory=UploadSettings)
    advanced: AdvancedSettings = Field(default_factory=AdvancedSettings)

    def public_dump(self) -> dict[str, object]:
        """Only what a public page needs; internal policy stays server-side."""
        return {
            "site": self.site.public(),
            "appearance": self.appearance.model_dump(),
            "copy": self.copy.model_dump(),
        }


# ---------------------------------------------------------------------------
# Patch models: every field optional, "not provided" means "keep the value".
# An explicitly provided `None` is rejected for non-nullable fields by the
# full-model validation after merging.
# ---------------------------------------------------------------------------


class SiteSettingsPatch(StripModel):
    site_title: str | None = Field(default=None, max_length=60)
    site_subtitle: str | None = Field(default=None, max_length=60)
    tagline: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=300)
    site_url: str | None = Field(default=None, max_length=200)
    logo: str | None = Field(default=None, max_length=500)
    favicon: str | None = Field(default=None, max_length=500)
    nav: list[NavLink] | None = None
    social: list[NavLink] | None = None
    footer_links: list[NavLink] | None = None
    footer_text: str | None = Field(default=None, max_length=200)
    footer_note: str | None = Field(default=None, max_length=200)
    icp: str | None = Field(default=None, max_length=80)
    seo_description: str | None = Field(default=None, max_length=300)
    seo_keywords: str | None = Field(default=None, max_length=200)
    og_image: str | None = Field(default=None, max_length=500)
    posts_per_page: int | None = Field(default=None, ge=1, le=30)
    gallery_columns: int | None = Field(default=None, ge=2, le=4)
    announcement: str | None = Field(default=None, max_length=300)
    editor_manage_others: bool | None = None

    @field_validator("site_url")
    @classmethod
    def valid_site_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.rstrip("/")
        if value and not re.match(r"^https?://", value):
            raise ValueError("站点地址需要以 http:// 或 https:// 开头")
        return value


class AppearanceSettingsPatch(StripModel):
    theme: Literal["scene", "stone", "sand", "night"] | None = None
    color_mode: Literal["light", "dark", "system"] | None = None
    accent: str | None = None
    font_pair: Literal["sans", "serif", "mono"] | None = None
    layout_width: int | None = Field(default=None, ge=720, le=1600)
    radius: int | None = Field(default=None, ge=0, le=40)
    post_layout: Literal["grid", "list"] | None = None
    hero_style: Literal["split", "minimal", "image"] | None = None
    hero_show: bool | None = None
    hero_eyebrow: str | None = Field(default=None, max_length=100)
    hero_title: str | None = Field(default=None, max_length=160)
    hero_subtitle: str | None = Field(default=None, max_length=500)
    hero_image: str | None = Field(default=None, max_length=500)
    show_reading_time: bool | None = None
    show_author: bool | None = None
    custom_css: str | None = Field(default=None, max_length=60_000)
    head_html: str | None = Field(default=None, max_length=30_000)

    @field_validator("accent")
    @classmethod
    def valid_accent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not HEX_COLOR_RE.match(value):
            raise ValueError("强调色需要使用 #RRGGBB 格式")
        return value


class CopySettingsPatch(StripModel):
    hero_primary_label: str | None = Field(default=None, max_length=500)
    hero_primary_url: str | None = Field(default=None, max_length=500)
    hero_secondary_label: str | None = Field(default=None, max_length=500)
    hero_secondary_url: str | None = Field(default=None, max_length=500)
    index_title: str | None = Field(default=None, max_length=500)
    index_lead: str | None = Field(default=None, max_length=500)
    photos_title: str | None = Field(default=None, max_length=500)
    photos_lead: str | None = Field(default=None, max_length=500)
    photos_link: str | None = Field(default=None, max_length=500)
    projects_title: str | None = Field(default=None, max_length=500)
    projects_lead: str | None = Field(default=None, max_length=500)
    projects_link: str | None = Field(default=None, max_length=500)
    texts_title: str | None = Field(default=None, max_length=500)
    texts_lead: str | None = Field(default=None, max_length=500)
    texts_link: str | None = Field(default=None, max_length=500)
    stat_photos: str | None = Field(default=None, max_length=500)
    stat_projects: str | None = Field(default=None, max_length=500)
    stat_texts: str | None = Field(default=None, max_length=500)
    home_empty_title: str | None = Field(default=None, max_length=500)
    home_empty_text: str | None = Field(default=None, max_length=500)
    home_empty_cta: str | None = Field(default=None, max_length=500)
    cta_title: str | None = Field(default=None, max_length=500)
    cta_text: str | None = Field(default=None, max_length=500)
    cta_rss: str | None = Field(default=None, max_length=500)
    cta_search: str | None = Field(default=None, max_length=500)
    photos_eyebrow: str | None = Field(default=None, max_length=500)
    photos_empty_title: str | None = Field(default=None, max_length=500)
    photos_empty_text: str | None = Field(default=None, max_length=500)
    photos_empty_cta: str | None = Field(default=None, max_length=500)
    projects_eyebrow: str | None = Field(default=None, max_length=500)
    projects_empty_title: str | None = Field(default=None, max_length=500)
    projects_empty_text: str | None = Field(default=None, max_length=500)
    projects_empty_cta: str | None = Field(default=None, max_length=500)
    project_year: str | None = Field(default=None, max_length=500)
    project_role: str | None = Field(default=None, max_length=500)
    project_client: str | None = Field(default=None, max_length=500)
    project_kind: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    project_link: str | None = Field(default=None, max_length=500)
    project_back: str | None = Field(default=None, max_length=500)
    project_related: str | None = Field(default=None, max_length=500)
    texts_eyebrow: str | None = Field(default=None, max_length=500)
    texts_empty_title: str | None = Field(default=None, max_length=500)
    texts_empty_text: str | None = Field(default=None, max_length=500)
    texts_empty_cta: str | None = Field(default=None, max_length=500)
    search_eyebrow: str | None = Field(default=None, max_length=500)
    search_title: str | None = Field(default=None, max_length=500)
    search_lead: str | None = Field(default=None, max_length=500)
    search_placeholder: str | None = Field(default=None, max_length=500)
    search_empty: str | None = Field(default=None, max_length=500)
    search_projects: str | None = Field(default=None, max_length=500)
    search_photos: str | None = Field(default=None, max_length=500)
    search_photo_items: str | None = Field(default=None, max_length=500)
    search_texts: str | None = Field(default=None, max_length=500)
    search_suggestions: str | None = Field(default=None, max_length=500)
    notfound_title: str | None = Field(default=None, max_length=500)
    notfound_text: str | None = Field(default=None, max_length=500)
    notfound_cta: str | None = Field(default=None, max_length=500)
    footer_admin: str | None = Field(default=None, max_length=500)
    skip_link: str | None = Field(default=None, max_length=500)
    back_to_top: str | None = Field(default=None, max_length=500)
    article_related: str | None = Field(default=None, max_length=500)
    article_all: str | None = Field(default=None, max_length=500)
    article_share: str | None = Field(default=None, max_length=500)
    article_filed: str | None = Field(default=None, max_length=500)


class UploadSettingsPatch(StripModel):
    max_mb: int | None = Field(default=None, ge=1, le=200)
    image_formats: list[str] | None = None
    audio_formats: list[str] | None = None
    file_formats: list[str] | None = None


class ImagePipelineSettingsPatch(StripModel):
    widths: list[int] | None = None
    max_width: int | None = Field(default=None, ge=0, le=8192)
    cache_days: int | None = Field(default=None, ge=1, le=3650)
    prewarm: bool | None = None
    lazy: bool | None = None
    avif_enabled: bool | None = None
    avif_speed: int | None = Field(default=None, ge=0, le=10)
    webp_enabled: bool | None = None
    webp_quality: int | None = Field(default=None, ge=1, le=100)
    jpeg_quality: int | None = Field(default=None, ge=1, le=100)
    quality_thumb: int | None = Field(default=None, ge=1, le=100)
    quality_tile: int | None = Field(default=None, ge=1, le=100)
    quality_card: int | None = Field(default=None, ge=1, le=100)
    quality_hero: int | None = Field(default=None, ge=1, le=100)
    quality_viewer: int | None = Field(default=None, ge=1, le=100)
    quality_prose: int | None = Field(default=None, ge=1, le=100)
    quality_full: int | None = Field(default=None, ge=1, le=100)


class StorageSettingsPatch(StripModel):
    backend: Literal["local", "s3"] | None = None
    serve_mode: Literal["auto", "proxy", "direct"] | None = None
    public_base_url: str | None = Field(default=None, max_length=500)
    s3_endpoint: str | None = Field(default=None, max_length=500)
    s3_bucket: str | None = Field(default=None, max_length=200)
    s3_region: str | None = Field(default=None, max_length=200)
    s3_prefix: str | None = Field(default=None, max_length=200)
    s3_path_style: bool | None = None
    backup_local: bool | None = None


class AdvancedSettingsPatch(StripModel):
    image: ImagePipelineSettingsPatch | None = None
    storage: StorageSettingsPatch | None = None


class SettingsPatch(BaseModel):
    """Partial settings update: provide any subset of groups/fields."""

    model_config = ConfigDict(extra="forbid")

    site: SiteSettingsPatch | None = None
    appearance: AppearanceSettingsPatch | None = None
    copy: CopySettingsPatch | None = None
    upload: UploadSettingsPatch | None = None
    advanced: AdvancedSettingsPatch | None = None

    def provided(self) -> dict[str, dict[str, object]]:
        """Only groups/fields the client actually sent (PATCH semantics)."""
        result: dict[str, dict[str, object]] = {}
        for group in ("site", "appearance", "copy", "upload", "advanced"):
            patch = getattr(self, group)
            if patch is None:
                continue
            fields = patch.model_dump(exclude_unset=True)
            result[group] = {key: value for key, value in fields.items() if value is not None}
        return result
