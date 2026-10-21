import { defineMiddleware } from 'astro:middleware';

/**
 * Page middleware: security headers, path-based pagination redirects (R2) and
 * public HTML cache validation (3.6.1).
 *
 * 3.0.0 splits response ownership by class: Astro owns page headers (this file),
 * FastAPI owns /api and /media headers, and the operator nginx owns TLS/HSTS.
 * Nothing is defined twice — in particular HSTS is intentionally NOT set here.
 *
 * Astro's dev server is only used locally (it exposes source files); the
 * Content-Security-Policy is therefore only emitted for production builds,
 * where Vite's HMR client is absent.
 */
const SECURITY_HEADERS: Record<string, string> = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'SAMEORIGIN',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
};

// The site uses inline boot scripts, inline theme CSS and the admin's custom
// CSS/head HTML, so 'unsafe-inline' is required for style/script. Everything
// else stays same-origin; images/audio may live on https CDNs.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'self'",
  "form-action 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "media-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "manifest-src 'self'",
].join('; ');

const ADMIN_PREFIX = /^\/admin(?:\/|$)/;
const PUBLIC_CACHE_CONTROL = 'public, max-age=0, must-revalidate';
const ADMIN_CACHE_CONTROL = 'no-store';
const TAXONOMY_PATH = /^\/(tags|categories)\/([^/]+)(?:\/page\/(\d+))?\/?$/;

/** Is this URL a public server-rendered HTML page (not an asset/API/admin)? */
function isPublicHtmlPath(pathname: string): boolean {
  if (ADMIN_PREFIX.test(pathname)) return false;
  if (pathname === '/api' || pathname.startsWith('/api/')) return false;
  if (pathname === '/media' || pathname.startsWith('/media/')) return false;
  if (pathname.startsWith('/_')) return false; // /_astro, /_image, ...
  if (pathname.startsWith('/@')) return false; // Vite dev internals
  if (pathname.startsWith('/src/')) return false;
  const lastSegment = pathname.slice(pathname.lastIndexOf('/') + 1);
  // rss.xml / sitemap.xml / robots.txt and any real asset keep their own headers.
  if (lastSegment.includes('.')) return false;
  return true;
}

/**
 * Legacy `?page=N` on a listing path. Taxonomy listings now have a path-based
 * URL (`/tags/{tag}/page/{n}`); any other public page has no equivalent, so the
 * query is simply dropped and the user lands on the canonical listing.
 */
function legacyPageRedirect(url: URL): string | null {
  if (!url.searchParams.has('page')) return null;
  const params = new URLSearchParams(url.searchParams);
  const raw = params.get('page') ?? '';
  params.delete('page');
  const suffix = params.toString() ? `?${params}` : '';
  const taxonomy = TAXONOMY_PATH.exec(url.pathname);
  if (taxonomy) {
    const base = `/${taxonomy[1]}/${taxonomy[2]}`;
    const target = Number(raw);
    if (!Number.isInteger(target) || target <= 1) return `${base}${suffix}`;
    return `${base}/page/${target}${suffix}`;
  }
  return `${url.pathname}${suffix}`;
}

/** `/tags/{tag}/page/1` is not canonical: 301 to the short listing path. */
function canonicalPageRedirect(url: URL): string | null {
  const taxonomy = TAXONOMY_PATH.exec(url.pathname);
  if (!taxonomy || !taxonomy[3]) return null;
  if (Number(taxonomy[3]) > 1) return null;
  const params = new URLSearchParams(url.searchParams);
  const suffix = params.toString() ? `?${params}` : '';
  return `/${taxonomy[1]}/${taxonomy[2]}${suffix}`;
}

/** Weak ETag over the rendered page text (SHA-1, hex). */
async function weakEtag(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text));
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
  return `W/"${hex}"`;
}

export const onRequest = defineMiddleware(async (context, next) => {
  const { request, url } = context;
  const publicHtml = isPublicHtmlPath(url.pathname);

  // R2: redirect legacy query pagination before rendering anything.
  if (request.method === 'GET' && publicHtml) {
    const target = canonicalPageRedirect(url) ?? legacyPageRedirect(url);
    if (target && target !== `${url.pathname}${url.search}`) {
      return context.redirect(target, 301);
    }
  }

  const response = await next();

  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  if (!import.meta.env.DEV && !response.headers.has('Content-Security-Policy')) {
    // Upstream may already send a stricter policy (e.g. the sandbox CSP for
    // admin-uploaded HTML/SVG files served as downloads); keep that one.
    response.headers.set('Content-Security-Policy', CONTENT_SECURITY_POLICY);
  }
  // The ingress may generate X-Request-ID (forwarded via the request header);
  // when it does not, generate one so page and API logs can be correlated.
  const supplied = request.headers.get('x-request-id')?.trim().slice(0, 128);
  response.headers.set('X-Request-ID', supplied || crypto.randomUUID().replaceAll('-', ''));

  // Admin pages must never be cached (session-dependent).
  if (ADMIN_PREFIX.test(url.pathname)) {
    response.headers.set('Cache-Control', ADMIN_CACHE_CONTROL);
    return response;
  }

  // Public GET HTML: weak ETag + revalidation, honouring If-None-Match with 304.
  if (
    request.method === 'GET' &&
    response.status === 200 &&
    publicHtml &&
    !response.headers.has('set-cookie') &&
    (response.headers.get('content-type') || '').includes('text/html')
  ) {
    const body = await response.clone().text();
    const etag = await weakEtag(body);
    response.headers.set('ETag', etag);
    response.headers.set('Cache-Control', PUBLIC_CACHE_CONTROL);
    response.headers.set('Vary', 'Accept-Encoding');
    if (request.headers.get('if-none-match') === etag) {
      const headers = new Headers(response.headers);
      // A 304 must not carry a body/representation length.
      headers.delete('content-length');
      headers.delete('content-type');
      return new Response(null, { status: 304, headers });
    }
  }

  return response;
});
