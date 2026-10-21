import type { CopySettings, PublicSettings } from '../types';

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
