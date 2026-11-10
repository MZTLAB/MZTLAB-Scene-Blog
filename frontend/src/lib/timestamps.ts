import { escapeHtml, timeAgo } from './format';

export type TimestampStyle = 'long' | 'short' | 'datetime' | 'month' | 'year' | 'relative';

export function utcOffset(date: Date): string {
  const minutes = -date.getTimezoneOffset();
  return `UTC${minutes >= 0 ? '+' : '-'}${Math.abs(minutes) / 60}`;
}

export function timestampText(iso: string, style: TimestampStyle, client = true): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  if (style === 'year') return String(client ? date.getFullYear() : date.getUTCFullYear());
  if (style === 'relative') {
    return Date.now() - date.getTime() < 30 * 86_400_000
      ? timeAgo(iso)
      : timestampText(iso, 'short', client);
  }
  const options: Intl.DateTimeFormatOptions = {
    ...(!client ? { timeZone: 'UTC' } : {}),
    year: 'numeric',
    month: style === 'long' ? 'long' : style === 'month' ? 'short' : '2-digit',
    ...(style !== 'month' ? { day: style === 'long' ? 'numeric' : '2-digit' } : {}),
    ...(style === 'datetime' ? { hour: '2-digit', minute: '2-digit' } : {}),
  };
  const text = new Intl.DateTimeFormat(style === 'month' ? 'en-US' : 'zh-CN', options).format(date);
  return style === 'short'
    ? text.replaceAll('/', '.')
    : style === 'month'
      ? text.toUpperCase()
      : text;
}

/** Escapes the source before generating HTML, including in browser-rendered lists. */
export function formatTimestamp(
  iso: string | null | undefined,
  style: TimestampStyle = 'short',
): string {
  if (!iso || Number.isNaN(new Date(iso).getTime())) return '—';
  const client = typeof window !== 'undefined';
  return `<time datetime="${escapeHtml(iso)}" data-timestamp="${style}"><span>${escapeHtml(timestampText(iso, style, client))}</span><sup> ${client ? utcOffset(new Date(iso)) : 'UTC+0'}</sup></time>`;
}

/** Fixed offsets are minutes east of UTC; 'local' follows the device's DST rules. */
export function dateInput(iso: string | null | undefined, zone: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const offset = zone === 'local' ? -date.getTimezoneOffset() : Number(zone);
  return new Date(date.getTime() + offset * 60_000).toISOString().slice(0, 19);
}

export function inputToUtc(value: string, zone: string): string | null {
  if (!value) return null;
  const date =
    zone === 'local'
      ? new Date(value)
      : new Date(new Date(`${value}Z`).getTime() - Number(zone) * 60_000);
  if (Number.isNaN(date.getTime())) throw new Error('请输入有效时间');
  // A datetime-local value in a DST gap must not silently jump forward.
  if (zone === 'local' && dateInput(date.toISOString(), zone).slice(0, value.length) !== value) {
    throw new Error('该本地时间不存在，请选择其他时间或 UTC 偏移');
  }
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}
