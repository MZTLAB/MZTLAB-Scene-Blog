import { escapeHtml } from './admin-client';
import type { ExifInfo } from '../types';

const row = (label: string, value: unknown): string => {
  const text = value === null || value === undefined || value === '' ? '—' : String(value);
  return `<div class="exif-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(text)}</strong></div>`;
};

const gpsText = (exif: ExifInfo): string => {
  if (!exif.gps) return '';
  const { latitude, longitude, altitude } = exif.gps;
  const base = `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
  return altitude === undefined || altitude === null ? base : `${base} · ${altitude}m`;
};

/** Rows shown in the EXIF detail dialog, in reading order. */
export function exifRows(exif: ExifInfo): Array<[string, string]> {
  return [
    ['相机', exif.camera || ''],
    ['镜头', exif.lens || ''],
    ['拍摄时间', exif.taken_at_raw || exif.taken_at || ''],
    ['光圈', exif.aperture || ''],
    ['快门', exif.exposure || ''],
    ['ISO', exif.iso ? String(exif.iso) : ''],
    ['焦距', exif.focal_length || ''],
    ['等效焦距', exif.focal_length_35mm ? `${exif.focal_length_35mm}mm` : ''],
    ['软件', exif.software || ''],
    ['作者', exif.artist || ''],
    ['版权', exif.copyright || ''],
    ['位置', gpsText(exif)],
    ['方向', exif.orientation ? String(exif.orientation) : ''],
  ].filter(([, value]) => value) as Array<[string, string]>;
}

export function showExifDialog(exif: ExifInfo | null, title = 'EXIF 信息'): void {
  document.querySelector('[data-exif-dialog]')?.remove();
  const rows = exif ? exifRows(exif) : [];
  const raw = exif?.raw && Object.keys(exif.raw).length
    ? `<details class="exif-raw"><summary>原始标签（${Object.keys(exif.raw).length}）</summary><pre>${escapeHtml(
        JSON.stringify(exif.raw, null, 2),
      )}</pre></details>`
    : '';

  const overlay = document.createElement('div');
  overlay.className = 'modal-backdrop is-open';
  overlay.dataset.exifDialog = '1';
  overlay.innerHTML = `<div class="modal exif-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
    <div class="modal__head">
      <h3>${escapeHtml(title)}</h3>
      <button type="button" data-close-exif aria-label="关闭">×</button>
    </div>
    <div class="modal__body">
      ${
        rows.length
          ? `<div class="exif-grid">${rows.map(([label, value]) => row(label, value)).join('')}</div>`
          : '<p class="exif-empty">这张图片没有可读取的 EXIF 信息。上传时保留相机原始文件，或确认导出时没有移除元数据。</p>'
      }
      ${raw}
    </div>
    <div class="modal__foot">
      <span class="number-label">${exif ? 'CAMERA METADATA' : 'NO METADATA'}</span>
      <button class="a-btn" type="button" data-close-exif>关闭</button>
    </div>
  </div>`;

  document.body.appendChild(overlay);
  const previousOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  const close = () => {
    overlay.remove();
    document.body.style.overflow = previousOverflow;
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') close();
  };
  overlay.addEventListener('click', (event) => {
    const target = event.target as HTMLElement;
    if (target === overlay || target.closest('[data-close-exif]')) close();
  });
  document.addEventListener('keydown', onKey);
}
