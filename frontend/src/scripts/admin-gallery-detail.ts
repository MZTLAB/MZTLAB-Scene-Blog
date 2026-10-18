import { api } from '../lib/api';
import { debounce, errorMessage, escapeHtml, toast } from '../lib/admin-client';
import { PHOTO_EXIF_FIELDS, PHOTO_EXIF_LABELS } from '../lib/photo';
import type { Gallery, MediaItem, Paginated, Photo } from '../types';

const root = document.querySelector<HTMLElement>('[data-gallery-detail]');

if (root) {
  const id = Number(root.dataset.id);
  const rowsHost = root.querySelector<HTMLElement>('[data-photo-rows]');
  const picker = root.querySelector<HTMLElement>('[data-picker]');
  const pickerGrid = root.querySelector<HTMLElement>('[data-picker-grid]');
  const pickerCount = root.querySelector<HTMLElement>('[data-picker-count]');
  const pickerSearch = root.querySelector<HTMLInputElement>('[data-picker-search]');
  const confirmButton = root.querySelector<HTMLButtonElement>('[data-confirm-picker]');
  const coverSelect = root.querySelector<HTMLSelectElement>('[data-field="cover"]');
  const saveButton = root.querySelector<HTMLButtonElement>('[data-save]');

  let gallery: Gallery | null = null;
  const selected = new Set<number>();
  let mediaItems: MediaItem[] = [];

  const field = <T extends HTMLElement>(name: string) =>
    root.querySelector<T>(`[data-field="${name}"]`);

  const number = (value: number | null | undefined) => String(value ?? 0);

  const hydrate = (value: Gallery) => {
    gallery = value;
    (field<HTMLInputElement>('title') as HTMLInputElement).value = value.title;
    (field<HTMLInputElement>('slug') as HTMLInputElement).value = value.slug;
    (field<HTMLTextAreaElement>('description') as HTMLTextAreaElement).value = value.description;
    (field<HTMLSelectElement>('status') as HTMLSelectElement).value = value.status;
    (field<HTMLInputElement>('featured') as HTMLInputElement).checked = value.featured;
    root.querySelector<HTMLElement>('[data-title]')!.textContent = value.title;
    root.querySelector<HTMLElement>('[data-photo-count]')!.textContent = String(value.photo_count);
    root.querySelector<HTMLElement>('[data-gallery-status]')!.textContent =
      value.status === 'published' ? '已发布' : '草稿';
    const photos = value.photos || [];
    if (coverSelect) {
      coverSelect.innerHTML = [
        '<option value="">自动（第一张）</option>',
        ...photos.map(
          (photo) =>
            `<option value="${photo.id}" ${value.cover_photo_id === photo.id ? 'selected' : ''}>${escapeHtml(
              photo.title || `照片 #${photo.id}`,
            )}</option>`,
        ),
      ].join('');
    }
    const overviewPhotos = root.querySelector<HTMLElement>('[data-overview-photos]');
    const overviewPublished = root.querySelector<HTMLElement>('[data-overview-published]');
    const overviewViews = root.querySelector<HTMLElement>('[data-overview-views]');
    const overviewUpdated = root.querySelector<HTMLElement>('[data-overview-updated]');
    if (overviewPhotos) overviewPhotos.textContent = number(photos.length);
    if (overviewPublished)
      overviewPublished.textContent = number(photos.filter((photo) => photo.status === 'published').length);
    if (overviewViews) overviewViews.textContent = number(value.view_count);
    if (overviewUpdated) overviewUpdated.textContent = value.updated_at.slice(0, 10);
    renderPhotos();
  };

  const renderPhotos = () => {
    if (!rowsHost || !gallery) return;
    const photos = gallery.photos || [];
    if (!photos.length) {
      rowsHost.innerHTML = `<div class="admin-empty" style="padding:34px 18px">
        <p>这本相册还没有照片。先从媒体库挑选几张。</p>
        <button class="a-btn a-btn--sm" type="button" data-empty-add>从媒体库添加</button>
      </div>`;
      rowsHost.querySelector('[data-empty-add]')?.addEventListener('click', () => openPicker());
      return;
    }

    rowsHost.innerHTML = photos
      .map(
        (photo, index) => `<div class="photo-row" data-photo-row="${photo.id}">
          <button class="photo-row__thumb" type="button" data-preview="${escapeHtml(photo.url)}" title="查看大图">
            <img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.alt)}" loading="lazy" />
          </button>
          <div class="photo-row__fields">
            <input data-photo-field="title" type="text" maxlength="140" value="${escapeHtml(photo.title)}" placeholder="标题" />
            <input data-photo-field="caption" type="text" maxlength="600" value="${escapeHtml(photo.caption)}" placeholder="说明 / 旁注" />
            <span style="font-family:var(--font-mono);font-size:8px;letter-spacing:.06em;color:var(--accent);text-transform:uppercase">${escapeHtml(
              [photo.focal_length, photo.aperture, photo.exposure, photo.iso ? `ISO ${photo.iso}` : '']
                .filter(Boolean)
                .join(' / ') || 'NO EXIF',
            )}</span>
            <details class="photo-exif-panel">
              <summary>显示 EXIF · ${(photo.exif_fields || PHOTO_EXIF_FIELDS).length}/${PHOTO_EXIF_FIELDS.length}</summary>
              <div class="photo-exif-panel__body">
                ${PHOTO_EXIF_FIELDS.map((field) => {
                  const checked = (photo.exif_fields || PHOTO_EXIF_FIELDS).includes(field);
                  return `<label><input type="checkbox" data-exif-field="${field}" ${checked ? 'checked' : ''} /> ${PHOTO_EXIF_LABELS[field]}</label>`;
                }).join('')}
              </div>
            </details>
          </div>
          <div class="photo-row__side">
            <input data-photo-field="location" type="text" maxlength="120" value="${escapeHtml(photo.location)}" placeholder="地点" />
          </div>
          <div class="photo-row__actions">
            ${
              photo.media_id
                ? `<a class="icon-action icon-action--text" href="/admin/media?edit=${photo.media_id}" target="_blank" rel="noopener" title="在媒体库编辑 EXIF" aria-label="在媒体库编辑 EXIF">EXIF</a>`
                : ''
            }
            <button class="icon-action" type="button" data-move="-1" ${index === 0 ? 'disabled' : ''} title="上移" aria-label="上移">↑</button>
            <button class="icon-action" type="button" data-move="1" ${index === photos.length - 1 ? 'disabled' : ''} title="下移" aria-label="下移">↓</button>
            <button class="icon-action" type="button" data-featured="${photo.id}" title="${photo.featured ? '取消封面候选' : '设为精选'}" aria-label="切换精选" style="${photo.featured ? 'color:var(--accent);border-color:var(--accent)' : ''}">★</button>
            <button class="icon-action" type="button" data-toggle-status="${photo.id}" title="切换发布状态" aria-label="切换发布状态" style="${photo.status === 'published' ? '' : 'opacity:.45'}">●</button>
            <button class="icon-action icon-action--danger" type="button" data-remove="${photo.id}" title="从相册移除" aria-label="移除照片">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6"/></svg>
            </button>
          </div>
        </div>`,
      )
      .join('');

    bindRows();
  };

  const bindRows = () => {
    rowsHost?.querySelectorAll<HTMLElement>('[data-preview]').forEach((button) => {
      button.addEventListener('click', () => window.open(button.dataset.preview, '_blank', 'noopener'));
    });

    rowsHost?.querySelectorAll<HTMLElement>('[data-photo-row]').forEach((row) => {
      const photoId = Number(row.dataset.photoRow);
      const savePhoto = debounce(async () => {
        const photo = gallery?.photos?.find((item) => item.id === photoId);
        if (!photo) return;
        const value = (name: string) =>
          (row.querySelector<HTMLInputElement>(`[data-photo-field="${name}"]`)?.value || '').trim();
        try {
          await api<Photo>(`/api/admin/photos/${photoId}`, {
            method: 'PUT',
            body: {
              gallery_id: id,
              title: value('title'),
              caption: value('caption'),
              location: value('location'),
              camera: photo.camera,
              lens: photo.lens,
              taken_at: photo.taken_at,
              featured: photo.featured,
              status: photo.status,
            },
          });
          toast('照片信息已保存', 'success');
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      }, 450);

      row.querySelectorAll<HTMLInputElement>('[data-photo-field]').forEach((input) => {
        input.addEventListener('input', savePhoto);
      });

      row.querySelectorAll<HTMLButtonElement>('[data-move]').forEach((button) => {
        button.addEventListener('click', () => movePhoto(photoId, Number(button.dataset.move)));
      });

      row.querySelectorAll<HTMLInputElement>('[data-exif-field]').forEach((input) => {
        input.addEventListener('change', async () => {
          const selected = Array.from(
            row.querySelectorAll<HTMLInputElement>('[data-exif-field]:checked'),
          ).map((item) => item.dataset.exifField || '');
          await patchPhoto(photoId, { exif_fields: selected as Photo['exif_fields'] }, false);
          const summary = row.querySelector<HTMLElement>('.photo-exif-panel summary');
          if (summary) {
            summary.textContent = `显示 EXIF · ${selected.length}/${PHOTO_EXIF_FIELDS.length}`;
          }
        });
      });

      row.querySelector<HTMLButtonElement>('[data-featured]')?.addEventListener('click', async () => {
        const photo = gallery?.photos?.find((item) => item.id === photoId);
        if (!photo) return;
        await patchPhoto(photoId, { featured: !photo.featured });
      });

      row.querySelector<HTMLButtonElement>('[data-toggle-status]')?.addEventListener('click', async () => {
        const photo = gallery?.photos?.find((item) => item.id === photoId);
        if (!photo) return;
        await patchPhoto(photoId, {
          status: photo.status === 'published' ? 'draft' : 'published',
        });
      });

      row.querySelector<HTMLButtonElement>('[data-remove]')?.addEventListener('click', async () => {
        if (!window.confirm('从相册中移除这张照片？原图仍保留在媒体库。')) return;
        try {
          await api(`/api/admin/photos/${photoId}`, { method: 'DELETE' });
          toast('照片已移除', 'success');
          await reload();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
  };

  const patchPhoto = async (
    photoId: number,
    patch: Partial<Photo>,
    reloadAfter = true,
  ) => {
    const photo = gallery?.photos?.find((item) => item.id === photoId);
    if (!photo) return;
    try {
      await api(`/api/admin/photos/${photoId}`, {
        method: 'PUT',
        body: {
          gallery_id: id,
          title: photo.title,
          caption: photo.caption,
          location: photo.location,
          camera: photo.camera,
          lens: photo.lens,
          taken_at: photo.taken_at,
          featured: photo.featured,
          status: photo.status,
          ...patch,
        },
      });
      if (reloadAfter) await reload();
      else Object.assign(photo, patch);
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const movePhoto = async (photoId: number, delta: number) => {
    const photos = gallery?.photos || [];
    const index = photos.findIndex((item) => item.id === photoId);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= photos.length) return;
    const order = photos.map((item) => item.id);
    [order[index], order[target]] = [order[target], order[index]];
    try {
      await api(`/api/admin/galleries/${id}/reorder`, { method: 'POST', body: { ids: order } });
      await reload();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const reload = async () => {
    gallery = await api<Gallery>(`/api/admin/galleries/${id}`);
    hydrate(gallery);
  };

  const saveGallery = async () => {
    if (saveButton) saveButton.disabled = true;
    try {
      const cover = coverSelect?.value;
      const updated = await api<Gallery>(`/api/admin/galleries/${id}`, {
        method: 'PUT',
        body: {
          title: (field<HTMLInputElement>('title') as HTMLInputElement).value.trim(),
          slug: (field<HTMLInputElement>('slug') as HTMLInputElement).value.trim(),
          description: (field<HTMLTextAreaElement>('description') as HTMLTextAreaElement).value.trim(),
          status: (field<HTMLSelectElement>('status') as HTMLSelectElement).value,
          featured: (field<HTMLInputElement>('featured') as HTMLInputElement).checked,
          cover_photo_id: cover ? Number(cover) : null,
        },
      });
      hydrate(updated);
      toast('相册设置已保存', 'success');
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      if (saveButton) saveButton.disabled = false;
    }
  };

  const openPicker = () => {
    if (!picker) return;
    picker.classList.add('is-open');
    selected.clear();
    updatePickerCount();
    loadMedia('');
    pickerSearch?.focus();
  };

  const closePicker = () => picker?.classList.remove('is-open');

  const updatePickerCount = () => {
    if (pickerCount) pickerCount.textContent = `已选 ${selected.size} 张`;
    if (confirmButton) confirmButton.disabled = selected.size === 0;
  };

  const renderPicker = () => {
    if (!pickerGrid) return;
    if (!mediaItems.length) {
      pickerGrid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>媒体库还没有可用的图片。<a href="/admin/media">先上传</a>。</p></div>`;
      return;
    }
    pickerGrid.innerHTML = mediaItems
      .map(
        (item) => `<button class="picker-tile ${selected.has(item.id) ? 'is-selected' : ''}" type="button" data-pick="${item.id}" title="${escapeHtml(item.original_name)}">
          <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.alt)}" loading="lazy" />
          <span>${escapeHtml(item.original_name)}</span>
        </button>`,
      )
      .join('');
    pickerGrid.querySelectorAll<HTMLButtonElement>('[data-pick]').forEach((button) => {
      button.addEventListener('click', () => {
        const mediaId = Number(button.dataset.pick);
        if (selected.has(mediaId)) selected.delete(mediaId);
        else selected.add(mediaId);
        button.classList.toggle('is-selected', selected.has(mediaId));
        updatePickerCount();
      });
    });
  };

  const loadMedia = async (q: string) => {
    if (!pickerGrid) return;
    pickerGrid.innerHTML =
      '<div class="admin-loading" style="grid-column:1/-1"><div class="skeleton" style="height:100px"></div></div>';
    try {
      const data = await api<Paginated<MediaItem>>(
        `/api/admin/media?per_page=100&kind=image${q ? `&q=${encodeURIComponent(q)}` : ''}`,
      );
      mediaItems = data.items;
      renderPicker();
    } catch (error) {
      pickerGrid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>${escapeHtml(errorMessage(error))}</p></div>`;
    }
  };

  const confirmPicker = async () => {
    if (!selected.size) return;
    if (confirmButton) confirmButton.disabled = true;
    try {
      await api(`/api/admin/galleries/${id}/photos`, {
        method: 'POST',
        body: { media_ids: [...selected], status: 'published' },
      });
      toast(`已添加 ${selected.size} 张照片`, 'success');
      closePicker();
      await reload();
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      updatePickerCount();
    }
  };

  saveButton?.addEventListener('click', saveGallery);
  root.querySelectorAll<HTMLElement>('[data-add-photos]').forEach((button) =>
    button.addEventListener('click', openPicker),
  );
  root.querySelectorAll<HTMLElement>('[data-close-picker]').forEach((button) =>
    button.addEventListener('click', closePicker),
  );
  confirmButton?.addEventListener('click', confirmPicker);
  pickerSearch?.addEventListener(
    'input',
    debounce(() => loadMedia(pickerSearch.value.trim()), 320),
  );
  picker?.addEventListener('click', (event) => {
    if (event.target === picker) closePicker();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closePicker();
  });

  root.querySelector<HTMLElement>('[data-delete-gallery]')?.addEventListener('click', async () => {
    if (!window.confirm('删除这本相册？相册内的照片记录会移除，原图仍保留在媒体库。')) return;
    try {
      await api(`/api/admin/galleries/${id}`, { method: 'DELETE' });
      toast('相册已删除', 'success');
      window.location.href = '/admin/galleries';
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });

  reload().catch((error) => toast(errorMessage(error), 'error'));
}
