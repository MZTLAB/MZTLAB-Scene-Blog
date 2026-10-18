const longDate = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
});

const shortDate = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const dateTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

const monthLabel = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  year: 'numeric',
});

export function formatMonth(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value.length === 7 ? `${value}-01` : value);
  if (Number.isNaN(date.getTime())) return value;
  return monthLabel.format(date).toUpperCase();
}

export function formatDate(iso: string | null | undefined, style: 'long' | 'short' | 'datetime' = 'long'): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  if (style === 'short') return shortDate.format(date).replaceAll('/', '.');
  if (style === 'datetime') return dateTime.format(date);
  return longDate.format(date);
}

export function formatDateInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Math.max(0, Date.now() - then);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return formatDate(iso, 'short');
}

export function number(value: number | null | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(value || 0);
}

export function absoluteUrl(siteUrl: string, path: string): string {
  if (!path) return siteUrl || '';
  if (/^https?:\/\//.test(path)) return path;
  const base = (siteUrl || 'http://127.0.0.1:4321').replace(/\/$/, '');
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

export function initial(name: string): string {
  return (name || '岛').trim().slice(0, 1).toUpperCase();
}

export function safeJson(value: unknown): string {
  return JSON.stringify(value)
    .replaceAll('<', '\\u003c')
    .replaceAll('>', '\\u003e')
    .replaceAll('&', '\\u0026')
    .replaceAll('\u2028', '\\u2028')
    .replaceAll('\u2029', '\\u2029');
}

export function coverVariant(slug: string): number {
  let hash = 0;
  for (let i = 0; i < slug.length; i += 1) {
    hash = (hash * 31 + slug.charCodeAt(i)) >>> 0;
  }
  return hash % 6;
}

export function plainText(value: string): string {
  return value
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

export function stripStyleClose(css: string): string {
  return (css || '').replace(/<\/style/gi, '<\\/style');
}
