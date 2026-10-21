"""Request models.

Pydantic gives us helpful 422 errors without hand-writing validation. Content
requests are split per resource (posts / projects / pages) and every update
model is a true PATCH: only fields present in the request are written.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .avatars import AVATAR_ERROR, avatar_url_error
from .photo_exif import normalize_exif_fields
from .security import MIN_PASSWORD_LENGTH, password_policy_error

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SLUG_RE = re.compile(r"^[\w\u3400-\u9fff-]+$", re.UNICODE)
PROJECT_LINK_RE = re.compile(r"^(https?://|/)")


def _check_password(password: str, username: str | None = None) -> str:
    problem = password_policy_error(password, username)
    if problem:
        raise ValueError(problem)
    return password


class StrippedModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class PatchModel(StrippedModel):
    """Base for partial updates: omitted = keep, explicit null = clear."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)


class SetupIn(StrippedModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    display_name: str = Field(min_length=1, max_length=50)
    site_title: str = Field(default="MZTLAB", min_length=1, max_length=50)
    site_description: str = Field(default="", max_length=200)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        if not USERNAME_RE.match(value):
            raise ValueError("用户名只能包含字母、数字、点、下划线或短横线，长度 3-32")
        return value.lower()

    @model_validator(mode="after")
    def strong_password(self) -> SetupIn:
        _check_password(self.password, self.username)
        return self


class LoginIn(StrippedModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PreviewIn(StrippedModel):
    content_md: str = Field(default="", max_length=500_000)


def _clean_slug(value: str) -> str:
    if not value:
        return ""
    if not SLUG_RE.match(value):
        raise ValueError("别名只能包含文字、数字、下划线或短横线")
    return value.strip("-").lower().strip("-")


def _clean_terms(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value not in seen and len(value) <= 40:
            seen.append(value)
    return seen[:20]


class _ContentFields(StrippedModel):
    """Shared fields for the three content resources."""

    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(default="", max_length=100)
    excerpt: str = Field(default="", max_length=600)
    content_md: str = Field(default="", max_length=500_000)
    cover_image: str = Field(default="", max_length=500)
    status: Literal["draft", "published", "scheduled"] = "draft"
    featured: bool = False
    published_at: str | None = None
    # Ownership transfer; only callers with `content.others` may change it.
    owner_id: int | None = Field(default=None, ge=1)
    seo_title: str = Field(default="", max_length=200)
    seo_description: str = Field(default="", max_length=400)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        return _clean_slug(value)

    @model_validator(mode="after")
    def check_schedule(self) -> _ContentFields:
        if self.status == "scheduled" and not self.published_at:
            raise ValueError("定时文章需要发布时间")
        return self


class PostIn(_ContentFields):
    tags: list[str] = Field(default_factory=list, max_length=20)
    categories: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("tags", "categories")
    @classmethod
    def clean_terms(cls, values: list[str]) -> list[str]:
        return _clean_terms(values)


class ProjectIn(_ContentFields):
    project_year: str = Field(default="", max_length=20)
    project_role: str = Field(default="", max_length=100)
    project_client: str = Field(default="", max_length=100)
    # A free-form label (代码 / 影像 / 设计 …); no enum to maintain.
    project_kind: str = Field(default="", max_length=40)
    project_url: str = Field(default="", max_length=300)

    @field_validator("project_kind")
    @classmethod
    def clean_project_kind(cls, value: str) -> str:
        value = "".join(character for character in value if character.isprintable())
        return re.sub(r"\s+", " ", value).strip()[:40]

    @field_validator("project_url")
    @classmethod
    def project_link(cls, value: str) -> str:
        if value and not PROJECT_LINK_RE.match(value):
            raise ValueError("项目链接需要以 http://、https:// 或 / 开头")
        return value


class PageIn(_ContentFields):
    pass


class PostPatch(PatchModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    excerpt: str | None = Field(default=None, max_length=600)
    content_md: str | None = Field(default=None, max_length=500_000)
    cover_image: str | None = Field(default=None, max_length=500)
    status: Literal["draft", "published", "scheduled"] | None = None
    featured: bool | None = None
    published_at: str | None = None
    owner_id: int | None = Field(default=None, ge=1)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=400)
    tags: list[str] | None = Field(default=None, max_length=20)
    categories: list[str] | None = Field(default=None, max_length=6)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_slug(value)

    @field_validator("tags", "categories")
    @classmethod
    def clean_terms(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _clean_terms(values)


class ProjectPatch(PatchModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    excerpt: str | None = Field(default=None, max_length=600)
    content_md: str | None = Field(default=None, max_length=500_000)
    cover_image: str | None = Field(default=None, max_length=500)
    status: Literal["draft", "published", "scheduled"] | None = None
    featured: bool | None = None
    published_at: str | None = None
    owner_id: int | None = Field(default=None, ge=1)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=400)
    project_year: str | None = Field(default=None, max_length=20)
    project_role: str | None = Field(default=None, max_length=100)
    project_client: str | None = Field(default=None, max_length=100)
    project_kind: str | None = Field(default=None, max_length=40)
    project_url: str | None = Field(default=None, max_length=300)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_slug(value)

    @field_validator("project_kind")
    @classmethod
    def clean_project_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = "".join(character for character in value if character.isprintable())
        return re.sub(r"\s+", " ", value).strip()[:40]

    @field_validator("project_url")
    @classmethod
    def project_link(cls, value: str | None) -> str | None:
        if value and not PROJECT_LINK_RE.match(value):
            raise ValueError("项目链接需要以 http://、https:// 或 / 开头")
        return value


class PagePatch(PatchModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    excerpt: str | None = Field(default=None, max_length=600)
    content_md: str | None = Field(default=None, max_length=500_000)
    cover_image: str | None = Field(default=None, max_length=500)
    status: Literal["draft", "published", "scheduled"] | None = None
    featured: bool | None = None
    published_at: str | None = None
    owner_id: int | None = Field(default=None, ge=1)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=400)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_slug(value)


class TaxonomyIn(StrippedModel):
    name: str = Field(min_length=1, max_length=40)
    slug: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=300)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        if value and not SLUG_RE.match(value):
            raise ValueError("别名只能包含文字、数字、下划线或短横线")
        return value.strip("-").lower()


class MediaAltIn(PatchModel):
    """PATCH /api/admin/media/{id}: omitted fields keep their value.

    Per-image AVIF quality was removed with ADR-10: quality is an immutable
    pipeline constant, so the only editable media field is the alt text.
    """

    alt: str | None = Field(default=None, max_length=200)


class StorageSyncIn(StrippedModel):
    """Upload local originals / generated derivatives to the configured bucket."""

    force: bool = False
    scope: Literal["all", "originals", "derivatives"] = "all"


class MediaExifIn(StrippedModel):
    camera: str = Field(default="", max_length=120)
    lens: str = Field(default="", max_length=120)
    taken_at: str = Field(default="", max_length=10)
    aperture: str = Field(default="", max_length=40)
    exposure: str = Field(default="", max_length=40)
    iso: int | None = Field(default=None, ge=0, le=409_600)
    focal_length: str = Field(default="", max_length=40)
    focal_length_35mm: int | None = Field(default=None, ge=0, le=2000)

    @field_validator("taken_at")
    @classmethod
    def valid_taken_at(cls, value: str) -> str:
        if value and not re.match(r"^\d{4}-\d{2}(-\d{2})?$", value):
            raise ValueError("拍摄日期格式为 YYYY-MM 或 YYYY-MM-DD")
        return value


class ProfileIn(StrippedModel):
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=120)
    bio: str = Field(default="", max_length=500)
    avatar: str = Field(default="", max_length=500)
    current_password: str = Field(default="", max_length=128)
    new_password: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if value and not EMAIL_RE.match(value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("avatar")
    @classmethod
    def valid_avatar(cls, value: str) -> str:
        # Avatars end up in <img src> on public pages; only raster image links
        # are allowed so an SVG/HTML/data: URL can never be stored there.
        if avatar_url_error(value):
            raise ValueError(AVATAR_ERROR)
        return value

    @model_validator(mode="after")
    def password_pair(self) -> ProfileIn:
        if self.new_password:
            _check_password(self.new_password)
        if self.new_password and not self.current_password:
            raise ValueError("修改密码需要提供当前密码")
        return self


class UserCreateIn(StrippedModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=120)
    bio: str = Field(default="", max_length=500)
    role: Literal["admin", "editor", "author"] = "author"

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        if not USERNAME_RE.match(value):
            raise ValueError("用户名只能包含字母、数字、点、下划线或短横线，长度 3-32")
        return value.lower()

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if value and not EMAIL_RE.match(value):
            raise ValueError("邮箱格式不正确")
        return value

    @model_validator(mode="after")
    def strong_password(self) -> UserCreateIn:
        _check_password(self.password, self.username)
        return self


class UserUpdateIn(StrippedModel):
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=120)
    bio: str = Field(default="", max_length=500)
    role: Literal["admin", "editor", "author"]
    is_active: bool = True
    password: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if value and not EMAIL_RE.match(value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if value:
            _check_password(value)
        return value


class GalleryIn(StrippedModel):
    title: str = Field(min_length=1, max_length=120)
    slug: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    status: Literal["draft", "published"] = "draft"
    featured: bool = False
    cover_photo_id: int | None = None

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        if value and not SLUG_RE.match(value):
            raise ValueError("别名只能包含文字、数字、下划线或短横线")
        return value.strip("-").lower()


class GalleryPatch(PatchModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["draft", "published"] | None = None
    featured: bool | None = None
    cover_photo_id: int | None = None

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value and not SLUG_RE.match(value):
            raise ValueError("别名只能包含文字、数字、下划线或短横线")
        return value.strip("-").lower()


class PhotoIn(StrippedModel):
    media_id: int = Field(ge=1)
    gallery_id: int | None = None
    title: str = Field(default="", max_length=140)
    caption: str = Field(default="", max_length=600)
    location: str = Field(default="", max_length=120)
    camera: str = Field(default="", max_length=120)
    lens: str = Field(default="", max_length=120)
    taken_at: str = Field(default="", max_length=10)
    exif_fields: list[str] | None = Field(default=None, max_length=8)
    featured: bool = False
    status: Literal["draft", "published"] = "published"
    hide_download_link: bool = False

    @field_validator("exif_fields")
    @classmethod
    def valid_exif_fields(cls, value: list[str] | None) -> list[str] | None:
        return normalize_exif_fields(value)

    @field_validator("taken_at")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if value and not re.match(r"^\d{4}-\d{2}(-\d{2})?$", value):
            raise ValueError("拍摄日期格式为 YYYY-MM 或 YYYY-MM-DD")
        return value


class PhotoUpdateIn(PatchModel):
    """PATCH: omitted fields keep their value; explicit null clears."""

    gallery_id: int | None = None
    title: str | None = Field(default=None, max_length=140)
    caption: str | None = Field(default=None, max_length=600)
    location: str | None = Field(default=None, max_length=120)
    camera: str | None = Field(default=None, max_length=120)
    lens: str | None = Field(default=None, max_length=120)
    taken_at: str | None = Field(default=None, max_length=10)
    exif_fields: list[str] | None = Field(default=None, max_length=8)
    featured: bool | None = None
    status: Literal["draft", "published"] | None = None
    sort_order: int | None = None
    hide_download_link: bool | None = None

    @field_validator("exif_fields")
    @classmethod
    def valid_exif_fields(cls, value: list[str] | None) -> list[str] | None:
        return normalize_exif_fields(value)

    @field_validator("taken_at")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value and not re.match(r"^\d{4}-\d{2}(-\d{2})?$", value):
            raise ValueError("拍摄日期格式为 YYYY-MM 或 YYYY-MM-DD")
        return value


class PhotoBatchIn(StrippedModel):
    media_ids: list[int] = Field(min_length=1, max_length=60)
    gallery_id: int | None = None
    status: Literal["draft", "published"] = "published"


class ReorderIn(StrippedModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class JobCreateIn(StrippedModel):
    """Placeholder job requests whose executor arrives in later phases."""

    media_id: int | None = Field(default=None, ge=1)
    gallery_id: int | None = Field(default=None, ge=1)
    force: bool = False
