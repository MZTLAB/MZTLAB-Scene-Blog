import { api, qs } from '../lib/api';
import { debounce, errorMessage, escapeHtml, toast } from '../lib/admin-client';
import { formatDate, initial, timeAgo } from '../lib/format';
import type { Comment, Paginated } from '../types';

interface CommentsResponse extends Paginated<Comment> {
  counts: Record<string, number>;
}

const root = document.querySelector<HTMLElement>('[data-comments-page]');
if (root) {
  const list = root.querySelector<HTMLElement>('[data-comment-list]');
  const pagination = root.querySelector<HTMLElement>('[data-comment-pagination]');
  const filters = root.querySelector<HTMLElement>('[data-comment-filters]');
  const search = root.querySelector<HTMLInputElement>('[data-comment-search]');
  const state = { page: 1, status: '', q: '' };

  const load = async () => {
    if (!list) return;
    list.innerHTML = `<div class="admin-loading" style="padding: 30px"><div class="skeleton" style="height: 60px"></div><div class="skeleton" style="height: 60px"></div></div>`;
    try {
      const data = await api<CommentsResponse>(`/api/admin/comments${qs({ page: state.page, status: state.status, q: state.q, per_page: 20 })}`);
      updateCounts(data.counts);
      if (!data.items.length) {
        list.innerHTML = '<div class="admin-empty"><p>这里没有留言。</p></div>';
      } else {
        list.innerHTML = data.items
          .map(
            (comment) => `<article class="comment-admin-item" data-comment-id="${comment.id}">
              <span class="avatar">${escapeHtml(initial(comment.author_name))}</span>
              <div class="comment-admin-item__body">
                <div class="comment-admin-item__meta">
                  <strong>${escapeHtml(comment.author_name)}</strong>
                  ${comment.author_email ? `<span>${escapeHtml(comment.author_email)}</span>` : ''}
                  <span>${escapeHtml(timeAgo(comment.created_at))}</span>
                  <a href="/admin/posts/${comment.post_id}" style="color: var(--accent); font-size: 9px">${escapeHtml(comment.post_title || '文章')}</a>
                  <span class="badge badge--${escapeHtml(comment.status || 'pending')}">${statusLabel(comment.status)}</span>
                </div>
                <p>${escapeHtml(comment.content)}</p>
                ${comment.author_url ? `<a href="${escapeHtml(comment.author_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--ink-faint); font-size: 9px">${escapeHtml(comment.author_url)}</a>` : ''}
              </div>
              <div class="comment-admin-item__actions">
                ${comment.status !== 'approved' ? `<button class="a-btn a-btn--sm" type="button" data-set-status="approved" data-id="${comment.id}">通过</button>` : ''}
                ${comment.status !== 'pending' ? `<button class="a-btn a-btn--sm" type="button" data-set-status="pending" data-id="${comment.id}">待审</button>` : ''}
                ${comment.status !== 'spam' ? `<button class="a-btn a-btn--sm" type="button" data-set-status="spam" data-id="${comment.id}">垃圾</button>` : ''}
                <button class="a-btn a-btn--sm a-btn--danger" type="button" data-delete-comment="${comment.id}">删除</button>
              </div>
            </article>`,
          )
          .join('');
        bindActions();
      }
      if (pagination) {
        pagination.innerHTML =
          data.pages > 1
            ? `<span class="number-label">PAGE ${data.page} / ${data.pages} · ${data.total} COMMENTS</span>
               <div class="toolbar-group">
                 <button class="a-btn a-btn--sm" data-page="${data.page - 1}" ${data.has_prev ? '' : 'disabled'}>上一页</button>
                 <button class="a-btn a-btn--sm" data-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>下一页</button>
               </div>`
            : `<span class="number-label">${data.total} COMMENTS · ${formatDate(new Date().toISOString(), 'short')}</span>`;
        pagination.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => {
          button.addEventListener('click', () => {
            state.page = Number(button.dataset.page);
            load();
          });
        });
      }
    } catch (error) {
      list.innerHTML = `<div class="admin-empty"><p>${escapeHtml(errorMessage(error))}</p></div>`;
    }
  };

  const bindActions = () => {
    list?.querySelectorAll<HTMLButtonElement>('[data-set-status]').forEach((button) => {
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await api(`/api/admin/comments/${button.dataset.id}`, {
            method: 'PUT',
            body: { status: button.dataset.setStatus },
          });
          toast('留言状态已更新', 'success');
          load();
        } catch (error) {
          button.disabled = false;
          toast(errorMessage(error), 'error');
        }
      });
    });
    list?.querySelectorAll<HTMLButtonElement>('[data-delete-comment]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!window.confirm('确定删除这条留言吗？')) return;
        try {
          await api(`/api/admin/comments/${button.dataset.deleteComment}`, { method: 'DELETE' });
          toast('留言已删除', 'success');
          load();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
  };

  const updateCounts = (counts: Record<string, number>) => {
    filters?.querySelectorAll<HTMLElement>('[data-status]').forEach((button) => {
      const value = button.dataset.status || '';
      const node = button.querySelector('small');
      if (node) node.textContent = String(value ? counts[value] || 0 : counts.all || 0);
      button.classList.toggle('is-active', value === state.status);
    });
  };

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

function statusLabel(status?: string): string {
  return status === 'approved' ? '已通过' : status === 'spam' ? '垃圾' : '待审核';
}
