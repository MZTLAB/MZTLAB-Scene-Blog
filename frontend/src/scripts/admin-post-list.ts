import { api, qs } from '../lib/api';
import { debounce, errorMessage, escapeHtml, statusBadge, toast } from '../lib/admin-client';
import { formatDate, number } from '../lib/format';
import type { Paginated, PostSummary } from '../types';

interface ListResponse extends Paginated<PostSummary> {
  counts: { all: number; published: number; draft: number; scheduled: number };
}

const root = document.querySelector<HTMLElement>('[data-post-list]');
if (root) {
  const rawType = root.dataset.type || 'post';
  const type = rawType === 'page' || rawType === 'project' ? rawType : 'post';
  const isPage = type === 'page';
  const isProject = type === 'project';
  const base = isPage ? '/admin/pages' : isProject ? '/admin/projects' : '/admin/posts';
  const itemWord = isPage ? '页面' : isProject ? '项目' : '文章';
  const emptyWord = isPage ? '还没有独立页面。' : isProject ? '还没有项目，去创建第一个吧。' : '还没有文章，去写第一篇吧。';
  const tableHost = root.querySelector<HTMLElement>('[data-table]');
  const paginationHost = root.querySelector<HTMLElement>('[data-pagination]');
  const searchInput = root.querySelector<HTMLInputElement>('[data-search]');
  const filters = root.querySelector<HTMLElement>('[data-filters]');
  const initial = new URLSearchParams(window.location.search);
  const state = {
    page: Math.max(1, Number(initial.get('page') || 1)),
    status: initial.get('status') || '',
    q: initial.get('q') || '',
  };
  if (searchInput) searchInput.value = state.q;

  const syncUrl = () => {
    const params = new URLSearchParams();
    if (state.status) params.set('status', state.status);
    if (state.q) params.set('q', state.q);
    if (state.page > 1) params.set('page', String(state.page));
    const value = params.toString();
    window.history.replaceState(null, '', value ? `?${value}` : window.location.pathname);
  };

  const renderLoading = () => {
    if (!tableHost) return;
    tableHost.innerHTML = `<div class="admin-loading">
      <div class="skeleton" style="width: 45%; height: 18px"></div>
      <div class="skeleton" style="width: 100%; height: 12px"></div>
      <div class="skeleton" style="width: 80%; height: 12px"></div>
    </div>`;
  };

  const publicLink = (post: PostSummary) =>
    post.status === 'published'
      ? `<a href="${escapeHtml(post.url)}" target="_blank" rel="noopener" title="查看"><svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></a>`
      : '';

  const load = async () => {
    renderLoading();
    try {
      const data = await api<ListResponse>(
        `/api/admin/posts${qs({ type, status: state.status, q: state.q, page: state.page, per_page: 20 })}`,
      );
      updateCounts(data.counts);
      if (!data.items.length) {
        tableHost!.innerHTML = `<div class="admin-empty">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M9 13h6M9 17h4"/></svg>
          <p>${state.q ? '没有匹配的内容。' : emptyWord}</p>
          <a class="a-btn a-btn--sm" style="margin-top:12px" href="${base}/new">立即创建</a>
        </div>`;
      } else {
        tableHost!.innerHTML = `
          <table class="admin-table">
            <thead>
              <tr>
                <th>${itemWord}</th>
                <th>作者</th>
                <th>状态</th>
                <th>${isPage ? '更新时间' : '发布时间'}</th>
                <th>阅读</th>
                <th style="text-align:right">操作</th>
              </tr>
            </thead>
            <tbody>
              ${data.items
                .map(
                  (post) => `<tr>
                    <td>
                      <div class="table-title">
                        <span class="table-title__text">
                          <strong><a href="${base}/${post.id}">${escapeHtml(post.title)}</a></strong>
                          <span>/${escapeHtml(post.slug)} · ${escapeHtml(post.categories?.[0]?.name || (isPage ? 'Page' : '未分类'))}</span>
                        </span>
                      </div>
                    </td>
                    <td><span style="color:var(--ink-soft);font-size:11px">${escapeHtml(post.author?.name || '—')}</span></td>
                    <td>${statusBadge(post.raw_status || post.status)}</td>
                    <td><span style="color:var(--ink-faint);font-size:10px">${escapeHtml(
                      formatDate(isPage ? post.updated_at : post.published_at || post.updated_at, 'short'),
                    )}</span></td>
                    <td><span style="font-family:var(--font-mono);font-size:9px">${number(post.view_count)}</span></td>
                    <td>
                      <div class="table-actions">
                        ${publicLink(post)}
                        <a href="${base}/${post.id}" title="编辑"><svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></a>
                        <button class="danger" type="button" data-delete="${post.id}" data-title="${escapeHtml(post.title)}" title="删除"><svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/></svg></button>
                      </div>
                    </td>
                  </tr>`,
                )
                .join('')}
            </tbody>
          </table>`;
        tableHost!.querySelectorAll<HTMLButtonElement>('[data-delete]').forEach((button) => {
          button.addEventListener('click', () => remove(Number(button.dataset.delete), button.dataset.title || ''));
        });
      }
      renderPagination(data);
      syncUrl();
    } catch (error) {
      tableHost!.innerHTML = `<div class="admin-empty"><p>${escapeHtml(errorMessage(error))}</p><button class="a-btn a-btn--sm" style="margin-top:12px" data-retry>重试</button></div>`;
      tableHost!.querySelector('[data-retry]')?.addEventListener('click', load);
    }
  };

  const remove = async (id: number, title: string) => {
    if (!window.confirm(`确定删除「${title}」吗？此操作不可撤销。`)) return;
    try {
      await api(`/api/admin/posts/${id}`, { method: 'DELETE' });
      toast('已删除', 'success');
      await load();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const updateCounts = (counts: ListResponse['counts']) => {
    filters?.querySelectorAll<HTMLElement>('[data-status]').forEach((button) => {
      const value = button.dataset.status || '';
      const values: Record<string, number> = {
        '': counts.all,
        published: counts.published,
        draft: counts.draft,
        scheduled: counts.scheduled,
      };
      const countNode = button.querySelector('small');
      if (countNode) countNode.textContent = String(values[value] ?? 0);
      button.classList.toggle('is-active', value === state.status);
    });
  };

  const renderPagination = (data: ListResponse) => {
    if (!paginationHost) return;
    if (data.pages <= 1) {
      paginationHost.innerHTML = `<span class="number-label">${data.total} ITEMS</span>`;
      return;
    }
    paginationHost.innerHTML = `
      <span class="number-label">PAGE ${data.page} / ${data.pages} · ${data.total} ITEMS</span>
      <div class="toolbar-group">
        <button class="a-btn a-btn--sm" data-page="${data.page - 1}" ${data.has_prev ? '' : 'disabled'}>上一页</button>
        <button class="a-btn a-btn--sm" data-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>下一页</button>
      </div>`;
    paginationHost.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => {
      button.addEventListener('click', () => {
        state.page = Number(button.dataset.page);
        load();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  };

  filters?.querySelectorAll<HTMLButtonElement>('[data-status]').forEach((button) => {
    button.addEventListener('click', () => {
      state.status = button.dataset.status || '';
      state.page = 1;
      load();
    });
  });

  searchInput?.addEventListener(
    'input',
    debounce(() => {
      state.q = searchInput.value.trim();
      state.page = 1;
      load();
    }, 380),
  );

  load();
}
