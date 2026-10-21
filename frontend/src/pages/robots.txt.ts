import type { APIRoute } from 'astro';
import { getSite } from '../lib/api';
import { absoluteUrl } from '../lib/format';

export const GET: APIRoute = async ({ url }) => {
  const site = await getSite();
  const siteUrl = site.settings.site.site_url || url.origin;
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
