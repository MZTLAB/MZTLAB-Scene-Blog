/**
 * Admin settings form plumbing.
 *
 * 3.0.0 stores settings as grouped documents (`site`, `appearance`, `copy`,
 * `upload`, `advanced`) and updates them with a partial PATCH body. The admin
 * forms keep their existing flat `data-setting="<key>"` attributes; this module
 * maps every flat form key to its group path so the forms did not have to be
 * rewritten. Unknown keys are ignored by `buildSettingsPatch`.
 */
import type { AdminSettings } from '../types';

export type SettingsGroup = 'site' | 'appearance' | 'copy' | 'upload' | 'advanced';
type FieldKind = 'text' | 'number' | 'boolean' | 'list' | 'int-list';

export interface SettingField {
  group: SettingsGroup;
  path: readonly string[];
  kind?: FieldKind;
}

type FieldTable = Record<string, SettingField>;

/** `settings.site` fields. */
const SITE_FIELDS: FieldTable = {
  site_title: { group: 'site', path: ['site_title'] },
  site_subtitle: { group: 'site', path: ['site_subtitle'] },
  tagline: { group: 'site', path: ['tagline'] },
  description: { group: 'site', path: ['description'] },
  site_url: { group: 'site', path: ['site_url'] },
  logo: { group: 'site', path: ['logo'] },
  favicon: { group: 'site', path: ['favicon'] },
  announcement: { group: 'site', path: ['announcement'] },
  posts_per_page: { group: 'site', path: ['posts_per_page'], kind: 'number' },
  gallery_columns: { group: 'site', path: ['gallery_columns'], kind: 'number' },
  footer_text: { group: 'site', path: ['footer_text'] },
  footer_note: { group: 'site', path: ['footer_note'] },
  icp: { group: 'site', path: ['icp'] },
  seo_description: { group: 'site', path: ['seo_description'] },
  seo_keywords: { group: 'site', path: ['seo_keywords'] },
  og_image: { group: 'site', path: ['og_image'] },
  editor_manage_others: { group: 'site', path: ['editor_manage_others'], kind: 'boolean' },
};

/** `settings.appearance` fields. */
const APPEARANCE_FIELDS: FieldTable = {
  theme: { group: 'appearance', path: ['theme'] },
  color_mode: { group: 'appearance', path: ['color_mode'] },
  accent: { group: 'appearance', path: ['accent'] },
  font_pair: { group: 'appearance', path: ['font_pair'] },
  layout_width: { group: 'appearance', path: ['layout_width'], kind: 'number' },
  radius: { group: 'appearance', path: ['radius'], kind: 'number' },
  post_layout: { group: 'appearance', path: ['post_layout'] },
  hero_style: { group: 'appearance', path: ['hero_style'] },
  hero_show: { group: 'appearance', path: ['hero_show'], kind: 'boolean' },
  hero_eyebrow: { group: 'appearance', path: ['hero_eyebrow'] },
  hero_title: { group: 'appearance', path: ['hero_title'] },
  hero_subtitle: { group: 'appearance', path: ['hero_subtitle'] },
  hero_image: { group: 'appearance', path: ['hero_image'] },
  show_reading_time: { group: 'appearance', path: ['show_reading_time'], kind: 'boolean' },
  show_author: { group: 'appearance', path: ['show_author'], kind: 'boolean' },
  custom_css: { group: 'appearance', path: ['custom_css'] },
  head_html: { group: 'appearance', path: ['head_html'] },
};

