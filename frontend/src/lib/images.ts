/**
 * Image delivery helpers.
 *
 * The API hands every image a compact metadata block:
 *
 *   { width, height, s, l, f, formats, base, direct }
 *
 * `s` / `l` are the small (grid) and large (detail) ladder widths, `f` is the
 * full-resolution width. `base` is a same-origin proxy base; `direct` is an
 * absolute object-storage/CDN base that is only present once every variant has
 * been generated. The fallback `<img>` always uses the proxy so legacy
 * browsers and not-yet-generated variants still work.
 */
export interface ImageInfo {
  width: number;
  height: number;
  s: number;
  l: number;
  f: number;
  formats: string[];
  base: string;
  direct: string | null;
}

export type Scene = 'thumb' | 'tile' | 'card' | 'hero' | 'viewer' | 'prose' | 'full';

const EXT: Record<string, string> = { avif: 'avif', webp: 'webp', jpeg: 'jpg' };

/** `sizes` per scene, mirroring the CSS layout of each component. */
export const SCENE_SIZES: Record<Scene, string> = {
  thumb: '96px',
  tile: '(max-width: 720px) 50vw, 33vw',
  card: '(max-width: 720px) 100vw, 50vw',
  hero: '100vw',
  viewer: '(max-width: 900px) 100vw, 80vw',
  prose: '(max-width: 820px) 100vw, 820px',
  full: '100vw',
};

const SMALL_SCENES = new Set<Scene>(['thumb', 'tile', 'card']);
const LARGE_SCENES = new Set<Scene>(['hero', 'viewer']);

export function isValidImage(image?: ImageInfo | null): image is ImageInfo {
  return Boolean(image && image.base && image.width > 0 && image.s > 0);
}

function uniqueWidths(widths: Array<number | undefined>): number[] {
  const values = widths.filter((width): width is number => typeof width === 'number' && width > 0);
  return [...new Set(values)].sort((left, right) => left - right);
}

/** Widths advertised for one scene. */
export function sceneWidths(scene: Scene, image: ImageInfo): number[] {
  if (SMALL_SCENES.has(scene)) return uniqueWidths([image.s]);
  if (LARGE_SCENES.has(scene)) return uniqueWidths([image.l]);
  if (scene === 'prose') return uniqueWidths([image.s, image.l]);
  return uniqueWidths([image.f]);
}

export function variantUrl(
  image: ImageInfo,
  scene: Scene,
  width: number,
  format = 'jpeg',
  preferDirect = false,
): string {
  const base = preferDirect && image.direct ? image.direct : image.base;
  return `${base}/${scene}/${width}.${EXT[format] ?? 'jpg'}`;
}

export function srcset(
  image: ImageInfo,
  scene: Scene,
  format: string,
  preferDirect = true,
): string {
  return sceneWidths(scene, image)
    .map((width) => `${variantUrl(image, scene, width, format, preferDirect)} ${width}w`)
    .join(', ');
}

/** The plain-JPEG fallback loaded by `<img>` (always same-origin proxy). */
export function fallbackUrl(image: ImageInfo, scene: Scene): string {
  const widths = sceneWidths(scene, image);
  const width = widths[widths.length - 1] ?? image.s;
  return variantUrl(image, scene, width, 'jpeg', false);
}

/** Small JPEG used by admin thumbnails; falls back to the original URL. */
export function thumbUrl(image: ImageInfo | null | undefined, src: string): string {
  if (!isValidImage(image)) return src;
  return variantUrl(image, 'thumb', image.s, 'jpeg', false);
}

/** Sprite-ish background for the hero/OG image (CSS `image-set`). */
export function imageSet(image: ImageInfo, scene: Scene, formats: string[]): string {
  const sets = formats
    .filter((format) => format === 'avif' || format === 'webp')
    .map((format) => `url("${variantUrl(image, scene, sceneWidths(scene, image)[0], format, true)}") type("image/${format}")`);
  sets.push(`url("${fallbackUrl(image, scene)}") type("image/jpeg")`);
  return `image-set(${sets.join(', ')})`;
}
