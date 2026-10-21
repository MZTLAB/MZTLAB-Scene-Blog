"""Response DTOs (OpenAPI contract).

Every public route declares a `response_model` from this module, so the
generated `openapi.json` is the single cross-endpoint contract and the frontend
types are generated from it. Admin routes reuse the same building blocks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..settings.models import Settings


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ImagePayload(Model):
    """Resolved derivative metadata for one media row (see images.image_payload)."""

    width: int
    height: int
    s: int
    l: int
    f: int
    formats: list[str]
    base: str
    direct: str | None = None


class AuthorBrief(Model):
    name: str
    avatar: str = ""


class AuthorFull(AuthorBrief):
    bio: str = ""


class TermBrief(Model):
    id: int
    name: str
    slug: str


class TaxonomyTerm(Model):
    id: int
    name: str
    slug: str
    description: str = ""
    count: int = 0


class TocEntry(Model):
    level: int = 2
    text: str = ""
    id: str = ""


class NavLink(Model):
    label: str
    url: str


class SiteSettingsPublic(Model):
    site_title: str
    site_subtitle: str
    tagline: str
    description: str
    site_url: str
    logo: str
    favicon: str
    nav: list[NavLink]
    social: list[NavLink]
    footer_links: list[NavLink]
    footer_text: str
    footer_note: str
    icp: str
    seo_description: str
    seo_keywords: str
    og_image: str
    posts_per_page: int
    gallery_columns: int
    announcement: str


class AppearanceSettingsPublic(Model):
    theme: Literal["scene", "stone", "sand", "night"]
    color_mode: Literal["light", "dark", "system"]
    accent: str
    font_pair: Literal["sans", "serif", "mono"]
    layout_width: int
    radius: int
    post_layout: Literal["grid", "list"]
    hero_style: Literal["split", "minimal", "image"]
    hero_show: bool
    hero_eyebrow: str
    hero_title: str
    hero_subtitle: str
    hero_image: str
    show_reading_time: bool
    show_author: bool
    custom_css: str
    head_html: str


class CopySettingsPublic(Model):
    # All theme copy fields are short strings; keep them in one flat object.
    hero_primary_label: str
    hero_primary_url: str
    hero_secondary_label: str
    hero_secondary_url: str
    index_title: str
    index_lead: str
    photos_title: str
    photos_lead: str
    photos_link: str
    projects_title: str
    projects_lead: str
    projects_link: str
    texts_title: str
    texts_lead: str
    texts_link: str
    stat_photos: str
    stat_projects: str
    stat_texts: str
    home_empty_title: str
    home_empty_text: str
    home_empty_cta: str
    cta_title: str
    cta_text: str
    cta_rss: str
    cta_search: str
    photos_eyebrow: str
    photos_empty_title: str
    photos_empty_text: str
    photos_empty_cta: str
    projects_eyebrow: str
    projects_empty_title: str
    projects_empty_text: str
    projects_empty_cta: str
    project_year: str
    project_role: str
    project_client: str
    project_kind: str
    author: str
    project_link: str
    project_back: str
    project_related: str
    texts_eyebrow: str
    texts_empty_title: str
    texts_empty_text: str
    texts_empty_cta: str
    search_eyebrow: str
    search_title: str
    search_lead: str
    search_placeholder: str
    search_empty: str
    search_projects: str
    search_photos: str
    search_photo_items: str
    search_texts: str
    search_suggestions: str
    notfound_title: str
    notfound_text: str
    notfound_cta: str
    footer_admin: str
    skip_link: str
    back_to_top: str
    article_related: str
    article_all: str
    article_share: str
    article_filed: str


class PublicSettings(Model):
    site: SiteSettingsPublic
    appearance: AppearanceSettingsPublic
    copy: CopySettingsPublic  # type: ignore[assignment]  # domain name, shadows BaseModel.copy


class SiteInfoResponse(Model):
    settings: PublicSettings
    categories: list[TaxonomyTerm]
    tags: list[TaxonomyTerm]
    post_count: int
    project_count: int
    photo_count: int
    gallery_count: int
    hero_image_info: ImagePayload | None = None
    og_image_info: ImagePayload | None = None


class HealthResponse(Model):
    ok: bool
    time: str


class EdgeHealthResponse(Model):
    ok: bool
    client_ip: str
    forwarded_for: str | None = None
    forwarded_proto: str | None = None
    request_id: str = ""
    trusted_proxy: str
    cookie_secure: bool


class Pagination(Model):
    page: int
    per_page: int
    total: int
    pages: int
    has_prev: bool
    has_next: bool


class ContentListItem(Model):
    id: int
    type: Literal["post", "project", "page"]
    title: str
    slug: str
    url: str
    excerpt: str
    cover_image: str
    status: str
    featured: bool
    published_at: str | None = None
    created_at: str
    updated_at: str
    reading_time: int
    author: AuthorBrief
    categories: list[TermBrief] = Field(default_factory=list)
    tags: list[TermBrief] = Field(default_factory=list)
    project_year: str = ""
    project_role: str = ""
    project_client: str = ""
    project_kind: str = ""
    project_url: str = ""
    cover: ImagePayload | None = None


class AdjacentPost(Model):
    title: str
    slug: str
    url: str


class ContentDetail(ContentListItem):
    content_html: str
    toc: list[TocEntry] = Field(default_factory=list)
    author: AuthorFull  # type: ignore[assignment]
    seo_title: str = ""
    seo_description: str = ""
    canonical: str = ""
    prev: AdjacentPost | None = None
    next: AdjacentPost | None = None
    related: list[ContentListItem] = Field(default_factory=list)


class ContentListResponse(Pagination):
    items: list[ContentListItem]


class PageListResponse(Model):
    items: list[ContentListItem]
    total: int


class ProjectListResponse(Pagination):
    items: list[ContentListItem]


class ArchiveYear(Model):
    year: str
    count: int


class ArchiveResponse(Model):
    items: list[ContentListItem]
    total: int
    years: list[ArchiveYear]


class GalleryBrief(Model):
    id: int
    title: str
    slug: str
    url: str


class PublicExif(Model):
    camera: str | None = None
    lens: str | None = None
    taken_at: str | None = None
    taken_at_raw: str | None = None
    aperture: str | None = None
    exposure: str | None = None
    iso: int | None = None
    focal_length: str | None = None
    focal_length_35mm: int | None = None


class PhotoImage(Model):
    """Photo payload: image metadata plus EXIF projection and download links."""

    id: int
    gallery_id: int | None = None
    gallery: GalleryBrief | None = None
    media_id: int | None = None
    url: str
    filename: str
    title: str
    caption: str
    alt: str
    location: str
    camera: str
    lens: str
    taken_at: str
    taken_at_raw: str = ""
    aperture: str = ""
    exposure: str = ""
    iso: int | None = None
    focal_length: str = ""
    focal_length_35mm: int | None = None
    exif_fields: list[str] = Field(default_factory=list)
    exif: PublicExif | None = None
    image: ImagePayload | None = None
    allow_download: bool
    download_name: str
    download_url: str
    width: int
    height: int
    aspect: float
    featured: bool
    status: str
    sort_order: int
    created_at: str


class GallerySummary(Model):
    id: int
    title: str
    slug: str
    url: str
    description: str
    status: str
    featured: bool
    cover: PhotoImage | None = None
    photo_count: int
    created_at: str
    updated_at: str
    author: AuthorBrief


class GalleryDetail(GallerySummary):
    photos: list[PhotoImage] = Field(default_factory=list)
    related: list[GallerySummary] = Field(default_factory=list)


class GalleryListResponse(Pagination):
    items: list[GallerySummary]


class SearchResponse(Model):
    query: str
    articles: list[ContentListItem]
    projects: list[ContentListItem]
    galleries: list[GallerySummary]
    photos: list[PhotoImage]


class TaxonomyResponse(Model):
    categories: list[TaxonomyTerm]
    tags: list[TaxonomyTerm]


class OkResponse(Model):
    ok: bool


# --- Admin DTOs ------------------------------------------------------------


class AdminAuthorBrief(AuthorBrief):
    """Admin listings include the owner's username (public payloads drop it)."""

    username: str = ""