/** `settings.copy` fields. The flat form keys keep their old `copy_` prefix. */
const COPY_KEYS = [
  'hero_primary_label',
  'hero_primary_url',
  'hero_secondary_label',
  'hero_secondary_url',
  'index_title',
  'index_lead',
  'photos_title',
  'photos_lead',
  'photos_link',
  'projects_title',
  'projects_lead',
  'projects_link',
  'texts_title',
  'texts_lead',
  'texts_link',
  'stat_photos',
  'stat_projects',
  'stat_texts',
  'home_empty_title',
  'home_empty_text',
  'home_empty_cta',
  'cta_title',
  'cta_text',
  'cta_rss',
  'cta_search',
  'photos_eyebrow',
  'photos_empty_title',
  'photos_empty_text',
  'photos_empty_cta',
  'projects_eyebrow',
  'projects_empty_title',
  'projects_empty_text',
  'projects_empty_cta',
  'project_year',
  'project_role',
  'project_client',
  'project_kind',
  'author',
  'project_link',
  'project_back',
  'project_related',
  'texts_eyebrow',
  'texts_empty_title',
  'texts_empty_text',
  'texts_empty_cta',
  'search_eyebrow',
  'search_title',
  'search_lead',
  'search_placeholder',
  'search_empty',
  'search_projects',
  'search_photos',
  'search_photo_items',
  'search_texts',
  'search_suggestions',
  'notfound_title',
  'notfound_text',
  'notfound_cta',
  'footer_admin',
  'skip_link',
  'back_to_top',
  'article_related',
  'article_all',
  'article_share',
  'article_filed',
] as const;

const COPY_FIELDS: FieldTable = Object.fromEntries(
  COPY_KEYS.map((key) => [`copy_${key}`, { group: 'copy', path: [key] } satisfies SettingField]),
);

/** `settings.upload` fields. */
const UPLOAD_FIELDS: FieldTable = {
  upload_max_mb: { group: 'upload', path: ['max_mb'], kind: 'number' },
  upload_image_formats: { group: 'upload', path: ['image_formats'], kind: 'list' },
  upload_audio_formats: { group: 'upload', path: ['audio_formats'], kind: 'list' },
  upload_file_formats: { group: 'upload', path: ['file_formats'], kind: 'list' },
};

/** `settings.advanced.image` fields. */
const IMAGE_FIELDS: FieldTable = {
  image_avif_enabled: { group: 'advanced', path: ['image', 'avif_enabled'], kind: 'boolean' },
  image_avif_speed: { group: 'advanced', path: ['image', 'avif_speed'], kind: 'number' },
  image_webp_enabled: { group: 'advanced', path: ['image', 'webp_enabled'], kind: 'boolean' },
  image_webp_quality: { group: 'advanced', path: ['image', 'webp_quality'], kind: 'number' },
  image_jpeg_quality: { group: 'advanced', path: ['image', 'jpeg_quality'], kind: 'number' },
  image_quality_thumb: { group: 'advanced', path: ['image', 'quality_thumb'], kind: 'number' },
  image_quality_tile: { group: 'advanced', path: ['image', 'quality_tile'], kind: 'number' },
  image_quality_card: { group: 'advanced', path: ['image', 'quality_card'], kind: 'number' },
  image_quality_hero: { group: 'advanced', path: ['image', 'quality_hero'], kind: 'number' },
  image_quality_viewer: { group: 'advanced', path: ['image', 'quality_viewer'], kind: 'number' },
  image_quality_prose: { group: 'advanced', path: ['image', 'quality_prose'], kind: 'number' },
  image_quality_full: { group: 'advanced', path: ['image', 'quality_full'], kind: 'number' },
  image_widths: { group: 'advanced', path: ['image', 'widths'], kind: 'int-list' },
  image_max_width: { group: 'advanced', path: ['image', 'max_width'], kind: 'number' },
  image_cache_days: { group: 'advanced', path: ['image', 'cache_days'], kind: 'number' },
  image_prewarm: { group: 'advanced', path: ['image', 'prewarm'], kind: 'boolean' },
  image_lazy_enabled: { group: 'advanced', path: ['image', 'lazy'], kind: 'boolean' },
};

