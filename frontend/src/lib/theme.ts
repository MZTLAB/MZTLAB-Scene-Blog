/**
 * Theme token normalization (P-M2 / SSG reserve).
 *
 * The backend settings are validated, but layout code still needs one place
 * that clamps numeric tokens and rejects unknown enum values, so every layout
 * renders exactly the same `data-*` attributes and CSS variables. This module
 * is pure (no request context), which keeps it usable from a future static
 * build.
 */
import type { AppearanceSettings, SiteSettings } from '../types';

export const PALETTES = ['scene', 'stone', 'sand', 'night'] as const;
export const COLOR_MODES = ['light', 'dark', 'system'] as const;
export const FONT_PAIRS = ['sans', 'serif', 'mono'] as const;
export const HERO_STYLES = ['split', 'minimal', 'image'] as const;

export type Palette = (typeof PALETTES)[number];
export type ColorMode = (typeof COLOR_MODES)[number];
export type FontPair = (typeof FONT_PAIRS)[number];
export type HeroStyle = (typeof HERO_STYLES)[number];

export interface ThemeTokens {
  accent: string;
  width: number;
  radius: number;
  columns: number;
  colorMode: ColorMode;
  palette: Palette;
  fontPair: FontPair;
}

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

/**
 * Normalize the appearance tokens once instead of repeating the same clamps in
 * every layout. The values come from the validated backend settings, so the
 * fallbacks here only protect CSS from an unknown enum — they are not site
 * content defaults.
 */
export function normalizeTheme(
  appearance: AppearanceSettings,
  site: SiteSettings,
): ThemeTokens {
  const colorMode = COLOR_MODES.includes(appearance.color_mode as ColorMode)
    ? (appearance.color_mode as ColorMode)
    : 'light';
  const palette = PALETTES.includes(appearance.theme as Palette)
    ? (appearance.theme as Palette)
    : 'scene';
  const fontPair = FONT_PAIRS.includes(appearance.font_pair as FontPair)
    ? (appearance.font_pair as FontPair)
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
