import { api, qs } from '../lib/api';
import { debounce, errorMessage, escapeHtml, statusBadge, toast } from '../lib/admin-client';
import { formatDate } from '../lib/format';
import { thumbUrl } from '../lib/images';
import type { Gallery, Paginated } from '../types';

const root = document.querySelector<HTMLElement>('[data-galleries-page]');
if (root) {
  const grid = root.querySelector<HTMLElement>('[data-gallery-grid]');
  const pagination = root.querySelector<HTMLElement>('[data-pagination]');
  const filters = root.querySelector<HTMLElement>('[data-filters]');
  const search = root.querySelector<HTMLInputElement>('[data-search]');
  const createCard = root.querySelector<HTMLElement>('[data-create-card]');
  const createForm = root.querySelector<HTMLFormElement>('[data-create-form]');
  const state = { page: 1, status: '', q: '' };

  const openCreate = (open: boolean) => {
    if (!createCard) return;
    createCard.hidden = !open;
    if (open) {
      createCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
      root.querySelector<HTMLInputElement>('[data-create-title]')?.focus();
    }
  };

  const load = async () => {
    if (!grid) return;
    grid.innerHTML =
      '<div class="admin-loading" style="grid-column:1/-1"><div class="skeleton" style="height:140px"></div></div>';
    try {
      const data = await api<Paginated<Gallery> & { counts: Record<string, number> }>(
        `/api/admin/galleries${qs({ page: state.page, status: state.status, q: state.q, per_page: 24 })}`,
      );
      syncCounts(data.counts);
      if (!data.items.length) {
        grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1">
          <p>${state.q ? '没有匹配的相册。' : '还没有相册。新建一本，从媒体库挑几张照片开始。'}</p>
          <button class="a-btn a-btn--sm" type="button" data-empty-create>新建相册</button>
        </div>`;
        grid.querySelector('[data-empty-create]')?.addEventListener('click', () => openCreate(true));
      } else {
        grid.innerHTML = data.items.map(renderCard).join('');
        bindCards();
      }
      renderPagination(data);
    } catch (error) {
      grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>${escapeHtml(errorMessage(error))}</p></div>`;
    }
  };

  const renderCard = (gallery: Gallery) => {
    const cover = gallery.cover;
    return `<article class="gallery-admin-card" data-gallery="${gallery.id}">
      <a class="gallery-admin-card__media" href="/admin/galleries/${gallery.id}">
        ${cover ? `<img src="${escapeHtml(thumbUrl(cover.image, cover.url))}" alt="${escapeHtml(cover.alt)}" loading="lazy" />` : '<div style="display:grid;place-content:center;height:100%;color:var(--ink-faint);font-family:var(--font-mono);font-size:9px;letter-spacing:.12em">NO COVER</div>'}
        ${statusBadge(gallery.status)}
      </a>
      <div class="gallery-admin-card__body">
        <strong>${escapeHtml(gallery.title)}</strong>
        <div class="gallery-admin-card__meta">
          <span>${gallery.photo_count} FRAMES</span>
          <span>${escapeHtml(formatDate(gallery.updated_at, 'short'))}</span>
        </div>
      </div>
      <div class="gallery-admin-card__actions">
        <a class="a-btn a-btn--sm" href="/admin/galleries/${gallery.id}">编辑</a>
        ${gallery.status === 'published' ? `<a class="a-btn a-btn--sm" href="${escapeHtml(gallery.url)}" target="_blank" rel="noopener">查看</a>` : ''}
        <button class="a-btn a-btn--sm a-btn--danger" type="button" data-delete="${gallery.id}" data-title="${escapeHtml(gallery.title)}">删除</button>
      </div>
    </article>`;
  };

  const bindCards = () => {
    grid?.querySelectorAll<HTMLButtonElement>('[data-delete]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!window.confirm(`删除相册「${button.dataset.title}」？相册内的照片记录会一并移除（原图仍在媒体库）。`)) return;
        try {
          await api(`/api/admin/galleries/${button.dataset.delete}`, { method: 'DELETE' });
          toast('相册已删除', 'success');
          load();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
  };

  const syncCounts = (counts: Record<string, number>) => {
    filters?.querySelectorAll<HTMLElement>('[data-status]').forEach((button) => {
      const value = button.dataset.status || '';
      const node = button.querySelector('small');
      if (node) node.textContent = String(counts[value] ?? 0);
      button.classList.toggle('is-active', value === state.status);
    });
  };

  const renderPagination = (data: Paginated<Gallery>) => {
    if (!pagination) return;
    if (data.pages <= 1) {
      pagination.innerHTML = `<span class="number-label">${data.total} GALLERIES</span>`;
      return;
    }
    pagination.innerHTML = `
      <span class="number-label">PAGE ${data.page} / ${data.pages} · ${data.total} GALLERIES</span>
      <div class="toolbar-group">
        <button class="a-btn a-btn--sm" data-page="${data.page - 1}" ${data.has_prev ? '' : 'disabled'}>上一页</button>
        <button class="a-btn a-btn--sm" data-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>下一页</button>
      </div>`;
    pagination.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => {
      button.addEventListener('click', () => {
        state.page = Number(button.dataset.page);
        load();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  };

  root.querySelectorAll<HTMLElement>('[data-open-create]').forEach((button) =>
    button.addEventListener('click', () => openCreate(true)),
  );
  root.querySelectorAll<HTMLElement>('[data-close-create]').forEach((button) =>
    button.addEventListener('click', () => openCreate(false)),
  );

  createForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const title = root.querySelector<HTMLInputElement>('[data-create-title]')?.value.trim();
    if (!title) {
      toast('请填写相册标题', 'error');
      return;
    }
    const payload = {
      title,
      slug: root.querySelector<HTMLInputElement>('[data-create-slug]')?.value.trim() || '',
      description: root.querySelector<HTMLTextAreaElement>('[data-create-desc]')?.value.trim() || '',
      status: root.querySelector<HTMLSelectElement>('[data-create-status]')?.value || 'draft',
      featured: Boolean(root.querySelector<HTMLInputElement>('[data-create-featured]')?.checked),
      cover_photo_id: null,
    };
    try {
      const created = await api<Gallery>('/api/admin/galleries', { method: 'POST', body: payload });
      toast('相册已创建', 'success');
      window.location.href = `/admin/galleries/${created.id}`;
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });

  filters?.querySelectorAll<HTMLButtonElement>('[data-status]').forEach((button) => {
    button.addEventListener('click', () => {
      state.status = button.dataset.status || '';
      state.page = 1;
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

  load();
}
