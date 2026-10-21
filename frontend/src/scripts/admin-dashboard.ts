import { api } from '../lib/api';
import { errorMessage, statusBadge, toast } from '../lib/admin-client';
import { html, setHTML } from '../lib/dom';
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
      setStat('pages', number(stats.pages), '独立页面');
      renderRecent(stats);
      renderGalleries(stats);
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
    setHTML(
      container,
      html`<div class="admin-empty"><p>还没有文章。<a href="/admin/posts/new">写下第一篇</a>。</p></div>`,
    );
    return;
  }
  setHTML(
    container,
    html`
    <table class="admin-table">
      <thead><tr><th>标题</th><th>状态</th><th>更新</th></tr></thead>
      <tbody>
        ${stats.recent_posts.map(
          (post) => html`<tr>
              <td>
                <a class="table-title" href="/admin/posts/${post.id}">
                  <span class="table-title__text">
                    <strong>${post.title}</strong>
                    <span>${post.categories?.[0]?.name || '未分类'} · ${post.reading_time} min</span>
                  </span>
                </a>
              </td>
              <td>${statusBadge(post.raw_status || post.status)}</td>
              <td><span style="color: var(--ink-faint); font-size: 10px">${timeAgo(post.updated_at)}</span></td>
            </tr>`,
        )}
      </tbody>
    </table>`,
  );
}

function renderGalleries(stats: Stats): void {
  const container = root?.querySelector<HTMLElement>('[data-recent-galleries]');
  if (!container) return;
  if (!stats.recent_galleries?.length) {
    setHTML(
      container,
      html`<div class="admin-empty"><p>还没有相册。<a href="/admin/galleries">新建一本</a>。</p></div>`,
    );
    return;
  }
  setHTML(
    container,
    html`${stats.recent_galleries.map(
      (gallery) => html`<a class="top-post" href="/admin/galleries/${gallery.id}">
        <span class="top-post__index">${String(gallery.photo_count).padStart(2, '0')}</span>
        <span class="top-post__body">
          <strong>${gallery.title}</strong>
          <span style="color: var(--ink-faint); font-family: var(--font-mono); font-size: 8.5px; letter-spacing: .08em; text-transform: uppercase">
            ${gallery.status} · ${timeAgo(gallery.updated_at)}
          </span>
        </span>
        <span class="top-post__count">→</span>
      </a>`,
    )}`,
  );
}