class AdminAuthor(AdminAuthorBrief):
    bio: str = ""


class AdminContentListItem(ContentListItem):
    raw_status: str = "draft"
    owner_id: int | None = None
    seo_title: str = ""
    seo_description: str = ""
    revision_count: int = 0


class AdminContentDetail(ContentDetail):
    raw_status: str = "draft"
    owner_id: int | None = None
    content_md: str = ""
    render_version: int = 1
    revision_count: int = 0
    # The single-item payload keeps the author's username (the list payload does
    # not); see `posts.serialize_post(admin=True)`.
    author: AdminAuthor  # type: ignore[assignment]


class AdminContentListResponse(Pagination):
    items: list[AdminContentListItem]
    counts: dict[str, int]


class AdminContentItem(AdminContentListItem):
    """Single-item response from POST/PATCH (no rendered body, keeps Markdown)."""

    content_md: str = ""
    render_version: int = 1
    author: AdminAuthor  # type: ignore[assignment]


class ContentDeleteResponse(Model):
    ok: bool
    deleted: int
    title: str
    type: str


class RevisionItem(Model):
    id: int
    title: str
    excerpt: str
    created_at: str
    content_md: str
    reading_time: int
    author_name: str | None = None


class RevisionListResponse(Model):
    items: list[RevisionItem]
    total: int


