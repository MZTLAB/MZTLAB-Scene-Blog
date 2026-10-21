/**
 * API types.
 *
 * Most shapes are aliases into `src/api/types.gen.ts`, which is generated from
 * the backend OpenAPI contract (`npm run gen:types`). Do not hand-write field
 * lists here unless the generated contract has not caught up with a phase yet:
 * the blocks marked "hand-written until the Phase 3 contract is regenerated"
 * already detect the generated shape and prefer it once it lands.
 *
 * Every response DTO is passed through `DeepRequired`: the backend serializes
 * every field (Pydantic emits `null` for absent values), so an optional marker
 * in the generated schema only reflects a Pydantic default, not a field that
 * may be missing on the wire.
 */

import type { components } from './api/types.gen';

type Schemas = components['schemas'];

/** Normalize Pydantic-default optionality away; `null` stays `null`. */
type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

/** Same, one level deep (used where a recursive walk would be too broad). */
type RequiredKeys<T> = { [K in keyof T]-?: T[K] };

// --- Shared building blocks -------------------------------------------------

export type NavLink = RequiredKeys<Schemas['app__settings__models__NavLink']>;
export type TocItem = RequiredKeys<Schemas['TocEntry']>;
export type Term = DeepRequired<Schemas['TaxonomyTerm']>;
export type MiniTerm = RequiredKeys<Schemas['TermBrief']>;
export type Author = RequiredKeys<Schemas['AuthorBrief']> &
  Partial<Schemas['AuthorFull']>;

// --- Image payload v2 (Phase 3) --------------------------------------------

/** One generated derivative: its scene, ladder width, format and token. */
export interface ImageArtifact {
  scene: string;
  width: number;
  format: string;
  token: string;
}

/** Artifact tokens keyed `scene -> width -> format -> token`. */
export type ImageArtifactMap = Record<string, Record<string, Record<string, string>>>;

/**
 * Hand-written until the Phase 3 contract is regenerated.
 *
 * `artifacts` is accepted both as the contract map and as the flattened
 * `[{scene,width,format,token}]` list for forward compatibility; `lib/images.ts`
 * normalizes either shape at runtime. A derivative URL only exists when the
 * matching token is present; `ready: false` means "render the original file".
 */
export interface ImagePayloadV2 {
  id: number;
  width: number;
  height: number;
  s: number;
  l: number;
  f: number;
  ready: boolean;
  formats: string[];
  base: string;
  direct_base: string | null;
  artifacts: ImageArtifactMap | ImageArtifact[];
  placeholder: string;
  pipeline_version?: number;
}

type GeneratedImagePayload = RequiredKeys<Schemas['ImagePayload']>;
type HasPhase3ImagePayload = 'ready' extends keyof GeneratedImagePayload ? true : false;
type BaseImagePayload = HasPhase3ImagePayload extends true
  ? GeneratedImagePayload
  : ImagePayloadV2;

export type ImageInfo = Omit<BaseImagePayload, 'pipeline_version'> & {
  pipeline_version?: number;
};

/**
 * Swap the legacy single-token image shape for the Phase 3 payload anywhere a
 * generated DTO still embeds the old `ImagePayload`.
 */
type WithImageInfo<T, K extends keyof T> = Omit<T, K> & { [P in K]: ImageInfo | null };

// --- Public site data -------------------------------------------------------

export type SiteSettings = DeepRequired<Schemas['SiteSettingsPublic']>;
export type AppearanceSettings = DeepRequired<Schemas['AppearanceSettingsPublic']>;
export type CopySettings = DeepRequired<Schemas['CopySettingsPublic']>;
export type PublicSettings = DeepRequired<Schemas['PublicSettings']>;
export type SiteInfo = Omit<
  DeepRequired<Schemas['SiteInfoResponse']>,
  'hero_image_info' | 'og_image_info'
> & {
  hero_image_info: ImageInfo | null;
  og_image_info: ImageInfo | null;
};

// --- Content ----------------------------------------------------------------

type ContentBase = WithImageInfo<DeepRequired<Schemas['ContentListItem']>, 'cover'>;

export type PostSummary = ContentBase &
  Partial<Omit<Schemas['AdminContentListItem'], 'cover'>>;
export type Project = PostSummary & { type: 'project' };
export type PostDetail = Omit<
  WithImageInfo<DeepRequired<Schemas['ContentDetail']>, 'cover'>,
  'related'
> & { related: PostSummary[] };
export type AdminPost = Omit<
  WithImageInfo<DeepRequired<Schemas['AdminContentDetail']>, 'cover'>,
  'related'
> & { related: PostSummary[] };
export type Revision = DeepRequired<Schemas['RevisionItem']>;

// --- Photos and galleries ---------------------------------------------------

/** Whitelist of EXIF fields a photo may expose publicly. */
export type PhotoExifField =
  | 'camera'
  | 'lens'
  | 'focal_length'
  | 'aperture'
  | 'exposure'
  | 'iso'
  | 'taken_at'
  | 'dimensions';

export type PhotoExif = RequiredKeys<Schemas['PublicExif']> & {
  software?: string;
  orientation?: number | null;
};

type GeneratedPhotoImage = DeepRequired<Schemas['PhotoImage']>;

/**
 * `allow_download` was renamed to `hide_download_link` with inverted semantics
 * (`true` = hide the download affordance). Added by hand until the generated
 * contract is refreshed.
 */
export type Photo = Omit<
  GeneratedPhotoImage,
  'exif' | 'image' | 'allow_download' | 'hide_download_link'
> & {
  exif: PhotoExif | null;
  image: ImageInfo | null;
  hide_download_link: boolean;
};

type GeneratedGallerySummary = DeepRequired<Schemas['GallerySummary']>;

