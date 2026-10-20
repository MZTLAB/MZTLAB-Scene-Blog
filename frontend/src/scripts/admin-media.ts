import { api, qs } from '../lib/api';
import { debounce, errorMessage, escapeHtml, formatBytes, toast } from '../lib/admin-client';
import { thumbUrl } from '../lib/images';
import { initQualityDialog } from '../lib/quality-dialog';
import type { MediaItem, Paginated } from '../types';

const root = document.querySelector<HTMLElement>('[data-media-page]');
if (root) {
  // The upload policy is rendered by the server from 设置 → 上传与媒体, so the
  // client checks mirror the current configuration instead of a hard-coded
  // 12MB / format list.
  const maxMb = Math.max(1, Math.min(200, Number(root.dataset.uploadMaxMb) || 12));
  const maxBytes = maxMb * 1024 * 1024;
  const parseFormats = (value: string | undefined) =>
    new Set(
      String(value || '')
        .replace(/;/g, ',')
        .split(',')
        .map((token) => token.trim().toLowerCase().replace(/^\./, ''))
        .filter(Boolean),
    );
  const imageFormats = parseFormats(root.dataset.uploadImageFormats);
  const audioFormats = parseFormats(root.dataset.uploadAudioFormats);
  const fileFormats = parseFormats(root.dataset.uploadFileFormats);
  const unrestricted = root.dataset.uploadUnrestricted === '1';
  const formatLabels = [
    ...Array.from(imageFormats, (format) => format.toUpperCase()),
    ...Array.from(audioFormats, (format) => format.toUpperCase()),
    ...Array.from(fileFormats, (format) => format.toUpperCase()),
  ].join(' / ');
  const extensionOf = (name: string): string => {
    const match = /\.([a-z0-9]+)$/i.exec(name);
    return match ? match[1].toLowerCase() : '';
  };
  const formatAllowed = (file: File): boolean => {
    const extension = extensionOf(file.name);
    const normalized = extension === 'jpeg' ? 'jpg' : extension;
    if (
      imageFormats.has(normalized) ||
      audioFormats.has(normalized) ||
      fileFormats.has(normalized)
    ) {
      return true;
    }
    // Files without a usable extension but with an image/audio MIME are left
    // to the server's content validation (Pillow / magic bytes).
    return !extension && (file.type.startsWith('image/') || file.type.startsWith('audio/'));
  };

  const grid = root.querySelector<HTMLElement>('[data-media-grid]');
  const pagination = root.querySelector<HTMLElement>('[data-media-pagination]');
  const input = root.querySelector<HTMLInputElement>('[data-upload-input]');
  const zone = root.querySelector<HTMLElement>('[data-upload-zone]');
  const status = root.querySelector<HTMLElement>('[data-upload-status]');
  const search = root.querySelector<HTMLInputElement>('[data-media-search]');
  const kindTabs = root.querySelector<HTMLElement>('[data-media-kinds]');
  const exifDialog = root.querySelector<HTMLElement>('[data-exif-editor]');
  const exifForm = root.querySelector<HTMLFormElement>('[data-exif-form]');
  const exifTitle = root.querySelector<HTMLElement>('[data-exif-editor-title]');
  const exifFields = {
    camera: root.querySelector<HTMLInputElement>('[data-exif-camera]'),
    lens: root.querySelector<HTMLInputElement>('[data-exif-lens]'),
    taken_at: root.querySelector<HTMLInputElement>('[data-exif-taken]'),
    aperture: root.querySelector<HTMLInputElement>('[data-exif-aperture]'),
    exposure: root.querySelector<HTMLInputElement>('[data-exif-exposure]'),
    iso: root.querySelector<HTMLInputElement>('[data-exif-iso]'),
    focal_length: root.querySelector<HTMLInputElement>('[data-exif-focal]'),
    focal_length_35mm: root.querySelector<HTMLInputElement>('[data-exif-focal35]'),
  };
  const state = { page: 1, q: '', kind: '' };
  const editId = Number(new URLSearchParams(window.location.search).get('edit') || 0);
  let mediaItems: MediaItem[] = [];
  let editingMedia: MediaItem | null = null;
  let autoOpened = false;

  const closeExifEditor = () => {
    exifDialog?.classList.remove('is-open');
    document.body.style.overflow = '';
    editingMedia = null;
  };

  const openExifEditor = (item: MediaItem) => {
    if (!exifDialog || item.kind === 'audio') return;
    editingMedia = item;
    if (exifTitle) exifTitle.textContent = `编辑 EXIF · ${item.original_name}`;
    (Object.keys(exifFields) as Array<keyof typeof exifFields>).forEach((key) => {
      const field = exifFields[key];
      if (!field) return;
      if (key === 'iso' || key === 'focal_length_35mm') {
        field.value = item.exif?.[key] ? String(item.exif[key]) : '';
      } else {
        field.value = String(item.exif?.[key] || '');
      }
      const locked = field.value.trim() !== '';
      field.readOnly = locked;
      field.classList.toggle('is-locked', locked);
      field.title = locked ? '已有 EXIF，不可修改' : '';
    });
    exifDialog.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    exifFields.camera?.focus();
  };

  exifDialog?.querySelectorAll<HTMLElement>('[data-close-exif-editor]').forEach((button) => {
    button.addEventListener('click', closeExifEditor);
  });
  exifDialog?.addEventListener('click', (event) => {
    if (event.target === exifDialog) closeExifEditor();
  });

  exifForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!editingMedia) return;
    const numberOrNull = (field: HTMLInputElement | null) => {
      const value = Number(field?.value || '');
      return field?.value.trim() && Number.isFinite(value) ? value : null;
    };
    try {
      await api(`/api/admin/media/${editingMedia.id}/exif`, {
        method: 'PUT',
        body: {
          camera: exifFields.camera?.value || '',
          lens: exifFields.lens?.value || '',
          taken_at: exifFields.taken_at?.value || '',
          aperture: exifFields.aperture?.value || '',
          exposure: exifFields.exposure?.value || '',
          iso: numberOrNull(exifFields.iso),
          focal_length: exifFields.focal_length?.value || '',
          focal_length_35mm: numberOrNull(exifFields.focal_length_35mm),
        },
      });
      closeExifEditor();
      toast('EXIF 已保存', 'success');
      load();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });

  const load = async () => {
    if (!grid) return;
    grid.innerHTML = `<div class="admin-loading" style="grid-column:1/-1"><div class="skeleton" style="height:110px"></div><div class="skeleton" style="height:110px"></div></div>`;
    try {
      const data = await api<Paginated<MediaItem>>(`/api/admin/media${qs({ page: state.page, q: state.q, kind: state.kind, per_page: 30 })}`);
      mediaItems = data.items;
      if (!data.items.length) {
        grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>${state.q ? '没有匹配的媒体。' : '媒体库还是空的，上传图片、音频或其他文件吧。'}</p></div>`;
      } else {
        grid.innerHTML = data.items
          .map((item) => {
            const audio = item.kind === 'audio';
            const file = item.kind === 'file';
            const extension = (item.original_name.split('.').pop() || 'FILE').toUpperCase().slice(0, 6);
            const actions = `<div class="media-card__actions">
              ${
                !audio && !file
                  ? `<button type="button" data-exif-edit="${item.id}" title="编辑 EXIF" style="width:auto;padding:0 6px;font-family:var(--font-mono);font-size:7.5px;letter-spacing:.04em">EXIF</button>
                     <button type="button" data-quality-edit="${item.id}" title="设置 AVIF 画质" style="width:auto;padding:0 6px;font-family:var(--font-mono);font-size:7.5px;letter-spacing:.04em">画质</button>`
                  : ''
              }
              <button type="button" data-copy="${escapeHtml(item.url)}" title="复制链接"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
              <button type="button" data-delete="${item.id}" data-name="${escapeHtml(item.original_name)}" title="删除"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/></svg></button>
            </div>`;
            const preview = audio
              ? `<div class="media-card__image media-card__audio"><audio controls preload="metadata" src="${escapeHtml(item.url)}"></audio>${actions}</div>`
              : file
                ? `<div class="media-card__image media-card__file">
                    <a class="media-card__file-link" href="${escapeHtml(item.url)}" target="_blank" rel="noopener" download>
                      <span class="media-card__file-ext">${escapeHtml(extension)}</span>
                      <span class="media-card__file-name">${escapeHtml(item.original_name)}</span>
                      <span class="media-card__file-hint">下载文件</span>
                    </a>${actions}
                  </div>`
                : `<div class="media-card__image"><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener"><img src="${escapeHtml(thumbUrl(item.image, item.url))}" alt="${escapeHtml(item.alt)}" loading="lazy" decoding="async" /></a>${actions}</div>`;
            const sizeLabel = audio ? 'AUDIO' : file ? 'FILE' : `${item.width}×${item.height}`;
            const altPlaceholder = audio ? '音频标题 / 描述' : file ? '文件描述' : '图片替代文字（alt）';
            const isAutoQuality =
              item.avif_quality_auto == null ? true : Boolean(item.avif_quality_auto);
            const qualityLabel =
              !audio && !file
                ? `<span class="media-card__quality">AVIF ${isAutoQuality ? 'AUTO' : Number(item.avif_quality) || 70}</span>`
                : '';
            return `<article class="media-card" id="media-${item.id}">
              ${preview}
              <div class="media-card__body">
                <strong title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</strong>
                <span>${sizeLabel} · ${formatBytes(item.size)}</span>
                <span class="media-card__owner">上传者 · ${escapeHtml(item.owner?.name || '未知')}</span>
                ${
                  !audio && !file && (item.exif?.camera || item.exif?.taken_at)
                    ? `<span class="media-card__exif">${escapeHtml(
                        [item.exif?.camera, item.exif?.taken_at].filter(Boolean).join(' · '),
                      )}</span>`
                    : ''
                }
                <input class="media-card__alt" type="text" value="${escapeHtml(item.alt)}" placeholder="${altPlaceholder}" data-alt="${item.id}" />
                ${qualityLabel}
              </div>
            </article>`;
          })
          .join('');
        bindCards();
      }
      if (!autoOpened && editId) {
        const target =
          mediaItems.find((item) => item.id === editId) ||
          (await api<MediaItem>(`/api/admin/media/${editId}`).catch(() => null));
        if (target?.kind === 'image') {
          autoOpened = true;
          openExifEditor(target);
        }
      }
      if (pagination) {
        pagination.innerHTML =
          data.pages > 1
            ? `<span class="number-label">${data.total} FILES · PAGE ${data.page}/${data.pages}</span>
               <div class="toolbar-group">
                 <button class="a-btn a-btn--sm" data-page="${data.page - 1}" ${data.has_prev ? '' : 'disabled'}>上一页</button>
                 <button class="a-btn a-btn--sm" data-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>下一页</button>
               </div>`
            : `<span class="number-label">${data.total} FILES · MEDIA LIBRARY</span>`;
        pagination.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => {
          button.addEventListener('click', () => {
            state.page = Number(button.dataset.page);
            load();
          });
        });
      }
    } catch (error) {
      grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>${escapeHtml(errorMessage(error))}</p></div>`;
    }
  };

  const bindCards = () => {
    grid?.querySelectorAll<HTMLButtonElement>('[data-exif-edit]').forEach((button) => {
      button.addEventListener('click', () => {
        const item = mediaItems.find((entry) => entry.id === Number(button.dataset.exifEdit));
        if (item) openExifEditor(item);
      });
    });
    grid?.querySelectorAll<HTMLButtonElement>('[data-copy]').forEach((button) => {
      button.addEventListener('click', async () => {
        const url = `${window.location.origin}${button.dataset.copy}`;
        try {
          await navigator.clipboard.writeText(url);
          toast('链接已复制', 'success');
        } catch {
          window.prompt('复制链接', url);
        }
      });
    });
    grid?.querySelectorAll<HTMLButtonElement>('[data-delete]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!window.confirm(`删除「${button.dataset.name}」？已引用它的文章会失去这张图或这段音频。`)) return;
        try {
          await api(`/api/admin/media/${button.dataset.delete}`, { method: 'DELETE' });
          toast('媒体已删除', 'success');
          load();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
    grid?.querySelectorAll<HTMLInputElement>('[data-alt]').forEach((field) => {
      field.addEventListener(
        'change',
        debounce(async () => {
          try {
            await api(`/api/admin/media/${field.dataset.alt}`, { method: 'PUT', body: { alt: field.value } });
            toast('替代文字已保存', 'success');
          } catch (error) {
            toast(errorMessage(error), 'error');
          }
        }, 400),
      );
    });
  };

  const uploadFiles = async (files: FileList | File[]) => {
    const candidates = Array.from(files);
    // Administrators bypass the configured policy; the server keeps its own
    // technical ceiling.
    const list = unrestricted ? candidates : candidates.filter(formatAllowed);
    if (!list.length) {
      toast(`请选择允许的格式：${formatLabels}`, 'error');
      return;
    }
    if (!unrestricted && list.length < candidates.length) {
      toast(`${candidates.length - list.length} 个文件格式未启用，已跳过`, 'error');
    }
    for (const file of list) {
      if (!unrestricted && file.size > maxBytes) {
        toast(`${file.name} 超过 ${maxMb}MB，已跳过`, 'error');
        continue;
      }
      if (status) status.textContent = `正在上传 ${file.name}…`;
      const form = new FormData();
      form.append('file', file);
      form.append('alt', '');
      try {
        await api<MediaItem>('/api/admin/media', { method: 'POST', form });
        toast(`${file.name} 已上传`, 'success');
      } catch (error) {
        toast(`${file.name}：${errorMessage(error)}`, 'error');
      }
    }
    if (status) status.textContent = '';
    load();
  };

  zone?.addEventListener('click', (event) => {
    if ((event.target as HTMLElement).tagName !== 'INPUT') input?.click();
  });
  zone?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      input?.click();
    }
  });
  input?.addEventListener('change', () => {
    if (input.files) uploadFiles(input.files);
    input.value = '';
  });
  ['dragenter', 'dragover'].forEach((eventName) => {
    zone?.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add('is-dragging');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    zone?.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove('is-dragging');
    });
  });
  zone?.addEventListener('drop', (event) => {
    if (event.dataTransfer?.files) uploadFiles(event.dataTransfer.files);
  });

  kindTabs?.querySelectorAll<HTMLButtonElement>('[data-kind]').forEach((button) => {
    button.addEventListener('click', () => {
      state.kind = button.dataset.kind || '';
      state.page = 1;
      kindTabs.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      load();
    });
  });

  search?.addEventListener(
    'input',
    debounce(() => {
      state.q = search.value.trim();
      state.page = 1;
      load();
    }, 350),
  );

  // 画质按钮打开与 EXIF 一致的弹窗；列表重渲染后委托仍然有效。
  initQualityDialog({ onSaved: () => load() });

  load();
}
