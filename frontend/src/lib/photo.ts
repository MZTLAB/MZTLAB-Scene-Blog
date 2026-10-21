import type { Photo, PhotoExifField } from '../types';

export type PhotoSpec = [label: string, value: string];

export const PHOTO_EXIF_FIELDS: PhotoExifField[] = [
  'camera',
  'lens',
  'focal_length',
  'aperture',
  'exposure',
  'iso',
  'taken_at',
  'dimensions',
];

export const PHOTO_EXIF_LABELS: Record<PhotoExifField, string> = {
  camera: '相机',
  lens: '镜头',
  focal_length: '焦距',
  aperture: '光圈',
  exposure: '快门',
  iso: 'ISO',
  taken_at: '拍摄时间',
  dimensions: '尺寸',
};

export function visibleExifFields(photo: Photo): Set<PhotoExifField> {
  const stored = photo.exif_fields ?? [];
  if (!stored.length) return new Set(PHOTO_EXIF_FIELDS);
  const allowed = new Set<string>(PHOTO_EXIF_FIELDS);
  return new Set(stored.filter((field): field is PhotoExifField => allowed.has(field)));
}

export function exifFieldVisible(photo: Photo, field: PhotoExifField): boolean {
  return visibleExifFields(photo).has(field);
}

/** Technical EXIF summary shared by grids, the album viewer and the lightbox. */
export function photoSpecs(photo: Photo): PhotoSpec[] {
  const exif = photo.exif;
  const visible = visibleExifFields(photo);
  const focal = photo.focal_length || exif?.focal_length || '';
  const focal35 = photo.focal_length_35mm || exif?.focal_length_35mm || null;
  const focalText = focal
    ? `${focal}${focal35 ? ` / ${focal35}mm eq` : ''}`
    : focal35
      ? `${focal35}mm eq`
      : '';
  const specs: PhotoSpec[] = [];
  if (visible.has('camera')) specs.push(['CAM', photo.camera || exif?.camera || '']);
  if (visible.has('lens')) specs.push(['LENS', photo.lens || exif?.lens || '']);
  if (visible.has('focal_length')) specs.push(['FOCAL', focalText]);
  if (visible.has('aperture')) specs.push(['APERTURE', photo.aperture || exif?.aperture || '']);
  if (visible.has('exposure')) specs.push(['SHUTTER', photo.exposure || exif?.exposure || '']);
  if (visible.has('iso')) specs.push(['ISO', photo.iso ? String(photo.iso) : '']);
  if (visible.has('taken_at')) {
    specs.push([
      'DATE',
      (photo.taken_at_raw || photo.taken_at || exif?.taken_at_raw || '').replace(
        /^(\d{4}):(\d{2}):(\d{2})/,
        '$1-$2-$3',
      ),
    ]);
  }
  if (visible.has('dimensions')) {
    specs.push(['SIZE', photo.width && photo.height ? `${photo.width} × ${photo.height}` : '']);
  }
  return specs.filter(([, value]) => Boolean(value));
}

/** One compact line for cards and album captions. */
export function photoMetaLine(photo: Photo): string {
  const visible = visibleExifFields(photo);
  const focal = photo.focal_length || photo.exif?.focal_length || '';
  return [
    visible.has('taken_at') ? photo.taken_at : '',
    visible.has('camera') ? photo.camera : '',
    visible.has('lens') ? photo.lens : '',
    visible.has('focal_length') ? focal : '',
    visible.has('aperture') ? photo.aperture : '',
    visible.has('exposure') ? photo.exposure : '',
    visible.has('iso') && photo.iso ? `ISO ${photo.iso}` : '',
    photo.location,
  ]
    .filter(Boolean)
    .join(' · ');
}

export function specsJson(photo: Photo): string {
  return JSON.stringify(photoSpecs(photo));
}
