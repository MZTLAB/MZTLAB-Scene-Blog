import type { APIRoute } from 'astro';
import { getSite } from '../lib/api';
import { absoluteUrl } from '../lib/format';

export const GET: APIRoute = async ({ url }) => {
  let siteUrl = url.origin;
  try {
    const site = await getSite();
    siteUrl = site.settings.site_url || siteUrl;
  } catch {
    // Use the request origin.
  }
  const body = `User-agent: *
Allow: /
Disallow: /admin
Disallow: /api

Sitemap: ${absoluteUrl(siteUrl, '/sitemap.xml')}
`;
  return new Response(body, {
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
};
