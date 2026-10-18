import type { SiteInfo } from '../types';

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function internalBase(): string {
  // `process` only exists on the server. Do not evaluate this in the browser.
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  return env?.BLOG_API_INTERNAL_URL || 'http://127.0.0.1:8000';
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'object' && item && 'msg' in item) {
          return String((item as { msg: unknown }).msg).replace(/^Value error, /, '');
        }
        return String(item);
      })
      .join('；');
  }
  if (detail && typeof detail === 'object' && 'detail' in detail) {
    return detailToMessage((detail as { detail: unknown }).detail, fallback);
  }
  return fallback;
}

/** Server-side fetch with the visitor's cookie forwarded when needed. */
export async function apiServer<T>(
  path: string,
  options: { cookie?: string; method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const headers = new Headers();
  if (options.cookie) headers.set('cookie', options.cookie);
  if (options.body !== undefined) headers.set('content-type', 'application/json');
  headers.set('x-blog-request', '1');
  const response = await fetch(`${internalBase()}${path}`, {
    method: options.method || 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: AbortSignal.timeout(options.timeoutMs ?? 12_000),
  });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const message = detailToMessage(
      (data as { detail?: unknown } | null)?.detail,
      `请求失败（${response.status}）`,
    );
    throw new ApiError(response.status, message, data);
  }
  return data as T;
}

let siteCache: { at: number; data: SiteInfo } | null = null;
let sitePromise: Promise<SiteInfo> | null = null;

/** Site chrome changes should be visible almost immediately after saving. */
export async function getSite(): Promise<SiteInfo> {
  if (siteCache && Date.now() - siteCache.at < 1_000) return siteCache.data;
  if (sitePromise) return sitePromise;
  sitePromise = apiServer<SiteInfo>('/api/site')
    .then((data) => {
      siteCache = { at: Date.now(), data };
      return data;
    })
    .finally(() => {
      sitePromise = null;
    });
  return sitePromise;
}

export function clearSiteCache(): void {
  siteCache = null;
}

export async function getPost(slug: string): Promise<import('../types').PostDetail> {
  return apiServer(`/api/posts/${encodeURIComponent(slug)}`);
}

export async function getPage(slug: string): Promise<import('../types').PostDetail> {
  return apiServer(`/api/pages/${encodeURIComponent(slug)}`);
}

/** Browser API client. All admin calls carry the CSRF marker header. */
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    form?: FormData;
    signal?: AbortSignal;
    redirectOn401?: boolean;
  } = {},
): Promise<T> {
  const headers = new Headers();
  headers.set('x-blog-request', '1');
  headers.set('accept', 'application/json');
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers.set('content-type', 'application/json');
    body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {
    method: options.method || 'GET',
    headers,
    body,
    credentials: 'same-origin',
    signal: options.signal,
  });
  if (response.status === 401 && options.redirectOn401 !== false) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/admin/login?next=${next}`;
    throw new ApiError(401, '登录已过期');
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      detailToMessage((data as { detail?: unknown } | null)?.detail, `请求失败（${response.status}）`),
      data,
    );
  }
  return data as T;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const value = search.toString();
  return value ? `?${value}` : '';
}