class DeleteResponse(Model):
    ok: bool
    deleted: int
    title: str | None = None
    type: str | None = None


class RecentGallery(Model):
    id: int
    title: str
    slug: str
    status: str
    updated_at: str
    photo_count: int = 0


class DashboardSystem(Model):
    version: str
    generated_at: str


class DashboardStats(Model):
    posts: dict[str, int]
    projects: dict[str, int]
    pages: int
    media: int
    galleries: int
    photos: int
    tags: int
    categories: int
    recent_posts: list[AdminContentListItem]
    recent_projects: list[AdminContentListItem]
    recent_galleries: list[RecentGallery]
    system: DashboardSystem


class TaxonomyAdminTerm(Model):
    id: int
    name: str
    slug: str
    description: str = ""
    count: int = 0


class TaxonomyAdminResponse(Model):
    categories: list[TaxonomyAdminTerm]
    tags: list[TaxonomyAdminTerm]


class SessionUser(Model):
    id: int
    username: str
    display_name: str
    email: str = ""
    bio: str = ""
    avatar: str = ""
    role: str
    role_label: str
    is_active: bool
    last_login_at: str = ""
    permissions: list[str] = Field(default_factory=list)
    can_manage_others: bool = False
    created_at: str


class ProfileResponse(Model):
    user: SessionUser


class ProfileUser(Model):
    """Shape returned by the profile PATCH: the fields the member may edit."""

    id: int
    username: str
    display_name: str
    email: str = ""
    bio: str = ""
    avatar: str = ""
    role: str


class ProfileUpdateResponse(Model):
    ok: bool
    user: ProfileUser


class ContentAuthor(Model):
    id: int
    username: str
    name: str
    role: str
    role_label: str
    is_active: bool


class ContentAuthorsResponse(Model):
    items: list[ContentAuthor]


class PreviewResponse(Model):
    html: str
    toc: list[TocEntry]
    reading_time: int


class JobStatusResponse(Model):
    id: int
    kind: str
    status: str
    progress: int
    result: str = ""
    error: str = ""
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


# --- Taxonomies (admin) ----------------------------------------------------


class TaxonomyTermResponse(Model):
    """A full `taxonomy_terms` row as returned by create/update."""

    id: int
    kind: str
    name: str
    slug: str
    description: str = ""
    created_at: str


class TaxonomyDeleteResponse(Model):
    ok: bool
    deleted: int
    name: str


# --- Settings (admin) ------------------------------------------------------


class SettingsMetaImage(Model):
    avif: bool
    webp: bool
    scenes: list[str]


class SettingsMetaStorage(Model):
    backends: list[str]
    serve_modes: list[str]
    access_key_configured: bool
    secret_key_configured: bool


class SettingsMeta(Model):
    """Display metadata (allowed enum values / capability flags) for the editor."""

    version: str
    themes: list[str]
    color_modes: list[str]
    font_pairs: list[str]
    post_layouts: list[str]
    hero_styles: list[str]
    image: SettingsMetaImage
    storage: SettingsMetaStorage


