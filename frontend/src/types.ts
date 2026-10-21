/**
 * API types.
 *
 * The shapes below are aliases into `src/api/types.gen.ts`, which is generated
 * from the backend OpenAPI contract (`npm run gen:types`). Do not hand-write
 * field lists here: CI regenerates the contract and fails on drift.
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
export type ImageInfo = RequiredKeys<Schemas['ImagePayload']>;
export type TocItem = RequiredKeys<Schemas['TocEntry']>;
export type Term = DeepRequired<Schemas['TaxonomyTerm']>;
export type MiniTerm = RequiredKeys<Schemas['TermBrief']>;
export type Author = RequiredKeys<Schemas['AuthorBrief']> &
  Partial<Schemas['AuthorFull']>;

// --- Public site data -------------------------------------------------------

export type SiteSettings = DeepRequired<Schemas['SiteSettingsPublic']>;
export type AppearanceSettings = DeepRequired<Schemas['AppearanceSettingsPublic']>;
export type CopySettings = DeepRequired<Schemas['CopySettingsPublic']>;
export type PublicSettings = DeepRequired<Schemas['PublicSettings']>;
export type SiteInfo = DeepRequired<Schemas['SiteInfoResponse']>;

// --- Content ----------------------------------------------------------------

export type PostSummary = DeepRequired<Schemas['ContentListItem']> &
  Partial<Schemas['AdminContentListItem']>;
export type Project = PostSummary & { type: 'project' };
export type PostDetail = DeepRequired<Schemas['ContentDetail']>;
export type AdminPost = DeepRequired<Schemas['AdminContentDetail']>;
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

export type Photo = Omit<DeepRequired<Schemas['PhotoImage']>, 'exif'> & {
  exif: PhotoExif | null;
};

/** A gallery list item; detail responses additionally carry photos/related. */
export type Gallery = DeepRequired<Schemas['GallerySummary']> & {
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

export type SearchResults = DeepRequired<Schemas['SearchResponse']>;

// --- Auth and members -------------------------------------------------------

export type SiteStatus = DeepRequired<Schemas['AuthStatusResponse']>;
export type AdminUser = DeepRequired<Schemas['SessionUser']>;
export type AuthorOption = DeepRequired<Schemas['ContentAuthor']>;
export type Member = DeepRequired<Schemas['AdminUserItem']>;
export type Stats = DeepRequired<Schemas['DashboardStats']>;

// --- Media ------------------------------------------------------------------

export type MediaItem = DeepRequired<Schemas['MediaItem']>;
export type ExifGps = RequiredKeys<Schemas['ExifGps']>;
export type ExifInfo = DeepRequired<Schemas['ExifPayload']>;

// --- Admin settings ---------------------------------------------------------

export type UploadSettings = DeepRequired<Schemas['UploadSettings']>;
export type ImagePipelineSettings = DeepRequired<Schemas['ImagePipelineSettings']>;
export type StorageSettings = DeepRequired<Schemas['StorageSettings']>;
export type AdvancedSettings = DeepRequired<Schemas['AdvancedSettings']>;
export type AdminSiteSettings = DeepRequired<Schemas['SiteSettings']>;
/** Generated group models mark defaults optional; the admin always receives all groups. */
export type AdminSettings = DeepRequired<Schemas['Settings']>;
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
