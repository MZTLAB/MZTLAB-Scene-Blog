/**
 * Per-image AVIF quality dialog.
 *
 * Behaviour mirrors the EXIF editor: a tiny「画质」button on a media card or
 * gallery photo row opens a modal instead of showing a flat input everywhere.
 * Any element with `data-quality-edit="<media id>"` opens it.
 */
import { api } from './api';
import { errorMessage, toast } from './admin-client';
import type { MediaItem } from '../types';

export interface QualityDialogOptions {
  /** Called after the quality was saved (reload the list). */
  onSaved?: () => void;
}

export interface QualityDialogHandle {
  open: (mediaId: number) => Promise<void>;
}

export function initQualityDialog(
  options: QualityDialogOptions = {},
): QualityDialogHandle | null {
  const root = document.querySelector<HTMLElement>('[data-quality-editor]');
  if (!root) return null;

  const form = root.querySelector<HTMLFormElement>('[data-quality-form]');
  const title = root.querySelector<HTMLElement>('[data-quality-title]');
  const output = root.querySelector<HTMLElement>('[data-quality-output]');
  const range = root.querySelector<HTMLInputElement>('[data-quality-range]');
  const number = root.querySelector<HTMLInputElement>('[data-quality-number]');
  const hint = root.querySelector<HTMLElement>('[data-quality-hint]');
  const regenerate = root.querySelector<HTMLButtonElement>('[data-quality-regenerate]');

  let current: MediaItem | null = null;
  let saving = false;

  const sceneHint = (quality: number) => {
    if (quality === 0) return '当前继承全局场景质量。';
    if (quality <= 40) return '偏省流量，适合缩略图 / 背景图。';
    if (quality <= 60) return '日常推荐区间，细节与体积平衡。';
    if (quality <= 80) return '偏高画质，适合首屏或大幅输出。';
    return '接近无损，文件会明显变大。';
  };

  const setValue = (value: number) => {
    const quality = Math.max(0, Math.min(100, Math.round(Number.isFinite(value) ? value : 0)));
    if (range) range.value = String(quality);
    if (number) number.value = String(quality);
    if (output) output.textContent = quality === 0 ? 'AUTO' : String(quality);
    if (hint) hint.textContent = sceneHint(quality);
  };

  const close = () => {
    root.classList.remove('is-open');
    document.body.style.overflow = '';
    current = null;
  };

  const open = async (mediaId: number) => {
    if (!mediaId) return;
    try {
      const item = await api<MediaItem>(`/api/admin/media/${mediaId}`);
      current = item;
      if (title) title.textContent = `图片画质 · ${item.original_name || item.filename}`;
      setValue(Number(item.avif_quality) || 0);
      root.classList.add('is-open');
      document.body.style.overflow = 'hidden';
      range?.focus();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  range?.addEventListener('input', () => setValue(Number(range.value)));
  number?.addEventListener('input', () => setValue(Number(number.value)));

  root.querySelectorAll<HTMLElement>('[data-close-quality]').forEach((button) => {
    button.addEventListener('click', () => close());
  });
  root.addEventListener('click', (event) => {
    if (event.target === root) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && root.classList.contains('is-open')) close();
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!current || saving) return;
    saving = true;
    const mediaId = current.id;
    const quality = Math.max(0, Math.min(100, Number(number?.value) || 0));
    try {
      // `alt` is required by the endpoint; send the current value so a quality
      // edit never clears the alternative text.
      await api(`/api/admin/media/${mediaId}`, {
        method: 'PUT',
        body: { alt: current.alt, avif_quality: quality },
      });
      toast(
        quality === 0 ? '已恢复为继承场景质量，正在后台重新生成' : `画质已设为 ${quality}，正在后台重新生成`,
        'success',
      );
      close();
      options.onSaved?.();
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      saving = false;
    }
  });

  regenerate?.addEventListener('click', async () => {
    if (!current) return;
    try {
      await api(`/api/admin/media/${current.id}/optimize`, { method: 'POST' });
      toast('已开始重新生成派生图', 'success');
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });

  // Delegation keeps working after list re-renders (media grid / photo rows).
  document.addEventListener('click', (event) => {
    const trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>(
      '[data-quality-edit]',
    );
    if (!trigger) return;
    event.preventDefault();
    void open(Number(trigger.dataset.qualityEdit) || 0);
  });

  return { open };
}