class StorageSecrets(Model):
    access_key_configured: bool
    secret_key_configured: bool


class AdminSettingsResponse(Model):
    settings: Settings
    meta: SettingsMeta
    storage_secrets: StorageSecrets


class AdminSettingsUpdateResponse(AdminSettingsResponse):
    ok: bool
    updated: list[str]


# --- Auth / profile --------------------------------------------------------


class AuthStatusResponse(Model):
    authenticated: bool
    user: SessionUser | None = None
    needs_setup: bool


class LoginResponse(Model):
    ok: bool
    user: SessionUser
    redirect: str


class SetupResponse(Model):
    ok: bool
    redirect: str


# --- Users (admin) ---------------------------------------------------------


class AdminUserItem(Model):
    id: int
    username: str
    display_name: str
    email: str = ""
    bio: str = ""
    avatar: str = ""
    role: str
    role_label: str
    is_active: bool
    last_login_at: str = ""
    created_at: str
    permissions: list[str] = Field(default_factory=list)
    content_count: int = 0
    gallery_count: int = 0
    media_count: int = 0


class AdminUserListResponse(Model):
    items: list[AdminUserItem]
    total: int
    counts: dict[str, int]


class AdminUserMutationResponse(Model):
    ok: bool
    user: AdminUserItem


class UserDeleteResponse(Model):
    ok: bool
    deleted: int
    username: str


class RoleMetaItem(Model):
    key: str
    label: str
    summary: str
    permissions: list[str]


class PermissionMetaItem(Model):
    key: str
    label: str


class UsersMetaResponse(Model):
    roles: list[RoleMetaItem]
    permissions: list[PermissionMetaItem]
    role_labels: dict[str, str]


# --- Galleries (admin) -----------------------------------------------------


class AdminGallerySummary(GallerySummary):
    author: AdminAuthorBrief  # type: ignore[assignment]
    owner_id: int | None = None
    cover_photo_id: int | None = None


class AdminGalleryDetail(AdminGallerySummary):
    photos: list[PhotoImage] = Field(default_factory=list)


class AdminGalleryListResponse(Pagination):
    items: list[AdminGallerySummary]
    counts: dict[str, int]


class PhotoListResponse(Pagination):
    items: list[PhotoImage]


class GalleryDeleteResponse(Model):
    ok: bool
    deleted: int
    title: str


class GalleryPhotosAddedResponse(Model):
    ok: bool
    added: list[int]
    gallery: AdminGalleryDetail


class GalleryReorderResponse(Model):
    ok: bool
    gallery: AdminGalleryDetail


class PhotoDeleteResponse(Model):
    ok: bool
    deleted: int


# --- Media (admin) ---------------------------------------------------------


class ExifGps(Model):
    latitude: float
    longitude: float
    altitude: float | None = None


class ExifPayload(Model):
    """Typed projection of the JSON block stored in `media.exif`."""

    found: bool = True
    camera: str = ""
    make: str = ""
    model: str = ""
    lens: str = ""
    taken_at: str = ""
    taken_at_raw: str = ""
    exposure: str = ""
    aperture: str = ""
    iso: int | None = None
    focal_length: str = ""
    focal_length_35mm: int | None = None
    orientation: int | None = None
    software: str = ""
    artist: str = ""
    copyright: str = ""
    gps: ExifGps | None = None
    # Raw EXIF tags: tag name -> JSON scalar/array/object (see exif._json_safe).
    raw: dict[str, JsonValue] = Field(default_factory=dict)


class MediaOwner(Model):
    id: int
    name: str
    username: str = ""


class MediaItem(Model):
    id: int
    filename: str
    original_name: str
    mime: str
    size: int
    width: int = 0
    height: int = 0
    alt: str = ""
    owner_id: int
    exif: ExifPayload | None = None
    avif_quality: int
    avif_quality_auto: bool
    placeholder: str = ""
    created_at: str
    owner: MediaOwner
    url: str
    kind: Literal["image", "audio", "file"]
    image: ImagePayload | None = None


class MediaUploadResponse(MediaItem):
    exif_summary: str = ""


class MediaListResponse(Pagination):
    items: list[MediaItem]


class MediaDeleteResponse(Model):
    ok: bool
    deleted: int