/** A gallery list item; detail responses additionally carry photos/related. */
export type Gallery = Omit<GeneratedGallerySummary, 'cover'> & {
  cover: Photo | null;
  cover_photo_id?: number | null;
  photos?: Photo[];
  related?: Gallery[];
};

// --- Lists and search -------------------------------------------------------

export interface Paginated<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  pages: number;
  has_prev: boolean;
  has_next: boolean;
}

export type SearchResults = Omit<
  DeepRequired<Schemas['SearchResponse']>,
  'articles' | 'projects' | 'galleries' | 'photos'
> & {
  articles: PostSummary[];
  projects: PostSummary[];
  galleries: Gallery[];
  photos: Photo[];
};

// --- Aggregated page data (R1: `GET /api/bootstrap`) -----------------------

/** Route kinds accepted by `GET /api/bootstrap`, mirrored from `page_data()`. */
export type BootstrapRoute =
  | 'home'
  | 'archive'
  | 'post'
  | 'page'
  | 'project'
  | 'projects'
  | 'galleries'
  | 'gallery'
  | 'taxonomy'
  | 'search';

export interface BootstrapPagination {
  page: number;
  per_page: number;
  total: number;
  pages: number;
  has_prev: boolean;
  has_next: boolean;
}

export interface BootstrapHomePage {
  kind: 'home';
  posts: PostSummary[];
  projects: PostSummary[];
  galleries: Gallery[];
}

export interface BootstrapArchivePage {
  kind: 'archive';
  items: PostSummary[];
  total: number;
  years: Array<{ year: string; count: number }>;
}

/** One article / page / project detail (the payload includes canonical/related). */
export interface BootstrapContentPage {
  kind: 'post' | 'page' | 'project';
  item: PostDetail;
}

export interface BootstrapProjectsPage extends BootstrapPagination {
  kind: 'projects';
  items: PostSummary[];
}

export interface BootstrapGalleriesPage extends BootstrapPagination {
  kind: 'galleries';
  items: Gallery[];
}

export interface BootstrapGalleryPage {
  kind: 'gallery';
  item: Gallery;
}

export interface BootstrapTaxonomyPage extends BootstrapPagination {
  kind: 'taxonomy';
  categories: Term[];
  tags: Term[];
  term: Term | null;
  items: PostSummary[];
}

export interface BootstrapSearchPage {
  kind: 'search';
  query: string;
  articles: PostSummary[];
  projects: PostSummary[];
  galleries: Gallery[];
  photos: Photo[];
}

/**
 * Discriminated page payload. Mirrors the generated `BootstrapResponse` DTO
 * (validated server-side); it is hand-mapped here so the Phase 3 image/photo
 * overrides above apply uniformly to every page shape.
 */
export type BootstrapPage =
  | BootstrapHomePage
  | BootstrapArchivePage
  | BootstrapContentPage
  | BootstrapProjectsPage
  | BootstrapGalleriesPage
  | BootstrapGalleryPage
  | BootstrapTaxonomyPage
  | BootstrapSearchPage;

export interface BootstrapInfo {
  site: SiteInfo;
  page: BootstrapPage;
}

// --- Auth and members -------------------------------------------------------

export type SiteStatus = DeepRequired<Schemas['AuthStatusResponse']>;
export type AdminUser = DeepRequired<Schemas['SessionUser']>;
export type AuthorOption = DeepRequired<Schemas['ContentAuthor']>;
export type Member = DeepRequired<Schemas['AdminUserItem']>;
export type Stats = DeepRequired<Schemas['DashboardStats']>;

// --- Media ------------------------------------------------------------------

export type MediaItem = Omit<
  DeepRequired<Schemas['MediaItemPayload']>,
  'image' | 'avif_quality' | 'avif_quality_auto'
> & {
  image: ImageInfo | null;
};
export type ExifGps = RequiredKeys<Schemas['ExifGps']>;
export type ExifInfo = DeepRequired<Schemas['ExifPayload']>;

// --- Admin settings ---------------------------------------------------------

export type UploadSettings = DeepRequired<Schemas['UploadSettings']>;

/**
 * Hand-written until the Phase 3 contract is regenerated: quality/encoding
 * parameters are code constants (ADR-10), only these three fields are settings.
 */
export interface ImagePipelineSettingsV2 {
  widths: number[];
  avif_enabled: boolean;
  webp_enabled: boolean;
}

type GeneratedImagePipeline = DeepRequired<Schemas['ImagePipelineSettings']>;
type HasPhase3ImagePipeline = 'quality_thumb' extends keyof GeneratedImagePipeline
  ? false
  : true;
export type ImagePipelineSettings = HasPhase3ImagePipeline extends true
  ? GeneratedImagePipeline
  : ImagePipelineSettingsV2;

export type StorageSettings = DeepRequired<Schemas['StorageSettings']>;
export type AdvancedSettings = Omit<DeepRequired<Schemas['AdvancedSettings']>, 'image'> & {
  image: ImagePipelineSettings;
};
export type AdminSiteSettings = DeepRequired<Schemas['SiteSettings-Output']>;
/** Generated group models mark defaults optional; the admin always receives all groups. */
export type AdminSettings = Omit<DeepRequired<Schemas['Settings-Output']>, 'advanced'> & {
  advanced: AdvancedSettings;
};
export type SettingsStorageSecrets = RequiredKeys<Schemas['StorageSecrets']>;
export type SettingsMeta = DeepRequired<Schemas['SettingsMeta']>;
export type AdminSettingsResponse = Omit<
  Schemas['AdminSettingsResponse'],
  'settings'
> & { settings: AdminSettings };
export type AdminSettingsUpdateResponse = Omit<
  Schemas['AdminSettingsUpdateResponse'],
  'settings'
> & { settings: AdminSettings };
