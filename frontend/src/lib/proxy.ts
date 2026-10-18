import type { APIContext } from 'astro';

function internalBase(): string {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  return env?.BLOG_API_INTERNAL_URL || 'http://127.0.0.1:8000';
}

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

/**
 * Proxy a browser request to FastAPI. Keeping this on the Astro origin means
 * cookies are first-party, there is no CORS configuration, and production only
 * exposes one port.
 */
export async function forwardToApi(
  context: APIContext,
  upstreamPrefix: '/api' | '/media',
): Promise<Response> {
  const { request, params, clientAddress } = context;
  const path = Array.isArray(params.path) ? params.path.join('/') : params.path || '';
  const search = new URL(request.url).search;
  const target = `${internalBase()}${upstreamPrefix}/${path}${search}`;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('content-length');
  headers.delete('connection');
  headers.set('x-blog-real-ip', clientAddress || 'unknown');
  const forwardedProto = request.headers.get('x-forwarded-proto');
  if (forwardedProto) headers.set('x-forwarded-proto', forwardedProto);

  let body: ArrayBuffer | undefined;
  if (!['GET', 'HEAD'].includes(request.method)) {
    body = await request.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      redirect: 'manual',
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    return new Response(JSON.stringify({ detail: '后端服务暂时不可用，请确认 FastAPI 已启动' }), {
      status: 502,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower)) return;
    if (lower === 'set-cookie') return;
    // Node's fetch transparently decompresses, so the upstream encoding and
    // length headers would be wrong if copied.
    if (lower === 'content-encoding' || lower === 'content-length') return;
    responseHeaders.append(key, value);
  });
  const cookies = upstream.headers.getSetCookie?.() ?? [];
  for (const cookie of cookies) responseHeaders.append('set-cookie', cookie);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}
