import type {
  AppearanceSettings,
  CopySettings,
  SiteSettings,
  PublicSettings,
} from '../types';

/** Read a `settings.copy` value, falling back when it is empty. */
export function copyText(
  copy: CopySettings,
  key: keyof CopySettings,
  fallback = '',
): string {
  const value = copy[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

/** Build a `copy(key, fallback)` helper bound to a site's copy group. */
export function copyReader(settings: PublicSettings) {
  return (key: keyof CopySettings, fallback = ''): string =>
    copyText(settings.copy, key, fallback);
}

export const PALETTES = ['scene', 'stone', 'sand', 'night'] as const;
export const COLOR_MODES = ['light', 'dark', 'system'] as const;
export const FONT_PAIRS = ['sans', 'serif', 'mono'] as const;
export const HERO_STYLES = ['split', 'minimal', 'image'] as const;

export interface ThemeTokens {
  accent: string;
  width: number;
  radius: number;
  columns: number;
  colorMode: (typeof COLOR_MODES)[number];
  palette: (typeof PALETTES)[number];
  fontPair: (typeof FONT_PAIRS)[number];
}

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

/**
 * Normalize the appearance tokens once, instead of repeating the same clamps
 * in every layout. The values come from the validated backend settings, so the
 * fallbacks here only protect CSS from an unknown enum — they are not site
 * content defaults.
 */
export function themeTokens(appearance: AppearanceSettings, site: SiteSettings): ThemeTokens {
  const colorMode = COLOR_MODES.includes(appearance.color_mode as (typeof COLOR_MODES)[number])
    ? (appearance.color_mode as ThemeTokens['colorMode'])
    : 'light';
  const palette = PALETTES.includes(appearance.theme as (typeof PALETTES)[number])
    ? (appearance.theme as ThemeTokens['palette'])
    : 'scene';
  const fontPair = FONT_PAIRS.includes(appearance.font_pair as (typeof FONT_PAIRS)[number])
    ? (appearance.font_pair as ThemeTokens['fontPair'])
    : 'mono';
  return {
    accent: HEX_COLOR.test(appearance.accent || '') ? appearance.accent : '#c2451f',
    width: Math.min(1600, Math.max(720, Number(appearance.layout_width) || 1360)),
    radius: Math.min(40, Math.max(0, Number(appearance.radius) || 0)),
    columns: Math.min(4, Math.max(2, Number(site.gallery_columns) || 3)),
    colorMode,
    palette,
    fontPair,
  };
}