/** `settings.advanced.storage` fields. Credentials are environment-only. */
const STORAGE_FIELDS: FieldTable = {
  storage_backend: { group: 'advanced', path: ['storage', 'backend'] },
  storage_serve_mode: { group: 'advanced', path: ['storage', 'serve_mode'] },
  storage_public_base_url: { group: 'advanced', path: ['storage', 'public_base_url'] },
  storage_s3_endpoint: { group: 'advanced', path: ['storage', 's3_endpoint'] },
  storage_s3_bucket: { group: 'advanced', path: ['storage', 's3_bucket'] },
  storage_s3_region: { group: 'advanced', path: ['storage', 's3_region'] },
  storage_s3_prefix: { group: 'advanced', path: ['storage', 's3_prefix'] },
  storage_s3_path_style: { group: 'advanced', path: ['storage', 's3_path_style'], kind: 'boolean' },
  storage_backup_local: { group: 'advanced', path: ['storage', 'backup_local'], kind: 'boolean' },
};

export const SETTING_FIELDS: FieldTable = {
  ...SITE_FIELDS,
  ...APPEARANCE_FIELDS,
  ...COPY_FIELDS,
  ...UPLOAD_FIELDS,
  ...IMAGE_FIELDS,
  ...STORAGE_FIELDS,
};

function navigate(source: unknown, path: readonly string[]): unknown {
  let node: unknown = source;
  for (const part of path) {
    if (!node || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

/** Read one flat form key out of the grouped settings document. */
export function readSetting(settings: AdminSettings, key: string): unknown {
  const field = SETTING_FIELDS[key];
  return field ? navigate(settings, [field.group, ...field.path]) : undefined;
}

function formatValue(field: SettingField, value: unknown): string | boolean {
  switch (field.kind) {
    case 'boolean':
      return Boolean(value);
    case 'list':
      return Array.isArray(value) ? value.join(',') : String(value ?? '');
    case 'int-list':
      return Array.isArray(value) ? value.join(',') : String(value ?? '');
    case 'number':
      return value === undefined || value === null ? '' : String(value);
    default:
      return String(value ?? '');
  }
}

/** Flat `data-setting` key -> form value used to hydrate the inputs. */
export function flattenSettings(settings: AdminSettings): Record<string, string | boolean> {
  const result: Record<string, string | boolean> = {};
  for (const [key, field] of Object.entries(SETTING_FIELDS)) {
    result[key] = formatValue(field, navigate(settings, [field.group, ...field.path]));
  }
  return result;
}

function parseValue(field: SettingField, raw: string | boolean): unknown {
  switch (field.kind) {
    case 'boolean':
      return typeof raw === 'boolean' ? raw : raw === 'true';
    case 'number': {
      const value = Number(raw);
      return Number.isFinite(value) ? value : 0;
    }
    case 'list':
      return String(raw)
        .replace(/;/g, ',')
        .split(',')
        .map((token) => token.trim().toLowerCase().replace(/^\./, ''))
        .filter(Boolean);
    case 'int-list':
      return String(raw)
        .replace(/;/g, ',')
        .split(',')
        .map((token) => Number(token.trim()))
        .filter((value) => Number.isFinite(value) && value > 0);
    default:
      return String(raw);
  }
}

/**
 * Turn flat form values into the grouped partial body for
 * `PATCH /api/admin/settings`. `groups` limits the patch to the groups a page
 * actually owns so unrelated fields are never accidentally written.
 */
export function buildSettingsPatch(
  values: Record<string, unknown>,
  groups?: readonly SettingsGroup[],
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(values)) {
    const field = SETTING_FIELDS[key];
    if (!field) continue;
    if (groups && !groups.includes(field.group)) continue;
    let target = (patch[field.group] as Record<string, unknown> | undefined) ?? {};
    patch[field.group] = target;
    for (let index = 0; index < field.path.length - 1; index += 1) {
      const segment = field.path[index];
      const next = (target[segment] as Record<string, unknown> | undefined) ?? {};
      target[segment] = next;
      target = next;
    }
    target[field.path[field.path.length - 1]] = parseValue(
      field,
      raw as string | boolean,
    );
  }
  return patch;
}
