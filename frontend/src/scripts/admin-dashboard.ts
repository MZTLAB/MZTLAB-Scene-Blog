import { api } from '../lib/api';
import { escapeHtml, errorMessage, statusBadge, toast } from '../lib/admin-client';
import { number, timeAgo } from '../lib/format';
import type { Stats } from '../types';

const root = document.querySelector<HTMLElement>('[data-dashboard]');
if (root) {
  const hour = new Date().getHours();
  const greeting =
    hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 19 ? '下午好' : '晚上好';
  const greetingNode = root.querySelector('[data-greeting]');
  if (greetingNode) greetingNode.textContent = `${greeting}，今天记录什么？`;

  api<Stats>('/api/admin/stats')
    .then((stats) => {
      setStat('photos', number(stats.photos), `${stats.galleries} 本相册 · ${stats.media} 个文件`);
      setStat('posts', number(stats.posts.all), `${stats.posts.published} 篇已发布 · ${stats.posts.draft} 篇草稿`);
      setStat(
        'projects',
        number(stats.projects?.all || 0),
        `${stats.projects?.published || 0} 个已发布 · ${stats.projects?.draft || 0} 个草稿`,
      );
      setStat('comments', number(stats.comments.pending), `${stats.comments.all} 条留言总数`);
      renderRecent(stats);
      renderGalleries(stats);
      renderPending(stats);
      const version = root.querySelector('[data-version]');
      if (version) version.textContent = `v${stats.system.version}`;
    })
    .catch((error) => {
      toast(errorMessage(error), 'error');
      root.querySelectorAll('.skeleton').forEach((node) => {
        (node as HTMLElement).style.opacity = '0.4';
      });
    });
}

function setStat(key: string, value: string, hint: string): void {
  const card = root?.querySelector<HTMLElement>(`[data-stat="${key}"]`);
  if (!card) return;
  const valueNode = card.querySelector('[data-value]');
  const hintNode = card.querySelector('[data-hint]');
  if (valueNode) valueNode.textContent = value;
  if (hintNode) hintNode.textContent = hint;
}

function renderRecent(stats: Stats): void {
  const container = root?.querySelector<HTMLElement>('[data-recent-posts]');
  if (!container) return;
  if (!stats.recent_posts.length) {
    container.innerHTML =
      '<div class="admin-empty"><p>还没有文章。<a href="/admin/posts/new">写下第一篇</a>。</p></div>';
    return;
  }
  container.innerHTML = `
    <table class="admin-table">
      <thead><tr><th>标题</th><th>状态</th><th>更新</th><th style="text-align:right">浏览</th></tr></thead>
      <tbody>
        ${stats.recent_posts
          .map(
            (post) => `<tr>
              <td>
                <a class="table-title" href="/admin/posts/${post.id}">
                  <span class="table-title__text">
                    <strong>${escapeHtml(post.title)}</strong>
                    <span>${escapeHtml(post.categories?.[0]?.name || '未分类')} · ${post.reading_time} min</span>
                  </span>
                </a>
              </td>
              <td>${statusBadge(post.raw_status || post.status)}</td>
              <td><span style="color: var(--ink-faint); font-size: 10px">${escapeHtml(timeAgo(post.updated_at))}</span></td>
              <td style="text-align:right"><span style="font-family: var(--font-mono); font-size: 9px">${number(post.view_count)}</span></td>
            </tr>`,
          )
          .join('')}
      </tbody>
    </table>`;
}

function renderGalleries(stats: Stats): void {
  const container = root?.querySelector<HTMLElement>('[data-recent-galleries]');
  if (!container) return;
  if (!stats.recent_galleries?.length) {
    container.innerHTML =
      '<div class="admin-empty"><p>还没有相册。<a href="/admin/galleries">新建一本</a>。</p></div>';
    return;
  }
  container.innerHTML = stats.recent_galleries
    .map(
      (gallery) => `<a class="top-post" href="/admin/galleries/${gallery.id}">
        <span class="top-post__index">${String(gallery.photo_count).padStart(2, '0')}</span>
        <span class="top-post__body">
          <strong>${escapeHtml(gallery.title)}</strong>
          <span style="color: var(--ink-faint); font-family: var(--font-mono); font-size: 8.5px; letter-spacing: .08em; text-transform: uppercase">
            ${escapeHtml(gallery.status)} · ${escapeHtml(timeAgo(gallery.updated_at))}
          </span>
        </span>
        <span class="top-post__count">→</span>
      </a>`,
    )
    .join('');
}

function renderPending(stats: Stats): void {
  const container = root?.querySelector<HTMLElement>('[data-pending-comments]');
  if (!container) return;
  if (!stats.pending_comments.length) {
    container.innerHTML = '<div class="admin-empty"><p>没有待审核的留言。</p></div>';
    return;
  }
  container.innerHTML = stats.pending_comments
    .map(
      (comment) => `<div class="comment-admin-item" data-comment-row="${comment.id}">
        <span class="avatar">${escapeHtml((comment.author_name || '客').slice(0, 1))}</span>
        <div class="comment-admin-item__body">
          <div class="comment-admin-item__meta">
            <strong>${escapeHtml(comment.author_name)}</strong>
            <span>${escapeHtml(timeAgo(comment.created_at))}</span>
          </div>
          <p>${escapeHtml(comment.content)}</p>
        </div>
        <div class="comment-admin-item__actions">
          <button class="a-btn a-btn--sm" type="button" data-approve-comment="${comment.id}">通过</button>
        </div>
      </div>`,
    )
    .join('');

  container.querySelectorAll<HTMLButtonElement>('[data-approve-comment]').forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await api(`/api/admin/comments/${button.dataset.approveComment}`, {
          method: 'PUT',
          body: { status: 'approved' },
        });
        button.closest('[data-comment-row]')?.remove();
        toast('留言已通过', 'success');
        if (!container.querySelector('[data-comment-row]')) {
          container.innerHTML = '<div class="admin-empty"><p>没有待审核的留言。</p></div>';
        }
        const badge = document.querySelector<HTMLElement>('[data-pending-count]');
        if (badge) {
          const next = Math.max(0, Number(badge.textContent || 0) - 1);
          badge.textContent = String(next);
          badge.hidden = next === 0;
        }
      } catch (error) {
        button.disabled = false;
        toast(errorMessage(error), 'error');
      }
    });
  });
}
