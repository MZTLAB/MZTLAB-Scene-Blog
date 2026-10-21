import { api } from './api';
import { html, type RawHtml } from './dom';

// Backwards-compatible re-export: `escapeHtml` now lives in ./dom (single
// implementation for the whole frontend).
export { escapeHtml } from './dom';

type ToastKind = 'info' | 'success' | 'error';

export function toast(message: string, kind: ToastKind = 'info', duration = 3200): void {
  let root = document.getElementById('toastRoot');
  if (!root) {
    root = document.createElement('div');
    root.id = 'toastRoot';
    root.className = 'toast-root';
    document.body.appendChild(root);
  }
  const item = document.createElement('div');
  item.className = `toast toast--${kind}`;
  item.textContent = message;
  root.appendChild(item);
  window.setTimeout(() => {
    item.classList.add('is-leaving');
    window.setTimeout(() => item.remove(), 220);
  }, duration);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试';
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function statusBadge(status: string): RawHtml {
  const labels: Record<string, string> = {
    published: '已发布',
    draft: '草稿',
    scheduled: '定时',
  };
  return html`<span class="badge badge--${status}">${labels[status] || status}</span>`;
}

export function debounce<T extends (...args: never[]) => void>(fn: T, wait = 300): (...args: Parameters<T>) => void {
  let timer: number | undefined;
  return (...args: Parameters<T>) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

export async function logout(): Promise<void> {
  try {
    await api('/api/auth/logout', { method: 'POST', redirectOn401: false });
  } catch {
    // Even if the request fails, clear the local view.
  }
  window.location.href = '/admin/login';
}

export function initAdminShell(): void {
  const shell = document.querySelector<HTMLElement>('.admin-shell');
  const menuButtons = document.querySelectorAll<HTMLElement>('[data-admin-menu]');
  const backdrop = document.querySelector<HTMLElement>('[data-admin-backdrop]');

  const closeNav = () => shell?.classList.remove('is-nav-open');
  menuButtons.forEach((button) =>
    button.addEventListener('click', () => shell?.classList.toggle('is-nav-open')),
  );
  backdrop?.addEventListener('click', closeNav);
  document.querySelectorAll('.admin-nav a, .admin-sidebar__foot a').forEach((link) =>
    link.addEventListener('click', closeNav),
  );
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeNav();
  });

  document.querySelectorAll<HTMLElement>('[data-logout]').forEach((button) =>
    button.addEventListener('click', () => logout()),
  );
}