class OptimizeStatusResponse(Model):
    running: bool
    total: int
    done: int
    failed: int
    started_at: str
    finished_at: str
    error: str = ""


class OptimizeStartResponse(Model):
    ok: bool
    started: bool
    message: str = ""


class OptimizeQueuedResponse(Model):
    ok: bool
    queued: bool
    media_id: int


class MediaExifResponse(Model):
    media_id: int
    exif: ExifPayload | None = None
    source: Literal["cache", "file", "none"]
    summary: str


class StorageConfigInfo(Model):
    backend: str
    serve_mode: str
    bucket: str = ""
    endpoint: str = ""
    region: str = ""
    prefix: str = ""
    path_style: bool = False
    public_base_url: str = ""
    direct_enabled: bool = False
    backup_local: bool = False
    secret_configured: bool = False


class StorageHealthResponse(Model):
    ok: bool
    backend: str
    bucket: str = ""
    backup_local: bool = False
    backup_ok: bool | None = None
    backup_error: str = ""


class DerivativeStats(Model):
    files: int
    bytes: int


class StorageStatusResponse(Model):
    config: StorageConfigInfo
    avif: bool
    webp: bool
    reachable: bool | None = None
    error: str = ""
    health: StorageHealthResponse | None = None
    derivatives: DerivativeStats


class StorageTestResponse(Model):
    ok: bool
    backend: str = ""
    message: str


class StorageSyncStatusResponse(Model):
    running: bool
    total: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    current: str = ""
    force: bool = False
    scope: str = "all"
    started_at: str = ""
    finished_at: str = ""
    error: str = ""
    errors: list[str] = Field(default_factory=list)


class StorageSyncStartResponse(Model):
    ok: bool
    started: bool
    message: str = ""
    force: bool = False
    scope: str = "all"


# --- Data export (3.0.0 backup format) -------------------------------------


class ExportPost(Model):
    """One `posts` row exactly as stored (booleans are SQLite 0/1 integers)."""

    id: int
    type: str
    title: str
    slug: str
    excerpt: str
    content_md: str
    content_html: str
    render_version: int
    cover_image: str
    status: str
    published_at: str | None = None
    featured: int
    owner_id: int
    seo_title: str
    seo_description: str
    reading_time: int
    toc_json: str
    created_at: str
    updated_at: str


class ExportProjectDetail(Model):
    post_id: int
    kind: str
    year: str
    role: str
    client: str
    url: str


class ExportTaxonomyTerm(Model):
    id: int
    kind: str
    name: str
    slug: str
    description: str
    created_at: str


class ExportPostTerm(Model):
    post_id: int
    term_id: int


class ExportGallery(Model):
    id: int
    title: str
    slug: str
    description: str
    status: str
    featured: int
    cover_photo_id: int | None = None
    owner_id: int
    created_at: str
    updated_at: str


class ExportPhoto(Model):
    id: int
    gallery_id: int | None = None
    media_id: int | None = None
    filename: str
    title: str
    caption: str
    location: str
    camera: str
    lens: str
    taken_at: str
    width: int
    height: int
    exif_fields: str
    allow_download: int
    featured: int
    status: str
    sort_order: int
    created_at: str


class ExportMedia(Model):
    id: int
    filename: str
    original_name: str
    mime: str
    size: int
    width: int
    height: int
    alt: str
    owner_id: int
    # Stored as the raw JSON TEXT column, not the parsed object.
    exif: str
    avif_quality: int
    avif_quality_auto: int
    placeholder: str
    ready_hash: str
    created_at: str


class ExportRevision(Model):
    id: int
    post_id: int
    title: str
    excerpt: str
    content_md: str
    owner_id: int | None = None
    created_at: str


class ExportV3Response(Model):
    format: Literal["mztlab-scene-export"]
    version: Literal[3]
    exported_at: str
    settings: PublicSettings
    posts: list[ExportPost]
    project_details: list[ExportProjectDetail]
    taxonomy_terms: list[ExportTaxonomyTerm]
    post_terms: list[ExportPostTerm]
    galleries: list[ExportGallery]
    photos: list[ExportPhoto]
    media: list[ExportMedia]
    revisions: list[ExportRevision]
