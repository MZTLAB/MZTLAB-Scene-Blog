/**
 * Image delivery helpers for the Phase 3 artifact contract.
 *
 * The API hands every image a payload v2:
 *
 *   { id, width, height, s, l, f, ready, formats, base, direct_base,
 *     artifacts, placeholder, pipeline_version? }
 *
 * `artifacts` maps `scene -> width -> format -> token` (the backend may also
 * serialize it as a flat `[{scene,width,format,token}]` list; both are accepted
 * here). A derivative URL only exists when the matching token is present:
 *
 *   {direct_base || base}/{token}/{scene}/{width}.{ext}
 *
 * `ready: false` (or an empty artifact set) means the backend has not generated
 * derivatives yet: the caller renders the ORIGINAL file (`/media/{filename}`,
 * `photo.url`, `cover_image`, `hero_image`) instead of a `<picture>`.
 */
export type { ImageArtifact, ImageArtifactMap, ImageInfo } from '../types';
import type { ImageArtifact, ImageArtifactMap, ImageInfo } from '../types';

export type Scene = 'thumb' | 'tile' | 'card' | 'hero' | 'viewer' | 'prose' | 'full';

export type ImageFormat = 'avif' | 'webp' | 'jpeg';

const EXT: Record<ImageFormat, string> = { avif: 'avif', webp: 'webp', jpeg: 'jpg' };

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

/** Structural guard: the payload exists and has usable dimensions. */
export function isValidImage(image?: ImageInfo | null): image is ImageInfo {
  return Boolean(
    image &&
      typeof image.base === 'string' &&
      image.base.length > 0 &&
      Number(image.width) > 0 &&
      Number(image.height) > 0,
  );
}

/** True when the backend has generated (some) derivatives for this image. */
export function isReady(image?: ImageInfo | null): image is ImageInfo {
  if (!isValidImage(image)) return false;
  if (!image.ready) return false;
  return artifactCount(image.artifacts) > 0;
}

type TokenIndex = Map<string, Map<number, Map<string, string>>>;

function artifactCount(artifacts: ImageInfo['artifacts'] | undefined): number {
  if (!artifacts) return 0;
  if (Array.isArray(artifacts)) return artifacts.length;
  return Object.keys(artifacts).length;
}

function indexArtifacts(
  artifacts: ImageArtifactMap | ImageArtifact[] | undefined,
): TokenIndex {
  const index: TokenIndex = new Map();
  const add = (scene: string, width: number, format: string, token: string): void => {
    if (!scene || !format || !token || !Number.isFinite(width) || width <= 0) return;
    const widths = index.get(scene) ?? new Map<number, Map<string, string>>();
    index.set(scene, widths);
    const formats = widths.get(width) ?? new Map<string, string>();
    widths.set(width, formats);
    formats.set(format, token);
  };

  if (Array.isArray(artifacts)) {
    for (const item of artifacts) {
      if (!item || typeof item !== 'object') continue;
      add(
        String(item.scene ?? ''),
        Number(item.width ?? 0),
        String(item.format ?? ''),
        String(item.token ?? ''),
      );
    }
    return index;
  }
  if (artifacts && typeof artifacts === 'object') {
    for (const [scene, widths] of Object.entries(artifacts)) {
      if (!widths || typeof widths !== 'object') continue;
      for (const [width, formats] of Object.entries(widths)) {
        if (!formats || typeof formats !== 'object') continue;
        for (const [format, token] of Object.entries(formats)) {
          add(scene, Number(width), format, String(token));
        }
      }
    }
  }
  return index;
}

function indexFor(image: ImageInfo): TokenIndex {
  return indexArtifacts(image.artifacts);
}

function uniqueWidths(widths: Array<number | undefined>): number[] {
  const values = widths.filter((width): width is number => typeof width === 'number' && width > 0);
  return [...new Set(values)].sort((left, right) => left - right);
}

