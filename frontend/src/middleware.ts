import { defineMiddleware } from 'astro:middleware';
import type { APIContext } from 'astro';

/**
 * Security headers for every HTML/API/media response served by Astro.
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

function isHttps(context: APIContext): boolean {
  const forwarded = context.request.headers.get('x-forwarded-proto');
  if (forwarded) return forwarded.split(',')[0].trim().toLowerCase() === 'https';
  return context.url.protocol === 'https:';
}

export const onRequest = defineMiddleware(async (context, next) => {
  const response = await next();

  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  if (!import.meta.env.DEV && !response.headers.has('Content-Security-Policy')) {
    // Upstream may already send a stricter policy (e.g. the sandbox CSP for
    // admin-uploaded HTML/SVG files served as downloads); keep that one.
    response.headers.set('Content-Security-Policy', CONTENT_SECURITY_POLICY);
  }
  if (isHttps(context)) {
    response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  }
  return response;
});
