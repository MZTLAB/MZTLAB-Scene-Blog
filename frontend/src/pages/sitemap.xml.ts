import type { APIRoute } from 'astro';
import { apiServer, getSite } from '../lib/api';
import { absoluteUrl } from '../lib/format';
import type { Gallery, Paginated, PostSummary } from '../types';

function escapeXml(value: string): string {
  return (value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

export const GET: APIRoute = async ({ url }) => {
  const site = await getSite();
  const base = (site.settings.site_url || url.origin).replace(/\/$/, '');
  const entries: Array<{ loc: string; lastmod?: string }> = [
    { loc: '/' },
    { loc: '/photos' },
    { loc: '/projects' },
    { loc: '/archive' },
  ];
  try {
    const archive = await apiServer<{ items: PostSummary[] }>('/api/archive');
    archive.items.forEach((post) => {
      entries.push({ loc: post.url, lastmod: post.updated_at });
    });
    const projects = await apiServer<Paginated<PostSummary>>('/api/projects?per_page=60');
    projects.items.forEach((project) => {
      entries.push({ loc: project.url, lastmod: project.updated_at });
    });
    const galleries = await apiServer<Paginated<Gallery>>('/api/galleries?per_page=60');
    galleries.items.forEach((gallery) => {
      entries.push({ loc: gallery.url, lastmod: gallery.updated_at });
    });
    const pages = await apiServer<{ items: PostSummary[] }>('/api/pages');
    pages.items.forEach((page) => {
      entries.push({ loc: page.url, lastmod: page.updated_at });
    });
  } catch {
    // Keep the static entries; the index route will still work.
  }
  site.categories
    .filter((category) => (category.count || 0) > 0)
    .forEach((category) => entries.push({ loc: `/categories/${category.slug}` }));
  site.tags
    .filter((tag) => (tag.count || 0) > 0)
    .forEach((tag) => entries.push({ loc: `/tags/${tag.slug}` }));

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries
  .map(
    (entry) =>
      `  <url><loc>${escapeXml(absoluteUrl(base, entry.loc))}</loc>${
        entry.lastmod ? `<lastmod>${entry.lastmod.slice(0, 10)}</lastmod>` : ''
      }</url>`,
  )
  .join('\n')}
</urlset>`;

  return new Response(body, {
    headers: {
      'content-type': 'application/xml; charset=utf-8',
      'cache-control': 'public, max-age=300',
    },
  });
};