/** Candidate ladder widths advertised for one scene. */
export function sceneWidths(scene: Scene, image: ImageInfo): number[] {
  if (SMALL_SCENES.has(scene)) return uniqueWidths([image.s]);
  if (LARGE_SCENES.has(scene)) return uniqueWidths([image.l]);
  if (scene === 'prose') return uniqueWidths([image.s, image.l]);
  return uniqueWidths([image.f]);
}

/** Widths that actually have a token for this scene/format. */
export function artifactWidths(
  image: ImageInfo,
  scene: Scene,
  format: ImageFormat = 'jpeg',
): number[] {
  const widths = indexFor(image).get(scene);
  if (!widths) return [];
  return [...widths.entries()]
    .filter(([, formats]) => formats.has(format))
    .map(([width]) => width)
    .sort((left, right) => left - right);
}

/**
 * Build one derivative URL, or `''` when the backend has no artifact for this
 * scene/width/format (callers then fall back to the original file).
 */
export function derivativeUrl(
  image: ImageInfo,
  scene: Scene,
  width: number,
  format: ImageFormat = 'jpeg',
  preferDirect = false,
): string {
  if (!isValidImage(image)) return '';
  const token = indexFor(image).get(scene)?.get(width)?.get(format);
  if (!token) return '';
  const base = preferDirect && image.direct_base ? image.direct_base : image.base;
  return `${base}/${token}/${scene}/${width}.${EXT[format]}`;
}

/** Legacy name kept for call sites that predate `derivativeUrl`. */
export const variantUrl = derivativeUrl;

export function srcset(
  image: ImageInfo,
  scene: Scene,
  format: ImageFormat,
  preferDirect = true,
): string {
  return artifactWidths(image, scene, format)
    .map((width) => `${derivativeUrl(image, scene, width, format, preferDirect)} ${width}w`)
    .filter((entry) => !entry.startsWith(' '))
    .join(', ');
}

/** Does a `<picture>` source set exist for this scene/format? */
export function hasSrcset(image: ImageInfo, scene: Scene, format: ImageFormat): boolean {
  return artifactWidths(image, scene, format).length > 0;
}

/**
 * Plain-JPEG fallback loaded by `<img>`: always same-origin proxy, largest
 * available JPEG token. Returns `''` when no JPEG artifact exists.
 */
export function fallbackUrl(image: ImageInfo, scene: Scene): string {
  const widths = artifactWidths(image, scene, 'jpeg');
  const width = widths[widths.length - 1];
  if (!width) return '';
  return derivativeUrl(image, scene, width, 'jpeg', false);
}

/** Best available URL for preload/warmup (largest width, AVIF > WebP > JPEG). */
export function preferredUrl(image: ImageInfo, scene: Scene, preferDirect = true): string {
  for (const format of ['avif', 'webp', 'jpeg'] as const) {
    const widths = artifactWidths(image, scene, format);
    const width = widths[widths.length - 1];
    if (width) return derivativeUrl(image, scene, width, format, preferDirect);
  }
  return '';
}

/** Small JPEG used by admin thumbnails; falls back to the original URL. */
export function thumbUrl(image: ImageInfo | null | undefined, src: string): string {
  if (!isReady(image)) return src;
  return fallbackUrl(image, 'thumb') || src;
}

/** Sprite-ish background for the hero/OG image (CSS `image-set`). */
export function imageSet(image: ImageInfo, scene: Scene, formats: string[]): string {
  if (!isReady(image)) return 'none';
  const widths = artifactWidths(image, scene, 'jpeg');
  const width = widths[widths.length - 1];
  if (!width) return 'none';
  const sets: string[] = [];
  for (const format of ['avif', 'webp'] as const) {
    if (!formats.includes(format)) continue;
    if (!artifactWidths(image, scene, format).length) continue;
    sets.push(`url("${derivativeUrl(image, scene, width, format, true)}") type("image/${format}")`);
  }
  sets.push(`url("${derivativeUrl(image, scene, width, 'jpeg', false)}") type("image/jpeg")`);
  return `image-set(${sets.join(', ')})`;
}
